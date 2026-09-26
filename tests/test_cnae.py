"""Testes do índice de embeddings CNAE: busca, construção e similaridade."""

from __future__ import annotations

import json

import pytest

from quimera.cnae import (
    build_index,
    cosine_similarity,
    load_index,
    search,
)


class FakeEmbedder:
    """Embedder determinístico: vetor unitário por palavra-chave na frase."""

    KEYWORDS = ["odontológica", "advocacia", "transporte"]

    def embed(self, texts):
        vectors = []
        for text in texts:
            vec = [1.0 if kw in text.lower() else 0.0 for kw in self.KEYWORDS]
            vectors.append(vec)
        return vectors


def _write_index(path, entries):
    with path.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


class TestCosineSimilarity:
    def test_identical_vectors(self):
        assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_zero_vector_returns_zero(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


class TestLoadIndex:
    def test_missing_index_raises_with_instructions(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="python -m quimera.cnae build"):
            load_index(tmp_path / "inexistente.jsonl")

    def test_loads_entries(self, tmp_path):
        path = tmp_path / "indice.jsonl"
        _write_index(
            path, [{"codigo": "8630-5/01", "descricao": "d", "embedding": [1.0]}]
        )
        entries = load_index(path)
        assert entries[0]["codigo"] == "8630-5/01"


class TestSearch:
    def test_returns_top_k_sorted_by_similarity(self, tmp_path):
        path = tmp_path / "indice.jsonl"
        _write_index(
            path,
            [
                {
                    "codigo": "8630-5/01",
                    "descricao": "atividade odontológica",
                    "embedding": [1, 0, 0],
                },
                {
                    "codigo": "6911-7/01",
                    "descricao": "advocacia",
                    "embedding": [0, 1, 0],
                },
                {
                    "codigo": "4930-2/01",
                    "descricao": "transporte rodoviário",
                    "embedding": [0, 0, 1],
                },
            ],
        )
        results = search(
            "clínica odontológica", 2, index_path=path, embedder=FakeEmbedder()
        )
        assert len(results) == 2
        assert results[0][0] == "8630-5/01"
        assert results[0][1] == "atividade odontológica"
        assert results[0][2] == pytest.approx(1.0)
        assert results[1][2] <= results[0][2]

    def test_k_larger_than_index_returns_all(self, tmp_path):
        path = tmp_path / "indice.jsonl"
        _write_index(path, [{"codigo": "1", "descricao": "d", "embedding": [1, 0, 0]}])
        results = search("odontológica", 5, index_path=path, embedder=FakeEmbedder())
        assert len(results) == 1


class TestBuildIndex:
    def test_builds_index_in_batches(self, tmp_path):
        source = tmp_path / "pares.jsonl"
        with source.open("w", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {"codigo": "8630-5/01", "descricao": "atividade odontológica"}
                )
                + "\n"
            )
            fh.write(
                json.dumps({"codigo": "6911-7/01", "descricao": "advocacia"}) + "\n"
            )
            fh.write(
                json.dumps({"codigo": "4930-2/01", "descricao": "transporte"}) + "\n"
            )

        out = tmp_path / "indice.jsonl"
        count = build_index(source, out, embedder=FakeEmbedder(), batch_size=2)
        assert count == 3

        entries = load_index(out)
        assert [e["codigo"] for e in entries] == ["8630-5/01", "6911-7/01", "4930-2/01"]
        assert entries[0]["embedding"] == [1, 0, 0]

    def test_accepts_csv_source(self, tmp_path):
        source = tmp_path / "pares.csv"
        source.write_text(
            "codigo,descricao\n8630-5/01,atividade odontológica\n", encoding="utf-8"
        )
        out = tmp_path / "indice.jsonl"
        count = build_index(source, out, embedder=FakeEmbedder())
        assert count == 1
        assert load_index(out)[0]["codigo"] == "8630-5/01"
