from __future__ import annotations

from module.umamusume.scenario.mant import inventory as _inventory
from module.umamusume.scenario.mant.actions import use_item_and_update_inventory
from module.umamusume.scenario.mant.policy import get_chain_position

MANT_CLIMAX_RACE_TURNS = _inventory.MANT_CLIMAX_RACE_TURNS
CLIMAX_CLEAT_RESERVE = 1


def remaining_climax_races(date):
    return sum(1 for t in MANT_CLIMAX_RACE_TURNS if t >= date)


def get_cleat_state(owned_map):
    owned_map = owned_map or {}
    master_qty = int(owned_map.get('Master Cleat Hammer', 0) or 0)
    artisan_qty = int(owned_map.get('Artisan Cleat Hammer', 0) or 0)
    total = master_qty + artisan_qty
    reserve_total = min(CLIMAX_CLEAT_RESERVE, total)
    reserve_master = min(master_qty, reserve_total)
    reserve_artisan = max(0, reserve_total - reserve_master)
    spare_master = max(0, master_qty - reserve_master)
    spare_artisan = max(0, artisan_qty - reserve_artisan)
    return {
        "master_qty": master_qty,
        "artisan_qty": artisan_qty,
        "total": total,
        "reserve_total": reserve_total,
        "reserve_master": reserve_master,
        "reserve_artisan": reserve_artisan,
        "spare_master": spare_master,
        "spare_artisan": spare_artisan,
    }


def choose_cleat_for_race(current_date, race_id, owned_map, *, is_climax_override=False):
    from module.umamusume.asset.race_data import is_g1_race

    state = get_cleat_state(owned_map)
    if state["total"] <= 0:
        return None

    is_climax_race = is_climax_override or current_date in MANT_CLIMAX_RACE_TURNS
    if is_climax_race:
        if state["master_qty"] > 0:
            return 'Master Cleat Hammer'
        if state["artisan_qty"] > 0:
            return 'Artisan Cleat Hammer'
        return None

    if state["spare_artisan"] > 0:
        return 'Artisan Cleat Hammer'
    if state["spare_master"] > 0:
        return 'Master Cleat Hammer'
    if race_id and is_g1_race(race_id):
        return None
    return None


def would_cleat_be_useful_before_race(cleat_name, race_id, current_date, owned_map, *, is_climax_override=False):
    sim = dict(owned_map or {})
    sim[cleat_name] = int(sim.get(cleat_name, 0) or 0) + 1
    return choose_cleat_for_race(
        current_date,
        race_id,
        sim,
        is_climax_override=is_climax_override,
    ) == cleat_name


def handle_energy_drink_max_before_race(ctx):
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    if owned_map.get('Energy Drink MAX', 0) <= 0:
        return False
    current_energy = getattr(ctx.cultivate_detail.turn_info, 'cached_energy', None)
    if current_energy is None:
        return False
    if int(current_energy) > 1:
        return False
    position, _ = get_chain_position(ctx)
    if position > 3:
        _inventory.log.info(f"Race {position} in chain - deferring Energy Drink MAX (only used on races 1-3)")
        return False
    return use_item_and_update_inventory(ctx, 'Energy Drink MAX')


def _get_mant_cfg(ctx):
    return getattr(getattr(ctx.task.detail, 'scenario_config', None), 'mant_config', None)


def _current_race_id(ctx):
    op = getattr(getattr(ctx.cultivate_detail, 'turn_info', None), 'turn_operation', None)
    try:
        return int(getattr(op, 'race_id', 0) or 0)
    except Exception:
        return 0


def _select_cleat_by_priority(owned_map, priority):
    order = ['Artisan Cleat Hammer', 'Master Cleat Hammer'] if priority == 'artisan' \
        else ['Master Cleat Hammer', 'Artisan Cleat Hammer']
    for name in order:
        if int((owned_map or {}).get(name, 0) or 0) > 0:
            return name
    return None


def handle_glow_sticks_before_race(ctx):
    # User-controlled: glow on a calendar race only if its id is listed; on climax
    # only if enabled AND it's the last climax race (turn 78).
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    if owned_map.get('Glow Sticks', 0) <= 0:
        return False
    mant_cfg = _get_mant_cfg(ctx)
    if mant_cfg is None:
        return False
    date = int(getattr(ctx.cultivate_detail.turn_info, 'date', 0) or 0)
    if date in MANT_CLIMAX_RACE_TURNS:
        if not getattr(mant_cfg, 'climax_use_glow', False):
            _inventory.log.info("[GLOW] Skip — climax glow disabled")
            return False
        if date != max(MANT_CLIMAX_RACE_TURNS):
            _inventory.log.info(f"[GLOW] Skip — climax glow only on last race (turn {max(MANT_CLIMAX_RACE_TURNS)})")
            return False
    else:
        race_id = _current_race_id(ctx)
        glow_ids = getattr(mant_cfg, 'glow_race_ids', []) or []
        if race_id not in glow_ids:
            _inventory.log.info(f"[GLOW] Skip — race {race_id} not in glow list")
            return False
    return use_item_and_update_inventory(ctx, 'Glow Sticks')


def handle_cleat_before_race(ctx, race_id, is_climax_override=False):
    # User-controlled: cleat on a calendar race only if its id is listed; on climax
    # only if enabled. Picks the cleat by the global priority, falling back to the
    # other if the preferred one isn't in inventory.
    if getattr(ctx.cultivate_detail, 'mant_cleat_used', False):
        _inventory.log.info("[CLEAT] Skipping — already used this turn")
        return False

    mant_cfg = _get_mant_cfg(ctx)
    if mant_cfg is None:
        return False

    date = int(getattr(ctx.cultivate_detail.turn_info, 'date', 0) or 0)
    is_climax = bool(is_climax_override) or date in MANT_CLIMAX_RACE_TURNS
    if is_climax:
        if not getattr(mant_cfg, 'climax_use_cleat', True):
            _inventory.log.info("[CLEAT] Skip — climax cleats disabled")
            return False
    else:
        cleat_ids = getattr(mant_cfg, 'cleat_race_ids', []) or []
        if int(race_id or 0) not in cleat_ids:
            _inventory.log.info(f"[CLEAT] Skip — race {race_id} not in cleat list")
            return False

    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    selected = _select_cleat_by_priority(owned_map, getattr(mant_cfg, 'cleat_priority', 'master'))
    if not selected:
        _inventory.log.info("[CLEAT] Skip — no cleat in inventory")
        return False
    _inventory.log.info(f"[CLEAT] Using {selected} (priority={getattr(mant_cfg, 'cleat_priority', 'master')})")
    result = use_item_and_update_inventory(ctx, selected)
    if result:
        ctx.cultivate_detail.mant_cleat_used = True
        _inventory.log.info(f"[CLEAT] Successfully used {selected}")
    else:
        _inventory.log.warning(f"[CLEAT] Failed to use {selected}")
    return result


__all__ = [
    "MANT_CLIMAX_RACE_TURNS",
    "remaining_climax_races",
    "get_cleat_state",
    "choose_cleat_for_race",
    "would_cleat_be_useful_before_race",
    "handle_energy_drink_max_before_race",
    "handle_glow_sticks_before_race",
    "handle_cleat_before_race",
]
