import tkinter as tk
from tkinter import ttk


class TabLogs(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.txt = tk.Text(self, wrap="none")
        self.txt.grid(row=0, column=0, sticky="nsew")

        y = ttk.Scrollbar(self, orient="vertical", command=self.txt.yview)
        y.grid(row=0, column=1, sticky="ns")
        self.txt.configure(yscrollcommand=y.set)

        x = ttk.Scrollbar(self, orient="horizontal", command=self.txt.xview)
        x.grid(row=1, column=0, sticky="ew")
        self.txt.configure(xscrollcommand=x.set)

    def append(self, msg: str):
        self.txt.insert("end", msg + "\n")
        self.txt.see("end")
