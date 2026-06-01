from __future__ import annotations

from dataclasses import dataclass, field

from module.umamusume.asset.race_data import get_races_for_period
from module.umamusume.define import ScenarioType, TurnOperationType
from module.umamusume.types import TurnOperation


@dataclass
class RaceTurnDecision:
    has_race: bool = False
    race_id: int = 0
    source: str = "none"
    candidates: list[dict] = field(default_factory=list)
    scheduled_race: bool = False
    climax_race: bool = False
    forced_race: bool = False
    rival_hint: bool = False


def is_mant(ctx) -> bool:
    try:
        return ctx.cultivate_detail.scenario.scenario_type() == ScenarioType.SCENARIO_TYPE_MANT
    except Exception:
        return False


def get_extra_races_this_turn(ctx) -> list[int]:
    date = ctx.cultivate_detail.turn_info.date
    available = get_races_for_period(date)
    return [race_id for race_id in ctx.cultivate_detail.extra_race_list if race_id in available]


def get_user_races_for_period(ctx, period: int) -> list[int]:
    available = get_races_for_period(period)
    return [race_id for race_id in getattr(ctx.cultivate_detail, "extra_race_list", []) if race_id in available]


def build_user_race_operation_for_period(ctx, period: int, source: str = "user_extra_race") -> TurnOperation | None:
    races = get_user_races_for_period(ctx, period)
    if not races:
        return None
    operation = TurnOperation()
    operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_RACE
    operation.race_id = int(races[0])
    operation.source = source
    return operation


def get_scheduled_race_this_turn(ctx) -> bool:
    if not is_mant(ctx):
        return False
    try:
        from module.umamusume.scenario.mant.policy import has_scheduled_race_this_turn

        return has_scheduled_race_this_turn(ctx)
    except Exception:
        return False


def get_climax_race_this_turn(ctx) -> bool:
    if not is_mant(ctx):
        return False
    try:
        from module.umamusume.scenario.mant.race_prep import MANT_CLIMAX_RACE_TURNS

        return int(ctx.cultivate_detail.turn_info.date) in MANT_CLIMAX_RACE_TURNS
    except Exception:
        return False


def is_forced_race_turn(ctx) -> bool:
    if not is_mant(ctx):
        return False
    try:
        from module.umamusume.scenario.mant.policy import is_forced_race_turn as policy_fn

        return bool(policy_fn(ctx))
    except Exception:
        return False


def get_plannable_race_choice(ctx) -> tuple[bool, int, list[dict]]:
    extra = get_extra_races_this_turn(ctx)
    date = getattr(ctx.cultivate_detail.turn_info, "date", 0)
    rejected = getattr(ctx.cultivate_detail, "mant_race_rejections", set())
    candidates = []
    if extra:
        for race_id in extra:
            rejected_now = (date, race_id) in rejected
            candidates.append({"race_id": race_id, "kind": "extra", "source": "user_extra_race", "rejected": rejected_now})
            if not rejected_now:
                return True, race_id, candidates

    return False, 0, candidates


def get_race_turn_decision(ctx) -> RaceTurnDecision:
    has_race, race_id, candidates = get_plannable_race_choice(ctx)
    scheduled_race = get_scheduled_race_this_turn(ctx)
    climax_race = get_climax_race_this_turn(ctx)
    forced_race = is_forced_race_turn(ctx)
    rival_hint = bool(getattr(ctx.cultivate_detail.turn_info, "mant_rival_race_available", False))
    if has_race or scheduled_race or climax_race or forced_race:
        source = "user_extra_race" if (has_race or scheduled_race) else "goal_forced"
        if climax_race:
            source = "climax_forced"
        elif forced_race:
            source = "goal_forced"
        combined_candidates = list(candidates or [])
        combined_candidates.append({
            "race_id": int(race_id or 0),
            "source": source,
            "scheduled_race": bool(scheduled_race),
            "climax_race": bool(climax_race),
            "forced_race": bool(forced_race),
            "rival_hint": bool(rival_hint),
            "rejected": False,
        })
        return RaceTurnDecision(
            has_race=True,
            race_id=int(race_id or 0),
            source=source,
            candidates=combined_candidates,
            scheduled_race=bool(scheduled_race),
            climax_race=bool(climax_race),
            forced_race=bool(forced_race),
            rival_hint=bool(rival_hint),
        )
    return RaceTurnDecision()


__all__ = [
    "RaceTurnDecision",
    "is_mant",
    "get_extra_races_this_turn",
    "get_user_races_for_period",
    "build_user_race_operation_for_period",
    "get_scheduled_race_this_turn",
    "get_climax_race_this_turn",
    "is_forced_race_turn",
    "get_plannable_race_choice",
    "get_race_turn_decision",
]
