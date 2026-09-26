# Deploy da demo pública (Fase 3b) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Colocar a demo pública da Quimera no ar: front HTML+JS (laudo técnico numerado) servido pela própria FastAPI, Dockerfile, script de deploy Cloud Run (escala a zero, instância única), Secret Manager, Turnstile e runbook.

**Architecture:** Imagem única — a FastAPI serve os estáticos em `src/quimera/api/static/` (mesma origem, sem CORS) e autentica `POST /leads` com X-Api-Token OU Turnstile verificado server-side (`turnstile.py`, httpx injetável). Build via Cloud Build → Artifact Registry → Cloud Run `max-instances=1` (orçamento diário e rate limit continuam globais no `MemoryStateStore`). `GET /metrics` ganha a suíte e2e; o resultado do pipeline ganha `query_sql` para o painel "como a Quimera decidiu".

**Tech Stack:** Python 3.10+, FastAPI, uvicorn, httpx (entra no extra `[api]`), Cloudflare Turnstile, Docker (python:3.12-slim), gcloud (Cloud Run/Build/AR/Secret Manager/IAM), HTML+CSS+JS vanilla.

**Spec:** `docs/superpowers/specs/2026-09-26-deploy-demo-design.md`
**Mundo visual:** `DESIGN.md` (seed) + `PRODUCT.md` + `.impeccable/surfaces/src-quimera-api-static-index-html.md` — "Laudo Técnico Numerado" (roll 8ae3159d, escolhido pelo Bruno). Sem ferramenta de geração de imagem no harness, o passo de visualização do new-work foi pulado (registrado).

**Convenções do repo (importantíssimo):**
- Docstrings em pt-BR em todo módulo, classe e função pública; sem comentários inline salvo necessidade real (o comentário de DIREÇÃO no topo do CSS é a exceção deliberada — é o contrato do mundo visual).
- Imports de dependências opcionais sempre lazy (dentro de função); `pytest` roda sem o extra `[gcp]`.
- Testes não tocam GCP/rede: fakes de `tests/fakes.py` (`FakeGenaiClient`, `FakePipelineBQ`), verifier fake para Turnstile e `httpx.MockTransport` para o siteverify.
- `python -m pytest` roda do diretório raiz `C:\Dev\quimera`; `pyproject.toml` já tem `pythonpath = ["."]`.
- Commits em pt-BR, prefixos do estilo do repo (`api:`, `eval:`, `docs:`, …). Trabalho direto na `master`, como na Fase 3a.
- UI em pt-BR; identificadores em inglês; sem emojis.
- Verificação de testes após cada task: `python -m pytest -q` no final da task inteira (os steps mostram o comando focado; o da task garante regressão zero).

---

### Task 1: `query_sql` no resultado do pipeline

O painel "como a Quimera decidiu" exibe o SQL parametrizado (spec da Fase 3); hoje `PipelineResult` não carrega o SQL.

**Files:**
- Modify: `src/quimera/pipeline.py` (PipelineResult, run)
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Escrever o teste de falha**

Adicionar ao final de `tests/test_pipeline.py`:

```python
class TestQuerySql:
    def test_to_dict_exposes_parameterized_sql_of_last_query(self):
        extract = FakeGenaiClient(_extraction_payload(ufs=["SP"]))
        bq = FakePipelineBQ()
        result = run("empresas em SP", PUBLIC, extract_client=extract, bq_client=bq)
        assert bq.executed, "a query deveria ter rodado"
        assert result.query_sql == bq.executed[0][0]
        assert "@ufs" in result.query_sql
        assert result.to_dict()["query_sql"] == result.query_sql

    def test_refused_result_has_empty_query_sql(self):
        extract = FakeGenaiClient(
            json.dumps(
                {"refused": True, "refusal_reason": "pedido de dado pessoal"},
                ensure_ascii=False,
            )
        )
        result = run(
            "telefone do dono",
            PUBLIC,
            extract_client=extract,
            bq_client=FakePipelineBQ(),
        )
        assert result.query_sql == ""
        assert result.to_dict()["query_sql"] == ""
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_pipeline.py::TestQuerySql -v`
Expected: FAIL com `AttributeError: ... has no attribute 'query_sql'`

- [ ] **Step 3: Implementar**

Em `src/quimera/pipeline.py`, no dataclass `PipelineResult` (após o campo `warnings`):

```python
    # SQL parametrizado executado (vazio quando a consulta não roda).
    query_sql: str = ""
```

No `to_dict()`, após `"warnings"`:

```python
            "query_sql": self.query_sql,
```

No `run()`, no `PipelineResult(...)` final (o que recebe `rows=rows`), acrescentar o campo:

```python
        query_sql=spec.sql,
```

- [ ] **Step 4: Rodar testes e ver passar**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS (todos)

- [ ] **Step 5: Commit**

```bash
git add src/quimera/pipeline.py tests/test_pipeline.py
git commit -m "api: sql parametrizado no resultado (painel como decidiu)"
```

---

### Task 2: Campos Turnstile no `ApiConfig`

**Files:**
- Modify: `src/quimera/api/protections.py:41-61`
- Test: `tests/test_api_protections.py`

- [ ] **Step 1: Escrever o teste de falha**

Em `tests/test_api_protections.py`, trocar a tupla `ENV_VARS` por:

```python
ENV_VARS = (
    "API_TOKEN",
    "RATE_LIMIT_MAX",
    "RATE_LIMIT_WINDOW_S",
    "CACHE_TTL_S",
    "DAILY_BYTES_BUDGET",
    "REQUEST_TIMEOUT_S",
    "TURNSTILE_SECRET_KEY",
    "TURNSTILE_SITE_KEY",
)
```

E acrescentar ao `TestApiConfigFromEnv`:

```python
    def test_turnstile_defaults_to_disabled(self, monkeypatch):
        for var in ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        config = ApiConfig.from_env()
        assert config.turnstile_secret_key is None
        assert config.turnstile_site_key is None

    def test_reads_turnstile_environment(self, monkeypatch):
        monkeypatch.setenv("TURNSTILE_SECRET_KEY", "chave-secreta")
        monkeypatch.setenv("TURNSTILE_SITE_KEY", "chave-publica")
        config = ApiConfig.from_env()
        assert config.turnstile_secret_key == "chave-secreta"
        assert config.turnstile_site_key == "chave-publica"

    def test_empty_turnstile_env_means_disabled(self, monkeypatch):
        monkeypatch.setenv("TURNSTILE_SECRET_KEY", "")
        monkeypatch.setenv("TURNSTILE_SITE_KEY", "")
        config = ApiConfig.from_env()
        assert config.turnstile_secret_key is None
        assert config.turnstile_site_key is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_api_protections.py::TestApiConfigFromEnv -v`
Expected: FAIL com `TypeError: ApiConfig.__init__() got an unexpected keyword argument 'turnstile_secret_key'`

- [ ] **Step 3: Implementar**

Em `src/quimera/api/protections.py`, `ApiConfig` (campos novos no fim, com default para não quebrar os testes existentes que montam o dataclass direto):

```python
    turnstile_secret_key: str | None = None
    turnstile_site_key: str | None = None
```

No `from_env()`, após `request_timeout_s`:

```python
            turnstile_secret_key=os.environ.get("TURNSTILE_SECRET_KEY") or None,
            turnstile_site_key=os.environ.get("TURNSTILE_SITE_KEY") or None,
```

- [ ] **Step 4: Rodar testes e ver passar**

Run: `python -m pytest tests/test_api_protections.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/quimera/api/protections.py tests/test_api_protections.py
git commit -m "api: config do turnstile no ambiente"
```

---

### Task 3: `turnstile.py` — verificação server-side

**Files:**
- Create: `src/quimera/api/turnstile.py`
- Modify: `pyproject.toml` (httpx no extra `api`)
- Test: `tests/test_turnstile.py`

- [ ] **Step 1: Escrever o teste de falha**

Criar `tests/test_turnstile.py`:

```python
"""Testes da verificação do Turnstile com MockTransport (sem rede)."""

from __future__ import annotations

import httpx

from quimera.api.turnstile import verify


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestVerify:
    def test_success_true_passes(self):
        client = _client(lambda request: httpx.Response(200, json={"success": True}))
        assert verify("token-ok", "segredo", client=client) is True

    def test_success_false_fails(self):
        client = _client(lambda request: httpx.Response(200, json={"success": False}))
        assert verify("token-ok", "segredo", client=client) is False

    def test_empty_or_missing_token_fails_without_request(self):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"success": True})

        assert verify(None, "segredo", client=_client(handler)) is False
        assert verify("", "segredo", client=_client(handler)) is False
        assert seen == []

    def test_network_error_fails_closed(self):
        def handler(request):
            raise httpx.ConnectError("sem rede")

        assert verify("token-ok", "segredo", client=_client(handler)) is False

    def test_malformed_json_fails_closed(self):
        client = _client(lambda request: httpx.Response(200, text="não é json"))
        assert verify("token-ok", "segredo", client=client) is False

    def test_remote_ip_is_sent_as_form_field(self):
        captured = {}

        def handler(request):
            captured["body"] = request.read().decode("utf-8")
            return httpx.Response(200, json={"success": True})

        assert verify("token-ok", "segredo", "5.6.7.8", client=_client(handler)) is True
        assert "remoteip=5.6.7.8" in captured["body"]
        assert "secret=segredo" in captured["body"]
        assert "response=token-ok" in captured["body"]

    def test_no_remote_ip_no_field(self):
        captured = {}

        def handler(request):
            captured["body"] = request.read().decode("utf-8")
            return httpx.Response(200, json={"success": True})

        verify("token-ok", "segredo", None, client=_client(handler))
        assert "remoteip" not in captured["body"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_turnstile.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'quimera.api.turnstile'`

- [ ] **Step 3: Implementar**

Criar `src/quimera/api/turnstile.py`:

```python
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
```

Em `pyproject.toml`, extra `api`:

```toml
api = [
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "httpx>=0.27",
]
```

- [ ] **Step 4: Rodar testes e ver passar**

Run: `python -m pytest tests/test_turnstile.py -v`
Expected: PASS (7 testes)

- [ ] **Step 5: Commit**

```bash
git add src/quimera/api/turnstile.py tests/test_turnstile.py pyproject.toml
git commit -m "api: verificacao server-side do turnstile"
```

---

### Task 4: Autenticação X-Api-Token OU Turnstile + `GET /config`

Regras (spec): header válido passa; senão, com Turnstile configurado, o token do body é verificado (falha → 401); senão, com `API_TOKEN` configurado, 401; senão (nada configurado) liberado com warning — ergonomia de dev igual à 3a. O 401 do header continua vencendo o 422 de body.

**Files:**
- Modify: `src/quimera/api/app.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Escrever os testes de falha**

Adicionar a `tests/test_api.py` (helpers existentes `_config`, `_happy_clients`, `_app`):

```python
def _ts_app(verifier, **overrides):
    extract, search, bq = _happy_clients()
    return create_app(
        config=_config(turnstile_secret_key="ts-secret", **overrides),
        extract_client=extract,
        cnae_search=search,
        bq_client=bq,
        turnstile_verify=verifier,
    )


class TestTurnstileAuth:
    def test_valid_turnstile_token_passes_without_api_token(self):
        client = TestClient(_ts_app(lambda token, secret, ip=None: True))
        resp = client.post(
            "/leads", json={"request": "clínicas em SP", "turnstile": "tok"}
        )
        assert resp.status_code == 200
        assert resp.json()["cached"] is False

    def test_invalid_turnstile_returns_401(self):
        client = TestClient(_ts_app(lambda token, secret, ip=None: False))
        resp = client.post(
            "/leads", json={"request": "clínicas em SP", "turnstile": "tok"}
        )
        assert resp.status_code == 401
        assert resp.json()["error"] == "unauthorized"
        assert "Turnstile" in resp.json()["reason"]

    def test_missing_turnstile_returns_401_when_configured(self):
        client = TestClient(_ts_app(lambda token, secret, ip=None: True))
        resp = client.post("/leads", json={"request": "clínicas em SP"})
        assert resp.status_code == 401

    def test_api_token_still_passes_when_turnstile_is_configured(self):
        client = TestClient(
            _ts_app(lambda token, secret, ip=None: False, api_token="segredo")
        )
        resp = client.post(
            "/leads",
            json={"request": "clínicas em SP"},
            headers={"X-Api-Token": "segredo"},
        )
        assert resp.status_code == 200

    def test_verifier_receives_token_secret_and_client_ip(self):
        chamadas = []

        def verifier(token, secret, ip=None):
            chamadas.append((token, secret, ip))
            return True

        client = TestClient(_ts_app(verifier))
        client.post(
            "/leads",
            json={"request": "clínicas em SP", "turnstile": "tok-1"},
            headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"},
        )
        assert chamadas == [("tok-1", "ts-secret", "5.6.7.8")]

    def test_malformed_body_json_with_turnstile_returns_401_not_500(self):
        client = TestClient(_ts_app(lambda token, secret, ip=None: True))
        resp = client.post(
            "/leads",
            content=b"{nao e json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401

    def test_no_auth_configured_still_open_with_warning(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="quimera.api"):
            client = TestClient(_app(api_token=None))
        resp = client.post("/leads", json={"request": "clínicas em SP"})
        assert resp.status_code == 200
        assert any(
            "TURNSTILE" in msg or "API_TOKEN" in msg for msg in caplog.messages
        )


class TestConfigEndpoint:
    def test_config_exposes_turnstile_site_key(self):
        client = TestClient(_app(turnstile_site_key="chave-publica"))
        resp = client.get("/config")
        assert resp.status_code == 200
        assert resp.json() == {"turnstile_site_key": "chave-publica"}
        assert resp.headers["cache-control"] == "no-store"

    def test_config_site_key_none_when_unset(self):
        resp = TestClient(_app()).get("/config")
        assert resp.json() == {"turnstile_site_key": None}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_api.py::TestTurnstileAuth tests/test_api.py::TestConfigEndpoint -v`
Expected: FAIL (`TypeError: create_app() got an unexpected keyword argument 'turnstile_verify'`)

- [ ] **Step 3: Implementar**

Em `src/quimera/api/app.py`:

1. Import no topo, junto dos demais:

```python
from starlette.concurrency import run_in_threadpool
```

2. Body model — campo opcional que documenta o contrato:

```python
class LeadsRequestBody(BaseModel):
    request: str = Field(min_length=1, max_length=MAX_REQUEST_CHARS)
    turnstile: str | None = Field(default=None, max_length=2048)
```

3. `create_app` ganha o parâmetro (entre `bq_client` e `warmup`) e, logo após o `logger.warning` existente do `API_TOKEN`, o warning combinado e o resolver do verifier:

```python
    bq_client: Any | None = None,
    turnstile_verify: Any | None = None,
    warmup: bool = False,
```

```python
    if config.api_token is None and config.turnstile_secret_key is None:
        logger.warning(
            "nem API_TOKEN nem TURNSTILE_SECRET_KEY definidos; "
            "checagem de autenticação desabilitada"
        )

    def _turnstile_verifier():
        if turnstile_verify is not None:
            return turnstile_verify
        from .turnstile import verify as _verify

        return _verify
```

4. Trocar a função `_require_token` inteira por `_body_turnstile_token` + `_authenticate` (as dependências da rota passam a referenciar `_authenticate`):

```python
    async def _body_turnstile_token(request: Request) -> str | None:
        """Token do Turnstile do body, lido sem validar o body (auth antes)."""
        try:
            body = await request.json()
        except Exception:
            return None
        if isinstance(body, dict):
            token = body.get("turnstile")
            if isinstance(token, str) and token:
                return token
        return None

    async def _authenticate(
        request: Request, x_api_token: str | None = Header(default=None)
    ):
        """X-Api-Token válido OU Turnstile válido; nada configurado libera (dev)."""
        if config.api_token and token_ok(x_api_token, config.api_token):
            return
        if config.turnstile_secret_key:
            token = await _body_turnstile_token(request)
            if token:
                ip = _client_ip(request)
                ok = await run_in_threadpool(
                    _turnstile_verifier(), token, config.turnstile_secret_key, ip
                )
                if ok:
                    return
            raise ApiError(
                401,
                "unauthorized",
                "verificação Turnstile falhou ou está ausente; "
                "complete o desafio e tente de novo",
            )
        if config.api_token is None:
            return
        raise ApiError(401, "unauthorized", "token ausente ou inválido (X-Api-Token)")
```

5. Na rota, trocar `Depends(_require_token)`:

```python
    @app.post(
        "/leads",
        dependencies=[Depends(_authenticate), Depends(_enforce_rate_limit)],
    )
```

6. `GET /config`, ao lado de `/health` e `/metrics`:

```python
    @app.get("/config")
    def front_config():
        """Site key público do Turnstile para o front (não é segredo)."""
        return JSONResponse(
            {"turnstile_site_key": config.turnstile_site_key},
            headers={"Cache-Control": "no-store"},
        )
```

- [ ] **Step 4: Rodar testes e ver passar**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS (todos, inclusive os antigos — 401-vence-422 segue valendo pelo caminho do header)

- [ ] **Step 5: Commit**

```bash
git add src/quimera/api/app.py tests/test_api.py
git commit -m "api: /leads aceita turnstile ou token de servico; GET /config"
```

---

### Task 5: Suíte e2e no `GET /metrics`

A página de métricas precisa dos resultados ponta a ponta; `load_metrics` hoje só devolve `extraction` e `cnae`.

**Files:**
- Modify: `src/quimera/api/metrics.py:32`
- Test: `tests/test_api_metrics.py`

- [ ] **Step 1: Escrever o teste de falha**

Em `tests/test_api_metrics.py`, no `TestLoadMetrics`, ajustar o teste existente:

```python
    def test_missing_dir_returns_empty_structure(self, tmp_path):
        metrics = load_metrics(eval_dir=tmp_path / "inexistente")
        assert metrics == {"thresholds": {}, "extraction": [], "cnae": [], "e2e": []}
```

E acrescentar:

```python
    def test_reads_e2e_suite(self, tmp_path):
        results = tmp_path / "results"
        results.mkdir()
        _write(
            results / "e2e_flash_20260926.json",
            {
                "suite": "e2e",
                "date": "2026-09-26T19:17:57+00:00",
                "commit": "6ac4f68",
                "metrics": {"case_pass_rate": 0.95, "row_precision": 0.997},
            },
        )
        metrics = load_metrics(eval_dir=tmp_path)
        assert metrics["e2e"][0]["metrics"]["case_pass_rate"] == 0.95
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_api_metrics.py -v`
Expected: FAIL (e2e ausente; asserção de estrutura vazia diverge)

- [ ] **Step 3: Implementar**

Em `src/quimera/api/metrics.py`, trocar:

```python
    suites: dict[str, list[dict]] = {"extraction": [], "cnae": []}
```

por:

```python
    suites: dict[str, list[dict]] = {"extraction": [], "cnae": [], "e2e": []}
```

- [ ] **Step 4: Rodar testes e ver passar**

Run: `python -m pytest tests/test_api_metrics.py tests/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/quimera/api/metrics.py tests/test_api_metrics.py
git commit -m "api: suite e2e no GET /metrics"
```

### Task 6: Front estático — `index.html` + montagem + package-data

A app monta `StaticFiles(html=True)` em `/` **depois** de todas as rotas (API vence o mount). O `index.html` completo entra aqui; `style.css`/`app.js` na Task 7; anexo de métricas na Task 8.

**Files:**
- Create: `src/quimera/api/static/index.html`
- Modify: `src/quimera/api/app.py` (mount), `pyproject.toml` (package-data)
- Test: `tests/test_api.py`

- [ ] **Step 1: Escrever o teste de falha**

Adicionar a `tests/test_api.py`:

```python
class TestFrontend:
    def test_root_serves_laud_page(self):
        resp = TestClient(_app()).get("/")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert "Quimera — Laudo de Prospecção" in resp.text
        assert "Emitir laudo" in resp.text
        assert 'lang="pt-BR"' in resp.text

    def test_metrics_html_served(self):
        resp = TestClient(_app()).get("/metrics.html")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert "Métricas medidas" in resp.text
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_api.py::TestFrontend -v`
Expected: FAIL (404 — sem mount e sem arquivos)

- [ ] **Step 3: Criar `index.html`**

Criar `src/quimera/api/static/index.html`:

```html
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Quimera — Laudo de Prospecção</title>
<meta name="description" content="Pedido em português vira lista ranqueada de empresas (CNPJ) com decisão explicável, bytes e custo medidos.">
<link rel="stylesheet" href="/style.css">
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit" defer></script>
</head>
<body>
<main class="sheet" id="laudo">
  <header class="laudo-header">
    <p class="doc-kind">Demo pública</p>
    <h1>Quimera — Laudo de Prospecção</h1>
    <dl class="meta">
      <div><dt>Versão</dt><dd id="meta-version">—</dd></div>
      <div><dt>Política</dt><dd>pública · sem dado pessoal</dd></div>
      <div><dt>Base</dt><dd>CNPJ ativos (Receita Federal via BigQuery)</dd></div>
      <div><dt>Avaliação</dt><dd><a href="/metrics.html">métricas medidas</a></dd></div>
    </dl>
  </header>

  <form id="form-laudo" class="findings" novalidate>
    <label class="field-label" for="pedido">Pedido — o que este laudo deve investigar</label>
    <textarea id="pedido" name="request" maxlength="500" rows="3" required
      placeholder="ex.: clínicas odontológicas em Santo André abertas há mais de 2 anos"></textarea>
    <p class="field-meta"><span id="contador">0/500</span></p>
    <fieldset class="exemplos">
      <legend>Pedidos-modelo</legend>
      <button type="button" class="exemplo">clínicas odontológicas em Santo André abertas há mais de 2 anos</button>
      <button type="button" class="exemplo">padarias artesanais em Curitiba</button>
      <button type="button" class="exemplo">transportadoras de carga em São Paulo capital</button>
      <button type="button" class="exemplo">escritórios de contabilidade em Belo Horizonte</button>
    </fieldset>
    <div id="turnstile" class="turnstile"></div>
    <button type="submit" id="emitir" class="acao-primaria">Emitir laudo</button>
    <p id="status" class="status" role="status" aria-live="polite"></p>
  </form>

  <section id="resultado" class="findings" hidden></section>

  <footer class="laudo-footer">
    <p>Nenhum dado pessoal é coletado ou exibido. Cada afirmação deste laudo vem
    da resposta da API; as métricas do <a href="/metrics.html">anexo</a> vêm
    de <code>eval/</code>.</p>
  </footer>
</main>
<script src="/app.js" defer></script>
</body>
</html>
```

(Os 4 pedidos-modelo vêm do golden e2e — casos reais medidos.)

- [ ] **Step 4: Montar os estáticos na app**

Em `src/quimera/api/app.py`, import no topo (junto aos de `logging` etc.):

```python
from pathlib import Path
```

Logo antes do `return app` final (depois de todas as rotas — o mount em `/` só pega o que nenhuma rota pegou):

```python
    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
```

(Instalação sem package-data: a API segue funcionando e o front dá 404.)

Em `pyproject.toml`:

```toml
[tool.setuptools.package-data]
quimera = ["data/*.jsonl", "data/*.npz"]
"quimera.api" = ["static/*"]
```

- [ ] **Step 5: Rodar testes e ver passar**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/quimera/api/static/index.html src/quimera/api/app.py pyproject.toml tests/test_api.py
git commit -m "front: folha do laudo servida pela propria api"
```

---

### Task 7: Front — `style.css` + `app.js` (o laudo completo)

**Files:**
- Create: `src/quimera/api/static/style.css`
- Create: `src/quimera/api/static/app.js`
- Test: `tests/test_api.py`

- [ ] **Step 1: Escrever o teste de falha**

Adicionar ao `TestFrontend` em `tests/test_api.py`:

```python
    def test_static_assets_served(self):
        client = TestClient(_app())
        css = client.get("/style.css")
        js = client.get("/app.js")
        assert css.status_code == 200
        assert "text/css" in css.headers["content-type"]
        assert js.status_code == 200
        assert "javascript" in js.headers["content-type"]
        assert "--acento" in css.text
        assert "renderizarLaudo" in js.text
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_api.py::TestFrontend::test_static_assets_served -v`
Expected: FAIL (404)

- [ ] **Step 3: Criar `style.css`**

Criar `src/quimera/api/static/style.css` (o comentário de abertura é o contrato de direção do mundo visual — mantê-lo):

```css
/*
DIREÇÃO — Laudo Técnico Numerado (Fase 3b)
THESIS: a demo que prova rigor vira laudo: achados numerados e valores medidos, recusando o hero-gradiente-card do gênero SaaS de IA.
OWN-WORLD: papel #FFFFFF sobre mesa #F1F1EF, tinta #16181D, hairlines #C7CAD1, acento único azul-tinta #1F3DB3; sans de sistema + mono para todo valor medido; zero sombras.
STORY: o visitante emite o laudo e lê a decisão como achados numerados (interpretação, CNAE, consulta, ranking, custos), com bytes e custo em mono; as métricas medidas ficam no anexo carimbado.
FIRST VIEWPORT: folha centrada, cabeçalho de metadados, campo Pedido com 4 pedidos-modelo e o botão "Emitir laudo" em azul-tinta; nada mais.
FORM: laudo técnico numerado, 5º de 7 por ressonância; staging documental própria (achados em sequência); seed 8ae3159d.
*/

:root {
  --papel: #ffffff;
  --mesa: #f1f1ef;
  --tinta: #16181d;
  --suporte: #5a5f6b;
  --regra: #c7cad1;
  --acento: #1f3db3;
  --acento-fundo: #1a349c;
  --ok: #0e7a3c;
  --erro: #b3261e;
  --mono: ui-monospace, "Cascadia Mono", Consolas, Menlo, monospace;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--mesa);
  color: var(--tinta);
  font: 400 16px/1.6 system-ui, "Segoe UI", Arial, sans-serif;
}

a { color: var(--acento); }
a:focus-visible, button:focus-visible, summary:focus-visible {
  outline: 2px solid var(--tinta);
  outline-offset: 2px;
}

.sheet {
  max-width: 880px;
  margin: 24px auto 64px;
  background: var(--papel);
  border: 1px solid var(--regra);
  padding: clamp(20px, 5vw, 48px);
}

/* Cabeçalho do laudo */
.doc-kind {
  margin: 0;
  font-size: 11px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--suporte);
}
.laudo-header h1 {
  margin: 4px 0 16px;
  font-size: clamp(24px, 4.5vw, 32px);
  line-height: 1.2;
  letter-spacing: 0.01em;
}
.meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 8px 24px;
  margin: 0 0 24px;
  padding: 14px 0;
  border-top: 2px solid var(--tinta);
  border-bottom: 1px solid var(--regra);
}
.meta dt {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--suporte);
}
.meta dd { margin: 2px 0 0; font-size: 14px; }

/* Achados numerados */
.findings { margin: 0; }
.achado {
  padding: 28px 0 6px;
  border-top: 1px solid var(--regra);
}
.achado:first-child { border-top: none; }
.achado h2 {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin: 0 0 12px;
  font-size: 15px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.achado h2 .num {
  font: 700 15px/1 var(--mono);
  color: var(--acento);
}
.achado p { margin: 0 0 12px; max-width: 72ch; }

/* Tabelas */
.tabela-wrap { overflow-x: auto; margin: 0 0 12px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--regra);
  text-align: left;
  vertical-align: top;
}
thead th {
  border-top: 2px solid var(--tinta);
  border-bottom: 1px solid var(--tinta);
  font-size: 11px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--suporte);
  white-space: nowrap;
}
td.mono, .mono { font-family: var(--mono); font-size: 13.5px; }
td.num { text-align: right; font-family: var(--mono); white-space: nowrap; }
caption {
  caption-side: top;
  text-align: left;
  font-size: 12px;
  color: var(--suporte);
  padding: 0 0 8px;
}

/* Formulário */
.field-label {
  display: block;
  font-size: 11px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--suporte);
  margin: 8px 0 6px;
}
textarea {
  width: 100%;
  font: inherit;
  color: inherit;
  background: var(--papel);
  border: 1px solid var(--regra);
  border-bottom: 2px solid var(--tinta);
  padding: 10px 12px;
  resize: vertical;
}
textarea:focus-visible { outline: 2px solid var(--acento); outline-offset: 1px; }
.field-meta {
  margin: 4px 0 0;
  font-family: var(--mono);
  font-size: 12px;
  color: var(--suporte);
  text-align: right;
}
.exemplos {
  border: 1px solid var(--regra);
  padding: 10px 14px;
  margin: 20px 0 0;
}
.exemplos legend {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--suporte);
  padding: 0 6px;
}
.exemplo {
  display: block;
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  border-bottom: 1px solid var(--regra);
  padding: 8px 4px;
  font: inherit;
  color: var(--tinta);
  cursor: pointer;
}
.exemplo:last-child { border-bottom: none; }
.exemplo:hover { color: var(--acento); }
.turnstile { margin-top: 20px; min-height: 65px; }
.acao-primaria {
  background: var(--acento);
  color: var(--papel);
  border: none;
  padding: 14px 28px;
  margin-top: 20px;
  font: 600 14px/1 system-ui, "Segoe UI", Arial, sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  cursor: pointer;
}
.acao-primaria:hover { background: var(--acento-fundo); }
.acao-primaria:disabled { background: var(--suporte); cursor: wait; }
.status {
  min-height: 24px;
  margin: 12px 0 0;
  font-family: var(--mono);
  font-size: 13px;
  color: var(--suporte);
}

/* SQL e pares chave-valor */
.sql {
  font-family: var(--mono);
  font-size: 13px;
  line-height: 1.5;
  border: 1px solid var(--regra);
  padding: 12px 14px;
  margin: 0 0 12px;
  overflow-x: auto;
  white-space: pre;
}
.kv {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 4px 16px;
  margin: 0 0 12px;
  max-width: 72ch;
}
.kv dt {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--suporte);
  align-self: baseline;
}
.kv dd { margin: 0; font-family: var(--mono); font-size: 14px; }

/* Selos e estados */
.selo {
  display: inline-block;
  font: 600 11px/1 var(--mono);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 4px 8px;
  border: 1px solid currentColor;
}
.selo-cache { color: var(--ok); }
.selo-limiar { color: var(--ok); }
.selo-modo-cache { color: var(--erro); }
.observacao { border: 2px solid var(--erro); padding: 16px 20px; margin: 28px 0 8px; }
.observacao h2 { color: var(--erro); }
.ressalvas { margin: 0 0 12px; padding-left: 20px; max-width: 72ch; }
.ressalvas li { margin: 4px 0; }
.motivos { margin: 4px 0 0; padding-left: 16px; font-size: 13px; color: var(--suporte); }
details.resumo-nota summary { cursor: pointer; font-family: var(--mono); font-size: 13.5px; }
details.resumo-nota summary::marker { color: var(--acento); }

/* Rodapé */
.laudo-footer {
  border-top: 2px solid var(--tinta);
  margin-top: 40px;
  padding-top: 16px;
  font-size: 13px;
  color: var(--suporte);
}
.laudo-footer p { margin: 0; max-width: 72ch; }

/* Carimbo (anexo de métricas) */
.carimbo {
  display: inline-block;
  margin: 8px 0 24px;
  font: 700 14px/1.3 var(--mono);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--acento);
  border: 3px double var(--acento);
  padding: 10px 18px;
  transform: rotate(-4deg);
}
.carregando { font-family: var(--mono); font-size: 13px; color: var(--suporte); }

/* Movimento (documental, discreto) */
@media (prefers-reduced-motion: no-preference) {
  .achado { animation: surge 220ms ease-out both; }
  .achado:nth-of-type(2) { animation-delay: 90ms; }
  .achado:nth-of-type(3) { animation-delay: 180ms; }
  .achado:nth-of-type(4) { animation-delay: 270ms; }
  .achado:nth-of-type(5) { animation-delay: 360ms; }
  @keyframes surge {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: none; }
  }
  .carimbo { animation: carimbar 320ms cubic-bezier(0.2, 1.4, 0.4, 1) backwards; }
  @keyframes carimbar {
    from { opacity: 0; transform: rotate(-4deg) scale(1.6); }
    to { opacity: 1; transform: rotate(-4deg) scale(1); }
  }
}
```

- [ ] **Step 4: Criar `app.js`**

Criar `src/quimera/api/static/app.js`:

```js
/* Laudo de prospecção — front da demo pública (vanilla, mesma origem). */
"use strict";

const form = document.getElementById("form-laudo");
const textarea = document.getElementById("pedido");
const contador = document.getElementById("contador");
const statusEl = document.getElementById("status");
const resultado = document.getElementById("resultado");
const botaoEmitir = document.getElementById("emitir");
const turnstileBox = document.getElementById("turnstile");

let turnstileWidgetId = null;
let turnstileToken = null;

const fmtNum = new Intl.NumberFormat("pt-BR");
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
const fmtBytes = (b) =>
  b >= 1024 ** 3
    ? `${fmtNum.format(+(b / 1024 ** 3).toFixed(2))} GB`
    : `${fmtNum.format(+(b / 1024 ** 2).toFixed(1))} MB`;
const fmtUSD = (v) => (v == null ? "—" : `US$ ${v.toFixed(6).replace(".", ",")}`);
const fmtMs = (v) => (v == null ? "—" : `${fmtNum.format(Math.round(v))} ms`);
const fmtData = (yyyymmdd) =>
  /^\d{8}$/.test(yyyymmdd || "")
    ? `${yyyymmdd.slice(6, 8)}/${yyyymmdd.slice(4, 6)}/${yyyymmdd.slice(0, 4)}`
    : "—";
const lista = (v) => (Array.isArray(v) && v.length ? v.map(esc).join(", ") : "—");
const valor = (v) => (v == null ? "—" : fmtNum.format(v));

async function carregarConfig() {
  try {
    const cfg = await (await fetch("/config")).json();
    if (cfg.turnstile_site_key && window.turnstile) {
      turnstileWidgetId = window.turnstile.render(turnstileBox, {
        sitekey: cfg.turnstile_site_key,
        callback: (token) => { turnstileToken = token; },
        "expired-callback": () => { turnstileToken = null; },
        "error-callback": () => { turnstileToken = null; },
        language: "pt-br",
      });
    }
  } catch (_) { /* sem config: ambiente local sem Turnstile */ }
}

async function anotarVersao() {
  try {
    const saude = await (await fetch("/health")).json();
    const campo = document.getElementById("meta-version");
    if (campo && saude.version) campo.textContent = saude.version;
  } catch (_) { /* ignora */ }
}

async function orcamentoRestante() {
  try {
    const saude = await (await fetch("/health")).json();
    return fmtBytes(saude.budget_remaining_bytes);
  } catch (_) {
    return "—";
  }
}

textarea.addEventListener("input", () => {
  contador.textContent = `${textarea.value.length}/500`;
});

document.querySelectorAll(".exemplo").forEach((botao) => {
  botao.addEventListener("click", () => {
    textarea.value = botao.textContent.trim();
    contador.textContent = `${textarea.value.length}/500`;
    textarea.focus();
  });
});

form.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  const pedido = textarea.value.trim();
  if (!pedido) {
    statusEl.textContent = "Escreva um pedido para emitir o laudo.";
    return;
  }
  botaoEmitir.disabled = true;
  resultado.hidden = true;
  resultado.textContent = "";
  const inicio = performance.now();
  const etapas = "extração → classificação → consulta → pontuação";
  statusEl.textContent = `Elaborando laudo… (${etapas})`;
  const cronometro = setInterval(() => {
    statusEl.textContent =
      `Elaborando laudo… ${((performance.now() - inicio) / 1000).toFixed(1)} s (${etapas})`;
  }, 200);
  try {
    const body = { request: pedido };
    if (turnstileToken) body.turnstile = turnstileToken;
    const resp = await fetch("/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const dados = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      renderizarErro(resp.status, dados);
    } else {
      await renderizarLaudo(dados, (performance.now() - inicio) / 1000);
    }
  } catch (_) {
    statusEl.textContent = "Falha de rede ao contatar a API.";
  } finally {
    clearInterval(cronometro);
    statusEl.textContent = "";
    botaoEmitir.disabled = false;
    if (turnstileWidgetId !== null && window.turnstile) {
      turnstileToken = null;
      window.turnstile.reset(turnstileWidgetId);
    }
  }
});

function achado(num, titulo, corpoHtml) {
  return `<section class="achado">
    <h2><span class="num">${num}</span> ${esc(titulo)}</h2>
    ${corpoHtml}
  </section>`;
}

async function renderizarLaudo(dados, segundos) {
  const orcamento = await orcamentoRestante();
  const partes = [];
  if (dados.cached) {
    partes.push(`<p><span class="selo selo-cache">Em cache</span></p>`);
  }
  if (dados.refused) {
    partes.push(achado(1, "Indeferimento", `
      <p>${esc(dados.refusal_reason || "pedido recusado")}</p>
      <p>A política pública não responde pedidos de dado pessoal — de sócios,
      contato ou qualquer pessoa física.</p>`));
  } else {
    partes.push(...achadosDoLaudo(dados));
  }
  if (Array.isArray(dados.warnings) && dados.warnings.length) {
    const itens = dados.warnings.map((w) => `<li>${esc(w)}</li>`).join("");
    partes.push(achado(dados.refused ? 2 : 6, "Ressalvas", `<ol class="ressalvas">${itens}</ol>`));
  }
  partes.push(rodapeCustos(dados, segundos, orcamento));
  resultado.innerHTML = partes.join("");
  resultado.hidden = false;
  resultado.scrollIntoView({ behavior: "smooth", block: "start" });
}

function achadosDoLaudo(dados) {
  const f = dados.filters || {};
  const achados = [];
  achados.push(achado(1, "Interpretação do pedido", `
    <dl class="kv">
      <div><dt>Atividade</dt><dd>${esc(f.cnae_query || "—")}</dd></div>
      <div><dt>UFs</dt><dd>${lista(f.ufs)}</dd></div>
      <div><dt>Municípios</dt><dd>${lista(f.municipio_names)}</dd></div>
      <div><dt>Idade mínima</dt><dd>${f.min_age_years == null ? "—" : `${f.min_age_years} anos`}</dd></div>
      <div><dt>Idade máxima</dt><dd>${f.max_age_years == null ? "—" : `${f.max_age_years} anos`}</dd></div>
      <div><dt>Capital mínimo</dt><dd>${f.min_capital == null ? "—" : valor(f.min_capital)}</dd></div>
      <div><dt>Portes</dt><dd>${lista(f.portes)}</dd></div>
      <div><dt>Limite</dt><dd>${f.limit == null ? "—" : `${f.limit} empresas`}</dd></div>
    </dl>
    <p class="mono">filtro aplicado pela policy pública: sem MEI, sem contato, sem pessoa física.</p>`));

  if (Array.isArray(dados.cnae_matches) && dados.cnae_matches.length) {
    const linhas = dados.cnae_matches.map((m) => `
      <tr>
        <td class="mono">${esc(m[0])}</td>
        <td>${esc(m[1])}</td>
        <td class="num">${Number(m[2]).toFixed(3).replace(".", ",")}</td>
      </tr>`).join("");
    achados.push(achado(2, "Classificação CNAE", `
      <div class="tabela-wrap">
        <table>
          <caption>códigos escolhidos por similaridade de embeddings (top-k)</caption>
          <thead><tr><th>Código</th><th>Descrição</th><th>Simil.</th></tr></thead>
          <tbody>${linhas}</tbody>
        </table>
      </div>`));
  }

  const snapshot = dados.snapshot && Object.values(dados.snapshot)[0];
  achados.push(achado(3, "Consulta ao BigQuery", `
    ${dados.query_sql ? `<pre class="sql">${esc(dados.query_sql)}</pre>` : `<p>Consulta não executada (ver ressalvas).</p>`}
    <dl class="kv">
      <div><dt>Bytes processados</dt><dd>${fmtBytes(dados.bytes_processed)}</dd></div>
      <div><dt>Bytes cobrados</dt><dd>${fmtBytes(dados.bytes_billed)}</dd></div>
      <div><dt>Snapshot da base</dt><dd>${esc(snapshot || "—")}</dd></div>
    </dl>
    <p>SQL montado pelo sistema, parametrizado — o modelo não escreve SQL.
    Valores dos parâmetros: achados 1 e 2.</p>`));

  achados.push(achado(4, "Ranking de empresas", tabelaRanking(dados)));
  return achados;
}

function tabelaRanking(dados) {
  const linhas = (dados.rows || []).map((r, i) => `
    <tr>
      <td class="num">${i + 1}</td>
      <td>${esc(r.razao_social)}${r.nome_fantasia ? `<br><small>${esc(r.nome_fantasia)}</small>` : ""}</td>
      <td>${esc(r.municipio || r.id_municipio || "—")}/${esc(r.sigla_uf || "—")}</td>
      <td class="mono">${esc(r.cnae_fiscal_principal || "—")}</td>
      <td class="mono">${fmtData(r.data_inicio_atividade)}</td>
      <td class="num">${r.capital_social == null ? "—" : valor(r.capital_social)}</td>
      <td>${esc(r.porte || "—")}</td>
      <td class="num">${r.score == null ? "—" : r.score}</td>
      <td>
        <details class="resumo-nota">
          <summary>motivos</summary>
          <ul class="motivos">${(r.motivos_score || []).map((m) => `<li>${esc(m)}</li>`).join("") || "<li>—</li>"}</ul>
        </details>
      </td>
    </tr>`).join("");
  if (!linhas) {
    return `<p>Nenhuma empresa atendida ao pedido (ver ressalvas).</p>`;
  }
  return `<div class="tabela-wrap">
    <table>
      <caption>${(dados.rows || []).length} empresas — ordenadas pela nota do ICP</caption>
      <thead><tr>
        <th>#</th><th>Empresa</th><th>Local</th><th>CNAE</th><th>Início</th>
        <th>Capital (R$)</th><th>Porte</th><th>Nota</th><th></th>
      </tr></thead>
      <tbody>${linhas}</tbody>
    </table>
  </div>`;
}

function rodapeCustos(dados, segundos, orcamento) {
  const etapas = Object.entries(dados.timings_ms || {})
    .map(([etapa, ms]) => `${etapa} ${fmtMs(ms)}`)
    .join(" · ");
  const modoCache = dados.cache_mode
    ? `<p><span class="selo selo-modo-cache">Modo cache — orçamento do dia esgotado</span></p>`
    : "";
  return achado(dados.refused ? 3 : 5, "Custos e latência", `
    ${modoCache}
    <dl class="kv">
      <div><dt>Bytes cobrados</dt><dd>${fmtBytes(dados.bytes_billed)}</dd></div>
      <div><dt>Custo estimado</dt><dd>${fmtUSD(dados.estimated_cost_usd)}</dd></div>
      <div><dt>Latência do pipeline</dt><dd>${fmtMs(dados.latency_ms)}</dd></div>
      <div><dt>No navegador</dt><dd>${segundos.toFixed(1).replace(".", ",")} s</dd></div>
      <div><dt>Orçamento diário restante</dt><dd>${orcamento}</dd></div>
      <div><dt>Modelo</dt><dd>${esc(dados.model || "—")}</dd></div>
    </dl>
    ${etapas ? `<p class="mono">${etapas}</p>` : ""}`);
}

function renderizarErro(status, dados) {
  const mensagens = {
    401: "Não verificado: complete o desafio Turnstile e tente de novo.",
    422: `Pedido inválido: ${esc(dados.reason || "escreva um pedido com até 500 caracteres")}`,
    429: "Limite de requisições por IP atingido; aguarde alguns minutos.",
    502: `A extração falhou: ${esc(dados.reason || "tente reformular o pedido")}`,
    503: esc(dados.reason || "serviço indisponível; tente mais tarde"),
    504: "A execução passou de 60 s e foi cancelada; tente um pedido mais específico.",
  };
  const texto = mensagens[status] || esc(dados.reason || `erro ${status}`);
  resultado.innerHTML = `<section class="observacao achado">
    <h2><span class="num">!</span> Observação — pedido não atendido</h2>
    <p>${texto}</p>
  </section>`;
  resultado.hidden = false;
}

carregarConfig();
anotarVersao();
```

- [ ] **Step 5: Rodar testes e ver passar**

Run: `python -m pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 6: Verificação visual local (com o Bruno)**

Rodar `python -m quimera.api` e abrir `http://localhost:8000/`. Sem GCP os pedidos falham (502), mas a folha tem de aparecer: laudo centrado, cabeçalho de metadados, campo com contador, 4 pedidos-modelo clicáveis, botão azul-tinta. `/metrics.html` ainda 404 (Task 8).

- [ ] **Step 7: Commit**

```bash
git add src/quimera/api/static/style.css src/quimera/api/static/app.js tests/test_api.py
git commit -m "front: laudo completo (html+css+js) com achados numerados"
```

### Task 8: Front — anexo de métricas (`metrics.html` + `metrics.js`)

**Files:**
- Create: `src/quimera/api/static/metrics.html`
- Create: `src/quimera/api/static/metrics.js`
- Test: `tests/test_api.py`

- [ ] **Step 1: Escrever o teste de falha**

Adicionar ao `TestFrontend` em `tests/test_api.py`:

```python
    def test_metrics_page_renders_from_api_json(self):
        client = TestClient(_app())
        html = client.get("/metrics.html").text
        js = client.get("/metrics.js")
        assert "Anexo A" in html
        assert "regra de ouro" in html.lower()
        assert js.status_code == 200
        assert "javascript" in js.headers["content-type"]
        assert "carregarMetricas" in js.text
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_api.py::TestFrontend::test_metrics_page_renders_from_api_json -v`
Expected: FAIL (404 em `/metrics.js`)

- [ ] **Step 3: Criar `metrics.html`**

Criar `src/quimera/api/static/metrics.html`:

```html
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Quimera — Anexo A: Métricas medidas</title>
<meta name="description" content="Resultados medidos da avaliação da Quimera: extração de filtros, mapeamento CNAE e ponta a ponta, com limiares.">
<link rel="stylesheet" href="/style.css">
</head>
<body>
<main class="sheet">
  <header class="laudo-header">
    <p class="doc-kind">Anexo A</p>
    <h1>Métricas medidas</h1>
    <dl class="meta">
      <div><dt>Fonte</dt><dd><code>eval/results/*.json</code></dd></div>
      <div><dt>Limiares</dt><dd><code>eval/thresholds.json</code></dd></div>
      <div><dt>Regra de ouro</dt><dd>nenhum número escrito à mão</dd></div>
      <div><dt>Laudo</dt><dd><a href="/">voltar à demo</a></dd></div>
    </dl>
  </header>

  <section id="metricas" class="findings" aria-live="polite">
    <p class="carregando">Carregando métricas…</p>
  </section>

  <p class="carimbo" id="carimbo" hidden>Avaliado</p>

  <footer class="laudo-footer">
    <p>Toda métrica acima vem da última execução de cada suíte em
    <code>eval/results/</code>, com data e commit; os limiares são os mesmos do
    CI. O README só afirma o que está aqui (regra de ouro do projeto).</p>
  </footer>
</main>
<script src="/metrics.js" defer></script>
</body>
</html>
```

- [ ] **Step 4: Criar `metrics.js`**

Criar `src/quimera/api/static/metrics.js`:

```js
/* Anexo A — métricas medidas: renderiza GET /metrics (nada escrito à mão). */
"use strict";

const fmtNum = new Intl.NumberFormat("pt-BR");
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
const fmtPct = (v) => (v == null ? "—" : `${fmtNum.format(+(v * 100).toFixed(1))}%`);
const fmtNum2 = (v) => (v == null ? "—" : fmtNum.format(v));
const ultima = (lista) => (lista && lista.length ? lista[lista.length - 1] : null);

function linhaPct(rotulo, medido, limiar) {
  const texto = medido == null ? "—" : fmtPct(medido);
  const lim = limiar == null ? "—" : fmtPct(limiar);
  const batido = medido != null && limiar != null && medido >= limiar;
  const status = limiar == null
    ? ""
    : batido
      ? '<span class="selo selo-limiar">≥ limiar</span>'
      : "abaixo";
  return `<tr>
    <td>${esc(rotulo)}</td>
    <td class="num">${texto}</td>
    <td class="num">${lim}</td>
    <td>${status}</td>
  </tr>`;
}

function linhaQtd(rotulo, valor) {
  return `<tr>
    <td>${esc(rotulo)}</td>
    <td class="num">${fmtNum2(valor)}</td>
    <td class="num">—</td>
    <td></td>
  </tr>`;
}

function tabela(num, titulo, caption, corpo) {
  return `<section class="achado">
    <h2><span class="num">${num}</span> ${esc(titulo)}</h2>
    <div class="tabela-wrap">
      <table>
        <caption>${esc(caption)}</caption>
        <thead><tr><th>Métrica</th><th>Medido</th><th>Limiar</th><th></th></tr></thead>
        <tbody>${corpo}</tbody>
      </table>
    </div>
  </section>`;
}

async function carregarMetricas() {
  const alvo = document.getElementById("metricas");
  const carimbo = document.getElementById("carimbo");
  try {
    const dados = await (await fetch("/metrics")).json();
    const limiares = dados.thresholds || {};
    const ext = ultima(dados.extraction);
    const cnae = ultima(dados.cnae);
    const e2e = ultima(dados.e2e);
    const partes = [];

    if (ext) {
      const m = ext.metrics || {};
      partes.push(tabela(1, "Extração de filtros",
        `última execução: ${ext.date || "?"} · commit ${ext.commit || "?"}`,
        linhaPct("Recusa correta (dado pessoal)", m.correct_refusal_rate, limiares.correct_refusal_rate)
        + linhaPct("Recusa indevida", m.false_refusal_rate)
        + linhaPct("Acerto por campo", m.overall_field_accuracy, limiares.overall_field_accuracy)
        + linhaPct("Acerto exato do conjunto", m.exact_match_rate)
        + linhaQtd("Casos", m.n_cases)));
    }
    if (cnae) {
      const m = cnae.metrics || {};
      partes.push(tabela(2, "Mapeamento CNAE",
        `última execução: ${cnae.date || "?"} · commit ${cnae.commit || "?"}`,
        linhaPct("Recall@1", m["recall@1"])
        + linhaPct("Recall@5", m["recall@5"], limiares.recall_at_5)
        + linhaPct("MRR", m.mrr)
        + linhaQtd("Casos", m.n_cases)));
    }
    if (e2e) {
      const m = e2e.metrics || {};
      partes.push(tabela(3, "Ponta a ponta",
        `última execução: ${e2e.date || "?"} · commit ${e2e.commit || "?"}`,
        linhaPct("Casos 100% corretos", m.case_pass_rate, limiares.e2e_case_pass_rate)
        + linhaPct("Precisão por empresa", m.row_precision, limiares.e2e_row_precision)
        + linhaPct("Recusa correta", m.e2e_correct_refusal_rate, limiares.e2e_correct_refusal_rate)
        + linhaQtd("Empresas avaliadas", m.n_rows)
        + linhaQtd("Casos", m.n_cases)));
    }
    if (!partes.length) {
      alvo.innerHTML = `<p>Sem resultados de avaliação disponíveis.</p>`;
      return;
    }
    alvo.innerHTML = partes.join("");
    const referencia = e2e || cnae || ext;
    if (carimbo && referencia) {
      carimbo.textContent = `Avaliado — ${(referencia.date || "").slice(0, 10)}`;
      carimbo.hidden = false;
    }
  } catch (_) {
    alvo.innerHTML = `<p class="carregando">Não foi possível carregar /metrics.</p>`;
  }
}

carregarMetricas();
```

(Os limiares vêm de `eval/thresholds.json`: `correct_refusal_rate` 1.0, `overall_field_accuracy` 0.85, `recall_at_5` 0.9, `e2e_*` — chaves reais do arquivo.)

- [ ] **Step 5: Rodar testes e ver passar**

Run: `python -m pytest -q`
Expected: PASS (coleção inteira — fim das tasks de código)

- [ ] **Step 6: Commit**

```bash
git add src/quimera/api/static/metrics.html src/quimera/api/static/metrics.js tests/test_api.py
git commit -m "front: anexo A de metricas medidas"
```

---

### Task 9: Passada de acabamento visual (impeccable)

**Files:**
- Modify (se houver achados): `src/quimera/api/static/*`

- [ ] **Step 1: Rodar o detector mecânico**

```bash
node C:\Users\bruno\.opencode\skills\impeccable\scripts\detect.mjs --json src/quimera/api/static/index.html src/quimera/api/static/style.css src/quimera/api/static/app.js src/quimera/api/static/metrics.html src/quimera/api/static/metrics.js
```

Corrigir todo achado material (contraste, foco, semântica, responsivo) **sem abrir mão do mundo**: sem sombras, sem gradientes, sem radius (exceto carimbo), mono para valor medido, acento único.

- [ ] **Step 2: Conferência visual com o Bruno (mandatória)**

Com `python -m quimera.api` rodando, conferir em `http://localhost:8000/` e `http://localhost:8000/metrics.html`:

- folha do laudo: hierarquia por regras, sem sombras; azul-tinta só em interação/verificação;
- celulares (~375px): folha ocupa a largura, tabelas rolam horizontalmente, nada corta;
- teclado: Tab percorre textarea → pedidos-modelo → botão, com foco visível;
- com GCP configurado: achados aparecem numerados em sequência; recusa ("telefone do dono") mostra o Indeferimento; `/metrics.html` mostra as 3 tabelas + carimbo "Avaliado — data";
- erros (429/503/504 simulados) mostram a "Observação" com borda vermelha.

- [ ] **Step 3: Commit (se houve ajustes)**

```bash
git add src/quimera/api/static
git commit -m "front: acabamento do laudo (detector + revisao visual)"
```

---

### Task 10: Dockerfile + .dockerignore

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: Criar o Dockerfile**

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EVAL_DIR=/app/eval

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir ".[api,gcp]"

COPY eval/results/ eval/results/
COPY eval/thresholds.json eval/

RUN useradd --create-home quimera \
    && chown -R quimera:quimera /app
USER quimera

EXPOSE 8080
CMD ["python", "-m", "quimera.api"]
```

(O Cloud Run injeta `PORT=8080`; o `__main__` já lê. O índice CNAE de 25 MB e os dados entram via package-data do wheel.)

- [ ] **Step 2: Criar o .dockerignore**

```
.git
.gitignore
.env
.venv
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
tests/
docs/
scripts/
smoke_real.py
probe_*.py
debug_snapshot.py
eval/*.py
eval/golden_*.jsonl
eval/results/report.md
PRODUCT.md
DESIGN.md
.impeccable/
```

(`.env` NUNCA entra na imagem; só `eval/results/*.json` + `eval/thresholds.json` são copiados — é o que `EVAL_DIR=/app/eval` lê.)

- [ ] **Step 3: Build local (se houver Docker; senão o Cloud Build valida na Task 11)**

```bash
docker build -t quimera-demo:local .
docker run --rm -p 8080:8080 -e API_TOKEN=x quimera-demo:local
curl -s http://localhost:8080/health
```

Expected: `{"status": "ok", ...}` (falha de GCP no warmup só vai para o log).

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "deploy: imagem docker da demo (escala a zero)"
```

---

### Task 11: `scripts/deploy.sh` — runbook executável

**Files:**
- Create: `scripts/deploy.sh`

- [ ] **Step 1: Criar o script**

```bash
#!/usr/bin/env bash
# Deploy da demo pública da Quimera (Fase 3b). Runbook completo: docs/deploy.md.
# Requisitos: gcloud autenticado (login + application-default) e bq (vem no SDK).
# Uso:
#   API_TOKEN=... TURNSTILE_SITE_KEY=... TURNSTILE_SECRET_KEY=... bash scripts/deploy.sh
# Idempotente: re-executar só re-deploya (secrets/SA/bindings não são duplicados).
set -euo pipefail

PROJECT="${PROJECT:-quimera-leads}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-quimera-demo}"
SA_NAME="${SA_NAME:-quimera-demo}"
AR_REPO="${AR_REPO:-quimera}"
LEADS_DATASET="${LEADS_DATASET:-quimera}"
BQ_LOCATION="${BQ_LOCATION:-US}"
VERTEX_LOCATION="${VERTEX_LOCATION:-us-central1}"
DAILY_BYTES_BUDGET="${DAILY_BYTES_BUDGET:-10737418240}"
RATE_LIMIT_MAX="${RATE_LIMIT_MAX:-10}"
BUDGET_USD="${BUDGET_USD:-}"            # ex.: 20 -> cria alertas 50/80/100%
API_TOKEN="${API_TOKEN:-}"              # valor do secret (só na 1ª criação)
TURNSTILE_SECRET_KEY="${TURNSTILE_SECRET_KEY:-}"
TURNSTILE_SITE_KEY="${TURNSTILE_SITE_KEY:-}"

log() { printf '\n==> %s\n' "$*"; }

log "projeto e APIs"
gcloud config set project "$PROJECT"
gcloud services enable run cloudbuild artifactregistry secretmanager

SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${AR_REPO}/${SERVICE}"

log "artifact registry"
if ! gcloud artifacts repositories describe "$AR_REPO" --location="$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$AR_REPO" \
    --repository-format=docker --location="$REGION"
fi

log "secrets (cria só se não existirem)"
if ! gcloud secrets describe quimera-api-token >/dev/null 2>&1; then
  [ -n "$API_TOKEN" ] || { echo "API_TOKEN vazio: passe o valor para criar o secret"; exit 1; }
  printf '%s' "$API_TOKEN" | gcloud secrets create quimera-api-token --data-file=-
fi
if ! gcloud secrets describe quimera-turnstile-secret >/dev/null 2>&1; then
  if [ -n "$TURNSTILE_SECRET_KEY" ]; then
    printf '%s' "$TURNSTILE_SECRET_KEY" | gcloud secrets create quimera-turnstile-secret --data-file=-
  else
    echo "aviso: TURNSTILE_SECRET_KEY vazio — o front fica sem Turnstile até o próximo deploy com a chave"
  fi
fi

log "service account (privilégio mínimo da spec)"
if ! gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SA_NAME" --display-name="Quimera demo (Cloud Run)"
fi
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${SA_EMAIL}" --role=roles/bigquery.jobUser --condition=None >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${SA_EMAIL}" --role=roles/aiplatform.user --condition=None >/dev/null
bq add-iam-policy-binding \
  --member="serviceAccount:${SA_EMAIL}" \
  --role=roles/bigquery.dataViewer \
  "${PROJECT}:${LEADS_DATASET}" >/dev/null
gcloud secrets add-iam-policy-binding quimera-api-token \
  --member="serviceAccount:${SA_EMAIL}" --role=roles/secretmanager.secretAccessor >/dev/null
if gcloud secrets describe quimera-turnstile-secret >/dev/null 2>&1; then
  gcloud secrets add-iam-policy-binding quimera-turnstile-secret \
    --member="serviceAccount:${SA_EMAIL}" --role=roles/secretmanager.secretAccessor >/dev/null
fi

log "build (cloud build)"
TAG="$(date -u +%Y%m%dT%H%M%SZ)"
gcloud builds submit --tag="${IMAGE}:${TAG}" .

log "deploy (cloud run)"
SECRETS="API_TOKEN=quimera-api-token:latest"
if gcloud secrets describe quimera-turnstile-secret >/dev/null 2>&1; then
  SECRETS="${SECRETS},TURNSTILE_SECRET_KEY=quimera-turnstile-secret:latest"
fi
gcloud run deploy "$SERVICE" \
  --image="${IMAGE}:${TAG}" \
  --region="$REGION" \
  --service-account="$SA_EMAIL" \
  --min-instances=0 --max-instances=1 --concurrency=4 \
  --cpu=1 --memory=1Gi --timeout=120 \
  --allow-unauthenticated \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT},BQ_LOCATION=${BQ_LOCATION},VERTEX_LOCATION=${VERTEX_LOCATION},EXTRACT_MODEL=gemini-2.5-flash,EMBED_MODEL=text-embedding-005,MAX_BYTES_BILLED=5368709120,LEADS_DATASET=${LEADS_DATASET},DAILY_BYTES_BUDGET=${DAILY_BYTES_BUDGET},RATE_LIMIT_MAX=${RATE_LIMIT_MAX},RATE_LIMIT_WINDOW_S=3600,CACHE_TTL_S=86400,REQUEST_TIMEOUT_S=60,EVAL_DIR=/app/eval,TURNSTILE_SITE_KEY=${TURNSTILE_SITE_KEY}" \
  --set-secrets="$SECRETS"

URL=$(gcloud run services describe "$SERVICE" --region="$REGION" --format='value(status.url)')
log "smoke test: $URL"
curl -fsS "$URL/health"; echo
curl -fsS "$URL/metrics" -o /dev/null -w 'metrics: %{http_code}\n'
curl -fsS "$URL/" | grep -qi '<html' && echo 'front: ok'
curl -fsS "$URL/metrics.html" | grep -qi 'anexo' && echo 'anexo: ok'

if [ -n "$BUDGET_USD" ]; then
  log "alertas de orçamento (50/80/100%)"
  BA=$(gcloud billing projects describe "$PROJECT" --format='value(billingAccountName)' | sed 's#.*/##')
  gcloud beta billing budgets create --billing-account="$BA" \
    --display-name="quimera-demo" --budget-amount="${BUDGET_USD}USD" \
    --threshold-rule=percent=0.5 --threshold-rule=percent=0.8 --threshold-rule=percent=1.0 \
    || echo "sem permissão para criar orçamento por API: crie no console (docs/deploy.md)"
else
  echo "BUDGET_USD vazio: alertas não criados (console: Billing > Orçamentos; 50/80/100%)"
fi

printf '\nDEMO: %s\nANEXO: %s/metrics.html\n' "$URL" "$URL"
```

- [ ] **Step 2: Sintaxe e permissão**

```bash
bash -n scripts/deploy.sh && chmod +x scripts/deploy.sh && echo ok
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add scripts/deploy.sh
git commit -m "deploy: script gcloud do cloud run (idempotente)"
```

---

### Task 12: Docs — runbook, README, .env.example, roadmap

**Files:**
- Create: `docs/deploy.md`
- Modify: `README.md`, `.env.example`
- Commit também: `PRODUCT.md`, `DESIGN.md`, `.impeccable/surfaces/src-quimera-api-static-index-html.md`

- [ ] **Step 1: Criar `docs/deploy.md`**

```markdown
# Deploy da demo pública (Fase 3b)

Runbook para colocar e manter a demo no ar. O script `scripts/deploy.sh`
automatiza quase tudo; este documento explica cada peça e o que fazer quando
algo falha.

## Pré-requisitos (uma vez)

1. **gcloud** autenticado no WSL2 (ou git-bash):
   `gcloud auth login && gcloud auth application-default login`
2. **Projeto GCP** `quimera-leads` com billing ativo (crédito de teste).
3. **Turnstile (Cloudflare)**: dashboard > Turnstile > Add site.
   Hostname: `*.run.app` (a URL final do Cloud Run; dá para adicionar depois
   do 1º deploy). Widget "Managed". Guarde o **Site Key** (público) e o
   **Secret Key** (vai para o Secret Manager).

## Primeiro deploy

```bash
API_TOKEN=$(openssl rand -hex 32) \
TURNSTILE_SITE_KEY=0x... \
TURNSTILE_SECRET_KEY=0x... \
BUDGET_USD=20 \
bash scripts/deploy.sh
```

O script: habilita APIs, cria o repo no Artifact Registry, cria os secrets,
cria o SA `quimera-demo` com o mínimo (`bigquery.jobUser` no projeto,
`bigquery.dataViewer` só no dataset `quimera`, `aiplatform.user`,
`secretmanager.secretAccessor` nos 2 secrets), constrói a imagem, faz o
deploy (max-instances=1, escala a zero) e roda o smoke test.

Se o Turnstile ainda não tiver a URL: rode o 1º deploy sem
`TURNSTILE_*`, copie a URL impressa, cadastre o hostname no Cloudflare e
rode de novo com as chaves.

## Re-deploy (só código)

`bash scripts/deploy.sh` — secrets/SA/bindings já existem; só build+deploy.

## Alertas de orçamento

`BUDGET_USD=20` cria alertas 50/80/100%. Sem permissão de billing? Console:
Billing > Budgets & alerts > Create budget (projeto `quimera-leads`,
50/80/100%, notificar o e-mail do Bruno).

## Verificações de aceite (spec Fase 3)

- URL pública responde `/health` e o laudo em `/`.
- `POST /leads` com "telefone do dono de clínicas" → 200 `refused: true`.
- 11º pedido do mesmo IP em 1h → 429 (rate limit).
- Nenhuma resposta contém e-mail/telefone (colunas não existem no público).
- Orçamento esgotado → 503 com modo cache (testável baixando
  `DAILY_BYTES_BUDGET` num re-deploy de teste).

## Troubleshooting

- **Cold start lento no 1º pedido**: warmup roda em background; `/health`
  responde imediatamente, o 1º pedido pode levar +2–3 s.
- **429 do Gemini (cauda de latência)**: cota em `us-central1`; ver README.
- **500 sem detalhe**: `gcloud logging read 'resource.type=cloud_run_revision
  resource.labels.service_name=quimera-demo' --limit 20 --project quimera-leads`.
- **Turnstile sempre falhando**: conferir hostname do widget (deve cobrir a
  URL `*.run.app`) e `TURNSTILE_SECRET_KEY` (versão `latest` do secret).
- **Tabela de leads indisponível**: rodar `python -m quimera.dados build`
  (mensal — agendamento é item próprio do roadmap).

## Domínio custom (depois)

Cloud Run > Domains > Add; apontar CNAME; re-registrar o hostname no
Turnstile. Sem re-deploy.
```

- [ ] **Step 2: Atualizar `README.md`**

Na seção "Uso", após o bloco do servidor da demo, acrescentar:

```markdown
### Demo pública (Cloud Run)

Deploy: `bash scripts/deploy.sh` (runbook em `docs/deploy.md`, incluindo
Cloudflare Turnstile, service account mínimo e alertas de orçamento). A
página é um laudo técnico: pedido → achados numerados (interpretação, CNAEs,
SQL, ranking, custos) e o anexo `/metrics.html` com as métricas medidas.
```

E em "Variáveis de ambiente" acrescentar: `TURNSTILE_SITE_KEY` (público, no
HTML), `TURNSTILE_SECRET_KEY` (Secret Manager; verifica o token do front).

- [ ] **Step 3: Atualizar `.env.example`**

Acrescentar ao final:

```env
# --- Turnstile (Fase 3b: front público; site key é público, secret é segredo) ---
TURNSTILE_SITE_KEY=
TURNSTILE_SECRET_KEY=
```

- [ ] **Step 4: Roadmap no README**

Trocar a linha `  - [ ] 3b — front (HTML+JS), Dockerfile, deploy, Secret Manager`
por `  - [x] 3b — front (HTML+JS), Dockerfile, deploy, Secret Manager`.

- [ ] **Step 5: Commit**

```bash
git add docs/deploy.md README.md .env.example PRODUCT.md DESIGN.md .impeccable/surfaces/src-quimera-api-static-index-html.md
git commit -m "docs: runbook do deploy e contexto de produto/design do front"
```

---

### Task 13: Deploy real (com o Bruno) + aceite

**Files:** nenhum do repo (exceto README com a URL no final).

- [ ] **Step 1: Pré-requisitos com o Bruno**

- Bruno cria o widget Turnstile (Cloudflare) — ou decide adiar: 1º deploy sem
  Turnstile, cadastrar hostname depois e re-deployar com as chaves.
- Definir `API_TOKEN` (`openssl rand -hex 32`), `BUDGET_USD` (ex.: 20).

- [ ] **Step 2: Executar o deploy**

No WSL2/git-bash do Bruno (gcloud autenticado):

```bash
API_TOKEN=... TURNSTILE_SITE_KEY=... TURNSTILE_SECRET_KEY=... BUDGET_USD=20 bash scripts/deploy.sh
```

Se qualquer passo falhar (permissão, cota, API desabilitada), seguir o
troubleshooting de `docs/deploy.md`; nada de contornar com privilégio extra.

- [ ] **Step 3: Aceite da spec Fase 3 (verificar um a um)**

- [ ] URL pública: `/health` ok, laudo em `/`, anexo em `/metrics.html` com
      as 3 tabelas + carimbo.
- [ ] "telefone do dono de clínicas em SP" → 200 `refused: true` (Indeferimento).
- [ ] Um pedido real ("clínicas odontológicas em Santo André...") → laudo com
      os 5 achados, SQL, bytes e custo; repetir o pedido → selo "Em cache".
- [ ] 11 pedidos no mesmo IP na mesma hora → 429 no 11º.
- [ ] Nenhum campo de contato em nenhuma resposta (conferir o JSON do /leads).
- [ ] Custo por pedido registrado: `gcloud logging read` (log record do pipeline).

- [ ] **Step 4: Anotar a URL no README**

Na seção "Demo pública", incluir a URL final. Commit:

```bash
git add README.md
git commit -m "docs: url publica da demo"
```

---

## Notas de self-review do plano

- **Cobertura da spec:** Turnstile (Tasks 2-4), front + métricas (Tasks 5-8),
  Dockerfile (10), deploy/Secret Manager/SA/orçamento (11, 13), runbook (12),
  `/config` (4), `max-instances=1` (11), aceites da spec Fase 3 (13).
- **Decisões já validadas com testes existentes:** 401-vence-422 mantido
  (autenticação por header roda antes da validação do body); recusa não
  consome orçamento/cache (inalterado).
- **Riscos aceitos (herdados da spec):** `bq add-iam-policy-binding` pode
  pedir `--location` dependendo da versão do bq — se falhar, rodar com
  `--location=US`; `gcloud beta billing budgets` pode falhar por permissão —
  o script degrada para instruções manuais.


