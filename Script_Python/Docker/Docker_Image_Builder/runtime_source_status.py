import posixpath
from pathlib import Path


def expected_runtime_path(state, component):
    kind = str(component.get('kind', '')).strip().lower()
    if kind not in ('source', 'binary', 'script', 'jar/application', 'folder', 'other'):
        return ''
    destination = str(component.get('destination') or '').strip().replace('\\', '/')
    if not destination.startswith('/') or any(part in ('.', '..') for part in destination.split('/')):
        return ''
    output = str(component.get('output_rel') or '').strip().replace('\\', '/') if kind == 'source' else ''
    record = (state.get('compiled_artifacts') or {}).get(str(component.get('name') or '')) or {}
    filename = posixpath.basename(output.rstrip('/')) if output else ''
    if not filename and kind == 'source' and isinstance(record, dict):
        filename = Path(str(record.get('artifact') or '')).name
    if not filename and kind != 'source':
        filename = posixpath.basename(str(component.get('source') or '').replace('\\', '/').rstrip('/'))
    if not filename or filename in ('.', '..'):
        return ''
    return posixpath.normpath(posixpath.join(destination, filename))


def runtime_component_status(state, component):
    path = expected_runtime_path(state, component)
    image = str(state.get('base_image') or '').strip()
    if not image or not path:
        return None
    inventory = state.get('base_inventory') or {}
    if not isinstance(inventory, dict):
        inventory = {}
    inventory_tag = str(inventory.get('docker_tag') or inventory.get('tag') or '').strip()
    if inventory_tag and inventory_tag not in (image, image + ':latest') and image != inventory_tag + ':latest':
        inventory = {}
    kind = str(component.get('kind', '')).strip().lower()
    executables = inventory.get('executables') or []
    if isinstance(executables, list):
        for entry in executables:
            if not isinstance(entry, dict):
                continue
            located = str(entry.get('path') or '').replace('\\', '/')
            if located and posixpath.normpath('/' + located.lstrip('/')) == path:
                return {'path': path, 'image': image, 'verified': True,
                        'version': str(entry.get('version') or component.get('version') or ''),
                        'source': 'runtime executable inventory'}
    packages = inventory.get('packages') or {}
    jars = packages.get('jars') or [] if isinstance(packages, dict) else []
    if kind == 'jar/application':
        for entry in jars:
            located = str(entry.get('path') if isinstance(entry, dict) else entry).replace('\\', '/')
            if located and posixpath.normpath('/' + located.lstrip('/')) == path:
                return {'path': path, 'image': image, 'verified': True,
                        'version': str(component.get('version') or ''), 'source': 'runtime JAR inventory'}
    if inventory.get('inspected_at') and kind in ('source', 'binary', 'script', 'jar/application'):
        return None
    provenance = inventory.get('provenance') or {}
    records = (provenance.get('components') or []) if isinstance(provenance, dict) else []
    for entry in records:
        if not isinstance(entry, dict):
            continue
        if posixpath.normpath(str(entry.get('path') or '')) == path and (kind != 'source' or entry.get('source_kind') == 'compiled'):
            return {'path': path, 'image': image, 'verified': False,
                    'version': str(entry.get('version') or component.get('version') or ''),
                    'source': 'runtime image provenance', 'sha256': entry.get('sha256') or ''}
    report = state.get('last_build_report') or {}
    if isinstance(report, dict) and report.get('build_succeeded') and str(report.get('image') or '') == image:
        for entry in report.get('installed_components') or []:
            if not isinstance(entry, dict):
                continue
            if posixpath.normpath(str(entry.get('installed') or '')) == path and (kind != 'source' or entry.get('source_kind') == 'compiled'):
                return {'path': path, 'image': image, 'verified': False,
                        'version': str(entry.get('version') or component.get('version') or ''),
                        'source': 'successful image build report', 'sha256': entry.get('sha256') or ''}
    receipt = state.get('runtime_install_receipt') or {}
    if isinstance(receipt, dict) and str(receipt.get('image') or '') == image:
        for entry in (receipt.get('installed_components') or []) + (receipt.get('inherited_components') or []):
            if not isinstance(entry, dict):
                continue
            located = str(entry.get('installed') or entry.get('path') or '')
            if posixpath.normpath(located) == path:
                return {'path': path, 'image': image, 'verified': False,
                        'version': str(entry.get('version') or component.get('version') or ''),
                        'source': 'completed image revision record', 'sha256': entry.get('sha256') or ''}
    return None


def runtime_source_status(state, component):
    if str(component.get('kind', '')).strip().lower() != 'source':
        return None
    return runtime_component_status(state, component)


def runtime_compiled_inventory(state):
    output = []
    for component in state.get('components') or []:
        if not isinstance(component, dict):
            continue
        found = runtime_component_status(state, component)
        if not found or not found['verified']:
            continue
        kind = str(component.get('kind') or '').lower()
        output.append({'name': str(component.get('name') or ''), 'path': found['path'],
                       'kind': 'binary' if kind == 'source' else kind,
                       'version': found['version'], 'present_in_image': True,
                       'origin': 'BUILDER' if kind == 'source' else 'ADDED',
                       'status': 'PRESENT' if found['verified'] else 'PRESENT_EXPECTED',
                       'certainty': 'runtime inventory' if found['verified'] else found['source']})
    return output


def verified_image_components(state):
    inventory = state.get('base_inventory') or {}
    if not isinstance(inventory, dict) or not inventory.get('inspected_at'):
        return []
    image = str(state.get('base_image') or '').strip()
    inventory_tag = str(inventory.get('docker_tag') or inventory.get('tag') or '').strip()
    if inventory_tag and image not in (inventory_tag, inventory_tag.removesuffix(':latest')):
        return []
    executables = {
        posixpath.normpath(str(item.get('path') or '')): item
        for item in inventory.get('executables') or []
        if isinstance(item, dict) and str(item.get('path') or '').startswith('/')
    }
    packages = inventory.get('packages') or {}
    jars = {
        posixpath.normpath(str(item.get('path') if isinstance(item, dict) else item))
        for item in (packages.get('jars') or [] if isinstance(packages, dict) else [])
        if item
    }
    result = {}
    provenance = inventory.get('provenance') or {}
    records = provenance.get('components') or [] if isinstance(provenance, dict) else []
    for entry in records:
        if not isinstance(entry, dict):
            continue
        path = posixpath.normpath(str(entry.get('path') or ''))
        if not path.startswith('/') or path not in executables and path not in jars:
            continue
        name = str(entry.get('name') or posixpath.basename(path))
        version = str(entry.get('version') or executables.get(path, {}).get('version') or '')
        kind = str(entry.get('type') or 'Binary')
        key = (path, name.casefold())
        result[key] = {
            'name': name,
            'path': path,
            'version': version,
            'kind': kind,
            'origin': str(entry.get('origin') or 'INHERITED / UNKNOWN'),
            'revision': entry.get('introduced_revision'),
            'present_in_image': True,
            'status': 'PRESENT',
            'certainty': 'verified by filesystem inventory',
        }
    for component in state.get('components') or []:
        if not isinstance(component, dict):
            continue
        found = runtime_component_status(state, component)
        if not found or not found.get('verified'):
            continue
        name = str(component.get('name') or '')
        kind = str(component.get('kind') or '')
        path = found['path']
        key = (path, name.casefold())
        if key not in result:
            result[key] = {
                'name': name, 'path': path, 'version': found.get('version') or '',
                'kind': 'Binary (Built from Source)' if kind.lower() == 'source' else kind,
                'origin': 'BUILDER' if kind.lower() == 'source' else 'ADDED',
                'revision': None, 'present_in_image': True,
                'status': 'PRESENT', 'certainty': 'verified by filesystem inventory',
            }
    return sorted(result.values(), key=lambda item: (item['name'].casefold(), item['path']))
