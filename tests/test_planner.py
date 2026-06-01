import unittest
import logging
import sys
import types
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

sys.modules.setdefault("bot.conn.fetch", types.SimpleNamespace(read_energy=lambda: 0))
sys.modules.setdefault("module.umamusume.context", types.SimpleNamespace(UmamusumeContext=object))
sys.modules.setdefault(
    "module.umamusume.script.cultivate_task.helpers",
    types.SimpleNamespace(should_use_pal_outing_simple=lambda ctx: False),
)
if "module.umamusume.asset" not in sys.modules:
    asset_pkg = types.ModuleType("module.umamusume.asset")
    asset_pkg.__path__ = []
    sys.modules["module.umamusume.asset"] = asset_pkg
sys.modules.setdefault(
    "module.umamusume.asset.race_data",
    types.SimpleNamespace(get_races_for_period=lambda date: []),
)

from module.umamusume.define import ScenarioType, TrainingType, TurnOperationType
from module.umamusume.types import TurnOperation, TurnPlan
from module.umamusume.script.cultivate_task import planner
from module.umamusume.script.cultivate_task import race_policy
from module.umamusume.script.cultivate_task.race_policy import RaceTurnDecision


def _make_ctx(date=1, turn_operation=None):
    return SimpleNamespace(
        cultivate_detail=SimpleNamespace(
            scenario=SimpleNamespace(scenario_type=lambda: ScenarioType.SCENARIO_TYPE_MANT),
            turn_info=SimpleNamespace(
                date=date,
                turn_operation=turn_operation,
                cached_energy=None,
                race_available=False,
                train_available=True,
                rest_available=True,
                trip_available=True,
                skill_available=True,
                medic_room_available=False,
                mant_rival_race_available=False,
            ),
            extra_race_list=[],
            rest_threshold=48,
            mant_race_rejections=set(),
        )
    )


class PlannerTests(unittest.TestCase):
    def test_set_turn_plan_keeps_training_operation_for_scan_transition(self):
        ctx = _make_ctx()
        plan = TurnPlan(
            primary_action="training",
            training_type=TrainingType.TRAINING_TYPE_UNKNOWN,
            requires_training_scan=True,
            reason="need training scan",
        )

        planner.set_turn_plan(ctx, plan)

        self.assertIs(ctx.cultivate_detail.turn_info.turn_plan, plan)
        self.assertIsNone(ctx.cultivate_detail.turn_info.turn_operation)
        self.assertTrue(ctx.cultivate_detail.turn_info.pending_training_scan)

    def test_plan_main_menu_turn_prioritizes_race_turn(self):
        ctx = _make_ctx(date=74)
        with patch.object(planner, "get_race_turn_decision", return_value=RaceTurnDecision(has_race=True, climax_race=True, source="climax_forced")), \
             patch.object(planner, "build_race_pre_actions", return_value=["cleat"]):
            plan = planner.plan_main_menu_turn(ctx)

        self.assertEqual(plan.primary_action, "race")
        self.assertEqual(plan.pre_actions, ["cleat"])
        self.assertFalse(plan.requires_training_scan)
        self.assertEqual(plan.source, "climax_forced")

    def test_plan_training_turn_force_safe_recovery_prefers_rest(self):
        ctx = _make_ctx()
        with patch.object(planner, "should_use_pal_outing_simple", return_value=False):
            plan = planner.plan_training_turn(
                ctx,
                TrainingType.TRAINING_TYPE_SPEED,
                force_safe_recovery=True,
            )

        self.assertEqual(plan.primary_action, "rest")
        self.assertIn("failure limit", plan.reason)

    def test_plan_training_turn_preserves_scored_training_choice(self):
        ctx = _make_ctx()
        ai_operation = TurnOperation()
        ai_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_TRAINING
        ai_operation.training_type = TrainingType.TRAINING_TYPE_INTELLIGENCE

        fake_ai = types.SimpleNamespace(get_operation=lambda _ctx: ai_operation)
        with patch.dict(sys.modules, {"module.umamusume.script.cultivate_task.ai": fake_ai}):
            plan = planner.plan_training_turn(ctx, TrainingType.TRAINING_TYPE_SPEED)

        self.assertEqual(plan.primary_action, "training")
        self.assertEqual(plan.training_type, TrainingType.TRAINING_TYPE_SPEED)

    def test_plan_main_menu_turn_keeps_mant_training_scan_on_low_energy_with_recovery(self):
        ctx = _make_ctx(date=20)
        fake_policy = types.SimpleNamespace(
            has_energy_recovery=lambda _ctx: True,
            has_charm=lambda _ctx: False,
        )
        with patch.object(planner, "get_extra_races_this_turn", return_value=[]), \
             patch.object(planner, "get_scheduled_race_this_turn", return_value=False), \
             patch.object(planner, "get_climax_race_this_turn", return_value=False), \
            patch.object(planner, "get_current_energy", return_value=20), \
            patch.object(planner, "get_rest_threshold", return_value=48), \
            patch.dict(sys.modules, {"module.umamusume.scenario.mant.policy": fake_policy}):
            plan = planner.plan_main_menu_turn(ctx)

        self.assertEqual(plan.primary_action, "training")
        self.assertTrue(plan.requires_training_scan)
        self.assertEqual(plan.pre_actions, [])
        self.assertFalse(plan.requires_replan_after_pre_action)
        self.assertEqual(plan.reason, "low energy MANT training risk evaluation")

    def test_plan_main_menu_turn_keeps_mant_training_scan_on_low_energy_with_charm(self):
        ctx = _make_ctx(date=20)
        fake_policy = types.SimpleNamespace(
            has_energy_recovery=lambda _ctx: False,
            has_charm=lambda _ctx: True,
        )
        with patch.object(planner, "get_extra_races_this_turn", return_value=[]), \
             patch.object(planner, "get_scheduled_race_this_turn", return_value=False), \
             patch.object(planner, "get_climax_race_this_turn", return_value=False), \
            patch.object(planner, "get_current_energy", return_value=20), \
            patch.object(planner, "get_rest_threshold", return_value=48), \
            patch.dict(sys.modules, {"module.umamusume.scenario.mant.policy": fake_policy}):
            plan = planner.plan_main_menu_turn(ctx)

        self.assertEqual(plan.primary_action, "training")
        self.assertTrue(plan.requires_training_scan)
        self.assertEqual(plan.pre_actions, [])
        self.assertFalse(plan.requires_replan_after_pre_action)
        self.assertEqual(plan.reason, "low energy MANT training risk evaluation")

    def test_plan_main_menu_turn_keeps_mant_training_scan_on_low_energy_with_early_charm(self):
        ctx = _make_ctx(date=5)
        fake_policy = types.SimpleNamespace(
            has_energy_recovery=lambda _ctx: False,
            has_charm=lambda _ctx: True,
        )
        with patch.object(planner, "get_extra_races_this_turn", return_value=[]), \
             patch.object(planner, "get_scheduled_race_this_turn", return_value=False), \
             patch.object(planner, "get_climax_race_this_turn", return_value=False), \
            patch.object(planner, "get_current_energy", return_value=20), \
            patch.object(planner, "get_rest_threshold", return_value=48), \
            patch.dict(sys.modules, {"module.umamusume.scenario.mant.policy": fake_policy}):
            plan = planner.plan_main_menu_turn(ctx)

        self.assertEqual(plan.primary_action, "training")
        self.assertTrue(plan.requires_training_scan)
        self.assertEqual(plan.pre_actions, [])
        self.assertFalse(plan.requires_replan_after_pre_action)
        self.assertEqual(plan.reason, "low energy MANT training risk evaluation")

    def test_plan_main_menu_turn_keeps_mant_training_scan_on_low_energy_even_without_recovery_items(self):
        ctx = _make_ctx(date=20)
        fake_policy = types.SimpleNamespace(
            has_energy_recovery=lambda _ctx: False,
            has_charm=lambda _ctx: False,
        )
        with patch.object(planner, "get_extra_races_this_turn", return_value=[]), \
             patch.object(planner, "get_scheduled_race_this_turn", return_value=False), \
             patch.object(planner, "get_climax_race_this_turn", return_value=False), \
             patch.object(planner, "get_current_energy", return_value=20), \
             patch.object(planner, "get_rest_threshold", return_value=48), \
             patch.dict(sys.modules, {"module.umamusume.scenario.mant.policy": fake_policy}):
            plan = planner.plan_main_menu_turn(ctx)

        self.assertEqual(plan.primary_action, "training")
        self.assertTrue(plan.requires_training_scan)
        self.assertEqual(plan.pre_actions, [])
        self.assertFalse(plan.requires_replan_after_pre_action)
        self.assertEqual(plan.reason, "low energy MANT training risk evaluation")

    def test_plan_main_menu_turn_preserves_pending_training_scan_without_training_prebuffs(self):
        ctx = _make_ctx(date=20)
        ctx.cultivate_detail.turn_info.pending_training_scan = True
        with patch.object(planner, "get_current_energy", return_value=80):
            plan = planner.plan_main_menu_turn(ctx)

        self.assertEqual(plan.primary_action, "training")
        self.assertTrue(plan.requires_training_scan)
        self.assertEqual(plan.pre_actions, [])
        self.assertEqual(plan.reason, "pending training scan")

    def test_build_race_pre_actions_does_not_use_energy_item_at_48_percent(self):
        ctx = _make_ctx(date=20)
        fake_policy = types.SimpleNamespace(
            should_use_energy_before_race=lambda _ctx, race_id, current_energy: False,
        )
        with patch.object(planner, "get_current_energy", return_value=48), \
             patch.dict(sys.modules, {"module.umamusume.scenario.mant.policy": fake_policy}):
            actions = planner.build_race_pre_actions(ctx, 2022)

        self.assertNotIn("energy_item", actions)
        self.assertEqual(actions, ["cleat", "energy_drink_max", "glow_sticks"])

    def test_build_race_pre_actions_uses_energy_item_when_policy_requires_it(self):
        ctx = _make_ctx(date=20)
        fake_policy = types.SimpleNamespace(
            should_use_energy_before_race=lambda _ctx, race_id, current_energy: True,
        )
        with patch.object(planner, "get_current_energy", return_value=0), \
             patch.dict(sys.modules, {"module.umamusume.scenario.mant.policy": fake_policy}):
            actions = planner.build_race_pre_actions(ctx, 2022)

        self.assertIn("energy_item", actions)

    def test_get_plannable_race_id_skips_rejected_race(self):
        ctx = _make_ctx(date=20)
        ctx.cultivate_detail.mant_race_rejections = {(20, 1111)}
        with patch("module.umamusume.script.cultivate_task.race_policy.get_extra_races_this_turn", return_value=[1111, 2222]):
            race_id = planner.get_plannable_race_id(ctx)

        self.assertEqual(race_id, 2222)

    def test_get_plannable_race_choice_ignores_rival_hint_without_user_race(self):
        ctx = _make_ctx(date=20)
        ctx.cultivate_detail.turn_info.race_available = True
        ctx.cultivate_detail.turn_info.mant_rival_race_available = True
        with patch("module.umamusume.script.cultivate_task.race_policy.get_extra_races_this_turn", return_value=[]):
            has_race, race_id, candidates = planner.get_plannable_race_choice(ctx)

        self.assertFalse(has_race)
        self.assertEqual(race_id, 0)
        self.assertEqual(candidates, [])

    def test_build_user_race_operation_for_period_uses_configured_race(self):
        ctx = _make_ctx(date=20)
        ctx.cultivate_detail.extra_race_list = [2056, 9999]
        with patch("module.umamusume.script.cultivate_task.race_policy.get_races_for_period", return_value=[1000, 2056]):
            operation = race_policy.build_user_race_operation_for_period(ctx, 20)

        self.assertIsNotNone(operation)
        self.assertEqual(operation.race_id, 2056)
        self.assertEqual(operation.source, "user_extra_race")

    def test_build_user_race_operation_for_period_returns_none_when_no_user_race(self):
        ctx = _make_ctx(date=20)
        ctx.cultivate_detail.extra_race_list = [2056]
        with patch("module.umamusume.script.cultivate_task.race_policy.get_races_for_period", return_value=[1000, 1001]):
            operation = race_policy.build_user_race_operation_for_period(ctx, 20)

        self.assertIsNone(operation)

    def test_plan_main_menu_turn_detects_forced_race_from_ui_state(self):
        ctx = _make_ctx(date=20)
        ctx.cultivate_detail.turn_info.race_available = True
        ctx.cultivate_detail.turn_info.train_available = False
        ctx.cultivate_detail.turn_info.rest_available = False
        ctx.cultivate_detail.turn_info.trip_available = False
        ctx.cultivate_detail.turn_info.skill_available = False
        ctx.cultivate_detail.turn_info.medic_room_available = False

        with patch.object(
            planner,
            "get_race_turn_decision",
            return_value=RaceTurnDecision(has_race=True, forced_race=True, rival_hint=False, source="goal_forced"),
        ), \
             patch.object(planner, "build_race_pre_actions", return_value=["cleat"]):
            plan = planner.plan_main_menu_turn(ctx)

        self.assertEqual(plan.primary_action, "race")
        self.assertEqual(plan.race_id, 0)
        self.assertEqual(plan.pre_actions, ["cleat"])
        self.assertTrue(plan.debug.get("forced_race"))
        self.assertEqual(plan.debug.get("source"), "goal_forced")

    def test_plan_main_menu_turn_not_forced_when_other_actions_exist(self):
        ctx = _make_ctx(date=20)
        ctx.cultivate_detail.turn_info.race_available = True
        ctx.cultivate_detail.turn_info.train_available = True

        fake_policy = types.SimpleNamespace(is_forced_race_turn=lambda _ctx: False)
        with patch.object(planner, "get_extra_races_this_turn", return_value=[]), \
             patch.object(planner, "get_scheduled_race_this_turn", return_value=False), \
             patch.object(planner, "get_climax_race_this_turn", return_value=False), \
             patch.object(planner, "get_current_energy", return_value=80), \
             patch.dict(sys.modules, {"module.umamusume.scenario.mant.policy": fake_policy}):
            plan = planner.plan_main_menu_turn(ctx)

        self.assertEqual(plan.primary_action, "training")
        self.assertTrue(plan.requires_training_scan)


if __name__ == "__main__":
    unittest.main()
