import json
import os
import subprocess
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from builder_presets import (ARCHITECTURES, DISTRIBUTIONS, OPTIONS, build_spec,
                             detect_runtime_image_system, matching_runtime,
                             preferred_preset, timestamp_tag)
from docker_image_checkpoint import load_image_checkpoint, save_image_checkpoint
from project_state import effective_builder_image


class BuilderBaseTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg='#F5F7F9')
        self.app = app
        self._busy = False
        self._autofollow = True
        self._runtime_signature = None
        self._updating = False
        self.mode = tk.StringVar(value='runtime')
        self.distribution = tk.StringVar(value='Debian')
        self.version = tk.StringVar(value='12')
        self.architecture = tk.StringVar(value='linux/amd64')
        self.preset = tk.StringVar(value=OPTIONS[0])
        self.source_override = tk.StringVar(value=str(app.state.get('builder_source_override') or ''))
        self.runtime_description = tk.StringVar(value='Runtime image has not been selected in Tab 0.')
        self.selection_description = tk.StringVar(value='Builder: same as runtime')
        self.suggestion = tk.StringVar(value='')
        self.status = tk.StringVar(value='Ready')

        tk.Label(self, text='1 — BUILDER BASE / COMPILATION ENVIRONMENT', bg='#6C3483', fg='white',
                 font=('Segoe UI', 16, 'bold'), anchor='w', padx=14, pady=10).pack(fill='x')
        tk.Label(self, text='The builder is used for compiling software. Only selected build artifacts are copied to the final runtime image.',
                 bg='#E8DAEF', fg='#512E5F', anchor='w', padx=12, pady=8).pack(fill='x')

        runtime_box = tk.LabelFrame(self, text='Runtime base selected in Tab 0 (read-only reference)',
                                    bg='#EAF3FA', fg='#154360', font=('Segoe UI', 10, 'bold'), padx=12, pady=9)
        runtime_box.pack(fill='x', padx=12, pady=(10, 8))
        tk.Label(runtime_box, textvariable=self.runtime_description, bg='#EAF3FA', fg='#154360',
                 justify='left', anchor='w', wraplength=1220).pack(fill='x')
        actions = tk.Frame(runtime_box, bg='#EAF3FA')
        actions.pack(fill='x', pady=(5, 0))
        tk.Button(actions, text='Match builder preset to runtime', bg='#D6EAF8',
                  command=self.match_runtime).pack(side='left')
        tk.Button(actions, text='Inspect runtime OS / architecture', bg='#D6EAF8',
                  command=self.probe_runtime).pack(side='left', padx=7)

        mode_frame = tk.LabelFrame(self, text='Builder selection', bg='#F5F7F9', fg='#424949',
                                   font=('Segoe UI', 10, 'bold'), padx=12, pady=9)
        mode_frame.pack(fill='x', padx=12, pady=(0, 8))
        tk.Radiobutton(mode_frame, text='Use the runtime base as builder (no separate builder download)',
                       variable=self.mode, value='runtime', bg='#F5F7F9',
                       command=self.change_mode).pack(anchor='w')
        tk.Radiobutton(mode_frame, text='Use a separate builder image / TAR', variable=self.mode,
                       value='separate', bg='#F5F7F9', command=self.change_mode).pack(anchor='w')
        tk.Label(mode_frame, textvariable=self.selection_description, bg='#F5F7F9', fg='#2874A6',
                 anchor='w', justify='left', wraplength=1200).pack(fill='x', pady=(7, 3))
        tk.Button(mode_frame, text='Load existing builder .tar', bg='#2874A6', fg='white',
                  command=self.select_builder_tar).pack(anchor='w')

        preset_box = tk.LabelFrame(self, text='Download a builder: distribution / release / CPU architecture',
                                   bg='#F4ECF7', fg='#512E5F', font=('Segoe UI', 10, 'bold'), padx=12, pady=10)
        preset_box.pack(fill='x', padx=12, pady=(0, 8))
        preset_box.columnconfigure(1, weight=1)
        preset_box.columnconfigure(3, weight=1)
        self.dist_combo = ttk.Combobox(preset_box, textvariable=self.distribution,
                                       values=tuple(DISTRIBUTIONS), state='readonly', width=27)
        self.version_combo = ttk.Combobox(preset_box, textvariable=self.version, width=22)
        self.arch_combo = ttk.Combobox(preset_box, textvariable=self.architecture,
                                      values=ARCHITECTURES, state='readonly', width=22)
        self.preset_combo = ttk.Combobox(preset_box, textvariable=self.preset,
                                        values=OPTIONS, state='readonly', width=52)
        tk.Label(preset_box, text='Linux distribution', bg='#F4ECF7').grid(row=0, column=0, sticky='w', pady=4)
        self.dist_combo.grid(row=0, column=1, sticky='ew', padx=8, pady=4)
        tk.Label(preset_box, text='Release / version', bg='#F4ECF7').grid(row=0, column=2, sticky='w', pady=4)
        self.version_combo.grid(row=0, column=3, sticky='ew', padx=8, pady=4)
        tk.Label(preset_box, text='CPU architecture', bg='#F4ECF7').grid(row=1, column=0, sticky='w', pady=4)
        self.arch_combo.grid(row=1, column=1, sticky='ew', padx=8, pady=4)
        tk.Label(preset_box, text='Builder preset', bg='#F4ECF7').grid(row=1, column=2, sticky='w', pady=4)
        self.preset_combo.grid(row=1, column=3, sticky='ew', padx=8, pady=4)
        self.dist_combo.bind('<<ComboboxSelected>>', self.distribution_changed)
        for cb in (self.version_combo, self.arch_combo, self.preset_combo):
            cb.bind('<<ComboboxSelected>>', self.user_changed)
            cb.bind('<KeyRelease>', self.user_changed)
        tk.Label(preset_box, text='Custom Docker image (optional)', bg='#F4ECF7').grid(row=2, column=0, sticky='w', pady=4)
        source_entry = tk.Entry(preset_box, textvariable=self.source_override)
        source_entry.grid(row=2, column=1, columnspan=3, sticky='ew', padx=8, pady=4)
        source_entry.bind('<KeyRelease>', self.user_changed)
        source_entry.bind('<FocusOut>', self.user_changed)
        tk.Label(preset_box, textvariable=self.suggestion, bg='#F4ECF7', fg='#6C3483',
                 anchor='w', justify='left', wraplength=1180).grid(row=3, column=0, columnspan=4, sticky='ew', pady=(6, 9))
        buttons = tk.Frame(preset_box, bg='#F4ECF7')
        buttons.grid(row=4, column=0, columnspan=4, sticky='w')
        self.download_button = tk.Button(buttons, text='Download / create builder and save as TAR',
                                         bg='#117864', fg='white', font=('Segoe UI', 10, 'bold'),
                                         command=self.download_builder)
        self.download_button.pack(side='left', padx=(0, 9))
        tk.Button(buttons, text='Preview builder selection', command=self.preview).pack(side='left')
        tk.Label(preset_box, text='Downloads require confirmation. Platform availability is checked during Docker pull. A full toolkit may require building a new image with internet access.',
                 bg='#F4ECF7', fg='#5D6D7E', anchor='w', wraplength=1180).grid(row=5, column=0, columnspan=4, sticky='ew', pady=(7, 0))

        log_box = tk.LabelFrame(self, text='Builder activity and validation', bg='#F5F7F9',
                                fg='#424949', font=('Segoe UI', 10, 'bold'), padx=10, pady=7)
        log_box.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        top = tk.Frame(log_box, bg='#F5F7F9')
        top.pack(fill='x')
        tk.Label(top, textvariable=self.status, bg='#F5F7F9', fg='#154360').pack(side='left')
        tk.Button(top, text='Clear log', command=lambda: self.output.delete('1.0', 'end')).pack(side='right')
        self.output = scrolledtext.ScrolledText(log_box, font=('Consolas', 9), height=10, wrap='word')
        self.output.pack(fill='both', expand=True, pady=(5, 0))
        self.refresh_from_project_state()

    def _line(self, line):
        self.output.insert('end', str(line).rstrip('\n') + '\n')
        self.output.see('end')

    def _progress(self, line):
        try:
            self.after(0, lambda s=str(line): self._line(s))
        except RuntimeError:
            pass

    def _working(self, busy):
        self._busy = busy
        self.download_button.configure(state='disabled' if busy else 'normal')
        self.status.set('Docker image operation in progress...' if busy else 'Ready')

    def refresh_from_project_state(self):
        state = self.app.state
        system = state.get('base_system') or {}
        if not isinstance(system, dict):
            system = {}
        distro, version, platform = matching_runtime(system)
        self.runtime_description.set('Tag: ' + (str(state.get('base_image') or '') or '(not selected)') +
                                     '     TAR: ' + (str(state.get('runtime_base_archive') or '') or '(not recorded)') +
                                     '\nOS: ' + (str(system.get('os') or system.get('id') or 'unknown')) +
                                     '     Version: ' + (str(system.get('version_id') or 'unknown')) +
                                     '     CPU: ' + (str(system.get('architecture') or 'unknown')))
        mode = state.get('builder_mode', 'runtime')
        if mode not in ('runtime', 'separate'):
            mode = 'separate' if state.get('builder_image') else 'runtime'
        self.mode.set(mode)
        if mode == 'runtime':
            self.selection_description.set('Builder: same as runtime  |  ' + (effective_builder_image(state) or 'no runtime image loaded'))
        else:
            self.selection_description.set('Separate builder tag: ' + (str(state.get('builder_image') or '') or 'NOT LOADED') +
                                           '\nTAR: ' + (str(state.get('builder_base_archive') or '') or '(not yet saved)'))
        signature = (str(state.get('base_image') or ''), distro, version, platform)
        if signature != self._runtime_signature:
            self._runtime_signature = signature
            if self._autofollow:
                self._set_runtime_preset(distro, version, platform)
        if not self.source_override.get() and state.get('builder_source_override'):
            self.source_override.set(str(state.get('builder_source_override') or ''))
        self._update_suggestion()

    def _set_runtime_preset(self, distro, version, platform):
        self._updating = True
        try:
            if distro in DISTRIBUTIONS:
                self.distribution.set(distro)
                self.version_combo.configure(values=DISTRIBUTIONS[distro]['versions'])
                if version:
                    self.version.set(version)
                else:
                    self.version.set(DISTRIBUTIONS[distro]['versions'][0])
            if platform in ARCHITECTURES:
                self.architecture.set(platform)
            self.preset.set(preferred_preset(self.distribution.get(), self.version.get()))
        finally:
            self._updating = False

    def match_runtime(self):
        self._autofollow = True
        state = self.app.state
        system = state.get('base_system') or {}
        distro, version, platform = matching_runtime(system)
        if not distro or not version or not platform:
            messagebox.showwarning('Runtime metadata incomplete',
                                   'The runtime distribution, version or architecture could not be determined. '
                                   'Click Inspect runtime OS / architecture, or inspect the TAR in Tab 2.', parent=self)
        self.source_override.set('')
        self.app.state['builder_source_override'] = ''
        self._set_runtime_preset(distro, version, platform)
        self._update_suggestion()

    def probe_runtime(self):
        if self._busy:
            return
        image = str(self.app.state.get('base_image') or '').strip()
        if not image:
            messagebox.showwarning('No runtime', 'Load the runtime image in Tab 0 first.', parent=self)
            return
        self._working(True)
        self._line('Inspecting runtime OS and architecture: ' + image)

        def worker():
            found = detect_runtime_image_system(image)
            def finish():
                self._working(False)
                if found:
                    old = self.app.state.get('base_system') or {}
                    self.app.state['base_system'] = {**old, **found}
                    self._line('Runtime metadata: ' + str(found))
                    self._autofollow = True
                    self._runtime_signature = None
                    self.refresh_from_project_state()
                else:
                    self._line('No metadata returned. The image may not contain /bin/sh or /etc/os-release.')
            self.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    def change_mode(self):
        if self._busy:
            return
        value = self.mode.get()
        self.app.state['builder_mode'] = value
        self.refresh_from_project_state()

    def distribution_changed(self, event=None):
        if self._updating:
            return
        self._autofollow = False
        distro = self.distribution.get()
        if distro in DISTRIBUTIONS:
            self.version_combo.configure(values=DISTRIBUTIONS[distro]['versions'])
            self.version.set(DISTRIBUTIONS[distro]['versions'][0])
        self.preset.set(preferred_preset(distro, self.version.get()))
        self._update_suggestion()

    def user_changed(self, event=None):
        if self._updating:
            return
        self._autofollow = False
        value = self.source_override.get().strip()
        if self.app.state.get('builder_source_override') != value:
            self.app.state['builder_source_override'] = value
        self._update_suggestion()

    def _spec(self):
        return build_spec(self.distribution.get(), self.version.get(), self.architecture.get(), self.preset.get(), self.source_override.get())

    def _update_suggestion(self):
        try:
            spec = self._spec()
            description = 'Image: ' + spec['image'] + '    |    Platform: ' + spec['platform']
            if self.source_override.get().strip():
                description += '    |    Custom image reference'
            if spec['command']:
                description += '    |    Build common compiler tools before saving'
            else:
                description += '    |    Download existing image (no additional packages)'
            runtime = matching_runtime(self.app.state.get('base_system') or {})
            if all(runtime) and (self.distribution.get(), self.version.get().strip(), self.architecture.get()) != runtime:
                description += '\nCAUTION: This selection differs from the runtime platform/release. Verify compiled binary compatibility.'
            self.suggestion.set(description)
        except ValueError as exc:
            self.suggestion.set(str(exc))

    def preview(self):
        try:
            spec = self._spec()
        except ValueError as exc:
            messagebox.showerror('Builder preset', str(exc), parent=self)
            return
        text = '\n'.join(f'{key}: {value}' for key, value in spec.items())
        messagebox.showinfo('Builder preset', text, parent=self)

    def select_builder_tar(self):
        if self._busy:
            return
        path = filedialog.askopenfilename(parent=self, title='Select existing builder Docker TAR',
                                           filetypes=[('Docker image archives', '*.tar'), ('All files', '*.*')])
        if not path:
            return
        if not messagebox.askyesno('Load builder TAR', 'Import this TAR into Docker Desktop as a separate builder?\n\n' + path,
                                   parent=self):
            return
        self._working(True)
        def worker():
            try:
                result = load_image_checkpoint(path, progress=self._progress)
                system = result.get('system') or detect_runtime_image_system(result['tag'])
                self.after(0, lambda: self._complete(result['tag'], result['archive'], system,
                                                       result.get('inventory') or {}, {'source': 'existing TAR'}))
            except Exception as exc:
                self.after(0, lambda msg=str(exc): self._failed(msg))
        threading.Thread(target=worker, daemon=True).start()

    def _run(self, args, cwd=None):
        self._progress('$ ' + subprocess.list2cmdline([str(x) for x in args]))
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        process = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', errors='replace', bufsize=1,
                                   creationflags=flags)
        lines = []
        for line in process.stdout:
            stripped = line.rstrip('\r\n')
            self._progress(stripped)
            lines.append(stripped)
            if len(lines) > 40:
                lines.pop(0)
        rc = process.wait()
        if rc:
            raise RuntimeError(f'Command failed (exit {rc}):\n' + '\n'.join(lines[-16:]))
        return '\n'.join(lines)

    def download_builder(self):
        if self._busy:
            return
        try:
            spec = self._spec()
        except ValueError as exc:
            messagebox.showerror('Builder preset', str(exc), parent=self)
            return
        state = self.app.state
        runtime = matching_runtime(state.get('base_system') or {})
        mismatch = all(runtime) and (spec['distribution'], spec['version'], spec['platform']) != runtime
        warning = '\nWARNING: Builder distribution/version/architecture differs from runtime.' if mismatch else ''
        command = 'Docker pull: ' + spec['image'] + '  (' + spec['platform'] + ')'
        if spec['command']:
            command += '\nThen Docker will build a new compiler-equipped image using online package installation.'
        if not messagebox.askyesno('Approve builder download',
                                   'This will access the internet and may download significant image data.\n\n' + command +
                                   warning + '\n\nProceed?', parent=self):
            return
        initial_dir = str(state.get('export_image_dir') or state.get('project_dir') or Path.cwd())
        selected_tag = timestamp_tag(spec['distribution'], spec['version'], spec['platform'])
        name = selected_tag.replace(':', '_') + '.tar'
        destination = filedialog.asksaveasfilename(parent=self, title='Save builder Docker image TAR',
                                                   initialdir=initial_dir if Path(initial_dir).is_dir() else str(Path.cwd()),
                                                   initialfile=name, defaultextension='.tar',
                                                   filetypes=[('Docker image TAR', '*.tar')])
        if not destination:
            return
        self._working(True)
        self._line('Approved builder: ' + json.dumps(spec, ensure_ascii=False))
        def worker():
            try:
                image = spec['image']
                platform = spec['platform']
                tag = selected_tag
                self._run(['docker', 'pull', '--platform', platform, image])
                if spec['command']:
                    with tempfile.TemporaryDirectory(prefix='component-builder-') as directory:
                        dockerfile = Path(directory) / 'Dockerfile'
                        dockerfile.write_text('FROM ' + image + '\nRUN set -eu; ' + spec['command'] + '\n', encoding='utf-8')
                        self._run(['docker', 'build', '--pull=false', '--network=default',
                                   '--platform', platform, '-t', tag, '-f', str(dockerfile), directory])
                else:
                    self._run(['docker', 'tag', image, tag])
                inspection = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Architecture}}', tag],
                                            capture_output=True, text=True, timeout=45)
                if inspection.returncode:
                    raise RuntimeError('Cannot verify architecture of the newly prepared builder image.')
                actual_arch = inspection.stdout.strip()
                expected_arch = platform.split('/')[1]
                if actual_arch != expected_arch:
                    raise RuntimeError(f'Builder architecture is {actual_arch}, expected {expected_arch}.')
                system = detect_runtime_image_system(tag)
                system.setdefault('id', DISTRIBUTIONS[spec['distribution']]['id'])
                system.setdefault('version_id', spec['version'])
                system.setdefault('architecture', actual_arch)
                ident = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', tag],
                                       capture_output=True, text=True, timeout=45, check=True).stdout.strip()
                inventory = {'image_id': ident, 'system': system}
                result = save_image_checkpoint(tag, destination, system=system, inventory=inventory,
                                               progress=self._progress)
                self.after(0, lambda: self._complete(tag, result['archive'], result.get('system', system), result.get('inventory', inventory), spec))
            except Exception as exc:
                self.after(0, lambda msg=str(exc): self._failed(msg))
        threading.Thread(target=worker, daemon=True).start()

    def _complete(self, tag, archive, system, inventory, spec):
        self._working(False)
        self.app.state.update({'builder_mode': 'separate', 'builder_image': tag,
                               'builder_base_archive': archive, 'builder_system': system,
                               'builder_inventory': inventory, 'builder_preset': spec})
        self._line('Builder ready. Docker tag: ' + tag + '\nSaved TAR: ' + archive)
        self.refresh_from_project_state()
        base_tab = getattr(self.app, 'base_tab', None)
        if base_tab is not None:
            self.after(0, base_tab.refresh_selected_archives)
        messagebox.showinfo('Builder ready', 'Separate builder image selected.\n\n' + tag + '\n\nTAR: ' + archive, parent=self)

    def _failed(self, message):
        self._working(False)
        self._line('ERROR: ' + message)
        messagebox.showerror('Builder operation failed', message, parent=self)
