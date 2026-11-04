import json
import posixpath
import re
import shlex
import shutil
import subprocess
import threading
import queue
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from build_artifacts import read_record, sha256_file
from component_file_types import validate_component_type
from network_policy import POLICY_OFFLINE, normalize_policy, package_names, inspect_packages, permission_message, require_local_image
from java_runtime_checker import probe_java
from dependency_planner import plan_runtime_dependencies, evaluate_java_requirement
from general_environment import package_plan, custom_directives
from environment_install import language_lines, custom_script_lines
from build_modes import STRICT, PERMISSIVE, ASSEMBLY, normalize_mode, optional_lines, environment_lines, derive_next_tag
from component_provenance import make_build_provenance, parent_provenance
from manual_installation_overrides import user_confirmed_package
from image_removals import normalize_removals, remove_deferred_packages, dockerfile_removal_lines
from image_component_inventory import inspect_image_components
from revision_dependencies import dependency_impact, normalize_satisfactions, projected_java_versions
from image_compaction import show_compaction_dialog
from local_package_catalog import local_installation_plan, installed_packages


class BuildTab(tk.Frame):
    FILE_KINDS = {'binary', 'script', 'jar/application', 'folder', 'other'}

    def __init__(self, parent, app):
        super().__init__(parent, bg='#E9F7EF')
        self.app = app
        self.image = tk.StringVar()
        self.context = tk.StringVar()
        self.summary = tk.StringVar()
        self.status = tk.StringVar(value='NOT BUILT')
        self._busy = False
        self._messages = queue.Queue()
        self._package_inspection = None
        self._last_plan = None
        self._last_environment = None
        self._generation_issues = []
        tk.Label(self, text='6 — ASSEMBLE FINAL DOCKER IMAGE', bg='#1E8449', fg='white',
                 font=('Segoe UI', 16, 'bold'), anchor='w', padx=14, pady=10).pack(fill='x')
        tk.Label(self, text='Uses the runtime from Tab 1, existing binaries configured in Tab 3, compiled outputs from Tab 4, and library requirements from Tab 5. Does not recompile sources.',
                 bg='#D5F5E3', fg='#145A32', anchor='w', wraplength=1250, padx=10, pady=9).pack(fill='x', padx=12, pady=(8, 4))
        tk.Label(self, textvariable=self.summary, bg='#E9F7EF', anchor='w', justify='left').pack(fill='x', padx=12, pady=8)
        form = tk.Frame(self, bg='#E9F7EF')
        form.pack(fill='x', padx=12, pady=8)
        form.columnconfigure(1, weight=1)
        tk.Label(form, text='Final image name:', bg='#E9F7EF').grid(row=0, column=0, sticky='w', pady=4)
        tk.Entry(form, textvariable=self.image).grid(row=0, column=1, sticky='ew', padx=8)
        tk.Label(form, text='Build context folder:', bg='#E9F7EF').grid(row=1, column=0, sticky='w', pady=4)
        tk.Entry(form, textvariable=self.context).grid(row=1, column=1, sticky='ew', padx=8)
        tk.Button(form, text='Browse', command=self.browse).grid(row=1, column=2)
        controls = tk.Frame(self, bg='#E9F7EF')
        controls.pack(fill='x', padx=12, pady=8)
        tk.Button(controls, text='Generate Dockerfile', command=self.generate, bg='#82E0AA').pack(side='left', padx=3)
        tk.Button(controls, text='Show Dockerfile', command=self.show, bg='#58D68D').pack(side='left', padx=3)
        self.build_button = tk.Button(controls, text='Build Final Image', command=self.build, bg='#239B56', fg='white')
        self.build_button.pack(side='left', padx=3)
        tk.Button(controls, text='Check required OS packages', command=self.check_required_packages, bg='#A9DFBF').pack(side='left', padx=3)
        tk.Button(controls, text='Refresh', command=self.refresh_from_project_state, bg='#A9DFBF').pack(side='left', padx=3)
        tk.Button(controls, text='Revise Built Image', command=self.revise_built_image, bg='#AED6F1').pack(side='left', padx=3)
        tk.Button(controls, text='Compact Built Image', command=self.compact_built_image, bg='#F9E79F').pack(side='left', padx=3)
        self.policy_status = tk.StringVar()
        tk.Label(self, textvariable=self.policy_status, bg='#E9F7EF', anchor='w').pack(fill='x', padx=16)
        tk.Label(self, textvariable=self.status, bg='#E9F7EF', fg='#145A32', font=('Segoe UI', 10, 'bold'), anchor='w').pack(fill='x', padx=16, pady=5)
        output_frame = tk.Frame(self, bg='#E9F7EF')
        output_frame.pack(fill='both', expand=True, padx=12, pady=(2, 12))
        self.out = tk.Text(output_frame, bg='white', font=('Consolas', 9), wrap='none')
        sy = tk.Scrollbar(output_frame, orient='vertical', command=self.out.yview)
        sx = tk.Scrollbar(output_frame, orient='horizontal', command=self.out.xview)
        self.out.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.out.grid(row=0, column=0, sticky='nsew')
        sy.grid(row=0, column=1, sticky='ns')
        sx.grid(row=1, column=0, sticky='ew')
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)
        self.refresh_from_project_state()

    def _will_install_now(self, mode=None):
        return normalize_mode(mode or self.app.state.get('build_mode')) != ASSEMBLY

    def browse(self):
        path = filedialog.askdirectory(parent=self)
        if path:
            self.context.set(path)

    def _components(self):
        return [c for c in self.app.state.get('components', []) if c.get('enabled', True)]

    def refresh_from_project_state(self):
        state = self.app.state
        tag = str(state.get('image_name', '') or '').strip()
        if tag:
            self.image.set(tag)
        elif not self.image.get().strip():
            self.image.set('component-toolbox:latest')
        folder = str(state.get('generated_context', '') or '').strip()
        if folder:
            self.context.set(folder)
        elif not self.context.get().strip():
            project = str(state.get('project_dir', '') or '').strip()
            if project:
                self.context.set(str(Path(project) / '_generated_docker_context'))
        self.policy_status.set('Build mode: ' + normalize_mode(state.get('build_mode')).upper() + '    |    OS packages: LOCAL FILES ONLY' + '    |    Network: ' + ('OFFLINE' if normalize_policy(state.get('package_download_policy')) == POLICY_OFFLINE else 'APPROVAL FOR OPTIONAL LANGUAGE/CUSTOM DOWNLOADS'))
        components = self._components()
        source = [c for c in components if str(c.get('kind', '')).lower() == 'source']
        ready = sum(bool(read_record(state, c)[0]) for c in source)
        binaries = [c for c in components if str(c.get('kind', '')).lower() in self.FILE_KINDS]
        packages = [c for c in components if str(c.get('kind', '')).lower() == 'os package']
        removals = normalize_removals(state.get('image_removals'))
        env_data = self.app.state.get('environment_requirements') or {}
        languages = ', '.join(lang for lang, key in [('Java', 'java_version'), ('Python', 'python_version'), ('R', 'r_version'), ('Perl', 'perl_version')] if env_data.get(key))
        self.summary.set(f'Runtime: {state.get("base_image", "") or "NOT SELECTED"}    |    '
                         f'Compiled sources: {ready}/{len(source)} ready    |    '
                         f'Existing binaries/files: {len(binaries)}    |    OS packages: {len(packages)}    |    Removals: {len(removals)}    |    Runtimes: {languages or "auto / none"}')

    def _check_context(self, context, components):
        marker = context / '.docker_component_builder_managed.json'
        if context == context.parent or context == Path.home().resolve():
            raise ValueError('Choose a dedicated context folder, not a drive root or home directory.')
        project_text = str(self.app.state.get('project_dir', '') or '').strip()
        if project_text and context == Path(project_text).resolve():
            raise ValueError('The context may not be the project root.')
        for c in components:
            source = str(c.get('source', '') or '').strip()
            if not source:
                continue
            path = Path(source).expanduser().resolve()
            if path == context or context in path.parents:
                raise ValueError('Component source is inside the generated context: ' + source)
        if context.exists() and not context.is_dir():
            raise ValueError('Build context path is not a directory.')
        if context.exists() and any(context.iterdir()):
            if not marker.is_file():
                raise ValueError('Nonempty context folder was not created by this application; choose an empty folder.')
            metadata = json.loads(marker.read_text(encoding='utf-8'))
            if metadata.get('managed_by') != 'component-docker-image-builder':
                raise ValueError('Unrecognized build-context folder; refusing to overwrite it.')
        context.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({'managed_by': 'component-docker-image-builder'}), encoding='utf-8')
        for name in ('compiled', 'binaries', 'Dockerfile', 'build_manifest.json', 'pending_requirements.json', 'installation_status.tsv', 'local_packages', 'custom_before.sh', 'custom_after.sh', 'custom_verify.sh', 'component_provenance.json', 'local_packages'):
            target = context / name
            if target.is_symlink():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        (context / 'compiled').mkdir()
        (context / 'binaries').mkdir()

    def _check_binary_architecture(self, path, component):
        if not path.is_file():
            return
        try:
            with path.open('rb') as source:
                header = source.read(20)
        except OSError as exc:
            raise ValueError(f"Cannot inspect {path}: {exc}")
        name = str(component.get('name', '') or '')
        if header.startswith(b'MZ') and str(component.get('kind', '')).strip().lower() in ('binary', 'source'):
            raise ValueError(f'{name}: Windows PE executables cannot run natively in a Linux image.')
        if not header.startswith(b'\x7fELF') or len(header) < 20:
            return
        endian = 'little' if header[5] == 1 else 'big'
        machine = int.from_bytes(header[18:20], endian)
        runtime = self.app.state.get('base_system', {}) or {}
        architecture = str(runtime.get('architecture', '') or runtime.get('arch', '') or '').lower().strip()
        expectations = {'amd64': 62, 'x86_64': 62, 'x64': 62, 'aarch64': 183, 'arm64': 183, 'armv7': 40, 'arm': 40, 'i386': 3, '386': 3}
        expected = expectations.get(architecture)
        if expected is not None and machine != expected:
            raise ValueError(f'{name}: ELF CPU architecture {machine} does not match runtime {architecture}.')

    def _destination(self, component):
        value = str(component.get('destination', '') or '').strip()
        if not value.startswith('/') or any(part in ('.', '..') for part in value.split('/')):
            raise ValueError(f'Invalid image destination for {component.get("name", "")}: {value or "<blank>"}')
        return posixpath.normpath(value).rstrip('/') + '/'

    def _package_lines(self, local_archives, family):
        if not local_archives:
            return []
        files = ' '.join(shlex.quote(path) for path in local_archives)
        scripts = {
            'rpm': 'if command -v rpm >/dev/null 2>&1; then rpm -Uvh --replacepkgs ' + files + '; else echo "RPM installation unavailable" >&2; exit 22; fi',
            'apt': 'if command -v dpkg >/dev/null 2>&1; then dpkg -i ' + files + '; else echo "DPKG installation unavailable" >&2; exit 22; fi',
            'apk': 'if command -v apk >/dev/null 2>&1; then apk add --no-network ' + files + '; else echo "APK installation unavailable" >&2; exit 22; fi',
        }
        if family not in scripts:
            raise ValueError('Cannot install local packages: unknown Linux package format. Inspect the base in Tab 2.')
        return ['RUN set -eu; ' + scripts[family], '']

    def _plan(self, base_java=None):
        plan = plan_runtime_dependencies(self.app.state, base_java=base_java)
        env = package_plan(self.app.state, plan['manager'], plan)
        from network_policy import validate_packages
        plan['packages'] = validate_packages([*plan['packages'], *env['packages']])
        manual = [name for name in plan['packages'] if user_confirmed_package(self.app.state, name)]
        if manual:
            plan['manually_confirmed'] = manual
            plan['packages'] = [name for name in plan['packages'] if name not in manual]
            plan.setdefault('notes', []).append('USER CONFIRMED, NOT VERIFIED: skipped OS package reinstallation for ' + ', '.join(manual))
        self._last_environment = env
        self._last_plan = plan
        if plan['target_java'] and plan['manager'] == 'unknown' and normalize_mode(self.app.state.get('build_mode')) == STRICT:
            raise RuntimeError('Cannot identify the runtime Linux distribution. Inspect the base in Tab 2 or select its Docker archive before installing Java.')
        return plan

    def _java_activation_lines(self, plan):
        target = plan.get('target_java')
        if target is None:
            return []
        script = r'''RUN set -eu; wanted=JAVA_MAJOR; chosen=''; chosen_major=999; fallback=''; fallback_major=0; \
  for executable in /usr/lib/jvm/*/bin/java /usr/lib/jvm/*/*/bin/java /opt/java/openjdk/bin/java /usr/bin/java; do \
    [ -x "$executable" ] || continue; \
    release=$("$executable" -version 2>&1 | head -n 1 | sed -n 's/.*version "\([0-9][^"]*\)".*/\1/p') || true; \
    [ -n "$release" ] || continue; \
    major=${release%%.*}; \
    if [ "$major" = 1 ]; then release=${release#1.}; major=${release%%.*}; fi; \
    case "$major" in ''|*[!0-9]*) continue ;; esac; \
    if [ "$major" -ge "$wanted" ] && [ "$major" -lt "$chosen_major" ]; then chosen="$executable"; chosen_major=$major; fi; \
    if [ "$major" -gt "$fallback_major" ]; then fallback="$executable"; fallback_major=$major; fi; \
  done; \
  if [ -z "$chosen" ]; then \
    if [ -n "$fallback" ]; then chosen="$fallback"; fi; \
    printf "%s\n" "Compatible Java $wanted+ could not be selected; best available is Java $fallback_major" >&2; \
    mkdir -p /opt/component-builder; \
    printf "%s\n" "Compatible Java $wanted+ missing; best available Java $fallback_major" >> /opt/component-builder/setup-issues.txt; \
  fi; \
  if [ -n "$chosen" ]; then \
    mkdir -p /opt/component-builder; \
    ln -sfn "$(dirname "$(dirname "$chosen")")" /opt/component-builder/java; \
    /opt/component-builder/java/bin/java -version; \
  fi; \
  [ "$chosen_major" != 999 ]'''
        return [script.replace('JAVA_MAJOR', str(target)), 'ENV JAVA_HOME=/opt/component-builder/java', 'ENV PATH="/opt/component-builder/java/bin:${PATH}"', '']

    def _installation_status_lines(self, packages):
        output = ['RUN mkdir -p /opt/component-builder && : > /opt/component-builder/installation_status.tsv']
        if not packages:
            return output
        quoted = ' '.join(shlex.quote(value) for value in packages)
        script = (
            'for package in ' + quoted + '; do '
            'present=0; '
            'if command -v dpkg-query >/dev/null 2>&1; then '
            '[ "$(dpkg-query -W -f=\'${Status}\' "$package" 2>/dev/null || true)" = "install ok installed" ] && present=1; '
            'elif command -v apk >/dev/null 2>&1; then apk info -e "$package" >/dev/null 2>&1 && present=1; '
            'elif command -v rpm >/dev/null 2>&1; then rpm -q "$package" >/dev/null 2>&1 && present=1; fi; '
            'if [ "$present" = 1 ]; then outcome=INSTALLED; else outcome="NOT INSTALLED"; fi; '
            r'printf "%s\t%s\n" "$package" "$outcome" >> /opt/component-builder/installation_status.tsv; '
            'done; true'
        )
        output.append('RUN ' + script)
        return output

    def check_required_packages(self):
        image = str(self.app.state.get('base_image', '') or '').strip()
        if not image:
            messagebox.showerror('Dependencies', 'Select and load the runtime in Tabs 1–2.', parent=self)
            return
        try:
            plan = self._plan()
            removals = normalize_removals(self.app.state.get('image_removals'))
            packages = remove_deferred_packages(plan['packages'], removals)
            inspection = inspect_packages(image, packages)
            self._package_inspection = inspection
        except Exception as exc:
            messagebox.showerror('Dependencies', str(exc), parent=self)
            return
        lines = ['Package inventory for ' + image, 'Package manager: ' + (inspection['manager'] if packages else 'not checked (no OS packages requested)'), '',
                 'Already installed (' + str(len(inspection['installed'])) + '):']
        lines.extend('  ' + item for item in inspection['installed'])
        lines.extend(['', 'Missing (' + str(len(inspection['missing'])) + '):'])
        lines.extend('  ' + item for item in inspection['missing'])
        lines.append('')
        local = local_installation_plan(self.app.state, packages, plan['manager'])
        lines += ['', 'LOCAL PACKAGE FILES AVAILABLE FOR OFFLINE INSTALLATION:']
        for name, archives in local['local'].items():
            lines.extend('  ' + name + ': ' + str(archive) for archive in archives)
        if not local['local']:
            lines.append('  None selected')
        lines += ['', 'NOT INSTALLED AND NO LOCAL PACKAGE FILE:']
        lines.extend('  ' + item for item in local['not_installed'])
        lines.extend('  ' + item for item in local['errors'])
        lines.append('No internet access is needed to install supplied local archives. Missing dependencies must also be provided locally.')
        lines += ['', 'Detected application requirements (not auto-installed):']
        lines.extend('  ' + item['name'] + ': Java ' + str(item['minimum']) + '+' for item in plan['java'] if item['minimum'])
        env = self._last_environment or package_plan(self.app.state, plan['manager'], plan)
        lines.extend('  ' + lang + ': ' + (', '.join(pkgs) or 'none') for lang, pkgs in env['language_packages'].items())
        for language, key in (('Java', 'java_version'), ('Python', 'python_version'), ('R', 'r_version'), ('Perl', 'perl_version')):
            if env['config'][key]:
                lines.append('  Minimum ' + language + ': ' + env['config'][key])
        if env['config']['pre_commands'] or env['config']['post_commands']:
            lines.append('  Custom Linux setup commands will run during Tab 6 build.')
        lines.extend('  Translate: ' + original + ' => ' + resolved for original, resolved in plan['translations'])
        if plan['target_java']:
            lines.append('  Java selection: ' + plan['selection_reason'])
        lines.append('Detected application requirements are not installed automatically. You must select packages in Tab 3.')
        if not packages:
            lines.append('No OS packages are declared. This does not verify application dependencies or Java compatibility.')
        self.out.delete('1.0', 'end')
        self.out.insert('end', '\n'.join(lines))
        self.status.set('PACKAGE CHECK: ' + str(len(inspection['installed'])) + ' installed, ' + str(len(inspection['missing'])) + ' missing')

    def _consume_messages(self):
        try:
            while True:
                event = self._messages.get_nowait()
                if event[0] == 'log':
                    self.out.insert('end', event[1])
                    self.out.see('end')
                elif event[0] == 'approve':
                    _, image, report, response, signal = event
                    response['approved'] = messagebox.askyesno('Approve runtime package downloads', permission_message('runtime', image, report, continue_on_decline=normalize_mode(self.app.state.get('build_mode')) != STRICT), parent=self)
                    signal.set()
                elif event[0] == 'image_ready':
                    _, image = event
                    self.app.state['built_image'] = image
                    self.app.state['image_name'] = image
                    self.status.set('IMAGE CREATED — finishing dependency reports: ' + image)
                    validator = getattr(self.app, 'validation_tab', None)
                    if validator is not None:
                        validator.refresh_from_project_state()
                elif event[0] == 'finish':
                    _, code, image, detail, report = event
                    self._busy = False
                    self.build_button.config(state='normal')
                    self.status.set(('BUILT — ' + report.get('quality', 'UNVERIFIED') + ': ' + image) if code == 0 else 'BUILD FAILED: ' + detail)
                    if code == 0:
                        self.app.state['built_image'] = image
                        self.app.state['image_name'] = image
                        self.app.state['last_build_report'] = report
                        self.app.state['image_removals'] = []
                        history = list(self.app.state.get('build_history', []))
                        history.append(report)
                        self.app.state['build_history'] = history[-50:]
                        self.app.state['validation'] = dict(self.app.state.get('validation', {}), last_results={}, verified_image_id='')
                        validator = getattr(self.app, 'validation_tab', None)
                        if validator is not None:
                            validator.refresh_from_project_state()
        except queue.Empty:
            pass
        if self._busy or not self._messages.empty():
            self.after(100, self._consume_messages)

    def generate(self):
        state = self.app.state
        base = str(state.get('base_image', '') or '').strip()
        image = self.image.get().strip()
        if not base:
            messagebox.showerror('Build', 'Select and load the final runtime image in Tab 1 and Tab 2.', parent=self)
            return False
        if image == base:
            messagebox.showerror('Build', 'The output image tag must differ from the runtime base tag to preserve the original image.', parent=self)
            return False
        if not image or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.:/-]*', image):
            messagebox.showerror('Build', 'Enter a valid Docker image name and tag.', parent=self)
            return False
        if not self.context.get().strip():
            messagebox.showerror('Build', 'Select the build context directory.', parent=self)
            return False
        components = self._components()
        removals = normalize_removals(state.get('image_removals', []))
        environment = self.app.state.get('environment_requirements') or {}
        environment_configured = any(str(value or '').strip() for key, value in environment.items() if key not in ('auto_detect', 'allow_custom_network'))
        if not components and not environment_configured and not removals and normalize_mode(state.get('build_mode')) == STRICT:
            messagebox.showerror('Build', 'No enabled components or configured runtime environment. Add components or an environment in Tab 3.', parent=self)
            return False
        mode = normalize_mode(state.get('build_mode'))
        manifest = []
        issues = []
        try:
            for component in components:
                kind = str(component.get('kind', '') or '').strip().lower()
                name = str(component.get('name', '') or '').strip()
                if kind == 'source':
                    record, detail = read_record(state, component)
                    if not record:
                        if mode == STRICT:
                            messagebox.showerror('Compilation required', f'{name}: {detail}', parent=self)
                            return False
                        issues.append(name + ': compiled source unavailable: ' + detail)
                        continue
                    self._check_binary_architecture(Path(record['artifact']), component)
                    manifest.append((component, Path(record['artifact']), record))
                elif kind in self.FILE_KINDS:
                    path = Path(str(component.get('source', '') or '').strip()).expanduser()
                    if not path.exists():
                        if mode == STRICT:
                            messagebox.showerror('Missing file', f'{name}: {path}', parent=self)
                            return False
                        issues.append(name + ': input file unavailable: ' + str(path))
                        continue
                    if kind in ('binary', 'jar/application'):
                        valid, problem = validate_component_type(kind, path)
                        if not valid:
                            if mode == STRICT:
                                raise ValueError(name + ': ' + problem)
                            issues.append(name + ': invalid component format: ' + problem)
                            continue
                    self._check_binary_architecture(path, component)
                    manifest.append((component, path, None))
        except ValueError as exc:
            messagebox.showerror('Binary compatibility', str(exc), parent=self)
            return False
        context = Path(self.context.get().strip()).expanduser().resolve()
        try:
            self._check_context(context, components)
            lines = [f'FROM {base} AS final', 'USER root', '']
            if mode != STRICT:
                lines.extend(['ARG COMPONENT_BUILDER_ALLOW_DOWNLOADS=0', 'RUN mkdir -p /opt/component-builder && rm -f /opt/component-builder/setup-issues.txt', ''])
            lines.extend(dockerfile_removal_lines([row for row in removals if row['kind'] in ('file', 'directory')], mode == STRICT))
            plan = self._plan()
            removed_package_names = {item['name'].lower() for item in removals if item['kind'] == 'os_package'}
            reinstall = [name for name in plan['packages'] if name.lower() in removed_package_names]
            if reinstall:
                issues.append('User-requested removal takes priority over conflicting package installation requests: ' + ', '.join(reinstall) + '. Dependencies must be rechecked after building.')
                plan['packages'] = [name for name in plan['packages'] if name.lower() not in removed_package_names]
            removals_by_language = {'python_packages': 'python_package', 'cran_packages': 'r_package',
                                    'bioc_packages': 'r_package', 'cpan_modules': 'perl_package'}
            env = self._last_environment or package_plan(state, plan['manager'], plan)
            env = dict(env, language_packages={k: list(v) for k, v in env['language_packages'].items()})
            for field, kind in removals_by_language.items():
                removed_names = {item['name'].lower() for item in removals if item['kind'] == kind}
                conflicts = [x for x in env['language_packages'].get(field, []) if x.lower() in removed_names]
                if conflicts:
                    issues.append('Explicit removal overrides reinstall request for ' + ', '.join(conflicts))
                    env['language_packages'][field] = [x for x in env['language_packages'][field] if x.lower() not in removed_names]
            self._last_environment = env
            self._last_plan = plan
            if mode != STRICT:
                issues.extend(plan.get('notes') or [])
            packages = plan['packages']
            install_now = self._will_install_now(mode)
            local_plan = local_installation_plan(state, packages, plan['manager'])
            if local_plan['errors']:
                if mode == STRICT:
                    raise ValueError('Required OS packages cannot be installed locally:\n' + '\n'.join(local_plan['errors']))
                issues.extend(local_plan['errors'])
            staged_archives = []
            for package, archives in local_plan['local'].items():
                for archive in archives:
                    target = context / 'local_packages' / ('pkg_' + str(len(staged_archives)).zfill(4) + '_' + archive.name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(archive, target)
                    staged_archives.append({'package': package, 'source': str(archive), 'context': str(target.relative_to(context)).replace('\\', '/'),
                                            'target': '/opt/component-builder/local-packages/' + target.name, 'sha256': sha256_file(target)})
            if install_now and staged_archives:
                lines.append('RUN mkdir -p /opt/component-builder/local-packages')
                for archive in staged_archives:
                    lines.append('COPY ' + json.dumps([archive['context'], archive['target']]))
                lines.extend(optional_lines(self._package_lines([x['target'] for x in staged_archives], plan['manager']), 'Offline local OS package installation', False, mode))
            lines.extend(dockerfile_removal_lines([row for row in removals if row['kind'] in ('os_package', 'python_package', 'r_package', 'perl_package')], mode == STRICT))
            if install_now and plan.get('target_java'):
                lines.extend(optional_lines(self._java_activation_lines(plan), 'Java runtime selection', False, mode))
            if mode != ASSEMBLY:
                lines.extend(optional_lines(custom_script_lines(env['config']['pre_commands'], context, 'before'), 'Custom pre-installation', bool(env['config']['allow_custom_network']), mode))
            if install_now:
                lines.extend(environment_lines(language_lines(env), mode))
            lines.extend(self._installation_status_lines(packages))
            paths = []
            metadata = []
            removed_paths = {item['path'] for item in removals if item['kind'] == 'file'}
            for index, (component, path, record) in enumerate(manifest):
                destination = self._destination(component)
                if posixpath.join(destination, path.name) in removed_paths:
                    issues.append(str(component.get('name', '')) + ': installation skipped because removal was requested for this same path')
                    continue
                source_kind = 'compiled' if record else 'binaries'
                target_name = f'item_{index:03d}'
                folder = context / source_kind / target_name
                folder.mkdir(parents=True)
                if path.is_dir():
                    staged = folder / path.name
                    shutil.copytree(path, staged)
                    relative = f'{source_kind}/{target_name}/{path.name}/'
                    installed_name = path.name
                    integrity = ''
                else:
                    staged = folder / path.name
                    shutil.copy2(path, staged)
                    relative = f'{source_kind}/{target_name}/{path.name}'
                    installed_name = path.name
                    integrity = sha256_file(staged)
                lines.extend([f'RUN mkdir -p {shlex.quote(destination)}', 'COPY ' + json.dumps([relative, destination])])
                if str(component.get('kind', '')).lower() in ('source', 'binary') and path.is_file():
                    lines.append('RUN chmod +x ' + shlex.quote(posixpath.join(destination, installed_name)))
                lines.append('')
                if component.get('add_to_path'):
                    paths.append(destination.rstrip('/'))
                metadata.append({'name': component.get('name', ''), 'kind': component.get('kind', ''),
                                 'version': component.get('version', ''), 'source_kind': source_kind,
                                 'installed': posixpath.join(destination, installed_name), 'sha256': integrity,
                                 'compiled_signature': record.get('signature') if record else None})
            if mode != ASSEMBLY:
                lines.extend(optional_lines(custom_script_lines(env['config']['post_commands'], context, 'after'), 'Custom post-installation', bool(env['config']['allow_custom_network']), mode))
                lines.extend(optional_lines(custom_script_lines(env['config']['verify_commands'], context, 'verify'), 'Custom verification', False, mode))
            if paths:
                lines.extend(['ENV PATH=' + json.dumps(':'.join(dict.fromkeys(paths)) + ':${PATH}'), ''])
            pending = {'status': 'INSTALLATION_ATTEMPTED' if install_now else 'NOT_INSTALLED',
                       'os_packages': list(packages), 'java_requirements': plan.get('java', []),
                       'java_target': plan.get('target_java'), 'local_os_package_archives': staged_archives, 'language_packages': env['language_packages'],
                       'language_versions': {key: env['config'].get(key, '') for key in ('java_version', 'python_version', 'r_version', 'perl_version')}}
            try:
                archive = str(state.get('runtime_base_archive') or '')
                snapshot = inspect_image_components(archive) if archive else {}
                projected_dependencies = dependency_impact(state, snapshot)
            except Exception as exc:
                projected_dependencies = []
                issues.append('Dependency revision preview unavailable: ' + str(exc))
            unsatisfied = [x for x in projected_dependencies if x['status'] in ('MISSING', 'UNVERIFIED', 'UNRESOLVED', 'RECHECK', 'INCOMPATIBLE')]
            if unsatisfied:
                issues.append(str(len(unsatisfied)) + ' dependencies require post-build verification or a substitute provider; see Tab 5.')
            previous = parent_provenance(state)
            pending['os_packages'] = remove_deferred_packages(pending['os_packages'], removals)
            pending['removed_requests'] = [x['name'] for x in removals if x['kind'] == 'deferred']
            provenance = make_build_provenance(state, image, metadata, issues, pending, mode, install_now, previous, removals=removals)
            (context / 'component_provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
            lines.extend(['RUN mkdir -p /opt/component-builder',
                          'COPY ["component_provenance.json", "/opt/component-builder/component_provenance.json"]', ''])
            (context / 'pending_requirements.json').write_text(json.dumps(pending, indent=2), encoding='utf-8')
            lines.extend(['RUN mkdir -p /opt/component-builder',
                          'COPY ["pending_requirements.json", "/opt/component-builder/pending_requirements.json"]', ''])
            lines.extend(['WORKDIR /workspace', 'CMD ["/bin/sh"]', ''])
            lines.extend(custom_directives(env['config']['dockerfile_directives']))
            dockerfile = '\n'.join(lines)
            (context / 'Dockerfile').write_text(dockerfile, encoding='utf-8')
            (context / 'build_manifest.json').write_text(json.dumps({'image_name': image, 'runtime': base,
                'builder_used_during_tab4': state.get('builder_image', '') or base,
                'components': metadata, 'runtime_packages': sorted(set(packages)),
                'dependency_plan': plan, 'language_environment': env, 'mode': mode,
                'installation_attempted': install_now, 'local_os_package_archives': staged_archives, 'requested_requirements': pending,
                'skipped_inputs': issues, 'component_provenance': provenance, 'image_removals': removals,
                'dependency_satisfactions': normalize_satisfactions(state.get('dependency_satisfactions')),
                'projected_dependency_impacts': projected_dependencies}, indent=2), encoding='utf-8')
        except Exception as exc:
            messagebox.showerror('Build context', str(exc), parent=self)
            return False
        state['image_name'] = image
        state['generated_context'] = str(context)
        state['generated_dockerfile'] = str(context / 'Dockerfile')
        state['validation'] = dict(state.get('validation', {}), last_results={})
        self._generation_issues = issues
        self.out.delete('1.0', 'end')
        self.out.insert('end', dockerfile + ('\n\nBUILD WARNINGS:\n' + '\n'.join(issues) if issues else ''))
        self.status.set('Dockerfile generated; ready to build')
        return True

    def show(self):
        path = Path(self.context.get().strip()) / 'Dockerfile'
        if not path.is_file():
            messagebox.showerror('Dockerfile', 'Generate the Dockerfile first.', parent=self)
            return
        self.out.delete('1.0', 'end')
        self.out.insert('end', path.read_text(encoding='utf-8'))

    def compact_built_image(self):
        image = str(self.app.state.get('built_image') or self.image.get() or '').strip()
        if not image:
            messagebox.showerror('Compact image', 'Build an image first.', parent=self)
            return
        def complete(result):
            self.app.state['compacted_image'] = result['image']
            self.app.state['built_image'] = result['image']
            self.app.state['image_name'] = result['image']
            previous_report = dict(self.app.state.get('last_build_report') or {})
            if previous_report.get('image') == result.get('source'):
                previous_report['image'] = result['image']
                previous_report['compaction'] = result
                self.app.state['last_build_report'] = previous_report
            self.app.state['validation'] = dict(self.app.state.get('validation', {}), last_results={}, verified_image_id='')
            validator = getattr(self.app, 'validation_tab', None)
            if validator is not None:
                validator.refresh_from_project_state()
            self.out.insert('end', '\nCompacted image: ' + result['image'] + '\n')
            self.out.see('end')
        show_compaction_dialog(self, image, complete)

    def revise_built_image(self):
        image = str(self.app.state.get('built_image', '') or '').strip()
        if not image:
            messagebox.showerror('Revise image', 'Build a Docker image first. To load an exported TAR, use Tab 2.', parent=self)
            return False
        try:
            require_local_image(image)
        except Exception as exc:
            messagebox.showerror('Revise image', str(exc), parent=self)
            return False
        suggestion = derive_next_tag(image)
        new_tag = simpledialog.askstring('Revise existing image',
                                        'The completed image becomes the new runtime base.\nEnter a NEW image tag for the updated image. The original remains unchanged:',
                                        initialvalue=suggestion, parent=self)
        if new_tag is None:
            return False
        new_tag = new_tag.strip()
        if not new_tag or new_tag == image or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.:/-]*', new_tag):
            messagebox.showerror('Revise image', 'Enter a valid NEW image tag different from the original.', parent=self)
            return False
        self.app.state.publish_base(archive='', tag=image, system=self.app.state.get('base_system', {}), inventory={})
        self.app.state.update({'image_name': new_tag, 'built_image': '', 'generated_dockerfile': '',
                               'runtime_libraries': {}, 'validation': {}, 'last_build_report': {}})
        self.image.set(new_tag)
        self._last_plan = None
        self._last_environment = None
        self.status.set('REVISION: base is ' + image + '; next image is ' + new_tag)
        self.out.delete('1.0', 'end')
        self.out.insert('end', 'Original image retained locally: ' + image + '\nNew base image: ' + image +
                        '\nNew image tag: ' + new_tag + '\nAdd or change components in Tab 3, then build again.\n')
        return True

    @staticmethod
    def _read_setup_issues(image):
        return BuildTab._read_image_report(image, 'setup-issues.txt')

    @staticmethod
    def _read_image_report(image, filename):
        container = ''
        try:
            proc = subprocess.run(['docker', 'create', '--entrypoint', '/bin/sh', image], capture_output=True,
                                  text=True, timeout=18, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if proc.returncode:
                return ['Could not inspect dependency-installation report: ' + proc.stderr.strip()[-350:]]
            container = proc.stdout.strip()
            proc = subprocess.run(['docker', 'cp', container + ':/opt/component-builder/' + filename, '-'],
                                  capture_output=True, timeout=18, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if proc.returncode:
                return []
            import io
            import tarfile
            with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode='r:*') as archive:
                member = next((value for value in archive.getmembers() if value.isfile()), None)
                if member is None:
                    return []
                content = archive.extractfile(member).read().decode('utf-8', errors='replace')
                return [line.strip() for line in content.splitlines() if line.strip()]
        except (OSError, subprocess.TimeoutExpired, ValueError, EOFError) as exc:
            return ['Could not verify dependency-installation report: ' + str(exc)]
        finally:
            if container:
                try:
                    subprocess.run(['docker', 'rm', '-f', container], capture_output=True,
                                   timeout=12, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                except (OSError, subprocess.TimeoutExpired):
                    pass

    def build(self):
        if self._busy:
            return
        if not self.generate():
            return
        image = self.image.get().strip()
        base = str(self.app.state.get('base_image', '') or '').strip()
        context = self.context.get().strip()
        plan = self._last_plan or self._plan()
        env = self._last_environment or package_plan(self.app.state, plan['manager'], plan)
        manifest_path = Path(context) / 'build_manifest.json'
        pending_path = Path(context) / 'pending_requirements.json'
        provenance_path = Path(context) / 'component_provenance.json'
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            pending = json.loads(pending_path.read_text(encoding='utf-8'))
            provenance = json.loads(provenance_path.read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror('Build', 'Generated build metadata is not readable: ' + str(exc), parent=self)
            return
        removals = normalize_removals(manifest.get('image_removals', []))
        packages = list(pending.get('os_packages') or [])
        install_now = self._will_install_now()
        policy = normalize_policy(self.app.state.get('package_download_policy'))
        mode = normalize_mode(self.app.state.get('build_mode'))
        initial_issues = list(self._generation_issues)
        self._busy = True
        self.build_button.config(state='disabled')
        self.status.set('ASSEMBLING IMAGE — ' + mode.upper())
        self.out.delete('1.0', 'end')
        self.out.insert('end', 'Build mode: ' + mode.upper() + '\n' + ('Enabled OS and language package installation will be attempted.\n' if install_now else 'Assembly only: no installations will be attempted.\n'))
        self._consume_messages()

        def log(value):
            self._messages.put(('log', value))

        def worker():
            code = -1
            detail = ''
            issues = list(initial_issues)
            network = 'none'
            try:
                require_local_image(base)
                for jar in plan['java']:
                    if jar['error']:
                        text = jar['name'] + ': ' + jar['error']
                        if mode == STRICT:
                            raise RuntimeError(text)
                        issues.append(text)
                    else:
                        log('  ' + jar['name'] + ' requires Java ' + str(jar['minimum']) + '+\n')
                for original, translated in plan['translations']:
                    log('Distribution package mapping: ' + original + ' => ' + translated + '\n')
                if plan['target_java'] is not None:
                    log('USER-SELECTED Java version: ' + str(plan['target_java']) + '\n')
                if install_now:
                    try:
                        inspection = inspect_packages(base, packages, timeout=16)
                    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
                        inspection = {'installed': [], 'missing': packages, 'manager': plan['manager'], 'unverified': True}
                        log('WARNING: Package inventory unavailable: ' + str(exc) + '\n')
                        if mode != STRICT:
                            issues.append('Package inventory could not be verified')
                    log('Already installed: ' + (', '.join(inspection['installed']) or 'none') + '\n')
                    log('Need installation or verification: ' + (', '.join(inspection['missing']) or 'none') + '\n')
                else:
                    inspection = {'installed': [], 'missing': packages, 'manager': plan['manager']}
                    if packages:
                        issues.append('Assembly-only build: requested OS packages NOT INSTALLED by this build: ' + ', '.join(packages))
                language_packages = env['language_packages']
                uncertain_language_downloads = [key + ': ' + ', '.join(value) for key, value in language_packages.items() if value]
                if not install_now and uncertain_language_downloads:
                    issues.append('Language packages NOT INSTALLED by assembly-only build: ' + '; '.join(uncertain_language_downloads))
                custom_network = bool(env['config']['allow_custom_network'] and
                                      (env['config']['pre_commands'] or env['config']['post_commands'] or env['config']['dockerfile_directives']))
                needs_network = bool((install_now and uncertain_language_downloads) or custom_network)
                if mode == ASSEMBLY:
                    if env['python_required'] or env['r_required'] or env['perl_required'] or uncertain_language_downloads:
                        issues.append('Assembly-only mode skipped language environment installation and checks')
                elif needs_network:
                    if policy == POLICY_OFFLINE:
                        if mode == STRICT:
                            raise RuntimeError('Offline policy prohibits missing package installation in strict mode')
                        issues.append('Network disabled; missing OS/language components NOT INSTALLED')
                        log('WARNING: Offline policy; downloading dependencies will be skipped.\n')
                    else:
                        response = {}
                        signal = threading.Event()
                        approval = dict(inspection)
                        approval['missing'] = list(uncertain_language_downloads)
                        if custom_network:
                            approval['missing'].append('Custom commands requiring network access')
                        self._messages.put(('approve', base, approval, response, signal))
                        if not signal.wait(timeout=600):
                            raise RuntimeError('Package download approval timed out')
                        if response.get('approved'):
                            network = 'default'
                        elif mode == STRICT:
                            raise RuntimeError('Package download not approved; strict mode stops the build')
                        else:
                            issues.append('Package downloads refused; proceeding without missing dependencies')
                            log('WARNING: Downloads refused. Building a partial image offline.\n')
                if mode == STRICT and plan['java'] and plan['target_java'] is None:
                    base_java = probe_java(base, timeout=12)
                    installed = base_java.get('version') if base_java.get('status') == 'OK' else None
                    if removals:
                        try:
                            archive = str(self.app.state.get('runtime_base_archive') or '')
                            snapshot = inspect_image_components(archive) if archive else {}
                        except Exception:
                            snapshot = {}
                        installed = max(projected_java_versions(self.app.state, snapshot), default=None)
                    for jar in plan['java']:
                        outcome = evaluate_java_requirement(jar['minimum'], installed, plan)
                        if outcome['status'] in ('MISSING', 'UNRESOLVED'):
                            raise RuntimeError(jar['name'] + ': ' + outcome['path'])
                args = ['docker', 'build', '--pull=false', '--network=' + network, '--progress=plain']
                if mode != STRICT:
                    args += ['--build-arg', 'COMPONENT_BUILDER_ALLOW_DOWNLOADS=' + ('1' if network == 'default' else '0')]
                args += ['-t', image, context]
                log('Network access: ' + network + '\n$ ' + subprocess.list2cmdline(args) + '\n')
                process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, text=True, errors='replace', bufsize=1,
                                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                for line in process.stdout:
                    log(line)
                code = process.wait()
                detail = 'Docker build exit code ' + str(code)
                if code == 0:
                    self._messages.put(('image_ready', image))
                    if mode != STRICT and (install_now or removals or env['config']['pre_commands'] or env['config']['post_commands'] or env['config']['verify_commands']):
                        found_issues = self._read_setup_issues(image)
                        issues += found_issues
                        for issue in found_issues:
                            log('INSTALLATION WARNING: ' + issue + '\n')
                    if install_now and network == 'none':
                        if uncertain_language_downloads:
                            issues.append('Unverified language packages: ' + '; '.join(uncertain_language_downloads))
                    if install_now and plan['java']:
                        verification = probe_java(image, timeout=12)
                        installed = verification.get('version') if verification.get('status') == 'OK' else None
                        minimums = [jar['minimum'] for jar in plan['java'] if jar['minimum']]
                        if installed is None:
                            issues.append('Final image JVM could not be verified; verify in Tab 7')
                            log('WARNING: Final Java runtime could not be queried.\n')
                        elif minimums and installed < max(minimums):
                            issues.append('Final Java ' + str(installed) + ' is older than required Java ' + str(max(minimums)))
                            log('WARNING: Final Java runtime is incompatible with some JARs.\n')
                        else:
                            log('VERIFIED: Java ' + str(installed) + ' satisfies all detected JAR minimum versions.\n')
                    detail = 'Docker image created successfully'
                else:
                    log('Docker image assembly failed with exit code ' + str(code) + '\n')
            except Exception as exc:
                if code == 0:
                    issues.append('Post-build reporting could not be completed: ' + str(exc))
                    detail = 'Docker image created successfully; post-build reporting incomplete'
                    log('WARNING: ' + str(exc) + '\n')
                else:
                    detail = str(exc)
                    log('BUILD FAILED: ' + detail + '\n')
            issues = list(dict.fromkeys(issues))
            quality = 'INCOMPLETE' if issues else ('NOT VERIFIED' if mode != STRICT else 'UNVERIFIED')
            report = {'image': image, 'base': base, 'mode': mode, 'quality': quality,
                      'issues': issues, 'network': network, 'docker_exit_code': code,
                      'installation_attempted': install_now,
                      'not_installed_os_packages': [x for x in packages if x not in inspection.get('installed', [])] if not install_now else [],
                      'not_installed_language_packages': env['language_packages'] if not install_now else {},
                      'provenance_revision': provenance.get('revision'),
                      'component_provenance_path': '/opt/component-builder/component_provenance.json',
                      'removed_this_revision': removals}
            self._messages.put(('finish', code, image, detail, report))

        threading.Thread(target=worker, daemon=True).start()
