"""Query parametrizada sobre a tabela própria de estabelecimentos ativos.

A consulta de leads NÃO lê a Base dos Dados direto: lá cada consulta custa
~13 GB (filtros não reduzem bytes; docs/schema.md). ``quimera.dados build``
materializa mensalmente o snapshot mais recente numa tabela enxuta,
clusterizada por UF, município e CNAE; ``build_query`` lê essa tabela.

Regras inegociáveis:
- O LLM nunca escreve SQL: este módulo monta a query a partir de LeadFilters.
- Toda execução passa por estimativa prévia obrigatória + ``maximum_bytes_billed``
  (o dry run não estima as tabelas de CNPJ — ver ``run_query``).
- Valores do usuário vão SEMPRE como parâmetros nomeados, nunca interpolados.
- Leitura direta da Base dos Dados (materialização, descoberta de snapshot)
  filtra ``data``: as tabelas empilham ~45 snapshots e sem o filtro cada
  empresa aparece ~45x e o custo explode (~132 GB; docs/schema.md).

Nomes de tabelas/colunas e qualidade dos dados medidos contra o BigQuery
(docs/schema.md).
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from datetime import date
from typing import Any

from .filters import VALID_REGIMES, LeadFilters
from .policy import Policy
from .score import ICPConfig
from .text import normalize_name

# ---------------------------------------------------------------------------
# Tabelas e colunas — validados na Fase 0 (docs/schema.md).
# ---------------------------------------------------------------------------
DATASET = "basedosdados.br_me_cnpj"
TABLE_ESTABELECIMENTOS = f"`{DATASET}.estabelecimentos`"
TABLE_EMPRESAS = f"`{DATASET}.empresas`"
TABLE_SIMPLES = f"`{DATASET}.simples`"  # não particionada
# Diretório de municípios (lookup nome -> código IBGE); o LLM devolve nome, nunca código.
TABLE_DIRETORIO_MUNICIPIOS = "`basedosdados.br_bd_diretorios_brasil.municipio`"
TABLE_DIRETORIO_CEP = "`basedosdados.br_bd_diretorios_brasil.cep`"

COL_CNPJ = "cnpj"  # 14 dígitos — identifica o estabelecimento (matriz ou filial)
COL_CNPJ_BASICO = "cnpj_basico"  # 8 dígitos — identifica a empresa
COL_MATRIZ_FILIAL = "identificador_matriz_filial"  # 1 = matriz, 2 = filial
COL_SITUACAO_CADASTRAL = "situacao_cadastral"
SITUACAO_CADASTRAL_ATIVA = "2"  # dicionário: chave de 1 dígito, sem zero à esquerda
COL_SIGLA_UF = "sigla_uf"
COL_ID_MUNICIPIO = "id_municipio"
COL_NOME_MUNICIPIO = "nome"  # coluna de nome no diretório
COL_CNAE_PRINCIPAL = "cnae_fiscal_principal"
COL_DATA_INICIO_ATIVIDADE = "data_inicio_atividade"  # DATE
COL_CAPITAL_SOCIAL = "capital_social"  # FLOAT
COL_PORTE = "porte"  # códigos 0/1/3/5 — ver PORTE_LABEL_TO_CODES
COL_RAZAO_SOCIAL = "razao_social"
COL_NOME_FANTASIA = "nome_fantasia"
COL_NATUREZA_JURIDICA = "natureza_juridica"
COL_OPCAO_MEI = "opcao_mei"  # INTEGER 0/1 (medido; simples tem 1 linha por cnpj_basico)
COL_CORREIO_ELETRONICO = "email"
COL_DDD = "ddd_1"
COL_TELEFONE = "telefone_1"  # sem DDD na base — a tabela de contatos concatena
COL_DATA_SNAPSHOT = "data"  # coluna de partição (snapshots mensais completos)
COL_OPCAO_SIMPLES = "opcao_simples"  # INTEGER 0/1
COL_CEP = "cep"
COL_BAIRRO = "bairro"
COL_CENTROIDE = "centroide"  # GEOGRAPHY no diretório de CEP

# Natureza jurídica de Empresário Individual — excluída no deploy público.
# Confirmado no diretório br_bd_diretorios_brasil.natureza_juridica:
# 2135 = "Empresário (Individual)".
NATUREZA_EMPRESARIO_INDIVIDUAL = "2135"
# Primeiro dígito da natureza jurídica: 1 = administração pública,
# 2 = entidade empresarial, 3 = sem fins lucrativos, 4 = pessoa física,
# 5 = organização internacional.
NATUREZA_PREFIXO_EMPRESARIAL = "2"
# 4xxx é pessoa física (ex.: 4120 produtor rural, ~0,7 M ativos) — dado pessoal.
NATUREZA_PREFIXO_PESSOA_FISICA = "4"

# Valor sentinela de capital social (124 empresas com exatamente este valor,
# medido em 2026-09-26) — tratado como "não informado", assim como 0.
CAPITAL_SOCIAL_SENTINELA = 999_999_999_999.0

# Tabelas particionadas por snapshot mensal — build_query exige a data de cada uma.
SNAPSHOT_TABLES = ("estabelecimentos", "empresas")

# Janela da descoberta de snapshot: sondas VAZIAS custam 0 bytes (pruning de
# partição — medido no real), então a descoberta recua janela a janela até a
# primeira não-vazia. 100 dias ≈ até 4 snapshots mensais por tabela.
SNAPSHOT_DISCOVERY_WINDOW_DAYS = 100
# Teto por sonda: coluna data ≈ 1,6 GiB por partição por tabela (medido);
# 4 partições × 2 tabelas ≈ 13 GiB — 16 GiB de margem.
SNAPSHOT_DISCOVERY_MAX_BYTES = 16 * 1024**3
# Janelas que recuem até cobrir o início do dataset (~2021) — vazias não custam.
SNAPSHOT_DISCOVERY_MAX_STEPS = 24

# Porte só distingue 1=Micro, 3=Pequeno Porte, 5=Demais. "media" e "grande"
# são indistinguíveis: ambas viram '5' restrito a entidades empresariais (2xxx).
# Sem essa restrição, 53% do '5' ativo é associação, condomínio, igreja, órgão
# público ou pessoa física (medido em 2026-09-26; docs/schema.md).
PORTE_LABEL_TO_CODES: dict[str, tuple[str, ...]] = {
    "micro": ("1",),
    "pequena": ("3",),
}
PORTE_DEMAIS = "5"
PORTE_LABELS_DEMAIS = frozenset({"media", "grande"})
PORTE_CODES_TO_LABELS: dict[str, str] = {
    "1": "micro",
    "3": "pequena",
    "5": "demais",
}
# Tradução do porte para o SELECT (o resultado usa rótulos, não códigos).
PORTE_SELECT_EXPR = (
    "CASE t."
    + COL_PORTE
    + " "
    + " ".join(
        f"WHEN '{code}' THEN '{label}'" for code, label in PORTE_CODES_TO_LABELS.items()
    )
    + " ELSE NULL END"
)

DEFAULT_MAX_BYTES_BILLED = 5 * 1024**3  # 5 GiB

# Tabela própria (quimera.dados build). Colunas com os nomes finais do resultado.
DEFAULT_LEADS_DATASET = "quimera"
LEADS_TABLE_NAME = "estabelecimentos_ativos"
CONTATOS_TABLE_NAME = "contatos_ativos"  # só no ambiente privado (--contatos)
CEPS_TABLE_NAME = "ceps"  # coordenadas por CEP, do diretório
# Partição da tabela própria: divisão CNAE (2 primeiros dígitos, 1..99).
# O BigQuery aplica o maximum_bytes_billed sobre a estimativa ANTES de rodar,
# e a estimativa só enxerga poda de PARTIÇÃO (clusterização só poda na
# execução): sem partição, toda consulta estimava a tabela inteira (4 GB) e
# custava ~100 MB. Medido em 2026-09-26.
COL_CNAE_DIVISAO = "cnae_divisao"

# Colunas da tabela própria (nomes finais).
COL_REGIME = "regime_tributario"  # 'mei' | 'simples' | 'fora_simples'
COL_N_ESTABELECIMENTOS = "n_estabelecimentos"
COL_BAIRRO_NORM = "bairro_norm"
COL_LATITUDE = "latitude"
COL_LONGITUDE = "longitude"
COL_DOMINIO_PROPRIO = "dominio_proprio"
REGIMES = tuple(sorted(VALID_REGIMES))

# Labels da tabela com a data do snapshot de origem — lidos sem custo.
LABEL_SNAPSHOT = {"estabelecimentos": "snapshot_est", "empresas": "snapshot_emp"}

# Rótulos de contato do policy -> colunas da tabela de contatos.
CONTACT_FIELD_COLUMNS = {
    "correio_eletronico": "correio_eletronico",
    "telefone": "telefone",
}

_TABLE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class LeadsTables:
    """Ids ``projeto.dataset.tabela`` da tabela de leads e das auxiliares."""

    leads: str
    contatos: str
    ceps: str = ""

    def __post_init__(self) -> None:
        # Ids vêm de env/config, nunca do usuário — ainda assim, só o formato
        # esperado entra no SQL (são identificadores, não parâmetros).
        ids = [self.leads, self.contatos]
        if self.ceps:
            ids.append(self.ceps)
        for table_id in ids:
            if not _TABLE_ID_RE.match(table_id):
                raise ValueError(f"Id de tabela inválido: {table_id!r}")
        if not self.ceps:
            # Dataclass frozen: a derivação só é possível com
            # object.__setattr__ (leads já validado, o split é seguro).
            project, dataset, _ = self.leads.split(".")
            object.__setattr__(self, "ceps", f"{project}.{dataset}.{CEPS_TABLE_NAME}")


def resolve_leads_tables(project: str | None = None) -> LeadsTables:
    """Tabelas próprias em ``GOOGLE_CLOUD_PROJECT``.``LEADS_DATASET`` (default quimera)."""
    project = project or os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if not project:
        raise ValueError(
            "GOOGLE_CLOUD_PROJECT não definido — necessário para localizar a "
            "tabela de leads (quimera.dados build)."
        )
    dataset = os.environ.get("LEADS_DATASET", "").strip() or DEFAULT_LEADS_DATASET
    return LeadsTables(
        leads=f"{project}.{dataset}.{LEADS_TABLE_NAME}",
        contatos=f"{project}.{dataset}.{CONTATOS_TABLE_NAME}",
    )


class LeadsTableMissingError(RuntimeError):
    """A tabela de leads não existe ou não tem snapshot — rode quimera.dados build."""


class BytesBudgetExceededError(RuntimeError):
    """Dry run estimou bytes acima do teto — a consulta é recusada."""


def _unmask_cnae(code: str) -> str:
    """Remove a máscara oficial do CNAE ("8630-5/01" -> "8630501").

    A coluna ``cnae_fiscal_principal`` guarda o código sem máscara (medido no
    real), enquanto filters, índice de embeddings e golden set usam a forma
    oficial CNAE 2.3.
    """
    return "".join(ch for ch in code if ch.isdigit())


@dataclass(frozen=True)
class QueryParam:
    """Parâmetro nomeado; convertido para o tipo do BigQuery só na execução."""

    name: str
    type: str  # "STRING", "INT64", "FLOAT64", "ARRAY<STRING>", ...
    value: Any


@dataclass(frozen=True)
class QuerySpec:
    sql: str
    params: tuple[QueryParam, ...] = field(default=())


@dataclass
class QueryResult:
    rows: list[dict]
    bytes_processed: int
    bytes_billed: int


def build_query(
    filters: LeadFilters,
    policy: Policy,
    *,
    tables: LeadsTables,
    icp: ICPConfig | None = None,
) -> QuerySpec:
    """Monta SQL parametrizado a partir dos filtros (já passados por apply_policy).

    Lê a tabela própria (``tables.leads``), que já contém só estabelecimentos
    ativos do snapshot mais recente, cruzados com empresas, simples e
    município. Contatos só entram via ``tables.contatos`` e só quando a policy
    permite. A ordem segue o ``icp`` (mesma regra do score) antes do LIMIT.
    """
    select_cols = [
        # cnpj (14 dígitos) identifica o estabelecimento: com só cnpj_basico,
        # matriz e filiais da mesma empresa sairiam como linhas repetidas.
        f"t.{COL_CNPJ}",
        f"t.{COL_CNPJ_BASICO}",
        "t.matriz_filial",
        f"t.{COL_RAZAO_SOCIAL}",
        f"t.{COL_NOME_FANTASIA}",
        f"t.{COL_SIGLA_UF}",
        f"t.{COL_ID_MUNICIPIO}",
        "t.municipio",
        f"t.{COL_CNAE_PRINCIPAL}",
        f"t.{COL_DATA_INICIO_ATIVIDADE}",
        f"t.{COL_CAPITAL_SOCIAL}",
        f"{PORTE_SELECT_EXPR} AS porte",
        # Dado da empresa (não pessoal); deixa auditável a exclusão de pessoa
        # física e empresário individual no público.
        f"t.{COL_NATUREZA_JURIDICA}",
    ]
    if policy.allow_mei:
        select_cols.append(f"t.{COL_OPCAO_MEI}")
    for contact_field in policy.contact_fields:
        select_cols.append(
            f"c.{CONTACT_FIELD_COLUMNS[contact_field]} AS {contact_field}"
        )

    # Situação ativa e snapshot já foram aplicados na materialização.
    where: list[str] = []
    params: list[QueryParam] = []

    if filters.ufs:
        where.append(f"t.{COL_SIGLA_UF} IN UNNEST(@ufs)")
        params.append(QueryParam("ufs", "ARRAY<STRING>", list(filters.ufs)))

    if filters.municipio_ids:
        # ids resolvidos por lookup no diretório de municípios — nunca vindos do LLM.
        where.append(f"t.{COL_ID_MUNICIPIO} IN UNNEST(@municipio_ids)")
        params.append(
            QueryParam("municipio_ids", "ARRAY<STRING>", list(filters.municipio_ids))
        )

    if filters.cnae_codes:
        # A base guarda o código sem máscara ("8630501"); filters/índice/golden
        # usam a forma oficial "8630-5/01". Normaliza aqui, na fronteira.
        codes = [_unmask_cnae(code) for code in filters.cnae_codes]
        # Filtro na coluna de partição: é o que reduz a estimativa (e o teto).
        where.append(f"t.{COL_CNAE_DIVISAO} IN UNNEST(@cnae_divisoes)")
        params.append(
            QueryParam(
                "cnae_divisoes",
                "ARRAY<INT64>",
                sorted({int(code[:2]) for code in codes if len(code) >= 2}),
            )
        )
        where.append(f"t.{COL_CNAE_PRINCIPAL} IN UNNEST(@cnae_codes)")
        params.append(QueryParam("cnae_codes", "ARRAY<STRING>", codes))

    # Idade em anos COMPLETOS. DATE_DIFF(..., YEAR) conta viradas de ano
    # (31/12/2024 -> 26/09/2026 dá 2), então "mais de 2 anos" aceitaria
    # empresas com 1 ano e 9 meses.
    if filters.min_age_years is not None:
        where.append(
            f"t.{COL_DATA_INICIO_ATIVIDADE}"
            " <= DATE_SUB(CURRENT_DATE(), INTERVAL @min_age_years YEAR)"
        )
        params.append(QueryParam("min_age_years", "INT64", filters.min_age_years))

    if filters.max_age_years is not None:
        # Idade completa <= N  <=>  início > hoje - (N + 1) anos.
        where.append(
            f"t.{COL_DATA_INICIO_ATIVIDADE}"
            " > DATE_SUB(CURRENT_DATE(), INTERVAL @max_age_years + 1 YEAR)"
        )
        params.append(QueryParam("max_age_years", "INT64", filters.max_age_years))

    if filters.min_capital is not None:
        # O sentinela 999.999.999.999 passaria em qualquer mínimo.
        where.append(
            f"t.{COL_CAPITAL_SOCIAL} >= @min_capital"
            f" AND t.{COL_CAPITAL_SOCIAL} < @capital_sentinela"
        )
        params.append(QueryParam("min_capital", "FLOAT64", filters.min_capital))

    if filters.portes:
        # Rótulos do usuário -> códigos do dataset. media/grande viram "Demais"
        # restrito a entidades empresariais (ver PORTE_LABELS_DEMAIS).
        porte_clauses: list[str] = []
        codes = [
            code
            for label in filters.portes
            for code in PORTE_LABEL_TO_CODES.get(label, ())
        ]
        if codes:
            porte_clauses.append(f"t.{COL_PORTE} IN UNNEST(@portes)")
            params.append(QueryParam("portes", "ARRAY<STRING>", codes))
        if PORTE_LABELS_DEMAIS.intersection(filters.portes):
            porte_clauses.append(
                f"(t.{COL_PORTE} = @porte_demais"
                f" AND STARTS_WITH(t.{COL_NATUREZA_JURIDICA}, @natureza_empresarial))"
            )
            params.append(QueryParam("porte_demais", "STRING", PORTE_DEMAIS))
            params.append(
                QueryParam(
                    "natureza_empresarial", "STRING", NATUREZA_PREFIXO_EMPRESARIAL
                )
            )
        where.append("(" + " OR ".join(porte_clauses) + ")")

    if not policy.allow_pessoa_fisica:
        where.append(
            f"NOT STARTS_WITH(t.{COL_NATUREZA_JURIDICA}, @natureza_pessoa_fisica)"
        )
        params.append(
            QueryParam(
                "natureza_pessoa_fisica", "STRING", NATUREZA_PREFIXO_PESSOA_FISICA
            )
        )

    exclude_mei = (not policy.allow_mei) or (not filters.include_mei)
    if exclude_mei:
        # Público: sem MEI e sem empresário individual (pessoa natural).
        where.append(f"t.{COL_OPCAO_MEI} != 1")
        where.append(f"t.{COL_NATUREZA_JURIDICA} != @natureza_empresario_individual")
        params.append(
            QueryParam(
                "natureza_empresario_individual",
                "STRING",
                NATUREZA_EMPRESARIO_INDIVIDUAL,
            )
        )

    ranking, icp_params = _icp_ranking(icp or ICPConfig())
    params.extend(icp_params)

    limit = min(filters.limit, policy.max_rows)
    params.append(QueryParam("limit", "INT64", limit))

    from_clause = f"FROM `{tables.leads}` AS t\n"
    if policy.contact_fields:
        from_clause += f"LEFT JOIN `{tables.contatos}` AS c USING ({COL_CNPJ})\n"
    # QUALIFY exige WHERE/GROUP BY/HAVING na mesma consulta.
    where_clause = "WHERE\n  " + ("\n  AND ".join(where) if where else "TRUE") + "\n"
    sql = (
        "SELECT\n  "
        + ",\n  ".join(select_cols)
        + "\n"
        + from_clause
        + where_clause
        # Um estabelecimento por empresa (o mais bem ranqueado): sem isso,
        # "padarias em SP" devolvia 50 filiais do mesmo grupo varejista.
        + f"QUALIFY ROW_NUMBER() OVER (\n  PARTITION BY t.{COL_CNPJ_BASICO}\n"
        + f"  ORDER BY {ranking}) = 1\n"
        + f"ORDER BY {ranking}"
        + "LIMIT @limit"
    )
    return QuerySpec(sql=sql, params=tuple(params))


def _icp_ranking(icp: ICPConfig) -> tuple[str, list[QueryParam]]:
    """Termos de ordenação com a mesma regra de ``score.score_lead``, em SQL.

    Sem isso, ``LIMIT`` devolvia N linhas QUAISQUER entre milhares e o score
    só reordenava essa amostra arbitrária. Desempate: capital informado maior,
    empresa mais antiga, cnpj (ordem determinística). O sort do pipeline é
    estável, então o desempate do SQL sobrevive entre scores iguais.
    """
    label_to_code = {label: code for code, label in PORTE_CODES_TO_LABELS.items()}
    preferred = [label_to_code[p] for p in icp.preferred_portes if p in label_to_code]
    capital_informado = (
        f"t.{COL_CAPITAL_SOCIAL} > 0 AND t.{COL_CAPITAL_SOCIAL} < @capital_sentinela"
    )
    score = (
        "(\n"
        f"    CASE WHEN t.{COL_PORTE} IN UNNEST(@icp_portes) THEN @icp_w_porte\n"
        f"      WHEN t.{COL_PORTE} IN UNNEST(@icp_portes_conhecidos)"
        " THEN @icp_w_porte * @icp_porte_parcial\n"
        "      ELSE 0 END\n"
        f"    + IF(t.{COL_DATA_INICIO_ATIVIDADE}"
        " <= DATE_SUB(CURRENT_DATE(), INTERVAL @icp_idade_min YEAR),"
        " @icp_w_idade, 0)\n"
        f"    + IF({capital_informado}"
        f" AND t.{COL_CAPITAL_SOCIAL} >= @icp_capital_min, @icp_w_capital, 0)\n"
        f"  ) * IF(t.{COL_OPCAO_MEI} = 1, @icp_fator_mei, 1)"
    )
    ranking = (
        f"\n  {score} DESC,\n"
        f"  IF({capital_informado}, t.{COL_CAPITAL_SOCIAL}, -1) DESC,\n"
        f"  t.{COL_DATA_INICIO_ATIVIDADE} ASC,\n"
        f"  t.{COL_CNPJ}\n"
    )
    params = [
        QueryParam("capital_sentinela", "FLOAT64", CAPITAL_SOCIAL_SENTINELA),
        QueryParam("icp_portes", "ARRAY<STRING>", preferred),
        QueryParam(
            "icp_portes_conhecidos", "ARRAY<STRING>", list(PORTE_CODES_TO_LABELS)
        ),
        QueryParam("icp_w_porte", "FLOAT64", icp.w_porte),
        QueryParam("icp_porte_parcial", "FLOAT64", icp.porte_partial_factor),
        QueryParam("icp_idade_min", "INT64", icp.target_min_age_years),
        QueryParam("icp_w_idade", "FLOAT64", icp.w_age),
        QueryParam("icp_capital_min", "FLOAT64", icp.target_min_capital),
        QueryParam("icp_w_capital", "FLOAT64", icp.w_capital),
        QueryParam("icp_fator_mei", "FLOAT64", icp.mei_factor),
    ]
    return ranking, params


def _to_bq_parameters(params: tuple[QueryParam, ...]) -> list[Any]:
    from google.cloud import bigquery  # lazy import — extra ``gcp``

    bq_params = []
    for p in params:
        if p.type.startswith("ARRAY<"):
            element_type = p.type[len("ARRAY<") : -1]
            bq_params.append(
                bigquery.ArrayQueryParameter(p.name, element_type, p.value)
            )
        else:
            bq_params.append(bigquery.ScalarQueryParameter(p.name, p.type, p.value))
    return bq_params


@lru_cache(maxsize=1)
def _default_client() -> Any:
    """Cliente BigQuery, um por processo (cada criação busca credenciais)."""
    from google.cloud import bigquery  # lazy import — extra ``gcp``

    # O job precisa rodar na mesma região do dataset (US — docs/schema.md).
    return bigquery.Client(
        project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        location=os.environ.get("BQ_LOCATION"),
    )


def resolve_latest_snapshots(*, client: Any | None = None) -> dict[str, date]:
    """Data da última partição (snapshot mensal) de cada tabela em SNAPSHOT_TABLES.

    Ordem de resolução:
    1. ``SNAPSHOT_DATE`` (ISO, ex.: 2026-07-12) — fixa ambas as tabelas, custo
       zero. Útil para CI, eval e para pinar a partição manualmente.
    2. Descoberta por query: ``MAX(data)`` em janelas de
       ``SNAPSHOT_DISCOVERY_WINDOW_DAYS`` dias que recuam até
       ``SNAPSHOT_DISCOVERY_MAX_STEPS`` vezes. Janela vazia custa 0 bytes
       (pruning de partição, medido no real), então recuar até a primeira
       janela não-vazia acha o máximo global sem varrer a coluna ``data``
       inteira (~78 GB por tabela sem janela, medido no real). Cada tabela
       recua de forma independente. ``INFORMATION_SCHEMA.PARTITIONS`` seria
       grátis, mas dá Access Denied com credencial comum em dataset de
       terceiro.

    Partição = snapshot completo do mês (não delta), então a última partição
    isolada já é o universo atual, sem deduplicação.
    """
    client = client or _default_client()

    env_date = os.environ.get("SNAPSHOT_DATE", "").strip()
    if env_date:
        try:
            snapshot = date.fromisoformat(env_date)
        except ValueError as exc:
            raise ValueError(
                f"SNAPSHOT_DATE inválida: {env_date!r} — use formato ISO (2026-07-12)."
            ) from exc
        return {table: snapshot for table in SNAPSHOT_TABLES}

    from datetime import timedelta  # local: só para o cálculo das janelas

    from google.cloud import bigquery  # lazy import — extra ``gcp``

    window = timedelta(days=SNAPSHOT_DISCOVERY_WINDOW_DAYS)
    snapshots: dict[str, date] = {}
    end = date.today() + timedelta(days=1)  # exclusivo; inclui partições de hoje
    for _ in range(SNAPSHOT_DISCOVERY_MAX_STEPS):
        start = end - window
        missing = [table for table in SNAPSHOT_TABLES if table not in snapshots]
        # Literais internos (datas/tabelas nossas), não input do usuário.
        union = "\nUNION ALL\n".join(
            f"SELECT '{table}' AS table_name, MAX(data) AS latest_partition\n"
            f"FROM `{DATASET}.{table}`\n"
            f"WHERE data >= DATE '{start.isoformat()}' AND data < DATE '{end.isoformat()}'"
            for table in missing
        )
        job = client.query(
            union,
            job_config=bigquery.QueryJobConfig(
                maximum_bytes_billed=SNAPSHOT_DISCOVERY_MAX_BYTES
            ),
        )
        for row in job.result():
            latest = row["latest_partition"]
            if latest is None:
                continue
            if not isinstance(latest, date):
                latest = date.fromisoformat(str(latest))
            snapshots[row["table_name"]] = latest
        if len(snapshots) == len(SNAPSHOT_TABLES):
            return snapshots
        end = start

    raise RuntimeError(
        f"Nenhum snapshot encontrado em {SNAPSHOT_DISCOVERY_MAX_STEPS} janelas de "
        f"{SNAPSHOT_DISCOVERY_WINDOW_DAYS} dias para {sorted(set(SNAPSHOT_TABLES) - set(snapshots))} "
        f"em {DATASET}. Verifique BQ_LOCATION e o acesso ao dataset, ou fixe a "
        "partição com a variável SNAPSHOT_DATE (ISO, ex.: 2026-07-12)."
    )


def read_leads_snapshot(
    tables: LeadsTables,
    *,
    client: Any | None = None,
    require_contatos: bool = False,
) -> dict[str, date]:
    """Snapshot de origem da tabela de leads, lido dos labels (sem custo).

    ``require_contatos`` confere também a tabela de contatos (policy com
    campos de contato): sem ela, a consulta falharia com NotFound cru.

    Com o cliente padrão, o resultado fica em cache por
    ``SNAPSHOT_CACHE_TTL_S`` (o build é mensal; a leitura custava ~1,9 s).

    Substitui a descoberta por consulta no caminho do pedido: a descoberta lê a
    coluna ``data`` da Base dos Dados (GBs por chamada) e só roda no build.
    """
    if client is None:
        key = (tables, require_contatos)
        cached = _SNAPSHOT_CACHE.get(key)
        now = time.monotonic()
        if cached and cached[0] > now:
            return cached[1]
        snapshots = _read_leads_snapshot(tables, _default_client(), require_contatos)
        _SNAPSHOT_CACHE[key] = (now + SNAPSHOT_CACHE_TTL_S, snapshots)
        return snapshots
    return _read_leads_snapshot(tables, client, require_contatos)


SNAPSHOT_CACHE_TTL_S = 600
_SNAPSHOT_CACHE: dict[tuple[LeadsTables, bool], tuple[float, dict[str, date]]] = {}


def _read_leads_snapshot(
    tables: LeadsTables, client: Any, require_contatos: bool
) -> dict[str, date]:
    from google.api_core.exceptions import NotFound  # lazy — extra ``gcp``

    try:
        table = client.get_table(tables.leads)
    except NotFound as exc:
        raise LeadsTableMissingError(
            f"Tabela de leads {tables.leads} não existe. "
            "Rode: python -m quimera.dados build"
        ) from exc
    labels = table.labels or {}
    try:
        snapshots = {
            source: date.fromisoformat(labels[label])
            for source, label in LABEL_SNAPSHOT.items()
        }
    except (KeyError, ValueError) as exc:
        raise LeadsTableMissingError(
            f"Tabela de leads {tables.leads} sem label de snapshot válido "
            f"({labels!r}). Rode: python -m quimera.dados build"
        ) from exc
    if require_contatos:
        try:
            client.get_table(tables.contatos)
        except NotFound as exc:
            raise LeadsTableMissingError(
                f"Tabela de contatos {tables.contatos} não existe. "
                "Rode: python -m quimera.dados build --contatos"
            ) from exc
    return snapshots


def _fetch_municipality_directory(client: Any) -> tuple[tuple[str, str, str], ...]:
    sql = (
        f"SELECT {COL_NOME_MUNICIPIO}, {COL_SIGLA_UF}, {COL_ID_MUNICIPIO}\n"
        f"FROM {TABLE_DIRETORIO_MUNICIPIOS}"
    )
    return tuple(
        (row[COL_NOME_MUNICIPIO], row.get(COL_SIGLA_UF), str(row[COL_ID_MUNICIPIO]))
        for row in client.query(sql).result()
    )


@lru_cache(maxsize=1)
def _default_municipality_directory() -> tuple[tuple[str, str, str], ...]:
    # Diretório estático (~5,5 mil linhas): lido uma vez por processo. Relê-lo
    # a cada pedido custava ~2,8 s (medido em 2026-09-26).
    return _fetch_municipality_directory(_default_client())


def resolve_municipality_ids(
    names: list[str],
    *,
    ufs: list[str] | None = None,
    client: Any | None = None,
) -> dict[str, list[str]]:
    """Resolve nomes de municípios (como escritos pelo usuário) para códigos IBGE.

    Lookup na tabela de diretório — nunca confiamos em código inventado pelo LLM.
    A tabela é pequena (~5,5 mil municípios); lê-se inteira e casa no cliente com
    normalização (sem acento, maiúscula), então "santo andre" acha "Santo André".

    Nomes se repetem entre UFs (233 nomes; "Santo André" existe em SP e na PB),
    então cada nome resolve para uma LISTA de códigos: restrita às ``ufs`` do
    pedido quando houver, ou todos os homônimos quando não houver.
    Devolve apenas os nomes resolvidos: ``{nome_digitado: [id_ibge, ...]}``.
    """
    rows = (
        _fetch_municipality_directory(client)
        if client is not None
        else _default_municipality_directory()
    )
    wanted_ufs = set(ufs or ())
    lookup: dict[str, list[str]] = {}
    for nome, uf, id_municipio in rows:
        if wanted_ufs and uf not in wanted_ufs:
            continue
        lookup.setdefault(normalize_name(nome), []).append(id_municipio)
    return {
        name: sorted(lookup[key])
        for name in names
        if (key := normalize_name(name)) in lookup
    }


def resolve_max_bytes_billed(max_bytes_billed: int | None = None) -> int:
    """Teto de bytes por consulta: explícito, ``MAX_BYTES_BILLED`` ou o default."""
    return max_bytes_billed or int(
        os.environ.get("MAX_BYTES_BILLED", DEFAULT_MAX_BYTES_BILLED)
    )


def _is_bytes_limit_error(exc: Exception) -> bool:
    """Erro do BigQuery por estouro do ``maximum_bytes_billed`` do job."""
    errors = getattr(exc, "errors", None) or []
    return any(
        isinstance(err, dict) and err.get("reason") == "bytesBilledLimitExceeded"
        for err in errors
    )


_REQUIRED_BYTES_RE = re.compile(r"(\d+) or higher required")


def _required_bytes(exc: Exception) -> int | None:
    """Bytes exigidos, lidos da mensagem de ``bytesBilledLimitExceeded``."""
    messages = [str(exc)] + [
        str(err.get("message", ""))
        for err in (getattr(exc, "errors", None) or [])
        if isinstance(err, dict)
    ]
    for message in messages:
        match = _REQUIRED_BYTES_RE.search(message)
        if match:
            return int(match.group(1))
    return None


def _budget_error(max_bytes: int, required: int | None) -> BytesBudgetExceededError:
    detail = f"exige {required} bytes, " if required is not None else ""
    return BytesBudgetExceededError(
        f"Consulta recusada: {detail}acima do teto de {max_bytes} bytes "
        "(MAX_BYTES_BILLED). "
        "Refine os filtros (UF, município, CNAE) para reduzir o volume."
    )


def run_query(
    spec: QuerySpec,
    *,
    client: Any | None = None,
    max_bytes_billed: int | None = None,
) -> QueryResult:
    """Executa com ``maximum_bytes_billed``: acima do teto, recusa sem custo.

    O BigQuery confere o teto contra a estimativa ANTES de executar e, ao
    recusar, informa "N or higher required" — esse N vai para a mensagem. Na
    tabela própria, N é o limite superior após a poda de partição (a
    clusterização só poda na execução: 136 MB estimados para 70 MB cobrados,
    medido), e o job informa os bytes cobrados normalmente.

    Não há sonda prévia: na tabela própria o próprio job já é a estimativa, e
    a sonda custava uma ida e volta (~1 s) por pedido. Ela só era necessária
    para consultar a Base dos Dados direto, onde nem o job informa bytes.
    """
    from google.cloud import bigquery  # lazy import — extra ``gcp``

    max_bytes = resolve_max_bytes_billed(max_bytes_billed)
    client = client or _default_client()
    job_config = bigquery.QueryJobConfig(
        query_parameters=_to_bq_parameters(spec.params),
        maximum_bytes_billed=max_bytes,
    )
    try:
        job = client.query(spec.sql, job_config=job_config)
        rows = [dict(row) for row in job.result()]
    except Exception as exc:
        if _is_bytes_limit_error(exc):
            raise _budget_error(max_bytes, _required_bytes(exc)) from exc
        raise
    return QueryResult(
        rows=rows,
        bytes_processed=job.total_bytes_processed or 0,
        bytes_billed=job.total_bytes_billed or 0,
    )
