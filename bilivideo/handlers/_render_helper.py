"""Bridge between the renderer and the AstrBot message components.

`render_note_components()` returns either a list of `Image` components
(image mode) or a plain string (text mode), so handlers can decide how to
package the result without knowing about the renderer internals.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..core.exceptions import PartialRenderError, RenderError
from ..core.logging import get_logger
from ..services import BiliVideoServices

logger = get_logger("BiliVideo/RenderHelper")

try:
    from astrbot.api.message_components import Image, Plain  # type: ignore[import]
except Exception:  # pragma: no cover - test stub
    Image = None  # type: ignore[assignment]
    Plain = None  # type: ignore[assignment]


def render_note_components(services: BiliVideoServices, markdown_text: str) -> list[Any] | str:
    """Convert Markdown to either a list of Image components or raw text."""

    if not services.config.output_image:
        return markdown_text
    if Image is None:
        return markdown_text

    base_filename = f"note_{int(time.time() * 1000)}"
    try:
        paths = services.renderer.render(
            markdown_text,
            base_filename=base_filename,
            max_cards_per_image=services.config.max_cards_per_image,
            enable_split=services.config.enable_auto_split,
        )
        partial_failed_pages: list[int] = []
    except PartialRenderError as exc:
        logger.warning(f"partial render fallback text appended: {exc}")
        paths = exc.generated_paths
        partial_failed_pages = exc.failed_pages
    except RenderError as exc:
        logger.warning(f"render fallback to text: {exc}")
        return markdown_text

    components: list[Any] = []
    fallback_texts: list[str] = []
    invalid_paths: list[str] = []
    for path in paths:
        if not isinstance(path, Path):
            path = Path(path)
        if not path.exists() or path.stat().st_size <= 0:
            invalid_paths.append(str(path))
            continue
        try:
            components.append(Image.fromFileSystem(str(path)))
        except Exception as exc:
            logger.warning(f"image component build failed for {path}: {exc}")
            fallback_texts.append(f"⚠️ 图片文件 {path.name} 发送失败,以下为文本兜底:\n\n{markdown_text}")
    if partial_failed_pages:
        fallback_texts.append(
            f"⚠️ 第 {', '.join(str(p) for p in partial_failed_pages)} 页图片生成失败,"
            "以下为完整文本兜底:\n\n" + markdown_text
        )
    if invalid_paths:
        logger.warning(f"renderer returned invalid image paths: {invalid_paths}")
        fallback_texts.append(
            "⚠️ 部分总结图片生成失败,以下为完整文本兜底:\n\n" + markdown_text
        )
    if not components:
        return markdown_text
    if fallback_texts:
        fallback_text = "\n\n".join(fallback_texts)
        if Plain is None:
            logger.warning("Plain component unavailable; cannot append render fallback text")
            return components
        components.append(Plain(fallback_text))
    return components
