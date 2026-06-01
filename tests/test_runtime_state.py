import unittest

from bot.base.runtime_state import get_state, patch_state, set_state


class RuntimeStateTests(unittest.TestCase):
    def test_runtime_state_snapshot_is_immutable(self):
        snapshot = get_state()
        with self.assertRaises(TypeError):
            snapshot["input_blocked"] = True

    def test_runtime_state_updates_flow_through_setters(self):
        set_state("input_blocked", True)
        patch_state({"in_career_run": True}, trigger_decision_reset=True)
        snapshot = get_state()
        self.assertTrue(snapshot["input_blocked"])
        self.assertTrue(snapshot["in_career_run"])
        self.assertTrue(snapshot["trigger_decision_reset"])


if __name__ == "__main__":
    unittest.main()
