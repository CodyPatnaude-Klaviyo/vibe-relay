"""CLI entry point for vibe-relay.

Commands:
    vibe-relay init       — scaffold config and agent prompts in current directory
    vibe-relay serve      — start the API server (placeholder)
    vibe-relay mcp        — start the MCP server (stdio transport)
    vibe-relay run-agent  — launch a Claude agent for a specific task
"""

import json
import os
import shutil
from pathlib import Path

import click


DEFAULT_CONFIG = {
    "repo_path": str(Path.cwd()),
    "base_branch": "main",
    "worktrees_path": "~/.vibe-relay/worktrees",
    "db_path": "~/.vibe-relay/vibe-relay.db",
    "max_parallel_agents": 3,
    "port_range": [4000, 4099],
    "agents": {
        "planner": {
            "model": "claude-opus-4-5",
            "system_prompt_file": "agents/planner.md",
        },
        "coder": {
            "model": "claude-sonnet-4-5",
            "system_prompt_file": "agents/coder.md",
        },
        "reviewer": {
            "model": "claude-sonnet-4-5",
            "system_prompt_file": "agents/reviewer.md",
        },
        "orchestrator": {
            "model": "claude-opus-4-5",
            "system_prompt_file": "agents/orchestrator.md",
        },
    },
}

# Default agent prompt files bundled with the package
_PACKAGE_AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"


@click.group()
def main() -> None:
    """vibe-relay: multi-agent coding orchestration built on Claude Code."""


@main.command()
def init() -> None:
    """Create a starter vibe-relay.config.json and copy default agent prompts."""
    config_path = Path.cwd() / "vibe-relay.config.json"

    # Write config
    if config_path.exists():
        click.echo(f"Config already exists: {config_path}")
    else:
        config = DEFAULT_CONFIG.copy()
        config["repo_path"] = str(Path.cwd())
        config_path.write_text(json.dumps(config, indent=2) + "\n")
        click.echo(f"Created {config_path}")

    # Copy agent prompts
    agents_dir = Path.cwd() / "agents"
    agents_dir.mkdir(exist_ok=True)

    prompt_files = ["planner.md", "coder.md", "reviewer.md", "orchestrator.md"]
    for filename in prompt_files:
        dest = agents_dir / filename
        if dest.exists():
            click.echo(f"  Agent prompt already exists: {dest}")
            continue

        source = _PACKAGE_AGENTS_DIR / filename
        if source.exists():
            shutil.copy2(source, dest)
            click.echo(f"  Copied {filename} -> {dest}")
        else:
            # Create a minimal placeholder if source doesn't exist
            dest.write_text(
                f"# {filename.replace('.md', '').title()} Agent\n\nSystem prompt not yet configured.\n"
            )
            click.echo(f"  Created placeholder {dest}")

    click.echo("Done. Edit vibe-relay.config.json to set your repo_path.")


@main.command()
def serve() -> None:
    """Start the vibe-relay API server."""
    click.echo("Server not yet implemented.")


@main.command()
@click.option(
    "--task-id", default=None, help="Scope context-sensitive tools to this task"
)
def mcp(task_id: str | None) -> None:
    """Start the vibe-relay MCP server (stdio transport)."""
    from vibe_relay.config import ConfigError, load_config

    # Resolve db_path from env, config, or default
    db_path = os.environ.get("VIBE_RELAY_DB")
    if db_path is None:
        try:
            config = load_config()
            db_path = config["db_path"]
        except ConfigError:
            db_path = str(Path("~/.vibe-relay/vibe-relay.db").expanduser())

    from vibe_relay.mcp.server import run_server

    run_server(task_id=task_id, db_path=db_path)


@main.command("run-agent")
@click.option("--task-id", required=True, help="UUID of the task to run an agent for")
def run_agent_cmd(task_id: str) -> None:
    """Launch a Claude agent for a specific task."""
    import sys

    from vibe_relay.config import ConfigError, load_config

    try:
        config = load_config()
    except ConfigError as e:
        click.echo(f"Config error: {e}", err=True)
        sys.exit(1)

    from runner.launcher import LaunchError, launch_agent
    from runner.worktree import WorktreeError

    try:
        result = launch_agent(task_id, config)
    except (LaunchError, WorktreeError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    click.echo(
        f"Agent completed. session_id={result.session_id} exit_code={result.exit_code}"
    )
    if result.error:
        click.echo(f"Error: {result.error}", err=True)

    sys.exit(result.exit_code)
