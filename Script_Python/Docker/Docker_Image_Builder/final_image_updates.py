from pathlib import Path

from local_package_catalog import package_archive_type, package_identity
from network_policy import validate_packages


def _consolidate_online_requests(entries):
    consolidated = []
    for original in entries:
        if not isinstance(original, dict):
            raise ValueError('A saved online installation request is invalid. Clear the queued online installs in Tab 3.')
        current = dict(original)
        current['packages'] = validate_packages(current.get('packages') or [])
        current['verify_commands'] = sorted(set(current.get('verify_commands') or []))
        current_names = {name.casefold() for name in current['packages']}
        retained = []
        for previous in consolidated:
            previous_names = {name.casefold() for name in previous['packages']}
            overlap = current_names & previous_names if current.get('base_image') == previous.get('base_image') else set()
            if overlap:
                previous_custom = str(previous.get('custom_command') or '').strip()
                current_custom = str(current.get('custom_command') or '').strip()
                remaining = [name for name in previous['packages'] if name.casefold() not in overlap]
                if remaining and previous_custom and previous_custom != current_custom:
                    raise ValueError('Conflicting custom installation commands for ' + ', '.join(sorted(overlap)) + '. Clear queued online installs in Tab 3 and add the intended request once.')
                if remaining:
                    retained.append(dict(previous, packages=remaining))
            elif previous != current:
                retained.append(previous)
        retained.append(current)
        consolidated = retained
    return consolidated


def pending_online_requests(state, base=None):
    saved = list(state.get('final_online_package_requests') or [])
    entries = _consolidate_online_requests(saved)
    selected = str(base if base is not None else state.get('base_image') or '').strip()
    for entry in entries:
        if entry.get('base_image') != selected:
            raise ValueError('The runtime image changed after online packages were selected. Clear the pending final-image package requests in Tab 3 before building against a different runtime.')
    if entries != saved:
        state['final_online_package_requests'] = entries
    return entries


def stage_online_request(state, base, packages, info, use_archive=False, allow_unverified=False,
                         custom_command='', verify_commands=()):
    selected = str(state.get('base_image') or '').strip()
    if not selected or selected != str(base or '').strip():
        raise ValueError('The selected runtime changed. Select its packages again.')
    entries = pending_online_requests(state, selected)
    record = {
        'base_image': selected,
        'packages': validate_packages(packages),
        'info': dict(info),
        'use_archive': bool(use_archive),
        'allow_unverified': bool(allow_unverified),
        'custom_command': str(custom_command or '').strip(),
        'verify_commands': sorted(set(verify_commands)),
    }
    entries.append(record)
    state['final_online_package_requests'] = _consolidate_online_requests(entries)
    return record


def stage_local_packages(state, files):
    existing = list(state.get('components') or [])
    entries = []
    for filename in files:
        path = Path(filename).expanduser().resolve()
        if not path.is_file() or not package_archive_type(path):
            raise ValueError('Select a valid .deb, .rpm, or .apk package archive: ' + str(path))
        name, version = package_identity(path)
        if not name:
            raise ValueError('Could not determine the package name: ' + str(path))
        entries.append((name, version, str(path)))
    updated = 0
    for name, version, path in entries:
        matching = next((item for item in existing if isinstance(item, dict) and
                         str(item.get('kind') or '').lower() == 'os package' and
                         str(item.get('name') or '').lower() == name.lower()), None)
        if matching is None:
            matching = {'enabled': True, 'name': name, 'version': version, 'kind': 'OS Package',
                        'source': path, 'destination': '', 'local_package_files': [path]}
            existing.append(matching)
            updated += 1
        else:
            paths = list(matching.get('local_package_files') or [])
            if path not in paths:
                paths.append(path)
                matching['local_package_files'] = paths
                updated += 1
            matching['enabled'] = True
            if not matching.get('source'):
                matching['source'] = path
    if entries:
        state['components'] = existing
        known = list(state.get('final_local_package_paths') or [])
        for _, _, path in entries:
            if path not in known:
                known.append(path)
        state['final_local_package_paths'] = known
    return updated


def build_full_image_now(app):
    tab = getattr(app, 'build_tab', None)
    if tab is None:
        raise ValueError('The final-image build tab is not available.')
    if tab._busy:
        raise ValueError('The full Docker image is already being built. Wait for that operation to finish.')
    app.notebook.select(tab)
    tab.refresh_from_project_state()
    app.after(150, tab.build)
