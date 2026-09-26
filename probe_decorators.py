"""Sonda decoradores de partição via list_rows (sem SQL, sem scan)."""

import os

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "quimera-leads")
os.environ.setdefault("BQ_LOCATION", "US")

from google.cloud import bigquery

client = bigquery.Client(project="quimera-leads", location="US")

for decorator in ("$20260712", "$20260614", "$20260510", "$20240719", "$20240116"):
    for table in ("estabelecimentos", "empresas"):
        try:
            rows = client.list_rows(
                f"basedosdados.br_me_cnpj.{table}{decorator}",
                selected_fields=[bigquery.SchemaField("data", "DATE")],
                max_results=2,
            )
            values = [r["data"] for r in rows]
            print(f"{table}{decorator}: {values}")
        except Exception as exc:  # noqa: BLE001
            print(f"{table}{decorator}: {type(exc).__name__} {str(exc)[:120]}")
