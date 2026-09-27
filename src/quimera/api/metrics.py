"""Métricas da Fase 2 para o endpoint GET /metrics.

Lê os JSON gravados por ``eval/run_eval`` (nenhuma métrica é escrita à
mão) e os limiares de ``eval/thresholds.json``. ``EVAL_DIR`` aponta a
raiz de ``eval/`` (padrão: ``eval`` relativo ao cwd; no deploy, o
diretório é copiado para dentro da imagem).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_EVAL_DIR = "eval"


def _strip_per_case(payload: dict) -> dict:
    payload.pop("per_case", None)
    metrics = payload.get("metrics")
    if isinstance(metrics, dict):
        metrics.pop("per_case", None)
    return payload


def load_metrics(
    *, results_dir: str | Path | None = None, eval_dir: str | Path | None = None
) -> dict:
    """Devolve ``{"thresholds": {...}, "extraction": [...], "cnae": [...], "e2e": [...]}``."""
    base = Path(eval_dir or os.environ.get("EVAL_DIR", DEFAULT_EVAL_DIR))
    results = Path(results_dir) if results_dir else base / "results"
    suites: dict[str, list[dict]] = {"extraction": [], "cnae": [], "e2e": []}
    if results.exists():
        for path in sorted(results.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            payload = _strip_per_case(payload)
            suite = payload.get("suite")
            if isinstance(suite, str) and suite in suites:
                suites[suite].append(payload)

    thresholds: dict = {}
    thresholds_path = base / "thresholds.json"
    if thresholds_path.exists():
        try:
            thresholds = json.loads(thresholds_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            thresholds = {}
    if not isinstance(thresholds, dict):
        thresholds = {}
    thresholds.pop("_comentario", None)
    return {"thresholds": thresholds, **suites}
