"""Testes do run_eval: suites com providers injetáveis, limiares e gravação."""

from __future__ import annotations

import json

from eval.run_eval import (
    check_thresholds,
    load_cases,
    run_cnae_suite,
    run_extraction_suite,
    save_result,
)
from quimera.filters import ExtractionResult, LeadFilters


def _extract_ok(request: str) -> ExtractionResult:
    return ExtractionResult(refused=False, filters=LeadFilters(ufs=["SP"]))


def _extract_refused(request: str) -> ExtractionResult:
    return ExtractionResult(refused=True, refusal_reason="dado pessoal")


class TestLoadCases:
    def test_loads_jsonl_ignoring_blank_lines(self, tmp_path):
        path = tmp_path / "golden.jsonl"
        path.write_text('{"id": "1"}\n\n{"id": "2"}\n', encoding="utf-8")
        cases = load_cases(path)
        assert [c["id"] for c in cases] == ["1", "2"]


class TestRunExtractionSuite:
    def _cases(self):
        return [
            {
                "id": "1",
                "policy": "public",
                "request": "a",
                "expect": {"filters": {"ufs": ["SP"]}},
            },
            {
                "id": "2",
                "policy": "private",
                "request": "b",
                "expect": {"filters": {"ufs": ["RJ"]}},
            },
            {
                "id": "3",
                "policy": "public",
                "request": "c",
                "expect": {"refused": True},
            },
        ]

    def test_runs_only_cases_of_the_policy(self):
        calls = []

        def extract_fn(request):
            calls.append(request)
            if request == "c":
                return _extract_refused(request)
            return _extract_ok(request)

        payload = run_extraction_suite(
            self._cases(), extract_fn, policy="public", model="m-teste"
        )
        assert calls == ["a", "c"]
        assert payload["suite"] == "extraction"
        assert payload["policy"] == "public"
        assert payload["model"] == "m-teste"
        assert payload["metrics"]["n_cases"] == 2
        assert payload["metrics"]["correct_refusal_rate"] == 1.0
        for key in ("date", "commit", "latency_ms_p50", "latency_ms_p95"):
            assert key in payload

    def test_records_latency(self):
        payload = run_extraction_suite(
            [{"id": "1", "request": "a", "expect": {"filters": {}}}],
            _extract_ok,
        )
        assert payload["latency_ms_p50"] >= 0
        assert payload["latency_ms_p95"] >= 0


class TestRunCnaeSuite:
    def test_suite_with_injected_search(self):
        cases = [{"id": "a", "query": "dentistas", "acceptable": ["8630-5/01"]}]

        def search_fn(query, k):
            assert query == "dentistas"
            return [
                ("8630-5/01", "Atividades odontológicas", 0.9),
                ("0000-0/00", "x", 0.1),
            ]

        payload = run_cnae_suite(cases, search_fn, model="emb-teste")
        assert payload["suite"] == "cnae"
        assert payload["model"] == "emb-teste"
        assert payload["metrics"]["recall@1"] == 1.0
        assert payload["metrics"]["mrr"] == 1.0
        assert payload["metrics"]["per_case"][0]["ranked"] == ["8630-5/01", "0000-0/00"]


class TestCheckThresholds:
    def _metrics(self, **overrides):
        metrics = {
            "correct_refusal_rate": 1.0,
            "overall_field_accuracy": 0.9,
            "recall@5": 0.8,
        }
        metrics.update(overrides)
        return metrics

    def test_all_pass(self):
        failures = check_thresholds(
            self._metrics(),
            {
                "correct_refusal_rate": 1.0,
                "overall_field_accuracy": 0.85,
                "recall_at_5": 0.75,
            },
        )
        assert failures == []

    def test_correct_refusal_below_1_fails(self):
        failures = check_thresholds(
            self._metrics(correct_refusal_rate=0.9),
            {
                "correct_refusal_rate": 1.0,
                "overall_field_accuracy": 0.85,
                "recall_at_5": None,
            },
        )
        assert len(failures) == 1
        assert "recusa" in failures[0]

    def test_field_accuracy_below_threshold_fails(self):
        failures = check_thresholds(
            self._metrics(overall_field_accuracy=0.7),
            {
                "correct_refusal_rate": 1.0,
                "overall_field_accuracy": 0.85,
                "recall_at_5": None,
            },
        )
        assert len(failures) == 1

    def test_null_threshold_is_baseline_pending_and_skips(self):
        failures = check_thresholds(
            self._metrics(**{"recall@5": 0.1}),
            {
                "correct_refusal_rate": 1.0,
                "overall_field_accuracy": 0.85,
                "recall_at_5": None,
            },
        )
        assert failures == []

    def test_none_metric_skips(self):
        failures = check_thresholds(
            self._metrics(correct_refusal_rate=None),
            {
                "correct_refusal_rate": 1.0,
                "overall_field_accuracy": 0.85,
                "recall_at_5": None,
            },
        )
        assert failures == []

    def test_holdout_golden_uses_holdout_threshold_when_present(self):
        # Conjunto separado tem limiar próprio: mais difícil por natureza
        # (ambiguidade de CNAE mais frequente), não herda o do golden principal.
        failures = check_thresholds(
            {"row_precision": 0.94},
            {"e2e_row_precision": 0.98, "e2e_holdout_row_precision": 0.9},
            golden="golden_e2e_holdout.jsonl",
        )
        assert failures == []

    def test_non_holdout_golden_ignores_holdout_threshold(self):
        failures = check_thresholds(
            {"row_precision": 0.94},
            {"e2e_row_precision": 0.98, "e2e_holdout_row_precision": 0.9},
            golden="golden_e2e.jsonl",
        )
        assert len(failures) == 1
        assert "e2e_row_precision" in failures[0]

    def test_holdout_without_specific_threshold_falls_back_to_base(self):
        failures = check_thresholds(
            {"row_precision": 0.94},
            {"e2e_row_precision": 0.98},
            golden="golden_e2e_holdout.jsonl",
        )
        assert len(failures) == 1
        assert "e2e_row_precision" in failures[0]

    def test_no_golden_behaves_like_before(self):
        failures = check_thresholds(
            self._metrics(), {"correct_refusal_rate": 1.0, "overall_field_accuracy": 0.85}
        )
        assert failures == []

    def test_correct_refusal_stays_strict_on_holdout(self):
        # Recusa correta é inegociável (spec Fase 2): nunca ganha limiar
        # próprio de conjunto separado, mesmo que outras métricas ganhem.
        failures = check_thresholds(
            {"e2e_correct_refusal_rate": 0.9},
            {"e2e_correct_refusal_rate": 1.0},
            golden="golden_e2e_holdout.jsonl",
        )
        assert len(failures) == 1


class TestSaveResult:
    def test_writes_json_with_suite_and_timestamp(self, tmp_path):
        payload = {"suite": "extraction", "model": "m", "metrics": {"n_cases": 1}}
        path = save_result(payload, results_dir=tmp_path)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["suite"] == "extraction"
        assert path.name.startswith("extraction_")
        assert path.suffix == ".json"


def test_sintetico_golden_uses_its_own_threshold():
    from eval.run_eval import check_thresholds

    th = {"e2e_row_precision": 0.98, "e2e_sintetico_row_precision": 0.95}
    m = {"row_precision": 0.96}
    assert check_thresholds(m, th, golden="golden_e2e_sintetico.jsonl") == []
    assert len(check_thresholds(m, th, golden="golden_e2e.jsonl")) == 1
