"""Audio downloader & subtitle harvester via yt-dlp.

Refactored from the previous `BilibiliDownloader`:
  * subtitle parsing extracted into helpers so it can be reused/tested
  * cookie file lifecycle isolated; we always overwrite to keep it in sync
  * uses dataclasses from `core.types`
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

import yt_dlp

from ..core.constants import QUALITY_TO_KBPS
from ..core.exceptions import DownloadError, TranscriptionError
from ..core.logging import get_logger
from ..core.types import AudioDownloadResult, TranscriptResult, TranscriptSegment

logger = get_logger("BiliVideo/Download")

DEFAULT_SUBTITLE_LANGS: tuple[str, ...] = (
    "zh-Hans",
    "zh",
    "zh-CN",
    "ai-zh",
    "en",
    "en-US",
)


class YtDlpDownloader:
    """Bilibili audio + subtitle downloader."""

    def __init__(self, data_dir: str | Path, *, cookies: Mapping[str, str] | None = None) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._cookies_file: Path | None = None
        self.update_cookies(cookies)

    # ------------------------------------------------------------------
    # cookie helpers
    # ------------------------------------------------------------------
    def update_cookies(self, cookies: Mapping[str, str] | None) -> None:
        if not cookies:
            self._cookies_file = None
            return
        path = self._data_dir / "cookies.txt"
        lines = ["# Netscape HTTP Cookie File"]
        for name, value in cookies.items():
            if value:
                lines.append(f".bilibili.com\tTRUE\t/\tFALSE\t0\t{name}\t{value}")
        try:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            os.chmod(path, 0o600)
        except OSError as exc:
            logger.warning(f"cookies.txt write failed: {exc}")
            self._cookies_file = None
            return
        self._cookies_file = path

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def download_audio(
        self,
        video_url: str,
        *,
        output_dir: str | Path | None = None,
        quality: str = "fast",
    ) -> AudioDownloadResult:
        target = Path(output_dir) if output_dir else self._data_dir
        target.mkdir(parents=True, exist_ok=True)

        opts = {
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": str(target / "%(id)s.%(ext)s"),
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": QUALITY_TO_KBPS.get(quality, "64"),
                }
            ],
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }
        if self._cookies_file and self._cookies_file.exists():
            opts["cookiefile"] = str(self._cookies_file)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
        except yt_dlp.utils.DownloadError as exc:
            raise DownloadError(str(exc)) from exc

        video_id = info.get("id", "")
        audio_path = target / f"{video_id}.mp3"
        return AudioDownloadResult(
            file_path=str(audio_path),
            title=str(info.get("title", "")),
            duration=float(info.get("duration", 0) or 0),
            cover_url=info.get("thumbnail"),
            platform="bilibili",
            video_id=str(video_id),
            raw_info=dict(info),
        )

    def download_subtitles(
        self,
        video_url: str,
        *,
        output_dir: str | Path | None = None,
        langs: Iterable[str] | None = None,
    ) -> TranscriptResult | None:
        target = Path(output_dir) if output_dir else self._data_dir
        target.mkdir(parents=True, exist_ok=True)
        lang_list = list(langs) if langs else list(DEFAULT_SUBTITLE_LANGS)
        video_id = _extract_video_id_from_url(video_url) or "video"

        opts = {
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": lang_list,
            "subtitlesformat": "srt/json3/best",
            "skip_download": True,
            "outtmpl": str(target / f"{video_id}.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        if self._cookies_file and self._cookies_file.exists():
            opts["cookiefile"] = str(self._cookies_file)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
        except yt_dlp.utils.DownloadError as exc:
            logger.warning(f"subtitle download failed: {exc}")
            return None

        subtitles = info.get("requested_subtitles") or {}
        if not subtitles:
            logger.info(f"{video_id}: no platform subtitles")
            return None

        for lang in lang_list:
            if lang in subtitles:
                return _parse_sub(subtitles[lang], lang, target, video_id)
        # any other available language except 'danmaku'
        for lang, sub_info in subtitles.items():
            if lang == "danmaku":
                continue
            return _parse_sub(sub_info, lang, target, video_id)
        return None


# ──────────────────────────── helpers ──────────────────────────────


def _extract_video_id_from_url(url: str) -> str | None:
    match = re.search(r"BV[0-9A-Za-z]{10}", url or "")
    return match.group(0) if match else None


def _parse_sub(sub_info: dict, language: str, output_dir: Path, video_id: str) -> TranscriptResult | None:
    inline = sub_info.get("data")
    if isinstance(inline, str) and inline:
        return _parse_srt(inline, language)
    ext = sub_info.get("ext", "srt")
    path = output_dir / f"{video_id}.{language}.{ext}"
    if not path.exists():
        return None
    if ext == "json3":
        return _parse_json3(path, language)
    try:
        return _parse_srt(path.read_text(encoding="utf-8"), language)
    except OSError as exc:
        raise TranscriptionError(f"subtitle file read error: {exc}") from exc


def _parse_srt(content: str, language: str) -> TranscriptResult | None:
    pattern = re.compile(
        r"(\d+)\n(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\n(.*?)(?=\n\n|\n\d+\n|$)",
        re.DOTALL,
    )
    segments: list[TranscriptSegment] = []
    for _, start_t, end_t, text in pattern.findall(content):
        text = text.strip()
        if not text:
            continue
        segments.append(
            TranscriptSegment(
                start=_srt_time(start_t),
                end=_srt_time(end_t),
                text=text,
            )
        )
    if not segments:
        return None
    full_text = " ".join(seg.text for seg in segments)
    return TranscriptResult(
        language=language,
        full_text=full_text,
        segments=tuple(segments),
        raw={"source": "bilibili_subtitle", "format": "srt"},
    )


def _parse_json3(path: Path, language: str) -> TranscriptResult | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"json3 subtitle parse failed: {exc}")
        return None

    segments: list[TranscriptSegment] = []
    for event in data.get("events", []):
        start_ms = event.get("tStartMs", 0)
        duration_ms = event.get("dDurationMs", 0)
        text = "".join(s.get("utf8", "") for s in event.get("segs", [])).strip()
        if not text:
            continue
        segments.append(
            TranscriptSegment(
                start=start_ms / 1000.0,
                end=(start_ms + duration_ms) / 1000.0,
                text=text,
            )
        )
    if not segments:
        return None
    return TranscriptResult(
        language=language,
        full_text=" ".join(seg.text for seg in segments),
        segments=tuple(segments),
        raw={"source": "bilibili_subtitle", "format": "json3"},
    )


def _srt_time(token: str) -> float:
    parts = token.replace(",", ".").split(":")
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
