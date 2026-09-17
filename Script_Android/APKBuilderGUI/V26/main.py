from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app_state import AppState
from style import apply_style
from tabs.project_tab import ProjectTab
from tabs.components_tab import ComponentsTab
from tabs.install_tab import InstallTab
from tabs.verify_tab import VerifyTab
from tabs.build_tab import BuildTab
from tabs.log_tab import LogTab


APP_TITLE = "APK Builder GUI v26 - Windows Only"


def main() -> int:
    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("1220x850")
    root.minsize(980, 650)

    apply_style(root)

    state = AppState(root)

    main_pane = ttk.PanedWindow(root, orient="vertical")
    main_pane.pack(fill="both", expand=True, padx=6, pady=6)

    notebook_frame = ttk.Frame(main_pane)
    notebook_frame.rowconfigure(0, weight=1)
    notebook_frame.columnconfigure(0, weight=1)

    notebook = ttk.Notebook(notebook_frame)
    notebook.grid(row=0, column=0, sticky="nsew")

    tabs = [
        (ProjectTab(notebook, state), "1. Project"),
        (ComponentsTab(notebook, state), "2. Components"),
        (InstallTab(notebook, state), "3. Install"),
        (VerifyTab(notebook, state), "4. Verify"),
        (BuildTab(notebook, state), "5. Build"),
    ]

    for frame, title in tabs:
        notebook.add(frame, text=title)

    log_outer = ttk.LabelFrame(main_pane, text="Always-visible log")
    log_outer.rowconfigure(0, weight=1)
    log_outer.columnconfigure(0, weight=1)
    log_panel = LogTab(log_outer, state, compact=True)
    log_panel.grid(row=0, column=0, sticky="nsew")

    main_pane.add(notebook_frame, weight=5)
    main_pane.add(log_outer, weight=1)

    state.log("APK Builder GUI v26 started.", "OK")
    state.log("Windows-only APK Builder GUI started.", "OK")
    state.log("The log is visible from every tab. Use tabs left to right: Project -> Components -> Install -> Verify -> Build.", "INFO")
    state.log("This version is Windows-only and uses Windows Java, Android SDK, and Gradle paths.", "INFO")
    state.log("For this project, prefer JDK 17 or 21 for Gradle. Java 25 may work for sdkmanager but may fail when running Gradle 8.9.", "WARN")

    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
