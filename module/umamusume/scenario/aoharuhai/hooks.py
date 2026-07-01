import time
from bot.recog.image_matcher import image_match
from module.umamusume.asset.template import (
    REF_AOHARU_RACE, REF_SELECT_OPP2, REF_ALL_RES, REF_RACE_END, REF_RACE_END2,
    REF_TEAM_SHOWDOWN, REF_NEXT, REF_ROUND_1, REF_ROUND_2, REF_ROUND_3, REF_ROUND_4,
    REF_AOHARUHAI_TEAM_NAME_0, REF_AOHARUHAI_TEAM_NAME_1,
    REF_AOHARUHAI_TEAM_NAME_2, REF_AOHARUHAI_TEAM_NAME_3,
    REF_MANT_RESET_CLOCK
)
import bot.base.log as logger

log = logger.get_logger(__name__)

TEAM_SHOWDOWN_ROI = (0, 0, 230, 48)
TEAM_SHOWDOWN_RACE_X = 360
TEAM_SHOWDOWN_RACE_Y = 980
TEAM_SHOWDOWN_CONFIRM_X = 530
TEAM_SHOWDOWN_CONFIRM_Y = 975


def _is_team_showdown_screen(img):
    try:
        h, w = img.shape[:2]
        x1, y1, x2, y2 = TEAM_SHOWDOWN_ROI
        x1 = max(0, min(w, x1))
        x2 = max(x1, min(w, x2))
        y1 = max(0, min(h, y1))
        y2 = max(y1, min(h, y2))
        roi = img[y1:y2, x1:x2]
        return image_match(roi, REF_TEAM_SHOWDOWN).find_match
    except Exception:
        return False


def is_team_showdown_confirmation_popup(img):
    try:
        if not _is_team_showdown_screen(img):
            return False
        header_roi = img[300:360, 10:710]
        button_roi = img[900:1040, 370:690]
        if header_roi.size == 0 or button_roi.size == 0:
            return False
        header_mean = header_roi.mean(axis=(0, 1))
        button_mean = button_roi.mean(axis=(0, 1))
        header_is_green = (
            header_mean[1] > 150
            and header_mean[1] > header_mean[2] + 20
            and header_mean[1] > header_mean[0] + 20
        )
        button_is_green = (
            button_mean[1] > 140
            and button_mean[1] > button_mean[2] + 20
            and button_mean[1] > button_mean[0] + 20
        )
        return bool(header_is_green and button_is_green)
    except Exception:
        return False


def aoharuhai_after_hook(ctx, img):
    if image_match(img[984:1025, 297:365], REF_AOHARU_RACE).find_match:
        try:
            cd = getattr(getattr(ctx, 'cultivate_detail', None), 'event_cooldown_until', 0)
            if isinstance(cd, (int, float)) and time.time() < cd:
                return True
        except Exception:
            pass
        
        try:
            h, w = img.shape[:2]
            team_roi_x1, team_roi_y1, team_roi_x2, team_roi_y2 = 70, 315, 162, 811
            team_roi_x1 = max(0, min(w, team_roi_x1))
            team_roi_x2 = max(team_roi_x1, min(w, team_roi_x2))
            team_roi_y1 = max(0, min(h, team_roi_y1))
            team_roi_y2 = max(team_roi_y1, min(h, team_roi_y2))
            team_roi = img[team_roi_y1:team_roi_y2, team_roi_x1:team_roi_x2]
            
            for team_tpl in [REF_AOHARUHAI_TEAM_NAME_0, REF_AOHARUHAI_TEAM_NAME_1, 
                             REF_AOHARUHAI_TEAM_NAME_2, REF_AOHARUHAI_TEAM_NAME_3]:
                if image_match(team_roi, team_tpl).find_match:
                    log.info("Team name selection screen detected, skipping auto-click")
                    return True
        except Exception:
            pass
        
        try:
            ti = getattr(getattr(ctx, 'cultivate_detail', None), 'turn_info', None)
            roi = img[343:389, 443:485]
            refs = [REF_ROUND_1, REF_ROUND_2, REF_ROUND_3, REF_ROUND_4]
            for i, tpl in enumerate(refs):
                try:
                    if image_match(roi, tpl).find_match:
                        if ti is not None:
                            ti.aoharu_race_index = i
                        break
                except Exception:
                    continue
        except Exception:
            pass
        ctx.ctrl.click(344, 1091, 'Aoharu race')
        return True
    
    if image_match(img[1089:1113, 318:376], REF_SELECT_OPP2).find_match:
        try:
            sc = getattr(ctx.task.detail, 'scenario_config', None)
            aoharu_cfg = getattr(sc, 'aoharu_config', None)
            ti = getattr(getattr(ctx, 'cultivate_detail', None), 'turn_info', None)
            idx = getattr(ti, 'aoharu_race_index', None)
            prs = getattr(aoharu_cfg, 'preliminary_round_selections', None)
            if isinstance(idx, int) and isinstance(prs, (list, tuple)) and 0 <= idx < len(prs):
                sel = prs[idx]
                if sel == 1:
                    ctx.ctrl.click(339, 278, 'select opp')
                    time.sleep(0.5)
                elif sel == 2:
                    ctx.ctrl.click(335, 574, 'select opp')
                    time.sleep(0.5)
                elif sel == 3:
                    ctx.ctrl.click(339, 830, 'select opp')
                    time.sleep(0.5)
        except Exception:
            pass
        ctx.ctrl.click(355, 1082, 'select opp2')
        time.sleep(0.5)
        ctx.ctrl.click(522, 930, 'select opp2 cont')
        time.sleep(0.17)
        ctx.ctrl.click(522, 930, 'select opp2 cont')
        return True
    
    if image_match(img[1204:1219, 476:597], REF_ALL_RES).find_match:
        ctx.ctrl.click(536, 1211, 'all res')
        return True
    
    if image_match(img[43:72, 123:411], REF_RACE_END).find_match:
        ctx.ctrl.click(351, 1112, 'race end')
        return True
    
    if image_match(img[1204:1228, 319:399], REF_RACE_END2).find_match:
        try:
            from module.umamusume.define import ScenarioType
            if (hasattr(ctx, 'cultivate_detail') and hasattr(ctx.cultivate_detail, 'scenario')
                    and ctx.cultivate_detail.scenario.scenario_type() == ScenarioType.SCENARIO_TYPE_MANT
                    and ctx.cultivate_detail.clock_used <= ctx.cultivate_detail.clock_use_limit):
                clock_roi = img[1138:1212, 70:135]
                reset_match = image_match(clock_roi, REF_MANT_RESET_CLOCK)
                if reset_match.find_match:
                    cx, cy = reset_match.center_point
                    ctx.ctrl.click(cx + 70, cy + 1138, 'mant reset clock')
                    ctx.cultivate_detail.clock_used += 1
                    log.info("Clocks used: %s", ctx.cultivate_detail.clock_used)
                    time.sleep(0.2)
                    return True
        except Exception:
            pass
        ctx.ctrl.click(350, 1199, 'race end2')
        return True
    
    if image_match(img[1200:1222, 467:553], REF_RACE_END2).find_match:
        try:
            from module.umamusume.define import ScenarioType
            if (hasattr(ctx, 'cultivate_detail') and hasattr(ctx.cultivate_detail, 'scenario')
                    and ctx.cultivate_detail.scenario.scenario_type() == ScenarioType.SCENARIO_TYPE_MANT
                    and ctx.cultivate_detail.clock_used <= ctx.cultivate_detail.clock_use_limit):
                clock_roi = img[1138:1212, 70:135]
                reset_match = image_match(clock_roi, REF_MANT_RESET_CLOCK)
                if reset_match.find_match:
                    cx, cy = reset_match.center_point
                    ctx.ctrl.click(cx + 70, cy + 1138, 'mant reset clock')
                    ctx.cultivate_detail.clock_used += 1
                    log.info("Clocks used: %s", ctx.cultivate_detail.clock_used)
                    time.sleep(0.2)
                    return True
        except Exception:
            pass
        ctx.ctrl.click(508, 1196, 'race end2 b')
        return True
    
    if is_team_showdown_confirmation_popup(img):
        log.info("Final Aoharu Team Showdown confirmation detected - beginning Team Zenith showdown")
        ctx.ctrl.click(TEAM_SHOWDOWN_CONFIRM_X, TEAM_SHOWDOWN_CONFIRM_Y, 'team showdown begin')
        return True

    if _is_team_showdown_screen(img):
        log.info("Final Aoharu Team Showdown detected - starting Team Zenith race")
        ctx.ctrl.click(TEAM_SHOWDOWN_RACE_X, TEAM_SHOWDOWN_RACE_Y, 'team showdown race')
        return True
    
    if image_match(img[1097:1124, 327:393], REF_NEXT).find_match:
        ctx.ctrl.click(360, 1112, 'next')
        return True
    
    return False
