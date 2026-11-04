import json
import re
import tkinter as tk
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from tkinter import messagebox, ttk

CATEGORIES = ('Java', 'Python', 'R', 'Perl', 'OS package', 'Native program', 'Custom')


@lru_cache(maxsize=32)
def _archive_image_id(path, size, mtime):
    from component_provenance import image_identity
    return image_identity(path, '')


def selected_image_identity(state, image=None, archive=None):
    tag = str(image if image is not None else state.get('base_image', '') or '').strip()
    path = str(archive if archive is not None else state.get('runtime_base_archive', '') or '').strip()
    if image is not None and archive is None and tag != str(state.get('base_image', '') or '').strip():
        path = ''
    if path and Path(path).is_file():
        try:
            stat = Path(path).stat()
            identity = _archive_image_id(path, stat.st_size, stat.st_mtime_ns)
            if identity:
                return identity
        except OSError:
            pass
    if tag:
        from component_provenance import image_identity
        identity = image_identity('', tag)
        if identity:
            return identity
    if path:
        return 'archive:' + str(Path(path).resolve()).lower()
    return 'tag:' + tag.lower() if tag else ''


def _normalize_category(category):
    value = str(category or '').strip().lower()
    for recognized in CATEGORIES:
        if value == recognized.lower():
            return recognized
    raise ValueError('Choose an installation category.')


def _normalize_path(value):
    path = str(value or '').strip()
    if path and (not path.startswith('/') or '..' in path.split('/') or '\\' in path or '\n' in path):
        raise ValueError('Executable or installation path must be an absolute Linux path without traversal.')
    return path


def make_override(state, category, name, version, executable, image=None, archive=None):
    category = _normalize_category(category)
    name = str(name or '').strip()
    version = str(version or '').strip()
    executable = _normalize_path(executable)
    identity = selected_image_identity(state, image, archive)
    if not identity:
        raise ValueError('Select and inspect a runtime image before confirming installed software.')
    if not name or not version or not executable:
        raise ValueError('Enter the software name, claimed version, and installed executable or directory path.')
    if len(name) > 160 or len(version) > 120 or len(executable) > 1000:
        raise ValueError('An entered value is too long.')
    return {
        'category': category,
        'name': name,
        'version': version,
        'executable': executable,
        'image_id': identity,
        'image_tag': str(image if image is not None else state.get('base_image', '') or ''),
        'status': 'USER CONFIRMED',
        'confirmation': 'user assertion; executable not independently verified',
        'confirmed_at_utc': datetime.now(timezone.utc).isoformat(),
        'execution_verified': False,
        'carried_from_parent': False,
    }


def override_key(record):
    return (str(record.get('image_id', '')), str(record.get('category', '')).lower(), str(record.get('name', '')).lower())


def save_override(state, record):
    records = [deepcopy(x) for x in state.get('installation_overrides', []) if isinstance(x, dict)]
    key = override_key(record)
    records = [x for x in records if override_key(x) != key]
    records.append(deepcopy(record))
    state['installation_overrides'] = records
    state['installation_override_rejections'] = [x for x in state.get('installation_override_rejections', [])
        if (x.get('image_id'), x.get('category'), x.get('name')) !=
           (record.get('image_id'), record.get('category'), record.get('name'))]
    return record


def delete_override(state, record):
    key = (selected_image_identity(state), str(record.get('category', '')).lower(), str(record.get('name', '')).lower())
    state['installation_overrides'] = [deepcopy(x) for x in state.get('installation_overrides', [])
                                       if isinstance(x, dict) and override_key(x) != key]
    rejected = [x for x in state.get('installation_override_rejections', []) if isinstance(x, dict)]
    if key not in {(x.get('image_id'), x.get('category', '').lower(), x.get('name', '').lower()) for x in rejected}:
        rejected.append({'image_id': selected_image_identity(state), 'category': record.get('category'), 'name': record.get('name')})
    state['installation_override_rejections'] = rejected


@lru_cache(maxsize=20)
def _embedded_confirmations(path, size, mtime):
    from component_provenance import provenance_from_archive
    provenance = provenance_from_archive(path) or {}
    return tuple(dict(x) for x in (provenance.get('manual_installation_overrides') or [])
                 if isinstance(x, dict) and x.get('status') == 'USER CONFIRMED')


def records_for_image(state, image=None, archive=None, include_provenance=True):
    identity = selected_image_identity(state, image, archive)
    local = [deepcopy(x) for x in state.get('installation_overrides', [])
             if isinstance(x, dict) and x.get('image_id') == identity and x.get('status') == 'USER CONFIRMED']
    if not include_provenance:
        return local
    path = str(archive if archive is not None else state.get('runtime_base_archive', '') or '').strip()
    rejected = {tuple(x.get(key, '') for key in ('image_id', 'category', 'name'))
                for x in state.get('installation_override_rejections', []) if isinstance(x, dict)}
    if path and Path(path).is_file():
        try:
            stat = Path(path).stat()
            for entry in _embedded_confirmations(path, stat.st_size, stat.st_mtime_ns):
                key = (identity, entry.get('category', ''), entry.get('name', ''))
                if key in rejected:
                    continue
                if not any((x.get('category', '').lower(), x.get('name', '').lower()) ==
                           (entry.get('category', '').lower(), entry.get('name', '').lower()) for x in local):
                    local.append(dict(entry, carried_from_parent=True, execution_verified=False))
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return local


def parse_major(version):
    text = str(version or '').strip()
    match = re.match(r'^(?:1\.)?(\d+)(?:[.\-+_]|$)', text)
    return int(match.group(1)) if match else None


def confirmed_category(state, category, minimum=None, image=None, archive=None):
    matches = []
    for entry in records_for_image(state, image=image, archive=archive):
        if str(entry.get('category', '')).lower() != str(category).lower():
            continue
        if minimum is not None:
            from general_environment import version
            try:
                if version(entry.get('version', ''), category) < version(minimum, category):
                    continue
            except (ValueError, TypeError):
                continue
        matches.append(entry)
    return matches


def user_confirmed_package(state, package):
    normalized = str(package or '').lower().strip()
    for record in records_for_image(state):
        if record.get('category') == 'OS package' and str(record.get('name', '')).lower().strip() == normalized:
            return record
    return None


def compatible_java_override(state, minimum, image=None, archive=None):
    candidates = []
    for entry in records_for_image(state, image=image, archive=archive):
        if str(entry.get('category', '')).lower() != 'java':
            continue
        major = parse_major(entry.get('version', ''))
        if major is not None and major >= int(minimum):
            candidates.append((major, entry))
    return max(candidates, key=lambda pair: pair[0])[1] if candidates else None


class ManualOverrideDialog(tk.Toplevel):
    def __init__(self, parent, state, initial_category='Java', initial_name='', initial_version='', initial_path='', on_save=None):
        super().__init__(parent)
        self.state = state
        self.on_save = on_save
        self.title('Manually confirm installed software')
        self.geometry('890x565')
        self.minsize(720, 480)
        self.configure(bg='#F0F5FA')
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.category = tk.StringVar(value=initial_category if initial_category in CATEGORIES else 'Custom')
        self.name = tk.StringVar(value=initial_name or ('Java runtime' if initial_category == 'Java' else ''))
        self.version = tk.StringVar(value=initial_version)
        self.executable = tk.StringVar(value=initial_path)
        self.identity = selected_image_identity(state)
        tk.Label(self, text='USER-CONFIRMED INSTALLATION — NOT AUTOMATIC VERIFICATION',
                 font=('Segoe UI', 13, 'bold'), fg='white', bg='#1F618D', padx=12, pady=10).pack(fill='x')
        tk.Label(self, text='Image: ' + str(state.get('base_image') or '') + '\nImmutable identity: ' + self.identity,
                 anchor='w', justify='left', bg='#D6EAF8', padx=12, pady=9, wraplength=820).pack(fill='x', padx=12, pady=8)
        editor = tk.Frame(self, bg='#F0F5FA')
        editor.pack(fill='x', padx=14, pady=5)
        editor.columnconfigure(1, weight=1)
        for row, (caption, var, widget) in enumerate((
            ('Software category', self.category, 'category'),
            ('Software name', self.name, 'entry'),
            ('Claimed installed version', self.version, 'entry'),
            ('Executable / installation path in image', self.executable, 'entry'),
        )):
            tk.Label(editor, text=caption + ':', bg='#F0F5FA', anchor='w').grid(row=row, column=0, sticky='w', padx=5, pady=7)
            if widget == 'category':
                control = ttk.Combobox(editor, textvariable=var, values=CATEGORIES, state='readonly')
            else:
                control = ttk.Entry(editor, textvariable=var)
            control.grid(row=row, column=1, sticky='ew', pady=7, padx=5)
        tk.Label(self, text='Example: Java  |  Java runtime  |  17.0.12  |  /usr/java/jdk-17/bin/java\n'
                           'This is your assertion, NOT a successful test. Actual execution checks remain separate in Tab 7.\n'
                           'Overrides apply only to this image identity. Revisions may inherit them as unverified assertions.',
                 bg='#FFF2D9', fg='#7E5109', padx=10, pady=10, wraplength=840, justify='left').pack(fill='x', padx=14, pady=7)
        frame = tk.Frame(self, bg='#F0F5FA')
        frame.pack(fill='both', expand=True, padx=14, pady=5)
        tk.Label(frame, text='User confirmations recorded for this image:', bg='#F0F5FA').pack(anchor='w')
        self.tree = ttk.Treeview(frame, columns=('category', 'name', 'version', 'path', 'source'), show='headings', height=5)
        for column, caption, width in (('category', 'Category', 110), ('name', 'Software', 160),
                                       ('version', 'Version', 90), ('path', 'Executable / directory', 330),
                                       ('source', 'Evidence', 150)):
            self.tree.heading(column, text=caption)
            self.tree.column(column, width=width)
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self._select)
        actions = tk.Frame(self, bg='#F0F5FA')
        actions.pack(fill='x', padx=14, pady=12)
        tk.Button(actions, text='Save user confirmation', command=self._save, bg='#2471A3', fg='white').pack(side='left', padx=4)
        tk.Button(actions, text='Remove selected confirmation', command=self._delete, bg='#E6B0AA').pack(side='left', padx=4)
        tk.Button(actions, text='Close', command=self.destroy).pack(side='right', padx=4)
        self.refresh()

    def refresh(self):
        self.records = records_for_image(self.state)
        self.tree.delete(*self.tree.get_children())
        for index, entry in enumerate(self.records):
            self.tree.insert('', 'end', iid=str(index), values=(entry.get('category', ''), entry.get('name', ''),
                entry.get('version', ''), entry.get('executable', ''),
                'INHERITED' if entry.get('carried_from_parent') else 'USER CONFIRMED'))

    def _select(self, event=None):
        keys = self.tree.selection()
        if not keys:
            return
        record = self.records[int(keys[0])]
        self.category.set(record.get('category', 'Java'))
        self.name.set(record.get('name', ''))
        self.version.set(record.get('version', ''))
        self.executable.set(record.get('executable', ''))

    def _save(self):
        try:
            record = make_override(self.state, self.category.get(), self.name.get(),
                                   self.version.get(), self.executable.get())
        except ValueError as exc:
            messagebox.showerror('Manual installation confirmation', str(exc), parent=self)
            return
        save_override(self.state, record)
        self.refresh()
        if self.on_save:
            self.on_save()

    def _delete(self):
        keys = self.tree.selection()
        if not keys:
            messagebox.showinfo('Manual confirmation', 'Select a confirmation to remove.', parent=self)
            return
        record = self.records[int(keys[0])]
        delete_override(self.state, record)
        self.refresh()
        if self.on_save:
            self.on_save()
