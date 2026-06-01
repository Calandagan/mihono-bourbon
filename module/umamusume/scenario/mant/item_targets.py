from __future__ import annotations


def item_option(
    name,
    context,
    *,
    selected=False,
    priority=None,
    skip_reason=None,
    reason=None,
    current_num=None,
    planned_use=None,
    payload=None,
    debug=None,
    **extra,
):
    option = {
        "name": name,
        "context": context,
        "selected": bool(selected),
    }
    if priority is not None:
        option["priority"] = priority
    if skip_reason is not None:
        option["skip_reason"] = skip_reason
    if reason is not None:
        option["reason"] = reason
    if current_num is not None:
        option["current_num"] = int(current_num or 0)
    if planned_use is not None:
        option["planned_use"] = planned_use
    if payload is not None:
        option["payload"] = payload
    if debug is not None:
        option["debug"] = debug
    option.update(extra)
    return option


def selected_item(name, *, use_num=1, **extra):
    row = {
        "name": name,
        "use_num": int(use_num or 1),
    }
    row.update(extra)
    return row


__all__ = ["item_option", "selected_item"]
