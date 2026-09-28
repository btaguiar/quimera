"""Sonda alternativas para descobrir a última partição sem custo.

A) client.list_partitions — API de metadados, sem query.
B) SELECT MAX(data) com maximum_bytes_billed=1MB — se falhar, não cobra nada.
"""

import os

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "quimera-leads")
os.environ.setdefault("BQ_LOCATION", "US")

from google.cloud import bigquery

client = bigquery.Client(
    project=os.environ["GOOGLE_CLOUD_PROJECT"],
    location=os.environ["BQ_LOCATION"],
)

print("A) list_partitions:")
try:
    ids = client.list_partitions("basedosdados.br_me_cnpj.estabelecimentos")
    print("   ok:", sorted(ids)[-3:])
except Exception as exc:  # noqa: BLE001
    print("   falhou:", type(exc).__name__, str(exc)[:200])

print("B) MAX(data) com teto de 1MB:")
try:
    job = client.query(
        "SELECT MAX(data) AS latest FROM `basedosdados.br_me_cnpj.estabelecimentos`",
        job_config=bigquery.QueryJobConfig(maximum_bytes_billed=1024 * 1024),
    )
    rows = list(job.result())
    print("   ok:", rows[0]["latest"], "| bytes:", job.total_bytes_billed)
except Exception as exc:  # noqa: BLE001
    print("   falhou:", type(exc).__name__, str(exc)[:200])
