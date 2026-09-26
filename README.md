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
             └─► [cnae] cnae_query → 15 candidatos (embeddings) → Gemini escolhe
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
python -m quimera.cnae fonte    # CNAE 2.3 + atividades do IBGE -> data/cnae_subclasses.jsonl
python -m quimera.cnae build    # índice multi-vetor -> data/cnae_index.npz (~7 min)

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
python -m eval.run_eval --suite e2e                   # só ponta a ponta (~2 min, ~US$ 0,02)
python -m eval.report                                 # relatório Markdown em eval/results/
```

- `eval/golden_e2e.jsonl` — 20 pedidos rodados no pipeline inteiro; cada
  empresa devolvida é conferida (UF, município, CNAE, idade, capital, porte)
  e todo resultado público checa as invariantes (sem pessoa física nem
  empresário individual, sem contato, uma linha por empresa, ordem de score).
- `eval/golden_extraction.jsonl` — 56 casos (46 públicos, 10 privados), incluindo
  recusas de dado pessoal, pedidos mistos, sinônimos, typos e ambiguidade.
  Rótulos `flag: review` revisados e validados (2026-09-26).
- `eval/golden_cnae.jsonl` — 66 casos linguagem natural → CNAE, **corrigidos
  contra as atividades oficiais do IBGE em 2026-09-26** (fonte:
  `src/quimera/data/cnae_subclasses.jsonl`; um teste garante que todo código
  aceitável existe na CNAE 2.3).
- `eval/thresholds.json` — limiares do CI (recusa correta = 100%, extração ≥ 85%;
  recall@5 ≥ 0,90; medido 0,955 em 2026-09-26).

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

**Ponta a ponta** — 20 pedidos, cada empresa devolvida conferida
(`eval/golden_e2e.jsonl`):

| versão | casos 100% corretos | precisão por empresa | recusa correta | p50 | p95 | MB/pedido |
|---|---|---|---|---|---|---|
| seleção por lista, extração recusava local fictício | 0,75 | 0,944 | 1,00 | 3,5 s | 6,0 s | 136 |
| **seleção por nota + extração corrigida** | **0,95** | **0,997** | 1,00 | 3,7 s | 7,0 s | 77 |

Único caso ainda falhando: "transportadoras de carga" inclui 2 de 50
empresas de outro modal. Limiares no CI: casos ≥ 0,90, precisão ≥ 0,98,
recusa = 1,00.

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
- [x] Ranking do ICP no SQL (antes: LIMIT devolvia amostra arbitrária) e um
      estabelecimento por empresa
- [x] Índice CNAE multi-vetor com atividades do IBGE + seleção pelo Gemini
- [x] Latência: ~25 s → ~4 s por pedido (clientes reaproveitados, caches,
      sem raciocínio no Gemini, aquecimento na inicialização)
- [x] Avaliação ponta a ponta com limiares no CI
- [ ] Cota do Gemini (429) — cauda de latência
- [ ] "empresas de TI": pedido genérico ainda falha na busca (único erro no top-15)
- [ ] Fase 5 — uso privado (repositório da Turno 24)
