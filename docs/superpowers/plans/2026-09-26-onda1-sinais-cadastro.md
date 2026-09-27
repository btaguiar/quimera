# Onda 1 — sinais do próprio cadastro — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** acrescentar à tabela própria e ao pipeline quatro sinais que já estão
nas tabelas lidas pelo build: **rede** (nº de estabelecimentos da empresa),
**regime tributário**, **localização fina** (bairro e raio a partir de um CEP)
e **domínio de e-mail próprio** (só o booleano). Cada sinal chega ao usuário
como filtro extraído pelo LLM e como motivo no score.

**Architecture:** tudo é calculado no `python -m quimera.dados build`
(CTEs sobre o mesmo snapshot) e desnormalizado em `estabelecimentos_ativos`.
Uma tabela auxiliar nova, `ceps`, guarda (cep, latitude, longitude) para
resolver o centro do raio. O pedido continua sendo um `SELECT` parametrizado
sobre a tabela própria, e o LLM continua só preenchendo `LeadFilters`.

**Tech Stack:** Python 3.10+, pydantic v2, BigQuery (GEOGRAPHY:
`ST_GEOGPOINT`, `ST_DWITHIN`, `ST_DISTANCE`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-26-expansao-dados-design.md` (Onda 1)

**Convenções do repo (importantíssimo):**
- Docstrings em pt-BR em todo módulo, classe e função pública; comentário
  inline só quando explica um porquê medido.
- Imports de `google.cloud` sempre lazy (dentro de função).
- Testes não tocam GCP/rede: usam fakes de `tests/fakes.py`.
- `python -m pytest` roda da raiz `C:\Dev\quimera`.
- Todo número novo em comentário ou doc cita a medição (data + valor).
- Casos novos do eval são **escritos e commitados antes de rodar**.
- Commits em pt-BR, direto em `master` (repo só local).

---

## Medições que definem este plano (2026-09-26, snapshot 2026-01-11)

| sinal | medido | consequência |
|---|---|---|
| rede | 26.457.209 empresas ativas; 487.521 com 2–4 unidades, 50.110 com 5–19, 5.662 com 20+ (máx. 7.695) | `min_estabelecimentos` filtra de fato |
| regime | 18,4 M ativos no Simples, 11,5 M MEI, 9,4 M fora (4,65 M sem linha em `simples`) | `regimes` = `simples` / `fora_simples` / `mei` |
| exclusão do Simples | ~200 mil/mês o ano todo e ~1,2 M em dezembro (exclusão anual), mesmo padrão no MEI | **não** é sinal de crescimento, porque a data não diz o motivo. Fica fora; crescimento vai para a Onda 3 (diff de capital/porte) |
| `simples` mais nova que o CNPJ | datas de exclusão até 2026-08 com o snapshot em 2026-01 | o regime é mais recente que o resto da linha; registrar no doc |
| `ente_federativo` | 84.004 preenchidos contra 84.107 com natureza 1xxx | redundante com a natureza jurídica, então **não entra** |
| CEP → centroide | 25.332.194 de 27.786.988 ativos (91,2%) casam com `diretorio.cep` com centroide; 74.830 sem CEP; 433.159 (1,6%) com município do CEP ≠ município do cadastro | busca por raio cobre ~91%, com aviso de cobertura |
| bairro | 28.415 sem bairro | filtro por bairro viável (exige município) |
| e-mail | 24,46 M ativos com e-mail; gmail 12,9 M empresas, hotmail 4,2 M; contabilizei.com.br 141.903, maismei.com.br 88.408 (e-mail da contabilidade); erros de digitação (gmai.com 11 mil) | "domínio próprio" = domínio usado por **no máximo 4** empresas. Com esse corte não é preciso lista de provedores: 658.689 domínios são exclusivos de 1 empresa e 177.445 são de 2 a 4 |

Custo do build (sonda sem custo, Task 1): **13,17 GB hoje e 16,54 GB com os
sinais da Onda 1** (protótipo do SQL da Task 2), mais ~0,05 GB da tabela
`ceps`, ou seja, ~US$ 0,10/mês. O CTE `ativos`, referenciado três vezes, não é
cobrado três vezes.

---

### Task 1: Sonda de custo do build novo (portão antes de qualquer execução real)

O script é escrito agora e roda assim que a Task 2 estiver pronta. Nenhum
build real acontece antes de ele passar.

**Files:**
- Create: `probe_build_onda1.py` (raiz, no padrão dos `probe_*.py` existentes)

- [x] **Step 1:** Escrever a sonda: gera `build_leads_sql` com um destino
  descartável e executa com `maximum_bytes_billed=1`, que é recusada sem
  custo. Imprime os bytes exigidos (`"N or higher required"`), como em
  `probe_data.py`.
- [x] **Step 2:** Critério: N ≤ 25 GB. **Medido: 16,54 GB (protótipo); OK.** Se o CTE `ativos` for cobrado uma vez
  por referência (três referências), N sobe para ~40 GB. Nesse caso,
  materializar `ativos` numa tabela `_ativos_tmp` e ler dela.
- [x] **Step 3:** Anotar N no comentário de `BUILD_MAX_BYTES`.
- [ ] **Step 4 (depois da Task 2):** rodar `python probe_build_onda1.py`
  sobre o `build_leads_sql` real (+ `build_ceps_sql`) e conferir que N fica
  perto dos 16,54 GB do protótipo.

---

### Task 2: Build — sinais na tabela própria e tabela `ceps`

**Files:**
- Modify: `src/quimera/query.py` (constantes de coluna)
- Modify: `src/quimera/dados.py`
- Test: `tests/test_dados.py`

- [ ] **Step 1: Constantes em `query.py`** (bloco "Tabelas e colunas"):

```python
TABLE_DIRETORIO_CEP = "`basedosdados.br_bd_diretorios_brasil.cep`"
COL_CEP = "cep"
COL_BAIRRO = "bairro"
COL_OPCAO_SIMPLES = "opcao_simples"  # INTEGER 0/1
COL_CENTROIDE = "centroide"  # GEOGRAPHY no diretório de CEP
CEPS_TABLE_NAME = "ceps"
# Colunas da tabela própria (nomes finais).
COL_REGIME = "regime_tributario"  # 'mei' | 'simples' | 'fora_simples'
COL_N_ESTABELECIMENTOS = "n_estabelecimentos"
COL_BAIRRO_NORM = "bairro_norm"
COL_LATITUDE = "latitude"
COL_LONGITUDE = "longitude"
COL_DOMINIO_PROPRIO = "dominio_proprio"
REGIMES = ("mei", "simples", "fora_simples")
```

- [ ] **Step 2: Testes que falham** (em `tests/test_dados.py`):

```python
class TestBuildLeadsSqlSinais:
    def test_counts_active_establishments_per_company(self):
        sql = dados.build_leads_sql("p.d.t", SNAPSHOTS)
        assert "COUNT(*) AS n_estabelecimentos" in sql
        assert "GROUP BY cnpj_basico" in sql

    def test_regime_from_simples(self):
        sql = dados.build_leads_sql("p.d.t", SNAPSHOTS)
        assert (
            "CASE WHEN sim.opcao_mei = 1 THEN 'mei'"
            " WHEN sim.opcao_simples = 1 THEN 'simples'"
            " ELSE 'fora_simples' END AS regime_tributario" in sql
        )

    def test_coordinates_from_cep_directory(self):
        sql = dados.build_leads_sql("p.d.t", SNAPSHOTS)
        assert "ST_Y(dcep.centroide) AS latitude" in sql
        assert "ST_X(dcep.centroide) AS longitude" in sql
        assert "LEFT JOIN `basedosdados.br_bd_diretorios_brasil.cep` AS dcep" in sql

    def test_dominio_proprio_is_boolean_with_measured_cut(self):
        sql = dados.build_leads_sql("p.d.t", SNAPSHOTS)
        assert f"COALESCE(dom.empresas <= {dados.MAX_EMPRESAS_POR_DOMINIO}, FALSE)" in sql
        assert dados.MAX_EMPRESAS_POR_DOMINIO == 4

    def test_output_has_no_contact_or_address(self):
        # O e-mail é lido só para calcular o domínio; nada de contato,
        # domínio, CEP ou logradouro sai na tabela de leads.
        for col in dados.LEADS_COLUMNS:
            assert col not in {
                "email", "correio_eletronico", "telefone", "ddd_1",
                "dominio", "cep", "logradouro", "numero", "complemento",
            }
        final_select = dados.build_leads_sql("p.d.t", SNAPSHOTS).split("\nSELECT\n")[-1]
        assert "email" not in final_select.split("\nFROM ")[0]

    def test_active_filter_and_snapshot_live_in_the_cte(self):
        sql = dados.build_leads_sql("p.d.t", SNAPSHOTS)
        assert "data = DATE '2026-01-11'" in sql
        assert "situacao_cadastral = '2'" in sql
        assert "emp.data = DATE '2025-12-14'" in sql


class TestBuildCepsSql:
    def test_only_ceps_with_centroid_clustered_by_cep(self):
        sql = dados.build_ceps_sql("p.d.ceps")
        assert "CLUSTER BY cep" in sql
        assert "WHERE centroide IS NOT NULL" in sql
        assert "ST_Y(centroide) AS latitude" in sql
```

Os testes antigos `test_reads_each_table_in_its_own_snapshot`,
`test_only_active_establishments` e `test_has_no_contact_columns` mudam de
forma: o filtro de estabelecimentos passa para o CTE, sem o prefixo `est.`.
`test_has_no_contact_columns` é substituído por
`test_output_has_no_contact_or_address`.

- [ ] **Step 3: Rodar e ver falhar.** `python -m pytest tests/test_dados.py -q`

- [ ] **Step 4: Implementar `build_leads_sql`** com três CTEs sobre o mesmo
  snapshot. Constantes novas em `dados.py`:

```python
# Domínio de e-mail usado por até 4 empresas conta como próprio. Medido em
# 2026-09-26: gmail 12,9 M empresas, contabilizei.com.br 141.903 (e-mail da
# contabilidade), 658.689 domínios exclusivos de 1 empresa e 177.445 de 2 a 4.
# O corte descarta provedores, contabilidades e erros de digitação sem lista.
MAX_EMPRESAS_POR_DOMINIO = 4
LEADS_COLUMNS = (
    "cnpj", "cnpj_basico", "matriz_filial", "razao_social", "nome_fantasia",
    "sigla_uf", "id_municipio", "municipio", "cnae_fiscal_principal",
    "cnae_divisao", "data_inicio_atividade", "capital_social", "porte",
    "natureza_juridica", "opcao_mei", "regime_tributario", "n_estabelecimentos",
    "bairro", "bairro_norm", "latitude", "longitude", "dominio_proprio",
)
```

Forma do SQL (nomes via constantes; datas e tabelas são nossas):

```sql
CREATE OR REPLACE TABLE `<dest>`
PARTITION BY RANGE_BUCKET(cnae_divisao, GENERATE_ARRAY(1, 100, 1))
CLUSTER BY sigla_uf, id_municipio, cnae_fiscal_principal
OPTIONS(labels=[...])
AS
WITH ativos AS (
  SELECT cnpj, cnpj_basico, identificador_matriz_filial, nome_fantasia,
    sigla_uf, id_municipio, cnae_fiscal_principal, data_inicio_atividade,
    cep, bairro,
    LOWER(REGEXP_EXTRACT(TRIM(email), r'@([^@\s]+)$')) AS dominio
  FROM `basedosdados.br_me_cnpj.estabelecimentos`
  WHERE data = DATE '<est>' AND situacao_cadastral = '2'
),
unidades AS (
  SELECT cnpj_basico, COUNT(*) AS n_estabelecimentos
  FROM ativos GROUP BY cnpj_basico
),
dominios AS (
  SELECT dominio, COUNT(DISTINCT cnpj_basico) AS empresas
  FROM ativos WHERE dominio IS NOT NULL GROUP BY dominio
)
SELECT
  est.cnpj, ..., (colunas de hoje, iguais) ...,
  COALESCE(sim.opcao_mei, 0) AS opcao_mei,
  CASE WHEN sim.opcao_mei = 1 THEN 'mei' WHEN sim.opcao_simples = 1 THEN 'simples' ELSE 'fora_simples' END AS regime_tributario,
  uni.n_estabelecimentos,
  NULLIF(TRIM(est.bairro), '') AS bairro,
  NULLIF(REGEXP_REPLACE(REGEXP_REPLACE(NORMALIZE(UPPER(TRIM(est.bairro)), NFD), r'\p{M}', ''), r'\s+', ' '), '') AS bairro_norm,
  ST_Y(dcep.centroide) AS latitude,
  ST_X(dcep.centroide) AS longitude,
  COALESCE(dom.empresas <= 4, FALSE) AS dominio_proprio
FROM ativos AS est
JOIN `basedosdados.br_me_cnpj.empresas` AS emp USING (cnpj_basico)
JOIN unidades AS uni USING (cnpj_basico)
LEFT JOIN `basedosdados.br_me_cnpj.simples` AS sim USING (cnpj_basico)
LEFT JOIN `basedosdados.br_bd_diretorios_brasil.municipio` AS mun ON mun.id_municipio = est.id_municipio
LEFT JOIN dominios AS dom ON dom.dominio = est.dominio
LEFT JOIN `basedosdados.br_bd_diretorios_brasil.cep` AS dcep ON dcep.cep = est.cep
WHERE emp.data = DATE '<emp>'
```

`bairro_norm` tem de bater com `text.normalize_name`, que tira acentos,
passa para maiúscula e colapsa espaços. A Task 10 confere isso no real.

- [ ] **Step 5: `build_ceps_sql(destination)`**:

```sql
CREATE OR REPLACE TABLE `<dest>`
CLUSTER BY cep
AS
SELECT cep, ST_Y(centroide) AS latitude, ST_X(centroide) AS longitude, id_municipio, sigla_uf
FROM `basedosdados.br_bd_diretorios_brasil.cep`
WHERE centroide IS NOT NULL
```

`LeadsTables` ganha `ceps: str = ""`. Se vier vazio, `__post_init__`
deriva `<projeto>.<dataset>.ceps` de `leads` (com `object.__setattr__`,
porque a dataclass é frozen) e valida o formato como as outras. Assim os
construtores existentes nos testes continuam valendo. `build()` grava
`ceps` depois de promover a tabela de leads. A checagem é
`linhas >= MIN_CEPS` (medido: 905.210; mínimo 800.000).

- [ ] **Step 6: Checagens novas** em `quality_checks_sql` e `evaluate_checks`:

```python
# Medido em 2026-09-26: 91,2% dos ativos com centroide de CEP.
MIN_COM_COORDENADA_RATIO = 0.85
# Estimado com as medições por domínio (~4% das empresas); o primeiro
# build real (Task 10) fixa o valor medido aqui.
DOMINIO_PROPRIO_RATIO = (0.01, 0.10)
```

| checagem | SQL | regra |
|---|---|---|
| regime presente | `COUNTIF(regime_tributario IS NULL) AS sem_regime` | `== 0` |
| regime coerente com MEI | `COUNTIF((regime_tributario = 'mei') != (opcao_mei = 1)) AS regime_incoerente` | `== 0` |
| unidades válidas | `COUNTIF(n_estabelecimentos IS NULL OR n_estabelecimentos < 1) AS unidades_invalidas` | `== 0` |
| coordenada presente | `COUNTIF(latitude IS NOT NULL) AS com_coordenada` | razão `>= 0.85` |
| coordenada no Brasil | `COUNTIF(latitude NOT BETWEEN -34 AND 6 OR longitude NOT BETWEEN -74 AND -34) AS fora_do_brasil` | `== 0` |
| domínio próprio plausível | `COUNTIF(dominio_proprio) AS com_dominio_proprio` | razão dentro de `DOMINIO_PROPRIO_RATIO` |

Acrescentar essas chaves em `GOOD_STATS` (valores medidos:
`com_coordenada=25_332_194`; `com_dominio_proprio` ~4% das linhas) e cada
uma no `parametrize` de `test_each_check_fails_on_bad_data`.
`FakeBuildClient.query` passa a aceitar os dois `CREATE` (leads e ceps) e
devolve `{"linhas": 905_210}` para a checagem de `ceps`.

- [ ] **Step 7:** `python -m pytest tests/test_dados.py -q` verde.
- [ ] **Step 8: Commit** `dados: rede, regime, bairro, coordenada e domínio próprio na tabela própria`

---

### Task 3: `LeadFilters` — campos novos

**Files:**
- Modify: `src/quimera/filters.py`
- Test: `tests/test_filters.py`

- [ ] **Step 1: Testes que falham:**

```python
class TestSinaisOnda1:
    def test_defaults_keep_current_behavior(self):
        f = LeadFilters()
        assert f.min_estabelecimentos is None
        assert f.regimes == []
        assert f.bairros == []
        assert f.cep_centro is None and f.raio_km is None
        assert f.com_dominio_proprio is False

    def test_regimes_normalized_and_validated(self):
        assert LeadFilters(regimes=["Simples", " fora_simples "]).regimes == [
            "simples", "fora_simples",
        ]
        with pytest.raises(ValidationError, match="Regime inválido"):
            LeadFilters(regimes=["lucro_real"])

    def test_cep_keeps_only_digits(self):
        assert LeadFilters(cep_centro="01310-100").cep_centro == "01310100"

    def test_invalid_cep_rejected(self):
        with pytest.raises(ValidationError, match="CEP"):
            LeadFilters(cep_centro="1234")

    def test_raio_bounds(self):
        with pytest.raises(ValidationError, match="raio"):
            LeadFilters(raio_km=0)
        with pytest.raises(ValidationError, match="raio"):
            LeadFilters(raio_km=500)

    def test_min_estabelecimentos_positive(self):
        with pytest.raises(ValidationError):
            LeadFilters(min_estabelecimentos=0)
```

- [ ] **Step 2: Implementar.** Campos:

```python
    # Rede: nº de estabelecimentos ATIVOS da empresa no país (matriz + filiais).
    min_estabelecimentos: int | None = Field(default=None, ge=1)
    regimes: list[str] = Field(default_factory=list)
    bairros: list[str] = Field(default_factory=list)
    cep_centro: str | None = None
    raio_km: float | None = None
    com_dominio_proprio: bool = False
```

Limites do raio (`RAIO_KM_MIN = 0.1`, `RAIO_KM_MAX = 100.0`) ficam num
`field_validator`, não em `Field(gt=...)`, porque o schema do Vertex não
aceita `exclusiveMinimum` (mesma razão do `limit`). O CEP vira só dígitos e
exige 8. Os regimes são normalizados como os portes e validados contra
`VALID_REGIMES`, definido em `filters.py`. `query.py` importa de `filters`
(e não o contrário), então `query.REGIMES` da Task 2 vira
`REGIMES = tuple(sorted(VALID_REGIMES))`.

- [ ] **Step 3:** `python -m pytest tests/test_filters.py -q` verde.
- [ ] **Step 4: Commit** `filters: rede, regime, bairro, raio por CEP e domínio próprio`

---

### Task 4: Policy — MEI no regime segue a policy

**Files:**
- Modify: `src/quimera/policy.py`
- Test: `tests/test_policy.py`

- [ ] **Step 1: Teste que falha:**

```python
def test_public_strips_mei_from_regimes():
    f = apply_policy(LeadFilters(regimes=["mei", "simples"]), PUBLIC)
    assert f.regimes == ["simples"]

def test_private_keeps_mei_regime():
    f = apply_policy(LeadFilters(regimes=["mei"]), PRIVATE)
    assert f.regimes == ["mei"]
```

- [ ] **Step 2: Implementar** em `apply_policy`: com `not policy.allow_mei`,
  `updates["regimes"] = [r for r in filters.regimes if r != "mei"]`.
- [ ] **Step 3:** Um pedido público "só MEI" fica com `regimes == []`, e a
  query devolveria qualquer regime como se fosse MEI. O pipeline (Task 8)
  detecta "regimes pedidos, todos removidos pela policy" e responde com aviso,
  sem rodar a consulta, como já faz com CNAE e município não resolvidos.
- [ ] **Step 4: Commit** `policy: regime MEI removido no público`

---

### Task 5: Query — filtros, colunas, raio e ranking

**Files:**
- Modify: `src/quimera/query.py`
- Test: `tests/test_query.py`

- [ ] **Step 1: Testes que falham:**

```python
class TestBuildQuerySinais:
    def test_min_estabelecimentos_param(self):
        spec = _build(LeadFilters(min_estabelecimentos=5))
        assert "t.n_estabelecimentos >= @min_estabelecimentos" in spec.sql
        assert _param(spec, "min_estabelecimentos").value == 5

    def test_regimes_param(self):
        spec = _build(LeadFilters(regimes=["fora_simples"]))
        assert "t.regime_tributario IN UNNEST(@regimes)" in spec.sql

    def test_private_mei_regime_lifts_mei_exclusion(self):
        spec = _build(LeadFilters(regimes=["mei"]), PRIVATE)
        assert "t.opcao_mei != 1" not in spec.sql

    def test_bairros_normalized(self):
        spec = _build(LeadFilters(bairros=["Pinheiros", "vila  madalena"]))
        assert "t.bairro_norm IN UNNEST(@bairros)" in spec.sql
        assert _param(spec, "bairros").value == ["PINHEIROS", "VILA MADALENA"]

    def test_radius_uses_center_params_and_selects_distance(self):
        spec = build_query(
            LeadFilters(raio_km=3), PUBLIC, tables=TABLES, centro=(-23.56, -46.65)
        )
        assert (
            "ST_DWITHIN(ST_GEOGPOINT(t.longitude, t.latitude),"
            " ST_GEOGPOINT(@centro_lon, @centro_lat), @raio_m)" in spec.sql
        )
        assert _param(spec, "raio_m").value == 3000.0
        assert "AS distancia_km" in spec.sql

    def test_radius_without_center_is_not_applied(self):
        spec = _build(LeadFilters(raio_km=3))
        assert "ST_DWITHIN" not in spec.sql

    def test_dominio_proprio_filter(self):
        assert "t.dominio_proprio" in _build(LeadFilters(com_dominio_proprio=True)).sql

    def test_new_signals_selected_but_never_coordinates(self):
        sql = _build().sql
        for col in ("t.n_estabelecimentos", "t.regime_tributario", "t.bairro",
                    "t.dominio_proprio"):
            assert col in sql
        select_list = sql.split("\nFROM ")[0]
        assert "t.latitude" not in select_list and "t.longitude" not in select_list
```

Mais um teste em `TestIcpRanking`: com `ICPConfig(w_rede=10, w_dominio=5)`,
os params `icp_w_rede`, `icp_rede_min` e `icp_w_dominio` existem e o ranking
contém `IF(t.n_estabelecimentos >= @icp_rede_min, @icp_w_rede, 0)` e
`IF(t.dominio_proprio, @icp_w_dominio, 0)`.

- [ ] **Step 2: Implementar em `build_query`:**
  - assinatura: `build_query(filters, policy, *, tables, icp=None, centro: tuple[float, float] | None = None)`;
    `centro` = (lat, lon) resolvido pelo pipeline, nunca pelo LLM;
  - `select_cols` += `t.n_estabelecimentos`, `t.regime_tributario`, `t.bairro`,
    `t.dominio_proprio`. Com raio:
    `ROUND(ST_DISTANCE(ST_GEOGPOINT(t.longitude, t.latitude), ST_GEOGPOINT(@centro_lon, @centro_lat)) / 1000, 1) AS distancia_km`;
  - `where` += os filtros acima; bairros por `normalize_name`;
  - `exclude_mei = (not policy.allow_mei) or not (filters.include_mei or "mei" in filters.regimes)`.

- [ ] **Step 3: `_icp_ranking`** espelha o score (Task 6): soma
  `IF(t.n_estabelecimentos >= @icp_rede_min, @icp_w_rede, 0)` e
  `IF(t.dominio_proprio, @icp_w_dominio, 0)` dentro do parêntese, antes do
  fator MEI.

- [ ] **Step 4: `resolve_cep_center(cep, *, tables, client=None) -> tuple[float, float] | None`:**

```python
CEP_LOOKUP_MAX_BYTES = 100 * 1024**2  # tabela ceps ~905 mil linhas (medido)

def resolve_cep_center(cep: str, *, tables: LeadsTables, client: Any | None = None):
    """(lat, lon) do centroide do CEP, lido da tabela própria ``ceps``.

    O CEP vem de LeadFilters (só dígitos, validado); vai como parâmetro.
    Devolve None se o CEP não existe no diretório ou não tem centroide.
    """
```

Faz `SELECT latitude, longitude FROM \`{tables.ceps}\` WHERE cep = @cep LIMIT 1`
com `maximum_bytes_billed=CEP_LOOKUP_MAX_BYTES`. Testes: CEP encontrado,
CEP ausente → None, CEP vai como `ScalarQueryParameter`.

- [ ] **Step 5:** `python -m pytest tests/test_query.py -q` verde.
- [ ] **Step 6: Commit** `query: filtros de rede, regime, bairro, raio e domínio próprio`

---

### Task 6: Score — motivos novos, pesos opcionais

**Files:**
- Modify: `src/quimera/score.py`
- Test: `tests/test_score.py`

Os pesos novos têm **padrão 0**, então o ranking e as métricas atuais do eval
não mudam. A Turno 24 liga os pesos no ICP dela, e os motivos aparecem sempre
que o dado existe.

- [ ] **Step 1: Testes que falham:**

```python
    def test_default_icp_ignores_new_signals_in_score(self):
        base, _ = score_lead(_lead(), _icp())
        with_signals, motivos = score_lead(
            _lead(n_estabelecimentos=12, dominio_proprio=True), _icp()
        )
        assert with_signals == base
        assert "rede com 12 estabelecimentos ativos" in motivos
        assert "e-mail em domínio próprio" in motivos

    def test_weighted_rede_and_dominio(self):
        icp = ICPConfig(w_porte=40, w_age=20, w_capital=20, w_rede=10, w_dominio=10)
        score, _ = score_lead(_lead(n_estabelecimentos=3, dominio_proprio=True), icp)
        assert score == 100.0

    def test_single_establishment_has_no_rede_reason(self):
        _, motivos = score_lead(_lead(n_estabelecimentos=1), _icp())
        assert not any("rede" in m for m in motivos)

    def test_regime_reason(self):
        _, motivos = score_lead(_lead(regime_tributario="fora_simples"), _icp())
        assert "fora do Simples Nacional" in motivos
```

- [ ] **Step 2: Implementar:** `ICPConfig` += `w_rede: float = 0.0`,
  `target_min_estabelecimentos: int = 2`, `w_dominio: float = 0.0`. Os motivos
  informam sem prometer mais do que o dado diz: "fora do Simples Nacional"
  não afirma faturamento, porque há empresas fora do Simples por escolha ou
  por atividade vedada.
- [ ] **Step 3:** `python -m pytest tests/test_score.py tests/test_query.py -q` verde.
- [ ] **Step 4: Commit** `score: motivos de rede, regime e domínio; pesos opcionais no ICP`

---

### Task 7: Prompt de extração

**Files:**
- Modify: `src/quimera/extract.py`
- Test: `tests/test_extract.py`

- [ ] **Step 1: Testes que falham** (conteúdo do prompt):

```python
    def test_prompt_explains_new_signals(self):
        prompt = build_prompt("x", PUBLIC)
        for field in ("min_estabelecimentos", "regimes", "bairros",
                      "cep_centro", "raio_km", "com_dominio_proprio"):
            assert field in prompt

    def test_public_prompt_never_offers_mei_regime(self):
        assert "'mei'" not in build_prompt("x", PUBLIC).split("regimes:")[1].split("\n")[0]

    def test_prompt_radius_only_with_explicit_cep(self):
        assert "só se o pedido trouxer um CEP" in build_prompt("x", PUBLIC)
```

- [ ] **Step 2: Linhas novas em `build_prompt`:**

```
- min_estabelecimentos: nº mínimo de unidades da empresa ('rede', 'com filiais' sem número = 2).
- regimes: 'simples' ou 'fora_simples' ('lucro presumido', 'lucro real' = fora_simples).
  (privado: também 'mei')
- bairros: nomes de bairros como escritos; use junto com municipio_names.
- cep_centro e raio_km: só se o pedido trouxer um CEP; 'perto de', 'na região de'
  sem CEP não viram raio.
- com_dominio_proprio: true para 'com site próprio', 'domínio próprio', 'e-mail corporativo'
  usados como FILTRO. Pedir o e-mail em si continua sendo pedido de contato.
```

- [ ] **Step 3:** `python -m pytest tests/test_extract.py -q` verde.
- [ ] **Step 4: Commit** `extract: prompt com os filtros da Onda 1`

---

### Task 8: Pipeline — CEP, avisos e ordem das etapas

**Files:**
- Modify: `src/quimera/pipeline.py`
- Modify: `tests/fakes.py` (`FakePipelineBQ` responde à consulta de `ceps`)
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: `FakePipelineBQ`** ganha `cep_rows=None`. Em `query`, um SQL
  que contém ``.ceps` `` devolve `FakeJob(0, self.cep_rows)` e registra o SQL
  em `cep_queries`, antes do ramo de execução de leads.

- [ ] **Step 2: Testes que falham:**

```python
class TestSinaisOnda1:
    def test_cep_center_passed_to_query(self):
        bq = FakePipelineBQ(lead_rows=LEAD_ROWS,
                            cep_rows=[{"latitude": -23.56, "longitude": -46.65}])
        result = _run(bq, cnae_query="clínicas", cep_centro="01310100", raio_km=3)
        sql, _ = bq.executed[0]
        assert "ST_DWITHIN" in sql
        assert bq.cep_queries

    def test_unknown_cep_warns_and_skips_query(self):
        bq = FakePipelineBQ(cep_rows=[])
        result = _run(bq, cnae_query="clínicas", cep_centro="99999999", raio_km=3)
        assert not bq.executed
        assert any("CEP 99999999" in w for w in result.warnings)

    def test_radius_without_cep_warns_and_is_ignored(self):
        bq = FakePipelineBQ(lead_rows=LEAD_ROWS)
        result = _run(bq, cnae_query="clínicas", raio_km=3)
        assert bq.executed and "ST_DWITHIN" not in bq.executed[0][0]
        assert any("CEP de referência" in w for w in result.warnings)

    def test_cep_without_radius_uses_default(self):
        ...  # raio padrão 5 km, com aviso

    def test_radius_warns_about_coverage(self):
        ...  # aviso: "~9% dos estabelecimentos não têm coordenada e ficam de fora"

    def test_bairros_without_municipio_warn_and_are_ignored(self):
        ...

    def test_public_mei_only_regime_warns_without_query(self):
        ...  # Task 4, Step 3
```

(`_run` é o helper local que monta `FakeGenaiClient(_extraction_payload(...))`
e chama `run(...)` com `cnae_search=_cnae_search_recorder([...])`, como os
testes existentes.)

- [ ] **Step 3: Implementar** a etapa `cep`, entre `municipios` e `snapshot`,
  cronometrada com `_stage(timings, "cep")`. Constantes:

```python
RAIO_PADRAO_KM = 5.0
# Medido em 2026-09-26: 91,2% dos ativos têm centroide de CEP.
AVISO_COBERTURA_RAIO = (
    "Busca por raio usa o centro do CEP de cada empresa; cerca de 9% dos "
    "estabelecimentos não têm coordenada e ficam de fora."
)
```

Regras:
- `raio_km` sem `cep_centro`: aviso "informe um CEP de referência", e o
  filtro sai via `model_copy(update={"raio_km": None})`;
- `cep_centro` sem `raio_km`: usa `RAIO_PADRAO_KM`, com aviso;
- CEP não encontrado: aviso e retorno sem consulta. Rodar sem o raio
  devolveria empresas de qualquer distância como se estivessem perto;
- `bairros` sem `municipio_names`: aviso e o filtro sai;
- `centro` vai para `build_query(..., centro=centro)`.

- [ ] **Step 4:** `python -m pytest -q` (suíte inteira) verde.
- [ ] **Step 5: Commit** `pipeline: centro do raio por CEP e avisos dos filtros da Onda 1`

---

### Task 9: Eval — critérios por linha, invariantes e casos novos

**Files:**
- Modify: `eval/metrics.py`
- Modify: `eval/golden_extraction.jsonl`, `eval/golden_e2e.jsonl`, `eval/golden_e2e_holdout.jsonl`
- Test: `tests/test_eval_metrics.py`, `tests/test_golden_sets.py`

- [ ] **Step 1: Testes que falham** para `e2e_row_checks`:
  `min_estabelecimentos` (a linha tem `n_estabelecimentos >=`), `regimes`
  (`regime_tributario in`), `bairros` (`normalize_name(bairro) in`),
  `raio_km` (`distancia_km <= raio_km`) e `com_dominio_proprio`
  (`dominio_proprio is True`). Em `e2e_invariant_violations`: no público,
  nenhuma linha tem `latitude`, `longitude`, `cep`, `dominio` ou
  `regime_tributario == "mei"`.

- [ ] **Step 2: Implementar** em `metrics.py`.

- [ ] **Step 3: Casos novos, escritos ANTES de rodar** (CNAEs conferidos
  contra `src/quimera/data/cnae_subclasses.jsonl` na hora de escrever):

`golden_e2e.jsonl`:
```json
{"id": "e2e_021", "request": "redes de academias em São Paulo com pelo menos 5 unidades", "expect": {"uf": ["SP"], "municipio": ["São Paulo"], "cnae": ["9313-1/00"], "min_estabelecimentos": 5}}
{"id": "e2e_022", "request": "escritórios de contabilidade em Belo Horizonte optantes do Simples", "expect": {"uf": ["MG"], "municipio": ["Belo Horizonte"], "cnae": ["6920-6/01", "6920-6/02"], "regimes": ["simples"]}}
{"id": "e2e_023", "request": "restaurantes no bairro Pinheiros em São Paulo", "expect": {"uf": ["SP"], "municipio": ["São Paulo"], "cnae": ["5611-2/01"], "bairros": ["Pinheiros"]}}
{"id": "e2e_024", "request": "clínicas odontológicas num raio de 3 km do CEP 01310-100", "expect": {"cnae": ["8630-5/04"], "raio_km": 3}}
{"id": "e2e_025", "request": "clínicas médicas em Campinas com site próprio", "expect": {"uf": ["SP"], "municipio": ["Campinas"], "cnae": ["8630-5/01", "8630-5/02", "8630-5/03"], "com_dominio_proprio": true}}
{"id": "e2e_026", "request": "lojas de material de construção em Goiânia fora do Simples", "expect": {"uf": ["GO"], "municipio": ["Goiânia"], "cnae": ["4744-0/01", "4744-0/05", "4744-0/99"], "regimes": ["fora_simples"]}}
{"id": "e2e_027", "request": "padarias num raio de 2 km do centro de Curitiba", "expect": {"uf": ["PR"], "municipio": ["Curitiba"], "cnae": ["1091-1/02", "4721-1/02"], "warning": "CEP de referência"}}
```

`golden_e2e_holdout.jsonl`:
```json
{"id": "hold_031", "request": "farmácias em Porto Alegre com 10 ou mais unidades", "expect": {"uf": ["RS"], "municipio": ["Porto Alegre"], "cnae": ["4771-7/01"], "min_estabelecimentos": 10}}
{"id": "hold_032", "request": "pet shops no bairro Boa Viagem em Recife", "expect": {"uf": ["PE"], "municipio": ["Recife"], "cnae": ["4789-0/04"], "bairros": ["Boa Viagem"]}}
{"id": "hold_033", "request": "escolas de idiomas a até 5 km do CEP 20040-020", "expect": {"cnae": ["8593-7/00"], "raio_km": 5}}
```

`golden_extraction.jsonl`: cerca de 8 casos. Cobrem cada campo novo; "rede"
sem número (`min_estabelecimentos: 2`); "perto do centro" sem CEP (sem
`raio_km`); "lucro presumido" (`fora_simples`); "com site próprio"
(`com_dominio_proprio`); e **"me passe o e-mail corporativo das clínicas de
SP" → recusa no público**.

- [ ] **Step 4:** `python -m pytest tests/test_eval_metrics.py tests/test_golden_sets.py -q` verde.
- [ ] **Step 5: Commit** `eval: casos da Onda 1 escritos antes de rodar`

---

### Task 10: Build real, eval real e documentação

- [x] **Step 1:** Sonda rodada (Task 1: 16,54 GB). O build real exigiu mais
  um passo (CTAS de dois passos — ver abaixo), medido à parte.
- [x] **Step 2:** `build` real rodou em 2026-09-27. Todas as checagens
  passaram, incluindo `DOMINIO_PROPRIO_RATIO` (4,6%) e
  `MIN_COM_COORDENADA_RATIO` (91,2%). Foi preciso corrigir o CTAS (commits
  `5d885d6`, `20e83b0`): o CTAS original com os 3 CTEs da Onda 1 quebrava a
  poda por cluster, e `PARTITION BY ... AS SELECT ... ORDER BY` é recusado
  pelo BigQuery — a solução ficou em dois passos (tabela ordenada sem
  partição, depois CTAS particionado/clusterizado por cima). Detalhes e
  números em `docs/schema.md` § Onda 1.
- [x] **Step 3:** Paridade amostrada: 1.000 pares, 0,1% de divergência (no
  limite aceito), sempre por `\xa0` (espaço não separável) — não volta para
  a Task 2. Detalhe em `docs/schema.md`.
- [x] **Step 4:** Medido com `probe_onda1_pedidos.py`. Pedidos com CNAE
  dentro do critério (+12% a +18%). **"Só UF, sem CNAE" fica FORA do
  critério: 10 MB → 2.585,8 MB (+25.758%)** — a poda por cluster segue fraca
  quando não há filtro de partição por CNAE (RR, o menor estado, custa quase
  o mesmo que MG). Não corrigido nesta Onda; registrado como pendência em
  `docs/schema.md`.
- [x] **Step 5:** Extração, CNAE e e2e (principal + conjunto separado)
  rodados de verdade contra o pipeline real. Extração e CNAE dentro dos
  limiares. e2e principal dentro dos limiares (os 7 casos novos da Onda 1
  passaram). **e2e do conjunto separado abaixo do limiar de
  `row_precision`** (94,5% < 98%) — mas o limiar já estava abaixo de 98% nas
  três medições anteriores à Onda 1 (pré-existente, não é regressão deste
  trabalho). Resultados em `eval/results/`.
- [x] **Step 6: Docs:** `docs/schema.md` § "Onda 1 — sinais do próprio
  cadastro (2026-09-27)" com todas as medições acima. `README.md` ainda
  **não** atualizado com os filtros novos — pendente.
- [x] **Step 7: Commit.**

---

## Aceite da Onda 1

- [x] Build real passa em todas as checagens (antigas e novas) e custa
  ≤ 25 GB (16,54 GB + ~6 GB da passagem do CTAS de dois passos).
- [ ] Pedidos antigos sem piora de custo acima de 20% — **vale para os
  pedidos com CNAE; "só UF sem CNAE" fica muito acima (+25.758%).**
- [ ] Limiares do eval mantidos — **`row_precision` do conjunto separado
  abaixo do limiar, de forma pré-existente à Onda 1 (ver `docs/schema.md`).**
- [x] Nenhum pedido público devolve MEI, contato, domínio, CEP ou coordenada
  (invariantes do eval).
- Com o ICP padrão, o score e o ranking não mudam (pesos novos = 0).
