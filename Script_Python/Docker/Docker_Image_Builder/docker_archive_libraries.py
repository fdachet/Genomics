from __future__ import annotations

import json
import posixpath
import tarfile
from functools import lru_cache
from pathlib import Path


def _path(name):
    value = posixpath.normpath(str(name).replace('\\', '/').lstrip('/').removeprefix('./'))
    if value == '..' or value.startswith('../') or value in ('', '.'):
        return ''
    return value


def _interesting(name):
    base = posixpath.basename(name)
    return ('.so' in base or base.startswith(('ld-linux', 'ld-musl')) or
            base in ('os-release', 'java', 'microdnf', 'dnf', 'yum', 'apt-get', 'apk', 'zypper'))


@lru_cache(maxsize=4)
def _read_archive(filename, length, modification):
    files = {}
    release = {}
    with tarfile.open(filename, 'r:*') as outer:
        try:
            manifest = json.load(outer.extractfile('manifest.json'))
            layers = manifest[0]['Layers']
        except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
            raise ValueError('Unsupported Docker archive: missing docker-save manifest.json or image layers') from exc
        for layername in layers:
            member = outer.getmember(layername)
            stream = outer.extractfile(member)
            if stream is None:
                raise ValueError('Missing layer contents: ' + layername)
            with stream:
                with tarfile.open(fileobj=stream, mode='r|*') as layer:
                    for item in layer:
                        name = _path(item.name)
                        if not name:
                            continue
                        base = posixpath.basename(name)
                        directory = posixpath.dirname(name)
                        if base == '.wh..wh..opq':
                            prefix = directory + '/' if directory else ''
                            files = {key: value for key, value in files.items() if not key.startswith(prefix)}
                            continue
                        if base.startswith('.wh.'):
                            target = posixpath.join(directory, base[4:])
                            files.pop(target, None)
                            prefix = target + '/'
                            for key in list(files):
                                if key.startswith(prefix):
                                    del files[key]
                            continue
                        if item.isfile() and name in ('etc/os-release', 'usr/lib/os-release') and item.size <= 16384:
                            contents = layer.extractfile(item)
                            if contents:
                                for line in contents.read().decode('utf-8', 'replace').splitlines():
                                    if '=' in line and not line.startswith('#'):
                                        key, val = line.split('=', 1)
                                        if key in ('PRETTY_NAME', 'ID', 'VERSION_ID'):
                                            release[key] = val.strip().strip('"').strip("'")
                        if item.isfile() or item.issym() or item.islnk():
                            if _interesting(name):
                                files[name] = item.linkname if (item.issym() or item.islnk()) else ''
    by_base = {}
    for name in files:
        by_base.setdefault(posixpath.basename(name), []).append('/' + name)
    return by_base, files, release


def archive_library_inventory(archive):
    path = Path(str(archive or '')).expanduser()
    if not path.is_file():
        raise FileNotFoundError('Selected runtime archive is not accessible: ' + str(path))
    stat = path.stat()
    bases, files, release = _read_archive(str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    pkg = next((name for name in ('microdnf', 'dnf', 'yum', 'apt-get', 'apk', 'zypper') if name in bases), 'unknown')
    return {'by_base': bases, 'paths': files, 'package_manager': pkg,
            'java_executables': bases.get('java', []), 'archive': str(path),
            'os': release.get('PRETTY_NAME', release.get('ID', 'unknown'))}


def find_in_archive(inventory, library):
    return list(inventory.get('by_base', {}).get(posixpath.basename(library), []))
