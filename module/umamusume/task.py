from enum import Enum
import math
from module.umamusume.define import ScenarioType
from bot.base.task import Task, TaskExecuteMode
from module.umamusume.constants.scoring_constants import (
    DEFAULT_BASE_SCORES,
    DEFAULT_MAX_FAILURE_RATE,
    DEFAULT_PAL_CARD_MULTIPLIER,
    DEFAULT_PAL_FRIENDSHIP_SCORES,
    DEFAULT_REST_THRESHOLD,
    DEFAULT_SPIRIT_EXPLOSION,
    DEFAULT_STAT_VALUE_MULTIPLIER,
    DEFAULT_SUMMER_SCORE_THRESHOLD,
    DEFAULT_WIT_SPECIAL_MULTIPLIER,
)
from module.umamusume.scenario.configs import ScenarioConfig, AoharuConfig, MantConfig
import bot.base.log as logger
log = logger.get_logger(__name__)
log = logger.get_logger(__name__)

DEFAULT_SCORE_VALUE = (
    (0.11, 0.10, 0.01, 0.09),
    (0.11, 0.10, 0.09, 0.09),
    (0.11, 0.10, 0.12, 0.09),
    (0.03, 0.05, 0.15, 0.09),
    (0, 0, 0.15, 0, 0),
)

DEFAULT_FACILITY_PERIOD_CONFIGS = tuple(
    {
        "enabled": False,
        "base": 0.0,
        "scale": 0.0,
        "ratios": [1.0] * 5,
    }
    for _ in range(6)
)


def _safe_int(value, default, minimum=None, maximum=None):
    try:
        if value is None or value == "":
            raise ValueError
        if isinstance(value, float) and math.isnan(value):
            raise ValueError
        value = int(float(value))
    except Exception:
        value = int(default)
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _safe_float(value, default, minimum=None, maximum=None):
    try:
        if value is None or value == "":
            raise ValueError
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            raise ValueError
    except Exception:
        value = float(default)
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _normalize_list(value, default, length=None, cast=float, minimum=None, maximum=None):
    src = value if isinstance(value, (list, tuple)) else []
    base = list(default if isinstance(default, (list, tuple)) else [])
    target_len = length if isinstance(length, int) and length > 0 else len(base)
    if target_len <= 0:
        target_len = len(src)
    result = []
    for idx in range(target_len):
        fallback = base[idx] if idx < len(base) else (base[-1] if base else 0)
        current = src[idx] if idx < len(src) else fallback
        if cast is int:
            result.append(_safe_int(current, fallback, minimum=minimum, maximum=maximum))
        else:
            result.append(_safe_float(current, fallback, minimum=minimum, maximum=maximum))
    return result


def _normalize_matrix(value, default, row_length=None, cast=float, minimum=None, maximum=None):
    src = value if isinstance(value, (list, tuple)) else []
    base = list(default if isinstance(default, (list, tuple)) else [])
    rows = max(len(src), len(base))
    result = []
    for idx in range(rows):
        fallback_row = list(base[idx]) if idx < len(base) and isinstance(base[idx], (list, tuple)) else []
        current_row = src[idx] if idx < len(src) else fallback_row
        row_len = row_length if isinstance(row_length, int) and row_length > 0 else len(fallback_row)
        result.append(
            _normalize_list(
                current_row,
                fallback_row,
                length=row_len,
                cast=cast,
                minimum=minimum,
                maximum=maximum,
            )
        )
    return result


def _maybe_warn_normalized(field_name, original, normalized):
    try:
        if original != normalized:
            log.warning("Normalized invalid task field '%s': %r -> %r", field_name, original, normalized)
    except Exception:
        pass


def _normalize_spirit_explosion(value):
    if isinstance(value, (list, tuple)) and value and isinstance(value[0], (list, tuple)):
        normalized = _normalize_matrix(value, [list(DEFAULT_SPIRIT_EXPLOSION) for _ in range(5)], row_length=5)
    else:
        normalized = _normalize_list(value, DEFAULT_SPIRIT_EXPLOSION, length=5)
    _maybe_warn_normalized("spirit_explosion", value, normalized)
    return normalized


def _normalize_facility_period_configs(value):
    src = value if isinstance(value, (list, tuple)) else []
    normalized = []
    for idx in range(len(DEFAULT_FACILITY_PERIOD_CONFIGS)):
        fallback = DEFAULT_FACILITY_PERIOD_CONFIGS[idx]
        current = src[idx] if idx < len(src) and isinstance(src[idx], dict) else {}
        normalized.append({
            "enabled": bool(current.get("enabled", fallback["enabled"])),
            "base": _safe_float(current.get("base", fallback["base"]), fallback["base"]),
            "scale": _safe_float(current.get("scale", fallback["scale"]), fallback["scale"]),
            "ratios": _normalize_list(current.get("ratios", fallback["ratios"]), fallback["ratios"], length=5),
        })
    _maybe_warn_normalized("facility_period_configs", value, normalized)
    return normalized


class TaskDetail:
    cure_asap_conditions: str
    scenario: ScenarioType
    expect_attribute: list[int]
    follow_support_card_name: str
    follow_support_card_level: int
    extra_race_list: list[int]
    learn_skill_list: list[list[str]]
    learn_skill_blacklist: list[str]
    tactic_list: list[int]
    tactic_actions: list
    clock_use_limit: int
    learn_skill_threshold: int
    learn_skill_only_user_provided: bool
    allow_recover_tp: bool
    cultivate_progress_info: dict
    extra_weight: list
    spirit_explosion: list
    manual_purchase_at_end: bool
    override_insufficient_fans_forced_races: bool
    use_last_parents: bool
    motivation_threshold_year1: int
    motivation_threshold_year2: int
    motivation_threshold_year3: int
    prioritize_recreation: bool
    pal_name: str
    pal_thresholds: list
    pal_friendship_score: list[float]
    pal_card_multiplier: float
    score_value: list
    compensate_failure: bool
    max_failure_rate: int
    base_score: list
    event_weights: dict
    scenario_config: ScenarioConfig
    do_tt_next: bool
    stat_value_multiplier: list
    wit_special_multiplier: list
    skip_double_circle_unless_high_hint: bool
    hint_boost_characters: list[str]
    hint_boost_multiplier: int
    friendship_score_groups: list
    character_score_configs: dict
    pal_card_store: dict
    group_card_enabled: bool
    group_card_name: str
    group_card_percentile: int
    facility_ratios: list[float]
    facility_period_configs: list[dict]


class EndTaskReason(Enum):
    TP_NOT_ENOUGH = "训练值不足"
    SESSION_ERROR = "Session Error"
    UNKNOWN_OPTION_BOX = "Unknown Option Box"



class UmamusumeTask(Task):
    detail: TaskDetail

    def end_task(self, status, reason) -> None:
        super().end_task(status, reason)

    def start_task(self) -> None:
        if self.task_execute_mode == TaskExecuteMode.TASK_EXECUTE_MODE_FULL_AUTO:
            self.detail.do_tt_next = False
        super().start_task()


class UmamusumeTaskType(Enum):
    UMAMUSUME_TASK_TYPE_UNKNOWN = 0
    UMAMUSUME_TASK_TYPE_CULTIVATE = 1


def build_task(task_execute_mode: TaskExecuteMode, task_type: int,
               task_desc: str, cron_job_config: dict, attachment_data: dict) -> UmamusumeTask:
    td = TaskDetail()
    ut = UmamusumeTask(task_execute_mode=task_execute_mode,
                       task_type=UmamusumeTaskType(task_type), task_desc=task_desc, app_name="umamusume")
    ut.cron_job_config = cron_job_config
    td.scenario = ScenarioType(attachment_data['scenario'])
    td.expect_attribute = _normalize_list(
        attachment_data.get('expect_attribute'),
        [0, 0, 0, 0, 0],
        length=5,
        cast=int,
        minimum=0,
    )
    _maybe_warn_normalized("expect_attribute", attachment_data.get('expect_attribute'), td.expect_attribute)
    td.follow_support_card_level = _safe_int(attachment_data.get('follow_support_card_level'), 50, minimum=0)
    td.follow_support_card_name = attachment_data['follow_support_card_name']
    td.extra_race_list = [int(x) for x in attachment_data.get('extra_race_list', []) if isinstance(x, (int, float, str)) and str(x).strip()]
    td.learn_skill_list = attachment_data.get('learn_skill_list', [])
    td.learn_skill_blacklist = attachment_data.get('learn_skill_blacklist', [])
    td.tactic_list = attachment_data.get('tactic_list', [])
    td.tactic_actions = attachment_data.get('tactic_actions', [])
    td.clock_use_limit = _safe_int(attachment_data.get('clock_use_limit'), 0, minimum=0)
    td.learn_skill_threshold = _safe_int(attachment_data.get('learn_skill_threshold'), 0, minimum=0)
    td.learn_skill_only_user_provided = bool(attachment_data.get('learn_skill_only_user_provided', False))
    td.allow_recover_tp = bool(attachment_data.get('allow_recover_tp', False))
    td.extra_weight = _normalize_matrix(
        attachment_data.get('extra_weight'),
        [[0, 0, 0, 0, 0] for _ in range(4)],
        row_length=5,
        minimum=-1.0,
        maximum=1.0,
    )
    _maybe_warn_normalized("extra_weight", attachment_data.get('extra_weight'), td.extra_weight)
    td.spirit_explosion = _normalize_spirit_explosion(attachment_data.get('spirit_explosion', list(DEFAULT_SPIRIT_EXPLOSION)))
    td.compensate_failure = bool(attachment_data.get('compensate_failure', True))
    td.max_failure_rate = _safe_int(
        attachment_data.get('max_failure_rate', DEFAULT_MAX_FAILURE_RATE),
        DEFAULT_MAX_FAILURE_RATE,
        minimum=0,
        maximum=100,
    )
    td.manual_purchase_at_end = attachment_data['manual_purchase_at_end']
    td.override_insufficient_fans_forced_races = bool(attachment_data.get('override_insufficient_fans_forced_races', False))
    td.use_last_parents = bool(attachment_data.get('use_last_parents', False))
    td.cure_asap_conditions = attachment_data.get("cure_asap_conditions", "")
    td.rest_threshold = _safe_int(
        attachment_data.get('rest_threshold', DEFAULT_REST_THRESHOLD),
        DEFAULT_REST_THRESHOLD,
        minimum=0,
    )
    td.summer_score_threshold = _safe_float(
        attachment_data.get('summer_score_threshold', DEFAULT_SUMMER_SCORE_THRESHOLD),
        DEFAULT_SUMMER_SCORE_THRESHOLD,
        minimum=0.0,
    )
    td.wit_race_search_threshold = _safe_float(
        attachment_data.get('wit_race_search_threshold', 0.15),
        0.15,
        minimum=0.0,
    )
    td.facility_period_configs = _normalize_facility_period_configs(attachment_data.get('facility_period_configs', list(DEFAULT_FACILITY_PERIOD_CONFIGS)))
    
    td.motivation_threshold_year1 = _safe_int(attachment_data.get('motivation_threshold_year1', 3), 3, minimum=1, maximum=5)
    td.motivation_threshold_year2 = _safe_int(attachment_data.get('motivation_threshold_year2', 4), 4, minimum=1, maximum=5)
    td.motivation_threshold_year3 = _safe_int(attachment_data.get('motivation_threshold_year3', 4), 4, minimum=1, maximum=5)
    td.pal_name = attachment_data.get('pal_name', "")
    td.pal_thresholds = attachment_data.get('pal_thresholds', [])
    if not isinstance(td.pal_thresholds, list) or not td.pal_thresholds:
        td.pal_thresholds = []
    td.prioritize_recreation = bool(attachment_data.get('prioritize_recreation', False)) and bool(td.pal_thresholds)

    td.pal_friendship_score = _normalize_list(
        attachment_data.get('pal_friendship_score'),
        DEFAULT_PAL_FRIENDSHIP_SCORES,
        length=3,
        minimum=0.0,
    )
    td.pal_card_multiplier = _safe_float(
        attachment_data.get('pal_card_multiplier', DEFAULT_PAL_CARD_MULTIPLIER),
        DEFAULT_PAL_CARD_MULTIPLIER,
        minimum=0.0,
    )
    td.pal_card_store = attachment_data.get('pal_card_store', {})
    td.group_card_enabled = False
    td.group_card_name = ""
    td.group_card_percentile = 26
    if isinstance(td.pal_card_store, dict):
        for _k, _v in td.pal_card_store.items():
            if not isinstance(_v, (dict, list)):
                continue
            if isinstance(_v, dict):
                _pal_type = _v.get('type', 'group' if _v.get('group') else 'friend')
            else:
                _pal_type = 'friend'
            if _pal_type == 'group' and not td.group_card_enabled:
                _enabled = _v.get('enabled', False) if isinstance(_v, dict) else False
                if _enabled:
                    td.group_card_enabled = True
                    td.group_card_name = _v.get('group', _k) if isinstance(_v, dict) else _k
                    td.group_card_percentile = _safe_int(_v.get('percentile', 26), 26, minimum=0, maximum=100) if isinstance(_v, dict) else 26
    if td.prioritize_recreation and td.pal_thresholds:
        td.group_card_enabled = False
        td.group_card_name = ""
    td.npc_score_value = _normalize_matrix(
        attachment_data.get('npc_score_value'),
        [
            [0.05, 0.05, 0.05],
            [0.05, 0.05, 0.05],
            [0.05, 0.05, 0.05],
            [0.03, 0.05, 0.05],
            [0, 0, 0.05]
        ],
        row_length=3,
        minimum=0.0,
    )

    td.score_value = _normalize_matrix(
        attachment_data.get('score_value'),
        DEFAULT_SCORE_VALUE,
        minimum=-1.0,
    )
    
    td.base_score = _normalize_list(
        attachment_data.get('base_score'),
        DEFAULT_BASE_SCORES,
        length=5,
    )
    
    td.cultivate_result = {}
    sew = attachment_data.get('skillEventWeight', None)
    rsewl = attachment_data.get('resetSkillEventWeightList', None)
    if sew is None and attachment_data.get('ura_config') is not None:
        sew = attachment_data['ura_config'].get('skillEventWeight', None)
    if rsewl is None and attachment_data.get('ura_config') is not None:
        rsewl = attachment_data['ura_config'].get('resetSkillEventWeightList', None)
    td.scenario_config = ScenarioConfig(
        aoharu_config = None if (attachment_data.get('aoharu_config') is None) else AoharuConfig(attachment_data['aoharu_config']),
        mant_config = None if (attachment_data.get('mant_config') is None) else MantConfig(attachment_data['mant_config']),
        skill_event_weight=sew,
        reset_skill_event_weight_list=rsewl)
    try:
        eo = attachment_data.get('event_overrides', attachment_data.get('event_choices', {}))
        td.event_overrides = eo if isinstance(eo, dict) else {}
    except Exception:
        td.event_overrides = {}
    
    try:
        ew = attachment_data.get('event_weights', None)
        td.event_weights = ew if isinstance(ew, dict) else None
    except Exception:
        td.event_weights = None

    td.do_tt_next = bool(attachment_data.get('do_tt_next', False))
    td.stat_value_multiplier = _normalize_list(
        attachment_data.get('stat_value_multiplier'),
        DEFAULT_STAT_VALUE_MULTIPLIER,
        length=6,
        minimum=0.0,
    )
    td.wit_special_multiplier = _normalize_list(
        attachment_data.get('wit_special_multiplier'),
        DEFAULT_WIT_SPECIAL_MULTIPLIER,
        length=2,
        minimum=0.0,
    )
    td.skip_double_circle_unless_high_hint = bool(attachment_data.get('skip_double_circle_unless_high_hint', False))
    td.hint_boost_characters = attachment_data.get('hint_boost_characters', [])
    td.hint_boost_multiplier = _safe_int(attachment_data.get('hint_boost_multiplier', 100), 100, minimum=0)
    td.friendship_score_groups = attachment_data.get('friendship_score_groups', [])
    td.character_score_configs = attachment_data.get('character_score_configs', {})
    td.facility_ratios = _normalize_list(
        attachment_data.get('facility_ratios'),
        [1.0] * 5,
        length=5,
        minimum=0.0,
    )
    
    ut.detail = td
    return ut
