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
    from module.umamusume.context import log_detected_items

    opened = open_items_panel(ctx)
    if not opened:
        ctx.ctrl.trigger_decision_reset = True
        return True

    owned = scan_inventory(ctx)
    ctx.cultivate_detail.mant_owned_items = owned
    from module.umamusume.persistence import save_inventory
    save_inventory(ctx.cultivate_detail.mant_owned_items)
    ctx.cultivate_detail.mant_inventory_scanned = True
    log_detected_items(owned)

    close_items_panel(ctx)
    ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
    return True


def handle_mant_inventory_rescan_if_pending(ctx, current_date):
    pending = getattr(ctx.cultivate_detail, 'mant_inventory_rescan_pending', False)
    if not pending:
        return False

    from module.umamusume.scenario.mant.scan import scan_inventory, open_items_panel, close_items_panel
    from module.umamusume.context import log_detected_items

    opened = open_items_panel(ctx)
    if not opened:
        ctx.ctrl.trigger_decision_reset = True
        return True

    owned = scan_inventory(ctx)
    ctx.cultivate_detail.mant_owned_items = owned
    from module.umamusume.persistence import save_inventory
    save_inventory(ctx.cultivate_detail.mant_owned_items)
    ctx.cultivate_detail.mant_inventory_scanned = True
    ctx.cultivate_detail.mant_inventory_rescan_pending = False
    log_detected_items(owned)
    close_items_panel(ctx)
    ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
    return True


def handle_mant_turn_start(ctx, current_date):
    from module.umamusume.scenario.mant.shop import is_shop_scan_turn, current_shop_chunk
    if not is_shop_scan_turn(current_date):
        return

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
    if ctx.cultivate_detail.mant_shop_scanned_this_turn:
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
        get_mant_shop_buy_floor,
    )
    from module.umamusume.scenario.mant.shop_policy import (
        collect_shop_copy_counts,
        collect_shop_turns,
        collect_priority_cure_targets,
        get_deck_type_counts,
        get_shop_stock_state,
        should_skip_shop_item,
    )
    if not is_shop_scan_turn(current_date):
        return False
    chunk = current_shop_chunk(current_date)
    last_chunk = getattr(ctx.cultivate_detail, 'mant_shop_last_chunk', -1)
    if chunk == last_chunk:
        return False

    log.info(f"[SHOP] Starting scan — date={current_date} chunk={chunk} coins={ctx.cultivate_detail.mant_coins}")
    scan_result = scan_mant_shop(ctx)
    if scan_result is None:
        log.warning("[SHOP] scan_mant_shop returned None — shop did not open or REF_SHOP_MANT_CHECK not found")
        ctx.ctrl.trigger_decision_reset = True
        return True

    items_list, ratio, drag_ratio, first_item_gy = scan_result
    ctx.cultivate_detail.mant_shop_items = items_list
    ctx.cultivate_detail.mant_shop_ratio = ratio
    ctx.cultivate_detail.mant_shop_drag_ratio = drag_ratio
    ctx.cultivate_detail.mant_shop_first_gy = first_item_gy
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
        shop_slugs = {display_to_slug(n) for n in shop_available}
        log.info(
            f"[SHOP] Budget={budget} reserve={coin_reserve} cap={coin_cap} | shop_slugs={shop_slugs}"
        )
        shop_copy_counts = collect_shop_copy_counts(items_list)

        img = ctx.ctrl.get_screen()
        any_sale = handle_mant_on_sale(img) if img is not None else False
        sale_modifier = 0.9 if any_sale else 1.0

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
        )
        if bought_cures:
            ctx.cultivate_detail._mant_bought_cures_this_cycle = bought_cures

        priority_set = set(priority_targets)

        all_cures = set(AILMENT_CURE_MAP.values())

        deck_counts = get_deck_type_counts(getattr(ctx.task.detail, 'pal_card_store', {}))

        def should_skip(display_name):
            return should_skip_shop_item(
                display_name,
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
                "ui_tier": mant_cfg.item_tiers.get(slug),
                "current_stock": current_num,
            }
            if max_stock is not None:
                option_meta[name]["max_stock"] = max_stock

        for tier in range(1, mant_cfg.tier_count + 1):
            tier_items = []
            for slug, t in mant_cfg.item_tiers.items():
                if t != tier or slug not in shop_slugs:
                    continue
                tier_items.append(slug)

            tier_items.sort(key=lambda s: shop_turns.get(SLUG_TO_DISPLAY.get(s), 99))

            for slug in tier_items:
                display = SLUG_TO_DISPLAY.get(slug)
                if not display:
                    continue
                if should_skip(display):
                    current_num, max_stock = get_shop_stock_state(display, owned_map)
                    if current_num and max_stock is not None and current_num >= max_stock:
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
                    remaining_after = budget - cost
                    if remaining_after < 0:
                        skip_overrides.setdefault(display, "budget_exhausted")
                        break
                    threshold = 0
                    if tier > 2:
                        raw_threshold = mant_cfg.tier_thresholds.get(tier, (tier - 1) * 50)
                        threshold = int(raw_threshold * sale_modifier)
                    floor = get_mant_shop_buy_floor(display, tier, current_date, start_budget, threshold, mant_cfg)
                    if remaining_after < floor:
                        skip_overrides.setdefault(display, "budget_floor")
                        break
                    tier_targets.append(display)
                    target_sources.setdefault(display, "tier_policy")
                    target_ui_tiers.setdefault(display, tier)
                    budget -= cost

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
            bought, held_items = buy_shop_items(ctx, targets, items_list, ratio, drag_ratio, first_item_gy)
            if bought:
                ctx.cultivate_detail.mant_inventory_rescan_pending = True
                total_spent = sum(SHOP_ITEM_COSTS.get(t, 0) for t in targets)
                budget_end = max(0, ctx.cultivate_detail.mant_coins - total_spent)
                ctx.cultivate_detail.mant_coins = budget_end
                bought_set = set(targets)
                ctx.cultivate_detail.mant_shop_items = [
                    (name, conf, gy, turns, buyable and (name not in bought_set))
                    for name, conf, gy, turns, buyable in items_list
                ]
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
        is_shop_scan_turn, scan_mant_shop, buy_shop_items,
        SHOP_ITEM_COSTS, SLUG_TO_DISPLAY, display_to_slug,
        BACK_BTN_X, BACK_BTN_Y,
    )
    from module.umamusume.scenario.mant.constants import AILMENT_CURE_MAP, AILMENT_CURE_ALL
    from module.umamusume.scenario.mant.shop_policy import (
        build_emergency_expiring_targets,
        collect_emergency_cure_targets,
        get_deck_type_counts,
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
        )
        ctx.cultivate_detail._mant_bought_cures_this_cycle = bought_this_cycle

    if not emergency_targets:
        return False

    scan_result = scan_mant_shop(ctx)
    if scan_result is None:
        ctx.ctrl.trigger_decision_reset = True
        return True

    ctx.cultivate_detail.turn_info.mant_emergency_shop_done = True
    items_list, ratio, drag_ratio, first_item_gy = scan_result
    ctx.cultivate_detail.mant_shop_items = items_list

    fresh_available = {name for name, _, _, _, buyable in items_list if buyable}
    final_targets = [tgt for tgt in emergency_targets if tgt in fresh_available]
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

    bought, _ = buy_shop_items(ctx, final_targets, items_list, ratio, drag_ratio, first_item_gy)
    if bought:
        ctx.cultivate_detail.mant_inventory_rescan_pending = True
        spent = sum(SHOP_ITEM_COSTS.get(tgt, 0) for tgt in final_targets)
        budget_end = max(0, ctx.cultivate_detail.mant_coins - spent)
        
        ctx.cultivate_detail.mant_coins = budget_end
        bought_set = set(final_targets)
        ctx.cultivate_detail.mant_shop_items = [
            (name, conf, gy, turns, buyable and (name not in bought_set))
            for name, conf, gy, turns, buyable in items_list
        ]
        from module.umamusume.context import log_detected_shop_items
        remaining = [(name, turns, buyable)
                     for name, _, _, turns, buyable in items_list
                     if buyable and name not in bought_set]
        log_detected_shop_items(remaining)
    else:
        ctx.ctrl.click(BACK_BTN_X, BACK_BTN_Y)
        _t.sleep(1)

    return True


CLIMAX_MASTER_RESERVE = 40


def _would_cleat_be_used(cleat_name, race_id, current_date, owned_map):
    from module.umamusume.scenario.mant.race_prep import would_cleat_be_useful_before_race

    return would_cleat_be_useful_before_race(cleat_name, race_id, current_date, owned_map)


def handle_mant_cleat_shop_buy(ctx, current_date):
    from module.umamusume.scenario.mant.shop import (
        SHOP_ITEM_COSTS, scan_mant_shop, buy_shop_items, BACK_BTN_X, BACK_BTN_Y
    )
    from module.umamusume.define import TurnOperationType
    from module.umamusume.scenario.mant.race_prep import get_cleat_state
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

    turn_op = getattr(ctx.cultivate_detail.turn_info, 'turn_operation', None)
    if not turn_op or getattr(turn_op, 'turn_operation_type', None) != TurnOperationType.RACE:
        return False
    race_id = int(getattr(turn_op, 'race_id', 0) or 0)
    if race_id <= 0:
        return False

    state = get_cleat_state(owned)
    reserve_total = state["reserve_total"]
    spare_total = state["spare_master"] + state["spare_artisan"]
    reserve_budget = CLIMAX_MASTER_RESERVE if reserve_total < 2 else 0

    for candidate in ('Artisan Cleat Hammer', 'Master Cleat Hammer'):
        if candidate not in shop_available:
            continue
        cost = SHOP_ITEM_COSTS.get(candidate, 9999)
        if cost > budget:
            continue
        if budget - cost < reserve_budget:
            continue
        useful = _would_cleat_be_used(candidate, race_id, current_date, owned)
        if not useful and reserve_total >= 2:
            continue
        return _execute_cleat_buy(
            ctx,
            candidate,
            cost,
            source="cleat_override",
            debug={
                "race_id": race_id,
                "climax_reserve": reserve_total,
                "spare_cleats": spare_total,
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
    items_list, ratio, drag_ratio, first_item_gy = scan_result
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

    bought, _ = buy_shop_items(ctx, [cleat_name], items_list, ratio, drag_ratio, first_item_gy)
    if bought:
        ctx.cultivate_detail.mant_inventory_rescan_pending = True
        ctx.cultivate_detail.mant_coins = max(0, ctx.cultivate_detail.mant_coins - cost)
        owned = dict(getattr(ctx.cultivate_detail, 'mant_owned_items', {}))
        owned[cleat_name] = owned.get(cleat_name, 0) + 1
        ctx.cultivate_detail.mant_owned_items = list(owned.items())
        from module.umamusume.persistence import save_inventory
        save_inventory(ctx.cultivate_detail.mant_owned_items)
        ctx.cultivate_detail.mant_shop_items = [
            (n, c, g, t, buyable and n != cleat_name)
            for n, c, g, t, buyable in items_list
        ]
        from module.umamusume.context import log_detected_shop_items
        log_detected_shop_items(
            [(n, t, buyable) for n, _, _, t, buyable in items_list if buyable and n != cleat_name]
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
    """Buy shop items when coins exceed threshold, bypassing the regular chunk schedule.

    Before Summer Camp 2 (date <= 64): triggers when coins >= 250, max once per 3-turn window.
    After Summer Camp 2 (date > 64):   triggers when coins >= 150, max once per 2-turn window.
    This ensures leftover coins are spent aggressively in the final stretch of the run.
    """
    if getattr(ctx.cultivate_detail.turn_info, 'mant_coin_buy_done', False):
        return False
    if ctx.cultivate_detail.mant_shop_scanned_this_turn:
        return False

    from module.umamusume.constants.game_constants import SUMMER_CAMP_2_END
    post_summer = current_date > SUMMER_CAMP_2_END

    # Differentiated threshold and window based on game phase
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
        f"(post_summer={post_summer}) — triggering extra shop scan (coin_chunk={coin_chunk})"
    )

    saved_last_chunk = getattr(ctx.cultivate_detail, 'mant_shop_last_chunk', -1)
    ctx.cultivate_detail.mant_shop_last_chunk = -1
    result = handle_mant_shop_scan(ctx, current_date)
    if result:
        ctx.cultivate_detail.mant_coin_buy_last_chunk = coin_chunk
    else:
        ctx.cultivate_detail.mant_shop_last_chunk = saved_last_chunk
    return result


def handle_mant_main_menu(ctx, img, current_date):
    from module.umamusume.constants.game_constants import is_summer_camp_period

    if handle_mant_inventory_rescan_if_pending(ctx, current_date):
        return True

    if handle_mant_inventory_scan(ctx, current_date):
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
