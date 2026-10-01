"""Idade e capital lidos do texto: só com qualificador claro, nunca inventa."""

from __future__ import annotations

import pytest

from quimera.filtros_texto import filtros_no_texto


@pytest.mark.parametrize(
    "pedido, esperado",
    [
        ("padarias em Recife há mais de 5 anos", {"min_age_years": 5}),
        ("padarias com pelo menos 10 anos de mercado", {"min_age_years": 10}),
        ("padarias com 3 anos ou mais", {"min_age_years": 3}),
        ("dentistas com 10+ anos de mercado", {"min_age_years": 10}),
        ("padarias com até 2 anos de atividade", {"max_age_years": 2}),
        ("padarias com menos de 3 anos", {"max_age_years": 3}),
        ("padarias com capital social acima de R$ 500 mil", {"min_capital": 500_000}),
        ("padarias com capital de pelo menos 1 milhão de reais", {"min_capital": 1_000_000}),
        ("padarias capital social > R$ 100 MIL", {"min_capital": 100_000}),
        ("padarias com capital de R$ 100 mil ou mais", {"min_capital": 100_000}),
        ("padarias com capital acima de 1,5 milhão", {"min_capital": 1_500_000}),
        ("padarias com capital acima de 500.000", {"min_capital": 500_000}),
        ("padarias com capital acima de 200k", {"min_capital": 200_000}),
        (
            "padarias fora do Simples e com capital acima de R$ 500 mil e há mais de 8 anos",
            {"min_capital": 500_000, "min_age_years": 8},
        ),
    ],
)
def test_le_o_que_esta_escrito(pedido, esperado):
    assert filtros_no_texto(pedido) == esperado


@pytest.mark.parametrize(
    "pedido",
    [
        "padarias em Campinas",
        "padarias com 5 anos",  # sem qualificador: não dá para saber se é mínimo
        "padarias com capital abaixo de 100 mil",  # não há filtro de teto
        "padarias com capital de 100 mil",  # exato não é mínimo
        "padarias com pelo menos 5 unidades",  # rede, não idade
        "redes com mais de 10 lojas em SP",
    ],
)
def test_nao_inventa(pedido):
    assert filtros_no_texto(pedido) == {}
