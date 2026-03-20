import bot.base.log as logger
from module.umamusume.asset.ui import MANT_CLIMAX_RESULT

log = logger.get_logger(__name__)


def script_mant_climax_result(ctx):
    ctx.ctrl.click(360, 1110, "MANT Climax Next")


def get_mant_ui_handlers():
    return {
        MANT_CLIMAX_RESULT: script_mant_climax_result,
    }
