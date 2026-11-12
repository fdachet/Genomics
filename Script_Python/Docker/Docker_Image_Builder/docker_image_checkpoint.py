import json
import os
import tarfile
import time
import uuid
from copy import deepcopy
from pathlib import Path

from package_repository_finder import _run


def archive_image_tags(path):
    tags = []
    with tarfile.open(path, "r:*") as archive:
        try:
            stream = archive.extractfile("manifest.json")
            manifest = json.load(stream) if stream else []
            if not isinstance(manifest, list):
                raise ValueError("Docker image manifest is invalid.")
            for image in manifest:
                for tag in image.get("RepoTags") or []:
                    if isinstance(tag, str) and tag and tag not in tags:
                        tags.append(tag)
        except KeyError:
            pass
        if not tags:
            try:
                stream = archive.extractfile("repositories")
                repositories = json.load(stream) if stream else {}
                for repository, versions in repositories.items():
                    for version in versions:
                        tag = f"{repository}:{version}"
                        if tag not in tags:
                            tags.append(tag)
            except KeyError:
                pass
    return tags


def canonical_image_tag(tag):
    tag = str(tag or '').strip()
    if not tag or tag.startswith('sha256:') or '@' in tag:
        return tag
    if ':' not in tag.rsplit('/', 1)[-1]:
        return tag + ':latest'
    return tag


def archive_has_image_tag(tags, image):
    wanted = canonical_image_tag(image)
    return wanted in {canonical_image_tag(tag) for tag in tags}


def checkpoint_sidecar_path(path):
    return Path(path).with_suffix(".json")


def read_checkpoint_metadata(path):
    sidecar = checkpoint_sidecar_path(path)
    if not sidecar.is_file():
        return {}
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError, UnicodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_image_checkpoint(image, destination, system=None, inventory=None, cancel=None, progress=None):
    image = str(image or "").strip()
    destination = Path(destination)
    if not image:
        raise ValueError("No Docker image is selected. Select or inspect the image in Tab 1/2 first.")
    if destination.suffix.lower() != ".tar":
        raise ValueError("Select a .tar file for the saved Docker image.")
    if not destination.parent.is_dir():
        raise ValueError("The selected destination folder does not exist.")
    sidecar = checkpoint_sidecar_path(destination)
    if sidecar.exists():
        existing = read_checkpoint_metadata(destination)
        if not existing.get("docker_tag") or not isinstance(existing.get("inspection"), dict):
            raise ValueError(f"An unrelated JSON file already uses the checkpoint metadata path: {sidecar}. Choose a different TAR filename.")
    _run(["docker", "image", "inspect", "--format", "{{.Id}}", image], timeout=60, cancel=cancel)
    temporary = destination.with_name(destination.name + ".pending-" + uuid.uuid4().hex)
    temporary_sidecar = sidecar.with_name(sidecar.name + ".pending-" + uuid.uuid4().hex)
    try:
        if progress:
            progress("Saving the existing Docker image without rebuilding it. Large images may take several minutes.\n")
        _run(["docker", "save", "-o", str(temporary), image], timeout=14400, idle_timeout=0, cancel=cancel)
        if not temporary.is_file() or not temporary.stat().st_size:
            raise RuntimeError("Docker reported success but did not create a nonempty TAR archive.")
        tags = archive_image_tags(temporary)
        if not archive_has_image_tag(tags, image):
            raise RuntimeError("Image TAR validation failed. Requested: " + canonical_image_tag(image) + "; available: " + (", ".join(tags) or "none"))
        details = deepcopy(inventory) if isinstance(inventory, dict) else {}
        selected_system = deepcopy(system) if isinstance(system, dict) else {}
        if selected_system:
            details["system"] = selected_system
        metadata = {
            "docker_tag": image,
            "inspection": details,
            "checkpoint_format": "component-image-builder-1",
        }
        temporary_sidecar.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        os.replace(temporary, destination)
        os.replace(temporary_sidecar, sidecar)
        if progress:
            progress(f"Saved {destination.stat().st_size / 1000000:.1f} MB Docker TAR: {destination}\n")
            progress(f"Saved image inventory metadata: {sidecar}\n")
        return {"archive": str(destination), "tag": image, "metadata": metadata, "tags": tags}
    finally:
        if temporary.exists():
            temporary.unlink()
        if temporary_sidecar.exists():
            temporary_sidecar.unlink()


def save_full_image_to_tar(image, destination, cancel=None, progress=None, overwrite=False):
    image = str(image or '').strip()
    destination = Path(destination)
    if not image:
        raise ValueError('No complete Docker image is available to export.')
    if destination.suffix.lower() != '.tar' or not destination.parent.is_dir():
        raise ValueError('Choose a .tar filename inside an existing directory.')
    if destination.exists() and not overwrite:
        raise FileExistsError('This TAR already exists. Choose a new filename or approve replacement: ' + str(destination))
    _run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], timeout=60, cancel=cancel)
    temporary = destination.with_name(destination.name + '.pending-' + uuid.uuid4().hex)
    try:
        if progress:
            progress('Exporting FULL Docker image ' + image + ' to TAR. Large images may take several minutes.\n')
        _run(['docker', 'save', '-o', str(temporary), image], timeout=14400, idle_timeout=0, cancel=cancel)
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError('Docker did not create a nonempty complete-image TAR.')
        tags = archive_image_tags(temporary)
        if not archive_has_image_tag(tags, image):
            raise RuntimeError('Final TAR validation failed. Requested: ' + canonical_image_tag(image) + '; available: ' + (', '.join(tags) or 'none'))
        if destination.exists() and not overwrite:
            raise FileExistsError('The complete-image TAR filename was created by another process: ' + str(destination))
        os.replace(temporary, destination)
        if progress:
            progress('COMPLETE IMAGE TAR: ' + str(destination) + ' (' + f'{destination.stat().st_size / 1000000:.1f}' + ' MB)\n')
        return {'archive': str(destination), 'tag': image}
    finally:
        if temporary.exists():
            temporary.unlink()


def _normalize_digest(value):
    value = str(value or "").strip().lower()
    if value.startswith("sha256:"):
        value = value[7:]
    if len(value) == 64 and all(c in "0123456789abcdef" for c in value):
        return "sha256:" + value
    return ""


def _normalize_layers(value):
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(_normalize_digest(item) for item in value)


def archive_image_entries(path):
    entries = []
    with tarfile.open(path, "r:*") as archive:
        stream = archive.extractfile("manifest.json")
        manifest = json.load(stream) if stream else []
        if not isinstance(manifest, list) or not manifest:
            raise ValueError("The TAR does not contain a valid Docker save manifest.")
        for entry in manifest:
            if not isinstance(entry, dict):
                continue
            config_name = str(entry.get("Config") or "")
            digest = config_name.rsplit("/", 1)[-1].removesuffix(".json")
            image_id = _normalize_digest(digest)
            tags = [tag for tag in entry.get("RepoTags") or [] if isinstance(tag, str) and tag.strip()]
            config = {}
            if config_name:
                try:
                    stream = archive.extractfile(config_name)
                    if stream:
                        config = json.loads(stream.read(4 * 1024 * 1024))
                except (KeyError, ValueError, OSError, TypeError):
                    pass
            rootfs = config.get("rootfs") or config.get("RootFS") or {}
            diff_ids = _normalize_layers(rootfs.get("diff_ids") or rootfs.get("Layers") or []) if isinstance(rootfs, dict) else ()
            entries.append({
                "tags": tags,
                "image_id": image_id,
                "config": config_name,
                "rootfs_layers": diff_ids,
                "architecture": str(config.get("architecture") or config.get("Architecture") or "").lower(),
                "os": str(config.get("os") or config.get("Os") or "").lower(),
            })
    if not entries:
        raise ValueError("The Docker save manifest contains no usable image configuration.")
    return entries


def _loaded_image_details(image, cancel=None):
    try:
        output = _run(["docker", "image", "inspect", "--format", "{{json .}}", image],
                      timeout=40, idle_timeout=0, cancel=cancel)
        data = json.loads(output.strip().splitlines()[-1])
    except (RuntimeError, ValueError, OSError, IndexError, TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    rootfs = data.get("RootFS") or data.get("rootfs") or {}
    return {
        "image_id": _normalize_digest(data.get("Id") or data.get("ID")),
        "rootfs_layers": _normalize_layers(rootfs.get("Layers") or rootfs.get("diff_ids") or []) if isinstance(rootfs, dict) else (),
        "architecture": str(data.get("Architecture") or data.get("architecture") or "").lower(),
        "os": str(data.get("Os") or data.get("os") or "").lower(),
        "name": image,
    }


def _loaded_image_id(image, cancel=None):
    return _loaded_image_details(image, cancel).get("image_id", "")


def _image_configuration_matches(entry, details):
    if not details or not details.get("image_id"):
        return False
    if entry.get("image_id") and entry["image_id"] == details["image_id"]:
        return True
    layers = entry.get("rootfs_layers") or ()
    loaded_layers = details.get("rootfs_layers") or ()
    if not layers or not loaded_layers or layers != loaded_layers or not all(layers):
        return False
    for field in ("architecture", "os"):
        if entry.get(field) and details.get(field) and entry[field] != details[field]:
            return False
    return True


def docker_image_matches_tar(archive, tag, cancel=None, entries=None):
    details = _loaded_image_details(tag, cancel)
    if not details:
        return False
    if entries is None:
        entries = archive_image_entries(archive)
    tagged = [entry for entry in entries if tag in entry["tags"]]
    candidates = tagged or entries
    return any(_image_configuration_matches(entry, details) for entry in candidates)


def load_image_checkpoint(source, cancel=None, progress=None):
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(f"Docker image archive was not found: {source}")
    if progress:
        progress(f"Reading Docker TAR: {source}\n")
    try:
        entries = archive_image_entries(source)
    except (tarfile.TarError, ValueError, OSError, KeyError) as exc:
        raise ValueError(f"This file is not a valid Docker save TAR: {exc}") from exc
    metadata = read_checkpoint_metadata(source)
    preferred = str(metadata.get("docker_tag", "") or "").strip()
    matching = next((entry for entry in entries if preferred and preferred in entry["tags"]), None)
    chosen = matching or next((entry for entry in entries if entry["tags"]), entries[0])
    tags = list(dict.fromkeys(tag for entry in entries for tag in entry["tags"]))
    selected = preferred if matching else (chosen["tags"][0] if chosen["tags"] else "")
    expected_id = chosen["image_id"]
    candidates = [entry for entry in entries if selected in entry["tags"]] if selected else [chosen]
    if not selected and not expected_id:
        raise ValueError("The TAR has no usable named image or identifiable image ID.")
    before = _loaded_image_details(selected, cancel) if selected else {}
    if progress:
        progress(f"Importing image {selected or expected_id} into Docker Desktop...\n")
    load_output = _run(["docker", "load", "-i", str(source)], timeout=14400,
                       idle_timeout=0, cancel=cancel, progress=progress)
    details = {}
    for attempt in range(9):
        if cancel is not None and cancel.is_set():
            raise RuntimeError("Docker image load was cancelled.")
        details = _loaded_image_details(selected, cancel) if selected else {}
        if details and any(_image_configuration_matches(entry, details) for entry in candidates):
            break
        if attempt < 8:
            time.sleep(.25)
    if not details or not any(_image_configuration_matches(entry, details) for entry in candidates):
        recovered = {}
        for entry in candidates:
            if not entry["image_id"]:
                continue
            check = _loaded_image_details(entry["image_id"], cancel)
            if _image_configuration_matches(entry, check):
                recovered = check
                break
        if recovered and selected:
            if progress:
                progress("Restored image was found by configuration ID; applying its saved Docker tag.\n")
            _run(["docker", "tag", recovered["image_id"], selected], timeout=60,
                 idle_timeout=0, cancel=cancel)
            details = _loaded_image_details(selected, cancel)
        elif recovered:
            details = recovered
    if not details or not details.get("image_id"):
        raise RuntimeError(
            "Docker load reported completion, but the restored image could not be inspected.\n"
            f"Saved tag: {selected or '(unnamed)'}\n"
            f"Docker load output: {load_output[-1300:]}\n"
            "Verify that Docker Desktop is running with Linux containers and retry."
        )
    matched = next((entry for entry in candidates if _image_configuration_matches(entry, details)), None)
    if not matched:
        old_id = before.get("image_id", "")
        still_old = bool(old_id and details["image_id"] == old_id)
        raise RuntimeError(
            "Docker loaded the TAR, but the selected Docker tag does not match its image filesystem.\n"
            f"Tag: {selected or '(unnamed)'}\n"
            f"TAR configuration ID: {expected_id or '(unavailable)'}\n"
            f"Current Docker image ID: {details['image_id']}\n"
            f"Tag unchanged from before import: {'YES' if still_old else 'NO'}\n"
            "The archive was not replaced by an unrelated local image. Check the Docker load output and image platform."
        )
    loaded_id = details["image_id"]
    if not selected:
        selected = "restored-image:" + loaded_id.split(":")[-1][:12]
        _run(["docker", "tag", loaded_id, selected], timeout=60, idle_timeout=0, cancel=cancel)
        if not _loaded_image_details(selected, cancel).get("image_id"):
            raise RuntimeError("Could not tag the restored unnamed Docker image.")
    inspection = metadata.get("inspection") if isinstance(metadata.get("inspection"), dict) else {}
    if inspection and inspection.get("image_id") not in (loaded_id, matched.get("image_id")):
        inspection = {}
    system = inspection.get("system") if isinstance(inspection.get("system"), dict) else {}
    if progress:
        method = "configuration ID" if matched.get("image_id") == loaded_id else "matching filesystem layers and platform"
        progress(f"Verified loaded Docker image by {method}: {selected} ({loaded_id})\n")
    return {"archive": str(source), "tag": selected, "image_id": loaded_id,
            "inventory": inspection, "system": system, "tags": tags}
