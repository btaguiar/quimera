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
        assert metrics == {"thresholds": {}, "extraction": [], "cnae": [], "e2e": []}

    def test_reads_e2e_suite(self, tmp_path):
        results = tmp_path / "results"
        results.mkdir()
        _write(
            results / "e2e_flash_20260926.json",
            {
                "suite": "e2e",
                "date": "2026-09-26T19:17:57+00:00",
                "commit": "6ac4f68",
                "metrics": {"case_pass_rate": 0.95, "row_precision": 0.997},
            },
        )
        metrics = load_metrics(eval_dir=tmp_path)
        assert metrics["e2e"][0]["metrics"]["case_pass_rate"] == 0.95

    def test_env_eval_dir_is_used(self, tmp_path, monkeypatch):
        (tmp_path / "results").mkdir()
        _write(
            tmp_path / "results" / "cnae_m_20260926.json",
            {"suite": "cnae", "metrics": {"mrr": 0.5}},
        )
        monkeypatch.setenv("EVAL_DIR", str(tmp_path))
        assert load_metrics()["cnae"][0]["metrics"]["mrr"] == 0.5

    def test_non_dict_json_payloads_are_skipped(self, tmp_path):
        results = tmp_path / "results"
        results.mkdir()
        (results / "lista.json").write_text("[1, 2, 3]", encoding="utf-8")
        (results / "texto.json").write_text('"apenas texto"', encoding="utf-8")
        (results / "suite_lista.json").write_text(
            json.dumps({"suite": ["x"], "metrics": {}}), encoding="utf-8"
        )
        _write(
            results / "valido.json",
            {"suite": "cnae", "metrics": {"mrr": 0.5}},
        )
        metrics = load_metrics(eval_dir=tmp_path)
        assert metrics["cnae"] == [{"suite": "cnae", "metrics": {"mrr": 0.5}}]

    def test_non_dict_thresholds_ignored(self, tmp_path):
        (tmp_path / "thresholds.json").write_text("[1, 2]", encoding="utf-8")
        metrics = load_metrics(eval_dir=tmp_path)
        assert metrics["thresholds"] == {}

    def test_results_dir_override(self, tmp_path):
        results = tmp_path / "results"
        results.mkdir()
        _write(
            results / "cnae_m.json",
            {"suite": "cnae", "metrics": {"recall@5": 0.7}},
        )
        (tmp_path / "thresholds.json").write_text("{}", encoding="utf-8")
        metrics = load_metrics(results_dir=results, eval_dir=tmp_path)
        assert metrics["cnae"][0]["metrics"]["recall@5"] == 0.7


class TestMetricsCache:
    """Relê eval/ só quando algum arquivo muda."""

    def _grava(self, pasta, nome, payload):
        (pasta / nome).write_text(json.dumps(payload), encoding="utf-8")

    def test_reuses_until_a_file_changes(self, tmp_path, monkeypatch):
        from quimera.api import metrics as mod

        results = tmp_path / "results"
        results.mkdir()
        self._grava(results, "a.json", {"suite": "cnae", "metrics": {"recall@5": 0.9}})
        leituras = []
        original = mod._read_metrics

        def contando(r, b):
            leituras.append(1)
            return original(r, b)

        monkeypatch.setattr(mod, "_read_metrics", contando)
        primeiro = mod.load_metrics(eval_dir=tmp_path)
        mod.load_metrics(eval_dir=tmp_path)
        assert len(leituras) == 1
        self._grava(results, "b.json", {"suite": "cnae", "metrics": {"recall@5": 0.95}})
        segundo = mod.load_metrics(eval_dir=tmp_path)
        assert len(leituras) == 2
        assert len(primeiro["cnae"]) == 1 and len(segundo["cnae"]) == 2

    def test_returned_dict_does_not_leak_into_cache(self, tmp_path):
        from quimera.api.metrics import load_metrics

        (tmp_path / "results").mkdir()
        load_metrics(eval_dir=tmp_path)["cnae"].append({"x": 1})
        assert load_metrics(eval_dir=tmp_path)["cnae"] == []
