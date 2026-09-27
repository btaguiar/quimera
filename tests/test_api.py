"""Testes da API com TestClient: endpoints, proteções e modo cache."""

from __future__ import annotations

import asyncio
import json
import time

import pytest
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
        request_timeout_s=30.0,
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


def _ts_app(verifier, **overrides):
    extract, search, bq = _happy_clients()
    return create_app(
        config=_config(turnstile_secret_key="ts-secret", **overrides),
        extract_client=extract,
        cnae_search=search,
        bq_client=bq,
        turnstile_verify=verifier,
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

    def test_query_cap_is_limited_by_remaining_budget(self, monkeypatch):
        monkeypatch.delenv("MAX_BYTES_BILLED", raising=False)
        app = _app(daily_bytes_budget=5000)
        bq = app.state.pipeline_deps["bq_client"]
        resp = TestClient(app).post("/leads", json={"request": "empresas em SP"})
        assert resp.status_code == 200
        _, job_config = bq.executed[0]
        assert job_config.maximum_bytes_billed == 5000

    def test_query_cap_is_per_query_ceiling_when_budget_is_larger(self, monkeypatch):
        monkeypatch.setenv("MAX_BYTES_BILLED", "2048")
        app = _app()
        bq = app.state.pipeline_deps["bq_client"]
        TestClient(app).post("/leads", json={"request": "empresas em SP"})
        _, job_config = bq.executed[0]
        assert job_config.maximum_bytes_billed == 2048

    def test_query_above_remaining_budget_returns_503_without_running(
        self, monkeypatch
    ):
        monkeypatch.delenv("MAX_BYTES_BILLED", raising=False)
        app = _app(daily_bytes_budget=500)
        bq = app.state.pipeline_deps["bq_client"]
        resp = TestClient(app).post("/leads", json={"request": "empresas em SP"})
        assert resp.status_code == 503
        data = resp.json()
        assert data["error"] == "orçamento diário"
        assert "500" in data["reason"]
        assert bq.executed == []

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


def _slow_cnae_search(results, delay_s=1.0):
    def search(query, k):
        time.sleep(delay_s)
        return results

    return search


class TestTimeout:
    def test_slow_pipeline_returns_504(self):
        extract = FakeGenaiClient(_extraction_payload(cnae_query="clínicas"))
        app = create_app(
            config=_config(request_timeout_s=0.05),
            extract_client=extract,
            cnae_search=_slow_cnae_search(CNAE_MATCHES),
            bq_client=FakePipelineBQ(lead_rows=[]),
        )
        client = TestClient(app)
        resp = client.post("/leads", json={"request": "clínicas em SP"})
        assert resp.status_code == 504
        data = resp.json()
        assert data["error"] == "timeout"


class TestPipelineErrors:
    def test_bytes_ceiling_exceeded_returns_503(self):
        extract = FakeGenaiClient(_extraction_payload(ufs=["SP"]))
        bq = FakePipelineBQ(lead_rows=[], dry_run_bytes=10 * 1024**3)
        app = create_app(
            config=_config(),
            extract_client=extract,
            cnae_search=_cnae_search(CNAE_MATCHES),
            bq_client=bq,
        )
        client = TestClient(app)
        resp = client.post("/leads", json={"request": "empresas em SP"})
        assert resp.status_code == 503
        assert resp.json()["error"] == "teto de bytes"

    def test_extraction_error_returns_502(self):
        extract = FakeGenaiClient("não é json")
        app = create_app(
            config=_config(),
            extract_client=extract,
            cnae_search=_cnae_search(CNAE_MATCHES),
            bq_client=FakePipelineBQ(),
        )
        client = TestClient(app)
        resp = client.post("/leads", json={"request": "empresas em SP"})
        assert resp.status_code == 502
        assert resp.json()["error"] == "erro de extração"

    def test_extraction_error_does_not_leak_model_output(self, caplog):
        import logging

        marker = "João Silva 11 99999-0000"
        extract = FakeGenaiClient(
            json.dumps(
                {"refused": False, "filters": {"campo_inventado": marker}},
                ensure_ascii=False,
            )
        )
        app = create_app(
            config=_config(),
            extract_client=extract,
            cnae_search=_cnae_search(CNAE_MATCHES),
            bq_client=FakePipelineBQ(),
        )
        with caplog.at_level(logging.DEBUG, logger="quimera"):
            resp = TestClient(app).post("/leads", json={"request": "empresas em SP"})
        assert resp.status_code == 502
        assert "99999" not in resp.text
        assert "99999" not in caplog.text


class TestUnexpectedErrors:
    def test_unexpected_pipeline_error_returns_500_envelope(self):
        class ExplodingClient:
            def __init__(self):
                self.calls = 0

            class _Models:
                def __init__(self, outer):
                    self._outer = outer

                def generate_content(self, **kwargs):
                    self._outer.calls += 1
                    raise RuntimeError("boom inesperado")

            @property
            def models(self):
                return self._Models(self)

        exploding = ExplodingClient()
        app = create_app(
            config=_config(),
            extract_client=exploding,
            cnae_search=_cnae_search(CNAE_MATCHES),
            bq_client=FakePipelineBQ(),
        )
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/leads", json={"request": "empresas em SP"})
        assert resp.status_code == 500
        data = resp.json()
        assert data["error"] == "erro interno"
        assert data["reason"]
        assert "boom" not in data["reason"]
        assert exploding.calls == 1


class TestLifecycle:
    def test_shutdown_event_shuts_down_executor(self):
        app = _app()
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200
        assert app.state.executor._shutdown is True

    def test_exception_through_lifespan_yield_still_shuts_down_executor(self):
        app = _app()
        executor = app.state.executor

        async def _drive():
            async with app.router.lifespan_context(app):
                raise RuntimeError("falha simulada após o startup")

        with pytest.raises(RuntimeError):
            asyncio.run(_drive())
        assert executor._shutdown is True


class TestStartupWarnings:
    def test_unset_api_token_logs_warning(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="quimera.api"):
            _app(api_token=None)
        assert any("API_TOKEN" in msg for msg in caplog.messages)

    def test_set_api_token_logs_no_warning(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="quimera.api"):
            _app(api_token="tok")
        assert not any("API_TOKEN" in msg for msg in caplog.messages)


class TestWarmup:
    """O 1º pedido do processo pagava ~16 s de clientes, índice e diretório
    (medido); o servidor aquece isso na inicialização, em segundo plano."""

    def test_startup_runs_warmup_when_enabled(self, monkeypatch):
        from quimera import pipeline

        calls = []
        monkeypatch.setattr(pipeline, "warmup", lambda: calls.append("ok"))
        extract, search, bq = _happy_clients()
        app = create_app(
            config=_config(),
            extract_client=extract,
            cnae_search=search,
            bq_client=bq,
            warmup=True,
        )
        with TestClient(app) as client:
            client.get("/health")
            client.app.state.executor.shutdown(wait=True)
        assert calls == ["ok"]

    def test_no_warmup_by_default(self, monkeypatch):
        from quimera import pipeline

        calls = []
        monkeypatch.setattr(pipeline, "warmup", lambda: calls.append("ok"))
        with TestClient(_app()) as client:
            client.get("/health")
        assert calls == []


class TestTurnstileAuth:
    def test_valid_turnstile_token_passes_without_api_token(self):
        client = TestClient(_ts_app(lambda token, secret, ip=None: True))
        resp = client.post(
            "/leads", json={"request": "clínicas em SP", "turnstile": "tok"}
        )
        assert resp.status_code == 200
        assert resp.json()["cached"] is False

    def test_invalid_turnstile_returns_401(self):
        client = TestClient(_ts_app(lambda token, secret, ip=None: False))
        resp = client.post(
            "/leads", json={"request": "clínicas em SP", "turnstile": "tok"}
        )
        assert resp.status_code == 401
        assert resp.json()["error"] == "unauthorized"
        assert "Turnstile" in resp.json()["reason"]

    def test_missing_turnstile_returns_401_when_configured(self):
        client = TestClient(_ts_app(lambda token, secret, ip=None: True))
        resp = client.post("/leads", json={"request": "clínicas em SP"})
        assert resp.status_code == 401

    def test_api_token_still_passes_when_turnstile_is_configured(self):
        client = TestClient(
            _ts_app(lambda token, secret, ip=None: False, api_token="segredo")
        )
        resp = client.post(
            "/leads",
            json={"request": "clínicas em SP"},
            headers={"X-Api-Token": "segredo"},
        )
        assert resp.status_code == 200

    def test_verifier_receives_token_secret_and_client_ip(self):
        chamadas = []

        def verifier(token, secret, ip=None):
            chamadas.append((token, secret, ip))
            return True

        client = TestClient(_ts_app(verifier))
        client.post(
            "/leads",
            json={"request": "clínicas em SP", "turnstile": "tok-1"},
            headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"},
        )
        assert chamadas == [("tok-1", "ts-secret", "5.6.7.8")]

    def test_malformed_body_json_with_turnstile_returns_401_not_500(self):
        client = TestClient(_ts_app(lambda token, secret, ip=None: True))
        resp = client.post(
            "/leads",
            content=b"{nao e json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401

    def test_no_auth_configured_still_open_with_warning(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="quimera.api"):
            client = TestClient(_app(api_token=None))
        resp = client.post("/leads", json={"request": "clínicas em SP"})
        assert resp.status_code == 200
        assert any("TURNSTILE" in msg or "API_TOKEN" in msg for msg in caplog.messages)


class TestSingleUseTokenInvariant:
    def test_schema_invalid_body_verifies_token_exactly_once(self):
        calls = []

        def verifier(token, secret, ip=None):
            calls.append(token)
            return True

        client = TestClient(_ts_app(verifier))
        resp = client.post("/leads", json={"request": "", "turnstile": "tok"})
        assert resp.status_code == 422
        assert calls == ["tok"]

    def test_missing_token_never_calls_verifier(self):
        calls = []

        def verifier(token, secret, ip=None):
            calls.append(token)
            return True

        client = TestClient(_ts_app(verifier))
        resp = client.post("/leads", json={"request": "clínicas em SP"})
        assert resp.status_code == 401
        assert calls == []

    def test_malformed_json_with_api_token_only_checks_auth_first(self):
        client = TestClient(_app(api_token="segredo"))
        resp = client.post(
            "/leads",
            content=b"{nao e json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401
        resp = client.post(
            "/leads",
            content=b"{nao e json",
            headers={"Content-Type": "application/json", "X-Api-Token": "segredo"},
        )
        assert resp.status_code == 422

    def test_oversized_token_never_reaches_verifier(self):
        calls = []

        def verifier(token, secret, ip=None):
            calls.append(token)
            return True

        client = TestClient(_ts_app(verifier))
        resp = client.post(
            "/leads", json={"request": "clínicas em SP", "turnstile": "x" * 3000}
        )
        assert resp.status_code == 401
        assert calls == []


class TestConfigEndpoint:
    def test_config_exposes_turnstile_site_key(self):
        client = TestClient(_app(turnstile_site_key="chave-publica"))
        resp = client.get("/config")
        assert resp.status_code == 200
        assert resp.json() == {"turnstile_site_key": "chave-publica"}
        assert resp.headers["cache-control"] == "no-store"

    def test_config_site_key_none_when_unset(self):
        resp = TestClient(_app()).get("/config")
        assert resp.json() == {"turnstile_site_key": None}


class TestFrontend:
    def test_root_serves_laudo_page(self):
        resp = TestClient(_app()).get("/")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert "Quimera — Laudo de Prospecção" in resp.text
        assert "Emitir laudo" in resp.text
        assert 'lang="pt-BR"' in resp.text

    def test_metrics_html_served(self):
        resp = TestClient(_app()).get("/metrics.html")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert "Métricas medidas" in resp.text

    def test_metrics_page_renders_from_api_json(self):
        client = TestClient(_app())
        html = client.get("/metrics.html").text
        js = client.get("/metrics.js")
        assert "Anexo A" in html
        assert "regra de ouro" in html.lower()
        assert js.status_code == 200
        assert "javascript" in js.headers["content-type"]
        assert "carregarMetricas" in js.text

    def test_static_assets_served(self):
        client = TestClient(_app())
        css = client.get("/style.css")
        js = client.get("/app.js")
        assert css.status_code == 200
        assert "text/css" in css.headers["content-type"]
        assert js.status_code == 200
        assert "javascript" in js.headers["content-type"]
        assert "--acento" in css.text
        assert "renderizarLaudo" in js.text
