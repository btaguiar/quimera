"""Testes do MemoryStateStore: janela de rate limit, cache com TTL e orçamento."""

from __future__ import annotations

import calendar

from quimera.api.protections import ApiConfig
from quimera.api.state import MemoryStateStore


def _config(**overrides) -> ApiConfig:
    base = dict(
        api_token=None,
        rate_limit_max=2,
        rate_limit_window_s=60,
        cache_ttl_s=100,
        daily_bytes_budget=1000,
        request_timeout_s=5.0,
    )
    base.update(overrides)
    return ApiConfig(**base)


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class TestRateLimit:
    def test_allows_up_to_max_then_blocks(self):
        clock = FakeClock()
        store = MemoryStateStore(_config(), clock=clock)
        assert store.allow_request("ip1") is True
        assert store.allow_request("ip1") is True
        assert store.allow_request("ip1") is False

    def test_window_slides_and_frees_slots(self):
        clock = FakeClock()
        store = MemoryStateStore(_config(), clock=clock)
        store.allow_request("ip1")
        store.allow_request("ip1")
        clock.now += 61
        assert store.allow_request("ip1") is True

    def test_ips_are_independent(self):
        store = MemoryStateStore(_config(), clock=FakeClock())
        assert store.allow_request("ip1") is True
        assert store.allow_request("ip2") is True

    def test_retry_after_reports_seconds_to_oldest_hit(self):
        clock = FakeClock(start=100.0)
        store = MemoryStateStore(_config(), clock=clock)
        store.allow_request("ip1")
        clock.now += 10
        assert store.retry_after("ip1") > 0
        assert store.retry_after("ip1") <= 51


class TestCache:
    def test_set_and_get_roundtrip(self):
        store = MemoryStateStore(_config(), clock=FakeClock())
        store.cache_set("k", {"refused": False})
        assert store.cache_get("k") == {"refused": False}

    def test_missing_key_returns_none(self):
        store = MemoryStateStore(_config(), clock=FakeClock())
        assert store.cache_get("nada") is None

    def test_entry_expires_after_ttl(self):
        clock = FakeClock()
        store = MemoryStateStore(_config(), clock=clock)
        store.cache_set("k", {"a": 1})
        clock.now += 101
        assert store.cache_get("k") is None

    def test_expired_entry_is_evicted(self):
        clock = FakeClock()
        store = MemoryStateStore(_config(), clock=clock)
        store.cache_set("k", {"a": 1})
        clock.now += 101
        store.cache_get("k")
        assert "k" not in store._cache


class TestBudget:
    def test_bytes_debit_and_cache_mode(self):
        store = MemoryStateStore(_config(), clock=FakeClock())
        assert store.cache_mode() is False
        store.add_bytes(999)
        assert store.budget_remaining() == 1
        assert store.cache_mode() is False
        store.add_bytes(1)
        assert store.cache_mode() is True

    def test_budget_resets_on_utc_day_rollover(self):
        midnight = calendar.timegm((2026, 9, 27, 0, 0, 0))
        clock = FakeClock(start=midnight - 1)
        store = MemoryStateStore(_config(), clock=clock)
        store.add_bytes(1000)
        assert store.cache_mode() is True
        clock.now = midnight + 1
        assert store.budget_remaining() == 1000
        assert store.cache_mode() is False

    def test_remaining_never_negative(self):
        store = MemoryStateStore(_config(), clock=FakeClock())
        store.add_bytes(5000)
        assert store.budget_remaining() == 0
