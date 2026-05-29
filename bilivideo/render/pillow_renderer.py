"""Pillow-based fallback renderer.

When wkhtmltopdf isn't installed (Debian 13 dropped the package, Docker
containers without xvfb, etc.) we still want image output. Pillow is a
much smaller dep and ships with most Python installs, so we use it to
render a simple card-style image — visually less rich than the HTML
version, but still readable and unifrom.

Notable simplifications vs. the HTML renderer:
  * No background blur, gradients, or radial glows
  * Uses the best font we can discover. A CJK font is preferred, but
    missing CJK fonts should not prevent image output.
  * No code blocks / tables (rendered as plain monospaced lines)
  * Uses solid color cards with a left accent strip
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..core.exceptions import PartialRenderError, RenderError
from ..core.logging import get_logger
from .pagination import split_by_chapters
from .theme import card_color_for

if TYPE_CHECKING:  # pragma: no cover
    from PIL.ImageFont import FreeTypeFont

logger = get_logger("BiliVideo/PillowRender")


# ──────────────────────── font discovery ────────────────────────


_CJK_FONT_CANDIDATES: tuple[str, ...] = (
    # Linux
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    # Windows
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    "/mnt/c/Windows/Fonts/msyh.ttc",
    "/mnt/c/Windows/Fonts/simhei.ttf",
    "/mnt/c/Windows/Fonts/simsun.ttc",
)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_FALLBACK_FONT_CANDIDATES: tuple[str, ...] = (
    str(_REPO_ROOT / "fonts" / "JetBrainsMono-Light.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/mnt/c/Windows/Fonts/arial.ttf",
)


def _find_cjk_font() -> str | None:
    for candidate in _CJK_FONT_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return None


def _find_fallback_font() -> str | None:
    for candidate in _FALLBACK_FONT_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return None


def check_pillow_ready() -> tuple[bool, str]:
    """Return whether Pillow can produce images in this environment."""

    try:
        from PIL import ImageFont
    except ImportError as exc:
        return False, f"Pillow not installed: {exc}"

    font_path = _find_cjk_font()
    if font_path is not None:
        try:
            ImageFont.truetype(font_path, 14)
        except Exception as exc:
            return False, f"CJK font cannot be loaded: {font_path} ({exc})"
        return True, f"font={font_path}"

    fallback_path = _find_fallback_font()
    if fallback_path is None:
        return True, "ready with Pillow default font; no CJK font discovered"
    try:
        ImageFont.truetype(fallback_path, 14)
    except Exception as exc:
        return False, f"fallback font cannot be loaded: {fallback_path} ({exc})"
    return True, f"fallback_font={fallback_path}; no CJK font discovered"


def _load_font(size: int):
    from PIL import ImageFont

    font_path = _find_cjk_font() or _find_fallback_font()
    if font_path is not None:
        try:
            return ImageFont.truetype(font_path, size), font_path
        except Exception as exc:
            logger.warning(f"font load failed ({font_path}): {exc}; using Pillow default")
    return ImageFont.load_default(), "Pillow default"


# ──────────────────────── markdown parsing ────────────────────────


@dataclass(slots=True)
class _Block:
    kind: str  # "h1" | "h2" | "h3" | "p" | "li"
    text: str


def _parse_markdown_blocks(markdown_text: str) -> list[_Block]:
    """Very small markdown-ish tokenizer producing block-level elements."""

    out: list[_Block] = []
    in_code = False
    for raw in markdown_text.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            out.append(_Block("p", line))
            continue
        if not line.strip():
            continue
        if line.startswith("# "):
            out.append(_Block("h1", line[2:].strip()))
        elif line.startswith("## "):
            out.append(_Block("h2", line[3:].strip()))
        elif line.startswith("### "):
            out.append(_Block("h3", line[4:].strip()))
        elif line.startswith(("- ", "* ", "+ ")):
            out.append(_Block("li", line[2:].strip()))
        elif re.match(r"^\d+\.\s", line):
            out.append(_Block("li", re.sub(r"^\d+\.\s", "", line).strip()))
        elif line.startswith("> "):
            out.append(_Block("p", "“" + line[2:].strip() + "”"))
        else:
            # strip Markdown emphasis for plain rendering
            cleaned = re.sub(r"\*\*?(.+?)\*\*?", r"\1", line.strip())
            cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
            out.append(_Block("p", cleaned))
    return out


# ──────────────────────── renderer ────────────────────────


class PillowRenderer:
    """Render Markdown into PNG cards using only Pillow.

    Layout: dark background, single column, one card per `## chapter`
    section, with a left accent stripe color-cycled through the same
    palette as the wkhtmltopdf renderer.
    """

    BG = (26, 27, 46)
    CARD_BG = (30, 33, 64)
    TITLE_FG = (241, 245, 249)
    TEXT_FG = (201, 206, 220)
    ACCENT_FG = (147, 197, 253)
    DIM_FG = (148, 163, 184)
    PADDING = 40
    CARD_PADDING = 24
    CARD_GAP = 18

    def __init__(self, *, output_dir: str | Path, image_width: int = 1400) -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._width = image_width

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def render(
        self,
        markdown_text: str,
        *,
        base_filename: str,
        max_cards_per_image: int = 6,
        enable_split: bool = True,
    ) -> list[Path]:
        chapter_count = sum(1 for line in markdown_text.splitlines() if line.startswith("## "))
        if not enable_split or chapter_count <= max_cards_per_image:
            return self._render_one(markdown_text, base_filename, page_label=None, total=1)

        pages = split_by_chapters(markdown_text, max_cards=max_cards_per_image)
        outputs: list[Path] = []
        failed_pages: list[int] = []
        page_errors: dict[int, str] = {}
        total = len(pages)
        for idx, page in enumerate(pages, start=1):
            label = None if total == 1 else f"({idx}/{total})"
            try:
                outputs.extend(
                    self._render_one(page, f"{base_filename}_p{idx}", page_label=label, total=total)
                )
            except RenderError as exc:
                logger.warning(
                    f"page {idx}/{total} pillow render failed: {exc}; "
                    f"page_chars={len(page)} chapters={page.count(chr(10) + '## ')}"
                )
                failed_pages.append(idx)
                page_errors[idx] = str(exc)
        if failed_pages and outputs:
            raise PartialRenderError(
                f"partial pillow render failed; failed_pages={failed_pages}, "
                f"succeeded_pages={[p.name for p in outputs]}",
                generated_paths=outputs,
                failed_pages=failed_pages,
                page_errors=page_errors,
            )
        if not outputs:
            raise RenderError("all pages failed to render with Pillow")
        return outputs

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _render_one(
        self,
        markdown_text: str,
        base_filename: str,
        *,
        page_label: str | None,
        total: int,
    ) -> list[Path]:
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise RenderError(f"Pillow not installed: {exc}") from exc

        blocks = _parse_markdown_blocks(markdown_text)
        if not blocks:
            blocks.append(_Block("p", "(空内容)"))

        title_block = next((b for b in blocks if b.kind == "h1"), None)
        body_blocks = [b for b in blocks if b is not title_block]
        title_text = title_block.text if title_block else "AI 视频总结"
        if page_label:
            title_text = f"{title_text} {page_label}"

        f_title, font_path = _load_font(26)
        f_h2, _ = _load_font(19)
        f_h3, _ = _load_font(16)
        f_body, _ = _load_font(14)

        # split body into cards by h2
        cards = self._group_into_cards(body_blocks)

        # measurement pass: compute image height
        body_max_width = self._width - self.PADDING * 2
        line_h_h2 = 30

        def text_height(font: ImageFont.FreeTypeFont, lines: list[str]) -> int:
            return len(lines) * (font.size + 6)

        cards_with_lines: list[tuple[int, str | None, list[tuple[str, list[str]]]]] = []
        for chapter_idx, (heading, blocks_) in enumerate(cards):
            wrapped: list[tuple[str, list[str]]] = []
            for b in blocks_:
                lines = self._wrap(b.text, font=f_body, max_width=body_max_width - self.CARD_PADDING * 2)
                wrapped.append((b.kind, lines))
            cards_with_lines.append((chapter_idx, heading, wrapped))

        total_h = self.PADDING + 60  # header
        for _, heading, wrapped in cards_with_lines:
            card_h = self.CARD_PADDING * 2
            if heading is not None:
                card_h += line_h_h2 + 8
            for kind, lines in wrapped:
                if kind == "h3":
                    card_h += text_height(f_h3, lines) + 4
                else:
                    card_h += text_height(f_body, lines) + 4
            total_h += card_h + self.CARD_GAP
        total_h += 50  # footer
        logger.debug(
            f"pillow page layout: chars={len(markdown_text)} cards={len(cards_with_lines)} "
            f"height={total_h} width={self._width} font={font_path}"
        )

        # actually paint
        img = Image.new("RGB", (self._width, total_h), self.BG)
        draw = ImageDraw.Draw(img)

        # Header
        draw.text((self.PADDING, self.PADDING), title_text, fill=self.TITLE_FG, font=f_title)
        draw.line(
            (self.PADDING, self.PADDING + 38, self.PADDING + 80, self.PADDING + 38),
            fill=self.ACCENT_FG,
            width=3,
        )

        y = self.PADDING + 60
        for chapter_idx, heading, wrapped in cards_with_lines:
            border, _ = card_color_for(chapter_idx)
            border_rgb = self._hex_to_rgb(border)
            card_h = self.CARD_PADDING * 2
            if heading is not None:
                card_h += line_h_h2 + 8
            for kind, lines in wrapped:
                if kind == "h3":
                    card_h += text_height(f_h3, lines) + 4
                else:
                    card_h += text_height(f_body, lines) + 4

            # card background
            card_x0 = self.PADDING
            card_x1 = self._width - self.PADDING
            draw.rounded_rectangle(
                (card_x0, y, card_x1, y + card_h),
                radius=12,
                fill=self.CARD_BG,
            )
            # left stripe
            draw.rectangle((card_x0, y, card_x0 + 4, y + card_h), fill=border_rgb)

            cy = y + self.CARD_PADDING
            cx = card_x0 + self.CARD_PADDING
            if heading is not None:
                draw.text((cx, cy), heading, fill=self.TITLE_FG, font=f_h2)
                cy += line_h_h2 + 8

            for kind, lines in wrapped:
                font = f_h3 if kind == "h3" else f_body
                color = self.ACCENT_FG if kind == "h3" else self.TEXT_FG
                if kind == "li":
                    bullet = "• "
                    for i, line in enumerate(lines):
                        prefix = bullet if i == 0 else "  "
                        draw.text((cx, cy), prefix + line, fill=color, font=font)
                        cy += font.size + 6
                else:
                    for line in lines:
                        draw.text((cx, cy), line, fill=color, font=font)
                        cy += font.size + 6
                cy += 4

            y += card_h + self.CARD_GAP

        footer_text = f"Pillow renderer · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        if total > 1 and page_label:
            footer_text += f" · {page_label}"
        draw.text(
            (self.PADDING, total_h - 30),
            footer_text,
            fill=self.DIM_FG,
            font=f_body,
        )

        out = self._output_dir / f"{base_filename}.png"
        try:
            img.save(out, "PNG", optimize=True)
        except OSError as exc:
            raise RenderError(f"Pillow save failed: {exc}") from exc
        logger.info(f"pillow rendered {out.name} ({out.stat().st_size} bytes)")
        return [out]

    @staticmethod
    def _group_into_cards(
        blocks: Sequence[_Block],
    ) -> list[tuple[str | None, list[_Block]]]:
        cards: list[tuple[str | None, list[_Block]]] = []
        current: list[_Block] = []
        current_heading: str | None = None
        for b in blocks:
            if b.kind == "h2":
                if current_heading is not None or current:
                    cards.append((current_heading, current))
                current = []
                current_heading = b.text
            else:
                current.append(b)
        cards.append((current_heading, current))
        return cards

    @staticmethod
    def _wrap(
        text: str,
        *,
        font: FreeTypeFont,
        max_width: int,
    ) -> list[str]:
        """Break a string into wrapped lines without splitting CJK characters."""

        if not text:
            return [""]

        lines: list[str] = []
        current = ""
        for ch in text:
            test = current + ch
            try:
                bbox = font.getbbox(test)
                width = bbox[2] - bbox[0]
            except Exception:
                width = len(test) * (font.size // 2)
            if width <= max_width:
                current = test
                continue
            if current:
                lines.append(current)
            current = ch
        if current:
            lines.append(current)
        return lines or [""]

    @staticmethod
    def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
        s = hex_str.lstrip("#")
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
