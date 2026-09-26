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

## PENDENTE — não validável neste dataset

1. ~~**`NATUREZA_EMPRESARIO_INDIVIDUAL = "2135"`**~~ **RESOLVIDO (2026-09-26)**:
   o diretório `br_bd_diretorios_brasil.natureza_juridica` confirma
   `2135 = "Empresário (Individual)"`.
2. **`porte` não tem "média" nem "grande".** `filters.py` aceita
   `{micro, pequena, media, grande}`, e `score.py` usa `preferred_portes=("media",)`
   — mas a coluna só distingue Micro / Pequeno Porte / Demais. "Média" e "grande"
   caem juntas em `"5"` (Demais), indistinguíveis. Decisão de produto pendente.
3. **`opcao_mei` é INTEGER**, não `'S'/'N'` como o comentário no código supunha.
   Valores (provavelmente 0/1) não estão no `dicionario`.
4. **Dry run não estima bytes** em `estabelecimentos`/`empresas`:
   `total_bytes_processed` volta `None`. Em tabelas normais (`dicionario`,
   `municipio`) volta normalmente. O job real reporta bytes — só o dry run não.

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
