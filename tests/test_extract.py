"""Testes do extrator: prompt por policy e contrato da resposta do LLM."""

from __future__ import annotations

import json

import pytest

from quimera.extract import (
    ExtractionError,
    build_prompt,
    extract_filters,
    parse_extraction_response,
)
from quimera.filters import LeadFilters
from quimera.policy import PRIVATE, PUBLIC

from fakes import FakeGenaiClient


class TestBuildPrompt:
    def test_prompt_states_never_write_sql(self):
        prompt = build_prompt("clínicas em SP", PUBLIC)
        assert "Nunca escreva SQL" in prompt

    def test_public_prompt_refuses_personal_data(self):
        prompt = build_prompt("qualquer pedido", PUBLIC)
        assert "refused=true" in prompt
        assert "dado pessoal" in prompt

    def test_private_prompt_allows_mei_and_asks_for_no_cpf(self):
        prompt = build_prompt("qualquer pedido", PRIVATE)
        assert "include_mei" in prompt
        assert "CPF" in prompt
        assert "refused=true" not in prompt

    def test_prompt_carries_request(self):
        assert "clínicas odontológicas em Santo André" in build_prompt(
            "clínicas odontológicas em Santo André", PUBLIC
        )

    def test_prompt_forbids_invented_codes(self):
        prompt = build_prompt("pedido", PUBLIC)
        assert "Não invente códigos CNAE" in prompt
        assert "Não invente códigos IBGE" in prompt

    def test_prompt_never_refuses_vague_requests(self):
        """Regressão de ext_032/ext_033: o modelo recusava pedidos vagos
        ('empresas boas em SP', 'me passa umas empresas aí'). Recusa é
        exclusivamente para dado pessoal; pedidos vagos são aceitos,
        extraindo apenas os filtros mapeáveis."""
        for policy in (PUBLIC, PRIVATE):
            prompt = build_prompt("empresas boas em SP", policy)
            assert "Não recuse pedidos vagos" in prompt
            assert "Recusa é exclusivamente para dado pessoal" in prompt


class TestParseExtractionResponse:
    def test_accepts_dict(self):
        result = parse_extraction_response({"refused": False, "filters": {}})
        assert result.filters == LeadFilters()

    def test_accepts_json_string(self):
        payload = json.dumps(
            {"refused": False, "filters": {"ufs": ["SP"], "limit": 10}},
            ensure_ascii=False,
        )
        result = parse_extraction_response(payload)
        assert result.filters.ufs == ["SP"]

    def test_accepts_sdk_response_with_text(self):
        class Response:
            text = '{"refused": false, "filters": {}}'

        assert parse_extraction_response(Response()).filters == LeadFilters()

    def test_accepts_sdk_response_with_parsed(self):
        class Response:
            parsed = {"refused": False, "filters": LeadFilters()}

        result = parse_extraction_response(Response())
        assert result.filters == LeadFilters()

    def test_malformed_json_raises_extraction_error(self):
        with pytest.raises(ExtractionError, match="não é JSON válido"):
            parse_extraction_response('{"refused": false, "filters":')

    def test_out_of_contract_payload_raises_extraction_error(self):
        with pytest.raises(ExtractionError, match="fora do contrato"):
            parse_extraction_response({"refused": False, "sql": "SELECT 1"})


class TestExtractFilters:
    def test_happy_path_with_fake_client(self):
        payload = (
            '{"refused": false, "filters": {"ufs": ["SP"], "cnae_query": "clínicas"}}'
        )
        client = FakeGenaiClient(payload)
        result = extract_filters(
            "clínicas em SP", PUBLIC, model="m-teste", client=client
        )
        assert result.filters.ufs == ["SP"]

        call = client.calls[0]
        assert call["model"] == "m-teste"
        assert call["config"]["temperature"] == 0
        assert call["config"]["response_mime_type"] == "application/json"
        assert call["config"]["response_schema"] is not None
        assert "clínicas em SP" in call["contents"]

    def test_env_model_used_when_not_provided(self, monkeypatch):
        monkeypatch.setenv("EXTRACT_MODEL", "gemini-teste")
        client = FakeGenaiClient('{"refused": false, "filters": {}}')
        extract_filters("pedido", PUBLIC, client=client)
        assert client.calls[0]["model"] == "gemini-teste"
