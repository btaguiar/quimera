"""Testes das proteções puras da API (sem FastAPI, sem estado)."""

from __future__ import annotations

from quimera.api.protections import (
    ApiConfig,
    normalize_request,
    request_hash,
    token_ok,
)

ENV_VARS = (
    "API_TOKEN",
    "RATE_LIMIT_MAX",
    "RATE_LIMIT_WINDOW_S",
    "CACHE_TTL_S",
    "DAILY_BYTES_BUDGET",
    "REQUEST_TIMEOUT_S",
)


class TestNormalizeRequest:
    def test_collapses_whitespace(self):
        assert normalize_request("  clínicas   em  \nSP ") == "clínicas em SP"

    def test_equivalent_requests_share_hash(self):
        a = request_hash(normalize_request("clínicas em SP"))
        b = request_hash(normalize_request("clínicas  em SP"))
        assert a == b
        assert request_hash("x") != request_hash("y")


class TestTokenOk:
    def test_unset_expected_disables_check(self):
        assert token_ok(None, None) is True
        assert token_ok("qualquer coisa", None) is True

    def test_missing_or_wrong_token_fails(self):
        assert token_ok(None, "segredo") is False
        assert token_ok("errado", "segredo") is False

    def test_correct_token_passes(self):
        assert token_ok("segredo", "segredo") is True


class TestApiConfigFromEnv:
    def test_defaults(self, monkeypatch):
        for var in ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        config = ApiConfig.from_env()
        assert config.api_token is None
        assert config.rate_limit_max == 10
        assert config.rate_limit_window_s == 3600
        assert config.cache_ttl_s == 86400
        assert config.daily_bytes_budget == 10 * 1024**3
        assert config.request_timeout_s == 60.0

    def test_reads_environment(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "tok")
        monkeypatch.setenv("RATE_LIMIT_MAX", "3")
        monkeypatch.setenv("DAILY_BYTES_BUDGET", "2048")
        config = ApiConfig.from_env()
        assert config.api_token == "tok"
        assert config.rate_limit_max == 3
        assert config.daily_bytes_budget == 2048

    def test_empty_api_token_means_disabled(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "")
        assert ApiConfig.from_env().api_token is None
