"""Testes das métricas ponta a ponta (puras, sem GCP) e da suíte e2e."""

from __future__ import annotations

from datetime import date

import pytest

from eval.metrics import (
    e2e_case_outcome,
    e2e_invariant_violations,
    e2e_metrics,
    e2e_row_checks,
)
from eval.run_eval import GOLDEN_E2E, check_thresholds, load_cases, run_e2e_suite

TODAY = date(2026, 9, 26)


def _row(**overrides):
    row = {
        "cnpj": "11111111000101",
        "cnpj_basico": "11111111",
        "sigla_uf": "SP",
        "municipio": "Santo André",
        "cnae_fiscal_principal": "8630504",
        "data_inicio_atividade": date(2020, 1, 1),
        "capital_social": 50_000.0,
        "porte": "micro",
        "natureza_juridica": "2062",
        "score": 70.0,
        # Sinais do próprio cadastro (Onda 1): sempre no SELECT da query.
        "n_estabelecimentos": 1,
        "regime_tributario": "simples",
        "bairro": "Centro",
        "dominio_proprio": False,
    }
    row.update(overrides)
    return row


def _result(rows, **overrides):
    result = {"refused": False, "rows": rows, "warnings": [], "policy": "public"}
    result.update(overrides)
    return result


class TestRowChecks:
    def test_all_criteria_pass(self):
        expect = {
            "uf": ["SP"],
            "municipio": ["santo andre"],  # sem acento/caixa
            "cnae": ["8630-5/04"],  # golden mascarado, base sem máscara
            "min_age_years": 6,
            "max_age_years": 6,
            "min_capital": 50_000,
            "portes": ["micro"],
        }
        checks = e2e_row_checks(_row(), expect, TODAY)
        assert checks == {k: True for k in expect}

    def test_age_is_complete_years(self):
        # 2024-09-27 -> 2026-09-26 = 1 ano completo (DATE_DIFF daria 2).
        row = _row(data_inicio_atividade="2024-09-27")
        assert e2e_row_checks(row, {"min_age_years": 2}, TODAY) == {
            "min_age_years": False
        }

    @pytest.mark.parametrize(
        ("field", "value", "expect"),
        [
            ("sigla_uf", "PB", {"uf": ["SP"]}),
            ("cnae_fiscal_principal", "4721102", {"cnae": ["8630-5/04"]}),
            ("capital_social", None, {"min_capital": 1}),
            ("porte", "demais", {"portes": ["micro"]}),
            ("data_inicio_atividade", None, {"max_age_years": 3}),
            ("n_estabelecimentos", 2, {"min_estabelecimentos": 5}),
            ("regime_tributario", "mei", {"regimes": ["simples"]}),
            ("bairro", "Jardim América", {"bairros": ["Pinheiros"]}),
            ("dominio_proprio", False, {"com_dominio_proprio": True}),
        ],
    )
    def test_each_criterion_fails(self, field, value, expect):
        checks = e2e_row_checks(_row(**{field: value}), expect, TODAY)
        assert list(checks.values()) == [False]

    def test_onda1_criteria_pass(self):
        expect = {
            "min_estabelecimentos": 1,
            "regimes": ["simples"],
            "bairros": ["centro"],  # sem acento/caixa, como municipio
            "com_dominio_proprio": True,
        }
        checks = e2e_row_checks(_row(dominio_proprio=True), expect, TODAY)
        assert checks == {k: True for k in expect}

    def test_raio_km_checked_only_with_distancia(self):
        near = e2e_row_checks(_row(distancia_km=2.9), {"raio_km": 3}, TODAY)
        assert near == {"raio_km": True}
        far = e2e_row_checks(_row(distancia_km=3.1), {"raio_km": 3}, TODAY)
        assert far == {"raio_km": False}
        # Sem distancia_km o raio não foi aplicado: a checagem de linha
        # não opina (a falha do caso é detectada em e2e_case_outcome).
        assert e2e_row_checks(_row(), {"raio_km": 3}, TODAY) == {}


class TestInvariants:
    def test_clean_result(self):
        assert e2e_invariant_violations(_result([_row()])) == []

    def test_repeated_company(self):
        rows = [_row(), _row(cnpj="11111111000282")]
        assert any("repetida" in v for v in e2e_invariant_violations(_result(rows)))

    @pytest.mark.parametrize("natureza", ["4120", "2135"])
    def test_public_forbids_pessoa_fisica_and_empresario_individual(self, natureza):
        result = _result([_row(natureza_juridica=natureza)])
        assert any(natureza in v for v in e2e_invariant_violations(result))

    def test_private_allows_them(self):
        result = _result([_row(natureza_juridica="4120")], policy="private")
        assert e2e_invariant_violations(result) == []

    def test_contact_in_public(self):
        result = _result([_row(telefone="1199999999")])
        assert any("contato" in v for v in e2e_invariant_violations(result))

    @pytest.mark.parametrize("campo", ["latitude", "longitude", "cep", "dominio"])
    def test_public_forbids_geo_cep_and_dominio(self, campo):
        result = _result([_row(**{campo: "qualquer"})])
        assert any(campo in v for v in e2e_invariant_violations(result))

    def test_dominio_proprio_flag_is_allowed(self):
        # O booleano dominio_proprio é um sinal do cadastro, não o domínio em si.
        assert e2e_invariant_violations(_result([_row(dominio_proprio=True)])) == []

    def test_public_forbids_mei(self):
        result = _result([_row(regime_tributario="mei")])
        assert any("mei" in v for v in e2e_invariant_violations(result))

    def test_private_allows_mei(self):
        result = _result([_row(regime_tributario="mei")], policy="private")
        assert e2e_invariant_violations(result) == []

    def test_score_out_of_order(self):
        rows = [_row(score=50.0), _row(cnpj_basico="2", score=90.0)]
        assert any("ordem" in v for v in e2e_invariant_violations(_result(rows)))


class TestCaseOutcome:
    def test_expected_refusal(self):
        case = {"id": "x", "expect": {"refused": True}}
        assert e2e_case_outcome(case, _result([], refused=True), TODAY)["passed"]
        outcome = e2e_case_outcome(case, _result([_row()]), TODAY)
        assert "deveria recusar" in outcome["problems"]

    def test_false_refusal(self):
        case = {"id": "x", "expect": {"empty": True}}
        outcome = e2e_case_outcome(case, _result([], refused=True), TODAY)
        assert "recusou" in outcome["problems"]

    def test_empty_and_warning(self):
        case = {"id": "x", "expect": {"empty": True, "warning": "não encontrado"}}
        ok = _result([], warnings=["Município não encontrado no diretório: Narnia."])
        assert e2e_case_outcome(case, ok, TODAY)["passed"]
        outcome = e2e_case_outcome(case, _result([]), TODAY)
        assert "sem aviso 'não encontrado'" in outcome["problems"]

    def test_unexpected_empty(self):
        case = {"id": "x", "expect": {"uf": ["SP"]}}
        assert "veio vazio" in e2e_case_outcome(case, _result([]), TODAY)["problems"]

    def test_raio_expected_but_not_applied(self):
        # expect raio_km com linhas sem distancia_km = raio ignorado na query;
        # sem isto o caso passaria como se a proximidade tivesse sido aplicada.
        case = {"id": "x", "expect": {"raio_km": 3}}
        outcome = e2e_case_outcome(case, _result([_row()]), TODAY)
        assert any("raio" in p for p in outcome["problems"])

    def test_failing_rows_are_counted(self):
        case = {"id": "x", "expect": {"uf": ["SP"]}}
        rows = [_row(), _row(cnpj_basico="2", sigla_uf="RJ")]
        outcome = e2e_case_outcome(case, _result(rows), TODAY)
        assert outcome["rows_ok"] == 1
        assert outcome["problems"] == ["1/2 linhas falham ['uf']"]


class TestMetrics:
    def test_aggregates_cases_rows_and_refusals(self):
        cases = [
            {"id": "a", "expect": {"uf": ["SP"]}},
            {"id": "b", "expect": {"uf": ["SP"]}},
            {"id": "c", "expect": {"refused": True}},
        ]
        results = [
            _result([_row(), _row(cnpj_basico="2")]),
            _result([_row(sigla_uf="RJ")]),
            _result([], refused=True),
        ]
        m = e2e_metrics(cases, results, TODAY)
        assert m["case_pass_rate"] == pytest.approx(2 / 3)
        assert m["row_precision"] == pytest.approx(2 / 3)
        assert m["row_precision_by_check"]["uf"] == pytest.approx(2 / 3)
        assert m["row_precision_by_check"]["cnae"] is None
        assert m["e2e_correct_refusal_rate"] == 1.0
        assert m["n_rows"] == 3

    def test_length_mismatch(self):
        with pytest.raises(ValueError):
            e2e_metrics([{"id": "a", "expect": {}}], [], TODAY)


class TestSuite:
    def test_run_e2e_suite_records_latency_and_bytes(self):
        cases = [{"id": "a", "request": "dentistas em SP", "expect": {"uf": ["SP"]}}]
        result = _result(
            [_row()],
            timings_ms={"extract": 10.0, "query": 20.0},
            bytes_billed=1000,
            estimated_cost_usd=0.001,
            cnae_matches=[["8630-5/04", "Odonto", 0.9]],
        )
        payload = run_e2e_suite(cases, lambda request: result)
        assert payload["suite"] == "e2e"
        assert payload["metrics"]["case_pass_rate"] == 1.0
        assert payload["metrics"]["bytes_billed_p50"] == 1000
        assert payload["stage_latency_ms"]["query"]["p50"] == 20.0
        assert payload["detail"][0]["cnae_codes"] == ["8630-5/04"]

    def test_thresholds_cover_e2e(self):
        failures = check_thresholds(
            {
                "case_pass_rate": 0.5,
                "row_precision": 0.99,
                "e2e_correct_refusal_rate": 0.5,
            },
            {
                "e2e_case_pass_rate": 0.9,
                "e2e_row_precision": 0.98,
                "e2e_correct_refusal_rate": 1.0,
            },
        )
        assert len(failures) == 2


class TestGoldenE2e:
    def test_golden_is_well_formed(self):
        from quimera.cnae import load_subclasses

        valid = {s["codigo"] for s in load_subclasses()}
        cases = load_cases(GOLDEN_E2E)
        assert len(cases) >= 20
        assert len({c["id"] for c in cases}) == len(cases)
        assert sum(bool(c["expect"].get("refused")) for c in cases) >= 2
        for case in cases:
            for code in case["expect"].get("cnae", []):
                assert code in valid, (case["id"], code)
