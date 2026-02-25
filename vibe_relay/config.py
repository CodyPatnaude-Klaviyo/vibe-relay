"""Config loading and validation for vibe-relay.

Loads vibe-relay.config.json, validates required fields, and expands ~ in paths.
"""

import json
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    """Raised when configuration is invalid or missing required fields."""


REQUIRED_FIELDS = ["repo_path", "base_branch", "worktrees_path", "db_path"]

PATH_FIELDS = ["repo_path", "worktrees_path", "db_path"]

DEFAULTS: dict[str, Any] = {
    "max_parallel_agents": 3,
    "port_range": [4000, 4099],
    "default_model": "claude-sonnet-4-5",
}


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate vibe-relay.config.json.

    Args:
        config_path: Path to config file. Defaults to ./vibe-relay.config.json.

    Returns:
        Validated config dict with paths expanded and defaults applied.

    Raises:
        ConfigError: If file is missing, unreadable, or has invalid content.
    """
    if config_path is None:
        config_path = Path.cwd() / "vibe-relay.config.json"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    try:
        raw = config_path.read_text()
        config = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in {config_path}: {e}") from e

    _validate(config)
    _apply_defaults(config)
    _expand_paths(config)

    return config


def _validate(config: dict[str, Any]) -> None:
    """Validate required fields are present."""
    for field in REQUIRED_FIELDS:
        if field not in config:
            raise ConfigError(
                f"Missing required config field: '{field}'. "
                f"See vibe-relay.config.json.example for the expected format."
            )


def _apply_defaults(config: dict[str, Any]) -> None:
    """Apply default values for optional fields."""
    for key, default in DEFAULTS.items():
        if key not in config:
            config[key] = default


def _expand_paths(config: dict[str, Any]) -> None:
    """Expand ~ in path fields to the user's home directory."""
    for field in PATH_FIELDS:
        if field in config and isinstance(config[field], str):
            config[field] = str(Path(config[field]).expanduser())
