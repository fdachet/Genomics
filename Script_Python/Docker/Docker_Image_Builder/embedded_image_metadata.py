import json
import posixpath
import tarfile
from pathlib import Path


INVENTORY_PATH = 'opt/component-builder/image_inventory.json'
PROVENANCE_PATH = 'opt/component-builder/component_provenance.json'
FORMAT = 'component-builder-embedded-inventory-v1'


def _normal_path(value):
    return posixpath.normpath(str(value or '').replace('\\', '/').lstrip('./').lstrip('/'))


def read_embedded_image_metadata(archive_path, preferred_tag=''):
    archive_path = Path(archive_path)
    if not archive_path.is_file():
        return {}
    with tarfile.open(str(archive_path), 'r:*') as outer:
        source = outer.extractfile('manifest.json')
        manifest = json.load(source) if source else []
        if not isinstance(manifest, list) or not manifest:
            return {}
        chosen = next((entry for entry in manifest if preferred_tag and preferred_tag in (entry.get('RepoTags') or [])), manifest[0])
        layers = chosen.get('Layers') or []
        if not layers:
            return {}
        layer = outer.extractfile(layers[-1])
        if layer is None:
            return {}
        payload = None
        provenance = None
        with tarfile.open(fileobj=layer, mode='r|*') as members:
            for member in members:
                path = _normal_path(member.name)
                if path not in (INVENTORY_PATH, PROVENANCE_PATH) or not member.isfile() or member.size > 32 * 1024 * 1024:
                    continue
                stream = members.extractfile(member)
                if stream is None:
                    continue
                try:
                    record = json.load(stream)
                except (ValueError, UnicodeError):
                    continue
                if path == INVENTORY_PATH:
                    payload = record
                elif path == PROVENANCE_PATH:
                    provenance = record
        if not isinstance(payload, dict) or payload.get('format') != FORMAT:
            return {}
        inspection = payload.get('inspection')
        if not isinstance(inspection, dict) or inspection.get('schema') != 6:
            return {}
        if not isinstance(inspection.get('executables'), list) or not isinstance(inspection.get('packages'), dict):
            return {}
        config_name = str(chosen.get('Config') or '')
        config_hash = config_name.rsplit('/', 1)[-1].removesuffix('.json')
        image_id = 'sha256:' + config_hash if len(config_hash) == 64 and all(c in '0123456789abcdefABCDEF' for c in config_hash) else ''
        config = {}
        try:
            stream = outer.extractfile(config_name)
            if stream:
                config = json.load(stream)
        except (KeyError, ValueError, TypeError, OSError):
            pass
        tag = (chosen.get('RepoTags') or [''])[0]
        inspection = dict(inspection)
        inspection['image_id'] = image_id
        inspection['docker_tag'] = preferred_tag if preferred_tag in (chosen.get('RepoTags') or []) else tag
        inspection['inventory_method'] = 'embedded_image'
        inspection['archive_tag'] = tag
        rootfs = config.get('rootfs') or {}
        inspection['rootfs_diff_ids'] = list(rootfs.get('diff_ids') or []) if isinstance(rootfs, dict) else []
        if isinstance(provenance, dict):
            inspection['provenance'] = provenance
        elif isinstance(payload.get('provenance'), dict):
            inspection['provenance'] = payload['provenance']
        probes = payload.get('version_probes')
        if not isinstance(probes, dict):
            probes = {}
        return {
            'docker_tag': inspection['docker_tag'],
            'inspection': inspection,
            'version_probes': probes,
            'os': inspection.get('system', {}).get('os', ''),
            'architecture': inspection.get('system', {}).get('architecture', ''),
            'checkpoint_format': FORMAT,
        }
