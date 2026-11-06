"""Identity tokens for calling a private Cloud Run service from a Google Cloud VM.

The VM's service account needs roles/run.invoker on the service. Tokens come from
the metadata server and last an hour; we refresh a little early.
"""

from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit

import httpx

METADATA_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity"
REFRESH_AFTER_S = 45 * 60

_cache: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()


def audience_for(base_url: str) -> str:
    """Cloud Run expects the service root URL as the audience, without the /v1 path."""
    parts = urlsplit(base_url)
    return f"{parts.scheme}://{parts.netloc}"


def id_token(audience: str) -> str:
    with _lock:
        cached = _cache.get(audience)
        if cached and time.monotonic() - cached[1] < REFRESH_AFTER_S:
            return cached[0]
    resp = httpx.get(METADATA_URL, params={"audience": audience, "format": "full"}, headers={"Metadata-Flavor": "Google"}, timeout=5)
    resp.raise_for_status()
    token = resp.text.strip()
    with _lock:
        _cache[audience] = (token, time.monotonic())
    return token
