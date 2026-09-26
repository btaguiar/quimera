"""Score transparente de leads contra um ICP configurável.

Regras simples e explicáveis: cada ponto vem com um motivo legível em pt-BR.
MEI tem peso reduzido (fator multiplicativo configurável).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Any

from .text import strip_accents

MEI_TRUTHY = {"s", "sim", "1", "true", "y", "yes"}

# Capital social 0 (17,5 M empresas) e o sentinela 999.999.999.999 significam
# "não informado" no cadastro, não capital baixo/alto (docs/schema.md).
CAPITAL_SENTINELA = 999_999_999_999.0


@dataclass(frozen=True)
class ICPConfig:
    """Perfil de cliente ideal configurável (a Turno 24 define o dela fora do repo).

    ``preferred_portes`` usa os rótulos que o SELECT devolve: micro/pequena/demais.
    "demais" = tudo que não é micro nem pequeno porte — média e grande são
    indistinguíveis no dataset (docs/schema.md).
    """

    preferred_portes: tuple[str, ...] = ("demais",)
    target_min_age_years: int = 2
    target_min_capital: float = 50_000.0
    mei_factor: float = 0.5  # peso reduzido para MEI
    w_porte: float = 40.0
    w_age: float = 30.0
    w_capital: float = 30.0
    porte_partial_factor: float = 0.4  # porte presente mas fora do alvo


def _normalize_porte(value: Any) -> str | None:
    if value is None:
        return None
    return strip_accents(str(value).strip().lower()) or None


def _is_mei(lead: Mapping[str, Any]) -> bool:
    for key in ("is_mei", "opcao_mei"):
        value = lead.get(key)
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in MEI_TRUTHY
    return False


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            from datetime import datetime

            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _age_years(lead: Mapping[str, Any], today: date | None = None) -> int | None:
    """Idade em anos completos — mesma regra do filtro de idade da query."""
    if lead.get("idade_anos") is not None:
        return int(lead["idade_anos"])
    start = _parse_date(lead.get("data_inicio_atividade"))
    if start is None:
        return None
    today = today or date.today()
    years = today.year - start.year
    if (today.month, today.day) < (start.month, start.day):
        years -= 1
    return years


def score_lead(lead: Mapping[str, Any], icp: ICPConfig) -> tuple[float, list[str]]:
    """Pontua o lead de 0 a 100 e explica cada ponto em pt-BR."""
    score = 0.0
    motivos: list[str] = []

    porte = _normalize_porte(lead.get("porte"))
    if porte and porte in icp.preferred_portes:
        score += icp.w_porte
        motivos.append(f"porte {porte} é o alvo do ICP")
    elif porte:
        score += icp.w_porte * icp.porte_partial_factor
        motivos.append(f"porte {porte} fora do alvo do ICP (pontuação parcial)")

    idade = _age_years(lead)
    if idade is not None and idade >= icp.target_min_age_years:
        score += icp.w_age
        motivos.append(f"ativa há {idade} anos, dentro da faixa alvo do ICP")
    elif idade is not None:
        motivos.append(f"ativa há {idade} anos, abaixo da faixa alvo do ICP")

    capital = lead.get("capital_social")
    if capital is not None:
        capital = float(capital)
        if capital <= 0 or capital >= CAPITAL_SENTINELA:
            motivos.append("capital social não informado no cadastro")
        elif capital >= icp.target_min_capital:
            score += icp.w_capital
            motivos.append(f"capital social de R$ {capital:,.0f} acima do alvo do ICP")
        else:
            motivos.append(f"capital social de R$ {capital:,.0f} abaixo do alvo do ICP")

    if _is_mei(lead):
        score *= icp.mei_factor
        motivos.append("MEI tem peso reduzido no ICP")

    if not motivos:
        motivos.append("sem sinais do ICP identificados nos dados disponíveis")

    return round(min(max(score, 0.0), 100.0), 1), motivos
