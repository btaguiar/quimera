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
