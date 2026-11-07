import json
import os
import tarfile
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
        if image not in tags:
            raise RuntimeError("Image TAR validation failed: the saved archive does not contain the selected Docker tag.")
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


def load_image_checkpoint(source, cancel=None, progress=None):
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(f"Docker image archive was not found: {source}")
    if progress:
        progress(f"Reading Docker TAR: {source}\n")
    try:
        tags = archive_image_tags(source)
    except (tarfile.TarError, ValueError, OSError) as exc:
        raise ValueError(f"This file is not a valid Docker image TAR: {exc}") from exc
    if not tags:
        raise ValueError("The selected archive does not contain a named Docker image. Export a named image from Tab 1.")
    metadata = read_checkpoint_metadata(source)
    preferred = str(metadata.get("docker_tag", "") or "").strip()
    if preferred and preferred not in tags:
        raise ValueError("The archive metadata refers to a Docker tag that is missing from this TAR.")
    if len(tags) > 1 and not preferred:
        raise ValueError("This TAR contains multiple image tags and has no matching checkpoint metadata. Choose a single-image TAR.")
    selected = preferred or tags[0]
    if progress:
        progress(f"Importing image {selected} into Docker Desktop...\n")
    _run(["docker", "load", "-i", str(source)], timeout=14400, idle_timeout=0, cancel=cancel, progress=progress)
    _run(["docker", "image", "inspect", "--format", "{{.Id}}", selected], timeout=60, cancel=cancel)
    inspection = metadata.get("inspection") if isinstance(metadata.get("inspection"), dict) else {}
    system = inspection.get("system") if isinstance(inspection.get("system"), dict) else {}
    if progress:
        progress(f"Confirmed Docker image: {selected}\n")
    return {"archive": str(source), "tag": selected, "inventory": inspection, "system": system, "tags": tags}
