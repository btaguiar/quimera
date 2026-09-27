"""Testes da verificação do Turnstile com MockTransport (sem rede)."""

from __future__ import annotations

import logging
import sys

import httpx

from quimera.api.turnstile import TIMEOUT_S, verify


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


class _StubResponse:
    def __init__(self, payload, status_error=None):
        self._payload = payload
        self._status_error = status_error

    def raise_for_status(self):
        if self._status_error is not None:
            raise self._status_error

    def json(self):
        return self._payload


def _stub_client_class(record, *, response=None, post_error=None, close_error=None):
    class StubClient:
        def __init__(self, **kwargs):
            record["timeout"] = kwargs.get("timeout")
            record["closed"] = False

        def post(self, url, data=None):
            record["url"] = url
            record["data"] = data
            if post_error is not None:
                raise post_error
            return response

        def close(self):
            record["closed"] = True
            if close_error is not None:
                raise close_error

    return StubClient


class TestVerify:
    def test_success_true_passes(self):
        client = _client(lambda request: httpx.Response(200, json={"success": True}))
        assert verify("token-ok", "segredo", client=client) is True

    def test_success_false_fails(self):
        client = _client(lambda request: httpx.Response(200, json={"success": False}))
        assert verify("token-ok", "segredo", client=client) is False

    def test_empty_or_missing_token_fails_without_request(self):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"success": True})

        assert verify(None, "segredo", client=_client(handler)) is False
        assert verify("", "segredo", client=_client(handler)) is False
        assert seen == []

    def test_network_error_fails_closed(self):
        def handler(request):
            raise httpx.ConnectError("sem rede")

        assert verify("token-ok", "segredo", client=_client(handler)) is False

    def test_malformed_json_fails_closed(self):
        client = _client(lambda request: httpx.Response(200, text="não é json"))
        assert verify("token-ok", "segredo", client=client) is False

    def test_http_error_status_fails_closed(self):
        client = _client(lambda request: httpx.Response(500, json={"success": True}))
        assert verify("token-ok", "segredo", client=client) is False

    def test_remote_ip_is_sent_as_form_field(self):
        captured = {}

        def handler(request):
            captured["body"] = request.read().decode("utf-8")
            return httpx.Response(200, json={"success": True})

        assert verify("token-ok", "segredo", "5.6.7.8", client=_client(handler)) is True
        assert "remoteip=5.6.7.8" in captured["body"]
        assert "secret=segredo" in captured["body"]
        assert "response=token-ok" in captured["body"]

    def test_no_remote_ip_no_field(self):
        captured = {}

        def handler(request):
            captured["body"] = request.read().decode("utf-8")
            return httpx.Response(200, json={"success": True})

        verify("token-ok", "segredo", None, client=_client(handler))
        assert "remoteip" not in captured["body"]


class TestDefaultClientPath:
    def test_own_client_uses_timeout_and_closes(self, monkeypatch):
        record = {}
        stub = _stub_client_class(record, response=_StubResponse({"success": True}))
        monkeypatch.setattr(httpx, "Client", stub)
        assert verify("token-ok", "segredo") is True
        assert record["timeout"] == TIMEOUT_S == 5.0
        assert record["closed"] is True

    def test_post_error_fails_closed_and_closes(self, monkeypatch):
        record = {}
        stub = _stub_client_class(record, post_error=httpx.ConnectError("sem rede"))
        monkeypatch.setattr(httpx, "Client", stub)
        assert verify("token-ok", "segredo") is False
        assert record["closed"] is True

    def test_close_error_does_not_escape_on_success(self, monkeypatch):
        record = {}
        stub = _stub_client_class(
            record,
            response=_StubResponse({"success": True}),
            close_error=RuntimeError("falha ao fechar"),
        )
        monkeypatch.setattr(httpx, "Client", stub)
        assert verify("token-ok", "segredo") is True
        assert record["closed"] is True

    def test_close_error_keeps_fail_closed_on_post_error(self, monkeypatch):
        record = {}
        stub = _stub_client_class(
            record,
            post_error=httpx.ConnectError("sem rede"),
            close_error=RuntimeError("falha ao fechar"),
        )
        monkeypatch.setattr(httpx, "Client", stub)
        assert verify("token-ok", "segredo") is False
        assert record["closed"] is True

    def test_injected_client_is_never_closed(self):
        record = {}
        stub = _stub_client_class(record, response=_StubResponse({"success": True}))
        assert verify("token-ok", "segredo", client=stub()) is True
        assert record["closed"] is False


class TestFailureLogging:
    def test_missing_httpx_logs_error(self, monkeypatch, caplog):
        monkeypatch.setitem(sys.modules, "httpx", None)
        with caplog.at_level(logging.DEBUG, logger="quimera.api.turnstile"):
            assert verify("token-ok", "segredo") is False
        assert caplog.records[-1].levelno == logging.ERROR

    def test_other_errors_log_warning(self, monkeypatch, caplog):
        record = {}
        stub = _stub_client_class(record, post_error=httpx.ConnectError("sem rede"))
        monkeypatch.setattr(httpx, "Client", stub)
        with caplog.at_level(logging.DEBUG, logger="quimera.api.turnstile"):
            assert verify("token-ok", "segredo") is False
        assert caplog.records[-1].levelno == logging.WARNING
