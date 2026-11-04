from __future__ import annotations

import mmap
import os
import re
import struct
import subprocess
from pathlib import Path


def is_elf(path):
    try:
        with Path(path).open('rb') as handle:
            return handle.read(4) == b'\x7fELF'
    except OSError:
        return False


def elf_dependencies(path):
    with Path(path).open('rb') as source:
        with mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as data:
            if len(data) < 52 or data[:4] != b'\x7fELF':
                raise ValueError('Not a valid ELF executable')
            width = data[4]
            endian = '<' if data[5] == 1 else '>' if data[5] == 2 else None
            if width not in (1, 2) or endian is None:
                raise ValueError('Unsupported ELF class or byte order')
            if width == 2:
                ph_offset = struct.unpack_from(endian + 'Q', data, 32)[0]
                ph_size, ph_count = struct.unpack_from(endian + 'HH', data, 54)
                ph_format = endian + 'IIQQQQQQ'
                dyn_format = endian + 'qQ'
            else:
                ph_offset = struct.unpack_from(endian + 'I', data, 28)[0]
                ph_size, ph_count = struct.unpack_from(endian + 'HH', data, 42)
                ph_format = endian + 'IIIIIIII'
                dyn_format = endian + 'iI'
            program = []
            for index in range(ph_count):
                start = ph_offset + index * ph_size
                if start + struct.calcsize(ph_format) > len(data):
                    raise ValueError('Truncated ELF program headers')
                fields = struct.unpack_from(ph_format, data, start)
                if width == 2:
                    typ, flags, offset, vaddr, paddr, file_size, memory_size, align = fields
                else:
                    typ, offset, vaddr, paddr, file_size, memory_size, flags, align = fields
                program.append((typ, offset, vaddr, file_size, memory_size))
            interpreter = ''
            for typ, offset, vaddr, file_size, memory_size in program:
                if typ == 3:
                    raw = data[offset:offset + file_size].split(b'\x00', 1)[0]
                    interpreter = raw.decode('utf-8', 'replace')
            dynamic = next((entry for entry in program if entry[0] == 2), None)
            if dynamic is None:
                return {'needed': [], 'interpreter': interpreter, 'rpaths': [], 'static': True}
            offsets = []
            addresses = {}
            offset, size = dynamic[1], dynamic[3]
            entry_size = struct.calcsize(dyn_format)
            for position in range(offset, min(offset + size, len(data)), entry_size):
                tag, value = struct.unpack_from(dyn_format, data, position)
                if tag == 0:
                    break
                if tag == 1:
                    offsets.append(value)
                if tag in (5, 10, 15, 29):
                    addresses[tag] = value
            if not offsets:
                return {'needed': [], 'interpreter': interpreter, 'rpaths': [], 'static': not interpreter}
            str_addr = addresses.get(5)
            if str_addr is None:
                raise ValueError('ELF has shared-library references but no dynamic string table')
            str_offset = next((file_offset + str_addr - vaddr for typ, file_offset, vaddr, file_size, memory_size in program
                               if typ == 1 and vaddr <= str_addr < vaddr + file_size), None)
            if str_offset is None:
                raise ValueError('Cannot locate ELF dynamic string table')
            str_limit = min(len(data), str_offset + addresses.get(10, 65536))

            def string_at(location):
                pos = str_offset + location
                if pos >= str_limit:
                    raise ValueError('Invalid dynamic string offset')
                end = data.find(b'\x00', pos, str_limit)
                if end == -1:
                    raise ValueError('Unterminated dynamic string')
                return data[pos:end].decode('utf-8', 'replace')

            needed = list(dict.fromkeys(string_at(i) for i in offsets))
            rpaths = []
            for tag in (29, 15):
                if tag in addresses:
                    rpaths.extend(string_at(addresses[tag]).split(':'))
            return {'needed': needed, 'interpreter': interpreter, 'rpaths': rpaths, 'static': False}


def parse_ldd(output, returncode=0):
    output = str(output or '')
    lowered = output.lower()
    if 'not a dynamic executable' in lowered or 'statically linked' in lowered:
        return {'status': 'STATIC', 'libraries': [], 'detail': output.strip(), 'error': ''}
    libraries = []
    seen = set()
    notes = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line or line.startswith('linux-vdso.') or line.startswith('linux-gate.'):
            continue
        if '=>' in line:
            name, resolved = (part.strip() for part in line.split('=>', 1))
            if resolved.startswith('not found'):
                status, location, category = 'MISSING', '', 'Shared library'
            elif resolved.startswith('/'):
                status, location, category = 'FOUND', resolved.split(' (', 1)[0].strip(), 'Shared library'
            elif resolved.startswith('('):
                status, location, category = 'UNRESOLVED', '', 'Shared library'
            else:
                notes.append(line)
                continue
        elif line.startswith('/'):
            location = line.split(' (', 1)[0].strip()
            name = os.path.basename(location)
            status, category = 'FOUND', 'Dynamic loader'
        elif re.match(r'^\S+\.so(?:\.\S+)?\s+\(', line):
            name = line.split()[0]
            location, status, category = '', 'UNRESOLVED', 'Shared library'
        else:
            notes.append(line)
            continue
        key = (name, category)
        if key not in seen:
            libraries.append({'name': name, 'status': status, 'path': location, 'category': category})
            seen.add(key)
    if any(item['status'] == 'MISSING' for item in libraries):
        status, error = 'MISSING', ''
    elif returncode != 0:
        status, error = 'ERROR', f'ldd returned exit code {returncode}. ' + ' '.join(notes)
    elif not libraries:
        status, error = 'ERROR', 'No libraries were resolved. ' + ' '.join(notes)
    elif any(item['status'] == 'UNRESOLVED' for item in libraries):
        status, error = 'INCOMPLETE', 'Some libraries have no resolved location.'
    else:
        status, error = 'OK', ''
    return {'status': status, 'libraries': libraries, 'detail': output.strip(), 'error': error}


def local_elf_report(binary):
    try:
        elf = elf_dependencies(binary)
    except (OSError, ValueError, struct.error) as exc:
        return {'status': 'ERROR', 'libraries': [], 'detail': '', 'error': 'ELF analysis failed: ' + str(exc)}
    if elf['static']:
        return {'status': 'STATIC', 'libraries': [], 'detail': 'Statically linked ELF: no dynamically linked libraries.', 'error': ''}
    libraries = [{'name': name, 'status': 'UNRESOLVED', 'path': '', 'category': 'Shared library'}
                 for name in elf['needed']]
    if elf['interpreter']:
        libraries.append({'name': os.path.basename(elf['interpreter']), 'status': 'UNRESOLVED',
                          'path': elf['interpreter'], 'category': 'Dynamic loader'})
    return {'status': 'INCOMPLETE', 'libraries': libraries,
            'detail': 'ELF dependency table read locally. Runtime availability has not yet been checked.\n'
                      + 'Required: ' + ', '.join(elf['needed']) + '\nDynamic loader: ' + (elf['interpreter'] or 'none'),
            'error': ''}


def scan_binary_archive(binary, inventory):
    from docker_archive_libraries import find_in_archive
    report = local_elf_report(binary)
    if report['status'] != 'INCOMPLETE':
        return report
    for item in report['libraries']:
        matches = find_in_archive(inventory, item['name'])
        if item['category'] == 'Dynamic loader':
            declared = item['path']
            exact = declared.lstrip('/')
            matches = [declared] if exact in inventory.get('paths', {}) else matches
        if matches:
            item['status'] = 'FOUND'
            item['path'] = matches[0]
        else:
            item['status'] = 'MISSING'
            item['path'] = ''
    report['status'] = 'MISSING' if any(x['status'] == 'MISSING' for x in report['libraries']) else 'OK'
    report['detail'] += '\nMatched file names against the selected Docker runtime archive. '
    report['detail'] += 'This checks file presence, not linker ABI compatibility or Java compatibility.'
    report['error'] = ('Some required library filenames were not present in the selected Docker archive.'
                       if report['status'] == 'MISSING' else '')
    return report


def scan_binary(binary, runtime, timeout=75, runner=subprocess.run):
    binary = Path(binary)
    if not binary.is_file():
        return {'status': 'ERROR', 'libraries': [], 'detail': '', 'error': 'Executable file does not exist: ' + str(binary)}
    if not is_elf(binary):
        return {'status': 'SKIPPED', 'libraries': [], 'detail': '', 'error': 'Not an ELF Linux executable.'}
    try:
        elf = elf_dependencies(binary)
    except (OSError, ValueError, struct.error) as exc:
        return {'status': 'ERROR', 'libraries': [], 'detail': '', 'error': 'ELF analysis failed: ' + str(exc)}
    if elf['static']:
        return {'status': 'STATIC', 'libraries': [], 'detail': 'Static ELF binary: no shared library requirements.', 'error': ''}
    fallback = [{'name': name, 'status': 'UNRESOLVED', 'path': '', 'category': 'Shared library'} for name in elf['needed']]
    if elf['interpreter']:
        fallback.append({'name': os.path.basename(elf['interpreter']), 'status': 'UNRESOLVED', 'path': elf['interpreter'], 'category': 'Dynamic loader'})
    cid = ''
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

    def command(args, wait=timeout):
        return runner(args, capture_output=True, text=True, errors='replace', timeout=wait,
                      stdin=subprocess.DEVNULL, creationflags=flags)

    try:
        created = command(['docker', 'create', '--pull=never', '--network=none',
                           '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=128',
                           '--memory=512m', '--user=65534:65534', '--entrypoint=/usr/bin/ldd',
                           runtime, '/tmp/component_dependency_probe'])
        if created.returncode != 0:
            raise RuntimeError('Docker create: ' + (created.stderr or created.stdout).strip())
        cid = created.stdout.strip()
        if not re.fullmatch(r'[a-fA-F0-9]{12,64}', cid):
            raise RuntimeError('Docker create returned an invalid container identifier')
        copied = command(['docker', 'cp', str(binary.resolve()), cid + ':/tmp/component_dependency_probe'])
        if copied.returncode != 0:
            raise RuntimeError('Docker copy: ' + (copied.stderr or copied.stdout).strip())
        started = command(['docker', 'start', '-a', cid])
        output = (started.stdout or '') + ('\n' + started.stderr if started.stderr else '')
        result = parse_ldd(output, started.returncode)
        if result['status'] == 'ERROR' and not result['libraries']:
            raise RuntimeError('ldd inside runtime image: ' + output.strip()[-1500:])
        return result
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        return {'status': 'INCOMPLETE', 'libraries': fallback,
                'detail': 'ELF DT_NEEDED entries: ' + (', '.join(elf['needed']) or '(none)') + '\n'
                          + 'Interpreter: ' + (elf['interpreter'] or '(not declared)'),
                'error': 'Runtime library locations could not be checked: ' + str(exc)}
    finally:
        if cid:
            try:
                command(['docker', 'rm', '-f', cid], wait=25)
            except (OSError, subprocess.TimeoutExpired):
                pass


def metrics(result):
    libraries = result.get('libraries', [])
    return {
        'needed': len(libraries),
        'found': sum(item.get('status') == 'FOUND' for item in libraries),
        'missing': sum(item.get('status') == 'MISSING' for item in libraries),
        'planned': sum(item.get('status') == 'PLANNED' for item in libraries),
        'unresolved': sum(item.get('status') == 'UNRESOLVED' for item in libraries),
    }


def global_metrics(results):
    total = {'needed': 0, 'found': 0, 'missing': 0, 'planned': 0, 'unresolved': 0, 'checked': 0, 'not_checked': 0, 'failed': 0, 'static': 0}
    unique = {}
    for result in results.values():
        status = result.get('status', 'NOT CHECKED')
        if status == 'NOT CHECKED':
            total['not_checked'] += 1
            continue
        if status == 'PREVIEW':
            total['not_checked'] += 1
        if status in ('ERROR', 'SKIPPED', 'INCOMPLETE'):
            total['failed'] += 1
        if status == 'STATIC':
            total['static'] += 1
        if status not in ('ERROR', 'SKIPPED', 'PREVIEW'):
            total['checked'] += 1
        for key, value in metrics(result).items():
            total[key] += value
        for item in result.get('libraries', []):
            key = (item.get('name', ''), item.get('category', ''))
            previous = unique.get(key)
            if previous is None or (previous['status'] == 'FOUND' and item['status'] != 'FOUND'):
                unique[key] = item
    total['unique_needed'] = len(unique)
    total['unique_found'] = sum(item['status'] == 'FOUND' for item in unique.values())
    total['unique_missing'] = sum(item['status'] == 'MISSING' for item in unique.values())
    total['unique_planned'] = sum(item['status'] == 'PLANNED' for item in unique.values())
    total['unique_unresolved'] = sum(item['status'] == 'UNRESOLVED' for item in unique.values())
    return total
