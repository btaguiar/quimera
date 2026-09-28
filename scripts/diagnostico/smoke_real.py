"""Smoke real: roda a query base contra a tabela própria (quimera.dados build).

Custo: labels da tabela são grátis; a query lê a tabela própria (dezenas de
MB com filtro de CNAE; até ~4 GB estimados sem ele). Deletar depois do uso.
"""

import os

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "quimera-leads")
os.environ.setdefault("BQ_LOCATION", "US")

from quimera.filters import LeadFilters
from quimera.policy import PUBLIC
from quimera.query import (
    build_query,
    read_leads_snapshot,
    resolve_leads_tables,
    run_query,
)

tables = resolve_leads_tables()
print("snapshot:", read_leads_snapshot(tables))

spec = build_query(
    LeadFilters(ufs=["SP"], cnae_codes=["8630-5/04"], limit=5), PUBLIC, tables=tables
)
result = run_query(spec)
print("linhas:", len(result.rows))
print("bytes:", result.bytes_billed)
for row in result.rows[:5]:
    print(" ", row["cnpj"], "|", row["razao_social"], "|", row["municipio"], "|", row["porte"])
