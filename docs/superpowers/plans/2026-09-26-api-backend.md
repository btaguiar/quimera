# Backend da demo pública (Fase 3a) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** FastAPI com `POST /leads`, `GET /health` e `GET /metrics`, protegida por token, rate limit por IP, orçamento diário de bytes com modo cache e timeout — sem front e sem deploy.

**Architecture:** Pacote `quimera/api` com factory `create_app()` e injeção das mesmas dependências do pipeline (`extract_client`, `cnae_search`, `bq_client`). Proteções são funções puras (`protections.py`) + estado injetável (`StateStore`/`MemoryStateStore`); métricas vêm dos JSON em `eval/results/`. Imports de fastapi/uvicorn são lazy (regra do projeto: `pytest` roda sem o extra `[gcp]`; testes de API precisam do extra `dev`, que inclui fastapi + httpx).

**Tech Stack:** Python 3.10+, FastAPI, uvicorn, pydantic v2, pytest (+ fastapi TestClient, que exige httpx).

**Spec:** `docs/superpowers/specs/2026-09-26-api-backend-design.md`

**Convenções do repo (importantíssimo):**
- Docstrings em pt-BR em todo módulo, classe e função pública; sem comentários inline salvo necessidade real.
- Imports de dependências opcionais sempre lazy (dentro de função).
- Testes não tocam GCP/rede: injetam fakes de `tests/fakes.py` (`FakeGenaiClient`, `FakePipelineBQ`).
- `python -m pytest` roda do diretório raiz `C:\Dev\quimera`; `pyproject.toml` já tem `pythonpath = ["."]`.
- `FakeGenaiClient(json.dumps({...}))` devolve a string como resposta; `parse_extraction_response` (em `src/quimera/extract.py:65`) aceita string JSON direto.
- Commits em pt-BR, no estilo do commit inicial (`aa8404b`).

---

### Task 1: Proteções puras — `protections.py`

**Files:**
- Create: `src/quimera/api/__init__.py` (placeholder temporário; Task 4 completa)
- Create: `src/quimera/api/protections.py`
- Test: `tests/test_api_protections.py`

- [ ] **Step 1: Criar o pacote e escrever o teste de falha**

Criar `src/quimera/api/__init__.py`:

```python
"""API da demo pública (FastAPI). fastapi só é importado dentro de create_app."""
```

Criar `tests/test_api_protections.py`:

```python
"""Testes das proteções puras da API (sem FastAPI, sem estado)."""

from __future__ import annotations

from quimera.api.protections import (
    ApiConfig,
    normalize_request,
    request_hash,
    token_ok,
)

ENV_VARS = (
    "API_TOKEN",
    "RATE_LIMIT_MAX",
    "RATE_LIMIT_WINDOW_S",
    "CACHE_TTL_S",
    "DAILY_BYTES_BUDGET",
    "REQUEST_TIMEOUT_S",
)


class TestNormalizeRequest:
    def test_collapses_whitespace(self):
        assert normalize_request("  clínicas   em  \nSP ") == "clínicas em SP"

    def test_equivalent_requests_share_hash(self):
        a = request_hash(normalize_request("clínicas em SP"))
        b = request_hash(normalize_request("clínicas  em SP"))
        assert a == b
        assert request_hash("x") != request_hash("y")


class TestTokenOk:
    def test_unset_expected_disables_check(self):
        assert token_ok(None, None) is True
        assert token_ok("qualquer coisa", None) is True

    def test_missing_or_wrong_token_fails(self):
        assert token_ok(None, "segredo") is False
        assert token_ok("errado", "segredo") is False

    def test_correct_token_passes(self):
        assert token_ok("segredo", "segredo") is True


class TestApiConfigFromEnv:
    def test_defaults(self, monkeypatch):
        for var in ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        config = ApiConfig.from_env()
        assert config.api_token is None
        assert config.rate_limit_max == 10
        assert config.rate_limit_window_s == 3600
        assert config.cache_ttl_s == 86400
        assert config.daily_bytes_budget == 10 * 1024**3
        assert config.request_timeout_s == 60.0

    def test_reads_environment(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "tok")
        monkeypatch.setenv("RATE_LIMIT_MAX", "3")
        monkeypatch.setenv("DAILY_BYTES_BUDGET", "2048")
        config = ApiConfig.from_env()
        assert config.api_token == "tok"
        assert config.rate_limit_max == 3
        assert config.daily_bytes_budget == 2048

    def test_empty_api_token_means_disabled(self, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "")
        assert ApiConfig.from_env().api_token is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_api_protections.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'quimera.api'`

- [ ] **Step 3: Implementar `src/quimera/api/protections.py`**

```python
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

    @classmethod
    def from_env(cls) -> "ApiConfig":
        return cls(
            api_token=os.environ.get("API_TOKEN") or None,
            rate_limit_max=int(os.environ.get("RATE_LIMIT_MAX", "10")),
            rate_limit_window_s=int(
                os.environ.get("RATE_LIMIT_WINDOW_S", "3600")
            ),
            cache_ttl_s=int(os.environ.get("CACHE_TTL_S", "86400")),
            daily_bytes_budget=int(
                os.environ.get("DAILY_BYTES_BUDGET", str(10 * GIB))
            ),
            request_timeout_s=float(os.environ.get("REQUEST_TIMEOUT_S", "60")),
        )
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_api_protections.py -v`
Expected: PASS (10 testes)

- [ ] **Step 5: Commit**

```bash
git add src/quimera/api/__init__.py src/quimera/api/protections.py tests/test_api_protections.py
git commit -m "api: proteções puras (token, normalização/hash, config por env)"
```

---

### Task 2: Estado — `state.py` (rate limit, cache com TTL, orçamento diário)

**Files:**
- Create: `src/quimera/api/state.py`
- Test: `tests/test_api_state.py`

- [ ] **Step 1: Escrever o teste de falha**

Criar `tests/test_api_state.py`:

```python
"""Testes do MemoryStateStore: janela de rate limit, cache com TTL e orçamento."""

from __future__ import annotations

import calendar

from quimera.api.protections import ApiConfig
from quimera.api.state import MemoryStateStore


def _config(**overrides) -> ApiConfig:
    base = dict(
        api_token=None,
        rate_limit_max=2,
        rate_limit_window_s=60,
        cache_ttl_s=100,
        daily_bytes_budget=1000,
        request_timeout_s=5.0,
    )
    base.update(overrides)
    return ApiConfig(**base)


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class TestRateLimit:
    def test_allows_up_to_max_then_blocks(self):
        clock = FakeClock()
        store = MemoryStateStore(_config(), clock=clock)
        assert store.allow_request("ip1") is True
        assert store.allow_request("ip1") is True
        assert store.allow_request("ip1") is False

    def test_window_slides_and_frees_slots(self):
        clock = FakeClock()
        store = MemoryStateStore(_config(), clock=clock)
        store.allow_request("ip1")
        store.allow_request("ip1")
        clock.now += 61
        assert store.allow_request("ip1") is True

    def test_ips_are_independent(self):
        store = MemoryStateStore(_config(), clock=FakeClock())
        assert store.allow_request("ip1") is True
        assert store.allow_request("ip2") is True

    def test_retry_after_reports_seconds_to_oldest_hit(self):
        clock = FakeClock(start=100.0)
        store = MemoryStateStore(_config(), clock=clock)
        store.allow_request("ip1")
        clock.now += 10
        assert store.retry_after("ip1") > 0
        assert store.retry_after("ip1") <= 51


class TestCache:
    def test_set_and_get_roundtrip(self):
        store = MemoryStateStore(_config(), clock=FakeClock())
        store.cache_set("k", {"refused": False})
        assert store.cache_get("k") == {"refused": False}

    def test_missing_key_returns_none(self):
        store = MemoryStateStore(_config(), clock=FakeClock())
        assert store.cache_get("nada") is None

    def test_entry_expires_after_ttl(self):
        clock = FakeClock()
        store = MemoryStateStore(_config(), clock=clock)
        store.cache_set("k", {"a": 1})
        clock.now += 101
        assert store.cache_get("k") is None

    def test_expired_entry_is_evicted(self):
        clock = FakeClock()
        store = MemoryStateStore(_config(), clock=clock)
        store.cache_set("k", {"a": 1})
        clock.now += 101
        store.cache_get("k")
        assert "k" not in store._cache


class TestBudget:
    def test_bytes_debit_and_cache_mode(self):
        store = MemoryStateStore(_config(), clock=FakeClock())
        assert store.cache_mode() is False
        store.add_bytes(999)
        assert store.budget_remaining() == 1
        assert store.cache_mode() is False
        store.add_bytes(1)
        assert store.cache_mode() is True

    def test_budget_resets_on_utc_day_rollover(self):
        midnight = calendar.timegm((2026, 9, 27, 0, 0, 0))
        clock = FakeClock(start=midnight - 1)
        store = MemoryStateStore(_config(), clock=clock)
        store.add_bytes(1000)
        assert store.cache_mode() is True
        clock.now = midnight + 1
        assert store.budget_remaining() == 1000
        assert store.cache_mode() is False

    def test_remaining_never_negative(self):
        store = MemoryStateStore(_config(), clock=FakeClock())
        store.add_bytes(5000)
        assert store.budget_remaining() == 0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_api_state.py -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError` (módulo `quimera.api.state` não existe)

- [ ] **Step 3: Implementar `src/quimera/api/state.py`**

```python
"""Estado da API: cache, janela de rate limit e orçamento diário.

``StateStore`` é o protocolo; ``MemoryStateStore`` é a implementação
padrão — serve para dev, testes e a demo (um processo, escala a zero).
O Firestore entra depois implementando o mesmo protocolo, sem tocar na
app. Orçamento zera à meia-noite UTC; contagem de rate limit só registra
requisições ACEITAS (rejeitadas são baratas e não estendam o bloqueio).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Protocol

from .protections import ApiConfig


class StateStore(Protocol):
    """Estado compartilhado das proteções (cache, rate limit, orçamento)."""

    def cache_get(self, key: str) -> dict | None: ...
    def cache_set(self, key: str, value: dict) -> None: ...
    def allow_request(self, ip: str) -> bool: ...
    def retry_after(self, ip: str) -> int: ...
    def add_bytes(self, n: int) -> None: ...
    def budget_remaining(self) -> int: ...
    def cache_mode(self) -> bool: ...


class MemoryStateStore:
    """Implementação em memória do ``StateStore`` (um processo)."""

    def __init__(self, config: ApiConfig, clock=time.time) -> None:
        self._config = config
        self._clock = clock
        self._cache: dict[str, tuple[float, dict]] = {}
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._budget_day = self._utc_today()
        self._budget_used = 0

    def cache_get(self, key: str) -> dict | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if self._clock() - stored_at > self._config.cache_ttl_s:
            del self._cache[key]
            return None
        return value

    def cache_set(self, key: str, value: dict) -> None:
        self._cache[key] = (self._clock(), value)

    def allow_request(self, ip: str) -> bool:
        now = self._clock()
        window = self._config.rate_limit_window_s
        hits = self._requests[ip]
        while hits and now - hits[0] >= window:
            hits.popleft()
        if len(hits) >= self._config.rate_limit_max:
            return False
        hits.append(now)
        return True

    def retry_after(self, ip: str) -> int:
        hits = self._requests[ip]
        if not hits:
            return 0
        elapsed = self._clock() - hits[0]
        return max(1, int(self._config.rate_limit_window_s - elapsed) + 1)

    def add_bytes(self, n: int) -> None:
        self._check_day_rollover()
        self._budget_used += n

    def budget_remaining(self) -> int:
        self._check_day_rollover()
        return max(0, self._config.daily_bytes_budget - self._budget_used)

    def cache_mode(self) -> bool:
        return self.budget_remaining() <= 0

    def _check_day_rollover(self) -> None:
        today = self._utc_today()
        if today != self._budget_day:
            self._budget_day = today
            self._budget_used = 0

    def _utc_today(self):
        return datetime.fromtimestamp(self._clock(), timezone.utc).date()
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_api_state.py -v`
Expected: PASS (12 testes)

- [ ] **Step 5: Commit**

```bash
git add src/quimera/api/state.py tests/test_api_state.py
git commit -m "api: StateStore em memória (rate limit, cache com TTL, orçamento diário)"
```

---

### Task 3: Métricas — `metrics.py`

**Files:**
- Create: `src/quimera/api/metrics.py`
- Test: `tests/test_api_metrics.py`

- [ ] **Step 1: Escrever o teste de falha**

Criar `tests/test_api_metrics.py`:

```python
"""Testes do loader de métricas (Fase 2) para GET /metrics."""

from __future__ import annotations

import json

from quimera.api.metrics import load_metrics


def _write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class TestLoadMetrics:
    def test_reads_suites_thresholds_and_drops_per_case(self, tmp_path):
        results = tmp_path / "results"
        results.mkdir()
        _write(
            results / "extraction_m1_20260926.json",
            {"suite": "extraction", "metrics": {"n_cases": 45}, "per_case": [{"id": "ext_001"}]},
        )
        _write(
            results / "cnae_m2_20260926.json",
            {"suite": "cnae", "metrics": {"recall@5": 0.742}},
        )
        (results / "broken.json").write_text("{invalido", encoding="utf-8")
        _write(
            tmp_path / "thresholds.json",
            {"overall_field_accuracy": 0.85, "_comentario": {"nota": "x"}},
        )

        metrics = load_metrics(eval_dir=tmp_path)

        assert metrics["thresholds"] == {"overall_field_accuracy": 0.85}
        assert metrics["extraction"][0]["metrics"]["n_cases"] == 45
        assert "per_case" not in metrics["extraction"][0]
        assert metrics["cnae"][0]["metrics"]["recall@5"] == 0.742
        assert len(metrics["extraction"]) == 1

    def test_missing_dir_returns_empty_structure(self, tmp_path):
        metrics = load_metrics(eval_dir=tmp_path / "inexistente")
        assert metrics == {"thresholds": {}, "extraction": [], "cnae": []}

    def test_env_eval_dir_is_used(self, tmp_path, monkeypatch):
        (tmp_path / "results").mkdir()
        _write(
            tmp_path / "results" / "cnae_m_20260926.json",
            {"suite": "cnae", "metrics": {"mrr": 0.5}},
        )
        monkeypatch.setenv("EVAL_DIR", str(tmp_path))
        assert load_metrics()["cnae"][0]["metrics"]["mrr"] == 0.5
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_api_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError` (módulo `quimera.api.metrics` não existe)

- [ ] **Step 3: Implementar `src/quimera/api/metrics.py`**

```python
"""Métricas da Fase 2 para o endpoint GET /metrics.

Lê os JSON gravados por ``eval/run_eval`` (nenhuma métrica é escrita à
mão) e os limiares de ``eval/thresholds.json``. ``EVAL_DIR`` aponta a
raiz de ``eval/`` (padrão: ``eval`` relativo ao cwd; no deploy, o
diretório é copiado para dentro da imagem).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_EVAL_DIR = "eval"


def load_metrics(
    *, results_dir: str | Path | None = None, eval_dir: str | Path | None = None
) -> dict:
    """Devolve ``{"thresholds": {...}, "extraction": [...], "cnae": [...]}``."""
    base = Path(eval_dir or os.environ.get("EVAL_DIR", DEFAULT_EVAL_DIR))
    results = Path(results_dir) if results_dir else base / "results"
    suites: dict[str, list[dict]] = {"extraction": [], "cnae": []}
    if results.exists():
        for path in sorted(results.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            payload.pop("per_case", None)
            suite = payload.get("suite")
            if suite in suites:
                suites[suite].append(payload)

    thresholds: dict = {}
    thresholds_path = base / "thresholds.json"
    if thresholds_path.exists():
        try:
            thresholds = json.loads(thresholds_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            thresholds = {}
    thresholds.pop("_comentario", None)
    return {"thresholds": thresholds, **suites}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_api_metrics.py -v`
Expected: PASS (3 testes)

- [ ] **Step 5: Commit**

```bash
git add src/quimera/api/metrics.py tests/test_api_metrics.py
git commit -m "api: loader de métricas da Fase 2 (results + limiares)"
```

---

### Task 4: App FastAPI — factory, `/health`, `/metrics`

**Files:**
- Modify: `pyproject.toml` (extras `api` e `dev`)
- Modify: `src/quimera/api/__init__.py` (create_app re-export com import lazy)
- Create: `src/quimera/api/app.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Instalar dependências e atualizar `pyproject.toml`**

Alterar o bloco `[project.optional-dependencies]` para:

```toml
[project.optional-dependencies]
# Dependências de GCP nunca são importadas no topo dos módulos:
# todo import é lazy (dentro de funções), então `pytest` roda sem este extra.
gcp = [
    "google-cloud-bigquery>=3",
    "google-genai>=1",
]
api = [
    "fastapi>=0.115",
    "uvicorn>=0.30",
]
dev = [
    "pytest>=8",
    "fastapi>=0.115",
    "httpx>=0.27",
]
```

Executar: `pip install -e ".[dev,api,gcp]"`
Expected: instalação concluída sem erros.

- [ ] **Step 2: Escrever o teste de falha**

Criar `tests/test_api.py` (helpers no topo; as próximas tasks acrescentam classes a este arquivo):

```python
"""Testes da API com TestClient: endpoints, proteções e modo cache."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from quimera.api import create_app
from quimera.api.protections import ApiConfig
from quimera.api.state import MemoryStateStore

from fakes import FakeGenaiClient, FakePipelineBQ


def _config(**overrides) -> ApiConfig:
    base = dict(
        api_token=None,
        rate_limit_max=100,
        rate_limit_window_s=3600,
        cache_ttl_s=3600,
        daily_bytes_budget=10 * 1024**3,
        request_timeout_s=10.0,
    )
    base.update(overrides)
    return ApiConfig(**base)


LEAD_ROWS = [
    {
        "cnpj_basico": "12345678",
        "razao_social": "CLINICA ALFA",
        "nome_fantasia": None,
        "sigla_uf": "SP",
        "id_municipio": "3547807",
        "municipio": "Santo André",
        "cnae_fiscal_principal": "8630-5/01",
        "data_inicio_atividade": "20150110",
        "capital_social": 100_000.0,
        "porte": "demais",
    },
    {
        "cnpj_basico": "87654321",
        "razao_social": "CLINICA BETA",
        "nome_fantasia": "Beta Odonto",
        "sigla_uf": "SP",
        "id_municipio": "3547807",
        "municipio": "Santo André",
        "cnae_fiscal_principal": "8630-5/01",
        "data_inicio_atividade": "20240110",
        "capital_social": 1_000.0,
        "porte": "micro",
    },
]


def _extraction_payload(**filters) -> str:
    return json.dumps({"refused": False, "filters": filters}, ensure_ascii=False)


def _cnae_search(results):
    calls = []

    def search(query, k):
        calls.append((query, k))
        return results

    search.calls = calls
    return search


CNAE_MATCHES = [
    ("8630-5/01", "Atividade médica ambulatorial odontológica", 0.92),
    ("8630-5/02", "Atividade médica ambulatorial restrita a consultos", 0.81),
]


def _happy_clients():
    extract = FakeGenaiClient(
        _extraction_payload(cnae_query="clínicas odontológicas", ufs=["SP"])
    )
    search = _cnae_search(CNAE_MATCHES)
    bq = FakePipelineBQ(lead_rows=LEAD_ROWS)
    return extract, search, bq


def _app(**overrides):
    extract, search, bq = _happy_clients()
    return create_app(
        config=_config(**overrides),
        extract_client=extract,
        cnae_search=search,
        bq_client=bq,
    )


class TestHealth:
    def test_health_reports_version_and_budget(self):
        client = TestClient(_app())
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"]
        assert data["cache_mode"] is False
        assert data["budget_remaining_bytes"] == 10 * 1024**3


class TestMetrics:
    def test_metrics_serves_phase2_results(self, tmp_path, monkeypatch):
        (tmp_path / "results").mkdir()
        (tmp_path / "results" / "extraction_m1.json").write_text(
            json.dumps({"suite": "extraction", "metrics": {"n_cases": 45}}),
            encoding="utf-8",
        )
        (tmp_path / "thresholds.json").write_text(
            json.dumps({"overall_field_accuracy": 0.85}), encoding="utf-8"
        )
        monkeypatch.setenv("EVAL_DIR", str(tmp_path))
        client = TestClient(_app())
        resp = client.get("/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["thresholds"]["overall_field_accuracy"] == 0.85
        assert data["extraction"][0]["metrics"]["n_cases"] == 45


class TestCreateAppLazyImport:
    def test_package_reexports_create_app(self):
        import quimera.api

        assert callable(quimera.api.create_app)
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `python -m pytest tests/test_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'create_app' from 'quimera.api'`

- [ ] **Step 4: Implementar `src/quimera/api/__init__.py` e `src/quimera/api/app.py`**

`src/quimera/api/__init__.py`:

```python
"""API da demo pública (FastAPI). fastapi só é importado dentro de create_app."""

from __future__ import annotations


def create_app(**kwargs):
    from .app import create_app as _create_app

    return _create_app(**kwargs)
```

`src/quimera/api/app.py`:

```python
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
from .metrics import load_metrics
from .protections import ApiConfig
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

    app = FastAPI(title="Quimera", version=__version__)
    app.state.config = config
    app.state.store = state
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

    return app
```

Atenção: `create_app` recebe também `policy` (usado a partir da Task 5). Importar no topo de `app.py`:

```python
from ..policy import Policy, resolve_policy
```

e resolver dentro de create_app:

```python
    policy = policy or resolve_policy()
    app.state.policy = policy
```

(Mas NÃO remover o parâmetro — os testes futuros podem fixar `PUBLIC`.)

- [ ] **Step 5: Rodar e ver passar**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS (3 testes)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/quimera/api/__init__.py src/quimera/api/app.py tests/test_api.py
git commit -m "api: create_app com /health e /metrics; extras api e dev no pyproject"
```

---

### Task 5: `POST /leads` — happy path e recusa

**Files:**
- Modify: `src/quimera/api/app.py`
- Test: `tests/test_api.py` (acrescentar classes)

- [ ] **Step 1: Escrever o teste de falha (acrescentar ao final de `tests/test_api.py`)**

```python
class TestLeadsHappyPath:
    def test_post_leads_runs_pipeline_and_serializes(self):
        app = _app()
        client = TestClient(app)
        resp = client.post(
            "/leads", json={"request": "clínicas odontológicas em SP"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["refused"] is False
        assert data["cached"] is False
        assert data["policy"] == "public"
        assert data["filters"]["ufs"] == ["SP"]
        assert data["filters"]["cnae_codes"] == ["8630-5/01", "8630-5/02"]
        assert data["cnae_matches"][0][0] == "8630-5/01"
        assert [r["razao_social"] for r in data["rows"]] == [
            "CLINICA ALFA",
            "CLINICA BETA",
        ]
        assert data["rows"][0]["score"] >= data["rows"][1]["score"]
        assert data["bytes_billed"] == 1000
        assert data["cache_mode"] is False

    def test_post_leads_uses_injected_cnae_search(self):
        app = _app()
        client = TestClient(app)
        client.post("/leads", json={"request": "clínicas odontológicas"})
        assert app.state.pipeline_deps["cnae_search"].calls == [
            ("clínicas odontológicas", 5)
        ]


class TestLeadsRefusal:
    def test_personal_data_request_is_refused_with_200(self):
        extract = FakeGenaiClient(
            json.dumps(
                {"refused": True, "refusal_reason": "pedido de dado pessoal"},
                ensure_ascii=False,
            )
        )
        app = create_app(
            config=_config(),
            extract_client=extract,
            cnae_search=_cnae_search(CNAE_MATCHES),
            bq_client=FakePipelineBQ(),
        )
        client = TestClient(app)
        resp = client.post("/leads", json={"request": "telefone do dono"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["refused"] is True
        assert data["refusal_reason"] == "pedido de dado pessoal"
        assert data["cached"] is False

    def test_refusal_is_not_cached_or_budgeted(self):
        extract = FakeGenaiClient(
            json.dumps(
                {"refused": True, "refusal_reason": "pedido de dado pessoal"},
                ensure_ascii=False,
            )
        )
        app = create_app(
            config=_config(),
            extract_client=extract,
            cnae_search=_cnae_search(CNAE_MATCHES),
            bq_client=FakePipelineBQ(),
        )
        client = TestClient(app)
        client.post("/leads", json={"request": "telefone do dono"})
        client.post("/leads", json={"request": "telefone do dono"})
        assert len(extract.calls) == 2
        health = TestClient(app).get("/health").json()
        assert health["budget_remaining_bytes"] == 10 * 1024**3
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_api.py::TestLeadsHappyPath -v`
Expected: FAIL — `404 Not Found` (rota `/leads` não existe; `assert resp.status_code == 200` falha)

- [ ] **Step 3: Implementar o endpoint em `src/quimera/api/app.py`**

Acrescentar dentro de `create_app`, antes do `return app`:

```python
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
```

E acrescentar aos imports do topo:

```python
from .protections import normalize_request, request_hash
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS (8 testes)

- [ ] **Step 5: Commit**

```bash
git add src/quimera/api/app.py tests/test_api.py
git commit -m "api: POST /leads com happy path, recusa 200 e cache por hash do pedido"
```

---

### Task 6: Proteções no request — 401 (token) e 422 (validação)

**Files:**
- Modify: `src/quimera/api/app.py`
- Test: `tests/test_api.py` (acrescentar classes)

- [ ] **Step 1: Escrever o teste de falha (acrescentar ao final de `tests/test_api.py`)**

```python
class TestTokenProtection:
    def test_wrong_token_returns_401(self):
        client = TestClient(_app(api_token="segredo"))
        resp = client.post(
            "/leads",
            json={"request": "clínicas em SP"},
            headers={"X-Api-Token": "errado"},
        )
        assert resp.status_code == 401
        assert resp.json()["error"] == "unauthorized"

    def test_missing_token_returns_401(self):
        client = TestClient(_app(api_token="segredo"))
        resp = client.post("/leads", json={"request": "clínicas em SP"})
        assert resp.status_code == 401

    def test_correct_token_passes(self):
        client = TestClient(_app(api_token="segredo"))
        resp = client.post(
            "/leads",
            json={"request": "clínicas em SP"},
            headers={"X-Api-Token": "segredo"},
        )
        assert resp.status_code == 200

    def test_unset_token_disables_check(self):
        client = TestClient(_app(api_token=None))
        resp = client.post("/leads", json={"request": "clínicas em SP"})
        assert resp.status_code == 200


class TestBodyValidation:
    def test_empty_request_returns_422(self):
        client = TestClient(_app())
        resp = client.post("/leads", json={"request": ""})
        assert resp.status_code == 422
        assert resp.json()["error"] == "validação"

    def test_too_long_request_returns_422(self):
        client = TestClient(_app())
        resp = client.post("/leads", json={"request": "x" * 501})
        assert resp.status_code == 422

    def test_missing_request_field_returns_422(self):
        client = TestClient(_app())
        resp = client.post("/leads", json={})
        assert resp.status_code == 422
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_api.py::TestTokenProtection -v`
Expected: FAIL — recebe 200 em vez de 401

- [ ] **Step 3: Implementar o check de token em `src/quimera/api/app.py`**

Acrescentar `token_ok` aos imports de `.protections`, `Header` aos imports de `fastapi`, e o primeiro bloco do handler `leads`:

```python
    @app.post("/leads")
    def leads(
        body: LeadsRequestBody,
        request: Request,
        x_api_token: str | None = Header(default=None),
    ):
        if not token_ok(x_api_token, config.api_token):
            return JSONResponse(
                status_code=401,
                content={
                    "error": "unauthorized",
                    "reason": "token ausente ou inválido (X-Api-Token)",
                },
            )
        key = request_hash(normalize_request(body.request))
```

(O resto do handler permanece igual ao da Task 5.)

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS (15 testes)

- [ ] **Step 5: Commit**

```bash
git add src/quimera/api/app.py tests/test_api.py
git commit -m "api: token X-Api-Token (401) e validação de body (422)"
```

---

### Task 7: Rate limit por IP — 429

**Files:**
- Modify: `src/quimera/api/app.py`
- Test: `tests/test_api.py` (acrescentar classes)

- [ ] **Step 1: Escrever o teste de falha (acrescentar ao final de `tests/test_api.py`)**

```python
class TestRateLimit:
    def test_fourth_request_within_window_returns_429(self):
        client = TestClient(_app(rate_limit_max=3))
        for _ in range(3):
            resp = client.post("/leads", json={"request": "empresas em SP"})
            assert resp.status_code == 200
        resp = client.post("/leads", json={"request": "empresas em RJ"})
        assert resp.status_code == 429
        assert resp.json()["error"] == "rate limit"
        assert int(resp.headers["Retry-After"]) > 0

    def test_cache_hit_does_not_help_after_rate_limit(self):
        client = TestClient(_app(rate_limit_max=2))
        client.post("/leads", json={"request": "empresas em SP"})
        resp = client.post("/leads", json={"request": "empresas em SP"})
        assert resp.status_code == 429

    def test_other_ip_is_not_affected(self):
        client = TestClient(_app(rate_limit_max=1))
        resp = client.post("/leads", json={"request": "empresas em SP"})
        assert resp.status_code == 200
        resp = client.post(
            "/leads",
            json={"request": "empresas em SP"},
            headers={"X-Forwarded-For": "outro-ip, proxy"},
        )
        assert resp.status_code == 200

    def test_forwarded_for_first_hop_wins(self):
        client = TestClient(_app(rate_limit_max=1))
        resp = client.post(
            "/leads",
            json={"request": "empresas em SP"},
            headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"},
        )
        assert resp.status_code == 200
        resp = client.post(
            "/leads",
            json={"request": "empresas em RJ"},
            headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"},
        )
        assert resp.status_code == 429
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_api.py::TestRateLimit -v`
Expected: FAIL — recebe 200 em vez de 429

- [ ] **Step 3: Implementar rate limit em `src/quimera/api/app.py`**

Acrescentar o helper de IP dentro de `create_app` e o segundo bloco do handler:

```python
    def _client_ip(request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"
```

Dentro de `leads`, logo após o check de token:

```python
        ip = _client_ip(request)
        if not state.allow_request(ip):
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate limit",
                    "reason": (
                        f"limite de {config.rate_limit_max} requisições por "
                        f"{config.rate_limit_window_s}s por IP"
                    ),
                },
                headers={"Retry-After": str(state.retry_after(ip))},
            )
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS (19 testes)

- [ ] **Step 5: Commit**

```bash
git add src/quimera/api/app.py tests/test_api.py
git commit -m "api: rate limit por IP com X-Forwarded-For (429 + Retry-After)"
```

---

### Task 8: Orçamento diário e modo cache — 503

**Files:**
- Modify: `src/quimera/api/app.py`
- Test: `tests/test_api.py` (acrescentar classes)

- [ ] **Step 1: Escrever o teste de falha (acrescentar ao final de `tests/test_api.py`)**

```python
class TestBudgetAndCacheMode:
    def test_budget_debited_after_real_run(self):
        app = _app()
        client = TestClient(app)
        client.post("/leads", json={"request": "empresas em SP"})
        health = client.get("/health").json()
        assert health["budget_remaining_bytes"] == 10 * 1024**3 - 1000

    def test_budget_exhausted_blocks_new_requests_with_503(self):
        client = TestClient(_app(daily_bytes_budget=1000))
        resp = client.post("/leads", json={"request": "empresas em SP"})
        assert resp.status_code == 200
        resp = client.post("/leads", json={"request": "empresas em RJ"})
        assert resp.status_code == 503
        data = resp.json()
        assert data["error"] == "cache mode"
        assert "orçamento" in data["reason"]

    def test_cache_hit_still_served_in_cache_mode(self):
        client = TestClient(_app(daily_bytes_budget=1000))
        client.post("/leads", json={"request": "empresas em SP"})
        resp = client.post("/leads", json={"request": "empresas em SP"})
        assert resp.status_code == 200
        assert resp.json()["cached"] is True


class TestCache:
    def test_second_identical_request_is_cached(self):
        app = _app()
        extract, search, bq = app.state.pipeline_deps["extract_client"], (
            app.state.pipeline_deps["cnae_search"]
        ), app.state.pipeline_deps["bq_client"]
        client = TestClient(app)
        resp1 = client.post("/leads", json={"request": "empresas em SP"})
        resp2 = client.post("/leads", json={"request": "empresas em SP"})
        assert resp1.json()["cached"] is False
        assert resp2.json()["cached"] is True
        assert len(extract.calls) == 1
        assert len(bq.executed) == 1

    def test_normalization_makes_variants_share_cache(self):
        client = TestClient(_app())
        client.post("/leads", json={"request": "empresas em SP"})
        resp = client.post("/leads", json={"request": "empresas   em SP"})
        assert resp.json()["cached"] is True

    def test_different_request_is_not_cached(self):
        client = TestClient(_app())
        client.post("/leads", json={"request": "empresas em SP"})
        resp = client.post("/leads", json={"request": "empresas em RJ"})
        assert resp.json()["cached"] is False

    def test_cached_response_keeps_payload_shape(self):
        client = TestClient(_app())
        first = client.post("/leads", json={"request": "empresas em SP"}).json()
        cached = client.post("/leads", json={"request": "empresas em SP"}).json()
        assert cached["rows"] == first["rows"]
        assert cached["filters"] == first["filters"]
        assert cached["bytes_billed"] == first["bytes_billed"]
        assert cached["cache_mode"] is False
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_api.py::TestBudgetAndCacheMode -v`
Expected: FAIL — `test_budget_exhausted_blocks_new_requests_with_503` recebe 200 em vez de 503 (cache hit já cobre parte; o miss sem check de modo cache não bloqueia)

- [ ] **Step 3: Implementar o modo cache em `src/quimera/api/app.py`**

Dentro de `leads`, entre o rate limit e a checagem de cache... na ordem correta (token → rate limit → cache → modo cache):

```python
        cached = state.cache_get(key)
        if cached is not None:
            return {**cached, "cached": True, "cache_mode": state.cache_mode()}

        if state.cache_mode():
            return JSONResponse(
                status_code=503,
                content={
                    "error": "cache mode",
                    "reason": (
                        "orçamento diário esgotado; apenas pedidos já vistos "
                        "são respondidos"
                    ),
                },
            )

        result = _run_pipeline(body.request)
```

(O `if state.cache_mode()` entra DEPOIS do lookup de cache e ANTES da execução do pipeline.)

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS (27 testes)

- [ ] **Step 5: Commit**

```bash
git add src/quimera/api/app.py tests/test_api.py
git commit -m "api: orçamento diário com modo cache (503 no miss, cache hit segue 200)"
```

---

### Task 9: Timeout e erros do pipeline — 504, 503, 502

**Files:**
- Modify: `src/quimera/api/app.py`
- Test: `tests/test_api.py` (acrescentar classes)

- [ ] **Step 1: Escrever o teste de falha (acrescentar `import time` ao topo de `tests/test_api.py` e as classes ao final)**

```python
def _slow_cnae_search(results, delay_s=1.0):
    def search(query, k):
        time.sleep(delay_s)
        return results

    return search


class TestTimeout:
    def test_slow_pipeline_returns_504(self):
        extract = FakeGenaiClient(_extraction_payload(cnae_query="clínicas"))
        app = create_app(
            config=_config(request_timeout_s=0.05),
            extract_client=extract,
            cnae_search=_slow_cnae_search(CNAE_MATCHES),
            bq_client=FakePipelineBQ(lead_rows=[]),
        )
        client = TestClient(app)
        resp = client.post("/leads", json={"request": "clínicas em SP"})
        assert resp.status_code == 504
        data = resp.json()
        assert data["error"] == "timeout"


class TestPipelineErrors:
    def test_bytes_ceiling_exceeded_returns_503(self):
        extract = FakeGenaiClient(_extraction_payload(ufs=["SP"]))
        bq = FakePipelineBQ(lead_rows=[], dry_run_bytes=10 * 1024**3)
        app = create_app(
            config=_config(),
            extract_client=extract,
            cnae_search=_cnae_search(CNAE_MATCHES),
            bq_client=bq,
        )
        client = TestClient(app)
        resp = client.post("/leads", json={"request": "empresas em SP"})
        assert resp.status_code == 503
        assert resp.json()["error"] == "teto de bytes"

    def test_extraction_error_returns_502(self):
        extract = FakeGenaiClient("não é json")
        app = create_app(
            config=_config(),
            extract_client=extract,
            cnae_search=_cnae_search(CNAE_MATCHES),
            bq_client=FakePipelineBQ(),
        )
        client = TestClient(app)
        resp = client.post("/leads", json={"request": "empresas em SP"})
        assert resp.status_code == 502
        assert resp.json()["error"] == "erro de extração"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_api.py::TestTimeout tests/test_api.py::TestPipelineErrors -v`
Expected: FAIL — exceção do TestClient (500/exception) em vez de 504/503/502

- [ ] **Step 3: Implementar timeout e mapeamento de erros em `src/quimera/api/app.py`**

Trocar `_run_pipeline` e a chamada dentro de `leads`:

```python
    def _run_pipeline(text: str):
        from ..pipeline import run as run_pipeline

        return run_pipeline(
            text,
            policy,
            extract_client=app.state.pipeline_deps["extract_client"],
            cnae_search=app.state.pipeline_deps["cnae_search"],
            bq_client=app.state.pipeline_deps["bq_client"],
        )

    _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="quimera-api")
```

Dentro de `leads`, substituir `result = _run_pipeline(body.request)` por:

```python
        try:
            future = _executor.submit(_run_pipeline, body.request)
            result = future.result(timeout=config.request_timeout_s)
        except FuturesTimeoutError:
            return JSONResponse(
                status_code=504,
                content={
                    "error": "timeout",
                    "reason": (
                        f"execução excedeu {config.request_timeout_s} segundos"
                    ),
                },
            )
        except BytesBudgetExceededError as exc:
            return JSONResponse(
                status_code=503,
                content={"error": "teto de bytes", "reason": str(exc)},
            )
        except ExtractionError as exc:
            logger.warning("erro de extração: %s", exc)
            return JSONResponse(
                status_code=502,
                content={"error": "erro de extração", "reason": str(exc)},
            )
```

Imports no topo de `app.py`:

```python
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError

from ..extract import ExtractionError
from ..query import BytesBudgetExceededError
```

Limitação aceita e documentada: no 504 a thread continua o pipeline em background; se a query do BigQuery completar, os bytes dela não entram no orçamento (pior caso: uma query a 5 GiB não contabilizada). Aceitável para a demo de escala a zero.

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS (29 testes)

- [ ] **Step 5: Commit**

```bash
git add src/quimera/api/app.py tests/test_api.py
git commit -m "api: timeout 504 em thread pool e mapeamento de erros do pipeline (503/502)"
```

---

### Task 10: Runner `python -m quimera.api`

**Files:**
- Create: `src/quimera/api/__main__.py`

- [ ] **Step 1: Implementar `src/quimera/api/__main__.py`**

```python
"""Sobe o servidor da demo: ``python -m quimera.api`` (extra [api]).

Usa uvicorn; host/port vêm de ``API_HOST``/``PORT`` (Cloud Run injeta
``PORT``).
"""

from __future__ import annotations

import os


def main() -> int:
    import uvicorn

    from . import create_app

    uvicorn.run(
        create_app(),
        host=os.environ.get("API_HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Verificar que o servidor sobe e responde**

Run (PowerShell, fundo):

```powershell
$job = Start-Job { python -m quimera.api }
Start-Sleep -Seconds 4
Invoke-RestMethod http://127.0.0.1:8000/health
Remove-Job $job -Force
```

Expected: JSON `{"status": "ok", "version": "0.1.0", "cache_mode": false, "budget_remaining_bytes": 10737418240}`

- [ ] **Step 3: Rodar a suíte completa**

Run: `python -m pytest -q`
Expected: PASS — 196 testes (167 existentes + 29 novos)

- [ ] **Step 4: Commit**

```bash
git add src/quimera/api/__main__.py
git commit -m "api: runner python -m quimera.api (uvicorn, PORT/API_HOST)"
```

---

### Task 11: Documentação — README e .env.example

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

- [ ] **Step 1: Atualizar o README**

Na seção `## Uso`, acrescentar após o bloco de CLI existente:

```markdown
Servidor da demo (API):

```bash
python -m quimera.api            # uvicorn em 0.0.0.0:8000 (PORT/API_HOST)
# POST /leads   {"request": "..."} → filtros, CNAEs, ranking, bytes, custo
# GET  /health  → status, versão, orçamento restante, modo cache
# GET  /metrics → resultados medidos da Fase 2 (JSON)
```
```

Na linha de variáveis de ambiente, acrescentar: `API_TOKEN`,
`RATE_LIMIT_MAX`, `RATE_LIMIT_WINDOW_S`, `CACHE_TTL_S`,
`DAILY_BYTES_BUDGET`, `REQUEST_TIMEOUT_S`, `EVAL_DIR`.

No roadmap, trocar a linha da Fase 3 por:

```markdown
- [ ] Fase 3 — demo pública no Cloud Run
  - [x] 3a — API + proteções (FastAPI: token, rate limit, orçamento diário
        com modo cache, timeout; `src/quimera/api/`)
  - [ ] 3b — front (HTML+JS), Dockerfile, deploy, Secret Manager
```

- [ ] **Step 2: Atualizar o `.env.example`**

Acrescentar ao final:

```env
# --- API da demo (python -m quimera.api) ---
# Token obrigatório no deploy público (header X-Api-Token); vazio = desabilitado (dev).
API_TOKEN=
# Rate limit por IP: RATE_LIMIT_MAX requisições por RATE_LIMIT_WINDOW_S segundos.
RATE_LIMIT_MAX=10
RATE_LIMIT_WINDOW_S=3600
# TTL do cache de pedidos (hash SHA-256 do pedido normalizado).
CACHE_TTL_S=86400
# Orçamento diário global de bytes do BigQuery; ao estourar, modo cache (só pedidos já vistos).
DAILY_BYTES_BUDGET=10737418240
# Timeout por request em segundos.
REQUEST_TIMEOUT_S=60
```

- [ ] **Step 3: Rodar a suíte completa e lint**

Run: `python -m pytest -q` e `python -m ruff check src tests`
Expected: PASS — 196 testes; ruff sem erros (se houver, corrigir antes do commit)

- [ ] **Step 4: Commit**

```bash
git add README.md .env.example
git commit -m "docs: uso da API, variáveis de ambiente e roadmap da Fase 3a"
```

---

## Notas de auto-revisão do plano

- **Cobertura da spec:** token (Task 6), rate limit por IP com X-Forwarded-For e Retry-After (Task 7), cache por hash com TTL e normalização (Tasks 5/8), orçamento diário com modo cache e reset UTC (Tasks 2/8), timeout em thread (Task 9), limite de linhas via policy existente (sem código novo — `max_rows=50` já é forçado em `apply_policy`), `/health` (Task 4), `/metrics` (Tasks 3/4), recusa 200 sem cache/orçamento (Task 5), erros 422/401/429/503/504 + 502 (Tasks 6-9), extras `api`/`dev` (Task 4), runner (Task 10), docs (Task 11).
- **Tipos consistentes:** `ApiConfig(api_token, rate_limit_max, rate_limit_window_s, cache_ttl_s, daily_bytes_budget, request_timeout_s)` usado igual em Tasks 1-9; `StateStore` com os 7 métodos das Tasks 2-8.
- **Fora de escopo (conforme spec):** front, Dockerfile, Cloud Run, Firestore, tokens de LLM no orçamento.
