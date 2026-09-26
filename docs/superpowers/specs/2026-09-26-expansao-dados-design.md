# Expansão de dados — plano em ondas

**Objetivo:** tirar o máximo de sinal das bases públicas já acessíveis no
BigQuery, sem quebrar as regras do projeto (o LLM nunca escreve SQL, a policy é
ponto único, teto de custo em toda consulta e nenhum dado pessoal no público).

**Estado atual:** `quimera.estabelecimentos_ativos` usa ~15 colunas de
`estabelecimentos`, `empresas`, `simples` e do diretório de municípios, só do
snapshot mais recente. O build custa ~US$ 0,10 por mês.

Cada onda abaixo vira depois o seu próprio spec + plano de implementação. Esta
é a ordem e o raciocínio, não o passo a passo.

---

## 1. Inventário medido (2026-09-26)

Os bytes vêm da sonda com `maximum_bytes_billed=1` (recusada sem custo), só
com as colunas que cada onda precisa. Os schemas vêm de `bq show`.

| Fonte | Liga por | O que extrair | Bytes/leitura | Modo |
|---|---|---|---|---|
| `br_me_cnpj.estabelecimentos` (colunas não usadas) | `cnpj` | CNAE secundário, CEP, bairro, domínio do e-mail (só flag), situação especial | 3,7 GB (só `cnae_fiscal_secundaria`) | público (flag) |
| `br_me_cnpj.estabelecimentos` (histórico, ~45 snapshots) | `cnpj` | eventos: abertura, fechamento, filial nova, mudança de endereço ou CNAE | 9,8 GB por par de snapshots (6 col.) | público |
| `br_me_cnpj.empresas` (histórico) | `cnpj_basico` | variação de capital social e de porte | ~2 GB por snapshot (estimado; medir) | público |
| `br_me_cnpj.simples` | `cnpj_basico` | regime (MEI, Simples ou fora) | 2,3 GB (tabela toda) | público |
| `br_me_cnpj.socios` | `cnpj_basico` | nº de sócios, sócio PJ, sócio estrangeiro, entrada recente | 0,97 GB (sem nome e sem documento) | público só agregado |
| `br_ms_cnes.estabelecimento` | `cpf_cnpj`, `cnpj_mantenedora` | tipo de unidade, vínculo SUS, CNES↔CNPJ | 0,30 GB/mês | público |
| `br_ms_cnes.profissional` | `id_estabelecimento_cnes` | **contagem** de profissionais por CBO (dentista, médico, fisioterapeuta…) | 2,5 GB/mês | público só contagem |
| `br_ms_cnes.leito` | `id_estabelecimento_cnes` | nº de leitos | 0,02 GB/mês | público |
| `br_ms_cnes.equipamento` | `id_estabelecimento_cnes` | equipamentos (raio-X, tomógrafo, cadeira odontológica…) | 0,49 GB/mês | público |
| `br_cgu_sancoes.ceis`/`cnep`/`cepim`/`acordos_leniencia` | `cpf_cnpj_sancionado` | empresa sancionada ou impedida | ~0,03 GB | público (exclusão) |
| `br_mf_divida_ativa.*` | `cpf_cnpj` | inscrito em dívida ativa (PGFN, FGTS, previdenciária) e valor | 7,6 GB (não prev., 1 ano) | a decidir (§4) |
| `br_cgu_licitacao_contrato.licitacao_participante`/`contrato_compra` | `cpf_cnpj_participante`/`contratado` | vende para o governo federal, venceu licitação, valor contratado | 2,5 GB (tudo) | público |
| `br_bd_diretorios_brasil.cep` | `cep` | centroide (lat/long) do CEP | 0,05 GB | público |
| `br_ibge_populacao.municipio`, `br_ibge_pib.municipio` | `id_municipio` | população, PIB, VA por setor | ~0 GB | público |
| `br_me_exportadoras_importadoras.estabelecimentos` | `cnpj` | exporta ou importa | `numRows=0` no `bq show` — **verificar** | público |

**Descartado de propósito:**
- `br_me_rais` e `br_me_caged` públicos não têm CNPJ, então não ligam. Podem
  servir no máximo como agregado por município e CNAE, na Onda 6.
- `br_cgu_beneficios_cidadao` é dado de pessoa física: nunca.
- Nome ou documento de sócio e nome de profissional do CNES ficam fora do
  público. Nome de sócio no privado continua **[CONFIRMAR com o Bruno]**, como
  já diz a spec.

**Custo total estimado de um build mensal com tudo:** ~30 GB, ou seja,
~US$ 0,20 on-demand. O backfill histórico único (Onda 3) fica em ~150–250 GB,
~US$ 1–1,5.

---

## 2. Arquitetura: tabelas de sinais, juntadas no build

Continua valendo a regra de **um pedido = uma tabela própria particionada**.
Cada fonte nova vira uma tabela de sinais pequena, chaveada por `cnpj_basico`
ou `cnpj`, construída no mesmo `python -m quimera.dados build`, com checagens
próprias. Na etapa final, as colunas de sinal são **desnormalizadas** em
`estabelecimentos_ativos`. Com isso, o custo por pedido segue o de hoje mais os
bytes das colunas novas lidas, e o SQL continua sendo um `SELECT` só.

```
fontes (Base dos Dados)
  ├─ sinais_empresa     (cnpj_basico): regime, sócios agregados, sanção, dívida, licitações, nº unidades
  ├─ sinais_saude       (cnpj):        CNES — tipo, SUS, profissionais por grupo CBO, leitos, equipamentos
  ├─ cnae_secundario    (cnpj, cnae)   particionada por divisão CNAE  ← consultada à parte
  ├─ eventos            (cnpj, tipo, data) — diff entre snapshots        ← consultada à parte
  └─ mercado_municipio  (id_municipio): população, PIB, densidade por CNAE
                │
                ▼
estabelecimentos_ativos (+ colunas de sinal, + lat/long do CEP)
```

A exceção são as duas tabelas "consultadas à parte". O CNAE secundário e os
eventos são 1:N e não cabem numa coluna. Elas entram na query como
`EXISTS`/semi-join, particionadas para podar bytes.

A policy continua sendo o ponto único. Cada coluna nova é classificada em
`policy.py` como pública ou privada, e o teste "o SQL público não contém
coluna privada" passa a cobrir as colunas novas.

---

## 3. Ondas

Cada onda segue o mesmo ciclo do projeto: medir custo real → build com
checagens → novo campo em `LeadFilters` → prompt de extração → score com
motivo legível → casos no eval **escritos antes de rodar** → README só com o
que foi medido.

### Onda 1 — o que já está nas tabelas lidas (baixo esforço, alto retorno)

- **`n_estabelecimentos`** por `cnpj_basico` (contagem na própria partição):
  um filtro "rede, com N+ unidades" e um sinal de porte real. Para o ICP de
  clínicas é provavelmente o melhor sinal, porque `porte` não separa médio de
  grande.
- **Regime tributário** a partir de `simples`: `mei` / `simples` /
  `fora_simples`. "Fora do Simples" **não** é afirmado como faturamento alto,
  porque há empresas fora por escolha ou por atividade vedada.
- **CEP e bairro** + **lat/long** pelo `diretorio.cep` (centroide): busca por
  raio ("até 5 km do CEP X") e por bairro. O endereço completo não entra.
- **`dominio_proprio`** (bool): domínio de e-mail usado por no máximo 4
  empresas. Serve como sinal de maturidade digital sem expor o e-mail. É
  calculado no build e o e-mail nunca sai de lá.

**Revisto pelas medições de 2026-09-26** (detalhes no plano
`docs/superpowers/plans/2026-09-26-onda1-sinais-cadastro.md`):
- *"Saiu do Simples" e "ex-MEI" como crescimento: descartados.* Saem ~200 mil
  empresas por mês o ano todo, e ~1,2 M em dezembro (exclusão anual). A data
  não diz o motivo. Crescimento vai para a Onda 3 (diff de capital e porte).
- *`ente_federativo`: descartado.* São 84.004 preenchidos contra 84.107 com
  natureza 1xxx, então é redundante.
- *Domínio próprio sem lista de provedores:* o corte por nº de empresas por
  domínio já elimina provedores, contabilidades (contabilizei.com.br: 141.903
  empresas) e erros de digitação.

Novos filtros: `min_estabelecimentos`, `regimes`, `bairros`,
`cep_centro` + `raio_km`, `com_dominio_proprio`.

**Aceite:** ver o plano da Onda 1 (checagens de build com limiares medidos,
custo por pedido sem piora > 20%, limiares do eval mantidos, invariantes do
público).

### Onda 2 — CNAE secundário

A tabela `cnae_secundario (cnpj, cnae, cnae_divisao)` é explodida do campo
de texto e particionada por divisão. `LeadFilters` ganha
`incluir_cnae_secundario: bool` (padrão falso, porque muda o significado do
resultado). A query faz `cnpj IN (SELECT … WHERE cnae_divisao IN UNNEST(@div))`.

**Aceite:** medir o recall ganho no conjunto separado (quantos leads
relevantes só apareciam pelo secundário) e o custo extra por pedido.

### Onda 3 — Histórico e eventos (o diferencial)

O build faz o diff entre o snapshot atual e o anterior e acumula em `eventos`:

| evento | regra |
|---|---|
| `abertura` | `cnpj` novo e ativo |
| `fechamento` | ativo → baixada/inapta (entra no analítico e nunca vira lead) |
| `nova_filial` | `cnpj_basico` existente ganha um `cnpj` |
| `mudou_endereco` | `id_municipio` ou `cep` mudou |
| `mudou_cnae` | `cnae_fiscal_principal` mudou |
| `aumento_capital` | `capital_social` subiu (de `empresas`) |
| `mudou_porte` | `porte` mudou |
| `mudou_regime` | `regime_tributario` mudou entre snapshots da tabela própria (a data de exclusão do Simples sozinha não serve: não diz o motivo) |

O backfill é feito uma vez, varrendo pares de snapshots consecutivos
(~US$ 1–1,5). Depois, custa um par por mês. O pedido ganha
`eventos: [tipo]` + `eventos_desde_meses`. O score ganha motivos como
"abriu filial há 2 meses".

**Pré-requisito:** medir quantas partições existem de fato hoje. Em
2026-09-26 os snapshots foram reorganizados (§ Achados em `docs/schema.md`).

**Aceite:** checagem de sanidade por mês (volume de aberturas e fechamentos
dentro de ±50% da média); pelo menos 3 tipos de evento no eval.

### Onda 4 — CNES (vertical saúde, ICP de clínicas)

`sinais_saude` liga CNES→CNPJ por `cpf_cnpj` (e `cnpj_mantenedora` para
redes) e agrega:
- `tipo_unidade`, `atende_sus`;
- **contagem** de profissionais por grupo de CBO (dentistas, médicos,
  enfermagem, fisioterapia, psicologia…), com um mapa CBO→grupo versionado no
  repo;
- `leitos_total`, equipamentos por tipo (mapa código→rótulo a partir do
  `dicionario` do CNES).

Filtros: `min_profissionais` (com grupo), `atende_sus`, `tem_equipamento`.
Pedidos do tipo "clínicas com 5+ dentistas que não atendem SUS" passam a ser
possíveis.

**Pré-requisitos:** medir a taxa de casamento CNES↔CNPJ em estabelecimentos
de saúde ativos (sem esse número a onda não vale). Confirmar o último mês
disponível no CNES.

### Onda 5 — Risco e relação com governo

- `sancionada` (CEIS/CNEP/CEPIM/leniência vigentes): **exclusão padrão** em
  ambos os modos, aplicada pela policy.
- `vende_governo_federal`, `licitacoes_vencidas_12m`, `valor_contratado_12m`
  (CGU, só esfera federal; deixar a limitação escrita no resultado).
- `divida_ativa` (bool + faixa de valor): ver decisão em §4.

**Aceite:** um teste que prova que empresa sancionada nunca sai no resultado,
nem com o pedido pedindo explicitamente.

### Onda 6 — Mercado e modo analítico (junto da Fase 4)

- `mercado_municipio`: população, PIB, VA por setor e densidade de
  estabelecimentos por divisão CNAE por 10 mil habitantes. Entra no score
  ("mercado pouco saturado") e na resposta ("342 concorrentes na cidade").
- É a base de dados natural da Fase 4, com perguntas agregadas: aberturas por
  ano, taxa de fechamento por CNAE e cidade, saturação. Os eventos da Onda 3
  tornam essas perguntas baratas.

---

## 4. Decisões abertas para o Bruno

1. **Dívida ativa no público.** A lista da PGFN é pública por lei, mas expor
   "empresa X deve R$ Y" numa demo tem risco reputacional. Proposta: no público,
   só como **filtro de exclusão** ("sem dívida ativa"), sem mostrar valor; no
   privado, com faixa de valor.
2. **Sócios agregados no público.** Nº de sócios, sócio PJ e sócio estrangeiro
   não identificam pessoa. A proposta é liberar esses três. `faixa_etaria`
   dos sócios ficaria só no privado.
3. **Ordem das ondas 3 e 4.** Se o nicho de clínicas estiver confirmado, a
   Onda 4 (CNES) antes da 3 dá mais retorno para a Turno 24. Se não, a Onda 3
   serve a qualquer ICP.
4. **Onda 2 ligada por padrão?** A proposta é não ligar: incluir o secundário
   muda o que "empresa de X" significa.

## 5. Riscos

- **Dados com defasagem diferente:** o CNPJ está em 2026-01, o CNES é mensal
  com atraso próprio e dívida ativa e licitações são anuais ou trimestrais. Cada
  sinal leva a sua data de referência nos labels, e o resultado a mostra.
- **Tabela final mais larga:** cada coluna nova custa bytes em todo pedido que
  a lê. O SQL só seleciona as colunas de sinal que o filtro ou o score usa, e
  o eval de custo pega regressões.
- **Casamento CNES↔CNPJ e CEP↔centroide** podem ter cobertura baixa. Isso é
  medido antes de prometer o filtro, e o filtro traz um aviso de cobertura.
- **Base dos Dados reorganiza tabelas** (já aconteceu). O build falha
  fechado, pelas checagens de volume por fonte, e a versão em uso fica
  intacta.
