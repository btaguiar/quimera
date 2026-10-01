"""Testes do pipeline: extract → cnae → policy → municípios → cep → query → score."""

from __future__ import annotations

import json
from dataclasses import replace

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


def _uma_atividade():
    """Busca de CNAE falsa: a policy pública só consulta com atividade."""
    return _cnae_search_recorder([("8630-5/04", "Atividade odontológica", 0.9)])


def _run(bq, policy=PUBLIC, request="pedido", **filters):
    """Executa o pipeline com extração fixa nos ``filters`` e CNAE resolvido."""
    extract = FakeGenaiClient(_extraction_payload(**filters))
    cnae_search = _cnae_search_recorder(
        [("8630-5/01", "Atividade médica ambulatorial", 0.92)]
    )
    return run(
        request, policy, extract_client=extract, cnae_search=cnae_search, bq_client=bq
    )


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
        extract = FakeGenaiClient(
            _extraction_payload(cnae_query="dentistas", municipio_names=["Narnia"])
        )
        bq = FakePipelineBQ(
            municipio_rows=[
                {"nome": "Campinas", "sigla_uf": "SP", "id_municipio": "3509502"}
            ],
            lead_rows=LEAD_ROWS,
        )
        result = run(
            "empresas em Narnia",
            PUBLIC,
            extract_client=extract,
            cnae_search=_uma_atividade(),
            bq_client=bq,
        )
        assert result.municipio_resolution == {}
        assert result.rows == []
        assert bq.executed == []
        assert any("Narnia" in w for w in result.warnings)

    def test_partially_resolved_municipalities_warn_and_query(self):
        extract = FakeGenaiClient(
            _extraction_payload(
                cnae_query="dentistas", municipio_names=["Campinas", "Narnia"]
            )
        )
        bq = FakePipelineBQ(
            municipio_rows=[
                {"nome": "Campinas", "sigla_uf": "SP", "id_municipio": "3509502"}
            ],
            lead_rows=[],
        )
        result = run(
            "empresas",
            PUBLIC,
            extract_client=extract,
            cnae_search=_uma_atividade(),
            bq_client=bq,
        )
        assert result.filters.municipio_ids == ["3509502"]
        assert any("Narnia" in w for w in result.warnings)
        assert len(bq.executed) == 1

    def test_homonym_without_uf_includes_all_and_warns(self):
        extract = FakeGenaiClient(
            _extraction_payload(cnae_query="dentistas", municipio_names=["Santo André"])
        )
        bq = FakePipelineBQ(
            municipio_rows=[
                {"nome": "Santo André", "sigla_uf": "SP", "id_municipio": "3547807"},
                {"nome": "Santo André", "sigla_uf": "PB", "id_municipio": "2513851"},
            ],
            lead_rows=[],
        )
        result = run(
            "empresas",
            PUBLIC,
            extract_client=extract,
            cnae_search=_uma_atividade(),
            bq_client=bq,
        )
        assert sorted(result.filters.municipio_ids) == ["2513851", "3547807"]
        assert any("Informe a UF" in w for w in result.warnings)

    def test_media_or_grande_porte_warns_about_dataset_limit(self):
        extract = FakeGenaiClient(
            _extraction_payload(cnae_query="dentistas", ufs=["SP"], portes=["media"])
        )
        bq = FakePipelineBQ(lead_rows=[])
        result = run(
            "empresas médias",
            PUBLIC,
            extract_client=extract,
            cnae_search=_uma_atividade(),
            bq_client=bq,
        )
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

    def test_public_request_without_activity_does_not_query(self):
        # Sem CNAE o ranking lê todas as empresas da região (1,6–2,5 GB).
        extract = FakeGenaiClient(_extraction_payload(ufs=["SP"]))
        bq = FakePipelineBQ(lead_rows=LEAD_ROWS)
        result = run("empresas em SP", PUBLIC, extract_client=extract, bq_client=bq)
        assert result.refused is False
        assert result.rows == []
        assert bq.executed == []
        assert result.query_sql == ""
        assert any("Informe a atividade" in w for w in result.warnings)

    def test_private_request_without_activity_still_queries(self):
        extract = FakeGenaiClient(_extraction_payload(ufs=["SP"]))
        bq = FakePipelineBQ(lead_rows=LEAD_ROWS)
        result = run("empresas em SP", PRIVATE, extract_client=extract, bq_client=bq)
        assert bq.executed
        assert not any("Informe a atividade" in w for w in result.warnings)

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

        monkeypatch.setattr(cnae, "hybrid_candidates", fake_search)
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
        monkeypatch.setattr(cnae, "hybrid_candidates", lambda q, k: candidates)

        chamadas = []

        def fail(query, cands):
            chamadas.append(query)
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

        monkeypatch.setattr(cnae, "select_codes", fail)
        monkeypatch.setattr(pipeline, "SELECT_PAUSA_S", 0)
        assert [c for c, _, _ in pipeline.default_cnae_search("x", 5)] == ["a", "b"]
        assert len(chamadas) == pipeline.SELECT_TENTATIVAS

    def test_second_attempt_avoids_fallback(self, monkeypatch):
        # e2e_026: um 429 isolado mandava "material de construção" para o
        # corte por similaridade, que pôs representantes comerciais em 1º.
        from quimera import cnae, pipeline

        candidates = [("a", "A", 0.80), ("b", "B", 0.78), ("c", "C", 0.60)]
        monkeypatch.setattr(cnae, "hybrid_candidates", lambda q, k: candidates)
        respostas = iter([RuntimeError("429"), [candidates[2]]])

        def select(query, cands):
            r = next(respostas)
            if isinstance(r, Exception):
                raise r
            return r

        monkeypatch.setattr(cnae, "select_codes", select)
        monkeypatch.setattr(pipeline, "SELECT_PAUSA_S", 0)
        assert pipeline.default_cnae_search("x", 5) == [("c", "C", 0.60)]
        assert pipeline._selecao.fallback is False


class TestCostGuard:
    def test_bytes_budget_exceeded_propagates(self):
        extract = FakeGenaiClient(
            _extraction_payload(cnae_query="dentistas", ufs=["SP"])
        )
        bq = FakePipelineBQ(lead_rows=[], dry_run_bytes=10 * 1024**3)
        with pytest.raises(BytesBudgetExceededError):
            run(
                "empresas em SP",
                PUBLIC,
                extract_client=extract,
                cnae_search=_uma_atividade(),
                bq_client=bq,
                max_bytes_billed=1024,
            )
        assert bq.executed == []


class TestResultSerialization:
    def test_to_dict_is_json_serializable(self):
        extract = FakeGenaiClient(
            _extraction_payload(cnae_query="dentistas", ufs=["SP"])
        )
        bq = FakePipelineBQ(lead_rows=LEAD_ROWS)
        result = run(
            "empresas em SP",
            PUBLIC,
            extract_client=extract,
            cnae_search=_uma_atividade(),
            bq_client=bq,
        )
        data = json.loads(json.dumps(result.to_dict(), ensure_ascii=False))
        assert data["refused"] is False
        assert data["filters"]["ufs"] == ["SP"]
        assert data["cnae_matches"] == [["8630-5/04", "Atividade odontológica", 0.9]]
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


CEP_ROWS = [{"latitude": -23.56, "longitude": -46.65}]


class TestSinaisOnda1:
    def test_cep_center_passed_to_query(self):
        bq = FakePipelineBQ(lead_rows=LEAD_ROWS, cep_rows=CEP_ROWS)
        _run(bq, request="clínicas perto do CEP 01310-100", cnae_query="clínicas", cep_centro="01310100", raio_km=3)
        sql, _ = bq.executed[0]
        assert "ST_DWITHIN" in sql
        assert bq.cep_queries

    def test_unknown_cep_warns_and_skips_query(self):
        bq = FakePipelineBQ(cep_rows=[])
        result = _run(bq, request="clínicas perto do CEP 99999-999", cnae_query="clínicas", cep_centro="99999999", raio_km=3)
        assert not bq.executed
        assert any("CEP 99999999" in w for w in result.warnings)

    def test_unknown_cep_without_radius_keeps_raio_unset(self):
        # CEP ausente não aplica o padrão: raio_km fica None e não há aviso
        # contraditório de "padrão de 5 km" para um raio que não rodou.
        bq = FakePipelineBQ(cep_rows=[])
        result = _run(bq, request="clínicas perto do CEP 99999-999", cnae_query="clínicas", cep_centro="99999999")
        assert not bq.executed
        assert result.filters.raio_km is None
        assert any("CEP 99999999" in w for w in result.warnings)
        assert not any("5 km" in w for w in result.warnings)

    def test_invented_cep_is_dropped_and_radius_ignored(self):
        # e2e_027: "raio de 2 km do centro de Curitiba" sem CEP no pedido; o
        # Gemini devolvia 80000000 e o pedido voltava vazio.
        bq = FakePipelineBQ(lead_rows=LEAD_ROWS, cep_rows=CEP_ROWS)
        result = _run(
            bq,
            request="padarias num raio de 2 km do centro de Curitiba",
            cnae_query="padarias",
            cep_centro="80000000",
            raio_km=2,
        )
        assert result.filters.cep_centro is None
        assert result.filters.raio_km is None
        assert not bq.cep_queries
        assert bq.executed and "ST_DWITHIN" not in bq.executed[0][0]
        assert any("80000000" in w and "não aparece no pedido" in w for w in result.warnings)
        assert any("CEP de referência" in w for w in result.warnings)

    def test_cep_in_request_accepts_common_formats(self):
        for escrito in ("01310-100", "01310100", "01.310-100"):
            bq = FakePipelineBQ(lead_rows=LEAD_ROWS, cep_rows=CEP_ROWS)
            result = _run(
                bq,
                request=f"clínicas a 3 km do CEP {escrito}",
                cnae_query="clínicas",
                cep_centro="01310100",
                raio_km=3,
            )
            assert result.filters.cep_centro == "01310100", escrito
            assert bq.cep_queries, escrito

    def test_cep_must_match_whole_number_in_request(self):
        # Dígitos que só aparecem dentro de um número maior não contam.
        bq = FakePipelineBQ(lead_rows=LEAD_ROWS, cep_rows=CEP_ROWS)
        result = _run(
            bq,
            request="clínicas com capital acima de 9013101001",
            cnae_query="clínicas",
            cep_centro="01310100",
        )
        assert result.filters.cep_centro is None
        assert not bq.cep_queries

    def test_radius_without_cep_warns_and_is_ignored(self):
        bq = FakePipelineBQ(lead_rows=LEAD_ROWS)
        result = _run(bq, cnae_query="clínicas", raio_km=3)
        assert result.filters.raio_km is None
        assert bq.executed and "ST_DWITHIN" not in bq.executed[0][0]
        assert any("CEP de referência" in w for w in result.warnings)

    def test_cep_without_radius_uses_default(self):
        # raio padrão 5 km, com aviso
        bq = FakePipelineBQ(lead_rows=LEAD_ROWS, cep_rows=CEP_ROWS)
        result = _run(bq, request="clínicas perto do CEP 01310-100", cnae_query="clínicas", cep_centro="01310100")
        sql, job_config = bq.executed[0]
        assert "ST_DWITHIN" in sql
        raio_m = next(p for p in job_config.query_parameters if p.name == "raio_m")
        assert raio_m.value == 5000.0
        assert any("5 km" in w for w in result.warnings)

    def test_radius_warns_about_coverage(self):
        # aviso: "~9% dos estabelecimentos não têm coordenada e ficam de fora"
        bq = FakePipelineBQ(lead_rows=LEAD_ROWS, cep_rows=CEP_ROWS)
        result = _run(bq, request="clínicas perto do CEP 01310-100", cnae_query="clínicas", cep_centro="01310100", raio_km=3)
        assert "cep" in result.timings_ms
        assert any("9%" in w and "coordenada" in w for w in result.warnings)

    def test_bairros_without_municipio_warn_and_are_ignored(self):
        bq = FakePipelineBQ(lead_rows=LEAD_ROWS)
        result = _run(bq, cnae_query="clínicas", bairros=["Centro"])
        assert result.filters.bairros == []
        assert len(bq.executed) == 1
        assert "@bairros" not in bq.executed[0][0]
        assert any("bairros" in w.lower() for w in result.warnings)

    def test_public_mei_only_regime_warns_without_query(self):
        # Task 4, Step 3: regimes pedidos, todos removidos pela policy pública.
        bq = FakePipelineBQ(lead_rows=LEAD_ROWS)
        result = _run(bq, cnae_query="clínicas", regimes=["mei"])
        assert not bq.executed
        assert any("MEI" in w for w in result.warnings)

    def test_public_partial_mei_regime_warns_and_queries(self):
        # Remoção parcial: "simples" sobrevive à policy e a query roda, mas o
        # MEI removido precisa estar nos avisos.
        bq = FakePipelineBQ(lead_rows=LEAD_ROWS)
        result = _run(bq, cnae_query="clínicas", regimes=["mei", "simples"])
        assert result.filters.regimes == ["simples"]
        assert len(bq.executed) == 1
        assert any("MEI" in w for w in result.warnings)


class TestQuerySql:
    def test_to_dict_exposes_parameterized_sql_of_last_query(self):
        extract = FakeGenaiClient(
            _extraction_payload(cnae_query="dentistas", ufs=["SP"])
        )
        bq = FakePipelineBQ()
        result = run(
            "empresas em SP",
            PUBLIC,
            extract_client=extract,
            cnae_search=_uma_atividade(),
            bq_client=bq,
        )
        assert bq.executed, "a query deveria ter rodado"
        assert result.query_sql == bq.executed[0][0]
        assert "@ufs" in result.query_sql
        assert result.to_dict()["query_sql"] == result.query_sql

    def test_refused_result_has_empty_query_sql(self):
        extract = FakeGenaiClient(
            json.dumps(
                {"refused": True, "refusal_reason": "pedido de dado pessoal"},
                ensure_ascii=False,
            )
        )
        result = run(
            "telefone do dono",
            PUBLIC,
            extract_client=extract,
            bq_client=FakePipelineBQ(),
        )
        assert result.query_sql == ""
        assert result.to_dict()["query_sql"] == ""


class TestRowLimit:
    """``limit`` da avaliação substitui o do LLM; o teto da policy segue valendo."""

    def _run(self, policy, limit):
        extract = FakeGenaiClient(
            _extraction_payload(cnae_query="padarias", ufs=["SP"], limit=10)
        )
        cnae_search = _cnae_search_recorder([("1091-1/02", "Padaria", 0.9)])
        bq = FakePipelineBQ(lead_rows=LEAD_ROWS)
        return run(
            "padarias em SP",
            policy,
            extract_client=extract,
            cnae_search=cnae_search,
            bq_client=bq,
            limit=limit,
        )

    def test_overrides_llm_limit_up_to_policy_cap(self):
        policy = replace(PUBLIC, max_rows=200)
        assert self._run(policy, 200).filters.limit == 200
        assert self._run(PUBLIC, 200).filters.limit == 50

    def test_without_limit_keeps_llm_value(self):
        assert self._run(PUBLIC, None).filters.limit == 10


class TestUfJuntoDoMunicipio:
    """UF escrita junto da cidade: colada no nome ou fora de ``ufs``."""

    @pytest.mark.parametrize(
        "nome, esperado",
        [
            ("Extrema/MG", ("Extrema", "MG")),
            ("Ouro (SC)", ("Ouro", "SC")),
            ("Valença - BA", ("Valença", "BA")),
            ("Valença, ba", ("Valença", "BA")),
            ("Embu-Guaçu", ("Embu-Guaçu", None)),
            ("Campinas", ("Campinas", None)),
            ("Santo André/XX", ("Santo André/XX", None)),
        ],
    )
    def test_separar_uf_do_nome(self, nome, esperado):
        from quimera.pipeline import separar_uf_do_nome

        assert separar_uf_do_nome(nome) == esperado

    @pytest.mark.parametrize(
        "pedido, nome, esperado",
        [
            ("pousadas em Valença, BA com 2 anos", "Valença", ["BA"]),
            ("marmitex em Sobradinho/RS", "Sobradinho", ["RS"]),
            ("praia grande - sp, padarias", "Praia Grande", ["SP"]),
            ("padarias em Campinas com mais de 2 anos", "Campinas", []),
            ("padarias em Campinas, se possível", "Campinas", ["SE"]),
        ],
    )
    def test_ufs_apos_nome(self, pedido, nome, esperado):
        from quimera.pipeline import ufs_apos_nome

        assert ufs_apos_nome(pedido, nome) == esperado

    MUNICIPIOS = [
        {"nome": "Valença", "sigla_uf": "BA", "id_municipio": "2932903"},
        {"nome": "Valença", "sigla_uf": "RJ", "id_municipio": "3306107"},
        {"nome": "Extrema", "sigla_uf": "MG", "id_municipio": "3125101"},
    ]

    def test_glued_uf_resolves_the_city(self):
        bq = FakePipelineBQ(municipio_rows=self.MUNICIPIOS, lead_rows=LEAD_ROWS)
        result = _run(bq, cnae_query="cafeterias", municipio_names=["Extrema/MG"])
        assert result.municipio_resolution == {"Extrema": ["3125101"]}
        assert result.filters.municipio_names == ["Extrema"]
        assert not any("não encontrado" in w for w in result.warnings)

    def test_uf_written_after_homonym_picks_one_city(self):
        bq = FakePipelineBQ(municipio_rows=self.MUNICIPIOS, lead_rows=LEAD_ROWS)
        result = _run(
            bq,
            request="pousadas em Valença, BA",
            cnae_query="pousadas",
            municipio_names=["Valença"],
        )
        assert result.municipio_resolution == {"Valença": ["2932903"]}
        assert not any("existe em" in w for w in result.warnings)

    def test_homonym_without_uf_still_warns(self):
        bq = FakePipelineBQ(municipio_rows=self.MUNICIPIOS, lead_rows=LEAD_ROWS)
        result = _run(
            bq, request="pousadas em Valença", cnae_query="pousadas", municipio_names=["Valença"]
        )
        assert result.municipio_resolution == {"Valença": ["2932903", "3306107"]}
        assert any("existe em 2" in w for w in result.warnings)


class TestCnaeFallbackFlag:
    """O resultado marca quando a seleção de CNAE caiu no plano B."""

    def _run(self, monkeypatch, select):
        from quimera import cnae

        monkeypatch.setattr(
            cnae, "hybrid_candidates", lambda q, k: [("1091-1/02", "Padaria", 0.9)]
        )
        monkeypatch.setattr(cnae, "select_codes", select)
        extract = FakeGenaiClient(_extraction_payload(cnae_query="padarias", ufs=["SP"]))
        return run(
            "padarias em SP",
            PUBLIC,
            extract_client=extract,
            bq_client=FakePipelineBQ(lead_rows=LEAD_ROWS),
        )

    def test_selection_ok(self, monkeypatch):
        result = self._run(monkeypatch, lambda q, c: c)
        assert result.cnae_fallback is False
        assert result.to_dict()["cnae_fallback"] is False

    def test_selection_failure_is_flagged(self, monkeypatch):
        from quimera import pipeline

        monkeypatch.setattr(pipeline, "SELECT_PAUSA_S", 0)

        def falha(q, c):
            raise TimeoutError

        result = self._run(monkeypatch, falha)
        assert result.cnae_fallback is True
        assert result.filters.cnae_codes == ["1091-1/02"]


class TestReescritaDaAtividade:
    """Seleção vazia (gíria, nome informal) -> reescrita na CNAE e nova busca."""

    def _prepara(self, monkeypatch, selecoes, reescrita="bares e estabelecimentos de bebidas"):
        from quimera import cnae, pipeline

        buscas, julgadas, reescritas = [], [], []

        def busca(q, k):
            buscas.append(q)
            return [("5611-2/04" if "bares" in q else "9999-9/99", "X", 0.9)]

        def seleciona(atividade, cands):
            julgadas.append(atividade)
            return selecoes.pop(0)(cands)

        def reescreve(atividade):
            reescritas.append(atividade)
            if isinstance(reescrita, Exception):
                raise reescrita
            return reescrita

        monkeypatch.setattr(cnae, "hybrid_candidates", busca)
        monkeypatch.setattr(cnae, "select_codes", seleciona)
        monkeypatch.setattr(cnae, "reformulate_activity", reescreve)
        monkeypatch.setattr(pipeline, "SELECT_PAUSA_S", 0)
        return pipeline, buscas, julgadas, reescritas

    def test_empty_selection_rewrites_and_searches_again(self, monkeypatch):
        pipeline, buscas, julgadas, reescritas = self._prepara(
            monkeypatch, [lambda c: [], lambda c: c]
        )
        assert [c for c, _, _ in pipeline.default_cnae_search("botecos", 5)] == ["5611-2/04"]
        assert reescritas == ["botecos"]
        assert buscas == ["botecos", "bares e estabelecimentos de bebidas"]
        # a seleção julga com o termo original e a reescrita juntos
        assert julgadas[1] == "botecos (bares e estabelecimentos de bebidas)"
        assert pipeline._selecao.reformulada == "bares e estabelecimentos de bebidas"

    def test_selection_with_result_does_not_rewrite(self, monkeypatch):
        pipeline, _, _, reescritas = self._prepara(monkeypatch, [lambda c: c])
        assert pipeline.default_cnae_search("padarias", 5)
        assert reescritas == []
        assert pipeline._selecao.reformulada is None

    def test_rewrite_failure_keeps_empty(self, monkeypatch):
        pipeline, _, _, _ = self._prepara(
            monkeypatch, [lambda c: []], reescrita=TimeoutError()
        )
        assert pipeline.default_cnae_search("botecos", 5) == []
        assert pipeline._selecao.fallback is False

    def test_same_text_after_rewrite_does_not_search_again(self, monkeypatch):
        pipeline, buscas, _, _ = self._prepara(
            monkeypatch, [lambda c: []], reescrita="Botecos"
        )
        assert pipeline.default_cnae_search("botecos", 5) == []
        assert buscas == ["botecos"]

    def test_result_records_rewrite(self, monkeypatch):
        from quimera import cnae

        monkeypatch.setattr(
            cnae, "hybrid_candidates",
            lambda q, k: [("5611-2/04", "Bares", 0.9)] if "bares" in q else [("x", "X", 0.9)],
        )
        respostas = iter([[], [("5611-2/04", "Bares", 0.9)]])
        monkeypatch.setattr(cnae, "select_codes", lambda a, c: next(respostas))
        monkeypatch.setattr(cnae, "reformulate_activity", lambda a: "bares")
        extract = FakeGenaiClient(_extraction_payload(cnae_query="botecos", ufs=["SP"]))
        result = run(
            "botecos em SP", PUBLIC, extract_client=extract,
            bq_client=FakePipelineBQ(lead_rows=LEAD_ROWS),
        )
        assert result.filters.cnae_codes == ["5611-2/04"]
        assert result.to_dict()["cnae_reformulada"] == "bares"


class TestCompletarDoTexto:
    """A extração perdeu a última condição: o texto do pedido completa."""

    def test_fills_only_what_extraction_left_empty(self):
        from quimera.filters import LeadFilters
        from quimera.pipeline import completar_do_texto

        f = LeadFilters(regimes=["fora_simples"], min_age_years=3)
        novo, campos = completar_do_texto(
            "padarias fora do Simples e com capital acima de R$ 500 mil e há mais de 8 anos", f
        )
        assert novo.min_capital == 500_000
        assert novo.min_age_years == 3  # o do modelo fica
        assert campos == ["min_capital"]

    def test_never_creates_inverted_age_range(self):
        from quimera.filters import LeadFilters
        from quimera.pipeline import completar_do_texto

        f = LeadFilters(max_age_years=2)
        novo, campos = completar_do_texto("padarias há mais de 5 anos", f)
        assert novo.min_age_years is None and campos == []

    def test_pipeline_records_completed_fields(self):
        extract = FakeGenaiClient(
            _extraction_payload(cnae_query="padarias", ufs=["SP"], regimes=["fora_simples"])
        )
        result = run(
            "padarias em SP fora do Simples e com capital acima de R$ 500 mil",
            PUBLIC,
            extract_client=extract,
            cnae_search=_uma_atividade(),
            bq_client=FakePipelineBQ(lead_rows=LEAD_ROWS),
        )
        assert result.filters.min_capital == 500_000
        assert result.to_dict()["filtros_completados"] == ["min_capital"]
