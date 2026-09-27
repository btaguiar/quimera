"""Verificação server-side do Cloudflare Turnstile para o front público.

O widget roda no navegador e entrega um token single-use; o servidor confere
o token no siteverify da Cloudflare antes de liberar o pedido. Falha de rede
conta como falha: melhor recusar (fail closed) do que deixar passar sem
verificação. O cliente HTTP é injetável para testes sem rede.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("quimera.api.turnstile")

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TIMEOUT_S = 5.0


def verify(
    response: str | None,
    secret: str,
    remote_ip: str | None = None,
    *,
    client: Any | None = None,
) -> bool:
    """Confere um token do Turnstile no siteverify; ``False`` em qualquer falha."""
    if not response:
        return False
    data = {"secret": secret, "response": response}
    if remote_ip:
        data["remoteip"] = remote_ip
    own_client = client is None
    try:
        if client is None:
            import httpx

            client = httpx.Client(timeout=TIMEOUT_S)
        payload = client.post(SITEVERIFY_URL, data=data).json()
    except Exception as exc:
        logger.warning(
            "siteverify do Turnstile falhou (%s); recusando por fail closed",
            type(exc).__name__,
        )
        return False
    finally:
        if own_client and client is not None:
            client.close()
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("success"))
