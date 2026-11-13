import re
import json
import subprocess
from datetime import datetime

DISTRIBUTIONS = {
    'Debian': {'id': 'debian', 'repository': 'debian', 'versions': ('13', '12', '11', '10', '9', '8'), 'packages': 'apt'},
    'Ubuntu': {'id': 'ubuntu', 'repository': 'ubuntu', 'versions': ('26.04', '24.04', '22.04', '20.04', '18.04'), 'packages': 'apt'},
    'Alpine Linux': {'id': 'alpine', 'repository': 'alpine', 'versions': ('3.23', '3.22', '3.21', '3.20'), 'packages': 'apk'},
    'Fedora': {'id': 'fedora', 'repository': 'fedora', 'versions': ('43', '42', '41', '40'), 'packages': 'dnf'},
    'Rocky Linux': {'id': 'rocky', 'repository': 'rockylinux', 'versions': ('10', '9', '8'), 'packages': 'dnf'},
    'AlmaLinux': {'id': 'almalinux', 'repository': 'almalinux', 'versions': ('10', '9', '8'), 'packages': 'dnf'},
    'Oracle Linux': {'id': 'ol', 'repository': 'oraclelinux', 'versions': ('10', '9', '8'), 'packages': 'dnf'},
    'Arch Linux': {'id': 'arch', 'repository': 'archlinux', 'versions': ('latest',), 'packages': 'pacman'},
    'Amazon Linux': {'id': 'amzn', 'repository': 'amazonlinux', 'versions': ('2023', '2'), 'packages': 'dnf'},
}

HISTORICAL_BASES = {('Debian', '8'): 'debian:jessie-20201117'}

PREBUILT = {
    ('Debian', '12'): 'buildpack-deps:bookworm',
    ('Debian', '13'): 'buildpack-deps:trixie',
    ('Ubuntu', '22.04'): 'buildpack-deps:jammy',
    ('Ubuntu', '24.04'): 'buildpack-deps:noble',
    ('Ubuntu', '26.04'): 'buildpack-deps:resolute',
}

ARCHITECTURES = ('linux/amd64', 'linux/arm64', 'linux/386', 'linux/arm/v7', 'linux/arm/v6', 'linux/ppc64le', 'linux/s390x', 'linux/riscv64')

OPTIONS = ('Preconfigured buildpack-deps (when available)', 'Full compiler toolkit (build from distribution base)', 'Distribution base only (no compiler installation)')


def normalize_version(value):
    return str(value or '').strip().split(' ', 1)[0]


def system_distribution(system):
    identifier = str(system.get('id') or '').strip().lower()
    pretty = str(system.get('os') or '').lower()
    for label, data in DISTRIBUTIONS.items():
        if identifier == data['id'] or (identifier in ('', 'linux') and label.lower() in pretty):
            return label
    if identifier in ('rhel', 'centos'):
        return 'Rocky Linux'
    return ''


def matching_runtime(system):
    if not isinstance(system, dict):
        system = {}
    distro = system_distribution(system)
    version = normalize_version(system.get('version_id'))
    arch = str(system.get('architecture') or '').lower().strip()
    aliases = {'x86_64': 'amd64', 'aarch64': 'arm64', 'x86': '386', 'i686': '386'}
    arch = aliases.get(arch, arch)
    if arch == 'arm':
        variant = str(system.get('variant') or '').lower().strip()
        arch = 'arm/' + variant if variant in ('v5', 'v6', 'v7') else ''
    platform = 'linux/' + arch if arch else ''
    return distro, version, platform


def preferred_preset(distribution, version):
    if (distribution, normalize_version(version)) in PREBUILT:
        return OPTIONS[0]
    return OPTIONS[1]


def build_spec(distribution, version, platform, preset, source_override=""):
    if distribution not in DISTRIBUTIONS:
        raise ValueError('Choose a supported Linux distribution.')
    version = normalize_version(version)
    if not version or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', version):
        raise ValueError('Enter a valid distribution version or tag.')
    if platform not in ARCHITECTURES:
        raise ValueError('Choose a supported CPU architecture.')
    if preset not in OPTIONS:
        raise ValueError('Choose a builder preset.')
    release = DISTRIBUTIONS[distribution]
    prebuilt = PREBUILT.get((distribution, version))
    if preset == OPTIONS[0] and not prebuilt:
        raise ValueError('No curated buildpack-deps tag is available for this release. Choose Full compiler toolkit instead.')
    source_image = prebuilt if preset == OPTIONS[0] else HISTORICAL_BASES.get((distribution, version), release['repository'] + ':' + version)
    override = str(source_override or '').strip()
    if override:
        if len(override) > 260 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:@+-]*', override):
            raise ValueError('Enter a valid custom Docker image reference without spaces or shell characters.')
        source_image = override
    family = release['packages']
    if preset == OPTIONS[0] or preset == OPTIONS[2]:
        install_command = ''
    elif family == 'apt':
        updater = 'apt-get update'
        if distribution == 'Debian' and version.isdigit() and int(version) <= 10:
            updater = ("if [ -f /etc/apt/sources.list ]; then "
                       "sed -i 's@http://deb.debian.org/debian@http://archive.debian.org/debian@g; s@http://security.debian.org/debian-security@http://archive.debian.org/debian-security@g; s@http://httpredir.debian.org/debian@http://archive.debian.org/debian@g' /etc/apt/sources.list; "
                       "sed -i '/-updates[[:space:]]/d' /etc/apt/sources.list; fi; "
                       "printf '%s\\n' 'Acquire::Check-Valid-Until \"false\";' > /etc/apt/apt.conf.d/99builder-archive; apt-get update")
        install_command = updater + ' && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends build-essential cmake ninja-build pkg-config git curl wget ca-certificates autoconf automake libtool bison flex file patch python3 perl && rm -rf /var/lib/apt/lists/*'
    elif family == 'apk':
        install_command = 'apk add --no-cache build-base cmake ninja pkgconf git curl wget ca-certificates autoconf automake libtool bison flex file patch python3 perl bash'
    elif family == 'dnf':
        if distribution == 'Amazon Linux' and version == '2':
            install_command = 'yum install -y gcc gcc-c++ make cmake git curl wget autoconf automake libtool bison flex patch python3 perl && yum clean all'
        else:
            install_command = 'dnf install -y gcc gcc-c++ make cmake ninja-build pkgconf-pkg-config git curl wget ca-certificates autoconf automake libtool bison flex file patch python3 perl && dnf clean all'
    elif family == 'pacman':
        install_command = 'pacman -Syu --noconfirm --needed base-devel cmake ninja git curl wget autoconf automake libtool bison flex file patch python perl'
    else:
        raise ValueError('No package-installation recipe available for this distribution.')
    return {'image': source_image, 'command': install_command, 'distribution': distribution,
            'version': version, 'platform': platform, 'preset': preset}


def timestamp_tag(distribution, version, platform, when=None):
    when = when or datetime.now()
    stem = re.sub(r'[^a-z0-9_.-]+', '-', distribution.lower()).strip('-')
    release = re.sub(r'[^a-z0-9_.-]+', '-', version.lower()).strip('-')
    arch = re.sub(r'[^a-z0-9_.-]+', '-', platform.replace('linux/', '').lower()).strip('-')
    month = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')[when.month - 1]
    date = f'{month}{when.day}_{when.hour % 12 or 12}.{when:%M}{"am" if when.hour < 12 else "pm"}'
    return f'local-builder-{stem}-{release}-{arch}:{date}'


def detect_runtime_image_system(image, timeout=40):
    image = str(image or '').strip()
    if not image:
        return {}
    system = {}
    try:
        result = subprocess.run(['docker', 'image', 'inspect', '--format', '{{json .}}', image],
                                capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            details = json.loads(result.stdout.strip())
            system['architecture'] = str(details.get('Architecture') or '')
            if details.get('Variant'):
                system['variant'] = str(details['Variant'])
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        result = subprocess.run(['docker', 'run', '--rm', '--pull', 'never', '--network', 'none',
                                 '--entrypoint', '/bin/sh', image, '-c', 'cat /etc/os-release 2>/dev/null || cat /usr/lib/os-release 2>/dev/null'],
                                capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if '=' not in line or line.lstrip().startswith('#'):
                    continue
                key, value = line.split('=', 1)
                value = value.strip().strip('"\'')
                if key == 'ID':
                    system['id'] = value
                elif key == 'VERSION_ID':
                    system['version_id'] = value
                elif key == 'PRETTY_NAME':
                    system['os'] = value
    except (OSError, subprocess.TimeoutExpired):
        pass
    return system
