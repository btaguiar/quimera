"""Score transparente de leads contra um ICP configurável.

Regras simples e explicáveis: cada ponto vem com um motivo legível em pt-BR.
Idade e capital pontuam em faixa: sobem do mínimo até o pleno (idade) ou o
teto (capital), e o capital volta a cair acima do teto — empresa grande demais
não é o cliente ideal. MEI tem peso reduzido (fator multiplicativo).
``query._icp_ranking`` repete a mesma conta em SQL para a ordem bater.
"""

from __future__ import annotations

import math
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
    target_full_age_years: int = 10  # idade com nota plena
    target_min_capital: float = 50_000.0
    target_max_capital: float = 10_000_000.0  # acima disso a nota cai
    capital_decay_decades: float = 2.0  # zera em 100x o teto
    mei_factor: float = 0.5  # peso reduzido para MEI
    w_porte: float = 40.0
    w_age: float = 30.0
    w_capital: float = 30.0
    porte_partial_factor: float = 0.4  # porte presente mas fora do alvo
    # Sinais do próprio cadastro (Onda 1): peso 0 por padrão mantém o score e
    # o ranking atuais; os motivos informam o dado mesmo sem peso.
    w_rede: float = 0.0
    w_dominio: float = 0.0
    target_min_estabelecimentos: int = 2

    def __post_init__(self) -> None:
        if self.capital_decay_decades <= 0:
            raise ValueError("capital_decay_decades precisa ser > 0")
        if self.target_min_capital <= 0:
            raise ValueError("target_min_capital precisa ser > 0")

    @property
    def age_span(self) -> int:
        """Anos entre a idade mínima e a plena (0 = nota plena já no mínimo)."""
        return max(self.target_full_age_years - self.target_min_age_years, 0)

    @property
    def capital_log_span(self) -> float:
        """Décadas entre o capital mínimo e o teto (0 = nota plena já no mínimo)."""
        if self.target_max_capital <= self.target_min_capital:
            return 0.0
        return math.log10(self.target_max_capital / self.target_min_capital)


def _reais(valor: float) -> str:
    return "R$ " + f"{valor:,.0f}".replace(",", ".")


def age_fraction(idade: int | None, icp: ICPConfig) -> float:
    """0 abaixo do mínimo; de 0,5 no mínimo a 1 na idade plena."""
    if idade is None or idade < icp.target_min_age_years:
        return 0.0
    if icp.age_span == 0:
        return 1.0
    return 0.5 + 0.5 * min(1.0, (idade - icp.target_min_age_years) / icp.age_span)


def capital_fraction(capital: float, icp: ICPConfig) -> float:
    """0 abaixo do mínimo; de 0,5 no mínimo a 1 no teto (escala log); cai a 0
    em ``capital_decay_decades`` décadas acima do teto. Capital já informado."""
    if capital < icp.target_min_capital:
        return 0.0
    if capital <= icp.target_max_capital:
        if icp.capital_log_span == 0:
            return 1.0
        subida = math.log10(capital / icp.target_min_capital) / icp.capital_log_span
        return 0.5 + 0.5 * subida
    excesso = math.log10(capital / icp.target_max_capital) / icp.capital_decay_decades
    return max(0.0, 1.0 - excesso)


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
    if idade is not None:
        score += icp.w_age * age_fraction(idade, icp)
        if idade < icp.target_min_age_years:
            motivos.append(
                f"ativa há {idade} anos, abaixo do mínimo do ICP "
                f"({icp.target_min_age_years} anos)"
            )
        elif idade >= icp.target_full_age_years:
            motivos.append(f"ativa há {idade} anos, maturidade plena para o ICP")
        else:
            motivos.append(
                f"ativa há {idade} anos, na faixa do ICP "
                f"(nota plena a partir de {icp.target_full_age_years})"
            )

    capital = lead.get("capital_social")
    if capital is not None:
        capital = float(capital)
        if capital <= 0 or capital >= CAPITAL_SENTINELA:
            motivos.append("capital social não informado no cadastro")
        else:
            score += icp.w_capital * capital_fraction(capital, icp)
            if capital < icp.target_min_capital:
                motivos.append(
                    f"capital social de {_reais(capital)} abaixo do mínimo do ICP "
                    f"({_reais(icp.target_min_capital)})"
                )
            elif capital <= icp.target_max_capital:
                motivos.append(
                    f"capital social de {_reais(capital)} na faixa do ICP "
                    f"({_reais(icp.target_min_capital)} a {_reais(icp.target_max_capital)})"
                )
            else:
                motivos.append(
                    f"capital social de {_reais(capital)} acima do teto do ICP "
                    f"({_reais(icp.target_max_capital)}): grande demais, nota reduzida"
                )

    n_estabelecimentos = lead.get("n_estabelecimentos")
    if n_estabelecimentos is not None:
        n_estabelecimentos = int(n_estabelecimentos)
        # O motivo informa o fato (2+ unidades já é rede); os pontos seguem o
        # target do ICP, como no _icp_ranking do query.py.
        if n_estabelecimentos >= 2:
            motivos.append(f"rede com {n_estabelecimentos} estabelecimentos ativos")
        if n_estabelecimentos >= icp.target_min_estabelecimentos:
            score += icp.w_rede

    if lead.get("dominio_proprio"):
        score += icp.w_dominio
        motivos.append("e-mail em domínio próprio")

    # Regime informa, não pontua (não há w_regime): "fora do Simples" não
    # afirma faturamento — há empresas fora por escolha ou atividade vedada.
    regime = str(lead.get("regime_tributario") or "").strip().lower()
    if regime == "fora_simples":
        motivos.append("fora do Simples Nacional")
    elif regime == "simples":
        motivos.append("optante do Simples Nacional")

    if _is_mei(lead):
        score *= icp.mei_factor
        motivos.append("MEI tem peso reduzido no ICP")

    if not motivos:
        motivos.append("sem sinais do ICP identificados nos dados disponíveis")

    return round(min(max(score, 0.0), 100.0), 1), motivos
