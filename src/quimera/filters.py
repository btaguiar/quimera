"""Schemas de filtros de leads e do resultado de extração.

Regra inegociável: o LLM nunca escreve SQL — ele só preenche ``LeadFilters``.
A query é montada por ``query.py`` a partir destes campos validados.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .text import strip_accents

VALID_UFS = frozenset(
    {
        "AC",
        "AL",
        "AM",
        "AP",
        "BA",
        "CE",
        "DF",
        "ES",
        "GO",
        "MA",
        "MG",
        "MS",
        "MT",
        "PA",
        "PB",
        "PE",
        "PI",
        "PR",
        "RJ",
        "RN",
        "RO",
        "RR",
        "RS",
        "SC",
        "SE",
        "SP",
        "TO",
    }
)

VALID_PORTES = frozenset({"micro", "pequena", "media", "grande"})


class LeadFilters(BaseModel):
    """Filtros estruturados que o LLM preenche (saída estruturada do Gemini).

    ``municipio_names`` recebe nomes de municípios em linguagem natural;
    os códigos IBGE (``municipio_ids``) são resolvidos por lookup em tabela
    de diretório no pipeline — nunca confiamos em código inventado pelo LLM.
    """

    model_config = ConfigDict(extra="forbid")

    cnae_query: str | None = None
    cnae_codes: list[str] = Field(default_factory=list)
    ufs: list[str] = Field(default_factory=list)
    municipio_ids: list[str] = Field(default_factory=list)
    municipio_names: list[str] = Field(default_factory=list)
    min_age_years: int | None = Field(default=None, ge=0)
    max_age_years: int | None = Field(default=None, ge=0)
    min_capital: float | None = Field(default=None, ge=0)
    portes: list[str] = Field(default_factory=list)
    include_mei: bool = False
    # ge=1 (e não gt=0): o schema do Vertex não aceita exclusiveMinimum.
    limit: int = Field(default=50, ge=1)

    @field_validator("ufs", mode="before")
    @classmethod
    def _normalize_ufs(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return [str(uf).strip().upper() for uf in value]
        return value

    @field_validator("ufs")
    @classmethod
    def _validate_ufs(cls, value: list[str]) -> list[str]:
        invalid = [uf for uf in value if uf not in VALID_UFS]
        if invalid:
            raise ValueError(
                f"UF inválida: {invalid}. Use siglas válidas (ex.: SP, RJ)."
            )
        return value

    @field_validator("portes", mode="before")
    @classmethod
    def _normalize_portes(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            # 'Média' -> 'media': rótulos canônicos são sem acento.
            return [strip_accents(str(p).strip().lower()) for p in value]
        return value

    @field_validator("portes")
    @classmethod
    def _validate_portes(cls, value: list[str]) -> list[str]:
        invalid = [p for p in value if p not in VALID_PORTES]
        if invalid:
            raise ValueError(
                f"Porte inválido: {invalid}. Valores permitidos: {sorted(VALID_PORTES)}."
            )
        return value

    @model_validator(mode="after")
    def _validate_age_range(self) -> "LeadFilters":
        if (
            self.min_age_years is not None
            and self.max_age_years is not None
            and self.min_age_years > self.max_age_years
        ):
            raise ValueError(
                "Faixa de idade invertida: min_age_years não pode ser maior que max_age_years."
            )
        return self


class ExtractionResult(BaseModel):
    """Contrato da extração: ou recusa com motivo, ou filtros válidos."""

    model_config = ConfigDict(extra="forbid")

    refused: bool = False
    refusal_reason: str | None = None
    filters: LeadFilters | None = None

    @model_validator(mode="after")
    def _validate_consistency(self) -> "ExtractionResult":
        if self.refused:
            if not self.refusal_reason:
                raise ValueError("Recusa exige refusal_reason explicando o motivo.")
            if self.filters is not None:
                raise ValueError("Resultado recusado não pode carregar filtros.")
        else:
            if self.filters is None:
                raise ValueError("Resultado não recusado exige filters preenchidos.")
        return self
