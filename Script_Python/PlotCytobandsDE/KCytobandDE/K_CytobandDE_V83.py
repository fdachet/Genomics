#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Cytoband DEG Explorer — 24 panels (multi-patient, NEW FORMAT + gene_type + per-gene segments)

Key features:
• Band mode: ratio-centered coloring with selectable color baseline (GENOME/CHROM/NONE)
• Segment mode: per-gene colored segments, optional intensity-by-|FC| with Unified/Separate scaling
• Color baseline applies to BOTH Band and Segment modes:
    - Band mode: determines ratio_centered (as before)
    - Segment mode: determines the SCOPE for intensity quantiles (GENOME vs CHROM)
• Intensity-by-|FC| (segments):
    - Separate: red and blue scaled independently via robust quantiles (5th–95th)
    - Unified: both red and blue share a single global |FC| scale
    - Scope: GENOME vs CHROM as per the “Color baseline” radio; NONE ⇒ GENOME
    - Single-value (only 1 qualifying segment on a chromosome) ⇒ max intensity
• Manual / LIVE rendering:
    - LIVE: every change redraws
    - MANUAL: queue changes; redraw only after clicking “Update”
    - Displays “Processing update…” during redraws
• Filtered (gray) segments/bands are NOT clickable; only red/white/blue respond.

NEW INPUT FORMAT (fixed first 8 columns):
1) chr
2) band
3) CytobandSizeInGenes
4) CytobandSizeInNT
5) gene
6) gene_order      <-- order of each gene on its chromosome
7) immune_corr
8) gene_type
Then, for EACH patient, columns repeat in triplets:
  [ PtName_FC, PtName_FDR, PtName_TPM ], then next patient [ Pt2_FC, Pt2_FDR, Pt2_TPM ], …
"""

from __future__ import annotations

import io
import os
import re
from collections import OrderedDict
from typing import Dict, List, Tuple, Set, Optional

import numpy as np
import pandas as pd

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.patches
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ----------------------------- Color Settings (TWEAK HERE) ------------------------------
# Colors are floats in [0,1]. LOW = faintest visible tint; HIGH = strongest tint.
RED_LOW   = (1.00, 0.70, 0.70)   # faintest red (still clearly red)(1.00, 0.70, 0.70)  
RED_HIGH  = (1.00, 0, 0)   # strongest red(1.00, 0.12, 0.12)
BLUE_LOW  = (0.70, 0.70, 1.00)   # faintest blue (still clearly blue)(0.70, 0.70, 1.00)
BLUE_HIGH = (0, 0, 1.00)   # strongest blue(0.12, 0.12, 1.00)

# Minimum intensity floors (so “low” never fades into white), and optional gamma to brighten/darken ramps
MIN_INTENSITY_BAND = 0.12   # band mode floor for non-neutral colored bands
MIN_INTENSITY_SEG  = 0.12   # segment mode floor when Intensity-by-|FC| is ON
GAMMA_BAND         = 1.00   # <1 brightens lows; >1 darkens lows
GAMMA_SEG          = 1.00   # <1 brightens lows; >1 darkens lows

NEUTRAL_WHITE = (1.0, 1.0, 1.0)   # neutral = white
DIMMED_COLOR  = (0.93, 0.93, 0.93)  # de-emphasized (out of band count range)
# ----------------------------------------------------------------------------------------

# ----------------------------- config ------------------------------

BASE_COLS = [
    "chr", "band", "band_gene_count", "band_nt_size",
    "gene", "gene_order", "immune_corr", "gene_type"   # 8 fixed columns
]

DEFAULT_BAR_WIDTH = 0.12
DEFAULT_WSPACE = 0.18
GAP_FRACTION = 0.035
MIN_GAP_ABS   = 4.0

LABEL_DIMMED = "#888"
LABEL_NORMAL = "#000"

PANELS = 24  # 12 top, 12 bottom

LEFT_MIN_WIDTH = 380
LEFT_WRAP = 320
PAD_S = (4, 2)

EPS = 1e-9

# --- segments-mode drawing constants --------------------------------

PINK_TICK_COLOR = (1.0, 0.6, 0.8, 1.0)   # soft pink
PINK_TICK_LEN   = 0.06                   # tick length in X data units (constant in X)
PINK_TICK_LW    = 0.51                   # constant visual thickness (points)
LEFT_LABEL_PAD  = 0.16                   # extra x-space to the left for gene names
RIGHT_EXTRA_PAD = 0.10                   # a bit wider so ticks never clip

GENE_NAME_FONTSIZE = 7
GENE_NAME_COLOR_UP = (RED_HIGH[0], RED_HIGH[1], RED_HIGH[2], 1.0)
GENE_NAME_COLOR_DN = (BLUE_HIGH[0], BLUE_HIGH[1], BLUE_HIGH[2], 1.0)

# ----------------------------- I/O helpers -------------------------

def _detect_bom_encoding(path: str) -> str:
    with open(path, "rb") as f:
        head = f.read(4)
    if head.startswith(b"\xEF\xBB\xBF"):
        return "utf-8-sig"
    if head.startswith(b"\xFF\xFE") or head.startswith(b"\xFE\xFF"):
        return "utf-16"
    return "utf-8"

def _guess_delimiter_from_text(sample: str) -> Optional[str]:
    candidates = ['\t', ',', ';', '|']
    counts = {c: sample.count(c) for c in candidates}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else None

def _read_text_table_headered(path: str) -> pd.DataFrame:
    enc = _detect_bom_encoding(path)
    sep = None
    try:
        with io.open(path, "r", encoding=enc, errors="strict") as fh:
            sample = fh.read(8192)
            sep = _guess_delimiter_from_text(sample)
    except Exception:
        pass
    return pd.read_csv(path, encoding=enc, sep=sep, engine="python", header=0)

def _read_excel_headered(path: str) -> pd.DataFrame:
    return pd.read_excel(path, header=0)

def _norm_chr(s: pd.Series) -> pd.Series:
    return s.astype(str).str.replace("^chr", "", regex=True).str.strip()

def _to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")

def _extract_patient_from_fc_header(colname: str, fallback: str) -> str:
    if not isinstance(colname, str):
        return fallback
    name = colname.strip()
    if "_" in name:
        pt = name.split("_", 1)[0].strip()
        return pt if pt else fallback
    if " " in name:
        pt = name.split(" ", 1)[0].strip()
        return pt if pt else fallback
    return fallback

def read_multi_patient_newformat(path: str) -> "OrderedDict[str, pd.DataFrame]":
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        raw = _read_excel_headered(path)
    else:
        raw = _read_text_table_headered(path)

    ncols = raw.shape[1]
    if ncols < 11:  # 8 fixed + 3 for first patient
        raise ValueError(f"Expected at least 11 columns (8 fixed + 3 per first patient); got {ncols}.")

    core = raw.iloc[:, :8].copy()
    core.columns = BASE_COLS

    if "gene_type" in core.columns:
        core["gene_type"] = (
            core["gene_type"]
            .astype(str).fillna("Unknown").str.strip()
            .replace({"": "Unknown"})
        )

    rem = ncols - 8
    if rem % 3 != 0:
        raise ValueError(
            f"After the first 8 columns, the remaining columns ({rem}) must be a multiple of 3 (FC,FDR,TPM per patient)."
        )

    n_patients = rem // 3
    patients: "OrderedDict[str, pd.DataFrame]" = OrderedDict()

    for i in range(n_patients):
        s = 8 + 3*i

        label = _extract_patient_from_fc_header(str(raw.columns[s]), fallback=f"Patient_{i+1}")
        base_label = label
        k = 1
        while label in patients:
            k += 1
            label = f"{base_label} ({k})"

        df = pd.DataFrame({
            "chr":        _norm_chr(core["chr"]),
            "band":       core["band"].astype(str).str.strip(),
            "band_gene_count": _to_num(core["band_gene_count"]),
            "band_nt_size":    _to_num(core["band_nt_size"]),
            "gene":       core["gene"].astype(str).str.strip(),
            "gene_order": _to_num(core["gene_order"]),
            "immune_corr":_to_num(core["immune_corr"]),
            "gene_type":  core["gene_type"].astype(str).fillna("Unknown").str.strip().replace({"": "Unknown"}),
            "fc":         _to_num(raw.iloc[:, s]),
            "fdr":        _to_num(raw.iloc[:, s+1]),   # EXPECTED AS PERCENT already
            "tpm":        _to_num(raw.iloc[:, s+2]),
        })

        df["band_gene_count"] = df["band_gene_count"].replace(0, np.nan)
        df.dropna(subset=["band", "band_nt_size", "band_gene_count", "fc", "fdr", "tpm", "immune_corr"], inplace=True)
        df.reset_index(drop=True, inplace=True)
        patients[label] = df

    return patients

# --------------------------- analysis helpers ----------------------

_cyto_num_re = re.compile(r"([pqPQ])\s*([0-9]+(?:\.[0-9]+)?)")

def cyto_sort_key(cyto: str) -> Tuple[int, float]:
    m = _cyto_num_re.match(cyto)
    if not m:
        arm = 'p' if ('p' in cyto.lower()) else ('q' if 'q' in cyto.lower() else 'p')
        num = 9999.0
    else:
        arm, num = m.group(1).lower(), float(m.group(2))
    return (0 if arm == 'p' else 1, num)

def split_arm_mask(bands: pd.Series) -> Tuple[np.ndarray, np.ndarray]:
    low = bands.str.lower()
    is_p = low.str.startswith('p')
    is_q = low.str.startswith('q')
    return is_p.values, is_q.values

def _range_mask(val: pd.Series, vmin: float, vmax: float, absolute: bool=False, eps: float = EPS) -> pd.Series:
    if absolute:
        val = np.abs(val)
    return (val >= vmin - eps) & (val <= vmax + eps)

def compute_band_summary(
    df_all: pd.DataFrame, chr_name: str,
    fc_min: float, fc_max: float,
    fdr_min_pct: float, fdr_max_pct: float,
    tpm_min: float, tpm_max: float,
    corr_min: float, corr_max: float,
    center_mode: str = "genome",
    invert: bool = False,
    selected_types: Optional[Set[str]] = None,
    fc_sign_mode: str = "none",  # "none" | "exclude_neg" | "exclude_pos"
) -> Tuple[pd.DataFrame, int, int, float, float]:
    """
    Compute per-band summary for a chromosome, including ratio-centering
    with a selectable baseline (genome/chrom/none). If the chosen scope
    (genome or chromosome) is monochrome (all up or all down), we do NOT
    subtract that baseline (baseline→0) to avoid washing colors to white.
    Returns:
        (out_df, total_deg_genome, total_deg_chr, ratio_genome, ratio_chrom)
    """
    if df_all is None or df_all.empty:
        return (pd.DataFrame(), 0, 0, 0.0, 0.0)

    # All rows for this chromosome (for layout/union of bands)
    df_chr_all = df_all[df_all["chr"] == chr_name].copy()
    if df_chr_all.empty:
        return (pd.DataFrame(), 0, 0, 0.0, 0.0)

    # Unique band list with provided sizes/counts (for ordering and density)
    uniq = (
        df_chr_all.sort_values(["band"], key=lambda s: s.map(cyto_sort_key))
                  .drop_duplicates("band")[["band", "band_nt_size", "band_gene_count"]]
    )

    # Optionally restrict *counts* to selected gene types
    if selected_types is not None and "gene_type" in df_all.columns:
        df_count_all = df_all[df_all["gene_type"].isin(list(selected_types))].copy()
    else:
        df_count_all = df_all.copy()

    if df_count_all.empty:
        out = uniq.copy()
        out["n_deg"] = out["n_up"] = out["n_down"] = 0
        out["ratio_raw"] = 0.0
        out["density"]   = 0.0
        out["ratio_centered"] = 0.0
        out["intensity_raw"]  = 0.0
        return (
            out.sort_values(by="band", key=lambda s: s.map(cyto_sort_key)).reset_index(drop=True),
            0, 0, 0.0, 0.0
        )

    # ---------- Build genome-wide pass mask (or its inverse when invert=True)
    abs_fc_all = np.abs(df_count_all["fc"])
    deg_core_all = abs_fc_all >= 1.0 - EPS

    fc_ok_all   = _range_mask(df_count_all["fc"], fc_min, fc_max, absolute=True)
    fdr_ok_all  = _range_mask(df_count_all["fdr"], fdr_min_pct, fdr_max_pct, absolute=False)
    tpm_ok_all  = _range_mask(df_count_all["tpm"], tpm_min, tpm_max, absolute=False)
    corr_ok_all = _range_mask(df_count_all["immune_corr"], corr_min, corr_max, absolute=True)

    # FC sign filter
    fc_vals_all = pd.to_numeric(df_count_all["fc"], errors="coerce")
    if fc_sign_mode == "exclude_neg":
        sign_ok_all = fc_vals_all > 0
    elif fc_sign_mode == "exclude_pos":
        sign_ok_all = fc_vals_all < 0
    else:
        sign_ok_all = pd.Series(True, index=df_count_all.index)
    sign_ok_all = sign_ok_all.fillna(False)

    selected_all = deg_core_all & fc_ok_all & fdr_ok_all & tpm_ok_all & corr_ok_all & sign_ok_all
    if invert:
        # "Show excluded": keep only core DEGs that fail at least one filter/sign
        mask_all = deg_core_all & (~(fc_ok_all & fdr_ok_all & tpm_ok_all & corr_ok_all & sign_ok_all))
    else:
        mask_all = selected_all

    # ---------- Genome-level counts / baseline
    total_deg_genome = int(mask_all.sum())
    is_up_all   = mask_all & (df_count_all["fc"] >= +1.0 - EPS)
    is_down_all = mask_all & (df_count_all["fc"] <= -1.0 + EPS)
    up_all, down_all = int(is_up_all.sum()), int(is_down_all.sum())
    ratio_genome = (up_all - down_all) / total_deg_genome if total_deg_genome > 0 else 0.0

    # ---------- Chromosome subset (for per-band metrics and chrom baseline)
    df_chr_count = df_count_all[df_count_all["chr"] == chr_name].copy()
    if df_chr_count.empty:
        out = uniq.copy()
        out["n_deg"] = out["n_up"] = out["n_down"] = 0
        out["ratio_raw"] = 0.0
        out["density"]   = 0.0
        # Baseline (if genome centering and genome is mono, we'll zero below; here chrom is empty)
        out["ratio_centered"] = -ratio_genome if center_mode == "genome" else 0.0
        out["intensity_raw"]  = 0.0
        return (
            out.sort_values(by="band", key=lambda s: s.map(cyto_sort_key)).reset_index(drop=True),
            total_deg_genome, 0, ratio_genome, 0.0
        )

    idx_chr = df_chr_count.index
    mask_chr = mask_all.loc[idx_chr]  # align by index
    total_deg_chr = int(mask_chr.sum())
    is_up_chr   = mask_chr & (df_chr_count["fc"] >= +1.0 - EPS)
    is_down_chr = mask_chr & (df_chr_count["fc"] <= -1.0 + EPS)
    up_chr, down_chr = int(is_up_chr.sum()), int(is_down_chr.sum())
    ratio_chrom = (up_chr - down_chr) / total_deg_chr if total_deg_chr > 0 else 0.0

    # Attach flags to the chr DF for band aggregations
    df_chr_count = df_chr_count.assign(_is_deg=mask_chr, _is_up=is_up_chr, _is_down=is_down_chr)

    # Per-band counts
    agg = (
        df_chr_count.groupby("band", as_index=False)
                    .agg(n_deg=("_is_deg", "sum"),
                         n_up=("_is_up", "sum"),
                         n_down=("_is_down", "sum"))
    )

    # Per-band median FDR/TPM among passing genes only
    med = (
        df_chr_count[df_chr_count["_is_deg"]]
            .groupby("band", as_index=False)
            .agg(med_fdr=("fdr", "median"),
                 med_tpm=("tpm", "median"))
    )

    out = (
        uniq.merge(agg, on="band", how="left")
            .merge(med, on="band", how="left")
    ).fillna({"n_deg": 0, "n_up": 0, "n_down": 0})

    out["n_deg"]  = out["n_deg"].astype(int)
    out["n_up"]   = out["n_up"].astype(int)
    out["n_down"] = out["n_down"].astype(int)

    # Raw ratio and density
    out["ratio_raw"] = np.where(out["n_deg"] > 0, (out["n_up"] - out["n_down"]) / out["n_deg"], 0.0)
    out["density"]   = np.clip(
        np.where(out["band_gene_count"] > 0,
                 out["n_deg"] / out["band_gene_count"], 0.0),
        0.0, 1.0
    )

    # ---------- Baseline selection with monochrome fallback
    chrom_is_mono  = (total_deg_chr > 0) and (up_chr == 0 or down_chr == 0)
    genome_is_mono = (total_deg_genome > 0) and (up_all == 0 or down_all == 0)

    if center_mode == "genome":
        baseline = 0.0 if genome_is_mono else ratio_genome
    elif center_mode == "chrom":
        baseline = 0.0 if chrom_is_mono else ratio_chrom
    else:
        baseline = 0.0

    out["ratio_centered"] = out["ratio_raw"] - baseline
    out["intensity_raw"]  = np.sqrt(np.abs(out["ratio_centered"])) * np.sqrt(out["density"])

    # Stable band ordering
    out = out.sort_values(by="band", key=lambda s: s.map(cyto_sort_key)).reset_index(drop=True)

    return out, total_deg_genome, total_deg_chr, ratio_genome, ratio_chrom


# ------------------------------- GUI --------------------------------

class ScrolledFrame(ttk.Frame):
    def __init__(self, parent, width=LEFT_MIN_WIDTH, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0, width=width)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")

        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>", self._on_frame_configure)
        self.win_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self._bind_mousewheel(self.canvas)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    def _on_frame_configure(self, _evt=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        bbox = self.canvas.bbox(self.win_id)
        if bbox:
            self.canvas.itemconfig(self.win_id, width=self.canvas.winfo_width())

    def _bind_mousewheel(self, widget):
        widget.bind("<Enter>", lambda e: widget.bind_all("<MouseWheel>", self._on_mousewheel))
        widget.bind("<Leave>", lambda e: widget.unbind_all("<MouseWheel>"))
        widget.bind_all("<Button-4>", self._on_mousewheel)
        widget.bind_all("<Button-5>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        if event.num == 4:
            self.canvas.yview_scroll(-3, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(3, "units")
        else:
            delta = int(-1*(event.delta/120))
            self.canvas.yview_scroll(delta*3, "units")

class CytobandDEApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cytoband DEG Explorer — 24 panels (multi-patient — NEW FORMAT)")
        self.geometry("1620x920")
        self.minsize(1280, 720)

        # Data
        self.patient_dfs: "OrderedDict[str, pd.DataFrame]" = OrderedDict()
        self.df: Optional[pd.DataFrame] = None
        self.current_patient = tk.StringVar(value="")

        # Panel state
        self.chr_vars = [tk.StringVar(value="empty") for _ in range(PANELS)]
        self.band_layouts: List[List[Tuple[str, float, float]]] = [[] for _ in range(PANELS)]
        self._chr_combos: List[ttk.Combobox] = []

        # Per-panel gene segment geometry for clicks
        self._gene_segments: List[List[dict]] = [[] for _ in range(PANELS)]

        # Gene type UI state
        self.gene_type_vars: Dict[str, tk.BooleanVar] = {}
        self.gene_type_frame: Optional[ttk.LabelFrame] = None

        # Settings / filters
        self.scale_mode = tk.StringVar(value="genes")
        self.center_mode = tk.StringVar(value="genome")  # genome|chrom|none
        self.fdr_mode = tk.StringVar(value="linear")

        # Rendering mode: 'band' or 'segments'
        self.render_mode = tk.StringVar(value="band")

        # Show excluded toggle (band mode only)
        self.show_excluded = tk.BooleanVar(value=False)
        self.toggle_btn_text = tk.StringVar(value="Show Excluded")

        # Toggle DEG labels (segments mode)
        self.show_deg_labels = tk.BooleanVar(value=False)
        self._deg_btn_text = tk.StringVar(value="Show DEG gene names")

        # NEW: Intensity by |FC| toggle (segments mode)
        self.segments_intensity_by_fc = tk.BooleanVar(value=False)
        self._intensity_btn_text = tk.StringVar(value="Intensity by |FC|: OFF")
        # Robust scaling quantiles (percent)
        self._inten_q_lo = 5.0
        self._inten_q_hi = 95.0
        # NEW: Unified vs Separate scaling for segments intensity
        self.segments_intensity_scale = tk.StringVar(value="separate")  # 'separate' | 'unified'

        # Filters
        self.fc_min = tk.DoubleVar(value=1.1)
        self.fc_max = tk.DoubleVar(value=10.0)
        self.fdr_min_lin = tk.DoubleVar(value=0.00)
        self.fdr_max_lin = tk.DoubleVar(value=10.00)
        self.fdr_log_Lmax = tk.DoubleVar(value=-2.0)
        self.tpm_min = tk.DoubleVar(value=0.0)
        self.tpm_max = tk.DoubleVar(value=100.0)
        self.corr_min = tk.DoubleVar(value=0.0)
        self.corr_max = tk.DoubleVar(value=1.0)

        # Band emphasis
        self.banddeg_min = tk.DoubleVar(value=0.0)
        self.banddeg_max = tk.DoubleVar(value=100.0)
        self._banddeg_domain_max = 100

        # Width slider
        self.bar_width = tk.DoubleVar(value=DEFAULT_BAR_WIDTH)

        # Axes layout
        self.ax_for_panel: List[Optional[plt.Axes]] = [None] * PANELS
        self.primary_index_for_axis: Dict[plt.Axes, int] = {}
        self.ax_unique: List[plt.Axes] = []
        self._span_cols: Set[int] = set()
        self._visible_cols: List[int] = list(range(12))

        # Domains
        self._fc_dom_max = 10.0
        self._tpm_dom_max_base = 100.0
        self._tpm_dom_max_active = 100.0

        # UI readouts
        self.selection_summary_var = tk.StringVar(value="—")
        self.counts_var = tk.StringVar(value="—")
        self.processing_var = tk.StringVar(value="")  # shows "Processing update…" during redraws

        # FC sign filter
        self.fc_sign_mode = tk.StringVar(value="none")  # "none" | "exclude_neg" | "exclude_pos"
        self._fcsign_btns: Dict[str, tk.Button] = {}  # name -> button widget

        # LIVE / MANUAL update
        self.live_mode = tk.StringVar(value="live")
        self._needs_update = False

        self._build_layout()

    # ------------------------ color helpers ------------------------

    @staticmethod
    def _lerp_color(c0: Tuple[float,float,float], c1: Tuple[float,float,float], t: float) -> Tuple[float,float,float,float]:
        t = float(np.clip(t, 0.0, 1.0))
        a = np.array(c0); b = np.array(c1)
        rgb = a*(1.0 - t) + b*t
        return (float(rgb[0]), float(rgb[1]), float(rgb[2]), 1.0)

    @staticmethod
    def _gamma(t: float, g: float) -> float:
        t = float(np.clip(t, 0.0, 1.0))
        if g is None or g == 1.0:
            return t
        if g <= 0:
            return t
        return float(t ** g)

    # ------------------------ gene types helpers ------------------------

    def _selected_gene_types(self) -> Optional[Set[str]]:
        if self.df is None or "gene_type" not in self.df.columns or not self.gene_type_vars:
            return None
        chosen = {t for t, var in self.gene_type_vars.items() if var.get()}
        return chosen

    def _build_gene_type_ui(self, parent):
        if self.gene_type_frame is not None:
            try: self.gene_type_frame.destroy()
            except: pass
            self.gene_type_frame = None
            self.gene_type_vars.clear()

        if self.df is None or "gene_type" not in self.df.columns:
            return

        types = sorted(str(x) for x in self.df["gene_type"].dropna().astype(str).unique())
        self.gene_type_frame = ttk.LabelFrame(parent, text="Gene types")
        self.gene_type_frame.grid(row=2, column=0, sticky="ew", pady=PAD_S)
        self.gene_type_frame.columnconfigure(0, weight=1)

        btn_row = ttk.Frame(self.gene_type_frame)
        btn_row.grid(row=0, column=0, sticky="ew", padx=(6,6), pady=(2,2))
        ttk.Button(btn_row, text="All", command=lambda: self._set_all_gene_types(True)).grid(row=0, column=0, padx=(0,6))
        ttk.Button(btn_row, text="None", command=lambda: self._set_all_gene_types(False)).grid(row=0, column=1)

        cols = 2 if len(types) > 6 else 1
        grid = ttk.Frame(self.gene_type_frame)
        grid.grid(row=1, column=0, sticky="ew", padx=(6,6), pady=(2,4))
        for c in range(cols):
            grid.columnconfigure(c, weight=1)

        for i, t in enumerate(types):
            var = tk.BooleanVar(value=True)
            self.gene_type_vars[t] = var
            cb = ttk.Checkbutton(grid, text=t, variable=var, command=self.on_gene_types_changed)
            cb.grid(row=i//cols, column=i%cols, sticky="w", padx=(0,10), pady=(1,1))

    def _set_all_gene_types(self, state: bool):
        for var in self.gene_type_vars.values():
            var.set(state)
        self.on_gene_types_changed()

    def on_gene_types_changed(self):
        self._set_banddeg_domain_for_active_chromosomes()
        self._trigger_update()
        self._update_selection_summary()

    # ------------------------ domain from data ------------------------

    def _refresh_numeric_domains_from_df(self):
        if self.df is None or self.df.empty:
            self._fc_dom_max = 10.0
            self._tpm_dom_max_base = 100.0
            self._tpm_dom_max_active = 100.0
            return

        fc_abs_max = float(np.nanmax(np.abs(self.df["fc"]))) if "fc" in self.df else 10.0
        if not np.isfinite(fc_abs_max) or fc_abs_max < 1.0:
            fc_abs_max = 1.0
        self._fc_dom_max = fc_abs_max

        tpm_max = float(np.nanmax(self.df["tpm"])) if "tpm" in self.df else 100.0
        if not np.isfinite(tpm_max) or tpm_max <= 0.0:
            tpm_max = 1.0
        self._tpm_dom_max_base = tpm_max
        self._tpm_dom_max_active = tpm_max

        smin_fc, smax_fc, *_ = self._fc_widgets
        smin_fc.configure(from_=1.0, to=self._fc_dom_max)
        smax_fc.configure(from_=1.0, to=self._fc_dom_max)

    def _active_chromosomes(self) -> List[str]:
        return sorted({v.get() for v in self.chr_vars if v.get() and v.get() != "empty"})

    def _active_scope_mask(self) -> np.ndarray:
        if self.df is None or self.df.empty:
            return np.zeros(0, dtype=bool)
        active_chrs = self._active_chromosomes()
        chr_mask = self.df["chr"].isin(active_chrs).values if active_chrs else np.ones(len(self.df), dtype=bool)
        sel_types = self._selected_gene_types()
        if sel_types is None:
            type_mask = np.ones(len(self.df), dtype=bool)
        else:
            type_mask = self.df["gene_type"].isin(list(sel_types)).values if len(sel_types) else np.zeros(len(self.df), dtype=bool)
        return chr_mask & type_mask

    def _compute_active_tpm_max(self) -> float:
        if self.df is None or self.df.empty:
            return 100.0
        scope = self._active_scope_mask()
        sub = self.df.loc[scope]
        if sub.empty:
            return float(np.nanmax(self.df["tpm"]))
        val = float(np.nanmax(sub["tpm"]))
        return val if np.isfinite(val) and val > 0 else 1.0

    def _apply_active_tpm_domain(self, set_value: bool = False):
        self._tpm_dom_max_active = self._compute_active_tpm_max()
        smin_tpm, smax_tpm, *_ = self._tpm_widgets
        smin_tpm.configure(from_=0.0, to=100.0)
        smax_tpm.configure(from_=0.0, to=self._tpm_dom_max_active)
        if set_value:
            self.tpm_max.set(self._tpm_dom_max_active)
        else:
            if float(self.tpm_max.get()) > self._tpm_dom_max_active:
                self.tpm_max.set(self._tpm_dom_max_active)

    # ----------------------------- layout -----------------------------

    def _build_layout(self):
        self.columnconfigure(0, weight=0, minsize=LEFT_MIN_WIDTH)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # ---------- LEFT: Scrollable Controls ----------
        left_scroller = ScrolledFrame(self, width=LEFT_MIN_WIDTH)
        left_scroller.grid(row=0, column=0, sticky="nsw")
        left = left_scroller.inner
        left.columnconfigure(0, weight=1)

        # Header
        header = ttk.LabelFrame(left, text="Data / Patient")
        header.grid(row=0, column=0, sticky="ew", pady=PAD_S)
        header.columnconfigure(1, weight=1)

        self.file_var = tk.StringVar(value="No file")
        ttk.Label(header, text="File").grid(row=0, column=0, sticky="e", padx=(6,4))
        ttk.Label(header, textvariable=self.file_var, width=24).grid(row=0, column=1, sticky="w")

        ttk.Label(header, text="Patient").grid(row=0, column=2, sticky="e", padx=(8,4))
        self.patient_cb = ttk.Combobox(header, textvariable=self.current_patient, state="disabled", width=16)
        self.patient_cb.grid(row=0, column=3, padx=(4,4), pady=2, sticky="w")
        self.patient_cb.bind("<<ComboboxSelected>>", self.on_patient_changed)

        ttk.Button(header, text="Browse…", command=self.on_browse).grid(row=0, column=4, padx=(6,6))

        # Chromosome selectors (4×6)
        self.chr_frame = ttk.LabelFrame(left, text="Chromosomes (24 panels)")
        self.chr_frame.grid(row=1, column=0, sticky="ew", pady=PAD_S)
        for c in range(8):
            self.chr_frame.columnconfigure(c, weight=1)

        rows_per_col = 6
        for i in range(PANELS):
            col_block = i // rows_per_col
            row_in_block = i % rows_per_col
            base_col = col_block * 2

            ttk.Label(self.chr_frame, text=f"P{i+1:>2}:").grid(
                row=row_in_block, column=base_col, padx=(6,2), pady=(1,1), sticky="e"
            )
            cb = ttk.Combobox(self.chr_frame, textvariable=self.chr_vars[i], state="disabled", width=14)
            cb.grid(row=row_in_block, column=base_col+1, padx=(2,8), pady=(1,1), sticky="w")
            cb.bind("<<ComboboxSelected>>", self.on_chr_changed)
            self._chr_combos.append(cb)

        af_container = ttk.Frame(self.chr_frame)
        af_container.grid(row=rows_per_col, column=0, columnspan=8, sticky="ew", pady=(3,2), padx=(6,6))
        af_container.columnconfigure(2, weight=1)
        ttk.Button(af_container, text="Autofill all", command=self.on_autofill).grid(row=0, column=0, sticky="w")
        ttk.Button(af_container, text="Autofill top 12", command=self.on_autofill_top12).grid(row=0, column=1, sticky="w", padx=(6,0))
        ttk.Label(af_container, text="Order").grid(row=0, column=2, sticky="e", padx=(10,4))
        self.autofill_order = tk.StringVar(value="A→Z")
        order_cb = ttk.Combobox(af_container, values=["A→Z", "Natural"], width=8, state="readonly",
                                textvariable=self.autofill_order)
        order_cb.grid(row=0, column=3, sticky="w")
        ttk.Button(af_container, text="Clear", command=self.on_clear_panels).grid(row=0, column=4, sticky="w", padx=(8,0))

        # Gene types (populated after loading)
        self.gene_type_frame = ttk.LabelFrame(left, text="Gene types")
        self.gene_type_frame.grid(row=2, column=0, sticky="ew", pady=PAD_S)
        ttk.Label(self.gene_type_frame, text="(load data to populate)").grid(row=0, column=0, padx=6, pady=4, sticky="w")

        # DEG filters
        thr = ttk.LabelFrame(left, text="DEG filters")
        thr.grid(row=3, column=0, sticky="ew", pady=PAD_S)
        thr.columnconfigure(1, weight=1)

        def add_range_row(row, label, vmin_var, vmax_var, from_, to_, cb_on_change):
            ttk.Label(thr, text=label).grid(row=row, column=0, sticky="w", padx=(6,4))
            frame = ttk.Frame(thr)
            frame.grid(row=row, column=1, sticky="ew", padx=(4,6))
            frame.columnconfigure(0, weight=1)
            frame.columnconfigure(1, weight=1)

            smin = ttk.Scale(frame, from_=from_, to=to_, variable=vmin_var,
                             command=lambda _v: cb_on_change())
            smax = ttk.Scale(frame, from_=from_, to=to_, variable=vmax_var,
                             command=lambda _v: cb_on_change())
            smin.grid(row=0, column=0, sticky="ew", padx=(0,2))
            smax.grid(row=0, column=1, sticky="ew", padx=(2,0))

            emin = ttk.Entry(frame, textvariable=vmin_var, width=8, justify="center")
            emax = ttk.Entry(frame, textvariable=vmax_var, width=8, justify="center")
            emin.grid(row=1, column=0, pady=(1,0))
            emax.grid(row=1, column=1, pady=(1,0))
            for w in (emin, emax):
                w.bind("<Return>", lambda e: cb_on_change())
                w.bind("<FocusOut>", lambda e: cb_on_change())

            return smin, smax, emin, emax

        self._fc_widgets = add_range_row(
            0, "|FC| (abs) range", self.fc_min, self.fc_max,
            from_=1.0, to_=10.0, cb_on_change=self._on_range_change
        )

        fdr_mode = ttk.LabelFrame(thr, text="FDR mode")
        fdr_mode.grid(row=2, column=0, columnspan=2, sticky="ew", padx=(6,6), pady=(2,2))
        ttk.Radiobutton(fdr_mode, text="Percent", value="linear",
                        variable=self.fdr_mode, command=self._on_fdr_mode_toggle).grid(row=0, column=0, sticky="w", padx=4, pady=1)
        ttk.Radiobutton(fdr_mode, text="Log MAX (L −100..0)", value="logmax",
                        variable=self.fdr_mode, command=self._on_fdr_mode_toggle).grid(row=0, column=1, sticky="w", padx=8, pady=1)

        fdr_lin = ttk.LabelFrame(thr, text="FDR %")
        fdr_lin.grid(row=3, column=0, columnspan=2, sticky="ew", padx=(6,6), pady=(0,2))
        fdr_lin.columnconfigure(0, weight=1); fdr_lin.columnconfigure(1, weight=1)
        self._fdr_lin_frame = fdr_lin

        self.fdr_smin = ttk.Scale(fdr_lin, from_=0.0, to=100.0, variable=self.fdr_min_lin,
                                  command=lambda _v: self._on_fdr_lin_change())
        self.fdr_smax = ttk.Scale(fdr_lin, from_=0.0, to=100.0, variable=self.fdr_max_lin,
                                  command=lambda _v: self._on_fdr_lin_change())
        self.fdr_smin.grid(row=0, column=0, sticky="ew", padx=(0,2))
        self.fdr_smax.grid(row=0, column=1, sticky="ew", padx=(2,0))

        row2 = ttk.Frame(fdr_lin); row2.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(1,0))
        ttk.Label(row2, text="min%").grid(row=0, column=0, sticky="e", padx=(0,4))
        self.fdr_emin = ttk.Entry(row2, textvariable=self.fdr_min_lin, width=8, justify="center")
        self.fdr_emin.grid(row=0, column=1, sticky="w")
        ttk.Label(row2, text="max%").grid(row=0, column=2, sticky="e", padx=(8,4))
        self.fdr_emax = ttk.Entry(row2, textvariable=self.fdr_max_lin, width=8, justify="center")
        self.fdr_emax.grid(row=0, column=3, sticky="w")
        for w in (self.fdr_emin, self.fdr_emax):
            w.bind("<Return>", lambda e: self._on_fdr_lin_entry())
            w.bind("<FocusOut>", lambda e: self._on_fdr_lin_entry())

        fdr_log = ttk.LabelFrame(thr, text="FDR log MAX")
        fdr_log.grid(row=4, column=0, columnspan=2, sticky="ew", padx=(6,6), pady=(2,2))
        fdr_log.columnconfigure(0, weight=1)
        self._fdr_log_frame = fdr_log

        self.fdr_log_scale = ttk.Scale(fdr_log, from_=-100, to=0, variable=self.fdr_log_Lmax,
                                       command=lambda _v: self._on_fdr_log_change())
        self.fdr_log_scale.grid(row=0, column=0, sticky="ew", padx=(0,0))
        self.fdr_log_label = ttk.Label(fdr_log, text="")
        self.fdr_log_label.grid(row=1, column=0, sticky="w", pady=(1,0))

        # TPM sliders
        self._tpm_widgets = add_range_row(
            6, "TPM range", self.tpm_min, self.tpm_max,
            from_=0.0, to_=100.0, cb_on_change=self._on_range_change
        )

        # immun |cor|
        self._corr_widgets = add_range_row(
            8, "immun |cor|", self.corr_min, self.corr_max,
            from_=0.0, to_=1.0, cb_on_change=self._on_range_change
        )

        # FC SIGN FILTER buttons
        sign_frame = ttk.LabelFrame(thr, text="FC sign filter")
        sign_frame.grid(row=9, column=0, columnspan=2, sticky="ew", padx=(6,6), pady=(4,2))
        def mk_btn(parent, text, mode, col):
            b = tk.Button(parent, text=text, width=14,
                          command=lambda m=mode: self._set_fc_sign_mode(m))
            b.grid(row=0, column=col, padx=(0 if col==0 else 6, 0), pady=(2,2), sticky="w")
            self._fcsign_btns[mode] = b
        mk_btn(sign_frame, "Only Positif", "exclude_neg", 0)
        mk_btn(sign_frame, "Only Negatif", "exclude_pos", 1)
        mk_btn(sign_frame, "All Genes", "none",        2)
        self._refresh_fcsign_buttons()

        # Side-by-side: scaling + centering
        side_row = ttk.Frame(left)
        side_row.grid(row=4, column=0, sticky="ew", pady=PAD_S)
        side_row.columnconfigure(0, weight=1)
        side_row.columnconfigure(1, weight=1)

        scale_frame = ttk.LabelFrame(side_row, text="Cytoband height")
        scale_frame.grid(row=0, column=0, sticky="ew", padx=(0,3))
        ttk.Radiobutton(scale_frame, text="By gene count", value="genes",
                        variable=self.scale_mode, command=self._on_simple_change).grid(row=0, column=0, sticky="w", padx=6, pady=1)
        ttk.Radiobutton(scale_frame, text="By nucleotides", value="nt",
                        variable=self.scale_mode, command=self._on_simple_change).grid(row=1, column=0, sticky="w", padx=6, pady=1)

        center_frame = ttk.LabelFrame(side_row, text="Color baseline (both modes)")
        center_frame.grid(row=0, column=1, sticky="ew", padx=(3,0))
        ttk.Radiobutton(center_frame, text="GENOME", value="genome",
                        variable=self.center_mode, command=self._on_simple_change).grid(row=0, column=0, sticky="w", padx=6, pady=1)
        ttk.Radiobutton(center_frame, text="CHROM", value="chrom",
                        variable=self.center_mode, command=self._on_simple_change).grid(row=1, column=0, sticky="w", padx=6, pady=1)
        ttk.Radiobutton(center_frame, text="None", value="none",
                        variable=self.center_mode, command=self._on_simple_change).grid(row=2, column=0, sticky="w", padx=6, pady=1)

        # Rendering mode
        render_frame = ttk.LabelFrame(left, text="Rendering mode")
        render_frame.grid(row=5, column=0, sticky="ew", pady=PAD_S)
        ttk.Radiobutton(render_frame, text="Band ratio (original)", value="band",
                        variable=self.render_mode, command=self._on_simple_change).grid(row=0, column=0, sticky="w", padx=6, pady=1)
        ttk.Radiobutton(render_frame, text="Per-gene segments (red/blue/gray)", value="segments",
                        variable=self.render_mode, command=self._on_simple_change).grid(row=1, column=0, sticky="w", padx=6, pady=1)

        self.deg_btn = ttk.Button(render_frame, textvariable=self._deg_btn_text, command=self._toggle_deg_labels)
        self.deg_btn.grid(row=2, column=0, sticky="w", padx=6, pady=(4,3))

        # Intensity by |FC| button (segments mode)
        self.intensity_btn = ttk.Button(render_frame, textvariable=self._intensity_btn_text, command=self._toggle_intensity_by_fc)
        self.intensity_btn.grid(row=3, column=0, sticky="w", padx=6, pady=(0,6))

        # Unified vs Separate intensity scale (segments)
        inten_scale = ttk.LabelFrame(left, text="Segments intensity scale")
        inten_scale.grid(row=6, column=0, sticky="ew", pady=PAD_S)
        ttk.Radiobutton(inten_scale, text="Separate (per sign)", value="separate",
                        variable=self.segments_intensity_scale, command=self._on_simple_change).grid(row=0, column=0, sticky="w", padx=6, pady=1)
        ttk.Radiobutton(inten_scale, text="Unified (red+blue same scale)", value="unified",
                        variable=self.segments_intensity_scale, command=self._on_simple_change).grid(row=1, column=0, sticky="w", padx=6, pady=1)

        # Band #DEG emphasis
        banddeg = ttk.LabelFrame(left, text="Band #DEG emphasis")
        banddeg.grid(row=7, column=0, sticky="ew", pady=PAD_S)
        banddeg.columnconfigure(0, weight=1); banddeg.columnconfigure(1, weight=1)

        ttk.Label(banddeg, text="Min").grid(row=0, column=0, sticky="w", padx=(6,4))
        ttk.Label(banddeg, text="Max").grid(row=0, column=1, sticky="w", padx=(6,4))

        self.banddeg_smin = ttk.Scale(banddeg, from_=0.0, to=float(self._banddeg_domain_max), variable=self.banddeg_min,
                                      command=lambda _v: self._on_banddeg_change())
        self.banddeg_smax = ttk.Scale(banddeg, from_=0.0, to=float(self._banddeg_domain_max), variable=self.banddeg_max,
                                      command=lambda _v: self._on_banddeg_change())
        self.banddeg_smin.grid(row=1, column=0, sticky="ew", padx=(6,6))
        self.banddeg_smax.grid(row=1, column=1, sticky="ew", padx=(6,6))

        self.banddeg_emin = ttk.Entry(banddeg, textvariable=self.banddeg_min, width=8, justify="center")
        self.banddeg_emax = ttk.Entry(banddeg, textvariable=self.banddeg_max, width=8, justify="center")
        self.banddeg_emin.grid(row=2, column=0, pady=(2,0))
        self.banddeg_emax.grid(row=2, column=1, pady=(2,0))
        for w in (self.banddeg_emin, self.banddeg_emax):
            w.bind("<Return>", lambda e: self._on_banddeg_entry_change())
            w.bind("<FocusOut>", lambda e: self._on_banddeg_entry_change())

        # Cytoband width
        ws_frame = ttk.LabelFrame(left, text="Widths")
        ws_frame.grid(row=8, column=0, sticky="ew", pady=PAD_S)
        ws_frame.columnconfigure(0, weight=1)
        ttk.Label(ws_frame, text="Cytoband width").grid(row=0, column=0, sticky="w", padx=(6,6))
        ttk.Scale(ws_frame, from_=0.005, to=0.30, variable=self.bar_width,
                  command=lambda _v: self._on_simple_change()).grid(row=1, column=0, sticky="ew", padx=(6,6))

        # Reset + toggle + LIVE/MANUAL
        btns = ttk.Frame(left)
        btns.grid(row=9, column=0, sticky="ew", pady=PAD_S)
        btns.columnconfigure(4, weight=1)
        ttk.Button(btns, text="Reset", command=self.on_reset).grid(row=0, column=0, padx=(0,6))

        self.toggle_btn = tk.Button(
            btns,
            textvariable=self.toggle_btn_text,
            command=self.on_toggle_show_mode,
            relief="raised"
        )
        self.toggle_btn.grid(row=0, column=1, padx=(0,6))

        # LIVE / MANUAL block
        live_box = ttk.LabelFrame(left, text="Update mode")
        live_box.grid(row=10, column=0, sticky="ew", pady=PAD_S)
        ttk.Radiobutton(live_box, text="LIVE", value="live", variable=self.live_mode,
                        command=self._on_live_mode_change).grid(row=0, column=0, padx=6, pady=(4,2), sticky="w")
        ttk.Radiobutton(live_box, text="MANUAL", value="manual", variable=self.live_mode,
                        command=self._on_live_mode_change).grid(row=0, column=1, padx=6, pady=(4,2), sticky="w")
        ttk.Button(live_box, text="Update", command=self._do_update).grid(row=0, column=2, padx=6, pady=(4,2))
        ttk.Label(live_box, textvariable=self.processing_var, foreground="#a33").grid(row=0, column=3, padx=6, pady=(4,2), sticky="w")

        ttk.Label(left, textvariable=self.counts_var, foreground="#444", justify="left",
                  wraplength=LEFT_WRAP).grid(row=11, column=0, sticky="w", pady=(2,2))

        # Selection Summary
        sel_frame = ttk.LabelFrame(left, text="Selection Summary")
        sel_frame.grid(row=12, column=0, sticky="ew", pady=(2,8))
        ttk.Label(sel_frame, textvariable=self.selection_summary_var, justify="left", anchor="w",
                  foreground="#222", wraplength=LEFT_WRAP).grid(row=0, column=0, sticky="w", padx=6, pady=4)

        # ---------- RIGHT: Figure ----------
        right = ttk.Frame(self, padding=(4, 4))
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=1); right.columnconfigure(0, weight=1)

        self.fig = plt.figure(figsize=(28.0, 9.0), dpi=100, constrained_layout=True)
        self.fig.set_constrained_layout_pads(w_pad=0.01, h_pad=0.01, wspace=DEFAULT_WSPACE, hspace=0.01)

        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.draw()
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self.cid = self.canvas.mpl_connect("button_press_event", self.on_click_plot)

        # Initial layout
        self._visible_cols = []
        self._build_axes_layout(self._visible_cols, span_cols=set())

        for ax in self.ax_unique:
            ax.axis("off")
        if not self.ax_unique:
            ax = self.fig.add_subplot(111)
            self.ax_unique.append(ax)
        self.ax_unique[0].text(0.5, 0.5, "No panels (all columns hidden)", ha="center", va="center",
                               transform=self.ax_unique[0].transAxes, fontsize=12)
        self.canvas.draw_idle()

        self._refresh_fdr_ui_state()
        self._refresh_fdr_log_label()
        self._refresh_segments_ui_state()

    # --------------------------- LIVE/MANUAL helpers --------------------------

    def _on_live_mode_change(self):
        if self.live_mode.get() == "live" and self._needs_update:
            self._do_update()

    def _trigger_update(self):
        if self.live_mode.get() == "live":
            self._do_update()
        else:
            self._needs_update = True

    def _do_update(self):
        self.processing_var.set("Processing update…")
        try:
            self.update_idletasks()
        except Exception:
            pass
        self.update_plot()
        self.processing_var.set("")
        self._needs_update = False

    # --------------------------- events & syncing -----------------------------

    def on_browse(self):
        path = filedialog.askopenfilename(
            title="Select gene results file",
            filetypes=[
                ("Text/CSV", "*.txt *.tsv *.csv *.tabtxt"),
                ("Excel", "*.xlsx *.xls"),
                ("All files", "*.*"),
            ]
        )
        if not path:
            return
        try:
            self.patient_dfs = read_multi_patient_newformat(path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read file (new format):\n{e}")
            return
        if not self.patient_dfs:
            messagebox.showwarning("Empty", "No patient triplets detected.")
            return

        self.file_var.set(os.path.basename(path))

        labels = list(self.patient_dfs.keys())
        self.patient_cb.configure(state="readonly", values=labels)
        self.current_patient.set(labels[0])
        self.df = self.patient_dfs[self.current_patient.get()]

        chrs = sorted(self.df["chr"].astype(str).unique(), key=self._chr_sort_key)
        values = ["empty"] + chrs
        for cb in self._chr_combos:
            cb.configure(state="readonly", values=values)

        for i in range(PANELS):
            self.chr_vars[i].set("empty")

        self._build_gene_type_ui(self.chr_frame.master)

        self._refresh_numeric_domains_from_df()
        self._apply_active_tpm_domain(set_value=True)
        self._set_banddeg_domain_for_active_chromosomes()
        self.on_reset()

    def on_patient_changed(self, _evt=None):
        label = self.current_patient.get()
        if not label or label not in self.patient_dfs:
            return
        self.df = self.patient_dfs[label]
        chrs = sorted(self.df["chr"].astype(str).unique(), key=self._chr_sort_key)
        values = ["empty"] + chrs
        for cb in self._chr_combos:
            cb.configure(values=values)

        self._build_gene_type_ui(self.chr_frame.master)

        self._refresh_numeric_domains_from_df()
        self._apply_active_tpm_domain(set_value=True)
        self._set_banddeg_domain_for_active_chromosomes()
        self._trigger_update()
        self._update_selection_summary()

    def _chr_sort_key(self, c):
        try:
            return (0, int(c))
        except:
            order = {"X": 1000, "Y": 1001, "MT": 1002, "M": 1002}
            return (1, order.get(str(c).upper(), 2000))

    def on_chr_changed(self, _evt=None):
        self._apply_active_tpm_domain(set_value=True)
        self._set_banddeg_domain_for_active_chromosomes()
        self._trigger_update()
        self._update_selection_summary()

    # ----------- Autofill / Clear panels -------------------------------------

    def _ordered_chr_list(self):
        chrs = list(self.df["chr"].astype(str).unique())
        if self.autofill_order.get() == "A→Z":
            chrs = sorted(chrs, key=lambda s: s.upper())
        else:
            chrs = sorted(chrs, key=self._chr_sort_key)
        return chrs

    def on_autofill(self):
        if self.df is None:
            return
        chrs = self._ordered_chr_list()
        n = min(len(chrs), PANELS)
        for i in range(PANELS):
            self.chr_vars[i].set(chrs[i] if i < n else "empty")
        self._apply_active_tpm_domain(set_value=True)
        self._set_banddeg_domain_for_active_chromosomes()
        self._trigger_update()
        self._update_selection_summary()

    def on_autofill_top12(self):
        if self.df is None:
            return
        chrs = self._ordered_chr_list()
        n = min(len(chrs), 12)
        for i in range(PANELS):
            if i < 12:
                self.chr_vars[i].set(chrs[i] if i < n else "empty")
            else:
                self.chr_vars[i].set("empty")
        self._apply_active_tpm_domain(set_value=True)
        self._set_banddeg_domain_for_active_chromosomes()
        self._trigger_update()
        self._update_selection_summary()

    def on_clear_panels(self):
        for i in range(PANELS):
            self.chr_vars[i].set("empty")
        self._apply_active_tpm_domain(set_value=True)
        self._set_banddeg_domain_for_active_chromosomes()
        self._trigger_update()
        self._update_selection_summary()

    # ---------------- band-DEG domain recompute ------------------------------

    def _set_banddeg_domain_for_active_chromosomes(self):
        if self.df is None or len(self.df) == 0:
            return

        active_chrs = self._active_chromosomes()
        sel_types = self._selected_gene_types()

        df_used = self.df
        if sel_types is not None:
            if len(sel_types) == 0:
                df_used = self.df.iloc[0:0]
            else:
                df_used = self.df[self.df["gene_type"].isin(list(sel_types))]

        fdr_min_pct, fdr_max_pct = self._current_fdr_range_percent()

        abs_fc = np.abs(df_used["fc"]) if len(df_used) else pd.Series([], dtype=float)
        deg_core = abs_fc >= 1.0 - EPS
        fc_ok   = _range_mask(df_used["fc"], float(self.fc_min.get()), float(self.fc_max.get()), absolute=True) if len(df_used) else pd.Series([], dtype=bool)
        fdr_ok  = _range_mask(df_used["fdr"], fdr_min_pct, fdr_max_pct, absolute=False) if len(df_used) else pd.Series([], dtype=bool)
        tpm_ok  = _range_mask(df_used["tpm"], float(self.tpm_min.get()), float(self.tpm_max.get()), absolute=False) if len(df_used) else pd.Series([], dtype=bool)
        corr_ok = _range_mask(df_used["immune_corr"], float(self.corr_min.get()), float(self.corr_max.get()), absolute=True) if len(df_used) else pd.Series([], dtype=bool)

        # FC sign filter
        if len(df_used):
            fc_vals_used = pd.to_numeric(df_used["fc"], errors="coerce")
            if self.fc_sign_mode.get() == "exclude_neg":
                sign_ok = fc_vals_used > 0
            elif self.fc_sign_mode.get() == "exclude_pos":
                sign_ok = fc_vals_used < 0
            else:
                sign_ok = pd.Series(True, index=df_used.index)
            sign_ok = sign_ok.fillna(False)
        else:
            sign_ok = pd.Series([], dtype=bool)

        selected = deg_core & fc_ok & fdr_ok & tpm_ok & corr_ok & sign_ok
        mask = deg_core & (~(fc_ok & fdr_ok & tpm_ok & corr_ok & sign_ok)) if self.show_excluded.get() else selected

        df_tmp = df_used.loc[:, ["chr", "band"]].copy()
        df_tmp["_is_deg"] = mask.astype(int)

        if not active_chrs:
            gb = df_tmp.groupby(["chr", "band"], as_index=False)["_is_deg"].sum() if len(df_tmp) else pd.DataFrame({"_is_deg":[0]})
        else:
            gb = (df_tmp[df_tmp["chr"].isin(active_chrs)]
                  .groupby(["chr", "band"], as_index=False)["_is_deg"].sum()) if len(df_tmp) else pd.DataFrame({"_is_deg":[0]})

        domain_max = int(gb["_is_deg"].max()) if len(gb) and "_is_deg" in gb else 1
        if domain_max < 1:
            domain_max = 1

        self._banddeg_domain_max = domain_max
        self.banddeg_smin.configure(from_=0.0, to=float(domain_max))
        self.banddeg_smax.configure(from_=0.0, to=float(domain_max))

        current_min = int(round(float(self.banddeg_min.get())))
        if current_min > domain_max:
            current_min = 0
        self.banddeg_min.set(current_min)
        self.banddeg_max.set(float(domain_max))

    # ------------------------------ reset / toggle ----------------------------

    def on_reset(self):
        self.fc_min.set(1.1)
        self.fc_max.set(self._fc_dom_max)
        self.fdr_mode.set("linear")
        self.fdr_min_lin.set(0.00); self.fdr_max_lin.set(10.00)
        self.fdr_log_Lmax.set(-2.0)
        self.tpm_min.set(0.0)
        self._apply_active_tpm_domain(set_value=True)
        self.corr_min.set(0.0); self.corr_max.set(1.0)
        self.scale_mode.set("genes")
        self.center_mode.set("genome")
        self.render_mode.set("band")
        self.bar_width.set(DEFAULT_BAR_WIDTH)
        self.show_excluded.set(False)
        self.toggle_btn_text.set("Show Excluded")
        self.show_deg_labels.set(False)
        self._deg_btn_text.set("Show DEG gene names")
        # FC SIGN
        self.fc_sign_mode.set("none")
        self._refresh_fcsign_buttons()
        # Intensity
        self.segments_intensity_by_fc.set(False)
        self._intensity_btn_text.set("Intensity by |FC|: OFF")
        self.segments_intensity_scale.set("separate")
        # LIVE by default
        self.live_mode.set("live")
        self._needs_update = False

        self._refresh_toggle_button_appearance()

        smin_fc, smax_fc, *_ = self._fc_widgets
        smin_fc.configure(from_=1.0, to=self._fc_dom_max)
        smax_fc.configure(from_=1.0, to=self._fc_dom_max)
        smin_tpm, smax_tpm, *_ = self._tpm_widgets
        smin_tpm.configure(from_=0.0, to=100.0)
        smax_tpm.configure(from_=0.0, to=self._tpm_dom_max_active)

        self._refresh_fdr_ui_state()
        self._refresh_fdr_log_label()
        self._set_banddeg_domain_for_active_chromosomes()
        self._trigger_update()
        self._update_selection_summary()

    def _refresh_toggle_button_appearance(self):
        if self.show_excluded.get():
            self.toggle_btn_text.set("EXCLUDED")
            self.toggle_btn.configure(
                bg="#d9534f", fg="white",
                activebackground="#c9302c", activeforeground="white",
                relief="sunken"
            )
        else:
            self.toggle_btn_text.set("Show Excluded")
            self.toggle_btn.configure(
                bg=self.cget("bg") if isinstance(self, tk.Tk) else "#f0f0f0",
                fg="black",
                activebackground="#e6e6e6", activeforeground="black",
                relief="raised"
            )

    def on_toggle_show_mode(self):
        self.show_excluded.set(not self.show_excluded.get())
        self._refresh_toggle_button_appearance()
        self._set_banddeg_domain_for_active_chromosomes()
        self._trigger_update()
        self._update_selection_summary()

    def _toggle_deg_labels(self):
        self.show_deg_labels.set(not self.show_deg_labels.get())
        self._deg_btn_text.set("Hide DEG gene names" if self.show_deg_labels.get() else "Show DEG gene names")
        self._trigger_update()

    # -------- Intensity helpers & toggle (robust scaling) --------

    def _toggle_intensity_by_fc(self):
        self.segments_intensity_by_fc.set(not self.segments_intensity_by_fc.get())
        self._intensity_btn_text.set("Intensity by |FC|: ON" if self.segments_intensity_by_fc.get()
                                     else "Intensity by |FC|: OFF")
        self._trigger_update()

    def _refresh_segments_ui_state(self):
        seg_mode = (self.render_mode.get() == "segments")
        state = ("normal" if seg_mode else "disabled")
        try: self.deg_btn.configure(state=state)
        except: pass
        try: self.intensity_btn.configure(state=state)
        except: pass

    def _robust_quantiles(self, arr: np.ndarray) -> Tuple[Optional[float], Optional[float]]:
        a = np.asarray(arr, dtype=float)
        a = a[np.isfinite(a)]
        if a.size == 0:
            return None, None
        if a.size == 1:
            v = float(a[0])
            return v, v
        if a.size == 2:
            vmin, vmax = float(np.nanmin(a)), float(np.nanmax(a))
            return vmin, vmax
        qlo = float(np.nanpercentile(a, self._inten_q_lo))
        qhi = float(np.nanpercentile(a, self._inten_q_hi))
        if not np.isfinite(qlo) or not np.isfinite(qhi):
            return None, None
        return qlo, qhi

    def _t_from_abs_fc(self, val: float, qlo: Optional[float], qhi: Optional[float]) -> float:
        if val is None or not np.isfinite(val):
            return 0.0
        if (qlo is None) or (qhi is None):
            denom = max(1e-9, float(self.fc_max.get()))
            return float(min(abs(val), denom) / denom)
        if qhi <= qlo:
            return 1.0 if val >= qhi else 0.0
        return float(np.clip((val - qlo)/(qhi - qlo), 0.0, 1.0))

    # ------------------------- filter handlers -------------------------------

    def _set_fc_sign_mode(self, mode: str):
        if mode not in ("none", "exclude_neg", "exclude_pos"):
            return
        self.fc_sign_mode.set(mode)
        self._refresh_fcsign_buttons()
        self._set_banddeg_domain_for_active_chromosomes()
        self._trigger_update()
        self._update_selection_summary()

    def _refresh_fcsign_buttons(self):
        for m, b in self._fcsign_btns.items():
            if m == self.fc_sign_mode.get():
                b.configure(relief="sunken", bg="#5bc0de", fg="white",
                            activebackground="#31b0d5", activeforeground="white")
            else:
                b.configure(relief="raised", bg="#f0f0f0", fg="black",
                            activebackground="#e6e6e6", activeforeground="black")

    def _on_simple_change(self):
        self._trigger_update()

    def _on_range_change(self):
        if self.fc_min.get() > self.fc_max.get():
            self.fc_max.set(self.fc_min.get())
        self.fc_min.set(round(float(self.fc_min.get()), 1))
        self.fc_max.set(round(float(self.fc_max.get()), 1))

        tmin = round(float(self.tpm_min.get()), 1)
        tmax = round(float(self.tpm_max.get()), 1)
        tmin = max(0.0, min(100.0, tmin))
        tmax = max(0.0, min(self._tpm_dom_max_active, tmax))
        if tmin <= self._tpm_dom_max_active and tmin > tmax:
            tmax = tmin
        self.tpm_min.set(tmin)
        self.tpm_max.set(tmax)

        if self.corr_min.get() > self.corr_max.get():
            self.corr_max.set(self.corr_min.get())

        self._set_banddeg_domain_for_active_chromosomes()
        self._trigger_update()
        self._update_selection_summary()

    def _on_fdr_mode_toggle(self):
        self._refresh_fdr_ui_state()
        self._trigger_update()
        self._update_selection_summary()

    def _on_fdr_lin_change(self):
        fmin = float(self.fdr_min_lin.get()); fmax = float(self.fdr_max_lin.get())
        fmin = max(0.0, min(100.0, fmin))
        fmax = max(0.0, min(100.0, fmax))
        if fmin > fmax: fmax = fmin
        self.fdr_min_lin.set(round(fmin, 2)); self.fdr_max_lin.set(round(fmax, 2))
        self._set_banddeg_domain_for_active_chromosomes()
        self._trigger_update()
        self._update_selection_summary()

    def _on_fdr_lin_entry(self):
        self._on_fdr_lin_change()

    def _refresh_fdr_log_label(self):
        L = int(round(float(self.fdr_log_Lmax.get())))
        p = 10.0 ** L
        pct = 100.0 * p
        pct_str = f"{pct:.2f}%" if pct >= 0.01 else f"{pct:.2e}%"
        self.fdr_log_label.configure(text=f"L={L:d} → [0, {p:.2e}]  ({pct_str})")

    def _on_fdr_log_change(self):
        L = int(round(float(self.fdr_log_Lmax.get())))
        if L < -100: L = -100
        if L > 0:    L = 0
        if L != self.fdr_log_Lmax.get():
            self.fdr_log_Lmax.set(float(L))
        self._refresh_fdr_log_label()
        self._set_banddeg_domain_for_active_chromosomes()
        self._trigger_update()
        self._update_selection_summary()

    def _refresh_fdr_ui_state(self):
        mode = self.fdr_mode.get()
        state_lin = ("normal" if mode == "linear" else "disabled")
        state_log = ("normal" if mode == "logmax" else "disabled")
        for child in self._fdr_lin_frame.winfo_children():
            try: child.configure(state=state_lin)
            except: pass
        for child in self._fdr_log_frame.winfo_children():
            try: child.configure(state=state_log)
            except: pass

    def _on_banddeg_change(self):
        mn = int(round(float(self.banddeg_min.get())))
        mx = int(round(float(self.banddeg_max.get())))
        mn = max(0, min(self._banddeg_domain_max, mn))
        mx = max(0, min(self._banddeg_domain_max, mx))
        if mx < mn: mx = mn
        if mn != self.banddeg_min.get(): self.banddeg_min.set(mn)
        if mx != self.banddeg_max.get(): self.banddeg_max.set(mx)
        self._trigger_update()
        self._update_selection_summary()

    def _on_banddeg_entry_change(self):
        self._on_banddeg_change()

    # ----------------- layout helpers for panels -------------------

    def _active_span_columns(self) -> Set[int]:
        span = set()
        for c in range(12):
            top = self.chr_vars[c].get()
            bot = self.chr_vars[c+12].get()
            if top and top != "empty" and (not bot or bot == "empty"):
                span.add(c)
        return span

    def _current_visible_columns(self) -> List[int]:
        vis = []
        for c in range(12):
            top = self.chr_vars[c].get()
            bot = self.chr_vars[c+12].get()
            both_empty = (not top or top == "empty") and (not bot or bot == "empty")
            if not both_empty:
                vis.append(c)
        return vis

    def _build_axes_layout(self, visible_cols: List[int], span_cols: Set[int]):
        self.fig.clear()
        ncols = max(1, len(visible_cols))
        gs = self.fig.add_gridspec(nrows=2, ncols=ncols,
                                   height_ratios=[1, 1],
                                   wspace=DEFAULT_WSPACE, hspace=0.02)

        self.ax_for_panel = [None] * PANELS
        self.primary_index_for_axis = {}
        self.ax_unique = []

        if len(visible_cols) == 0:
            ax = self.fig.add_subplot(gs[:, 0])
            self.ax_unique.append(ax)
            return

        for j, orig_c in enumerate(visible_cols):
            if orig_c in span_cols and (self.chr_vars[orig_c].get() and self.chr_vars[orig_c].get() != "empty"):
                ax = self.fig.add_subplot(gs[:, j])
                self.ax_for_panel[orig_c] = ax
                self.ax_for_panel[orig_c + 12] = ax
                self.primary_index_for_axis[ax] = orig_c
                self.ax_unique.append(ax)
            else:
                axT = self.fig.add_subplot(gs[0, j])
                axB = self.fig.add_subplot(gs[1, j])
                self.ax_for_panel[orig_c] = axT
                self.ax_for_panel[orig_c + 12] = axB
                self.primary_index_for_axis[axT] = orig_c
                self.primary_index_for_axis[axB] = orig_c + 12
                self.ax_unique.extend([axT, axB])

    def _place_panel_title(self, ax, text: str):
        from matplotlib.transforms import blended_transform_factory
        trans = blended_transform_factory(ax.transData, ax.transAxes)
        ax.annotate(
            text,
            xy=(0.0, 1.0), xycoords=trans,
            xytext=(0, 6), textcoords="offset points",
            ha="left", va="bottom",
            fontsize=10, fontweight="bold",
            annotation_clip=False
        )

    # ---------------------------- plot ------------------------------

    def _current_fdr_range_percent(self) -> Tuple[float, float]:
        if self.fdr_mode.get() == "linear":
            fmin = max(0.0, min(100.0, float(self.fdr_min_lin.get())))
            fmax = max(0.0, min(100.0, float(self.fdr_max_lin.get())))
            if fmin > fmax: fmax = fmin
            return round(fmin, 2), round(fmax, 2)
        else:
            L = int(round(float(self.fdr_log_Lmax.get())))
            max_pct = 100.0 * (10.0 ** L)
            max_pct = max(0.0, min(100.0, max_pct))
            return 0.0, max_pct

    def _segments_intensity_scope_arrays(self, chr_name: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        if self.df is None or self.df.empty:
            return np.array([]), np.array([]), np.array([])

        fc_vals = pd.to_numeric(self.df["fc"].values, errors="coerce")
        fc_abs  = np.abs(fc_vals)

        fmin, fmax = self._current_fdr_range_percent()
        fdr = self.df["fdr"].values
        tpm = self.df["tpm"].values
        corr_abs = np.abs(self.df["immune_corr"].values)

        M_fc  = (fc_abs >= float(self.fc_min.get()) - EPS) & (fc_abs <= float(self.fc_max.get()) + EPS)
        M_fdr = (fdr    >= fmin - EPS) & (fdr    <= fmax + EPS)
        M_tpm = (tpm    >= float(self.tpm_min.get()) - EPS) & (tpm    <= float(self.tpm_max.get()) + EPS)
        M_cor = (corr_abs >= float(self.corr_min.get()) - EPS) & (corr_abs <= float(self.corr_max.get()) + EPS)

        # FC sign filter
        if self.fc_sign_mode.get() == "exclude_neg":
            sign_ok = (fc_vals > 0)
        elif self.fc_sign_mode.get() == "exclude_pos":
            sign_ok = (fc_vals < 0)
        else:
            sign_ok = np.ones_like(fc_vals, dtype=bool)
        sign_ok = np.isfinite(fc_vals) & sign_ok

        # Gene types
        sel_types = self._selected_gene_types()
        if sel_types is None:
            type_ok = np.ones(len(self.df), dtype=bool)
        else:
            sel_types = set(sel_types)
            type_ok = self.df["gene_type"].astype(str).isin(list(sel_types)).values

        base = (fc_abs >= 1.0 - EPS) & M_fc & M_fdr & M_tpm & M_cor & sign_ok & type_ok

        if self.center_mode.get() == "chrom":
            scope_mask = (self.df["chr"].astype(str).values == str(chr_name)) & base
        else:
            scope_mask = base

        scope_abs = fc_abs[scope_mask]
        pos_abs = scope_abs[fc_vals[scope_mask] > 0]
        neg_abs = scope_abs[fc_vals[scope_mask] < 0]
        return scope_abs, pos_abs, neg_abs

    def _draw_one_chrom(self, ax, chr_name, store_idx: int):
        ax.clear()
        ax.axis("off")

        # Always reset recorded segments for this panel
        self._gene_segments[store_idx] = []

        if not chr_name or chr_name == "empty":
            ax.text(0.5, 0.5, f"P{store_idx+1} (empty)", ha="center", va="center",
                    transform=ax.transAxes, fontsize=11)
            self.band_layouts[store_idx] = []
            return

        # --- Band summary (band mode uses selected types for counts; segments only needs layout)
        fdr_min_pct, fdr_max_pct = self._current_fdr_range_percent()
        sel_types = self._selected_gene_types() if self.render_mode.get()=="band" else None
        out, *_ = compute_band_summary(
            self.df, chr_name,
            float(self.fc_min.get()), float(self.fc_max.get()),
            fdr_min_pct, fdr_max_pct,
            float(self.tpm_min.get()), float(self.tpm_max.get()),
            float(self.corr_min.get()), float(self.corr_max.get()),
            center_mode=self.center_mode.get(),
            invert=(self.show_excluded.get() if self.render_mode.get()=="band" else False),
            selected_types=(sel_types if sel_types is not None else None),
            fc_sign_mode=self.fc_sign_mode.get()
        )

        show_names = (self.render_mode.get()=="segments") and self.show_deg_labels.get()
        left_margin = LEFT_LABEL_PAD if show_names else 0.02
        right_margin = 0.22 + (RIGHT_EXTRA_PAD if self.render_mode.get()=="segments" else 0.0)

        self._place_panel_title(ax, f"K_{chr_name}")

        if out is None or out.empty:
            ax.text(0.5, 0.5, f"No data for K_{chr_name}", ha="center", va="center",
                    transform=ax.transAxes, fontsize=10)
            self.band_layouts[store_idx] = []
            return

        mn = int(round(float(self.banddeg_min.get())))
        mx = int(round(float(self.banddeg_max.get())))
        emphasize = (out["n_deg"] >= mn) & (out["n_deg"] <= mx)

        metric = (out["band_gene_count"] if self.scale_mode.get() == "genes"
                  else out["band_nt_size"]).fillna(1.0).astype(float).values

        bands = out["band"]
        is_p, is_q = split_arm_mask(bands)
        metric_p = metric[is_p]; metric_q = metric[is_q]

        total_height_p = float(np.nansum(metric_p)) if metric_p.size else 0.0
        total_height_q = float(np.nansum(metric_q)) if metric_q.size else 0.0
        total_height_no_gap = total_height_p + total_height_q
        if total_height_no_gap <= 0:
            total_height_no_gap = float(len(metric)) or 1.0
            metric = np.ones_like(metric, dtype=float)

        gap_h = max(total_height_no_gap * GAP_FRACTION, MIN_GAP_ABS) if (total_height_p > 0 and total_height_q > 0) else 0.0
        y_top = total_height_no_gap + gap_h

        intens = out["intensity_raw"].values.astype(float)
        max_int = np.nanmax(intens) if intens.size else 0.0
        intens_scaled = (intens / max_int) if max_int > 1e-12 else np.zeros_like(intens)

        # --- color setup for BAND MODE (respect baseline + LOW/HIGH palette) ---
        base_colors = []
        eps = 1e-12
        cmode = self.center_mode.get()  # 'genome' | 'chrom' | 'none'

        for rc, t, n_deg, n_up, n_down in zip(
            out["ratio_centered"].values,
            intens_scaled,
            out["n_deg"].values,
            out["n_up"].values,
            out["n_down"].values
         ):
            if self.render_mode.get() == "segments":
                col = None
            else:
                if n_deg == 0:
                    # no DEG in band → gray (not clickable)
                    col = (0.85, 0.85, 0.85)
                else:
                    # Neutral (white) ONLY when centered ratio ~ 0.
                    neutral = ((abs(rc) < eps) and (n_up > 0) and (n_down > 0)) \
                              or (cmode == "none" and n_up == n_down)

                    if neutral:
                        col = NEUTRAL_WHITE
                    else:
                        t_eff = max(MIN_INTENSITY_BAND, float(t))
                        t_eff = self._gamma(t_eff, GAMMA_BAND)
                        if rc > 0:
                            col = self._lerp_color(RED_LOW, RED_HIGH, t_eff)
                        else:
                            col = self._lerp_color(BLUE_LOW, BLUE_HIGH, t_eff)
            base_colors.append(col)

        bw = float(self.bar_width.get())
        label_pad = max(0.004, bw * 0.12)

        # Make sure the name/tick gutters are in-range even if bw is tiny
        left_range = max(left_margin, 0.02)
        right_range = max(right_margin, 0.15)
        ax.set_xlim(-left_range, bw + right_range)
        ax.set_ylim(0, total_height_no_gap + gap_h)

        band_layout: List[Tuple[str, float, float, bool, float]] = []
        idx_all = np.arange(len(out))
        idx_p = idx_all[is_p]
        idx_q = idx_all[is_q]

        def draw_stack(indices, start_y_top):
            yT = start_y_top
            for idx in indices:
                h = float(metric[idx])
                y0, y1 = yT - h, yT

                if self.render_mode.get() != "segments":
                    col = base_colors[idx] if emphasize.iloc[idx] else DIMMED_COLOR
                    rect = matplotlib.patches.Rectangle((0.0, y0), bw, h,
                                                        facecolor=col, edgecolor="black", linewidth=0.7)
                    ax.add_patch(rect)

                band_layout.append((out["band"].iloc[idx], y0, y1, emphasize.iloc[idx], h))

                ax.text(
                    bw + label_pad, (y0 + y1)/2.0, str(out["band"].iloc[idx]),
                    va="center", ha="left", fontsize=8.5,
                    color=(LABEL_NORMAL if emphasize.iloc[idx] else LABEL_DIMMED)
                )
                yT = y0
            return yT

        y_after_p = draw_stack(idx_p, y_top)

        if gap_h > 0:
            y_top_gap    = y_after_p
            y_bottom_gap = y_after_p - gap_h
            y_mid        = 0.5 * (y_top_gap + y_bottom_gap)
            tri_top = matplotlib.patches.Polygon(
                [(0.0, y_top_gap), (bw, y_top_gap), (bw/2.0, y_mid)],
                closed=True, facecolor="black", edgecolor="black", linewidth=0.7, zorder=2
            )
            tri_bot = matplotlib.patches.Polygon(
                [(0.0, y_bottom_gap), (bw, y_bottom_gap), (bw/2.0, y_mid)],
                closed=True, facecolor="black", edgecolor="black", linewidth=0.7, zorder=2
            )
            ax.add_patch(tri_top); ax.add_patch(tri_bot)
            y_after_gap = y_bottom_gap
        else:
            y_after_gap = y_after_p

        _ = draw_stack(idx_q, y_after_gap)

        # store band layout for click mapping (for band clicks)
        self.band_layouts[store_idx] = [(b, y0, y1) for (b, y0, y1, _emph, _h) in band_layout]

        # ------------------- Per-gene segments -------------------
        if self.render_mode.get() == "segments":
            df_chr = self.df[self.df["chr"] == chr_name].copy()

            if not df_chr.empty:
                # Ensure numeric order; synthesize if missing/NaN
                if "gene_order" not in df_chr.columns:
                    df_chr["gene_order"] = np.nan
                df_chr["gene_order"] = pd.to_numeric(df_chr["gene_order"], errors="coerce")

                na_mask = df_chr["gene_order"].isna()
                if na_mask.any():
                    df_chr["_row_id"] = np.arange(len(df_chr))
                    df_chr["gene_order"] = (
                        df_chr
                        .groupby("band", group_keys=False)
                        .apply(lambda g: g["gene_order"].fillna(pd.Series(range(1, len(g)+1), index=g.index)))
                    )
                # Sort by band (p→q), then by gene_order, then index for stability
                df_chr["_orig_idx"] = np.arange(len(df_chr))
                df_chr_sorted = (
                    df_chr
                    .sort_values("band", key=lambda s: s.map(cyto_sort_key))
                    .sort_values(["band", "gene_order", "_orig_idx"], kind="mergesort")
                )

                gene_names = df_chr_sorted["gene"].astype(str).values
                fc_vals   = df_chr_sorted["fc"].values
                fc_abs    = np.abs(fc_vals)
                fdr_vals  = df_chr_sorted["fdr"].values
                tpm_vals  = df_chr_sorted["tpm"].values
                corr_vals = np.abs(df_chr_sorted["immune_corr"].values)
                types_vals= df_chr_sorted["gene_type"].astype(str).values
                bands_vals= df_chr_sorted["band"].astype(str).values

                # Filter masks
                M_fc  = (fc_abs >= float(self.fc_min.get()) - EPS) & (fc_abs <= float(self.fc_max.get()) + EPS)
                fmin, fmax = self._current_fdr_range_percent()
                fdr_ok = (fdr_vals >= fmin - EPS) & (fdr_vals <= fmax + EPS)
                tpm_ok = (tpm_vals >= float(self.tpm_min.get()) - EPS) & (tpm_vals <= float(self.tpm_max.get()) + EPS)
                corr_ok= (corr_vals >= float(self.corr_min.get()) - EPS) & (corr_vals <= float(self.corr_max.get()) + EPS)
                M_fc  = M_fc & np.isfinite(fc_abs)
                fdr_ok= fdr_ok & np.isfinite(fdr_vals)
                tpm_ok= tpm_ok & np.isfinite(tpm_vals)
                corr_ok= corr_ok & np.isfinite(corr_vals)
                deg_core = (fc_abs >= 1.0 - EPS) & np.isfinite(fc_abs)

                # FC sign filter
                if self.fc_sign_mode.get() == "exclude_neg":
                    sign_ok = (fc_vals > 0)
                elif self.fc_sign_mode.get() == "exclude_pos":
                    sign_ok = (fc_vals < 0)
                else:
                    sign_ok = np.ones_like(fc_vals, dtype=bool)
                sign_ok = np.isfinite(fc_vals) & sign_ok

                passes = deg_core & M_fc & fdr_ok & tpm_ok & corr_ok & sign_ok

                selected_types = self._selected_gene_types()
                if selected_types is None:
                    type_selected_mask = np.ones(len(df_chr_sorted), dtype=bool)
                else:
                    selected_types = set(selected_types)
                    type_selected_mask = np.array([t in selected_types for t in types_vals], dtype=bool)

                # Map band -> row positions
                by_band_positions: Dict[str, List[int]] = {}
                for pos, b in enumerate(bands_vals):
                    by_band_positions.setdefault(b, []).append(pos)

                # CONSTANT thickness across chromosome using ALL genes:
                total_genes_chr = len(df_chr_sorted)
                total_drawable_h = max(1e-9, total_height_no_gap)
                per_gene_thick = total_drawable_h / float(max(1, total_genes_chr))

                # ----------- Intensity quantiles (scope + unified/separate) ------------
                scope_abs, scope_pos, scope_neg = self._segments_intensity_scope_arrays(chr_name)

                if self.segments_intensity_scale.get() == "unified":
                    qlo_u, qhi_u = self._robust_quantiles(scope_abs)
                    pos_qlo = pos_qhi = None
                    neg_qlo = neg_qhi = None
                else:
                    pos_qlo, pos_qhi = self._robust_quantiles(scope_pos)
                    neg_qlo, neg_qhi = self._robust_quantiles(scope_neg)
                    qlo_u = qhi_u = None

                # Draw segments band-by-band; collect boundaries for ticks
                boundary_ys = []
                for i, (band_name, y0_band, y1_band, _is_emph, _band_h) in enumerate(band_layout):
                    positions = by_band_positions.get(str(band_name), [])
                    if i > 0:
                        boundary_ys.append(y1_band)

                    if not positions:
                        continue

                    y_cursor = y1_band
                    for pos in positions:
                        y0_slot = y_cursor - per_gene_thick
                        y1_slot = y_cursor
                        y_cursor = y0_slot

                        # clip to band bounds
                        y_seg0 = max(y0_band, y0_slot)
                        y_seg1 = min(y1_band, y1_slot)
                        if y_seg1 - y_seg0 <= 0:
                            continue

                        # Color
                        if not type_selected_mask[pos]:
                            color = (0.80, 0.80, 0.80, 1.0)
                            passes_this = False
                        else:
                            if passes[pos] and fc_vals[pos] > 0:
                                if self.segments_intensity_by_fc.get():
                                    if self.segments_intensity_scale.get() == "unified":
                                        t = self._t_from_abs_fc(fc_abs[pos], qlo_u, qhi_u)
                                    else:
                                        t = self._t_from_abs_fc(fc_abs[pos], pos_qlo, pos_qhi)
                                    t = max(MIN_INTENSITY_SEG, t)
                                    t = self._gamma(t, GAMMA_SEG)
                                    color = self._lerp_color(RED_LOW, RED_HIGH, t)
                                else:
                                    color = (RED_HIGH[0], RED_HIGH[1], RED_HIGH[2], 1.0)  # solid red = HIGH
                                passes_this = True
                            elif passes[pos] and fc_vals[pos] < 0:
                                if self.segments_intensity_by_fc.get():
                                    if self.segments_intensity_scale.get() == "unified":
                                        t = self._t_from_abs_fc(fc_abs[pos], qlo_u, qhi_u)
                                    else:
                                        t = self._t_from_abs_fc(fc_abs[pos], neg_qlo, neg_qhi)
                                    t = max(MIN_INTENSITY_SEG, t)
                                    t = self._gamma(t, GAMMA_SEG)
                                    color = self._lerp_color(BLUE_LOW, BLUE_HIGH, t)
                                else:
                                    color = (BLUE_HIGH[0], BLUE_HIGH[1], BLUE_HIGH[2], 1.0)  # solid blue = HIGH
                                passes_this = True
                            else:
                                color = (0.80, 0.80, 0.80, 1.0)  # filtered/gray
                                passes_this = False

                        rect = matplotlib.patches.Rectangle(
                            (0.0, y_seg0), bw, (y_seg1 - y_seg0),
                            facecolor=color, edgecolor=None, linewidth=0, zorder=3
                        )
                        ax.add_patch(rect)

                        # record for clicks (only colored, not gray)
                        self._gene_segments[store_idx].append({
                            "y0": y_seg0, "y1": y_seg1,
                            "gene": gene_names[pos],
                            "fc": float(fc_vals[pos]) if np.isfinite(fc_vals[pos]) else np.nan,
                            "fdr": float(fdr_vals[pos]) if np.isfinite(fdr_vals[pos]) else np.nan,
                            "tpm": float(tpm_vals[pos]) if np.isfinite(tpm_vals[pos]) else np.nan,
                            "corr": float(corr_vals[pos]) if np.isfinite(corr_vals[pos]) else np.nan,
                            "chr": str(chr_name),
                            "band": str(band_name),
                            "type_selected": bool(type_selected_mask[pos]),
                            "passes": bool(passes_this)
                        })

                        # Optional gene names on the LEFT
                        if show_names and passes_this:
                            name_color = GENE_NAME_COLOR_UP if fc_vals[pos] > 0 else GENE_NAME_COLOR_DN
                            ax.text(
                                -0.005, (y_seg0 + y_seg1)/2.0, gene_names[pos],
                                ha="right", va="center",
                                fontsize=GENE_NAME_FONTSIZE,
                                color=name_color,
                                zorder=4
                            )

                # Pink boundary ticks (constant thickness via linewidth)
                x0 = bw + 0.01
                x1 = x0 + PINK_TICK_LEN
                for yb in boundary_ys:
                    ax.hlines(yb, x0, x1,
                              colors=[PINK_TICK_COLOR],
                              linewidths=PINK_TICK_LW,
                              zorder=5)

    def update_plot(self):
        if self.df is None:
            self._refresh_segments_ui_state()
            return

        if self.fc_min.get() > self.fc_max.get(): self.fc_max.set(self.fc_min.get())
        self.fc_min.set(round(float(self.fc_min.get()), 1))
        self.fc_max.set(round(float(self.fc_max.get()), 1))

        self._apply_active_tpm_domain(set_value=False)

        tmin = round(float(self.tpm_min.get()), 1)
        tmax = round(float(self.tpm_max.get()), 1)
        tmin = max(0.0, min(100.0, tmin))
        tmax = max(0.0, min(self._tpm_dom_max_active, tmax))
        if tmin <= self._tpm_dom_max_active and tmin > tmax:
            tmax = tmin
        self.tpm_min.set(tmin); self.tpm_max.set(tmax)

        mn = int(round(float(self.banddeg_min.get())))
        mx = int(round(float(self.banddeg_max.get())))
        mn = max(0, min(self._banddeg_domain_max, mn))
        mx = max(0, min(self._banddeg_domain_max, mx))
        if mx < mn: mx = mn
        self.banddeg_min.set(mn); self.banddeg_max.set(mx)

        vis_new = self._current_visible_columns()
        span_cols_new = self._active_span_columns()

        if (vis_new != self._visible_cols) or (span_cols_new != self._span_cols):
            self._build_axes_layout(vis_new, span_cols_new)
            self._visible_cols = list(vis_new)
            self._span_cols = set(span_cols_new)

        for ax in self.ax_unique:
            ax.clear()
            ax.axis("off")

        if len(self._visible_cols) == 0:
            self.ax_unique[0].text(0.5, 0.5, "No panels (all columns hidden)", ha="center", va="center",
                                   transform=self.ax_unique[0].transAxes, fontsize=12)
        else:
            for orig_c in self._visible_cols:
                if orig_c in self._span_cols and (self.chr_vars[orig_c].get() and self.chr_vars[orig_c].get() != "empty"):
                    idx = orig_c
                    ax = self.ax_for_panel[idx]
                    chr_name = self.chr_vars[idx].get()
                    self._draw_one_chrom(ax, chr_name, store_idx=idx)
                    self.band_layouts[orig_c + 12] = []
                    self._gene_segments[orig_c + 12] = []
                else:
                    idx_top = orig_c
                    idx_bot = orig_c + 12
                    axT = self.ax_for_panel[idx_top]
                    axB = self.ax_for_panel[idx_bot]
                    chr_top = self.chr_vars[idx_top].get()
                    chr_bot = self.chr_vars[idx_bot].get()
                    self._draw_one_chrom(axT, chr_top, store_idx=idx_top)
                    self._draw_one_chrom(axB, chr_bot, store_idx=idx_bot)

        fdr_min_pct, fdr_max_pct = self._current_fdr_range_percent()
        mode_txt = ("linear [%0.2f, %0.2f]%%" % (fdr_min_pct, fdr_max_pct)) if self.fdr_mode.get()=="linear" \
                   else ("logmax [0, %s]" % (f"{fdr_max_pct:.2e}%" if fdr_max_pct < 0.01 else f"{fdr_max_pct:.2f}%"))

        rmode = "Segments" if self.render_mode.get()=="segments" else "Band ratio"
        showing_txt = "" if self.render_mode.get()=="segments" else (" | Showing: EXCLUDED" if self.show_excluded.get() else " | Showing: SELECTED")
        sign_txt = {"none":"±FC", "exclude_neg":"+only", "exclude_pos":"−only"}[self.fc_sign_mode.get()]
        inten_txt = ""
        if self.render_mode.get()=="segments":
            scope_txt = {"genome":"GENOME", "chrom":"CHROM", "none":"GENOME"}[self.center_mode.get()]
            scale_txt = "Unified" if self.segments_intensity_scale.get()=="unified" else "Separate"
            inten_txt = " | Seg intensity(|FC|): " + ("ON" if self.segments_intensity_by_fc.get() else "OFF") \
                        + ("" if not self.segments_intensity_by_fc.get() else f" [{scale_txt}, scope={scope_txt}]")
        self.counts_var.set(
            f"{rmode}{showing_txt}{inten_txt} | {sign_txt} | Patient: {self.current_patient.get() or '—'} | "
            f"FDR: {mode_txt} | |FC| [{self.fc_min.get():.1f},{self.fc_max.get():.1f}] "
            f"| TPM [{self.tpm_min.get():.1f},{self.tpm_max.get():.1f}] "
            f"| immun |cor| [{self.corr_min.get():.2f},{self.corr_max.get():.2f}]"
        )

        self.canvas.draw_idle()
        self._update_selection_summary()
        self._refresh_segments_ui_state()

    # --------------------------- selection summary helpers --------------------

    @staticmethod
    def _fmt_count(n: int) -> str:
        try:
            return f"{int(n):,}"
        except:
            return str(int(n))

    @staticmethod
    def _fmt_pct(n: int, denom: int) -> str:
        if denom <= 0:
            return "0.0%"
        return f"{(100.0 * n / denom):.1f}%"

    def _build_filter_masks(self):
        scope = self._active_scope_mask()
        if self.df is None or self.df.empty or scope.sum() == 0:
            n = 0 if self.df is None else len(self.df)
            z = np.zeros(n, dtype=bool)
            return scope, z, z, z, z

        fc_abs = np.abs(self.df["fc"].values)
        M_fc = (fc_abs >= float(self.fc_min.get()) - EPS) & (fc_abs <= float(self.fc_max.get()) + EPS)

        fmin, fmax = self._current_fdr_range_percent()
        fdr = self.df["fdr"].values
        M_fdr = (fdr >= fmin - EPS) & (fdr <= fmax + EPS)

        tpm = self.df["tpm"].values
        M_tpm = (tpm >= float(self.tpm_min.get()) - EPS) & (tpm <= float(self.tpm_max.get()) + EPS)

        corr_abs = np.abs(self.df["immune_corr"].values)
        M_corr = (corr_abs >= float(self.corr_min.get()) - EPS) & (corr_abs <= float(self.corr_max.get()) + EPS)

        return scope, M_fc, M_fdr, M_tpm, M_corr

    def _band_ok_mask_for_base(self, base_mask: np.ndarray) -> np.ndarray:
        if self.df is None or self.df.empty:
            return np.zeros(0, dtype=bool)

        scope = self._active_scope_mask()
        base_mask = base_mask & scope

        mn = int(round(float(self.banddeg_min.get())))
        mx = int(round(float(self.banddeg_max.get())))
        mn = max(0, mn); mx = max(mn, mx)

        df_tmp = pd.DataFrame({
            "chr": self.df["chr"].values[scope],
            "band": self.df["band"].values[scope],
            "hit": base_mask[scope].astype(int)
        })
        band_counts = df_tmp.groupby(["chr", "band"], sort=False)["hit"].sum()
        band_ok_map = (band_counts.between(mn, mx)).to_dict()

        chr_vals = self.df["chr"].values
        band_vals = self.df["band"].values
        return np.array([band_ok_map.get((c,b), False) for c,b in zip(chr_vals, band_vals)], dtype=bool)

    def _compute_core_and_pass_sets(self):
        if self.df is None or self.df.empty:
            return 0, np.zeros(0, dtype=bool), 0, 0

        scope, M_fc, M_fdr, M_tpm, M_corr = self._build_filter_masks()
        fc_vals = self.df["fc"].values
        fc_abs = np.abs(fc_vals)
        deg_core = (fc_abs >= 1.0 - EPS) & scope

        # FC sign filter
        if self.fc_sign_mode.get() == "exclude_neg":
            sign_ok = (fc_vals >= 0)
        elif self.fc_sign_mode.get() == "exclude_pos":
            sign_ok = (fc_vals <= 0)
        else:
            sign_ok = np.ones_like(fc_vals, dtype=bool)

        pass_mask = deg_core & M_fc & M_fdr & M_tpm & M_corr & sign_ok
        if self.show_excluded.get() and self.render_mode.get() == "band":
            pass_mask = deg_core & (~(M_fc & M_fdr & M_tpm & M_corr & sign_ok))

        up = int((pass_mask & (fc_vals > 0)).sum())
        down = int((pass_mask & (fc_vals < 0)).sum())
        core_total = int(deg_core.sum())
        return core_total, pass_mask, up, down

    def _compute_shown_hidden_counts(self):
        core_total, pass_mask, _u, _d = self._compute_core_and_pass_sets()
        band_ok = self._band_ok_mask_for_base(pass_mask)
        shown = int((pass_mask & band_ok).sum())
        hidden = core_total - shown
        return core_total, shown, hidden

    def _update_selection_summary(self):
        if self.df is None or self.df.empty:
            self.selection_summary_var.set("—")
            return

        scope_mask = self._active_scope_mask()
        total_scope_genes = int(scope_mask.sum())
        total_genome_genes = int(len(self.df))

        core_total, pass_mask, up, down = self._compute_core_and_pass_sets()
        Z = up + down
        XY_pct = self._fmt_pct(Z, core_total)
        up_pct = self._fmt_pct(up, Z)
        down_pct = self._fmt_pct(down, Z)

        _core_total, shown, hidden = self._compute_shown_hidden_counts()

        total_line = (f"Total genes in scope = {self._fmt_count(total_scope_genes)}"
                      f"  |  genome = {self._fmt_count(total_genome_genes)}")

        deg_line = (f"DEG = {self._fmt_count(Z)}  "
                    f"({XY_pct} of core)  |  "
                    f"up = {self._fmt_count(up)} ({up_pct})  |  "
                    f"down = {self._fmt_count(down)} ({down_pct})")

        shown_line = f"Shown = {self._fmt_count(shown)} ({self._fmt_pct(shown, core_total)})  |  " \
                     f"Hidden = {self._fmt_count(hidden)} ({self._fmt_pct(hidden, core_total)})"

        lines = [total_line, deg_line, shown_line]
        self.selection_summary_var.set("\n".join(lines))

    # --------------------------- click handler -------------------------------

    def on_click_plot(self, event):
        if self.df is None or event.inaxes is None:
            return
        ax = event.inaxes
        panel_idx = self.primary_index_for_axis.get(ax)
        if panel_idx is None:
            return

        chr_name = self.chr_vars[panel_idx].get()
        if not chr_name or chr_name == "empty":
            return

        x = event.xdata
        y = event.ydata
        if (x is None) or (y is None):
            return

        # Prefer gene clicks in segments mode (segment area or left label gutter)
        if self.render_mode.get() == "segments":
            left_gutter_min_x = -LEFT_LABEL_PAD if self.show_deg_labels.get() else 0.0
            within_x_for_segment = (0.0 <= x <= float(self.bar_width.get()))
            within_x_for_label   = (left_gutter_min_x <= x <= 0.0)

            if within_x_for_segment or within_x_for_label:
                tol = 1e-9
                for g in self._gene_segments[panel_idx]:
                    if (g["y0"] - tol) <= y <= (g["y1"] + tol):
                        # Clickable only if colored (passes=True), i.e. not gray
                        if not g.get("passes", False):
                            return
                        fc  = g["fc"]; fdr = g["fdr"]; tpm = g["tpm"]; corr= g["corr"]
                        fc_txt  = "—" if not np.isfinite(fc)  else f"{fc:.3f}"
                        fdr_txt = "—" if not np.isfinite(fdr) else f"{fdr:.2f}%"
                        tpm_txt = "—" if not np.isfinite(tpm) else f"{tpm:.1f}"
                        cor_txt = "—" if not np.isfinite(corr) else f"{abs(corr):.3f}"

                        messagebox.showinfo(
                            "Gene details",
                            (f"Patient: {self.current_patient.get()}\n"
                             f"Gene: {g['gene']}\n"
                             f"Location: K_{g['chr']} {g['band']}\n\n"
                             f"FC: {fc_txt}\n"
                             f"FDR: {fdr_txt}\n"
                             f"TPM: {tpm_txt}\n"
                             f"|immune_corr|: {cor_txt}\n")
                        )
                        return
            # fall through to band click if no gene hit

        # Band click (both modes) — clickable only if band has n_deg>0 (i.e., not gray)
        for band, y0, y1 in self.band_layouts[panel_idx]:
            if y0 <= y <= y1:
                fdr_min_pct, fdr_max_pct = self._current_fdr_range_percent()
                sel_types = self._selected_gene_types() if self.render_mode.get()=="band" else None
                out, total_deg_genome, total_deg_chr, ratio_genome, ratio_chrom = compute_band_summary(
                    self.df, chr_name,
                    float(self.fc_min.get()), float(self.fc_max.get()),
                    fdr_min_pct, fdr_max_pct,
                    float(self.tpm_min.get()), float(self.tpm_max.get()),
                    float(self.corr_min.get()), float(self.corr_max.get()),
                    center_mode=self.center_mode.get(),
                    invert=(self.show_excluded.get() if self.render_mode.get()=="band" else False),
                    selected_types=(sel_types if sel_types is not None else None),
                    fc_sign_mode=self.fc_sign_mode.get()
                )
                row = out.loc[out["band"] == band]
                if row.empty:
                    return
                r = row.iloc[0]
                if int(r['n_deg']) <= 0:
                    return  # gray/filtered → not clickable

                base = {"genome": ratio_genome, "chrom": ratio_chrom, "none": 0.0}[self.center_mode.get()]
                dir_txt = "Up-majority" if r["ratio_centered"] > 0 else ("Down-majority" if r["ratio_centered"] < 0 else "No majority")

                med_fdr = r.get("med_fdr", np.nan)
                med_tpm = r.get("med_tpm", np.nan)
                med_fdr_txt = ("—" if pd.isna(med_fdr) else f"{float(med_fdr):.2f}%")
                med_tpm_txt = ("—" if pd.isna(med_tpm) else f"{float(med_tpm):.1f}")

                messagebox.showinfo(
                    "Cytoband details",
                    (f"Patient: {self.current_patient.get()}\n"
                     f"K_{chr_name} {band}\n\n"
                     f"Band nt size: {int(r['band_nt_size']):,}\n"
                     f"Band gene count (provided): {int(r['band_gene_count'])}\n\n"
                     f"#DEG: {int(r['n_deg'])}  (Up: {int(r['n_up'])}, Down: {int(r['n_down'])})\n"
                     f"Median FDR: {med_fdr_txt}\n"
                     f"Median TPM: {med_tpm_txt}\n\n"
                     f"Ratio (raw): {r['ratio_raw']:.3f}\n"
                     f"Baseline ({self.center_mode.get()}): {base:.3f}\n"
                     f"Ratio (centered): {r['ratio_centered']:.3f}  → {dir_txt}\n"
                     f"DEG density: {r['density']:.3f}\n")
                )
                return

# ------------------------------ main -------------------------------

if __name__ == "__main__":
    app = CytobandDEApp()
    app.mainloop()
