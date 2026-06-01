import time
import random
import threading
import ctypes
import ctypes.wintypes as wintypes
import cv2
import numpy as np
from typing import Optional, Tuple

import win32gui
import win32con
import win32api
import win32ui

from bot.conn.ctrl import AndroidController
from bot.base.point import ClickPoint, ClickPointType
from bot.recog.image_matcher import image_match
import bot.base.log as logger

log = logger.get_logger(__name__)

LOGICAL_W = 720
LOGICAL_H = 1280


class Win32Controller(AndroidController):
    def __init__(self, window_title: str = "Umamusume"):
        self.window_title = window_title
        self.hwnd: Optional[int] = None
        self.lock = threading.Lock()
        self.input_lock = threading.Lock()
        self.last_img: Optional[np.ndarray] = None
        self.last_ts: float = 0.0
        self.max_age: float = 0.120
        self.last_click_time: float = 0.0
        self.trigger_decision_reset: bool = False

        self.recent_click_buckets = []
        self.fallback_block_until: float = 0.0
        self.repetitive_click_name = None
        self.repetitive_click_count: int = 0
        self.repetitive_other_clicks: int = 0
        self.last_recovery_time: float = 0
        self.recovery_grace_until: float = 0.0

    # ------------------------------------------------------------------
    # Window management
    # ------------------------------------------------------------------

    def _find_hwnd(self) -> Optional[int]:
        found = []
        title_lower = self.window_title.lower()

        def cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                t = win32gui.GetWindowText(hwnd).lower()
                if title_lower in t:
                    found.append(hwnd)

        win32gui.EnumWindows(cb, None)
        return found[0] if found else None

    def _client_size(self) -> Tuple[int, int]:
        if not self.hwnd:
            return LOGICAL_W, LOGICAL_H
        r = win32gui.GetClientRect(self.hwnd)
        return r[2], r[3]

    def _scale_to_window(self, x: int, y: int) -> Tuple[int, int]:
        """Map logical 720x1280 coordinates to the actual window client size."""
        cw, ch = self._client_size()
        if cw == LOGICAL_W and ch == LOGICAL_H:
            return x, y
        return int(x * cw / LOGICAL_W), int(y * ch / LOGICAL_H)

    def init_env(self) -> None:
        self.hwnd = self._find_hwnd()
        if not self.hwnd:
            raise RuntimeError(f"Window '{self.window_title}' not found. Is the game open?")
        cw, ch = self._client_size()
        log.info(f"Win32Controller attached to HWND={self.hwnd:#010x} '{self.window_title}' ({cw}x{ch})")

    def reinit_connection(self) -> None:
        self.hwnd = self._find_hwnd()
        self.last_img = None

    def destroy(self) -> None:
        self.last_img = None
        self.hwnd = None

    # ------------------------------------------------------------------
    # Screen capture (PrintWindow — works without focus)
    # ------------------------------------------------------------------

    def capture(self) -> Optional[np.ndarray]:
        if not self.hwnd:
            return None
        try:
            left, top, right, bottom = win32gui.GetWindowRect(self.hwnd)
            w = right - left
            h = bottom - top
            if w <= 0 or h <= 0:
                return None

            hwnd_dc = win32gui.GetWindowDC(self.hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()
            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(mfc_dc, w, h)
            save_dc.SelectObject(bmp)

            PW_RENDERFULLCONTENT = 2
            ok = ctypes.windll.user32.PrintWindow(self.hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)

            if not ok:
                save_dc.DeleteDC()
                mfc_dc.DeleteDC()
                win32gui.ReleaseDC(self.hwnd, hwnd_dc)
                win32gui.DeleteObject(bmp.GetHandle())
                return None

            bmp_info = bmp.GetInfo()
            bmp_str = bmp.GetBitmapBits(True)

            img = np.frombuffer(bmp_str, dtype=np.uint8).reshape(
                (bmp_info["bmHeight"], bmp_info["bmWidth"], 4)
            )
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(self.hwnd, hwnd_dc)
            win32gui.DeleteObject(bmp.GetHandle())

            # Crop to client area (removes title bar / borders)
            cr = win32gui.GetClientRect(self.hwnd)
            cl, ct, cw, ch = win32gui.ClientToScreen(self.hwnd, (0, 0)) + (cr[2], cr[3])
            ox = cl - left
            oy = ct - top
            img = img[oy:oy + ch, ox:ox + cw]

            # Scale to logical 720x1280 so all downstream recognition works unchanged
            if img.shape[1] != LOGICAL_W or img.shape[0] != LOGICAL_H:
                img = cv2.resize(img, (LOGICAL_W, LOGICAL_H), interpolation=cv2.INTER_AREA)

            return img
        except Exception as e:
            log.warning(f"Win32 capture failed: {e}")
            return None

    def get_screen(self, to_gray=False, force=False) -> Optional[np.ndarray]:
        for attempt in range(3):
            img = None
            with self.lock:
                now = time.time()
                if not force and self.last_img is not None and (now - self.last_ts) < self.max_age:
                    img = self.last_img
                else:
                    img = self.capture()
                    if img is not None:
                        self.last_img = img
                        self.last_ts = time.time()
            if img is not None:
                return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if to_gray else img
            if attempt < 2:
                time.sleep(0.1)
        return None

    # ------------------------------------------------------------------
    # Input helpers (mirrored from AdbController)
    # ------------------------------------------------------------------

    def in_fallback_block(self, name) -> bool:
        if isinstance(name, str) and name == "Default fallback click":
            if time.time() < self.fallback_block_until:
                return True
        return False

    def update_click_buckets(self, x, y) -> None:
        bucket = (int(x / 25), int(y / 25))
        if bucket not in self.recent_click_buckets:
            self.recent_click_buckets.append(bucket)
            if len(self.recent_click_buckets) > 2:
                self.recent_click_buckets.pop(0)
            self.fallback_block_until = time.time() + 2.0

    def build_click_key(self, x, y, name) -> str:
        if isinstance(name, str) and name.strip():
            return name.strip()
        return f"{int(x / 50)}:{int(y / 50)}"

    def update_repetitive_click(self, click_key) -> bool:
        try:
            from bot.base.runtime_state import update_repetitive, get_repetitive_threshold
            repetitive_threshold = int(get_repetitive_threshold())
        except Exception:
            repetitive_threshold = 11
            update_repetitive = None

        if isinstance(click_key, str):
            click_key = click_key.strip()

        if self.repetitive_click_name is None:
            self.repetitive_click_name = click_key
            self.repetitive_click_count = 1
            self.repetitive_other_clicks = 0
            if update_repetitive:
                update_repetitive(1, 0)
            return False

        current = self.repetitive_click_name.strip() if isinstance(self.repetitive_click_name, str) else self.repetitive_click_name
        is_same = click_key == current or (
            isinstance(click_key, str) and isinstance(current, str) and click_key.lower() == current.lower()
        )
        if is_same:
            self.repetitive_click_count += 1
        else:
            self.repetitive_other_clicks += 1
            if self.repetitive_other_clicks >= 2:
                self.repetitive_click_name = click_key
                self.repetitive_click_count = 1
                self.repetitive_other_clicks = 0

        if update_repetitive:
            update_repetitive(self.repetitive_click_count, self.repetitive_other_clicks)

        if time.time() < self.recovery_grace_until:
            self.repetitive_click_name = None
            self.repetitive_click_count = 0
            self.repetitive_other_clicks = 0
            return False

        if self.repetitive_click_name == click_key and self.repetitive_click_count >= repetitive_threshold:
            try:
                self.recover_home_and_reopen()
            finally:
                self.repetitive_click_name = None
                self.repetitive_click_count = 0
                self.repetitive_other_clicks = 0
                if update_repetitive:
                    update_repetitive(0, 0)
            return True
        return False

    def safety_dont_click(self, x, y) -> bool:
        if 263 <= x <= 458 and 559 <= y <= 808:
            from module.umamusume.asset.template import UI_CULTIVATE_SUPPORT_CARD_SELECT
            screen_gray = self.get_screen(to_gray=True, force=True)
            match = image_match(screen_gray, UI_CULTIVATE_SUPPORT_CARD_SELECT)
            if getattr(match, "find_match", False):
                return True
        return False

    def wait_click_interval(self) -> None:
        elapsed = time.time() - self.last_click_time
        min_interval = random.uniform(0.06, 0.09)
        wait = max(0.0, min_interval - elapsed)
        if wait > 0:
            time.sleep(wait)

    # ------------------------------------------------------------------
    # PostMessage helpers
    # ------------------------------------------------------------------

    def _post_click_raw(self, cx: int, cy: int, hold_duration: int = 0) -> None:
        """Send WM_LBUTTONDOWN/UP to the window at client coords (cx, cy)."""
        if not self.hwnd:
            return
        lparam = win32api.MAKELONG(cx, cy)
        win32api.PostMessage(self.hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
        win32api.PostMessage(self.hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
        duration = hold_duration if hold_duration > 0 else int(random.uniform(60, 130))
        time.sleep(duration / 1000.0)
        win32api.PostMessage(self.hwnd, win32con.WM_LBUTTONUP, 0, lparam)

    def _post_scroll(self, cx: int, cy: int, delta: int) -> None:
        """Send WM_MOUSEWHEEL. delta > 0 = scroll up, < 0 = scroll down."""
        if not self.hwnd:
            return
        screen_x, screen_y = win32gui.ClientToScreen(self.hwnd, (cx, cy))
        wparam = win32api.MAKELONG(0, delta)
        lparam = win32api.MAKELONG(screen_x, screen_y)
        win32api.PostMessage(self.hwnd, win32con.WM_MOUSEWHEEL, wparam, lparam)

    # ------------------------------------------------------------------
    # Public controller interface
    # ------------------------------------------------------------------

    def click(self, x, y, name="", random_offset=True, hold_duration=0) -> None:
        with self.input_lock:
            try:
                from bot.base.runtime_state import get_state
                if get_state().get("input_blocked"):
                    return
            except Exception:
                pass

            if self.safety_dont_click(x, y):
                return
            if self.in_fallback_block(name):
                return
            self.update_click_buckets(x, y)

            click_key = self.build_click_key(x, y, name)
            if self.update_repetitive_click(click_key):
                return

            if random_offset:
                x += int(max(-8, min(8, random.gauss(0, 3))))
                y += int(max(-8, min(8, random.gauss(0, 3))))

            x, y = max(1, min(LOGICAL_W - 1, x)), max(1, min(LOGICAL_H - 1, y))
            if hold_duration > 0 and y < 66:
                hold_duration = 0

            self.wait_click_interval()

            cx, cy = self._scale_to_window(x, y)
            self._post_click_raw(cx, cy, hold_duration)
            self.last_click_time = time.time()

            try:
                from config import CONFIG
                time.sleep(CONFIG.bot.auto.adb.delay)
            except Exception:
                time.sleep(0.38)

    def swipe(self, x1, y1, x2, y2, duration=0.2, name="") -> None:
        with self.input_lock:
            try:
                from bot.base.runtime_state import get_state
                if get_state().get("input_blocked"):
                    return
            except Exception:
                pass

            x1 += int(max(-10, min(10, random.gauss(0, 4))))
            y1 += int(max(-10, min(10, random.gauss(0, 4))))
            x2 += int(max(-10, min(10, random.gauss(0, 4))))
            y2 += int(max(-10, min(10, random.gauss(0, 4))))

            if y1 < 120:
                self.click(x1, y1, name=name, random_offset=False)
                return

            cx1, cy1 = self._scale_to_window(
                max(1, min(LOGICAL_W - 1, x1)), max(1, min(LOGICAL_H - 1, y1))
            )
            cx2, cy2 = self._scale_to_window(
                max(1, min(LOGICAL_W - 1, x2)), max(1, min(LOGICAL_H - 1, y2))
            )

            # Detect vertical swipe → send as scroll wheel (more natural on PC)
            is_vertical = abs(y2 - y1) > abs(x2 - x1)
            if is_vertical:
                # WM_MOUSEWHEEL delta: WHEEL_DELTA=120 per notch
                scroll_delta = int(((y1 - y2) / LOGICAL_H) * 120 * 8)
                scroll_delta = max(-960, min(960, scroll_delta))
                self._post_scroll(cx1, cy1, scroll_delta)
            else:
                # Horizontal swipe via button down/move/up sequence
                steps = max(3, int(duration * 20))
                if not self.hwnd:
                    return
                win32api.PostMessage(self.hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON,
                                     win32api.MAKELONG(cx1, cy1))
                for i in range(1, steps + 1):
                    t = i / steps
                    ix = int(cx1 + (cx2 - cx1) * t)
                    iy = int(cy1 + (cy2 - cy1) * t)
                    win32api.PostMessage(self.hwnd, win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON,
                                         win32api.MAKELONG(ix, iy))
                    time.sleep(duration / steps)
                win32api.PostMessage(self.hwnd, win32con.WM_LBUTTONUP, 0,
                                     win32api.MAKELONG(cx2, cy2))

            try:
                from config import CONFIG
                time.sleep(CONFIG.bot.auto.adb.delay)
            except Exception:
                time.sleep(0.38)

    def swipe_and_hold(self, x1, y1, x2, y2, swipe_duration, hold_duration, name="") -> None:
        with self.input_lock:
            try:
                from bot.base.runtime_state import get_state
                if get_state().get("input_blocked"):
                    return
            except Exception:
                pass

            x1 += int(max(-10, min(10, random.gauss(0, 4))))
            y1 += int(max(-10, min(10, random.gauss(0, 4))))
            x2 += int(max(-10, min(10, random.gauss(0, 4))))
            y2 += int(max(-10, min(10, random.gauss(0, 4))))

            if y1 < 120:
                self.click(x1, y1, name=name, random_offset=False)
                return

            cx1, cy1 = self._scale_to_window(max(1, min(LOGICAL_W - 1, x1)), max(1, min(LOGICAL_H - 1, y1)))
            cx2, cy2 = self._scale_to_window(max(1, min(LOGICAL_W - 1, x2)), max(1, min(LOGICAL_H - 1, y2)))

            if not self.hwnd:
                return
            win32api.PostMessage(self.hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON,
                                 win32api.MAKELONG(cx1, cy1))
            steps = max(3, int(swipe_duration / 1000 * 20))
            dur_s = swipe_duration / 1000.0
            for i in range(1, steps + 1):
                t = i / steps
                ix = int(cx1 + (cx2 - cx1) * t)
                iy = int(cy1 + (cy2 - cy1) * t)
                win32api.PostMessage(self.hwnd, win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON,
                                     win32api.MAKELONG(ix, iy))
                time.sleep(dur_s / steps)
            time.sleep(hold_duration / 1000.0 * random.uniform(0.94, 1.06))
            win32api.PostMessage(self.hwnd, win32con.WM_LBUTTONUP, 0, win32api.MAKELONG(cx2, cy2))

            try:
                from config import CONFIG
                time.sleep(CONFIG.bot.auto.adb.delay)
            except Exception:
                time.sleep(0.38)

    def back(self) -> None:
        with self.input_lock:
            if not self.hwnd:
                return
            win32api.PostMessage(self.hwnd, win32con.WM_KEYDOWN, win32con.VK_ESCAPE, 0)
            time.sleep(0.05)
            win32api.PostMessage(self.hwnd, win32con.WM_KEYUP, win32con.VK_ESCAPE, 0)
            try:
                from config import CONFIG
                time.sleep(CONFIG.bot.auto.adb.delay)
            except Exception:
                time.sleep(0.38)

    def start_app(self, package, activity=None) -> None:
        # Steam game is already running; bring window to foreground if minimized
        if self.hwnd:
            if win32gui.IsIconic(self.hwnd):
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)

    def recover_home_and_reopen(self) -> None:
        if time.time() - self.last_recovery_time < 10:
            return
        self.last_recovery_time = time.time()
        self.recovery_grace_until = time.time() + 60
        # Press Escape a few times to dismiss dialogs, then do nothing else
        # (can't force-stop a Steam game the way ADB can restart an Android app)
        if self.hwnd:
            for _ in range(3):
                win32api.PostMessage(self.hwnd, win32con.WM_KEYDOWN, win32con.VK_ESCAPE, 0)
                time.sleep(0.4)
                win32api.PostMessage(self.hwnd, win32con.WM_KEYUP, win32con.VK_ESCAPE, 0)
        self.trigger_decision_reset = True

    def execute_adb_shell(self, cmd: str, sync: bool = True):
        log.debug(f"execute_adb_shell called on Win32Controller (no-op): {cmd}")
        return None

    def click_by_point(self, point: ClickPoint, random_offset=True, hold_duration=0) -> None:
        if point.target_type == ClickPointType.CLICK_POINT_TYPE_COORDINATE:
            self.click(point.coordinate.x, point.coordinate.y, name=point.desc,
                       random_offset=random_offset, hold_duration=hold_duration)
        elif point.target_type == ClickPointType.CLICK_POINT_TYPE_TEMPLATE:
            gray = self.get_screen(to_gray=True)
            res = image_match(gray, point.template)
            if res.find_match:
                self.click(res.center_point[0], res.center_point[1], name=point.desc,
                           random_offset=random_offset, hold_duration=hold_duration)
