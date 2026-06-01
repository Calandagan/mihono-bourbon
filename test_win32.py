"""
Test script: Win32 background capture + PostMessage/SendMessage click on Umamusume Steam.

Requirements (install on Windows):
    pip install pywin32 pillow

Run on Windows with the game open (doesn't need to be in focus).
"""

import sys
import time
import ctypes
import ctypes.wintypes as wintypes

try:
    import win32gui
    import win32con
    import win32api
    import win32ui
    from PIL import Image
except ImportError:
    print("Missing deps. Run: pip install pywin32 pillow")
    sys.exit(1)


GAME_TITLES = [
    "umamusume",
    "ウマ娘",
    "pretty derby",
]


def find_umamusume_hwnd():
    found = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).lower()
        if any(kw.lower() in title for kw in GAME_TITLES):
            found.append((hwnd, win32gui.GetWindowText(hwnd)))

    win32gui.EnumWindows(callback, None)
    return found


def list_all_windows():
    """Helper: print all visible window titles so you can identify the right one."""
    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title.strip():
                print(f"  HWND={hwnd:#010x}  '{title}'")
    win32gui.EnumWindows(callback, None)


def capture_window_printwindow(hwnd, save_path="test_capture.png"):
    """
    Captures the window using PrintWindow with PW_RENDERFULLCONTENT.
    Works even when the window is behind other windows (not minimized).
    """
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w = right - left
    h = bottom - top

    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc_dc, w, h)
    save_dc.SelectObject(bmp)

    # PW_RENDERFULLCONTENT = 2 — captures DirectX/OpenGL surfaces
    PW_RENDERFULLCONTENT = 2
    result = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)

    bmp_info = bmp.GetInfo()
    bmp_str = bmp.GetBitmapBits(True)

    img = Image.frombuffer(
        "RGB",
        (bmp_info["bmWidth"], bmp_info["bmHeight"]),
        bmp_str, "raw", "BGRX", 0, 1
    )
    img.save(save_path)

    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)
    win32gui.DeleteObject(bmp.GetHandle())

    return result == 1, img.size


def post_click(hwnd, x, y, delay_ms=80):
    """PostMessage: async, puts message in queue."""
    lparam = win32api.MAKELONG(x, y)
    win32api.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    time.sleep(delay_ms / 1000.0)
    win32api.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)


def send_click(hwnd, x, y, delay_ms=80):
    """
    SendMessage: synchronous, forces the window procedure to process
    the message immediately before returning — bypasses the message queue.
    x, y are relative to the window client area.
    """
    lparam = win32api.MAKELONG(x, y)
    win32api.SendMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
    win32api.SendMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    time.sleep(delay_ms / 1000.0)
    win32api.SendMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)


def get_client_size(hwnd):
    rect = win32gui.GetClientRect(hwnd)
    return rect[2], rect[3]  # width, height


def main():
    print("=== Umamusume Win32 Background Test ===\n")

    print("Searching for Umamusume window...")
    found = find_umamusume_hwnd()

    if not found:
        print("Window not found. Listing all visible windows:\n")
        list_all_windows()
        print("\nAdd the correct title keyword to GAME_TITLES in this script.")
        return

    print(f"Found {len(found)} window(s):")
    for i, (hwnd, title) in enumerate(found):
        cw, ch = get_client_size(hwnd)
        print(f"  [{i}] HWND={hwnd:#010x}  '{title}'  client={cw}x{ch}")

    hwnd, title = found[0]
    print(f"\nUsing: '{title}'")

    # --- Test 1: Background capture ---
    print("\n[TEST 1] Capturing window with PrintWindow (background)...")
    ok, size = capture_window_printwindow(hwnd, "test_capture.png")
    if ok:
        print(f"  OK — saved test_capture.png  ({size[0]}x{size[1]})")
        print("  Open the file and verify the game frame was captured correctly.")
    else:
        print("  FAILED — PrintWindow returned 0.")
        print("  The game may use a protected/DRM surface. Try running as Administrator.")

    cw, ch = get_client_size(hwnd)
    cx, cy = cw // 2, ch // 2

    # --- Test 2: PostMessage (async queue) ---
    print(f"\n[TEST 2] PostMessage click to center ({cx}, {cy}) — game NOT focused...")
    print("  Click somewhere else on your screen so the game loses focus, then wait.")
    print("  Sending in 4 seconds...")
    time.sleep(4)
    post_click(hwnd, cx, cy)
    print("  PostMessage sent. Did the game react? (y/n)")
    post_result = input("  > ").strip().lower()

    # --- Test 3: SendMessage (synchronous, forces WndProc) ---
    print(f"\n[TEST 3] SendMessage click to center ({cx}, {cy}) — game NOT focused...")
    print("  Keep the game out of focus. Sending in 4 seconds...")
    time.sleep(4)
    send_click(hwnd, cx, cy)
    print("  SendMessage sent. Did the game react? (y/n)")
    send_result = input("  > ").strip().lower()

    print("\n=== Results ===")
    print(f"  Background capture (PrintWindow): {'OK' if ok else 'FAILED'}")
    print(f"  PostMessage background click:     {'WORKS' if post_result == 'y' else 'no response'}")
    print(f"  SendMessage background click:     {'WORKS' if send_result == 'y' else 'no response'}")


if __name__ == "__main__":
    main()
