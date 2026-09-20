import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import math
import os

import matplotlib

# Use TkAgg backend for embedding in Tkinter.
matplotlib.use("TkAgg")

import numpy as np
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.lines import Line2D


class VolcanoGUI:
    """
    Volcano plot GUI with explicit handling of raw P-values and FDR.

    Supported significance inputs:
      - raw P-values (0..1): Benjamini-Hochberg FDR is calculated
      - FDR fraction (0..1): converted to percent
      - FDR percent (0..100): used directly

    IMPORTANT:
      FDR cannot be converted back to the original raw P-values. Therefore,
      when a file contains only FDR values, P-value plotting is unavailable.
    """

    # ----------------------------- GUI COLORS -----------------------------
    COLOR_BG = "#EAF0F6"
    COLOR_PANEL = "#F7F9FC"
    COLOR_PANEL_ALT = "#E4EDF7"
    COLOR_BORDER = "#B8C7D9"
    COLOR_TEXT = "#1F2937"
    COLOR_MUTED = "#5B6777"
    COLOR_LOAD = "#2F6F9F"
    COLOR_UPDATE = "#2E7D32"
    COLOR_FIND = "#6A4C93"
    COLOR_EXPORT = "#8A5A00"
    COLOR_RESET = "#59636E"
    COLOR_UP = "#D62728"
    COLOR_DOWN = "#1F77B4"
    COLOR_NONSIG = "#9AA0A6"
    COLOR_STATUS = "#DDE8F3"

    def __init__(self, master):
        self.master = master
        self.master.title("Volcano Plot GUI - V5")
        self.master.configure(bg=self.COLOR_BG)
        self.master.minsize(1050, 760)

        # ----------------------------- DATA -----------------------------
        self.filepath = None
        self.loaded_df = None
        self.input_sig_header = ""

        self.genes = None
        self.fc = None
        self.source_sig_values = None

        self.p_values = None
        self.fdr_percent = None

        self.total_genes_raw = 0
        self.sig_source_kind = None
        self.detected_sig_text = "No file loaded"

        # ----------------------------- OPTIONS -----------------------------
        # How column 3 should be interpreted.
        self.input_sig_mode = tk.StringVar(value="Auto-detect")

        # What to plot / classify with.
        self.sig_type = tk.StringVar(value="FDR (%)")
        self.sig_threshold_var = tk.StringVar(value="5.0")
        self.fc_threshold_var = tk.StringVar(value="1.0")

        # Log options
        self.log_fc_var = tk.BooleanVar(value=False)
        self.log_sig_var = tk.BooleanVar(value=True)

        # Axes override
        self.override_axes_var = tk.BooleanVar(value=False)
        self.xmin_var = tk.StringVar()
        self.xmax_var = tk.StringVar()
        self.ymin_var = tk.StringVar()
        self.ymax_var = tk.StringVar()

        # Dot style
        self.dot_size_var = tk.StringVar(value="20")
        self.dot_alpha_var = tk.StringVar(value="0.65")

        # Selected gene and search
        self.selected_gene_var = tk.StringVar(value="No gene selected")
        self.search_gene_var = tk.StringVar()

        # File/source information
        self.source_info_var = tk.StringVar(value="No file loaded")

        # Summary
        self.stats_total_var = tk.StringVar(value="Displayed genes: 0 (0.0%)")
        self.stats_up_var = tk.StringVar(value="Upregulated DEGs: 0 (0.0%)")
        self.stats_down_var = tk.StringVar(value="Downregulated DEGs: 0 (0.0%)")
        self.stats_nondeg_var = tk.StringVar(value="Non DEGs: 0 (0.0%)")
        self.stats_notrep_var = tk.StringVar(value="Not represented: 0 (0.0%)")

        # Matplotlib
        self.fig = Figure(figsize=(8.5, 6.2), dpi=100, facecolor="white")
        self.ax = self.fig.add_subplot(111)
        self.canvas = None
        self.scatter = None
        self.highlight_artist = None
        self.annotation = None
        self.toolbar = None

        self._configure_ttk_styles()
        self._build_widgets()
        self._init_plot()

    # ==================================================================
    # GUI BUILDING / STYLE
    # ==================================================================

    def _configure_ttk_styles(self):
        style = ttk.Style(self.master)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "TCombobox",
            fieldbackground="white",
            background="white",
            foreground=self.COLOR_TEXT,
            padding=2,
        )

    def _make_button(self, parent, text, command, bg, width=None):
        kwargs = dict(
            text=text,
            command=command,
            bg=bg,
            fg="white",
            activebackground=bg,
            activeforeground="white",
            relief=tk.FLAT,
            bd=0,
            padx=10,
            pady=5,
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
        )
        if width is not None:
            kwargs["width"] = width
        return tk.Button(parent, **kwargs)

    def _panel(self, parent, text):
        return tk.LabelFrame(
            parent,
            text=text,
            bg=self.COLOR_PANEL,
            fg=self.COLOR_TEXT,
            bd=1,
            relief=tk.GROOVE,
            highlightbackground=self.COLOR_BORDER,
            font=("Segoe UI", 9, "bold"),
            padx=4,
            pady=3,
        )

    def _label(self, parent, text=None, textvariable=None, **kwargs):
        return tk.Label(
            parent,
            text=text,
            textvariable=textvariable,
            bg=kwargs.pop("bg", self.COLOR_PANEL),
            fg=kwargs.pop("fg", self.COLOR_TEXT),
            font=kwargs.pop("font", ("Segoe UI", 9)),
            **kwargs,
        )

    def _entry(self, parent, variable, width=8):
        return tk.Entry(
            parent,
            textvariable=variable,
            width=width,
            bg="white",
            fg=self.COLOR_TEXT,
            insertbackground=self.COLOR_TEXT,
            relief=tk.SOLID,
            bd=1,
            font=("Segoe UI", 9),
        )

    def _checkbutton(self, parent, text, variable, command=None):
        return tk.Checkbutton(
            parent,
            text=text,
            variable=variable,
            command=command,
            bg=self.COLOR_PANEL,
            fg=self.COLOR_TEXT,
            activebackground=self.COLOR_PANEL,
            activeforeground=self.COLOR_TEXT,
            selectcolor="white",
            font=("Segoe UI", 9),
        )

    def _build_widgets(self):
        # ----------------------------- TOP ACTION ROW -----------------------------
        top_frame = tk.Frame(self.master, bg=self.COLOR_BG)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(8, 4))

        self._make_button(top_frame, "Load File", self.load_file, self.COLOR_LOAD).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        self._make_button(top_frame, "Update Plot", self.update_plot, self.COLOR_UPDATE).pack(
            side=tk.LEFT, padx=6
        )
        self._make_button(top_frame, "Save PNG", self.save_png, self.COLOR_EXPORT).pack(
            side=tk.LEFT, padx=6
        )
        self._make_button(top_frame, "Export Table", self.export_table, self.COLOR_EXPORT).pack(
            side=tk.LEFT, padx=6
        )
        self._make_button(top_frame, "Reset View", self.reset_view, self.COLOR_RESET).pack(
            side=tk.LEFT, padx=6
        )

        # ----------------------------- SIGNIFICANCE PANEL -----------------------------
        sig_frame = self._panel(self.master, "Significance")
        sig_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=4)

        self._label(sig_frame, text="Input column type:").grid(
            row=0, column=0, padx=(5, 2), pady=3, sticky="w"
        )
        self.input_sig_combo = ttk.Combobox(
            sig_frame,
            textvariable=self.input_sig_mode,
            values=[
                "Auto-detect",
                "P-value",
                "FDR fraction (0-1)",
                "FDR (%)",
            ],
            state="readonly",
            width=18,
        )
        self.input_sig_combo.grid(row=0, column=1, padx=2, pady=3, sticky="w")
        self.input_sig_combo.bind("<<ComboboxSelected>>", self._on_input_sig_mode_change)

        self._label(sig_frame, text="Plot / classify by:").grid(
            row=0, column=2, padx=(18, 2), pady=3, sticky="w"
        )
        self.sig_type_combo = ttk.Combobox(
            sig_frame,
            textvariable=self.sig_type,
            values=["P-value", "FDR (%)"],
            state="readonly",
            width=11,
        )
        self.sig_type_combo.grid(row=0, column=3, padx=2, pady=3, sticky="w")
        self.sig_type_combo.bind("<<ComboboxSelected>>", self._on_sig_type_change)

        self.sig_label = self._label(sig_frame, text="FDR cutoff (≤ %):")
        self.sig_label.grid(row=0, column=4, padx=(18, 2), pady=3, sticky="w")
        self._entry(sig_frame, self.sig_threshold_var, width=8).grid(
            row=0, column=5, padx=2, pady=3, sticky="w"
        )

        self._label(sig_frame, text="|FC| cutoff ≥").grid(
            row=0, column=6, padx=(18, 2), pady=3, sticky="w"
        )
        self._entry(sig_frame, self.fc_threshold_var, width=8).grid(
            row=0, column=7, padx=2, pady=3, sticky="w"
        )

        source_label = self._label(
            sig_frame,
            textvariable=self.source_info_var,
            fg=self.COLOR_MUTED,
            font=("Segoe UI", 8, "italic"),
        )
        source_label.grid(row=1, column=0, columnspan=8, padx=5, pady=(1, 3), sticky="w")

        # ----------------------------- DISPLAY OPTIONS -----------------------------
        display_frame = self._panel(self.master, "Display options")
        display_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=4)

        self._checkbutton(
            display_frame,
            "Use signed log2(|FC|) on X-axis",
            self.log_fc_var,
            self.update_plot,
        ).grid(row=0, column=0, padx=5, pady=2, sticky="w")

        self._checkbutton(
            display_frame,
            "Use -log10(significance) on Y-axis",
            self.log_sig_var,
            self.update_plot,
        ).grid(row=0, column=1, padx=12, pady=2, sticky="w")

        self._label(display_frame, text="Dot size").grid(
            row=0, column=2, padx=(20, 2), pady=2, sticky="w"
        )
        self._entry(display_frame, self.dot_size_var, width=7).grid(
            row=0, column=3, padx=2, pady=2
        )

        self._label(display_frame, text="Opacity").grid(
            row=0, column=4, padx=(12, 2), pady=2, sticky="w"
        )
        self._entry(display_frame, self.dot_alpha_var, width=7).grid(
            row=0, column=5, padx=2, pady=2
        )

        # ----------------------------- AXES OVERRIDE -----------------------------
        axes_frame = self._panel(self.master, "Axes override")
        axes_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=4)

        self._checkbutton(
            axes_frame,
            "Override axes",
            self.override_axes_var,
            self.update_plot,
        ).grid(row=0, column=0, padx=5, pady=2, sticky="w")

        self._label(axes_frame, text="Xmin").grid(row=0, column=1, padx=(12, 2))
        self._entry(axes_frame, self.xmin_var, width=8).grid(row=0, column=2, padx=2)

        self._label(axes_frame, text="Xmax").grid(row=0, column=3, padx=(12, 2))
        self._entry(axes_frame, self.xmax_var, width=8).grid(row=0, column=4, padx=2)

        self._label(axes_frame, text="Ymin").grid(row=0, column=5, padx=(12, 2))
        self._entry(axes_frame, self.ymin_var, width=8).grid(row=0, column=6, padx=2)

        self._label(axes_frame, text="Ymax").grid(row=0, column=7, padx=(12, 2))
        self._entry(axes_frame, self.ymax_var, width=8).grid(row=0, column=8, padx=2)

        # ----------------------------- SEARCH -----------------------------
        middle_frame = tk.Frame(self.master, bg=self.COLOR_BG)
        middle_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=4)

        tk.Label(
            middle_frame,
            text="Search gene:",
            bg=self.COLOR_BG,
            fg=self.COLOR_TEXT,
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, padx=(0, 2))

        search_entry = tk.Entry(
            middle_frame,
            textvariable=self.search_gene_var,
            width=18,
            bg="white",
            fg=self.COLOR_TEXT,
            relief=tk.SOLID,
            bd=1,
            font=("Segoe UI", 9),
        )
        search_entry.pack(side=tk.LEFT, padx=2)
        search_entry.bind("<Return>", lambda _event: self.search_gene())

        self._make_button(middle_frame, "Find", self.search_gene, self.COLOR_FIND).pack(
            side=tk.LEFT, padx=5
        )

        tk.Label(
            middle_frame,
            textvariable=self.selected_gene_var,
            bg=self.COLOR_BG,
            fg=self.COLOR_FIND,
            font=("Segoe UI", 9, "bold"),
        ).pack(side=tk.LEFT, padx=18)

        # ----------------------------- SUMMARY -----------------------------
        summary_frame = self._panel(self.master, "Summary")
        summary_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=4)

        self._label(summary_frame, textvariable=self.stats_total_var).grid(
            row=0, column=0, sticky="w", padx=5, pady=2
        )
        self._label(
            summary_frame,
            textvariable=self.stats_up_var,
            fg=self.COLOR_UP,
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=1, sticky="w", padx=18, pady=2)

        self._label(
            summary_frame,
            textvariable=self.stats_down_var,
            fg=self.COLOR_DOWN,
            font=("Segoe UI", 9, "bold"),
        ).grid(row=1, column=0, sticky="w", padx=5, pady=2)

        self._label(summary_frame, textvariable=self.stats_nondeg_var).grid(
            row=1, column=1, sticky="w", padx=18, pady=2
        )
        self._label(summary_frame, textvariable=self.stats_notrep_var, fg=self.COLOR_MUTED).grid(
            row=2, column=0, sticky="w", padx=5, pady=2
        )

        # ----------------------------- PLOT -----------------------------
        plot_frame = tk.Frame(self.master, bg="white", bd=1, relief=tk.SUNKEN)
        plot_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(4, 8))

        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.toolbar = NavigationToolbar2Tk(self.canvas, plot_frame, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side=tk.BOTTOM, fill=tk.X)

        self.fig.canvas.mpl_connect("pick_event", self.on_pick)
        self.fig.canvas.mpl_connect("button_press_event", self.on_click_empty)

    # ==================================================================
    # FILE LOADING / SIGNIFICANCE PREPARATION
    # ==================================================================

    def load_file(self):
        filepath = filedialog.askopenfilename(
            title="Select tabulated text file",
            filetypes=[
                ("Tab-delimited files", "*.tabtxt *.tsv *.txt"),
                ("All files", "*.*"),
            ],
        )
        if not filepath:
            return

        try:
            # First read without a header so we can detect one.
            df0 = pd.read_csv(filepath, sep="\t", header=None, dtype=str)
            if df0.shape[1] < 3:
                raise ValueError("File must contain at least 3 columns: gene, FC, significance.")

            first_fc = pd.to_numeric(pd.Series([df0.iloc[0, 1]]), errors="coerce").iloc[0]
            first_sig = pd.to_numeric(pd.Series([df0.iloc[0, 2]]), errors="coerce").iloc[0]
            has_header = pd.isna(first_fc) or pd.isna(first_sig)

            if has_header:
                df = pd.read_csv(filepath, sep="\t", header=0)
            else:
                df = pd.read_csv(filepath, sep="\t", header=None)
                df.columns = ["Gene", "FC", "Significance"] + [
                    f"Column_{i+1}" for i in range(3, df.shape[1])
                ]

            if df.shape[1] < 3:
                raise ValueError("File must contain at least 3 columns.")

            self.filepath = filepath
            self.loaded_df = df.iloc[:, :3].copy()
            self.input_sig_header = str(self.loaded_df.columns[2])
            self._prepare_loaded_data()

        except Exception as exc:
            messagebox.showerror("Error", f"Failed to load file:\n{exc}")

    def _on_input_sig_mode_change(self, event=None):
        if self.loaded_df is not None:
            try:
                self._prepare_loaded_data()
            except Exception as exc:
                messagebox.showerror("Significance input error", str(exc))

    @staticmethod
    def _benjamini_hochberg(p_values):
        """
        Benjamini-Hochberg FDR adjustment.

        NaN values are preserved. Finite p-values must be in [0, 1].
        """
        p = np.asarray(p_values, dtype=float)
        out = np.full(p.shape, np.nan, dtype=float)

        valid = np.isfinite(p)
        pv = p[valid]

        if pv.size == 0:
            return out

        if np.any((pv < 0) | (pv > 1)):
            raise ValueError("Raw P-values must be between 0 and 1.")

        order = np.argsort(pv)
        ranked = pv[order]
        m = ranked.size
        ranks = np.arange(1, m + 1, dtype=float)

        adjusted_sorted = ranked * m / ranks

        # Enforce monotonicity from largest rank to smallest.
        adjusted_sorted = np.minimum.accumulate(adjusted_sorted[::-1])[::-1]
        adjusted_sorted = np.clip(adjusted_sorted, 0.0, 1.0)

        adjusted = np.empty_like(adjusted_sorted)
        adjusted[order] = adjusted_sorted
        out[valid] = adjusted
        return out

    def _detect_sig_kind(self, header, values):
        """
        Returns one of:
            'pvalue', 'fdr_fraction', 'fdr_percent'
        """
        mode = self.input_sig_mode.get()
        if mode == "P-value":
            return "pvalue"
        if mode == "FDR fraction (0-1)":
            return "fdr_fraction"
        if mode == "FDR (%)":
            return "fdr_percent"

        h = str(header).strip().lower()
        finite = values[np.isfinite(values)]
        vmax = float(np.max(finite)) if finite.size else np.nan

        # Strong header-based FDR clues.
        fdr_tokens = (
            "fdr",
            "qvalue",
            "q-value",
            "q_value",
            "padj",
            "p_adj",
            "adjusted p",
            "adj.p",
            "adj_p",
        )
        is_fdr_header = any(token in h for token in fdr_tokens)

        # Raw P-value clues, but avoid "adjusted" variants.
        p_tokens = ("pvalue", "p-value", "p_value", "p value", "pval", "p.val")
        is_p_header = any(token in h for token in p_tokens) and not is_fdr_header

        percent_clue = ("%" in h) or ("percent" in h) or ("pct" in h)

        if is_fdr_header:
            if percent_clue:
                return "fdr_percent"
            if np.isfinite(vmax) and vmax > 1.0:
                return "fdr_percent"
            return "fdr_fraction"

        if is_p_header:
            return "pvalue"

        # Numeric fallback. Values >1 cannot be raw probabilities.
        if np.isfinite(vmax) and vmax > 1.0:
            return "fdr_percent"

        # Ambiguous 0..1 columns default to raw P-value so BH FDR can be computed.
        return "pvalue"

    def _prepare_loaded_data(self):
        if self.loaded_df is None:
            return

        df = self.loaded_df
        self.total_genes_raw = int(df.shape[0])

        genes_all = df.iloc[:, 0].astype(str).to_numpy()
        fc_all = pd.to_numeric(df.iloc[:, 1], errors="coerce").to_numpy(dtype=float)
        sig_all = pd.to_numeric(df.iloc[:, 2], errors="coerce").to_numpy(dtype=float)

        finite_sig = sig_all[np.isfinite(sig_all)]
        if finite_sig.size == 0:
            raise ValueError("No valid significance values were found in column 3.")

        kind = self._detect_sig_kind(self.input_sig_header, finite_sig)

        # Build significance arrays BEFORE filtering on FC. For raw P-values this
        # is important: BH correction must use all tested rows with valid P-values,
        # not only the subset that happens to have a plottable FC.
        p_all = None
        fdr_percent_all = np.full(sig_all.shape, np.nan, dtype=float)

        if kind == "pvalue":
            if np.any((finite_sig < 0) | (finite_sig > 1)):
                raise ValueError(
                    "The significance column is being interpreted as raw P-values, "
                    "but it contains values outside 0..1.\n\n"
                    "Choose 'FDR (%)' or 'FDR fraction (0-1)' as the input column type."
                )
            p_all = sig_all.copy()
            fdr_fraction_all = self._benjamini_hochberg(p_all)
            fdr_percent_all = fdr_fraction_all * 100.0
            detected = "Raw P-value → BH FDR calculated"

            if self.sig_type.get() not in ("P-value", "FDR (%)"):
                self.sig_type.set("FDR (%)")

        elif kind == "fdr_fraction":
            if np.any((finite_sig < 0) | (finite_sig > 1)):
                raise ValueError("FDR fractions must be between 0 and 1.")
            fdr_percent_all = sig_all * 100.0
            detected = "FDR fraction (0–1) → converted to FDR (%)"
            self.sig_type.set("FDR (%)")
            self.sig_threshold_var.set("5.0")

        elif kind == "fdr_percent":
            if np.any((finite_sig < 0) | (finite_sig > 100)):
                raise ValueError("FDR percentages must be between 0 and 100.")
            fdr_percent_all = sig_all.copy()
            detected = "FDR (%) used directly"
            self.sig_type.set("FDR (%)")
            self.sig_threshold_var.set("5.0")

        else:
            raise RuntimeError(f"Unsupported significance kind: {kind}")

        # A plotted row requires a finite FC and a finite significance value.
        valid = np.isfinite(fc_all) & np.isfinite(sig_all) & np.isfinite(fdr_percent_all)

        genes = genes_all[valid]
        fc = fc_all[valid]
        source_sig = sig_all[valid]

        if genes.size == 0:
            raise ValueError("No valid rows found after parsing numeric FC/significance values.")

        p_values = p_all[valid] if p_all is not None else None
        fdr_percent = fdr_percent_all[valid]

        self.genes = genes
        self.fc = fc
        self.source_sig_values = source_sig
        self.p_values = p_values
        self.fdr_percent = fdr_percent
        self.sig_source_kind = kind
        self.detected_sig_text = detected

        dropped = self.total_genes_raw - len(self.genes)
        filename = os.path.basename(self.filepath) if self.filepath else "loaded data"
        self.source_info_var.set(
            f"{filename} | column 3: '{self.input_sig_header}' | "
            f"{detected} | valid rows: {len(self.genes):,} | dropped: {dropped:,}"
        )

        # If source contains only FDR, P-value plotting is impossible.
        if self.p_values is None:
            self.sig_type.set("FDR (%)")
            self.sig_threshold_var.set("5.0")
        else:
            self._sync_sig_label()

        self.selected_gene_var.set(f"Loaded {len(self.genes):,} genes.")
        self.update_plot()

    # ==================================================================
    # SIGNIFICANCE TYPE / THRESHOLDS
    # ==================================================================

    def _sync_sig_label(self):
        if self.sig_type.get() == "P-value":
            self.sig_label.config(text="P-value cutoff (≤):")
        else:
            self.sig_label.config(text="FDR cutoff (≤ %):")

    def _on_sig_type_change(self, event=None):
        requested = self.sig_type.get()

        if requested == "P-value" and self.p_values is None:
            self.sig_type.set("FDR (%)")
            self.sig_threshold_var.set("5.0")
            self._sync_sig_label()
            messagebox.showwarning(
                "Raw P-values unavailable",
                "This file contains FDR values only.\n\n"
                "FDR cannot be converted back to the original raw P-values. "
                "Load a file containing raw P-values if you want to plot P-values.",
            )
            self.update_plot()
            return

        # Use conventional matching default cutoffs when switching statistic.
        if requested == "P-value":
            self.sig_threshold_var.set("0.05")
        else:
            self.sig_threshold_var.set("5.0")

        self._sync_sig_label()
        self.update_plot()

    def _current_sig_values(self):
        if self.sig_type.get() == "P-value":
            if self.p_values is None:
                return None
            return self.p_values
        return self.fdr_percent

    def _validate_thresholds(self):
        # Significance threshold
        try:
            sig_cutoff = float(self.sig_threshold_var.get())
        except ValueError:
            sig_cutoff = 0.05 if self.sig_type.get() == "P-value" else 5.0
            self.sig_threshold_var.set(str(sig_cutoff))

        if self.sig_type.get() == "P-value":
            if not (0.0 <= sig_cutoff <= 1.0):
                raise ValueError("P-value cutoff must be between 0 and 1.")
        else:
            if not (0.0 <= sig_cutoff <= 100.0):
                raise ValueError("FDR cutoff must be between 0 and 100 percent.")

        # Fold-change threshold
        try:
            fc_cutoff = float(self.fc_threshold_var.get())
        except ValueError:
            fc_cutoff = 1.0
            self.fc_threshold_var.set("1.0")

        if fc_cutoff < 0:
            raise ValueError("|FC| cutoff must be ≥ 0.")

        return fc_cutoff, sig_cutoff

    # ==================================================================
    # TRANSFORMS / CLASSIFICATION
    # ==================================================================

    def _transform_fc_for_plot(self, fc_array):
        if not self.log_fc_var.get():
            return np.asarray(fc_array, dtype=float)

        fc_array = np.asarray(fc_array, dtype=float)
        abs_fc = np.clip(np.abs(fc_array), 1e-300, None)
        return np.sign(fc_array) * np.log2(abs_fc)

    def _transform_sig_for_plot(self, sig_array):
        sig_array = np.asarray(sig_array, dtype=float)

        if not self.log_sig_var.get():
            return sig_array

        if self.sig_type.get() == "P-value":
            probability = np.clip(sig_array, 1e-300, 1.0)
        else:
            # FDR is stored internally in percent, convert to fraction for -log10.
            probability = np.clip(sig_array / 100.0, 1e-300, 1.0)

        return -np.log10(probability)

    def _compute_classification_masks(self):
        if self.genes is None:
            return None

        sig_values = self._current_sig_values()
        if sig_values is None:
            return None

        fc_cutoff, sig_cutoff = self._validate_thresholds()

        sig_mask = sig_values <= sig_cutoff
        fc_mask = np.abs(self.fc) >= fc_cutoff
        final_sig_mask = sig_mask & fc_mask

        up_mask = final_sig_mask & (self.fc > 0)
        down_mask = final_sig_mask & (self.fc < 0)
        nonsig_mask = ~final_sig_mask

        return up_mask, down_mask, nonsig_mask, fc_cutoff, sig_cutoff

    # ==================================================================
    # SUMMARY
    # ==================================================================

    def _update_stats_panel(self, up_mask, down_mask, nonsig_mask, x, y):
        total_raw = self.total_genes_raw if self.total_genes_raw is not None else 0
        total_display = len(self.genes) if self.genes is not None else 0
        invalid_count = max(total_raw - total_display, 0)

        if self.genes is None or x is None or y is None:
            self.stats_total_var.set("Displayed genes: 0 (0.0%)")
            self.stats_up_var.set("Upregulated DEGs: 0 (0.0%)")
            self.stats_down_var.set("Downregulated DEGs: 0 (0.0%)")
            self.stats_nondeg_var.set("Non DEGs: 0 (0.0%)")
            self.stats_notrep_var.set("Not represented: 0 (0.0%)")
            return

        finite_xy = np.isfinite(x) & np.isfinite(y)

        if not self.override_axes_var.get():
            visible_mask = finite_xy
        else:
            xlim = self.ax.get_xlim()
            ylim = self.ax.get_ylim()
            visible_mask = (
                finite_xy
                & (x >= xlim[0])
                & (x <= xlim[1])
                & (y >= ylim[0])
                & (y <= ylim[1])
            )

        visible_display = int(np.sum(visible_mask))
        nonvisible_clean = max(total_display - visible_display, 0)

        up_count = int(np.sum(up_mask & visible_mask)) if up_mask is not None else 0
        down_count = int(np.sum(down_mask & visible_mask)) if down_mask is not None else 0
        nondeg_count = int(np.sum(nonsig_mask & visible_mask)) if nonsig_mask is not None else 0

        not_rep = invalid_count + nonvisible_clean
        denom = total_raw if total_raw > 0 else max(total_display, 1)

        def fmt(count):
            return f"{count:,} ({(count / denom) * 100:.1f}%)"

        self.stats_total_var.set(f"Displayed genes: {fmt(visible_display)}")
        self.stats_up_var.set(f"Upregulated DEGs: {fmt(up_count)}")
        self.stats_down_var.set(f"Downregulated DEGs: {fmt(down_count)}")
        self.stats_nondeg_var.set(f"Non DEGs: {fmt(nondeg_count)}")
        self.stats_notrep_var.set(f"Not represented: {fmt(not_rep)}")

    # ==================================================================
    # PLOTTING
    # ==================================================================

    def _init_plot(self):
        self.ax.clear()
        self.ax.set_title("Volcano Plot", fontweight="bold")
        self.ax.set_xlabel("Fold change")
        self.ax.set_ylabel("-log10(significance)")
        self.ax.grid(True, linestyle="--", alpha=0.25)
        self.fig.tight_layout()
        self.canvas.draw()

    def update_plot(self):
        if self.genes is None:
            self._init_plot()
            self._update_stats_panel(None, None, None, None, None)
            return

        try:
            masks_info = self._compute_classification_masks()
            if masks_info is None:
                return
            up_mask, down_mask, nonsig_mask, fc_cutoff, sig_cutoff = masks_info

            sig_values = self._current_sig_values()
            x = self._transform_fc_for_plot(self.fc)
            y = self._transform_sig_for_plot(sig_values)

            try:
                dot_size = float(self.dot_size_var.get())
            except ValueError:
                dot_size = 20.0
                self.dot_size_var.set("20")
            if dot_size <= 0:
                dot_size = 20.0
                self.dot_size_var.set("20")

            try:
                dot_alpha = float(self.dot_alpha_var.get())
            except ValueError:
                dot_alpha = 0.65
                self.dot_alpha_var.set("0.65")
            dot_alpha = max(0.0, min(1.0, dot_alpha))
            self.dot_alpha_var.set(f"{dot_alpha:g}")

            # Clear old selection artists before clearing axes.
            self.highlight_artist = None
            self.annotation = None
            self.selected_gene_var.set("No gene selected")

            self.ax.clear()

            colors = np.full(len(x), self.COLOR_NONSIG, dtype=object)
            colors[up_mask] = self.COLOR_UP
            colors[down_mask] = self.COLOR_DOWN

            self.scatter = self.ax.scatter(
                x,
                y,
                c=colors,
                s=dot_size,
                alpha=dot_alpha,
                picker=5,
                linewidths=0,
                rasterized=False,
            )

            # Axes labels
            if self.log_fc_var.get():
                self.ax.set_xlabel("signed log2(|FC|)")
            else:
                self.ax.set_xlabel("Fold change")

            if self.log_sig_var.get():
                if self.sig_type.get() == "P-value":
                    self.ax.set_ylabel("-log10(P-value)")
                else:
                    self.ax.set_ylabel("-log10(FDR)")
            else:
                if self.sig_type.get() == "P-value":
                    self.ax.set_ylabel("P-value")
                else:
                    self.ax.set_ylabel("FDR (%)")

            stat_name = "P-value" if self.sig_type.get() == "P-value" else "FDR"
            self.ax.set_title(f"Volcano Plot — classified by {stat_name}", fontweight="bold")

            # Fold-change cutoff lines
            if fc_cutoff > 0:
                fc_line_pos = self._transform_fc_for_plot(np.array([fc_cutoff]))[0]
                fc_line_neg = self._transform_fc_for_plot(np.array([-fc_cutoff]))[0]
                self.ax.axvline(
                    fc_line_pos, color="#333333", linestyle="--", linewidth=1, alpha=0.55
                )
                self.ax.axvline(
                    fc_line_neg, color="#333333", linestyle="--", linewidth=1, alpha=0.55
                )

            # Significance cutoff line
            if self.log_sig_var.get():
                if self.sig_type.get() == "P-value":
                    probability_cutoff = max(min(sig_cutoff, 1.0), 1e-300)
                else:
                    probability_cutoff = max(min(sig_cutoff / 100.0, 1.0), 1e-300)
                y_cut = -math.log10(probability_cutoff)
            else:
                y_cut = sig_cutoff

            self.ax.axhline(
                y_cut, color="#333333", linestyle="--", linewidth=1, alpha=0.55
            )

            legend_handles = [
                Line2D(
                    [0], [0], marker="o", color="none", markerfacecolor=self.COLOR_UP,
                    markeredgecolor="none", markersize=7, label="Upregulated DEG"
                ),
                Line2D(
                    [0], [0], marker="o", color="none", markerfacecolor=self.COLOR_DOWN,
                    markeredgecolor="none", markersize=7, label="Downregulated DEG"
                ),
                Line2D(
                    [0], [0], marker="o", color="none", markerfacecolor=self.COLOR_NONSIG,
                    markeredgecolor="none", markersize=7, label="Non DEG"
                ),
            ]
            self.ax.legend(handles=legend_handles, loc="best", frameon=True, fontsize=8)

            self.ax.grid(True, linestyle="--", alpha=0.22)
            self._apply_axes_override()
            self._update_stats_panel(up_mask, down_mask, nonsig_mask, x, y)

            self.fig.tight_layout()
            self.canvas.draw_idle()

        except Exception as exc:
            messagebox.showerror("Plot error", str(exc))

    def _apply_axes_override(self):
        if not self.override_axes_var.get():
            return

        xmin_txt = self.xmin_var.get().strip()
        xmax_txt = self.xmax_var.get().strip()
        if xmin_txt and xmax_txt:
            try:
                xmin = float(xmin_txt)
                xmax = float(xmax_txt)
                if xmin < xmax:
                    self.ax.set_xlim(xmin, xmax)
            except ValueError:
                pass

        ymin_txt = self.ymin_var.get().strip()
        ymax_txt = self.ymax_var.get().strip()
        if ymin_txt and ymax_txt:
            try:
                ymin = float(ymin_txt)
                ymax = float(ymax_txt)
                if ymin < ymax:
                    self.ax.set_ylim(ymin, ymax)
            except ValueError:
                pass

    def reset_view(self):
        self.override_axes_var.set(False)
        self.xmin_var.set("")
        self.xmax_var.set("")
        self.ymin_var.set("")
        self.ymax_var.set("")
        self.update_plot()

    # ==================================================================
    # INTERACTION
    # ==================================================================

    def _format_significance_for_index(self, idx):
        parts = []
        if self.p_values is not None:
            parts.append(f"p={self.p_values[idx]:.3g}")
        if self.fdr_percent is not None:
            parts.append(f"FDR={self.fdr_percent[idx]:.3g}%")
        return ", ".join(parts)

    def on_pick(self, event):
        if self.scatter is None or event.artist != self.scatter:
            return

        ind = event.ind
        if len(ind) == 0:
            return

        idx = int(ind[0])
        gene = self.genes[idx]
        fc_val = self.fc[idx]
        sig_text = self._format_significance_for_index(idx)

        x_val = self._transform_fc_for_plot(np.array([fc_val]))[0]
        current_sig = self._current_sig_values()[idx]
        y_val = self._transform_sig_for_plot(np.array([current_sig]))[0]

        self.selected_gene_var.set(
            f"Selected: {gene}  (FC={fc_val:.3g}, {sig_text})"
        )
        self._highlight_point(idx, x_val, y_val, gene, sig_text, fc_val)

    def _highlight_point(self, idx, x_val, y_val, gene_name, sig_text, fc_val):
        if self.highlight_artist is not None:
            try:
                self.highlight_artist.remove()
            except Exception:
                pass
            self.highlight_artist = None

        if self.annotation is not None:
            try:
                self.annotation.remove()
            except Exception:
                pass
            self.annotation = None

        self.highlight_artist = self.ax.scatter(
            [x_val],
            [y_val],
            s=140,
            facecolors="none",
            edgecolors="black",
            linewidths=1.6,
            zorder=6,
        )

        text = f"{gene_name}\nFC={fc_val:.3g}\n{sig_text}"
        self.annotation = self.ax.annotate(
            text,
            xy=(x_val, y_val),
            xytext=(7, 7),
            textcoords="offset points",
            fontsize=8,
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#777777", alpha=0.9),
            zorder=7,
        )
        self.canvas.draw_idle()

    def on_click_empty(self, event):
        if event.inaxes != self.ax:
            return

        if self.scatter is not None:
            contains, _ = self.scatter.contains(event)
            if contains:
                return

        changed = False

        if self.highlight_artist is not None:
            try:
                self.highlight_artist.remove()
            except Exception:
                pass
            self.highlight_artist = None
            changed = True

        if self.annotation is not None:
            try:
                self.annotation.remove()
            except Exception:
                pass
            self.annotation = None
            changed = True

        if changed:
            self.selected_gene_var.set("No gene selected")
            self.canvas.draw_idle()

    def search_gene(self):
        if self.genes is None:
            messagebox.showwarning("Warning", "Load a file first.")
            return

        query = self.search_gene_var.get().strip()
        if not query:
            return

        genes_lower = [str(g).lower() for g in self.genes]

        try:
            idx = genes_lower.index(query.lower())
        except ValueError:
            messagebox.showinfo("Not found", f"Gene '{query}' not found.")
            return

        fc_val = self.fc[idx]
        current_sig = self._current_sig_values()[idx]
        x_val = self._transform_fc_for_plot(np.array([fc_val]))[0]
        y_val = self._transform_sig_for_plot(np.array([current_sig]))[0]
        sig_text = self._format_significance_for_index(idx)

        self.selected_gene_var.set(
            f"Found: {self.genes[idx]}  (FC={fc_val:.3g}, {sig_text})"
        )
        self._highlight_point(idx, x_val, y_val, self.genes[idx], sig_text, fc_val)

    # ==================================================================
    # EXPORT
    # ==================================================================

    def save_png(self):
        if self.genes is None:
            messagebox.showwarning("Warning", "Load a file first.")
            return

        default_name = "VolcanoPlot.png"
        if self.filepath:
            stem = os.path.splitext(os.path.basename(self.filepath))[0]
            default_name = f"{stem}_VolcanoPlot.png"

        path = filedialog.asksaveasfilename(
            title="Save volcano plot",
            defaultextension=".png",
            initialfile=default_name,
            filetypes=[
                ("PNG image", "*.png"),
                ("PDF vector", "*.pdf"),
                ("SVG vector", "*.svg"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        try:
            self.fig.savefig(path, dpi=300, bbox_inches="tight")
            messagebox.showinfo("Saved", f"Plot saved:\n{path}")
        except Exception as exc:
            messagebox.showerror("Save error", str(exc))

    def export_table(self):
        if self.genes is None:
            messagebox.showwarning("Warning", "Load a file first.")
            return

        try:
            masks_info = self._compute_classification_masks()
            if masks_info is None:
                return

            up_mask, down_mask, nonsig_mask, _fc_cutoff, _sig_cutoff = masks_info

            classification = np.full(len(self.genes), "Non DEG", dtype=object)
            classification[up_mask] = "Upregulated DEG"
            classification[down_mask] = "Downregulated DEG"

            data = {
                "Gene": self.genes,
                "FC": self.fc,
            }

            if self.p_values is not None:
                data["P_value"] = self.p_values

            data["FDR_percent"] = self.fdr_percent
            data["Classification"] = classification

            out_df = pd.DataFrame(data)

            default_name = "VolcanoPlot_classification.tsv"
            if self.filepath:
                stem = os.path.splitext(os.path.basename(self.filepath))[0]
                default_name = f"{stem}_VolcanoPlot_classification.tsv"

            path = filedialog.asksaveasfilename(
                title="Export classified data",
                defaultextension=".tsv",
                initialfile=default_name,
                filetypes=[
                    ("TSV file", "*.tsv"),
                    ("CSV file", "*.csv"),
                    ("Text file", "*.txt"),
                    ("All files", "*.*"),
                ],
            )
            if not path:
                return

            if path.lower().endswith(".csv"):
                out_df.to_csv(path, index=False)
            else:
                out_df.to_csv(path, sep="\t", index=False)

            messagebox.showinfo("Exported", f"Classification table saved:\n{path}")

        except Exception as exc:
            messagebox.showerror("Export error", str(exc))


def main():
    root = tk.Tk()
    VolcanoGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
