"""Ambiente comum dos testes (sem rede, sem GCP)."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _gcp_project(monkeypatch):
    # resolve_leads_tables exige o projeto para montar o id da tabela própria.
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "projeto-teste")
    monkeypatch.delenv("LEADS_DATASET", raising=False)
