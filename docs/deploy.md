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
4. Componentes do SDK: `gcloud`, `bq`, `curl`. O caminho de orçamento usa
   `gcloud beta billing budgets` (componente `beta`).

## Testar a imagem localmente (opcional, antes do 1º deploy)

```bash
docker build -t quimera-demo:local .
docker run --rm -p 8080:8080 -e API_TOKEN=x -e PORT=8080 quimera-demo:local
curl -s http://localhost:8080/health
```

**`-e PORT=8080` é obrigatório aqui.** Em produção o Cloud Run injeta `PORT`
sozinho; local não — sem a variável, `python -m quimera.api` sobe em 8000 por
padrão e o `docker run -p 8080:8080` não alcança nada (`curl` cai em "Empty
reply from server"). `POST /leads` retorna 500 nesse teste local sem
`gcloud auth application-default login` (o cliente Gemini não acha
credencial) — esperado; só `/health`, `/config`, `/`, `/metrics*` e o 401
sem token validam sem GCP.

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

Se o Turnstile ainda não tiver a URL: rode o 1º deploy sem `TURNSTILE_*`,
copie a URL impressa, cadastre o hostname no Cloudflare e rode de novo com
as chaves.

**Segredos no shell:** a linha de comando acima deixa `API_TOKEN` e
`TURNSTILE_SECRET_KEY` no `~/.bash_history`. Em máquina compartilhada, prefira
um `secrets.env` fora do git (`chmod 600`) e `source` antes do deploy, ou
`set +o history` ao redor da invocação. Os valores nunca entram em argv do
`gcloud` (vão por stdin para o Secret Manager) nem em log do script.

## Re-deploy (só código)

`bash scripts/deploy.sh` — secrets/SA/bindings já existem; só build+deploy.

Para **rotacionar** um secret depois de criado (o script só cria uma vez):

```bash
printf '%s' "$NOVO_API_TOKEN" | gcloud secrets versions add quimera-api-token --data-file=-
```

Depois um re-deploy para a nova versão ser montada (`:latest`).

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

## Custos e tempo operacional

| Item | Medida | Fonte |
|---|---|---|
| Pedido típico (com CNAE) | 33–250 MB lidos; p50 ~110 MB | `docs/schema.md`, `eval/results/` |
| Pedido sem CNAE | pode passar de 2 GB (poda de cluster fraca, ainda aberta) | `docs/schema.md` |
| Latência por pedido | p50 ~3,7 s; p95 ~5–7 s (cauda = cota Gemini 429) | README, `eval/results/` |
| Teto por consulta | `MAX_BYTES_BILLED=5368709120` (5 GB) — acima disso, recusa | `deploy.sh` |
| Orçamento diário | `DAILY_BYTES_BUDGET=10737418240` (10 GB) — esgotado, entra em modo cache | `deploy.sh` |
| Build da tabela própria | ~US$ 0,10 por mês (1×/mês via `python -m quimera.dados build`) | README |
| Avaliação e2e completa | ~US$ 0,02 e ~2 min | README |
| Cenário de tráfego | 10 GB/dia de BigQuery on-demand ≈ US$ 6,25/TB → ~US$ 0,06/dia no teto do orçamento | estimativa |
| Cloud Run | escala a zero; só cobra execução (~1 CPU, 1 GiB, máx. 1 instância) | config do deploy |
| Alerta de gasto | `BUDGET_USD=20` com avisos em 50/80/100% | `deploy.sh` |

Escalas de segurança, da menor para a maior: teto por consulta (5 GB) →
orçamento diário (10 GB, vira cache) → rate limit (10 req/h/IP) → alerta de
billing (US$ 20).

## Registro do trabalho (Fase 3b — 2026-09-27)

**Tempo:** ~4 h 40 min de implementação contínua (12:37–17:18, 20 commits),
mais a conferência visual aprovada pelo Bruno. Testes unitários: 473
passando, sem GCP/rede; ruff limpo; smoke da imagem Docker local OK.

**Descrição do que foi feito:**

1. **API** — `query_sql` no resultado do pipeline (painel "como decidiu");
   config de Turnstile no ambiente; `turnstile.py` com verificação server-side
   fail-closed (caminho de produção testado, `raise_for_status`, close
   protegido); autenticação `X-Api-Token` **ou** Turnstile com precedência
   explícita e invariante de token single-use travado em teste; `GET /config`
   com a site key; suíte e2e em `GET /metrics`; migração para `lifespan`
   (obrigatória: fastapi 0.141+ removeu `add_event_handler`).
2. **Front** — laudo técnico numerado servido pela própria FastAPI:
   `index.html` + `style.css` + `app.js` (achados numerados em sequência,
   erros visíveis, desafio anti-bot com mensagem coerente) e o anexo
   `metrics.html` + `metrics.js` com as 3 tabelas medidas, carimbo
   "Avaliado" e seleção explícita do golden principal (27 casos — não o
   smoke de 1 caso). Acabamento pelo detector impeccable (1 achado
   corrigido) e conferência visual aprovada.
3. **Deploy** — `Dockerfile` (`python:3.12.11-slim-bookworm`, usuário
   não-root, `EVAL_DIR=/app/eval`), `.dockerignore` (`.env` nunca entra) e
   `scripts/deploy.sh` idempotente (Artifact Registry, Secret Manager, SA de
   menor privilégio, Cloud Build, Cloud Run com escala a zero, smoke test).

**Correções que a revisão de código obrigou** (além do previsto no plano):
erro de rede apagado antes de aparecer; ordem e buracos na numeração dos
achados; guardas contra DOM clobbering do Turnstile; anexo não afirma
"abaixo" quando nada foi medido; `try/finally` no lifespan; base da imagem
pinada; token do Turnstile limitado a 2048 chars antes de chegar no
verificador.

**Custo desta fase:** apenas tempo de máquina local + as medições em `eval/`
já existentes (~US$ 0,02 pela re-execução e2e). O deploy real (Task 13) é o
primeiro momento com gasto de GCP — ver a tabela de custos acima.

## Decisões registradas

- **`MemoryStateStore` é por instância.** Orçamento diário e rate limit
  vivem em memória e **resetam a cada cold start** (escala a zero). Com
  `max-instances=1` o comportamento é coerente, mas não confie no orçamento
  como teto duro de gasto — o alerta de billing é a rede de segurança final.
- **Amplificação do siteverify.** `POST /leads` roda a autenticação antes do
  rate limit (o 401 precisa vencer o 429 — testado). Isso significa que uma
  enxurrada de tokens inválidos gera uma chamada ao Cloudflare por request
  à frente do rate limit. Mitigação hoje: token limitado a 2048 chars,
  fail-closed e 5 s de timeout. Mitigação futura (se virar problema):
  cache negativo por IP ou rate limit de WAF na frente do Cloud Run.
- **Dependências da imagem sem lock.** A imagem resolve `fastapi>=0.115,<0.150`
  na hora do build; o teste local usa 0.128.8 e a imagem smoke-testada usou
  0.141.1 (ambas funcionam com `lifespan`). Para reprodutibilidade estrita,
  falta um `constraints.txt`/lock — aceito por simplicidade operacional por
  enquanto.
- **Fences do plano emendados na Task 7.** O `app.js`/`style.css` entregues
  divergem deliberadamente do fence do plano em pontos corrigidos pela
  revisão (mensagem de erro de rede, ordem dos achados, guards do Turnstile,
  foco do painel de erro). Quem re-gerar a partir do plano precisa portar
  essas correções.
- **Imagem guarda o índice CNAE duas vezes** (~27 MB: `COPY src/` +
  package-data do wheel). Aceito para manter o Dockerfile simples; uma build
  multi-stage resolveria junto com o cache de camadas.

## Troubleshooting

- **`docker run` local não responde em 8080**: falta `-e PORT=8080` — o
  Cloud Run injeta essa variável sozinho, `docker run` direto não (default é
  8000). Ver "Testar a imagem localmente" acima.
- **Cold start lento no 1º pedido**: warmup roda em background; `/health`
  responde imediatamente, o 1º pedido pode levar +2–3 s.
- **429 do Gemini (cauda de latência)**: cota em `us-central1`; ver README.
- **500 sem detalhe**: `gcloud logging read 'resource.type=cloud_run_revision
  resource.labels.service_name=quimera-demo' --limit 20 --project quimera-leads`.
- **Turnstile sempre falhando**: conferir hostname do widget (deve cobrir a
  URL `*.run.app`) e `TURNSTILE_SECRET_KEY` (versão `latest` do secret).
- **Tabela de leads indisponível**: rodar `python -m quimera.dados build`
  (mensal — agendamento é item próprio do roadmap).
- **Imagem quebra no boot com AttributeError**: a app exige a API `lifespan`
  (fastapi 0.141+ removeu `add_event_handler`); confira se o build não está
  com um pin antigo de fastapi.

## Domínio custom (depois)

Cloud Run > Domains > Add; apontar CNAME; re-registrar o hostname no
Turnstile. Sem re-deploy.
