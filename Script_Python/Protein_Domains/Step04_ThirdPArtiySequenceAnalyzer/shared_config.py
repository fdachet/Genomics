import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

APP_NAME = "IsoSwitch 3rd-Party Sequence Analyzer (WSL1)"
APP_VERSION = "3.0-per-tool-tabs"


def config_path_default() -> str:
    home = os.path.expanduser("~")
    return os.path.join(home, ".isoswitch_seq_analyzer_wsl1_tools.json")


@dataclass
class AppConfig:
    # Inputs
    aa_fasta: str = ""
    nt_fasta: str = ""
    gtf_file: str = ""     # optional (used by NMD heuristic)
    out_dir: str = ""
    threads: int = 4

    # Per-tool settings, keyed by tool_id
    tools: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def tool(self, tool_id: str) -> Dict[str, Any]:
        if tool_id not in self.tools:
            self.tools[tool_id] = {}
        return self.tools[tool_id]


def load_config(path: str) -> Optional[AppConfig]:
    try:
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        cfg = AppConfig()
        cfg.aa_fasta = d.get("aa_fasta", "") or ""
        cfg.nt_fasta = d.get("nt_fasta", "") or ""
        cfg.gtf_file = d.get("gtf_file", "") or ""
        cfg.out_dir = d.get("out_dir", "") or ""
        cfg.threads = int(d.get("threads", 4) or 4)
        cfg.tools = d.get("tools", {}) or {}
        return cfg
    except Exception:
        return None


def save_config(path: str, cfg: AppConfig) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    d = {
        "aa_fasta": cfg.aa_fasta,
        "nt_fasta": cfg.nt_fasta,
        "gtf_file": cfg.gtf_file,
        "out_dir": cfg.out_dir,
        "threads": cfg.threads,
        "tools": cfg.tools,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
