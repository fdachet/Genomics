import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from project_state import effective_builder_image
from recognized_elements import (database_path, inspect_docker_distribution, load_database, normalize_entry,
                                 save_database, scan_image_executables, select_database)


class ElementDialog(tk.Toplevel):
    def __init__(self, parent, existing=None):
        super().__init__(parent)
        self.result = None
        self.existing = existing or {}
        self.title('Edit recognized executable' if existing else 'Add recognized executable')
        self.geometry('810x650')
        self.minsize(680, 600)
        self.configure(bg='#EFF6FC')
        self.transient(parent.winfo_toplevel())
        self.fields = {key: tk.StringVar(value=str(self.existing.get(key) or '')) for key in
                       ('name', 'purpose', 'category', 'origin', 'kind', 'pattern', 'build_system', 'build_command')}
        self.fields['priority'] = tk.StringVar(value=str(self.existing.get('priority', 100)))
        self.fields['category'].set(self.fields['category'].get() or 'User-defined')
        self.fields['origin'].set(self.fields['origin'].get() or 'user')
        self.fields['kind'].set(self.fields['kind'].get() or 'executable')
        self.fields['requires'] = tk.StringVar(value=', '.join(self.existing.get('requires') or []))
        self.enabled = tk.BooleanVar(value=self.existing.get('enabled', True))
        self.executable = tk.BooleanVar(value=self.existing.get('executable', True))
        form = tk.Frame(self, bg='#EFF6FC')
        form.pack(fill='both', expand=True, padx=20, pady=14)
        form.columnconfigure(1, weight=1)
        labels = [('name', 'Recognized name'), ('kind', 'Element kind'),
                  ('purpose', 'Purpose / description'), ('category', 'Category'),
                  ('pattern', 'Optional filename / ID match (glob)'),
                  ('requires', 'Other recognized executables required'),
                  ('build_system', 'Auto-detected build system (optional)'),
                  ('build_command', 'Suggested build command (optional)'),
                  ('priority', 'Build detection priority (lower means first)'),
                  ('origin', 'Origin / source')]
        for index, (key, label) in enumerate(labels):
            tk.Label(form, text=label + ':', bg='#EFF6FC', anchor='w').grid(row=index, column=0, sticky='w', padx=4, pady=9)
            if key == 'kind':
                widget = ttk.Combobox(form, textvariable=self.fields[key], state='readonly',
                                      values=('executable', 'library', 'distribution', 'package_manager', 'build_file'))
            else:
                widget = tk.Entry(form, textvariable=self.fields[key], font=('Segoe UI', 10))
            widget.grid(row=index, column=1, sticky='ew', padx=8, pady=9)
        tk.Checkbutton(form, text='Enabled for recognition', variable=self.enabled,
                       bg='#EFF6FC').grid(row=10, column=1, sticky='w', padx=7, pady=6)
        tk.Checkbutton(form, text='Check this name as an executable (turn off for wrappers)', variable=self.executable,
                       bg='#EFF6FC').grid(row=11, column=1, sticky='w', padx=7, pady=3)
        tk.Label(form, text='Build markers can suggest a command; this command is never executed until you select a source build. '
                 'Dependencies are comma-separated executable names. No package is installed automatically.',
                 bg='#EFF6FC', fg='#21618C', wraplength=730, justify='left').grid(row=12, column=0, columnspan=2, sticky='w', pady=10)
        buttons = tk.Frame(self, bg='#EFF6FC')
        buttons.pack(fill='x', padx=18, pady=(0, 16))
        tk.Button(buttons, text='Save element', bg='#27AE60', fg='white', command=self._save).pack(side='left')
        tk.Button(buttons, text='Cancel', command=self.destroy).pack(side='right')
        self.grab_set()
        self.wait_window(self)

    def _save(self):
        try:
            entry = {name: variable.get().strip() for name, variable in self.fields.items()}
            entry['enabled'] = self.enabled.get()
            entry['executable'] = (self.executable.get() if entry['kind'] in ('executable', 'package_manager') else False)
            self.result = normalize_entry(entry)
        except ValueError as exc:
            messagebox.showerror('Invalid executable', str(exc), parent=self)
            return
        self.destroy()


class RecognizedElementsTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg='#EDF4FA')
        self.app = app
        self.elements = []
        self._loaded_path = None
        self._dirty = False
        self._busy = False
        self._events = queue.Queue()
        self.search = tk.StringVar()
        self.search.trace_add('write', lambda *_: self._populate())
        self.image = tk.StringVar()
        self.path_label = tk.StringVar()
        self.count_label = tk.StringVar()
        self.status = tk.StringVar(value='Loading recognized executable database...')
        self._sort_column = 'name'
        self._sort_reverse = False
        tk.Label(self, text='10 — RECOGNIZED ELEMENTS DATABASE', bg='#34495E', fg='white',
                 font=('Segoe UI', 16, 'bold'), anchor='w', padx=17, pady=13).pack(fill='x')
        tk.Label(self, text='Editable recognition catalog: build commands, languages, package managers, Linux shared libraries, '
                 'build files and distributions. Docker image scans read release versions from the image. No package is installed by this tab. '
                 'Unlisted manual build requirements remain allowed.',
                 bg='#D6EAF8', fg='#154360', anchor='w', justify='left', wraplength=1350,
                 padx=12, pady=10).pack(fill='x', padx=12, pady=(8, 6))
        path_row = tk.Frame(self, bg='#EDF4FA')
        path_row.pack(fill='x', padx=14, pady=5)
        tk.Label(path_row, text='JSON database:', bg='#EDF4FA', font=('Segoe UI', 10, 'bold')).pack(side='left')
        tk.Label(path_row, textvariable=self.path_label, bg='#EDF4FA', fg='#21618C', anchor='w').pack(side='left', padx=9)
        tk.Button(path_row, text='Open database', command=self._open).pack(side='right', padx=3)
        tk.Button(path_row, text='Save As...', command=self._save_as).pack(side='right', padx=3)
        tk.Button(path_row, text='Save database', bg='#27AE60', fg='white', command=self._save).pack(side='right', padx=3)
        tk.Button(path_row, text='Reload', command=self._reload).pack(side='right', padx=3)
        filter_row = tk.Frame(self, bg='#EDF4FA')
        filter_row.pack(fill='x', padx=14, pady=5)
        tk.Label(filter_row, text='Filter name, category, purpose or origin:', bg='#EDF4FA').pack(side='left')
        tk.Entry(filter_row, textvariable=self.search, width=52).pack(side='left', fill='x', expand=True, padx=8)
        tk.Label(filter_row, textvariable=self.count_label, bg='#EDF4FA', fg='#154360').pack(side='right')
        table_frame = tk.Frame(self, bg='#EDF4FA')
        table_frame.pack(fill='both', expand=True, padx=14, pady=9)
        columns = ('enabled', 'kind', 'name', 'category', 'purpose', 'pattern', 'build_system', 'requires', 'executable', 'origin')
        self.tree = ttk.Treeview(table_frame, columns=columns, show='headings', selectmode='extended')
        headings = (('enabled', 'ON', 55), ('kind', 'Kind', 115), ('name', 'Name', 160),
                    ('category', 'Category', 160), ('purpose', 'Purpose / description', 420),
                    ('pattern', 'Match pattern', 155),
                    ('build_system', 'Auto build', 115),
                    ('requires', 'Requires', 155), ('executable', 'Run check?', 95),
                    ('origin', 'Origin', 220))
        for key, label, width in headings:
            self.tree.heading(key, text=label, command=lambda col=key: self._sort(col))
            self.tree.column(key, width=width, minwidth=50, anchor='w')
        self.tree.tag_configure('disabled', foreground='#777777')
        self.tree.grid(row=0, column=0, sticky='nsew')
        scroll_y = ttk.Scrollbar(table_frame, orient='vertical', command=self.tree.yview)
        scroll_x = ttk.Scrollbar(table_frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        scroll_y.grid(row=0, column=1, sticky='ns')
        scroll_x.grid(row=1, column=0, sticky='ew')
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.tree.bind('<Double-1>', lambda _: self._edit())
        buttons = tk.Frame(self, bg='#EDF4FA')
        buttons.pack(fill='x', padx=14, pady=5)
        tk.Button(buttons, text='Add element', bg='#AED6F1', command=self._add).pack(side='left', padx=3)
        tk.Button(buttons, text='Edit selected', bg='#AED6F1', command=self._edit).pack(side='left', padx=3)
        tk.Button(buttons, text='Enable / Disable', bg='#AED6F1', command=self._toggle).pack(side='left', padx=3)
        tk.Button(buttons, text='Remove selected', bg='#F5B7B1', command=self._remove).pack(side='left', padx=3)
        scanner = tk.Frame(self, bg='#E8F8F5')
        scanner.pack(fill='x', padx=14, pady=(8, 4))
        tk.Label(scanner, text='Discover executables in Docker image:', bg='#E8F8F5').pack(side='left', padx=5)
        tk.Entry(scanner, textvariable=self.image, font=('Consolas', 10)).pack(side='left', fill='x', expand=True, padx=7)
        self.scan_button = tk.Button(scanner, text='Scan image / add new names', bg='#73C6B6', command=self._scan)
        self.scan_button.pack(side='left', padx=5, pady=6)
        tk.Label(self, text='Scanned entries without a known package description are marked for you to describe. '
                 'Nothing is installed, downloaded or copied from the Docker image during a scan.',
                 bg='#EDF4FA', fg='#566573', anchor='w', padx=16).pack(fill='x')
        tk.Label(self, textvariable=self.status, bg='#D6EAF8', fg='#154360', anchor='w',
                 padx=12, pady=8).pack(fill='x', padx=14, pady=(7, 12))
        self.refresh_from_project_state()

    def _mark_dirty(self):
        self._dirty = True
        self.status.set('Unsaved changes. Click Save database to use the updated recognition list in build detection.')
        self._populate()

    def _sort(self, column):
        if column == self._sort_column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = False
        self._populate()

    def _populate(self):
        if not hasattr(self, 'tree'):
            return
        selected = set(self.tree.selection())
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        keyword = self.search.get().strip().casefold()
        visible = []
        for entry in self.elements:
            text = ' '.join(str(entry.get(key) or '') for key in
                            ('name', 'kind', 'category', 'purpose', 'origin', 'pattern', 'requires', 'build_system', 'build_command')).casefold()
            if keyword and keyword not in text:
                continue
            visible.append(entry)
        def sort_key(entry):
            value = entry.get(self._sort_column)
            if isinstance(value, list):
                value = ', '.join(value)
            return str(value).casefold()
        visible.sort(key=sort_key, reverse=self._sort_reverse)
        for entry in visible:
            name = entry['name']
            self.tree.insert('', 'end', iid=name, values=(
                'YES' if entry['enabled'] else 'NO', entry['kind'], name, entry['category'], entry['purpose'],
                entry['pattern'], entry['build_system'], ', '.join(entry['requires']),
                'YES' if entry['executable'] else 'NO',
                entry['origin']), tags=() if entry['enabled'] else ('disabled',))
            if name in selected:
                self.tree.selection_add(name)
        enabled = sum(entry['enabled'] for entry in self.elements)
        self.count_label.set(str(len(visible)) + ' shown / ' + str(len(self.elements)) +
                             ' total / ' + str(enabled) + ' enabled')

    def _selection(self):
        names = set(self.tree.selection())
        return [entry for entry in self.elements if entry['name'] in names]

    def _add(self):
        dialog = ElementDialog(self)
        if dialog.result is None:
            return
        if any(entry['name'].casefold() == dialog.result['name'].casefold() for entry in self.elements):
            messagebox.showerror('Duplicate name', 'An element with this name already exists. Select it and use Edit.', parent=self)
            return
        self.elements.append(dialog.result)
        self._mark_dirty()
        self.tree.selection_set(dialog.result['name'])
        self.tree.see(dialog.result['name'])

    def _edit(self):
        selected = self._selection()
        if len(selected) != 1:
            messagebox.showinfo('Edit element', 'Select exactly one element to edit.', parent=self)
            return
        original = selected[0]
        dialog = ElementDialog(self, original)
        if dialog.result is None:
            return
        if dialog.result['name'].casefold() != original['name'].casefold() and any(
                entry['name'].casefold() == dialog.result['name'].casefold() for entry in self.elements):
            messagebox.showerror('Duplicate name', 'An element with this name already exists.', parent=self)
            return
        index = self.elements.index(original)
        self.elements[index] = dialog.result
        self._mark_dirty()
        if self.tree.exists(dialog.result['name']):
            self.tree.selection_set(dialog.result['name'])

    def _toggle(self):
        selected = self._selection()
        if not selected:
            return
        new_value = not all(entry['enabled'] for entry in selected)
        for entry in selected:
            entry['enabled'] = new_value
        self._mark_dirty()

    def _remove(self):
        selected = self._selection()
        if not selected:
            return
        if not messagebox.askyesno('Remove recognized elements',
                'Remove ' + str(len(selected)) + ' selected element(s) from the editable database?\n\n'
                'This does not uninstall any software from Docker images.', parent=self):
            return
        removed = {entry['name'] for entry in selected}
        self.elements = [entry for entry in self.elements if entry['name'] not in removed]
        self._mark_dirty()

    def _discard_changes(self):
        return not self._dirty or messagebox.askyesno(
            'Unsaved recognized elements',
            'Your database has unsaved changes. Discard them and continue?', parent=self)

    def _load(self, path, discard=False):
        if not discard and not self._discard_changes():
            return False
        try:
            entries = load_database(path)
        except ValueError as exc:
            messagebox.showerror('Database', str(exc), parent=self)
            return False
        self.elements = entries
        self._loaded_path = Path(path)
        self._dirty = False
        self.path_label.set(str(path))
        self.status.set('Loaded ' + str(len(entries)) + ' recognized elements. Changes affect future build analysis after saving.')
        self._populate()
        return True

    def _open(self):
        path = filedialog.askopenfilename(parent=self, title='Open recognized executable database',
                                          filetypes=[('JSON database', '*.json')])
        if not path or not self._load(path):
            return
        select_database(path)
        self.app.state['recognized_elements_database'] = str(database_path())

    def _reload(self):
        self._load(database_path())

    def _save(self):
        try:
            destination = save_database(self.elements)
        except (OSError, ValueError) as exc:
            messagebox.showerror('Save recognized elements', str(exc), parent=self)
            return False
        self.elements = load_database(destination)
        self._loaded_path = destination
        self._dirty = False
        self.path_label.set(str(destination))
        self.status.set('Saved ' + str(len(self.elements)) + ' recognized elements to ' + str(destination))
        self._populate()
        return True

    def _save_as(self):
        path = filedialog.asksaveasfilename(parent=self, title='Save recognized executable database as JSON',
                                            defaultextension='.json', filetypes=[('JSON database', '*.json')],
                                            initialfile='recognized_elements.json')
        if not path:
            return
        try:
            destination = save_database(self.elements, path)
        except (OSError, ValueError) as exc:
            messagebox.showerror('Save database', str(exc), parent=self)
            return
        select_database(destination)
        self.app.state['recognized_elements_database'] = str(destination)
        self._loaded_path = destination
        self._dirty = False
        self.path_label.set(str(destination))
        self.status.set('Saved new editable recognition database: ' + str(destination))
        self._populate()

    def _scan(self):
        if self._busy:
            return
        image = self.image.get().strip()
        if not image:
            messagebox.showinfo('Select a Docker image', 'Enter the local Docker image to scan.', parent=self)
            return
        self._scan_image = image
        self._busy = True
        self.scan_button.config(state='disabled')
        self.status.set('Scanning executable names from ' + image + ' (offline, read-only)...')
        def worker():
            try:
                records = scan_image_executables(image)
                try:
                    distro = inspect_docker_distribution(image)
                except (ValueError, RuntimeError):
                    distro = {}
                self._events.put(('result', {'executables': records, 'distribution': distro}))
            except Exception as exc:
                self._events.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()
        self.after(150, self._poll)

    def _poll(self):
        if not self.winfo_exists():
            return
        try:
            event, payload = self._events.get_nowait()
        except queue.Empty:
            self.after(150, self._poll)
            return
        self._busy = False
        self.scan_button.config(state='normal')
        if event == 'error':
            self.status.set('Docker executable scan failed: ' + payload)
            messagebox.showerror('Executable scan', payload, parent=self)
            return
        existing = {item['name'].casefold() for item in self.elements}
        additions = []
        for item in payload['executables']:
            key = item['name'].casefold()
            if key not in existing:
                additions.append(item)
                existing.add(key)
        distro = payload['distribution']
        if distro.get('id') and distro['id'].casefold() not in existing and all(
                entry['name'].casefold() != distro['id'].casefold() for entry in additions):
            additions.append({'name': distro['id'], 'purpose': distro.get('pretty_name') or 'Detected Linux distribution',
                              'category': 'Linux distribution', 'origin': self._scan_image, 'kind': 'distribution',
                              'pattern': distro['id'], 'enabled': True, 'executable': False, 'requires': []})
        self.elements.extend(additions)
        if additions:
            self._mark_dirty()
        detail = (' OS: ' + distro.get('id', '') + ' ' + distro.get('version_id', '') +
                  (' (' + distro.get('pretty_name', '') + ')' if distro.get('pretty_name') else '') + '.') if distro else ''
        self.status.set('Found ' + str(len(payload['executables'])) + ' image executables. Added ' + str(len(additions)) +
                        ' new entries.' + detail + ' Existing purposes and enabled/disabled choices were preserved. ' +
                        ('Click Save database.' if additions else 'No changes needed.'))
        self._populate()

    def refresh_from_project_state(self):
        desired = str(self.app.state.get('recognized_elements_database') or '').strip()
        try:
            path = select_database(desired)
        except ValueError as exc:
            self.status.set(str(exc))
            return
        if self._loaded_path != path:
            if self._dirty:
                self.status.set('Save or discard pending changes before switching databases.')
            else:
                self._load(path, discard=True)
        if not self.image.get().strip():
            image = str(self.app.state.get('base_image') or '').strip() or effective_builder_image(self.app.state)
            if image:
                self.image.set(image)
