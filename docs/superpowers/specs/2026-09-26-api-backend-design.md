# Design — Backend da demo pública (Fase 3, sub-fase API)

Data: 2026-09-26
Status: aprovado pelo Bruno em conversa
Escopo: FastAPI + proteções, **sem front e sem deploy** (Dockerfile/Cloud Run ficam
para a sub-fase seguinte).

## Decisões confirmadas com o Bruno

1. **Estado/cache:** abstração `StateStore` com implementação em memória
   (testes sem GCP; Firestore depois, sem tocar na app).
2. **Anti-abuso:** token estático no header `X-Api-Token` (captcha/Turnstile
   fica para a fase do front).
3. **Orçamento diário:** só bytes do BigQuery nesta fase (tokens do LLM depois).
4. **Métricas:** `GET /metrics` servindo JSON com os resultados da Fase 2.

## Arquitetura

```
src/quimera/api/
  __init__.py     # create_app(); import de fastapi só aqui (lazy)
  app.py          # create_app(state_store, pipeline_deps) — factory com DI
  protections.py  # funções puras: token, janela de rate limit, orçamento
  state.py        # protocolo StateStore + MemoryStateStore (padrão)
  metrics.py      # carrega eval/results/*.json + thresholds.json
```

- A app chama `pipeline.run()` com os clientes injetáveis já existentes
  (`extract_client`, `cnae_search`, `bq_client`) — mesmos fakes dos testes.
- `StateStore` (protocolo único, responsabilidades explícitas):
  `cache_get(key)`, `cache_set(key, value)`, `allow_request(ip) -> bool`,
  `add_bytes(n)`, `cache_mode() -> bool`.
- Policy continua vindo de `resolve_policy()` (`DEPLOY_MODE`; público por padrão).

## Endpoints

### POST /leads

Body: `{"request": string}` — não vazio, ≤ 500 chars (fora disso **422**).

Resposta: `PipelineResult.to_dict()` + `"cached": bool` + `"cache_mode": bool`.
Já inclui filtros extraídos, CNAEs com similaridade, linhas com score/motivos,
`bytes_billed` e custo estimado — o que a spec de Fase 3 pede.

### GET /health

`{"status": "ok", "version", "cache_mode", "budget_remaining_bytes"}`.

### GET /metrics

JSON com os resultados da Fase 2: carrega `eval/results/*.json` +
`eval/thresholds.json` (empacotados na imagem; arquivos pequenos) e devolve
métricas resumidas por suíte.

## Proteções (ordem por request em POST /leads)

1. **Token** — `X-Api-Token` vs `API_TOKEN` (env). Errado/ausente → **401**.
   `API_TOKEN` não definido → check desabilitado com warning no log
   (ergonomia de dev; no deploy o Secret Manager o define).
2. **Rate limit por IP** — janela deslizante em memória: `RATE_LIMIT_MAX`
   por `RATE_LIMIT_WINDOW_S` (default **10/hora/IP**). Excedeu → **429** com
   `Retry-After`. IP: `X-Forwarded-For` (padrão Cloud Run), fallback client direto.
3. **Cache** — chave `sha256` do pedido normalizado (mesma normalização do
   pipeline: `" ".join(split())`). Hit → **200** `cached: true`, sem LLM/BQ;
   conta no rate limit, não no orçamento. TTL default 24 h (`CACHE_TTL_S`).
4. **Modo cache** — orçamento diário estourado: cache hit responde; miss →
   **503** `reason: "orçamento diário esgotado"`. Orçamento:
   `DAILY_BYTES_BUDGET` (default **10 GiB** ≈ 2× o teto de 5 GiB por consulta);
   debita `bytes_billed` só de execuções reais; reset à meia-noite UTC.
5. **Timeout** — pipeline em thread com `REQUEST_TIMEOUT_S` (default **60 s**;
   p95 da extração ~7 s + BQ). Estourou → **504**.
6. **Limite de linhas** — garantido pela policy (`max_rows=50` público).
7. **Recusa (dado pessoal)** — `refused: true` em **200** (resultado legítimo,
   não erro HTTP); não consome orçamento nem entra no cache.

Erros sempre `{"error", "reason"}`: 422, 401, 429, 503, 504. Nenhum log ou
resposta contém dado pessoal — o pedido só é logado após a recusa (já vale
no pipeline).

## Testes (sem GCP, sem rede)

`tests/test_api.py` com `TestClient` (in-process) + fakes de cliente no estilo
de `tests/test_extract.py`:

- happy path → 200 com filtros/CNAEs/score
- recusa de dado pessoal → 200 `refused: true`, sem orçamento/cache
- 401 token errado/ausente; 422 vazio/`>500` chars; 429 após N requests
- cache: 2º pedido idêntico → `cached: true`, pipeline chamado 1×
- modo cache: orçamento esgotado → 503 no pedido novo; cache hit 200
- 504 timeout (fake lento + timeout curto)
- `/health` e `/metrics`
- proteções puras (janela, reset diário, hash) testadas como funções

## Empacotamento

```toml
api = ["fastapi>=0.115", "uvicorn>=0.30"]
dev = ["pytest>=8", "fastapi>=0.115", "httpx>=0.27"]   # TestClient
```

Execução local: `python -m quimera.api` (uvicorn via `create_app()`, import
lazy). README ganha seção de uso; roadmap recebe a sub-fase concluída.

## Limitações aceitas (decisões registradas em code review)

- **504 e bytes órfãos:** no timeout, a thread do pipeline continua rodando;
  se a query do BigQuery completar, os bytes não entram no orçamento (pior
  caso: ~uma query de 5 GiB não contabilizada por request).
- **Timeout conta espera de fila:** com mais de 4 requests simultâneos lentos,
  os enfileirados podem estourar o timeout sem ter começado.
- **Corrida conservadora no modo cache:** dois requests simultâneos podem
  passar pelo check antes do primeiro debitar (superdébito limitado pela
  concorrência do threadpool; direção conservadora).
- **IP por último hop do X-Forwarded-For:** o Cloud Run anexa o IP real
  observado; hops anteriores são controláveis pelo cliente. Correto para
  exatamente um proxy confiável (topologia atual). Revisar se um CDN entrar
  na frente.
- **Estado por processo:** `MemoryStateStore` perde cache/rate limit/orçamento
  no restart e o dicionário de IPs cresce sem varredura (aceito para
  escala a zero; Firestore na Fase 3b resolve).
- **Runner single-process:** `uvicorn.run(create_app(), ...)` sem
  import-string desabilita `--reload` e múltiplos workers (irrelevante para
  o deploy de escala a zero).

## Fora de escopo (registros explícitos)

- Front (HTML/JS), Dockerfile, Cloud Run, Secret Manager, alertas de orçamento
  GCP, service account — Fase 3b.
- Firestore, tokens do LLM no orçamento, captcha real, página HTML de métricas.
