import shlex
import subprocess
import threading
import queue
import os
import time
import uuid
from datetime import datetime, timezone
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from build_artifacts import prepare_workspace, read_record, register_output
from binary_version_probe import probe_binary_version
from compilation_status import compilation_status
from component_presets import BUILD_COMMANDS, COMMON_BUILD_COMMANDS, detect_build_system
from component_output_detector import detect_compiled_output, normalized_relative
from project_state import effective_builder_image
from source_documentation import discover_build_documentation, open_build_documentation, show_build_documentation
from network_policy import POLICY_OFFLINE, normalize_policy, package_names, inspect_packages, permission_message, validate_packages


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
        self.timeout_minutes = tk.StringVar(value='30')
        self.source_network = tk.BooleanVar(value=bool(app.state.get('allow_source_network', False)))
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
        labels = [('Source component:', self.comp), ('Source folder (Tab 3):', self.source),
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
        tk.Button(bar, text='Detect build system & output', command=self.detect, bg='#F0B27A').pack(side='left', padx=3)
        self.compile_button = tk.Button(bar, text='Compile Source and Save Output', command=self.compile_selected, bg='#D35400', fg='white')
        self.compile_button.pack(side='left', padx=3)
        self.compile_all_button = tk.Button(bar, text='Compile All Required Sources', command=self.compile_all, bg='#A04000', fg='white')
        self.compile_all_button.pack(side='left', padx=3)
        self.stop_button = tk.Button(bar, text='Stop Compilation', command=self.stop_compilation, bg='#922B21', fg='white', state='disabled')
        self.stop_button.pack(side='left', padx=3)
        tk.Button(bar, text='View components in Tab 3', command=lambda: self.app.notebook.select(self.app.components_tab), bg='#F5CBA7').pack(side='left', padx=3)
        tk.Button(bar, text='Refresh', command=self.refresh_from_project_state, bg='#F5CBA7').pack(side='left', padx=3)
        timeout_bar = tk.Frame(self, bg='#FEF5E7')
        timeout_bar.pack(fill='x', padx=15)
        tk.Label(timeout_bar, text='Maximum compilation time per component (minutes):', bg='#FEF5E7').pack(side='left')
        tk.Entry(timeout_bar, textvariable=self.timeout_minutes, width=6).pack(side='left', padx=8)
        tk.Checkbutton(timeout_bar, text='Permit internet for custom source build commands (ask first)', variable=self.source_network, command=self._set_source_network, bg='#FEF5E7').pack(side='left', padx=15)
        tk.Label(self, textvariable=self.status, bg='#FEF5E7', fg='#784212', anchor='w', font=('Segoe UI', 10, 'bold')).pack(fill='x', padx=16, pady=4)
        tk.Label(self, text='Compiles inside the builder selected in Tab 1. Successful executables are saved for runtime library checks in Tab 5 and installation during final image creation in Tab 6. The builder is not included in the final image.',
                 bg='#FEF5E7', fg='#784212', anchor='w', justify='left', wraplength=1250).pack(fill='x', padx=15, pady=4)
        self.out = tk.Text(self, font=('Consolas', 9), height=25, wrap='none')
        self.out.pack(fill='both', expand=True, padx=12, pady=(4, 12))
        self.refresh_from_project_state()

    def _set_source_network(self):
        self.app.state['allow_source_network'] = bool(self.source_network.get())

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
        self.builder.set('Builder (Tab 1): ' + (builder or 'NOT SELECTED') + (' (same as runtime)' if not state.get('builder_base_archive') else '') + '    |    Runtime (Tab 1): ' + (state.get('base_image', '') or 'NOT SELECTED'))
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
        if not source.is_dir():
            messagebox.showerror('Source', 'The source folder selected in Tab 3 does not exist.', parent=self)
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
        self._save()

    def _automatic_settings(self, component):
        source = Path(str(component.get('source', '') or '').strip())
        if not source.is_dir():
            raise ValueError('Source folder does not exist: ' + str(source))
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
                    self.out.insert('end', message)
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
        finally:
            with self._process_lock:
                if self._current_process is process:
                    self._current_process = None
            if process.stdout is not None:
                process.stdout.close()

    def _perform_compilation(self, component, builder, append, timeout_seconds, missing_packages=(), network_enabled=False):
        if self._cancel_event.is_set():
            raise RuntimeError('Cancelled by user.')
        self._automatic_settings(component)
        work = prepare_workspace(self.app.state, component)
        relative = normalized_relative(component.get('output_rel', ''))
        if not relative:
            raise RuntimeError('Compiled output path is missing.')
        command = str(component['build_command']).strip()
        packages = validate_packages(str(component.get('build_deps', '') or '').split(','))
        missing = sorted(set(packages).intersection(missing_packages))
        if missing:
            words = ' '.join(shlex.quote(package) for package in missing)
            setup = ('if command -v apt-get >/dev/null 2>&1; then apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y ' + words + '; '
                     'elif command -v apk >/dev/null 2>&1; then apk add --no-cache ' + words + '; '
                     'elif command -v dnf >/dev/null 2>&1; then dnf install -y ' + words + '; '
                     'elif command -v microdnf >/dev/null 2>&1; then microdnf install -y ' + words + '; '
                     'else echo Unsupported package manager; exit 31; fi')
            command = setup + ' && ' + command
        token = uuid.uuid4().hex[:16]
        image_tag = 'local/component-build-' + token
        container_name = 'docker-component-extract-' + token
        dockerfile = work / '.component-build.Dockerfile'
        dockerfile.write_text('FROM ' + builder + '\nWORKDIR /src\nCOPY . /src\nRUN ' + command + '\n', encoding='utf-8')
        deadline = time.monotonic() + timeout_seconds
        with self._process_lock:
            self._current_container = container_name
        append('Compiler module loaded: ' + str(Path(__file__).resolve()) + '\n')
        append('Compilation pipeline: docker build -> docker create -> docker cp -> cleanup. No bind mounts.\n')
        try:
            self._run_docker_step(
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
                append, deadline, 'Copying compiled executable back to Windows', 120)
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
                active_targets = [component for component in targets if not (skip_current and compilation_status(self.app.state, component)['status'] == 'COMPILED')]
                all_packages = package_names(active_targets, 'builder')
                inspection = inspect_packages(builder, all_packages)
                self._log('Builder packages already installed: ' + (', '.join(inspection['installed']) or 'none') + '\n')
                self._log('Builder packages missing: ' + (', '.join(inspection['missing']) or 'none') + '\n')
                policy = normalize_policy(self.app.state.get('package_download_policy'))
                extra_network = bool(self.app.state.get('allow_source_network', False)) and bool(active_targets)
                if policy == POLICY_OFFLINE and (inspection['missing'] or extra_network):
                    raise RuntimeError('Offline-only network policy blocks missing builder packages or custom source network access.')
                network_enabled = False
                if inspection['missing'] or extra_network:
                    response = {}
                    signal = threading.Event()
                    self._messages.put(('approval', builder, inspection, extra_network, response, signal))
                    if not signal.wait(timeout=600):
                        raise RuntimeError('Network approval timed out.')
                    if not response.get('approved'):
                        raise RuntimeError('Network access was not approved. No online compilation started.')
                    network_enabled = True
                for component in targets:
                    if self._cancel_event.is_set():
                        break
                    name = str(component.get('name', '') or '').strip()
                    if skip_current and compilation_status(self.app.state, component)['status'] == 'COMPILED':
                        counts['skipped'] += 1
                        self._log('SKIPPED (already compiled): ' + name + '\n')
                        continue
                    try:
                        record = self._perform_compilation(component, builder, self._log, timeout_seconds, inspection['missing'], network_enabled)
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
