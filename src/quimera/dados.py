"""Tabela própria de estabelecimentos ativos, materializada da Base dos Dados.

Por quê: consultar ``basedosdados.br_me_cnpj`` direto custa ~13 GB por pedido
— as tabelas só são clusterizadas por ``ano, mes``, então filtros de UF,
município e CNAE não reduzem bytes (medido; docs/schema.md). Uma vez por mês
(a Receita publica snapshots mensais), ``build`` grava o snapshot mais recente
numa tabela enxuta, clusterizada pelos filtros do pipeline.

Fluxo do ``build``:
1. descobre o snapshot mais recente (``resolve_latest_snapshots``);
2. grava ``<tabela>_staging`` com CREATE OR REPLACE ... AS SELECT;
3. roda as checagens de qualidade na staging;
4. só se todas passarem, copia a staging sobre a tabela final (cópia não
   custa) e grava o snapshot nos labels — lidos sem custo a cada pedido;
5. grava a tabela auxiliar ``ceps`` (coordenadas por CEP) e confere o volume.

A tabela de leads NÃO tem colunas de contato. Contatos (e-mail e telefone com
DDD) vão para uma tabela separada, criada só com ``--contatos`` e só no
ambiente privado. O e-mail só é lido no build para derivar o domínio próprio
— contato, domínio, CEP e endereço não saem na tabela (``LEADS_COLUMNS``).

Uso:
    python -m quimera.dados build [--contatos]
    python -m quimera.dados status
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date
from typing import Any

from .query import (
    COL_BAIRRO,
    COL_BAIRRO_NORM,
    COL_CAPITAL_SOCIAL,
    COL_CENTROIDE,
    COL_CEP,
    COL_CNAE_DIVISAO,
    COL_CNAE_PRINCIPAL,
    COL_CNPJ,
    COL_CNPJ_BASICO,
    COL_CORREIO_ELETRONICO,
    COL_DATA_INICIO_ATIVIDADE,
    COL_DATA_SNAPSHOT,
    COL_DDD,
    COL_DOMINIO_PROPRIO,
    COL_ID_MUNICIPIO,
    COL_LATITUDE,
    COL_LONGITUDE,
    COL_MATRIZ_FILIAL,
    COL_NATUREZA_JURIDICA,
    COL_NOME_FANTASIA,
    COL_NOME_MUNICIPIO,
    COL_N_ESTABELECIMENTOS,
    COL_OPCAO_MEI,
    COL_OPCAO_SIMPLES,
    COL_PORTE,
    COL_RAZAO_SOCIAL,
    COL_REGIME,
    COL_SIGLA_UF,
    COL_SITUACAO_CADASTRAL,
    COL_TELEFONE,
    LABEL_SNAPSHOT,
    SITUACAO_CADASTRAL_ATIVA,
    TABLE_DIRETORIO_CEP,
    TABLE_DIRETORIO_MUNICIPIOS,
    TABLE_EMPRESAS,
    TABLE_ESTABELECIMENTOS,
    TABLE_SIMPLES,
    LeadsTables,
    _default_client,
    read_leads_snapshot,
    resolve_latest_snapshots,
    resolve_leads_tables,
)

# Teto da materialização: o build exige 13,17 GB hoje e 16,54 GB com os sinais
# da Onda 1 (sonda sem custo, probe_build_onda1.py, 2026-09-26); 64 GiB dá
# margem sem permitir leitura de vários snapshots (~132 GB por tabela sem
# filtro de partição).
BUILD_MAX_BYTES = 64 * 1024**3
# Checagens leem poucas colunas da tabela própria (~4 GB no total).
CHECK_MAX_BYTES = 8 * 1024**3
STAGING_SUFFIX = "_staging"

# Partição por divisão CNAE (entra na estimativa pré-execução — ver
# COL_CNAE_DIVISAO em query.py) e clusterização pelos demais filtros.
CNAE_DIVISAO_RANGE = (1, 100)  # divisões 01..99
CLUSTER_COLUMNS = (COL_SIGLA_UF, COL_ID_MUNICIPIO, COL_CNAE_PRINCIPAL)

# Limiares das checagens — derivados das medições de 2026-09-26 (27,8 M ativos;
# 0,3% sem município). Folga para a variação mensal, não para dado quebrado.
MIN_ROWS = 20_000_000
MAX_SEM_MUNICIPIO_RATIO = 0.01

# Domínio de e-mail usado por até 4 empresas conta como próprio. Medido em
# 2026-09-26: gmail 12,9 M empresas, contabilizei.com.br 141.903 (e-mail da
# contabilidade), 658.689 domínios exclusivos de 1 empresa e 177.445 de 2 a 4.
# O corte descarta provedores, contabilidades e erros de digitação sem lista.
MAX_EMPRESAS_POR_DOMINIO = 4
# Colunas da tabela de leads, na ordem do SELECT final do build.
LEADS_COLUMNS = (
    "cnpj",
    "cnpj_basico",
    "matriz_filial",
    "razao_social",
    "nome_fantasia",
    "sigla_uf",
    "id_municipio",
    "municipio",
    "cnae_fiscal_principal",
    "cnae_divisao",
    "data_inicio_atividade",
    "capital_social",
    "porte",
    "natureza_juridica",
    "opcao_mei",
    "regime_tributario",
    "n_estabelecimentos",
    "bairro",
    "bairro_norm",
    "latitude",
    "longitude",
    "dominio_proprio",
)
# Medido em 2026-09-26: 905.210 CEPs com centroide no diretório.
MIN_CEPS = 800_000
# Medido em 2026-09-26: 91,2% dos ativos com centroide de CEP.
MIN_COM_COORDENADA_RATIO = 0.85
# Estimado com as medições por domínio (~4% das empresas); o primeiro
# build real (Task 10) fixa o valor medido aqui.
DOMINIO_PROPRIO_RATIO = (0.01, 0.10)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _labels(snapshots: dict[str, date]) -> str:
    pairs = ", ".join(
        f'("{LABEL_SNAPSHOT[source]}", "{snap.isoformat()}")'
        for source, snap in sorted(snapshots.items())
    )
    return f"[{pairs}]"


def build_leads_sql(destination: str, snapshots: dict[str, date]) -> str:
    """CREATE OR REPLACE da tabela de leads a partir de um snapshot.

    Datas e nomes são nossos (resolvidos pela descoberta), não input do usuário.
    Cada tabela particionada é lida na SUA partição: empresas pode atrasar em
    relação a estabelecimentos.

    Três CTEs sobre o mesmo snapshot: ``ativos`` (estabelecimentos ativos,
    com CEP, bairro e domínio do e-mail), ``unidades`` (rede: estabelecimentos
    ativos por cnpj_basico) e ``dominios`` (empresas por domínio, para o corte
    do sinal de domínio próprio). O e-mail é lido SÓ para derivar o domínio —
    contato não sai na tabela (ver ``LEADS_COLUMNS``).
    """
    return (
        f"CREATE OR REPLACE TABLE `{destination}`\n"
        f"PARTITION BY RANGE_BUCKET({COL_CNAE_DIVISAO},"
        f" GENERATE_ARRAY({CNAE_DIVISAO_RANGE[0]}, {CNAE_DIVISAO_RANGE[1]}, 1))\n"
        f"CLUSTER BY {', '.join(CLUSTER_COLUMNS)}\n"
        f"OPTIONS(labels={_labels(snapshots)})\n"
        "AS\n"
        "WITH ativos AS (\n"
        "  SELECT\n"
        f"    {COL_CNPJ},\n"
        f"    {COL_CNPJ_BASICO},\n"
        f"    {COL_MATRIZ_FILIAL},\n"
        f"    {COL_NOME_FANTASIA},\n"
        f"    {COL_SIGLA_UF},\n"
        f"    {COL_ID_MUNICIPIO},\n"
        f"    {COL_CNAE_PRINCIPAL},\n"
        f"    {COL_DATA_INICIO_ATIVIDADE},\n"
        f"    {COL_CEP},\n"
        f"    {COL_BAIRRO},\n"
        f"    LOWER(REGEXP_EXTRACT(TRIM({COL_CORREIO_ELETRONICO}),"
        " r'@([^@\\s]+)$')) AS dominio\n"
        f"  FROM {TABLE_ESTABELECIMENTOS}\n"
        "  WHERE\n"
        f"    {COL_DATA_SNAPSHOT} = DATE"
        f" '{snapshots['estabelecimentos'].isoformat()}'"
        f" AND {COL_SITUACAO_CADASTRAL} = '{SITUACAO_CADASTRAL_ATIVA}'\n"
        "),\n"
        "unidades AS (\n"
        f"  SELECT {COL_CNPJ_BASICO}, COUNT(*) AS {COL_N_ESTABELECIMENTOS}\n"
        f"  FROM ativos GROUP BY {COL_CNPJ_BASICO}\n"
        "),\n"
        "dominios AS (\n"
        f"  SELECT dominio, COUNT(DISTINCT {COL_CNPJ_BASICO}) AS empresas\n"
        "  FROM ativos WHERE dominio IS NOT NULL GROUP BY dominio\n"
        ")\n"
        "SELECT\n"
        f"  est.{COL_CNPJ},\n"
        f"  est.{COL_CNPJ_BASICO},\n"
        f"  CASE est.{COL_MATRIZ_FILIAL} WHEN '1' THEN 'matriz'"
        " WHEN '2' THEN 'filial' ELSE NULL END AS matriz_filial,\n"
        f"  emp.{COL_RAZAO_SOCIAL},\n"
        f"  est.{COL_NOME_FANTASIA},\n"
        f"  est.{COL_SIGLA_UF},\n"
        f"  est.{COL_ID_MUNICIPIO},\n"
        f"  mun.{COL_NOME_MUNICIPIO} AS municipio,\n"
        f"  est.{COL_CNAE_PRINCIPAL},\n"
        f"  SAFE_CAST(SUBSTR(est.{COL_CNAE_PRINCIPAL}, 1, 2) AS INT64)"
        f" AS {COL_CNAE_DIVISAO},\n"
        f"  est.{COL_DATA_INICIO_ATIVIDADE},\n"
        f"  emp.{COL_CAPITAL_SOCIAL},\n"
        f"  emp.{COL_PORTE},\n"
        f"  emp.{COL_NATUREZA_JURIDICA},\n"
        # simples tem 1 linha por cnpj_basico (medido) — o LEFT JOIN não duplica.
        f"  COALESCE(sim.{COL_OPCAO_MEI}, 0) AS {COL_OPCAO_MEI},\n"
        f"  CASE WHEN sim.{COL_OPCAO_MEI} = 1 THEN 'mei'"
        f" WHEN sim.{COL_OPCAO_SIMPLES} = 1 THEN 'simples'"
        f" ELSE 'fora_simples' END AS {COL_REGIME},\n"
        f"  uni.{COL_N_ESTABELECIMENTOS},\n"
        f"  NULLIF(TRIM(est.{COL_BAIRRO}), '') AS {COL_BAIRRO},\n"
        # bairro_norm espelha text.normalize_name: NORMALIZE NFD + remover
        # marcas (= strip_accents) e colapsar espaços (= split/join). Hífens e
        # pontuação ficam — normalize_name também não os remove.
        f"  NULLIF(REGEXP_REPLACE(REGEXP_REPLACE("
        f"NORMALIZE(UPPER(TRIM(est.{COL_BAIRRO})), NFD), r'\\p{{M}}', ''),"
        f" r'\\s+', ' '), '') AS {COL_BAIRRO_NORM},\n"
        f"  ST_Y(dcep.{COL_CENTROIDE}) AS {COL_LATITUDE},\n"
        f"  ST_X(dcep.{COL_CENTROIDE}) AS {COL_LONGITUDE},\n"
        f"  COALESCE(dom.empresas <= {MAX_EMPRESAS_POR_DOMINIO}, FALSE)"
        f" AS {COL_DOMINIO_PROPRIO}\n"
        "FROM ativos AS est\n"
        f"JOIN {TABLE_EMPRESAS} AS emp USING ({COL_CNPJ_BASICO})\n"
        f"JOIN unidades AS uni USING ({COL_CNPJ_BASICO})\n"
        f"LEFT JOIN {TABLE_SIMPLES} AS sim USING ({COL_CNPJ_BASICO})\n"
        f"LEFT JOIN {TABLE_DIRETORIO_MUNICIPIOS} AS mun"
        f" ON mun.{COL_ID_MUNICIPIO} = est.{COL_ID_MUNICIPIO}\n"
        "LEFT JOIN dominios AS dom ON dom.dominio = est.dominio\n"
        f"LEFT JOIN {TABLE_DIRETORIO_CEP} AS dcep ON dcep.{COL_CEP} = est.{COL_CEP}\n"
        "WHERE\n"
        f"  emp.{COL_DATA_SNAPSHOT} = DATE '{snapshots['empresas'].isoformat()}'"
    )


def build_ceps_sql(destination: str) -> str:
    """CREATE OR REPLACE da tabela auxiliar ``ceps``: coordenadas por CEP.

    Materializa ``ST_Y``/``ST_X`` do centroide do diretório de CEPs uma vez
    por build — a consulta por pedido não lida com GEOGRAPHY nem lê o
    diretório. Só CEPs com centroide (905.210 medidos em 2026-09-26).
    """
    return (
        f"CREATE OR REPLACE TABLE `{destination}`\n"
        f"CLUSTER BY {COL_CEP}\n"
        "AS\n"
        "SELECT\n"
        f"  {COL_CEP},\n"
        f"  ST_Y({COL_CENTROIDE}) AS {COL_LATITUDE},\n"
        f"  ST_X({COL_CENTROIDE}) AS {COL_LONGITUDE},\n"
        f"  {COL_ID_MUNICIPIO},\n"
        f"  {COL_SIGLA_UF}\n"
        f"FROM {TABLE_DIRETORIO_CEP}\n"
        f"WHERE {COL_CENTROIDE} IS NOT NULL"
    )


def build_contatos_sql(destination: str, snapshots: dict[str, date]) -> str:
    """Contatos dos estabelecimentos ativos — só para o ambiente privado.

    ``telefone_1`` vem sem DDD na base: sem concatenar ``ddd_1`` o número é
    inutilizável para contato.
    """
    return (
        f"CREATE OR REPLACE TABLE `{destination}`\n"
        f"CLUSTER BY {COL_CNPJ}\n"
        f"OPTIONS(labels={_labels(snapshots)})\n"
        "AS\n"
        "SELECT\n"
        f"  {COL_CNPJ},\n"
        f"  NULLIF(TRIM({COL_CORREIO_ELETRONICO}), '') AS correio_eletronico,\n"
        f"  NULLIF(CONCAT(COALESCE(TRIM({COL_DDD}), ''),"
        f" COALESCE(TRIM({COL_TELEFONE}), '')), '') AS telefone\n"
        f"FROM {TABLE_ESTABELECIMENTOS}\n"
        "WHERE\n"
        f"  {COL_DATA_SNAPSHOT} = DATE '{snapshots['estabelecimentos'].isoformat()}'\n"
        f"  AND {COL_SITUACAO_CADASTRAL} = '{SITUACAO_CADASTRAL_ATIVA}'"
    )


def quality_checks_sql(table: str) -> str:
    """Estatísticas de qualidade da tabela própria, numa única leitura."""
    return (
        "SELECT\n"
        "  COUNT(*) AS linhas,\n"
        f"  COUNT(DISTINCT {COL_CNPJ}) AS cnpj_distintos,\n"
        f"  COUNTIF({COL_CNPJ} IS NULL OR LENGTH({COL_CNPJ}) != 14) AS cnpj_invalido,\n"
        f"  COUNTIF({COL_SIGLA_UF} IS NULL) AS sem_uf,\n"
        f"  COUNTIF({COL_ID_MUNICIPIO} IS NULL OR municipio IS NULL) AS sem_municipio,\n"
        f"  COUNTIF({COL_CNAE_PRINCIPAL} IS NULL"
        f" OR LENGTH({COL_CNAE_PRINCIPAL}) != 7) AS cnae_invalido,\n"
        f"  COUNTIF({COL_DATA_INICIO_ATIVIDADE} IS NULL) AS sem_inicio,\n"
        f"  COUNTIF({COL_DATA_INICIO_ATIVIDADE} > CURRENT_DATE()) AS inicio_futuro,\n"
        f"  COUNTIF({COL_OPCAO_MEI} NOT IN (0, 1)) AS mei_invalido,\n"
        f"  COUNTIF({COL_PORTE} IS NULL) AS sem_porte,\n"
        f"  COUNTIF({COL_REGIME} IS NULL) AS sem_regime,\n"
        f"  COUNTIF(({COL_REGIME} = 'mei') != ({COL_OPCAO_MEI} = 1))"
        " AS regime_incoerente,\n"
        f"  COUNTIF({COL_N_ESTABELECIMENTOS} IS NULL"
        f" OR {COL_N_ESTABELECIMENTOS} < 1) AS unidades_invalidas,\n"
        f"  COUNTIF({COL_LATITUDE} IS NOT NULL) AS com_coordenada,\n"
        f"  COUNTIF({COL_LATITUDE} NOT BETWEEN -34 AND 6"
        # Limite leste -28 (não -34): inclui as ilhas atlânticas — Noronha
        # ~-32,4, Trindade ~-29,3 — sem abrir mão da detecção de outliers.
        f" OR {COL_LONGITUDE} NOT BETWEEN -74 AND -28) AS fora_do_brasil,\n"
        f"  COUNTIF({COL_DOMINIO_PROPRIO}) AS com_dominio_proprio\n"
        f"FROM `{table}`"
    )


def evaluate_checks(stats: dict[str, int]) -> list[Check]:
    """Checagens de qualidade sobre as estatísticas da tabela recém-gravada."""
    linhas = stats["linhas"]
    ratio_sem_mun = stats["sem_municipio"] / linhas if linhas else 1.0
    ratio_coordenada = stats["com_coordenada"] / linhas if linhas else 0.0
    ratio_dominio = stats["com_dominio_proprio"] / linhas if linhas else 0.0
    return [
        Check(
            "volume",
            linhas >= MIN_ROWS,
            f"{linhas:,} estabelecimentos ativos (mínimo {MIN_ROWS:,})",
        ),
        Check(
            "cnpj único",
            stats["cnpj_distintos"] == linhas,
            f"{stats['cnpj_distintos']:,} distintos em {linhas:,} linhas",
        ),
        Check(
            "cnpj com 14 dígitos",
            stats["cnpj_invalido"] == 0,
            f"{stats['cnpj_invalido']:,} inválidos",
        ),
        Check("uf presente", stats["sem_uf"] == 0, f"{stats['sem_uf']:,} sem UF"),
        Check(
            "município presente",
            ratio_sem_mun <= MAX_SEM_MUNICIPIO_RATIO,
            f"{stats['sem_municipio']:,} sem município ({ratio_sem_mun:.2%};"
            f" máximo {MAX_SEM_MUNICIPIO_RATIO:.0%})",
        ),
        Check(
            "cnae com 7 dígitos",
            stats["cnae_invalido"] == 0,
            f"{stats['cnae_invalido']:,} inválidos",
        ),
        Check(
            "início de atividade válido",
            stats["sem_inicio"] == 0 and stats["inicio_futuro"] == 0,
            f"{stats['sem_inicio']:,} sem data, {stats['inicio_futuro']:,} no futuro",
        ),
        Check(
            "opcao_mei 0/1",
            stats["mei_invalido"] == 0,
            f"{stats['mei_invalido']:,} fora de 0/1",
        ),
        Check(
            "porte presente",
            stats["sem_porte"] == 0,
            f"{stats['sem_porte']:,} sem porte",
        ),
        Check(
            "regime presente",
            stats["sem_regime"] == 0,
            f"{stats['sem_regime']:,} sem regime tributário",
        ),
        Check(
            "regime coerente com MEI",
            stats["regime_incoerente"] == 0,
            f"{stats['regime_incoerente']:,} divergem de opcao_mei",
        ),
        Check(
            "unidades válidas",
            stats["unidades_invalidas"] == 0,
            f"{stats['unidades_invalidas']:,} com n_estabelecimentos inválido",
        ),
        Check(
            "coordenada presente",
            ratio_coordenada >= MIN_COM_COORDENADA_RATIO,
            f"{stats['com_coordenada']:,} com coordenada ({ratio_coordenada:.1%};"
            f" mínimo {MIN_COM_COORDENADA_RATIO:.0%})",
        ),
        Check(
            "coordenada no Brasil",
            stats["fora_do_brasil"] == 0,
            f"{stats['fora_do_brasil']:,} fora da caixa envolvente do Brasil",
        ),
        Check(
            "domínio próprio plausível",
            DOMINIO_PROPRIO_RATIO[0] <= ratio_dominio <= DOMINIO_PROPRIO_RATIO[1],
            f"{stats['com_dominio_proprio']:,} com domínio próprio"
            f" ({ratio_dominio:.1%}; faixa {DOMINIO_PROPRIO_RATIO[0]:.0%} a"
            f" {DOMINIO_PROPRIO_RATIO[1]:.0%})",
        ),
    ]


def run_quality_checks(table: str, *, client: Any) -> list[Check]:
    from google.cloud import bigquery  # lazy import — extra ``gcp``

    job = client.query(
        quality_checks_sql(table),
        job_config=bigquery.QueryJobConfig(maximum_bytes_billed=CHECK_MAX_BYTES),
    )
    stats = dict(next(iter(job.result())))
    return evaluate_checks(stats)


def run_ceps_check(table: str, *, client: Any) -> Check:
    """Volume da tabela de ``ceps`` recém-gravada (checagem pós-gravação)."""
    from google.cloud import bigquery  # lazy import — extra ``gcp``

    job = client.query(
        f"SELECT COUNT(*) AS linhas FROM `{table}`",
        job_config=bigquery.QueryJobConfig(maximum_bytes_billed=CHECK_MAX_BYTES),
    )
    linhas = dict(next(iter(job.result())))["linhas"]
    return Check(
        "volume de ceps",
        linhas >= MIN_CEPS,
        f"{linhas:,} CEPs com centroide (mínimo {MIN_CEPS:,})",
    )


class QualityCheckError(RuntimeError):
    """Alguma checagem falhou — a tabela final não foi substituída."""

    def __init__(self, checks: list[Check]):
        self.checks = checks
        failed = ", ".join(c.name for c in checks if not c.ok)
        super().__init__(f"Checagens de qualidade falharam: {failed}")


class PostPromotionCheckError(RuntimeError):
    """Checagem pós-promoção falhou — a tabela de leads JÁ FOI promovida."""

    def __init__(self, checks: list[Check]):
        self.checks = checks
        failed = ", ".join(c.name for c in checks if not c.ok)
        super().__init__(
            f"Checagem pós-promoção falhou: {failed}. A tabela de leads já "
            "foi promovida e permanece com este snapshot."
        )


def _run_ddl(sql: str, *, client: Any) -> None:
    from google.cloud import bigquery  # lazy import — extra ``gcp``

    client.query(
        sql, job_config=bigquery.QueryJobConfig(maximum_bytes_billed=BUILD_MAX_BYTES)
    ).result()


def _ensure_dataset(table_id: str, *, client: Any) -> None:
    from google.cloud import bigquery  # lazy import — extra ``gcp``

    project, dataset, _ = table_id.split(".")
    ds = bigquery.Dataset(f"{project}.{dataset}")
    # Mesma região da Base dos Dados (US): o CREATE ... AS SELECT lê de lá.
    ds.location = "US"
    client.create_dataset(ds, exists_ok=True)


def _layout(table: Any) -> tuple:
    rp = table.range_partitioning
    partition = (rp.field, rp.range_.start, rp.range_.end) if rp else None
    return partition, tuple(table.clustering_fields or ())


def _drop_if_layout_changed(final: str, staging: str, *, client: Any) -> None:
    """A cópia WRITE_TRUNCATE falha se partição/cluster mudaram entre versões;
    nesse caso (só em mudança de layout) a tabela final é recriada."""
    from google.api_core.exceptions import NotFound  # lazy — extra ``gcp``

    try:
        current = client.get_table(final)
    except NotFound:
        return
    if _layout(current) != _layout(client.get_table(staging)):
        client.delete_table(final)


def build(
    *,
    tables: LeadsTables | None = None,
    contatos: bool = False,
    client: Any | None = None,
) -> tuple[dict[str, date], list[Check]]:
    """Materializa o snapshot mais recente; devolve (snapshots, checagens)."""
    from google.cloud import bigquery  # lazy import — extra ``gcp``

    client = client or _default_client()
    tables = tables or resolve_leads_tables()
    snapshots = resolve_latest_snapshots(client=client)
    _ensure_dataset(tables.leads, client=client)

    staging = tables.leads + STAGING_SUFFIX
    _run_ddl(build_leads_sql(staging, snapshots), client=client)
    checks = run_quality_checks(staging, client=client)
    if not all(c.ok for c in checks):
        raise QualityCheckError(checks)

    _drop_if_layout_changed(tables.leads, staging, client=client)
    copy_config = bigquery.CopyJobConfig(write_disposition="WRITE_TRUNCATE")
    client.copy_table(staging, tables.leads, job_config=copy_config).result()
    # Labels não acompanham a cópia de forma garantida: grava de novo.
    final = client.get_table(tables.leads)
    final.labels = {LABEL_SNAPSHOT[s]: d.isoformat() for s, d in snapshots.items()}
    client.update_table(final, ["labels"])
    client.delete_table(staging, not_found_ok=True)

    # ceps é auxiliar: grava só depois de promover a tabela de leads — um
    # problema aqui não desfaz a promoção, mas interrompe com erro (o
    # retorno 0 exige as duas tabelas boas).
    _run_ddl(build_ceps_sql(tables.ceps), client=client)
    checks.append(run_ceps_check(tables.ceps, client=client))
    if not all(c.ok for c in checks):
        raise PostPromotionCheckError(checks)

    if contatos:
        _run_ddl(build_contatos_sql(tables.contatos, snapshots), client=client)
    return snapshots, checks


def status(*, tables: LeadsTables | None = None, client: Any | None = None) -> dict:
    """Snapshot, linhas e tamanho da tabela de leads (metadados, sem custo)."""
    client = client or _default_client()
    tables = tables or resolve_leads_tables()
    snapshots = read_leads_snapshot(tables, client=client)
    table = client.get_table(tables.leads)
    return {
        "tabela": tables.leads,
        "snapshot": {s: d.isoformat() for s, d in snapshots.items()},
        "linhas": table.num_rows,
        "bytes": table.num_bytes,
        "modificada": table.modified.isoformat() if table.modified else None,
    }


def _print_checks(checks: list[Check]) -> None:
    for check in checks:
        mark = "ok  " if check.ok else "FALHA"
        print(f"  [{mark}] {check.name}: {check.detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m quimera.dados",
        description="Tabela própria de estabelecimentos ativos (Base dos Dados).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build", help="materializa o snapshot mais recente")
    build_parser.add_argument(
        "--contatos",
        action="store_true",
        help="também grava a tabela de contatos (só no ambiente privado)",
    )
    sub.add_parser("status", help="snapshot e tamanho da tabela atual")
    args = parser.parse_args(argv)

    if args.command == "build":
        try:
            snapshots, checks = build(contatos=args.contatos)
        except QualityCheckError as exc:
            print(f"Build abortado: {exc}. A tabela final não foi alterada.")
            _print_checks(exc.checks)
            return 1
        except PostPromotionCheckError as exc:
            print(f"Build falhou após promover a tabela de leads: {exc}")
            _print_checks(exc.checks)
            return 1
        print(
            "Tabela atualizada: snapshot "
            + ", ".join(f"{s}={d.isoformat()}" for s, d in sorted(snapshots.items()))
        )
        _print_checks(checks)
        return 0

    info = status()
    for key, value in info.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
