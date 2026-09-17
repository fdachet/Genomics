from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from command_utils import apply_app_identity_to_project, apply_launcher_icon_to_project, app_name_from_apk_name, get_android_app_label, get_current_application_id, get_current_manifest_icon, gradle_wrapper_windows, list_apks, make_application_id_from_name, project_has_gradle, validate_icon_source
from style import make_header


class ProjectTab(ttk.Frame):
    def __init__(self, parent, state):
        super().__init__(parent)
        self.state = state
        self.project_dir = tk.StringVar(value=state.config.get("project_dir", ""))
        self.output_dir = tk.StringVar(value=state.config.get("output_dir", ""))
        self.output_apk_name = tk.StringVar(value=state.config.get("output_apk_name", ""))
        self.app_icon_file = tk.StringVar(value=state.config.get("app_icon_file", ""))
        self.make_new_application = tk.BooleanVar(value=bool(state.config.get("make_new_application", True)))
        self.application_id_override = tk.StringVar(value=state.config.get("application_id_override", ""))
        self._build_ui()
        if self.project_dir.get().strip():
            self.scan()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        make_header(
            self,
            "Project: choose the app source-code folder, not an APK",
            "The app source-code folder is the unzipped folder containing build.gradle/settings.gradle and usually app/src/main/AndroidManifest.xml.",
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))

        top = ttk.LabelFrame(self, text="Project and output")
        top.grid(row=1, column=0, sticky="ew", padx=10, pady=8)
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="App source-code folder:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(top, textvariable=self.project_dir).grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(top, text="Browse", command=self.browse_project).grid(row=0, column=2, padx=6, pady=4)

        ttk.Label(top, text="APK output folder:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(top, textvariable=self.output_dir).grid(row=1, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(top, text="Browse", command=self.browse_output).grid(row=1, column=2, padx=6, pady=4)

        ttk.Label(top, text="Installed app name / APK filename:").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(top, textvariable=self.output_apk_name).grid(row=2, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(top, text="Use current installed name", command=self.use_installed_app_name).grid(row=2, column=2, padx=6, pady=4)

        ttk.Label(top, text="Unique application ID:").grid(row=3, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(top, textvariable=self.application_id_override).grid(row=3, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(top, text="Generate from name", command=self.generate_application_id).grid(row=3, column=2, padx=6, pady=4)

        ttk.Checkbutton(
            top,
            text="Create a new installed app from this name, not an update of the old app",
            variable=self.make_new_application,
            command=self.save,
        ).grid(row=4, column=0, columnspan=3, sticky="w", padx=6, pady=4)

        ttk.Label(top, text="Launcher icon picture:").grid(row=5, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(top, textvariable=self.app_icon_file).grid(row=5, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(top, text="Browse picture", command=self.browse_icon).grid(row=5, column=2, padx=6, pady=4)

        buttons = ttk.Frame(top)
        buttons.grid(row=6, column=0, columnspan=3, sticky="ew", padx=6, pady=6)
        ttk.Button(buttons, text="Save", command=self.save, style="Accent.TButton").pack(side="left", padx=4)
        ttk.Button(buttons, text="Scan", command=self.scan, style="Ok.TButton").pack(side="left", padx=4)
        ttk.Button(buttons, text="Open project folder", command=lambda: self.open_folder(self.project_dir.get())).pack(side="left", padx=4)
        ttk.Button(buttons, text="Open APK output folder", command=lambda: self.open_folder(self.output_dir.get())).pack(side="left", padx=4)
        ttk.Button(buttons, text="Apply name/new app ID", command=self.apply_identity_now, style="Warn.TButton").pack(side="left", padx=4)
        ttk.Button(buttons, text="Apply icon to project", command=self.apply_icon_now, style="Warn.TButton").pack(side="left", padx=4)

        info = ttk.LabelFrame(self, text="What this means")
        info.grid(row=2, column=0, sticky="nsew", padx=10, pady=8)
        info.rowconfigure(0, weight=1)
        info.columnconfigure(0, weight=1)

        self.text = tk.Text(info, wrap="word", height=20)
        self.text.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        scroll = ttk.Scrollbar(info, command=self.text.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=6)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.tag_configure("h", foreground="#2563eb", font=("Segoe UI", 11, "bold"))
        self.text.tag_configure("ok", foreground="#15803d")
        self.text.tag_configure("warn", foreground="#b45309")
        self.text.tag_configure("err", foreground="#b91c1c")

    def browse_project(self) -> None:
        path = filedialog.askdirectory(title="Select app source-code folder")
        if path:
            self.project_dir.set(path)
            self.save()
            self.scan()

    def browse_output(self) -> None:
        path = filedialog.askdirectory(title="Select APK output folder")
        if path:
            self.output_dir.set(path)
            self.save()

    def browse_icon(self) -> None:
        path = filedialog.askopenfilename(
            title="Select launcher icon picture",
            filetypes=[
                ("Android-compatible picture files", "*.png *.jpg *.jpeg *.webp"),
                ("PNG files", "*.png"),
                ("JPG files", "*.jpg *.jpeg"),
                ("WEBP files", "*.webp"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.app_icon_file.set(path)
            self.save()
            self.state.log(f"Launcher icon picture selected: {path}", "OK")

    def apply_icon_now(self) -> None:
        self.save()
        project = self.project_dir.get().strip()
        icon_file = self.app_icon_file.get().strip()
        if not project:
            self.state.log("Select the app source-code folder before applying an icon.", "ERROR")
            return
        ok, message = apply_launcher_icon_to_project(project, icon_file)
        self.state.log(message, "OK" if ok else "ERROR")
        if ok:
            self.scan()

    def save(self) -> None:
        self.state.config["project_dir"] = self.project_dir.get().strip()
        self.state.config["output_dir"] = self.output_dir.get().strip()
        name = self.output_apk_name.get().strip()
        if name and not name.lower().endswith(".apk"):
            name += ".apk"
            self.output_apk_name.set(name)
        self.state.config["output_apk_name"] = name
        self.state.config["app_icon_file"] = self.app_icon_file.get().strip()
        self.state.config["make_new_application"] = bool(self.make_new_application.get())
        self.state.config["application_id_override"] = self.application_id_override.get().strip()
        if self.project_dir.get().strip() and not self.state.config.get("gradle_wrapper"):
            wrapper = gradle_wrapper_windows(self.project_dir.get().strip())
            if wrapper:
                self.state.config["gradle_wrapper"] = wrapper
        self.state.save_config()
        self.state.log("Project settings saved.", "OK")

    def use_installed_app_name(self) -> None:
        project = self.project_dir.get().strip() or self.state.config.get("project_dir", "").strip()
        if not project:
            self.state.log("Select the app source-code folder first, then the GUI can read the installed app name.", "WARN")
            return
        label = get_android_app_label(project)
        name = label.strip() if label else "app"
        if not name.lower().endswith(".apk"):
            name += ".apk"
        self.output_apk_name.set(name)
        self.state.config["output_apk_name"] = name
        self.state.save_config()
        self.state.log(f"Final copied APK name set from installed app name: {name}", "OK")


    def generate_application_id(self) -> None:
        name = self.output_apk_name.get().strip()
        if not name:
            project = self.project_dir.get().strip() or self.state.config.get("project_dir", "").strip()
            name = get_android_app_label(project) if project else "app"
        app_id = make_application_id_from_name(name)
        self.application_id_override.set(app_id)
        self.save()
        self.state.log(f"Generated unique Android application ID: {app_id}", "OK")

    def apply_identity_now(self) -> None:
        self.save()
        project = self.project_dir.get().strip()
        if not project:
            self.state.log("Select the app source-code folder before applying the app identity.", "ERROR")
            return
        apk_name = self.output_apk_name.get().strip()
        if not apk_name:
            self.state.log("Enter the installed app name / APK filename first.", "ERROR")
            return
        ok, message = apply_app_identity_to_project(
            project,
            apk_name,
            self.application_id_override.get().strip(),
            bool(self.make_new_application.get()),
        )
        self.state.log(message, "OK" if ok else "ERROR")
        if ok:
            # Keep the generated ID visible if the user left the field empty.
            if bool(self.make_new_application.get()) and not self.application_id_override.get().strip():
                self.application_id_override.set(make_application_id_from_name(apk_name))
                self.state.config["application_id_override"] = self.application_id_override.get().strip()
                self.state.save_config()
            self.scan()

    def scan(self) -> None:
        self.save()
        project = self.project_dir.get().strip()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")

        self._line("App source-code folder\n", "h")
        self._line(
            "This is the unzipped Android project folder that Gradle compiles into an APK. "
            "Select the folder that directly contains settings.gradle/build.gradle and the app folder. "
            "It is not the .apk file.\n\n"
        )

        if not project:
            self._line("No project selected.\n", "warn")
            self.text.configure(state="disabled")
            return

        p = Path(project)
        self._line(f"Selected folder: {p}\n")
        installed_label = get_android_app_label(project)
        final_name = self.state.config.get("output_apk_name", "") or (installed_label + ".apk" if installed_label else "app.apk")
        self._line(f"Installed app name found in manifest/resources: {installed_label or 'not found'}\n")
        app_label_from_name = app_name_from_apk_name(final_name, fallback=installed_label or "app")
        current_app_id = get_current_application_id(project)
        generated_app_id = self.application_id_override.get().strip() or make_application_id_from_name(final_name)
        self._line(f"Final copied APK name: {final_name}\n")
        self._line(f"Installed app name that will be applied before build: {app_label_from_name}\n")
        self._line(f"Current Android application ID: {current_app_id or 'not found'}\n")
        if bool(self.make_new_application.get()):
            self._line(f"New Android application ID for separate install: {generated_app_id}\n", "ok")
        else:
            self._line("New Android application ID: not applied; Android may treat the APK as an update.\n", "warn")
        current_icon = get_current_manifest_icon(project)
        self._line(f"Current manifest launcher icon: {current_icon or 'not found'}\n")
        selected_icon = self.app_icon_file.get().strip() or self.state.config.get("app_icon_file", "")
        if selected_icon:
            icon_ok, icon_msg = validate_icon_source(selected_icon)
            self._line(f"Selected icon picture: {selected_icon}\n", "ok" if icon_ok else "err")
            if not icon_ok:
                self._line(f"  {icon_msg}\n", "err")
        else:
            self._line("Selected icon picture: none; existing project icon will be kept.\n")
        if not p.exists():
            self._line("Folder does not exist.\n", "err")
            self.text.configure(state="disabled")
            return

        def exists(rel: str) -> bool:
            return (p / rel).exists()

        checks = [
            (
                "Project settings file",
                ["settings.gradle", "settings.gradle.kts"],
                "required: one of these must exist; .kts is optional when settings.gradle exists",
            ),
            (
                "Root build file",
                ["build.gradle", "build.gradle.kts"],
                "required: one of these must exist; .kts is optional when build.gradle exists",
            ),
            (
                "Windows build launcher",
                ["gradlew.bat"],
                "recommended: lets this GUI build without relying only on global Gradle",
            ),
            (
                "Unix build launcher",
                ["gradlew"],
                "optional on Windows; useful if the same project is later used on Linux/macOS",
            ),
            (
                "Android app build file",
                ["app/build.gradle", "app/build.gradle.kts"],
                "required: one of these must exist; .kts is optional when app/build.gradle exists",
            ),
            (
                "Android manifest",
                ["app/src/main/AndroidManifest.xml"],
                "required: defines app package, label, icon, activities",
            ),
        ]

        self._line("\nImportant project files\n", "h")
        for label, alternatives, note in checks:
            found = [rel for rel in alternatives if exists(rel)]
            if found:
                self._line(f"  OK   {label}: {', '.join(found)}\n", "ok")
                if len(alternatives) > 1:
                    missing = [rel for rel in alternatives if rel not in found]
                    self._line(f"       Not needed here: {', '.join(missing)}\n")
            else:
                tag = "err" if "required" in note else "warn"
                self._line(f"  MISS {label}: expected {' or '.join(alternatives)}\n", tag)
            self._line(f"       {note}\n")

        self._line("\nInterpretation:\n", "h")
        self._line(f"  Gradle project: {'yes' if project_has_gradle(project) else 'not clear'}\n", "ok" if project_has_gradle(project) else "warn")
        if gradle_wrapper_windows(project):
            self._line("  gradlew.bat: found; the Build tab can use the project wrapper.\n", "ok")
        else:
            self._line("  gradlew.bat: not found; use Install -> Create gradlew.bat in project or select global Gradle.\n", "warn")

        apks = list_apks(project)
        self._line(f"\nDetected APK files already present: {len(apks)}\n", "h")
        for apk in apks[:25]:
            self._line(f"  {apk}\n")
        if len(apks) > 25:
            self._line(f"  ... {len(apks) - 25} more\n")

        self._line("\nBuild tasks:\n", "h")
        self._line("  assembleDebug      -> debug APK for testing\n")
        self._line("  assembleRelease    -> release APK; usually needs signing settings\n")
        self._line("  clean assembleDebug -> delete old build output and rebuild debug APK\n")

        self.text.configure(state="disabled")
        self.state.log("Project scan finished.", "OK")

    def _line(self, text: str, tag: str | None = None) -> None:
        self.text.insert("end", text, tag or "")

    def open_folder(self, folder: str) -> None:
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
