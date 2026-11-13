import json
import os
import subprocess
import tempfile
import tarfile
import time
import uuid
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

from package_repository_finder import _run
from embedded_image_metadata import read_embedded_image_metadata, FORMAT


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


@lru_cache(maxsize=32)
def _read_embedded_cached(path, size, mtime_ns):
    return read_embedded_image_metadata(path)


def read_checkpoint_metadata(path):
    try:
        stat = Path(path).stat()
        embedded = _read_embedded_cached(str(Path(path).resolve()), stat.st_size, stat.st_mtime_ns)
        if embedded:
            return deepcopy(embedded)
    except (tarfile.TarError, OSError, KeyError, ValueError, TypeError):
        pass
    sidecar = checkpoint_sidecar_path(path)
    if not sidecar.is_file():
        return {}
    try:
        data = json.loads(sidecar.read_text(encoding='utf-8-sig'))
    except (ValueError, OSError, UnicodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _image_id(image, cancel=None):
    return _run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], timeout=60, cancel=cancel).strip()


def _embed_inventory_in_image(image, inventory=None, provenance=None, progress=None, cancel=None):
    from image_filesystem_inventory import inspect_tag_via_export
    image_id_before = _image_id(image, cancel)
    ready = (isinstance(inventory, dict) and inventory.get('schema') == 6
             and inventory.get('image_id') == image_id_before
             and isinstance(inventory.get('executables'), list)
             and isinstance(inventory.get('packages'), dict))
    if ready:
        snapshot = deepcopy(inventory)
        if progress:
            progress('Using matching installed-software inventory from this image.\n')
    else:
        if progress:
            progress('Inspecting installed software before embedding image inventory.\n')
        snapshot = inspect_tag_via_export(
            image,
            report=(lambda kind, value: progress('Inventory: ' + str(value) + '\n')
                    if progress and kind == 'stage' else None),
            cancel=cancel,
            timeout=600,
        )
    parent_provenance = snapshot.get('provenance')
    if not isinstance(provenance, dict):
        provenance = parent_provenance if isinstance(parent_provenance, dict) else None
    if provenance is None:
        provenance = {
            'provenance_status': 'NOT_AVAILABLE',
            'source_image': image,
            'source_image_id': image_id_before,
            'components': [],
            'note': 'No component-builder provenance was present in the source image; past installations cannot be reconstructed from this record.',
        }
    snapshot['provenance'] = provenance
    snapshot.pop('image_id', None)
    snapshot.pop('rootfs_diff_ids', None)
    snapshot.pop('archive_tag', None)
    snapshot['docker_tag'] = image
    version_probes = {}
    for item in snapshot.get('executables') or []:
        if not isinstance(item, dict) or not item.get('version') or not item.get('path'):
            continue
        if item.get('version_source') in ('saved', 'runtime', 'package'):
            version_probes[item['path']] = {
                key: item.get(key, '') for key in ('name', 'version', 'version_source', 'package', 'package_version')
            }
    payload = {
        'format': FORMAT,
        'inspection': snapshot,
        'version_probes': version_probes,
    }
    with tempfile.TemporaryDirectory(prefix='component-builder-embedded-') as temp:
        folder = Path(temp)
        (folder / 'image_inventory.json').write_text(json.dumps(payload, indent=2), encoding='utf-8')
        dockerfile = ['FROM ' + image, 'COPY ["image_inventory.json", "/opt/component-builder/image_inventory.json"]']
        (folder / 'component_provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
        dockerfile.append('COPY ["component_provenance.json", "/opt/component-builder/component_provenance.json"]')
        (folder / 'Dockerfile').write_text('\n'.join(dockerfile) + '\n', encoding='utf-8')
        if progress:
            progress('Embedding inventory and provenance in an actual Docker image filesystem layer.\n')
        _run(['docker', 'build', '--pull=false', '--network=none', '--progress=plain', '-t', image, str(folder)],
             timeout=1800, idle_timeout=0, cancel=cancel, progress=progress)
    image_id_after = _image_id(image, cancel)
    if image_id_after == image_id_before:
        raise RuntimeError('Embedded metadata build did not create a new image configuration.')
    if progress:
        progress('Metadata embedded in Docker image; original and new image IDs are different as expected.\n')
    snapshot['image_id'] = image_id_after
    snapshot['inventory_method'] = 'embedded_image'
    return {'image_id': image_id_after, 'inspection': snapshot, 'embedded': True}


def save_image_checkpoint(image, destination, system=None, inventory=None, cancel=None, progress=None):
    image = str(image or '').strip()
    destination = Path(destination)
    if not image:
        raise ValueError('No Docker image is selected for the checkpoint.')
    if destination.suffix.lower() != '.tar' or not destination.parent.is_dir():
        raise ValueError('Choose a .tar filename inside an existing directory.')
    _image_id(image, cancel)
    temporary = destination.with_name(destination.name + '.pending-' + uuid.uuid4().hex)
    try:
        prepared = _embed_inventory_in_image(image, inventory=inventory, progress=progress, cancel=cancel)
        _run(['docker', 'save', '-o', str(temporary), image], timeout=14400,
             idle_timeout=0, cancel=cancel, progress=progress)
        if not temporary.is_file() or not temporary.stat().st_size:
            raise RuntimeError('Docker did not create a nonempty saved image TAR.')
        tags = archive_image_tags(temporary)
        if not archive_has_image_tag(tags, image):
            raise RuntimeError('Saved image TAR does not contain the requested Docker tag.')
        embedded = read_embedded_image_metadata(temporary, preferred_tag=image)
        if not embedded:
            raise RuntimeError('Saved image TAR is missing its embedded inspection metadata.')
        os.replace(temporary, destination)
        if progress:
            progress(f'Saved self-contained image TAR: {destination} ({destination.stat().st_size / 1000000:.1f} MB)\n')
        return {'archive': str(destination), 'tag': image, 'metadata': embedded,
                'tags': tags, 'system': embedded['inspection'].get('system', {}),
                'inventory': embedded['inspection'], 'image_id': prepared['image_id']}
    finally:
        if temporary.exists():
            temporary.unlink()


def save_full_image_to_tar(image, destination, cancel=None, progress=None, overwrite=False, inventory=None, provenance=None):
    image = str(image or '').strip()
    destination = Path(destination)
    if not image:
        raise ValueError('No complete Docker image is available to export.')
    if destination.suffix.lower() != '.tar' or not destination.parent.is_dir():
        raise ValueError('Choose a .tar filename inside an existing directory.')
    if destination.exists() and not overwrite:
        raise FileExistsError('This TAR already exists. Choose a new filename or approve replacement: ' + str(destination))
    _image_id(image, cancel)
    temporary = destination.with_name(destination.name + '.pending-' + uuid.uuid4().hex)
    try:
        prepared = _embed_inventory_in_image(image, inventory=inventory, provenance=provenance,
                                             progress=progress, cancel=cancel)
        if progress:
            progress('Exporting self-contained Docker image ' + image + ' to TAR.\n')
        _run(['docker', 'save', '-o', str(temporary), image], timeout=14400, idle_timeout=0, cancel=cancel)
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError('Docker did not create a nonempty complete-image TAR.')
        tags = archive_image_tags(temporary)
        if not archive_has_image_tag(tags, image):
            raise RuntimeError('Final TAR validation failed. Requested: ' + canonical_image_tag(image) + '; available: ' + (', '.join(tags) or 'none'))
        embedded = read_embedded_image_metadata(temporary, preferred_tag=image)
        if not embedded:
            raise RuntimeError('Image TAR did not retain its embedded inventory and provenance layer.')
        if destination.exists() and not overwrite:
            raise FileExistsError('The complete-image TAR filename was created by another process: ' + str(destination))
        os.replace(temporary, destination)
        if progress:
            progress('COMPLETE IMAGE TAR: ' + str(destination) + ' (' + f'{destination.stat().st_size / 1000000:.1f}' + ' MB)\n')
        return {'archive': str(destination), 'tag': image, 'image_id': prepared['image_id'], 'metadata': embedded, 'inventory': embedded['inspection']}
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
