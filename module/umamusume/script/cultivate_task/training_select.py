import time
import threading

import numpy as np
import cv2

import bot.base.log as logger
from bot.recog.image_matcher import image_match
from module.umamusume.context import UmamusumeContext
from module.umamusume.types import TurnOperation
from module.umamusume.define import TrainingType, TurnOperationType, ScenarioType, SupportCardType, SupportCardFavorLevel
from module.umamusume.asset.point import (
    TRAINING_POINT_LIST, RETURN_TO_CULTIVATE_MAIN_MENU
)
from module.umamusume.constants.game_constants import (
    is_summer_camp_period, JUNIOR_YEAR_END, CLASSIC_YEAR_END, get_date_period_index
)
from module.umamusume.constants.scoring_constants import (
    DEFAULT_BASE_SCORES, DEFAULT_SCORE_VALUE,
    DEFAULT_MAX_FAILURE_RATE, DEFAULT_REST_THRESHOLD,
    DEFAULT_STAT_VALUE_MULTIPLIER, DEFAULT_NPC_SCORE_VALUE
)
from module.umamusume.constants.timing_constants import (
    TRAINING_CLICK_DELAY, TRAINING_WAIT_DELAY,
    MAX_TRAINING_RETRY, TRAINING_RETRY_DELAY,
    MAX_DETECTION_ATTEMPTS, TRAINING_DETECTION_DELAY,
    ENERGY_READ_RETRY_DELAY
)
from module.umamusume.constants.game_constants import get_date_period_index
from module.umamusume.script.cultivate_task.parse import parse_train_type, parse_failure_rates
from module.umamusume.script.cultivate_task.planner import (
    execute_mant_pre_action,
    plan_training_turn,
    set_turn_plan,
)
from module.umamusume.script.cultivate_task.helpers import should_use_pal_outing_simple
from bot.recog.training_stat_scanner import scan_facility_stats
from bot.recog.energy_scanner import scan_training_energy_change
from bot.recog.character_detector import CharacterDetector
from module.umamusume.persistence import MAX_DATAPOINTS

log = logger.get_logger(__name__)

character_detector = CharacterDetector()

FACILITY_NAME_MAP = {
    TrainingType.TRAINING_TYPE_SPEED: "speed",
    TrainingType.TRAINING_TYPE_STAMINA: "stamina",
    TrainingType.TRAINING_TYPE_POWER: "power",
    TrainingType.TRAINING_TYPE_WILL: "guts",
    TrainingType.TRAINING_TYPE_INTELLIGENCE: "wits",
}

TRAINING_NAMES = ["Speed", "Stamina", "Power", "Guts", "Wit"]

def get_facility_period_index(date):
    if date <= 12: return 0  # Junior Early
    if date <= 24: return 1  # Junior Late
    if date <= 36: return 2  # Classic Early
    if date <= 48: return 3  # Classic Late
    if date <= 60: return 4  # Senior Early
    if date <= 72: return 5  # Senior Late
    return 6  # Endgame (Disable)
STAT_KEY_LIST = ["speed", "stamina", "power", "guts", "wits", "sp"]

# Hard cap (Option B): when a facility's own primary stat is already at/over its
# configured cap, multiply the WHOLE facility score by this factor so it only
# wins when its cross-stat value is genuinely high. Lower = harder cap.
CAPPED_FACILITY_SCORE_MULT = 0.25

TYPE_MAP = [
    SupportCardType.SUPPORT_CARD_TYPE_SPEED,
    SupportCardType.SUPPORT_CARD_TYPE_STAMINA,
    SupportCardType.SUPPORT_CARD_TYPE_POWER,
    SupportCardType.SUPPORT_CARD_TYPE_WILL,
    SupportCardType.SUPPORT_CARD_TYPE_INTELLIGENCE,
]


def get_max_failure_rate(ctx: UmamusumeContext) -> int:
    try:
        limit = int(getattr(ctx.cultivate_detail, 'max_failure_rate', DEFAULT_MAX_FAILURE_RATE))
    except Exception:
        limit = DEFAULT_MAX_FAILURE_RATE
    return max(0, min(100, limit))


def _get_stat_caps_and_current_values(ctx: UmamusumeContext):
    try:
        ea = getattr(ctx.cultivate_detail, 'expect_attribute', None)
        if not (isinstance(ea, list) and len(ea) == 5):
            return None, None
        uma_now = ctx.cultivate_detail.turn_info.uma_attribute
        stat_caps = [float(v) for v in ea]
        curr_stat_vals = [
            float(uma_now.speed),
            float(uma_now.stamina),
            float(uma_now.power),
            float(uma_now.will),
            float(uma_now.intelligence),
        ]
        return stat_caps, curr_stat_vals
    except Exception:
        return None, None


def _should_fast_skip_capped_facility_scan(
        ctx: UmamusumeContext,
        facility_idx: int,
        stat_caps,
        curr_stat_vals) -> bool:
    if not bool(getattr(ctx.cultivate_detail, 'aggressive_cap_skip', False)):
        return False
    try:
        scenario_type = ctx.cultivate_detail.scenario.scenario_type()
    except Exception:
        return False
    aoharu_type = getattr(ScenarioType, 'SCENARIO_TYPE_AOHARUHAI', None)
    allowed_scenarios = {ScenarioType.SCENARIO_TYPE_URA}
    if aoharu_type is not None:
        allowed_scenarios.add(aoharu_type)
    if scenario_type not in allowed_scenarios:
        return False
    if stat_caps is None or curr_stat_vals is None:
        return False
    if facility_idx < 0 or facility_idx >= 5:
        return False
    cap = stat_caps[facility_idx]
    current = curr_stat_vals[facility_idx]
    return cap > 0 and current >= cap


def script_cultivate_training_select(ctx: UmamusumeContext):
    script_t0 = time.perf_counter()
    if ctx.cultivate_detail.turn_info is None:
        log.warning("Turn information not initialized")
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
        return

    ctx.cultivate_detail.turn_info.pending_training_scan = False
    ctx.cultivate_detail.turn_info.training_select_request_count = 0
    ctx.cultivate_detail.turn_info.force_safe_recovery = False

    turn_op = ctx.cultivate_detail.turn_info.turn_operation

    if turn_op is not None:
        try:
            cached_stats = getattr(ctx.cultivate_detail, 'last_decision_stats', None)
            if cached_stats is not None:
                uma = ctx.cultivate_detail.turn_info.uma_attribute
                current_stats = (uma.speed, uma.stamina, uma.power, uma.will, uma.intelligence)
                if current_stats != cached_stats:
                    log.info(f"Cache invalid. was {cached_stats}, now {current_stats})")
                    ctx.cultivate_detail.turn_info.turn_operation = None
                    ctx.cultivate_detail.turn_info.parse_train_info_finish = False
                    ctx.cultivate_detail.mant_cleat_used = False
                    turn_op = None
        except Exception:
            pass

    if turn_op is not None:
        if turn_op.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_TRAINING:
            training_type = turn_op.training_type
            if training_type == TrainingType.TRAINING_TYPE_UNKNOWN:
                log.info("Training operation missing training type; recomputing from training scan")
                ctx.cultivate_detail.turn_info.turn_operation = None
                ctx.cultivate_detail.turn_info.parse_train_info_finish = False
                turn_op = None
            else:
                idx = training_type.value - 1
                if 0 <= idx < 5:
                    if not getattr(ctx.cultivate_detail.turn_info, 'facility_click_logged', False):
                        facility_keys = ["speed", "stamina", "power", "guts", "wits"]
                        key = facility_keys[idx]
                        if not hasattr(ctx.cultivate_detail, "facility_clicks"):
                            ctx.cultivate_detail.facility_clicks = {"speed": 0, "stamina": 0, "power": 0, "guts": 0, "wits": 0}
                        ctx.cultivate_detail.facility_clicks[key] += 1
                        ctx.cultivate_detail.turn_info.facility_click_logged = True
                        try:
                            from module.umamusume.persistence import save_career_data
                            save_career_data(ctx)
                        except Exception:
                            pass
                ctx.ctrl.click_by_point(TRAINING_POINT_LIST[training_type.value - 1])
                time.sleep(TRAINING_CLICK_DELAY)
                ctx.ctrl.click_by_point(TRAINING_POINT_LIST[training_type.value - 1])
                time.sleep(TRAINING_WAIT_DELAY)
                return

        else:
            ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
            return

    is_mant = False
    try:
        is_mant = ctx.cultivate_detail.scenario.scenario_type() == ScenarioType.SCENARIO_TYPE_MANT
    except Exception:
        pass

    mant_skip = False
    if is_mant:
        from module.umamusume.scenario.mant.policy import should_skip_fast_path
        mant_skip = should_skip_fast_path(ctx)

        if not mant_skip:
            if getattr(ctx.cultivate_detail.turn_info, "energy_recovery_deferred", False):
                mant_skip = True
            else:
                try:
                    from module.umamusume.scenario.mant.policy import has_energy_recovery, has_cupcakes
                    if has_energy_recovery(ctx) or has_cupcakes(ctx):
                        mant_skip = True
                    else:
                        from module.umamusume.asset.race_data import get_races_for_period
                        date = ctx.cultivate_detail.turn_info.date
                        available_races_now = get_races_for_period(date)
                        next_date = date + 1
                        available_races_next = get_races_for_period(next_date)
                        has_race_now = any(r in ctx.cultivate_detail.extra_race_list for r in available_races_now)
                        has_race_next = any(r in ctx.cultivate_detail.extra_race_list for r in available_races_next)
                        if has_race_now or has_race_next:
                            mant_skip = True
                except Exception:
                    pass

        if getattr(ctx.cultivate_detail.turn_info, 'skip_training_review_for_race', False):
            ctx.cultivate_detail.turn_info.skip_training_review_for_race = False
            try:
                from module.umamusume.scenario.mant.scan import close_items_panel
                from module.umamusume.scenario.mant.training_recovery import handle_energy_recovery
                from module.umamusume.scenario.mant.policy import has_scheduled_race_this_turn
                if has_scheduled_race_this_turn(ctx) and getattr(ctx.cultivate_detail.turn_info, 'energy_recovery_deferred', False):
                    handle_energy_recovery(ctx, mode="race")
                ctx.cultivate_detail.turn_info.energy_recovery_deferred = False
                ctx.cultivate_detail.turn_info.post_item_rescan_needed = False
                ctx.cultivate_detail.turn_info.energy_item_used = False
                ctx.cultivate_detail.turn_info.turn_operation = TurnOperation()
                ctx.cultivate_detail.turn_info.turn_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_RACE
                ctx.cultivate_detail.turn_info.parse_train_info_finish = True
                ctx.cultivate_detail.last_decision_stats = None
                close_items_panel(ctx)
            except Exception:
                pass
            ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
            return

    if not getattr(ctx.cultivate_detail, 'career_data_loaded', False):
        try:
            from module.umamusume.persistence import load_career_data
            load_career_data(ctx)
        except Exception:
            pass
        ctx.cultivate_detail.career_data_loaded = True

    limit = int(getattr(ctx.cultivate_detail, 'rest_threshold', getattr(ctx.cultivate_detail, 'rest_treshold', getattr(ctx.cultivate_detail, 'fast_path_energy_limit', DEFAULT_REST_THRESHOLD))))
    if limit == 0:
        energy = 100
    else:
        from bot.conn.fetch import read_energy
        energy = read_energy()
        if energy == 0:
            time.sleep(ENERGY_READ_RETRY_DELAY)
            energy = read_energy()
    ctx.cultivate_detail.turn_info.cached_energy = energy

    if not ctx.cultivate_detail.turn_info.parse_train_info_finish:

        class TrainingDetectionResult:
            def __init__(self):
                self.support_card_info_list = []
                self.has_hint = False
                self.failure_rate = -1
                self.speed_incr = 0
                self.stamina_incr = 0
                self.power_incr = 0
                self.will_incr = 0
                self.intelligence_incr = 0
                self.skill_point_incr = 0
                self.energy_change = 0.0
                self.detected_characters = []

        def detect_training_once(ctx, img, train_type, energy_change=None):
            result = TrainingDetectionResult()
            result.facility_name = FACILITY_NAME_MAP.get(train_type)
            result.scenario_name = "ura" if ctx.cultivate_detail.scenario.scenario_type() == ScenarioType.SCENARIO_TYPE_URA else "aoharuhai"
            result.stat_results = {}
            result.energy_change = energy_change if energy_change is not None else 0.0
            try:
                if result.facility_name:
                    result.stat_results = scan_facility_stats(img, result.facility_name, result.scenario_name)
                train_incr = ctx.cultivate_detail.scenario.parse_training_result(img)
                result.speed_incr = train_incr[0]
                result.stamina_incr = train_incr[1]
                result.power_incr = train_incr[2]
                result.will_incr = train_incr[3]
                result.intelligence_incr = train_incr[4]
                result.skill_point_incr = train_incr[5]
            except Exception:
                pass
            try:
                parse_failure_rates(ctx, img, train_type)
                til = ctx.cultivate_detail.turn_info.training_info_list[train_type.value - 1]
                result.failure_rate = getattr(til, 'failure_rate', -1)
            except Exception:
                pass
            try:
                result.support_card_info_list = ctx.cultivate_detail.scenario.parse_training_support_card(img)
            except Exception:
                pass
            try:
                slot_config = ctx.cultivate_detail.scenario.get_support_card_slot_config()
                if slot_config is not None:
                    detections = character_detector.detect_facility(img, slot_config)
                    from module.umamusume.asset.template import REF_TRAINING_HINT
                    hint_tpl = REF_TRAINING_HINT.template_image
                    hint_slot = -1
                    if hint_tpl is not None:
                        strip_y1 = slot_config["base_y"]
                        strip_y2 = strip_y1 + slot_config["num_slots"] * slot_config["inc"]
                        strip_gray = cv2.cvtColor(img[strip_y1:strip_y2, 655:710], cv2.COLOR_BGR2GRAY)
                        tm_result = cv2.matchTemplate(strip_gray, hint_tpl, cv2.TM_CCOEFF_NORMED)
                        _, max_val, _, max_loc = cv2.minMaxLoc(tm_result)
                        if max_val >= 0.75:
                            hint_slot = (max_loc[1] + hint_tpl.shape[0]) // slot_config["inc"]
                    for slot_idx, name, score in detections:
                        if name is not None:
                            slot_has_hint = (slot_idx == hint_slot)
                            result.detected_characters.append((name, score, slot_has_hint))
                            if slot_has_hint:
                                result.has_hint = True
                            try:
                                sc_list = result.support_card_info_list
                                if slot_idx < len(sc_list):
                                    favor = getattr(sc_list[slot_idx], "favor", None)
                                    if favor is not None and favor.value != 0:
                                        from module.umamusume.context import log_detected_portrait
                                        card_type = getattr(sc_list[slot_idx], "card_type", None)
                                        is_npc = (card_type == SupportCardType.SUPPORT_CARD_TYPE_NPC)
                                        log_detected_portrait(name, favor.value, is_npc=is_npc, card_type=card_type)
                            except Exception:
                                pass
            except Exception:
                result.detected_characters = []
            return result

        def compare_detection_results(result1, result2):
            if len(result1.support_card_info_list) != len(result2.support_card_info_list):
                return False
            for sc1, sc2 in zip(result1.support_card_info_list, result2.support_card_info_list):
                if getattr(sc1, "card_type", None) != getattr(sc2, "card_type", None):
                    return False
                if getattr(sc1, "favor", None) != getattr(sc2, "favor", None):
                    return False
            if result1.has_hint != result2.has_hint:
                return False
            if result1.failure_rate != result2.failure_rate:
                return False
            if result1.speed_incr != result2.speed_incr:
                return False
            if result1.stamina_incr != result2.stamina_incr:
                return False
            if result1.power_incr != result2.power_incr:
                return False
            if result1.will_incr != result2.will_incr:
                return False
            if result1.intelligence_incr != result2.intelligence_incr:
                return False
            if result1.skill_point_incr != result2.skill_point_incr:
                return False
            return True

        def apply_detection_result(ctx, train_type, result):
            til = ctx.cultivate_detail.turn_info.training_info_list[train_type.value - 1]
            til.support_card_info_list = result.support_card_info_list
            til.has_hint = result.has_hint
            til.failure_rate = result.failure_rate
            til.speed_incr = result.speed_incr
            til.stamina_incr = result.stamina_incr
            til.power_incr = result.power_incr
            til.will_incr = result.will_incr
            til.intelligence_incr = result.intelligence_incr
            til.skill_point_incr = result.skill_point_incr
            til.stat_results = getattr(result, 'stat_results', {})
            til.energy_change = getattr(result, 'energy_change', 0.0)
            til.detected_characters = getattr(result, 'detected_characters', [])
            tt_map = {
                TrainingType.TRAINING_TYPE_SPEED: SupportCardType.SUPPORT_CARD_TYPE_SPEED,
                TrainingType.TRAINING_TYPE_STAMINA: SupportCardType.SUPPORT_CARD_TYPE_STAMINA,
                TrainingType.TRAINING_TYPE_POWER: SupportCardType.SUPPORT_CARD_TYPE_POWER,
                TrainingType.TRAINING_TYPE_WILL: SupportCardType.SUPPORT_CARD_TYPE_WILL,
                TrainingType.TRAINING_TYPE_INTELLIGENCE: SupportCardType.SUPPORT_CARD_TYPE_INTELLIGENCE,
            }
            target = tt_map.get(train_type)
            relevant_count = 0
            for sc in result.support_card_info_list:
                if getattr(sc, "card_type", None) == target:
                    relevant_count += 1
            til.relevant_count = relevant_count

        def parse_training_with_retry(ctx, img, train_type, energy_change=None):
            # First attempt
            result1 = detect_training_once(ctx, img, train_type, energy_change)
            
            # Fast path: if we have good data, don't wait for retry
            if result1.failure_rate != -1 and len(result1.support_card_info_list) > 0:
                apply_detection_result(ctx, train_type, result1)
                return

            for attempt in range(MAX_DETECTION_ATTEMPTS):
                time.sleep(TRAINING_DETECTION_DELAY)
                result2 = detect_training_once(ctx, img, train_type, energy_change)
                if compare_detection_results(result1, result2):
                    apply_detection_result(ctx, train_type, result1)
                    return
                result1 = result2
            apply_detection_result(ctx, train_type, result1)

        def parse_training_full(ctx, img, train_type, ctrl, facility_name, energy_changes, idx):
            """Runs OCR + energy scan in a single thread to eliminate sequential blocking."""
            try:
                energy_change, _ = scan_training_energy_change(ctrl, facility_name, initial_img=img)
            except Exception:
                energy_change = 0.0
            energy_changes.append((idx, energy_change))
            parse_training_with_retry(ctx, img, train_type, energy_change)

        def clear_training(ctx: UmamusumeContext, train_type: 'TrainingType'):
            til = ctx.cultivate_detail.turn_info.training_info_list[train_type.value - 1]
            til.speed_incr = 0
            til.stamina_incr = 0
            til.power_incr = 0
            til.will_incr = 0
            til.intelligence_incr = 0
            til.skill_point_incr = 0
            til.support_card_info_list = []
            til.stat_results = {}

        threads: list[threading.Thread] = []
        blocked_trainings = [False] * 5
        energy_changes: list[tuple[int, float]] = []

        date = ctx.cultivate_detail.turn_info.date
        if date == 0:
            extra_weight = [0, 0, 0, 0, 0]
        elif date <= JUNIOR_YEAR_END:
            extra_weight = ctx.cultivate_detail.extra_weight[0]
        elif date <= CLASSIC_YEAR_END:
            extra_weight = ctx.cultivate_detail.extra_weight[1]
        else:
            extra_weight = ctx.cultivate_detail.extra_weight[2]

        try:
            if is_summer_camp_period(date) and isinstance(ctx.cultivate_detail.extra_weight, (list, tuple)) and len(ctx.cultivate_detail.extra_weight) >= 4:
                extra_weight = ctx.cultivate_detail.extra_weight[3]
        except Exception:
            pass

        img = ctx.current_screen
        train_type = parse_train_type(ctx, img)
        if train_type == TrainingType.TRAINING_TYPE_UNKNOWN:
            return
        viewed = train_type.value

        stat_caps, curr_stat_vals = _get_stat_caps_and_current_values(ctx)
        _scan_t0 = time.perf_counter()

        skip_viewed_scan = _should_fast_skip_capped_facility_scan(
            ctx, viewed - 1, stat_caps, curr_stat_vals)
        if extra_weight[viewed - 1] > -1 and not skip_viewed_scan:
            facility_name = FACILITY_NAME_MAP.get(train_type)
            immediate_img = ctx.ctrl.get_screen()
            # Use full parallel thread: OCR + energy scan together
            thread = threading.Thread(
                target=parse_training_full,
                args=(ctx, immediate_img, train_type, ctx.ctrl, facility_name, energy_changes, viewed - 1)
            )
            threads.append(thread)
            thread.start()
        else:
            if skip_viewed_scan:
                log.info(
                    "[FAST-CAP] Skipping %s facility scan — target already reached",
                    TRAINING_NAMES[viewed - 1],
                )
            clear_training(ctx, train_type)

        for i in range(5):
            if i != (viewed - 1):
                skip_facility_scan = _should_fast_skip_capped_facility_scan(
                    ctx, i, stat_caps, curr_stat_vals)
                if extra_weight[i] > -1 and not skip_facility_scan:
                    slot_start = time.perf_counter()
                    retry = 0
                    ctx.ctrl.click_by_point(TRAINING_POINT_LIST[i])
                    img = ctx.ctrl.get_screen()
                    while parse_train_type(ctx, img) != TrainingType(i + 1) and retry < MAX_TRAINING_RETRY:
                        if retry > 2:
                            ctx.ctrl.click_by_point(TRAINING_POINT_LIST[i])
                        time.sleep(TRAINING_RETRY_DELAY)
                        img = ctx.ctrl.get_screen()
                        retry += 1
                    if retry == MAX_TRAINING_RETRY:
                        log.info(f"Training {TrainingType(i + 1).name} is restricted by game - skipping")
                        blocked_trainings[i] = True
                        clear_training(ctx, TrainingType(i + 1))
                        continue

                    train_type_i = TrainingType(i + 1)
                    facility_name = FACILITY_NAME_MAP.get(train_type_i)
                    # Use full parallel thread: OCR + energy scan together
                    thread = threading.Thread(
                        target=parse_training_full,
                        args=(ctx, img, train_type_i, ctx.ctrl, facility_name, energy_changes, i)
                    )
                    threads.append(thread)
                    thread.start()
                else:
                    if skip_facility_scan:
                        log.info(
                            "[FAST-CAP] Skipping %s facility scan — target already reached",
                            TRAINING_NAMES[i],
                        )
                    clear_training(ctx, TrainingType(i + 1))

        for thread in threads:
            thread.join()

        log.info(f"[TIMING] facility scan ({len(threads)} facilities) took {(time.perf_counter() - _scan_t0) * 1000:.0f} ms")
        decision_t0 = time.perf_counter()

        for idx, energy_val in energy_changes:
            ctx.cultivate_detail.turn_info.training_info_list[idx].energy_change = energy_val

        date = ctx.cultivate_detail.turn_info.date
        sv = getattr(ctx.cultivate_detail, 'score_value', DEFAULT_SCORE_VALUE)
        def resolve_weights(sv_list, idx):
            try:
                arr = sv_list[idx]
            except Exception:
                arr = [0.11, 0.10, 0.006, 0.09]
            if not isinstance(arr, (list, tuple)):
                arr = [0.11, 0.10, 0.006, 0.09]
            base = list(arr[:4])
            if len(base) < 4:
                base += [0.09] * (4 - len(base))
            return base
        period_idx = get_date_period_index(date)
        w_lv1, w_lv2, w_energy_change, w_hint = resolve_weights(sv, period_idx)

        type_map = TYPE_MAP
        names = TRAINING_NAMES
        stat_keys = STAT_KEY_LIST
        computed_scores = [0.0, 0.0, 0.0, 0.0, 0.0]
        original_scores = [0.0, 0.0, 0.0, 0.0, 0.0]
        stat_scores = [0.0, 0.0, 0.0, 0.0, 0.0]
        stat_contributions = [[0.0] * 6 for _ in range(5)]
        facility_mults = [1.0] * 5

        pre_highest_stat_idx = None
        try:
            d_pre = int(ctx.cultivate_detail.turn_info.date)
            if isinstance(d_pre, int) and d_pre > 48 and d_pre <= 72:
                uma_pre = ctx.cultivate_detail.turn_info.uma_attribute
                stats_pre = [uma_pre.speed, uma_pre.stamina, uma_pre.power, uma_pre.will, uma_pre.intelligence]
                pre_highest_stat_idx = int(np.argmax(stats_pre)) if len(stats_pre) == 5 else None
        except Exception:
            pass

        stat_mult = getattr(ctx.cultivate_detail, 'stat_value_multiplier', DEFAULT_STAT_VALUE_MULTIPLIER)
        if not isinstance(stat_mult, (list, tuple)) or len(stat_mult) < 6:
            stat_mult = DEFAULT_STAT_VALUE_MULTIPLIER



        try:
            current_energy = int(getattr(ctx.cultivate_detail.turn_info, 'cached_energy', 0))
            if current_energy == 0:
                from bot.conn.fetch import read_energy
                current_energy = int(read_energy())
                ctx.cultivate_detail.turn_info.cached_energy = current_energy
        except Exception:
            current_energy = None
        try:
            rest_threshold = int(getattr(ctx.cultivate_detail, 'rest_threshold', getattr(ctx.cultivate_detail, 'rest_treshold', getattr(ctx.cultivate_detail, 'fast_path_energy_limit', DEFAULT_REST_THRESHOLD))))
        except Exception:
            rest_threshold = DEFAULT_REST_THRESHOLD
        
        energy_penalty_mult = ctx.cultivate_detail.scenario.compute_energy_penalty_for_race_chain(
            ctx, current_energy, rest_threshold, date)
        
        base_scores = getattr(ctx.cultivate_detail, 'base_score', DEFAULT_BASE_SCORES)

        base_energy = getattr(ctx.cultivate_detail.turn_info, 'base_energy', None)
        if base_energy is not None:
            log.info(f"Base Energy: {base_energy:.1f}%{' (high energy)' if base_energy >= 80 else ''}")


        char_configs = getattr(ctx.cultivate_detail, 'character_score_configs', {})
        period_key = 'junior' if period_idx == 0 else 'classic' if period_idx == 1 else 'senior'

        deck_multipliers = [1.0] * 5
        try:
            pcs = getattr(ctx.task.detail, 'pal_card_store', {})
            if isinstance(pcs, dict):
                deck_counts = [0] * 6
                for card_info in pcs.values():
                    if not isinstance(card_info, dict):
                        continue
                    c_type = card_info.get('type')
                    if c_type is None:
                        continue
                    if hasattr(c_type, 'value'):
                        c_type = c_type.value
                    if isinstance(c_type, str):
                        c_type_lower = c_type.lower()
                        if 'speed' in c_type_lower: c_type = 1
                        elif 'stamina' in c_type_lower: c_type = 2
                        elif 'power' in c_type_lower: c_type = 3
                        elif 'guts' in c_type_lower or 'will' in c_type_lower: c_type = 4
                        elif 'wit' in c_type_lower or 'intelligence' in c_type_lower: c_type = 5
                        else: continue
                    if isinstance(c_type, int) and 1 <= c_type <= 5:
                        deck_counts[c_type] += 1
                passed_days = max(1, int(date)) - 1
                decay = passed_days * 0.0018
                for i in range(5):
                    count = deck_counts[i+1]
                    card_boost = 0.0
                    for j in range(count):
                        card_boost += max(0.0, 0.018 - (j * 0.001))
                    deck_multipliers[i] = 1.0 + max(0.0, card_boost - decay)
            if any(m != 1.0 for m in deck_multipliers) and date < 60:
                log.info(f"Deck multipliers: Spd:{deck_multipliers[0]:.3f} Sta:{deck_multipliers[1]:.3f} Pow:{deck_multipliers[2]:.3f} Guts:{deck_multipliers[3]:.3f} Wit:{deck_multipliers[4]:.3f}")
        except Exception:
            pass

        for idx in range(5):
            til = ctx.cultivate_detail.turn_info.training_info_list[idx]
            target_type_val = idx + 1
            pal_count = 0
            score = base_scores[idx] if isinstance(base_scores, (list, tuple)) and len(base_scores) > idx else 0.0
            
            lv1c = 0
            lv2c = 0
            lv1_total = 0.0
            lv2_total = 0.0
            npc = 0
            npc_total_contrib = 0.0

            detected_chars = getattr(til, 'detected_characters', [])
            slot_name_map = {}
            for slot_idx, card_name, cscore in detected_chars:
                if card_name:
                    slot_name_map[slot_idx] = card_name

            sc_list = getattr(til, "support_card_info_list", []) or []
            for sc_idx, sc in enumerate(sc_list):
                favor = getattr(sc, "favor", SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN)
                card_type = getattr(sc, "card_type", SupportCardType.SUPPORT_CARD_TYPE_UNKNOWN)
                
                if card_type == SupportCardType.SUPPORT_CARD_TYPE_NPC:
                    npc += 1
                    npc_scores = getattr(ctx.cultivate_detail, 'npc_score_value', DEFAULT_NPC_SCORE_VALUE)
                    npc_period_idx = get_date_period_index(date)
                    npc_add = 0.0
                    if npc_period_idx < len(npc_scores):
                        npc_arr = npc_scores[npc_period_idx]
                        if favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1:
                            npc_add = npc_arr[0]
                        elif favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_2:
                            npc_add = npc_arr[1]
                        elif favor in (SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_3, SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_4):
                            npc_add = npc_arr[2]
                    score += npc_add
                    npc_total_contrib += npc_add
                    continue

                if card_type == SupportCardType.SUPPORT_CARD_TYPE_UNKNOWN or favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN:
                    continue

                if card_type == SupportCardType.SUPPORT_CARD_TYPE_FRIEND:
                    pal_count += 1
                    pal_scores = ctx.cultivate_detail.pal_friendship_score
                    if favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1:
                        score += pal_scores[0]
                    elif favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_2:
                        score += pal_scores[1]
                    elif favor in (SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_3, SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_4):
                        score += pal_scores[2]
                    continue

                if card_type == SupportCardType.SUPPORT_CARD_TYPE_GROUP:
                    if favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1:
                        score += w_lv1
                    elif favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_2:
                        score += w_lv2
                    continue

                char_name = slot_name_map.get(sc_idx)
                if char_name and char_name in char_configs:
                    cfg = char_configs[char_name].get(period_key, {})
                    if favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1:
                        add_val = cfg.get('blue', 0)
                        score += add_val
                        lv1_total += add_val
                        lv1c += 1
                    elif favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_2:
                        add_val = cfg.get('green', 0)
                        score += add_val
                        lv2_total += add_val
                        lv2c += 1
                    elif favor in (SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_3, SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_4):
                        score += cfg.get('yellow', 0)
                else:
                    if favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_1:
                        score += w_lv1
                        lv1_total += w_lv1
                        lv1c += 1
                    elif favor == SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_2:
                        score += w_lv2
                        lv2_total += w_lv2
                        lv2c += 1
            
            stat_results = getattr(til, 'stat_results', {})
            stat_score = 0.0
            stat_parts = []
            # Per-stat hard cap: once a stat reaches its configured cap (expect_attribute,
            # one value per stat in order speed/stamina/power/guts/wit), stop counting gains
            # in THAT stat — but keep the other stats' gains, so a buffed off-type training
            # (e.g. a Speed facility that also gives Power) can still win. A cap of 0 (or a
            # very high value like 9999) effectively means "no cap" for that stat.
            for sk_idx, sk in enumerate(stat_keys):
                sv_val = stat_results.get(sk, 0)
                if sv_val > 0:
                    if (stat_caps is not None and sk_idx < 5
                            and stat_caps[sk_idx] > 0
                            and curr_stat_vals[sk_idx] >= stat_caps[sk_idx]):
                        stat_parts.append(f"{sk}:{sv_val} (capped)")
                        continue
                    contrib = sv_val * stat_mult[sk_idx]
                    stat_score += contrib
                    stat_contributions[idx][sk_idx] = contrib
                    if pre_highest_stat_idx is not None and sk_idx == pre_highest_stat_idx:
                        stat_parts.append(f"{sk}:{sv_val} (-5% score)")
                    else:
                        stat_parts.append(f"{sk}:{sv_val}")
            
            score += stat_score
            stat_scores[idx] = stat_score
            try:
                fr = int(getattr(til, 'failure_rate', -1))
            except Exception:
                fr = -1
            hint_bonus = 0.0
            selected_hint_count = 0
            regular_hint_count = 0
            try:
                boost_chars = getattr(ctx.cultivate_detail, 'hint_boost_characters', [])
                boost_mult = getattr(ctx.cultivate_detail, 'hint_boost_multiplier', 100) / 100.0
                char_list_hint = getattr(til, 'detected_characters', [])
                has_any_hint = False
                hint_total = 0.0
                hint_count = 0
                for char_name, cscore, c_has_hint in char_list_hint:
                    if c_has_hint:
                        has_any_hint = True
                        if char_name in boost_chars:
                            hint_total += w_hint * boost_mult
                            selected_hint_count += 1
                        else:
                            hint_total += w_hint
                            regular_hint_count += 1
                        hint_count += 1
                if hint_count > 0:
                    hint_bonus = hint_total / hint_count
                elif not has_any_hint and bool(getattr(til, 'has_hint', False)):
                    hint_bonus = w_hint
                    regular_hint_count = 1
            except Exception:
                hint_bonus = w_hint if bool(getattr(til, 'has_hint', False)) else 0.0
            score += hint_bonus
            energy_change_val = getattr(til, 'energy_change', 0.0)
            energy_change_contrib = energy_change_val * w_energy_change * energy_penalty_mult
            if base_energy is not None and base_energy >= 80 and energy_change_val < 0:
                energy_change_contrib *= 0.9
            score += energy_change_contrib
            scenario_additive = 0.0
            scenario_multiplier = 1.0
            scenario_formula_parts = []
            scenario_mult_parts = []
            try:
                scenario = ctx.cultivate_detail.scenario
                if scenario is not None:
                    scenario_additive, scenario_multiplier, scenario_formula_parts, scenario_mult_parts = scenario.compute_scenario_bonuses(
                        ctx, idx, getattr(til, "support_card_info_list", []), date, period_idx, current_energy)
            except Exception:
                pass
            score += scenario_additive

            # Investment Scoring
            facility_bonus = 0.0
            try:
                date_val = int(date)
                f_period_idx = get_facility_period_index(date_val)
                if f_period_idx < 6:
                    period_cfg = ctx.cultivate_detail.facility_period_configs[f_period_idx]
                    if period_cfg.get('enabled', False):
                        f_key = FACILITY_NAME_MAP.get(TrainingType(idx + 1))
                        if f_key:
                            f_clicks = ctx.cultivate_detail.facility_clicks.get(f_key, 0)
                            f_ratio_list = period_cfg.get('ratios', [1.0] * 5)
                            f_ratio = f_ratio_list[idx] if len(f_ratio_list) > idx else 1.0
                            facility_bonus = float(period_cfg.get('base', 0.0)) + (float(period_cfg.get('scale', 0.0)) * f_clicks * f_ratio)
                            score += facility_bonus
                            if facility_bonus != 0:
                                scenario_formula_parts.append(f"fac:{facility_bonus:.1f}")
            except Exception as e:
                log.debug(f"Facility bonus error: {e}")

            pre_mult_score = score

            pal_mult = 1.0
            if pal_count > 0:
                clamped_multiplier = max(0.0, min(1.0, ctx.cultivate_detail.pal_card_multiplier))
                pal_mult = 1.0 + clamped_multiplier
                score *= pal_mult
            
            fail_mult = 1.0
            try:
                energy_item_used = getattr(ctx.cultivate_detail.turn_info, 'energy_item_used', False)
                if getattr(ctx.cultivate_detail, 'compensate_failure', True):
                    fr_val = int(getattr(til, 'failure_rate', -1))
                    if fr_val >= 0:
                        fail_mult = max(0.0, 1.0 - (float(fr_val) / 50.0))
                        if not energy_item_used:
                            score *= fail_mult
            except Exception:
                pass
            pre_fail_score = score / fail_mult if fail_mult > 0 and fail_mult != 1.0 and not getattr(ctx.cultivate_detail.turn_info, 'energy_item_used', False) else score

            energy_mult = 1.0
            if idx == 4 and current_energy is not None:
                if current_energy > 90:
                    if date > 72:
                        energy_mult = 0.35
                    else:
                        energy_mult = 0.75
                elif 85 > current_energy:
                    energy_mult = 1.03
                score *= energy_mult

            if scenario_multiplier != 1.0:
                score *= scenario_multiplier

            # Per-stat capping (Option A) already removed the capped stat's own gain
            # in the stat-contribution loop above, keeping cross-stat gains.
            # Option B (hard cap): if THIS facility's primary stat is already at/over
            # its cap, deprioritize the whole facility so it only wins when its
            # cross-stat value is genuinely high.
            target_mult = 1.0
            try:
                if (stat_caps is not None and idx < 5
                        and stat_caps[idx] > 0
                        and curr_stat_vals[idx] >= stat_caps[idx]):
                    target_mult = CAPPED_FACILITY_SCORE_MULT
                    score *= target_mult
            except Exception:
                pass

            weight_mult = 1.0
            try:
                ew = extra_weight[idx] if isinstance(extra_weight, (list, tuple)) and len(extra_weight) == 5 else 0.0
            except Exception:
                ew = 0.0
            if ew > -1.0:
                weight_mult = 1.0 + float(ew)
                if weight_mult < 0.0:
                    weight_mult = 0.0
                elif weight_mult > 2.0:
                    weight_mult = 2.0
                score *= weight_mult

            deck_mult = 1.0
            if date < 60:
                deck_mult = deck_multipliers[idx]
                score *= deck_mult

            computed_scores[idx] = score
            original_scores[idx] = pre_fail_score
            facility_mults[idx] = score / pre_mult_score if abs(pre_mult_score) > 1e-12 else 0.0
            
            base_val = base_scores[idx] if isinstance(base_scores, (list, tuple)) and len(base_scores) > idx else 0.0
            lv1_contrib = lv1_total
            lv2_contrib = lv2_total
            
            formula_parts = []
            formula_parts.append(f"base:{base_val:.2f}")
            if stat_score > 0:
                formula_parts.append(f"stats:+{stat_score:.3f}")
            if lv1_contrib > 0:
                formula_parts.append(f"lv1({lv1c}):+{lv1_contrib:.3f}")
            if lv2_contrib > 0:
                formula_parts.append(f"lv2({lv2c}):+{lv2_contrib:.3f}")
            if energy_change_contrib != 0:
                formula_parts.append(f"nrg({energy_change_val:+.1f}):{energy_change_contrib:+.3f}")
            if npc_total_contrib > 0:
                formula_parts.append(f"npc({npc}):+{npc_total_contrib:.3f}")
            if hint_bonus > 0:
                total_hints = selected_hint_count + regular_hint_count
                if total_hints > 1:
                    formula_parts.append(f"hint(avg {total_hints}):+{hint_bonus:.3f} (sel:{selected_hint_count} reg:{regular_hint_count})")
                elif selected_hint_count > 0:
                    formula_parts.append(f"hint(selected):+{hint_bonus:.3f}")
                else:
                    formula_parts.append(f"hint:+{hint_bonus:.3f}")
            formula_parts.extend(scenario_formula_parts)
            
            mult_parts = []
            if pal_mult != 1.0:
                mult_parts.append(f"pal:x{pal_mult:.2f}")
            if fail_mult != 1.0:
                mult_parts.append(f"fail:x{fail_mult:.2f}")
            if energy_mult != 1.0:
                mult_parts.append(f"energy:x{energy_mult:.2f}")
            mult_parts.extend(scenario_mult_parts)
            if target_mult != 1.0:
                mult_parts.append(f"target:x{target_mult:.2f}")
            if weight_mult != 1.0:
                mult_parts.append(f"weight:x{weight_mult:.2f}")
            if deck_mult != 1.0:
                mult_parts.append(f"deck:x{deck_mult:.3f}")
            
            formula_str = " ".join(formula_parts)
            if mult_parts:
                formula_str += " | " + " ".join(mult_parts)
            
            stat_str = " | " + " ".join(stat_parts) if stat_parts else ""
            nrg_change = getattr(til, 'energy_change', 0.0)
            nrg_str = f" | nrg:{nrg_change:+.1f}" if nrg_change != 0 else ""
            log.info(f"{names[idx]}: {score:.3f} = [{formula_str}]{stat_str}{nrg_str}")

        if is_mant:
            try:
                from module.umamusume.scenario.mant.training_recovery import save_megaphone_scan_state_and_tick
                save_megaphone_scan_state_and_tick(ctx)
            except Exception:
                pass

        ctx.cultivate_detail.turn_info.parse_train_info_finish = True
        
        ctx.cultivate_detail.turn_info.cached_original_scores = list(original_scores)

        ctx.cultivate_detail.turn_info.cached_stat_scores = list(stat_scores)

        mega_mult = 1.0
        if is_mant:
            mega_tier = getattr(ctx.cultivate_detail, 'mant_megaphone_tier', 0)
            mega_turns = getattr(ctx.cultivate_detail, 'mant_megaphone_turns', 0)
            if mega_turns > 0:
                mega_mult = {1: 1.20, 2: 1.40, 3: 1.60}.get(mega_tier, 1.0)

        best_stat_score = max(stat_scores) if stat_scores else 0.0
        unboosted_stat_score = best_stat_score / mega_mult

        if not hasattr(ctx.cultivate_detail, 'stat_only_history'):
            ctx.cultivate_detail.stat_only_history = []
        ctx.cultivate_detail.stat_only_history.append(unboosted_stat_score)
        if len(ctx.cultivate_detail.stat_only_history) > MAX_DATAPOINTS:
            ctx.cultivate_detail.stat_only_history = ctx.cultivate_detail.stat_only_history[-MAX_DATAPOINTS:]
        ctx.cultivate_detail.turn_info.cached_stat_only_score = best_stat_score

        if not hasattr(ctx.cultivate_detail, 'energy_history'):
            ctx.cultivate_detail.energy_history = []
        if not hasattr(ctx.cultivate_detail, 'raw_stat_history'):
            ctx.cultivate_detail.raw_stat_history = []
        if not hasattr(ctx.cultivate_detail, 'date_history'):
            ctx.cultivate_detail.date_history = []
        energy_val = getattr(ctx.cultivate_detail.turn_info, 'cached_energy', 0) or 0
        ctx.cultivate_detail.energy_history.append(float(energy_val))
        if len(ctx.cultivate_detail.energy_history) > MAX_DATAPOINTS:
            ctx.cultivate_detail.energy_history = ctx.cultivate_detail.energy_history[-MAX_DATAPOINTS:]
        raw_best = 0.0
        for idx2 in range(5):
            til2 = ctx.cultivate_detail.turn_info.training_info_list[idx2]
            sr = getattr(til2, 'stat_results', {})
            raw_sum = sum(v for v in sr.values() if v > 0)
            if raw_sum > raw_best:
                raw_best = raw_sum
        
        unboosted_raw_best = raw_best / mega_mult
        ctx.cultivate_detail.raw_stat_history.append(unboosted_raw_best)
        if len(ctx.cultivate_detail.raw_stat_history) > MAX_DATAPOINTS:
            ctx.cultivate_detail.raw_stat_history = ctx.cultivate_detail.raw_stat_history[-MAX_DATAPOINTS:]
        ctx.cultivate_detail.date_history.append(int(date))
        if len(ctx.cultivate_detail.date_history) > MAX_DATAPOINTS:
            ctx.cultivate_detail.date_history = ctx.cultivate_detail.date_history[-MAX_DATAPOINTS:]

        try:
            from module.umamusume.persistence import save_career_data
            save_career_data(ctx)
        except Exception:
            pass

        for idx in range(5):
            if extra_weight[idx] == -1:
                computed_scores[idx] = -float('inf')

        try:
            d = int(ctx.cultivate_detail.turn_info.date)
        except Exception:
            d = -1
        highest_stat_idx = None
        if isinstance(d, int) and d > 48 and d <= 72:
            try:
                uma = ctx.cultivate_detail.turn_info.uma_attribute
                stats = [uma.speed, uma.stamina, uma.power, uma.will, uma.intelligence]
                highest_stat_idx = int(np.argmax(stats)) if len(stats) == 5 else None
                if highest_stat_idx is not None:
                    computed_scores[highest_stat_idx] *= 0.95
                    facility_mults[highest_stat_idx] *= 0.95
                    for i in range(5):
                        penalty = stat_contributions[i][highest_stat_idx] * 0.05
                        if penalty > 0:
                            computed_scores[i] -= penalty
            except Exception:
                pass

        raw_max_score = max(computed_scores) if len(computed_scores) == 5 else 0.0
        eps = 1e-9
        history = []
        percentile = 100.0
        
        blocked_count = sum(blocked_trainings)
        available_trainings = [i for i, blocked in enumerate(blocked_trainings) if not blocked]
        risk_blocked_trainings = [False] * 5
        failure_limit = get_max_failure_rate(ctx)
        detected_failure_rates = []
        for idx in range(5):
            try:
                fr_val = int(getattr(ctx.cultivate_detail.turn_info.training_info_list[idx], 'failure_rate', -1))
            except Exception:
                fr_val = -1
            detected_failure_rates.append(fr_val)
        failure_summary = ", ".join(
            f"{names[idx]}={'?' if val < 0 else str(val) + '%'}"
            for idx, val in enumerate(detected_failure_rates)
        )
        log.info(f"Failure rates detected: {failure_summary}")

        if not getattr(ctx.cultivate_detail.turn_info, 'charm_used_this_turn', False):
            for idx in available_trainings:
                fr_val = detected_failure_rates[idx]
                if fr_val < 0:
                    risk_blocked_trainings[idx] = True
                    computed_scores[idx] = -float('inf')
                    log.info(f"{names[idx]} blocked by failure limit: unreadable failure rate")
                elif fr_val >= failure_limit:
                    risk_blocked_trainings[idx] = True
                    computed_scores[idx] = -float('inf')
                    log.info(f"{names[idx]} blocked by failure limit: {fr_val}% >= {failure_limit}%")

        safe_available_trainings = [i for i in available_trainings if not risk_blocked_trainings[i]]
        if available_trainings and not safe_available_trainings:
            readable_risk_blocked = any(
                detected_failure_rates[idx] >= failure_limit
                for idx in available_trainings
                if detected_failure_rates[idx] >= 0
            )
            if is_mant and readable_risk_blocked:
                try:
                    from module.umamusume.scenario.mant.training_recovery import (
                        choose_training_failure_recovery_action,
                        handle_charm,
                        handle_energy_recovery,
                        rescan_training,
                    )
                    action, item_name = choose_training_failure_recovery_action(ctx)
                    if action == "charm" and handle_charm(ctx, force=True):
                        log.info(
                            f"All available trainings exceed failure limit ({failure_limit}%) - "
                            f"used {item_name} and will re-evaluate"
                        )
                        rescan_training(ctx, in_place=True)
                        return
                    if action == "energy_item" and handle_energy_recovery(ctx, item_name=item_name, mode="failure"):
                        log.info(
                            f"All available trainings exceed failure limit ({failure_limit}%) - "
                            f"used {item_name} and will re-evaluate"
                        )
                        rescan_training(ctx, in_place=True)
                        return
                except Exception:
                    pass
            ctx.cultivate_detail.turn_info.force_safe_recovery = True
            log.info(f"All available trainings exceed failure limit ({failure_limit}%) - preferring recovery")

        ctx.cultivate_detail.turn_info.cached_computed_scores = list(computed_scores)
        ctx.cultivate_detail.turn_info.cached_facility_mults = list(facility_mults)

        max_score = max(computed_scores) if len(computed_scores) == 5 else 0.0
        if not hasattr(ctx.cultivate_detail, 'score_history'):
            ctx.cultivate_detail.score_history = []
        stat_boost_amt = best_stat_score - unboosted_stat_score
        history_score = raw_max_score if raw_max_score != -float('inf') else max_score
        unboosted_total_score = history_score - stat_boost_amt
        ctx.cultivate_detail.score_history.append(unboosted_total_score)

        if len(ctx.cultivate_detail.score_history) >= 2:
            history = ctx.cultivate_detail.score_history
            best_score = history[-1]
            prev = history[:-1]
            below_count = sum(1 for s in prev if s < best_score)
            percentile = below_count / len(prev) * 100
            ctx.cultivate_detail.percentile_history.append(percentile)
        else:
            history = ctx.cultivate_detail.score_history

        if len(ctx.cultivate_detail.score_history) > MAX_DATAPOINTS:
            ctx.cultivate_detail.score_history = ctx.cultivate_detail.score_history[-MAX_DATAPOINTS:]
            history = ctx.cultivate_detail.score_history
        
        if len(safe_available_trainings) == 1:
            chosen_idx = safe_available_trainings[0]
        elif available_trainings and not safe_available_trainings:
            chosen_idx = 4 if 4 in available_trainings else available_trainings[0]
        else:
        
            if not hasattr(ctx.cultivate_detail.turn_info, 'race_search_attempted') and date <= 72:
                wit_race_threshold = getattr(ctx.cultivate_detail, 'wit_race_search_threshold', 0.15)
                
                current_energy = getattr(ctx.cultivate_detail.turn_info, 'cached_energy', 0)
                if current_energy == 0:
                    from bot.conn.fetch import read_energy
                    current_energy = read_energy()
                    ctx.cultivate_detail.turn_info.cached_energy = current_energy
                
                from module.umamusume.asset.race_data import get_races_for_period
                next_date = ctx.cultivate_detail.turn_info.date + 1
                available_races = get_races_for_period(next_date)
                has_extra_race_next = len([r for r in ctx.cultivate_detail.extra_race_list 
                                           if r in available_races]) > 0
                
                if (max_score < wit_race_threshold and 
                    current_energy > 90 and 
                    not has_extra_race_next):
                    
                    log.info(f"Race search: Max score {max_score:.3f}<{wit_race_threshold}, Energy {current_energy}>90, No races next turn")
                    
                    ctx.cultivate_detail.turn_info.race_search_attempted = True
                    
                    op = TurnOperation()
                    op.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_RACE
                    op.race_id = 0
                    ctx.cultivate_detail.turn_info.turn_operation = op
                    
                    ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
                    return
            
            if date in (35, 36, 59, 60):
                best_idx_tmp = int(np.argmax(computed_scores))
                best_score_tmp = computed_scores[best_idx_tmp]
                summer_threshold = getattr(ctx.cultivate_detail, 'summer_score_threshold', 0.34)
                if best_score_tmp < summer_threshold:
                    log.info(f"Low training score before summer, conserving energy (score < {summer_threshold:.2f})")
                    chosen_idx = 4
                else:
                    ties = [i for i, v in enumerate(computed_scores) if abs(v - max_score) < eps]
                    chosen_idx = 4 if 4 in ties else (min(ties) if len(ties) > 0 else best_idx_tmp)
            else:
                ties = [i for i, v in enumerate(computed_scores) if abs(v - max_score) < eps]
                chosen_idx = 4 if 4 in ties else (min(ties) if len(ties) > 0 else int(np.argmax(computed_scores)))
        local_training_type = TrainingType(chosen_idx + 1)
        log.info(
            "[TIMING] training score/decision took %.0f ms",
            (time.perf_counter() - decision_t0) * 1000.0,
        )
       
        ctx.cultivate_detail.turn_info.cached_training_type = local_training_type
        try:
            uma = ctx.cultivate_detail.turn_info.uma_attribute
            ctx.cultivate_detail.last_decision_stats = (uma.speed, uma.stamina, uma.power, uma.will, uma.intelligence)
        except Exception:
            pass
       

    force_safe_recovery = getattr(ctx.cultivate_detail.turn_info, 'force_safe_recovery', False)
    ctx.cultivate_detail.turn_info.force_safe_recovery = False
    planner_turn = plan_training_turn(ctx, local_training_type, force_safe_recovery=force_safe_recovery)
    set_turn_plan(ctx, planner_turn)
    log.info(
        "[TIMING] training select evaluation total took %.0f ms",
        (time.perf_counter() - script_t0) * 1000.0,
    )
    if planner_turn.primary_action == "training":
        log.info(
            "Training decision: scored_best=%s final=%s reason=%s",
            local_training_type.name,
            planner_turn.training_type.name,
            planner_turn.reason or "-",
        )
    else:
        log.info(
            "Training decision redirected: scored_best=%s final_action=%s reason=%s",
            local_training_type.name,
            planner_turn.primary_action,
            planner_turn.reason or "-",
        )
    new_is_race = (planner_turn.primary_action == "race")

    if not new_is_race:
        ctx.cultivate_detail.mant_cleat_used = False

    mant_recovery_pending = (
        is_mant
        and planner_turn.primary_action == "training"
        and any(action in ("energy_item", "charm") for action in getattr(planner_turn, "pre_actions", []) or [])
    )
    mant_recovery_priority = False
    if is_mant:
        try:
            from module.umamusume.scenario.mant.policy import should_prefer_training_recovery_over_rest
            mant_recovery_priority = should_prefer_training_recovery_over_rest(ctx, energy)
        except Exception:
            mant_recovery_priority = False


    if getattr(ctx.cultivate_detail, 'group_card_enabled', False):
        gc_dates = getattr(ctx.cultivate_detail, 'group_card_available_dates', [])
        gc_percentile = getattr(ctx.cultivate_detail, 'group_card_percentile', 26)
        if not (mant_recovery_pending or mant_recovery_priority) and gc_dates and len(history) >= 2:
            if percentile < gc_percentile:
                from module.umamusume.asset.race_data import get_races_for_period
                date = ctx.cultivate_detail.turn_info.date
                available_races = get_races_for_period(date)
                has_race_this_turn = any(r in ctx.cultivate_detail.extra_race_list for r in available_races)
                has_scheduled = False
                try:
                    from module.umamusume.scenario.mant.policy import has_scheduled_race_this_turn as check_fn
                    has_scheduled = check_fn(ctx)
                except Exception:
                    pass
                if not (has_race_this_turn or has_scheduled):
                    from module.umamusume.script.cultivate_task.helpers import TRAINING_REPLACEMENT_DATES
                    matching = [d for d in TRAINING_REPLACEMENT_DATES if d in gc_dates]
                    if matching:
                        ctx.cultivate_detail.turn_info.turn_operation = TurnOperation()
                        ctx.cultivate_detail.turn_info.turn_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_REST
                        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
                        return

    try:
        best_idx_tmp = int(np.argmax(computed_scores))
        best_score_tmp = computed_scores[best_idx_tmp]
    except Exception:
        best_idx_tmp = None
        best_score_tmp = 0.0
    
    if (not (mant_recovery_pending or mant_recovery_priority) and
        ctx.cultivate_detail.prioritize_recreation and 
        ctx.cultivate_detail.pal_event_stage > 0 and
        best_idx_tmp is not None):
        
        op_from_ai = ctx.cultivate_detail.turn_info.turn_operation
        
        is_race_operation = (op_from_ai is not None and 
                            op_from_ai.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_RACE)
        
        if is_race_operation:
            log.info("Race goal detected - prioritizing race over pal outing")
        elif op_from_ai is not None and op_from_ai.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_TRAINING:
            from bot.conn.fetch import fetch_state
            
            pal_name = ctx.cultivate_detail.pal_name
            pal_thresholds = ctx.cultivate_detail.pal_thresholds
            
            if pal_name and pal_thresholds:
                pal_data = pal_thresholds
                stage = ctx.cultivate_detail.pal_event_stage
                
                if stage <= len(pal_data):
                    thresholds = pal_data[stage - 1]
                    mood_threshold, energy_threshold, score_threshold = thresholds
                    
                    state = fetch_state(ctx.current_screen)
                    current_energy = state.get("energy", 0)
                    current_mood_raw = state.get("mood")
                    current_mood = current_mood_raw if current_mood_raw is not None else 4
                    current_score = best_score_tmp
                    
                    mood_below = current_mood <= mood_threshold
                    energy_below = current_energy <= energy_threshold
                    score_below = current_score <= score_threshold
                    
                    conditions_met = sum([mood_below, energy_below, score_below])
                    
                    if conditions_met >= 2:
                        log.info("2/3 conditions met - overriding to pal outing")
                        if op_from_ai.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_RACE:
                            ctx.cultivate_detail.mant_cleat_used = False
                        op_from_ai.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_TRIP
                        ctx.cultivate_detail.turn_info.turn_operation = op_from_ai
                        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
                        return
                    else:
                        log.info("At least one condition failed - continuing with training")
    
    op = ctx.cultivate_detail.turn_info.turn_operation

    if op is not None and op.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_TRAINING:
        try:
            if ctx.cultivate_detail.scenario.scenario_type() == ScenarioType.SCENARIO_TYPE_MANT:
                pre_actions = list(getattr(planner_turn, 'pre_actions', []) or [])
                for action in pre_actions:
                    if action in ("energy_item", "charm"):
                        if execute_mant_pre_action(ctx, action, getattr(planner_turn, 'race_id', 0)):
                            if getattr(planner_turn, 'requires_replan_after_pre_action', False):
                                from module.umamusume.scenario.mant.training_recovery import rescan_training
                                rescan_training(ctx, in_place=True)
                                return

                from module.umamusume.scenario.mant.training_recovery import execute_training_commitment_actions
                execute_training_commitment_actions(
                    ctx,
                    planned_actions=[action for action in pre_actions if action in ("megaphone", "anklet")],
                    current_op=op,
                )

                if getattr(ctx.cultivate_detail.turn_info, 'post_item_rescan_needed', False):
                    from module.umamusume.scenario.mant.training_recovery import rescan_training
                    ctx.cultivate_detail.turn_info.post_item_rescan_needed = False
                    ctx.cultivate_detail.turn_info.energy_item_used = False
                    rescan_training(ctx, in_place=True)
                    return
        except Exception:
            log.exception("MANT training pre-actions failed")

        if op.training_type == TrainingType.TRAINING_TYPE_UNKNOWN:
            op.training_type = local_training_type

        idx = op.training_type.value - 1
        if 0 <= idx < 5:
            if not getattr(ctx.cultivate_detail.turn_info, 'facility_click_logged', False):
                facility_keys = ["speed", "stamina", "power", "guts", "wits"]
                key = facility_keys[idx]
                if not hasattr(ctx.cultivate_detail, "facility_clicks"):
                    ctx.cultivate_detail.facility_clicks = {"speed": 0, "stamina": 0, "power": 0, "guts": 0, "wits": 0}
                ctx.cultivate_detail.facility_clicks[key] += 1
                ctx.cultivate_detail.turn_info.facility_click_logged = True
                try:
                    from module.umamusume.persistence import save_career_data
                    save_career_data(ctx)
                except Exception:
                    pass

        ctx.ctrl.click_by_point(TRAINING_POINT_LIST[op.training_type.value - 1])
        time.sleep(0.15)
        ctx.ctrl.click_by_point(TRAINING_POINT_LIST[op.training_type.value - 1])
        time.sleep(0.5)
        return

    if (
        ctx.cultivate_detail.scenario.scenario_type() == ScenarioType.SCENARIO_TYPE_MANT
        and getattr(ctx.cultivate_detail.turn_info, 'energy_recovery_deferred', False)
    ):
        log.warning("Clearing stale MANT deferred recovery flag after training evaluation")
        ctx.cultivate_detail.turn_info.energy_recovery_deferred = False
        ctx.cultivate_detail.turn_info.post_item_rescan_needed = False
    ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
    return
