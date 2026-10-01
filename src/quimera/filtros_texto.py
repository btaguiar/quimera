"""Idade e capital lidos do próprio texto do pedido — rede de segurança da extração.

O Gemini, sem raciocínio, às vezes deixa de fora a última condição de um
pedido com duas ("fora do Simples e com capital acima de R$ 500 mil" saía
sem o capital): 48 de 833 pedidos com duas condições no golden sintético
(2026-09-30). Pedir isso no prompt piorou (94,2% -> 88,7%), então o pipeline
completa o que ficou vazio a partir do texto escrito, como já faz com o CEP:
nunca sobrescreve o que o modelo extraiu e nunca inventa valor.
"""

from __future__ import annotations

import re

from .text import strip_accents

# Qualificadores de mínimo e de máximo, já sem acento e em minúsculas.
_MINIMO = r"(?:mais de|pelo menos|ao menos|no minimo|minimo de|acima de|superior a|maior que|maior do que|a partir de)"
_MAXIMO = r"(?:menos de|ate|no maximo|abaixo de|inferior a)"
_ANOS = r"(\d{1,3})\s*anos?\b"

_IDADE_MIN = re.compile(
    rf"\b{_MINIMO}\s+{_ANOS}|\b{_ANOS}\s+ou\s+mais\b|\b(\d{{1,3}})\s*\+\s*anos?\b"
)
_IDADE_MAX = re.compile(rf"\b{_MAXIMO}\s+{_ANOS}")

# "capital (social) [de] <qualificador de mínimo> [R$] 500 mil" ou
# "capital ... 500 mil ou mais". Sem qualificador de mínimo não preenche:
# "capital abaixo de 100 mil" não tem filtro correspondente.
_VALOR = r"(?:r\$\s*)?(\d+(?:[.,]\d+)*)\s*(mil|milhao|milhoes|mi|k)?\b(?:\s*(?:de\s+)?reais)?"
_CAPITAL = re.compile(
    rf"\bcapital(?:\s+social)?\s*(?:de\s+|>=?\s*)?{_MINIMO}\s+(?:de\s+)?{_VALOR}"
    rf"|\bcapital(?:\s+social)?\s*(?:de\s+)?{_VALOR}\s+ou\s+mais\b"
    rf"|\bcapital(?:\s+social)?\s*>=?\s*{_VALOR}"
)
_MULTIPLICADOR = {"mil": 1_000, "k": 1_000, "milhao": 1_000_000, "milhoes": 1_000_000, "mi": 1_000_000}


def _numero(texto: str, unidade: str | None) -> float | None:
    """'500' + 'mil' -> 500000; '1,5' + 'milhao' -> 1500000; '500.000' -> 500000."""
    if unidade:
        valor = float(texto.replace(".", "").replace(",", "."))
        return valor * _MULTIPLICADOR[unidade]
    # Sem unidade: ponto e vírgula são separadores de milhar ("500.000").
    digitos = texto.replace(".", "").replace(",", "")
    return float(digitos) if digitos.isdigit() else None


def filtros_no_texto(pedido: str) -> dict[str, float | int]:
    """Idade mínima/máxima e capital mínimo escritos no pedido, se houver."""
    texto = " ".join(strip_accents(pedido).lower().split())
    achados: dict[str, float | int] = {}
    if m := _IDADE_MIN.search(texto):
        achados["min_age_years"] = int(next(g for g in m.groups() if g))
    if m := _IDADE_MAX.search(texto):
        achados["max_age_years"] = int(m.group(1))
    if m := _CAPITAL.search(texto):
        grupos = [g for g in m.groups()]
        for i in range(0, len(grupos), 2):
            if grupos[i]:
                valor = _numero(grupos[i], grupos[i + 1])
                if valor:
                    achados["min_capital"] = valor
                break
    return achados
