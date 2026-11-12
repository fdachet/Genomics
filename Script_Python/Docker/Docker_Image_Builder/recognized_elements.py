import json
import fnmatch
import os
import re
import subprocess
import tempfile
from pathlib import Path


DEFAULT_DATABASE = Path(__file__).resolve().with_name('recognized_elements.json')
_active_database = DEFAULT_DATABASE
NAME_PATTERN = re.compile(r'[A-Za-z0-9_+][A-Za-z0-9_.+-]*\Z')


def valid_name(name):
    return bool(NAME_PATTERN.fullmatch(str(name or '')))


def database_path():
    return _active_database


def select_database(path=None):
    global _active_database
    candidate = Path(str(path)).expanduser().resolve() if str(path or '').strip() else DEFAULT_DATABASE
    if candidate.suffix.lower() != '.json':
        raise ValueError('Select a .json database file.')
    _active_database = candidate
    return candidate


def normalize_entry(value):
    if not isinstance(value, dict):
        raise ValueError('Recognized-element entries must be objects.')
    name = str(value.get('name') or '').strip()
    if not valid_name(name):
        raise ValueError('Invalid executable name: ' + name)
    requires = value.get('requires') or []
    if isinstance(requires, str):
        requires = re.split(r'[,\s]+', requires)
    if not isinstance(requires, list):
        raise ValueError('The requirements for ' + name + ' must be a list.')
    dependencies = []
    for required in requires:
        required = str(required).strip()
        if not required:
            continue
        if not valid_name(required):
            raise ValueError('Invalid dependency for ' + name + ': ' + required)
        if required != name and required not in dependencies:
            dependencies.append(required)
    purpose = str(value.get('purpose') or '').strip()
    category = str(value.get('category') or '').strip() or 'Uncategorized'
    origin = str(value.get('origin') or '').strip() or 'preloaded catalog'
    kind = str(value.get('kind') or 'executable').strip().lower()
    if kind not in ('executable', 'library', 'distribution', 'package_manager', 'build_file'):
        raise ValueError('Invalid recognition kind for ' + name + ': ' + kind)
    pattern = str(value.get('pattern') or '').strip()
    build_system = str(value.get('build_system') or '').strip()
    build_command = str(value.get('build_command') or '').strip()
    try:
        priority = int(value.get('priority', 100))
    except (TypeError, ValueError) as exc:
        raise ValueError('Build detection priority must be an integer for ' + name) from exc
    if not 0 <= priority <= 100000:
        raise ValueError('Build detection priority must be between 0 and 100000 for ' + name)
    for field, text in (('purpose', purpose), ('category', category), ('origin', origin), ('pattern', pattern),
                        ('build_system', build_system), ('build_command', build_command)):
        if len(text) > 4000 or '\x00' in text:
            raise ValueError('Invalid ' + field + ' in the entry ' + name)
    return {'name': name, 'purpose': purpose, 'category': category,
            'origin': origin, 'kind': kind, 'pattern': pattern,
            'build_system': build_system, 'build_command': build_command, 'priority': priority,
            'enabled': bool(value.get('enabled', True)),
            'executable': bool(value.get('executable', True)), 'requires': dependencies}


def normalize_entries(entries):
    if not isinstance(entries, list):
        raise ValueError('The recognized-element database must contain an elements list.')
    normalized = []
    seen = set()
    for entry in entries:
        current = normalize_entry(entry)
        key = current['name'].casefold()
        if key in seen:
            raise ValueError('Duplicate recognized element: ' + current['name'])
        seen.add(key)
        normalized.append(current)
    return sorted(normalized, key=lambda item: item['name'].lower())


def load_database(path=None):
    location = Path(path) if path is not None else _active_database
    if not location.is_file():
        return []
    try:
        contents = json.loads(location.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ValueError('Cannot read the executable database: ' + str(exc)) from exc
    if isinstance(contents, list):
        elements = contents
    elif isinstance(contents, dict) and contents.get('schema') == 1:
        elements = contents.get('elements', [])
    else:
        raise ValueError('Unsupported recognized-element database format.')
    return normalize_entries(elements)


def save_database(entries, path=None):
    location = Path(path) if path is not None else _active_database
    normalized = normalize_entries(entries)
    location.parent.mkdir(parents=True, exist_ok=True)
    filename = ''
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.json',
                                         prefix='.recognized_', dir=location.parent, delete=False) as stream:
            filename = stream.name
            json.dump({'schema': 1, 'elements': normalized}, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(filename, location)
    finally:
        if filename and Path(filename).exists():
            Path(filename).unlink()
    return location


def entry_map():
    return {entry['name']: entry for entry in load_database()
            if entry['enabled'] and entry['kind'] in ('executable', 'package_manager')}


def recognized_names():
    return frozenset(entry_map())


def entry_category(name):
    return (entry_map().get(str(name)) or {}).get('category') or 'Build utility'


def find_recognition(kind, value):
    candidate = str(value or '').strip().lower()
    if not candidate:
        return None
    for entry in load_database():
        if entry['enabled'] and entry['kind'] == kind:
            pattern = (entry['pattern'] or entry['name']).lower()
            if fnmatch.fnmatchcase(candidate, pattern):
                return entry
    return None


def require_dependencies(requirements):
    catalog = entry_map()
    detected = {item['command']: {'command': item['command'],
                                   'evidence': list(item.get('evidence') or [])}
                for item in requirements if valid_name(item.get('command'))}
    stack = list(detected)
    visited = set()
    while stack:
        command = stack.pop()
        if command in visited:
            continue
        visited.add(command)
        for required in catalog.get(command, {}).get('requires', []):
            provider = catalog.get(required)
            if provider is None:
                continue
            if provider['executable']:
                evidence = 'Required by ' + command
                record = detected.setdefault(required, {'command': required, 'evidence': []})
                if evidence not in record['evidence']:
                    record['evidence'].append(evidence)
            stack.append(required)
    for name in list(detected):
        if name in catalog and not catalog[name]['executable']:
            detected.pop(name)
    return sorted(detected.values(), key=lambda item: item['command'].lower())


def add_element(name, purpose='', category='User-defined', origin='user'):
    current = load_database()
    candidate = normalize_entry({'name': name, 'purpose': purpose, 'category': category,
                                 'origin': origin, 'enabled': True})
    if any(item['name'].casefold() == candidate['name'].casefold() for item in current):
        return False
    save_database(current + [candidate])
    return True


def scan_image_executables(image, runner=None, timeout=180):
    image = str(image or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_./:@+-]+', image):
        raise ValueError('Select a valid local Docker image tag before scanning.')
    script = """old_ifs=$IFS
IFS=:
for directory in $PATH; do
  [ -d "$directory" ] || continue
  for candidate in "$directory"/*; do
    [ -f "$candidate" ] && [ -x "$candidate" ] || continue
    name=$(basename "$candidate")
    printf 'EXEC|%s|%s\\n' "$name" "$candidate"
  done
done
IFS=$old_ifs"""
    args = ['docker', 'run', '--rm', '--pull=never', '--network=none',
            '--entrypoint', '/bin/sh', image, '-c', script]
    runner = runner or subprocess.run
    try:
        result = runner(args, capture_output=True, text=True, encoding='utf-8',
                        errors='replace', timeout=timeout, stdin=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('Cannot scan the selected Docker image: ' + str(exc)) from exc
    if result.returncode:
        raise RuntimeError('Docker executable scan failed: ' + (result.stderr or result.stdout or '')[-1200:])
    records = {}
    for line in result.stdout.splitlines():
        parts = line.split('|', 2)
        if len(parts) != 3 or parts[0] != 'EXEC' or not valid_name(parts[1]):
            continue
        records.setdefault(parts[1], parts[2])
        if len(records) > 20000:
            raise RuntimeError('The image contained too many executable names to import safely.')
    return [{'name': name, 'purpose': 'Purpose not documented; edit this entry.',
             'category': 'Discovered in Docker image', 'origin': image,
             'enabled': True, 'executable': True, 'requires': []}
            for name in sorted(records, key=str.lower)]


def inspect_docker_distribution(image, runner=None, timeout=30):
    image = str(image or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_./:@+-]+', image):
        raise ValueError('Select a valid local Docker image tag before inspection.')
    script = """for source in /etc/os-release /usr/lib/os-release; do
  if [ -r "$source" ]; then
    . "$source"
    printf 'ID|%s\nVERSION_ID|%s\nPRETTY_NAME|%s\nVERSION_CODENAME|%s\n' "$ID" "$VERSION_ID" "$PRETTY_NAME" "$VERSION_CODENAME"
    exit 0
  fi
done
exit 1"""
    runner = runner or subprocess.run
    try:
        result = runner(['docker', 'run', '--rm', '--pull=never', '--network=none',
                         '--entrypoint', '/bin/sh', image, '-c', script],
                        capture_output=True, text=True, encoding='utf-8', errors='replace',
                        timeout=timeout, stdin=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('Cannot inspect Linux distribution metadata: ' + str(exc)) from exc
    if result.returncode:
        raise RuntimeError('The selected image did not provide readable os-release metadata.')
    result_values = {}
    mapping = {'ID': 'id', 'VERSION_ID': 'version_id',
               'PRETTY_NAME': 'pretty_name', 'VERSION_CODENAME': 'version_codename'}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition('|')
        if sep and key in mapping:
            result_values[mapping[key]] = value.strip()
    return result_values
