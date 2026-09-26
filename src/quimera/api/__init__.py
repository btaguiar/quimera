"""API da demo pública (FastAPI). fastapi só é importado dentro de create_app."""

from __future__ import annotations


def create_app(**kwargs):
    from .app import create_app as _create_app

    return _create_app(**kwargs)
