# main_app.py
"""
Main GUI for the IsoSwitch 3rd-Party Sequence Analyzer.

Features:
- Each tool tab has an Enable toggle button and a Run button.
- Inputs tab has Run All which runs ONLY enabled tabs (skips disabled tools).
- Settings are saved/loaded via the main app and include per-tab settings.
- A single shared Logs tab receives output from all tabs.
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from shared_config import APP_NAME, APP_VERSION, AppConfig, load_config, save_config
from shared_utils import ensure_dir, safe_write_text

from tab_inputs import TabInputs
from tab_logs import TabLogs

try:
    from tab_about import TabAbout
except Exception:
    class TabAbout(ttk.Frame):
        def __init__(self, parent):
            super().__init__(parent)
            self.columnconfigure(0, weight=1)
            ttk.Label(self, text="About", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 6))
            ttk.Label(self, text="tab_about.py is missing in this folder.").grid(row=1, column=0, sticky="w", padx=10, pady=(0, 10))


from tab_pfam import TabPFAM
from tab_signalp import TabSignalP
from tab_iupred import TabIUPred
from tab_coding_potential import TabCodingPotential

# NEW
from tab_deeptmhmm import TabDeepTMHMM

# NEW (DeepLoc2 tab)
from tab_deeploc2 import TabDeepLoc2


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("1250x800")
        self.minsize(1100, 680)

        # Active config in memory
        self.cfg = AppConfig()

        # Log queue
        self.log_queue: "queue.Queue[str]" = queue.Queue()

        # Cancel for running tool(s)
        self.cancel_event = threading.Event()
        self.run_thread: threading.Thread | None = None

        # UI
        self._build_ui()
        self._poll_log()

    # ---------------- Logging ----------------
    def log(self, msg: str):
        self.log_queue.put(msg)

    def _poll_log(self):
        try:
            while True:
                m = self.log_queue.get_nowait()
                self.tab_logs.append(m)
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    # ---------------- UI Build ----------------
    def _build_ui(self):
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        nb = ttk.Notebook(self)
        nb.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        # Inputs tab also gets Run All callback
        self.tab_inputs = TabInputs(nb, cfg=self.cfg, run_all_cb=self.run_all_tools)

        self.tab_pfam = TabPFAM(nb, cfg=self.cfg, log_cb=self.log, run_cb=self.run_single_tool)
        self.tab_signalp = TabSignalP(nb, cfg=self.cfg, log_cb=self.log, run_cb=self.run_single_tool)
        self.tab_iupred = TabIUPred(nb, cfg=self.cfg, log_cb=self.log, run_cb=self.run_single_tool)
        self.tab_deeptmhmm = TabDeepTMHMM(nb, cfg=self.cfg, log_cb=self.log, run_cb=self.run_single_tool)

        # NEW (DeepLoc2 tab)
        self.tab_deeploc2 = TabDeepLoc2(nb, cfg=self.cfg, log_cb=self.log, run_cb=self.run_single_tool)

        self.tab_cpat = TabCodingPotential(nb, cfg=self.cfg, log_cb=self.log, run_cb=self.run_single_tool)

        self.tab_logs = TabLogs(nb)
        self.tab_about = TabAbout(nb)

        nb.add(self.tab_inputs, text="Inputs")
        nb.add(self.tab_pfam, text="PFAM")
        nb.add(self.tab_signalp, text="SignalP5")
        nb.add(self.tab_iupred, text="IUPred2A")
        nb.add(self.tab_deeptmhmm, text="DeepTMHMM")

        # NEW
        nb.add(self.tab_deeploc2, text="DeepLoc2")

        nb.add(self.tab_cpat, text="Coding Potential")
        nb.add(self.tab_logs, text="Logs")
        nb.add(self.tab_about, text="About")

        # Bottom bar: config save/load + cancel
        bottom = ttk.Frame(self)
        bottom.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        bottom.columnconfigure(1, weight=1)
        bottom.columnconfigure(4, weight=1)

        ttk.Label(bottom, text="Save settings to (Windows path):").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.var_cfg_save = tk.StringVar(value="")
        ttk.Entry(bottom, textvariable=self.var_cfg_save).grid(row=0, column=1, sticky="ew", padx=(0, 6))
        ttk.Button(bottom, text="Browse", command=self._browse_save_cfg).grid(row=0, column=2, padx=(0, 14))
        ttk.Button(bottom, text="Save Settings", command=self.save_settings_to_path).grid(row=0, column=3, padx=(0, 18))

        ttk.Label(bottom, text="Load settings from (Windows path):").grid(row=0, column=4, sticky="w", padx=(0, 6))
        self.var_cfg_load = tk.StringVar(value="")
        ttk.Entry(bottom, textvariable=self.var_cfg_load).grid(row=0, column=5, sticky="ew", padx=(0, 6))
        ttk.Button(bottom, text="Browse", command=self._browse_load_cfg).grid(row=0, column=6, padx=(0, 14))
        ttk.Button(bottom, text="Load Settings", command=self.load_settings_from_path).grid(row=0, column=7, padx=(0, 18))

        ttk.Button(bottom, text="Cancel running tool", command=self.cancel_run).grid(row=0, column=8, padx=(0, 0))

        # Menu
        menubar = tk.Menu(self)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Save Settings...", command=self._menu_save_settings)
        filemenu.add_command(label="Load Settings...", command=self._menu_load_settings)
        filemenu.add_separator()
        filemenu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=filemenu)
        self.config(menu=menubar)

        self.log("Ready.")

    # ---------------- Config file pickers ----------------
    def _browse_save_cfg(self):
        p = filedialog.asksaveasfilename(
            title="Save settings JSON",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if p:
            self.var_cfg_save.set(p)

    def _browse_load_cfg(self):
        p = filedialog.askopenfilename(
            title="Load settings JSON",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if p:
            self.var_cfg_load.set(p)

    def _menu_save_settings(self):
        self._browse_save_cfg()
        if self.var_cfg_save.get().strip():
            self.save_settings_to_path()

    def _menu_load_settings(self):
        self._browse_load_cfg()
        if self.var_cfg_load.get().strip():
            self.load_settings_from_path()

    # ---------------- Save/Load settings ----------------
    def save_settings_to_path(self):
        path = self.var_cfg_save.get().strip()
        if not path:
            messagebox.showerror("Save settings", "Please choose a Windows path for saving settings.")
            return

        self._apply_all_tabs_to_cfg()

        try:
            ensure_dir(os.path.dirname(path))
            save_config(path, self.cfg)
            self.log(f"[CFG] Saved settings: {path}")
            messagebox.showinfo("Saved", f"Settings saved:\n{path}")
        except Exception as e:
            messagebox.showerror("Save settings failed", str(e))

    def load_settings_from_path(self):
        path = self.var_cfg_load.get().strip()
        if not path:
            messagebox.showerror("Load settings", "Please choose a Windows path to load settings.")
            return
        if not os.path.isfile(path):
            messagebox.showerror("Load settings", "Settings file does not exist.")
            return

        cfg = load_config(path)
        if not cfg:
            messagebox.showerror("Load settings", "Failed to load settings (file invalid or unreadable).")
            return

        self.cfg = cfg
        self._bind_cfg_to_tabs()
        self._refresh_all_tabs_from_cfg()
        self.log(f"[CFG] Loaded settings: {path}")

    def _bind_cfg_to_tabs(self):
        self.tab_inputs.cfg = self.cfg
        for t in (self.tab_pfam, self.tab_signalp, self.tab_iupred, self.tab_deeptmhmm, self.tab_deeploc2, self.tab_cpat):
            t.cfg = self.cfg

    def _refresh_all_tabs_from_cfg(self):
        self.tab_inputs.refresh_from_cfg()
        self.tab_pfam.refresh_from_cfg()
        self.tab_signalp.refresh_from_cfg()
        self.tab_iupred.refresh_from_cfg()
        self.tab_deeptmhmm.refresh_from_cfg()
        self.tab_deeploc2.refresh_from_cfg()
        self.tab_cpat.refresh_from_cfg()

    def _apply_all_tabs_to_cfg(self):
        # Avoid popups during Run All / Save Settings
        try:
            self.tab_inputs.apply_to_cfg(silent=True)
        except TypeError:
            self.tab_inputs.apply_to_cfg()

        self.tab_pfam.save_to_cfg()
        self.tab_signalp.save_to_cfg()
        self.tab_iupred.save_to_cfg()
        self.tab_deeptmhmm.save_to_cfg()
        self.tab_deeploc2.save_to_cfg()
        self.tab_cpat.save_to_cfg()

    # ---------------- Common output dirs (NO Run_YYYY folders) ----------------
    def _common_return_to_r_dir(self) -> str:
        if not self.cfg.out_dir:
            return ""
        return os.path.join(self.cfg.out_dir, "return_to_R")

    def _ensure_common_return_to_r(self):
        if not self.cfg.out_dir:
            return False
        ensure_dir(self.cfg.out_dir)

        return_dir = self._common_return_to_r_dir()
        ensure_dir(return_dir)

        r_script = os.path.join(return_dir, "import_back_into_IsoformSwitchAnalyzeR.R")
        if not os.path.isfile(r_script):
            safe_write_text(
                r_script,
                "# Helper script.\n"
                "# This folder contains the per-tool outputs you should import back into IsoformSwitchAnalyzeR.\n"
                "# The tool files are written as:\n"
                "#   Result_PFAM.txt            (PFAM)\n"
                "#   Result_SignalP.txt         (SignalP5)\n"
                "#   Result_IUPRED2A.txt        (IUPred2A)\n"
                "#   Result_DeepTMHMM.gff3      (DeepTMHMM)  <-- copied/renamed from TMRs.gff3\n"
                "#   Result_DeepLoc2.txt        (DeepLoc2)\n"
                "#   Result_CPAT.txt            (CPAT)\n"
                "# Join by isoform_id as needed.\n"
                "message('Read Result_* files from return_to_R/ and join by isoform_id as needed.')\n",
            )
        return True

    def _tool_enabled(self, tool_tab) -> bool:
        tool_id = getattr(tool_tab, "TOOL_ID", "") or ""
        try:
            t = self.cfg.tool(tool_id)
            return bool(t.get("enabled", True))
        except Exception:
            return True

    # ---------------- Per-tool run ----------------
    def run_single_tool(self, tool_tab):
        if isinstance(tool_tab, str):
            tool_id = tool_tab.strip()
            for t in (
                getattr(self, "tab_pfam", None),
                getattr(self, "tab_signalp", None),
                getattr(self, "tab_iupred", None),
                getattr(self, "tab_deeptmhmm", None),
                getattr(self, "tab_deeploc2", None),
                getattr(self, "tab_cpat", None),
            ):
                if t is not None and getattr(t, "TOOL_ID", "") == tool_id:
                    tool_tab = t
                    break
            else:
                self.log(f"[RUN] ERROR: Unknown tool id: {tool_id}")
                return

        if self.run_thread and self.run_thread.is_alive():
            messagebox.showwarning("Running", "A tool is already running. Cancel it or wait for completion.")
            return

        self._apply_all_tabs_to_cfg()

        if not self.cfg.out_dir:
            messagebox.showerror("Run tool", "Output directory is empty (Inputs tab).")
            return

        if not self._ensure_common_return_to_r():
            messagebox.showerror("Run tool", "Failed to create OutputDir/return_to_R.")
            return

        tool_name = getattr(tool_tab, "TOOL_ID", "tool")

        run_dir = self.cfg.out_dir
        return_dir = self._common_return_to_r_dir()

        self.cancel_event.clear()

        def worker():
            self.log(f"[RUN] Tool: {tool_name}")
            self.log(f"[RUN] OutputDir: {self.cfg.out_dir}")
            self.log(f"[RUN] Common return_to_R: {return_dir}")

            ok = True
            try:
                ok = tool_tab.run_tool(run_dir, return_dir, self.cancel_event)
            except Exception as e:
                ok = False
                self.log(f"[RUN] ERROR: {e}")

            if self.cancel_event.is_set():
                self.log("[RUN] Cancel requested.")
            elif ok:
                self.log("[RUN] Completed successfully.")
                self.log(f"[RUN] Results for R: {return_dir}")
            else:
                self.log("[RUN] Stopped due to error.")

        self.run_thread = threading.Thread(target=worker, daemon=True)
        self.run_thread.start()

    # ---------------- Run All (ENABLED only) ----------------
    def run_all_tools(self):
        if self.run_thread and self.run_thread.is_alive():
            messagebox.showwarning("Running", "A tool is already running. Cancel it or wait for completion.")
            return

        self._apply_all_tabs_to_cfg()

        if not self.cfg.out_dir:
            messagebox.showerror("Run All", "Output directory is empty (Inputs tab).")
            return

        if not self._ensure_common_return_to_r():
            messagebox.showerror("Run All", "Failed to create OutputDir/return_to_R.")
            return

        run_dir = self.cfg.out_dir
        return_dir = self._common_return_to_r_dir()

        # (unchanged pipeline)
        pipeline_tabs = [self.tab_iupred, self.tab_pfam, self.tab_signalp, self.tab_deeptmhmm, self.tab_deeploc2, self.tab_cpat]

        self.cancel_event.clear()

        def worker():
            self.log("[RUNALL] Starting pipeline (ENABLED only): IUPred2A -> PFAM -> SignalP5 -> DeepTMHMM -> DeepLoc2 -> CPAT")
            self.log(f"[RUNALL] OutputDir: {self.cfg.out_dir}")
            self.log(f"[RUNALL] Common return_to_R: {return_dir}")

            all_ok = True
            ran_any = False

            for tool_tab in pipeline_tabs:
                if self.cancel_event.is_set():
                    all_ok = False
                    break

                tool_name = getattr(tool_tab, "TOOL_ID", "tool")

                if not self._tool_enabled(tool_tab):
                    self.log(f"[RUNALL] ---- Tool: {tool_name} ----")
                    self.log(f"[RUNALL] {tool_name}: SKIPPED (disabled)")
                    continue

                ran_any = True
                self.log(f"[RUNALL] ---- Tool: {tool_name} ----")

                ok = True
                try:
                    ok = tool_tab.run_tool(run_dir, return_dir, self.cancel_event)
                except Exception as e:
                    ok = False
                    self.log(f"[RUNALL] ERROR in {tool_name}: {e}")

                if self.cancel_event.is_set():
                    all_ok = False
                    break

                if ok:
                    self.log(f"[RUNALL] {tool_name}: OK")
                else:
                    self.log(f"[RUNALL] {tool_name}: FAILED (stopping pipeline)")
                    all_ok = False
                    break

            if not ran_any and not self.cancel_event.is_set():
                self.log("[RUNALL] Nothing to do: all tools are disabled.")
                all_ok = False

            if self.cancel_event.is_set():
                self.log("[RUNALL] Cancel requested.")
            elif all_ok:
                self.log("[RUNALL] Pipeline completed successfully.")
                self.log(f"[RUNALL] Results for R: {return_dir}")
            else:
                self.log("[RUNALL] Pipeline stopped.")

        self.run_thread = threading.Thread(target=worker, daemon=True)
        self.run_thread.start()

    # ---------------- Cancel ----------------
    def cancel_run(self):
        if self.run_thread and self.run_thread.is_alive():
            self.cancel_event.set()
            self.log("[RUN] Cancel signal sent.")
        else:
            self.log("[RUN] Nothing to cancel.")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
