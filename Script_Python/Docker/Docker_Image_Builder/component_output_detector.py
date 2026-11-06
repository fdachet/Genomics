





from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re


SKIP_DIRS = {
    '.git', '.hg', '.svn', '.venv', 'venv', '__pycache__', '.tox',
    'node_modules', '.idea', '.vscode', '.gradle', '.m2',
}
IGNORE_TARGETS = {
    'all', 'default', 'clean', 'distclean', 'mostlyclean', 'install', 'uninstall',
    'check', 'test', 'tests', 'help', 'docs', 'doc', 'build', 'release', 'debug',
    'prepare', 'configure', 'setup', 'lint', 'format', 'package', 'run', 'phony',
}
NON_OUTPUT_SUFFIXES = {
    '.c', '.cc', '.cpp', '.h', '.hpp', '.rs', '.go', '.java', '.py',
    '.sh', '.o', '.a', '.d', '.lo', '.la', '.in', '.txt', '.md', '.json',
    '.yaml', '.yml', '.toml', '.xml', '.html', '.css', '.js', '.ts',
}


@dataclass(frozen=True)
class OutputDetection:
    path: str = ''
    message: str = ''
    verified: bool = False
    ambiguous: bool = False
    candidates: tuple = ()


def normalized_relative(value):

    value = str(value or '').strip().replace('\\', '/')
    p = PurePosixPath(value)
    if (not value or p.is_absolute() or ':' in value or
            any(char in value for char in '$%*?[]{}') or
            any(ord(char) < 32 for char in value) or
            any(part in ('..', '.') for part in value.split('/'))):
        return ''
    if not p.parts:
        return ''
    return p.as_posix()


def _is_elf_or_script(path):
    try:
        with path.open('rb') as stream:
            header = stream.read(64)
    except (OSError, ValueError):
        return False
    if header.startswith(b'\x7fELF'):
        
        endian = 'little' if header[5:6] == b'\x01' else 'big'
        if len(header) < 18 or header[5:6] not in (b'\x01', b'\x02'):
            return False
        return int.from_bytes(header[16:18], endian) in (2, 3)
    return header.startswith(b'#!')


def _existing_outputs(source):

    candidates = []
    seen = 0
    try:
        tree = source.rglob('*')
        for path in tree:
            if any(part in SKIP_DIRS for part in path.relative_to(source).parts):
                continue
            seen += 1
            if seen > 5000:
                return [], True
            if not path.is_file() or len(path.relative_to(source).parts) > 5:
                continue
            if path.suffix in ('.so', '.dll', '.dylib', '.o', '.a', '.class', '.exe'):
                continue
            if _is_elf_or_script(path):
                candidates.append(path.relative_to(source).as_posix())
    except (OSError, ValueError):
        return [], True
    return sorted(set(candidates)), False


def _makefile_target_candidates(source):
    file = next((source / name for name in ('GNUmakefile', 'Makefile', 'makefile')
                 if (source / name).is_file()), None)
    if file is None:
        return [], ''
    try:
        content = file.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return [], ''
    rules = {}
    phony = set()
    first_target = None
    variables = {}
    content = re.sub(r'\\\n\s*', ' ', content)
    lines = content.splitlines()
    for line in lines:
        if not line or line[0].isspace() or line.lstrip().startswith('#'):
            continue
        assignment = re.match(r'^([A-Za-z_][A-Za-z0-9_.-]*)\s*(:=|\?=|\+=|=)\s*(.*)$', line)
        if assignment is None:
            continue
        key, operation, raw_value = assignment.groups()
        value = raw_value.split('#', 1)[0].strip()
        if operation == '?=' and key in variables:
            continue
        if operation == '+=':
            variables[key] = (variables.get(key, '') + ' ' + value).strip()
        else:
            variables[key] = value

    variable_pattern = re.compile(r'\$\(([^()]+)\)|\$\{([^{}]+)\}')

    def expand(value):
        result = value
        for _ in range(12):
            expanded = variable_pattern.sub(lambda match: variables.get(
                (match.group(1) or match.group(2)).strip(), match.group(0)), result)
            if expanded == result:
                break
            result = expanded
        return result

    for line in lines:
        if not line or line[0].isspace() or line.lstrip().startswith('#'):
            continue
        rule = re.match(r'^([^:#=]+?)\s*:(?![=])(.*)$', line)
        if not rule:
            continue
        left = expand(rule.group(1).strip())
        right = expand(rule.group(2).split('#', 1)[0].split(';', 1)[0].strip())
        if left == '.PHONY':
            phony.update(right.split())
            continue
        if '%' in left or '$' in left:
            continue
        targets = left.split()
        for target in targets:
            if not normalized_relative(target):
                continue
            if target not in rules:
                rules[target] = right.split()
            if first_target is None and not target.startswith('.'):
                first_target = target

    def valid_target(target):
        path = normalized_relative(target)
        if not path or target.lower() in IGNORE_TARGETS or target in phony:
            return False
        if Path(path).suffix.lower() in NON_OUTPUT_SUFFIXES:
            return False
        if target.startswith('.') or '/' in target and target.endswith('/'):
            return False
        return True

    candidates = []
    if 'all' in rules:
        
        candidates = [x for x in rules['all'] if valid_target(x)]
    if not candidates:
        candidates = [x for x in rules if valid_target(x)]
    if not candidates and first_target and valid_target(first_target):
        candidates = [first_target]
    return list(dict.fromkeys(candidates)), file.name


def _cmake_candidates(source):
    for relative in ('', 'source', 'src'):
        cmake = source / relative / 'CMakeLists.txt' if relative else source / 'CMakeLists.txt'
        if not cmake.is_file():
            continue
        try:
            contents = cmake.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        targets = re.findall(r'\badd_executable\s*\(\s*([A-Za-z0-9_.+-]+)', contents, re.I)
        return [f'build/{target}' for target in dict.fromkeys(targets)]
    return []


def build_target_names(component_name, source_folder):
    names = []
    for value in (component_name, Path(source_folder).name):
        name = str(value or '').strip()
        if not name:
            continue
        names.append(name.casefold())
        without_version = re.split(r'(?=[\s_-]v?\d)', name, maxsplit=1)[0].strip(' _-')
        if without_version:
            names.append(without_version.casefold())
    return set(names)


def detect_compiled_output(source_folder, build_system='', component_name=''):






    source = Path(source_folder)
    if not source.is_dir():
        return OutputDetection(message='Source directory does not exist.')

    outputs, truncated = _existing_outputs(source)
    preferred_names = build_target_names(component_name, source)
    for relative in ('', 'source', 'src'):
        work = source / relative if relative else source
        if not work.is_dir():
            continue
        make_targets, makefile_name = _makefile_target_candidates(work)
        if not make_targets:
            continue
        candidates = [f'{relative}/{target}' if relative else target for target in make_targets]
        named = [target for target in candidates if Path(target).name.casefold() in preferred_names]
        matches = [target for target in candidates if target in outputs]
        selected = named if named else matches if matches else candidates
        if len(selected) == 1:
            path = selected[0]
            exists = (source / path).is_file() and _is_elf_or_script(source / path)
            return OutputDetection(path, (
                f'{makefile_name} identifies this build target; executable verified.' if exists
                else f'Suggested from {relative + "/" if relative else ""}{makefile_name}; confirm it exists after the build.'
            ), exists)
        return OutputDetection(message='Multiple Make outputs found; select the desired executable.',
                               ambiguous=True, candidates=tuple(selected))

    cmake = _cmake_candidates(source)
    if len(cmake) == 1:
        path = cmake[0]
        exists = (source / path).is_file() and _is_elf_or_script(source / path)
        return OutputDetection(path,
                               'CMake declares one executable; path is a conventional suggestion.'
                               if not exists else 'Built CMake executable found.', exists)
    if len(cmake) > 1:
        return OutputDetection(message='CMake declares multiple executables; choose one.',
                               ambiguous=True, candidates=tuple(cmake))
    if len(outputs) == 1:
        return OutputDetection(outputs[0], 'Found one ELF executable or shebang script in source tree.', True)
    if len(outputs) > 1:
        return OutputDetection(message='Several executable artifacts found; choose one.',
                               ambiguous=True, candidates=tuple(outputs))
    if truncated:
        return OutputDetection(message='Source tree too large to scan safely; choose the output manually.')
    return OutputDetection(message='No unambiguous output found. Build the source and detect again.')
