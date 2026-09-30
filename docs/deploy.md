# Deploy da demo pública (Fase 3b)

Runbook para colocar e manter a demo no ar. O script `scripts/deploy.sh`
automatiza quase tudo; este documento explica cada peça e o que fazer quando
algo falha.

**Estado atual (2026-09-29):** no ar em modo **privado** (serviço
`quimera-demo`, `us-central1`, projeto `quimera-leads`, revisão
`quimera-demo-00008` com o front React e a trava de CEP), com o aceite da spec
cumprido. **Chaves de teste do Turnstile ativas** (aprovam qualquer desafio):
aceitável só enquanto o serviço é privado; o deploy público com as chaves
reais as substitui. Orçamento de R$ 100 com alertas 50/80/100%, restrito ao
projeto. Detalhes em "Registro do deploy real".

## Pré-requisitos (uma vez)

1. **gcloud** autenticado no WSL2 (ou git-bash):
   `gcloud auth login && gcloud auth application-default login`.
   O script é bash: no Windows, rode no Git Bash ou no WSL, não no PowerShell
   (ver Troubleshooting).
2. **Projeto GCP** `quimera-leads` com billing ativo (crédito de teste).
3. **Turnstile (Cloudflare)**: dashboard > Turnstile > Add site.
   Hostnames: `quimera-leads.web.app` e `quimera-leads.firebaseapp.com` (o
   endereço público via Firebase Hosting). Sem Firebase, `*.run.app`. Widget "Managed". Guarde o **Site Key** (público) e o
   **Secret Key** (vai para o Secret Manager).
4. Componentes do SDK: `gcloud`, `bq`, `curl`. O caminho de orçamento usa
   `gcloud beta billing budgets` (componente `beta`).

## Firebase Hosting (endereço público)

Desde 2026-09-30 o endereço público é **https://quimera-leads.web.app**: o
Firebase Hosting (projeto `quimera-leads`, o mesmo do Cloud Run) serve o
front pela CDN e repassa `/leads`, `/metrics`, `/config` e `/health` ao
serviço `quimera-demo` (`firebase.json`). O front usa caminhos relativos,
então nada muda no código dele. App Web registrado: `quimera-web`
(`1:1077923511370:web:2ed63799a2c1cfcf01bab3`), sem SDK no front enquanto
nenhum recurso do Firebase for usado.

- **O repasse exige o Cloud Run público** (`--allow-unauthenticated`): com o
  serviço privado, o Firebase recebe 403 nas rotas da API (medido num canal
  de pré-visualização). Por isso `deploy.sh` só publica o Hosting com
  `PUBLIC_ACCESS=true`.
- **IP do visitante:** atrás do Firebase, o último hop do `X-Forwarded-For`
  é o servidor do Firebase, o mesmo para todos, e o limite por IP viraria
  global. O IP real vem em `Fastly-Client-IP`; o deploy liga
  `TRUST_FASTLY_CLIENT_IP=true`. Quem chamar o `run.app` direto pode forjar
  esse cabeçalho, mas cada `/leads` ainda exige um token novo do Turnstile e
  o orçamento diário continua valendo.
- Só o front: `npx -y firebase-tools@latest deploy --only hosting --project quimera-leads`
  (o `predeploy` roda `npm run build`). Pré-visualização sem tocar no
  endereço principal: `npx -y firebase-tools@latest hosting:channel:deploy <nome> --expires 7d`.

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
BUDGET=100 \
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

**Deploy privado (validar antes de abrir ao público):** `PUBLIC_ACCESS=false
bash scripts/deploy.sh` remove `--allow-unauthenticated` — o Cloud Run passa
a exigir IAM invoker, então só quem tiver `roles/run.invoker` (ou for owner
do projeto) consegue chamar a URL. O smoke test do próprio script já usa
`gcloud auth print-identity-token` nesse modo; para testar manualmente:

```bash
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$URL/health"
```

Quando estiver pronto para abrir ao público, re-deploy com
`PUBLIC_ACCESS=true bash scripts/deploy.sh` (é o default — não precisa
passar a variável). Nesse modo o Turnstile deixa de fazer sentido como
proteção: sem acesso anônimo, ninguém de fora chega no formulário para
verificar.

**Segredos no shell:** a linha de comando acima deixa `API_TOKEN` e
`TURNSTILE_SECRET_KEY` no `~/.bash_history`. Em máquina compartilhada, prefira
um `secrets.env` fora do git (`chmod 600`) e `source` antes do deploy, ou
`set +o history` ao redor da invocação. Os valores nunca entram em argv do
`gcloud` (vão por stdin para o Secret Manager) nem em log do script.

## Re-deploy (só código)

`bash scripts/deploy.sh` — secrets/SA/bindings já existem; só build+deploy.

**Enquanto o serviço for privado com as chaves de teste, não use o script
para re-deploy de código.** Ele tem `PUBLIC_ACCESS=true` por padrão (abriria
o serviço) e usa `--set-env-vars`, que substitui todas as variáveis: as
chaves de teste do Turnstile foram postas como variáveis de ambiente (não
existe `quimera-turnstile-secret` no Secret Manager) e sumiriam, e todo
pedido do navegador passaria a dar 401. Troque só a imagem, que preserva
variáveis, secrets, IAM e escala (foi assim a revisão 00008, 2026-09-29):

```bash
TAG="$(date -u +%Y%m%dT%H%M%SZ)"
IMAGE="us-central1-docker.pkg.dev/quimera-leads/quimera/quimera-demo:${TAG}"
gcloud builds submit --project=quimera-leads --region=us-central1 --tag="$IMAGE" .
gcloud run deploy quimera-demo --project=quimera-leads --region=us-central1 --image="$IMAGE"
```

Em máquina com IPv6 quebrado (o `gcloud` leva minutos por chamada), rode com
`CLOUDSDK_PYTHON_SITEPACKAGES=1` e um `sitecustomize.py` no `PYTHONPATH` que
force IPv4 (`socket.getaddrinfo` com `AF_INET`); sem a primeira variável o
`gcloud` usa `python -S` e ignora o `sitecustomize`.

Para **rotacionar** um secret depois de criado (o script só cria uma vez):

```bash
printf '%s' "$NOVO_API_TOKEN" | gcloud secrets versions add quimera-api-token --data-file=-
```

Depois um re-deploy para a nova versão ser montada (`:latest`).

## Alertas de orçamento

`BUDGET=100` cria alertas 50/80/100% (uma vez só: re-deploy não duplica).
A moeda é `BUDGET_CURRENCY` (padrão `BRL`) e **tem de ser a da conta de
billing** — `20USD` numa conta em BRL volta `INVALID_ARGUMENT`. Sem permissão
de billing? Console:
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
| Pedido sem atividade (sem CNAE) | 1,6–2,5 GB se executado; no público não executa (`require_activity`) — custo 0 | `docs/schema.md` |
| Latência por pedido | p50 ~3,7 s; p95 ~5–7 s (cauda = cota Gemini 429) | README, `eval/results/` |
| Teto por consulta | `MAX_BYTES_BILLED=5368709120` (5 GB) — acima disso, recusa | `deploy.sh` |
| Orçamento diário | `DAILY_BYTES_BUDGET=10737418240` (10 GB) — esgotado, entra em modo cache | `deploy.sh` |
| Build da tabela própria | ~US$ 0,10 por mês (1×/mês via `python -m quimera.dados build`) | README |
| Avaliação e2e completa | ~US$ 0,02 e ~2 min | README |
| Cenário de tráfego | 10 GB/dia de BigQuery on-demand ≈ US$ 6,25/TB → ~US$ 0,06/dia no teto do orçamento | estimativa |
| Cloud Run | escala a zero; só cobra execução (~1 CPU, 1 GiB, máx. 1 instância) | config do deploy |
| Alerta de gasto | `BUDGET=100` (R$) com avisos em 50/80/100% | `deploy.sh` |

Escalas de segurança, da menor para a maior: teto por consulta (5 GB) →
orçamento diário (10 GB, vira cache) → rate limit (10 req/h/IP) → alerta de
billing (R$ 100).

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

## Registro do deploy real (Task 13 — 2026-09-27)

**Tempo:** ~1 h 30 min (18:22–19:50), do teste local da imagem à validação
no navegador. Rodado pelo Git Bash no Windows, com `PUBLIC_ACCESS=false`.

**Aceite da spec Fase 3, medido contra o serviço no ar:**

| Verificação | Resultado |
|---|---|
| Sem identity token | 403 (serviço privado) |
| `/health`, laudo em `/`, `/metrics.html` | 200 |
| `/metrics` | 8 limiares; 7 + 6 + 11 medições (extração, CNAE, e2e) |
| "telefone do dono de clínicas em SP" | 200, `refused: true` |
| Pedido real (clínicas em Santo André) | 200, 50 empresas, 156 MB cobrados, ~US$ 0,0009 |
| Mesmo pedido repetido | 200, `cached: true`, ~0,35 s |
| 11º pedido do mesmo IP na hora | 429 |
| Campos de contato nas respostas | nenhum |
| Custo por pedido no Cloud Logging | registrado (bytes, custo, latência, linhas) |
| Fluxo pelo navegador (Turnstile de teste) | laudo completo; pipeline 4,4 s, navegador 5,0 s |

Não verificado neste deploy: o modo cache por orçamento esgotado (exige
re-deploy com `DAILY_BYTES_BUDGET` baixo; coberto pelos testes unitários).

**Bugs que só o deploy real revelou (todos corrigidos):**

1. `gcloud services enable` não aceita o nome curto `artifactregistry` →
   nomes completos `*.googleapis.com`.
2. `bq add-iam-policy-binding` em dataset exige allowlist do Google →
   `GRANT ... ON SCHEMA` via `bq query`.
3. O Git Bash converteu `EVAL_DIR=/app/eval` em
   `C:/Program Files/Git/app/eval`, e o `/metrics` de produção voltou vazio →
   a variável saiu do script (o Dockerfile já a define).
4. O `logger.info` do pipeline era descartado (ninguém configurava o logging
   da aplicação), então o custo por pedido não chegava ao Cloud Logging →
   `logging.basicConfig` no `__main__`.
5. Orçamento em `USD` numa conta em `BRL` → `INVALID_ARGUMENT`. Agora
   `BUDGET` + `BUDGET_CURRENCY`, com filtro no projeto (sem ele o orçamento
   somava a conta de billing inteira) e checagem de existência (o `create`
   não é idempotente).

Também veio à tona um problema de produto, não de deploy: o ranking quase não
diferencia as empresas (ver Próximos passos no README).

**Como testar o serviço privado:**

- Navegador: `gcloud run services proxy quimera-demo --region us-central1
  --project quimera-leads` e abrir `http://127.0.0.1:8080` (use o IP; o proxy
  escuta só em IPv4). O botão "Emitir laudo" precisa do Turnstile.
- Linha de comando (PowerShell): identity token no `Authorization` e o
  `X-Api-Token` do Secret Manager; mande o corpo em bytes UTF-8, senão os
  acentos quebram o JSON:

```powershell
$id  = gcloud auth print-identity-token
$tok = gcloud secrets versions access latest --secret=quimera-api-token --project quimera-leads
$body = [Text.Encoding]::UTF8.GetBytes('{"request":"padarias artesanais em Curitiba"}')
Invoke-RestMethod -Method Post -Uri https://quimera-demo-mcftihctrq-uc.a.run.app/leads `
  -Headers @{ Authorization = "Bearer $id"; "X-Api-Token" = $tok } `
  -ContentType "application/json; charset=utf-8" -Body $body
```

**Custo:** dezenas de pedidos de teste a menos de US$ 0,01 cada, mais os
builds no Cloud Build — centavos no total.

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

- **`This feature requires allowlisting` no IAM do dataset**: é o
  `bq add-iam-policy-binding` em dataset (preview, só para projetos
  liberados). O script usa `GRANT ... ON SCHEMA` via `bq query`, que é o
  caminho suportado.
- **PowerShell: `O termo 'API_TOKEN=...' não é reconhecido`**: `VAR=valor
  comando` é sintaxe bash. No PowerShell, defina `$env:VAR="valor"` antes e
  chame o Git Bash pelo caminho completo
  (`& "C:\Program Files\Git\bin\bash.exe" scripts/deploy.sh`). O `bash` puro
  do PowerShell abre o WSL, onde o `gcloud` pode não estar autenticado.
- **PowerShell junta variáveis em `--update-env-vars A=1,B=2`**: sem aspas,
  a vírgula vira separador de lista e tudo cai num só valor. Use aspas:
  `--update-env-vars "A=1,B=2"`.
- **Anexo de métricas vazio em produção (Git Bash)**: o Git Bash converte
  argumentos iniciados em `/` em caminhos do Windows (`/app/eval` virou
  `C:/Program Files/Git/app/eval`). Por isso o script não passa caminhos em
  `--set-env-vars`; `EVAL_DIR` vem do `ENV` do Dockerfile. `MSYS_NO_PATHCONV=1`
  não serve de atalho: quebra o wrapper do próprio `gcloud`.
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
