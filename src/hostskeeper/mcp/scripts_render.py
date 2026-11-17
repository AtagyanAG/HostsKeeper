"""MCP-facing wrappers for saved-script analysis and rendering."""

from __future__ import annotations

from collections.abc import Mapping

from hostskeeper.mcp.errors import McpToolError
from hostskeeper.vault.models import Script
from hostskeeper.vault.script_render import (
    Placeholder,
    ScriptAnalysis,
    ScriptDiagnostic,
    ScriptRenderError,
    analyze_script,
    render_script as _render_saved_script,
)


def render_script(
    script: Script,
    params: Mapping[str, str] | None = None,
    *,
    use_user_values: bool = False,
) -> str:
    try:
        return _render_saved_script(
            script, params, use_user_values=use_user_values
        )
    except ScriptRenderError as exc:
        raise McpToolError(exc.code, str(exc)) from exc


__all__ = [
    "Placeholder",
    "ScriptAnalysis",
    "ScriptDiagnostic",
    "analyze_script",
    "render_script",
]
