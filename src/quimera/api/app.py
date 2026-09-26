"""App FastAPI da demo pública: POST /leads, GET /health, GET /metrics.

A app é uma casca fina sobre ``quimera.pipeline.run`` com as proteções
da spec da Fase 3: token, rate limit por IP, orçamento diário de bytes
com modo cache e timeout por request. Tudo injetável para testes sem
GCP (mesmos fakes dos testes do pipeline).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..policy import Policy, resolve_policy
from .metrics import load_metrics
from .protections import ApiConfig, normalize_request, request_hash, token_ok
from .state import MemoryStateStore, StateStore

logger = logging.getLogger("quimera.api")

MAX_REQUEST_CHARS = 500


class LeadsRequestBody(BaseModel):
    request: str = Field(min_length=1, max_length=MAX_REQUEST_CHARS)


class ApiError(Exception):
    """Erro da API com envelope uniforme {"error", "reason"}."""

    def __init__(
        self,
        status_code: int,
        error: str,
        reason: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(reason)
        self.status_code = status_code
        self.error = error
        self.reason = reason
        self.headers = headers


def create_app(
    *,
    config: ApiConfig | None = None,
    state: StateStore | None = None,
    policy: Policy | None = None,
    extract_client: Any | None = None,
    cnae_search: Any | None = None,
    bq_client: Any | None = None,
) -> FastAPI:
    config = config or ApiConfig.from_env()
    state = state or MemoryStateStore(config)
    policy = policy or resolve_policy()

    app = FastAPI(title="Quimera", version=__version__)
    app.state.config = config
    app.state.store = state
    app.state.policy = policy
    app.state.pipeline_deps = {
        "extract_client": extract_client,
        "cnae_search": cnae_search,
        "bq_client": bq_client,
    }

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": "validação",
                "reason": (
                    f"campo 'request' é obrigatório, não vazio e com até "
                    f"{MAX_REQUEST_CHARS} caracteres"
                ),
            },
        )

    @app.exception_handler(ApiError)
    async def _api_error_handler(request: Request, exc: ApiError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.error, "reason": exc.reason},
            headers=exc.headers,
        )

    async def _require_token(x_api_token: str | None = Header(default=None)):
        if not token_ok(x_api_token, config.api_token):
            raise ApiError(
                401, "unauthorized", "token ausente ou inválido (X-Api-Token)"
            )

    def _client_ip(request: Request) -> str:
        """IP do cliente: último hop do X-Forwarded-For (o Cloud Run anexa o
        IP real observado; hops anteriores são controláveis pelo cliente).
        Sem XFF, o endereço direto."""
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            if parts:
                return parts[-1]
        return request.client.host if request.client else "unknown"

    async def _enforce_rate_limit(request: Request):
        ip = _client_ip(request)
        if not state.allow_request(ip):
            raise ApiError(
                429,
                "rate limit",
                f"limite de {config.rate_limit_max} requisições por "
                f"{config.rate_limit_window_s}s por IP",
                headers={"Retry-After": str(state.retry_after(ip))},
            )

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "version": __version__,
            "cache_mode": state.cache_mode(),
            "budget_remaining_bytes": state.budget_remaining(),
        }

    @app.get("/metrics")
    def metrics():
        return load_metrics()

    def _run_pipeline(text: str):
        from ..pipeline import run as run_pipeline

        return run_pipeline(
            text,
            policy,
            extract_client=app.state.pipeline_deps["extract_client"],
            cnae_search=app.state.pipeline_deps["cnae_search"],
            bq_client=app.state.pipeline_deps["bq_client"],
        )

    @app.post(
        "/leads",
        dependencies=[Depends(_require_token), Depends(_enforce_rate_limit)],
    )
    def leads(body: LeadsRequestBody, request: Request):
        key = request_hash(normalize_request(body.request))
        cached = state.cache_get(key)
        if cached is not None:
            return {**cached, "cached": True, "cache_mode": state.cache_mode()}

        if state.cache_mode():
            raise ApiError(
                503,
                "cache mode",
                "orçamento diário esgotado; apenas pedidos já vistos são respondidos",
            )

        result = _run_pipeline(body.request)
        payload = result.to_dict()
        if not result.refused:
            state.add_bytes(result.bytes_billed)
            state.cache_set(key, payload)
        return {**payload, "cached": False, "cache_mode": state.cache_mode()}

    return app
