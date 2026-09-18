#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import shutil
import subprocess
import threading
import queue
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import List, Tuple, Optional, Dict


# ----------------- PATH UTILITIES ----------------- #

def windows_to_wsl_path(win_path: str) -> str:
    """
    Convert a Windows path like:
        C:\\String\\BAM_small
    to a WSL path:
        /mnt/c/String/BAM_small
    """
    win_path = os.path.abspath(win_path)
    drive, tail = os.path.splitdrive(win_path)
    if not drive:
        return win_path.replace("\\", "/")

    drive_letter = drive[0].lower()
    tail = tail.lstrip("\\/").replace("\\", "/")
    return f"/mnt/{drive_letter}/{tail}"


def run_wsl_command(cmd: str, log_callback=None) -> int:
    """
    Run a command inside WSL:
        wsl bash -c "<cmd>"
    Streams stdout+stderr line by line.
    Returns exit code.
    """
    full = ["wsl", "bash", "-c", cmd]
    if log_callback:
        log_callback(f"$ {cmd}")

    try:
        proc = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    except FileNotFoundError:
        raise RuntimeError("wsl.exe not found. Install WSL and ensure 'wsl' is in PATH.")
    except Exception as ex:
        raise RuntimeError(f"Failed to start WSL process: {ex}")

    if proc.stdout:
        for line in proc.stdout:
            line = line.rstrip("\n")
            if log_callback:
                log_callback(line)

    return proc.wait()


# ----------------- SAM/BAM SORT CHECK ----------------- #

def _parse_sq_order_from_sam_header(header_lines: List[str]) -> List[str]:
    """
    Extract @SQ SN order to compare contig order (coordinate sorting).
    """
    order = []
    for ln in header_lines:
        if ln.startswith("@SQ"):
            m = re.search(r"\bSN:([^\t]+)", ln)
            if m:
                order.append(m.group(1))
    return order


def _sam_line_to_refpos(line: str) -> Optional[Tuple[str, int]]:
    """
    From a SAM alignment line, extract RNAME and POS.
    Returns None for unmapped/invalid lines.
    """
    if not line or line.startswith("@"):
        return None
    parts = line.split("\t")
    if len(parts) < 4:
        return None
    rname = parts[2]
    try:
        pos = int(parts[3])
    except Exception:
        return None
    if rname == "*" or pos <= 0:
        return None
    return (rname, pos)


def _is_sorted_by_sample_sam_lines(aln_lines: List[str], sq_order: List[str]) -> Optional[bool]:
    """
    Decide if a set of alignment lines appears coordinate-sorted:
    - Compare contig order using @SQ order (if present)
    - Within contig, POS should be non-decreasing
    Returns True/False/None (None if insufficient evidence).
    """
    if not aln_lines:
        return None

    # Build contig ranking
    contig_rank: Dict[str, int] = {}
    if sq_order:
        contig_rank = {c: i for i, c in enumerate(sq_order)}

    prev_rank = None
    prev_contig = None
    prev_pos = None
    seen = 0

    for ln in aln_lines:
        rp = _sam_line_to_refpos(ln)
        if rp is None:
            continue
        contig, pos = rp
        seen += 1

        rank = contig_rank.get(contig, None)
        # If contig order is unknown, use lexicographic as fallback
        if rank is None:
            rank = (10 ** 9)  # unknown contigs treated as very "late"

        if prev_rank is None:
            prev_rank = rank
            prev_contig = contig
            prev_pos = pos
            continue

        # Must not go backward in contig rank
        if rank < prev_rank:
            return False

        # If same contig, must not go backward in POS
        if contig == prev_contig:
            if pos < (prev_pos or 0):
                return False

        prev_rank = rank
        prev_contig = contig
        prev_pos = pos

    if seen < 20:
        # Too few mapped alignments to conclude
        return None

    return True


def sample_check_sam_sorted(path_win: str, sample_reads: int) -> Optional[bool]:
    """
    Sample-check sorting for a SAM file by reading a small number of alignment lines.
    SAM files are treated as needing conversion anyway, but this provides a hint.
    """
    try:
        header_lines = []
        aln_lines = []
        with open(path_win, "r", encoding="utf-8", errors="ignore") as f:
            for ln in f:
                if ln.startswith("@"):
                    header_lines.append(ln.rstrip("\n"))
                    continue
                aln_lines.append(ln.rstrip("\n"))
                if len(aln_lines) >= sample_reads:
                    break
        sq_order = _parse_sq_order_from_sam_header(header_lines)
        return _is_sorted_by_sample_sam_lines(aln_lines, sq_order)
    except Exception:
        return None


def sample_check_bam_sorted_wsl(bam_wsl: str, sample_reads: int, threads: int = 1, log_callback=None) -> Optional[bool]:
    """
    Sample-check coordinate sorting of a BAM in WSL using:
      - samtools view -H (to get @SQ order)
      - samtools view (first N alignments)
    Returns True/False/None.
    """
    header_lines: List[str] = []

    def collect_header(line: str):
        header_lines.append(line)

    rc = run_wsl_command(f'samtools view -H "{bam_wsl}"', collect_header if log_callback is None else collect_header)
    if rc != 0 or not header_lines:
        return None

    sq_order = _parse_sq_order_from_sam_header(header_lines)

    aln_lines: List[str] = []

    def collect_aln(line: str):
        aln_lines.append(line)

    n = max(0, int(sample_reads))
    # Note: bash pipelines return the last command's status (head), so rc should be 0.
    rc2 = run_wsl_command(f'samtools view -@ {max(1,int(threads))} "{bam_wsl}" | head -n {n}', collect_aln)
    if rc2 != 0 and not aln_lines:
        return None

    return _is_sorted_by_sample_sam_lines(aln_lines, sq_order)


def strict_check_bam_indexable_wsl(bam_wsl: str, threads: int = 1, log_callback=None) -> Optional[bool]:
    """
    Reliable coordinate-sort check for BAM: attempt to build an index in /tmp.
    If samtools index succeeds, the BAM is coordinate-sorted (indexable).
    If it fails, it is not coordinate-sorted (or is corrupted).
    Returns True/False/None (None if samtools missing / command failed unexpectedly).
    """
    ts = int(time.time())
    tmpdir = f"/tmp/sortcheck_{ts}_{os.getpid()}"
    tmpidx = f"{tmpdir}/tmp.bai"

    # Create tmpdir
    rc = run_wsl_command(f'mkdir -p "{tmpdir}"', log_callback)
    if rc != 0:
        return None

    try:
        # Note: samtools index supports an optional output index filename as a second argument.
        # We write into /tmp to avoid touching the original folder.
        cmd = f'samtools index -@ {max(1, int(threads))} "{bam_wsl}" "{tmpidx}"'
        rc2 = run_wsl_command(cmd, log_callback)
        if rc2 == 0:
            return True
        return False
    finally:
        # Cleanup tmpdir regardless of outcome
        run_wsl_command(f'rm -rf "{tmpdir}"', log_callback)


def detect_sort_status(path_win: str, sample_reads: int, threads: int, strict_bam_check: bool = True, log_callback=None) -> Tuple[Optional[bool], str]:
    """
    Returns (sorted?, reason).
      sorted? True/False/None
    """
    p = path_win
    base = os.path.basename(p)
    if p.lower().endswith(".sam"):
        # SAM is treated as "needs conversion" regardless, but we still can report a sample-check.
        res = sample_check_sam_sorted(p, sample_reads)
        if res is True:
            return (False, f"SAM detected (even if sorted, StringTie expects coordinate-sorted BAM for indexing/perf): {base}")
        if res is False:
            return (False, f"SAM detected (and sample-check suggests NOT sorted): {base}")
        return (False, f"SAM detected (sort status unknown): {base}")

    if not p.lower().endswith(".bam"):
        return (None, f"Unsupported extension: {base}")

    bam_wsl = windows_to_wsl_path(p)

    # If an index exists and idxstats works, that's strong evidence it's coordinate-sorted/indexable.
    bai1 = p + ".bai"
    bai2 = os.path.splitext(p)[0] + ".bai"
    if os.path.isfile(bai1) or os.path.isfile(bai2):
        rc = run_wsl_command(f'samtools idxstats "{bam_wsl}" >/dev/null 2>&1')
        if rc == 0:
            return (True, f".bai present and samtools idxstats OK: {base}")

    res = sample_check_bam_sorted_wsl(bam_wsl, sample_reads=sample_reads, threads=threads, log_callback=log_callback)

    # If sample-check clearly shows out-of-order, it's not coordinate-sorted.
    if res is False:
        return (False, f"sample-check FAILED (out-of-order ref/pos found): {base}")

    # If strict check is enabled, confirm by attempting to build an index in /tmp.
    if strict_bam_check:
        strict_res = strict_check_bam_indexable_wsl(bam_wsl, threads=threads, log_callback=log_callback)
        if strict_res is True:
            if res is True:
                return (True, f"sample-check OK + index-test OK (coordinate-sorted/indexable): {base}")
            return (True, f"index-test OK (coordinate-sorted/indexable): {base}")
        if strict_res is False:
            return (False, f"index-test FAILED (not coordinate-sorted or invalid BAM): {base}")
        # strict_res is None -> fall back to sample-check below

    # No strict confirmation (or strict unavailable): use sample-check result.
    if res is True:
        return (True, f"sample-check OK (non-decreasing ref/pos): {base}")

    return (None, f"sort status UNKNOWN (samtools missing/failed or not enough alignments): {base}")




def run_wsl_command_capture(cmd: str, max_lines: Optional[int] = None) -> Tuple[int, List[str]]:
    """
    Run a WSL command and capture stdout/stderr lines.
    """
    lines: List[str] = []

    def collector(line: str):
        if max_lines is None or len(lines) < max_lines:
            lines.append(line)

    rc = run_wsl_command(cmd, collector)
    return rc, lines


def _parse_int_from_last_line(lines: List[str]) -> Optional[int]:
    if not lines:
        return None
    try:
        return int(lines[-1].strip())
    except Exception:
        return None


def sample_spliced_alignments_for_tag_check_wsl(path_wsl: str, sample_spliced_reads: int, threads: int = 1) -> Tuple[int, List[str]]:
    """
    Sample spliced alignments (CIGAR containing 'N') for XS/ts tag checks.
    To avoid scanning an entire huge BAM when spliced reads are rare or absent,
    stop after either:
      - collecting `sample_spliced_reads` spliced alignments, or
      - examining `max_records` total alignments.
    """
    n = max(1, int(sample_spliced_reads))
    max_records = max(50000, n * 200)
    cmd = (
        f"samtools view -@ {max(1, int(threads))} -F 2308 \"{path_wsl}\" | "
        f"awk 'BEGIN{{c=0; seen=0}} "
        f"{{seen++; if (index($6,\"N\")>0) {{print; c++; if (c>={n}) exit}} "
        f"if (seen>={max_records}) exit}}'"
    )
    return run_wsl_command_capture(cmd)


def analyze_splice_strand_tags_from_sam_lines(lines: List[str]) -> Dict[str, int]:
    """
    Inspect sampled SAM lines and count presence of XS/ts tags on spliced alignments.
    """
    stats = {
        "spliced_sampled": 0,
        "xs_present": 0,
        "ts_present": 0,
        "missing_both": 0,
    }

    for ln in lines:
        if not ln or ln.startswith("@"):
            continue
        parts = ln.rstrip("\n").split("\t")
        if len(parts) < 11:
            continue
        cigar = parts[5]
        if "N" not in cigar:
            continue

        stats["spliced_sampled"] += 1
        tags = parts[11:]
        has_xs = any(tag.startswith("XS:A:") for tag in tags)
        has_ts = any(tag.startswith("ts:A:") for tag in tags)

        if has_xs:
            stats["xs_present"] += 1
        if has_ts:
            stats["ts_present"] += 1
        if not has_xs and not has_ts:
            stats["missing_both"] += 1

    return stats


def validate_alignment_file(path_win: str, sample_spliced_reads: int, threads: int, log_callback=None) -> Dict[str, object]:
    """
    Validate that an input alignment file is sane for this StringTie pipeline.

    Checks:
      - supported extension (.bam/.sam)
      - samtools quickcheck (header + EOF/truncation sanity)
      - readable header with @SQ records
      - total/mapped alignments
      - presence of XS on sampled spliced alignments
        (ts is noted, but this GUI is a standard short-read StringTie pipeline)

    Returns a dict with:
      status: PASS / WARN / FAIL
      messages: list[str]
      total_alignments / mapped_alignments / spliced_sampled / xs_present / ts_present / missing_both
    """
    base = os.path.basename(path_win)
    path_wsl = windows_to_wsl_path(path_win)
    ext = os.path.splitext(path_win)[1].lower()

    result: Dict[str, object] = {
        "file": base,
        "status": "PASS",
        "messages": [],
        "total_alignments": None,
        "mapped_alignments": None,
        "spliced_sampled": 0,
        "xs_present": 0,
        "ts_present": 0,
        "missing_both": 0,
    }

    def add_fail(msg: str):
        result["messages"].append(msg)
        result["status"] = "FAIL"

    def add_warn(msg: str):
        result["messages"].append(msg)
        if result["status"] != "FAIL":
            result["status"] = "WARN"

    def add_pass(msg: str):
        result["messages"].append(msg)

    if ext not in (".bam", ".sam"):
        add_fail(f"Unsupported extension: {base}")
        return result

    # Quick truncation/header sanity
    rc, qc_lines = run_wsl_command_capture(f'samtools quickcheck -v "{path_wsl}"')
    if rc != 0:
        detail = "; ".join(qc_lines[-5:]) if qc_lines else "samtools quickcheck failed"
        add_fail(f"samtools quickcheck FAILED: {detail}")
        return result
    add_pass("samtools quickcheck OK")

    # Read header
    rc, header_lines = run_wsl_command_capture(f'samtools view -H "{path_wsl}"', max_lines=2000)
    if rc != 0:
        add_fail("samtools view -H failed")
        return result

    sq_count = sum(1 for ln in header_lines if ln.startswith("@SQ"))
    if sq_count <= 0:
        add_fail("No @SQ records found in header")
        return result
    add_pass(f"Header OK (@SQ={sq_count})")

    # Count alignments
    rc, total_lines = run_wsl_command_capture(f'samtools view -c "{path_wsl}"', max_lines=5)
    total_alignments = _parse_int_from_last_line(total_lines)
    result["total_alignments"] = total_alignments
    if rc != 0 or total_alignments is None:
        add_fail("Could not count total alignments with samtools view -c")
        return result
    if total_alignments <= 0:
        add_fail("File contains 0 alignments")
        return result
    add_pass(f"Total alignments: {total_alignments}")

    rc, mapped_lines = run_wsl_command_capture(f'samtools view -c -F 4 "{path_wsl}"', max_lines=5)
    mapped_alignments = _parse_int_from_last_line(mapped_lines)
    result["mapped_alignments"] = mapped_alignments
    if rc != 0 or mapped_alignments is None:
        add_fail("Could not count mapped alignments with samtools view -c -F 4")
        return result
    if mapped_alignments <= 0:
        add_fail("File contains 0 mapped alignments")
        return result
    add_pass(f"Mapped alignments: {mapped_alignments}")

    # Check XS / ts on sampled spliced alignments
    rc, spliced_lines = sample_spliced_alignments_for_tag_check_wsl(
        path_wsl=path_wsl,
        sample_spliced_reads=sample_spliced_reads,
        threads=threads
    )
    if rc != 0:
        add_warn("Could not sample spliced alignments to verify XS/ts tags")
        return result

    tag_stats = analyze_splice_strand_tags_from_sam_lines(spliced_lines)
    result["spliced_sampled"] = tag_stats["spliced_sampled"]
    result["xs_present"] = tag_stats["xs_present"]
    result["ts_present"] = tag_stats["ts_present"]
    result["missing_both"] = tag_stats["missing_both"]

    if tag_stats["spliced_sampled"] <= 0:
        add_warn(
            "No spliced alignments found in sampled records, so XS/ts verification was inconclusive"
        )
        return result

    if tag_stats["missing_both"] > 0:
        add_fail(
            f"Sampled spliced alignments missing both XS and ts tags: "
            f"{tag_stats['missing_both']} / {tag_stats['spliced_sampled']}"
        )
        return result

    if tag_stats["xs_present"] == tag_stats["spliced_sampled"]:
        add_pass(
            f"XS tag present on all sampled spliced alignments: "
            f"{tag_stats['xs_present']} / {tag_stats['spliced_sampled']}"
        )
        return result

    if tag_stats["xs_present"] > 0 and tag_stats["xs_present"] < tag_stats["spliced_sampled"]:
        add_fail(
            f"XS tag present only on part of sampled spliced alignments: "
            f"{tag_stats['xs_present']} / {tag_stats['spliced_sampled']}"
        )
        return result

    # No XS, but ts exists on all sampled spliced alignments
    if tag_stats["xs_present"] == 0 and tag_stats["ts_present"] == tag_stats["spliced_sampled"]:
        add_fail(
            "Spliced alignments have ts tags but no XS tags. "
            "That can be acceptable for minimap2 long-read workflows, but this GUI runs the standard short-read "
            "StringTie pipeline and should receive splice alignments with XS tags."
        )
        return result

    add_fail("Unable to confirm valid XS tags on sampled spliced alignments")
    return result


# ----------------- StringTie GUI ----------------- #

class StringTieGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("StringTie 2-pass pipeline (WSL) - V18")
        self.geometry("1200x800")

        # Log queue
        self.log_queue = queue.Queue()

        self._build_ui()
        self.after(100, self._poll_log_queue)

    def _build_ui(self):
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Inputs
        pad = 4
        r = 0

        ttk.Label(frame, text="BAM/SAM input folder:").grid(row=r, column=0, sticky="w", padx=pad, pady=pad)
        self.bam_dir_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.bam_dir_var, width=80).grid(row=r, column=1, sticky="w", padx=pad, pady=pad)
        ttk.Button(frame, text="Browse", command=self._browse_bam_dir).grid(row=r, column=2, sticky="w", padx=pad, pady=pad)
        r += 1

        ttk.Label(frame, text="GTF annotation file:").grid(row=r, column=0, sticky="w", padx=pad, pady=pad)
        self.gtf_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.gtf_var, width=80).grid(row=r, column=1, sticky="w", padx=pad, pady=pad)
        ttk.Button(frame, text="Browse", command=self._browse_gtf).grid(row=r, column=2, sticky="w", padx=pad, pady=pad)
        r += 1
        ttk.Label(frame, text="Genome FASTA (-g for gffread):").grid(row=r, column=0, sticky="w", padx=pad, pady=pad)
        self.genome_fa_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.genome_fa_var, width=80).grid(row=r, column=1, sticky="w", padx=pad, pady=pad)
        ttk.Button(frame, text="Browse", command=self._browse_genome_fa).grid(row=r, column=2, sticky="w", padx=pad, pady=pad)
        r += 1

        ttk.Label(frame, text="Output directory:").grid(row=r, column=0, sticky="w", padx=pad, pady=pad)
        self.out_dir_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.out_dir_var, width=80).grid(row=r, column=1, sticky="w", padx=pad, pady=pad)
        ttk.Button(frame, text="Browse", command=self._browse_out_dir).grid(row=r, column=2, sticky="w", padx=pad, pady=pad)
        r += 1

        # Threads
        ttk.Label(frame, text="Threads:").grid(row=r, column=0, sticky="w", padx=pad, pady=pad)
        self.threads_var = tk.IntVar(value=8)
        ttk.Entry(frame, textvariable=self.threads_var, width=10).grid(row=r, column=1, sticky="w", padx=pad, pady=pad)
        r += 1

        # Sort-check sample reads
        ttk.Label(frame, text="Sort-check sample reads:").grid(row=r, column=0, sticky="w", padx=pad, pady=pad)
        self.sortcheck_reads_var = tk.IntVar(value=5000)
        ttk.Entry(frame, textvariable=self.sortcheck_reads_var, width=10).grid(row=r, column=1, sticky="w", padx=pad, pady=pad)
        r += 1

        # Strict sort check (more reliable)
        self.strict_sortcheck_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frame,
            text="Strict BAM sort check (verify indexability via samtools index; slower but reliable)",
            variable=self.strict_sortcheck_var
        ).grid(row=r, column=0, columnspan=3, sticky="w", padx=pad, pady=pad)
        r += 1

        # StringTie cmd
        ttk.Label(frame, text="StringTie (WSL cmd):").grid(row=r, column=0, sticky="w", padx=pad, pady=pad)
        self.stringtie_cmd_var = tk.StringVar(value="stringtie")
        ttk.Entry(frame, textvariable=self.stringtie_cmd_var, width=30).grid(row=r, column=1, sticky="w", padx=pad, pady=pad)
        ttk.Button(frame, text="Test StringTie", command=self._test_stringtie).grid(row=r, column=2, sticky="w", padx=pad, pady=pad)
        r += 1

        # Strandedness
        ttk.Label(frame, text="Strandedness (Run RSeQC InferExperiment):").grid(row=r, column=0, sticky="w", padx=pad, pady=pad)
        self.strand_var = tk.StringVar(value="FR (--fr) (s1)(2nd Strand)")
        strand_combo = ttk.Combobox(frame, textvariable=self.strand_var, state="readonly", width=40)
        strand_combo["values"] = [
            "Unstranded (none)",
            "FR (--fr) (s1)(2nd Strand)",
            "RF (--rf) (s2)(1st Strand)"
        ]
        strand_combo.grid(row=r, column=1, sticky="w", padx=pad, pady=pad)
        r += 1

        # Convert inputs
        self.convert_sort_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frame,
            text="Convert inputs to coordinate-sorted BAM (samtools sort in WSL)",
            variable=self.convert_sort_var
        ).grid(row=r, column=0, columnspan=3, sticky="w", padx=pad, pady=pad)
        r += 1

        # Index sorted BAM
        self.index_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text="Create index for sorted BAM (samtools index)", variable=self.index_var).grid(
            row=r, column=0, columnspan=3, sticky="w", padx=pad, pady=pad
        )
        r += 1

        # gffread + FASTA generation
        self.make_fasta_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text="Create merged FASTA (gffread)", variable=self.make_fasta_var).grid(
            row=r, column=0, columnspan=3, sticky="w", padx=pad, pady=pad
        )
        r += 1

        self.strip_versions_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frame,
            text="Strip Ensembl version suffixes in merged.gtf (gene_id/transcript_id) (keeps gene_name; does NOT touch MSTRG.* IDs)",
            variable=self.strip_versions_var
        ).grid(row=r, column=0, columnspan=3, sticky="w", padx=pad, pady=pad)
        r += 1


        ttk.Label(frame, text="gffread (WSL cmd):").grid(row=r, column=0, sticky="w", padx=pad, pady=pad)
        self.gffread_cmd_var = tk.StringVar(value="gffread")
        ttk.Entry(frame, textvariable=self.gffread_cmd_var, width=30).grid(row=r, column=1, sticky="w", padx=pad, pady=pad)
        ttk.Button(frame, text="Test gffread", command=self._test_gffread).grid(row=r, column=2, sticky="w", padx=pad, pady=pad)
        r += 1

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=r, column=0, columnspan=3, sticky="w", padx=pad, pady=(10, pad))
        self.scan_button = ttk.Button(btn_frame, text="Scan inputs (sort + BAM validation)", command=self._scan_inputs_clicked)
        self.scan_button.pack(side="left", padx=(0, 10))
        self.run_button = ttk.Button(btn_frame, text="Run StringTie 2-pass", command=self._run_clicked)
        self.run_button.pack(side="left", padx=(0, 10))
        ttk.Button(btn_frame, text="Clear log", command=self._clear_log).pack(side="left")
        r += 1

        # Log box
        ttk.Label(frame, text="Run / Logs:").grid(row=r, column=0, sticky="w", padx=pad, pady=(10, pad))
        r += 1
        self.log_text = tk.Text(frame, height=25, wrap="none")
        self.log_text.grid(row=r, column=0, columnspan=3, sticky="nsew", padx=pad, pady=pad)

        # Scrollbars
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.log_text.yview)
        yscroll.grid(row=r, column=3, sticky="ns")
        self.log_text.configure(yscrollcommand=yscroll.set)

        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=self.log_text.xview)
        xscroll.grid(row=r + 1, column=0, columnspan=3, sticky="ew")
        self.log_text.configure(xscrollcommand=xscroll.set)

        # Expand
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_rowconfigure(r, weight=1)

    # ---------------- UI actions ---------------- #

    def log(self, msg: str):
        self.log_queue.put(msg)

    def _poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _clear_log(self):
        self.log_text.delete("1.0", "end")

    def _browse_bam_dir(self):
        d = filedialog.askdirectory()
        if d:
            self.bam_dir_var.set(d)

    def _browse_gtf(self):
        p = filedialog.askopenfilename(filetypes=[("GTF files", "*.gtf"), ("All files", "*.*")])
        if p:
            self.gtf_var.set(p)

    def _browse_out_dir(self):
        d = filedialog.askdirectory()
        if d:
            self.out_dir_var.set(d)

    def _browse_genome_fa(self):
        p = filedialog.askopenfilename(filetypes=[("FASTA files", "*.fa *.fasta"), ("All files", "*.*")])
        if p:
            self.genome_fa_var.set(p)

    def _test_tool_worker(self, tool_name: str, cmd: str, args_list: List[str]):
        try:
            for arg in args_list:
                rc = run_wsl_command(f'"{cmd}" {arg}', self.log)
                if rc == 0:
                    self.after(0, lambda: messagebox.showinfo("Test OK", f"{tool_name} seems installed: '{cmd}' works with {arg}"))
                    return
            raise RuntimeError(f"'{cmd}' did not run successfully with any test args: {args_list}")
        except Exception as ex:
            err = str(ex)
            self.log(f"[{tool_name}][TEST] ERROR: {err}")
            self.after(0, lambda m=err: messagebox.showerror("Test failed", f"{tool_name} test failed:\n{m}"))

    def _test_stringtie(self):
        cmd = self.stringtie_cmd_var.get().strip() or "stringtie"
        t = threading.Thread(target=self._test_tool_worker, args=("StringTie", cmd, ["--version", "-v", "-V", "--help"]), daemon=True)
        t.start()

    def _test_gffread(self):
        cmd = self.gffread_cmd_var.get().strip() or "gffread"
        t = threading.Thread(target=self._test_tool_worker, args=("gffread", cmd, ["--version", "-V", "-h", "--help"]), daemon=True)
        t.start()

    def _scan_inputs_clicked(self):
        bam_dir = self.bam_dir_var.get().strip()
        if not bam_dir or not os.path.isdir(bam_dir):
            messagebox.showerror("Error", "Select a valid BAM/SAM input folder.")
            return
        self.scan_button.config(state="disabled")
        t = threading.Thread(target=self._scan_inputs_worker, args=(bam_dir,), daemon=True)
        t.start()

    def _scan_inputs_worker(self, bam_dir: str):
        try:
            sample_reads = int(self.sortcheck_reads_var.get())
            threads = int(self.threads_var.get())

            strict = bool(self.strict_sortcheck_var.get())
            summary = self._scan_inputs(bam_dir=bam_dir, sample_reads=sample_reads, threads=threads, strict_check=strict)
            self.log(summary["log_block"])
            popup = summary["popup_text"]

            if summary["needs_sorting"]:
                self.after(0, lambda: self.convert_sort_var.set(True))

            title = "Input scan result"
            if summary.get("validation_failures", 0) > 0:
                title = "Input scan result (problems found)"
            self.after(0, lambda t=title, m=popup: messagebox.showinfo(t, m))
        except Exception as ex:
            err = str(ex)
            self.log(f"SCAN ERROR: {err}")
            self.after(0, lambda m=err: messagebox.showerror("Scan error", m))
        finally:
            self.after(0, lambda: self.scan_button.config(state="normal"))

    def _scan_inputs(self, bam_dir: str, sample_reads: int, threads: int, strict_check: bool):
        files = [
            os.path.join(bam_dir, f)
            for f in os.listdir(bam_dir)
            if f.lower().endswith(".bam") or f.lower().endswith(".sam")
        ]
        files.sort()

        if not files:
            raise RuntimeError("No BAM/SAM files (*.bam, *.sam) found in the selected directory.")

        sam_files = [f for f in files if f.lower().endswith(".sam")]
        bam_files = [f for f in files if f.lower().endswith(".bam")]

        needs_sort = 0
        already_sorted = 0
        unknown = 0

        validation_pass = 0
        validation_warn = 0
        validation_fail = 0

        details_lines = []

        for f in files:
            base = os.path.basename(f)

            sort_res, sort_reason = detect_sort_status(
                f,
                sample_reads=sample_reads,
                threads=threads,
                strict_bam_check=strict_check
            )

            if f.lower().endswith(".sam"):
                needs_sort += 1
                sort_label = f"NEEDS CONVERSION/SORT ({sort_reason})"
            elif sort_res is True:
                already_sorted += 1
                sort_label = f"SORTED ({sort_reason})"
            elif sort_res is False:
                needs_sort += 1
                sort_label = f"NOT SORTED ({sort_reason})"
            else:
                unknown += 1
                sort_label = f"UNKNOWN ({sort_reason})"

            val = validate_alignment_file(
                path_win=f,
                sample_spliced_reads=sample_reads,
                threads=threads
            )

            if val["status"] == "PASS":
                validation_pass += 1
            elif val["status"] == "WARN":
                validation_warn += 1
            else:
                validation_fail += 1

            val_msgs = " | ".join(val["messages"])
            details_lines.append(f" - {base}")
            details_lines.append(f"     sort      : {sort_label}")
            details_lines.append(f"     validation: {val['status']} ({val_msgs})")

        total = len(files)
        needs_sorting_flag = (len(sam_files) > 0) or (needs_sort > 0) or (unknown > 0)

        rec_lines = []
        if len(sam_files) > 0:
            rec_lines.append("• SAM files detected: enable 'Convert inputs to coordinate-sorted BAM'.")
        if needs_sort > 0:
            rec_lines.append("• Some inputs are not coordinate-sorted: conversion/sorting is recommended.")
        if unknown > 0:
            rec_lines.append("• Some inputs could not be checked reliably for sorting: conversion/sorting is recommended for safety.")
        if validation_fail > 0:
            rec_lines.append("• Some alignment files failed validation: do NOT run StringTie until those files are fixed.")
            rec_lines.append("• For short-read splice alignments, sampled spliced reads should carry XS tags.")
        elif validation_warn > 0:
            rec_lines.append("• Some validation checks were inconclusive; review the log before running.")
        if not rec_lines:
            rec_lines.append("• Inputs look usable for this StringTie pipeline.")

        log_block = []
        log_block.append("=== INPUT SCAN (sorting + BAM validation) ===")
        log_block.append(f"Directory: {bam_dir}")
        log_block.append(f"Sort-check sample reads: {sample_reads}")
        log_block.append(f"Strict BAM sort check (index test): {strict_check}")
        log_block.append(f"Total input files (BAM/SAM): {total}")
        log_block.append(f"  BAM: {len(bam_files)}")
        log_block.append(f"  SAM: {len(sam_files)}")
        log_block.append(f"Already coordinate-sorted BAM: {already_sorted}")
        log_block.append(f"Needs conversion/sorting: {needs_sort}")
        log_block.append(f"Unknown sort status: {unknown}")
        log_block.append(f"Validation PASS: {validation_pass}")
        log_block.append(f"Validation WARN: {validation_warn}")
        log_block.append(f"Validation FAIL: {validation_fail}")
        log_block.append("Details:")
        log_block.extend(details_lines)
        log_block.append("Recommendation:")
        log_block.extend(rec_lines)
        log_block.append("=" * 60)

        popup_lines = []
        popup_lines.append(f"Total files: {total}  (BAM={len(bam_files)}, SAM={len(sam_files)})")
        popup_lines.append(f"Sorted BAM: {already_sorted}")
        popup_lines.append(f"Needs conversion/sorting: {needs_sort}")
        popup_lines.append(f"Unknown sort status: {unknown}")
        popup_lines.append(f"Validation PASS/WARN/FAIL: {validation_pass}/{validation_warn}/{validation_fail}")
        popup_lines.append("")
        popup_lines.extend(rec_lines)

        return {
            "needs_sorting": bool(needs_sorting_flag),
            "validation_failures": int(validation_fail),
            "log_block": "\n".join(log_block),
            "popup_text": "\n".join(popup_lines),
        }

    # ---------------- Pipeline ---------------- #

    def _validate_alignment_files_or_raise(self, files: List[str], sample_reads: int, threads: int):
        """
        Validate alignment files before running StringTie.
        Raises RuntimeError if any file fails validation.
        """
        self.log("=== PREFLIGHT ALIGNMENT VALIDATION ===")
        failures = []
        warns = []

        for f in files:
            val = validate_alignment_file(
                path_win=f,
                sample_spliced_reads=sample_reads,
                threads=threads
            )
            base = os.path.basename(f)
            joined = " | ".join(val["messages"])
            self.log(f"[VALIDATE] {base} -> {val['status']} :: {joined}")

            if val["status"] == "FAIL":
                failures.append((base, joined))
            elif val["status"] == "WARN":
                warns.append((base, joined))

        if warns:
            self.log("Validation warnings:")
            for base, msg in warns:
                self.log(f"  - {base}: {msg}")

        if failures:
            lines = []
            lines.append("Alignment validation failed. Fix the following files before running StringTie:")
            lines.append("")
            for base, msg in failures:
                lines.append(f" - {base}: {msg}")
            lines.append("")
            lines.append("Common fix for short-read RNA-seq:")
            lines.append(" - realign so spliced reads carry XS tags")
            lines.append(" - STAR: add --outSAMstrandField intronMotif")
            lines.append(" - HISAT2: use --dta and the correct --rna-strandness")
            raise RuntimeError("\\n".join(lines))


    def _run_clicked(self):
        bam_dir = self.bam_dir_var.get().strip()
        gtf = self.gtf_var.get().strip()
        out_dir = self.out_dir_var.get().strip()
        threads = int(self.threads_var.get())
        sample_reads = int(self.sortcheck_reads_var.get())
        stringtie_cmd = self.stringtie_cmd_var.get().strip() or "stringtie"
        gffread_cmd = self.gffread_cmd_var.get().strip() or "gffread"

        if not bam_dir or not os.path.isdir(bam_dir):
            messagebox.showerror("Error", "Select a valid BAM/SAM input folder.")
            return
        if not gtf or not os.path.isfile(gtf):
            messagebox.showerror("Error", "Select a valid GTF file.")
            return
        if not out_dir:
            messagebox.showerror("Error", "Select a valid output directory.")
            return

        # Ensure output exists on Windows side
        os.makedirs(out_dir, exist_ok=True)

        do_convert_sorted = bool(self.convert_sort_var.get())
        do_index = bool(self.index_var.get())
        do_make_fasta = bool(self.make_fasta_var.get())
        do_strip_versions = bool(self.strip_versions_var.get())
        genome_fasta = self.genome_fa_var.get().strip()

        if do_make_fasta and (not genome_fasta or not os.path.isfile(genome_fasta)):
            messagebox.showerror("Error", "If 'Create merged FASTA' is enabled, select a valid Genome FASTA.")
            return

        self.run_button.config(state="disabled")
        self.scan_button.config(state="disabled")

        args = (
            bam_dir, gtf, out_dir, threads, sample_reads, stringtie_cmd,
            do_convert_sorted, do_index, do_make_fasta, do_strip_versions, genome_fasta, gffread_cmd
        )
        self.pipeline_thread = threading.Thread(target=self.run_pipeline, args=args, daemon=True)
        self.pipeline_thread.start()

    def run_pipeline(self, bam_dir, gtf_file, out_dir, threads, sample_reads, stringtie_cmd, do_convert_sorted, do_index,
                     do_make_fasta, do_strip_versions, genome_fasta, gffread_cmd):
        try:
            self._run_stringtie_two_pass(
                bam_dir=bam_dir,
                gtf_file=gtf_file,
                out_dir=out_dir,
                threads=threads,
                sample_reads=sample_reads,
                stringtie_cmd=stringtie_cmd,
                do_convert_sorted=do_convert_sorted,
                do_index=do_index,
                do_make_fasta=do_make_fasta,
                do_strip_versions=do_strip_versions,
                genome_fasta=genome_fasta,
                gffread_cmd=gffread_cmd
            )
            self.log("Pipeline completed successfully.")
        except Exception as ex:
            err = str(ex)
            self.log(f"ERROR: {err}")
            self.after(0, lambda m=err: messagebox.showerror("Error", m))
        finally:
            self.after(0, lambda: self.run_button.config(state="normal"))
            self.after(0, lambda: self.scan_button.config(state="normal"))

    # ----------------- gffread install/help ----------------- #

    @staticmethod
    def _gffread_install_hint_debian() -> str:
        return (
            "gffread is part of the Cufflinks/StringTie toolkit in many distros.\n"
            "Debian/Ubuntu install options:\n"
            "  1) apt (if available):\n"
            "     sudo apt-get update\n"
            "     sudo apt-get install gffread\n"
            "  2) conda:\n"
            "     conda install -c bioconda gffread\n"
            "  3) compile from source:\n"
            "     https://github.com/gpertea/gffread\n"
        )

    def _wsl_has_rsync(self) -> bool:
        try:
            rc = run_wsl_command("command -v rsync >/dev/null 2>&1")
            return rc == 0
        except Exception:
            return False

    def _wsl_copy_tree(self, src_wsl: str, dst_wsl: str):
        """
        Copy content of src_wsl directory into dst_wsl directory.

        Strategy (robust on /mnt/*):
          1) Ensure dst exists and is writable
          2) Try rsync (fast) with options that behave better on drvfs
          3) Fallback to tar stream copy (often more compatible)
        """
        # Ensure destination exists
        rc = run_wsl_command(f'mkdir -p "{dst_wsl}"', self.log)
        if rc != 0:
            raise RuntimeError(f"Failed to create destination folder in WSL: {dst_wsl}")

        # Basic writability test (drvfs can be weird on some paths)
        rc = run_wsl_command(
            f'test -d "{dst_wsl}" && touch "{dst_wsl}/.wsl_write_test" && rm -f "{dst_wsl}/.wsl_write_test"',
            self.log
        )
        if rc != 0:
            raise RuntimeError(
                "Destination folder is not writable from WSL.\n"
                f"Destination: {dst_wsl}\n"
                "Check Windows permissions / controlled folder access / antivirus."
            )

        # Try rsync first (if available)
        if self._wsl_has_rsync():
            # --inplace avoids mkstemp issues; --no-*/--omit-dir-times reduce drvfs metadata friction
            rsync_cmd = (
                f'rsync -a --inplace --no-perms --no-owner --no-group --omit-dir-times '
                f'"{src_wsl}/" "{dst_wsl}/"'
            )
            rc = run_wsl_command(rsync_cmd, self.log)
            if rc == 0:
                return

            self.log("WARNING: rsync copy-back failed (will try tar fallback).")

        # Fallback: tar stream copy (creates directories/files reliably)
        tar_cmd = f'cd "{src_wsl}" && tar -cf - . | (cd "{dst_wsl}" && tar -xf -)'
        rc = run_wsl_command(tar_cmd, self.log)
        if rc != 0:
            raise RuntimeError("Failed to copy results back to Windows output folder (tar fallback).")

    def _strip_versions_in_gtf_wsl_inplace(self, gtf_wsl: str):
        """
        Strip Ensembl version suffixes only (IDs starting with ENS...) in-place using sed.
        This avoids breaking StringTie novel IDs (e.g., MSTRG.43.1) which are NOT Ensembl versions.
        """
        self.log("=== Stripping Ensembl version suffixes in merged.gtf (Ensembl-only) ===")
        sed_cmd = (
            r"sed -E -i "
            r"'s/(gene_id \"ENS[^\"]+)\.[0-9]+\"/\1\"/g; "
            r"s/(transcript_id \"ENS[^\"]+)\.[0-9]+\"/\1\"/g' "
            f"\"{gtf_wsl}\""
        )

        rc = run_wsl_command(sed_cmd, self.log)
        if rc != 0:
            raise RuntimeError("Failed to strip Ensembl versions in merged.gtf (sed).")
        self.log("Stripping complete.")

    # ----------------- Core pipeline ----------------- #

    def _run_stringtie_two_pass(self, bam_dir: str, gtf_file: str, out_dir: str, threads: int,
                                sample_reads: int, stringtie_cmd: str,
                                do_convert_sorted: bool, do_index: bool,
                                do_make_fasta: bool, do_strip_versions: bool,
                                genome_fasta: str, gffread_cmd: str):

        # Discover input files
        input_files = [
            os.path.join(bam_dir, f)
            for f in os.listdir(bam_dir)
            if f.lower().endswith(".bam") or f.lower().endswith(".sam")
        ]
        input_files.sort()

        if not input_files:
            raise RuntimeError(f"No BAM/SAM files found in {bam_dir}")

        # Derive sample names
        sample_names = []
        for p in input_files:
            base = os.path.basename(p)
            sample = os.path.splitext(base)[0]
            sample_names.append(sample)

        # Log inputs
        self.log(f"Found {len(input_files)} BAM/SAM files in {bam_dir}")
        self.log(f"Using GTF: {gtf_file}")
        self.log(f"Output directory: {out_dir}")
        self.log(f"Threads: {threads}")
        self.log(f"Sort-check sample reads: {sample_reads}")
        self.log(f"StringTie command in WSL: {stringtie_cmd}")

        # Determine strandedness arg
        strand_label = self.strand_var.get()
        if strand_label.startswith("FR"):
            strand_arg = "--fr"
        elif strand_label.startswith("RF"):
            strand_arg = "--rf"
        else:
            strand_arg = ""  # unstranded
        self.log(f"Library strandedness: {strand_label} -> arg: {strand_arg if strand_arg else '(none)'}")

        self.log(f"Convert inputs to sorted BAM: {'YES' if do_convert_sorted else 'NO'}")
        self.log(f"Create index for sorted BAM: {'YES' if do_index else 'NO'}")
        self.log(f"Create merged FASTA (gffread): {'YES' if do_make_fasta else 'NO'}")
        self.log(f"Strip versions in merged.gtf: {'YES' if do_strip_versions else 'NO'}")
        if do_make_fasta:
            self.log(f"Genome FASTA (-g): {genome_fasta}")
            self.log(f"gffread command in WSL: {gffread_cmd}")
        self.log("-" * 60)

        # Prepare output structure on Windows side
        sorted_dir_win = os.path.join(out_dir, "sorted_bam")
        pass1_dir_win = os.path.join(out_dir, "pass1_assembly")
        pass2_dir_win = os.path.join(out_dir, "pass2_quant")
        os.makedirs(out_dir, exist_ok=True)
        os.makedirs(sorted_dir_win, exist_ok=True)
        os.makedirs(pass1_dir_win, exist_ok=True)
        os.makedirs(pass2_dir_win, exist_ok=True)

        # Work in WSL staging to avoid WSL<->/mnt/c temp issues
        stage_id = f"stringtie_stage_{int(time.time())}_{os.getpid()}"
        stage_root_wsl = f"/tmp/{stage_id}"
        stage_out_wsl = f"{stage_root_wsl}/out"

        out_dir_wsl = windows_to_wsl_path(out_dir)
        gtf_wsl = windows_to_wsl_path(gtf_file)

        # Build list of input files used by pipeline (possibly converted)
        align_files_win = list(input_files)

        try:
            # Create staging
            self.log("=== Preparing WSL staging folder ===")
            rc = run_wsl_command(f'mkdir -p "{stage_out_wsl}"', self.log)
            if rc != 0:
                raise RuntimeError("Failed to create WSL staging folder in /tmp.")

            # Optionally convert/sort inputs to coordinate-sorted BAM
            if do_convert_sorted:
                self.log("=== Converting/SORTING inputs to coordinate-sorted BAM (samtools, WSL) ===")
                align_files_win = []
                for p in input_files:
                    sample = os.path.splitext(os.path.basename(p))[0]
                    out_bam_win = os.path.join(sorted_dir_win, f"{sample}.sorted.bam")
                    out_bam_wsl = windows_to_wsl_path(out_bam_win)

                    in_wsl = windows_to_wsl_path(p)
                    cmd = f'samtools sort -@ {threads} -o "{out_bam_wsl}" "{in_wsl}"'
                    self.log(f"[CONVERT/SORT:{sample}] {cmd}")
                    rc = run_wsl_command(cmd, self.log)
                    if rc != 0:
                        raise RuntimeError(f"samtools sort failed for {sample}")

                    align_files_win.append(out_bam_win)

                self.log("All inputs converted/sorted to BAM.")

                # Optionally index sorted BAM
                if do_index:
                    for out_bam_win in align_files_win:
                        sample = os.path.splitext(os.path.basename(out_bam_win))[0].replace(".sorted", "")
                        out_bam_wsl = windows_to_wsl_path(out_bam_win)
                        cmd = f'samtools index -@ {threads} "{out_bam_wsl}"'
                        self.log(f"[INDEX:{sample}] {cmd}")
                        rc = run_wsl_command(cmd, self.log)
                        if rc != 0:
                            raise RuntimeError(f"samtools index failed for {sample}")
                    self.log("All sorted BAM files indexed (.bai).")
            else:
                self.log("=== Sort check because conversion/sorting is DISABLED ===")
                self.log(f"Strict BAM sort check (index test): {bool(self.strict_sortcheck_var.get())}")
                bad = []
                unk = []
                for f in align_files_win:
                    if not f.lower().endswith(".bam"):
                        continue
                    res, reason = detect_sort_status(f, sample_reads=sample_reads, threads=threads, strict_bam_check=bool(self.strict_sortcheck_var.get()))
                    self.log(f"[SORTCHECK] {os.path.basename(f)} -> {reason}")
                    if res is False:
                        bad.append(os.path.basename(f))
                    elif res is None:
                        unk.append(os.path.basename(f))

                if bad or unk:
                    msg = []
                    msg.append("Inputs do not appear to be coordinate-sorted BAM (or cannot be verified).")
                    if bad:
                        msg.append("")
                        msg.append("NOT sorted (check failed):")
                        for b in bad:
                            msg.append(f"  - {b}")
                    if unk:
                        msg.append("")
                        msg.append("UNKNOWN sort status:")
                        for u in unk:
                            msg.append(f"  - {u}")
                    msg.append("")
                    msg.append("Fix: enable 'Convert inputs to coordinate-sorted BAM' and rerun.")
                    raise RuntimeError("\n".join(msg))

            self._validate_alignment_files_or_raise(
                files=align_files_win,
                sample_reads=sample_reads,
                threads=threads
            )

            # Copy needed BAMs into staging? (StringTie can read from /mnt/c directly; keep as-is)
            # Create per-sample directories in staging
            rc = run_wsl_command(f'mkdir -p "{stage_out_wsl}/pass1_assembly" "{stage_out_wsl}/pass2_quant"', self.log)
            if rc != 0:
                raise RuntimeError("Failed to create staging output folders.")

            for s in sample_names:
                run_wsl_command(f'mkdir -p "{stage_out_wsl}/pass1_assembly/{s}" "{stage_out_wsl}/pass2_quant/{s}"', self.log)

            # PASS 1
            self.log("=== PASS 1: per-sample assembly (no -e) ===")
            pass1_gtfs_wsl = []
            for sample, bam_win in zip(sample_names, align_files_win):
                bam_wsl = windows_to_wsl_path(bam_win)
                out_gtf_wsl = f"{stage_out_wsl}/pass1_assembly/{sample}/{sample}.gtf"
                cmd = f'"{stringtie_cmd}" -p {threads} -G "{gtf_wsl}" {strand_arg} -o "{out_gtf_wsl}" "{bam_wsl}"'.strip()
                self.log(f"[PASS1:{sample}] Running: {cmd}")
                rc = run_wsl_command(cmd, self.log)
                if rc != 0:
                    raise RuntimeError(f"StringTie PASS 1 failed for sample: {sample}")
                pass1_gtfs_wsl.append(out_gtf_wsl)

            # Merge
            self.log("=== MERGE: stringtie --merge ===")
            mergelist_wsl = f"{stage_out_wsl}/mergelist.txt"
            # Write mergelist in staging
            tmp_list = "\n".join(pass1_gtfs_wsl) + "\n"
            tmp_local = os.path.join(out_dir, "._tmp_mergelist.txt")
            with open(tmp_local, "w", encoding="utf-8") as f:
                f.write(tmp_list)
            tmp_local_wsl = windows_to_wsl_path(tmp_local)
            run_wsl_command(f'cp "{tmp_local_wsl}" "{mergelist_wsl}"', self.log)
            try:
                os.remove(tmp_local)
            except Exception:
                pass

            merged_gtf_wsl = f"{stage_out_wsl}/merged.gtf"
            cmd_merge = f'"{stringtie_cmd}" --merge -p {threads} -G "{gtf_wsl}" -o "{merged_gtf_wsl}" "{mergelist_wsl}"'
            self.log(f"[MERGE] Running: {cmd_merge}")
            rc = run_wsl_command(cmd_merge, self.log)
            if rc != 0:
                raise RuntimeError("StringTie --merge failed.")

            # Optionally strip Ensembl versions
            if do_strip_versions:
                self._strip_versions_in_gtf_wsl_inplace(merged_gtf_wsl)

            # PASS 2 (quant with -e -B)
            self.log("=== PASS 2: quant (-e -B) ===")
            for sample, bam_win in zip(sample_names, align_files_win):
                bam_wsl = windows_to_wsl_path(bam_win)
                out_dir_sample_wsl = f"{stage_out_wsl}/pass2_quant/{sample}"
                out_gtf_wsl = f"{out_dir_sample_wsl}/{sample}.gtf"
                cmd = f'"{stringtie_cmd}" -e -B -p {threads} -G "{merged_gtf_wsl}" {strand_arg} -o "{out_gtf_wsl}" "{bam_wsl}"'.strip()
                self.log(f"[PASS2:{sample}] Running: {cmd}")
                rc = run_wsl_command(cmd, self.log)
                if rc != 0:
                    raise RuntimeError(f"StringTie PASS 2 failed for sample: {sample}")

            self.log("PASS 2 completed for all samples.")

            # Optionally create merged FASTA
            if do_make_fasta:
                merged_fa_wsl = f"{stage_out_wsl}/merged.fa"
                genome_wsl = windows_to_wsl_path(genome_fasta)
                cmd = f'"{gffread_cmd}" "{merged_gtf_wsl}" -g "{genome_wsl}" -w "{merged_fa_wsl}"'
                self.log(f"[GFFREAD] Running: {cmd}")
                rc = run_wsl_command(cmd, self.log)
                if rc != 0:
                    raise RuntimeError("gffread failed (see log for details).")

        finally:
            # Copy-back staged results if staging exists
            try:
                # Only attempt copy-back if stage_out exists
                rc = run_wsl_command(f'test -d "{stage_out_wsl}"', self.log)
                if rc == 0:
                    # Remove tmp dirs inside staging before copy-back (optional cleanup)
                    run_wsl_command(
                        f'find "{stage_out_wsl}" -maxdepth 4 -type d -name "tmp*" -print -exec rm -rf "{{}}" +',
                        self.log
                    )

                    # Pre-create expected destination folders (helps on some drvfs setups)
                    run_wsl_command(f'mkdir -p "{out_dir_wsl}"', self.log)
                    run_wsl_command(f'mkdir -p "{out_dir_wsl}/pass1_assembly" "{out_dir_wsl}/pass2_quant" "{out_dir_wsl}/sorted_bam"', self.log)
                    for s in sample_names:
                        run_wsl_command(f'mkdir -p "{out_dir_wsl}/pass1_assembly/{s}" "{out_dir_wsl}/pass2_quant/{s}"', self.log)

                    self.log("=== Copying staged results back to Windows output folder ===")
                    try:
                        self._wsl_copy_tree(stage_out_wsl, out_dir_wsl)
                        self.log("Copy-back done.")
                        run_wsl_command(f'rm -rf "{stage_root_wsl}"', self.log)
                        self.log("WSL staging cleaned up.")
                    except Exception as ex_copy:
                        # Do NOT abort the pipeline after PASS2 success; keep staging folder for manual recovery
                        msg = str(ex_copy)
                        self.log("ERROR: Failed to copy results back to Windows output folder.")
                        self.log(f"       {msg}")
                        self.log("NOTE: Results are still available in WSL staging folder:")
                        self.log(f"      {stage_out_wsl}")
                        self.log("Manual copy (inside WSL) example:")
                        self.log(f'  mkdir -p "{out_dir_wsl}" && cp -a "{stage_out_wsl}/." "{out_dir_wsl}/"')
                        self.after(
                            0,
                            lambda m=msg: messagebox.showwarning(
                                "Copy-back failed",
                                "StringTie finished, but copying results back to Windows failed.\n\n"
                                "Your results are still in WSL staging under:\n"
                                f"{stage_out_wsl}\n\n"
                                "See the log for a manual copy command.\n\n"
                                f"Details: {m}"
                            )
                        )
            except Exception:
                # Never block UI teardown on staging cleanup/copy
                pass


def main():
    app = StringTieGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
