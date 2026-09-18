# PzDomain_2_on_4_PrepDE_V9.py
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from app_state import AppState
from tab_inputs import InputsTab
from tab_prepde import PrepDETab
from tab_design import DesignTab

APP_TITLE = "StringTie PASS2 → prepDE → Design (IsoformSwitchAnalyzeR) - WSL GUI"
APP_VERSION = "v9"


class PrepDEApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE}  {APP_VERSION}")
        self.geometry("1220x820")
        self.minsize(1050, 700)

        app_dir = os.path.dirname(os.path.abspath(__file__))
        self.state_obj = AppState(app_dir=app_dir)
        self.stop_event = threading.Event()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.tab_inputs = InputsTab(nb, self.state_obj)
        self.tab_prepde = PrepDETab(nb, self.state_obj, stop_event=self.stop_event)
        self.tab_design = DesignTab(nb, self.state_obj)

        self.tab_prepde.set_design_tab(self.tab_design)

        nb.add(self.tab_inputs, text="1) Inputs")
        nb.add(self.tab_prepde, text="2) Run prepDE")
        nb.add(self.tab_design, text="3) Design")

    def _on_close(self):
        if self.state_obj.is_busy:
            if not messagebox.askyesno("Quit", "A task is still running.\n\nQuit anyway?"):
                return
        self.destroy()


def main():
    app = PrepDEApp()
    app.mainloop()


if __name__ == "__main__":
    main()
