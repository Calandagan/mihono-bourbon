import json
import os

import bot.base.log as logger

log = logger.get_logger(__name__)

PERSISTENCE_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'career_data.json')
PERSISTENCE_FILE = os.path.normpath(PERSISTENCE_FILE)


def save_career_data(ctx):
    try:
        date = getattr(ctx.cultivate_detail.turn_info, 'date', None)
        score_history = getattr(ctx.cultivate_detail, 'score_history', [])
        percentile_history = getattr(ctx.cultivate_detail, 'percentile_history', [])
        if not score_history:
            return
        data = {
            'last_date': date,
            'score_history': list(score_history),
            'percentile_history': list(percentile_history),
        }
        with open(PERSISTENCE_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        log.info(f"Failed to save career data: {e}")


def load_career_data(ctx):
    try:
        if not os.path.exists(PERSISTENCE_FILE):
            return False
        with open(PERSISTENCE_FILE, 'r') as f:
            data = json.load(f)
        saved_date = data.get('last_date')
        current_date = getattr(ctx.cultivate_detail.turn_info, 'date', None)
        if saved_date is None or current_date is None:
            return False
        if saved_date != current_date:
            return False
        score_history = data.get('score_history', [])
        percentile_history = data.get('percentile_history', [])
        if not score_history:
            return False
        ctx.cultivate_detail.score_history = list(score_history)
        ctx.cultivate_detail.percentile_history = list(percentile_history)
        log.info(f"Restored career data: {len(score_history)} scores, {len(percentile_history)} percentiles")
        return True
    except Exception as e:
        log.info(f"Failed to load career data: {e}")
        return False
