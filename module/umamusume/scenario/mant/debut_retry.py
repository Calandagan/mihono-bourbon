from __future__ import annotations

import time

import numpy as np

import bot.base.log as logger
from module.umamusume.define import ScenarioType


log = logger.get_logger(__name__)

MANT_DEBUT_DATE = 12
MANT_DEBUT_RETRY_LIMIT = 5
MANT_RETRY_REFERENCE_SIZE = (720, 1280)
MANT_RETRY_CLICK = (202, 1179)
MANT_RETRY_STATUS_REGION = (118, 1150, 328, 1168)
MANT_RETRY_ICON_REGION = (72, 1152, 121, 1201)
MANT_RETRY_TEXT_REGION = (160, 1160, 286, 1194)
MANT_NEXT_BUTTON_REGION = (420, 1155, 620, 1200)
MANT_RETRY_ENABLED_BRIGHTNESS = 235.0
MANT_RETRY_PRESENT_MIN_BRIGHTNESS = 115.0
MANT_RETRY_PRESENT_MIN_STD = 30.0
MANT_NEXT_GREEN_MIN = 135.0
MANT_NEXT_GREEN_DELTA_MIN = 35.0
MANT_RETRY_CLICK_COOLDOWN = 10.0
MANT_BIG_RESULT_CORE_REGION = (60, 190, 330, 390)
MANT_BIG_RESULT_VISIBLE_MIN_RATIO = 0.025
MANT_BIG_RESULT_GOLD_MIN_RATIO = 0.018
MANT_BIG_RESULT_BROWN_MIN_RATIO = 0.018


def _is_mant(ctx) -> bool:
    try:
        return ctx.cultivate_detail.scenario.scenario_type() == ScenarioType.SCENARIO_TYPE_MANT
    except Exception:
        return getattr(getattr(ctx.task.detail, "scenario_config", None), "mant_config", None) is not None


def _current_date(ctx) -> int:
    turn_info = getattr(ctx.cultivate_detail, "turn_info", None)
    try:
        return int(getattr(turn_info, "date", 0) or 0)
    except Exception:
        return 0


def reset_mant_debut_retry_state(ctx) -> None:
    detail = ctx.cultivate_detail
    detail.mant_debut_retry_pending = False
    detail.mant_debut_retry_count = 0
    detail.mant_debut_retry_last_click_at = 0.0


def mark_mant_debut_race_started(ctx, source: str = "") -> bool:
    if not _is_mant(ctx) or _current_date(ctx) != MANT_DEBUT_DATE:
        return False

    detail = ctx.cultivate_detail
    if not hasattr(detail, "mant_debut_retry_count"):
        detail.mant_debut_retry_count = 0
    if not hasattr(detail, "mant_debut_retry_last_click_at"):
        detail.mant_debut_retry_last_click_at = 0.0

    detail.mant_debut_retry_pending = True
    detail.mant_debut_retry_source = source
    log.info(
        "[DEBUT-RETRY] Armed MANT debut retry - source=%s count=%s/%s",
        source or "unknown",
        detail.mant_debut_retry_count,
        MANT_DEBUT_RETRY_LIMIT,
    )
    return True


def _scale_region(screen, region):
    h, w = screen.shape[:2]
    ref_w, ref_h = MANT_RETRY_REFERENCE_SIZE
    x1, y1, x2, y2 = region
    sx = w / float(ref_w)
    sy = h / float(ref_h)
    return (
        max(0, min(w, int(round(x1 * sx)))),
        max(0, min(h, int(round(y1 * sy)))),
        max(0, min(w, int(round(x2 * sx)))),
        max(0, min(h, int(round(y2 * sy)))),
    )


def _region(screen, region):
    if screen is None or len(getattr(screen, "shape", ())) < 2:
        return None
    x1, y1, x2, y2 = _scale_region(screen, region)
    if x2 <= x1 or y2 <= y1:
        return None
    roi = screen[y1:y2, x1:x2]
    if roi.size == 0:
        return None
    return roi.astype(np.float32)


def mant_debut_retry_button_state(screen):
    status = _region(screen, MANT_RETRY_STATUS_REGION)
    icon = _region(screen, MANT_RETRY_ICON_REGION)
    text = _region(screen, MANT_RETRY_TEXT_REGION)
    next_button = _region(screen, MANT_NEXT_BUTTON_REGION)
    if status is None or icon is None or text is None or next_button is None:
        return {
            "present": False,
            "enabled": False,
            "brightness": 0.0,
            "icon_std": 0.0,
            "text_std": 0.0,
            "next_green": 0.0,
            "next_green_delta": 0.0,
        }

    brightness = float(np.mean(status))
    icon_std = float(np.std(icon))
    text_std = float(np.std(text))
    next_mean = np.mean(next_button, axis=(0, 1))
    next_green = float(next_mean[1])
    next_green_delta = float(next_mean[1] - max(next_mean[0], next_mean[2]))
    next_present = (
        next_green >= MANT_NEXT_GREEN_MIN
        and next_green_delta >= MANT_NEXT_GREEN_DELTA_MIN
    )
    present = (
        brightness >= MANT_RETRY_PRESENT_MIN_BRIGHTNESS
        and icon_std >= MANT_RETRY_PRESENT_MIN_STD
        and text_std >= MANT_RETRY_PRESENT_MIN_STD
        and next_present
    )
    enabled = present and brightness >= MANT_RETRY_ENABLED_BRIGHTNESS
    return {
        "present": present,
        "enabled": enabled,
        "brightness": brightness,
        "icon_std": icon_std,
        "text_std": text_std,
        "next_green": next_green,
        "next_green_delta": next_green_delta,
    }


def mant_debut_big_rank_state(screen):
    roi = _region(screen, MANT_BIG_RESULT_CORE_REGION)
    if roi is None or roi.ndim < 3 or roi.shape[2] < 3:
        return {
            "result": "unknown",
            "visible": False,
            "gold_ratio": 0.0,
            "brown_ratio": 0.0,
            "visible_ratio": 0.0,
        }

    b = roi[:, :, 0]
    g = roi[:, :, 1]
    r = roi[:, :, 2]

    gold = (
        (r >= 185)
        & (g >= 120)
        & (b <= 125)
        & ((r - b) >= 60)
        & ((g - b) >= 25)
    )
    brown = (
        (r >= 110)
        & (g >= 45)
        & (g <= 165)
        & (b <= 150)
        & ((r - g) >= 18)
        & ((r - b) >= 25)
    )
    white_outline = (r >= 215) & (g >= 215) & (b >= 215)

    gold_ratio = float(np.mean(gold))
    brown_ratio = float(np.mean(brown & ~gold))
    visible_ratio = float(np.mean(gold | brown | white_outline))
    visible = visible_ratio >= MANT_BIG_RESULT_VISIBLE_MIN_RATIO

    if visible and gold_ratio >= MANT_BIG_RESULT_GOLD_MIN_RATIO:
        result = "first"
    elif visible and brown_ratio >= MANT_BIG_RESULT_BROWN_MIN_RATIO:
        result = "not_first"
    else:
        result = "unknown"

    return {
        "result": result,
        "visible": visible,
        "gold_ratio": gold_ratio,
        "brown_ratio": brown_ratio,
        "visible_ratio": visible_ratio,
    }


def clear_mant_debut_retry_pending(ctx, reason: str = "") -> bool:
    detail = getattr(ctx, "cultivate_detail", None)
    if detail is None or not getattr(detail, "mant_debut_retry_pending", False):
        return False
    state = mant_debut_retry_button_state(getattr(ctx, "current_screen", None))
    detail.mant_debut_retry_pending = False
    log.info(
        "[DEBUT-RETRY] Clearing pending retry - reason=%s present=%s enabled=%s "
        "brightness=%.1f next_green=%.1f next_delta=%.1f",
        reason or "unknown",
        state["present"],
        state["enabled"],
        state["brightness"],
        state["next_green"],
        state["next_green_delta"],
    )
    return True


def _click_mant_debut_retry(ctx, state, reason: str) -> bool:
    detail = ctx.cultivate_detail
    retry_count = int(getattr(detail, "mant_debut_retry_count", 0) or 0)
    if retry_count >= MANT_DEBUT_RETRY_LIMIT:
        detail.mant_debut_retry_pending = False
        log.info(
            "[DEBUT-RETRY] Retry cap reached - count=%s/%s brightness=%.1f next_green=%.1f; continuing",
            retry_count,
            MANT_DEBUT_RETRY_LIMIT,
            state.get("brightness", 0.0),
            state.get("next_green", 0.0),
        )
        return False

    now = time.time()
    last_click_at = float(getattr(detail, "mant_debut_retry_last_click_at", 0.0) or 0.0)
    if now - last_click_at < MANT_RETRY_CLICK_COOLDOWN:
        log.info("[DEBUT-RETRY] Waiting for retry transition")
        return True

    retry_count += 1
    detail.mant_debut_retry_count = retry_count
    detail.mant_debut_retry_last_click_at = now
    x, y = MANT_RETRY_CLICK
    log.info(
        "[DEBUT-RETRY] Retrying debut via %s - brightness=%.1f next_green=%.1f clock=%s/%s",
        reason,
        state.get("brightness", 0.0),
        state.get("next_green", 0.0),
        retry_count,
        MANT_DEBUT_RETRY_LIMIT,
    )
    ctx.ctrl.click(x, y, "MANT Debut Try Again")
    return True


def maybe_handle_mant_debut_retry(ctx) -> bool:
    detail = getattr(ctx, "cultivate_detail", None)
    if detail is None or not _is_mant(ctx):
        return False
    if not getattr(detail, "mant_debut_retry_pending", False):
        return False

    state = mant_debut_retry_button_state(getattr(ctx, "current_screen", None))
    if not state["present"]:
        return False

    retry_count = int(getattr(detail, "mant_debut_retry_count", 0) or 0)
    if retry_count >= MANT_DEBUT_RETRY_LIMIT:
        detail.mant_debut_retry_pending = False
        log.info(
            "[DEBUT-RETRY] Retry cap reached - count=%s/%s brightness=%.1f next_green=%.1f; continuing",
            retry_count,
            MANT_DEBUT_RETRY_LIMIT,
            state["brightness"],
            state["next_green"],
        )
        return False

    if not state["enabled"]:
        detail.mant_debut_retry_pending = False
        log.info(
            "[DEBUT-RETRY] Try Again disabled - brightness=%.1f next_green=%.1f; debut result accepted",
            state["brightness"],
            state["next_green"],
        )
        return False

    return _click_mant_debut_retry(ctx, state, "enabled button")


def handle_mant_debut_retry_on_race_result(ctx, wait_seconds: float = 3.0, sample_interval: float = 0.25) -> bool:
    detail = getattr(ctx, "cultivate_detail", None)
    if detail is None or not _is_mant(ctx):
        return False
    if not getattr(detail, "mant_debut_retry_pending", False):
        return False

    deadline = time.time() + max(0.0, wait_seconds)
    last_button = None
    last_rank = None
    logged_sample = False

    while True:
        screen = getattr(ctx, "current_screen", None)
        button = mant_debut_retry_button_state(screen)
        rank = mant_debut_big_rank_state(screen)
        last_button = button
        last_rank = rank

        if button["present"] or rank["result"] != "unknown":
            log.info(
                "[DEBUT-RETRY] Race result sample present=%s enabled=%s rank=%s "
                "brightness=%.1f next_green=%.1f gold=%.3f brown=%.3f",
                button["present"],
                button["enabled"],
                rank["result"],
                button["brightness"],
                button["next_green"],
                rank["gold_ratio"],
                rank["brown_ratio"],
            )
            logged_sample = True

        if button["enabled"]:
            return _click_mant_debut_retry(ctx, button, "enabled button")

        if rank["result"] == "not_first":
            return _click_mant_debut_retry(ctx, button, "big result rank")

        if button["present"] and rank["result"] == "first":
            detail.mant_debut_retry_pending = False
            log.info(
                "[DEBUT-RETRY] Debut won - rank=first brightness=%.1f; accepting result",
                button["brightness"],
            )
            return False

        if time.time() >= deadline:
            break

        time.sleep(max(0.05, sample_interval))
        try:
            frame = ctx.ctrl.get_screen(force=True)
        except TypeError:
            frame = ctx.ctrl.get_screen()
        except Exception:
            frame = None
        if frame is not None:
            ctx.current_screen = frame

    if last_button and last_button["present"] and not last_button["enabled"]:
        detail.mant_debut_retry_pending = False
        log.info(
            "[DEBUT-RETRY] Try Again still disabled after wait - rank=%s brightness=%.1f; accepting result",
            (last_rank or {}).get("result", "unknown"),
            last_button["brightness"],
        )
        return False

    if not logged_sample:
        log.info("[DEBUT-RETRY] Race result retry wait timed out without stable button/rank signal")
    else:
        log.info(
            "[DEBUT-RETRY] Race result retry wait timed out - present=%s enabled=%s rank=%s brightness=%.1f",
            bool(last_button and last_button["present"]),
            bool(last_button and last_button["enabled"]),
            (last_rank or {}).get("result", "unknown"),
            (last_button or {}).get("brightness", 0.0),
        )
    return False
