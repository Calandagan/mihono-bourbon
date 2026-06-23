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
MANT_RETRY_ENABLED_BRIGHTNESS = 200.0
MANT_RETRY_PRESENT_MIN_BRIGHTNESS = 115.0
MANT_RETRY_PRESENT_MIN_STD = 30.0
MANT_RETRY_CLICK_COOLDOWN = 10.0


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
    if status is None or icon is None or text is None:
        return {
            "present": False,
            "enabled": False,
            "brightness": 0.0,
            "icon_std": 0.0,
            "text_std": 0.0,
        }

    brightness = float(np.mean(status))
    icon_std = float(np.std(icon))
    text_std = float(np.std(text))
    present = (
        brightness >= MANT_RETRY_PRESENT_MIN_BRIGHTNESS
        and icon_std >= MANT_RETRY_PRESENT_MIN_STD
        and text_std >= MANT_RETRY_PRESENT_MIN_STD
    )
    enabled = present and brightness >= MANT_RETRY_ENABLED_BRIGHTNESS
    return {
        "present": present,
        "enabled": enabled,
        "brightness": brightness,
        "icon_std": icon_std,
        "text_std": text_std,
    }


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
            "[DEBUT-RETRY] Retry cap reached - count=%s/%s brightness=%.1f; continuing",
            retry_count,
            MANT_DEBUT_RETRY_LIMIT,
            state["brightness"],
        )
        return False

    if not state["enabled"]:
        detail.mant_debut_retry_pending = False
        log.info(
            "[DEBUT-RETRY] Try Again disabled - brightness=%.1f; debut result accepted",
            state["brightness"],
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
        "[DEBUT-RETRY] Try Again enabled - brightness=%.1f; retrying debut with clock %s/%s",
        state["brightness"],
        retry_count,
        MANT_DEBUT_RETRY_LIMIT,
    )
    ctx.ctrl.click(x, y, "MANT Debut Try Again")
    return True
