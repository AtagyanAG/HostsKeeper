"""Unit tests for script editor bracket matching helpers."""

from __future__ import annotations

from hostskeeper.desktop.syntax_edit import _find_match, _in_json_string


def test_find_match_simple_brackets() -> None:
    text = "echo $(foo [bar])"
    # '(' at index of first '('
    open_paren = text.index("(")
    assert _find_match(text, open_paren, json_mode=False) == text.rindex(")")
    assert _find_match(text, text.rindex(")"), json_mode=False) == open_paren
    open_bracket = text.index("[")
    assert _find_match(text, open_bracket, json_mode=False) == text.index("]")


def test_find_match_json_skips_brackets_in_strings() -> None:
    text = '{"a": "[not]", "b": [1, 2]}'
    # Real array bracket after "b":
    real_open = text.rindex("[")
    real_close = text.rindex("]")
    assert _find_match(text, real_open, json_mode=True) == real_close
    # Bracket characters inside the string value should not match as structure.
    inside = text.index("[not]")
    assert _in_json_string(text, inside)
    assert _find_match(text, inside, json_mode=True) is None


def test_in_json_string_escape() -> None:
    text = r'"say \"hi\"" ,'
    # Position of the letter h inside escaped quotes region still in string.
    h_pos = text.index("h")
    assert _in_json_string(text, h_pos)
    comma = text.index(",")
    assert not _in_json_string(text, comma)
