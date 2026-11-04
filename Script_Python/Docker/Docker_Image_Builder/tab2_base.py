import json
import os
import re
import shlex
import subprocess
import tarfile
import threading
from datetime import datetime, timezone
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk


class BaseTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg="#EAF2F8")
        self.app = app
        self._library_records = []
        self._busy = False
        self._active_role = "runtime"

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
            text="2 — BASE INVENTORY / DOCKER IMAGE LOADING",
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
            text="Runtime and builder archives are selected ONLY in Tab 1 — Project / Base. "
                 "The paths below are read-only; Tab 2 loads images and inspects their contents.",
            bg="#D6EAF8", fg="#154360", justify="left", anchor="w", padx=10, pady=8,
        ).pack(side="left", fill="x", expand=True)
        selectors = tk.LabelFrame(
            self,
            text=" Runtime / builder selected in Tab 1 — READ ONLY ",
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
        tk.Button(
            base_buttons,
            text="Load selected bases into Docker",
            bg="#2E86C1",
            fg="white",
            command=self.load_selected_bases,
        ).pack(side="left", padx=3)
        tk.Button(
            base_buttons,
            text="Unload GUI-loaded bases",
            bg="#7B241C",
            fg="white",
            command=self.unload_gui_images,
        ).pack(side="left", padx=3)
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

        tk.Label(self.inventory_frame, text="Base contents / software inventory", bg="#EAF2F8", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        inventory_buttons = tk.Frame(self.inventory_frame, bg="#EAF2F8")
        inventory_buttons.pack(fill="x", pady=(4, 4))
        tk.Button(inventory_buttons, text="Show runtime", bg="#AED6F1", command=self.show_runtime_contents).pack(side="left", padx=(0, 3))
        tk.Button(inventory_buttons, text="Show builder", bg="#D7BDE2", command=self.show_builder_contents).pack(side="left", padx=3)
        tk.Button(
            inventory_buttons,
            text="Inspect / refresh selected",
            bg="#17A589",
            fg="white",
            command=self.refresh_selected_inventory,
        ).pack(side="left", padx=3)
        tk.Button(inventory_buttons, text="Full inventory", bg="#117864", fg="white", command=self.show_full_package_list).pack(side="left", padx=3)
        tk.Button(inventory_buttons, text="Probe version(s)", bg="#7D3C98", fg="white", command=self.probe_selected_version).pack(side="left", padx=3)

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
            ),
        )
        self.inventory_view_combo.pack(side="left", padx=(4, 8))
        self.inventory_view_combo.bind("<<ComboboxSelected>>", lambda e: self._populate_inventory_tree())
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

        tk.Label(self.analysis_frame, text="Base analysis / activity log", bg="#EAF2F8", font=("Segoe UI", 10, "bold")).pack(anchor="w")
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
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            **kwargs,
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
        return self._find_record_by_path(self.app.state.get("runtime_base_archive", ""))

    def _builder_record(self):
        builder_path = self.app.state.get("builder_base_archive", "")
        if not builder_path:
            return self._runtime_record()
        return self._find_record_by_path(builder_path)

    def _inventory_short_summary(self, rec):
        if not rec:
            return "not selected"
        metadata = rec.get("metadata") or self._read_sidecar(rec.get("path", ""))
        inspection = metadata.get("inspection") if isinstance(metadata.get("inspection"), dict) else {}
        if not inspection:
            return f"{Path(rec.get('path','')).name}: not inspected"
        system = inspection.get("system") if isinstance(inspection.get("system"), dict) else {}
        packages = inspection.get("packages") if isinstance(inspection.get("packages"), dict) else {}
        executables = inspection.get("executables") if isinstance(inspection.get("executables"), list) else []
        os_packages = packages.get("os", []) if isinstance(packages.get("os", []), list) else []
        return (f"{Path(rec.get('path','')).name}: {system.get('os','unknown')} | "
                f"{system.get('architecture','unknown')} | {len(executables)} executables | "
                f"{len(os_packages)} OS packages")

    def _update_role_summaries(self):
        runtime = self._runtime_record()
        builder_path = self.app.state.get("builder_base_archive", "")
        builder = self._builder_record()
        self.runtime_role_summary.set("Runtime contents: " + self._inventory_short_summary(runtime))
        if not builder_path:
            self.builder_role_summary.set("Builder contents: SAME AS RUNTIME — " + self._inventory_short_summary(runtime))
        else:
            self.builder_role_summary.set("Builder contents: " + self._inventory_short_summary(builder))

    def _display_selected_inventory(self, rec):
        if rec is None:
            return False
        self._show_record_inventory(rec)
        return True

    def show_runtime_contents(self):
        self._active_role = "runtime"
        rec = self._runtime_record()
        if not rec:
            messagebox.showwarning("Runtime base", "No runtime base archive is selected.")
            return
        self._display_selected_inventory(rec)

    def show_builder_contents(self):
        self._active_role = "builder"
        rec = self._builder_record()
        if not rec:
            messagebox.showwarning("Builder base", "No builder base archive is selected.")
            return
        self._display_selected_inventory(rec)

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
        if not tag:
            return False
        try:
            p = self._run(["docker", "image", "inspect", tag], timeout=8)
            return p.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _sidecar_path(self, archive_path):
        return Path(archive_path).with_suffix(".json")

    def _read_sidecar(self, archive_path):
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
        archive_name = Path(rec["path"]).name

        if inspection:
            os_name = system.get("os", metadata.get("os", "unknown"))
            arch = system.get("architecture", metadata.get("architecture", "unknown"))
            libc = system.get("glibc", "unknown")
            pm = system.get("package_manager", "unknown")
            inspected_at = inspection.get("inspected_at", "")
            total_entries = len(executables) + len(jars) + len(os_packages) + len(py_packages) + len(r_packages)
            self.inventory_summary.set(
                f"{archive_name}\n"
                f"Tag: {tag}   |   OS: {os_name}   |   Arch: {arch}\n"
                f"Software entries: {total_entries}   |   Executables: {len(executables)}   |   OS packages: {len(os_packages)}   |   JARs: {len(jars)}\n"
                f"Python packages: {len(py_packages)}   |   R packages: {len(r_packages)}   |   libc: {libc}   |   Package manager: {pm}\n"
                f"Inspection: {inspected_at or 'cached'}"
            )
            self._populate_inventory_tree(inspection)
            self._publish_runtime_inspection(rec, inspection)
            self._publish_builder_inspection(rec, inspection)
            self._update_role_summaries()
        else:
            self.inventory_tree.delete(*self.inventory_tree.get_children())
            os_name = metadata.get("os", "unknown")
            arch = metadata.get("architecture", "unknown")
            self.inventory_summary.set(
                f"{archive_name}\n"
                f"Tag: {tag}   |   OS: {os_name}   |   Arch: {arch}\n"
                "No cached software inventory. Click 'Inspect / refresh selected'."
            )

    def _populate_inventory_tree(self, inspection=None):
        self.inventory_tree.delete(*self.inventory_tree.get_children())
        if inspection is None:
            rec = self._selected_record()
            if not rec:
                return
            metadata = rec.get("metadata") or self._read_sidecar(rec["path"])
            inspection = metadata.get("inspection") if isinstance(metadata.get("inspection"), dict) else {}
            if inspection:
                self._apply_persistent_versions(metadata, inspection)
        if not inspection:
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

        view = self.inventory_view.get() if hasattr(self, "inventory_view") else "All software entries"
        query = self.inventory_search.get().strip().lower() if hasattr(self, "inventory_search") else ""
        view_map = {
            "Executables": {"Executable"},
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

        type_order = {"Executable": 0, "OS package": 1, "Python package": 2, "R package": 3, "JAR": 4}
        rows.sort(key=lambda r: (type_order.get(r["type"], 9), str(r["name"]).lower(), str(r["path"]).lower()))
        for i, row in enumerate(rows):
            self.inventory_tree.insert("", "end", iid=f"inv{i}", values=(row["type"], row["name"], row["version"], row["path"]))
        if not rows:
            self.inventory_tree.insert("", "end", values=("", "<no matching software entries>", "", ""))

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
                metadata_now = self._read_sidecar(rec["path"])
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
                try:
                    self._sidecar_path(rec["path"]).write_text(json.dumps(metadata_now, indent=2), encoding="utf-8")
                except Exception as e:
                    self._log(f"WARNING: could not save probed versions: {e}\n")

                rec["metadata"] = metadata_now
                self._show_record_inventory(rec)
                self._log(f"Saved version probes permanently in: {self._sidecar_path(rec['path'])}\n")
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

exec_tmp="/tmp/gui_all_executables.$$"
: > "$exec_tmp"
for d in /bin /sbin /usr/bin /usr/sbin /usr/local/bin /usr/local/sbin /opt; do
    if [ -d "$d" ]; then
        if [ "$d" = "/opt" ]; then
            depth=8
        else
            depth=4
        fi
        find "$d" -maxdepth "$depth" \( -type f -o -type l \) -print 2>/dev/null | while IFS= read -r f; do
            [ -x "$f" ] && printf '%s\n' "$f"
        done >> "$exec_tmp"
    fi
done
sort -u "$exec_tmp" 2>/dev/null | while IFS= read -r exe_path; do
    [ -n "$exe_path" ] || continue
    exe_name="$(basename "$exe_path" | clean_one_line)"
    resolved="$(readlink -f "$exe_path" 2>/dev/null || printf '%s' "$exe_path")"
    owner=""
    owner_version=""
    if [ "$pm" = "dpkg" ]; then
        owner_line="$(dpkg-query -S "$exe_path" 2>/dev/null | head -1)"
        [ -z "$owner_line" ] && owner_line="$(dpkg-query -S "$resolved" 2>/dev/null | head -1)"
        owner="$(printf '%s' "$owner_line" | cut -d: -f1 | clean_one_line)"
        [ -n "$owner" ] && owner_version="$(dpkg-query -W -f='${Version}' "$owner" 2>/dev/null | clean_one_line)"
    elif [ "$pm" = "rpm" ]; then
        owner="$(rpm -qf --qf '%{NAME}' "$resolved" 2>/dev/null | clean_one_line)"
        [ -n "$owner" ] && owner_version="$(rpm -qf --qf '%{VERSION}-%{RELEASE}' "$resolved" 2>/dev/null | clean_one_line)"
    elif [ "$pm" = "apk" ]; then
        owner_line="$(apk info --who-owns "$resolved" 2>/dev/null | head -1 | clean_one_line)"
        owner="$(printf '%s' "$owner_line" | awk '{print $1}')"
        [ -n "$owner" ] && owner_version="$(apk info -e "$owner" 2>/dev/null && apk info -v "$owner" 2>/dev/null | head -1 | sed 's/^.*-//' | clean_one_line)"
    fi
    printf 'EXEC\t%s\t%s\t%s\t%s\n' "$exe_name" "$exe_path" "$owner_version" "$owner"
done
rm -f "$exec_tmp"

if [ "$pm" = "dpkg" ]; then
    dpkg-query -W -f='PKG\tOS\t${binary:Package}\t${Version}\n' 2>/dev/null || true
elif [ "$pm" = "rpm" ]; then
    rpm -qa --qf 'PKG\tOS\t%{NAME}\t%{VERSION}-%{RELEASE}\n' 2>/dev/null || true
    rpm -qa --qf '%{NAME}\n' 2>/dev/null | while IFS= read -r pkg; do
        [ -n "$pkg" ] || continue
        rpm -q --requires "$pkg" 2>/dev/null | while IFS= read -r requirement; do
            [ -n "$requirement" ] && printf 'PKGREQ\t%s\t%s\n' "$pkg" "$(printf '%s' "$requirement" | clean_one_line)"
        done
        rpm -q --provides "$pkg" 2>/dev/null | while IFS= read -r provided; do
            [ -n "$provided" ] && printf 'PKGPROVIDES\t%s\t%s\n' "$pkg" "$(printf '%s' "$provided" | clean_one_line)"
        done
    done
elif [ "$pm" = "apk" ]; then
    apk info -v 2>/dev/null | while IFS= read -r line; do printf 'PKG\tOS\t%s\t\n' "$line"; done
fi

if command -v python3 >/dev/null 2>&1 && python3 -m pip --version >/dev/null 2>&1; then
    python3 -m pip list --format=freeze 2>/dev/null | while IFS= read -r line; do
        [ -n "$line" ] && printf 'PIP\t%s\n' "$line"
    done
elif command -v python >/dev/null 2>&1 && python -m pip --version >/dev/null 2>&1; then
    python -m pip list --format=freeze 2>/dev/null | while IFS= read -r line; do
        [ -n "$line" ] && printf 'PIP\t%s\n' "$line"
    done
fi

if command -v Rscript >/dev/null 2>&1; then
    Rscript -e 'ip <- installed.packages()[,c("Package","Version"),drop=FALSE]; apply(ip,1,function(x) cat("RPKG\t",x[1],"\t",x[2],"\n",sep=""))' 2>/dev/null || true
fi

for d in /opt /usr/local /usr/share /usr/lib /usr; do
    if [ -d "$d" ]; then
        find "$d" -maxdepth 8 -type f -name '*.jar' -print 2>/dev/null
    fi
done | sort -u | while IFS= read -r jar; do
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

    def _inspection_record(self, rec, force=False):
        metadata = rec.get("metadata") or self._read_sidecar(rec["path"])
        rec["metadata"] = metadata
        cached = metadata.get("inspection") if isinstance(metadata.get("inspection"), dict) else {}
        if cached and not force and cached.get("schema") == 6:
            self._show_record_inventory(rec)
            return

        image = rec["tags"][0] if rec.get("tags") else metadata.get("docker_tag", "")
        if not image or not self._image_exists(image):
            if not self._load_archive(rec, "inspection"):
                return
            image = rec["tags"][0] if rec.get("tags") else ""
        if not image:
            messagebox.showerror("Inspect base", "The archive was loaded but no Docker tag could be determined.")
            return

        self.out.delete("1.0", "end")
        self._log(f"Inspecting base image: {image}\nArchive: {rec['path']}\n\n")
        self.inventory_summary.set(f"Inspecting {Path(rec['path']).name} ...")
        self.inventory_tree.delete(*self.inventory_tree.get_children())

        script = self._inspection_script()

        def work():
            try:
                p = self._run(["docker", "run", "--rm", "--pull=never", "--network=none", "--entrypoint", "/bin/sh", image, "-c", script])
                raw_text = p.stdout
                err_text = p.stderr
                if p.returncode != 0 and not raw_text.strip():
                    result = None
                    error = (
                        f"Inspection container exited with code {p.returncode}.\n"
                        f"{err_text}\n"
                        "This image may not contain a POSIX shell. Component inspection requires a shell-capable base."
                    )
                else:
                    result = self._parse_inspection_output(raw_text, image)
                    error = ""
            except Exception as e:
                result = None
                error = str(e)

            def finish():
                if result is None:
                    self._log(error + "\n")
                    self.inventory_summary.set("Inspection failed. See the activity log.")
                    return

                metadata_now = self._read_sidecar(rec["path"])
                probes = self._persistent_version_probes(metadata_now)
                metadata_now["version_probes"] = probes
                self._apply_persistent_versions(metadata_now, result)
                metadata_now["docker_tag"] = image
                metadata_now["os"] = result.get("system", {}).get("os", metadata_now.get("os", ""))
                metadata_now["architecture"] = result.get("system", {}).get("architecture", metadata_now.get("architecture", ""))
                metadata_now["inspection"] = result
                try:
                    self._sidecar_path(rec["path"]).write_text(json.dumps(metadata_now, indent=2), encoding="utf-8")
                except Exception as e:
                    self._log(f"WARNING: could not update metadata sidecar: {e}\n")

                rec["metadata"] = metadata_now
                self._show_record_inventory(rec)
                self._log(
                    f"Inspection complete.\n"
                    f"Executable commands/files: {len(result.get('executables', []))}\n"
                    f"OS packages: {len(result.get('packages', {}).get('os', []))}\n"
                    f"Python packages: {len(result.get('packages', {}).get('python', []))}\n"
                    f"R packages: {len(result.get('packages', {}).get('r', []))}\n"
                    f"JAR files indexed: {len(result.get('packages', {}).get('jars', []))}\n"
                    f"Metadata saved to: {self._sidecar_path(rec['path'])}\n"
                )
                self.refresh_selected_archives()

            self.after(0, finish)

        threading.Thread(target=work, daemon=True).start()

    def inspect_selected_base(self):
        rec = self._selected_record()
        if not rec:
            messagebox.showwarning("Inspect base", "Select a runtime or builder archive in Tab 1.")
            return
        self._inspection_record(rec, force=False)

    def refresh_selected_inventory(self):
        rec = self._selected_record()
        if not rec:
            messagebox.showwarning("Inspect base", "Select a runtime or builder archive in Tab 1.")
            return
        self._inspection_record(rec, force=True)

    def show_full_package_list(self):
        rec = self._selected_record()
        if not rec:
            messagebox.showwarning("Package list", "Select a runtime or builder archive in Tab 1.")
            return

        metadata = rec.get("metadata") or self._read_sidecar(rec["path"])
        inspection = metadata.get("inspection") if isinstance(metadata.get("inspection"), dict) else {}
        packages = inspection.get("packages") if isinstance(inspection.get("packages"), dict) else {}
        if not packages:
            if messagebox.askyesno("Package list", "This base has not been inspected yet. Inspect it now?"):
                self._inspection_record(rec, force=True)
            return

        win = tk.Toplevel(self)
        win.title(f"Full software inventory — {Path(rec['path']).name}")
        win.geometry("1050x760")
        win.configure(bg="#EAF2F8")

        tk.Label(
            win,
            text=f"Full software inventory — {Path(rec['path']).name}",
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
                initialfile=Path(rec["path"]).stem + "_full_inventory.txt",
            )
            if target:
                Path(target).write_text(report, encoding="utf-8")

        tk.Button(win, text="Save full inventory", bg="#117864", fg="white", command=save_report).pack(pady=(0, 10))

    def refresh_selected_archives(self):




        runtime_path = str(self.app.state.get("runtime_base_archive", "") or "").strip()
        builder_path = str(self.app.state.get("builder_base_archive", "") or "").strip()
        self.runtime_display.set(runtime_path or "(not selected — choose in Tab 1)")
        self.builder_display.set(builder_path or "(same as runtime — set in Tab 1)")

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
            tags = self._archive_tags(archive)
            metadata_tag = str(metadata.get("docker_tag", "") or "").strip()
            if not tags and metadata_tag:
                tags = [metadata_tag]
            records.append({"path": str(archive), "tags": tags, "size": archive.stat().st_size, "metadata": metadata})
        self._library_records = records

        runtime_rec = self._runtime_record()
        builder_rec = self._builder_record()
        if runtime_rec:
            self._apply_runtime_record(runtime_rec)
        else:
            self.runtime_tag.set(str(self.app.state.get("base_image", "") or ""))
            self.runtime_status.config(text="ARCHIVE MISSING" if runtime_path else "NOT SELECTED", fg="#922B21")
        if builder_path:
            if builder_rec:
                self._apply_builder_record(builder_rec)
            else:
                self.builder_tag.set(str(self.app.state.get("builder_image", "") or ""))
                self.builder_status.config(text="ARCHIVE MISSING", fg="#922B21")
        else:
            self.builder_tag.set("")
            self.builder_status.config(text="Same as runtime", fg="#566573")

        shown = self._selected_record()
        if shown:
            self._show_record_inventory(shown)
        else:
            self.inventory_tree.delete(*self.inventory_tree.get_children())
            self.inventory_summary.set("No selected base archive is available. Choose archives in Tab 1.")
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
            messagebox.showerror("Base", f"Select a {role} archive first.")
            return False
        archive = Path(rec["path"])
        if not archive.exists():
            messagebox.showerror("Base", f"Archive does not exist:\n{archive}")
            return False
        expected = rec["tags"][0] if rec["tags"] else ""
        if expected and self._image_exists(expected):
            self._log(f"{role.title()} image already present in Docker: {expected}\n")
            return True

        before = {row[0] for row in self._local_image_choices()}
        self._log(f"Loading external archive temporarily:\n{archive}\n")
        p = self._run(["docker", "load", "-i", str(archive)])
        self._log(p.stdout + p.stderr)
        if p.returncode != 0:
            messagebox.showerror("docker load", f"Failed to load {archive.name}. See activity log.")
            return False

        after = {row[0] for row in self._local_image_choices()}
        newly_loaded = sorted(after - before)
        known = set(self.app.state.get("gui_loaded_images", []))
        known.update(newly_loaded)
        self.app.state["gui_loaded_images"] = sorted(known)

        if not rec["tags"]:
            rec["tags"] = self._archive_tags(archive)
        if not rec["tags"] and newly_loaded:
            rec["tags"] = [newly_loaded[0]]
        tag = rec["tags"][0] if rec["tags"] else ""
        if role == "runtime":
            self.runtime_tag.set(tag)
            self.app.state["base_image"] = tag
            self.runtime_status.config(text="LOADED", fg="#1E8449")
        elif role == "builder":
            self.builder_tag.set(tag)
            self.app.state["builder_image"] = tag
            self.builder_status.config(text="LOADED", fg="#1E8449")
        self._log(f"Temporary Docker tag for {role}: {tag or '<unknown>'}\n")
        self.refresh_selected_archives()
        return True

    def load_selected_bases(self):
        runtime_path = str(self.app.state.get("runtime_base_archive", "") or "").strip()
        builder_path = str(self.app.state.get("builder_base_archive", "") or "").strip()
        if not runtime_path:
            messagebox.showerror("Runtime archive", "Choose the runtime archive in Tab 1 first.")
            return
        runtime_rec = self._find_record_by_path(runtime_path)
        if not self._load_archive(runtime_rec, "runtime"):
            return
        if builder_path:
            builder_rec = self._find_record_by_path(builder_path)
            if not self._load_archive(builder_rec, "builder"):
                return
        else:
            self.builder_tag.set("")
            self.builder_status.config(text="Same as runtime", fg="#566573")
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
