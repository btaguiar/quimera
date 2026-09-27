"""Contrato dos golden sets: schema, unicidade e rótulos válidos.

Estes testes protegem os arquivos JSONL de regressões involuntárias
(caso malformado, id duplicado, filtro que o schema recusa).
"""

from __future__ import annotations

import re

import pytest

from eval.run_eval import GOLDEN_CNAE, GOLDEN_EXTRACTION, GOLDEN_E2E, load_cases
from quimera.filters import VALID_REGIMES, VALID_UFS, LeadFilters
from quimera.query import PORTE_CODES_TO_LABELS

CNAE_CODE_PATTERN = re.compile(r"^\d{4}-\d{1}/\d{2}$")

E2E_GOLDENS = [GOLDEN_E2E, GOLDEN_E2E.parent / "golden_e2e_holdout.jsonl"]

# Chaves que o expect de um caso e2e aceita: critérios por linha de
# metrics.e2e_row_checks + bandeiras do caso em metrics.e2e_case_outcome.
E2E_EXPECT_KEYS = frozenset(
    {
        "uf",
        "municipio",
        "cnae",
        "min_age_years",
        "max_age_years",
        "min_capital",
        "portes",
        "min_estabelecimentos",
        "regimes",
        "bairros",
        "raio_km",
        "com_dominio_proprio",
        "refused",
        "empty",
        "warning",
    }
)
# A suíte e2e roda só no público, onde MEI não existe: esperá-lo seria erro.
VALID_E2E_REGIMES = VALID_REGIMES - {"mei"}
# A linha devolvida traz o rótulo traduzido do porte: media/grande são
# indistinguíveis no cadastro e chegam como "demais" (ver query.py).
VALID_E2E_PORTES = frozenset(PORTE_CODES_TO_LABELS.values())


@pytest.fixture(scope="module")
def extraction_cases():
    return load_cases(GOLDEN_EXTRACTION)


@pytest.fixture(scope="module")
def cnae_cases():
    return load_cases(GOLDEN_CNAE)


@pytest.fixture(scope="module", params=E2E_GOLDENS, ids=lambda p: p.name)
def e2e_cases(request):
    return load_cases(request.param)


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


class TestGoldenE2e:
    def test_unique_ids(self, e2e_cases):
        ids = [c["id"] for c in e2e_cases]
        assert len(ids) == len(set(ids))

    def test_schema_of_every_case(self, e2e_cases):
        from quimera.cnae import load_subclasses

        valid_cnae = {s["codigo"] for s in load_subclasses()}
        for case in e2e_cases:
            assert isinstance(case["request"], str) and case["request"].strip()
            expect = case["expect"]
            unknown = set(expect) - E2E_EXPECT_KEYS
            assert not unknown, (case["id"], unknown)
            if not expect.get("refused") and not expect.get("empty"):
                assert expect.get("cnae"), case["id"]
            for code in expect.get("cnae", []):
                assert CNAE_CODE_PATTERN.match(code), (case["id"], code)
                assert code in valid_cnae, (case["id"], code)
            assert all(uf in VALID_UFS for uf in expect.get("uf", [])), case["id"]
            assert all(p in VALID_E2E_PORTES for p in expect.get("portes", [])), case[
                "id"
            ]
            regimes = expect.get("regimes", [])
            assert all(r in VALID_E2E_REGIMES for r in regimes), case["id"]
            n = expect.get("min_estabelecimentos")
            assert n is None or (isinstance(n, int) and n >= 1), case["id"]
            raio = expect.get("raio_km")
            assert raio is None or (isinstance(raio, (int, float)) and raio > 0), case[
                "id"
            ]
            flag = expect.get("com_dominio_proprio")
            assert flag is None or isinstance(flag, bool), case["id"]
            for bairro in expect.get("bairros", []):
                assert isinstance(bairro, str) and bairro.strip(), (case["id"], bairro)
