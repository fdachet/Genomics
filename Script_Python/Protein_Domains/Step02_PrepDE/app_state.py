from __future__ import annotations

import gzip
import os
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from utils_paths import win_to_wsl_path


@dataclass
class ProjectConfig:
    # Required inputs
    pass2_dir_win: str = ""          # PASS2 folder containing sample subfolders
    output_dir_win: str = ""         # Output folder for run results

    # Output behavior
    create_run_folder: bool = True
    run_prefix: str = "prepde_run"

    # WSL execution
    wsl_distro: str = ""             # blank => default WSL distro
    wsl_python: str = "python3"      # python command inside WSL

    # prepDE script (third-party)
    prepde_py_win: str = ""          # Windows path to prepDE.py

    # prepDE parameter
    read_length: int = 150            # average read length (-l) used by prepDE.py

    # Produced outputs (filled after run)
    gene_counts_win: str = ""
    iso_counts_win: str = ""
    design_tsv_win: str = ""

    # Design helpers
    condition_a: str = "ConditionA"
    condition_b: str = "ConditionB"


@dataclass
class SampleEntry:
    sample_id: str
    gtf_win: str
    ok: bool
    message: str


class AppState:
    """
    Shared state across tabs.
    """
    def __init__(self, app_dir: Optional[str] = None):
        self.app_dir = app_dir or os.path.dirname(os.path.abspath(__file__))

        self.cfg = ProjectConfig()
        self.detected_samples: List[SampleEntry] = []
        self.last_run_paths: Dict[str, str] = {}
        self.is_busy: bool = False

        self._ensure_default_prepde()

    def _ensure_default_prepde(self) -> None:
        if (self.cfg.prepde_py_win or "").strip():
            return
        candidate = os.path.join(self.app_dir, "prepDE.py")
        if os.path.isfile(candidate):
            self.cfg.prepde_py_win = candidate

    # ---------------------------
    # PASS2 scanning helpers
    # ---------------------------
    @staticmethod
    def _open_text_maybe_gzip(path: str):
        if path.lower().endswith(".gz"):
            return gzip.open(path, "rt", encoding="utf-8", errors="replace")
        return open(path, "r", encoding="utf-8", errors="replace")

    @classmethod
    def _find_stringtie_flags_in_header(cls, gtf_path: str, max_lines: int = 60) -> Tuple[bool, bool, str]:
        """
        Scan initial comment header lines for '-e' and '-G <file>'.
        Returns (has_e, has_G, gfile_or_empty).
        """
        has_e = False
        has_g = False
        gfile = ""

        try:
            with cls._open_text_maybe_gzip(gtf_path) as f:
                for _ in range(max_lines):
                    line = f.readline()
                    if not line:
                        break
                    if not line.startswith("#"):
                        break

                    if re.search(r"(^|\s)-e(\s|$)", line):
                        has_e = True

                    # robust parse of -G argument: -G <path> with quotes or without
                    m = re.search(r"(?:^|\s)-G\s+(\"([^\"]+)\"|'([^']+)'|(\S+))", line)
                    if m:
                        gfile = (m.group(2) or m.group(3) or m.group(4) or "").strip()
                        if gfile:
                            has_g = True
        except Exception:
            return False, False, ""

        return has_e, has_g, gfile

    @classmethod
    def _gtf_looks_like_stringtie_pass2(cls, gtf_path: str) -> Tuple[bool, str, str]:
        """
        prepDE.py requires StringTie GTFs produced with:
          stringtie ... -e -G <annotation.gtf> ...
        """
        has_e, has_g, gfile = cls._find_stringtie_flags_in_header(gtf_path)
        if not has_e and not has_g:
            return False, "Header missing '-e' and '-G' (not a PASS2 quant GTF).", ""
        if not has_e:
            return False, "Header missing '-e' (StringTie PASS2 must be run with -e).", gfile
        if not has_g:
            return False, "Header missing '-G <annotation.gtf>' (prepDE will abort without -G).", ""
        return True, f"OK (-e, -G={os.path.basename(gfile) if gfile else 'found'})", gfile

    @staticmethod
    def _choose_gtf_for_sample(sample_dir: str, sample_id: str) -> Tuple[str, str]:
        """
        Prefer <sample_id>.gtf(.gz), else any *.gtf(.gz) directly in sample_dir.
        """
        if not os.path.isdir(sample_dir):
            return "", "Sample folder missing"

        preferred = [os.path.join(sample_dir, sample_id + ext) for ext in (".gtf", ".gtf.gz")]
        for p in preferred:
            if os.path.isfile(p):
                return p, "Found (preferred name)"

        candidates: List[str] = []
        for name in os.listdir(sample_dir):
            n = name.lower()
            if n.endswith(".gtf") or n.endswith(".gtf.gz"):
                candidates.append(os.path.join(sample_dir, name))

        if not candidates:
            return "", "No .gtf/.gtf.gz found in sample folder"

        candidates.sort(key=lambda x: (len(os.path.basename(x)), os.path.basename(x).lower()))
        return candidates[0], f"Found ({os.path.basename(candidates[0])})"

    def scan_pass2_folder(self) -> List[SampleEntry]:
        base = (self.cfg.pass2_dir_win or "").strip()
        out: List[SampleEntry] = []

        if not base:
            self.detected_samples = []
            return []

        if not os.path.isdir(base):
            self.detected_samples = [SampleEntry("(none)", "", False, "PASS2 folder does not exist")]
            return self.detected_samples

        entries = sorted([d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))])
        if not entries:
            self.detected_samples = [SampleEntry("(none)", "", False, "No sample subfolders found")]
            return self.detected_samples

        first_gfile = ""
        for sample_id in entries:
            sdir = os.path.join(base, sample_id)
            gtf, _ = self._choose_gtf_for_sample(sdir, sample_id)
            if not gtf:
                out.append(SampleEntry(sample_id, "", False, "No GTF found"))
                continue

            ok, msg, gfile = self._gtf_looks_like_stringtie_pass2(gtf)
            if ok and gfile:
                if not first_gfile:
                    first_gfile = gfile
                elif gfile != first_gfile:
                    msg += " [WARN: -G differs across samples]"
            out.append(SampleEntry(sample_id, gtf, ok, msg))

        self.detected_samples = out
        return out

    def ok_samples(self) -> List[SampleEntry]:
        return [s for s in (self.detected_samples or []) if s.ok and s.gtf_win and os.path.isfile(s.gtf_win)]

    def ensure_run_folder(self) -> Dict[str, str]:
        out_base = (self.cfg.output_dir_win or "").strip()
        if not out_base:
            raise ValueError("Output folder is empty.")
        os.makedirs(out_base, exist_ok=True)

        if self.cfg.create_run_folder:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            run_dir = os.path.join(out_base, f"{self.cfg.run_prefix}_{stamp}")
        else:
            run_dir = out_base

        os.makedirs(run_dir, exist_ok=True)

        self.last_run_paths = {"run_dir_win": run_dir, "run_dir_wsl": win_to_wsl_path(run_dir)}
        return self.last_run_paths
