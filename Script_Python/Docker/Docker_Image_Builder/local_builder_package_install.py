import hashlib
import io
import json
import re
import shlex
import shutil
import tarfile
import tempfile
from pathlib import Path

from local_package_catalog import _rpm_header, package_archive_type, package_identity
from package_repository_finder import _docker_shell, _run, inspect_repository_image


def _deb_fields(path):
    with Path(path).open('rb') as handle:
        if handle.read(8) != b'!<arch>\n':
            raise ValueError('Invalid Debian package archive: ' + str(path))
        control = None
        while True:
            header = handle.read(60)
            if not header:
                break
            if len(header) != 60 or header[58:60] != b'`\n':
                raise ValueError('Damaged Debian package archive: ' + str(path))
            try:
                length = int(header[48:58].decode('ascii').strip())
            except ValueError as exc:
                raise ValueError('Invalid Debian package header: ' + str(path)) from exc
            if length < 0 or length > 512 * 1024 * 1024:
                raise ValueError('Invalid Debian package member size: ' + str(path))
            name = header[:16].decode('utf-8', 'replace').strip().rstrip('/')
            if name.startswith('control.tar.'):
                control = handle.read(length)
            else:
                handle.seek(length, 1)
            if length % 2:
                handle.seek(1, 1)
            if control is not None:
                break
    if control is None:
        raise ValueError('Debian package has no control archive: ' + str(path))
    if control[:4] == b'\x28\xb5\x2f\xfd':
        return {}
    try:
        with tarfile.open(fileobj=io.BytesIO(control), mode='r:*') as archive:
            member = next((item for item in archive if item.name.lstrip('./') == 'control' and item.isfile()), None)
            if member is None:
                return {}
            stream = archive.extractfile(member)
            if stream is None:
                return {}
            content = stream.read(1024 * 1024).decode('utf-8', 'replace')
    except (tarfile.TarError, OSError) as exc:
        raise ValueError('Could not read Debian package metadata: ' + str(path)) from exc
    result = {}
    current = ''
    for line in content.splitlines():
        if line[:1].isspace() and current:
            result[current] += ' ' + line.strip()
        elif ':' in line:
            key, value = line.split(':', 1)
            current = key.strip().lower()
            result[current] = value.strip()
    return result


def _apk_fields(path):
    try:
        with tarfile.open(path, 'r:*') as archive:
            member = next((item for item in archive if item.name.lstrip('./') == '.PKGINFO' and item.isfile()), None)
            if member is None:
                return {}
            stream = archive.extractfile(member)
            if stream is None:
                return {}
            content = stream.read(1024 * 1024).decode('utf-8', 'replace')
    except (tarfile.TarError, OSError):
        return {}
    return {key.strip(): value.strip() for line in content.splitlines() if ' = ' in line
            for key, value in [line.split(' = ', 1)]}


def describe_local_package(path):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ValueError('Package file not found: ' + str(path))
    manager = package_archive_type(path)
    if manager not in ('apt', 'apk', 'rpm'):
        raise ValueError('Choose a .deb, .apk, or .rpm package: ' + str(path))
    name, version = package_identity(path)
    architecture = ''
    dependencies = ''
    if manager == 'apt':
        fields = _deb_fields(path)
        name = fields.get('package') or name
        version = fields.get('version') or version
        architecture = fields.get('architecture') or (path.stem.rsplit('_', 1)[-1] if '_' in path.stem else '')
        dependencies = ', '.join(value for value in (fields.get('pre-depends', ''), fields.get('depends', '')) if value)
    elif manager == 'rpm':
        fields = _rpm_header(path)
        if not fields:
            raise ValueError('Invalid RPM metadata: ' + str(path))
        architecture = fields.get(1022, '')
    else:
        fields = _apk_fields(path)
        name = fields.get('pkgname') or name
        version = fields.get('pkgver') or version
        architecture = fields.get('arch', '')
        dependencies = fields.get('depend', '')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_.:-]*', name):
        raise ValueError('Package metadata contains an unsupported name: ' + name)
    return {'path': str(path), 'name': name, 'version': version, 'architecture': architecture,
            'dependencies': dependencies, 'manager': manager, 'bytes': path.stat().st_size,
            'sha256': digest.hexdigest(), 'signature_verified': False}


def _normal_arch(value):
    name = str(value or '').strip().lower()
    return {'x86_64': 'amd64', 'x64': 'amd64', 'aarch64': 'arm64', 'armv7l': 'armhf',
            'arm/v7': 'armhf', 'i686': '386', 'i386': '386', 'x86': '386'}.get(name, name)


def check_local_package_compatibility(builder_info, packages):
    manager = str(builder_info.get('manager') or '')
    permitted = {'apt': ('apt',), 'apk': ('apk',),
                 'rpm': ('dnf', 'yum', 'microdnf')}
    incompatible = []
    warnings = []
    target_arch = _normal_arch(builder_info.get('arch'))
    target_version = str(builder_info.get('version_id') or '')
    target_distro = str(builder_info.get('id') or '').lower()
    if len({row['manager'] for row in packages}) > 1:
        incompatible.append('Local DEB, APK, and RPM packages cannot be mixed in one installation.')
    for row in packages:
        if manager not in permitted.get(row['manager'], ()):
            incompatible.append(row['name'] + ': this Docker image uses ' + manager + ' instead of ' + row['manager'] + '.')
        arch = _normal_arch(row['architecture'])
        if arch and arch not in ('all', 'noarch', 'any') and arch != target_arch:
            incompatible.append(row['name'] + ': package architecture ' + row['architecture'] +
                                ' does not match Docker image architecture ' + str(builder_info.get('arch') or '?') + '.')
        if not arch:
            warnings.append(row['name'] + ': architecture could not be determined from package metadata.')
        if row['manager'] == 'apt' and target_distro == 'debian':
            match = re.search(r'(?:\+|~)deb(\d+)(?:u\d+)?(?:\b|$)', row['version'], re.I)
            if match and target_version and match.group(1) != target_version.split('.', 1)[0]:
                incompatible.append(row['name'] + ': built for Debian ' + match.group(1) +
                                    ', but selected Docker image is Debian ' + target_version + '.')
    return incompatible, warnings


def _dependency_alternatives(group):
    result = []
    for part in group.split('|'):
        text = re.sub(r'\s*(?:\[[^]]*\]|<[^>]*>)', '', part.strip())
        match = re.match(r'^([a-zA-Z0-9][a-zA-Z0-9+.-]*)(?::[a-zA-Z0-9-]+)?\s*(?:\(\s*(<<|<=|=|>=|>>)\s*([^)]*?)\s*\))?', text)
        if match:
            result.append((match.group(1), match.group(2) or '', match.group(3) or ''))
    return result


def _installed_debian_packages(image, cancel=None):
    text = _docker_shell(image, "dpkg-query -W -f='${Package}\\t${Version}\\t${Status}\\t${Provides}\\n'",
                         timeout=90, cancel=cancel)
    installed = {}
    for line in text.splitlines():
        pieces = line.split('\t', 3)
        if len(pieces) < 3 or pieces[2].strip() != 'install ok installed':
            continue
        name, version = pieces[0].strip(), pieces[1].strip()
        installed[name.split(':', 1)[0]] = version
        if len(pieces) == 4:
            for virtual in pieces[3].split(','):
                match = re.match(r'\s*([a-zA-Z0-9][a-zA-Z0-9+.-]*)(?:\s*\(\s*=\s*([^)]*)\s*\))?', virtual)
                if match and match.group(1) not in installed:
                    installed[match.group(1)] = (match.group(2) or '').strip()
    return installed


def _compare_debian_versions(image, comparisons, cancel=None):
    pairs = list(dict.fromkeys(comparisons))
    if not pairs:
        return {}
    scripts = []
    for index, (actual, operator, requested) in enumerate(pairs):
        scripts.append('if dpkg --compare-versions ' + shlex.quote(actual) + ' ' + shlex.quote(operator) +
                       ' ' + shlex.quote(requested) + '; then echo ' +
                       shlex.quote('VERSION_CHECK|' + str(index) + '|YES') + '; else echo ' +
                       shlex.quote('VERSION_CHECK|' + str(index) + '|NO') + '; fi')
    output = _docker_shell(image, 'set -eu; ' + '; '.join(scripts), timeout=90, cancel=cancel)
    checked = {}
    for line in output.splitlines():
        match = re.fullmatch(r'VERSION_CHECK\|(\d+)\|(YES|NO)', line.strip())
        if match:
            checked[pairs[int(match.group(1))]] = match.group(2) == 'YES'
    if len(checked) != len(pairs):
        raise RuntimeError('Could not verify required Debian package versions in the selected builder.')
    return checked


def preflight_local_builder_packages(builder_image, files, cancel=None, progress=None):
    image = str(builder_image or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_./:@+-]+', image):
        raise ValueError('Select or load a valid Docker builder image in Tab 1.')
    paths = list(dict.fromkeys(str(Path(path).expanduser().resolve()) for path in files))
    if not paths:
        raise ValueError('Choose one or more local Linux package archives.')
    packages = [describe_local_package(path) for path in paths]
    if progress:
        progress('Checking local packages and selected Docker image ' + image)
    info = inspect_repository_image(image, cancel=cancel, progress=progress)
    errors, warnings = check_local_package_compatibility(info, packages)
    if errors:
        raise RuntimeError('Package / Docker image mismatch:\n' + '\n'.join(errors))
    rows = []
    if packages[0]['manager'] == 'apt':
        installed = _installed_debian_packages(image, cancel)
        local = {item['name']: item['version'] for item in packages}
        version_checks = []
        for item in packages:
            for relation in item.get('dependencies', '').split(','):
                if not relation.strip():
                    continue
                choices = _dependency_alternatives(relation)
                if not choices:
                    rows.append({'package': item['name'], 'requirement': relation.strip(),
                                 'status': 'UNRESOLVED', 'provider': '', 'version': ''})
                    continue
                candidates = []
                for name, operator, required in choices:
                    for origin, mapping in (('IN BUILDER', installed), ('SELECTED LOCAL', local)):
                        if name in mapping:
                            version = mapping[name]
                            candidates.append((origin, name, version, operator, required))
                            if operator and required and version:
                                version_checks.append((version, operator, required))
                rows.append({'package': item['name'], 'requirement': relation.strip(),
                             'status': 'MISSING', 'provider': '', 'version': '', 'candidates': candidates})
        passed_versions = _compare_debian_versions(image, version_checks, cancel)
        for row in rows:
            candidates = row.pop('candidates', [])
            for origin, name, version, operator, required in candidates:
                if not operator or (version and passed_versions.get((version, operator, required), False)):
                    row.update({'status': origin, 'provider': name, 'version': version})
                    break
            if row['status'] == 'MISSING' and candidates:
                row.update({'status': 'WRONG VERSION', 'provider': candidates[0][1],
                            'version': candidates[0][2]})
    else:
        warnings.append('Automatic installed-dependency checks are currently available for Debian DEB packages only.')
        for item in packages:
            if item.get('dependencies'):
                rows.append({'package': item['name'], 'requirement': item['dependencies'],
                             'status': 'UNRESOLVED', 'provider': '', 'version': ''})
    missing = [item for item in rows if item['status'] not in ('IN BUILDER', 'SELECTED LOCAL')]
    if progress:
        for item in rows:
            progress('DEPENDENCY ' + item['package'] + ' -> ' + item['requirement'] + ': ' +
                     item['status'] + ((' (' + item['provider'] + ' ' + item['version'] + ')') if item['provider'] else ''))
        progress('PRECHECK: ' + str(len(rows) - len(missing)) + ' satisfied, ' +
                 str(len(missing)) + ' missing or unresolved dependencies.')
        for warning in warnings:
            progress('WARNING: ' + warning)
    return {'packages': packages, 'builder_info': info, 'dependencies': rows,
            'missing': missing, 'warnings': warnings}


def install_local_packages_in_builder(builder_image, files, cancel=None, progress=None, role='builder'):
    if role not in ('builder', 'runtime'):
        raise ValueError('Package installation target must be builder or runtime.')
    image = str(builder_image or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_./:@+-]+', image):
        raise ValueError('Select or load a valid Docker ' + role + ' image in Tab 1.')
    preflight = preflight_local_builder_packages(image, files, cancel=cancel, progress=progress)
    packages = preflight['packages']
    info = preflight['builder_info']
    if preflight['missing'] and packages[0]['manager'] == 'apt':
        raise RuntimeError('Installation stopped before building because required dependencies are missing:\n' +
                           '\n'.join(item['package'] + ' needs ' + item['requirement'] + ' [' + item['status'] + ']'
                                     for item in preflight['missing']) +
                           '\n\nAdd matching dependency DEB archives using Browse package file(s) and check again.')
    family = packages[0]['manager']
    token = hashlib.sha256((image + '|' + '|'.join(row['sha256'] for row in packages)).encode()).hexdigest()[:18]
    tag = 'component-' + role + '-local:' + token
    commands = {'apt': 'dpkg -i /tmp/component-local-packages/*.deb',
                'apk': 'apk add --no-network /tmp/component-local-packages/*.apk',
                'rpm': 'rpm -Uvh --replacepkgs /tmp/component-local-packages/*.rpm'}
    with tempfile.TemporaryDirectory(prefix='component_local_builder_') as directory:
        root = Path(directory)
        staged = root / 'packages'
        staged.mkdir()
        for number, package in enumerate(packages):
            if cancel is not None and cancel.is_set():
                raise RuntimeError('Package installation cancelled.')
            source = Path(package['path'])
            target = staged / (f'{number:04d}_' + source.name)
            shutil.copy2(source, target)
            if progress:
                progress('Staged ' + source.name + ' (' + f'{package["bytes"] / 1000000:.2f}' + ' MB)')
        dockerfile = ('FROM ' + image + '\nUSER root\nCOPY packages/ /tmp/component-local-packages/\n' +
                      'RUN set -eu; ' + commands[family] + '; rm -rf /tmp/component-local-packages\n')
        (root / 'Dockerfile').write_text(dockerfile, encoding='utf-8')
        if progress:
            progress('Installing local packages in a new ' + role + ' image without network access...')
        try:
            _run(['docker', 'build', '--pull=false', '--network=none', '--progress=plain', '-t', tag, str(root)],
                 timeout=1800, cancel=cancel, progress=progress, idle_timeout=0)
        except RuntimeError as exc:
            detail = str(exc)
            if 'depend' in detail.lower() or 'not going to be installed' in detail.lower():
                raise RuntimeError(detail + '\n\nSelect the missing dependency archives together with this package and retry.') from exc
            raise
    if progress:
        progress('Verifying installation inside ' + tag + '...')
    checks = []
    for package in packages:
        name = shlex.quote(package['name'])
        if family == 'apt':
            checks.append('test "$(dpkg-query -W -f=\'${Status}\' ' + name + ' 2>/dev/null)" = "install ok installed"')
        elif family == 'apk':
            checks.append('apk info -e ' + name + ' >/dev/null')
        else:
            checks.append('rpm -q ' + name + ' >/dev/null')
    checks.append('echo LOCAL_BUILDER_PACKAGES_VERIFIED')
    _docker_shell(tag, 'set -eu; ' + '; '.join(checks), timeout=90, cancel=cancel, progress=progress)
    return {'builder_from': image, 'builder_image': tag, 'builder_info': info,
            'source_image': image, 'installed_image': tag, 'role': role,
            'packages': packages, 'network': 'offline',
            'verification': 'installed in derived ' + role + '; archive signatures not authenticated'}
