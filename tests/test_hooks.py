import tempfile
import unittest
from pathlib import Path

from agent_ledger.db import connect, initialize, now
from agent_ledger.hooks import inject_inbox


class HookTests(unittest.TestCase):
    def test_subagent_does_not_consume_parent_inbox(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialize(root)
            with connect(root) as con:
                con.execute(
                    "INSERT INTO sessions(tag,session_id,role,pid,started_at) VALUES(?,?,?,?,?)",
                    ("parent", "parent-session", "worker", 100, now()),
                )
                con.execute(
                    "INSERT INTO inbox(to_tag,from_tag,body,created_at) VALUES(?,?,?,?)",
                    ("parent", "planner", "message", now()),
                )
            inject_inbox(root, {"agent_id": "subagent-1", "session_id": "parent-session"})
            with connect(root) as con:
                unread = con.execute("SELECT COUNT(*) FROM inbox WHERE read_at IS NULL").fetchone()[0]
            self.assertEqual(unread, 1)


if __name__ == "__main__":
    unittest.main()
