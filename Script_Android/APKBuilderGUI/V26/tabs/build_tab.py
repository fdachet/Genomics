from __future__ import annotations

import os
import re
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

from command_utils import (
    IS_WINDOWS,
    apply_app_identity_to_project,
    apply_launcher_icon_to_project,
    copy_newest_apk,
    gradle_wrapper_windows,
    list_apks,
    make_windows_env,
    run_streaming,
    run_windows_script_capture,
    split_tasks,
    windows_env_setup_script,
)
from style import make_header


class BuildTab(ttk.Frame):
    def __init__(self, parent, state):
        super().__init__(parent)
        self.state = state
        self.environment = tk.StringVar(value="Windows")
        self.build_task = tk.StringVar(value=state.config.get("build_task", "assembleDebug"))
        self.status = tk.StringVar(value="Ready")
        self._build_ui()
        self.refresh_apks()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        make_header(
            self,
            "Build APK",
            "Uses the selected build program and Android SDK paths. Start with assembleDebug to create a test APK.",
            purple=True,
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))

        settings = ttk.LabelFrame(self, text="Build settings - the build action is the command given to Gradle")
        settings.grid(row=1, column=0, sticky="ew", padx=10, pady=8)
        settings.columnconfigure(3, weight=1)
        settings.columnconfigure(5, weight=1)

        ttk.Label(settings, text="Environment:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(settings, textvariable=self.environment, values=["Windows"], state="readonly", width=12).grid(row=0, column=1, sticky="w", padx=6, pady=4)

        ttk.Label(settings, text="Build action:").grid(row=0, column=2, sticky="w", padx=6, pady=4)
        ttk.Combobox(
            settings,
            textvariable=self.build_task,
            values=["assembleDebug", "clean assembleDebug", "assembleRelease", "clean assembleRelease", "bundleDebug", "bundleRelease"],
            width=24,
        ).grid(row=0, column=3, sticky="w", padx=6, pady=4)

        ttk.Button(settings, text="Save", command=self.save_settings, style="Accent.TButton").grid(row=0, column=4, padx=4)
        ttk.Button(settings, text="Build APK", command=self.start_build, style="Ok.TButton").grid(row=0, column=5, sticky="w", padx=4)
        ttk.Button(settings, text="Stop", command=self.state.request_stop, style="Danger.TButton").grid(row=0, column=6, padx=4)
        ttk.Button(settings, text="Refresh APK list", command=self.refresh_apks).grid(row=0, column=7, padx=4)

        info = ttk.LabelFrame(self, text="Paths used")
        info.grid(row=2, column=0, sticky="ew", padx=10, pady=6)
        info.columnconfigure(1, weight=1)
        self.path_text = tk.Text(info, height=8, wrap="word")
        self.path_text.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        ttk.Button(info, text="Refresh paths", command=self.refresh_paths).grid(row=0, column=1, sticky="ne", padx=6, pady=6)

        status_frame = ttk.Frame(self)
        status_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 6))
        status_frame.columnconfigure(0, weight=1)
        ttk.Label(status_frame, textvariable=self.status, style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(status_frame, mode="indeterminate")
        self.progress.grid(row=0, column=1, sticky="e", padx=5)

        apk_frame = ttk.LabelFrame(self, text="Detected APK files")
        apk_frame.grid(row=4, column=0, sticky="nsew", padx=10, pady=8)
        apk_frame.rowconfigure(0, weight=1)
        apk_frame.columnconfigure(0, weight=1)

        self.apk_list = tk.Listbox(apk_frame, height=10)
        self.apk_list.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        scroll = ttk.Scrollbar(apk_frame, command=self.apk_list.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=6)
        self.apk_list.configure(yscrollcommand=scroll.set)

        btns = ttk.Frame(apk_frame)
        btns.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=6)
        ttk.Button(btns, text="Open output folder", command=self.open_output).pack(side="left", padx=4)
        ttk.Button(btns, text="Open project folder", command=self.open_project).pack(side="left", padx=4)

        self.refresh_paths()

    def save_settings(self) -> None:
        self.state.config["build_environment"] = "Windows"
        self.environment.set("Windows")
        self.state.config["build_task"] = self.build_task.get().strip()
        self.state.save_config()
        self.state.log("Build settings saved. APK output filename is configured only in the Project tab.", "OK")

    def refresh_paths(self) -> None:
        cfg = self.state.config
        text = (
            f"Project folder: {cfg.get('project_dir', '')}\n"
            f"APK output folder: {cfg.get('output_dir', '')}\n"
            f"Java executable: {cfg.get('java_exe', '')}\n"
            f"JAVA_HOME: {cfg.get('java_home', '')}\n"
            f"Android SDK root Windows: {cfg.get('android_sdk_root_windows', '')}\n"
            f"Gradle wrapper: {cfg.get('gradle_wrapper', '')}\n"
            f"Global Gradle: {cfg.get('gradle_exe', '')}\n"
            f"Installed app name/APK filename: {cfg.get('output_apk_name', '')}\n"
            f"Create separate application ID: {cfg.get('make_new_application', True)}\n"
            f"Unique application ID override: {cfg.get('application_id_override', '')}\n"
        )
        self.path_text.configure(state="normal")
        self.path_text.delete("1.0", "end")
        self.path_text.insert("1.0", text)
        self.path_text.configure(state="disabled")

    def start_build(self) -> None:
        self.save_settings()
        project = self.state.config.get("project_dir", "").strip()
        if not project or not Path(project).exists():
            messagebox.showerror("Missing project", "Select and verify the Android source project first.")
            return
        self.progress.start(10)
        self.status.set("Building APK...")
        self.state.run_in_thread("Build APK", self._build_worker)

    def _build_worker(self) -> None:
        try:
            self.state.log("Selected build environment: Windows", "INFO")
            rc = self._run_windows_build()
            if rc == 0:
                copied = copy_newest_apk(self.state.config.get("project_dir", ""), self.state.config.get("output_dir", ""), self.state.config.get("output_apk_name", ""))
                if copied:
                    self.state.log(f"Newest APK copied to: {copied}", "OK")
                else:
                    self.state.log("Build succeeded, but no APK file was found under the project folder.", "WARN")
            self.state.post(self._finish_build, rc)
        except Exception as exc:
            self.state.log(str(exc), "ERROR")
            self.state.post(self._finish_build, 1)

    def _run_windows_build(self) -> int:
        cfg = self.state.config
        project = cfg.get("project_dir", "").strip()
        tasks = split_tasks(cfg.get("build_task", "assembleDebug"))
        env = make_windows_env(cfg)

        wrapper = cfg.get("gradle_wrapper", "").strip() or gradle_wrapper_windows(project)
        gradle = cfg.get("gradle_exe", "").strip()

        if not self._java_ok_for_gradle89():
            self.state.log("Build stopped before running Gradle because the selected Java is not compatible with Gradle 8.9.", "ERROR")
            self.state.log("Fix: install/select JDK 17 or JDK 21 in Install Help, then verify Gradle again.", "WARN")
            return 1

        output_apk_name = cfg.get("output_apk_name", "").strip()
        if output_apk_name:
            ok, message = apply_app_identity_to_project(
                project,
                output_apk_name,
                cfg.get("application_id_override", "").strip(),
                bool(cfg.get("make_new_application", True)),
            )
            self.state.log(message, "OK" if ok else "ERROR")
            if not ok:
                self.state.log("Build stopped because the app name/application ID could not be applied.", "ERROR")
                return 1
        else:
            self.state.log("No installed app name/APK filename set in Project tab; keeping the current app label and applicationId.", "WARN")

        icon_file = cfg.get("app_icon_file", "").strip()
        if icon_file:
            ok, message = apply_launcher_icon_to_project(project, icon_file)
            self.state.log(message, "OK" if ok else "ERROR")
            if not ok:
                self.state.log("Build stopped because the selected launcher icon could not be applied.", "ERROR")
                return 1

        if wrapper and Path(wrapper).exists():
            self._repair_wrapper_to_gradle89_if_needed(project)
            command = [wrapper] + tasks
        elif gradle and Path(gradle).exists():
            command = [gradle] + tasks
        else:
            self.state.log("No Gradle build program is available for this project.", "ERROR")
            self.state.log("The project has no gradlew.bat, and no global gradle.bat is selected.", "ERROR")
            self.state.log("Fix: open tab 4 Install Help, use buttons 18-21 to install/verify Gradle, then button 22 to create gradlew.bat in the project.", "WARN")
            return 1

        return run_streaming(command, self.state, cwd=project, env=env, shell=False)


    def _repair_wrapper_to_gradle89_if_needed(self, project: str) -> None:
        prop = Path(project) / "gradle" / "wrapper" / "gradle-wrapper.properties"
        if not prop.exists():
            return
        try:
            text = prop.read_text(encoding="utf-8", errors="replace")
            if "gradle-8.9" in text:
                return
            new_text = re.sub(
                r"(?m)^distributionUrl=.*$",
                "distributionUrl=https\\://services.gradle.org/distributions/gradle-8.9-bin.zip",
                text,
            )
            if new_text == text and "distributionUrl=" not in text:
                new_text = text.rstrip() + "\ndistributionUrl=https\\://services.gradle.org/distributions/gradle-8.9-bin.zip\n"
            prop.write_text(new_text, encoding="utf-8")
            self.state.log(f"Updated Gradle wrapper to use Gradle 8.9: {prop}", "OK")
        except Exception as exc:
            self.state.log(f"Could not update Gradle wrapper properties before build: {exc}", "WARN")


    def _java_ok_for_gradle89(self) -> bool:
        cfg = self.state.config
        setup = windows_env_setup_script(cfg)
        script = (setup + "\n" if setup else "") + "where java\njava -version"
        result = run_windows_script_capture(script, timeout=25)
        output = result.output or ""
        for line in output.splitlines():
            self.state.log(line, "OUT")
        m = re.search(r'version\s+"(\d+)(?:\.(\d+))?', output)
        if not m:
            m = re.search(r'openjdk\s+(\d+)(?:\.(\d+))?', output, re.IGNORECASE)
        if not m:
            self.state.log("Could not determine Java version before Gradle build.", "ERROR")
            return False
        major = int(m.group(1))
        if major == 1 and m.group(2):
            major = int(m.group(2))
        if 17 <= major <= 21:
            self.state.log(f"Java {major} is OK for the Gradle 8.9 build.", "OK")
            return True
        if major > 21:
            self.state.log(f"Java {major} is too new for Gradle 8.9 in this project.", "ERROR")
            self.state.log("This causes errors such as: Unsupported class file major version 69.", "ERROR")
            return False
        self.state.log(f"Java {major} is too old for Android Gradle Plugin; use JDK 17 or 21.", "ERROR")
        return False

    def _finish_build(self, rc: int) -> None:
        self.progress.stop()
        self.status.set("Build completed." if rc == 0 else "Build failed.")
        self.refresh_apks()
        self.refresh_paths()

    def refresh_apks(self) -> None:
        self.apk_list.delete(0, "end")
        project = self.state.config.get("project_dir", "").strip()
        apks = list_apks(project) if project else []
        if not apks:
            self.apk_list.insert("end", "No APK found yet.")
        else:
            for apk in apks:
                self.apk_list.insert("end", str(apk))
        self.status.set(f"Found {len(apks)} APK file(s).")

    def open_output(self) -> None:
        self._open_folder(self.state.config.get("output_dir", ""))

    def open_project(self) -> None:
        self._open_folder(self.state.config.get("project_dir", ""))

    def _open_folder(self, folder: str) -> None:
        if not folder:
            return
        path = Path(folder).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
