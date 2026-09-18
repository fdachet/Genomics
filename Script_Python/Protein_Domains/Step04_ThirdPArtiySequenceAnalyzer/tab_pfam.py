# -*- coding: utf-8 -*-
"""
tab_pfam.py ( - Enable + Run)

PFAM:
- Run hmmscan in WSL, parse domtblout, write IsoformSwitchAnalyzeR-compatible PFAMScan-like output:
    <OutputDir>/return_to_R/Result_PFAM.txt

Manual hmmpress:
- A button "Run hmmpress (manual)" is provided.
- PFAM run will STOP (with message) if pressed files are missing.

NEW in this version:
- "Enable" toggle button (stores tools.pfam.enabled in config)
- "Run" button (runs this tab only)
- When disabled, this tab is skipped by Run All.

MULTICORE FIX:
- The old code only relied on hmmscan --cpu.
- On some WSL1 / HMMER installs, that still behaves like 1 core or scales poorly.
- This version uses OUTER parallelism too:
    - split the AA fasta into N chunks
    - launch N hmmscan processes in parallel through WSL
    - merge domtblout/tblout
- "Threads" now means TOTAL CPU budget for PFAM on this tab.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox


# --------------------------
# Config helpers (robust)
# --------------------------
def _cfg_tool_get(cfg, tool_id: str) -> dict:
    try:
        if hasattr(cfg, "tool"):
            d = cfg.tool(tool_id)
            return d if isinstance(d, dict) else {}
    except Exception:
        pass
    if isinstance(cfg, dict):
        tools = cfg.get("tools", {})
        if isinstance(tools, dict):
            d = tools.get(tool_id, {})
            return d if isinstance(d, dict) else {}
    return {}


def _cfg_tool_set(cfg, tool_id: str, d: dict) -> None:
    try:
        if hasattr(cfg, "set_tool"):
            cfg.set_tool(tool_id, d)
            return
    except Exception:
        pass
    try:
        if hasattr(cfg, "tool"):
            dd = cfg.tool(tool_id)
            if isinstance(dd, dict):
                dd.clear()
                dd.update(d)
                return
    except Exception:
        pass
    if isinstance(cfg, dict):
        tools = cfg.get("tools")
        if not isinstance(tools, dict):
            cfg["tools"] = {}
            tools = cfg["tools"]
        tools[tool_id] = d


def _cfg_get(cfg, key: str, default=None):
    try:
        if hasattr(cfg, "get"):
            return cfg.get(key, default)
    except Exception:
        pass
    if isinstance(cfg, dict):
        return cfg.get(key, default)
    return getattr(cfg, key, default)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def win_to_wsl_path(p: str) -> str:
    if not p:
        return p
    p = p.strip().strip('"')
    if p.startswith("/"):
        return p
    p2 = p.replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)$", p2)
    if m:
        drive = m.group(1).lower()
        rest = m.group(2)
        return f"/mnt/{drive}/{rest}"
    return p2


def _wsl_distro_from_cfg(cfg) -> Optional[str]:
    def _clean(s: str) -> str:
        s = s.replace(chr(0), "")
        s = "".join(ch for ch in s if ch.isprintable())
        return s.strip()

    distro = _cfg_get(cfg, "wsl_distro", None)
    if distro:
        d = _clean(str(distro))
        if d:
            return d
    distro = _cfg_get(cfg, "distro", None)
    if distro:
        d = _clean(str(distro))
        if d:
            return d
    return None


def run_wsl(argv: List[str], cfg=None, timeout_sec: Optional[int] = None) -> Tuple[int, str, str]:
    distro = _wsl_distro_from_cfg(cfg) if cfg is not None else None
    cmd_str = " ".join(shlex.quote(a) for a in argv)

    base = ["wsl.exe"]
    if distro:
        base += ["-d", distro]
    base += ["--", "bash", "-lc", cmd_str]

    p = subprocess.run(
        base,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
    )
    return p.returncode, p.stdout or "", p.stderr or ""


# --------------------------
# FASTA helpers
# --------------------------
def count_fasta_records(fasta_path: str) -> int:
    n = 0
    with open(fasta_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith(">"):
                n += 1
    return n


def split_fasta_round_robin(fasta_path: str, out_dir: str, n_parts: int) -> List[Tuple[str, int]]:
    ensure_dir(out_dir)
    if n_parts < 1:
        n_parts = 1

    part_paths = [os.path.join(out_dir, f"part_{i+1:04d}.faa") for i in range(n_parts)]
    handles = [open(p, "w", encoding="utf-8", newline="\n") for p in part_paths]
    counts = [0] * n_parts

    try:
        current_idx = -1
        current_handle = None

        with open(fasta_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith(">"):
                    current_idx = (current_idx + 1) % n_parts
                    current_handle = handles[current_idx]
                    counts[current_idx] += 1
                if current_handle is not None:
                    current_handle.write(line)
    finally:
        for h in handles:
            try:
                h.close()
            except Exception:
                pass

    nonempty: List[Tuple[str, int]] = []
    for p, n in zip(part_paths, counts):
        if n > 0 and os.path.exists(p) and os.path.getsize(p) > 0:
            nonempty.append((p, n))
    return nonempty


def concat_text_files(in_paths: List[str], out_path: str) -> None:
    ensure_dir(os.path.dirname(out_path))
    with open(out_path, "w", encoding="utf-8", newline="\n") as out:
        first = True
        for p in in_paths:
            if not os.path.exists(p):
                continue
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                txt = f.read()
            if not txt:
                continue
            if not first and not txt.startswith("\n"):
                out.write("\n")
            out.write(txt)
            first = False


def hmmscan_supports_cpu(hmmscan_exe: str, cfg=None) -> Tuple[bool, str]:
    rc, out, err = run_wsl([hmmscan_exe, "-h"], cfg=cfg)
    txt = "\n".join([out or "", err or ""])
    if rc != 0 and not txt.strip():
        return False, "unable to read hmmscan help"
    if "--cpu" in txt:
        return True, "hmmscan help exposes --cpu"
    return False, "hmmscan help does not expose --cpu (possible non-threaded build)"


# --------------------------
# domtblout parsing
# --------------------------
@dataclass
class DomHit:
    seq_id: str
    hmm_acc: str
    hmm_name: str
    hmm_len: int
    ali_start: int
    ali_end: int
    env_start: int
    env_end: int
    hmm_start: int
    hmm_end: int
    bit_score: float
    i_evalue: str


def parse_domtblout(domtbl_path: str) -> List[DomHit]:
    hits: List[DomHit] = []
    if not os.path.exists(domtbl_path):
        return hits

    with open(domtbl_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line or line.startswith("#"):
                continue
            s = line.strip()
            if not s:
                continue

            parts = re.split(r"\s+", s, maxsplit=22)
            if len(parts) < 21:
                continue

            try:
                hmm_name = parts[0]
                hmm_acc = parts[1]
                hmm_len = int(parts[2])
                seq_id = parts[3]

                i_evalue = parts[12]
                bit_score = float(parts[13])

                hmm_start = int(parts[15])
                hmm_end = int(parts[16])
                ali_start = int(parts[17])
                ali_end = int(parts[18])
                env_start = int(parts[19])
                env_end = int(parts[20])
            except Exception:
                continue

            hits.append(
                DomHit(
                    seq_id=seq_id,
                    hmm_acc=hmm_acc,
                    hmm_name=hmm_name,
                    hmm_len=hmm_len,
                    ali_start=ali_start,
                    ali_end=ali_end,
                    env_start=env_start,
                    env_end=env_end,
                    hmm_start=hmm_start,
                    hmm_end=hmm_end,
                    bit_score=bit_score,
                    i_evalue=i_evalue,
                )
            )
    return hits


def build_pfam_clan_map(pfam_dat_path: str) -> Dict[str, str]:
    """Best-effort: map PFxxxxx.yy accession -> CLxxxx from Pfam .dat file. If missing/invalid, return {}."""
    m: Dict[str, str] = {}
    if not pfam_dat_path or not os.path.exists(pfam_dat_path):
        return m

    current_acc = None
    current_clan = None

    with open(pfam_dat_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            if line.startswith("ACC"):
                toks = line.strip().split()
                if len(toks) >= 2:
                    current_acc = toks[1].strip()
            elif line.startswith("CL"):
                toks = line.strip().split()
                if len(toks) >= 2:
                    current_clan = toks[1].strip()
            elif line.strip() == "//":
                if current_acc and current_clan:
                    m[current_acc] = current_clan
                current_acc = None
                current_clan = None

    return m


def write_pfamscan_like(result_path: str, hits: List[DomHit], clan_map: Dict[str, str]) -> None:
    """
    Write PFAMScan-like oldstyle 15 columns (no header), tab-separated.

    Column order:
      seq_id  ali_start  ali_end  env_start  env_end  hmm_acc  hmm_name  type
      hmm_start  hmm_end  hmm_length  bit_score  E_value  significant  clan
    """
    ensure_dir(os.path.dirname(result_path))
    with open(result_path, "w", encoding="utf-8", newline="\n") as out:
        for h in hits:
            clan = clan_map.get(h.hmm_acc, "CL0000")
            out.write(
                "\t".join(
                    [
                        h.seq_id,
                        str(h.ali_start),
                        str(h.ali_end),
                        str(h.env_start),
                        str(h.env_end),
                        h.hmm_acc,
                        h.hmm_name,
                        "Domain",
                        str(h.hmm_start),
                        str(h.hmm_end),
                        str(h.hmm_len),
                        f"{h.bit_score:.2f}",
                        h.i_evalue,
                        "1",
                        clan,
                    ]
                )
                + "\n"
            )


# --------------------------
# TabPFAM
# --------------------------
class TabPFAM(ttk.Frame):
    TOOL_ID = "pfam"

    def __init__(self, parent, cfg, log_cb=None, run_cb=None):
        super().__init__(parent)
        self.cfg = cfg
        self.log = log_cb or (lambda msg: None)
        self._run_cb = run_cb

        self.var_enabled = tk.BooleanVar(value=True)
        self.var_hmmscan = tk.StringVar(value="/usr/local/bin/hmmscan")
        self.var_hmmpress = tk.StringVar(value="/usr/local/bin/hmmpress")
        self.var_threads = tk.IntVar(value=4)
        self.var_pfam_hmm = tk.StringVar(value="")
        self.var_pfam_dat = tk.StringVar(value="")

        self.var_progress_text = tk.StringVar(value="PFAM progress: idle")
        self.var_progress_counts = tk.StringVar(value="Done: 0 | Remaining: 0")
        self._progress_total = 0
        self._progress_done = 0

        self._build_ui()
        self._load_from_cfg()
        self._update_enable_button()

    def _build_ui(self):
        pad = 6
        self.columnconfigure(1, weight=1)

        r = 0
        ttk.Label(self, text="PFAM / hmmscan (WSL)", font=("Segoe UI", 10, "bold")).grid(
            row=r, column=0, columnspan=4, sticky="w", padx=pad, pady=(pad, pad)
        )

        self.btn_enable = tk.Button(
            self, text="Enable", command=self._toggle_enabled, font=("Segoe UI", 9, "bold"), width=12
        )
        self.btn_enable.grid(row=r, column=2, sticky="e", padx=(pad, 3), pady=(pad, pad))

        ttk.Button(self, text="Run", command=self._run_via_callback).grid(
            row=r, column=3, sticky="e", padx=(3, pad), pady=(pad, pad)
        )

        r += 1
        ttk.Label(self, text="hmmscan (WSL):").grid(row=r, column=0, sticky="w", padx=pad, pady=2)
        ttk.Entry(self, textvariable=self.var_hmmscan).grid(row=r, column=1, sticky="ew", padx=pad, pady=2)
        ttk.Button(self, text="Test", command=self._test_hmmscan).grid(row=r, column=2, sticky="w", padx=pad, pady=2)

        r += 1
        ttk.Label(self, text="hmmpress (WSL):").grid(row=r, column=0, sticky="w", padx=pad, pady=2)
        ttk.Entry(self, textvariable=self.var_hmmpress).grid(row=r, column=1, sticky="ew", padx=pad, pady=2)
        ttk.Button(self, text="Test", command=self._test_hmmpress).grid(row=r, column=2, sticky="w", padx=pad, pady=2)

        r += 1
        ttk.Button(self, text="Run hmmpress (manual)", command=self._run_hmmpress_manual).grid(
            row=r, column=1, sticky="w", padx=pad, pady=(2, 6)
        )
        ttk.Button(self, text="Check DB pressed (YES/NO)", command=self._check_db_pressed).grid(
            row=r, column=2, sticky="w", padx=pad, pady=(2, 6)
        )

        r += 1
        ttk.Label(self, text="PFAM HMM (Pfam-A.hmm or .hmm.gz):").grid(row=r, column=0, sticky="w", padx=pad, pady=2)
        ttk.Entry(self, textvariable=self.var_pfam_hmm).grid(row=r, column=1, sticky="ew", padx=pad, pady=2)
        ttk.Button(self, text="Browse", command=self._browse_pfam_hmm).grid(row=r, column=2, sticky="w", padx=pad, pady=2)

        r += 1
        ttk.Label(self, text="PFAM .dat (optional, for CL clans):").grid(row=r, column=0, sticky="w", padx=pad, pady=2)
        ttk.Entry(self, textvariable=self.var_pfam_dat).grid(row=r, column=1, sticky="ew", padx=pad, pady=2)
        ttk.Button(self, text="Browse", command=self._browse_pfam_dat).grid(row=r, column=2, sticky="w", padx=pad, pady=2)

        r += 1
        ttk.Label(self, text="Threads:").grid(row=r, column=0, sticky="w", padx=pad, pady=2)
        ttk.Spinbox(self, from_=1, to=256, textvariable=self.var_threads, width=6).grid(
            row=r, column=1, sticky="w", padx=pad, pady=2
        )

        r += 1
        ttk.Label(self, text="Progress:").grid(row=r, column=0, sticky="nw", padx=pad, pady=(4, 2))
        self.progressbar = ttk.Progressbar(self, orient="horizontal", mode="determinate", maximum=100, value=0)
        self.progressbar.grid(row=r, column=1, columnspan=3, sticky="ew", padx=pad, pady=(4, 2))

        r += 1
        ttk.Label(self, textvariable=self.var_progress_text, justify="left").grid(
            row=r, column=1, columnspan=3, sticky="w", padx=pad, pady=(0, 0)
        )

        r += 1
        ttk.Label(self, textvariable=self.var_progress_counts, justify="left").grid(
            row=r, column=1, columnspan=3, sticky="w", padx=pad, pady=(0, 2)
        )

        r += 1
        ttk.Separator(self, orient="horizontal").grid(row=r, column=0, columnspan=4, sticky="ew", padx=pad, pady=(pad, pad))

        r += 1
        ttk.Label(
            self,
            text=(
                "Output:\n"
                "  <OutputDir>/return_to_R/Result_PFAM.txt  (PFAMScan-like 15 columns, accepted by IsoformSwitchAnalyzeR::analyzePFAM)\n\n"
                "Manual hmmpress requirement:\n"
                "  If Pfam-A.hmm is not pressed (.h3f/.h3i/.h3m/.h3p), PFAM run will stop.\n"
                "  Click 'Run hmmpress (manual)' first.\n\n"
                "Threads behavior in this version:\n"
                "  The value is treated as total CPU budget.\n"
                "  The tab can split the fasta and run several hmmscan jobs in parallel, which works better on some WSL1 setups."
            ),
            justify="left",
            wraplength=900,
        ).grid(row=r, column=0, columnspan=4, sticky="w", padx=pad, pady=(0, pad))

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
        if not callable(self._run_cb):
            messagebox.showerror("PFAM", "No run callback (run_cb) was provided by the main app.")
            return
        try:
            self._run_cb(self)
        except Exception as e:
            try:
                self._run_cb(self.TOOL_ID)
            except Exception:
                messagebox.showerror("PFAM", f"Run callback failed:\n{e}")

    def _load_from_cfg(self):
        t = _cfg_tool_get(self.cfg, self.TOOL_ID)
        if t:
            self.var_enabled.set(bool(t.get("enabled", True)))
            self.var_hmmscan.set(t.get("hmmscan", self.var_hmmscan.get()))
            self.var_hmmpress.set(t.get("hmmpress", self.var_hmmpress.get()))
            try:
                self.var_threads.set(int(t.get("threads", self.var_threads.get())))
            except Exception:
                pass
            self.var_pfam_hmm.set(t.get("pfam_hmm", self.var_pfam_hmm.get()))
            self.var_pfam_dat.set(t.get("pfam_dat", self.var_pfam_dat.get()))

    def save_to_cfg(self):
        _cfg_tool_set(
            self.cfg,
            self.TOOL_ID,
            {
                "enabled": bool(self.var_enabled.get()),
                "hmmscan": self.var_hmmscan.get().strip(),
                "hmmpress": self.var_hmmpress.get().strip(),
                "threads": int(self.var_threads.get()),
                "pfam_hmm": self.var_pfam_hmm.get().strip(),
                "pfam_dat": self.var_pfam_dat.get().strip(),
            },
        )

    def refresh_from_cfg(self):
        self._load_from_cfg()
        self._update_enable_button()

    def _set_progress_ui(self, done: int, total: int, status: str) -> None:
        done = max(0, int(done))
        total = max(0, int(total))
        if total > 0:
            done = min(done, total)

        def _apply():
            try:
                self._progress_total = total
                self._progress_done = done
                maxv = total if total > 0 else 1
                self.progressbar.configure(maximum=maxv)
                self.progressbar["value"] = done if total > 0 else 0
                remaining = max(0, total - done)
                pct = (100.0 * done / total) if total > 0 else 0.0
                self.var_progress_text.set(f"{status} ({pct:.1f}%)" if total > 0 else status)
                self.var_progress_counts.set(f"Done: {done} / {total} | Remaining: {remaining}")
            except Exception:
                pass

        try:
            self.after(0, _apply)
        except Exception:
            _apply()

    def _reset_progress_ui(self, status: str = "PFAM progress: idle") -> None:
        self._set_progress_ui(0, 0, status)

    def _browse_pfam_hmm(self):
        p = filedialog.askopenfilename(
            title="Select Pfam-A.hmm",
            filetypes=[("HMM files", "*.hmm *.hmm.gz"), ("All files", "*.*")],
        )
        if p:
            self.var_pfam_hmm.set(p)

    def _browse_pfam_dat(self):
        p = filedialog.askopenfilename(
            title="Select PFAM .dat (optional)",
            filetypes=[("DAT files", "*.dat *.txt"), ("All files", "*.*")],
        )
        if p:
            self.var_pfam_dat.set(p)

    def _pressed_files(self, pfam_hmm_win: str) -> List[str]:
        base = pfam_hmm_win
        if base.endswith(".gz"):
            base = base[:-3]
        return [base + ext for ext in [".h3f", ".h3i", ".h3m", ".h3p"]]

    def _is_pressed(self, pfam_hmm_win: str) -> bool:
        return all(os.path.exists(p) for p in self._pressed_files(pfam_hmm_win))

    def _check_db_pressed(self):
        self.save_to_cfg()
        pfam_hmm = self.var_pfam_hmm.get().strip()
        if not pfam_hmm:
            messagebox.showerror("PFAM", "PFAM HMM is not set. Please select Pfam-A.hmm (or .hmm.gz).")
            return

        pfam_hmm_unz = pfam_hmm[:-3] if pfam_hmm.endswith(".gz") else pfam_hmm
        needed: List[str] = [pfam_hmm_unz] + self._pressed_files(pfam_hmm_unz)
        missing = [p for p in needed if not os.path.exists(p)]

        ok = (len(missing) == 0)
        status = "YES" if ok else "NO"

        lines = []
        lines.append(f"Database pressed: {status}")
        lines.append("")
        lines.append("Required files:")
        for p in needed:
            lines.append(("  OK   " if os.path.exists(p) else "  MISS ") + p)

        msg = "\n".join(lines)
        self.log("[PFAM] Check DB pressed -> " + status)
        if missing:
            for p in missing:
                self.log(f"[PFAM][MISS] {p}")

        messagebox.showinfo("PFAM - DB pressed (YES/NO)", msg)

    def _run_hmmpress_manual(self):
        pfam_hmm = self.var_pfam_hmm.get().strip()
        hmmpress = self.var_hmmpress.get().strip()

        if not pfam_hmm:
            messagebox.showerror("PFAM", "Please select PFAM HMM (Pfam-A.hmm) first.")
            return

        pfam_hmm_unz = pfam_hmm[:-3] if pfam_hmm.endswith(".gz") else pfam_hmm
        if not os.path.exists(pfam_hmm_unz):
            messagebox.showerror("PFAM", f"PFAM HMM not found:\n{pfam_hmm_unz}")
            return

        def worker():
            try:
                self.log(f"[PFAM] Running hmmpress (manual) on: {pfam_hmm_unz}")
                wsl_db = win_to_wsl_path(pfam_hmm_unz)
                rc, out, err = run_wsl([hmmpress, wsl_db], cfg=self.cfg)
                if out:
                    for ln in out.splitlines():
                        self.log(ln)
                if err:
                    for ln in err.splitlines():
                        self.log(ln)
                self.log(f"[PFAM] hmmpress rc={rc}")

                if rc == 0 and self._is_pressed(pfam_hmm_unz):
                    self.log("[PFAM] DB press OK: .h3* files present.")
                elif rc == 0:
                    self.log("[PFAM][WARN] hmmpress succeeded but .h3* files are not visible on Windows side.")
                else:
                    self.log("[PFAM][ERROR] hmmpress failed.")
            except Exception as e:
                self.log(f"[PFAM][ERROR] hmmpress exception: {e}")

        threading.Thread(target=worker, daemon=True).start()

    def _test_hmmscan(self):
        exe = self.var_hmmscan.get().strip()
        if not exe:
            messagebox.showerror("PFAM", "hmmscan path is empty.")
            return

        def worker():
            self.log(f"[PFAM] Testing hmmscan: {exe}")
            rc, out, err = run_wsl([exe, "-h"], cfg=self.cfg)
            self.log(f"[PFAM] hmmscan test rc={rc}")
            if out:
                self.log(out.strip().splitlines()[0] if out.strip() else "")
            if err:
                self.log(err.strip().splitlines()[0] if err.strip() else "")
            ok, why = hmmscan_supports_cpu(exe, cfg=self.cfg)
            self.log(f"[PFAM] hmmscan --cpu support: {'YES' if ok else 'NO'} ({why})")

        threading.Thread(target=worker, daemon=True).start()

    def _test_hmmpress(self):
        exe = self.var_hmmpress.get().strip()
        if not exe:
            messagebox.showerror("PFAM", "hmmpress path is empty.")
            return

        def worker():
            self.log(f"[PFAM] Testing hmmpress: {exe}")
            rc, out, err = run_wsl([exe, "-h"], cfg=self.cfg)
            self.log(f"[PFAM] hmmpress test rc={rc}")
            if out:
                self.log(out.strip().splitlines()[0] if out.strip() else "")
            if err:
                self.log(err.strip().splitlines()[0] if err.strip() else "")

        threading.Thread(target=worker, daemon=True).start()

    def _run_one_hmmscan_job(
        self,
        job_idx: int,
        hmmscan: str,
        threads_per_job: int,
        wsl_db: str,
        part_faa_win: str,
        part_tbl_win: str,
        part_domtbl_win: str,
    ) -> Tuple[int, str, str]:
        part_faa_wsl = win_to_wsl_path(part_faa_win)
        part_tbl_wsl = win_to_wsl_path(part_tbl_win)
        part_domtbl_wsl = win_to_wsl_path(part_domtbl_win)

        cmd = [
            hmmscan,
            "--cpu", str(max(1, threads_per_job)),
            "--tblout", part_tbl_wsl,
            "--domtblout", part_domtbl_wsl,
            wsl_db,
            part_faa_wsl,
        ]

        self.log(
            f"[PFAM][JOB {job_idx}] hmmscan start "
            f"(cpu/job={max(1, threads_per_job)}) -> {os.path.basename(part_faa_win)}"
        )
        rc, out, err = run_wsl(cmd, cfg=self.cfg)
        return rc, out, err

    def run_tool(self, run_dir_win: str, return_dir_win: str, cancel_event=None) -> bool:
        self.save_to_cfg()
        self._reset_progress_ui("PFAM progress: preparing")
        if not bool(self.var_enabled.get()):
            self.log("[PFAM] Skipped (disabled)")
            self._reset_progress_ui("PFAM progress: skipped (disabled)")
            return True

        hmmscan = self.var_hmmscan.get().strip()
        pfam_hmm = self.var_pfam_hmm.get().strip()
        pfam_dat = self.var_pfam_dat.get().strip()
        total_threads = max(1, int(self.var_threads.get()))

        faa_win = _cfg_get(self.cfg, "aa_fasta", "") or ""
        if not faa_win or not os.path.exists(faa_win):
            self._reset_progress_ui("PFAM progress: AA fasta missing")
            raise FileNotFoundError(f"AA fasta not found (Inputs tab): {faa_win}")

        if not pfam_hmm:
            self._reset_progress_ui("PFAM progress: PFAM HMM missing")
            raise ValueError("PFAM HMM not set (Pfam-A.hmm).")

        pfam_hmm_unz = pfam_hmm[:-3] if pfam_hmm.endswith(".gz") else pfam_hmm
        if not os.path.exists(pfam_hmm_unz):
            self._reset_progress_ui("PFAM progress: PFAM HMM missing")
            raise FileNotFoundError(f"PFAM HMM not found: {pfam_hmm_unz}")

        if not self._is_pressed(pfam_hmm_unz):
            msg = (
                "PFAM database is not pressed (missing .h3f/.h3i/.h3m/.h3p).\n\n"
                "Manual hmmpress is required.\n"
                "Click 'Run hmmpress (manual)' in the PFAM tab, then re-run PFAM."
            )
            self.log("[PFAM][ERROR] " + msg.replace("\n", " "))
            self._reset_progress_ui("PFAM progress: database not pressed")
            return False

        work_dir = os.path.join(run_dir_win, "PFAM")
        return_dir = return_dir_win
        ensure_dir(work_dir)
        ensure_dir(return_dir)

        domtbl_path = os.path.join(work_dir, "hmmscan_domtblout.txt")
        tblout_path = os.path.join(work_dir, "hmmscan_tblout.txt")
        parts_dir = os.path.join(work_dir, "parts")
        part_out_dir = os.path.join(work_dir, "parts_out")
        ensure_dir(parts_dir)
        ensure_dir(part_out_dir)

        for name in os.listdir(parts_dir):
            try:
                os.remove(os.path.join(parts_dir, name))
            except Exception:
                pass
        for name in os.listdir(part_out_dir):
            try:
                os.remove(os.path.join(part_out_dir, name))
            except Exception:
                pass

        wsl_db = win_to_wsl_path(pfam_hmm_unz)

        seq_count = count_fasta_records(faa_win)
        if seq_count <= 0:
            self._reset_progress_ui("PFAM progress: no sequences found")
            raise RuntimeError(f"No FASTA records found in: {faa_win}")

        host_cpus = os.cpu_count() or 1
        max_workers = min(total_threads, seq_count, host_cpus)
        max_workers = max(1, max_workers)

        # Use more chunks than workers so the user gets real sequence-based progress updates.
        # Each completed chunk advances the meter by the exact number of sequences in that chunk.
        if seq_count <= max_workers:
            n_chunks = seq_count
        else:
            n_chunks = min(seq_count, max(max_workers * 8, max_workers))

        threads_per_job = max(1, total_threads // max_workers)

        hmmscan_has_cpu, hmmscan_cpu_msg = hmmscan_supports_cpu(hmmscan, cfg=self.cfg)

        self.log(f"[PFAM] OutputDir: {run_dir_win}")
        self.log(f"[PFAM] Work folder: {work_dir}")
        self.log(f"[PFAM] AA fasta: {faa_win}")
        self.log(f"[PFAM] Sequences detected: {seq_count}")
        self.log(f"[PFAM] Windows host logical CPUs detected: {host_cpus}")
        self.log(f"[PFAM] Requested total threads: {total_threads}")
        self.log(f"[PFAM] hmmscan --cpu support: {'YES' if hmmscan_has_cpu else 'NO'} ({hmmscan_cpu_msg})")
        self.log(f"[PFAM] Parallel plan: {max_workers} concurrent worker(s), {threads_per_job} cpu/job, {n_chunks} total chunk(s)")
        self._set_progress_ui(0, seq_count, f"PFAM running: 0/{seq_count} sequences")

        if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
            self.log("[PFAM] Cancelled before start.")
            self._reset_progress_ui("PFAM progress: cancelled")
            return False

        part_fastas = split_fasta_round_robin(faa_win, parts_dir, n_chunks)
        total_chunks = len(part_fastas)
        if total_chunks < 1:
            self._reset_progress_ui("PFAM progress: chunk creation failed")
            raise RuntimeError("Failed to create FASTA parts for PFAM.")

        self.log(f"[PFAM] Created {total_chunks} FASTA chunk(s)")
        self._set_progress_ui(0, seq_count, f"PFAM running: 0/{seq_count} sequences | 0/{total_chunks} chunks done")

        futures = {}
        part_tbls: List[str] = []
        part_domtbls: List[str] = []
        done_sequences = 0
        done_chunks = 0

        try:
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                for i, (part_faa, part_seq_count) in enumerate(part_fastas, start=1):
                    part_tbl = os.path.join(part_out_dir, f"job_{i:04d}.tblout.txt")
                    part_domtbl = os.path.join(part_out_dir, f"job_{i:04d}.domtblout.txt")
                    part_tbls.append(part_tbl)
                    part_domtbls.append(part_domtbl)

                    fut = ex.submit(
                        self._run_one_hmmscan_job,
                        i,
                        hmmscan,
                        threads_per_job,
                        wsl_db,
                        part_faa,
                        part_tbl,
                        part_domtbl,
                    )
                    futures[fut] = (i, part_faa, part_seq_count)

                for fut in as_completed(futures):
                    if cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)():
                        self.log("[PFAM] Cancel requested during hmmscan execution.")
                        self._set_progress_ui(done_sequences, seq_count, "PFAM progress: cancelling")
                        raise RuntimeError("PFAM cancelled by user.")

                    i, part_faa, part_seq_count = futures[fut]
                    rc, out, err = fut.result()

                    if out:
                        for ln in out.splitlines():
                            self.log(f"[PFAM][JOB {i}] {ln}")
                    if err:
                        for ln in err.splitlines():
                            self.log(f"[PFAM][JOB {i}] {ln}")

                    self.log(f"[PFAM][JOB {i}] rc={rc} ({os.path.basename(part_faa)})")

                    if rc != 0:
                        self._set_progress_ui(done_sequences, seq_count, f"PFAM failed at chunk {i}/{total_chunks}")
                        raise RuntimeError(f"hmmscan failed in PFAM worker {i} (rc={rc}). See log output above.")

                    done_chunks += 1
                    done_sequences += part_seq_count
                    remaining_sequences = max(0, seq_count - done_sequences)

                    self.log(
                        f"[PFAM] Progress: done {done_sequences}/{seq_count} sequences, "
                        f"remaining {remaining_sequences}, chunks {done_chunks}/{total_chunks}"
                    )
                    self._set_progress_ui(
                        done_sequences,
                        seq_count,
                        f"PFAM running: {done_sequences}/{seq_count} sequences | {done_chunks}/{total_chunks} chunks done",
                    )

            concat_text_files(part_tbls, tblout_path)
            concat_text_files(part_domtbls, domtbl_path)
            self.log(f"[PFAM] Merged tblout -> {tblout_path}")
            self.log(f"[PFAM] Merged domtblout -> {domtbl_path}")

            result_path = os.path.join(return_dir, "Result_PFAM.txt")
            self.log(f"[PFAM] Parsing -> {result_path}")

            hits = parse_domtblout(domtbl_path)
            clan_map = build_pfam_clan_map(pfam_dat) if pfam_dat else {}
            write_pfamscan_like(result_path, hits, clan_map)

            self.log(f"[PFAM] Hits parsed: {len(hits)}")
            self.log(f"[PFAM] Done -> {result_path}")
            self._set_progress_ui(seq_count, seq_count, "PFAM complete")
            return True

        except Exception:
            raise

