"""Testes das métricas puras do eval (acerto por campo, recusas, recall@k, MRR)."""

from __future__ import annotations

import pytest

from eval.metrics import (
    cnae_metrics,
    compare_extraction,
    extraction_metrics,
    percentile,
    recall_at_k,
    reciprocal_rank,
)
from quimera.filters import ExtractionResult, LeadFilters


def _result(filters: LeadFilters | None = None, refused=False, reason=None):
    return ExtractionResult(refused=refused, refusal_reason=reason, filters=filters)


class TestCompareExtraction:
    def test_matching_filters_exact(self):
        case = {"id": "1", "expect": {"filters": {"ufs": ["SP"], "min_age_years": 2}}}
        outcome = compare_extraction(
            case, _result(LeadFilters(ufs=["SP"], min_age_years=2))
        )
        assert outcome["exact_match"] is True
        assert outcome["extra_fields"] == []
        assert all(outcome["field_results"].values())

    def test_wrong_field_value(self):
        case = {"id": "1", "expect": {"filters": {"ufs": ["SP"]}}}
        outcome = compare_extraction(case, _result(LeadFilters(ufs=["RJ"])))
        assert outcome["exact_match"] is False
        assert outcome["field_results"]["ufs"] is False

    def test_list_fields_compared_as_sets(self):
        case = {"id": "1", "expect": {"filters": {"ufs": ["SP", "RJ"]}}}
        outcome = compare_extraction(case, _result(LeadFilters(ufs=["RJ", "SP"])))
        assert outcome["field_results"]["ufs"] is True

    def test_municipio_names_compared_case_insensitive(self):
        case = {"id": "1", "expect": {"filters": {"municipio_names": ["Santo André"]}}}
        outcome = compare_extraction(
            case, _result(LeadFilters(municipio_names=["santo andre"]))
        )
        assert outcome["field_results"]["municipio_names"] is True

    def test_cnae_query_compared_normalized(self):
        case = {
            "id": "1",
            "expect": {"filters": {"cnae_query": "Clínicas Odontológicas"}},
        }
        outcome = compare_extraction(
            case, _result(LeadFilters(cnae_query="clinicas odontologicas"))
        )
        assert outcome["field_results"]["cnae_query"] is True

    def test_capital_float_tolerance(self):
        case = {"id": "1", "expect": {"filters": {"min_capital": 100000.0}}}
        outcome = compare_extraction(case, _result(LeadFilters(min_capital=100000.001)))
        assert outcome["field_results"]["min_capital"] is True

    def test_hallucinated_filter_is_not_exact(self):
        case = {"id": "1", "expect": {"filters": {"ufs": ["SP"]}}}
        outcome = compare_extraction(
            case, _result(LeadFilters(ufs=["SP"], min_capital=50000))
        )
        assert outcome["field_results"]["ufs"] is True
        assert outcome["extra_fields"] == ["min_capital"]
        assert outcome["exact_match"] is False

    def test_resolved_fields_never_counted_as_extra(self):
        case = {"id": "1", "expect": {"filters": {"ufs": ["SP"]}}}
        outcome = compare_extraction(
            case,
            _result(
                LeadFilters(ufs=["SP"], cnae_codes=["8630-5/01"], municipio_ids=["1"])
            ),
        )
        assert outcome["extra_fields"] == []
        assert outcome["exact_match"] is True

    def test_cnae_query_without_expect_does_not_break_exact(self):
        # cnae_query é informacional: sua qualidade é medida pelo eval de CNAE.
        case = {"id": "1", "expect": {"filters": {"ufs": ["SP"]}}}
        outcome = compare_extraction(
            case, _result(LeadFilters(ufs=["SP"], cnae_query="empresas em geral"))
        )
        assert outcome["extra_fields"] == []
        assert outcome["exact_match"] is True

    def test_correct_refusal(self):
        case = {"id": "1", "expect": {"refused": True}}
        outcome = compare_extraction(case, _result(refused=True, reason="dado pessoal"))
        assert outcome["refusal_expected"] is True
        assert outcome["refused_correctly"] is True
        assert outcome["exact_match"] is True

    def test_missed_refusal(self):
        case = {"id": "1", "expect": {"refused": True}}
        outcome = compare_extraction(case, _result(LeadFilters(ufs=["SP"])))
        assert outcome["refused_correctly"] is False

    def test_false_refusal(self):
        case = {"id": "1", "expect": {"filters": {"ufs": ["SP"]}}}
        outcome = compare_extraction(case, _result(refused=True, reason="achou melhor"))
        assert outcome["false_refusal"] is True
        assert outcome["exact_match"] is False


class TestExtractionMetrics:
    def _cases(self):
        return [
            {"id": "1", "expect": {"filters": {"ufs": ["SP"], "min_age_years": 2}}},
            {"id": "2", "expect": {"filters": {"ufs": ["RJ"], "min_age_years": 5}}},
            {"id": "3", "expect": {"refused": True}},
        ]

    def _results(self):
        return [
            _result(LeadFilters(ufs=["SP"], min_age_years=2)),  # exato
            _result(LeadFilters(ufs=["RJ"], min_age_years=9)),  # erra idade
            _result(refused=True, reason="CPF"),  # recusa correta
        ]

    def test_metric_aggregation(self):
        metrics = extraction_metrics(self._cases(), self._results())
        assert metrics["n_cases"] == 3
        assert metrics["n_refusal_cases"] == 1
        assert metrics["correct_refusal_rate"] == 1.0
        assert metrics["false_refusal_rate"] == 0.0
        assert metrics["field_accuracy"]["ufs"]["rate"] == 1.0
        assert metrics["field_accuracy"]["min_age_years"]["rate"] == 0.5
        assert metrics["overall_field_accuracy"] == pytest.approx(0.75)
        assert metrics["exact_match_rate"] == pytest.approx(2 / 3)

    def test_no_refusal_cases_reports_none(self):
        cases = [{"id": "1", "expect": {"filters": {"ufs": ["SP"]}}}]
        results = [_result(LeadFilters(ufs=["SP"]))]
        metrics = extraction_metrics(cases, results)
        assert metrics["correct_refusal_rate"] is None

    def test_per_case_outcomes_recorded(self):
        metrics = extraction_metrics(self._cases(), self._results())
        assert metrics["per_case"][0]["id"] == "1"
        assert metrics["per_case"][2]["refused_correctly"] is True


class TestCnaeMetrics:
    def test_recall_at_k_any_match(self):
        ranked = ["0000-0/00", "8630-5/01", "1111-1/11"]
        assert recall_at_k(ranked, {"8630-5/01"}, 5) == 1.0
        assert recall_at_k(ranked, {"9999-9/99"}, 5) == 0.0

    def test_recall_at_k_respects_cutoff(self):
        ranked = ["0000-0/00", "8630-5/01"]
        assert recall_at_k(ranked, {"8630-5/01"}, 1) == 0.0
        assert recall_at_k(ranked, {"8630-5/01"}, 2) == 1.0

    def test_reciprocal_rank(self):
        ranked = ["0000-0/00", "8630-5/01"]
        assert reciprocal_rank(ranked, {"8630-5/01"}) == pytest.approx(0.5)
        assert reciprocal_rank(ranked, {"9999-9/99"}) == 0.0

    def test_cnae_metrics_aggregation(self):
        cases = [
            {"id": "a", "acceptable": ["8630-5/01"]},
            {"id": "b", "acceptable": ["6911-7/01", "6911-7/02"]},
            {"id": "c", "acceptable": ["4711-3/01"]},
        ]
        ranked_lists = [
            ["8630-5/01", "0000-0/00"],  # hit@1
            ["0000-0/00", "6911-7/02", "9999-9/99"],  # hit@2
            ["1111-1/11", "2222-2/22"],  # miss
        ]
        metrics = cnae_metrics(cases, ranked_lists, k_values=(1, 5))
        assert metrics["n_cases"] == 3
        assert metrics["recall@1"] == pytest.approx(1 / 3)
        assert metrics["recall@5"] == pytest.approx(2 / 3)
        assert metrics["mrr"] == pytest.approx((1.0 + 0.5 + 0.0) / 3)


class TestPercentile:
    def test_p50_and_p95_nearest_rank(self):
        values = sorted(range(1, 101))  # 1..100
        assert percentile(values, 50) == 50
        assert percentile(values, 95) == 95

    def test_empty_returns_none(self):
        assert percentile([], 50) is None

    def test_single_value(self):
        assert percentile([7], 95) == 7
