import json
import os
import re
import shlex
import subprocess
import tarfile
import threading
import time
import uuid
from datetime import datetime, timezone
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from project_state import effective_builder_image
from build_artifacts import read_record
from component_presets import suggested_destination
from runtime_source_status import runtime_component_status
from component_provenance import provenance_from_docker
from docker_image_checkpoint import save_full_image_to_tar
from workflow_toolbar import add_more_menu
from image_filesystem_inventory import inspect_saved_tar, inspect_tag_via_export, InspectionCancelled, InspectionTimeout
from component_provenance import image_identity
from docker_image_checkpoint import docker_image_matches_tar


class BaseTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg="#EAF2F8")
        self.app = app
        self._library_records = []
        self._busy = False
        self._inspection_active = False
        self._inspection_target = ''
        self._inspection_cancel = threading.Event()
        self._inspection_process = None
        self._inspection_start = 0.0
        self._inspection_phase = 'Idle'
        self._inspection_layer = (0, 0)
        self._inspection_stage_index = 0
        self._inspection_last_update = 0.0
        self._scan_data_lock = threading.Lock()
        self._scan_counts = {'EXEC': 0, 'PKG': 0, 'PIP': 0, 'RPKG': 0, 'JAR': 0}
        self._scan_totals = {}
        self._scan_recent_packages = []
        self._scan_last_name = ''
        self._scan_detail = ''
        self._scan_previous_package_count = 0
        self._auto_inspections = set()
        self._active_role = "runtime"
        self._image_export_busy = False

        self.app.state.setdefault("runtime_base_archive", "")
        self.app.state.setdefault("builder_base_archive", "")
        self.app.state.setdefault("gui_loaded_images", [])
        self.app.state.setdefault("base_image", "")
        self.app.state.setdefault("builder_image", "")
        self.app.state.setdefault("base_prepare", "")
        self.app.state.setdefault("project_dir", str(Path.cwd()))
        self.app.state.setdefault("base_system", {})
        self.app.state.setdefault("base_inventory", {})
        self.app.state.setdefault("builder_system", {})
        self.app.state.setdefault("builder_inventory", {})

        tk.Label(
            self,
            text="2 — BASE INVENTORY / DOCKER IMAGE INSPECTION",
            bg="#1F4E78",
            fg="white",
            font=("Segoe UI", 16, "bold"),
            anchor="w",
            padx=14,
            pady=10,
        ).pack(fill="x")

        selection_note = tk.Frame(self, bg="#D6EAF8")
        selection_note.pack(fill="x", padx=14, pady=(10, 5))
        tk.Label(
            selection_note,
            text="Runtime is selected in Tab 0; the builder is selected in Tab 1. "
                 "A TAR is optional: Tab 2 inspects the CURRENT selected image, including binaries "
                 "from earlier builds. New compiled outputs remain staged until assembled in Tab 6.",
            bg="#D6EAF8", fg="#154360", justify="left", anchor="w", padx=10, pady=8,
        ).pack(side="left", fill="x", expand=True)
        selectors = tk.LabelFrame(
            self,
            text=" Runtime Tab 0 / Builder Tab 1 — READ ONLY ",
            bg="#EAF2F8",
            fg="#154360",
            font=("Segoe UI", 10, "bold"),
            padx=10,
            pady=8,
        )
        self.selectors_frame = selectors
        selectors.pack(fill="x", padx=14, pady=6)

        tk.Label(selectors, text="Runtime (final) base archive:", bg="#EAF2F8", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", pady=4)
        self.runtime_display = tk.StringVar()
        ttk.Entry(selectors, textvariable=self.runtime_display, state="readonly", width=86).grid(
            row=0, column=1, sticky="ew", padx=8
        )

        tk.Label(selectors, text="Builder base archive:", bg="#EAF2F8", font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky="w", pady=4)
        self.builder_display = tk.StringVar(value="(same as runtime base)")
        ttk.Entry(selectors, textvariable=self.builder_display, state="readonly", width=86).grid(
            row=1, column=1, sticky="ew", padx=8
        )

        tk.Label(selectors, text="Runtime Docker tag:", bg="#EAF2F8").grid(row=2, column=0, sticky="w", pady=4)
        self.runtime_tag = tk.StringVar(value=self.app.state.get("base_image", ""))
        tk.Entry(selectors, textvariable=self.runtime_tag, width=65, state="readonly").grid(row=2, column=1, sticky="ew", padx=8)
        self.runtime_status = tk.Label(selectors, text="Not selected", bg="#EAF2F8", fg="#7F8C8D")
        self.runtime_status.grid(row=2, column=2, sticky="w", padx=3)

        tk.Label(selectors, text="Builder Docker tag:", bg="#EAF2F8").grid(row=3, column=0, sticky="w", pady=4)
        self.builder_tag = tk.StringVar(value=self.app.state.get("builder_image", ""))
        tk.Entry(selectors, textvariable=self.builder_tag, width=65, state="readonly").grid(row=3, column=1, sticky="ew", padx=8)
        self.builder_status = tk.Label(selectors, text="Same as runtime" if not self.builder_tag.get() else "Not loaded", bg="#EAF2F8", fg="#7F8C8D")
        self.builder_status.grid(row=3, column=2, sticky="w", padx=3)

        self.runtime_role_summary = tk.StringVar(value="Runtime contents: not selected")
        self.builder_role_summary = tk.StringVar(value="Builder contents: same as runtime")
        tk.Label(selectors, textvariable=self.runtime_role_summary, bg="#EAF2F8", fg="#34495E", anchor="w", justify="left").grid(row=4, column=1, columnspan=2, sticky="ew", padx=8, pady=(2, 0))
        tk.Label(selectors, textvariable=self.builder_role_summary, bg="#EAF2F8", fg="#34495E", anchor="w", justify="left").grid(row=5, column=1, columnspan=2, sticky="ew", padx=8, pady=(0, 2))

        base_buttons = tk.Frame(selectors, bg="#EAF2F8")
        base_buttons.grid(row=6, column=1, columnspan=2, sticky="w", padx=8, pady=6)
        self.image_save_button = tk.Button(base_buttons, text="Save selected image to TAR",
                                           bg="#117864", fg="white", command=self.save_selected_image_to_tar)
        self.image_save_button.pack(side="left", padx=5)
        selectors.columnconfigure(1, weight=1)

        advanced = tk.LabelFrame(
            self,
            text=" Advanced base preparation (optional) ",
            bg="#EAF2F8",
            fg="#154360",
            font=("Segoe UI", 10, "bold"),
            padx=10,
            pady=6,
        )
        advanced.pack(fill="x", padx=14, pady=6)

        tk.Label(
            advanced,
            text="Preparation command executed before package installation/build steps:",
            bg="#EAF2F8",
        ).pack(anchor="w")
        self.prepare = tk.Text(advanced, height=3, width=90)
        self.prepare.pack(fill="x", pady=(4, 0))
        self.prepare.insert("1.0", self.app.state.get("base_prepare", ""))
        self.prepare.bind("<KeyRelease>", self._sync_prepare_to_state)
        self.prepare.bind("<FocusOut>", self._sync_prepare_to_state)

        self.lower = tk.PanedWindow(self, orient="horizontal", sashrelief="raised", bg="#D6EAF8")
        self.lower.pack(fill="both", expand=True, padx=14, pady=(6, 14))

        self.inventory_frame = tk.Frame(self.lower, bg="#EAF2F8")
        self.analysis_frame = tk.Frame(self.lower, bg="#EAF2F8")
        self.lower.add(self.inventory_frame, minsize=650)
        self.lower.add(self.analysis_frame, minsize=430)

        tk.Label(self.inventory_frame, text="Selected Docker image / installed software inventory", bg="#EAF2F8", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        inventory_buttons = tk.Frame(self.inventory_frame, bg="#EAF2F8")
        inventory_buttons.pack(fill="x", pady=(4, 4))
        tk.Button(inventory_buttons, text="Show runtime", bg="#AED6F1", command=self.show_runtime_contents).pack(side="left", padx=(0, 3))
        tk.Button(inventory_buttons, text="Show builder", bg="#D7BDE2", command=self.show_builder_contents).pack(side="left", padx=3)
        tk.Button(inventory_buttons, text="Compiled outputs", bg="#F9E79F", command=self.show_compiled_outputs).pack(side="left", padx=3)
        tk.Button(
            inventory_buttons,
            text="Inspect / refresh selected",
            bg="#17A589",
            fg="white",
            command=self.refresh_selected_inventory,
        ).pack(side="left", padx=3)
        add_more_menu(inventory_buttons, [
            ("Full package inventory report", self.show_full_package_list),
            ("Probe selected executable version", self.probe_selected_version),
            ("Unload images imported by this GUI", self.unload_gui_images),
        ], "#EAF2F8")

        self.inventory_summary = tk.StringVar(value="Select runtime or builder. Cached inspection results will appear here.")
        tk.Label(
            self.inventory_frame,
            textvariable=self.inventory_summary,
            bg="#EAF2F8",
            fg="#34495E",
            justify="left",
            anchor="w",
            wraplength=650,
        ).pack(fill="x", pady=(0, 4))

        self.scan_status = tk.StringVar(value="Inspection idle — select an image and click Inspect / refresh selected")
        scan_row = tk.Frame(self.inventory_frame, bg="#EAF2F8")
        scan_row.pack(fill="x", pady=(0, 6))
        self.scan_progress = ttk.Progressbar(scan_row, mode="determinate", maximum=800, length=210)
        self.scan_progress.pack(side="left", fill="x", expand=True, padx=(0, 7))
        self.scan_stop = tk.Button(scan_row, text="Stop scan", command=self.cancel_inspection,
                                   state="disabled", bg="#B03A2E", fg="white")
        self.scan_stop.pack(side="right")
        tk.Label(self.inventory_frame, textvariable=self.scan_status, bg="#EAF2F8", fg="#154360",
                 anchor="w", justify="left", wraplength=700).pack(fill="x", pady=(0, 3))
        self.scan_found_text = tk.StringVar(value='Actual results: no scan running')
        tk.Label(self.inventory_frame, textvariable=self.scan_found_text, bg="#EAF2F8",
                 fg="#1F4E78", anchor="w", justify="left", wraplength=700,
                 font=('Segoe UI', 9, 'bold')).pack(fill='x', pady=(0, 4))

        inventory_filter = tk.Frame(self.inventory_frame, bg="#EAF2F8")
        inventory_filter.pack(fill="x", pady=(0, 4))
        tk.Label(inventory_filter, text="Show:", bg="#EAF2F8").pack(side="left")
        self.inventory_view = tk.StringVar(value="All software entries")
        self.inventory_view_combo = ttk.Combobox(
            inventory_filter,
            textvariable=self.inventory_view,
            state="readonly",
            width=27,
            values=(
                "All software entries",
                "Executables",
                "OS packages",
                "Python packages",
                "R packages",
                "JAR files",
                "Compiled outputs (staged)",
            ),
        )
        self.inventory_view_combo.pack(side="left", padx=(4, 8))
        self.inventory_view_combo.bind("<<ComboboxSelected>>", lambda e: self._inventory_view_changed())
        tk.Label(inventory_filter, text="Search:", bg="#EAF2F8").pack(side="left")
        self.inventory_search = tk.StringVar()
        search_entry = tk.Entry(inventory_filter, textvariable=self.inventory_search, width=18)
        search_entry.pack(side="left", padx=(4, 0), fill="x", expand=True)
        self.inventory_search.trace_add("write", lambda *_: self._populate_inventory_tree())

        inventory_body = tk.Frame(self.inventory_frame, bg="#EAF2F8")
        inventory_body.pack(fill="both", expand=True)
        inv_cols = ("type", "application", "version", "path")
        self.inventory_tree = ttk.Treeview(inventory_body, columns=inv_cols, show="headings", height=10, selectmode="extended")
        self.inventory_tree.heading("type", text="Type")
        self.inventory_tree.heading("application", text="Software / Command")
        self.inventory_tree.heading("version", text="Version")
        self.inventory_tree.heading("path", text="Location")
        self.inventory_tree.column("type", width=90, anchor="w")
        self.inventory_tree.column("application", width=190, anchor="w")
        self.inventory_tree.column("version", width=160, anchor="w")
        self.inventory_tree.column("path", width=330, anchor="w")
        inventory_scroll = ttk.Scrollbar(inventory_body, orient="vertical", command=self.inventory_tree.yview)
        self.inventory_tree.configure(yscrollcommand=inventory_scroll.set)
        self.inventory_tree.grid(row=0, column=0, sticky="nsew")
        inventory_scroll.grid(row=0, column=1, sticky="ns")
        inventory_body.rowconfigure(0, weight=1)
        inventory_body.columnconfigure(0, weight=1)

        analysis_header = tk.Frame(self.analysis_frame, bg="#EAF2F8")
        analysis_header.pack(fill="x")
        tk.Label(analysis_header, text="Base analysis / activity log", bg="#EAF2F8", font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Button(analysis_header, text="Clear log", bg="#D6DBDF", command=lambda: self.out.delete('1.0', 'end')).pack(side="right", padx=3)
        analysis_body = tk.Frame(self.analysis_frame, bg="#EAF2F8")
        analysis_body.pack(fill="both", expand=True, pady=(4, 0))
        self.out = tk.Text(analysis_body, bg="white", font=("Consolas", 9), height=13, wrap="word")
        activity_scroll = ttk.Scrollbar(analysis_body, orient="vertical", command=self.out.yview)
        self.out.configure(yscrollcommand=activity_scroll.set)
        self.out.grid(row=0, column=0, sticky="nsew")
        activity_scroll.grid(row=0, column=1, sticky="ns")
        analysis_body.rowconfigure(0, weight=1)
        analysis_body.columnconfigure(0, weight=1)

        self.refresh_selected_archives()

    def _run(self, args, **kwargs):
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            **kwargs,
        )

    @staticmethod
    def _run_linux_stdin_script(args, script, timeout):
        normalized = str(script).replace("\r\n", "\n").replace("\r", "\n")
        result = subprocess.run(
            args,
            input=normalized.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return subprocess.CompletedProcess(
            args,
            result.returncode,
            result.stdout.decode("utf-8", errors="replace"),
            result.stderr.decode("utf-8", errors="replace"),
        )

    def _log(self, text):
        self.out.insert("end", text)
        self.out.see("end")

    def _set_busy(self, busy):
        self._busy = busy

    def _sync_prepare_to_state(self, event=None):
        if hasattr(self, "prepare"):
            self.app.state["base_prepare"] = self.prepare.get("1.0", "end").strip()

    def _touch_shared_state(self, key="base"):
        touch = getattr(self.app.state, "touch", None)
        if callable(touch):
            touch(key)

    def _path_equal(self, a, b):
        if not a or not b:
            return False
        try:
            return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))
        except Exception:
            return str(a) == str(b)

    def _find_record_by_path(self, path):
        if not path:
            return None
        for rec in self._library_records:
            if self._path_equal(rec.get("path", ""), path):
                return rec
        return None

    def _runtime_record(self):
        selected_archive = str(self.app.state.get("runtime_base_archive", "") or "").strip()
        if selected_archive:
            return self._find_record_by_path(selected_archive)
        return self._tag_record("runtime")

    def _builder_record(self):
        if self.app.state.get('builder_mode') == 'runtime':
            return self._runtime_record()
        builder_path = self.app.state.get("builder_base_archive", "")
        if builder_path:
            return self._find_record_by_path(builder_path)
        if self.app.state.get("builder_image"):
            return self._tag_record("builder")
        return self._runtime_record()

    def _tag_record(self, role):
        tag_key = "base_image" if role == "runtime" else "builder_image"
        inventory_key = "base_inventory" if role == "runtime" else "builder_inventory"
        system_key = "base_system" if role == "runtime" else "builder_system"
        tag = str(self.app.state.get(tag_key, "") or "").strip()
        if not tag:
            return None
        inventory = self.app.state.get(inventory_key)
        inspection = dict(inventory) if isinstance(inventory, dict) else {}
        system = self.app.state.get(system_key)
        current_id = self._docker_image_id(tag)
        if not self._has_complete_inspection(inspection) or not current_id or inspection.get('image_id') != current_id:
            if inspection and self._has_complete_inspection(inspection):
                self.app.state[inventory_key] = {}
            inspection = {}
        elif isinstance(system, dict) and system and not inspection.get("system"):
            inspection["system"] = dict(system)
        return {
            "path": "", "tags": [tag], "size": 0, "tag_only": True, "role": role,
            "metadata": {"docker_tag": tag, "inspection": inspection,
                         "os": system.get("os", "") if isinstance(system, dict) else "",
                         "architecture": system.get("architecture", "") if isinstance(system, dict) else ""},
        }

    @staticmethod
    def _has_complete_inspection(inspection):
        if not isinstance(inspection, dict) or inspection.get('schema') != 6:
            return False
        executables = inspection.get('executables')
        packages = inspection.get('packages')
        return (isinstance(executables, list) and len(executables) > 0
                and isinstance(packages, dict) and isinstance(packages.get('os'), list)
                and bool(inspection.get('inspected_at')))

    def _inventory_short_summary(self, rec):
        if not rec:
            return "not selected"
        metadata = rec.get("metadata") or (self._read_sidecar(rec.get("path", "")) if rec.get("path") else {})
        label = rec["tags"][0] if rec.get("tag_only") else Path(rec.get("path", "")).name
        inspection = metadata.get("inspection") if isinstance(metadata.get("inspection"), dict) else {}
        if not self._has_complete_inspection(inspection):
            return f"{label}: not inspected"
        system = inspection.get("system") if isinstance(inspection.get("system"), dict) else {}
        packages = inspection.get("packages") if isinstance(inspection.get("packages"), dict) else {}
        executables = inspection.get("executables") if isinstance(inspection.get("executables"), list) else []
        os_packages = packages.get("os", []) if isinstance(packages.get("os", []), list) else []
        return (f"{label}: {system.get('os','unknown')} | "
                f"{system.get('architecture','unknown')} | {len(executables)} executables | "
                f"{len(os_packages)} OS packages")

    def _update_role_summaries(self):
        runtime = self._runtime_record()
        builder_path = self.app.state.get("builder_base_archive", "")
        builder = self._builder_record()
        runtime_description = (self._inventory_short_summary(runtime) if runtime else
                               self._docker_tag_summary('base_image', 'base_inventory', 'base_system'))
        self.runtime_role_summary.set("Runtime contents: " + runtime_description)
        if builder_path:
            self.builder_role_summary.set("Builder contents: " + self._inventory_short_summary(builder))
        elif self.app.state.get('builder_image'):
            self.builder_role_summary.set("Builder contents: " +
                                          self._docker_tag_summary('builder_image', 'builder_inventory', 'builder_system'))
        else:
            self.builder_role_summary.set("Builder contents: SAME AS RUNTIME — " + runtime_description)

    def _docker_tag_summary(self, tag_key, inventory_key, system_key):
        tag = str(self.app.state.get(tag_key) or '')
        if not tag:
            return 'not selected'
        inventory = self.app.state.get(inventory_key) or {}
        system = self.app.state.get(system_key) or {}
        if not isinstance(inventory, dict):
            inventory = {}
        if not isinstance(system, dict):
            system = {}
        if not self._has_complete_inspection(inventory):
            return tag + ' | ' + str(system.get('os') or '?') + ' | software inventory NOT INSPECTED'
        packages = inventory.get('packages') or {}
        if not isinstance(packages, dict):
            packages = {}
        executables = inventory.get('executables') or []
        if not isinstance(executables, list):
            executables = []
        return (tag + ' | ' + str(system.get('os') or '?') + ' | ' +
                str(len(executables)) + ' executables | ' +
                str(len(packages.get('os') or [])) + ' OS packages')

    def _display_selected_inventory(self, rec):
        if rec is None:
            return False
        self._show_record_inventory(rec)
        return True

    def show_runtime_contents(self):
        self._active_role = "runtime"
        self.inventory_view.set("All software entries")
        rec = self._runtime_record()
        if not rec:
            messagebox.showwarning("Runtime base", "No runtime Docker image is selected.")
            return
        self._display_selected_inventory(rec)

    def show_builder_contents(self):
        self._active_role = "builder"
        self.inventory_view.set("All software entries")
        rec = self._builder_record()
        if not rec:
            messagebox.showwarning("Builder base", "No builder Docker image is selected.")
            return
        self._display_selected_inventory(rec)

    def show_compiled_outputs(self):
        self.inventory_view.set("Compiled outputs (staged)")
        self._populate_inventory_tree()

    def _inventory_view_changed(self):
        if self.inventory_view.get() == "Compiled outputs (staged)":
            self._populate_inventory_tree()
            return
        rec = self._selected_record()
        if rec:
            self._display_selected_inventory(rec)
        else:
            self._populate_inventory_tree()

    def _publish_builder_inspection(self, rec, inspection):
        if not rec or not inspection:
            return
        builder_archive = str(self.app.state.get("builder_base_archive", "") or "")
        if not builder_archive or not self._path_equal(builder_archive, rec.get("path", "")):
            return
        system = inspection.get("system", {}) if isinstance(inspection.get("system", {}), dict) else {}
        if hasattr(self.app.state, "publish_builder"):
            self.app.state.publish_builder(archive=rec.get("path", ""), tag=self.app.state.get("builder_image", ""), system=system, inventory=inspection)
        else:
            self.app.state["builder_system"] = system
            self.app.state["builder_inventory"] = inspection
            self._touch_shared_state("builder_base")

    def _publish_runtime_inspection(self, rec, inspection):
        if not rec or not inspection:
            return
        current_archive = str(self.app.state.get("runtime_base_archive", "") or "")
        if not current_archive:
            return
        try:
            same = os.path.normcase(os.path.abspath(current_archive)) == os.path.normcase(os.path.abspath(rec["path"]))
        except Exception:
            same = current_archive == str(rec.get("path", ""))
        if not same:
            return

        system = inspection.get("system", {}) if isinstance(inspection.get("system", {}), dict) else {}
        if hasattr(self.app.state, "publish_base"):
            self.app.state.publish_base(
                archive=rec.get("path", ""),
                tag=self.app.state.get("base_image", ""),
                system=system,
                inventory=inspection,
            )
        else:
            self.app.state["base_system"] = system
            self.app.state["base_inventory"] = inspection
            self._touch_shared_state("base")

    def refresh_from_project_state(self):
        self.runtime_tag.set(self.app.state.get("base_image", ""))
        self.builder_tag.set(self.app.state.get("builder_image", ""))
        if hasattr(self, "prepare"):
            current = self.prepare.get("1.0", "end").strip()
            wanted = str(self.app.state.get("base_prepare", "") or "")
            if current != wanted:
                self.prepare.delete("1.0", "end")
                self.prepare.insert("1.0", wanted)

        self.refresh_selected_archives()
        rec = self._runtime_record()
        if rec and rec.get('tag_only'):
            tag = str(rec.get('tags', [''])[0] or '')
            image_id = self._docker_image_id(tag)
            key = (tag, image_id)
            metadata = rec.get('metadata') or {}
            if image_id and key not in self._auto_inspections and not self._has_complete_inspection(metadata.get('inspection')):
                self._auto_inspections.add(key)
                def inspect_when_visible():
                    current = self._runtime_record()
                    if not current or current.get('tags', [''])[0] != tag:
                        return
                    if self._inspection_active:
                        self.after(400, inspect_when_visible)
                    else:
                        self._inspection_record(current, force=True)
                self.after(150, inspect_when_visible)

    def _archive_tags(self, archive_path):
        tags = []
        try:
            with tarfile.open(archive_path, "r:*") as tf:
                try:
                    member = tf.getmember("manifest.json")
                    f = tf.extractfile(member)
                    if f:
                        manifest = json.loads(f.read().decode("utf-8", errors="replace"))
                        for item in manifest:
                            for tag in item.get("RepoTags") or []:
                                if tag and tag not in tags:
                                    tags.append(tag)
                except (KeyError, json.JSONDecodeError, tarfile.TarError):
                    pass
                if not tags:
                    try:
                        member = tf.getmember("repositories")
                        f = tf.extractfile(member)
                        if f:
                            repositories = json.loads(f.read().decode("utf-8", errors="replace"))
                            for repo, tag_map in repositories.items():
                                for tag in tag_map:
                                    full = f"{repo}:{tag}"
                                    if full not in tags:
                                        tags.append(full)
                    except (KeyError, json.JSONDecodeError, tarfile.TarError):
                        pass
        except (tarfile.TarError, OSError):
            pass
        return tags

    def _image_exists(self, tag):
        return bool(self._docker_image_id(tag))

    def _docker_image_id(self, tag):
        if not tag:
            return ''
        try:
            p = self._run(["docker", "image", "inspect", "--format", "{{.Id}}", tag], timeout=8)
            return p.stdout.strip() if p.returncode == 0 else ''
        except (OSError, subprocess.TimeoutExpired):
            return ''

    def _sidecar_path(self, archive_path):
        return Path(archive_path).with_suffix(".json")

    def _read_sidecar(self, archive_path):
        if not archive_path:
            return {}
        p = self._sidecar_path(archive_path)
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_sidecar(self, archive_path, updates):
        p = self._sidecar_path(archive_path)
        data = self._read_sidecar(archive_path)
        data.update(updates)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data

    def _persistent_version_probes(self, metadata):
        probes = metadata.get("version_probes")
        if not isinstance(probes, dict):
            probes = {}

        inspection = metadata.get("inspection") if isinstance(metadata.get("inspection"), dict) else {}
        executables = inspection.get("executables") if isinstance(inspection.get("executables"), list) else []
        for item in executables:
            path = str(item.get("path", "")).strip()
            version = str(item.get("version", "")).strip()
            source = str(item.get("version_source", "")).strip()
            if not path or not version:
                continue
            if source not in ("runtime", "package", "saved"):
                continue
            if path not in probes:
                probes[path] = {
                    "name": str(item.get("name", "")).strip(),
                    "version": version,
                    "version_source": source,
                    "package": str(item.get("package", "")).strip(),
                    "package_version": str(item.get("package_version", "")).strip(),
                }
        return probes

    def _apply_persistent_versions(self, metadata, inspection):
        probes = self._persistent_version_probes(metadata)
        executables = inspection.get("executables") if isinstance(inspection.get("executables"), list) else []
        for item in executables:
            path = str(item.get("path", "")).strip()
            saved = probes.get(path)
            if not isinstance(saved, dict):
                continue
            version = str(saved.get("version", "")).strip()
            if version:
                item["version"] = version
                item["version_source"] = str(saved.get("version_source", "saved") or "saved")
            package = str(saved.get("package", "")).strip()
            if package:
                item["package"] = package
            package_version = str(saved.get("package_version", "")).strip()
            if package_version:
                item["package_version"] = package_version
        return probes

    def _selected_record(self):
        if self._active_role == "builder":
            return self._builder_record()
        return self._runtime_record()

    def _show_record_inventory(self, rec):
        metadata = rec.get("metadata") or self._read_sidecar(rec["path"])
        rec["metadata"] = metadata
        inspection = metadata.get("inspection") if isinstance(metadata.get("inspection"), dict) else {}
        if not self._has_complete_inspection(inspection):
            inspection = {}
        if inspection:
            self._apply_persistent_versions(metadata, inspection)
        system = inspection.get("system") if isinstance(inspection.get("system"), dict) else {}
        packages = inspection.get("packages") if isinstance(inspection.get("packages"), dict) else {}
        executables = inspection.get("executables") if isinstance(inspection.get("executables"), list) else []
        jars = packages.get("jars", []) if isinstance(packages.get("jars", []), list) else []
        os_packages = packages.get("os", []) if isinstance(packages.get("os", []), list) else []
        py_packages = packages.get("python", []) if isinstance(packages.get("python", []), list) else []
        r_packages = packages.get("r", []) if isinstance(packages.get("r", []), list) else []

        tag = rec["tags"][0] if rec["tags"] else metadata.get("docker_tag", "<unknown>")
        archive_name = tag if rec.get("tag_only") else Path(rec["path"]).name

        if inspection:
            os_name = system.get("os", metadata.get("os", "unknown"))
            arch = system.get("architecture", metadata.get("architecture", "unknown"))
            libc = system.get("glibc", "unknown")
            pm = system.get("package_manager", "unknown")
            inspected_at = inspection.get("inspected_at", "")
            total_entries = len(executables) + len(jars) + len(os_packages) + len(py_packages) + len(r_packages)
            refresh_note = ('REFRESH IN PROGRESS — showing the previous saved inventory until verification finishes.\n'
                            if self._inspection_active and self._inspection_target == tag else '')
            self.inventory_summary.set(
                refresh_note + f"{archive_name}\n"
                f"Tag: {tag}   |   OS: {os_name}   |   Arch: {arch}\n"
                f"Software entries: {total_entries}   |   Executables: {len(executables)}   |   OS packages: {len(os_packages)}   |   JARs: {len(jars)}\n"
                f"Python packages: {len(py_packages)}   |   R packages: {len(r_packages)}   |   libc: {libc}   |   Package manager: {pm}\n"
                f"Inspection: {inspected_at or 'cached'}   |   Staged outputs (not installed): {len(self._staged_inventory_rows()) if self._active_role == 'runtime' else 0}"
            )
            self._populate_inventory_tree(inspection)
            if rec.get("tag_only"):
                inventory_key = "base_inventory" if rec.get("role") == "runtime" else "builder_inventory"
                if self.app.state.get(inventory_key) != inspection:
                    system_data = inspection.get("system", {}) if isinstance(inspection.get("system", {}), dict) else {}
                    if rec.get("role") == "runtime":
                        self.app.state.publish_base(tag=tag, system=system_data, inventory=inspection)
                    else:
                        self.app.state.publish_builder(tag=tag, system=system_data, inventory=inspection)
            else:
                self._publish_runtime_inspection(rec, inspection)
                self._publish_builder_inspection(rec, inspection)
            self._update_role_summaries()
        else:
            os_name = metadata.get("os", "unknown")
            arch = metadata.get("architecture", "unknown")
            self.inventory_summary.set(
                f"{archive_name}\n"
                f"Tag: {tag}   |   OS: {os_name}   |   Arch: {arch}\n"
                "No cached installed-software inventory. Click 'Inspect / refresh selected'. Staged outputs may still be listed."
            )
            self._populate_inventory_tree({})

    def _staged_inventory_rows(self):
        if self._active_role != "runtime":
            return []
        state = self.app.state
        rows = []
        for component in state.get("components", []) or []:
            if not isinstance(component, dict) or str(component.get("kind", "")).strip().lower() != "source":
                continue
            installed = runtime_component_status(state, component)
            if installed and installed.get("verified"):
                continue
            record, _ = read_record(state, component)
            if not record:
                continue
            filename = Path(str(record["artifact"])).name
            destination = str(component.get("destination") or suggested_destination(component.get("kind"), component.get("name"))).strip()
            if not destination.startswith("/"):
                destination = "/usr/local/bin/"
            final_path = destination.rstrip("/") + "/" + filename
            active = bool(component.get("enabled", True))
            rows.append({"type": "Staged executable" if active else "Staged (disabled)",
                         "name": str(component.get("name") or filename),
                         "version": str(component.get("version") or record.get("version") or ""),
                         "path": "Planned: " + final_path + " (not in image; " +
                                 ("build in Tab 6" if active else "currently disabled") + ") | Saved: " + str(record["artifact"])})
        return rows

    def _populate_inventory_tree(self, inspection=None):
        self.inventory_tree.delete(*self.inventory_tree.get_children())
        if self.inventory_view.get() == "Compiled outputs (staged)":
            self._populate_compiled_outputs()
            return
        if inspection is None:
            rec = self._selected_record()
            if not rec:
                return
            metadata = rec.get("metadata") or self._read_sidecar(rec["path"])
            inspection = metadata.get("inspection") if isinstance(metadata.get("inspection"), dict) else {}
            if not self._has_complete_inspection(inspection):
                inspection = {}
            if inspection:
                self._apply_persistent_versions(metadata, inspection)
        if not inspection and not self._staged_inventory_rows():
            return

        executables = inspection.get("executables") if isinstance(inspection.get("executables"), list) else []
        packages = inspection.get("packages") if isinstance(inspection.get("packages"), dict) else {}
        os_packages = packages.get("os", []) if isinstance(packages.get("os", []), list) else []
        py_packages = packages.get("python", []) if isinstance(packages.get("python", []), list) else []
        r_packages = packages.get("r", []) if isinstance(packages.get("r", []), list) else []
        jars = packages.get("jars", []) if isinstance(packages.get("jars", []), list) else []

        rows = []
        for item in executables:
            rows.append({"type": "Executable", "name": item.get("name", ""), "version": item.get("version", ""), "path": item.get("path", "")})
        for item in os_packages:
            rows.append({"type": "OS package", "name": item.get("name", ""), "version": item.get("version", ""), "path": ""})
        for item in py_packages:
            rows.append({"type": "Python package", "name": item.get("name", ""), "version": item.get("version", ""), "path": ""})
        for item in r_packages:
            rows.append({"type": "R package", "name": item.get("name", ""), "version": item.get("version", ""), "path": ""})
        for jar in jars:
            jar = str(jar).strip()
            if jar:
                rows.append({"type": "JAR", "name": Path(jar).name, "version": "", "path": jar})
        rows.extend(self._staged_inventory_rows())

        view = self.inventory_view.get() if hasattr(self, "inventory_view") else "All software entries"
        query = self.inventory_search.get().strip().lower() if hasattr(self, "inventory_search") else ""
        view_map = {
            "Executables": {"Executable", "Staged executable", "Staged (disabled)"},
            "OS packages": {"OS package"},
            "Python packages": {"Python package"},
            "R packages": {"R package"},
            "JAR files": {"JAR"},
        }
        allowed = view_map.get(view)
        if allowed is not None:
            rows = [r for r in rows if r["type"] in allowed]

        if query:
            rows = [
                r for r in rows
                if query in str(r["name"]).lower()
                or query in str(r["version"]).lower()
                or query in str(r["path"]).lower()
                or query in str(r["type"]).lower()
            ]

        type_order = {"Executable": 0, "Staged executable": 1, "Staged (disabled)": 1, "OS package": 2, "Python package": 3, "R package": 4, "JAR": 5}
        rows.sort(key=lambda r: (type_order.get(r["type"], 9), str(r["name"]).lower(), str(r["path"]).lower()))
        for i, row in enumerate(rows):
            self.inventory_tree.insert("", "end", iid=f"inv{i}", values=(row["type"], row["name"], row["version"], row["path"]))
        if not rows:
            self.inventory_tree.insert("", "end", values=("", "<no matching software entries>", "", ""))

    def _populate_compiled_outputs(self):
        state = self.app.state
        sources = [item for item in state.get('components', [])
                   if str(item.get('kind', '')).lower() == 'source']
        query = self.inventory_search.get().strip().lower()
        ready = 0
        in_runtime = 0
        unverified = 0
        visible = []
        for item in sources:
            name = str(item.get('name') or '')
            active = bool(item.get('enabled', True))
            installed = runtime_component_status(state, item)
            if installed:
                in_runtime += int(installed['verified'])
                unverified += int(not installed['verified'])
                kind = 'Present in image' if installed['verified'] else 'Unverified — build record only'
                row = (kind, name, str(item.get('version') or ''), installed['path'] + ' | ' + installed['source'])
                if not query or query in ' '.join(row).lower():
                    visible.append(row)
                continue
            record, explanation = read_record(state, item)
            if record:
                ready += int(active)
                filename = Path(record['artifact']).name
                destination = str(item.get('destination') or suggested_destination(item.get('kind'), name)).rstrip('/')
                final_path = (destination + '/' + filename) if destination.startswith('/') else '(set destination in Tab 3)'
                kind = 'Staged executable' if active else 'Disabled executable'
                location = 'Final: ' + final_path + ' | Saved: ' + str(record['artifact'])
            else:
                kind = 'Not ready' if active else 'Disabled source'
                location = explanation
            row = (kind, name, str(item.get('version') or ''), location)
            if not query or query in ' '.join(row).lower():
                visible.append(row)
        self.inventory_summary.set('Compiled source outputs — ' + str(in_runtime) + ' already present in the selected runtime image; '
                                   + str(unverified) + ' need runtime inspection; '
                                   + str(ready) + ' ready to add in the NEXT Tab 6 build. '
                                   'Select Show runtime to inspect executable files actually found in the image.')
        for index, row in enumerate(sorted(visible, key=lambda item: item[1].lower())):
            self.inventory_tree.insert('', 'end', iid='compiled' + str(index), values=row)
        if not visible:
            self.inventory_tree.insert('', 'end', values=('', '<no matching compiled source outputs>', '', ''))

    def _extract_version_candidate(self, raw, returncode=None):
        lines = [re.sub(r"\s+", " ", x.strip()) for x in (raw or "").splitlines() if x.strip()]
        if not lines:
            return ""

        reject_phrases = (
            "usage:", "usage ", "synopsis:", "try '", 'try "', "unknown option", "unrecognized option",
            "invalid option", "invalid operation", "illegal option", "unknown command", "unrecognized command",
            "no such file", "not found", "does not exist", "missing operand", "missing argument", "requires an argument",
            "too few arguments", "too many arguments", "permission denied", "must use", "error:", "fatal:", "exception:",
            "traceback ", "user 'version'", 'user "version"', "command not found", "cannot open", "failed to",
        )
        version_re = re.compile(
            r"(?i)(?:\bversion\s*[:=]?\s*)?v?\d+(?:[._-]\d+)+(?:[+._~-]?[0-9A-Za-z]+)*"
        )
        loose_re = re.compile(r"(?i)\b(?:v|release|version)\s*[:=]?\s*\d+(?:[._-]\d+)*")

        best = ""
        best_score = -1
        for line in lines[:30]:
            low = line.lower()
            if any(x in low for x in reject_phrases):
                continue
            if not any(ch.isdigit() for ch in line):
                continue
            has_version_token = bool(version_re.search(line) or loose_re.search(line))
            if not has_version_token:
                continue
            score = 0
            if "version" in low or "release" in low:
                score += 5
            if version_re.search(line):
                score += 4
            if returncode == 0:
                score += 2
            if len(line) <= 160:
                score += 1
            if low.startswith(("usage", "error", "warning", "fatal")):
                score -= 10
            if score > best_score:
                best = line[:300]
                best_score = score
        return best

    def _package_version_for_executable(self, image, exe_path):
        script = r'''path="$GUI_TARGET"
resolved="$(readlink -f "$path" 2>/dev/null || printf '%s' "$path")"
if command -v dpkg-query >/dev/null 2>&1; then
    line="$(dpkg-query -S "$path" 2>/dev/null | head -1)"
    [ -z "$line" ] && line="$(dpkg-query -S "$resolved" 2>/dev/null | head -1)"
    owner="$(printf '%s' "$line" | sed 's/: \/.*$//' | sed 's/:.*$//')"
    if [ -n "$owner" ]; then
        version="$(dpkg-query -W -f='${Version}' "$owner" 2>/dev/null)"
        printf '%s\t%s\n' "$owner" "$version"
    fi
elif command -v rpm >/dev/null 2>&1; then
    owner="$(rpm -qf --qf '%{NAME}' "$resolved" 2>/dev/null)"
    version="$(rpm -qf --qf '%{VERSION}-%{RELEASE}' "$resolved" 2>/dev/null)"
    [ -n "$owner" ] && printf '%s\t%s\n' "$owner" "$version"
elif command -v apk >/dev/null 2>&1; then
    line="$(apk info --who-owns "$resolved" 2>/dev/null | head -1)"
    owner="$(printf '%s' "$line" | awk '{print $1}')"
    version="$(apk info -v "$owner" 2>/dev/null | head -1)"
    [ -n "$owner" ] && printf '%s\t%s\n' "$owner" "$version"
fi
'''
        try:
            p = self._run(
                ["docker", "run", "--rm", "-e", f"GUI_TARGET={exe_path}", "--entrypoint", "sh", image, "-lc", script],
                timeout=8,
            )
            lines = [x for x in ((p.stdout or "") + (p.stderr or "")).splitlines() if x.strip()]
            if lines:
                parts = lines[0].split("\t", 1)
                if len(parts) == 2:
                    return parts[0].strip(), parts[1].strip()
        except Exception:
            pass
        return "", ""

    def _probe_one_executable(self, image, exe_name, exe_path, existing_version=""):
        package_name, package_version = self._package_version_for_executable(image, exe_path)
        fallback = package_version or existing_version or ""

        candidates = [
            ["--version"],
            ["-version"],
            ["-V"],
            ["-v"],
            ["version"],
            ["--help"],
            ["-h"],
            [],
        ]
        for args in candidates:
            try:
                p = self._run(
                    ["docker", "run", "--rm", "--entrypoint", exe_path, image] + args,
                    timeout=4,
                )
                raw = (p.stdout or "") + (p.stderr or "")
                candidate = self._extract_version_candidate(raw, p.returncode)
                if candidate:
                    return candidate, "runtime", package_name, package_version
            except subprocess.TimeoutExpired:
                continue
            except Exception:
                continue

        if fallback:
            return fallback, "package", package_name, package_version
        return "", "none", package_name, package_version

    def probe_selected_version(self):
        sel = list(self.inventory_tree.selection())
        if not sel:
            messagebox.showwarning("Version probe", "Select one or more executable rows first.")
            return

        targets = []
        skipped = 0
        seen_paths = set()
        for iid in sel:
            values = self.inventory_tree.item(iid, "values")
            if not values or len(values) < 4 or values[0] != "Executable":
                skipped += 1
                continue
            exe_name = str(values[1]).strip()
            existing_version = str(values[2]).strip()
            exe_path = str(values[3]).strip()
            if not exe_path or exe_path in seen_paths:
                continue
            seen_paths.add(exe_path)
            targets.append((exe_name, exe_path, existing_version))

        if not targets:
            messagebox.showwarning(
                "Version probe",
                "None of the selected rows are executable entries.\n\n"
                "OS, Python and R package rows already use their package versions.",
            )
            return

        rec = self._selected_record()
        if not rec:
            return
        metadata = rec.get("metadata") or self._read_sidecar(rec["path"])
        image = rec["tags"][0] if rec.get("tags") else metadata.get("docker_tag", "")
        if not image or not self._image_exists(image):
            if not self._load_archive(rec, "inspection"):
                return
            image = rec["tags"][0] if rec.get("tags") else metadata.get("docker_tag", "")
        if not image:
            messagebox.showerror("Version probe", "No Docker tag is available for this archive.")
            return

        count = len(targets)
        self._log(f"Probing versions for {count} selected executable(s).\n")
        if skipped:
            self._log(f"Skipped {skipped} selected non-executable row(s).\n")

        def work():
            results = []
            for index, (exe_name, exe_path, existing_version) in enumerate(targets, 1):
                self.after(0, lambda n=exe_name, i=index, total=count: self._log(f"[{i}/{total}] Probing: {n}\n"))
                version, source, package_name, package_version = self._probe_one_executable(
                    image, exe_name, exe_path, existing_version
                )
                results.append({
                    "name": exe_name,
                    "path": exe_path,
                    "version": version,
                    "version_source": source,
                    "package": package_name,
                    "package_version": package_version,
                })

            def finish():
                metadata_now = (dict(rec.get("metadata") or {}) if rec.get("tag_only") else self._read_sidecar(rec["path"]))
                inspection = metadata_now.get("inspection") if isinstance(metadata_now.get("inspection"), dict) else {}
                executables = inspection.get("executables") if isinstance(inspection.get("executables"), list) else []
                by_path = {str(item.get("path", "")): item for item in executables}

                detected = 0
                package_fallbacks = 0
                not_detected = 0
                for result in results:
                    item = by_path.get(result["path"])
                    if item is not None:
                        if result["version"]:
                            item["version"] = result["version"]
                            item["version_source"] = result["version_source"]
                        if result["package"]:
                            item["package"] = result["package"]
                        if result["package_version"]:
                            item["package_version"] = result["package_version"]

                    if result["version_source"] == "runtime":
                        detected += 1
                        self._log(f"  {result['name']}: {result['version']}\n")
                    elif result["version_source"] == "package":
                        package_fallbacks += 1
                        self._log(f"  {result['name']}: {result['version']}  [package version]\n")
                    else:
                        not_detected += 1
                        self._log(f"  {result['name']}: version not detected\n")

                inspection["schema"] = 6
                metadata_now["inspection"] = inspection
                probes = self._persistent_version_probes(metadata_now)
                for result in results:
                    if not result["version"]:
                        continue
                    probes[result["path"]] = {
                        "name": result["name"],
                        "version": result["version"],
                        "version_source": result["version_source"] or "saved",
                        "package": result["package"],
                        "package_version": result["package_version"],
                    }
                metadata_now["version_probes"] = probes
                self._apply_persistent_versions(metadata_now, inspection)
                if not rec.get("tag_only"):
                    try:
                        self._sidecar_path(rec["path"]).write_text(json.dumps(metadata_now, indent=2), encoding="utf-8")
                    except Exception as e:
                        self._log(f"WARNING: could not save probed versions: {e}\n")

                rec["metadata"] = metadata_now
                self._show_record_inventory(rec)
                self._log(("Version probes saved in project state (save the project JSON to keep them).\n" if rec.get("tag_only") else f"Saved version probes permanently in: {self._sidecar_path(rec['path'])}\n"))
                summary = (
                    f"Selected executables: {count}\n"
                    f"Runtime versions detected: {detected}\n"
                    f"Package-version fallbacks: {package_fallbacks}\n"
                    f"No version detected: {not_detected}"
                )
                self._log(summary.replace("\n", " | ") + "\n")
                messagebox.showinfo("Version probing complete", summary)

            self.after(0, finish)

        threading.Thread(target=work, daemon=True).start()

    def _inspection_script(self):
        return r'''clean_one_line() {
    tr '\t\r\n' '   ' | sed 's/|/\//g' | sed 's/  */ /g'
}

printf 'SCAN_STAGE\tIdentify operating system\n' >&2
os_name="$(awk -F= '/^PRETTY_NAME=/{v=$2; gsub(/^"|"$/, "", v); print v; exit}' /etc/os-release 2>/dev/null)"
[ -z "$os_name" ] && os_name="$(uname -s 2>/dev/null)"
printf 'SYS\tos\t%s\n' "$(printf '%s' "$os_name" | clean_one_line)"
printf 'SYS\tarchitecture\t%s\n' "$(uname -m 2>/dev/null | clean_one_line)"
printf 'SYS\tkernel\t%s\n' "$(uname -r 2>/dev/null | clean_one_line)"
printf 'SYS\tglibc\t%s\n' "$(ldd --version 2>&1 | head -1 | clean_one_line)"

pm="none"
command -v dpkg-query >/dev/null 2>&1 && pm="dpkg"
[ "$pm" = "none" ] && command -v rpm >/dev/null 2>&1 && pm="rpm"
[ "$pm" = "none" ] && command -v apk >/dev/null 2>&1 && pm="apk"
printf 'SYS\tpackage_manager\t%s\n' "$pm"

if command -v java >/dev/null 2>&1 && command -v timeout >/dev/null 2>&1; then
    java_banner="$(timeout 6 java -version 2>&1 | head -n 1)"
    if [ -n "$java_banner" ]; then
        printf 'SYS\tjava_version\t%s\n' "$(printf '%s' "$java_banner" | clean_one_line)"
        printf 'SYS\tjava_executable\t%s\n' "$(command -v java)"
    fi
fi

printf 'SCAN_STAGE\tSearch executable files\n' >&2
exec_tmp="/tmp/gui_all_executables.$$"
: > "$exec_tmp"
for d in /bin /sbin /usr/bin /usr/sbin /usr/local/bin /usr/local/sbin /opt; do
    if [ -d "$d" ]; then
        printf 'SCAN_DETAIL\tSearching %s\n' "$d" >&2
        if [ "$d" = "/opt" ]; then
            depth=8
        else
            depth=4
        fi
        if [ "$d" = "/opt" ] && command -v timeout >/dev/null 2>&1; then
            timeout 12 find "$d" -maxdepth "$depth" \( -type f -o -type l \) -print 2>/dev/null
        else
            find "$d" -maxdepth "$depth" \( -type f -o -type l \) -print 2>/dev/null
        fi | while IFS= read -r f; do
            [ -x "$f" ] && printf '%s\n' "$f"
        done >> "$exec_tmp"
    fi
done
sort -u "$exec_tmp" 2>/dev/null > "$exec_tmp.sorted"
exec_total="$(wc -l < "$exec_tmp.sorted" | tr -d ' ')"
printf 'SCAN_TOTAL\tEXEC\t%s\n' "$exec_total"
while IFS= read -r exe_path; do
    [ -n "$exe_path" ] || continue
    exe_name="${exe_path##*/}"
    printf 'EXEC\t%s\t%s\t\t\n' "$exe_name" "$exe_path"
done < "$exec_tmp.sorted"
rm -f "$exec_tmp" "$exec_tmp.sorted"

printf 'SCAN_STAGE\tRead installed system packages\n' >&2
pkg_tmp="/tmp/gui_installed_packages.$$"
: > "$pkg_tmp"
if [ "$pm" = "dpkg" ]; then
    dpkg-query -W -f='PKG\tOS\t${binary:Package}\t${Version}\n' > "$pkg_tmp" 2>/dev/null || true
elif [ "$pm" = "rpm" ]; then
    rpm -qa --qf 'PKG\tOS\t%{NAME}\t%{VERSION}-%{RELEASE}\n' > "$pkg_tmp" 2>/dev/null || true
elif [ "$pm" = "apk" ]; then
    apk info -v 2>/dev/null | while IFS= read -r line; do printf 'PKG\tOS\t%s\t\n' "$line"; done > "$pkg_tmp"
fi
pkg_total="$(wc -l < "$pkg_tmp" | tr -d ' ')"
printf 'SCAN_TOTAL\tPKG\t%s\n' "$pkg_total"
cat "$pkg_tmp"
rm -f "$pkg_tmp"

printf 'SCAN_STAGE\tRead Python packages\n' >&2
if command -v timeout >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
    timeout 8 python3 -m pip list --format=freeze 2>/dev/null | while IFS= read -r line; do
        [ -n "$line" ] && printf 'PIP\t%s\n' "$line"
    done
elif command -v timeout >/dev/null 2>&1 && command -v python >/dev/null 2>&1; then
    timeout 8 python -m pip list --format=freeze 2>/dev/null | while IFS= read -r line; do
        [ -n "$line" ] && printf 'PIP\t%s\n' "$line"
    done
fi

printf 'SCAN_STAGE\tRead R packages\n' >&2
if command -v Rscript >/dev/null 2>&1 && command -v timeout >/dev/null 2>&1; then
    timeout 8 Rscript --vanilla -e 'ip <- installed.packages()[,c("Package","Version"),drop=FALSE]; apply(ip,1,function(x) cat("RPKG\t",x[1],"\t",x[2],"\n",sep=""))' 2>/dev/null || true
fi

printf 'SCAN_STAGE\tIndex application JAR files\n' >&2
if command -v timeout >/dev/null 2>&1; then
    timeout 18 find /opt /usr -maxdepth 8 -type f -name '*.jar' -print 2>/dev/null
else
    find /opt /usr -maxdepth 6 -type f -name '*.jar' -print 2>/dev/null
fi | sort -u | while IFS= read -r jar; do
    printf 'JAR\t%s\n' "$jar"
done
'''

    def _parse_inspection_output(self, text, image):
        system = {}
        executables = []
        packages = {"os": [], "python": [], "r": [], "jars": []}
        seen_executables = set()

        package_metadata = {}
        for raw in text.splitlines():
            parts = raw.split("\t")
            if not parts:
                continue
            prefix = parts[0]
            if prefix == "SYS" and len(parts) >= 3:
                system[parts[1]] = "\t".join(parts[2:]).strip()
            elif prefix == "EXEC" and len(parts) >= 3:
                name = parts[1].strip()
                path = parts[2].strip()
                version = parts[3].strip() if len(parts) >= 4 else ""
                package = parts[4].strip() if len(parts) >= 5 else ""
                key = (name.lower(), path)
                if key not in seen_executables:
                    seen_executables.add(key)
                    executables.append({"name": name, "version": version, "path": path, "package": package})
            elif prefix == "PKG" and len(parts) >= 4:
                packages["os"].append({"name": parts[2].strip(), "version": "\t".join(parts[3:]).strip()})
            elif prefix in ("PKGREQ", "PKGPROVIDES") and len(parts) >= 3:
                owner = parts[1].strip().lower()
                value = "\t".join(parts[2:]).strip()
                if owner and value:
                    key = "requires" if prefix == "PKGREQ" else "provides"
                    package_metadata.setdefault(owner, {}).setdefault(key, []).append(value)
            elif prefix == "PIP" and len(parts) >= 2:
                value = "\t".join(parts[1:]).strip()
                if "==" in value:
                    name, version = value.split("==", 1)
                else:
                    name, version = value, ""
                packages["python"].append({"name": name.strip(), "version": version.strip()})
            elif prefix == "RPKG" and len(parts) >= 3:
                packages["r"].append({"name": parts[1].strip(), "version": "\t".join(parts[2:]).strip()})
            elif prefix == "JAR" and len(parts) >= 2:
                packages["jars"].append("\t".join(parts[1:]).strip())

        executables.sort(key=lambda x: (x["name"].lower(), x["path"].lower()))
        for item in packages["os"]:
            item.update(package_metadata.get(item["name"].lower(), {}))
        packages["os"].sort(key=lambda x: x["name"].lower())
        packages["python"].sort(key=lambda x: x["name"].lower())
        packages["r"].sort(key=lambda x: x["name"].lower())
        packages["jars"] = sorted(dict.fromkeys(packages["jars"]), key=str.lower)

        return {
            "schema": 6,
            "inspected_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "docker_tag": image,
            "system": system,
            "executables": executables,
            "packages": packages,
        }

    def save_selected_image_to_tar(self):
        if self._image_export_busy:
            return
        rec = self._selected_record()
        if not rec:
            messagebox.showerror('Save Docker TAR', 'Select a runtime or builder image in Tab 1.', parent=self)
            return
        image = str((rec.get('tags') or [''])[0] or '').strip()
        if not image:
            messagebox.showerror('Save Docker TAR', 'The selected image has no Docker tag.', parent=self)
            return
        directory = str(self.app.state.get('export_image_dir') or '').strip()
        if not Path(directory).is_dir():
            directory = str(Path.cwd())
        filename = re.sub(r'[^A-Za-z0-9_.-]', '_', image) + '_FULL.tar'
        chosen = filedialog.asksaveasfilename(
            parent=self, title='Save complete Docker image to TAR', initialdir=directory,
            initialfile=filename, defaultextension='.tar',
            filetypes=[('Docker image TAR', '*.tar'), ('All files', '*.*')],
        )
        if not chosen:
            return
        if Path(chosen).suffix.lower() != '.tar':
            chosen += '.tar'
        overwrite = Path(chosen).exists()
        if overwrite and not messagebox.askyesno('Overwrite existing image archive',
                'Replace this TAR with the selected Docker image after verifying the export?\n\n'
                + str(chosen), parent=self):
            return
        self._image_export_busy = True
        self.image_save_button.configure(state='disabled')
        self._log(f'Saving complete Docker image {image} to {chosen}\n')

        def worker():
            try:
                result = save_full_image_to_tar(image, chosen, overwrite=overwrite)
                error = ''
            except Exception as exc:
                result = None
                error = str(exc)
            def finish():
                self._image_export_busy = False
                self.image_save_button.configure(state='normal')
                if error:
                    self._log('TAR export FAILED: ' + error + '\n')
                    messagebox.showerror('Docker TAR export failed', error, parent=self)
                else:
                    self._log('COMPLETE Docker TAR saved: ' + result['archive'] + '\n')
                    self.app.state['last_saved_full_tar'] = result['archive']
                    messagebox.showinfo('Docker TAR saved',
                            'Saved the complete image without rebuilding.\n\n' + result['archive'], parent=self)
            try:
                self.after(0, finish)
            except RuntimeError:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _scan_message(self, phase):
        if not self._inspection_active:
            return
        phases = {
            'Read saved image manifest': 0,
            'Create temporary inspection container (not started)': 0,
            'Export image filesystem for inspection': 1,
            'Identify operating system': 2,
            'Read installed system packages': 3,
            'Search executable files': 4,
            'Read Python packages': 5,
            'Read R packages': 6,
            'Index application JAR files': 7,
        }
        self._inspection_phase = str(phase).strip() or self._inspection_phase
        layer = re.search(r'^Read image filesystem layer (\d+)/(\d+)$', self._inspection_phase)
        if layer:
            self._inspection_stage_index = 1
            self._inspection_layer = (int(layer.group(1)), int(layer.group(2)))
        else:
            self._inspection_stage_index = phases.get(self._inspection_phase, self._inspection_stage_index)
        self._inspection_last_update = time.monotonic()
        self._scan_detail = ''
        self._log('Scan stage: ' + self._inspection_phase + '\n')

    def _scan_emit(self, kind, value):
        if kind == 'stage':
            self.after(0, lambda v=value: self._scan_message(v))
        elif kind == 'detail':
            with self._scan_data_lock:
                self._scan_detail = str(value)
                self._inspection_last_update = time.monotonic()
        elif kind == 'total':
            self._read_scan_event('SCAN_TOTAL\t%s\t%s' % (value[0], value[1]))
        elif kind == 'item':
            item = tuple(str(v) for v in value)
            if item[0] == 'PKG':
                self._read_scan_event('PKG\tOS\t%s\t%s' % (item[1], item[2]))
            elif item[0] == 'EXEC':
                self._read_scan_event('EXEC\t%s\t%s\t\t' % (item[1], item[2]))
            elif item[0] in ('PIP', 'RPKG', 'JAR'):
                self._read_scan_event(item[0] + '\t' + '\t'.join(item[1:]))

    def _read_scan_event(self, line):
        parts = line.rstrip('\r\n').split('\t')
        if not parts:
            return
        kind = parts[0]
        with self._scan_data_lock:
            if kind == 'SCAN_TOTAL' and len(parts) >= 3:
                try:
                    self._scan_totals[parts[1]] = max(0, int(parts[2]))
                except ValueError:
                    pass
                return
            if kind not in self._scan_counts:
                return
            self._scan_counts[kind] += 1
            if kind == 'PKG' and len(parts) >= 4:
                detail = parts[2].strip() + ' ' + parts[3].strip()
                self._scan_recent_packages.append(detail.strip())
                self._scan_recent_packages = self._scan_recent_packages[-12:]
                self._scan_last_name = detail.strip()
            elif kind == 'EXEC' and len(parts) >= 3:
                self._scan_last_name = parts[1].strip()
            elif kind in ('PIP', 'RPKG', 'JAR'):
                self._scan_last_name = parts[1].strip() if len(parts) > 1 else ''
        self._inspection_last_update = time.monotonic()

    def _scan_clock(self):
        if not self._inspection_active:
            return
        elapsed = int(time.monotonic() - self._inspection_start)
        quiet = int(time.monotonic() - self._inspection_last_update)
        with self._scan_data_lock:
            counts = dict(self._scan_counts)
            totals = dict(self._scan_totals)
            recent = list(self._scan_recent_packages)
            self._scan_recent_packages.clear()
            latest = self._scan_last_name
        with self._scan_data_lock:
            detail = self._scan_detail
        stage = self._inspection_stage_index
        target_kind = {3: 'PKG', 4: 'EXEC'}.get(stage)
        completed = 0.0
        if target_kind and totals.get(target_kind, 0):
            completed = min(1.0, counts[target_kind] / totals[target_kind])
        layer_progress = 0
        if stage == 1 and self._inspection_layer[1] > 0:
            layer_progress = int(max(0, self._inspection_layer[0] - 1) / self._inspection_layer[1] * 100)
        self.scan_progress['value'] = min(799, stage * 100 + max(int(completed * 100), layer_progress))
        extra = f' | {target_kind}: {counts[target_kind]}/{totals[target_kind]}' if target_kind and target_kind in totals else ''
        if detail:
            extra += ' | ' + detail
        waiting = f' | No new results for {quiet}s' if quiet >= 10 else ''
        self.scan_status.set(
            f'Stage {stage + 1}/8: {self._inspection_phase} | '
            f'{elapsed // 60:02d}:{elapsed % 60:02d} elapsed{extra}{waiting}')
        tally = (f'Found {counts["PKG"]} OS packages, {counts["EXEC"]} executables, '
                 f'{counts["PIP"]} Python packages, {counts["RPKG"]} R packages, '
                 f'{counts["JAR"]} JARs.')
        if recent:
            newly_detected = counts['PKG'] - self._scan_previous_package_count
            self._scan_previous_package_count = counts['PKG']
            self.scan_found_text.set(tally +
                f'\n{newly_detected} new OS packages in this update; latest: ' + ', '.join(recent[-6:]))
            self._log(f'Packages discovered: {counts["PKG"]}' +
                      (' / ' + str(totals['PKG']) if 'PKG' in totals else '') +
                      ' | Recent: ' + ', '.join(recent[-6:]) + '\n')
        elif latest:
            self.scan_found_text.set(tally + '\nMost recent item: ' + latest)
        else:
            self.scan_found_text.set(tally + '\nWaiting for Docker to report the next item...')
        self.after(1000, self._scan_clock)

    def cancel_inspection(self):
        if not self._inspection_active:
            return
        self._inspection_cancel.set()
        self._inspection_phase = "Cancelling Docker scan"
        self.scan_stop.configure(state="disabled")
        self.scan_status.set("Cancelling scan — existing image remains unchanged")

    def _finish_scan_ui(self):
        self._inspection_active = False
        self._inspection_target = ''
        self._inspection_process = None
        self.scan_progress['value'] = 800 if getattr(self, '_inspection_succeeded', False) else self.scan_progress['value']
        self.scan_stop.configure(state="disabled")

    def _run_live_inspection(self, args, script, timeout=150):
        normalized = str(script).replace("\r\n", "\n").replace("\r", "\n")
        command = list(args)
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, bufsize=0,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self._inspection_process = process
        output = []
        errors = []
        def reader(pipe, sink, stages=False):
            try:
                for raw in iter(pipe.readline, b''):
                    line = raw.decode('utf-8', errors='replace')
                    if stages and line.startswith('SCAN_STAGE\t'):
                        phase = line.split('\t', 1)[1].strip()
                        try:
                            self.after(0, lambda value=phase: self._scan_message(value))
                        except RuntimeError:
                            pass
                    elif stages and line.startswith('SCAN_DETAIL\t'):
                        detail = line.split('\t', 1)[1].strip()
                        try:
                            self.after(0, lambda value=detail: setattr(self, '_scan_detail', value))
                        except RuntimeError:
                            pass
                    else:
                        if not stages:
                            self._read_scan_event(line)
                        sink.append(line)
            finally:
                pipe.close()
        out_thread = threading.Thread(target=reader, args=(process.stdout, output), daemon=True)
        err_thread = threading.Thread(target=reader, args=(process.stderr, errors, True), daemon=True)
        out_thread.start()
        err_thread.start()
        def send():
            try:
                process.stdin.write(normalized.encode('utf-8'))
                process.stdin.flush()
            except (OSError, ValueError, BrokenPipeError):
                pass
            finally:
                try:
                    process.stdin.close()
                except (OSError, ValueError):
                    pass
        writer = threading.Thread(target=send, daemon=True)
        writer.start()
        end = time.monotonic() + timeout
        timed_out = False
        try:
            while process.poll() is None:
                if self._inspection_cancel.is_set() or time.monotonic() >= end:
                    timed_out = not self._inspection_cancel.is_set()
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    break
                time.sleep(0.15)
            process.wait(timeout=5)
            draining = 0.15 if (timed_out or self._inspection_cancel.is_set()) else 2
            out_thread.join(timeout=draining)
            err_thread.join(timeout=draining)
            if self._inspection_cancel.is_set():
                raise InterruptedError('Docker image inspection was cancelled. The previous verified inventory remains unchanged.')
            if timed_out:
                raise subprocess.TimeoutExpired(command, timeout)
            return subprocess.CompletedProcess(command, process.returncode, ''.join(output), ''.join(errors))
        finally:
            if process.poll() is None:
                process.kill()
            self._inspection_process = None

    def _inspection_record(self, rec, force=False):
        if self._inspection_active:
            messagebox.showinfo('Inspect base', 'The current Docker image inspection is still running. Wait for its results.', parent=self)
            return
        metadata = rec.get("metadata") or self._read_sidecar(rec["path"])
        rec["metadata"] = metadata
        cached = metadata.get("inspection") if isinstance(metadata.get("inspection"), dict) else {}
        archive_cache_valid = False
        if not rec.get('tag_only') and rec.get('path'):
            try:
                archive_stat = Path(rec['path']).stat()
                stamp = (rec.get('metadata') or {}).get('archive_stamp') or {}
                archive_cache_valid = stamp.get('size') == archive_stat.st_size and stamp.get('mtime_ns') == archive_stat.st_mtime_ns
            except OSError:
                pass
        if not force and self._has_complete_inspection(cached) and (
                archive_cache_valid or
                (rec.get('tag_only') and cached.get('image_id') == self._docker_image_id(rec['tags'][0]))):
            self._show_record_inventory(rec)
            return

        image = rec["tags"][0] if rec.get("tags") else metadata.get("docker_tag", "")
        archive = Path(str(rec.get('path') or '')) if not rec.get('tag_only') else None
        if archive is None or not archive.is_file():
            if not image or not self._image_exists(image):
                messagebox.showerror('Inspect image',
                                     'The Docker image is not loaded. Use the single Load Docker image from TAR button in Tab 1.',
                                     parent=self)
                return
        elif not image:
            messagebox.showerror('Inspect image', 'The TAR has no selected image tag. Load it through Tab 1 first.', parent=self)
            return
        image_id = self._docker_image_id(image)
        if archive is None and not image_id:
            messagebox.showerror('Inspect image', 'Docker could not identify the selected image. Load it through Tab 1.', parent=self)
            return

        self._inspection_active = True
        self._inspection_target = image
        self._inspection_cancel = threading.Event()
        self._inspection_start = time.monotonic()
        self._inspection_last_update = self._inspection_start
        self._inspection_succeeded = False
        self._scan_previous_package_count = 0
        with self._scan_data_lock:
            self._scan_counts = {'EXEC': 0, 'PKG': 0, 'PIP': 0, 'RPKG': 0, 'JAR': 0}
            self._scan_totals = {}
            self._scan_recent_packages = []
            self._scan_last_name = ''
            self._scan_detail = ''
        self._inspection_phase = 'Read saved image manifest' if archive is not None else 'Prepare Docker filesystem export'
        self._inspection_stage_index = 0
        self._inspection_layer = (0, 0)
        self.scan_stop.configure(state='normal')
        self.scan_progress['value'] = 0
        self._scan_clock()
        self.out.delete("1.0", "end")
        self._log(f"Inspecting base image: {image}\nSource: {rec['path'] or 'Docker tag (no TAR required)'}\n\n")
        self._log('Reading the saved TAR filesystem directly, or using Docker export without starting an application.\n')
        self.inventory_summary.set(f"INSPECTION IN PROGRESS: {image}\nThe runtime contents have not yet been verified. Do not interpret missing results as an empty image.")
        self.inventory_tree.delete(*self.inventory_tree.get_children())
        self.inventory_tree.insert('', 'end', values=('', '<scanning Docker image; wait for completion>', '', ''))

        script = self._inspection_script()

        def work():
            try:
                if archive is not None and archive.is_file():
                    result = inspect_saved_tar(archive, image=image, report=self._scan_emit,
                                               cancel=self._inspection_cancel, timeout=300)
                    if not result.get('image_id'):
                        raise RuntimeError('The saved TAR has no identifiable Docker image configuration.')
                else:
                    result = inspect_tag_via_export(image, report=self._scan_emit,
                                                    cancel=self._inspection_cancel, timeout=300)
                if not self._has_complete_inspection(result):
                    raise RuntimeError('The filesystem inspection did not produce valid inventory metadata.')
                if archive is None:
                    result['image_id'] = image_id
                error = ''
            except (InterruptedError, InspectionCancelled, InspectionTimeout) as exc:
                result = None
                error = str(exc)
            except subprocess.TimeoutExpired:
                result = None
                error = 'Docker image preparation exceeded its timeout. The previous inventory remains unchanged.' 
            except Exception as e:
                result = None
                error = str(e)[:1000]

            def finish():
                self._inspection_succeeded = result is not None
                self._finish_scan_ui()
                if result is None:
                    self.scan_status.set('Inspection stopped or failed. Installed software not verified.')
                    self._log(error + "\n")
                    previous = (rec.get("metadata") or {}).get("inspection")
                    if self._has_complete_inspection(previous) and previous.get("image_id") == image_id:
                        self._show_record_inventory(rec)
                        self._log("Inspection failed; the previously verified inventory of this image remains visible.\n")
                    else:
                        self.inventory_summary.set("INSPECTION FAILED. Installed programs are UNKNOWN, not absent. See the activity log.")
                        self.inventory_tree.delete(*self.inventory_tree.get_children())
                        self.inventory_tree.insert('', 'end', values=('', '<inspection failed; installed software unknown>', '', ''))
                    return
                selected_tag = str(self.app.state.get('base_image' if rec.get('role') == 'runtime' else 'builder_image') or '').strip()
                if rec.get('tag_only') and selected_tag != image:
                    self._log('Inspection completed for an image no longer selected. Results were discarded: ' + image + '\n')
                    return
                local_id = self._docker_image_id(image)
                actual_id = result.get('image_id', '')
                if rec.get('tag_only') and local_id != image_id:
                    self._log('The Docker tag changed during inspection; results were discarded. Refresh the inventory again.\n')
                    self.inventory_summary.set('Image tag changed during inspection. Run Inspect / refresh selected again.')
                    return
                archive_not_loaded = False
                if archive is not None:
                    try:
                        archive_not_loaded = not docker_image_matches_tar(archive, image, cancel=self._inspection_cancel)
                    except (ValueError, OSError, tarfile.TarError, RuntimeError) as check_error:
                        archive_not_loaded = True
                        self._log('Image identity check could not be completed: ' + str(check_error) + '\n')
                if archive_not_loaded:
                    self._log('WARNING: The TAR inventory was read successfully, but its image is not loaded under the selected Docker tag. '
                              'Load the TAR using Tab 1 before trying to build from it.\n')

                metadata_now = (dict(rec.get("metadata") or {}) if rec.get("tag_only") else self._read_sidecar(rec["path"]))
                probes = self._persistent_version_probes(metadata_now)
                metadata_now["version_probes"] = probes
                self._apply_persistent_versions(metadata_now, result)
                metadata_now["docker_tag"] = image
                metadata_now["os"] = result.get("system", {}).get("os", metadata_now.get("os", ""))
                metadata_now["architecture"] = result.get("system", {}).get("architecture", metadata_now.get("architecture", ""))
                metadata_now["inspection"] = result
                if not rec.get("tag_only"):
                    try:
                        archive_stat = Path(rec["path"]).stat()
                        metadata_now['archive_stamp'] = {'size': archive_stat.st_size, 'mtime_ns': archive_stat.st_mtime_ns}
                        self._sidecar_path(rec["path"]).write_text(json.dumps(metadata_now, indent=2), encoding="utf-8")
                    except Exception as e:
                        self._log(f"WARNING: could not update metadata sidecar: {e}\n")

                rec["metadata"] = metadata_now
                self._show_record_inventory(rec)
                duration = int(time.monotonic() - self._inspection_start)
                self.scan_status.set(
                    f'Inspection complete in {duration}s — '
                    f'{len(result.get("executables", []))} executables, '
                    f'{len(result.get("packages", {}).get("os", []))} OS packages verified')
                if archive_not_loaded:
                    self.scan_status.set(self.scan_status.get() + ' | TAR INSPECTED, DOCKER TAG NOT MATCHED')
                    self.inventory_summary.set(self.inventory_summary.get() + '\nTAR contents inspected; load the TAR in Tab 1 before building.')
                self.scan_found_text.set(self.scan_status.get())
                self._log(
                    f"Inspection complete.\n"
                    f"Executable commands/files: {len(result.get('executables', []))}\n"
                    f"OS packages: {len(result.get('packages', {}).get('os', []))}\n"
                    f"Python packages: {len(result.get('packages', {}).get('python', []))}\n"
                    f"R packages: {len(result.get('packages', {}).get('r', []))}\n"
                    f"JAR files indexed: {len(result.get('packages', {}).get('jars', []))}\n" +
                    ("Inventory saved in project state. Save project JSON to preserve it.\n" if rec.get("tag_only") else f"Metadata saved to: {self._sidecar_path(rec['path'])}\n")
                )
                self.refresh_selected_archives()

            self.after(0, finish)

        threading.Thread(target=work, daemon=True).start()

    def inspect_selected_base(self):
        rec = self._selected_record()
        if not rec:
            messagebox.showwarning("Inspect base", "Select a runtime or builder Docker image in Tab 1.")
            return
        self._inspection_record(rec, force=False)

    def refresh_selected_inventory(self):
        rec = self._selected_record()
        if not rec:
            messagebox.showwarning("Inspect base", "Select a runtime or builder Docker image in Tab 1.")
            return
        self._inspection_record(rec, force=True)

    def show_full_package_list(self):
        rec = self._selected_record()
        if not rec:
            messagebox.showwarning("Package list", "Select a runtime or builder Docker image in Tab 1.")
            return

        metadata = rec.get("metadata") or self._read_sidecar(rec["path"])
        inspection = metadata.get("inspection") if isinstance(metadata.get("inspection"), dict) else {}
        packages = inspection.get("packages") if isinstance(inspection.get("packages"), dict) else {}
        if not packages:
            if messagebox.askyesno("Package list", "This base has not been inspected yet. Inspect it now?"):
                self._inspection_record(rec, force=True)
            return

        label = rec["tags"][0] if rec.get("tag_only") else Path(rec["path"]).name
        win = tk.Toplevel(self)
        win.title(f"Full software inventory — {label}")
        win.geometry("1050x760")
        win.configure(bg="#EAF2F8")

        tk.Label(
            win,
            text=f"Full software inventory — {label}",
            bg="#117864",
            fg="white",
            font=("Segoe UI", 13, "bold"),
            anchor="w",
            padx=10,
            pady=8,
        ).pack(fill="x")

        body = tk.Frame(win, bg="#EAF2F8")
        body.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        text = tk.Text(body, bg="white", font=("Consolas", 9), wrap="none")
        yscroll = ttk.Scrollbar(body, orient="vertical", command=text.yview)
        xscroll = ttk.Scrollbar(body, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        lines = []
        lines.append(f"=== EXECUTABLE COMMANDS / FILES ({len(inspection.get('executables', []))}) ===")
        for item in inspection.get("executables", []):
            lines.append(f"{item.get('name','')}\t{item.get('path','')}")
        lines.append("")
        lines.append(f"=== OS PACKAGES ({len(packages.get('os', []))}) ===")
        for item in packages.get("os", []):
            lines.append(f"{item.get('name','')}\t{item.get('version','')}")
        lines.append("")
        lines.append(f"=== PYTHON PACKAGES ({len(packages.get('python', []))}) ===")
        for item in packages.get("python", []):
            lines.append(f"{item.get('name','')}\t{item.get('version','')}")
        lines.append("")
        lines.append(f"=== R PACKAGES ({len(packages.get('r', []))}) ===")
        for item in packages.get("r", []):
            lines.append(f"{item.get('name','')}\t{item.get('version','')}")
        lines.append("")
        lines.append(f"=== JAR FILES ({len(packages.get('jars', []))}) ===")
        lines.extend(packages.get("jars", []))
        report = "\n".join(lines)
        text.insert("1.0", report)
        text.configure(state="disabled")

        def save_report():
            target = filedialog.asksaveasfilename(
                parent=win,
                defaultextension=".txt",
                filetypes=[("Text report", "*.txt")],
                initialfile=re.sub(r"[^A-Za-z0-9_.-]", "_", label) + "_full_inventory.txt",
            )
            if target:
                Path(target).write_text(report, encoding="utf-8")

        tk.Button(win, text="Save full inventory", bg="#117864", fg="white", command=save_report).pack(pady=(0, 10))

    def refresh_selected_archives(self):




        runtime_path = str(self.app.state.get("runtime_base_archive", "") or "").strip()
        using_runtime_as_builder = self.app.state.get("builder_mode") == "runtime"
        builder_path = "" if using_runtime_as_builder else str(self.app.state.get("builder_base_archive", "") or "").strip()
        selected_runtime_tag = str(self.app.state.get("base_image", "") or "").strip()
        selected_builder_tag = "" if using_runtime_as_builder else str(self.app.state.get("builder_image", "") or "").strip()
        self.runtime_display.set(runtime_path or ("Docker tag only: " + selected_runtime_tag if selected_runtime_tag else "(not selected — choose in Tab 0)"))
        self.builder_display.set(builder_path or ("Docker tag only: " + selected_builder_tag if selected_builder_tag else "(same as runtime)"))

        records = []
        missing = []
        for role, path in (("runtime", runtime_path), ("builder", builder_path)):
            if not path or any(self._path_equal(path, r["path"]) for r in records):
                continue
            archive = Path(path)
            if not archive.is_file() or archive.suffix.lower() != ".tar":
                missing.append((role, path))
                continue
            metadata = self._read_sidecar(archive)
            inspection = metadata.get("inspection") if isinstance(metadata.get("inspection"), dict) else {}
            if inspection:
                self._apply_persistent_versions(metadata, inspection)
            metadata_tag = str(metadata.get("docker_tag", "") or "").strip()
            selected_tag = (selected_runtime_tag if role == 'runtime' else selected_builder_tag)
            tags = [selected_tag] if selected_tag else ([metadata_tag] if metadata_tag else self._archive_tags(archive))
            records.append({"path": str(archive), "tags": tags, "size": archive.stat().st_size, "metadata": metadata})
        self._library_records = records

        runtime_rec = self._runtime_record()
        builder_rec = self._builder_record()
        if runtime_rec and not runtime_rec.get("tag_only"):
            self._apply_runtime_record(runtime_rec)
        else:
            runtime_tag = str(self.app.state.get("base_image", "") or "")
            self.runtime_tag.set(runtime_tag)
            if runtime_path:
                self.runtime_status.config(text="ARCHIVE MISSING", fg="#922B21")
            elif runtime_tag:
                exists = self._image_exists(runtime_tag)
                self.runtime_status.config(text="Docker tag — LOADED" if exists else "Docker tag — NOT LOADED",
                                           fg="#1E8449" if exists else "#B9770E")
            else:
                self.runtime_status.config(text="NOT SELECTED", fg="#922B21")
        if builder_path:
            if builder_rec:
                self._apply_builder_record(builder_rec)
            else:
                self.builder_tag.set(str(self.app.state.get("builder_image", "") or ""))
                self.builder_status.config(text="ARCHIVE MISSING", fg="#922B21")
        else:
            builder = effective_builder_image(self.app.state)
            self.builder_tag.set(builder)
            label = 'Separate builder Docker tag' if self.app.state.get('builder_mode') == 'separate' else 'Same as runtime'
            if builder and self._image_exists(builder):
                self.builder_status.config(text=label + ' — LOADED', fg="#1E8449")
            elif builder:
                self.builder_status.config(text=label + ' — NOT LOADED', fg="#B9770E")
            else:
                self.builder_status.config(text=label, fg="#566573")

        shown = self._selected_record()
        if shown:
            self._show_record_inventory(shown)
        else:
            self.inventory_tree.delete(*self.inventory_tree.get_children())
            self.inventory_summary.set("No selected Docker image is available. Select a runtime or builder in Tab 1.")
        self._update_role_summaries()
        for role, path in missing:
            self._log(f"WARNING: {role} archive chosen in Tab 1 cannot be found: {path}\n")

    def _apply_runtime_record(self, rec):
        if not self._path_equal(self.app.state.get("runtime_base_archive", ""), rec.get("path", "")):
            raise ValueError("Runtime archive can only be selected in Tab 1.")
        tag = rec["tags"][0] if rec["tags"] else ""
        self.runtime_tag.set(tag)

        metadata = rec.get("metadata") or self._read_sidecar(rec["path"])
        inspection = metadata.get("inspection") if isinstance(metadata.get("inspection"), dict) else {}
        
        
        if not inspection:
            saved_inventory = self.app.state.get("base_inventory", {})
            if isinstance(saved_inventory, dict):
                inspection = saved_inventory
        system = inspection.get("system", {}) if isinstance(inspection.get("system", {}), dict) else {}
        if not system:
            saved_system = self.app.state.get("base_system", {})
            if isinstance(saved_system, dict):
                system = saved_system

        if hasattr(self.app.state, "publish_base"):
            self.app.state.publish_base(
                archive=rec["path"],
                tag=tag,
                system=system,
                inventory=inspection,
            )
        else:
            self.app.state["runtime_base_archive"] = rec["path"]
            self.app.state["base_image"] = tag
            self.app.state["base_system"] = system
            self.app.state["base_inventory"] = inspection
            self._touch_shared_state("base")

        if tag:
            if self._image_exists(tag):
                self.runtime_status.config(text="LOADED", fg="#1E8449")
            else:
                self.runtime_status.config(text="external only", fg="#B9770E")
        else:
            self.runtime_status.config(text="tag unknown", fg="#922B21")

    def _apply_builder_record(self, rec):
        if not self._path_equal(self.app.state.get("builder_base_archive", ""), rec.get("path", "")):
            raise ValueError("Builder archive can only be selected in Tab 1.")
        tag = rec["tags"][0] if rec["tags"] else ""
        self.builder_tag.set(tag)
        metadata = rec.get("metadata") or self._read_sidecar(rec["path"])
        inspection = metadata.get("inspection") if isinstance(metadata.get("inspection"), dict) else {}
        if not inspection:
            saved_inventory = self.app.state.get("builder_inventory", {})
            if isinstance(saved_inventory, dict):
                inspection = saved_inventory
        system = inspection.get("system", {}) if isinstance(inspection.get("system", {}), dict) else {}
        if not system:
            saved_system = self.app.state.get("builder_system", {})
            if isinstance(saved_system, dict):
                system = saved_system
        if hasattr(self.app.state, "publish_builder"):
            self.app.state.publish_builder(archive=rec["path"], tag=tag, system=system, inventory=inspection)
        else:
            self.app.state["builder_base_archive"] = rec["path"]
            self.app.state["builder_image"] = tag
            self.app.state["builder_system"] = system
            self.app.state["builder_inventory"] = inspection
            self._touch_shared_state("builder_base")
        if tag:
            if self._image_exists(tag):
                self.builder_status.config(text="LOADED", fg="#1E8449")
            else:
                self.builder_status.config(text="external only", fg="#B9770E")
        else:
            self.builder_status.config(text="tag unknown", fg="#922B21")
        self._update_role_summaries()

    def _local_image_choices(self):
        p = self._run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Size}}"])
        rows = []
        for line in p.stdout.splitlines():
            if not line.strip() or "<none>" in line:
                continue
            parts = line.split("\t")
            tag = parts[0]
            image_id = parts[1] if len(parts) > 1 else ""
            size = parts[2] if len(parts) > 2 else ""
            rows.append((tag, image_id, size))
        return rows

    def _load_archive(self, rec, role):
        if not rec:
            messagebox.showerror('Base', f'No {role} archive was selected.', parent=self)
            return False
        archive = Path(rec.get('path') or '')
        if not archive.is_file():
            messagebox.showerror('Base', f'The selected archive does not exist: {archive}', parent=self)
            return False
        expected = (rec.get('tags') or [''])[0]
        if not expected:
            messagebox.showerror('Base', 'The selected TAR has no image tag. Load it in Tab 1.', parent=self)
            return False
        try:
            verified = docker_image_matches_tar(archive, expected)
        except (OSError, ValueError, RuntimeError, tarfile.TarError) as exc:
            self._log('Cannot verify the selected TAR: ' + str(exc) + '\n')
            verified = False
        if not verified:
            messagebox.showinfo('Docker image not loaded',
                                'Use the single Load Docker image from TAR button in Tab 1. '
                                'Tab 2 will not import or replace images automatically.', parent=self)
            return False
        if role == 'runtime':
            self.runtime_tag.set(expected)
            self.app.state['base_image'] = expected
            self.runtime_status.config(text='LOADED — VERIFIED', fg='#1E8449')
        elif role == 'builder':
            self.builder_tag.set(expected)
            self.app.state['builder_image'] = expected
            self.app.state['builder_mode'] = 'separate'
            self.builder_status.config(text='LOADED — VERIFIED', fg='#1E8449')
        self._log(f'{role.title()} TAR matches the Docker filesystem: {expected}\n')
        return True

    def load_selected_bases(self):
        runtime_path = str(self.app.state.get("runtime_base_archive", "") or "").strip()
        builder_path = "" if self.app.state.get("builder_mode") == "runtime" else str(self.app.state.get("builder_base_archive", "") or "").strip()
        if runtime_path:
            runtime_rec = self._find_record_by_path(runtime_path)
            if not self._load_archive(runtime_rec, "runtime"):
                return
        else:
            runtime_tag = str(self.app.state.get('base_image') or '').strip()
            if not runtime_tag or not self._image_exists(runtime_tag):
                messagebox.showerror('Runtime image', 'Choose a runtime archive in Tab 1 or select a Docker runtime image that is already loaded.')
                return
            self.runtime_tag.set(runtime_tag)
            self.runtime_status.config(text='Docker tag — LOADED', fg='#1E8449')
        if builder_path:
            builder_rec = self._find_record_by_path(builder_path)
            if not self._load_archive(builder_rec, "builder"):
                return
        else:
            builder = effective_builder_image(self.app.state)
            self.builder_tag.set(builder)
            separate = self.app.state.get('builder_mode') == 'separate'
            exists = bool(builder and self._image_exists(builder))
            self.builder_status.config(text=('Separate builder Docker tag' if separate else 'Same as runtime') +
                                       (' — LOADED' if exists else ' — NOT LOADED'),
                                       fg='#1E8449' if exists else '#B9770E')
        self._sync_prepare_to_state()

    def unload_gui_images(self):
        tags = list(self.app.state.get("gui_loaded_images", []))
        if not tags:
            messagebox.showinfo("Unload", "No images are recorded as having been loaded by this GUI.")
            return
        if not messagebox.askyesno("Unload", "Remove only Docker images that this GUI loaded temporarily?\n\n" + "\n".join(tags)):
            return
        self.out.delete("1.0", "end")
        remaining = []
        for tag in tags:
            p = self._run(["docker", "image", "rm", tag])
            self._log(f"$ docker image rm {tag}\n{p.stdout}{p.stderr}\n")
            if p.returncode != 0 and self._image_exists(tag):
                remaining.append(tag)
        self.app.state["gui_loaded_images"] = remaining
        self.refresh_selected_archives()
        if remaining:
            messagebox.showwarning("Unload", "Some GUI-loaded images could not be removed because Docker reports they are still referenced. See the log.")
        else:
            messagebox.showinfo("Unload", "GUI-loaded Docker images were removed. External TAR archives were not changed.")



if __name__ == "__main__":
    root = tk.Tk()
    root.title("Debug — BaseTab")
    root.geometry("1500x900")

    class DebugApp:
        pass

    app = DebugApp()
    app.state = {
        "project_dir": str(Path.cwd()),
        "runtime_base_archive": "",
        "builder_base_archive": "",
        "gui_loaded_images": [],
        "base_image": "",
        "builder_image": "",
        "base_prepare": "",
        "components": [],
        "payloads": [],
        "image_name": "",
        "generated_context": "",
        "generated_dockerfile": "",
    }
    tab = BaseTab(root, app)
    tab.pack(fill="both", expand=True)
    root.mainloop()
