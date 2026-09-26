"""Contrato dos golden sets: schema, unicidade e rótulos válidos.

Estes testes protegem os arquivos JSONL de regressões involuntárias
(caso malformado, id duplicado, filtro que o schema recusa).
"""

from __future__ import annotations

import re

import pytest

from eval.run_eval import GOLDEN_CNAE, GOLDEN_EXTRACTION, load_cases
from quimera.filters import LeadFilters

CNAE_CODE_PATTERN = re.compile(r"^\d{4}-\d{1}/\d{2}$")


@pytest.fixture(scope="module")
def extraction_cases():
    return load_cases(GOLDEN_EXTRACTION)


@pytest.fixture(scope="module")
def cnae_cases():
    return load_cases(GOLDEN_CNAE)


class TestGoldenExtraction:
    def test_has_at_least_50_cases(self, extraction_cases):
        assert len(extraction_cases) >= 50

    def test_unique_ids(self, extraction_cases):
        ids = [c["id"] for c in extraction_cases]
        assert len(ids) == len(set(ids))

    def test_schema_of_every_case(self, extraction_cases):
        for case in extraction_cases:
            assert case["policy"] in {"public", "private"}
            assert isinstance(case["request"], str) and case["request"].strip()
            expect = case["expect"]
            has_refused = "refused" in expect
            has_filters = "filters" in expect
            assert has_refused != has_filters, case["id"]
            if has_filters:
                LeadFilters.model_validate(expect["filters"])
            else:
                assert expect["refused"] is True

    def test_refusal_expect_never_carries_filters(self, extraction_cases):
        for case in extraction_cases:
            if case["expect"].get("refused"):
                assert "filters" not in case["expect"]

    def test_public_has_at_least_10_refusal_cases(self, extraction_cases):
        refusals = [
            c
            for c in extraction_cases
            if c["policy"] == "public" and c["expect"].get("refused")
        ]
        assert len(refusals) >= 10

    def test_has_difficult_cases(self, extraction_cases):
        """Spec: ambiguidade, pedido misto, sinônimos, erros de digitação."""
        requests = " ".join(c["request"] for c in extraction_cases).lower()
        assert "odontologicas" in requests  # typo/sem acento
        assert "dentistas" in requests  # sinônimo
        assert "boas em sp" in requests  # ambiguidade

    def test_no_pending_review_flags(self, extraction_cases):
        """Os 5 rótulos draft foram revisados com o Bruno em 2026-09-26.
        Decisões: pedidos vagos com qualificadores não-mapeáveis ("boas",
        "conhecidas", "maiores") extraem o que for mapeável — recusa é só
        para dado pessoal; "dados bancários das empresas" permanece recusado
        (sensível, fora do schema público). Novos casos draft devem ser
        revisados antes de virar baseline."""
        flagged = [c["id"] for c in extraction_cases if c.get("flag") == "review"]
        assert flagged == []


class TestGoldenCnae:
    def test_has_at_least_50_cases(self, cnae_cases):
        assert len(cnae_cases) >= 50

    def test_unique_ids(self, cnae_cases):
        ids = [c["id"] for c in cnae_cases]
        assert len(ids) == len(set(ids))

    def test_schema_of_every_case(self, cnae_cases):
        for case in cnae_cases:
            assert isinstance(case["query"], str) and case["query"].strip()
            assert case["acceptable"], case["id"]
            for code in case["acceptable"]:
                assert CNAE_CODE_PATTERN.match(code), (case["id"], code)

    def test_every_acceptable_code_exists_in_cnae_2_3(self, cnae_cases):
        # O golden já apontou para códigos inexistentes (5510-8/00, 4771-7/00)
        # e obsoletos (4721-1/01, 0 empresas ativas) — medido em 2026-09-26.
        from quimera.cnae import load_subclasses

        valid = {s["codigo"] for s in load_subclasses()}
        invalid = [
            (c["id"], code)
            for c in cnae_cases
            for code in c["acceptable"]
            if code not in valid
        ]
        assert invalid == []

    def test_no_pending_review_flags(self, cnae_cases):
        """Os 23 rótulos draft foram revisados contra a CNAE 2.3 em 2026-09-26
        (fonte: diretório br_bd_diretorios_brasil.cnae_2). Novos casos draft
        devem ser revisados antes de virar baseline."""
        flagged = [c["id"] for c in cnae_cases if c.get("flag") == "review"]
        assert flagged == []
