from __future__ import annotations

import subprocess
import threading
import time
from typing import Callable, Optional, Dict

from utils_paths import quote_bash


def list_wsl_distros() -> list[str]:
    """
    Return list of distro names via: wsl.exe -l -q
    """
    try:
        cp = subprocess.run(["wsl.exe", "-l", "-q"], capture_output=True, text=True, check=False)
        lines = [ln.strip().replace("\x00", "") for ln in cp.stdout.splitlines() if ln.strip()]
        return lines
    except Exception:
        return []


def run_wsl_command(
    distro: str,
    bash_command: str,
    cwd_wsl: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    stream_callback: Optional[Callable[[str, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> int:
    """
    Run a bash command in WSL. Streams stdout/stderr line-by-line to stream_callback(kind, line).
    kind is 'stdout' or 'stderr'.

    If stop_event is set, terminates the process.
    """
    if env is None:
        env = {}

    parts = []
    if cwd_wsl:
        parts.append(f"cd {quote_bash(cwd_wsl)}")
    for k, v in env.items():
        parts.append(f"export {k}={quote_bash(v)}")
    parts.append(bash_command)
    wrapped = " && ".join(parts)

    cmd = ["wsl.exe"]
    if distro:
        cmd += ["-d", distro]
    cmd += ["bash", "-lc", wrapped]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    def pump(stream, kind: str):
        try:
            for line in iter(stream.readline, ""):
                if stop_event and stop_event.is_set():
                    break
                if line and stream_callback:
                    stream_callback(kind, line.rstrip("\n"))
        finally:
            try:
                stream.close()
            except Exception:
                pass

    t_out = threading.Thread(target=pump, args=(proc.stdout, "stdout"), daemon=True)
    t_err = threading.Thread(target=pump, args=(proc.stderr, "stderr"), daemon=True)
    t_out.start()
    t_err.start()

    while proc.poll() is None:
        if stop_event and stop_event.is_set():
            try:
                proc.terminate()
            except Exception:
                pass
            break
        time.sleep(0.1)

    rc = proc.wait()
    return rc
