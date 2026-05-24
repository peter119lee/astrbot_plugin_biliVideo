"""CookieJar atomic write + load tests."""

from __future__ import annotations

import json

from bilivideo.auth.cookies import CookieJar


def test_save_and_load(tmp_path) -> None:
    jar = CookieJar(tmp_path)
    assert not jar.is_logged_in()
    jar.save({"SESSDATA": "abc", "bili_jct": "xyz"})
    assert jar.is_logged_in()
    assert jar.get() == {"SESSDATA": "abc", "bili_jct": "xyz"}

    # reload from disk
    jar2 = CookieJar(tmp_path)
    assert jar2.is_logged_in()
    assert jar2.get()["SESSDATA"] == "abc"


def test_save_drops_empty_values(tmp_path) -> None:
    jar = CookieJar(tmp_path)
    jar.save({"SESSDATA": "abc", "empty": ""})
    assert "empty" not in jar.get()


def test_save_without_sessdata_is_noop(tmp_path) -> None:
    jar = CookieJar(tmp_path)
    jar.save({"bili_jct": "xyz"})
    assert not jar.is_logged_in()
    assert not (tmp_path / "bili_cookies.json").exists()


def test_clear(tmp_path) -> None:
    jar = CookieJar(tmp_path)
    jar.save({"SESSDATA": "abc"})
    assert (tmp_path / "bili_cookies.json").exists()
    jar.clear()
    assert not jar.is_logged_in()
    assert not (tmp_path / "bili_cookies.json").exists()


def test_corrupted_file_falls_back(tmp_path) -> None:
    (tmp_path / "bili_cookies.json").write_text("not json", encoding="utf-8")
    jar = CookieJar(tmp_path)
    assert not jar.is_logged_in()


def test_atomic_write_persists_valid_json(tmp_path) -> None:
    jar = CookieJar(tmp_path)
    jar.save({"SESSDATA": "x" * 100})
    raw = (tmp_path / "bili_cookies.json").read_text(encoding="utf-8")
    payload = json.loads(raw)
    assert payload["SESSDATA"] == "x" * 100
