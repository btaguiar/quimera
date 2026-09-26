"""Estado da API: cache, janela de rate limit e orçamento diário.

``StateStore`` é o protocolo; ``MemoryStateStore`` é a implementação
padrão — serve para dev, testes e a demo (um processo, escala a zero).
O Firestore entra depois implementando o mesmo protocolo, sem tocar na
app. Orçamento zera à meia-noite UTC; contagem de rate limit só registra
requisições ACEITAS (rejeitadas são baratas e não estendam o bloqueio).
Um ``threading.Lock`` serializa o acesso — handlers sync do FastAPI
rodam em threadpool — e o cache tem teto de entradas para não crescer
sem fim.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Protocol

from .protections import ApiConfig


class StateStore(Protocol):
    """Estado compartilhado das proteções (cache, rate limit, orçamento)."""

    def cache_get(self, key: str) -> dict | None: ...
    def cache_set(self, key: str, value: dict) -> None: ...
    def allow_request(self, ip: str) -> bool: ...
    def retry_after(self, ip: str) -> int: ...
    def add_bytes(self, n: int) -> None: ...
    def budget_remaining(self) -> int: ...
    def cache_mode(self) -> bool: ...


class MemoryStateStore:
    """Implementação em memória do ``StateStore`` (um processo)."""

    def __init__(
        self,
        config: ApiConfig,
        clock=time.time,
        max_cache_entries: int = 1000,
    ) -> None:
        self._config = config
        self._clock = clock
        self._max_cache_entries = max_cache_entries
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, dict]] = {}
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._budget_day = self._utc_today()
        self._budget_used = 0

    def cache_get(self, key: str) -> dict | None:
        """Devolve o valor em cache, ou ``None`` se ausente ou expirado."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if self._clock() - stored_at > self._config.cache_ttl_s:
                del self._cache[key]
                return None
            return value

    def cache_set(self, key: str, value: dict) -> None:
        """Guarda o valor; com o cache cheio, remove a entrada mais antiga."""
        with self._lock:
            if key not in self._cache and len(self._cache) >= self._max_cache_entries:
                oldest = min(self._cache, key=lambda k: self._cache[k][0])
                del self._cache[oldest]
            self._cache[key] = (self._clock(), value)

    def allow_request(self, ip: str) -> bool:
        """Checa a janela deslizante; registra e aceita se houver vaga."""
        with self._lock:
            now = self._clock()
            window = self._config.rate_limit_window_s
            hits = self._requests[ip]
            while hits and now - hits[0] >= window:
                hits.popleft()
            if len(hits) >= self._config.rate_limit_max:
                return False
            hits.append(now)
            return True

    def retry_after(self, ip: str) -> int:
        """Segundos (mínimo 1) até a liberação da vaga mais antiga."""
        with self._lock:
            hits = self._requests.get(ip)
            if not hits:
                return 0
            elapsed = self._clock() - hits[0]
            return max(1, int(self._config.rate_limit_window_s - elapsed) + 1)

    def add_bytes(self, n: int) -> None:
        """Debita bytes do orçamento do dia (reseta à meia-noite UTC)."""
        with self._lock:
            self._check_day_rollover()
            self._budget_used += n

    def budget_remaining(self) -> int:
        """Bytes restantes hoje; nunca negativo."""
        with self._lock:
            self._check_day_rollover()
            return max(0, self._config.daily_bytes_budget - self._budget_used)

    def cache_mode(self) -> bool:
        """``True`` quando o orçamento acabou: só servimos o cache."""
        return self.budget_remaining() <= 0

    def _check_day_rollover(self) -> None:
        today = self._utc_today()
        if today != self._budget_day:
            self._budget_day = today
            self._budget_used = 0

    def _utc_today(self):
        return datetime.fromtimestamp(self._clock(), timezone.utc).date()
