"""Testes de build_query: cláusulas, parâmetros, snapshots e regras por policy."""

from __future__ import annotations

from datetime import date

import pytest

from quimera.filters import LeadFilters
from quimera.policy import PRIVATE, PUBLIC
from quimera.query import (
    DEFAULT_MAX_BYTES_BILLED,
    BytesBudgetExceededError,
    build_query,
    resolve_latest_snapshots,
    resolve_max_bytes_billed,
    resolve_municipality_ids,
    run_query,
)

SNAPSHOTS = {
    "estabelecimentos": date(2026, 7, 12),
    "empresas": date(2026, 7, 12),
}


def _param(spec, name):
    return next(p for p in spec.params if p.name == name)


class TestBuildQueryPublic:
    def test_no_contact_columns_in_public_sql(self):
        spec = build_query(LeadFilters(), PUBLIC, snapshots=SNAPSHOTS)
        for col in ("email", "telefone_1", "correio_eletronico"):
            assert col not in spec.sql

    def test_public_sql_excludes_mei_and_empresario_individual(self):
        spec = build_query(LeadFilters(include_mei=True), PUBLIC, snapshots=SNAPSHOTS)
        assert "COALESCE(sim.opcao_mei, 0) != 1" in spec.sql
        assert "natureza_juridica" in spec.sql
        assert _param(spec, "natureza_empresario_individual").value == "2135"

    def test_active_situation_uses_one_digit_code(self):
        spec = build_query(LeadFilters(), PUBLIC, snapshots=SNAPSHOTS)
        assert _param(spec, "situacao_ativa").value == "2"
        assert "@situacao_ativa" in spec.sql


class TestBuildQueryPrivate:
    def test_private_sql_includes_contact_columns(self):
        spec = build_query(LeadFilters(), PRIVATE, snapshots=SNAPSHOTS)
        assert "est.email AS correio_eletronico" in spec.sql
        assert "est.telefone_1 AS telefone" in spec.sql

    def test_private_without_mei_still_excludes_mei(self):
        spec = build_query(LeadFilters(include_mei=False), PRIVATE, snapshots=SNAPSHOTS)
        assert "COALESCE(sim.opcao_mei, 0) != 1" in spec.sql

    def test_private_with_mei_selects_mei_flag(self):
        spec = build_query(LeadFilters(include_mei=True), PRIVATE, snapshots=SNAPSHOTS)
        assert "COALESCE(sim.opcao_mei, 0) AS opcao_mei" in spec.sql
        assert "!= 1" not in spec.sql
        assert "natureza_empresario_individual" not in " ".join(
            p.name for p in spec.params
        )


class TestBuildQuerySnapshots:
    """Fase 0: tabelas empilham ~45 snapshots mensais — SEM filtro de data,
    toda consulta custa ~132 GB e devolve empresas duplicadas ~45x."""

    def test_snapshots_are_required(self):
        with pytest.raises(TypeError):
            build_query(LeadFilters(), PUBLIC)

    def test_incomplete_snapshots_rejected(self):
        with pytest.raises(ValueError, match="empresas"):
            build_query(
                LeadFilters(),
                PUBLIC,
                snapshots={"estabelecimentos": date(2026, 7, 12)},
            )

    def test_filters_latest_partition_of_est_and_emp(self):
        spec = build_query(LeadFilters(), PUBLIC, snapshots=SNAPSHOTS)
        assert "est.data = @snapshot_est" in spec.sql
        assert "emp.data = @snapshot_emp" in spec.sql
        assert _param(spec, "snapshot_est").type == "DATE"
        assert _param(spec, "snapshot_est").value == date(2026, 7, 12)
        assert _param(spec, "snapshot_emp").value == date(2026, 7, 12)

    def test_simples_has_no_partition_filter(self):
        spec = build_query(LeadFilters(), PUBLIC, snapshots=SNAPSHOTS)
        assert "sim.data" not in spec.sql  # simples não é particionada (docs/schema.md)


class TestBuildQueryClauses:
    def test_uses_named_parameters_not_interpolation(self):
        filters = LeadFilters(
            ufs=["SP"], cnae_codes=["8630-5/01"], municipio_ids=["3547807"]
        )
        spec = build_query(filters, PUBLIC, snapshots=SNAPSHOTS)
        assert "IN UNNEST(@ufs)" in spec.sql
        assert "IN UNNEST(@cnae_codes)" in spec.sql
        assert "IN UNNEST(@municipio_ids)" in spec.sql
        assert "'SP'" not in spec.sql and "3547807" not in spec.sql

    def test_cnae_codes_unmasked_for_dataset(self):
        # A base guarda o CNAE sem máscara ("8630501"); filters usam a forma
        # oficial "8630-5/01" — a normalização acontece na fronteira (query.py).
        filters = LeadFilters(cnae_codes=["8630-5/01", "4781400"])
        spec = build_query(filters, PUBLIC, snapshots=SNAPSHOTS)
        assert _param(spec, "cnae_codes").value == ["8630501", "4781400"]

    def test_param_values_reflect_filters(self):
        filters = LeadFilters(
            ufs=["SP", "RJ"],
            min_age_years=2,
            max_age_years=10,
            min_capital=5000.0,
        )
        spec = build_query(filters, PUBLIC, snapshots=SNAPSHOTS)
        assert _param(spec, "ufs").value == ["SP", "RJ"]
        assert _param(spec, "min_age_years").value == 2
        assert _param(spec, "max_age_years").value == 10
        assert _param(spec, "min_capital").value == 5000.0

    def test_age_uses_date_column_directly(self):
        # data_inicio_atividade é DATE (Fase 0) — sem PARSE_DATE de string.
        filters = LeadFilters(min_age_years=2, max_age_years=10)
        spec = build_query(filters, PUBLIC, snapshots=SNAPSHOTS)
        assert "DATE_DIFF(CURRENT_DATE(), est.data_inicio_atividade, YEAR)" in spec.sql
        assert "SAFE.PARSE_DATE" not in spec.sql

    def test_portes_translated_to_dataset_codes(self):
        # Fase 0: porte só distingue 1=Micro, 3=Pequeno Porte, 5=Demais;
        # "media" e "grande" são indistinguíveis — ambas caem em '5'.
        filters = LeadFilters(portes=["media", "micro"])
        spec = build_query(filters, PUBLIC, snapshots=SNAPSHOTS)
        assert _param(spec, "portes").value == ["5", "1"]

    def test_porte_select_translated_to_labels(self):
        spec = build_query(LeadFilters(), PUBLIC, snapshots=SNAPSHOTS)
        assert "WHEN '5' THEN 'demais'" in spec.sql

    def test_limit_param_capped_by_policy(self):
        spec = build_query(LeadFilters(limit=10_000), PUBLIC, snapshots=SNAPSHOTS)
        assert _param(spec, "limit").value == 50

    def test_joins_estabelecimentos_empresas_simples(self):
        spec = build_query(LeadFilters(), PUBLIC, snapshots=SNAPSHOTS)
        assert "estabelecimentos" in spec.sql
        assert "empresas" in spec.sql
        assert "simples" in spec.sql


class _FakeJob:
    def __init__(self, total_bytes_processed, rows=None):
        self.total_bytes_processed = total_bytes_processed
        self.total_bytes_billed = total_bytes_processed
        self._rows = rows or []

    def result(self):
        return self._rows


class FakeBQClient:
    """Cliente BigQuery falso: dry run devolve estimativa, execução devolve rows."""

    def __init__(self, dry_run_bytes=1000, rows=None, dry_run_estimate_none=False):
        self.dry_run_bytes = dry_run_bytes
        self.rows = rows or []
        self.dry_run_estimate_none = dry_run_estimate_none
        self.executed = []

    def query(self, sql, job_config=None):
        if job_config is not None and job_config.dry_run:
            estimate = None if self.dry_run_estimate_none else self.dry_run_bytes
            return _FakeJob(estimate)
        self.executed.append((sql, job_config))
        return _FakeJob(self.dry_run_bytes, self.rows)


class FakeDirectoryClient:
    """Cliente falso que só responde à consulta ao diretório de municípios."""

    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def query(self, sql, job_config=None):
        self.queries.append(sql)
        return _FakeJob(0, self.rows)


class FakeInfoClient:
    """Cliente falso para a descoberta de snapshot: consome uma fila de respostas."""

    def __init__(self, responses):
        # Aceita uma única lista de rows ou uma fila (uma por janela sondada).
        if responses and isinstance(responses[0], dict):
            responses = [responses]
        self.responses = list(responses)
        self.queries = []
        self.configs = []

    def query(self, sql, job_config=None):
        self.queries.append(sql)
        self.configs.append(job_config)
        rows = self.responses.pop(0) if self.responses else []
        return _FakeJob(0, rows)


@pytest.fixture
def spec():
    return build_query(LeadFilters(ufs=["SP"]), PUBLIC, snapshots=SNAPSHOTS)


class TestResolveLatestSnapshots:
    """Descoberta do snapshot: INFORMATION_SCHEMA regional e tabledata dão
    Access Denied com credencial comum (validado no real); MAX(data) sem filtro
    exigiria ~78 GB. Estratégia: MAX(data) em janelas que recuem — janela VAZIA
    custa 0 bytes (pruning; medido no real), então recuar até a primeira
    não-vazia acha o máximo global. SNAPSHOT_DATE fixa tudo com custo zero."""

    def _rows(self):
        return [
            {"table_name": "estabelecimentos", "latest_partition": "2026-07-12"},
            {"table_name": "empresas", "latest_partition": "2026-07-12"},
        ]

    def test_returns_latest_partition_per_table(self):
        client = FakeInfoClient(self._rows())
        snapshots = resolve_latest_snapshots(client=client)
        assert snapshots == SNAPSHOTS
        assert len(client.queries) == 1  # primeira janela já resolveu

    def test_accepts_date_objects_from_bigquery(self):
        rows = [
            {"table_name": "estabelecimentos", "latest_partition": date(2026, 7, 12)},
            {"table_name": "empresas", "latest_partition": date(2026, 7, 12)},
        ]
        assert resolve_latest_snapshots(client=FakeInfoClient(rows)) == SNAPSHOTS

    def test_empty_windows_step_back_until_found(self):
        # Janelas recentes vazias (0 bytes) até a primeira com partição.
        client = FakeInfoClient(
            [
                [
                    {"table_name": "estabelecimentos", "latest_partition": None},
                    {"table_name": "empresas", "latest_partition": None},
                ],
                self._rows(),
            ]
        )
        snapshots = resolve_latest_snapshots(client=client)
        assert snapshots == SNAPSHOTS
        assert len(client.queries) == 2

    def test_mixed_tables_keep_stepping_for_the_missing_one(self):
        client = FakeInfoClient(
            [
                [
                    {
                        "table_name": "estabelecimentos",
                        "latest_partition": "2026-07-12",
                    },
                    {"table_name": "empresas", "latest_partition": None},
                ],
                [{"table_name": "empresas", "latest_partition": "2026-06-14"}],
            ]
        )
        snapshots = resolve_latest_snapshots(client=client)
        assert snapshots == {
            "estabelecimentos": date(2026, 7, 12),
            "empresas": date(2026, 6, 14),
        }

    def test_all_windows_empty_raises_with_guidance(self):
        client = FakeInfoClient([])
        with pytest.raises(RuntimeError, match="SNAPSHOT_DATE"):
            resolve_latest_snapshots(client=client)

    def test_discovery_uses_bounded_window_not_full_scan(self):
        client = FakeInfoClient(self._rows())
        resolve_latest_snapshots(client=client)
        sql = client.queries[0]
        assert "MAX(data)" in sql
        assert "estabelecimentos" in sql and "empresas" in sql
        # Janela obrigatória: sem ela o BigQuery leria a coluna data de TODAS as
        # partições (~78 GB, medido no real).
        assert "data >= DATE" in sql and "data < DATE" in sql

    def test_discovery_carries_bytes_cap(self):
        from quimera.query import SNAPSHOT_DISCOVERY_MAX_BYTES

        client = FakeInfoClient(self._rows())
        resolve_latest_snapshots(client=client)
        config = client.configs[0]
        assert config is not None
        assert config.maximum_bytes_billed == SNAPSHOT_DISCOVERY_MAX_BYTES

    def test_env_snapshot_short_circuits_discovery(self, monkeypatch):
        client = FakeInfoClient([])
        monkeypatch.setenv("SNAPSHOT_DATE", "2026-08-12")
        snapshots = resolve_latest_snapshots(client=client)
        assert snapshots == {
            "estabelecimentos": date(2026, 8, 12),
            "empresas": date(2026, 8, 12),
        }
        assert client.queries == []  # custo zero: nem consulta

    def test_invalid_env_snapshot_raises(self, monkeypatch):
        monkeypatch.setenv("SNAPSHOT_DATE", "12/08/2026")
        with pytest.raises(ValueError, match="SNAPSHOT_DATE"):
            resolve_latest_snapshots(client=FakeInfoClient([]))


class TestResolveMunicipalityIds:
    def test_resolves_names_ignoring_accents_and_case(self):
        client = FakeDirectoryClient(
            [
                {"nome": "Santo André", "id_municipio": 3547807},
                {"nome": "Campinas", "id_municipio": "3509502"},
            ]
        )
        resolved = resolve_municipality_ids(["santo andre", "CAMPINAS"], client=client)
        assert resolved == {"santo andre": "3547807", "CAMPINAS": "3509502"}

    def test_unresolved_names_are_absent(self):
        client = FakeDirectoryClient([{"nome": "Campinas", "id_municipio": "3509502"}])
        resolved = resolve_municipality_ids(["Narnia", "Campinas"], client=client)
        assert resolved == {"Campinas": "3509502"}

    def test_queries_directory_table_without_user_input(self):
        client = FakeDirectoryClient([])
        resolve_municipality_ids(["São Paulo"], client=client)
        assert "municipio" in client.queries[0]
        assert "São Paulo" not in client.queries[0]


class TestResolveMaxBytesBilled:
    def test_explicit_value_wins(self, monkeypatch):
        monkeypatch.setenv("MAX_BYTES_BILLED", "999")
        assert resolve_max_bytes_billed(2048) == 2048

    def test_reads_environment(self, monkeypatch):
        monkeypatch.setenv("MAX_BYTES_BILLED", "999")
        assert resolve_max_bytes_billed() == 999

    def test_default(self, monkeypatch):
        monkeypatch.delenv("MAX_BYTES_BILLED", raising=False)
        assert resolve_max_bytes_billed() == DEFAULT_MAX_BYTES_BILLED


class TestRunQuery:
    def test_dry_run_above_cap_refuses_before_executing(self, spec):
        client = FakeBQClient(dry_run_bytes=10 * 1024**3)
        with pytest.raises(BytesBudgetExceededError, match="teto"):
            run_query(spec, client=client, max_bytes_billed=1024)
        assert client.executed == []

    def test_dry_run_without_estimate_still_proceeds(self, spec):
        # Fase 0 (PENDENTE 4): dry run nestas tabelas volta None em vez de
        # estimativa. Não pode quebrar: a barreira dura é o maximum_bytes_billed
        # do job real.
        client = FakeBQClient(dry_run_estimate_none=True, rows=[{"razao_social": "X"}])
        result = run_query(spec, client=client, max_bytes_billed=1024**3)
        assert len(client.executed) == 1
        assert result.rows == [{"razao_social": "X"}]

    def test_execution_returns_rows_and_bytes(self, spec):
        rows = [{"razao_social": "CLINICA EXEMPLO ME", "porte": "demais"}]
        client = FakeBQClient(dry_run_bytes=1000, rows=rows)
        result = run_query(spec, client=client, max_bytes_billed=1024**3)
        assert result.rows == rows
        assert result.bytes_processed == 1000
        assert len(client.executed) == 1

    def test_execution_enforces_maximum_bytes_billed(self, spec):
        client = FakeBQClient(dry_run_bytes=1000)
        run_query(spec, client=client, max_bytes_billed=2048)
        _, job_config = client.executed[0]
        assert job_config.maximum_bytes_billed == 2048

    def test_bytes_limit_error_on_execution_becomes_budget_error(self, spec):
        # Dry run sem estimativa (PENDENTE 4): quem barra é o
        # maximum_bytes_billed do job real, e o erro precisa virar o mesmo
        # BytesBudgetExceededError do dry run.
        class BytesLimitError(Exception):
            errors = [{"reason": "bytesBilledLimitExceeded", "message": "x"}]

        class FailingJob(_FakeJob):
            def result(self):
                raise BytesLimitError("Query exceeded limit for bytes billed")

        class Client(FakeBQClient):
            def query(self, sql, job_config=None):
                if job_config is not None and job_config.dry_run:
                    return _FakeJob(None)
                return FailingJob(0)

        with pytest.raises(BytesBudgetExceededError, match="2048"):
            run_query(spec, client=Client(), max_bytes_billed=2048)

    def test_other_execution_errors_propagate(self, spec):
        class Client(FakeBQClient):
            def query(self, sql, job_config=None):
                if job_config is not None and job_config.dry_run:
                    return _FakeJob(1000)
                raise RuntimeError("falha de rede")

        with pytest.raises(RuntimeError, match="falha de rede"):
            run_query(spec, client=Client(), max_bytes_billed=2048)

    def test_query_parameters_passed_to_job(self, spec):
        client = FakeBQClient(dry_run_bytes=1000)
        run_query(spec, client=client, max_bytes_billed=1024**3)
        _, job_config = client.executed[0]
        names = {p.name for p in job_config.query_parameters}
        assert {"ufs", "limit", "snapshot_est", "snapshot_emp"} <= names
