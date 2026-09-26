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
  janelas de `resolve_latest_snapshots` absorve a mudança sem intervenção.
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

**Consequência: com o teto padrão, toda consulta de leads é recusada.** O dry
run sem estimativa escondia isso. Custo on-demand ≈ US$ 0,08 por consulta.

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
