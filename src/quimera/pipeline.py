"""Orquestração do fluxo: extract → cnae → policy → municípios → cep → query → score.

O pipeline nunca decide permissões: ``apply_policy`` é o único ponto que
diferencia público de privado, e roda sempre DEPOIS do LLM e ANTES da query.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable

from . import cnae
from .extract import DEFAULT_MODEL, extract_filters
from .filters import VALID_UFS, LeadFilters
from .policy import Policy, apply_policy
from .query import (
    PORTE_LABELS_DEMAIS,
    LeadsTables,
    QueryResult,
    build_query,
    read_leads_snapshot,
    resolve_cep_center,
    resolve_leads_tables,
    resolve_municipality_ids,
    run_query,
)
from .score import ICPConfig, score_lead
from .text import normalize_name

logger = logging.getLogger("quimera.pipeline")

# Preço on-demand do BigQuery (USD por TiB) — apenas estimativa exibida ao usuário.
BQ_USD_PER_TIB = 6.25

RAIO_PADRAO_KM = 5.0

# CEP escrito no pedido: 01310-100, 01310100 ou 01.310-100, sem colar em
# outro número (os dígitos de "capital acima de 9013101001" não contam).
_CEP_NO_PEDIDO = re.compile(r"(?<!\d)(\d{2})\.?(\d{3})-?(\d{3})(?!\d)")


def ceps_no_pedido(text: str) -> set[str]:
    """CEPs (8 dígitos) escritos literalmente no pedido."""
    return {"".join(m.groups()) for m in _CEP_NO_PEDIDO.finditer(text)}
# Medido em 2026-09-26: 91,2% dos ativos têm centroide de CEP.
AVISO_COBERTURA_RAIO = (
    "Busca por raio usa o centro do CEP de cada empresa; cerca de 9% dos "
    "estabelecimentos não têm coordenada e ficam de fora."
)

# UF colada no nome do município pela extração: "Extrema/MG", "Ouro (SC)",
# "Valença - BA", "Valença, BA". Sem separar, o nome não existe no diretório
# e o pedido para em "município não encontrado" (golden sintético, 2026-09-29).
_UF_COLADA = re.compile(r"^(.+?)\s*(?:[/,\-–]\s*|\(\s*)([A-Za-z]{2})\s*\)?$")
_SEPARADOR_UF = r"\s*(?:[/,\-–]\s*|\(\s*)"


def separar_uf_do_nome(nome: str) -> tuple[str, str | None]:
    """("Extrema/MG") -> ("Extrema", "MG"); nome sem UF volta intacto."""
    m = _UF_COLADA.match(nome.strip())
    if m and m.group(2).upper() in VALID_UFS:
        return m.group(1).strip(), m.group(2).upper()
    return nome, None


def ufs_apos_nome(request: str, nome: str) -> list[str]:
    """UFs escritas logo depois do município no pedido ("Valença, BA").

    A extração às vezes lê o município e deixa a UF de fora; com um homônimo
    ("Valença" existe na BA e no RJ), a consulta traria as duas cidades.
    ``resolve_municipality_ids`` só usa a UF se o município existir nela, o
    que descarta falsos positivos como "Campinas, se possível" (SE).
    """
    texto = normalize_name(request)
    alvo = re.escape(normalize_name(nome))
    achadas = re.findall(rf"{alvo}{_SEPARADOR_UF}([A-Z]{{2}})\b", texto)
    return [uf for uf in dict.fromkeys(achadas) if uf in VALID_UFS]


# Busca CNAE injetável: (query, k) -> [(codigo, descricao, similaridade)]
CnaeSearchFn = Callable[[str, int], list[tuple[str, str, float]]]


# Se a última seleção desta thread caiu no plano B. A avaliação separa essas
# falhas das de qualidade: com pedidos em paralelo, o 429 de cota do Gemini
# chegou a 20% dos casos (2026-09-29), coisa que o tráfego da demo não gera.
_selecao = threading.local()
# Uma nova tentativa antes do plano B. O corte por similaridade erra muito
# quando o embedding põe um vizinho em 1º ("material de construção" ->
# representantes comerciais; golden principal e2e_026, 2026-09-30), e
# nenhuma variante de corte testada ganhou dele em acerto. Cada chamada tem
# timeout de SELECT_TIMEOUT_MS, então o pior caso fica em ~8,5 s, não nos
# ~20 s das retentativas do SDK.
SELECT_TENTATIVAS = 2
SELECT_PAUSA_S = 0.5


def default_cnae_search(query: str, k: int) -> list[tuple[str, str, float]]:
    """Busca candidatos por embeddings e deixa o Gemini escolher entre eles.

    Só a busca punha vizinhos semânticos errados no filtro ("padarias" trazia
    chaveiros e atacado de pães); o LLM só escolhe entre os candidatos.
    """
    candidates = cnae.hybrid_candidates(query, cnae.SELECT_CANDIDATES)
    _selecao.fallback = False
    for tentativa in range(SELECT_TENTATIVAS):
        try:
            return cnae.select_codes(query, candidates)[:k]
        except Exception as exc:  # 429/5xx/resposta fora do contrato
            if tentativa + 1 < SELECT_TENTATIVAS:
                time.sleep(SELECT_PAUSA_S)
                continue
            logger.warning(
                "seleção de CNAE falhou (%s); usando corte por similaridade",
                type(exc).__name__,
            )
    _selecao.fallback = True
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
    # Tempo por etapa (extract, cnae, municipios, cep, snapshot, query, score).
    timings_ms: dict[str, float] = field(default_factory=dict)
    model: str = ""
    policy: str = ""
    request_normalized: str = ""
    # Limitações dos dados que afetaram ESTE resultado, em pt-BR.
    warnings: list[str] = field(default_factory=list)
    # SQL parametrizado executado (vazio quando a consulta não roda).
    query_sql: str = ""
    # A seleção de CNAE falhou (429/timeout) e valeu o corte por similaridade.
    cnae_fallback: bool = False

    def to_dict(self) -> dict:
        return {
            "refused": self.refused,
            "refusal_reason": self.refusal_reason,
            "filters": self.filters.model_dump() if self.filters else None,
            "cnae_matches": [list(m) for m in self.cnae_matches],
            "cnae_fallback": self.cnae_fallback,
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
            "query_sql": self.query_sql,
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
    limit: int | None = None,
) -> PipelineResult:
    """Executa o fluxo completo e devolve o resultado explicável.

    ``limit`` substitui o nº de linhas pedido pelo LLM (a avaliação usa para
    conferir mais empresas por caso); o teto da policy continua valendo.
    """
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
    cnae_fallback = False
    if filters.cnae_query:
        _selecao.fallback = False
        with _stage(timings, "cnae"):
            cnae_matches = cnae_search(filters.cnae_query, cnae_top_k)
        cnae_fallback = getattr(_selecao, "fallback", False)
        filters = filters.model_copy(
            update={"cnae_codes": [c for c, _, _ in cnae_matches]}
        )

    # 2. Limites da policy aplicados DEPOIS do LLM e ANTES da query.
    # Regimes pedidos ANTES da policy: no público o pedido "só MEI" fica vazio
    # e a query ignoraria o regime — a etapa cep detecta e avisa.
    regimes_pedidos = list(filters.regimes)
    if limit is not None:
        filters = filters.model_copy(update={"limit": limit})
    filters = apply_policy(filters, policy)

    warnings: list[str] = []
    municipio_resolution: dict[str, list[str]] = {}

    def _early_stop(log_message: str) -> PipelineResult:
        """Parada sem consulta: filtros, avisos e timings do que ficou resolvido."""
        stopped = PipelineResult(
            refused=False,
            filters=filters,
            cnae_matches=cnae_matches,
            cnae_fallback=cnae_fallback,
            municipio_resolution=municipio_resolution,
            model=resolved_model,
            policy=policy.name,
            request_normalized=request_normalized,
            warnings=warnings,
        )
        stopped.latency_ms = (time.perf_counter() - started) * 1000
        stopped.timings_ms = timings
        logger.info(log_message)
        return stopped

    if filters.cnae_query and not cnae_matches:
        # Sem CNAE, a consulta devolveria empresas de qualquer atividade como
        # se fossem da atividade pedida.
        warnings.append(
            f"Nenhuma atividade CNAE corresponde a '{filters.cnae_query}'; "
            "reformule a atividade do pedido."
        )
        return _early_stop(
            f"nenhum CNAE para {filters.cnae_query!r}; consulta não executada"
        )
    if policy.require_activity and not filters.cnae_codes:
        warnings.append(
            "Informe a atividade das empresas (ex.: 'padarias em Santo André'): "
            "sem atividade, a consulta varreria todas as empresas da região e "
            "não é executada nesta demo."
        )
        return _early_stop("pedido sem atividade na policy; consulta não executada")
    if PORTE_LABELS_DEMAIS.intersection(filters.portes):
        warnings.append(
            "O cadastro não distingue porte médio de grande: ambos vêm do porte "
            "'Demais' da Receita (tudo acima de pequeno porte), restrito a "
            "entidades empresariais."
        )

    # 3. Nome de município -> códigos IBGE por lookup no diretório.
    if filters.municipio_names:
        nomes: list[str] = []
        ufs_por_nome: dict[str, list[str]] = {}
        for nome in filters.municipio_names:
            limpo, uf = separar_uf_do_nome(nome)
            nomes.append(limpo)
            if uf:
                ufs_por_nome[limpo] = [uf]
            elif not filters.ufs and (escritas := ufs_apos_nome(request, limpo)):
                ufs_por_nome[limpo] = escritas
        nomes = list(dict.fromkeys(nomes))
        filters = filters.model_copy(update={"municipio_names": nomes})
        with _stage(timings, "municipios"):
            municipio_resolution = resolve_municipality_ids(
                nomes,
                ufs=filters.ufs or None,
                client=bq_client,
                ufs_por_nome=ufs_por_nome,
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
            return _early_stop("nenhum município resolvido; consulta não executada")
        filters = filters.model_copy(
            update={
                "municipio_ids": list(
                    dict.fromkeys(
                        mid for ids in municipio_resolution.values() for mid in ids
                    )
                )
            }
        )

    # 4. Sinais do próprio cadastro (Onda 1): centro do raio por CEP, bairros
    #    e regimes. Roda DEPOIS dos municípios (bairros dependem de
    #    municipio_names) e da policy (regimes removidos no público), mas
    #    ANTES da consulta.
    tables = tables or resolve_leads_tables()
    if filters.cep_centro and filters.cep_centro not in ceps_no_pedido(request):
        # O LLM inventava CEP ("centro de Curitiba" virava 80000000) e o
        # pedido voltava vazio. Como no CNAE, o código não vem do modelo:
        # só vale o CEP escrito no pedido. Sem ele, o raio cai no aviso abaixo.
        warnings.append(
            f"CEP {filters.cep_centro} não aparece no pedido e foi descartado; "
            "escreva o CEP de referência para buscar por proximidade."
        )
        filters = filters.model_copy(update={"cep_centro": None})
    raio_sem_cep = filters.raio_km is not None and not filters.cep_centro
    bairros_sem_municipio = bool(filters.bairros) and not filters.municipio_names
    mei_removido = "mei" in regimes_pedidos and "mei" not in filters.regimes
    so_mei = bool(regimes_pedidos) and not filters.regimes
    centro: tuple[float, float] | None = None
    if filters.cep_centro or raio_sem_cep or bairros_sem_municipio or mei_removido:
        with _stage(timings, "cep"):
            if so_mei:
                # Sem isso, a consulta devolveria empresas de qualquer regime
                # como se fossem MEI.
                warnings.append(
                    "O pedido pede apenas MEI, que este ambiente não inclui; "
                    "a consulta traria empresas de qualquer regime tributário. "
                    "Reformule o pedido."
                )
                return _early_stop("pedido só MEI; consulta não executada")
            if mei_removido:
                warnings.append(
                    "MEI removido dos regimes pelo modo público; a consulta "
                    "segue com os regimes restantes."
                )
            if raio_sem_cep:
                warnings.append(
                    "Raio ignorado: informe um CEP de referência para buscar "
                    "por proximidade."
                )
                filters = filters.model_copy(update={"raio_km": None})
            if bairros_sem_municipio:
                # Bairros se repetem entre cidades: sem município, o filtro
                # casaria nomes em todo o país.
                warnings.append(
                    "Filtro de bairros ignorado: informe também o município."
                )
                filters = filters.model_copy(update={"bairros": []})
            if filters.cep_centro:
                usar_raio_padrao = filters.raio_km is None
                centro = resolve_cep_center(
                    filters.cep_centro, tables=tables, client=bq_client
                )
                if centro is None:
                    # Rodar sem o raio devolveria empresas de qualquer
                    # distância como se estivessem perto.
                    warnings.append(
                        f"CEP {filters.cep_centro} não encontrado no diretório; "
                        "reformule o pedido."
                    )
                    return _early_stop(
                        f"CEP {filters.cep_centro} sem centroide; "
                        "consulta não executada"
                    )
                if usar_raio_padrao:
                    filters = filters.model_copy(update={"raio_km": RAIO_PADRAO_KM})
                    warnings.append(
                        f"CEP sem raio: usando o padrão de {RAIO_PADRAO_KM:g} km."
                    )
                warnings.append(AVISO_COBERTURA_RAIO)

    # 5. Tabela própria (snapshot lido dos labels, sem custo) + query
    #    parametrizada com teto de bytes.
    with _stage(timings, "snapshot"):
        snapshots = read_leads_snapshot(
            tables, client=bq_client, require_contatos=bool(policy.contact_fields)
        )
    spec = build_query(filters, policy, tables=tables, icp=icp, centro=centro)
    with _stage(timings, "query"):
        query_result: QueryResult = run_query(
            spec, client=bq_client, max_bytes_billed=max_bytes_billed
        )

    # 6. Score explicável e ranking.
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
        cnae_fallback=cnae_fallback,
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
        query_sql=spec.sql,
    )
    result.latency_ms = (time.perf_counter() - started) * 1000
    result.timings_ms = timings
    logger.info("execução concluída: %s", result.log_record())
    return result
