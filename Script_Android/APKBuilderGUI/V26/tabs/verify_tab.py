from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from data.components import COMPONENTS
from style import make_header
from verification import verify_component


class VerifyTab(ttk.Frame):
    def __init__(self, parent, state):
        super().__init__(parent)
        self.state = state
        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        make_header(
            self,
            "Verify: check every component separately",
            "Each row shows whether that specific tool/folder is usable from this GUI.",
        ).grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))

        buttons = ttk.Frame(self)
        buttons.grid(row=1, column=0, sticky="ew", padx=10, pady=6)
        ttk.Button(buttons, text="Run all verification checks", command=self.verify_all, style="Ok.TButton").pack(side="left", padx=4)
        ttk.Button(buttons, text="Clear results", command=self.clear).pack(side="left", padx=4)

        frame = ttk.LabelFrame(self, text="Verification results")
        frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=8)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(frame, columns=("component", "required", "status", "detail"), show="headings")
        self.tree.heading("component", text="Component")
        self.tree.heading("required", text="Required")
        self.tree.heading("status", text="Status")
        self.tree.heading("detail", text="Detail")
        self.tree.column("component", width=210, anchor="w")
        self.tree.column("required", width=80, anchor="center")
        self.tree.column("status", width=90, anchor="center")
        self.tree.column("detail", width=760, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        scroll = ttk.Scrollbar(frame, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=6)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.tag_configure("OK", foreground="#15803d")
        self.tree.tag_configure("WARN", foreground="#b45309")
        self.tree.tag_configure("ERROR", foreground="#b91c1c")
        self.tree.tag_configure("INFO", foreground="#0369a1")

    def clear(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

    def verify_all(self) -> None:
        self.clear()
        self.state.log("Starting full component verification.", "INFO")
        self.state.run_in_thread("Full verification", self._worker)

    def _worker(self) -> None:
        ok_count = warn_count = error_count = 0
        for comp in COMPONENTS:
            status, detail = verify_component(comp, self.state.config)
            if status == "OK":
                ok_count += 1
            elif status == "WARN":
                warn_count += 1
            elif status == "ERROR":
                error_count += 1
            self.state.post(self._add_result, comp, status, detail)
            self.state.log(f"{comp['name']}: {status} - {detail}", status if status in {"OK", "WARN", "ERROR"} else "INFO")
        self.state.log(f"Verification summary: {ok_count} OK, {warn_count} warnings, {error_count} errors.", "OK" if error_count == 0 else "WARN")

    def _add_result(self, comp: dict, status: str, detail: str) -> None:
        self.tree.insert(
            "",
            "end",
            values=(comp["name"], "yes" if comp.get("required") else "optional", status, detail),
            tags=(status if status in {"OK", "WARN", "ERROR", "INFO"} else "INFO",),
        )
