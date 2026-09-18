# tab_prepde.py
from __future__ import annotations

import csv
import os
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

from app_state import AppState
from utils_paths import win_to_wsl_path, quote_bash
from utils_wsl import run_wsl_command


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


def _maybe_convert_csv_to_tsv_inplace(path: str) -> bool:
    """
    Some prepDE variants write CSV even if you name the file .tsv.
    If the header looks comma-delimited, rewrite to tab-delimited.
    """
    if not os.path.isfile(path):
        return False

    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            head = f.readline()
            if not head:
                return False
            comma = head.count(",")
            tab = head.count("\t")
            if comma <= tab:
                return False
    except Exception:
        return False

    tmp = path + ".tmp_tsv"
    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as fin, \
             open(tmp, "w", encoding="utf-8", newline="") as fout:
            reader = csv.reader(fin)
            for row in reader:
                fout.write("\t".join(row) + "\n")
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        return False


class PrepDETab(ttk.Frame):
    """
    Runs prepDE inside WSL to generate:
      - gene_count_matrix.tsv
      - isoform_count_matrix.tsv
    """
    def __init__(
        self,
        parent,
        state: AppState,
        ensure_project_layout=None,               # backward compatibility (unused)
        stop_event: Optional[threading.Event] = None,
        *args,
        **kwargs
    ):
        super().__init__(parent)
        self.state = state
        self.ensure_project_layout = ensure_project_layout  # kept for compatibility; not used
        self.stop_event = stop_event or threading.Event()

        self._running = False
        self._design_tab = None

        self._build_ui()
        self._refresh_summary()

    def set_design_tab(self, design_tab):
        self._design_tab = design_tab

    def _build_ui(self):
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        # Summary
        info = ttk.LabelFrame(outer, text="Run summary", padding=10)
        info.pack(fill=tk.X)

        self.lbl_pass2 = ttk.Label(info, text="PASS2 folder: (not set)")
        self.lbl_pass2.pack(anchor="w")

        self.lbl_samples = ttk.Label(info, text="Samples detected: 0 (0 OK)")
        self.lbl_samples.pack(anchor="w")

        self.lbl_out = ttk.Label(info, text="Output folder: (not set)")
        self.lbl_out.pack(anchor="w")

        self.lbl_wsl = ttk.Label(info, text="WSL: default distro | python3")
        self.lbl_wsl.pack(anchor="w")

        self.lbl_len = ttk.Label(info, text="Read length (-l): 150")
        self.lbl_len.pack(anchor="w")

        # Controls
        ctl = ttk.Frame(outer)
        ctl.pack(fill=tk.X, pady=(10, 0))

        self.btn_rescan = ttk.Button(ctl, text="Re-scan samples", command=self._rescan)
        self.btn_rescan.pack(side=tk.LEFT)

        self.btn_test = ttk.Button(ctl, text="Test prepDE (-h)", command=self._test_prepde)
        self.btn_test.pack(side=tk.LEFT, padx=(10, 0))

        self.btn_run = ttk.Button(ctl, text="Generate count matrices", command=self._run_prepde)
        self.btn_run.pack(side=tk.LEFT, padx=(10, 0))

        self.btn_stop = ttk.Button(ctl, text="Stop", command=self._stop, state="disabled")
        self.btn_stop.pack(side=tk.LEFT, padx=(10, 0))

        ttk.Label(
            ctl,
            text="Runs prepDE on PASS2 (-e/-G) GTFs to create gene/isoform count matrices.",
        ).pack(side=tk.LEFT, padx=(12, 0))

        # Progress
        self.pb = ttk.Progressbar(outer, mode="indeterminate")
        self.pb.pack(fill=tk.X, pady=(8, 0))

        # Results
        res = ttk.LabelFrame(outer, text="Results", padding=10)
        res.pack(fill=tk.X, pady=(10, 0))
        res.columnconfigure(1, weight=1)

        ttk.Label(res, text="Gene count matrix:").grid(row=0, column=0, sticky="w")
        self.var_gene = tk.StringVar(value="")
        ttk.Entry(res, textvariable=self.var_gene, state="readonly").grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(res, text="Open", command=lambda: _open_file(self.var_gene.get())).grid(row=0, column=2, padx=6)
        ttk.Button(res, text="Open folder", command=lambda: _open_in_explorer(self.var_gene.get())).grid(row=0, column=3, padx=6)

        ttk.Label(res, text="Isoform count matrix:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.var_iso = tk.StringVar(value="")
        ttk.Entry(res, textvariable=self.var_iso, state="readonly").grid(row=1, column=1, sticky="ew", padx=6, pady=(6, 0))
        ttk.Button(res, text="Open", command=lambda: _open_file(self.var_iso.get())).grid(row=1, column=2, padx=6, pady=(6, 0))
        ttk.Button(res, text="Open folder", command=lambda: _open_in_explorer(self.var_iso.get())).grid(row=1, column=3, padx=6, pady=(6, 0))

        self.btn_push_design = ttk.Button(
            res,
            text="Use these matrices in Design tab",
            command=self._push_to_design,
            state="disabled",
        )
        self.btn_push_design.grid(row=2, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Label(
            res,
            text="Makes the Design tab read sample names from the matrices (guarantees a match).",
            wraplength=900
        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))

        # Log
        log_frame = ttk.LabelFrame(outer, text="prepDE log", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        self.txt = tk.Text(log_frame, height=18, wrap="none")
        self.txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        yscroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.txt.yview)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt.configure(yscrollcommand=yscroll.set)

        try:
            self.txt.configure(font=("Consolas", 10))
        except Exception:
            pass

    def _set_running(self, running: bool):
        self._running = running
        self.state.is_busy = running
        self.btn_run.configure(state="disabled" if running else "normal")
        self.btn_test.configure(state="disabled" if running else "normal")
        self.btn_rescan.configure(state="disabled" if running else "normal")
        self.btn_stop.configure(state="normal" if running else "disabled")
        if running:
            self.pb.start(10)
        else:
            self.pb.stop()

    def log(self, msg: str):
        self.txt.insert(tk.END, msg + "\n")
        self.txt.see(tk.END)

    def _refresh_summary(self):
        cfg = self.state.cfg
        self.lbl_pass2.configure(text=f"PASS2 folder: {cfg.pass2_dir_win or '(not set)'}")
        ok = len(self.state.ok_samples())
        total = len(self.state.detected_samples or [])
        self.lbl_samples.configure(text=f"Samples detected: {total} ({ok} OK)")

        run_mode = "new run folder each run" if cfg.create_run_folder else "write directly into output folder"
        self.lbl_out.configure(text=f"Output folder: {cfg.output_dir_win or '(not set)'}  ({run_mode})")

        distro = cfg.wsl_distro or "default distro"
        py = cfg.wsl_python or "python3"
        self.lbl_wsl.configure(text=f"WSL: {distro} | {py}")

        self.lbl_len.configure(text=f"Read length (-l): {int(getattr(cfg, 'read_length', 150) or 150)} bp")

        self.var_gene.set(cfg.gene_counts_win or "")
        self.var_iso.set(cfg.iso_counts_win or "")

        if cfg.gene_counts_win and os.path.isfile(cfg.gene_counts_win) and cfg.iso_counts_win and os.path.isfile(cfg.iso_counts_win):
            self.btn_push_design.configure(state="normal")
        else:
            self.btn_push_design.configure(state="disabled")

    def _rescan(self):
        try:
            self.state.scan_pass2_folder()
            self._refresh_summary()
            self.log("[SCAN] PASS2 scan refreshed.")
        except Exception as e:
            messagebox.showerror("Scan", str(e))

    def _stop(self):
        if self._running:
            self.stop_event.set()
            self.log("[STOP] Stop requested…")

    def _require_prepde(self) -> str:
        p = (self.state.cfg.prepde_py_win or "").strip()
        if not p:
            raise ValueError("prepDE.py path is empty (set it in Inputs tab).")
        if not os.path.isfile(p):
            raise ValueError(f"prepDE.py not found: {p}")
        return p

    def _stream_cb(self, kind: str, line: str):
        def _append():
            prefix = "" if kind == "stdout" else "[stderr] "
            self.log(prefix + line)
        try:
            self.after(0, _append)
        except Exception:
            pass

    def _test_prepde(self):
        try:
            prepde_win = self._require_prepde()
            cfg = self.state.cfg
            distro = (cfg.wsl_distro or "").strip()
            py = (cfg.wsl_python or "python3").strip() or "python3"
            prepde_wsl = win_to_wsl_path(prepde_win)

            self.txt.delete("1.0", tk.END)
            self.log("=== prepDE TEST (-h) ===")
            self.log(f"WSL distro: {distro or '(default)'}")
            self.log(f"Python in WSL: {py}")
            self.log(f"prepDE.py (WSL): {prepde_wsl}")
            self.log("")

            self.stop_event.clear()
            self._set_running(True)

            def worker():
                try:
                    cmd = f"{py} {quote_bash(prepde_wsl)} -h"
                    rc = run_wsl_command(
                        distro=distro,
                        bash_command=cmd,
                        stream_callback=self._stream_cb,
                        stop_event=self.stop_event,
                    )
                    self.after(0, lambda: self.log(f"\n[EXIT] code={rc}"))
                except Exception as e:
                    self.after(0, lambda: self.log(f"\n[ERROR] {e}"))
                finally:
                    self.after(0, lambda: self._set_running(False))
                    self.stop_event.clear()

            threading.Thread(target=worker, daemon=True).start()

        except Exception as e:
            messagebox.showerror("prepDE test", str(e))

    def _run_prepde(self):
        try:
            cfg = self.state.cfg
            prepde_win = self._require_prepde()

            if not self.state.detected_samples:
                self.state.scan_pass2_folder()

            ok_samples = self.state.ok_samples()
            if not ok_samples:
                raise ValueError("No valid samples detected.\n\nRun 'Scan PASS2 folder' in the Inputs tab first.")

            if not (cfg.output_dir_win or "").strip():
                raise ValueError("Output folder is empty (set it in Inputs tab).")

            distro = (cfg.wsl_distro or "").strip()
            py = (cfg.wsl_python or "python3").strip() or "python3"
            read_len = int(getattr(cfg, "read_length", 150) or 150)
            if read_len <= 0:
                read_len = 150

            # Create run folder
            paths = self.state.ensure_run_folder()
            run_win = paths["run_dir_win"]
            run_wsl = paths["run_dir_wsl"]

            # Write sample list (sampleID \t WSL-path-to-gtf)
            list_win = os.path.join(run_win, "prepde_samples.tsv")
            with open(list_win, "w", encoding="utf-8") as f:
                for s in ok_samples:
                    f.write(f"{s.sample_id}\t{win_to_wsl_path(s.gtf_win)}\n")

            gene_out_win = os.path.join(run_win, "gene_count_matrix.tsv")
            iso_out_win = os.path.join(run_win, "isoform_count_matrix.tsv")

            cfg.gene_counts_win = gene_out_win
            cfg.iso_counts_win = iso_out_win
            self._refresh_summary()

            prepde_wsl = win_to_wsl_path(prepde_win)
            list_wsl = win_to_wsl_path(list_win)
            gene_out_wsl = win_to_wsl_path(gene_out_win)
            iso_out_wsl = win_to_wsl_path(iso_out_win)

            self.txt.delete("1.0", tk.END)
            self.log("=== prepDE RUN ===")
            self.log(f"Run folder (Windows): {run_win}")
            self.log(f"WSL distro: {distro or '(default)'}")
            self.log(f"Python in WSL: {py}")
            self.log(f"Read length (-l): {read_len}")
            self.log(f"prepDE.py (WSL): {prepde_wsl}")
            self.log(f"Sample list (WSL): {list_wsl}")
            self.log(f"Gene matrix (WSL): {gene_out_wsl}")
            self.log(f"Isoform matrix (WSL): {iso_out_wsl}")
            self.log("")

            self.stop_event.clear()
            self._set_running(True)

            def worker():
                try:
                    cmd = (
                        f"cd {quote_bash(run_wsl)} && "
                        f"{py} {quote_bash(prepde_wsl)} "
                        f"-i {quote_bash(list_wsl)} "
                        f"-g {quote_bash(gene_out_wsl)} "
                        f"-t {quote_bash(iso_out_wsl)} "
                        f"-l {read_len}"
                    )

                    t0 = time.time()
                    rc = run_wsl_command(
                        distro=distro,
                        bash_command=cmd,
                        stream_callback=self._stream_cb,
                        stop_event=self.stop_event,
                    )
                    dt = time.time() - t0

                    def done():
                        self.log("")
                        self.log(f"[EXIT] code={rc}  elapsed={dt:.1f}s")
                        if rc == 0:
                            self.log("[OK] prepDE completed.")

                            conv_gene = _maybe_convert_csv_to_tsv_inplace(gene_out_win)
                            conv_iso = _maybe_convert_csv_to_tsv_inplace(iso_out_win)
                            if conv_gene or conv_iso:
                                self.log("[OK] Converted matrices to TAB-delimited TSV (in-place).")

                            self.log(f"Gene matrix: {gene_out_win}")
                            self.log(f"Isoform matrix: {iso_out_win}")
                        else:
                            self.log("[WARN] Non-zero exit; check stderr above.")

                        self._refresh_summary()

                    self.after(0, done)

                except Exception as e:
                    self.after(0, lambda: self.log(f"\n[ERROR] {e}"))
                finally:
                    self.after(0, lambda: self._set_running(False))
                    self.stop_event.clear()

            threading.Thread(target=worker, daemon=True).start()

        except Exception as e:
            messagebox.showerror("prepDE run", str(e))

    def _push_to_design(self):
        cfg = self.state.cfg
        if not (cfg.gene_counts_win and os.path.isfile(cfg.gene_counts_win)):
            messagebox.showerror("Design", "Gene count matrix is missing.")
            return
        if not (cfg.iso_counts_win and os.path.isfile(cfg.iso_counts_win)):
            messagebox.showerror("Design", "Isoform count matrix is missing.")
            return

        if self._design_tab is not None:
            self._design_tab.use_prepde_outputs()
            self.log("[DESIGN] Design tab set to read sample names from matrices.")
        else:
            self.log("[DESIGN] Open the Design tab and choose: Source = From last PrepDE matrices.")
