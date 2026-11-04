import re
import subprocess

POLICY_OFFLINE = 'offline'
POLICY_APPROVAL = 'approval'
POLICIES = {POLICY_OFFLINE, POLICY_APPROVAL}
PACKAGE_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9.+:_-]*\Z')


def normalize_policy(value):
    return value if value in POLICIES else POLICY_APPROVAL


def package_names(components, stage):
    names = []
    for component in components:
        if not component.get('enabled', True):
            continue
        kind = str(component.get('kind', '') or '').strip().lower()
        if stage == 'builder':
            if kind == 'source':
                names.extend(str(component.get('build_deps', '') or '').split(','))
        elif stage == 'runtime':
            names.extend(str(component.get('runtime_packages', '') or '').split(','))
            if kind == 'os package':
                from local_package_catalog import component_package_identity
                names.append(component_package_identity(component)[0])
        else:
            raise ValueError('Unknown build stage: ' + str(stage))
    return validate_packages(names)


def validate_packages(values):
    result = []
    seen = set()
    for value in values:
        package = str(value or '').strip()
        if not package:
            continue
        if not PACKAGE_PATTERN.fullmatch(package):
            raise ValueError('Invalid OS package name: ' + package)
        if package not in seen:
            seen.add(package)
            result.append(package)
    return sorted(result)


def inspect_packages(image, packages, runner=None, timeout=45):
    requested = validate_packages(packages)
    if not requested:
        return {'installed': [], 'missing': [], 'manager': 'none'}
    if not str(image or '').strip():
        raise RuntimeError('No Docker image selected for dependency inspection.')
    program = '''if command -v dpkg-query >/dev/null 2>&1; then manager=apt; elif command -v apk >/dev/null 2>&1; then manager=apk; elif command -v rpm >/dev/null 2>&1; then manager=rpm; else echo "ERROR|No supported OS package database"; exit 31; fi
printf 'MANAGER|%s\\n' "$manager"
for package do
if [ "$manager" = apt ]; then
    if [ "$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true)" = 'install ok installed' ]; then found=1; else found=0; fi
elif [ "$manager" = apk ]; then
    if apk info -e "$package" >/dev/null 2>&1; then found=1; else found=0; fi
else
    if rpm -q "$package" >/dev/null 2>&1; then found=1; else found=0; fi
fi
printf 'PACKAGE|%s|%s\\n' "$package" "$found"
done'''
    args = ['docker', 'run', '--rm', '--pull=never', '--network=none', '--entrypoint', '/bin/sh', image, '-c', program, 'package-inspection', *requested]
    runner = runner or subprocess.run
    try:
        completed = runner(args, capture_output=True, text=True, errors='replace', timeout=timeout, stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('Package inventory check timed out. Check the Docker Linux Engine.') from exc
    except OSError as exc:
        raise RuntimeError('Cannot inspect Docker packages: ' + str(exc)) from exc
    if completed.returncode:
        raise RuntimeError('Package inventory check failed: ' + (completed.stderr or completed.stdout or 'no details').strip()[-1500:])
    installed = []
    missing = []
    manager = ''
    seen = set()
    for line in completed.stdout.splitlines():
        parts = line.strip().split('|')
        if len(parts) == 2 and parts[0] == 'MANAGER':
            manager = parts[1]
        elif len(parts) == 3 and parts[0] == 'PACKAGE' and parts[1] in requested and parts[1] not in seen:
            seen.add(parts[1])
            if parts[2] == '1':
                installed.append(parts[1])
            elif parts[2] == '0':
                missing.append(parts[1])
            else:
                raise RuntimeError('Invalid package-check output: ' + line)
    if len(seen) != len(requested) or manager not in ('apt', 'apk', 'rpm'):
        raise RuntimeError('Package inventory check returned incomplete results: ' + completed.stdout[-1000:])
    return {'installed': sorted(installed), 'missing': sorted(missing), 'manager': manager}


def permission_message(stage, image, inspection, extra_network=False, continue_on_decline=False):
    missing = inspection['missing']
    header = 'Builder source compilation' if stage == 'builder' else 'Final runtime image'
    lines = [header, 'Docker image: ' + str(image), '', 'Missing packages:']
    lines += ['  ' + name for name in missing] or ['  None']
    if extra_network:
        lines.extend(['', 'The source build command will also have network access and may download additional dependencies.'])
    lines.extend(['', 'Package managers can download additional transitive dependencies.', 'Allow network access for this build only?', 'Selecting No continues assembly offline and records missing dependencies.' if continue_on_decline else 'Selecting No cancels the build without downloading.'])
    return '\n'.join(lines)


def require_local_image(image, runner=None, timeout=20):
    tag = str(image or '').strip()
    if not tag:
        raise RuntimeError('Docker base image is not selected.')
    runner = runner or subprocess.run
    try:
        completed = runner(['docker', 'image', 'inspect', tag], capture_output=True, text=True,
                           errors='replace', timeout=timeout, stdin=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError('Cannot verify local Docker image: ' + tag + ': ' + str(exc)) from exc
    if completed.returncode:
        raise RuntimeError('Docker image is not available locally: ' + tag + '. Load the base archive in Tab 2. No online image pull was attempted.')
    return tag
