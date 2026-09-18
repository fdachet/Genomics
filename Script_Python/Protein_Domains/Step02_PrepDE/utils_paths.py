from __future__ import annotations

import re
import shlex


def win_to_wsl_path(p: str) -> str:
    """
    Convert Windows path like C:\\data\\file to /mnt/c/data/file
    Leaves non-Windows paths untouched.
    """
    p = (p or "").strip().strip('"')
    if not p:
        return p

    p = p.replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)$", p)
    if not m:
        return p

    drive = m.group(1).lower()
    rest = m.group(2)
    return f"/mnt/{drive}/{rest}"


def quote_bash(s: str) -> str:
    """
    POSIX-safe shell quoting for bash -lc.
    """
    return shlex.quote(s or "")
