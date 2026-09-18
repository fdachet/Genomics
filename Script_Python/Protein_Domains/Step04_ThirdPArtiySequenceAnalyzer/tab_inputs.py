# tab_inputs.py
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Optional, Callable

from shared_config import AppConfig
from shared_utils import read_first_fasta_ids, count_fasta_records


class TabInputs(ttk.Frame):
    def __init__(self, parent, cfg: AppConfig, run_all_cb: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self.cfg = cfg
        self.run_all_cb = run_all_cb
        self._build_ui()
        self._load_from_cfg()
        self._refresh_counts()

    def _build_ui(self):
        self.columnconfigure(1, weight=1)

        r = 0

        ttk.Label(self, text="AA FASTA (protein)").grid(row=r, column=0, sticky="w", padx=10, pady=(10, 4))
        self.var_aa = tk.StringVar()
        ttk.Entry(self, textvariable=self.var_aa).grid(row=r, column=1, sticky="ew", padx=10, pady=(10, 4))
        ttk.Button(self, text="Browse", command=self._browse_aa).grid(row=r, column=2, padx=10, pady=(10, 4))
        ttk.Button(self, text="Preview IDs", command=self._preview_aa).grid(row=r, column=3, padx=(0, 10), pady=(10, 4))
        self.var_aa_count = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.var_aa_count).grid(row=r, column=4, sticky="w", padx=(0, 10), pady=(10, 4))

        r += 1
        ttk.Label(self, text="NT FASTA (nucleotide)").grid(row=r, column=0, sticky="w", padx=10, pady=4)
        self.var_nt = tk.StringVar()
        ttk.Entry(self, textvariable=self.var_nt).grid(row=r, column=1, sticky="ew", padx=10, pady=4)
        ttk.Button(self, text="Browse", command=self._browse_nt).grid(row=r, column=2, padx=10, pady=4)
        ttk.Button(self, text="Preview IDs", command=self._preview_nt).grid(row=r, column=3, padx=(0, 10), pady=4)
        self.var_nt_count = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.var_nt_count).grid(row=r, column=4, sticky="w", padx=(0, 10), pady=4)

        r += 1
        ttk.Label(self, text="Output directory").grid(row=r, column=0, sticky="w", padx=10, pady=4)
        self.var_out = tk.StringVar()
        ttk.Entry(self, textvariable=self.var_out).grid(row=r, column=1, sticky="ew", padx=10, pady=4)
        ttk.Button(self, text="Browse", command=self._browse_out).grid(row=r, column=2, padx=10, pady=4)

        r += 1
        ttk.Label(self, text="Threads").grid(row=r, column=0, sticky="w", padx=10, pady=(4, 10))
        self.var_threads = tk.StringVar(value="4")
        ttk.Entry(self, textvariable=self.var_threads, width=8).grid(row=r, column=1, sticky="w", padx=10, pady=(4, 10))
        ttk.Button(self, text="Apply", command=self.apply_to_cfg).grid(row=r, column=2, padx=10, pady=(4, 10), sticky="w")

        # Run All
        self.btn_run_all = tk.Button(
            self,
            text="Run All (enabled tabs)",
            command=self._run_all,
            bg="blue",
            fg="white",
            activebackground="royalblue",
            activeforeground="white",
            font=("Segoe UI", 10, "bold"),
        )
        self.btn_run_all.grid(row=r + 1, column=0, padx=(0, 10), pady=(4, 10), sticky="e")

        if self.run_all_cb is None:
            self.btn_run_all.configure(state="disabled")

    def refresh_from_cfg(self):
        self._load_from_cfg()
        self._refresh_counts()

    def _browse_aa(self):
        p = filedialog.askopenfilename(
            title="Select AA FASTA",
            filetypes=[("FASTA", "*.fa *.fasta *.faa *.fsa *.txt *.gz"), ("All", "*.*")],
        )
        if p:
            self.var_aa.set(p)
            self._refresh_counts()

    def _browse_nt(self):
        p = filedialog.askopenfilename(
            title="Select NT FASTA",
            filetypes=[("FASTA", "*.fa *.fasta *.fna *.ffn *.txt *.gz"), ("All", "*.*")],
        )
        if p:
            self.var_nt.set(p)
            self._refresh_counts()

    def _browse_out(self):
        p = filedialog.askdirectory(title="Select output directory")
        if p:
            self.var_out.set(p)

    def _preview_aa(self):
        p = self.var_aa.get().strip()
        if not p:
            return
        ids = read_first_fasta_ids(p, n=30)
        messagebox.showinfo("AA FASTA IDs", "\n".join(ids) if ids else "(none)")

    def _preview_nt(self):
        p = self.var_nt.get().strip()
        if not p:
            return
        ids = read_first_fasta_ids(p, n=30)
        messagebox.showinfo("NT FASTA IDs", "\n".join(ids) if ids else "(none)")

    def _load_from_cfg(self):
        self.var_aa.set(self.cfg.aa_fasta or "")
        self.var_nt.set(self.cfg.nt_fasta or "")
        self.var_out.set(self.cfg.out_dir or "")
        self.var_threads.set(str(self.cfg.threads or 4))

    def _refresh_counts(self):
        aa = self.var_aa.get().strip()
        nt = self.var_nt.get().strip()

        if aa and os.path.isfile(aa):
            n = count_fasta_records(aa)
            self.var_aa_count.set(f"FASTA: {n:,} seq")
        elif aa:
            self.var_aa_count.set("FASTA: (file not found)")
        else:
            self.var_aa_count.set("")

        if nt and os.path.isfile(nt):
            n = count_fasta_records(nt)
            self.var_nt_count.set(f"FASTA: {n:,} seq")
        elif nt:
            self.var_nt_count.set("FASTA: (file not found)")
        else:
            self.var_nt_count.set("")

    def apply_to_cfg(self, silent: bool = False):
        self.cfg.aa_fasta = self.var_aa.get().strip()
        self.cfg.nt_fasta = self.var_nt.get().strip()
        self.cfg.out_dir = self.var_out.get().strip()

        try:
            self.cfg.threads = max(1, int(self.var_threads.get().strip() or "4"))
        except Exception:
            messagebox.showerror("Invalid threads", "Threads must be an integer >= 1.")
            return

        self._refresh_counts()

        if not silent:
            messagebox.showinfo("Applied", "Inputs applied to configuration.")

    def _run_all(self):
        if self.run_all_cb is None:
            messagebox.showerror("Run All", "Run All is not available (no callback wired).")
            return
        self.run_all_cb()
