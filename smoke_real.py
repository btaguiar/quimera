"""Smoke real: resolve snapshots e roda a query base contra o BigQuery.

Custo: INFORMATION_SCHEMA é grátis; a query lê 1 snapshot com teto de 5 GiB
(~US$ 0,01 no pior caso). Deletar depois do uso.
"""

import os

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "quimera-leads")
os.environ.setdefault("BQ_LOCATION", "US")

from quimera.filters import LeadFilters
from quimera.policy import PUBLIC
from quimera.query import build_query, resolve_latest_snapshots, run_query

snapshots = resolve_latest_snapshots()
print("snapshots:", snapshots)

spec = build_query(LeadFilters(ufs=["SP"], limit=5), PUBLIC, snapshots=snapshots)
result = run_query(spec)
print("linhas:", len(result.rows))
print("bytes:", result.bytes_processed)
for row in result.rows[:5]:
    print(" ", row["razao_social"], "|", row["municipio"], "|", row["porte"])
