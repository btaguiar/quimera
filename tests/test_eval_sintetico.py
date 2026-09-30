"""Golden sintético: plano determinístico, gabarito coerente, paráfrase validada."""

from __future__ import annotations

import pytest

from eval.sintetico.gerar import (
    PARES,
    PERFIS,
    _par_nome,
    carregar_atividades,
    censo_sql,
    parafrase_valida,
    parafrasear,
    planejar,
)


def _celula(atividade, municipio, uf, n=50, **extra):
    return {
        "atividade": atividade,
        "uf": uf,
        "id_municipio": f"{uf}-{municipio}",
        "municipio": municipio,
        "n": n,
        "perfis": {nome: n for nome in PERFIS},
        "pares": {_par_nome(par): n for par in PARES},
        "bairros": [["BOA VIAGEM", 12], ["CENTRO", 30]],
        "ponto": "-8.1,-34.9",
        "cep": "51020000",
        **extra,
    }


ATIVIDADES = [
    {"id": "padaria", "termos": ["padarias"], "cnae": ["1091-1/02", "4721-1/02"]},
    {"id": "odonto", "termos": ["dentistas"], "cnae": ["8630-5/04"]},
]
CENSO = {
    "snapshot": {"snapshot_est": "2026-01-11"},
    "celulas": [
        _celula("padaria", "Recife", "PE"),
        _celula("padaria", "Santo André", "SP"),
        _celula("odonto", "São Paulo", "SP", n=900),
        _celula("odonto", "Santo André", "PB", n=4),
    ],
    "municipios": [
        {"nome": "Recife", "uf": "PE", "id": "1"},
        {"nome": "Santo André", "uf": "SP", "id": "2"},
        {"nome": "Santo André", "uf": "PB", "id": "3"},
        {"nome": "São Paulo", "uf": "SP", "id": "4"},
    ],
}


class TestPlano:
    def test_deterministic_and_prefix_stable(self):
        a = planejar(CENSO, ATIVIDADES, 200, seed=3)
        b = planejar(CENSO, ATIVIDADES, 200, seed=3)
        assert [c["request"] for c in a] == [c["request"] for c in b]
        assert len({c["request"] for c in a}) == 200
        assert [c["id"] for c in a[:2]] == ["sint_00001", "sint_00002"]

    def test_expect_matches_template(self):
        for caso in planejar(CENSO, ATIVIDADES, 300, seed=1):
            exp, tipo = caso["expect"], caso["meta"]["tipo"]
            if tipo == "recusa":
                assert exp == {"refused": True}
                continue
            if tipo in ("cidade_inexistente", "sem_atividade"):
                assert exp["empty"] is True
                continue
            assert exp["cnae"] in ([a["cnae"] for a in ATIVIDADES])
            if tipo.startswith("cidade") or tipo == "bairro":
                assert exp["municipio"][0] in caso["request"]
            if tipo == "raio":
                assert "CEP 51020-000" in caso["request"]
                assert exp["raio_km"] in (1, 2, 3, 5, 10)
            for perfil in caso["meta"].get("perfis", []):
                for chave, valor in PERFIS[perfil].expect.items():
                    assert exp[chave] == valor

    def test_homonym_city_always_carries_uf_except_homonym_cases(self):
        for caso in planejar(CENSO, ATIVIDADES, 300, seed=2):
            if caso["meta"]["tipo"] in ("cidade", "cidade_perfil", "cidade_par"):
                if "Santo André" in caso["request"]:
                    assert "SP" in caso["request"] or "PB" in caso["request"]
            if caso["meta"]["tipo"] == "homonimo":
                assert caso["expect"]["warning"] == "Informe a UF"

    def test_city_named_like_state_is_disambiguated(self):
        reqs = [
            c["request"]
            for c in planejar(CENSO, ATIVIDADES, 300, seed=4)
            if c["meta"]["tipo"] == "cidade" and "São Paulo" in c["request"]
        ]
        assert reqs and all("cidade de São Paulo" in r for r in reqs)

    def test_media_porte_expects_demais_and_warning(self):
        casos = planejar(CENSO, ATIVIDADES, 600, seed=5)
        medios = [c for c in casos if "porte_media" in c["meta"].get("perfis", [])]
        assert medios
        for c in medios:
            assert c["expect"]["portes"] == ["demais"]
            assert c["expect"]["warning"] == "médio de grande"

    def test_cells_below_profile_count_are_skipped(self):
        censo = {**CENSO, "celulas": [_celula("odonto", "Recife", "PE")]}
        censo["celulas"][0]["perfis"]["dominio"] = 0
        for par in PARES:
            if "dominio" in par:
                censo["celulas"][0]["pares"][_par_nome(par)] = 0
        casos = planejar(censo, ATIVIDADES[1:], 300, seed=6)
        assert not any("dominio" in c["meta"].get("perfis", []) for c in casos)


class TestParafrase:
    CASO = {
        "template": "padarias de pequeno porte em Recife, PE com capital social acima de R$ 100 mil",
        "ancoras": ["padarias", "Recife", "PE|Pernambuco", "pequen", "100", "capital"],
    }

    @pytest.mark.parametrize(
        "texto",
        [
            "quero padarias de pequeno porte em Recife/PE com capital social acima de R$ 100 mil",
            "lista de padarias pequenas em recife pe, capital social maior que 100 mil",
            "PADARIAS DE PEQUENO PORTE EM RECIFE, PERNAMBUCO, CAPITAL SOCIAL > R$ 100 MIL",
        ],
    )
    def test_accepts_faithful(self, texto):
        assert parafrase_valida(self.CASO, texto)

    @pytest.mark.parametrize(
        "texto",
        [
            "padarias de pequeno porte em Recife com capital social acima de R$ 100 mil",  # sem UF
            "padarias de pequeno porte em Recife, PE com capital acima de R$ 100.000",  # número
            "padarias em Recife, PE com capital social acima de R$ 100 mil",  # sem porte
            "panificadoras de pequeno porte em Recife, PE, capital social acima de 100 mil",
            "padarias de pequeno porte em Recife, PE com capital social acima de R$ 100 mil há 5 anos",
            "",
        ],
    )
    def test_rejects_drift(self, texto):
        assert not parafrase_valida(self.CASO, texto)

    def test_short_anchor_is_whole_word(self):
        caso = {"template": "padarias em Belém, PA", "ancoras": ["padarias", "Belém", "PA|Pará"]}
        assert not parafrase_valida(caso, "padarias em Belém")
        assert parafrase_valida(caso, "padarias em belem pa")

    def test_rejected_keeps_template_and_accepted_goes_to_cache(self, tmp_path):
        casos = [
            {**self.CASO, "request": self.CASO["template"]},
            {"template": "dentistas em Recife, PE", "ancoras": ["dentistas", "Recife", "PE"],
             "request": "dentistas em Recife, PE"},
        ]
        cache = tmp_path / "cache.jsonl"
        stats = parafrasear(
            casos,
            lambda ts: ["padarias em Recife", "preciso de dentistas em recife/pe"],
            cache_path=cache,
        )
        assert stats == {"cache": 0, "aceitas": 1, "rejeitadas": 1}
        assert casos[0]["request"] == casos[0]["template"]
        assert casos[1]["request"] == "preciso de dentistas em recife/pe"
        # 2ª rodada: vem do cache, sem chamar o gerador
        casos[1]["request"] = casos[1]["template"]
        stats = parafrasear(casos[1:], lambda ts: pytest.fail("não devia chamar"), cache_path=cache)
        assert stats["cache"] == 1 and casos[1]["request"].startswith("preciso")

    def test_batch_error_keeps_templates(self, tmp_path):
        casos = [{**self.CASO, "request": self.CASO["template"]}]

        def falha(_):
            raise TimeoutError

        stats = parafrasear(casos, falha, cache_path=tmp_path / "c.jsonl")
        assert stats["rejeitadas"] == 1 and casos[0]["request"] == self.CASO["template"]


class TestCatalogoECenso:
    def test_catalog_codes_exist_and_ids_unique(self):
        from quimera.cnae import load_subclasses

        valid = {s["codigo"] for s in load_subclasses()}
        atividades = carregar_atividades()
        assert len(atividades) >= 150
        assert len({a["id"] for a in atividades}) == len(atividades)
        for a in atividades:
            assert a["termos"] and a["cnae"]
            assert a["principal"] in a["cnae"], a["id"]
            for code in a["cnae"]:
                assert code in valid, (a["id"], code)

    def test_census_sql_mirrors_public_exclusions(self):
        sql = censo_sql("p.d.t")
        assert "opcao_mei != 1" in sql
        assert "natureza_juridica != '2135'" in sql
        assert "NOT STARTS_WITH(natureza_juridica, '4')" in sql
        assert "cnae_divisao IN UNNEST(@divisoes)" in sql  # poda de partição
        for nome in PERFIS:
            assert f"`p_{nome}`" in sql


class TestPolaridade:
    """Troca de sentido preserva números e nomes: as âncoras de polaridade pegam."""

    def _caso(self, perfil):
        casos = planejar(CENSO, ATIVIDADES, 600, seed=9)
        return next(c for c in casos if c["meta"].get("perfis") == [perfil])

    def test_min_age_flipped_to_max_is_rejected(self):
        caso = self._caso("idade_min_5")
        virado = caso["template"].replace("mais de", "menos de").replace("pelo menos", "no máximo")
        assert not parafrase_valida(caso, virado)
        assert parafrase_valida(caso, caso["template"])

    def test_fora_simples_losing_negation_is_rejected(self):
        caso = self._caso("fora_simples")
        assert not parafrase_valida(
            caso, caso["template"].replace("fora do", "do").replace("não são", "são")
        )

    def test_simples_gaining_negation_is_rejected(self):
        caso = self._caso("simples")
        assert not parafrase_valida(
            caso, caso["template"].replace("optantes pelo", "fora do").replace("que são", "que não são")
        )
        assert parafrase_valida(caso, caso["template"])
