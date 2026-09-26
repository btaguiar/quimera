"""Normalização de texto compartilhada (acentos, caixa, espaços)."""

from __future__ import annotations

import unicodedata


def strip_accents(value: str) -> str:
    """Remove acentos/diacríticos: 'Média' -> 'Media'."""
    return "".join(
        ch
        for ch in unicodedata.normalize("NFD", value)
        if unicodedata.category(ch) != "Mn"
    )


def normalize_name(value: str) -> str:
    """Normaliza nomes próprios para comparação: sem acento, maiúsculo, sem espaços extras."""
    return " ".join(strip_accents(value).upper().split())
