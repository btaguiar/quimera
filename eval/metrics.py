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

from datetime import date
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


# ---------------------------------------------------------------------------
# Ponta a ponta: critérios verificados em CADA empresa devolvida
# ---------------------------------------------------------------------------

# Critérios de linha do golden_e2e e a checagem de cada um.
E2E_ROW_CHECKS = (
    "uf",
    "municipio",
    "cnae",
    "min_age_years",
    "max_age_years",
    "min_capital",
    "portes",
)
# Público: natureza jurídica proibida (pessoa física 4xxx, empresário individual).
PUBLIC_FORBIDDEN_NATUREZA_PREFIX = "4"
PUBLIC_FORBIDDEN_NATUREZA = "2135"


def _digits(code: Any) -> str:
    return "".join(ch for ch in str(code or "") if ch.isdigit())


def _full_years(start: Any, today: date) -> int | None:
    if isinstance(start, str):
        try:
            start = date.fromisoformat(start[:10])
        except ValueError:
            return None
    if not isinstance(start, date):
        return None
    years = today.year - start.year
    if (today.month, today.day) < (start.month, start.day):
        years -= 1
    return years


def e2e_row_checks(
    row: Mapping[str, Any], expect: Mapping[str, Any], today: date
) -> dict[str, bool]:
    """Resultado de cada critério do caso para uma linha devolvida."""
    checks: dict[str, bool] = {}
    if "uf" in expect:
        checks["uf"] = row.get("sigla_uf") in expect["uf"]
    if "municipio" in expect:
        wanted = {_norm_name(m) for m in expect["municipio"]}
        checks["municipio"] = _norm_name(row.get("municipio") or "") in wanted
    if "cnae" in expect:
        wanted = {_digits(c) for c in expect["cnae"]}
        checks["cnae"] = _digits(row.get("cnae_fiscal_principal")) in wanted
    age = _full_years(row.get("data_inicio_atividade"), today)
    if "min_age_years" in expect:
        checks["min_age_years"] = age is not None and age >= expect["min_age_years"]
    if "max_age_years" in expect:
        checks["max_age_years"] = age is not None and age <= expect["max_age_years"]
    if "min_capital" in expect:
        capital = row.get("capital_social")
        checks["min_capital"] = capital is not None and capital >= expect["min_capital"]
    if "portes" in expect:
        checks["portes"] = row.get("porte") in expect["portes"]
    return checks


def _norm_name(value: str) -> str:
    return " ".join(strip_accents(value).lower().split())


def e2e_invariant_violations(result: Mapping[str, Any]) -> list[str]:
    """Regras que valem para todo resultado público, com ou sem golden."""
    rows = result.get("rows") or []
    violations = []
    basicos = [r.get("cnpj_basico") for r in rows]
    if len(basicos) != len(set(basicos)):
        violations.append("empresa repetida (mais de um estabelecimento)")
    if result.get("policy") == "public":
        for r in rows:
            natureza = str(r.get("natureza_juridica") or "")
            if natureza.startswith(PUBLIC_FORBIDDEN_NATUREZA_PREFIX) or (
                natureza == PUBLIC_FORBIDDEN_NATUREZA
            ):
                violations.append(f"natureza {natureza} no público ({r.get('cnpj')})")
            if "correio_eletronico" in r or "telefone" in r:
                violations.append(f"contato no público ({r.get('cnpj')})")
    scores = [r.get("score") for r in rows]
    if any(
        a is not None and b is not None and a < b for a, b in zip(scores, scores[1:])
    ):
        violations.append("ranking fora de ordem de score")
    return violations


def e2e_case_outcome(
    case: Mapping[str, Any], result: Mapping[str, Any], today: date
) -> dict[str, Any]:
    """Avalia um caso: expectativas do caso + critérios por linha + invariantes."""
    expect = case["expect"]
    problems: list[str] = []
    refused = bool(result.get("refused"))
    if refused != bool(expect.get("refused", False)):
        problems.append("recusou" if refused else "deveria recusar")
    rows = result.get("rows") or []
    if not refused and not expect.get("refused"):
        if expect.get("empty") and rows:
            problems.append(f"deveria vir vazio ({len(rows)} linhas)")
        if not expect.get("empty") and not rows:
            problems.append("veio vazio")
    if "warning" in expect and not any(
        expect["warning"] in w for w in result.get("warnings") or []
    ):
        problems.append(f"sem aviso '{expect['warning']}'")

    per_check = {name: [0, 0] for name in E2E_ROW_CHECKS}  # [ok, total]
    rows_ok = 0
    for row in rows:
        checks = e2e_row_checks(row, expect, today)
        for name, ok in checks.items():
            per_check[name][0] += ok
            per_check[name][1] += 1
        rows_ok += all(checks.values())
    if rows and rows_ok < len(rows):
        failing = sorted(n for n, (ok, tot) in per_check.items() if tot and ok < tot)
        problems.append(f"{len(rows) - rows_ok}/{len(rows)} linhas falham {failing}")
    problems += e2e_invariant_violations(result)
    return {
        "id": case["id"],
        "passed": not problems,
        "problems": problems,
        "n_rows": len(rows),
        "rows_ok": rows_ok,
        "per_check": per_check,
    }


def e2e_metrics(
    cases: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
    today: date | None = None,
) -> dict[str, Any]:
    """Casos 100% corretos, precisão por linha (total e por critério), recusas."""
    if len(cases) != len(results):
        raise ValueError("cases e results precisam ter o mesmo comprimento")
    today = today or date.today()
    outcomes = [e2e_case_outcome(c, r, today) for c, r in zip(cases, results)]
    n_rows = sum(o["n_rows"] for o in outcomes)
    per_check: dict[str, float | None] = {}
    for name in E2E_ROW_CHECKS:
        ok = sum(o["per_check"][name][0] for o in outcomes)
        tot = sum(o["per_check"][name][1] for o in outcomes)
        per_check[name] = ok / tot if tot else None
    refusal_cases = [
        (c, r) for c, r in zip(cases, results) if c["expect"].get("refused")
    ]
    return {
        "n_cases": len(cases),
        "case_pass_rate": sum(o["passed"] for o in outcomes) / len(cases)
        if cases
        else None,
        "row_precision": sum(o["rows_ok"] for o in outcomes) / n_rows
        if n_rows
        else None,
        "row_precision_by_check": per_check,
        "e2e_correct_refusal_rate": sum(
            bool(r.get("refused")) for _, r in refusal_cases
        )
        / len(refusal_cases)
        if refusal_cases
        else None,
        "n_rows": n_rows,
        "per_case": outcomes,
    }
