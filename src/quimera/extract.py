"""Extração de filtros via Gemini com saída estruturada.

O LLM nunca escreve SQL: ele só preenche ``ExtractionResult``. O SDK do
Google é importado de forma lazy — testes injetam um cliente fake e rodam
sem o extra ``gcp`` instalado.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

from pydantic import ValidationError

from .filters import ExtractionResult
from .policy import Policy

# Validado na conta em 2026-09-26 (Vertex AI, us-central1).
DEFAULT_MODEL = "gemini-2.5-flash"


class ExtractionError(RuntimeError):
    """Resposta do LLM fora do contrato (JSON malformado ou inconsistente)."""


def build_prompt(request: str, policy: Policy) -> str:
    """Prompt em pt-BR, com regra de recusa diferente por policy."""
    lines = [
        "Você extrai filtros estruturados de um pedido de prospecção de empresas brasileiras.",
        "Responda APENAS com o JSON do schema ExtractionResult. Nunca escreva SQL.",
        "",
        "Regras:",
        "- cnae_query: descreva a atividade em linguagem natural (ex.: 'clínicas odontológicas').",
        "  Não invente códigos CNAE; o sistema resolve cnae_query para códigos por embeddings.",
        "- municipio_names: nomes de municípios como escritos pelo usuário.",
        "  Não invente códigos IBGE; o sistema resolve nomes por lookup em tabela de diretório.",
        "- ufs: siglas de estados (ex.: SP).",
        "- min_age_years/max_age_years: idade da empresa em anos, se mencionada.",
        "- min_capital: capital social mínimo em reais, se mencionado.",
        "- portes: um ou mais de 'micro', 'pequena', 'media', 'grande'.",
        "- limit: quantidade de resultados pedida (padrão 50).",
        "- Não recuse pedidos vagos, subjetivos ou incompletos: extraia apenas "
        "os filtros mapeáveis e ignore qualificadores sem filtro correspondente "
        "(ex.: 'empresas boas', 'conhecidas', 'maiores'); se nada for mapeável, "
        "devolva filters vazio. Recusa é exclusivamente para dado pessoal.",
    ]
    if policy.allow_mei:
        lines.append("- include_mei: true apenas se o usuário quiser incluir MEI.")
        lines.append(
            "- Este deployment permite e-mail e telefone do estabelecimento; "
            "ainda assim recuse pedidos de CPF, endereço de pessoa física ou dados de redes sociais."
        )
    else:
        lines.append(
            "- Este deployment é público: se o pedido solicitar dado pessoal "
            "(telefone do dono, CPF, e-mail pessoal, nome de pessoa física, redes sociais), "
            "responda refused=true com refusal_reason explicando o motivo da recusa."
        )
    lines.append("")
    lines.append(f"Pedido: {request}")
    return "\n".join(lines)


def parse_extraction_response(payload: Any) -> ExtractionResult:
    """Valida a resposta do LLM contra o contrato ExtractionResult.

    Aceita string JSON, dict, ou objeto de resposta do SDK (``.parsed``/``.text``).
    """
    data: Any
    parsed = getattr(payload, "parsed", None)
    if parsed is not None:
        data = parsed
    elif hasattr(payload, "text"):
        data = payload.text
    else:
        data = payload

    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ExtractionError(
                f"Resposta do LLM não é JSON válido: {exc.msg}"
            ) from exc

    try:
        return ExtractionResult.model_validate(data)
    except ValidationError as exc:
        raise ExtractionError(
            f"Resposta do LLM fora do contrato ExtractionResult: {exc}"
        ) from exc


@lru_cache(maxsize=1)
def _default_client() -> Any:
    """Cliente Gemini/Vertex com import lazy do SDK (extra ``gcp``).

    Um por processo: criar o cliente (credenciais + conexão) custava ~2-3 s
    por pedido na seleção de CNAE (medido em 2026-09-26).
    """
    from google import genai  # lazy import

    return genai.Client(
        vertexai=True,
        project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        location=os.environ.get("VERTEX_LOCATION"),
    )


def extract_filters(
    request: str,
    policy: Policy,
    model: str | None = None,
    client: Any | None = None,
) -> ExtractionResult:
    """Extrai filtros do pedido via Gemini (temperature=0, schema fixo)."""
    model = model or os.environ.get("EXTRACT_MODEL", DEFAULT_MODEL)
    client = client or _default_client()
    response = client.models.generate_content(
        model=model,
        contents=build_prompt(request, policy),
        config={
            "temperature": 0,
            # Sem raciocínio: ~5 s -> ver docs/schema.md (latência). O golden de
            # extração decide se isso fica (recusa correta tem de seguir 100%).
            "thinking_config": {"thinking_budget": 0},
            "response_mime_type": "application/json",
            "response_schema": ExtractionResult,
        },
    )
    return parse_extraction_response(response)
