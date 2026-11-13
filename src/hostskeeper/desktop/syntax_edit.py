"""Syntax highlighting and bracket matching for script editors."""

from __future__ import annotations

import re

from PySide6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit

_PAIRS = {
    "(": ")",
    "[": "]",
    "{": "}",
    ")": "(",
    "]": "[",
    "}": "{",
}
_OPENERS = frozenset("([{")
_CLOSERS = frozenset(")]}")


def _fmt(color: str, *, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    out = QTextCharFormat()
    out.setForeground(QColor(color))
    if bold:
        out.setFontWeight(QFont.Weight.Bold)
    if italic:
        out.setFontItalic(True)
    return out


class ShellScriptHighlighter(QSyntaxHighlighter):
    """Lightweight shell-ish highlighting + ``{{param}}`` placeholders."""

    _KEYWORDS = (
        "if",
        "then",
        "else",
        "elif",
        "fi",
        "for",
        "while",
        "until",
        "do",
        "done",
        "case",
        "esac",
        "function",
        "return",
        "exit",
        "export",
        "local",
        "readonly",
        "declare",
        "set",
        "unset",
        "shift",
        "echo",
        "printf",
        "read",
        "cd",
        "test",
        "true",
        "false",
        "sudo",
        "ssh",
        "awk",
        "sed",
        "grep",
        "cat",
        "curl",
        "wget",
        "systemctl",
        "docker",
        "kubectl",
    )

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self._rules: list[tuple[re.Pattern[str], QTextCharFormat]] = []
        kw = r"\b(?:" + "|".join(self._KEYWORDS) + r")\b"
        self._rules.append((re.compile(kw), _fmt("#0563A8", bold=True)))
        self._rules.append((re.compile(r"#.*$"), _fmt("#6A737D", italic=True)))
        self._rules.append((re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?"), _fmt("#0B7A3B")))
        self._rules.append(
            (re.compile(r"\{\{\s*[a-zA-Z_][a-zA-Z0-9_]*\s*\}\}"), _fmt("#B35900", bold=True))
        )
        self._string = _fmt("#0B7A3B")
        self._dq = re.compile(r'"([^"\\]|\\.)*"')
        self._sq = re.compile(r"'[^']*'")

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt API
        for pattern, fmt in self._rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)
        # Strings last so content inside quotes is not keyword-colored.
        for match in self._dq.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self._string)
        for match in self._sq.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self._string)


class JsonHighlighter(QSyntaxHighlighter):
    """JSON highlighting for script parameters editor."""

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self._key = _fmt("#0563A8", bold=True)
        self._string = _fmt("#0B7A3B")
        self._number = _fmt("#6F42C1")
        self._literal = _fmt("#B35900", bold=True)
        self._punct = _fmt("#586069")
        self._key_re = re.compile(r'"(?:\\.|[^"\\])*"\s*:')
        self._string_re = re.compile(r'"(?:\\.|[^"\\])*"')
        self._number_re = re.compile(r"-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b")
        self._literal_re = re.compile(r"\b(?:true|false|null)\b")
        self._punct_re = re.compile(r"[{}\[\],:]")

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt API
        for match in self._punct_re.finditer(text):
            self.setFormat(match.start(), 1, self._punct)
        for match in self._number_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self._number)
        for match in self._literal_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self._literal)
        for match in self._string_re.finditer(text):
            self.setFormat(match.start(), match.end() - match.start(), self._string)
        for match in self._key_re.finditer(text):
            # Color only the quoted key, not the colon.
            raw = match.group(0)
            end = raw.rfind('"')
            if end > 0:
                self.setFormat(match.start(), end + 1, self._key)


def _char_at(text: str, index: int) -> str | None:
    if 0 <= index < len(text):
        return text[index]
    return None


def _in_json_string(text: str, index: int) -> bool:
    """True if ``index`` lies inside a JSON double-quoted string."""
    i = 0
    in_str = False
    escape = False
    while i < len(text) and i <= index:
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        i += 1
    return in_str


def _find_match(text: str, pos: int, *, json_mode: bool) -> int | None:
    """Return index of matching bracket for opener/closer at ``pos``, or None."""
    ch = _char_at(text, pos)
    if ch is None or ch not in _PAIRS:
        return None
    if json_mode and _in_json_string(text, pos):
        return None
    match = _PAIRS[ch]
    if ch in _OPENERS:
        depth = 0
        i = pos
        while i < len(text):
            c = text[i]
            if json_mode and _in_json_string(text, i):
                i += 1
                continue
            if c == ch:
                depth += 1
            elif c == match:
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        return None
    depth = 0
    i = pos
    while i >= 0:
        c = text[i]
        if json_mode and _in_json_string(text, i):
            i -= 1
            continue
        if c == ch:
            depth += 1
        elif c == match:
            depth -= 1
            if depth == 0:
                return i
        i -= 1
    return None


class BracketMatcher:
    """Highlight matching ``()[]{}`` near the cursor on a ``QPlainTextEdit``."""

    def __init__(self, edit: QPlainTextEdit, *, json_mode: bool = False) -> None:
        self._edit = edit
        self._json_mode = json_mode
        self._fmt = QTextCharFormat()
        self._fmt.setBackground(QColor("#FFF3BF"))
        self._fmt.setForeground(QColor("#24292E"))
        edit.cursorPositionChanged.connect(self._update)
        edit.textChanged.connect(self._update)

    def _update(self) -> None:
        edit = self._edit
        text = edit.toPlainText()
        cursor = edit.textCursor()
        pos = cursor.position()
        candidates = [pos - 1, pos]
        match_pair: tuple[int, int] | None = None
        for cand in candidates:
            ch = _char_at(text, cand)
            if ch is None or ch not in _PAIRS:
                continue
            other = _find_match(text, cand, json_mode=self._json_mode)
            if other is not None:
                match_pair = (cand, other)
                break
        selections: list[QTextEdit.ExtraSelection] = []
        if match_pair is not None:
            for index in match_pair:
                sel = QTextEdit.ExtraSelection()
                sel.format = self._fmt
                c = QTextCursor(edit.document())
                c.setPosition(index)
                c.movePosition(
                    QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor
                )
                sel.cursor = c
                selections.append(sel)
        edit.setExtraSelections(selections)


def install_shell_editor(edit: QPlainTextEdit) -> tuple[ShellScriptHighlighter, BracketMatcher]:
    font = QFont("Consolas")
    if not font.exactMatch():
        font = QFont("Courier New")
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(10)
    edit.setFont(font)
    edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    highlighter = ShellScriptHighlighter(edit.document())
    matcher = BracketMatcher(edit, json_mode=False)
    return highlighter, matcher


def install_json_editor(edit: QPlainTextEdit) -> tuple[JsonHighlighter, BracketMatcher]:
    font = QFont("Consolas")
    if not font.exactMatch():
        font = QFont("Courier New")
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(10)
    edit.setFont(font)
    edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    highlighter = JsonHighlighter(edit.document())
    matcher = BracketMatcher(edit, json_mode=True)
    return highlighter, matcher
