import json
import re
import threading
import queue
import ntpath
import posixpath
import shlex
import tkinter as tk
from pathlib import Path
from source_archive import archive_stem, is_source_archive
from tkinter import filedialog, messagebox, simpledialog, ttk, scrolledtext

from binary_version_probe import probe_binary_version, inspect_jar
from component_presets import suggested_destination, validation_presets
from compilation_status import compilation_status
from component_file_types import inspect_component_file, validate_component_type
from dependency_planner import identify_runtime_family
from environment_editor import EnvironmentEditor
from image_component_inventory import inspect_image_components
from image_removals import java_runtime_packages, normalize_removals, protected_package, removal_id, safe_directory_path, safe_file_path, safe_package_name
from dependency_resolution_ui import DependencyResolutionDialog
from revision_dependencies import dependency_impact
from manual_installation_overrides import ManualOverrideDialog, records_for_image


from local_package_catalog import package_catalog, package_identity, package_archive_type, compatible_package_file, installed_packages, component_files, component_package_identity, installed_package_record, installed_java_versions
from local_builder_package_dialog import LocalBuilderPackageDialog
from repository_package_dialog import RepositoryPackageInstallDialog


class ComponentsTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg="#E8F8F5")
        self.app = app

        if "components" not in self.app.state or not isinstance(self.app.state["components"], list):
            self.app.state["components"] = []
        self.app.state.setdefault("base_image", "")
        self.app.state.setdefault("runtime_base_archive", "")
        self.app.state.setdefault("base_system", {})
        self.app.state.setdefault("base_inventory", {})
        self.app.state.setdefault('image_removals', [])
        self._visible_image_items = {}

        tk.Label(
            self,
            text="3 — ADD COMPONENTS / DEPENDENCY RESOLUTION",
            bg="#117864",
            fg="white",
            font=("Segoe UI", 16, "bold"),
            anchor="w",
            padx=14,
            pady=10,
        ).pack(fill="x")

        base_frame = tk.LabelFrame(
            self,
            text=" Selected runtime base from Tab 1 ",
            bg="#E8F8F5",
            fg="#0E6655",
            font=("Segoe UI", 10, "bold"),
            padx=8,
            pady=6,
        )
        base_frame.pack(fill="x", padx=12, pady=(10, 2))
        self.base_summary = tk.StringVar()
        tk.Label(
            base_frame,
            textvariable=self.base_summary,
            bg="#E8F8F5",
            justify="left",
            anchor="w",
        ).pack(fill="x")

        toolbar = tk.Frame(self, bg="#E8F8F5")
        toolbar.pack(fill="x", padx=12, pady=10)

        tk.Button(toolbar, text="Add component", bg="#48C9B0", command=lambda: self.component_dialog(None)).pack(side="left", padx=3)
        tk.Button(toolbar, text="Edit", bg="#45B39D", command=self.edit_selected).pack(side="left", padx=3)
        tk.Button(toolbar, text="Enable/Disable", bg="#16A085", fg="white", command=self.toggle_selected).pack(side="left", padx=3)
        tk.Button(toolbar, text="Remove", bg="#138D75", fg="white", command=self.remove_selected).pack(side="left", padx=3)
        tk.Button(toolbar, text="Resolve dependencies", bg="#0E6655", fg="white", command=self.resolve_dependencies).pack(side="left", padx=3)
        tk.Button(toolbar, text="Language runtimes / Custom setup", bg="#D4AC0D", command=lambda: EnvironmentEditor(self, self.app.state)).pack(side="left", padx=3)
        tk.Button(toolbar, text="Import component JSON", bg="#5DADE2", command=self.import_component_json).pack(side="left", padx=3)
        tk.Button(toolbar, text="Export selected JSON", bg="#3498DB", fg="white", command=self.export_selected_json).pack(side="left", padx=3)
        tk.Button(toolbar, text="Refresh", bg="#A2D9CE", command=self.refresh).pack(side="left", padx=3)

        local_install_row = tk.Frame(self, bg='#E8F8F5')
        local_install_row.pack(fill='x', padx=14, pady=(0, 6))
        tk.Button(local_install_row, text='Install local package into builder', bg='#F5B041',
                  command=self.install_local_builder_packages).pack(side='left', padx=3)
        tk.Button(local_install_row, text='Install local package into runtime base', bg='#85C1E9',
                  command=self.install_local_runtime_packages).pack(side='left', padx=3)
        tk.Button(local_install_row, text='Install packages online into builder', bg='#58D68D',
                  command=lambda: RepositoryPackageInstallDialog(self, self.app, target='builder',
                                                                 on_complete=self.refresh)).pack(side='left', padx=3)
        tk.Button(local_install_row, text='Install packages online into runtime', bg='#76D7C4',
                  command=lambda: RepositoryPackageInstallDialog(self, self.app, target='runtime',
                                                                 on_complete=self.refresh)).pack(side='left', padx=3)
        tk.Label(local_install_row, text='Local files: offline. Online: dependencies resolved automatically after approval.',
                 bg='#E8F8F5', fg='#21618C', anchor='w').pack(side='left', padx=10)

        self.show_image_components = tk.BooleanVar(value=bool(self.app.state.get('show_image_components', False)))
        image_row = tk.Frame(self, bg='#E8F8F5')
        image_row.pack(fill='x', padx=14, pady=(0, 5))
        tk.Button(image_row, text='Manually confirm installed', bg='#F7DC6F', command=self.manual_installation).pack(side='right', padx=5)
        tk.Button(image_row, text='Review removal dependencies / substitutes', bg='#D4E6F1',
                  command=self.review_dependencies).pack(side='right', padx=5)
        tk.Checkbutton(image_row, text='Show image components', variable=self.show_image_components,
                       command=self.toggle_image_components, bg='#E8F8F5', fg='#0E6655',
                       font=('Segoe UI', 10, 'bold')).pack(side='left')
        self.inventory_category = tk.StringVar(value=str(self.app.state.get('inventory_category', 'Applications')))
        self.inventory_origin = tk.StringVar(value=str(self.app.state.get('inventory_origin', 'All')))
        self.show_builder_inventory = tk.BooleanVar(value=bool(self.app.state.get('show_builder_inventory', False)))
        tk.Label(image_row, text='Inventory:', bg='#E8F8F5').pack(side='left', padx=(8, 2))
        category_box = ttk.Combobox(image_row, textvariable=self.inventory_category, state='readonly', width=17,
                                    values=('Applications', 'All software', 'OS packages', 'Python packages', 'R packages', 'Perl packages', 'Executables', 'All JARs', 'Language runtimes'))
        category_box.pack(side='left', padx=2)
        category_box.bind('<<ComboboxSelected>>', lambda e: self._inventory_settings())
        tk.Label(image_row, text='Origin:', bg='#E8F8F5').pack(side='left', padx=(8, 2))
        origin_box = ttk.Combobox(image_row, textvariable=self.inventory_origin, state='readonly', width=17,
                                 values=('All', 'Added', 'Compiled using builder', 'Inherited / unknown', 'Not installed'))
        origin_box.pack(side='left', padx=2)
        origin_box.bind('<<ComboboxSelected>>', lambda e: self._inventory_settings())
        tk.Checkbutton(image_row, text='Show builder-only inventory', variable=self.show_builder_inventory,
                       command=self._inventory_settings, bg='#E8F8F5').pack(side='left', padx=6)
        self.image_notice = tk.StringVar(value='Shows installed applications from the selected runtime image; these are not copied twice.')
        tk.Label(image_row, textvariable=self.image_notice, bg='#E8F8F5', fg='#21618C').pack(side='left', padx=10)

        columns = (
            "on",
            "name",
            "version",
            "kind",
            "comp_required",
            "comp_status",
            "compiled_version",
            "source",
            "destination",
            "depends",
            "builddeps",
            "runtime",
            "base_status",
            "base_version",
            "origin", "revision", "scope",
        )
        tree_holder = tk.Frame(self, bg="#E8F8F5")
        tree_holder.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.tree = ttk.Treeview(
            tree_holder,
            columns=columns,
            show="headings",
            height=19,
            selectmode="extended",
        )

        headings = {
            "on": "On",
            "name": "Name",
            "version": "Version",
            "kind": "Type",
            "comp_required": "Compile?",
            "comp_status": "Build / install status",
            "compiled_version": "Compiled version",
            "source": "Source",
            "destination": "Destination",
            "depends": "Depends",
            "builddeps": "Build deps",
            "runtime": "Runtime packages",
            "base_status": "Base status",
            "base_version": "Base version",
            "origin": "Origin / provenance",
            "revision": "Revision",
            "scope": "Image scope",
        }
        widths = {
            "on": 55,
            "name": 170,
            "version": 95,
            "kind": 125,
            "comp_required": 110,
            "comp_status": 165,
            "compiled_version": 125,
            "source": 260,
            "destination": 240,
            "depends": 190,
            "builddeps": 190,
            "runtime": 190,
            "base_status": 115,
            "base_version": 150,
            "origin": 190,
            "revision": 75,
            "scope": 135,
        }

        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], anchor="w")

        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll_y = ttk.Scrollbar(tree_holder, orient="vertical", command=self.tree.yview)
        tree_scroll_x = ttk.Scrollbar(tree_holder, orient="horizontal", command=self.tree.xview)
        tree_scroll_y.grid(row=0, column=1, sticky="ns")
        tree_scroll_x.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)
        tree_holder.columnconfigure(0, weight=1)
        tree_holder.rowconfigure(0, weight=1)
        self.tree.tag_configure('image_present', background='#D6EAF8', foreground='#154360')
        self.tree.tag_configure('builder_only', background='#F4ECF7', foreground='#6C3483')
        self.tree.tag_configure('deferred', background='#FCF3CF', foreground='#9C640C')
        self.tree.tag_configure('user_confirmed', background='#FCF3CF', foreground='#7D6608')
        self.tree.tag_configure('remove_pending', background='#FADBD8', foreground='#922B21')
        self.tree.tag_configure("compiled", background="#E1F5E8")
        self.tree.tag_configure("outdated", background="#FFF0CF")
        self.tree.tag_configure("failed", background="#FCE3E2")
        self.tree.tag_configure("notcompiled", background="#F9F5E6")
        self.tree.bind("<Double-1>", lambda event: self.edit_selected())

        self.compilation_summary = tk.StringVar(value="")
        tk.Label(self, textvariable=self.compilation_summary, bg="#D5F5E3", fg="#0E6655",
                 anchor="w", padx=10, pady=5).pack(fill="x", padx=12, pady=(0, 4))
        messages_header = tk.Frame(self, bg="#E8F8F5")
        messages_header.pack(fill="x", padx=12)
        tk.Label(messages_header, text="Dependency messages", bg="#E8F8F5",
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Button(messages_header, text="Clear log", bg="#D6DBDF",
                  command=lambda: self.output.delete('1.0', 'end')).pack(side="right")

        self.output = tk.Text(self, height=8, bg="white", font=("Consolas", 9))
        self.output.pack(fill="x", padx=12, pady=(4, 12))

        self.refresh()

    def _selected_local_package_files(self):
        files = []
        for item in self.tree.selection():
            try:
                index = int(item)
                component = self.app.state.get('components', [])[index]
            except (ValueError, IndexError, TypeError):
                continue
            if str(component.get('kind', '')).lower() == 'os package':
                files.extend(component_files(component))
        return files

    def install_local_builder_packages(self):
        LocalBuilderPackageDialog(self, self.app, initial_files=self._selected_local_package_files(),
                                  on_complete=self.refresh, target='builder')

    def install_local_runtime_packages(self):
        LocalBuilderPackageDialog(self, self.app, initial_files=self._selected_local_package_files(),
                                  on_complete=self.refresh, target='runtime')

    def _blank_component(self):
        return {
            "enabled": True,
            "name": "",
            "version": "",
            "kind": "Binary",
            "source": "",
            "destination": "",
            "depends": "",
            "build_system": "",
            "build_command": "",
            "build_deps": "",
            "runtime_packages": "",
            "output_rel": "",
            "validation": "",
            "add_to_path": False,
            "base_match": "",
            "local_package_files": [],
        }

    def _normalized_component(self, component):
        result = self._blank_component()
        if isinstance(component, dict):
            for key in result:
                if key in component:
                    result[key] = component[key]
        result["local_package_files"] = component_files(result) if result.get("kind", "").lower() == "os package" else []
        result["enabled"] = bool(result.get("enabled", True))
        result["add_to_path"] = bool(result.get("add_to_path", False))
        for key in (
            "name",
            "version",
            "kind",
            "source",
            "destination",
            "depends",
            "build_system",
            "build_command",
            "build_deps",
            "runtime_packages",
            "output_rel",
            "validation",
            "base_match",
        ):
            result[key] = str(result.get(key, "") or "").strip()
        if result["kind"].lower() == "os package":
            canonical, version = component_package_identity(result)
            if canonical and canonical != result["name"]:
                result["name"] = canonical
            if version and not result["version"]:
                result["version"] = version
        if result["kind"].lower() == "binary" and result["source"] and (result["source"].lower().endswith(".jar") or (Path(result["source"]).is_file() and inspect_component_file(result["source"])["format"] == "JAVA_ARCHIVE")):
            result["kind"] = "JAR/Application"
            if result["destination"].rstrip("/") == "/usr/local/bin":
                result["destination"] = suggested_destination("JAR/Application", result["name"])
            if not result["version"] and Path(result["source"]).is_file():
                result["version"] = inspect_jar(result["source"])["version"]
        return result

    def _touch_shared_state(self, key="components"):
        touch = getattr(self.app.state, "touch", None)
        if callable(touch):
            touch(key)

    def _norm_name(self, value):
        return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())

    def _base_inventory_entries(self):
        inventory = self.app.state.get("base_inventory", {})
        if not isinstance(inventory, dict):
            return []

        entries = []
        for item in inventory.get("executables", []) if isinstance(inventory.get("executables", []), list) else []:
            entries.append(("Executable", item.get("name", ""), item.get("version", ""), item.get("path", "")))

        packages = inventory.get("packages", {}) if isinstance(inventory.get("packages", {}), dict) else {}
        for group, label in (("os", "OS package"), ("python", "Python package"), ("r", "R package")):
            values = packages.get(group, []) if isinstance(packages.get(group, []), list) else []
            for item in values:
                entries.append((label, item.get("name", ""), item.get("version", ""), ""))

        jars = packages.get("jars", []) if isinstance(packages.get("jars", []), list) else []
        for jar in jars:
            p = Path(str(jar))
            entries.append(("JAR", p.stem, "", str(jar)))
            entries.append(("JAR", p.name, "", str(jar)))

        return entries

    def manual_installation(self):
        category, name, version, path = 'Java', 'Java runtime', '', ''
        selection = self.tree.selection()
        if selection:
            iid = selection[0]
            if iid.startswith('image:'):
                item = self._visible_image_items.get(iid) or {}
                name = str(item.get('name') or name)
                version = str(item.get('version') or '')
                path = str(item.get('path') or '') if str(item.get('path') or '').startswith('/') else ''
                kind = str(item.get('kind') or '').lower()
                if 'java' in name.lower():
                    category, name = 'Java', 'Java runtime'
                elif kind == 'os package':
                    category = 'OS package'
                elif kind in ('binary', 'executable', 'native program'):
                    category = 'Native program'
                else:
                    category = 'Custom'
            elif iid.isdigit():
                component = self.app.state['components'][int(iid)]
                name = str(component.get('name') or name)
                version = str(component.get('version') or '')
                kind = str(component.get('kind') or '').lower()
                category = 'OS package' if kind == 'os package' else 'Java' if 'java' in name.lower() else 'Native program' if kind == 'binary' else 'Custom'
                if category == 'Java':
                    name = 'Java runtime'
        ManualOverrideDialog(self, self.app.state, category, name, version, path, on_save=self.refresh)

    def _find_base_match(self, component_or_name):
        if isinstance(component_or_name, dict):
            query = component_or_name.get("base_match") or component_or_name.get("name", "")
        else:
            query = str(component_or_name or "")

        if isinstance(component_or_name, dict) and str(component_or_name.get('kind', '')).lower() == 'os package':
            match = installed_package_record(component_or_name, self.app.state.get('base_inventory'))
            if match:
                return {'type': 'OS package', 'name': match.get('name', ''), 'version': match.get('version', ''), 'path': ''}
        norm = self._norm_name(query)
        if not norm:
            return None

        exact = []
        for entry in self._base_inventory_entries():
            if self._norm_name(entry[1]) == norm:
                exact.append(entry)

        if not exact:
            return None

        exact.sort(key=lambda x: (0 if x[2] else 1, x[0], x[1]))
        kind, name, version, path = exact[0]
        return {
            "type": kind,
            "name": name,
            "version": version,
            "path": path,
        }

    def _inventory_settings(self):
        if self.show_builder_inventory.get() and self.inventory_category.get() == 'Applications':
            self.inventory_category.set('All software')
        self.app.state.update({'inventory_category': self.inventory_category.get(),
                               'inventory_origin': self.inventory_origin.get(),
                               'show_builder_inventory': bool(self.show_builder_inventory.get())})
        self.refresh()

    @staticmethod
    def _inventory_items(inventory, scope):
        if not isinstance(inventory, dict):
            return []
        items = []
        for item in inventory.get('executables', []) or []:
            if isinstance(item, dict):
                items.append({'name': item.get('name', ''), 'version': item.get('version', ''),
                              'path': item.get('path', ''), 'package': item.get('package', ''),
                              'group': 'Executables', 'scope': scope})
        packages = inventory.get('packages') or {}
        if not isinstance(packages, dict):
            packages = {}
        for key, group in (('os', 'OS packages'), ('python', 'Python packages'), ('r', 'R packages'), ('perl', 'Perl packages')):
            for item in packages.get(key, []) or []:
                if isinstance(item, dict):
                    items.append({'name': item.get('name', ''), 'version': item.get('version', ''),
                                  'path': item.get('path', ''), 'group': group, 'scope': scope})
        for value in packages.get('jars', []) or []:
            path = str(value.get('path', '') if isinstance(value, dict) else value)
            items.append({'name': posixpath.basename(path), 'version': '', 'path': path,
                          'group': 'All JARs', 'scope': scope})
        return items

    def _show_inventory(self, image_snapshot, existing):
        selected = self.inventory_category.get()
        source = self.inventory_origin.get()
        output = []
        archive = str(self.app.state.get('runtime_base_archive') or '')
        provenance = (image_snapshot or {}).get('provenance') or {}
        for item in (image_snapshot or {}).get('components', []):
            origin = item.get('origin', 'UNKNOWN')
            output.append({'name': item.get('name', ''), 'version': item.get('version', ''), 'path': item.get('path', ''),
                           'origin': origin, 'revision': item.get('revision'), 'scope': 'RUNTIME IMAGE',
                           'group': 'Applications', 'kind': item.get('kind', 'Application')})
        versions = set((image_snapshot or {}).get('installed_java_versions') or [])
        if (image_snapshot or {}).get('installed_java') is not None:
            versions.add((image_snapshot or {}).get('installed_java'))
        versions.update(installed_java_versions(self.app.state.get('base_inventory')))
        for java in sorted(versions):
            output.append({'name': 'Java runtime', 'version': str(java), 'path': 'java:' + str(java), 'origin': 'INHERITED / UNKNOWN',
                           'revision': None, 'scope': 'RUNTIME IMAGE', 'group': 'Language runtimes', 'kind': 'Runtime'})
        for record in records_for_image(self.app.state):
            output.append({'name': record.get('name', ''), 'version': record.get('version', ''),
                           'path': record.get('executable', ''), 'origin': 'USER CONFIRMED',
                           'revision': None, 'scope': 'RUNTIME IMAGE', 'group': 'Language runtimes' if
                           record.get('category') in ('Java', 'Python', 'R', 'Perl') else 'Applications',
                           'kind': 'Manual: ' + record.get('category', 'Custom')})
        pending = (image_snapshot or {}).get('pending') or {}
        package_status = (image_snapshot or {}).get('installation_status') or {}
        inventory_names = {str(x.get('name', '')).lower() for x in ((self.app.state.get('base_inventory') or {}).get('packages') or {}).get('os', []) if isinstance(x, dict)}
        for name in pending.get('os_packages', []) or []:
            identity, _ = component_package_identity({'kind': 'OS package', 'name': name})
            installed = identity.lower() in inventory_names or package_status.get(name) == 'INSTALLED' or package_status.get(identity) == 'INSTALLED' 
            if installed:
                continue
            output.append({'name': name, 'version': '', 'path': '', 'origin': 'NOT INSTALLED',
                           'revision': None, 'scope': 'NOT INSTALLED', 'group': 'Not installed', 'kind': 'OS package'})
        if selected != 'Applications':
            inventory = self.app.state.get('base_inventory') or {}
            requests = (provenance.get('os_package_requests') or [])
            requested = {str(x.get('name', '')).lower(): x for x in requests if isinstance(x, dict)}
            for item in self._inventory_items(inventory, 'RUNTIME IMAGE'):
                entry = dict(item, origin='INHERITED / UNKNOWN', revision=None, kind=item['group'])
                known = requested.get(str(item.get('name', '')).lower()) if item['group'] == 'OS packages' else None
                if known:
                    revision = known.get('revision')
                    if known.get('was_present_before') is False and known.get('status') in ('INSTALLATION_REQUESTED', 'INSTALLATION_ATTEMPTED'):
                        entry['origin'] = 'ADDED'
                        entry['revision'] = revision
                    else:
                        entry['origin'] = 'INSTALL REQUESTED / ORIGIN UNKNOWN'
                        entry['revision'] = revision
                output.append(entry)
            if self.show_builder_inventory.get():
                builder = self.app.state.get('builder_inventory') or {}
                output.extend(dict(item, origin='BUILDER ONLY', revision=None, kind=item['group'])
                              for item in self._inventory_items(builder, 'BUILDER ONLY'))
        show = []
        seen = set()
        for item in output:
            if selected == 'Applications' and item['group'] not in ('Applications', 'Language runtimes', 'Not installed'):
                continue
            if selected == 'OS packages' and item['group'] not in ('OS packages', 'Not installed'):
                continue
            if selected in ('Python packages', 'R packages', 'Perl packages') and item['group'] != selected:
                continue
            if selected == 'Executables' and item['group'] not in ('Executables', 'Applications'):
                continue
            if selected == 'All JARs' and item['group'] != 'All JARs' and not (item['group']=='Applications' and str(item.get('kind','')).lower()=='jar/application'):
                continue
            if selected == 'Language runtimes' and item['group'] not in ('Language runtimes', 'Not installed'):
                continue
            origin = item['origin']
            if source == 'Added' and origin != 'ADDED':
                continue
            if source == 'Compiled using builder' and origin != 'BUILDER':
                continue
            if source == 'Inherited / unknown' and not (origin in ('UNKNOWN', 'INHERITED / UNKNOWN', 'BUILDER ONLY') or origin.startswith('UNKNOWN')):
                continue
            if source == 'Not installed' and origin != 'NOT INSTALLED':
                continue
            key = (item['scope'], item['group'], item['name'], item['path'])
            if key in seen:
                continue
            seen.add(key)
            show.append(item)
        self._visible_image_items = {}
        selected_removals = normalize_removals(self.app.state.get('image_removals', []))
        for i, item in enumerate(show):
            origin = item['origin']
            entry_kind = self._removal_kind(item)
            marked = any(removal_id(x['kind'], x['name'], x['path']) == removal_id(entry_kind, item['name'], item['path']) for x in selected_removals)
            if item.get('package'):
                marked = marked or any(x['kind'] == 'os_package' and x['name'].lower() == str(item['package']).lower() for x in selected_removals)
            if self._is_java_runtime(item):
                runtime_packages = java_runtime_packages(item.get('version'), self.app.state.get('base_inventory'))
                marked = bool(runtime_packages) and all(any(x['kind'] == 'os_package' and x['name'].lower() == package.lower()
                                                           for x in selected_removals) for package in runtime_packages)
            forced = any(x['kind'] == 'os_package' and x.get('force') and
                         (x['name'].lower() == str(item.get('package', '')).lower() or
                          x['name'].lower() == str(item.get('name', '')).lower() or
                          (self._is_java_runtime(item) and x['name'] in java_runtime_packages(item.get('version'), self.app.state.get('base_inventory'))))
                         for x in selected_removals)
            tag = 'remove_pending' if marked else 'user_confirmed' if origin == 'USER CONFIRMED' else 'deferred' if origin == 'NOT INSTALLED' else 'builder_only' if item['scope'] == 'BUILDER ONLY' else 'image_present'
            self._visible_image_items['image:' + str(i)] = dict(item)
            self.tree.insert('', 'end', iid='image:' + str(i), values=(
                '—' if origin == 'NOT INSTALLED' else 'YES', item['name'], item['version'],
                'Present in image' if item['scope'] == 'RUNTIME IMAGE' else item['kind'], 'No',
                ('REMOVE IN NEXT IMAGE (FORCE)' if forced else 'REMOVE IN NEXT IMAGE') if marked else 'USER CONFIRMED' if origin == 'USER CONFIRMED' else 'NOT INSTALLED' if origin == 'NOT INSTALLED' else 'AVAILABLE IN BUILDER' if item['scope'] == 'BUILDER ONLY' else 'ALREADY PRESENT',
                '', item['path'], item['path'], '', '', '',
                'REMOVE REQUESTED' if marked else 'USER CONFIRMED' if origin == 'USER CONFIRMED' else 'NOT INSTALLED' if origin == 'NOT INSTALLED' else 'BUILDER ONLY' if item['scope'] == 'BUILDER ONLY' else 'PRESENT',
                item['version'], origin, str(item['revision'] or ''), item['scope']), tags=(tag,))
        self.image_notice.set(str(len(show)) + ' inventory entries shown; builder-only software is not copied into the final image.')

    def toggle_image_components(self):
        self.app.state['show_image_components'] = bool(self.show_image_components.get())
        self.refresh()

    def _image_entries(self):
        archive = str(self.app.state.get('runtime_base_archive', '') or '').strip()
        if not archive:
            return []
        try:
            return inspect_image_components(archive)['components']
        except Exception as exc:
            self.image_notice.set('Image inventory unavailable: ' + str(exc))
            return []

    def refresh_base_summary(self):
        tag = self.app.state.get("base_image", "")
        archive = self.app.state.get("runtime_base_archive", "")
        system = self.app.state.get("base_system", {}) if isinstance(self.app.state.get("base_system", {}), dict) else {}
        inventory = self.app.state.get("base_inventory", {}) if isinstance(self.app.state.get("base_inventory", {}), dict) else {}
        packages = inventory.get("packages", {}) if isinstance(inventory.get("packages", {}), dict) else {}
        executables = inventory.get("executables", []) if isinstance(inventory.get("executables", []), list) else []
        os_packages = packages.get("os", []) if isinstance(packages.get("os", []), list) else []
        jars = packages.get("jars", []) if isinstance(packages.get("jars", []), list) else []

        if not tag:
            self.base_summary.set("No runtime base has been selected in Tab 1.")
            return

        self.base_summary.set(
            f"Tag: {tag}   |   Archive: {archive or '<not recorded>'}\n"
            f"OS: {system.get('os','')}   |   Architecture: {system.get('architecture','')}   |   "
            f"Executables: {len(executables)}   |   OS packages: {len(os_packages)}   |   JARs: {len(jars)}"
        )

    def refresh_from_project_state(self):
        self.refresh()

    def refresh(self):
        self.refresh_base_summary()
        self.tree.delete(*self.tree.get_children())

        components = self.app.state.get("components", [])
        normalized = []
        for component in components:
            updated = self._normalized_component(component)
            if isinstance(component, dict):
                if component != updated:
                    component.clear()
                    component.update(updated)
                normalized.append(component)
            else:
                normalized.append(updated)
        if normalized != components:
            self.app.state["components"] = normalized

        counts = {"COMPILED": 0, "NOT COMPILED": 0, "OUTDATED": 0, "FAILED": 0}
        for index, component in enumerate(normalized):
            compilation = compilation_status(self.app.state, component)
            if compilation["required"] == "Yes":
                counts[compilation["status"]] = counts.get(compilation["status"], 0) + 1
            match = self._find_base_match(component)
            base_status = "FOUND" if match else ("UNKNOWN" if not self.app.state.get("base_inventory") else "NOT FOUND")
            base_version = match.get("version", "") if match else ""
            if str(component.get('kind', '')).lower() == 'os package':
                if match:
                    display_status = 'INSTALLED'
                else:
                    confirmations = records_for_image(self.app.state)
                    manual_names = {str(x.get('name', '')).lower() for x in confirmations if x.get('category') == 'OS package'}
                    display_status = 'USER CONFIRMED' if component.get('name', '').lower() in manual_names else 'NOT INSTALLED'
            else:
                display_status = compilation['status']
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    "YES" if component["enabled"] else "NO",
                    component["name"],
                    component["version"],
                    component["kind"],
                    compilation["required"],
                    display_status,
                    compilation["version"],
                    component["source"],
                    component["destination"],
                    component["depends"],
                    component["build_deps"],
                    component["runtime_packages"],
                    base_status,
                    base_version,
                    "PROJECT", "", "NEW COMPONENT",
                ),
                tags=({"COMPILED": "compiled", "OUTDATED": "outdated", "FAILED": "failed", "NOT COMPILED": "notcompiled"}.get(compilation["status"], ""),),
            )

        if self.show_image_components.get():
            try:
                archive = str(self.app.state.get('runtime_base_archive') or '')
                snapshot = inspect_image_components(archive) if archive else {}
                self._show_inventory(snapshot, normalized)
            except Exception as exc:
                self.image_notice.set('Runtime inventory could not be read: ' + str(exc))
        else:
            self.image_notice.set('Enable image inventory to see installed software and unmet installation requests.')

        self.compilation_summary.set(
            "Sources: " + str(sum(counts.values())) + "    |    Compiled: " + str(counts["COMPILED"]) +
            "    |    Not compiled: " + str(counts["NOT COMPILED"]) +
            "    |    Outdated: " + str(counts["OUTDATED"]) +
            "    |    Failed: " + str(counts["FAILED"])
        )
        self._touch_shared_state("components")

    def _selected_indices(self):
        indices = []
        for item in self.tree.selection():
            try:
                indices.append(int(item))
            except ValueError:
                pass
        return sorted(set(indices))

    def edit_selected(self):
        indices = self._selected_indices()
        if not indices:
            messagebox.showwarning("Component", "Select one component to edit.")
            return
        if len(indices) > 1:
            messagebox.showwarning("Component", "Edit supports one component at a time.")
            return
        if not indices:
            messagebox.showinfo('Present in image', 'This application is already inside the selected image. Its entry is read-only. Add a new component to update it.')
            return
        self.component_dialog(indices[0])

    def toggle_selected(self):
        indices = self._selected_indices()
        if not indices:
            messagebox.showinfo('Present in image', 'Existing image components are read-only. Use Add component to install or replace software.')
            return

        components = self.app.state["components"]
        for index in indices:
            components[index]["enabled"] = not bool(components[index].get("enabled", True))
        self.refresh()

    @staticmethod
    def _removal_kind(item):
        if item.get('origin') == 'NOT INSTALLED':
            return 'deferred'
        if item.get('group') == 'OS packages':
            return 'os_package'
        for group, kind in (('Python packages', 'python_package'), ('R packages', 'r_package'), ('Perl packages', 'perl_package')):
            if item.get('group') == group:
                return kind
        return 'file'

    @staticmethod
    def _is_java_runtime(item):
        return item.get('name') == 'Java runtime' and item.get('group') == 'Language runtimes'

    def review_dependencies(self):
        DependencyResolutionDialog(self, self.app)

    def _manual_removal_target(self, item):
        value = simpledialog.askstring('Identify installed component',
            'The image inventory does not identify how this component was installed:\n' +
            str(item.get('name', '')) + '  ' + str(item.get('version', '')) + '\n\n'
            'Enter its exact Linux OS package name, absolute file path, or a directory path ending in /.\n'
            'The next build will verify that the selected target can be removed.', parent=self)
        value = str(value or '').strip()
        if not value:
            return None
        if value.endswith('/') and safe_directory_path(value):
            return {'kind': 'directory', 'name': item['name'], 'path': value.rstrip('/')}
        if safe_file_path(value):
            return {'kind': 'file', 'name': item['name'], 'path': value}
        if safe_package_name(value):
            return {'kind': 'os_package', 'name': value, 'path': ''}
        messagebox.showwarning('Invalid removal target', 'Enter an exact installed Linux package name or absolute file path.', parent=self)
        return None

    def remove_selected(self):
        indices = self._selected_indices()
        selections = [self._visible_image_items[x] for x in self.tree.selection() if x in self._visible_image_items]
        if not indices and not selections:
            messagebox.showwarning('Remove', 'Select a registered component or a component from the opened image.', parent=self)
            return
        current = normalize_removals(self.app.state.get('image_removals', []))
        planned = []
        refused = []
        for item in selections:
            kind = self._removal_kind(item)
            if item.get('scope') == 'BUILDER ONLY':
                refused.append(item['name'] + ': belongs to the builder, not the runtime')
                continue
            if self._is_java_runtime(item):
                packages = java_runtime_packages(item.get('version'), self.app.state.get('base_inventory'))
                if not packages:
                    manual = self._manual_removal_target(item)
                    if manual:
                        planned.append(manual)
                    continue
                planned.extend({'kind': 'os_package', 'name': name, 'path': ''} for name in packages)
                continue
            if item.get('group') == 'Executables' and str(item.get('package', '')) and safe_package_name(item.get('package', '')):
                owner = item['package']
                decision = messagebox.askyesnocancel('Executable installed by OS package',
                    item['name'] + ' is owned by OS package ' + owner + '.\n\n'
                    'Yes: uninstall the entire OS package.\nNo: remove only this executable file.\nCancel: leave it unchanged.', parent=self)
                if decision is None:
                    continue
                if decision:
                    planned.append({'kind': 'os_package', 'name': owner, 'path': ''})
                    continue
            if kind == 'file' and not safe_file_path(item.get('path', '')):
                manual = self._manual_removal_target(item)
                if manual:
                    planned.append(manual)
                continue
            if kind == 'os_package' and not safe_package_name(item['name']):
                refused.append(item['name'] + ': invalid package identifier')
                continue
            planned.append({'kind': kind, 'name': item['name'], 'path': item.get('path', '')})
        planned = list({removal_id(row['kind'], row['name'], row['path']): row for row in planned}.values())
        added = []
        canceled = []
        for row in planned:
            key = removal_id(row['kind'], row['name'], row['path'])
            old = next((x for x in current if removal_id(x['kind'], x['name'], x['path']) == key), None)
            if old:
                canceled.append(row)
            else:
                added.append(row)
        package_removals = [row for row in added if row['kind'] == 'os_package']
        if package_removals:
            force = messagebox.askyesnocancel('OS package dependency handling',
                'Selected package(s): ' + ', '.join(row['name'] for row in package_removals) + '\n\n'
                'YES — force uninstall even when the package manager reports dependent packages. '
                'The rebuilt image may be broken; review and explicitly replace missing dependencies.\n\n'
                'NO — uninstall only if package-manager dependency checks pass.\n\n'
                'CANCEL — do not change anything.', parent=self)
            if force is None:
                return
            for row in package_removals:
                row['force'] = bool(force)
        detail = []
        if indices:
            detail.append('Remove project registrations: ' + ', '.join(self.app.state['components'][i]['name'] for i in indices))
        if added:
            detail.append('Schedule for next image: ' + ', '.join(x['name'] + (' [FORCE]' if x.get('force') else '') for x in added))
        if canceled:
            detail.append('Cancel previously scheduled removals: ' + ', '.join(x['name'] for x in canceled))
        if refused:
            detail.append('Not allowed: ' + '; '.join(refused))
        protected = [x['name'] for x in added if x['kind'] == 'os_package' and protected_package(x['name'])]
        if protected:
            detail.append('WARNING: These foundational OS packages can make the image unbootable: ' + ', '.join(protected))
        if not (indices or added or canceled):
            messagebox.showwarning('Remove', '\n'.join(detail), parent=self)
            return
        detail.append('The original image will not be modified. A removal from a later Docker layer does not necessarily reduce the total image size; use Compact Built Image afterward.')
        if added or canceled or indices:
            preview_state = dict(self.app.state)
            canceled_ids = {removal_id(x['kind'], x['name'], x['path']) for x in canceled}
            preview_state['image_removals'] = normalize_removals([x for x in current if removal_id(x['kind'], x['name'], x['path']) not in canceled_ids] + added)
            preview_state['components'] = [x for i, x in enumerate(self.app.state['components']) if i not in indices]
            try:
                archive = str(self.app.state.get('runtime_base_archive') or '')
                snapshot = inspect_image_components(archive) if archive else {}
                impacts = dependency_impact(preview_state, snapshot)
                unresolved = [row for row in impacts if row['status'] in ('MISSING', 'UNVERIFIED', 'UNRESOLVED', 'RECHECK', 'INCOMPATIBLE')]
                if unresolved:
                    detail.append('Projected missing or unverified requirements (' + str(len(unresolved)) + '):\n' +
                                  '\n'.join('  ' + row['owner'] + ' needs ' + row['requirement'] + ': ' + row['status'] for row in unresolved[:12]) +
                                  ('\n  ...' if len(unresolved) > 12 else '') +
                                  '\nUse Review removal dependencies / substitutes to assign a different provider.')
            except Exception as exc:
                detail.append('Dependency impact will require another check: ' + str(exc))
        if not messagebox.askyesno('Confirm image revision changes', '\n\n'.join(detail), parent=self):
            return
        for index in sorted(indices, reverse=True):
            del self.app.state['components'][index]
        canceled_ids = {removal_id(x['kind'], x['name'], x['path']) for x in canceled}
        current = [x for x in current if removal_id(x['kind'], x['name'], x['path']) not in canceled_ids]
        current.extend(added)
        self.app.state['image_removals'] = normalize_removals(current)
        self.refresh()

    @staticmethod
    def _name_from_source_path(source_path, kind="Binary"):

        raw_path = str(source_path or "").strip().strip('"').strip("'")
        if not raw_path:
            return ""
        
        last_part = ntpath.basename(raw_path.replace("\\", "/").rstrip("/"))
        if not last_part or last_part in (".", ".."):
            return ""
        kind = str(kind or "").lower().strip()
        if kind == 'source' and is_source_archive(raw_path):
            return archive_stem(raw_path)
        path = Path(raw_path)
        is_folder = kind in ("folder", "source") and not path.is_file()
        if path.is_dir():
            is_folder = True
        if is_folder:
            return last_part

        root, extension = ntpath.splitext(last_part)
        
        known_file_extensions = {
            ".exe", ".bin", ".elf", ".jar", ".py", ".sh", ".bat", ".cmd",
            ".so", ".dll", ".dylib", ".c", ".cc", ".cpp", ".h", ".hpp",
            ".rs", ".java", ".go", ".r", ".zip", ".tar", ".gz", ".xz",
            ".bz2", ".txt", ".json", ".yaml", ".yml", ".csv", ".tsv",
        }
        if root and (extension.lower() in known_file_extensions or path.is_file()):
            return root
        return last_part

    def component_dialog(self, index):
        existing = self._blank_component() if index is None else self._normalized_component(
            self.app.state["components"][index]
        )

        win = tk.Toplevel(self)
        win.title("Component — Add / Edit")
        win.geometry("1100x820")
        win.minsize(850, 620)
        win.configure(bg="#E8F8F5")
        win.transient(self.winfo_toplevel())

        top = tk.Frame(win, bg="#117864", padx=12, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="COMPONENT SETTINGS", font=("Segoe UI", 14, "bold"),
                 fg="white", bg="#117864").pack(anchor="w")

        body_holder = tk.Frame(win, bg="#E8F8F5")
        body_holder.pack(fill="both", expand=True)
        canvas = tk.Canvas(body_holder, bg="#E8F8F5", highlightthickness=0)
        scrollbar = ttk.Scrollbar(body_holder, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        form = tk.Frame(canvas, bg="#E8F8F5")
        canvas_window = canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(canvas_window, width=event.width))

        if str(existing.get("source", "")).lower().endswith(".jar") and str(existing.get("kind", "")).lower() == "binary":
            existing["kind"] = "JAR/Application"
            if existing.get("destination", "").rstrip("/") == "/usr/local/bin":
                existing["destination"] = suggested_destination("JAR/Application", existing.get("name", ""))
        fields = {key: tk.StringVar(value=str(existing.get(key, "") or "")) for key in (
            "name", "version", "source", "destination", "depends",
            "runtime_packages", "validation",
        )}
        kind_var = tk.StringVar(value=existing.get("kind", "Binary"))
        flag_var = tk.StringVar(value="Auto")
        status_var = tk.StringVar(value="")
        enabled_var = tk.BooleanVar(value=bool(existing.get("enabled", True)))
        path_var = tk.BooleanVar(value=bool(existing.get("add_to_path", False)))
        advanced_var = tk.BooleanVar(value=bool(existing.get("runtime_packages") or existing.get("depends")))

        def section(text):
            label = tk.Label(form, text=text, bg="#D5F5E3", fg="#0B5345", anchor="w",
                             font=("Segoe UI", 10, "bold"), padx=12, pady=6)
            label.pack(fill="x", padx=12, pady=(10, 4))
            return label

        def row_entry(parent, label, key=None, *, widget="entry", presets=None, extra=None):
            row = tk.Frame(parent, bg="#E8F8F5")
            row.pack(fill="x", padx=14, pady=4)
            tk.Label(row, text=label, bg="#E8F8F5", anchor="w", width=31).pack(side="left")
            var = fields[key] if key else None
            if widget == "combo":
                control = ttk.Combobox(row, textvariable=var, values=presets or (), state="normal")
            else:
                control = tk.Entry(row, textvariable=var)
            control.pack(side="left", fill="x", expand=True, padx=(4, 6))
            if extra is not None:
                extra(row)
            return row, control

        section("Component identity")

        def source_basename():
            return self._name_from_source_path(fields["source"].get(), kind_var.get())

        previous_autoname = {"name": source_basename() if fields["name"].get() == source_basename() else ""}
        previous_dest = {"value": suggested_destination(kind_var.get(), fields["name"].get())}

        def adopt_name():
            suggestion = source_basename()
            if suggestion:
                fields["name"].set(suggestion)
                previous_autoname["name"] = suggestion

        name_button = {}
        name_label = tk.StringVar(value="Component name:")
        def add_name_button(parent):
            name_button["button"] = tk.Button(parent, text="Use file/folder name", command=adopt_name, bg="#B7E4D0")
            name_button["button"].pack(side="left")
        name_row, name_combo = row_entry(form, "Component name:", "name", widget="combo", extra=add_name_button)
        for child in name_row.winfo_children():
            if isinstance(child, tk.Label):
                child.configure(textvariable=name_label)
                break
        os_package_hint = tk.Label(form, text="Only actual installed packages and local package files are listed. To add unavailable software, download its .rpm, .deb, or .apk file yourself and browse to it. All local-package installations run offline. Additional dependency archives can be selected together.", bg="#E8F8F5", fg="#21618C", wraplength=1000, justify="left", anchor="w")
        os_package_hint.pack(fill="x", padx=290, after=name_row)
        os_package_hint.pack_forget()

        local_files = {'paths': component_files(existing)}
        local_catalog = {'choices': {}}
        package_choice = tk.StringVar()
        local_package_notice = tk.StringVar(value='')
        local_package_row = tk.Frame(form, bg='#E8F8F5')
        package_catalog_row = tk.Frame(form, bg='#E8F8F5')
        tk.Label(package_catalog_row, text='Actually available packages:', width=31, anchor='w', bg='#E8F8F5').pack(side='left')
        package_catalog_combo = ttk.Combobox(package_catalog_row, textvariable=package_choice, state='readonly')
        package_catalog_combo.pack(side='left', fill='x', expand=True, padx=(4, 8))
        package_catalog_row.pack_forget()
        tk.Label(local_package_row, text='Local package archives:', width=31, anchor='w', bg='#E8F8F5').pack(side='left')
        def reload_catalog():
            family = identify_runtime_family(self.app.state)
            local_catalog['choices'] = package_catalog(self.app.state, family)
            for file in local_files['paths']:
                path = Path(file)
                if path.is_file() and package_archive_type(path):
                    name, version = package_identity(path)
                    label = 'LOCAL FILE  |  ' + name + '  |  ' + str(path)
                    local_catalog['choices'][label] = {'name': name, 'version': version, 'source': str(path), 'files': [str(path)], 'status': 'LOCAL FILE'}
            name_combo.configure(values=tuple(sorted({entry['name'] for entry in local_catalog['choices'].values()}, key=str.lower)))
            package_catalog_combo.configure(values=tuple(sorted(local_catalog['choices'])))
            count_installed = sum(x['status'] == 'INSTALLED' for x in local_catalog['choices'].values())
            count_files = sum(bool(x['files']) for x in local_catalog['choices'].values())
            local_package_notice.set(f'{count_installed} installed packages; {count_files} local package files. Select an installed package or browse to a package archive.')
        def choose_local_packages():
            family = identify_runtime_family(self.app.state)
            names = filedialog.askopenfilenames(parent=win, title='Choose locally downloaded OS packages and their dependencies', filetypes=[('Linux package archives', '*.rpm *.deb *.apk'), ('All files', '*.*')])
            if not names:
                return
            wrong = [path for path in names if not compatible_package_file(path, family)]
            if wrong:
                messagebox.showerror('Package format', 'Runtime package manager: ' + family + '\nSelect compatible package files only.\n' + '\n'.join(wrong[:8]), parent=win)
                return
            local_files['paths'] = list(dict.fromkeys(str(path) for path in names))
            fields['source'].set(str(names[0]))
            package, version = package_identity(names[0])
            fields['name'].set(package)
            reload_catalog()
            status_var.set(str(len(names)) + ' local package archive(s) selected; these will be installed offline during the build.')
        def choose_local_folder():
            folder = filedialog.askdirectory(parent=win, title='Select a folder containing local Linux packages')
            if not folder:
                return
            folders = list(self.app.state.get('local_package_folders') or [])
            if folder not in folders:
                folders.append(folder)
                self.app.state['local_package_folders'] = folders
            reload_catalog()
            status_var.set('Local package folder indexed: ' + folder)
        tk.Button(local_package_row, text='Browse package file(s)', command=choose_local_packages, bg='#B7E4D0').pack(side='left', padx=3)
        tk.Button(local_package_row, text='Index local folder', command=choose_local_folder).pack(side='left', padx=3)
        tk.Label(local_package_row, textvariable=local_package_notice, bg='#E8F8F5', fg='#21618C', wraplength=480, justify='left').pack(side='left', padx=8)
        local_package_row.pack_forget()
        def package_name_selected(*_):
            if kind_var.get().strip().lower() != 'os package':
                return
            name = fields['name'].get().strip()
            options = [choice for choice in local_catalog['choices'].values() if choice['name'] == name]
            if any(x['status'] == 'INSTALLED' for x in options):
                fields['source'].set('')
                local_files['paths'] = []
                status_var.set(name + ' is INSTALLED in the selected runtime inventory. No download or reinstallation necessary.')
            elif options:
                selected = next((x for x in options if x['status'] == 'LOCAL FILE'), options[0])
                fields['source'].set(selected['source'])
                local_files['paths'] = list(selected['files'])
                status_var.set(name + ': local package file selected. Installation runs offline.')
        name_combo.bind('<<ComboboxSelected>>', package_name_selected)
        def choose_catalog_item(*_):
            selected = local_catalog['choices'].get(package_choice.get())
            if selected is None:
                return
            fields['name'].set(selected['name'])
            fields['source'].set(selected['source'])
            local_files['paths'] = list(selected['files'])
            if selected['version'] and selected['status'] == 'INSTALLED':
                fields['version'].set(selected['version'])
            if selected['status'] == 'INSTALLED':
                status_var.set(selected['name'] + ': already INSTALLED in the runtime; no installation needed.')
            elif selected['status'] == 'LOCAL FILE':
                status_var.set(selected['name'] + ': local package available for offline installation. Include any required dependency files.')
            else:
                status_var.set('This package file is not compatible with the selected Linux distribution.')
        package_catalog_combo.bind('<<ComboboxSelected>>', choose_catalog_item)

        def create_probe_button(parent):
            probe_button = tk.Button(parent, text="Check version", bg="#2471A3", fg="white")
            probe_button.pack(side="left")
            probe_button_ref["button"] = probe_button

        probe_button_ref = {}
        row_entry(form, "Version (verified only):", "version", extra=create_probe_button)
        version_row = tk.Frame(form, bg="#E8F8F5")
        tk.Label(version_row, text="Version command:", bg="#E8F8F5", width=31, anchor="w").pack(side="left")
        ttk.Combobox(version_row, textvariable=flag_var,
                     values=("Auto", "--version", "-V", "-v"),
                     state="readonly", width=20).pack(side="left", padx=(4, 8))
        tk.Label(version_row, text="Runs inside Docker, not directly on Windows.",
                 bg="#E8F8F5", fg="#566573").pack(side="left")
        tk.Label(form, textvariable=status_var, anchor="w", bg="#E8F8F5",
                 fg="#21618C", wraplength=950, justify="left").pack(fill="x", padx=14)

        kind_row = tk.Frame(form, bg="#E8F8F5")
        kind_row.pack(fill="x", padx=14, pady=4)
        tk.Label(kind_row, text="Component type:", bg="#E8F8F5", width=31, anchor="w").pack(side="left")
        kinds = ("Source", "Binary", "Script", "OS package", "Base-provided", "JAR/Application", "Folder", "Other")
        ttk.Combobox(kind_row, textvariable=kind_var, values=kinds, state="readonly").pack(
            side="left", fill="x", expand=True, padx=(4, 6))

        def browse_source(parent):
            tk.Button(parent, text="File", command=lambda: self._browse_file(fields["source"])).pack(side="left", padx=2)
            tk.Button(parent, text="Folder", command=lambda: self._browse_folder(fields["source"])).pack(side="left", padx=2)

        source_row, _ = row_entry(form, "Local source / file / folder:", "source", extra=browse_source)
        destination_presets = ("/usr/local/bin/", "/usr/local/sbin/", "/usr/local/lib/", "/opt/", "/usr/local/share/", "/etc/")
        destination_row, destination_combo = row_entry(
            form, "Destination in Docker image:", "destination", widget="combo", presets=destination_presets
        )
        destination_note = tk.Label(form, text="Destination is a Linux directory, not a Windows folder.",
                                    bg="#E8F8F5", fg="#566573", anchor="w")
        destination_note.pack(fill="x", padx=290)
        location_anchor = tk.Frame(form, bg="#E8F8F5", height=1)
        location_anchor.pack(fill="x")

        source_build_note = tk.Label(
            form,
            text=(
                "Select an extracted source folder or a ZIP / TAR / TAR.GZ / TAR.XZ archive directly. "
                "Archives are unpacked inside Docker, never into a Windows source folder. "
                "Configure the build command, output, and required builder tools in Tab 4."
            ),
            bg="#D5F5E3", fg="#0B5345", anchor="w", justify="left",
            wraplength=960, padx=12, pady=8,
        )
        source_build_note.pack(fill="x", padx=12, pady=(10, 3))

        validation_heading = section("Validation inside the final image")
        validation_row, validation_combo = row_entry(
            form, "Validation command:", "validation", widget="combo"
        )
        tk.Label(form, text="Choose a test from the dropdown or enter your own. --self-test is valid only when supported by the program.",
                 bg="#E8F8F5", fg="#566573", wraplength=980, anchor="w").pack(fill="x", padx=14, pady=3)

        advanced_header = tk.Frame(form, bg="#E8F8F5")
        advanced_header.pack(fill="x", padx=14, pady=(12, 3))
        tk.Checkbutton(advanced_header, text="Show optional dependencies and packages",
                       variable=advanced_var, bg="#E8F8F5", activebackground="#E8F8F5",
                       font=("Segoe UI", 10, "bold")).pack(side="left")
        advanced_panel = tk.Frame(form, bg="#E8F8F5", highlightbackground="#B2DFDB", highlightthickness=1)
        depends_row, _ = row_entry(advanced_panel, "Other component dependencies:", "depends")
        runtime_row, _ = row_entry(advanced_panel, "Runtime packages:", "runtime_packages")
        tk.Label(advanced_panel, text="Optional runtime requirements. Build-only packages are managed in Tab 4.",
                 bg="#E8F8F5", fg="#566573", anchor="w").pack(fill="x", padx=14, pady=6)

        check_row = tk.Frame(form, bg="#E8F8F5")
        check_row.pack(fill="x", padx=290, pady=(12, 8))
        tk.Checkbutton(check_row, text="Enabled", variable=enabled_var, bg="#E8F8F5").pack(side="left", padx=(0, 18))
        path_check = tk.Checkbutton(check_row, text="Add destination to PATH", variable=path_var, bg="#E8F8F5")
        path_check.pack(side="left")

        
        def update_auto_name(*_):
            candidate = source_basename()
            current = fields["name"].get().strip()
            if candidate and (not current or current == previous_autoname["name"]):
                fields["name"].set(candidate)
                previous_autoname["name"] = candidate

        def update_destination(*_):
            new = suggested_destination(kind_var.get(), fields["name"].get())
            old = fields["destination"].get().strip()
            if new and (not old or old == previous_dest["value"]):
                fields["destination"].set(new)
            previous_dest["value"] = new

        last_auto_validation = {"value": ""}
        def update_validation_options(*_):
            values = validation_presets(
                kind_var.get(), fields["source"].get(), fields["destination"].get(),
                fields["name"].get(), existing.get("output_rel", "")
            )
            validation_combo.configure(values=values)
            if kind_var.get().strip().lower() == "os package" and values:
                previous = last_auto_validation["value"]
                current = fields["validation"].get().strip()
                if not current or current == previous:
                    fields["validation"].set(values[0])
                    last_auto_validation["value"] = values[0]

        def optional_panel(*_):
            if advanced_var.get():
                advanced_panel.pack(fill="x", padx=14, pady=(0, 4), before=check_row)
            else:
                advanced_panel.pack_forget()

        def update_kind(*_):
            kind = kind_var.get().strip().lower()
            source_path = fields["source"].get().strip()
            if kind == "binary" and source_path and Path(source_path).is_file() and inspect_component_file(source_path)["format"] == "JAVA_ARCHIVE":
                kind_var.set("JAR/Application")
                status_var.set("A JAR cannot be registered as a Linux Binary. JAR/Application selected automatically.")
                return
            if kind == "os package":
                name_label.set("OS package name:")
                reload_catalog()
                name_combo.configure(state='readonly')
                os_package_hint.pack(fill="x", padx=290, pady=(0, 5), after=name_row)
                package_catalog_row.pack(fill='x', padx=14, pady=(2, 5), after=os_package_hint)
                local_package_row.pack(fill='x', padx=14, pady=(2, 5), after=package_catalog_row)
                name_button["button"].pack_forget()
                if not fields["name"].get().strip():
                    status_var.set("Only installed packages and local package files are offered. Download any other package yourself, then browse to it.")
            else:
                name_label.set("Component name:")
                name_combo.configure(values=(), state='normal')
                os_package_hint.pack_forget()
                package_catalog_row.pack_forget()
                local_package_row.pack_forget()
                if not name_button["button"].winfo_manager():
                    name_button["button"].pack(side="left")
            if kind in ("base-provided", "os package"):
                source_row.pack_forget()
                destination_row.pack_forget()
            else:
                source_row.pack(fill="x", padx=14, pady=4, before=location_anchor)
                destination_row.pack(fill="x", padx=14, pady=4, before=location_anchor)
                destination_note.pack(fill="x", padx=290, before=location_anchor)
            if kind in ("base-provided", "os package"):
                destination_note.pack_forget()
            if kind == "source":
                source_build_note.pack(fill="x", padx=12, pady=(10, 3), before=validation_heading)
            else:
                source_build_note.pack_forget()
            if kind in ("binary", "jar/application"):
                probe_button_ref["button"].config(state="normal")
                probe_button_ref["button"].configure(text="Read JAR version" if kind == "jar/application" else "Check binary version")
                version_row.pack(fill="x", padx=14, pady=(2, 5), after=version_row_anchor)
            else:
                probe_button_ref["button"].config(state="disabled")
                version_row.pack_forget()
            if kind in ("source", "binary", "script", "jar/application", "folder", "other"):
                path_check.config(state="normal")
            else:
                path_check.config(state="disabled")
            if kind == "base-provided":
                runtime_row.pack_forget()
            else:
                runtime_row.pack(fill="x", padx=14, pady=4, after=depends_row)
            update_destination()
            update_validation_options()
            optional_panel()

        
        version_row_anchor = tk.Frame(form, bg="#E8F8F5", height=1)
        version_row_anchor.pack(fill="x", before=kind_row)

        def show_probe_report(report):
            lines = []
            for attempt in report.get("attempts", []):
                lines.extend([f"Flag: {attempt['flag']}   Exit code: {attempt['code']}",
                              attempt["output"] or "(no output)", ""])
            if report.get("version"):
                lines.insert(0, f"Reported version: {report['version']}\n")
                if not fields["version"].get().strip():
                    fields["version"].set(report["version"])
                elif fields["version"].get().strip() != report["version"]:
                    lines.insert(1, f"Current version field was not overwritten: {fields['version'].get()}\n")
                status_var.set(f"Verified component version: {report['version']}.")
            else:
                status_var.set("No verified version detected; Version remains unchanged.")
            if report.get("error"):
                lines.insert(0, report["error"] + "\n")
            report_win = tk.Toplevel(win)
            report_win.title("Component version inspection")
            report_win.geometry("850x480")
            report_win.transient(win)
            box = scrolledtext.ScrolledText(report_win, font=("Consolas", 10), wrap="word")
            box.pack(fill="both", expand=True, padx=10, pady=10)
            box.insert("1.0", "\n".join(lines))
            box.configure(state="disabled")
            tk.Button(report_win, text="Close", command=report_win.destroy).pack(pady=(0, 10))
            probe_button_ref["button"].config(state="normal")

        result_queue = queue.Queue()
        checking = {"active": False}

        def check_probe_queue():
            if not win.winfo_exists():
                return
            try:
                report = result_queue.get_nowait()
            except queue.Empty:
                if checking["active"]:
                    win.after(150, check_probe_queue)
                return
            checking["active"] = False
            show_probe_report(report)

        def probe_version():
            file = fields["source"].get().strip()
            if not Path(file).is_file():
                messagebox.showerror("Version check", "Choose an existing component file first.", parent=win)
                return
            if checking["active"]:
                return
            image = str(self.app.state.get("base_image", "") or "")
            kind = kind_var.get()
            probe_button_ref["button"].config(state="disabled")
            checking["active"] = True
            status_var.set("Reading JAR manifest..." if kind.lower() == "jar/application" else f"Checking native Linux binary using {image or '<no image>'}...")

            def worker():
                try:
                    report = probe_binary_version(file, image, flag_var.get(), component_kind=kind)
                except Exception as exc:
                    report = {"version": "", "attempts": [], "error": str(exc)}
                result_queue.put(report)

            threading.Thread(target=worker, daemon=True).start()
            win.after(150, check_probe_queue)

        probe_button_ref["button"].configure(command=probe_version)

        def auto_detect_jar(*_):
            path = fields["source"].get().strip()
            if not path:
                return
            result = inspect_component_file(path) if Path(path).is_file() else {"format": "JAVA_ARCHIVE" if path.lower().endswith(".jar") else "UNKNOWN"}
            if result["format"] == "JAVA_ARCHIVE":
                if kind_var.get() != "JAR/Application":
                    kind_var.set("JAR/Application")
                if Path(path).is_file():
                    info = inspect_jar(path)
                    if info["version"] and not fields["version"].get().strip():
                        fields["version"].set(info["version"])
                    if info["minimum_java"]:
                        status_var.set("JAR detected. Minimum Java: " + info["minimum_java"] + ". A compatible Java runtime is required in the final image.")
            elif Path(path).is_file() and Path(path).suffix.lower() in ('.py', '.r', '.pl', '.sh') and kind_var.get().lower() == 'binary':
                kind_var.set('Script')
                status_var.set('Script detected. Configure its interpreter and dependencies using Language runtimes / Custom setup.')
            elif kind_var.get().lower() == "binary" and Path(path).is_file():
                ok, problem = validate_component_type("Binary", path)
                status_var.set("Linux binary detected (ELF)." if ok else problem)

        fields["source"].trace_add("write", update_auto_name)
        fields["source"].trace_add("write", auto_detect_jar)
        fields["name"].trace_add("write", update_destination)
        fields["name"].trace_add("write", update_validation_options)
        fields["source"].trace_add("write", update_validation_options)
        fields["destination"].trace_add("write", update_validation_options)
        kind_var.trace_add("write", update_kind)
        advanced_var.trace_add("write", optional_panel)

        if not fields["name"].get().strip():
            update_auto_name()
        update_destination()
        update_kind()
        auto_detect_jar()

        footer = tk.Frame(win, bg="#D5F5E3", padx=12, pady=10)
        footer.pack(fill="x", side="bottom")

        def save(open_build_tab=False):
            
            
            component = self._normalized_component(existing)
            for key, var in fields.items():
                component[key] = var.get().strip()
            component["kind"] = kind_var.get().strip()
            component["enabled"] = enabled_var.get()
            component["add_to_path"] = path_var.get() if component["kind"].lower() not in ("base-provided", "os package") else False
            if component["kind"].lower() != "source":
                component["build_system"] = ""
                component["build_command"] = ""
                component["build_deps"] = ""
                component["output_rel"] = ""
            elif component["source"] != str(existing.get("source", "") or ""):
                
                
                component["build_system"] = ""
                component["build_command"] = ""
                component["build_deps"] = ""
                component["output_rel"] = ""
            if component["kind"].lower() == "os package":
                component["local_package_files"] = list(local_files['paths'])
                component["source"] = component["local_package_files"][0] if component["local_package_files"] else ""
                component["destination"] = ""
                family = identify_runtime_family(self.app.state)
                if any(not compatible_package_file(file, family) for file in component["local_package_files"]):
                    messagebox.showerror("Local packages", "Choose local files compatible with " + family + " (.deb, .rpm, or .apk).", parent=win)
                    return
                if not component["local_package_files"] and component["name"] not in installed_packages(self.app.state):
                    messagebox.showerror("Package not available locally", "This package is not installed in the selected runtime and no local package file was selected. Download the package yourself and select Browse package file(s).", parent=win)
                    return
            elif component["kind"].lower() == "base-provided":
                component["source"] = ""
                component["destination"] = ""
            if not component["name"]:
                explanation = "Choose an installed package or browse to a locally downloaded package archive." if component["kind"].lower() == "os package" else "Component name is required."
                messagebox.showerror("Component", explanation, parent=win)
                name_combo.focus_set()
                return
            if component["kind"].lower() == "os package" and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+:_-]*", component["name"]):
                messagebox.showerror("OS package", "Choose an installed package or a locally downloaded package archive.", parent=win)
                name_combo.focus_set()
                return
            if component["kind"].lower() in ("binary", "source", "script", "jar/application", "folder", "other"):
                if not component["source"]:
                    messagebox.showerror("Component", "Select a local file or folder.", parent=win)
                    return
                if not component["destination"].startswith("/"):
                    messagebox.showerror("Component", "Destination must be an absolute Linux path starting with /.", parent=win)
                    return
            if component["kind"].lower() in ("binary", "jar/application"):
                valid, error = validate_component_type(component["kind"], component["source"])
                if not valid:
                    messagebox.showerror("Invalid component type", error, parent=win)
                    status_var.set(error)
                    return
            for i, other in enumerate(self.app.state["components"]):
                if i == index:
                    continue
                if str(other.get("name", "")).strip().lower() == component["name"].lower():
                    messagebox.showerror("Component", f"Component '{component['name']}' already exists.", parent=win)
                    return
            if index is None:
                self.app.state["components"].append(component)
            else:
                self.app.state["components"][index] = component
            win.destroy()
            self.refresh()
            if open_build_tab and component["kind"].strip().lower() == "source":
                sources_tab = getattr(self.app, "sources_tab", None)
                notebook = getattr(self.app, "notebook", None)
                if sources_tab is not None and notebook is not None:
                    notebook.select(sources_tab)
                    sources_tab.refresh_from_project_state()
                    sources_tab.comp.set(component["name"])
                    sources_tab.load_component()
            return True

        tk.Button(footer, text="Save component", command=lambda: save(False), bg="#117864", fg="white",
                  font=("Segoe UI", 10, "bold"), padx=12).pack(side="right", padx=5)
        tk.Button(footer, text="Cancel", command=win.destroy, padx=10).pack(side="right", padx=5)
        build_next_button = tk.Button(
            footer, text="Save and open Tab 4 — Compile Sources",
            command=lambda: save(True), bg="#D35400", fg="white", padx=10,
        )
        build_next_button.pack(side="right", padx=5)

        def toggle_build_next(*_):
            if kind_var.get().strip().lower() == "source":
                if not build_next_button.winfo_manager():
                    build_next_button.pack(side="right", padx=5)
            else:
                build_next_button.pack_forget()

        kind_var.trace_add("write", toggle_build_next)
        toggle_build_next()
        tk.Label(footer, text="Build settings are edited and tested only in Tab 4.",
                 bg="#D5F5E3", fg="#566573").pack(side="left")

    def _browse_file(self, variable):
        path = filedialog.askopenfilename(parent=self)
        if path:
            variable.set(path)

    def _browse_folder(self, variable):
        path = filedialog.askdirectory(parent=self)
        if path:
            variable.set(path)

    def resolve_dependencies(self):
        components = self.app.state.get("components", [])
        by_name = {}

        duplicate_names = []
        for index, component in enumerate(components):
            name = str(component.get("name", "")).strip()
            if not name:
                continue
            key = name.lower()
            if key in by_name:
                duplicate_names.append(name)
            else:
                by_name[key] = index

        messages = []
        if duplicate_names:
            for name in sorted(set(duplicate_names), key=str.lower):
                messages.append(f"DUPLICATE NAME: {name}")

        changed = True
        while changed:
            changed = False
            for component in components:
                if not component.get("enabled", True):
                    continue

                name = str(component.get("name", "")).strip() or "<unnamed>"
                dependencies = [
                    item.strip()
                    for item in str(component.get("depends", "")).split(",")
                    if item.strip()
                ]

                for dependency in dependencies:
                    dep_index = by_name.get(dependency.lower())
                    if dep_index is None:
                        base_match = self._find_base_match(dependency)
                        if base_match:
                            version_text = f" {base_match.get('version','')}" if base_match.get("version") else ""
                            messages.append(
                                f"BASE-SATISFIED: {name} requires '{dependency}', found as "
                                f"{base_match.get('type','')} '{base_match.get('name','')}'{version_text} in the selected base."
                            )
                        else:
                            messages.append(f"MISSING: {name} requires component '{dependency}'.")
                        continue

                    dep_component = components[dep_index]
                    if not dep_component.get("enabled", True):
                        dep_component["enabled"] = True
                        messages.append(
                            f"AUTO-ENABLED: {dep_component.get('name', dependency)} because {name} depends on it."
                        )
                        changed = True

        cycles = self._dependency_cycles(components, by_name)
        for cycle in cycles:
            messages.append("DEPENDENCY CYCLE: " + " -> ".join(cycle))

        if not messages:
            messages.append("No missing dependencies, disabled required components, or dependency cycles detected.")

        self.output.delete("1.0", "end")
        self.output.insert("end", "\n".join(dict.fromkeys(messages)))
        self.refresh()

    def _dependency_cycles(self, components, by_name):
        graph = {}
        display_name = {}

        for component in components:
            if not component.get("enabled", True):
                continue
            name = str(component.get("name", "")).strip()
            if not name:
                continue
            key = name.lower()
            display_name[key] = name
            graph[key] = [
                dependency.strip().lower()
                for dependency in str(component.get("depends", "")).split(",")
                if dependency.strip() and dependency.strip().lower() in by_name
            ]

        visited = set()
        active = []
        active_set = set()
        found = []

        def visit(node):
            if node in active_set:
                start = active.index(node)
                cycle_keys = active[start:] + [node]
                found.append([display_name.get(k, k) for k in cycle_keys])
                return
            if node in visited:
                return

            visited.add(node)
            active.append(node)
            active_set.add(node)
            for dep in graph.get(node, []):
                visit(dep)
            active.pop()
            active_set.remove(node)

        for node in graph:
            visit(node)

        unique = []
        seen = set()
        for cycle in found:
            signature = tuple(x.lower() for x in cycle)
            if signature not in seen:
                seen.add(signature)
                unique.append(cycle)
        return unique

    def import_component_json(self):
        path = filedialog.askopenfilename(
            parent=self,
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            messagebox.showerror("Import component", str(exc))
            return

        if isinstance(data, dict) and "components" in data:
            candidates = data["components"]
        elif isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            candidates = [data]
        else:
            messagebox.showerror("Import component", "JSON must contain a component object or component list.")
            return

        if not isinstance(candidates, list):
            messagebox.showerror("Import component", "'components' must be a list.")
            return

        imported = 0
        rejected = []
        existing_names = {
            str(c.get("name", "")).strip().lower()
            for c in self.app.state["components"]
            if str(c.get("name", "")).strip()
        }

        for raw in candidates:
            component = self._normalized_component(raw)
            if not component["name"]:
                continue
            if component["name"].lower() in existing_names:
                continue
            if component["kind"].lower() in ("binary", "jar/application"):
                valid, problem = validate_component_type(component["kind"], component["source"])
                if not valid:
                    rejected.append(component["name"] + ": " + problem)
                    continue
            self.app.state["components"].append(component)
            existing_names.add(component["name"].lower())
            imported += 1

        self.refresh()
        messagebox.showinfo("Import component", f"Imported {imported} component definition(s)." + ("\n\nRejected:\n" + "\n".join(rejected[:12]) if rejected else ""))

    def export_selected_json(self):
        indices = self._selected_indices()
        if not indices:
            messagebox.showwarning("Export component", "Select one or more components.")
            return

        selected = [self.app.state["components"][i] for i in indices]
        initial_name = "component.json" if len(selected) == 1 else "components.json"

        path = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile=initial_name,
        )
        if not path:
            return

        payload = selected[0] if len(selected) == 1 else {"components": selected}
        try:
            Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            messagebox.showerror("Export component", str(exc))
            return

        messagebox.showinfo("Export component", f"Saved:\n{path}")


class _DebugApp:
    def __init__(self):
        self.state = {"components": [], "base_image": "", "runtime_base_archive": "", "base_system": {}, "base_inventory": {}}


if __name__ == "__main__":
    root = tk.Tk()
    root.title("Debug — ComponentsTab")
    root.geometry("1500x900")
    root.minsize(1100, 700)
    app = _DebugApp()
    tab = ComponentsTab(root, app)
    tab.pack(fill="both", expand=True)
    root.mainloop()
