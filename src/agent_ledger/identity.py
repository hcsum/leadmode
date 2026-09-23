from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from dataclasses import dataclass

from .db import connect


def tag_for(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:8]


def parent_pid(pid: int) -> int | None:
    try:
        result = subprocess.run(
            ["ps", "-o", "ppid=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        value = result.stdout.strip()
        return int(value) if value.isdigit() else None
    except (OSError, subprocess.SubprocessError):
        return None


def ancestor_pids(start: int | None = None, limit: int = 20) -> list[int]:
    pid = start or os.getppid()
    result: list[int] = []
    for _ in range(limit):
        if pid <= 1 or pid in result:
            break
        result.append(pid)
        next_pid = parent_pid(pid)
        if next_pid is None:
            break
        pid = next_pid
    return result


def process_command(pid: int) -> str:
    try:
        result = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def hook_host_pid() -> int:
    """Return the stable ancestor that launched a hook, without using external registries."""
    pids = ancestor_pids()
    for pid in pids:
        command = process_command(pid).lower()
        if any("claude" in Path(part).name for part in command.split()[:3]):
            return pid
    return pids[0] if pids else os.getppid()


@dataclass(frozen=True)
class Identity:
    tag: str
    role: str
    is_user: bool

    @property
    def label(self) -> str:
        return "user" if self.is_user else f"{self.role or 'unregistered'} [{self.tag}]"


def current_identity(root) -> Identity:
    override = os.environ.get("AGENT_LEDGER_AS")
    with connect(root) as con:
        if override:
            row = con.execute(
                "SELECT tag,role FROM sessions WHERE tag=? AND ended_at IS NULL", (override,)
            ).fetchone()
            if not row:
                raise PermissionError(f"Unknown or ended session: {override}")
            return Identity(row["tag"], row["role"], False)
        pids = ancestor_pids()
        if pids:
            placeholders = ",".join("?" for _ in pids)
            rows = con.execute(
                f"SELECT tag,role,pid,started_at FROM sessions WHERE ended_at IS NULL AND pid IN ({placeholders}) "
                "ORDER BY started_at DESC",
                pids,
            ).fetchall()
            if rows:
                row = rows[0]
                return Identity(row["tag"], row["role"], False)
    return Identity("user", "user", True)
