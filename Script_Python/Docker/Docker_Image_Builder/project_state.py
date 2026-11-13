import json
from copy import deepcopy
from pathlib import Path


def effective_builder_image(state):
    mode = state.get('builder_mode')
    if mode == 'runtime':
        return str(state.get('base_image', '') or '').strip()
    explicit = str(state.get('builder_image', '') or '').strip()
    if explicit:
        return explicit
    if mode == 'separate' or str(state.get('builder_base_archive', '') or '').strip():
        return ''
    return str(state.get('base_image', '') or '').strip()



class ProjectState(dict):
    DEFAULTS = {
        "project_dir": "",
        "export_image_dir": "",
        "runtime_base_archive": "",
        "builder_base_archive": "",
        "builder_mode": "runtime",
        "builder_preset": {},
        "builder_source_override": "",
        "gui_loaded_images": [],
        "base_image": "",
        "builder_image": "",
        "base_prepare": "",
        "base_system": {},
        "base_inventory": {},
        "builder_system": {},
        "builder_inventory": {},
        "components": [],
        "local_package_folders": [],
        "image_removals": [],
        "dependency_satisfactions": [],
        "compacted_image": "",
        "show_image_components": True,
        "payloads": [],
        "sources": {},
        "runtime_libraries": {},
        "image_name": "",
        "generated_context": "",
        "generated_dockerfile": "",
        "validation": {},
        "compiled_artifacts": {},
        "compilation_failures": {},
        "built_image": "",
        "last_full_image_tar": "",
        "final_online_package_requests": [],
        "final_local_package_paths": [],
        "package_download_policy": "approval",
        "environment_requirements": {},
        "allow_source_network": False,
        "accept_partial_source_output": False,
        "suggest_build_packages": False,
        "build_mode": "permissive",
        "install_planned_packages_now": True,
        "last_build_report": {},
        "runtime_install_receipt": {},
        "build_history": [],
        "parent_provenance": {},
        "installation_overrides": [],
        "installation_override_rejections": [],
        "show_builder_inventory": False,
        "inventory_category": "Applications",
        "inventory_origin": "All",
        "package_finder_downloads": [],
        "package_finder_source_downloads": [],
        "package_finder_builder_installs": [],
        "local_builder_installs": [],
        "local_runtime_installs": [],
        "repository_builder_installs": [],
        "repository_runtime_installs": [],
        "package_finder_cache": "",
        "package_finder_archive_mode": False,
        "package_finder_repository_override": "",
        "package_finder_source_mode": "Selected builder/runtime",
        "package_finder_distribution": "",
        "package_finder_distribution_tag": "",
        "package_finder_platform": "linux/amd64",
        "package_finder_custom_image": "",
        "container_config": {},
        "recognized_elements_database": "",
    }

    def __init__(self, initial=None):
        self._listeners = []
        self._revision = 0
        self.last_load_metadata_report = []
        dict.__init__(self)
        self._apply_defaults()
        if initial:
            self.load_dict(initial, notify=False)

    @property
    def revision(self):
        return self._revision

    def _apply_defaults(self):
        if 'builder_mode' not in self:
            dict.__setitem__(self, 'builder_mode', 'separate' if (self.get('builder_image') or self.get('builder_base_archive')) else 'runtime')
        for key, value in self.DEFAULTS.items():
            if key not in self:
                dict.__setitem__(self, key, deepcopy(value))


    def subscribe(self, callback):
        if callback not in self._listeners:
            self._listeners.append(callback)

    def unsubscribe(self, callback):
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify(self, key=""):
        self._revision += 1
        for callback in list(self._listeners):
            try:
                callback(self, key)
            except Exception:
                pass

    def touch(self, key=""):
        self._notify(key)

    def __setitem__(self, key, value):
        dict.__setitem__(self, key, value)
        self._notify(str(key))

    def setdefault(self, key, default=None):
        if key not in self:
            dict.__setitem__(self, key, deepcopy(default))
            self._notify(str(key))
        return dict.__getitem__(self, key)

    def update(self, *args, **kwargs):
        incoming = dict(*args, **kwargs)
        for key, value in incoming.items():
            if key in ("base_archive_collection_dir", "image_library_dir"):
                continue
            dict.__setitem__(self, key, value)
        self._apply_defaults()
        self._notify("update")

    @staticmethod
    def _nonempty_dict(value):
        return isinstance(value, dict) and bool(value)

    def _restore_archive_metadata(self):











        self.last_load_metadata_report = []
        for role, archive_key, tag_key, system_key, inventory_key in (
            ("Runtime", "runtime_base_archive", "base_image", "base_system", "base_inventory"),
            ("Builder", "builder_base_archive", "builder_image", "builder_system", "builder_inventory"),
        ):
            archive_value = str(dict.get(self, archive_key, "") or "").strip()
            if not archive_value:
                
                continue

            current_system = dict.get(self, system_key)
            current_inventory = dict.get(self, inventory_key)
            if not isinstance(current_system, dict):
                current_system = {}
                dict.__setitem__(self, system_key, {})
            if not isinstance(current_inventory, dict):
                current_inventory = {}
                dict.__setitem__(self, inventory_key, {})

            
            embedded_system = current_inventory.get("system")
            if not current_system and self._nonempty_dict(embedded_system):
                dict.__setitem__(self, system_key, deepcopy(embedded_system))
                current_system = embedded_system

            sidecar = Path(archive_value).with_suffix(".json")
            if not sidecar.is_file():
                if not current_system or not current_inventory:
                    self.last_load_metadata_report.append(
                        f"{role}: metadata sidecar unavailable ({sidecar}); "
                        "saved values preserved. Use Tab 2 to inspect the archive if needed."
                    )
                continue

            try:
                metadata = json.loads(sidecar.read_text(encoding="utf-8-sig"))
                if not isinstance(metadata, dict):
                    raise ValueError("sidecar root is not a JSON object")
            except (OSError, ValueError, UnicodeError) as exc:
                self.last_load_metadata_report.append(
                    f"{role}: could not read metadata sidecar ({sidecar}): {exc}"
                )
                continue

            inspection = metadata.get("inspection")
            if not isinstance(inspection, dict):
                inspection = {}
            inspected_system = inspection.get("system")
            if not isinstance(inspected_system, dict):
                inspected_system = {}

            updated = []
            
            
            merged_inventory = deepcopy(current_inventory)
            for field, value in inspection.items():
                if not merged_inventory.get(field) and value:
                    merged_inventory[field] = deepcopy(value)
            if merged_inventory != current_inventory:
                dict.__setitem__(self, inventory_key, merged_inventory)
                updated.append("inventory")

            merged_system = deepcopy(current_system)
            for field, value in inspected_system.items():
                if not merged_system.get(field) and value:
                    merged_system[field] = deepcopy(value)
            if merged_system != current_system:
                dict.__setitem__(self, system_key, merged_system)
                updated.append("OS/architecture/libc")
            if not str(dict.get(self, tag_key, "") or "").strip():
                sidecar_tag = str(metadata.get("docker_tag", "") or "").strip()
                if sidecar_tag:
                    dict.__setitem__(self, tag_key, sidecar_tag)
                    updated.append("Docker tag")

            if updated:
                self.last_load_metadata_report.append(
                    f"{role}: restored {', '.join(updated)} from {sidecar.name}."
                )
            elif not current_system or not current_inventory:
                self.last_load_metadata_report.append(
                    f"{role}: metadata sidecar lacks the missing inspection fields."
                )

    def load_dict(self, data, notify=True):
        if not isinstance(data, dict):
            raise ValueError("Project state must be a JSON object.")
        dict.clear(self)
        for key, value in data.items():
            if key in ("base_archive_collection_dir", "image_library_dir"):
                continue
            dict.__setitem__(self, key, deepcopy(value))
        self._apply_defaults()
        self._restore_archive_metadata()
        if notify:
            self._notify("load")
        return list(self.last_load_metadata_report)

    def snapshot(self):
        return deepcopy(dict(self))

    def save_file(self, path):
        Path(path).write_text(json.dumps(self.snapshot(), indent=2), encoding="utf-8")

    def load_file(self, path):
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return self.load_dict(data)

    def publish_base(self, archive=None, tag=None, builder_archive=None, builder_tag=None,
                     system=None, inventory=None):
        if archive is not None:
            dict.__setitem__(self, "runtime_base_archive", archive)
        if tag is not None:
            dict.__setitem__(self, "base_image", tag)
        if builder_archive is not None:
            dict.__setitem__(self, "builder_base_archive", builder_archive)
        if builder_tag is not None:
            dict.__setitem__(self, "builder_image", builder_tag)
        if system is not None:
            dict.__setitem__(self, "base_system", deepcopy(system))
        if inventory is not None:
            dict.__setitem__(self, "base_inventory", deepcopy(inventory))
        self._notify("base")

    def publish_builder(self, archive=None, tag=None, system=None, inventory=None):
        if tag or archive:
            dict.__setitem__(self, 'builder_mode', 'separate')
        if archive is not None:
            dict.__setitem__(self, "builder_base_archive", archive)
        if tag is not None:
            dict.__setitem__(self, "builder_image", tag)
        if system is not None:
            dict.__setitem__(self, "builder_system", deepcopy(system))
        if inventory is not None:
            dict.__setitem__(self, "builder_inventory", deepcopy(inventory))
        self._notify("builder_base")

    def publish_components(self, components):
        dict.__setitem__(self, "components", deepcopy(components))
        self._notify("components")
