import time
import re
import random
import cv2
import numpy as np
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor

from bot.recog.ocr import ocr
from rapidfuzz import process, fuzz
import bot.base.log as logger

from module.umamusume.scenario.mant.shop import (
    SHOP_ITEM_NAMES, EFFECT_PREFIXES,
    SB_X, SB_X_MIN, SB_X_MAX,
    _gauss_scan_x,
)

log = logger.get_logger(__name__)

MAX_ENERGY_OCR_X1 = 456
MAX_ENERGY_OCR_Y1 = 219
MAX_ENERGY_OCR_X2 = 516
MAX_ENERGY_OCR_Y2 = 243

def ocr_max_energy_from_screen(img):
    if img is None:
        return None
    try:
        h, w = img.shape[:2]
        x1 = min(MAX_ENERGY_OCR_X1, w - 1)
        y1 = min(MAX_ENERGY_OCR_Y1, h - 1)
        x2 = min(MAX_ENERGY_OCR_X2, w)
        y2 = min(MAX_ENERGY_OCR_Y2, h)
        if x2 <= x1 or y2 <= y1:
            return None
        roi = img[y1:y2, x1:x2]
        roi_scaled = cv2.resize(roi, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(roi_scaled, cv2.COLOR_BGR2GRAY)
        _, thr = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        roi_ocr = cv2.cvtColor(thr, cv2.COLOR_GRAY2BGR)
        raw = ocr(roi_ocr, lang="en")
        if not raw or not raw[0]:
            return None
        for entry in raw[0]:
            if not entry or len(entry) < 2:
                continue
            text = entry[1][0].strip()
            digits = re.sub(r'[^0-9]', '', text)
            if digits:
                val = int(digits)
                if 50 <= val <= 999:
                    return val
        return None
    except Exception:
        return None


def sync_max_energy_to_scanner(ctx):
    max_energy = getattr(ctx.cultivate_detail, 'mant_max_energy', 100)
    from bot.recog.energy_scanner import set_max_energy
    set_max_energy(max_energy)


def update_max_energy_from_ocr(ctx):
    frame = ctx.ctrl.get_screen()
    if frame is None:
        return False
    detected = ocr_max_energy_from_screen(frame)
    if detected is None:
        return False
    current_max = getattr(ctx.cultivate_detail, 'mant_max_energy', 100)
    if detected > current_max:
        ctx.cultivate_detail.mant_max_energy = detected
        log.info(f"new max energy: {detected}")
        sync_max_energy_to_scanner(ctx)
        return True
    return False


INV_TRACK_TOP = 120
INV_TRACK_BOT = 1060
INV_CONTENT_TOP = 90
INV_CONTENT_BOT = 1080
INV_CONTENT_X1 = 30
INV_CONTENT_X2 = 640
SCREEN_WIDTH = 720
OCR_X1 = 60
OCR_X2 = 560
OCR_Y1 = 50
OCR_Y2 = 1080


def inv_find_thumb(img_rgb):
    from module.umamusume.scenario.mant.shop import is_thumb
    top = bot = None
    for y in range(INV_TRACK_TOP, INV_TRACK_BOT + 1):
        r, g, b = int(img_rgb[y, SB_X, 0]), int(img_rgb[y, SB_X, 1]), int(img_rgb[y, SB_X, 2])
        if is_thumb(r, g, b):
            if top is None:
                top = y
            bot = y
    return (top, bot) if top is not None else None


def inv_at_top(img_rgb):
    thumb = inv_find_thumb(img_rgb)
    if thumb is None:
        return False
    return thumb[0] <= INV_TRACK_TOP + 10


def inv_at_bottom(img_rgb):
    from module.umamusume.scenario.mant.shop import is_track
    thumb = inv_find_thumb(img_rgb)
    if thumb is None:
        return True
    for y in range(thumb[1] + 1, INV_TRACK_BOT + 1):
        r, g, b = int(img_rgb[y, SB_X, 0]), int(img_rgb[y, SB_X, 1]), int(img_rgb[y, SB_X, 2])
        if is_track(r, g, b):
            return False
    return True


def inv_content_gray(img):
    return cv2.cvtColor(img[INV_CONTENT_TOP:INV_CONTENT_BOT, INV_CONTENT_X1:INV_CONTENT_X2], cv2.COLOR_BGR2GRAY)


def inv_content_same(before, after):
    b = inv_content_gray(before)
    a = inv_content_gray(after)
    diff = cv2.absdiff(b, a)
    return cv2.mean(diff)[0] < 3


def inv_find_content_shift(before, after):
    bg = inv_content_gray(before)
    ag = inv_content_gray(after)
    ch = bg.shape[0]
    strip_h = 80
    best_shift = 0
    best_conf = 0
    for strip_y in [ch - strip_h - 10, ch - strip_h - 80, ch // 2]:
        if strip_y < 0 or strip_y + strip_h > ch:
            continue
        strip = bg[strip_y:strip_y + strip_h]
        result = cv2.matchTemplate(ag, strip, cv2.TM_CCOEFF_NORMED)
        _, mv, _, ml = cv2.minMaxLoc(result)
        if mv > best_conf:
            best_conf = mv
            if mv > 0.85:
                best_shift = strip_y - ml[1]
    return best_shift, best_conf




def sb_drag(ctx, from_y, to_y):
    # Deterministic, pure-vertical scrollbar drag for precise/repeatable scrolling
    dist = abs(to_y - from_y)
    dur = max(160, min(600, int(dist * 0.75)))
    from_y, to_y = max(110, from_y), max(110, to_y)
    ctx.ctrl.swipe(SB_X, from_y, SB_X, to_y, duration=dur / 1000.0)
    time.sleep(0.20)


def scroll_to_top(ctx):
    for _ in range(15):
        img = ctx.ctrl.get_screen()
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if inv_at_top(img_rgb):
            return
        thumb = inv_find_thumb(img_rgb)
        if thumb is None:
            continue
        sb_drag(ctx, (thumb[0] + thumb[1]) // 2, INV_TRACK_TOP)


def is_effect_text(text):
    lower = text.lower()
    return any(lower.startswith(p) for p in EFFECT_PREFIXES) or any(
        lower.startswith(p) for p in (
            'support', 'cure', 'max energy', 'fan ',
            'failure', 'increase', 'reroll', 'choose',
        )
    )


def parse_held_qty(text):
    digits = re.sub(r'[^0-9]', '', text)
    if not digits:
        return None
    n = len(digits)
    if n % 2 == 0:
        first_half = digits[:n // 2]
        second_half = digits[n // 2:]
        if first_half == second_half:
            return int(first_half)
    return int(digits)


def classify_names_only(frame):
    roi = frame[OCR_Y1:OCR_Y2, OCR_X1:OCR_X2]
    raw = ocr(roi, lang="en")
    if not raw or not raw[0]:
        return []
    items = []
    seen_y = []
    for entry in raw[0]:
        if not entry or len(entry) < 2:
            continue
        bbox = entry[0]
        text = entry[1][0].strip()
        conf = entry[1][1]
        y_center = (bbox[0][1] + bbox[2][1]) / 2
        abs_y = OCR_Y1 + y_center
        if len(text) < 3 or conf < 0.4:
            continue
        lower = text.lower()
        if lower in ('held', 'effect', 'cost', 'new', 'turn(s)', 'choose how many to use.',
                      'close', 'confirm use', 'training items', 'confirm', 'cancel'):
            continue
        if text.replace('+', '').replace('-', '').replace(' ', '').replace('.', '').replace('>', '').isdigit():
            continue
        if text.startswith('+') or text.startswith('-'):
            continue
        if is_effect_text(text):
            continue
        if '>' in text or 'held' in lower:
            continue
        match = process.extractOne(text, SHOP_ITEM_NAMES, scorer=fuzz.ratio, score_cutoff=55)
        if not match:
            continue
        matched_name, match_score, _ = match
        is_dup = False
        for sy in seen_y:
            if abs(abs_y - sy) < 40:
                is_dup = True
                break
        if is_dup:
            continue
        items.append((matched_name, match_score, abs_y))
        seen_y.append(abs_y)
    items.sort(key=lambda r: r[2])
    return items


def read_qty_at(frame, item_y):
    qty_y1 = int(item_y + 28)
    qty_y2 = int(item_y + 58)
    qty_x1 = 240
    qty_x2 = 370
    h, w = frame.shape[:2]
    if qty_y1 < 0 or qty_y2 > h or qty_x1 < 0 or qty_x2 > w:
        return 1
    roi = frame[qty_y1:qty_y2, qty_x1:qty_x2]
    try:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        _, thr = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        roi_ocr = cv2.cvtColor(thr, cv2.COLOR_GRAY2BGR)
    except Exception:
        roi_ocr = roi

    raw = ocr(roi_ocr, lang="en")
    if not raw or not raw[0]:
        return 1
    for entry in raw[0]:
        if not entry or len(entry) < 2:
            continue
        text = entry[1][0].strip()
        parsed = parse_held_qty(text)
        if parsed is None:
            continue
        if parsed <= 0:
            continue
        if parsed > 9:
            continue
        return parsed
    return 1


def classify_with_qty(frame):
    roi = frame[OCR_Y1:OCR_Y2, OCR_X1:OCR_X2]
    raw = ocr(roi, lang="en")
    if not raw or not raw[0]:
        return []
    items = []
    seen_y = []
    for entry in raw[0]:
        if not entry or len(entry) < 2:
            continue
        bbox = entry[0]
        text = entry[1][0].strip()
        conf = entry[1][1]
        y_center = (bbox[0][1] + bbox[2][1]) / 2
        abs_y = OCR_Y1 + y_center
        if len(text) < 3 or conf < 0.4:
            continue
        lower = text.lower()
        if lower in ('held', 'effect', 'cost', 'new', 'turn(s)', 'choose how many to use.',
                      'close', 'confirm use', 'training items', 'confirm', 'cancel'):
            continue
        if text.replace('+', '').replace('-', '').replace(' ', '').replace('.', '').replace('>', '').isdigit():
            continue
        if text.startswith('+') or text.startswith('-'):
            continue
        if is_effect_text(text):
            continue
        if '>' in text or 'held' in lower:
            continue
        match = process.extractOne(text, SHOP_ITEM_NAMES, scorer=fuzz.ratio, score_cutoff=55)
        if not match:
            continue
        matched_name, match_score, _ = match
        is_dup = False
        for sy in seen_y:
            if abs(abs_y - sy) < 40:
                is_dup = True
                break
        if is_dup:
            continue
        qty = read_qty_at(frame, abs_y)
        items.append((matched_name, match_score, abs_y, qty))
        seen_y.append(abs_y)
    items.sort(key=lambda r: r[2])
    return items


def dedup_names(all_detections, captured_frames):
    by_frame = defaultdict(list)
    for key, conf, fi, abs_y in all_detections:
        by_frame[fi].append((key, conf, abs_y))
    sorted_frames = sorted(by_frame.keys())
    if not sorted_frames:
        return []
    cumulative_shift = {sorted_frames[0]: 0}
    for i in range(1, len(sorted_frames)):
        prev_fi = sorted_frames[i - 1]
        curr_fi = sorted_frames[i]
        content_shift = 0
        if prev_fi in captured_frames and curr_fi in captured_frames:
            shift, conf = inv_find_content_shift(captured_frames[prev_fi], captured_frames[curr_fi])
            if conf > 0.85 and shift > 0:
                content_shift = shift
        if content_shift == 0:
            prev_items = [(k, y) for k, c, y in by_frame[prev_fi]]
            curr_items = [(k, y) for k, c, y in by_frame[curr_fi]]
            shifts = []
            used = set()
            for pk, py in prev_items:
                best_s = None
                best_d = 9999
                best_ci = -1
                for ci, (ck, cy) in enumerate(curr_items):
                    if ci in used or pk != ck:
                        continue
                    dist = abs(py - cy)
                    if dist < best_d:
                        best_d = dist
                        best_s = py - cy
                        best_ci = ci
                if best_s is not None:
                    shifts.append(best_s)
                    used.add(best_ci)
            if shifts:
                shifts.sort()
                content_shift = shifts[len(shifts) // 2]
        cumulative_shift[curr_fi] = cumulative_shift[prev_fi] + content_shift
    global_dets = []
    for key, conf, fi, abs_y in all_detections:
        gy = abs_y + cumulative_shift.get(fi, 0)
        global_dets.append((key, conf, fi, gy))
    global_dets.sort(key=lambda d: d[3])
    clusters = []
    for key, conf, fi, gy in global_dets:
        placed = False
        for cluster in clusters:
            cluster_gy = sum(d[3] for d in cluster) / len(cluster)
            if abs(gy - cluster_gy) < 80:
                cluster.append((key, conf, fi, gy))
                placed = True
                break
        if not placed:
            clusters.append([(key, conf, fi, gy)])
    items_list = []
    for cluster in clusters:
        name_counts = Counter()
        name_best_conf = {}
        for k, c, fi, gy in cluster:
            name_counts[k] += 1
            if k not in name_best_conf or c > name_best_conf[k]:
                name_best_conf[k] = c
        winner = max(name_counts.keys(), key=lambda n: (name_counts[n], name_best_conf[n]))
        avg_gy = sum(d[3] for d in cluster) / len(cluster)
        items_list.append((winner, name_best_conf[winner], avg_gy))
    items_list.sort(key=lambda x: x[2])
    return items_list


def _accumulate_inventory_items(item_qtys, frame):
    if frame is None:
        return item_qtys
    for name, score, y, qty in classify_with_qty(frame):
        if 130 < y < 1030:
            item_qtys[name] = max(qty, item_qtys.get(name, 0))
    return item_qtys


def scan_inventory(ctx, stop_when_found=None):
    scroll_to_top(ctx)
    time.sleep(0.3)

    img = ctx.ctrl.get_screen()
    if img is None:
        return []

    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    thumb = inv_find_thumb(img_rgb)

    if thumb is None:
        results = classify_with_qty(img)
        owned = [(name, qty) for name, score, y, qty in results if 130 < y < 1030]
        owned.sort(key=lambda x: x[0])
        return owned

    time.sleep(random.uniform(0.2, 0.4))
    
    item_qtys = {}
    
    # Initial scan of the top view
    frame = ctx.ctrl.get_screen()
    item_qtys = _accumulate_inventory_items(item_qtys, frame)

    reached_bottom = False

    # Segmented scroll loop
    for _segment in range(36):
        if not ctx.task.running():
            break
            
        img = ctx.ctrl.get_screen()
        if img is None:
            break
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if inv_at_bottom(img_rgb):
            item_qtys = _accumulate_inventory_items(item_qtys, img)
            reached_bottom = True
            break
            
        thumb = inv_find_thumb(img_rgb)
        if thumb is None:
            break
            
        cursor = (thumb[0] + thumb[1]) // 2
        thumb_h = thumb[1] - thumb[0]
        step = max(int(thumb_h * 1.1), 40)
        target_y = min(INV_TRACK_BOT, cursor + step)
        
        if target_y <= cursor + 10:
            reached_bottom = True
            break
            
        seg_dur = 850

        # Pure-vertical scrollbar drag (deterministic) while capturing frames
        proc = ctx.ctrl.swipe_async(SB_X, cursor, SB_X, target_y, seg_dur)
        
        # Scan during this segment's motion
        segment_end_time = time.time() + (seg_dur / 1000.0) + 0.2
        while proc.is_alive() and time.time() < segment_end_time:
            time.sleep(0.1)
            frame = ctx.ctrl.get_screen()
            item_qtys = _accumulate_inventory_items(item_qtys, frame)
            
            if stop_when_found and stop_when_found in item_qtys:
                break
        
        if stop_when_found and stop_when_found in item_qtys:
            break

        settled = ctx.ctrl.get_screen()
        item_qtys = _accumulate_inventory_items(item_qtys, settled)
        if stop_when_found and stop_when_found in item_qtys:
            break
            
        # Pause briefly between segments as if the user is looking at the screen
        time.sleep(random.uniform(0.3, 0.7))

    log.info(f"[INVENTORY] Scan complete — found {len(item_qtys)} items: {dict(item_qtys)}")

    if not stop_when_found and not reached_bottom:
        log.warning("[INVENTORY] Scan ended before confirming bottom of inventory list")

    owned = [(name, qty) for name, qty in item_qtys.items()]

    stat_items = {
        "Speed Scroll", "Stamina Scroll", "Power Scroll", "Guts Scroll", "Wit Scroll",
        "Speed Notepad", "Stamina Notepad", "Power Notepad", "Guts Notepad", "Wit Notepad",
        "Speed Manual", "Stamina Manual", "Power Manual", "Guts Manual", "Wit Manual",
        "Speed Training Application", "Stamina Training Application",
        "Power Training Application", "Guts Training Application", "Wit Training Application",
    }
    owned_names = {name for name, qty in owned}
    if any(item in stat_items for item in owned_names):
        for _ in range(3):
            log.info("TURN AUTO USE PROSHOP ITEMS ON IN GAME SETTINGS")

    from module.umamusume.persistence import get_ignore_cat_food, get_ignore_grilled_carrots
    if get_ignore_cat_food():
        owned = [(name, qty) for name, qty in owned if name != "Yummy Cat Food"]
    if get_ignore_grilled_carrots():
        owned = [(name, qty) for name, qty in owned if name != "Grilled Carrots"]

    owned.sort(key=lambda x: x[0])
    scroll_to_top(ctx)
    return owned



def find_plus_buttons(frame):
    from module.umamusume.asset.template import REF_MANT_PLUS
    template = cv2.imread(REF_MANT_PLUS.template_path)
    if template is None:
        return []
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    tmpl_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    th, tw = tmpl_gray.shape[:2]
    result = cv2.matchTemplate(gray, tmpl_gray, cv2.TM_CCOEFF_NORMED)
    threshold = 0.8
    loc = np.where(result >= threshold)
    buttons = []
    for pt in zip(*loc[::-1]):
        cx = pt[0] + tw // 2
        cy = pt[1] + th // 2
        if any(abs(cx - bx) < 10 and abs(cy - by) < 10 for bx, by in buttons):
            continue
        buttons.append((cx, cy))
    return buttons


def try_click_item_plus_once(ctx, item_name: str) -> tuple[bool, bool]:
    scroll_to_top(ctx)
    prev_cursor = -1
    stall_count = 0
    found_names = []
    reached_bottom = False
    for iteration in range(60):
        time.sleep(0.18)
        frame = ctx.ctrl.get_screen()
        if frame is None:
            continue
        items = classify_names_only(frame)
        target_y = None
        for name, score, abs_y in items:
            if name == item_name:
                target_y = abs_y
                break
            if name not in found_names:
                found_names.append(name)
        if target_y is not None and 130 < target_y < 1030:
            plus_buttons = find_plus_buttons(frame)
            if not plus_buttons:
                log.warning(f"No + buttons found on screen")
                plus_x = 648
                plus_y = int(round(target_y + 48))
                ctx.ctrl.click(plus_x, plus_y, name="item plus button fallback")
                time.sleep(0.25)
                return True, True
            best_button = None
            best_dy = float('inf')
            for bx, by in plus_buttons:
                dy = abs(by - target_y)
                if dy < best_dy:
                    best_dy = dy
                    best_button = (bx, by)
            if best_button and best_dy < 80:
                log.info(f"Clicking + for '{item_name}' at ({best_button[0]}, {best_button[1]}), dy={best_dy:.1f}")
                ctx.ctrl.click(best_button[0], best_button[1], name="exchange item button")
                time.sleep(0.25)
                return True, True
            else:
                log.warning(f"No + button found near '{item_name}' (y={target_y:.1f}), best dy={best_dy:.1f}")
                plus_x = 648
                plus_y = int(round(target_y + 48))
                ctx.ctrl.click(plus_x, plus_y, name="item plus button fallback")
                time.sleep(0.25)
                return True, True

        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        if inv_at_bottom(img_rgb):
            reached_bottom = True
            break
        thumb = inv_find_thumb(img_rgb)
        if thumb is None:
            log.info(f"[INVENTORY] No thumb found at iteration {iteration}, stopping scroll")
            break

        cursor = (thumb[0] + thumb[1]) // 2
        th = thumb[1] - thumb[0]
        if prev_cursor >= 0 and abs(cursor - prev_cursor) < 5:
            stall_count += 1
            if stall_count >= 3:
                log.info(f"[INVENTORY] Scroll stalled at iteration {iteration} (cursor={cursor}), stopping")
                break
        else:
            stall_count = 0
        prev_cursor = cursor

        step = max(int(th * 1.1), 40)
        target = min(INV_TRACK_BOT, cursor + step)
        if target <= cursor + 3:
            log.info(f"[INVENTORY] Reached bottom at iteration {iteration} (cursor={cursor}), stopping")
            reached_bottom = True
            break
        sb_drag(ctx, cursor, target)

    log.info(f"[INVENTORY] Could not find '{item_name}' after scrolling. Items seen: {found_names}")
    return False, reached_bottom


def is_on_training_screen(frame):
    if frame is None:
        return False
    from bot.recog.image_matcher import image_match
    from module.umamusume.asset.template import UI_CULTIVATE_TRAINING_SELECT
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return image_match(gray, UI_CULTIVATE_TRAINING_SELECT).find_match


def is_on_main_menu(frame):
    if frame is None:
        return False
    from bot.recog.image_matcher import image_match
    from module.umamusume.asset.template import UI_CULTIVATE_MAIN_MENU
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return image_match(gray, UI_CULTIVATE_MAIN_MENU).find_match


def is_items_panel_open(frame):
    if frame is None:
        return False
    from bot.recog.image_matcher import image_match
    from module.umamusume.asset.template import UI_CULTIVATE_TRAINING_ITEMS
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return image_match(gray, UI_CULTIVATE_TRAINING_ITEMS).find_match


def has_use_training_items_button(frame):
    if frame is None:
        return False
    from bot.recog.image_matcher import image_match
    from module.umamusume.asset.template import UI_CULTIVATE_USE_TRAINING_ITEMS
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return image_match(gray, UI_CULTIVATE_USE_TRAINING_ITEMS).find_match


def find_training_items_button(frame):
    if frame is None:
        return None
    from bot.recog.image_matcher import image_match
    from module.umamusume.asset.template import REF_TRAINING_ITEMS_BTN
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    result = image_match(gray, REF_TRAINING_ITEMS_BTN)
    if result.find_match and result.center_point:
        return result.center_point
    return None


def open_items_panel(ctx):
    for attempt in range(3):
        frame = ctx.ctrl.get_screen()
        if is_items_panel_open(frame):
            return True
        btn = find_training_items_button(frame)
        if btn:
            ctx.ctrl.click(int(btn[0]), int(btn[1]), "Training Items button")
        for _ in range(10):
            time.sleep(0.3)
            if is_items_panel_open(ctx.ctrl.get_screen()):
                return True
    return False


def close_items_panel(ctx):
    for _ in range(10):
        frame = ctx.ctrl.get_screen()
        if not is_items_panel_open(frame) and not has_use_training_items_button(frame):
            return
        ctx.ctrl.click(200, 1205, name="cancel exchange")
        time.sleep(0.3)


def use_training_item(ctx, item_name, quantity=1):
    if not open_items_panel(ctx):
        return False

    for _ in range(quantity):
        found, search_complete = try_click_item_plus_once(ctx, item_name)
        if not found:
            close_items_panel(ctx)
            if search_complete:
                setattr(ctx.cultivate_detail, 'mant_inventory_rescan_pending', True)
                log.warning(
                    f"[INVENTORY] '{item_name}' was not found after a full search; "
                    "keeping local inventory unchanged and scheduling a rescan"
                )
            return False
        time.sleep(0.15)

    ctx.ctrl.click(530, 1205, name="confirm exchange")
    time.sleep(0.3)

    clicked_use = False
    for _ in range(20):
        time.sleep(0.17)
        frame = ctx.ctrl.get_screen()
        if has_use_training_items_button(frame):
            ctx.ctrl.click(530, 1205, name="confirm exchange")
            clicked_use = True
            time.sleep(0.5)
            continue
        if clicked_use:
            if is_items_panel_open(frame) or not has_use_training_items_button(frame):
                return True
        if not clicked_use and is_items_panel_open(frame):
            ctx.ctrl.click(530, 1205, name="confirm exchange")

    return True


INSTANT_USE_ITEMS = [
    'Grilled Carrots',
    'Yummy Cat Food',
    'Energy Drink MAX EX',
    'Pretty Mirror',
    "Scholar's Hat",
    "Reporter's Binoculars",
    'Master Practice Guide',
]

ONE_TIME_BUFF_ITEMS = {
    'Pretty Mirror',
    "Scholar's Hat",
    "Reporter's Binoculars",
    'Master Practice Guide',
}

ENERGY_RECOVERY_ITEMS = {
    'Vita 20', 'Vita 40', 'Vita 65', 'Royal Kale Juice',
}
CHARM_ITEM = 'Good-Luck Charm'
ENERGY_ITEM_SKIP_FAST_PATH_THRESHOLD = 1

ENERGY_ITEMS = {
    'Vita 20': 20,
    'Vita 40': 40,
    'Vita 65': 65,
    'Royal Kale Juice': 100,
}

KALE_MOOD_PENALTY = 20

OVERFLOW_PENALTY = {0: 1.0, 1: 0.9, 2: 0.8, 3: 0.8, 4: 0.8}


def calc_effective_energy(item_name, raw_energy, current_energy, period_idx, max_energy=100):
    effective = raw_energy
    overflow = max(0, current_energy + raw_energy - max_energy)
    penalty_rate = OVERFLOW_PENALTY.get(period_idx, 0.8)
    effective -= overflow * penalty_rate
    if item_name == 'Royal Kale Juice':
        effective -= KALE_MOOD_PENALTY
    return effective


LOW_ENERGY_THRESHOLD = 5


def pick_best_energy_item(ctx):
    from module.umamusume.scenario.mant.policy import pick_best_energy_item as impl
    return impl(ctx)


def plan_low_energy_recovery(current_energy, owned_map, max_energy=100):
    available = []
    for item_name, raw_energy in sorted(ENERGY_ITEMS.items(), key=lambda x: x[1]):
        qty = owned_map.get(item_name, 0)
        if qty > 0:
            available.append((item_name, raw_energy, qty))

    if not available:
        return []

    plan = []
    energy = current_energy

    for item_name, raw_energy, qty in reversed(available):
        if energy >= max_energy:
            break
        while qty > 0 and energy + raw_energy <= max_energy:
            plan.append(item_name)
            energy += raw_energy
            qty -= 1

    if not plan:
        smallest = available[0]
        plan.append(smallest[0])

    result = []
    seen = {}
    for name in plan:
        if name not in seen:
            seen[name] = 0
        seen[name] += 1
    for name, count in seen.items():
        result.append((name, count))

    return result


def use_item_and_update_inventory(ctx, item_name):
    from module.umamusume.scenario.mant.actions import use_item_and_update_inventory as impl
    return impl(ctx, item_name)


def handle_training_whistle(ctx):
    from module.umamusume.scenario.mant.training_recovery import handle_training_whistle as impl
    return impl(ctx)


def handle_energy_item(ctx):
    from module.umamusume.scenario.mant.training_recovery import handle_energy_item as impl
    return impl(ctx)


def handle_energy_recovery(ctx):
    from module.umamusume.scenario.mant.training_recovery import handle_energy_recovery as impl
    return impl(ctx)


def handle_instant_use_items(ctx):
    from module.umamusume.scenario.mant.actions import handle_instant_use_items as impl
    return impl(ctx)


def handle_charm(ctx):
    from module.umamusume.scenario.mant.training_recovery import handle_charm as impl
    return impl(ctx)


def rescan_training(ctx):
    from module.umamusume.scenario.mant.training_recovery import rescan_training as impl
    return impl(ctx)


def has_energy_recovery(ctx):
    from module.umamusume.scenario.mant.policy import has_energy_recovery as impl
    return impl(ctx)


def has_charm(ctx):
    from module.umamusume.scenario.mant.policy import has_charm as impl
    return impl(ctx)


def has_whistle(ctx):
    from module.umamusume.scenario.mant.policy import has_whistle as impl
    return impl(ctx)


def has_cupcakes(ctx):
    from module.umamusume.scenario.mant.policy import has_cupcakes as impl
    return impl(ctx)


def whistle_loop(ctx, start_date):
    from module.umamusume.scenario.mant.training_recovery import whistle_loop as impl
    return impl(ctx, start_date)


def handle_cupcake_use(ctx):
    from module.umamusume.scenario.mant.actions import handle_cupcake_use as impl
    return impl(ctx)

def has_instant_use_items(ctx):
    from module.umamusume.scenario.mant.actions import has_instant_use_items as impl
    return impl(ctx)


MEGAPHONE_TIERS = {
    'Coaching Megaphone': (1, 4),
    'Motivating Megaphone': (2, 3),
    'Empowering Megaphone': (3, 2),
}

MEGAPHONE_CONFIG_KEYS = {
    1: 'mega_small_threshold',
    2: 'mega_medium_threshold',
    3: 'mega_large_threshold',
}

TRAINING_TYPE_ANKLET = {
    1: 'Speed Ankle Weights',
    2: 'Stamina Ankle Weights',
    3: 'Power Ankle Weights',
    4: 'Guts Ankle Weights',
}


def get_best_percentile(ctx):
    from module.umamusume.scenario.mant.policy import get_best_percentile as impl
    return impl(ctx)


def get_stat_only_percentile(ctx):
    from module.umamusume.scenario.mant.policy import get_stat_only_percentile as impl
    return impl(ctx)




def get_date_weighted_score_percentile(ctx):
    from module.umamusume.scenario.mant.policy import get_date_weighted_score_percentile as impl
    return impl(ctx)


MEGA_STAT_MULT = {1: 1.20, 2: 1.40, 3: 1.60}


def save_megaphone_scan_state_and_tick(ctx):
    from module.umamusume.scenario.mant.training_recovery import save_megaphone_scan_state_and_tick as impl
    return impl(ctx)


def megaphone_reevaluate(ctx, current_op):
    from module.umamusume.scenario.mant.training_recovery import megaphone_reevaluate as impl
    return impl(ctx, current_op)


def count_races_in_window(ctx, duration):
    current_date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    count = 0
    if current_date >= MANT_CLIMAX_START - duration:
        for offset in range(duration):
            future_date = current_date + offset
            if future_date >= MANT_CLIMAX_START and future_date % 2 == 0:
                count += 1
    extra_races = getattr(ctx.cultivate_detail, 'extra_race_list', [])
    if extra_races:
        from module.umamusume.asset.race_data import get_races_for_period
        for offset in range(1, duration):
            future_date = current_date + offset
            available = get_races_for_period(future_date)
            if any(r in available for r in extra_races):
                count += 1
    return count

def get_chain_position(ctx) -> tuple[int, int]:
    from module.umamusume.scenario.mant.policy import get_chain_position as impl
    return impl(ctx)


def has_scheduled_race_this_turn(ctx) -> bool:
    from module.umamusume.scenario.mant.policy import has_scheduled_race_this_turn as impl
    return impl(ctx)

MANT_CLIMAX_START = 73
MANT_CLIMAX_TRAINING_TURNS = [73, 75, 77]


def remaining_training_turns(date):
    if date >= MANT_CLIMAX_START:
        return sum(1 for t in MANT_CLIMAX_TRAINING_TURNS if t >= date)
    return (MANT_CLIMAX_START - date) + len(MANT_CLIMAX_TRAINING_TURNS)


def remaining_training_turns_real(ctx, date):
    from module.umamusume.scenario.mant.policy import remaining_training_turns_real as impl
    return impl(ctx, date)


def total_megaphone_turns(owned_map):
    total = 0
    for name, (tier, duration) in MEGAPHONE_TIERS.items():
        qty = owned_map.get(name, 0)
        total += qty * duration
    return total


def compute_mega_urgency(ctx):
    owned = getattr(ctx.cultivate_detail, 'mant_owned_items', [])
    owned_map = {n: q for n, q in owned}
    active_turns = getattr(ctx.cultivate_detail, 'mant_megaphone_turns', 0)
    date = getattr(ctx.cultivate_detail.turn_info, 'date', 0)
    mega_turns = total_megaphone_turns(owned_map) + active_turns
    training_remaining = remaining_training_turns_real(ctx, date)
    if training_remaining <= 0:
        return 99.0
    return mega_turns / training_remaining


def handle_megaphone(ctx):
    from module.umamusume.scenario.mant.training_recovery import handle_megaphone as impl
    return impl(ctx)


def handle_anklet(ctx):
    from module.umamusume.scenario.mant.training_recovery import handle_anklet as impl
    return impl(ctx)


def tick_megaphone(ctx):
    active_turns = getattr(ctx.cultivate_detail, 'mant_megaphone_turns', 0)
    if active_turns > 0:
        active_turns -= 1
        ctx.cultivate_detail.mant_megaphone_turns = active_turns
        if active_turns <= 0:
            ctx.cultivate_detail.mant_megaphone_tier = 0
        from module.umamusume.persistence import save_megaphone_state
        save_megaphone_state(getattr(ctx.cultivate_detail, 'mant_megaphone_tier', 0), active_turns)


def item_loop(ctx):
    from module.umamusume.scenario.mant.training_recovery import item_loop as impl
    return impl(ctx)


def should_skip_fast_path(ctx):
    from module.umamusume.scenario.mant.policy import should_skip_fast_path as impl
    return impl(ctx)


def handle_energy_drink_max_before_race(ctx):
    from module.umamusume.scenario.mant.race_prep import handle_energy_drink_max_before_race as impl
    return impl(ctx)

def handle_glow_sticks_before_race(ctx):
    from module.umamusume.scenario.mant.race_prep import handle_glow_sticks_before_race as impl
    return impl(ctx)


MANT_CLIMAX_RACE_TURNS = [74, 76, 78]


def remaining_climax_races(date):
    from module.umamusume.scenario.mant.race_prep import remaining_climax_races as impl
    return impl(date)


def handle_cleat_before_race(ctx, race_id, is_climax_override=False):
    from module.umamusume.scenario.mant.race_prep import handle_cleat_before_race as impl
    return impl(ctx, race_id, is_climax_override=is_climax_override)


def should_skip_race(ctx):
    from module.umamusume.scenario.mant.policy import should_skip_race as impl
    return impl(ctx)
