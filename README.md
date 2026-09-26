# Quimera

> Agente que transforma um pedido em português ("clínicas odontológicas abertas
> há mais de 2 anos em Santo André, porte médio") em uma lista ranqueada de
> empresas (CNPJ), combinando LLM, embeddings e BigQuery.

**Status: em construção (Fase 2 medida — baseline real abaixo).** Este README só
afirma métricas com resultados reproduzíveis em `eval/` (regra de ouro do projeto).

## Como funciona

```
pedido (pt-BR)
  └─► [extract] Gemini (saída estruturada) → ExtractionResult
        ├─ refused=true → recusa com motivo
        └─ filters
             └─► [cnae] cnae_query → top-k CNAEs (embeddings)
                  └─► [policy] apply_policy — limites do deploy
                       └─► [query] SQL parametrizado (tabela própria) → estimativa → teto de bytes
                            └─► [score] 0-100 + motivos legíveis
```

Decisões de projeto (detalhes na especificação `QUIMERA_SPEC.md`):

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
  checagens de qualidade antes de substituir a versão em uso. Um pedido típico
  passa a custar 70–500 MB (medições em `docs/schema.md`).
- **Sempre o snapshot mensal mais recente**: o build lê só a última partição
  de cada tabela (sem isso, ~45 snapshots empilhados custariam ~132 GB e
  duplicariam cada empresa ~45×) e grava a data nos labels da tabela própria,
  lidos sem custo a cada pedido.
- **Sem dado pessoal** no deploy público, em logs ou em eval.

## Uso

```bash
pip install -e ".[gcp]"        # dependências GCP (import lazy nos módulos)

python -m quimera "clínicas odontológicas em Santo André abertas há mais de 2 anos" --mode public
python -m quimera "pedido..." --json          # saída estruturada
python -m quimera.cnae build --fonte pares.jsonl   # índice de embeddings CNAE

python -m quimera.dados build             # tabela própria (1×/mês, ~US$ 0,10)
python -m quimera.dados build --contatos  # + tabela de contatos (só ambiente privado)
python -m quimera.dados status            # snapshot, linhas e tamanho (sem custo)
```

Servidor da demo (API):

```bash
python -m quimera.api            # uvicorn em 0.0.0.0:8000 (PORT/API_HOST)
# POST /leads   {"request": "..."} → filtros, CNAEs, ranking, bytes, custo
#               (header X-Api-Token quando API_TOKEN estiver definido)
# GET  /health  → status, versão, orçamento restante, modo cache
# GET  /metrics → resultados medidos da Fase 2 (JSON)
```

Proteções da API pública: token opcional (`API_TOKEN`), rate limit por IP
(`RATE_LIMIT_MAX`/`RATE_LIMIT_WINDOW_S`; IP = último hop do `X-Forwarded-For`),
cache por hash do pedido normalizado (`CACHE_TTL_S`), orçamento diário de
bytes com modo cache (`DAILY_BYTES_BUDGET`) e timeout por request
(`REQUEST_TIMEOUT_S`).

Variáveis de ambiente: `GOOGLE_CLOUD_PROJECT`, `BQ_LOCATION`, `VERTEX_LOCATION`,
`EXTRACT_MODEL`, `EMBED_MODEL`, `MAX_BYTES_BILLED`, `LEADS_DATASET` (dataset da
tabela própria; padrão `quimera`), `DEPLOY_MODE` (vazio =
público; `private` só no ambiente da Turno 24), `API_TOKEN`, `RATE_LIMIT_MAX`,
`RATE_LIMIT_WINDOW_S`, `CACHE_TTL_S`, `DAILY_BYTES_BUDGET`,
`REQUEST_TIMEOUT_S`, `EVAL_DIR`.

## Desenvolvimento

```bash
pip install -e ".[dev,gcp]"
python -m pytest              # testes unitários, sem chamar GCP
```

## Avaliação

```bash
python -m eval.run_eval --suite all --policy public   # golden sets + limiares (requer GCP)
python -m eval.report                                 # relatório Markdown em eval/results/
```

- `eval/golden_extraction.jsonl` — 55 casos (45 públicos, 10 privados), incluindo
  recusas de dado pessoal, pedidos mistos, sinônimos, typos e ambiguidade.
  Rótulos `flag: review` revisados e validados (2026-09-26).
- `eval/golden_cnae.jsonl` — 66 casos linguagem natural → CNAE, com os 23
  rótulos `flag: review` **revisados contra a CNAE 2.3 em 2026-09-26** (fonte:
  diretório `br_bd_diretorios_brasil.cnae_2`).
- `eval/thresholds.json` — limiares do CI (recusa correta = 100%, extração ≥ 85%;
  recall@5 ≥ 0,74 = baseline medido em 2026-09-26).

## Resultados medidos (2026-09-26, `eval/results/`)

Primeira medição real contra GCP, com os rótulos de CNAE já revisados.

**Extração de filtros** — `gemini-2.5-flash`, 45 casos públicos (re-executada
após ajuste no prompt de extração para eliminar recusas indevidas):

| métrica | valor | limiar CI |
|---|---|---|
| recusa correta (dado pessoal) | 100% | 100% |
| acerto por campo | 89,9% | ≥ 85% |
| acerto exato do conjunto | 77,8% | — |
| recusa indevida | 0,0% (era 5,7%) | — |
| latência p50 / p95 | 4,6 s / 7,4 s | — |

**Mapeamento CNAE** — 66 casos, comparação de modelos de embedding:

| modelo | recall@1 | recall@5 | MRR | p50 (ms) |
|---|---|---|---|---|
| text-embedding-005 | 0,485 | 0,742 | 0,570 | 731 |
| text-embedding-004 | 0,424 | 0,697 | 0,518 | 769 |

`text-embedding-005` venceu as três métricas e é o modelo padrão do índice
(`src/quimera/data/cnae_index.jsonl`, 1356 subclasses da CNAE 2.3 geradas a
partir do diretório `br_bd_diretorios_brasil.cnae_2`).

## Roadmap

- [x] Fase 0 — schema validado no BigQuery (`docs/schema.md`; pendências resolvidas)
- [x] Auditoria de qualidade dos dados (`docs/schema.md`: porte, pessoa física,
      homônimos, idade, capital, filiais, contabilidade de bytes)
- [x] Tabela própria `quimera.estabelecimentos_ativos` com checagens de
      qualidade no build (custo por pedido: ~13 GB → 70–500 MB)
- [x] Fase 1 — núcleo (`filters`, `policy`, `cnae`, `extract`, `query`, `score`, `pipeline`, CLI) + testes
- [x] Fase 2 — infraestrutura de avaliação (`eval/`: golden sets, métricas, limiares, relatório)
- [x] Primeira medição real (extraction + CNAE) e baseline de recall@5 (0,742)
- [x] Revisão dos rótulos `flag: review` do golden CNAE contra a CNAE 2.3
- [x] Revisão dos 5 rótulos `flag: review` restantes (golden de extração, Bruno)
- [ ] Fase 3 — demo pública no Cloud Run
  - [x] 3a — API + proteções (FastAPI: token, rate limit, orçamento diário
        com modo cache, timeout; `src/quimera/api/`)
  - [ ] 3b — front (HTML+JS), Dockerfile, deploy, Secret Manager
  - [ ] agendar `python -m quimera.dados build` mensal (Cloud Scheduler/Run job)
- [ ] Fase 5 — uso privado (repositório da Turno 24)
