from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .db import log_change, now
from .identity import Identity


class LedgerError(RuntimeError):
    pass


@dataclass
class Ledger:
    con: sqlite3.Connection
    actor: Identity

    def require_role(self, *roles: str) -> None:
        if not self.actor.is_user and self.actor.role not in roles:
            allowed = ", ".join(roles)
            raise LedgerError(f"This action requires one of these roles: {allowed}.")

    def card(self, card_id: str) -> sqlite3.Row:
        row = self.con.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
        if not row:
            raise LedgerError(f"Card not found: {card_id}")
        return row

    def add_card(self, card_id: str, title: str, lane: str = "Backlog") -> None:
        self.require_role("planner")
        stamp = now()
        try:
            self.con.execute(
                "INSERT INTO cards(id,title,lane,status,created_at,updated_at) VALUES(?,?,?,'open',?,?)",
                (card_id, title, lane, stamp, stamp),
            )
        except sqlite3.IntegrityError as exc:
            raise LedgerError(f"Card already exists: {card_id}") from exc
        log_change(self.con, self.actor.tag, "cards", card_id, "created", None, title)
        self.deliver(f"Card {card_id} added: {title}", roles=("planner",))

    def claim(self, card_id: str) -> None:
        self.require_role("worker")
        card = self.card(card_id)
        if card["closed_at"]:
            raise LedgerError(f"Card is closed: {card_id}")
        if card["owner"] and card["owner"] != self.actor.tag and not self.actor.is_user:
            raise LedgerError(f"Card {card_id} is owned by session {card['owner']}.")
        old = card["owner"]
        self.con.execute(
            "UPDATE cards SET owner=?,lane='Doing',updated_at=? WHERE id=?",
            (self.actor.tag, now(), card_id),
        )
        log_change(self.con, self.actor.tag, "cards", card_id, "owner", old, self.actor.tag)
        self.deliver(f"Card {card_id} claimed by {self.actor.tag}.", roles=("planner",))

    def require_owner(self, card: sqlite3.Row) -> None:
        if self.actor.is_user:
            return
        if self.actor.role == "planner" and not card["owner"]:
            return
        if card["owner"] != self.actor.tag:
            raise LedgerError(f"Only the owner of card {card['id']} may change its work state.")

    def set_field(self, card_id: str, field: str, value: str) -> None:
        allowed = {"title", "lane", "status", "progress"}
        if field not in allowed:
            raise LedgerError(f"Field must be one of: {', '.join(sorted(allowed))}.")
        card = self.card(card_id)
        if field == "title":
            self.require_role("planner")
        else:
            self.require_owner(card)
        self.con.execute(f"UPDATE cards SET {field}=?,updated_at=? WHERE id=?", (value, now(), card_id))
        log_change(self.con, self.actor.tag, "cards", card_id, field, card[field], value)
        self.deliver(f"Card {card_id} {field}: {value}", roles=("planner",), extra=(card["owner"],))

    def release(self, card_id: str) -> None:
        card = self.card(card_id)
        self.require_owner(card)
        self.con.execute("UPDATE cards SET owner=NULL,updated_at=? WHERE id=?", (now(), card_id))
        log_change(self.con, self.actor.tag, "cards", card_id, "owner", card["owner"], None)
        self.deliver(f"Card {card_id} released.", roles=("planner",))

    def close(self, card_id: str) -> None:
        card = self.card(card_id)
        self.require_owner(card)
        count = self.con.execute(
            "SELECT COUNT(*) FROM decisions WHERE card_id=? AND closed_at IS NULL", (card_id,)
        ).fetchone()[0]
        if count:
            raise LedgerError(f"Cannot close {card_id}: {count} open decision(s).")
        stamp = now()
        self.con.execute(
            "UPDATE cards SET status='closed',lane='Done',owner=NULL,closed_at=?,updated_at=? WHERE id=?",
            (stamp, stamp, card_id),
        )
        log_change(self.con, self.actor.tag, "cards", card_id, "closed_at", card["closed_at"], stamp)
        self.deliver(f"Card {card_id} closed.", roles=("planner",))

    def reopen(self, card_id: str) -> None:
        self.require_role("planner")
        card = self.card(card_id)
        self.con.execute(
            "UPDATE cards SET status='open',lane='Ready',closed_at=NULL,updated_at=? WHERE id=?",
            (now(), card_id),
        )
        log_change(self.con, self.actor.tag, "cards", card_id, "closed_at", card["closed_at"], None)

    def add_note(self, card_id: str | None, body: str) -> int:
        if card_id:
            self.card(card_id)
        cur = self.con.execute(
            "INSERT INTO notes(card_id,session,body,created_at) VALUES(?,?,?,?)",
            (card_id, self.actor.tag, body, now()),
        )
        note_id = int(cur.lastrowid)
        log_change(self.con, self.actor.tag, "notes", note_id, "created", None, body)
        owner = self.card(card_id)["owner"] if card_id else None
        self.deliver(f"Note on {card_id or 'ledger'}: {body}", roles=("planner",), extra=(owner,))
        return note_id

    def add_decision(self, body: str, card_id: str | None = None) -> int:
        if card_id:
            self.card(card_id)
        cur = self.con.execute(
            "INSERT INTO decisions(card_id,body,raised_by,created_at) VALUES(?,?,?,?)",
            (card_id, body, self.actor.tag, now()),
        )
        decision_id = int(cur.lastrowid)
        log_change(self.con, self.actor.tag, "decisions", decision_id, "created", None, body)
        self.deliver(f"Decision #{decision_id} opened: {body}", roles=("planner", "consult"))
        return decision_id

    def check_decision(self, decision_id: int) -> None:
        row = self._decision(decision_id)
        if row["closed_at"]:
            raise LedgerError(f"Decision #{decision_id} is already closed.")
        self.con.execute("UPDATE decisions SET checked_at=? WHERE id=?", (now(), decision_id))
        log_change(self.con, self.actor.tag, "decisions", decision_id, "checked_at", row["checked_at"], now())

    def close_decision(self, decision_id: int, resolution: str) -> None:
        self.require_role("planner", "consult")
        row = self._decision(decision_id)
        if row["closed_at"]:
            raise LedgerError(f"Decision #{decision_id} is already closed.")
        stamp = now()
        self.con.execute(
            "UPDATE decisions SET resolution=?,closed_by=?,closed_at=? WHERE id=?",
            (resolution, self.actor.tag, stamp, decision_id),
        )
        log_change(self.con, self.actor.tag, "decisions", decision_id, "resolution", None, resolution)
        owner = self.card(row["card_id"])["owner"] if row["card_id"] else None
        self.deliver(f"Decision #{decision_id} closed: {resolution}", extra=(row["raised_by"], owner))

    def _decision(self, decision_id: int) -> sqlite3.Row:
        row = self.con.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
        if not row:
            raise LedgerError(f"Decision not found: {decision_id}")
        return row

    def deliver(self, body: str, roles: tuple[str, ...] = (), extra: tuple[str | None, ...] = ()) -> None:
        targets = {tag for tag in extra if tag}
        if roles:
            placeholders = ",".join("?" for _ in roles)
            targets.update(
                row["tag"]
                for row in self.con.execute(
                    f"SELECT tag FROM sessions WHERE ended_at IS NULL AND role IN ({placeholders})", roles
                )
            )
        targets.discard(self.actor.tag)
        stamp = now()
        for target in targets:
            self.con.execute(
                "INSERT INTO inbox(to_tag,from_tag,kind,body,created_at) VALUES(?,?,?,?,?)",
                (target, self.actor.tag, "change", body, stamp),
            )

    def tell(self, target: str, body: str) -> int:
        rows = self.con.execute(
            "SELECT tag FROM sessions WHERE ended_at IS NULL AND (tag=? OR role=?)", (target, target)
        ).fetchall()
        tags = [row["tag"] for row in rows if row["tag"] != self.actor.tag]
        if not tags:
            raise LedgerError(f"No active session or role matches: {target}")
        for tag in tags:
            self.con.execute(
                "INSERT INTO inbox(to_tag,from_tag,kind,body,created_at) VALUES(?,?,?,?,?)",
                (tag, self.actor.tag, "tell", body, now()),
            )
        return len(tags)
