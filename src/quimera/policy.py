"""Políticas de deploy — ponto único que diferencia público de privado.

Regra inegociável: nenhum outro módulo decide o que é permitido em cada
deploy. ``apply_policy`` roda DEPOIS do LLM e força os limites da policy,
mesmo que a extração tenha pedido o contrário.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .filters import LeadFilters


@dataclass(frozen=True)
class Policy:
    name: str
    allow_mei: bool
    # Natureza jurídica 4xxx (pessoa física: produtor rural, candidato etc.).
    allow_pessoa_fisica: bool = False
    contact_fields: tuple[str, ...] = field(default=())
    max_rows: int = 50


# Deploy público (portfólio): sem MEI, sem pessoa física, sem qualquer campo
# de contato/pessoa.
PUBLIC = Policy(
    name="public",
    allow_mei=False,
    allow_pessoa_fisica=False,
    contact_fields=(),
    max_rows=50,
)

# Deploy privado (Turno 24): MEI conforme filtros e contato do estabelecimento.
PRIVATE = Policy(
    name="private",
    allow_mei=True,
    allow_pessoa_fisica=True,
    contact_fields=("correio_eletronico", "telefone"),
    max_rows=1000,
)


def apply_policy(filters: LeadFilters, policy: Policy) -> LeadFilters:
    """Força os limites da policy sobre os filtros vindos do LLM."""
    updates: dict[str, object] = {"limit": min(filters.limit, policy.max_rows)}
    if not policy.allow_mei and filters.include_mei:
        updates["include_mei"] = False
    if not policy.allow_mei:
        updates["regimes"] = [r for r in filters.regimes if r != "mei"]
    return filters.model_copy(update=updates)


def resolve_policy() -> Policy:
    """Lê DEPLOY_MODE: vazio = público; "private" = privado (só na Turno 24)."""
    mode = os.environ.get("DEPLOY_MODE", "").strip().lower()
    if mode == "private":
        return PRIVATE
    return PUBLIC
