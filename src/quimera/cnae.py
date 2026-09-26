"""Índice de embeddings de descrições CNAE e busca por similaridade.

O índice é um JSONL versionável, uma linha por CNAE:
``{"codigo": "8630-5/01", "descricao": "...", "embedding": [...]}``

Construção: ``python -m quimera.cnae build --fonte pares.jsonl --saida indice.jsonl``
(fonte: JSONL ou CSV com pares codigo/descricao; embeddings via Vertex AI).

Similaridade de cosseno em Python puro — são ~700 CNAEs, vetores pequenos,
performance não importa (por isso, sem numpy).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from pathlib import Path
from typing import Protocol, Sequence

# Validado na conta em 2026-09-26 (004, 005 e gemini-embedding-001 disponíveis).
DEFAULT_EMBED_MODEL = "text-embedding-005"

DEFAULT_INDEX_PATH = Path(__file__).resolve().parent / "data" / "cnae_index.jsonl"


class Embedder(Protocol):
    """Provider de embeddings injetável (testes usam fakes, sem GCP)."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def vertex_embedder(model: str | None = None) -> Embedder:
    """Embedder real via Vertex AI. Import lazy: o SDK não é necessário nos testes."""
    from google import genai  # lazy import — extra ``gcp``

    model = model or os.environ.get("EMBED_MODEL", DEFAULT_EMBED_MODEL)
    client = genai.Client(
        vertexai=True,
        project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        location=os.environ.get("VERTEX_LOCATION"),
    )

    class _VertexEmbedder:
        def embed(self, texts: list[str]) -> list[list[float]]:
            response = client.models.embed_content(model=model, contents=texts)
            return [list(e.values) for e in response.embeddings]

    return _VertexEmbedder()


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def load_index(index_path: Path) -> list[dict]:
    if not index_path.exists():
        raise FileNotFoundError(
            f"Índice de CNAEs não encontrado em {index_path}. "
            "Construa o índice com: python -m quimera.cnae build "
            "--fonte <pares.jsonl> --saida <indice.jsonl> "
            "(requer credenciais GCP para gerar os embeddings)."
        )
    entries = []
    with index_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def search(
    query: str,
    k: int = 5,
    *,
    index_path: str | Path | None = None,
    embedder: Embedder | None = None,
) -> list[tuple[str, str, float]]:
    """Devolve os k CNAEs mais próximos: lista de (codigo, descricao, similaridade)."""
    path = Path(index_path) if index_path else DEFAULT_INDEX_PATH
    entries = load_index(path)
    embedder = embedder or vertex_embedder()
    (query_vec,) = embedder.embed([query])
    scored = [
        (entry["codigo"], entry["descricao"], cosine_similarity(query_vec, entry["embedding"]))
        for entry in entries
    ]
    scored.sort(key=lambda item: item[2], reverse=True)
    return scored[:k]


def _read_pairs(source_path: Path) -> list[tuple[str, str]]:
    """Lê pares (codigo, descricao) de JSONL ou CSV."""
    pairs: list[tuple[str, str]] = []
    if source_path.suffix == ".csv":
        with source_path.open(encoding="utf-8", newline="") as fh:
            for row in csv.reader(fh):
                if row and row[0].strip().lower() != "codigo":
                    pairs.append((row[0].strip(), row[1].strip()))
    else:
        with source_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    entry = json.loads(line)
                    pairs.append((entry["codigo"], entry["descricao"]))
    return pairs


def build_index(
    source_path: str | Path,
    output_path: str | Path,
    *,
    embedder: Embedder | None = None,
    batch_size: int = 100,
) -> int:
    """Gera o índice de embeddings a partir da fonte de pares (codigo, descricao)."""
    pairs = _read_pairs(Path(source_path))
    embedder = embedder or vertex_embedder()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out.open("w", encoding="utf-8") as fh:
        for start in range(0, len(pairs), batch_size):
            batch = pairs[start : start + batch_size]
            vectors = embedder.embed([descricao for _, descricao in batch])
            for (codigo, descricao), vector in zip(batch, vectors):
                fh.write(
                    json.dumps(
                        {"codigo": codigo, "descricao": descricao, "embedding": vector},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m quimera.cnae",
        description="Constrói o índice de embeddings de descrições CNAE.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="Gera o índice a partir de pares codigo/descricao.")
    build.add_argument("--fonte", required=True, help="JSONL ou CSV com codigo/descricao.")
    build.add_argument("--saida", default=str(DEFAULT_INDEX_PATH), help="Caminho do índice JSONL.")
    args = parser.parse_args(argv)

    if args.command == "build":
        count = build_index(args.fonte, args.saida)
        print(f"Índice construído com {count} CNAEs em {args.saida}.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
