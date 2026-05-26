"""Manual summary URL extraction/canonicalization tests."""

from __future__ import annotations

import pytest

from bilivideo.handlers.summary import _canonicalize_video_url, _extract_video_url


class _HTTP:
    def __init__(self, resolved: str | None) -> None:
        self.resolved = resolved
        self.urls: list[str] = []

    async def follow_redirect(self, url: str) -> str | None:
        self.urls.append(url)
        return self.resolved


class _Services:
    def __init__(self, resolved: str | None) -> None:
        self.http_client = _HTTP(resolved)


def test_manual_summary_cleans_short_url_argument() -> None:
    url = _extract_video_url("/总结 https://b23.tv/abc，", object())
    assert url == "https://b23.tv/abc"


@pytest.mark.asyncio
async def test_canonicalize_other_bili_short_domain() -> None:
    services = _Services("https://www.bilibili.com/video/BV1xx411c7mD")

    out = await _canonicalize_video_url(services, "https://bili2233.cn/abc")

    assert out == "https://www.bilibili.com/video/BV1xx411c7mD"
    assert services.http_client.urls == ["https://bili2233.cn/abc"]


@pytest.mark.asyncio
async def test_canonicalize_short_url_failure_returns_empty() -> None:
    services = _Services(None)

    assert await _canonicalize_video_url(services, "https://b23.tv/bad") == ""
