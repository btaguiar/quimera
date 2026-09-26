"""Orquestração do fluxo: extract → cnae → policy → municípios → query → score.

O pipeline nunca decide permissões: ``apply_policy`` é o único ponto que
diferencia público de privado, e roda sempre DEPOIS do LLM e ANTES da query.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable

from . import cnae
from .extract import DEFAULT_MODEL, extract_filters
from .filters import LeadFilters
from .policy import Policy, apply_policy
from .query import (
    PORTE_LABELS_DEMAIS,
    LeadsTables,
    QueryResult,
    build_query,
    read_leads_snapshot,
    resolve_leads_tables,
    resolve_municipality_ids,
    run_query,
)
from .score import ICPConfig, score_lead

logger = logging.getLogger("quimera.pipeline")

# Preço on-demand do BigQuery (USD por TiB) — apenas estimativa exibida ao usuário.
BQ_USD_PER_TIB = 6.25

# Busca CNAE injetável: (query, k) -> [(codigo, descricao, similaridade)]
CnaeSearchFn = Callable[[str, int], list[tuple[str, str, float]]]


def default_cnae_search(query: str, k: int) -> list[tuple[str, str, float]]:
    """Busca candidatos por embeddings e deixa o Gemini escolher entre eles.

    Só a busca punha vizinhos semânticos errados no filtro ("padarias" trazia
    chaveiros e atacado de pães); o LLM só escolhe entre os candidatos.
    """
    candidates = cnae.search(query, cnae.SELECT_CANDIDATES)
    try:
        return cnae.select_codes(query, candidates)[:k]
    except Exception as exc:  # 429/timeout: não segura o pedido por ~20 s
        logger.warning(
            "seleção de CNAE falhou (%s); usando corte por similaridade",
            type(exc).__name__,
        )
        return cnae.fallback_codes(candidates)[:k]


@dataclass
class PipelineResult:
    """Resultado completo de uma execução, com explicação de cada etapa."""

    refused: bool = False
    refusal_reason: str | None = None
    filters: LeadFilters | None = None
    cnae_matches: list[tuple[str, str, float]] = field(default_factory=list)
    municipio_resolution: dict[str, list[str]] = field(default_factory=dict)
    snapshot: dict[str, str] = field(default_factory=dict)
    rows: list[dict] = field(default_factory=list)
    bytes_processed: int = 0
    bytes_billed: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: float = 0.0
    # Tempo por etapa (extract, cnae, municipios, snapshot, query, score).
    timings_ms: dict[str, float] = field(default_factory=dict)
    model: str = ""
    policy: str = ""
    request_normalized: str = ""
    # Limitações dos dados que afetaram ESTE resultado, em pt-BR.
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "refused": self.refused,
            "refusal_reason": self.refusal_reason,
            "filters": self.filters.model_dump() if self.filters else None,
            "cnae_matches": [list(m) for m in self.cnae_matches],
            "municipio_resolution": self.municipio_resolution,
            "snapshot": self.snapshot,
            "rows": self.rows,
            "bytes_processed": self.bytes_processed,
            "bytes_billed": self.bytes_billed,
            "estimated_cost_usd": self.estimated_cost_usd,
            "latency_ms": self.latency_ms,
            "timings_ms": self.timings_ms,
            "model": self.model,
            "policy": self.policy,
            "request_normalized": self.request_normalized,
            "warnings": self.warnings,
        }

    def log_record(self) -> dict:
        """Registro de execução sem dado pessoal (o pedido já passou pela recusa)."""
        return {
            "request": self.request_normalized,
            "policy": self.policy,
            "filters": self.filters.model_dump() if self.filters else None,
            "n_rows": len(self.rows),
            "bytes": self.bytes_billed,
            "estimated_cost_usd": self.estimated_cost_usd,
            "latency_ms": round(self.latency_ms, 1),
            "timings_ms": self.timings_ms,
            "model": self.model,
        }


@contextmanager
def _stage(timings: dict[str, float], name: str):
    started = time.perf_counter()
    try:
        yield
    finally:
        timings[name] = round((time.perf_counter() - started) * 1000, 1)


def warmup(tables: LeadsTables | None = None) -> dict[str, float]:
    """Prepara no processo o que o 1º pedido pagaria (ms por item).

    Medido em 2026-09-26, máquina local: cliente BigQuery 9,9 s, cliente
    Gemini 2,1 s, 1ª chamada de embedding 2,3 s (depois 0,95 s), diretório
    de municípios 2,0 s — o 1º pedido levava 39 s e os seguintes 4-5 s.
    Falhas só vão para o log: o pedido real tenta de novo e reporta o erro.
    """
    from . import extract, query

    tables = tables or resolve_leads_tables()
    steps: list[tuple[str, Callable[[], object]]] = [
        ("cnae_index", cnae.load_index),
        ("gemini", extract._default_client),
        ("embedding", lambda: cnae.vertex_embedder().embed(["aquecimento"])),
        ("bigquery", query._default_client),
        ("municipios", query._default_municipality_directory),
        ("snapshot", lambda: read_leads_snapshot(tables)),
    ]
    timings: dict[str, float] = {}
    for name, step in steps:
        with _stage(timings, name):
            try:
                step()
            except Exception:  # aquecimento nunca derruba o processo
                logger.exception("aquecimento falhou em %s", name)
    logger.info("aquecimento concluído: %s", timings)
    return timings


def _resolve_model(model: str | None) -> str:
    return model or os.environ.get("EXTRACT_MODEL", DEFAULT_MODEL)


def run(
    request: str,
    policy: Policy,
    *,
    model: str | None = None,
    cnae_top_k: int = 5,
    icp: ICPConfig | None = None,
    extract_client: Any | None = None,
    cnae_search: CnaeSearchFn | None = None,
    bq_client: Any | None = None,
    max_bytes_billed: int | None = None,
    tables: LeadsTables | None = None,
) -> PipelineResult:
    """Executa o fluxo completo e devolve o resultado explicável."""
    started = time.perf_counter()
    icp = icp or ICPConfig()
    cnae_search = cnae_search or default_cnae_search
    resolved_model = _resolve_model(model)
    request_normalized = " ".join(request.split())

    timings: dict[str, float] = {}
    with _stage(timings, "extract"):
        extraction = extract_filters(
            request, policy, model=model, client=extract_client
        )
    if extraction.refused:
        result = PipelineResult(
            refused=True,
            refusal_reason=extraction.refusal_reason,
            model=resolved_model,
            policy=policy.name,
            request_normalized=request_normalized,
        )
        result.latency_ms = (time.perf_counter() - started) * 1000
        result.timings_ms = timings
        logger.info("pedido recusado: %s", extraction.refusal_reason)
        return result

    filters = extraction.filters

    # 1. cnae_query -> códigos CNAE por embeddings (o LLM nunca inventa código).
    cnae_matches: list[tuple[str, str, float]] = []
    if filters.cnae_query:
        with _stage(timings, "cnae"):
            cnae_matches = cnae_search(filters.cnae_query, cnae_top_k)
        filters = filters.model_copy(
            update={"cnae_codes": [c for c, _, _ in cnae_matches]}
        )

    # 2. Limites da policy aplicados DEPOIS do LLM e ANTES da query.
    filters = apply_policy(filters, policy)

    warnings: list[str] = []
    if filters.cnae_query and not cnae_matches:
        # Sem CNAE, a consulta devolveria empresas de qualquer atividade como
        # se fossem da atividade pedida.
        warnings.append(
            f"Nenhuma atividade CNAE corresponde a '{filters.cnae_query}'; "
            "reformule a atividade do pedido."
        )
        result = PipelineResult(
            refused=False,
            filters=filters,
            model=resolved_model,
            policy=policy.name,
            request_normalized=request_normalized,
            warnings=warnings,
        )
        result.latency_ms = (time.perf_counter() - started) * 1000
        result.timings_ms = timings
        logger.info("nenhum CNAE para %r; consulta não executada", filters.cnae_query)
        return result
    if PORTE_LABELS_DEMAIS.intersection(filters.portes):
        warnings.append(
            "O cadastro não distingue porte médio de grande: ambos vêm do porte "
            "'Demais' da Receita (tudo acima de pequeno porte), restrito a "
            "entidades empresariais."
        )

    # 3. Nome de município -> códigos IBGE por lookup no diretório.
    municipio_resolution: dict[str, list[str]] = {}
    if filters.municipio_names:
        with _stage(timings, "municipios"):
            municipio_resolution = resolve_municipality_ids(
                filters.municipio_names, ufs=filters.ufs or None, client=bq_client
            )
        unresolved = [
            name for name in filters.municipio_names if name not in municipio_resolution
        ]
        if unresolved:
            warnings.append(
                "Município não encontrado no diretório do IBGE: "
                + ", ".join(unresolved)
                + "."
            )
        for name, ids in municipio_resolution.items():
            if len(ids) > 1:
                warnings.append(
                    f"'{name}' existe em {len(ids)} municípios de UFs diferentes; "
                    "todos foram incluídos. Informe a UF para restringir."
                )
        if not municipio_resolution:
            # Sem nenhum município resolvido, rodar a query sem esse filtro
            # devolveria empresas de qualquer lugar como se fossem do local pedido.
            result = PipelineResult(
                refused=False,
                filters=filters,
                cnae_matches=cnae_matches,
                model=resolved_model,
                policy=policy.name,
                request_normalized=request_normalized,
                warnings=warnings,
            )
            result.latency_ms = (time.perf_counter() - started) * 1000
            result.timings_ms = timings
            logger.info("nenhum município resolvido; consulta não executada")
            return result
        filters = filters.model_copy(
            update={
                "municipio_ids": list(
                    dict.fromkeys(
                        mid for ids in municipio_resolution.values() for mid in ids
                    )
                )
            }
        )

    # 4. Tabela própria (snapshot lido dos labels, sem custo) + query
    #    parametrizada com teto de bytes.
    tables = tables or resolve_leads_tables()
    with _stage(timings, "snapshot"):
        snapshots = read_leads_snapshot(
            tables, client=bq_client, require_contatos=bool(policy.contact_fields)
        )
    spec = build_query(filters, policy, tables=tables, icp=icp)
    with _stage(timings, "query"):
        query_result: QueryResult = run_query(
            spec, client=bq_client, max_bytes_billed=max_bytes_billed
        )

    # 5. Score explicável e ranking.
    rows: list[dict] = []
    with _stage(timings, "score"):
        for row in query_result.rows:
            score, motivos = score_lead(row, icp)
            rows.append({**row, "score": score, "motivos_score": motivos})
        rows.sort(key=lambda r: r["score"], reverse=True)

    result = PipelineResult(
        refused=False,
        filters=filters,
        cnae_matches=cnae_matches,
        municipio_resolution=municipio_resolution,
        snapshot={table: snap.isoformat() for table, snap in snapshots.items()},
        rows=rows,
        bytes_processed=query_result.bytes_processed,
        bytes_billed=query_result.bytes_billed,
        estimated_cost_usd=round(
            query_result.bytes_billed / 1024**4 * BQ_USD_PER_TIB, 10
        ),
        model=resolved_model,
        policy=policy.name,
        request_normalized=request_normalized,
        warnings=warnings,
    )
    result.latency_ms = (time.perf_counter() - started) * 1000
    result.timings_ms = timings
    logger.info("execução concluída: %s", result.log_record())
    return result
