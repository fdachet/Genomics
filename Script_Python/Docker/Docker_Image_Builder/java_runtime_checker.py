from __future__ import annotations

import re
import subprocess
import zipfile
from pathlib import Path


def minimum_java_version(jar):
    majors = []
    with zipfile.ZipFile(Path(jar)) as archive:
        for name in archive.namelist():
            if not name.lower().endswith('.class') or name.startswith('META-INF/versions/'):
                continue
            with archive.open(name) as stream:
                header = stream.read(8)
            if len(header) == 8 and header[:4] == b'\xca\xfe\xba\xbe':
                majors.append(int.from_bytes(header[6:8], 'big'))
    if not majors:
        raise ValueError('No Java class files with readable bytecode versions found')
    return max(majors) - 44


def parse_java_version(output):
    match = re.search(r'(?:openjdk|java) version\s+"([0-9][^"\s]*)"', str(output), re.I)
    if not match:
        match = re.search(r'\b(?:openjdk|java)\s+([0-9]+)(?:[.\s]|$)', str(output), re.I)
    if not match:
        return None
    raw = match.group(1)
    if raw.startswith('1.'):
        fields = raw.split('.')
        return int(fields[1]) if len(fields) > 1 and fields[1].isdigit() else None
    return int(raw.split('.', 1)[0])


def probe_java(image, runner=subprocess.run, timeout=45):
    cid = ''
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

    def command(args):
        return runner(args, capture_output=True, text=True, errors='replace', timeout=timeout,
                      stdin=subprocess.DEVNULL, creationflags=flags)

    try:
        created = command(['docker', 'create', '--pull=never', '--network=none', '--cap-drop=ALL',
                           '--security-opt=no-new-privileges', '--pids-limit=128', '--memory=512m',
                           '--entrypoint=java', image, '-version'])
        if created.returncode:
            return {'version': None, 'detail': (created.stderr or created.stdout).strip(), 'status': 'ERROR'}
        cid = created.stdout.strip()
        if not re.fullmatch(r'[a-fA-F0-9]{12,64}', cid):
            return {'version': None, 'detail': 'Docker create returned an invalid ID', 'status': 'ERROR'}
        completed = command(['docker', 'start', '-a', cid])
        output = (completed.stdout or '') + '\n' + (completed.stderr or '')
        version = parse_java_version(output)
        return {'version': version, 'detail': output.strip(),
                'status': 'OK' if version is not None and completed.returncode == 0 else 'ERROR'}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'version': None, 'detail': str(exc), 'status': 'ERROR'}
    finally:
        if cid:
            try:
                command(['docker', 'rm', '-f', cid])
            except (OSError, subprocess.TimeoutExpired):
                pass


def inspect_jar(jar, runtime_probe):
    try:
        minimum = minimum_java_version(jar)
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        return {'status': 'ERROR', 'libraries': [], 'detail': '', 'error': 'JAR analysis: ' + str(exc)}
    installed = runtime_probe.get('version') if runtime_probe.get('status') == 'OK' else None
    if installed is None:
        status = 'UNRESOLVED'
        location = 'Java runtime could not be checked'
    elif installed < minimum:
        status = 'MISSING'
        location = f'Java {installed} installed; Java {minimum}+ required'
    else:
        status = 'FOUND'
        location = f'Java {installed} available in selected runtime'
    return {'status': 'OK' if status == 'FOUND' else 'MISSING' if status == 'MISSING' else 'INCOMPLETE',
            'libraries': [{'name': f'Java {minimum}+ JVM', 'status': status,
                           'path': location, 'category': 'Java runtime'}],
            'detail': f'JAR bytecode requires Java {minimum}+\n' + runtime_probe.get('detail', ''),
            'error': '' if status == 'FOUND' else location}
