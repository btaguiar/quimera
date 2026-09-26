"""Testes de build_query, descoberta de snapshot, municípios e run_query."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from fakes import FakeRejectedJob, is_estimate_probe
from quimera.filters import LeadFilters
from quimera.policy import PRIVATE, PUBLIC
from quimera.query import (
    DEFAULT_MAX_BYTES_BILLED,
    BytesBudgetExceededError,
    LeadsTableMissingError,
    LeadsTables,
    build_query,
    read_leads_snapshot,
    resolve_latest_snapshots,
    resolve_leads_tables,
    resolve_max_bytes_billed,
    resolve_municipality_ids,
    run_query,
)

SNAPSHOTS = {
    "estabelecimentos": date(2026, 7, 12),
    "empresas": date(2026, 7, 12),
}
TABLES = LeadsTables(
    leads="projeto-teste.quimera.estabelecimentos_ativos",
    contatos="projeto-teste.quimera.contatos_ativos",
)


def _build(filters=None, policy=PUBLIC):
    return build_query(filters or LeadFilters(), policy, tables=TABLES)


def _param(spec, name):
    return next(p for p in spec.params if p.name == name)


class TestBuildQueryPublic:
    def test_no_contact_columns_in_public_sql(self):
        spec = _build()
        for col in ("email", "telefone", "correio_eletronico", "contatos_ativos"):
            assert col not in spec.sql

    def test_public_sql_excludes_mei_and_empresario_individual(self):
        spec = _build(LeadFilters(include_mei=True))
        assert "t.opcao_mei != 1" in spec.sql
        assert "t.natureza_juridica != @natureza_empresario_individual" in spec.sql
        assert _param(spec, "natureza_empresario_individual").value == "2135"

    def test_public_excludes_pessoa_fisica(self):
        # Natureza 4xxx = pessoa física (ex.: 4120 produtor rural).
        spec = _build()
        assert (
            "NOT STARTS_WITH(t.natureza_juridica, @natureza_pessoa_fisica)" in spec.sql
        )
        assert _param(spec, "natureza_pessoa_fisica").value == "4"


class TestBuildQueryPrivate:
    def test_private_sql_joins_contacts_table(self):
        spec = _build(policy=PRIVATE)
        assert (
            "LEFT JOIN `projeto-teste.quimera.contatos_ativos` AS c USING (cnpj)"
            in spec.sql
        )
        assert "c.correio_eletronico AS correio_eletronico" in spec.sql
        assert "c.telefone AS telefone" in spec.sql

    def test_private_without_mei_still_excludes_mei(self):
        spec = _build(LeadFilters(include_mei=False), PRIVATE)
        assert "t.opcao_mei != 1" in spec.sql

    def test_private_allows_pessoa_fisica(self):
        spec = _build(policy=PRIVATE)
        assert "@natureza_pessoa_fisica" not in spec.sql

    def test_private_with_mei_selects_mei_flag(self):
        spec = _build(LeadFilters(include_mei=True), PRIVATE)
        assert "t.opcao_mei,\n" in spec.sql
        assert "!= 1" not in spec.sql
        assert "natureza_empresario_individual" not in " ".join(
            p.name for p in spec.params
        )


class TestBuildQueryTable:
    """A consulta lê a tabela própria: direto na Base dos Dados custava
    ~13 GB por pedido (filtros não reduzem bytes; docs/schema.md)."""

    def test_reads_only_the_leads_table(self):
        spec = _build(LeadFilters(ufs=["SP"]))
        assert "FROM `projeto-teste.quimera.estabelecimentos_ativos` AS t" in spec.sql
        assert "basedosdados" not in spec.sql
        assert "JOIN" not in spec.sql  # cruzamentos já feitos na materialização

    def test_where_omitted_when_there_is_nothing_to_filter(self):
        assert "WHERE" in _build().sql  # público sempre exclui MEI/pessoa física
        private = _build(LeadFilters(include_mei=True), PRIVATE)
        assert "WHERE" not in private.sql
        assert private.sql.endswith("LIMIT @limit")

    def test_invalid_table_id_rejected(self):
        with pytest.raises(ValueError, match="inválido"):
            LeadsTables(leads="x`; DROP TABLE y; --", contatos="a.b.c")

    def test_resolve_leads_tables_from_env(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "meu-projeto")
        monkeypatch.setenv("LEADS_DATASET", "dados")
        tables = resolve_leads_tables()
        assert tables.leads == "meu-projeto.dados.estabelecimentos_ativos"
        assert tables.contatos == "meu-projeto.dados.contatos_ativos"

    def test_resolve_leads_tables_requires_project(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        with pytest.raises(ValueError, match="GOOGLE_CLOUD_PROJECT"):
            resolve_leads_tables()


class TestReadLeadsSnapshot:
    class _Client:
        def __init__(self, labels=None, missing=False):
            self.labels = labels
            self.missing = missing

        def get_table(self, table_id):
            if self.missing:
                from google.api_core.exceptions import NotFound

                raise NotFound("tabela")
            return SimpleNamespace(labels=self.labels)

    def test_reads_snapshot_from_labels(self):
        client = self._Client(
            {"snapshot_est": "2026-07-12", "snapshot_emp": "2026-06-14"}
        )
        assert read_leads_snapshot(TABLES, client=client) == {
            "estabelecimentos": date(2026, 7, 12),
            "empresas": date(2026, 6, 14),
        }

    def test_missing_table_points_to_build(self):
        with pytest.raises(LeadsTableMissingError, match="quimera.dados build"):
            read_leads_snapshot(TABLES, client=self._Client(missing=True))

    def test_missing_labels_points_to_build(self):
        with pytest.raises(LeadsTableMissingError, match="quimera.dados build"):
            read_leads_snapshot(TABLES, client=self._Client({}))


class TestBuildQueryClauses:
    def test_uses_named_parameters_not_interpolation(self):
        filters = LeadFilters(
            ufs=["SP"], cnae_codes=["8630-5/01"], municipio_ids=["3547807"]
        )
        spec = _build(filters)
        assert "IN UNNEST(@ufs)" in spec.sql
        assert "IN UNNEST(@cnae_codes)" in spec.sql
        assert "IN UNNEST(@municipio_ids)" in spec.sql
        assert "'SP'" not in spec.sql and "3547807" not in spec.sql

    def test_cnae_codes_unmasked_for_dataset(self):
        # A base guarda o CNAE sem máscara ("8630501"); filters usam a forma
        # oficial "8630-5/01" — a normalização acontece na fronteira (query.py).
        spec = _build(LeadFilters(cnae_codes=["8630-5/01", "4781400"]))
        assert _param(spec, "cnae_codes").value == ["8630501", "4781400"]

    def test_cnae_filters_partition_column(self):
        # O teto de bytes é checado sobre a estimativa pré-execução, que só vê
        # poda de partição: sem este filtro toda consulta estimava 4 GB.
        spec = _build(LeadFilters(cnae_codes=["8630-5/01", "8630-5/04", "4781400"]))
        assert "t.cnae_divisao IN UNNEST(@cnae_divisoes)" in spec.sql
        divisoes = _param(spec, "cnae_divisoes")
        assert divisoes.type == "ARRAY<INT64>"
        assert divisoes.value == [47, 86]

    def test_param_values_reflect_filters(self):
        filters = LeadFilters(
            ufs=["SP", "RJ"],
            min_age_years=2,
            max_age_years=10,
            min_capital=5000.0,
        )
        spec = _build(filters)
        assert _param(spec, "ufs").value == ["SP", "RJ"]
        assert _param(spec, "min_age_years").value == 2
        assert _param(spec, "max_age_years").value == 10
        assert _param(spec, "min_capital").value == 5000.0

    def test_age_counts_complete_years(self):
        # DATE_DIFF(..., YEAR) conta viradas de ano: 31/12/2024 -> 26/09/2026
        # daria 2 "anos". A comparação com DATE_SUB exige anos completos.
        spec = _build(LeadFilters(min_age_years=2, max_age_years=10))
        assert (
            "t.data_inicio_atividade"
            " <= DATE_SUB(CURRENT_DATE(), INTERVAL @min_age_years YEAR)"
        ) in spec.sql
        assert (
            "t.data_inicio_atividade"
            " > DATE_SUB(CURRENT_DATE(), INTERVAL @max_age_years + 1 YEAR)"
        ) in spec.sql
        assert "DATE_DIFF" not in spec.sql

    def test_portes_translated_to_dataset_codes(self):
        spec = _build(LeadFilters(portes=["pequena", "micro"]))
        assert _param(spec, "portes").value == ["3", "1"]
        assert "@porte_demais" not in spec.sql

    def test_media_grande_are_demais_restricted_to_business_entities(self):
        # Porte só distingue 1/3/5; '5' (Demais) ativo é 53% associação,
        # condomínio, igreja, órgão público e pessoa física (medido).
        spec = _build(LeadFilters(portes=["media", "grande", "micro"]))
        assert _param(spec, "portes").value == ["1"]
        assert _param(spec, "porte_demais").value == "5"
        assert _param(spec, "natureza_empresarial").value == "2"
        assert (
            "(t.porte IN UNNEST(@portes) OR (t.porte = @porte_demais"
            " AND STARTS_WITH(t.natureza_juridica, @natureza_empresarial)))"
        ) in spec.sql

    def test_only_media_has_no_exact_porte_param(self):
        spec = _build(LeadFilters(portes=["media"]))
        assert "@portes" not in spec.sql
        assert "@porte_demais" in spec.sql

    def test_min_capital_excludes_sentinel(self):
        spec = _build(LeadFilters(min_capital=1e6))
        assert "t.capital_social < @capital_sentinela" in spec.sql
        assert _param(spec, "capital_sentinela").value == 999_999_999_999.0

    def test_selects_full_cnpj_and_matriz_filial(self):
        # Com só cnpj_basico, matriz e filiais sairiam como linhas repetidas.
        spec = _build()
        assert "t.cnpj,\n" in spec.sql
        assert "t.matriz_filial" in spec.sql

    def test_porte_select_translated_to_labels(self):
        spec = _build()
        assert "WHEN '5' THEN 'demais'" in spec.sql

    def test_limit_param_capped_by_policy(self):
        spec = _build(LeadFilters(limit=10_000))
        assert _param(spec, "limit").value == 50


class _FakeJob:
    def __init__(self, total_bytes_processed, rows=None):
        self.total_bytes_processed = total_bytes_processed
        self.total_bytes_billed = total_bytes_processed
        self._rows = rows or []

    def result(self):
        return self._rows


class FakeBQClient:
    """Cliente BigQuery falso: a sonda de 1 byte é recusada com a estimativa
    ("N or higher required"), a execução devolve rows.

    ``job_reports_bytes=False`` imita as tabelas de CNPJ, cujo job real devolve
    ``total_bytes_billed=None`` (medido em 2026-09-26).
    """

    def __init__(self, estimate_bytes=1000, rows=None, job_reports_bytes=True):
        self.estimate_bytes = estimate_bytes
        self.rows = rows or []
        self.job_reports_bytes = job_reports_bytes
        self.executed = []
        self.probes = []

    def query(self, sql, job_config=None):
        if is_estimate_probe(job_config):
            self.probes.append((sql, job_config))
            return FakeRejectedJob(1, self.estimate_bytes)
        self.executed.append((sql, job_config))
        reported = self.estimate_bytes if self.job_reports_bytes else None
        return _FakeJob(reported, self.rows)


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
    return _build(LeadFilters(ufs=["SP"]))


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
                {"nome": "Santo André", "sigla_uf": "SP", "id_municipio": 3547807},
                {"nome": "Campinas", "sigla_uf": "SP", "id_municipio": "3509502"},
            ]
        )
        resolved = resolve_municipality_ids(["santo andre", "CAMPINAS"], client=client)
        assert resolved == {"santo andre": ["3547807"], "CAMPINAS": ["3509502"]}

    def test_unresolved_names_are_absent(self):
        client = FakeDirectoryClient(
            [{"nome": "Campinas", "sigla_uf": "SP", "id_municipio": "3509502"}]
        )
        resolved = resolve_municipality_ids(["Narnia", "Campinas"], client=client)
        assert resolved == {"Campinas": ["3509502"]}

    def test_homonyms_resolve_to_every_match_without_uf(self):
        # 233 nomes se repetem entre UFs; "Santo André" existe em SP e na PB.
        # Antes, um dict nome->id guardava só o último lido (arbitrário).
        client = FakeDirectoryClient(
            [
                {"nome": "Santo André", "sigla_uf": "PB", "id_municipio": "2513851"},
                {"nome": "Santo André", "sigla_uf": "SP", "id_municipio": "3547809"},
            ]
        )
        resolved = resolve_municipality_ids(["Santo André"], client=client)
        assert resolved == {"Santo André": ["2513851", "3547809"]}

    def test_ufs_restrict_homonyms(self):
        client = FakeDirectoryClient(
            [
                {"nome": "Santo André", "sigla_uf": "PB", "id_municipio": "2513851"},
                {"nome": "Santo André", "sigla_uf": "SP", "id_municipio": "3547809"},
            ]
        )
        resolved = resolve_municipality_ids(["Santo André"], ufs=["SP"], client=client)
        assert resolved == {"Santo André": ["3547809"]}

    def test_name_outside_requested_ufs_is_unresolved(self):
        client = FakeDirectoryClient(
            [{"nome": "Campinas", "sigla_uf": "SP", "id_municipio": "3509502"}]
        )
        assert resolve_municipality_ids(["Campinas"], ufs=["RJ"], client=client) == {}

    def test_queries_directory_table_without_user_input(self):
        client = FakeDirectoryClient([])
        resolve_municipality_ids(["São Paulo"], client=client)
        assert "municipio" in client.queries[0]
        assert "sigla_uf" in client.queries[0]
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
    """Nas tabelas de CNPJ o BigQuery não informa bytes (dry run, job e
    INFORMATION_SCHEMA devolvem None — medido). A estimativa vem de uma sonda
    com teto de 1 byte, recusada sem custo com "N or higher required"."""

    def test_estimate_above_cap_refuses_before_executing(self, spec):
        client = FakeBQClient(estimate_bytes=10 * 1024**3)
        with pytest.raises(BytesBudgetExceededError, match=str(10 * 1024**3)):
            run_query(spec, client=client, max_bytes_billed=1024)
        assert client.executed == []

    def test_probe_carries_parameters_and_one_byte_cap(self, spec):
        client = FakeBQClient(estimate_bytes=1000)
        run_query(spec, client=client, max_bytes_billed=1024**3)
        _, probe_config = client.probes[0]
        assert probe_config.maximum_bytes_billed == 1
        names = {p.name for p in probe_config.query_parameters}
        assert {"ufs", "limit"} <= names

    def test_execution_returns_rows_and_bytes(self, spec):
        rows = [{"razao_social": "CLINICA EXEMPLO ME", "porte": "demais"}]
        client = FakeBQClient(estimate_bytes=1000, rows=rows)
        result = run_query(spec, client=client, max_bytes_billed=1024**3)
        assert result.rows == rows
        assert result.bytes_processed == 1000
        assert len(client.executed) == 1

    def test_job_without_reported_bytes_accounts_the_estimate(self, spec):
        # Sem isso bytes_billed seria 0 e o orçamento diário da API nunca baixaria.
        client = FakeBQClient(estimate_bytes=3_580_887_040, job_reports_bytes=False)
        result = run_query(spec, client=client, max_bytes_billed=5 * 1024**3)
        assert result.bytes_billed == 3_580_887_040
        assert result.bytes_processed == 3_580_887_040

    def test_probe_that_runs_returns_its_result_without_second_job(self, spec):
        # Cache hit: a sonda passa com 0 bytes e o resultado dela já serve.
        class Client(FakeBQClient):
            def query(self, sql, job_config=None):
                self.probes.append((sql, job_config))
                return _FakeJob(0, [{"razao_social": "X"}])

        client = Client()
        result = run_query(spec, client=client, max_bytes_billed=1024**3)
        assert result.rows == [{"razao_social": "X"}]
        assert result.bytes_billed == 0
        assert len(client.probes) == 1

    def test_probe_error_without_number_still_proceeds(self, spec):
        # Mensagem sem "N or higher required": sem estimativa, a barreira dura
        # continua sendo o maximum_bytes_billed do job real.
        class Client(FakeBQClient):
            def query(self, sql, job_config=None):
                if is_estimate_probe(job_config):
                    return FakeRejectedJob(1, None)
                return super().query(sql, job_config)

        client = Client(rows=[{"razao_social": "X"}], job_reports_bytes=False)
        result = run_query(spec, client=client, max_bytes_billed=1024**3)
        assert result.rows == [{"razao_social": "X"}]
        assert result.bytes_billed == 0

    def test_execution_enforces_maximum_bytes_billed(self, spec):
        client = FakeBQClient(estimate_bytes=1000)
        run_query(spec, client=client, max_bytes_billed=2048)
        _, job_config = client.executed[0]
        assert job_config.maximum_bytes_billed == 2048

    def test_bytes_limit_error_on_execution_becomes_budget_error(self, spec):
        class Client(FakeBQClient):
            def query(self, sql, job_config=None):
                if is_estimate_probe(job_config):
                    return FakeRejectedJob(1, None)
                return FakeRejectedJob(2048, 4096)

        with pytest.raises(BytesBudgetExceededError, match="exige 4096 bytes"):
            run_query(spec, client=Client(), max_bytes_billed=2048)

    def test_probe_errors_other_than_bytes_limit_propagate(self, spec):
        class Client(FakeBQClient):
            def query(self, sql, job_config=None):
                raise RuntimeError("sintaxe inválida")

        with pytest.raises(RuntimeError, match="sintaxe inválida"):
            run_query(spec, client=Client(), max_bytes_billed=2048)

    def test_other_execution_errors_propagate(self, spec):
        class Client(FakeBQClient):
            def query(self, sql, job_config=None):
                if is_estimate_probe(job_config):
                    return FakeRejectedJob(1, 1000)
                raise RuntimeError("falha de rede")

        with pytest.raises(RuntimeError, match="falha de rede"):
            run_query(spec, client=Client(), max_bytes_billed=2048)

    def test_query_parameters_passed_to_job(self, spec):
        client = FakeBQClient(estimate_bytes=1000)
        run_query(spec, client=client, max_bytes_billed=1024**3)
        _, job_config = client.executed[0]
        names = {p.name for p in job_config.query_parameters}
        assert {"ufs", "limit"} <= names
