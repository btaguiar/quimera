"""Testes da verificação do Turnstile com MockTransport (sem rede)."""

from __future__ import annotations

import httpx

from quimera.api.turnstile import verify


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


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
