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

    def test_rejected_requests_do_not_extend_the_block(self):
        clock = FakeClock()
        store = MemoryStateStore(_config(), clock=clock)
        store.allow_request("ip1")
        store.allow_request("ip1")
        assert store.allow_request("ip1") is False
        clock.now += 30
        assert store.allow_request("ip1") is False
        clock.now += 31
        assert store.allow_request("ip1") is True


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


class TestConcurrency:
    def test_parallel_allow_request_never_exceeds_max(self):
        import threading

        store = MemoryStateStore(_config(rate_limit_max=5), clock=FakeClock())
        accepted = []

        def hammer():
            for _ in range(20):
                if store.allow_request("ip1"):
                    accepted.append(1)

        threads = [threading.Thread(target=hammer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sum(accepted) == 5

    def test_parallel_add_bytes_counts_every_byte(self):
        import threading

        store = MemoryStateStore(_config(daily_bytes_budget=10**9), clock=FakeClock())

        def add():
            for _ in range(100):
                store.add_bytes(1)

        threads = [threading.Thread(target=add) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert store.budget_remaining() == 10**9 - 800


class TestCacheBound:
    def test_cache_cap_evicts_oldest_entry(self):
        clock = FakeClock()
        store = MemoryStateStore(_config(), clock=clock, max_cache_entries=2)
        store.cache_set("a", {"n": 1})
        clock.now += 1
        store.cache_set("b", {"n": 2})
        clock.now += 1
        store.cache_set("c", {"n": 3})
        assert store.cache_get("a") is None
        assert store.cache_get("b") == {"n": 2}
        assert store.cache_get("c") == {"n": 3}

    def test_retry_after_does_not_create_entry_for_unseen_ip(self):
        store = MemoryStateStore(_config(), clock=FakeClock())
        assert store.retry_after("nunca-visto") == 0
        assert "nunca-visto" not in store._requests
