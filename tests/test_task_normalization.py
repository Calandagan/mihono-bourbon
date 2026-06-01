import unittest
import logging
import sys
import types

if "colorlog" not in sys.modules:
    class _ColoredFormatter(logging.Formatter):
        def __init__(self, *args, **kwargs):
            kwargs.pop("log_colors", None)
            super().__init__(*args, **kwargs)

        def format(self, record):
            if not hasattr(record, "log_color"):
                record.log_color = ""
            return super().format(record)

    sys.modules["colorlog"] = types.SimpleNamespace(ColoredFormatter=_ColoredFormatter)

from bot.base.task import TaskExecuteMode
from module.umamusume.task import build_task


class TaskNormalizationTests(unittest.TestCase):
    def test_build_task_normalizes_numeric_and_matrix_fields(self):
        task = build_task(
            TaskExecuteMode.TASK_EXECUTE_MODE_ONE_TIME,
            1,
            "cultivate",
            {},
            {
                "scenario": 3,
                "expect_attribute": ["100", "", None, "250.8", "0"],
                "follow_support_card_name": "",
                "follow_support_card_level": "45",
                "extra_race_list": ["101", 202, ""],
                "learn_skill_list": [],
                "learn_skill_blacklist": [],
                "tactic_list": [4, 4, 4],
                "tactic_actions": [],
                "clock_use_limit": "3",
                "manual_purchase_at_end": False,
                "skip_double_circle_unless_high_hint": False,
                "hint_boost_characters": [],
                "hint_boost_multiplier": "150",
                "character_score_configs": {},
                "learn_skill_threshold": "120",
                "allow_recover_tp": True,
                "rest_threshold": "52",
                "compensate_failure": True,
                "max_failure_rate": "180",
                "summer_score_threshold": "0.42",
                "wit_race_search_threshold": "0.2",
                "use_last_parents": False,
                "learn_skill_only_user_provided": False,
                "extra_weight": [["1", "-2", "", None, "0.5"]],
                "base_score": ["0", "0.2", "", None, "0.7"],
                "spirit_explosion": [["0.1", "0.2", "", None, "0.3"]],
                "score_value": [["0.1", "0.2", "0.3", "0.4"]],
                "stat_value_multiplier": ["0.01", "", None, "0.03"],
                "wit_special_multiplier": ["1.9", ""],
                "motivation_threshold_year1": "0",
                "motivation_threshold_year2": "6",
                "motivation_threshold_year3": "4",
                "prioritize_recreation": False,
                "facility_ratios": ["1", "", None, "1.5"],
                "facility_period_configs": [{"enabled": 1, "base": "0.4", "scale": "", "ratios": ["1", "", None, "2", "3"]}],
            },
        )

        self.assertEqual(task.detail.expect_attribute, [100, 0, 0, 250, 0])
        self.assertEqual(task.detail.extra_race_list, [101, 202])
        self.assertEqual(task.detail.max_failure_rate, 100)
        self.assertEqual(task.detail.rest_threshold, 52)
        self.assertEqual(task.detail.extra_weight[0], [1.0, -1.0, 0.0, 0.0, 0.5])
        self.assertEqual(len(task.detail.extra_weight), 4)
        self.assertEqual(task.detail.base_score, [0.0, 0.2, 0.0, 0.0, 0.7])
        self.assertEqual(task.detail.stat_value_multiplier, [0.01, 0.01, 0.01, 0.03, 0.01, 0.005])
        self.assertEqual(task.detail.wit_special_multiplier, [1.9, 1.37])
        self.assertEqual(task.detail.motivation_threshold_year1, 1)
        self.assertEqual(task.detail.motivation_threshold_year2, 5)
        self.assertEqual(task.detail.facility_ratios, [1.0, 1.0, 1.0, 1.5, 1.0])
        self.assertEqual(len(task.detail.facility_period_configs), 6)
        self.assertEqual(task.detail.facility_period_configs[0]["ratios"], [1.0, 1.0, 1.0, 2.0, 3.0])


if __name__ == "__main__":
    unittest.main()
