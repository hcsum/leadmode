from __future__ import annotations

import json
import hashlib
import shlex
import sys
from importlib.resources import files
from pathlib import Path

from .db import initialize

EVENTS = ("SessionStart", "SessionEnd", "PostToolUse", "UserPromptSubmit", "Stop")
PERMISSIONS = ("Bash(agent-ledger *)", "Bash(agent-ledger:*)")
HOOK_COMMAND = '"$CLAUDE_PROJECT_DIR/.agent-ledger/hook"'


def hook_entry(event: str) -> dict:
    return {
        "hooks": [
            {
                "type": "command",
                "command": HOOK_COMMAND,
                "timeout": 15,
                "statusMessage": f"agent-ledger: {event}",
            }
        ]
    }


def merge_settings(settings: dict) -> dict:
    hooks = settings.setdefault("hooks", {})
    for event in EVENTS:
        entries = hooks.setdefault(event, [])
        for entry in entries:
            for hook in entry.get("hooks", []):
                if hook.get("command") == "agent-ledger-hook":
                    hook["command"] = HOOK_COMMAND
        if not any(
            hook.get("command") == HOOK_COMMAND
            for entry in entries
            for hook in entry.get("hooks", [])
        ):
            entries.append(hook_entry(event))
    permissions = settings.setdefault("permissions", {})
    allowed = permissions.setdefault("allow", [])
    for permission in PERMISSIONS:
        if permission not in allowed:
            allowed.append(permission)
    return settings


def install(root: Path) -> list[Path]:
    claude = root / ".claude"
    state_dir = root / ".agent-ledger"
    metadata_path = state_dir / "install.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    old_hashes = metadata.get("skill_hashes", {}) if isinstance(metadata, dict) else {}
    source = files("agent_ledger").joinpath("assets", "skills")
    skill_data = {role: source.joinpath(role, "SKILL.md").read_bytes() for role in ("planner", "consult", "worker")}

    # A recorded hash proves the file is an untouched copy from an earlier install.
    for role, data in skill_data.items():
        target = claude / "skills" / role / "SKILL.md"
        if not target.exists():
            continue
        current_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        source_hash = hashlib.sha256(data).hexdigest()
        if current_hash not in {source_hash, old_hashes.get(role)}:
            raise ValueError(
                f"Refusing to overwrite existing skill: {target}. "
                "Move or rename it, then run `agent-ledger install` again."
            )

    initialize(root)
    claude.mkdir(parents=True, exist_ok=True)
    settings_path = claude / "settings.json"
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            raise ValueError(f"Expected a JSON object in {settings_path}")
    else:
        settings = {}
    merge_settings(settings)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    gitignore = root / ".gitignore"
    ignore_text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if ".agent-ledger/" not in {line.strip() for line in ignore_text.splitlines()}:
        separator = "" if not ignore_text or ignore_text.endswith("\n") else "\n"
        gitignore.write_text(ignore_text + separator + ".agent-ledger/\n", encoding="utf-8")

    written = [settings_path, gitignore]
    skill_hashes = {}
    for role, data in skill_data.items():
        destination = claude / "skills" / role
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / "SKILL.md"
        target.write_bytes(data)
        skill_hashes[role] = hashlib.sha256(data).hexdigest()
        written.append(target)

    hook_path = state_dir / "hook"
    hook_path.write_text(
        "#!/bin/sh\nexec " + shlex.quote(sys.executable) + " -m agent_ledger.hooks \"$@\"\n",
        encoding="utf-8",
    )
    hook_path.chmod(0o700)
    metadata_path.write_text(json.dumps({"skill_hashes": skill_hashes}, indent=2) + "\n", encoding="utf-8")
    return written
