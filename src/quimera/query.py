"""Query parametrizada sobre a base pública de CNPJ (Base dos Dados).

Regras inegociáveis:
- O LLM nunca escreve SQL: este módulo monta a query a partir de LeadFilters.
- Toda execução passa por dry run obrigatório + ``maximum_bytes_billed``.
- Valores do usuário vão SEMPRE como parâmetros nomeados, nunca interpolados.
- Toda query filtra ``data`` (snapshot mensal): as tabelas empilham ~45 snapshots
  e sem o filtro cada empresa aparece ~45x e o custo explode (~132 GB vs ~1,7 GB;
  docs/schema.md).

Nomes de tabelas/colunas validados na Fase 0 contra o BigQuery (docs/schema.md).
Pendências marcadas com PENDENTE.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping

from .filters import LeadFilters
from .policy import Policy
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

COL_CNPJ_BASICO = "cnpj_basico"
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
COL_OPCAO_MEI = (
    "opcao_mei"  # INTEGER; valores 0/1 presumidos (PENDENTE item 3 do schema.md)
)
COL_CORREIO_ELETRONICO = "email"
COL_TELEFONE = "telefone_1"
COL_DATA_SNAPSHOT = "data"  # coluna de partição (snapshots mensais completos)

# Natureza jurídica de Empresário Individual — excluída no deploy público.
# Confirmado no diretório br_bd_diretorios_brasil.natureza_juridica:
# 2135 = "Empresário (Individual)".
NATUREZA_EMPRESARIO_INDIVIDUAL = "2135"

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

# Fase 0: porte só distingue 1=Micro, 3=Pequeno Porte, 5=Demais. "media" e
# "grande" são indistinguíveis (ambas caem em '5') — PENDENTE decisão de produto
# (item 2 do schema.md).
PORTE_LABEL_TO_CODES: dict[str, tuple[str, ...]] = {
    "micro": ("1",),
    "pequena": ("3",),
    "media": ("5",),
    "grande": ("5",),
}
PORTE_CODES_TO_LABELS: dict[str, str] = {
    "1": "micro",
    "3": "pequena",
    "5": "demais",
}
# Tradução do porte para o SELECT (o resultado usa rótulos, não códigos).
PORTE_SELECT_EXPR = (
    "CASE emp."
    + COL_PORTE
    + " "
    + " ".join(
        f"WHEN '{code}' THEN '{label}'" for code, label in PORTE_CODES_TO_LABELS.items()
    )
    + " ELSE NULL END"
)

DEFAULT_MAX_BYTES_BILLED = 5 * 1024**3  # 5 GiB; ajustar após dry runs reais

# Mapeamento de rótulos de contato do policy para colunas reais do dataset.
CONTACT_FIELD_COLUMNS = {
    "correio_eletronico": COL_CORREIO_ELETRONICO,
    "telefone": COL_TELEFONE,
}


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
    snapshots: Mapping[str, date],
) -> QuerySpec:
    """Monta SQL parametrizado a partir dos filtros (já passados por apply_policy).

    ``snapshots`` é obrigatório: data da última partição de cada tabela em
    ``SNAPSHOT_TABLES`` (use ``resolve_latest_snapshots``). Sem isso, a query
    leria ~45 snapshots mensais (~132 GB) — por isso o parâmetro não tem default.
    """
    missing = [table for table in SNAPSHOT_TABLES if table not in snapshots]
    if missing:
        raise ValueError(
            f"Snapshots ausentes para: {missing}. "
            "Resolva com resolve_latest_snapshots() antes de montar a query."
        )

    select_cols = [
        f"est.{COL_CNPJ_BASICO}",
        f"emp.{COL_RAZAO_SOCIAL}",
        f"est.{COL_NOME_FANTASIA}",
        f"est.{COL_SIGLA_UF}",
        f"est.{COL_ID_MUNICIPIO}",
        f"mun.{COL_NOME_MUNICIPIO} AS municipio",
        f"est.{COL_CNAE_PRINCIPAL}",
        f"est.{COL_DATA_INICIO_ATIVIDADE}",
        f"emp.{COL_CAPITAL_SOCIAL}",
        f"{PORTE_SELECT_EXPR} AS porte",
    ]
    if policy.allow_mei:
        select_cols.append(f"COALESCE(sim.{COL_OPCAO_MEI}, 0) AS opcao_mei")
    for contact_field in policy.contact_fields:
        select_cols.append(
            f"est.{CONTACT_FIELD_COLUMNS[contact_field]} AS {contact_field}"
        )

    where: list[str] = [
        f"est.{COL_SITUACAO_CADASTRAL} = @situacao_ativa",
        # Snapshot mensal: cada tabela particionada na SUA última partição
        # (empresas pode atrasar em relação a estabelecimentos; um único
        # snapshot compartilhado deixaria o join silenciosamente vazio).
        f"est.{COL_DATA_SNAPSHOT} = @snapshot_est",
        f"emp.{COL_DATA_SNAPSHOT} = @snapshot_emp",
    ]
    params: list[QueryParam] = [
        QueryParam("situacao_ativa", "STRING", SITUACAO_CADASTRAL_ATIVA),
        QueryParam("snapshot_est", "DATE", snapshots["estabelecimentos"]),
        QueryParam("snapshot_emp", "DATE", snapshots["empresas"]),
    ]

    if filters.ufs:
        where.append(f"est.{COL_SIGLA_UF} IN UNNEST(@ufs)")
        params.append(QueryParam("ufs", "ARRAY<STRING>", list(filters.ufs)))

    if filters.municipio_ids:
        # ids resolvidos por lookup no diretório de municípios — nunca vindos do LLM.
        where.append(f"est.{COL_ID_MUNICIPIO} IN UNNEST(@municipio_ids)")
        params.append(
            QueryParam("municipio_ids", "ARRAY<STRING>", list(filters.municipio_ids))
        )

    if filters.cnae_codes:
        where.append(f"est.{COL_CNAE_PRINCIPAL} IN UNNEST(@cnae_codes)")
        # A base guarda o código sem máscara ("8630501"); filters/índice/golden
        # usam a forma oficial "8630-5/01". Normaliza aqui, na fronteira.
        params.append(
            QueryParam(
                "cnae_codes",
                "ARRAY<STRING>",
                [_unmask_cnae(code) for code in filters.cnae_codes],
            )
        )

    if filters.min_age_years is not None:
        where.append(
            f"DATE_DIFF(CURRENT_DATE(), est.{COL_DATA_INICIO_ATIVIDADE}, YEAR)"
            " >= @min_age_years"
        )
        params.append(QueryParam("min_age_years", "INT64", filters.min_age_years))

    if filters.max_age_years is not None:
        where.append(
            f"DATE_DIFF(CURRENT_DATE(), est.{COL_DATA_INICIO_ATIVIDADE}, YEAR)"
            " <= @max_age_years"
        )
        params.append(QueryParam("max_age_years", "INT64", filters.max_age_years))

    if filters.min_capital is not None:
        where.append(f"emp.{COL_CAPITAL_SOCIAL} >= @min_capital")
        params.append(QueryParam("min_capital", "FLOAT64", filters.min_capital))

    if filters.portes:
        # Rótulos do usuário (micro/pequena/media/grande) -> códigos do dataset.
        codes = [
            code for label in filters.portes for code in PORTE_LABEL_TO_CODES[label]
        ]
        where.append(f"emp.{COL_PORTE} IN UNNEST(@portes)")
        params.append(QueryParam("portes", "ARRAY<STRING>", codes))

    exclude_mei = (not policy.allow_mei) or (not filters.include_mei)
    if exclude_mei:
        # Público: sem MEI e sem empresário individual (pessoa natural).
        where.append(f"COALESCE(sim.{COL_OPCAO_MEI}, 0) != 1")
        where.append(f"emp.{COL_NATUREZA_JURIDICA} != @natureza_empresario_individual")
        params.append(
            QueryParam(
                "natureza_empresario_individual",
                "STRING",
                NATUREZA_EMPRESARIO_INDIVIDUAL,
            )
        )

    limit = min(filters.limit, policy.max_rows)
    params.append(QueryParam("limit", "INT64", limit))

    sql = (
        "SELECT\n  " + ",\n  ".join(select_cols) + "\n"
        f"FROM {TABLE_ESTABELECIMENTOS} AS est\n"
        f"JOIN {TABLE_EMPRESAS} AS emp USING ({COL_CNPJ_BASICO})\n"
        f"LEFT JOIN {TABLE_SIMPLES} AS sim USING ({COL_CNPJ_BASICO})\n"
        f"LEFT JOIN {TABLE_DIRETORIO_MUNICIPIOS} AS mun"
        f" ON mun.{COL_ID_MUNICIPIO} = est.{COL_ID_MUNICIPIO}\n"
        "WHERE\n  " + "\n  AND ".join(where) + "\n"
        "LIMIT @limit"
    )
    return QuerySpec(sql=sql, params=tuple(params))


def _to_bq_parameters(params: tuple[QueryParam, ...]) -> list[Any]:
    from google.cloud import bigquery  # lazy import — extra ``gcp``

    bq_params = []
    for p in params:
        if p.type.startswith("ARRAY<"):
            bq_params.append(bigquery.ArrayQueryParameter(p.name, "STRING", p.value))
        else:
            bq_params.append(bigquery.ScalarQueryParameter(p.name, p.type, p.value))
    return bq_params


def _default_client() -> Any:
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


def resolve_municipality_ids(
    names: list[str],
    *,
    client: Any | None = None,
) -> dict[str, str]:
    """Resolve nomes de municípios (como escritos pelo usuário) para código IBGE.

    Lookup na tabela de diretório — nunca confiamos em código inventado pelo LLM.
    A tabela é pequena (~5,5 mil municípios); lê-se inteira e casa no cliente com
    normalização (sem acento, maiúscula), então "santo andre" acha "Santo André".
    Devolve apenas os nomes resolvidos: ``{nome_digitado: id_ibge}``.
    """
    client = client or _default_client()
    sql = (
        f"SELECT {COL_NOME_MUNICIPIO}, {COL_ID_MUNICIPIO}\n"
        f"FROM {TABLE_DIRETORIO_MUNICIPIOS}"
    )
    job = client.query(sql)
    lookup = {
        normalize_name(row[COL_NOME_MUNICIPIO]): str(row[COL_ID_MUNICIPIO])
        for row in job.result()
    }
    return {
        name: lookup[key] for name in names if (key := normalize_name(name)) in lookup
    }


def run_query(
    spec: QuerySpec,
    *,
    client: Any | None = None,
    max_bytes_billed: int | None = None,
) -> QueryResult:
    """Executa com dry run obrigatório + maximum_bytes_billed.

    Se o dry run estimar acima do teto, a consulta é recusada antes de rodar.
    """
    from google.cloud import bigquery  # lazy import — extra ``gcp``

    max_bytes = max_bytes_billed or int(
        os.environ.get("MAX_BYTES_BILLED", DEFAULT_MAX_BYTES_BILLED)
    )
    client = client or _default_client()
    bq_params = _to_bq_parameters(spec.params)

    dry_run_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    dry_run_job = client.query(spec.sql, job_config=dry_run_config)
    estimated = dry_run_job.total_bytes_processed
    # Fase 0 (PENDENTE 4 do schema.md): o dry run destas tabelas devolve None
    # em vez de estimativa. None NÃO pode quebrar a execução — a barreira dura
    # continua sendo o maximum_bytes_billed do job real, que o BigQuery recusa
    # se a consulta ultrapassar.
    if estimated is not None and estimated > max_bytes:
        raise BytesBudgetExceededError(
            f"Consulta recusada: dry run estimou {estimated} bytes, "
            f"acima do teto de {max_bytes} bytes (MAX_BYTES_BILLED). "
            "Refine os filtros (UF, município, CNAE) para reduzir o volume."
        )

    job_config = bigquery.QueryJobConfig(
        query_parameters=bq_params,
        maximum_bytes_billed=max_bytes,
    )
    job = client.query(spec.sql, job_config=job_config)
    rows = [dict(row) for row in job.result()]
    return QueryResult(
        rows=rows,
        bytes_processed=job.total_bytes_processed or 0,
        bytes_billed=job.total_bytes_billed or 0,
    )
