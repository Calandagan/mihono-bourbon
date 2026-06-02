from __future__ import annotations

from module.umamusume.scenario.mant import inventory as _inventory
from module.umamusume.scenario.mant.constants import display_to_slug

ENERGY_ITEMS = _inventory.ENERGY_ITEMS
CHARM_ITEM = _inventory.CHARM_ITEM
TRAINING_RECOVERY_ITEM_PRIORITY = (
    "Vita 20",
    "Vita 40",
    "Vita 65",
    "Royal Kale Juice",
)


def _cfg_get(cfg, key, default):
    if cfg is None:
        return default
    if isinstance(cfg, dict):
        return cfg.get(key, default)
    return getattr(cfg, key, default)


def is_mant_stat_book(display_name: str) -> bool:
    slug = display_to_slug(display_name or "")
    return slug.endswith("_notepad") or slug.endswith("_manual") or slug.endswith("_scroll")


def get_mant_coin_cap(turn: int, cfg=None) -> int:
    turn = int(turn or 0)
    if turn <= 20:
        default = 999999
        key = "mant_coin_cap_t20"
    elif turn <= 35:
        default = 300
        key = "mant_coin_cap_t35"
    elif turn <= 45:
        default = 260
        key = "mant_coin_cap_t45"
    elif turn <= 55:
        default = 200
        key = "mant_coin_cap_t55"
    elif turn <= 64:
        default = 140
        key = "mant_coin_cap_t64"
    elif turn <= 72:
        default = 80
        key = "mant_coin_cap_t72"
    else:
        default = 0
        key = "mant_coin_cap_final"
    return int(_cfg_get(cfg, key, default) or default)


def get_mant_coin_reserve(turn: int, budget: int, cfg=None) -> int:
    turn = int(turn or 0)
    budget = int(budget or 0)
    if turn <= 20:
        reserve = 160
    elif turn <= 35:
        reserve = 220
    elif turn <= 45:
        reserve = 180
    elif turn <= 55:
        reserve = 120
    elif turn <= 64:
        reserve = 80
    elif turn <= 72:
        reserve = 40
    else:
        reserve = 0

    reserve = int(_cfg_get(cfg, "mant_coin_reserve", reserve) if cfg is not None else reserve)
    cap = get_mant_coin_cap(turn, cfg)
    if cap and budget > cap:
        reserve = min(reserve, max(0, cap // 2))
    if turn >= 73:
        return 0
    if turn >= 65 and budget > 300:
        return min(reserve, 40)
    if turn >= 56 and budget > 220:
        return min(reserve, 60)
    if turn >= 46 and budget > 260:
        return min(reserve, 80)
    if turn >= 36 and budget > 320:
        return min(reserve, 120)
    return max(0, int(reserve))


def get_mant_shop_buy_floor(display_name: str, tier: int, turn: int, start_budget: int, threshold: int, cfg=None) -> int:
    tier = int(tier or 0)
    turn = int(turn or 0)
    start_budget = int(start_budget or 0)
    threshold = int(threshold or 0)

    reserve = get_mant_coin_reserve(turn, start_budget, cfg)
    cap = get_mant_coin_cap(turn, cfg)
    floor = max(threshold, reserve) if tier > 1 else 0

    if is_mant_stat_book(display_name):
        if turn >= 46:
            return 0
        if turn >= 36 and start_budget > cap:
            return min(floor, 40)
        if start_budget > cap:
            return min(floor, reserve // 2)
        return min(floor, reserve)

    if turn >= 73:
        return 0
    if cap and start_budget > cap:
        floor = min(floor, max(0, reserve // 2))
    if start_budget >= reserve + 400:
        floor = min(floor, max(0, reserve // 3))
    elif start_budget >= reserve + 250:
        floor = min(floor, max(0, reserve // 2))
    if turn >= 65:
        floor = min(floor, 40)
    elif turn >= 56:
        floor = min(floor, 80)
    elif turn >= 46:
        floor = min(floor, 120)
    return max(0, int(floor))


def pick_best_energy_item(ctx, excluded_items=None):
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    excluded = set(excluded_items or [])
    current_energy = getattr(ctx.cultivate_detail.turn_info, 'cached_energy', 0)
    if current_energy is None:
        return None
    current_energy = int(current_energy)
    max_energy = getattr(ctx.cultivate_detail, 'mant_max_energy', 100)
    energy_use_max = max_energy * 0.55
    energy_result_min = max_energy * 0.3
    energy_score_threshold = max_energy * 0.1
    if current_energy >= energy_use_max:
        return None

    date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    from module.umamusume.asset.race_data import get_races_for_period
    from module.umamusume.constants.game_constants import get_date_period_index

    period_idx = get_date_period_index(date)

    for offset in range(1, 5):
        future_date = date + offset
        available = get_races_for_period(future_date)
        if any(r in ctx.cultivate_detail.extra_race_list for r in available):
            break

    candidate_pools = [
        [(name, raw) for name, raw in ENERGY_ITEMS.items() if name != 'Royal Kale Juice'],
        [(name, raw) for name, raw in ENERGY_ITEMS.items() if name == 'Royal Kale Juice'],
    ]

    best_item = None
    best_effective = 0
    for pool in candidate_pools:
        best_item = None
        best_effective = 0
        for item_name, raw_energy in pool:
            if item_name in excluded:
                continue
            if owned_map.get(item_name, 0) <= 0:
                continue
            result_energy = current_energy + raw_energy
            if result_energy < energy_result_min:
                continue
            effective = _inventory.calc_effective_energy(item_name, raw_energy, current_energy, period_idx, max_energy)
            if effective > best_effective:
                best_effective = effective
                best_item = item_name
        if best_item is not None:
            break
    if best_effective < energy_score_threshold:
        return None
    return best_item


def pick_training_recovery_item(ctx, excluded_items=None):
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    excluded = set(excluded_items or [])
    for item_name in TRAINING_RECOVERY_ITEM_PRIORITY:
        if item_name in excluded:
            continue
        if int(owned_map.get(item_name, 0) or 0) > 0:
            return item_name
    return None


def has_energy_recovery(ctx):
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    return any(owned_map.get(item_name, 0) > 0 for item_name in ENERGY_ITEMS)


def has_charm(ctx):
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    return owned_map.get('Good-Luck Charm', 0) > 0


def should_prefer_training_recovery_over_rest(ctx, current_energy: int | None = None) -> bool:
    if current_energy is None:
        current_energy = getattr(ctx.cultivate_detail.turn_info, 'cached_energy', None)
    if current_energy is None:
        return False
    try:
        current_energy = int(current_energy)
    except Exception:
        return False

    try:
        threshold = int(
            getattr(
                ctx.cultivate_detail,
                'rest_threshold',
                getattr(
                    ctx.cultivate_detail,
                    'rest_treshold',
                    getattr(ctx.cultivate_detail, 'fast_path_energy_limit', 48),
                ),
            )
        )
    except Exception:
        threshold = 48

    if current_energy > threshold:
        return False

    return has_charm(ctx) or has_energy_recovery(ctx)


def should_use_energy_before_race(ctx, race_id: int = 0, current_energy: int | None = None) -> bool:
    if current_energy is None:
        current_energy = getattr(ctx.cultivate_detail.turn_info, 'cached_energy', 0)
    if current_energy is None:
        return False
    try:
        current_energy = int(current_energy)
    except Exception:
        return False

    if current_energy > 0:
        return False

    return has_energy_recovery(ctx)


def has_whistle(ctx):
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    return owned_map.get('Reset Whistle', 0) > 0


def has_cupcakes(ctx):
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    return owned_map.get('Plain Cupcake', 0) > 0 or owned_map.get('Berry Sweet Cupcake', 0) > 0


def get_chain_position(ctx) -> tuple[int, int]:
    chain_map = getattr(ctx.cultivate_detail, 'race_chain_map', {})
    date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    return chain_map.get(date, (1, 1))


def has_scheduled_race_this_turn(ctx) -> bool:
    chain_map = getattr(ctx.cultivate_detail, 'race_chain_map', {})
    date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    return date in chain_map


def get_best_percentile(ctx):
    scores = getattr(ctx.cultivate_detail.turn_info, 'cached_original_scores', None)
    if not scores or len(scores) != 5:
        return None
    score_history = getattr(ctx.cultivate_detail, 'score_history', [])
    if len(score_history) < 16:
        return None
    best_score = max(scores)
    prev = score_history[:-1]
    below_count = sum(1 for s in prev if s < best_score)
    return below_count / len(prev) * 100


def get_stat_only_percentile(ctx):
    scores = getattr(ctx.cultivate_detail.turn_info, 'cached_original_scores', None)
    if not scores or len(scores) != 5:
        return None
    stat_only_history = getattr(ctx.cultivate_detail, 'stat_only_history', [])
    if len(stat_only_history) < 16:
        return None
    best_score = getattr(ctx.cultivate_detail.turn_info, 'cached_stat_only_score', None)
    if best_score is None:
        return None
    prev = stat_only_history[:-1]
    below_count = sum(1 for s in prev if s < best_score)
    return below_count / len(prev) * 100


def get_date_weighted_score_percentile(ctx):
    score_history = getattr(ctx.cultivate_detail, 'score_history', [])
    date_history = getattr(ctx.cultivate_detail, 'date_history', [])
    if len(score_history) < 8 or len(date_history) != len(score_history):
        return get_stat_only_percentile(ctx)

    current_date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    scores = getattr(ctx.cultivate_detail.turn_info, 'cached_original_scores', None)
    if not scores or len(scores) != 5:
        return 50.0
    current_score = max(scores)

    mega_tier = getattr(ctx.cultivate_detail, 'mant_megaphone_tier', 0)
    mega_turns = getattr(ctx.cultivate_detail, 'mant_megaphone_turns', 0)
    if mega_turns > 0:
        mult = _inventory.MEGA_STAT_MULT.get(mega_tier, 1.0)
        current_score /= mult

    weighted_below = 0.0
    weighted_total = 0.0
    for i in range(len(score_history) - 1):
        d = date_history[i]
        distance = abs(d - current_date)
        weight = 1.0 / (1.0 + distance)
        if distance > 12:
            continue
        weighted_total += weight
        if score_history[i] < current_score:
            weighted_below += weight

    if weighted_total <= 0:
        return 50.0
    return weighted_below / weighted_total * 100


def remaining_training_turns_real(ctx, date):
    if date >= _inventory.MANT_CLIMAX_START:
        clim_turns = [73, 74, 75, 76, 77, 78]
        training_count = 0
        for t in clim_turns:
            if t >= date and t % 2 == 1:
                training_count += 1
        return training_count
    extra_races = getattr(ctx.cultivate_detail, 'extra_race_list', [])
    if not extra_races:
        return (_inventory.MANT_CLIMAX_START - date) + len(_inventory.MANT_CLIMAX_TRAINING_TURNS)

    from module.umamusume.asset.race_data import get_races_for_period

    races_in_window = 0
    for future_date in range(date, _inventory.MANT_CLIMAX_START):
        available = get_races_for_period(future_date)
        if any(r in extra_races for r in available):
            races_in_window += 1

    total_turns = (_inventory.MANT_CLIMAX_START - date) + len(_inventory.MANT_CLIMAX_TRAINING_TURNS)
    return total_turns - races_in_window


def should_skip_fast_path(ctx):
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    has_charm_item = owned_map.get(CHARM_ITEM, 0) > 0
    energy_count = sum(owned_map.get(item, 0) for item in ENERGY_ITEMS)
    has_mood_item = owned_map.get('Plain Cupcake', 0) > 0 or owned_map.get('Berry Sweet Cupcake', 0) > 0
    if has_charm_item:
        return True
    if energy_count >= _inventory.ENERGY_ITEM_SKIP_FAST_PATH_THRESHOLD:
        return True
    if has_mood_item:
        return True
    return False


def should_skip_race(ctx):
    mant_cfg = getattr(ctx.task.detail.scenario_config, 'mant_config', None)
    if mant_cfg is None:
        return False
    skip_pct = getattr(mant_cfg, 'skip_race_percentile', 0)
    if skip_pct <= 0:
        return False
    pct_hist = getattr(ctx.cultivate_detail, 'percentile_history', [])
    if len(pct_hist) < 16 or not pct_hist:
        return False
    last_pct = pct_hist[-1]

    active_tier = getattr(ctx.cultivate_detail, 'mant_megaphone_tier', 0)
    active_turns = getattr(ctx.cultivate_detail, 'mant_megaphone_turns', 0)
    effective_skip_pct = skip_pct
    if active_turns > 0 and active_tier > 0:
        mega_mult = _inventory.MEGA_STAT_MULT.get(active_tier, 1.0)
        bonus_pct = (mega_mult - 1.0) * 100
        effective_skip_pct = max(0, skip_pct - bonus_pct)

    if last_pct > effective_skip_pct:
        _inventory.log.info(
            f"skipping optional race: percentile {last_pct:.0f}% > threshold {effective_skip_pct:.0f}%"
            + (f" (megaphone t{active_tier} active)" if active_tier > 0 else "")
        )
        return True
    return False


def is_forced_race_turn(ctx) -> bool:
    turn_info = getattr(ctx.cultivate_detail, "turn_info", None)
    if turn_info is None:
        return False
    race_available = bool(getattr(turn_info, "race_available", False))
    if not race_available:
        return False
    other_available = any(
        bool(getattr(turn_info, attr, False))
        for attr in ("train_available", "rest_available", "trip_available", "skill_available", "medic_room_available")
    )
    return not other_available


__all__ = [
    "ENERGY_ITEMS",
    "CHARM_ITEM",
    "is_mant_stat_book",
    "get_mant_coin_cap",
    "get_mant_coin_reserve",
    "get_mant_shop_buy_floor",
    "pick_best_energy_item",
    "pick_training_recovery_item",
    "has_energy_recovery",
    "has_charm",
    "should_prefer_training_recovery_over_rest",
    "should_use_energy_before_race",
    "has_whistle",
    "has_cupcakes",
    "get_chain_position",
    "has_scheduled_race_this_turn",
    "remaining_training_turns_real",
    "get_best_percentile",
    "get_stat_only_percentile",
    "get_date_weighted_score_percentile",
    "should_skip_fast_path",
    "should_skip_race",
    "is_forced_race_turn",
]
