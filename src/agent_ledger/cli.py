from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .core import Ledger, LedgerError
from .db import LANES, connect, initialize, now, project_root, today
from .identity import current_identity
from .install import install as install_project


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent-ledger", description="Coordinate human and agent work locally.")
    p.add_argument("--project", type=Path, help="Target project (defaults to the nearest project root).")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create .agent-ledger/ledger.sqlite.")
    sub.add_parser("install", help="Install Claude Code hooks and role skills.")

    register = sub.add_parser("register", help="Register this tracked Claude session's role.")
    register.add_argument("role", choices=("planner", "consult", "worker"))
    register.add_argument("--tag", help="Session tag to register (terminal user only).")
    sub.add_parser("who", help="List tracked sessions.")

    add = sub.add_parser("add", help="Add a card (planner or terminal user).")
    add.add_argument("id")
    add.add_argument("title")
    add.add_argument("--lane", default="Backlog")

    claim = sub.add_parser("claim", help="Claim a card as a worker.")
    claim.add_argument("id")
    release = sub.add_parser("release", help="Release a card or end this session.")
    release.add_argument("id", nargs="?")
    release.add_argument("--end", action="store_true")

    set_cmd = sub.add_parser("set", help="Set a card field.")
    set_cmd.add_argument("id")
    set_cmd.add_argument("field", choices=("title", "lane", "status", "progress"))
    set_cmd.add_argument("value")
    for name in ("close", "reopen"):
        cmd = sub.add_parser(name, help=f"{name.title()} a card.")
        cmd.add_argument("id")

    show = sub.add_parser("show", help="Show cards or one card.")
    show.add_argument("id", nargs="?")
    show.add_argument("--log", action="store_true")

    note = sub.add_parser("note", help="Add a note; use '-' for a ledger-wide note.")
    note.add_argument("card")
    note.add_argument("body")

    decide = sub.add_parser("decide", help="Manage decisions.")
    decide_sub = decide.add_subparsers(dest="decide_command", required=True)
    decide_add = decide_sub.add_parser("add")
    decide_add.add_argument("body")
    decide_add.add_argument("--card")
    decide_list = decide_sub.add_parser("list")
    decide_list.add_argument("--all", action="store_true")
    decide_check = decide_sub.add_parser("check")
    decide_check.add_argument("id", type=int)
    decide_close = decide_sub.add_parser("close")
    decide_close.add_argument("id", type=int)
    decide_close.add_argument("resolution")

    plan = sub.add_parser("plan", help="Manage today's plan.")
    plan_sub = plan.add_subparsers(dest="plan_command", required=True)
    plan_add = plan_sub.add_parser("add")
    plan_add.add_argument("ids", nargs="+")
    plan_remove = plan_sub.add_parser("remove")
    plan_remove.add_argument("ids", nargs="+")
    plan_sub.add_parser("show")

    tell = sub.add_parser("tell", help="Send a message to an active role or session tag.")
    tell.add_argument("target")
    tell.add_argument("body")
    inbox = sub.add_parser("inbox", help="Read and mark inbox messages delivered.")
    inbox.add_argument("--peek", action="store_true")
    inbox.add_argument("--to", help="Target tag (terminal user only).")
    log = sub.add_parser("log", help="Show recent activity.")
    log.add_argument("--limit", type=int, default=30)
    watch = sub.add_parser("watch", help="Wait for new ledger activity.")
    watch.add_argument("--interval", type=float, default=2.0)
    watch.add_argument("--once", action="store_true")
    sub.add_parser("demo", help="Seed a small dashboard demo.")
    return p


def _root(args) -> Path:
    return project_root(args.project) if args.project else project_root()


def _identity(root: Path):
    try:
        return current_identity(root)
    except PermissionError as exc:
        raise LedgerError(str(exc)) from exc


def register(root: Path, args) -> None:
    actor = _identity(root)
    tag = args.tag or actor.tag
    if actor.is_user:
        if not args.tag:
            raise LedgerError("A terminal user must provide --tag when registering another session.")
    elif args.tag and args.tag != actor.tag:
        raise LedgerError("Only the terminal user may register another session.")
    with connect(root) as con:
        row = con.execute("SELECT * FROM sessions WHERE tag=? AND ended_at IS NULL", (tag,)).fetchone()
        if not row:
            raise LedgerError(f"Active tracked session not found: {tag}")
        con.execute("UPDATE sessions SET role=? WHERE tag=?", (args.role, tag))
    print(f"Registered {tag} as {args.role}.")


def show_cards(con, card_id: str | None, include_log: bool) -> None:
    if card_id:
        row = con.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
        if not row:
            raise LedgerError(f"Card not found: {card_id}")
        print(f"{row['id']}  {row['title']}")
        print(f"Lane: {row['lane']}  Status: {row['status']}  Owner: {row['owner'] or '-'}")
        print(f"Progress: {row['progress'] or '-'}")
        decisions = con.execute(
            "SELECT id,body FROM decisions WHERE card_id=? AND closed_at IS NULL ORDER BY id", (card_id,)
        ).fetchall()
        for decision in decisions:
            print(f"Decision #{decision['id']}: {decision['body']}")
        for note in con.execute(
            "SELECT created_at,session,body FROM notes WHERE card_id=? ORDER BY id", (card_id,)
        ):
            print(f"Note {note['created_at']} {note['session']}: {note['body']}")
        if include_log:
            for item in con.execute(
                "SELECT created_at,session,field,new_value FROM changelog "
                "WHERE table_name='cards' AND row_id=? ORDER BY id", (card_id,)
            ):
                print(f"Log {item['created_at']} {item['session']} {item['field']}: {item['new_value'] or '-'}")
        return
    rows = con.execute(
        "SELECT * FROM cards ORDER BY closed_at IS NOT NULL,lane,updated_at DESC,id"
    ).fetchall()
    if not rows:
        print("No cards.")
        return
    for row in rows:
        mark = "x" if row["closed_at"] else " "
        print(f"[{mark}] {row['id']:<14} {row['lane']:<8} {row['status']:<10} "
              f"owner={row['owner'] or '-':<8} {row['title']}")


def decisions(con, args, ledger: Ledger) -> None:
    if args.decide_command == "add":
        decision_id = ledger.add_decision(args.body, args.card)
        print(f"Opened decision #{decision_id}.")
    elif args.decide_command == "check":
        ledger.check_decision(args.id)
        print(f"Checked decision #{args.id}.")
    elif args.decide_command == "close":
        ledger.close_decision(args.id, args.resolution)
        print(f"Closed decision #{args.id}.")
    else:
        where = "" if args.all else "WHERE closed_at IS NULL"
        rows = con.execute(f"SELECT * FROM decisions {where} ORDER BY id").fetchall()
        if not rows:
            print("No decisions.")
        for row in rows:
            state = "closed" if row["closed_at"] else "open"
            print(f"#{row['id']} [{state}] card={row['card_id'] or '-'} {row['body']}")


def day_plan(con, args, ledger: Ledger) -> None:
    day = today()
    if args.plan_command == "add":
        ledger.require_role("planner")
        for card_id in args.ids:
            ledger.card(card_id)
            con.execute(
                "INSERT INTO day_plan(day,card_id,added_by,added_at,removed_at) VALUES(?,?,?,?,NULL) "
                "ON CONFLICT(day,card_id) DO UPDATE SET added_by=excluded.added_by,added_at=excluded.added_at,removed_at=NULL",
                (day, card_id, ledger.actor.tag, now()),
            )
            print(f"Added {card_id} to today's plan.")
    elif args.plan_command == "remove":
        ledger.require_role("planner")
        for card_id in args.ids:
            con.execute(
                "UPDATE day_plan SET removed_at=? WHERE day=? AND card_id=? AND removed_at IS NULL",
                (now(), day, card_id),
            )
            print(f"Removed {card_id} from today's plan.")
    else:
        rows = con.execute(
            "SELECT c.id,c.title,c.status FROM day_plan p JOIN cards c ON c.id=p.card_id "
            "WHERE p.day=? AND p.removed_at IS NULL ORDER BY p.added_at", (day,)
        ).fetchall()
        if not rows:
            print("Today's plan is empty.")
        for row in rows:
            print(f"{row['id']} [{row['status']}] {row['title']}")


def read_inbox(con, target: str, peek: bool) -> int:
    rows = con.execute(
        "SELECT * FROM inbox WHERE to_tag=? AND read_at IS NULL ORDER BY id", (target,)
    ).fetchall()
    if not rows:
        print("Inbox is empty.")
        return 0
    for row in rows:
        print(f"#{row['id']} {row['created_at']} from {row['from_tag']}: {row['body']}")
    if not peek:
        con.execute("UPDATE inbox SET read_at=? WHERE to_tag=? AND read_at IS NULL", (now(), target))
    return len(rows)


def seed_demo(con, ledger: Ledger) -> None:
    ledger.require_role("planner")
    samples = (
        ("DEMO-1", "Define the first public milestone", "Ready", "ready"),
        ("DEMO-2", "Implement the local integration", "Doing", "in progress"),
        ("DEMO-3", "Review the release checklist", "Blocked", "waiting for decision"),
    )
    for card_id, title, lane, status in samples:
        if not con.execute("SELECT 1 FROM cards WHERE id=?", (card_id,)).fetchone():
            ledger.add_card(card_id, title, lane)
            con.execute("UPDATE cards SET status=? WHERE id=?", (status, card_id))
    if not con.execute("SELECT 1 FROM decisions WHERE card_id='DEMO-3' AND closed_at IS NULL").fetchone():
        ledger.add_decision("Choose the release channel for the first preview.", "DEMO-3")
    ledger.add_note("DEMO-2", "Demo data is safe to remove at any time.")
    print("Seeded DEMO-1, DEMO-2, and DEMO-3.")


def dispatch(args) -> None:
    root = _root(args)
    if args.command == "init":
        print(f"Initialized {initialize(root)}")
        return
    if args.command == "install":
        paths = install_project(root)
        print(f"Installed agent-ledger in {root}")
        for path in paths:
            print(f"  {path.relative_to(root)}")
        return
    initialize(root)
    if args.command == "register":
        register(root, args)
        return
    actor = _identity(root)
    with connect(root) as con:
        ledger = Ledger(con, actor)
        command = args.command
        if command == "who":
            rows = con.execute("SELECT * FROM sessions ORDER BY started_at DESC").fetchall()
            active = [row for row in rows if not row["ended_at"]]
            if not active:
                print("No active tracked sessions.")
            for row in active:
                print(f"{row['tag']} role={row['role'] or 'unregistered'} pid={row['pid'] or '-'} started={row['started_at']}")
        elif command == "add":
            ledger.add_card(args.id, args.title, args.lane)
            print(f"Added {args.id}.")
        elif command == "claim":
            ledger.claim(args.id)
            print(f"Claimed {args.id}.")
        elif command == "release":
            if args.id:
                ledger.release(args.id)
                print(f"Released {args.id}.")
            if args.end:
                if actor.is_user:
                    raise LedgerError("The terminal user is not a tracked session.")
                owned = con.execute("SELECT id FROM cards WHERE owner=?", (actor.tag,)).fetchall()
                for row in owned:
                    ledger.release(row["id"])
                con.execute("UPDATE sessions SET ended_at=? WHERE tag=?", (now(), actor.tag))
                print(f"Ended session {actor.tag}.")
            if not args.id and not args.end:
                raise LedgerError("Provide a card ID or --end.")
        elif command == "set":
            ledger.set_field(args.id, args.field, args.value)
            print(f"Updated {args.id} {args.field}.")
        elif command == "close":
            ledger.close(args.id)
            print(f"Closed {args.id}.")
        elif command == "reopen":
            ledger.reopen(args.id)
            print(f"Reopened {args.id}.")
        elif command == "show":
            show_cards(con, args.id, args.log)
        elif command == "note":
            note_id = ledger.add_note(None if args.card == "-" else args.card, args.body)
            print(f"Added note #{note_id}.")
        elif command == "decide":
            decisions(con, args, ledger)
        elif command == "plan":
            day_plan(con, args, ledger)
        elif command == "tell":
            count = ledger.tell(args.target, args.body)
            print(f"Delivered to {count} session(s).")
        elif command == "inbox":
            target = args.to or actor.tag
            if args.to and not actor.is_user:
                raise LedgerError("Only the terminal user may read another session's inbox.")
            read_inbox(con, target, args.peek)
        elif command == "log":
            rows = con.execute(
                "SELECT * FROM changelog ORDER BY id DESC LIMIT ?", (args.limit,)
            ).fetchall()
            for row in rows:
                print(f"{row['created_at']} {row['session']} {row['table_name']}/{row['row_id']} "
                      f"{row['field']}: {row['new_value'] or '-'}")
        elif command == "watch":
            last = con.execute("SELECT COALESCE(MAX(id),0) FROM changelog").fetchone()[0]
            while True:
                rows = con.execute("SELECT * FROM changelog WHERE id>? ORDER BY id", (last,)).fetchall()
                for row in rows:
                    print(f"{row['created_at']} {row['session']} {row['table_name']}/{row['row_id']} {row['field']}", flush=True)
                    last = row["id"]
                if args.once:
                    break
                time.sleep(args.interval)
        elif command == "demo":
            seed_demo(con, ledger)


def main(argv: list[str] | None = None) -> int:
    try:
        dispatch(parser().parse_args(argv))
        return 0
    except (LedgerError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
