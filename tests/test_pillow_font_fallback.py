"""Pillow renderer font fallback tests."""

from __future__ import annotations

from bilivideo.render import pillow_renderer


def test_pillow_ready_without_cjk_font_uses_fallback_font(monkeypatch, tmp_path) -> None:
    fallback = tmp_path / "Fallback.ttf"
    fallback.write_bytes(b"fake")

    class _ImageFont:
        @staticmethod
        def truetype(path, _size):
            assert path == str(fallback)
            return object()

    monkeypatch.setattr(pillow_renderer, "_find_cjk_font", lambda: None)
    monkeypatch.setattr(pillow_renderer, "_find_fallback_font", lambda: str(fallback))
    monkeypatch.setitem(__import__("sys").modules, "PIL.ImageFont", _ImageFont)

    ready, reason = pillow_renderer.check_pillow_ready()

    assert ready
    assert "fallback_font" in reason
    assert "no CJK font discovered" in reason
