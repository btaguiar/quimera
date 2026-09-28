"""Testes do score explicável contra ICP configurável."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from quimera.score import ICPConfig, age_fraction, capital_fraction, score_lead


def _icp() -> ICPConfig:
    return ICPConfig()


def _lead(**overrides):
    lead = {
        "porte": "demais",
        "idade_anos": 12,
        "capital_social": 10_000_000.0,
        "n_estabelecimentos": 1,
    }
    lead.update(overrides)
    return lead


class TestScoreLead:
    def test_full_icp_match_scores_100(self):
        score, motivos = score_lead(_lead(), _icp())
        assert score == 100.0
        assert len(motivos) == 3

    def test_porte_out_of_target_partial_points(self):
        score, motivos = score_lead(_lead(porte="pequena"), _icp())
        assert score == 40.0 * 0.4 + 30.0 + 30.0
        assert any("fora do alvo" in m for m in motivos)

    def test_age_below_target_no_age_points(self):
        score, motivos = score_lead(
            _lead(
                idade_anos=None,
                data_inicio_atividade=(date.today() - timedelta(days=90)).isoformat(),
            ),
            _icp(),
        )
        assert score == 40.0 + 30.0
        assert any("abaixo do mínimo do ICP" in m for m in motivos)

    def test_capital_below_target_no_capital_points(self):
        score, motivos = score_lead(_lead(capital_social=1_000.0), _icp())
        assert score == 40.0 + 30.0
        assert any("abaixo do mínimo do ICP (R$ 50.000)" in m for m in motivos)

    def test_mei_reduces_score(self):
        score, motivos = score_lead(_lead(opcao_mei="S"), _icp())
        assert score == 50.0
        assert any("MEI" in m for m in motivos)

    def test_mei_flag_variants(self):
        assert score_lead(_lead(is_mei=True), _icp())[0] == 50.0
        assert score_lead(_lead(opcao_mei="N"), _icp())[0] == 100.0

    def test_capital_as_string_is_coerced(self):
        score, _ = score_lead(_lead(capital_social="10000000"), _icp())
        assert score == 100.0

    def test_date_in_compact_format_is_parsed(self):
        twelve_years_ago = date.today() - timedelta(days=365 * 12 + 10)
        score, _ = score_lead(
            _lead(
                idade_anos=None,
                data_inicio_atividade=twelve_years_ago.strftime("%Y%m%d"),
            ),
            _icp(),
        )
        assert score == 100.0

    def test_age_field_takes_precedence(self):
        score, _ = score_lead(
            _lead(idade_anos=10, data_inicio_atividade="2025-01-01"), _icp()
        )
        assert score == 100.0

    def test_empty_lead_scores_zero_with_reason(self):
        score, motivos = score_lead({}, _icp())
        assert score == 0.0
        assert motivos == ["sem sinais do ICP identificados nos dados disponíveis"]

    def test_score_never_exceeds_100(self):
        icp = ICPConfig(w_porte=60.0, w_age=60.0, w_capital=60.0)
        score, _ = score_lead(_lead(), icp)
        assert score == 100.0

    def test_zero_capital_is_not_informed(self):
        # 17,5 M empresas têm capital 0: é ausência de dado, não capital baixo.
        score, motivos = score_lead(_lead(capital_social=0.0), _icp())
        assert score == 40.0 + 30.0
        assert "capital social não informado no cadastro" in motivos
        assert not any("abaixo do mínimo" in m for m in motivos)

    def test_sentinel_capital_is_not_informed(self):
        score, motivos = score_lead(_lead(capital_social=999_999_999_999.0), _icp())
        assert score == 40.0 + 30.0
        assert "capital social não informado no cadastro" in motivos

    def test_age_counts_complete_years(self):
        # Mesma regra do filtro SQL: 2 anos completos só no aniversário.
        from quimera.score import _age_years

        today = date(2026, 9, 26)
        lead = {"data_inicio_atividade": "2024-09-27"}
        assert _age_years(lead, today) == 1
        lead = {"data_inicio_atividade": "2024-09-26"}
        assert _age_years(lead, today) == 2


class TestFaixaAlvo:
    """Idade e capital pontuam em faixa; capital acima do teto perde nota."""

    def test_age_ramps_from_half_at_minimum_to_full(self):
        icp = _icp()
        assert age_fraction(1, icp) == 0.0
        assert age_fraction(2, icp) == 0.5
        assert age_fraction(6, icp) == 0.75
        assert age_fraction(10, icp) == 1.0
        assert age_fraction(40, icp) == 1.0

    def test_capital_ramps_on_log_scale_up_to_the_cap(self):
        icp = _icp()
        assert capital_fraction(49_999.0, icp) == 0.0
        assert capital_fraction(50_000.0, icp) == 0.5
        assert capital_fraction(10_000_000.0, icp) == 1.0
        meio = math.sqrt(50_000.0 * 10_000_000.0)  # meio da faixa em escala log
        assert capital_fraction(meio, icp) == pytest.approx(0.75)

    def test_capital_decays_above_cap_until_zero(self):
        icp = _icp()
        assert capital_fraction(100_000_000.0, icp) == pytest.approx(0.5)
        assert capital_fraction(1_000_000_000.0, icp) == 0.0
        assert capital_fraction(50_000_000_000.0, icp) == 0.0

    def test_giant_ranks_below_established_clinic(self):
        # Caso real do aceite (Santo André): a operadora de R$ 207 mi empatava
        # em 100 com as clínicas e ficava em 1º pelo desempate de capital.
        operadora, motivos = score_lead(
            {"porte": "demais", "idade_anos": 4, "capital_social": 207_369_723.0},
            _icp(),
        )
        clinica, _ = score_lead(
            {"porte": "demais", "idade_anos": 31, "capital_social": 420_000.0},
            _icp(),
        )
        assert clinica > operadora
        assert any("acima do teto do ICP (R$ 10.000.000)" in m for m in motivos)

    def test_scores_distinguish_companies_that_used_to_tie(self):
        leads = [
            {"porte": "demais", "idade_anos": a, "capital_social": c}
            for a, c in [
                (2, 850_000.0),
                (2, 500_000.0),
                (31, 420_000.0),
                (5, 150_000.0),
            ]
        ]
        scores = [score_lead(lead, _icp())[0] for lead in leads]
        assert len(set(scores)) == len(scores)

    def test_capital_reason_names_the_band_in_reais(self):
        _, motivos = score_lead(_lead(capital_social=850_000.0), _icp())
        assert (
            "capital social de R$ 850.000 na faixa do ICP (R$ 50.000 a R$ 10.000.000)"
            in motivos
        )

    def test_age_reasons(self):
        _, motivos = score_lead(_lead(idade_anos=4), _icp())
        assert "ativa há 4 anos, na faixa do ICP (nota plena a partir de 10)" in motivos
        _, motivos = score_lead(_lead(idade_anos=12), _icp())
        assert "ativa há 12 anos, maturidade plena para o ICP" in motivos

    def test_cap_at_or_below_minimum_gives_full_points_in_band(self):
        icp = ICPConfig(target_min_capital=50_000.0, target_max_capital=50_000.0)
        assert icp.capital_log_span == 0.0
        assert capital_fraction(50_000.0, icp) == 1.0

    def test_invalid_decay_is_rejected(self):
        with pytest.raises(ValueError):
            ICPConfig(capital_decay_decades=0)


class TestScoreSinaisCadastro:
    def test_default_icp_ignores_new_signals_in_score(self):
        base, _ = score_lead(_lead(), _icp())
        with_signals, motivos = score_lead(
            _lead(n_estabelecimentos=12, dominio_proprio=True), _icp()
        )
        assert with_signals == base
        assert "rede com 12 estabelecimentos ativos" in motivos
        assert "e-mail em domínio próprio" in motivos

    def test_weighted_rede_and_dominio(self):
        icp = ICPConfig(w_porte=40, w_age=20, w_capital=20, w_rede=10, w_dominio=10)
        score, _ = score_lead(_lead(n_estabelecimentos=3, dominio_proprio=True), icp)
        assert score == 100.0

    def test_single_establishment_has_no_rede_reason(self):
        _, motivos = score_lead(_lead(n_estabelecimentos=1), _icp())
        assert not any("rede" in m for m in motivos)

    def test_regime_reason(self):
        _, motivos = score_lead(_lead(regime_tributario="fora_simples"), _icp())
        assert "fora do Simples Nacional" in motivos

    def test_regime_simples_reason(self):
        _, motivos = score_lead(_lead(regime_tributario="simples"), _icp())
        assert "optante do Simples Nacional" in motivos

    def test_rede_below_target_scores_no_points_but_informs(self):
        icp = ICPConfig(
            w_porte=40,
            w_age=20,
            w_capital=20,
            w_rede=10,
            target_min_estabelecimentos=5,
        )
        score, motivos = score_lead(_lead(n_estabelecimentos=3), icp)
        assert score == 80.0
        assert "rede com 3 estabelecimentos ativos" in motivos


class TestICPConfigSinais:
    def test_sinais_pesam_zero_por_padrao(self):
        # Defaults não mudam o score: os motivos/score dos sinais vêm na Onda 1.
        icp = ICPConfig()
        assert icp.w_rede == 0.0
        assert icp.w_dominio == 0.0
        assert icp.target_min_estabelecimentos == 2
