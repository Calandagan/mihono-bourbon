import json
import os

import bot.base.log as logger

log = logger.get_logger(__name__)

PERSISTENCE_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'career_data.json')
PERSISTENCE_FILE = os.path.normpath(PERSISTENCE_FILE)

MAX_DATAPOINTS = 888


def rebuild_percentile_history(score_history):
    percentiles = []
    for i in range(1, len(score_history)):
        current = score_history[i]
        prev = score_history[:i]
        below_count = sum(1 for s in prev if s < current)
        percentile = below_count / len(prev) * 100
        percentiles.append(percentile)
    return percentiles


def save_career_data(ctx):
    try:
        score_history = getattr(ctx.cultivate_detail, 'score_history', [])
        if not score_history:
            return
        scores = list(score_history[-MAX_DATAPOINTS:])
        data = {
            'score_history': scores,
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
        score_history = data.get('score_history', [])
        if not score_history:
            return False
        scores = list(score_history[-MAX_DATAPOINTS:])
        ctx.cultivate_detail.score_history = scores
        ctx.cultivate_detail.percentile_history = rebuild_percentile_history(scores)
        log.info(f"Restored career data: {len(scores)} datapoints")
        return True
    except Exception as e:
        log.info(f"Failed to load career data: {e}")
        return False


def clear_career_data():
    try:
        if os.path.exists(PERSISTENCE_FILE):
            os.remove(PERSISTENCE_FILE)
            log.info("Career data cleared")
            return True
        return False
    except Exception as e:
        log.info(f"Failed to clear career data: {e}")
        return False
