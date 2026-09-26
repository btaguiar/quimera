"""Fakes compartilhados entre os testes (sem rede, sem GCP)."""

from __future__ import annotations


class FakeGenaiClient:
    """Cliente genai falso: devolve resposta fixa e registra chamadas."""

    def __init__(self, response):
        self._response = response
        self.calls = []

    class _Models:
        def __init__(self, outer):
            self._outer = outer

        def generate_content(self, **kwargs):
            self._outer.calls.append(kwargs)
            return self._outer._response

    @property
    def models(self):
        return self._Models(self)


class FakeJob:
    def __init__(self, total_bytes_processed, rows=None):
        self.total_bytes_processed = total_bytes_processed
        self.total_bytes_billed = total_bytes_processed
        self._rows = rows or []

    def result(self):
        return self._rows


class FakePipelineBQ:
    """Cliente BigQuery falso para o pipeline completo.

    Sequência de chamadas (todas com client.query):
    1. job_config com MAX(data)     -> descoberta de snapshot (janela, com teto);
    2. job_config ausente           -> consulta ao diretório de municípios;
    3. job_config com dry_run=True  -> estimativa de bytes;
    4. job_config de execução        -> consulta de leads (registrada em ``executed``).
    """

    def __init__(
        self,
        municipio_rows=None,
        lead_rows=None,
        dry_run_bytes=1000,
        snapshot_rows=None,
    ):
        self.municipio_rows = municipio_rows or []
        self.lead_rows = lead_rows or []
        self.dry_run_bytes = dry_run_bytes
        self.snapshot_rows = (
            snapshot_rows
            if snapshot_rows is not None
            else [
                {"table_name": "estabelecimentos", "latest_partition": "2026-07-12"},
                {"table_name": "empresas", "latest_partition": "2026-07-12"},
            ]
        )
        self.executed: list[tuple[str, object]] = []
        self.directory_queries: list[str] = []
        self.snapshot_queries: list[tuple[str, object]] = []

    def query(self, sql, job_config=None):
        if "MAX(data)" in sql:
            self.snapshot_queries.append((sql, job_config))
            return FakeJob(0, self.snapshot_rows)
        if job_config is not None and getattr(job_config, "dry_run", False):
            return FakeJob(self.dry_run_bytes)
        if job_config is None:
            self.directory_queries.append(sql)
            return FakeJob(0, self.municipio_rows)
        self.executed.append((sql, job_config))
        return FakeJob(self.dry_run_bytes, self.lead_rows)
