# Quimera

> Agente que transforma um pedido em português ("clínicas odontológicas abertas
> há mais de 2 anos em Santo André, porte médio") em uma lista ranqueada de
> empresas (CNPJ), combinando LLM, embeddings e BigQuery.

**Status: Fase 3 no ar em modo privado (2026-09-27).** A demo roda no Cloud Run
com o aceite da spec cumprido, mas ainda sem acesso anônimo; a abertura ao
público depende dos itens em [Próximos passos](#próximos-passos). Este README só
afirma métricas com resultados reproduzíveis em `eval/` (regra de ouro do projeto).

## Como funciona

```
pedido (pt-BR)
  └─► [extract] Gemini (saída estruturada) → ExtractionResult
        ├─ refused=true → recusa com motivo
        └─ filters
             └─► [cnae] cnae_query → 15 candidatos (embeddings) → Gemini escolhe
                  └─► [policy] apply_policy — limites do deploy
                       └─► [query] SQL parametrizado (tabela própria) → estimativa → teto de bytes
                            └─► [score] 0-100 + motivos legíveis
```

Decisões de projeto (detalhes na especificação `docs/QUIMERA_SPEC.md`):

- **O LLM nunca escreve SQL.** Ele só preenche o schema `LeadFilters`; a query é
  nossa, parametrizada.
- **Público vs. privado vive em um único lugar:** `core/policy.py`. Nenhum outro
  módulo decide isso, e `apply_policy` roda sempre depois do LLM.
- **Teto de custo em toda consulta:** estimativa prévia obrigatória +
  `maximum_bytes_billed`; acima do teto, a consulta é recusada. O dry run não
  estima as tabelas de CNPJ, então a estimativa vem de uma sonda com teto de
  1 byte (recusada sem custo, informando os bytes exigidos).
- **Tabela própria, não consulta direta.** Consultar a Base dos Dados custa
  ~13 GB por pedido (filtros não reduzem bytes). `python -m quimera.dados build`
  materializa 1×/mês os ~27,8 M estabelecimentos ativos numa tabela
  particionada por divisão CNAE e clusterizada por UF/município/CNAE, com
  sinais do próprio cadastro — rede (nº de unidades ativas), regime
  tributário, bairro, coordenada por CEP e domínio de e-mail próprio, sem
  expor e-mail nem CEP — e checagens de qualidade antes de substituir a
  versão em uso. Um pedido com CNAE filtrado custa 33–250 MB. Sem atividade,
  o ranking precisa ler todas as empresas da região (1,6–2,5 GB em qualquer
  UF ou município), então a demo pública exige atividade no pedido
  (`Policy.require_activity`; medição e alternativas testadas em
  `docs/schema.md`).
- **Nota em faixa, não em degraus:** idade e capital pontuam gradualmente
  (idade de 2 a 10 anos; capital de R$ 50 mil a R$ 10 mi em escala log), e o
  capital perde nota acima do teto — empresa grande demais não é o cliente
  ideal. O SQL ordena pela mesma conta (`query._icp_ranking`), então a ordem
  do laudo é a da nota.
- **Filtros do cadastro, extraídos do pedido em português:** UF, município,
  bairro (com o município), raio a partir de um CEP, idade, capital social,
  porte, rede (nº mínimo de unidades), regime tributário (Simples, fora do
  Simples ou, no ambiente privado, MEI) e domínio de e-mail próprio como
  sinal de maturidade digital — nunca o e-mail em si.
- **Sempre o snapshot mensal mais recente**: o build lê só a última partição
  de cada tabela (sem isso, ~45 snapshots empilhados custariam ~132 GB e
  duplicariam cada empresa ~45×) e grava a data nos labels da tabela própria,
  lidos sem custo a cada pedido.
- **Sem dado pessoal** no deploy público, em logs ou em eval.

## Uso

```bash
pip install -e ".[gcp]"        # dependências GCP (import lazy nos módulos)

python -m quimera "clínicas odontológicas em Santo André abertas há mais de 2 anos" --mode public
python -m quimera "redes de academias em São Paulo com 5 ou mais unidades, fora do Simples" --mode public
python -m quimera "restaurantes num raio de 3 km do CEP 01310-100" --mode public
python -m quimera "pedido..." --json          # saída estruturada
python -m quimera.cnae fonte    # CNAE 2.3 + atividades do IBGE -> data/cnae_subclasses.jsonl
python -m quimera.cnae build    # índice multi-vetor -> data/cnae_index.npz (~7 min)

python -m quimera.dados build             # tabela própria (1×/mês, ~US$ 0,10)
python -m quimera.dados build --contatos  # + tabela de contatos (só ambiente privado)
python -m quimera.dados status            # snapshot, linhas e tamanho (sem custo)
```

Servidor da demo (API):

```bash
python -m quimera.api            # uvicorn em 0.0.0.0:8000 (PORT/API_HOST)
# POST /leads   {"request": "...", "turnstile": "..."} → filtros, CNAEs,
#               ranking, SQL, bytes, custo (auth: X-Api-Token OU Turnstile)
# GET  /health  → status, versão, orçamento restante, modo cache
# GET  /config  → site key pública do Turnstile (para o front)
# GET  /metrics → resultados medidos da Fase 2 (JSON)
```

Proteções da API pública: token opcional (`API_TOKEN`), rate limit por IP
(`RATE_LIMIT_MAX`/`RATE_LIMIT_WINDOW_S`; IP = último hop do `X-Forwarded-For`),
cache por hash do pedido normalizado (`CACHE_TTL_S`), orçamento diário de
bytes com modo cache (`DAILY_BYTES_BUDGET`) e timeout por request
(`REQUEST_TIMEOUT_S`).

### Demo pública (Cloud Run)

Deploy: `bash scripts/deploy.sh` (runbook em `docs/deploy.md`, incluindo
Cloudflare Turnstile, service account mínimo, alertas de orçamento, tabela de
custos por pedido e o registro do trabalho da Fase 3b). O front é React
(Vite + TypeScript, código em `frontend/`): pedido →
resultado em seções (interpretação, CNAEs, SQL, ranking, custos, ressalvas)
e a página `/metricas` com as métricas medidas (`/metrics.html` redireciona
para ela). O bundle é gerado por `npm run build` em
`src/quimera/api/static/` (fora do git) e entra na imagem pelo estágio Node
do Dockerfile.

Hoje o serviço está no ar **privado** (`PUBLIC_ACCESS=false`: só abre com
login Google e permissão de invoker). Para ver no navegador:
`gcloud run services proxy quimera-demo --region us-central1 --project
quimera-leads` e abrir `http://127.0.0.1:8080`. O registro do deploy real,
os bugs que ele revelou e como testar pela linha de comando estão em
`docs/deploy.md`.

Variáveis de ambiente: `GOOGLE_CLOUD_PROJECT`, `BQ_LOCATION`, `VERTEX_LOCATION`,
`EXTRACT_MODEL`, `EMBED_MODEL`, `MAX_BYTES_BILLED`, `LEADS_DATASET` (dataset da
tabela própria; padrão `quimera`), `DEPLOY_MODE` (vazio =
público; `private` só no ambiente da Turno 24), `API_TOKEN`, `RATE_LIMIT_MAX`,
`RATE_LIMIT_WINDOW_S`, `CACHE_TTL_S`, `DAILY_BYTES_BUDGET`,
`REQUEST_TIMEOUT_S`, `EVAL_DIR`, `TURNSTILE_SITE_KEY` (público, no HTML),
`TURNSTILE_SECRET_KEY` (Secret Manager; verifica o token do front).

## Desenvolvimento

```bash
pip install -e ".[dev,gcp]"
python -m pytest              # testes unitários, sem chamar GCP
```

`scripts/deploy.sh` faz o deploy (runbook em `docs/deploy.md`).
`scripts/diagnostico/` guarda as sondas usadas nas medições de
`docs/schema.md` (rodam contra o BigQuery real e têm custo).

## Avaliação

```bash
python -m eval.run_eval --suite all --policy public   # golden sets + limiares (requer GCP)
python -m eval.run_eval --suite e2e                   # só ponta a ponta (~2 min, ~US$ 0,02)
python -m eval.report                                 # relatório Markdown em eval/results/
```

Se o eval ou a CLI ficarem parados sem saída, confira o IPv6 da máquina: numa
rede que resolve IPv6 mas não roteia, a chamada ao Gemini fica presa em
`socket.create_connection` (sem timeout) tentando os endereços IPv6 do Vertex
antes dos IPv4. Medido nesta máquina em 2026-09-28: IPv6 dá timeout, IPv4
conecta em 0,02 s. Corrija o IPv6 (ou dê preferência a IPv4 no Windows); no
Cloud Run não acontece.

- `eval/golden_e2e.jsonl` — 28 pedidos rodados no pipeline inteiro (o 28º,
  pedido sem atividade que a policy pública não executa, entrou em
  2026-09-28 e passou; as tabelas abaixo medem os 27 anteriores); cada
  empresa devolvida é conferida (UF, município, CNAE, idade, capital, porte,
  rede, regime, bairro, raio, domínio próprio) e todo resultado público checa
  as invariantes (sem pessoa física nem empresário individual, sem contato
  nem coordenada nem CEP, uma linha por empresa, ordem de score).
- `eval/golden_extraction.jsonl` — 56 casos (46 públicos, 10 privados), incluindo
  recusas de dado pessoal, pedidos mistos, sinônimos, typos e ambiguidade.
  Rótulos `flag: review` revisados e validados (2026-09-26).
- `eval/golden_cnae.jsonl` — 66 casos linguagem natural → CNAE, **corrigidos
  contra as atividades oficiais do IBGE em 2026-09-26** (fonte:
  `src/quimera/data/cnae_subclasses.jsonl`; um teste garante que todo código
  aceitável existe na CNAE 2.3).
- `eval/thresholds.json` — limiares (recusa correta = 100%, extração ≥ 85%;
  recall@5 ≥ 0,90; medido 0,955 em 2026-09-26). Abaixo de qualquer limiar,
  `run_eval` sai com código ≠ 0 — pronto para CI, mas **ainda não há CI
  configurado** (ver Próximos passos).

## Resultados medidos (2026-09-26, ponta a ponta atualizado em 2026-09-27 — `eval/results/`)

Primeira medição real contra GCP, com os rótulos de CNAE já revisados.

**Extração de filtros** — `gemini-2.5-flash`, 45 casos públicos (re-executada
após ajuste no prompt de extração para eliminar recusas indevidas):

| métrica | valor | limiar |
|---|---|---|
| recusa correta (dado pessoal) | 100% | 100% |
| acerto por campo | 89,9% | ≥ 85% |
| acerto exato do conjunto | 77,8% | — |
| recusa indevida | 0,0% (era 5,7%) | — |
| latência p50 / p95 | 4,6 s / 7,4 s | — |

**Mapeamento CNAE** — 66 casos, golden **corrigido contra a lista oficial de
atividades do IBGE** em 2026-09-26 (17 rótulos estavam errados: códigos
inexistentes, obsoletos ou trocados, ex.: "dentistas" → 8630-5/01 em vez de
8630-5/04):

| índice (text-embedding-005) | recall@1 | recall@5 | MRR |
|---|---|---|---|
| antigo: 1356 descrições, com 24 códigos fora da CNAE 2.3 | 0,576 | 0,803 | 0,669 |
| **multi-vetor: 1332 subclasses 2.3 + 17 mil atividades IBGE** | **0,758** | **0,955** | **0,831** |

Seleção final (quais candidatos viram filtro da consulta):

| estratégia | acerto | precisão | cobertura | códigos | p50 |
|---|---|---|---|---|---|
| top-5 fixo (antes) | 0,955 | 0,227 | 0,864 | 5,0 | — |
| **Gemini escolhe entre 15 candidatos** | **0,985** | **0,645** | **0,930** | 2,95 | 0,87 s |

Seleção atual: o Gemini dá nota 0–2 a cada candidato e só a nota 2 vira
filtro — precisão **0,849**, acerto 0,970, cobertura 0,875, p50 0,82 s.
Se a chamada falhar (429 de cota, timeout de 4 s), cai no corte por
similaridade (top1 − 0,04).

Precisão = fração dos códigos escolhidos que estão no golden (o golden lista
o mínimo correto, então é um piso). Detalhes em `docs/schema.md`.

**Ponta a ponta** (`eval/golden_e2e.jsonl`), cada empresa devolvida conferida:

| versão | casos | casos 100% corretos | precisão por empresa | recusa correta | p50 | p95 | MB/pedido (p50) |
|---|---|---|---|---|---|---|---|
| seleção por lista, extração recusava local fictício | 20 | 0,75 | 0,944 | 1,00 | 3,5 s | 6,0 s | 136 |
| seleção por nota + extração corrigida | 20 | 0,95 | 0,997 | 1,00 | 3,7 s | 7,0 s | 77 |
| **+ Onda 1 (rede, regime, bairro, raio, domínio próprio)** | 27 | **0,926** | **0,990** | 1,00 | 3,5 s | 5,2 s | 110 |
| + UF junto do município (2026-09-30) | 28 | 0,964 | 0,957 | 1,00 | 4,2 s | — | — |
| **+ nova tentativa na seleção de CNAE (2026-09-30)** | 28 | **1,000** | **1,000** | 1,00 | 3,9 s | — | — |
| + reescrita da atividade e filtros lidos do texto (2026-10-01) | 28 | 0,964 | 0,995 | 1,00 | 4,1 s | — | — |

Na 1ª medição de 2026-09-30 a única falha foi `e2e_026`: a chamada de
seleção de CNAE falhou (cota) e o plano B — corte por similaridade do
embedding — pôs representantes comerciais em 1º para "material de
construção". Seis variantes de corte testadas em 322 casos com gabarito não
ganharam do atual em acerto; a correção foi tentar a seleção uma 2ª vez
(pausa de 0,5 s, timeout de 4 s por chamada) antes do plano B. Plano B no
piloto sintético de 500 casos: 2,2% → 0%.
Os 7 casos novos da Onda 1 passaram todos; os 2 casos que falharam já
falhavam antes (ambiguidade de seleção de CNAE, não é regressão da Onda 1 —
`docs/schema.md`). Limiares: casos ≥ 0,90, precisão ≥ 0,98, recusa =
1,00.

**Conjunto separado** (`eval/golden_e2e_holdout.jsonl`) — 30 pedidos com
atividades e cidades fora de todos os goldens, rótulos commitados antes da
1ª execução. Os 20 casos acima serviram para ajustar o prompt; este mede
generalização:

| execução | casos | casos 100% corretos | precisão por empresa |
|---|---|---|---|
| 1ª execução, inédita (medida honesta) | 30 | 0,900 | 0,942 |
| após busca híbrida (já não é inédito) | 30 | 0,933 | 0,960 |
| + Onda 1 (3 casos novos) | 33 | 0,909 | 0,945 |
| + UF junto do município (2026-09-30) | 33 | 0,909 | 0,952 |
| + reescrita da atividade e filtros lidos do texto (2026-10-01) | 33 | 0,909 | 0,952 |

A precisão do conjunto separado nunca atingiu a mesma barra do golden
principal (0,942 a 0,96, sempre por ambiguidade de seleção de CNAE, mesmo
antes da Onda 1) — o eval usa um limiar próprio para este conjunto
(`eval/thresholds.json`: `e2e_holdout_row_precision` 0,92), em vez do limiar
0,98 do golden principal. Todas as falhas restantes são de CNAE (UF,
município, idade, capital e porte: 100%).
A 1ª execução mostrou: "borracharias" confundido com artigos de borracha
pelo embedding (corrigido com busca por palavra somada ao embedding);
variação do Gemini entre chamadas em casos de fronteira (seed não resolve);
"cervejarias artesanais" ambíguo — o Gemini inclui bares de cerveja, uso
comum no Brasil, e o rótulo (estrito, mantido) não. "Joalherias" inclui a
fabricação de joias: a regra "fabricantes/fornecedores recebem no máximo 1"
foi restaurada no prompt, mas o Gemini sem raciocínio a ignora nesse caso
(métricas iguais: golden CNAE 0,970/0,819/0,895; ajuste 0,95/0,997;
separado 0,933/0,960).

**Golden sintético** (`eval/golden_e2e_sintetico.jsonl`) — 10.000 pedidos
gerados por `eval/sintetico/gerar.py`, para medir com amostra grande o que os
28 + 33 casos curados medem com intervalo largo (28 casos: ±15 pontos; e a
mesma configuração variou 7 pontos entre duas rodadas). Como é feito:

- **O gabarito nunca vem de um LLM.** Cada caso nasce de um template:
  atividade de um catálogo curado (`eval/sintetico/atividades.jsonl`, 159
  atividades, códigos conferidos nas atividades oficiais do IBGE) × local ×
  filtros. O `expect` sai do próprio template.
- **Todo caso "com resultado" tem empresas de verdade.** Um censo na tabela de
  leads (mesmas exclusões do público; ~US$ 0,02) conta empresas por atividade ×
  município × filtro, só no CNAE **principal** de cada atividade; a célula
  entra com 5 ou mais empresas.
- **O Gemini só reescreve a frase.** A paráfrase é descartada se perder
  cidade, UF, número, bairro, CEP ou a atividade, ou se inverter o sentido
  ("fora do Simples" → "do Simples"); 97% passaram.
- Tipos: cidade (29%), cidade + 1 filtro (28%), + 2 filtros (8%), bairro,
  raio por CEP, UF, homônimo sem UF, pedido de dado pessoal, cidade fictícia,
  pedido sem atividade. Até 200 empresas conferidas por caso.

```bash
python -m eval.sintetico.gerar censo                          # BigQuery, ~4 min
python -m eval.sintetico.gerar golden --total 10000 --n 10000 # paráfrases, ~45 min
python -m eval.run_eval --suite e2e --golden golden_e2e_sintetico.jsonl \
  --max-rows 200 --workers 4 --checkpoint /tmp/ckpt.jsonl     # ~2h30, ~US$ 7 de BigQuery
```

Resultado (2026-09-30, 10.000 casos, 379.962 empresas):

| métrica | valor | limiar |
|---|---|---|
| casos 100% corretos | **0,920** (IC95 0,915–0,925) | ≥ 0,90 |
| precisão por empresa | 0,960 | ≥ 0,95 |
| recusa de dado pessoal | 1,000 (719 de 719) | = 1,00 |
| recusa indevida | 2 casos | — |
| seleção de CNAE no plano B (cota do Gemini) | 2,4% | — |
| casos corretos sem os do plano B | 0,927 | — |
| p50 / p95 | 3,5 s / 5,5 s | — |

Das 800 falhas: 300 são CNAE extra ou errado na seleção; 173 são termos que
não acham CNAE nenhum ("botecos", "docerias", "lojas de pneus"); 93 são
cervejaria ≠ bar e joalheria ≠ fabricação, rótulos mantidos estritos como no
holdout (um terço das empresas erradas); 83 são o plano B por cota; 62 são a
extração perdendo um filtro em pedidos com dois (capital mínimo é o mais
perdido: 92,8% das empresas conferidas). Pedidos com dois filtros acertam
0,863; com um, 0,907; sem filtro, 0,93. 56 das 159 atividades acertam 100%;
as piores são "empresas de TI" (0,21), cervejarias (0,37) e indústria de
alimentos (0,40).

O golden sintético achou dois bugs, corrigidos em 2026-09-29: UF colada no
nome da cidade ("Extrema/MG", "Ouro (SC)") virava "município não encontrado",
e UF escrita depois de uma cidade homônima ("pousadas em Valença, BA") era
ignorada quando a extração não a devolvia. Uma terceira mudança (mostrar
primeiro os exemplos do IBGE que citam o pedido, na seleção de CNAE) melhorou
a seleção isolada e piorou o ponta a ponta no A/B — foi revertida.

**Correções guiadas pelas 800 falhas (2026-09-30)** — orçamento de US$ 8,
gasto ~US$ 7. Três mudanças no pipeline, cada uma mirando um grupo de erros:

| causa no golden de 10 mil | casos | consertados | mudança |
|---|---|---|---|
| termo informal sem CNAE ("botecos", "sacolões", "empresas de TI") | 173 | 151 (87%) | seleção vazia → Gemini reescreve a atividade no vocabulário da CNAE e busca de novo |
| extração perdia a última condição ("fora do Simples **e** com capital…") | 62 | 56 (90%) | idade e capital vazios lidos do texto do pedido (0 falsos positivos em 10.061 pedidos); pedir no prompt piorou (94,2% → 88,7%) e foi revertido |
| seleção de CNAE no plano B por cota | 83 | 73 (88%) | 2ª tentativa antes do plano B |

Medição sem viés: as correções saíram das falhas do golden de 10 mil, então
o número que vale é o de **1.000 pedidos inéditos** (`eval/golden_e2e_inedito.jsonl`,
outra semente, nenhum pedido nem template repetido):

| conjunto | casos corretos | precisão por empresa | recusa correta |
|---|---|---|---|
| golden de 10 mil, pipeline antigo | 0,920 (IC95 0,915–0,925) | 0,960 | 1,00 |
| **1.000 inéditos, pipeline novo** | **0,954 (IC95 0,939–0,965)** | **0,965** | **1,00** |

O reteste dos mesmos casos (as 800 falhas + 2.000 acertos sorteados como
controle) estima 0,946 para os 10 mil com o pipeline novo; o controle manteve
98,8% (24 regressões, 21 sem relação com as mudanças — variação do Gemini).

Os goldens curados não pioraram: principal 0,964 / 0,995 (a única falha,
`e2e_026`, com 6 de 50 empresas fora) e separado 0,909 / 0,952, igual ao
anterior. Reteste em `eval/golden_e2e_reteste.jsonl`.

Rótulos corrigidos à parte, só com confirmação no texto do IBGE (abate de
equinos/ovinos/bufalinos/suínos em "frigoríficos", facção de roupas em
"confecções", alimentos dietéticos e moagem em "indústrias de alimentos",
aquecimento solar em "energia solar"): +0,3 ponto nos inéditos, +0,8 no
golden de 10 mil. "Cervejarias" (bares) e "joalherias" (fabricação) seguem
estritos.

**Latência** (servidor aquecido): p50 ~3,7–5 s por pedido, antes ~25 s. O
tempo por etapa vem em `timings_ms` no resultado. A cauda (p95 ~7 s, picos
de 10–20 s) é o Gemini esperando cota (429 em `us-central1`); resolve no
GCP (cota/capacidade reservada), não no código.

## Roadmap

- [x] Fase 0 — schema validado no BigQuery (`docs/schema.md`; pendências resolvidas)
- [x] Auditoria de qualidade dos dados (`docs/schema.md`: porte, pessoa física,
      homônimos, idade, capital, filiais, contabilidade de bytes)
- [x] Tabela própria `quimera.estabelecimentos_ativos` com checagens de
      qualidade no build (custo por pedido: ~13 GB → 70–500 MB)
- [x] Onda 1 — sinais do próprio cadastro: rede, regime tributário, bairro,
      raio por CEP e domínio próprio (`docs/schema.md`)
  - [x] pedidos sem CNAE caros (1,6–2,5 GB): não era poda nem maturação da
        tabela, e sim o pedido sem atividade; o público agora exige
        atividade (2026-09-28, `docs/schema.md`)
- [x] Fase 1 — núcleo (`filters`, `policy`, `cnae`, `extract`, `query`, `score`, `pipeline`, CLI) + testes
- [x] Fase 2 — infraestrutura de avaliação (`eval/`: golden sets, métricas, limiares, relatório)
- [x] Primeira medição real (extraction + CNAE) e baseline de recall@5 (0,742)
- [x] Revisão dos rótulos `flag: review` do golden CNAE contra a CNAE 2.3
- [x] Revisão dos 5 rótulos `flag: review` restantes (golden de extração, Bruno)
- [ ] Fase 3 — demo pública no Cloud Run
  - [x] 3a — API + proteções (FastAPI: token, rate limit, orçamento diário
        com modo cache, timeout; `src/quimera/api/`)
  - [x] 3b — front (HTML+JS), Dockerfile, deploy, Secret Manager
  - [x] front novo em React (dark) + trava de CEP no ar (2026-09-29,
        revisão `quimera-demo-00008`; pedido real com CEP: 50 empresas,
        168 MB, 10,8 s com cold start)
  - [x] deploy real em modo privado + aceite da spec (2026-09-27;
        registro em `docs/deploy.md`)
  - [x] nota em faixa alvo: idade e capital graduais, capital acima de
        R$ 10 mi perde nota (2026-09-28; antes metade empatava em 100)
  - [x] re-deploy com a nota nova e a exigência de atividade (2026-09-28,
        revisão `quimera-demo-00007`)
  - [ ] abertura ao público (Turnstile real, `PUBLIC_ACCESS=true`, URL aqui)
  - [ ] agendar `python -m quimera.dados build` mensal (Cloud Scheduler/Run job)
- [x] Ranking do ICP no SQL (antes: LIMIT devolvia amostra arbitrária) e um
      estabelecimento por empresa
- [x] Índice CNAE multi-vetor com atividades do IBGE + seleção pelo Gemini
- [x] Latência: ~25 s → ~4 s por pedido (clientes reaproveitados, caches,
      sem raciocínio no Gemini, aquecimento na inicialização)
- [x] Avaliação ponta a ponta com limiares (`run_eval` sai ≠ 0 abaixo deles)
- [ ] Repositório público no GitHub + CI (testes, eval com limiares, gitleaks)
- [ ] Cota do Gemini (429) — cauda de latência
- [ ] "empresas de TI": pedido genérico ainda falha na busca (único erro no top-15)
- [ ] Fase 5 — uso privado (repositório da Turno 24)
- [ ] Fase 4 (opcional, depois da 5) — modo analítico com SQL livre validado

## Próximos passos

Em ordem de prioridade. O primeiro vem antes da abertura ao público
(item 2), porque é o que um visitante veria.

Feitos em 2026-09-28: a nota em faixa alvo (antes metade das empresas
empatava em 100 e uma operadora de R$ 207 mi aparecia em 1º num pedido de
clínicas; agora fica com 69, abaixo das clínicas estabelecidas) e a exigência
de atividade no público (pedidos sem CNAE custavam 1,6–2,5 GB). Eval
ponta a ponta depois das duas mudanças: casos 0,926 (igual), precisão 0,985
(limiar 0,98).

Validado no serviço no ar (revisão `quimera-demo-00007`, 2026-09-28): no
pedido de clínicas em Santo André, 17 notas distintas entre 50 empresas
(antes 2) e a operadora de R$ 207 mi fora do top 50; "empresas em Santo
André" volta o aviso sem consultar (0 bytes).

1. ~~**O LLM inventa CEP.**~~ **Feito (2026-09-29):** o pipeline só aceita
   CEP escrito no próprio pedido (`ceps_no_pedido`), como já se faz com o
   CNAE; o inventado é descartado com aviso e o raio cai no aviso de "CEP de
   referência". Medido com o Gemini real: em 5 execuções do e2e_027 ele
   inventou 80000000 uma vez, e o pedido voltou com 50 padarias de Curitiba
   em vez de vazio; o e2e_024 (CEP escrito) segue com raio de 3 km. Custo do
   e2e_027 sem raio: 520–585 MB (a cidade inteira).
2. **Abrir ao público.** Criar o widget no Cloudflare para `*.run.app`,
   rodar `scripts/deploy.sh` com `PUBLIC_ACCESS=true` e as chaves reais (isso
   também remove as chaves de teste do Turnstile que estão ativas no serviço
   privado) e anotar a URL aqui. Fecha a Fase 3.
3. **Repositório público e CI.** A definição de pronto da spec pede o repo
   público no GitHub e CI verde com o eval; hoje o repositório é só local, sem
   remoto. O CI precisa rodar `pytest`, o eval com os limiares (exige
   credencial GCP e custa ~US$ 0,02 por execução) e `gitleaks` — antes do
   primeiro push, para nenhum segredo entrar no histórico público.
4. **Build mensal agendado.** Cloud Scheduler disparando um Cloud Run job com
   `python -m quimera.dados build`; sem isso a tabela própria envelhece e a
   demo mostra um snapshot cada vez mais velho.
5. **Qualidade restante:** cota do Gemini (429, cauda p95 de 5–7 s; resolve
   com cota/capacidade no GCP) e o pedido genérico "empresas de TI".
6. **Fase 5 — uso privado** na Turno 24 (`docs/QUIMERA_SPEC.md`), e só depois a
   Fase 4 opcional.

Decisões aceitas por simplicidade, a revisitar só se virarem problema
(detalhes em `docs/deploy.md`): cache, orçamento diário e rate limit em
memória (`MemoryStateStore`), que zeram a cada cold start — a spec previa
Firestore, que entra pelo mesmo protocolo de `src/quimera/api/state.py`;
dependências da imagem sem lock; índice CNAE duplicado na imagem (~27 MB).

## Licença

Código sob licença MIT (`LICENSE`). Os dados de empresas vêm do cadastro
público de CNPJ da Receita Federal, lido pela Base dos Dados
(`basedosdados.br_me_cnpj`), e não fazem parte deste repositório; a demo
pública não exibe nenhum dado pessoal (sem MEI, sem pessoa física, sem
contato).
