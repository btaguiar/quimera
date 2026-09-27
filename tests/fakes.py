"""Fakes compartilhados entre os testes (sem rede, sem GCP)."""

from __future__ import annotations

from types import SimpleNamespace


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


class FakeBytesLimitError(Exception):
    """Imita o erro real do BigQuery ao estourar ``maximum_bytes_billed``."""

    def __init__(self, limit, required=None):
        message = f"Query exceeded limit for bytes billed: {limit}."
        if required is not None:
            message += f" {required} or higher required."
        super().__init__(message)
        self.errors = [{"reason": "bytesBilledLimitExceeded", "message": message}]


class FakeRejectedJob(FakeJob):
    """Job recusado pelo teto: o erro sai em ``result()``, como no real."""

    def __init__(self, limit, required):
        super().__init__(None)
        self._error = FakeBytesLimitError(limit, required)

    def result(self):
        raise self._error


def exceeds_cap(job_config, required) -> bool:
    """Como o BigQuery: teto abaixo do custo estimado recusa ANTES de executar."""
    cap = getattr(job_config, "maximum_bytes_billed", None)
    return cap is not None and required is not None and cap < required


class FakePipelineBQ:
    """Cliente BigQuery falso para o pipeline completo.

    Sequência de chamadas:
    1. client.get_table              -> labels de snapshot da tabela própria;
    2. job_config ausente           -> consulta ao diretório de municípios;
    3. SQL com parâmetro ``@cep``   -> centroide do CEP (FakeJob(0, cep_rows));
    4. job_config de execução        -> consulta de leads: recusada com
       "N or higher required" (N = ``dry_run_bytes``) se o teto for menor,
       senão registrada em ``executed``.
    """

    def __init__(
        self,
        municipio_rows=None,
        lead_rows=None,
        cep_rows=None,
        dry_run_bytes=1000,
        table_labels=None,
    ):
        self.municipio_rows = municipio_rows or []
        self.lead_rows = lead_rows or []
        self.cep_rows = cep_rows
        self.dry_run_bytes = dry_run_bytes
        self.table_labels = (
            table_labels
            if table_labels is not None
            else {"snapshot_est": "2026-07-12", "snapshot_emp": "2026-07-12"}
        )
        self.executed: list[tuple[str, object]] = []
        self.directory_queries: list[str] = []
        self.cep_queries: list[str] = []
        self.table_lookups: list[str] = []

    def get_table(self, table_id):
        self.table_lookups.append(table_id)
        return SimpleNamespace(labels=self.table_labels)

    def query(self, sql, job_config=None):
        if job_config is None:
            self.directory_queries.append(sql)
            return FakeJob(0, self.municipio_rows)
        if "@cep" in sql:
            self.cep_queries.append(sql)
            return FakeJob(0, self.cep_rows)
        if exceeds_cap(job_config, self.dry_run_bytes):
            return FakeRejectedJob(job_config.maximum_bytes_billed, self.dry_run_bytes)
        self.executed.append((sql, job_config))
        return FakeJob(self.dry_run_bytes, self.lead_rows)
