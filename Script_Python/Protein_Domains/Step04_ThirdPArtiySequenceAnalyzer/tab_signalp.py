# -*- coding: utf-8 -*-
"""
tab_signalp.py ( - SignalP5 WSL - Enable + Run)

Fixes included:
1) SignalP 5.0b "bin/bin" / "usr/local/bin/usr/local/bin/signalp" bug:
   - Always execute as argv0 WITHOUT slashes:  signalp ...
   - Prepend the directory of the user-provided path to PATH:
       export PATH='<dir>':$PATH; signalp ...

2) IsoformSwitchAnalyzeR::analyzeSignalP format detection bug:
   analyzeSignalP auto-detects SignalP5 by reading ONLY the first token of the first line
   and checking for 'SignalP-5'. If output starts with a header line like:
      ID  Prediction  SP(Sec/SPI)  OTHER  CS Position
   it is misdetected as SignalP4 and import can fail.

   This tab writes:
      #SignalP-5.0    Eukarya
   as FIRST line (comment, but first token still contains "SignalP-5"),
   then NO header, only 5-column data lines:
      isoform_id   Prediction   SP_Sec_SPI   OTHER   CS_Position

NEW in this version:
- "Enable" toggle button (stores tools.signalp.enabled in config)
- "Run" button (runs this tab only)
- When disabled, this tab is skipped by Run All.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import threading
from typing import List, Optional, Tuple, Union

import tkinter as tk
from tkinter import ttk, messagebox


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


def run_wsl(cmd: Union[List[str], str], cfg=None, timeout_sec: Optional[int] = None) -> Tuple[int, str, str]:
    """
    Run a command inside WSL via:
      wsl.exe [-d DISTRO] -- bash -lc "<cmd>"

    cmd may be:
      - list[str] -> safely shell-quoted and joined
      - str       -> passed as-is (useful for 'export PATH=...; signalp ...')
    """
    distro = _wsl_distro_from_cfg(cfg) if cfg is not None else None

    if isinstance(cmd, list):
        cmd_str = " ".join(shlex.quote(a) for a in cmd)
    else:
        cmd_str = cmd

    base = ["wsl.exe"]
    if distro:
        base += ["-d", distro]
    base += ["--", "bash", "--noprofile", "--norc", "-c", cmd_str]

    p = subprocess.run(
        base,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
    )
    return p.returncode, p.stdout or "", p.stderr or ""


# --------------------------
# TabSignalP
# --------------------------
class TabSignalP(ttk.Frame):
    TOOL_ID = "signalp"

    def __init__(self, parent, cfg, log_cb=None, run_cb=None):
        super().__init__(parent)
        self.cfg = cfg
        self.log = log_cb or (lambda msg: None)
        self._run_cb = run_cb

        self.var_enabled = tk.BooleanVar(value=True)
        self.var_signalp = tk.StringVar(value="/usr/local/bin/signalp")
        self.var_threads = tk.IntVar(value=4)

        # organism
        self.var_is_euk = tk.BooleanVar(value=True)
        self.var_non_euk = tk.StringVar(value="gram-")  # gram-, gram+, arch

        # R import parameter
        self.var_min_prob = tk.DoubleVar(value=0.5)

        self._build_ui()
        self._load_from_cfg()
        self._sync_org_widgets()
        self._update_enable_button()

    # ---------------- UI ----------------
    def _build_ui(self):
        pad = 6
        self.columnconfigure(1, weight=1)

        r = 0
        ttk.Label(self, text="SignalP 5 (WSL)", font=("Segoe UI", 10, "bold")).grid(
            row=r, column=0, columnspan=4, sticky="w", padx=pad, pady=(pad, pad)
        )

        self.btn_enable = tk.Button(
            self,
            text="Enable",
            command=self._toggle_enabled,
            font=("Segoe UI", 9, "bold"),
            width=12,
        )
        self.btn_enable.grid(row=r, column=2, sticky="e", padx=(pad, 3), pady=(pad, pad))

        ttk.Button(self, text="Run", command=self._run_via_callback).grid(
            row=r, column=3, sticky="e", padx=(3, pad), pady=(pad, pad)
        )

        r += 1
        ttk.Label(self, text="signalp (WSL):").grid(row=r, column=0, sticky="w", padx=pad, pady=2)
        ttk.Entry(self, textvariable=self.var_signalp).grid(row=r, column=1, sticky="ew", padx=pad, pady=2)
        ttk.Button(self, text="Test", command=self._test_signalp).grid(row=r, column=2, sticky="w", padx=pad, pady=2)

        r += 1
        ttk.Label(self, text="Organism:").grid(row=r, column=0, sticky="w", padx=pad, pady=2)
        self.chk_euk = ttk.Checkbutton(self, text="Eukaryote (euk)", variable=self.var_is_euk, command=self._sync_org_widgets)
        self.chk_euk.grid(row=r, column=1, sticky="w", padx=pad, pady=2)

        self.cmb_non_euk = ttk.Combobox(self, textvariable=self.var_non_euk, values=["gram-", "gram+", "arch"], state="readonly", width=8)
        self.cmb_non_euk.grid(row=r, column=2, sticky="w", padx=pad, pady=2)

        r += 1
        ttk.Label(self, text="Threads (info only):").grid(row=r, column=0, sticky="w", padx=pad, pady=2)
        ttk.Spinbox(self, from_=1, to=64, textvariable=self.var_threads, width=6).grid(
            row=r, column=1, sticky="w", padx=pad, pady=2
        )
        ttk.Label(self, text="(SignalP5 CLI does not always expose a threads flag)").grid(
            row=r, column=2, columnspan=2, sticky="w", padx=pad, pady=2
        )

        r += 1
        ttk.Label(self, text="minSignalPeptideProbability (R import):").grid(row=r, column=0, sticky="w", padx=pad, pady=2)
        ttk.Entry(self, textvariable=self.var_min_prob, width=10).grid(row=r, column=1, sticky="w", padx=pad, pady=2)

        r += 1
        ttk.Separator(self, orient="horizontal").grid(row=r, column=0, columnspan=4, sticky="ew", padx=pad, pady=(pad, pad))

        r += 1
        ttk.Label(
            self,
            text=(
                "Output file is written in SignalP5 format expected by IsoformSwitchAnalyzeR::analyzeSignalP:\n"
                "  - First line: '#SignalP-5.0\\tEukarya'  (comment, used only for version detection)\n"
                "  - Then NO header, only data lines:\n"
                "      isoform_id\\tPrediction\\tSP_Sec_SPI\\tOTHER\\tCS_Position\n"
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

    def _sync_org_widgets(self):
        if bool(self.var_is_euk.get()):
            self.cmb_non_euk.configure(state="disabled")
        else:
            self.cmb_non_euk.configure(state="readonly")

    # ---------------- Run button callback ----------------
    def _run_via_callback(self):
        self.save_to_cfg()

        if not callable(self._run_cb):
            messagebox.showerror("SignalP", "No run callback (run_cb) was provided by the main app.")
            return

        try:
            self._run_cb(self)  # preferred
        except Exception as e:
            try:
                self._run_cb(self.TOOL_ID)  # fallback
            except Exception:
                messagebox.showerror("SignalP", f"Run callback failed:\n{e}")

    # ---------------- Config ----------------
    def _load_from_cfg(self):
        t = _cfg_tool_get(self.cfg, self.TOOL_ID)
        if t:
            self.var_enabled.set(bool(t.get("enabled", True)))
            self.var_signalp.set(t.get("signalp", self.var_signalp.get()))
            try:
                self.var_threads.set(int(t.get("threads", self.var_threads.get())))
            except Exception:
                pass
            try:
                self.var_min_prob.set(float(t.get("min_prob", self.var_min_prob.get())))
            except Exception:
                pass

            org = t.get("org", "euk")
            if org == "euk":
                self.var_is_euk.set(True)
            else:
                self.var_is_euk.set(False)
                if org in ("gram-", "gram+", "arch"):
                    self.var_non_euk.set(org)

    def save_to_cfg(self):
        _cfg_tool_set(
            self.cfg,
            self.TOOL_ID,
            {
                "enabled": bool(self.var_enabled.get()),
                "signalp": self.var_signalp.get().strip(),
                "threads": int(self.var_threads.get()),
                "min_prob": float(self.var_min_prob.get()),
                "org": self._get_org(),
            },
        )

    def refresh_from_cfg(self):
        self._load_from_cfg()
        self._sync_org_widgets()
        self._update_enable_button()

    def _get_org(self) -> str:
        return "euk" if bool(self.var_is_euk.get()) else (self.var_non_euk.get().strip() or "gram-")

    # ---------------- SignalP path fix ----------------
    def _signalp_safe_invocation(self) -> Tuple[str, str]:
        """
        Returns (prefix, exe_name) where:
          - exe_name has NO slashes (argv0 safe)
          - prefix is a shell snippet that prepends the directory to PATH if needed.
        """
        exe = (self.var_signalp.get() or "").strip()
        if not exe:
            return "", "signalp"

        if "/" in exe:
            exe_dir = os.path.dirname(exe) or "."
            exe_base = os.path.basename(exe) or "signalp"
            prefix = f'PATH={shlex.quote(exe_dir)}:"$PATH" '
            return prefix, exe_base

        return "", exe

    # ---------------- Tests ----------------
    def _test_signalp(self):
        if not (self.var_signalp.get() or "").strip():
            messagebox.showerror("SignalP", "signalp path is empty.")
            return

        def worker():
            prefix, exe_name = self._signalp_safe_invocation()
            self.log(f"[SignalP] Testing signalp: {self.var_signalp.get().strip()}")
            cmd = prefix + " ".join(shlex.quote(a) for a in [exe_name, "-version"])
            rc, out, err = run_wsl(cmd, cfg=self.cfg)
            self.log(f"[SignalP] test rc={rc}")
            if out.strip():
                self.log(out.strip().splitlines()[0])
            if err.strip():
                self.log(err.strip().splitlines()[0])

        threading.Thread(target=worker, daemon=True).start()

    # ---------------- Tool run (called by main app) ----------------
    def run_tool(self, run_dir_win: str, return_dir_win: str, cancel_event=None) -> bool:
        """
        Run SignalP5 and write a SignalP5-compatible summary file for IsoformSwitchAnalyzeR.
        """
        self.save_to_cfg()
        if not bool(self.var_enabled.get()):
            self.log("[SignalP] Skipped (disabled)")
            return True

        org = self._get_org()

        faa_win = _cfg_get(self.cfg, "aa_fasta", "") or ""
        if not faa_win or not os.path.exists(faa_win):
            raise FileNotFoundError(f"AA fasta not found (Inputs tab): {faa_win}")

        work_dir = os.path.join(run_dir_win, "SignalP")
        return_dir = return_dir_win
        ensure_dir(work_dir)
        ensure_dir(return_dir)

        raw_path = os.path.join(work_dir, "signalp_stdout.txt")
        result_path = os.path.join(return_dir, "Result_SignalP.txt")

        wsl_faa = win_to_wsl_path(faa_win)

        prefix, exe_name = self._signalp_safe_invocation()

        argv = [
            exe_name,
            "-fasta", wsl_faa,
            "-org", org,
            "-format", "short",
            "-stdout",
            "-verbose=false",
        ]
        cmd = prefix + " ".join(shlex.quote(a) for a in argv)

        self.log(f"[SignalP] Running: {exe_name} -fasta {wsl_faa} -org {org} -format short -stdout -verbose=false")
        if prefix:
            self.log("[SignalP] (PATH fix) argv0 has no slashes; PATH is prepended from the UI path.")

        rc, out, err = run_wsl(cmd, cfg=self.cfg)

        # Save raw output for diagnosis
        try:
            with open(raw_path, "w", encoding="utf-8", newline="\n") as f:
                if out:
                    f.write(out.rstrip("\n") + "\n")
                if err:
                    f.write("\n# STDERR\n")
                    f.write(err.rstrip("\n") + "\n")
        except Exception:
            pass

        if rc != 0:
            if err:
                for ln in err.splitlines():
                    self.log(ln)
            raise RuntimeError(f"SignalP failed (rc={rc}). See {raw_path}")

        data_rows = self._extract_short_rows(out)
        if not data_rows:
            self.log("[SignalP][ERROR] No parsable rows detected in SignalP output.")
            self.log(f"[SignalP][ERROR] Raw output saved to: {raw_path}")
            return False

        org_tag = "Eukarya" if org == "euk" else org
        with open(result_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"#SignalP-5.0\t{org_tag}\n")
            for isoform_id, pred, sp_prob, other_prob, cs_pos in data_rows:
                f.write("\t".join([isoform_id, pred, sp_prob, other_prob, cs_pos]) + "\n")

        self.log(f"[SignalP] Done -> {result_path}")
        return True

    # ---------------- Parsing ----------------
    def _extract_short_rows(self, text: str) -> List[Tuple[str, str, str, str, str]]:
        if not text:
            return []

        lines = [ln.rstrip("\n") for ln in text.splitlines() if ln.strip()]
        if not lines:
            return []

        header_idx = None
        for i, ln in enumerate(lines):
            s = ln.strip()
            if s.startswith("#"):
                s2 = s.lstrip("#").strip()
            else:
                s2 = s
            if ("Prediction" in s2) and ("OTHER" in s2) and ("SP" in s2):
                header_idx = i
                break
        data_start = (header_idx + 1) if header_idx is not None else 0

        out_rows: List[Tuple[str, str, str, str, str]] = []
        for ln in lines[data_start:]:
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            if set(s) <= set("-=|"):
                continue

            row = self._parse_row(s)
            if not row:
                continue

            isoform_id, pred, sp, other, cs = row
            sp_s = self._to_float_str(sp)
            other_s = self._to_float_str(other)
            cs = (cs or "").replace("\t", " ").strip()

            out_rows.append((isoform_id, pred, sp_s, other_s, cs))

        return out_rows

    @staticmethod
    def _to_float_str(x: str) -> str:
        x = (x or "").strip()
        if x == "":
            return ""
        try:
            v = float(x)
            return f"{v:.6f}".rstrip("0").rstrip(".") if "." in f"{v:.6f}" else str(v)
        except Exception:
            return x

    def _parse_row(self, s: str) -> Optional[Tuple[str, str, str, str, str]]:
        if "\t" in s:
            parts = s.split("\t")
            if len(parts) < 4:
                return None
            isoform_id = parts[0].strip()
            pred = parts[1].strip()
            sp = parts[2].strip()
            other = parts[3].strip()
            cs = "\t".join(parts[4:]).strip() if len(parts) > 4 else ""
            return isoform_id, pred, sp, other, cs

        toks = re.split(r"\s+", s, maxsplit=4)
        if len(toks) < 4:
            return None
        isoform_id = toks[0].strip()
        pred = toks[1].strip()
        sp = toks[2].strip()
        other = toks[3].strip()
        cs = toks[4].strip() if len(toks) > 4 else ""
        return isoform_id, pred, sp, other, cs
