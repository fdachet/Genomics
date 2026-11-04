import os
import posixpath
import re
from pathlib import Path

from image_removals import java_runtime_packages, normalize_removals
from java_runtime_checker import minimum_java_version
from local_package_catalog import installed_java_versions


def _names(value):
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    return [x.strip() for x in re.split(r'[,;\n]+', str(value or '')) if x.strip()]


def _capability(value):
    value = str(value or '').strip()
    return re.split(r'\s+(?:>=|<=|=|<|>)\s*', value, maxsplit=1)[0].strip().lower()


def normalize_satisfactions(rows):
    result = []
    for record in rows or []:
        if not isinstance(record, dict):
            continue
        owner = str(record.get('owner', '')).strip()
        requirement = str(record.get('requirement', '')).strip()
        provider = str(record.get('provider', '')).strip()
        if not owner or not requirement or not provider or len(provider) > 300:
            continue
        item = {'owner': owner, 'requirement': requirement, 'provider': provider,
                'status': 'USER DECLARED', 'notes': str(record.get('notes', '') or '')[:1000]}
        result = [old for old in result if (old['owner'].lower(), old['requirement'].lower()) != (owner.lower(), requirement.lower())]
        result.append(item)
    return result


def removal_matches(removal, item):
    kind = str(removal.get('kind', ''))
    name = str(removal.get('name', '')).lower()
    path = str(removal.get('path', ''))
    item_path = str(item.get('path', '') or item.get('source', ''))
    item_name = str(item.get('name', '')).lower()
    if kind == 'file' and path and item_path == path:
        return True
    if kind == 'directory' and path and (item_path == path or item_path.startswith(path.rstrip('/') + '/')):
        return True
    if kind == 'os_package' and str(item.get('package', '')).lower() == name:
        return True
    if kind in ('os_package', 'python_package', 'r_package', 'perl_package') and item_name == name:
        return True
    return False


def projected_java_versions(state, snapshot=None):
    snapshot = snapshot or {}
    inventory = state.get('base_inventory') or {}
    versions = set(installed_java_versions(inventory))
    versions.update(int(x) for x in snapshot.get('installed_java_versions', []) or [] if str(x).isdigit())
    if snapshot.get('installed_java') is not None and str(snapshot['installed_java']).isdigit():
        versions.add(int(snapshot['installed_java']))
    removed = {x['name'].lower() for x in normalize_removals(state.get('image_removals')) if x['kind'] == 'os_package'}
    for version in list(versions):
        packages = java_runtime_packages(version, inventory)
        if packages and all(package.lower() in removed for package in packages):
            versions.discard(version)
    return sorted(versions)


def _catalog(state, snapshot=None):
    snapshot = snapshot or {}
    removed = normalize_removals(state.get('image_removals'))
    present = []
    planned = []
    inventory = state.get('base_inventory') or {}
    for item in ((inventory.get('packages') or {}).get('os') or []):
        if isinstance(item, dict):
            present.append({'name': item.get('name', ''), 'path': '', 'package': item.get('name', ''), 'kind': 'OS package'})
    for kind in ('python', 'r', 'perl'):
        for item in ((inventory.get('packages') or {}).get(kind) or []):
            if isinstance(item, dict):
                present.append({'name': item.get('name', ''), 'path': item.get('path', ''), 'kind': kind + '_package'})
    for item in (inventory.get('executables') or []):
        if isinstance(item, dict):
            present.append({'name': item.get('name', ''), 'path': item.get('path', ''), 'package': item.get('package', ''), 'kind': 'file'})
    for item in snapshot.get('components', []) or []:
        if isinstance(item, dict):
            present.append({'name': item.get('name', ''), 'path': item.get('path', ''), 'kind': item.get('kind', '')})
    for item in state.get('components', []) or []:
        if isinstance(item, dict) and item.get('enabled', True):
            planned.append({'name': item.get('name', ''), 'path': item.get('destination', ''), 'kind': item.get('kind', ''), 'package': item.get('name', '') if str(item.get('kind', '')).lower() == 'os package' else ''})
    present = [item for item in present if not any(removal_matches(removal, item) for removal in removed)]
    return present, planned


def provider_choices(state, snapshot=None):
    present, planned = _catalog(state, snapshot)
    names = [str(item.get('name', '')).strip() for item in [*present, *planned]]
    names.extend('Java ' + str(version) for version in projected_java_versions(state, snapshot))
    try:
        from manual_installation_overrides import records_for_image
        for record in records_for_image(state):
            names.append(str(record.get('name', '')).strip())
            if record.get('category') == 'Java':
                major = re.match(r'^(?:1\.)?(\d+)', str(record.get('version', '')))
                if major:
                    names.append('Java ' + major.group(1))
    except Exception:
        pass
    return sorted({name for name in names if name}, key=str.casefold)


def _consumer_removed(name, path, state):
    removed = normalize_removals(state.get('image_removals'))
    item = {'name': name, 'path': path}
    return any(removal_matches(row, item) for row in removed)


def _requirements(state, snapshot, checked=None):
    consumers = []
    os_records = [item for item in (((state.get('base_inventory') or {}).get('packages') or {}).get('os') or []) if isinstance(item, dict)]
    removed_packages = {x['name'].lower() for x in normalize_removals(state.get('image_removals')) if x['kind'] == 'os_package'}
    providers = {}
    for record in os_records:
        owner = str(record.get('name', '')).strip()
        if not owner:
            continue
        capabilities = [owner, *(record.get('provides') or [])]
        for capability in capabilities:
            key = _capability(capability)
            if key:
                providers.setdefault(key, set()).add(owner.lower())
    if removed_packages:
        for record in os_records:
            owner = str(record.get('name', '')).strip()
            if not owner or owner.lower() in removed_packages:
                continue
            for required in record.get('requires', []) or []:
                capability = _capability(required)
                matches = providers.get(capability, set())
                if matches and matches.intersection(removed_packages) and not matches.difference(removed_packages):
                    consumers.append((owner, capability, 'OS capability', 'RPM dependency previously provided by ' + ', '.join(sorted(matches))))
    for item in state.get('components', []) or []:
        if not isinstance(item, dict) or not item.get('enabled', True):
            continue
        owner = str(item.get('name', '')).strip()
        if not owner:
            continue
        source = str(item.get('source', '') or '')
        if _consumer_removed(owner, source, state):
            continue
        for name in _names(item.get('depends')):
            consumers.append((owner, name, 'Component', 'Declared dependency'))
        for name in _names(item.get('runtime_packages')):
            consumers.append((owner, name, 'OS package', 'Declared runtime package'))
        if str(item.get('kind', '')).lower() == 'jar/application':
            try:
                if os.path.isfile(source):
                    consumers.append((owner, 'Java ' + str(minimum_java_version(source)) + '+', 'Java runtime', 'JAR bytecode'))
            except Exception:
                pass
    for item in snapshot.get('components', []) or []:
        if not isinstance(item, dict):
            continue
        owner = str(item.get('name', '')).strip()
        path = str(item.get('path', '') or '')
        if not owner or _consumer_removed(owner, path, state):
            continue
        if item.get('java_minimum'):
            consumers.append((owner, 'Java ' + str(item['java_minimum']) + '+', 'Java runtime', 'JAR bytecode'))
    for owner, result in (checked or {}).items():
        if _consumer_removed(owner, '', state):
            continue
        for item in result.get('libraries', []) or []:
            if not isinstance(item, dict):
                continue
            category = str(item.get('category', '') or '')
            if category in ('Shared library', 'Dynamic loader'):
                consumers.append((owner, str(item.get('name', '')), category, str(item.get('path', ''))))
    seen = set()
    for row in consumers:
        key = (row[0].lower(), row[1].lower(), row[2].lower())
        if row[1] and key not in seen:
            seen.add(key)
            yield row


def _status_for(requirement, category, state, snapshot, present, planned, checked, owner):
    name = requirement.lower()
    existing = [item for item in present if str(item.get('name', '')).lower() == name or str(item.get('path', '')).lower() == name]
    future = [item for item in planned if str(item.get('name', '')).lower() == name]
    removed = normalize_removals(state.get('image_removals'))
    if category == 'Java runtime':
        match = re.search(r'Java\s+(\d+)\+', requirement, re.I)
        minimum = int(match.group(1)) if match else None
        if minimum is not None:
            versions = projected_java_versions(state, snapshot)
            if any(version >= minimum for version in versions):
                return 'FOUND', 'Java ' + str(min(version for version in versions if version >= minimum)) + ' remains in the projected image'
            planned_versions = set()
            for item in planned:
                match = re.search(r'(?:jdk|jre|java|openjdk|temurin)[-_]?(\d+)', str(item.get('name', '')), re.I)
                if match:
                    planned_versions.add(int(match.group(1)))
            if any(version >= minimum for version in planned_versions):
                return 'PLANNED', 'A matching Java package is registered for the next build, not yet verified'
        return 'MISSING', 'No remaining inspected Java runtime satisfies this bytecode requirement'
    if existing:
        return 'FOUND', 'Available in the projected runtime image'
    if future:
        return 'PLANNED', 'Registered as a component for the next build; installation not verified'
    if category in ('Shared library', 'Dynamic loader'):
        result = (checked or {}).get(owner, {})
        lib = next((x for x in result.get('libraries', []) if str(x.get('name', '')).lower() == name), {})
        path = str(lib.get('path', '') or '')
        if any((x['kind'] == 'file' and (x['path'] == path or posixpath.basename(x['path']).lower() == name)) or
               (x['kind'] == 'directory' and path.startswith(x['path'].rstrip('/') + '/')) for x in removed):
            return 'MISSING', 'Library file is scheduled for removal: ' + path
        if any(x['kind'] == 'os_package' for x in removed):
            return 'RECHECK', 'An OS package will be removed; library ownership must be checked in the rebuilt image'
        if lib.get('status') == 'FOUND':
            return 'FOUND', path
        return 'MISSING' if lib.get('status') == 'MISSING' else 'UNRESOLVED', path or 'Library provider has not been verified'
    if any(x['name'].lower() == name for x in removed):
        return 'MISSING', 'The required component is scheduled for removal'
    return 'MISSING', 'No matching installed or planned component was identified'


def dependency_impact(state, snapshot=None, checked=None):
    snapshot = snapshot or {}
    present, planned = _catalog(state, snapshot)
    selected = {(x['owner'].lower(), x['requirement'].lower()): x for x in normalize_satisfactions(state.get('dependency_satisfactions'))}
    manual_claims = set()
    try:
        from manual_installation_overrides import records_for_image
        for claim in records_for_image(state):
            manual_claims.add(str(claim.get('name', '')).lower())
            if claim.get('category') == 'Java':
                match = re.match(r'^(?:1\.)?(\d+)', str(claim.get('version', '')))
                if match:
                    manual_claims.add('java ' + match.group(1))
    except Exception:
        pass
    rows = []
    for owner, requirement, category, detail in _requirements(state, snapshot, checked):
        status, explanation = _status_for(requirement, category, state, snapshot, present, planned, checked, owner)
        mapping = selected.get((owner.lower(), requirement.lower()))
        provider = ''
        if mapping:
            provider = mapping['provider']
            removed_names = {item['name'].lower() for item in normalize_removals(state.get('image_removals'))}
            installed_catalog = {str(item.get('name', '')).lower() for item in present}
            installed_catalog.update(str(item.get('path', '')).lower() for item in present)
            planned_catalog = {str(item.get('name', '')).lower() for item in planned}
            minimum = re.search(r'Java\s+(\d+)\+', requirement, re.I) if category == 'Java runtime' else None
            provider_version = re.search(r'(?:java|jdk|jre|openjdk|temurin)[-_\s]?(\d+)', provider, re.I) if minimum else None
            if provider.lower() in removed_names:
                status = 'MISSING'
                explanation = provider + ' is also scheduled for removal and cannot satisfy this requirement'
            elif minimum and provider_version and int(provider_version.group(1)) < int(minimum.group(1)):
                status = 'INCOMPATIBLE'
                explanation = provider + ' is below the required Java ' + minimum.group(1) + '+ version'
            elif provider.lower() in installed_catalog or provider.lower() in manual_claims or (re.fullmatch(r'Java\s+\d+', provider, re.I) and
                                                          int(provider.split()[-1]) in projected_java_versions(state, snapshot)):
                status = 'USER DECLARED'
                explanation = 'User selected ' + provider + ' as a substitute; actual compatibility is not verified'
            elif provider.lower() in planned_catalog:
                status = 'PLANNED'
                explanation = provider + ' is registered for installation, but not yet installed or verified'
            else:
                status = 'UNVERIFIED'
                explanation = 'User selected ' + provider + ', but it is not identified as present in the projected image'
        rows.append({'owner': owner, 'requirement': requirement, 'category': category,
                     'status': status, 'provider': provider, 'detail': explanation,
                     'basis': detail})
    return rows


def project_scan_result(result, removals):
    if not isinstance(result, dict):
        return {'status': 'NOT CHECKED', 'libraries': []}
    selected = normalize_removals(removals)
    if not selected:
        return result
    output = dict(result)
    output['libraries'] = [dict(item) for item in result.get('libraries', [])]
    packages_removed = any(item['kind'] in ('os_package', 'python_package', 'r_package', 'perl_package') for item in selected)
    for item in output['libraries']:
        if item.get('category') not in ('Shared library', 'Dynamic loader'):
            continue
        path = str(item.get('path', '') or '')
        name = str(item.get('name', '') or '')
        if any((row['kind'] == 'file' and (row['path'] == path or posixpath.basename(row['path']) == name)) or
               (row['kind'] == 'directory' and path.startswith(row['path'].rstrip('/') + '/')) for row in selected):
            item['status'] = 'MISSING'
            item['path'] = 'Scheduled for removal: ' + path
        elif packages_removed and item.get('status') == 'FOUND':
            item['status'] = 'UNRESOLVED'
            item['path'] = path + ' (provider ownership must be checked after removal)'
    if any(item.get('status') == 'MISSING' for item in output['libraries']):
        output['status'] = 'MISSING'
    elif any(item.get('status') == 'UNRESOLVED' for item in output['libraries']):
        output['status'] = 'INCOMPLETE'
    return output
