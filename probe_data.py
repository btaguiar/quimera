"""Sonda o conteúdo real da coluna data (LIMIT = um bloco, custo desprezível)."""

import os

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "quimera-leads")
os.environ.setdefault("BQ_LOCATION", "US")

from google.cloud import bigquery

client = bigquery.Client(project="quimera-leads", location="US")

for table in ("estabelecimentos", "empresas"):
    job = client.query(f"SELECT data FROM `basedosdados.br_me_cnpj.{table}` LIMIT 5")
    rows = [r["data"] for r in job.result()]
    print(table, "->", rows, "| billed:", job.total_bytes_billed)
