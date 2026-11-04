import copy
import hashlib
import json
import queue
import subprocess
import posixpath
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from validation_discovery import CHECK_TYPES, DockerValidator, installed_target
from image_component_inventory import inspect_image_components
from manual_installation_overrides import ManualOverrideDialog, records_for_image


class ValidationTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg='#EBF5FB')
        self.app = app
        self.image = tk.StringVar()
        self.shared_summary = tk.StringVar()
        self.summary = tk.StringVar(value='Select Auto-check all components to verify the finished image.')
        self.busy = False
        self.cancel_requested = False
        self.rows = []
        self._image_id_checked = ''
        self._closed = False
        self._event_queue = queue.Queue()
        tk.Label(self, text='7 — AUTOMATIC VERIFICATION / EXPORT', bg='#154360', fg='white',
                 font=('Segoe UI', 16, 'bold'), anchor='w', padx=14, pady=10).pack(fill='x')
        tk.Label(self, textvariable=self.shared_summary, bg='#EBF5FB', fg='#154360',
                 anchor='w', justify='left').pack(fill='x', padx=14, pady=(10, 3))
        tk.Label(self, text='Auto-detect installation, version, help/startup, and self-tests. Known-input tests run only when their expected result is known. Edit any test manually.',
                 bg='#D6EAF8', fg='#154360', anchor='w', wraplength=1250, padx=10, pady=8).pack(fill='x', padx=12, pady=(3, 7))
        toolbar = tk.Frame(self, bg='#EBF5FB')
        toolbar.pack(fill='x', padx=12, pady=5)
        tk.Label(toolbar, text='Final image:', bg='#EBF5FB').pack(side='left')
        tk.Entry(toolbar, textvariable=self.image, width=31).pack(side='left', padx=5)
        self.auto_button = tk.Button(toolbar, text='Auto-check all components', bg='#2874A6', fg='white', command=self.run_all)
        self.auto_button.pack(side='left', padx=3)
        self.selected_button = tk.Button(toolbar, text='Check selected', bg='#3498DB', fg='white', command=self.run_selected)
        self.selected_button.pack(side='left', padx=3)
        self.stop_button = tk.Button(toolbar, text='Stop', bg='#D35400', fg='white', command=self.stop, state='disabled')
        self.stop_button.pack(side='left', padx=3)
        tk.Button(toolbar, text='Edit selected test', bg='#5DADE2', command=self.edit_selected).pack(side='left', padx=3)
        tk.Button(toolbar, text='Use automatic', bg='#AED6F1', command=self.reset_selected).pack(side='left', padx=3)
        tk.Button(toolbar, text='Refresh', command=self.refresh_from_project_state).pack(side='left', padx=3)
        extra = tk.Frame(self, bg='#EBF5FB')
        extra.pack(fill='x', padx=12, pady=3)
        tk.Button(extra, text='Add project test', bg='#5DADE2', command=self.add_project_test).pack(side='left', padx=3)
        tk.Button(extra, text='Remove selected project test', bg='#AED6F1', command=self.remove_project_test).pack(side='left', padx=3)
        tk.Button(extra, text='Export image .tar (partial OK)', bg='#1B4F72', fg='white', command=self.export_image).pack(side='left', padx=3)
        tk.Button(extra, text='Use existing local image', bg='#A9DFBF', command=self.use_existing_image).pack(side='left', padx=3)
        tk.Button(extra, text='Save report', bg='#21618C', fg='white', command=self.save_report).pack(side='left', padx=3)
        tk.Button(extra, text='Revise Built Image', bg='#A9DFBF', command=self.revise_image).pack(side='left', padx=3)
        tk.Button(extra, text='Manual confirmations', bg='#F7DC6F', command=self.manual_installation).pack(side='left', padx=3)
        tk.Label(self, textvariable=self.summary, bg='#D6EAF8', fg='#154360', anchor='w', padx=9,
                 pady=7, justify='left', wraplength=1300).pack(fill='x', padx=12, pady=(5, 6))
        frame = tk.Frame(self)
        frame.pack(fill='both', expand=True, padx=12, pady=(0, 6))
        cols = ('component', 'kind', 'check', 'command', 'status', 'detail')
        self.tree = ttk.Treeview(frame, columns=cols, show='headings', selectmode='extended', height=16)
        labels = {'component': 'Component', 'kind': 'Component type', 'check': 'Check',
                  'command': 'Command used', 'status': 'Status', 'detail': 'Result / explanation'}
        widths = {'component': 145, 'kind': 160, 'check': 115, 'command': 405, 'status': 110, 'detail': 460}
        for col in cols:
            self.tree.heading(col, text=labels[col])
            self.tree.column(col, width=widths[col], minwidth=65, anchor='w')
        scrollbar_y = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        scrollbar_x = ttk.Scrollbar(frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        scrollbar_y.grid(row=0, column=1, sticky='ns')
        scrollbar_x.grid(row=1, column=0, sticky='ew')
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree.tag_configure('pass', foreground='#145A32')
        self.tree.tag_configure('fail', foreground='#922B21')
        self.tree.tag_configure('warn', foreground='#9C640C')
        self.tree.bind('<Double-1>', lambda event: self.edit_selected())
        self.out = tk.Text(self, bg='white', font=('Consolas', 9), height=10, wrap='none')
        self.out.pack(fill='both', expand=False, padx=12, pady=(2, 12))
        self.refresh_from_project_state()
        self.after(50, self._drain_events)

    def manual_installation(self):
        ManualOverrideDialog(self, self.app.state, on_save=self.refresh_from_project_state)

    def _validation(self):
        data = self.app.state.get('validation', {})
        if not isinstance(data, dict):
            data = {}
            self.app.state['validation'] = data
        data.setdefault('checks', {})
        data.setdefault('project_tests', [])
        data.setdefault('last_results', {})
        return data

    def _notify(self):
        callback = getattr(self.app.state, 'touch', None)
        if callable(callback):
            callback('validation')

    def _components(self):
        added = [c for c in self.app.state.get('components', []) if isinstance(c, dict) and c.get('enabled', True)]
        archive = str(self.app.state.get('runtime_base_archive', '') or '').strip()
        if not archive:
            return added
        try:
            discovered = inspect_image_components(archive).get('components', [])
        except (OSError, ValueError, KeyError, TypeError):
            return added
        seen_paths = set()
        for component in added:
            target = installed_target(component)
            if target:
                seen_paths.add(target)
        combined = list(added)
        build_report = self.app.state.get('last_build_report') or {}
        build_image = str(build_report.get('image') or '')
        selected_image = str(self.image.get() or self.app.state.get('built_image') or '')
        removed_paths = {str(x.get('path') or '') for x in build_report.get('removed_this_revision', [])
                         if isinstance(x, dict) and x.get('kind') == 'file'} if build_image and build_image == selected_image else set()
        for item in discovered:
            path = str(item.get('path', '') or '')
            if not path or path in seen_paths or path in removed_paths:
                continue
            name = str(item.get('name', '') or '')
            if any(c.get('name') == name and c.get('kind') != 'os package' for c in combined):
                continue
            combined.append({'name': name, 'kind': item.get('kind'), 'source': item.get('local', ''),
                             'destination': posixpath.dirname(path).rstrip('/') + '/',
                             'version': item.get('version', ''), 'enabled': True,
                             'present_in_image': True})
            seen_paths.add(path)
        return combined

    def refresh_from_project_state(self):
        if self.busy:
            return
        image = str(self.app.state.get('image_name', '') or '')
        if image:
            self.image.set(image)
        report = self.app.state.get('last_build_report') or {}
        quality = '    |    Build: ' + report.get('quality', 'UNVERIFIED') + '    |    Warnings: ' + str(len(report.get('issues', []))) if report.get('image') == image else ''
        self.shared_summary.set('Image: ' + (image or '<not built>') + quality + '    |    Runtime: ' +
                                str(self.app.state.get('base_image', '') or '<not selected>') +
                                '\nExport folder: ' + str(self.app.state.get('export_image_dir', '') or '<not selected>'))
        self.load_commands()

    def load_commands(self):
        if self.busy:
            return
        data = self._validation()
        rows = []
        for component in self._components():
            name = str(component.get('name', '') or '').strip()
            if not name:
                continue
            for check in CHECK_TYPES:
                key = 'component:' + name + ':' + check
                rows.append({'id': key, 'name': name, 'kind': str(component.get('kind', '') or ''),
                             'check': check, 'component': component,
                             'override': (data.get('checks', {}).get(name, {}) or {}).get(check), 'project': False})
        for component in self._components():
            name = str(component.get('name', '') or '').strip()
            command = str(component.get('validation', '') or '').strip()
            if name and command:
                rows.append({'id': 'configured:' + name, 'name': name, 'kind': str(component.get('kind', '') or ''),
                             'check': 'Configured', 'component': component,
                             'override': {'command': command, 'exit_code': 0}, 'project': False, 'configured': True})
        for index, item in enumerate(data.get('project_tests', [])):
            if isinstance(item, dict):
                rows.append({'id': 'project:' + str(index), 'name': 'Project', 'kind': 'Custom',
                             'check': 'Functional', 'component': None, 'override': item, 'project': True, 'index': index})
        for index, command in enumerate(data.get('manual_commands', [])):
            if str(command or '').strip():
                rows.append({'id': 'legacy:' + str(index), 'name': 'Project', 'kind': 'Legacy manual',
                             'check': 'Custom', 'component': None,
                             'override': {'command': str(command), 'exit_code': 0}, 'project': True,
                             'legacy': index})
        for item in records_for_image(self.app.state):
            rows.append({'id': 'user-confirmed:' + item.get('category', '') + ':' + item.get('name', ''),
                         'name': item.get('name', ''), 'kind': item.get('category', ''),
                         'check': 'Manual confirmation', 'component': None, 'project': False,
                         'manual_confirmation': True, 'record': item, 'override': None})
        self.rows = rows
        self.tree.delete(*self.tree.get_children())
        results = data.get('last_results', {})
        for index, row in enumerate(rows):
            result = results.get(row['id'], {}) if isinstance(results, dict) else {}
            override = row.get('override')
            command = str((override or {}).get('command', '') or result.get('command', '')) if isinstance(result, dict) else ''
            status = ('USER CONFIRMED' if row.get('manual_confirmation') else str(result.get('status', 'NOT RUN')) if isinstance(result, dict) else 'NOT RUN')
            detail = ('User assertion: ' + row['record'].get('version', '') + ' at ' + row['record'].get('executable', '') + '; NOT execution verified'
                      if row.get('manual_confirmation') else str(result.get('detail', '')) if isinstance(result, dict) else '')
            self.tree.insert('', 'end', iid=str(index), values=(row['name'], row['kind'], row['check'], command,
                             status, detail), tags=self._tags(status))
        self._update_summary()

    @staticmethod
    def _tags(status):
        if status == 'PASS':
            return ('pass',)
        if status in ('FAIL', 'ERROR'):
            return ('fail',)
        if status in ('NOT VERIFIED', 'N/A', 'USER CONFIRMED'):
            return ('warn',)
        return ()

    def _update_summary(self):
        statuses = [self.tree.set(item, 'status') for item in self.tree.get_children()]
        counts = {status: statuses.count(status) for status in ('PASS', 'FAIL', 'ERROR', 'NOT VERIFIED', 'N/A', 'NOT RUN', 'USER CONFIRMED')}
        components = len(self._components())
        self.summary.set(f'{components} enabled components   |   PASS: {counts["PASS"]}   |   USER CONFIRMED: {counts["USER CONFIRMED"]}   |   FAIL: {counts["FAIL"]}   |   ERROR: {counts["ERROR"]}   |   NOT VERIFIED: {counts["NOT VERIFIED"]}   |   N/A: {counts["N/A"]}   |   NOT RUN: {counts["NOT RUN"]}')

    def _selected_rows(self):
        return [self.rows[int(index)] for index in self.tree.selection() if index.isdigit() and int(index) < len(self.rows)]

    def _editor(self, title, initial, callback):
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.geometry('870x690')
        dialog.minsize(620, 500)
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        frame = tk.Frame(dialog, padx=12, pady=12)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)
        vars = {}
        for row, (name, label, value) in enumerate((
            ('command', 'Command inside container:', initial.get('command', '')),
            ('exit_code', 'Expected exit code:', str(initial.get('exit_code', 0))),
            ('match', 'Expected-output match:', initial.get('match', 'contains')),
            ('input_folder', 'Windows test-data folder (mounted /testdata):', initial.get('input_folder', '')),
        )):
            tk.Label(frame, text=label, anchor='w').grid(row=row, column=0, sticky='w', pady=6)
            var = tk.StringVar(value=str(value))
            vars[name] = var
            if name == 'match':
                control = ttk.Combobox(frame, textvariable=var, values=('contains', 'exact', 'regex'), state='readonly')
            else:
                control = tk.Entry(frame, textvariable=var)
            control.grid(row=row, column=1, sticky='ew', padx=8, pady=6)
            if name == 'input_folder':
                tk.Button(frame, text='Browse', command=lambda v=var: self._browse_input_folder(v, dialog)).grid(row=row, column=2)
        tk.Label(frame, text='Expected output text, stdout or stderr (recommended for functional tests):').grid(row=4, column=0, columnspan=2, sticky='w', pady=(13, 2))
        expected_box = tk.Text(frame, height=5, wrap='word')
        expected_box.grid(row=5, column=0, columnspan=3, sticky='nsew', pady=3)
        expected_box.insert('1.0', str(initial.get('expected', '')))
        tk.Label(frame, text='Input sent to program stdin (optional):').grid(row=6, column=0, columnspan=2, sticky='w', pady=(13, 2))
        stdin_box = tk.Text(frame, height=5, wrap='word')
        stdin_box.grid(row=7, column=0, columnspan=3, sticky='nsew', pady=3)
        stdin_box.insert('1.0', str(initial.get('stdin', '')))
        tk.Label(frame, text='Use /testdata for files from the selected Windows folder. Tests run with network disabled and a read-only container filesystem.',
                 wraplength=770, justify='left', fg='#566573').grid(row=8, column=0, columnspan=3, sticky='w', pady=10)
        frame.rowconfigure(5, weight=1)
        frame.rowconfigure(7, weight=1)
        def save():
            try:
                code = int(vars['exit_code'].get().strip())
            except ValueError:
                messagebox.showerror('Validation', 'Expected exit code must be an integer.', parent=dialog)
                return
            cmd = vars['command'].get().strip()
            if not cmd:
                messagebox.showerror('Validation', 'Enter a command or choose Use automatic.', parent=dialog)
                return
            result = {'command': cmd, 'exit_code': code, 'match': vars['match'].get(),
                      'expected': expected_box.get('1.0', 'end-1c'),
                      'stdin': stdin_box.get('1.0', 'end-1c'),
                      'input_folder': vars['input_folder'].get().strip()}
            callback(result)
            dialog.destroy()
        controls = tk.Frame(frame)
        controls.grid(row=9, column=0, columnspan=3, sticky='e', pady=8)
        tk.Button(controls, text='Cancel', command=dialog.destroy).pack(side='right', padx=5)
        tk.Button(controls, text='Save test', bg='#2874A6', fg='white', command=save).pack(side='right', padx=5)

    @staticmethod
    def _browse_input_folder(var, parent):
        folder = filedialog.askdirectory(parent=parent)
        if folder:
            var.set(folder)

    def _invalidate_results(self):
        data = self._validation()
        data['last_results'] = {}
        data['verified_image_id'] = ''
        self._notify()

    def edit_selected(self):
        rows = self._selected_rows()
        if len(rows) != 1:
            messagebox.showinfo('Validation', 'Select exactly one check to edit.', parent=self)
            return
        row = rows[0]
        initial = copy.deepcopy(row.get('override') or {})
        if not initial.get('command'):
            initial['command'] = str(self.tree.set(str(self.rows.index(row)), 'command') or '')
        def save(spec):
            data = self._validation()
            if row.get('configured'):
                data['checks'].setdefault(row['name'], {})['Configured'] = spec
            elif row['project']:
                if 'index' in row:
                    data['project_tests'][row['index']] = spec
                elif 'legacy' in row:
                    data['manual_commands'].pop(row['legacy'])
                    data['project_tests'].append(spec)
            else:
                data['checks'].setdefault(row['name'], {})[row['check']] = spec
            self._invalidate_results()
            self.load_commands()
        self._editor(row['name'] + ' — ' + row['check'], initial, save)

    def reset_selected(self):
        rows = self._selected_rows()
        changed = 0
        data = self._validation()
        for row in rows:
            if row['project']:
                continue
            per_component = data.get('checks', {}).get(row['name'], {})
            if row['check'] in per_component:
                del per_component[row['check']]
                changed += 1
        if changed:
            self._invalidate_results()
            self.load_commands()
        else:
            messagebox.showinfo('Validation', 'No manual overrides selected.', parent=self)

    def add_project_test(self):
        def save(spec):
            self._validation()['project_tests'].append(spec)
            self._invalidate_results()
            self.load_commands()
        self._editor('New project-level validation', {'command': '', 'exit_code': 0, 'match': 'contains'}, save)

    def remove_project_test(self):
        rows = self._selected_rows()
        data = self._validation()
        for row in sorted((r for r in rows if 'index' in r), key=lambda r: r['index'], reverse=True):
            del data['project_tests'][row['index']]
        for row in sorted((r for r in rows if 'legacy' in r), key=lambda r: r['legacy'], reverse=True):
            del data['manual_commands'][row['legacy']]
        if rows:
            self._invalidate_results()
            self.load_commands()

    def stop(self):
        self.cancel_requested = True

    def _image_id(self, image):
        try:
            p = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], capture_output=True,
                               text=True, timeout=12, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return p.stdout.strip() if p.returncode == 0 else ''
        except (OSError, subprocess.TimeoutExpired):
            return ''

    def _ensure_image_available(self, image):
        if not image:
            messagebox.showerror('Docker image', 'Enter a Docker image tag in the Final image field.', parent=self)
            return ''
        image_id = self._image_id(image)
        if not image_id:
            messagebox.showerror('Docker image', 'Image ' + image + ' was not found in the local Docker engine. Complete the build in Tab 6, or load its exported TAR with docker load.', parent=self)
            return ''
        registered = str(self.app.state.get('built_image', '') or '').strip()
        if registered != image:
            if not messagebox.askyesno('Use existing Docker image',
                'Docker already contains this image:\n\n' + image + '\n' + image_id +
                '\n\nThe current project does not record this image as its completed build. '
                'Use this existing local image for verification or export without rebuilding it?', parent=self):
                return ''
            self.app.state['built_image'] = image
            self.app.state['image_name'] = image
            report = self.app.state.get('last_build_report') or {}
            if report.get('image') != image:
                self.app.state['last_build_report'] = {'image': image, 'quality': 'UNVERIFIED',
                    'issues': ['Using an existing Docker image: build history not confirmed by this session'],
                    'docker_exit_code': 0}
            self.refresh_from_project_state()
            self.out.insert('end', 'Existing local Docker image registered: ' + image + '\n')
        return image_id

    def use_existing_image(self):
        image = self.image.get().strip()
        found = self._ensure_image_available(image)
        if found:
            self.out.insert('end', 'Local image available for verification and export: ' + image + '\n')
            self.out.see('end')

    def run_selected(self):
        selected = [int(key) for key in self.tree.selection() if key.isdigit()]
        if not selected:
            messagebox.showinfo('Validation', 'Select one or more checks.', parent=self)
            return
        self._start_checks(selected)

    def run_all(self):
        self._start_checks(list(range(len(self.rows))))

    def _start_checks(self, indices):
        if self.busy:
            return
        image = self.image.get().strip()
        if not self._ensure_image_available(image):
            return
        indices = [i for i in indices if not self.rows[i].get('manual_confirmation')]
        if not indices:
            messagebox.showinfo('Validation', 'Manual confirmations are not executable tests. Select an actual test to verify the software.', parent=self)
            return
        self.busy = True
        self.cancel_requested = False
        self.auto_button.configure(state='disabled')
        self.selected_button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        self.out.delete('1.0', 'end')
        self._invalidate_results()
        items = [(index, copy.deepcopy(self.rows[index])) for index in indices]
        image_id = self._image_id(image)
        manager = str((self.app.state.get('base_system', {}) or {}).get('package_manager', 'dpkg'))
        self._image_id_checked = image_id
        for index in indices:
            self.tree.set(str(index), 'status', 'PENDING')
            self.tree.set(str(index), 'detail', '')
        def worker():
            results = {}
            validator = DockerValidator(image)
            for index, row in items:
                if self.cancel_requested:
                    break
                self._schedule(lambda i=index: self.tree.set(str(i), 'status', 'RUNNING'))
                spec = row.get('override')
                if row['project'] or row.get('configured'):
                    outcome = validator._run_spec(spec, 'manual' if row['project'] else 'configured')
                else:
                    outcome = validator.test(row['component'], row['check'], spec, manager)
                results[row['id']] = outcome
                def display(i=index, r=outcome, name=row['name'], check=row['check']):
                    if not self.winfo_exists():
                        return
                    self.tree.set(str(i), 'status', r['status'])
                    self.tree.set(str(i), 'command', r['command'])
                    self.tree.set(str(i), 'detail', r['detail'])
                    self.tree.item(str(i), tags=self._tags(r['status']))
                    self.out.insert('end', '\n=== ' + name + ' / ' + check + ' ===\n' +
                                    'Command: ' + r['command'] + '\n' +
                                    (r['output'] or r['detail']) + '\nSTATUS: ' + r['status'] + '\n')
                    self.out.see('end')
                    self._update_summary()
                self._schedule(display)
            def finish():
                self.busy = False
                self.auto_button.configure(state='normal')
                self.selected_button.configure(state='normal')
                self.stop_button.configure(state='disabled')
                if self.cancel_requested:
                    self.out.insert('end', '\nStopped. Remaining checks are unverified.\n')
                saved = self._validation()
                saved['last_results'] = {**saved.get('last_results', {}), **results}
                saved['verified_image_id'] = image_id if not self.cancel_requested and image_id else ''
                saved['verified_plan_hash'] = self._plan_hash() if not self.cancel_requested else ''
                self._notify()
                self._update_summary()
            self._schedule(finish)
        threading.Thread(target=worker, daemon=True).start()

    def _schedule(self, callback):
        self._event_queue.put(callback)

    def _drain_events(self):
        try:
            while True:
                callback = self._event_queue.get_nowait()
                callback()
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(50, self._drain_events)

    def _plan_hash(self):
        selected = {'components': self._components(), 'checks': self._validation().get('checks', {}),
                    'project_tests': self._validation().get('project_tests', []),
                    'manual_commands': self._validation().get('manual_commands', [])}
        return hashlib.sha256(json.dumps(selected, sort_keys=True, default=str).encode('utf-8')).hexdigest()

    def export_image(self):
        if self.busy:
            return
        image = self.image.get().strip()
        if not self._ensure_image_available(image):
            return
        from build_modes import STRICT, normalize_mode
        mode = normalize_mode(self.app.state.get('build_mode'))
        report = self.app.state.get('last_build_report') or {}
        data = self._validation()
        image_id = self._image_id(image)
        verification_current = bool(image_id and image_id == data.get('verified_image_id') and data.get('verified_plan_hash') == self._plan_hash())
        if not image_id:
            messagebox.showerror('Export', 'The built image is not available in the local Docker engine.', parent=self)
            return
        if mode == STRICT and not verification_current:
            messagebox.showerror('Export', 'Strict mode requires verification. Click Auto-check all components.', parent=self)
            return
        if not self.rows and mode == STRICT:
            messagebox.showerror('Export', 'No components or checks configured.', parent=self)
            return
        results = data.get('last_results', {})
        missing = [row for row in self.rows if row['id'] not in results]
        failures = [row for row in self.rows if results.get(row['id'], {}).get('status') in ('FAIL', 'ERROR')]
        installations = [row for row in self.rows if row['check'] == 'Installation']
        failed_installations = [row for row in installations if results.get(row['id'], {}).get('status') != 'PASS']
        if mode == STRICT and (missing or failures or failed_installations):
            messagebox.showerror('Export', f'Strict mode: {len(missing)} checks not run, {len(failures)} failed/error, {len(failed_installations)} installations unconfirmed.', parent=self)
            return
        unknown = [row for row in self.rows if results.get(row['id'], {}).get('status') in ('NOT VERIFIED', 'N/A')]
        issues = list(report.get('issues', [])) if report.get('image') == image else []
        if mode != STRICT:
            details = (f'Image: {image}\nBuild quality: {report.get("quality", "UNVERIFIED")}\n'
                       f'Unrun checks: {len(missing)}\nFailed/error checks: {len(failures)}\n'
                       f'Unconfirmed installations: {len(failed_installations)}\n'
                       f'Other unverified checks: {len(unknown)}\n'
                       f'Build warnings: {len(issues)}\n\n')
            if issues:
                details += '\n'.join(issues[:12]) + '\n\n'
            details += 'Export this image even though it may be incomplete or nonfunctional?'
            if not messagebox.askyesno('Export incomplete image', details, parent=self):
                return
        elif unknown and not messagebox.askyesno('Unverified checks',
                f'{len(unknown)} checks are not verified or not applicable. Export anyway?', parent=self):
            return
        root = str(self.app.state.get('export_image_dir', '') or '').strip()
        chosen = filedialog.asksaveasfilename(parent=self, defaultextension='.tar',
                 filetypes=[('Docker image TAR', '*.tar')],
                 initialdir=root if root and Path(root).is_dir() else str(Path.cwd()),
                 initialfile=image.replace('/', '_').replace(':', '_') + '.tar')
        if not chosen:
            return
        self.out.insert('end', '\nExporting ' + image + ' to ' + chosen + '\n')
        def worker():
            try:
                process = subprocess.run(['docker', 'save', '-o', chosen, image], capture_output=True, text=True,
                                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                result = (process.stdout + process.stderr) + '\nExit code: ' + str(process.returncode) + '\n'
            except OSError as exc:
                result = str(exc)
            self._schedule(lambda: self.out.insert('end', result))
        threading.Thread(target=worker, daemon=True).start()

    def revise_image(self):
        target = getattr(self.app, 'build_tab', None)
        if target is None:
            return
        if target.revise_built_image():
            notebook = getattr(self.app, 'notebook', None)
            if notebook is not None:
                notebook.select(target)

    def save_report(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension='.json',
                  filetypes=[('JSON report', '*.json')], initialfile='image_validation.json')
        if not path:
            return
        data = {'image': self.image.get().strip(), 'summary': self.summary.get(),
                'build_report': self.app.state.get('last_build_report', {}),
                'checks': self._validation().get('last_results', {})}
        Path(path).write_text(json.dumps(data, indent=2), encoding='utf-8')


class _DebugApp:
    def __init__(self):
        from project_state import ProjectState
        self.state = ProjectState()


if __name__ == '__main__':
    root = tk.Tk()
    root.title('Debug — ValidationTab')
    root.geometry('1500x900')
    app = _DebugApp()
    tab = ValidationTab(root, app)
    tab.pack(fill='both', expand=True)
    root.mainloop()
