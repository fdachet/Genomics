# tab_inputs.py
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from app_state import AppState
from utils_wsl import list_wsl_distros


def _open_in_explorer(path: str) -> None:
    try:
        if os.path.isdir(path):
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            os.startfile(os.path.dirname(path))  # type: ignore[attr-defined]
    except Exception:
        pass


class InputsTab(ttk.Frame):
    """
    Inputs tab:
      - PASS2 folder
      - Output folder
      - WSL distro / python / prepDE path / read length
    """
    def __init__(self, parent, state: AppState, *args, **kwargs):
        super().__init__(parent)
        self.state = state

        self._build_ui()
        self._load_from_state()
        self._refresh_distros()
        self._refresh_samples_view()
        self._refresh_status()

    def _build_ui(self):
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(2, weight=1)

        # PASS2 folder
        sec_pass2 = ttk.LabelFrame(outer, text="StringTie PASS2 inputs (required)", padding=10)
        sec_pass2.grid(row=0, column=0, columnspan=3, sticky="ew")
        sec_pass2.columnconfigure(1, weight=1)

        ttk.Label(sec_pass2, text="PASS2 folder (Windows):").grid(row=0, column=0, sticky="w")
        self.var_pass2 = tk.StringVar()
        ttk.Entry(sec_pass2, textvariable=self.var_pass2).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(sec_pass2, text="Browse…", command=self._browse_pass2).grid(row=0, column=2, padx=6)

        ttk.Button(sec_pass2, text="Scan PASS2 folder", command=self._scan_pass2).grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(
            sec_pass2,
            text="Checks that each sample GTF header contains BOTH '-e' and '-G' (prepDE requirement).",
            wraplength=900
        ).grid(row=1, column=1, columnspan=2, sticky="w", pady=(8, 0))

        # Samples table
        sec_samples = ttk.LabelFrame(outer, text="Detected samples", padding=10)
        sec_samples.grid(row=1, column=0, columnspan=3, sticky="nsew", pady=(10, 0))
        sec_samples.columnconfigure(0, weight=1)
        sec_samples.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(sec_samples, columns=("sample", "gtf", "status"), show="headings", height=10)
        self.tree.heading("sample", text="Sample")
        self.tree.heading("gtf", text="GTF path (Windows)")
        self.tree.heading("status", text="Status")
        self.tree.column("sample", width=160, anchor="w")
        self.tree.column("gtf", width=640, anchor="w")
        self.tree.column("status", width=300, anchor="w")

        yscroll = ttk.Scrollbar(sec_samples, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")

        # Output folder
        sec_out = ttk.LabelFrame(outer, text="Outputs (required)", padding=10)
        sec_out.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        sec_out.columnconfigure(1, weight=1)

        ttk.Label(sec_out, text="Output folder (Windows):").grid(row=0, column=0, sticky="w")
        self.var_output = tk.StringVar()
        ttk.Entry(sec_out, textvariable=self.var_output).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(sec_out, text="Browse…", command=self._browse_output).grid(row=0, column=2, padx=6)

        self.var_run_folder = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            sec_out,
            text="Create run subfolder (run_YYYYMMDD_HHMMSS)",
            variable=self.var_run_folder
        ).grid(row=1, column=1, columnspan=2, sticky="w", pady=(6, 0))

        # Advanced
        sec_adv = ttk.LabelFrame(outer, text="Advanced (optional)", padding=10)
        sec_adv.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        sec_adv.columnconfigure(1, weight=1)

        ttk.Label(sec_adv, text="WSL distro:").grid(row=0, column=0, sticky="w")
        self.var_distro = tk.StringVar()
        self.cbo_distro = ttk.Combobox(sec_adv, textvariable=self.var_distro, state="readonly", width=28)
        self.cbo_distro.grid(row=0, column=1, sticky="w", padx=6)
        ttk.Button(sec_adv, text="Refresh", command=self._refresh_distros).grid(row=0, column=2, padx=6)

        ttk.Label(sec_adv, text="Python in WSL:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.var_wsl_python = tk.StringVar()
        ttk.Entry(sec_adv, textvariable=self.var_wsl_python, width=18).grid(row=1, column=1, sticky="w", padx=6, pady=(8, 0))
        ttk.Label(sec_adv, text="(usually: python3)").grid(row=1, column=2, sticky="w", pady=(8, 0))

        ttk.Label(sec_adv, text="Read length (-l):").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.var_readlen = tk.StringVar()
        vcmd = (self.register(self._validate_int), "%P")
        ttk.Entry(sec_adv, textvariable=self.var_readlen, width=8, validate="key", validatecommand=vcmd).grid(row=2, column=1, sticky="w", padx=6, pady=(8, 0))
        ttk.Label(sec_adv, text="(bp; per-end length, default 150)").grid(row=2, column=2, sticky="w", pady=(8, 0))

        ttk.Label(sec_adv, text="prepDE.py path (Windows):").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.var_prepde = tk.StringVar()
        ttk.Entry(sec_adv, textvariable=self.var_prepde).grid(row=3, column=1, sticky="ew", padx=6, pady=(8, 0))
        ttk.Button(sec_adv, text="Browse…", command=self._browse_prepde).grid(row=3, column=2, padx=6, pady=(8, 0))

        # Status line (instead of popups)
        self.lbl_status = ttk.Label(outer, text="", anchor="w")
        self.lbl_status.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 0))

        # Auto-sync (silent)
        for v in (self.var_pass2, self.var_output, self.var_distro, self.var_wsl_python, self.var_readlen, self.var_prepde, self.var_run_folder):
            v.trace_add("write", lambda *_: self._on_change())

    def _validate_int(self, proposed: str) -> bool:
        return (proposed == "") or proposed.isdigit()

    def _on_change(self):
        self._sync_to_state()
        self._refresh_status()

    def _load_from_state(self):
        cfg = self.state.cfg
        self.var_pass2.set(cfg.pass2_dir_win or "")
        self.var_output.set(cfg.output_dir_win or "")
        self.var_run_folder.set(bool(cfg.create_run_folder))
        self.var_distro.set(cfg.wsl_distro or "")
        self.var_wsl_python.set(cfg.wsl_python or "python3")
        self.var_prepde.set(cfg.prepde_py_win or "")
        self.var_readlen.set(str(int(getattr(cfg, "read_length", 150) or 150)))

    def _sync_to_state(self):
        cfg = self.state.cfg
        cfg.pass2_dir_win = (self.var_pass2.get() or "").strip()
        cfg.output_dir_win = (self.var_output.get() or "").strip()
        cfg.create_run_folder = bool(self.var_run_folder.get())
        cfg.wsl_distro = (self.var_distro.get() or "").strip()
        cfg.wsl_python = (self.var_wsl_python.get() or "").strip() or "python3"
        cfg.prepde_py_win = (self.var_prepde.get() or "").strip()

        rl = (self.var_readlen.get() or "").strip()
        cfg.read_length = int(rl) if rl.isdigit() and int(rl) > 0 else 150

    def _refresh_status(self):
        cfg = self.state.cfg
        ok = len(self.state.ok_samples())
        total = len(self.state.detected_samples or [])
        issues = total - ok
        self.lbl_status.configure(
            text=f"Samples: {total}  OK: {ok}  Issues: {issues}   |   Read length: {cfg.read_length} bp"
        )

    def _browse_pass2(self):
        d = filedialog.askdirectory(title="Select StringTie PASS2 folder (contains sample subfolders)")
        if d:
            self.var_pass2.set(d)

    def _browse_output(self):
        d = filedialog.askdirectory(title="Select output folder")
        if d:
            self.var_output.set(d)

    def _browse_prepde(self):
        p = filedialog.askopenfilename(
            title="Select prepDE.py",
            filetypes=[("Python", "*.py"), ("All files", "*.*")]
        )
        if p:
            self.var_prepde.set(p)

    def _refresh_distros(self):
        distros = list_wsl_distros()
        values = [""] + [d for d in distros if d]
        self.cbo_distro["values"] = values
        cur = (self.var_distro.get() or "")
        if cur not in values:
            self.var_distro.set("")

    def _scan_pass2(self):
        self._sync_to_state()
        try:
            self.state.scan_pass2_folder()
            self._refresh_samples_view()
            self._refresh_status()
        except Exception as e:
            messagebox.showerror("Scan", str(e))

    def _refresh_samples_view(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        for s in (self.state.detected_samples or []):
            status = ("✅ " if s.ok else "❌ ") + (s.message or "")
            self.tree.insert("", "end", values=(s.sample_id, s.gtf_win, status))
