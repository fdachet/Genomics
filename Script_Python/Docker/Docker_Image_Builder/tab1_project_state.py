import json
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from docker_windows_diagnostics import DockerWindowsDiagnostics
from network_policy import POLICY_OFFLINE, POLICY_APPROVAL, normalize_policy
from build_modes import normalize_mode
from project_state import effective_builder_image
from docker_image_checkpoint import save_image_checkpoint, load_image_checkpoint, read_checkpoint_metadata
from workflow_toolbar import add_more_menu
from builder_presets import detect_runtime_image_system


class ProjectStateTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg="#F4F6F7")
        self.app = app

        tk.Label(
            self,
            text="0 — RUNTIME BASE / PROJECT SETUP",
            bg="#424949",
            fg="white",
            font=("Segoe UI", 16, "bold"),
            anchor="w",
            padx=14,
            pady=10,
        ).pack(fill="x")

        self._checkpoint_busy = False
        self.checkpoint_buttons = []
        self.checkpoint_status = tk.StringVar(value="Select a Docker image TAR to load as the runtime base.")
        self.network_policy = tk.StringVar(value=POLICY_APPROVAL)
        self.build_mode = tk.StringVar(value="permissive")

        load_frame = tk.LabelFrame(
            self, text=" 0 — Load runtime Docker image from TAR ",
            bg="#E8F6F3", fg="#117864", font=("Segoe UI", 11, "bold"), padx=12, pady=10,
        )
        load_frame.pack(fill="x", padx=12, pady=(10, 10))
        load_button = tk.Button(
            load_frame, text="Load runtime Docker image from .tar", bg="#2874A6", fg="white",
            font=("Segoe UI", 11, "bold"), padx=14, pady=6,
            command=lambda: self._checkpoint_action("load", "runtime"),
        )
        load_button.pack(side="left", padx=(0, 12))
        self.checkpoint_buttons.append(load_button)
        tk.Label(
            load_frame, textvariable=self.checkpoint_status, bg="#E8F6F3",
            fg="#1B4F72", anchor="w", justify="left", wraplength=950,
        ).pack(side="left", fill="x", expand=True)

        toolbar = tk.Frame(self, bg="#F4F6F7")
        toolbar.pack(fill="x", padx=12, pady=(0, 10))
        tk.Button(toolbar, text="Save project JSON", bg="#5D6D7E", fg="white", command=self.save_json).pack(side="left", padx=3)
        tk.Button(toolbar, text="Load project JSON", bg="#34495E", fg="white", command=self.load_json).pack(side="left", padx=3)
        self.docker_check_button = tk.Button(
            toolbar, text="Check Docker on Windows", bg="#1B4F72", fg="white",
            command=self.check_docker_on_windows,
        )
        self.docker_check_button.pack(side="left", padx=6)
        add_more_menu(toolbar, [("Validate project paths", self.validate_links),
                                ("Show technical project state", self.show_raw_state),
                                ("Refresh project details", self.refresh_from_project_state)], "#F4F6F7")
        self.docker_check_status = tk.StringVar(value="Docker: not checked")
        tk.Label(toolbar, textvariable=self.docker_check_status, bg="#F4F6F7", fg="#1B4F72").pack(side="left", padx=4)

        self.vars = {}
        project_info = tk.LabelFrame(
            self, text=" Project paths and output ", bg="#F4F6F7", fg="#424949",
            font=("Segoe UI", 10, "bold"), padx=10, pady=7,
        )
        project_info.pack(fill="x", padx=12, pady=(0, 8))
        runtime_info = tk.LabelFrame(
            self, text=" RUNTIME BASE — Filesystem of the final Docker image ",
            bg="#EAF3FA", fg="#154360", font=("Segoe UI", 10, "bold"), padx=10, pady=8,
        )
        runtime_info.pack(fill="x", padx=12, pady=(0, 8))

        def add_field(frame, row, key, label, browse_command=None, extra_button=False):
            tk.Label(frame, text=label + ":", bg=frame.cget("bg"),
                     font=("Segoe UI", 9, "bold")).grid(row=row, column=0, sticky="w", pady=3)
            var = tk.StringVar()
            self.vars[key] = var
            tk.Entry(frame, textvariable=var, state="readonly").grid(
                row=row, column=1, sticky="ew", padx=8, pady=3)
            buttons = tk.Frame(frame, bg=frame.cget("bg"))
            buttons.grid(row=row, column=2, sticky="w", pady=3)
            if browse_command is not None:
                tk.Button(buttons, text="Browse", bg="#D5DBDB", command=browse_command).pack(side="left")
            if extra_button:
                tk.Button(buttons, text="Same as runtime", bg="#D5DBDB",
                          command=self.use_runtime_as_builder).pack(side="left", padx=(4, 0))
            frame.columnconfigure(1, weight=1)

        add_field(project_info, 0, "project_dir", "Project directory", self.browse_project_directory)
        add_field(project_info, 1, "export_image_dir", "Final image export folder (.tar)", self.browse_export_image_dir)
        add_field(project_info, 2, "generated_context", "Generated build context", self.browse_generated_context)

        add_field(runtime_info, 0, "runtime_base_archive", "Runtime Docker TAR [automatic]")
        add_field(runtime_info, 1, "base_image", "Runtime Docker tag [automatic]")
        add_field(runtime_info, 2, "base_os", "Operating system [automatic]")
        add_field(runtime_info, 3, "base_arch", "Architecture [automatic]")
        add_field(runtime_info, 4, "base_libc", "libc [automatic]")

        counts = tk.Frame(self, bg="#F4F6F7")
        counts.pack(fill="x", padx=12, pady=(0, 10))
        self.count_text = tk.StringVar()
        tk.Label(counts, textvariable=self.count_text, bg="#D6EAF8", fg="#154360",
                 anchor="w", justify="left", padx=10, pady=8).pack(fill="x")

        messages_header = tk.Frame(self, bg="#F4F6F7")
        messages_header.pack(fill="x", padx=12)
        tk.Label(messages_header, text="Link / validation messages", bg="#F4F6F7",
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Button(messages_header, text="Clear log", bg="#D6DBDF",
                  command=lambda: self.output.delete('1.0', 'end')).pack(side="right")
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

    def _checkpoint_action(self, action, role):
        if self._checkpoint_busy:
            return
        state = self._state()
        both = False
        if role == "runtime":
            image = str(state.get("base_image", "") or "").strip()
        elif role == "builder":
            image = effective_builder_image(state)
        else:
            image = str(state.get("built_image", "") or state.get("image_name", "") or "").strip()
        if action == "save":
            if not image:
                messagebox.showerror("Save Docker image", f"No {role} image is currently selected.", parent=self)
                return
            filename = re.sub(r"[^A-Za-z0-9_.-]", "_", image) + ".tar"
            chosen = filedialog.asksaveasfilename(
                parent=self, title=f"Save the working {role} Docker image as a TAR",
                initialdir=self._initial_directory(state.get("export_image_dir", ""), state.get("project_dir", "")),
                initialfile=filename, defaultextension=".tar",
                filetypes=[("Docker image archive", "*.tar")],
            )
        else:
            chosen = filedialog.askopenfilename(
                parent=self, title=f"Load a saved Docker TAR as {role}",
                initialdir=self._initial_directory(
                    state.get("runtime_base_archive" if role == "runtime" else "builder_base_archive", ""),
                    state.get("export_image_dir", ""), state.get("project_dir", ""),
                ),
                filetypes=[("Docker image archive", "*.tar"), ("All files", "*.*")],
            )
        if not chosen:
            return
        if action == "save":
            selected_system = state.get("base_system", {}) if role == "runtime" else state.get("builder_system", {})
            selected_inventory = state.get("base_inventory", {}) if role == "runtime" else state.get("builder_inventory", {})
            if role == "built":
                selected_system = {}
                selected_inventory = {}
            if role == "builder" and not state.get("builder_image") and not state.get("builder_base_archive"):
                selected_system = state.get("base_system", {})
                selected_inventory = state.get("base_inventory", {})
        else:
            selected_system = {}
            selected_inventory = {}

        self._checkpoint_busy = True
        for button in self.checkpoint_buttons:
            button.configure(state="disabled")
        self.checkpoint_status.set("Saving selected image to TAR..." if action == "save" else "Loading saved Docker TAR...")
        self.output.insert("end", f"{action.title()} {role} Docker image: {chosen}\n")
        self.output.see("end")

        def worker():
            def progress(message):
                try:
                    self.after(0, lambda line=message: self._checkpoint_log(line))
                except RuntimeError:
                    pass
            try:
                if action == "save":
                    result = save_image_checkpoint(
                        image, chosen, system=selected_system, inventory=selected_inventory, progress=progress,
                    )
                else:
                    result = load_image_checkpoint(chosen, progress=progress)
                    if role == "runtime":
                        detected = detect_runtime_image_system(result.get("tag", ""))
                        result["system"] = {**(result.get("system") or {}), **detected}
                self.after(0, lambda: self._checkpoint_finished(action, role, both, result, ""))
            except Exception as exc:
                error = str(exc)
                try:
                    self.after(0, lambda: self._checkpoint_finished(action, role, both, None, error))
                except RuntimeError:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _checkpoint_log(self, line):
        if not self.winfo_exists():
            return
        self.output.insert("end", str(line))
        self.output.see("end")

    def _checkpoint_finished(self, action, role, both, result, error):
        if not self.winfo_exists():
            return
        self._checkpoint_busy = False
        for button in self.checkpoint_buttons:
            button.configure(state="normal")
        if error:
            self.checkpoint_status.set("FAILED: " + error[:350])
            self._checkpoint_log("Image checkpoint failed: " + error + "\n")
            messagebox.showerror("Docker image checkpoint failed", error, parent=self)
            return
        state = self._state()
        tag = result["tag"]
        archive = result["archive"]
        changes = {}
        if action == "load":
            system = result["system"]
            inventory = result["inventory"]
            if role == "runtime" or both:
                changes.update(runtime_base_archive=archive, base_image=tag, base_system=system, base_inventory=inventory)
            if role == "builder" or both:
                changes.update(builder_base_archive="" if both else archive,
                               builder_image="" if both else tag,
                               builder_system={} if both else system,
                               builder_inventory={} if both else inventory)
        else:
            inventory = result.get('inventory', {})
            system = result.get('system', {})
            if role == "runtime" or (role == "builder" and both and str(state.get("base_image", "") or "") == tag):
                changes.update(runtime_base_archive=archive, base_image=tag,
                               base_inventory=inventory, base_system=system)
            if role == "builder" or (role == "runtime" and both and effective_builder_image(state) == tag):
                changes["builder_base_archive"] = archive
                changes["builder_image"] = tag
                changes["builder_inventory"] = inventory
                changes["builder_system"] = system
        if changes:
            state.update(changes)
        verb = "saved" if action == "save" else "loaded"
        self.checkpoint_status.set(f"Image {verb}: {tag}  |  TAR: {archive}")
        self._checkpoint_log(f"Image {verb} successfully: {tag}\nTAR: {archive}\n")
        self.refresh_from_project_state()
        if action == "load":
            base_tab = getattr(self.app, "base_tab", None)
            if base_tab is not None:
                self.after(0, base_tab.refresh_selected_archives)
        messagebox.showinfo(
            "Docker image checkpoint",
            f"Working image {verb} successfully.\n\nDocker tag: {tag}\nTAR: {archive}\n\n"
            "You can now inspect the installed software in Tab 2 and continue adding components.",
            parent=self,
        )

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
        try:
            return read_checkpoint_metadata(archive_path)
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
                "Runtime TAR has no embedded inventory snapshot. "
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
                "Builder TAR has no embedded inventory snapshot. "
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
        if state.get("package_download_policy") != POLICY_APPROVAL:
            state["package_download_policy"] = POLICY_APPROVAL
        if state.get("build_mode") != "permissive":
            state["build_mode"] = "permissive"
        self.network_policy.set(POLICY_APPROVAL)
        self.build_mode.set("permissive")
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
            "runtime_base_archive": state.get("runtime_base_archive", "") or ("(Docker tag only)" if state.get("base_image") else ""),
            "base_image": state.get("base_image", ""),
            "base_os": system.get("os", ""),
            "base_arch": system.get("architecture", ""),
            "base_libc": system.get("glibc", ""),
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
            f"Components: {len(components)}"
        )


    def validate_links(self):
        state = self._state()
        messages = []

        if not state.get("base_image"):
            messages.append("MISSING: no runtime base Docker tag has been published by Tab 2.")
        if state.get("base_image") and not state.get("runtime_base_archive"):
            messages.append("INFO: runtime is selected by Docker tag; no external TAR archive is recorded. The image can be used directly if it exists in Docker Desktop.")

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
                "Project loaded; Runtime Tab 0 and Builder Tab 1 are available.\n"
                "Runtime and builder metadata restored where available; "
                "see Link / validation messages for missing embedded inventory data.",
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
