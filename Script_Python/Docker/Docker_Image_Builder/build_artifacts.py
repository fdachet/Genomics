import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from component_output_detector import detect_compiled_output, normalized_relative
from project_state import effective_builder_image
from source_archive import SourceArchive, is_source_archive

SKIP_DIRS = {'.git', '.hg', '.svn', '__pycache__', '.venv', 'venv', '.docker_component_builder', '_compiled_artifacts'}


def safe_name(value):
    stem = re.sub(r'[^A-Za-z0-9_.-]+', '_', str(value or 'component')).strip('._') or 'component'
    return stem[:75] + '_' + hashlib.sha256(str(value).encode('utf-8')).hexdigest()[:10]


def source_path(component, project_dir=''):
    value = str(component.get('source', '') or '').strip()
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute() and project_dir:
        path = Path(project_dir).expanduser() / path
    return path.resolve()


def root_path(state):
    base = str(state.get('project_dir', '') or '').strip()
    if not base:
        raise ValueError('Select a project directory in Tab 1.')
    return Path(base).expanduser().resolve() / '_compiled_artifacts'


def artifact_dir(state, name):
    return root_path(state) / safe_name(name)


def fingerprint(component, builder, project_dir=''):
    source = source_path(component, project_dir)
    if not source or not (source.is_dir() or source.is_file() and is_source_archive(source)):
        raise ValueError('Source folder or archive is missing: ' + str(source))
    output_rel = normalized_relative(component.get('output_rel', ''))
    if not output_rel:
        raise ValueError('Compiled output must be identified in Tab 4.')
    digest = hashlib.sha256()
    settings = {key: component.get(key, '') for key in ('name', 'source', 'build_system', 'build_command', 'build_deps', 'output_rel')}
    settings['builder'] = builder
    digest.update(json.dumps(settings, sort_keys=True).encode('utf-8'))
    if source.is_file():
        with source.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        return digest.hexdigest()
    count = 0
    for file in sorted(source.rglob('*')):
        relative = file.relative_to(source)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if relative.as_posix() == output_rel:
            continue
        if file.is_symlink():
            raise ValueError(f'Source folder contains a symlink, not supported for a reproducible build: {file}')
        if not file.is_file():
            continue
        count += 1
        if count > 60000:
            raise ValueError('Source tree too large for safe fingerprinting.')
        digest.update(relative.as_posix().encode('utf-8'))
        with file.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
    return digest.hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_record(state, component, validate=True):
    name = str(component.get('name', '') or '')
    record = (state.get('compiled_artifacts', {}) or {}).get(name)
    if not isinstance(record, dict):
        return None, 'Not compiled yet. Use Tab 4.'
    path = Path(str(record.get('artifact', '') or ''))
    try:
        resolved = path.resolve()
        folder = artifact_dir(state, name).resolve()
        if folder not in resolved.parents:
            return None, 'Recorded artifact is outside the managed compilation folder.'
        if not path.is_file():
            return None, 'Compiled artifact file is missing. Recompile in Tab 4.'
        if validate:
            builder = effective_builder_image(state)
            if record.get('signature') != fingerprint(component, builder, str(state.get('project_dir', '') or '')):
                return None, 'Source or build settings changed. Recompile in Tab 4.'
            if sha256_file(path) != record.get('sha256'):
                return None, 'Compiled artifact checksum differs. Recompile in Tab 4.'
    except (OSError, ValueError) as exc:
        return None, str(exc)
    return record, 'Ready'


def prepare_workspace(state, component):
    root = root_path(state)
    source = source_path(component, str(state.get('project_dir', '') or ''))
    if not source or not (source.is_dir() or source.is_file() and is_source_archive(source)):
        raise ValueError('Source directory or ZIP/TAR archive missing. Configure in Tab 3.')
    destination = artifact_dir(state, component.get('name', ''))
    if destination == source or source in destination.parents or destination in source.parents:
        raise ValueError('Source and compilation staging directories must not contain one another.')
    marker = destination / '.managed_by_docker_component_builder'
    if destination.exists():
        if not marker.is_file() or marker.read_text(encoding='utf-8').strip() != 'compiled-artifacts-v1':
            raise ValueError('Refusing to replace an unrecognized compilation folder: ' + str(destination))
        for child in ('workspace', 'files'):
            target = destination / child
            if target.exists():
                if target.is_symlink():
                    target.unlink()
                elif target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
    destination.mkdir(parents=True, exist_ok=True)
    marker.write_text('compiled-artifacts-v1', encoding='utf-8')
    work = destination / 'workspace'
    output_rel = normalized_relative(component.get('output_rel', ''))
    def ignore(directory, names):
        current = Path(directory)
        result = set(name for name in names if name in SKIP_DIRS)
        if current.resolve() == source and output_rel and '/' not in output_rel:
            result.add(output_rel)
        return result
    if source.is_file():
        work.mkdir(parents=True, exist_ok=True)
        SourceArchive(source).write_normalized_tar(work / '.source.tar')
    else:
        shutil.copytree(source, work, ignore=ignore, symlinks=False)
    if output_rel:
        old = work.joinpath(*output_rel.split('/'))
        if old.is_file():
            old.unlink()
    return work


def register_output(state, component, work):
    output = normalized_relative(component.get('output_rel', ''))
    if not output:
        detected = detect_compiled_output(str(work), component.get('build_system', ''), component.get('name', ''))
        output = normalized_relative(detected.path)
        if not output:
            raise ValueError('Could not determine a unique output: ' + detected.message)
        component['output_rel'] = output
    source_file = (work.joinpath(*output.split('/'))).resolve()
    if work.resolve() not in source_file.parents or not source_file.is_file():
        raise ValueError('Compiled output is missing or unsafe: ' + output)
    header = source_file.open('rb').read(4)
    if header != b'\x7fELF' and not header.startswith(b'#!'):
        raise ValueError('Compiled output is not a Linux ELF executable or script: ' + output)
    target = artifact_dir(state, component.get('name', '')) / 'files' / Path(*output.split('/'))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, target)
    if not (target.stat().st_mode & 0o111):
        target.chmod(target.stat().st_mode | 0o755)
    builder = effective_builder_image(state)
    record = {
        'artifact': str(target.resolve()),
        'source': str(source_path(component, str(state.get('project_dir', '') or ''))),
        'output_rel': output,
        'sha256': sha256_file(target),
        'signature': fingerprint(component, builder, str(state.get('project_dir', '') or '')),
        'builder_image': builder,
        'compiled_at': datetime.now(timezone.utc).isoformat(),
    }
    records = state.setdefault('compiled_artifacts', {})
    records[component.get('name', '')] = record
    return record
