from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from .db import connect, db_path, initialize, now, project_root
from .identity import hook_host_pid, tag_for

LEDGER_WRITE = re.compile(
    r"\bagent-ledger\s+(?:add|claim|release|set|close|reopen|note|decide|plan|tell|register)\b"
)
WORK_COMMAND = re.compile(r"\bgit\s+(?:commit|push)\b")


def payload() -> dict:
    try:
        value = json.load(sys.stdin)
        return value if isinstance(value, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def emit_context(event: str, text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))


def session_start(root: Path, data: dict) -> None:
    session_id = str(data.get("session_id") or "")
    if not session_id:
        return
    initialize(root)
    tag = tag_for(session_id)
    pid = hook_host_pid()
    adopted: list[str] = []
    with connect(root) as con:
        old_rows = con.execute(
            "SELECT tag,role FROM sessions WHERE pid=? AND ended_at IS NULL AND tag!=? ORDER BY started_at",
            (pid, tag),
        ).fetchall()
        role = ""
        for old in old_rows:
            role = role or old["role"]
            con.execute("UPDATE cards SET owner=? WHERE owner=?", (tag, old["tag"]))
            con.execute("UPDATE inbox SET to_tag=? WHERE to_tag=? AND read_at IS NULL", (tag, old["tag"]))
            con.execute("UPDATE sessions SET ended_at=? WHERE tag=?", (now(), old["tag"]))
            adopted.append(old["tag"])
        con.execute(
            "INSERT INTO sessions(tag,session_id,role,pid,started_at,ended_at) VALUES(?,?,?,?,?,NULL) "
            "ON CONFLICT(tag) DO UPDATE SET session_id=excluded.session_id,pid=excluded.pid,ended_at=NULL",
            (tag, session_id, role, pid, now()),
        )
    text = (
        f"[agent-ledger] Session tag: {tag}. Register a role with "
        "`agent-ledger register planner|consult|worker`, then use `agent-ledger show`."
    )
    if adopted:
        text += f" Adopted role, cards, and unread inbox from {', '.join(adopted)} after /clear."
    emit_context("SessionStart", text)


def session_end(root: Path, data: dict) -> None:
    if str(data.get("reason") or "") == "clear":
        return
    session_id = str(data.get("session_id") or "")
    if not session_id or not db_path(root).exists():
        return
    tag = tag_for(session_id)
    with connect(root) as con:
        con.execute("UPDATE cards SET owner=NULL,updated_at=? WHERE owner=?", (now(), tag))
        con.execute("UPDATE sessions SET ended_at=? WHERE tag=?", (now(), tag))


def inject_inbox(root: Path, data: dict) -> None:
    if data.get("agent_id"):
        return
    session_id = str(data.get("session_id") or "")
    if not session_id or not db_path(root).exists():
        return
    tag = tag_for(session_id)
    with connect(root) as con:
        tracked = con.execute("SELECT 1 FROM sessions WHERE tag=? AND ended_at IS NULL", (tag,)).fetchone()
        if not tracked:
            return
        rows = con.execute(
            "SELECT id,from_tag,body FROM inbox WHERE to_tag=? AND read_at IS NULL ORDER BY id", (tag,)
        ).fetchall()
        if not rows:
            return
        con.execute("UPDATE inbox SET read_at=? WHERE to_tag=? AND read_at IS NULL", (now(), tag))
    text = "[agent-ledger] Inbox:\n" + "\n".join(
        f"- #{row['id']} from {row['from_tag']}: {row['body']}" for row in rows
    )
    emit_context(str(data.get("hook_event_name") or "PostToolUse"), text)


def current_turn(messages: list[dict]) -> list[dict]:
    start = 0
    for index, message in enumerate(messages):
        if message.get("type") != "user" or message.get("isMeta"):
            continue
        content = (message.get("message") or {}).get("content")
        if isinstance(content, str):
            start = index
        elif isinstance(content, list) and not any(
            isinstance(block, dict) and block.get("type") == "tool_result" for block in content
        ):
            start = index
    return messages[start:]


def tool_actions(messages: list[dict]) -> tuple[list[str], bool, bool]:
    actions: list[str] = []
    did_work = False
    wrote_ledger = False
    for message in messages:
        if message.get("type") != "assistant":
            continue
        for block in (message.get("message") or {}).get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = str(block.get("name") or "")
            values = block.get("input") or {}
            command = str(values.get("command") or "")
            path = str(values.get("file_path") or values.get("path") or "")
            if LEDGER_WRITE.search(command):
                wrote_ledger = True
                actions.append("ledger write")
            elif name.rsplit(".", 1)[-1] in {"Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"}:
                did_work = True
                actions.append(f"{name} {Path(path).name if path else 'files'}")
            elif name == "Bash" and WORK_COMMAND.search(command):
                did_work = True
                actions.append(command.strip().splitlines()[0][:70])
            elif name not in {"Read", "Glob", "Grep", "WebFetch", "Skill"}:
                actions.append(name)
    return actions, did_work, wrote_ledger


def stop(root: Path, data: dict) -> None:
    if data.get("agent_id"):
        return
    session_id = str(data.get("session_id") or "")
    transcript = data.get("transcript_path")
    if not session_id or not transcript or not db_path(root).exists():
        return
    messages: list[dict] = []
    try:
        with open(transcript, encoding="utf-8") as source:
            for line in source:
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return
    tag = tag_for(session_id)
    with connect(root) as con:
        row = con.execute("SELECT role FROM sessions WHERE tag=? AND ended_at IS NULL", (tag,)).fetchone()
    role = row["role"] if row else ""
    actions, did_work, wrote_ledger = tool_actions(current_turn(messages))
    summary = " | ".join(dict.fromkeys(actions[:10])) if actions else "none"
    if role in {"planner", "consult"}:
        print(json.dumps({"systemMessage": f"[agent-ledger action receipt] {summary}"}))
    elif role == "worker" and did_work and not wrote_ledger:
        if data.get("stop_hook_active"):
            print(json.dumps({"systemMessage": "[agent-ledger] Close-out is still missing; allowing stop to avoid a loop."}))
        else:
            print(json.dumps({
                "decision": "block",
                "reason": "This worker edited files or committed without a ledger write. Update the claimed card with "
                          "`agent-ledger set <card> progress \"...\"`, add a note, then close or release it.",
            }))


def main() -> int:
    data = payload()
    event = str(data.get("hook_event_name") or "")
    root = project_root(os.environ.get("CLAUDE_PROJECT_DIR"))
    try:
        if event == "SessionStart":
            session_start(root, data)
        elif event == "SessionEnd":
            session_end(root, data)
        elif event in {"PostToolUse", "UserPromptSubmit"}:
            inject_inbox(root, data)
        elif event == "Stop":
            stop(root, data)
    except Exception as exc:  # Hooks must not break Claude Code.
        print(f"[agent-ledger hook error] {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
