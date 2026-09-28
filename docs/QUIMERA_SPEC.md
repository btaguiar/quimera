# QUIMERA — Especificação de construção

> Documento para um agente de código (ex.: Claude Code) construir o projeto do zero ou continuar o esqueleto existente.
> Leia tudo antes de escrever código. Onde houver **[CONFIRMAR]**, não invente: consulte a fonte (console do BigQuery, docs oficiais) ou pergunte ao Bruno.

---

## 1. O que é

**Quimera** é um agente que transforma um pedido em português ("clínicas odontológicas abertas há mais de 2 anos em Santo André, porte médio") em uma lista ranqueada de empresas, combinando:

1. **LLM (Gemini via Vertex AI)** para extrair filtros estruturados (JSON com schema fixo);
2. **Embeddings** para mapear linguagem natural → códigos CNAE;
3. **BigQuery** com a base pública de CNPJ (Base dos Dados) via query parametrizada;
4. **Score transparente** com explicação de cada resultado.

O nome vem da criatura mítica formada de partes distintas: aqui, LLM + embeddings + dados públicos.

### Dois usos, um núcleo

| | Público (portfólio) | Privado (Turno 24, empresa do Bruno) |
|---|---|---|
| Onde vive | Repositório GitHub público `quimera` + demo no Cloud Run | Dentro do repositório privado da Turno 24, pasta `prospeccao/` |
| Dados | Só dados de empresa. Sem MEI, sem contato, sem pessoa | Inclui MEI (flag), e-mail/telefone do estabelecimento |
| Destino | Página web com contagem, ranking, score, explicação | CRM **Twenty** (Empresas + Oportunidades etapa Lead) |
| Custo | Crédito GCP de teste (3 meses), com tetos duros | Roda no PC/VPS, dentro da cota gratuita do BigQuery quando possível |

### Por que existe (contexto do portfólio)

Bruno está montando portfólio de **AI Engineer**. Já tem `grifo` (RAG com citação e recusa), `pauta` (LangGraph multi-agente) e `cortex-multi-agent`. Falta demonstrar **dados + cloud + avaliação rigorosa**. O valor do Quimera **não** está em "gerar leads" (gênero saturado), e sim em ser um **sistema avaliado**, com números publicados: acerto de extração, recall do mapeamento de CNAE, recusa correta de pedidos de dado pessoal, bytes e custo por consulta.

> Regra de ouro: cada afirmação no README precisa ter uma métrica reproduzível em `eval/`.

---

## 2. Regras inegociáveis

1. **O LLM nunca escreve SQL** no fluxo de leads. Ele só preenche o schema `LeadFilters`. A query é escrita por nós, parametrizada.
2. **Teto de custo em toda consulta:** dry run obrigatório + `maximum_bytes_billed`. Se a estimativa passar do teto, recusar.
3. **A diferença entre público e privado vive em um único lugar:** `core/policy.py`. Nenhum outro módulo decide isso.
4. **Nada de dado pessoal no repositório público, no deploy público, em logs públicos ou em datasets de eval.** Nem por acidente.
5. **Sem CPF, sem endereço completo de pessoa física, sem cruzamento com redes sociais pessoais** em nenhum dos deploys.
6. **Opt-out sempre checado** antes de qualquer exportação privada.
7. **Segredos nunca no código.** Variáveis de ambiente / Secret Manager. Chaves de API separadas por ambiente.
8. **Não afirmar o que não foi medido.** Nomes de tabelas, colunas, códigos CNAE e códigos de natureza jurídica devem ser confirmados na fonte.
9. **Idioma:** código e identificadores em inglês; README, comentários de domínio e mensagens ao usuário em português do Brasil.

---

## 3. Estrutura de repositórios

```
quimera/                       # REPO PÚBLICO (github.com/btaguiar/quimera)
├── README.md
├── pyproject.toml
├── src/quimera/
│   ├── policy.py              # Policy PUBLIC / PRIVATE, apply_policy()
│   ├── filters.py             # LeadFilters, ExtractionResult (pydantic)
│   ├── extract.py             # Gemini -> ExtractionResult (saída estruturada)
│   ├── cnae.py                # índice de embeddings + busca
│   ├── query.py               # query parametrizada + dry run + teto
│   ├── score.py               # ICP e score explicável
│   ├── pipeline.py            # request -> resultado (orquestra tudo)
│   └── api/                   # FastAPI (só a versão pública roda isto)
├── eval/
│   ├── golden_extraction.jsonl
│   ├── golden_cnae.jsonl
│   ├── run_eval.py
│   └── report.py              # gera tabela/gráfico para o README e a página
├── tests/
├── Dockerfile
└── .github/workflows/         # CI: testes + eval com limiar

turno24/                       # REPO PRIVADO (já existe; NÃO publicar)
└── prospeccao/
    ├── export_twenty.py
    ├── blocklist.py
    ├── contact_quality.py
    ├── retention.py
    └── config_icp.py          # ICP da Turno 24 (nicho, pesos)
```

`prospeccao/` importa o núcleo: `pip install -e ../quimera` em desenvolvimento, ou `pip install git+https://github.com/btaguiar/quimera` em produção. Defina `DEPLOY_MODE=private` **apenas** no ambiente da Turno 24.

### Estado atual (já existe, precisa ser migrado)

Existe um esqueleto em `cnpj-leads/` (nome provisório) com: `core/{filters,policy,query,score,cnae,extract}.py`, `private/{blocklist,contact_quality,export_twenty,retention}.py`, `eval/{golden_set.jsonl,run_eval.py}`, `README.md`, `pyproject.toml`. Um smoke test já validou `policy`, `build_query` e `score_lead` (sem rodar contra BigQuery/Gemini/Twenty).

**Tarefas de migração:**
- Renomear pacote para `quimera` e adotar layout `src/quimera/`.
- Mover `private/` inteiro para o repo da Turno 24 (`prospeccao/`) e ajustar imports (`from quimera...`).
- Remover `private/` do repo público e do `.gitignore` (o `.gitignore` deixa de ser a única barreira).
- Ajustar `extract.py`: o prompt fala em `cnae_query`; o campo já foi adicionado em `LeadFilters`. Falta o passo que converte `cnae_query` em `cnae_codes` via `cnae.py` (ver Fase 1).

---

## 4. Fluxo

```
pedido (pt-BR)
  └─► [extract] Gemini (saída estruturada) → ExtractionResult
        ├─ refused=true → resposta de recusa com motivo
        └─ filters
             └─► [cnae] cnae_query → top-k CNAEs (embeddings) → mostrar ao usuário e permitir correção
                  └─► [policy] apply_policy(filters, policy)  # força limites do deploy
                       └─► [query] SQL parametrizado → dry run → execução com teto
                            └─► [score] score 0-100 + motivos legíveis
                                 └─► resposta: lista + CNAEs usados + bytes + custo estimado
```

Cada execução é registrada (pedido normalizado, filtros, bytes, latência, modelo, custo) em uma tabela de log própria **sem dado pessoal**.

---

## 5. Fases de construção

Cada fase termina com critérios de aceite verificáveis. Não avance sem cumpri-los.

### Fase 0: Descoberta do schema (bloqueia o resto)

Ambiente: PC do Bruno (WSL2) com `gcloud` autenticado.

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project <PROJETO>
bq ls basedosdados:br_me_cnpj
bq show --schema --format=prettyjson basedosdados:br_me_cnpj.estabelecimentos
bq show --schema --format=prettyjson basedosdados:br_me_cnpj.empresas
bq show --schema --format=prettyjson basedosdados:br_me_cnpj.simples
bq show --format=prettyjson basedosdados:br_me_cnpj.estabelecimentos   # ver partição/cluster, tamanho, location
```

Registrar em `docs/schema.md`: nomes reais de tabelas e colunas, tipos, partição/cluster, tamanho em GB, data da última atualização, **região do dataset**.
Descobrir também: tabela de CNAE (subclasse + descrição) e tabela de natureza jurídica (código de "Empresário Individual"; o esqueleto assume `2135`, **[CONFIRMAR]**).

**Aceite:** `docs/schema.md` existe e o `query.py` foi ajustado a ele. Um `dry run` da query base foi executado e os bytes estimados foram anotados.
**Atenção:** o job do BigQuery precisa rodar na **mesma região do dataset**; configurar `bigquery.Client(location=...)`.

### Fase 1: Núcleo (`src/quimera`)

1. **`filters.py`:** manter `LeadFilters` (com `cnae_query`, `cnae_codes`, `ufs`, `municipio_ids`, `min/max_age_years`, `min_capital`, `portes`, `include_mei`, `limit`) e `ExtractionResult`.
2. **`policy.py`:** `PUBLIC` (sem MEI, sem campos de pessoa, `max_rows=50`) e `PRIVATE` (`allow_mei`, campos de contato, `max_rows=1000`). `apply_policy` força os limites **depois** do LLM.
3. **`cnae.py`:** construir o índice (`python -m quimera.cnae build`) com embeddings da descrição de cada CNAE (Vertex AI `text-embedding-005` ou o disponível; **[CONFIRMAR]** modelo). `search(query, k)` devolve `(codigo, descricao, similaridade)`. Guardar o índice em arquivo versionável (ou baixar de um bucket).
4. **`extract.py`:** Gemini com `response_schema=ExtractionResult`, `temperature=0`. Prompt com regra diferente por policy (público recusa dado pessoal). Aceitar o modelo como parâmetro (necessário para o eval comparativo).
5. **`query.py`:** query parametrizada (já esboçada). Mapeamento de UF e município: o LLM devolve nome de município; resolver para código IBGE por **lookup em tabela de diretório** (não deixar o LLM inventar código). **[CONFIRMAR]** tabela de municípios na Base dos Dados.
6. **`score.py`:** regras simples e explicáveis. ICP configurável (dataclass). MEI com peso reduzido. Saída: `(score, motivos[])`.
7. **`pipeline.py`:** `run(request, policy) -> Result` encadeando extract → cnae → policy → query → score, com log.
8. **CLI:** `python -m quimera "pedido..." --mode public|private`.

**Aceite:**
- `pytest` passa (testes unitários de `policy`, `build_query`, `score`, validadores de `filters`, sem chamar GCP: usar mocks).
- Teste garante que, com `PUBLIC`, o SQL **não** contém colunas de contato e **contém** o filtro de MEI/empresário individual.
- Teste garante que `apply_policy` corta `limit` e desliga `include_mei` no público mesmo que o LLM peça o contrário.
- Uma execução real ponta a ponta no modo público devolve resultados, com bytes abaixo do teto.

### Fase 2: Avaliação (o coração do portfólio)

Construir `eval/` de modo que rode local e no CI. Todo resultado vai para `eval/results/*.json` com: commit, data, modelo, métricas, custo, latência.

**2.1 Extração de filtros** (`golden_extraction.jsonl`, meta ≥ 50 casos):
- Campos por caso: `request`, `expect` (filtros esperados ou `refused: true`).
- Métricas: acerto por campo (UF, faixa de idade, capital, porte), acerto exato do conjunto, taxa de recusa correta, taxa de recusa indevida (falso positivo).
- Incluir casos difíceis: ambiguidade ("empresas boas"), pedido misto (legítimo + dado pessoal), sinônimos ("dentistas", "consultório odontológico"), erros de digitação.

**2.2 Mapeamento CNAE** (`golden_cnae.jsonl`, meta ≥ 50 casos):
- Cada caso: descrição em linguagem natural → conjunto de CNAEs aceitáveis (rotular à mão, com revisão do Bruno).
- Métricas: **recall@1, recall@5, MRR**. Comparar ≥ 2 modelos de embedding e mostrar a tabela.

**2.3 Comparação de modelos de extração** (ex.: Gemini Flash vs Pro): acerto × latência p50/p95 × custo por 1.000 pedidos. Gráfico.

**2.4 Custo da consulta:** bytes médios e p95 por tipo de pedido; taxa de dry run rejeitado.

**2.5 Relatório:** `eval/report.py` gera Markdown/HTML com tabelas e gráficos a partir dos JSON de resultado. Esse relatório alimenta o README e a página pública.

**Limiares (falham o CI):** recusa correta = 100%; acerto de extração ≥ 85%; recall@5 de CNAE ≥ valor definido após a primeira medição (anotar o baseline, não inventar meta antes de medir).

**Aceite:** `python -m eval.run_eval` roda, grava resultados e retorna código ≠ 0 se algum limiar falhar. O relatório é gerado sem edição manual.

### Fase 3: Demo pública (Cloud Run)

- **API:** FastAPI com `POST /leads` (pedido → resultado) e `GET /health`. Resposta inclui: filtros extraídos, CNAEs escolhidos (com similaridade), lista, score e motivos, bytes processados.
- **Front:** página simples (HTML + JS, sem framework pesado) com caixa de pedido, exemplos clicáveis, tabela de resultado, painel "como a Quimera decidiu" (filtros, CNAEs, SQL parametrizado exibido, bytes).
- **Proteções obrigatórias:**
  - rate limit por IP;
  - orçamento diário global de bytes/tokens; ao estourar, entrar em **modo cache** (só responde pedidos já vistos);
  - cache por hash do pedido normalizado (Firestore);
  - captcha ou token simples contra abuso;
  - `maximum_bytes_billed` por consulta;
  - timeout e limite de linhas.
- **Segurança de GCP:** service account com o mínimo (`bigquery.jobUser` no projeto, `dataViewer` só nos datasets usados, `aiplatform.user`). Projeto GCP **separado** do uso privado. Alerta de orçamento em 50%/80%/100%.
- **Deploy:** `Dockerfile` + Cloud Run com `min-instances=0` (escala a zero, custo quase nulo depois do crédito). Secrets no Secret Manager.
- **Página de métricas** pública com os resultados da Fase 2.

**Aceite:** URL pública funcionando; pedido de dado pessoal ("telefone do dono") é recusado; rate limit e modo cache testados; custo por pedido registrado; nenhum campo de contato aparece em nenhuma resposta.

### Fase 4 (opcional, depois): modo analítico com SQL livre guardado

Para perguntas agregadas ("quantas clínicas abriram por ano em SP"): LLM gera SQL → `sqlglot` valida (só `SELECT`, tabelas na whitelist, sem `INFORMATION_SCHEMA`, sem múltiplos statements, `LIMIT` forçado) → dry run → execução com teto → em caso de erro, até 2 retentativas com a mensagem do erro. Golden set próprio com **execution accuracy** (comparar o resultado, não o texto do SQL). Só implementar depois das Fases 1-3 estarem entregues.

### Fase 5: Uso privado (repositório da Turno 24)

Vive em `turno24/prospeccao/`, fora do repo público.

- **`config_icp.py`:** ICP inicial de **clínicas** (recepção com voz e WhatsApp), nicho ainda em decisão até a semana 8 do plano da Turno 24; deixar configurável.
- **`export_twenty.py`:** cria Empresa e Oportunidade (etapa Lead) via API REST do Twenty, com `origemLead="CNPJ"`, `scoreLead`, `motivoScore`, `isMei`. Modo `dry_run` por padrão. **[CONFIRMAR]** nomes dos campos custom e formato de resposta da API na versão instalada. Nenhuma Pessoa é criada aqui (só quando o SDR qualificar).
- **`blocklist.py`:** opt-out por CNPJ raiz e por e-mail, aplicado antes de exportar.
- **`contact_quality.py`:** descartar e-mail de contabilidade e telefones/e-mails repetidos em muitos CNPJs; ampliar a lista com o uso.
- **`retention.py`:** apagar oportunidades em Lead, origem CNPJ, sem interação após 180 dias (job semanal).
- **Execução:** job Python no PC, depois na VPS (Coolify). Preferir materializar o resultado da extração (parquet ou tabela pequena) e importar dali, para não consultar o BigQuery por lead.
- **Dados de pessoa (decisão do Bruno, com limites):** e-mail/telefone do estabelecimento entram. Nome do sócio administrador (só pessoa jurídica que não seja MEI) pode entrar em **tabela separada e restrita**, nunca no repo, nunca no Twenty como Pessoa antes da qualificação. CPF e endereço completo nunca. **[CONFIRMAR com o Bruno]** antes de implementar o campo de sócio.
- **Documento de legítimo interesse** (`docs/legitimo-interesse.md` no repo privado): finalidade, dados usados, necessidade, canal de descadastro, prazo de retenção. Recomendar revisão jurídica antes de escalar volume.
- **Canal:** primeiro contato por e-mail (com identificação e descadastro), ligação ou Instagram. **WhatsApp frio pela Cloud API não**: a política da Meta exige opt-in para mensagem de marketing.

**Aceite:** dry run exporta N leads imprimindo Empresa + Oportunidade; leads bloqueados não saem; contato de contabilidade é removido; teste automatizado cobre bloqueio e limpeza de contato.

---

## 6. Guardrails (checklist de revisão)

- [ ] Nenhum SQL gerado por LLM no fluxo de leads.
- [ ] Toda consulta passa por dry run e `maximum_bytes_billed`.
- [ ] `apply_policy` é chamado antes de `build_query` em todos os caminhos.
- [ ] Público: sem MEI, sem colunas de contato, sem nome de pessoa.
- [ ] Recusa de pedidos de dado pessoal testada no golden set (100%).
- [ ] Logs sem dado pessoal.
- [ ] Rate limit, orçamento diário, cache e modo cache ativos.
- [ ] Service accounts com privilégio mínimo; projetos GCP público e privado separados.
- [ ] Alertas de billing configurados.
- [ ] Nenhum segredo commitado (rodar `gitleaks` ou equivalente no CI).
- [ ] README só afirma métricas presentes em `eval/results/`.

---

## 7. Variáveis de ambiente

```
GOOGLE_CLOUD_PROJECT=
BQ_LOCATION=                  # região do dataset [CONFIRMAR]
DEPLOY_MODE=                  # vazio = público; "private" só na Turno 24
VERTEX_LOCATION=
EXTRACT_MODEL=gemini-2.5-flash    # [CONFIRMAR] modelo disponível na conta
EMBED_MODEL=text-embedding-005    # [CONFIRMAR]
MAX_BYTES_BILLED=5368709120       # 5 GB; ajustar após dry runs
DAILY_BYTES_BUDGET=
RATE_LIMIT_PER_MIN=
# Somente privado (Turno 24):
TWENTY_URL=
TWENTY_API_KEY=
```

---

## 8. Testes

- **Unitários (sem rede):** `policy`, `filters` (validadores), `build_query` (cláusulas e parâmetros), `score`, `contact_quality`, `blocklist`.
- **Contrato:** `ExtractionResult` aceita/recusa JSON malformado do LLM (mockar resposta).
- **Integração (marcados, rodam sob demanda):** dry run real no BigQuery; extração real no Gemini.
- **Eval:** ver Fase 2. Roda no CI em cada push com limiares.

---

## 9. Definição de pronto (portfólio)

1. Repositório público `quimera` com README que explica o problema, a arquitetura (diagrama) e os resultados medidos.
2. Demo pública no Cloud Run com proteções ativas.
3. Página de métricas: acerto de extração, recusa correta, recall@k de CNAE por modelo, custo e latência, bytes por consulta.
4. CI verde com o eval e seus limiares.
5. Nenhum dado pessoal no repositório ou na demo.
6. Texto curto no README sobre decisões de projeto (por que o LLM não escreve SQL, por que a policy é um ponto único, como o custo é limitado).

## 10. Fora de escopo

- Envio de mensagens (e-mail, WhatsApp, LinkedIn).
- Scraping de redes sociais pessoais ou cruzamento com outras bases sobre pessoas.
- Automação de disparo em massa.
- Interface administrativa complexa.
- Qualquer dado de pessoa física na versão pública.

## 11. Ordem de execução resumida

`Fase 0 (schema)` → `Fase 1 (núcleo + testes)` → `Fase 2 (eval + relatório)` → `Fase 3 (Cloud Run)` → `Fase 5 (privado, em paralelo quando o núcleo estiver estável)` → `Fase 4 (opcional)`.

Ao terminar cada fase: rodar testes, atualizar o README com o que foi **medido**, e listar pendências e decisões abertas para o Bruno.
