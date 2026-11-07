import re
import shlex
import subprocess
from pathlib import Path
from source_archive import SourceArchive, is_source_archive


TOOLS = frozenset('ar autoconf automake autoreconf bash bison c++ cargo cc clang clang++ cmake curl flex g++ gcc git go gfortran gmake gradle java javac ld make meson mvn ninja node npm perl pip pip3 pkg-config python python2 python3 R Rscript rustc sh swig tar unzip wget'.split())
PACKAGES = {
    'ar': ('binutils', 'binutils', 'binutils'),
    'autoconf': ('autoconf', 'autoconf', 'autoconf'),
    'automake': ('automake', 'automake', 'automake'),
    'autoreconf': ('autoconf', 'autoconf', 'autoconf'),
    'bash': ('bash', 'bash', 'bash'),
    'bison': ('bison', 'bison', 'bison'),
    'c++': ('g++', 'g++', 'gcc-c++'),
    'cargo': ('cargo', 'cargo', 'cargo'),
    'cc': ('gcc', 'gcc', 'gcc'),
    'clang': ('clang', 'clang', 'clang'),
    'clang++': ('clang', 'clang', 'clang'),
    'cmake': ('cmake', 'cmake', 'cmake'),
    'curl': ('curl', 'curl', 'curl'),
    'flex': ('flex', 'flex', 'flex'),
    'g++': ('g++', 'g++', 'gcc-c++'),
    'gcc': ('gcc', 'gcc', 'gcc'),
    'git': ('git', 'git', 'git'),
    'go': ('golang-go', 'go', 'golang'),
    'gfortran': ('gfortran', 'gfortran', 'gcc-gfortran'),
    'gmake': ('make', 'make', 'make'),
    'gradle': ('gradle', 'gradle', 'gradle'),
    'java': ('default-jre-headless', 'openjdk17-jre', 'java-17-openjdk-headless'),
    'javac': ('default-jdk-headless', 'openjdk17', 'java-17-openjdk-devel'),
    'ld': ('binutils', 'binutils', 'binutils'),
    'make': ('make', 'make', 'make'),
    'meson': ('meson', 'meson', 'meson'),
    'mvn': ('maven', 'maven', 'maven'),
    'ninja': ('ninja-build', 'ninja', 'ninja-build'),
    'node': ('nodejs', 'nodejs', 'nodejs'),
    'npm': ('npm', 'npm', 'npm'),
    'perl': ('perl', 'perl', 'perl'),
    'pip': ('python3-pip', 'py3-pip', 'python3-pip'),
    'pip3': ('python3-pip', 'py3-pip', 'python3-pip'),
    'pkg-config': ('pkg-config', 'pkgconf', 'pkgconf-pkg-config'),
    'python2': ('python2.7', '', 'python2'),
    'python3': ('python3', 'python3', 'python3'),
    'R': ('r-base-core', 'R', 'R'),
    'Rscript': ('r-base-core', 'R', 'R'),
    'rustc': ('rustc', 'rust', 'rust'),
    'sh': ('dash', 'busybox', 'bash'),
    'swig': ('swig', 'swig', 'swig'),
    'tar': ('tar', 'tar', 'tar'),
    'unzip': ('unzip', 'unzip', 'unzip'),
    'wget': ('wget', 'wget', 'wget'),
}
ASSIGNMENT = re.compile(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_.-]*)\s*(?::=|\?=|\+=|=)\s*(.*)$')
VARIABLE = re.compile(r'\$\(([^()]+)\)|\$\{([^{}]+)\}')
RULE = re.compile(r'^([^:#=]+?)\s*:(?![=])(.*)$')


def _tokens(command):
    try:
        return shlex.split(command, comments=True, posix=True)
    except ValueError:
        return command.split()


def _shell_commands(command):
    found = set()
    for segment in re.split(r'\s*(?:&&|\|\||[;|])\s*', command):
        words = _tokens(segment.strip().lstrip('@+-'))
        if not words or words[0] in ('echo', 'printf', 'test', 'export'):
            continue
        while words and (re.fullmatch(r'[A-Za-z_]\w*=.*', words[0]) or words[0] in ('if', 'then', 'else', 'do')):
            words = words[1:]
        if words and words[0] in ('command', 'which') and '-v' in words[:3]:
            continue
        for word in words[:3]:
            name = word.lstrip('@+-').rsplit('/', 1)[-1]
            if name in TOOLS:
                found.add(name)
                if word == words[0]:
                    break
    return found


def _shebang(path, archive=None):
    try:
        if archive:
            line = archive.read_head(path.relative_to(archive.path).as_posix()).splitlines()[0].decode('utf-8', errors='replace').strip()
        else:
            with path.open('rb') as stream:
                line = stream.readline(256).decode('utf-8', errors='replace').strip()
    except (OSError, ValueError, IndexError, KeyError):
        return ''
    if not line.startswith('#!'):
        return ''
    words = line[2:].split()
    if not words:
        return ''
    result = Path(words[0]).name
    if result == 'env' and len(words) > 1:
        result = words[1] if words[1] != '-S' else words[2] if len(words) > 2 else ''
    return result if result in TOOLS else ''


def _make_location(source, build_command):
    work = source
    for segment in re.split(r'&&|\|\||;', build_command):
        words = _tokens(segment.strip())
        if not words:
            continue
        if words[0] == 'cd' and len(words) > 1:
            candidate = (work / words[1]).resolve()
            if candidate == source or source in candidate.parents:
                work = candidate
            continue
        if words[0].rsplit('/', 1)[-1] not in ('make', 'gmake'):
            continue
        target = ''
        pos = 1
        while pos < len(words):
            value = words[pos]
            if value in ('-C', '--directory', '-f', '--file') and pos + 1 < len(words):
                if value in ('-C', '--directory'):
                    candidate = (work / words[pos + 1]).resolve()
                    if candidate == source or source in candidate.parents:
                        work = candidate
                pos += 2
                continue
            if value.startswith('-C') and len(value) > 2:
                candidate = (work / value[2:]).resolve()
                if candidate == source or source in candidate.parents:
                    work = candidate
            elif not value.startswith('-') and '=' not in value and not value.isdigit():
                target = value
            pos += 1
        return work, target
    return None, ''


def _make_rules(path, content=None):
    try:
        lines = (path.read_text(encoding='utf-8', errors='replace') if content is None else content)[:400000].splitlines()
    except (OSError, ValueError):
        return {}, ''
    variables = {'MAKE': 'make'}
    for line in lines:
        match = ASSIGNMENT.match(line)
        if match and not line.startswith('\t'):
            variables[match.group(1)] = match.group(2).split('#', 1)[0].strip()

    def expand(raw):
        value = raw
        for _ in range(8):
            updated = VARIABLE.sub(lambda m: variables.get((m.group(1) or m.group(2)).strip(), m.group(0)), value)
            if updated == value:
                break
            value = updated
        return value

    rules = {}
    current = []
    first = ''
    for lineno, line in enumerate(lines, 1):
        if line.startswith('\t') and current:
            for target in current:
                rules.setdefault(target, {'deps': [], 'recipes': []})['recipes'].append((expand(line.strip()), lineno))
            continue
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = RULE.match(line)
        if not match:
            current = []
            continue
        left = expand(match.group(1).strip())
        right = expand(match.group(2).split('#', 1)[0].split(';', 1)[0].strip())
        current = [item for item in left.split() if '$' not in item and '%' not in item]
        for target in current:
            rules.setdefault(target, {'deps': [], 'recipes': []})['deps'].extend(right.split())
        if not first and current and not current[0].startswith('.'):
            first = current[0]
    return rules, first


def discover_build_requirements(source_folder, build_command):
    source = Path(str(source_folder or '')).resolve()
    archive = SourceArchive(source) if source.is_file() and is_source_archive(source) else None
    detected = {}

    def exists(candidate):
        return archive.has(candidate.relative_to(source).as_posix()) if archive else candidate.is_file()

    def read_text(candidate, limit=30000):
        return (archive.read_text(candidate.relative_to(source).as_posix(), limit) if archive else
                candidate.read_text(encoding='utf-8', errors='replace')[:limit])

    def add(command, evidence):
        if command in TOOLS:
            detected.setdefault(command, set()).add(str(evidence))

    for command in _shell_commands(build_command):
        add(command, 'Build command')
    for token in _tokens(build_command):
        if token.startswith('./'):
            candidate = (source / token).resolve()
            if source in candidate.parents:
                add(_shebang(candidate, archive), 'Script: ' + token)
    scanned_makefiles = set()
    visited_scripts = set()

    def inspect_script(candidate):
        if candidate != source and source not in candidate.parents:
            return
        if candidate in visited_scripts or not exists(candidate):
            return
        visited_scripts.add(candidate)
        add(_shebang(candidate, archive), candidate.relative_to(source).as_posix())
        if candidate.suffix.lower() not in ('.sh', '.bash', '.pl', '.py', '.r'):
            return
        try:
            content = read_text(candidate)
        except (OSError, ValueError):
            return
        for line in content.splitlines():
            for command in _shell_commands(line):
                if candidate.suffix.lower() in ('.sh', '.bash'):
                    add(command, candidate.relative_to(source).as_posix())

    def inspect_recipe_scripts(work, recipe):
        for token in _tokens(recipe.lstrip('@+-')):
            if token.startswith(('scripts/', './', '../', 'src/')):
                candidate = (work / token).resolve()
                inspect_script(candidate)

    def scan_make(work, target, depth=0):
        if depth > 6:
            return
        makefile = next((work / name for name in ('GNUmakefile', 'Makefile', 'makefile')
                         if exists(work / name)), None)
        if makefile is None:
            return
        key = (makefile.resolve(), target)
        if key in scanned_makefiles:
            return
        scanned_makefiles.add(key)
        try:
            rules, first = _make_rules(makefile, read_text(makefile, 400000))
        except (OSError, ValueError):
            return
        pending = [target or first]
        visited = set()
        inspected = 0
        while pending and inspected < 250:
            name = pending.pop()
            if name in visited or name not in rules:
                continue
            visited.add(name)
            for recipe, lineno in rules[name]['recipes']:
                inspected += 1
                for command in _shell_commands(recipe):
                    add(command, makefile.relative_to(source).as_posix() + ':' + str(lineno))
                inspect_recipe_scripts(work, recipe)
                child, child_target = _make_location(work, recipe.lstrip('@+-'))
                if child is not None and (child == source or source in child.parents):
                    scan_make(child, child_target, depth + 1)
            for dependency in rules[name]['deps']:
                if dependency in rules and dependency not in visited:
                    pending.append(dependency)

    work, target = _make_location(source, build_command)
    if work is not None:
        scan_make(work, target)
    for token in _tokens(build_command):
        if token.startswith(('scripts/', './', 'src/')):
            inspect_script((source / token).resolve())
    commands = set(detected)
    if 'mvn' in commands or 'gradle' in commands:
        add('java', 'Java build system runtime')
        add('javac', 'Java build system compiler')
    if 'javac' in commands:
        add('java', 'Java compiler runtime')
    lowered = build_command.lower()
    if './mvnw' in lowered or './gradlew' in lowered:
        add('java', 'Java build wrapper runtime')
        add('javac', 'Java build wrapper compiler')
    if 'cargo' in commands:
        add('rustc', 'Rust compiler used by Cargo')
    return [{'command': name, 'evidence': sorted(reasons)} for name, reasons in sorted(detected.items())]


def valid_executable_path(value):
    value = str(value or '').strip()
    return (bool(value) and value.startswith('/') and len(value) <= 1000 and
            not any(part == '..' for part in value.split('/')) and
            not any(char in value for char in ('\n', '\r', '\x00', '|', '\\')))


def inspect_builder_commands(image, requirements, runner=None, timeout=75, overrides=None):
    commands = sorted({item['command'] if isinstance(item, dict) else str(item) for item in requirements})
    if not all(command in TOOLS for command in commands):
        raise ValueError('Unexpected command in build requirements.')
    paths = dict(overrides or {})
    if any(command not in commands or not valid_executable_path(path) for command, path in paths.items()):
        raise ValueError('Each custom builder executable must be an absolute Linux path.')
    script = '''if [ -r /etc/os-release ]; then . /etc/os-release; fi
printf 'DISTRO|%s|%s\n' "$ID" "$VERSION_ID"
if command -v apt-get >/dev/null 2>&1; then manager=apt; elif command -v apk >/dev/null 2>&1; then manager=apk; elif command -v rpm >/dev/null 2>&1; then manager=rpm; else manager=unknown; fi
printf 'MANAGER|%s\n' "$manager"
for item do
  tool=${item%%=*}
  custom=${item#*=}
  if [ -n "$custom" ]; then
    if [ -f "$custom" ] && [ -x "$custom" ]; then location=$custom; else location=''; fi
  else
    location=$(command -v "$tool" 2>/dev/null || true)
  fi
  if [ -n "$location" ]; then
    version=''
    case "$tool" in
      gcc|g++|c++|make|cmake|python|python2|python3|git|mvn|gradle|cargo|go|R|Rscript|ninja|meson|node|npm|bison|flex|autoconf|automake|swig|gfortran)
        if command -v timeout >/dev/null 2>&1; then version=$(timeout 3 "$location" --version 2>&1 | head -n 1 || true); fi ;;
      perl)
        if command -v timeout >/dev/null 2>&1; then version=$(timeout 3 "$location" -e 'print $^V' 2>&1 || true); fi ;;
      java|javac)
        if command -v timeout >/dev/null 2>&1; then version=$(timeout 3 "$location" -version 2>&1 | head -n 1 || true); fi ;;
    esac
    version=$(printf '%s' "$version" | tr '\r\n|' '   ' | cut -c 1-160)
    printf 'TOOL|%s|1|%s|%s\n' "$tool" "$location" "$version"
  else
    printf 'TOOL|%s|0||\n' "$tool"
  fi
done'''
    args = ['docker', 'run', '--rm', '--pull=never', '--network=none', '--entrypoint', '/bin/sh',
            str(image), '-c', script, 'builder-tool-inspection', *(command + '=' + paths.get(command, '') for command in commands)]
    runner = runner or subprocess.run
    try:
        result = runner(args, capture_output=True, text=True, errors='replace',
                        stdin=subprocess.DEVNULL, timeout=timeout,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('Cannot inspect commands in selected builder: ' + str(exc)) from exc
    if result.returncode:
        raise RuntimeError('Builder command inspection failed: ' + (result.stderr or result.stdout or '')[-1200:])
    found = {}
    missing = []
    seen = set()
    manager = 'unknown'
    distro = 'unknown'
    version = ''
    for line in result.stdout.splitlines():
        fields = line.split('|', 4)
        if fields[0] == 'DISTRO' and len(fields) >= 3:
            distro, version = fields[1:3]
        elif fields[0] == 'MANAGER' and len(fields) >= 2:
            manager = fields[1]
        elif fields[0] == 'TOOL' and len(fields) >= 3 and fields[1] in commands:
            name = fields[1]
            seen.add(name)
            if fields[2] == '1':
                found[name] = {'path': fields[3] if len(fields) > 3 else '',
                               'version': fields[4] if len(fields) > 4 else ''}
            else:
                missing.append(name)
    if seen != set(commands):
        raise RuntimeError('Builder returned an incomplete command inventory.')
    return {'found': found, 'missing': sorted(set(missing)), 'manager': manager,
            'distro': distro, 'distro_version': version}


def suggested_package(command, report):
    manager = report.get('manager', '')
    distro = report.get('distro', '')
    version = report.get('distro_version', '')
    if command == 'python':
        if manager != 'apt':
            return ''
        try:
            major = int(version.split('.', 1)[0])
        except (ValueError, TypeError):
            return ''
        if (distro == 'debian' and major <= 9) or (distro == 'ubuntu' and major <= 18):
            return 'python'
        return 'python-is-python3'
    hint = PACKAGES.get(command)
    return hint[{'apt': 0, 'apk': 1, 'rpm': 2}[manager]] if hint and manager in ('apt', 'apk', 'rpm') else ''


def builder_command_preflight(commands, allow_missing=False, overrides=None):
    parts = []
    paths = dict(overrides or {})
    if any(command not in TOOLS or not valid_executable_path(path) for command, path in paths.items()):
        raise ValueError('Invalid custom build-tool executable path.')
    if paths:
        parts.append('mkdir -p /tmp/docker-builder-tool-shims')
        for command, path in sorted(paths.items()):
            quoted_path = shlex.quote(path)
            quoted_name = shlex.quote('/tmp/docker-builder-tool-shims/' + command)
            parts.append('if [ -f ' + quoted_path + ' ] && [ -x ' + quoted_path + ' ]; then '
                         'ln -sf ' + quoted_path + ' ' + quoted_name + '; '
                         'else echo "INVALID-BUILD-TOOL-PATH: ' + command + '"; exit 46; fi')
        parts.append('export PATH=/tmp/docker-builder-tool-shims:"$PATH"')
    for command in sorted(set(commands)):
        if command not in TOOLS:
            continue
        quoted = shlex.quote(command)
        action = 'true' if allow_missing else 'exit 45'
        parts.append('if ! command -v ' + quoted + ' >/dev/null 2>&1; then '
                     'echo "MISSING-BUILD-TOOL: ' + command + '"; ' + action + '; '
                     'else echo "BUILD-TOOL-VERIFIED: ' + command + ' at $(command -v ' + quoted + ')"; '
                     'if command -v timeout >/dev/null 2>&1; then '
                     'case ' + quoted + ' in '
                     'python|python2|python3|gcc|g++|c++|make|cmake|perl|java|javac|mvn|gradle|cargo|go|R|Rscript) '
                     'case ' + quoted + ' in java|javac) _tool_arg=-version;; perl) _tool_arg=-v;; *) _tool_arg=--version;; esac; '
                     'timeout 3 ' + quoted + ' "$_tool_arg" 2>&1 | head -n 1 || true;; '
                     'esac; fi; fi')
    return '; '.join(parts)
