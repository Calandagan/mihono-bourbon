from __future__ import annotations

from module.umamusume.constants.game_constants import CLASSIC_YEAR_END, SUMMER_CAMP_2_END
from module.umamusume.scenario.mant.constants import get_incoming_mood

SHOP_STOCK_CAPS = {
    "Rich Hand Cream": 1,
    "Miracle Cure": 1,
    "Motivating Megaphone": 3,
    "Speed Training Application": 3,
    "Stamina Training Application": 3,
    "Power Training Application": 3,
    "Guts Training Application": 3,
    "Speed Ankle Weights": 3,
    "Stamina Ankle Weights": 3,
    "Power Ankle Weights": 3,
    "Guts Ankle Weights": 3,
}

CONTEXTUAL_ONLY_SHOP_ITEMS = {
    "Artisan Cleat Hammer",
    "Master Cleat Hammer",
}


def get_shop_item_ui_tier(mant_cfg, slug, default=0) -> int:
    tiers = getattr(mant_cfg, "item_tiers", {}) if mant_cfg else {}
    try:
        return int(tiers.get(slug, default))
    except Exception:
        return int(default)


def is_shop_item_disabled(mant_cfg, *, slug=None, display_name=None, display_to_slug=None) -> bool:
    if mant_cfg is None:
        return False
    if slug is None and display_name is not None and display_to_slug is not None:
        try:
            slug = display_to_slug(display_name)
        except Exception:
            slug = None
    if not slug:
        return False
    return get_shop_item_ui_tier(mant_cfg, slug, default=0) == 0


def get_deck_type_counts(pal_card_store) -> dict[int, int]:
    deck_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    try:
        pcs = pal_card_store or {}
        if isinstance(pcs, dict):
            for card_info in pcs.values():
                if not isinstance(card_info, dict):
                    continue
                c_type = card_info.get("type")
                if c_type is None:
                    continue
                if hasattr(c_type, "value"):
                    c_type = c_type.value
                if isinstance(c_type, str):
                    c_type_lower = c_type.lower()
                    if "speed" in c_type_lower:
                        c_type = 1
                    elif "stamina" in c_type_lower:
                        c_type = 2
                    elif "power" in c_type_lower:
                        c_type = 3
                    elif "guts" in c_type_lower or "will" in c_type_lower:
                        c_type = 4
                    elif "wit" in c_type_lower or "intelligence" in c_type_lower:
                        c_type = 5
                    else:
                        continue
                if isinstance(c_type, int) and 1 <= c_type <= 5:
                    deck_counts[c_type] += 1
    except Exception:
        pass
    return deck_counts


def deck_info_is_known(deck_counts) -> bool:
    try:
        return sum(int(v or 0) for v in (deck_counts or {}).values()) > 0
    except Exception:
        return False


def get_shop_stock_cap(display_name) -> int | None:
    return SHOP_STOCK_CAPS.get(display_name)


def is_contextual_shop_override_item(display_name) -> bool:
    return display_name in CONTEXTUAL_ONLY_SHOP_ITEMS


def get_shop_stock_state(display_name, owned_map) -> tuple[int, int | None]:
    current_num = int((owned_map or {}).get(display_name, 0) or 0)
    return current_num, get_shop_stock_cap(display_name)


def stock_cap_reached(display_name, owned_map) -> bool:
    current_num, cap = get_shop_stock_state(display_name, owned_map)
    return cap is not None and current_num >= cap


def compute_charm_purchase_state(current_date, owned_map, mant_cfg) -> tuple[int, bool]:
    charm_owned = int((owned_map or {}).get("Good-Luck Charm", 0) or 0)
    charm_base_tier = getattr(mant_cfg, "item_tiers", {}).get("good-luck_charm") if mant_cfg else None
    charm_effective_tier = 0
    if charm_base_tier is not None:
        charm_effective_tier = charm_base_tier - charm_owned
    is_senior_or_later = current_date > CLASSIC_YEAR_END
    charm_stop_qty = 2 if is_senior_or_later else 3
    charm_stop = charm_owned >= charm_stop_qty
    return charm_effective_tier, charm_stop


def compute_cupcake_purchase_state(current_date, current_mood, owned_map, mant_cfg) -> tuple[int | None, int | None]:
    owned_map = owned_map or {}
    cupcake_names = {"Plain Cupcake", "Berry Sweet Cupcake"}
    total_cupcakes = sum(int(owned_map.get(n, 0) or 0) for n in cupcake_names)
    is_senior_or_later = current_date > CLASSIC_YEAR_END

    skip_cupcakes = False
    if total_cupcakes >= 2:
        skip_cupcakes = True
    elif is_senior_or_later and (total_cupcakes >= 1 or current_mood is None or current_mood >= 5):
        skip_cupcakes = True
    elif current_mood is None or current_mood >= 5:
        skip_cupcakes = True
    else:
        incoming = get_incoming_mood(current_date, 3)
        if current_mood + 1 + incoming >= 5:
            skip_cupcakes = True

    cupcake_shift = total_cupcakes - 1 if skip_cupcakes else 0
    tiers = getattr(mant_cfg, "item_tiers", {}) if mant_cfg else {}
    plain_base = tiers.get("plain_cupcake")
    berry_base = tiers.get("berry_sweet_cupcake")
    plain_effective = plain_base - cupcake_shift if plain_base is not None else None
    berry_effective = berry_base - cupcake_shift if berry_base is not None else None
    return plain_effective, berry_effective


def compute_bbq_purchase_state(mant_cfg, detected_portraits_log) -> int | None:
    tiers = getattr(mant_cfg, "item_tiers", {}) if mant_cfg else {}
    bbq_base = tiers.get("grilled_carrots")
    if bbq_base is None:
        return None
    non_rainbow_count = 0
    portraits = detected_portraits_log or {}
    for info in portraits.values():
        if info.get("is_npc", False):
            continue
        if info.get("favor", 0) < 4:
            non_rainbow_count += 1
    bbq_threshold = getattr(mant_cfg, "bbq_unmaxxed_cards", 0)
    bbq_shift = non_rainbow_count - bbq_threshold if portraits else 0
    return bbq_base - bbq_shift


def collect_shop_copy_counts(items_list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, _conf, _gy, _turns, buyable in items_list or []:
        if buyable:
            counts[name] = counts.get(name, 0) + 1
    return counts


def collect_shop_turns(items_list) -> dict[str, int]:
    turns_map: dict[str, int] = {}
    for name, _conf, _gy, turns, buyable in items_list or []:
        if not buyable:
            continue
        if name not in turns_map or turns < turns_map[name]:
            turns_map[name] = turns
    return turns_map


def collect_priority_cure_targets(
    active_ailments,
    owned_map,
    shop_available,
    budget,
    ailment_cure_map,
    ailment_cure_all,
    shop_item_costs,
    *,
    mant_cfg=None,
    display_to_slug=None,
):
    owned_map = owned_map or {}
    shop_available = set(shop_available or set())
    bought_cures = set()
    priority_targets = []
    budget = int(budget or 0)
    has_miracle_cure = int(owned_map.get(ailment_cure_all, 0) or 0) > 0
    if active_ailments and not has_miracle_cure:
        needed_cures = set()
        for ailment, cure in ailment_cure_map.items():
            for active in active_ailments:
                if ailment.lower() in active.lower():
                    needed_cures.add(cure)
        for cure in needed_cures:
            if cure in bought_cures:
                continue
            if is_shop_item_disabled(mant_cfg, display_name=cure, display_to_slug=display_to_slug):
                continue
            if int(owned_map.get(cure, 0) or 0) <= 0 and cure in shop_available:
                cost = int(shop_item_costs.get(cure, 9999) or 9999)
                if cost <= budget:
                    priority_targets.append(cure)
                    bought_cures.add(cure)
                    budget -= cost
        if (
            not bought_cures.intersection(needed_cures)
            and ailment_cure_all in shop_available
            and not is_shop_item_disabled(mant_cfg, display_name=ailment_cure_all, display_to_slug=display_to_slug)
            and int(owned_map.get(ailment_cure_all, 0) or 0) <= 0
        ):
            cost = int(shop_item_costs.get(ailment_cure_all, 9999) or 9999)
            if cost <= budget:
                priority_targets.append(ailment_cure_all)
                bought_cures.add(ailment_cure_all)
                budget -= cost
    return priority_targets, bought_cures, budget


def collect_emergency_cure_targets(
    active_ailments,
    owned_map,
    shop_available,
    budget,
    ailment_cure_map,
    ailment_cure_all,
    shop_item_costs,
    *,
    existing_targets=None,
    bought_this_cycle=None,
    mant_cfg=None,
    display_to_slug=None,
):
    owned_map = owned_map or {}
    shop_available = set(shop_available or set())
    budget = int(budget or 0)
    planned = list(existing_targets or [])
    planned_set = set(planned)
    bought = set(bought_this_cycle or set())

    if int(owned_map.get(ailment_cure_all, 0) or 0) > 0:
        return planned, bought, budget

    any_uncovered = False
    for ailment in active_ailments or []:
        covered = False
        for ailment_name, cure_name in ailment_cure_map.items():
            if ailment_name.lower() not in ailment.lower():
                continue
            if (
                int(owned_map.get(cure_name, 0) or 0) > 0
                or cure_name in planned_set
                or cure_name in bought
            ):
                covered = True
                break
            if is_shop_item_disabled(mant_cfg, display_name=cure_name, display_to_slug=display_to_slug):
                break
            if cure_name in shop_available:
                cost = int(shop_item_costs.get(cure_name, 9999) or 9999)
                if cost <= budget:
                    planned.append(cure_name)
                    planned_set.add(cure_name)
                    bought.add(cure_name)
                    budget -= cost
                    covered = True
            break
        if not covered:
            any_uncovered = True

    if (
        any_uncovered
        and ailment_cure_all in shop_available
        and not is_shop_item_disabled(mant_cfg, display_name=ailment_cure_all, display_to_slug=display_to_slug)
        and ailment_cure_all not in planned_set
        and ailment_cure_all not in bought
        and int(owned_map.get(ailment_cure_all, 0) or 0) <= 0
    ):
        cost = int(shop_item_costs.get(ailment_cure_all, 9999) or 9999)
        if cost <= budget:
            planned.append(ailment_cure_all)
            bought.add(ailment_cure_all)
            budget -= cost

    return planned, bought, budget


def build_emergency_expiring_targets(
    *,
    current_date,
    budget,
    shop_items,
    mant_cfg,
    owned_map,
    deck_counts,
    used_buffs,
    one_time_buff_items,
    ignore_grilled_carrots,
    shop_item_costs,
    slug_to_display,
    display_to_slug,
    detected_portraits_log,
    ailment_cure_map,
    ailment_cure_all,
):
    if not mant_cfg or not getattr(mant_cfg, "item_tiers", None):
        return [], int(budget or 0)

    expiring = {
        name for name, _conf, _gy, turns, buyable in (shop_items or [])
        if turns == 1 and buyable
    }
    if not expiring:
        return [], int(budget or 0)

    shop_slugs = {
        display_to_slug(name)
        for name, _conf, _gy, _turns, buyable in (shop_items or [])
        if buyable
    }
    expiring_counts = collect_shop_copy_counts(
        [
            (name, conf, gy, turns, buyable)
            for name, conf, gy, turns, buyable in (shop_items or [])
            if buyable and name in expiring
        ]
    )
    budget = int(budget or 0)
    targets: list[str] = []
    post_senior_summer = current_date > SUMMER_CAMP_2_END

    cure_names = set(ailment_cure_map.values())
    known_deck = deck_info_is_known(deck_counts)
    for tier in range(1, getattr(mant_cfg, "tier_count", 0) + 1):
        tier_added = 0
        for slug, tier_value in getattr(mant_cfg, "item_tiers", {}).items():
            if tier_value != tier or slug not in shop_slugs:
                continue
            if int(tier_value or 0) < 1:
                continue

            display = slug_to_display.get(slug)
            if not display or display not in expiring:
                continue
            if display in cure_names or display == ailment_cure_all:
                continue
            if is_contextual_shop_override_item(display):
                continue
            if display in one_time_buff_items and display in used_buffs:
                continue
            if ignore_grilled_carrots and slug == "grilled_carrots":
                continue
            if display == "Energy Drink MAX" and int((owned_map or {}).get("Energy Drink MAX", 0) or 0) > 0:
                continue
            if stock_cap_reached(display, owned_map):
                continue

            if known_deck and ("Training Application" in display or "Ankle Weights" in display):
                if "Speed" in display and deck_counts.get(1, 0) == 0:
                    continue
                if "Stamina" in display and deck_counts.get(2, 0) == 0:
                    continue
                if "Power" in display and deck_counts.get(3, 0) == 0:
                    continue
                if "Guts" in display and deck_counts.get(4, 0) == 0:
                    continue
                if "Wit" in display and deck_counts.get(5, 0) == 0:
                    continue

            cost = int(shop_item_costs.get(display, 9999) or 9999)
            copies = expiring_counts.get(display, 0)
            if copies <= 0:
                continue
            threshold = 0
            if tier > 1 and not post_senior_summer:
                threshold = getattr(mant_cfg, "tier_thresholds", {}).get(tier, (tier - 1) * 50)
            for _ in range(copies):
                remaining_after = budget - cost
                if remaining_after < 0:
                    break
                if threshold > 0 and remaining_after < threshold:
                    break
                targets.append(display)
                budget -= cost
                tier_added += 1
        if tier_added > 0:
            break

    return targets, budget


def should_skip_shop_item(
    display_name,
    *,
    mant_cfg,
    priority_set,
    one_time_buff_items,
    used_buffs,
    ignore_cat,
    ignore_carrots,
    display_to_slug,
    all_cures,
    has_miracle_cure,
    owned_map,
    ailment_cure_all,
    deck_counts,
):
    if display_name in priority_set:
        return True
    if is_shop_item_disabled(mant_cfg, display_name=display_name, display_to_slug=display_to_slug):
        return True
    if is_contextual_shop_override_item(display_name):
        return True
    if display_name in one_time_buff_items and display_name in used_buffs:
        return True
    if ignore_cat and display_name == "Yummy Cat Food":
        return True
    if ignore_carrots and display_to_slug(display_name) == "grilled_carrots":
        return True
    if stock_cap_reached(display_name, owned_map):
        return True
    if display_name in all_cures:
        if int((owned_map or {}).get(display_name, 0) or 0) > 0:
            return True
    if display_name == ailment_cure_all and has_miracle_cure:
        return True
    if display_name == "Energy Drink MAX" and int((owned_map or {}).get("Energy Drink MAX", 0) or 0) > 0:
        return True
    known_deck = deck_info_is_known(deck_counts)
    if known_deck and ("Training Application" in display_name or "Ankle Weights" in display_name):
        if "Speed" in display_name and deck_counts.get(1, 0) == 0:
            return True
        if "Stamina" in display_name and deck_counts.get(2, 0) == 0:
            return True
        if "Power" in display_name and deck_counts.get(3, 0) == 0:
            return True
        if "Guts" in display_name and deck_counts.get(4, 0) == 0:
            return True
        if "Wit" in display_name and deck_counts.get(5, 0) == 0:
            return True
    return False


__all__ = [
    "build_emergency_expiring_targets",
    "collect_emergency_cure_targets",
    "collect_shop_copy_counts",
    "collect_shop_turns",
    "get_shop_stock_cap",
    "get_shop_stock_state",
    "get_deck_type_counts",
    "deck_info_is_known",
    "is_contextual_shop_override_item",
    "stock_cap_reached",
    "compute_bbq_purchase_state",
    "compute_charm_purchase_state",
    "compute_cupcake_purchase_state",
    "collect_priority_cure_targets",
    "get_shop_item_ui_tier",
    "is_shop_item_disabled",
    "should_skip_shop_item",
]
