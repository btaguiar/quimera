"""Testes do loader de métricas (Fase 2) para GET /metrics."""

from __future__ import annotations

import json

from quimera.api.metrics import load_metrics


def _write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class TestLoadMetrics:
    def test_reads_suites_thresholds_and_drops_per_case(self, tmp_path):
        results = tmp_path / "results"
        results.mkdir()
        _write(
            results / "extraction_m1_20260926.json",
            {
                "suite": "extraction",
                "metrics": {"n_cases": 45},
                "per_case": [{"id": "ext_001"}],
            },
        )
        _write(
            results / "cnae_m2_20260926.json",
            {"suite": "cnae", "metrics": {"recall@5": 0.742}},
        )
        (results / "broken.json").write_text("{invalido", encoding="utf-8")
        _write(
            tmp_path / "thresholds.json",
            {"overall_field_accuracy": 0.85, "_comentario": {"nota": "x"}},
        )

        metrics = load_metrics(eval_dir=tmp_path)

        assert metrics["thresholds"] == {"overall_field_accuracy": 0.85}
        assert metrics["extraction"][0]["metrics"]["n_cases"] == 45
        assert "per_case" not in metrics["extraction"][0]
        assert metrics["cnae"][0]["metrics"]["recall@5"] == 0.742
        assert len(metrics["extraction"]) == 1

    def test_drops_per_case_nested_in_metrics(self, tmp_path):
        results = tmp_path / "results"
        results.mkdir()
        _write(
            results / "cnae_m_20260926.json",
            {
                "suite": "cnae",
                "model": "text-embedding-005",
                "metrics": {
                    "recall@5": 0.742,
                    "n_cases": 66,
                    "per_case": [{"id": "c1"}, {"id": "c2"}],
                },
            },
        )

        metrics = load_metrics(eval_dir=tmp_path)

        assert "per_case" not in metrics["cnae"][0]["metrics"]
        assert metrics["cnae"][0]["metrics"]["n_cases"] == 66

    def test_missing_dir_returns_empty_structure(self, tmp_path):
        metrics = load_metrics(eval_dir=tmp_path / "inexistente")
        assert metrics == {"thresholds": {}, "extraction": [], "cnae": []}

    def test_env_eval_dir_is_used(self, tmp_path, monkeypatch):
        (tmp_path / "results").mkdir()
        _write(
            tmp_path / "results" / "cnae_m_20260926.json",
            {"suite": "cnae", "metrics": {"mrr": 0.5}},
        )
        monkeypatch.setenv("EVAL_DIR", str(tmp_path))
        assert load_metrics()["cnae"][0]["metrics"]["mrr"] == 0.5
