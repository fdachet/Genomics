from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class LogTab(ttk.Frame):
    def __init__(self, parent, state, compact: bool = False):
        super().__init__(parent)
        self.state = state
        self.compact = compact
        self._build_ui()
        self.state.add_log_listener(self.append_log)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        height = 8 if self.compact else 24
        self.text = tk.Text(self, wrap="word", height=height, undo=False, bg="#f8fafc", fg="#111827", font=("Consolas", 9))
        self.text.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        scroll = ttk.Scrollbar(self, command=self.text.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=4)
        self.text.configure(yscrollcommand=scroll.set)

        toolbar = ttk.Frame(self)
        toolbar.grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 4))
        toolbar.columnconfigure(1, weight=1)

        self.autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text="Auto-scroll", variable=self.autoscroll).grid(row=0, column=0, sticky="w")
        ttk.Label(toolbar, text="Errors and install/build output appear here from every tab.", style="Muted.TLabel").grid(row=0, column=1, sticky="w", padx=8)
        ttk.Button(toolbar, text="Clear log", command=self.clear).grid(row=0, column=2, sticky="e", padx=4)

        self.text.tag_configure("TIME", foreground="#64748b")
        self.text.tag_configure("INFO", foreground="#0369a1")
        self.text.tag_configure("CMD", foreground="#7c3aed")
        self.text.tag_configure("OUT", foreground="#111827")
        self.text.tag_configure("OK", foreground="#15803d")
        self.text.tag_configure("WARN", foreground="#b45309")
        self.text.tag_configure("ERROR", foreground="#b91c1c")

    def append_log(self, timestamp: str, level: str, message: str) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", f"[{timestamp}] ", "TIME")
        tag = level if level in {"INFO", "CMD", "OUT", "OK", "WARN", "ERROR"} else "INFO"
        self.text.insert("end", f"{level:<5} ", tag)
        self.text.insert("end", message + "\n", tag)
        self.text.configure(state="disabled")
        if self.autoscroll.get():
            self.text.see("end")

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
