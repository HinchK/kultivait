"""Effort-mapping policy: judge signals to per-CLI effort.

Resolves abstract effort from preprocessor complexity and task type,
projecting the canonical level (fast, balanced, deep) onto per-CLI flags
and model overrides.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EffortPlan:
    canonical: str
    cli_flags: list[str] = field(default_factory=list)
    model_override: str | None = None


DEFAULT_EFFORT_OVERRIDES: dict = {}

_CLI_EFFORT_MAP = {
    "fast": "low",
    "balanced": "medium",
    "deep": "high",
}


def load_effort_overrides(config: dict | None) -> dict:
    """Read an optional [effort] table from a parsed configuration dictionary."""
    if not config or not isinstance(config, dict):
        return {}
    effort_table = config.get("effort")
    if isinstance(effort_table, dict):
        return dict(effort_table)
    return {}


def resolve_effort(
    complexity: int,
    task_type: str,
    target_cli: str,
    overrides: dict | None = None,
) -> EffortPlan:
    """Resolve an EffortPlan from complexity, task type, and target CLI."""
    if isinstance(complexity, int) and 1 <= complexity <= 9 and isinstance(task_type, str):
        if 1 <= complexity <= 3:
            base = "fast"
        elif 4 <= complexity <= 6:
            base = "balanced"
        else:
            base = "deep"

        if task_type in ("simple_edit", "docs_lookup", "underspecified"):
            canonical = "balanced" if base == "deep" else base
        elif task_type in ("architecture", "compound"):
            if base == "fast":
                canonical = "balanced"
            elif base == "balanced":
                canonical = "deep"
            else:
                canonical = "deep"
        elif task_type == "debugging":
            canonical = base
        else:
            canonical = "balanced"
    else:
        canonical = "balanced"

    if overrides and isinstance(overrides, dict):
        if target_cli in overrides and isinstance(overrides[target_cli], str):
            canonical = overrides[target_cli]
        elif "default" in overrides and isinstance(overrides["default"], str):
            canonical = overrides["default"]

    cli_level = _CLI_EFFORT_MAP.get(canonical, "medium")

    if target_cli in ("claude", "agy"):
        cli_flags = ["--effort", cli_level]
        model_override = None
    elif target_cli == "codex":
        cli_flags = ["-c", f"model_reasoning_effort={cli_level}"]
        model_override = None
    elif target_cli == "opencode":
        cli_flags = ["--variant", cli_level]
        model_override = None
    elif target_cli == "gemini":
        cli_flags = []
        model_override = canonical
    else:
        cli_flags = []
        model_override = None

    return EffortPlan(
        canonical=canonical,
        cli_flags=cli_flags,
        model_override=model_override,
    )
