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


class _DummyFrame:
    size = 1
    shape = (1280, 720, 3)

    def copy(self):
        return self

    def __getitem__(self, _item):
        return self


_dummy_logger = types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
_bot_base_pkg = types.ModuleType("bot.base")
_bot_base_log = types.SimpleNamespace(get_logger=lambda _name: _dummy_logger)
_bot_base_pkg.log = _bot_base_log
_shop_path = (
    Path(__file__).resolve().parents[1]
    / "module"
    / "umamusume"
    / "scenario"
    / "mant"
    / "shop.py"
)
_shop_spec = importlib.util.spec_from_file_location("test_mant_shop_scroll_module", _shop_path)
shop = importlib.util.module_from_spec(_shop_spec)
assert _shop_spec is not None and _shop_spec.loader is not None

with patch.dict(
    sys.modules,
    {
        "cv2": types.SimpleNamespace(
            COLOR_BGR2GRAY=0,
            COLOR_BGR2RGB=0,
            TM_CCOEFF_NORMED=0,
            cvtColor=lambda img, *_a, **_k: img,
            imread=lambda *_a, **_k: None,
            matchTemplate=lambda *_a, **_k: [],
            minMaxLoc=lambda *_a, **_k: (0, 0, (0, 0), (0, 0)),
            mean=lambda *_a, **_k: (255,),
        ),
        "numpy": types.SimpleNamespace(where=lambda *_a, **_k: ([], []), mean=lambda *_a, **_k: 0),
        "bot.base": _bot_base_pkg,
        "bot.base.log": _bot_base_log,
        "bot.recog.ocr": types.SimpleNamespace(ocr=lambda *_a, **_k: [], ocr_line=lambda *_a, **_k: ""),
        "rapidfuzz": types.SimpleNamespace(
            process=types.SimpleNamespace(extractOne=lambda *_a, **_k: None),
            fuzz=types.SimpleNamespace(ratio=lambda *_a, **_k: 0),
        ),
        "module.umamusume.scenario.mant.constants": types.SimpleNamespace(
            MANT_ITEM_COSTS={"Vita 20": 20},
            MANT_ITEM_NAMES=["Vita 20"],
            MANT_SLUG_TO_DISPLAY={"vita_20": "Vita 20"},
            display_to_slug=lambda name: {"Vita 20": "vita_20"}.get(name, name.lower().replace(" ", "_")),
        ),
    },
):
    _shop_spec.loader.exec_module(shop)


class MantShopScrollTests(unittest.TestCase):
    def test_at_bottom_is_false_when_thumb_is_missing(self):
        with patch.object(shop, "find_thumb", return_value=None):
            self.assertFalse(shop.at_bottom(_DummyFrame()))

    def test_dedup_detections_uses_majority_buyable_vote(self):
        items = shop.dedup_detections(
            [
                ("Vita 20", 90, 0, 500, 4, False),
                ("Vita 20", 91, 1, 505, 4, False),
                ("Vita 20", 92, 2, 510, 4, True),
            ],
            {0: _DummyFrame(), 1: _DummyFrame(), 2: _DummyFrame()},
        )
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0][4])

    def test_buy_shop_items_does_not_treat_missing_thumb_as_bottom(self):
        frame_missing = _DummyFrame()
        frame_ready = _DummyFrame()
        clicks = []
        fallback_calls = []

        ctx = types.SimpleNamespace(
            ctrl=types.SimpleNamespace(
                click=lambda x, y, name=None: clicks.append((x, y, name)),
                get_screen=lambda **_kwargs: _DummyFrame(),
            ),
            cultivate_detail=types.SimpleNamespace(
                turn_info=types.SimpleNamespace(set_shop_trace=lambda **_k: None),
                mant_failed_shop_names_snapshot=set(),
            ),
        )

        image_match_result = types.SimpleNamespace(
            find_match=True,
            matched_area=((0, 10), (10, 20)),
        )

        with patch.object(shop, "scroll_to_top", return_value=None), \
             patch.object(
                 shop,
                 "capture_shop_scroll_state",
                 side_effect=[
                     (frame_missing, frame_missing, None),
                     (frame_ready, frame_ready, (500, 540)),
                 ],
             ), \
             patch.object(shop, "content_scroll_down", side_effect=lambda *_a, **_k: fallback_calls.append(True)), \
             patch.object(
                 shop,
                 "classify_items_in_frame",
                 side_effect=[
                     ([], False),
                     ([("Vita 20", 0.95, 620, 6, True)], False),
                 ],
             ), \
             patch.object(shop, "is_unbuyable", return_value=False), \
             patch.object(shop, "time", types.SimpleNamespace(sleep=lambda *_a, **_k: None)), \
             patch.dict(
                 sys.modules,
                 {
                     "bot.recog.image_matcher": types.SimpleNamespace(image_match=lambda *_a, **_k: image_match_result),
                     "module.umamusume.asset.template": types.SimpleNamespace(UI_INFO=object()),
                     "module.umamusume.script.cultivate_task.info": types.SimpleNamespace(
                         find_similar_text=lambda text, *_a, **_k: text
                     ),
                     "bot.recog.ocr": types.SimpleNamespace(
                         ocr=lambda *_a, **_k: [],
                         ocr_line=lambda *_a, **_k: "Exchange Complete",
                     ),
                 },
             ):
            bought, result = shop.buy_shop_items(ctx, ["Vita 20"], [])

        self.assertTrue(bought)
        self.assertEqual(result["selected"], ["Vita 20"])
        self.assertTrue(any(x == shop.CHECKBOX_X for x, _y, _name in clicks))
        self.assertEqual(len(fallback_calls), 1)

    def test_scan_mant_shop_uses_content_fallback_when_scrollbar_is_missing(self):
        frame_initial = _DummyFrame()
        frame_missing = _DummyFrame()
        frame_settled = _DummyFrame()
        fallback_calls = []

        ctx = types.SimpleNamespace(
            ctrl=types.SimpleNamespace(get_screen=lambda **_kwargs: _DummyFrame()),
            task=types.SimpleNamespace(running=lambda: True),
        )

        with patch.object(shop, "open_mant_shop", return_value=True), \
             patch.object(shop, "scroll_to_top", return_value=None), \
             patch.object(
                 shop,
                 "capture_shop_scroll_state",
                 side_effect=[
                     (frame_initial, frame_initial, (500, 540)),
                     (frame_missing, frame_missing, None),
                     (frame_settled, frame_settled, (700, 740)),
                 ],
             ), \
             patch.object(shop, "classify_items_in_frame", side_effect=[
                 ([("Vita 20", 0.95, 620, 6, True)], False),
                 ([("Vita 20", 0.95, 700, 6, True)], False),
             ]), \
             patch.object(shop, "content_same", return_value=False), \
             patch.object(shop, "content_scroll_down", side_effect=lambda *_a, **_k: fallback_calls.append(True)), \
             patch.object(shop, "dedup_detections", return_value=[("Vita 20", 0.95, 620, 6, True)]), \
             patch.object(shop, "at_bottom", side_effect=[False, True]), \
             patch.object(shop, "time", types.SimpleNamespace(sleep=lambda *_a, **_k: None)):
            items = shop.scan_mant_shop(ctx)

        self.assertEqual(items, [("Vita 20", 0.95, 620, 6, True)])
        self.assertEqual(len(fallback_calls), 1)


if __name__ == "__main__":
    unittest.main()
