"""Split a long Markdown document into multiple chapter-bounded pages."""

from __future__ import annotations


def split_by_chapters(markdown_text: str, *, max_cards: int = 6) -> list[str]:
    """Split a Markdown document at `## ` boundaries into pages of up to
    `max_cards` chapters, preserving the document's `# h1` title across
    pages and an `（续）` suffix on continuations.
    """

    lines = markdown_text.split("\n")

    title = "AI 视频总结"
    intro_lines: list[str] = []
    chapters: list[list[str]] = []
    current: list[str] = []

    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1

    if idx < len(lines) and lines[idx].startswith("# "):
        title = lines[idx][2:].strip()
        idx += 1

    while idx < len(lines):
        line = lines[idx]
        if line.startswith("## "):
            break
        intro_lines.append(line)
        idx += 1

    intro = "\n".join(intro_lines).strip()

    while idx < len(lines):
        line = lines[idx]
        if line.startswith("## "):
            if current:
                chapters.append(current)
            current = [line]
        else:
            current.append(line)
        idx += 1
    if current:
        chapters.append(current)

    if not chapters:
        return [f"# {title}\n\n{intro}".rstrip()]

    pages: list[str] = []
    first_count = min(max_cards, len(chapters))
    first_chunks = ["\n".join(c) for c in chapters[:first_count]]
    pages.append(
        f"# {title}\n\n{intro}\n\n" + "\n\n".join(first_chunks) if intro else
        f"# {title}\n\n" + "\n\n".join(first_chunks)
    )

    remaining = chapters[first_count:]
    while remaining:
        slice_ = remaining[:max_cards]
        remaining = remaining[max_cards:]
        chunks = ["\n".join(c) for c in slice_]
        pages.append(f"# {title}(续)\n\n" + "\n\n".join(chunks))
    return pages
