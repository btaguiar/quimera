# Schema real — Fase 0

Validado em 2026-09-25 contra o BigQuery, projeto `quimera-leads`.
Fonte: dataset público `basedosdados.br_me_cnpj` (**location `US`**).

Método: `bq show --schema` para colunas/tipos e a tabela `dicionario` para
valores codificados. Nada aqui é suposição — o que não pôde ser verificado
está marcado como **PENDENTE**.

## Tabelas

| Referência no código | Existe | Observação |
|---|---|---|
| `br_me_cnpj.estabelecimentos` | sim | particionada por dia (`data`), clusterizada por `ano, mes` |
| `br_me_cnpj.empresas` | sim | particionada por dia (`data`), clusterizada por `ano, mes` |
| `br_me_cnpj.simples` | sim | **não** particionada |
| `br_bd_diretorios_brasil.municipio` | sim | diretório de municípios; coluna de nome é `nome` |

Também existem `socios` e `dicionario` no dataset.

## Snapshots mensais — o ponto mais importante

`estabelecimentos` tem **3.241.945.742 linhas / 678 GiB**, porque empilha ~45
snapshots mensais. O universo real de um mês é ~72 M:

| partição | linhas |
|---|---|
| 2026-07-12 (mais recente) | 72.318.968 |
| 2026-06-14 | 71.874.448 |
| 2026-05-10 | 71.314.053 |

`empresas` segue o mesmo padrão (mais recente 2026-07-12, 69.059.702 linhas).

Consequência: **toda query precisa filtrar `data`**. Sem isso, cada empresa
aparece ~45 vezes no resultado e o custo explode. Medido por dry run/execução:

| consulta | bytes |
|---|---|
| 4 colunas de `empresas`, sem filtro de partição | **132 GB** |
| agregado trivial em `empresas`, 1 partição | **1,65 GB** |

~80× de diferença. `LIMIT` **não** reduz bytes escaneados — `LIMIT 3` custou os
mesmos 132 GB.

## Colunas confirmadas

### `estabelecimentos`
`ano` INTEGER · `mes` INTEGER · `data` DATE · `cnpj` STRING · `cnpj_basico` STRING ·
`cnpj_ordem` STRING · `cnpj_dv` STRING · `identificador_matriz_filial` STRING ·
`nome_fantasia` STRING · `situacao_cadastral` STRING · `data_situacao_cadastral` DATE ·
`motivo_situacao_cadastral` STRING · `data_inicio_atividade` **DATE** ·
`cnae_fiscal_principal` STRING · `cnae_fiscal_secundaria` STRING · `sigla_uf` STRING ·
`id_municipio` STRING · `id_municipio_rf` STRING · endereço (`tipo_logradouro`,
`logradouro`, `numero`, `complemento`, `bairro`, `cep`) · `ddd_1` · `telefone_1` ·
`ddd_2` · `telefone_2` · `ddd_fax` · `fax` · **`email`** · `situacao_especial` ·
`data_situacao_especial`

### `empresas`
`ano` · `mes` · `data` DATE · `cnpj_basico` STRING · `razao_social` STRING ·
`natureza_juridica` STRING · `qualificacao_responsavel` STRING ·
`capital_social` **FLOAT** · `porte` STRING · `ente_federativo` STRING

### `simples`
`cnpj_basico` STRING · `opcao_simples` **INTEGER** · `data_opcao_simples` DATE ·
`data_exclusao_simples` DATE · `opcao_mei` **INTEGER** · `data_opcao_mei` DATE ·
`data_exclusao_mei` DATE

## Valores codificados (via `dicionario`)

`situacao_cadastral` — chave é de **1 dígito**, sem zero à esquerda:

| chave | valor |
|---|---|
| 1 | Nula |
| **2** | **Ativa** |
| 3 | Suspensa |
| 4 | Inapta |
| 8 | Baixada |

`porte`:

| chave | valor |
|---|---|
| 0 | Não Informado |
| 1 | Micro Empresa |
| 3 | Empresa De Pequeno Porte |
| 5 | Demais |

`identificador_matriz_filial`: 1 = Matriz, 2 = Filial.

O `dicionario` cobre **apenas**: `empresas.porte`, `empresas.qualificacao_responsavel`,
`estabelecimentos.id_pais`, `estabelecimentos.identificador_matriz_filial`,
`estabelecimentos.motivo_situacao_cadastral`, `estabelecimentos.situacao_cadastral`,
e quatro colunas de `socios`.

## Correções aplicadas em `query.py`

| Constante | Era | É |
|---|---|---|
| `SITUACAO_CADASTRAL_ATIVA` | `"02"` | `"2"` |
| `COL_CORREIO_ELETRONICO` | `"correio_eletronico"` | `"email"` |

Confirmados como já corretos: todos os nomes de tabela, `cnpj_basico`,
`situacao_cadastral`, `sigla_uf`, `id_municipio`, `nome` (diretório),
`cnae_fiscal_principal`, `data_inicio_atividade`, `capital_social`, `porte`,
`razao_social`, `nome_fantasia`, `natureza_juridica`, `opcao_mei`, `telefone_1`.

## Pendências da Fase 0 — todas resolvidas (2026-09-26)

1. **`NATUREZA_EMPRESARIO_INDIVIDUAL = "2135"`** — confirmado no diretório
   `br_bd_diretorios_brasil.natureza_juridica` (`2135 = "Empresário (Individual)"`).
2. **`porte` não tem "média" nem "grande"** — a coluna só distingue Micro /
   Pequeno Porte / Demais. Decisão: `media` e `grande` viram `'5'` **restrito a
   natureza jurídica 2xxx** (entidade empresarial), e o resultado traz um aviso
   de que médio e grande são indistinguíveis. Sem a restrição, "empresa média"
   devolvia sobretudo associação, condomínio e igreja (ver qualidade abaixo).
3. **`opcao_mei` é INTEGER 0/1** — medido: `simples` tem 49,9 M linhas e 49,9 M
   `cnpj_basico` distintos (o LEFT JOIN não duplica). Distribuição
   (`opcao_mei`, `opcao_simples`): (0,0) 24,3 M · (1,1) 17,3 M · (0,1) 8,2 M ·
   (1,0) 477.
4. **O BigQuery não informa bytes nas tabelas de CNPJ** — nem no dry run, nem
   no job real, nem em `INFORMATION_SCHEMA.JOBS` (`total_bytes_billed = None`).
   O `maximum_bytes_billed` **é respeitado** (testado com teto de 10 MB:
   recusado). A recusa informa o custo: `"N or higher required"`. `run_query`
   usa isso como estimativa: sonda com `maximum_bytes_billed=1` (recusada sem
   custo, ~1,6 s), compara N com o teto e contabiliza N quando o job não
   reporta bytes — senão o orçamento diário da API nunca baixava.

## Achados de 2026-09-26 (primeira medição real)

- **O panorama de partições mudou.** `MAX(data)` de `estabelecimentos` agora é
  **2026-01-11**; a partição 2026-07-12 (mais recente na validação original)
  não existe mais — a Base dos Dados reorganizou os snapshots. A descoberta por
  janelas de `resolve_latest_snapshots` (hoje só no build) absorve a mudança
  sem intervenção. A base está ~8,5 meses atrás da data de hoje — o snapshot
  vem no resultado (`snapshot`) para quem usa o lead saber a idade do dado.
- **`cnae_fiscal_principal` guarda o código SEM máscara** (`"8630501"`), enquanto
  o formato oficial CNAE 2.3 é `"8630-5/01"`. `query.py` normaliza na fronteira
  (`_unmask_cnae`); filters, índice de embeddings e golden set seguem no formato
  oficial. Existe código placeholder na base (`"8888888"`, ~1,8 M estabelecimentos).
- **Fonte dos CNAEs**: `br_bd_diretorios_brasil.cnae_2` (1356 subclasses de 7
  dígitos) — usada para gerar o índice de embeddings.
- **Modelos validados na conta** (Vertex AI, `us-central1`): `gemini-2.5-flash`,
  `text-embedding-004` (768 dim), `text-embedding-005` (768 dim),
  `gemini-embedding-001` (3072 dim).

## Custo real por consulta (medido 2026-09-26, snapshot 2026-01-11)

As tabelas são clusterizadas só por `ano, mes`: filtros de UF, município e
CNAE **não reduzem bytes**. Cada coluna lida custa a coluna inteira da
partição (~1,8–4 GB por coluna, contando o overhead da partição).

| consulta | bytes |
|---|---|
| `build_query` antes desta revisão (qualquer filtro) | **11,86 GB** |
| `build_query` atual (+ `cnpj`, matriz/filial) | **13,17 GB** |
| teto padrão `MAX_BYTES_BILLED` | 5 GiB |

**Consequência: com o teto padrão, toda consulta de leads era recusada.** O
dry run sem estimativa escondia isso. Custo on-demand ≈ US$ 0,08 por consulta.
Além disso, `resolve_latest_snapshots` rodava a cada pedido (lê a coluna
`data`, ~1,6 GiB por partição por tabela).

## Tabela própria `quimera.estabelecimentos_ativos` (2026-09-26)

`python -m quimera.dados build` grava os estabelecimentos **ativos** do
snapshot mais recente, já cruzados com `empresas`, `simples` e o diretório de
municípios. 27.784.536 linhas, 4,25 GB, build em ~45 s (~US$ 0,10).

- **Partição por divisão CNAE** (`cnae_divisao`, 2 primeiros dígitos). O
  BigQuery aplica `maximum_bytes_billed` sobre a estimativa pré-execução, e a
  estimativa só enxerga poda de partição. Só com clusterização, toda consulta
  estimava 4,03 GB (tabela inteira) e custava ~100 MB — um teto de 500 MB
  recusava tudo (testado). A poda funciona com `IN UNNEST(@param)`.
- **Clusterização** por `sigla_uf, id_municipio, cnae_fiscal_principal`.
- **Snapshot nos labels** (`snapshot_est`, `snapshot_emp`): o pipeline lê via
  `get_table`, sem custo, em vez de descobrir o snapshot a cada pedido.
- **Checagens antes de publicar**: o build grava `_staging`, checa volume
  (≥ 20 M), `cnpj` único e com 14 dígitos, UF presente, município ausente
  ≤ 1%, CNAE com 7 dígitos, início de atividade válido, `opcao_mei` ∈ {0,1},
  porte presente — e só então copia sobre a tabela final. Falhou, a versão em
  uso fica intacta.
- **Sem contato.** `--contatos` grava `contatos_ativos` (só ambiente privado),
  com telefone = `ddd_1 || telefone_1` — a base guarda o número sem DDD.

Custo medido por pedido (teto necessário / cobrado):

| pedido | estimado | cobrado |
|---|---|---|
| odontologia (div. 86) + UF + município | 136 MB | 70 MB |
| varejo (div. 47) + UF | 812 MB | 221 MB |
| 3 divisões CNAE | 633 MB | 633 MB |
| só UF (sem CNAE) | 4,03 GB | 10 MB |
| pipeline completo, 5 CNAEs em 4 divisões | — | 487 MB (US$ 0,003) |

## Qualidade dos dados (medida 2026-09-26, snapshot 2026-01-11)

`estabelecimentos` (69,2 M linhas; `cnpj` único por linha):

| situação | linhas |
|---|---|
| 8 Baixada | 32,3 M |
| **2 Ativa** | **27,8 M** |
| 4 Inapta | 8,7 M |
| 3 Suspensa | 0,3 M |
| 1 Nula | 0,1 M |

Entre as **ativas**: 1,33 M filiais (por isso o resultado traz `cnpj` de 14
dígitos e `matriz_filial` — com só `cnpj_basico` saíam linhas repetidas);
79 mil sem `id_municipio` (0,3%); 10 mil com CNAE placeholder `8888888` (não
está no índice de embeddings, logo nunca é filtrado); 0 sem
`data_inicio_atividade`, 0 com data futura, 4 anteriores a 1900; 0 CNAE
malformado. 2.452 ativos sem linha em `empresas` (somem no JOIN).

`empresas` (66,0 M linhas; `cnpj_basico` único): 42,5 M são 2135 (Empresário
Individual). `capital_social`: 0 nulos, **17,5 M com 0** (= não informado),
4,5 M entre R$ 1 e R$ 99, **124 com o sentinela 999.999.999.999** — 0 e o
sentinela são tratados como "não informado" no score e o sentinela é excluído
do filtro de capital mínimo. Não há teto seguro abaixo disso: há capitais
legítimos acima de R$ 100 bi.

Porte × natureza jurídica (estabelecimentos ativos):

| natureza (1º dígito) | porte 1 Micro | porte 3 EPP | porte 5 Demais |
|---|---|---|---|
| 1 administração pública | — | — | 84 mil |
| **2 entidade empresarial** | 22,2 M | 1,54 M | **1,88 M** |
| 3 sem fins lucrativos | 15 | 3 | 1,33 M |
| **4 pessoa física** | 2 | 1 | **698 mil** |
| 5 organização internacional | — | — | 589 |

- Porte "Demais" ativo: só 47% é entidade empresarial; o resto é associação
  (3999), condomínio (3085), organização religiosa (3220), produtor rural
  pessoa física (4120), órgão público. 90% das empresas "Demais" têm capital 0.
- **Natureza 4xxx é pessoa física** (4120 produtor rural = 692 mil ativos). O
  deploy público excluía só 2135 — agora exclui toda natureza 4xxx
  (`Policy.allow_pessoa_fisica`).

Diretório de municípios: **233 nomes se repetem entre UFs** (Bom Jesus e São
Domingos em 5 UFs; **Santo André em SP e na PB**). O lookup guardava um id por
nome (o último lido, arbitrário); agora devolve todos, restritos às UFs do
pedido quando houver, com aviso de ambiguidade. Município não encontrado não
amplia mais a busca para o país inteiro: a consulta não é executada.

Idade: `DATE_DIFF(CURRENT_DATE(), inicio, YEAR)` conta viradas de ano
(31/12/2024 → 26/09/2026 = "2 anos"). O filtro agora compara com
`DATE_SUB(CURRENT_DATE(), INTERVAL n YEAR)` (anos completos), e o score usa a
mesma regra. Validado no real: "≥ 2 anos" devolveu idade mínima de 2,06 anos.

## CNAE: versão, fonte e golden (medido 2026-09-26)

- **A base da Receita usa a CNAE 2.3**: 99,96% dos estabelecimentos ativos
  têm código 2.3; o resto é o placeholder `8888888` (10 mil) e 7 códigos
  obsoletos com 147 empresas no total.
- **O índice antigo misturava versões**: 1356 entradas do diretório
  `br_bd_diretorios_brasil.cnae_2` sem filtrar `indicador_cnae_2_3` — 24
  códigos fora da 2.3, quase todos com 0 empresas ativas. Ex.: "padarias"
  apontava para 4721-1/01 (0 ativas); as padarias estão em 1091-1/02
  (192 mil) e 4721-1/02 (91 mil). "Clínicas de estética" em 9609-2/01 (0),
  e não 9602-5/02 (376 mil).
- **O `indicador_cnae_2_3` do diretório também erra**: marca 9900-8/00
  (organismos internacionais, 2.070 ativas) como fora da 2.3. A autoridade
  sobre os códigos passou a ser a API do IBGE/CONCLA (1332 subclasses); o
  diretório só dá a grafia das descrições.
- **O IBGE lista as atividades de cada subclasse** (17.180 no total; mediana
  7 por subclasse): "atividades de dentistas", "consultório dentário"… O
  índice tem um vetor por descrição e por atividade (18.498 vetores); a
  similaridade da subclasse é a maior entre os seus vetores.
- **Golden corrigido**: 17 dos 66 casos apontavam para código inexistente
  (5510-8/00, 4771-7/00), obsoleto (4721-1/01) ou errado (dentistas →
  8630-5/01 "procedimentos cirúrgicos"; lanchonetes → ambulantes; academias
  → gestão de estádios; pousadas → pensões, quando o IBGE lista pousada em
  5510-8/01 Hotéis).
- **Seleção pelo Gemini**: a busca devolve 15 candidatos e o Gemini escolhe
  (enum restrito aos candidatos, sem raciocínio: p50 0,87 s; com raciocínio
  4,9 s e mesma qualidade). O top-5 fixo punha 77% de códigos errados no
  filtro.

## Onda 1 — sinais do próprio cadastro (2026-09-27)

`estabelecimentos_ativos` ganhou seis colunas, calculadas no build sobre o
mesmo snapshot: rede (`n_estabelecimentos`), regime tributário, bairro
(+ `bairro_norm`), coordenada por CEP (`latitude`/`longitude`) e domínio
próprio. Mais uma tabela auxiliar, `quimera.ceps` (coordenadas por CEP, para
resolver o centro do raio sem ler `GEOGRAPHY` a cada pedido). Plano:
`docs/superpowers/plans/2026-09-26-onda1-sinais-cadastro.md`.

### Checagens do build real (mesmo snapshot 2026-01-11)

Todas passaram:

| checagem | resultado |
|---|---|
| regime presente / coerente com `opcao_mei` | 0 divergências |
| `n_estabelecimentos` válido | 0 inválidos |
| coordenada presente | 25.332.194 (91,2%; mínimo aceito 85%) |
| coordenada dentro da caixa do Brasil | 0 fora |
| domínio próprio plausível | 1.285.768 (4,6%; faixa aceita 1–10%) |

Regime tributário dos 27.784.536 ativos: **11.510.264 MEI, 9.387.165 fora do
Simples, 6.887.107 no Simples** (não MEI).

### CTAS em dois passos: BigQuery recusa `ORDER BY` em CTAS particionado

O `build_leads_sql` da Fase 1 usava um único
`CREATE TABLE ... PARTITION BY ... CLUSTER BY ... AS SELECT`. Com os 3 CTEs
da Onda 1 (agregações + JOINs), o resultado sai em blocos que não preservam
a ordem física das chaves do cluster, e a poda por clusterização — que só
atua na execução, nunca na estimativa pré-execução — parou de funcionar. A
correção óbvia, acrescentar `ORDER BY sigla_uf, id_municipio,
cnae_fiscal_principal` ao mesmo CTAS, é recusada pelo BigQuery: *"Result of
ORDER BY queries cannot be partitioned"*. A solução ficou em dois passos:
`build_leads_sql` grava uma tabela **ordenada, sem partição/cluster**;
`build_leads_staging_sql` faz um segundo CTAS particionado e clusterizado
por cima, com `SELECT * FROM <ordenada>`.

### Custo por pedido (medido 2026-09-27, `probe_onda1_pedidos.py`)

| pedido | antes da Onda 1 | Onda 1 |
|---|---|---|
| odontologia (div. 86) + UF + município | 70 MB | 82,8 MB (+18%) |
| varejo (div. 47) + UF | 221 MB | 247,5 MB (+12%) |
| **só UF, sem CNAE** | **10 MB** | **2.585,8 MB (+25.758%)** |
| rede: academias em SP capital, ≥ 5 unidades | — | 33,6 MB |
| regime: material de construção em Goiânia, fora do Simples | — | 101,7 MB |
| bairro: restaurantes em Pinheiros | — | 47,2 MB |
| raio: odontologia a 3 km do CEP 01310-100 | — | 176,2 MB |
| domínio próprio: clínicas médicas em Campinas | — | 82,8 MB |

**O CTAS em dois passos não restaurou a poda por completo.** Pedidos com
CNAE ficam dentro do critério de aceite do plano (piora ≤ 20%) porque a poda
por partição (`cnae_divisao`) já resolve a maior parte do custo. Sem CNAE, o
pedido depende só da poda por cluster, que segue fraca — medido à parte, na
mesma coluna (`sigla_uf`, sem nenhum filtro de CNAE):

| consulta | bytes cobrados | % do total |
|---|---|---|
| `sigla_uf` inteira, sem filtro | 111,15 MB | 100% |
| `WHERE sigla_uf = 'MG'` (10,4% das linhas) | 46,14 MB | 41,5% |
| `WHERE sigla_uf = 'RR'` (0,18% das linhas — o menor estado) | 38,80 MB | 34,9% |

RR tem 58× menos linhas que MG e custa quase o mesmo — sinal de que a
clusterização não está isolando por UF como deveria. **Pendência:**
investigar se a ordem das chaves do cluster, o número de partições (até 99,
por divisão CNAE, o que deixa poucos blocos por partição) ou outra causa
explica a poda fraca.

### Suíte e2e real, pós-build (2026-09-27)

| suíte | resultado | limiar |
|---|---|---|
| extração (55 casos públicos) | acerto 94,2%, recusa correta 100% | ≥ 85% / = 100% ✅ |
| CNAE (66 casos) | recall@5 95,5% | ≥ 90% ✅ |
| e2e principal (27 casos) | casos ok 92,6%, precisão 99,0% | ≥ 90% / ≥ 98% ✅ |
| e2e conjunto separado (33 casos) | casos ok 90,9%, precisão **94,5%** | ≥ 90% / ≥ 98% **❌** |

Os 7 casos novos da Onda 1 no conjunto principal (`e2e_021`–`e2e_027`)
passaram todos. No conjunto separado, 2 dos 3 casos que falharam
(`hold_011`, `hold_019`) já falhavam **antes** da Onda 1, com a mesma causa
(ambiguidade de seleção de CNAE) — não são regressão deste trabalho
(reproduzido contra o resultado do commit `6ac4f68`). O terceiro, `hold_032`
(novo, "pet shops no bairro Boa Viagem"), também falha por CNAE, não pelo
filtro de bairro. O limiar de precisão do conjunto separado já estava abaixo
de 98% nas três últimas medições **antes** desta Onda (94,2% / 96,0% / 96,0%
— `eval/results/e2e_gemini-2.5-flash_20260926T19*`): o valor de
`eval/thresholds.json` parece calibrado só contra o golden principal, não
contra o conjunto separado.

### Paridade `bairro_norm` × `normalize_name` (1.000 pares amostrados)

0,1% de divergência (1 par em 1.000; limite aceito no plano), sempre por
espaço não separável (`\xa0`): o `\s` do `REGEXP_REPLACE` do BigQuery não
cobre esse caractere, enquanto `str.split()` do Python cobre. Efeito
esperado só em nomes de bairro com esse artefato de codificação na fonte —
não volta para a Task 2.

### Pendências

- Poda por cluster fraca em pedidos sem filtro de CNAE (acima) — investigar
  antes de considerar a Onda 1 fechada.
- `row_precision` do conjunto separado abaixo do limiar de
  `eval/thresholds.json`, de forma pré-existente à Onda 1 — recalibrar o
  limiar por suíte (principal vs. separado) é a correção mais provável.
