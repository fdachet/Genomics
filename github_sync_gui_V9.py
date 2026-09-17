#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Controlled Folder Sync
=============================

Purpose
-------
This Windows GUI treats ONE user-selected folder as the complete Git working
repository. The program does not need a second "source" folder and does not
scan unrelated script locations.

Typical layout:

    Private / real script locations (not used by this program)
                    |
                    |  YOU manually copy only what you want to publish
                    v
        P:\\Github\\Script_R\\      <- selected controlled folder
                    |
                    |  Git repository (.git lives here)
                    v
              GitHub.com

Safety principles
-----------------
* File enumeration is restricted to the selected controlled folder.
* A drive root such as P:\\ is rejected as a controlled folder.
* The GUI never asks for or stores a GitHub account password.
* HTTPS authentication is delegated to Git Credential Manager (browser login).
* Pull uses --ff-only.
* Push checks for remote updates first and refuses to push when GitHub is ahead.
* Deletions require an explicit confirmation before Stage + Commit + Push.
* Connecting an existing GitHub repository to an uncommitted local folder uses
  "git reset --mixed origin/<branch>": the remote history is adopted while the
  files in the selected Windows folder are left untouched.

Requirements
------------
* Python 3.10+ (tested syntax compatible with Python 3.13)
* Git for Windows
* Optional: tkinterdnd2 for drag-and-drop folder support

No third-party package is required for normal Browse-button operation.
"""

from __future__ import annotations

import os
import json
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore
    HAVE_DND = True
except Exception:
    DND_FILES = None
    TkinterDnD = None
    HAVE_DND = False


# -----------------------------------------------------------------------------
# Appearance
# -----------------------------------------------------------------------------
COLOR_BG = "#e8eef5"
COLOR_PANEL = "#f8fafc"
COLOR_NAVY = "#18324a"
COLOR_NAVY_2 = "#254e70"
COLOR_BLUE = "#1976d2"
COLOR_GREEN = "#138a45"
COLOR_GREEN_DARK = "#0f6c38"
COLOR_ORANGE = "#c46a00"
COLOR_RED = "#b42318"
COLOR_PURPLE = "#6f42c1"
COLOR_TEXT = "#17212b"
COLOR_MUTED = "#5f6b76"
COLOR_BORDER = "#aeb8c2"
COLOR_LOG_BG = "#101820"
COLOR_LOG_FG = "#d9e2ec"
COLOR_WHITE = "#ffffff"
COLOR_LIGHT_BLUE = "#dbeafe"
COLOR_LIGHT_GREEN = "#dcfce7"
COLOR_LIGHT_ORANGE = "#ffedd5"
COLOR_LIGHT_RED = "#fee2e2"
COLOR_LIGHT_PURPLE = "#ede9fe"

APP_TITLE = "GitHub Controlled Folder Sync • Version 9"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SETTINGS_FILE = Path(__file__).with_name("github_sync_gui_settings.json")


@dataclass
class CommandResult:
    args: list[str]
    cwd: Optional[str]
    returncode: int
    stdout: str
    stderr: str


@dataclass
class CompareRow:
    status: str
    path: str
    local_size: str
    remote_size: str
    local_modified: str


class GitError(RuntimeError):
    pass


# -----------------------------------------------------------------------------
# Utility functions
# -----------------------------------------------------------------------------
def format_bytes(value: Optional[int]) -> str:
    if value is None:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    number = float(value)
    for unit in units:
        if number < 1000.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(number)} {unit}"
            return f"{number:.2f} {unit}"
        number /= 1000.0
    return f"{value} B"


def format_mtime(path: Path) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(path.stat().st_mtime))
    except OSError:
        return ""


def clean_drop_path(data: str) -> str:
    """Extract one Windows path from a TkDND drop string."""
    text = data.strip()
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1]
    # We intentionally accept only one dropped folder. For an unquoted path,
    # spaces are valid; TkDND normally wraps such a path in braces.
    return text.strip().strip('"')


def is_drive_root(path: Path) -> bool:
    try:
        resolved = path.resolve()
        return resolved.parent == resolved
    except OSError:
        return False


def normalize_repo_url(url: str) -> str:
    return url.strip()


def github_web_url(remote_url: str) -> Optional[str]:
    url = remote_url.strip()
    if not url:
        return None
    if url.startswith("https://github.com/"):
        if url.endswith(".git"):
            url = url[:-4]
        return url
    match = re.match(r"git@github\.com:(.+?)(?:\.git)?$", url)
    if match:
        return "https://github.com/" + match.group(1)
    return None


# -----------------------------------------------------------------------------
# Main application
# -----------------------------------------------------------------------------
BaseTk = TkinterDnD.Tk if HAVE_DND else tk.Tk


class GitHubSyncApp(BaseTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1450x900")
        self.minsize(1180, 760)
        self.configure(bg=COLOR_BG)

        self._ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._busy = False
        self._last_remote_branch: Optional[str] = None

        self.git_exe_var = tk.StringVar(value="")
        default_controlled = r"P:\Github" if os.name == "nt" and Path(r"P:\Github").is_dir() else ""
        self.repo_folder_var = tk.StringVar(value=default_controlled)
        self.remote_url_var = tk.StringVar(value="")
        self.favorite_repo_urls: list[str] = []
        self._load_settings()
        self.commit_message_var = tk.StringVar(value="Update scripts")
        self.author_name_var = tk.StringVar(value="")
        self.author_email_var = tk.StringVar(value="")
        self.git_status_var = tk.StringVar(value="Git: detecting...")
        self.auth_status_var = tk.StringVar(value="GitHub: checking sign-in...")
        self.github_root_var = tk.StringVar(value="GitHub root: not detected")
        self.local_root_var = tk.StringVar(value=f"Controlled local root: {default_controlled or 'not selected'}")
        self.github_username: Optional[str] = None
        self.remote_state_var = tk.StringVar(value="Remote state: not checked")
        self.main_status_var = tk.StringVar(value="Ready")
        self.ownership_status_var = tk.StringVar(value="Repository ownership: not checked")
        self.show_identical_var = tk.BooleanVar(value=False)

        self._configure_styles()
        self._build_ui()
        self.repo_folder_var.trace_add("write", self._on_local_root_changed)
        self.after(100, self._drain_ui_queue)
        self.after(200, self.detect_git)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=COLOR_BG)
        style.configure("Panel.TFrame", background=COLOR_PANEL)
        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT)
        style.configure("Panel.TLabel", background=COLOR_PANEL, foreground=COLOR_TEXT)
        style.configure("Muted.TLabel", background=COLOR_PANEL, foreground=COLOR_MUTED)
        style.configure("Header.TLabel", background=COLOR_NAVY, foreground=COLOR_WHITE,
                        font=("Segoe UI", 16, "bold"))
        style.configure("SubHeader.TLabel", background=COLOR_NAVY, foreground="#d7e5f2",
                        font=("Segoe UI", 9))
        style.configure("Section.TLabelframe", background=COLOR_PANEL,
                        bordercolor=COLOR_BORDER, relief="solid")
        style.configure("Section.TLabelframe.Label", background=COLOR_BG,
                        foreground=COLOR_NAVY, font=("Segoe UI", 10, "bold"))
        style.configure("TButton", font=("Segoe UI", 9), padding=(10, 6))
        style.configure("Blue.TButton", background=COLOR_BLUE, foreground=COLOR_WHITE)
        style.map("Blue.TButton", background=[("active", "#145ea8"), ("disabled", "#9bb9d6")])
        style.configure("Green.TButton", background=COLOR_GREEN, foreground=COLOR_WHITE)
        style.map("Green.TButton", background=[("active", COLOR_GREEN_DARK), ("disabled", "#9bc6aa")])
        style.configure("Orange.TButton", background=COLOR_ORANGE, foreground=COLOR_WHITE)
        style.map("Orange.TButton", background=[("active", "#9a5200")])
        style.configure("Red.TButton", background=COLOR_RED, foreground=COLOR_WHITE)
        style.map("Red.TButton", background=[("active", "#8f1b13")])
        style.configure("Treeview", rowheight=24, font=("Segoe UI", 9),
                        background=COLOR_WHITE, fieldbackground=COLOR_WHITE,
                        foreground=COLOR_TEXT)
        style.configure("Treeview.Heading", background=COLOR_NAVY, foreground=COLOR_WHITE,
                        font=("Segoe UI", 9, "bold"))
        style.map("Treeview.Heading", background=[("active", COLOR_NAVY_2)])
        style.configure("Horizontal.TProgressbar", thickness=12)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = tk.Frame(self, bg=COLOR_NAVY, padx=14, pady=8)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ttk.Label(header, text=APP_TITLE, style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Controlled Windows folder ↔ GitHub repository", style="SubHeader.TLabel").grid(row=1, column=0, sticky="w")

        main = ttk.Panedwindow(self, orient="horizontal")
        main.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)

        # Left 30% is a vertically scrollable control panel.  The Canvas is
        # necessary because ttk.Frame itself cannot scroll.  Mouse-wheel
        # scrolling is active while the pointer is anywhere over this panel.
        left_shell = ttk.Frame(main, style="Panel.TFrame")
        right = ttk.Panedwindow(main, orient="vertical")
        main.add(left_shell, weight=3)
        main.add(right, weight=7)

        left_shell.grid_rowconfigure(0, weight=1)
        left_shell.grid_columnconfigure(0, weight=1)
        left_canvas = tk.Canvas(left_shell, bg=COLOR_PANEL, highlightthickness=0, borderwidth=0)
        left_scrollbar = ttk.Scrollbar(left_shell, orient="vertical", command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scrollbar.set)
        left_canvas.grid(row=0, column=0, sticky="nsew")
        left_scrollbar.grid(row=0, column=1, sticky="ns")

        left = ttk.Frame(left_canvas, style="Panel.TFrame", padding=8)
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")
        left.grid_columnconfigure(0, weight=1)

        def _update_left_scrollregion(_event=None):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))

        def _fit_left_width(event):
            # Keep the embedded control frame exactly as wide as the visible
            # canvas so controls resize with the 30% pane.
            left_canvas.itemconfigure(left_window, width=max(1, event.width))

        def _left_mousewheel(event):
            # Windows / macOS Tk supplies event.delta.  Linux Tk commonly uses
            # Button-4/Button-5, handled below as well.
            if getattr(event, "num", None) == 4:
                units = -1
            elif getattr(event, "num", None) == 5:
                units = 1
            else:
                delta = getattr(event, "delta", 0)
                if delta == 0:
                    return "break"
                units = -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
            left_canvas.yview_scroll(units, "units")
            return "break"

        def _bind_left_wheel(_event=None):
            left_canvas.bind_all("<MouseWheel>", _left_mousewheel)
            left_canvas.bind_all("<Button-4>", _left_mousewheel)
            left_canvas.bind_all("<Button-5>", _left_mousewheel)

        def _unbind_left_wheel(_event=None):
            left_canvas.unbind_all("<MouseWheel>")
            left_canvas.unbind_all("<Button-4>")
            left_canvas.unbind_all("<Button-5>")

        left.bind("<Configure>", _update_left_scrollregion)
        left_canvas.bind("<Configure>", _fit_left_width)
        left_shell.bind("<Enter>", _bind_left_wheel)
        left_shell.bind("<Leave>", _unbind_left_wheel)

        # --- Left 30%: account, repository and actions ---
        tools = ttk.LabelFrame(left, text="Git and GitHub account", style="Section.TLabelframe", padding=8)
        tools.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        tools.grid_columnconfigure(0, weight=1)
        self.git_badge = tk.Label(tools, textvariable=self.git_status_var, bg=COLOR_ORANGE, fg=COLOR_WHITE, font=("Segoe UI",9,"bold"), padx=8, pady=5)
        self.git_badge.grid(row=0, column=0, sticky="ew", pady=(0,4))
        self.auth_badge = tk.Label(tools, textvariable=self.auth_status_var, bg=COLOR_ORANGE, fg=COLOR_WHITE, font=("Segoe UI",9,"bold"), padx=8, pady=5)
        self.auth_badge.grid(row=1, column=0, sticky="ew", pady=2)
        tk.Label(tools, textvariable=self.github_root_var, bg=COLOR_PANEL, fg=COLOR_NAVY, anchor="w", justify="left", wraplength=390).grid(row=2,column=0,sticky="ew",pady=2)
        row = ttk.Frame(tools, style="Panel.TFrame"); row.grid(row=3,column=0,sticky="ew",pady=(5,0))
        for i in range(3): row.grid_columnconfigure(i,weight=1)
        ttk.Button(row,text="Detect Git",command=self.detect_git).grid(row=0,column=0,sticky="ew",padx=(0,2))
        ttk.Button(row,text="Sign-in",style="Green.TButton",command=self.github_sign_in).grid(row=0,column=1,sticky="ew",padx=2)
        ttk.Button(row,text="Refresh login",command=self.refresh_github_auth_status).grid(row=0,column=2,sticky="ew",padx=(2,0))
        row2=ttk.Frame(tools,style="Panel.TFrame"); row2.grid(row=4,column=0,sticky="ew",pady=(4,0)); row2.grid_columnconfigure(0,weight=1); row2.grid_columnconfigure(1,weight=1)
        ttk.Button(row2,text="Browse git.exe",command=self.browse_git).grid(row=0,column=0,sticky="ew",padx=(0,2))
        ttk.Button(row2,text="Install Git",style="Orange.TButton",command=self.open_git_download).grid(row=0,column=1,sticky="ew",padx=(2,0))

        repo = ttk.LabelFrame(left, text="Controlled folder and repository", style="Section.TLabelframe", padding=8)
        repo.grid(row=1,column=0,sticky="ew",pady=(0,7)); repo.grid_columnconfigure(0,weight=1)
        ttk.Label(repo,text="Controlled local folder:",style="Panel.TLabel").grid(row=0,column=0,sticky="w")
        self.repo_entry=ttk.Entry(repo,textvariable=self.repo_folder_var); self.repo_entry.grid(row=1,column=0,sticky="ew",pady=(2,3))
        ttk.Button(repo,text="Browse...",command=self.browse_repo_folder).grid(row=2,column=0,sticky="ew",pady=(0,7))
        ttk.Label(repo,text="GitHub repository HTTPS URL:",style="Panel.TLabel").grid(row=3,column=0,sticky="w")
        self.remote_url_combo=ttk.Combobox(repo,textvariable=self.remote_url_var,values=self.favorite_repo_urls); self.remote_url_combo.grid(row=4,column=0,sticky="ew",pady=(2,3))
        fav=ttk.Frame(repo,style="Panel.TFrame"); fav.grid(row=5,column=0,sticky="ew"); fav.grid_columnconfigure(0,weight=1); fav.grid_columnconfigure(1,weight=1)
        ttk.Button(fav,text="★ Favorite",command=self.add_repo_favorite).grid(row=0,column=0,sticky="ew",padx=(0,2))
        ttk.Button(fav,text="Remove favorite",command=self.remove_repo_favorite).grid(row=0,column=1,sticky="ew",padx=(2,0))
        ttk.Button(repo,text="Initialize / Connect",style="Blue.TButton",command=self.initialize_or_connect).grid(row=6,column=0,sticky="ew",pady=(6,0))
        self.ownership_label=tk.Label(repo,textvariable=self.ownership_status_var,bg=COLOR_PANEL,fg=COLOR_MUTED,anchor="w",justify="left",wraplength=390); self.ownership_label.grid(row=7,column=0,sticky="ew",pady=(6,2))
        own=ttk.Frame(repo,style="Panel.TFrame"); own.grid(row=8,column=0,sticky="ew"); own.grid_columnconfigure(0,weight=1); own.grid_columnconfigure(1,weight=1)
        ttk.Button(own,text="Check ownership",command=self.check_repo_ownership).grid(row=0,column=0,sticky="ew",padx=(0,2))
        ttk.Button(own,text="Trust this folder + subfolders",style="Orange.TButton",command=self.trust_selected_safe_directory).grid(row=0,column=1,sticky="ew",padx=(2,0))

        ident=ttk.LabelFrame(left,text="Commit identity",style="Section.TLabelframe",padding=8); ident.grid(row=2,column=0,sticky="ew",pady=(0,7)); ident.grid_columnconfigure(0,weight=1)
        ttk.Label(ident,text="Author name:",style="Panel.TLabel").grid(row=0,column=0,sticky="w"); ttk.Entry(ident,textvariable=self.author_name_var).grid(row=1,column=0,sticky="ew")
        ttk.Label(ident,text="Author email:",style="Panel.TLabel").grid(row=2,column=0,sticky="w",pady=(4,0)); ttk.Entry(ident,textvariable=self.author_email_var).grid(row=3,column=0,sticky="ew")
        ttk.Button(ident,text="Save identity for this repository only",command=self.save_local_identity).grid(row=4,column=0,sticky="ew",pady=(5,0))

        actions=ttk.LabelFrame(left,text="Actions",style="Section.TLabelframe",padding=8); actions.grid(row=3,column=0,sticky="ew",pady=(0,7)); actions.grid_columnconfigure(0,weight=1)
        self.action_buttons=[]
        fetch_btn=ttk.Button(actions,text="Fetch (Preview)",style="Blue.TButton",command=self.compare_with_github); fetch_btn.grid(row=0,column=0,sticky="ew",pady=2); self.action_buttons.append(fetch_btn)
        self.show_identical_check=ttk.Checkbutton(actions,text="Show unchanged files",variable=self.show_identical_var,command=self.compare_with_github); self.show_identical_check.grid(row=1,column=0,sticky="w",pady=(3,7))
        pull_btn=ttk.Button(actions,text="Pull from GitHub",style="Orange.TButton",command=self.pull_remote); pull_btn.grid(row=2,column=0,sticky="ew",pady=2); self.action_buttons.append(pull_btn)
        self.upload_button=ttk.Button(actions,text="Push to GitHub",style="Green.TButton",command=self.stage_commit_push); self.upload_button.grid(row=3,column=0,sticky="ew",pady=2)
        openrow=ttk.Frame(actions,style="Panel.TFrame"); openrow.grid(row=4,column=0,sticky="ew",pady=(7,0)); openrow.grid_columnconfigure(0,weight=1); openrow.grid_columnconfigure(1,weight=1)
        ttk.Button(openrow,text="Open local folder",command=self.open_repo_folder).grid(row=0,column=0,sticky="ew",padx=(0,2))
        ttk.Button(openrow,text="Open GitHub",command=self.open_github_page).grid(row=0,column=1,sticky="ew",padx=(2,0))
        repair_btn=ttk.Button(actions,text="Repair stale Git paths",command=self.repair_stale_git_paths); repair_btn.grid(row=5,column=0,sticky="ew",pady=(7,0)); self.action_buttons.append(repair_btn)

        # --- Right 70%, upper half: comparison ---
        compare_frame=ttk.LabelFrame(right,text="Local folder compared with GitHub",style="Section.TLabelframe",padding=4)
        compare_frame.grid_rowconfigure(1,weight=1); compare_frame.grid_columnconfigure(0,weight=1)
        self.compare_summary_var=tk.StringVar(value="Click Fetch (Preview) to compare the controlled folder with GitHub.")
        ttk.Label(compare_frame,textvariable=self.compare_summary_var,style="Panel.TLabel").grid(row=0,column=0,sticky="ew",padx=4,pady=4)
        columns=("status","path","local_size","remote_size","local_modified")
        self.tree=ttk.Treeview(compare_frame,columns=columns,show="headings")
        for col,text in [("status","Status"),("path","Relative path"),("local_size","Local size"),("remote_size","GitHub size"),("local_modified","Local modified")]: self.tree.heading(col,text=text)
        self.tree.column("status",width=155,stretch=False,anchor="center"); self.tree.column("path",width=650,stretch=True); self.tree.column("local_size",width=100,stretch=False,anchor="e"); self.tree.column("remote_size",width=100,stretch=False,anchor="e"); self.tree.column("local_modified",width=150,stretch=False,anchor="center")
        ys=ttk.Scrollbar(compare_frame,orient="vertical",command=self.tree.yview); xs=ttk.Scrollbar(compare_frame,orient="horizontal",command=self.tree.xview); self.tree.configure(yscrollcommand=ys.set,xscrollcommand=xs.set)
        self.tree.grid(row=1,column=0,sticky="nsew"); ys.grid(row=1,column=1,sticky="ns"); xs.grid(row=2,column=0,sticky="ew")
        for tag,bg in [("LOCAL ONLY",COLOR_LIGHT_BLUE),("REMOTE ONLY",COLOR_LIGHT_ORANGE),("DIFFERENT",COLOR_LIGHT_RED),("IDENTICAL",COLOR_LIGHT_GREEN),("ERROR",COLOR_LIGHT_PURPLE)]: self.tree.tag_configure(tag,background=bg)

        # --- Right 70%, lower half: activity log ---
        log_frame=ttk.LabelFrame(right,text="Activity log",style="Section.TLabelframe",padding=4); log_frame.grid_rowconfigure(0,weight=1); log_frame.grid_columnconfigure(0,weight=1)
        self.log_text=tk.Text(log_frame,bg=COLOR_LOG_BG,fg=COLOR_LOG_FG,insertbackground=COLOR_WHITE,wrap="none",font=("Consolas",9))
        ly=ttk.Scrollbar(log_frame,orient="vertical",command=self.log_text.yview); lx=ttk.Scrollbar(log_frame,orient="horizontal",command=self.log_text.xview); self.log_text.configure(yscrollcommand=ly.set,xscrollcommand=lx.set)
        self.log_text.grid(row=0,column=0,sticky="nsew"); ly.grid(row=0,column=1,sticky="ns"); lx.grid(row=1,column=0,sticky="ew")
        for tag,fg in [("INFO","#c9d6e2"),("OK","#6ee7a0"),("WARN","#ffd166"),("ERROR","#ff7b72"),("CMD","#8ecae6")]: self.log_text.tag_configure(tag,foreground=fg)
        right.add(compare_frame,weight=1); right.add(log_frame,weight=1)

        footer=ttk.Frame(left,style="Panel.TFrame"); footer.grid(row=4,column=0,sticky="sew",pady=(4,0)); footer.grid_columnconfigure(0,weight=1)
        self.progress=ttk.Progressbar(footer,mode="indeterminate"); self.progress.grid(row=0,column=0,sticky="ew")
        ttk.Label(footer,textvariable=self.main_status_var,style="Panel.TLabel").grid(row=1,column=0,sticky="w",pady=(3,0))

        if HAVE_DND:
            try:
                self.repo_entry.drop_target_register(DND_FILES); self.repo_entry.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

        # Initial 30/70 and 50/50 sash positions after geometry is realized.
        def set_sashes():
            try:
                main.sashpos(0, int(main.winfo_width()*0.30))
                right.sashpos(0, int(right.winfo_height()*0.50))
            except Exception:
                pass
        self.after(250,set_sashes)

    def _drain_ui_queue(self) -> None:
        """Apply worker-thread results safely on Tk's main UI thread."""
        try:
            while True:
                kind, payload = self._ui_queue.get_nowait()
                if kind == "log":
                    message, level = payload  # type: ignore[misc]
                    self._append_log(message, level)
                elif kind == "status":
                    self.main_status_var.set(str(payload))
                elif kind == "busy":
                    self._set_busy_ui(bool(payload))
                elif kind == "remote_state":
                    self.remote_state_var.set(str(payload))
                elif kind == "auth_state":
                    self.auth_status_var.set(str(payload))
                elif kind == "auth_details":
                    username, accounts = payload  # type: ignore[misc]
                    self._apply_auth_details(username, accounts)
                elif kind == "ownership_state":
                    text, state = payload  # type: ignore[misc]
                    self.ownership_status_var.set(str(text))
                    color = {"ok": COLOR_GREEN_DARK, "warn": COLOR_ORANGE,
                             "error": COLOR_RED}.get(str(state), COLOR_MUTED)
                    self.ownership_label.configure(fg=color)
                elif kind == "compare_rows":
                    self._populate_compare_rows(payload)  # type: ignore[arg-type]
                elif kind == "compare_summary":
                    self.compare_summary_var.set(str(payload))
                elif kind == "identity":
                    name, email = payload  # type: ignore[misc]
                    self.author_name_var.set(name)
                    self.author_email_var.set(email)
                elif kind == "message_info":
                    title, text = payload  # type: ignore[misc]
                    messagebox.showinfo(title, text, parent=self)
                elif kind == "message_warn":
                    title, text = payload  # type: ignore[misc]
                    messagebox.showwarning(title, text, parent=self)
                elif kind == "message_error":
                    title, text = payload  # type: ignore[misc]
                    messagebox.showerror(title, text, parent=self)
        except queue.Empty:
            pass
        self.after(100, self._drain_ui_queue)

    def log(self, message: str, level: str = "INFO") -> None:
        self._ui_queue.put(("log", (message, level)))

    def _append_log(self, message: str, level: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{stamp}] {message}\n", level)
        self.log_text.see("end")

    def set_status(self, text: str) -> None:
        self._ui_queue.put(("status", text))

    def _set_busy_ui(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self.progress.start(12)
            for button in self.action_buttons:
                button.state(["disabled"])
            self.upload_button.state(["disabled"])
        else:
            self.progress.stop()
            for button in self.action_buttons:
                button.state(["!disabled"])
            self.upload_button.state(["!disabled"])

    def run_async(self, label: str, func: Callable[[], None]) -> None:
        if self._busy:
            messagebox.showinfo("Operation in progress", "Please wait for the current operation to finish.", parent=self)
            return

        self._ui_queue.put(("busy", True))
        self.set_status(label)

        def worker() -> None:
            try:
                func()
            except GitError as exc:
                self.log(str(exc), "ERROR")
                self._ui_queue.put(("message_error", ("Git operation failed", str(exc))))
            except Exception as exc:
                self.log(f"Unexpected error: {exc}", "ERROR")
                self._ui_queue.put(("message_error", ("Unexpected error", str(exc))))
            finally:
                self.set_status("Ready")
                self._ui_queue.put(("busy", False))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Git detection / execution
    # ------------------------------------------------------------------
    def detect_git(self) -> None:
        candidates: list[Path] = []
        found = shutil.which("git")
        if found:
            candidates.append(Path(found))

        env_program_files = os.environ.get("ProgramFiles")
        env_program_files_x86 = os.environ.get("ProgramFiles(x86)")
        env_local = os.environ.get("LOCALAPPDATA")
        for base in (env_program_files, env_program_files_x86):
            if base:
                candidates.extend([
                    Path(base) / "Git" / "cmd" / "git.exe",
                    Path(base) / "Git" / "bin" / "git.exe",
                ])
        if env_local:
            candidates.extend([
                Path(env_local) / "Programs" / "Git" / "cmd" / "git.exe",
                Path(env_local) / "Programs" / "Git" / "bin" / "git.exe",
            ])

        # If the user previously browsed to an executable during this run, try it first.
        current = self.git_exe_var.get().strip()
        if current:
            candidates.insert(0, Path(current))

        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate).lower()
            if key in seen:
                continue
            seen.add(key)
            if candidate.is_file():
                result = self._run_raw([str(candidate), "--version"], cwd=None, check=False)
                if result.returncode == 0:
                    self.git_exe_var.set(str(candidate))
                    version = result.stdout.strip() or "Git detected"
                    self.git_status_var.set(version)
                    self.git_badge.configure(bg=COLOR_GREEN)
                    self.log(f"Detected {version}: {candidate}", "OK")
                    self.after(100, self.refresh_github_auth_status)
                    return

        self.git_exe_var.set("")
        self.git_status_var.set("Git: NOT FOUND")
        self.git_badge.configure(bg=COLOR_RED)
        self.log("Git was not found. Install Git for Windows or browse to git.exe.", "ERROR")

    def browse_git(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Select git.exe",
            filetypes=[("Git executable", "git.exe"), ("Executable files", "*.exe"), ("All files", "*.*")],
        )
        if not path:
            return
        result = self._run_raw([path, "--version"], cwd=None, check=False)
        if result.returncode != 0:
            messagebox.showerror("Invalid Git executable", result.stderr or "The selected file did not run as Git.", parent=self)
            return
        self.git_exe_var.set(path)
        self.git_status_var.set(result.stdout.strip())
        self.git_badge.configure(bg=COLOR_GREEN)
        self.log(f"Git executable selected: {path}", "OK")
        self.after(100, self.refresh_github_auth_status)

    # ------------------------------------------------------------------
    # Windows filename normalization before repository operations
    # ------------------------------------------------------------------
    def _normalize_spaces_in_controlled_tree(self, folder: Path) -> int:
        """Recursively replace spaces with underscores inside the controlled tree.

        The .git metadata directory is NEVER traversed or renamed. Renames are
        performed bottom-up so parent directory renames cannot invalidate paths
        that still need processing. A collision aborts before that individual
        rename; existing files are never overwritten.
        """
        folder = folder.resolve()
        if not folder.is_dir():
            return 0

        # The controlled root itself is intentionally stable because .git lives
        # directly inside it.  Everything below it is normalized automatically.
        if " " in folder.name:
            raise GitError(
                "The selected controlled ROOT folder itself contains spaces:\n\n"
                f"{folder}\n\n"
                "For safety the GUI does not rename the repository root while it is open. "
                "Rename that one root folder manually once (replace spaces with underscores), "
                "then select it again. All files/folders BELOW it are normalized automatically."
            )

        planned: list[tuple[Path, Path]] = []
        # Build a complete bottom-up plan first, so collisions are detected before
        # any filesystem change is made.
        for current, dirs, files in os.walk(folder, topdown=False):
            current_path = Path(current)
            # Never touch Git's private metadata. With bottom-up os.walk(),
            # pruning `dirs` alone is too late, so explicitly skip .git and every
            # descendant that has already been yielded.
            git_private = folder / ".git"
            if current_path == git_private or git_private in current_path.parents:
                continue
            dirs[:] = [d for d in dirs if d != ".git"]
            for name in files:
                if " " in name:
                    old = current_path / name
                    new = current_path / name.replace(" ", "_")
                    planned.append((old, new))
            for name in dirs:
                if name == ".git":
                    continue
                if " " in name:
                    old = current_path / name
                    new = current_path / name.replace(" ", "_")
                    planned.append((old, new))

        # Windows is case-insensitive in the normal configuration. Detect both
        # actual targets and two source names converging on the same target.
        target_keys: dict[str, Path] = {}
        source_keys = {str(old).lower() for old, _ in planned}
        for old, new in planned:
            key = str(new).lower()
            previous = target_keys.get(key)
            if previous is not None and str(previous).lower() != str(old).lower():
                raise GitError(
                    "Space-to-underscore rename collision detected. Nothing was overwritten.\n\n"
                    f"Both names would become:\n{new}"
                )
            target_keys[key] = old
            if new.exists() and str(new).lower() not in source_keys and str(new).lower() != str(old).lower():
                raise GitError(
                    "Space-to-underscore rename collision detected. Nothing was overwritten.\n\n"
                    f"Existing target:\n{new}\n\nSource that would be renamed:\n{old}"
                )

        renamed = 0
        for old, new in planned:
            if not old.exists():
                # A parent may already have been renamed only if the plan order was
                # altered; bottom-up ordering normally keeps every old path valid.
                continue
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)
            renamed += 1
            try:
                rel_old = old.relative_to(folder)
                rel_new = new.relative_to(folder)
                self.log(f"Normalized Windows name: {rel_old}  ->  {rel_new}", "OK")
            except ValueError:
                self.log(f"Normalized Windows name: {old}  ->  {new}", "OK")

        if renamed:
            self.log(
                f"Pre-Git filename normalization complete: {renamed} file/folder name(s) changed (spaces -> _).",
                "OK",
            )
        return renamed

    def _run_raw(self, args: list[str], cwd: Optional[str], check: bool = True,
                 timeout: Optional[int] = None) -> CommandResult:
        self.log("$ " + subprocess.list2cmdline(args), "CMD")
        try:
            completed = subprocess.run(
                args,
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except FileNotFoundError as exc:
            raise GitError(f"Executable not found: {args[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"Command timed out after {timeout} seconds: {args[0]}") from exc

        result = CommandResult(
            args=args,
            cwd=cwd,
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
        if result.stdout.strip():
            for line in result.stdout.rstrip().splitlines():
                self.log(line, "INFO")
        if result.stderr.strip():
            level = "ERROR" if result.returncode else "INFO"
            for line in result.stderr.rstrip().splitlines():
                self.log(line, level)
        if check and result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"Exit code {result.returncode}"
            low = detail.lower()
            if "dubious ownership" in low or "does not record ownership" in low:
                folder_text = cwd or self.repo_folder_var.get().strip()
                self._ui_queue.put(("ownership_state", (
                    f"Repository ownership: BLOCKED by Git — trust {folder_text} to continue", "error"
                )))
                detail += (
                    "\n\nThe selected drive does not provide ownership information Git can verify."
                    "\nUse the GUI button ‘Trust ONLY this folder’."
                    "\nThis adds only the selected controlled repository to Git safe.directory;"
                    " it does NOT trust every repository or the whole drive."
                )
            raise GitError(detail)
        return result

    def _git(self, *git_args: str, cwd: Optional[Path] = None,
             check: bool = True, timeout: Optional[int] = None) -> CommandResult:
        git_exe = self.git_exe_var.get().strip()
        if not git_exe:
            raise GitError("Git is not configured. Click Detect Git or Browse to git.exe first.")
        cwd_text = str(cwd) if cwd else None

        # V7 rule: before ANY repository Git operation, normalize spaces in all
        # working-tree file/folder names to underscores. Git private metadata is excluded.
        if cwd is not None:
            repo_candidate = Path(cwd)
            if repo_candidate.is_dir():
                self._normalize_spaces_in_controlled_tree(repo_candidate)

        # IMPORTANT: when operating on the controlled repository, explicitly bind
        # Git to THIS .git directory and THIS working tree.  This overrides a stale
        # core.worktree value (or other old working-tree path remembered by Git)
        # that can otherwise make Git keep referring to a folder that the user has
        # renamed or moved.  Global Git commands have no repository cwd and are
        # intentionally left untouched.
        if cwd is not None and (Path(cwd) / ".git").exists():
            git_dir = (Path(cwd) / ".git").resolve()
            work_tree = Path(cwd).resolve()
            args = [
                git_exe,
                f"--git-dir={self._safe_directory_value(git_dir)}",
                f"--work-tree={self._safe_directory_value(work_tree)}",
                *git_args,
            ]
        else:
            args = [git_exe, *git_args]

        # First attempt is deliberately non-raising so this wrapper can repair the
        # Windows/exFAT/FAT/network-drive ownership case before the caller sees it.
        result = self._run_raw(args, cwd_text, check=False, timeout=timeout)
        combined = (result.stderr + "\n" + result.stdout).strip()
        low = combined.lower()

        if cwd is not None and result.returncode != 0 and (
            "dubious ownership" in low or "does not record ownership" in low
        ):
            folder = Path(cwd).resolve()
            # Trust the selected controlled root AND repositories below it.
            # Git supports a safe.directory value ending in /* for this purpose.
            try:
                controlled_root = self._controlled_folder()
            except GitError:
                controlled_root = folder
            safe_value = self._safe_directory_value(controlled_root)
            safe_values = [safe_value, safe_value.rstrip("/") + "/*"]
            self.log(
                f"Git cannot verify filesystem ownership for {folder}. "
                f"Automatically trusting the controlled root and its subfolders: {controlled_root}",
                "WARN",
            )

            # Read/write global safe.directory WITHOUT a repository cwd, otherwise
            # Git would perform the same ownership check before we can repair it.
            get_cmd = [git_exe, "config", "--global", "--get-all", "safe.directory"]
            existing = self._run_raw(get_cmd, None, check=False, timeout=20)
            values = {
                line.strip().replace("\\", "/").rstrip("/").lower()
                for line in existing.stdout.splitlines() if line.strip()
            }
            for trust_value in safe_values:
                wanted = trust_value.rstrip("/").lower() if not trust_value.endswith("/*") else trust_value.lower()
                if wanted not in values:
                    add_cmd = [git_exe, "config", "--global", "--add", "safe.directory", trust_value]
                    added = self._run_raw(add_cmd, None, check=False, timeout=20)
                    if added.returncode != 0:
                        detail = added.stderr.strip() or added.stdout.strip() or f"Exit code {added.returncode}"
                        raise GitError(
                            f"Git could not add the controlled repository scope to safe.directory:\n{trust_value}\n\n{detail}"
                        )
                    self.log(f"Added Git safe.directory: {trust_value}", "OK")
                else:
                    self.log(f"Git safe.directory already contains: {trust_value}", "INFO")

            # Retry the exact command once after the targeted repair.
            result = self._run_raw(args, cwd_text, check=False, timeout=timeout)
            combined = (result.stderr + "\n" + result.stdout).strip()
            if result.returncode == 0:
                self._ui_queue.put(("ownership_state", (
                    f"Repository ownership: TRUSTED — {folder}", "ok"
                )))
                self.log("Ownership problem repaired automatically; Git command succeeded on retry.", "OK")

        if check and result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"Exit code {result.returncode}"
            low_detail = detail.lower()
            if "make_cache_entry failed" in low_detail or "error: invalid path" in low_detail:
                detail += (
                    "\n\nThis is not a Windows path cache. Git itself contains an obsolete/invalid path "
                    "in its index or commit tree. Click 'Repair stale Git paths'. The repair uses "
                    "the current controlled-folder contents and does not recreate the old folder name."
                )
            raise GitError(detail)
        return result

    @staticmethod
    def _safe_directory_value(folder: Path) -> str:
        # Git's global config is most portable on Windows with forward slashes.
        return str(folder).replace("\\", "/")

    def check_repo_ownership(self) -> None:
        def task() -> None:
            folder = self._controlled_folder()
            if not (folder / ".git").exists():
                self._ui_queue.put(("ownership_state", (
                    "Repository ownership: folder is not initialized as a Git repository yet", "warn"
                )))
                return
            result = self._git("rev-parse", "--show-toplevel", cwd=folder, check=False, timeout=20)
            combined = (result.stderr + "\n" + result.stdout).strip()
            low = combined.lower()
            if "dubious ownership" in low or "does not record ownership" in low:
                self._ui_queue.put(("ownership_state", (
                    f"Repository ownership: BLOCKED — {folder} must be explicitly trusted", "error"
                )))
                self.log("Git ownership protection blocked this repository. Use ‘Trust ONLY this folder’.", "WARN")
            elif result.returncode == 0:
                self._ui_queue.put(("ownership_state", (
                    f"Repository ownership: OK — Git accepts {folder}", "ok"
                )))
                self.log(f"Git ownership check passed: {folder}", "OK")
            else:
                self._ui_queue.put(("ownership_state", (
                    "Repository ownership: check failed; see log", "warn"
                )))
                raise GitError(combined or f"Ownership check failed with exit code {result.returncode}")
        self.run_async("Checking repository ownership...", task)

    def trust_selected_safe_directory(self) -> None:
        try:
            folder = self._controlled_folder()
        except GitError as exc:
            messagebox.showerror("Cannot trust folder", str(exc), parent=self)
            return
        safe_value = self._safe_directory_value(folder)
        safe_values = [safe_value, safe_value.rstrip("/") + "/*"]
        answer = messagebox.askyesno(
            "Trust controlled folder and subfolders?",
            "Git cannot verify ownership on some filesystems.\n\n"
            f"Trust this controlled folder AND Git repositories in all of its subfolders?\n\n{folder}\n\n"
            "This uses the specific folder plus its /* scope. It does NOT use safe.directory=* "
            "and does NOT trust the entire drive.",
            parent=self,
        )
        if not answer:
            return

        def task() -> None:
            existing = self._git("config", "--global", "--get-all", "safe.directory",
                                 check=False, timeout=20)
            values = {line.strip().rstrip("/").lower() for line in existing.stdout.splitlines() if line.strip()}
            for trust_value in safe_values:
                wanted = trust_value.lower() if trust_value.endswith("/*") else trust_value.rstrip("/").lower()
                if wanted not in values:
                    self._git("config", "--global", "--add", "safe.directory", trust_value, timeout=20)
                    self.log(f"Trusted Git safe.directory: {trust_value}", "OK")
                else:
                    self.log(f"Git safe.directory already contains: {trust_value}", "INFO")

            verify = self._git("rev-parse", "--show-toplevel", cwd=folder, check=False, timeout=20)
            combined = (verify.stderr + "\n" + verify.stdout).strip()
            if verify.returncode != 0:
                raise GitError("The safe.directory entry was added, but Git still rejected the repository:\n" + combined)
            self._ui_queue.put(("ownership_state", (
                f"Repository ownership: TRUSTED — {folder}", "ok"
            )))
            self._ui_queue.put(("message_info", (
                "Repository trusted",
                f"Git now trusts only this controlled repository:\n\n{folder}\n\n"
                "You can retry the Git operation."
            )))
        self.run_async("Trusting selected repository...", task)

    # ------------------------------------------------------------------
    # Remembered repository URL / favorites
    # ------------------------------------------------------------------
    def _load_settings(self) -> None:
        try:
            if SETTINGS_FILE.is_file():
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                last_url = normalize_repo_url(str(data.get("last_repository_url", "")))
                favorites = data.get("favorite_repository_urls", [])
                if isinstance(favorites, list):
                    cleaned: list[str] = []
                    for value in favorites:
                        url = normalize_repo_url(str(value))
                        if url and url not in cleaned:
                            cleaned.append(url)
                    self.favorite_repo_urls = cleaned
                if last_url:
                    self.remote_url_var.set(last_url)
        except Exception:
            # A damaged settings file must never stop the Git GUI from starting.
            self.favorite_repo_urls = []

    def _save_settings(self) -> None:
        data = {
            "last_repository_url": normalize_repo_url(self.remote_url_var.get()),
            "favorite_repository_urls": list(self.favorite_repo_urls),
        }
        try:
            SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            self.log(f"Could not save GUI settings: {exc}", "WARN")

    def _refresh_favorite_combo(self) -> None:
        if hasattr(self, "remote_url_combo"):
            self.remote_url_combo.configure(values=self.favorite_repo_urls)

    def add_repo_favorite(self) -> None:
        url = normalize_repo_url(self.remote_url_var.get())
        if not url:
            messagebox.showwarning("No repository URL", "Enter a GitHub repository URL first.", parent=self)
            return
        self.remote_url_var.set(url)
        if url not in self.favorite_repo_urls:
            self.favorite_repo_urls.append(url)
            self._refresh_favorite_combo()
            self._save_settings()
            self.log(f"Repository added to favorites: {url}", "OK")
        else:
            self.log(f"Repository is already a favorite: {url}", "INFO")

    def remove_repo_favorite(self) -> None:
        url = normalize_repo_url(self.remote_url_var.get())
        if url not in self.favorite_repo_urls:
            messagebox.showinfo("Not a favorite", "The current repository URL is not in Favorites.", parent=self)
            return
        self.favorite_repo_urls = [item for item in self.favorite_repo_urls if item != url]
        self._refresh_favorite_combo()
        self._save_settings()
        self.log(f"Repository removed from favorites: {url}", "OK")

    def _remember_current_repo_url(self) -> None:
        url = normalize_repo_url(self.remote_url_var.get())
        if url:
            self.remote_url_var.set(url)
            self._save_settings()

    def _on_close(self) -> None:
        self._remember_current_repo_url()
        self.destroy()

    # ------------------------------------------------------------------
    # Folder / repository validation
    # ------------------------------------------------------------------
    def browse_repo_folder(self) -> None:
        initial = self.repo_folder_var.get().strip() or None
        folder = filedialog.askdirectory(parent=self, title="Select controlled GitHub folder",
                                         initialdir=initial)
        if folder:
            self.repo_folder_var.set(os.path.normpath(folder))
            self.log(f"Controlled folder selected: {folder}", "OK")
            self.load_identity()
            self.after(50, self.check_repo_ownership)

    def _on_folder_drop(self, event: object) -> None:
        data = getattr(event, "data", "")
        folder = clean_drop_path(str(data))
        if os.path.isdir(folder):
            self.repo_folder_var.set(os.path.normpath(folder))
            self.log(f"Controlled folder dropped: {folder}", "OK")
            self.load_identity()
            self.after(50, self.check_repo_ownership)
        else:
            messagebox.showwarning("Not a folder", "Please drop one folder onto the field.", parent=self)

    def _controlled_folder(self, must_exist: bool = True) -> Path:
        text = self.repo_folder_var.get().strip()
        if not text:
            raise GitError("Select the controlled local folder first.")
        folder = Path(text).expanduser()
        if must_exist and not folder.is_dir():
            raise GitError(f"Controlled folder does not exist:\n{folder}")
        if folder.exists() and is_drive_root(folder):
            raise GitError(
                f"For safety, a drive root cannot be used as the controlled folder:\n{folder}\n\n"
                "Select a dedicated subfolder such as P:\\Github\\Script_R."
            )
        return folder.resolve() if folder.exists() else folder.absolute()

    def _require_repo(self) -> Path:
        folder = self._controlled_folder()
        if not (folder / ".git").exists():
            raise GitError(
                f"The controlled folder is not yet a Git repository:\n{folder}\n\n"
                "Enter the GitHub repository URL and click Initialize / Connect."
            )
        return folder

    def _remote_url(self) -> str:
        url = normalize_repo_url(self.remote_url_var.get())
        if not url:
            raise GitError("Enter the GitHub repository HTTPS URL first.")
        self.remote_url_var.set(url)
        self._save_settings()
        return url

    # ------------------------------------------------------------------
    # Browser / authentication helpers
    # ------------------------------------------------------------------
    def _on_local_root_changed(self, *_args: object) -> None:
        text = self.repo_folder_var.get().strip()
        self.local_root_var.set(f"Controlled local root: {text or 'not selected'}")

    def _apply_auth_details(self, username: Optional[str], accounts: list[str]) -> None:
        self.github_username = username
        if username:
            extra = f" ({len(accounts)} accounts stored)" if len(accounts) > 1 else ""
            self.auth_status_var.set(f"GitHub: SIGNED IN as {username}{extra}")
            self.github_root_var.set(f"GitHub root: https://github.com/{username}/")
            self.auth_badge.configure(bg=COLOR_GREEN)
        else:
            self.auth_status_var.set("GitHub: NOT SIGNED IN")
            self.github_root_var.set("GitHub root: not available until sign-in")
            self.auth_badge.configure(bg=COLOR_RED)

    @staticmethod
    def _parse_gcm_accounts(text: str) -> list[str]:
        accounts: list[str] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            low = line.lower()
            if low.startswith(("warning:", "error:", "usage:", "info:")):
                continue
            # GCM's `github list` prints one remembered GitHub account per line.
            if " " not in line and "\t" not in line:
                accounts.append(line)
        return list(dict.fromkeys(accounts))

    def _gcm_github_list(self) -> list[str]:
        result = self._git("credential-manager", "github", "list", check=False, timeout=60)
        if result.returncode == 0:
            return self._parse_gcm_accounts(result.stdout)

        direct = self._find_gcm_executable()
        if direct:
            result2 = self._run_raw(
                [str(direct), "github", "list"], cwd=None, check=False, timeout=60
            )
            if result2.returncode == 0:
                return self._parse_gcm_accounts(result2.stdout)
        return []

    def _preferred_github_username(self, accounts: list[str]) -> Optional[str]:
        result = self._git(
            "config", "--global", "--get", "credential.https://github.com.username",
            check=False
        )
        preferred = result.stdout.strip()
        if preferred:
            for account in accounts:
                if account.lower() == preferred.lower():
                    return account
        return accounts[0] if accounts else None

    def _refresh_github_auth_status_worker(self) -> None:
        accounts = self._gcm_github_list()
        username = self._preferred_github_username(accounts)
        self._ui_queue.put(("auth_details", (username, accounts)))
        if username:
            self.log(f"GitHub authentication confirmed for account: {username}", "OK")
            self.log(f"GitHub account root: https://github.com/{username}/", "OK")
        else:
            self.log("No GitHub account is currently listed by Git Credential Manager.", "WARN")

    def refresh_github_auth_status(self) -> None:
        if not self.git_exe_var.get().strip():
            self._apply_auth_details(None, [])
            return

        def task() -> None:
            self._refresh_github_auth_status_worker()

        self.run_async("Checking GitHub sign-in status...", task)

    def open_git_download(self) -> None:
        webbrowser.open("https://git-scm.com/download/win")

    def open_github_page(self) -> None:
        url = github_web_url(self.remote_url_var.get())
        if url:
            webbrowser.open(url)
        elif self.github_username:
            webbrowser.open(f"https://github.com/{self.github_username}/")
        else:
            webbrowser.open("https://github.com/")

    def github_sign_in(self) -> None:
        def task() -> None:
            git_exe = self.git_exe_var.get().strip()
            if not git_exe:
                raise GitError("Git must be detected before GitHub browser sign-in.")

            # Git for Windows exposes Git Credential Manager as a git subcommand.
            # This opens the supported GitHub browser/OAuth login flow.
            result = self._git("credential-manager", "github", "login", "--browser", check=False, timeout=300)
            if result.returncode == 0:
                self.log("GitHub browser sign-in completed; verifying stored account...", "OK")
                self._refresh_github_auth_status_worker()
                return

            # Older/newer installations can expose the executable directly.
            direct = self._find_gcm_executable()
            if direct:
                result2 = self._run_raw([str(direct), "github", "login", "--browser"], cwd=None,
                                        check=False, timeout=300)
                if result2.returncode == 0:
                    self.log("GitHub browser sign-in completed; verifying stored account...", "OK")
                    self._refresh_github_auth_status_worker()
                    return

            raise GitError(
                "Git Credential Manager could not start its GitHub login flow.\n\n"
                "You can still continue: the first authenticated fetch/push normally asks Git "
                "Credential Manager to open the browser automatically."
            )

        self.run_async("Opening GitHub browser sign-in...", task)

    def _find_gcm_executable(self) -> Optional[Path]:
        names = ["git-credential-manager.exe", "git-credential-manager-core.exe",
                 "git-credential-manager", "git-credential-manager-core"]
        for name in names:
            found = shutil.which(name)
            if found:
                return Path(found)

        git_text = self.git_exe_var.get().strip()
        if git_text:
            git_path = Path(git_text)
            # Typical Git for Windows path: <root>\cmd\git.exe
            root = git_path.parent.parent
            for rel in [Path("mingw64/bin"), Path("mingw32/bin"), Path("bin")]:
                for name in names:
                    candidate = root / rel / name
                    if candidate.is_file():
                        return candidate
        return None

    # ------------------------------------------------------------------
    # Stale / invalid Git path repair
    # ------------------------------------------------------------------
    @staticmethod
    def _windows_invalid_git_path(path_text: str) -> bool:
        """Return True for Git tree/index names that cannot be a repository-relative Windows path."""
        text = path_text.strip()
        if not text:
            return False
        # A Git tree path must always be relative.  An old GUI version could leave
        # an absolute Windows source path such as P:\Script_R\... in the index/tree.
        if re.match(r"^[A-Za-z]:[\\/]", text):
            return True
        if text.startswith(("\\\\", "//")):
            return True
        # ':' is illegal in a Windows filename component.  A drive prefix was
        # handled above; any remaining colon is also invalid for this GUI's Windows tree.
        if ":" in text:
            return True
        return False

    def _invalid_paths_in_ref(self, folder: Path, ref: str) -> list[str]:
        result = self._git("ls-tree", "-r", "-z", "--name-only", ref,
                           cwd=folder, check=False, timeout=120)
        if result.returncode != 0:
            return []
        return [p for p in result.stdout.split("\0") if p and self._windows_invalid_git_path(p)]

    def _invalid_paths_in_index(self, folder: Path) -> list[str]:
        # ls-files is plumbing-like enough to enumerate an index even when porcelain
        # commands such as status/reset fail while trying to create Windows cache entries.
        result = self._git("ls-files", "-z", cwd=folder, check=False, timeout=120)
        if result.returncode != 0:
            return []
        return [p for p in result.stdout.split("\0") if p and self._windows_invalid_git_path(p)]

    def _backup_git_index(self, folder: Path) -> Optional[Path]:
        index = folder / ".git" / "index"
        if not index.is_file():
            return None
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup = index.with_name(f"index.before_stale_path_repair_{stamp}.bak")
        shutil.copy2(index, backup)
        self.log(f"Backed up Git index: {backup}", "OK")
        return backup

    def _repair_stale_paths_worker(self, folder: Path, parent_ref: Optional[str] = None) -> bool:
        """Repair absolute/invalid Windows paths without renaming or deleting working files.

        Returns True when a repair was performed.  The current controlled folder is
        treated as authoritative.  If the bad path is already in commit history, a
        new normal commit is created *on top of* that history, so no force-push or
        history rewrite is required.
        """
        bad_index = self._invalid_paths_in_index(folder)
        head_exists = self._has_head(folder)
        bad_head = self._invalid_paths_in_ref(folder, "HEAD") if head_exists else []

        if parent_ref is None:
            parent_ref = "HEAD" if head_exists else self._remote_ref(folder)
        bad_parent = self._invalid_paths_in_ref(folder, parent_ref) if parent_ref else []

        bad_all = list(dict.fromkeys(bad_index + bad_head + bad_parent))
        if not bad_all:
            return False

        self.log("Detected stale/invalid Git path entries. These are Git metadata, not current Windows folders:", "WARN")
        for item in bad_all[:20]:
            self.log(f"  STALE: {item}", "WARN")
        if len(bad_all) > 20:
            self.log(f"  ... and {len(bad_all) - 20} more", "WARN")

        self._backup_git_index(folder)

        # If only the index is stale and the current commit tree is valid, rebuilding
        # the index from HEAD is sufficient and preserves the working files untouched.
        if bad_index and not bad_head and not bad_parent and head_exists:
            self._git("read-tree", "--reset", "HEAD", cwd=folder, timeout=120)
            self.log("Rebuilt the stale Git index from the valid current commit.", "OK")
            return True

        # The invalid absolute path is already in the current/remote commit tree.
        # `reset --mixed` cannot load such a tree on Windows (make_cache_entry fails).
        # Build a clean tree from the files that ACTUALLY exist in the controlled folder.
        name = self._git("config", "--local", "--get", "user.name", cwd=folder,
                         check=False).stdout.strip()
        email = self._git("config", "--local", "--get", "user.email", cwd=folder,
                          check=False).stdout.strip()
        if not name or not email:
            raise GitError(
                "A stale absolute Windows path is stored in the Git commit history, not in a filesystem cache.\n\n"
                "The GUI can repair it without touching your current files, but Git needs a commit identity first.\n"
                "Enter Commit author name and Commit author email, click 'Save identity for this repository only', "
                "then click 'Repair stale Git paths'."
            )

        parent_commit = ""
        if parent_ref:
            parent_result = self._git("rev-parse", "--verify", parent_ref, cwd=folder,
                                      check=False, timeout=60)
            if parent_result.returncode == 0:
                parent_commit = parent_result.stdout.strip()

        self.log("Rebuilding Git index from the CURRENT controlled-folder contents; working files are not changed.", "WARN")
        self._git("read-tree", "--empty", cwd=folder, timeout=120)
        self._git("add", "-A", "--", ".", cwd=folder, timeout=300)
        tree = self._git("write-tree", cwd=folder, timeout=120).stdout.strip()
        if not tree:
            raise GitError("Git could not create a clean tree during stale-path repair.")

        commit_args = ["commit-tree", tree]
        if parent_commit:
            commit_args.extend(["-p", parent_commit])
        commit_args.extend(["-m", "Repair stale absolute Windows paths"])
        new_commit = self._git(*commit_args, cwd=folder, timeout=120).stdout.strip()
        if not new_commit:
            raise GitError("Git could not create the stale-path repair commit.")

        branch = self._current_branch(folder) or self._last_remote_branch or "main"
        branch_ref = f"refs/heads/{branch}"
        self._git("symbolic-ref", "HEAD", branch_ref, cwd=folder, timeout=60)

        # A damaged loose branch ref (for example refs/heads/main containing an
        # invalid/empty object id) makes `update-ref <ref> <new> <old>` fail with
        # "unable to resolve reference". Detect that condition and remove ONLY
        # the broken local ref file/lock; working files and remote refs are untouched.
        old_local = self._git("rev-parse", "--verify", branch_ref, cwd=folder, check=False, timeout=60)
        if old_local.returncode == 0 and old_local.stdout.strip():
            self._git("update-ref", branch_ref, new_commit, old_local.stdout.strip(), cwd=folder, timeout=60)
        else:
            loose_ref = folder / ".git" / "refs" / "heads" / Path(branch)
            lock_ref = Path(str(loose_ref) + ".lock")
            for damaged in (lock_ref, loose_ref):
                try:
                    if damaged.is_file():
                        stamp = time.strftime("%Y%m%d_%H%M%S")
                        backup = damaged.with_name(damaged.name + f".broken_{stamp}.bak")
                        shutil.copy2(damaged, backup)
                        damaged.unlink()
                        self.log(f"Backed up and removed broken local Git ref: {damaged}", "WARN")
                except OSError as exc:
                    raise GitError(f"Could not repair broken local branch reference {damaged}: {exc}") from exc
            self._git("update-ref", branch_ref, new_commit, cwd=folder, timeout=60)

        # The index already represents the clean tree created above.  Verify that
        # ordinary Windows Git porcelain now works and the stale absolute name is gone.
        verify = self._git("status", "--porcelain", cwd=folder, check=False, timeout=120)
        if verify.returncode != 0:
            detail = verify.stderr.strip() or verify.stdout.strip()
            raise GitError("Stale-path repair commit was created, but Git status still failed:\n\n" + detail)

        self.log("Stale absolute Git path repaired. Current Windows folder names are now authoritative.", "OK")
        self.log("The repair is a normal descendant commit; no force-push or history rewrite was used.", "OK")
        return True

    def repair_stale_git_paths(self) -> None:
        try:
            folder = self._require_repo()
        except GitError as exc:
            messagebox.showerror("Repair stale Git paths", str(exc), parent=self)
            return

        # Save typed identity first when both fields are present, because a repair
        # commit may be necessary if the bad path is already in HEAD/remote history.
        typed_name = self.author_name_var.get().strip()
        typed_email = self.author_email_var.get().strip()
        if typed_name and typed_email:
            self._git("config", "--local", "user.name", typed_name, cwd=folder)
            self._git("config", "--local", "user.email", typed_email, cwd=folder)

        if not messagebox.askyesno(
            "Repair stale Git paths?",
            "This checks the Git index and current Git history for old absolute Windows paths, for example:\n\n"
            "P:\\Script_R\\old folder\\...\n\n"
            "The CURRENT files inside the controlled folder are treated as authoritative.\n"
            "Your working files are NOT renamed, moved, or deleted. The existing Git index is backed up first.\n\n"
            "If the stale path is already committed, the GUI creates one normal repair commit on top of the existing history.\n\nContinue?",
            parent=self,
        ):
            return

        def task() -> None:
            self._git("fetch", "--prune", "origin", cwd=folder, check=False, timeout=300)
            remote_ref = self._remote_ref(folder)
            repaired = self._repair_stale_paths_worker(folder, remote_ref)
            if repaired:
                self._ui_queue.put(("message_info", (
                    "Stale Git paths repaired",
                    "The obsolete absolute path stored by Git was repaired.\n\n"
                    "Git now uses the current folder names inside the controlled repository.\n"
                    "No working file was renamed or moved."
                )))
            else:
                self._ui_queue.put(("message_info", (
                    "No stale absolute Git paths found",
                    "The Git index/current tree did not contain an absolute Windows path."
                )))
        self.run_async("Checking and repairing stale Git paths...", task)

    # ------------------------------------------------------------------
    # Initialization / connection
    # ------------------------------------------------------------------
    def initialize_or_connect(self) -> None:
        try:
            folder = self._controlled_folder()
            url = self._remote_url()
        except GitError as exc:
            messagebox.showerror("Cannot connect", str(exc), parent=self)
            return

        prompt = (
            "This will make the following folder the Git working repository:\n\n"
            f"{folder}\n\n"
            "The GUI will not search your other script folders. If this GitHub repository already "
            "contains history, the program will fetch that history and connect it WITHOUT replacing "
            "the files currently in this controlled folder.\n\nContinue?"
        )
        if not messagebox.askyesno("Initialize / Connect", prompt, parent=self):
            return

        def task() -> None:
            folder.mkdir(parents=True, exist_ok=True)
            git_dir = folder / ".git"

            if not git_dir.exists():
                self.log(f"Initializing Git only inside: {folder}", "INFO")
                init = self._git("init", "-b", "main", cwd=folder, check=False)
                if init.returncode != 0:
                    self._git("init", cwd=folder)
                    # Older Git fallback.
                    self._git("branch", "-M", "main", cwd=folder, check=False)
            else:
                self.log("Existing .git directory found; repository will be reused.", "OK")
                self.log(
                    f"Git working tree is explicitly bound to the current controlled folder: {folder}",
                    "OK",
                )

            remotes = self._git("remote", cwd=folder).stdout.split()
            if "origin" in remotes:
                existing = self._git("remote", "get-url", "origin", cwd=folder).stdout.strip()
                if existing != url:
                    self.log(f"Updating origin URL from {existing} to {url}", "WARN")
                    self._git("remote", "set-url", "origin", url, cwd=folder)
            else:
                self._git("remote", "add", "origin", url, cwd=folder)

            self.log("Fetching GitHub metadata/history...", "INFO")
            fetch = self._git("fetch", "--prune", "origin", cwd=folder, check=False, timeout=300)
            if fetch.returncode != 0:
                raise GitError(
                    "The local repository was initialized, but GitHub fetch failed.\n\n"
                    + (fetch.stderr.strip() or fetch.stdout.strip())
                )

            remote_branch = self._detect_remote_default_branch(folder)
            self._last_remote_branch = remote_branch
            remote_ref = f"origin/{remote_branch}" if remote_branch else None
            remote_exists = bool(remote_ref and self._ref_exists(folder, f"refs/remotes/{remote_ref}"))

            # IMPORTANT: detect the old absolute-path bug BEFORE reset --mixed.
            # A tree containing P:\Script_R\... cannot be loaded into a Windows
            # index and produces `invalid path` / `make_cache_entry failed`.
            if remote_exists:
                self._repair_stale_paths_worker(folder, remote_ref)

            local_has_head = self._has_head(folder)

            if remote_exists and not local_has_head:
                # Attach the unborn local branch to the remote history without checking out
                # remote files. The mixed reset changes HEAD/index only; working files remain.
                self.log(
                    f"Adopting GitHub history from {remote_ref} while preserving all current local files.",
                    "INFO",
                )
                self._git("symbolic-ref", "HEAD", f"refs/heads/{remote_branch}", cwd=folder)
                self._git("reset", "--mixed", remote_ref, cwd=folder)
                self._git("branch", "--set-upstream-to", remote_ref, remote_branch,
                          cwd=folder, check=False)
            elif remote_exists and local_has_head:
                current = self._current_branch(folder)
                if current == remote_branch:
                    self._git("branch", "--set-upstream-to", remote_ref, current,
                              cwd=folder, check=False)
                else:
                    self.log(
                        f"Local branch is '{current}' while GitHub default branch is '{remote_branch}'. "
                        "No automatic branch rename was performed because local commits already exist.",
                        "WARN",
                    )
            else:
                self.log("The GitHub repository appears to have no branch/history yet.", "INFO")

            self._load_identity_worker(folder)
            self._update_remote_state_worker(folder)
            self.log("Controlled folder is connected to GitHub.", "OK")
            self._ui_queue.put(("message_info", (
                "Connected",
                "The controlled folder is now the local Git repository.\n\n"
                f"Folder:\n{folder}\n\n"
                "No second local repository folder is required."
            )))

        self.run_async("Initializing / connecting repository...", task)

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    def load_identity(self) -> None:
        try:
            folder = self._require_repo()
        except GitError:
            return

        def task() -> None:
            self._load_identity_worker(folder)

        self.run_async("Reading repository identity...", task)

    def _load_identity_worker(self, folder: Path) -> None:
        # --local deliberately avoids reading or modifying identity outside this repo.
        name = self._git("config", "--local", "--get", "user.name", cwd=folder,
                         check=False).stdout.strip()
        email = self._git("config", "--local", "--get", "user.email", cwd=folder,
                          check=False).stdout.strip()
        self._ui_queue.put(("identity", (name, email)))
        if name and email:
            self.log(f"Repository-local commit identity: {name} <{email}>", "OK")
        else:
            self.log("Repository-local commit identity is not fully configured.", "WARN")

    def save_local_identity(self) -> None:
        try:
            folder = self._require_repo()
        except GitError as exc:
            messagebox.showerror("Repository identity", str(exc), parent=self)
            return
        name = self.author_name_var.get().strip()
        email = self.author_email_var.get().strip()
        if not name or not email:
            messagebox.showwarning(
                "Repository identity",
                "Enter both a commit author name and commit author email.",
                parent=self,
            )
            return

        def task() -> None:
            self._git("config", "--local", "user.name", name, cwd=folder)
            self._git("config", "--local", "user.email", email, cwd=folder)
            self.log("Commit identity saved only in this repository's .git/config.", "OK")
            self._ui_queue.put(("message_info", (
                "Identity saved",
                "The commit identity was saved only for this controlled repository."
            )))

        self.run_async("Saving repository-local identity...", task)

    # ------------------------------------------------------------------
    # Git state helpers
    # ------------------------------------------------------------------
    def _has_head(self, folder: Path) -> bool:
        return self._git("rev-parse", "--verify", "HEAD", cwd=folder,
                         check=False).returncode == 0

    def _current_branch(self, folder: Path) -> str:
        result = self._git("branch", "--show-current", cwd=folder, check=False)
        branch = result.stdout.strip()
        if branch:
            return branch
        symbolic = self._git("symbolic-ref", "--short", "HEAD", cwd=folder, check=False)
        return symbolic.stdout.strip() or "main"

    def _ref_exists(self, folder: Path, full_ref: str) -> bool:
        return self._git("show-ref", "--verify", "--quiet", full_ref,
                         cwd=folder, check=False).returncode == 0

    def _detect_remote_default_branch(self, folder: Path) -> Optional[str]:
        result = self._git("ls-remote", "--symref", "origin", "HEAD",
                           cwd=folder, check=False, timeout=120)
        for line in result.stdout.splitlines():
            if line.startswith("ref:") and line.rstrip().endswith("\tHEAD"):
                ref = line.split()[1]
                prefix = "refs/heads/"
                if ref.startswith(prefix):
                    return ref[len(prefix):]

        # Fallback to locally known origin/HEAD.
        symbolic = self._git("symbolic-ref", "--short", "refs/remotes/origin/HEAD",
                             cwd=folder, check=False)
        text = symbolic.stdout.strip()
        if text.startswith("origin/"):
            return text.split("/", 1)[1]

        # Common branch fallbacks only if they actually exist remotely.
        for branch in ("main", "master"):
            if self._ref_exists(folder, f"refs/remotes/origin/{branch}"):
                return branch
        return None

    def _remote_ref(self, folder: Path) -> Optional[str]:
        branch = self._detect_remote_default_branch(folder)
        self._last_remote_branch = branch
        if branch and self._ref_exists(folder, f"refs/remotes/origin/{branch}"):
            return f"origin/{branch}"
        return None

    def _ahead_behind(self, folder: Path, remote_ref: str) -> tuple[Optional[int], Optional[int]]:
        if not self._has_head(folder):
            return None, None
        result = self._git("rev-list", "--left-right", "--count",
                           f"HEAD...{remote_ref}", cwd=folder, check=False)
        if result.returncode != 0:
            return None, None
        parts = result.stdout.strip().split()
        if len(parts) != 2:
            return None, None
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            return None, None

    def _update_remote_state_worker(self, folder: Path) -> None:
        remote_ref = self._remote_ref(folder)
        branch = self._current_branch(folder)
        if not remote_ref:
            text = f"Local branch: {branch} | GitHub repository has no detected remote branch"
            self._ui_queue.put(("remote_state", text))
            return

        ahead, behind = self._ahead_behind(folder, remote_ref)
        if ahead is None or behind is None:
            text = f"Local branch: {branch} | GitHub: {remote_ref} | histories not directly comparable"
        else:
            text = (f"Local branch: {branch} | GitHub: {remote_ref} | "
                    f"local commits ahead: {ahead} | GitHub commits ahead: {behind}")
        self._ui_queue.put(("remote_state", text))

    # ------------------------------------------------------------------
    # Fetch / pull / status
    # ------------------------------------------------------------------
    def fetch_remote(self) -> None:
        try:
            folder = self._require_repo()
        except GitError as exc:
            messagebox.showerror("Fetch", str(exc), parent=self)
            return

        def task() -> None:
            self._git("fetch", "--prune", "origin", cwd=folder, timeout=300)
            self._update_remote_state_worker(folder)
            self.log("Fetch complete.", "OK")

        self.run_async("Fetching GitHub...", task)

    def pull_remote(self) -> None:
        try:
            folder = self._require_repo()
            # Any spaces below the controlled root are normalized before Git.
            self._normalize_spaces_in_controlled_tree(folder)
            dirty = self._git("status", "--porcelain", cwd=folder, check=False).stdout.strip()
            if dirty:
                messagebox.showwarning(
                    "Pull blocked for safety",
                    "The controlled folder has local changes. Push them first, or resolve them before pulling.\n\n"
                    "Pull will not overwrite uncommitted local work.", parent=self)
                return
            self._git("fetch", "--prune", "origin", cwd=folder, timeout=300)
            remote_ref = self._remote_ref(folder)
            if not remote_ref:
                raise GitError("No GitHub branch was detected to pull.")
            remote_branch = remote_ref.split("/", 1)[1]
            current = self._current_branch(folder)
            if current != remote_branch:
                raise GitError(f"Local branch '{current}' differs from GitHub branch '{remote_branch}'.")

            diff = self._git("diff", "--name-status", "HEAD.." + remote_ref, "--", cwd=folder, check=False)
            added, replaced, deleted = [], [], []
            for line in diff.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                code, path = parts[0], parts[-1]
                if code.startswith("A"):
                    added.append(path)
                elif code.startswith("D"):
                    deleted.append(path)
                else:
                    replaced.append(path)

            if not (added or replaced or deleted):
                messagebox.showinfo("Pull from GitHub", "Local folder is already up to date with GitHub.\n\nNothing will be changed.", parent=self)
                return

            def sample(items):
                shown = "\n".join("  " + x for x in items[:12])
                return shown + (f"\n  ... and {len(items)-12} more" if len(items) > 12 else "")
            text = (f"PULL FROM GITHUB → LOCAL FOLDER\n\n"
                    f"New local files: {len(added)}\nFiles replaced locally: {len(replaced)}\nFiles deleted locally: {len(deleted)}\n")
            if replaced:
                text += "\nFILES THAT WILL BE REPLACED LOCALLY:\n" + sample(replaced) + "\n"
            if deleted:
                text += "\nFILES THAT GITHUB DELETED AND WILL BE DELETED LOCALLY:\n" + sample(deleted) + "\n"
            if not messagebox.askyesno("Confirm Pull from GitHub", text + "\nContinue?", parent=self):
                return
            if deleted and not messagebox.askyesno(
                "Confirm local deletions",
                f"FINAL DELETION CONFIRMATION\n\n{len(deleted)} local tracked file(s) will be deleted because GitHub deleted them.\n\n" + sample(deleted) + "\n\nDelete these local files?", parent=self):
                return

        except GitError as exc:
            messagebox.showerror("Pull from GitHub", str(exc), parent=self)
            return

        def task() -> None:
            self._git("fetch", "--prune", "origin", cwd=folder, timeout=300)
            self._git("pull", "--ff-only", "origin", remote_branch, cwd=folder, timeout=300)
            self._update_remote_state_worker(folder)
            self.log("Pull completed. Confirmed GitHub changes were applied locally.", "OK")
            self._ui_queue.put(("message_info", ("Pull complete", "Confirmed GitHub changes were applied to the controlled local folder.")))
            self.after(100, self.compare_with_github)

        self.run_async("Pulling confirmed changes from GitHub...", task)

    def show_git_status(self) -> None:
        try:
            folder = self._require_repo()
        except GitError as exc:
            messagebox.showerror("Git status", str(exc), parent=self)
            return

        def task() -> None:
            result = self._git("status", "--short", "--branch", cwd=folder, check=False)
            if not result.stdout.strip():
                self.log("Git status: clean working tree.", "OK")
            self._update_remote_state_worker(folder)

        self.run_async("Reading Git status...", task)

    # ------------------------------------------------------------------
    # Compare local controlled folder with GitHub
    # ------------------------------------------------------------------
    def compare_with_github(self) -> None:
        try:
            folder = self._require_repo()
        except GitError as exc:
            messagebox.showerror("Compare", str(exc), parent=self)
            return

        show_identical = self.show_identical_var.get()

        def task() -> None:
            self.log(f"Comparing only inside controlled folder: {folder}", "INFO")
            self._git("fetch", "--prune", "origin", cwd=folder, timeout=300)
            remote_ref = self._remote_ref(folder)

            local_files = self._local_git_visible_files(folder)
            self.log(f"Local Git-visible files considered: {len(local_files)}", "INFO")

            remote_files: dict[str, Optional[int]] = {}
            changed_paths: set[str] = set()
            if remote_ref:
                remote_files = self._remote_tree(folder, remote_ref)
                changed_paths = self._changed_paths_against_remote(folder, remote_ref)
                self.log(f"GitHub files considered from {remote_ref}: {len(remote_files)}", "INFO")
            else:
                self.log("No GitHub branch exists yet; all local files are LOCAL ONLY.", "WARN")

            rows: list[CompareRow] = []
            all_paths = sorted(set(local_files) | set(remote_files), key=str.lower)
            counts = {"LOCAL ONLY": 0, "REMOTE ONLY": 0, "DIFFERENT": 0, "IDENTICAL": 0}

            for rel in all_paths:
                local_path = folder / Path(rel)
                local_exists = local_path.is_file() or local_path.is_symlink()
                remote_exists = rel in remote_files

                if local_exists and not remote_exists:
                    status = "LOCAL ONLY"
                elif remote_exists and not local_exists:
                    status = "REMOTE ONLY"
                elif rel in changed_paths:
                    status = "DIFFERENT"
                else:
                    status = "IDENTICAL"

                counts[status] += 1
                if status == "IDENTICAL" and not show_identical:
                    continue

                try:
                    local_size = local_path.stat().st_size if local_exists else None
                except OSError:
                    local_size = None

                rows.append(CompareRow(
                    status=status,
                    path=rel,
                    local_size=format_bytes(local_size),
                    remote_size=format_bytes(remote_files.get(rel)) if remote_exists else "",
                    local_modified=format_mtime(local_path) if local_exists else "",
                ))

            rows.sort(key=lambda row: (
                {"DIFFERENT": 0, "LOCAL ONLY": 1, "REMOTE ONLY": 2, "IDENTICAL": 3}.get(row.status, 9),
                row.path.lower(),
            ))
            self._ui_queue.put(("compare_rows", rows))
            summary = " | ".join(f"{k}: {v}" for k, v in counts.items())
            if counts["LOCAL ONLY"] == 0 and counts["REMOTE ONLY"] == 0 and counts["DIFFERENT"] == 0:
                display_summary = f"LOCAL AND GITHUB MATCH — {counts['IDENTICAL']} unchanged file(s); 0 new; 0 different; 0 missing."
            else:
                display_summary = summary
            self._ui_queue.put(("compare_summary", display_summary))
            self.log("Comparison summary: " + summary, "OK")
            self._update_remote_state_worker(folder)

        self.run_async("Comparing local folder with GitHub...", task)

    def _local_git_visible_files(self, folder: Path) -> set[str]:
        # This asks Git for tracked + untracked non-ignored files. It does not walk
        # any directory outside the repository root.
        result = self._git("ls-files", "--cached", "--others", "--exclude-standard",
                           "-z", cwd=folder)
        paths = set()
        for item in result.stdout.split("\0"):
            if not item:
                continue
            rel = item.replace("\\", "/")
            candidate = folder / Path(rel)
            if candidate.is_file() or candidate.is_symlink():
                paths.add(rel)
        return paths

    def _remote_tree(self, folder: Path, remote_ref: str) -> dict[str, Optional[int]]:
        result = self._git("ls-tree", "-r", "-l", "--full-tree", remote_ref, cwd=folder)
        files: dict[str, Optional[int]] = {}
        for line in result.stdout.splitlines():
            if "\t" not in line:
                continue
            meta, rel = line.split("\t", 1)
            fields = meta.split()
            size: Optional[int] = None
            if len(fields) >= 4 and fields[3] != "-":
                try:
                    size = int(fields[3])
                except ValueError:
                    size = None
            files[rel.replace("\\", "/")] = size
        return files

    def _changed_paths_against_remote(self, folder: Path, remote_ref: str) -> set[str]:
        result = self._git("diff", "--name-only", "-z", remote_ref, "--", cwd=folder)
        return {item.replace("\\", "/") for item in result.stdout.split("\0") if item}

    def _populate_compare_rows(self, rows: Iterable[CompareRow]) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in rows:
            self.tree.insert("", "end", values=(
                row.status, row.path, row.local_size, row.remote_size, row.local_modified
            ), tags=(row.status,))

    # ------------------------------------------------------------------
    # Stage / commit / push
    # ------------------------------------------------------------------
    def stage_commit_push(self) -> None:
        try:
            folder = self._require_repo()
            self._remote_url()
            self._normalize_spaces_in_controlled_tree(folder)
            # Fetch FIRST. The confirmation must describe the exact current local-vs-GitHub state.
            self._git("fetch", "--prune", "origin", cwd=folder, timeout=300)
            remote_ref = self._remote_ref(folder)
            local_files = self._local_git_visible_files(folder)
            remote_files = self._remote_tree(folder, remote_ref) if remote_ref else {}
            changed = self._changed_paths_against_remote(folder, remote_ref) if remote_ref else set()
            new_files = sorted(local_files - set(remote_files), key=str.lower)
            deleted_files = sorted(set(remote_files) - local_files, key=str.lower)
            replaced_files = sorted((local_files & set(remote_files)) & changed, key=str.lower)

            if not (new_files or replaced_files or deleted_files):
                self.compare_summary_var.set(f"LOCAL AND GITHUB MATCH — {len(local_files)} unchanged file(s). Nothing to push.")
                messagebox.showinfo("Push to GitHub", "Local folder and GitHub already match.\n\nThere is nothing to push.", parent=self)
                return

            def sample(items):
                shown = "\n".join("  " + x for x in items[:12])
                return shown + (f"\n  ... and {len(items)-12} more" if len(items) > 12 else "")

            summary = (f"PUSH LOCAL FOLDER → GITHUB\n\nControlled folder:\n{folder}\n\n"
                       f"New on GitHub: {len(new_files)}\n"
                       f"Replace on GitHub: {len(replaced_files)}\n"
                       f"Delete from GitHub: {len(deleted_files)}\n")
            if new_files:
                summary += "\nNEW FILES:\n" + sample(new_files) + "\n"
            if replaced_files:
                summary += "\nFILES THAT WILL BE REPLACED ON GITHUB:\n" + sample(replaced_files) + "\n"
            if deleted_files:
                summary += "\nFILES THAT WILL BE DELETED FROM GITHUB:\n" + sample(deleted_files) + "\n"
            if not messagebox.askyesno("Confirm Push to GitHub", summary + "\nContinue with this push?", parent=self):
                return
            if deleted_files and not messagebox.askyesno(
                "Confirm GitHub deletions",
                f"FINAL DELETION CONFIRMATION\n\n{len(deleted_files)} GitHub file(s) will be deleted because they are not present in the controlled local folder.\n\n" + sample(deleted_files) + "\n\nDelete these files from GitHub?", parent=self):
                return

            approved = (tuple(new_files), tuple(replaced_files), tuple(deleted_files))
        except GitError as exc:
            messagebox.showerror("Push to GitHub", str(exc), parent=self)
            return

        def task() -> None:
            name = self._git("config", "--local", "--get", "user.name", cwd=folder, check=False).stdout.strip()
            email = self._git("config", "--local", "--get", "user.email", cwd=folder, check=False).stdout.strip()
            if not name or not email:
                raise GitError("Commit identity is not configured. Enter author name/email and save it for this repository.")

            # Re-fetch and recompute. Never push a state different from the state the user approved.
            self._git("fetch", "--prune", "origin", cwd=folder, timeout=300)
            rr = self._remote_ref(folder)
            lf = self._local_git_visible_files(folder)
            rf = self._remote_tree(folder, rr) if rr else {}
            ch = self._changed_paths_against_remote(folder, rr) if rr else set()
            now = (tuple(sorted(lf-set(rf), key=str.lower)),
                   tuple(sorted((lf & set(rf)) & ch, key=str.lower)),
                   tuple(sorted(set(rf)-lf, key=str.lower)))
            if now != approved:
                raise GitError("The local/GitHub state changed after the confirmation. Push was aborted. Click Fetch (Preview) and review again.")

            if rr and self._has_head(folder):
                ahead, behind = self._ahead_behind(folder, rr)
                if behind is None or behind > 0:
                    raise GitError("GitHub changed since the local history was prepared. Push stopped; Pull from GitHub first.")

            self._git("add", "-A", cwd=folder)
            staged = self._git("diff", "--cached", "--quiet", cwd=folder, check=False)
            if staged.returncode == 0:
                raise GitError("Internal safety check: preview showed changes but Git staged no changes. Push aborted.")
            if staged.returncode != 1:
                raise GitError(staged.stderr.strip() or "Unable to verify staged changes.")

            n, r, d = map(len, approved)
            parts=[]
            if n: parts.append(f"{n} new")
            if r: parts.append(f"{r} modified")
            if d: parts.append(f"{d} deleted")
            commit_message = "Push local changes: " + ", ".join(parts)
            self._git("commit", "-m", commit_message, cwd=folder, timeout=300)
            current = self._current_branch(folder)
            upstream = self._git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", cwd=folder, check=False)
            if upstream.returncode == 0 and upstream.stdout.strip():
                self._git("push", cwd=folder, timeout=300)
            else:
                self._git("push", "-u", "origin", current, cwd=folder, timeout=300)
            self._git("fetch", "--prune", "origin", cwd=folder, timeout=300)
            self._update_remote_state_worker(folder)
            self.log("Push completed successfully.", "OK")
            self._ui_queue.put(("message_info", ("Push complete", "The confirmed local changes were pushed to GitHub.")))
            self.after(100, self.compare_with_github)

        self.run_async("Pushing confirmed changes to GitHub...", task)

    def _parse_porcelain(self, text: str) -> list[tuple[str, str]]:
        """Parse enough of `git status --porcelain -z` for a safe summary."""
        if not text:
            return []
        items = text.split("\0")
        changes: list[tuple[str, str]] = []
        i = 0
        while i < len(items):
            entry = items[i]
            if not entry:
                i += 1
                continue
            if len(entry) < 3:
                i += 1
                continue
            xy = entry[:2]
            path = entry[3:] if len(entry) > 3 else ""
            if xy == "??":
                kind = "new"
            elif "R" in xy:
                kind = "renamed"
                # Porcelain -z stores the second path as the next NUL field.
                if i + 1 < len(items) and items[i + 1]:
                    i += 1
            elif "D" in xy:
                kind = "deleted"
            else:
                kind = "modified"
            changes.append((kind, path))
            i += 1
        return changes

    # ------------------------------------------------------------------
    # Open folder
    # ------------------------------------------------------------------
    def open_repo_folder(self) -> None:
        try:
            folder = self._controlled_folder()
        except GitError as exc:
            messagebox.showerror("Open folder", str(exc), parent=self)
            return

        try:
            if os.name == "nt":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:
            messagebox.showerror("Open folder", str(exc), parent=self)


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------
def main() -> None:
    app = GitHubSyncApp()
    app.mainloop()


if __name__ == "__main__":
    main()
