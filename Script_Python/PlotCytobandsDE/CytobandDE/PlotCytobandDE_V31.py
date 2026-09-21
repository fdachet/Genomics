#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.widgets import RectangleSelector
import mplcursors

# --- Tunables ---
PSEUDOCOUNT        = 1.0
DEV_SCALE_PCTL     = 95
BINS_MIN, BINS_MAX = 5, 100
PAD_FRAC           = 0.01     # symmetric padding if min==max
PAD_MIN            = 1e-3
ALPHA_MAX_SCALE    = 5.0      # cap alpha at 5
FDR_EPS            = 1e-300   # avoid infs for -log10(FDR)

# Slider layout sizes (middle panel)
ROW_PADX           = 8
ROW_PADY           = 6
ENTRY_W            = 10             # width of min/max entries (characters)
RESET_W            = 4              # width of Reset button (characters)
LOG_W              = 2              # width of tiny log checkbox (~half reset)

# Slider length reduced by ~30% (was 340)
DUAL_LEN_PX        = 238            # pixel length for dual-handle slider & single Scales
DUAL_HEIGHT_PX     = 22             # height of the dual slider canvas
HANDLE_R           = 8              # handle radius (px)
TRACK_H            = 6              # track height (px)
ACTIVE_FILL        = "#f4cc80"      # active range fill
TRACK_FILL         = "#d1d5db"      # gray track
HANDLE_FILL        = "#f59e0b"      # handle color
HANDLE_OUTLINE     = "#000000"      # handle outline
# ----------------


def _expand_range(lo, hi, frac=PAD_FRAC, min_pad=PAD_MIN):
    """Return (lo, hi) with hi>lo; if degenerate, pad symmetrically."""
    if not (np.isfinite(lo) and np.isfinite(hi)):
        return 0.0, 1.0
    lo, hi = float(lo), float(hi)
    if hi <= lo:
        c = lo
        pad = max(min_pad, abs(c) * frac)
        return c - pad, c + pad
    return lo, hi


def _fmt6(x):
    try:
        return f"{float(x):.6g}"
    except Exception:
        return str(x)


class DualRangeSlider(tk.Canvas):
    """A pure-Tk dual-handle horizontal slider on a Canvas.

    - from_: minimum numeric value (float)
    - to:    maximum numeric value (float)
    - length: pixel width of the slider (not counting internal padding)
    - command(lo, hi): callback on change (during drag & after)
    """
    def __init__(self, master, from_, to, length=300, height=22,
                 handle_radius=8, track_h=6, command=None, **kwargs):
        super().__init__(master, width=length, height=height,
                         highlightthickness=0, bd=0, **kwargs)
        self.from_ = float(from_)
        self.to    = float(to)
        if self.to == self.from_:
            self.to = self.from_ + 1.0
        self.length = int(length)
        self.height = int(height)
        self.hr = int(handle_radius)
        self.track_h = int(track_h)
        self.command = command

        # internal padding to keep handles inside canvas border
        self.padx = self.hr + 2
        self.pady = 2

        # current lo/hi values
        self.lo = self.from_
        self.hi = self.to

        # draw base
        self._build_graphics()

        # interaction state
        self._drag = None  # 'lo' or 'hi' or None

        # bindings
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

        # initial paint
        self._update_positions()

    # ---- drawing helpers ----
    def _build_graphics(self):
        self.delete("all")
        ymid = self.height // 2
        th = self.track_h
        # track
        self.track_id = self.create_rectangle(
            self.padx, ymid - th//2, self.length - self.padx, ymid + th//2,
            fill=TRACK_FILL, outline=""
        )
        # active range fill (between handles)
        self.active_id = self.create_rectangle(
            self.padx, ymid - th//2, self.length - self.padx, ymid + th//2,
            fill=ACTIVE_FILL, outline=""
        )
        # handles
        r = self.hr
        self.h1 = self.create_oval(0, ymid - r, 2*r, ymid + r,
                                   fill=HANDLE_FILL, outline=HANDLE_OUTLINE, width=1)
        self.h2 = self.create_oval(0, ymid - r, 2*r, ymid + r,
                                   fill=HANDLE_FILL, outline=HANDLE_OUTLINE, width=1)

    def _val_to_x(self, v):
        v = float(v)
        v = max(self.from_, min(self.to, v))
        if self.to == self.from_:
            return self.padx
        frac = (v - self.from_) / (self.to - self.from_)
        return int(self.padx + frac * (self.length - 2*self.padx))

    def _x_to_val(self, x):
        x = float(x)
        x = max(self.padx, min(self.length - self.padx, x))
        frac = (x - self.padx) / (self.length - 2*self.padx)
        return self.from_ + frac * (self.to - self.from_)

    def _move_handle_to(self, item, x):
        r = self.hr
        ymid = self.height // 2
        self.coords(item, x - r, ymid - r, x + r, ymid + r)

    def _update_positions(self):
        # clamp lo/hi & ensure order
        lo = max(self.from_, min(self.lo, self.to))
        hi = max(self.from_, min(self.hi, self.to))
        if lo > hi:
            lo, hi = hi, lo
        self.lo, self.hi = lo, hi

        x1 = self._val_to_x(self.lo)
        x2 = self._val_to_x(self.hi)
        # handles
        self._move_handle_to(self.h1, x1)
        self._move_handle_to(self.h2, x2)
        # active fill
        ymid = self.height // 2
        th = self.track_h
        self.coords(self.active_id, x1, ymid - th//2, x2, ymid + th//2)

    # ---- public API ----
    def set_range(self, from_, to_):
        """Change full range, preserving current relative positions if possible."""
        from_, to_ = float(from_), float(to_)
        if to_ == from_:
            to_ = from_ + 1.0
        # keep relative fractions
        f_lo = (self.lo - self.from_) / (self.to - self.from_) if (self.to - self.from_) else 0.0
        f_hi = (self.hi - self.from_) / (self.to - self.from_) if (self.to - self.from_) else 1.0
        self.from_, self.to = from_, to_
        self.lo = self.from_ + f_lo * (self.to - self.from_)
        self.hi = self.from_ + f_hi * (self.to - self.from_)
        self._update_positions()
        self._fire()

    def set(self, lo, hi, fire=True):
        """Set lo/hi values and repaint. fire=False to skip callback."""
        self.lo, self.hi = float(lo), float(hi)
        self._update_positions()
        if fire:
            self._fire()

    def get(self):
        return float(self.lo), float(self.hi)

    # ---- events ----
    def _near_handle(self, x):
        """Return 'lo' or 'hi' depending on nearest handle to x."""
        x1 = self._val_to_x(self.lo)
        x2 = self._val_to_x(self.hi)
        return 'lo' if abs(x - x1) <= abs(x - x2) else 'hi'

    def _on_press(self, ev):
        x = ev.x
        # pick the nearest handle
        self._drag = self._near_handle(x)

    def _on_drag(self, ev):
        if not self._drag:
            return
        v = self._x_to_val(ev.x)
        if self._drag == 'lo':
            # lo cannot exceed current hi
            v = min(v, self.hi)
            self.lo = v
        else:
            # hi cannot be below current lo
            v = max(v, self.lo)
            self.hi = v
        self._update_positions()
        self._fire()

    def _on_release(self, _ev):
        self._drag = None
        self._fire()

    def _fire(self):
        if callable(self.command):
            try:
                self.command(self.lo, self.hi)
            except Exception:
                pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cytoband ratio grid")
        self.geometry("1780x980")

        # ================= LAYOUT: Left (controls), Middle (sliders), Right (plot) =================
        self.paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        self.paned.pack(fill="both", expand=True)

        # Left panel: file/chr/cytoband
        self.left_panel = ttk.Frame(self.paned, width=280)
        self.paned.add(self.left_panel, weight=0)

        # Middle panel: ALL Tk sliders (dual range + entries + reset/log under slider) and alpha + bins
        self.mid_panel = ttk.Frame(self.paned, width=600)
        self.paned.add(self.mid_panel, weight=0)

        # Right panel: main plot
        self.right_panel = ttk.Frame(self.paned)
        self.paned.add(self.right_panel, weight=1)

        # ================= Data & State =================
        self.df = None
        self.colnames = []  # actual headers from file in order
        self.col_idx_chr, self.col_idx_gene, self.col_idx_cb = 0, 1, 2
        self.col_idx_fc,  self.col_idx_fdr, self.col_idx_tpm = 3, 4, 5

        # Selection state
        self.chr_current = None
        self.cb_selected = []
        self.grid_n = 50
        self.alpha_var = tk.DoubleVar(value=1.0)

        # Per-metric log states
        self.log_states = {"tpm": False, "fdr": False, "fc": False}

        # Debounce for redraws
        self._redraw_after_id = None

        # ================= LEFT: Controls =================
        self._build_left_controls()

        # ================= MIDDLE: Sliders (pure Tk) =================
        self.mid_inner = ttk.Frame(self.mid_panel)
        self.mid_inner.pack(fill="both", expand=True, padx=8, pady=8)
        self.range_rows = {}  # key -> dict of widgets/vars

        # Bottom: Bins row (single)
        self._build_bins_row()

        # ================= RIGHT: Plot Figure =================
        self.plot_fig, self.plot_ax = plt.subplots(figsize=(8, 7), dpi=100)
        self.plot_fig.subplots_adjust(left=0.12, right=0.98, top=0.95, bottom=0.10)
        self.plot_canvas = FigureCanvasTkAgg(self.plot_fig, master=self.right_panel)
        self.plot_canvas.get_tk_widget().pack(fill="both", expand=True)

        self.toolbar = NavigationToolbar2Tk(self.plot_canvas, self.right_panel)
        self.toolbar.update()

        # Plot state
        self.f_bins = None
        self.t_bins = None
        self.up = None
        self.dn = None
        self.tot = None
        self.ratio = None
        self.bin_rows = None
        self.im = None
        self.cursor = None
        self.selector = None

    # ---------------- LEFT PANEL ----------------
    def _build_left_controls(self):
        pad = {"padx": 8, "pady": 6}

        ttk.Button(self.left_panel, text="Browse File…", command=self.on_browse).grid(row=0, column=0, sticky="ew", **pad)

        ttk.Label(self.left_panel, text="Chromosome:").grid(row=1, column=0, sticky="w", **pad)
        self.chr_var = tk.StringVar(value="")
        self.chr_combo = ttk.Combobox(self.left_panel, textvariable=self.chr_var, state="readonly", width=18)
        self.chr_combo.grid(row=2, column=0, sticky="ew", **pad)
        self.chr_combo.bind("<<ComboboxSelected>>", lambda e: self.on_chr_change())

        ttk.Label(self.left_panel, text="Cytobands (multi-select):").grid(row=3, column=0, sticky="w", **pad)

        cb_frame = ttk.Frame(self.left_panel)
        cb_frame.grid(row=4, column=0, sticky="nsew", **pad)
        self.left_panel.rowconfigure(4, weight=1)
        self.left_panel.columnconfigure(0, weight=1)

        self.cb_listbox = tk.Listbox(cb_frame, selectmode="extended", exportselection=False, height=16)
        yscroll = ttk.Scrollbar(cb_frame, orient="vertical", command=self.cb_listbox.yview)
        self.cb_listbox.config(yscrollcommand=yscroll.set)
        self.cb_listbox.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        cb_frame.rowconfigure(0, weight=1)
        cb_frame.columnconfigure(0, weight=1)

        ttk.Button(self.left_panel, text="Update Plot", command=self.on_cb_change).grid(row=5, column=0, sticky="ew", **pad)

    # ================= File I/O =================
    def on_browse(self):
        path = filedialog.askopenfilename(
            title="Select input file",
            filetypes=[("Tab-delimited", "*.txt *.tsv *.tabtxt"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            df = pd.read_csv(path, sep="\t")
        except Exception as e:
            messagebox.showerror("Read error", str(e))
            return

        # Keep headers in order
        self.colnames = df.columns.tolist()
        if len(self.colnames) < 6:
            messagebox.showerror("Format error", "Input must have at least 6 columns.")
            return

        # Coerce numeric on FC/FDR/TPM (positions 3,4,5)
        for idx in (self.col_idx_fc, self.col_idx_fdr, self.col_idx_tpm):
            df.iloc[:, idx] = pd.to_numeric(df.iloc[:, idx], errors="coerce")
        df = df.dropna(subset=[df.columns[self.col_idx_fc], df.columns[self.col_idx_fdr], df.columns[self.col_idx_tpm]])
        if df.empty:
            messagebox.showwarning("Empty", "No valid rows after parsing.")
            return

        self.df = df

        # Populate chromosomes
        chrs = sorted(self.df.iloc[:, self.col_idx_chr].astype(str).unique().tolist())
        self.chr_combo["values"] = chrs
        if chrs:
            self.chr_var.set(chrs[0])
            self.chr_current = chrs[0]
            self._populate_cytobands()
            self.rebuild_all()

    def _populate_cytobands(self):
        """Populate cytoband listbox based on current chromosome and select ALL by default."""
        if self.df is None or self.chr_current is None:
            return
        sub = self.df[self.df.iloc[:, self.col_idx_chr].astype(str) == str(self.chr_current)]
        cbs = sorted(sub.iloc[:, self.col_idx_cb].astype(str).unique().tolist())
        self.cb_listbox.delete(0, "end")
        for cb in cbs:
            self.cb_listbox.insert("end", cb)
        self.cb_selected = cbs[:]  # select all by default
        if cbs:
            self.cb_listbox.selection_clear(0, "end")
            self.cb_listbox.selection_set(0, "end")

    def on_chr_change(self):
        self.chr_current = self.chr_var.get()
        self._populate_cytobands()
        self.rebuild_all()

    def on_cb_change(self):
        sel_idx = self.cb_listbox.curselection()
        self.cb_selected = [self.cb_listbox.get(i) for i in sel_idx] if sel_idx else []
        self.rebuild_all()

    # ================= Helpers (log transforms & labels) =================
    def _tpmt(self, arr):
        return np.log10(np.asarray(arr, dtype=float) + PSEUDOCOUNT) if self.log_states["tpm"] else np.asarray(arr, dtype=float)

    def _fdrt(self, arr):
        a = np.asarray(arr, dtype=float)
        if self.log_states["fdr"]:
            a = np.clip(a, FDR_EPS, None)
            return -np.log10(a)
        return a

    def _fcat(self, fc_arr):
        a = np.abs(np.asarray(fc_arr, dtype=float))
        if self.log_states["fc"]:
            return np.log10(a + PSEUDOCOUNT)
        return a

    def _xlabel(self, base):
        return f"{base} (log10)" if self.log_states["tpm"] else base

    def _ylabel(self, base):
        return f"−log10({base})" if self.log_states["fdr"] else base

    def _display_name_for_key(self, key, tcol, fcol, fccol):
        if key == tcol:
            return f"{tcol} (log10)" if self.log_states["tpm"] else tcol
        if key == fcol:
            return f"−log10({fcol})" if self.log_states["fdr"] else fcol
        if key == fccol:
            return f"{fccol} (|·|, log10)" if self.log_states["fc"] else fccol
        return key

    # ================= Slider rows (pure Tk) =================
    def rebuild_all(self):
        """Recompute full ranges & rebuild slider rows; redraw plot."""
        if self.df is None or self.chr_current is None:
            return

        sub_chr = self.df[self.df.iloc[:, self.col_idx_chr].astype(str) == str(self.chr_current)]
        sub = sub_chr[sub_chr.iloc[:, self.col_idx_cb].astype(str).isin(self.cb_selected)] if self.cb_selected else sub_chr

        self.plot_ax.clear()
        if sub.empty:
            self.plot_ax.set_title("No data for selection")
            self.plot_canvas.draw_idle()
            return

        # Column names (keys)
        tcol  = self.colnames[self.col_idx_tpm]
        fcol  = self.colnames[self.col_idx_fdr]
        fccol = self.colnames[self.col_idx_fc]

        # Transformed data for ranges
        tpm_tr = self._tpmt(sub.iloc[:, self.col_idx_tpm].values)
        fdr_tr = self._fdrt(sub.iloc[:, self.col_idx_fdr].values)
        fc_tr  = self._fcat(sub.iloc[:, self.col_idx_fc].values)

        tmin, tmax   = _expand_range(np.min(tpm_tr), np.max(tpm_tr))
        fmin, fmax   = _expand_range(np.min(fdr_tr), np.max(fdr_tr))
        fcmin, fcmax = _expand_range(np.min(fc_tr),  np.max(fc_tr))

        # Coarse grid to set dynamic Ratio/Qty ceilings
        GRID_EST = min(self.grid_n, 50)
        f_bins = np.linspace(fmin, fmax, GRID_EST + 1)
        t_bins = np.linspace(tmin, tmax, GRID_EST + 1)
        up = np.zeros((GRID_EST, GRID_EST))
        dn = np.zeros((GRID_EST, GRID_EST))
        fi = np.clip(np.digitize(fdr_tr, f_bins) - 1, 0, GRID_EST - 1)
        GRID = GRID_EST
        ti = np.clip(np.digitize(tpm_tr, t_bins) - 1, 0, GRID - 1)
        for fy, tx, fc in zip(fi, ti, sub.iloc[:, self.col_idx_fc].values):
            if fc > 1: up[fy, tx] += 1
            elif fc < 1: dn[fy, tx] += 1
        total = up + dn
        ratio = np.where(up >= dn, (up + 1) / (dn + 1), - (dn + 1) / (up + 1))
        qty_max = max(1, int(total.max())) if total.size else 1
        rat_max = float(np.abs(ratio).max()) if ratio.size else 1.01
        if rat_max < 1.01:
            rat_max = 1.01

        ranges = {
            tcol:   (tmin, tmax),
            fcol:   (fmin, fmax),
            fccol:  (fcmin, fcmax),
            "Ratio": (1.0, rat_max),
            "Qty":   (0.0, float(qty_max)),
        }

        self._rebuild_slider_rows(ranges, tcol, fcol, fccol)
        self._draw_plot()

    def _destroy_children(self, parent):
        for w in parent.winfo_children():
            w.destroy()

    def _rebuild_slider_rows(self, ranges, tcol, fcol, fccol):
        """Builds all rows in the middle panel using Tk widgets and DualRangeSlider.
           Reset + Log are placed UNDER the slider (to avoid being cut off)."""
        self._destroy_children(self.mid_inner)
        self.range_rows.clear()

        rowi = 0
        for key in [tcol, fcol, fccol, "Ratio", "Qty"]:
            lo, hi = ranges[key]
            disp = self._display_name_for_key(key, tcol, fcol, fccol)

            # top label (dynamic text)
            lbl = ttk.Label(self.mid_inner, text=f"{disp} [{_fmt6(lo)},{_fmt6(hi)}]", font=("", 9, "bold"))
            lbl.grid(row=rowi, column=0, columnspan=7, sticky="w", padx=ROW_PADX, pady=(ROW_PADY, 2))
            rowi += 1

            # row frame
            rframe = ttk.Frame(self.mid_inner)
            rframe.grid(row=rowi, column=0, columnspan=7, sticky="ew", padx=ROW_PADX)
            self.mid_inner.columnconfigure(0, weight=1)

            # min entry (left side)
            ent_lo = ttk.Entry(rframe, width=ENTRY_W)
            ent_lo.insert(0, _fmt6(lo))
            ent_lo.grid(row=0, column=0, padx=(0, 6), pady=2, sticky="w")

            # dual-range slider (one widget, two handles) centered
            drs = DualRangeSlider(
                rframe, from_=lo, to=hi, length=DUAL_LEN_PX, height=DUAL_HEIGHT_PX,
                handle_radius=HANDLE_R, track_h=TRACK_H,
                command=lambda vlo, vhi, k=key: self._on_dual_drag(k, vlo, vhi)
            )
            drs.set(lo, hi, fire=False)
            drs.grid(row=0, column=1, columnspan=3, padx=6, pady=0, sticky="w")

            # max entry (right side)
            ent_hi = ttk.Entry(rframe, width=ENTRY_W)
            ent_hi.insert(0, _fmt6(hi))
            ent_hi.grid(row=0, column=4, padx=(6, 6), pady=2, sticky="w")

            # --- controls UNDER the slider (row 1 inside rframe) ---
            ctrl = ttk.Frame(rframe)
            ctrl.grid(row=1, column=1, columnspan=3, sticky="w", padx=6, pady=(4, 0))

            # reset button
            btn = ttk.Button(ctrl, text="R", width=RESET_W,
                             command=lambda k=key, lo_=lo, hi_=hi: self._on_reset(k, lo_, hi_))
            btn.grid(row=0, column=0, padx=(0, 6), pady=0, sticky="w")

            # tiny log box for TPM/FDR/|FC| (right next to Reset)
            log_btn = None
            log_var = None
            key_type = None
            if key == tcol:
                key_type = "tpm"
            elif key == fcol:
                key_type = "fdr"
            elif key == fccol:
                key_type = "fc"

            if key_type is not None:
                log_var = tk.BooleanVar(value=self.log_states[key_type])
                log_btn = ttk.Checkbutton(ctrl, variable=log_var, width=LOG_W,
                                          command=lambda kt=key_type: self._on_log_toggle(kt))
                log_btn.grid(row=0, column=1, padx=(0, 0), pady=0, sticky="w")

            # entry bindings
            ent_lo.bind("<Return>", lambda _e, k=key: self._on_entry_commit(k, "lo"))
            ent_lo.bind("<KP_Enter>", lambda _e, k=key: self._on_entry_commit(k, "lo"))
            ent_hi.bind("<Return>", lambda _e, k=key: self._on_entry_commit(k, "hi"))
            ent_hi.bind("<KP_Enter>", lambda _e, k=key: self._on_entry_commit(k, "hi"))

            self.range_rows[key] = {
                "disp": disp, "full_lo": lo, "full_hi": hi,
                "lbl": lbl,
                "ent_lo": ent_lo, "ent_hi": ent_hi,
                "scl": drs,  # DualRangeSlider
                "btn": btn, "log_btn": log_btn, "log_var": log_var,
                "key_type": key_type
            }

            rowi += 1  # next metric label row

        # ---- ALPHA row (single) under the others ----
        ttk.Separator(self.mid_inner, orient="horizontal").grid(row=rowi, column=0, columnspan=7, sticky="ew", pady=(10, 6), padx=ROW_PADX)
        rowi += 1

        al_lbl = ttk.Label(self.mid_inner, text=f"Alpha× {self.alpha_var.get():.2f}", font=("", 9, "bold"))
        al_lbl.grid(row=rowi, column=0, columnspan=7, sticky="w", padx=ROW_PADX, pady=(0, 2))
        rowi += 1

        afr = ttk.Frame(self.mid_inner)
        afr.grid(row=rowi, column=0, columnspan=7, sticky="ew", padx=ROW_PADX)

        a_ent = ttk.Entry(afr, width=ENTRY_W)
        a_ent.insert(0, f"{self.alpha_var.get():.2f}")
        a_ent.grid(row=0, column=0, padx=(0, 6), pady=2, sticky="w")

        a_scl = ttk.Scale(
            afr, from_=0.1, to=ALPHA_MAX_SCALE, orient="horizontal", length=DUAL_LEN_PX,
            command=lambda v: self._on_alpha_drag(v, al_lbl, a_ent)
        )
        a_scl.set(self.alpha_var.get())
        a_scl.grid(row=0, column=1, columnspan=3, padx=6, pady=2, sticky="w")

        a_rst = ttk.Button(afr, text="R", width=RESET_W, command=lambda: self._on_alpha_reset(al_lbl, a_scl, a_ent))
        a_rst.grid(row=0, column=5, padx=(6, 0), pady=2, sticky="w")

        a_ent.bind("<Return>", lambda _e: self._on_alpha_submit(al_lbl, a_scl, a_ent))
        a_ent.bind("<KP_Enter>", lambda _e: self._on_alpha_submit(al_lbl, a_scl, a_ent))

        # small spacer
        ttk.Label(self.mid_inner, text="").grid(row=rowi+1, column=0, pady=4)

    def _build_bins_row(self):
        """Bottom row in the middle panel for #Bins (native Tk scale)."""
        bottom = ttk.Frame(self.mid_panel)
        bottom.pack(fill="x", side="bottom", padx=8, pady=8)

        ttk.Separator(bottom, orient="horizontal").pack(fill="x", side="top", pady=(0, 8))

        inner = ttk.Frame(bottom)
        inner.pack(fill="x", side="top")

        ttk.Label(inner, text="#Bins").pack(side="left", padx=(4, 6))
        self._bin_scale = ttk.Scale(
            inner, from_=BINS_MIN, to=BINS_MAX, orient="horizontal",
            command=self._on_bins_drag, length=DUAL_LEN_PX
        )
        self._bin_scale.set(float(self.grid_n))
        self._bin_scale.pack(side="left", padx=6, pady=2, fill="x", expand=True)

        ttk.Label(inner, text="Value").pack(side="left", padx=(8, 4))
        self._bins_entry = ttk.Entry(inner, width=6)
        self._bins_entry.insert(0, str(self.grid_n))
        self._bins_entry.pack(side="left", padx=(0, 6))
        self._bins_entry.bind("<Return>", self._on_bins_submit)
        self._bins_entry.bind("<KP_Enter>", self._on_bins_submit)

        # Commit on release → full rebuild
        self._bin_scale.bind("<ButtonRelease-1>", self._on_bins_release)

    # ----- Handlers: dual-range slider, entries, reset, log -----
    def _on_dual_drag(self, key, vlo, vhi):
        """Called while dragging either handle; keep entries + label in sync; redraw (debounced)."""
        if key not in self.range_rows:
            return
        row = self.range_rows[key]
        # clamp to full range & ensure order
        lo_full, hi_full = row["full_lo"], row["full_hi"]
        lo = max(lo_full, min(float(vlo), hi_full))
        hi = max(lo_full, min(float(vhi), hi_full))
        if lo > hi:
            lo, hi = hi, lo
        # push back to widget (keeps display stable)
        if (abs(lo - vlo) > 1e-12) or (abs(hi - vhi) > 1e-12):
            row["scl"].set(lo, hi, fire=False)
        # sync entries + label
        row["ent_lo"].delete(0, "end"); row["ent_lo"].insert(0, _fmt6(lo))
        row["ent_hi"].delete(0, "end"); row["ent_hi"].insert(0, _fmt6(hi))
        row["lbl"].configure(text=f"{row['disp']} [{_fmt6(lo)},{_fmt6(hi)}]")
        self._schedule_redraw()

    def _on_entry_commit(self, key, which):
        if key not in self.range_rows:
            return
        row = self.range_rows[key]
        lo_full, hi_full = row["full_lo"], row["full_hi"]
        # current slider values
        cur_lo, cur_hi = row["scl"].get()
        try:
            if which == "lo":
                v = float(row["ent_lo"].get())
                lo, hi = max(lo_full, min(v, hi_full)), cur_hi
                if lo > hi: lo = hi
            else:
                v = float(row["ent_hi"].get())
                lo, hi = cur_lo, max(lo_full, min(v, hi_full))
                if lo > hi: hi = lo
        except Exception:
            return
        row["scl"].set(lo, hi, fire=False)
        row["lbl"].configure(text=f"{row['disp']} [{_fmt6(lo)},{_fmt6(hi)}]")
        self._schedule_redraw()

    def _on_reset(self, key, lo_full, hi_full):
        if key not in self.range_rows:
            return
        row = self.range_rows[key]
        row["scl"].set(lo_full, hi_full, fire=False)
        row["ent_lo"].delete(0, "end"); row["ent_lo"].insert(0, _fmt6(lo_full))
        row["ent_hi"].delete(0, "end"); row["ent_hi"].insert(0, _fmt6(hi_full))
        row["lbl"].configure(text=f"{row['disp']} [{_fmt6(lo_full)},{_fmt6(hi_full)}]")
        self._schedule_redraw()

    def _on_log_toggle(self, key_type):
        self.log_states[key_type] = not self.log_states[key_type]
        # Full rebuild because display names/ranges change
        self.rebuild_all()

    # ----- Alpha handlers -----
    def _on_alpha_drag(self, v, label_widget, entry_widget):
        v = max(0.1, min(ALPHA_MAX_SCALE, float(v)))
        self.alpha_var.set(v)
        label_widget.configure(text=f"Alpha× {self.alpha_var.get():.2f}")
        entry_widget.delete(0, "end"); entry_widget.insert(0, f"{self.alpha_var.get():.2f}")
        self._schedule_redraw()

    def _on_alpha_submit(self, label_widget, scale_widget, entry_widget):
        try:
            v = float(entry_widget.get())
        except Exception:
            return
        v = max(0.1, min(ALPHA_MAX_SCALE, v))
        self.alpha_var.set(v)
        label_widget.configure(text=f"Alpha× {self.alpha_var.get():.2f}")
        scale_widget.set(self.alpha_var.get())
        self._schedule_redraw()

    def _on_alpha_reset(self, label_widget, scale_widget, entry_widget):
        self.alpha_var.set(1.0)
        label_widget.configure(text=f"Alpha× {self.alpha_var.get():.2f}")
        scale_widget.set(self.alpha_var.get())
        entry_widget.delete(0, "end"); entry_widget.insert(0, f"{self.alpha_var.get():.2f}")
        self._schedule_redraw()

    # ----- Bins handlers (native Tk) -----
    def _on_bins_drag(self, value_str):
        try:
            n = int(round(float(value_str)))
        except Exception:
            return
        n = max(BINS_MIN, min(BINS_MAX, n))
        if n != self.grid_n:
            self.grid_n = n
            self._bins_entry.delete(0, "end")
            self._bins_entry.insert(0, str(self.grid_n))
            # light redraw during drag
            self._schedule_redraw(delay_ms=25)

    def _on_bins_release(self, _event=None):
        # full rebuild so Ratio/Qty ceilings refresh
        self.rebuild_all()

    def _on_bins_submit(self, _event=None):
        try:
            v = int(round(float(self._bins_entry.get())))
        except Exception:
            return
        v = max(BINS_MIN, min(BINS_MAX, v))
        self._bin_scale.set(float(v))
        self.rebuild_all()

    # ----- Redraw debounce -----
    def _schedule_redraw(self, delay_ms=10):
        if self._redraw_after_id is not None:
            try:
                self.after_cancel(self._redraw_after_id)
            except Exception:
                pass
        self._redraw_after_id = self.after(delay_ms, self._do_redraw)

    def _do_redraw(self):
        self._redraw_after_id = None
        self._draw_plot()

    # ================= Plotting (RIGHT PANEL) =================
    def _current_range(self, key):
        """Return (lo, hi) for a given metric key from the dual slider."""
        row = self.range_rows.get(key)
        if not row:
            return None
        return row["scl"].get()

    def _draw_plot(self):
        if self.df is None or self.chr_current is None or not self.range_rows:
            return

        sub_chr = self.df[self.df.iloc[:, self.col_idx_chr].astype(str) == str(self.chr_current)]
        sub = sub_chr[sub_chr.iloc[:, self.col_idx_cb].astype(str).isin(self.cb_selected)] if self.cb_selected else sub_chr

        # Column labels from file
        tcol = self.colnames[self.col_idx_tpm]
        fcol = self.colnames[self.col_idx_fdr]
        fccol = self.colnames[self.col_idx_fc]

        self.plot_ax.clear()
        self.plot_ax.set_xlabel(self._xlabel(tcol))
        self.plot_ax.set_ylabel(self._ylabel(fcol))

        if sub.empty:
            self.plot_ax.set_title("No genes pass filters")
            self.plot_canvas.draw_idle()
            return

        # Transform arrays (for filtering & binning)
        tvals_all = self._tpmt(sub.iloc[:, self.col_idx_tpm].values)
        fvals_all = self._fdrt(sub.iloc[:, self.col_idx_fdr].values)
        fcabs_all = self._fcat(sub.iloc[:, self.col_idx_fc].values)

        # Slider ranges (in transformed space)
        tlo, thi   = self._current_range(tcol)
        flo, fhi   = self._current_range(fcol)
        fclo, fchi = self._current_range(fccol)

        mask = (
            (tvals_all >= tlo) & (tvals_all <= thi) &
            (fvals_all >= flo) & (fvals_all <= fhi) &
            (fcabs_all >= fclo) & (fcabs_all <= fchi)
        )
        sub = sub[mask]
        tvals_tr = tvals_all[mask]
        fvals_tr = fvals_all[mask]

        if sub.empty:
            self.plot_ax.set_title("No genes pass filters")
            self.plot_canvas.draw_idle()
            return

        GRID = self.grid_n

        # Robust axis extents in transformed space
        fmin, fmax = _expand_range(np.min(fvals_tr), np.max(fvals_tr))
        tmin, tmax = _expand_range(np.min(tvals_tr), np.max(tvals_tr))

        # Bin edges
        self.f_bins = np.linspace(fmin, fmax, GRID + 1)
        self.t_bins = np.linspace(tmin, tmax, GRID + 1)

        # Accumulators
        self.up = np.zeros((GRID, GRID))
        self.dn = np.zeros((GRID, GRID))
        self.bin_rows = [[[] for _ in range(GRID)] for _ in range(GRID)]

        fi = np.clip(np.digitize(fvals_tr, self.f_bins) - 1, 0, GRID - 1)
        ti = np.clip(np.digitize(tvals_tr, self.t_bins) - 1, 0, GRID - 1)
        for fy, tx, row in zip(fi, ti, sub.itertuples(index=False)):
            fc = row[self.col_idx_fc]
            if fc > 1:
                self.up[fy, tx] += 1
            elif fc < 1:
                self.dn[fy, tx] += 1
            self.bin_rows[fy][tx].append(row)

        self.tot = self.up + self.dn
        self.ratio = np.where(
            self.up >= self.dn,
            (self.up + PSEUDOCOUNT) / (self.dn + PSEUDOCOUNT),
            - (self.dn + PSEUDOCOUNT) / (self.up + PSEUDOCOUNT)
        )
        ratabs = np.abs(self.ratio)

        # Bin-level filters (Ratio/Qty)
        rlo, rhi = self._current_range("Ratio")
        qlo, qhi = self._current_range("Qty")
        bin_mask = (ratabs >= rlo) & (ratabs <= rhi) & (self.tot >= qlo) & (self.tot <= qhi)

        valid = (self.tot > 0) & bin_mask
        dev_cap = np.percentile(ratabs[valid], DEV_SCALE_PCTL) if np.any(valid) else 1.0
        if dev_cap <= 0:
            dev_cap = 1.0
        intensity = np.clip(ratabs / dev_cap, 0, 1)

        rgba = np.zeros((GRID, GRID, 4))
        rgba[..., 0] = np.where(self.ratio > 1, intensity, 0.0)  # red for up-dominant
        rgba[..., 2] = np.where(self.ratio < 0, intensity, 0.0)  # blue for down-dominant

        maxsup = float(self.tot.max()) if self.tot.size else 0.0
        alpha = (self.tot / maxsup) * float(self.alpha_var.get()) if maxsup > 0 else np.zeros_like(self.tot)
        rgba[..., 3] = np.where(valid, np.clip(alpha, 0, 1), 0.0)

        self.im = self.plot_ax.imshow(
            rgba, origin="lower",
            extent=[tmin, tmax, fmin, fmax],
            aspect="auto", interpolation="nearest"
        )
        self.plot_ax.set_xlim(tmin, tmax)
        self.plot_ax.set_ylim(fmin, fmax)

        title_cb = ",".join(self.cb_selected) if self.cb_selected else "(all)"
        self.plot_ax.set_title(
            f"Chr {self.chr_current} — CB {title_cb} — {GRID} bins — α×{float(self.alpha_var.get()):.2f}"
        )

        # Hover info (tooltip only)
        if self.cursor:
            try:
                self.cursor.remove()
            except Exception:
                pass
        self.cursor = mplcursors.cursor(self.im, hover=True)

        @self.cursor.connect("add")
        def _hover(sel):
            x, y = sel.target
            fy = np.searchsorted(self.f_bins, y) - 1
            tx = np.searchsorted(self.t_bins, x) - 1
            if fy < 0 or fy >= GRID or tx < 0 or tx >= GRID:
                return
            n_up = int(self.up[fy, tx]); n_dn = int(self.dn[fy, tx]); n_tot = int(self.tot[fy, tx])
            r = float(self.ratio[fy, tx]) if n_tot > 0 else float("nan")
            t0, t1 = self.t_bins[tx], self.t_bins[tx + 1]
            f0, f1 = self.f_bins[fy], self.f_bins[fy + 1]
            sel.annotation.set(text=(
                f"{self._xlabel(self.colnames[self.col_idx_tpm])}∈[{t0:.3g},{t1:.3g}]  "
                f"{self._ylabel(self.colnames[self.col_idx_fdr])}∈[{f0:.3g},{f1:.3g}]\n"
                f"Genes={n_tot}  Up={n_up}  Down={n_dn}  Ratio={r:.3g}"
            ))
            sel.annotation.get_bbox_patch().set(fc="white", alpha=0.85)

        # Rectangle selector for export (recreate cleanly)
        if self.selector:
            try:
                self.selector.set_active(False)
                self.selector.disconnect_events()
            except Exception:
                pass
            self.selector = None

        self.selector = RectangleSelector(
            self.plot_ax, self._on_select,
            button=[1], interactive=True,
            minspanx=0.01, minspany=0.01
        )

        self.plot_canvas.draw_idle()

    # ================= Rectangle Export =================
    def _on_select(self, eclick, erelease):
        """Called on mouse release; exports all bins overlapped by the rectangle."""
        x0, y0, x1, y1 = eclick.xdata, eclick.ydata, erelease.xdata, erelease.ydata
        if None in (x0, y0, x1, y1):
            return
        xmin, xmax = sorted([x0, x1])
        ymin, ymax = sorted([y0, y1])

        rows = []
        sel_up = sel_dn = 0
        touched_bins = 0
        GRID = self.grid_n

        for fy in range(GRID):
            for tx in range(GRID):
                t0, t1 = self.t_bins[tx], self.t_bins[tx + 1]
                f0, f1 = self.f_bins[fy], self.f_bins[fy + 1]
                # overlap test
                if (t1 < xmin) or (t0 > xmax) or (f1 < ymin) or (f0 > ymax):
                    continue
                genes_here = self.bin_rows[fy][tx]
                if genes_here:
                    touched_bins += 1
                    sel_up += int(self.up[fy, tx])
                    sel_dn += int(self.dn[fy, tx])
                    rows.extend(genes_here)

        if not rows:
            messagebox.showinfo("No data", "No bins in selection.")
            return

        sel_tot = sel_up + sel_dn
        if sel_up >= sel_dn:
            sel_ratio = (sel_up + PSEUDOCOUNT) / (sel_dn + PSEUDOCOUNT)
        else:
            sel_ratio = - (sel_dn + PSEUDOCOUNT) / (sel_up + PSEUDOCOUNT)

        # Column labels for export table header
        chr_label  = self.colnames[self.col_idx_chr]
        gene_label = self.colnames[self.col_idx_gene]
        cb_label   = self.colnames[self.col_idx_cb]
        fc_label   = self.colnames[self.col_idx_fc]
        t_label    = self.colnames[self.col_idx_tpm]
        fdr_label  = self.colnames[self.col_idx_fdr]

        path = filedialog.asksaveasfilename(
            defaultextension=".tabtxt",
            filetypes=[("Tab-separated", "*.tabtxt"), ("All files", "*.*")]
        )
        if not path:
            return

        # Note: exported ranges are in the *current scale* (log if enabled)
        with open(path, "w", encoding="utf-8") as f:
            # Summary header
            f.write("# Selection summary\n")
            f.write(f"# Chromosome\t{self.chr_current}\n")
            f.write(f"# Cytobands\t{','.join(self.cb_selected) if self.cb_selected else '(all)'}\n")
            f.write(f"# Scale_TPM\t{'log10' if self.log_states['tpm'] else 'raw'}\n")
            f.write(f"# Scale_FDR\t{'-log10' if self.log_states['fdr'] else 'raw'}\n")
            f.write(f"# Scale_|FC|\t{'log10(|·|)' if self.log_states['fc'] else 'raw |·|'}\n")
            f.write(f"# {self._xlabel(t_label)}_range\t[{xmin:.6g},{xmax:.6g}]\n")
            f.write(f"# {self._ylabel(fdr_label)}_range\t[{ymin:.6g},{ymax:.6g}]\n")
            f.write(f"# Touched_bins\t{touched_bins}\n")
            f.write(f"# Genes_total\t{sel_tot}\n")
            f.write(f"# Up\t{sel_up}\n")
            f.write(f"# Down\t{sel_dn}\n")
            f.write(f"# Ratio\t{sel_ratio:.6g}\n\n")

            # Table with actual headers (original, untransformed values)
            f.write(f"{chr_label}\t{gene_label}\t{cb_label}\t{fc_label}\t{t_label}\t{fdr_label}\n")
            for row in rows:
                chrn = row[self.col_idx_chr]
                gene = row[self.col_idx_gene]
                cb   = row[self.col_idx_cb]
                fcv  = row[self.col_idx_fc]
                tval = row[self.col_idx_tpm]
                fval = row[self.col_idx_fdr]
                f.write(f"{chrn}\t{gene}\t{cb}\t{fcv:.6g}\t{tval:.6g}\t{fval:.6g}\n")

        messagebox.showinfo("Exported", f"Saved {len(rows)} rows from {touched_bins} bins to:\n{path}")

if __name__ == "__main__":
    App().mainloop()
