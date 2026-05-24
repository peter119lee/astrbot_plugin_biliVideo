"""Bridge between the renderer and the AstrBot message components.

`render_note_components()` returns either a list of `Image` components
(image mode) or a plain string (text mode), so handlers can decide how to
package the result without knowing about the renderer internals.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..core.exceptions import RenderError
from ..core.logging import get_logger
from ..services import BiliVideoServices

logger = get_logger("BiliVideo/RenderHelper")

try:
    from astrbot.api.message_components import Image  # type: ignore[import]
except Exception:  # pragma: no cover - test stub
    Image = None  # type: ignore[assignment]


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
    except RenderError as exc:
        logger.warning(f"render fallback to text: {exc}")
        return markdown_text

    components: list[Any] = []
    for path in paths:
        if not isinstance(path, Path):
            path = Path(path)
        if path.exists():
            components.append(Image.fromFileSystem(str(path)))
    if not components:
        return markdown_text
    return components
