import posixpath
import re
import shlex
import json


PROTECTED_PACKAGES = {'filesystem', 'glibc', 'libc6', 'bash', 'coreutils', 'dpkg', 'rpm', 'systemd', 'busybox', 'apk-tools', 'base-files', 'base-passwd', 'ca-certificates'}


def java_runtime_packages(version, inventory):
    try:
        major = int(str(version).strip())
    except (TypeError, ValueError):
        return []
    if not 1 <= major <= 100:
        return []
    patterns = (
        rf'(?:jdk|jre)-{major}',
        rf'java-{major}-openjdk(?:-headless|-devel)?',
        rf'openjdk-{major}-(?:jre|jdk)(?:-headless)?',
        rf'openjdk{major}(?:-jre|-jdk|-jre-headless|-jdk-headless)?',
        rf'temurin-{major}-(?:jdk|jre)',
        rf'java-{major}-amazon-corretto(?:-devel|-headless)?',
    )
    os_packages = ((inventory or {}).get('packages') or {}).get('os') or []
    matches = []
    for record in os_packages:
        name = str(record.get('name', '') if isinstance(record, dict) else '').strip()
        if name and safe_package_name(name) and any(re.fullmatch(pattern, name, re.I) for pattern in patterns):
            if name.lower() not in {value.lower() for value in matches}:
                matches.append(name)
    return matches


def removal_id(kind, name, path=''):
    return '|'.join([str(kind), str(name), str(path)])


def normalize_removals(rows):
    result = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        kind = str(row.get('kind', '')).strip()
        name = str(row.get('name', '')).strip()
        path = str(row.get('path', '')).strip()
        if kind not in ('deferred', 'file', 'directory', 'os_package', 'python_package', 'r_package', 'perl_package') or not name:
            continue
        if kind == 'file' and not safe_file_path(path):
            continue
        if kind == 'directory' and not safe_directory_path(path):
            continue
        if kind in ('os_package', 'python_package', 'r_package', 'perl_package') and not safe_package_name(name):
            continue
        if kind == 'perl_package' and not re.fullmatch(r'[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*', name):
            continue
        value = {'kind': kind, 'name': name, 'path': path, 'status': 'REQUESTED',
                 'force': bool(row.get('force', False)) if kind == 'os_package' else False}
        if not any(removal_id(x['kind'], x['name'], x['path']) == removal_id(kind, name, path) for x in result):
            result.append(value)
    return result


def safe_file_path(path):
    path = str(path or '')
    clean = posixpath.normpath(path)
    prefixes = ('/opt/', '/usr/', '/bin/', '/sbin/', '/lib/', '/lib64/', '/app/', '/srv/')
    return (path.startswith(prefixes) and clean == path and not path.endswith('/') and
            not clean.startswith('/opt/component-builder/') and path not in prefixes and
            all(part not in ('.', '..') for part in path.split('/')))


def safe_directory_path(path):
    value = str(path or '').rstrip('/')
    return (value.startswith(('/opt/', '/usr/local/', '/app/', '/srv/', '/var/opt/')) and
            posixpath.normpath(value) == value and not value.startswith('/opt/component-builder') and
            all(part not in ('.', '..') for part in value.split('/')) and
            len([part for part in value.split('/') if part]) >= 2)


def safe_package_name(name):
    value = str(name or '')
    return bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9+_.:-]*', value))


def protected_package(name):
    return str(name or '').lower() in PROTECTED_PACKAGES


def remove_deferred_packages(packages, removals):
    excluded = {x['name'].lower() for x in normalize_removals(removals) if x['kind'] == 'deferred'}
    return [name for name in packages or [] if str(name).lower() not in excluded]


def dockerfile_removal_lines(removals, strict=False):
    statements = []
    packages = {False: [], True: []}
    for row in normalize_removals(removals):
        name = row['name']
        if row['kind'] == 'file':
            path = shlex.quote(row['path'])
            statements.append('RUN set -eu; rm -f -- ' + path + '; test ! -e ' + path + ' && test ! -L ' + path)
        if row['kind'] == 'directory':
            path = shlex.quote(row['path'].rstrip('/'))
            statements.append('RUN set -eu; rm -rf -- ' + path + '; test ! -e ' + path + ' && test ! -L ' + path)
        if row['kind'] == 'os_package':
            group = packages[bool(row.get('force', False))]
            if name not in group:
                group.append(name)
        if row['kind'] == 'python_package':
            pkg = shlex.quote(name)
            statements.append('RUN set -eu; if command -v python3 >/dev/null 2>&1 && python3 -m pip --version >/dev/null 2>&1; then '
                              'python3 -m pip uninstall -y ' + pkg + '; ! python3 -m pip show ' + pkg + ' >/dev/null 2>&1; '
                              'elif command -v python >/dev/null 2>&1 && python -m pip --version >/dev/null 2>&1; then '
                              'python -m pip uninstall -y ' + pkg + '; ! python -m pip show ' + pkg + ' >/dev/null 2>&1; '
                              'else echo "Python pip unavailable for uninstall: ' + name + '" >&2; exit 24; fi')
        if row['kind'] == 'r_package':
            quoted = json.dumps(name)
            expression = ('pkg <- ' + quoted + '; ip <- installed.packages(); '
                          'libs <- unique(ip[ip[, "Package"] == pkg, "LibPath"]); '
                          'if (!length(libs)) stop("R package is not installed"); '
                          'for (lib in libs) remove.packages(pkg, lib=lib); '
                          'if (pkg %in% rownames(installed.packages())) stop("R package still present")')
            statements.append('RUN set -eu; command -v Rscript >/dev/null 2>&1 || { echo "Rscript unavailable" >&2; exit 24; }; Rscript -e ' + shlex.quote(expression))
        if row['kind'] == 'perl_package':
            if not re.fullmatch(r'[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*', name):
                continue
            pkg = shlex.quote(name)
            statements.append('RUN set -eu; command -v cpanm >/dev/null 2>&1 || { echo "cpanm unavailable for Perl uninstall" >&2; exit 24; }; '
                              'cpanm --uninstall ' + pkg + '; ! perl -M' + pkg + ' -e 1 >/dev/null 2>&1')
    for force in (True, False):
        group = packages[force]
        if not group:
            continue
        arguments = ' '.join(shlex.quote(name) for name in group)
        dpkg_erase = 'DEBIAN_FRONTEND=noninteractive dpkg --force-depends --purge "$@"; ' if force else 'dpkg --no-act --purge "$@"; DEBIAN_FRONTEND=noninteractive dpkg --purge "$@"; '
        rpm_erase = 'rpm -e --nodeps "$@"; ' if force else 'rpm -e --test "$@"; rpm -e "$@"; '
        apk_erase = 'apk del --force-broken-world "$@"; ' if force else 'apk del "$@"; '
        cmd = ('set -eu; set -- ' + arguments + '; '
               'if command -v dpkg-query >/dev/null 2>&1 && command -v dpkg >/dev/null 2>&1; then '
               + dpkg_erase +
               'for package do if [ "$(dpkg-query -W -f=\'${Status}\' "$package" 2>/dev/null || true)" = "install ok installed" ]; then echo "Package still installed: $package" >&2; exit 24; fi; done; '
               'elif command -v rpm >/dev/null 2>&1; then '
               'for package do rpm -q "$package" >/dev/null 2>&1 || { echo "RPM package not installed: $package" >&2; exit 24; }; done; '
               + rpm_erase +
               'for package do if rpm -q "$package" >/dev/null 2>&1; then echo "RPM uninstall did not remove: $package" >&2; exit 24; fi; done; '
               'elif command -v apk >/dev/null 2>&1; then '
               + apk_erase +
               'for package do if apk info -e "$package" >/dev/null 2>&1; then echo "Package still installed: $package" >&2; exit 24; fi; done; '
               'else echo "No supported package manager for uninstall" >&2; exit 24; fi')
        statements.append('RUN ' + cmd)
    return statements
