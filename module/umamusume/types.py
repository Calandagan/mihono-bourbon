from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from module.umamusume.define import *
import bot.base.log as logger

if TYPE_CHECKING:
    from module.umamusume.scenario import base_scenario

log = logger.get_logger(__name__)

class SupportCardInfo:
    name: str
    card_type: SupportCardType
    favor: SupportCardFavorLevel
    has_event: bool
    can_incr_special_training: bool
    spirit_explosion: bool

    def __init__(self,
                name: str = "support_card",
                card_type: SupportCardType = SupportCardType.SUPPORT_CARD_TYPE_UNKNOWN,
                favor: SupportCardFavorLevel = SupportCardFavorLevel.SUPPORT_CARD_FAVOR_LEVEL_UNKNOWN,
                has_event: bool = False,
                can_incr_special_training: bool = False,
                spirit_explosion: bool = False,
                center: tuple[int, int] | None = None):
        self.name = name
        self.card_type = card_type
        self.favor = favor
        self.has_event = has_event
        self.can_incr_special_training = can_incr_special_training
        self.spirit_explosion = spirit_explosion
        self.center = center


class TrainingInfo:
    support_card_info_list: list[SupportCardInfo]
    speed_incr: int
    stamina_incr: int
    power_incr: int
    will_incr: int
    intelligence_incr: int
    skill_point_incr: int
    failure_rate: int
    relevant_count: int

    def __init__(self):
        self.speed_incr = 0
        self.stamina_incr = 0
        self.power_incr = 0
        self.will_incr = 0
        self.intelligence_incr = 0
        self.skill_point_incr = 0
        self.failure_rate = -1
        self.support_card_info_list = []
        self.relevant_count = 0



class UmaAttribute:
    speed: int
    stamina: int
    power: int
    will: int
    intelligence: int
    skill_point: int

    def __init__(self):
        self.speed = 0
        self.stamina = 0
        self.power = 0
        self.will = 0
        self.intelligence = 0
        self.skill_point = 0


class TurnOperation:
    turn_operation_type: TurnOperationType
    turn_operation_type_replace: TurnOperationType
    training_type: TrainingType
    race_id: int
    source: str

    def __init__(self):
        self.turn_operation_type = TurnOperationType.TURN_OPERATION_TYPE_UNKNOWN
        self.turn_operation_type_replace = TurnOperationType.TURN_OPERATION_TYPE_UNKNOWN
        self.training_type = TrainingType.TRAINING_TYPE_UNKNOWN
        self.race_id = 0
        self.source = ""

    def log_turn_operation(self):
        log.info("Current turn operation: %s", self.turn_operation_type.name)
        log.info("Current turn alternative operation: %s", self.turn_operation_type_replace.name)
        if self.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_TRAINING:
            log.info("Training type: %s", self.training_type.name)


class TurnInfo:
    date: int

    parse_train_info_finish: bool
    training_info_list: list[TrainingInfo]
    parse_main_menu_finish: bool
    uma_attribute: UmaAttribute
    remain_stamina: int
    motivation_level: MotivationLevel
    medic_room_available: bool
    race_available: bool

    turn_operation: TurnOperation | None
    turn_info_logged: bool
    turn_learn_skill_done: bool

    # Youth Cup
    aoharu_race_index: int

    def __init__(self):
        self.date = -1
        self.parse_train_info_finish = False
        self.training_info_list = [TrainingInfo(), TrainingInfo(), TrainingInfo(), TrainingInfo(), TrainingInfo()]
        self.parse_main_menu_finish = False
        self.uma_attribute = UmaAttribute()
        self.remain_stamina = -1
        self.motivation_level = MotivationLevel.MOTIVATION_LEVEL_UNKNOWN
        self.medic_room_available = False
        self.race_available = False
        self.rest_available = False
        self.train_available = False
        self.skill_available = False
        self.trip_available = False
        self.turn_operation = None
        self.turn_plan = None
        self.pending_training_scan = False
        self.turn_decision_trace = []
        self.item_use_options = []
        self.item_use_selected = []
        self.item_use_result = {}
        self.shop_buy_options = []
        self.shop_buy_selected = []
        self.shop_buy_result = {}
        self.race_candidates = []
        self.race_rejections = []
        self.turn_info_logged = False
        self.turn_learn_skill_done = False
        self.aoharu_race_index = 0

    def append_trace(self, kind: str, **payload):
        row = {"kind": kind}
        row.update(payload)
        self.turn_decision_trace.append(row)
        if len(self.turn_decision_trace) > 100:
            self.turn_decision_trace = self.turn_decision_trace[-100:]
        return row

    def set_item_trace(self, *, options=None, selected=None, result=None):
        if options is not None:
            self.item_use_options = list(options)
        if selected is not None:
            self.item_use_selected = list(selected)
        if result is not None:
            self.item_use_result = dict(result)

    def set_shop_trace(self, *, options=None, selected=None, result=None):
        if options is not None:
            self.shop_buy_options = list(options)
        if selected is not None:
            self.shop_buy_selected = list(selected)
        if result is not None:
            self.shop_buy_result = dict(result)

    def set_race_trace(self, *, candidates=None, rejections=None):
        if candidates is not None:
            self.race_candidates = list(candidates)
        if rejections is not None:
            self.race_rejections = list(rejections)

    def log_turn_info(self, scenario_type: ScenarioType):
        log.info("Current turn time " + str(self.date))
        log.info(
            "Current attribute values Speed: %s, Stamina: %s, Power: %s, Guts: %s, Wit: %s, Skill Points: %s",
            self.uma_attribute.speed,
            self.uma_attribute.stamina,
            self.uma_attribute.power,
            self.uma_attribute.will,
            self.uma_attribute.intelligence,
            self.uma_attribute.skill_point,
        )


class CultivateContextDetail:
    turn_info: TurnInfo | None
    turn_info_history: list[TurnInfo]
    scenario : "base_scenario.BaseScenario"
    expect_attribute: list[int] | None
    follow_support_card_name: str
    follow_support_card_level: int
    extra_race_list: list[int]
    learn_skill_list: list[list[str]]
    learn_skill_blacklist: list[str]
    learn_skill_done: bool
    learn_skill_selected: bool
    cultivate_finish: bool
    tactic_list: list[int]
    tactic_actions: list
    debut_race_win: bool
    clock_use_limit: int
    clock_used: int
    learn_skill_threshold: int
    learn_skill_only_user_provided: bool
    learn_skill_before_race: bool
    allow_recover_tp: bool
    parse_factor_done: bool
    extra_weight: list
    spirit_explosion: list
    motivation_threshold_year1: int
    motivation_threshold_year2: int
    motivation_threshold_year3: int
    prioritize_recreation: bool
    pal_name: str
    pal_thresholds: list
    pal_friendship_score: list[float]
    pal_card_multiplier: float
    aggressive_cap_skip: bool
    wit_special_multiplier: list
    group_card_enabled: bool
    group_card_name: str
    group_card_percentile: int
    group_card_available_dates: list
    group_card_last_date: int

    def __init__(self):
        self.expect_attribute = None
        self.turn_info = TurnInfo()
        self.turn_info_history = []
        self.extra_race_list = []
        self.learn_skill_list = []
        self.learn_skill_blacklist = []
        self.learn_skill_done = False
        self.learn_skill_selected = False
        self.cultivate_finish = False
        self.tactic_list = []
        self.debut_race_win = False
        self.clock_use_limit = 0
        self.clock_used = 0
        self.allow_recover_tp = False
        self.parse_factor_done = False
        self.extra_weight = []
        self.spirit_explosion = [0.16, 0.16, 0.16, 0.06, 0.11]
        self.motivation_threshold_year1 = 3  # Default values
        self.motivation_threshold_year2 = 4
        self.motivation_threshold_year3 = 4
        self.prioritize_recreation = False
        self.pal_name = ""
        self.pal_thresholds = []
        self.pal_friendship_score = [0.08, 0.057, 0.018]
        self.pal_card_multiplier = 0.1
        self.group_card_enabled = False
        self.group_card_name = ""
        self.group_card_percentile = 26
        self.group_card_available_dates = []
        self.group_card_last_date = -1

    def reset_skill_learn(self):
        self.learn_skill_done = False
        self.learn_skill_selected = False


@dataclass
class TurnPlan:
    primary_action: str = "training"
    training_type: TrainingType = TrainingType.TRAINING_TYPE_UNKNOWN
    race_id: int = 0
    source: str = ""
    pre_actions: list[str] = field(default_factory=list)
    requires_training_scan: bool = False
    requires_replan_after_pre_action: bool = False
    reason: str = ""
    debug: dict = field(default_factory=dict)

    def to_turn_operation(self) -> TurnOperation:
        operation = TurnOperation()
        mapping = {
            "training": TurnOperationType.TURN_OPERATION_TYPE_TRAINING,
            "rest": TurnOperationType.TURN_OPERATION_TYPE_REST,
            "medic": TurnOperationType.TURN_OPERATION_TYPE_MEDIC,
            "trip": TurnOperationType.TURN_OPERATION_TYPE_TRIP,
            "race": TurnOperationType.TURN_OPERATION_TYPE_RACE,
        }
        operation.turn_operation_type = mapping.get(
            self.primary_action,
            TurnOperationType.TURN_OPERATION_TYPE_UNKNOWN,
        )
        if operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_TRAINING:
            operation.training_type = self.training_type
        if operation.turn_operation_type == TurnOperationType.TURN_OPERATION_TYPE_RACE:
            operation.race_id = self.race_id
            operation.source = self.source or ""
        return operation

    def log(self):
        action = self.primary_action or "unknown"
        pre = ",".join(self.pre_actions) if self.pre_actions else "-"
        msg = f"Turn plan: action={action} pre_actions={pre}"
        if self.training_type != TrainingType.TRAINING_TYPE_UNKNOWN:
            msg += f" training={self.training_type.name}"
        if self.race_id:
            msg += f" race_id={self.race_id}"
        if self.source:
            msg += f" source={self.source}"
        if self.requires_training_scan:
            msg += " requires_training_scan=True"
        if self.requires_replan_after_pre_action:
            msg += " requires_replan_after_pre_action=True"
        if self.reason:
            msg += f" reason={self.reason}"
        log.info(msg)
