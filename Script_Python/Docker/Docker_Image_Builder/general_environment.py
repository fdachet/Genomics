from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

FIELDS = ('java_version', 'python_version', 'python_packages', 'r_version', 'cran_packages', 'bioc_packages', 'perl_version', 'cpan_modules', 'os_packages', 'pre_commands', 'post_commands', 'verify_commands', 'dockerfile_directives')
PERL_CORE = {'strict', 'warnings', 'utf8', 'feature', 'lib', 'vars', 'constant', 'integer', 'bytes', 'base', 'parent', 'Exporter', 'Carp', 'Cwd', 'File::Path', 'File::Basename', 'File::Spec', 'File::Find', 'Getopt::Long', 'Data::Dumper', 'POSIX', 'FindBin', 'IO::File', 'Scalar::Util', 'List::Util', 'Storable', 'Time::HiRes', 'Digest::SHA', 'JSON::PP'}
VERSION_RE = re.compile(r'^(\d+)(?:\.(\d+))?(?:\.(\d+))?$')


def defaults():
    result = {key: '' for key in FIELDS}
    result['auto_detect'] = True
    result['allow_custom_network'] = False
    return result


def normalize(value):
    result = defaults()
    if isinstance(value, dict):
        for key in FIELDS:
            result[key] = str(value.get(key, '') or '').strip()
        result['auto_detect'] = bool(value.get('auto_detect', True))
        result['allow_custom_network'] = bool(value.get('allow_custom_network', False))
    return result


def items(text, spec=False):
    values = []
    seen = set()
    for line in (str(text or '').splitlines() if spec else str(text or '').replace(',', '\n').splitlines()):
        value = line.strip()
        if not value or value.startswith('#'):
            continue
        if spec:
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?(?:\s*(?:===|==|!=|>=|<=|~=|>|<)\s*[A-Za-z0-9.*+_-]+(?:\s*,\s*(?:===|==|!=|>=|<=|~=|>|<)\s*[A-Za-z0-9.*+_-]+)*)?', value):
                raise ValueError('Unsupported package specification: ' + value)
        elif not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+:_/-]*', value):
            raise ValueError('Unsupported package/module name: ' + value)
        key = value.lower()
        if key not in seen:
            values.append(value)
            seen.add(key)
    return values


def version(value, label):
    value = str(value or '').strip()
    if not value:
        return ()
    match = VERSION_RE.fullmatch(value)
    if not match:
        raise ValueError(label + ' must be a version like 3.11, 4.5, 5.36, or 21.')
    return tuple(int(part) for part in match.groups() if part is not None)


def merge(base, detected):
    result = {}
    for key in ('python_packages', 'cran_packages', 'bioc_packages', 'cpan_modules'):
        explicit = items(base.get(key, ''), spec=(key == 'python_packages'))
        suggested = detected.get(key, [])
        result[key] = list(dict.fromkeys([*explicit, *suggested]))
    return result


def file_candidates(components, limit=150, scope='runtime'):
    result = []
    allowed = {'.py', '.r', '.pl', '.pm', '.toml'}
    names = {'requirements.txt', 'description', 'renv.lock', 'cpanfile', 'pyproject.toml', 'setup.cfg'}
    for component in components:
        if not isinstance(component, dict) or not component.get('enabled', True):
            continue
        kind = str(component.get('kind', '')).lower().strip()
        if scope == 'build':
            if kind != 'source':
                continue
        elif scope == 'runtime':
            if kind not in ('script', 'folder', 'other'):
                continue
        else:
            raise ValueError('Unknown dependency detection scope: ' + str(scope))
        raw = str(component.get('source', '') or '')
        root = Path(raw)
        if not root.exists():
            continue
        files = [root] if root.is_file() else []
        if root.is_dir():
            try:
                files.extend(path for path in root.rglob('*') if path.is_file() and not path.is_symlink() and len(path.relative_to(root).parts) <= 5 and not any(part in ('.git', '.venv', 'venv', '__pycache__', 'node_modules', '.tox') for part in path.relative_to(root).parts))
            except (OSError, ValueError):
                pass
        for path in files:
            if len(result) >= limit:
                return result
            if scope == 'runtime' and kind in ('folder', 'other') and root.is_dir() and path.name.lower() not in names:
                continue
            if path.suffix.lower() in allowed or path.name.lower() in names:
                try:
                    if path.stat().st_size < 1500000:
                        result.append(path)
                except OSError:
                    continue
    return result


def _read(path):
    return path.read_text(encoding='utf-8-sig', errors='replace')


def detect(components, scope='runtime'):
    found = {key: set() for key in ('python_packages', 'cran_packages', 'bioc_packages', 'cpan_modules', 'unclassified_r_packages')}
    declared = {key: set() for key in found}
    hints = {'python': False, 'r': False, 'perl': False}
    evidence = []
    versions = {'python_version': '', 'r_version': '', 'perl_version': ''}
    standard = getattr(sys, 'stdlib_module_names', set())
    inspected_files = []
    for path in file_candidates(components, scope=scope):
        inspected_files.append(str(path))
        name = path.name.lower()
        suffix = path.suffix.lower()
        try:
            content = _read(path)
            if suffix == '.py':
                hints['python'] = True
                shebang = content.splitlines()[0] if content else ''
                if shebang.startswith('#!'):
                    detected_python = re.search(r'(?:^|[/\s])python(2|3)(?:\.(\d+))?(?:\s|$)', shebang)
                    if detected_python:
                        candidate = detected_python.group(1) + ('.' + detected_python.group(2) if detected_python.group(2) else '')
                        current = versions['python_version']
                        if not current or version(candidate, 'Python version') > version(current, 'Python version'):
                            versions['python_version'] = candidate
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        names = [alias.name.split('.')[0] for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                        names = [node.module.split('.')[0]]
                    else:
                        continue
                    for module in names:
                        if module not in standard and not module.startswith('_') and module != '__future__':
                            found['python_packages'].add(module)
            if name == 'requirements.txt':
                hints['python'] = True
                for line in content.splitlines():
                    value = line.split(' #', 1)[0].strip()
                    if value and not value.startswith(('#', '-', '.', '/', 'git+', 'https:', 'http:')):
                        try:
                            found['python_packages'].update(items(value, spec=True))
                            declared['python_packages'].update(items(value, spec=True))
                        except ValueError:
                            evidence.append(str(path) + ': unsupported requirement ' + value)
            if name == 'pyproject.toml':
                hints['python'] = True
                try:
                    import tomllib
                    obj = tomllib.loads(content)
                    specification = str(obj.get('project', {}).get('requires-python', '') or '')
                    bound = re.search(r'(?:>=|==)\s*(\d+\.\d+(?:\.\d+)?)', specification)
                    if bound:
                        versions['python_version'] = bound.group(1)
                    for value in (obj.get('project', {}).get('dependencies', []) or []):
                        try:
                            found['python_packages'].update(items(value, spec=True))
                            declared['python_packages'].update(items(value, spec=True))
                        except ValueError:
                            evidence.append('Unsupported pyproject dependency: ' + str(value))
                except (ImportError, ValueError) as exc:
                    evidence.append(str(path) + ': ' + str(exc))
            if suffix == '.r':
                hints['r'] = True
                for pkg in re.findall(r'\b(?:library|require|requireNamespace)\s*\(\s*["\']?([A-Za-z][A-Za-z0-9.]*)', content):
                    found['unclassified_r_packages'].add(pkg)
                for pkg in re.findall(r'\b([A-Za-z][A-Za-z0-9.]*):::{0,1}', content):
                    found['unclassified_r_packages'].add(pkg)
            if name == 'description':
                hints['r'] = True
                bound = re.search(r'(?ms)^Depends:\s*.*?R\s*\(\s*>=\s*(\d+\.\d+(?:\.\d+)?)', content)
                if bound:
                    versions['r_version'] = bound.group(1)
                for section in re.findall(r'(?ms)^(?:Depends|Imports|LinkingTo):\s*(.*?)(?=^[A-Za-z][A-Za-z0-9.]*:|\Z)', content):
                    for entry in re.split(r'\s*,\s*', re.sub(r'\s*\n\s*', ' ', section)):
                        pkg = re.match(r'([A-Za-z][A-Za-z0-9.]*)', entry.strip())
                        if pkg and pkg.group(1) != 'R':
                            value = pkg.group(1)
                            found['unclassified_r_packages'].add(value)
                            declared['unclassified_r_packages'].add(value)
            if name == 'renv.lock':
                hints['r'] = True
                obj = json.loads(content)
                locked_r = str((obj.get('R', {}) or {}).get('Version', '') or '')
                if locked_r and VERSION_RE.fullmatch(locked_r):
                    versions['r_version'] = locked_r
                for pkg, info in (obj.get('Packages', {}) or {}).items():
                    if not isinstance(info, dict):
                        continue
                    repo = str(info.get('Repository', '') or info.get('Source', '')).lower()
                    found['bioc_packages' if 'bioconductor' in repo else 'cran_packages'].add(pkg)
                    declared['bioc_packages' if 'bioconductor' in repo else 'cran_packages'].add(pkg)
            if suffix in ('.pl', '.pm') or name == 'cpanfile':
                hints['perl'] = True
                perl_marker = re.search(r'\buse\s+v(5\.\d+(?:\.\d+)?)', content)
                if perl_marker:
                    versions['perl_version'] = perl_marker.group(1)
                for pkg in re.findall(r'\b(?:use|requires|recommends|require)\b\s*(?:\(\s*)?["\']?([A-Za-z_][A-Za-z_0-9]*(?:::[A-Za-z_][A-Za-z_0-9]*)*)', content):
                    if pkg not in PERL_CORE and pkg not in ('v5', 'if', 'unless'):
                        found['cpan_modules'].add(pkg)
                        if name == 'cpanfile':
                            declared['cpan_modules'].add(pkg)
        except (OSError, ValueError, SyntaxError, UnicodeError) as exc:
            evidence.append(str(path) + ': ' + str(exc))
    return {'packages': {key: sorted(value, key=str.lower) for key, value in found.items()}, 'declared': {key: sorted(value, key=str.lower) for key, value in declared.items()}, 'hints': hints, 'versions': versions, 'issues': evidence, 'files': inspected_files, 'scope': scope}


def package_plan(state, family, java_plan=None):
    config = normalize(state.get('environment_requirements'))
    detected = detect(state.get('components', []), scope='runtime') if config['auto_detect'] else {'packages': {}, 'declared': {}, 'hints': {}, 'versions': {}, 'issues': [], 'files': []}
    combined = merge(config, detected['declared'])
    def required_version(key, label):
        configured = version(config[key], label)
        inferred = version(detected['versions'].get(key, ''), label)
        return max(configured, inferred)
    python_ver = required_version('python_version', 'Python version')
    r_ver = required_version('r_version', 'R version')
    perl_ver = required_version('perl_version', 'Perl version')
    require_python = bool(python_ver or combined['python_packages'] or detected['hints'].get('python'))
    require_r = bool(r_ver or combined['cran_packages'] or combined['bioc_packages'] or detected['hints'].get('r'))
    require_perl = bool(perl_ver or combined['cpan_modules'] or detected['hints'].get('perl'))
    os_packages = items(config['os_packages'])
    unresolved = []
    for required, language in ((require_python, 'Python'), (require_r, 'R'), (require_perl, 'Perl')):
        if required:
            unresolved.append(language + ' runtime required: check the selected image and explicitly choose the appropriate OS package if missing.')
    if require_python and not python_ver:
        unresolved.append('Python interpreter version not declared for deployed runtime scripts. Do not assume Python 3; verify the script shebang and select a compatible version.')
    if detected['declared'].get('unclassified_r_packages'):
        unresolved.append('R package repositories cannot be inferred from names alone: choose CRAN or Bioconductor for ' + ', '.join(detected['declared']['unclassified_r_packages']))
    resolved = list(dict.fromkeys(os_packages))
    language_packages = sum((combined[key] for key in combined), [])
    extra_network = bool(language_packages or (config['allow_custom_network'] and (config['pre_commands'] or config['post_commands'])))
    return {'config': config, 'detected': detected, 'packages': resolved, 'language_packages': combined,
            'python_version': python_ver, 'r_version': r_ver, 'perl_version': perl_ver,
            'python_required': require_python, 'r_required': require_r, 'perl_required': require_perl,
            'requires_network_permission': extra_network, 'issues': detected['issues'], 'unresolved': unresolved}


def custom_directives(text):
    valid = {'RUN', 'ENV', 'ARG', 'LABEL', 'EXPOSE', 'VOLUME', 'WORKDIR', 'USER', 'ENTRYPOINT', 'CMD', 'SHELL', 'STOPSIGNAL', 'HEALTHCHECK', 'COPY', 'ADD'}
    result = []
    for raw in str(text or '').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        keyword = line.split(None, 1)[0].upper()
        if keyword not in valid or len(line.split(None, 1)) != 2 or '\x00' in line:
            raise ValueError('Unsupported additional Dockerfile directive: ' + line)
        result.append(line)
    return result


def runtime_language_report(state):
    plan = package_plan(state, '')
    config = plan['config']
    detected = plan['detected']
    build = detect(state.get('components', []), scope='build') if config['auto_detect'] else {'hints': {}, 'files': [], 'versions': {}, 'declared': {}}
    lines = ['FINAL RUNTIME INTERPRETER REQUIREMENTS', '']
    for language, field, packages, required, executable in (
        ('Python', 'python_version', 'python_packages', 'python_required', 'python'),
        ('R', 'r_version', 'cran_packages', 'r_required', 'Rscript'),
        ('Perl', 'perl_version', 'cpan_modules', 'perl_required', 'perl'),
    ):
        explicit = config[field]
        explicit_packages = items(config[packages], spec=(packages == 'python_packages'))
        hints = bool(detected['hints'].get(language.lower()))
        declared_packages = detected['declared'].get(packages, [])
        present = bool(plan[required])
        lines.append(language + ': ' + ('REQUIRED OR REQUESTED' if present else 'NOT REQUIRED BY CURRENT RUNTIME CONFIGURATION'))
        lines.append('  Explicit minimum version: ' + (explicit or 'none'))
        lines.append('  Explicit packages: ' + (', '.join(explicit_packages) or 'none'))
        lines.append('  Detected deployed script/project: ' + ('yes' if hints else 'no'))
        lines.append('  Packages declared by runtime manifests: ' + (', '.join(declared_packages) or 'none'))
        if not present:
            lines.append('  No automatic ' + executable + ' verification will be generated.')
        elif language == 'Python' and not plan['python_version']:
            lines.append('  Python major version unspecified. The default command is python, not python3.')
        lines.append('')
    lines.append('FILES CONSIDERED FOR FINAL RUNTIME')
    lines.extend('  ' + name for name in detected.get('files', []))
    if not detected.get('files'):
        lines.append('  none')
    lines += ['', 'BUILD-ONLY SOURCE HINTS (NOT INFERRED AS FINAL-IMAGE REQUIREMENTS)']
    for language in ('python', 'r', 'perl'):
        if build['hints'].get(language):
            lines.append('  ' + language + ': source files or build manifests detected')
    lines.extend('  ' + name for name in build.get('files', []))
    if not build.get('files'):
        lines.append('  none')
    lines += ['', 'LIMITATION: optional scripts, custom commands, and dynamic program calls require separate testing.',
              'Explicit runtime settings and custom verification commands are never silently removed.']
    for key in ('pre_commands', 'post_commands', 'verify_commands', 'dockerfile_directives'):
        if config[key]:
            lines.append('Custom runtime field ' + key + ' contains user-provided commands; review it for interpreter requirements.')
    return '\n'.join(lines)
