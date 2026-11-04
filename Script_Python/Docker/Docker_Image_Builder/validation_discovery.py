import ntpath
import posixpath
import re
import shlex
import subprocess
from pathlib import Path
from zipfile import ZipFile, BadZipFile

CHECK_TYPES = ('Installation', 'Version', 'Help / startup', 'Self-test', 'Functional')
VERSION_PATTERN = re.compile(r'(?i)(?:\bversion\b[\s:=v"\']*|\bv)(\d+(?:\.\d+){1,4}(?:[-+._][A-Za-z0-9.+_-]+)?)')
VERSION_LINE = re.compile(r'^\s*(?:[A-Za-z][A-Za-z0-9_.+-]*(?:\s+[A-Za-z][A-Za-z0-9_.+-]*){0,3}\s+)?v?(\d+(?:\.\d+){1,4}(?:[-+._][A-Za-z0-9.+_-]+)?)\s*$', re.I)
HELP_PATTERN = re.compile(r'(?i)\b(usage|options|arguments|commands|help)\b')
SELF_TEST_PATTERN = re.compile(r'(?i)(?:self[ -]?test\s*[:=]\s*pass|self[ -]?test\s+passed|all\s+tests\s+passed|tests\s+passed|self[ -]?test\s*:\s*ok)')


def installed_target(component):
    kind = str(component.get('kind', '')).lower().strip()
    destination = str(component.get('destination', '') or '').rstrip('/')
    if kind in ('os package', 'base-provided'):
        return str(component.get('name', '') or '').strip()
    if not destination.startswith('/'):
        return ''
    if kind == 'source':
        name = posixpath.basename(str(component.get('output_rel', '') or '').replace('\\', '/'))
    else:
        name = ntpath.basename(str(component.get('source', '') or '').replace('\\', '/').rstrip('/'))
    if kind == 'folder':
        return destination
    return posixpath.join(destination, name) if name else ''


def entrypoint(component):
    kind = str(component.get('kind', '')).lower().strip()
    target = installed_target(component)
    if kind in ('binary', 'source') and target:
        return [target]
    if kind == 'jar/application' and target.lower().endswith('.jar'):
        return ['java', '-jar', target]
    if kind == 'base-provided' and re.fullmatch(r'[A-Za-z0-9_.+-]+', target):
        return [target]
    return None


def _manifest_version(path):
    if not str(path).lower().endswith('.jar') or not Path(path).is_file():
        return ''
    try:
        with ZipFile(path) as archive:
            manifest = archive.read('META-INF/MANIFEST.MF').decode('utf-8', errors='replace')
    except (OSError, BadZipFile, KeyError):
        return ''
    for line in manifest.splitlines():
        match = re.match(r'^(?:Implementation-Version|Bundle-Version):\s*(\S+)', line, re.I)
        if match and re.search(r'\d', match.group(1)):
            return match.group(1)
    return ''


def _version(output):
    if not output or re.search(r'(?i)(?:no such file|unrecognized option|unknown option|not found)', output):
        return ''
    for line in output.splitlines()[:12]:
        if re.search(r'(?i)^\s*(?:usage|error|warning)\s*:', line):
            continue
        match = VERSION_PATTERN.search(line) or VERSION_LINE.fullmatch(line)
        if match:
            return match.group(1)
    return ''


def _result(status, command='', output='', detail='', method='automatic'):
    return {'status': status, 'command': command, 'output': str(output)[:3000], 'detail': detail, 'method': method}


def _safename(value):
    return shlex.quote(str(value))


def _check_installed_command(component, package_manager='dpkg'):
    kind = str(component.get('kind', '')).lower().strip()
    target = installed_target(component)
    if not target:
        return ''
    quoted = _safename(target)
    if kind == 'os package':
        if not re.fullmatch(r'[\w.+:-]+', target):
            return ''
        manager = (package_manager or 'dpkg').lower()
        if 'apk' in manager:
            return 'apk info -e ' + quoted
        if 'rpm' in manager or 'dnf' in manager:
            return 'rpm -q ' + quoted
        return 'test "$(dpkg-query -W -f=\'${Status}\' ' + quoted + ' 2>/dev/null)" = "install ok installed"'
    if kind == 'base-provided':
        return 'command -v ' + quoted + ' >/dev/null 2>&1'
    if kind == 'folder':
        return 'test -d ' + quoted
    if kind in ('jar/application', 'other'):
        return 'test -f ' + quoted
    return 'test -x ' + quoted


def _known_functional(component):
    name = str(component.get('name', '')).lower().strip()
    target = installed_target(component)
    if not target or str(component.get('kind', '')).lower() not in ('source', 'binary'):
        return None
    if name == 'sum_numbers':
        cmd = "printf '1\\n2\\n3\\n4\\n5\\n' > /tmp/validation_numbers.txt && " + _safename(target) + ' /tmp/validation_numbers.txt'
        return {'command': cmd, 'expected': 'SUM=15', 'match': 'contains', 'exit_code': 0, 'stdin': '', 'input_folder': ''}
    if name == 'textstats':
        cmd = "printf 'alpha beta\\ngamma delta\\n' > /tmp/validation_words.txt && " + _safename(target) + ' /tmp/validation_words.txt'
        return {'command': cmd, 'expected': 'LINES=2 WORDS=4', 'match': 'contains', 'exit_code': 0, 'stdin': '', 'input_folder': ''}
    return None


def _evaluate_expected(result, spec):
    if result['returncode'] is None:
        return 'ERROR', 'Execution failed or timed out'
    expected_code = int(spec.get('exit_code', 0))
    if result['returncode'] != expected_code:
        return 'FAIL', 'Exit code ' + str(result['returncode']) + ', expected ' + str(expected_code)
    expected = str(spec.get('expected', '') or '')
    if expected:
        actual = result['stdout'] + result['stderr']
        mode = str(spec.get('match', 'contains') or 'contains')
        if mode == 'exact':
            ok = actual.strip() == expected.strip()
        elif mode == 'regex':
            try:
                ok = bool(re.search(expected, actual, re.M))
            except re.error:
                return 'ERROR', 'Invalid expected-output regular expression'
        else:
            ok = expected in actual
        if not ok:
            return 'FAIL', 'Expected output was not present'
    return 'PASS', 'Exit code and expected output verified' if expected else 'Exit code verified; no expected output specified'


class DockerValidator:
    def __init__(self, image, timeout=12):
        self.image = image
        self.timeout = max(2, int(timeout))

    def execute(self, argv=None, shell_command=None, stdin='', input_folder=''):
        args = ['docker', 'run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--pids-limit', '64', '--memory', '512m',
                '--tmpfs', '/tmp:rw,nosuid,nodev,size=32m']
        if input_folder:
            folder = Path(input_folder).expanduser()
            if not folder.is_dir():
                return {'returncode': None, 'stdout': '', 'stderr': 'Input folder does not exist: ' + str(folder)}
            args.extend(['--mount', f'type=bind,source={folder.resolve()},target=/testdata,readonly'])
        args.append(self.image)
        args.extend(['sh', '-lc', shell_command] if shell_command is not None else list(argv or []))
        try:
            process = subprocess.run(args, input=stdin or None, capture_output=True, text=True,
                                     errors='replace', timeout=self.timeout,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return {'returncode': process.returncode, 'stdout': process.stdout[:8000], 'stderr': process.stderr[:8000]}
        except subprocess.TimeoutExpired:
            return {'returncode': None, 'stdout': '', 'stderr': 'Timed out after ' + str(self.timeout) + ' seconds'}
        except (OSError, ValueError) as exc:
            return {'returncode': None, 'stdout': '', 'stderr': str(exc)}

    def _run_spec(self, spec, kind):
        command = str(spec.get('command', '') or '').strip()
        if not command:
            return _result('NOT VERIFIED', detail='No command configured')
        result = self.execute(shell_command=command, stdin=str(spec.get('stdin', '') or ''),
                              input_folder=str(spec.get('input_folder', '') or ''))
        status, detail = _evaluate_expected(result, spec)
        return _result(status, command, result['stdout'] + result['stderr'], detail, 'manual' if kind == 'manual' else kind)

    def test(self, component, check_type, override=None, package_manager='dpkg'):
        if override and str(override.get('command', '')).strip():
            outcome = self._run_spec(override, 'manual')
            if outcome['status'] == 'PASS' and not str(override.get('expected', '') or '').strip():
                if check_type == 'Version':
                    version = _version(outcome['output'])
                    if not version:
                        return _result('NOT VERIFIED', outcome['command'], outcome['output'], 'Command returned zero but no recognizable version was found', 'manual')
                    outcome['detail'] = 'Version: ' + version
                elif check_type == 'Help / startup' and not HELP_PATTERN.search(outcome['output']):
                    return _result('NOT VERIFIED', outcome['command'], outcome['output'], 'No recognizable help/usage output was found', 'manual')
                elif check_type == 'Functional':
                    return _result('NOT VERIFIED', outcome['command'], outcome['output'], 'Command exited successfully, but no expected output was supplied', 'manual')
            return outcome
        kind = str(component.get('kind', '') or '').lower().strip()
        target = installed_target(component)
        start = entrypoint(component)
        if check_type == 'Installation':
            command = _check_installed_command(component, package_manager)
            if not command:
                return _result('NOT VERIFIED', detail='Installation target is not defined')
            result = self.execute(shell_command=command)
            status = 'PASS' if result['returncode'] == 0 else 'ERROR' if result['returncode'] is None else 'FAIL'
            return _result(status, command, result['stdout'] + result['stderr'], 'Installed and accessible' if status == 'PASS' else 'Installation not confirmed')
        if check_type == 'Functional':
            known = _known_functional(component)
            return self._run_spec(known, 'built-in known-input') if known else _result('NOT VERIFIED', detail='No trusted known-input test available; configure one manually')
        if check_type == 'Version' and kind == 'os package':
            if not re.fullmatch(r'[A-Za-z0-9.+:_-]+', target):
                return _result('NOT VERIFIED', detail='Package name is not valid')
            if package_manager and 'apk' in package_manager.lower():
                cmd = ['apk', 'info', '-v', target]
            elif package_manager and any(s in package_manager.lower() for s in ('rpm', 'dnf')):
                cmd = ['rpm', '-q', target]
            else:
                cmd = ['dpkg-query', '-W', '-f=${Version}', target]
            probe = self.execute(argv=cmd)
            version = _version(probe['stdout']) or (probe['stdout'].strip() if probe['returncode'] == 0 else '')
            if probe['returncode'] == 0 and version:
                return _result('PASS', shlex.join(cmd), probe['stdout'], 'Package version: ' + version)
            return _result('NOT VERIFIED', shlex.join(cmd), probe['stdout'] + probe['stderr'], 'Package version unavailable')
        if not start:
            if check_type == 'Version' and kind == 'jar/application':
                version = _manifest_version(component.get('source', ''))
                if version:
                    return _result('PASS', 'JAR manifest', detail='Manifest version: ' + version, method='manifest')
            return _result('N/A' if check_type in ('Help / startup', 'Self-test') or (kind in ('folder', 'other') and check_type == 'Version') else 'NOT VERIFIED', detail='No executable entry point known; configure a command if needed')
        if check_type == 'Version':
            for flag in ('--version', '-V', '-v', 'version'):
                cmd = start + [flag]
                probe = self.execute(argv=cmd)
                if probe['returncode'] is None:
                    return _result('ERROR', shlex.join(cmd), probe['stderr'], 'Version probe could not execute')
                version = _version(probe['stdout'] + '\n' + probe['stderr'])
                if probe['returncode'] == 0 and version:
                    return _result('PASS', shlex.join(cmd), probe['stdout'] + probe['stderr'], 'Version: ' + version)
            if kind == 'jar/application':
                version = _manifest_version(component.get('source', ''))
                if version:
                    return _result('PASS', 'JAR manifest', detail='Manifest version: ' + version, method='manifest')
            return _result('NOT VERIFIED', detail='No supported version option produced a verifiable version')
        if check_type == 'Help / startup':
            for flag in ('--help', '-h', 'help'):
                cmd = start + [flag]
                probe = self.execute(argv=cmd)
                if probe['returncode'] is None:
                    return _result('ERROR', shlex.join(cmd), probe['stderr'], 'Help probe could not execute')
                output = probe['stdout'] + probe['stderr']
                if probe['returncode'] == 0 and HELP_PATTERN.search(output) and not re.search(r'(?i)(no such file|unknown option|unrecognized option)', output):
                    return _result('PASS', shlex.join(cmd), output, 'Help/startup works; not a functional test')
            return _result('NOT VERIFIED', detail='No recognized help response; startup is not confirmed by help')
        if check_type == 'Self-test':
            for flag in ('--self-test', '--selftest'):
                cmd = start + [flag]
                probe = self.execute(argv=cmd)
                if probe['returncode'] is None:
                    return _result('ERROR', shlex.join(cmd), probe['stderr'], 'Self-test probe could not execute')
                output = probe['stdout'] + probe['stderr']
                if probe['returncode'] == 0 and SELF_TEST_PATTERN.search(output):
                    return _result('PASS', shlex.join(cmd), output, 'Explicit self-test success confirmed')
            existing = str(component.get('validation', '') or '').strip()
            if '--self-test' in existing or '--selftest' in existing:
                return self._run_spec({'command': existing, 'exit_code': 0}, 'configured')
            return _result('NOT VERIFIED', detail='No supported self-test found; --help is not a self-test')
        return _result('NOT VERIFIED', detail='No automatic check available')
