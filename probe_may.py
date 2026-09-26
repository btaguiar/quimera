"""Sonda MAX(data) desde 2026-05-01 — resolve a discrepância com schema.md."""

import os

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "quimera-leads")
os.environ.setdefault("BQ_LOCATION", "US")

from google.cloud import bigquery

client = bigquery.Client(project="quimera-leads", location="US")
sql = "\nUNION ALL\n".join(
    f"SELECT '{t}' AS table_name, MAX(data) AS latest_partition, COUNT(1) AS n\n"
    f"FROM `basedosdados.br_me_cnpj.{t}`\n"
    f"WHERE data >= DATE '2026-05-01' AND data < DATE '2026-06-01'"
    for t in ("estabelecimentos", "empresas")
)
job = client.query(
    sql, job_config=bigquery.QueryJobConfig(maximum_bytes_billed=8 * 1024**3)
)
for row in job.result():
    print(dict(row))
print("billed:", job.total_bytes_billed)
