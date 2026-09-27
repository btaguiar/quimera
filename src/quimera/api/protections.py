"""Proteções da API pública: token, rate limit, orçamento e cache.

Funções puras testáveis sem FastAPI; o estado (contadores, janelas,
cache) vive em ``state.py``. Configuração vem do ambiente, com defaults
pensados para o deploy público (escala a zero, custo controlado).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

GIB = 1024**3


def normalize_request(text: str) -> str:
    """Mesma normalização do pipeline: colapsa espaços em branco."""
    return " ".join(text.split())


def request_hash(normalized: str) -> str:
    """Chave de cache: SHA-256 hexdigest do pedido normalizado."""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def token_ok(provided: str | None, expected: str | None) -> bool:
    """Checa o token do header com comparação de tempo constante.

    ``expected`` vazio/nulo desabilita o check (modo dev); no deploy o
    Secret Manager define ``API_TOKEN``.
    """
    if not expected:
        return True
    if provided is None:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())


@dataclass(frozen=True)
class ApiConfig:
    """Parâmetros das proteções, lidos do ambiente em ``from_env``."""

    api_token: str | None
    rate_limit_max: int
    rate_limit_window_s: int
    cache_ttl_s: int
    daily_bytes_budget: int
    request_timeout_s: float
    turnstile_secret_key: str | None = None
    turnstile_site_key: str | None = None

    @classmethod
    def from_env(cls) -> "ApiConfig":
        return cls(
            api_token=os.environ.get("API_TOKEN") or None,
            rate_limit_max=int(os.environ.get("RATE_LIMIT_MAX", "10")),
            rate_limit_window_s=int(os.environ.get("RATE_LIMIT_WINDOW_S", "3600")),
            cache_ttl_s=int(os.environ.get("CACHE_TTL_S", "86400")),
            daily_bytes_budget=int(os.environ.get("DAILY_BYTES_BUDGET", str(10 * GIB))),
            request_timeout_s=float(os.environ.get("REQUEST_TIMEOUT_S", "60")),
            turnstile_secret_key=os.environ.get("TURNSTILE_SECRET_KEY") or None,
            turnstile_site_key=os.environ.get("TURNSTILE_SITE_KEY") or None,
        )
