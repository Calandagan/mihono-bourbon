import time
import random
import cv2

import bot.base.log as logger
from bot.recog.image_matcher import image_match, compare_color_equal
from module.umamusume.context import UmamusumeContext
from module.umamusume.types import TurnInfo
from module.umamusume.define import TurnOperationType
from module.umamusume.asset.point import (
    CULTIVATE_GOAL_RACE_INTER_1, CULTIVATE_GOAL_RACE_INTER_2,
    RETURN_TO_CULTIVATE_MAIN_MENU, BEFORE_RACE_START, BEFORE_RACE_SKIP,
    BEFORE_RACE_CHANGE_TACTIC, IN_RACE_UMA_LIST_CONFIRM, IN_RACE_SKIP,
    RACE_RESULT_CONFIRM, RACE_REWARD_CONFIRM, TO_TRAINING_SELECT
)
from module.umamusume.asset.template import (
    REF_RACE_LIST, REF_RACE_LIST_GOAL_RACE, REF_RACE_LIST_URA_RACE,
    REF_SUITABLE_RACE, REF_TRAIN_BTN
)
from module.umamusume.script.cultivate_task.parse import parse_date, find_race

log = logger.get_logger(__name__)


def script_cultivate_goal_race(ctx: UmamusumeContext):
    log.info("Entering goal race function")

    mant_cfg = getattr(getattr(ctx.task.detail, 'scenario_config', None), 'mant_config', None)
    if mant_cfg is not None:
        img_gray = cv2.cvtColor(ctx.current_screen, cv2.COLOR_BGR2GRAY)
        train_btn_visible = image_match(img_gray, REF_TRAIN_BTN).find_match
        if train_btn_visible:
            if ctx.cultivate_detail.turn_info is not None:
                ctx.cultivate_detail.mant_climax_pending_train = False
                ctx.cultivate_detail.turn_info.parse_train_info_finish = False
                ctx.cultivate_detail.turn_info.turn_operation = None
            ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
            ctx.ctrl.trigger_decision_reset = True
            return

    img = ctx.current_screen
    current_date = parse_date(img, ctx)
    
    if current_date == -1:
        if not hasattr(ctx.cultivate_detail, 'goal_race_parse_failures'):
            ctx.cultivate_detail.goal_race_parse_failures = 0
        
        ctx.cultivate_detail.goal_race_parse_failures += 1
        log.warning(f"Failed to parse date (attempt {ctx.cultivate_detail.goal_race_parse_failures})")
        
        if ctx.cultivate_detail.goal_race_parse_failures >= 3:
            ctx.ctrl.trigger_decision_reset = True
            ctx.cultivate_detail.goal_race_parse_failures = 0
        return
    
    ctx.cultivate_detail.goal_race_parse_failures = 0
    
    if ctx.cultivate_detail.turn_info is None or current_date != ctx.cultivate_detail.turn_info.date:
        if ctx.cultivate_detail.turn_info is not None:
            ctx.cultivate_detail.turn_info_history.append(ctx.cultivate_detail.turn_info)
            if len(ctx.cultivate_detail.turn_info_history) > 100:
                ctx.cultivate_detail.turn_info_history = ctx.cultivate_detail.turn_info_history[-100:]
        ctx.cultivate_detail.turn_info = TurnInfo()
        ctx.cultivate_detail.turn_info.date = current_date
    
    if ctx.cultivate_detail.turn_info.turn_operation:
        race_id = ctx.cultivate_detail.turn_info.turn_operation.race_id
        log.info(f"Current race ID: {race_id}")
        if race_id in [2381, 2382, 2385, 2386, 2387]:
            log.info("This is a URA championship race - proceeding directly to start")
            ctx.ctrl.click_by_point(CULTIVATE_GOAL_RACE_INTER_2)
        else:
            log.info(f"This is a regular race (ID: {race_id}) - entering detail interface")
            if mant_cfg is not None and race_id == 0:
                from module.umamusume.scenario.mant.race_prep import (
                    handle_energy_drink_max_before_race, handle_glow_sticks_before_race
                )
                handle_energy_drink_max_before_race(ctx)
                handle_glow_sticks_before_race(ctx)
                ctx.cultivate_detail.mant_climax_pending_train = True
                ctx.cultivate_detail.turn_info.turn_operation.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_RACE
                ctx.cultivate_detail.turn_info.turn_operation.race_id = 0
            ctx.ctrl.click_by_point(CULTIVATE_GOAL_RACE_INTER_1)
    else:
        log.warning("No turn operation found - cannot determine race type")
        ctx.ctrl.click_by_point(CULTIVATE_GOAL_RACE_INTER_1)


def try_use_cleat(ctx, race_id, is_climax=False):
    mant_cfg = getattr(getattr(ctx.task.detail, 'scenario_config', None), 'mant_config', None)
    if mant_cfg is None:
        return False
    from module.umamusume.scenario.mant.race_prep import handle_cleat_before_race
    return handle_cleat_before_race(ctx, race_id, is_climax)


def script_cultivate_race_list(ctx: UmamusumeContext):
    log.info("Entered Race List menu (CULTIVATE_RACE_LIST)")
    deadline = time.time() + 6.0
    while time.time() < deadline:
        img_check = ctx.ctrl.get_screen(to_gray=True)
        if image_match(img_check, REF_RACE_LIST).find_match:
            break
        time.sleep(0.17)
    if ctx.cultivate_detail.turn_info is None:
        log.warning("Turn information not initialized")
        ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
        return

    turn_op = ctx.cultivate_detail.turn_info.turn_operation
    if turn_op and turn_op.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_RACE:
        race_id = turn_op.race_id
        race_source = getattr(turn_op, "source", "") or ""

        if race_id == 0 and race_source == "legacy_fallback":
            log.info("Suitable race search mode")
            time.sleep(0.4)
            
            img_gray = ctx.ctrl.get_screen(to_gray=True)
            
            suitable_match = image_match(img_gray, REF_SUITABLE_RACE)
            
            if suitable_match.find_match:
                log.info("Found suitable race")
                if hasattr(ctx.cultivate_detail.turn_info, "set_race_trace"):
                    ctx.cultivate_detail.turn_info.set_race_trace(
                        candidates=[{"race_id": 0, "mode": "suitable_race", "source": "legacy_fallback", "matched": True, "rejected": False}]
                    )
                try_use_cleat(ctx, race_id, is_climax=True)
                center_x = suitable_match.center_point[0]
                center_y = suitable_match.center_point[1]
                ctx.ctrl.click(center_x, center_y, "Suitable race")
                time.sleep(0.5)
                ctx.ctrl.click_by_point(CULTIVATE_GOAL_RACE_INTER_1)
                return
            else:
                log.info("No suitable race, continuing with wit training")
                current_turn = int(getattr(ctx.cultivate_detail.turn_info, "date", 0) or 0)
                rejections = getattr(ctx.cultivate_detail, "mant_race_rejections", set())
                rejections.add((current_turn, 0))
                ctx.cultivate_detail.mant_race_rejections = rejections
                if hasattr(ctx.cultivate_detail.turn_info, "set_race_trace"):
                    ctx.cultivate_detail.turn_info.set_race_trace(
                        rejections=[{"turn": current_turn, "race_id": 0, "source": "legacy_fallback", "reason": "no_suitable_race_match"}]
                    )
                ctx.cultivate_detail.turn_info.race_search_attempted = True
                ctx.cultivate_detail.turn_info.turn_operation = None
                ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
                return
    
    img = cv2.cvtColor(ctx.current_screen, cv2.COLOR_BGR2GRAY)
    
    goal_match = image_match(img, REF_RACE_LIST_GOAL_RACE).find_match
    ura_match = image_match(img, REF_RACE_LIST_URA_RACE).find_match
    
    log.info(f"Template matching - Goal Race: {goal_match}, URA Race: {ura_match}")
    
    if goal_match:
        log.info("Found Goal Race - clicking to enter detail interface")
        try_use_cleat(ctx, getattr(turn_op, 'race_id', 0) if turn_op else 0, is_climax=True)
        ctx.ctrl.click_by_point(CULTIVATE_GOAL_RACE_INTER_1)
    elif ura_match:
        log.info("Found URA Race - clicking to enter detail interface")
        try_use_cleat(ctx, getattr(turn_op, 'race_id', 0) if turn_op else 0, is_climax=True)
        ctx.ctrl.click_by_point(CULTIVATE_GOAL_RACE_INTER_1)
    else:
        if ctx.cultivate_detail.turn_info.turn_operation is None:
            log.warning("No turn operation - returning to main menu")
            ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
            return
        else:
            log.info(f"Turn operation type: {ctx.cultivate_detail.turn_info.turn_operation.turn_operation_type}")
            if ctx.cultivate_detail.turn_info.turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_RACE:
                race_id = ctx.cultivate_detail.turn_info.turn_operation.race_id
                log.info(f"Race operation with ID: {race_id}")
                if race_id in [2381, 2382, 2385, 2386, 2387] or race_id == 0:
                    log.info("Detected URA race operation - clicking race button directly")
                    try_use_cleat(ctx, race_id, is_climax=(race_id == 0))
                    ctx.ctrl.click(319, 1082, "URA Race Button")
                    time.sleep(0.4)
                    return
        if ctx.cultivate_detail.turn_info.turn_operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_RACE:
            target_race_id = ctx.cultivate_detail.turn_info.turn_operation.race_id
            log.info(f"Searching for race ID: {target_race_id}")
            
            direction = "down" # Start by searching downwards
            scrolled_down = False
            scrolled_up = False
            last_thumb_y = -1
            stall_count = 0
            
            search_deadline = time.time() + 45.0
            while time.time() < search_deadline:
                if not ctx.task.running():
                    break
                    
                img = ctx.ctrl.get_screen()
                ctx.current_screen = img
                
                # Try to find the race in the current view
                selected = find_race(ctx, img, target_race_id)
                if selected:
                    log.info(f"Found race ID: {target_race_id}")
                    try_use_cleat(ctx, target_race_id)
                    time.sleep(random.uniform(0.5, 0.7))
                    ctx.ctrl.click_by_point(CULTIVATE_GOAL_RACE_INTER_1)
                    return

                # Check scrollbar to detect limits robustly
                img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                
                # Race list scrollbar is usually at X=701, track from ~700 to ~1010
                thumb_y = None
                for y in range(700, 1015):
                    # Check if pixel is NOT the track color [211, 209, 219]
                    r, g, b = img_rgb[y, 701]
                    if abs(r - 211) > 10 or abs(g - 209) > 10 or abs(b - 219) > 10:
                        thumb_y = y
                        break
                
                at_top = (thumb_y is not None and thumb_y <= 715)
                at_bottom = True # Assume bottom if we can't find anything below
                for y in range(max(700, (thumb_y or 0) + 10), 1015):
                    r, g, b = img_rgb[y, 701]
                    if abs(r - 211) <= 10 and abs(g - 209) <= 10 and abs(b - 219) <= 10:
                        # Found track color below thumb, not at bottom yet
                        at_bottom = False
                        break

                # Logic to change direction or stop
                if direction == "down":
                    if at_bottom:
                        log.info("Reached bottom of race list, changing direction to UP")
                        direction = "up"
                        if at_top: # Small list
                            break
                        continue
                elif direction == "up":
                    if at_top:
                        log.info("Reached top of race list, race not found")
                        break
                
                # Deterministic, pure-vertical swipe for precise/repeatable scrolling
                sx = 360
                dur = 400

                if direction == "down":
                    y1, y2 = 900, 700
                    ctx.ctrl.swipe(x1=sx, y1=y1, x2=sx, y2=y2, duration=dur/1000.0, name="")
                    scrolled_down = True
                else:
                    y1, y2 = 700, 900
                    ctx.ctrl.swipe(x1=sx, y1=y1, x2=sx, y2=y2, duration=dur/1000.0, name="")
                    scrolled_up = True

                time.sleep(0.5)

            # If we reach here, the race wasn't found
            log.warning(f"Race ID {target_race_id} not found in list")
            current_turn = int(getattr(ctx.cultivate_detail.turn_info, 'date', 0) or 0)
            rejections = getattr(ctx.cultivate_detail, 'mant_race_rejections', set())
            rejections.add((current_turn, target_race_id))
            ctx.cultivate_detail.mant_race_rejections = rejections
            ctx.cultivate_detail.turn_info.set_race_trace(
                rejections=[{"turn": current_turn, "race_id": target_race_id, "reason": "not_found_in_race_list"}]
            )
            # Try to remove it from extra races if it's a failure
            try:
                if target_race_id in ctx.cultivate_detail.extra_race_list:
                    ctx.cultivate_detail.extra_race_list.remove(target_race_id)
            except Exception:
                pass
            ctx.cultivate_detail.turn_info.turn_operation = None
            ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)
        else:
            ctx.ctrl.click_by_point(RETURN_TO_CULTIVATE_MAIN_MENU)


def script_cultivate_before_race(ctx: UmamusumeContext):
    img = cv2.cvtColor(ctx.current_screen, cv2.COLOR_BGR2RGB)
    p_check_skip = img[1175, 330]

    date = ctx.cultivate_detail.turn_info.date
    if date != -1:
        tactic_check_point_list = [img[668, 480], img[668, 542], img[668, 600], img[668, 670]]
        target_tactic = None

        if hasattr(ctx.cultivate_detail, 'tactic_actions') and ctx.cultivate_detail.tactic_actions:
            for action in ctx.cultivate_detail.tactic_actions:
                op = action.get('op')
                val = int(action.get('val', 0))
                val2 = int(action.get('val2', 0))
                tactic = int(action.get('tactic', 0))
                
                match = False
                if op == '=':
                    if date == val: match = True
                elif op == '>':
                    if date > val: match = True
                elif op == '<':
                    if date < val: match = True
                elif op == 'range':
                    if val < date < val2: match = True
                
                if match:
                    target_tactic = tactic
                    break

        if target_tactic:
            p_check_tactic = tactic_check_point_list[target_tactic - 1]
            if compare_color_equal(p_check_tactic, [170, 170, 170]):
                ctx.ctrl.click_by_point(BEFORE_RACE_CHANGE_TACTIC)
                return
    if p_check_skip[0] < 200 and p_check_skip[1] < 200 and p_check_skip[2] < 200:
        ctx.ctrl.click_by_point(BEFORE_RACE_START)
    else:
        ctx.cultivate_detail.mant_cleat_used = False
        ctx.ctrl.click_by_point(BEFORE_RACE_SKIP)


def script_cultivate_in_race_uma_list(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(IN_RACE_UMA_LIST_CONFIRM)


def script_in_race(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(IN_RACE_SKIP)


def script_cultivate_race_result(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(RACE_RESULT_CONFIRM)


def script_cultivate_race_reward(ctx: UmamusumeContext):
    ctx.ctrl.click_by_point(RACE_REWARD_CONFIRM)
