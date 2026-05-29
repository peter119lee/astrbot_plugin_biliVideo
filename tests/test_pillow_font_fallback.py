"""Pillow renderer font fallback tests."""

from __future__ import annotations

from io import BytesIO

from bilivideo.render import pillow_renderer


def test_pillow_ready_without_cjk_font_uses_fallback_font(monkeypatch, tmp_path) -> None:
    fallback = tmp_path / "Fallback.ttf"
    fallback.write_bytes(b"fake")

    class _ImageFont:
        @staticmethod
        def truetype(path, _size):
            assert path == str(fallback)
            return object()

    def _missing_cjk_font(_extra_dirs=()):
        return None

    monkeypatch.setattr(pillow_renderer, "_find_cjk_font", _missing_cjk_font)
    monkeypatch.setattr(pillow_renderer, "_find_fallback_font", lambda: str(fallback))
    monkeypatch.setitem(__import__("sys").modules, "PIL.ImageFont", _ImageFont)

    ready, reason = pillow_renderer.check_pillow_ready()

    assert ready
    assert "fallback_font" in reason
    assert "no CJK font discovered" in reason


def test_pillow_ready_downloads_cjk_font_to_cache(monkeypatch, tmp_path) -> None:
    font_bytes = b"x" * (pillow_renderer._MIN_CJK_FONT_BYTES + 1)

    class _Response(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    class _ImageFont:
        @staticmethod
        def truetype(path, _size):
            assert str(path).endswith(pillow_renderer._BUNDLED_CJK_FONT_NAME)
            return object()

    def _missing_cjk_font(_extra_dirs=()):
        return None

    def _urlopen(*_args, **_kwargs):
        return _Response(font_bytes)

    monkeypatch.setattr(pillow_renderer, "_find_cjk_font", _missing_cjk_font)
    monkeypatch.setattr(pillow_renderer.urllib.request, "urlopen", _urlopen)
    monkeypatch.setitem(__import__("sys").modules, "PIL.ImageFont", _ImageFont)

    ready, reason = pillow_renderer.check_pillow_ready(tmp_path)

    cached = tmp_path / pillow_renderer._BUNDLED_CJK_FONT_NAME
    assert ready
    assert cached.exists()
    assert cached.read_bytes() == font_bytes
    assert reason == f"font={cached}"
