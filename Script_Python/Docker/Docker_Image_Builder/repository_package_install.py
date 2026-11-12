import re
import shlex
import subprocess
import tempfile
import uuid
from pathlib import Path

from network_policy import validate_packages, require_local_image
from package_repository_finder import _docker_shell, _repository_override, _repository_setup, _run, inspect_repository_image


def infer_packages_from_install_command(command):
    value = str(command or '').strip()
    if not value or any(character in value for character in (';', '|', '&', '\n', '\r', '`', '$')):
        return []
    try:
        words = shlex.split(value)
    except ValueError:
        return []
    if len(words) < 3:
        return []
    manager = words[0]
    if manager not in ('apt-get', 'apt', 'apk', 'dnf', 'yum', 'microdnf'):
        return []
    if words[1] not in ('install', 'add'):
        return []
    names = []
    skipped_argument = False
    for value in words[2:]:
        if skipped_argument:
            skipped_argument = False
            continue
        if value in ('-t', '--target-release', '--releasever', '--enablerepo', '--disablerepo'):
            skipped_argument = True
            continue
        if value.startswith('-'):
            continue
        try:
            names.extend(validate_packages([value]))
        except ValueError:
            return []
    return validate_packages(names)


def custom_install_problem(command):
    custom = str(command or '').strip()
    if not custom:
        return ''
    if re.match(r'^sudo(?:\s|$)', custom):
        return 'Docker executes installation commands as root, and sudo may be unavailable.'
    try:
        words = shlex.split(custom)
    except ValueError:
        return ''
    while words and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=[^\s]*', words[0]):
        words.pop(0)
    if words and words[0] in ('apt', 'apt-get', 'yum', 'dnf', 'microdnf'):
        if 'install' in words[1:] and not any(flag in ('-y', '--yes', '--assume-yes', '--assumeyes') for flag in words[1:]):
            return 'This custom package-manager command may ask for interactive confirmation, which Docker builds cannot provide. Add -y or leave the custom command blank for automatic noninteractive installation.'
    return ''


def archived_repository_recommended(info):
    family = str(info.get('id') or '').lower()
    try:
        major = int(str(info.get('version_id') or '').split('.', 1)[0])
    except (TypeError, ValueError):
        return False
    return info.get('manager') == 'apt' and ((family == 'debian' and major <= 9) or
                                              (family == 'ubuntu' and major <= 17))


def repository_install_command(info, packages, use_archive=False, allow_unverified=False, custom_command=''):
    names = validate_packages(packages)
    custom = str(custom_command or '').strip()
    if custom and ('\n' in custom or '\r' in custom or '\x00' in custom or len(custom) > 4000 or custom.endswith('\\')):
        raise ValueError('The custom install command must be one safe Dockerfile RUN line of at most 4,000 characters.')
    problem = custom_install_problem(custom)
    if problem:
        raise ValueError(problem + ' Clear the custom command field to use automatic package installation.')
    if not custom and not names:
        raise ValueError('Choose one or more OS package names, or provide a custom installation command.')
    manager = str(info.get('manager') or '').lower()
    if allow_unverified and not use_archive:
        raise ValueError('Allowing unauthenticated packages requires an explicitly selected archived repository.')
    if custom and allow_unverified:
        raise ValueError('The expired-signature approval applies to the automatic package installer only. Clear the custom command field to enable it; custom commands are not rewritten with APT authentication overrides.')
    quoted = ' '.join(shlex.quote(name) for name in names)
    if custom:
        if use_archive:
            setup, _ = _repository_setup(info, use_archive=True)
            return 'set -eu; ' + setup + '; ' + custom
        return 'set -eu; ' + custom
    if manager == 'apt':
        setup, apt = _repository_setup(info, use_archive=use_archive)
        options = ' --allow-unauthenticated' if allow_unverified else ''
        checks = '; '.join('if ! apt-cache show ' + shlex.quote(name) + ' >/dev/null 2>&1; then '
                           'echo ' + shlex.quote('PACKAGE_NOT_FOUND: ' + name) + ' >&2; exit 43; fi'
                           for name in names)
        return 'set -eu; ' + setup + '; ' + checks + '; DEBIAN_FRONTEND=noninteractive ' + apt + \
               ' install -y --no-install-recommends' + options + ' ' + quoted + '; apt-get clean'
    if use_archive:
        raise ValueError('Automatic archived repository configuration is supported for APT images only.')
    if allow_unverified:
        raise ValueError('Unverified-package installation is supported for archived APT images only.')
    if manager == 'apk':
        command = 'apk add --no-cache '
    elif manager == 'dnf':
        command = 'dnf install -y '
    elif manager == 'yum':
        command = 'yum install -y '
    elif manager == 'microdnf':
        command = 'microdnf install -y '
    else:
        raise ValueError('No supported package manager detected. Choose a compatible Linux image.')
    return 'set -eu; ' + command + quoted


def installed_package_records(image, info, cancel=None):
    manager = info.get('manager')
    if manager == 'apt':
        script = "dpkg-query -W -f='${Package}\\t${Version}\\t${Architecture}\\t${Status}\\n'"
    elif manager in ('dnf', 'yum', 'microdnf'):
        script = "rpm -qa --qf '%{NAME}\\t%{VERSION}-%{RELEASE}\\t%{ARCH}\\n'"
    else:
        return {}
    output = _docker_shell(image, script, timeout=120, cancel=cancel, max_output_lines=0)
    records = {}
    for line in output.splitlines():
        values = line.split('\t')
        if len(values) < 3:
            continue
        if manager == 'apt' and (len(values) < 4 or values[3].strip() != 'install ok installed'):
            continue
        name, version, arch = (value.strip() for value in values[:3])
        if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:+-]*', name):
            records[name] = {'name': name, 'version': version, 'architecture': arch}
    return records


def _image_user(image, cancel=None):
    output = _run(['docker', 'image', 'inspect', '--format', '{{.Config.User}}', image],
                  timeout=60, cancel=cancel).strip()
    if not output or output in ('root', '0'):
        return ''
    if not re.fullmatch(r'[A-Za-z0-9_.:-]+', output):
        raise RuntimeError('Cannot safely preserve the original Docker image USER: ' + output)
    return output


def install_repository_packages_in_image(image, packages, role='builder', use_archive=False,
                                         allow_unverified=False, verify_commands=(), cancel=None,
                                         progress=None, info=None, custom_command=''):
    if role not in ('builder', 'runtime'):
        raise ValueError('The installation target must be a builder or runtime image.')
    image = str(image or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_./:@+-]+', image):
        raise ValueError('Select a valid Docker image before installing packages.')
    require_local_image(image)
    names = validate_packages(packages)
    commands = sorted(set(verify_commands))
    if any(not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.+-]*', str(command)) for command in commands):
        raise ValueError('Verification commands must be executable names, without shell syntax or paths.')
    if custom_command and not names and not commands:
        raise ValueError('For a custom install command, provide an expected OS package or executable for verification.')
    info = info or inspect_repository_image(image, cancel=cancel, progress=progress)
    if info.get('image') != image:
        raise RuntimeError('The inspected image does not match the selected Docker image.')
    if use_archive:
        archive = _repository_override(info, archive=True)
        if progress:
            progress('Using archived distribution repository: ' + archive)
    if progress:
        progress('Selected ' + info.get('pretty_name', 'Linux') + '; package manager: ' + info.get('manager', '?'))
        progress('Requested packages: ' + ', '.join(names))
        if custom_command:
            progress('User-provided installation command: ' + str(custom_command))
        progress('Dependencies will be resolved by the Linux package manager inside Docker.')
        if allow_unverified:
            progress('SECURITY WARNING: User explicitly approved unauthenticated APT packages for this installation.')
    before = installed_package_records(image, info, cancel)
    script = repository_install_command(info, names, use_archive=use_archive,
                                        allow_unverified=allow_unverified, custom_command=custom_command)
    original_user = _image_user(image, cancel)
    tag = 'component-' + role + '-repo:' + uuid.uuid4().hex[:16]
    dockerfile = 'FROM ' + image + '\nUSER root\nRUN ' + script + '\n'
    if original_user:
        dockerfile += 'USER ' + original_user + '\n'
    with tempfile.TemporaryDirectory(prefix='component_repository_install_') as directory:
        root = Path(directory)
        (root / 'Dockerfile').write_text(dockerfile, encoding='utf-8')
        if progress:
            progress('Building a new Docker ' + role + ' with approved repository access; original image is preserved...')
        _run(['docker', 'build', '--pull=false', '--no-cache', '--network=default', '--progress=plain', '-t', tag, str(root)],
             timeout=3600, cancel=cancel, progress=progress, idle_timeout=0)
    check_parts = ['set -eu']
    for name in names:
        quoted = shlex.quote(name)
        if info['manager'] == 'apt':
            check_parts.append('test "$(dpkg-query -W -f=\'${Status}\' ' + quoted +
                               ' 2>/dev/null)" = "install ok installed"')
        elif info['manager'] == 'apk':
            check_parts.append('apk info -e ' + quoted + ' >/dev/null')
        else:
            check_parts.append('rpm -q ' + quoted + ' >/dev/null')
    for command in commands:
        check_parts.append('command -v ' + shlex.quote(command) + ' >/dev/null')
    check_parts.append('echo REPOSITORY_PACKAGE_INSTALL_VERIFIED')
    if progress:
        progress('Verifying requested packages and commands inside ' + tag + '...')
    verification = _docker_shell(tag, '; '.join(check_parts), timeout=180, cancel=cancel,
                                  progress=progress, max_output_lines=0)
    after = installed_package_records(tag, info, cancel)
    updated = [entry for name, entry in after.items() if name not in before or before[name]['version'] != entry['version']]
    if not updated:
        updated = [after[name] for name in names if name in after]
    for name in names:
        if name not in {record['name'] for record in updated}:
            record = after.get(name)
            if record:
                updated.append(record)
    if info['manager'] == 'apk':
        updated = [{'name': name, 'version': '', 'architecture': info.get('arch', '')} for name in names]
    if progress:
        progress('SUCCESS: ' + str(len(updated)) + ' installed or updated package records; verified ' +
                 str(len(commands)) + ' requested executables.')
    return {'source_image': image, 'installed_image': tag, 'builder_from': image,
            'builder_image': tag, 'builder_info': info, 'role': role, 'network': 'approved',
            'packages': updated, 'requested_packages': names,
            'repository': _repository_override(info, archive=use_archive) if use_archive else 'configured image repositories',
            'allow_unverified': bool(allow_unverified), 'custom_command': str(custom_command or ''),
            'verification': verification}
