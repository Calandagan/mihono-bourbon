from __future__ import annotations

import time

import numpy as np

from module.umamusume.scenario.mant import inventory as _inventory
from module.umamusume.scenario.mant.actions import use_item_and_update_inventory
from module.umamusume.scenario.mant.item_targets import item_option, selected_item
from module.umamusume.scenario.mant.policy import (
    get_date_weighted_score_percentile,
    get_stat_only_percentile,
    is_critical_low_energy,
    has_charm,
    has_energy_recovery,
    has_whistle,
    pick_best_energy_item,
    pick_training_recovery_item,
    remaining_training_turns_real,
)

MEGAPHONE_TIERS = _inventory.MEGAPHONE_TIERS
MEGAPHONE_CONFIG_KEYS = _inventory.MEGAPHONE_CONFIG_KEYS
TRAINING_TYPE_ANKLET = _inventory.TRAINING_TYPE_ANKLET
MEGA_STAT_MULT = _inventory.MEGA_STAT_MULT
TRAINING_NAMES = ["Speed", "Stamina", "Power", "Guts", "Wit"]


def _owned_map(ctx):
    return {n: q for n, q in getattr(ctx.cultivate_detail, 'mant_owned_items', [])}


def _ensure_item_fail_state(ctx):
    current_date = int(getattr(ctx.cultivate_detail.turn_info, 'date', 0) or 0)
    if getattr(ctx.cultivate_detail, 'mant_failed_use_turn', None) != current_date:
        ctx.cultivate_detail.mant_failed_use_turn = current_date
        ctx.cultivate_detail.mant_failed_use_items = set()
        ctx.cultivate_detail.mant_item_use_error_pending = False


def _item_failed(ctx, item_name):
    _ensure_item_fail_state(ctx)
    return item_name in getattr(ctx.cultivate_detail, 'mant_failed_use_items', set())


def _mark_item_failed(ctx, item_name):
    _ensure_item_fail_state(ctx)
    ctx.cultivate_detail.mant_failed_use_items.add(item_name)
    ctx.cultivate_detail.mant_item_use_error_pending = True


def _clear_item_failed(ctx, item_name):
    _ensure_item_fail_state(ctx)
    failed = getattr(ctx.cultivate_detail, 'mant_failed_use_items', set())
    if item_name in failed:
        failed.discard(item_name)
    if not failed:
        ctx.cultivate_detail.mant_item_use_error_pending = False


def _record_item_trace(ctx, *, options=None, selected=None, result=None):
    turn_info = getattr(ctx.cultivate_detail, 'turn_info', None)
    if turn_info is None:
        return
    turn_info.set_item_trace(options=options, selected=selected, result=result)
    turn_info.append_trace(
        "mant_item_policy",
        options_count=len(options or turn_info.item_use_options or []),
        selected=list(selected if selected is not None else turn_info.item_use_selected or []),
        result=dict(result if result is not None else turn_info.item_use_result or {}),
    )


def _favor_value(card) -> int:
    favor = getattr(card, 'favor', 0)
    if hasattr(favor, 'value'):
        try:
            return int(favor.value)
        except Exception:
            return 0
    try:
        return int(favor)
    except Exception:
        return 0


def _best_training_snapshot(ctx):
    scores = getattr(ctx.cultivate_detail.turn_info, 'cached_original_scores', None)
    training_list = getattr(ctx.cultivate_detail.turn_info, 'training_info_list', None)
    if not scores or not training_list or len(scores) != 5 or len(training_list) != 5:
        return None
    try:
        best_idx = int(np.argmax(scores))
    except Exception:
        return None
    ti = training_list[best_idx]
    support_cards = list(getattr(ti, 'support_card_info_list', []) or [])
    high_favor_count = sum(1 for card in support_cards if _favor_value(card) >= 3)
    hint_count = sum(1 for card in support_cards if getattr(card, 'has_event', False))
    stat_gain = (
        max(0, int(getattr(ti, 'speed_incr', 0) or 0))
        + max(0, int(getattr(ti, 'stamina_incr', 0) or 0))
        + max(0, int(getattr(ti, 'power_incr', 0) or 0))
        + max(0, int(getattr(ti, 'will_incr', 0) or 0))
        + max(0, int(getattr(ti, 'intelligence_incr', 0) or 0))
        + max(0.0, float(getattr(ti, 'skill_point_incr', 0) or 0)) * 0.5
    )
    raw_failure_rate = getattr(ti, 'failure_rate', -1)
    try:
        failure_rate = int(raw_failure_rate)
    except Exception:
        failure_rate = -1
    return {
        "idx": best_idx,
        "name": TRAINING_NAMES[best_idx],
        "score": float(scores[best_idx]),
        "stat_gain": float(stat_gain),
        "support_count": len(support_cards),
        "high_favor_count": high_favor_count,
        "hint_count": hint_count,
        "failure_rate": failure_rate,
    }


def _build_failure_recovery_targets(ctx):
    _ensure_item_fail_state(ctx)
    options = []
    selected = []
    current_energy = getattr(ctx.cultivate_detail.turn_info, 'cached_energy', None)
    critical_low = is_critical_low_energy(current_energy)

    charm_failed = _item_failed(ctx, 'Good-Luck Charm')
    charm_available = has_charm(ctx)
    charm_selected = (
        critical_low
        and
        charm_available
        and not charm_failed
        and not getattr(ctx.cultivate_detail.turn_info, 'energy_item_used_this_turn', False)
    )
    options.append(
        item_option(
            "Good-Luck Charm",
            "training_failure_recovery",
            priority=1,
            selected=charm_selected,
            skip_reason=None if charm_selected else (
                "failed_this_turn" if charm_failed else
                "no_owned" if not charm_available else
                "not_critical_low_energy" if not critical_low else
                "energy_already_used"
            ),
            reason="critical_low_energy_prefer_charm" if charm_selected else "not_selected",
            planned_use="training_failure_recovery",
        )
    )
    if charm_selected:
        selected.append(selected_item("Good-Luck Charm"))
        return options, selected, ("charm", "Good-Luck Charm")

    failed_names = set(getattr(ctx.cultivate_detail, 'mant_failed_use_items', set()))
    energy_item_mode = "critical_low" if critical_low else "failure"
    energy_item = pick_training_recovery_item(
        ctx,
        excluded_items=failed_names,
        mode=energy_item_mode,
        current_energy=current_energy,
    )
    energy_selected = bool(energy_item)
    options.append(
        item_option(
            energy_item or "energy_item",
            "training_failure_recovery",
            priority=2,
            selected=energy_selected,
            skip_reason=None if energy_selected else (
                "no_recovery_items" if not has_energy_recovery(ctx) else
                "failed_this_turn_or_not_useful"
            ),
            reason=(
                "critical_low_energy_recovery"
                if energy_selected and critical_low else
                "failure_threshold_recovery"
                if energy_selected else
                "not_selected"
            ),
            planned_use="training_failure_recovery",
        )
    )
    if energy_selected:
        selected.append(selected_item(energy_item))
        return options, selected, ("energy_item", energy_item)

    if not critical_low and charm_available and not charm_failed and not getattr(ctx.cultivate_detail.turn_info, 'energy_item_used_this_turn', False):
        options.append(
            item_option(
                "Good-Luck Charm",
                "training_failure_recovery",
                priority=3,
                selected=True,
                skip_reason=None,
                reason="fallback_charm_after_vitas",
                planned_use="training_failure_recovery",
            )
        )
        selected.append(selected_item("Good-Luck Charm"))
        return options, selected, ("charm", "Good-Luck Charm")

    return options, selected, (None, None)


def choose_training_failure_recovery_action(ctx):
    options, selected, choice = _build_failure_recovery_targets(ctx)
    _record_item_trace(
        ctx,
        options=options,
        selected=selected,
        result={"phase": "training_failure_recovery", "choice": choice[0] or "none"},
    )
    return choice


def _build_megaphone_targets(ctx):
    _ensure_item_fail_state(ctx)
    snapshot = _best_training_snapshot(ctx)
    owned_map = _owned_map(ctx)
    mant_cfg = getattr(ctx.task.detail.scenario_config, 'mant_config', None)
    if snapshot is None or mant_cfg is None:
        return [], [], None

    active_tier = getattr(ctx.cultivate_detail, 'mant_megaphone_tier', 0)
    active_turns = getattr(ctx.cultivate_detail, 'mant_megaphone_turns', 0)
    date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    slots_left = max(0, remaining_training_turns_real(ctx, date))
    total_duration = total_megaphone_turns(owned_map)
    inventory_pressure = slots_left > 0 and sum(int(owned_map.get(name, 0) or 0) for name in MEGAPHONE_TIERS) >= slots_left
    dump_mode = slots_left > 0 and total_duration >= slots_left

    opportunity_score = (
        snapshot["stat_gain"] * 2.0
        + max(0.0, snapshot["score"]) * 12.0
        + snapshot["support_count"] * 6.0
        + snapshot["high_favor_count"] * 10.0
        + snapshot["hint_count"] * 8.0
    )

    thresholds = {
        1: float(getattr(mant_cfg, 'mega_small_threshold', 50)),
        2: float(getattr(mant_cfg, 'mega_medium_threshold', 50)),
        3: float(getattr(mant_cfg, 'mega_large_threshold', 50)),
    }

    options = []
    selected = []
    best_name = None
    best_tier = 0
    for name, (tier, _duration) in sorted(MEGAPHONE_TIERS.items(), key=lambda item: -item[1][0]):
        failed = _item_failed(ctx, name)
        owned_qty = int(owned_map.get(name, 0) or 0)
        eligible = owned_qty > 0 and not failed
        threshold = thresholds[tier]
        if active_turns > 0 and tier <= active_tier:
            eligible = False
            skip_reason = "active_tier_not_upgrade"
        elif not eligible:
            skip_reason = "failed_this_turn" if failed else "no_owned"
        elif dump_mode or inventory_pressure:
            skip_reason = None
        elif opportunity_score >= threshold:
            skip_reason = None
        else:
            skip_reason = "opportunity_below_threshold"

        selected_now = skip_reason is None and best_name is None
        if selected_now:
            best_name = name
            best_tier = tier
            selected.append(selected_item(name))
        options.append(
            item_option(
                name,
                "training_commitment",
                priority=10 - tier,
                selected=selected_now,
                skip_reason=skip_reason,
                reason=(
                    "dump_mode" if selected_now and (dump_mode or inventory_pressure) else
                    "high_value_training" if selected_now else
                    "not_selected"
                ),
                planned_use="training_commitment",
                debug={
                    "opportunity_score": round(opportunity_score, 2),
                    "threshold": round(threshold, 2),
                    "active_tier": active_tier,
                    "slots_left": slots_left,
                    "dump_mode": dump_mode,
                    "inventory_pressure": inventory_pressure,
                    "best_training": snapshot["name"],
                },
            )
        )
    return options, selected, (best_name, best_tier)


def handle_training_whistle(ctx):
    mant_cfg = getattr(ctx.task.detail.scenario_config, 'mant_config', None)
    if mant_cfg is None:
        return False

    threshold = getattr(mant_cfg, 'whistle_threshold', None)
    if threshold is None:
        return False

    score_history = getattr(ctx.cultivate_detail, 'score_history', [])
    if len(score_history) < 16:
        return False

    scores = getattr(ctx.cultivate_detail.turn_info, 'cached_original_scores', None)
    if not scores or len(scores) != 5:
        return False

    best_score = max(scores)
    prev = score_history[:-1]
    below_count = sum(1 for s in prev if s < best_score)
    percentile = below_count / len(prev) * 100

    effective_threshold = float(threshold)
    if mant_cfg.whistle_focus_summer:
        date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
        from module.umamusume.constants.game_constants import CLASSIC_YEAR_END, is_summer_camp_period

        if is_summer_camp_period(date):
            if date <= CLASSIC_YEAR_END:
                effective_threshold += mant_cfg.focus_summer_classic
            else:
                effective_threshold += mant_cfg.focus_summer_senior

    if percentile >= effective_threshold:
        return False

    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    if owned_map.get('Reset Whistle', 0) <= 0:
        return False

    return use_item_and_update_inventory(ctx, 'Reset Whistle')


def handle_energy_item(ctx, item_name=None, *, mode: str = "failure"):
    _ensure_item_fail_state(ctx)
    if item_name is None:
        item_name = pick_training_recovery_item(
            ctx,
            excluded_items=getattr(ctx.cultivate_detail, 'mant_failed_use_items', set()),
            mode=mode,
            current_energy=getattr(ctx.cultivate_detail.turn_info, 'cached_energy', None),
        )
    if item_name is None:
        _record_item_trace(
            ctx,
            options=[{
                "name": "energy_item",
                "context": "energy_recovery",
                "priority": 1,
                "selected": False,
                "skip_reason": "no_useful_energy_item",
                "reason": "not_selected",
            }],
            selected=[],
            result={"phase": "energy_recovery", "result": "skip"},
        )
        return False
    ctx.cultivate_detail.turn_info.energy_item_used = True
    ctx.cultivate_detail.turn_info.energy_item_used_this_turn = True
    ctx.cultivate_detail.turn_info.post_item_rescan_needed = True
    ok = use_item_and_update_inventory(ctx, item_name)
    if ok:
        _clear_item_failed(ctx, item_name)
    else:
        _mark_item_failed(ctx, item_name)
    _record_item_trace(
        ctx,
        options=[{
            "name": item_name,
            "context": "energy_recovery",
            "priority": 1,
            "selected": True,
            "skip_reason": None,
            "reason": "selected",
        }],
        selected=[{"name": item_name, "use_num": 1}],
        result={"phase": "energy_recovery", "result": "ok" if ok else "failed", "item": item_name},
    )
    return ok


def handle_energy_recovery(ctx, item_name=None, *, mode: str = "failure"):
    current_energy = getattr(ctx.cultivate_detail.turn_info, 'cached_energy', None)
    if current_energy is None:
        return False
    current_energy = int(current_energy)

    max_energy = getattr(ctx.cultivate_detail, 'mant_max_energy', 100)
    if item_name is None:
        item_name = pick_training_recovery_item(ctx, mode=mode, current_energy=current_energy)
    if item_name is None:
        return False

    raw_energy = _inventory.ENERGY_ITEMS.get(item_name, 0)
    predicted_energy = min(max_energy, current_energy + raw_energy)
    ok = handle_energy_item(ctx, item_name=item_name, mode=mode)
    if not ok:
        return False

    ctx.cultivate_detail.turn_info.cached_energy = predicted_energy
    ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
    _inventory.log.info(f"Used one energy item for re-evaluation: {item_name} ({current_energy}% -> {predicted_energy}%)")
    return True


def handle_charm(ctx, force=False):
    mant_cfg = getattr(ctx.task.detail.scenario_config, 'mant_config', None)
    if mant_cfg is None:
        return False

    if getattr(ctx.cultivate_detail.turn_info, 'energy_item_used_this_turn', False):
        _inventory.log.info("Skipping Good-Luck Charm because an energy item was already used this turn")
        return False

    _ensure_item_fail_state(ctx)
    owned_map = _owned_map(ctx)
    if owned_map.get('Good-Luck Charm', 0) <= 0:
        return False
    if _item_failed(ctx, 'Good-Luck Charm'):
        return False

    if force:
        result = use_item_and_update_inventory(ctx, 'Good-Luck Charm')
        if result:
            ctx.cultivate_detail.turn_info.charm_used_this_turn = True
            ctx.cultivate_detail.turn_info.post_item_rescan_needed = True
            _clear_item_failed(ctx, 'Good-Luck Charm')
        else:
            _mark_item_failed(ctx, 'Good-Luck Charm')
        return result

    snapshot = _best_training_snapshot(ctx)
    if snapshot is None:
        return False
    fr = int(snapshot.get('failure_rate', -1))
    charm_failure_rate = getattr(mant_cfg, 'charm_failure_rate', 21)
    if fr < charm_failure_rate:
        return False

    result = use_item_and_update_inventory(ctx, 'Good-Luck Charm')
    if result:
        ctx.cultivate_detail.turn_info.charm_used_this_turn = True
        ctx.cultivate_detail.turn_info.post_item_rescan_needed = True
        _clear_item_failed(ctx, 'Good-Luck Charm')
    else:
        _mark_item_failed(ctx, 'Good-Luck Charm')
    return result


def rescan_training(ctx):
    _inventory.close_items_panel(ctx)
    ctx.cultivate_detail.turn_info.parse_train_info_finish = False
    ctx.cultivate_detail.turn_info.turn_operation = None
    ctx.cultivate_detail.last_decision_stats = None
    from module.umamusume.asset.point import RETURN_TO_CULTIVATE_MAIN_MENU

    ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
    time.sleep(0.5)
    from module.umamusume.script.cultivate_task.main_menu_handler import request_training_select
    request_training_select(ctx, reason="training rescan")


def whistle_loop(ctx, start_date):
    if not ctx.task.running():
        return False
    if getattr(ctx.cultivate_detail.turn_info, 'date', None) != start_date:
        return False
    used = handle_training_whistle(ctx)
    if not used:
        return False
    time.sleep(0.5)
    rescan_training(ctx)
    return True


def save_megaphone_scan_state_and_tick(ctx):
    ctx.cultivate_detail.turn_info._mega_scan_tier = getattr(ctx.cultivate_detail, 'mant_megaphone_tier', 0)
    ctx.cultivate_detail.turn_info._mega_scan_turns = getattr(ctx.cultivate_detail, 'mant_megaphone_turns', 0)
    tick_megaphone(ctx)


def megaphone_reevaluate(ctx, current_op):
    pre_item_tier = getattr(ctx.cultivate_detail.turn_info, 'pre_item_tier', None)
    pre_item_turns = getattr(ctx.cultivate_detail.turn_info, 'pre_item_turns', None)
    if pre_item_tier is None or pre_item_turns is None:
        return False

    post_item_tier = getattr(ctx.cultivate_detail, 'mant_megaphone_tier', 0)
    post_item_turns = getattr(ctx.cultivate_detail, 'mant_megaphone_turns', 0)

    if post_item_tier == pre_item_tier and post_item_turns == pre_item_turns:
        return False

    scan_tier = getattr(ctx.cultivate_detail.turn_info, '_mega_scan_tier', 0)
    scan_turns = getattr(ctx.cultivate_detail.turn_info, '_mega_scan_turns', 0)
    old_mult = MEGA_STAT_MULT.get(scan_tier, 1.0) if scan_turns > 1 else 1.0
    new_mult = MEGA_STAT_MULT.get(post_item_tier, 1.0) if post_item_turns > 0 else 1.0

    if new_mult == old_mult:
        return False

    ratio = new_mult / old_mult
    cached_stat_scores = getattr(ctx.cultivate_detail.turn_info, 'cached_stat_scores', None)
    cached_scores = getattr(ctx.cultivate_detail.turn_info, 'cached_computed_scores', None)
    cached_mults = getattr(ctx.cultivate_detail.turn_info, 'cached_facility_mults', None)
    if not cached_stat_scores or not cached_scores or len(cached_stat_scores) != 5 or len(cached_scores) != 5:
        return False

    buffed_scores = []
    for bi in range(5):
        mult = cached_mults[bi] if cached_mults and len(cached_mults) == 5 else 1.0
        delta = cached_stat_scores[bi] * (ratio - 1.0) * mult
        buffed_scores.append(cached_scores[bi] + delta)

    buffed_max = max(buffed_scores)
    eps = 1e-9
    ties = [bi for bi, bv in enumerate(buffed_scores) if abs(bv - buffed_max) < eps]
    new_chosen = 4 if 4 in ties else (min(ties) if ties else int(np.argmax(buffed_scores)))

    from module.umamusume.define import TrainingType

    new_type = TrainingType(new_chosen + 1)

    if new_type != current_op.training_type:
        current_op.training_type = new_type
        return True
    return False


def count_races_in_window(ctx, duration):
    current_date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    count = 0
    if current_date >= _inventory.MANT_CLIMAX_START - duration:
        for offset in range(duration):
            future_date = current_date + offset
            if future_date >= _inventory.MANT_CLIMAX_START and future_date % 2 == 0:
                count += 1
    extra_races = getattr(ctx.cultivate_detail, 'extra_race_list', [])
    if extra_races:
        from module.umamusume.asset.race_data import get_races_for_period

        for offset in range(1, duration):
            future_date = current_date + offset
            available = get_races_for_period(future_date)
            if any(r in available for r in extra_races):
                count += 1
    return count


def total_megaphone_turns(owned_map):
    total = 0
    for name, (_, duration) in MEGAPHONE_TIERS.items():
        qty = owned_map.get(name, 0)
        total += qty * duration
    return total


def handle_megaphone(ctx):
    mant_cfg = getattr(ctx.task.detail.scenario_config, 'mant_config', None)
    if mant_cfg is None:
        return False

    date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    if date >= _inventory.MANT_CLIMAX_START and date not in _inventory.MANT_CLIMAX_TRAINING_TURNS:
        log.info(f"[MEGAPHONE] Skipping — climax non-training turn (date={date})")
        return False

    owned_map = _owned_map(ctx)
    active_tier = getattr(ctx.cultivate_detail, 'mant_megaphone_tier', 0)
    active_turns = getattr(ctx.cultivate_detail, 'mant_megaphone_turns', 0)
    options, selected, choice = _build_megaphone_targets(ctx)
    best_mega, best_tier = choice
    
    # Log detailed decision info
    snapshot = _best_training_snapshot(ctx)
    if snapshot:
        opportunity_score = (
            snapshot["stat_gain"] * 2.0
            + max(0.0, snapshot["score"]) * 12.0
            + snapshot["support_count"] * 6.0
            + snapshot["high_favor_count"] * 10.0
            + snapshot["hint_count"] * 8.0
        )
        log.info(
            f"[MEGAPHONE] opportunity_score={opportunity_score:.1f} "
            f"best_training={snapshot['name']} stat_gain={snapshot['stat_gain']:.1f} "
            f"score={snapshot['score']:.1f} supports={snapshot['support_count']} "
            f"active_tier={active_tier} active_turns={active_turns} "
            f"owned={ {n: int(owned_map.get(n, 0) or 0) for n in MEGAPHONE_TIERS} }"
        )
    
    if best_mega is None:
        log.info(f"[MEGAPHONE] No megaphone selected — skipping")
        _record_item_trace(
            ctx,
            options=options,
            selected=selected,
            result={"phase": "training_commitment", "result": "skip_megaphone"},
        )
        return False

    _, duration = MEGAPHONE_TIERS[best_mega]
    log.info(f"[MEGAPHONE] Using {best_mega} (tier {best_tier}, {duration} turns)")
    ok = use_item_and_update_inventory(ctx, best_mega)
    if ok:
        ctx.cultivate_detail.mant_megaphone_tier = best_tier
        ctx.cultivate_detail.mant_megaphone_turns = duration
        from module.umamusume.persistence import save_megaphone_state

        save_megaphone_state(best_tier, duration)
        _clear_item_failed(ctx, best_mega)
        log.info(f"[MEGAPHONE] Successfully used {best_mega}")
    else:
        _mark_item_failed(ctx, best_mega)
        log.warning(f"[MEGAPHONE] Failed to use {best_mega}")
    _record_item_trace(
        ctx,
        options=options,
        selected=selected,
        result={"phase": "training_commitment", "result": "ok" if ok else "failed", "item": best_mega},
    )
    return ok


def handle_anklet(ctx):
    mant_cfg = getattr(ctx.task.detail.scenario_config, 'mant_config', None)
    if mant_cfg is None:
        return False

    percentile = get_stat_only_percentile(ctx)
    owned_map = _owned_map(ctx)
    if percentile is None:
        log.info(f"[ANKLET] Skipping — no percentile data")
        _record_item_trace(
            ctx,
            options=[{
                "name": "anklet",
                "context": "training_commitment",
                "priority": 20,
                "selected": False,
                "skip_reason": "no_percentile",
                "reason": "not_selected",
            }],
            result={"phase": "training_commitment", "result": "skip_anklet"},
        )
        return False

    threshold = getattr(mant_cfg, 'training_weights_threshold', 40)
    if percentile < threshold:
        log.info(f"[ANKLET] Skipping — percentile={percentile:.1f} < threshold={threshold}")
        _record_item_trace(
            ctx,
            options=[{
                "name": "anklet",
                "context": "training_commitment",
                "priority": 20,
                "selected": False,
                "skip_reason": "percentile_below_threshold",
                "reason": "not_selected",
            }],
            result={"phase": "training_commitment", "result": "skip_anklet"},
        )
        return False

    turn_info = getattr(ctx.cultivate_detail, 'turn_info', None)
    op = getattr(turn_info, 'turn_operation', None) if turn_info else None
    if op is None:
        log.info(f"[ANKLET] Skipping — no turn operation")
        return False
    training_type = getattr(op, 'training_type', None)
    if training_type is None:
        log.info(f"[ANKLET] Skipping — no training type")
        return False
    training_val = training_type.value if hasattr(training_type, 'value') else int(training_type)

    anklet_name = TRAINING_TYPE_ANKLET.get(training_val)
    if anklet_name is None:
        log.info(f"[ANKLET] Skipping — no anklet for training type {training_val}")
        return False
    
    anklet_qty = int(owned_map.get(anklet_name, 0) or 0)
    log.info(
        f"[ANKLET] percentile={percentile:.1f} threshold={threshold} "
        f"training_type={training_val} anklet={anklet_name} qty={anklet_qty} "
        f"owned={ {n: int(owned_map.get(n, 0) or 0) for n in TRAINING_TYPE_ANKLET.values()} }"
    )
    
    if anklet_qty <= 0:
        log.info(f"[ANKLET] Skipping — no {anklet_name} in inventory")
        _record_item_trace(
            ctx,
            options=[{
                "name": anklet_name,
                "context": "training_commitment",
                "priority": 20,
                "selected": False,
                "skip_reason": "no_owned",
                "reason": "not_selected",
            }],
            result={"phase": "training_commitment", "result": "skip_anklet"},
        )
        return False

    log.info(f"[ANKLET] Using {anklet_name}")
    ok = use_item_and_update_inventory(ctx, anklet_name)
    if ok:
        _clear_item_failed(ctx, anklet_name)
        log.info(f"[ANKLET] Successfully used {anklet_name}")
    else:
        _mark_item_failed(ctx, anklet_name)
        log.warning(f"[ANKLET] Failed to use {anklet_name}")
    _record_item_trace(
        ctx,
        options=[{
            "name": anklet_name,
            "context": "training_commitment",
            "priority": 20,
            "selected": True,
            "skip_reason": None,
            "reason": "selected",
        }],
        selected=[{"name": anklet_name, "use_num": 1}],
        result={"phase": "training_commitment", "result": "ok" if ok else "failed", "item": anklet_name},
    )
    return ok


def tick_megaphone(ctx):
    active_turns = getattr(ctx.cultivate_detail, 'mant_megaphone_turns', 0)
    if active_turns > 0:
        active_turns -= 1
        ctx.cultivate_detail.mant_megaphone_turns = active_turns
        if active_turns <= 0:
            ctx.cultivate_detail.mant_megaphone_tier = 0
        from module.umamusume.persistence import save_megaphone_state

        save_megaphone_state(getattr(ctx.cultivate_detail, 'mant_megaphone_tier', 0), active_turns)


def item_loop(ctx):
    execute_training_commitment_actions(ctx, planned_actions=["megaphone", "anklet"])


def execute_training_commitment_actions(ctx, planned_actions=None, current_op=None):
    start_date = getattr(ctx.cultivate_detail.turn_info, 'date', None)
    if has_whistle(ctx) and whistle_loop(ctx, start_date):
        return True

    actions = [action for action in (planned_actions or []) if action in ("megaphone", "anklet")]
    if not actions:
        actions = ["megaphone", "anklet"]

    used_any = False

    if "megaphone" in actions:
        ctx.cultivate_detail.turn_info.pre_item_tier = getattr(ctx.cultivate_detail, 'mant_megaphone_tier', 0)
        ctx.cultivate_detail.turn_info.pre_item_turns = getattr(ctx.cultivate_detail, 'mant_megaphone_turns', 0)
        used_mega = handle_megaphone(ctx)
        used_any = used_any or used_mega
        if used_mega and current_op is not None:
            megaphone_reevaluate(ctx, current_op)

    if "anklet" in actions:
        used_anklet = handle_anklet(ctx)
        used_any = used_any or used_anklet

    if not used_any:
        _record_item_trace(
            ctx,
            result={"phase": "training_commitment", "result": "no_item_used"},
        )
    return used_any


__all__ = [
    "handle_training_whistle",
    "handle_energy_item",
    "handle_energy_recovery",
    "choose_training_failure_recovery_action",
    "handle_charm",
    "rescan_training",
    "save_megaphone_scan_state_and_tick",
    "megaphone_reevaluate",
    "handle_megaphone",
    "handle_anklet",
    "item_loop",
    "execute_training_commitment_actions",
]
