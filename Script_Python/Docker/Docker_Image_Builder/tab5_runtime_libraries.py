from __future__ import annotations

import queue
import fnmatch
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from build_artifacts import read_record
from runtime_dependency_scanner import global_metrics, is_elf, metrics, scan_binary, local_elf_report, scan_binary_archive
from docker_archive_libraries import archive_library_inventory
from java_runtime_checker import minimum_java_version, probe_java
from dependency_planner import plan_runtime_dependencies, evaluate_java_requirement, java_package, identify_runtime_family
from image_component_inventory import inspect_image_components
from local_package_catalog import installed_java_versions, component_package_identity
from general_environment import package_plan, runtime_language_report
from environment_editor import EnvironmentEditor
from manual_installation_overrides import ManualOverrideDialog, compatible_java_override, confirmed_category, records_for_image, user_confirmed_package
from dependency_resolution_ui import DependencyResolutionDialog
from revision_dependencies import dependency_impact, projected_java_versions, project_scan_result, removal_matches
from image_removals import normalize_removals
from recognized_elements import load_database
from workflow_toolbar import add_more_menu
from comprehensive_dependency_analysis import InspectionWindow


class RuntimeTab(tk.Frame):
    ANALYZABLE_KINDS = {'binary', 'source', 'other', 'jar/application'}

    def __init__(self, parent, app):
        super().__init__(parent, bg='#FDEDEC')
        self.app = app
        self._results = {}
        self._files = {}
        self._runtime = ''
        self._busy = False
        self._pending = queue.Queue()
        self._work_id = 0
        self._active_names = []
        self._all_view = True
        self._auto_signature = None
        self._started_scan = False
        self._discovered_system = {}
        self._image_entries = {}
        self._image_snapshot = {}
        self._image_error = '' 
        self.base_summary = tk.StringVar()
        self.package_plan_summary = tk.StringVar()
        self.global_summary = tk.StringVar(value='Run Check All Components to calculate dependency totals.')
        self.unique_summary = tk.StringVar()
        self.progress = tk.StringVar()
        self.packages = tk.StringVar()
        self.selected_path = tk.StringVar()

        tk.Label(self, text='5 — COMPREHENSIVE DEPENDENCY ANALYSIS', bg='#922B21', fg='white',
                 font=('Segoe UI', 16, 'bold'), anchor='w', padx=14, pady=10).pack(fill='x')
        tk.Label(self, textvariable=self.base_summary, bg='#FADBD8', fg='#78281F',
                 anchor='w', padx=10, pady=7).pack(fill='x', padx=12, pady=(10, 3))
        tk.Label(self, textvariable=self.package_plan_summary, bg='#FDEBD0', fg='#7E5109',
                 anchor='w', padx=10, pady=5, wraplength=1420, justify='left').pack(fill='x', padx=12, pady=(0, 3))

        actions = tk.Frame(self, bg='#FDEDEC')
        actions.pack(fill='x', padx=12, pady=(5, 4))
        self.all_button = tk.Button(actions, text='Check All Components', bg='#C0392B', fg='white',
                                    command=self.check_all)
        self.all_button.pack(side='left', padx=3)
        self.one_button = tk.Button(actions, text='Check Selected Component', bg='#EC7063',
                                    command=self.check_selected)
        self.cancel_button = tk.Button(actions, text='Cancel / Reset Scan', bg='#F5B7B1',
                                       command=self.cancel_scan)
        self.cancel_button.pack(side='left', padx=3)
        tk.Button(actions, text='Add missing to Tab 3', bg='#F7DC6F', command=self.add_missing_component).pack(side='left', padx=3)
        tk.Button(actions, text='Explain runtime requirements', bg='#AED6F1',
                  command=self.show_language_requirements).pack(side='left', padx=3)
        tk.Button(actions, text='All dependency types', bg='#A9DFBF', command=self.open_comprehensive_analyzer).pack(side='left', padx=3)
        tk.Button(actions, text='Image file history', bg='#AED6F1', command=self.open_image_history).pack(side='left', padx=3)
        add_more_menu(actions, [
            ("Check only selected component", self.check_selected),
            ("Show all library details", self.show_all_details),
            ("Review removals / assign providers", self.review_dependencies),
            ("Manually confirm installed", self.manual_installation),
            ("Edit final-image runtime requirements", self.edit_language_requirements),
            ("Refresh library status", self.refresh_from_project_state),
        ], "#FDEDEC")
        tk.Label(actions, textvariable=self.progress, bg='#FDEDEC', fg='#78281F').pack(side='left', padx=12)

        totals = tk.Frame(self, bg='#FDEDEC')
        totals.pack(fill='x', padx=12, pady=(3, 7))
        tk.Label(totals, textvariable=self.global_summary, bg='#FADBD8', fg='#78281F',
                 padx=9, pady=7, anchor='w', font=('Segoe UI', 10, 'bold')).pack(fill='x')
        tk.Label(totals, textvariable=self.unique_summary, bg='#FDEDEC', fg='#78281F',
                 padx=9, pady=3, anchor='w').pack(fill='x')

        missing_frame = tk.Frame(self, bg='#FDEDEC')
        missing_frame.pack(fill='x', padx=12, pady=(2, 5))
        tk.Label(missing_frame, text='Outstanding requirements in opened runtime image', bg='#FDEDEC',
                 font=('Segoe UI', 10, 'bold')).pack(side='left')
        tk.Button(missing_frame, text='Add selected requirement to Tab 3', bg='#F7DC6F',
                  command=self.add_selected_requirement).pack(side='left', padx=10)
        self.outstanding = ttk.Treeview(self, columns=('software', 'requirement', 'state', 'action'),
                                        show='headings', height=4, selectmode='browse')
        for key, caption, width in (('software', 'Required by', 180), ('requirement', 'Requirement', 255),
                                    ('state', 'Actual status', 165), ('action', 'Notes / installation plan', 640)):
            self.outstanding.heading(key, text=caption)
            self.outstanding.column(key, width=width)
        self.outstanding.pack(fill='x', padx=12, pady=(0, 4))
        self._outstanding_entries = []

        tk.Label(self, text='Component dependency summary', bg='#FDEDEC',
                 font=('Segoe UI', 10, 'bold')).pack(anchor='w', padx=14, pady=(0, 3))
        overview_frame = tk.Frame(self, bg='#FDEDEC')
        overview_frame.pack(fill='x', padx=12, pady=(0, 6))
        self.overview = ttk.Treeview(
            overview_frame,
            columns=('component', 'type', 'needed', 'found', 'missing', 'planned', 'unresolved', 'state'),
            show='headings', height=6, selectmode='browse',
        )
        for key, caption, width in (
            ('component', 'Component', 180), ('type', 'Type', 185),
            ('needed', 'Required', 90), ('found', 'Found', 90),
            ('missing', 'Missing', 90), ('planned', 'Not installed', 95), ('unresolved', 'Unresolved', 100),
            ('state', 'Check status', 260),
        ):
            self.overview.heading(key, text=caption)
            self.overview.column(key, width=width, anchor='w' if key in ('component', 'type', 'state') else 'center')
        self.overview.tag_configure('failed', foreground='#A93226')
        self.overview.tag_configure('good', foreground='#196F3D')
        self.overview.pack(fill='x')
        self.overview.bind('<<TreeviewSelect>>', self._selection_changed)

        options = tk.Frame(self, bg='#FDEDEC')
        options.pack(fill='x', padx=12, pady=(3, 8))
        options.columnconfigure(1, weight=1)
        tk.Label(options, text='Executable (from Tabs 3–4):', bg='#FDEDEC').grid(row=0, column=0, sticky='w')
        tk.Entry(options, textvariable=self.selected_path, state='readonly').grid(
            row=0, column=1, columnspan=2, padx=7, pady=2, sticky='ew')
        tk.Label(options, text='Additional runtime packages:', bg='#FDEDEC').grid(row=1, column=0, sticky='w')
        tk.Entry(options, textvariable=self.packages).grid(row=1, column=1, padx=7, pady=2, sticky='ew')
        tk.Button(options, text='Save', bg='#CD6155', fg='white', command=self.save_packages).grid(
            row=1, column=2, sticky='w', padx=3)

        tk.Label(self, text='Native libraries and runtime requirements for selected component (or all components)', bg='#FDEDEC',
                 font=('Segoe UI', 10, 'bold')).pack(anchor='w', padx=14, pady=(0, 3))
        detail_frame = tk.Frame(self, bg='#FDEDEC')
        detail_frame.pack(fill='both', expand=True, padx=12, pady=(0, 6))
        self.detail = ttk.Treeview(detail_frame, columns=('component', 'library', 'status', 'location', 'category', 'purpose'),
                                   show='headings', height=12)
        for key, caption, width in (
            ('component', 'Component', 150), ('library', 'Required library / runtime', 230),
            ('status', 'Availability', 105), ('location', 'Location inside runtime image', 610),
            ('category', 'Category', 150),
            ('purpose', 'Recognized library purpose', 300),
        ):
            self.detail.heading(key, text=caption)
            self.detail.column(key, width=width, anchor='w')
        self.detail.tag_configure('missing', foreground='#A93226')
        self.detail.tag_configure('found', foreground='#196F3D')
        self.detail.tag_configure('planned', foreground='#B9770E')
        self.detail.configure(yscrollcommand=(lambda a, b: sy.set(a, b)),
                              xscrollcommand=(lambda a, b: sx.set(a, b)))
        sy = ttk.Scrollbar(detail_frame, orient='vertical', command=self.detail.yview)
        sx = ttk.Scrollbar(detail_frame, orient='horizontal', command=self.detail.xview)
        self.detail.grid(row=0, column=0, sticky='nsew')
        sy.grid(row=0, column=1, sticky='ns')
        sx.grid(row=1, column=0, sticky='ew')
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(0, weight=1)

        log_header = tk.Frame(self, bg='#FDEDEC')
        log_header.pack(fill='x', padx=12)
        tk.Label(log_header, text='Dependency inspection log', bg='#FDEDEC').pack(side='left')
        tk.Button(log_header, text='Clear log', bg='#D6DBDF',
                  command=lambda: self.out.delete('1.0', 'end')).pack(side='right')
        self.out = tk.Text(self, height=6, bg='white', font=('Consolas', 9), wrap='word')
        self.out.pack(fill='x', padx=12, pady=(0, 8))
        tk.Label(self, text='Static ELF binaries have no shared libraries. JARs are checked for minimum Java versions. Native checks inspect actual files in the selected runtime. A requested OS package is INSTALLED only when detected in that image.',
                 bg='#FDEDEC', fg='#78281F', anchor='w', wraplength=1450).pack(fill='x', padx=12, pady=(0, 6))
        self.refresh_from_project_state()

    def _analysis_source(self, component):
        path, reason = self._component_file(component)
        if path is not None:
            return str(path)
        direct = self._source_path(component.get('source', ''))
        if direct is not None and direct.is_file():
            return str(direct)
        return None

    def open_comprehensive_analyzer(self):
        InspectionWindow(self, self.app, list(self._components()), self._analysis_source, 'dependencies')

    def open_image_history(self):
        InspectionWindow(self, self.app, [], self._analysis_source, 'history')

    def manual_installation(self):
        name = self._selected_name()
        component = self._component(name) if name else None
        if component and str(component.get('kind', '')).lower() == 'jar/application':
            initial_category, initial_name = 'Java', 'Java runtime'
        else:
            initial_category, initial_name = 'Java', 'Java runtime'
            keys = self.outstanding.selection()
            if keys:
                item = self._outstanding_entries[int(keys[0])]
                if 'java' in str(item.get('requirement', '')).lower():
                    initial_category = 'Java'
                elif item.get('field') == 'python_version':
                    initial_category = 'Python'
                elif item.get('field') == 'r_version':
                    initial_category = 'R'
                elif item.get('field') == 'perl_version':
                    initial_category = 'Perl'
                elif item.get('category') in ('Shared library', 'Dynamic loader'):
                    initial_category = 'Native program'
                else:
                    initial_category = 'OS package'
                initial_name = 'Java runtime' if initial_category == 'Java' else str(item.get('requirement', ''))
        ManualOverrideDialog(self, self.app.state, initial_category, initial_name, on_save=self.refresh_from_project_state)

    def _reload_image(self):
        archive = str(self.app.state.get('runtime_base_archive', '') or '').strip()
        if not archive:
            self._image_entries = {}
            self._image_snapshot = {}
            return
        try:
            snapshot = inspect_image_components(archive)
            self._image_entries = {
                x['name']: {'enabled': True, 'name': x['name'], 'kind': x['kind'],
                            'source': x['local'], 'destination': x['path'], 'runtime_packages': '',
                            'present_in_image': True, 'java_minimum': x['java_minimum']}
                for x in snapshot['components']
            }
            detected = set(snapshot.get('installed_java_versions') or [])
            if snapshot.get('installed_java') is not None:
                detected.add(snapshot['installed_java'])
            detected.update(installed_java_versions(self.app.state.get('base_inventory')))
            snapshot = dict(snapshot)
            snapshot['installed_java_versions'] = sorted(detected)
            snapshot['installed_java'] = max(detected, default=None)
            self._image_snapshot = snapshot
            self._image_error = ''
        except Exception as exc:
            self._image_entries = {}
            self._image_snapshot = {}
            self._image_error = str(exc)

    def _components(self):
        added = [item for item in self.app.state.get('components', [])
                if isinstance(item, dict) and item.get('enabled', True)
                and str(item.get('name', '')).strip()
                and str(item.get('kind', '')).strip().lower() in self.ANALYZABLE_KINDS]
        names = {str(x.get('name', '')).lower() for x in added}
        removals = normalize_removals(self.app.state.get('image_removals'))
        return [*added, *(x for x in self._image_entries.values() if x['kind'] in self.ANALYZABLE_KINDS
                           and x['name'].lower() not in names
                           and not any(removal_matches(removal, x) for removal in removals))]

    def review_dependencies(self):
        DependencyResolutionDialog(self, self.app, self._image_snapshot, self._results)

    def _effective_result(self, name):
        return project_scan_result(self._results.get(name, {}), self.app.state.get('image_removals'))

    def _component(self, name):
        return next((component for component in self._components() if str(component.get('name', '')) == name), None)

    def _source_path(self, raw):
        raw = str(raw or '').strip().strip('"').strip("'")
        if not raw:
            return None
        path = Path(raw).expanduser()
        if not path.is_absolute():
            project_dir = str(self.app.state.get('project_dir', '') or '').strip()
            if project_dir:
                path = Path(project_dir) / path
        return path

    def _component_file(self, component):
        kind = str(component.get('kind', '')).lower()
        if kind == 'source':
            record, message = read_record(self.app.state, component)
            if not record:
                return None, message
            path = Path(record['artifact'])
        else:
            path = self._source_path(component.get('source', ''))
            if path is None or not path.is_file():
                return None, 'No existing executable file selected in Tab 3.'
        if kind == 'jar/application':
            if path.suffix.lower() != '.jar':
                return None, 'This Java component does not point to a JAR file.'
            return path, ''
        if not is_elf(path):
            return None, 'This component is not an ELF executable. Native shared-library analysis does not apply.'
        return path, ''

    def _current_files(self):
        result = {}
        for component in self._components():
            name = str(component['name'])
            path, reason = self._component_file(component)
            result[name] = (path, reason)
        return result

    def edit_language_requirements(self):
        editor = EnvironmentEditor(self, self.app.state)
        editor.bind('<Destroy>', lambda event: self.refresh_from_project_state() if event.widget is editor else None)

    def show_language_requirements(self):
        window = tk.Toplevel(self)
        window.title('Explain final-runtime and build-only language requirements')
        window.geometry('1050x680')
        window.transient(self.winfo_toplevel())
        body = tk.Text(window, font=('Consolas', 10), wrap='word')
        body.pack(fill='both', expand=True, padx=12, pady=12)
        try:
            body.insert('1.0', runtime_language_report(self.app.state))
        except Exception as exc:
            body.insert('1.0', 'Dependency explanation unavailable: ' + str(exc))
        body.configure(state='disabled')

    def _snapshot_signature(self, files=None):
        files = self._current_files() if files is None else files
        signature = []
        for name, (path, reason) in files.items():
            if path is None:
                signature.append((name, '', reason))
            else:
                try:
                    stat = path.stat()
                    signature.append((name, str(path), stat.st_size, stat.st_mtime_ns))
                except OSError:
                    signature.append((name, str(path), 'missing'))
        return (str(self.app.state.get('base_image', '') or ''),
                str(self.app.state.get('runtime_base_archive', '') or ''),
                tuple((str(c.get('name', '')), str(c.get('kind', '')), str(c.get('runtime_packages', '')), str(c.get('enabled', True))) for c in self.app.state.get('components', []) if isinstance(c, dict)),
                tuple(sorted((str(k), str(v)) for k, v in (self.app.state.get('environment_requirements') or {}).items())),
                tuple((x.get('kind'), x.get('name'), x.get('path')) for x in normalize_removals(self.app.state.get('image_removals'))),
                tuple((str(x.get('owner')), str(x.get('requirement')), str(x.get('provider'))) for x in self.app.state.get('dependency_satisfactions', []) if isinstance(x, dict)),
                tuple((str(x.get('name')), str(x.get('version')), str(x.get('executable'))) for x in records_for_image(self.app.state)), tuple(signature))

    def refresh_from_project_state(self):
        self._reload_image()
        base = str(self.app.state.get('base_image', '') or '').strip()
        system = self.app.state.get('base_system', {})
        system = system if isinstance(system, dict) else {}
        discovered = self._discovered_system if getattr(self, '_runtime', '') == base else {}
        self.base_summary.set(f'Runtime: {base or "NOT SELECTED"}   |   '
                              f'OS: {system.get("os", "") or discovered.get("os", "Unknown")}   |   '
                              f'Package manager: {system.get("package_manager", "") or discovered.get("package_manager", "Unknown")}')
        try:
            plan = plan_runtime_dependencies(self.app.state)
            env = package_plan(self.app.state, plan['manager'], plan)
            package_list = ', '.join(dict.fromkeys([*plan['packages'], *env['packages']])) or 'None'
            languages = []
            for lang, key in (('Java', 'java_version'), ('Python', 'python_version'), ('R', 'r_version'), ('Perl', 'perl_version')):
                if env['config'][key]:
                    languages.append(lang + ' ' + env['config'][key])
            for key, names in env['language_packages'].items():
                if names:
                    languages.append(key + ': ' + ', '.join(names))
            translations = '; '.join(original + ' → ' + translated for original, translated in plan['translations'])
            selection = ('  |  User-selected Java ' + str(plan['target_java'])) if plan['target_java'] else '  |  No Java runtime automatically selected'
            self.package_plan_summary.set('USER-SELECTED FINAL-IMAGE OS PACKAGES: ' + package_list +
                (('  |  Distribution translation: ' + translations) if translations else '') + selection +
                ('  |  Other user-selected requirements: ' + '; '.join(languages) if languages else '') +
                ('  |  Installation WILL be attempted during Tab 6.' if plan.get('install_now') else
                 '  |  Assembly-only: software not installed by this build.'))
        except Exception as exc:
            self.package_plan_summary.set('Dependency planning unavailable: ' + str(exc))
        files = self._current_files()
        signature = self._snapshot_signature(files)
        if getattr(self, '_signature', None) != signature:
            self._signature = signature
            self._work_id += 1
            self._busy = False
            self._auto_signature = None
            self._discovered_system = {}
            self._results = {name: self._preview(name, path, reason) for name, (path, reason) in files.items()}
            self.progress.set('Local requirements shown; runtime verification not yet complete.' if files else 'No supported components.')
        self._files = files
        self._runtime = base
        selected = self._selected_name()
        self._render(selected)

    def _selected_name(self):
        selected = self.overview.selection()
        return selected[0] if selected else ''

    def _render(self, keep_selected=''):
        names = list(self._files)
        self.overview.delete(*self.overview.get_children())
        for name in names:
            component = self._component(name)
            component_kind = str(component.get('kind', '')).lower()
            kind = 'Present in image' if component.get('present_in_image') else 'Compiled from Source' if component_kind == 'source' else 'Java JAR' if component_kind == 'jar/application' else 'Binary'
            result = self._effective_result(name)
            path, problem = self._files[name]
            if result:
                count = metrics(result)
                status = result['status']
                numbers = (count['needed'], count['found'], count['missing'], count['planned'], count['unresolved'])
                if status in ('ERROR', 'SKIPPED') and not result.get('libraries'):
                    numbers = ('—', '—', '—', '—', '—')
            else:
                numbers = ('—', '—', '—', '—', '—')
                status = 'UNAVAILABLE: ' + problem if path is None else 'NOT CHECKED'
            self.overview.insert('', 'end', iid=name, values=(name, kind, *numbers, status),
                                 tags=('failed' if status in ('MISSING', 'ERROR', 'INCOMPLETE') or status.startswith('UNAVAILABLE')
                                       else 'good' if status in ('OK', 'STATIC', 'PLANNED') else '',))
        if keep_selected in names:
            self.overview.selection_set(keep_selected)
        self._selection_changed()
        report = {name: self._effective_result(name) for name in names}
        totals = global_metrics(report)
        manually_confirmed = sum(1 for result in report.values() for item in result.get('libraries', [])
                                 if item.get('status') == 'USER CONFIRMED')
        if not names:
            self.global_summary.set('No enabled executable components to check.')
            self.unique_summary.set('')
        else:
            prefix = 'REQUIREMENTS FOUND — RUNTIME CHECK PENDING' if totals['not_checked'] == len(names) else 'PARTIAL RESULTS' if totals['not_checked'] or totals['failed'] else 'CHECK COMPLETE'
            self.global_summary.set(
                f'{prefix}  |  TOTAL: required {totals["needed"]}  |  found {totals["found"]}  |  missing {totals["missing"] + totals["planned"]}  |  '
                f'unresolved {totals["unresolved"]}  |  USER CONFIRMED {manually_confirmed}  |  checked {totals["checked"]}/{len(names)}'
            )
            self.unique_summary.set(
                f'Unique libraries: required {totals["unique_needed"]}  |  found {totals["unique_found"]}  |  '
                f'missing {totals["unique_missing"] + totals["unique_planned"]}  |  unresolved {totals["unique_unresolved"]}  |  '
                f'unchecked {totals["not_checked"]}  |  errors/skips {totals["failed"]}'
            )
        self.all_button.configure(state='normal')
        self.one_button.configure(state='normal')
        self.cancel_button.configure(state='normal')
        self._refresh_outstanding()

    def _outstanding_items(self):
        output = []
        active_java = (self._image_snapshot or {}).get('installed_java')
        snapshot = self._image_snapshot or {}
        pending = snapshot.get('pending') or {}
        os_installed = set()
        package_status = snapshot.get('installation_status') or {}
        inventory = self.app.state.get('base_inventory') or {}
        for item in ((inventory.get('packages') or {}).get('os') or []):
            if isinstance(item, dict):
                os_installed.add(str(item.get('name', '')).lower())
        for package in pending.get('os_packages', []) or []:
            identity, _ = component_package_identity({'kind': 'OS package', 'name': package})
            is_installed = identity.lower() in os_installed or package_status.get(package) == 'INSTALLED' or package_status.get(identity) == 'INSTALLED'
            if is_installed:
                continue
            manual = user_confirmed_package(self.app.state, package) or user_confirmed_package(self.app.state, identity)
            if manual:
                output.append({'owner': 'Earlier image record', 'requirement': package,
                               'status': 'USER CONFIRMED', 'detail': 'User claims installation at ' + manual['executable'] + '; execution NOT verified',
                               'package': '', 'category': 'OS package'})
                continue
            output.append({'owner': 'Earlier image record', 'requirement': package,
                           'status': 'INSTALLED' if is_installed else 'NOT INSTALLED',
                           'detail': 'Package is in the selected runtime inventory' if is_installed else 'Requested in an earlier image; not detected as installed. This is not a minimum runtime version',
                           'package': package if not is_installed else ''})
        for field, packages in (pending.get('language_packages') or {}).items():
            display = {'python_packages': 'Python / pip', 'cran_packages': 'R / CRAN',
                       'bioc_packages': 'R / Bioconductor', 'cpan_modules': 'Perl / CPAN'}.get(field, field)
            for name in packages:
                output.append({'owner': display, 'requirement': name,
                               'status': 'NOT INSTALLED',
                               'detail': 'Language package was previously requested but its installation has not been verified',
                               'package': '', 'field': field})
        for field, requested in (pending.get('language_versions') or {}).items():
            if not requested:
                continue
            label = {'python_version': 'Python interpreter', 'r_version': 'R interpreter',
                     'perl_version': 'Perl interpreter', 'java_version': 'Java runtime'}.get(field, field)
            category = {'java_version': 'Java', 'python_version': 'Python', 'r_version': 'R', 'perl_version': 'Perl'}.get(field)
            confirmations = confirmed_category(self.app.state, category, requested) if category else []
            if confirmations:
                selected = confirmations[0]
                output.append({'owner': label, 'requirement': requested, 'status': 'USER CONFIRMED',
                               'detail': 'User claims ' + selected['version'] + ' at ' + selected['executable'] + '; NOT automatically verified',
                               'package': '', 'field': field})
                continue
            if field == 'java_version' and active_java is not None:
                from general_environment import version
                actual = (int(active_java),)
                minimum = version(requested, label)
                if actual >= minimum:
                    continue
            output.append({'owner': label, 'requirement': requested,
                           'status': 'NOT INSTALLED',
                           'detail': 'Required interpreter version not verified in the image',
                           'package': '', 'field': field})
        for name in self._results:
            result = self._effective_result(name)
            for item in result.get('libraries', []):
                status = str(item.get('status', '')).upper()
                if status not in ('MISSING', 'UNRESOLVED', 'PLANNED'):
                    continue
                package = ''
                if item.get('category') == 'Java runtime':
                    import re
                    match = re.search(r'Java\s+(\d+)\+', item.get('name', ''))
                    if match:
                        required = int(match.group(1))
                        package = ''
                output.append({'owner': name, 'requirement': item.get('name', ''),
                               'status': status, 'detail': item.get('path', '') or 'Unknown provider', 'package': package,
                               'category': item.get('category')})
        for impact in dependency_impact(self.app.state, self._image_snapshot, self._results):
            if impact['status'] == 'FOUND':
                continue
            normalize_requirement = lambda value: str(value or '').lower().removesuffix(' jvm').strip()
            existing = next((row for row in output if row.get('owner') == impact['owner'] and
                             normalize_requirement(row.get('requirement')) == normalize_requirement(impact['requirement'])), None)
            if existing:
                existing.update(requirement=impact['requirement'], status=impact['status'], detail=impact['detail'])
                continue
            output.append({'owner': impact['owner'], 'requirement': impact['requirement'],
                           'status': impact['status'], 'detail': impact['detail'], 'package': '',
                           'category': impact['category']})
        return output

    def _refresh_outstanding(self):
        if not hasattr(self, 'outstanding'):
            return
        self.outstanding.delete(*self.outstanding.get_children())
        self._outstanding_entries = self._outstanding_items()
        for i, item in enumerate(self._outstanding_entries):
            self.outstanding.insert('', 'end', iid=str(i), values=(item['owner'], item['requirement'],
                                     item['status'], item['detail']))

    def add_selected_requirement(self):
        selection = self.outstanding.selection()
        if not selection:
            messagebox.showinfo('Missing requirements', 'Select an outstanding requirement first.', parent=self)
            return
        item = self._outstanding_entries[int(selection[0])]
        if item['status'] in ('PRESENT', 'INSTALLED'):
            messagebox.showinfo('Requirements', 'This package is already installed.', parent=self)
            return
        field = item.get('field')
        if field:
            from general_environment import normalize
            environment = normalize(self.app.state.get('environment_requirements') or {})
            if field.endswith('_version'):
                environment[field] = item['requirement']
            else:
                lines = [x.strip() for x in environment.get(field, '').splitlines() if x.strip()]
                if item['requirement'] not in lines:
                    lines.append(item['requirement'])
                environment[field] = '\n'.join(lines)
            self.app.state['environment_requirements'] = environment
            self.app.notebook.select(self.app.components_tab)
            messagebox.showinfo('Language requirement registered',
                                item['requirement'] + ' is saved in Language runtimes / Custom setup for a future revision.', parent=self)
            return
        package = item.get('package', '')
        if not package:
            package = simpledialog.askstring('OS package provider',
                'Requirement: ' + item['requirement'] + '\nThe builder does not select any OS package automatically.\nEnter the exact package YOU want, or Cancel to keep this requirement missing.', parent=self) or ''
        package = package.strip()
        import re
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+:_-]*', package):
            messagebox.showwarning('Missing requirement', 'No valid package name selected.', parent=self)
            return
        components = self.app.state.setdefault('components', [])
        if any(str(c.get('name', '')).lower() == package.lower() for c in components if isinstance(c, dict)):
            messagebox.showinfo('Missing requirement', package + ' is already registered in Tab 3 but is not installed in the opened image.', parent=self)
            return
        components.append({'name': package, 'kind': 'OS package', 'enabled': True, 'source': '',
                           'destination': '', 'version': '', 'runtime_packages': '',
                           'validation': 'java -version' if 'java' in package.lower() else ''})
        self.app.state.touch('components')
        self.app.components_tab.refresh_from_project_state()
        self.app.notebook.select(self.app.components_tab)
        messagebox.showinfo('Registered', package + ' has been added for a future image revision. No download was performed.', parent=self)

    def _selection_changed(self, event=None):
        if event is not None:
            self._all_view = False
        selected = self._selected_name()
        self.detail.delete(*self.detail.get_children())
        try:
            known_libraries = [entry for entry in load_database()
                               if entry['enabled'] and entry['kind'] == 'library']
        except ValueError:
            known_libraries = []
        rows = list(self._results) if self._all_view else [selected] if selected in self._files else list(self._results)
        for name in rows:
            result = self._effective_result(name)
            if result.get('status') == 'STATIC':
                self.detail.insert('', 'end', iid=f'{name}:static',
                                   values=(name, 'No shared libraries required', 'STATIC',
                                           'Self-contained ELF', 'Native binary', ''))
            if result.get('status') in ('ERROR', 'SKIPPED') and not result.get('libraries'):
                self.detail.insert('', 'end', iid=f'{name}:error',
                                   values=(name, result.get('error', 'Could not analyze'), 'ERROR',
                                           'Select component for details', 'Scan error', ''), tags=('missing',))
            for idx, item in enumerate(result.get('libraries', [])):
                known_purpose = next((entry['purpose'] for entry in known_libraries
                                      if fnmatch.fnmatchcase(item['name'].lower(),
                                                            (entry['pattern'] or entry['name']).lower())), '')
                self.detail.insert('', 'end', iid=f'{name}:{idx}',
                                   values=(name, item['name'], item['status'], item['path'] or 'NOT FOUND',
                                           item['category'], known_purpose),
                                   tags=('missing' if item['status'] == 'MISSING' else 'found' if item['status'] == 'FOUND' else 'planned' if item['status'] in ('PLANNED', 'USER CONFIRMED') else '',))
        if selected and selected in self._files:
            path, _ = self._files[selected]
            component = self._component(selected)
            self.selected_path.set(str(path) if path else '')
            self.packages.set(str(component.get('runtime_packages', '') or '') if component else '')
            result = self._effective_result(selected)
            log = result.get('detail', '') if result else 'Select Check All Components to inspect this executable. Static binaries have no native shared libraries.'
            if result and result.get('error'):
                log += '\n' + result['error']
        else:
            self.selected_path.set('')
            self.packages.set('')
            log = ''
        self.out.delete('1.0', 'end')
        self.out.insert('end', log)

    def show_all_details(self):
        self._all_view = True
        self._selection_changed()

    def save_packages(self):
        name = self._selected_name()
        component = self._component(name)
        if component is None:
            messagebox.showwarning('Runtime packages', 'Select one component first.', parent=self)
            return
        component['runtime_packages'] = self.packages.get().strip()
        notify = getattr(self.app.state, 'touch', None)
        if callable(notify):
            notify('components')
        self.refresh_from_project_state()

    def _image_java_resolution(self, minimum, plan):
        remaining = projected_java_versions(self.app.state, self._image_snapshot)
        installed = max(remaining, default=None)
        pending = self._image_snapshot.get('pending') or {}
        required_package = ', '.join(pending.get('os_packages', []) or [])
        if installed is not None and installed >= minimum:
            return {'status': 'FOUND', 'path': 'Java ' + str(installed) + ' is present in the opened image'}
        confirmed = compatible_java_override(self.app.state, minimum)
        if confirmed:
            return {'status': 'USER CONFIRMED', 'path':
                    'USER CONFIRMED: Java ' + confirmed['version'] + ' at ' + confirmed['executable'] +
                    '. This is a manual assertion, not an executed check.' +
                    (' Automatic inventory found Java ' + str(installed) + ' only.' if installed is not None else '')}
        if installed is not None:
            message = 'Java ' + str(installed) + ' is present, but Java ' + str(minimum) + '+ is required'
            if required_package:
                message += '; an earlier image recorded ' + required_package + ' as requested but NOT INSTALLED (not a minimum requirement)'
            return {'status': 'MISSING', 'path': message}
        message = 'Java version could not be verified from the image metadata'
        if required_package:
            message += '; earlier recorded package: ' + required_package + ' (NOT INSTALLED; not a minimum version)'
        return {'status': 'UNRESOLVED', 'path': message}

    def _missing_packages(self, result):
        requirements = [x for x in result.get('libraries', []) if x.get('status') == 'MISSING']
        if not requirements:
            return []
        pending = self._image_snapshot.get('pending') or {}
        planned = list(pending.get('os_packages') or [])
        found = []
        for row in requirements:
            if row.get('category') == 'Java runtime':
                match = __import__('re').search(r'Java\s+(\d+)\+', row['name'])
                if not match:
                    continue
                required = int(match.group(1))
                response = simpledialog.askstring('Choose Java package yourself',
                    'This application requires Java ' + str(required) + ' or newer.\n'
                    'The builder will NOT select a Java version or OS package automatically.\n'
                    'Enter the exact package name you want to add for this Linux distribution, or Cancel to leave it missing.',
                    parent=self)
                if response and response.strip():
                    import re
                    package = response.strip()
                    if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+:_-]*', package):
                        found.append(package)
                    else:
                        messagebox.showwarning('Invalid package', 'Enter a valid Linux package identifier.', parent=self)
            elif row.get('category') in ('Shared library', 'Dynamic loader'):
                name = row.get('name', '')
                response = simpledialog.askstring('Missing native dependency',
                    'The image is missing ' + name + '.\nEnter the actual OS package name that provides it for this Linux distribution, or Cancel to leave it unresolved.',
                    parent=self)
                if response and response.strip():
                    candidate = response.strip()
                    import re
                    if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+:_-]*', candidate):
                        found.append(candidate)
                    else:
                        messagebox.showwarning('Invalid package name', 'The supplied name is not a valid OS package identifier.', parent=self)
        return list(dict.fromkeys(found))

    def add_missing_component(self):
        selected = self._selected_name()
        if not selected:
            messagebox.showinfo('Missing requirements', 'Select a component with missing requirements first.', parent=self)
            return
        result = self._results.get(selected, {})
        packages = self._missing_packages(result)
        if not packages:
            messagebox.showinfo('Missing requirements', 'No OS package was selected. Choose an actual package yourself to address the missing requirement.', parent=self)
            return
        components = self.app.state.setdefault('components', [])
        existing = {str(x.get('name', '')).lower() for x in components if isinstance(x, dict)}
        added = []
        for package in packages:
            if package.lower() in existing:
                continue
            components.append({'name': package, 'kind': 'OS package', 'enabled': True, 'source': '',
                               'destination': '', 'version': '', 'runtime_packages': '',
                               'validation': 'java -version' if 'java' in package.lower() else ''})
            added.append(package)
        if not added:
            messagebox.showinfo('Missing requirements', 'The package is already listed in Tab 3. It remains missing inside the opened image until you install it in a revision.', parent=self)
            return
        touch = getattr(self.app.state, 'touch', None)
        if callable(touch):
            touch('components')
        self.app.components_tab.refresh_from_project_state()
        self.app.notebook.select(self.app.components_tab)
        messagebox.showinfo('Added to Tab 3', 'Registered for a future image revision: ' + ', '.join(added) + '\nNo package was installed or downloaded.', parent=self)

    def _preview(self, name, path, reason):
        if path is None:
            return {'status': 'ERROR', 'libraries': [], 'detail': '', 'error': reason}
        component = self._component(name)
        if component and str(component.get('kind', '')).lower() == 'jar/application':
            try:
                minimum = minimum_java_version(path)
                plan = plan_runtime_dependencies(self.app.state)
                resolution = self._image_java_resolution(minimum, plan) if component.get('present_in_image') else evaluate_java_requirement(minimum, None, plan)
                if resolution['status'] != 'FOUND':
                    confirmed = compatible_java_override(self.app.state, minimum)
                    if confirmed:
                        resolution = {'status': 'USER CONFIRMED', 'path': 'User claims Java ' + confirmed['version'] +
                            ' at ' + confirmed['executable'] + '; NOT automatically verified'}
                status = resolution['status']
                return {'status': 'MISSING' if status == 'MISSING' else 'OK' if status == 'FOUND' else 'USER CONFIRMED' if status == 'USER CONFIRMED' else 'PLANNED' if status == 'PLANNED' else 'PREVIEW', 'libraries': [
                    {'name': f'Java {minimum}+ JVM', 'status': status, 'path': resolution['path'], 'category': 'Java runtime'}],
                    'detail': f'JAR bytecode requires Java {minimum}+.\n' + resolution['path'], 'error': ''}
            except Exception as exc:
                return {'status': 'ERROR', 'libraries': [], 'detail': '', 'error': str(exc)}
        result = local_elf_report(path)
        if result['status'] == 'INCOMPLETE':
            result['status'] = 'PREVIEW'
        return result

    def auto_check(self):
        self.refresh_from_project_state()
        signature = self._snapshot_signature(self._files)
        if not self._busy and self._auto_signature != signature and self._files:
            self._auto_signature = signature
            self._begin_check(list(self._files))

    def cancel_scan(self):
        self._work_id += 1
        self._busy = False
        self.progress.set('Previous check cancelled. Local requirements remain visible. Click Check All to retry.')
        self._render(self._selected_name())

    def _begin_check(self, names):
        if self._busy:
            self.cancel_scan()
        runtime = str(self.app.state.get('base_image', '') or '').strip()
        if not runtime:
            messagebox.showerror('Runtime', 'Select a runtime image in Tab 1.', parent=self)
            return
        files = self._current_files()
        names = [name for name in names if name in files]
        if not names:
            messagebox.showinfo('Runtime', 'No eligible executable components were found.', parent=self)
            return
        self._busy = True
        self._work_id += 1
        work_id = self._work_id
        signature = self._snapshot_signature(files)
        kinds = {name: str((self._component(name) or {}).get('kind', '')).lower() for name in names}
        archive = str(self.app.state.get('runtime_base_archive', '') or '').strip()
        self._active_names = names
        self._auto_signature = signature
        self.progress.set(f'Checking 0/{len(names)} — reading selected runtime...')
        self._render(self._selected_name())

        def worker():
            try:
                inventory = None
                archive_error = ''
                if archive:
                    try:
                        inventory = archive_library_inventory(archive)
                    except Exception as exc:
                        archive_error = f'Docker archive could not be inspected: {exc}'
                if inventory:
                    self._pending.put((work_id, signature, '__inventory__', inventory, 0, len(names)))
                self._pending.put((work_id, signature, '__stage__',
                                   'Runtime archive indexed; checking components...' if inventory else
                                   'Runtime archive unavailable; checking with Docker...', 0, len(names)))
                java_probe = None
                plan = plan_runtime_dependencies(self.app.state, manager=None if inventory is None else (inventory.get('package_manager') or inventory.get('os')))
                for index, name in enumerate(names, start=1):
                    path, reason = files[name]
                    try:
                        if path is None:
                            result = {'status': 'ERROR', 'libraries': [], 'error': reason, 'detail': ''}
                        elif kinds[name] == 'jar/application':
                            minimum = minimum_java_version(path)
                            if java_probe is None:
                                java_probe = probe_java(runtime, timeout=25)
                            base_version = java_probe.get('version') if java_probe.get('status') == 'OK' else None
                            resolution = evaluate_java_requirement(minimum, base_version, plan,
                                java_probe.get('detail', '') if java_probe.get('status') != 'OK' else '')
                            if resolution['status'] != 'FOUND':
                                confirmed = compatible_java_override(self.app.state, minimum)
                                if confirmed:
                                    resolution = {'status': 'USER CONFIRMED', 'path': 'User claims Java ' + confirmed['version'] +
                                        ' at ' + confirmed['executable'] + '; NOT automatically verified'}
                            status = resolution['status']
                            result = {'status': 'USER CONFIRMED' if status == 'USER CONFIRMED' else 'PLANNED' if status == 'PLANNED' else 'OK' if status == 'FOUND' else 'MISSING' if status == 'MISSING' else 'INCOMPLETE',
                                'libraries': [{'name': f'Java {minimum}+ JVM', 'status': status,
                                'path': resolution['path'], 'category': 'Java runtime'}],
                                'detail': f'JAR bytecode requires Java {minimum}+.\n' + resolution['path'],
                                'error': '' if status in ('PLANNED', 'FOUND', 'USER CONFIRMED') else resolution['path']}
                            if archive_error:
                                result['detail'] += '\n' + archive_error
                        elif inventory is not None:
                            result = scan_binary_archive(path, inventory)
                        else:
                            result = scan_binary(path, runtime, timeout=25)
                            if archive_error:
                                result['detail'] += '\n' + archive_error
                    except Exception as exc:
                        result = self._preview(name, path, reason)
                        result['error'] = f'Component check failed: {exc}'
                        if result['status'] == 'PREVIEW':
                            result['status'] = 'INCOMPLETE'
                    self._pending.put((work_id, signature, name, result, index, len(names)))
            except Exception as exc:
                self._pending.put((work_id, signature, '__stage__',
                                   f'Runtime check error: {exc}', 0, len(names)))
            finally:
                self._pending.put((work_id, signature, None, None, len(names), len(names)))

        threading.Thread(target=worker, daemon=True).start()
        self.after(90, self._poll)

    def _poll(self):
        running = True
        while True:
            try:
                work_id, signature, name, result, count, total = self._pending.get_nowait()
            except queue.Empty:
                break
            if work_id != self._work_id:
                continue
            if self._snapshot_signature() != signature:
                self._busy = False
                self._work_id += 1
                self.progress.set('Components or runtime changed. Local requirements remain visible; run Check All again.')
                running = False
                break
            if name == '__inventory__':
                self._discovered_system = {'os': result.get('os', 'unknown'), 'package_manager': result.get('package_manager', 'unknown')}
                self.base_summary.set(f'Runtime: {self._runtime}   |   '
                                      f'OS: {result.get("os", "unknown")}   |   '
                                      f'Package manager: {result.get("package_manager", "unknown")} '
                                      '(detected from runtime archive)')
                continue
            if name == '__stage__':
                self.progress.set(result)
                self._render(self._selected_name())
                continue
            if name is None:
                self._busy = False
                self.progress.set(f'Completed {total} component checks. Select a row for details.')
                running = False
            else:
                self._results[name] = result
                self.progress.set(f'Checking {count}/{total} components ...')
            self._render(self._selected_name())
        if running and self._busy:
            self.after(100, self._poll)
        else:
            self._render(self._selected_name())

    def check_all(self):
        self.refresh_from_project_state()
        self._begin_check(list(self._files))

    def check_selected(self):
        self.refresh_from_project_state()
        name = self._selected_name()
        if not name:
            messagebox.showwarning('Runtime', 'Select a component first.', parent=self)
            return
        self._begin_check([name])


if __name__ == '__main__':
    from project_state import ProjectState
    root = tk.Tk()
    root.geometry('1500x900')
    class Demo:
        def __init__(self):
            self.state = ProjectState()
    tab = RuntimeTab(root, Demo())
    tab.pack(fill='both', expand=True)
    root.mainloop()
