"""Local implementation of the env.step interface used by OSWorld agents."""

import ctypes
from io import BytesIO
import json
import subprocess
import time


class DesktopEnv:
    def __init__(self, *, gui=None, keyboard=None):
        if gui is None:
            import pyautogui as gui
        if keyboard is None:
            import pydirectinput as keyboard
        if not hasattr(keyboard, "scancode_press"):
            raise RuntimeError("Install pydirectinput-rgx, not original pydirectinput")
        self.gui, self.keyboard = gui, keyboard
        self.hwnd = None

    def game_windows(self, title="League of Legends (TM) Client"):
        """Describe exact-title game windows, including their owning processes."""
        import pygetwindow

        windows = []
        for window in pygetwindow.getWindowsWithTitle(title):
            if window.title != title:
                continue
            process_id = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(
                ctypes.c_void_p(window._hWnd), ctypes.byref(process_id))
            windows.append({"title": window.title, "hwnd": window._hWnd,
                            "pid": process_id.value})
        return windows

    def bind_window(self, title):
        """Optionally restrict execution to one foreground window, regardless of agent."""
        import pygetwindow

        windows = [w for w in pygetwindow.getWindowsWithTitle(title) if w.title == title]
        if len(windows) != 1:
            raise RuntimeError(f"Expected exactly one window titled {title!r}; "
                               f"found {len(windows)}, handles={[w._hWnd for w in windows]}")
        window = windows[0]
        if window.isMinimized:
            window.restore()
        self.hwnd = window._hWnd
        deadline = time.monotonic() + 10
        while True:
            try:
                self._check_foreground()
                return
            except RuntimeError:
                pass
            try:
                window.activate()
            except pygetwindow.PyGetWindowException:
                # SetForegroundWindow may report failure even when focus changed.
                pass
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = ctypes.c_void_p
            foreground = user32.GetForegroundWindow()
            current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
            foreground_thread = user32.GetWindowThreadProcessId(
                ctypes.c_void_p(foreground), None)
            attached = False
            try:
                if foreground_thread and foreground_thread != current_thread:
                    attached = bool(user32.AttachThreadInput(
                        current_thread, foreground_thread, True))
                user32.BringWindowToTop(ctypes.c_void_p(self.hwnd))
                user32.SetForegroundWindow(ctypes.c_void_p(self.hwnd))
            finally:
                if attached:
                    user32.AttachThreadInput(current_thread, foreground_thread, False)
            time.sleep(0.3)
            try:
                self._check_foreground()
                return
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise

    def _check_foreground(self):
        if self.hwnd is not None:
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = ctypes.c_void_p
            if user32.GetForegroundWindow() != self.hwnd:
                raise RuntimeError("Target window lost foreground focus; no input sent")

    def _bound_window_exists(self):
        return bool(self.hwnd and ctypes.windll.user32.IsWindow(ctypes.c_void_p(self.hwnd)))

    def dismiss_afk_warning(self):
        """Use separate mouse down/up events so the game observes the OK click."""
        self._check_foreground()
        print("Closing game: clicking AFK Warning OK at (956, 488), hold=0.12s", flush=True)
        self.keyboard.moveTo(956, 488, _pause=False)
        time.sleep(0.1)
        self._check_foreground()
        try:
            self.keyboard.mouseDown(button="left", _pause=False)
            time.sleep(0.12)
        finally:
            self.keyboard.mouseUp(button="left", _pause=False)
        time.sleep(0.3)

    def exit_game(self, title="League of Legends (TM) Client"):
        """Normally leave the game by sending Alt+F4 twice to its own window."""
        self.bind_window(title)
        self.dismiss_afk_warning()
        self._check_foreground()
        print(f"Closing game: sending first Alt+F4 to hwnd={self.hwnd}", flush=True)
        self.keyboard.hotkey("alt", "f4", wait=0.08)
        time.sleep(0.5)
        # Never send the second shortcut to the client or another foreground app.
        if self._bound_window_exists():
            self._check_foreground()
            print(f"Closing game: sending second Alt+F4 to hwnd={self.hwnd}", flush=True)
            self.keyboard.hotkey("alt", "f4", wait=0.08)
        self.hwnd = None

    def game_process_ids(self):
        """Inspect only the game executable, excluding the League launcher."""
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "@(Get-Process -Name 'League of Legends' -ErrorAction SilentlyContinue | "
             "Select-Object -ExpandProperty Id) | ConvertTo-Json -Compress"],
            capture_output=True, text=True, check=True, timeout=10,
        )
        ids = json.loads(result.stdout) if result.stdout.strip() else []
        return [ids] if isinstance(ids, int) else ids

    def clear_stale_game(self, client):
        """Close a detached game; force termination only while LCU has no session."""
        if client.phase() != "None":
            raise RuntimeError("Cannot clear a residual game while a session is active")
        ids = self.game_process_ids()
        if not ids:
            self.hwnd = None
            return {"method": "no_residual_game"}
        graceful_error = None
        attempted_alt_f4 = bool(self.game_windows())
        if attempted_alt_f4:
            try:
                self.exit_game()
            except Exception as exc:
                graceful_error = str(exc)
        deadline = time.monotonic() + 5
        while self.game_process_ids() and time.monotonic() < deadline:
            time.sleep(0.5)
        remaining = self.game_process_ids()
        forced_ids = [pid for pid in remaining if pid in ids]
        if remaining:
            if client.phase() != "None":
                raise RuntimeError("Client entered a session during residual-game cleanup")
            if set(remaining) != set(forced_ids):
                raise RuntimeError("A new game process appeared during cleanup")
            pid_list = ",".join(str(int(pid)) for pid in forced_ids)
            print(f"Client home confirmed; force closing residual game PIDs {forced_ids}",
                  flush=True)
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                 f"Get-Process -Id {pid_list} -ErrorAction SilentlyContinue | "
                 "Where-Object { $_.ProcessName -eq 'League of Legends' } | "
                 "Stop-Process -Force -ErrorAction Stop"],
                capture_output=True, text=True, check=True, timeout=10,
            )
        self.hwnd = None
        # Stop-Process can return before Windows finishes removing the process.
        deadline = time.monotonic() + 5
        while self.game_process_ids():
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Residual game process did not finish shutting down; "
                                   f"process_ids={self.game_process_ids()}, windows={self.game_windows()}")
            time.sleep(0.5)
        if client.phase() != "None":
            raise RuntimeError("Residual-game cleanup could not confirm a clean client")
        method = ("terminate_residual_game" if forced_ids else
                  "alt_f4_residual_game" if attempted_alt_f4 else "wait_residual_game")
        result = {"method": method,
                  "process_ids": ids}
        if graceful_error:
            result["graceful_error"] = graceful_error
        return result

    def get_obs(self):
        self._check_foreground()
        png = BytesIO()
        self.gui.screenshot().save(png, format="PNG")
        return {"screenshot": png.getvalue()}

    def center_mouse(self):
        """Move the cursor to the primary screen center before the first observation."""
        self._check_foreground()
        width, height = self.gui.size()
        center = (width // 2, height // 2)
        for _ in range(2):
            self._check_foreground()
            self.gui.moveTo(*center, duration=0.2)
            self._check_foreground()
            if tuple(self.gui.position()) == center:
                return
        raise RuntimeError("Mouse did not reach the screen center")

    def step(self, action, sleep_after_execution=0.0):
        """Execute Python code and return (observation, reward, terminated, info).

        Like OSWorld's Python action space, this runs trusted agent code with
        Python privileges. This is an execution interface, not a sandbox.
        Scoring remains the task's responsibility.
        """
        if not isinstance(action, str) or not action.strip():
            raise ValueError("Expected a non-empty Python action string")

        self._check_foreground()

        if action not in {"WAIT", "DONE", "FAIL"}:
            namespace = {
                "pyautogui": self.gui,
                "pydirectinput": self.keyboard,
                "time": time,
            }
            exec(compile(action, "<desktop-action>", "exec"), namespace)

        if sleep_after_execution:
            time.sleep(sleep_after_execution)

        return self.get_obs(), 0.0, action in {"DONE", "FAIL"}, {}
