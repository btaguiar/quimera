"""Gera o relatório Markdown dos resultados em ``eval/results/``.

Uso: ``python -m eval.report [--results-dir eval/results] [--out eval/results/report.md]``
O relatório alimenta o README e a página de métricas — nenhuma métrica é escrita
à mão: tudo vem dos JSON gravados pelo ``run_eval``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_RESULTS_DIR = EVAL_DIR / "results"
DEFAULT_OUT = DEFAULT_RESULTS_DIR / "report.md"


def _fmt(value, digits=3) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _fmt_ms(value) -> str:
    return "—" if value is None else f"{value:.0f}"


def _extraction_rows(results: list[dict]) -> list[str]:
    header = (
        "| modelo | policy | casos | acerto campos | acerto exato | "
        "recusa correta | recusa indevida | p50 (ms) | p95 (ms) | commit | data |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|"
    )
    rows = [header]
    for payload in results:
        m = payload.get("metrics", {})
        rows.append(
            "| {model} | {policy} | {n} | {fields} | {exact} | {cr} | {fr} | "
            "{p50} | {p95} | {commit} | {date} |".format(
                model=payload.get("model", "—"),
                policy=payload.get("policy", "—"),
                n=m.get("n_cases", "—"),
                fields=_fmt(m.get("overall_field_accuracy")),
                exact=_fmt(m.get("exact_match_rate")),
                cr=_fmt(m.get("correct_refusal_rate")),
                fr=_fmt(m.get("false_refusal_rate")),
                p50=_fmt_ms(payload.get("latency_ms_p50")),
                p95=_fmt_ms(payload.get("latency_ms_p95")),
                commit=payload.get("commit", "—"),
                date=(payload.get("date") or "")[:10],
            )
        )
    return rows


def _cnae_rows(results: list[dict]) -> list[str]:
    header = (
        "| modelo | casos | recall@1 | recall@5 | MRR | "
        "p50 (ms) | p95 (ms) | commit | data |\n"
        "|---|---|---|---|---|---|---|---|---|"
    )
    rows = [header]
    for payload in results:
        m = payload.get("metrics", {})
        rows.append(
            "| {model} | {n} | {r1} | {r5} | {mrr} | {p50} | {p95} | {commit} | {date} |".format(
                model=payload.get("model", "—"),
                n=m.get("n_cases", "—"),
                r1=_fmt(m.get("recall@1")),
                r5=_fmt(m.get("recall@5")),
                mrr=_fmt(m.get("mrr")),
                p50=_fmt_ms(payload.get("latency_ms_p50")),
                p95=_fmt_ms(payload.get("latency_ms_p95")),
                commit=payload.get("commit", "—"),
                date=(payload.get("date") or "")[:10],
            )
        )
    return rows


def generate_report(results: list[dict]) -> str:
    """Monta o Markdown a partir dos payloads de resultado (sem per_case)."""
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Relatório de avaliação — Quimera",
        "",
        f"Gerado em {generated} a partir de {len(results)} resultados "
        "em `eval/results/`. Métricas 0–1; latência em ms.",
        "",
    ]
    extraction = [r for r in results if r.get("suite") == "extraction"]
    cnae = [r for r in results if r.get("suite") == "cnae"]

    lines.append("## Extração de filtros")
    lines.append("")
    if extraction:
        lines.extend(_extraction_rows(extraction))
    else:
        lines.append("_Sem resultados ainda._")
    lines.append("")

    lines.append("## Mapeamento CNAE")
    lines.append("")
    if cnae:
        lines.extend(_cnae_rows(cnae))
    else:
        lines.append("_Sem resultados ainda._")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m eval.report",
        description="Gera o relatório Markdown a partir dos JSON de resultados.",
    )
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    results_dir = Path(args.results_dir)
    results = []
    if results_dir.exists():
        for path in sorted(results_dir.glob("*.json")):
            try:
                results.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                print(f"aviso: {path} ignorado (JSON inválido)", file=sys.stderr)

    report = generate_report(results)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"Relatório gerado em {out} ({len(results)} resultados de {results_dir}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
