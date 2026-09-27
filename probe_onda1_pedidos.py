"""Mede no real o custo por pedido com os filtros da Onda 1 (Task 10).

Cada pedido roda duas vezes: (1) sonda com ``maximum_bytes_billed=1`` —
recusada ANTES de executar, sem custo, informa os bytes exigidos
(estimativa pré-execução, que só enxerga poda de partição); (2) execução
real com ``run_query`` (bytes cobrados + duração).

Pedidos novos (um por filtro da Onda 1) e três pedidos antigos, para
comparar com a tabela "Custo medido por pedido" de docs/schema.md (aceite
do plano: pedidos antigos sem piora acima de 20%).

Uso:
    python probe_onda1_pedidos.py              # custos (sonda + execução real)
    python probe_onda1_pedidos.py --paridade   # bairro x bairro_norm (1000 pares)
"""

from __future__ import annotations

import argparse
import os
import sys
import time

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "quimera-leads")
os.environ.setdefault("BQ_LOCATION", "US")

from quimera.filters import LeadFilters  # noqa: E402
from quimera.policy import PUBLIC  # noqa: E402
from quimera.query import (  # noqa: E402
    _default_client,
    _required_bytes,
    build_query,
    resolve_cep_center,
    resolve_leads_tables,
    resolve_municipality_ids,
    run_query,
)
from quimera.text import normalize_name  # noqa: E402

PROBE_MAX_BYTES = 1  # recusa sem custo — o número exigido é a estimativa
# "só UF" estimava 4,03 GB antes da Onda 1 (docs/schema.md); 6 GiB dá folga.
RUN_MAX_BYTES = 6 * 1024**3
PARIDADE_MAX_BYTES = 1 * 1024**3  # 2 colunas de string da tabela própria


def _municipio(nome: str, uf: str) -> list[str]:
    ids = resolve_municipality_ids([nome], ufs=[uf])
    if not ids or not ids[nome]:
        raise RuntimeError(f"Município não resolvido: {nome}/{uf}")
    return ids[nome]


def _scenarios() -> list[tuple[str, LeadFilters, tuple[float, float] | None]]:
    """(rótulo, filtros, centro do raio) — centro resolvido fora do LLM."""
    return [
        (
            "ANTIGO odontologia (div. 86) + UF + municipio",
            LeadFilters(
                ufs=["SP"],
                municipio_ids=_municipio("São Paulo", "SP"),
                cnae_codes=["8630-5/04"],
                limit=5,
            ),
            None,
        ),
        (
            "ANTIGO varejo (div. 47) + UF",
            LeadFilters(ufs=["SP"], cnae_codes=["4711-3/01", "4711-3/02"], limit=5),
            None,
        ),
        (
            "ANTIGO so UF (sem CNAE)",
            LeadFilters(ufs=["SP"], limit=5),
            None,
        ),
        (
            "NOVO rede: academias na capital SP, >= 5 unidades",
            LeadFilters(
                ufs=["SP"],
                municipio_ids=_municipio("São Paulo", "SP"),
                cnae_codes=["9313-1/00"],
                min_estabelecimentos=5,
                limit=5,
            ),
            None,
        ),
        (
            "NOVO regime: material de construcao Goiania, fora_simples",
            LeadFilters(
                ufs=["GO"],
                municipio_ids=_municipio("Goiânia", "GO"),
                cnae_codes=["4744-0/01", "4744-0/05", "4744-0/99"],
                regimes=["fora_simples"],
                limit=5,
            ),
            None,
        ),
        (
            "NOVO bairro: restaurantes em Pinheiros, Sao Paulo",
            LeadFilters(
                ufs=["SP"],
                municipio_ids=_municipio("São Paulo", "SP"),
                cnae_codes=["5611-2/01"],
                bairros=["Pinheiros"],
                limit=5,
            ),
            None,
        ),
        (
            "NOVO raio: odontologia a 3 km do CEP 01310-100",
            LeadFilters(
                cnae_codes=["8630-5/04"], cep_centro="01310100", raio_km=3, limit=5
            ),
            resolve_cep_center("01310100", tables=resolve_leads_tables()),
        ),
        (
            "NOVO dominio proprio: clinicas medicas em Campinas",
            LeadFilters(
                ufs=["SP"],
                municipio_ids=_municipio("Campinas", "SP"),
                cnae_codes=["8630-5/01", "8630-5/02", "8630-5/03"],
                com_dominio_proprio=True,
                limit=5,
            ),
            None,
        ),
    ]


def _estimate(spec, *, client) -> int | None:
    """Bytes exigidos (recusa do teto de 1 byte, sem custo)."""
    from google.cloud import bigquery
    from quimera.query import _to_bq_parameters

    try:
        client.query(
            spec.sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=_to_bq_parameters(spec.params),
                maximum_bytes_billed=PROBE_MAX_BYTES,
            ),
        ).result()
    except Exception as exc:
        required = _required_bytes(exc)
        if required is None:
            raise
        return required
    raise RuntimeError("A sonda executou: o teto de 1 byte não foi aplicado.")


def custos() -> int:
    client = _default_client()
    tables = resolve_leads_tables()
    print(f"tabela: {tables.leads}")
    total_billed = 0
    print(f"{'pedido':48} {'estimado':>12} {'cobrado':>12} {'linhas':>7} {'dur':>6}")
    for label, filters, centro in _scenarios():
        spec = build_query(filters, PUBLIC, tables=tables, centro=centro)
        estimate = _estimate(spec, client=client)
        started = time.perf_counter()
        result = run_query(spec, max_bytes_billed=RUN_MAX_BYTES)
        dur = time.perf_counter() - started
        total_billed += result.bytes_billed
        print(
            f"{label:48} {estimate / 1e6:>10.1f} MB"
            f" {result.bytes_billed / 1e6:>10.1f} MB"
            f" {len(result.rows):>7} {dur:>5.1f}s"
        )
    print(
        f"total cobrado: {total_billed / 1e9:.2f} GB"
        f" (~US$ {total_billed / 2**40 * 5:.4f})"
    )
    return 0


def paridade() -> int:
    """Amostra 1.000 pares (bairro, bairro_norm) e confere normalize_name."""
    from google.cloud import bigquery

    client = _default_client()
    tables = resolve_leads_tables()
    sql = (
        f"SELECT bairro, bairro_norm FROM `{tables.leads}`\n"
        "WHERE bairro IS NOT NULL AND bairro_norm IS NOT NULL\n"
        "GROUP BY bairro, bairro_norm LIMIT 1000"
    )
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(maximum_bytes_billed=PARIDADE_MAX_BYTES),
    )
    rows = [(r["bairro"], r["bairro_norm"]) for r in job.result()]
    divergent = [(b, n) for b, n in rows if normalize_name(b) != n]
    ratio = len(divergent) / len(rows) if rows else 0.0
    print(f"pares amostrados: {len(rows)} (billed={job.total_bytes_billed or 0:,})")
    print(f"divergencias: {len(divergent)} ({ratio:.3%})")
    for bairro, norm in divergent[:10]:
        print(f"  {bairro!r} -> {norm!r} (python: {normalize_name(bairro)!r})")
    return 0 if ratio <= 0.001 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--paridade", action="store_true", help="só a paridade bairro/bairro_norm"
    )
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # console do Windows (cp1252)
    return paridade() if args.paridade else custos()


if __name__ == "__main__":
    sys.exit(main())
