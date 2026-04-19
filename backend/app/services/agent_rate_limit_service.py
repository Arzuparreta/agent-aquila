from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, status

from app.core.config import settings

_WINDOW_SEC = 3600


class AgentRateLimitService:
    _by_user: dict[int, deque[float]] = defaultdict(deque)
    # Separate bucket for proactive (worker-spawned) runs so the synchronous
    # API quota is unaffected by background traffic.
    _proactive_by_user: dict[int, deque[float]] = defaultdict(deque)

    @classmethod
    def check(cls, user_id: int) -> None:
        now = time.monotonic()
        q = cls._by_user[user_id]
        while q and now - q[0] > _WINDOW_SEC:
            q.popleft()
        limit = settings.agent_max_runs_per_hour
        if len(q) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Agent run rate limit exceeded; try again later.",
            )
        q.append(now)

    @classmethod
    def try_consume_heartbeat(cls, user_id: int) -> bool:
        """Non-raising counterpart used by the agent heartbeat worker.

        Returns ``True`` when the burst budget allows another background
        agent run for ``user_id``, ``False`` otherwise.
        ``agent_heartbeat_burst_per_hour=0`` disables the cap.
        """
        limit = settings.agent_heartbeat_burst_per_hour
        if limit <= 0:
            return True
        now = time.monotonic()
        q = cls._proactive_by_user[user_id]
        while q and now - q[0] > _WINDOW_SEC:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True
