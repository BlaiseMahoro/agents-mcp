"""Who may do what. Locally everything is allowed; in demo mode (deployment.demo)
chats belong to an anonymous visitor id, settings need the admin token, and
messages are rate limited."""

from __future__ import annotations

import hmac
import os
import re
import threading
import time
from collections import defaultdict, deque
from datetime import date

from fastapi import Header, HTTPException, Request

from agents_core.config import get_config
from agents_core.store import repo
from agents_core.store.db import Conversation

VISITOR_RE = re.compile(r"^[A-Za-z0-9-]{16,64}$")


def demo() -> bool:
    return get_config().deployment.demo


def visitor(x_visitor_id: str | None = Header(default=None)) -> str | None:
    """The browser's anonymous id in demo mode; None locally (everything is shared)."""
    if not demo():
        return None
    if not x_visitor_id or not VISITOR_RE.match(x_visitor_id):
        raise HTTPException(400, "missing or malformed X-Visitor-Id header")
    return x_visitor_id


def is_admin(token: str | None) -> bool:
    if not demo():
        return True
    expected = os.environ.get(get_config().deployment.admin_token_env, "")
    return bool(expected) and bool(token) and hmac.compare_digest(token, expected)


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if not is_admin(x_admin_token):
        raise HTTPException(403, "Settings are managed by the owner of this demo.")


def own_conversation(conv_id: str, owner: str | None) -> Conversation:
    conv = repo.get_conversation(conv_id)
    if not conv or (owner is not None and conv.owner != owner):
        raise HTTPException(404, "conversation not found")
    return conv


def check_plan_access(conversation_id: str | None, owner: str | None) -> None:
    if owner is None:
        return
    if conversation_id is None:
        raise HTTPException(404, "plan not found")
    own_conversation(conversation_id, owner)


class RateLimiter:
    """In-memory limits: messages per visitor and per IP per hour, plus a daily total.

    One API process serves the demo, so memory is enough; limits reset on restart.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._day = date.today()
        self._day_count = 0

    def check(self, limits: dict[str, int], per_day: int) -> None:
        """`limits` maps a key (visitor, IP) to its allowed messages per hour."""
        now = time.monotonic()
        with self._lock:
            if date.today() != self._day:
                self._day, self._day_count = date.today(), 0
            if self._day_count >= per_day:
                raise HTTPException(429, "The demo has reached today's message limit. Please come back tomorrow.")
            for key, per_hour in limits.items():
                hits = self._hits[key]
                while hits and now - hits[0] > 3600:
                    hits.popleft()
                if len(hits) >= per_hour:
                    wait = int(3600 - (now - hits[0])) // 60 + 1
                    raise HTTPException(429, f"You've sent a lot of messages. Try again in about {wait} minutes.")
            for key in limits:
                self._hits[key].append(now)
            self._day_count += 1


limiter = RateLimiter()


def rate_limit(request: Request, owner: str | None) -> None:
    if not demo():
        return
    cfg = get_config().deployment
    ip = request.client.host if request.client else "unknown"
    # People behind one office or campus IP share its allowance, so it is looser than a visitor's.
    limits = {f"visitor:{owner}": cfg.messages_per_visitor_hour, f"ip:{ip}": cfg.messages_per_visitor_hour * 3}
    limiter.check(limits, cfg.messages_per_day)
