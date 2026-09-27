"""Testes da materialização da tabela própria (quimera.dados)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from fakes import FakeJob
from quimera import dados
from quimera.query import LeadsTables

SNAPSHOTS = {
    "estabelecimentos": date(2026, 1, 11),
    "empresas": date(2025, 12, 14),
}
TABLES = LeadsTables(
    leads="projeto-teste.quimera.estabelecimentos_ativos",
    contatos="projeto-teste.quimera.contatos_ativos",
)

GOOD_STATS = {
    "linhas": 27_784_536,
    "cnpj_distintos": 27_784_536,
    "cnpj_invalido": 0,
    "sem_uf": 0,
    "sem_municipio": 76_622,
    "cnae_invalido": 0,
    "sem_inicio": 0,
    "inicio_futuro": 0,
    "mei_invalido": 0,
    "sem_porte": 0,
    # Sinais da Onda 1 — medidos em 2026-09-26 (91,2% com coordenada de CEP;
    # ~4% com domínio próprio).
    "sem_regime": 0,
    "regime_incoerente": 0,
    "unidades_invalidas": 0,
    "com_coordenada": 25_332_194,
    "fora_do_brasil": 0,
    "com_dominio_proprio": 1_111_381,
}


class TestBuildLeadsSql:
    def test_reads_each_table_in_its_own_snapshot(self):
        # empresas pode atrasar em relação a estabelecimentos; o snapshot de
        # estabelecimentos fica no CTE ativos (sem prefixo est.).
        sql = dados.build_leads_sql("p.d.t", SNAPSHOTS)
        assert "data = DATE '2026-01-11'" in sql
        assert "emp.data = DATE '2025-12-14'" in sql

    def test_only_active_establishments(self):
        sql = dados.build_leads_sql("p.d.t", SNAPSHOTS)
        assert "situacao_cadastral = '2'" in sql

    def test_partitioned_by_cnae_division_and_clustered_by_filters(self):
        sql = dados.build_leads_sql("p.d.t", SNAPSHOTS)
        assert (
            "PARTITION BY RANGE_BUCKET(cnae_divisao, GENERATE_ARRAY(1, 100, 1))" in sql
        )
        assert "CLUSTER BY sigla_uf, id_municipio, cnae_fiscal_principal" in sql
        assert (
            "SAFE_CAST(SUBSTR(est.cnae_fiscal_principal, 1, 2) AS INT64)"
            " AS cnae_divisao" in sql
        )

    def test_snapshot_written_to_labels(self):
        sql = dados.build_leads_sql("p.d.t", SNAPSHOTS)
        assert '("snapshot_emp", "2025-12-14")' in sql
        assert '("snapshot_est", "2026-01-11")' in sql

    def test_mei_flag_defaults_to_zero_without_simples_row(self):
        sql = dados.build_leads_sql("p.d.t", SNAPSHOTS)
        assert "COALESCE(sim.opcao_mei, 0) AS opcao_mei" in sql


class TestBuildLeadsSqlSinais:
    def test_counts_active_establishments_per_company(self):
        sql = dados.build_leads_sql("p.d.t", SNAPSHOTS)
        assert "COUNT(*) AS n_estabelecimentos" in sql
        assert "GROUP BY cnpj_basico" in sql

    def test_regime_from_simples(self):
        sql = dados.build_leads_sql("p.d.t", SNAPSHOTS)
        assert (
            "CASE WHEN sim.opcao_mei = 1 THEN 'mei'"
            " WHEN sim.opcao_simples = 1 THEN 'simples'"
            " ELSE 'fora_simples' END AS regime_tributario" in sql
        )

    def test_coordinates_from_cep_directory(self):
        sql = dados.build_leads_sql("p.d.t", SNAPSHOTS)
        assert "ST_Y(dcep.centroide) AS latitude" in sql
        assert "ST_X(dcep.centroide) AS longitude" in sql
        assert "LEFT JOIN `basedosdados.br_bd_diretorios_brasil.cep` AS dcep" in sql

    def test_dominio_proprio_is_boolean_with_measured_cut(self):
        sql = dados.build_leads_sql("p.d.t", SNAPSHOTS)
        assert (
            f"COALESCE(dom.empresas <= {dados.MAX_EMPRESAS_POR_DOMINIO}, FALSE)" in sql
        )
        assert dados.MAX_EMPRESAS_POR_DOMINIO == 4

    def test_output_has_no_contact_or_address(self):
        # O e-mail é lido só para calcular o domínio; nada de contato,
        # domínio, CEP ou logradouro sai na tabela de leads.
        for col in dados.LEADS_COLUMNS:
            assert col not in {
                "email",
                "correio_eletronico",
                "telefone",
                "ddd_1",
                "dominio",
                "cep",
                "logradouro",
                "numero",
                "complemento",
            }
        final_select = dados.build_leads_sql("p.d.t", SNAPSHOTS).split("\nSELECT\n")[-1]
        assert "email" not in final_select.split("\nFROM ")[0]

    def test_active_filter_and_snapshot_live_in_the_cte(self):
        sql = dados.build_leads_sql("p.d.t", SNAPSHOTS)
        assert "data = DATE '2026-01-11'" in sql
        assert "situacao_cadastral = '2'" in sql
        assert "emp.data = DATE '2025-12-14'" in sql


class TestBuildCepsSql:
    def test_only_ceps_with_centroid_clustered_by_cep(self):
        sql = dados.build_ceps_sql("p.d.ceps")
        assert "CLUSTER BY cep" in sql
        assert "WHERE centroide IS NOT NULL" in sql
        assert "ST_Y(centroide) AS latitude" in sql


class TestLeadsTablesCeps:
    def test_ceps_derived_from_leads_dataset_when_omitted(self):
        tables = LeadsTables(
            leads="p.quimera.estabelecimentos_ativos",
            contatos="p.quimera.contatos_ativos",
        )
        assert tables.ceps == "p.quimera.ceps"

    def test_explicit_ceps_is_kept(self):
        tables = LeadsTables(
            leads="p.quimera.estabelecimentos_ativos",
            contatos="p.quimera.contatos_ativos",
            ceps="p.outro.ceps",
        )
        assert tables.ceps == "p.outro.ceps"


class TestBuildContatosSql:
    def test_phone_includes_ddd(self):
        # telefone_1 vem sem DDD na base: sozinho é inutilizável.
        sql = dados.build_contatos_sql("p.d.c", SNAPSHOTS)
        assert (
            "CONCAT(COALESCE(TRIM(ddd_1), ''), COALESCE(TRIM(telefone_1), ''))" in sql
        )

    def test_blank_values_become_null(self):
        sql = dados.build_contatos_sql("p.d.c", SNAPSHOTS)
        assert "NULLIF(TRIM(email), '') AS correio_eletronico" in sql

    def test_only_active_in_latest_snapshot(self):
        sql = dados.build_contatos_sql("p.d.c", SNAPSHOTS)
        assert "data = DATE '2026-01-11'" in sql
        assert "situacao_cadastral = '2'" in sql


class TestEvaluateChecks:
    def test_measured_stats_pass(self):
        checks = dados.evaluate_checks(GOOD_STATS)
        assert all(c.ok for c in checks), [c for c in checks if not c.ok]

    @pytest.mark.parametrize(
        ("field", "value", "check_name"),
        [
            ("linhas", 1_000, "volume"),
            ("cnpj_distintos", 27_000_000, "cnpj único"),
            ("cnpj_invalido", 1, "cnpj com 14 dígitos"),
            ("sem_uf", 3, "uf presente"),
            ("sem_municipio", 1_000_000, "município presente"),
            ("cnae_invalido", 1, "cnae com 7 dígitos"),
            ("inicio_futuro", 1, "início de atividade válido"),
            ("mei_invalido", 1, "opcao_mei 0/1"),
            ("sem_porte", 1, "porte presente"),
            ("sem_regime", 1, "regime presente"),
            ("regime_incoerente", 1, "regime coerente com MEI"),
            ("unidades_invalidas", 1, "unidades válidas"),
            ("com_coordenada", 0, "coordenada presente"),
            ("fora_do_brasil", 1, "coordenada no Brasil"),
            ("com_dominio_proprio", 0, "domínio próprio plausível"),
        ],
    )
    def test_each_check_fails_on_bad_data(self, field, value, check_name):
        stats = {**GOOD_STATS, field: value}
        failed = [c.name for c in dados.evaluate_checks(stats) if not c.ok]
        assert check_name in failed

    def test_empty_table_fails_without_division_error(self):
        stats = {key: 0 for key in GOOD_STATS}
        failed = {c.name for c in dados.evaluate_checks(stats) if not c.ok}
        assert {"volume", "município presente"} <= failed


class FakeBuildClient:
    """Registra DDL, cópias e mudanças de tabela; devolve ``stats`` na checagem."""

    def __init__(self, stats, existing_final=None):
        self.stats = stats
        self.ddl: list[str] = []
        self.copies: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.updated: list[tuple[object, list[str]]] = []
        self.datasets: list[str] = []
        self.tables: dict[str, SimpleNamespace] = {}
        if existing_final is not None:
            self.tables[TABLES.leads] = existing_final

    def query(self, sql, job_config=None):
        if sql.startswith("CREATE OR REPLACE TABLE"):
            self.ddl.append(sql)
            name = sql.split("`")[1]
            self.tables[name] = SimpleNamespace(
                labels={},
                range_partitioning=SimpleNamespace(
                    field="cnae_divisao", range_=SimpleNamespace(start=1, end=100)
                ),
                clustering_fields=list(dados.CLUSTER_COLUMNS),
            )
            return FakeJob(0)
        if "COUNT(DISTINCT cnpj)" in sql:
            return FakeJob(0, [self.stats])
        # Checagem de volume da tabela de ceps (905.210 medidos em 2026-09-26).
        if sql.startswith("SELECT COUNT(*) AS linhas FROM `"):
            return FakeJob(0, [{"linhas": 905_210}])
        raise AssertionError(f"consulta inesperada: {sql[:60]}")

    def create_dataset(self, ds, exists_ok=False):
        self.datasets.append(ds.dataset_id)

    def get_table(self, table_id):
        if table_id not in self.tables:
            from google.api_core.exceptions import NotFound

            raise NotFound(table_id)
        return self.tables[table_id]

    def copy_table(self, source, destination, job_config=None):
        self.copies.append((source, destination))
        self.tables[destination] = SimpleNamespace(**vars(self.tables[source]))
        return FakeJob(0)

    def update_table(self, table, fields):
        self.updated.append((table, fields))

    def delete_table(self, table_id, not_found_ok=False):
        self.deleted.append(table_id)
        self.tables.pop(table_id, None)


@pytest.fixture
def snapshots(monkeypatch):
    monkeypatch.setattr(dados, "resolve_latest_snapshots", lambda client: SNAPSHOTS)


class TestBuild:
    def test_good_data_promotes_staging_and_writes_labels(self, snapshots):
        client = FakeBuildClient(GOOD_STATS)
        result, checks = dados.build(tables=TABLES, client=client)
        assert result == SNAPSHOTS
        assert all(c.ok for c in checks)
        staging = TABLES.leads + "_staging"
        assert client.ddl[0].startswith(f"CREATE OR REPLACE TABLE `{staging}`")
        assert client.copies == [(staging, TABLES.leads)]
        table, fields = client.updated[0]
        assert fields == ["labels"]
        assert table.labels == {
            "snapshot_est": "2026-01-11",
            "snapshot_emp": "2025-12-14",
        }
        assert staging in client.deleted
        assert client.datasets == ["quimera"]

    def test_failed_check_keeps_final_table_untouched(self, snapshots):
        client = FakeBuildClient({**GOOD_STATS, "cnpj_distintos": 1})
        with pytest.raises(dados.QualityCheckError, match="cnpj único") as exc_info:
            dados.build(tables=TABLES, client=client)
        assert client.copies == []
        assert TABLES.leads not in client.deleted
        assert any(not c.ok for c in exc_info.value.checks)

    def test_contacts_table_only_on_request(self, snapshots):
        client = FakeBuildClient(GOOD_STATS)
        dados.build(tables=TABLES, client=client)
        assert not any(TABLES.contatos in sql for sql in client.ddl)

        client = FakeBuildClient(GOOD_STATS)
        dados.build(tables=TABLES, contatos=True, client=client)
        assert any(
            sql.startswith(f"CREATE OR REPLACE TABLE `{TABLES.contatos}`")
            for sql in client.ddl
        )

    def test_build_writes_ceps_after_promoting_leads(self, snapshots):
        client = FakeBuildClient(GOOD_STATS)
        _, checks = dados.build(tables=TABLES, client=client)
        assert any(
            sql.startswith(f"CREATE OR REPLACE TABLE `{TABLES.ceps}`")
            for sql in client.ddl
        )
        assert client.copies == [(TABLES.leads + "_staging", TABLES.leads)]
        assert any(c.name == "volume de ceps" and c.ok for c in checks)

    def test_failed_leads_check_does_not_write_ceps(self, snapshots):
        client = FakeBuildClient({**GOOD_STATS, "cnpj_distintos": 1})
        with pytest.raises(dados.QualityCheckError):
            dados.build(tables=TABLES, client=client)
        assert not any(TABLES.ceps in sql for sql in client.ddl)

    def test_layout_change_recreates_final_table(self, snapshots):
        # Cópia WRITE_TRUNCATE falha se a partição mudou (ex.: tabela antiga
        # sem partição): nesse caso a final é removida antes da cópia.
        old = SimpleNamespace(labels={}, range_partitioning=None, clustering_fields=[])
        client = FakeBuildClient(GOOD_STATS, existing_final=old)
        dados.build(tables=TABLES, client=client)
        assert client.deleted[0] == TABLES.leads
        assert client.copies

    def test_same_layout_keeps_final_table_for_truncate_copy(self, snapshots):
        client = FakeBuildClient(GOOD_STATS)
        dados.build(tables=TABLES, client=client)
        client.deleted.clear()
        dados.build(tables=TABLES, client=client)
        assert TABLES.leads not in client.deleted
