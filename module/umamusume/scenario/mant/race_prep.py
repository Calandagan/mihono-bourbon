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


def handle_glow_sticks_before_race(ctx):
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    if owned_map.get('Glow Sticks', 0) <= 0:
        return False
    return use_item_and_update_inventory(ctx, 'Glow Sticks')


def handle_cleat_before_race(ctx, race_id, is_climax_override=False):
    if getattr(ctx.cultivate_detail, 'mant_cleat_used', False):
        _inventory.log.info(f"[CLEAT] Skipping — already used this turn")
        return False

    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    state = get_cleat_state(owned_map)
    _inventory.log.info(f"[CLEAT] Checking — race_id={race_id} date={date} is_climax={is_climax_override} owned={state}")
    selected = choose_cleat_for_race(
        date,
        race_id,
        owned_map,
        is_climax_override=is_climax_override,
    )
    if not selected:
        _inventory.log.info(f"[CLEAT] No cleat selected — total={state['total']} spare_artisan={state['spare_artisan']} spare_master={state['spare_master']}")
        return False
    _inventory.log.info(f"[CLEAT] Using {selected}")
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
