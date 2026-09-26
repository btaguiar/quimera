"""Testes do gerador de relatório Markdown a partir dos JSON de resultados."""

from __future__ import annotations

import json

from eval.report import generate_report, main


def _extraction_result(model="gemini-2.5-flash", policy="public", n=52, **overrides):
    payload = {
        "suite": "extraction",
        "model": model,
        "policy": policy,
        "date": "2026-09-25T12:00:00+00:00",
        "commit": "abc1234",
        "metrics": {
            "n_cases": n,
            "overall_field_accuracy": 0.91,
            "exact_match_rate": 0.72,
            "correct_refusal_rate": 1.0,
            "false_refusal_rate": 0.0,
        },
        "latency_ms_p50": 812.0,
        "latency_ms_p95": 1500.0,
    }
    payload["metrics"].update(overrides.pop("metrics", {}))
    payload.update(overrides)
    return payload


def _cnae_result(model="text-embedding-005", n=52, **overrides):
    payload = {
        "suite": "cnae",
        "model": model,
        "date": "2026-09-25T12:00:00+00:00",
        "commit": "abc1234",
        "metrics": {"n_cases": n, "recall@1": 0.85, "recall@5": 0.94, "mrr": 0.90},
        "latency_ms_p50": 40.0,
        "latency_ms_p95": 90.0,
    }
    payload["metrics"].update(overrides.pop("metrics", {}))
    payload.update(overrides)
    return payload


class TestGenerateReport:
    def test_contains_section_headers(self):
        report = generate_report([_extraction_result(), _cnae_result()])
        assert "## Extração de filtros" in report
        assert "## Mapeamento CNAE" in report

    def test_one_row_per_result(self):
        report = generate_report(
            [
                _extraction_result(model="gemini-2.5-flash"),
                _extraction_result(model="gemini-2.5-pro"),
                _cnae_result(),
            ]
        )
        assert "gemini-2.5-flash" in report
        assert "gemini-2.5-pro" in report
        assert "text-embedding-005" in report

    def test_none_values_rendered_as_dash(self):
        result = _extraction_result()
        result["metrics"]["correct_refusal_rate"] = None
        report = generate_report([result])
        assert "—" in report

    def test_empty_results_still_renders(self):
        report = generate_report([])
        assert "Quimera" in report

    def test_flows_are_excluded_from_tables(self):
        payload = _extraction_result()
        payload["metrics"]["per_case"] = [{"id": "1"}]
        report = generate_report([payload])
        assert "per_case" not in report


class TestMain:
    def test_writes_report_from_results_dir(self, tmp_path, capsys):
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        (results_dir / "a.json").write_text(
            json.dumps(_extraction_result()), encoding="utf-8"
        )
        out = tmp_path / "report.md"
        code = main(["--results-dir", str(results_dir), "--out", str(out)])
        assert code == 0
        text = out.read_text(encoding="utf-8")
        assert "## Extração de filtros" in text
        assert "gemini-2.5-flash" in text
        assert str(results_dir) in capsys.readouterr().out
