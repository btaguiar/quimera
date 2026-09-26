"""Testes dos validadores de LeadFilters e do contrato ExtractionResult."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from quimera.filters import ExtractionResult, LeadFilters


class TestLeadFilters:
    def test_valid_full_filters(self):
        filters = LeadFilters(
            cnae_query="clínicas odontológicas",
            cnae_codes=["8630-5/01"],
            ufs=["SP"],
            municipio_ids=["3547807"],
            min_age_years=2,
            max_age_years=10,
            min_capital=50000.0,
            portes=["media"],
            limit=25,
        )
        assert filters.ufs == ["SP"]
        assert filters.limit == 25

    def test_defaults(self):
        filters = LeadFilters()
        assert filters.cnae_query is None
        assert filters.cnae_codes == []
        assert filters.include_mei is False
        assert filters.limit == 50

    def test_ufs_normalized_to_uppercase(self):
        assert LeadFilters(ufs=["sp", "Rj"]).ufs == ["SP", "RJ"]

    def test_invalid_uf_rejected(self):
        with pytest.raises(ValidationError, match="UF inválida"):
            LeadFilters(ufs=["XX"])

    def test_portes_normalized_to_lowercase(self):
        assert LeadFilters(portes=["Micro", "MEDIA"]).portes == ["micro", "media"]

    def test_porte_with_accent_normalized(self):
        assert LeadFilters(portes=["Média", "Pequena"]).portes == ["media", "pequena"]

    def test_invalid_porte_rejected(self):
        with pytest.raises(ValidationError, match="Porte inválido"):
            LeadFilters(portes=["enorme"])

    def test_inverted_age_range_rejected(self):
        with pytest.raises(ValidationError, match="invertida"):
            LeadFilters(min_age_years=10, max_age_years=2)

    def test_negative_capital_rejected(self):
        with pytest.raises(ValidationError):
            LeadFilters(min_capital=-1)

    def test_zero_limit_rejected(self):
        with pytest.raises(ValidationError):
            LeadFilters(limit=0)

    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            LeadFilters(sql="SELECT 1")


class TestExtractionResult:
    def test_refused_with_reason(self):
        result = ExtractionResult(refused=True, refusal_reason="pedido de dado pessoal")
        assert result.filters is None

    def test_refused_without_reason_rejected(self):
        with pytest.raises(ValidationError, match="refusal_reason"):
            ExtractionResult(refused=True)

    def test_refused_with_filters_rejected(self):
        with pytest.raises(ValidationError, match="não pode carregar filtros"):
            ExtractionResult(
                refused=True, refusal_reason="motivo", filters=LeadFilters()
            )

    def test_not_refused_requires_filters(self):
        with pytest.raises(ValidationError, match="exige filters"):
            ExtractionResult(refused=False)

    def test_not_refused_with_filters(self):
        result = ExtractionResult(refused=False, filters=LeadFilters())
        assert result.filters is not None
