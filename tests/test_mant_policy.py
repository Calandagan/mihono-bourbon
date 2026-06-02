import logging
import sys
import types
import unittest
import importlib.util
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

    sys.modules["colorlog"] = types.SimpleNamespace(ColoredFormatter=_ColoredFormatter)


_dummy_log = types.SimpleNamespace(info=lambda *a, **k: None)
_mant_pkg = types.ModuleType("module.umamusume.scenario.mant")
_mant_pkg.__path__ = [
    str(Path(__file__).resolve().parents[1] / "module" / "umamusume" / "scenario" / "mant")
]
sys.modules["module.umamusume.scenario.mant"] = _mant_pkg
sys.modules.setdefault(
    "module.umamusume.scenario.mant.inventory",
    types.SimpleNamespace(
        ENERGY_ITEMS={"Vita 20": 20, "Vita 40": 40, "Royal Kale Juice": 100},
        CHARM_ITEM="Good-Luck Charm",
        MEGAPHONE_TIERS={
            "Basic Megaphone": (1, 2),
            "Cheer Megaphone": (2, 2),
            "Motivating Megaphone": (3, 3),
        },
        MEGAPHONE_CONFIG_KEYS={
            "Basic Megaphone": "basic_megaphone",
            "Cheer Megaphone": "cheer_megaphone",
            "Motivating Megaphone": "motivating_megaphone",
        },
        TRAINING_TYPE_ANKLET={},
        MEGA_STAT_MULT={1: 1.12, 2: 1.2, 3: 1.3},
        ENERGY_ITEM_SKIP_FAST_PATH_THRESHOLD=2,
        MANT_CLIMAX_START=73,
        MANT_CLIMAX_TRAINING_TURNS=[73, 75, 77],
        MANT_CLIMAX_RACE_TURNS=[74, 76, 78],
        log=_dummy_log,
        calc_effective_energy=lambda item_name, raw_energy, current_energy, period_idx, max_energy: raw_energy,
    ),
)
_mant_pkg.inventory = sys.modules["module.umamusume.scenario.mant.inventory"]
sys.modules.setdefault(
    "module.umamusume.scenario.mant.actions",
    types.SimpleNamespace(use_item_and_update_inventory=lambda *a, **k: True),
)
sys.modules["module.umamusume.asset.race_data"] = types.SimpleNamespace(
    is_g1_race=lambda race_id: int(race_id or 0) >= 2000,
    get_races_for_period=lambda period: [],
)

_policy_path = Path(__file__).resolve().parents[1] / "module" / "umamusume" / "scenario" / "mant" / "policy.py"
_policy_spec = importlib.util.spec_from_file_location("test_mant_policy_module", _policy_path)
policy = importlib.util.module_from_spec(_policy_spec)
assert _policy_spec is not None and _policy_spec.loader is not None
_policy_spec.loader.exec_module(policy)
sys.modules["module.umamusume.scenario.mant.policy"] = policy

_shop_policy_path = Path(__file__).resolve().parents[1] / "module" / "umamusume" / "scenario" / "mant" / "shop_policy.py"
_shop_policy_spec = importlib.util.spec_from_file_location("test_mant_shop_policy_module", _shop_policy_path)
shop_policy = importlib.util.module_from_spec(_shop_policy_spec)
assert _shop_policy_spec is not None and _shop_policy_spec.loader is not None
_shop_policy_spec.loader.exec_module(shop_policy)

_training_recovery_path = Path(__file__).resolve().parents[1] / "module" / "umamusume" / "scenario" / "mant" / "training_recovery.py"
_training_recovery_spec = importlib.util.spec_from_file_location("test_mant_training_recovery_module", _training_recovery_path)
training_recovery = importlib.util.module_from_spec(_training_recovery_spec)
assert _training_recovery_spec is not None and _training_recovery_spec.loader is not None
_training_recovery_spec.loader.exec_module(training_recovery)

_race_prep_path = Path(__file__).resolve().parents[1] / "module" / "umamusume" / "scenario" / "mant" / "race_prep.py"
_race_prep_spec = importlib.util.spec_from_file_location("test_mant_race_prep_module", _race_prep_path)
race_prep = importlib.util.module_from_spec(_race_prep_spec)
assert _race_prep_spec is not None and _race_prep_spec.loader is not None
_race_prep_spec.loader.exec_module(race_prep)


class MantPolicyTests(unittest.TestCase):
    def test_coin_cap_defaults_follow_turn_windows(self):
        self.assertEqual(policy.get_mant_coin_cap(10), 999999)
        self.assertEqual(policy.get_mant_coin_cap(40), 260)
        self.assertEqual(policy.get_mant_coin_cap(70), 80)
        self.assertEqual(policy.get_mant_coin_cap(75), 0)

    def test_coin_reserve_reduces_when_budget_is_far_above_cap(self):
        self.assertEqual(policy.get_mant_coin_reserve(40, 500), 120)
        self.assertEqual(policy.get_mant_coin_reserve(68, 350), 40)

    def test_buy_floor_for_stat_books_is_more_aggressive_than_general_items(self):
        stat_floor = policy.get_mant_shop_buy_floor("Speed Scroll", 3, 40, 500, 100)
        general_floor = policy.get_mant_shop_buy_floor("Good-Luck Charm", 3, 40, 500, 100)
        self.assertEqual(stat_floor, 40)
        self.assertEqual(general_floor, 60)
        self.assertLess(stat_floor, general_floor)

    def test_buy_floor_goes_to_zero_late_for_stat_books(self):
        self.assertEqual(policy.get_mant_shop_buy_floor("Speed Scroll", 3, 50, 220, 100), 0)

    def test_compute_charm_purchase_state_stops_early_when_stock_is_high(self):
        cfg = types.SimpleNamespace(item_tiers={"good-luck_charm": 4})
        effective_tier, charm_stop = shop_policy.compute_charm_purchase_state(55, {"Good-Luck Charm": 2}, cfg)
        self.assertEqual(effective_tier, 2)
        self.assertTrue(charm_stop)

    def test_collect_priority_cure_targets_prefers_specific_cure_first(self):
        targets, bought, budget = shop_policy.collect_priority_cure_targets(
            ["Headache"],
            {},
            {"Rich Hand Cream", "Miracle Cure"},
            100,
            {"Headache": "Rich Hand Cream"},
            "Miracle Cure",
            {"Rich Hand Cream": 15, "Miracle Cure": 40},
        )
        self.assertEqual(targets, ["Rich Hand Cream"])
        self.assertEqual(bought, {"Rich Hand Cream"})
        self.assertEqual(budget, 85)

    def test_pick_training_recovery_item_prefers_vitas_before_juice(self):
        ctx = types.SimpleNamespace(
            cultivate_detail=types.SimpleNamespace(
                mant_owned_items=[
                    ("Royal Kale Juice", 2),
                    ("Vita 20", 5),
                    ("Vita 40", 1),
                ]
            )
        )
        self.assertEqual(policy.pick_training_recovery_item(ctx), "Vita 20")

    def test_pick_training_recovery_item_falls_back_to_juice_last(self):
        ctx = types.SimpleNamespace(
            cultivate_detail=types.SimpleNamespace(
                mant_owned_items=[
                    ("Royal Kale Juice", 2),
                ]
            )
        )
        self.assertEqual(policy.pick_training_recovery_item(ctx), "Royal Kale Juice")

    def test_should_prefer_training_recovery_over_rest_when_low_energy_and_charm_available(self):
        ctx = types.SimpleNamespace(
            cultivate_detail=types.SimpleNamespace(
                rest_threshold=48,
                mant_owned_items=[("Good-Luck Charm", 1)],
                turn_info=types.SimpleNamespace(cached_energy=20),
            )
        )
        self.assertTrue(policy.should_prefer_training_recovery_over_rest(ctx))

    def test_should_prefer_training_recovery_over_rest_is_false_without_items(self):
        ctx = types.SimpleNamespace(
            cultivate_detail=types.SimpleNamespace(
                rest_threshold=48,
                mant_owned_items=[],
                turn_info=types.SimpleNamespace(cached_energy=20),
            )
        )
        self.assertFalse(policy.should_prefer_training_recovery_over_rest(ctx))

    def test_choose_training_failure_recovery_action_prefers_charm_before_energy(self):
        training_info = types.SimpleNamespace(
            support_card_info_list=[],
            failure_rate=18,
            speed_incr=8,
            stamina_incr=0,
            power_incr=0,
            will_incr=0,
            intelligence_incr=0,
            skill_point_incr=0,
        )
        ctx = types.SimpleNamespace(
            task=types.SimpleNamespace(
                detail=types.SimpleNamespace(
                    scenario_config=types.SimpleNamespace(
                        mant_config=types.SimpleNamespace(charm_failure_rate=30)
                    )
                )
            ),
            cultivate_detail=types.SimpleNamespace(
                mant_owned_items=[
                    ("Good-Luck Charm", 1),
                    ("Vita 20", 5),
                ],
                mant_failed_use_turn=None,
                mant_failed_use_items=set(),
                mant_item_use_error_pending=False,
                turn_info=types.SimpleNamespace(
                    date=20,
                    energy_item_used_this_turn=False,
                    cached_original_scores=[1.0, 0.1, 0.1, 0.1, 0.1],
                    training_info_list=[training_info] * 5,
                    set_item_trace=lambda **kwargs: None,
                    append_trace=lambda *args, **kwargs: None,
                ),
            ),
        )

        action, item_name = training_recovery.choose_training_failure_recovery_action(ctx)
        self.assertEqual(action, "charm")
        self.assertEqual(item_name, "Good-Luck Charm")

    def test_compute_bbq_purchase_state_rewards_non_rainbow_pressure(self):
        cfg = types.SimpleNamespace(
            item_tiers={"grilled_carrots": 3},
            bbq_unmaxxed_cards=1,
        )
        portraits = {
            "a": {"is_npc": False, "favor": 2},
            "b": {"is_npc": False, "favor": 3},
            "c": {"is_npc": True, "favor": 0},
        }
        self.assertEqual(shop_policy.compute_bbq_purchase_state(cfg, portraits), 2)

    def test_collect_emergency_cure_targets_adds_specific_then_global_fallback(self):
        targets, bought, budget = shop_policy.collect_emergency_cure_targets(
            ["Headache", "Skin Outbreak"],
            {},
            {"Rich Hand Cream", "Miracle Cure"},
            100,
            {"Headache": "Rich Hand Cream", "Skin Outbreak": "Unknown Cure"},
            "Miracle Cure",
            {"Rich Hand Cream": 15, "Miracle Cure": 40, "Unknown Cure": 30},
            existing_targets=[],
            bought_this_cycle=set(),
        )
        self.assertEqual(targets, ["Rich Hand Cream", "Miracle Cure"])
        self.assertEqual(bought, {"Rich Hand Cream", "Miracle Cure"})
        self.assertEqual(budget, 45)

    def test_should_skip_shop_item_enforces_stock_caps(self):
        skipped = shop_policy.should_skip_shop_item(
            "Motivating Megaphone",
            priority_set=set(),
            one_time_buff_items=set(),
            used_buffs=set(),
            ignore_cat=False,
            ignore_carrots=False,
            display_to_slug=lambda name: name.lower().replace(" ", "_"),
            all_cures={"Rich Hand Cream"},
            has_miracle_cure=False,
            owned_map={"Motivating Megaphone": 3},
            ailment_cure_all="Miracle Cure",
            deck_counts={1: 1, 2: 1, 3: 1, 4: 1, 5: 1},
        )
        self.assertTrue(skipped)

    def test_should_skip_shop_item_treats_cleats_as_contextual_only(self):
        skipped = shop_policy.should_skip_shop_item(
            "Master Cleat Hammer",
            priority_set=set(),
            one_time_buff_items=set(),
            used_buffs=set(),
            ignore_cat=False,
            ignore_carrots=False,
            display_to_slug=lambda name: name.lower().replace(" ", "_"),
            all_cures={"Rich Hand Cream"},
            has_miracle_cure=False,
            owned_map={},
            ailment_cure_all="Miracle Cure",
            deck_counts={1: 1, 2: 1, 3: 1, 4: 1, 5: 1},
        )
        self.assertTrue(skipped)

    def test_should_skip_shop_item_does_not_reject_training_items_when_deck_info_is_unknown(self):
        skipped = shop_policy.should_skip_shop_item(
            "Speed Ankle Weights",
            priority_set=set(),
            one_time_buff_items=set(),
            used_buffs=set(),
            ignore_cat=False,
            ignore_carrots=False,
            display_to_slug=lambda name: name.lower().replace(" ", "_"),
            all_cures={"Rich Hand Cream"},
            has_miracle_cure=False,
            owned_map={},
            ailment_cure_all="Miracle Cure",
            deck_counts={1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
        )
        self.assertFalse(skipped)

    def test_specific_cure_is_not_blocked_just_because_miracle_exists(self):
        skipped = shop_policy.should_skip_shop_item(
            "Rich Hand Cream",
            priority_set=set(),
            one_time_buff_items=set(),
            used_buffs=set(),
            ignore_cat=False,
            ignore_carrots=False,
            display_to_slug=lambda name: name.lower().replace(" ", "_"),
            all_cures={"Rich Hand Cream"},
            has_miracle_cure=True,
            owned_map={"Miracle Cure": 1},
            ailment_cure_all="Miracle Cure",
            deck_counts={1: 1, 2: 1, 3: 1, 4: 1, 5: 1},
        )
        self.assertFalse(skipped)

    def test_build_emergency_expiring_targets_respects_ui_tier_and_stock_caps(self):
        cfg = types.SimpleNamespace(
            tier_count=4,
            item_tiers={"motivating_megaphone": 2, "grilled_carrots": 3},
            tier_thresholds={2: 0, 3: 0},
        )
        targets, _budget = shop_policy.build_emergency_expiring_targets(
            current_date=40,
            budget=200,
            shop_items=[
                ("Motivating Megaphone", 1.0, 10, 1, True),
                ("Grilled Carrots", 1.0, 20, 1, True),
            ],
            mant_cfg=cfg,
            owned_map={"Motivating Megaphone": 3},
            deck_counts={1: 1, 2: 1, 3: 1, 4: 1, 5: 1},
            used_buffs=set(),
            one_time_buff_items=set(),
            ignore_grilled_carrots=False,
            shop_item_costs={"Motivating Megaphone": 55, "Grilled Carrots": 40},
            slug_to_display={"motivating_megaphone": "Motivating Megaphone", "grilled_carrots": "Grilled Carrots"},
            display_to_slug=lambda name: {
                "Motivating Megaphone": "motivating_megaphone",
                "Grilled Carrots": "grilled_carrots",
            }[name],
            detected_portraits_log={"a": {"is_npc": False, "favor": 1}},
            ailment_cure_map={},
            ailment_cure_all="Miracle Cure",
        )
        self.assertEqual(targets, ["Grilled Carrots"])

    def test_choose_cleat_for_race_prefers_master_on_climax_turn(self):
        selected = race_prep.choose_cleat_for_race(
            74,
            0,
            {"Artisan Cleat Hammer": 1, "Master Cleat Hammer": 1},
            is_climax_override=True,
        )
        self.assertEqual(selected, "Master Cleat Hammer")

    def test_choose_cleat_for_race_uses_spare_artisan_first_on_regular_race(self):
        selected = race_prep.choose_cleat_for_race(
            50,
            2056,
            {"Artisan Cleat Hammer": 3, "Master Cleat Hammer": 2},
        )
        self.assertEqual(selected, "Artisan Cleat Hammer")

    def test_build_emergency_expiring_targets_stops_after_first_valid_tier(self):
        cfg = types.SimpleNamespace(
            tier_count=4,
            item_tiers={"motivating_megaphone": 1, "grilled_carrots": 2},
            tier_thresholds={1: 0, 2: 0},
        )
        targets, _budget = shop_policy.build_emergency_expiring_targets(
            current_date=40,
            budget=200,
            shop_items=[
                ("Motivating Megaphone", 1.0, 10, 1, True),
                ("Grilled Carrots", 1.0, 20, 1, True),
            ],
            mant_cfg=cfg,
            owned_map={},
            deck_counts={1: 1, 2: 1, 3: 1, 4: 1, 5: 1},
            used_buffs=set(),
            one_time_buff_items=set(),
            ignore_grilled_carrots=False,
            shop_item_costs={"Motivating Megaphone": 55, "Grilled Carrots": 40},
            slug_to_display={"motivating_megaphone": "Motivating Megaphone", "grilled_carrots": "Grilled Carrots"},
            display_to_slug=lambda name: {
                "Motivating Megaphone": "motivating_megaphone",
                "Grilled Carrots": "grilled_carrots",
            }[name],
            detected_portraits_log={"a": {"is_npc": False, "favor": 1}},
            ailment_cure_map={},
            ailment_cure_all="Miracle Cure",
        )
        self.assertEqual(targets, ["Motivating Megaphone"])

    def test_choose_cleat_for_race_prefers_spare_artisan_on_normal_race(self):
        selected = race_prep.choose_cleat_for_race(
            60,
            1234,
            {"Master Cleat Hammer": 2, "Artisan Cleat Hammer": 1},
        )
        self.assertEqual(selected, "Artisan Cleat Hammer")

    def test_would_cleat_be_useful_before_race_detects_useful_purchase(self):
        useful = race_prep.would_cleat_be_useful_before_race(
            "Artisan Cleat Hammer",
            1234,
            60,
            {"Master Cleat Hammer": 2, "Artisan Cleat Hammer": 0},
        )
        self.assertTrue(useful)


if __name__ == "__main__":
    unittest.main()
