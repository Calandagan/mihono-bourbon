from __future__ import annotations

import time

import numpy as np

import bot.base.log as logger
from bot.recog.image_matcher import image_match
from module.umamusume.asset.template import REF_TEAM_SHOWDOWN
from module.umamusume.define import ScenarioType


log = logger.get_logger(__name__)

AOHARU_RETRY_REFERENCE_SIZE = (720, 1280)
AOHARU_TEAM_SHOWDOWN_HEADER_REGION = (0, 0, 230, 48)
AOHARU_LOSE_BANNER_REGION = (240, 390, 545, 570)
AOHARU_TRY_AGAIN_BUTTON_REGION = (65, 1142, 350, 1228)
AOHARU_NEXT_BUTTON_REGION = (370, 1142, 655, 1228)
AOHARU_TRY_AGAIN_CLICK = (205, 1185)
AOHARU_NEXT_CLICK = (515, 1185)
AOHARU_RETRY_CLICK_COOLDOWN = 8.0


def _is_aoharu(ctx) -> bool:
    try:
        return ctx.cultivate_detail.scenario.scenario_type() == ScenarioType.SCENARIO_TYPE_AOHARUHAI
    except Exception:
        return False


def _scale_region(screen, region):
    h, w = screen.shape[:2]
    ref_w, ref_h = AOHARU_RETRY_REFERENCE_SIZE
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


def _is_team_showdown_header(screen) -> bool:
    roi = _region(screen, AOHARU_TEAM_SHOWDOWN_HEADER_REGION)
    if roi is None:
        return False
    try:
        return image_match(roi.astype(np.uint8), REF_TEAM_SHOWDOWN).find_match
    except Exception:
        return False


def _green_button_state(screen, region):
    roi = _region(screen, region)
    if roi is None or roi.ndim < 3 or roi.shape[2] < 3:
        return {"present": False, "green": 0.0, "delta": 0.0}
    mean = np.mean(roi, axis=(0, 1))
    blue = float(mean[0])
    green = float(mean[1])
    red = float(mean[2])
    delta = green - max(red, blue)
    return {
        "present": green >= 125.0 and delta >= 25.0,
        "green": green,
        "delta": delta,
    }


def _try_again_button_state(screen):
    roi = _region(screen, AOHARU_TRY_AGAIN_BUTTON_REGION)
    next_state = _green_button_state(screen, AOHARU_NEXT_BUTTON_REGION)
    if roi is None:
        return {"present": False, "enabled": False, "brightness": 0.0, "std": 0.0}
    brightness = float(np.mean(roi))
    std = float(np.std(roi))
    present = brightness >= 105.0 and std >= 18.0 and next_state["present"]
    enabled = present and brightness >= 150.0
    return {
        "present": present,
        "enabled": enabled,
        "brightness": brightness,
        "std": std,
    }


def _lose_banner_state(screen):
    roi = _region(screen, AOHARU_LOSE_BANNER_REGION)
    if roi is None or roi.ndim < 3 or roi.shape[2] < 3:
        return {"lost": False, "blue_ratio": 0.0, "white_ratio": 0.0}
    blue = roi[:, :, 0]
    green = roi[:, :, 1]
    red = roi[:, :, 2]
    blue_mask = (
        (blue >= 135)
        & (green >= 85)
        & (red <= 215)
        & ((blue - red) >= 20)
    )
    white_mask = (blue >= 210) & (green >= 210) & (red >= 210)
    blue_ratio = float(np.mean(blue_mask))
    white_ratio = float(np.mean(white_mask))
    return {
        "lost": blue_ratio >= 0.035 and white_ratio >= 0.010,
        "blue_ratio": blue_ratio,
        "white_ratio": white_ratio,
    }


def aoharu_showdown_result_state(screen):
    next_state = _green_button_state(screen, AOHARU_NEXT_BUTTON_REGION)
    retry_state = _try_again_button_state(screen)
    header = _is_team_showdown_header(screen)
    present = header and next_state["present"] and retry_state["present"]
    lose_state = _lose_banner_state(screen)
    return {
        "present": present,
        "lost": present and lose_state["lost"],
        "retry_enabled": retry_state["enabled"],
        "retry_brightness": retry_state["brightness"],
        "retry_std": retry_state["std"],
        "lose_blue_ratio": lose_state["blue_ratio"],
        "lose_white_ratio": lose_state["white_ratio"],
        "next_green": next_state["green"],
        "next_delta": next_state["delta"],
    }


def mark_aoharu_showdown_retry_confirm_pending(ctx):
    detail = getattr(ctx, "cultivate_detail", None)
    if detail is None:
        return
    detail.aoharu_showdown_retry_confirm_pending = True
    detail.aoharu_showdown_retry_confirm_started_at = time.time()


def clear_aoharu_showdown_retry_confirm_pending(ctx):
    detail = getattr(ctx, "cultivate_detail", None)
    if detail is None:
        return
    detail.aoharu_showdown_retry_confirm_pending = False
    detail.aoharu_showdown_retry_confirm_started_at = 0.0


def has_aoharu_showdown_retry_confirm_pending(ctx, ttl: float = 12.0) -> bool:
    detail = getattr(ctx, "cultivate_detail", None)
    if detail is None or not getattr(detail, "aoharu_showdown_retry_confirm_pending", False):
        return False
    started_at = float(getattr(detail, "aoharu_showdown_retry_confirm_started_at", 0.0) or 0.0)
    if started_at > 0.0 and time.time() - started_at > ttl:
        clear_aoharu_showdown_retry_confirm_pending(ctx)
        return False
    return True


def handle_aoharu_showdown_retry_confirm(ctx) -> bool:
    if not _is_aoharu(ctx) or not has_aoharu_showdown_retry_confirm_pending(ctx):
        return False
    detail = ctx.cultivate_detail
    if int(getattr(detail, "clock_used", 0) or 0) >= int(getattr(detail, "clock_use_limit", 0) or 0):
        log.info("[AOHARU-RETRY] Clock limit reached before retry confirm; canceling")
        from module.umamusume.asset.point import RACE_FAIL_CONTINUE_CANCEL
        ctx.ctrl.click_by_point(RACE_FAIL_CONTINUE_CANCEL)
        clear_aoharu_showdown_retry_confirm_pending(ctx)
        return True
    from module.umamusume.asset.point import RACE_FAIL_CONTINUE_USE_CLOCK
    ctx.ctrl.click_by_point(RACE_FAIL_CONTINUE_USE_CLOCK)
    detail.clock_used = int(getattr(detail, "clock_used", 0) or 0) + 1
    log.info(
        "[AOHARU-RETRY] Confirmed lost showdown retry - clocks %s/%s",
        detail.clock_used,
        detail.clock_use_limit,
    )
    clear_aoharu_showdown_retry_confirm_pending(ctx)
    return True


def handle_aoharu_showdown_result(ctx, screen=None) -> bool:
    if not _is_aoharu(ctx):
        return False
    img = screen if screen is not None else getattr(ctx, "current_screen", None)
    state = aoharu_showdown_result_state(img)
    if not state["present"]:
        return False

    detail = ctx.cultivate_detail
    retry_enabled = bool(getattr(detail, "retry_lost_aoharu_showdowns", False))
    used = int(getattr(detail, "clock_used", 0) or 0)
    limit = int(getattr(detail, "clock_use_limit", 0) or 0)

    if state["lost"] and state["retry_enabled"] and retry_enabled and used < limit:
        last_click = float(getattr(detail, "aoharu_showdown_retry_last_click_at", 0.0) or 0.0)
        now = time.time()
        if now - last_click < AOHARU_RETRY_CLICK_COOLDOWN:
            log.info("[AOHARU-RETRY] Waiting for Try Again transition")
            return True
        detail.aoharu_showdown_retry_last_click_at = now
        mark_aoharu_showdown_retry_confirm_pending(ctx)
        x, y = AOHARU_TRY_AGAIN_CLICK
        log.info(
            "[AOHARU-RETRY] Lost Team Showdown detected - clicking Try Again "
            "(clocks %s/%s, blue_ratio=%.3f, retry_brightness=%.1f)",
            used,
            limit,
            state["lose_blue_ratio"],
            state["retry_brightness"],
        )
        ctx.ctrl.click(x, y, "Aoharu Team Showdown Try Again")
        return True

    if state["lost"] and retry_enabled and used >= limit:
        log.info("[AOHARU-RETRY] Lost Team Showdown accepted - clock limit reached %s/%s", used, limit)
    elif state["lost"] and retry_enabled and not state["retry_enabled"]:
        log.info("[AOHARU-RETRY] Lost Team Showdown accepted - Try Again disabled")
    elif state["lost"] and not retry_enabled:
        log.info("[AOHARU-RETRY] Lost Team Showdown accepted - retry toggle disabled")

    x, y = AOHARU_NEXT_CLICK
    ctx.ctrl.click(x, y, "Aoharu Team Showdown Next")
    return True
