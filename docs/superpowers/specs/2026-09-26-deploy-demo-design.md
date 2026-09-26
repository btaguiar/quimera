# Design — Deploy da demo pública (Fase 3b)

Data: 2026-09-26
Status: aprovado pelo Bruno em conversa
Escopo: front (HTML+JS), Dockerfile, deploy Cloud Run, Secret Manager,
service account mínimo e alertas de orçamento — tudo o que falta para a
URL pública. A API em si (`src/quimera/api/`) já existe (Fase 3a).

## Decisões confirmadas com o Bruno

1. **Escopo:** 3b completo (front, Dockerfile, deploy, Secret Manager,
   SA mínimo, alertas de orçamento). Firestore fica de fora.
2. **Projeto/região:** tudo em `quimera-leads`, Cloud Run em `us-central1`
   (mesmo projeto da tabela própria e do crédito de teste).
3. **Instância única:** `--max-instances=1` — o `MemoryStateStore` mantém
   orçamento diário e rate limit globais sem novo componente.
4. **Anti-abuso do front:** Cloudflare Turnstile (widget no front +
   verificação server-side), exigindo conta Cloudflare e registro do
   hostname da demo.
5. **Deploy manual:** script `gcloud` (bash, WSL2/git-bash); CI/CD depois.
6. **URL:** `run.app` padrão; domínio custom pode ser mapeado depois.

## Arquitetura

Imagem única: a FastAPI serve o front estático na mesma origem (sem
CORS) e o `/leads` verifica o Turnstile. Build pelo Cloud Build →
Artifact Registry → Cloud Run escala a zero.

```
src/quimera/api/
  static/          # index.html, app.js, style.css, metrics.html, metrics.js
  turnstile.py     # verify() -> siteverify da Cloudflare (httpx injetável)
scripts/deploy.sh  # runbook executável: APIs, AR, secrets, SA, build, deploy
Dockerfile
.dockerignore
docs/deploy.md     # runbook em texto + troubleshooting
```

### Serviço Cloud Run (`quimera-demo`)

- `--region=us-central1 --min-instances=0 --max-instances=1
  --concurrency=4 --cpu=1 --memory=1Gi --timeout=120
  --allow-unauthenticated`
  (concurrency=4 alinha com o `ThreadPoolExecutor` de 4 workers do
  pipeline; timeout 120 = `REQUEST_TIMEOUT_S` 60 + margem; proteção
  real vive na app, não no ingress).
- Env: os já existentes (`GOOGLE_CLOUD_PROJECT`, `BQ_LOCATION=US`,
  `VERTEX_LOCATION`, `EXTRACT_MODEL`, `EMBED_MODEL`,
  `MAX_BYTES_BILLED`, `DAILY_BYTES_BUDGET`, `RATE_LIMIT_*`,
  `CACHE_TTL_S`, `REQUEST_TIMEOUT_S`, `EVAL_DIR=/app/eval`) +
  `TURNSTILE_SITE_KEY` (público, vai no HTML).
- Secrets: `API_TOKEN=quimera-api-token:latest`,
  `TURNSTILE_SECRET_KEY=quimera-turnstile-secret:latest`.
- `warmup=True` já no `__main__`: o 1º pedido não paga os ~16 s de
  clientes/índice/diretório.

### Service account (privilégio mínimo da spec)

`quimera-demo@quimera-leads.iam.gserviceaccount.com`:

- `roles/bigquery.jobUser` no projeto (jobs faturados no projeto);
- `roles/bigquery.dataViewer` **só no dataset `quimera`** (via
  `bq add-iam-policy-binding`, não no projeto inteiro);
- `roles/aiplatform.user` no projeto (Gemini + embeddings).

O diretório de municípios (`br_bd_diretorios_brasil.municipio`, lido no
warmup) é público a usuários autenticados — não exige grant. O
`dados build` (mensal) roda com o usuário do Bruno, fora do SA.

## Front (sem framework)

`src/quimera/api/static/` entra como package-data; a app monta
`StaticFiles` e serve `/` (index) e `/metrics.html`. O site key do
Turnstile chega ao front por `GET /config` (JSON
`{"turnstile_site_key": "..."}`, sem cache, lido de `ApiConfig`). UI em
pt-BR, identificadores em inglês, responsivo e acessível no básico.

- **index.html:** caixa de pedido (≤ 500 chars), 4 exemplos clicáveis,
  widget Turnstile, tabela de resultado (empresa, local, CNAE, capital,
  porte, idade, score + motivos) e painel **"Como a Quimera decidiu"**
  (filtros extraídos, CNAEs com similaridade, SQL parametrizado, bytes,
  custo). Estados de erro com mensagem pt-BR: 422, 401, 429, 503 modo
  cache, 504. Badge de cache quando `cached: true`.
- **metrics.html:** tabelas da Fase 2 (extração, CNAE, e2e) renderizadas
  do `GET /metrics`; nota da regra de ouro (nada escrito à mão, tudo vem
  de `eval/results/`).

## Turnstile (server-side)

- `turnstile.py`: `verify(response, secret, remote_ip, *, client=None)
  -> bool` — POST em
  `https://challenges.cloudflare.com/turnstile/v0/siteverify` com
  `httpx` (cliente injetável; `MockTransport` nos testes). **Erro de
  rede → `False` (fail closed).** Sucesso exige `"success": true`.
- `ApiConfig` ganha `turnstile_secret_key` e `turnstile_site_key`
  (`TURNSTILE_SECRET_KEY`, `TURNSTILE_SITE_KEY`).
- `POST /leads` autentica com **X-Api-Token OU Turnstile**; o body ganha
  o campo opcional `turnstile: str`. Nenhum dos dois configurado →
  warning no log e liberado (ergonomia dev, igual ao `API_TOKEN`).
  Falha de autenticação → **401** (envelope `{"error", "reason"}`).
- Token é single-use: o front resolve o widget a cada envio; cache hit
  também exige token válido (e conta no rate limit).
- `httpx` entra no extra `api` (continua no `dev`; já é dependência do
  projeto).

## Dockerfile + .dockerignore

- `python:3.12-slim`, usuário não-root, `pip install .[api,gcp]`,
  `COPY eval/results/` + `eval/thresholds.json` → `/app/eval`
  (`EVAL_DIR=/app/eval`), `CMD python -m quimera.api`.
- `.dockerignore`: `.git`, **`.env`**, `tests/`, `docs/`, `probe_*.py`,
  `smoke_real.py`, `debug_snapshot.py`, `__pycache__/`, goldens de eval
  (só results + thresholds entram).

## scripts/deploy.sh (bash)

Idempotente, `--project/--region` com defaults `quimera-leads` /
`us-central1`:

1. Habilita APIs (`run`, `cloudbuild`, `artifactregistry`,
   `secretmanager`).
2. Cria repo `quimera` (docker) no Artifact Registry se faltar.
3. Cria secrets `quimera-api-token` / `quimera-turnstile-secret` se
   faltarem (valores passados como argumento/env; recusa valor vazio).
4. Cria SA `quimera-demo` + bindings (dataset via
   `bq add-iam-policy-binding quimera --member=... --role=roles/bigquery.dataViewer`).
5. `gcloud builds submit` → imagem no AR.
6. `gcloud run deploy quimera-demo` com as flags da seção Cloud Run.
7. Smoke test: `GET /health`, `GET /metrics`, `GET /` (HTML); imprime a
   URL final.
8. Alertas de orçamento 50/80/100%: tenta
   `gcloud beta billing budgets create`; sem permissão/indisponível,
   imprime os passos do console e segue (não bloqueia o deploy).

## Testes (sem GCP, sem rede)

- `tests/test_turnstile.py`: verify com `MockTransport` — sucesso,
   `success: false`, erro de rede → `False`.
- Extensões em `tests/test_api.py`: `/` serve HTML com form;
   `/metrics.html`; `GET /config` devolve o site key; `POST /leads` com
   Turnstile via verifier fake (token válido passa, inválido → 401,
   `X-Api-Token` continua passando).
- Docker/deploy: verificação manual documentada (`docker build .`
   local opcional + `scripts/deploy.sh` com smoke test).

## Docs

- `docs/deploy.md`: runbook (pré-requisitos, site key na Cloudflare,
   secrets, SA, budgets, domínio custom depois, troubleshooting).
- README: seção "Demo pública" (URL + uso), variáveis novas
  (`TURNSTILE_*`), roadmap 3b marcado como concluído.

## Limitações aceitas

- **Instância única:** uma segunda instância nunca sobe
  (`max-instances=1`); pico de tráfego espera na fila do Cloud Run em
  vez de escalar. Aceito para demo de portfólio.
- **Restart zera cache/rate limit/orçamento do processo** (estado em
  memória; `max-instances=1` mantém o resto válido). Reset de
  orçamento continua à meia-noite UTC.
- **Turnstile é o anti-abuso do front, não da API:** quem tiver o
  `API_TOKEN` continua chamando `/leads` direto (é o token de
  serviço).
- **Orçamento cobre só bytes do BigQuery** (decisão 3a); tokens do LLM
  ficam limitados por rate limit + Turnstile.
- **`gcloud beta billing budgets`** pode falhar conforme permissões da
  conta — o script degrada para instrução manual.

## Fora de escopo (registros explícitos)

- Firestore (estado compartilhado entre instâncias/restarts).
- Agendamento mensal do `python -m quimera.dados build` (item próprio
  do roadmap; Cloud Scheduler/Run job depois).
- Domínio custom, CI/CD, captcha alternativo, orçamento de tokens do
  LLM, modo privado (Fase 5).
