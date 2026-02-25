"""
alara/integrations/windows_os.py

Controls Windows apps, windows, files, and system functions.
Uses pywinauto + win32api for deep OS access.

Week 1-2: Stub implementations that log what they would do.
Week 5-6: Replace stubs with real pywinauto/win32 calls.
"""

import subprocess
import os
from loguru import logger


class WindowsOSIntegration:
    """
    Handles all Windows OS-level actions:
    - App open/close/switch
    - Window management
    - File/folder operations
    - System controls (volume, lock, screenshot)
    """

    # Common app name → executable path mappings
    APP_MAP = {
        "chrome":           "chrome.exe",
        "google chrome":    "chrome.exe",
        "edge":             "msedge.exe",
        "firefox":          "firefox.exe",
        "vscode":           "code.exe",
        "vs code":          "code.exe",
        "visual studio code": "code.exe",
        "windows terminal": "wt.exe",
        "terminal":         "wt.exe",
        "powershell":       "powershell.exe",
        "notepad":          "notepad.exe",
        "explorer":         "explorer.exe",
        "file explorer":    "explorer.exe",
        "spotify":          "Spotify.exe",
        "slack":            "slack.exe",
    }

    def _resolve_app(self, app_name: str) -> str:
        """Normalize app name to executable."""
        return self.APP_MAP.get(app_name.lower(), f"{app_name}.exe")

    # ── App Control ───────────────────────────────────────────────────────────

    def open_app(self, params: dict):
        app_name = params.get("app_name", "")
        exe = self._resolve_app(app_name)
        logger.info(f"[STUB] Opening app: {app_name} → {exe}")
        # TODO Week 5: subprocess.Popen([exe])

    def close_app(self, params: dict):
        app_name = params.get("app_name", "")
        logger.info(f"[STUB] Closing app: {app_name}")
        # TODO Week 5:
        # import win32process, win32con
        # Find window by app name and send WM_CLOSE

    def switch_app(self, params: dict):
        app_name = params.get("app_name", "")
        logger.info(f"[STUB] Switching to app: {app_name}")
        # TODO Week 5:
        # from pywinauto import Desktop
        # windows = Desktop(backend="uia").windows()
        # Find matching window, call .set_focus()

    # ── Window Management ─────────────────────────────────────────────────────

    def minimize_window(self, params: dict):
        logger.info("[STUB] Minimizing active window")
        # TODO Week 5: win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)

    def maximize_window(self, params: dict):
        logger.info("[STUB] Maximizing active window")

    def close_window(self, params: dict):
        logger.info("[STUB] Closing active window")

    def take_screenshot(self, params: dict):
        logger.info("[STUB] Taking screenshot")
        # TODO Week 5:
        # import pyautogui
        # screenshot = pyautogui.screenshot()
        # screenshot.save(f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")

    # ── File System ───────────────────────────────────────────────────────────

    def open_file(self, params: dict):
        path = params.get("path", "")
        logger.info(f"[STUB] Opening file: {path}")
        # TODO Week 5: os.startfile(path)

    def open_folder(self, params: dict):
        path = params.get("path", "")
        logger.info(f"[STUB] Opening folder: {path}")
        # TODO Week 5: subprocess.Popen(["explorer", path])

    def search_files(self, params: dict):
        query = params.get("query", "")
        location = params.get("location", os.path.expanduser("~"))
        logger.info(f"[STUB] Searching for '{query}' in {location}")

    # ── System Controls ───────────────────────────────────────────────────────

    def volume_up(self, params: dict):
        amount = params.get("amount", 10)
        logger.info(f"[STUB] Volume up: {amount}%")
        # TODO Week 5: use pycaw or nircmd.exe

    def volume_down(self, params: dict):
        amount = params.get("amount", 10)
        logger.info(f"[STUB] Volume down: {amount}%")

    def volume_mute(self, params: dict):
        logger.info("[STUB] Toggling mute")

    def lock_screen(self, params: dict):
        logger.info("[STUB] Locking screen")
        # TODO Week 5: ctypes.windll.user32.LockWorkStation()
