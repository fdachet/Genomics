import hashlib
import json
import os
import posixpath
import re
import tarfile
import tempfile
from functools import lru_cache
from pathlib import Path

from component_provenance import PROVENANCE_PATH, component_origin
from java_runtime_checker import minimum_java_version
from runtime_dependency_scanner import is_elf


def _normalized(name):
    name = posixpath.normpath(str(name).replace('\\', '/').lstrip('/'))
    if not name or name == '.' or name == '..' or name.startswith('../'):
        return ''
    return name


def _candidate(name):
    if name in ('opt/component-builder/pending_requirements.json', 'opt/component-builder/installation_status.tsv'):
        return True
    if name.startswith('usr/local/bin/') and name.count('/') == 3:
        return True
    if name.startswith('opt/') and name.endswith('.jar') and name.count('/') <= 4:
        return not name.startswith(('opt/java/', 'opt/jdk/', 'opt/temurin/', 'opt/component-builder/'))
    if name.startswith('opt/') and name.count('/') <= 3:
        return name.endswith(('.py', '.R', '.r', '.pl', '.sh'))
    return False


def _major_from_env(env):
    for item in env:
        if item.startswith(('JAVA_VERSION=', 'JDK_VERSION=')):
            value = item.split('=', 1)[1]
            match = re.search(r'(?:jdk|java|openjdk)[- ]?(?:1\.)?(\d+)', value, re.I)
            if match:
                version = int(match.group(1))
                if 1 <= version <= 100:
                    return version
    for item in env:
        if item.startswith('JAVA_HOME='):
            value = item.split('=', 1)[1]
            match = re.search(r'(?:java|jdk|openjdk)[-/]?(\d+)(?:\D|$)', value, re.I)
            if match:
                return int(match.group(1))
    return None


@lru_cache(maxsize=3)
def _inspect(path, size, mtime):
    entries = {}
    pending = {}
    installation_status = {}
    provenance = None
    layer_events = {}
    env = []
    with tarfile.open(path, 'r:*') as archive:
        manifest = json.load(archive.extractfile('manifest.json'))
        if not manifest or 'Layers' not in manifest[0]:
            raise ValueError('This is not a supported Docker save archive')
        meta = manifest[0]
        try:
            config = json.load(archive.extractfile(meta['Config']))
            env = config.get('config', config.get('Config', {})).get('Env', []) or []
        except (KeyError, ValueError, TypeError, AttributeError):
            pass
        for layer_index, layername in enumerate(meta['Layers'], 1):
            with tarfile.open(fileobj=archive.extractfile(layername), mode='r|*') as layer:
                for member in layer:
                    name = _normalized(member.name)
                    if not name:
                        continue
                    leaf = posixpath.basename(name)
                    parent = posixpath.dirname(name)
                    if leaf == '.wh..wh..opq':
                        prefix = parent + '/' if parent else ''
                        entries = {key: value for key, value in entries.items() if not key.startswith(prefix)}
                        layer_events = {key: value for key, value in layer_events.items() if not key.startswith(prefix)}
                        continue
                    if leaf.startswith('.wh.'):
                        target = posixpath.join(parent, leaf[4:])
                        entries.pop(target, None)
                        for old in tuple(entries):
                            if old.startswith(target + '/'):
                                entries.pop(old, None)
                        for old in tuple(layer_events):
                            if old == target or old.startswith(target + '/'):
                                layer_events.pop(old, None)
                        continue
                    if member.isfile() or member.issym() or member.islnk():
                        record = layer_events.setdefault(name, {'first_layer': layer_index, 'last_layer': layer_index, 'changes': 0})
                        record['last_layer'] = layer_index
                        record['changes'] += 1
                    if not member.isfile() or not (_candidate(name) or name == PROVENANCE_PATH):
                        continue
                    if member.size > 64 * 1024 * 1024:
                        continue
                    stream = layer.extractfile(member)
                    if stream is None:
                        continue
                    contents = stream.read()
                    entries[name] = contents
    cache_id = hashlib.sha256((path + str(size) + str(mtime)).encode('utf-8')).hexdigest()[:24]
    cache_root = Path(tempfile.gettempdir()) / 'component_docker_image_scan' / cache_id
    results = []
    for name, contents in sorted(entries.items()):
        if name == PROVENANCE_PATH:
            try:
                provenance = json.loads(contents.decode('utf-8-sig'))
                if not isinstance(provenance, dict) or provenance.get('format') != 'component-builder-provenance-v1':
                    provenance = None
            except (ValueError, UnicodeDecodeError):
                provenance = None
            continue
        if name == 'opt/component-builder/installation_status.tsv':
            for record in contents.decode('utf-8', 'replace').splitlines():
                fields = record.split('\t', 1)
                if len(fields) == 2 and fields[1] in ('INSTALLED', 'NOT INSTALLED'):
                    installation_status[fields[0]] = fields[1]
            continue
        if name == 'opt/component-builder/pending_requirements.json':
            try:
                pending = json.loads(contents.decode('utf-8-sig'))
                if not isinstance(pending, dict):
                    pending = {}
            except (ValueError, UnicodeDecodeError):
                pending = {}
            continue
        ext = posixpath.splitext(name)[1].lower()
        if ext == '.jar':
            kind = 'jar/application'
        elif contents.startswith(b'\x7fELF'):
            kind = 'binary'
        elif ext in ('.py', '.r', '.pl', '.sh') or contents.startswith(b'#!'):
            kind = 'script'
        else:
            continue
        local = cache_root / name
        local.parent.mkdir(parents=True, exist_ok=True)
        if not local.is_file() or local.stat().st_size != len(contents):
            local.write_bytes(contents)
        minimum = None
        version = ''
        if kind == 'jar/application':
            try:
                minimum = minimum_java_version(local)
            except Exception:
                pass
            try:
                import zipfile
                with zipfile.ZipFile(local) as jar:
                    for nm in ('META-INF/MANIFEST.MF', 'meta-inf/manifest.mf'):
                        if nm in jar.namelist():
                            value = jar.read(nm).decode('utf-8', 'replace')
                            m = re.search(r'^Implementation-Version:\s*(\S+)', value, re.M | re.I)
                            if m:
                                version = m.group(1)
                            break
            except Exception:
                pass
        result = {'name': posixpath.basename(name).removesuffix('.jar'), 'path': '/' + name,
                  'local': str(local), 'kind': kind, 'version': version, 'java_minimum': minimum,
                  'present_in_image': True, 'sha256': hashlib.sha256(contents).hexdigest()}
        results.append(result)
    history = {'layers': layer_events, 'provenance': provenance,
               'layer_count': len(meta.get('Layers', [])),
               'tag': (meta.get('RepoTags') or [''])[0],
               'config_digest': str(meta.get('Config', '')).removesuffix('.json')}
    if provenance:
        for item in provenance.get('requested_os_packages', provenance.get('deferred_os_packages', [])) or []:
            pending.setdefault('os_packages', [])
            if item not in pending['os_packages']:
                pending['os_packages'].append(item)
        inherited_languages = provenance.get('requested_language_packages', provenance.get('deferred_language_packages')) or {}
        for field, packages in inherited_languages.items():
            current = (pending.setdefault('language_packages', {})).setdefault(field, [])
            current.extend(x for x in packages if x not in current)
        for field, version in (provenance.get('requested_language_versions', provenance.get('deferred_language_versions')) or {}).items():
            if version and not (pending.setdefault('language_versions', {})).get(field):
                pending['language_versions'][field] = version
    for result in results:
        result.update(component_origin(result, history))
    java = _major_from_env(env)
    home = next((x.split('=', 1)[1] for x in env if x.startswith('JAVA_HOME=')), '')
    match = re.search(r'(?:java|jdk|openjdk)[-/]?(\d+)(?:\D|$)', home, re.I)
    if match:
        java = int(match.group(1))
    versions = {java} if java is not None else set()
    for name, status in installation_status.items():
        if status != 'INSTALLED':
            continue
        found = re.fullmatch(r'(?:java-(\d+)-openjdk(?:-headless|-devel)?|openjdk-(\d+)-(?:jre|jdk)(?:-headless)?|openjdk(\d+)(?:-jre|-jdk|-jre-headless|-jdk-headless)?)', name, re.I)
        if found:
            versions.add(int(next(x for x in found.groups() if x)))
    java = max(versions, default=None)
    return {'components': results, 'pending': pending, 'installation_status': installation_status, 'installed_java': java,
            'installed_java_versions': sorted(versions),
            'environment': env, 'archive': path, 'tag': (meta.get('RepoTags') or [''])[0],
            'provenance': history.get('provenance'), 'layer_count': history.get('layer_count'),
            'lineage': (history.get('provenance') or {}).get('lineage', []),
            'history': history}


def inspect_image_components(archive):
    path = Path(str(archive or '')).expanduser()
    if not path.is_file():
        raise FileNotFoundError('No accessible runtime Docker .tar was selected')
    stat = path.stat()
    return _inspect(str(path.resolve()), stat.st_size, stat.st_mtime_ns)


def image_component_records(archive):
    return inspect_image_components(archive)['components']
