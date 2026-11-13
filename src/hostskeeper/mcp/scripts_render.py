"""Render script body with {{param}} placeholders."""

from __future__ import annotations

import re
from typing import Mapping

from hostskeeper.mcp.errors import McpToolError
from hostskeeper.vault.models import Script

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def render_script(script: Script, params: Mapping[str, str] | None = None) -> str:
    values = dict(params or {})
    defined = {p.name: p for p in script.parameters}

    for name, meta in defined.items():
        if name not in values:
            if meta.default is not None:
                values[name] = meta.default
            elif meta.required:
                raise McpToolError("missing_param", f"missing required param: {name}")

    unknown_keys = sorted(set(values) - set(defined))
    # Extra params are allowed only if body references them? Spec: unknown placeholder error.
    # Extra unused params: ignore. Placeholders not in parameters list: unknown_placeholder.

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise McpToolError("unknown_placeholder", f"unknown placeholder: {key}")
        return values[key]

    try:
        return _PLACEHOLDER.sub(_replace, script.body)
    except McpToolError:
        raise
