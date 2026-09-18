# tab_coding_potential.py (CPAT tab)
#
# IMPORTANT (IsoformSwitchAnalyzeR compatibility)
# ---------------------------------------------
# IsoformSwitchAnalyzeR::analyzeCPAT() accepts CPAT results in either:
#   (A) CPAT webserver 8-column format, OR
#   (B) a "local/CLI" format that R reads as 5 columns because the *first field*
#       is treated as rownames.
#
# This tab writes format (B) to:
#   OutputDir\return_to_R\Result_CPAT.txt
#
# The output file is TAB-delimited and MUST have:
#   - Header with EXACTLY 5 columns (NO id header, NO trailing tab):
#       mRNA_size\tORF_size\tFickett_score\tHexamer_score\tcoding_prob
#   - Each data row has 6 fields:
#       <isoform_id>\t<mRNA_size>\t<ORF_size>\t<Fickett_score>\t<Hexamer_score>\t<coding_prob>
#
# This tab converts CPAT "*.ORF_prob.tsv" (CPAT CLI output; can include multiple ORFs per transcript)
# into one row per transcript by keeping the ORF with the highest coding probability.
#
# UI NOTE
# -------
# Layout is kept the same as before: this tab does NOT add any new UI controls.
# The CPAT executable is resolved automatically in WSL (command -v cpat), with fallbacks.

import os
import re
import shutil
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from shared_config import AppConfig
from shared_utils import ensure_dir, win_to_wsl_path, run_wsl_command


class TabCodingPotential(ttk.Frame):
    """
    Coding Potential via CPAT (WSL executable: 'cpat').

    Requirements (WSL/Debian):
      - CPAT installed in a venv (recommended) and executable available, e.g.:
          /home/dash/venvs/cpat/bin/cpat
      - Human_Hexamer.tsv (Windows path)
      - Human_logitModel.RData (Windows path)

    Input:
      - NT FASTA from Inputs tab (IsoformSwitchAnalyzeR export)

    Outputs:
      - Raw CPAT outputs in:   OutputDir/CPAT/   (Windows: OutputDir\\CPAT\\)
          cpat.ORF_prob.tsv (+ other files)
      - Return-to-R (single shared folder for all tools):
          OutputDir\\return_to_R\\Result_CPAT.txt

    Notes:
      - This tab ignores run_dir_win and return_dir_win arguments (no Run_YYYY folders).
      - Result_CPAT.txt is written in IsoformSwitchAnalyzeR-compatible "local/CLI" format:
          Header (5 cols):  mRNA_size ORF_size Fickett_score Hexamer_score coding_prob
          Rows (6 fields):  <isoform_id> + the 5 numeric columns
    """
    TOOL_ID = "coding_potential"

    def __init__(self, parent, cfg: AppConfig, log_cb, run_cb):
        super().__init__(parent)
        self.cfg = cfg
        self.log = log_cb
        self.run_cb = run_cb
        self._build_ui()
        self._load_from_cfg()
        self._update_enable_button()

    def refresh_from_cfg(self):
        self._load_from_cfg()

        self._update_enable_button()

    def _log_tool(self, msg: str):
        if msg is None:
            return
        self.log(f"[CPAT] {msg}")

    def _toggle_enabled(self):
        self.var_enabled.set(not bool(self.var_enabled.get()))
        self.save_to_cfg()
        self._update_enable_button()

    def _update_enable_button(self):
        if bool(self.var_enabled.get()):
            self.btn_enable.configure(text="Enable: ON", bg="green", fg="white", activebackground="darkgreen", activeforeground="white")
        else:
            self.btn_enable.configure(text="Enable: OFF", bg="gray60", fg="white", activebackground="gray50", activeforeground="white")

    def _run_via_callback(self):
        self.save_to_cfg()
        if not callable(self.run_cb):
            messagebox.showerror("CPAT", "No run callback (run_cb) was provided by the main app.")
            return
        try:
            self.run_cb(self)
        except Exception as e:
            try:
                self.run_cb(self.TOOL_ID)
            except Exception:
                messagebox.showerror("CPAT", f"Run callback failed:\n{e}")

    # ---------------- UI ----------------
    def _build_ui(self):
        self.columnconfigure(1, weight=1)
        r = 0

        ttk.Label(self, text="Coding Potential (CPAT)", font=("Segoe UI", 11, "bold")).grid(
            row=r, column=0, columnspan=6, sticky="w", padx=10, pady=(10, 6)
        )

        r += 1
        self.var_enabled = tk.BooleanVar(value=True)

        self.btn_enable = tk.Button(
            self,
            text="Enable",
            command=self._toggle_enabled,
            font=("Segoe UI", 9, "bold"),
            width=12,
        )
        self.btn_enable.grid(row=r, column=0, sticky="w", padx=10, pady=4)

        ttk.Button(self, text="Run", command=self._run_via_callback).grid(
            row=r, column=1, sticky="w", padx=10, pady=4
        )
        ttk.Button(self, text="Test CPAT (-h)", command=self._test_cpat).grid(
            row=r, column=2, sticky="w", padx=6, pady=4
        )

        # Hexamer (Windows)
        r += 1
        ttk.Label(self, text="Hexamer table (Windows path)").grid(row=r, column=0, sticky="w", padx=10, pady=4)
        self.var_hexamer_win = tk.StringVar()
        ttk.Entry(self, textvariable=self.var_hexamer_win).grid(row=r, column=1, sticky="ew", padx=10, pady=4)
        ttk.Button(self, text="Browse", command=self._browse_hexamer_win).grid(
            row=r, column=2, padx=6, pady=4, sticky="w"
        )

        # Logit model (Windows)
        r += 1
        ttk.Label(self, text="Logit model (.RData) (Windows path)").grid(row=r, column=0, sticky="w", padx=10, pady=4)
        self.var_logit_win = tk.StringVar()
        ttk.Entry(self, textvariable=self.var_logit_win).grid(row=r, column=1, sticky="ew", padx=10, pady=4)
        ttk.Button(self, text="Browse", command=self._browse_logit_win).grid(
            row=r, column=2, padx=6, pady=4, sticky="w"
        )

        # Optional: antisense
        r += 1
        self.var_antisense = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text="Also search ORFs on antisense strand (--antisense)", variable=self.var_antisense).grid(
            row=r, column=0, columnspan=3, sticky="w", padx=10, pady=4
        )

        # Cutoff (used later in R as codingCutoff; CPAT itself always computes coding_prob)
        r += 1
        ttk.Label(self, text="Coding probability cutoff").grid(row=r, column=0, sticky="w", padx=10, pady=4)
  
        

        r += 1
        ttk.Button(self, text="Save tab settings", command=self.save_to_cfg).grid(
            row=r, column=0, padx=10, pady=(8, 10), sticky="w"
        )
        ttk.Button(self, text="Explain", command=self._explain).grid(
            row=r, column=1, padx=10, pady=(8, 10), sticky="w"
        )

    def _explain(self):
        messagebox.showinfo(
            "CPAT",
            "This tab runs CPAT using the WSL executable 'cpat'.\n\n"
            "Return-to-R output is always written to:\n"
            "  OutputDir\\return_to_R\\Result_CPAT.txt\n\n"
            "Raw CPAT outputs are written to:\n"
            "  OutputDir\\CPAT\\cpat.ORF_prob.tsv (+ other files)\n",
        )

    # ---------------- Browsing ----------------
    def _browse_hexamer_win(self):
        p = filedialog.askopenfilename(
            title="Select hexamer table (e.g., Human_Hexamer.tsv)",
            filetypes=[("TSV", "*.tsv"), ("All files", "*.*")],
        )
        if p:
            self.var_hexamer_win.set(p)

    def _browse_logit_win(self):
        p = filedialog.askopenfilename(
            title="Select logit model (e.g., Human_logitModel.RData)",
            filetypes=[("RData", "*.RData"), ("All files", "*.*")],
        )
        if p:
            self.var_logit_win.set(p)

    # ---------------- Config ----------------
    def _load_from_cfg(self):
        t = self.cfg.tool(self.TOOL_ID)
        self.var_enabled.set(bool(t.get("enabled", True)))
        self.var_hexamer_win.set((t.get("cpat_hexamer_win", "") or "").strip())
        self.var_logit_win.set((t.get("cpat_logit_win", "") or "").strip())
        self.var_antisense.set(bool(t.get("cpat_antisense", False)))


    def save_to_cfg(self):
        t = self.cfg.tool(self.TOOL_ID)
        t["enabled"] = bool(self.var_enabled.get())
        t["cpat_hexamer_win"] = self.var_hexamer_win.get().strip()
        t["cpat_logit_win"] = self.var_logit_win.get().strip()
        t["cpat_antisense"] = bool(self.var_antisense.get())


    # ---------------- Paths (NO Run_ folders) ----------------
    def _tool_work_dir_win(self) -> str:
        if not self.cfg.out_dir:
            return ""
        return os.path.join(self.cfg.out_dir, "CPAT")

    def _return_to_r_dir_win(self) -> str:
        if not self.cfg.out_dir:
            return ""
        return os.path.join(self.cfg.out_dir, "return_to_R")

    # ---------------- WSL helpers ----------------
    def _wsl_is_executable(self, wsl_path: str):
        wsl_path = (wsl_path or "").strip()
        if not wsl_path:
            return False, "Empty CPAT executable path."
        cmd = f"set -e; test -x {wsl_path}"
        rc, _, _ = run_wsl_command(cmd, log_cb=None)
        if rc == 0:
            return True, "OK"
        return False, f"Not executable in WSL: {wsl_path}"

    def _resolve_cpat_exe(self) -> str:
        """Resolve CPAT executable in WSL without adding UI controls."""
        # 1) If user already stored a custom path in settings.json, honor it.
        t = self.cfg.tool(self.TOOL_ID)
        cand = (t.get("cpat_exe", "") or "").strip()
        if cand:
            ok, _ = self._wsl_is_executable(cand)
            if ok:
                return cand

        # 2) Try PATH in WSL
        rc, out, _ = run_wsl_command("set -e; command -v cpat || true", log_cb=None)
        if rc == 0 and out:
            p = out.strip().splitlines()[-1].strip()
            if p:
                ok, _ = self._wsl_is_executable(p)
                if ok:
                    return p

        # 3) Common venv fallback
        fallback = "~/venvs/cpat/bin/cpat"
        ok, _ = self._wsl_is_executable(fallback)
        if ok:
            return fallback

        return ""  # not found

    def _log_cpat_install_instructions(self, exe_path: str):
        exe_path = (exe_path or "").strip() or "<EMPTY>"
        self.log("[CPAT][ERROR] CPAT not found / not executable.")
        self.log(f"[CPAT][ERROR] Configured executable: {exe_path}")
        self.log("")
        self.log("[CPAT][INSTALL] Install CPAT in Debian (WSL) using a virtual environment (recommended):")
        self.log("")
        self.log("  # 1) Create venv")
        self.log("  python3 -m venv ~/venvs/cpat")
        self.log("  source ~/venvs/cpat/bin/activate")
        self.log("")
        self.log("  # 2) Upgrade pip")
        self.log("  pip install -U pip")
        self.log("")
        self.log("  # 3) Install CPAT")
        self.log("  pip install CPAT")
        self.log("")
        self.log("  # 4) Test")
        self.log("  ~/venvs/cpat/bin/cpat -h | head -n 25")
        self.log("")
        self.log("[CPAT][INSTALL] If CPAT is not on PATH, set a custom executable in settings.json:")
        self.log("  tools -> coding_potential -> cpat_exe : ~/venvs/cpat/bin/cpat")
        self.log("")
        self.log("[CPAT][INSTALL] CPAT also requires these species-specific model files (you already have them):")
        self.log("  - Human_Hexamer.tsv")
        self.log("  - Human_logitModel.RData")
        self.log("")

    def _test_cpat(self):
        self.save_to_cfg()
        exe = self._resolve_cpat_exe()

        ok, msg = self._wsl_is_executable(exe)
        if not ok:
            self._log_cpat_install_instructions(exe)
            messagebox.showerror("CPAT", msg + "\n\nSee the Log for Debian installation instructions.")
            return

        cmd = f"set -e; {exe} -h 2>&1 | head -n 80"
        rc, out, _ = run_wsl_command(cmd, log_cb=None)
        self.log("[CPAT] Test: cpat -h (first lines)")
        for ln in (out.splitlines() if out else []):
            self.log(f"  {ln}")

        if rc == 0:
            messagebox.showinfo("CPAT", "CPAT help displayed (see Log).")
        else:
            self.log("[CPAT][WARN] CPAT executable exists but 'cpat -h' returned non-zero.")
            self._log_cpat_install_instructions(exe)
            messagebox.showwarning("CPAT", "Could not run CPAT help. See Log.")

    # ---------------- Run tool ----------------
    def run_tool(self, run_dir_win: str, return_dir_win: str, cancel_event: threading.Event) -> bool:
        """
        IMPORTANT:
          - Ignores run_dir_win / return_dir_win (no Run_YYYY folders).
          - Writes:
              Work:      OutputDir\\CPAT\\...
              Return-R:  OutputDir\\return_to_R\\Result_CPAT.txt
        """
        self.save_to_cfg()
        t = self.cfg.tool(self.TOOL_ID)

        if not bool(t.get("enabled", True)):
            self.log("[CPAT] Skipped (disabled)")
            return True

        if not self.cfg.out_dir or not os.path.isdir(self.cfg.out_dir):
            messagebox.showerror("CPAT", "Output directory missing/invalid (Inputs tab).")
            return False

        if not self.cfg.nt_fasta or not os.path.isfile(self.cfg.nt_fasta):
            messagebox.showerror("CPAT", "NT FASTA missing (Inputs tab).")
            return False

        cpat_exe = self._resolve_cpat_exe()
        if not cpat_exe:
            self._log_cpat_install_instructions("")
            messagebox.showerror("CPAT", "CPAT not found in WSL. See the Log for installation instructions.")
            return False
        ok, msg = self._wsl_is_executable(cpat_exe)
        if not ok:
            self._log_cpat_install_instructions(cpat_exe)
            messagebox.showerror("CPAT", msg + "\n\nSee the Log for Debian installation instructions.")
            return False

        hex_win = (t.get("cpat_hexamer_win", "") or "").strip()
        model_win = (t.get("cpat_logit_win", "") or "").strip()
        if not hex_win or not os.path.isfile(hex_win):
            messagebox.showerror("CPAT", "Hexamer table missing or not found (Windows path).")
            return False
        if not model_win or not os.path.isfile(model_win):
            messagebox.showerror("CPAT", "Logit model .RData missing or not found (Windows path).")
            return False

        antisense = bool(t.get("cpat_antisense", False))

        try:
            cutoff = float((t.get("cpat_cutoff", "0.364") or "0.364").strip())
        except Exception:
            cutoff = 0.364

        # Work folder (NO Run_YYYY)
        tool_work_dir_win = self._tool_work_dir_win()
        ensure_dir(tool_work_dir_win)

        # Return-to-R common folder
        return_dir_win2 = self._return_to_r_dir_win()
        ensure_dir(return_dir_win2)

        # WSL paths
        nt_wsl = win_to_wsl_path(self.cfg.nt_fasta)
        hex_wsl = win_to_wsl_path(hex_win)
        model_wsl = win_to_wsl_path(model_win)

        # Prefix (stable) in work folder
        prefix_win = os.path.join(tool_work_dir_win, "cpat")
        prefix_wsl = win_to_wsl_path(prefix_win)

        self.log("[CPAT] Running CPAT on NT FASTA")
        self.log(f"[CPAT] Work folder: {tool_work_dir_win}")
        self.log(f"[CPAT] Return-to-R: {os.path.join(return_dir_win2, 'Result_CPAT.txt')}")
        self.log(f"[CPAT] exe: {cpat_exe}")
        self.log(f"[CPAT] nt_fasta: {self.cfg.nt_fasta}")
        self.log(f"[CPAT] hexamer: {hex_win}")
        self.log(f"[CPAT] model: {model_win}")
        self.log(f"[CPAT] prefix: {prefix_win}")
        self.log(f"[CPAT] antisense: {antisense}")
        self.log(f"[CPAT] cutoff(for R codingCutoff): {cutoff}")

        cmd = (
            "set -euo pipefail; "
            f"{cpat_exe} "
            f"-g {nt_wsl} "
            f"-x {hex_wsl} "
            f"-d {model_wsl} "
            f"-o {prefix_wsl} "
            f"{'--antisense' if antisense else ''}"
        ).strip()

        rc, _, _ = run_wsl_command(cmd, log_cb=self._log_tool, cancel_event=cancel_event)
        if rc != 0:
            messagebox.showerror("CPAT", "CPAT failed. See Log for stderr.")
            return False

        # Main raw output expected
        raw_orf_prob_win = prefix_win + ".ORF_prob.tsv"
        if not os.path.isfile(raw_orf_prob_win):
            # Try to find any ORF_prob file produced in work folder
            candidates = []
            for fn in os.listdir(tool_work_dir_win):
                lfn = fn.lower()
                if "orf_prob" in lfn and lfn.endswith(".tsv"):
                    candidates.append(os.path.join(tool_work_dir_win, fn))
            if candidates:
                raw_orf_prob_win = candidates[0]
                self.log(f"[CPAT] ORF_prob detected as: {os.path.basename(raw_orf_prob_win)}")
            else:
                messagebox.showerror("CPAT", "CPAT finished but ORF_prob output file not found in OutputDir\\CPAT.")
                return False

        # Also keep a stable copy name inside the work folder (optional, but useful)
        try:
            stable_raw_win = os.path.join(tool_work_dir_win, "cpat.ORF_prob.tsv")
            if os.path.abspath(raw_orf_prob_win) != os.path.abspath(stable_raw_win):
                shutil.copy2(raw_orf_prob_win, stable_raw_win)
                self.log(f"[CPAT] Copied raw ORF_prob to stable name: {stable_raw_win}")
            raw_orf_prob_win = stable_raw_win
        except Exception as e:
            self.log(f"[CPAT][WARN] Could not copy raw ORF_prob to stable name: {e}")

        # Build the Return-to-R file with stable required name
        result_for_r = os.path.join(return_dir_win2, "Result_CPAT.txt")
        self.log(f"[CPAT] Parsing ORF_prob -> {result_for_r}")
        self._parse_cpat_orf_prob_to_result(raw_orf_prob_win, result_for_r)

        self.log("[CPAT] Done")
        return True

    # ---------------- Parsing ----------------
    def _parse_cpat_orf_prob_to_result(self, orf_prob_tsv: str, out_txt: str) -> None:
        """Convert CPAT ORF_prob output into IsoformSwitchAnalyzeR analyzeCPAT() local/CLI format.

        Supports CPAT header variants, including CPAT 3.x style:
          ID  mRNA  ORF_strand  ORF_frame  ORF_start  ORF_end  ORF  Fickett  Hexamer  coding_prob

        Writes Result_CPAT.txt with:
          Header (5 cols):  mRNA_size  ORF_size  Fickett_score  Hexamer_score  coding_prob
          Rows: <isoform_id> + the 5 numeric columns (6 fields total)

        If multiple ORFs per transcript exist (e.g., ENST..._ORF_1), keeps the ORF with the
        highest coding_prob (tie-breaker: largest ORF_size).
        """

        if not os.path.isfile(orf_prob_tsv):
            raise FileNotFoundError(f"CPAT ORF_prob not found: {orf_prob_tsv}")

        def norm(s: str) -> str:
            s = (s or "").strip().lower()
            s = re.sub(r"[^a-z0-9]+", "_", s)
            s = re.sub(r"_+", "_", s).strip("_")
            return s

        def strip_orf_suffix(x: str) -> str:
            x = (x or "").strip()
            # ENST..._ORF_1  -> ENST...
            x = re.sub(r"(?i)(_orf_\d+)$", "", x)
            # ENST....ORF.1  -> ENST...
            x = re.sub(r"(?i)(\.orf\.\d+)$", "", x)
            return x

        def to_float(x: str):
            try:
                return float(x)
            except Exception:
                x2 = re.sub(r"[^0-9eE\.\+\-]", "", (x or ""))
                try:
                    return float(x2)
                except Exception:
                    return None

        def to_int(x: str):
            fx = to_float(x)
            if fx is None:
                return None
            try:
                return int(round(fx))
            except Exception:
                return None

        # Read first non-empty line as header
        with open(orf_prob_tsv, "r", encoding="utf-8", errors="ignore") as f:
            header_line = ""
            for ln in f:
                if ln.strip():
                    header_line = ln.rstrip("\n\r")
                    break
            if not header_line:
                # Empty file -> write header-only output
                ensure_dir(os.path.dirname(out_txt))
                with open(out_txt, "w", encoding="utf-8", newline="\n") as out:
                    out.write("mRNA_size\tORF_size\tFickett_score\tHexamer_score\tcoding_prob\n")
                return

            cols = header_line.split("\t") if ("\t" in header_line) else re.split(r"\s+", header_line.strip())
            cols_n = [norm(c) for c in cols]
            idx = {cols_n[i]: i for i in range(len(cols_n))}

            def pick(*names):
                for nm in names:
                    nm2 = norm(nm)
                    if nm2 in idx:
                        return idx[nm2]
                return None

            # Required mappings (support CPAT 2.x and 3.x headers)
            i_id = pick("id", "seq_id", "seqid", "transcript_id", "isoform_id")
            i_mrna = pick("mrna_size", "mrna", "rna_size", "rna", "mrna_length", "mrna_len")
            i_orf = pick("orf_size", "orf", "orf_length", "orf_len")
            i_fick = pick("fickett_score", "fickett", "ficket_score", "ficket")
            i_hex = pick("hexamer_score", "hexamer")
            i_prob = pick("coding_prob", "coding_probability", "codingprob", "prob", "probability")

            missing = []
            if i_id is None:
                missing.append("ID")
            if i_mrna is None:
                missing.append("mRNA")
            if i_orf is None:
                missing.append("ORF")
            if i_fick is None:
                missing.append("Fickett")
            if i_hex is None:
                missing.append("Hexamer")
            if i_prob is None:
                missing.append("coding_prob")

            if missing:
                self.log("[CPAT][ERROR] ORF_prob header not recognized. Header columns:")
                self.log("  " + "\t".join(cols))
                raise ValueError("ORF_prob header not recognized (missing: " + ", ".join(missing) + ")")

            best = {}  # tx_id -> (prob, orf_size, mrna_size, fick, hex)
            n_rows = 0
            n_used = 0

            for ln in f:
                if not ln.strip():
                    continue
                parts = ln.rstrip("\n\r").split("\t") if ("\t" in ln) else re.split(r"\s+", ln.strip())
                if len(parts) <= max(i_id, i_mrna, i_orf, i_fick, i_hex, i_prob):
                    continue

                raw_id = (parts[i_id] or "").strip()
                if not raw_id:
                    continue
                tx_id = strip_orf_suffix(raw_id)
                if not tx_id:
                    continue

                mrna = to_int(parts[i_mrna])
                orf = to_int(parts[i_orf])
                fick = to_float(parts[i_fick])
                hexa = to_float(parts[i_hex])
                prob = to_float(parts[i_prob])

                if mrna is None or orf is None or fick is None or hexa is None or prob is None:
                    continue

                n_rows += 1
                prev = best.get(tx_id)
                if prev is None:
                    best[tx_id] = (prob, orf, mrna, fick, hexa)
                    n_used += 1
                else:
                    prev_prob, prev_orf, *_ = prev
                    if (prob > prev_prob) or (prob == prev_prob and orf > prev_orf):
                        best[tx_id] = (prob, orf, mrna, fick, hexa)

        # Write EXACT output format (NO trailing tab)
        ensure_dir(os.path.dirname(out_txt))
        with open(out_txt, "w", encoding="utf-8", newline="\n") as out:
            out.write("mRNA_size\tORF_size\tFickett_score\tHexamer_score\tcoding_prob\n")
            for tx_id in sorted(best.keys()):
                prob, orf, mrna, fick, hexa = best[tx_id]
                out.write(f"{tx_id}\t{mrna}\t{orf}\t{fick:.15g}\t{hexa:.15g}\t{prob:.15g}\n")

        self.log(f"[CPAT] Parsed ORF_prob rows: {n_rows}; kept transcripts: {len(best)}")
