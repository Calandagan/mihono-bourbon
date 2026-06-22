import importlib.util
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path


if "colorlog" not in sys.modules:
    class _ColoredFormatter(logging.Formatter):
        def __init__(self, *args, **kwargs):
            kwargs.pop("log_colors", None)
            super().__init__(*args, **kwargs)

        def format(self, record):
            if not hasattr(record, "log_color"):
                record.log_color = ""
            return super().format(record)

    sys.modules["colorlog"] = type("_ColorLog", (), {"ColoredFormatter": _ColoredFormatter})()


_persistence_path = Path(__file__).resolve().parents[1] / "module" / "umamusume" / "persistence.py"
_persistence_spec = importlib.util.spec_from_file_location("test_persistence_module", _persistence_path)
persistence = importlib.util.module_from_spec(_persistence_spec)
assert _persistence_spec is not None and _persistence_spec.loader is not None
_persistence_spec.loader.exec_module(persistence)


class PersistenceTests(unittest.TestCase):
    def test_clear_mant_run_state_removes_stale_run_keys_only(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            persist_file = Path(tmp_dir) / "persist.json"
            persistence.PERSIST_FILE = str(persist_file)
            persist_file.write_text(
                json.dumps(
                    {
                        "inventory": [["Motivating Megaphone", 1]],
                        "afflictions": ["Headache"],
                        "megaphone_tier": 3,
                        "megaphone_turns": 2,
                        "used_buffs": ["Pretty Mirror"],
                        "ignore_cat_food": True,
                        "ignore_grilled_carrots": True,
                        "last_known_date": 60,
                        "unrelated": "keep",
                    }
                )
            )

            persistence.clear_mant_run_state()

            data = json.loads(persist_file.read_text())

        self.assertEqual(data, {"unrelated": "keep"})


if __name__ == "__main__":
    unittest.main()
