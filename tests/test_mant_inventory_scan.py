import importlib.util
import logging
import sys
import types
import unittest
from pathlib import Path
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


class _DummyArray:
    size = 1
    shape = (1280, 720, 3)

    def __getitem__(self, _item):
        return self


_dummy_logger = types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
_bot_base_pkg = types.ModuleType("bot.base")
_bot_base_log = types.SimpleNamespace(get_logger=lambda _name: _dummy_logger)
_bot_base_pkg.log = _bot_base_log

_inventory_path = (
    Path(__file__).resolve().parents[1]
    / "module"
    / "umamusume"
    / "scenario"
    / "mant"
    / "inventory.py"
)
_inventory_spec = importlib.util.spec_from_file_location("test_mant_inventory_scan_module", _inventory_path)
inventory = importlib.util.module_from_spec(_inventory_spec)
assert _inventory_spec is not None and _inventory_spec.loader is not None

with patch.dict(
    sys.modules,
    {
        "cv2": types.SimpleNamespace(
            COLOR_BGR2GRAY=0,
            COLOR_BGR2RGB=0,
            COLOR_GRAY2BGR=0,
            THRESH_BINARY=0,
            THRESH_OTSU=0,
            INTER_CUBIC=0,
            cvtColor=lambda img, *_a, **_k: img,
            resize=lambda img, *_a, **_k: img,
            threshold=lambda img, *_a, **_k: (0, img),
            absdiff=lambda a, b: a,
            mean=lambda *_a, **_k: (0,),
        ),
        "numpy": types.SimpleNamespace(mean=lambda *_a, **_k: 0),
        "bot.base": _bot_base_pkg,
        "bot.base.log": _bot_base_log,
        "bot.recog.ocr": types.SimpleNamespace(ocr=lambda *_a, **_k: []),
        "rapidfuzz": types.SimpleNamespace(
            process=types.SimpleNamespace(extractOne=lambda *_a, **_k: None),
            fuzz=types.SimpleNamespace(ratio=lambda *_a, **_k: 0),
        ),
        "module.umamusume.scenario.mant.shop": types.SimpleNamespace(
            SHOP_ITEM_NAMES=[],
            EFFECT_PREFIXES=(),
            SB_X=695,
            SB_X_MIN=693,
            SB_X_MAX=697,
            _gauss_scan_x=lambda: 360,
            is_thumb=lambda *_a, **_k: False,
            is_track=lambda *_a, **_k: False,
        ),
    },
):
    _inventory_spec.loader.exec_module(inventory)


class _ScreenStream:
    def __init__(self, frames):
        self.frames = list(frames)
        self.index = 0

    def __call__(self):
        idx = min(self.index, len(self.frames) - 1)
        self.index += 1
        return self.frames[idx]


class MantInventoryScanTests(unittest.TestCase):
    def test_scan_inventory_reads_bottom_view_before_stopping(self):
        top_frame = _DummyArray()
        bottom_frame = _DummyArray()
        screens = _ScreenStream([top_frame, top_frame, top_frame, bottom_frame])

        def classify(frame):
            if frame is bottom_frame:
                return [("Artisan Cleat Hammer", 1.0, 200, 2)]
            return []

        bottom_checks = iter([False, True])

        ctx = types.SimpleNamespace(
            ctrl=types.SimpleNamespace(get_screen=screens, swipe_async=lambda *_a, **_k: types.SimpleNamespace(is_alive=lambda: False)),
            task=types.SimpleNamespace(running=lambda: True),
        )

        with patch.object(inventory, "scroll_to_top", return_value=None), \
             patch.object(inventory, "classify_with_qty", side_effect=classify), \
             patch.object(inventory, "inv_find_thumb", return_value=(500, 540)), \
             patch.object(inventory, "inv_at_bottom", side_effect=lambda _img: next(bottom_checks)), \
             patch.object(inventory, "time", types.SimpleNamespace(sleep=lambda *_a, **_k: None, time=lambda: 0.0)), \
             patch.object(inventory, "random", types.SimpleNamespace(uniform=lambda *_a, **_k: 0.0, randint=lambda a, b: a)):
            owned = inventory.scan_inventory(ctx)

        self.assertIn(("Artisan Cleat Hammer", 2), owned)


if __name__ == "__main__":
    unittest.main()
