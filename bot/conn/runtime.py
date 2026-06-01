import json
import os
import threading
from dataclasses import asdict, dataclass
from typing import Optional

from bot.conn.ctrl import AndroidController

_RUNTIME_CONTROLLER_PATH = os.path.join("userdata", "runtime_controller.json")
_active_controller: Optional[AndroidController] = None
_active_lock = threading.Lock()


@dataclass(frozen=True)
class RuntimeControllerConfig:
    controller_type: str = "adb"
    device_name: str = ""
    window_title: str = "Umamusume"


def _normalize_controller_type(value: Optional[str]) -> str:
    if isinstance(value, str) and value.strip().lower() == "win32":
        return "win32"
    return "adb"


def read_runtime_controller_config() -> RuntimeControllerConfig:
    try:
        if os.path.isfile(_RUNTIME_CONTROLLER_PATH):
            with open(_RUNTIME_CONTROLLER_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return RuntimeControllerConfig(
                controller_type=_normalize_controller_type(data.get("controller_type")),
                device_name=str(data.get("device_name") or ""),
                window_title=str(data.get("window_title") or "Umamusume"),
            )
    except Exception:
        pass

    try:
        from config import CONFIG
        return RuntimeControllerConfig(
            controller_type="adb",
            device_name=str(getattr(getattr(CONFIG.bot.auto, "adb", None), "device_name", "") or ""),
            window_title="Umamusume",
        )
    except Exception:
        return RuntimeControllerConfig()


def write_runtime_controller_config(config: RuntimeControllerConfig) -> bool:
    try:
        os.makedirs(os.path.dirname(_RUNTIME_CONTROLLER_PATH), exist_ok=True)
        with open(_RUNTIME_CONTROLLER_PATH, "w", encoding="utf-8") as f:
            json.dump(asdict(config), f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def build_controller_from_runtime_config(
    config: Optional[RuntimeControllerConfig] = None,
) -> AndroidController:
    runtime_config = config or read_runtime_controller_config()
    if runtime_config.controller_type == "win32":
        from bot.conn.win32_controller import Win32Controller

        return Win32Controller(runtime_config.window_title)

    from bot.conn.adb_controller import AdbController

    return AdbController(runtime_config.device_name)


def set_active_controller(controller: Optional[AndroidController]) -> None:
    global _active_controller
    with _active_lock:
        _active_controller = controller


def get_active_controller() -> Optional[AndroidController]:
    with _active_lock:
        return _active_controller


def clear_active_controller(controller: Optional[AndroidController] = None) -> None:
    global _active_controller
    with _active_lock:
        if controller is None or _active_controller is controller:
            _active_controller = None
