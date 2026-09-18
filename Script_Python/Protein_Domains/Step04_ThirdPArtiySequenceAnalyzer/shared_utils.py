import os
import re
import csv
import time
import threading
import subprocess
from typing import Dict, List, Optional, Tuple


def is_windows() -> bool:
    return os.name == "nt"


def ensure_dir(path: str) -> None:
    if not path:
        return
    os.makedirs(path, exist_ok=True)


def now_stamp() -> str:
    return time.strftime("%Y-%m-%d_%H-%M-%S")


def normpath_win(p: str) -> str:
    return os.path.normpath(p).replace("/", "\\")


def normpath_unix(p: str) -> str:
    return p.replace("\\", "/")


def win_to_wsl_path(win_path: str) -> str:
    """
    Convert a Windows drive path to a WSL /mnt/<drive>/ path.

    Examples:
      C:\\Data\\file.fa  ->  /mnt/c/Data/file.fa
      P:\\Work\\x.txt    ->  /mnt/p/Work/x.txt

    If it doesn't look like a drive path, returns a slash-normalized path.
    """
    p = (win_path or "").strip().strip('"').strip("'")
    if not p:
        return ""
    p = normpath_win(p)
    m = re.match(r"^([A-Za-z]):\\(.*)$", p)
    if not m:
        return normpath_unix(p)
    drive = m.group(1).lower()
    rest = m.group(2).replace("\\", "/")
    return f"/mnt/{drive}/{rest}"


def read_first_fasta_ids(fasta_path: str, n: int = 20) -> List[str]:
    ids: List[str] = []
    try:
        with open(fasta_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith(">"):
                    hdr = line[1:].strip()
                    iso = hdr.split()[0]
                    ids.append(iso)
                    if len(ids) >= n:
                        break
    except Exception:
        return []
    return ids


def count_fasta_records(fasta_path: str) -> int:
    """
    Count FASTA records by counting header lines starting with '>'.
    Supports plain text and .gz FASTA.
    """
    p = (fasta_path or "").strip()
    if not p or not os.path.isfile(p):
        return 0

    try:
        if p.lower().endswith(".gz"):
            import gzip
            opener = gzip.open
            mode = "rt"
        else:
            opener = open
            mode = "r"

        n = 0
        with opener(p, mode, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith(">"):
                    n += 1
        return n
    except Exception:
        return 0


def tsv_write(path: str, header: List[str], rows: List[List[str]]) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(header)
        w.writerows(rows)


def safe_write_text(path: str, text: str) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def sanitize_nulls(s: str) -> str:
    return (s or "").replace("\x00", "")


def build_wsl_bash_command(cmd: str, distro: Optional[str] = None, wsl_user: Optional[str] = None) -> List[str]:
    """
    Build a bash invocation.

    - On Windows (WSL): supports optional distro/user:
        * no distro/user:  wsl.exe bash -lc "<cmd>"
        * with distro/user: wsl.exe -d <distro> [-u <user>] -- bash -lc "<cmd>"

    - On Linux: bash -lc "<cmd>" (ignores distro/user)
    """
    if not is_windows():
        return ["bash", "-lc", cmd]

    distro = (distro or "").strip()
    wsl_user = (wsl_user or "").strip()

    if not distro and not wsl_user:
        # Keep the classic form for maximum compatibility.
        return ["wsl.exe", "bash", "-lc", cmd]

    args: List[str] = ["wsl.exe"]
    if distro:
        args += ["-d", distro]
    if wsl_user:
        args += ["-u", wsl_user]
    args += ["--", "bash", "-lc", cmd]
    return args


def run_wsl_command(
    cmd: str,
    cwd_win: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    log_cb=None,
    cancel_event: Optional[threading.Event] = None,
    distro: Optional[str] = None,
    wsl_user: Optional[str] = None,
) -> Tuple[int, str, str]:
    """
    Run a bash command in WSL and stream stdout/stderr to log_cb.
    Returns (returncode, stdout_text, stderr_text).
    """
    args = build_wsl_bash_command(cmd, distro=distro, wsl_user=wsl_user)
    penv = os.environ.copy()
    if env:
        penv.update(env)

    p = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd_win if cwd_win else None,
        env=penv,
    )

    stdout_lines: List[str] = []
    stderr_lines: List[str] = []

    def pump(stream, collector: List[str], prefix: str):
        for line in iter(stream.readline, ""):
            if cancel_event and cancel_event.is_set():
                break
            collector.append(line)
            if log_cb:
                log_cb(f"{prefix}{line.rstrip()}")
        try:
            stream.close()
        except Exception:
            pass

    t_out = threading.Thread(target=pump, args=(p.stdout, stdout_lines, ""), daemon=True)
    t_err = threading.Thread(target=pump, args=(p.stderr, stderr_lines, "[stderr] "), daemon=True)
    t_out.start()
    t_err.start()

    while p.poll() is None:
        if cancel_event and cancel_event.is_set():
            try:
                p.terminate()
            except Exception:
                pass
            break
        time.sleep(0.05)

    t_out.join(timeout=1)
    t_err.join(timeout=1)

    rc = p.poll()
    if rc is None:
        try:
            p.kill()
        except Exception:
            pass
        rc = p.wait(timeout=5)

    return rc, "".join(stdout_lines), "".join(stderr_lines)
