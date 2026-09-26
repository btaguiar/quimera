"""Sonda o custo do build (Onda 1) sem executar nada.

Cada SQL roda com ``maximum_bytes_billed=1``: o BigQuery recusa ANTES de
executar, sem cobrar, e informa "N or higher required" — N é o custo do build.
Portão da Onda 1: nenhum build real antes de N <= 25 GB
(docs/superpowers/plans/2026-09-26-onda1-sinais-cadastro.md, Task 1).

Os snapshots vêm dos labels da tabela própria (leitura de metadados, sem custo),
não da descoberta por consulta (que lê GBs da coluna ``data``).

Uso:
    python probe_build_onda1.py                 # build_leads_sql (+ ceps, se existir)
    python probe_build_onda1.py --sql arq.sql   # SQL arbitrário ({est}/{emp} = snapshots)
"""

from __future__ import annotations

import argparse
import os
import sys

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "quimera-leads")
os.environ.setdefault("BQ_LOCATION", "US")

from quimera import dados  # noqa: E402
from quimera.query import (  # noqa: E402
    _default_client,
    _required_bytes,
    read_leads_snapshot,
    resolve_leads_tables,
)

GATE_BYTES = 25 * 10**9
DESTINO = "_sonda_onda1"  # nunca criado: a recusa acontece antes de executar


def probe(sql: str, *, client) -> int | None:
    """Bytes exigidos pelo SQL (None se o erro não informar)."""
    from google.cloud import bigquery

    try:
        client.query(
            sql, job_config=bigquery.QueryJobConfig(maximum_bytes_billed=1)
        ).result()
    except Exception as exc:  # recusa pelo teto é o resultado esperado
        required = _required_bytes(exc)
        if required is None:
            raise
        return required
    raise RuntimeError("A sonda executou: o teto de 1 byte não foi aplicado.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sql", help="arquivo com SQL ({est}/{emp} = snapshots)")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # console do Windows (cp1252)

    client = _default_client()
    tables = resolve_leads_tables()
    snapshots = read_leads_snapshot(tables, client=client)
    project, dataset, _ = tables.leads.split(".")
    destino = f"{project}.{dataset}.{DESTINO}"

    sqls: dict[str, str] = {}
    if args.sql:
        with open(args.sql, encoding="utf-8") as fh:
            sqls[args.sql] = fh.read().format(
                est=snapshots["estabelecimentos"].isoformat(),
                emp=snapshots["empresas"].isoformat(),
                destino=destino,
            )
    else:
        sqls["build_leads_sql"] = dados.build_leads_sql(destino, snapshots)
        if hasattr(dados, "build_ceps_sql"):  # Task 2
            sqls["build_ceps_sql"] = dados.build_ceps_sql(destino + "_ceps")

    print(
        "snapshots:",
        ", ".join(f"{s}={d.isoformat()}" for s, d in sorted(snapshots.items())),
    )
    total = 0
    for name, sql in sqls.items():
        required = probe(sql, client=client)
        total += required or 0
        print(f"{name}: {required / 1e9:.2f} GB" if required else f"{name}: ?")
    ok = total <= GATE_BYTES
    print(
        f"total: {total / 1e9:.2f} GB (portão {GATE_BYTES / 1e9:.0f} GB)"
        f" -> {'OK' if ok else 'ACIMA DO PORTÃO'}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
