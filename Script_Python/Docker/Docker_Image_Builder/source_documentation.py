import os
import re
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext
from source_archive import ArchiveDocument, SourceArchive, is_source_archive


DOCUMENT_FOLDERS = ('', 'source', 'src', 'doc', 'docs')
DOCUMENT_NAMES = ('README.md', 'README', 'README.rst', 'README.txt', 'BUILDING.md', 'BUILD.md',
                  'INSTALL.md', 'INSTALL', 'INSTALL.txt', 'COMPILING.md', 'COMPILE.md')
BUILD_HEADINGS = ('compiling from source', 'compilation', 'compile', 'building from source',
                  'building', 'build instructions', 'installation', 'installing', 'installation instructions')


def discover_build_documentation(source_folder):
    source = Path(str(source_folder or '').strip())
    if source.is_file() and is_source_archive(source):
        contents = SourceArchive(source)
        files = {name.casefold(): name for name in contents.file_names}
        documents = []
        for directory in DOCUMENT_FOLDERS:
            for name in DOCUMENT_NAMES:
                relative = f'{directory}/{name}' if directory else name
                member = files.get(relative.casefold())
                if member:
                    documents.append(ArchiveDocument(source, member))
        return documents
    if not source.is_dir():
        return []
    documents = []
    seen = set()
    for directory in DOCUMENT_FOLDERS:
        folder = source / directory if directory else source
        if not folder.is_dir():
            continue
        try:
            files = {entry.name.casefold(): entry for entry in folder.iterdir() if entry.is_file()}
        except OSError:
            continue
        for name in DOCUMENT_NAMES:
            path = files.get(name.casefold())
            if path is None:
                continue
            try:
                if path.stat().st_size > 8 * 1024 * 1024:
                    continue
            except OSError:
                continue
            key = str(path.resolve()).casefold()
            if key not in seen:
                seen.add(key)
                documents.append(path)
    return documents


def build_instruction_line(text):
    lines = str(text or '').splitlines()
    for heading in BUILD_HEADINGS:
        for index, line in enumerate(lines):
            normalized = re.sub(r'^[\s#*=_~-]+|[\s#*=_~-]+$', '', line).casefold()
            if normalized == heading or normalized.startswith(heading + ' '):
                return index + 1
    for index, line in enumerate(lines):
        if re.match(r'^\s*(?:#{1,6}\s*)?(?:compil\w*|build(?:ing)?|install(?:ation|ing)?)\b', line, re.I):
            return index + 1
    return 1


def show_build_documentation(parent, path):
    if not isinstance(path, ArchiveDocument):
        path = Path(path)
    try:
        content = path.read_text(encoding='utf-8-sig', errors='replace')
    except (OSError, ValueError, FileNotFoundError) as exc:
        messagebox.showerror('Source documentation', str(exc), parent=parent)
        return
    window = tk.Toplevel(parent)
    window.title('Source build documentation — ' + path.name)
    window.geometry('1050x750')
    window.minsize(650, 420)
    tk.Label(window, text=str(path), anchor='w', padx=12, pady=9).pack(fill='x')
    viewer = scrolledtext.ScrolledText(window, font=('Consolas', 10), wrap='word')
    viewer.pack(fill='both', expand=True, padx=10, pady=(0, 10))
    viewer.insert('1.0', content)
    line = build_instruction_line(content)
    viewer.tag_configure('build_heading', background='#FFF2B3', foreground='#6E2C00')
    viewer.tag_add('build_heading', f'{line}.0', f'{line}.end')
    viewer.configure(state='disabled')
    viewer.see(f'{line}.0')
    viewer.mark_set('insert', f'{line}.0')
    window.lift()
    return window


def open_build_documentation(path):
    if isinstance(path, ArchiveDocument):
        raise ValueError('Archive documentation opens in the internal reader.')
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(str(path))
    if sys.platform == 'win32':
        os.startfile(str(path))
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', str(path)], start_new_session=True)
    else:
        subprocess.Popen(['xdg-open', str(path)], start_new_session=True)
