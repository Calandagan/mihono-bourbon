import logging
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np


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


_retry_path = (
    Path(__file__).resolve().parents[1]
    / "module"
    / "umamusume"
    / "scenario"
    / "aoharuhai"
    / "retry.py"
)
_retry_spec = importlib.util.spec_from_file_location("test_aoharu_retry_module", _retry_path)
retry = importlib.util.module_from_spec(_retry_spec)
assert _retry_spec is not None and _retry_spec.loader is not None
with patch.dict(
    sys.modules,
    {
        "bot.recog.image_matcher": types.SimpleNamespace(
            image_match=lambda *_a, **_k: types.SimpleNamespace(find_match=False)
        ),
        "module.umamusume.asset.template": types.SimpleNamespace(
            REF_TEAM_SHOWDOWN=object(),
        ),
        "module.umamusume.define": types.SimpleNamespace(
            ScenarioType=types.SimpleNamespace(SCENARIO_TYPE_AOHARUHAI=object()),
        ),
    },
):
    _retry_spec.loader.exec_module(retry)


class _Ctrl:
    def __init__(self):
        self.clicks = []
        self.point_clicks = []

    def click(self, x, y, name=""):
        self.clicks.append((x, y, name))

    def click_by_point(self, point):
        self.point_clicks.append(point)


def _ctx(**detail_kwargs):
    detail = types.SimpleNamespace(**detail_kwargs)
    return types.SimpleNamespace(ctrl=_Ctrl(), cultivate_detail=detail)


def _lost_state():
    return {
        "present": True,
        "lost": True,
        "retry_enabled": True,
        "retry_brightness": 190.0,
        "retry_std": 32.0,
        "lose_blue_ratio": 0.15,
        "lose_white_ratio": 0.03,
        "next_green": 210.0,
        "next_delta": 80.0,
    }


class AoharuShowdownRetryTests(unittest.TestCase):
    def test_lost_showdown_clicks_try_again_and_marks_confirm_pending(self):
        ctx = _ctx(
            retry_lost_aoharu_showdowns=True,
            clock_used=1,
            clock_use_limit=3,
            aoharu_showdown_retry_last_click_at=0.0,
        )
        screen = np.zeros((1280, 720, 3), dtype=np.uint8)

        with patch.object(retry, "_is_aoharu", return_value=True), \
                patch.object(retry, "aoharu_showdown_result_state", return_value=_lost_state()), \
                patch.object(retry.time, "time", return_value=100.0):
            handled = retry.handle_aoharu_showdown_result(ctx, screen)

        self.assertTrue(handled)
        self.assertEqual(
            ctx.ctrl.clicks,
            [(retry.AOHARU_TRY_AGAIN_CLICK[0], retry.AOHARU_TRY_AGAIN_CLICK[1], "Aoharu Team Showdown Try Again")],
        )
        self.assertTrue(ctx.cultivate_detail.aoharu_showdown_retry_confirm_pending)
        self.assertEqual(ctx.cultivate_detail.clock_used, 1)

    def test_retry_confirm_spends_one_clock_and_clears_pending(self):
        ctx = _ctx(
            clock_used=1,
            clock_use_limit=3,
            aoharu_showdown_retry_confirm_pending=True,
            aoharu_showdown_retry_confirm_started_at=100.0,
        )
        fake_asset = types.ModuleType("module.umamusume.asset")
        fake_point = types.ModuleType("module.umamusume.asset.point")
        fake_point.RACE_FAIL_CONTINUE_USE_CLOCK = object()
        fake_point.RACE_FAIL_CONTINUE_CANCEL = object()

        with patch.object(retry, "_is_aoharu", return_value=True), \
                patch.object(retry.time, "time", return_value=101.0), \
                patch.dict(
                    sys.modules,
                    {
                        "module.umamusume.asset": fake_asset,
                        "module.umamusume.asset.point": fake_point,
                    },
                ):
            handled = retry.handle_aoharu_showdown_retry_confirm(ctx)

        self.assertTrue(handled)
        self.assertEqual(len(ctx.ctrl.point_clicks), 1)
        self.assertEqual(ctx.cultivate_detail.clock_used, 2)
        self.assertFalse(ctx.cultivate_detail.aoharu_showdown_retry_confirm_pending)

    def test_lost_showdown_without_toggle_clicks_next(self):
        ctx = _ctx(
            retry_lost_aoharu_showdowns=False,
            clock_used=0,
            clock_use_limit=3,
            aoharu_showdown_retry_last_click_at=0.0,
        )

        with patch.object(retry, "_is_aoharu", return_value=True), \
                patch.object(retry, "aoharu_showdown_result_state", return_value=_lost_state()):
            handled = retry.handle_aoharu_showdown_result(ctx, np.zeros((1280, 720, 3), dtype=np.uint8))

        self.assertTrue(handled)
        self.assertEqual(
            ctx.ctrl.clicks,
            [(retry.AOHARU_NEXT_CLICK[0], retry.AOHARU_NEXT_CLICK[1], "Aoharu Team Showdown Next")],
        )


if __name__ == "__main__":
    unittest.main()
