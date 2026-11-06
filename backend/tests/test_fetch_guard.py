import pytest

from agents_core.tools.search import BlockedURL, check_public_url


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/computeMetadata/v1/",  # cloud metadata server
        "http://metadata.google.internal/",
        "http://localhost:8000/api/settings",
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://[::1]/",
        "file:///etc/passwd",
        "ftp://example.com/x",
    ],
)
async def test_blocks_private_and_non_http(url):
    with pytest.raises(BlockedURL):
        await check_public_url(url)


async def test_allows_public_host(monkeypatch):
    import asyncio

    async def fake_getaddrinfo(host, port, *a, **k):
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)
    await check_public_url("https://example.com/page")
