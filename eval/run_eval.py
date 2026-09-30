"""Roda os golden sets contra os modelos e grava resultados com limiares.

Uso (requer credenciais GCP):

    python -m eval.run_eval --suite all --policy public --model gemini-2.5-flash
    python -m eval.run_eval --suite cnae --k 5

Resultados vão para ``eval/results/*.json`` (commit, data, modelo, métricas,
latência). Sai com código != 0 se algum limiar de ``eval/thresholds.json`` falhar.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from eval.metrics import (
    cnae_metrics,
    e2e_case_outcome,
    e2e_metrics_from_outcomes,
    extraction_metrics,
)
from quimera.cnae import DEFAULT_EMBED_MODEL
from quimera.extract import DEFAULT_MODEL
from quimera.filters import ExtractionResult

EVAL_DIR = Path(__file__).resolve().parent
GOLDEN_EXTRACTION = EVAL_DIR / "golden_extraction.jsonl"
GOLDEN_CNAE = EVAL_DIR / "golden_cnae.jsonl"
GOLDEN_E2E = EVAL_DIR / "golden_e2e.jsonl"
THRESHOLDS_PATH = EVAL_DIR / "thresholds.json"
RESULTS_DIR = EVAL_DIR / "results"

ExtractFn = Callable[[str], ExtractionResult]
SearchFn = Callable[[str, int], list[tuple[str, str, float]]]
# Pedido -> resultado do pipeline serializado (PipelineResult.to_dict()).
RunFn = Callable[[str], dict]

# Limiar nulo = baseline pendente (anotar após a primeira medição, não inventar).
DEFAULT_THRESHOLDS = {
    "correct_refusal_rate": 1.0,  # spec: recusa correta = 100%
    "overall_field_accuracy": 0.85,  # spec: acerto de extração >= 85%
    "recall_at_5": None,  # spec: definir baseline após primeira medição
}


def load_cases(path: str | Path) -> list[dict]:
    cases = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _payload(suite: str, metrics: dict, latencies: list[float], **extra) -> dict:
    return {
        "suite": suite,
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": _commit(),
        "metrics": metrics,
        "latency_ms_p50": _pct(latencies, 50),
        "latency_ms_p95": _pct(latencies, 95),
        **extra,
    }


def _pct(values: list[float], p: int):
    from eval.metrics import percentile

    return round(percentile(values, p), 2) if values else None


def run_extraction_suite(
    cases: Sequence[dict],
    extract_fn: ExtractFn,
    *,
    policy: str = "public",
    model: str | None = None,
) -> dict:
    """Extrai filtros dos casos da policy escolhida e agrega métricas."""
    selected = [c for c in cases if c.get("policy", "public") == policy]
    results: list[ExtractionResult] = []
    latencies: list[float] = []
    for case in selected:
        started = time.perf_counter()
        results.append(extract_fn(case["request"]))
        latencies.append((time.perf_counter() - started) * 1000)
    metrics = extraction_metrics(selected, results)
    return _payload(
        "extraction",
        metrics,
        latencies,
        policy=policy,
        model=model or os.environ.get("EXTRACT_MODEL", DEFAULT_MODEL),
    )


def run_cnae_suite(
    cases: Sequence[dict],
    search_fn: SearchFn,
    *,
    k_values: tuple[int, ...] = (1, 5),
    model: str | None = None,
) -> dict:
    """Busca CNAEs para cada query e agrega recall@k e MRR."""
    ranked_lists: list[list[str]] = []
    latencies: list[float] = []
    max_k = max(k_values)
    for case in cases:
        started = time.perf_counter()
        matches = search_fn(case["query"], max_k)
        latencies.append((time.perf_counter() - started) * 1000)
        ranked_lists.append([codigo for codigo, _, _ in matches])
    metrics = cnae_metrics(cases, ranked_lists, k_values=k_values)
    return _payload(
        "cnae",
        metrics,
        latencies,
        model=model or os.environ.get("EMBED_MODEL", DEFAULT_EMBED_MODEL),
    )


def _e2e_record(case: dict, result: dict, latency_ms: float, today: date) -> dict:
    """Desfecho de um caso sem as linhas (que só servem para calculá-lo)."""
    return {
        "id": case["id"],
        "outcome": e2e_case_outcome(case, result, today),
        "latency_ms": latency_ms,
        "timings_ms": result.get("timings_ms") or {},
        "bytes_billed": result.get("bytes_billed"),
        "estimated_cost_usd": result.get("estimated_cost_usd"),
        "has_rows": bool(result.get("rows")),
        "detail": {
            "id": case["id"],
            "request": case["request"],
            "filters": result.get("filters"),
            "cnae_codes": [m[0] for m in result.get("cnae_matches") or []],
            "cnae_fallback": bool(result.get("cnae_fallback")),
            "warnings": result.get("warnings"),
            "latency_ms": round(latency_ms, 1),
            "timings_ms": result.get("timings_ms"),
            "bytes_billed": result.get("bytes_billed"),
        },
    }


def _load_checkpoint(path: Path | None, ids: set[str]) -> dict[str, dict]:
    done: dict[str, dict] = {}
    if path is None or not path.exists():
        return done
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # última linha cortada por interrupção
            if record.get("id") in ids:
                done[record["id"]] = record
    return done


def run_e2e_suite(
    cases: Sequence[dict],
    run_fn: RunFn,
    *,
    policy: str = "public",
    golden: str = GOLDEN_E2E.name,
    workers: int = 1,
    checkpoint: str | Path | None = None,
    max_rows: int | None = None,
    retries: int = 3,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Roda o pipeline inteiro por pedido e confere cada empresa devolvida.

    Além da qualidade, registra latência total e por etapa, e bytes por pedido.

    ``workers`` > 1 roda casos em paralelo. ``checkpoint`` (jsonl) grava cada
    caso ao terminar e, numa nova chamada com o mesmo arquivo, pula os já
    feitos: uma rodada de horas sobrevive a queda de rede. Caso que falha
    ``retries`` vezes fica fora do checkpoint e a suíte levanta erro no fim —
    métrica sobre um subconjunto silencioso não vale.
    """
    today = date.today()
    checkpoint_path = Path(checkpoint) if checkpoint else None
    records = _load_checkpoint(checkpoint_path, {c["id"] for c in cases})
    pending = [c for c in cases if c["id"] not in records]
    lock = threading.Lock()
    errors: dict[str, str] = {}

    def one(case: dict) -> None:
        last_exc: Exception | None = None
        for attempt in range(retries):
            started = time.perf_counter()
            try:
                result = run_fn(case["request"])
            except Exception as exc:  # rede/cota: tenta de novo
                last_exc = exc
                if attempt + 1 < retries:
                    time.sleep(2**attempt)
                continue
            latency = (time.perf_counter() - started) * 1000
            record = _e2e_record(case, result, latency, today)
            with lock:
                records[case["id"]] = record
                if checkpoint_path is not None:
                    with checkpoint_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                if progress:
                    progress(len(records), len(cases))
            return
        with lock:
            errors[case["id"]] = repr(last_exc)

    if checkpoint_path is not None:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, pending))
    else:
        for case in pending:
            one(case)
    if errors:
        sample = "; ".join(f"{k}: {v}" for k, v in list(errors.items())[:3])
        raise RuntimeError(
            f"{len(errors)} caso(s) sem resultado após {retries} tentativas "
            f"({sample}). Rode de novo com o mesmo --checkpoint para retomar."
        )

    ordered = [records[c["id"]] for c in cases]
    metrics = e2e_metrics_from_outcomes([r["outcome"] for r in ordered])

    def stage_values(stage: str) -> list[float]:
        return [r["timings_ms"][stage] for r in ordered if stage in r["timings_ms"]]

    stages = sorted({k for r in ordered for k in r["timings_ms"]})
    stage_latency = {
        stage: {
            "p50": _pct(stage_values(stage), 50),
            "p95": _pct(stage_values(stage), 95),
        }
        for stage in stages
    }
    # Casos em que a seleção de CNAE caiu no plano B (cota/timeout do Gemini):
    # a taxa sem eles separa falha de infraestrutura de falha de qualidade.
    sem_fallback = [r["outcome"] for r in ordered if not r["detail"].get("cnae_fallback")]
    metrics["cnae_fallback_rate"] = (len(ordered) - len(sem_fallback)) / len(ordered)
    metrics["case_pass_rate_sem_fallback"] = (
        sum(o["passed"] for o in sem_fallback) / len(sem_fallback) if sem_fallback else None
    )
    billed = [r.get("bytes_billed") or 0 for r in ordered if r["has_rows"]]
    metrics["bytes_billed_p50"] = _pct(billed, 50)
    metrics["bytes_billed_p95"] = _pct(billed, 95)
    metrics["estimated_cost_usd_total"] = round(
        sum(r.get("estimated_cost_usd") or 0 for r in ordered), 6
    )
    extra = {"max_rows": max_rows} if max_rows else {}
    return _payload(
        "e2e",
        metrics,
        [r["latency_ms"] for r in ordered],
        policy=policy,
        model=os.environ.get("EXTRACT_MODEL", DEFAULT_MODEL),
        stage_latency_ms=stage_latency,
        detail=[r["detail"] for r in ordered],
        golden=golden,
        **extra,
    )


# Limiar (thresholds.json) -> (métrica agregada, rótulo legível no CI).
_THRESHOLD_TO_METRIC = {
    "correct_refusal_rate": ("correct_refusal_rate", "recusa correta"),
    "overall_field_accuracy": ("overall_field_accuracy", "acerto de extração"),
    "recall_at_5": ("recall@5", "recall@5 de CNAE"),
    "e2e_case_pass_rate": ("case_pass_rate", "casos ponta a ponta 100% corretos"),
    "e2e_row_precision": ("row_precision", "precisão por empresa devolvida"),
    "e2e_correct_refusal_rate": (
        "e2e_correct_refusal_rate",
        "recusa correta ponta a ponta",
    ),
}


def check_thresholds(
    metrics: dict, thresholds: dict, *, golden: str | None = None
) -> list[str]:
    """Devolve mensagens de falha; lista vazia = todos os limiares ok.

    ``golden``: nome do arquivo golden da suíte e2e (``run_eval.py --golden``).
    Para ``golden_e2e_<variante>.jsonl`` (``holdout``, ``sintetico``), usa o
    limiar ``e2e_<variante>_<resto>`` se existir em ``thresholds`` (ex.:
    ``e2e_holdout_row_precision``), senão cai no limiar padrão da mesma chave
    (``e2e_row_precision``). O conjunto separado é mais difícil por natureza
    (mesma ambiguidade de seleção de CNAE que já limita o recall@5 do golden
    principal, aqui sem o filtro de curadoria) — não recebe automaticamente o
    limiar calibrado contra o golden principal; o sintético idem, e ainda
    confere até 200 empresas por caso.
    ``e2e_correct_refusal_rate`` nunca ganha variante: recusa correta é
    inegociável em qualquer conjunto (spec Fase 2).
    """
    failures = []
    variante = None
    if golden:
        m = re.match(r"golden_e2e_(\w+)\.jsonl$", Path(golden).name)
        variante = m.group(1) if m else None
    for threshold_key, (metric_key, label) in _THRESHOLD_TO_METRIC.items():
        lookup_key = threshold_key
        if variante and threshold_key != "e2e_correct_refusal_rate":
            variant_key = threshold_key.replace("e2e_", f"e2e_{variante}_", 1)
            if variant_key in thresholds:
                lookup_key = variant_key
        limit = thresholds.get(lookup_key)
        if limit is None:
            continue  # baseline pendente
        value = metrics.get(metric_key)
        if value is None:
            continue  # métrica não aplicável a esta suíte
        if value < limit:
            failures.append(
                f"{label} = {value:.3f}, abaixo do limiar {limit:.2f} ({lookup_key})"
            )
    return failures


def save_result(payload: dict, results_dir: str | Path = RESULTS_DIR) -> Path:
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = results_dir / f"{payload['suite']}_{payload.get('model', 'na')}_{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_thresholds(path: str | Path = THRESHOLDS_PATH) -> dict:
    path = Path(path)
    if not path.exists():
        return dict(DEFAULT_THRESHOLDS)
    return {**DEFAULT_THRESHOLDS, **json.loads(path.read_text(encoding="utf-8"))}


def _real_extract_fn(policy_obj, model):
    from quimera.extract import extract_filters

    return lambda request: extract_filters(request, policy_obj, model=model)


def _real_run_fn(policy_obj, max_rows: int | None = None):
    from dataclasses import replace

    from quimera.pipeline import run, warmup

    # Como o servidor (python -m quimera.api): sem isso o 1º caso paga ~16 s
    # de clientes e diretório e distorce o p95.
    warmup()
    if max_rows:
        # Mesma policy (mesmas exclusões do público), só com mais linhas.
        policy_obj = replace(policy_obj, max_rows=max_rows)
    return lambda request: run(request, policy_obj, limit=max_rows).to_dict()


def _real_search_fn(index_path, embed_model):
    from quimera.cnae import search, vertex_embedder

    # Importante: o índice precisa ter sido construído com o MESMO modelo de
    # embedding usado para a query (comparar modelos = um índice por modelo,
    # construído com `python -m quimera.cnae build`).
    embedder = vertex_embedder(embed_model) if embed_model else None

    def fn(query: str, k: int):
        return search(query, k, index_path=index_path, embedder=embedder)

    return fn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m eval.run_eval",
        description="Roda os golden sets e verifica limiares (falha o CI se estourar).",
    )
    parser.add_argument(
        "--suite", choices=["extraction", "cnae", "e2e", "all"], default="all"
    )
    parser.add_argument("--policy", choices=["public", "private"], default="public")
    parser.add_argument("--model", default=None, help="modelo de extração ou embedding")
    parser.add_argument("--index", default=None, help="caminho do índice CNAE")
    parser.add_argument(
        "--limit", type=int, default=None, help="rodar só os N primeiros casos"
    )
    parser.add_argument(
        "--golden",
        default=None,
        help="golden da suíte e2e (padrão: golden_e2e.jsonl; "
        "conjunto separado: golden_e2e_holdout.jsonl)",
    )
    parser.add_argument("--workers", type=int, default=1, help="casos e2e em paralelo")
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="empresas conferidas por caso e2e (padrão: o teto da policy, 50)",
    )
    parser.add_argument(
        "--checkpoint",
        default=None,
        help="jsonl de progresso da suíte e2e; rodar de novo com o mesmo "
        "arquivo retoma de onde parou",
    )
    args = parser.parse_args(argv)

    thresholds = load_thresholds()
    failures: list[str] = []

    if args.suite in ("extraction", "all"):
        cases = load_cases(GOLDEN_EXTRACTION)
        if args.limit:
            cases = cases[: args.limit]
        from quimera.policy import PRIVATE, PUBLIC

        policy_obj = PUBLIC if args.policy == "public" else PRIVATE
        payload = run_extraction_suite(
            cases,
            _real_extract_fn(policy_obj, args.model),
            policy=args.policy,
            model=args.model,
        )
        path = save_result(payload)
        print(f"[extraction] {payload['metrics']['n_cases']} casos -> {path}")
        failures += check_thresholds(payload["metrics"], thresholds)

    if args.suite in ("cnae", "all"):
        cases = load_cases(GOLDEN_CNAE)
        if args.limit:
            cases = cases[: args.limit]
        index_path = args.index or os.environ.get("CNAE_INDEX_PATH")
        payload = run_cnae_suite(
            cases, _real_search_fn(index_path, args.model), model=args.model
        )
        path = save_result(payload)
        print(f"[cnae] {payload['metrics']['n_cases']} casos -> {path}")
        failures += check_thresholds(payload["metrics"], thresholds)

    if args.suite in ("e2e", "all"):
        golden_path = Path(args.golden) if args.golden else GOLDEN_E2E
        if not golden_path.is_absolute() and not golden_path.exists():
            golden_path = EVAL_DIR / golden_path
        cases = load_cases(golden_path)
        if args.limit:
            cases = cases[: args.limit]
        from quimera.policy import PUBLIC

        def _progress(done: int, total: int) -> None:
            if done % 50 == 0 or done == total:
                print(f"      {done}/{total}", flush=True)

        payload = run_e2e_suite(
            cases,
            _real_run_fn(PUBLIC, args.max_rows),
            golden=golden_path.name,
            workers=args.workers,
            checkpoint=args.checkpoint,
            max_rows=args.max_rows,
            progress=_progress,
        )
        path = save_result(payload)
        m = payload["metrics"]
        print(
            f"[e2e] {m['n_cases']} casos, {m['n_rows']} empresas -> {path}\n"
            f"      casos ok {m['case_pass_rate']:.3f} | precisão por empresa "
            f"{m['row_precision']:.3f} | p50 {payload['latency_ms_p50']} ms"
        )
        failed = [o for o in m["per_case"] if not o["passed"]]
        for outcome in failed[:30]:
            print(f"      FALHOU {outcome['id']}: {'; '.join(outcome['problems'])}")
        if len(failed) > 30:
            print(f"      ... e mais {len(failed) - 30} (ver {path})")
        failures += check_thresholds(m, thresholds, golden=golden_path.name)

    for failure in failures:
        print(f"LIMIAR FALHOU: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
