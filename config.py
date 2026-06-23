import os
import shutil
import yaml
import bot.base.log as logger

log = logger.get_logger(__name__)

CONFIG_PATH = "config.yaml"
CONFIG_EXAMPLE_PATH = "config.example.yaml"

# Fallback used only if both config.yaml and config.example.yaml are missing.
DEFAULT_CONFIG = """bot:
  auto:
    adb:
      delay: 0.38
      device_name: emulator-5556
    cpu_alloc: 4
  gpu:
    device_id: 0
    enabled: auto
    memory_fraction: 0.3
version: 0.0.1
"""


class Config(dict):
    def __getattr__(self, key):
        value = self.get(key, None)
        if isinstance(value, dict):
            value = Config(value)
        return value


def _ensure_config_exists():
    # config.yaml is gitignored and personal. On a first-time install it won't
    # exist, so create it from the tracked template. Users who already have a
    # config.yaml keep theirs untouched (git pull never overwrites it).
    if os.path.exists(CONFIG_PATH):
        return
    try:
        if os.path.exists(CONFIG_EXAMPLE_PATH):
            shutil.copyfile(CONFIG_EXAMPLE_PATH, CONFIG_PATH)
            log.info("config.yaml not found - created from config.example.yaml")
        else:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                f.write(DEFAULT_CONFIG)
            log.info("config.yaml not found - created with default settings")
    except Exception as e:
        log.error(f"Failed to create config.yaml: {e}")


def load() -> Config:
    _ensure_config_exists()
    with open(CONFIG_PATH, 'r', encoding='utf-8') as config_file:
        config = config_file.read()
    return Config(yaml.load(config, yaml.FullLoader))


CONFIG = load()
