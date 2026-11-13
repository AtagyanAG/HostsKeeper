"""Render script body with {{param}} placeholders."""

from __future__ import annotations

import re
from typing import Mapping

from hostskeeper.mcp.errors import McpToolError
from hostskeeper.vault.models import Script

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def render_script(
    script: Script,
    params: Mapping[str, str] | None = None,
    *,
    use_user_values: bool = False,
) -> str:
    """Substitute ``{{name}}`` placeholders.

    When ``use_user_values`` is True (human Run dialog), values come only from
    ``ScriptParameter.user_value`` — not from ``params`` or ``default``.
    MCP ``scripts_run`` always uses ``use_user_values=False``.
    """
    defined = {p.name: p for p in script.parameters}

    if use_user_values:
        values: dict[str, str] = {}
        for name, meta in defined.items():
            if meta.user_value is not None:
                values[name] = meta.user_value
    else:
        values = dict(params or {})
        for name, meta in defined.items():
            if name not in values:
                if meta.default is not None:
                    values[name] = meta.default
                elif meta.required:
                    raise McpToolError(
                        "missing_param", f"missing required param: {name}"
                    )

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            if use_user_values:
                raise McpToolError(
                    "missing_param", f"missing user_value for param: {key}"
                )
            raise McpToolError("unknown_placeholder", f"unknown placeholder: {key}")
        return values[key]

    try:
        return _PLACEHOLDER.sub(_replace, script.body)
    except McpToolError:
        raise
