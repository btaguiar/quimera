"""ICP escolhido pelo visitante da demo (corpo de POST /leads).

Os valores viram parâmetros do ranking no SQL (``query._icp_ranking``),
nunca texto da consulta. Os pesos são relativos: ``to_config`` normaliza
para somar 100, porque o SQL não corta a nota em 100 como o Python.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..score import ICPConfig

PORTES_ICP = ("micro", "pequena", "demais")
ICP_WEIGHTS = ("w_porte", "w_age", "w_capital", "w_rede", "w_dominio")


class IcpBody(BaseModel):
    """Perfil inteiro, sem mescla parcial: o front sempre manda todos os campos."""

    model_config = ConfigDict(extra="forbid")

    preferred_portes: list[str] = Field(min_length=1, max_length=3)
    target_min_age_years: int = Field(ge=0, le=50)
    target_full_age_years: int = Field(ge=0, le=60)
    target_min_capital: float = Field(ge=1_000, le=1_000_000_000)
    target_max_capital: float = Field(ge=1_000, le=10_000_000_000)
    w_porte: float = Field(ge=0, le=100)
    w_age: float = Field(ge=0, le=100)
    w_capital: float = Field(ge=0, le=100)
    w_rede: float = Field(ge=0, le=100)
    w_dominio: float = Field(ge=0, le=100)
    target_min_estabelecimentos: int = Field(ge=2, le=100)
    mei_factor: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _coerente(self) -> "IcpBody":
        portes = self.preferred_portes
        if len(set(portes)) != len(portes) or not set(portes) <= set(PORTES_ICP):
            raise ValueError(
                f"preferred_portes: valores distintos entre {', '.join(PORTES_ICP)}"
            )
        if self.target_full_age_years < self.target_min_age_years:
            raise ValueError("target_full_age_years abaixo de target_min_age_years")
        if self.target_max_capital < self.target_min_capital:
            raise ValueError("target_max_capital abaixo de target_min_capital")
        if sum(getattr(self, w) for w in ICP_WEIGHTS) <= 0:
            raise ValueError("a soma dos pesos precisa ser maior que zero")
        return self

    def to_config(self) -> ICPConfig:
        total = sum(getattr(self, w) for w in ICP_WEIGHTS)
        pesos = {w: round(getattr(self, w) * 100 / total, 4) for w in ICP_WEIGHTS}
        return ICPConfig(
            preferred_portes=tuple(self.preferred_portes),
            target_min_age_years=self.target_min_age_years,
            target_full_age_years=self.target_full_age_years,
            target_min_capital=self.target_min_capital,
            target_max_capital=self.target_max_capital,
            target_min_estabelecimentos=self.target_min_estabelecimentos,
            mei_factor=self.mei_factor,
            **pesos,
        )


def icp_payload(icp: ICPConfig) -> dict:
    """ICP efetivamente usado, no formato do corpo (resposta e chave de cache)."""
    return {
        "preferred_portes": list(icp.preferred_portes),
        "target_min_age_years": icp.target_min_age_years,
        "target_full_age_years": icp.target_full_age_years,
        "target_min_capital": icp.target_min_capital,
        "target_max_capital": icp.target_max_capital,
        **{w: getattr(icp, w) for w in ICP_WEIGHTS},
        "target_min_estabelecimentos": icp.target_min_estabelecimentos,
        "mei_factor": icp.mei_factor,
    }


def icp_cache_suffix(icp: ICPConfig) -> str:
    """Sufixo da chave de cache: vazio no ICP padrão (as chaves de antes do
    ICP escolhido continuam valendo), JSON canônico nos outros."""
    if icp == ICPConfig():
        return ""
    return "\n" + json.dumps(icp_payload(icp), sort_keys=True, separators=(",", ":"))
