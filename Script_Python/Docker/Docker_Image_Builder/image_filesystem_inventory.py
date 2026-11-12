import json
import os
import posixpath
import re
import subprocess
import tarfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


class InspectionCancelled(Exception):
    pass


class InspectionTimeout(Exception):
    pass


def _path(value):
    name = posixpath.normpath(str(value or '').replace('\\', '/').lstrip('/'))
    if name in ('', '.', '..') or name.startswith('../'):
        return ''
    return name


def _read_small(archive, member, maximum=16 * 1024 * 1024):
    if not member.isfile() or member.size > maximum:
        return None
    stream = archive.extractfile(member)
    return stream.read(maximum + 1) if stream else None


def _field_text(value):
    return (value or b'').decode('utf-8', errors='replace')


def _parse_fields(text):
    values = {}
    for raw in text.splitlines():
        if raw and not raw[0].isspace() and ':' in raw:
            key, value = raw.split(':', 1)
            values[key.strip()] = value.strip()
    return values


def _parse_dpkg(data):
    packages = {}
    for stanza in re.split(r'\r?\n\s*\r?\n', _field_text(data)):
        record = _parse_fields(stanza)
        name = record.get('Package', '').strip()
        version = record.get('Version', '').strip()
        status = record.get('Status', '').strip()
        if name and version and status.split()[-1:] == ['installed']:
            packages[name] = version
    return packages


def _parse_apk(data):
    packages = {}
    for stanza in re.split(r'\r?\n\s*\r?\n', _field_text(data)):
        props = {}
        for line in stanza.splitlines():
            if len(line) > 2 and line[1] == ':':
                props[line[0]] = line[2:]
        if props.get('P') and props.get('V'):
            packages[props['P']] = props['V']
    return packages


def _parse_pacman(data):
    values = {}
    lines = _field_text(data).splitlines()
    for index, line in enumerate(lines[:-1]):
        if line in ('%NAME%', '%VERSION%'):
            values[line] = lines[index + 1].strip()
    return values.get('%NAME%', ''), values.get('%VERSION%', '')


def _symlink_target(name, link, hard=False):
    if hard:
        return _path(link)
    if link.startswith('/'):
        return _path(link)
    return _path(posixpath.join(posixpath.dirname(name), link))


def _executable(files, name):
    seen = set()
    current = name
    for _ in range(25):
        if current in seen:
            return False
        seen.add(current)
        item = files.get(current)
        if not item:
            return False
        if item[0] == 'file':
            return bool(item[1] & 0o111)
        if item[0] not in ('link', 'hard'):
            return False
        current = _symlink_target(current, item[2], hard=item[0] == 'hard')
    return False


def _info_from_files(files, metadata, image, image_id, config, report):
    system = {'architecture': str(config.get('architecture') or ''), 'kernel': '', 'glibc': '', 'package_manager': 'none'}
    release = _field_text(metadata.get('etc/os-release') or metadata.get('usr/lib/os-release'))
    for line in release.splitlines():
        if '=' not in line or line.startswith('#'):
            continue
        k, v = line.split('=', 1)
        if k == 'PRETTY_NAME':
            system['os'] = v.strip().strip('"').strip("'")
        elif k == 'ID':
            system['id'] = v.strip().strip('"').strip("'")
        elif k == 'VERSION_ID':
            system['version_id'] = v.strip().strip('"').strip("'")
    if not system.get('os'):
        system['os'] = ('Linux (' + system.get('architecture', '') + ')')

    packages = {'os': [], 'python': [], 'r': [], 'jars': []}
    installed = {}
    dpkg = metadata.get('var/lib/dpkg/status')
    apk = metadata.get('lib/apk/db/installed')
    if dpkg is not None:
        system['package_manager'] = 'dpkg'
        installed.update(_parse_dpkg(dpkg))
    elif apk is not None:
        system['package_manager'] = 'apk'
        installed.update(_parse_apk(apk))
    else:
        for name, data in metadata.items():
            if name.startswith('var/lib/pacman/local/') and name.endswith('/desc'):
                key, version = _parse_pacman(data)
                if key:
                    installed[key] = version
        if installed:
            system['package_manager'] = 'pacman'
        elif any('rpm' in name and ('rpmdb' in name or name.startswith('var/lib/rpm/')) for name in files):
            system['package_manager'] = 'rpm (package DB unavailable without rpm query)'
    report('stage', 'Read installed system packages')
    report('total', ('PKG', len(installed)))
    for name, version in sorted(installed.items(), key=lambda x: x[0].casefold()):
        packages['os'].append({'name': name, 'version': version})
        report('item', ('PKG', name, version))
    if 'libc6' in installed:
        system['glibc'] = 'libc6 ' + installed['libc6']
    elif 'glibc' in installed:
        system['glibc'] = 'glibc ' + installed['glibc']
    else:
        system['glibc'] = 'not determined from package metadata'

    executables = []
    candidates = []
    folders = ('bin/', 'sbin/', 'usr/bin/', 'usr/sbin/', 'usr/local/bin/', 'usr/local/sbin/', 'opt/')
    for name in files:
        if name.startswith(folders):
            candidates.append(name)
    report('stage', 'Search executable files')
    report('total', ('EXEC', len(candidates)))
    for name in sorted(candidates):
        if _executable(files, name):
            record = {'name': posixpath.basename(name), 'version': '', 'path': '/' + name, 'package': ''}
            executables.append(record)
            report('item', ('EXEC', record['name'], record['path']))
    report('total', ('EXEC', len(executables)))

    python = {}
    report('stage', 'Read Python packages')
    for name, data in metadata.items():
        if (name.endswith('/METADATA') and '.dist-info/' in name) or name.endswith('/PKG-INFO'):
            if '/site-packages/' not in name and '/dist-packages/' not in name:
                continue
            fields = _parse_fields(_field_text(data))
            pkg = fields.get('Name', '').strip()
            ver = fields.get('Version', '').strip()
            if pkg and ver:
                python[pkg] = ver
    report('total', ('PIP', len(python)))
    for name, version in sorted(python.items(), key=lambda x: x[0].casefold()):
        packages['python'].append({'name': name, 'version': version})
        report('item', ('PIP', name, version))

    rpkgs = {}
    report('stage', 'Read R packages')
    for name, data in metadata.items():
        if name.endswith('/DESCRIPTION') and ('/library/' in name or '/site-library/' in name):
            fields = _parse_fields(_field_text(data))
            pkg = fields.get('Package', '').strip()
            ver = fields.get('Version', '').strip()
            if pkg and ver:
                rpkgs[pkg] = ver
    report('total', ('RPKG', len(rpkgs)))
    for name, version in sorted(rpkgs.items(), key=lambda x: x[0].casefold()):
        packages['r'].append({'name': name, 'version': version})
        report('item', ('RPKG', name, version))

    report('stage', 'Index application JAR files')
    jars = sorted('/' + name for name, item in files.items() if name.lower().endswith('.jar') and item[0] == 'file')
    report('total', ('JAR', len(jars)))
    for name in jars:
        report('item', ('JAR', name, ''))
    packages['jars'] = jars

    provenance = None
    data = metadata.get('opt/component-builder/component_provenance.json')
    if data:
        try:
            provenance = json.loads(_field_text(data))
            if not isinstance(provenance, dict):
                provenance = None
        except ValueError:
            pass
    return {'schema': 6,
            'inspected_at': datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),
            'docker_tag': image,
            'image_id': image_id,
            'system': system,
            'executables': executables,
            'packages': packages,
            'provenance': provenance,
            'inventory_method': 'filesystem'}


def _scan_layer(layer, files, metadata, report, cancel, deadline, layer_index, layer_count):
    count = 0
    with tarfile.open(fileobj=layer, mode='r|*') as entries:
        for member in entries:
            if cancel is not None and cancel.is_set():
                raise InspectionCancelled('The filesystem inspection was cancelled.')
            if deadline and time.monotonic() > deadline:
                raise InspectionTimeout('Filesystem inspection exceeded its time limit.')
            name = _path(member.name)
            if not name:
                continue
            basename = posixpath.basename(name)
            parent = posixpath.dirname(name)
            if basename == '.wh..wh..opq':
                prefix = parent + '/' if parent else ''
                for path in tuple(files):
                    if path.startswith(prefix):
                        files.pop(path, None)
                        metadata.pop(path, None)
                continue
            if basename.startswith('.wh.'):
                target = posixpath.join(parent, basename[4:])
                for path in tuple(files):
                    if path == target or path.startswith(target + '/'):
                        files.pop(path, None)
                        metadata.pop(path, None)
                continue
            if member.isfile():
                files[name] = ('file', member.mode, '', member.size)
                if name in ('etc/os-release', 'usr/lib/os-release', 'etc/debian_version', 'etc/alpine-release',
                            'var/lib/dpkg/status', 'lib/apk/db/installed',
                            'opt/component-builder/component_provenance.json'):
                    read = _read_small(entries, member)
                    if read is not None:
                        metadata[name] = read
                elif (name.startswith('var/lib/pacman/local/') and name.endswith('/desc')) or (
                      (name.endswith('/METADATA') and '.dist-info/' in name) or name.endswith('/PKG-INFO') or
                      (name.endswith('/DESCRIPTION') and ('/library/' in name or '/site-library/' in name))):
                    read = _read_small(entries, member, 256 * 1024)
                    if read is not None:
                        metadata[name] = read
                else:
                    metadata.pop(name, None)
            elif member.issym() or member.islnk():
                files[name] = ('hard' if member.islnk() else 'link', member.mode, member.linkname, 0)
                metadata.pop(name, None)
            count += 1
            if count % 350 == 0:
                report('detail', f'Layer {layer_index}/{layer_count}: {count:,} entries; {len(files):,} filesystem paths, latest {name[:110]}')
    report('detail', f'Layer {layer_index}/{layer_count} complete: {len(files):,} filesystem paths')


def inspect_saved_tar(archive, image='', report=None, cancel=None, timeout=300):
    report = report or (lambda *_: None)
    deadline = time.monotonic() + timeout if timeout else None
    report('stage', 'Read saved image manifest')
    with tarfile.open(str(archive), mode='r:*') as outer:
        try:
            member = outer.getmember('manifest.json')
            source = outer.extractfile(member)
            manifest = json.loads(source.read()) if source else []
        except KeyError as error:
            raise ValueError('The selected TAR is not a docker save archive (manifest.json is missing).') from error
        if not manifest:
            raise ValueError('The image TAR contains no image manifest entries.')
        candidates = [item for item in manifest if image and image in (item.get('RepoTags') or [])] or list(manifest)
        selected = candidates[0]
        if len(candidates) > 1 and image:
            from docker_image_checkpoint import _loaded_image_details, _image_configuration_matches, _normalize_digest, _normalize_layers
            loaded = _loaded_image_details(image, cancel)
            for candidate in candidates:
                name = str(candidate.get('Config') or '')
                try:
                    source = outer.extractfile(name)
                    config_candidate = json.loads(source.read(4 * 1024 * 1024)) if source else {}
                except (KeyError, ValueError, OSError, TypeError):
                    continue
                rootfs_candidate = config_candidate.get('rootfs') or {}
                record = {
                    'image_id': _normalize_digest(name.rsplit('/', 1)[-1].removesuffix('.json')),
                    'rootfs_layers': _normalize_layers(rootfs_candidate.get('diff_ids') or []) if isinstance(rootfs_candidate, dict) else (),
                    'architecture': str(config_candidate.get('architecture') or '').lower(),
                    'os': str(config_candidate.get('os') or '').lower(),
                }
                if _image_configuration_matches(record, loaded):
                    selected = candidate
                    break
        actual_tag = (selected.get('RepoTags') or [''])[0]
        config_name = str(selected.get('Config') or '')
        config_id = config_name.rsplit('/', 1)[-1].removesuffix('.json')
        image_id = 'sha256:' + config_id if len(config_id) == 64 and all(c in '0123456789abcdefABCDEF' for c in config_id) else ''
        config = {}
        try:
            source = outer.extractfile(config_name)
            if source:
                config = json.loads(source.read(4 * 1024 * 1024))
        except (KeyError, ValueError, TypeError):
            pass
        layers = list(selected.get('Layers') or [])
        if not layers:
            raise ValueError('The image archive does not contain filesystem layers.')
        files = {}
        metadata = {}
        for index, name in enumerate(layers, 1):
            if cancel is not None and cancel.is_set():
                raise InspectionCancelled('The image inspection was cancelled.')
            report('stage', f'Read image filesystem layer {index}/{len(layers)}')
            report('detail', f'Opening saved layer {index}/{len(layers)}')
            source = outer.extractfile(name)
            if not source:
                raise ValueError(f'Missing filesystem layer {name} in saved TAR.')
            _scan_layer(source, files, metadata, report, cancel, deadline, index, len(layers))
        report('stage', 'Identify operating system')
        result = _info_from_files(files, metadata, image or actual_tag, image_id, config, report)
        result['inventory_method'] = 'saved_tar'
        result['archive_tag'] = actual_tag
        rootfs = config.get('rootfs') or config.get('RootFS') or {}
        result['rootfs_diff_ids'] = list(rootfs.get('diff_ids') or rootfs.get('Layers') or []) if isinstance(rootfs, dict) else []
        return result


def _execute(args, timeout):
    result = subprocess.run(args, capture_output=True, text=True, errors='replace', timeout=timeout,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError(f'Docker command failed ({result.returncode}): {(result.stderr or result.stdout).strip()[:1000]}')
    return result.stdout.strip()


def inspect_tag_via_export(image, report=None, cancel=None, timeout=240):
    report = report or (lambda *_: None)
    started = time.monotonic()
    image_id = _execute(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], 15)
    report('stage', 'Create temporary inspection container (not started)')
    container_id = _execute(['docker', 'create', '--entrypoint', '/bin/sh', image, '-c', ':'], 35)
    process = None
    stop_watch = threading.Event()
    failure = []
    def watchdog():
        while not stop_watch.wait(0.25):
            if cancel is not None and cancel.is_set():
                failure.append(InspectionCancelled('Image inspection cancelled by user.'))
            elif time.monotonic() - started > timeout:
                failure.append(InspectionTimeout('Docker image filesystem export timed out.'))
            if failure:
                if process is not None and process.poll() is None:
                    process.kill()
                break
    try:
        report('stage', 'Export image filesystem for inspection')
        process = subprocess.Popen(['docker', 'export', container_id], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        errors = []
        def read_error():
            while True:
                data = process.stderr.read(8192)
                if not data:
                    break
                errors.append(data.decode('utf-8', errors='replace'))
        stderr_thread = threading.Thread(target=read_error, daemon=True)
        stderr_thread.start()
        guard = threading.Thread(target=watchdog, daemon=True)
        guard.start()
        files = {}
        metadata = {}
        try:
            _scan_layer(process.stdout, files, metadata, report, cancel, time.monotonic() + timeout, 1, 1)
        except (tarfile.TarError, EOFError, OSError) as error:
            if failure:
                raise failure[0] from error
            raise RuntimeError('Docker export ended before its filesystem inventory could be read: ' + str(error)) from error
        process.wait(timeout=10)
        stderr_thread.join(timeout=2)
        if failure:
            raise failure[0]
        if process.returncode:
            raise RuntimeError('Docker export failed: ' + ''.join(errors)[-1500:])
        report('stage', 'Identify operating system')
        return _info_from_files(files, metadata, image, image_id, {}, report)
    finally:
        stop_watch.set()
        if process is not None and process.poll() is None:
            process.kill()
        try:
            _execute(['docker', 'rm', '-f', container_id], 20)
        except (RuntimeError, subprocess.TimeoutExpired, OSError):
            pass
