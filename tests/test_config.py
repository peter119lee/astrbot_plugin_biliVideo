"""Config validation tests."""

from __future__ import annotations

from bilivideo.core.config import PluginConfig


def test_defaults() -> None:
    cfg = PluginConfig.from_mapping({})
    assert cfg.note_style == "professional"
    assert cfg.max_cards_per_image == 6
    assert cfg.access_mode == "blacklist"
    assert "总结" in cfg.trigger_keywords


def test_invalid_enum_falls_back() -> None:
    cfg = PluginConfig.from_mapping({"note_style": "invalid"})
    assert cfg.note_style == "professional"


def test_int_clamps_within_range() -> None:
    cfg = PluginConfig.from_mapping({"max_note_length": 99})
    assert cfg.max_note_length == 500  # clamped to lo=500
    cfg = PluginConfig.from_mapping({"max_note_length": 99999})
    assert cfg.max_note_length == 12000  # clamped to hi


def test_csv_split() -> None:
    cfg = PluginConfig.from_mapping({"push_groups": "100,200,abc, 300 "})
    assert cfg.push_groups == ("100", "200", "300")  # 'abc' filtered (not isdigit)


def test_trigger_keywords_custom() -> None:
    cfg = PluginConfig.from_mapping({"trigger_keywords": "abc,def"})
    assert cfg.trigger_keywords == ("abc", "def")


def test_openai_compatible_predicate() -> None:
    cfg = PluginConfig.from_mapping(
        {
            "llm_provider": "openai_compatible",
            "llm_api_base": "https://x/v1",
            "llm_api_key": "sk-x",
        }
    )
    assert cfg.is_openai_compatible
    assert cfg.has_llm_credentials()
