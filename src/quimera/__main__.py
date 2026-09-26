"""CLI da Quimera.

Uso: ``python -m quimera "pedido em português" --mode public|private [--k N] [--json]``
Por padrão, o modo vem de ``DEPLOY_MODE`` (vazio = público).
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from .extract import ExtractionError
from .pipeline import PipelineResult, run as run_pipeline
from .policy import PRIVATE, PUBLIC, Policy, resolve_policy
from .query import BytesBudgetExceededError

Runner = Callable[..., PipelineResult]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m quimera",
        description="Transforma um pedido em português em uma lista ranqueada de empresas (CNPJ).",
    )
    parser.add_argument(
        "pedido",
        help="pedido em linguagem natural (ex.: 'clínicas odontológicas em SP')",
    )
    parser.add_argument(
        "--mode",
        choices=["public", "private"],
        default=None,
        help="política de deploy (padrão: DEPLOY_MODE; vazio = público)",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=5,
        help="quantos CNAEs recuperar por busca de embeddings (padrão: 5)",
    )
    parser.add_argument("--json", action="store_true", help="saída em JSON")
    return parser


def _resolve_policy(mode: str | None) -> Policy:
    if mode is None:
        return resolve_policy()
    return PRIVATE if mode == "private" else PUBLIC


def _print_human(result: PipelineResult) -> None:
    if result.refused:
        print(f"Pedido recusado: {result.refusal_reason}")
        return

    print(f"Política: {result.policy}")
    if result.filters:
        parts = []
        if result.filters.ufs:
            parts.append("UFs=" + ",".join(result.filters.ufs))
        if result.filters.cnae_codes:
            parts.append("CNAEs=" + ",".join(result.filters.cnae_codes))
        if result.municipio_resolution:
            names = ", ".join(
                f"{nome} ({', '.join(ids)})"
                for nome, ids in result.municipio_resolution.items()
            )
            parts.append(f"municípios={names}")
        if parts:
            print("Filtros: " + " | ".join(parts))

    for aviso in result.warnings:
        print(f"Aviso: {aviso}")

    if result.cnae_matches:
        print("CNAEs escolhidos (similaridade):")
        for codigo, descricao, similaridade in result.cnae_matches:
            print(f"  {codigo} — {descricao} ({similaridade:.2f})")

    print(
        f"Resultado: {len(result.rows)} empresas | "
        f"{result.bytes_processed} bytes | "
        f"custo estimado US$ {result.estimated_cost_usd:.10f} | "
        f"{result.latency_ms:.0f} ms | modelo {result.model}"
    )
    if not result.rows:
        print("Nenhuma empresa encontrada com esses filtros.")
        return
    for i, row in enumerate(result.rows, start=1):
        municipio = row.get("municipio") or row.get("id_municipio") or "?"
        uf = row.get("sigla_uf") or "?"
        motivo = row.get("motivos_score") or []
        primeiro_motivo = motivo[0] if motivo else ""
        print(
            f"  {i}. {row.get('razao_social', '?')} [{row.get('cnpj', '?')}] "
            f"({municipio}/{uf}) — "
            f"score {row.get('score', 0.0)} — {primeiro_motivo}"
        )


def main(argv: list[str] | None = None, *, runner: Runner = run_pipeline) -> int:
    args = _build_parser().parse_args(argv)
    policy = _resolve_policy(args.mode)

    try:
        result = runner(
            args.pedido,
            policy,
            cnae_top_k=args.k,
        )
    except BytesBudgetExceededError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    except ExtractionError as exc:
        print(f"Erro de extração: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    if args.json:
        import json

        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_human(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
