"""Testes de policy: limites público/privado aplicados DEPOIS do LLM."""

from __future__ import annotations

from quimera.filters import LeadFilters
from quimera.policy import PRIVATE, PUBLIC, apply_policy, resolve_policy


class TestPolicies:
    def test_public_forbids_mei_and_contacts(self):
        assert PUBLIC.allow_mei is False
        assert PUBLIC.contact_fields == ()
        assert PUBLIC.max_rows == 50

    def test_private_allows_mei_and_contacts(self):
        assert PRIVATE.allow_mei is True
        assert "correio_eletronico" in PRIVATE.contact_fields
        assert PRIVATE.max_rows == 1000


class TestApplyPolicy:
    def test_public_cuts_limit_above_max_rows(self):
        filters = apply_policy(LeadFilters(limit=500), PUBLIC)
        assert filters.limit == 50

    def test_private_cuts_limit_at_1000(self):
        filters = apply_policy(LeadFilters(limit=5000), PRIVATE)
        assert filters.limit == 1000

    def test_public_disables_include_mei_even_if_llm_asked(self):
        filters = apply_policy(LeadFilters(include_mei=True), PUBLIC)
        assert filters.include_mei is False

    def test_private_keeps_include_mei(self):
        filters = apply_policy(LeadFilters(include_mei=True), PRIVATE)
        assert filters.include_mei is True

    def test_public_strips_mei_from_regimes(self):
        filters = apply_policy(LeadFilters(regimes=["mei", "simples"]), PUBLIC)
        assert filters.regimes == ["simples"]

    def test_private_keeps_mei_regime(self):
        filters = apply_policy(LeadFilters(regimes=["mei"]), PRIVATE)
        assert filters.regimes == ["mei"]

    def test_limit_below_max_is_untouched(self):
        filters = apply_policy(LeadFilters(limit=10), PUBLIC)
        assert filters.limit == 10

    def test_does_not_mutate_original(self):
        original = LeadFilters(limit=500, include_mei=True)
        apply_policy(original, PUBLIC)
        assert original.limit == 500
        assert original.include_mei is True


class TestResolvePolicy:
    def test_default_is_public(self, monkeypatch):
        monkeypatch.delenv("DEPLOY_MODE", raising=False)
        assert resolve_policy() is PUBLIC

    def test_private_mode(self, monkeypatch):
        monkeypatch.setenv("DEPLOY_MODE", "private")
        assert resolve_policy() is PRIVATE

    def test_mode_is_case_insensitive_and_trimmed(self, monkeypatch):
        monkeypatch.setenv("DEPLOY_MODE", "  PRIVATE ")
        assert resolve_policy() is PRIVATE

    def test_unknown_mode_falls_back_to_public(self, monkeypatch):
        monkeypatch.setenv("DEPLOY_MODE", "staging")
        assert resolve_policy() is PUBLIC
