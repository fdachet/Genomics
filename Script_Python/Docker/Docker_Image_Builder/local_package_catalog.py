import re
import struct
from pathlib import Path


EXTENSIONS = {'.rpm': 'rpm', '.deb': 'apt', '.apk': 'apk'}


def package_archive_type(path):
    return EXTENSIONS.get(Path(str(path)).suffix.lower(), '')


def _rpm_header(path):
    file = Path(str(path))
    if not file.is_file():
        return {}
    try:
        with file.open('rb') as stream:
            lead = stream.read(96)
            if len(lead) != 96 or lead[:4] != b'\xed\xab\xee\xdb':
                return {}
            for index in range(2):
                start = stream.tell()
                header = stream.read(16)
                if len(header) != 16 or header[:3] != b'\x8e\xad\xe8':
                    return {}
                count, size = struct.unpack('>II', header[8:16])
                if count > 50000 or size > 32 * 1024 * 1024:
                    return {}
                entries = stream.read(16 * count)
                data = stream.read(size)
                if len(entries) != 16 * count or len(data) != size:
                    return {}
                if index == 0:
                    stream.seek((stream.tell() + 7) // 8 * 8)
                    continue
                result = {}
                for offset in range(0, len(entries), 16):
                    tag, kind, position, number = struct.unpack('>IIII', entries[offset:offset + 16])
                    if tag not in (1000, 1001, 1002, 1022) or kind not in (6, 8, 9) or position >= len(data):
                        continue
                    value = data[position:].split(b'\x00', 1)[0].decode('utf-8', 'replace').strip()
                    result[tag] = value
                return result
    except (OSError, ValueError, struct.error, OverflowError):
        return {}
    return {}


def _oracle_jdk_name(name):
    found = re.fullmatch(r'(jdk|jre)-(\d+)(?:\.[A-Za-z0-9.+-]+)?_linux[-_][A-Za-z0-9_-]+_bin', str(name), re.I)
    return found.group(1).lower() + '-' + found.group(2) if found else ''


def package_identity(path):
    item = Path(str(path))
    suffix = item.suffix.lower()
    name = item.name
    if suffix == '.deb':
        parts = name[:-4].split('_')
        if len(parts) >= 3 and parts[0]:
            return parts[0], parts[1]
    if suffix == '.rpm':
        header = _rpm_header(item)
        if header.get(1000):
            version = header.get(1001, '')
            release = header.get(1002, '')
            return header[1000], version + ('-' + release if release else '')
        oracle = _oracle_jdk_name(item.stem)
        if oracle:
            match = re.match(r'^(?:jdk|jre)-(\d+(?:\.\d+)+)', item.stem, re.I)
            return oracle, match.group(1) if match else ''
        match = re.match(r'^(.+)-([0-9][^-]*)-([^-]+)\.([A-Za-z0-9_]+)\.rpm$', name)
        if match:
            return match.group(1), match.group(2) + '-' + match.group(3)
    if suffix == '.apk':
        match = re.match(r'^(.+)-([0-9][^-]*)-r([0-9]+)\.apk$', name)
        if match:
            return match.group(1), match.group(2) + '-r' + match.group(3)
    return item.stem, ''


def component_package_identity(component):
    kind = str(component.get('kind', '') or '').strip().lower()
    if kind != 'os package':
        return str(component.get('name', '') or '').strip(), ''
    name = str(component.get('name', '') or '').strip()
    source = str(component.get('source', '') or '').strip()
    if source and package_archive_type(source):
        detected, version = package_identity(source)
        if detected and (name == Path(source).stem or name == detected or _oracle_jdk_name(name)):
            return detected, version
    oracle = _oracle_jdk_name(name)
    if oracle:
        return oracle, ''
    return name, ''


def installed_package_record(component, inventory):
    name, _ = component_package_identity(component)
    records = ((inventory or {}).get('packages') or {}).get('os') or []
    for record in records:
        if isinstance(record, dict) and str(record.get('name', '')).strip().lower() == name.lower():
            return record
    return None


def installed_java_versions(inventory):
    result = set()
    system = (inventory or {}).get('system') or {}
    if isinstance(system, dict):
        from java_runtime_checker import parse_java_version
        detected = parse_java_version(system.get('java_version', ''))
        if detected is not None:
            result.add(detected)
    packages = ((inventory or {}).get('packages') or {}).get('os') or []
    for record in packages:
        if not isinstance(record, dict):
            continue
        name = str(record.get('name', '') or '').lower()
        match = re.fullmatch(r'(?:jdk|jre)-(\d+)', name)
        if not match:
            match = re.fullmatch(r'java-(\d+)-openjdk(?:-headless|-devel)?', name)
        if not match:
            match = re.fullmatch(r'openjdk-(\d+)-(?:jre|jdk)(?:-headless)?', name)
        if not match:
            match = re.fullmatch(r'openjdk(\d+)(?:-jre|-jdk|-jre-headless|-jdk-headless)?', name)
        if match:
            result.add(int(match.group(1)))
    for record in (inventory or {}).get('executables') or []:
        if not isinstance(record, dict) or str(record.get('name', '')).lower() != 'java':
            continue
        pkg = str(record.get('package', '')).lower()
        version = str(record.get('version', '') or '')
        if not (re.search(r'(?:jdk|java|openjdk)', pkg) or '/java/' in str(record.get('path', '')).lower()):
            continue
        match = re.match(r'^(?:1\.)?(\d+)(?:\.|\+|-|$)', version)
        if match and 8 <= int(match.group(1)) <= 200:
            result.add(int(match.group(1)))
    return sorted(result)


def compatible_package_file(path, family):
    archive = package_archive_type(path)
    return bool(archive and archive == family)


def installed_packages(state):
    inventory = state.get('base_inventory') or {}
    packages = inventory.get('packages') or {}
    result = {}
    for record in packages.get('os') or []:
        if not isinstance(record, dict):
            continue
        name = str(record.get('name') or '').strip()
        if name:
            result[name] = str(record.get('version') or '').strip()
    return result


def local_package_files(state, family='', max_results=25000):
    paths = []
    seen = set()
    folders = list(state.get('local_package_folders') or [])
    for item in state.get('components') or []:
        if isinstance(item, dict) and str(item.get('kind', '')).lower() == 'os package':
            paths.extend(item.get('local_package_files') or [])
            if item.get('source'):
                paths.append(item['source'])
    for folder in folders:
        root = Path(str(folder)).expanduser()
        if not root.is_dir():
            continue
        try:
            for path in root.iterdir():
                if path.is_file() and package_archive_type(path):
                    paths.append(str(path))
                    if len(paths) >= max_results:
                        break
        except OSError:
            continue
        if len(paths) >= max_results:
            break
    records = []
    for item in paths:
        path = Path(str(item)).expanduser()
        key = str(path).lower()
        if key in seen or not path.is_file() or not package_archive_type(path):
            continue
        seen.add(key)
        name, version = package_identity(path)
        records.append({'name': name, 'version': version, 'path': str(path), 'format': package_archive_type(path),
                        'compatible': compatible_package_file(path, family)})
    return sorted(records, key=lambda x: (x['name'].lower(), x['path'].lower()))


def package_catalog(state, family=''):
    installed = installed_packages(state)
    local = local_package_files(state, family)
    choices = {}
    for name, version in installed.items():
        choices['INSTALLED  |  ' + name + ('  (' + version + ')' if version else '')] = {'name': name, 'version': version, 'source': '', 'files': [], 'status': 'INSTALLED'}
    for record in local:
        label = 'LOCAL FILE  |  ' + record['name'] + ('  (' + record['version'] + ')' if record['version'] else '') + '  |  ' + record['path']
        choices[label] = {'name': record['name'], 'version': record['version'], 'source': record['path'], 'files': [record['path']],
                          'status': 'LOCAL FILE' if record['compatible'] else 'WRONG PACKAGE FORMAT'}
    return choices


def component_files(component):
    supplied = component.get('local_package_files') or []
    if isinstance(supplied, str):
        supplied = [supplied]
    if not supplied and str(component.get('source') or '').strip():
        supplied = [str(component['source'])]
    return list(dict.fromkeys(str(Path(str(p)).expanduser()) for p in supplied if str(p).strip()))


def local_installation_plan(state, packages, family):
    from dependency_planner import translate_package
    installed = installed_packages(state)
    supplied = {}
    errors = []
    for component in state.get('components') or []:
        if not isinstance(component, dict) or not component.get('enabled', True) or str(component.get('kind', '')).lower() != 'os package':
            continue
        name = translate_package(component_package_identity(component)[0], family)
        files = component_files(component)
        if files:
            if name not in supplied:
                supplied[name] = []
            supplied[name].extend(files)
    matched = {}
    for name in packages:
        if name in installed:
            continue
        files = list(dict.fromkeys(supplied.get(name) or []))
        if not files:
            errors.append(name + ': NOT INSTALLED; no local package file was provided')
            continue
        for file in files:
            path = Path(file)
            if not path.is_file():
                errors.append(name + ': missing local package file: ' + file)
            elif not compatible_package_file(path, family):
                errors.append(name + ': ' + path.suffix + ' is incompatible with the selected ' + family + ' runtime')
            else:
                matched.setdefault(name, []).append(path)
    for name in tuple(matched):
        if any(name + ':' in issue for issue in errors):
            del matched[name]
    return {'installed': installed, 'local': matched, 'errors': errors,
            'not_installed': [name for name in packages if name not in installed and name not in matched]}
