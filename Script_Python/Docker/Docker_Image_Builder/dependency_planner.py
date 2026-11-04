from __future__ import annotations

import re
from pathlib import Path

from java_runtime_checker import minimum_java_version
from network_policy import package_names, validate_packages


def package_family(value):
    text = str(value or '').lower()
    if any(word in text for word in ('microdnf', 'dnf', 'yum', 'rhel', 'red hat', 'fedora', 'ubi', 'rocky', 'alma', 'centos')):
        return 'rpm'
    if any(word in text for word in ('debian', 'ubuntu', 'apt', 'dpkg')):
        return 'apt'
    if 'alpine' in text or text.strip() == 'apk':
        return 'apk'
    return 'unknown'


def identify_runtime_family(state, inventory=None):
    system = state.get('base_system', {}) or {}
    values = []
    if inventory:
        values += [inventory.get('package_manager'), inventory.get('os')]
    if isinstance(system, dict):
        values += [system.get('package_manager'), system.get('os'), system.get('distribution'), system.get('os_release')]
    for value in values:
        result = package_family(value)
        if result != 'unknown':
            return result
    archive = str(state.get('runtime_base_archive', '') or '')
    if archive and Path(archive).is_file():
        try:
            from docker_archive_libraries import archive_library_inventory
            data = archive_library_inventory(archive)
            for value in (data.get('package_manager'), data.get('os')):
                result = package_family(value)
                if result != 'unknown':
                    return result
        except (OSError, ValueError, KeyError, RuntimeError):
            pass
    return package_family(state.get('base_image', ''))


def runtime_distribution(state):
    system = state.get('base_system', {}) or {}
    values = []
    if isinstance(system, dict):
        values += [system.get('os'), system.get('distribution'), system.get('os_release')]
    archive = str(state.get('runtime_base_archive', '') or '')
    if archive and Path(archive).is_file():
        try:
            from docker_archive_libraries import archive_library_inventory
            values.append(archive_library_inventory(archive).get('os'))
        except (OSError, ValueError, KeyError, RuntimeError):
            pass
    values += [state.get('base_image'), state.get('runtime_tag')]
    return ' '.join(str(value or '') for value in values).lower()


def preferred_java_version(minimum, family, state):
    version = int(minimum)
    distro = runtime_distribution(state)
    rhel_ten = bool(re.search(r'(?:red hat enterprise linux|rhel|ubi|rocky linux|almalinux|alma linux)[^0-9]{0,12}10(?:\D|$)', distro))
    if family == 'rpm' and rhel_ten and version <= 21:
        return 21, 'RHEL/UBI 10 uses OpenJDK 21 as its default Java implementation; repository availability remains unverified'
    return version, 'Minimum Java version inferred from JAR bytecode; repository availability remains unverified'


def java_package_version(name):
    value = str(name or '').lower().strip()
    expressions = (
        r'openjdk-(\d+)-(?:jre|jdk)(?:-headless)?',
        r'java-(\d+)-openjdk(?:-headless|-devel)?',
        r'openjdk(\d+)(?:-jre|-jdk|-jre-headless|-jdk-headless)?',
    )
    for expression in expressions:
        found = re.fullmatch(expression, value)
        if found:
            return int(found.group(1))
    return None


def java_package(version, family):
    version = int(version)
    if family == 'apt':
        return f'openjdk-{version}-jre-headless'
    if family == 'rpm':
        return f'java-{version}-openjdk-headless'
    if family == 'apk':
        return f'openjdk{version}-jre'
    return None


def translate_package(name, family):
    major = java_package_version(name)
    if major is not None and family in ('apt', 'rpm', 'apk'):
        return java_package(major, family)
    return name


def jar_requirements(components):
    output = []
    for component in components:
        if not component.get('enabled', True) or str(component.get('kind', '')).lower() != 'jar/application':
            continue
        path = Path(str(component.get('source', '') or '')).expanduser()
        if not path.is_file():
            output.append({'name': str(component.get('name', '')), 'minimum': None, 'error': 'JAR file not found: ' + str(path)})
            continue
        try:
            output.append({'name': str(component.get('name', '')), 'minimum': minimum_java_version(path), 'error': ''})
        except Exception as exc:
            output.append({'name': str(component.get('name', '')), 'minimum': None, 'error': str(exc)})
    return output


def plan_runtime_dependencies(state, base_java=None, manager=None):
    components = [c for c in state.get('components', []) if isinstance(c, dict) and c.get('enabled', True)]
    family = package_family(manager) if manager else identify_runtime_family(state)
    raw = package_names(components, 'runtime')
    translated = [(name, translate_package(name, family)) for name in raw]
    mapped = validate_packages(value for _, value in translated)
    java = jar_requirements(components)
    requirements = [entry['minimum'] for entry in java if entry['minimum'] is not None]
    minimum = max(requirements, default=None)
    explicit = [(name, java_package_version(name)) for name in raw if java_package_version(name) is not None]
    configured_java = str((state.get('environment_requirements') or {}).get('java_version', '') or '').strip()
    if configured_java and (not configured_java.isdigit() or int(configured_java) < 8 or int(configured_java) > 200):
        raise ValueError('Java runtime major version must be a number such as 8, 11, 17, or 21.')
    requested_java = max([*(version for _, version in explicit), *([int(configured_java)] if configured_java else [])], default=None)
    auto_package = None
    selection_reason = 'Selected by user in Tab 3' if requested_java is not None else ''
    errors = [entry['name'] + ': ' + entry['error'] for entry in java if entry['error']]
    if minimum is not None and requested_java is not None and requested_java < minimum:
        errors.append('Selected Java ' + str(requested_java) + ' is below the detected Java ' + str(minimum) + '+ requirement. No additional package will be selected automatically.')
    if requested_java is not None and configured_java and family in ('apt', 'rpm', 'apk'):
        configured_package = java_package(requested_java, family)
        mapped = validate_packages([*mapped, configured_package])
        selection_reason = 'Explicit Java runtime version configured in Language runtimes / Custom setup'
    if minimum is not None and (base_java is None or base_java < minimum) and (requested_java is None or requested_java < minimum):
        errors.append('Java ' + str(minimum) + '+ required by application bytecode. No compatible Java runtime was selected by the user. Add one manually in Tab 3 if desired.')
    auto_version = java_package_version(auto_package) if auto_package else None
    target = max((version for version in (requested_java, auto_version) if version is not None), default=None)
    install_now = state.get('build_mode') != 'assembly'
    return {'manager': family, 'packages': mapped, 'translations': [(a, b) for a, b in translated if a != b],
            'install_now': install_now,
            'java': java, 'minimum_java': minimum, 'requested_java': requested_java, 'target_java': target,
            'auto_java_package': auto_package, 'base_java': base_java, 'selection_reason': selection_reason, 'notes': errors}


def evaluate_java_requirement(minimum, base_version, plan, verification_error=''):
    if minimum is None:
        return {'status': 'UNRESOLVED', 'path': 'JAR bytecode version could not be determined'}
    target = plan.get('target_java')
    if base_version is not None and base_version >= minimum and (target is None or target <= base_version):
        return {'status': 'FOUND', 'path': f'Java {base_version} verified in the original runtime image'}
    if target is not None and target >= minimum:
        package = java_package(target, plan.get('manager')) or 'a user-selected Java ' + str(target) + ' runtime'
        if plan.get('install_now'):
            path = f'Java {minimum}+ is NOT VERIFIED in the base. User-selected {package} is scheduled for installation; only a successful final-image check can establish compatibility'
        else:
            path = f'Java {minimum}+ is NOT INSTALLED. User-selected {package} has not been installed in this image'
        if verification_error:
            path += '; base JVM check unavailable'
        return {'status': 'MISSING' if base_version is not None and base_version < minimum else 'UNRESOLVED', 'path': path}
    if base_version is not None:
        return {'status': 'MISSING', 'path': f'Base Java {base_version} is too old; Java {minimum}+ is required'}
    return {'status': 'UNRESOLVED', 'path': 'Base JVM not verified. No Java package is selected automatically; choose one in Tab 3 if needed'}
