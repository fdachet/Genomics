from __future__ import annotations

import os
import shutil
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, ttk

from command_utils import (
    default_android_sdk_root,
    find_on_path,
    find_sdk_tool,
    gradle_wrapper_windows,
    run_capture,
    clean_text_output,
)
from data.components import COMPONENTS, COMPONENT_BY_KEY
from style import COLORS, make_header
from verification import verify_component


class ComponentsTab(ttk.Frame):
    def __init__(self, parent, state):
        super().__init__(parent)
        self.state = state
        self.vars: dict[str, tk.StringVar] = {
            comp["key"]: tk.StringVar(value=str(state.config.get(comp["key"], "")))
            for comp in COMPONENTS
        }
        self.status_labels: dict[str, tk.Label] = {}
        self._updating_from_config = False
        self._build_ui()
        self.state.add_config_listener(self.on_config_changed)
        self.auto_detect(fill_only_empty=True, startup=True)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        make_header(
            self,
            "Components: locations and verification",
            "Use Auto-detect first, then manually browse/select anything still missing.  Use the horizontal scrollbar for long paths on small screens.",
            purple=True,
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))

        toolbar = ttk.Frame(self)
        toolbar.grid(row=1, column=0, sticky="ew", padx=10, pady=6)
        ttk.Button(toolbar, text="Auto-detect / refill missing paths", command=self.auto_detect, style="Accent.TButton").pack(side="left", padx=4)
        ttk.Button(toolbar, text="Save all locations", command=self.save_all, style="Ok.TButton").pack(side="left", padx=4)
        ttk.Button(toolbar, text="Verify all components", command=self.verify_all, style="Warn.TButton").pack(side="left", padx=4)

        # Compact Components tab: no permanent explanation panel and no extra
        # empty frame between the component list and the always-visible log.
        # Long path boxes remain accessible using the horizontal scrollbar.
        table_frame = ttk.LabelFrame(self, text="Locations and verification")
        table_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=(4, 8))
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        canvas = tk.Canvas(table_frame, bg=COLORS["card"], highlightthickness=0)
        vscroll = ttk.Scrollbar(table_frame, orient="vertical", command=canvas.yview)
        hscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=canvas.xview)
        self.rows_frame = ttk.Frame(canvas)
        self._rows_window = canvas.create_window((0, 0), window=self.rows_frame, anchor="nw")
        self.rows_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vscroll.grid(row=0, column=1, sticky="ns")
        hscroll.grid(row=1, column=0, sticky="ew")

        self._make_rows()

    def _make_rows(self) -> None:
        current_category = None
        row = 0
        for comp in COMPONENTS:
            if comp["category"] != current_category:
                current_category = comp["category"]
                label = tk.Label(
                    self.rows_frame,
                    text=current_category,
                    bg="#dbeafe",
                    fg="#1e3a8a",
                    font=("Segoe UI", 10, "bold"),
                    padx=8,
                    pady=5,
                    anchor="w",
                )
                label.grid(row=row, column=0, columnspan=7, sticky="ew", pady=(8, 2))
                row += 1

            ttk.Label(self.rows_frame, text=comp["name"], width=24).grid(row=row, column=0, sticky="w", padx=4, pady=3)
            entry = ttk.Entry(self.rows_frame, textvariable=self.vars[comp["key"]], width=52)
            entry.grid(row=row, column=1, sticky="ew", padx=4, pady=3)
            self.rows_frame.columnconfigure(1, weight=1)

            if comp["kind"] in {"file", "folder"}:
                ttk.Button(
                    self.rows_frame,
                    text="Browse",
                    command=lambda c=comp: self.browse(c),
                ).grid(row=row, column=2, padx=2, pady=3)
            else:
                ttk.Label(self.rows_frame, text="manual").grid(row=row, column=2, padx=2, pady=3)

            ttk.Button(
                self.rows_frame,
                text="Verify",
                command=lambda c=comp: self.verify_one(c),
                style="Ok.TButton",
            ).grid(row=row, column=3, padx=2, pady=3)

            ttk.Button(
                self.rows_frame,
                text="Explain",
                command=lambda c=comp: self.show_component(c),
            ).grid(row=row, column=4, padx=2, pady=3)

            ttk.Button(
                self.rows_frame,
                text="Open",
                command=lambda c=comp: self.open_download(c),
            ).grid(row=row, column=5, padx=2, pady=3)

            status = tk.Label(
                self.rows_frame,
                text="not checked",
                width=14,
                bg=COLORS["soft_info"],
                fg=COLORS["info"],
                font=("Segoe UI", 9, "bold"),
                padx=4,
            )
            status.grid(row=row, column=6, sticky="ew", padx=4, pady=3)
            self.status_labels[comp["key"]] = status
            row += 1

    def browse(self, comp: dict) -> None:
        key = comp["key"]
        if comp["kind"] == "folder":
            path = filedialog.askdirectory(title=f"Select {comp['name']}")
        else:
            path = filedialog.askopenfilename(title=f"Select {comp['name']}")
        if path:
            self.vars[key].set(path)
            self.save_all()
            self.show_component(comp)

    def save_all(self) -> None:
        for key, var in self.vars.items():
            self.state.config[key] = var.get().strip()
        self.state.save_config()
        self.state.log("Component locations saved and shared with other tabs.", "OK")

    def on_config_changed(self, config: dict) -> None:
        """Refresh visible path boxes when another tab changes component paths."""
        self._updating_from_config = True
        try:
            changed = 0
            for key, var in self.vars.items():
                new_value = str(config.get(key, ""))
                if var.get() != new_value:
                    var.set(new_value)
                    changed += 1
            if changed:
                # Refresh the detail panel if it is currently showing a component.
                self.state.log(f"Components tab updated {changed} location box(es) from another tab.", "INFO")
        finally:
            self._updating_from_config = False

    def _set_detected(self, key: str, value: str, fill_only_empty: bool = False) -> int:
        value = str(value or "").strip()
        if not value:
            return 0
        if fill_only_empty and self.vars[key].get().strip():
            return 0
        if self.vars[key].get().strip() == value:
            return 0
        self.vars[key].set(value)
        return 1

    def _java_major_version(self, java_path: str) -> int:
        if not java_path or not Path(java_path).exists():
            return 0
        result = run_capture([java_path, "-version"], timeout=12)
        text = clean_text_output(result.output)
        # Examples: openjdk version "17.0.19" or java version "1.8.0_451"
        import re
        m = re.search(r'version\s+"([0-9]+)(?:\.([0-9]+))?', text)
        if not m:
            return 0
        major = int(m.group(1))
        if major == 1 and m.group(2):
            major = int(m.group(2))
        return major

    def _find_best_java(self) -> tuple[str, str]:
        candidates: list[Path] = []
        current = self.vars.get("java_exe").get().strip() if "java_exe" in self.vars else ""
        if current:
            candidates.append(Path(current))
        for env_key in ("JAVA_HOME",):
            value = os.environ.get(env_key, "")
            if value:
                candidates.append(Path(value) / "bin" / "java.exe")
        for root in [Path("C:/Program Files/Eclipse Adoptium"), Path("C:/Program Files/Java")]:
            if root.exists():
                candidates.extend(sorted(root.glob("*/bin/java.exe")))
        on_path = find_on_path("java") or find_on_path("java.exe")
        if on_path:
            candidates.append(Path(on_path))

        unique: list[Path] = []
        seen = set()
        for c in candidates:
            try:
                key = str(c.resolve()).lower()
            except Exception:
                key = str(c).lower()
            if key not in seen and c.exists():
                unique.append(c)
                seen.add(key)

        scored: list[tuple[int, Path]] = []
        for c in unique:
            major = self._java_major_version(str(c))
            if major:
                scored.append((major, c))
        # For Android Gradle builds, prefer 17 first, then 21. Avoid 25 even if it exists.
        for wanted in (17, 21):
            for major, c in scored:
                if major == wanted:
                    java_home = str(c.parent.parent) if c.parent.name.lower() == "bin" else ""
                    return str(c), java_home
        for major, c in scored:
            if 17 <= major <= 21:
                java_home = str(c.parent.parent) if c.parent.name.lower() == "bin" else ""
                return str(c), java_home
        for major, c in scored:
            if major >= 17:
                java_home = str(c.parent.parent) if c.parent.name.lower() == "bin" else ""
                return str(c), java_home
        return "", ""

    def _gradle_version(self, gradle_path: str) -> tuple[int, int]:
        if not gradle_path or not Path(gradle_path).exists():
            return (0, 0)
        result = run_capture([gradle_path, "-v"], timeout=25)
        import re
        m = re.search(r"Gradle\s+([0-9]+)\.([0-9]+)", clean_text_output(result.output))
        if not m:
            return (0, 0)
        return int(m.group(1)), int(m.group(2))

    def _find_best_gradle(self) -> str:
        candidates: list[Path] = []
        current = self.vars.get("gradle_exe").get().strip() if "gradle_exe" in self.vars else ""
        if current:
            candidates.append(Path(current))
        install_root = self.vars.get("gradle_install_root").get().strip() or r"C:\Gradle"
        root = Path(install_root)
        if root.exists():
            candidates.extend(sorted(root.glob("**/bin/gradle.bat")))
        for name in ("gradle.bat", "gradle"):
            found = find_on_path(name)
            if found:
                candidates.append(Path(found))
        unique: list[Path] = []
        seen = set()
        for c in candidates:
            try:
                key = str(c.resolve()).lower()
            except Exception:
                key = str(c).lower()
            if key not in seen and c.exists():
                unique.append(c)
                seen.add(key)
        scored: list[tuple[tuple[int, int], Path]] = [(self._gradle_version(str(c)), c) for c in unique]
        # Prefer Gradle 8.9+ because current Android projects may require it.
        valid = [(ver, c) for ver, c in scored if ver >= (8, 9)]
        if valid:
            return str(sorted(valid, key=lambda x: x[0], reverse=True)[0][1])
        if scored:
            return str(sorted(scored, key=lambda x: x[0], reverse=True)[0][1])
        return ""

    def _find_download(self, pattern: str) -> str:
        roots = [Path.home() / "Downloads", Path.home() / "Desktop"]
        matches: list[Path] = []
        for root in roots:
            if root.exists():
                matches.extend(root.glob(pattern))
        if not matches:
            return ""
        matches = sorted(matches, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        return str(matches[0])

    def auto_detect(self, fill_only_empty: bool = False, startup: bool = False) -> None:
        changed = 0
        project = self.vars["project_dir"].get().strip() or self.state.config.get("project_dir", "").strip()
        if project:
            changed += self._set_detected("project_dir", project, fill_only_empty)
            wrapper = gradle_wrapper_windows(project)
            if wrapper:
                changed += self._set_detected("gradle_wrapper", wrapper, fill_only_empty)

        java, java_home = self._find_best_java()
        if java:
            changed += self._set_detected("java_exe", java, fill_only_empty)
        if java_home:
            changed += self._set_detected("java_home", java_home, fill_only_empty)

        sdk = self.vars["android_sdk_root_windows"].get().strip() or default_android_sdk_root() or r"C:\Android\Sdk"
        if sdk:
            changed += self._set_detected("android_sdk_root_windows", sdk, fill_only_empty)
            for key, tool in [
                ("sdkmanager_exe", "sdkmanager"),
                ("adb_exe", "adb"),
                ("aapt2_exe", "aapt2"),
                ("apksigner_exe", "apksigner"),
                ("zipalign_exe", "zipalign"),
            ]:
                found = find_sdk_tool(sdk, tool)
                if found:
                    changed += self._set_detected(key, found, fill_only_empty)

        cmd_zip = self._find_download("commandlinetools-win-*.zip")
        if cmd_zip:
            changed += self._set_detected("cmdline_tools_zip", cmd_zip, fill_only_empty)

        gradle_root = self.vars["gradle_install_root"].get().strip() or r"C:\Gradle"
        changed += self._set_detected("gradle_install_root", gradle_root, fill_only_empty)
        gradle = self._find_best_gradle()
        if gradle:
            changed += self._set_detected("gradle_exe", gradle, fill_only_empty)
        gradle_zip = self._find_download("gradle-8.9-bin.zip") or self._find_download("gradle-*.zip")
        if gradle_zip:
            changed += self._set_detected("gradle_zip", gradle_zip, fill_only_empty)

        self.save_all()
        if startup:
            if changed:
                self.state.log(f"Auto-filled {changed} missing component path(s) from common Windows locations and older GUI configs.", "OK")
        else:
            self.state.log("Auto-detection finished. Verify all components next.", "OK")

    def verify_one(self, comp: dict) -> None:
        self.save_all()
        status, detail = verify_component(comp, self.state.config)
        self._set_status(comp["key"], status)
        self.state.log(f"{comp['name']}: {status} - {detail}", status if status in {"OK", "WARN", "ERROR"} else "INFO")

    def verify_all(self) -> None:
        self.save_all()
        self.state.run_in_thread("Verify all components", self._verify_all_worker)

    def _verify_all_worker(self) -> None:
        for comp in COMPONENTS:
            status, detail = verify_component(comp, self.state.config)
            self.state.post(self._set_status, comp["key"], status)
            self.state.log(f"{comp['name']}: {status} - {detail}", status if status in {"OK", "WARN", "ERROR"} else "INFO")

    def _set_status(self, key: str, status: str) -> None:
        label = self.status_labels[key]
        if status == "OK":
            label.configure(text="OK", bg=COLORS["soft_ok"], fg=COLORS["ok"])
        elif status == "WARN":
            label.configure(text="WARNING", bg=COLORS["soft_warn"], fg=COLORS["warn"])
        elif status == "ERROR":
            label.configure(text="ERROR", bg=COLORS["soft_err"], fg=COLORS["err"])
        else:
            label.configure(text=status, bg=COLORS["soft_info"], fg=COLORS["info"])

    def show_component(self, comp: dict, status: str = "", result_detail: str = "") -> None:
        """Open component explanation in a small pop-up instead of keeping
        a permanent empty explanation panel in the Components tab.
        """
        win = tk.Toplevel(self)
        win.title(f"Component help - {comp.get('name', '')}")
        win.geometry("720x520")
        win.minsize(520, 360)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)

        text = tk.Text(win, wrap="word")
        text.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        scroll = ttk.Scrollbar(win, command=text.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8)
        text.configure(yscrollcommand=scroll.set)
        text.tag_configure("h", foreground="#2563eb", font=("Segoe UI", 11, "bold"))
        text.tag_configure("url", foreground="#7c3aed", underline=True)

        text.insert("end", f"{comp['name']}\n", "h")
        text.insert("end", f"Required: {'yes' if comp.get('required') else 'optional'}\n")
        text.insert("end", f"Configuration key / location box: {comp['key']}\n\n")
        text.insert("end", "What it means\n", "h")
        text.insert("end", comp.get("explain", "") + "\n\n")
        text.insert("end", "How to install or locate it\n", "h")
        text.insert("end", comp.get("install", "") + "\n\n")
        text.insert("end", "Download/source\n", "h")
        text.insert("end", comp.get("download", "") + "\n", "url")
        if comp.get("url"):
            text.insert("end", "Open button target: " + comp.get("url", "") + "\n", "url")
        text.insert("end", "\n")
        current = self.vars[comp["key"]].get()
        text.insert("end", "Current value\n", "h")
        text.insert("end", (current or "(empty)") + "\n\n")
        if status:
            text.insert("end", "Last verification\n", "h")
            text.insert("end", f"{status}: {result_detail}\n")
        text.configure(state="disabled")

        buttons = ttk.Frame(win)
        buttons.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        ttk.Button(buttons, text="Close", command=win.destroy).pack(side="right", padx=4)
        if comp.get("url"):
            ttk.Button(buttons, text="Open download/source page", command=lambda: webbrowser.open(comp["url"])).pack(side="right", padx=4)

    def open_download(self, comp: dict) -> None:
        url = comp.get("url", "") or comp.get("download", "")
        if isinstance(url, str) and url.startswith("http"):
            webbrowser.open(url)
        else:
            self.show_component(comp)
            self.state.log(f"No direct web link for {comp.get('name', 'component')}; use Explain for details.", "INFO")
