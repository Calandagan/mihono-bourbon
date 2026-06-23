import time
import cv2

import bot.base.log as logger
from bot.recog.image_matcher import image_match
from module.umamusume.context import UmamusumeContext
from module.umamusume.types import TurnInfo, TurnOperation
from module.umamusume.define import TurnOperationType
from module.umamusume.asset.point import (
    CULTIVATE_TRIP, CULTIVATE_REST, CULTIVATE_SKILL_LEARN,
    TO_TRAINING_SELECT, CULTIVATE_RACE, CULTIVATE_RACE_SUMMER,
    CULTIVATE_MEDIC, CULTIVATE_MEDIC_SUMMER,
    CULTIVATE_MEDIC_MANT, CULTIVATE_MEDIC_MANT_SUMMER,
    CULTIVATE_TRIP_MANT, CULTIVATE_RACE_MANT, CULTIVATE_RACE_MANT_SUMMER
)
from module.umamusume.define import ScenarioType
from module.umamusume.constants.game_constants import (
    is_summer_camp_period, is_ura_race, NEW_RUN_DETECTION_DATE,
    URA_QUALIFIER_ID, URA_SEMIFINAL_ID, URA_FINAL_IDS, PRE_DEBUT_END
)
from module.umamusume.constants.timing_constants import (
    MEDIC_CHECK_DELAY, RACE_SEARCH_TIMEOUT
)
from module.umamusume.script.cultivate_task.parse import parse_date, parse_cultivate_main_menu
from module.umamusume.script.cultivate_task.helpers import should_use_pal_outing_simple, detect_pal_stage, should_use_group_card_recreation, execute_group_card_recreation, detect_group_card_dates
from module.umamusume.script.cultivate_task.planner import (
    plan_main_menu_turn,
    set_turn_plan,
    execute_mant_pre_action,
)
from bot.recog.energy_scanner import scan_energy

log = logger.get_logger(__name__)


def is_mant(ctx):
    try:
        return ctx.cultivate_detail.scenario.scenario_type() == ScenarioType.SCENARIO_TYPE_MANT
    except Exception:
        return False


def get_trip(ctx):
    return CULTIVATE_TRIP_MANT if is_mant(ctx) else CULTIVATE_TRIP


def get_race(ctx, summer=False):
    if is_mant(ctx):
        return CULTIVATE_RACE_MANT_SUMMER if summer else CULTIVATE_RACE_MANT
    return CULTIVATE_RACE_SUMMER if summer else CULTIVATE_RACE


def get_medic(ctx, summer=False):
    if is_mant(ctx):
        return CULTIVATE_MEDIC_MANT_SUMMER if summer else CULTIVATE_MEDIC_MANT
    return CULTIVATE_MEDIC_SUMMER if summer else CULTIVATE_MEDIC


def set_race_operation(ctx: UmamusumeContext, race_id=None):
    turn_info = ctx.cultivate_detail.turn_info
    if turn_info.turn_operation is None:
        turn_info.turn_operation = TurnOperation()
    turn_info.turn_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_RACE
    if race_id is not None:
        turn_info.turn_operation.race_id = race_id
    turn_info.parse_train_info_finish = True


def request_training_select(ctx: UmamusumeContext, *, reason: str = "") -> bool:
    turn_info = ctx.cultivate_detail.turn_info
    attempt = int(getattr(turn_info, "training_select_request_count", 0) or 0) + 1
    turn_info.training_select_request_count = attempt
    turn_info.pending_training_scan = True
    turn_info.parse_main_menu_finish = False
    turn_info.parse_train_info_finish = False

    x = TO_TRAINING_SELECT.coordinate.x
    y = TO_TRAINING_SELECT.coordinate.y
    suffix = f" ({reason})" if reason else ""
    log.info("Requesting training select attempt %s%s", attempt, suffix)

    primary_name = f"Go to Training Selection [{attempt % 2}]"
    secondary_name = f"Go to Training Selection [{(attempt + 1) % 2}]"

    from module.umamusume.scenario.mant.inventory import is_on_main_menu, is_on_training_screen

    def _click_once(click_name: str, hold_duration: int) -> None:
        ctx.ctrl.click(x, y, name=click_name, random_offset=False, hold_duration=hold_duration)

    def _wait_for_transition(timeout_s: float = 0.7) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            time.sleep(0.12)
            frame = ctx.ctrl.get_screen(force=True)
            ctx.current_screen = frame
            if is_on_training_screen(frame):
                log.info("Training select detected after request attempt %s", attempt)
                turn_info.pending_training_scan = False
                turn_info.training_select_request_count = 0
                return True
            if frame is not None and not is_on_main_menu(frame):
                return True
        return False

    if attempt >= 3:
        _click_once(primary_name, 90)
        if _wait_for_transition():
            return True
        _click_once(secondary_name, 0)
        _wait_for_transition()
    else:
        _click_once(primary_name, 0)
        if _wait_for_transition():
            return True
        _click_once(secondary_name, 0)
        _wait_for_transition()
    return True


def execute_turn_plan(ctx: UmamusumeContext, plan, current_date, img) -> bool:
    if plan is None:
        return False

    turn_info = ctx.cultivate_detail.turn_info
    if is_mant(ctx) and plan.pre_actions:
        for action in plan.pre_actions:
            try:
                executed = execute_mant_pre_action(ctx, action, plan.race_id)
            except Exception:
                executed = False
            if executed and plan.primary_action == "training" and plan.requires_replan_after_pre_action:
                base_energy, _, _ = scan_energy(ctx.ctrl)
                turn_info.cached_energy = base_energy
                turn_info.base_energy = base_energy
                turn_info.turn_operation = None
                return request_training_select(ctx, reason="after pre-action replan")

    if plan.primary_action == "training":
        base_energy, _, _ = scan_energy(ctx.ctrl)
        turn_info.base_energy = base_energy
        return request_training_select(ctx, reason="turn plan training")

    if plan.primary_action == "race":
        set_race_operation(ctx, plan.race_id if plan.race_id else None)
        is_summer = is_summer_camp_period(current_date)
        ctx.ctrl.click_by_point(get_race(ctx, summer=is_summer))
        return True

    if plan.primary_action == "trip":
        if should_use_group_card_recreation(ctx):
            if execute_group_card_recreation(ctx, trip_click_point=get_trip(ctx)):
                return True
        if is_summer_camp_period(current_date):
            ctx.ctrl.click(68, 991, "Summer Camp")
        else:
            ctx.ctrl.click_by_point(get_trip(ctx))
        return True

    if plan.primary_action == "rest":
        if should_use_group_card_recreation(ctx):
            if execute_group_card_recreation(ctx, trip_click_point=get_trip(ctx)):
                return True
        if should_use_pal_outing_simple(ctx):
            ctx.ctrl.click_by_point(get_trip(ctx))
            return True
        turn_info.turn_operation = None
        turn_info.parse_main_menu_finish = False
        turn_info.parse_train_info_finish = False
        ctx.ctrl.click_by_point(CULTIVATE_REST)
        return True

    if plan.primary_action == "medic":
        is_summer = is_summer_camp_period(current_date)
        ctx.ctrl.click_by_point(get_medic(ctx, summer=is_summer))
        time.sleep(MEDIC_CHECK_DELAY)
        img = ctx.ctrl.get_screen()
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if is_mant(ctx):
            check_point = img_rgb[1118, 100] if is_summer else img_rgb[1125, 43]
        elif is_summer:
            check_point = img_rgb[1130, 200]
        else:
            check_point = img_rgb[1125, 105]
        if not (check_point[0] > 200 and check_point[1] > 200 and check_point[2] > 200):
            ctx.cultivate_detail.turn_info.medic_room_available = False
            from bot.base.runtime_state import set_state
            set_state("trigger_decision_reset", True)
        return True

    return False


def script_cultivate_main_menu(ctx: UmamusumeContext):
    img = ctx.current_screen
    current_date = parse_date(img, ctx)
    from bot.base.runtime_state import set_state
    set_state("in_career_run", True)
    if current_date == -1:
        current_date = -(len(ctx.cultivate_detail.turn_info_history) + 1)

    last_known_date = getattr(ctx.cultivate_detail, '_last_known_date_id', -1)
    if last_known_date != -1 and current_date > 0:
        if current_date != last_known_date and current_date != last_known_date + 1:
            if current_date > last_known_date + 1:
                from module.umamusume.persistence import clear_all_persistence
                clear_all_persistence()
                ctx.cultivate_detail.mant_megaphone_tier = 0
                ctx.cultivate_detail.mant_megaphone_turns = 0
                ctx.cultivate_detail.mant_megaphone_attempt_turn = None
                ctx.cultivate_detail.mant_megaphone_attempt_name = None
                ctx.cultivate_detail.mant_debut_retry_pending = False
                ctx.cultivate_detail.mant_debut_retry_count = 0
                ctx.cultivate_detail.mant_debut_retry_last_click_at = 0.0
                ctx.cultivate_detail.mant_afflictions = []
                ctx.cultivate_detail.mant_owned_items = []
            elif current_date < last_known_date:
                from module.umamusume.persistence import clear_career_data, clear_mant_run_state
                clear_career_data()
                clear_mant_run_state()
                ctx.cultivate_detail.mant_megaphone_tier = 0
                ctx.cultivate_detail.mant_megaphone_turns = 0
                ctx.cultivate_detail.mant_megaphone_attempt_turn = None
                ctx.cultivate_detail.mant_megaphone_attempt_name = None
                ctx.cultivate_detail.mant_debut_retry_pending = False
                ctx.cultivate_detail.mant_debut_retry_count = 0
                ctx.cultivate_detail.mant_debut_retry_last_click_at = 0.0
                ctx.cultivate_detail.mant_afflictions = []
                ctx.cultivate_detail.mant_owned_items = []
                ctx.cultivate_detail.mant_inventory_scanned = False
                ctx.cultivate_detail.mant_inventory_rescan_pending = False
                ctx.cultivate_detail.facility_clicks = {"speed": 0, "stamina": 0, "power": 0, "guts": 0, "wits": 0}

        ctx.cultivate_detail._last_known_date_id = current_date
        from module.umamusume.persistence import save_last_known_date
        save_last_known_date(current_date)
    elif last_known_date == -1 and current_date > 0:
        ctx.cultivate_detail._last_known_date_id = current_date
        from module.umamusume.persistence import save_last_known_date
        save_last_known_date(current_date)

    if ctx.cultivate_detail.turn_info is None or abs(current_date) != abs(ctx.cultivate_detail.turn_info.date):
        if ctx.cultivate_detail.turn_info is not None:
            ctx.cultivate_detail.turn_info_history.append(ctx.cultivate_detail.turn_info)
            if len(ctx.cultivate_detail.turn_info_history) > 100:
                ctx.cultivate_detail.turn_info_history = ctx.cultivate_detail.turn_info_history[-100:]
        ctx.cultivate_detail.turn_info = TurnInfo()
        ctx.cultivate_detail.turn_info.date = current_date
        ctx.cultivate_detail.mant_shop_scanned_this_turn = False
        if current_date > 0:
            ctx.cultivate_detail.group_card_available_dates = []
            ctx.cultivate_detail.pal_event_stage = 0
            if hasattr(ctx.cultivate_detail, 'pal_last_detection_date'):
                delattr(ctx.cultivate_detail, 'pal_last_detection_date')
        if is_mant(ctx):
            from module.umamusume.scenario.mant.main_menu import handle_mant_turn_start
            handle_mant_turn_start(ctx, current_date)
    else:
        ctx.cultivate_detail.turn_info.date = current_date

        if is_mant(ctx):
            from module.umamusume.scenario.mant.main_menu import handle_mant_turn_start
            handle_mant_turn_start(ctx, current_date)

        if current_date == NEW_RUN_DETECTION_DATE:
            ctx.cultivate_detail.manual_purchase_completed = False
            if hasattr(ctx.cultivate_detail, 'manual_purchase_initiated'):
                delattr(ctx.cultivate_detail, 'manual_purchase_initiated')

    from bot.conn.fetch import read_mood
    ctx.cultivate_detail.turn_info.cached_mood = read_mood(img)

    if not ctx.cultivate_detail.turn_info.parse_main_menu_finish:
        parse_cultivate_main_menu(ctx, img)

        from module.umamusume.asset.race_data import get_races_for_period
        available_races = get_races_for_period(ctx.cultivate_detail.turn_info.date)
        ctx.cultivate_detail.turn_info.cached_available_races = available_races
        ctx.cultivate_detail.turn_info.parse_main_menu_finish = True

    has_extra_race = len([race_id for race_id in ctx.cultivate_detail.extra_race_list
                         if race_id in ctx.cultivate_detail.turn_info.cached_available_races]) != 0

    if not has_extra_race:
        if getattr(ctx.cultivate_detail, 'group_card_enabled', False):
            if not ctx.cultivate_detail.group_card_available_dates:
                img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                from module.umamusume.asset.template import UI_RECREATION_FRIEND_NOTIFICATION
                ts_result = image_match(img_gray, UI_RECREATION_FRIEND_NOTIFICATION)
                if ts_result.find_match:
                    dates = detect_group_card_dates(ctx)
                    ctx.cultivate_detail.group_card_available_dates = dates
                time.sleep(0.5)
                img = ctx.ctrl.get_screen()
                ctx.current_screen = img

        if not getattr(ctx.cultivate_detail, 'group_card_enabled', False) and ctx.cultivate_detail.prioritize_recreation:
            pal_detection_date = getattr(ctx.cultivate_detail, 'pal_last_detection_date', -1)
            if ctx.cultivate_detail.pal_event_stage <= 0 and current_date != pal_detection_date:
                img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                from module.umamusume.asset.template import UI_RECREATION_FRIEND_NOTIFICATION
                result = image_match(img_gray, UI_RECREATION_FRIEND_NOTIFICATION)

                if result.find_match:
                    ctx.ctrl.click_by_point(get_trip(ctx))
                    time.sleep(0.15)
                    img = ctx.ctrl.get_screen()

                    calculated_stage = detect_pal_stage(ctx, img)
                    ctx.cultivate_detail.pal_event_stage = calculated_stage
                    ctx.cultivate_detail.pal_last_detection_date = current_date

                    pal_thresholds = ctx.cultivate_detail.pal_thresholds
                    if pal_thresholds and calculated_stage <= len(pal_thresholds):
                        thresholds = pal_thresholds[calculated_stage - 1]
                        mood, energy, score = thresholds

                    ctx.ctrl.click(5, 5)
                    time.sleep(0.15)
                    ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
                    return
                else:
                    if ctx.cultivate_detail.pal_event_stage > 0:
                        ctx.cultivate_detail.pal_event_stage = 0

    if has_extra_race and not is_mant(ctx):
        if ctx.cultivate_detail.turn_info.turn_operation is None:
            ctx.cultivate_detail.turn_info.turn_operation = TurnOperation()
            ctx.cultivate_detail.turn_info.turn_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_RACE
            matching_races = [race_id for race_id in ctx.cultivate_detail.extra_race_list if race_id in ctx.cultivate_detail.turn_info.cached_available_races]
            if matching_races:
                target_race_id = matching_races[0]
                ctx.cultivate_detail.turn_info.turn_operation.race_id = target_race_id
            else:
                pass
            ctx.cultivate_detail.turn_info.parse_train_info_finish = True

    if is_mant(ctx):
        from module.umamusume.scenario.mant.main_menu import handle_mant_main_menu
        if handle_mant_main_menu(ctx, img, current_date):
            return

    available_races = getattr(ctx.cultivate_detail.turn_info, 'cached_available_races', None)
    if available_races is None:
        from module.umamusume.asset.race_data import get_races_for_period
        available_races = get_races_for_period(ctx.cultivate_detail.turn_info.date)
        ctx.cultivate_detail.turn_info.cached_available_races = available_races
    has_extra_race = len([race_id for race_id in ctx.cultivate_detail.extra_race_list
                         if race_id in available_races]) != 0
    has_scheduled_race = False
    if is_mant(ctx):
        try:
            from module.umamusume.scenario.mant.policy import has_scheduled_race_this_turn
            has_scheduled_race = has_scheduled_race_this_turn(ctx)
        except Exception:
            has_scheduled_race = False

    turn_operation = ctx.cultivate_detail.turn_info.turn_operation

    if (not ctx.cultivate_detail.cultivate_finish and
        not ctx.cultivate_detail.turn_info.turn_learn_skill_done and
        ctx.cultivate_detail.learn_skill_done):
        ctx.cultivate_detail.reset_skill_learn()

    skip_auto_skill_learning = (ctx.task.detail.manual_purchase_at_end and ctx.cultivate_detail.cultivate_finish)


    if (ctx.cultivate_detail.turn_info.uma_attribute.skill_point > ctx.cultivate_detail.learn_skill_threshold
            and not ctx.cultivate_detail.turn_info.turn_learn_skill_done
            and not skip_auto_skill_learning):
        if (ctx.cultivate_detail.learn_skill_only_user_provided
                and len(ctx.cultivate_detail.learn_skill_list) == 0):
            ctx.cultivate_detail.learn_skill_done = True
            ctx.cultivate_detail.turn_info.turn_learn_skill_done = True
        else:
            ctx.ctrl.click_by_point(CULTIVATE_SKILL_LEARN)
            ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
            return
    else:
        if not ctx.cultivate_detail.cultivate_finish:
            ctx.cultivate_detail.reset_skill_learn()


    if (not is_mant(ctx)
            and turn_operation is not None
            and turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_REST):
        if should_use_group_card_recreation(ctx):
            if execute_group_card_recreation(ctx, trip_click_point=get_trip(ctx)):
                return
        if should_use_pal_outing_simple(ctx):
            ctx.ctrl.click_by_point(get_trip(ctx))
            return
        ctx.cultivate_detail.turn_info.turn_operation = None
        ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
        ctx.cultivate_detail.turn_info.parse_train_info_finish = False
        ctx.ctrl.click_by_point(CULTIVATE_REST)
        return

    if (not is_mant(ctx)
            and turn_operation is not None
            and turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_TRIP):
        if should_use_group_card_recreation(ctx):
            if execute_group_card_recreation(ctx, trip_click_point=get_trip(ctx)):
                return
        if is_summer_camp_period(ctx.cultivate_detail.turn_info.date):
            ctx.ctrl.click(68, 991, "Summer Camp")
        else:
            ctx.ctrl.click_by_point(get_trip(ctx))
        return

    mood = ctx.cultivate_detail.turn_info.cached_mood
    is_summer = is_summer_camp_period(ctx.cultivate_detail.turn_info.date)
    if not is_mant(ctx) and is_summer and mood is not None and mood <= 2:
        from bot.conn.fetch import read_energy
        energy = read_energy()
        if energy == 0:
            time.sleep(0.15)
            energy = read_energy()
        if energy > 0 and energy < 33:
            has_race = False
            try:
                from module.umamusume.asset.race_data import get_races_for_period
                date = ctx.cultivate_detail.turn_info.date
                available_races = get_races_for_period(date)
                has_race = any(r in ctx.cultivate_detail.extra_race_list for r in available_races)
                if not has_race:
                    from module.umamusume.scenario.mant.policy import has_scheduled_race_this_turn as check_fn
                    has_race = check_fn(ctx)
            except Exception:
                pass
            if not has_race:
                if should_use_pal_outing_simple(ctx):
                    ctx.ctrl.click_by_point(get_trip(ctx))
                else:
                    ctx.ctrl.click_by_point(CULTIVATE_REST)
                return

    if is_mant(ctx):
        from module.umamusume.scenario.mant.main_menu import handle_mant_rival_race
        handle_mant_rival_race(ctx, img)

    planner_turn = plan_main_menu_turn(ctx)
    set_turn_plan(ctx, planner_turn)
    if execute_turn_plan(ctx, planner_turn, current_date, img):
        return
    if is_mant(ctx):
        log.warning(
            "Planner did not dispatch MANT action cleanly: %s",
            getattr(planner_turn, "primary_action", None),
        )
        return

    if not ctx.cultivate_detail.turn_info.parse_train_info_finish:
        limit = int(getattr(ctx.cultivate_detail, 'rest_threshold', getattr(ctx.cultivate_detail, 'rest_treshold', getattr(ctx.cultivate_detail, 'fast_path_energy_limit', 48))))
        if has_extra_race and not is_mant(ctx):
            ctx.cultivate_detail.turn_info.parse_train_info_finish = True
            return
        if limit == 0:
            energy = 100
        else:
            base_energy, _, _ = scan_energy(ctx.ctrl)
            energy = base_energy
            if energy == 0:
                time.sleep(0.15)
                base_energy, _, _ = scan_energy(ctx.ctrl)
                energy = base_energy
        if is_mant(ctx) and energy <= limit:
            ctx.cultivate_detail.turn_info.cached_energy = energy

            if getattr(ctx.cultivate_detail.turn_info, 'charm_used_this_turn', False):
                if has_scheduled_race:
                    set_race_operation(ctx)
                    is_summer = is_summer_camp_period(ctx.cultivate_detail.turn_info.date)
                    ctx.ctrl.click_by_point(get_race(ctx, summer=is_summer))
                    return
                ctx.cultivate_detail.turn_info.base_energy = energy
                ctx.ctrl.click_by_point(TO_TRAINING_SELECT)
                return

            from module.umamusume.scenario.mant.policy import has_scheduled_race_this_turn
            has_race_this_turn = has_scheduled_race_this_turn(ctx)
            
            if has_race_this_turn or has_extra_race:
                from module.umamusume.scenario.mant.policy import has_energy_recovery
                if has_energy_recovery(ctx):
                    ctx.cultivate_detail.turn_info.energy_recovery_deferred = True
            else:
                from module.umamusume.scenario.mant.policy import has_charm
                if has_charm(ctx):
                    ctx.cultivate_detail.turn_info.energy_recovery_deferred = True
                else:
                    from module.umamusume.scenario.mant.policy import get_low_energy_threshold
                    from module.umamusume.scenario.mant.training_recovery import handle_energy_recovery
                    if handle_energy_recovery(
                        ctx,
                        mode="critical_low" if energy <= get_low_energy_threshold() else "failure",
                    ):
                        energy = getattr(ctx.cultivate_detail.turn_info, 'cached_energy', energy)
        if energy <= limit:
            if getattr(ctx.cultivate_detail.turn_info, 'energy_recovery_deferred', False):
                if has_scheduled_race:
                    ctx.cultivate_detail.turn_info.skip_training_review_for_race = True
                else:
                    ctx.cultivate_detail.turn_info.skip_training_review_for_race = False
                base_energy, _, _ = scan_energy(ctx.ctrl)
                ctx.cultivate_detail.turn_info.base_energy = base_energy
                ctx.ctrl.click_by_point(TO_TRAINING_SELECT)
                return

            _extra_now = [r for r in ctx.cultivate_detail.extra_race_list
                          if r in ctx.cultivate_detail.turn_info.cached_available_races]
            if _extra_now:
                target_race_id = _extra_now[0]
                op = TurnOperation()
                op.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_RACE
                op.race_id = target_race_id
                ctx.cultivate_detail.turn_info.turn_operation = op
                ctx.cultivate_detail.turn_info.parse_train_info_finish = True
                is_summer = is_summer_camp_period(ctx.cultivate_detail.turn_info.date)
                ctx.ctrl.click_by_point(get_race(ctx, summer=is_summer))
                return
            if has_scheduled_race:
                set_race_operation(ctx)
                is_summer = is_summer_camp_period(ctx.cultivate_detail.turn_info.date)
                ctx.ctrl.click_by_point(get_race(ctx, summer=is_summer))
                return
            if should_use_group_card_recreation(ctx):
                if execute_group_card_recreation(ctx, trip_click_point=get_trip(ctx)):
                    return
            if should_use_pal_outing_simple(ctx):
                ctx.ctrl.click_by_point(get_trip(ctx))
            else:
                ctx.ctrl.click_by_point(CULTIVATE_REST)
            return
        else:
            if has_scheduled_race:
                set_race_operation(ctx)
                is_summer = is_summer_camp_period(ctx.cultivate_detail.turn_info.date)
                ctx.ctrl.click_by_point(get_race(ctx, summer=is_summer))
                return
            base_energy, _, _ = scan_energy(ctx.ctrl)
            ctx.cultivate_detail.turn_info.base_energy = base_energy
            ctx.ctrl.click_by_point(TO_TRAINING_SELECT)
            return

    if turn_operation is not None:
        if turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_TRAINING:
            if getattr(ctx.cultivate_detail.turn_info, 'base_energy', None) is None:
                base_energy, _, _ = scan_energy(ctx.ctrl)
                ctx.cultivate_detail.turn_info.base_energy = base_energy
            ctx.ctrl.click_by_point(TO_TRAINING_SELECT)
        elif turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_REST:
            if should_use_group_card_recreation(ctx):
                if execute_group_card_recreation(ctx, trip_click_point=get_trip(ctx)):
                    return
            if should_use_pal_outing_simple(ctx):
                ctx.ctrl.click_by_point(get_trip(ctx))
                return
            ctx.cultivate_detail.turn_info.turn_operation = None
            ctx.cultivate_detail.turn_info.parse_main_menu_finish = False
            ctx.cultivate_detail.turn_info.parse_train_info_finish = False
            ctx.ctrl.click_by_point(TO_TRAINING_SELECT)
        elif turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_MEDIC:
            is_summer = is_summer_camp_period(ctx.cultivate_detail.turn_info.date)
            ctx.ctrl.click_by_point(get_medic(ctx, summer=is_summer))
            time.sleep(MEDIC_CHECK_DELAY)
            img = ctx.ctrl.get_screen()
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            if is_mant(ctx):
                if is_summer:
                    check_point = img_rgb[1118, 100]
                else:
                    check_point = img_rgb[1125, 43]
            elif is_summer:
                check_point = img_rgb[1130, 200]
            else:
                check_point = img_rgb[1125, 105]
            if not (check_point[0] > 200 and check_point[1] > 200 and check_point[2] > 200):
                ctx.cultivate_detail.turn_info.medic_room_available = False
                from bot.base.runtime_state import set_state
                set_state("trigger_decision_reset", True)
        elif turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_TRIP:
            if is_summer_camp_period(ctx.cultivate_detail.turn_info.date):
                ctx.ctrl.click(68, 991, "Summer Camp")
            else:
                ctx.ctrl.click_by_point(get_trip(ctx))
        elif turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_RACE:
            race_id = turn_operation.race_id

            if race_id == 0 and current_date <= PRE_DEBUT_END:
                ctx.cultivate_detail.turn_info.turn_operation = None
                base_energy, _, _ = scan_energy(ctx.ctrl)
                ctx.cultivate_detail.turn_info.base_energy = base_energy
                ctx.ctrl.click_by_point(TO_TRAINING_SELECT)
                return

            if race_id is None and has_extra_race:
                available_races = get_races_for_period(ctx.cultivate_detail.turn_info.date)
                for race_id in ctx.cultivate_detail.extra_race_list:
                    if race_id in available_races:
                        turn_operation.race_id = race_id
                        break

            if is_ura_race(race_id):
                img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                from module.umamusume.asset.template import UI_CULTIVATE_URA_RACE_1, UI_CULTIVATE_URA_RACE_2, UI_CULTIVATE_URA_RACE_3

                ura_race_available = False
                ura_phase = ""

                if race_id == URA_QUALIFIER_ID:
                    ura_race_available = image_match(img_gray, UI_CULTIVATE_URA_RACE_1).find_match
                    ura_phase = "Qualifier"
                elif race_id == URA_SEMIFINAL_ID:
                    ura_race_available = image_match(img_gray, UI_CULTIVATE_URA_RACE_2).find_match
                    ura_phase = "Semi-final"
                elif race_id in URA_FINAL_IDS:
                    ura_race_available = image_match(img_gray, UI_CULTIVATE_URA_RACE_3).find_match
                    ura_phase = "Final"

                if ura_race_available:
                    if is_mant(ctx):
                        from module.umamusume.scenario.mant.race_prep import handle_energy_drink_max_before_race, handle_glow_sticks_before_race
                        handle_energy_drink_max_before_race(ctx)
                        handle_glow_sticks_before_race(ctx)
                    is_summer = is_summer_camp_period(ctx.cultivate_detail.turn_info.date)
                    ctx.ctrl.click_by_point(get_race(ctx, summer=is_summer))
                else:
                    ctx.cultivate_detail.turn_info.turn_operation = None
                    if not ctx.cultivate_detail.turn_info.parse_train_info_finish:
                        ctx.cultivate_detail.turn_info.parse_train_info_finish = True
                        return
                    else:
                        ctx.ctrl.click_by_point(TO_TRAINING_SELECT)
            else:
                ti = ctx.cultivate_detail.turn_info
                op = ctx.cultivate_detail.turn_info.turn_operation
                if not hasattr(ti, 'race_search_started_at') or getattr(ti, 'race_search_id', None) != race_id:
                    ti.race_search_started_at = time.time()
                    ti.race_search_id = race_id
                elif time.time() - ti.race_search_started_at > RACE_SEARCH_TIMEOUT:
                    try:
                        if getattr(ctx.task.detail, 'extra_race_list', None) is ctx.cultivate_detail.extra_race_list:
                            ctx.cultivate_detail.extra_race_list = list(ctx.cultivate_detail.extra_race_list)
                        if race_id and race_id in ctx.cultivate_detail.extra_race_list:
                            ctx.cultivate_detail.extra_race_list.remove(race_id)
                            from module.umamusume.asset.race_data import compute_race_chains
                            ctx.cultivate_detail.race_chain_map = compute_race_chains(ctx.cultivate_detail.extra_race_list)
                    except Exception as e:
                        pass
                    ctx.cultivate_detail.turn_info.turn_operation = None
                    if hasattr(ti, 'race_search_started_at'):
                        delattr(ti, 'race_search_started_at')
                    if hasattr(ti, 'race_search_id'):
                        delattr(ti, 'race_search_id')
                    return
                if is_mant(ctx):
                    from module.umamusume.scenario.mant.race_prep import handle_energy_drink_max_before_race, handle_glow_sticks_before_race
                    handle_energy_drink_max_before_race(ctx)
                    handle_glow_sticks_before_race(ctx)
                is_summer = is_summer_camp_period(ctx.cultivate_detail.turn_info.date)
                ctx.ctrl.click_by_point(get_race(ctx, summer=is_summer))
