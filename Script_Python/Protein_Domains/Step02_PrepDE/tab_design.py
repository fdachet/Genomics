# tab_design.py
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from app_state import AppState


def _open_in_explorer(path: str) -> None:
    try:
        if os.path.isdir(path):
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            os.startfile(os.path.dirname(path))  # type: ignore[attr-defined]
    except Exception:
        pass


def _open_file(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.startfile(path)  # type: ignore[attr-defined]
    except Exception:
        pass


def _read_sample_ids_from_matrix(path: str) -> list[str]:
    """
    Read sample IDs from the header row of a prepDE matrix.
    Detect delimiter by comparing ',' vs '\\t' counts in the first line.
    """
    if not path or not os.path.isfile(path):
        return []

    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            header = f.readline()
            if not header:
                return []
            comma = header.count(",")
            tab = header.count("\t")
            delim = "," if comma > tab else "\t"
            cols = [c.strip() for c in header.strip().split(delim)]
            return [c for c in cols[1:] if c]
    except Exception:
        return []


class DesignTab(ttk.Frame):
    """
    Build a minimal design.tsv for IsoformSwitchAnalyzeR:
      sampleID <tab> condition
    """
    def __init__(self, parent, state: AppState, *args, **kwargs):
        super().__init__(parent)
        self.state = state

        self._build_ui()
        self._apply_defaults()

    def _build_ui(self):
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(4, weight=1)

        # Source
        src = ttk.LabelFrame(outer, text="Sample source", padding=10)
        src.grid(row=0, column=0, columnspan=3, sticky="ew")
        src.columnconfigure(1, weight=1)

        self.var_source = tk.StringVar(value="prepde")

        ttk.Radiobutton(src, text="From last PrepDE matrices", value="prepde", variable=self.var_source, command=self._load_samples).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(src, text="From PASS2 folder scan", value="pass2", variable=self.var_source, command=self._load_samples).grid(row=1, column=0, sticky="w")

        self.lbl_source_hint = ttk.Label(src, text="", wraplength=900)
        self.lbl_source_hint.grid(row=0, column=1, rowspan=2, sticky="w", padx=8)

        # Conditions
        cond = ttk.LabelFrame(outer, text="Conditions", padding=10)
        cond.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        cond.columnconfigure(1, weight=1)

        ttk.Label(cond, text="Condition A label:").grid(row=0, column=0, sticky="w")
        self.var_a = tk.StringVar()
        ttk.Entry(cond, textvariable=self.var_a, width=20).grid(row=0, column=1, sticky="w", padx=6)

        ttk.Label(cond, text="Condition B label:").grid(row=0, column=2, sticky="w", padx=(18, 0))
        self.var_b = tk.StringVar()
        ttk.Entry(cond, textvariable=self.var_b, width=20).grid(row=0, column=3, sticky="w", padx=6)

        ttk.Button(cond, text="Assign selected → A", command=lambda: self._assign_selected("A")).grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Button(cond, text="Assign selected → B", command=lambda: self._assign_selected("B")).grid(row=1, column=1, sticky="w", pady=(8, 0))
        ttk.Button(cond, text="Clear assignment", command=self._clear_assignments).grid(row=1, column=2, sticky="w", pady=(8, 0))

        # Output
        out = ttk.LabelFrame(outer, text="Output", padding=10)
        out.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        out.columnconfigure(1, weight=1)

        ttk.Label(out, text="design.tsv path:").grid(row=0, column=0, sticky="w")
        self.var_out = tk.StringVar()
        ttk.Entry(out, textvariable=self.var_out).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(out, text="Browse…", command=self._browse_out).grid(row=0, column=2, padx=6)

        self.btn_write = ttk.Button(out, text="Write design.tsv", command=self._write_design)
        self.btn_write.grid(row=1, column=0, sticky="w", pady=(8, 0))

        self.btn_open = ttk.Button(out, text="Open design.tsv", command=lambda: _open_file(self.var_out.get()))
        self.btn_open.grid(row=1, column=1, sticky="w", pady=(8, 0))

        self.btn_open_folder = ttk.Button(out, text="Open folder", command=lambda: _open_in_explorer(self.var_out.get()))
        self.btn_open_folder.grid(row=1, column=2, sticky="w", pady=(8, 0))

        # Table
        table = ttk.LabelFrame(outer, text="Samples", padding=10)
        table.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(10, 0))
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(table, columns=("sample", "assigned"), show="headings", height=10, selectmode="extended")
        self.tree.heading("sample", text="Sample")
        self.tree.heading("assigned", text="Assigned")
        self.tree.column("sample", width=340, anchor="w")
        self.tree.column("assigned", width=160, anchor="w")

        yscroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")

        # Status
        self.lbl_status = ttk.Label(outer, text="", anchor="w")
        self.lbl_status.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 0))

    def _apply_defaults(self):
        cfg = self.state.cfg
        self.var_a.set(getattr(cfg, "condition_a", "") or "ConditionA")
        self.var_b.set(getattr(cfg, "condition_b", "") or "ConditionB")

        out_path = (getattr(cfg, "design_tsv_win", "") or "").strip()
        if not out_path:
            run_dir = (self.state.last_run_paths or {}).get("run_dir_win", "")
            if run_dir:
                out_path = os.path.join(run_dir, "design.tsv")
            elif (cfg.output_dir_win or "").strip():
                out_path = os.path.join(cfg.output_dir_win, "design.tsv")
        self.var_out.set(out_path)

        self._load_samples()

    def use_prepde_outputs(self):
        self.var_source.set("prepde")
        run_dir = (self.state.last_run_paths or {}).get("run_dir_win", "")
        if run_dir:
            self.var_out.set(os.path.join(run_dir, "design.tsv"))
        self._load_samples()

    def _load_samples(self):
        cfg = self.state.cfg
        src = self.var_source.get()

        samples: list[str] = []
        if src == "prepde":
            self.lbl_source_hint.configure(text="Reads sample names from the header of the last prepDE matrices.")
            samples = _read_sample_ids_from_matrix(cfg.gene_counts_win) or _read_sample_ids_from_matrix(cfg.iso_counts_win)
        else:
            self.lbl_source_hint.configure(text="Uses sample folders detected in PASS2 scan (must run Scan in Inputs tab).")
            samples = [s.sample_id for s in (self.state.ok_samples() or [])]

        for iid in self.tree.get_children():
            self.tree.delete(iid)

        for s in samples:
            self.tree.insert("", "end", values=(s, ""))

        self._refresh_status()

    def _refresh_status(self):
        total = len(self.tree.get_children())
        a = b = 0
        for iid in self.tree.get_children():
            assigned = (self.tree.set(iid, "assigned") or "").strip()
            if assigned == "A":
                a += 1
            elif assigned == "B":
                b += 1
        self.lbl_status.configure(text=f"Samples: {total}   A: {a}   B: {b}")

    def _assign_selected(self, which: str):
        sels = self.tree.selection()
        if not sels:
            return
        for iid in sels:
            self.tree.set(iid, "assigned", which)
        self._refresh_status()

    def _clear_assignments(self):
        sels = self.tree.selection()
        if not sels:
            return
        for iid in sels:
            self.tree.set(iid, "assigned", "")
        self._refresh_status()

    def _browse_out(self):
        p = filedialog.asksaveasfilename(
            title="Save design.tsv as...",
            defaultextension=".tsv",
            filetypes=[("TSV", "*.tsv"), ("All files", "*.*")]
        )
        if p:
            self.var_out.set(p)

    def _write_design(self):
        cfg = self.state.cfg
        cfg.condition_a = (self.var_a.get() or "").strip() or "ConditionA"
        cfg.condition_b = (self.var_b.get() or "").strip() or "ConditionB"

        out_path = (self.var_out.get() or "").strip()
        if not out_path:
            messagebox.showerror("Design", "design.tsv output path is empty.")
            return

        rows = []
        for iid in self.tree.get_children():
            sample = (self.tree.set(iid, "sample") or "").strip()
            assigned = (self.tree.set(iid, "assigned") or "").strip()
            if not sample or not assigned:
                continue
            cond = cfg.condition_a if assigned == "A" else cfg.condition_b
            rows.append((sample, cond))

        if not rows:
            messagebox.showerror("Design", "No samples assigned. Select rows and assign to A or B.")
            return

        try:
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            with open(out_path, "w", encoding="utf-8", newline="") as f:
                f.write("sampleID\tcondition\n")
                for sample_id, condition in rows:
                    f.write(f"{sample_id}\t{condition}\n")
            cfg.design_tsv_win = out_path
            self._refresh_status()
        except Exception as e:
            messagebox.showerror("Design", str(e))
