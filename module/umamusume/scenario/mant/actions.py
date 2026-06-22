from __future__ import annotations

import time

from module.umamusume.scenario.mant import inventory as _inventory
from module.umamusume.scenario.mant.item_targets import item_option, selected_item

INSTANT_USE_ITEMS = _inventory.INSTANT_USE_ITEMS
ONE_TIME_BUFF_ITEMS = _inventory.ONE_TIME_BUFF_ITEMS


def _set_item_trace(ctx, *, options=None, selected=None, result=None):
    turn_info = getattr(ctx.cultivate_detail, "turn_info", None)
    if turn_info is None:
        return
    if hasattr(turn_info, "set_item_trace"):
        turn_info.set_item_trace(options=options, selected=selected, result=result)
    if hasattr(turn_info, "append_trace"):
        turn_info.append_trace(
            "mant_item_action",
            options_count=len(options or turn_info.item_use_options or []),
            selected=list(selected if selected is not None else turn_info.item_use_selected or []),
            result=dict(result if result is not None else turn_info.item_use_result or {}),
        )


def _remove_stale_local_items(ctx, item_names):
    stale = {name for name in (item_names or []) if name}
    if not stale:
        return []
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    changed = False
    for item_name in stale:
        if owned_map.pop(item_name, None) is not None:
            changed = True
    if not changed:
        return owned
    updated = [(n, q) for n, q in owned_map.items() if q > 0]
    ctx.cultivate_detail.mant_owned_items = updated
    from module.umamusume.persistence import save_inventory
    save_inventory(updated)
    from module.umamusume.context import log_detected_items
    log_detected_items(updated)
    return updated


def use_item_and_update_inventory(ctx, item_name):
    ok = _inventory.use_training_item(ctx, item_name, 1)
    if not ok:
        missing = getattr(ctx.cultivate_detail, 'mant_last_full_search_missing_items', [])
        if item_name in set(missing or []):
            _inventory.log.warning(f"[INVENTORY] Removing stale local entry for missing item '{item_name}'")
            _remove_stale_local_items(ctx, [item_name])
        return False
    _inventory.update_max_energy_from_ocr(ctx)
    _inventory.close_items_panel(ctx)
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    owned_map[item_name] = max(0, owned_map.get(item_name, 0) - 1)
    updated = [(n, q) for n, q in owned_map.items() if q > 0]
    ctx.cultivate_detail.mant_owned_items = updated
    from module.umamusume.persistence import save_inventory
    save_inventory(ctx.cultivate_detail.mant_owned_items)
    from module.umamusume.context import log_detected_items
    log_detected_items(updated)
    _inventory.log.info(f"used {item_name}")
    return True


def use_items_and_update_inventory(ctx, item_names):
    targets = [name for name in (item_names or []) if name]
    result = _inventory.use_training_items(ctx, targets)
    missing = result.get("fully_searched_missing", [])
    if missing:
        _inventory.log.warning(f"[INVENTORY] Removing stale local entries for missing items {missing}")
        _remove_stale_local_items(ctx, missing)
    if not result.get("confirmed"):
        return result

    selected = list(result.get("selected", []))
    _inventory.update_max_energy_from_ocr(ctx)
    _inventory.close_items_panel(ctx)
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    for item_name in selected:
        owned_map[item_name] = max(0, owned_map.get(item_name, 0) - 1)
    updated = [(n, q) for n, q in owned_map.items() if q > 0]
    ctx.cultivate_detail.mant_owned_items = updated
    from module.umamusume.persistence import save_inventory
    save_inventory(ctx.cultivate_detail.mant_owned_items)
    from module.umamusume.context import log_detected_items
    log_detected_items(updated)
    _inventory.log.info(f"used training items: {selected}")
    return result


def handle_instant_use_items(ctx):
    from module.umamusume.persistence import mark_buff_used, is_buff_used
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}

    items_to_use = []
    options = []
    for item_name in INSTANT_USE_ITEMS:
        qty = owned_map.get(item_name, 0)
        selected = False
        skip_reason = None
        if qty <= 0:
            skip_reason = "no_owned"
        elif item_name in ONE_TIME_BUFF_ITEMS and is_buff_used(item_name):
            skip_reason = "already_used"
        else:
            items_to_use.append(item_name)
            selected = True
        options.append(
            item_option(
                item_name,
                "instant_use",
                selected=selected,
                priority=1,
                skip_reason=skip_reason,
                current_num=qty,
            )
        )

    if not items_to_use:
        _set_item_trace(
            ctx,
            options=options,
            selected=[],
            result={"phase": "instant_use", "result": "skip", "reason": "no_targets"},
        )
        return False

    _inventory.open_items_panel(ctx)

    selected = []
    not_found = []
    fully_searched_missing = []
    for item_name in items_to_use:
        found, search_complete = _inventory.try_click_item_plus_once(ctx, item_name)
        if found:
            selected.append(item_name)
            time.sleep(0.15)
        else:
            not_found.append(item_name)
            if search_complete:
                fully_searched_missing.append(item_name)

    if fully_searched_missing:
        ctx.cultivate_detail.mant_inventory_rescan_pending = True
        _remove_stale_local_items(ctx, fully_searched_missing)
        _inventory.log.warning(
            f"[INSTANT-USE] Full search missed items {fully_searched_missing}; "
            "removing stale local entries and scheduling a rescan"
        )

    if not selected:
        _inventory.close_items_panel(ctx)
        _set_item_trace(
            ctx,
            options=options,
            selected=[],
            result={"phase": "instant_use", "result": "failed", "reason": "nothing_selected"},
        )
        return False

    ctx.ctrl.click(530, 1205, name="confirm items")

    for _ in range(20):
        time.sleep(0.35)
        frame = ctx.ctrl.get_screen()
        if _inventory.has_use_training_items_button(frame):
            ctx.ctrl.click(530, 1205, name="confirm items")
            time.sleep(0.5)
            _inventory.update_max_energy_from_ocr(ctx)
            break
        if _inventory.is_items_panel_open(frame):
            ctx.ctrl.click(530, 1205, name="confirm items")
            time.sleep(0.35)

    for _ in range(15):
        time.sleep(0.35)
        frame = ctx.ctrl.get_screen()
        if _inventory.is_items_panel_open(frame):
            break

    _inventory.close_items_panel(ctx)

    for item_name in selected:
        owned_map[item_name] = max(0, owned_map.get(item_name, 0) - 1)
        if item_name in ONE_TIME_BUFF_ITEMS:
            mark_buff_used(item_name)

    updated = [(n, q) for n, q in owned_map.items() if q > 0]
    ctx.cultivate_detail.mant_owned_items = updated
    from module.umamusume.persistence import save_inventory
    save_inventory(ctx.cultivate_detail.mant_owned_items)
    from module.umamusume.context import log_detected_items
    log_detected_items(updated)

    _inventory.log.info(f"used instant items: {selected}")
    _set_item_trace(
        ctx,
        options=options,
        selected=[selected_item(name) for name in selected],
        result={"phase": "instant_use", "result": "ok", "selected": list(selected), "not_found": list(not_found)},
    )
    return True


def handle_cupcake_use(ctx):
    from bot.conn.fetch import read_mood

    cached_mood = getattr(ctx.cultivate_detail.turn_info, 'cached_mood', None)
    mood = cached_mood if cached_mood is not None else read_mood(ctx.current_screen)

    # Goal: keep mood at Good (4) as a minimum. Only act when mood is below Good.
    # This intentionally runs even during race chains (mood can drop there too).
    # It does NOT touch the recreation/outing logic; by raising mood early it just
    # makes that path less likely to trigger.
    if mood is None or mood >= 4:
        _set_item_trace(
            ctx,
            options=[],
            selected=[],
            result={"phase": "mood_recovery", "result": "skip", "reason": "mood_ok"},
        )
        return False

    owned = {n: q for n, q in getattr(ctx.cultivate_detail, 'mant_owned_items', [])}
    # Use the largest cupcake that doesn't overshoot Great (5), repeating until mood
    # reaches Good (4) or we run out. This naturally yields: Normal -> Berry Sweet,
    # never wastes a Berry where it would overcap, and tops up Bad/Awful as needed.
    cupcakes = [('Berry Sweet Cupcake', 2), ('Plain Cupcake', 1)]
    used = []
    progressed = True
    while mood < 4 and progressed:
        progressed = False
        for name, boost in cupcakes:
            if owned.get(name, 0) > 0 and mood + boost <= 5:
                if use_item_and_update_inventory(ctx, name):
                    owned[name] = owned.get(name, 0) - 1
                    mood += boost
                    used.append(name)
                    progressed = True
                break

    if used:
        ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
        _set_item_trace(
            ctx,
            options=[],
            selected=[selected_item(n) for n in used],
            result={"phase": "mood_recovery", "result": "ok", "items": used},
        )
        return True

    _set_item_trace(
        ctx,
        options=[],
        selected=[],
        result={"phase": "mood_recovery", "result": "skip", "reason": "no_owned"},
    )
    return False


def has_instant_use_items(ctx):
    from module.umamusume.persistence import is_buff_used

    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    for item in INSTANT_USE_ITEMS:
        if owned_map.get(item, 0) <= 0:
            continue
        if item in ONE_TIME_BUFF_ITEMS and is_buff_used(item):
            continue
        return True
    return False


__all__ = [
    "INSTANT_USE_ITEMS",
    "ONE_TIME_BUFF_ITEMS",
    "use_item_and_update_inventory",
    "use_items_and_update_inventory",
    "handle_instant_use_items",
    "handle_cupcake_use",
    "has_instant_use_items",
    "update_max_energy_from_ocr",
    "sync_max_energy_to_scanner",
]


update_max_energy_from_ocr = _inventory.update_max_energy_from_ocr
sync_max_energy_to_scanner = _inventory.sync_max_energy_to_scanner
