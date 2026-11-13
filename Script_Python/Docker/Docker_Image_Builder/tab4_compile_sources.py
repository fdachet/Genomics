import shlex
import re
import subprocess
import threading
import queue
import os
import time
import uuid
from datetime import datetime, timezone
import tkinter as tk
from pathlib import Path
from source_archive import is_source_archive
from tkinter import messagebox, simpledialog, ttk
from build_artifacts import prepare_workspace, read_record, register_output
from binary_version_probe import probe_binary_version
from compilation_status import compilation_status
from component_presets import BUILD_COMMANDS, COMMON_BUILD_COMMANDS, detect_build_system
from component_output_detector import detect_compiled_output, normalized_relative
from project_state import effective_builder_image
from repository_package_dialog import RepositoryPackageInstallDialog
from source_documentation import discover_build_documentation, open_build_documentation, show_build_documentation
from network_policy import POLICY_OFFLINE, normalize_policy, package_names, inspect_packages, permission_message, validate_packages
from source_build_dependencies import discover_build_requirements, inspect_builder_commands, suggested_package, builder_command_preflight, valid_executable_path
from recognized_elements import entry_category, recognized_names, require_dependencies, valid_name


STATUS_WORDS = re.compile(r'\b(?:NOT INSTALLED|INSTALLED|MISSING)\b', flags=re.IGNORECASE)
INSTALLED_COLOR = '#173F73'
MISSING_COLOR = '#8B1E1E'


def insert_colored_status(widget, text):
    text = str(text)
    offset = 0
    for match in STATUS_WORDS.finditer(text):
        if match.start() > offset:
            widget.insert('end', text[offset:match.start()])
        token = match.group()
        widget.insert('end', token, 'missing_status' if token.upper() in ('MISSING', 'NOT INSTALLED') else 'installed_status')
        offset = match.end()
    if offset < len(text):
        widget.insert('end', text[offset:])


def build_command_with_output_fallback(command, output_relative):
    target = shlex.quote(output_relative)
    return ('( ' + command + ' ); _component_result=$?; '
            'if [ "$_component_result" -ne 0 ]; then '
            'if [ -s ' + target + ' ] && [ -x ' + target + ' ]; then '
            'echo "COMPONENT-PARTIAL-BUILD: build command failed with exit $_component_result but the requested executable exists"; '
            'else exit "$_component_result"; fi; fi')


def requirements_for_source(component, command=None):
    requirements = discover_build_requirements(component.get('source', ''),
                                               component.get('build_command', '') if command is None else command)
    names = {item['command'] for item in requirements}
    for name in component.get('manual_required_build_tools', []) or []:
        if valid_name(name) and name not in names:
            requirements.append({'command': name, 'evidence': ['Manually required']})
            names.add(name)
    return require_dependencies(requirements)


def describe_builder_tool_status(requirements, report, choices=None):
    selected = choices or {}
    installed = []
    missing = []
    for item in requirements:
        command = item['command']
        details = report.get('found', {}).get(command)
        if details:
            location = details.get('path', '')
            version = details.get('version', '')
            installed.append(command + (': ' + location if location else '') +
                             (' (' + version + ')' if version else ''))
        else:
            configured = selected.get(command) if isinstance(selected.get(command), dict) else {}
            package = str(configured.get('package', '') or '').strip()
            executable = str(configured.get('executable', '') or '').strip()
            chosen = ' | selected package: ' + package if package else ' | selected executable: ' + executable if executable else ''
            suggestion = suggested_package(command, report)
            if suggestion and not package and not executable:
                chosen = ' | suggested package: ' + suggestion
            missing.append(command + ' (NOT INSTALLED in builder' + chosen + ')')
    header = ('Builder ' + report.get('distro', 'unknown') + ' ' + report.get('distro_version', '') +
              ' | ' + str(len(installed)) + ' installed, ' + str(len(missing)) + ' missing')
    lines = [header]
    if installed:
        lines.append('INSTALLED: ' + ', '.join(installed))
    if missing:
        lines.append('MISSING: ' + ', '.join(missing))
        lines.append('Use "Check builder tools / choose installation" to choose an installation or executable path.')
    return '\n'.join(lines)


class BuildToolPlanDialog(tk.Toplevel):
    def __init__(self, parent, component, builder, requirements, on_save, app):
        super().__init__(parent)
        self.component = component
        self.builder = builder
        self.requirements = list(requirements)
        self.on_save = on_save
        self.app = app
        self.options = {str(command): dict(setting) for command, setting in
                        (component.get('build_tool_choices') or {}).items() if isinstance(setting, dict)}
        self.report = None
        self._result_queue = queue.Queue()
        self._checking = False
        self.title('Required build tools — choose how to supply missing software')
        self.geometry('1310x690')
        self.minsize(970, 540)
        self.configure(bg='#EAF2F8')
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        tk.Label(self, text='SOURCE BUILD REQUIREMENTS', bg='#2471A3', fg='white',
                 font=('Segoe UI', 14, 'bold'), anchor='w', padx=15, pady=10).pack(fill='x')
        tk.Label(self, text='Source: ' + str(component.get('name', '')) + '    |    Docker builder: ' + str(builder),
                 bg='#D6EAF8', anchor='w', padx=12, pady=8).pack(fill='x', padx=10, pady=8)
        self.summary = tk.StringVar(value='Checking executables in the selected Docker builder...')
        tk.Label(self, textvariable=self.summary, bg='#D5F5E3', anchor='w', padx=9, pady=6).pack(fill='x', padx=12)
        frame = tk.Frame(self)
        frame.pack(fill='both', expand=True, padx=12, pady=8)
        columns = ('category', 'tool', 'status', 'version', 'location', 'suggested', 'chosen', 'evidence')
        self.tree = ttk.Treeview(frame, columns=columns, show='headings', height=12)
        specs = (('category', 'Language / tool', 130), ('tool', 'Command', 85),
                 ('status', 'Builder status', 130), ('version', 'Detected version', 160),
                 ('location', 'Detected executable', 230), ('suggested', 'Suggested OS package', 160),
                 ('chosen', 'Your chosen installation / path', 280), ('evidence', 'Build evidence', 210))
        for key, heading, width in specs:
            self.tree.heading(key, text=heading)
            self.tree.column(key, width=width, minwidth=70)
        self.tree.tag_configure('installed_status', foreground=INSTALLED_COLOR)
        self.tree.tag_configure('missing_status', foreground=MISSING_COLOR)
        scroll_y = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        scroll_x = ttk.Scrollbar(frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        scroll_y.grid(row=0, column=1, sticky='ns')
        scroll_x.grid(row=1, column=0, sticky='ew')
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        controls = tk.Frame(self, bg='#EAF2F8')
        controls.pack(fill='x', padx=12, pady=6)
        actions = (('Use suggested OS package', self._choose_suggested),
                   ('Enter a different OS package', self._choose_package),
                   ('Use existing Linux executable path', self._choose_executable),
                   ('Clear selected choice', self._clear_choice),
                   ('Add a missing requirement', self._add_requirement),
                   ('Check builder again', self._begin_check))
        for label, handler in actions:
            tk.Button(controls, text=label, command=handler, bg='#AED6F1').pack(side='left', padx=3)
        tk.Label(self, text='Installations happen ONLY in the temporary Docker builder layer after your approval. '
                 'Choosing an existing executable path checks that it is executable inside the builder. '
                 'The builder and its compilers/interpreters are not automatically copied into the final image.',
                 justify='left', anchor='w', wraplength=1250, padx=12, pady=9, bg='#FCF3CF').pack(fill='x', padx=12, pady=8)
        bottom = tk.Frame(self, bg='#EAF2F8')
        bottom.pack(fill='x', padx=14, pady=8)
        tk.Button(bottom, text='Install missing tools automatically into builder', command=self._install_missing_now,
                  bg='#27AE60', fg='white', padx=10, pady=5).pack(side='left', padx=6)
        tk.Button(bottom, text='Save tool choices', command=self._save,
                  bg='#239B56', fg='white', padx=10, pady=5).pack(side='right', padx=6)
        tk.Button(bottom, text='Cancel', command=self.destroy, padx=10, pady=5).pack(side='right', padx=6)
        self._populate()
        self._begin_check()

    def _label(self, command):
        return entry_category(command)

    def _populate(self):
        selected = self.tree.selection()
        chosen = selected[0] if selected else ''
        self.tree.delete(*self.tree.get_children())
        for item in self.requirements:
            name = item['command']
            choice = self.options.get(name, {})
            if self.report is None:
                status = 'NOT CHECKED'
                existing = {}
            else:
                existing = self.report.get('found', {}).get(name, {})
                status = 'FOUND' if existing else 'MISSING'
            suggested = suggested_package(name, self.report or {})
            chosen_text = ('Package: ' + choice['package'] if choice.get('package') else
                           'Path: ' + choice['executable'] if choice.get('executable') else '')
            self.tree.insert('', 'end', iid=name, values=(self._label(name), name, status,
                             existing.get('version', ''), existing.get('path', ''), suggested,
                             chosen_text, ', '.join(item.get('evidence', []))),
                             tags=('missing_status',) if status == 'MISSING' else ('installed_status',) if status == 'FOUND' else ())
        if chosen and self.tree.exists(chosen):
            self.tree.selection_set(chosen)

    def _begin_check(self):
        if self._checking:
            return
        self._checking = True
        self.summary.set('Checking installed commands and versions inside Docker builder ' + str(self.builder) + '...')
        known = {item['command'] for item in self.requirements}
        choices = {name: item['executable'] for name, item in self.options.items()
                   if name in known and item.get('executable')}
        def worker():
            try:
                report = inspect_builder_commands(self.builder, self.requirements, overrides=choices)
                self._result_queue.put(('ok', report))
            except Exception as exc:
                self._result_queue.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()
        self.after(120, self._check_result)

    def _check_result(self):
        try:
            status, result = self._result_queue.get_nowait()
        except queue.Empty:
            if self.winfo_exists():
                self.after(120, self._check_result)
            return
        self._checking = False
        if status == 'ok':
            self.report = result
            present = len(result['found'])
            missing = ', '.join(result['missing']) or 'none'
            self.summary.set('Builder: ' + result['distro'] + ' ' + result['distro_version'] +
                             '  |  Package manager: ' + result['manager'] + '  |  Verified: ' +
                             str(present) + '/' + str(len(self.requirements)) + '  |  Missing: ' + missing)
        else:
            self.report = None
            self.summary.set('Builder inspection failed: ' + result)
        self._populate()

    def _selected_command(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo('Select tool', 'Select a command from the table first.', parent=self)
            return ''
        return selection[0]

    def _update_choice(self, name, key, value):
        previous_path = self.options.get(name, {}).get('executable', '')
        self.options[name] = {key: value} if value else {}
        if key == 'executable' or previous_path:
            self.report = None
        self._populate()
        self.tree.selection_set(name)
        self.summary.set('Choice recorded. Save your choices to use them during compilation.'
                         if self.report is not None else
                         'Choice recorded. Check the builder again to verify executable paths before compiling.')

    def _choose_suggested(self):
        name = self._selected_command()
        if not name:
            return
        package = suggested_package(name, self.report or {})
        if not package:
            messagebox.showinfo('OS package', 'No package is identified for this builder. Enter the package name supplied by your distribution.', parent=self)
            return
        self._update_choice(name, 'package', package)

    def _install_missing_now(self):
        if self._checking or self.report is None:
            messagebox.showwarning('Builder inspection', 'Wait for the builder-tool inspection before installing.', parent=self)
            return
        missing = list(self.report.get('missing') or [])
        if not missing:
            messagebox.showinfo('Builder tools', 'All detected builder tools are already installed.', parent=self)
            return
        packages = []
        for command in missing:
            chosen = self.options.get(command, {})
            if chosen.get('executable'):
                continue
            package = chosen.get('package') or suggested_package(command, self.report)
            if package and package not in packages:
                packages.append(package)
        if not packages:
            messagebox.showwarning('No package selected', 'The missing tools do not have a known package name. '
                                   'Select Enter a different OS package to specify the distribution package name.', parent=self)
            return
        RepositoryPackageInstallDialog(self, self.app, target='builder', packages=packages,
                                       verify_commands=[name for name in missing if not self.options.get(name, {}).get('executable')],
                                       on_complete=self._automatic_install_completed)

    def _automatic_install_completed(self):
        self.builder = effective_builder_image(self.app.state)
        self.on_save()
        self._begin_check()

    def _choose_package(self):
        name = self._selected_command()
        if not name:
            return
        package = simpledialog.askstring('Choose OS package',
                                         'OS package to install in the temporary Docker builder for ' + name + ':',
                                         initialvalue=self.options.get(name, {}).get('package', ''), parent=self)
        if package is None:
            return
        try:
            values = validate_packages([package])
            if package.strip() and not values:
                raise ValueError('Enter a package name.')
        except ValueError as exc:
            messagebox.showerror('OS package', str(exc), parent=self)
            return
        self._update_choice(name, 'package', values[0] if values else '')

    def _choose_executable(self):
        name = self._selected_command()
        if not name:
            return
        path = simpledialog.askstring('Existing Linux executable',
                                      'Exact executable path inside the selected Docker builder for ' + name +
                                      ' (example: /usr/bin/python3):',
                                      initialvalue=self.options.get(name, {}).get('executable', ''), parent=self)
        if path is None:
            return
        if path.strip() and not valid_executable_path(path):
            messagebox.showerror('Executable path', 'Enter an absolute Linux executable file path without traversal.', parent=self)
            return
        self._update_choice(name, 'executable', path.strip())

    def _clear_choice(self):
        name = self._selected_command()
        if name:
            self._update_choice(name, '', '')

    def _add_requirement(self):
        name = simpledialog.askstring('Add required build command',
                                      'Executable command required by this source (examples: perl, python, javac, g++, R, Rscript):',
                                      parent=self)
        if name is None:
            return
        name = name.strip()
        if not valid_name(name):
            messagebox.showerror('Build command', 'Enter a valid executable name containing letters, digits, underscores, plus signs, dots, or hyphens.', parent=self)
            return
        if name not in recognized_names():
            messagebox.showinfo('Custom build executable', 'This executable is not yet in the recognition database. It can still be checked as a manual build requirement. Add it in Tab 10 to recognize it automatically in other source projects.', parent=self)
        if name not in {item['command'] for item in self.requirements}:
            self.requirements.append({'command': name, 'evidence': ['Manually required']})
            self.requirements = require_dependencies(self.requirements)
            self.report = None
            self._populate()
        self.tree.selection_set(name)
        self.summary.set('Manual requirement added. Check the builder to verify availability.')

    def _save(self):
        self.component['build_tool_choices'] = {name: dict(choice) for name, choice in self.options.items() if choice}
        self.component['manual_required_build_tools'] = sorted(item['command'] for item in self.requirements
            if 'Manually required' in item.get('evidence', []))
        self.on_save()
        self.destroy()


class SourcesTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg='#FEF5E7')
        self.app = app
        self._busy = False
        self._loading = False
        self._active = ''
        self._cancel_event = threading.Event()
        self._process_lock = threading.Lock()
        self._current_process = None
        self._current_container = ''
        self._messages = queue.Queue()
        self._tool_probe_cache = {}
        self._tool_probe_waiting = set()
        self._tool_probe_results = queue.Queue()
        self._tool_probe_polling = False
        self._tool_probe_current = None
        self.timeout_minutes = tk.StringVar(value='30')
        self.source_network = tk.BooleanVar(value=bool(app.state.get('allow_source_network', False)))
        self.accept_partial_output = tk.BooleanVar(value=bool(app.state.get('accept_partial_source_output', False)))
        self.requirement_summary = tk.StringVar(value='Build tools: select a source to inspect requirements.')
        self.comp = tk.StringVar()
        self.source = tk.StringVar()
        self.system = tk.StringVar()
        self.command = tk.StringVar()
        self.builddeps = tk.StringVar()
        self.outputrel = tk.StringVar()
        self.document_choice = tk.StringVar()
        self.document_link_text = tk.StringVar(value='No source documentation selected')
        self.document_paths = {}
        self.status = tk.StringVar(value='NOT COMPILED')
        tk.Label(self, text='4 — COMPILE SOURCE PROGRAMS', bg='#CA6F1E', fg='white',
                 font=('Segoe UI', 16, 'bold'), anchor='w', padx=14, pady=10).pack(fill='x')
        self.builder = tk.StringVar()
        tk.Label(self, text='Compilation engine: Docker image build + artifact extraction (NO Windows bind mounts)', bg='#FDEBD0', fg='#6E2C00', anchor='w', padx=12).pack(fill='x', padx=12, pady=(4, 0))
        tk.Label(self, textvariable=self.builder, bg='#FDEBD0', anchor='w', padx=12, pady=9).pack(fill='x', padx=12, pady=(10, 4))
        form = tk.Frame(self, bg='#FEF5E7')
        form.pack(fill='x', padx=12, pady=8)
        form.columnconfigure(1, weight=1)
        labels = [('Source component:', self.comp), ('Source folder / archive (Tab 3):', self.source),
                  ('Build system:', self.system), ('Build command:', self.command),
                  ('Compiled output (relative):', self.outputrel), ('Build-only packages (optional):', self.builddeps)]
        for row, (label, variable) in enumerate(labels):
            tk.Label(form, text=label, bg='#FEF5E7', anchor='w').grid(row=row, column=0, sticky='w', pady=5)
            if row == 0:
                widget = ttk.Combobox(form, textvariable=variable, state='readonly', width=55)
                self.combo = widget
                widget.bind('<<ComboboxSelected>>', self._select)
            elif row == 1:
                widget = tk.Entry(form, textvariable=variable, state='readonly')
            elif row == 2:
                widget = ttk.Combobox(form, textvariable=variable, values=list(BUILD_COMMANDS))
                widget.bind('<<ComboboxSelected>>', self._preset)
            elif row == 3:
                widget = ttk.Combobox(form, textvariable=variable, values=COMMON_BUILD_COMMANDS)
            else:
                widget = tk.Entry(form, textvariable=variable)
            widget.grid(row=row, column=1, sticky='ew', padx=8, pady=3)
        tk.Button(form, text='Detect output', command=lambda: self.detect_output(force=True), bg='#F0B27A').grid(row=4, column=2)
        document_bar = tk.Frame(self, bg='#FEF5E7')
        document_bar.pack(fill='x', padx=15, pady=(0, 4))
        tk.Label(document_bar, text='Source documentation:', bg='#FEF5E7').pack(side='left')
        self.document_combo = ttk.Combobox(document_bar, textvariable=self.document_choice, width=37, state='disabled')
        self.document_combo.pack(side='left', padx=(9, 8))
        self.document_combo.bind('<<ComboboxSelected>>', self._update_document_link)
        self.document_link = tk.Label(document_bar, textvariable=self.document_link_text, bg='#FEF5E7', fg='#1B4F72',
                                      font=('Segoe UI', 9, 'underline'), cursor='hand2')
        self.document_link.pack(side='left', padx=5)
        self.document_link.bind('<Button-1>', self._open_document_file)
        tk.Button(document_bar, text='View build instructions', bg='#F9E79F', command=self._view_document).pack(side='left', padx=10)
        bar = tk.Frame(self, bg='#FEF5E7')
        bar.pack(fill='x', padx=12, pady=7)
        tk.Button(bar, text='Detect build system, output && dependencies', command=self.detect, bg='#F0B27A').pack(side='left', padx=3)
        tk.Button(bar, text='Check builder tools / choose installation', command=self.open_build_tools,
                  bg='#82E0AA').pack(side='left', padx=3)
        self.compile_button = tk.Button(bar, text='Compile Source and Save Output', command=self.compile_selected, bg='#D35400', fg='white')
        self.compile_button.pack(side='left', padx=3)
        self.compile_all_button = tk.Button(bar, text='Compile All Required Sources', command=self.compile_all, bg='#A04000', fg='white')
        self.compile_all_button.pack(side='left', padx=3)
        self.stop_button = tk.Button(bar, text='Stop Compilation', command=self.stop_compilation, bg='#922B21', fg='white', state='disabled')
        self.stop_button.pack(side='left', padx=3)
        tk.Button(bar, text='Clear log', command=lambda: self.out.delete('1.0', 'end'), bg='#D6DBDF').pack(side='left', padx=3)
        timeout_bar = tk.Frame(self, bg='#FEF5E7')
        timeout_bar.pack(fill='x', padx=15)
        tk.Label(timeout_bar, text='Maximum compilation time per component (minutes):', bg='#FEF5E7').pack(side='left')
        tk.Entry(timeout_bar, textvariable=self.timeout_minutes, width=6).pack(side='left', padx=8)
        tk.Checkbutton(timeout_bar, text='Permit internet for custom source build commands (ask first)', variable=self.source_network, command=self._set_source_network, bg='#FEF5E7').pack(side='left', padx=15)
        tk.Checkbutton(self, text='Accept a verified executable if a build fails after producing it (partial build)',
                       variable=self.accept_partial_output, command=self._set_partial_output,
                       bg='#FEF5E7').pack(anchor='w', padx=15, pady=(1, 2))
        self.requirement_label = tk.Text(self, height=3, wrap='word', bg='#E8F8F5', fg='#1B4F72',
                                         relief='flat', borderwidth=0, padx=8, pady=6,
                                         font=('Segoe UI', 9), cursor='arrow', takefocus=0)
        self.requirement_label.tag_configure('installed_status', foreground=INSTALLED_COLOR,
                                            font=('Segoe UI', 9, 'bold'))
        self.requirement_label.tag_configure('missing_status', foreground=MISSING_COLOR,
                                            font=('Segoe UI', 9, 'bold'))
        self.requirement_label.pack(fill='x', padx=15, pady=(2, 4))
        self.requirement_summary.trace_add('write', lambda *_: self._render_requirement_summary())
        self.requirement_label.bind('<Configure>', lambda _: self._resize_requirement_summary())
        self._render_requirement_summary()
        tk.Label(self, textvariable=self.status, bg='#FEF5E7', fg='#784212', anchor='w', font=('Segoe UI', 10, 'bold')).pack(fill='x', padx=16, pady=4)
        tk.Label(self, text='Compiles inside the builder selected in Tab 1. Successful executables are saved for runtime library checks in Tab 5 and installation during final image creation in Tab 6. The builder is not included in the final image.',
                 bg='#FEF5E7', fg='#784212', anchor='w', justify='left', wraplength=1250).pack(fill='x', padx=15, pady=4)
        self.out = tk.Text(self, font=('Consolas', 9), height=25, wrap='none')
        self.out.tag_configure('installed_status', foreground=INSTALLED_COLOR,
                               font=('Consolas', 9, 'bold'))
        self.out.tag_configure('missing_status', foreground=MISSING_COLOR,
                               font=('Consolas', 9, 'bold'))
        self.out.pack(fill='both', expand=True, padx=12, pady=(4, 12))
        self.refresh_from_project_state()

    def _render_requirement_summary(self):
        if not self.requirement_label.winfo_exists():
            return
        self.requirement_label.configure(state='normal')
        self.requirement_label.delete('1.0', 'end')
        insert_colored_status(self.requirement_label, self.requirement_summary.get())
        self.requirement_label.configure(state='disabled')
        self._resize_requirement_summary()

    def _resize_requirement_summary(self):
        if not self.requirement_label.winfo_exists():
            return
        width = max(440, self.requirement_label.winfo_width() - 20)
        columns = max(55, width // 7)
        lines = sum(max(1, (len(line) + columns - 1) // columns)
                    for line in self.requirement_summary.get().splitlines())
        height = max(1, min(7, lines))
        if int(self.requirement_label.cget('height')) != height:
            self.requirement_label.configure(height=height)

    def _set_source_network(self):
        self.app.state['allow_source_network'] = bool(self.source_network.get())

    def _set_partial_output(self):
        self.app.state['accept_partial_source_output'] = bool(self.accept_partial_output.get())

    def _components(self):
        return self.app.state.get('components', [])

    def _selected(self):
        return next((c for c in self._components() if c.get('name') == self.comp.get() and c.get('enabled', True) and str(c.get('kind', '')).lower() == 'source'), None)

    def _save(self):
        if self._loading:
            return True
        component = next((c for c in self._components() if c.get('name') == self._active), None)
        if not component:
            return True
        output = self.outputrel.get().strip()
        if output and not normalized_relative(output):
            messagebox.showerror('Output path', 'Output must be a safe path relative to the source folder.', parent=self)
            return False
        for key, value in [('build_system', self.system.get()), ('build_command', self.command.get()),
                           ('build_deps', self.builddeps.get()), ('output_rel', output)]:
            component[key] = value.strip()
        self.app.state.touch('components')
        return True

    def _select(self, event=None):
        if not self._save():
            self.comp.set(self._active)
            return
        self.load_component()

    def refresh_from_project_state(self):
        if self._busy:
            return
        state = self.app.state
        builder = effective_builder_image(state)
        self.source_network.set(bool(state.get('allow_source_network', False)))
        self.accept_partial_output.set(bool(state.get('accept_partial_source_output', False)))
        self.builder.set('Builder (Tab 1): ' + (builder or 'NOT SELECTED') + (' (same as runtime)' if not state.get('builder_base_archive') else '') + '    |    Runtime (Tab 0): ' + (state.get('base_image', '') or 'NOT SELECTED'))
        names = [str(c.get('name', '')) for c in self._components() if c.get('enabled', True) and str(c.get('kind', '')).lower() == 'source']
        self.combo['values'] = names
        self._loading = True
        if not names:
            self.comp.set('')
            for value in (self.source, self.system, self.command, self.outputrel, self.builddeps):
                value.set('')
            self._active = ''
            self.status.set('No enabled Source components in Tab 3')
            self._refresh_documentation()
        else:
            if self.comp.get() not in names:
                self.comp.set(names[0])
        self._loading = False
        if names:
            self.load_component()

    def load_component(self):
        component = self._selected()
        if component is None:
            return
        self._loading = True
        self.source.set(component.get('source', ''))
        self.system.set(component.get('build_system', ''))
        self.command.set(component.get('build_command', ''))
        self.builddeps.set(component.get('build_deps', ''))
        self.outputrel.set(component.get('output_rel', ''))
        self._active = component.get('name', '')
        self._loading = False
        if not normalized_relative(self.outputrel.get()):
            self.detect_output(quiet=True)
        self._refresh_documentation()
        self._update_requirement_summary(component)
        self._set_status()

    def _refresh_documentation(self):
        source = Path(str(self.source.get() or '').strip())
        documents = discover_build_documentation(source)
        self.document_paths = {path.relative_to(source).as_posix(): path for path in documents}
        choices = list(self.document_paths)
        self.document_combo['values'] = choices
        if self.document_choice.get() not in self.document_paths:
            self.document_choice.set(choices[0] if choices else '')
        self.document_combo.configure(state='readonly' if choices else 'disabled')
        self._update_document_link()

    def _update_document_link(self, event=None):
        choice = self.document_choice.get()
        if choice in self.document_paths:
            self.document_link_text.set('Open ' + choice)
            self.document_link.configure(fg='#1B4F72', cursor='hand2')
        else:
            self.document_link_text.set('No README or build instructions found')
            self.document_link.configure(fg='#7B7D7D', cursor='arrow')

    def _selected_document(self):
        return self.document_paths.get(self.document_choice.get())

    def _open_document_file(self, event=None):
        path = self._selected_document()
        if path is None:
            return
        try:
            open_build_documentation(path)
        except (OSError, ValueError):
            show_build_documentation(self, path)

    def _view_document(self):
        path = self._selected_document()
        if path is None:
            messagebox.showinfo('Source documentation', 'No README or build instructions were found in the selected source folder.', parent=self)
            return
        show_build_documentation(self, path)

    def _set_status(self):
        if self._busy:
            return
        component = self._selected()
        if component is None:
            return
        record, detail = read_record(self.app.state, component)
        compilation = compilation_status(self.app.state, component)
        self.status.set(compilation['status'] + ': ' + compilation['detail'])

    def _preset(self, event=None):
        value = BUILD_COMMANDS.get(self.system.get().strip())
        if value:
            self.command.set(value)

    def detect_output(self, force=False, quiet=False):
        component = self._selected()
        if component is None:
            return
        result = detect_compiled_output(self.source.get(), self.system.get(), component.get('name', ''))
        if result.path and (force or not normalized_relative(self.outputrel.get())):
            self.outputrel.set(result.path)
        if not quiet:
            self.out.insert('end', f'Output detection: {result.message}\n')
            if result.candidates:
                self.out.insert('end', 'Candidates: ' + ', '.join(result.candidates) + '\n')
        return result

    def detect(self):
        source = Path(self.source.get().strip())
        if not (source.is_dir() or (source.is_file() and is_source_archive(source))):
            messagebox.showerror('Source', 'Select an existing source folder or a ZIP/TAR source archive in Tab 3.', parent=self)
            return
        component = self._selected()
        system, command = detect_build_system(source, component.get('name', '') if component else '')
        if command:
            self.system.set(system)
            self.command.set(command)
            self.out.insert('end', f'Build system: {system}; suggested command: {command}\n')
        else:
            self.out.insert('end', 'Build system not recognized. Enter a suitable build command.\n')
        self.detect_output(force=False)
        self.detect_requirements()
        self._save()

    def _update_requirement_summary(self, component, force=False, command_override=None):
        if not component or not str(component.get('source', '') or '').strip():
            self.requirement_summary.set('Build tools: no source selected.')
            self._tool_probe_current = None
            return
        command = (component.get('build_command', '') or self.command.get()) if command_override is None else command_override
        requirements = requirements_for_source(component, command)
        builder = effective_builder_image(self.app.state)
        names = [item['command'] for item in requirements]
        if not requirements:
            self.requirement_summary.set('Build requirements: no executable commands detected. You can add tools manually in the builder tool planner.')
            self.requirement_label.configure(bg='#E8F8F5', fg='#1B4F72')
            self._tool_probe_current = None
            return
        if not builder:
            self.requirement_summary.set('DETECTED: ' + ', '.join(names) + '\nNOT CHECKED: select and load a Docker builder image in Tabs 1–2.')
            self.requirement_label.configure(bg='#FCF3CF', fg='#7D6608')
            self._tool_probe_current = None
            return
        choices = component.get('build_tool_choices') or {}
        paths = {name: str(choices.get(name, {}).get('executable', '') or '') for name in names
                 if isinstance(choices.get(name), dict) and choices[name].get('executable')}
        key = (builder, str(component.get('source', '')), str(command),
               tuple(names), tuple(sorted(paths.items())))
        self._tool_probe_current = key
        cached = self._tool_probe_cache.get(key)
        if cached and not force and time.monotonic() - cached[0] < (8 if cached[2] else 90):
            self._show_tool_probe_result(requirements, cached[1], cached[2], choices)
            return
        self.requirement_summary.set('CHECKING BUILDER: ' + builder + '\nDetected tools: ' +
                                     ', '.join(names) + '\nChecking installed executables and versions inside Docker...')
        self.requirement_label.configure(bg='#D6EAF8', fg='#154360')
        if key in self._tool_probe_waiting:
            return
        self._tool_probe_waiting.add(key)
        def worker():
            try:
                report = inspect_builder_commands(builder, names, overrides=paths)
                self._tool_probe_results.put((key, report, ''))
            except Exception as exc:
                self._tool_probe_results.put((key, None, str(exc)))
        threading.Thread(target=worker, daemon=True).start()
        if not self._tool_probe_polling:
            self._tool_probe_polling = True
            self.after(120, self._poll_tool_probe)

    def _show_tool_probe_result(self, requirements, report, error, choices):
        if error:
            self.requirement_summary.set('BUILDER CHECK FAILED: ' + error[:550] +
                                         '\nInstallation status is unknown. Check Docker Desktop and the selected image.')
            self.requirement_label.configure(bg='#FADBD8', fg='#922B21')
            return
        self.requirement_summary.set(describe_builder_tool_status(requirements, report, choices))
        self.requirement_label.configure(bg='#FCF3CF' if report.get('missing') else '#D5F5E3',
                                         fg='#7D6608' if report.get('missing') else '#196F3D')

    def _poll_tool_probe(self):
        try:
            while True:
                key, report, error = self._tool_probe_results.get_nowait()
                self._tool_probe_waiting.discard(key)
                self._tool_probe_cache[key] = (time.monotonic(), report, error)
                if key == self._tool_probe_current:
                    component = self._selected()
                    if component is not None:
                        requirements = requirements_for_source(component, key[2])
                        self._show_tool_probe_result(requirements, report, error,
                                                     component.get('build_tool_choices') or {})
                        if not self._busy:
                            self.out.insert('end', '\nBuilder tool availability check:\n')
                            if error:
                                self.out.insert('end', '  CHECK FAILED: ' + error[:650] + '\n')
                            else:
                                for item in requirements:
                                    command = item['command']
                                    info = report['found'].get(command)
                                    if info:
                                        insert_colored_status(self.out, '  ' + command + ': INSTALLED at ' +
                                                              info.get('path', '') +
                                                              (' | ' + info['version'] if info.get('version') else '') + '\n')
                                    else:
                                        package = suggested_package(command, report)
                                        insert_colored_status(self.out, '  ' + command + ': MISSING from selected builder' +
                                                              (' | suggested package: ' + package if package else '') + '\n')
                            self.out.see('end')
        except queue.Empty:
            pass
        if self._tool_probe_waiting:
            self.after(120, self._poll_tool_probe)
        else:
            self._tool_probe_polling = False

    def detect_requirements(self):
        component = self._selected()
        if component is None:
            return
        requirements = requirements_for_source(component, self.command.get())
        self._update_requirement_summary(component, force=True, command_override=self.command.get())
        self.out.insert('end', 'Source build requirements:\n')
        for item in requirements:
            self.out.insert('end', '  ' + item['command'] + ' <- ' + ', '.join(item['evidence']) + '\n')
        if not requirements:
            self.out.insert('end', '  No known executable requirements detected; manual build packages remain available.\n')
        self.out.see('end')

    def open_build_tools(self):
        if self._busy or not self._save():
            return
        component = self._selected()
        if component is None:
            return
        source = Path(str(component.get('source', '') or '').strip())
        if not (source.is_dir() or (source.is_file() and is_source_archive(source))):
            messagebox.showerror('Source', 'Select a source folder or a ZIP/TAR archive in Tab 3.', parent=self)
            return
        builder = effective_builder_image(self.app.state)
        if not builder:
            messagebox.showerror('Builder', 'Select and load a Docker builder image in Tabs 1–2.', parent=self)
            return
        requirements = requirements_for_source(component)
        BuildToolPlanDialog(self, component, builder, requirements,
                            lambda: (self.app.state.touch('components'), self._update_requirement_summary(component, force=True)),
                            self.app)

    def _automatic_settings(self, component):
        source = Path(str(component.get('source', '') or '').strip())
        if not (source.is_dir() or (source.is_file() and is_source_archive(source))):
            raise ValueError('Source folder or ZIP/TAR archive does not exist: ' + str(source))
        if not str(component.get('build_command', '') or '').strip():
            system, command = detect_build_system(source, component.get('name', ''))
            if command:
                component['build_system'] = system
                component['build_command'] = command
        if not str(component.get('build_command', '') or '').strip():
            raise ValueError('Cannot detect a build command. Select this component in Tab 4 and enter the command.')
        if not normalized_relative(component.get('output_rel', '')):
            result = detect_compiled_output(str(source), component.get('build_system', ''), component.get('name', ''))
            if not normalized_relative(result.path):
                raise ValueError('Cannot determine the compiled output: ' + result.message)
            component['output_rel'] = result.path
        return component

    def _log_drain(self):
        try:
            while True:
                message = self._messages.get_nowait()
                if isinstance(message, tuple) and message[0] == 'finish':
                    self._finish_compile(message[1], message[2])
                elif isinstance(message, tuple) and message[0] == 'approval':
                    _, builder, report, extra_network, response, signal = message
                    response['approved'] = messagebox.askyesno('Approve builder downloads', permission_message('builder', builder, report, extra_network), parent=self)
                    signal.set()
                else:
                    insert_colored_status(self.out, str(message))
                    self.out.see('end')
        except queue.Empty:
            pass
        if self._busy or not self._messages.empty():
            self.after(100, self._log_drain)

    def _log(self, message):
        self._messages.put(str(message))

    def _preflight(self, builder):
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        args = ['docker', 'info', '--format', '{{.OSType}}']
        try:
            result = subprocess.run(args, capture_output=True, text=True, errors='replace',
                                    stdin=subprocess.DEVNULL, timeout=15, creationflags=flags)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('Docker did not respond within 15 seconds. Check that Docker Desktop and the Linux engine are running.') from exc
        except OSError as exc:
            raise RuntimeError('Cannot start docker.exe: ' + str(exc)) from exc
        if result.returncode != 0:
            raise RuntimeError('Docker Engine is unavailable: ' + (result.stderr or result.stdout or '').strip()[:1200])
        if result.stdout.strip() != 'linux':
            raise RuntimeError('Docker is not running Linux containers. Switch Docker Desktop to Linux containers.')
        try:
            checked = subprocess.run(['docker', 'image', 'inspect', builder], capture_output=True,
                                     text=True, errors='replace', stdin=subprocess.DEVNULL,
                                     timeout=15, creationflags=flags)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('Docker image inspection timed out after 15 seconds.') from exc
        if checked.returncode != 0:
            raise RuntimeError('Builder image is not available locally: ' + builder + '. Load it in Tab 2. ' + (checked.stderr or '')[:600])
        self._log('Docker Linux Engine: READY\nBuilder image: ' + builder + ' (available locally)\n')

    def _abort_process(self):
        with self._process_lock:
            process = self._current_process
            container = self._current_container
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
            try:
                process.wait(timeout=2)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    process.kill()
                except OSError:
                    pass
        if container:
            try:
                subprocess.run(['docker', 'rm', '-f', container], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                               timeout=7, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except (subprocess.TimeoutExpired, OSError):
                pass

    def stop_compilation(self):
        if not self._busy:
            return
        self._cancel_event.set()
        self.stop_button.config(state='disabled')
        self.status.set('STOPPING: terminating the active Docker compilation')
        self._log('\nSTOP REQUESTED: stopping the active build.\n')
        threading.Thread(target=self._abort_process, daemon=True).start()

    def _run_docker_step(self, args, append, deadline, label, max_step_seconds=None):
        if self._cancel_event.is_set():
            raise RuntimeError('Compilation cancelled by user.')
        append('\n' + label + '\n$ ' + subprocess.list2cmdline(args) + '\n')
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, errors='replace',
                                   bufsize=1, creationflags=flags)
        with self._process_lock:
            self._current_process = process
        lines = []
        def reader():
            try:
                for line in process.stdout:
                    lines.append(line)
                    append(line)
            except (OSError, ValueError) as exc:
                append('Docker output reader: ' + str(exc) + '\n')
        reader_thread = threading.Thread(target=reader, daemon=True)
        reader_thread.start()
        started = time.monotonic()
        last_heartbeat = started
        try:
            while process.poll() is None:
                if self._cancel_event.is_set():
                    self._abort_process()
                    raise RuntimeError('Compilation cancelled by user.')
                now = time.monotonic()
                if now >= deadline or (max_step_seconds is not None and now - started > max_step_seconds):
                    self._abort_process()
                    raise RuntimeError(label + ' timed out after ' + str(int(now - started)) +
                                       ' seconds. Check Docker Desktop and its Linux engine.')
                if now - last_heartbeat >= 5:
                    append(label + ': waiting ' + str(int(now - started)) + ' s for Docker to finish.\n')
                    last_heartbeat = now
                time.sleep(0.15)
            reader_thread.join(timeout=3)
            code = process.returncode
            append(label + ' exit code: ' + str(code) + '\n')
            if code != 0:
                raise RuntimeError(label + ' failed (exit ' + str(code) + '): ' +
                                   ''.join(lines)[-1800:])
            return any('COMPONENT-PARTIAL-BUILD:' in line for line in lines)
        finally:
            with self._process_lock:
                if self._current_process is process:
                    self._current_process = None
            if process.stdout is not None:
                process.stdout.close()

    def _perform_compilation(self, component, builder, append, timeout_seconds, missing_packages=(), network_enabled=False, accept_partial_output=False, selected_packages=(), required_commands=(), tool_paths=None):
        if self._cancel_event.is_set():
            raise RuntimeError('Cancelled by user.')
        self._automatic_settings(component)
        work = prepare_workspace(self.app.state, component)
        relative = normalized_relative(component.get('output_rel', ''))
        if not relative:
            raise RuntimeError('Compiled output path is missing.')
        command = str(component['build_command']).strip()
        packages = validate_packages(str(component.get('build_deps', '') or '').split(',') + list(selected_packages))
        missing = sorted(set(packages).intersection(missing_packages))
        if missing:
            words = ' '.join(shlex.quote(package) for package in missing)
            setup = ('if command -v apt-get >/dev/null 2>&1; then apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y ' + words + '; '
                     'elif command -v apk >/dev/null 2>&1; then apk add --no-cache ' + words + '; '
                     'elif command -v dnf >/dev/null 2>&1; then dnf install -y ' + words + '; '
                     'elif command -v microdnf >/dev/null 2>&1; then microdnf install -y ' + words + '; '
                     'else echo Unsupported package manager; exit 31; fi')
            command = setup + ' && ' + command
        command_check = builder_command_preflight(required_commands, allow_missing=accept_partial_output,
                                                 overrides=tool_paths)
        if command_check:
            if missing:
                command = setup + ' && ' + command_check + ' && ' + str(component['build_command']).strip()
            else:
                command = command_check + ' && ' + command
        if accept_partial_output:
            command = build_command_with_output_fallback(command, relative)
        token = uuid.uuid4().hex[:16]
        image_tag = 'local/component-build-' + token
        container_name = 'docker-component-extract-' + token
        dockerfile = work / '.component-build.Dockerfile'
        transfer = 'ADD .source.tar /src/\n' if is_source_archive(component.get('source', '')) else 'COPY . /src\n'
        dockerfile.write_text('FROM ' + builder + '\nWORKDIR /src\n' + transfer + 'RUN ' + command + '\n', encoding='utf-8')
        deadline = time.monotonic() + timeout_seconds
        with self._process_lock:
            self._current_container = container_name
        append('Compiler module loaded: ' + str(Path(__file__).resolve()) + '\n')
        append('Compilation pipeline: docker build -> docker create -> docker cp -> cleanup. No bind mounts.\n')
        try:
            partial_build = self._run_docker_step(
                ['docker', 'build', '--pull=false', '--network=' + ('default' if network_enabled else 'none'), '--progress=plain', '--file', str(dockerfile),
                 '--tag', image_tag, str(work)],
                append, deadline, 'Compiling source using docker build')
            self._run_docker_step(
                ['docker', 'create', '--name', container_name, '--entrypoint', '/bin/sh',
                 image_tag, '-c', 'exit 0'],
                append, deadline, 'Creating stopped container for output extraction', 60)
            output = work.joinpath(*relative.split('/'))
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.exists():
                if output.is_dir():
                    raise RuntimeError('Compiled output path refers to a directory; select an executable file.')
                output.unlink()
            self._run_docker_step(
                ['docker', 'cp', '-L', container_name + ':/src/' + relative, str(output)],
                append, deadline, 'Copying compiled executable to the managed artifacts folder', 120)
            if not output.is_file() or output.stat().st_size == 0:
                raise RuntimeError('Docker copy returned without producing an executable: ' + str(output))
        finally:
            with self._process_lock:
                self._current_container = ''
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            try:
                subprocess.run(['docker', 'rm', '-f', container_name], capture_output=True,
                               text=True, errors='replace', stdin=subprocess.DEVNULL,
                               timeout=12, creationflags=flags)
            except (subprocess.TimeoutExpired, OSError) as exc:
                append('Container cleanup warning: ' + str(exc) + '\n')
            try:
                subprocess.run(['docker', 'image', 'rm', image_tag], capture_output=True,
                               text=True, errors='replace', stdin=subprocess.DEVNULL,
                               timeout=12, creationflags=flags)
            except (subprocess.TimeoutExpired, OSError) as exc:
                append('Temporary build image cleanup warning: ' + str(exc) + '\n')
            try:
                dockerfile.unlink(missing_ok=True)
            except OSError:
                pass
        if self._cancel_event.is_set():
            raise RuntimeError('Compilation cancelled by user.')
        record = register_output(self.app.state, component, work)
        record['build_status'] = 'partial' if partial_build else 'complete'
        if partial_build:
            component['compile_warning'] = 'Build command returned an error; the requested executable was recovered and its format verified.'
            record['build_warning'] = component['compile_warning']
            append('WARNING: PARTIAL BUILD. The executable was saved, but the build command did not finish successfully. Review missing optional outputs and run verification in Tab 7.\n')
        else:
            component.pop('compile_warning', None)
            if required_commands:
                if accept_partial_output:
                    component['builder_tool_status'] = {
                        command: ('verified_before_build' if
                                  component.get('builder_tool_status', {}).get(command) == 'verified'
                                  else 'not_verified_after_build') for command in required_commands}
                else:
                    component['builder_tool_status'] = {command: 'verified_during_build' for command in required_commands}
                for tool in required_commands:
                    details = component.setdefault('builder_tool_details', {}).setdefault(tool, {})
                    details['build_status'] = component['builder_tool_status'][tool]
        append('Compiled Linux executable copied and saved successfully.\n')
        append('Saved compiled output: ' + record['artifact'] + '\nSHA-256: ' + record['sha256'] + '\n')
        append('Build artifact verified. Version checks can run in the completed image (Tab 7).\n')
        return record

    def _finish_compile(self, counts, fatal):
        self._busy = False
        self.compile_button.config(state='normal')
        self.compile_all_button.config(state='normal')
        self.stop_button.config(state='disabled')
        self._loading = True
        selected = self._selected()
        if selected is not None:
            self.system.set(selected.get('build_system', ''))
            self.command.set(selected.get('build_command', ''))
            self.outputrel.set(selected.get('output_rel', ''))
            self.builddeps.set(selected.get('build_deps', ''))
        self._loading = False
        self.app.state.touch('components')
        if self._cancel_event.is_set():
            summary = 'CANCELLED BY USER'
        elif fatal:
            summary = 'DOCKER ERROR: ' + fatal
        elif counts['failed']:
            summary = 'BUILD FAILED: ' + str(counts['failed']) + ' failed, ' + str(counts['compiled']) + ' compiled'
        else:
            summary = 'COMPLETED: ' + str(counts['compiled']) + ' compiled, ' + str(counts['skipped']) + ' already current'
        self.status.set(summary)
        self._log('\n' + summary + '\n')
        if hasattr(self.app, 'components_tab'):
            self.app.components_tab.refresh()

    def _start_compile(self, components, *, skip_current):
        if self._busy:
            return
        if not self._save():
            return
        builder = effective_builder_image(self.app.state)
        if not builder:
            messagebox.showerror('Compile', 'Select a runtime image in Tab 1 and load it in Tab 2, or select a separate builder image.', parent=self)
            return
        targets = [component for component in components if component.get('enabled', True) and str(component.get('kind', '')).strip().lower() == 'source']
        if not targets:
            messagebox.showinfo('Compile', 'There are no enabled source components to compile.', parent=self)
            return
        try:
            timeout_seconds = int(float(self.timeout_minutes.get().strip()) * 60)
            if not 30 <= timeout_seconds <= 86400:
                raise ValueError()
        except ValueError:
            messagebox.showerror('Compile', 'Enter a compilation timeout from 0.5 to 1440 minutes.', parent=self)
            return
        self._busy = True
        accept_partial_output = bool(self.accept_partial_output.get())
        self._cancel_event.clear()
        self.compile_button.config(state='disabled')
        self.compile_all_button.config(state='disabled')
        self.stop_button.config(state='normal')
        self.out.delete('1.0', 'end')
        self._log('ACTIVE COMPILER: docker build (without bind mounts)\nSOURCE MODULE: ' + str(Path(__file__).resolve()) + '\n')
        self.status.set('COMPILING: checking Docker, then processing ' + str(len(targets)) + ' source component(s)')
        self._log_drain()
        def worker():
            counts = {'compiled': 0, 'skipped': 0, 'failed': 0}
            failures = self.app.state.setdefault('compilation_failures', {})
            fatal = ''
            try:
                self._preflight(builder)
                active_targets = [component for component in targets if not (skip_current and compilation_status(self.app.state, component)['status'] in ('COMPILED', 'INSTALLED IN RUNTIME'))]
                tool_requirements = {}
                for component in active_targets:
                    name = str(component.get('name', '') or '')
                    try:
                        self._automatic_settings(component)
                        requirements = requirements_for_source(component)
                    except (OSError, ValueError) as exc:
                        self._log('BUILD REQUIREMENT SCAN: ' + name + ': ' + str(exc) + '\n')
                        requirements = []
                    tool_requirements[name] = requirements
                    component['detected_build_tools'] = requirements
                commands = sorted({item['command'] for requirements in tool_requirements.values() for item in requirements})
                inspection_commands = list(commands)
                if 'python' in commands and 'python3' not in inspection_commands:
                    inspection_commands.append('python3')
                tool_report = inspect_builder_commands(builder, inspection_commands)
                self._log('Builder OS: ' + tool_report['distro'] + ' ' + tool_report['distro_version'] +
                          ' | Package manager: ' + tool_report['manager'] + '\n')
                for command in commands:
                    sources = sorted({str(component.get('name', '')) + ' (' + ', '.join(item['evidence']) + ')'
                                      for component in active_targets for item in tool_requirements.get(str(component.get('name', '')), [])
                                      if item['command'] == command})
                    if command in tool_report['found']:
                        info = tool_report['found'][command]
                        self._log('FOUND BUILD TOOL: ' + command + ' at ' + info['path'] +
                                  (' | ' + info['version'] if info['version'] else '') + '\n')
                    else:
                        self._log('MISSING BUILD TOOL: ' + command + ' required by ' + '; '.join(sources) + '\n')
                if 'python' in tool_report['missing'] and 'python3' in tool_report['found']:
                    self._log('NOTE: python3 exists, but the python command is missing. Python 3 compatibility and an alias must be checked before substitution.\n')
                selected_packages = {}
                manually_selected_packages = set()
                selected_paths = {}
                unresolved = []
                for component in active_targets:
                    name = str(component.get('name', '') or '')
                    needed = {item['command'] for item in tool_requirements.get(name, [])}
                    choices = component.get('build_tool_choices') or {}
                    paths = {command: str(choices.get(command, {}).get('executable', '') or '')
                             for command in needed if isinstance(choices.get(command), dict)
                             and choices[command].get('executable')}
                    selected_paths[name] = paths
                    local_report = (inspect_builder_commands(builder, sorted(needed), overrides=paths)
                                    if paths else tool_report)
                    selected_packages[name] = []
                    for command in sorted(needed.intersection(local_report['missing'])):
                        package = suggested_package(command, tool_report)
                        if package:
                            self._log('AVAILABLE PACKAGE SUGGESTION: ' + command + ' -> ' + package +
                                      ' (not selected for installation)\n')
                        else:
                            self._log('NO PACKAGE SUGGESTION: ' + command +
                                      '. Choose a package or existing executable path in the tool planner.\n')
                        setting = choices.get(command) if isinstance(choices.get(command), dict) else {}
                        chosen_package = str(setting.get('package', '') or '').strip()
                        if chosen_package:
                            validated = validate_packages([chosen_package])[0]
                            selected_packages[name].append(validated)
                            manually_selected_packages.add(validated)
                            self._log('USER-SELECTED BUILDER PACKAGE: ' + command + ' -> ' + validated + '\n')
                        elif not str(component.get('build_deps', '') or '').strip():
                            unresolved.append(name + ': ' + command)
                    component['builder_tool_status'] = {command: ('verified' if command in local_report['found'] else 'missing')
                                                        for command in needed}
                    component['builder_tool_details'] = {
                        command: {'base_status': 'verified' if command in local_report['found'] else 'missing',
                                  'executable': local_report['found'].get(command, {}).get('path', ''),
                                  'version': local_report['found'].get(command, {}).get('version', ''),
                                  'manual_path_requested': paths.get(command, ''),
                                  'chosen_package': str((choices.get(command) or {}).get('package', '')),
                                  'build_status': 'pending'}
                        for command in sorted(needed)}
                    component['suggested_builder_packages'] = list(selected_packages[name])
                    for command, path in paths.items():
                        if command in local_report['found']:
                            self._log('USER-SELECTED EXISTING EXECUTABLE VERIFIED: ' + command + ' -> ' + path + '\n')
                        else:
                            self._log('USER-SELECTED EXECUTABLE NOT FOUND: ' + command + ' -> ' + path + '\n')
                all_packages = validate_packages(package_names(active_targets, 'builder') + list(manually_selected_packages))
                inspection = inspect_packages(builder, all_packages)
                self._log('Builder packages already installed: ' + (', '.join(inspection['installed']) or 'none') + '\n')
                self._log('Builder packages missing: ' + (', '.join(inspection['missing']) or 'none') + '\n')
                policy = normalize_policy(self.app.state.get('package_download_policy'))
                extra_network = bool(self.app.state.get('allow_source_network', False)) and bool(active_targets)
                if unresolved and not accept_partial_output:
                    raise RuntimeError('Missing builder commands without your installation choice: ' + ', '.join(unresolved) +
                                       '. Open "Check builder tools / choose installation" and choose an OS package or valid executable path.')
                packages_to_install = list(inspection['missing'])
                if policy == POLICY_OFFLINE and (inspection['missing'] or extra_network):
                    self._log('OFFLINE: no missing builder packages will be downloaded or installed.\n')
                    packages_to_install = []
                    if extra_network or not accept_partial_output:
                        raise RuntimeError('Offline-only mode cannot install the detected missing builder tools. Supply a complete builder or enable partial builds.')
                network_enabled = False
                if policy != POLICY_OFFLINE and (inspection['missing'] or extra_network):
                    response = {}
                    signal = threading.Event()
                    self._messages.put(('approval', builder, inspection, extra_network, response, signal))
                    if not signal.wait(timeout=600):
                        raise RuntimeError('Network approval timed out.')
                    if not response.get('approved'):
                        raise RuntimeError('Network access was not approved. No online compilation started.')
                    network_enabled = True
                self._log('Build-tool preflight will be repeated inside the compilation image after approved package installation.\n')
                for component in targets:
                    if self._cancel_event.is_set():
                        break
                    name = str(component.get('name', '') or '').strip()
                    if skip_current and compilation_status(self.app.state, component)['status'] in ('COMPILED', 'INSTALLED IN RUNTIME'):
                        counts['skipped'] += 1
                        self._log('SKIPPED (compiled or already present in the runtime image): ' + name + '\n')
                        continue
                    try:
                        name_requirements = tool_requirements.get(name, [])
                        record = self._perform_compilation(component, builder, self._log, timeout_seconds,
                                                           packages_to_install, network_enabled, accept_partial_output,
                                                           selected_packages.get(name, []),
                                                           [item['command'] for item in name_requirements],
                                                           selected_paths.get(name, {}))
                        verified, explanation = read_record(self.app.state, component)
                        if not verified:
                            raise RuntimeError('Compiled output was saved, but status verification failed: ' + explanation)
                        failures.pop(name, None)
                        counts['compiled'] += 1
                        self._log('SUCCESS: ' + name + ' => ' + record['artifact'] + '\n')
                    except Exception as exc:
                        detail = str(exc)
                        if self._cancel_event.is_set():
                            self._log('CANCELLED: ' + name + ': ' + detail + '\n')
                            break
                        failures[name] = {'error': detail, 'failed_at': datetime.now(timezone.utc).isoformat()}
                        counts['failed'] += 1
                        self._log('FAILED: ' + name + ': ' + detail + '\n')
            except Exception as exc:
                fatal = str(exc)
                self._log('DOCKER ERROR: ' + fatal + '\n')
            self._messages.put(('finish', counts, fatal))
        threading.Thread(target=worker, daemon=True).start()

    def compile_selected(self):
        component = self._selected()
        if component is None:
            messagebox.showerror('Compile', 'Select an enabled Source component in Tab 4.', parent=self)
            return
        self._start_compile([component], skip_current=False)

    def compile_all(self):
        self._start_compile(list(self._components()), skip_current=True)
