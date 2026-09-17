from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import zipfile
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from command_utils import (
    clean_cmd_text,
    default_android_sdk_root,
    find_sdk_tool,
    make_windows_env,
    quote_cmd_arg,
    run_capture,
    run_streaming,
    run_windows_script_capture,
    run_windows_script_streaming,
    windows_env_setup_script,
)
from data.components import (
    ANDROID_CMDLINE_WIN_ZIP,
    ANDROID_SDKMANAGER_DOCS,
    ANDROID_STUDIO_DOWNLOADS,
    TEMURIN_DOWNLOADS,
    TEMURIN_JDK17_WIN_X64_INSTALLER,
    TEMURIN_JDK21_WIN_X64_INSTALLER,
    GRADLE_89_BIN_ZIP,
    GRADLE_INSTALL,
    GRADLE_RELEASES,
)
from style import make_header


class InstallTab(ttk.Frame):
    """Beginner installation tab with one-click sdkmanager and Gradle commands.

    v19 is Windows-only, uses a compact layout, keeps the global log visible, and can bootstrap a Gradle 8.9 project wrapper even when only old Gradle 8.7 is installed globally.

    Older versions focused on the exact failures reported by the user:
    1) sdkmanager.bat exists, but sdkmanager prints "Java version 17 or higher is required".
    2) sdkmanager paths were accidentally double-quoted/escaped in a cmd.exe command.
    3) sdkmanager.bat exists but its required lib folder/JARs are missing, causing
       ClassNotFoundException: com.android.sdklib.tool.sdkmanager.SdkManagerCli.
    4) Windows locks a file in the broken cmdline-tools\\latest folder, so repair
       must not depend on deleting or moving that locked folder.
    This tab makes the selected Java explicit and launches sdkmanager with cmd.exe:
        call "C:\\Android\\Sdk\\cmdline-tools\\latest\\bin\\sdkmanager.bat" "--sdk_root=C:\\Android\\Sdk" ...
    """

    def __init__(self, parent, state):
        super().__init__(parent)
        self.state = state
        self.android_platform = tk.StringVar(value=state.config.get("android_platform", "android-35"))
        self.build_tools_version = tk.StringVar(value=state.config.get("build_tools_version", "35.0.0"))
        self.sdk_root = tk.StringVar(value=state.config.get("android_sdk_root_windows", "") or default_android_sdk_root() or r"C:\Android\Sdk")
        self.sdkmanager = tk.StringVar(value=state.config.get("sdkmanager_exe", ""))
        self.cmdline_tools_zip = tk.StringVar(value=state.config.get("cmdline_tools_zip", ""))
        self.java_home = tk.StringVar(value=state.config.get("java_home", ""))
        self.java_exe = tk.StringVar(value=state.config.get("java_exe", ""))
        self.gradle_zip = tk.StringVar(value=state.config.get("gradle_zip", ""))
        self.gradle_install_root = tk.StringVar(value=state.config.get("gradle_install_root", r"C:\Gradle"))
        self.gradle_exe = tk.StringVar(value=state.config.get("gradle_exe", ""))
        self.status = tk.StringVar(value="Ready")
        self._build_ui()
        self.state.add_config_listener(self.on_config_changed)
        self.refresh_text()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        make_header(
            self,
            "Install: Java + Android SDK + Gradle",
            "Compact setup. The always-visible log below shows every command and error.",
            purple=True,
        ).grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 3))

        top = ttk.LabelFrame(self, text="Main locations")
        top.grid(row=1, column=0, sticky="ew", padx=6, pady=3)
        for col in range(6):
            top.columnconfigure(col, weight=1 if col in (1, 4) else 0)

        self._path_cell(top, 0, 0, "SDK folder", self.sdk_root, self.browse_sdk_root)
        self._path_cell(top, 0, 3, "JDK folder", self.java_home, self.browse_java_home)
        self._path_cell(top, 1, 0, "java.exe", self.java_exe, self.browse_java_exe)
        self._path_cell(top, 1, 3, "sdkmanager.bat", self.sdkmanager, self.browse_sdkmanager)
        self._path_cell(top, 2, 0, "Android tools ZIP", self.cmdline_tools_zip, self.browse_cmdline_tools_zip)
        self._path_cell(top, 2, 3, "Gradle ZIP", self.gradle_zip, self.browse_gradle_zip)
        self._path_cell(top, 3, 0, "Gradle folder", self.gradle_install_root, self.browse_gradle_install_root)
        self._path_cell(top, 3, 3, "gradle.bat", self.gradle_exe, self.browse_gradle_exe)

        packages = ttk.LabelFrame(self, text="Versions / quick actions")
        packages.grid(row=2, column=0, sticky="ew", padx=6, pady=3)
        packages.columnconfigure(8, weight=1)
        ttk.Label(packages, text="Android platform:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(packages, textvariable=self.android_platform, width=12).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(packages, text="Build-tools:").grid(row=0, column=2, sticky="w", padx=(10, 4))
        ttk.Entry(packages, textvariable=self.build_tools_version, width=12).grid(row=0, column=3, sticky="w", padx=4)
        ttk.Button(packages, text="Save", command=self.save_settings, style="Accent.TButton").grid(row=0, column=4, padx=4)
        ttk.Button(packages, text="Auto-detect", command=self.auto_detect_everything, style="Ok.TButton").grid(row=0, column=5, padx=4)
        ttk.Label(packages, textvariable=self.status, style="Muted.TLabel").grid(row=0, column=6, sticky="w", padx=8)

        body = ttk.PanedWindow(self, orient="horizontal")
        body.grid(row=3, column=0, sticky="nsew", padx=6, pady=4)

        left = ttk.Frame(body)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        right = ttk.LabelFrame(body, text="Explanation / exact steps")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        body.add(left, weight=1)
        body.add(right, weight=2)

        actions = ttk.Notebook(left)
        actions.grid(row=0, column=0, sticky="nsew")

        def add_page(title: str, rows: list[tuple[str, object, str]]):
            page = ttk.Frame(actions)
            page.columnconfigure(0, weight=1)
            actions.add(page, text=title)
            for row, (text, command, style) in enumerate(rows):
                ttk.Button(page, text=text, command=command, style=style).grid(row=row, column=0, sticky="ew", padx=6, pady=3)
            return page

        add_page("Java", [
            ("1. Open JDK 17/21 download page", lambda: webbrowser.open(TEMURIN_DOWNLOADS), "Accent.TButton"),
            ("1a. Open direct JDK 17 installer", self.open_jdk17_installer, "Accent.TButton"),
            ("1b. Open direct JDK 21 installer", self.open_jdk21_installer, "Accent.TButton"),
            ("2. Auto-detect installed Java", self.auto_detect_java, "Ok.TButton"),
            ("2b. Auto-detect JDK 17/21 only", self.auto_detect_gradle_java_only, "Ok.TButton"),
            ("3. Verify selected Java", self.verify_selected_java, "Warn.TButton"),
            ("3b. Verify Java for Gradle", self.verify_java_for_gradle, "Warn.TButton"),
            ("4. Verify Java used by sdkmanager", self.verify_java_used_by_sdkmanager, "Warn.TButton"),
            ("Explain Java / Gradle compatibility", self.explain_gradle_java, "TButton"),
        ])

        add_page("Android SDK", [
            ("5. Open Android command-line tools ZIP", self.open_windows_zip, "Accent.TButton"),
            ("6. Browse downloaded Android tools ZIP", self.browse_cmdline_tools_zip, "TButton"),
            ("7. Create SDK folders", self.create_sdk_folders, "Ok.TButton"),
            ("8. Extract / repair command-line tools", self.extract_cmdline_tools_zip, "Accent.TButton"),
            ("9. Verify command-line tools", self.verify_cmdline_layout, "Warn.TButton"),
            ("10. Run sdkmanager --version", self.run_sdkmanager_version, "Ok.TButton"),
            ("11. Install platform-tools", self.install_platform_tools_windows, "Ok.TButton"),
            ("12. Install Android platform", self.install_platform_windows, "Ok.TButton"),
            ("13. Install build-tools", self.install_build_tools_windows, "Ok.TButton"),
            ("14. Install all SDK packages", self.install_sdk_windows, "Accent.TButton"),
            ("15. Accept SDK licenses", self.accept_licenses_windows, "TButton"),
            ("16. Auto-fill SDK tool paths", self.autofill_sdk_tools, "Accent.TButton"),
            ("17. Verify SDK tools", self.verify_installed_sdk_tools, "Warn.TButton"),
            ("Explain sdkmanager", self.explain_sdkmanager, "TButton"),
        ])

        add_page("Gradle", [
            ("17a. Verify Java for Gradle first", self.verify_java_for_gradle, "Warn.TButton"),
            ("18. Open direct Gradle 8.9 ZIP", self.open_gradle_89_zip, "Accent.TButton"),
            ("19. Browse downloaded Gradle ZIP", self.browse_gradle_zip, "TButton"),
            ("20. Extract Gradle ZIP + select gradle.bat", self.extract_gradle_zip, "Accent.TButton"),
            ("21. Verify global Gradle", self.verify_global_gradle, "Warn.TButton"),
            ("22. Create gradlew.bat in project", self.create_project_gradle_wrapper, "Ok.TButton"),
            ("23. Explain Gradle install", self.explain_gradle, "TButton"),
            ("Open official Gradle install docs", lambda: webbrowser.open(GRADLE_INSTALL), "TButton"),
            ("Open Gradle releases page", lambda: webbrowser.open(GRADLE_RELEASES), "TButton"),
        ])

        add_page("Other", [
            ("Open Command Prompt ready", self.open_cmd_at_sdk, "TButton"),
            ("Explain the Java 17 error", self.explain_java_error, "TButton"),
            ("Open sdkmanager documentation", lambda: webbrowser.open(ANDROID_SDKMANAGER_DOCS), "TButton"),
            ("Open command-line tools page", lambda: webbrowser.open(ANDROID_STUDIO_DOWNLOADS), "TButton"),
        ])

        gradle_note = tk.Label(
            left,
            text="Gradle step: select JDK 17/21 -> download gradle-8.9-bin.zip -> extract -> verify -> create wrapper.",
            bg="#fef3c7",
            fg="#92400e",
            anchor="w",
            justify="left",
            padx=8,
            pady=5,
            font=("Segoe UI", 9, "bold"),
        )
        gradle_note.grid(row=1, column=0, sticky="ew", pady=(4, 0))

        self.text = tk.Text(right, wrap="word", height=18, bg="#f8fafc", fg="#111827", insertbackground="#111827", font=("Segoe UI", 9))
        self.text.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        scroll = ttk.Scrollbar(right, command=self.text.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=4)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.tag_configure("h", foreground="#1d4ed8", font=("Segoe UI", 11, "bold"))
        self.text.tag_configure("warn", foreground="#b91c1c", font=("Segoe UI", 9, "bold"))
        self.text.tag_configure("cmd", foreground="#7c2d12", background="#ffedd5", font=("Consolas", 9))
        self.text.tag_configure("ok", foreground="#166534", font=("Segoe UI", 9, "bold"))

    def _path_cell(self, parent, row: int, col: int, label: str, variable: tk.StringVar, command) -> None:
        ttk.Label(parent, text=label + ":").grid(row=row, column=col, sticky="w", padx=(4, 2), pady=2)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=col + 1, sticky="ew", padx=2, pady=2)
        if command is not None:
            ttk.Button(parent, text="...", width=3, command=command).grid(row=row, column=col + 2, padx=(2, 6), pady=2)

    def _path_row(self, parent, row: int, label: str, variable: tk.StringVar, command) -> None:
        self._path_cell(parent, row, 0, label, variable, command)

    def on_config_changed(self, config: dict) -> None:
        mapping = {
            "android_platform": self.android_platform,
            "build_tools_version": self.build_tools_version,
            "android_sdk_root_windows": self.sdk_root,
            "sdkmanager_exe": self.sdkmanager,
            "cmdline_tools_zip": self.cmdline_tools_zip,
            "java_home": self.java_home,
            "java_exe": self.java_exe,
            "gradle_zip": self.gradle_zip,
            "gradle_install_root": self.gradle_install_root,
            "gradle_exe": self.gradle_exe,
        }
        changed = False
        for key, var in mapping.items():
            new_value = str(config.get(key, ""))
            if new_value and var.get() != new_value:
                var.set(new_value)
                changed = True
        if changed:
            self.refresh_text()

    def browse_sdk_root(self) -> None:
        path = filedialog.askdirectory(title="Select Windows Android SDK folder, for example C:\\Android\\Sdk")
        if path:
            self.sdk_root.set(path)
            self.save_settings()
            self.autofill_sdkmanager_only()
            self.refresh_text()

    def browse_sdkmanager(self) -> None:
        path = filedialog.askopenfilename(title="Select sdkmanager.bat", filetypes=[("Batch files", "*.bat"), ("All files", "*.*")])
        if path:
            self.sdkmanager.set(path)
            self.save_settings()
            self.refresh_text()

    def browse_cmdline_tools_zip(self) -> None:
        path = filedialog.askopenfilename(
            title="Select the Android command-line tools ZIP you downloaded",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
        )
        if path:
            self.cmdline_tools_zip.set(path)
            self.save_settings()
            self.refresh_text()

    def browse_java_home(self) -> None:
        path = filedialog.askdirectory(title="Select JDK folder / JAVA_HOME, the folder containing bin\\java.exe")
        if path:
            self.java_home.set(path)
            java = Path(path) / "bin" / "java.exe"
            if java.exists():
                self.java_exe.set(str(java))
            self.save_settings()
            self.refresh_text()

    def browse_java_exe(self) -> None:
        path = filedialog.askopenfilename(title="Select java.exe", filetypes=[("java.exe", "java.exe"), ("All files", "*.*")])
        if path:
            self.java_exe.set(path)
            p = Path(path)
            if p.parent.name.lower() == "bin":
                self.java_home.set(str(p.parent.parent))
            self.save_settings()
            self.refresh_text()

    def browse_gradle_zip(self) -> None:
        path = filedialog.askopenfilename(
            title="Select the Gradle binary ZIP you downloaded, for example gradle-8.9-bin.zip",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
        )
        if path:
            self.gradle_zip.set(path)
            self.save_settings()
            self.refresh_text()

    def browse_gradle_install_root(self) -> None:
        path = filedialog.askdirectory(title="Select or create the folder where Gradle will be extracted, usually C:\\Gradle")
        if path:
            self.gradle_install_root.set(path)
            self.save_settings()
            self.refresh_text()

    def browse_gradle_exe(self) -> None:
        path = filedialog.askopenfilename(title="Select gradle.bat", filetypes=[("gradle.bat", "gradle.bat"), ("Batch files", "*.bat"), ("All files", "*.*")])
        if path:
            self.gradle_exe.set(path)
            self.save_settings()
            self.refresh_text()

    def save_settings(self) -> None:
        # Store clean, unquoted paths. Older versions could save paths such as
        # \"C:\Android\Sdk\...\sdkmanager.bat\", which cmd.exe cannot run.
        values = {
            "android_platform": self._android_platform_id(),
            "build_tools_version": self.build_tools_version.get().strip(),
            "android_sdk_root_windows": clean_cmd_text(self.sdk_root.get()),
            "sdkmanager_exe": clean_cmd_text(self.sdkmanager.get()),
            "cmdline_tools_zip": clean_cmd_text(self.cmdline_tools_zip.get()),
            "java_home": clean_cmd_text(self.java_home.get()),
            "java_exe": clean_cmd_text(self.java_exe.get()),
            "gradle_zip": clean_cmd_text(self.gradle_zip.get()),
            "gradle_install_root": clean_cmd_text(self.gradle_install_root.get()) or r"C:\Gradle",
            "gradle_exe": clean_cmd_text(self.gradle_exe.get()),
        }
        self.sdk_root.set(values["android_sdk_root_windows"])
        self.sdkmanager.set(values["sdkmanager_exe"])
        self.cmdline_tools_zip.set(values["cmdline_tools_zip"])
        self.java_home.set(values["java_home"])
        self.java_exe.set(values["java_exe"])
        self.gradle_zip.set(values["gradle_zip"])
        self.gradle_install_root.set(values["gradle_install_root"])
        self.gradle_exe.set(values["gradle_exe"])
        self.state.update_config(values)
        self.state.log("Installation settings saved and sent to Components tab.", "OK")

    def refresh_text(self) -> None:
        sdk = self.sdk_root.get().strip() or r"C:\Android\Sdk"
        build_tools = self.build_tools_version.get().strip() or "35.0.0"
        platform_id = self._android_platform_id()
        platform_package = self._android_platform_package()
        sm = self._sdkmanager_windows()
        java_home = self.java_home.get().strip() or r"C:\Program Files\Eclipse Adoptium\jdk-17..."
        java_exe = self.java_exe.get().strip() or rf"{java_home}\bin\java.exe"
        gradle_zip = self.gradle_zip.get().strip() or r"C:\Users\You\Downloads\gradle-8.9-bin.zip"
        gradle_root = self.gradle_install_root.get().strip() or r"C:\Gradle"
        gradle_exe = self.gradle_exe.get().strip() or rf"{gradle_root}\gradle-8.9\bin\gradle.bat"
        text = rf"""
YOUR CURRENT ERRORS
===================
Earlier errors showed three different problems:

1) Java version 17 or higher is required.
   That means Windows found an old Java, or JAVA_HOME was wrong.

2) Could not find or load main class com.android.sdklib.tool.sdkmanager.SdkManagerCli
   That means sdkmanager.bat exists, but the command-line tools folder is incomplete.
   sdkmanager.bat needs its sibling lib folder and source.properties from the ZIP.

3) Failed to find package 'android-35'
   That means the wrong sdkmanager package name was used. The correct package name is:
   platforms;android-35
   v16 accepts android-35 or 35 in the box, but sends platforms;android-35 to sdkmanager.

4) Gradle missing / gradlew.bat not found
   Your SDK tools are installed, but the selected project does not contain gradlew.bat and no global gradle.bat is selected.
   v16 adds a clearer Gradle workflow and blocks Gradle when Java 25 is selected.

FIX ORDER
=========
1) Install or locate a JDK 17 or newer.
2) Select JAVA_HOME here: {java_home}
3) Select java.exe here: {java_exe}
4) Press "Verify selected Java version".
5) Press "Verify Java used by sdkmanager".
6) Browse the downloaded command-line tools ZIP.
7) Press "Extract / repair command-line tools ZIP layout".
8) Press "Verify full command-line tools installation".
9) Press "Run sdkmanager --version".
10) Install platform-tools, the Android platform, and build-tools.
11) Install/select Gradle. If your project has no gradlew.bat, use the Gradle section: open ZIP -> browse ZIP -> extract -> verify -> create wrapper.

IMPORTANT ABOUT JAVA_HOME
=========================
JAVA_HOME must be the JDK root folder, not the bin folder and not java.exe.
Correct example:
C:\Program Files\Eclipse Adoptium\jdk-17.0.18.10-hotspot

Wrong examples:
C:\Program Files\Eclipse Adoptium\jdk-17...\bin
C:\Program Files\Eclipse Adoptium\jdk-17...\bin\java.exe

WHAT THE GUI RUNS FOR YOU
=========================
The SDK buttons run commands like these with JAVA_HOME and PATH fixed:
"{sm}" --sdk_root="{sdk}" --version
"{sm}" --sdk_root="{sdk}" "platform-tools"
"{sm}" --sdk_root="{sdk}" "{platform_package}"
"{sm}" --sdk_root="{sdk}" "build-tools;{build_tools}"

You do not need to type:
sdkmanager.bat platform-tools

COMMAND-LINE TOOLS LAYOUT / REPAIR
==================================
The file sdkmanager.bat alone is not enough. It must live next to the lib folder from the ZIP.

Standard complete layout:
{sdk}\cmdline-tools\latest\bin\sdkmanager.bat
{sdk}\cmdline-tools\latest\lib\many .jar files
{sdk}\cmdline-tools\latest\source.properties

If Windows locks the old broken latest folder, v16 does not need to delete it. It can create a clean folder such as:
{sdk}\cmdline-tools\latest_gui_YYYYMMDD_HHMMSS\bin\sdkmanager.bat

Then the GUI uses that selected sdkmanager.bat directly.

EXPECTED FILES AFTER SUCCESS
============================
After platform-tools:
{sdk}\platform-tools\adb.exe

After {platform_package}:
{sdk}\platforms\{platform_id}\android.jar

After build-tools;{build_tools}:
{sdk}\build-tools\{build_tools}\aapt2.exe
{sdk}\build-tools\{build_tools}\apksigner.bat
{sdk}\build-tools\{build_tools}\zipalign.exe

WHY DOUBLE-CLICKING sdkmanager.bat DOES NOTHING
===============================================
sdkmanager.bat is not a graphical installer. It is a command-line tool. It needs arguments such as --version, --list, --licenses, or a package name.

GRADLE / gradlew.bat
====================
Gradle is the build program. It reads build.gradle files in the app source-code folder and asks the Android SDK tools to create an APK.

Two ways to run Gradle:
1) Project wrapper: gradlew.bat inside the app source-code folder. This is best when it exists.
2) Global Gradle: a separate program such as {gradle_exe}. This is needed when the project has no gradlew.bat.

Your selected Gradle ZIP:
{gradle_zip}

Gradle install folder:
{gradle_root}

Selected global Gradle program:
{gradle_exe}

For the example project created by this GUI, Gradle 8.9 is the correct default here because your project reported: Minimum supported Gradle version is 8.9. Use JDK 17 or 21 for Gradle 8.9. Java 25 can work for sdkmanager but can fail with Gradle/Groovy errors such as Unsupported class file major version 69.

After global Gradle works, button 22 can create gradlew.bat inside the project. Then later builds can use the project wrapper.

DIRECT DOWNLOADS / SOURCE PAGES
===============================
JDK 17+ page:
{TEMURIN_DOWNLOADS}

Direct JDK 17 Windows x64 installer:
{TEMURIN_JDK17_WIN_X64_INSTALLER}

Direct JDK 21 Windows x64 installer:
{TEMURIN_JDK21_WIN_X64_INSTALLER}

Android command-line tools Windows ZIP:
{ANDROID_CMDLINE_WIN_ZIP}

Gradle 8.9 binary ZIP:
{GRADLE_89_BIN_ZIP}

Gradle install documentation:
{GRADLE_INSTALL}

Downloaded ZIP selected here:
{self.cmdline_tools_zip.get().strip() or '(empty)'}
""".strip()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for line in text.splitlines(True):
            tag = None
            stripped = line.strip()
            if stripped.isupper() and len(stripped) > 5:
                tag = "h"
            if "Correct example" in line or "You do not need" in line or "fixed" in line:
                tag = "ok"
            if "Wrong examples" in line or "Java version 17" in line or "not" in line.lower() and "not" in stripped[:20].lower():
                tag = tag or "warn"
            if stripped.startswith('"') or "\\" in line or stripped.startswith("http") or stripped.startswith("sdkmanager"):
                tag = tag or "cmd"
            self.text.insert("end", line, tag)
        self.text.configure(state="disabled")

    def _sdkmanager_windows(self) -> str:
        configured = clean_cmd_text(self.sdkmanager.get()) or clean_cmd_text(self.state.config.get("sdkmanager_exe", ""))
        if configured:
            return configured
        sdk = clean_cmd_text(self.sdk_root.get()) or clean_cmd_text(self.state.config.get("android_sdk_root_windows", ""))
        return find_sdk_tool(sdk, "sdkmanager") or "sdkmanager"

    def _sdk_root(self) -> str:
        return clean_cmd_text(self.sdk_root.get()) or r"C:\Android\Sdk"

    def _android_platform_id(self) -> str:
        """Return the human-friendly platform folder name, for example android-35.

        The user may type 35, android-35, platforms;android-35, or platforms/android-35.
        sdkmanager needs platforms;android-35, while the installed folder is
        C:\\Android\\Sdk\\platforms\\android-35.
        """
        raw = clean_cmd_text(self.android_platform.get()).strip() or "android-35"
        raw = raw.replace("/", ";").replace("\\", ";")
        raw_lower = raw.lower()
        if raw_lower.startswith("platforms;"):
            raw = raw.split(";", 1)[1].strip() or "android-35"
        if raw.isdigit():
            raw = f"android-{raw}"
        if raw.lower().startswith("android") and not raw.lower().startswith("android-"):
            raw = raw.replace("android", "android-", 1)
        return raw

    def _android_platform_package(self) -> str:
        """Return the exact sdkmanager package name, for example platforms;android-35."""
        return f"platforms;{self._android_platform_id()}"

    def _sdk_packages(self) -> list[str]:
        build_tools = self.build_tools_version.get().strip() or "35.0.0"
        return ["platform-tools", self._android_platform_package(), f"build-tools;{build_tools}"]

    def _env(self) -> dict:
        self.save_settings()
        return make_windows_env(self.state.config)

    def _sdk_cmd(self, *args: str) -> list[str]:
        return [self._sdkmanager_windows(), f"--sdk_root={self._sdk_root()}", *args]

    def _sdk_script(self, *args: str, show_java: bool = True) -> str:
        setup = windows_env_setup_script(self.state.config)
        sdkmanager_path = clean_cmd_text(self._sdkmanager_windows())
        sdkmanager = quote_cmd_arg(sdkmanager_path)
        sdk_root_arg = quote_cmd_arg(f"--sdk_root={clean_cmd_text(self._sdk_root())}")
        quoted_args = " ".join(quote_cmd_arg(a) for a in args)
        pieces = []
        if setup:
            pieces.append(setup)
        if show_java:
            pieces.extend([
                "echo JAVA_HOME=%JAVA_HOME%",
                "echo First java.exe visible to this command:",
                "where java",
                "java -version",
            ])
        # sdkmanager.bat is a batch file. In a longer cmd.exe chain, use CALL so
        # cmd.exe invokes the batch file and then returns to the GUI command chain.
        pieces.append(f"call {sdkmanager} {sdk_root_arg}" + (f" {quoted_args}" if quoted_args else ""))
        return " && ".join(pieces)

    def _run_sdkmanager(self, title: str, args: list[str], input_text: str | None = None, after=None) -> None:
        self.save_settings()
        ok, messages = self._cmdline_layout_details()
        if not ok:
            for level, message in messages:
                self.state.log(message, level)
            self.state.log("sdkmanager was not launched because the command-line tools folder is incomplete.", "ERROR")
            self.state.log("Select the downloaded command-line tools ZIP, then press Extract / repair command-line tools ZIP layout.", "WARN")
            return
        script = self._sdk_script(*args)

        def worker() -> None:
            self.state.log(f"Using JAVA_HOME: {self.state.config.get('java_home', '') or '(empty)'}", "INFO")
            self.state.log(f"Using java.exe: {self.state.config.get('java_exe', '') or '(from PATH)'}", "INFO")
            self.state.log("Running sdkmanager through cmd.exe after forcing JAVA_HOME and PATH.", "INFO")
            rc = run_windows_script_streaming(script, self.state, input_text=input_text)
            if rc == 0 and after:
                after()

        self.state.run_in_thread(title, worker)

    def open_windows_zip(self) -> None:
        webbrowser.open(ANDROID_CMDLINE_WIN_ZIP)
        self.state.log("Opened the direct Windows command-line tools ZIP URL.", "INFO")

    def create_sdk_folders(self) -> None:
        self.save_settings()
        sdk = Path(self._sdk_root())
        for rel in ["cmdline-tools", "platform-tools", "build-tools", "platforms"]:
            (sdk / rel).mkdir(parents=True, exist_ok=True)
        self.state.log(f"Created/reused SDK folder structure under: {sdk}", "OK")
        self.state.log("The cmdline-tools\\latest folder is now created only by the ZIP repair button, so an empty latest folder does not confuse verification.", "INFO")
        self.refresh_text()

    def _find_extracted_cmdline_root(self, temp_root: Path) -> Path | None:
        # The official ZIP normally extracts as: cmdline-tools/bin, cmdline-tools/lib, source.properties.
        # We search for the folder that contains bin/sdkmanager.bat and lib/*.jar.
        candidates: list[Path] = []
        for sm in temp_root.rglob("sdkmanager.bat"):
            if sm.parent.name.lower() == "bin":
                candidates.append(sm.parent.parent)
        for candidate in candidates:
            lib = candidate / "lib"
            if lib.exists() and list(lib.glob("*.jar")):
                return candidate
        return candidates[0] if candidates else None

    def _copy_cmdline_tree(self, source: Path, target: Path, overwrite: bool = True) -> tuple[bool, list[str]]:
        """Copy command-line tools files without deleting the target first.

        This avoids the WinError 32 problem from a locked file in an existing broken
        cmdline-tools\\latest folder. If a file is locked, the copy continues and
        reports the failure instead of destroying the partially repaired folder.
        """
        errors: list[str] = []
        for src in source.rglob("*"):
            rel = src.relative_to(source)
            dst = target / rel
            try:
                if src.is_dir():
                    dst.mkdir(parents=True, exist_ok=True)
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if dst.exists() and not overwrite:
                        continue
                    shutil.copy2(src, dst)
            except Exception as exc:
                errors.append(f"{rel}: {exc}")
        return len(errors) == 0, errors

    def _cmdline_root_is_complete(self, root: Path) -> tuple[bool, list[str]]:
        problems: list[str] = []
        sm = root / "bin" / "sdkmanager.bat"
        lib = root / "lib"
        source_props = root / "source.properties"
        if not sm.exists():
            problems.append(f"missing {sm}")
        jars = list(lib.rglob("*.jar")) if lib.exists() else []
        if not jars:
            problems.append(f"missing JAR files under {lib}")
        if not source_props.exists():
            problems.append(f"missing {source_props}")
        return not problems, problems

    def extract_cmdline_tools_zip(self) -> None:
        self.save_settings()
        zip_path_text = clean_cmd_text(self.cmdline_tools_zip.get())
        if not zip_path_text:
            self.state.log("No command-line tools ZIP selected. Use button 6 first.", "ERROR")
            return
        zip_path = Path(zip_path_text)
        if not zip_path.exists():
            self.state.log(f"Command-line tools ZIP not found: {zip_path}", "ERROR")
            return

        sdk = Path(self._sdk_root())
        cmdline_parent = sdk / "cmdline-tools"
        target_latest = cmdline_parent / "latest"
        sdk.mkdir(parents=True, exist_ok=True)
        cmdline_parent.mkdir(parents=True, exist_ok=True)

        try:
            with tempfile.TemporaryDirectory(prefix="apk_builder_cmdtools_") as tmp:
                tmp_root = Path(tmp)
                self.state.log(f"Extracting command-line tools ZIP: {zip_path}", "INFO")
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(tmp_root)

                source = self._find_extracted_cmdline_root(tmp_root)
                if source is None:
                    self.state.log("Could not find bin\\sdkmanager.bat inside the ZIP.", "ERROR")
                    self.state.log("The selected ZIP does not look like the Android command-line tools Windows ZIP.", "WARN")
                    return

                ok_source, source_problems = self._cmdline_root_is_complete(source)
                if not ok_source:
                    self.state.log(f"Found sdkmanager.bat under {source}, but the extracted ZIP is incomplete.", "ERROR")
                    for problem in source_problems:
                        self.state.log(problem, "WARN")
                    self.state.log("Select the full Windows command-line tools ZIP, not a manually copied bin folder.", "WARN")
                    return

                self.state.log("Repair strategy 1: copy/overlay files into cmdline-tools\\latest without deleting the old folder.", "INFO")
                ok_copy, copy_errors = self._copy_cmdline_tree(source, target_latest, overwrite=True)
                ok_latest, latest_problems = self._cmdline_root_is_complete(target_latest)

                chosen_root = target_latest if ok_latest else None
                if ok_copy and ok_latest:
                    self.state.log(f"Command-line tools repaired in standard folder: {target_latest}", "OK")
                else:
                    self.state.log("Standard latest folder could not be fully repaired. Windows may be locking old files there.", "WARN")
                    for err in copy_errors[:8]:
                        self.state.log(f"Copy warning: {err}", "WARN")
                    if len(copy_errors) > 8:
                        self.state.log(f"... {len(copy_errors) - 8} more copy warning(s)", "WARN")
                    for problem in latest_problems:
                        self.state.log(f"latest problem: {problem}", "WARN")

                    stamp = __import__("time").strftime("%Y%m%d_%H%M%S")
                    alt_target = cmdline_parent / f"latest_gui_{stamp}"
                    self.state.log(f"Repair strategy 2: create a clean unlocked command-line tools folder: {alt_target}", "INFO")
                    shutil.copytree(source, alt_target)
                    ok_alt, alt_problems = self._cmdline_root_is_complete(alt_target)
                    if not ok_alt:
                        self.state.log("Clean versioned repair folder is still incomplete.", "ERROR")
                        for problem in alt_problems:
                            self.state.log(problem, "WARN")
                        return
                    chosen_root = alt_target
                    self.state.log(f"Command-line tools installed into clean folder: {alt_target}", "OK")
                    self.state.log("This is valid. The GUI will use this folder directly even if cmdline-tools\\latest remains broken or locked.", "OK")

                sm = chosen_root / "bin" / "sdkmanager.bat"
                self.sdkmanager.set(str(sm))
                self.state.config["sdkmanager_exe"] = str(sm)
                self.state.config["cmdline_tools_zip"] = str(zip_path)
                self.state.save_config()
                self.state.notify_config_changed()
                self.state.log(f"Selected sdkmanager.bat is now: {sm}", "OK")
                self.verify_cmdline_layout()
        except zipfile.BadZipFile:
            self.state.log(f"Not a valid ZIP file: {zip_path}", "ERROR")
        except Exception as exc:
            self.state.log(f"Could not extract command-line tools ZIP: {exc}", "ERROR")

    def autofill_sdkmanager_only(self) -> None:
        sdk = self._sdk_root()
        found = find_sdk_tool(sdk, "sdkmanager")
        if found:
            self.sdkmanager.set(found)
            self.state.config["sdkmanager_exe"] = found
            self.state.save_config()

    def _cmdline_root_from_sdkmanager(self, sdkmanager_path: str) -> Path | None:
        text = clean_cmd_text(sdkmanager_path)
        if not text:
            return None
        p = Path(text)
        if p.name.lower() != "sdkmanager.bat" or p.parent.name.lower() != "bin":
            return None
        return p.parent.parent

    def _cmdline_layout_details(self) -> tuple[bool, list[tuple[str, str]]]:
        """Validate the selected command-line tools folder.

        v16 accepts both the standard folder:
            C:\\Android\\Sdk\\cmdline-tools\\latest\\bin\\sdkmanager.bat
        and a clean repaired folder such as:
            C:\\Android\\Sdk\\cmdline-tools\\latest_gui_YYYYMMDD_HHMMSS\\bin\\sdkmanager.bat
        This is necessary when Windows locks the old broken latest folder.
        """
        sdk = Path(self._sdk_root())
        selected_root = self._cmdline_root_from_sdkmanager(self.sdkmanager.get() or self.state.config.get("sdkmanager_exe", ""))
        latest_root = sdk / "cmdline-tools" / "latest"
        cmdline_parent = sdk / "cmdline-tools"

        candidate_roots: list[Path] = []
        if selected_root:
            candidate_roots.append(selected_root)
        candidate_roots.append(latest_root)
        if cmdline_parent.exists():
            for sm in cmdline_parent.glob("*/bin/sdkmanager.bat"):
                root = sm.parent.parent
                if root not in candidate_roots:
                    candidate_roots.append(root)

        messages: list[tuple[str, str]] = []
        best_root: Path | None = None
        for root in candidate_roots:
            if not root:
                continue
            sm = root / "bin" / "sdkmanager.bat"
            lib = root / "lib"
            source_props = root / "source.properties"
            jars = list(lib.rglob("*.jar")) if lib.exists() else []
            complete = sm.exists() and bool(jars) and source_props.exists()
            label = "selected" if selected_root and root == selected_root else ("standard latest" if root == latest_root else "alternate")
            messages.append(("OK" if complete else "WARN", f"Checking {label} command-line tools folder: {root}"))
            messages.append(("OK" if sm.exists() else "ERROR", f"{'FOUND' if sm.exists() else 'MISSING'} sdkmanager.bat: {sm}"))
            messages.append(("OK" if jars else "ERROR", f"{'FOUND' if jars else 'MISSING'} lib JAR files: {lib} ({len(jars)} found)"))
            messages.append(("OK" if source_props.exists() else "WARN", f"{'FOUND' if source_props.exists() else 'MISSING'} source.properties: {source_props}"))
            if complete and best_root is None:
                best_root = root
                break

        common_wrong = sdk / "cmdline-tools" / "cmdline-tools" / "bin" / "sdkmanager.bat"
        if common_wrong.exists():
            messages.append(("WARN", f"Common wrong nested layout also exists: {common_wrong}"))
            messages.append(("WARN", "If repair still fails, browse to the original ZIP and use Extract / repair command-line tools ZIP layout."))

        if best_root is not None:
            sm = best_root / "bin" / "sdkmanager.bat"
            self.sdkmanager.set(str(sm))
            self.state.config["sdkmanager_exe"] = str(sm)
            self.state.save_config()
            self.state.notify_config_changed()
            messages.append(("OK", f"Using sdkmanager from: {sm}"))
            return True, messages

        messages.append(("ERROR", "No complete command-line tools folder was found. Use the ZIP repair button. If latest is locked, v16 will create and use a clean latest_gui_* folder."))
        return False, messages

    def verify_cmdline_layout(self) -> None:
        self.save_settings()
        ok, messages = self._cmdline_layout_details()
        for level, message in messages:
            self.state.log(message, level)
        if ok:
            self.state.log("Command-line tools installation is complete enough to run sdkmanager.", "OK")
        else:
            self.state.log("Command-line tools installation is incomplete. Select the downloaded ZIP and press Extract / repair command-line tools ZIP layout.", "ERROR")
        self.refresh_text()

    def _extract_java_major(self, output: str) -> int | None:
        text = output or ""
        m = re.search(r'version\s+"(\d+)(?:\.(\d+))?', text)
        if not m:
            m = re.search(r'openjdk\s+(\d+)(?:\.(\d+))?', text, re.IGNORECASE)
        if not m:
            return None
        first = int(m.group(1))
        if first == 1 and m.group(2):
            return int(m.group(2))
        return first

    def _verify_java_command(self, java_path: str | None = None, use_env: bool = False) -> tuple[int | None, str, int]:
        if use_env:
            setup = windows_env_setup_script(self.state.config)
            script = (setup + " && " if setup else "") + "where java && java -version"
            result = run_windows_script_capture(script, timeout=25)
        else:
            cmd = [java_path or "java", "-version"]
            result = run_capture(cmd, timeout=20)
        major = self._extract_java_major(result.output)
        return major, result.output, result.returncode

    def _is_gradle_friendly_java_major(self, major: int | None) -> bool:
        # Gradle 8.9 is a good Android build choice here, but it should be run with JDK 17-21.
        # Java 25 can run sdkmanager, but it is too new for many Gradle/Groovy combinations.
        return major is not None and 17 <= major <= 21

    def _warn_if_java_too_new_for_gradle(self, major: int | None) -> None:
        if major is not None and major > 21:
            self.state.log(
                f"Java {major} is OK for sdkmanager, but it is too new for Gradle 8.9. Install/select JDK 17 or 21 before building the APK.",
                "WARN",
            )

    def explain_gradle_java(self) -> None:
        self.refresh_text()
        self.state.log("Gradle 8.9 should be run with JDK 17 or 21 for this Android project. Java 25 can pass sdkmanager checks but can break Gradle.", "WARN")
        messagebox.showinfo(
            "Java for Gradle",
            "Your Android SDK tools can run with Java 25, but Gradle 8.9 should use JDK 17 or 21.\n\n"
            "Install Temurin JDK 17 or 21, then select its JAVA_HOME and java.exe in this tab before verifying Gradle."
        )


    def open_jdk17_installer(self) -> None:
        webbrowser.open(TEMURIN_JDK17_WIN_X64_INSTALLER)
        self.state.log("Opened direct Eclipse Temurin JDK 17 Windows x64 installer URL.", "INFO")
        self.state.log("After installation, press Auto-detect JDK 17/21 only.", "INFO")

    def open_jdk21_installer(self) -> None:
        webbrowser.open(TEMURIN_JDK21_WIN_X64_INSTALLER)
        self.state.log("Opened direct Eclipse Temurin JDK 21 Windows x64 installer URL.", "INFO")
        self.state.log("After installation, press Auto-detect JDK 17/21 only.", "INFO")

    def _selected_java_major_for_gradle(self) -> tuple[int | None, str]:
        self.save_settings()
        major, output, rc = self._verify_java_command(use_env=True)
        return major, output

    def verify_java_for_gradle(self) -> bool:
        major, output = self._selected_java_major_for_gradle()
        self.state.log("Checking selected Java for Gradle 8.9.", "INFO")
        for line in output.splitlines():
            self.state.log(line, "OUT")
        if major is None:
            self.state.log("Could not determine Java version for Gradle.", "ERROR")
            return False
        if 17 <= major <= 21:
            self.state.log(f"Java {major} is compatible with this Gradle 8.9 workflow.", "OK")
            return True
        if major > 21:
            self.state.log(f"Java {major} is too new for Gradle 8.9 in this Android project.", "ERROR")
            self.state.log("This is the cause of errors like: Unsupported class file major version 69.", "ERROR")
            self.state.log("Fix: install/select JDK 17 or JDK 21, then verify Gradle again.", "WARN")
            messagebox.showerror(
                "Wrong Java for Gradle",
                f"Java {major} is selected. Gradle 8.9 should use JDK 17 or 21 here.\n\n"
                "Your SDK tools can use Java 25, but Gradle failed with Unsupported class file major version 69.\n\n"
                "Install Temurin JDK 17 or 21, then press Auto-detect JDK 17/21 only."
            )
            return False
        self.state.log(f"Java {major} is too old. Gradle/Android Gradle Plugin need JDK 17+.", "ERROR")
        return False

    def auto_detect_gradle_java_only(self) -> None:
        candidates: list[Path] = []
        common_roots = [
            Path(r"C:\Program Files\Eclipse Adoptium"),
            Path(r"C:\Program Files\Java"),
            Path(r"C:\Program Files\Microsoft"),
            Path(r"C:\Program Files\Amazon Corretto"),
            Path(r"C:\Program Files\Zulu"),
        ]
        for root in common_roots:
            if root.exists():
                candidates.extend(root.glob("**/bin/java.exe"))
        good: list[tuple[int, Path]] = []
        seen: set[str] = set()
        for java in candidates:
            key = str(java).lower()
            if key in seen or not java.exists():
                continue
            seen.add(key)
            major, output, rc = self._verify_java_command(str(java))
            first = output.splitlines()[0] if output.splitlines() else "no output"
            if 17 <= (major or 0) <= 21:
                self.state.log(f"Gradle-compatible Java candidate: version {major} -> {java}", "OK")
                good.append((major or 0, java))
            elif major:
                self.state.log(f"Ignoring Java {major} for Gradle 8.9: {java} -> {first}", "WARN")
        if not good:
            self.state.log("No JDK 17 or JDK 21 was found. Use the direct JDK 17/21 installer button first.", "ERROR")
            messagebox.showwarning(
                "JDK 17/21 not found",
                "I could not find JDK 17 or JDK 21.\n\n"
                "Install Temurin JDK 17 or 21, then press Auto-detect JDK 17/21 only again."
            )
            return
        # Prefer JDK 21, then JDK 17.
        best = sorted(good, key=lambda x: x[0], reverse=True)[0]
        java = best[1]
        self.java_exe.set(str(java))
        if java.parent.name.lower() == "bin":
            self.java_home.set(str(java.parent.parent))
        self.save_settings()
        self.status.set(f"Gradle-compatible Java {best[0]} selected")
        self.state.log(f"Selected JDK {best[0]} for Gradle: {java}", "OK")
        self.refresh_text()

    def auto_detect_java(self) -> None:
        candidates: list[Path] = []
        configured = self.java_exe.get().strip()
        if configured:
            candidates.append(Path(configured))
        common_roots = [
            Path(r"C:\Program Files\Eclipse Adoptium"),
            Path(r"C:\Program Files\Java"),
            Path(r"C:\Program Files\Microsoft"),
            Path(r"C:\Program Files\Amazon Corretto"),
            Path(r"C:\Program Files\Zulu"),
        ]
        for root in common_roots:
            if root.exists():
                candidates.extend(root.glob("**/bin/java.exe"))
        seen = set()
        gradle_friendly: list[tuple[int, Path]] = []
        sdkmanager_only: list[tuple[int, Path]] = []
        for java in candidates:
            if java in seen or not java.exists():
                continue
            seen.add(java)
            major, output, rc = self._verify_java_command(str(java))
            detail = output.splitlines()[0] if output.splitlines() else "no output"
            if major is None:
                self.state.log(f"Java candidate failed: {java} -> {detail}", "WARN")
                continue
            if self._is_gradle_friendly_java_major(major):
                self.state.log(f"Java candidate: version {major} -> {java} (good for sdkmanager and Gradle 8.9)", "OK")
                gradle_friendly.append((major, java))
            elif major >= 17:
                self.state.log(f"Java candidate: version {major} -> {java} (OK for sdkmanager, too new for Gradle 8.9)", "WARN")
                sdkmanager_only.append((major, java))
            else:
                self.state.log(f"Java candidate: version {major} -> {java} (too old)", "WARN")
        if gradle_friendly:
            # Prefer JDK 21 over 17 when both exist, but avoid Java 22+ for Gradle 8.9.
            best = sorted(gradle_friendly, key=lambda x: x[0], reverse=True)[0]
        elif sdkmanager_only:
            best = sorted(sdkmanager_only, key=lambda x: x[0], reverse=True)[0]
            self.state.log("Only Java 22+ was found. Install JDK 17 or 21 before building with Gradle 8.9.", "WARN")
        else:
            best = None
        if best:
            java = best[1]
            self.java_exe.set(str(java))
            if java.parent.name.lower() == "bin":
                self.java_home.set(str(java.parent.parent))
            self.save_settings()
            self.status.set(f"Java {best[0]} selected")
            self.state.log(f"Selected Java {best[0]}: {java}", "OK" if self._is_gradle_friendly_java_major(best[0]) else "WARN")
            self._warn_if_java_too_new_for_gradle(best[0])
        else:
            self.state.log("No Java 17+ installation was auto-detected. Install a JDK 17 or 21 first, then browse to it.", "ERROR")
            messagebox.showwarning("Java not found", "No Java 17+ installation was auto-detected. Install JDK 17 or 21 first, then select JAVA_HOME and java.exe.")
        self.refresh_text()

    def auto_detect_everything(self) -> None:
        self.auto_detect_java()
        self.autofill_sdkmanager_only()
        self.autofill_sdk_tools(log=True)
        self._autofill_gradle_from_install_root(log=True)
        self.refresh_text()

    def verify_selected_java(self) -> None:
        self.save_settings()
        java = self.java_exe.get().strip()
        if not java and self.java_home.get().strip():
            java_path = Path(self.java_home.get().strip()) / "bin" / "java.exe"
            if java_path.exists():
                java = str(java_path)
                self.java_exe.set(java)
                self.save_settings()
        if not java:
            self.state.log("No java.exe selected. Use Auto-detect Java or Browse java.exe.", "ERROR")
            return
        major, output, rc = self._verify_java_command(java)
        for line in output.splitlines():
            self.state.log(line, "OUT")
        if major is None:
            self.state.log("Could not read Java version.", "ERROR")
        elif major >= 17:
            self.state.log(f"Selected Java is OK for sdkmanager: version {major}.", "OK")
            if self._is_gradle_friendly_java_major(major):
                self.state.log(f"Selected Java {major} is also good for Gradle 8.9.", "OK")
            else:
                self._warn_if_java_too_new_for_gradle(major)
        else:
            self.state.log(f"Selected Java is too old: version {major}. sdkmanager requires 17 or newer.", "ERROR")

    def verify_java_used_by_sdkmanager(self) -> None:
        self.save_settings()
        major, output, rc = self._verify_java_command(use_env=True)
        self.state.log("Checking the java.exe that sdkmanager will see using the GUI environment.", "INFO")
        self.state.log(f"JAVA_HOME={self.state.config.get('java_home', '') or '(empty)'}", "INFO")
        for line in output.splitlines():
            self.state.log(line, "OUT")
        if major is None:
            self.state.log("The GUI environment still cannot find Java. Select JAVA_HOME/java.exe.", "ERROR")
        elif major >= 17:
            self.state.log(f"sdkmanager will see Java {major}: OK.", "OK")
        else:
            self.state.log(f"sdkmanager will see Java {major}: too old. Select a newer JDK.", "ERROR")

    def run_sdkmanager_version(self) -> None:
        self._run_sdkmanager("sdkmanager version", ["--version"])

    def run_sdkmanager_list(self) -> None:
        self._run_sdkmanager("sdkmanager list", ["--list"])

    def accept_licenses_windows(self) -> None:
        self._run_sdkmanager("Accept SDK licenses Windows", ["--licenses"], input_text="y\n" * 120)

    def install_platform_tools_windows(self) -> None:
        self._run_sdkmanager("Install platform-tools", ["platform-tools"], after=lambda: self.autofill_sdk_tools(log=True))

    def install_platform_windows(self) -> None:
        platform_id = self._android_platform_id()
        platform_package = self._android_platform_package()
        self.state.log(f"Android platform field is {platform_id}; sdkmanager package is {platform_package}.", "INFO")
        self._run_sdkmanager(f"Install {platform_package}", [platform_package], after=lambda: self.autofill_sdk_tools(log=True))

    def install_build_tools_windows(self) -> None:
        build_tools = self.build_tools_version.get().strip() or "35.0.0"
        self._run_sdkmanager(f"Install build-tools;{build_tools}", [f"build-tools;{build_tools}"], after=lambda: self.autofill_sdk_tools(log=True))

    def install_sdk_windows(self) -> None:
        packages = self._sdk_packages()
        self.state.log("Installing SDK packages: " + ", ".join(packages), "INFO")
        self._run_sdkmanager("Install required SDK packages Windows", packages, after=lambda: self.autofill_sdk_tools(log=True))

    def autofill_sdk_tools(self, log: bool = True) -> None:
        self.save_settings()
        sdk = self._sdk_root()
        mapping = {
            "sdkmanager_exe": "sdkmanager",
            "adb_exe": "adb",
            "aapt2_exe": "aapt2",
            "apksigner_exe": "apksigner",
            "zipalign_exe": "zipalign",
        }
        found_count = 0
        for key, tool in mapping.items():
            found = find_sdk_tool(sdk, tool)
            if found:
                self.state.config[key] = found
                if key == "sdkmanager_exe":
                    self.sdkmanager.set(found)
                found_count += 1
                if log:
                    self.state.log(f"Auto-filled {key}: {found}", "OK")
            elif log:
                self.state.log(f"Could not find {tool} under SDK folder: {sdk}", "WARN")
        self.state.save_config()
        if log:
            self.state.log(f"Auto-fill finished: {found_count}/{len(mapping)} SDK tools found.", "OK" if found_count else "WARN")
        self.refresh_text()

    def verify_installed_sdk_tools(self) -> None:
        self.save_settings()
        sdk = self._sdk_root()
        build_tools = self.build_tools_version.get().strip() or "35.0.0"
        platform_id = self._android_platform_id()
        sm = clean_cmd_text(self.sdkmanager.get()) or clean_cmd_text(self.state.config.get("sdkmanager_exe", ""))
        expected = {
            "sdkmanager.bat": Path(sm) if sm else Path(sdk) / "cmdline-tools" / "latest" / "bin" / "sdkmanager.bat",
            "adb.exe": Path(sdk) / "platform-tools" / "adb.exe",
            f"{platform_id} android.jar": Path(sdk) / "platforms" / platform_id / "android.jar",
            "aapt2.exe": Path(sdk) / "build-tools" / build_tools / "aapt2.exe",
            "apksigner.bat": Path(sdk) / "build-tools" / build_tools / "apksigner.bat",
            "zipalign.exe": Path(sdk) / "build-tools" / build_tools / "zipalign.exe",
        }
        ok = 0
        for name, path in expected.items():
            if path.exists():
                ok += 1
                self.state.log(f"FOUND {name}: {path}", "OK")
            else:
                self.state.log(f"MISSING {name}: {path}", "ERROR")
        self.state.log(f"SDK verification complete: {ok}/{len(expected)} files found.", "OK" if ok == len(expected) else "WARN")

    def open_gradle_89_zip(self) -> None:
        webbrowser.open(GRADLE_89_BIN_ZIP)
        self.state.log("Opened the direct Gradle 8.9 binary ZIP URL.", "INFO")

    def _find_extracted_gradle_root(self, temp_root: Path) -> Path | None:
        candidates: list[Path] = []
        for gradle_bat in temp_root.rglob("gradle.bat"):
            if gradle_bat.parent.name.lower() == "bin":
                candidates.append(gradle_bat.parent.parent)
        if not candidates:
            return None
        candidates.sort(key=lambda p: ("gradle-" not in p.name.lower(), p.name.lower()))
        return candidates[0]

    def _autofill_gradle_from_install_root(self, log: bool = True) -> str:
        root = Path(clean_cmd_text(self.gradle_install_root.get()) or r"C:\Gradle")
        candidates = self._find_all_gradle_candidates()

        def version_from_path(path: Path) -> tuple[int, ...]:
            m = re.search(r"gradle-(\d+(?:\.\d+)*)", str(path).lower())
            return tuple(int(part) for part in m.group(1).split(".")) if m else ()

        if log and candidates:
            for cand in sorted(candidates, key=lambda p: version_from_path(p), reverse=True):
                version = version_from_path(cand)
                version_text = ".".join(map(str, version)) if version else "unknown"
                if version and self._gradle_version_at_least(version, (8, 9)):
                    self.state.log(f"Found acceptable gradle.bat under {root}: Gradle {version_text} -> {cand}", "OK")
                else:
                    self.state.log(f"Found gradle.bat under {root}, but it is too old for direct Android build: Gradle {version_text} -> {cand}", "WARN")

        acceptable = [p for p in candidates if self._gradle_version_at_least(version_from_path(p), (8, 9))]
        acceptable.sort(key=lambda p: version_from_path(p), reverse=True)
        if acceptable:
            found = str(acceptable[0])
            self.gradle_exe.set(found)
            self.state.config["gradle_exe"] = found
            self.state.save_config()
            if log:
                self.state.log(f"Auto-filled gradle_exe with Gradle 8.9+ path: {found}", "OK")
            return found

        if candidates:
            # Do not select old Gradle as the normal build Gradle. Keep the field empty,
            # but make the log explicit so the user knows the recursive search did work.
            if log:
                self.state.log("Only old Gradle versions were found. They are not accepted as the global Android build Gradle.", "ERROR")
                self.state.log("Button #22 can still use old Gradle as a bootstrap tool to create a Gradle 8.9 wrapper in an empty temporary project.", "WARN")
                self.state.log("Best fix: download/extract gradle-8.9-bin.zip with buttons 18-20.", "WARN")
            return ""

        if log:
            self.state.log(f"Could not find any gradle.bat under: {root}", "WARN")
        return ""

    def extract_gradle_zip(self) -> None:
        self.save_settings()
        zip_text = clean_cmd_text(self.gradle_zip.get())
        if not zip_text:
            self.state.log("No Gradle ZIP selected. Use button 19 first.", "ERROR")
            return
        zip_path = Path(zip_text)
        if not zip_path.exists():
            self.state.log(f"Gradle ZIP not found: {zip_path}", "ERROR")
            return
        install_root = Path(clean_cmd_text(self.gradle_install_root.get()) or r"C:\Gradle")
        install_root.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix="apk_builder_gradle_") as tmp:
                tmp_root = Path(tmp)
                self.state.log(f"Extracting Gradle ZIP: {zip_path}", "INFO")
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(tmp_root)
                source = self._find_extracted_gradle_root(tmp_root)
                if source is None:
                    self.state.log("Could not find bin\\gradle.bat inside the selected ZIP.", "ERROR")
                    self.state.log("Select the Gradle binary-only ZIP, for example gradle-8.9-bin.zip.", "WARN")
                    return
                m = re.search(r"gradle-(\d+(?:\.\d+)*)", source.name.lower())
                source_version = tuple(int(part) for part in m.group(1).split(".")) if m else None
                if source_version is None:
                    self.state.log(f"Could not determine Gradle version from extracted folder name: {source.name}", "ERROR")
                    self.state.log("Select gradle-8.9-bin.zip or newer, not an older Gradle ZIP.", "WARN")
                    return
                if not self._gradle_version_at_least(source_version, (8, 9)):
                    self.state.log(f"The selected ZIP contains Gradle {'.'.join(map(str, source_version))}, but this project requires Gradle 8.9 or newer.", "ERROR")
                    self.state.log("Use button 18 to download gradle-8.9-bin.zip, then browse that ZIP and extract it.", "WARN")
                    return
                target = install_root / source.name
                if target.exists():
                    self.state.log(f"Gradle folder already exists and will be reused/overwritten where possible: {target}", "WARN")
                for src in source.rglob("*"):
                    rel = src.relative_to(source)
                    dst = target / rel
                    if src.is_dir():
                        dst.mkdir(parents=True, exist_ok=True)
                    else:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                gradle_bat = target / "bin" / "gradle.bat"
                if not gradle_bat.exists():
                    self.state.log(f"Extraction finished but gradle.bat was not found at: {gradle_bat}", "ERROR")
                    return
                self.gradle_exe.set(str(gradle_bat))
                self.state.update_config({
                    "gradle_zip": str(zip_path),
                    "gradle_install_root": str(install_root),
                    "gradle_exe": str(gradle_bat),
                })
                self.state.log(f"Gradle extracted and selected: {gradle_bat}", "OK")
                self.verify_global_gradle()
        except zipfile.BadZipFile:
            self.state.log(f"Not a valid ZIP file: {zip_path}", "ERROR")
        except Exception as exc:
            self.state.log(f"Could not extract Gradle ZIP: {exc}", "ERROR")

    def _parse_gradle_version_from_text(self, output: str) -> tuple[int, ...] | None:
        m = re.search(r"(?im)^\s*Gradle\s+(\d+(?:\.\d+)*)\s*$", output or "")
        if not m:
            return None
        try:
            return tuple(int(part) for part in m.group(1).split("."))
        except Exception:
            return None

    def _gradle_version_at_least(self, version: tuple[int, ...], minimum: tuple[int, ...] = (8, 9)) -> bool:
        max_len = max(len(version), len(minimum))
        v = version + (0,) * (max_len - len(version))
        m = minimum + (0,) * (max_len - len(minimum))
        return v >= m

    def _gradle_path_looks_too_old(self, gradle: str) -> bool:
        normalized = (gradle or "").replace("\\", "/").lower()
        return "gradle-8.7" in normalized or "gradle-8_7" in normalized

    def _find_all_gradle_candidates(self) -> list[Path]:
        """Find every gradle.bat under the selected install folder, including old versions.

        Older GUI versions filtered out Gradle 8.7 before logging it, which made it
        look as if the GUI did not search recursively. In v19 we show what was
        found, then clearly separate Gradle that is acceptable for building
        directly from Gradle that can only be used to bootstrap a wrapper.
        """
        root = Path(clean_cmd_text(self.gradle_install_root.get()) or r"C:\Gradle")
        candidates: list[Path] = []
        if root.exists():
            candidates.extend(root.glob("gradle-*/bin/gradle.bat"))
            candidates.extend(root.glob("**/bin/gradle.bat"))
        unique: list[Path] = []
        seen = set()
        for item in candidates:
            try:
                key = str(item.resolve()).lower()
            except Exception:
                key = str(item).lower()
            if item.exists() and key not in seen:
                seen.add(key)
                unique.append(item)
        return unique

    def _find_bootstrap_gradle(self, log: bool = True) -> str:
        """Find any usable Gradle, including 8.7, for wrapper bootstrapping.

        Important: Gradle 8.7 is too old to load this Android project, but it can
        still run the generic `wrapper` task inside a temporary empty Gradle
        project. We then copy the generated Gradle 8.9 wrapper files into the
        Android project, avoiding the Android plugin version check entirely.
        """
        current = clean_cmd_text(self.gradle_exe.get()) or clean_cmd_text(self.state.config.get("gradle_exe", ""))
        if current and Path(current).exists():
            if log:
                self.state.log(f"Using selected Gradle as bootstrap tool: {current}", "INFO")
            return current
        candidates = self._find_all_gradle_candidates()
        if not candidates:
            if log:
                root = Path(clean_cmd_text(self.gradle_install_root.get()) or r"C:\Gradle")
                self.state.log(f"No gradle.bat found under: {root}", "ERROR")
            return ""
        # Prefer 8.9+, but allow older Gradle only for isolated wrapper creation.
        def score(path: Path):
            m = re.search(r"gradle-(\d+(?:\.\d+)*)", str(path).lower())
            version = tuple(int(part) for part in m.group(1).split(".")) if m else ()
            return (1 if version and self._gradle_version_at_least(version, (8, 9)) else 0, version)
        candidates.sort(key=score, reverse=True)
        chosen = str(candidates[0])
        if log:
            for cand in candidates:
                tag = "OK" if not self._gradle_path_looks_too_old(str(cand)) else "WARN"
                note = "new enough" if tag == "OK" else "old; bootstrap-only"
                self.state.log(f"Found gradle.bat under install folder ({note}): {cand}", tag)
            self.state.log(f"Selected bootstrap Gradle: {chosen}", "INFO")
        return chosen

    def _get_gradle_version(self, gradle: str, log: bool = True) -> tuple[int, ...] | None:
        """Run gradle -v with the selected JDK and return the Gradle version."""
        if not gradle or not Path(gradle).exists():
            if log:
                self.state.log(f"gradle.bat not found: {gradle}", "ERROR")
            return None
        setup = windows_env_setup_script(self.state.config)
        script = (setup + "\n" if setup else "") + f"call {quote_cmd_arg(gradle)} -v"
        result = run_windows_script_capture(script, timeout=60)
        if log:
            for line in (result.output or "").splitlines():
                if line.strip():
                    self.state.log(line, "OUT")
        if result.returncode != 0:
            if log:
                self.state.log(f"Gradle version check failed with exit code {result.returncode}.", "ERROR")
            return None
        version = self._parse_gradle_version_from_text(result.output or "")
        if version is None and log:
            self.state.log("Could not read the Gradle version from gradle -v output.", "ERROR")
        return version

    def _ensure_gradle_89_or_newer(self, gradle: str) -> bool:
        """Prevent the old Gradle 8.7 executable from being used for this project."""
        if self._gradle_path_looks_too_old(gradle):
            self.state.log(f"Selected gradle.bat is Gradle 8.7 and is too old for this project: {gradle}", "ERROR")
            self.state.log("Use buttons 18-20 to download/extract Gradle 8.9, then press 21 Verify global Gradle again.", "WARN")
            return False
        version = self._get_gradle_version(gradle, log=False)
        if version is None:
            self.state.log("Could not verify the selected Gradle version. Use button 20 to extract Gradle 8.9 again.", "ERROR")
            return False
        readable = ".".join(map(str, version))
        if not self._gradle_version_at_least(version, (8, 9)):
            self.state.log(f"Selected Gradle is {readable}, but this project requires Gradle 8.9 or newer.", "ERROR")
            self.state.log("The previous failure came from Gradle 8.7 trying to load the Android plugin before wrapper creation.", "ERROR")
            self.state.log("Fix: download gradle-8.9-bin.zip, extract it, and select C:\\Gradle\\gradle-8.9\\bin\\gradle.bat.", "WARN")
            return False
        self.state.log(f"Selected Gradle {readable} is new enough for this project.", "OK")
        return True

    def verify_global_gradle(self) -> bool:
        self.save_settings()
        gradle = clean_cmd_text(self.gradle_exe.get()) or clean_cmd_text(self.state.config.get("gradle_exe", ""))
        if not gradle:
            gradle = self._autofill_gradle_from_install_root(log=True)
        if not gradle:
            self.state.log("No gradle.bat selected. Download/extract Gradle first, or browse to gradle.bat.", "ERROR")
            return False
        if not Path(gradle).exists():
            self.state.log(f"gradle.bat not found: {gradle}", "ERROR")
            return False
        if not self.verify_java_for_gradle():
            self.state.log("Global Gradle was not verified because the selected Java is not compatible with Gradle 8.9.", "ERROR")
            return False
        if not self._ensure_gradle_89_or_newer(gradle):
            return False
        self.state.log(f"Verifying global Gradle with the selected JDK: {gradle}", "INFO")
        setup = windows_env_setup_script(self.state.config)
        script = (setup + "\n" if setup else "") + (
            "echo JAVA_HOME=%JAVA_HOME%\n"
            "echo First java.exe visible to Gradle:\n"
            "where java\n"
            "java -version\n"
            f"call {quote_cmd_arg(gradle)} -v"
        )
        rc = run_windows_script_streaming(script, self.state)
        if rc == 0:
            self.state.log("Global Gradle is working with the selected JDK and is new enough for this project.", "OK")
            return True
        else:
            self.state.log(f"Global Gradle failed with exit code {rc}.", "ERROR")
            return False

    def _force_wrapper_properties_version(self, project: str, version: str = "8.9") -> None:
        """If a Gradle wrapper properties file exists, force it to the version required by the project."""
        prop = Path(project) / "gradle" / "wrapper" / "gradle-wrapper.properties"
        if not prop.exists():
            return
        try:
            text = prop.read_text(encoding="utf-8", errors="replace")
            new_url = f"https\\://services.gradle.org/distributions/gradle-{version}-bin.zip"
            if "distributionUrl=" in text:
                text = re.sub(r"(?m)^distributionUrl=.*$", f"distributionUrl={new_url}", text)
            else:
                text = text.rstrip() + "\n" + f"distributionUrl={new_url}\n"
            prop.write_text(text, encoding="utf-8")
            self.state.log(f"Gradle wrapper properties forced to Gradle {version}: {prop}", "OK")
        except Exception as exc:
            self.state.log(f"Could not update Gradle wrapper properties: {exc}", "WARN")

    def _create_wrapper_using_isolated_project(self, project: str, bootstrap_gradle: str) -> bool:
        """Create a Gradle 8.9 wrapper without loading the Android project.

        Running `gradle wrapper` inside the Android project can fail if the currently
        installed global Gradle is too old, because the Android plugin is applied
        before the wrapper task runs. This helper runs the wrapper task in a tiny
        temporary Gradle project, then copies the wrapper files into the Android
        source project. That means even Gradle 8.7 can bootstrap a Gradle 8.9
        wrapper without triggering the Android plugin version check.
        """
        if not bootstrap_gradle or not Path(bootstrap_gradle).exists():
            self.state.log("Cannot bootstrap gradlew.bat because no usable gradle.bat was found.", "ERROR")
            return False
        self.state.log("Creating Gradle 8.9 wrapper in an isolated temporary Gradle project.", "INFO")
        if self._gradle_path_looks_too_old(bootstrap_gradle):
            self.state.log(f"Using old Gradle only as a bootstrap tool, not to build the Android project: {bootstrap_gradle}", "WARN")
        try:
            with tempfile.TemporaryDirectory(prefix="apk_builder_wrapper_bootstrap_") as tmp:
                tmp_path = Path(tmp)
                (tmp_path / "settings.gradle").write_text('pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }\ndependencyResolutionManagement { repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS); repositories { google(); mavenCentral() } }\nrootProject.name = "WrapperBootstrap"\n', encoding="utf-8")
                (tmp_path / "build.gradle").write_text("// Empty project used only to generate Gradle wrapper files.\n", encoding="utf-8")
                setup = windows_env_setup_script(self.state.config)
                script = (setup + "\n" if setup else "") + (
                    "echo JAVA_HOME=%JAVA_HOME%\n"
                    "echo First java.exe visible to Gradle:\n"
                    "where java\n"
                    "java -version\n"
                    f"call {quote_cmd_arg(bootstrap_gradle)} wrapper --gradle-version 8.9 --distribution-type bin"
                )
                rc = run_windows_script_streaming(script, self.state, cwd=str(tmp_path))
                if rc != 0:
                    self.state.log("Isolated wrapper generation failed.", "ERROR")
                    return False

                files_to_copy = [
                    (tmp_path / "gradlew.bat", Path(project) / "gradlew.bat"),
                    (tmp_path / "gradlew", Path(project) / "gradlew"),
                    (tmp_path / "gradle" / "wrapper" / "gradle-wrapper.jar", Path(project) / "gradle" / "wrapper" / "gradle-wrapper.jar"),
                    (tmp_path / "gradle" / "wrapper" / "gradle-wrapper.properties", Path(project) / "gradle" / "wrapper" / "gradle-wrapper.properties"),
                ]
                for src, dst in files_to_copy:
                    if not src.exists():
                        self.state.log(f"Expected wrapper file was not created: {src}", "ERROR")
                        return False
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                self._force_wrapper_properties_version(project, "8.9")
                wrapper = Path(project) / "gradlew.bat"
                self.state.config["gradle_wrapper"] = str(wrapper)
                self.state.save_config()
                self.state.notify_config_changed()
                self.state.log(f"Created and selected project wrapper without loading Android plugin: {wrapper}", "OK")
                return True
        except Exception as exc:
            self.state.log(f"Could not create wrapper in isolated temporary project: {exc}", "ERROR")
            return False

    def create_project_gradle_wrapper(self) -> None:
        self.save_settings()
        project = clean_cmd_text(self.state.config.get("project_dir", ""))
        if not project or not Path(project).exists():
            self.state.log("No app source-code folder selected. Use tab 1 or tab 2 first.", "ERROR")
            return

        wrapper = Path(project) / "gradlew.bat"
        gradle = clean_cmd_text(self.gradle_exe.get()) or clean_cmd_text(self.state.config.get("gradle_exe", ""))

        # If a wrapper already exists, it may still point to the old broken Gradle 8.7 distribution.
        # Do not silently accept it; repair the distributionUrl to 8.9.
        if wrapper.exists():
            self._force_wrapper_properties_version(project, "8.9")
            self.state.config["gradle_wrapper"] = str(wrapper)
            self.state.save_config()
            self.state.notify_config_changed()
            self.state.log(f"Project already has gradlew.bat and it was selected: {wrapper}", "OK")
            self.state.log("If the old wrapper was Gradle 8.7, it has been repaired to use Gradle 8.9.", "OK")
            return

        if not self.verify_java_for_gradle():
            self.state.log("Wrapper creation stopped before running Gradle because Java is not compatible.", "ERROR")
            return

        # Normal best path: selected global Gradle is 8.9+.
        if gradle and Path(gradle).exists() and not self._gradle_path_looks_too_old(gradle):
            if self._ensure_gradle_89_or_newer(gradle):
                self.state.log("Creating Gradle wrapper files inside the selected source project using Gradle 8.9+.", "INFO")
                setup = windows_env_setup_script(self.state.config)
                script = (setup + "\n" if setup else "") + (
                    "echo JAVA_HOME=%JAVA_HOME%\n"
                    "echo First java.exe visible to Gradle:\n"
                    "where java\n"
                    "java -version\n"
                    f"call {quote_cmd_arg(gradle)} wrapper --gradle-version 8.9 --distribution-type bin"
                )
                rc = run_windows_script_streaming(script, self.state, cwd=project)
                if rc == 0 and wrapper.exists():
                    self._force_wrapper_properties_version(project, "8.9")
                    self.state.config["gradle_wrapper"] = str(wrapper)
                    self.state.save_config()
                    self.state.notify_config_changed()
                    self.state.log(f"Created and selected project wrapper: {wrapper}", "OK")
                    return
                if rc == 0:
                    self.state.log("Gradle wrapper command finished, but gradlew.bat was not found. Trying isolated wrapper method.", "WARN")
                else:
                    self.state.log("Direct wrapper creation failed. Trying isolated wrapper method so the Android plugin is not loaded by old Gradle.", "WARN")
            else:
                self.state.log("Selected global Gradle is not acceptable for direct Android wrapper creation. Trying isolated wrapper method.", "WARN")

        # Fallback: any Gradle can generate wrapper files in a temporary empty project,
        # then we copy the Gradle 8.9 wrapper into the Android project.
        bootstrap_gradle = self._find_bootstrap_gradle(log=True)
        if not bootstrap_gradle:
            self.state.log("Cannot create gradlew.bat. Download/extract Gradle 8.9, or browse to an existing gradle.bat.", "ERROR")
            return
        if self._create_wrapper_using_isolated_project(project, bootstrap_gradle):
            self.state.log("Gradle wrapper creation finished. The project wrapper will download/use Gradle 8.9 when building.", "OK")
        else:
            self.state.log("Gradle wrapper creation failed even with the isolated method.", "ERROR")

    def open_cmd_at_sdk(self) -> None:
        self.save_settings()
        sdk = Path(self._sdk_root())
        sdk.mkdir(parents=True, exist_ok=True)
        sm = self._sdkmanager_windows()
        packages = " ".join(quote_cmd_arg(p) for p in self._sdk_packages())
        setup = windows_env_setup_script(self.state.config).replace(" && ", " & ")
        startup = (
            f'title APK Builder SDK Command Prompt & '
            f'{setup} & '
            f'cd /d "{sdk}" & '
            f'echo JAVA_HOME=%JAVA_HOME% & '
            f'echo First java.exe visible in this Command Prompt: & '
            f'where java & '
            f'java -version & '
            f'echo. & '
            f'echo Example commands: & '
            f'echo "{sm}" --sdk_root="{sdk}" --version & '
            f'echo "{sm}" --sdk_root="{sdk}" {packages} & '
            f'echo. & '
            f'echo Selected Gradle: {self.gradle_exe.get().strip() or self.state.config.get("gradle_exe", "(empty)")}'
        )
        if os.name == "nt":
            subprocess.Popen(["cmd", "/k", startup])
        else:
            self.state.log("Open Command Prompt is only available on Windows.", "WARN")

    def explain_java_error(self) -> None:
        self.refresh_text()
        self.state.log("The Java 17 error means sdkmanager found no Java or an old Java. Select JDK 17+ and retry with the GUI buttons.", "INFO")

    def explain_sdkmanager(self) -> None:
        self.refresh_text()
        self.state.log("sdkmanager.bat is command-line only. Use buttons 8-13 instead of double-clicking it.", "INFO")

    def explain_gradle(self) -> None:
        self.refresh_text()
        self.state.log("Gradle install order: open gradle-8.9-bin.zip -> save it -> browse the ZIP -> extract it to C:\\Gradle -> verify gradle.bat -> create gradlew.bat wrapper.", "INFO")
        messagebox.showinfo(
            "How to install Gradle",
            "Gradle is the program that reads build.gradle and creates the APK.\n\n"
            "1. Press: Open direct Gradle 8.9 ZIP.\n"
            "2. Save gradle-8.9-bin.zip, usually in Downloads.\n"
            "3. Press: Browse downloaded Gradle ZIP.\n"
            "4. Press: Extract Gradle ZIP + select gradle.bat.\n"
            "5. Press: Verify global Gradle.\n"
            "6. Press: Create gradlew.bat in project.\n\n"
            "Important: use JDK 17 or 21 for Gradle 8.9. Java 25 can fail when Gradle runs."
        )
