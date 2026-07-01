import importlib.util
import logging
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


_hooks_path = (
    Path(__file__).resolve().parents[1]
    / "module"
    / "umamusume"
    / "scenario"
    / "aoharuhai"
    / "hooks.py"
)
_handlers_path = (
    Path(__file__).resolve().parents[1]
    / "module"
    / "umamusume"
    / "scenario"
    / "aoharuhai"
    / "handlers.py"
)

_hooks_spec = importlib.util.spec_from_file_location("test_aoharu_hooks_module", _hooks_path)
hooks = importlib.util.module_from_spec(_hooks_spec)
assert _hooks_spec is not None and _hooks_spec.loader is not None
with patch.dict(
    sys.modules,
    {
        "bot.recog.image_matcher": types.SimpleNamespace(
            image_match=lambda *_a, **_k: types.SimpleNamespace(find_match=False)
        ),
        "module.umamusume.asset.template": types.SimpleNamespace(
            REF_AOHARU_RACE=object(),
            REF_SELECT_OPP2=object(),
            REF_ALL_RES=object(),
            REF_RACE_END=object(),
            REF_RACE_END2=object(),
            REF_TEAM_SHOWDOWN=object(),
            REF_NEXT=object(),
            REF_ROUND_1=object(),
            REF_ROUND_2=object(),
            REF_ROUND_3=object(),
            REF_ROUND_4=object(),
            REF_AOHARUHAI_TEAM_NAME_0=object(),
            REF_AOHARUHAI_TEAM_NAME_1=object(),
            REF_AOHARUHAI_TEAM_NAME_2=object(),
            REF_AOHARUHAI_TEAM_NAME_3=object(),
            REF_MANT_RESET_CLOCK=object(),
            UI_AOHARUHAI_RACE_1=object(),
            UI_AOHARUHAI_RACE_2=object(),
            UI_AOHARUHAI_RACE_3=object(),
            UI_AOHARUHAI_RACE_4=object(),
            UI_AOHARUHAI_RACE_5=object(),
        ),
        "module.umamusume.asset.ui": types.SimpleNamespace(
            AOHARUHAI_RACE=object(),
            AOHARUHAI_RACE_FINAL_START=object(),
            AOHARUHAI_RACE_SELECT_OPPONENT=object(),
            AOHARUHAI_RACE_INRACE=object(),
            AOHARUHAI_RACE_END=object(),
            AOHARUHAI_RACE_SCHEDULE=object(),
        ),
    },
):
    _hooks_spec.loader.exec_module(hooks)

_handlers_spec = importlib.util.spec_from_file_location("test_aoharu_handlers_module", _handlers_path)
handlers = importlib.util.module_from_spec(_handlers_spec)
assert _handlers_spec is not None and _handlers_spec.loader is not None
with patch.dict(
    sys.modules,
    {
        "bot.recog.image_matcher": types.SimpleNamespace(
            image_match=lambda *_a, **_k: types.SimpleNamespace(find_match=False)
        ),
        "module.umamusume.asset.template": types.SimpleNamespace(
            UI_AOHARUHAI_RACE_1=object(),
            UI_AOHARUHAI_RACE_2=object(),
            UI_AOHARUHAI_RACE_3=object(),
            UI_AOHARUHAI_RACE_4=object(),
            UI_AOHARUHAI_RACE_5=object(),
        ),
        "module.umamusume.asset.ui": types.SimpleNamespace(
            AOHARUHAI_RACE=object(),
            AOHARUHAI_RACE_FINAL_START=object(),
            AOHARUHAI_RACE_SELECT_OPPONENT=object(),
            AOHARUHAI_RACE_INRACE=object(),
            AOHARUHAI_RACE_END=object(),
            AOHARUHAI_RACE_SCHEDULE=object(),
        ),
    },
):
    _handlers_spec.loader.exec_module(handlers)


class _Ctrl:
    def __init__(self):
        self.clicks = []

    def click(self, x, y, name=""):
        self.clicks.append((x, y, name))


class AoharuFinalShowdownTests(unittest.TestCase):
    def test_after_hook_starts_team_showdown_race_with_single_click(self):
        ctrl = _Ctrl()
        ctx = types.SimpleNamespace(ctrl=ctrl)
        img = np.zeros((1280, 720, 3), dtype=np.uint8)

        with patch.object(hooks, "_is_team_showdown_screen", return_value=True):
            handled = hooks.aoharuhai_after_hook(ctx, img)

        self.assertTrue(handled)
        self.assertEqual(
            ctrl.clicks,
            [(hooks.TEAM_SHOWDOWN_RACE_X, hooks.TEAM_SHOWDOWN_RACE_Y, "team showdown race")],
        )

    def test_after_hook_confirms_team_showdown_popup_with_begin_button(self):
        ctrl = _Ctrl()
        ctx = types.SimpleNamespace(ctrl=ctrl)
        img = np.zeros((1280, 720, 3), dtype=np.uint8)

        with patch.object(hooks, "is_team_showdown_confirmation_popup", return_value=True):
            handled = hooks.aoharuhai_after_hook(ctx, img)

        self.assertTrue(handled)
        self.assertEqual(
            ctrl.clicks,
            [(hooks.TEAM_SHOWDOWN_CONFIRM_X, hooks.TEAM_SHOWDOWN_CONFIRM_Y, "team showdown begin")],
        )

    def test_final_start_handler_uses_team_showdown_race_button(self):
        ctrl = _Ctrl()
        ctx = types.SimpleNamespace(ctrl=ctrl)

        handlers.script_aoharuhai_race_final_start(ctx)

        self.assertEqual(
            ctrl.clicks,
            [(handlers.TEAM_SHOWDOWN_RACE_X, handlers.TEAM_SHOWDOWN_RACE_Y, "Start final team showdown race")],
        )


if __name__ == "__main__":
    unittest.main()
