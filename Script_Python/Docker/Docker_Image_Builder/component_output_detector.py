





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
    
    content = re.sub(r'\\\n\s*', ' ', content)
    for line in content.splitlines():
        if not line or line[0].isspace() or line.lstrip().startswith('#'):
            continue
        rule = re.match(r'^([^:#=]+?)\s*:(?![=])(.*)$', line)
        if not rule:
            continue
        left = rule.group(1).strip()
        right = rule.group(2).split('#', 1)[0].split(';', 1)[0].strip()
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
    cmake = source / 'CMakeLists.txt'
    if not cmake.is_file():
        return []
    try:
        contents = cmake.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return []
    targets = re.findall(r'\badd_executable\s*\(\s*([A-Za-z0-9_.+-]+)', contents, re.I)
    return [f'build/{target}' for target in dict.fromkeys(targets)]


def detect_compiled_output(source_folder, build_system='', component_name=''):






    source = Path(source_folder)
    if not source.is_dir():
        return OutputDetection(message='Source directory does not exist.')

    outputs, truncated = _existing_outputs(source)
    make_targets, makefile_name = _makefile_target_candidates(source)
    
    known_targets = set(make_targets)
    matched_outputs = [p for p in outputs if p in known_targets]
    if len(matched_outputs) == 1:
        return OutputDetection(matched_outputs[0],
                               f'Found executable declared by {makefile_name}.', True)
    if len(matched_outputs) > 1:
        return OutputDetection(message='Multiple built Make targets found; select the desired output.',
                               ambiguous=True, candidates=tuple(matched_outputs))
    if len(make_targets) == 1:
        path = make_targets[0]
        exists = (source / path).is_file() and _is_elf_or_script(source / path)
        return OutputDetection(path, (
            f'{makefile_name} identifies this build target; executable verified.' if exists
            else f'Suggested from {makefile_name}; confirm it exists after the build.'
        ), exists)
    if len(make_targets) > 1:
        return OutputDetection(message='Multiple Make outputs found; cannot choose safely.',
                               ambiguous=True, candidates=tuple(make_targets))

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
