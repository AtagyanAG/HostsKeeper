"""Analyze and render script bodies with {{param}} placeholders."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from hostskeeper.mcp.errors import McpToolError
from hostskeeper.vault.models import Script, ScriptParameter

_NAME = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")
_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


@dataclass(frozen=True)
class Placeholder:
    name: str
    position: int

    def to_dict(self) -> dict[str, str | int]:
        return {"name": self.name, "position": self.position}


@dataclass(frozen=True)
class ScriptDiagnostic:
    code: str
    name: str | None = None
    position: int | None = None
    parameter_index: int | None = None

    def to_dict(self) -> dict[str, str | int]:
        result: dict[str, str | int] = {"code": self.code}
        if self.name is not None:
            result["name"] = self.name
        if self.position is not None:
            result["position"] = self.position
        if self.parameter_index is not None:
            result["parameter_index"] = self.parameter_index
        return result


@dataclass(frozen=True)
class ScriptAnalysis:
    placeholders: tuple[Placeholder, ...]
    errors: tuple[ScriptDiagnostic, ...]
    warnings: tuple[ScriptDiagnostic, ...]
    missing_parameters: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def ready_to_run(self) -> bool:
        return self.valid and not self.missing_parameters

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "ready_to_run": self.ready_to_run,
            "placeholders": [item.to_dict() for item in self.placeholders],
            "errors": [item.to_dict() for item in self.errors],
            "warnings": [item.to_dict() for item in self.warnings],
            "missing_parameters": list(self.missing_parameters),
        }


def analyze_script(
    body: str,
    parameters: Sequence[ScriptParameter],
    params: Mapping[str, str] | None = None,
    *,
    use_user_values: bool = False,
) -> ScriptAnalysis:
    """Inspect placeholder declarations without returning script or value text."""
    placeholders: list[Placeholder] = []
    errors: list[ScriptDiagnostic] = []
    warnings: list[ScriptDiagnostic] = []
    cursor = 0

    while cursor < len(body):
        opening = body.find("{{", cursor)
        closing = body.find("}}", cursor)
        if opening < 0:
            if closing >= 0:
                errors.append(
                    ScriptDiagnostic("malformed_placeholder", position=closing)
                )
            break
        if 0 <= closing < opening:
            errors.append(
                ScriptDiagnostic("malformed_placeholder", position=closing)
            )
            cursor = closing + 2
            continue

        closing = body.find("}}", opening + 2)
        if closing < 0:
            errors.append(
                ScriptDiagnostic("malformed_placeholder", position=opening)
            )
            break

        token = body[opening : closing + 2]
        match = _PLACEHOLDER.fullmatch(token)
        if match is None:
            errors.append(
                ScriptDiagnostic("malformed_placeholder", position=opening)
            )
        else:
            placeholders.append(Placeholder(match.group(1), opening))
        cursor = closing + 2

    definitions: dict[str, ScriptParameter] = {}
    for index, parameter in enumerate(parameters):
        if _NAME.fullmatch(parameter.name) is None:
            errors.append(
                ScriptDiagnostic(
                    "invalid_parameter_name", parameter_index=index
                )
            )
            continue
        if parameter.name in definitions:
            errors.append(
                ScriptDiagnostic(
                    "duplicate_parameter", parameter_index=index
                )
            )
            continue
        definitions[parameter.name] = parameter

    used_names = {item.name for item in placeholders}
    for item in placeholders:
        if item.name not in definitions:
            errors.append(
                ScriptDiagnostic(
                    "unknown_placeholder",
                    name=item.name,
                    position=item.position,
                )
            )

    for name in definitions:
        if name not in used_names:
            warnings.append(ScriptDiagnostic("unused_parameter", name=name))

    supplied = params or {}
    missing: list[str] = []
    for name in dict.fromkeys(item.name for item in placeholders):
        parameter = definitions.get(name)
        if parameter is None:
            continue
        if use_user_values:
            available = parameter.user_value is not None
        else:
            available = name in supplied or parameter.default is not None
        if not available:
            missing.append(name)

    return ScriptAnalysis(
        placeholders=tuple(placeholders),
        errors=tuple(errors),
        warnings=tuple(warnings),
        missing_parameters=tuple(missing),
    )


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
    analysis = analyze_script(
        script.body,
        script.parameters,
        params,
        use_user_values=use_user_values,
    )
    if analysis.missing_parameters:
        name = analysis.missing_parameters[0]
        if use_user_values:
            raise McpToolError(
                "missing_param", f"missing user_value for param: {name}"
            )
        raise McpToolError("missing_param", f"missing value for param: {name}")
    if analysis.errors:
        issue = analysis.errors[0]
        if issue.code == "unknown_placeholder":
            raise McpToolError(
                "unknown_placeholder",
                f"unknown placeholder: {issue.name} at position {issue.position}",
            )
        if issue.code == "malformed_placeholder":
            raise McpToolError(
                "unknown_placeholder",
                f"malformed placeholder at position {issue.position}",
            )
        raise McpToolError("invalid_args", issue.code)

    defined = {parameter.name: parameter for parameter in script.parameters}
    supplied = params or {}

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if use_user_values:
            return defined[key].user_value or ""
        if key in supplied:
            return supplied[key]
        return defined[key].default or ""

    return _PLACEHOLDER.sub(_replace, script.body)
