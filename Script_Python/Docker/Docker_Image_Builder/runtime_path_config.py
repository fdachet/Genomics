import json
import posixpath
import subprocess
import tarfile
from pathlib import Path


def normalize_directory(value):
    raw = str(value or '').strip()
    if not raw.startswith('/') or ':' in raw or any(ord(char) < 32 for char in raw) or any(char in raw for char in '$\\\"\'`'):
        raise ValueError('Enter an absolute Linux directory without quotes, variables or colons.')
    if any(part in ('.', '..') for part in raw.split('/')):
        raise ValueError('Directory cannot contain . or .. segments.')
    value = posixpath.normpath(raw)
    if value == '/':
        raise ValueError('The filesystem root is not an executable directory.')
    return value


def normalize_directories(items):
    result = []
    for item in items:
        value = normalize_directory(item)
        if value not in result:
            result.append(value)
    return result


def split_path(value):
    return normalize_directories([entry for entry in str(value or '').split(':') if entry.strip()])


def _image_config_from_tar(path, tag=''):
    with tarfile.open(path, 'r:*') as archive:
        try:
            manifest_member = archive.getmember('manifest.json')
            stream = archive.extractfile(manifest_member)
            manifest = json.load(stream) if stream else []
        except KeyError:
            return None
        if not isinstance(manifest, list) or not manifest:
            return None
        selected = None
        for record in manifest:
            if not isinstance(record, dict):
                continue
            tags = record.get('RepoTags') or []
            if tag and tag in tags:
                selected = record
                break
            if selected is None:
                selected = record
        if not selected:
            return None
        name = str(selected.get('Config') or '').strip()
        if not name or '/' in name.strip('/') and '..' in name.split('/'):
            return None
        try:
            member = archive.getmember(name)
            if not member.isfile() or member.size > 32 * 1024 * 1024:
                return None
            stream = archive.extractfile(member)
            config = json.load(stream) if stream else None
        except (KeyError, ValueError, TypeError, OSError):
            return None
        return config if isinstance(config, dict) else None


def _path_in_configuration(config):
    for key in ('config', 'Config', 'container_config', 'ContainerConfig'):
        settings = config.get(key)
        if not isinstance(settings, dict):
            continue
        env = settings.get('Env') or settings.get('env') or []
        if isinstance(env, list):
            for item in reversed(env):
                if isinstance(item, str) and item.startswith('PATH='):
                    return item[5:]
    return None


def read_runtime_path(state):
    tag = str(state.get('base_image') or '').strip()
    archive = str(state.get('runtime_base_archive') or '').strip()
    if archive and Path(archive).is_file():
        try:
            config = _image_config_from_tar(archive, tag)
            if config:
                value = _path_in_configuration(config)
                if value is not None:
                    return value, 'TAR'
        except (OSError, tarfile.TarError, ValueError):
            pass
    if tag:
        try:
            result = subprocess.run(['docker', 'image', 'inspect', tag, '--format', '{{json .Config.Env}}'],
                                    capture_output=True, text=True, timeout=25,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode == 0:
                env = json.loads(result.stdout.strip())
                if isinstance(env, list):
                    for item in reversed(env):
                        if isinstance(item, str) and item.startswith('PATH='):
                            return item[5:], 'Docker'
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
            pass
    return None, ''


def component_path_directories(state):
    paths = []
    for component in state.get('components') or []:
        if not isinstance(component, dict) or not component.get('enabled', True) or not component.get('add_to_path'):
            continue
        target = str(component.get('destination') or '').strip()
        try:
            directory = normalize_directory(target)
        except ValueError:
            continue
        if directory not in paths:
            paths.append(directory)
    return paths


def active_settings(state):
    settings = state.get('runtime_path_settings')
    if not isinstance(settings, dict) or settings.get('runtime_tag') != str(state.get('base_image') or '').strip():
        return None
    if settings.get('runtime_archive') != str(state.get('runtime_base_archive') or '').strip():
        return None
    if not isinstance(settings.get('directories'), list):
        return None
    return settings


def final_path_directories(state):
    settings = active_settings(state)
    automatic = component_path_directories(state)
    if settings is None:
        return None
    directories = normalize_directories(settings['directories'])
    excluded = set(settings.get('excluded_automatic') or [])
    for path in automatic:
        if path not in directories and path not in excluded:
            directories.append(path)
    return directories


def new_path_settings(state, original_path, directories):
    selected = normalize_directories(directories)
    automatically_added = component_path_directories(state)
    return {
        'runtime_tag': str(state.get('base_image') or '').strip(),
        'runtime_archive': str(state.get('runtime_base_archive') or '').strip(),
        'original_path': str(original_path or ''),
        'directories': selected,
        'excluded_automatic': [item for item in automatically_added if item not in selected],
    }


def dockerfile_path_line(directories):
    result = normalize_directories(directories)
    if not result:
        raise ValueError('PATH must contain at least one directory.')
    return 'ENV PATH=' + json.dumps(':'.join(result), ensure_ascii=True)
