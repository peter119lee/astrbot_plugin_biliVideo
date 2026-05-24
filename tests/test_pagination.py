"""Markdown pagination tests."""

from __future__ import annotations

from bilivideo.render.pagination import split_by_chapters


def _doc(chapter_count: int) -> str:
    parts = ["# 视频标题", "引言段落"]
    for i in range(chapter_count):
        parts.append(f"## 章节{i}")
        parts.append(f"内容{i}")
    return "\n".join(parts)


class TestSplitByChapters:
    def test_no_chapters(self) -> None:
        out = split_by_chapters("# Title\n\n本文无章节", max_cards=6)
        assert out == ["# Title\n\n本文无章节"]

    def test_single_page(self) -> None:
        out = split_by_chapters(_doc(3), max_cards=6)
        assert len(out) == 1
        assert out[0].startswith("# 视频标题")

    def test_multi_page(self) -> None:
        out = split_by_chapters(_doc(8), max_cards=6)
        assert len(out) == 2
        assert out[0].count("## 章节") == 6
        assert out[1].count("## 章节") == 2
        assert out[1].startswith("# 视频标题(续)")

    def test_chapter_intact_per_page(self) -> None:
        out = split_by_chapters(_doc(13), max_cards=5)
        assert len(out) == 3
        assert sum(p.count("## 章节") for p in out) == 13
