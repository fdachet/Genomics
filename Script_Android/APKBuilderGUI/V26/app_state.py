from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable


CONFIG_PATH = Path.home() / ".apk_builder_gui_v26_windows_only_config.json"
FALLBACK_CONFIG_PATHS = [
    # Windows-only GUI versions. Keep newest first so existing paths are migrated.
    Path.home() / ".apk_builder_gui_v25_windows_only_config.json",
    Path.home() / ".apk_builder_gui_v24_windows_only_config.json",
    Path.home() / ".apk_builder_gui_v23_windows_only_config.json",
    Path.home() / ".apk_builder_gui_v22_windows_only_config.json",
    Path.home() / ".apk_builder_gui_v21_windows_only_config.json",
    Path.home() / ".apk_builder_gui_v20_windows_only_config.json",
    Path.home() / ".apk_builder_gui_v19_windows_only_config.json",
    Path.home() / ".apk_builder_gui_v18_windows_only_config.json",
    Path.home() / ".apk_builder_gui_v17_windows_only_config.json",
    # Older mixed Windows/WSL versions that may still contain useful Java/SDK paths.
    Path.home() / ".apk_builder_gui_v16_config.json",
    Path.home() / ".apk_builder_gui_v15_config.json",
    Path.home() / ".apk_builder_gui_v14_config.json",
    Path.home() / ".apk_builder_gui_v13_config.json",
    Path.home() / ".apk_builder_gui_v12_config.json",
    Path.home() / ".apk_builder_gui_v11_config.json",
    Path.home() / ".apk_builder_gui_v10_config.json",
    Path.home() / ".apk_builder_gui_v9_config.json",
    Path.home() / ".apk_builder_gui_v8_config.json",
    Path.home() / ".apk_builder_gui_v7_config.json",
    Path.home() / ".apk_builder_gui_v6_config.json",
]


DEFAULT_CONFIG: dict[str, Any] = {
    "project_dir": "",
    "output_dir": str(Path.home() / "Desktop" / "APK_Output"),
    "output_apk_name": "",
    "app_icon_file": "",
    "make_new_application": True,
    "application_id_override": "",
    "build_environment": "Windows",
    "build_task": "assembleDebug",

    "java_exe": "",
    "java_home": "",
    "gradle_exe": "",
    "gradle_wrapper": "",
    "gradle_zip": "",
    "gradle_install_root": r"C:\Gradle",

    "android_sdk_root_windows": "",
    "sdkmanager_exe": "",
    "cmdline_tools_zip": "",
    "adb_exe": "",
    "aapt2_exe": "",
    "apksigner_exe": "",
    "zipalign_exe": "",


    "android_platform": "android-35",
    "build_tools_version": "35.0.0",
}


class AppState:
    def __init__(self, root):
        self.root = root
        self.config: dict[str, Any] = DEFAULT_CONFIG.copy()
        self.log_listeners: list[Callable[[str, str, str], None]] = []
        self.config_listeners: list[Callable[[dict[str, Any]], None]] = []
        self.queue: queue.Queue[tuple] = queue.Queue()
        self.active_threads: list[threading.Thread] = []
        self.current_process = None
        self.stop_requested = False
        self._saving_config = False
        self.load_config()
        self.root.after(80, self.pump_queue)

    def load_config(self) -> None:
        paths = [CONFIG_PATH, *FALLBACK_CONFIG_PATHS]
        for path in paths:
            if path.exists():
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        self.config.update(loaded)
                        self._migrate_config()
                        return
                except Exception:
                    pass


    def _migrate_config(self) -> None:
        """Clean old saved values from older GUI versions.

        v15-v17 allowed Gradle 8.7 to remain selected even though the current
        example project requires Gradle 8.9 or newer. Keeping that stale path
        makes button #22 fail before it can create gradlew.bat. Clear only the
        stale Gradle paths; keep Java and Android SDK paths.
        """
        for key in ("gradle_exe", "gradle_zip"):
            value = str(self.config.get(key, ""))
            normalized = value.replace("\\", "/").lower()
            if "gradle-8.7" in normalized or "gradle-8_7" in normalized:
                self.config[key] = ""

    def save_config(self, notify: bool = True) -> None:
        try:
            CONFIG_PATH.write_text(json.dumps(self.config, indent=2), encoding="utf-8")
        except Exception as exc:
            self.log(f"Could not save config: {exc}", "ERROR")
        if notify:
            self.notify_config_changed()

    def update_config(self, values: dict[str, Any], notify: bool = True) -> None:
        self.config.update(values)
        self.save_config(notify=notify)

    def add_log_listener(self, listener: Callable[[str, str, str], None]) -> None:
        self.log_listeners.append(listener)

    def add_config_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        self.config_listeners.append(listener)

    def notify_config_changed(self) -> None:
        snapshot = dict(self.config)
        for listener in list(self.config_listeners):
            self.post(listener, snapshot)

    def log(self, message: str, level: str = "INFO") -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.queue.put(("log", timestamp, level, str(message)))

    def post(self, callback: Callable, *args, **kwargs) -> None:
        self.queue.put(("call", callback, args, kwargs))

    def pump_queue(self) -> None:
        try:
            while True:
                item = self.queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    _, timestamp, level, message = item
                    for listener in list(self.log_listeners):
                        listener(timestamp, level, message)
                elif kind == "call":
                    _, callback, args, kwargs = item
                    try:
                        callback(*args, **kwargs)
                    except Exception as exc:
                        self.log(f"UI callback failed: {exc}", "ERROR")
        except queue.Empty:
            pass
        self.root.after(80, self.pump_queue)

    def run_in_thread(self, name: str, target: Callable, *args, **kwargs) -> threading.Thread:
        def wrapped():
            try:
                target(*args, **kwargs)
            except Exception as exc:
                self.log(f"{name} failed: {exc}", "ERROR")

        thread = threading.Thread(target=wrapped, name=name, daemon=True)
        self.active_threads.append(thread)
        thread.start()
        return thread

    def request_stop(self) -> None:
        self.stop_requested = True
        proc = self.current_process
        if proc is not None:
            try:
                proc.terminate()
                self.log("Stop requested: process terminated.", "WARN")
            except Exception as exc:
                self.log(f"Could not terminate process: {exc}", "ERROR")
