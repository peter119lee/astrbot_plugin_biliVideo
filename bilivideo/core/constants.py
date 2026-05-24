"""Centralized constants: regexes, endpoints, user agents, defaults.

Keeping all magic strings/numbers in one file makes it trivial to:
  * audit network traffic surface
  * update User-Agent or endpoints when Bilibili changes them
  * unit-test regex behavior without importing handler code
"""

from __future__ import annotations

import re
from typing import Final

# ──────────────────────────── HTTP ───────────────────────────────

DEFAULT_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_REFERER: Final[str] = "https://www.bilibili.com"

# Lower than 30s so a stalled server doesn't hold up the event loop forever
HTTP_TIMEOUT_SECONDS: Final[int] = 12
HTTP_MAX_RETRIES: Final[int] = 3
HTTP_BACKOFF_BASE: Final[float] = 0.6  # seconds; exponential backoff base

# ───────────────────────── Bilibili API ──────────────────────────

API_BASE: Final[str] = "https://api.bilibili.com"
PASSPORT_BASE: Final[str] = "https://passport.bilibili.com"

ENDPOINT_NAV: Final[str] = f"{API_BASE}/x/web-interface/nav"
ENDPOINT_VIEW: Final[str] = f"{API_BASE}/x/web-interface/view"
ENDPOINT_USER_INFO: Final[str] = f"{API_BASE}/x/space/wbi/acc/info"
ENDPOINT_USER_VIDEOS: Final[str] = f"{API_BASE}/x/space/wbi/arc/search"
ENDPOINT_SEARCH_TYPE_WBI: Final[str] = f"{API_BASE}/x/web-interface/wbi/search/type"
ENDPOINT_SEARCH_TYPE: Final[str] = f"{API_BASE}/x/web-interface/search/type"
ENDPOINT_QR_GENERATE: Final[str] = f"{PASSPORT_BASE}/x/passport-login/web/qrcode/generate"
ENDPOINT_QR_POLL: Final[str] = f"{PASSPORT_BASE}/x/passport-login/web/qrcode/poll"

# Necessary cookies for many search endpoints
ESSENTIAL_COOKIES: Final[tuple[str, ...]] = ("buvid3",)

BILI_DOMAINS: Final[tuple[str, ...]] = (
    "bilibili.com",
    "b23.tv",
    "bili2233.cn",
    "bili22.cn",
    "bili23.cn",
    "bili33.cn",
)

# ──────────────────────────── Regex ──────────────────────────────

BV_REGEX: Final[re.Pattern[str]] = re.compile(r"BV[0-9A-Za-z]{10}")
UID_REGEX: Final[re.Pattern[str]] = re.compile(r"space\.bilibili\.com/(\d+)")
LONG_URL_REGEX: Final[re.Pattern[str]] = re.compile(
    r"https?://(?:www\.)?bilibili\.com/video/[A-Za-z0-9/?=&_.\-]+"
)
SHORT_URL_REGEX: Final[re.Pattern[str]] = re.compile(r"https?://b23\.tv/\S+")
QQDOC_URL_REGEX: Final[re.Pattern[str]] = re.compile(r'"qqdocurl"\s*:\s*"(https?://[^"]+)"')
TIMESTAMP_REGEX: Final[re.Pattern[str]] = re.compile(
    r"(?:\*?)Content-(?:\[(\d{2}):(\d{2})\]|(\d{2}):(\d{2}))"
)

# ──────────────────────────── Misc ───────────────────────────────

QUALITY_TO_KBPS: Final[dict[str, str]] = {
    "fast": "32",
    "medium": "64",
    "slow": "128",
}

NOTE_STYLES: Final[tuple[str, ...]] = ("concise", "detailed", "professional")
LLM_PROVIDERS: Final[tuple[str, ...]] = ("astrbot", "openai_compatible")
ACCESS_MODES: Final[tuple[str, ...]] = ("blacklist", "whitelist")

WBI_CACHE_TTL_SECONDS: Final[int] = 86_400  # 24h
VIDEO_INFO_CACHE_TTL_SECONDS: Final[int] = 600  # 10min
VIDEO_INFO_CACHE_MAX: Final[int] = 256
