"""Testes do pipeline: extract → cnae → policy → municípios → query → score."""

from __future__ import annotations

import json

import pytest

from quimera.filters import LeadFilters
from quimera.pipeline import run
from quimera.policy import PRIVATE, PUBLIC
from quimera.query import BytesBudgetExceededError

from fakes import FakeGenaiClient, FakePipelineBQ


def _extraction_payload(**filters) -> str:
    return json.dumps({"refused": False, "filters": filters}, ensure_ascii=False)


def _cnae_search_recorder(results):
    calls = []

    def search(query, k):
        calls.append((query, k))
        return results

    search.calls = calls
    return search


LEAD_ROWS = [
    {
        "cnpj_basico": "12345678",
        "razao_social": "CLINICA ALFA",
        "nome_fantasia": None,
        "sigla_uf": "SP",
        "id_municipio": "3547807",
        "municipio": "Santo André",
        "cnae_fiscal_principal": "8630-5/01",
        "data_inicio_atividade": "20150110",
        "capital_social": 100_000.0,
        "porte": "demais",
    },
    {
        "cnpj_basico": "87654321",
        "razao_social": "CLINICA BETA",
        "nome_fantasia": "Beta Odonto",
        "sigla_uf": "SP",
        "id_municipio": "3547807",
        "municipio": "Santo André",
        "cnae_fiscal_principal": "8630-5/01",
        "data_inicio_atividade": "20240110",
        "capital_social": 1_000.0,
        "porte": "micro",
    },
]


class TestRefusal:
    def test_refused_request_returns_refusal_without_querying(self):
        extract = FakeGenaiClient(
            json.dumps(
                {"refused": True, "refusal_reason": "pedido de dado pessoal"},
                ensure_ascii=False,
            )
        )
        bq = FakePipelineBQ()
        result = run(
            "telefone do dono de clínicas", PUBLIC, extract_client=extract, bq_client=bq
        )
        assert result.refused is True
        assert result.refusal_reason == "pedido de dado pessoal"
        assert result.rows == []
        assert bq.executed == []
        assert bq.directory_queries == []
        assert bq.snapshot_queries == []


class TestHappyPath:
    def test_full_public_flow(self):
        extract = FakeGenaiClient(
            _extraction_payload(
                cnae_query="clínicas odontológicas",
                ufs=["SP"],
                municipio_names=["Santo André"],
                min_age_years=2,
                include_mei=True,
                limit=500,
            )
        )
        cnae_search = _cnae_search_recorder(
            [
                (
                    "8630-5/01",
                    "Atividade médica ambulatorial com recursos para cirurgia odontológica",
                    0.92,
                ),
                (
                    "8630-5/02",
                    "Atividade médica ambulatorial restrita a consultos",
                    0.81,
                ),
            ]
        )
        bq = FakePipelineBQ(
            municipio_rows=[{"nome": "Santo André", "id_municipio": "3547807"}],
            lead_rows=LEAD_ROWS,
        )
        result = run(
            "clínicas odontológicas em Santo André abertas há mais de 2 anos",
            PUBLIC,
            extract_client=extract,
            cnae_search=cnae_search,
            bq_client=bq,
        )

        assert result.refused is False
        # cnae_query foi resolvida em cnae_codes via busca por embeddings
        assert result.filters.cnae_codes == ["8630-5/01", "8630-5/02"]
        assert result.cnae_matches[0] == (
            "8630-5/01",
            "Atividade médica ambulatorial com recursos para cirurgia odontológica",
            pytest.approx(0.92),
        )
        assert cnae_search.calls == [("clínicas odontológicas", 5)]
        # policy aplicada DEPOIS do LLM: limit cortado, MEI desligado no público
        assert result.filters.limit == 50
        assert result.filters.include_mei is False
        # município resolvido por lookup no diretório
        assert result.municipio_resolution == {"Santo André": "3547807"}
        assert result.filters.municipio_ids == ["3547807"]
        # snapshot mensal resolvido por descoberta e aplicado na query
        assert bq.snapshot_queries and "MAX(data)" in bq.snapshot_queries[0][0]
        assert result.snapshot == {
            "estabelecimentos": "2026-07-12",
            "empresas": "2026-07-12",
        }
        # linhas pontuadas e ordenadas por score desc
        assert [r["razao_social"] for r in result.rows] == [
            "CLINICA ALFA",
            "CLINICA BETA",
        ]
        assert result.rows[0]["score"] > result.rows[1]["score"]
        assert result.rows[0]["motivos_score"]
        # SQL executado reflete filtros + exclusão de MEI do público
        sql, _ = bq.executed[0]
        assert "@municipio_ids" in sql
        assert "@cnae_codes" in sql
        assert "@snapshot_est" in sql and "@snapshot_emp" in sql
        assert "COALESCE(sim.opcao_mei, 0) != 1" in sql  # exclusão de MEI
        # custo e latência registrados
        assert result.bytes_processed == 1000
        assert result.estimated_cost_usd > 0
        assert result.latency_ms >= 0

    def test_rows_sorted_by_score_desc(self):
        extract = FakeGenaiClient(_extraction_payload(cnae_query=None, ufs=[]))
        bq = FakePipelineBQ(lead_rows=list(reversed(LEAD_ROWS)))
        result = run("empresas em SP", PUBLIC, extract_client=extract, bq_client=bq)
        scores = [r["score"] for r in result.rows]
        assert scores == sorted(scores, reverse=True)


class TestOptionalSteps:
    def test_no_cnae_query_skips_cnae_search(self):
        extract = FakeGenaiClient(_extraction_payload(ufs=["SP"]))
        cnae_search = _cnae_search_recorder([("0000-0/00", "x", 1.0)])
        bq = FakePipelineBQ(lead_rows=[])
        result = run(
            "empresas em SP",
            PUBLIC,
            extract_client=extract,
            cnae_search=cnae_search,
            bq_client=bq,
        )
        assert cnae_search.calls == []
        assert result.filters.cnae_codes == []

    def test_unresolved_municipality_drops_municipio_filter(self):
        extract = FakeGenaiClient(_extraction_payload(municipio_names=["Narnia"]))
        bq = FakePipelineBQ(
            municipio_rows=[{"nome": "Campinas", "id_municipio": "3509502"}],
            lead_rows=[],
        )
        result = run("empresas em Narnia", PUBLIC, extract_client=extract, bq_client=bq)
        assert result.municipio_resolution == {}
        assert result.filters.municipio_ids == []
        sql, _ = bq.executed[0]
        assert "@municipio_ids" not in sql

    def test_private_flow_keeps_contact_columns(self):
        extract = FakeGenaiClient(
            _extraction_payload(ufs=["SP"], include_mei=True, limit=2000)
        )
        bq = FakePipelineBQ(lead_rows=LEAD_ROWS)
        result = run(
            "clínicas com telefone", PRIVATE, extract_client=extract, bq_client=bq
        )
        assert result.filters.limit == 1000
        sql, _ = bq.executed[0]
        assert "correio_eletronico" in sql
        assert "AS telefone" in sql


class TestCostGuard:
    def test_bytes_budget_exceeded_propagates(self):
        extract = FakeGenaiClient(_extraction_payload(ufs=["SP"]))
        bq = FakePipelineBQ(lead_rows=[], dry_run_bytes=10 * 1024**3)
        with pytest.raises(BytesBudgetExceededError):
            run(
                "empresas em SP",
                PUBLIC,
                extract_client=extract,
                bq_client=bq,
                max_bytes_billed=1024,
            )
        assert bq.executed == []


class TestResultSerialization:
    def test_to_dict_is_json_serializable(self):
        extract = FakeGenaiClient(_extraction_payload(ufs=["SP"]))
        bq = FakePipelineBQ(lead_rows=LEAD_ROWS)
        result = run("empresas em SP", PUBLIC, extract_client=extract, bq_client=bq)
        data = json.loads(json.dumps(result.to_dict(), ensure_ascii=False))
        assert data["refused"] is False
        assert data["filters"]["ufs"] == ["SP"]
        assert data["cnae_matches"] == []
        assert data["rows"][0]["score"] >= data["rows"][1]["score"]
        assert "request_normalized" in data
        assert data["snapshot"]["empresas"] == "2026-07-12"

    def test_log_record_has_no_raw_request(self):
        extract = FakeGenaiClient(_extraction_payload(ufs=["SP"]))
        bq = FakePipelineBQ(lead_rows=[])
        result = run(
            "  pedido   com espaços  ", PUBLIC, extract_client=extract, bq_client=bq
        )
        assert result.request_normalized == "pedido com espaços"
        record = result.log_record()
        assert record["request"] == "pedido com espaços"
        assert record["policy"] == "public"
        assert "bytes" in record and "latency_ms" in record and "model" in record
