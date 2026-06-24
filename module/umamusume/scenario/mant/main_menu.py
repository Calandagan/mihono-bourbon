import cv2
import re
from collections import Counter

from bot.recog.image_matcher import image_match
from bot.recog.ocr import ocr_line
from module.umamusume.asset.template import REF_MANT_ON_SALE
from module.umamusume.define import TurnOperationType
from module.umamusume.scenario.mant.item_targets import item_option, selected_item
import bot.base.log as logger

log = logger.get_logger(__name__)

COIN_ROI_NORMAL = (1172, 1197, 402, 500)
COIN_ROI_SUMMER = (1172, 1199, 321, 417)
COIN_ROI_CLIMAX = (1125, 1148, 565, 654)

RIVAL_COLOR_1 = (0x4E, 0xFF, 0xFF)
RIVAL_COLOR_2 = (0x30, 0xAD, 0xEB)
RIVAL_TOLERANCE = 5


def _owned_items_to_map(owned_items):
    if isinstance(owned_items, dict):
        return {str(name): int(qty or 0) for name, qty in owned_items.items() if int(qty or 0) > 0}
    mapped = {}
    for name, qty in owned_items or []:
        qty_val = int(qty or 0)
        if qty_val > 0:
            mapped[str(name)] = qty_val
    return mapped


def _save_owned_items_map(ctx, owned_map):
    updated = sorted(
        [(name, int(qty)) for name, qty in owned_map.items() if int(qty or 0) > 0],
        key=lambda row: row[0],
    )
    ctx.cultivate_detail.mant_owned_items = updated
    from module.umamusume.persistence import save_inventory
    save_inventory(updated)
    from module.umamusume.context import log_detected_items
    log_detected_items(updated)
    return updated


def _merge_scanned_inventory_with_local(ctx, scanned_items):
    merged = _owned_items_to_map(getattr(ctx.cultivate_detail, "mant_owned_items", []))
    for name, qty in scanned_items or []:
        qty_val = int(qty or 0)
        if qty_val > 0:
            merged[name] = max(qty_val, merged.get(name, 0))
    return _save_owned_items_map(ctx, merged)


def _overwrite_inventory_with_scan(ctx, scanned_items):
    # Replace local memory with exactly what the scan saw (corrects both ghost
    # items the memory missed AND stale over-counts). Only used after a scan that
    # confirmed it reached the bottom of the list.
    new_map = {}
    for name, qty in scanned_items or []:
        qty_val = int(qty or 0)
        if qty_val > 0:
            new_map[name] = qty_val
    return _save_owned_items_map(ctx, new_map)


def _apply_shop_purchase_to_local_inventory(ctx, selected_items):
    selected_items = [name for name in (selected_items or []) if name]
    if not selected_items:
        return []
    owned_map = _owned_items_to_map(getattr(ctx.cultivate_detail, "mant_owned_items", []))
    for item_name in selected_items:
        owned_map[item_name] = owned_map.get(item_name, 0) + 1
    return _save_owned_items_map(ctx, owned_map)


def _mark_inventory_rescan_if_shop_buy_uncertain(ctx, buy_result, selected_items, source):
    selected_items = [name for name in (selected_items or []) if name]
    clicked_items = list((buy_result or {}).get("clicked") or [])
    if selected_items:
        log.info(f"[INVENTORY] Applied confirmed shop purchase locally ({source}); skipping full rescan")
        return False
    if clicked_items:
        ctx.cultivate_detail.mant_inventory_rescan_pending = True
        log.warning(
            f"[INVENTORY] Shop buy clicked items but confirmed none ({source}); scheduling inventory rescan"
        )
        return True
    return False


def _use_grilled_carrots_now(ctx, selected_items):
    # Grilled Carrots are meant to be consumed immediately (favor/BBQ), not hoarded.
    # Force-use as many as were just purchased, right after closing the shop, instead
    # of waiting for the next turn's instant-use pass. Scoped to Grilled Carrots only.
    carrots = sum(1 for name in (selected_items or []) if name == "Grilled Carrots")
    if carrots <= 0:
        return
    from module.umamusume.scenario.mant.actions import use_item_and_update_inventory
    log.info(f"[CARROTS] Using {carrots} Grilled Carrots immediately after purchase")
    for _ in range(carrots):
        if not use_item_and_update_inventory(ctx, "Grilled Carrots"):
            log.warning("[CARROTS] Could not use a Grilled Carrots immediately; leaving for next inventory pass")
            break


def _mood_needs_shop_for_cupcakes(ctx, current_date):
    # True only when mood is below Good, we own no cupcakes, the shop is available,
    # and we haven't already tried a mood-driven shop trip this turn (avoids looping
    # the shop when cupcakes are disabled or out of stock).
    from module.umamusume.scenario.mant.shop import is_shop_scan_turn
    ti = getattr(ctx.cultivate_detail, 'turn_info', None)
    if ti is None or getattr(ti, 'mant_mood_shop_attempted', False):
        return False
    if not is_shop_scan_turn(current_date):
        return False
    mood = getattr(ti, 'cached_mood', None)
    if mood is None or mood >= 4:
        return False
    owned = {n: q for n, q in getattr(ctx.cultivate_detail, 'mant_owned_items', [])}
    if owned.get('Plain Cupcake', 0) > 0 or owned.get('Berry Sweet Cupcake', 0) > 0:
        return False
    return True


def _mark_bought_shop_rows(items_list, bought_items):
    bought_counts = Counter(bought_items or [])
    updated_rows = []
    for name, conf, gy, turns, buyable in items_list:
        row_buyable = buyable
        if row_buyable and bought_counts.get(name, 0) > 0:
            row_buyable = False
            bought_counts[name] -= 1
        updated_rows.append((name, conf, gy, turns, row_buyable))
    return updated_rows


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


def _ensure_item_fail_state(ctx):
    current_date = int(getattr(ctx.cultivate_detail.turn_info, "date", 0) or 0)
    if getattr(ctx.cultivate_detail, "mant_failed_use_turn", None) != current_date:
        ctx.cultivate_detail.mant_failed_use_turn = current_date
        ctx.cultivate_detail.mant_failed_use_items = set()
        ctx.cultivate_detail.mant_item_use_error_pending = False


def _item_failed(ctx, item_name):
    _ensure_item_fail_state(ctx)
    return item_name in getattr(ctx.cultivate_detail, "mant_failed_use_items", set())


def _mark_item_failed(ctx, item_name):
    _ensure_item_fail_state(ctx)
    ctx.cultivate_detail.mant_failed_use_items.add(item_name)
    ctx.cultivate_detail.mant_item_use_error_pending = True


def _clear_item_failed(ctx, item_name):
    _ensure_item_fail_state(ctx)
    failed = getattr(ctx.cultivate_detail, "mant_failed_use_items", set())
    if item_name in failed:
        failed.discard(item_name)
    if not failed:
        ctx.cultivate_detail.mant_item_use_error_pending = False


def _build_shop_trace_options(
    items_list,
    targets,
    *,
    failed_snapshot=None,
    skip_overrides=None,
    option_meta=None,
    selected_meta=None,
    default_skip_reason="not_selected_by_policy",
):
    selected_counter = Counter(targets or [])
    failed_snapshot = set(failed_snapshot or set())
    skip_overrides = dict(skip_overrides or {})
    option_meta = dict(option_meta or {})
    selected_meta = dict(selected_meta or {})
    options = []
    selected_rows = []
    for name, _conf, _gy, turns, buyable in items_list:
        selected = False
        skip_reason = None
        if not buyable:
            skip_reason = "not_buyable"
        elif name in failed_snapshot:
            skip_reason = "failed_snapshot"
        elif selected_counter.get(name, 0) > 0:
            selected = True
            selected_counter[name] -= 1
            row = {"name": name}
            row.update(selected_meta.get(name, {}))
            selected_rows.append(row)
        else:
            skip_reason = skip_overrides.get(name, default_skip_reason)
        option = {
            "name": name,
            "turns": turns,
            "selected": selected,
            "skip_reason": skip_reason,
        }
        option.update(option_meta.get(name, {}))
        options.append(option)
    return options, selected_rows


def read_shop_coins(img, is_summer, is_climax):
    if is_climax:
        y1, y2, x1, x2 = COIN_ROI_CLIMAX
    elif is_summer:
        y1, y2, x1, x2 = COIN_ROI_SUMMER
    else:
        y1, y2, x1, x2 = COIN_ROI_NORMAL
    roi = img[y1:y2, x1:x2]
    text = ocr_line(roi, lang="en")
    digits = re.sub(r'[^0-9]', '', text)
    if digits:
        return int(digits)
    return -1


def handle_mant_inventory_scan(ctx, current_date):
    if ctx.cultivate_detail.mant_inventory_scanned:
        return False
    if current_date < 13:
        return False

    from module.umamusume.scenario.mant.scan import scan_inventory, open_items_panel, close_items_panel

    opened = open_items_panel(ctx)
    if not opened:
        ctx.ctrl.trigger_decision_reset = True
        return True

    owned = scan_inventory(ctx)
    _merge_scanned_inventory_with_local(ctx, owned)
    ctx.cultivate_detail.mant_inventory_scanned = True
    ctx.cultivate_detail.mant_last_inventory_scan_date = current_date

    close_items_panel(ctx)
    ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
    return True


INVENTORY_PERIODIC_SCAN_INTERVAL = 6


def handle_mant_periodic_inventory_scan(ctx, current_date):
    # Every N turns, re-scan and resync local memory. The bot still trusts its
    # memory between scans; this just periodically corrects it (e.g. a ghost item
    # the initial scan missed). Overwrites memory when the scan reached the bottom
    # of the list; otherwise falls back to a safe max-merge so a cut-short scan
    # never wipes items it didn't reach.
    if current_date < 13:
        return False
    if not ctx.cultivate_detail.mant_inventory_scanned:
        return False  # let the initial scan run first
    last = getattr(ctx.cultivate_detail, 'mant_last_inventory_scan_date', None)
    if last is not None and current_date - last < INVENTORY_PERIODIC_SCAN_INTERVAL:
        return False

    from module.umamusume.scenario.mant.scan import scan_inventory, open_items_panel, close_items_panel

    opened = open_items_panel(ctx)
    if not opened:
        ctx.ctrl.trigger_decision_reset = True
        return True

    owned = scan_inventory(ctx)
    reached_bottom = getattr(ctx.cultivate_detail, 'mant_last_scan_reached_bottom', False)
    if reached_bottom:
        _overwrite_inventory_with_scan(ctx, owned)
        log.info("[INVENTORY] Periodic scan: resynced local memory from scan (reached bottom)")
    else:
        _merge_scanned_inventory_with_local(ctx, owned)
        log.warning("[INVENTORY] Periodic scan did not reach bottom; merged instead of overwriting")
    ctx.cultivate_detail.mant_last_inventory_scan_date = current_date
    close_items_panel(ctx)
    ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
    return True


def handle_mant_inventory_rescan_if_pending(ctx, current_date):
    pending = getattr(ctx.cultivate_detail, 'mant_inventory_rescan_pending', False)
    if not pending:
        return False

    from module.umamusume.scenario.mant.scan import scan_inventory, open_items_panel, close_items_panel

    opened = open_items_panel(ctx)
    if not opened:
        ctx.ctrl.trigger_decision_reset = True
        return True

    owned = scan_inventory(ctx)
    _merge_scanned_inventory_with_local(ctx, owned)
    ctx.cultivate_detail.mant_inventory_scanned = True
    ctx.cultivate_detail.mant_inventory_rescan_pending = False
    ctx.cultivate_detail.mant_last_inventory_scan_date = current_date
    close_items_panel(ctx)
    ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
    return True


def handle_mant_turn_start(ctx, current_date):
    from module.umamusume.scenario.mant.shop import is_shop_scan_turn, current_shop_chunk
    if not is_shop_scan_turn(current_date):
        return
    processed_date = getattr(ctx.cultivate_detail, 'mant_shop_turn_start_date', None)
    if processed_date == current_date:
        return
    ctx.cultivate_detail.mant_shop_turn_start_date = current_date

    chunk = current_shop_chunk(current_date)
    last_chunk = getattr(ctx.cultivate_detail, 'mant_shop_last_chunk', -1)

    if chunk != last_chunk:
        ctx.cultivate_detail.mant_shop_items = []
    else:
        updated = []
        for name, conf, gy, turns, buyable in ctx.cultivate_detail.mant_shop_items:
            if turns == 99:
                updated.append((name, conf, gy, turns, buyable))
            elif turns > 1:
                updated.append((name, conf, gy, turns - 1, buyable))
        ctx.cultivate_detail.mant_shop_items = updated

        from module.umamusume.context import log_detected_shop_items
        log_detected_shop_items([(name, turns, buyable) for name, _, _, turns, buyable in updated])


def handle_mant_shop_scan(ctx, current_date):
    force_mood = getattr(ctx.cultivate_detail.turn_info, 'mant_force_shop_scan', False)
    if ctx.cultivate_detail.mant_shop_scanned_this_turn and not force_mood:
        return False
    from module.umamusume.scenario.mant.shop import (
        is_shop_scan_turn, scan_mant_shop, buy_shop_items,
        SHOP_ITEM_COSTS, SLUG_TO_DISPLAY, display_to_slug,
        current_shop_chunk
    )
    from module.umamusume.scenario.mant.constants import AILMENT_CURE_MAP, AILMENT_CURE_ALL
    from module.umamusume.scenario.mant.policy import (
        get_mant_coin_cap,
        get_mant_coin_reserve,
    )
    from module.umamusume.scenario.mant.shop_policy import (
        collect_shop_turns,
        collect_priority_cure_targets,
        get_deck_type_counts,
        get_shop_item_ui_tier,
        get_shop_stock_state,
        is_shop_item_disabled,
        should_skip_shop_item,
    )
    if not is_shop_scan_turn(current_date):
        return False
    chunk = current_shop_chunk(current_date)
    last_chunk = getattr(ctx.cultivate_detail, 'mant_shop_last_chunk', -1)
    if chunk == last_chunk and not force_mood:
        return False
    if force_mood:
        ctx.cultivate_detail.turn_info.mant_force_shop_scan = False

    log.info(f"[SHOP] Starting scan — date={current_date} chunk={chunk} coins={ctx.cultivate_detail.mant_coins}")
    scan_result = scan_mant_shop(ctx)
    if scan_result is None:
        log.warning("[SHOP] scan_mant_shop returned None — shop did not open or REF_SHOP_MANT_CHECK not found")
        ctx.ctrl.trigger_decision_reset = True
        return True

    items_list = scan_result
    ctx.cultivate_detail.mant_shop_items = items_list
    ctx.cultivate_detail.mant_shop_scanned_this_turn = True
    ctx.cultivate_detail.mant_shop_last_chunk = chunk

    from module.umamusume.context import log_detected_shop_items
    log_detected_shop_items([(name, turns, buyable) for name, _, _, turns, buyable in items_list])
    buyable_items = [(name, turns) for name, _, _, turns, buyable in items_list if buyable]
    non_buyable = [name for name, _, _, _, buyable in items_list if not buyable]
    log.info(f"[SHOP] Scan complete — buyable={buyable_items} | not_buyable={non_buyable}")

    bought = False
    mant_cfg = getattr(ctx.task.detail.scenario_config, 'mant_config', None)
    if mant_cfg and mant_cfg.item_tiers:
        budget = ctx.cultivate_detail.mant_coins
        start_budget = budget
        coin_cap = get_mant_coin_cap(current_date, mant_cfg)
        coin_reserve = get_mant_coin_reserve(current_date, start_budget, mant_cfg)
        shop_available = {name for name, _, _, _, buyable in items_list if buyable}
        shop_detected = {name for name, _, _, _, _ in items_list}
        shop_slugs = {display_to_slug(n) for n in shop_available}
        detected_slugs = {display_to_slug(n) for n in shop_detected}
        log.info(
            f"[SHOP] Budget={budget} reserve_hint={coin_reserve} cap_hint={coin_cap} "
            f"| shop_slugs={detected_slugs}"
        )
        shop_copy_counts = {}
        for name, _conf, _gy, _turns, buyable in items_list:
            if buyable:
                shop_copy_counts[name] = shop_copy_counts.get(name, 0) + 1

        img = ctx.ctrl.get_screen()
        if img is not None:
            handle_mant_on_sale(img)

        from module.umamusume.persistence import get_used_buffs, get_ignore_cat_food, get_ignore_grilled_carrots
        from module.umamusume.scenario.mant.actions import ONE_TIME_BUFF_ITEMS
        used_buffs = get_used_buffs()
        ignore_cat = get_ignore_cat_food()
        ignore_carrots = get_ignore_grilled_carrots()

        active_ailments = getattr(ctx.cultivate_detail, 'mant_afflictions', [])
        owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
        owned_map = {n: q for n, q in owned}
        has_miracle_cure = owned_map.get(AILMENT_CURE_ALL, 0) > 0

        priority_targets, bought_cures, budget = collect_priority_cure_targets(
            active_ailments,
            owned_map,
            shop_available,
            budget,
            AILMENT_CURE_MAP,
            AILMENT_CURE_ALL,
            SHOP_ITEM_COSTS,
            mant_cfg=mant_cfg,
            display_to_slug=display_to_slug,
        )
        log.info(f"[SHOP] priority_targets (cures)={priority_targets}, budget={budget}")
        if bought_cures:
            ctx.cultivate_detail._mant_bought_cures_this_cycle = bought_cures

        priority_set = set(priority_targets)

        all_cures = set(AILMENT_CURE_MAP.values())

        deck_counts = get_deck_type_counts(getattr(ctx.task.detail, 'pal_card_store', {}))

        def should_skip(display_name):
            return should_skip_shop_item(
                display_name,
                mant_cfg=mant_cfg,
                priority_set=priority_set,
                one_time_buff_items=ONE_TIME_BUFF_ITEMS,
                used_buffs=used_buffs,
                ignore_cat=ignore_cat,
                ignore_carrots=ignore_carrots,
                display_to_slug=display_to_slug,
                all_cures=all_cures,
                has_miracle_cure=has_miracle_cure,
                owned_map=owned_map,
                ailment_cure_all=AILMENT_CURE_ALL,
                deck_counts=deck_counts,
            )

        tier_targets = []
        target_sources = {name: "urgent_cure_override" for name in priority_targets}
        target_ui_tiers = {}
        skip_overrides = {}
        option_meta = {}
        selected_meta = {}
        shop_turns = collect_shop_turns(items_list)

        for name, _conf, _gy, _turns, buyable in items_list:
            if not buyable:
                continue
            slug = display_to_slug(name)
            current_num, max_stock = get_shop_stock_state(name, owned_map)
            option_meta[name] = {
                "source": "tier_policy",
                "ui_tier": get_shop_item_ui_tier(mant_cfg, slug, default=mant_cfg.tier_count),
                "current_stock": current_num,
            }
            if max_stock is not None:
                option_meta[name]["max_stock"] = max_stock

        # Spend aggressively, but never plan more checkboxes than the current
        # coin budget can physically pay for. "Clicked" is not a purchase.
        for tier in range(1, mant_cfg.tier_count + 1):
            tier_items = []
            for slug, t in mant_cfg.item_tiers.items():
                if int(t or 0) < 1 or t != tier or slug not in shop_slugs:
                    continue
                tier_items.append(slug)

            tier_items.sort(key=lambda s, tier=t: (
                tier,
                shop_turns.get(SLUG_TO_DISPLAY.get(s), 99),
                SHOP_ITEM_COSTS.get(SLUG_TO_DISPLAY.get(s, ''), 9999),
            ))

            for slug in tier_items:
                display = SLUG_TO_DISPLAY.get(slug)
                if not display:
                    continue
                if should_skip(display):
                    current_num, max_stock = get_shop_stock_state(display, owned_map)
                    if is_shop_item_disabled(mant_cfg, display_name=display, display_to_slug=display_to_slug):
                        skip_overrides[display] = "disabled_by_ui"
                    elif current_num and max_stock is not None and current_num >= max_stock:
                        skip_overrides[display] = "stock_cap_reached"
                    elif display in priority_set:
                        skip_overrides[display] = "already_selected_by_urgent_cure_policy"
                    elif display in ONE_TIME_BUFF_ITEMS and display in used_buffs:
                        skip_overrides[display] = "one_time_buff_already_used"
                    elif ignore_cat and display == "Yummy Cat Food":
                        skip_overrides[display] = "ignored_by_user_flag"
                    elif ignore_carrots and display_to_slug(display) == "grilled_carrots":
                        skip_overrides[display] = "ignored_by_user_flag"
                    elif display == "Energy Drink MAX" and current_num > 0:
                        skip_overrides[display] = "already_in_stock"
                    else:
                        skip_overrides[display] = "not_useful_for_current_deck"
                    continue

                cost = SHOP_ITEM_COSTS.get(display, 9999)
                copies = shop_copy_counts.get(display, 0)
                if copies <= 0:
                    continue

                actual_copies = 1 if display in all_cures or display == AILMENT_CURE_ALL else copies
                for _i in range(actual_copies):
                    if cost > budget:
                        skip_overrides.setdefault(display, "insufficient_coins")
                        break
                    tier_targets.append(display)
                    target_sources.setdefault(display, "tier_policy")
                    target_ui_tiers.setdefault(display, tier)
                    budget -= cost

        log.info(f"[SHOP] tier_targets built={tier_targets}, budget_remaining={budget}")

        targets = priority_targets + tier_targets
        log.info(f"[SHOP] targets to buy={targets}")
        failed_snapshot = set(getattr(ctx.cultivate_detail, 'mant_failed_shop_names_snapshot', set()))
        for target_name in targets:
            selected_meta[target_name] = {
                "source": target_sources.get(target_name, "tier_policy"),
                "ui_tier": target_ui_tiers.get(target_name, option_meta.get(target_name, {}).get("ui_tier")),
                "reason": "selected_by_shop_policy",
                "current_stock": option_meta.get(target_name, {}).get("current_stock", 0),
            }
            max_stock = option_meta.get(target_name, {}).get("max_stock")
            if max_stock is not None:
                selected_meta[target_name]["max_stock"] = max_stock

        shop_options, selected_rows = _build_shop_trace_options(
            items_list,
            targets,
            failed_snapshot=failed_snapshot,
            skip_overrides=skip_overrides,
            option_meta=option_meta,
            selected_meta=selected_meta,
        )
        ctx.cultivate_detail.turn_info.set_shop_trace(
            options=shop_options,
            selected=selected_rows,
            result={
                "phase": "shop_scan",
                "source": "urgent_cure_override" if priority_targets else "tier_policy",
                "result": "planned",
                "targets": list(targets),
                "start_budget": int(start_budget),
                "reserve": int(coin_reserve),
                "cap": int(coin_cap),
            },
        )
        if targets:
            bought, held_items = buy_shop_items(ctx, targets, items_list)
            if bought:
                selected_items = list((held_items or {}).get("selected") or [])
                _mark_inventory_rescan_if_shop_buy_uncertain(ctx, held_items, selected_items, "shop_scan")
                _apply_shop_purchase_to_local_inventory(ctx, selected_items)
                _use_grilled_carrots_now(ctx, selected_items)
                total_spent = sum(SHOP_ITEM_COSTS.get(t, 0) for t in selected_items)
                budget_end = max(0, ctx.cultivate_detail.mant_coins - total_spent)
                ctx.cultivate_detail.mant_coins = budget_end
                ctx.cultivate_detail.mant_shop_items = _mark_bought_shop_rows(items_list, selected_items)
                bought_set = set(selected_items)
                remaining = [(name, turns, buyable) for name, _, _, turns, buyable in items_list
                             if buyable and name not in bought_set]
                log_detected_shop_items(remaining)
            else:
                ctx.cultivate_detail.turn_info.append_trace(
                    "mant_shop_buy_failed",
                    targets=list(targets),
                    result=dict(held_items or {}),
                )
        else:
            ctx.cultivate_detail.turn_info.set_shop_trace(
                options=shop_options,
                selected=[],
                result={"phase": "shop_scan", "source": "tier_policy", "result": "skip", "reason": "no_targets"},
            )

    if not bought:
        from module.umamusume.scenario.mant.shop import BACK_BTN_X, BACK_BTN_Y
        import time as t
        ctx.ctrl.click(BACK_BTN_X, BACK_BTN_Y)
        t.sleep(1)

    ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
    return True


def handle_mant_emergency_shop_buys(ctx, current_date):
    if getattr(ctx.cultivate_detail.turn_info, 'mant_emergency_shop_done', False):
        return False

    from module.umamusume.scenario.mant.shop import (
        is_shop_scan_turn, open_mant_shop, buy_shop_items,
        SHOP_ITEM_COSTS, SLUG_TO_DISPLAY, display_to_slug,
        BACK_BTN_X, BACK_BTN_Y,
    )
    from module.umamusume.scenario.mant.constants import AILMENT_CURE_MAP, AILMENT_CURE_ALL
    from module.umamusume.scenario.mant.shop_policy import (
        build_emergency_expiring_targets,
        collect_emergency_cure_targets,
        get_deck_type_counts,
        is_shop_item_disabled,
    )
    import time as _t

    if not is_shop_scan_turn(current_date):
        return False

    shop_items = getattr(ctx.cultivate_detail, 'mant_shop_items', [])
    if not shop_items:
        return False

    budget = ctx.cultivate_detail.mant_coins
    emergency_targets = []
    owned_map = {n: q for n, q in getattr(ctx.cultivate_detail, 'mant_owned_items', [])}

    mant_cfg = getattr(ctx.task.detail.scenario_config, 'mant_config', None)
    if mant_cfg and mant_cfg.item_tiers:
        from module.umamusume.context import detected_portraits_log
        from module.umamusume.persistence import get_ignore_grilled_carrots, get_used_buffs
        from module.umamusume.scenario.mant.actions import ONE_TIME_BUFF_ITEMS

        deck_counts_em = get_deck_type_counts(getattr(ctx.task.detail, 'pal_card_store', {}))
        emergency_targets, budget = build_emergency_expiring_targets(
            current_date=current_date,
            budget=budget,
            shop_items=shop_items,
            mant_cfg=mant_cfg,
            owned_map=owned_map,
            deck_counts=deck_counts_em,
            used_buffs=get_used_buffs(),
            one_time_buff_items=ONE_TIME_BUFF_ITEMS,
            ignore_grilled_carrots=get_ignore_grilled_carrots(),
            shop_item_costs=SHOP_ITEM_COSTS,
            slug_to_display=SLUG_TO_DISPLAY,
            display_to_slug=display_to_slug,
            detected_portraits_log=detected_portraits_log,
            ailment_cure_map=AILMENT_CURE_MAP,
            ailment_cure_all=AILMENT_CURE_ALL,
        )

    active_ailments = getattr(ctx.cultivate_detail, 'mant_afflictions', [])
    if active_ailments:
        shop_available = {name for name, _, _, _, buyable in shop_items if buyable}
        bought_this_cycle = getattr(ctx.cultivate_detail, '_mant_bought_cures_this_cycle', set())
        emergency_targets, bought_this_cycle, budget = collect_emergency_cure_targets(
            active_ailments,
            owned_map,
            shop_available,
            budget,
            AILMENT_CURE_MAP,
            AILMENT_CURE_ALL,
            SHOP_ITEM_COSTS,
            existing_targets=emergency_targets,
            bought_this_cycle=bought_this_cycle,
            mant_cfg=mant_cfg,
            display_to_slug=display_to_slug,
        )
        ctx.cultivate_detail._mant_bought_cures_this_cycle = bought_this_cycle

    if not emergency_targets:
        return False

    ctx.cultivate_detail.turn_info.mant_emergency_shop_done = True
    items_list = getattr(ctx.cultivate_detail, 'mant_shop_items', [])
    fresh_available = {name for name, _, _, _, buyable in items_list if buyable}
    final_targets = [
        tgt for tgt in emergency_targets
        if tgt in fresh_available and not is_shop_item_disabled(mant_cfg, display_name=tgt, display_to_slug=display_to_slug)
    ]
    cure_names = set(AILMENT_CURE_MAP.values()) | {AILMENT_CURE_ALL}
    selected_meta = {
        tgt: {
            "source": "urgent_cure_override" if tgt in cure_names else "expiring_override",
            "reason": "selected_by_emergency_policy",
        }
        for tgt in final_targets
    }
    shop_options, selected_rows = _build_shop_trace_options(
        items_list,
        final_targets,
        selected_meta=selected_meta,
        default_skip_reason="not_selected_by_emergency_policy",
    )
    ctx.cultivate_detail.turn_info.set_shop_trace(
        options=shop_options,
        selected=selected_rows,
        result={
            "phase": "emergency_shop",
            "source": "urgent_cure_override" if any(tgt in cure_names for tgt in final_targets) else "expiring_override",
            "result": "planned",
            "targets": list(final_targets),
        },
    )

    if not final_targets:
        ctx.ctrl.click(BACK_BTN_X, BACK_BTN_Y)
        _t.sleep(1)
        return True

    if not open_mant_shop(ctx):
        ctx.ctrl.trigger_decision_reset = True
        return True

    bought, buy_result = buy_shop_items(ctx, final_targets, items_list)
    if bought:
        selected_items = list((buy_result or {}).get("selected") or [])
        _mark_inventory_rescan_if_shop_buy_uncertain(ctx, buy_result, selected_items, "emergency_shop")
        _apply_shop_purchase_to_local_inventory(ctx, selected_items)
        _use_grilled_carrots_now(ctx, selected_items)
        spent = sum(SHOP_ITEM_COSTS.get(tgt, 0) for tgt in selected_items)
        budget_end = max(0, ctx.cultivate_detail.mant_coins - spent)
        ctx.cultivate_detail.mant_coins = budget_end
        ctx.cultivate_detail.mant_shop_items = _mark_bought_shop_rows(items_list, selected_items)
        from module.umamusume.context import log_detected_shop_items
        bought_set = set(selected_items)
        remaining = [(name, turns, buyable)
                     for name, _, _, turns, buyable in items_list
                     if buyable and name not in bought_set]
        log_detected_shop_items(remaining)
    else:
        ctx.ctrl.click(BACK_BTN_X, BACK_BTN_Y)
        _t.sleep(1)

    return True


CLIMAX_MASTER_RESERVE = 40


def _would_cleat_be_used(cleat_name, race_id, current_date, owned_map, *, is_climax_override=False):
    from module.umamusume.scenario.mant.race_prep import would_cleat_be_useful_before_race

    return would_cleat_be_useful_before_race(
        cleat_name,
        race_id,
        current_date,
        owned_map,
        is_climax_override=is_climax_override,
    )


def _get_pending_cleat_race_context(ctx, current_date):
    from module.umamusume.script.cultivate_task.race_policy import get_pending_race_context

    pending = get_pending_race_context(ctx)
    if not pending.has_race:
        return None
    if not pending.race_id and not pending.is_climax and pending.source != "goal_forced":
        return None
    return {
        "race_id": int(pending.race_id or 0),
        "source": pending.source or "none",
        "is_climax": bool(pending.is_climax),
    }


def handle_mant_cleat_shop_buy(ctx, current_date):
    from module.umamusume.scenario.mant.shop import (
        SHOP_ITEM_COSTS, scan_mant_shop, buy_shop_items, BACK_BTN_X, BACK_BTN_Y
    )
    from module.umamusume.scenario.mant.race_prep import get_cleat_state
    from module.umamusume.scenario.mant.shop import display_to_slug
    from module.umamusume.scenario.mant.shop_policy import is_shop_item_disabled
    import time as _t

    if getattr(ctx.cultivate_detail.turn_info, 'mant_cleat_shop_done', False):
        return False

    owned = dict(getattr(ctx.cultivate_detail, 'mant_owned_items', {}))
    master_qty = owned.get('Master Cleat Hammer', 0)
    artisan_qty = owned.get('Artisan Cleat Hammer', 0)
    total_cleats = master_qty + artisan_qty
    budget = ctx.cultivate_detail.mant_coins

    shop_items = getattr(ctx.cultivate_detail, 'mant_shop_items', [])
    if not shop_items:
        return False
    shop_available = {name for name, _, _, _, buyable in shop_items if buyable}
    mant_cfg = getattr(ctx.task.detail.scenario_config, 'mant_config', None)

    race_ctx = _get_pending_cleat_race_context(ctx, current_date)
    if not race_ctx:
        return False
    race_id = int(race_ctx["race_id"] or 0)
    race_source = race_ctx["source"]
    is_climax = bool(race_ctx["is_climax"])

    state = get_cleat_state(owned)
    reserve_total = state["reserve_total"]
    spare_total = state["spare_master"] + state["spare_artisan"]
    reserve_budget = CLIMAX_MASTER_RESERVE if reserve_total < 2 else 0

    candidate_order = ('Master Cleat Hammer', 'Artisan Cleat Hammer') if is_climax else (
        'Artisan Cleat Hammer', 'Master Cleat Hammer'
    )
    for candidate in candidate_order:
        if candidate not in shop_available:
            continue
        if is_shop_item_disabled(mant_cfg, display_name=candidate, display_to_slug=display_to_slug):
            continue
        cost = SHOP_ITEM_COSTS.get(candidate, 9999)
        if cost > budget:
            continue
        if budget - cost < reserve_budget:
            continue
        useful = _would_cleat_be_used(
            candidate,
            race_id,
            current_date,
            owned,
            is_climax_override=is_climax,
        )
        if not useful and reserve_total >= 2:
            continue
        return _execute_cleat_buy(
            ctx,
            candidate,
            cost,
            source="cleat_override",
            debug={
                "race_id": race_id,
                "race_source": race_source,
                "climax_reserve": reserve_total,
                "spare_cleats": spare_total,
                "is_climax": is_climax,
                "race_usefulness": bool(useful),
            },
        )

    return False


def _execute_cleat_buy(ctx, cleat_name, cost, *, source="cleat_override", debug=None):
    from module.umamusume.scenario.mant.shop import (
        scan_mant_shop, buy_shop_items, BACK_BTN_X, BACK_BTN_Y
    )
    import time as _t

    scan_result = scan_mant_shop(ctx)
    if scan_result is None:
        ctx.ctrl.trigger_decision_reset = True
        return True

    ctx.cultivate_detail.turn_info.mant_cleat_shop_done = True
    items_list = scan_result
    ctx.cultivate_detail.mant_shop_items = items_list
    shop_options, selected_rows = _build_shop_trace_options(
        items_list,
        [cleat_name],
        selected_meta={cleat_name: {"source": source, "reason": "selected_by_cleat_policy"}},
        default_skip_reason="not_selected_by_cleat_policy",
    )
    ctx.cultivate_detail.turn_info.set_shop_trace(
        options=shop_options,
        selected=selected_rows,
        result={"phase": "cleat_shop", "source": source, "result": "planned", "targets": [cleat_name], **(debug or {})},
    )

    fresh_available = {n for n, _, _, _, buyable in items_list if buyable}
    if cleat_name not in fresh_available:
        ctx.cultivate_detail.turn_info.set_shop_trace(
            selected=[],
            result={"phase": "cleat_shop", "source": source, "result": "skip", "reason": "target_not_available", "target": cleat_name, **(debug or {})},
        )
        ctx.ctrl.click(BACK_BTN_X, BACK_BTN_Y)
        _t.sleep(1)
        return True

    bought, buy_result = buy_shop_items(ctx, [cleat_name], items_list)
    if bought:
        selected_items = list((buy_result or {}).get("selected") or [])
        _mark_inventory_rescan_if_shop_buy_uncertain(ctx, buy_result, selected_items, "cleat_shop")
        _apply_shop_purchase_to_local_inventory(ctx, selected_items)
        spent = sum(cost for item_name in selected_items if item_name == cleat_name)
        ctx.cultivate_detail.mant_coins = max(0, ctx.cultivate_detail.mant_coins - spent)
        ctx.cultivate_detail.mant_shop_items = _mark_bought_shop_rows(items_list, selected_items)
        from module.umamusume.context import log_detected_shop_items
        log_detected_shop_items(
            [(n, t, buyable) for n, _, _, t, buyable in items_list if buyable and n not in set(selected_items)]
        )
    else:
        ctx.cultivate_detail.turn_info.append_trace(
            "mant_shop_buy_failed",
            targets=[cleat_name],
            result={"phase": "cleat_shop", "source": source, "result": "failed", "target": cleat_name, **(debug or {})},
        )
        ctx.ctrl.click(BACK_BTN_X, BACK_BTN_Y)
        _t.sleep(1)

    return True


def handle_mant_coin_triggered_buy(ctx, current_date):
    """When coins exceed threshold, trigger emergency buy logic against the
    already-scanned shop items so leftover coins are spent without re-scanning.
    """
    if getattr(ctx.cultivate_detail.turn_info, 'mant_coin_buy_done', False):
        return False

    from module.umamusume.constants.game_constants import SUMMER_CAMP_2_END
    post_summer = current_date > SUMMER_CAMP_2_END

    coin_threshold = 150 if post_summer else 250
    chunk_size = 2 if post_summer else 3

    if ctx.cultivate_detail.mant_coins < coin_threshold:
        return False

    from module.umamusume.scenario.mant.shop import is_shop_scan_turn
    if not is_shop_scan_turn(current_date):
        return False

    coin_chunk = (current_date - 13) // chunk_size
    last_coin_chunk = getattr(ctx.cultivate_detail, 'mant_coin_buy_last_chunk', -1)
    if coin_chunk == last_coin_chunk:
        return False

    ctx.cultivate_detail.turn_info.mant_coin_buy_done = True
    log.info(
        f"[COIN-BUY] coins={ctx.cultivate_detail.mant_coins} >= {coin_threshold} "
        f"(post_summer={post_summer}) — triggering emergency buy on already-scanned items"
    )

    ctx.cultivate_detail.turn_info.mant_emergency_shop_done = False
    ctx.cultivate_detail.mant_coin_buy_last_chunk = coin_chunk
    return handle_mant_emergency_shop_buys(ctx, current_date)


def handle_mant_main_menu(ctx, img, current_date):
    from module.umamusume.constants.game_constants import is_summer_camp_period

    if handle_mant_inventory_rescan_if_pending(ctx, current_date):
        return True

    if handle_mant_inventory_scan(ctx, current_date):
        return True

    if handle_mant_periodic_inventory_scan(ctx, current_date):
        return True

    from module.umamusume.scenario.mant.actions import (
        has_instant_use_items, handle_instant_use_items, handle_cupcake_use
    )
    if has_instant_use_items(ctx):
        handle_instant_use_items(ctx)
        ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
        return True

    if not getattr(ctx.cultivate_detail.turn_info, 'mant_cupcake_checked', False):
        ctx.cultivate_detail.turn_info.mant_cupcake_checked = True
        if handle_cupcake_use(ctx):
            return True
        # Mood still below Good and no cupcakes on hand: force one shop trip this turn
        # to buy them (and whatever else is allowed). They get used on the next pass.
        if _mood_needs_shop_for_cupcakes(ctx, current_date):
            ctx.cultivate_detail.turn_info.mant_force_shop_scan = True
            ctx.cultivate_detail.turn_info.mant_mood_shop_attempted = True
            ctx.cultivate_detail.turn_info.mant_cupcake_checked = False

    if not getattr(ctx.cultivate_detail.turn_info, 'mant_main_menu_coins_read', False):
        is_summer = is_summer_camp_period(current_date)
        is_climax = current_date > 72 or current_date < -72
        coins = read_shop_coins(img, is_summer, is_climax)
        ctx.cultivate_detail.turn_info.mant_main_menu_coins_read = True
        if coins >= 0:
            ctx.cultivate_detail.mant_coins = coins

    if handle_mant_shop_scan(ctx, current_date):
        return True

    if handle_mant_emergency_shop_buys(ctx, current_date):
        return True

    if handle_mant_coin_triggered_buy(ctx, current_date):
        return True

    handle_mant_on_sale(img)

    if handle_mant_afflictions(ctx, img):
        return True

    if handle_mant_cleat_shop_buy(ctx, current_date):
        return True

    return False


def handle_mant_on_sale(img):
    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    sale_result = image_match(img_gray, REF_MANT_ON_SALE)
    if sale_result.find_match:
        log.info("shop on sale")
        return True
    return False


def try_use_cure_items(ctx):
    from module.umamusume.scenario.mant.constants import AILMENT_CURE_MAP, AILMENT_CURE_ALL
    from module.umamusume.scenario.mant.actions import use_item_and_update_inventory
    from module.umamusume.scenario.mant.policy import get_chain_position

    _, total = get_chain_position(ctx)
    if total > 1:
        log.info(f"Race chain of {total} - skipping cure items")
        _set_item_trace(
            ctx,
            options=[],
            selected=[],
            result={"phase": "ailment_cure", "result": "skip", "reason": "race_chain_active"},
        )
        return False
    
    afflictions = getattr(ctx.cultivate_detail, 'mant_afflictions', [])
    if not afflictions:
        _set_item_trace(
            ctx,
            options=[],
            selected=[],
            result={"phase": "ailment_cure", "result": "skip", "reason": "no_afflictions"},
        )
        return False

    _ensure_item_fail_state(ctx)
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    options = []

    miracle_failed = _item_failed(ctx, AILMENT_CURE_ALL)
    miracle_selected = owned_map.get(AILMENT_CURE_ALL, 0) > 0 and not miracle_failed
    options.append(
        item_option(
            AILMENT_CURE_ALL,
            "ailment_cure",
            selected=miracle_selected,
            priority=1,
            skip_reason=None if miracle_selected else ("failed_this_turn" if miracle_failed else "no_owned"),
            current_num=owned_map.get(AILMENT_CURE_ALL, 0),
            planned_use="ailment_cure",
        )
    )
    if miracle_selected:
        log.info(f"using {AILMENT_CURE_ALL} for {afflictions}")
        if use_item_and_update_inventory(ctx, AILMENT_CURE_ALL):
            ctx.cultivate_detail.mant_afflictions = []
            from module.umamusume.persistence import save_afflictions
            save_afflictions(ctx.cultivate_detail.mant_afflictions)
            _clear_item_failed(ctx, AILMENT_CURE_ALL)
            _set_item_trace(
                ctx,
                options=options,
                selected=[selected_item(AILMENT_CURE_ALL)],
                result={"phase": "ailment_cure", "result": "ok", "item": AILMENT_CURE_ALL, "cured": list(afflictions)},
            )
            return True
        _mark_item_failed(ctx, AILMENT_CURE_ALL)

    used_any = False
    used_items = []
    remaining_afflictions = list(afflictions)
    for ailment in list(afflictions):
        for ailment_name, cure_name in AILMENT_CURE_MAP.items():
            if ailment_name.lower() not in ailment.lower():
                continue
            cure_failed = _item_failed(ctx, cure_name)
            options.append(
                item_option(
                    cure_name,
                    "ailment_cure",
                    selected=owned_map.get(cure_name, 0) > 0 and not cure_failed,
                    priority=2,
                    skip_reason=None if owned_map.get(cure_name, 0) > 0 and not cure_failed else ("failed_this_turn" if cure_failed else "no_owned"),
                    current_num=owned_map.get(cure_name, 0),
                    planned_use="ailment_cure",
                    payload={"affliction": ailment},
                    affliction=ailment,
                )
            )
            if owned_map.get(cure_name, 0) > 0:
                if cure_failed:
                    break
                log.info(f"using {cure_name} for {ailment}")
                if use_item_and_update_inventory(ctx, cure_name):
                    owned_map[cure_name] = max(0, owned_map.get(cure_name, 0) - 1)
                    afflictions.remove(ailment)
                    used_any = True
                    used_items.append(cure_name)
                    _clear_item_failed(ctx, cure_name)
                else:
                    _mark_item_failed(ctx, cure_name)
            break

    ctx.cultivate_detail.mant_afflictions = afflictions
    from module.umamusume.persistence import save_afflictions
    save_afflictions(ctx.cultivate_detail.mant_afflictions)
    if used_any:
        _set_item_trace(
            ctx,
            options=options,
            selected=[selected_item(name) for name in used_items],
            result={"phase": "ailment_cure", "result": "ok", "items": list(used_items), "remaining_afflictions": list(afflictions)},
        )
    else:
        _set_item_trace(
            ctx,
            options=options,
            selected=[],
            result={"phase": "ailment_cure", "result": "skip", "reason": "no_valid_cure_item", "remaining_afflictions": remaining_afflictions},
        )
    return used_any


def handle_mant_afflictions(ctx, img):
    from module.umamusume.constants.game_constants import is_summer_camp_period
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    current_date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    if is_summer_camp_period(current_date):
        medic_px = img_rgb[1118, 100]
    else:
        medic_px = img_rgb[1125, 43]
    medic_lit = medic_px[0] > 200 and medic_px[1] > 200 and medic_px[2] > 200
    if not medic_lit:
        ctx.cultivate_detail.mant_afflictions = []
        from module.umamusume.persistence import save_afflictions
        save_afflictions(ctx.cultivate_detail.mant_afflictions)
        return False
    if medic_lit and not ctx.cultivate_detail.mant_afflictions:
        from module.umamusume.scenario.mant.afflictions import detect_afflictions
        afflictions = detect_afflictions(ctx)
        ctx.cultivate_detail.mant_afflictions = afflictions
        from module.umamusume.persistence import save_afflictions
        save_afflictions(ctx.cultivate_detail.mant_afflictions)
        ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
        return True
    if ctx.cultivate_detail.mant_afflictions:
        if try_use_cure_items(ctx):
            ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
            return True
    return False


def color_match(px, target, tol):
    return (abs(int(px[0]) - target[0]) <= tol and
            abs(int(px[1]) - target[1]) <= tol and
            abs(int(px[2]) - target[2]) <= tol)


def handle_mant_rival_race(ctx, img):
    if getattr(ctx.cultivate_detail.turn_info, 'mant_rival_checked', False):
        return
    from module.umamusume.constants.game_constants import is_summer_camp_period
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    current_date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    rival_x = 497 if is_summer_camp_period(current_date) else 565
    px = img_rgb[1089, rival_x]
    if color_match(px, RIVAL_COLOR_1, RIVAL_TOLERANCE) or color_match(px, RIVAL_COLOR_2, RIVAL_TOLERANCE):
        log.info("rival race detected")
        ctx.cultivate_detail.turn_info.mant_rival_race_available = True
        ctx.cultivate_detail.turn_info.turn_operation = None
        ctx.cultivate_detail.turn_info.parse_train_info_finish = False
    else:
        ctx.cultivate_detail.turn_info.mant_rival_race_available = False
    ctx.cultivate_detail.turn_info.mant_rival_checked = True
