"""Índice CNAE multi-vetor (descrição + atividades oficiais do IBGE) e busca.

Fonte — ``python -m quimera.cnae fonte``: as subclasses da CNAE 2.3 vigente
segundo o IBGE/CONCLA (API servicodados), cada uma com as atividades que o
IBGE lista como compreendidas nela, e a grafia das descrições do diretório
``br_bd_diretorios_brasil.cnae_2``. Grava ``data/cnae_subclasses.jsonl``,
legível e versionado.

Índice — ``python -m quimera.cnae build``: um vetor para a descrição e um para
cada atividade (~18,5 mil vetores, float16) em ``data/cnae_index.npz``. A
similaridade de uma subclasse é a MAIOR entre os seus vetores: "dentistas"
casa com a atividade "atividades de dentistas" mesmo que a descrição oficial
seja "Atividade odontológica".

Medido no golden corrigido (66 casos, 2026-09-26): recall@5 0,818 só com as
descrições da 2.3 → 0,955 multi-vetor. O índice anterior misturava 24 códigos
que saíram da CNAE 2.3 (ex.: 4721-1/01 padaria, 0 empresas ativas na base).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Protocol

# Validado na conta em 2026-09-26 (004, 005 e gemini-embedding-001 disponíveis).
DEFAULT_EMBED_MODEL = "text-embedding-005"

DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_SOURCE_PATH = DATA_DIR / "cnae_subclasses.jsonl"
DEFAULT_INDEX_PATH = DATA_DIR / "cnae_index.npz"

IBGE_SUBCLASSES_URL = "https://servicodados.ibge.gov.br/api/v2/cnae/subclasses"
DIRETORIO_CNAE = "`basedosdados.br_bd_diretorios_brasil.cnae_2`"

# Limites do endpoint de embeddings do Vertex: 250 textos e 20 mil tokens por
# requisição. Atividades são curtas; o orçamento de caracteres cobre as longas.
EMBED_BATCH_SIZE = 100
EMBED_BATCH_MAX_CHARS = 30_000

# Conectores que o IBGE põe no fim da atividade: "DENTISTAS; ATIVIDADES DE".
_TRAILING_CONNECTORS = {"DE", "DA", "DO", "DAS", "DOS", "EM", "POR", "PARA"}


class Embedder(Protocol):
    """Provider de embeddings injetável (testes usam fakes, sem GCP)."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def vertex_embedder(model: str | None = None) -> Embedder:
    """Embedder real via Vertex AI. Import lazy: o SDK não é necessário nos testes."""
    return _vertex_embedder(model or os.environ.get("EMBED_MODEL", DEFAULT_EMBED_MODEL))


@lru_cache(maxsize=4)
def _vertex_embedder(model: str) -> Embedder:
    # Um cliente por modelo e processo (criar custava ~0,75 s por pedido).
    from .extract import _default_client

    client = _default_client()

    class _VertexEmbedder:
        def embed(self, texts: list[str]) -> list[list[float]]:
            response = client.models.embed_content(model=model, contents=texts)
            return [list(e.values) for e in response.embeddings]

    return _VertexEmbedder()


# ---------------------------------------------------------------------------
# Fonte: CNAE 2.3 + atividades do IBGE
# ---------------------------------------------------------------------------


def mask_code(digits: str) -> str:
    """ "8630504" -> "8630-5/04" (forma oficial usada em filters e golden)."""
    return f"{digits[:4]}-{digits[4]}/{digits[5:]}"


def clean_activity(text: str) -> str:
    """Atividade do IBGE em texto corrido e minúsculo.

    "DENTISTAS; ATIVIDADES DE" -> "atividades de dentistas";
    "PÃO; COMÉRCIO VAREJISTA DE" -> "comércio varejista de pão";
    "HOTEL" -> "hotel"; "FARMÁCIAS; COMÉRCIO VAREJISTA" ->
    "farmácias (comércio varejista)".
    """
    text = " ".join(text.replace("\xa0", " ").split()).strip().rstrip(";").strip()
    if "; " in text:
        head, tail = text.split("; ", 1)
        if tail.split()[-1] in _TRAILING_CONNECTORS:
            text = f"{tail} {head}"
        else:
            text = f"{head} ({tail})"
    return text.lower()


def merge_sources(
    diretorio: list[dict[str, Any]], ibge: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Subclasses do IBGE (CNAE 2.3 vigente) com a descrição do diretório.

    ``ibge``: itens da API com ``id`` (7 dígitos), ``descricao`` e ``atividades``
    — é a autoridade sobre QUAIS códigos existem. O ``indicador_cnae_2_3`` do
    diretório erra ao menos um (9900-8/00, 2.070 empresas ativas, medido).
    ``diretorio``: linhas com ``subclasse`` e ``descricao`` — só a grafia (o
    IBGE devolve tudo em maiúsculas). Sem linha no diretório, usa a do IBGE.
    """
    grafia = {row["subclasse"]: row["descricao"].strip() for row in diretorio}
    subclasses = []
    for item in sorted(ibge, key=lambda i: str(i["id"])):
        code = str(item["id"])
        descricao = grafia.get(code) or str(item["descricao"]).strip().capitalize()
        subclasses.append(
            {
                "codigo": mask_code(code),
                "descricao": descricao,
                # Sem duplicatas, na ordem do IBGE.
                "atividades": list(
                    dict.fromkeys(
                        clean_activity(a) for a in item.get("atividades") or []
                    )
                ),
            }
        )
    return subclasses


def _fetch_diretorio(client: Any) -> list[dict[str, Any]]:
    # Sem filtro de versão: o diretório só dá a grafia (ver merge_sources).
    job = client.query(
        f"SELECT subclasse, descricao_subclasse AS descricao\nFROM {DIRETORIO_CNAE}"
    )
    return [
        {
            "subclasse": "".join(ch for ch in str(r["subclasse"]) if ch.isdigit()),
            "descricao": r["descricao"],
        }
        for r in job.result()
    ]


def _fetch_ibge(url: str = IBGE_SUBCLASSES_URL) -> list[dict[str, Any]]:
    from urllib.request import urlopen

    with urlopen(url, timeout=120) as response:  # noqa: S310 — URL fixa do IBGE
        return json.loads(response.read().decode("utf-8"))


def build_source(
    output_path: str | Path = DEFAULT_SOURCE_PATH,
    *,
    fetch_diretorio: Callable[[], list[dict[str, Any]]] | None = None,
    fetch_ibge: Callable[[], list[dict[str, Any]]] | None = None,
) -> int:
    """Gera ``cnae_subclasses.jsonl`` a partir do diretório 2.3 e do IBGE."""
    if fetch_diretorio is None:
        from .query import _default_client

        client = _default_client()
        fetch_diretorio = lambda: _fetch_diretorio(client)  # noqa: E731
    subclasses = merge_sources(fetch_diretorio(), (fetch_ibge or _fetch_ibge)())
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for entry in subclasses:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return len(subclasses)


def load_subclasses(path: str | Path = DEFAULT_SOURCE_PATH) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# ---------------------------------------------------------------------------
# Índice multi-vetor
# ---------------------------------------------------------------------------


def _batches(texts: list[str]) -> list[list[str]]:
    batches: list[list[str]] = []
    current: list[str] = []
    chars = 0
    for text in texts:
        if current and (
            len(current) >= EMBED_BATCH_SIZE
            or chars + len(text) > EMBED_BATCH_MAX_CHARS
        ):
            batches.append(current)
            current, chars = [], 0
        current.append(text)
        chars += len(text)
    if current:
        batches.append(current)
    return batches


def build_index(
    source_path: str | Path = DEFAULT_SOURCE_PATH,
    output_path: str | Path = DEFAULT_INDEX_PATH,
    *,
    embedder: Embedder | None = None,
    model: str | None = None,
) -> int:
    """Embeda descrição + atividades de cada subclasse; devolve nº de vetores."""
    import numpy as np

    subclasses = load_subclasses(source_path)
    texts: list[str] = []
    owner: list[int] = []
    for i, entry in enumerate(subclasses):
        for text in [entry["descricao"], *entry["atividades"]]:
            texts.append(text)
            owner.append(i)

    embedder = embedder or vertex_embedder(model)
    vectors: list[list[float]] = []
    for batch in _batches(texts):
        vectors.extend(embedder.embed(batch))

    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms > 0)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out,
        vectors=matrix.astype(np.float16),
        owner=np.asarray(owner, dtype=np.int32),
        codes=np.asarray([e["codigo"] for e in subclasses]),
        descriptions=np.asarray([e["descricao"] for e in subclasses]),
        model=np.asarray(model or os.environ.get("EMBED_MODEL", DEFAULT_EMBED_MODEL)),
    )
    return len(texts)


@dataclass(frozen=True)
class CnaeIndex:
    vectors: Any  # np.ndarray float32 [n_vetores, dim], linhas normalizadas
    owner: Any  # np.ndarray int32 [n_vetores] -> posição em codes
    codes: list[str]
    descriptions: list[str]
    model: str


@lru_cache(maxsize=4)
def _load_cached(path: str, mtime: float) -> CnaeIndex:
    import numpy as np

    with np.load(path) as data:
        return CnaeIndex(
            vectors=data["vectors"].astype(np.float32),
            owner=data["owner"],
            codes=[str(c) for c in data["codes"]],
            descriptions=[str(d) for d in data["descriptions"]],
            model=str(data["model"]),
        )


def load_index(index_path: str | Path = DEFAULT_INDEX_PATH) -> CnaeIndex:
    path = Path(index_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Índice de CNAEs não encontrado em {path}. "
            "Construa com: python -m quimera.cnae build "
            "(requer credenciais GCP para gerar os embeddings)."
        )
    return _load_cached(str(path), path.stat().st_mtime)


def search(
    query: str,
    k: int = 5,
    *,
    index_path: str | Path | None = None,
    embedder: Embedder | None = None,
) -> list[tuple[str, str, float]]:
    """Os k CNAEs mais próximos: lista de (codigo, descricao, similaridade).

    Similaridade de uma subclasse = máximo do cosseno entre a consulta e os
    vetores dela (descrição e cada atividade).
    """
    import numpy as np

    index = load_index(index_path or DEFAULT_INDEX_PATH)
    embedder = embedder or vertex_embedder(index.model)
    (query_vec,) = embedder.embed([query])
    q = np.asarray(query_vec, dtype=np.float32)
    norm = float(np.linalg.norm(q))
    if norm == 0.0:
        return []
    sims = index.vectors @ (q / norm)
    best = np.full(len(index.codes), -np.inf, dtype=np.float32)
    np.maximum.at(best, index.owner, sims)
    top = np.argsort(-best)[:k]
    return [
        (index.codes[i], index.descriptions[i], float(best[i]))
        for i in top
        if np.isfinite(best[i])
    ]


# ---------------------------------------------------------------------------
# Candidatos híbridos: embedding + palavra
# ---------------------------------------------------------------------------

# Candidatos por palavra somados aos do embedding. O embedding confunde
# palavras parecidas: "borracharias" trazia fabricantes de artigos de borracha
# e nem punha 4520-0/06 ("serviços de borracharia") entre os 15 (medido no
# conjunto separado, 2026-09-26).
LEXICAL_CANDIDATES = 5
_STOPWORDS = frozenset(
    "a as o os de da das do dos e em no na nos nas para por com sem que "
    "empresa empresas loja lojas servico servicos".split()
)


def _normalize(text: str) -> str:
    from .text import strip_accents

    return " ".join(strip_accents(text).lower().split())


def _query_stems(query: str) -> list[str]:
    """Palavras relevantes do pedido, sem plural simples ("borracharias")."""
    stems = []
    for word in _normalize(query).replace("-", " ").split():
        word = "".join(ch for ch in word if ch.isalnum())
        if len(word) < 4 or word in _STOPWORDS:
            continue
        stems.append(word[:-1] if word.endswith("s") else word)
    return stems


@lru_cache(maxsize=1)
def _lexical_documents() -> tuple[tuple[str, str, tuple[tuple[str, ...], ...]], ...]:
    """(codigo, descricao, palavras de cada texto) — descrição e atividades."""
    docs = []
    for sub in load_subclasses():
        texts = [sub["descricao"], *sub["atividades"]]
        words = tuple(
            tuple(_normalize(t).replace("-", " ").replace("(", " ").split())
            for t in texts
        )
        docs.append((sub["codigo"], sub["descricao"], words))
    return tuple(docs)


def lexical_search(query: str, k: int = LEXICAL_CANDIDATES) -> list[tuple[str, str]]:
    """Subclasses com algum texto contendo TODAS as palavras do pedido.

    Casa por prefixo de palavra ("borracharia" casa "borracharia", não
    "borracha"); ordena pelo nº de textos da subclasse que casam.
    """
    stems = _query_stems(query)
    if not stems:
        return []
    scored = []
    for code, descricao, texts in _lexical_documents():
        hits = sum(
            all(any(w.startswith(stem) for w in words) for stem in stems)
            for words in texts
        )
        if hits:
            scored.append((hits, code, descricao))
    scored.sort(key=lambda item: -item[0])
    return [(code, descricao) for _, code, descricao in scored[:k]]


def hybrid_candidates(
    query: str,
    k: int | None = None,
    *,
    index_path: str | Path | None = None,
    embedder: Embedder | None = None,
) -> list[tuple[str, str, float]]:
    """Top-k do embedding + até ``LEXICAL_CANDIDATES`` achados por palavra.

    Os achados por palavra que o embedding não trouxe entram no fim da lista,
    com a similaridade do embedding (quando existir) só para exibição.
    """
    k = k or SELECT_CANDIDATES
    by_embedding = search(query, k, index_path=index_path, embedder=embedder)
    seen = {code for code, _, _ in by_embedding}
    extra = [
        (code, descricao, 0.0)
        for code, descricao in lexical_search(query)
        if code not in seen
    ]
    return by_embedding + extra


# ---------------------------------------------------------------------------
# Seleção final: quais candidatos viram filtro
# ---------------------------------------------------------------------------

# Candidatos que a busca entrega à seleção (recall@15 cobre os casos do golden).
SELECT_CANDIDATES = 15
# Atividades de exemplo por candidato no prompt (contexto sem inflar tokens).
SELECT_EXAMPLES = 6
# Seleção falha rápido: 10% das chamadas levavam > 5 s (até 22 s) por 429 de
# cota com retentativas do SDK (medido em 2026-09-26). Sem retentativa e com
# timeout, a falha cai no corte por similaridade (``fallback_codes``).
SELECT_TIMEOUT_MS = 4000
# Corte relativo ao 1º candidato no fallback: no golden, acerto 0,909 e
# precisão 0,698 (Gemini: 0,985 e 0,645; top-5 fixo: 0,955 e 0,227).
FALLBACK_DELTA = 0.04
FALLBACK_MAX = 5

SELECT_PROMPT = """Você classifica códigos CNAE para filtrar empresas num pedido de prospecção.
Atividade pedida pelo usuário: "{activity}"

Candidatos (código — descrição — exemplos de atividades da subclasse):
{candidates}

Dê uma nota a CADA candidato:
2 = é a atividade pedida: o usuário chamaria essas empresas pelo mesmo nome que usou
    (inclui variações que só mudam o modelo de negócio, ex.: com ou sem produção própria);
1 = atividade relacionada, vizinha ou mais ampla, mas não a pedida;
0 = outra atividade.
Fabricantes do produto, fornecedores de insumos, atacadistas, representantes
comerciais, construção ou manutenção ligados à atividade recebem no máximo 1,
a menos que o pedido peça isso (ex.: para "lojas de bicicletas", a fábrica de
bicicletas e o atacadista de bicicletas recebem 1).
Responda com a lista de notas na MESMA ordem dos candidatos."""
# Só nota 2 vira filtro. Dar nota a cada candidato (em vez de pedir a lista
# dos que servem) deixou o LLM mais criterioso: no golden CNAE, precisão
# 0,645 -> 0,849, acerto 0,985 -> 0,970, mesma latência (medido 2026-09-26).
SELECT_KEEP_GRADE = 2


@lru_cache(maxsize=1)
def _activities_by_code() -> dict[str, list[str]]:
    return {s["codigo"]: s["atividades"] for s in load_subclasses()}


def build_select_prompt(activity: str, candidates: list[tuple[str, str, float]]) -> str:
    # Exemplos na ordem do IBGE. Pôr primeiro os que citam o pedido foi
    # testado em 2026-09-29: melhorou a seleção isolada (golden CNAE, acerto
    # 0,957 -> 0,986), mas piorou o ponta a ponta na média de 2 rodadas
    # (principal 0,893 -> 0,857; separado 0,879 -> 0,818): código vizinho com
    # a palavra do pedido num exemplo passava a parecer a atividade pedida.
    examples = _activities_by_code()
    lines = [
        f"- {code} — {descricao} — "
        + "; ".join(examples.get(code, [])[:SELECT_EXAMPLES])
        for code, descricao, _ in candidates
    ]
    return SELECT_PROMPT.format(activity=activity, candidates="\n".join(lines))


def fallback_codes(
    candidates: list[tuple[str, str, float]],
) -> list[tuple[str, str, float]]:
    """Candidatos próximos do 1º (sem LLM) — plano B quando a seleção falha."""
    if not candidates:
        return []
    top = candidates[0][2]
    return [c for c in candidates[:FALLBACK_MAX] if c[2] >= top - FALLBACK_DELTA]


@lru_cache(maxsize=1)
def _select_client() -> Any:
    """Cliente Gemini da seleção: timeout curto e sem retentativa (ver acima)."""
    from google import genai  # lazy import — extra ``gcp``
    from google.genai import types

    return genai.Client(
        vertexai=True,
        project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        location=os.environ.get("VERTEX_LOCATION"),
        http_options=types.HttpOptions(
            timeout=SELECT_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


class SelectionError(ValueError):
    """Resposta da seleção fora do contrato (nº de notas ou valores)."""


def select_codes(
    activity: str,
    candidates: list[tuple[str, str, float]],
    *,
    client: Any | None = None,
    model: str | None = None,
) -> list[tuple[str, str, float]]:
    """Filtra os candidatos da busca com o Gemini; mantém a ordem da busca.

    O LLM só dá notas aos códigos recebidos (uma por candidato, na ordem) —
    nunca inventa código. A busca sozinha põe no filtro vizinhos semânticos
    errados ("padarias" trazia atacado de pães e chaveiros).
    """
    if not candidates:
        return []
    from .extract import DEFAULT_MODEL

    client = client or _select_client()
    response = client.models.generate_content(
        model=model or os.environ.get("EXTRACT_MODEL", DEFAULT_MODEL),
        contents=build_select_prompt(activity, candidates),
        config={
            "temperature": 0,
            # Sem raciocínio: p50 4,9 s -> 0,87 s com a mesma qualidade (medido).
            "thinking_config": {"thinking_budget": 0},
            "response_mime_type": "application/json",
            "response_schema": {
                "type": "OBJECT",
                "properties": {
                    "notas": {"type": "ARRAY", "items": {"type": "INTEGER"}}
                },
                "required": ["notas"],
            },
        },
    )
    notas = json.loads(response.text).get("notas") or []
    if len(notas) != len(candidates) or any(n not in (0, 1, 2) for n in notas):
        raise SelectionError(
            f"{len(notas)} notas para {len(candidates)} candidatos: {notas}"
        )
    return [c for c, nota in zip(candidates, notas) if nota == SELECT_KEEP_GRADE]


REFORMULATE_PROMPT = """Reescreva a atividade econômica abaixo como ela é descrita na CNAE \
(Classificação Nacional de Atividades Econômicas, IBGE): termos formais, sem gíria, sem \
sigla, sem marca. Se o termo tiver mais de uma leitura comum, use a mais comum para \
empresas. Responda só com a descrição, em até 12 palavras.
Atividade: "{activity}\""""
REFORMULATE_MAX_CHARS = 160


def reformulate_activity(
    activity: str, *, client: Any | None = None, model: str | None = None
) -> str:
    """Atividade no vocabulário da CNAE ("botecos" -> "bares...").

    Gíria e nome informal ("botecos", "sacolões", "empresas de TI") não
    aparecem nas atividades do IBGE: a busca não traz o código certo e a
    seleção volta vazia. Só é chamada nesse caso (golden sintético,
    2026-09-30: 173 de 10 mil pedidos terminavam em "nenhuma atividade").
    O texto volta para a busca, nunca vira código.
    """
    from .extract import DEFAULT_MODEL

    client = client or _select_client()
    response = client.models.generate_content(
        model=model or os.environ.get("EXTRACT_MODEL", DEFAULT_MODEL),
        contents=REFORMULATE_PROMPT.format(activity=activity),
        config={"temperature": 0, "thinking_config": {"thinking_budget": 0}},
    )
    texto = " ".join((response.text or "").split()).strip("\"'. ")
    return texto[:REFORMULATE_MAX_CHARS]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m quimera.cnae",
        description="Fonte e índice de embeddings das subclasses CNAE 2.3.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    fonte = sub.add_parser(
        "fonte", help="baixa CNAE 2.3 (diretório) + atividades do IBGE"
    )
    fonte.add_argument("--saida", default=str(DEFAULT_SOURCE_PATH))
    build = sub.add_parser("build", help="gera o índice multi-vetor a partir da fonte")
    build.add_argument("--fonte", default=str(DEFAULT_SOURCE_PATH))
    build.add_argument("--saida", default=str(DEFAULT_INDEX_PATH))
    build.add_argument("--modelo", default=None, help="modelo de embedding")
    args = parser.parse_args(argv)

    if args.command == "fonte":
        count = build_source(args.saida)
        print(f"Fonte com {count} subclasses CNAE 2.3 em {args.saida}.")
        return 0
    count = build_index(args.fonte, args.saida, model=args.modelo)
    print(f"Índice construído com {count} vetores em {args.saida}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
