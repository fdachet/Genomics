import hashlib
import io
import json
import posixpath
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from image_removals import normalize_removals, remove_deferred_packages
from project_state import effective_builder_image


PROVENANCE_PATH = 'opt/component-builder/component_provenance.json'


def _name(value):
    result = posixpath.normpath(str(value).replace('\\', '/').lstrip('/'))
    return '' if result in ('', '.', '..') or result.startswith('../') else result


def _read_bytes(archive, filename, limit=16 * 1024 * 1024):
    try:
        member = archive.getmember(filename)
        if not member.isfile() or member.size > limit:
            return None
        stream = archive.extractfile(member)
        return stream.read() if stream else None
    except (KeyError, OSError, ValueError):
        return None


def scan_archive_history(filename):
    archive_path = Path(filename).expanduser()
    layer_events = {}
    provenance = None
    manifest_meta = {}
    config = {}
    with tarfile.open(archive_path, 'r:*') as outer:
        manifest = json.loads(_read_bytes(outer, 'manifest.json') or b'[]')
        if not manifest:
            raise ValueError('Docker archive has no image manifest')
        manifest_meta = manifest[0]
        config = json.loads(_read_bytes(outer, manifest_meta.get('Config', '')) or b'{}')
        for i, layername in enumerate(manifest_meta.get('Layers', []), 1):
            stream = outer.extractfile(layername)
            if stream is None:
                continue
            with tarfile.open(fileobj=stream, mode='r|*') as layer:
                for member in layer:
                    name = _name(member.name)
                    if not name:
                        continue
                    leaf = posixpath.basename(name)
                    parent = posixpath.dirname(name)
                    if leaf == '.wh..wh..opq':
                        prefix = parent + '/' if parent else ''
                        for key in tuple(layer_events):
                            if key.startswith(prefix):
                                del layer_events[key]
                        continue
                    if leaf.startswith('.wh.'):
                        target = posixpath.join(parent, leaf[4:])
                        for key in tuple(layer_events):
                            if key == target or key.startswith(target + '/'):
                                del layer_events[key]
                        continue
                    if not (member.isfile() or member.issym() or member.islnk()):
                        continue
                    history = layer_events.setdefault(name, {'first_layer': i, 'last_layer': i, 'changes': 0})
                    history['last_layer'] = i
                    history['changes'] += 1
                    if name == PROVENANCE_PATH and member.isfile() and member.size < 16 * 1024 * 1024:
                        file = layer.extractfile(member)
                        if file:
                            try:
                                parsed = json.loads(file.read())
                                if isinstance(parsed, dict) and parsed.get('format') == 'component-builder-provenance-v1':
                                    provenance = parsed
                            except (ValueError, UnicodeDecodeError):
                                pass
    return {'layers': layer_events, 'provenance': provenance, 'tag': (manifest_meta.get('RepoTags') or [''])[0],
            'config_digest': manifest_meta.get('Config', '').removesuffix('.json'),
            'created': config.get('created', ''), 'layer_count': len(manifest_meta.get('Layers', []))}


def provenance_from_archive(filename):
    if not filename or not Path(filename).is_file():
        return None
    return scan_archive_history(filename)['provenance']


def provenance_from_docker(image):
    if not image:
        return None
    container = ''
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        result = subprocess.run(['docker', 'create', '--entrypoint', '/bin/sh', image], capture_output=True,
                                text=True, timeout=16, creationflags=flags)
        if result.returncode:
            return None
        container = result.stdout.strip()
        result = subprocess.run(['docker', 'cp', container + ':/' + PROVENANCE_PATH, '-'], capture_output=True,
                                timeout=16, creationflags=flags)
        if result.returncode or len(result.stdout) > 20 * 1024 * 1024:
            return None
        with tarfile.open(fileobj=io.BytesIO(result.stdout), mode='r:*') as outer:
            member = next((m for m in outer if m.isfile() and m.size < 16 * 1024 * 1024), None)
            if not member:
                return None
            data = json.load(outer.extractfile(member))
        return data if data.get('format') == 'component-builder-provenance-v1' else None
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        return None
    finally:
        if container:
            try:
                subprocess.run(['docker', 'rm', '-f', container], capture_output=True,
                               timeout=10, creationflags=flags)
            except (OSError, subprocess.TimeoutExpired):
                pass


def parent_provenance(state):
    archive = str(state.get('runtime_base_archive') or '')
    if archive and Path(archive).is_file():
        try:
            value = provenance_from_archive(archive)
            if value:
                return value
            from image_component_inventory import inspect_image_components
            inventory = inspect_image_components(archive)
            inherited = []
            for item in inventory.get('components', []):
                inherited.append({'name': item.get('name', ''), 'type': item.get('kind', ''),
                                  'path': item.get('path', ''), 'version': item.get('version', ''),
                                  'sha256': item.get('sha256', ''), 'origin': 'INHERITED / UNKNOWN',
                                  'introduced_revision': 0, 'introduced_image': '',
                                  'status': 'PRESENT', 'source_kind': 'unknown'})
            source_image = inventory.get('tag') or str(state.get('base_image') or '')
            return {'format': 'component-builder-provenance-v1', 'revision': 0,
                    'image': source_image, 'lineage': [{'revision': 0, 'image': source_image,
                    'origin': 'UNTRACKED_BASE', 'certainty': 'unknown'}], 'components': inherited,
                    'deferred_os_packages': list((inventory.get('pending') or {}).get('os_packages', []) or []),
                    'deferred_language_packages': (inventory.get('pending') or {}).get('language_packages') or {},
                    'deferred_language_versions': (inventory.get('pending') or {}).get('language_versions') or {},
                    'origin_certainty': 'INFERRED_FROM_FILESYSTEM',
                    'note': 'Existing applications were detected but their original build origin is unknown'}
        except (ValueError, OSError, tarfile.TarError):
            pass
    base = str(state.get('base_image') or '')
    return provenance_from_docker(base)


def image_identity(archive, tag):
    filename = str(archive or '')
    if filename and Path(filename).is_file():
        try:
            with tarfile.open(filename, 'r:*') as saved:
                manifest = json.loads(_read_bytes(saved, 'manifest.json') or b'[]')
                config_name = str(manifest[0].get('Config', '')) if manifest else ''
                value = config_name.removesuffix('.json')
                if value.startswith('blobs/sha256/'):
                    value = value.rsplit('/', 1)[-1]
                if len(value) == 64 and all(c in '0123456789abcdefABCDEF' for c in value):
                    return 'sha256:' + value.lower()
        except (OSError, ValueError, KeyError, tarfile.TarError):
            pass
    if tag:
        try:
            response = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', tag],
                                      capture_output=True, text=True, timeout=5,
                                      creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if response.returncode == 0:
                return response.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return ''


def make_build_provenance(state, image, manifest, skipped, pending, mode, install_now, parent=None, removals=None):
    parent = parent if isinstance(parent, dict) else None
    lineage = list(parent.get('lineage', [])) if parent else []
    if not lineage:
        lineage = [{'revision': 0, 'image': str(state.get('base_image', '')),
                    'origin': 'UNTRACKED_BASE', 'certainty': 'unknown',
                    'note': 'Original image provenance not available'}]
    revision = max((int(row.get('revision', 0)) for row in lineage if isinstance(row, dict)), default=0) + 1
    now = datetime.now(timezone.utc).isoformat()
    records = [dict(item) for item in (parent.get('components', []) if parent else []) if isinstance(item, dict)]
    removals = normalize_removals(removals)
    from revision_dependencies import normalize_satisfactions
    satisfactions = normalize_satisfactions(state.get('dependency_satisfactions'))
    removed_files = {x['path'] for x in removals if x['kind'] == 'file'}
    removed_directories = [x['path'].rstrip('/') + '/' for x in removals if x['kind'] == 'directory']
    records = [x for x in records if x.get('path') not in removed_files and
               not any(str(x.get('path', '')).startswith(directory) for directory in removed_directories)]
    preserved = {str(item.get('path', '')): i for i, item in enumerate(records) if item.get('path')}
    added = []
    source_by_name = {str(component.get('name', '')): component for component in state.get('components', [])
                      if isinstance(component, dict) and str(component.get('kind', '')).lower() == 'source'}
    for row in manifest:
        source = str(row.get('source_kind', '')).lower()
        new = {'name': str(row.get('name', '')), 'type': str(row.get('kind', '')),
               'path': str(row.get('installed', '')), 'version': str(row.get('version', '')),
               'sha256': row.get('sha256') or '', 'origin': 'BUILDER' if source == 'compiled' else 'ADDED',
               'introduced_revision': revision, 'introduced_image': image,
               'builder_image': str(state.get('builder_image') or state.get('base_image')) if source == 'compiled' else '',
               'source_kind': source, 'status': 'PRESENT_EXPECTED',
               'compiled_signature': row.get('compiled_signature') or ''}
        if source == 'compiled':
            component = source_by_name.get(new['name'], {})
            new['build_command'] = str(component.get('build_command', ''))
            new['detected_build_tools'] = list(component.get('detected_build_tools') or [])
            new['builder_tool_status'] = dict(component.get('builder_tool_status') or {})
            new['builder_tool_details'] = dict(component.get('builder_tool_details') or {})
            new['builder_package_suggestions'] = list(component.get('suggested_builder_packages') or [])
            new['build_tool_choices'] = dict(component.get('build_tool_choices') or {})
            new['manual_required_build_tools'] = list(component.get('manual_required_build_tools') or [])
            new['manual_build_packages'] = str(component.get('build_deps', ''))
        if new['path'] in preserved:
            records[preserved[new['path']]] = new
        else:
            preserved[new['path']] = len(records)
            records.append(new)
        added.append(new)
    requested = list(pending.get('os_packages') or [])
    baseline_inventory = state.get('base_inventory') or {}
    baseline_os = ((baseline_inventory.get('packages') or {}).get('os') or []) if isinstance(baseline_inventory, dict) else []
    baseline_names = {str(item.get('name', '')).lower() for item in baseline_os if isinstance(item, dict)}
    previous_requests = list((parent or {}).get('os_package_requests') or [])
    from manual_installation_overrides import records_for_image
    confirmations = records_for_image(state)
    confirmations = [dict(x, status='USER CONFIRMED', execution_verified=False, carried_from_parent=True,
                          revalidation_required=True) for x in confirmations]
    new_requests = [{'name': name, 'revision': revision,
                     'status': 'INSTALLATION_ATTEMPTED' if install_now else 'NOT INSTALLED',
                     'was_present_before': name.lower() in baseline_names if baseline_names else None,
                     'verified': False} for name in requested]
    deferred = remove_deferred_packages(list(dict.fromkeys(requested)), removals)
    runtime_id = image_identity(state.get('runtime_base_archive'), state.get('base_image', ''))
    builder_archive = state.get('builder_base_archive') or state.get('runtime_base_archive')
    builder_id = image_identity(builder_archive, effective_builder_image(state))
    previous_languages = (parent or {}).get('deferred_language_packages') or {}
    current_languages = pending.get('language_packages') or {}
    deferred_languages = {key: list(dict.fromkeys([*(previous_languages.get(key) or []), *(current_languages.get(key) or [])]))
                          for key in set(previous_languages) | set(current_languages)}
    previous_versions = (parent or {}).get('deferred_language_versions') or {}
    current_versions = pending.get('language_versions') or {}
    deferred_versions = dict(previous_versions)
    deferred_versions.update({key: val for key, val in current_versions.items() if val})
    current = {'revision': revision, 'image': image, 'parent_image': str(state.get('base_image') or ''),
               'builder_image': str(state.get('builder_image') or state.get('base_image') or ''),
               'parent_image_id': runtime_id, 'builder_image_id': builder_id,
               'time_utc': now, 'added': len(added), 'skipped': len(skipped),
               'mode': mode, 'install_requested': bool(install_now)}
    lineage.append(current)
    return {'format': 'component-builder-provenance-v1', 'revision': revision,
            'image': image, 'parent_image': current['parent_image'], 'builder_image': current['builder_image'],
            'created_utc': now, 'parent_image_id': runtime_id, 'builder_image_id': builder_id, 'lineage': lineage[-80:], 'components': records,
            'requested_os_packages': deferred,
            'manual_installation_overrides': confirmations,
            'dependency_satisfactions': [dict(x, execution_verified=False, source='USER DECLARATION') for x in satisfactions],
            'removed_this_revision': [dict(x, revision=revision, verified=False) for x in removals],
            'removal_history': ((parent or {}).get('removal_history') or []) + [dict(x, revision=revision, verified=False) for x in removals],
            'requested_language_packages': current_languages, 'requested_language_versions': current_versions,
            'os_package_requests': (previous_requests + new_requests)[-250:],
            'current_installation_requested': bool(install_now),
            'installation_verification': 'CHECK IMAGE PACKAGE DATABASE', 'requested_requirements': pending,
            'skipped_inputs': list(skipped), 'added_this_revision': added,
            'original_base': lineage[0].get('image', ''),
            'note': 'PRESENT_EXPECTED means copied during build; final image integrity and runtime availability require verification.'}


def component_origin(row, history):
    provenance = history.get('provenance') or {}
    location = str(row.get('path', '') or '')
    records = provenance.get('components', [])
    matched = next((item for item in reversed(records) if item.get('path') == location), None)
    if matched:
        saved_hash = str(matched.get('sha256') or '').lower()
        actual_hash = str(row.get('sha256') or '').lower()
        if saved_hash and actual_hash and saved_hash != actual_hash:
            return {'origin': 'UNKNOWN (CHECKSUM MISMATCH)', 'revision': None, 'status': 'PRESENT',
                    'certainty': 'mismatch', 'builder': '',
                    'layer': (history.get('layers') or {}).get(location.lstrip('/'), {}).get('last_layer')}
        return {'origin': str(matched.get('origin') or 'UNKNOWN'), 'revision': matched.get('introduced_revision'),
                'status': 'PRESENT', 'certainty': 'recorded', 'builder': matched.get('builder_image', ''),
                'layer': (history.get('layers') or {}).get(location.lstrip('/'), {}).get('last_layer')}
    info = (history.get('layers') or {}).get(location.lstrip('/'), {})
    return {'origin': 'UNKNOWN', 'revision': None, 'status': 'PRESENT', 'certainty': 'layer only',
            'layer': info.get('last_layer'), 'builder': ''}
