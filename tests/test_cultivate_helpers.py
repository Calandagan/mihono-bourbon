import logging
import sys
import types
import unittest
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


if "colorlog" not in sys.modules:
    class _ColoredFormatter(logging.Formatter):
        def __init__(self, *args, **kwargs):
            kwargs.pop("log_colors", None)
            super().__init__(*args, **kwargs)

        def format(self, record):
            if not hasattr(record, "log_color"):
                record.log_color = ""
            return super().format(record)

    sys.modules["colorlog"] = types.SimpleNamespace(ColoredFormatter=_ColoredFormatter)


sys.modules.setdefault(
    "bot.recog.image_matcher",
    types.SimpleNamespace(image_match=lambda *args, **kwargs: SimpleNamespace(find_match=True)),
)
sys.modules.setdefault(
    "cv2",
    types.SimpleNamespace(cvtColor=lambda img, mode: img, COLOR_BGR2GRAY=0),
)
sys.modules.setdefault(
    "module.umamusume.context",
    types.SimpleNamespace(UmamusumeContext=object),
)
sys.modules["module.umamusume.asset.template"] = types.SimpleNamespace(
    UI_RECREATION_FRIEND_NOTIFICATION=object()
)

_helpers_path = Path(__file__).resolve().parents[1] / "module" / "umamusume" / "script" / "cultivate_task" / "helpers.py"
_helpers_spec = importlib.util.spec_from_file_location("test_cultivate_helpers_module", _helpers_path)
helpers = importlib.util.module_from_spec(_helpers_spec)
assert _helpers_spec is not None and _helpers_spec.loader is not None
_helpers_spec.loader.exec_module(helpers)
sys.modules["module.umamusume.script.cultivate_task.helpers"] = helpers


class CultivateHelpersTests(unittest.TestCase):
    def test_should_use_pal_outing_simple_skips_when_mood_is_max(self):
        ctx = SimpleNamespace(
            cultivate_detail=SimpleNamespace(
                prioritize_recreation=True,
                pal_event_stage=1,
                pal_thresholds=[(5, 80, 0)],
                turn_info=SimpleNamespace(
                    date=20,
                    pal_outing_cached=None,
                    pal_outing_cached_date=-1,
                ),
            ),
            current_screen=object(),
        )

        fake_fetch = types.SimpleNamespace(fetch_state=lambda _img: {"energy": 20, "mood": 5})
        with patch.object(helpers.cv2, "cvtColor", return_value=object()), \
             patch.dict(sys.modules, {"bot.conn.fetch": fake_fetch}):
            result = helpers.should_use_pal_outing_simple(ctx)

        self.assertFalse(result)
        self.assertFalse(ctx.cultivate_detail.turn_info.pal_outing_cached)


if __name__ == "__main__":
    unittest.main()
