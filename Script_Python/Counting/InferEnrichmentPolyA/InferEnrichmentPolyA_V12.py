#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Poly(A) Enrichment Predictor – Fast BUILD 11.9 (tabtxt, Windows-1252, PolyA probability)
-----------------------------------------------------------------------------------------
• Goal: Estimate the probability that a library is poly(A)-enriched (no statements about rRNA depletion).
• Outputs .tabtxt (pure tab-delimited, Windows-1252 / cp1252), with:
    - Column summaries and an expanded THRESHOLD LEGEND at the top (as '#' comments, ASCII-safe).
    - Probability of polyA enrichment (PolyA_Prob%) derived from FastScore by a logistic transform.
    - Qualitative scale (Very strong / Strong / Moderate / Weak / Unlikely) for polyA evidence.
    - Compact signal bins (Signals) and an expanded per-row Explanation (human-readable sentences).
• GUI label: "Output TabTxt"
• Optional BED12 proximity (3' end proximity; XS-stranded if available).
"""

import os, re, subprocess, threading, time, bisect, math
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from collections import defaultdict, Counter

def is_windows_path(p: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", p or ""))

def win_to_wsl_path(win_path: str) -> str:
    r"""Convert Windows path C:\dir\file to /mnt/c/dir/file (no double slashes)."""
    if not win_path:
        return win_path
    p = win_path.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", p):
        drive = p[0].lower()
        rest = p[2:]
        if rest.startswith("/"):
            rest = rest[1:]
        return f"/mnt/{drive}/{rest}"
    return p

def parse_cigar(cigar: str):
    out, num = [], ""
    for ch in cigar:
        if ch.isdigit():
            num += ch
        else:
            if num:
                out.append((ch, int(num)))
                num = ""
    return out

def at_purity(s: str) -> float:
    if not s:
        return 0.0
    u = s.upper()
    a = u.count("A")
    t = u.count("T")
    return max(a, t) / max(1, len(s))

def detect_polyA_tail(seq, cigar, min_tail_len=10, min_purity=0.8):
    ops = parse_cigar(cigar)
    if not ops:
        return {"has_tail": False}
    left_S  = ops[0][0]  == "S"
    right_S = ops[-1][0] == "S"
    left_seq  = seq[:ops[0][1]]   if left_S  else ""
    right_seq = seq[-ops[-1][1]:] if right_S else ""

    cands = []
    if left_S  and len(left_seq)  >= min_tail_len and at_purity(left_seq)  >= min_purity:
        cands.append(("5p", len(left_seq),  at_purity(left_seq),  left_seq))
    if right_S and len(right_seq) >= min_tail_len and at_purity(right_seq) >= min_purity:
        cands.append(("3p", len(right_seq), at_purity(right_seq), right_seq))
    if not cands:
        return {"has_tail": False}

    end, ln, pu, seg = sorted(cands, key=lambda x: (x[1], x[2]), reverse=True)[0]

    HEX = {
        "AATAAA","ATTAAA","AGTAAA","TATAAA","CATAAA","GATAAA","AATACA","AATAGA",
        "AAAAAA","AAAATA","AAATAA","ATAAAA","TTTTTT","TTTTTA","TTTTAT"
    }
    k = min(25, len(seg))
    win = seg[-k:].upper() if end == "3p" else seg[:k].upper()
    has_hex = any(h in win for h in HEX)

    return {"has_tail": True, "end": end, "length": ln, "purity": pu, "has_hexamer": has_hex}

def sample_bam_reads(bam_path, sample_reads=200000, min_tail_len=10, min_purity=0.8,
                     hard_impair_thresh=0.15, threads=4, progress_cb=None):
    bam_wsl = win_to_wsl_path(bam_path) if is_windows_path(bam_path) else bam_path
    cmd = ["wsl", "samtools", "view", "-@", str(max(1, int(threads))), bam_wsl]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1)
    threading.Thread(target=lambda: [None for _ in proc.stderr], daemon=True).start()

    total = tails = sum_len = sum_pur = tails_5p = tails_3p = 0
    soft5 = soft3 = hard5 = hard3 = hex_hits = 0
    t0 = time.time()

    for line in proc.stdout:
        if not line or line.startswith("@"):
            continue
        f = line.rstrip("\n").split("\t")
        if len(f) < 11:
            continue
        cigar, seq = f[5], f[9]
        res = detect_polyA_tail(seq, cigar, min_tail_len, min_purity)
        ops = parse_cigar(cigar)
        if ops:
            if ops[0][0] == "S": soft5 += 1
            if ops[-1][0] == "S": soft3 += 1
            if ops[0][0] == "H": hard5 += 1
            if ops[-1][0] == "H": hard3 += 1
        if res.get("has_tail"):
            tails += 1
            sum_len += res["length"]
            sum_pur += res["purity"]
            if res["end"] == "5p": tails_5p += 1
            else: tails_3p += 1
            if res["has_hexamer"]: hex_hits += 1
        total += 1
        if progress_cb and time.time() - t0 > 0.3:
            progress_cb(total)
            t0 = time.time()
        if total >= sample_reads:
            break

    try:
        proc.terminate()
    except Exception:
        pass

    if total == 0:
        return {k: 0 for k in (
            "TotalReadsScanned","TailReads","TailFrac","MeanTailLen","MeanTailPurity",
            "Tails5p","Tails3p","SoftClip5p_All","SoftClip3p_All","HardClip5p","HardClip3p",
            "SoftClipFrac","HardClipFlag","HexamerRate"
        )}

    tail_frac = tails / total
    mean_len  = (sum_len / tails) if tails else 0.0
    mean_pur  = (sum_pur / tails) if tails else 0.0
    soft_frac = min((soft5 + soft3) / (2 * total), 1.0)
    hard_flag = (hard5 + hard3) / (2 * total) >= hard_impair_thresh
    hex_rate  = (hex_hits / tails) if tails else 0.0

    return dict(
        TotalReadsScanned=total,
        TailReads=tails,
        TailFrac=tail_frac,
        MeanTailLen=mean_len,
        MeanTailPurity=mean_pur,
        Tails5p=tails_5p,
        Tails3p=tails_3p,
        SoftClip5p_All=soft5,
        SoftClip3p_All=soft3,
        HardClip5p=hard5,
        HardClip3p=hard3,
        SoftClipFrac=soft_frac,
        HardClipFlag=hard_flag,
        HexamerRate=hex_rate
    )

def load_bed12_3ends(bed12_path, log=lambda s: None):
    """Return dict of transcript 3' ends by chrom (+ and - strands)."""
    log(f"[BED12] Loading 3' ends from {bed12_path}")
    p = subprocess.Popen(["wsl", "cat", bed12_path], stdout=subprocess.PIPE, text=True)
    fwd, rev = defaultdict(list), defaultdict(list)
    for ln in p.stdout:
        if not ln.strip() or ln.startswith("#"):
            continue
        f = ln.rstrip("\n").split("\t")
        if len(f) < 6:
            continue
        chrom, start, end, strand = f[0], int(f[1]), int(f[2]), f[5]
        if strand == "+": fwd[chrom].append(end)
        elif strand == "-": rev[chrom].append(start)
    for d in (fwd, rev):
        for k in d: d[k].sort()
    log(f"[BED12] Loaded transcripts: {sum(len(v) for v in fwd.values()) + sum(len(v) for v in rev.values()):,}")
    return fwd, rev

def within_window(lst, x, w):
    i = bisect.bisect_left(lst, x)
    for j in (i-1, i, i+1):
        if 0 <= j < len(lst) and abs(lst[j]-x) <= w:
            return True
    return False

def compute_proximity(bam, fwd, rev, window=200, reads=200000, threads=4):
    """Return proximity metrics: fraction near any 3' end, XS-stranded proximity, and XS tag counts."""
    bam_wsl = win_to_wsl_path(bam) if is_windows_path(bam) else bam
    cmd = ["wsl", "samtools", "view", "-@", str(max(1, int(threads))), bam_wsl]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    threading.Thread(target=lambda: [None for _ in p.stderr], daemon=True).start()

    n = near_any = near_strand = 0
    xs = Counter()
    for line in p.stdout:
        if not line or line.startswith("@"): 
            continue
        f = line.rstrip("\n").split("\t")
        if len(f) < 11: 
            continue
        rname, pos, cigar = f[2], int(f[3]), f[5]
        cons = sum(l for op, l in parse_cigar(cigar) if op in "MDN=X")
        read3 = pos + max(cons - 1, 0)

        xs_tag = next((x[5] for x in f[11:] if x.startswith("XS:A:")), None)

        if (rname in fwd and within_window(fwd[rname], read3, window)) or \
           (rname in rev and within_window(rev[rname], pos,   window)):
            near_any += 1

        if xs_tag and xs_tag in "+-":
            xs[xs_tag] += 1
            if xs_tag == "+" and rname in fwd and within_window(fwd[rname], read3, window):
                near_strand += 1
            if xs_tag == "-" and rname in rev and within_window(rev[rname], pos, window):
                near_strand += 1

        n += 1
        if n >= reads:
            break

    try:
        p.terminate()
    except Exception:
        pass

    return dict(ProxAny=near_any / max(1, n),
                ProxStranded=near_strand / max(1, n),
                XS_plus=xs.get("+", 0),
                XS_minus=xs.get("-", 0),
                N=n)

def scale_from_score(score: float):
    if score >= 0.35: return "Very strong"
    if score >= 0.25: return "Strong"
    if score >= 0.18: return "Moderate"
    if score >= 0.12: return "Weak"
    return "Unlikely"

def polyA_probability(score: float, center=0.18, k=60.0):
    return 1.0 / (1.0 + math.exp(-k * (score - center)))

def label_from_probability(p: float):
    if p >= 0.85: return "Very strong"
    if p >= 0.65: return "Strong"
    if p >= 0.45: return "Moderate"
    if p >= 0.25: return "Weak"
    return "Unlikely"

def signal_band(name, value, bands):
    for label, lo, hi in bands:
        if lo <= value < hi:
            return f"{name}:{label}"
    return f"{name}:NA"

BANDS = {
    "tails3p": [("very", 0.010, 1.0), ("some", 0.004, 0.010), ("low", 0.0, 0.004)],
    "tailfrac": [("high", 0.015, 1.0), ("med", 0.005, 0.015), ("low", 0.0, 0.005)],
    "taillen": [("long", 20,  999), ("ok", 12, 20), ("short", 0, 12)],
    "hex":     [("high", 0.20, 1.0), ("med", 0.05, 0.20), ("low", 0.0, 0.05)],
    "prox":    [("near", 0.10, 1.0), ("some", 0.03, 0.10), ("far", 0.0, 0.03)],
}

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Poly(A) Enrichment Predictor [Fast BUILD 11.9 — PolyA Probability]")
        self.geometry("1200x980")
        self._build_ui()

    def _build_ui(self):
        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True)
        self.main = ttk.Frame(nb, padding=10); nb.add(self.main, text="Predictor")
        self.help = ttk.Frame(nb, padding=10); nb.add(self.help, text="Help")

        row = 0
        self.mode = tk.StringVar(value="single")
        fr = ttk.LabelFrame(self.main, text="Mode"); fr.grid(row=row, column=0, columnspan=6, sticky="we")
        ttk.Radiobutton(fr, text="Single BAM", value="single", variable=self.mode, command=self._mode).grid(row=0, column=0, padx=5)
        ttk.Radiobutton(fr, text="Folder of BAMs", value="folder", variable=self.mode, command=self._mode).grid(row=0, column=1, padx=5)
        row += 1

        self.path = tk.StringVar(); self.lab = ttk.Label(self.main, text="BAM file:")
        self.lab.grid(row=row, column=0, sticky="w")
        ttk.Entry(self.main, textvariable=self.path, width=100).grid(row=row, column=1, columnspan=4, sticky="we")
        ttk.Button(self.main, text="Browse...", command=self._browse).grid(row=row, column=5)
        row += 1

        self.out = tk.StringVar(value=os.path.join(os.getcwd(), "polyA_prediction_summary.tabtxt"))
        ttk.Label(self.main, text="Output TabTxt:").grid(row=row, column=0, sticky="w")
        ttk.Entry(self.main, textvariable=self.out, width=100).grid(row=row, column=1, columnspan=4, sticky="we")
        ttk.Button(self.main, text="Browse...", command=self._browse_out).grid(row=row, column=5)
        row += 1

        prm = ttk.LabelFrame(self.main, text="Parameters"); prm.grid(row=row, column=0, columnspan=6, sticky="we", pady=8)
        self.sample = tk.IntVar(value=200000); self.minlen = tk.IntVar(value=10)
        self.minpur = tk.DoubleVar(value=0.8); self.threads = tk.IntVar(value=4); self.hard = tk.DoubleVar(value=0.15)
        ttk.Label(prm, text="Max reads to sample:").grid(row=0, column=0, sticky="w")
        ttk.Entry(prm, textvariable=self.sample, width=10).grid(row=0, column=1, sticky="w")
        ttk.Label(prm, text="Min tail length:").grid(row=0, column=2, sticky="w")
        ttk.Entry(prm, textvariable=self.minlen, width=8).grid(row=0, column=3, sticky="w")
        ttk.Label(prm, text="Min tail A/T purity:").grid(row=1, column=0, sticky="w")
        ttk.Entry(prm, textvariable=self.minpur, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(prm, text="WSL samtools threads:").grid(row=1, column=2, sticky="w")
        ttk.Entry(prm, textvariable=self.threads, width=8).grid(row=1, column=3, sticky="w")
        ttk.Label(prm, text="Hard-clip impairment threshold:").grid(row=2, column=0, sticky="w")
        ttk.Entry(prm, textvariable=self.hard, width=8).grid(row=2, column=1, sticky="w")
        row += 1

        opt = ttk.LabelFrame(self.main, text="Optional: BED12 proximity"); opt.grid(row=row, column=0, columnspan=6, sticky="we", pady=8)
        self.usebed = tk.BooleanVar()
        ttk.Checkbutton(opt, text="Enable BED12-based 3' proximity", variable=self.usebed).grid(row=0, column=0, sticky="w")
        self.bed = tk.StringVar()
        ttk.Entry(opt, textvariable=self.bed, width=100).grid(row=1, column=1, columnspan=4, sticky="we")
        ttk.Button(opt, text="Browse...", command=self._browse_bed).grid(row=1, column=5)
        self.win = tk.IntVar(value=200); ttk.Label(opt, text="+/- window (bp):").grid(row=2, column=0, sticky="w")
        ttk.Entry(opt, textvariable=self.win, width=10).grid(row=2, column=1, sticky="w")
        row += 1

        frb = ttk.Frame(self.main); frb.grid(row=row, column=0, columnspan=6, sticky="we")
        ttk.Button(frb, text="Run Analysis", command=self._run).pack(side="left")
        self.prog = ttk.Label(frb, text=""); self.prog.pack(side="left", padx=10)
        row += 1

        self.txt = tk.Text(self.main, wrap="word", height=26); self.txt.grid(row=row, column=0, columnspan=6, sticky="nsew")
        self.main.rowconfigure(row, weight=1)

        help = tk.Text(self.help, wrap="word"); help.pack(fill="both", expand=True)
        help.insert("1.0", "Heuristic PolyA probability predictor (no RSeQC).\nUses tail purity, hexamer presence, and optional BED12 proximity.\nOutputs .tabtxt (Windows-1252) with PolyA probability and explanations.")
        help.config(state="disabled")

    def _mode(self):
        self.lab.config(text="BAM file:" if self.mode.get() == "single" else "Folder with BAMs")
        self.path.set("")

    def _browse(self):
        p = filedialog.askopenfilename(title="Select BAM") if self.mode.get() == "single" else filedialog.askdirectory(title="Select folder")
        if p: self.path.set(p)

    def _browse_out(self):
        p = filedialog.asksaveasfilename(title="Save TabTxt", defaultextension=".tabtxt")
        if p: self.out.set(p)

    def _browse_bed(self):
        p = filedialog.askopenfilename(title="Select BED12", filetypes=[("BED12","*.bed12 *.bed"), ("All files","*.*")])
        if not p: return
        wp = win_to_wsl_path(p) if is_windows_path(p) else p
        self.bed.set(wp)

    def log(self, msg):
        self.txt.insert("end", msg + "\n"); self.txt.see("end"); self.update_idletasks()

    @staticmethod
    def _sanitize_field(x):
        return str(x).replace('"', '')

    def _run(self):
        out = self.out.get().strip()
        if not out:
            return messagebox.showerror("Missing", "Output file missing.")
        try:
            sample = int(self.sample.get()); minlen = int(self.minlen.get())
            minpur  = float(self.minpur.get()); threads = int(self.threads.get())
            hard    = float(self.hard.get());   win     = int(self.win.get())
        except:
            return messagebox.showerror("Error", "Invalid numeric parameter.")

        if self.mode.get() == "single":
            if not os.path.isfile(self.path.get()):
                return messagebox.showerror("Error", "BAM not found.")
            bams = [self.path.get()]
        else:
            if not os.path.isdir(self.path.get()):
                return messagebox.showerror("Error", "Folder missing.")
            bams = [os.path.join(self.path.get(), f) for f in os.listdir(self.path.get()) if f.lower().endswith(".bam")]
            if not bams:
                return messagebox.showerror("Error", "No BAMs found.")

        usebed = self.usebed.get() and self.bed.get().startswith("/mnt/")
        fwd = rev = None
        if usebed:
            fwd, rev = load_bed12_3ends(self.bed.get(), log=self.log)

        summaries = [
            "# File: Basename of the input BAM file.",
            "# TotalReadsScanned: Number of aligned records sampled from the BAM.",
            "# TailReads: Reads with candidate poly(A/T) soft-clip detected at either end.",
            "# TailFrac: TailReads / TotalReadsScanned, as a percentage.",
            "# MeanTailLen: Mean length (nt) of detected soft-clip tails.",
            "# MeanTailPurity: Mean A/T purity (0-1) of detected tails.",
            "# Tails5p: Count of tail calls at the 5' end.",
            "# Tails3p: Count of tail calls at the 3' end (3'-biased tails support polyA selection).",
            "# SoftClip5p_All: Reads with any 5' soft-clip (S in CIGAR).",
            "# SoftClip3p_All: Reads with any 3' soft-clip (S in CIGAR).",
            "# HardClip5p: Reads with hard-clip at the 5' end (H in CIGAR).",
            "# HardClip3p: Reads with hard-clip at the 3' end (H in CIGAR).",
            "# SoftClipFrac: Fraction of reads with soft-clips at either end (as a percentage).",
            "# HardClipFlag: YES if hard-clip fraction suggests impaired tail detection (may hide polyA soft-clips).",
            "# HexamerRate: Fraction of tail reads containing poly(A)-like motif/hexamer signal.",
            "# Prox3p_any: Fraction of reads whose ends fall within +/-window of any transcript 3' end (BED12).",
            "# Prox3p_stranded: Strand-aware fraction of reads near 3' ends when XS tags are present.",
            "# XS_plus: Count of reads with XS:A:+ (if present).",
            "# XS_minus: Count of reads with XS:A:- (if present).",
            "# FastScore: Heuristic combination of features emphasizing 3' tails, tail fraction, and proximity.",
            "# PolyA_Prob%: Probability (0-100) of polyA enrichment (from FastScore via logistic transform).",
            "# PolyA_Scale: Qualitative strength of polyA evidence (Very strong/Strong/Moderate/Weak/Unlikely).",
            "# Signals: Compact per-signal bins (e.g., tails3p:some; tailfrac:low; taillen:ok; hex:med; prox:near).",
            "# Explanation: Human-readable summary of why the probability was assigned."
        ]

        legend = [
            "# --- Threshold legend (all oriented to polyA evidence) ---",
            "# 3' Tail rate (Tails3p/reads): very >= 1.0% (supports), some >= 0.4% (weak support), low < 0.4% (argues against).",
            "# TailFrac (TailReads/reads): high >= 1.5% (supports), med >= 0.5% (weak support), low < 0.5% (argues against).",
            "# MeanTailLen: long >= 20 nt (supports), ok 12-19 nt (weak support), short < 12 nt (argues against).",
            "# HexamerRate (polyA-like motif in tails): high >= 0.20 (supports), med >= 0.05 (weak support), low < 0.05 (argues against).",
            "# Prox3p_any (BED12 +/-window): near >= 0.10 (supports), some >= 0.03 (weak support), far < 0.03 (argues against).",
            "# Hard-clip impairment: (HardClip5p+HardClip3p)/(2xreads) >= 0.15 -> YES (reduces visibility of soft-clips; may lower evidence).",
            "# FastScore weights: 3' tails 0.50; TailFrac 0.15; TailLen 0.15 (cap 30 nt); ProxAny 0.10; ProxStranded 0.07; Hexamer 0.03.",
            "# Probability mapping: P = 1/(1 + exp(-k*(score-center))) with center=0.18 (50% line), k=60 (steepness).",
            "# PolyA_Scale by probability: Very strong >= 85%; Strong >= 65%; Moderate >= 45%; Weak >= 25%; Unlikely < 25%.",
            "# Notes: thresholds are heuristic and may vary with depth, organism, aligner, and pre-processing."
        ]

        header = ["File","TotalReadsScanned","TailReads","TailFrac","MeanTailLen","MeanTailPurity",
                  "Tails5p","Tails3p","SoftClip5p_All","SoftClip3p_All","HardClip5p","HardClip3p",
                  "SoftClipFrac","HardClipFlag","HexamerRate",
                  "Prox3p_any","Prox3p_stranded","XS_plus","XS_minus",
                  "FastScore","PolyA_Prob%","PolyA_Scale","Signals","Explanation"]

        with open(out, "w", encoding="cp1252", errors="replace") as f:
            for line in summaries: f.write(line + "\n")
            for line in legend:    f.write(line + "\n")
            f.write("\n")
            f.write("\t".join(header) + "\n")

            for i, bam in enumerate(bams, 1):
                self.log(f"[{i}/{len(bams)}] {bam}")
                s = sample_bam_reads(bam, sample, minlen, minpur, hard, threads,
                                     progress_cb=lambda n: self.prog.config(text=f"Reads {n}/{sample}"))

                prox = dict(ProxAny=0.0, ProxStranded=0.0, XS_plus=0, XS_minus=0, N=0)
                if usebed and fwd is not None:
                    prox = compute_proximity(bam, fwd, rev, window=win, reads=sample, threads=threads)

                score = (0.5 * (s['Tails3p'] / max(1, s['TotalReadsScanned'])) +
                         0.15 * s['TailFrac'] +
                         0.15 * min(s['MeanTailLen'] / 30.0, 1.0) +
                         0.10 * prox['ProxAny'] +
                         0.07 * prox['ProxStranded'] +
                         0.03 * s['HexamerRate'])
                prob = 1.0 / (1.0 + math.exp(-60.0 * (score - 0.18)))
                label = label_from_probability(prob)

                tails3p_rate = s['Tails3p'] / max(1, s['TotalReadsScanned'])
                sigs = [
                    signal_band("tails3p", tails3p_rate, BANDS["tails3p"]),
                    signal_band("tailfrac", s['TailFrac'], BANDS["tailfrac"]),
                    signal_band("taillen", s['MeanTailLen'], BANDS["taillen"]),
                    signal_band("hex", s['HexamerRate'], BANDS["hex"]),
                    signal_band("prox", prox['ProxAny'], BANDS["prox"])
                ]
                signals_str = "; ".join(sigs)

                parts = []
                if tails3p_rate >= 0.010: parts.append("3' tail rate >= 1.0% (strong indicator).")
                elif tails3p_rate >= 0.004: parts.append("3' tail rate between 0.4% and 1.0% (weak support).")
                else: parts.append("3' tail rate < 0.4% (argues against).")
                if s['TailFrac'] >= 0.015: parts.append("Tail fraction >= 1.5% (supports polyA).")
                elif s['TailFrac'] >= 0.005: parts.append("Tail fraction 0.5%-1.5% (weak support).")
                else: parts.append("Tail fraction < 0.5% (argues against).")
                if s['MeanTailLen'] >= 20: parts.append("Mean tail length >= 20 nt (consistent with polyA).")
                elif s['MeanTailLen'] >= 12: parts.append("Mean tail length 12-19 nt (acceptable).")
                else: parts.append("Mean tail length < 12 nt (weak).")
                if s['HexamerRate'] >= 0.20: parts.append("PolyA-like hexamer frequent in tails (supports).")
                elif s['HexamerRate'] >= 0.05: parts.append("PolyA-like hexamer sometimes present (weak support).")
                else: parts.append("PolyA-like hexamer rare (argues against).")
                if prox['ProxAny'] >= 0.10: parts.append("Read ends often near 3' termini (supports).")
                elif prox['ProxAny'] >= 0.03: parts.append("Some proximity to 3' termini (weak support).")
                else: parts.append("Little proximity to 3' termini (argues against).")
                if s['HardClipFlag']: parts.append("High hard-clipping may hide soft-clipped tails (evidence may be under-estimated).")

                explanation = " ".join(parts)

                row = [
                    os.path.basename(bam),
                    s["TotalReadsScanned"],
                    s["TailReads"],
                    f"{s['TailFrac']*100:.2f}%",
                    f"{s['MeanTailLen']:.1f}",
                    f"{s['MeanTailPurity']:.3f}",
                    s["Tails5p"], s["Tails3p"],
                    s["SoftClip5p_All"], s["SoftClip3p_All"],
                    s["HardClip5p"], s["HardClip3p"],
                    f"{s['SoftClipFrac']*100:.2f}%",
                    ("YES" if s["HardClipFlag"] else "NO"),
                    f"{s['HexamerRate']:.3f}",
                    f"{prox['ProxAny']:.3f}",
                    f"{prox['ProxStranded']:.3f}",
                    prox["XS_plus"], prox["XS_minus"],
                    f"{score:.3f}",
                    f"{prob*100:.1f}%",
                    label,
                    signals_str,
                    explanation
                ]
                row = [self._sanitize_field(x) for x in row]
                f.write("\t".join(map(str, row)) + "\n")

                self.log(f"TailFrac={s['TailFrac']*100:.2f}%  Len={s['MeanTailLen']:.1f}  Pur={s['MeanTailPurity']:.3f}  Hex={s['HexamerRate']:.3f}")
                self.log(f"Prox_any={prox['ProxAny']:.3f}  Prox_str={prox['ProxStranded']:.3f}  Score={score:.3f}  PolyA_Prob={prob*100:.1f}%  Scale={label}")

            self.log("\nSummary TabTxt written (Windows-1252): " + out)

def main(): App().mainloop()
if __name__ == "__main__": main()
