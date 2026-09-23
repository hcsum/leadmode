import json
import tempfile
import unittest
from pathlib import Path

from agent_ledger.install import HOOK_COMMAND, install, merge_settings


class InstallTests(unittest.TestCase):
    def test_merge_preserves_settings_and_is_idempotent(self):
        settings = {"permissions": {"allow": ["Bash(git status)"]}, "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "existing-hook"}]}]}}
        merge_settings(settings)
        merge_settings(settings)
        self.assertIn("Bash(git status)", settings["permissions"]["allow"])
        self.assertIn("Bash(agent-ledger *)", settings["permissions"]["allow"])
        self.assertIn("Bash(agent-ledger:*)", settings["permissions"]["allow"])
        self.assertEqual(settings["permissions"]["allow"].count("Bash(agent-ledger *)"), 1)
        for event in ("SessionStart", "SessionEnd", "PostToolUse", "UserPromptSubmit", "Stop"):
            commands = [hook["command"] for entry in settings["hooks"][event] for hook in entry["hooks"]]
            self.assertEqual(commands.count(HOOK_COMMAND), 1)
        self.assertIn("existing-hook", [h["command"] for e in settings["hooks"]["Stop"] for h in e["hooks"]])

    def test_merge_migrates_legacy_hook_command(self):
        settings = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "agent-ledger-hook"}]}]}}
        merge_settings(settings)
        commands = [hook["command"] for entry in settings["hooks"]["Stop"] for hook in entry["hooks"]]
        self.assertEqual(commands, [HOOK_COMMAND])

    def test_install_keeps_existing_json_and_copies_skills(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text(json.dumps({"custom": True}))
            install(root)
            install(root)
            settings = json.loads((root / ".claude" / "settings.json").read_text())
            self.assertTrue(settings["custom"])
            self.assertTrue((root / ".claude" / "skills" / "worker" / "SKILL.md").exists())
            self.assertEqual((root / ".gitignore").read_text().count(".agent-ledger/"), 1)
            self.assertTrue((root / ".agent-ledger" / "hook").exists())

    def test_install_refuses_to_overwrite_existing_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / ".claude" / "skills" / "planner" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("user-owned skill\n")
            with self.assertRaisesRegex(ValueError, "Refusing to overwrite"):
                install(root)
            self.assertEqual(skill.read_text(), "user-owned skill\n")


if __name__ == "__main__":
    unittest.main()
