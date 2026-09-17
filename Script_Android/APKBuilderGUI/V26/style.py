from __future__ import annotations

import tkinter as tk
from tkinter import ttk


COLORS = {
    "bg": "#0f172a",
    "card": "#f8fafc",
    "ink": "#0f172a",
    "muted": "#475569",
    "accent": "#2563eb",
    "accent2": "#7c3aed",
    "ok": "#15803d",
    "warn": "#b45309",
    "err": "#b91c1c",
    "info": "#0369a1",
    "soft_ok": "#dcfce7",
    "soft_warn": "#fef3c7",
    "soft_err": "#fee2e2",
    "soft_info": "#e0f2fe",
}


def apply_style(root: tk.Tk) -> None:
    root.configure(bg=COLORS["bg"])
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    default_font = ("Segoe UI", 10)
    heading_font = ("Segoe UI", 12, "bold")
    title_font = ("Segoe UI", 15, "bold")
    small_bold = ("Segoe UI", 9, "bold")

    style.configure(".", font=default_font)
    style.configure("TFrame", background=COLORS["card"])
    style.configure("Header.TFrame", background=COLORS["accent"])
    style.configure("PurpleHeader.TFrame", background=COLORS["accent2"])
    style.configure("TLabel", background=COLORS["card"], foreground=COLORS["ink"])
    style.configure("Muted.TLabel", background=COLORS["card"], foreground=COLORS["muted"])
    style.configure("Title.TLabel", background=COLORS["accent"], foreground="white", font=title_font, padding=(12, 8))
    style.configure("PurpleTitle.TLabel", background=COLORS["accent2"], foreground="white", font=title_font, padding=(12, 8))
    style.configure("Section.TLabel", background=COLORS["card"], foreground=COLORS["ink"], font=heading_font)
    style.configure("SmallBold.TLabel", background=COLORS["card"], foreground=COLORS["ink"], font=small_bold)

    style.configure("TLabelframe", background=COLORS["card"], bordercolor="#cbd5e1", relief="solid", padding=(5, 4))
    style.configure("TLabelframe.Label", background=COLORS["card"], foreground=COLORS["ink"], font=heading_font)

    style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", padding=(10, 5), background="#cbd5e1", foreground=COLORS["ink"])
    style.map("TNotebook.Tab", background=[("selected", COLORS["card"])], foreground=[("selected", COLORS["ink"])])

    style.configure("TButton", padding=(6, 3), background="#e2e8f0", foreground=COLORS["ink"])
    style.map("TButton", background=[("active", "#cbd5e1")])
    style.configure("Accent.TButton", background=COLORS["accent"], foreground="white")
    style.map("Accent.TButton", background=[("active", "#1d4ed8")], foreground=[("active", "white")])
    style.configure("Ok.TButton", background=COLORS["ok"], foreground="white")
    style.map("Ok.TButton", background=[("active", "#166534")], foreground=[("active", "white")])
    style.configure("Warn.TButton", background=COLORS["warn"], foreground="white")
    style.map("Warn.TButton", background=[("active", "#92400e")], foreground=[("active", "white")])
    style.configure("Danger.TButton", background=COLORS["err"], foreground="white")
    style.map("Danger.TButton", background=[("active", "#991b1b")], foreground=[("active", "white")])

    style.configure("TEntry", fieldbackground="white", foreground=COLORS["ink"])
    style.configure("TCombobox", fieldbackground="white", foreground=COLORS["ink"])
    style.configure("Horizontal.TProgressbar", troughcolor="#e5e7eb", background=COLORS["accent"])
    style.configure("Treeview", background="white", foreground=COLORS["ink"], fieldbackground="white", rowheight=23)
    style.configure("Treeview.Heading", font=small_bold, background="#e2e8f0", foreground=COLORS["ink"])


def make_header(parent, title: str, subtitle: str = "", purple: bool = False):
    frame = ttk.Frame(parent, style="PurpleHeader.TFrame" if purple else "Header.TFrame")
    title_label = ttk.Label(frame, text=title, style="PurpleTitle.TLabel" if purple else "Title.TLabel")
    title_label.pack(anchor="w", fill="x")
    if subtitle:
        subtitle_label = tk.Label(
            frame,
            text=subtitle,
            bg=COLORS["accent2"] if purple else COLORS["accent"],
            fg="#e0f2fe",
            font=("Segoe UI", 10),
            padx=12,
            pady=4,
            anchor="w",
        )
        subtitle_label.pack(fill="x")
    return frame
