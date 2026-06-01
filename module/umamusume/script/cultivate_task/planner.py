from __future__ import annotations

from typing import Iterable

import bot.base.log as logger
from bot.conn.fetch import read_energy
from module.umamusume.constants.game_constants import is_summer_camp_period
from module.umamusume.constants.scoring_constants import DEFAULT_REST_THRESHOLD
from module.umamusume.context import UmamusumeContext
from module.umamusume.define import ScenarioType, TrainingType, TurnOperationType
from module.umamusume.script.cultivate_task.helpers import should_use_pal_outing_simple
from module.umamusume.script.cultivate_task.race_policy import (
    get_climax_race_this_turn,
    get_extra_races_this_turn,
    get_plannable_race_choice,
    get_race_turn_decision,
    get_scheduled_race_this_turn,
    is_forced_race_turn,
)
from module.umamusume.types import TurnOperation, TurnPlan

log = logger.get_logger(__name__)


def is_mant(ctx: UmamusumeContext) -> bool:
    try:
        return ctx.cultivate_detail.scenario.scenario_type() == ScenarioType.SCENARIO_TYPE_MANT
    except Exception:
        return False


def get_rest_threshold(ctx: UmamusumeContext) -> int:
    try:
        return int(
            getattr(
                ctx.cultivate_detail,
                "rest_threshold",
                getattr(
                    ctx.cultivate_detail,
                    "rest_treshold",
                    getattr(
                        ctx.cultivate_detail,
                        "fast_path_energy_limit",
                        DEFAULT_REST_THRESHOLD,
                    ),
                ),
            )
        )
    except Exception:
        return DEFAULT_REST_THRESHOLD


def get_current_energy(ctx: UmamusumeContext) -> int:
    cached = getattr(ctx.cultivate_detail.turn_info, "cached_energy", None)
    if cached is not None:
        try:
            return int(cached)
        except Exception:
            pass
    energy = read_energy()
    ctx.cultivate_detail.turn_info.cached_energy = energy
    return int(energy or 0)


def get_plannable_race_id(ctx: UmamusumeContext) -> int:
    has_race, race_id, candidates = get_plannable_race_choice(ctx)
    if hasattr(ctx.cultivate_detail.turn_info, "set_race_trace") and candidates:
        ctx.cultivate_detail.turn_info.set_race_trace(candidates=candidates)
    return race_id if has_race else 0


def turn_operation_to_plan(turn_operation: TurnOperation | None) -> TurnPlan | None:
    if turn_operation is None:
        return None
    mapping = {
        TurnOperationType.TURN_OPERATION_TYPE_TRAINING: "training",
        TurnOperationType.TURN_OPERATION_TYPE_REST: "rest",
        TurnOperationType.TURN_OPERATION_TYPE_MEDIC: "medic",
        TurnOperationType.TURN_OPERATION_TYPE_TRIP: "trip",
        TurnOperationType.TURN_OPERATION_TYPE_RACE: "race",
    }
    primary = mapping.get(turn_operation.turn_operation_type)
    if primary is None:
        return None
    return TurnPlan(
        primary_action=primary,
        training_type=getattr(turn_operation, "training_type", TrainingType.TRAINING_TYPE_UNKNOWN),
        race_id=getattr(turn_operation, "race_id", 0) or 0,
        source=getattr(turn_operation, "source", "") or "",
        reason="from turn_operation",
    )


def set_turn_plan(ctx: UmamusumeContext, plan: TurnPlan | None) -> None:
    turn_info = ctx.cultivate_detail.turn_info
    turn_info.turn_plan = plan
    if plan is None:
        turn_info.turn_operation = None
        turn_info.pending_training_scan = False
        if hasattr(turn_info, "append_trace"):
            turn_info.append_trace("turn_plan", action=None, reason="cleared")
        return
    plan.log()
    if hasattr(turn_info, "append_trace"):
        turn_info.append_trace(
            "turn_plan",
            action=plan.primary_action,
            training_type=getattr(plan.training_type, "name", str(plan.training_type)),
            race_id=plan.race_id,
            source=plan.source,
            pre_actions=list(plan.pre_actions or []),
            requires_training_scan=bool(plan.requires_training_scan),
            requires_replan_after_pre_action=bool(plan.requires_replan_after_pre_action),
            reason=plan.reason,
            debug=dict(getattr(plan, "debug", {}) or {}),
        )
    if plan.primary_action == "training" and getattr(plan, "requires_training_scan", False):
        turn_info.turn_operation = None
        turn_info.pending_training_scan = True
        return
    turn_info.pending_training_scan = False
    turn_info.turn_operation = plan.to_turn_operation()


def _append_unique(actions: list[str], values: Iterable[str]) -> None:
    for value in values:
        if value and value not in actions:
            actions.append(value)


def build_race_pre_actions(ctx: UmamusumeContext, race_id: int) -> list[str]:
    actions: list[str] = []
    if not is_mant(ctx):
        return actions

    energy = get_current_energy(ctx)
    try:
        from module.umamusume.scenario.mant.policy import should_use_energy_before_race

        if should_use_energy_before_race(ctx, race_id, energy):
            actions.append("energy_item")
    except Exception:
        pass

    _append_unique(actions, ["cleat", "energy_drink_max", "glow_sticks"])
    return actions


def build_training_pre_actions(ctx: UmamusumeContext, training_type: TrainingType) -> list[str]:
    actions: list[str] = []
    if not is_mant(ctx):
        return actions

    if training_type != TrainingType.TRAINING_TYPE_UNKNOWN:
        _append_unique(actions, ["megaphone", "anklet"])
    return actions


def plan_main_menu_turn(ctx: UmamusumeContext) -> TurnPlan:
    turn_info = ctx.cultivate_detail.turn_info
    if getattr(turn_info, "pending_training_scan", False):
        pre_actions = build_training_pre_actions(ctx, TrainingType.TRAINING_TYPE_UNKNOWN)
        return TurnPlan(
            primary_action="training",
            pre_actions=pre_actions,
            requires_training_scan=True,
            requires_replan_after_pre_action=any(action in ("energy_item", "charm") for action in pre_actions),
            reason="pending training scan",
        )
    op_plan = turn_operation_to_plan(turn_info.turn_operation)
    if op_plan is not None:
        if op_plan.primary_action == "race":
            op_plan.pre_actions = build_race_pre_actions(ctx, op_plan.race_id)
        elif op_plan.primary_action == "training":
            op_plan.pre_actions = build_training_pre_actions(ctx, op_plan.training_type)
        op_plan.requires_replan_after_pre_action = any(
            action in ("energy_item", "charm") for action in op_plan.pre_actions
        )
        return op_plan

    race_decision = get_race_turn_decision(ctx)
    if race_decision.has_race:
        if hasattr(turn_info, "set_race_trace"):
            turn_info.set_race_trace(candidates=list(race_decision.candidates or []))
        return TurnPlan(
            primary_action="race",
            race_id=race_decision.race_id,
            source=race_decision.source,
            pre_actions=build_race_pre_actions(ctx, race_decision.race_id),
            requires_replan_after_pre_action=False,
            reason="race turn",
            debug={
                "source": race_decision.source,
                "scheduled_race": bool(race_decision.scheduled_race),
                "climax_race": bool(race_decision.climax_race),
                "forced_race": bool(race_decision.forced_race),
                "rival_hint": bool(race_decision.rival_hint),
                "race_id": int(race_decision.race_id or 0),
            },
        )

    energy = get_current_energy(ctx)
    if energy <= get_rest_threshold(ctx):
        if is_mant(ctx):
            return TurnPlan(
                primary_action="training",
                requires_training_scan=True,
                reason="low energy MANT training risk evaluation",
            )
        if should_use_pal_outing_simple(ctx):
            return TurnPlan(primary_action="trip", reason="low energy with pal outing available")
        return TurnPlan(primary_action="rest", reason="low energy fast path")

    return TurnPlan(
        primary_action="training",
        requires_training_scan=True,
        reason="need training scan",
    )


def plan_training_turn(
    ctx: UmamusumeContext,
    default_training_type: TrainingType,
    force_safe_recovery: bool = False,
) -> TurnPlan:
    if force_safe_recovery:
        if should_use_pal_outing_simple(ctx):
            return TurnPlan(primary_action="trip", reason="all trainings blocked by failure limit")
        return TurnPlan(primary_action="rest", reason="all trainings blocked by failure limit")

    plan = TurnPlan(
        primary_action="training",
        training_type=default_training_type,
        reason="scored training decision",
    )

    if plan.primary_action == "race":
        plan.pre_actions = build_race_pre_actions(ctx, plan.race_id)
    elif plan.primary_action == "training":
        plan.pre_actions = build_training_pre_actions(ctx, plan.training_type)
        plan.requires_replan_after_pre_action = any(
            action in ("energy_item", "charm") for action in plan.pre_actions
        )
    return plan


def execute_mant_pre_action(ctx: UmamusumeContext, action: str, race_id: int = 0) -> bool:
    from module.umamusume.scenario.mant.race_prep import (
        handle_cleat_before_race,
        handle_energy_drink_max_before_race,
        handle_glow_sticks_before_race,
    )
    from module.umamusume.scenario.mant.training_recovery import (
        handle_anklet,
        handle_charm,
        handle_energy_recovery,
        handle_megaphone,
    )

    if action == "energy_item":
        return handle_energy_recovery(ctx)
    if action == "charm":
        return handle_charm(ctx)
    if action == "megaphone":
        return handle_megaphone(ctx)
    if action == "anklet":
        return handle_anklet(ctx)
    if action == "cleat":
        return handle_cleat_before_race(ctx, race_id, is_climax_override=get_climax_race_this_turn(ctx))
    if action == "energy_drink_max":
        return handle_energy_drink_max_before_race(ctx)
    if action == "glow_sticks":
        return handle_glow_sticks_before_race(ctx)
    return False
