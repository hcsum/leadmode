import unittest

from agent_ledger.dashboard import validate_bind


class DashboardSafetyTests(unittest.TestCase):
    def test_loopback_is_allowed(self):
        validate_bind("127.0.0.1")
        validate_bind("::1")
        validate_bind("localhost")

    def test_non_loopback_requires_explicit_override(self):
        with self.assertRaisesRegex(ValueError, "Refusing non-loopback"):
            validate_bind("0.0.0.0")
        validate_bind("0.0.0.0", unsafe_expose=True)


if __name__ == "__main__":
    unittest.main()
