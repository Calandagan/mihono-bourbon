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


_main_menu_path = (
    Path(__file__).resolve().parents[1]
    / "module"
    / "umamusume"
    / "scenario"
    / "mant"
    / "main_menu.py"
)
_main_menu_spec = importlib.util.spec_from_file_location("test_mant_main_menu_module", _main_menu_path)
main_menu = importlib.util.module_from_spec(_main_menu_spec)
assert _main_menu_spec is not None and _main_menu_spec.loader is not None
_bot_base_pkg = types.ModuleType("bot.base")
_bot_base_log = types.SimpleNamespace(
    get_logger=lambda _name: types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
)
_bot_base_pkg.log = _bot_base_log
with patch.dict(
    sys.modules,
    {
        "cv2": types.SimpleNamespace(),
        "bot.base": _bot_base_pkg,
        "bot.base.log": _bot_base_log,
        "bot.recog.image_matcher": types.SimpleNamespace(image_match=lambda *a, **k: None),
        "bot.recog.ocr": types.SimpleNamespace(ocr_line=lambda *a, **k: ""),
        "module.umamusume.asset.template": types.SimpleNamespace(REF_MANT_ON_SALE=object()),
        "module.umamusume.scenario.mant.item_targets": types.SimpleNamespace(
            item_option=lambda *a, **k: {},
            selected_item=lambda name: {"name": name},
        ),
    },
):
    _main_menu_spec.loader.exec_module(main_menu)


class MantMainMenuTests(unittest.TestCase):
    def test_handle_mant_turn_start_decrements_shop_turns_only_once_per_date(self):
        ctx = types.SimpleNamespace(
            cultivate_detail=types.SimpleNamespace(
                mant_shop_last_chunk=2,
                mant_shop_items=[("Artisan Cleat Hammer", 1.0, 10, 4, True)],
            )
        )

        shop_stub = types.SimpleNamespace(
            is_shop_scan_turn=lambda date: True,
            current_shop_chunk=lambda date: 2,
        )
        context_stub = types.SimpleNamespace(log_detected_shop_items=lambda *_: None)

        with patch.dict(
            sys.modules,
            {
                "module.umamusume.scenario.mant.shop": shop_stub,
                "module.umamusume.context": context_stub,
            },
        ):
            main_menu.handle_mant_turn_start(ctx, 21)
            self.assertEqual(ctx.cultivate_detail.mant_shop_items[0][3], 3)
            main_menu.handle_mant_turn_start(ctx, 21)

        self.assertEqual(ctx.cultivate_detail.mant_shop_items[0][3], 3)

    def test_merge_scanned_inventory_preserves_unseen_local_items(self):
        ctx = types.SimpleNamespace(
            cultivate_detail=types.SimpleNamespace(
                mant_owned_items=[("Artisan Cleat Hammer", 1), ("Vita 20", 1)]
            )
        )
        persistence_stub = types.SimpleNamespace(save_inventory=lambda *_: None)
        context_stub = types.SimpleNamespace(log_detected_items=lambda *_: None)
        with patch.dict(
            sys.modules,
            {
                "module.umamusume.persistence": persistence_stub,
                "module.umamusume.context": context_stub,
            },
        ):
            merged = main_menu._merge_scanned_inventory_with_local(
                ctx,
                [("Vita 20", 1), ("Motivating Megaphone", 2)],
            )

        self.assertEqual(
            merged,
            [
                ("Artisan Cleat Hammer", 1),
                ("Motivating Megaphone", 2),
                ("Vita 20", 1),
            ],
        )

    def test_apply_shop_purchase_to_local_inventory_increments_selected_items(self):
        ctx = types.SimpleNamespace(
            cultivate_detail=types.SimpleNamespace(
                mant_owned_items=[("Vita 20", 1), ("Artisan Cleat Hammer", 1)]
            )
        )
        persistence_stub = types.SimpleNamespace(save_inventory=lambda *_: None)
        context_stub = types.SimpleNamespace(log_detected_items=lambda *_: None)
        with patch.dict(
            sys.modules,
            {
                "module.umamusume.persistence": persistence_stub,
                "module.umamusume.context": context_stub,
            },
        ):
            updated = main_menu._apply_shop_purchase_to_local_inventory(
                ctx,
                ["Artisan Cleat Hammer", "Power Ankle Weights"],
            )

        self.assertEqual(
            updated,
            [
                ("Artisan Cleat Hammer", 2),
                ("Power Ankle Weights", 1),
                ("Vita 20", 1),
            ],
        )

    def test_coin_triggered_buy_tracks_chunk_on_cultivate_detail(self):
        ctx = types.SimpleNamespace(
            cultivate_detail=types.SimpleNamespace(
                mant_coins=768,
                mant_coin_buy_last_chunk=-1,
                turn_info=types.SimpleNamespace(),
            )
        )
        game_constants_stub = types.SimpleNamespace(SUMMER_CAMP_2_END=50)
        shop_stub = types.SimpleNamespace(is_shop_scan_turn=lambda date: True)
        with patch.dict(
            sys.modules,
            {
                "module.umamusume.constants.game_constants": game_constants_stub,
                "module.umamusume.scenario.mant.shop": shop_stub,
            },
        ):
            with patch.object(main_menu, "handle_mant_emergency_shop_buys", return_value=True) as emergency_buy:
                result = main_menu.handle_mant_coin_triggered_buy(ctx, 44)

        self.assertTrue(result)
        self.assertEqual(ctx.cultivate_detail.mant_coin_buy_last_chunk, (44 - 13) // 3)
        emergency_buy.assert_called_once_with(ctx, 44)

    def test_emergency_shop_buy_opens_shop_before_buying_cached_targets(self):
        calls = []

        def _open_shop(_ctx):
            calls.append("open")
            return True

        def _buy_shop_items(_ctx, targets, _items):
            calls.append(("buy", list(targets)))
            return True, {"selected": list(targets)}

        ctx = types.SimpleNamespace(
            task=types.SimpleNamespace(
                detail=types.SimpleNamespace(
                    scenario_config=types.SimpleNamespace(
                        mant_config=types.SimpleNamespace(item_tiers={"artisan_cleat_hammer": 1})
                    ),
                    pal_card_store={},
                )
            ),
            ctrl=types.SimpleNamespace(trigger_decision_reset=False),
            cultivate_detail=types.SimpleNamespace(
                mant_coins=500,
                mant_owned_items=[],
                mant_shop_items=[("Artisan Cleat Hammer", 1.0, 10, 2, True)],
                turn_info=types.SimpleNamespace(mant_emergency_shop_done=False, set_shop_trace=lambda **_: None),
                mant_inventory_rescan_pending=False,
                mant_afflictions=[],
            ),
        )

        shop_stub = types.SimpleNamespace(
            is_shop_scan_turn=lambda date: True,
            open_mant_shop=_open_shop,
            buy_shop_items=_buy_shop_items,
            SHOP_ITEM_COSTS={"Artisan Cleat Hammer": 25},
            SLUG_TO_DISPLAY={"artisan_cleat_hammer": "Artisan Cleat Hammer"},
            display_to_slug=lambda name: {"Artisan Cleat Hammer": "artisan_cleat_hammer"}[name],
            BACK_BTN_X=0,
            BACK_BTN_Y=0,
        )
        constants_stub = types.SimpleNamespace(AILMENT_CURE_MAP={}, AILMENT_CURE_ALL="Miracle Cure")
        shop_policy_stub = types.SimpleNamespace(
            build_emergency_expiring_targets=lambda **kwargs: (["Artisan Cleat Hammer"], kwargs["budget"]),
            collect_emergency_cure_targets=lambda *args, **kwargs: ([], set(), kwargs.get("budget", args[3])),
            get_deck_type_counts=lambda _store: {},
            is_shop_item_disabled=lambda *args, **kwargs: False,
        )
        context_stub = types.SimpleNamespace(
            detected_portraits_log={},
            log_detected_items=lambda *_: None,
            log_detected_shop_items=lambda *_: None,
        )
        persistence_stub = types.SimpleNamespace(
            get_ignore_grilled_carrots=lambda: False,
            get_used_buffs=lambda: set(),
            save_inventory=lambda *_: None,
        )
        actions_stub = types.SimpleNamespace(ONE_TIME_BUFF_ITEMS=set())

        with patch.dict(
            sys.modules,
            {
                "module.umamusume.scenario.mant.shop": shop_stub,
                "module.umamusume.scenario.mant.constants": constants_stub,
                "module.umamusume.scenario.mant.shop_policy": shop_policy_stub,
                "module.umamusume.context": context_stub,
                "module.umamusume.persistence": persistence_stub,
                "module.umamusume.scenario.mant.actions": actions_stub,
            },
        ):
            result = main_menu.handle_mant_emergency_shop_buys(ctx, 44)

        self.assertTrue(result)
        self.assertEqual(calls, ["open", ("buy", ["Artisan Cleat Hammer"])])
        self.assertEqual(dict(ctx.cultivate_detail.mant_owned_items).get("Artisan Cleat Hammer"), 1)

    def test_shop_scan_targets_only_affordable_items_after_priority_cures(self):
        captured_targets = []

        def _buy_shop_items(_ctx, targets, _items):
            captured_targets.extend(targets)
            return True, {"selected": list(targets)}

        mant_cfg = types.SimpleNamespace(
            item_tiers={
                "speed_manual": 1,
                "vita_20": 1,
                "grilled_carrots": 1,
            },
            tier_count=1,
        )
        turn_info = types.SimpleNamespace(
            set_shop_trace=lambda **_k: None,
            append_trace=lambda *_a, **_k: None,
            parse_main_menu_finish=True,
        )
        ctx = types.SimpleNamespace(
            task=types.SimpleNamespace(
                detail=types.SimpleNamespace(
                    scenario_config=types.SimpleNamespace(mant_config=mant_cfg),
                    pal_card_store={},
                )
            ),
            ctrl=types.SimpleNamespace(get_screen=lambda **_k: None, trigger_decision_reset=False),
            cultivate_detail=types.SimpleNamespace(
                mant_shop_scanned_this_turn=False,
                mant_shop_last_chunk=-1,
                mant_coins=112,
                mant_owned_items=[],
                mant_inventory_rescan_pending=False,
                mant_afflictions=[],
                turn_info=turn_info,
            ),
        )
        items_list = [
            ("Miracle Cure", 1.0, 500, 6, True),
            ("Speed Manual", 1.0, 620, 6, True),
            ("Vita 20", 1.0, 700, 6, True),
            ("Grilled Carrots", 1.0, 780, 6, True),
        ]
        shop_stub = types.SimpleNamespace(
            is_shop_scan_turn=lambda date: True,
            scan_mant_shop=lambda _ctx: items_list,
            buy_shop_items=_buy_shop_items,
            SHOP_ITEM_COSTS={
                "Miracle Cure": 40,
                "Speed Manual": 15,
                "Vita 20": 35,
                "Grilled Carrots": 40,
            },
            SLUG_TO_DISPLAY={
                "speed_manual": "Speed Manual",
                "vita_20": "Vita 20",
                "grilled_carrots": "Grilled Carrots",
            },
            display_to_slug=lambda name: {
                "Miracle Cure": "miracle_cure",
                "Speed Manual": "speed_manual",
                "Vita 20": "vita_20",
                "Grilled Carrots": "grilled_carrots",
            }[name],
            current_shop_chunk=lambda date: 6,
        )
        constants_stub = types.SimpleNamespace(AILMENT_CURE_MAP={}, AILMENT_CURE_ALL="Miracle Cure")
        shop_policy_stub = types.SimpleNamespace(
            collect_shop_turns=lambda items: {name: turns for name, _c, _g, turns, _b in items},
            collect_priority_cure_targets=lambda *args, **kwargs: (["Miracle Cure"], {"Miracle Cure"}, 72),
            get_deck_type_counts=lambda _store: {},
            get_shop_item_ui_tier=lambda _cfg, _slug, default=None: 1,
            get_shop_stock_state=lambda _name, _owned: (0, None),
            is_shop_item_disabled=lambda *args, **kwargs: False,
            should_skip_shop_item=lambda *args, **kwargs: False,
        )
        policy_stub = types.SimpleNamespace(
            get_mant_coin_cap=lambda *_a, **_k: 260,
            get_mant_coin_reserve=lambda *_a, **_k: 180,
        )
        context_stub = types.SimpleNamespace(
            log_detected_items=lambda *_a, **_k: None,
            log_detected_shop_items=lambda *_a, **_k: None,
        )
        persistence_stub = types.SimpleNamespace(
            get_used_buffs=lambda: set(),
            get_ignore_cat_food=lambda: False,
            get_ignore_grilled_carrots=lambda: False,
            save_inventory=lambda *_a, **_k: None,
        )
        actions_stub = types.SimpleNamespace(ONE_TIME_BUFF_ITEMS=set())

        with patch.dict(
            sys.modules,
            {
                "module.umamusume.scenario.mant.shop": shop_stub,
                "module.umamusume.scenario.mant.constants": constants_stub,
                "module.umamusume.scenario.mant.policy": policy_stub,
                "module.umamusume.scenario.mant.shop_policy": shop_policy_stub,
                "module.umamusume.context": context_stub,
                "module.umamusume.persistence": persistence_stub,
                "module.umamusume.scenario.mant.actions": actions_stub,
            },
        ):
            result = main_menu.handle_mant_shop_scan(ctx, 37)

        self.assertTrue(result)
        self.assertEqual(captured_targets, ["Miracle Cure", "Speed Manual", "Vita 20"])


if __name__ == "__main__":
    unittest.main()
