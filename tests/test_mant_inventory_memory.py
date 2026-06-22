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
_inventory_spec = importlib.util.spec_from_file_location("test_mant_inventory_module", _inventory_path)
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


_actions_path = (
    Path(__file__).resolve().parents[1]
    / "module"
    / "umamusume"
    / "scenario"
    / "mant"
    / "actions.py"
)
_actions_spec = importlib.util.spec_from_file_location("test_mant_actions_module", _actions_path)
actions = importlib.util.module_from_spec(_actions_spec)
assert _actions_spec is not None and _actions_spec.loader is not None
_mant_pkg = types.ModuleType("module.umamusume.scenario.mant")
_mant_pkg.inventory = inventory
with patch.dict(
    sys.modules,
    {
        "module.umamusume.scenario.mant": _mant_pkg,
        "module.umamusume.scenario.mant.inventory": inventory,
        "module.umamusume.scenario.mant.item_targets": types.SimpleNamespace(
            item_option=lambda *a, **k: {},
            selected_item=lambda name: {"name": name},
        ),
    },
):
    _actions_spec.loader.exec_module(actions)


class MantInventoryMemoryTests(unittest.TestCase):
    def test_use_training_item_does_not_delete_local_inventory_when_full_search_misses(self):
        ctx = types.SimpleNamespace(
            cultivate_detail=types.SimpleNamespace(
                mant_owned_items=[("Master Cleat Hammer", 1), ("Artisan Cleat Hammer", 2)],
                mant_inventory_rescan_pending=False,
            )
        )

        with patch.object(inventory, "open_items_panel", return_value=True), \
             patch.object(inventory, "try_click_item_plus_once", return_value=(False, True)), \
             patch.object(inventory, "close_items_panel", return_value=None):
            ok = inventory.use_training_item(ctx, "Master Cleat Hammer", 1)

        self.assertFalse(ok)
        self.assertEqual(
            ctx.cultivate_detail.mant_owned_items,
            [("Master Cleat Hammer", 1), ("Artisan Cleat Hammer", 2)],
        )
        self.assertTrue(ctx.cultivate_detail.mant_inventory_rescan_pending)

    def test_use_item_wrapper_removes_stale_local_inventory_after_full_search_miss(self):
        ctx = types.SimpleNamespace(
            cultivate_detail=types.SimpleNamespace(
                mant_owned_items=[("Motivating Megaphone", 1), ("Vita 20", 1)],
                mant_inventory_rescan_pending=False,
                mant_last_full_search_missing_items=[],
            )
        )

        def miss_item(_ctx, item_name, _qty):
            _ctx.cultivate_detail.mant_last_full_search_missing_items = [item_name]
            return False

        with patch.object(actions._inventory, "use_training_item", side_effect=miss_item), \
             patch.dict(
                 sys.modules,
                 {
                     "module.umamusume.persistence": types.SimpleNamespace(save_inventory=lambda *_a, **_k: None),
                     "module.umamusume.context": types.SimpleNamespace(log_detected_items=lambda *_a, **_k: None),
                 },
             ):
            ok = actions.use_item_and_update_inventory(ctx, "Motivating Megaphone")

        self.assertFalse(ok)
        self.assertEqual(ctx.cultivate_detail.mant_owned_items, [("Vita 20", 1)])

    def test_batch_use_removes_stale_local_inventory_after_full_search_miss(self):
        ctx = types.SimpleNamespace(
            cultivate_detail=types.SimpleNamespace(
                mant_owned_items=[("Motivating Megaphone", 1), ("Power Ankle Weights", 1)],
                mant_inventory_rescan_pending=False,
            )
        )

        with patch.object(
            actions._inventory,
            "use_training_items",
            return_value={
                "selected": [],
                "not_found": ["Motivating Megaphone"],
                "fully_searched_missing": ["Motivating Megaphone"],
                "confirmed": False,
            },
        ), patch.dict(
            sys.modules,
            {
                "module.umamusume.persistence": types.SimpleNamespace(save_inventory=lambda *_a, **_k: None),
                "module.umamusume.context": types.SimpleNamespace(log_detected_items=lambda *_a, **_k: None),
            },
        ):
            result = actions.use_items_and_update_inventory(ctx, ["Motivating Megaphone"])

        self.assertFalse(result["confirmed"])
        self.assertEqual(ctx.cultivate_detail.mant_owned_items, [("Power Ankle Weights", 1)])

    def test_instant_use_full_search_miss_removes_stale_local_inventory(self):
        ctx = types.SimpleNamespace(
            ctrl=types.SimpleNamespace(),
            cultivate_detail=types.SimpleNamespace(
                mant_owned_items=[("Pretty Mirror", 1)],
                mant_inventory_rescan_pending=False,
                turn_info=types.SimpleNamespace(
                    item_use_options=[],
                    item_use_selected=[],
                    item_use_result={},
                    set_item_trace=lambda **_k: None,
                    append_trace=lambda *_a, **_k: None,
                ),
            ),
        )

        with patch.object(actions._inventory, "open_items_panel", return_value=True), \
             patch.object(actions._inventory, "try_click_item_plus_once", return_value=(False, True)), \
             patch.object(actions._inventory, "close_items_panel", return_value=None), \
             patch.dict(
                 sys.modules,
                 {
                     "module.umamusume.persistence": types.SimpleNamespace(
                         save_inventory=lambda *_a, **_k: None,
                         mark_buff_used=lambda *_a, **_k: None,
                         is_buff_used=lambda *_a, **_k: False,
                     ),
                     "module.umamusume.context": types.SimpleNamespace(log_detected_items=lambda *_a, **_k: None),
                 },
             ):
            ok = actions.handle_instant_use_items(ctx)

        self.assertFalse(ok)
        self.assertEqual(ctx.cultivate_detail.mant_owned_items, [])
        self.assertTrue(ctx.cultivate_detail.mant_inventory_rescan_pending)


if __name__ == "__main__":
    unittest.main()
