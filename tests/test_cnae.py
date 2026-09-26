"""Testes da fonte CNAE 2.3 + IBGE, do índice multi-vetor e da busca."""

from __future__ import annotations

import json

import pytest

from quimera.cnae import (
    DEFAULT_SOURCE_PATH,
    EMBED_BATCH_MAX_CHARS,
    EMBED_BATCH_SIZE,
    _batches,
    build_index,
    build_source,
    clean_activity,
    load_index,
    load_subclasses,
    mask_code,
    merge_sources,
    search,
    select_codes,
)


class FakeEmbedder:
    """Embedder determinístico: um eixo por palavra-chave presente no texto."""

    KEYWORDS = ["odonto", "dentista", "advoca", "transporte"]

    def __init__(self):
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [
            [1.0 if kw in text.lower() else 0.0 for kw in self.KEYWORDS]
            for text in texts
        ]


SUBCLASSES = [
    {
        "codigo": "8630-5/04",
        "descricao": "Atividade odontológica",
        "atividades": ["atividades de dentistas", "consultório dentário"],
    },
    {"codigo": "6911-7/01", "descricao": "Serviços advocatícios", "atividades": []},
    {
        "codigo": "4930-2/01",
        "descricao": "Transporte rodoviário de carga",
        "atividades": ["frete (transporte)"],
    },
]


@pytest.fixture
def index_path(tmp_path):
    source = tmp_path / "fonte.jsonl"
    source.write_text(
        "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in SUBCLASSES),
        encoding="utf-8",
    )
    out = tmp_path / "indice.npz"
    build_index(source, out, embedder=FakeEmbedder(), model="fake")
    return out


class TestCleanActivity:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("DENTISTAS; ATIVIDADES DE", "atividades de dentistas"),
            ("PÃO; COMÉRCIO VAREJISTA DE", "comércio varejista de pão"),
            ("HOTEL", "hotel"),
            (
                "FARMÁCIAS, DROGARIAS ALOPÁTICAS; COMÉRCIO VAREJISTA",
                "farmácias, drogarias alopáticas (comércio varejista)",
            ),
            ("  CONSULTÓRIO\xa0DENTÁRIO ", "consultório dentário"),
            (
                "PRONTO-SOCORRO, SEM INTERNAÇÃO; ATIVIDADES DE\xa0",
                "atividades de pronto-socorro, sem internação",
            ),
        ],
    )
    def test_normalizes_ibge_format(self, raw, expected):
        assert clean_activity(raw) == expected

    def test_mask_code(self):
        assert mask_code("8630504") == "8630-5/04"


class TestMergeSources:
    IBGE = [
        {
            "id": "8630504",
            "descricao": "ATIVIDADE ODONTOLÓGICA",
            "atividades": ["DENTISTAS; ATIVIDADES DE", "DENTISTAS; ATIVIDADES DE"],
        },
        {"id": "9900800", "descricao": "ORGANISMOS INTERNACIONAIS", "atividades": []},
    ]

    def test_ibge_decides_which_codes_exist(self):
        # O diretório tem códigos fora da 2.3 (ex.: 4721-1/01): não entram.
        diretorio = [
            {"subclasse": "8630504", "descricao": "Atividade odontológica"},
            {"subclasse": "4721101", "descricao": "Padaria (obsoleto)"},
        ]
        merged = merge_sources(diretorio, self.IBGE)
        assert [m["codigo"] for m in merged] == ["8630-5/04", "9900-8/00"]

    def test_description_spelling_from_directory_with_fallback(self):
        # 9900-8/00 está no IBGE mas o diretório não o marca como 2.3 (medido).
        diretorio = [{"subclasse": "8630504", "descricao": "Atividade odontológica"}]
        merged = {m["codigo"]: m for m in merge_sources(diretorio, self.IBGE)}
        assert merged["8630-5/04"]["descricao"] == "Atividade odontológica"
        assert merged["9900-8/00"]["descricao"] == "Organismos internacionais"

    def test_activities_cleaned_and_deduplicated(self):
        merged = merge_sources([], self.IBGE)
        assert merged[0]["atividades"] == ["atividades de dentistas"]

    def test_build_source_writes_jsonl(self, tmp_path):
        out = tmp_path / "fonte.jsonl"
        count = build_source(
            out, fetch_diretorio=lambda: [], fetch_ibge=lambda: self.IBGE
        )
        assert count == 2
        assert load_subclasses(out)[0]["codigo"] == "8630-5/04"


class TestBatches:
    def test_respects_count_limit(self):
        batches = _batches(["x"] * (EMBED_BATCH_SIZE + 1))
        assert [len(b) for b in batches] == [EMBED_BATCH_SIZE, 1]

    def test_respects_char_budget(self):
        # Limite do Vertex: 20 mil tokens por requisição (medido: 21 mil falhou).
        text = "a" * (EMBED_BATCH_MAX_CHARS // 2 + 1)
        assert [len(b) for b in _batches([text, text, text])] == [1, 1, 1]


class TestBuildIndex:
    def test_one_vector_per_description_and_activity(self, tmp_path):
        source = tmp_path / "fonte.jsonl"
        source.write_text(
            "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in SUBCLASSES),
            encoding="utf-8",
        )
        embedder = FakeEmbedder()
        count = build_index(source, tmp_path / "i.npz", embedder=embedder, model="fake")
        assert count == 3 + 2 + 0 + 1
        embedded = [t for call in embedder.calls for t in call]
        assert "atividades de dentistas" in embedded

    def test_index_metadata(self, index_path):
        index = load_index(index_path)
        assert index.codes == ["8630-5/04", "6911-7/01", "4930-2/01"]
        assert index.model == "fake"
        assert index.vectors.shape == (6, 4)
        assert list(index.owner) == [0, 0, 0, 1, 2, 2]

    def test_missing_index_raises_with_instructions(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="python -m quimera.cnae build"):
            load_index(tmp_path / "inexistente.npz")


class TestSearch:
    def test_activity_vector_matches_even_if_description_does_not(self, index_path):
        # "dentista" não aparece na descrição "Atividade odontológica", só na
        # atividade "atividades de dentistas": o multi-vetor acha mesmo assim.
        results = search("dentista", 1, index_path=index_path, embedder=FakeEmbedder())
        assert results[0][0] == "8630-5/04"
        assert results[0][1] == "Atividade odontológica"
        assert results[0][2] == pytest.approx(1.0, abs=1e-3)

    def test_one_result_per_subclass_sorted(self, index_path):
        results = search(
            "odonto e transporte", 5, index_path=index_path, embedder=FakeEmbedder()
        )
        codes = [r[0] for r in results]
        assert len(codes) == len(set(codes)) == 3
        sims = [r[2] for r in results]
        assert sims == sorted(sims, reverse=True)

    def test_zero_query_vector_returns_empty(self, index_path):
        assert search("nada", 3, index_path=index_path, embedder=FakeEmbedder()) == []


class TestShippedSource:
    def test_source_is_cnae_2_3_with_activities(self):
        subclasses = load_subclasses(DEFAULT_SOURCE_PATH)
        assert len(subclasses) == 1332  # CNAE 2.3 segundo o IBGE
        by_code = {s["codigo"]: s for s in subclasses}
        # Obsoletos que o índice antigo tinha (0 empresas ativas na base):
        assert "4721-1/01" not in by_code
        assert "9609-2/01" not in by_code
        assert "atividades de dentistas" in by_code["8630-5/04"]["atividades"]


class _FakeSelectClient:
    """Cliente genai falso para select_codes: registra o pedido e responde fixo."""

    def __init__(self, codigos):
        self.codigos = codigos
        self.calls = []

    @property
    def models(self):
        outer = self

        class _Models:
            def generate_content(self, **kwargs):
                outer.calls.append(kwargs)
                return type("R", (), {"text": json.dumps({"codigos": outer.codigos})})()

        return _Models()


CANDIDATES = [
    ("1091-1/02", "Padaria com produção própria", 0.81),
    ("4637-1/04", "Atacado de pães", 0.78),
    ("4721-1/02", "Padaria com predominância de revenda", 0.77),
]


class TestSelectCodes:
    def test_keeps_only_chosen_in_search_order(self):
        client = _FakeSelectClient(["4721-1/02", "1091-1/02"])
        chosen = select_codes("padarias", CANDIDATES, client=client, model="m")
        assert [c for c, _, _ in chosen] == ["1091-1/02", "4721-1/02"]

    def test_llm_can_only_pick_given_codes(self):
        client = _FakeSelectClient([])
        select_codes("padarias", CANDIDATES, client=client, model="m")
        schema = client.calls[0]["config"]["response_schema"]
        assert schema["properties"]["codigos"]["items"]["enum"] == [
            c for c, _, _ in CANDIDATES
        ]
        assert client.calls[0]["config"]["temperature"] == 0

    def test_prompt_has_activity_and_ibge_examples(self):
        client = _FakeSelectClient([])
        select_codes(
            "dentistas",
            [("8630-5/04", "Atividade odontológica", 0.9)],
            client=client,
            model="m",
        )
        prompt = client.calls[0]["contents"]
        assert '"dentistas"' in prompt
        assert "8630-5/04 — Atividade odontológica — " in prompt
        assert "atividades de dentistas" in prompt  # exemplos da fonte IBGE

    def test_invented_code_is_ignored(self):
        client = _FakeSelectClient(["9999-9/99"])
        assert select_codes("x", CANDIDATES, client=client, model="m") == []

    def test_no_candidates_no_call(self):
        client = _FakeSelectClient(["1091-1/02"])
        assert select_codes("x", [], client=client) == []
        assert client.calls == []
