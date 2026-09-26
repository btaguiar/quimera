"""Testes do pipeline: extract → cnae → policy → municípios → query → score."""

from __future__ import annotations

import json

import pytest

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
        assert bq.table_lookups == []


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
        # "Santo André" existe em SP e na PB: a UF do pedido desempata.
        bq = FakePipelineBQ(
            municipio_rows=[
                {"nome": "Santo André", "sigla_uf": "SP", "id_municipio": "3547807"},
                {"nome": "Santo André", "sigla_uf": "PB", "id_municipio": "2513851"},
            ],
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
        assert result.municipio_resolution == {"Santo André": ["3547807"]}
        assert result.filters.municipio_ids == ["3547807"]
        assert result.warnings == []
        # snapshot lido dos labels da tabela própria (sem consulta)
        assert bq.table_lookups == ["projeto-teste.quimera.estabelecimentos_ativos"]
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
        assert "`projeto-teste.quimera.estabelecimentos_ativos`" in sql
        assert "basedosdados" not in sql  # consulta direta custava ~13 GB
        assert "t.opcao_mei != 1" in sql  # exclusão de MEI
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

    def test_unresolved_municipality_does_not_broaden_search(self):
        # Rodar sem o filtro devolveria empresas de qualquer lugar como se
        # fossem de "Narnia": sem município resolvido, nada é consultado.
        extract = FakeGenaiClient(_extraction_payload(municipio_names=["Narnia"]))
        bq = FakePipelineBQ(
            municipio_rows=[
                {"nome": "Campinas", "sigla_uf": "SP", "id_municipio": "3509502"}
            ],
            lead_rows=LEAD_ROWS,
        )
        result = run("empresas em Narnia", PUBLIC, extract_client=extract, bq_client=bq)
        assert result.municipio_resolution == {}
        assert result.rows == []
        assert bq.executed == []
        assert any("Narnia" in w for w in result.warnings)

    def test_partially_resolved_municipalities_warn_and_query(self):
        extract = FakeGenaiClient(
            _extraction_payload(municipio_names=["Campinas", "Narnia"])
        )
        bq = FakePipelineBQ(
            municipio_rows=[
                {"nome": "Campinas", "sigla_uf": "SP", "id_municipio": "3509502"}
            ],
            lead_rows=[],
        )
        result = run("empresas", PUBLIC, extract_client=extract, bq_client=bq)
        assert result.filters.municipio_ids == ["3509502"]
        assert any("Narnia" in w for w in result.warnings)
        assert len(bq.executed) == 1

    def test_homonym_without_uf_includes_all_and_warns(self):
        extract = FakeGenaiClient(_extraction_payload(municipio_names=["Santo André"]))
        bq = FakePipelineBQ(
            municipio_rows=[
                {"nome": "Santo André", "sigla_uf": "SP", "id_municipio": "3547807"},
                {"nome": "Santo André", "sigla_uf": "PB", "id_municipio": "2513851"},
            ],
            lead_rows=[],
        )
        result = run("empresas", PUBLIC, extract_client=extract, bq_client=bq)
        assert sorted(result.filters.municipio_ids) == ["2513851", "3547807"]
        assert any("Informe a UF" in w for w in result.warnings)

    def test_media_or_grande_porte_warns_about_dataset_limit(self):
        extract = FakeGenaiClient(_extraction_payload(ufs=["SP"], portes=["media"]))
        bq = FakePipelineBQ(lead_rows=[])
        result = run("empresas médias", PUBLIC, extract_client=extract, bq_client=bq)
        assert any("médio de grande" in w for w in result.warnings)

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


class TestCnaeStep:
    def test_no_matching_cnae_does_not_query(self):
        # Sem CNAE, a consulta traria empresas de qualquer atividade.
        extract = FakeGenaiClient(
            _extraction_payload(cnae_query="naves espaciais", ufs=["SP"])
        )
        bq = FakePipelineBQ(lead_rows=LEAD_ROWS)
        result = run(
            "fábricas de naves espaciais em SP",
            PUBLIC,
            extract_client=extract,
            cnae_search=_cnae_search_recorder([]),
            bq_client=bq,
        )
        assert result.rows == []
        assert bq.executed == []
        assert any("naves espaciais" in w for w in result.warnings)

    def test_default_search_selects_among_candidates(self, monkeypatch):
        from quimera import cnae, pipeline

        candidates = [("a", "A", 0.9), ("b", "B", 0.8), ("c", "C", 0.7)]
        calls = {}

        def fake_search(query, k):
            calls["search"] = (query, k)
            return candidates

        def fake_select(query, cands):
            calls["select"] = (query, cands)
            return [cands[0], cands[2]]

        monkeypatch.setattr(cnae, "search", fake_search)
        monkeypatch.setattr(cnae, "select_codes", fake_select)
        assert pipeline.default_cnae_search("padarias", 5) == [
            ("a", "A", 0.9),
            ("c", "C", 0.7),
        ]
        assert calls["search"] == ("padarias", cnae.SELECT_CANDIDATES)
        assert calls["select"] == ("padarias", candidates)


class TestCnaeSelectionFallback:
    def test_selection_failure_falls_back_to_similarity_cut(self, monkeypatch):
        # 429 de cota no Gemini: o pedido segue com o corte por similaridade.
        from quimera import cnae, pipeline

        candidates = [("a", "A", 0.80), ("b", "B", 0.78), ("c", "C", 0.60)]
        monkeypatch.setattr(cnae, "search", lambda q, k: candidates)

        def fail(query, cands):
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

        monkeypatch.setattr(cnae, "select_codes", fail)
        assert [c for c, _, _ in pipeline.default_cnae_search("x", 5)] == ["a", "b"]


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


class TestTimingsAndWarmup:
    def test_result_has_per_stage_timings(self):
        extract = FakeGenaiClient(
            _extraction_payload(
                cnae_query="dentistas", ufs=["SP"], municipio_names=["Campinas"]
            )
        )
        bq = FakePipelineBQ(
            municipio_rows=[
                {"nome": "Campinas", "sigla_uf": "SP", "id_municipio": "3509502"}
            ],
            lead_rows=LEAD_ROWS,
        )
        result = run(
            "dentistas em Campinas",
            PUBLIC,
            extract_client=extract,
            cnae_search=_cnae_search_recorder([("8630-5/04", "Odonto", 0.9)]),
            bq_client=bq,
        )
        assert set(result.timings_ms) == {
            "extract",
            "cnae",
            "municipios",
            "snapshot",
            "query",
            "score",
        }
        assert result.to_dict()["timings_ms"] == result.timings_ms

    def test_warmup_logs_failures_without_raising(self, monkeypatch, caplog):
        from quimera import cnae, extract, pipeline, query

        def boom():
            raise RuntimeError("sem credencial")

        monkeypatch.setattr(cnae, "load_index", boom)
        monkeypatch.setattr(extract, "_default_client", lambda: object())
        monkeypatch.setattr(cnae, "vertex_embedder", boom)
        monkeypatch.setattr(query, "_default_client", lambda: object())
        monkeypatch.setattr(query, "_default_municipality_directory", lambda: ())
        monkeypatch.setattr(pipeline, "read_leads_snapshot", lambda tables: {})
        timings = pipeline.warmup()
        assert set(timings) == {
            "cnae_index",
            "gemini",
            "embedding",
            "bigquery",
            "municipios",
            "snapshot",
        }
        assert "aquecimento falhou em cnae_index" in caplog.text
