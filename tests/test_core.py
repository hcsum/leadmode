import tempfile
import unittest
from pathlib import Path

from agent_ledger.core import Ledger, LedgerError
from agent_ledger.db import connect, initialize, now
from agent_ledger.identity import Identity


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        initialize(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def identity(self, tag, role, user=False):
        return Identity(tag, role, user)

    def add_session(self, con, tag, role):
        con.execute(
            "INSERT INTO sessions(tag,session_id,role,pid,started_at) VALUES(?,?,?,?,?)",
            (tag, tag + "-session", role, 100, now()),
        )

    def test_card_ownership_and_permissions(self):
        with connect(self.root) as con:
            planner = Ledger(con, self.identity("plan", "planner"))
            planner.add_card("A-1", "Owned work", "Ready")
            planner.set_field("A-1", "status", "queued")
            worker = Ledger(con, self.identity("work-1", "worker"))
            worker.claim("A-1")
            worker.set_field("A-1", "progress", "testing")
            with self.assertRaises(LedgerError):
                planner.set_field("A-1", "status", "planner overwrite")
            other = Ledger(con, self.identity("work-2", "worker"))
            with self.assertRaises(LedgerError):
                other.set_field("A-1", "progress", "overwrite")
            with self.assertRaises(LedgerError):
                planner.claim("A-1")

    def test_open_decision_blocks_close(self):
        with connect(self.root) as con:
            user = Ledger(con, self.identity("user", "user", True))
            user.add_card("A-2", "Decision work", "Doing")
            user.add_decision("Which format?", "A-2")
            with self.assertRaisesRegex(LedgerError, "open decision"):
                user.close("A-2")
            user.close_decision(1, "Use JSON")
            user.close("A-2")
            self.assertEqual(con.execute("SELECT lane FROM cards WHERE id='A-2'").fetchone()[0], "Done")

    def test_inbox_delivery_to_planner_and_owner(self):
        with connect(self.root) as con:
            self.add_session(con, "plan", "planner")
            self.add_session(con, "work", "worker")
            user = Ledger(con, self.identity("user", "user", True))
            user.add_card("A-3", "Inbox work", "Ready")
            Ledger(con, self.identity("work", "worker")).claim("A-3")
            user.add_note("A-3", "Please verify edge cases")
            recipients = {
                row[0] for row in con.execute(
                    "SELECT to_tag FROM inbox WHERE body LIKE 'Note on A-3:%'"
                )
            }
            self.assertEqual(recipients, {"plan", "work"})


if __name__ == "__main__":
    unittest.main()
