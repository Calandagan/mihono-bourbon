import cv2
import numpy as np
import sys
import bot.base.log as logger

log = logger.get_logger(__name__)

MODEL_PATH = "resource/umamusume/digit_model.pth"
_classifier = None
_load_failed = False

def get_classifier():
    global _classifier, _load_failed
    if _load_failed:
        return None
    if _classifier is None:
        log.info(f"Loading CNN classifier from {MODEL_PATH}")
        try:
            from bot.recog.digit_cnn import DigitClassifier
            _classifier = DigitClassifier(MODEL_PATH)
            log.info("CNN classifier loaded successfully")
        except OSError as e:
            err_str = str(e)
            if "127" in err_str or "shm.dll" in err_str or "DLL" in err_str:
                _load_failed = True
                log.error(f"Failed to load CNN classifier: {e}")
                print("\nERROR: Microsoft Visual C++ Redistributable is required")
                print("\nThe CNN classifier failed to load due to missing VC++ runtime.")
                print("\nPlease download and install from:")
                print("https://aka.ms/vs/17/release/vc_redist.x64.exe")
                print("\nAfter installation, restart this application.\n")
                input("Press Enter to exit...")
                sys.exit(1)
            log.error(f"Failed to load CNN classifier: {e}")
            _load_failed = True
            return None
        except Exception as e:
            log.error(f"Failed to load CNN classifier: {e}")
            _load_failed = True
            return None
    return _classifier

STAT_AREAS_AOHARUHAI = {
    "speed": (31, 798, 132, 831),
    "stamina": (114, 798, 246, 831),
    "power": (256, 798, 359, 831),
    "guts": (369, 798, 471, 831),
    "wits": (482, 798, 585, 831),
    "sp": (595, 798, 698, 831),
}

STAT_AREAS_URA = {
    "speed": (30, 770, 140, 826),
    "stamina": (140, 770, 250, 826),
    "power": (250, 770, 360, 826),
    "guts": (360, 770, 470, 826),
    "wits": (470, 770, 580, 826),
    "sp": (588, 770, 695, 826),
}

FACILITY_STATS = {
    "speed": ["speed", "power", "sp"],
    "stamina": ["stamina", "guts", "sp"],
    "power": ["power", "stamina", "sp"],
    "guts": ["speed", "guts", "power", "sp"],
    "wits": ["speed", "wits", "sp"],
}

def create_color_mask(roi, sat_thresh=70):
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, sat_thresh, 70), (180, 255, 255))
    return mask

def remove_bottom_bar(mask):
    h, w = mask.shape
    for row in range(h - 1, max(h - 8, 0), -1):
        row_sum = np.sum(mask[row, :] > 0)
        if row_sum > w * 0.6:
            mask[row, :] = 0
        else:
            break
    return mask

def find_digit_regions(mask):
    mask = remove_bottom_bar(mask.copy())
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h_img, w_img = mask.shape
    all_candidates = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        area = cv2.contourArea(cnt)
        if area < 100:
            continue
        if w > 28 or w < 10:
            continue
        if h < 18 or h > 40:
            continue
        aspect = w / h
        if aspect > 0.98:
            continue
        if aspect < 0.40:
            continue
        if y > 20 or y == 0:
            continue
        right_edge = x + w
        if right_edge >= w_img and x >= w_img - 20:
            continue
        all_candidates.append((x, y, w, h, area))
    all_candidates.sort(key=lambda r: r[0])
    if len(all_candidates) >= 3:
        min_x = int(w_img * 0.25)
    else:
        min_x = int(w_img * 0.35)
    regions = []
    for x, y, w, h, area in all_candidates:
        if x < min_x:
            continue
        regions.append((x, y, w, h))
    if len(regions) > 3:
        areas = [(r[2] * r[3], r) for r in regions]
        areas.sort(key=lambda a: a[0], reverse=True)
        top_areas = [a[0] for a in areas[:3]]
        if len(top_areas) >= 3:
            avg_area = sum(top_areas) / len(top_areas)
            threshold = avg_area * 0.4
            regions = [r for _, r in areas if _ >= threshold]
            regions.sort(key=lambda r: r[0])
    return regions

def extract_digit_mask(mask, region):
    x, y, w, h = region
    padding = 2
    x1 = max(0, x - padding)
    y1 = max(0, y - padding)
    x2 = min(mask.shape[1], x + w + padding)
    y2 = min(mask.shape[0], y + h + padding)
    digit_mask = mask[y1:y2, x1:x2]
    return digit_mask if digit_mask.size > 0 else None

def _extract_digit_masks(roi):
    """CPU-side digit extraction for one stat ROI. Returns (digit_masks, valid_regions)."""
    if roi is None or roi.size == 0:
        return [], []
    mask = create_color_mask(roi)
    regions = find_digit_regions(mask)
    if not regions:
        return [], []
    digit_masks = []
    valid_regions = []
    for region in regions:
        dm = extract_digit_mask(mask, region)
        if dm is not None:
            digit_masks.append(dm)
            valid_regions.append(region)
    return digit_masks, valid_regions


def _assemble_value(results, valid_regions, max_value=100):
    """Turn per-digit (pred, conf) predictions + their regions into an int value."""
    digits = []
    for i, (pred, conf) in enumerate(results):
        if pred >= 0 and conf > 0.3:
            digits.append((valid_regions[i][0], pred, conf))
    if not digits:
        return 0
    digits.sort(key=lambda d: d[0])
    result_str = "".join(str(d[1]) for d in digits)
    value = int(result_str) if result_str else 0
    if value <= max_value:
        return value
    candidates = []
    for i in range(len(digits)):
        remaining = digits[:i] + digits[i+1:]
        if remaining:
            rem_str = "".join(str(d[1]) for d in remaining)
            rem_val = int(rem_str) if rem_str else 0
            if rem_val <= max_value:
                removed_conf = digits[i][2]
                candidates.append((rem_val, removed_conf))
    if candidates:
        candidates.sort(key=lambda c: c[1])
        return candidates[0][0]
    if len(result_str) >= 2:
        last_two = int(result_str[-2:])
        if last_two <= max_value:
            return last_two
    return 0


def recognize_digits_cnn(roi, max_value=100):
    digit_masks, valid_regions = _extract_digit_masks(roi)
    if not digit_masks:
        return 0
    classifier = get_classifier()
    if classifier is None:
        return 0
    results = classifier.predict_batch(digit_masks)
    return _assemble_value(results, valid_regions, max_value)


def scan_stats_batch(img, stat_names, scenario="aoharuhai", max_value=100):
    """Scan several stat regions with a SINGLE CNN forward pass.

    Collects the digit masks from every requested stat region, runs one
    predict_batch over all of them, then splits the predictions back per stat.
    Behaviour per stat is identical to recognize_digits_cnn.
    """
    areas = STAT_AREAS_URA if scenario == "ura" else STAT_AREAS_AOHARUHAI
    h, w = img.shape[:2]
    all_masks = []
    spans = {}  # stat -> (start_index, count, valid_regions)
    for stat in stat_names:
        if stat not in areas:
            spans[stat] = (0, 0, [])
            continue
        x1, y1, x2, y2 = areas[stat]
        x1 = max(0, min(x1, w)); x2 = max(0, min(x2, w))
        y1 = max(0, min(y1, h)); y2 = max(0, min(y2, h))
        roi = img[y1:y2, x1:x2]
        masks, regions = _extract_digit_masks(roi)
        start = len(all_masks)
        all_masks.extend(masks)
        spans[stat] = (start, len(masks), regions)

    results = {stat: 0 for stat in stat_names}
    if not all_masks:
        return results
    classifier = get_classifier()
    if classifier is None:
        return results
    preds = classifier.predict_batch(all_masks)
    for stat in stat_names:
        start, count, regions = spans[stat]
        if count == 0:
            continue
        results[stat] = _assemble_value(preds[start:start + count], regions, max_value)
    return results

def scan_stat_gain(img, stat_name, scenario="aoharuhai"):
    if scenario == "ura":
        areas = STAT_AREAS_URA
    else:
        areas = STAT_AREAS_AOHARUHAI
    if stat_name not in areas:
        return 0
    h, w = img.shape[:2]
    x1, y1, x2, y2 = areas[stat_name]
    x1 = max(0, min(x1, w))
    x2 = max(0, min(x2, w))
    y1 = max(0, min(y1, h))
    y2 = max(0, min(y2, h))
    roi = img[y1:y2, x1:x2]
    return recognize_digits_cnn(roi)

def scan_facility_stats(img, facility_type, scenario="aoharuhai"):
    if facility_type not in FACILITY_STATS:
        return {}
    # One CNN forward pass for all of this facility's stats instead of one per stat.
    return scan_stats_batch(img, FACILITY_STATS[facility_type], scenario)

def parse_training_result_template(img, scenario="aoharuhai"):
    order = ["speed", "stamina", "power", "guts", "wits", "sp"]
    # One CNN forward pass for all 6 stats instead of six separate calls.
    vals = scan_stats_batch(img, order, scenario)
    return [vals[s] for s in order]
