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


class TestCacheHitSmoke:
    def test_second_identical_request_is_served_from_cache(self):
        app = _app()
        extract = app.state.pipeline_deps["extract_client"]
        client = TestClient(app)
        resp1 = client.post("/leads", json={"request": "empresas em SP"})
        resp2 = client.post("/leads", json={"request": "empresas em SP"})
        assert resp1.json()["cached"] is False
        assert resp2.json()["cached"] is True
        assert len(extract.calls) == 1
        assert resp2.json()["rows"] == resp1.json()["rows"]
