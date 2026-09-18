# tab_iupred.py
import os
import re
import shutil
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from shared_config import AppConfig
from shared_utils import ensure_dir, win_to_wsl_path, run_wsl_command


class TabIUPred(ttk.Frame):
    TOOL_ID = "iupred2a"

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
        self.log(f"[IUPred2A] {msg}")

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
            messagebox.showerror("IUPred2A", "No run callback (run_cb) was provided by the main app.")
            return
        try:
            self.run_cb(self)
        except Exception as e:
            try:
                self.run_cb(self.TOOL_ID)
            except Exception:
                messagebox.showerror("IUPred2A", f"Run callback failed:\n{e}")

    # ---------------- UI ----------------
    def _build_ui(self):
        self.columnconfigure(1, weight=1)
        r = 0

        ttk.Label(self, text="IUPred2A need: iupred2a.py, _lib.py, and the data folder", font=("Segoe UI", 11, "bold")).grid(
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

        r += 1
        ttk.Label(self, text="ANCHOR").grid(row=r, column=0, sticky="w", padx=10, pady=4)
        ttk.Label(self, text="ANCHOR2 is always ON (runs with -a).").grid(
            row=r, column=1, columnspan=5, sticky="w", padx=10, pady=4
        )

        r += 1
        self.var_cleanup_tmp = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text="Delete _tmp_fasta after run", variable=self.var_cleanup_tmp).grid(
            row=r, column=0, columnspan=3, sticky="w", padx=10, pady=4
        )

        r += 1
        ttk.Label(self, text="iupred2a.py (WSL path)").grid(row=r, column=0, sticky="w", padx=10, pady=4)
        self.var_iupred = tk.StringVar()
        ttk.Entry(self, textvariable=self.var_iupred).grid(row=r, column=1, sticky="ew", padx=10, pady=4)
        ttk.Button(self, text="Browse (Windows)", command=self._browse_iupred_py_win).grid(
            row=r, column=2, padx=6, pady=4, sticky="w"
        )
        ttk.Button(self, text="Example", command=lambda: self.var_iupred.set("/opt/iupred2a/iupred2a.py")).grid(
            row=r, column=3, padx=6, pady=4, sticky="w"
        )
        ttk.Button(self, text="Test", command=self._test_iupred).grid(
            row=r, column=5, padx=10, pady=4, sticky="w"
        )

        r += 1
        ttk.Label(self, text="iupred2a_lib.py (optional WSL path)").grid(
            row=r, column=0, sticky="w", padx=10, pady=4
        )
        self.var_iupred_lib = tk.StringVar()
        ttk.Entry(self, textvariable=self.var_iupred_lib).grid(row=r, column=1, sticky="ew", padx=10, pady=4)
        ttk.Button(self, text="Browse (Windows)", command=self._browse_iupred_lib_win).grid(
            row=r, column=2, padx=6, pady=4, sticky="w"
        )
        ttk.Button(self, text="Auto from iupred2a.py", command=self._autofill_lib_from_script).grid(
            row=r, column=3, padx=6, pady=4, sticky="w"
        )
        ttk.Button(self, text="Clear", command=lambda: self.var_iupred_lib.set("")).grid(
            row=r, column=4, padx=6, pady=4, sticky="w"
        )

        r += 1
        ttk.Label(self, text="python3 (WSL path or name)").grid(row=r, column=0, sticky="w", padx=10, pady=4)
        self.var_python = tk.StringVar(value="python3")
        ttk.Entry(self, textvariable=self.var_python).grid(row=r, column=1, sticky="ew", padx=10, pady=4)
        ttk.Button(self, text="Default", command=lambda: self.var_python.set("python3")).grid(
            row=r, column=2, padx=6, pady=4, sticky="w"
        )
        ttk.Button(self, text="Test", command=self._test_python).grid(row=r, column=5, padx=10, pady=4, sticky="w")

        r += 1
        ttk.Label(self, text="IUPred2 type").grid(row=r, column=0, sticky="w", padx=10, pady=4)
        self.var_mode = tk.StringVar(value="long")
        ttk.Combobox(self, textvariable=self.var_mode, values=["long", "short", "glob"], state="readonly", width=10).grid(
            row=r, column=1, sticky="w", padx=10, pady=4
        )

        r += 1
        ttk.Label(self, text="Return-to-R filename (raw text)").grid(
            row=r, column=0, sticky="w", padx=10, pady=(8, 4)
        )
        self.var_r_filename = tk.StringVar(value="Result_IUPRED2A.txt")
        ttk.Entry(self, textvariable=self.var_r_filename, width=34).grid(
            row=r, column=1, sticky="w", padx=10, pady=(8, 4)
        )
        ttk.Label(self, text="(saved into OutputDir\\return_to_R\\)").grid(
            row=r, column=2, columnspan=4, sticky="w", padx=10, pady=(8, 4)
        )

        r += 1
        ttk.Button(self, text="Save tab settings", command=self.save_to_cfg).grid(
            row=r, column=0, padx=10, pady=(6, 10), sticky="w"
        )
        ttk.Button(self, text="Explain", command=self._explain).grid(
            row=r, column=1, padx=10, pady=(6, 10), sticky="w"
        )

    def _explain(self):
        messagebox.showinfo(
            "IUPred2A",
            "Writes IsoformSwitchAnalyzeR-compatible IUPred2A raw output.\n"
            "No Run_YYYY folders.\n"
            "Work: OutputDir\\IUPred2A\\\n"
            "Return-to-R: OutputDir\\return_to_R\\Result_IUPRED2A.txt\n\n"
            "On errors, this tab now captures the FULL tool error text into the raw file for debugging.",
        )

    # ---------------- Browsing (Windows) ----------------
    def _browse_iupred_py_win(self):
        p = filedialog.askopenfilename(
            title="Select iupred2a.py (Windows path)",
            filetypes=[("Python file", "*.py"), ("All files", "*.*")],
        )
        if not p:
            return
        self.var_iupred.set(win_to_wsl_path(p))
        self._autofill_lib_from_script()

    def _browse_iupred_lib_win(self):
        p = filedialog.askopenfilename(
            title="Select iupred2a_lib.py (Windows path)",
            filetypes=[("Python file", "*.py"), ("All files", "*.*")],
        )
        if not p:
            return
        self.var_iupred_lib.set(win_to_wsl_path(p))

    def _autofill_lib_from_script(self):
        script = (self.var_iupred.get() or "").strip()
        if not script:
            return
        if "/" in script:
            d = script.rsplit("/", 1)[0]
            self.var_iupred_lib.set(f"{d}/iupred2a_lib.py")

    # ---------------- Config ----------------
    def _load_from_cfg(self):
        t = self.cfg.tool(self.TOOL_ID)
        self.var_enabled.set(bool(t.get("enabled", True)))
        self.var_cleanup_tmp.set(bool(t.get("cleanup_tmp_fasta", False)))
        self.var_iupred.set(t.get("iupred_script", "/opt/iupred2a/iupred2a.py"))
        self.var_iupred_lib.set(t.get("iupred_lib", ""))
        self.var_python.set(t.get("python3", "python3"))
        self.var_mode.set(t.get("mode", "long"))
        self.var_r_filename.set(t.get("return_to_r_raw", "Result_IUPRED2A.txt"))
        if not self.var_iupred_lib.get().strip():
            self._autofill_lib_from_script()

    def save_to_cfg(self):
        t = self.cfg.tool(self.TOOL_ID)
        t["enabled"] = bool(self.var_enabled.get())
        t["cleanup_tmp_fasta"] = bool(self.var_cleanup_tmp.get())
        t["iupred_script"] = self.var_iupred.get().strip() or "/opt/iupred2a/iupred2a.py"
        t["iupred_lib"] = self.var_iupred_lib.get().strip()
        t["python3"] = self.var_python.get().strip() or "python3"
        t["mode"] = self.var_mode.get().strip() or "long"
        fn = (self.var_r_filename.get().strip() or "Result_IUPRED2A.txt")
        if not fn.lower().endswith(".txt"):
            fn += ".txt"
        t["return_to_r_raw"] = fn

    # ---------------- Output locations (NO Run_ folders) ----------------
    def _iupred_work_dir_win(self) -> str:
        if not self.cfg.out_dir:
            return ""
        return os.path.join(self.cfg.out_dir, "IUPred2A")

    def _return_to_r_dir_win(self) -> str:
        if not self.cfg.out_dir:
            return ""
        return os.path.join(self.cfg.out_dir, "return_to_R")

    # ---------------- WSL helpers ----------------
    def _wsl_resolve_exe(self, exe: str):
        exe = (exe or "").strip()
        if not exe:
            return False, "", "Empty executable."
        if "/" in exe:
            cmd = f"set -e; if [ -x {exe} ]; then echo {exe}; else exit 20; fi"
            rc, out, _ = run_wsl_command(cmd, log_cb=None)
            if rc == 0 and out.strip():
                return True, out.strip(), "OK"
            return False, "", f"Not executable at {exe}."
        cmd = f"set -e; command -v {exe}"
        rc, out, _ = run_wsl_command(cmd, log_cb=None)
        if rc == 0 and out.strip():
            return True, out.strip(), "OK"
        return False, "", f"'{exe}' not found in WSL PATH."

    def _wsl_file_exists(self, wsl_path: str) -> bool:
        wsl_path = (wsl_path or "").strip()
        if not wsl_path:
            return False
        rc, _, _ = run_wsl_command(f"set -e; test -f {wsl_path}", log_cb=None)
        return rc == 0

    def _test_python(self):
        self.save_to_cfg()
        ok, resolved, msg = self._wsl_resolve_exe(self.cfg.tool(self.TOOL_ID).get("python3", "python3"))
        if not ok:
            messagebox.showerror("IUPred2A", f"python3 not found:\n{msg}")
            return
        rc, out, _ = run_wsl_command(f"set -e; {resolved} --version", log_cb=self._log_tool)
        if rc == 0:
            messagebox.showinfo("IUPred2A", f"python3 OK:\n{out.strip()}")
        else:
            messagebox.showerror("IUPred2A", "python3 test failed. Check logs.")

    def _test_iupred(self):
        self.save_to_cfg()
        t = self.cfg.tool(self.TOOL_ID)

        script = (t.get("iupred_script", "") or "").strip()
        if not script or not self._wsl_file_exists(script):
            messagebox.showerror("IUPred2A", f"iupred2a.py not found in WSL:\n{script}")
            return

        lib = (t.get("iupred_lib", "") or "").strip()
        if not lib:
            d = script.rsplit("/", 1)[0]
            lib = f"{d}/iupred2a_lib.py"
        if not self._wsl_file_exists(lib):
            messagebox.showwarning("IUPred2A", f"iupred2a_lib.py not found in WSL:\n{lib}")

        ok, py, msg = self._wsl_resolve_exe(t.get("python3", "python3"))
        if not ok:
            messagebox.showerror("IUPred2A", f"python3 not found:\n{msg}")
            return

        # show script header / usage
        cmd = f"set -e; {py} {script} 2>&1 | head -n 40"
        rc, out, _ = run_wsl_command(cmd, log_cb=self._log_tool)
        if out.strip():
            messagebox.showinfo("IUPred2A", "IUPred2A script callable (usage printed).")
        else:
            messagebox.showwarning("IUPred2A", "Could not confirm IUPred2A output. Check logs.")

    # ---------------- FASTA parsing ----------------
    def _iter_fasta(self, fasta_path: str):
        sid = None
        seq_chunks = []
        with open(fasta_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue
                if line.startswith(">"):
                    if sid is not None:
                        yield sid, "".join(seq_chunks)
                    sid = line[1:].strip().split()[0]
                    seq_chunks = []
                else:
                    seq_chunks.append(line.strip())
        if sid is not None:
            yield sid, "".join(seq_chunks)

    @staticmethod
    def _safe_filename(s: str) -> str:
        s = s.strip()
        s = re.sub(r"[\\/:*?\"<>|]+", "_", s)
        s = re.sub(r"\s+", "_", s)
        s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
        if not s:
            s = "seq"
        return s[:180]

    @staticmethod
    def _inject_iso_id_before_pos_table(iupred_stdout: str, iso_id: str) -> str:
        lines = iupred_stdout.splitlines()
        pos_idx = None
        for i, ln in enumerate(lines):
            if ln.strip().startswith("#") and re.search(r"\bPOS\b", ln) and re.search(r"\bIUPRED\b", ln, re.IGNORECASE):
                pos_idx = i
                break
        if pos_idx is None:
            return f">{iso_id}\n" + iupred_stdout.rstrip("\n") + "\n"
        new_lines = lines[:pos_idx] + [f">{iso_id}"] + lines[pos_idx:]
        return "\n".join(new_lines).rstrip("\n") + "\n"

    @staticmethod
    def _looks_like_anchor_present(block_text: str) -> bool:
        has_anchor_header = any("ANCHOR" in ln.upper() for ln in block_text.splitlines() if ln.strip().startswith("#"))
        if not has_anchor_header:
            return False
        for ln in block_text.splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#") or ln.startswith(">"):
                continue
            parts = re.split(r"\s+", ln)
            if len(parts) >= 4:
                try:
                    float(parts[2])
                    float(parts[3])
                    return True
                except Exception:
                    pass
        return False

    # ---------------- Run ----------------
    def run_tool(self, run_dir_win: str, return_dir_win: str, cancel_event: threading.Event) -> bool:
        self.save_to_cfg()
        t = self.cfg.tool(self.TOOL_ID)

        if not bool(t.get("enabled", True)):
            self.log("[IUPred2A] Skipped (disabled)")
            return True

        if not self.cfg.out_dir or not os.path.isdir(self.cfg.out_dir):
            messagebox.showerror("IUPred2A", "Output directory missing/invalid (Inputs tab).")
            return False

        if not self.cfg.aa_fasta or not os.path.isfile(self.cfg.aa_fasta):
            messagebox.showerror("IUPred2A", "AA FASTA missing (Inputs tab).")
            return False

        ok, py, msg = self._wsl_resolve_exe(t.get("python3", "python3"))
        if not ok:
            messagebox.showerror("IUPred2A", f"python3 not available:\n{msg}")
            return False

        script = (t.get("iupred_script", "") or "").strip()
        if not script or not self._wsl_file_exists(script):
            messagebox.showerror("IUPred2A", f"iupred2a.py not found in WSL:\n{script}")
            return False

        lib = (t.get("iupred_lib", "") or "").strip()
        if not lib:
            d = script.rsplit("/", 1)[0]
            lib = f"{d}/iupred2a_lib.py"
        if not self._wsl_file_exists(lib):
            messagebox.showerror("IUPred2A", f"iupred2a_lib.py not found in WSL:\n{lib}")
            return False

        mode = (t.get("mode", "long") or "long").strip()

        tool_dir_win = self._iupred_work_dir_win()
        ensure_dir(tool_dir_win)

        return_dir_win2 = self._return_to_r_dir_win()
        ensure_dir(return_dir_win2)

        raw_all_win = os.path.join(tool_dir_win, "iupred2a.raw.txt")

        r_filename = (t.get("return_to_r_raw", "Result_IUPRED2A.txt") or "Result_IUPRED2A.txt").strip()
        if not r_filename.lower().endswith(".txt"):
            r_filename += ".txt"
        raw_for_r_win = os.path.join(return_dir_win2, r_filename)

        tmp_fa_dir_win = os.path.join(tool_dir_win, "_tmp_fasta")
        ensure_dir(tmp_fa_dir_win)

        used_names = {}
        n_total = 0
        n_ok = 0
        n_anchor_ok = 0
        first_fail_logged = False

        self.log(f"[IUPred2A] OutputDir: {self.cfg.out_dir}")
        self.log(f"[IUPred2A] Work folder: {tool_dir_win}")
        self.log(f"[IUPred2A] Return-to-R: {raw_for_r_win}")
        self.log(f"[IUPred2A] Mode: {mode}   (ANCHOR2: ON via -a)")

        with open(raw_all_win, "w", encoding="utf-8", errors="ignore") as f_audit, open(
            raw_for_r_win, "w", encoding="utf-8", errors="ignore"
        ) as f_r:

            def write_both(s: str):
                f_audit.write(s)
                f_r.write(s)

            for iso_id, seq in self._iter_fasta(self.cfg.aa_fasta):
                n_total += 1
                if cancel_event and cancel_event.is_set():
                    self.log("[IUPred2A] Cancelled by user.")
                    return False

                base = self._safe_filename(iso_id)
                c = used_names.get(base, 0) + 1
                used_names[base] = c
                base_use = f"{base}__{c}" if c > 1 else base

                tmp_fa_win = os.path.join(tmp_fa_dir_win, f"{base_use}.fa")
                with open(tmp_fa_win, "w", encoding="utf-8") as tf:
                    tf.write(f">{iso_id}\n")
                    for i in range(0, len(seq), 60):
                        tf.write(seq[i:i + 60] + "\n")

                tmp_fa_wsl = win_to_wsl_path(tmp_fa_win)

                # Capture BOTH stdout and stderr in one stream for debugging
                # Run via bash -lc so "2>&1" is handled predictably.
                inner_cmd = f"{py} {script} -a {tmp_fa_wsl} {mode}"
                bash_cmd = f"bash -lc {self._bash_quote(inner_cmd + ' 2>&1')}"

                rc, out, _ = run_wsl_command(bash_cmd, log_cb=None, cancel_event=cancel_event)

                write_both("################\n")

                if rc != 0:
                    write_both(f">{iso_id}\n")
                    write_both(f"# ERROR: IUPred2A failed\n")
                    write_both(f"# RC: {rc}\n")
                    write_both(f"# CMD: {inner_cmd}\n")
                    write_both("# OUTPUT (stdout+stderr):\n")
                    write_both(out.rstrip("\n") + "\n\n")

                    if not first_fail_logged:
                        first_fail_logged = True
                        # Log a short excerpt
                        excerpt = "\n".join(out.splitlines()[:15]).strip()
                        self.log(f"[IUPred2A] First failure: isoform={iso_id} rc={rc}")
                        if excerpt:
                            self.log("[IUPred2A] Error excerpt (first 15 lines):")
                            for ln in excerpt.splitlines():
                                self.log(f"[IUPred2A] {ln}")
                    continue

                n_ok += 1
                block = self._inject_iso_id_before_pos_table(out, iso_id)
                write_both(block)
                write_both("\n")

                if self._looks_like_anchor_present(block):
                    n_anchor_ok += 1

                if n_total % 50 == 0:
                    self.log(f"[IUPred2A] Processed {n_total} isoforms...")

        self.log(f"[IUPred2A] Total isoforms in AA FASTA: {n_total}")
        self.log(f"[IUPred2A] Successfully processed: {n_ok}")
        self.log(f"[IUPred2A] Blocks with ANCHOR column detected: {n_anchor_ok}")
        self.log(f"[IUPred2A] Audit raw: {raw_all_win}")
        self.log(f"[IUPred2A] Return-to-R raw: {raw_for_r_win}")

        if n_ok == 0:
            messagebox.showerror("IUPred2A", "No isoforms were processed successfully. Check raw file + Logs.")
            return False

        if n_anchor_ok == 0:
            messagebox.showwarning(
                "IUPred2A",
                "No ANCHOR column detected in output blocks.\n\n"
                "This tab runs with -a, so this usually means your IUPred2A script is not the expected version.\n"
                "Open OutputDir\\return_to_R\\Result_IUPRED2A.txt and check the block headers.",
            )

        if bool(t.get("cleanup_tmp_fasta", False)):
            try:
                shutil.rmtree(tmp_fa_dir_win, ignore_errors=True)
                self.log("[IUPred2A] Cleaned up: _tmp_fasta")
            except Exception as e:
                self.log(f"[IUPred2A] Cleanup warning: {e}")

        return True

    @staticmethod
    def _bash_quote(s: str) -> str:
        # Safe single-quote for bash -lc
        return "'" + s.replace("'", "'\"'\"'") + "'"
