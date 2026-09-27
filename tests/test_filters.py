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


class TestSinaisOnda1:
    def test_defaults_keep_current_behavior(self):
        f = LeadFilters()
        assert f.min_estabelecimentos is None
        assert f.regimes == []
        assert f.bairros == []
        assert f.cep_centro is None and f.raio_km is None
        assert f.com_dominio_proprio is False

    def test_regimes_normalized_and_validated(self):
        assert LeadFilters(regimes=["Simples", " fora_simples "]).regimes == [
            "simples",
            "fora_simples",
        ]
        with pytest.raises(ValidationError, match="Regime inválido"):
            LeadFilters(regimes=["lucro_real"])

    def test_cep_keeps_only_digits(self):
        assert LeadFilters(cep_centro="01310-100").cep_centro == "01310100"

    def test_cep_fullwidth_digits_rejected(self):
        # Dígitos Unicode fullwidth não são ASCII: não podem virar CEP armazenado.
        with pytest.raises(ValidationError, match="CEP inválido"):
            LeadFilters(cep_centro="０１３１０１００")

    def test_invalid_cep_rejected(self):
        with pytest.raises(ValidationError, match="CEP inválido"):
            LeadFilters(cep_centro="1234")

    def test_raio_bounds(self):
        with pytest.raises(ValidationError, match="fora dos limites"):
            LeadFilters(raio_km=0)
        with pytest.raises(ValidationError, match="fora dos limites"):
            LeadFilters(raio_km=500)

    def test_raio_boundaries_accepted(self):
        assert LeadFilters(raio_km=0.1).raio_km == 0.1
        assert LeadFilters(raio_km=100.0).raio_km == 100.0

    def test_raio_happy_path(self):
        assert LeadFilters(raio_km=3).raio_km == 3

    def test_min_estabelecimentos_positive(self):
        with pytest.raises(ValidationError):
            LeadFilters(min_estabelecimentos=0)


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
