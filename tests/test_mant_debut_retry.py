import logging
import importlib.util
import sys
import types
import unittest
from pathlib import Path

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


from module.umamusume.define import ScenarioType

_debut_retry_path = Path(__file__).resolve().parents[1] / "module" / "umamusume" / "scenario" / "mant" / "debut_retry.py"
_debut_retry_spec = importlib.util.spec_from_file_location("test_mant_debut_retry_module", _debut_retry_path)
debut_retry = importlib.util.module_from_spec(_debut_retry_spec)
assert _debut_retry_spec is not None and _debut_retry_spec.loader is not None
_debut_retry_spec.loader.exec_module(debut_retry)


def _fill_noisy(screen, region, low, high):
    x1, y1, x2, y2 = region
    h = y2 - y1
    w = x2 - x1
    pattern = np.indices((h, w)).sum(axis=0) % 2
    values = np.where(pattern[..., None] == 0, low, high).astype(np.uint8)
    screen[y1:y2, x1:x2] = values


def _retry_screen(enabled=True, present=True):
    screen = np.full((1280, 720, 3), 240, dtype=np.uint8)
    if not present:
        return screen
    _fill_noisy(screen, debut_retry.MANT_RETRY_ICON_REGION, 70, 220)
    _fill_noisy(screen, debut_retry.MANT_RETRY_TEXT_REGION, 80, 220)
    x1, y1, x2, y2 = debut_retry.MANT_RETRY_STATUS_REGION
    screen[y1:y2, x1:x2] = 245 if enabled else 155
    x1, y1, x2, y2 = debut_retry.MANT_NEXT_BUTTON_REGION
    screen[y1:y2, x1:x2] = (80, 210, 20)
    return screen


class _Ctrl:
    def __init__(self):
        self.clicks = []

    def click(self, x, y, name=""):
        self.clicks.append((x, y, name))


def _ctx(screen, *, date=12, pending=True, count=0):
    return types.SimpleNamespace(
        current_screen=screen,
        ctrl=_Ctrl(),
        task=types.SimpleNamespace(
            detail=types.SimpleNamespace(
                scenario_config=types.SimpleNamespace(mant_config=types.SimpleNamespace())
            )
        ),
        cultivate_detail=types.SimpleNamespace(
            scenario=types.SimpleNamespace(scenario_type=lambda: ScenarioType.SCENARIO_TYPE_MANT),
            turn_info=types.SimpleNamespace(date=date),
            mant_debut_retry_pending=pending,
            mant_debut_retry_count=count,
            mant_debut_retry_last_click_at=0.0,
        ),
    )


class MantDebutRetryTests(unittest.TestCase):
    def test_button_state_detects_enabled_and_disabled(self):
        enabled = debut_retry.mant_debut_retry_button_state(_retry_screen(enabled=True))
        disabled = debut_retry.mant_debut_retry_button_state(_retry_screen(enabled=False))

        self.assertTrue(enabled["present"])
        self.assertTrue(enabled["enabled"])
        self.assertTrue(disabled["present"])
        self.assertFalse(disabled["enabled"])

    def test_maybe_handle_clicks_enabled_retry_and_increments_count(self):
        ctx = _ctx(_retry_screen(enabled=True), count=2)

        handled = debut_retry.maybe_handle_mant_debut_retry(ctx)

        self.assertTrue(handled)
        self.assertEqual(ctx.ctrl.clicks, [(202, 1179, "MANT Debut Try Again")])
        self.assertEqual(ctx.cultivate_detail.mant_debut_retry_count, 3)
        self.assertTrue(ctx.cultivate_detail.mant_debut_retry_pending)

    def test_maybe_handle_accepts_result_when_retry_disabled(self):
        ctx = _ctx(_retry_screen(enabled=False), count=2)

        handled = debut_retry.maybe_handle_mant_debut_retry(ctx)

        self.assertFalse(handled)
        self.assertEqual(ctx.ctrl.clicks, [])
        self.assertFalse(ctx.cultivate_detail.mant_debut_retry_pending)

    def test_maybe_handle_stops_at_five_retries(self):
        ctx = _ctx(_retry_screen(enabled=True), count=5)

        handled = debut_retry.maybe_handle_mant_debut_retry(ctx)

        self.assertFalse(handled)
        self.assertEqual(ctx.ctrl.clicks, [])
        self.assertFalse(ctx.cultivate_detail.mant_debut_retry_pending)

    def test_maybe_handle_rejects_ambiguous_brightness(self):
        screen = _retry_screen(enabled=True)
        x1, y1, x2, y2 = debut_retry.MANT_RETRY_STATUS_REGION
        screen[y1:y2, x1:x2] = 219
        ctx = _ctx(screen, count=0)

        handled = debut_retry.maybe_handle_mant_debut_retry(ctx)

        self.assertFalse(handled)
        self.assertEqual(ctx.ctrl.clicks, [])
        self.assertFalse(ctx.cultivate_detail.mant_debut_retry_pending)

    def test_button_state_requires_next_button_signal(self):
        screen = _retry_screen(enabled=True)
        x1, y1, x2, y2 = debut_retry.MANT_NEXT_BUTTON_REGION
        screen[y1:y2, x1:x2] = 240

        state = debut_retry.mant_debut_retry_button_state(screen)

        self.assertFalse(state["present"])
        self.assertFalse(state["enabled"])

    def test_mark_mant_debut_only_arms_date_twelve(self):
        ctx = _ctx(_retry_screen(enabled=True), date=12, pending=False)
        self.assertTrue(debut_retry.mark_mant_debut_race_started(ctx, "test"))
        self.assertTrue(ctx.cultivate_detail.mant_debut_retry_pending)

        ctx = _ctx(_retry_screen(enabled=True), date=13, pending=False)
        self.assertFalse(debut_retry.mark_mant_debut_race_started(ctx, "test"))
        self.assertFalse(ctx.cultivate_detail.mant_debut_retry_pending)


if __name__ == "__main__":
    unittest.main()
