import cv2
import time

import bot.base.log as logger
from bot.recog.image_matcher import image_match
from module.umamusume.context import UmamusumeContext
from module.umamusume.constants.game_constants import is_summer_camp_period

log = logger.get_logger(__name__)


def should_use_pal_outing_simple(ctx: UmamusumeContext):
    if not getattr(ctx.cultivate_detail, 'prioritize_recreation', False):
        return False
    if ctx.cultivate_detail.pal_event_stage <= 0:
        return False

    ti = ctx.cultivate_detail.turn_info
    if ti is None:
        return False
    cached = getattr(ti, 'pal_outing_cached', None)
    cached_date = getattr(ti, 'pal_outing_cached_date', -1)
    if cached is not None and cached_date == ti.date:
        return cached

    img = ctx.current_screen
    if img is None:
        return False

    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    from module.umamusume.asset.template import UI_RECREATION_FRIEND_NOTIFICATION
    result = image_match(img_gray, UI_RECREATION_FRIEND_NOTIFICATION)
    if not result.find_match:
        ti.pal_outing_cached = False
        ti.pal_outing_cached_date = ti.date
        return False

    pal_thresholds = ctx.cultivate_detail.pal_thresholds
    if not pal_thresholds:
        ti.pal_outing_cached = False
        ti.pal_outing_cached_date = ti.date
        return False

    stage = ctx.cultivate_detail.pal_event_stage
    if stage > len(pal_thresholds):
        ti.pal_outing_cached = False
        ti.pal_outing_cached_date = ti.date
        return False

    thresholds = pal_thresholds[stage - 1]
    mood_threshold = thresholds[0]
    energy_threshold = thresholds[1]

    from bot.conn.fetch import fetch_state
    state = fetch_state()
    current_energy = state.get("energy", 0)
    current_mood_raw = state.get("mood")
    current_mood = current_mood_raw if current_mood_raw is not None else 4

    mood_below = current_mood <= mood_threshold
    energy_below = current_energy <= energy_threshold

    log.info(f"PAL outing check - Stage {stage}:")
    log.info(f"Mood: {current_mood} vs {mood_threshold} - {'<=' if mood_below else '>'}")
    log.info(f"Energy: {current_energy} vs {energy_threshold} - {'<=' if energy_below else '>'}")

    should_outing = mood_below and energy_below
    if should_outing:
        log.info("Both conditions met - using pal outing instead of rest")
    else:
        log.info("Conditions not met - using rest")

    ti.pal_outing_cached = should_outing
    ti.pal_outing_cached_date = ti.date
    return should_outing


def detect_pal_stage(ctx: UmamusumeContext, img):
    pal_name = ctx.cultivate_detail.pal_name
    pal_thresholds = ctx.cultivate_detail.pal_thresholds

    if not pal_name or not pal_thresholds:
        log.error("PAL configuration missing")
        return 0

    pal_data = pal_thresholds
    num_stages = len(pal_data)

    coords_to_check = []
    if num_stages == 3:
        coords_to_check = [(554, 474), (605, 474)]
    elif num_stages == 4:
        coords_to_check = [(503, 474), (554, 474), (605, 474)]
    elif num_stages == 5:
        coords_to_check = [(452, 474), (503, 474), (554, 474), (605, 474)]

    matching_pixels = 0
    for x, y in coords_to_check:
        pixel_color = img[y, x]
        b, g, r = pixel_color[0], pixel_color[1], pixel_color[2]
        is_match = abs(b - 223) <= 5 and abs(g - 227) <= 5 and abs(r - 231) <= 5
        if is_match:
            matching_pixels += 1

    calculated_stage = len(coords_to_check) - matching_pixels + 1
    return calculated_stage
