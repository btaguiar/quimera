"""Métricas puras do eval (sem I/O, sem GCP).

Convenções de comparação (documentadas para o relatório):
- Campos de lista (``ufs``, ``portes``, ``municipio_names``) são comparados como
  conjunto (ordem irrelevante); nomes de município ignoram acento/caixa.
- ``cnae_query`` é comparado normalizado (sem acento, minúsculo, espaços colapsados).
- ``cnae_codes`` e ``municipio_ids`` são resolvidos pelo pipeline (não pelo LLM):
  nunca contam como campo extra nem são comparados.
- recall@k de CNAE = 1 se QUALQUER código aceitável aparece no top-k (o objetivo
  do mapeamento é achar um código certo, não todos).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from quimera.filters import ExtractionResult, LeadFilters
from quimera.text import strip_accents

# Resolvidos pelo pipeline, nunca pelo LLM.
EXCLUDED_KEYS = frozenset({"cnae_codes", "municipio_ids"})

# Informacional: comparado quando o expect o inclui, mas nunca conta como campo
# extra (a qualidade do cnae_query é medida pelo eval de CNAE, ponta a ponta).
INFORMATIONAL_KEYS = frozenset({"cnae_query"})

FLOAT_TOLERANCE = 0.01


def _normalize_scalar(field: str, value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = " ".join(strip_accents(value).lower().split())
        return text
    return value


def _normalize_value(field: str, value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return sorted(_normalize_scalar(field, item) for item in value)
    return _normalize_scalar(field, value)


def field_matches(field: str, expected: Any, extracted: Any) -> bool:
    exp = _normalize_value(field, expected)
    got = _normalize_value(field, extracted)
    if isinstance(exp, float) or isinstance(got, float):
        try:
            return abs(float(exp) - float(got)) <= FLOAT_TOLERANCE
        except (TypeError, ValueError):
            return False
    return exp == got


def _non_default_fields(filters: LeadFilters) -> set[str]:
    defaults = LeadFilters().model_dump()
    current = filters.model_dump()
    return {
        key
        for key, value in current.items()
        if value != defaults[key] and key not in EXCLUDED_KEYS
    }


def compare_extraction(
    case: Mapping[str, Any],
    result: ExtractionResult,
) -> dict[str, Any]:
    """Compara um caso do golden set com a extração obtida."""
    expect = case["expect"]
    if expect.get("refused"):
        return {
            "id": case["id"],
            "refusal_expected": True,
            "refused_correctly": result.refused,
            "false_refusal": False,
            "field_results": {},
            "extra_fields": [],
            "exact_match": result.refused,
        }

    if result.refused:
        return {
            "id": case["id"],
            "refusal_expected": False,
            "refused_correctly": None,
            "false_refusal": True,
            "field_results": {
                k: False for k in expect.get("filters", {}) if k not in EXCLUDED_KEYS
            },
            "extra_fields": [],
            "exact_match": False,
        }

    expected_filters = expect.get("filters", {})
    field_results = {
        field: field_matches(field, value, getattr(result.filters, field, None))
        for field, value in expected_filters.items()
        if field not in EXCLUDED_KEYS
    }
    extra = sorted(
        _non_default_fields(result.filters) - set(expected_filters) - INFORMATIONAL_KEYS
    )
    return {
        "id": case["id"],
        "refusal_expected": False,
        "refused_correctly": None,
        "false_refusal": False,
        "field_results": field_results,
        "extra_fields": extra,
        "exact_match": all(field_results.values()) and not extra,
    }


def extraction_metrics(
    cases: Sequence[Mapping[str, Any]],
    results: Sequence[ExtractionResult],
) -> dict[str, Any]:
    """Agrega acerto por campo, acerto exato e taxas de recusa."""
    if len(cases) != len(results):
        raise ValueError("cases e results precisam ter o mesmo comprimento")

    outcomes = [compare_extraction(c, r) for c, r in zip(cases, results)]

    refusal = [o for o in outcomes if o["refusal_expected"]]
    non_refusal = [o for o in outcomes if not o["refusal_expected"]]

    field_hits: dict[str, int] = {}
    field_totals: dict[str, int] = {}
    for outcome in outcomes:
        for field, ok in outcome["field_results"].items():
            field_totals[field] = field_totals.get(field, 0) + 1
            if ok:
                field_hits[field] = field_hits.get(field, 0) + 1
    field_accuracy = {
        field: {
            "hits": field_hits.get(field, 0),
            "total": total,
            "rate": field_hits.get(field, 0) / total,
        }
        for field, total in field_totals.items()
    }
    total_fields = sum(field_totals.values())
    total_hits = sum(field_hits.values())

    return {
        "n_cases": len(outcomes),
        "n_refusal_cases": len(refusal),
        "correct_refusal_rate": (
            sum(1 for o in refusal if o["refused_correctly"]) / len(refusal)
            if refusal
            else None
        ),
        "false_refusal_rate": (
            sum(1 for o in non_refusal if o["false_refusal"]) / len(non_refusal)
            if non_refusal
            else None
        ),
        "field_accuracy": field_accuracy,
        "overall_field_accuracy": (total_hits / total_fields) if total_fields else None,
        "exact_match_rate": (
            sum(1 for o in outcomes if o["exact_match"]) / len(outcomes)
            if outcomes
            else None
        ),
        "per_case": outcomes,
    }


def recall_at_k(ranked: Sequence[str], acceptable: Iterable[str], k: int) -> float:
    """1.0 se qualquer código aceitável aparece no top-k."""
    top = set(ranked[:k])
    return 1.0 if top & set(acceptable) else 0.0


def reciprocal_rank(ranked: Sequence[str], acceptable: Iterable[str]) -> float:
    """1/rank do primeiro código aceitável (0 se nenhum)."""
    acceptable = set(acceptable)
    for rank, code in enumerate(ranked, start=1):
        if code in acceptable:
            return 1.0 / rank
    return 0.0


def cnae_metrics(
    cases: Sequence[Mapping[str, Any]],
    ranked_lists: Sequence[Sequence[str]],
    k_values: tuple[int, ...] = (1, 5),
) -> dict[str, Any]:
    """Agrega recall@k e MRR do mapeamento linguagem natural -> CNAE."""
    if len(cases) != len(ranked_lists):
        raise ValueError("cases e ranked_lists precisam ter o mesmo comprimento")

    metrics: dict[str, Any] = {"n_cases": len(cases)}
    for k in k_values:
        hits = sum(
            recall_at_k(ranked, case["acceptable"], k)
            for case, ranked in zip(cases, ranked_lists)
        )
        metrics[f"recall@{k}"] = hits / len(cases) if cases else None
    mrr = sum(
        reciprocal_rank(ranked, case["acceptable"])
        for case, ranked in zip(cases, ranked_lists)
    )
    metrics["mrr"] = mrr / len(cases) if cases else None
    metrics["per_case"] = [
        {"id": case["id"], "ranked": list(ranked)}
        for case, ranked in zip(cases, ranked_lists)
    ]
    return metrics


def percentile(values: Sequence[float], p: int) -> float | None:
    """Percentil por nearest-rank; None para sequência vazia."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * p // 100))  # ceil(n*p/100), mínimo 1
    return ordered[rank - 1]
