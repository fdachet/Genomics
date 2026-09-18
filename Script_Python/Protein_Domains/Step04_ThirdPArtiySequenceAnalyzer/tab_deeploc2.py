import os
import shutil
import threading
import time
from datetime import datetime
import csv
import tkinter as tk
from tkinter import ttk, messagebox

from shared_config import AppConfig
from shared_utils import ensure_dir, win_to_wsl_path, run_wsl_command


# --------- Local helper (keeps chunking independent from shared_utils) ---------
def count_fasta_records(fasta_path: str) -> int:
    """Count FASTA records by counting lines starting with '>' (plain text only)."""
    p = (fasta_path or "").strip()
    if not p or not os.path.isfile(p):
        return 0
    try:
        n = 0
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith(">"):
                    n += 1
        return n
    except Exception:
        return 0


def _fmt_seconds(sec: float) -> str:
    if sec is None:
        return "?"
    sec = max(0.0, float(sec))
    s = int(round(sec))
    h = s // 3600
    m = (s % 3600) // 60
    ss = s % 60
    if h > 0:
        return f"{h:d}:{m:02d}:{ss:02d}"
    return f"{m:d}:{ss:02d}"


class TabDeepLoc2(ttk.Frame):
    """
    DeepLoc2 tab for IsoSwitch 3rd-Party Sequence Analyzer.

    Expected by main_app:
      - constructor: TabDeepLoc2(parent, cfg=<AppConfig>, log_cb=<callable>, run_cb=<callable>)
      - methods: refresh_from_cfg(), save_to_cfg()
      - attribute: TOOL_ID = "deeploc2"
      - runner: run_tool(run_dir, return_dir, cancel_event) -> bool
    """

    TOOL_ID = "deeploc2"

    def __init__(self, parent, cfg: AppConfig, log_cb=None, run_cb=None):
        super().__init__(parent)
        self.cfg = cfg
        self.log_cb = log_cb
        self.run_cb = run_cb

        # UI variables
        self.var_enabled = tk.BooleanVar(value=True)
        self.var_model = tk.StringVar(value="Fast")      # Fast | Accurate
        self.var_device = tk.StringVar(value="cpu")      # cpu | cuda | mps
        self.var_offline = tk.BooleanVar(value=True)
        self.var_plot_attention = tk.BooleanVar(value=False)

        # Progress mode
        self.var_chunked = tk.BooleanVar(value=True)
        self.var_chunk_size = tk.StringVar(value="100")  # default 100

        # Cache monitor (Accurate mode only)
        self.var_acc_cache_path = tk.StringVar(value="~/.cache/huggingface/hub/models--Rostlab--prot_t5_xl_uniref50")
        self.var_acc_cache_size = tk.StringVar(value="(unknown)")

        # WSL target
        self.var_wsl_distro = tk.StringVar(value="Debian")
        self.var_wsl_user = tk.StringVar(value="dash")

        self._cache_refresh_lock = threading.Lock()

        self._build_ui()
        self.refresh_from_cfg()
        self._refresh_acc_cache_size_async()

    # ---------------- Logging ----------------
    def log(self, msg: str):
        if callable(self.log_cb):
            self.log_cb(msg)
        else:
            print(msg)

    # ---------------- UI ----------------
    def _build_ui(self):
        self.columnconfigure(0, weight=1)

        frame = ttk.LabelFrame(self, text="DeepLoc2")
        frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        frame.columnconfigure(1, weight=1)

        r = 0

        # Enable "button"
        dark_green = "gray60"
        dark_green_active = "green"

        enable_btn = tk.Checkbutton(
            frame,
            text="Enable DeepLoc2",
            variable=self.var_enabled,
            indicatoron=False,
            bg=dark_green,
            fg="white",
            activebackground=dark_green_active,
            activeforeground="white",
            selectcolor=dark_green_active,
            relief="raised",
            bd=2,
            padx=12,
            pady=6,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            highlightthickness=0,
        )
        enable_btn.grid(row=r, column=0, columnspan=4, sticky="w", padx=10, pady=(10, 6))
        r += 1

        ttk.Label(frame, text="Model").grid(row=r, column=0, sticky="e", padx=10, pady=4)
        ttk.Combobox(frame, textvariable=self.var_model, values=["Fast", "Accurate"], width=12, state="readonly").grid(
            row=r, column=1, sticky="w", padx=10, pady=4
        )

        ttk.Label(frame, text="Device").grid(row=r, column=2, sticky="e", padx=10, pady=4)
        ttk.Combobox(frame, textvariable=self.var_device, values=["cpu", "cuda", "mps"], width=12, state="readonly").grid(
            row=r, column=3, sticky="w", padx=10, pady=4
        )
        r += 1

        ttk.Checkbutton(frame, text="Offline (no downloads)", variable=self.var_offline).grid(
            row=r, column=0, columnspan=4, sticky="w", padx=10, pady=2
        )
        r += 1

        ttk.Checkbutton(frame, text="Plot attention", variable=self.var_plot_attention).grid(
            row=r, column=0, columnspan=4, sticky="w", padx=10, pady=2
        )
        r += 1

        # Progress / chunking
        prog = ttk.LabelFrame(frame, text="Progress feedback")
        prog.grid(row=r, column=0, columnspan=4, sticky="ew", padx=10, pady=(6, 10))
        prog.columnconfigure(1, weight=1)

        ttk.Checkbutton(
            prog,
            text="Chunked run (progress feedback). Auto single-run if N <= chunk_size.",
            variable=self.var_chunked
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(8, 4))

        ttk.Label(prog, text="Chunk size").grid(row=1, column=0, sticky="e", padx=10, pady=(0, 8))
        ttk.Entry(prog, textvariable=self.var_chunk_size, width=10).grid(row=1, column=1, sticky="w", padx=10, pady=(0, 8))
        ttk.Label(prog, text="(recommended: 25–200; default 100)").grid(row=1, column=2, sticky="w", padx=10, pady=(0, 8))

        r += 1

        btns = ttk.Frame(frame)
        btns.grid(row=r, column=0, columnspan=4, sticky="w", padx=10, pady=(0, 10))
        ttk.Button(btns, text="Verify", command=self._on_verify).pack(side="left", padx=(0, 10))
        ttk.Button(btns, text="Run", command=self._on_run).pack(side="left", padx=(0, 10))
        ttk.Button(btns, text="Refresh Accurate cache size", command=self._refresh_acc_cache_size_async).pack(side="left")

        cache = ttk.LabelFrame(self, text="Accurate mode download (ProtT5) — size monitor")
        cache.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        cache.columnconfigure(1, weight=1)

        ttk.Label(cache, text="WSL cache path").grid(row=0, column=0, sticky="e", padx=10, pady=(10, 4))
        ttk.Entry(cache, textvariable=self.var_acc_cache_path).grid(row=0, column=1, sticky="ew", padx=10, pady=(10, 4))

        ttk.Label(cache, text="Size").grid(row=1, column=0, sticky="e", padx=10, pady=4)
        ttk.Label(cache, textvariable=self.var_acc_cache_size).grid(row=1, column=1, sticky="w", padx=10, pady=4)

        openf = ttk.Frame(cache)
        openf.grid(row=2, column=1, sticky="w", padx=10, pady=(4, 10))
        ttk.Label(openf, text="Distro").pack(side="left")
        ttk.Entry(openf, textvariable=self.var_wsl_distro, width=10).pack(side="left", padx=(6, 10))
        ttk.Label(openf, text="User").pack(side="left")
        ttk.Entry(openf, textvariable=self.var_wsl_user, width=10).pack(side="left", padx=(6, 10))
        ttk.Button(openf, text="Open folder in Explorer (best-effort)", command=self._open_acc_cache_in_explorer).pack(side="left", padx=(6, 0))

    # ---------------- Config sync ----------------
    def refresh_from_cfg(self):
        tool = self.cfg.tool(self.TOOL_ID)

        self.var_enabled.set(bool(tool.get("enabled", True)))
        self.var_model.set(tool.get("model", "Fast") or "Fast")
        self.var_device.set(tool.get("device", "cpu") or "cpu")
        self.var_offline.set(bool(tool.get("offline", True)))
        self.var_plot_attention.set(bool(tool.get("plot_attention", False)))

        self.var_chunked.set(bool(tool.get("chunked", True)))
        self.var_chunk_size.set(str(tool.get("chunk_size", 100)))

        if tool.get("acc_cache_path"):
            self.var_acc_cache_path.set(tool.get("acc_cache_path"))
        if tool.get("wsl_distro"):
            self.var_wsl_distro.set(tool.get("wsl_distro"))
        if tool.get("wsl_user"):
            self.var_wsl_user.set(tool.get("wsl_user"))

    def save_to_cfg(self):
        tool = self.cfg.tool(self.TOOL_ID)
        tool["enabled"] = bool(self.var_enabled.get())
        tool["model"] = (self.var_model.get() or "Fast").strip()
        tool["device"] = (self.var_device.get() or "cpu").strip()
        tool["offline"] = bool(self.var_offline.get())
        tool["plot_attention"] = bool(self.var_plot_attention.get())

        tool["chunked"] = bool(self.var_chunked.get())
        try:
            tool["chunk_size"] = max(1, int((self.var_chunk_size.get() or "100").strip()))
        except Exception:
            tool["chunk_size"] = 100

        tool["acc_cache_path"] = (self.var_acc_cache_path.get() or "").strip()
        tool["wsl_distro"] = (self.var_wsl_distro.get() or "").strip()
        tool["wsl_user"] = (self.var_wsl_user.get() or "").strip()

    # ---------------- Internal helpers ----------------
    def _get_wsl_target(self):
        """
        Read target distro/user from current UI values first, then cfg fallback.
        """
        tool = self.cfg.tool(self.TOOL_ID)

        distro = (self.var_wsl_distro.get() or "").strip()
        user = (self.var_wsl_user.get() or "").strip()

        if not distro:
            distro = (tool.get("wsl_distro", "") or "").strip()
        if not user:
            user = (tool.get("wsl_user", "") or "").strip()

        if not distro:
            distro = "Debian"
        if not user:
            user = "dash"

        return distro, user

    def _bash_dq(self, s: str) -> str:
        """
        Escape text for inclusion inside double quotes in a bash command.
        """
        return (s or "").replace("\\", "\\\\").replace('"', '\\"')

    def _deeploc2_paths(self, user: str):
        user = (user or "").strip() or "dash"
        base = f"/home/{user}/venvs/deeploc2/bin"
        return {
            "cli": f"{base}/deeploc2",
            "python": f"{base}/python",
            "activate": f"{base}/activate",
        }

    def _deeploc2_env_prefix(self, offline: bool) -> str:
        if offline:
            return "export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1;"
        return "export HF_HUB_DISABLE_TELEMETRY=1;"

    def _build_deeploc2_run_cmd(self, fasta_wsl: str, out_wsl: str, model: str, device: str, plot_attention: bool, user: str, offline: bool) -> str:
        paths = self._deeploc2_paths(user)
        cli = self._bash_dq(paths["cli"])
        fasta_wsl = self._bash_dq(fasta_wsl)
        out_wsl = self._bash_dq(out_wsl)
        model = (model or "Fast").strip()
        device = (device or "cpu").strip()
        plot_flag = " -p" if plot_attention else ""
        env_prefix = self._deeploc2_env_prefix(offline)
        return f'{env_prefix} "{cli}" -f "{fasta_wsl}" -o "{out_wsl}" -m {model} -d {device}{plot_flag}'

    def _run_wsl(self, cmd: str, distro: str, user: str, cancel_event=None):
        return run_wsl_command(
            cmd,
            cwd_win=None,
            env=None,
            log_cb=lambda line: self.log(f"[DeepLoc2] {line}"),
            cancel_event=cancel_event,
            distro=distro,
            wsl_user=user,
        )

    # ---------------- UI callbacks ----------------
    def _on_verify(self):
        self.save_to_cfg()
        distro, user = self._get_wsl_target()
        paths = self._deeploc2_paths(user)

        self.log("[DeepLoc2] Verify installation...")
        self.log(f"[DeepLoc2] Using WSL distro: {distro}")
        self.log(f"[DeepLoc2] Using WSL user: {user}")

        cli = self._bash_dq(paths["cli"])
        py = self._bash_dq(paths["python"])
        activate = self._bash_dq(paths["activate"])

        cmd = (
            'set -e; '
            'echo "__VERIFY_BEGIN__"; '
            'whoami; '
            'echo "$HOME"; '
            f'test -e "{activate}" && echo "VENV_OK" || echo "VENV_MISSING"; '
            f'test -x "{cli}" && echo "CLI_OK" || echo "CLI_MISSING"; '
            f'"{cli}" --help; '
            f'''"{py}" -c 'import DeepLoc2; print("DeepLoc2 import OK")' '''
        )

        rc, out, err = self._run_wsl(cmd, distro=distro, user=user, cancel_event=None)

        self.log(f"[DeepLoc2][DBG] rc={rc}")
        if err:
            for line in err.strip().splitlines():
                self.log(f"[DeepLoc2][stderr] {line}")
        if out:
            for line in out.strip().splitlines():
                self.log(f"[DeepLoc2][stdout] {line}")

        if rc == 0:
            self.log("[DeepLoc2] Verify OK")
        else:
            self.log("[DeepLoc2] Verify FAILED")

    def _on_run(self):
        self.save_to_cfg()
        if callable(self.run_cb):
            self.run_cb(self.TOOL_ID)
        else:
            messagebox.showerror("DeepLoc2", "Run callback is not connected in main app.")

    # ---------------- Accurate cache size ----------------
    def _refresh_acc_cache_size_async(self):
        if not self._cache_refresh_lock.acquire(blocking=False):
            return

        def worker():
            try:
                distro, user = self._get_wsl_target()
                acc_dir = (self.var_acc_cache_path.get() or "").strip()
                if not acc_dir:
                    self.var_acc_cache_size.set("(unknown)")
                    return

                acc_dir_q = self._bash_dq(acc_dir)
                cmd = f'if [ -d "{acc_dir_q}" ]; then du -sh "{acc_dir_q}"; else echo "0\t{acc_dir_q}"; fi'
                rc, out, err = run_wsl_command(
                    cmd,
                    distro=distro,
                    wsl_user=user,
                )

                size = "(unknown)"
                if out:
                    first = out.strip().splitlines()[0]
                    parts = first.split("\t")
                    if parts and parts[0].strip():
                        size = parts[0].strip()

                if rc != 0 and err:
                    self.log(f"[DeepLoc2][cache] du rc={rc}: {err.strip()}")

                self.var_acc_cache_size.set(size)
            finally:
                self._cache_refresh_lock.release()

        threading.Thread(target=worker, daemon=True).start()

    def _open_acc_cache_in_explorer(self):
        distro = (self.var_wsl_distro.get() or "").strip() or "Debian"
        user = (self.var_wsl_user.get() or "").strip() or "dash"
        acc_dir = (self.var_acc_cache_path.get() or "").strip()

        prefix = f"/home/{user}/"
        if not acc_dir.startswith(prefix):
            messagebox.showwarning(
                "Open folder",
                f"Best-effort open supports paths under {prefix}\n\nCurrent path:\n{acc_dir}",
            )
            return

        sub = acc_dir[len(prefix):].replace("/", "\\")
        unc = "\\\\wsl$\\" + distro + "\\home\\" + user + "\\" + sub
        try:
            os.startfile(unc)  # noqa: S606
        except Exception as e:
            messagebox.showerror("Open folder", f"Could not open:\n{unc}\n\n{e}")

    # ---------------- FASTA chunking helpers ----------------
    def _split_fasta_into_chunks(self, in_fa: str, chunks_dir: str, chunk_size: int):
        """
        Split FASTA into chunk files of <= chunk_size sequences (plain text only).
        Returns: (chunks, total_seqs)
          chunks: list of dicts: {path, start, end}
        """
        ensure_dir(chunks_dir)

        chunks = []
        total = 0

        out = None
        chunk_no = 0
        in_chunk = 0

        def open_new_chunk(start_idx: int):
            nonlocal out, chunk_no, in_chunk
            if out is not None:
                out.close()
                out = None
            chunk_no += 1
            in_chunk = 0
            p = os.path.join(chunks_dir, f"chunk_{chunk_no:05d}.fa")
            out = open(p, "w", encoding="utf-8", errors="ignore", newline="\n")
            chunks.append({"path": p, "start": start_idx, "end": start_idx - 1})

        with open(in_fa, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith(">"):
                    total += 1
                    if out is None or in_chunk >= chunk_size:
                        open_new_chunk(total)
                    in_chunk += 1
                    chunks[-1]["end"] = total
                if out is not None:
                    out.write(line)

        if out is not None:
            out.close()

        return chunks, total

    def _append_table_file(self, src: str, dst: str):
        """
        Append src to dst, trying to avoid duplicating an identical header line.
        """
        if not os.path.isfile(src):
            return

        if not os.path.isfile(dst) or os.path.getsize(dst) == 0:
            shutil.copy2(src, dst)
            return

        dst_header = ""
        try:
            with open(dst, "r", encoding="utf-8", errors="ignore") as f:
                dst_header = f.readline()
        except Exception:
            dst_header = ""

        with open(src, "r", encoding="utf-8", errors="ignore") as fin, open(dst, "a", encoding="utf-8", newline="\n") as fout:
            first = fin.readline()
            if dst_header and first == dst_header:
                pass
            else:
                fout.write(first)
            shutil.copyfileobj(fin, fout)

    # ---------------- Result exports (V2.1 + legacy V2.0) ----------------
    def _detect_delimiter_from_header_line(self, header_line: str) -> str:
        """Best-effort delimiter detection for DeepLoc2 output."""
        if "\t" in header_line:
            return "\t"
        if "," in header_line:
            return ","
        if ";" in header_line:
            return ";"
        return "\t"

    def _write_deeploc2_v20(self, src_v21_path: str, dst_v20_path: str) -> bool:
        """Create a legacy V2.0 export (subset of columns) from a V2.1 DeepLoc2 result file."""
        cols_v20 = [
            "Protein_ID",
            "Localizations",
            "Signals",
            "Cytoplasm",
            "Nucleus",
            "Extracellular",
            "Cell membrane",
            "Mitochondrion",
            "Plastid",
            "Endoplasmic reticulum",
            "Lysosome/Vacuole",
            "Golgi apparatus",
            "Peroxisome",
        ]

        if not src_v21_path or not os.path.isfile(src_v21_path):
            self.log(f"[DeepLoc2] WARNING: Cannot create V2.0 (source missing): {src_v21_path}")
            return False

        try:
            with open(src_v21_path, "r", encoding="utf-8", errors="ignore", newline="") as f:
                first_line = f.readline()
                if not first_line:
                    self.log(f"[DeepLoc2] WARNING: Cannot create V2.0 (empty source): {src_v21_path}")
                    return False
                delim = self._detect_delimiter_from_header_line(first_line)
                f.seek(0)

                reader = csv.reader(f, delimiter=delim)
                header_raw = next(reader, None)
                if not header_raw:
                    self.log(f"[DeepLoc2] WARNING: Cannot create V2.0 (no header): {src_v21_path}")
                    return False

                header = [str(x).strip() for x in header_raw]
                idx_exact = {name: i for i, name in enumerate(header)}
                idx_ci = {name.lower(): i for i, name in enumerate(header)}

                col_indices = []
                missing = []
                for col in cols_v20:
                    if col in idx_exact:
                        col_indices.append(idx_exact[col])
                    elif col.lower() in idx_ci:
                        col_indices.append(idx_ci[col.lower()])
                    else:
                        col_indices.append(None)
                        missing.append(col)

                if missing:
                    self.log(
                        "[DeepLoc2] WARNING: V2.0 export: missing columns in source -> will output blanks: "
                        + ", ".join(missing)
                    )

                os.makedirs(os.path.dirname(dst_v20_path), exist_ok=True)
                with open(dst_v20_path, "w", encoding="utf-8", newline="") as out:
                    writer = csv.writer(out, delimiter=delim, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
                    writer.writerow(cols_v20)
                    for row in reader:
                        if not row:
                            continue
                        out_row = []
                        for j in col_indices:
                            if j is None:
                                out_row.append("")
                            elif j < len(row):
                                out_row.append(row[j])
                            else:
                                out_row.append("")
                        writer.writerow(out_row)
        except Exception as e:
            self.log(f"[DeepLoc2] WARNING: Failed to create V2.0 export: {e}")
            return False

        return True

    def _export_deeploc2_results(self, src_path: str, return_dir: str):
        """Export both V2.1 (full) and V2.0 (legacy subset) into return_dir."""
        dst_v21 = os.path.join(return_dir, "Result_DeepLoc2.1.txt")
        dst_v20 = os.path.join(return_dir, "Result_DeepLoc2.0.txt")

        # V2.1 (copy as-is)
        try:
            shutil.copy2(src_path, dst_v21)
            self.log(f"[DeepLoc2] Copied V2.1 to return_to_R: {dst_v21}")
        except Exception as e:
            self.log(f"[DeepLoc2] WARNING: Could not copy V2.1 result file:\n  src={src_path}\n  dst={dst_v21}\n  err={e}")

        # V2.0 (subset)
        if self._write_deeploc2_v20(src_path, dst_v20):
            self.log(f"[DeepLoc2] Wrote V2.0 to return_to_R: {dst_v20}")
        else:
            self.log(f"[DeepLoc2] WARNING: V2.0 file was not created: {dst_v20}")

    # ---------------- Runner ----------------
    def run_tool(self, run_dir: str, return_dir: str, cancel_event: threading.Event) -> bool:
        tool = self.cfg.tool(self.TOOL_ID)
        if not bool(tool.get("enabled", True)):
            self.log("[DeepLoc2] Skipped (disabled).")
            return True

        model = (tool.get("model", "Fast") or "Fast").strip()
        device = (tool.get("device", "cpu") or "cpu").strip()
        offline = bool(tool.get("offline", True))
        plot_attention = bool(tool.get("plot_attention", False))

        chunked_requested = bool(tool.get("chunked", True))
        try:
            chunk_size = max(1, int(tool.get("chunk_size", 100)))
        except Exception:
            chunk_size = 100

        distro = (tool.get("wsl_distro", "") or "").strip() or "Debian"
        user = (tool.get("wsl_user", "") or "").strip() or "dash"

        win_fa = (self.cfg.aa_fasta or "").strip()
        if not win_fa:
            self.log("[DeepLoc2] ERROR: AA FASTA (protein) path is empty in Inputs tab.")
            return False
        if not os.path.isfile(win_fa):
            self.log(f"[DeepLoc2] ERROR: AA FASTA file not found: {win_fa}")
            return False

        if not run_dir:
            self.log("[DeepLoc2] ERROR: Output directory is empty.")
            return False

        ensure_dir(run_dir)
        ensure_dir(return_dir)

        # Decide chunked vs single-run (AUTO FALLBACK)
        chunked_effective = chunked_requested

        n_for_decision = None
        if chunked_effective:
            # We do NOT support .gz chunk splitting; auto fallback to single-run
            if win_fa.lower().endswith(".gz"):
                self.log("[DeepLoc2] Chunked mode: .gz FASTA is not supported for splitting -> running single-run.")
                chunked_effective = False
            else:
                n_for_decision = count_fasta_records(win_fa)
                if n_for_decision <= 0:
                    self.log("[DeepLoc2] ERROR: Could not count sequences (no '>' headers found).")
                    return False
                if n_for_decision <= chunk_size:
                    self.log(f"[DeepLoc2] Chunked mode: N={n_for_decision} <= chunk_size={chunk_size} -> running single-run (no split/merge).")
                    chunked_effective = False

        started_dt = datetime.now()
        started_ts = time.time()
        self.log(f"[DeepLoc2] Started: {started_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        self.log(f"[DeepLoc2] Using WSL distro: {distro}")
        self.log(f"[DeepLoc2] Using WSL user: {user}")
        self.log(f"[DeepLoc2] Running: mode={model} device={device} plot_attention={plot_attention} offline={offline}")
        self.log(f"[DeepLoc2] chunked_requested={chunked_requested} chunked_effective={chunked_effective} chunk_size={chunk_size}")
        self.log(f"[DeepLoc2][DBG] win_fa={win_fa}")

        # ---------------- Single run ----------------
        if not chunked_effective:
            wsl_fa = win_to_wsl_path(win_fa)
            wsl_out = win_to_wsl_path(run_dir)

            bash_cmd = self._build_deeploc2_run_cmd(
                fasta_wsl=wsl_fa,
                out_wsl=wsl_out,
                model=model,
                device=device,
                plot_attention=plot_attention,
                user=user,
                offline=offline,
            )

            self.log(f"[DeepLoc2][DBG] bash: {bash_cmd}")

            rc, out, err = self._run_wsl(
                bash_cmd,
                distro=distro,
                user=user,
                cancel_event=cancel_event,
            )

            self.log(f"[DeepLoc2][DBG] rc={rc}")

            if cancel_event.is_set():
                self.log("[DeepLoc2] Cancel requested.")
                return False

            if rc != 0:
                if err:
                    tail = "\n".join(err.strip().splitlines()[-20:])
                    self.log("[DeepLoc2][stderr][tail]\n" + tail)
                self.log(f"[DeepLoc2] ERROR: DeepLoc2 failed (rc={rc}).")
                return False

            newest = self._find_newest_result_file(run_dir)
            if newest:
                self._export_deeploc2_results(newest, return_dir)
            else:
                self.log("[DeepLoc2] WARNING: No obvious output file found to copy into return_to_R.")

            total_elapsed = time.time() - started_ts
            self.log(f"[DeepLoc2] Done. Total elapsed: {_fmt_seconds(total_elapsed)}")
            self._refresh_acc_cache_size_async()
            return True

        # ---------------- Chunked run ----------------
        total_seqs = n_for_decision if (n_for_decision is not None) else count_fasta_records(win_fa)
        if total_seqs <= 0:
            self.log("[DeepLoc2] ERROR: Could not count sequences (no '>' headers found).")
            return False

        self.log(f"[DeepLoc2] Input sequences: {total_seqs:,}")

        chunks_dir = os.path.join(run_dir, "_tmp_deeploc2_chunks_fasta")
        chunk_out_base = os.path.join(run_dir, "DeepLoc2_chunks_output")
        ensure_dir(chunks_dir)
        ensure_dir(chunk_out_base)

        try:
            chunks, total2 = self._split_fasta_into_chunks(win_fa, chunks_dir, chunk_size)
        except Exception as e:
            self.log(f"[DeepLoc2] ERROR: Could not split FASTA into chunks: {e}")
            return False

        if total2 != total_seqs:
            total_seqs = total2

        if not chunks:
            self.log("[DeepLoc2] ERROR: Chunk splitting produced 0 chunks.")
            return False

        merged_path = os.path.join(run_dir, "Result_DeepLoc2.1_merged.txt")
        try:
            if os.path.isfile(merged_path):
                os.remove(merged_path)
        except Exception:
            pass

        n_chunks = len(chunks)
        self.log(f"[DeepLoc2] Chunks: {n_chunks} (chunk_size={chunk_size})")

        chunk_durations = []  # seconds
        processed = 0

        for i, ch in enumerate(chunks, start=1):
            if cancel_event.is_set():
                self.log("[DeepLoc2] Cancel requested.")
                return False

            c_path = ch["path"]
            c_start = ch["start"]
            c_end = ch["end"]
            processed = c_end

            c_out_dir = os.path.join(chunk_out_base, f"chunk_{i:05d}")
            ensure_dir(c_out_dir)

            elapsed_so_far = time.time() - started_ts
            if chunk_durations:
                avg = sum(chunk_durations) / len(chunk_durations)
                eta = avg * (n_chunks - (i - 1))
                self.log(
                    f"[DeepLoc2] Progress: chunk {i}/{n_chunks}  (seq {c_start:,}–{c_end:,} of {total_seqs:,})"
                    f"  | elapsed={_fmt_seconds(elapsed_so_far)}  | avg/chunk={_fmt_seconds(avg)}  | remaining~{_fmt_seconds(eta)}"
                )
            else:
                self.log(
                    f"[DeepLoc2] Progress: chunk {i}/{n_chunks}  (seq {c_start:,}–{c_end:,} of {total_seqs:,})"
                    f"  | elapsed={_fmt_seconds(elapsed_so_far)}  | avg/chunk=?  | remaining=?"
                )

            wsl_c_fa = win_to_wsl_path(c_path)
            wsl_c_out = win_to_wsl_path(c_out_dir)

            bash_cmd = self._build_deeploc2_run_cmd(
                fasta_wsl=wsl_c_fa,
                out_wsl=wsl_c_out,
                model=model,
                device=device,
                plot_attention=plot_attention,
                user=user,
                offline=offline,
            )

            chunk_t0 = time.time()

            rc, out, err = self._run_wsl(
                bash_cmd,
                distro=distro,
                user=user,
                cancel_event=cancel_event,
            )

            chunk_dt = time.time() - chunk_t0
            chunk_durations.append(chunk_dt)

            self.log(f"[DeepLoc2][DBG] chunk {i}/{n_chunks} rc={rc}  duration={_fmt_seconds(chunk_dt)}")

            if cancel_event.is_set():
                self.log("[DeepLoc2] Cancel requested.")
                return False

            if rc != 0:
                if err:
                    tail = "\n".join(err.strip().splitlines()[-20:])
                    self.log("[DeepLoc2][stderr][tail]\n" + tail)
                self.log(f"[DeepLoc2] ERROR: DeepLoc2 failed on chunk {i}/{n_chunks} (rc={rc}).")
                return False

            newest = self._find_newest_result_file(c_out_dir)
            if newest:
                try:
                    self._append_table_file(newest, merged_path)
                except Exception as e:
                    self.log(f"[DeepLoc2] WARNING: Could not merge chunk output:\n  src={newest}\n  err={e}")
            else:
                self.log(f"[DeepLoc2] WARNING: No obvious result file found in chunk output folder: {c_out_dir}")

            # Updated ETA after completing this chunk
            avg_done = sum(chunk_durations) / len(chunk_durations)
            remaining_chunks = n_chunks - i
            eta_done = avg_done * remaining_chunks
            elapsed_done = time.time() - started_ts

            self.log(
                f"[DeepLoc2] Progress: {processed:,}/{total_seqs:,} sequences processed"
                f"  | chunk_done={_fmt_seconds(chunk_dt)}"
                f"  | avg/chunk={_fmt_seconds(avg_done)}"
                f"  | remaining~{_fmt_seconds(eta_done)}"
                f"  | elapsed={_fmt_seconds(elapsed_done)}"
            )

        if os.path.isfile(merged_path) and os.path.getsize(merged_path) > 0:
            self._export_deeploc2_results(merged_path, return_dir)
        else:
            self.log("[DeepLoc2] WARNING: Merged output file is missing or empty.")

        try:
            shutil.rmtree(chunks_dir, ignore_errors=True)
        except Exception:
            pass

        total_elapsed = time.time() - started_ts
        if chunk_durations:
            self.log(f"[DeepLoc2] Done. Total elapsed: {_fmt_seconds(total_elapsed)} | avg/chunk={_fmt_seconds(sum(chunk_durations)/len(chunk_durations))}")
        else:
            self.log(f"[DeepLoc2] Done. Total elapsed: {_fmt_seconds(total_elapsed)}")

        self._refresh_acc_cache_size_async()
        return True

    def _find_newest_result_file(self, run_dir: str) -> str:
        exts = (".txt", ".tsv", ".csv")
        newest_path = ""
        newest_mtime = -1.0

        try:
            for fn in os.listdir(run_dir):
                low = fn.lower()
                if not low.endswith(exts):
                    continue
                p = os.path.join(run_dir, fn)
                if not os.path.isfile(p):
                    continue
                try:
                    mt = os.path.getmtime(p)
                except Exception:
                    continue
                if mt > newest_mtime:
                    newest_mtime = mt
                    newest_path = p
        except Exception:
            return ""

        return newest_path