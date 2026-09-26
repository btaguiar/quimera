"""Testes da API com TestClient: endpoints, proteções e modo cache."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from quimera.api import create_app
from quimera.api.protections import ApiConfig

from fakes import FakeGenaiClient, FakePipelineBQ


def _config(**overrides) -> ApiConfig:
    base = dict(
        api_token=None,
        rate_limit_max=100,
        rate_limit_window_s=3600,
        cache_ttl_s=3600,
        daily_bytes_budget=10 * 1024**3,
        request_timeout_s=10.0,
    )
    base.update(overrides)
    return ApiConfig(**base)


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


def _extraction_payload(**filters) -> str:
    return json.dumps({"refused": False, "filters": filters}, ensure_ascii=False)


def _cnae_search(results):
    calls = []

    def search(query, k):
        calls.append((query, k))
        return results

    search.calls = calls
    return search


CNAE_MATCHES = [
    ("8630-5/01", "Atividade médica ambulatorial odontológica", 0.92),
    ("8630-5/02", "Atividade médica ambulatorial restrita a consultos", 0.81),
]


def _happy_clients():
    extract = FakeGenaiClient(
        _extraction_payload(cnae_query="clínicas odontológicas", ufs=["SP"])
    )
    search = _cnae_search(CNAE_MATCHES)
    bq = FakePipelineBQ(lead_rows=LEAD_ROWS)
    return extract, search, bq


def _app(**overrides):
    extract, search, bq = _happy_clients()
    return create_app(
        config=_config(**overrides),
        extract_client=extract,
        cnae_search=search,
        bq_client=bq,
    )


class TestHealth:
    def test_health_reports_version_and_budget(self):
        client = TestClient(_app())
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"]
        assert data["cache_mode"] is False
        assert data["budget_remaining_bytes"] == 10 * 1024**3


class TestMetrics:
    def test_metrics_serves_phase2_results(self, tmp_path, monkeypatch):
        (tmp_path / "results").mkdir()
        (tmp_path / "results" / "extraction_m1.json").write_text(
            json.dumps({"suite": "extraction", "metrics": {"n_cases": 45}}),
            encoding="utf-8",
        )
        (tmp_path / "thresholds.json").write_text(
            json.dumps({"overall_field_accuracy": 0.85}), encoding="utf-8"
        )
        monkeypatch.setenv("EVAL_DIR", str(tmp_path))
        client = TestClient(_app())
        resp = client.get("/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["thresholds"]["overall_field_accuracy"] == 0.85
        assert data["extraction"][0]["metrics"]["n_cases"] == 45


class TestCreateAppLazyImport:
    def test_package_reexports_create_app(self):
        import quimera.api

        assert callable(quimera.api.create_app)


class TestLeadsHappyPath:
    def test_post_leads_runs_pipeline_and_serializes(self):
        app = _app()
        client = TestClient(app)
        resp = client.post("/leads", json={"request": "clínicas odontológicas em SP"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["refused"] is False
        assert data["cached"] is False
        assert data["policy"] == "public"
        assert data["filters"]["ufs"] == ["SP"]
        assert data["filters"]["cnae_codes"] == ["8630-5/01", "8630-5/02"]
        assert data["cnae_matches"][0][0] == "8630-5/01"
        assert [r["razao_social"] for r in data["rows"]] == [
            "CLINICA ALFA",
            "CLINICA BETA",
        ]
        assert data["rows"][0]["score"] >= data["rows"][1]["score"]
        assert data["bytes_billed"] == 1000
        assert data["cache_mode"] is False

    def test_post_leads_uses_injected_cnae_search(self):
        app = _app()
        client = TestClient(app)
        client.post("/leads", json={"request": "clínicas odontológicas"})
        assert app.state.pipeline_deps["cnae_search"].calls == [
            ("clínicas odontológicas", 5)
        ]


class TestLeadsRefusal:
    def test_personal_data_request_is_refused_with_200(self):
        extract = FakeGenaiClient(
            json.dumps(
                {"refused": True, "refusal_reason": "pedido de dado pessoal"},
                ensure_ascii=False,
            )
        )
        app = create_app(
            config=_config(),
            extract_client=extract,
            cnae_search=_cnae_search(CNAE_MATCHES),
            bq_client=FakePipelineBQ(),
        )
        client = TestClient(app)
        resp = client.post("/leads", json={"request": "telefone do dono"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["refused"] is True
        assert data["refusal_reason"] == "pedido de dado pessoal"
        assert data["cached"] is False

    def test_refusal_is_not_cached_or_budgeted(self):
        extract = FakeGenaiClient(
            json.dumps(
                {"refused": True, "refusal_reason": "pedido de dado pessoal"},
                ensure_ascii=False,
            )
        )
        app = create_app(
            config=_config(),
            extract_client=extract,
            cnae_search=_cnae_search(CNAE_MATCHES),
            bq_client=FakePipelineBQ(),
        )
        client = TestClient(app)
        client.post("/leads", json={"request": "telefone do dono"})
        client.post("/leads", json={"request": "telefone do dono"})
        assert len(extract.calls) == 2
        health = TestClient(app).get("/health").json()
        assert health["budget_remaining_bytes"] == 10 * 1024**3


class TestTokenProtection:
    def test_wrong_token_returns_401(self):
        client = TestClient(_app(api_token="segredo"))
        resp = client.post(
            "/leads",
            json={"request": "clínicas em SP"},
            headers={"X-Api-Token": "errado"},
        )
        assert resp.status_code == 401
        assert resp.json()["error"] == "unauthorized"
        assert resp.json()["reason"]

    def test_missing_token_returns_401(self):
        client = TestClient(_app(api_token="segredo"))
        resp = client.post("/leads", json={"request": "clínicas em SP"})
        assert resp.status_code == 401

    def test_correct_token_passes(self):
        client = TestClient(_app(api_token="segredo"))
        resp = client.post(
            "/leads",
            json={"request": "clínicas em SP"},
            headers={"X-Api-Token": "segredo"},
        )
        assert resp.status_code == 200

    def test_unset_token_disables_check(self):
        client = TestClient(_app(api_token=None))
        resp = client.post("/leads", json={"request": "clínicas em SP"})
        assert resp.status_code == 200

    def test_401_wins_over_422_when_token_wrong_and_body_malformed(self):
        client = TestClient(_app(api_token="segredo"))
        resp = client.post(
            "/leads",
            json={"request": ""},
            headers={"X-Api-Token": "errado"},
        )
        assert resp.status_code == 401
        data = resp.json()
        assert data["error"] == "unauthorized"
        assert data["reason"]


class TestBodyValidation:
    def test_empty_request_returns_422(self):
        client = TestClient(_app())
        resp = client.post("/leads", json={"request": ""})
        assert resp.status_code == 422
        assert resp.json()["error"] == "validação"
        assert resp.json()["reason"]

    def test_too_long_request_returns_422(self):
        client = TestClient(_app())
        resp = client.post("/leads", json={"request": "x" * 501})
        assert resp.status_code == 422

    def test_missing_request_field_returns_422(self):
        client = TestClient(_app())
        resp = client.post("/leads", json={})
        assert resp.status_code == 422


class TestRateLimit:
    def test_fourth_request_within_window_returns_429(self):
        client = TestClient(_app(rate_limit_max=3))
        for _ in range(3):
            resp = client.post("/leads", json={"request": "empresas em SP"})
            assert resp.status_code == 200
        resp = client.post("/leads", json={"request": "empresas em RJ"})
        assert resp.status_code == 429
        assert resp.json()["error"] == "rate limit"
        assert int(resp.headers["Retry-After"]) > 0
        assert "3 requisições" in resp.json()["reason"]

    def test_cache_hit_does_not_help_after_rate_limit(self):
        client = TestClient(_app(rate_limit_max=1))
        client.post("/leads", json={"request": "empresas em SP"})
        resp = client.post("/leads", json={"request": "empresas em SP"})
        assert resp.status_code == 429

    def test_other_ip_is_not_affected(self):
        client = TestClient(_app(rate_limit_max=1))
        resp = client.post("/leads", json={"request": "empresas em SP"})
        assert resp.status_code == 200
        resp = client.post(
            "/leads",
            json={"request": "empresas em SP"},
            headers={"X-Forwarded-For": "outro-ip, proxy"},
        )
        assert resp.status_code == 200

    def test_forwarded_for_last_hop_wins(self):
        client = TestClient(_app(rate_limit_max=1))
        resp = client.post(
            "/leads",
            json={"request": "empresas em SP"},
            headers={"X-Forwarded-For": "fake-1, 5.6.7.8"},
        )
        assert resp.status_code == 200
        resp = client.post(
            "/leads",
            json={"request": "empresas em RJ"},
            headers={"X-Forwarded-For": "fake-2, 5.6.7.8"},
        )
        assert resp.status_code == 429

    def test_rate_limit_precedes_body_validation(self):
        client = TestClient(_app(rate_limit_max=1))
        resp = client.post("/leads", json={"request": "empresas em SP"})
        assert resp.status_code == 200
        resp = client.post("/leads", json={"request": ""})
        assert resp.status_code == 429

    def test_rate_limit_runs_after_token_check(self):
        client = TestClient(_app(api_token="segredo", rate_limit_max=1))
        resp = client.post(
            "/leads",
            json={"request": "empresas em SP"},
            headers={"X-Api-Token": "errado"},
        )
        assert resp.status_code == 401
        resp = client.post(
            "/leads",
            json={"request": "empresas em SP"},
            headers={"X-Api-Token": "segredo"},
        )
        assert resp.status_code == 200


class TestBudgetAndCacheMode:
    def test_budget_debited_after_real_run(self):
        app = _app()
        client = TestClient(app)
        client.post("/leads", json={"request": "empresas em SP"})
        health = client.get("/health").json()
        assert health["budget_remaining_bytes"] == 10 * 1024**3 - 1000

    def test_budget_exhausted_blocks_new_requests_with_503(self):
        client = TestClient(_app(daily_bytes_budget=1000))
        resp = client.post("/leads", json={"request": "empresas em SP"})
        assert resp.status_code == 200
        health = client.get("/health").json()
        assert health["cache_mode"] is True
        resp = client.post("/leads", json={"request": "empresas em RJ"})
        assert resp.status_code == 503
        data = resp.json()
        assert data["error"] == "cache mode"
        assert "orçamento" in data["reason"]

    def test_cache_hit_still_served_in_cache_mode(self):
        client = TestClient(_app(daily_bytes_budget=1000))
        client.post("/leads", json={"request": "empresas em SP"})
        resp = client.post("/leads", json={"request": "empresas em SP"})
        assert resp.status_code == 200
        assert resp.json()["cached"] is True

    def test_cache_mode_blocks_would_be_refusals_without_llm_call(self):
        extract = FakeGenaiClient(
            json.dumps(
                {"refused": True, "refusal_reason": "pedido de dado pessoal"},
                ensure_ascii=False,
            )
        )
        app = create_app(
            config=_config(daily_bytes_budget=0),
            extract_client=extract,
            cnae_search=_cnae_search(CNAE_MATCHES),
            bq_client=FakePipelineBQ(),
        )
        client = TestClient(app)
        resp = client.post("/leads", json={"request": "telefone do dono"})
        assert resp.status_code == 503
        assert resp.json()["error"] == "cache mode"
        assert len(extract.calls) == 0


class TestCache:
    def test_second_identical_request_is_cached(self):
        app = _app()
        extract = app.state.pipeline_deps["extract_client"]
        bq = app.state.pipeline_deps["bq_client"]
        client = TestClient(app)
        resp1 = client.post("/leads", json={"request": "empresas em SP"})
        resp2 = client.post("/leads", json={"request": "empresas em SP"})
        assert resp1.json()["cached"] is False
        assert resp2.json()["cached"] is True
        assert len(extract.calls) == 1
        assert len(bq.executed) == 1

    def test_normalization_makes_variants_share_cache(self):
        client = TestClient(_app())
        client.post("/leads", json={"request": "empresas em SP"})
        resp = client.post("/leads", json={"request": "empresas   em SP"})
        assert resp.json()["cached"] is True

    def test_different_request_is_not_cached(self):
        client = TestClient(_app())
        client.post("/leads", json={"request": "empresas em SP"})
        resp = client.post("/leads", json={"request": "empresas em RJ"})
        assert resp.json()["cached"] is False

    def test_cached_response_keeps_payload_shape(self):
        client = TestClient(_app())
        first = client.post("/leads", json={"request": "empresas em SP"}).json()
        cached = client.post("/leads", json={"request": "empresas em SP"}).json()
        assert cached["rows"] == first["rows"]
        assert cached["filters"] == first["filters"]
        assert cached["bytes_billed"] == first["bytes_billed"]
        assert cached["cache_mode"] is False
