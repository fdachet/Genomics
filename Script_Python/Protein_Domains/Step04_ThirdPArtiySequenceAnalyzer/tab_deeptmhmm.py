import os
import re
import time
import shlex
import shutil
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from shared_config import AppConfig
from shared_utils import ensure_dir, win_to_wsl_path


def _now_ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _run_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _sanitize_nulls(s: str) -> str:
    return (s or "").replace("\x00", "")


def _bash_quote(s: str) -> str:
    # Safe single-quote for bash -lc strings (no variable expansion)
    return "'" + (s or "").replace("'", "'\"'\"'") + "'"


def _norm_abs_win(p: str) -> str:
    if not p:
        return ""
    p = os.path.expandvars(os.path.expanduser(p))
    return os.path.abspath(p)


def _list_wsl_distros() -> list[str]:
    try:
        cp = subprocess.run(
            ["wsl.exe", "-l", "-q"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        out = _sanitize_nulls(cp.stdout or "")
        distros = [ln.strip() for ln in out.splitlines() if ln.strip()]
        return distros
    except Exception:
        return []

def _run_subprocess_capture(
    argv: list[str],
    timeout: float = 20.0,
) -> tuple[int, str]:
    """
    Run a process and capture merged stdout+stderr.
    Returns (rc, output_text).
    """
    try:
        cp = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return int(cp.returncode or 0), _sanitize_nulls(cp.stdout or "")
    except Exception as e:
        return 999, str(e)


def _detect_wsl_run_user(distro: str, log_cb=None) -> str:
    """
    Pick a safe non-root WSL user when possible.
    If the default distro user is already non-root, keep it.
    If the default user is root, fall back to the first normal user (uid >= 1000)
    by parsing getent/passwd output in Python instead of relying on awk.
    Returns '' to use the distro default when no better choice is found.
    """
    distro = (distro or "").strip()
    if not distro:
        return ""

    rc, out = _run_subprocess_capture(
        ["wsl.exe", "-d", distro, "--", "bash", "--noprofile", "--norc", "-c", "id -un 2>/dev/null || true"]
    )
    cur_user = ""
    for ln in (out or "").splitlines():
        ln = (ln or "").strip()
        if ln:
            cur_user = ln

    if cur_user and cur_user != "root":
        if log_cb:
            log_cb(f"[DeepTMHMM] Using WSL user: {cur_user} (distro default)")
        return ""

    rc2, out2 = _run_subprocess_capture(
        [
            "wsl.exe",
            "-d",
            distro,
            "--",
            "bash",
            "--noprofile",
            "--norc",
            "-c",
            "getent passwd 2>/dev/null || cat /etc/passwd 2>/dev/null || true",
        ]
    )
    alt = ""
    for ln in (out2 or "").splitlines():
        ln = (ln or "").strip()
        if not ln or ":" not in ln:
            continue
        parts = ln.split(":")
        if len(parts) < 7:
            continue
        user = parts[0].strip()
        try:
            uid = int(parts[2].strip())
        except Exception:
            continue
        shell = parts[6].strip().lower()
        if user in {"root", "nobody"}:
            continue
        if uid < 1000:
            continue
        if shell.endswith("/false") or shell.endswith("nologin"):
            continue
        alt = user
        break

    if alt:
        if log_cb:
            log_cb(f"[DeepTMHMM] Using WSL user: {alt} (auto-detected; default user was root)")
        return alt

    if log_cb and cur_user == "root":
        log_cb("[DeepTMHMM] WARNING: WSL default user is root and no normal user could be auto-detected. Using root.")
    return ""


def _get_wsl_current_user(distro: str, user: str = "") -> str:
    distro = (distro or "").strip()
    if not distro:
        return ""
    rc, out = _run_subprocess_capture(_wsl_bash_argv(distro, "id -un 2>/dev/null || true", user))
    for ln in (out or "").splitlines():
        ln = (ln or "").strip()
        if ln:
            return ln
    return ""


def _read_wsl_passwd_entries(distro: str) -> list[tuple[str, int, str, str]]:
    distro = (distro or "").strip()
    if not distro:
        return []
    rc, out = _run_subprocess_capture([
        "wsl.exe", "-d", distro, "--", "bash", "--noprofile", "--norc", "-c",
        "cat /etc/passwd 2>/dev/null || true",
    ])
    rows: list[tuple[str, int, str, str]] = []
    for ln in (out or "").splitlines():
        ln = (ln or "").strip()
        if not ln or ":" not in ln:
            continue
        parts = ln.split(":")
        if len(parts) < 7:
            continue
        user = parts[0].strip()
        try:
            uid = int(parts[2].strip())
        except Exception:
            uid = -1
        home = parts[5].strip()
        shell = parts[6].strip()
        rows.append((user, uid, home, shell))
    return rows


def _resolve_wsl_home(distro: str, user: str, log_cb=None) -> str:
    user = (user or "").strip()
    if not user:
        return ""
    for row_user, uid, home, shell in _read_wsl_passwd_entries(distro):
        if row_user == user and home:
            return home
    fallback = "/root" if user == "root" else f"/home/{user}"
    rc, out = _run_subprocess_capture(_wsl_bash_argv(distro, f"test -d {_bash_quote(fallback)} && echo OK || true", user))
    if "OK" in (out or ""):
        if log_cb:
            log_cb(f"[DeepTMHMM] WARNING: Home for WSL user {user} not found in /etc/passwd; using existing folder {fallback}")
        return fallback
    return fallback


def _wsl_bash_argv(distro: str, bash_cmd: str, user: str = "") -> list[str]:
    argv = ["wsl.exe", "-d", distro]
    user = (user or "").strip()
    if user:
        argv.extend(["-u", user])
    argv.extend(["--", "bash", "--noprofile", "--norc", "-c", bash_cmd])
    return argv



def _run_subprocess_stream(
    argv: list[str],
    log_cb,
    cancel_event: threading.Event | None = None,
    name: str = "PROC",
) -> int:
    """
    Run a process and stream stdout+stderr to log_cb.
    Returns process return code.
    """
    if log_cb:
        log_cb(f"[{name}] CMD: {argv}")

    try:
        p = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            universal_newlines=True,
        )
    except Exception as e:
        if log_cb:
            log_cb(f"[{name}] ERROR: failed to start process: {e}")
        return 999

    rc = 999

    try:
        assert p.stdout is not None
        for line in p.stdout:
            if cancel_event and cancel_event.is_set():
                break
            if log_cb:
                log_cb(line.rstrip("\n"))
    finally:
        if cancel_event and cancel_event.is_set():
            try:
                if log_cb:
                    log_cb(f"[{name}] Cancel requested -> terminating...")
                p.terminate()
            except Exception:
                pass
            try:
                p.wait(timeout=2)
            except Exception:
                try:
                    if log_cb:
                        log_cb(f"[{name}] Killing...")
                    p.kill()
                except Exception:
                    pass

        try:
            rc = p.wait(timeout=5)
        except Exception:
            rc = p.poll() if p.poll() is not None else 998

    if log_cb:
        log_cb(f"[{name}] END rc={rc}")
    return int(rc) if rc is not None else 998


class TabDeepTMHMM(ttk.Frame):
    TOOL_ID = "DeepTMHMM"

    def __init__(self, parent, cfg: AppConfig, log_cb=None, run_cb=None):
        super().__init__(parent)
        self.cfg = cfg
        self.log_cb = log_cb
        self.run_cb = run_cb

        # UI vars
        self.var_enabled = tk.BooleanVar(value=True)
        self.var_distro = tk.StringVar(value="Debian")
        self.var_tool_dir_win = tk.StringVar(value="")
        self.var_out_subdir = tk.StringVar(value="DeepTMHMM_output")
        self.var_out_policy = tk.StringVar(value="overwrite")  # fail / overwrite / unique
        self.var_venv_name = tk.StringVar(value="deeptmhmm_py38")
        self.var_extra_args = tk.StringVar(value="")

        # read-only display from Inputs tab
        self.var_inputs_aa = tk.StringVar(value="")
        self.var_inputs_out = tk.StringVar(value="")

        # button refs
        self.btn_enabled = None

        # build UI
        self._build_ui()
        self.refresh_from_cfg()

    # ---------------- Logging ----------------
    def _log(self, msg: str):
        if self.log_cb:
            self.log_cb(msg)

    # ---------------- Enabled toggle button ----------------
    def _update_enabled_button(self):
        if self.btn_enabled is None:
            return

        enabled = bool(self.var_enabled.get())

        # Colors requested:
        # - enabled: dark green
        # - disabled: grey
        if enabled:
            bg = "green"      # dark green  "#006400"
            fg = "#FFFFFF"      # white text
            abg = "#0B7A0B"     # a slightly lighter green on click
            txt = "Enable: ON"
        else:
            bg = "gray60"      # grey
            fg = "white"      # black text
            abg = "#B5B5B5"     # lighter grey on click
            txt = "Enable: OFF"

        try:
            self.btn_enabled.configure(
                text=txt,
                background=bg,
                foreground=fg,
                activebackground=abg,
                activeforeground=fg,
            )
        except Exception:
            # If a platform/theme ignores some options, keep functional behavior anyway.
            pass

    def _toggle_enabled(self):
        self.var_enabled.set(not bool(self.var_enabled.get()))
        self._update_enabled_button()
        self.save_to_cfg()

    # ---------------- UI ----------------
    def _build_ui(self):
        self.columnconfigure(1, weight=1)

        r = 0

        # Enable + Run row
        top = ttk.Frame(self)
        top.grid(row=r, column=0, columnspan=3, sticky="ew", padx=10, pady=(10, 6))
        top.columnconfigure(2, weight=1)

        # Replace the Checkbutton with a pressable toggle button (tk.Button so we can color it)
        self.btn_enabled = tk.Button(
            top,
            text="Enabled (participates in 'Run All')",
            command=self._toggle_enabled,
            relief="raised",
            bd=1,
            padx=10,
            pady=4,
        )
        self.btn_enabled.grid(row=0, column=0, sticky="w")

        ttk.Button(
            top,
            text="Run DeepTMHMM",
            command=self._click_run,
        ).grid(row=0, column=1, padx=(12, 0))

        ttk.Label(
            top,
            text="Runs predict.py inside your WSL1 Debian environment (CPU).",
            foreground="#444",
        ).grid(row=0, column=2, sticky="w", padx=(12, 0))

        # set initial colors
        self._update_enabled_button()

        r += 1

        # Inputs (read-only)
        box_inputs = ttk.LabelFrame(self, text="Inputs coming from the Inputs tab (read-only)", padding=10)
        box_inputs.grid(row=r, column=0, columnspan=3, sticky="ew", padx=10, pady=6)
        box_inputs.columnconfigure(1, weight=1)

        ttk.Label(box_inputs, text="AA FASTA (protein):").grid(row=0, column=0, sticky="w", pady=2)
        e1 = ttk.Entry(box_inputs, textvariable=self.var_inputs_aa, state="readonly")
        e1.grid(row=0, column=1, sticky="ew", padx=(8, 8), pady=2)
        ttk.Button(box_inputs, text="Open folder", command=self._open_aa_folder).grid(row=0, column=2, pady=2)

        ttk.Label(box_inputs, text="Pipeline OutputDir (Windows):").grid(row=1, column=0, sticky="w", pady=2)
        e2 = ttk.Entry(box_inputs, textvariable=self.var_inputs_out, state="readonly")
        e2.grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=2)
        ttk.Button(box_inputs, text="Open folder", command=self._open_out_folder).grid(row=1, column=2, pady=2)

        ttk.Label(
            box_inputs,
            text="Note: If a sequence has 0 predicted TMRs, DeepTMHMM may not produce plot.png (that is expected).",
            foreground="#444",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        r += 1

        # Config (Windows only)
        box_cfg = ttk.LabelFrame(self, text="DeepTMHMM configuration (Windows paths only)", padding=10)
        box_cfg.grid(row=r, column=0, columnspan=3, sticky="ew", padx=10, pady=6)
        box_cfg.columnconfigure(1, weight=1)

        ttk.Label(box_cfg, text="WSL distro:").grid(row=0, column=0, sticky="w", pady=2)
        self.cmb_distro = ttk.Combobox(box_cfg, textvariable=self.var_distro, values=[], state="readonly", width=22)
        self.cmb_distro.grid(row=0, column=1, sticky="w", padx=(8, 8), pady=2)
        ttk.Button(box_cfg, text="List distros", command=self._refresh_distros).grid(row=0, column=2, pady=2)
        ttk.Label(
            box_cfg,
            text="Pick your WSL1 Debian distro (example: Debian).",
            foreground="#444",
        ).grid(row=0, column=3, sticky="w", padx=(10, 0))

        ttk.Label(box_cfg, text="DeepTMHMM folder (Windows):").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Entry(box_cfg, textvariable=self.var_tool_dir_win).grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=2)
        ttk.Button(box_cfg, text="Browse", command=self._browse_tool_dir).grid(row=1, column=2, pady=2)
        ttk.Label(
            box_cfg,
            text="Folder containing predict.py + model files (deeptmhmm_cv_*.model, esm_model_*.pt, etc.).",
            foreground="#444",
        ).grid(row=1, column=3, sticky="w", padx=(10, 0))

        ttk.Label(box_cfg, text="Output subfolder name:").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Entry(box_cfg, textvariable=self.var_out_subdir, width=28).grid(row=2, column=1, sticky="w", padx=(8, 8), pady=2)
        ttk.Label(
            box_cfg,
            text="Created inside the pipeline OutputDir (Inputs tab).",
            foreground="#444",
        ).grid(row=2, column=3, sticky="w", padx=(10, 0))

        ttk.Label(box_cfg, text="Output policy:").grid(row=3, column=0, sticky="w", pady=2)
        cmb_pol = ttk.Combobox(
            box_cfg,
            textvariable=self.var_out_policy,
            values=["overwrite", "fail", "unique"],
            state="readonly",
            width=22,
        )
        cmb_pol.grid(row=3, column=1, sticky="w", padx=(8, 8), pady=2)
        ttk.Label(
            box_cfg,
            text="overwrite: delete output folder first | fail: error if exists | unique: add timestamp suffix",
            foreground="#444",
        ).grid(row=3, column=3, sticky="w", padx=(10, 0))

        ttk.Label(box_cfg, text="WSL venv name:").grid(row=4, column=0, sticky="w", pady=2)
        ttk.Entry(box_cfg, textvariable=self.var_venv_name, width=28).grid(row=4, column=1, sticky="w", padx=(8, 8), pady=2)
        ttk.Label(
            box_cfg,
            text="GUI uses: $HOME/venvs/<name>/bin/python  (no need to type any WSL paths).",
            foreground="#444",
        ).grid(row=4, column=3, sticky="w", padx=(10, 0))

        ttk.Label(box_cfg, text="Extra args (optional):").grid(row=5, column=0, sticky="w", pady=2)
        ttk.Entry(box_cfg, textvariable=self.var_extra_args).grid(row=5, column=1, sticky="ew", padx=(8, 8), pady=2)
        ttk.Label(
            box_cfg,
            text="Passed to predict.py (advanced; usually leave empty).",
            foreground="#444",
        ).grid(row=5, column=3, sticky="w", padx=(10, 0))

        btns = ttk.Frame(box_cfg)
        btns.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        ttk.Button(btns, text="Apply (save settings)", command=self.save_to_cfg).grid(row=0, column=0, padx=(0, 10))
        ttk.Button(btns, text="Test WSL (quick)", command=self._test_wsl_async).grid(row=0, column=1, padx=(0, 10))
        ttk.Button(btns, text="Test DeepTMHMM (imports)", command=self._test_deeptmhmm_async).grid(row=0, column=2, padx=(0, 10))
        ttk.Label(
            btns,
            text="Tests run in background (no GUI freeze).",
            foreground="#444",
        ).grid(row=0, column=3, sticky="w")

        r += 1

        # Install help (script embedded)
        box_install = ttk.LabelFrame(self, text="How to install DeepTMHMM in WSL1 Debian (script)", padding=10)
        box_install.grid(row=r, column=0, columnspan=3, sticky="nsew", padx=10, pady=6)
        box_install.columnconfigure(0, weight=1)
        self.rowconfigure(r, weight=1)

        ttk.Label(
            box_install,
            text="Copy/paste the script below into a .sh file. If you edit it in Notepad++, convert EOL to Unix (LF) to avoid WSL bash errors.",
            foreground="#222",
        ).grid(row=0, column=0, sticky="w")

        self.txt_install = tk.Text(box_install, height=18, wrap="none")
        self.txt_install.grid(row=1, column=0, sticky="nsew", pady=(6, 6))
        y = ttk.Scrollbar(box_install, orient="vertical", command=self.txt_install.yview)
        y.grid(row=1, column=1, sticky="ns", pady=(6, 6))
        self.txt_install.configure(yscrollcommand=y.set)

        x = ttk.Scrollbar(box_install, orient="horizontal", command=self.txt_install.xview)
        x.grid(row=2, column=0, sticky="ew")
        self.txt_install.configure(xscrollcommand=x.set)

        bot = ttk.Frame(box_install)
        bot.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(bot, text="Copy script to clipboard", command=self._copy_install_clipboard).grid(row=0, column=0, padx=(0, 10))
        ttk.Button(bot, text="Save script as .sh", command=self._save_install_script).grid(row=0, column=1, padx=(0, 10))
        ttk.Label(
            bot,
            text="Tip: If you still get CRLF issues:  sed -i 's/\\r$//' script.sh  &&  sed -i '1s/^\\xEF\\xBB\\xBF//' script.sh",
            foreground="#444",
        ).grid(row=0, column=2, sticky="w")

        self._fill_install_script()

    # ---------------- Install script text ----------------
    def _fill_install_script(self):
        script = r"""#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# DeepTMHMM on Debian (WSL1) - CPU install using pyenv + Python 3.8
#
# IMPORTANT (Notepad++):
# - Save as:
#     * EOL: Unix (LF)            (Edit -> EOL Conversion -> Unix (LF))
#     * Encoding: UTF-8 no BOM    (Encoding -> UTF-8 (without BOM))
#
# If you still get weird bash errors (CRLF/BOM), run:
#   sed -i 's/\r$//' install_deeptmhmm.sh
#   sed -i '1s/^\xEF\xBB\xBF//' install_deeptmhmm.sh
#
# Usage:
#   1) In Windows, put DeepTMHMM folder somewhere (contains predict.py, requirements.txt, models)
#   2) In WSL, cd to that folder via /mnt/c/... then run this script:
#        bash ./install_deeptmhmm.sh
#
# GUI expectation after install:
#   - venv at:  $HOME/venvs/deeptmhmm_py38
#   - python:   $HOME/venvs/deeptmhmm_py38/bin/python
###############################################################################

PY38_VERSION="3.8.18"
VENV_NAME="deeptmhmm_py38"
VENV_DIR="$HOME/venvs/$VENV_NAME"

TORCH_CPU_WHL="https://download.pytorch.org/whl/cpu/torch-1.5.0%2Bcpu-cp38-cp38-linux_x86_64.whl"

echo "=== DeepTMHMM WSL1 CPU install ==="
echo "Tool folder (current): $PWD"
echo "Venv dir: $VENV_DIR"
echo

if [[ ! -f "predict.py" ]]; then
  echo "ERROR: predict.py not found in current directory."
  echo "Please: cd into the DeepTMHMM folder (where predict.py is) and rerun."
  exit 2
fi
if [[ ! -f "requirements.txt" ]]; then
  echo "ERROR: requirements.txt not found in current directory."
  exit 3
fi

echo "[1/8] System dependencies..."
sudo apt-get update
sudo apt-get install -y \
  build-essential curl git ca-certificates make llvm xz-utils \
  zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev libncursesw5-dev \
  libffi-dev libssl-dev liblzma-dev tk-dev libxml2-dev libxmlsec1-dev \
  libhdf5-dev

echo "[2/8] Install/initialize pyenv..."
export PYENV_ROOT="$HOME/.pyenv"
if [[ ! -d "$PYENV_ROOT" ]]; then
  curl -fsSL https://pyenv.run | bash
fi
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"

echo "[3/8] Install Python $PY38_VERSION via pyenv (if needed)..."
pyenv install -s "$PY38_VERSION"
PY38_BIN="$PYENV_ROOT/versions/$PY38_VERSION/bin/python"
"$PY38_BIN" -V

echo "[4/8] Create venv..."
mkdir -p "$(dirname "$VENV_DIR")"
rm -rf "$VENV_DIR"
"$PY38_BIN" -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo "[5/8] Upgrade pip + build helpers..."
python -m pip install -U pip
python -m pip install wheel Cython==0.29.37 pkgconfig==1.5.5

echo "[6/8] Install CPU torch..."
python -m pip install "$TORCH_CPU_WHL"

echo "[7/8] Install requirements WITHOUT torch pin..."
REQ_NO_TORCH="/tmp/deeptmhmm_requirements_no_torch.txt"
grep -vE '^[[:space:]]*torch([=<>! ].*)?$' requirements.txt > "$REQ_NO_TORCH" || true
python -m pip install -r "$REQ_NO_TORCH"

echo "[8/8] Smoke test + run sample..."
python -c "import torch; print('torch:', torch.__version__); print('cuda available:', torch.cuda.is_available())"
python -c "import esm; print('esm: OK')"
python -c "import h5py; print('h5py:', h5py.__version__)"

if [[ ! -f "sample.fasta" ]]; then
  cat > sample.fasta <<'EOF'
>test
MKTIIALSYIFCLVFADYKDDDDK
EOF
fi

rm -rf result_wsl1_test
python predict.py --fasta sample.fasta --output-dir result_wsl1_test

echo
echo "=== SUCCESS ==="
echo "Output: $PWD/result_wsl1_test"
echo "Note: WSL1 is CPU only (cuda available should be False)"
"""
        self.txt_install.delete("1.0", "end")
        self.txt_install.insert("1.0", script)
        self.txt_install.configure(state="disabled")

    def _copy_install_clipboard(self):
        try:
            self.clipboard_clear()
            txt = self.txt_install.get("1.0", "end-1c")
            self.clipboard_append(txt)
            self._log("[DeepTMHMM] Install script copied to clipboard.")
        except Exception as e:
            messagebox.showerror("Clipboard", str(e))

    def _save_install_script(self):
        p = filedialog.asksaveasfilename(
            title="Save install script",
            defaultextension=".sh",
            filetypes=[("Shell script", "*.sh"), ("All files", "*.*")],
        )
        if not p:
            return
        try:
            txt = self.txt_install.get("1.0", "end-1c")
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(txt)
            self._log(f"[DeepTMHMM] Saved install script: {p}")
        except Exception as e:
            messagebox.showerror("Save script failed", str(e))

    # ---------------- File/folder helpers ----------------
    def _browse_tool_dir(self):
        p = filedialog.askdirectory(title="Select DeepTMHMM folder (contains predict.py)")
        if p:
            self.var_tool_dir_win.set(p)

    def _open_aa_folder(self):
        p = (self.var_inputs_aa.get() or "").strip()
        if not p:
            return
        d = os.path.dirname(p)
        if os.path.isdir(d):
            try:
                os.startfile(d)
            except Exception:
                pass

    def _open_out_folder(self):
        d = (self.var_inputs_out.get() or "").strip()
        if os.path.isdir(d):
            try:
                os.startfile(d)
            except Exception:
                pass

    # ---------------- Distros ----------------
    def _refresh_distros(self):
        distros = _list_wsl_distros()
        self.cmb_distro["values"] = distros
        if distros:
            cur = (self.var_distro.get() or "").strip()
            if not cur or cur not in distros:
                self.var_distro.set(distros[0])
        else:
            self.var_distro.set("")
        self._log(f"[DeepTMHMM] Distros: {distros}")

    # ---------------- Config plumbing ----------------
    def save_to_cfg(self):
        t = self.cfg.tool(self.TOOL_ID)
        t["enabled"] = bool(self.var_enabled.get())
        t["distro"] = (self.var_distro.get() or "").strip()
        t["tool_dir_win"] = (self.var_tool_dir_win.get() or "").strip()
        t["out_subdir"] = (self.var_out_subdir.get() or "").strip() or "DeepTMHMM_output"
        t["out_policy"] = (self.var_out_policy.get() or "").strip() or "overwrite"
        t["venv_name"] = (self.var_venv_name.get() or "").strip() or "deeptmhmm_py38"
        t["extra_args"] = (self.var_extra_args.get() or "").strip()
        self._update_enabled_button()
        self._log("[DeepTMHMM] Settings saved to config.")

    def refresh_from_cfg(self):
        # Inputs
        self.var_inputs_aa.set(self.cfg.aa_fasta or "")
        self.var_inputs_out.set(self.cfg.out_dir or "")

        # Tool settings
        t = self.cfg.tool(self.TOOL_ID)
        self.var_enabled.set(bool(t.get("enabled", True)))
        self.var_distro.set(str(t.get("distro", "Debian") or "Debian"))
        self.var_tool_dir_win.set(str(t.get("tool_dir_win", "") or ""))
        self.var_out_subdir.set(str(t.get("out_subdir", "DeepTMHMM_output") or "DeepTMHMM_output"))
        self.var_out_policy.set(str(t.get("out_policy", "overwrite") or "overwrite"))
        self.var_venv_name.set(str(t.get("venv_name", "deeptmhmm_py38") or "deeptmhmm_py38"))
        self.var_extra_args.set(str(t.get("extra_args", "") or ""))

        # reflect toggle state visually
        self._update_enabled_button()

        # Distros list (best-effort)
        self._refresh_distros()

    # ---------------- Public API expected by main_app ----------------
    def run_tool(self, run_dir: str, return_to_r_dir: str, cancel_event: threading.Event) -> bool:
        """
        Called by main_app worker thread.
        Must return True/False.
        """
        self.save_to_cfg()

        # Validate inputs from Inputs tab
        aa_fasta_win = _norm_abs_win(self.cfg.aa_fasta or "")
        if not aa_fasta_win or not os.path.isfile(aa_fasta_win):
            self._log("[DeepTMHMM] ERROR: AA FASTA from Inputs tab is missing or does not exist.")
            return False

        # Tool folder
        tool_dir_win = _norm_abs_win((self.var_tool_dir_win.get() or "").strip())
        if not tool_dir_win or not os.path.isdir(tool_dir_win):
            self._log("[DeepTMHMM] ERROR: Tool folder is missing/invalid (set 'DeepTMHMM folder (Windows)').")
            return False

        predict_py = os.path.join(tool_dir_win, "predict.py")
        if not os.path.isfile(predict_py):
            self._log(f"[DeepTMHMM] ERROR: predict.py not found in tool folder: {tool_dir_win}")
            return False

        distro = (self.var_distro.get() or "").strip()
        if not distro:
            self._log("[DeepTMHMM] ERROR: WSL distro is empty.")
            return False

        # Output folder inside pipeline run_dir
        out_sub = (self.var_out_subdir.get() or "").strip() or "DeepTMHMM_output"
        out_policy = (self.var_out_policy.get() or "overwrite").strip()

        # sanitize output subfolder name
        if any(c in out_sub for c in ("/", "\\", ":", "\0")) or out_sub in (".", ".."):
            self._log("[DeepTMHMM] ERROR: Output subfolder name must be a simple folder name (no slashes).")
            return False

        out_dir_win_base = os.path.join(_norm_abs_win(run_dir), out_sub)

        if out_policy == "unique":
            out_dir_win = out_dir_win_base + "_" + _run_id()
        else:
            out_dir_win = out_dir_win_base

        # Prepare WSL paths internally (GUI stays Windows-only)
        tool_dir_wsl = win_to_wsl_path(tool_dir_win)
        fasta_wsl = win_to_wsl_path(aa_fasta_win)
        out_dir_wsl = win_to_wsl_path(out_dir_win)

        venv_name = (self.var_venv_name.get() or "").strip() or "deeptmhmm_py38"
        wsl_user = _detect_wsl_run_user(distro, self._log)
        effective_user = _get_wsl_current_user(distro, wsl_user) or (wsl_user or "root")
        user_home = _resolve_wsl_home(distro, effective_user, self._log)
        venv_python_wsl = f"{user_home}/venvs/{venv_name}/bin/python"

        extra = (self.var_extra_args.get() or "").strip()
        extra_tokens: list[str] = []
        if extra:
            try:
                extra_tokens = shlex.split(extra, posix=True)
            except Exception:
                extra_tokens = [extra]
        extra_part = ""
        if extra_tokens:
            extra_part = " " + " ".join(_bash_quote(tok) for tok in extra_tokens)

        # Build bash payload (no temp .sh files => avoids CRLF problems)
        # Ensure output directory does NOT exist when predict.py runs.
        bash_cmd = (
            "set -euo pipefail; "
            f"cd {_bash_quote(tool_dir_wsl)}; "
            "test -f predict.py || (echo 'ERROR: predict.py missing' && exit 11); "
            f"test -f {_bash_quote(fasta_wsl)} || (echo 'ERROR: FASTA missing' && exit 12); "
            f"test -x {_bash_quote(venv_python_wsl)} || (echo 'ERROR: venv python not found: {venv_python_wsl}' && exit 13); "
        )

        if out_policy == "fail":
            bash_cmd += f"if [[ -e {_bash_quote(out_dir_wsl)} ]]; then echo 'ERROR: output directory already exists'; exit 31; fi; "
        elif out_policy == "overwrite":
            bash_cmd += f"if [[ -e {_bash_quote(out_dir_wsl)} ]]; then echo '[WSL] Removing existing output folder...'; rm -rf {_bash_quote(out_dir_wsl)}; fi; "

        # ensure parent exists
        bash_cmd += (
            f"mkdir -p {_bash_quote(os.path.dirname(out_dir_wsl))}; "
            f"env PYTHONUNBUFFERED=1 {_bash_quote(venv_python_wsl)} -u predict.py --fasta {_bash_quote(fasta_wsl)} --output-dir {_bash_quote(out_dir_wsl)}{extra_part}; "
        )

        # Run in WSL
        self._log("[DeepTMHMM] Running DeepTMHMM in WSL1...")
        self._log(f"[DeepTMHMM] Tool folder (Windows): {tool_dir_win}")
        self._log(f"[DeepTMHMM] AA FASTA (Windows): {aa_fasta_win}")
        self._log(f"[DeepTMHMM] Output (Windows): {out_dir_win}")
        self._log(f"[DeepTMHMM] Output policy: {out_policy}")
        self._log(f"[DeepTMHMM] Distro: {distro}")
        self._log(f"[DeepTMHMM] Effective WSL user: {effective_user}")
        self._log(f"[DeepTMHMM] Resolved WSL home: {user_home}")
        self._log(f"[DeepTMHMM] Venv python: {venv_python_wsl}")
        if extra.strip():
            self._log(f"[DeepTMHMM] Extra args: {extra.strip()}")

        argv = _wsl_bash_argv(distro, bash_cmd, wsl_user)
        rc = _run_subprocess_stream(argv, self._log, cancel_event=cancel_event, name="DEEPTMHMM")

        if cancel_event.is_set():
            self._log("[DeepTMHMM] Cancel requested.")
            return False

        if rc != 0:
            self._log(f"[DeepTMHMM] ERROR: DeepTMHMM failed (rc={rc}).")
            return False

        # After success, copy/rename TMRs.gff3 into return_to_R
        ensure_dir(out_dir_win)
        tmr_src = os.path.join(out_dir_win, "TMRs.gff3")

        if not os.path.isfile(tmr_src):
            # Search just in case tool wrote it deeper
            found = None
            for root, _, files in os.walk(out_dir_win):
                if "TMRs.gff3" in files:
                    found = os.path.join(root, "TMRs.gff3")
                    break
            if found:
                tmr_src = found

        if not os.path.isfile(tmr_src):
            self._log("[DeepTMHMM] ERROR: Could not find TMRs.gff3 in output folder.")
            return False

        ensure_dir(return_to_r_dir)
        dst = os.path.join(return_to_r_dir, "Result_DeepTMHMM.gff3")
        try:
            shutil.copy2(tmr_src, dst)
            self._log(f"[DeepTMHMM] Saved for R: {dst}")
        except Exception as e:
            self._log(f"[DeepTMHMM] ERROR: Failed to copy to return_to_R: {e}")
            return False

        return True

    # ---------------- Button handlers ----------------
    def _click_run(self):
        # main_app will call tab_inputs.apply_to_cfg(silent=True) before run, so Inputs are current
        self.save_to_cfg()
        if self.run_cb is None:
            messagebox.showerror("Run", "Run callback not wired.")
            return
        self.run_cb(self)

    # ---------------- Async tests (no GUI freeze) ----------------
    def _test_wsl_async(self):
        self.save_to_cfg()
        t = threading.Thread(target=self._test_wsl_worker, daemon=True)
        t.start()

    def _test_deeptmhmm_async(self):
        self.save_to_cfg()
        t = threading.Thread(target=self._test_deeptmhmm_worker, daemon=True)
        t.start()

    def _test_wsl_worker(self):
        distro = (self.var_distro.get() or "").strip()
        if not distro:
            self._log("[DeepTMHMM][TEST] ERROR: WSL distro is empty.")
            return

        self._log("[DeepTMHMM][TEST] Testing WSL...")
        wsl_user = _detect_wsl_run_user(distro, self._log)
        argv = _wsl_bash_argv(distro, "set -e; echo OK; uname -a; whoami; echo $HOME", wsl_user)
        _run_subprocess_stream(argv, self._log, cancel_event=None, name="WSL_TEST")

    def _test_deeptmhmm_worker(self):
        distro = (self.var_distro.get() or "").strip()
        tool_dir_win = _norm_abs_win((self.var_tool_dir_win.get() or "").strip())
        venv_name = (self.var_venv_name.get() or "").strip() or "deeptmhmm_py38"
        wsl_user = _detect_wsl_run_user(distro, self._log)

        self._log("[DeepTMHMM][TEST] Checking tool folder...")
        if not tool_dir_win or not os.path.isdir(tool_dir_win):
            self._log("[DeepTMHMM][TEST] ERROR: Tool folder invalid.")
            return
        if not os.path.isfile(os.path.join(tool_dir_win, "predict.py")):
            self._log("[DeepTMHMM][TEST] ERROR: predict.py not found in tool folder.")
            return

        tool_dir_wsl = win_to_wsl_path(tool_dir_win)

        effective_user = _get_wsl_current_user(distro, wsl_user) or (wsl_user or "root")
        user_home = _resolve_wsl_home(distro, effective_user, self._log)
        venv_python_wsl = f"{user_home}/venvs/{venv_name}/bin/python"

        self._log("[DeepTMHMM][TEST] Testing Python env + imports in WSL (torch/esm/h5py)...")
        self._log(f"[DeepTMHMM][TEST] Effective WSL user: {effective_user}")
        self._log(f"[DeepTMHMM][TEST] Resolved WSL home: {user_home}")
        self._log(f"[DeepTMHMM][TEST] Venv python: {venv_python_wsl}")
        bash_cmd = (
            "set -euo pipefail; "
            f"cd {_bash_quote(tool_dir_wsl)}; "
            f"test -x {_bash_quote(venv_python_wsl)} || (echo 'ERROR: venv python missing: {venv_python_wsl}' && exit 13); "
            f"{_bash_quote(venv_python_wsl)} -c \"import torch; print('torch:', torch.__version__); print('cuda:', torch.cuda.is_available())\"; "
            f"{_bash_quote(venv_python_wsl)} -c \"import esm; print('esm: OK')\"; "
            f"{_bash_quote(venv_python_wsl)} -c \"import h5py; print('h5py:', h5py.__version__)\"; "
            "echo 'OK: DeepTMHMM imports look good.'; "
        )

        argv = _wsl_bash_argv(distro, bash_cmd, wsl_user)
        _run_subprocess_stream(argv, self._log, cancel_event=None, name="DEEPTMHMM_TEST")