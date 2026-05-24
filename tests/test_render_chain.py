"""RenderChain fallback behavior tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from bilivideo.core.exceptions import RenderError
from bilivideo.render.chain import RenderChain


def test_chain_falls_through_failing_backend(tmp_path) -> None:
    chain = RenderChain(output_dir=str(tmp_path), image_width=800)

    class _Failing:
        def render(self, *args, **kwargs):
            raise RenderError("nope")

    class _Working:
        def __init__(self) -> None:
            self.calls = 0

        def render(self, *args, **kwargs):
            self.calls += 1
            (Path(tmp_path) / f"{kwargs['base_filename']}.png").write_bytes(b"fake")
            return [Path(tmp_path) / f"{kwargs['base_filename']}.png"]

    working = _Working()
    chain._backends = [("first", _Failing()), ("second", working)]
    out = chain.render(
        "# test\n\n## 章节\n内容",
        base_filename="t",
        max_cards_per_image=6,
        enable_split=False,
    )
    assert len(out) == 1
    assert working.calls == 1


def test_chain_raises_when_all_fail(tmp_path) -> None:
    chain = RenderChain(output_dir=str(tmp_path))

    class _Failing:
        def render(self, *args, **kwargs):
            raise RenderError("dead")

    chain._backends = [("a", _Failing()), ("b", _Failing())]
    try:
        chain.render(
            "# t\n\nbody",
            base_filename="x",
            max_cards_per_image=6,
            enable_split=False,
        )
    except RenderError as exc:
        assert "all image backends failed" in str(exc)
    else:
        raise AssertionError("expected RenderError")


def test_chain_skips_unavailable_wkhtmltopdf(tmp_path) -> None:
    """When wkhtmltoimage isn't on PATH, only the Pillow backend is added."""

    with patch("bilivideo.render.chain._wkhtmltopdf_available", return_value=False):
        chain = RenderChain(output_dir=str(tmp_path))
    assert chain.available_backends == ["pillow"]
