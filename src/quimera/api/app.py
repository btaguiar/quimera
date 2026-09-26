"""App FastAPI da demo pública: POST /leads, GET /health, GET /metrics.

A app é uma casca fina sobre ``quimera.pipeline.run`` com as proteções
da spec da Fase 3: token, rate limit por IP, orçamento diário de bytes
com modo cache e timeout por request. Tudo injetável para testes sem
GCP (mesmos fakes dos testes do pipeline).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..policy import Policy, resolve_policy
from .metrics import load_metrics
from .protections import ApiConfig, normalize_request, request_hash
from .state import MemoryStateStore, StateStore

logger = logging.getLogger("quimera.api")

MAX_REQUEST_CHARS = 500


class LeadsRequestBody(BaseModel):
    request: str = Field(min_length=1, max_length=MAX_REQUEST_CHARS)


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

    @app.post("/leads")
    def leads(body: LeadsRequestBody, request: Request):
        key = request_hash(normalize_request(body.request))
        cached = state.cache_get(key)
        if cached is not None:
            return {**cached, "cached": True, "cache_mode": state.cache_mode()}

        result = _run_pipeline(body.request)
        payload = result.to_dict()
        if not result.refused:
            state.add_bytes(result.bytes_billed)
            state.cache_set(key, payload)
        return {**payload, "cached": False, "cache_mode": state.cache_mode()}

    return app
