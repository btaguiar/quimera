"""Métricas da Fase 2 para o endpoint GET /metrics.

Lê os JSON gravados por ``eval/run_eval`` (nenhuma métrica é escrita à
mão) e os limiares de ``eval/thresholds.json``. ``EVAL_DIR`` aponta a
raiz de ``eval/`` (padrão: ``eval`` relativo ao cwd; no deploy, o
diretório é copiado para dentro da imagem).
"""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

DEFAULT_EVAL_DIR = "eval"


def _strip_per_case(payload: dict) -> dict:
    # detail: um item por caso (10 mil no golden sintético), sem uso no front.
    payload.pop("per_case", None)
    payload.pop("detail", None)
    metrics = payload.get("metrics")
    if isinstance(metrics, dict):
        metrics.pop("per_case", None)
    return payload


# Cache por diretório: /metrics é público e sem rate limit, e reler
# eval/results/ (22 MB com o golden sintético) custava ~0,24 s de CPU por
# acesso na única instância da demo (2026-09-30).
_cache: dict[tuple[str, str], tuple[tuple, dict]] = {}
_cache_lock = threading.Lock()


def _assinatura(results: Path, base: Path) -> tuple:
    """Nome, tamanho e mtime de cada arquivo lido: muda se qualquer um mudar."""
    arquivos = sorted(results.glob("*.json")) if results.exists() else []
    arquivos.append(base / "thresholds.json")
    assinatura = []
    for path in arquivos:
        try:
            st = path.stat()
        except OSError:
            continue
        assinatura.append((path.name, st.st_size, st.st_mtime_ns))
    return tuple(assinatura)


def load_metrics(
    *, results_dir: str | Path | None = None, eval_dir: str | Path | None = None
) -> dict:
    """Devolve ``{"thresholds": {...}, "extraction": [...], "cnae": [...], "e2e": [...]}``.

    Relê os arquivos só quando algum muda; devolve uma cópia (quem chama pode
    alterar o dicionário sem sujar o cache).
    """
    base = Path(eval_dir or os.environ.get("EVAL_DIR", DEFAULT_EVAL_DIR))
    results = Path(results_dir) if results_dir else base / "results"
    chave = (str(results.resolve()), str(base.resolve()))
    assinatura = _assinatura(results, base)
    with _cache_lock:
        guardado = _cache.get(chave)
        if guardado is None or guardado[0] != assinatura:
            guardado = (assinatura, _read_metrics(results, base))
            _cache[chave] = guardado
    return copy.deepcopy(guardado[1])


def _read_metrics(results: Path, base: Path) -> dict:
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
