"""Depura a descoberta de snapshot: imprime SQL, linhas e estatísticas do job."""

import os
from datetime import date, timedelta

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "quimera-leads")
os.environ.setdefault("BQ_LOCATION", "US")

from google.cloud import bigquery

print("date.today():", date.today())
cutoff = date.today() - timedelta(days=120)
print("cutoff:", cutoff)

sql = "\nUNION ALL\n".join(
    f"SELECT '{t}' AS table_name, MAX(data) AS latest_partition\n"
    f"FROM `basedosdados.br_me_cnpj.{t}`\n"
    f"WHERE data >= DATE '{cutoff.isoformat()}'"
    for t in ("estabelecimentos", "empresas")
)
print("SQL:\n", sql)

client = bigquery.Client(project="quimera-leads", location="US")
job = client.query(
    sql, job_config=bigquery.QueryJobConfig(maximum_bytes_billed=8 * 1024**3)
)
rows = list(job.result())
for row in rows:
    print("row:", dict(row), "| tipos:", {k: type(v).__name__ for k, v in row.items()})
print("bytes_billed:", job.total_bytes_billed, "processed:", job.total_bytes_processed)
