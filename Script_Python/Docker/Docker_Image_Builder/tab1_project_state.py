import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from docker_windows_diagnostics import DockerWindowsDiagnostics
from network_policy import POLICY_OFFLINE, POLICY_APPROVAL, normalize_policy
from build_modes import normalize_mode
from project_state import effective_builder_image


class ProjectStateTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg="#F4F6F7")
        self.app = app

        tk.Label(
            self,
            text="1 — PROJECT / BASE SELECTION",
            bg="#424949",
            fg="white",
            font=("Segoe UI", 16, "bold"),
            anchor="w",
            padx=14,
            pady=10,
        ).pack(fill="x")

        toolbar = tk.Frame(self, bg="#F4F6F7")
        toolbar.pack(fill="x", padx=12, pady=10)
        tk.Button(toolbar, text="Refresh", bg="#D5DBDB", command=self.refresh_from_project_state).pack(side="left", padx=3)
        tk.Button(toolbar, text="Save project JSON", bg="#5D6D7E", fg="white", command=self.save_json).pack(side="left", padx=3)
        tk.Button(toolbar, text="Load project JSON", bg="#34495E", fg="white", command=self.load_json).pack(side="left", padx=3)
        tk.Button(toolbar, text="Validate shared links", bg="#117864", fg="white", command=self.validate_links).pack(side="left", padx=3)
        tk.Button(toolbar, text="Show raw state", bg="#2874A6", fg="white", command=self.show_raw_state).pack(side="left", padx=3)
        self.docker_check_button = tk.Button(
            toolbar, text="Check Docker on Windows", bg="#1B4F72", fg="white",
            command=self.check_docker_on_windows,
        )
        self.docker_check_button.pack(side="left", padx=6)
        self.docker_check_status = tk.StringVar(value="Docker: not checked")
        tk.Label(toolbar, textvariable=self.docker_check_status, bg="#F4F6F7", fg="#1B4F72").pack(side="left", padx=4)

        info = tk.LabelFrame(
            self,
            text=" Shared project data used by every tab ",
            bg="#F4F6F7",
            fg="#424949",
            font=("Segoe UI", 10, "bold"),
            padx=10,
            pady=8,
        )
        info.pack(fill="x", padx=12, pady=(0, 10))

        self.vars = {}
        rows = [
            ("project_dir", "Project directory", "path_folder", self.browse_project_directory),
            ("export_image_dir", "Export folder for newly created Docker image (.tar)", "path_folder", self.browse_export_image_dir),
            ("runtime_base_archive", "Runtime (final) base archive", "path_file", self.browse_runtime_base_archive),
            ("base_image", "Runtime (final) Docker tag", "automatic", None),
            ("base_os", "Runtime OS", "automatic", None),
            ("base_arch", "Runtime architecture", "automatic", None),
            ("base_libc", "Runtime libc", "automatic", None),
            ("builder_base_archive", "Builder base archive", "path_file", self.browse_builder_base_archive),
            ("builder_image", "Builder Docker tag", "automatic", None),
            ("builder_os", "Builder OS", "automatic", None),
            ("builder_arch", "Builder architecture", "automatic", None),
            ("builder_libc", "Builder libc", "automatic", None),
            ("image_name", "Final image name", "automatic", None),
            ("generated_context", "Generated build context", "path_folder", self.browse_generated_context),
        ]

        for row, (key, label, field_type, browse_command) in enumerate(rows):
            suffix = ""
            if field_type == "automatic":
                suffix = "  [automatic]"
            elif key in ("runtime_base_archive", "builder_base_archive"):
                suffix = "  [Docker .tar]"

            tk.Label(
                info,
                text=label + suffix + ":",
                bg="#F4F6F7",
                font=("Segoe UI", 9, "bold"),
            ).grid(row=row, column=0, sticky="w", pady=3)

            var = tk.StringVar()
            self.vars[key] = var
            tk.Entry(info, textvariable=var, state="readonly").grid(
                row=row, column=1, sticky="ew", padx=8, pady=3
            )

            button_frame = tk.Frame(info, bg="#F4F6F7")
            button_frame.grid(row=row, column=2, sticky="w", padx=(0, 4), pady=3)

            if browse_command is not None:
                tk.Button(
                    button_frame,
                    text="Browse",
                    bg="#D5DBDB",
                    command=browse_command,
                ).pack(side="left")

            if key == "builder_base_archive":
                tk.Button(
                    button_frame,
                    text="Same as runtime",
                    bg="#E5E7E9",
                    command=self.use_runtime_as_builder,
                ).pack(side="left", padx=(4, 0))

        info.columnconfigure(1, weight=1)

        tk.Label(
            info,
            text=(
                "The export folder is only the destination for the newly created final Docker image .tar. "
                "Runtime = filesystem used by the final image. Builder = temporary environment used to compile software. "
                "Runtime and builder .tar files are selected independently above."
            ),
            bg="#F4F6F7",
            fg="#566573",
            justify="left",
            anchor="w",
        ).grid(row=len(rows), column=0, columnspan=3, sticky="ew", pady=(7, 2))

        network_options = tk.LabelFrame(self, text=" Package downloads and build network policy ", bg="#F4F6F7", padx=10, pady=6)
        network_options.pack(fill="x", padx=12, pady=(0, 8))
        self.network_policy = tk.StringVar()
        ttk.Radiobutton(network_options, text="Offline only: never download dependencies", variable=self.network_policy, value=POLICY_OFFLINE, command=self._save_network_policy).pack(side="left", padx=8)
        ttk.Radiobutton(network_options, text="Ask before downloading missing OS packages", variable=self.network_policy, value=POLICY_APPROVAL, command=self._save_network_policy).pack(side="left", padx=8)
        tk.Label(network_options, text="Applies to the builder and final runtime. Each online build requires confirmation.", bg="#F4F6F7", fg="#566573").pack(side="left", padx=8)

        mode_options = tk.LabelFrame(self, text=" Dependency requirements during image builds ", bg="#F4F6F7", padx=10, pady=6)
        mode_options.pack(fill="x", padx=12, pady=(0, 8))
        self.build_mode = tk.StringVar()
        for label, value in (("Permissive: build and flag missing requirements", "permissive"), ("Strict: require all dependencies", "strict"), ("Assembly only: skip installations", "assembly")):
            ttk.Radiobutton(mode_options, text=label, variable=self.build_mode, value=value, command=self._save_build_mode).pack(side="left", padx=8)

        counts = tk.Frame(self, bg="#F4F6F7")
        counts.pack(fill="x", padx=12, pady=(0, 10))
        self.count_text = tk.StringVar()
        tk.Label(
            counts,
            textvariable=self.count_text,
            bg="#D6EAF8",
            fg="#154360",
            anchor="w",
            justify="left",
            padx=10,
            pady=8,
        ).pack(fill="x")

        tk.Label(
            self,
            text="Workflow linkage",
            bg="#F4F6F7",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=12)

        columns = ("stage", "status", "shared_data")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=10)
        self.tree.heading("stage", text="Stage")
        self.tree.heading("status", text="Status")
        self.tree.heading("shared_data", text="Shared state")
        self.tree.column("stage", width=180, anchor="w")
        self.tree.column("status", width=130, anchor="center")
        self.tree.column("shared_data", width=900, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=12, pady=(4, 8))

        tk.Label(
            self,
            text="Link / validation messages",
            bg="#F4F6F7",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=12)
        self.output = tk.Text(self, height=8, bg="white", font=("Consolas", 9))
        self.output.pack(fill="x", padx=12, pady=(4, 12))

        self.refresh_from_project_state()

    def _save_build_mode(self):
        mode = normalize_mode(self.build_mode.get())
        if self.app.state.get("build_mode") != mode:
            self.app.state["build_mode"] = mode

    def _save_network_policy(self):
        policy = normalize_policy(self.network_policy.get())
        if self.app.state.get('package_download_policy') != policy:
            self.app.state['package_download_policy'] = policy

    def check_docker_on_windows(self):

        self.docker_check_button.configure(state="disabled")
        self.docker_check_status.set("Docker: checking...")
        dialog = tk.Toplevel(self)
        dialog.title("Docker on Windows — installation and runtime diagnostics")
        dialog.geometry("950x660")
        dialog.minsize(710, 440)
        dialog.transient(self.winfo_toplevel())
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)
        tk.Label(
            dialog,
            text="Windows Docker checks — CLI, Desktop, daemon, Linux, containers, bind mounts, builds",
            anchor="w", font=("Segoe UI", 11, "bold"), padx=10, pady=10,
        ).grid(row=0, column=0, sticky="ew")
        report_box = scrolledtext.ScrolledText(dialog, font=("Consolas", 10), wrap="word")
        report_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))
        report_box.insert("end", "Checking Windows Docker installation and functionality...\n\n")
        action_frame = tk.Frame(dialog)
        action_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))

        def copy_report():
            dialog.clipboard_clear()
            dialog.clipboard_append(report_box.get("1.0", "end-1c"))

        def save_report():
            path = filedialog.asksaveasfilename(
                parent=dialog, title="Save Docker diagnostic report",
                defaultextension=".txt", initialfile="docker_windows_diagnostics.txt",
                filetypes=[("Text report", "*.txt"), ("All files", "*.*")],
            )
            if not path:
                return
            try:
                Path(path).write_text(report_box.get("1.0", "end-1c"), encoding="utf-8")
            except OSError as exc:
                messagebox.showerror("Save diagnostic report", str(exc), parent=dialog)

        tk.Button(action_frame, text="Copy report", command=copy_report).pack(side="left", padx=3)
        tk.Button(action_frame, text="Save report", command=save_report).pack(side="left", padx=3)
        tk.Button(action_frame, text="Close", command=dialog.destroy).pack(side="right", padx=3)

        runtime = str(self.app.state.get("base_image", "") or "")
        builder = effective_builder_image(self.app.state)

        def append(message):
            def update():
                if not dialog.winfo_exists():
                    return
                report_box.insert("end", message)
                report_box.see("end")
            try:
                self.after(0, update)
            except RuntimeError:
                pass

        def worker():
            try:
                diagnostic = DockerWindowsDiagnostics(runtime, builder, emit=append)
                result = diagnostic.run()
            except Exception as exc:
                result = "FAILED"
                append(f"\n[FATAL] Docker diagnostics could not complete: {exc}\n")

            def finish():
                self.docker_check_status.set("Docker: " + result.lower())
                self.docker_check_button.configure(state="normal")
                self.output.insert("end", "\nDocker diagnostics: " + result + "\n")
                self.output.see("end")
            try:
                self.after(0, finish)
            except RuntimeError:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _state(self):
        return self.app.state

    def browse_project_directory(self):
        state = self._state()
        current = str(state.get("project_dir", "") or "").strip()
        initial_dir = current if current and Path(current).is_dir() else str(Path.cwd())

        selected = filedialog.askdirectory(
            parent=self,
            title="Select Docker project directory",
            initialdir=initial_dir,
        )
        if not selected:
            return

        state["project_dir"] = selected
        touch = getattr(state, "touch", None)
        if callable(touch):
            touch("project_dir")

        self.refresh_from_project_state()

    def _touch_state(self, key):
        touch = getattr(self._state(), "touch", None)
        if callable(touch):
            touch(key)

    def _initial_directory(self, *candidates):
        for candidate in candidates:
            value = str(candidate or "").strip()
            if not value:
                continue
            path = Path(value)
            if path.is_dir():
                return str(path)
            if path.parent.is_dir():
                return str(path.parent)
        return str(Path.cwd())

    def _read_archive_sidecar(self, archive_path):
        sidecar = Path(archive_path).with_suffix(".json")
        if not sidecar.is_file():
            return {}
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8-sig"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def browse_export_image_dir(self):
        state = self._state()
        selected = filedialog.askdirectory(
            parent=self,
            title="Select export folder for newly created Docker image (.tar)",
            initialdir=self._initial_directory(
                state.get("export_image_dir", ""),
                state.get("project_dir", ""),
            ),
        )
        if not selected:
            return

        state["export_image_dir"] = selected
        self._touch_state("export_image_dir")
        self.refresh_from_project_state()

    def browse_runtime_base_archive(self):
        state = self._state()
        selected = filedialog.askopenfilename(
            parent=self,
            title="Select runtime Docker base archive",
            initialdir=self._initial_directory(
                state.get("runtime_base_archive", ""),
                state.get("project_dir", ""),
            ),
            filetypes=[
                ("Docker image archive", "*.tar"),
                ("All files", "*.*"),
            ],
        )
        if not selected:
            return

        metadata = self._read_archive_sidecar(selected)
        tag = str(metadata.get("docker_tag", "") or "").strip()
        inspection = metadata.get("inspection", {})
        if not isinstance(inspection, dict):
            inspection = {}
        system = inspection.get("system", {})
        if not isinstance(system, dict):
            system = {}

        if hasattr(state, "publish_base"):
            state.publish_base(
                archive=selected,
                tag=tag,
                system=system,
                inventory=inspection,
            )
        else:
            state["runtime_base_archive"] = selected
            state["base_image"] = tag
            state["base_system"] = system
            state["base_inventory"] = inspection
            self._touch_state("base")

        if not metadata:
            self.output.insert(
                "end",
                "Runtime archive selected, but no matching .json metadata sidecar was found. "
                "Open Tab 2 to load/inspect the archive and determine its Docker tag and inventory.\\n",
            )
        elif not tag:
            self.output.insert(
                "end",
                "Runtime archive selected, but its metadata does not contain a Docker tag. "
                "Open Tab 2 to load the archive.\\n",
            )

        self.refresh_from_project_state()

    def browse_builder_base_archive(self):
        state = self._state()
        selected = filedialog.askopenfilename(
            parent=self,
            title="Select builder Docker base archive",
            initialdir=self._initial_directory(
                state.get("builder_base_archive", ""),
                state.get("project_dir", ""),
            ),
            filetypes=[
                ("Docker image archive", "*.tar"),
                ("All files", "*.*"),
            ],
        )
        if not selected:
            return

        metadata = self._read_archive_sidecar(selected)
        tag = str(metadata.get("docker_tag", "") or "").strip()
        inspection = metadata.get("inspection", {})
        if not isinstance(inspection, dict):
            inspection = {}
        system = inspection.get("system", {})
        if not isinstance(system, dict):
            system = {}

        if hasattr(state, "publish_builder"):
            state.publish_builder(archive=selected, tag=tag, system=system, inventory=inspection)
        else:
            state["builder_base_archive"] = selected
            state["builder_image"] = tag
            state["builder_system"] = system
            state["builder_inventory"] = inspection
            self._touch_state("builder_base")

        if not metadata:
            self.output.insert(
                "end",
                "Builder archive selected, but no matching .json metadata sidecar was found. "
                "Open Tab 2 to load the archive and determine its Docker tag.\\n",
            )
        elif not tag:
            self.output.insert(
                "end",
                "Builder archive selected, but its metadata does not contain a Docker tag. "
                "Open Tab 2 to load the archive.\\n",
            )

        self.refresh_from_project_state()

    def use_runtime_as_builder(self):
        state = self._state()
        state["builder_base_archive"] = ""
        state["builder_image"] = ""
        state["builder_system"] = {}
        state["builder_inventory"] = {}
        self._touch_state("builder_base")
        self.refresh_from_project_state()

    def browse_generated_context(self):
        state = self._state()
        selected = filedialog.askdirectory(
            parent=self,
            title="Select generated Docker build-context directory",
            initialdir=self._initial_directory(
                state.get("generated_context", ""),
                state.get("project_dir", ""),
            ),
        )
        if not selected:
            return

        state["generated_context"] = selected
        self._touch_state("generated_context")
        self.refresh_from_project_state()

    def refresh_from_project_state(self):
        state = self._state()
        self.network_policy.set(normalize_policy(state.get("package_download_policy")))
        self.build_mode.set(normalize_mode(state.get("build_mode")))
        system = state.get("base_system", {}) if isinstance(state.get("base_system", {}), dict) else {}
        inventory = state.get("base_inventory", {}) if isinstance(state.get("base_inventory", {}), dict) else {}
        packages = inventory.get("packages", {}) if isinstance(inventory.get("packages", {}), dict) else {}

        explicit_builder = bool(state.get("builder_base_archive") or state.get("builder_image"))
        builder_system = state.get("builder_system", {}) if isinstance(state.get("builder_system", {}), dict) else {}
        builder_inventory = state.get("builder_inventory", {}) if isinstance(state.get("builder_inventory", {}), dict) else {}
        if not explicit_builder:
            builder_system = system
            builder_inventory = inventory
        builder_packages = builder_inventory.get("packages", {}) if isinstance(builder_inventory.get("packages", {}), dict) else {}

        values = {
            "project_dir": state.get("project_dir", ""),
            "export_image_dir": state.get("export_image_dir", ""),
            "runtime_base_archive": state.get("runtime_base_archive", ""),
            "base_image": state.get("base_image", ""),
            "builder_base_archive": state.get("builder_base_archive", "") or "(same as runtime)",
            "builder_image": effective_builder_image(state) or "(same as runtime)",
            "base_os": system.get("os", ""),
            "base_arch": system.get("architecture", ""),
            "base_libc": system.get("glibc", ""),
            "builder_os": builder_system.get("os", ""),
            "builder_arch": builder_system.get("architecture", ""),
            "builder_libc": builder_system.get("glibc", ""),
            "image_name": state.get("image_name", ""),
            "generated_context": state.get("generated_context", ""),
        }
        for key, value in values.items():
            self.vars[key].set(str(value or ""))

        executables = inventory.get("executables", []) if isinstance(inventory.get("executables", []), list) else []
        os_packages = packages.get("os", []) if isinstance(packages.get("os", []), list) else []
        py_packages = packages.get("python", []) if isinstance(packages.get("python", []), list) else []
        r_packages = packages.get("r", []) if isinstance(packages.get("r", []), list) else []
        jars = packages.get("jars", []) if isinstance(packages.get("jars", []), list) else []
        builder_executables = builder_inventory.get("executables", []) if isinstance(builder_inventory.get("executables", []), list) else []
        builder_os_packages = builder_packages.get("os", []) if isinstance(builder_packages.get("os", []), list) else []
        components = state.get("components", []) if isinstance(state.get("components", []), list) else []

        self.count_text.set(
            f"Shared-state revision: {getattr(state, 'revision', 'n/a')}   |   "
            f"Runtime: {len(executables)} executables / {len(os_packages)} OS packages   |   "
            f"Builder: {len(builder_executables)} executables / {len(builder_os_packages)} OS packages   |   "
            f"Components: {len(components)}"
        )

        source_count = sum(1 for c in components if str(c.get("kind", "")).lower() == "source" and c.get("enabled", True))
        runtime_pkg_count = sum(
            1 for c in components
            if c.get("enabled", True) and str(c.get("runtime_packages", "")).strip()
        )

        ready_count = 0
        for component in components:
            if component.get("enabled", True) and str(component.get("kind", "")).lower() == "source":
                record = (state.get("compiled_artifacts", {}) or {}).get(str(component.get("name", "")))
                ready_count += bool(record and Path(str(record.get("artifact", ""))).is_file())
        rows = [
            ("2. Base Inventory", "READY" if state.get("base_image") else "MISSING", "Inspect runtime and builder selected in Tab 1"),
            ("3. Add Components", f"{len(components)} defined", "Register sources, binaries, packages and destinations"),
            ("4. Compile Sources", f"{ready_count}/{source_count} artifacts recorded", "Compile using the builder and preserve outputs"),
            ("5. Runtime Libraries", f"{runtime_pkg_count} component(s) with packages", "Analyze dependencies against the selected runtime"),
            ("6. Build Docker Image", "READY" if state.get("base_image") else "WAITING", "Assemble runtime, saved compiled outputs, binaries and libraries"),
            ("7. Verify / Export", "AVAILABLE" if state.get("image_name") else "WAITING", "Run tests in final image and export verified result"),
        ]

        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(rows):
            self.tree.insert("", "end", iid=str(index), values=row)

    def validate_links(self):
        state = self._state()
        messages = []

        if not state.get("base_image"):
            messages.append("MISSING: no runtime base Docker tag has been published by Tab 2.")
        if state.get("base_image") and not state.get("runtime_base_archive"):
            messages.append("WARNING: runtime Docker tag exists but no external runtime archive is recorded.")

        inventory = state.get("base_inventory", {})
        if state.get("base_image") and not isinstance(inventory, dict):
            messages.append("WARNING: base inventory has an invalid type.")
        elif state.get("base_image") and not inventory:
            messages.append("INFO: the selected base has not published an inspection inventory yet.")

        components = state.get("components", [])
        if not isinstance(components, list):
            messages.append("ERROR: shared component state is not a list.")

        export_dir = str(state.get("export_image_dir", "") or "").strip()
        if not export_dir:
            messages.append("INFO: no export folder for the newly created Docker image .tar has been selected yet.")
        elif not Path(export_dir).is_dir():
            messages.append(f"WARNING: Docker image export folder is not currently available: {export_dir}")

        if not messages:
            messages.append("Shared state links are structurally valid.")

        self.output.delete("1.0", "end")
        self.output.insert("end", "\n".join(messages))
        self.refresh_from_project_state()

    def save_json(self):
        state = self._state()
        initial_dir = state.get("project_dir", "") or str(Path.cwd())
        path = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialdir=initial_dir if Path(initial_dir).exists() else str(Path.cwd()),
            initialfile="docker_builder_project.json",
        )
        if not path:
            return
        try:
            if hasattr(state, "save_file"):
                state.save_file(path)
            else:
                Path(path).write_text(json.dumps(dict(state), indent=2), encoding="utf-8")
            messagebox.showinfo("Project state", f"Saved:\n{path}")
        except Exception as exc:
            messagebox.showerror("Project state", str(exc))

    def load_json(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            if hasattr(self._state(), "load_file"):
                report = self._state().load_file(path) or []
            else:
                data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
                self._state().clear()
                self._state().update(data)
                report = []

            
            
            self.refresh_from_project_state()
            self.output.delete("1.0", "end")
            self.output.insert("end", "Project loaded: " + str(path) + "\n")
            if report:
                self.output.insert("end", "\n".join(report) + "\n")
            else:
                self.output.insert("end", "All available saved base metadata is displayed.\n")
            messagebox.showinfo(
                "Project state",
                "Project loaded and Tab 1 refreshed.\n"
                "Runtime and builder metadata restored where available; "
                "see Link / validation messages for any missing sidecars.",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("Project state", str(exc), parent=self)

    def show_raw_state(self):
        win = tk.Toplevel(self)
        win.title("Raw shared project state")
        win.geometry("1000x700")
        text = tk.Text(win, font=("Consolas", 9), wrap="none")
        text.pack(fill="both", expand=True)
        text.insert("1.0", json.dumps(dict(self._state()), indent=2))
        text.configure(state="disabled")


class _DebugApp:
    def __init__(self):
        try:
            from project_state import ProjectState
            self.state = ProjectState()
        except Exception:
            self.state = {}


if __name__ == "__main__":
    root = tk.Tk()
    root.title("Debug — ProjectStateTab")
    root.geometry("1400x900")
    app = _DebugApp()
    tab = ProjectStateTab(root, app)
    tab.pack(fill="both", expand=True)
    root.mainloop()
