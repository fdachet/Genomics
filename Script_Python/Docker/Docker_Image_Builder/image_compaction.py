import json
import queue
import re
import subprocess
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog


def _json_arg(value):
    return json.dumps(value, ensure_ascii=True)


def _string_arg(value):
    return _json_arg(str(value).replace('$', '\\$'))


def compact_dockerfile(source, image_data):
    config = image_data.get('Config') or {}
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.:/@-]*', source):
        raise ValueError('Invalid source Docker image reference')
    lines = ['FROM ' + source + ' AS existing', 'FROM scratch', 'COPY --from=existing / /']
    for assignment in config.get('Env') or []:
        if '=' not in assignment:
            continue
        key, value = assignment.split('=', 1)
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
            raise ValueError('Unsupported environment variable: ' + key)
        lines.append('ENV ' + key + '=' + _string_arg(value))
    for key, value in (config.get('Labels') or {}).items():
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', key):
            raise ValueError('Unsupported label key: ' + key)
        lines.append('LABEL ' + key + '=' + _string_arg(value))
    for exposed in (config.get('ExposedPorts') or {}):
        if not re.fullmatch(r'\d+(?:/(?:tcp|udp|sctp))?', exposed):
            raise ValueError('Unsupported exposed port: ' + str(exposed))
        lines.append('EXPOSE ' + exposed)
    if config.get('Volumes'):
        lines.append('VOLUME ' + _json_arg(list(config['Volumes'])))
    if config.get('WorkingDir'):
        lines.append('WORKDIR ' + _string_arg(config['WorkingDir']))
    if config.get('User'):
        lines.append('USER ' + _string_arg(config['User']))
    if config.get('Shell'):
        lines.append('SHELL ' + _json_arg(config['Shell']))
    if config.get('Entrypoint') is not None:
        lines.append('ENTRYPOINT ' + _json_arg(config['Entrypoint']))
    if config.get('Cmd') is not None:
        lines.append('CMD ' + _json_arg(config['Cmd']))
    if config.get('StopSignal'):
        lines.append('STOPSIGNAL ' + str(config['StopSignal']))
    health = config.get('Healthcheck')
    if health:
        test = health.get('Test') or []
        if test == ['NONE']:
            lines.append('HEALTHCHECK NONE')
        elif test and test[0] in ('CMD', 'CMD-SHELL'):
            options = []
            for field, flag in (('Interval', 'interval'), ('Timeout', 'timeout'), ('StartPeriod', 'start-period'), ('StartInterval', 'start-interval')):
                duration = health.get(field)
                if duration:
                    options.append('--' + flag + '=' + str(duration) + 'ns')
            if health.get('Retries'):
                options.append('--retries=' + str(health['Retries']))
            command = 'CMD ' + _json_arg(test[1:]) if test[0] == 'CMD' else 'CMD ' + str(test[1])
            lines.append('HEALTHCHECK ' + ' '.join(options + [command]))
        else:
            raise ValueError('Unsupported healthcheck specification')
    if config.get('OnBuild'):
        for instruction in config['OnBuild']:
            if '\n' in instruction or '\r' in instruction:
                raise ValueError('Unsupported ONBUILD instruction')
            lines.append('ONBUILD ' + instruction)
    return '\n'.join(lines) + '\n'


def inspect_image(image, timeout=25):
    result = subprocess.run(['docker', 'image', 'inspect', image], capture_output=True, text=True,
                            timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Unable to inspect Docker image')
    data = json.loads(result.stdout)
    if not data:
        raise RuntimeError('Image not found locally: ' + image)
    return data[0]


def normalize_config(config):
    wanted = ('Env', 'Labels', 'Entrypoint', 'Cmd', 'User', 'WorkingDir', 'ExposedPorts', 'Volumes', 'StopSignal', 'Shell', 'Healthcheck')
    data = {key: config.get(key) for key in wanted}
    if not data.get('User'):
        data['User'] = ''
    if not data.get('WorkingDir'):
        data['WorkingDir'] = ''
    for key in ('ExposedPorts', 'Volumes', 'Labels'):
        data[key] = data[key] or {}
    return data


def run_compaction(source, destination, log):
    before = inspect_image(source)
    if destination == source:
        raise ValueError('Compact image must have a different tag from the source')
    dockerfile = compact_dockerfile(source, before)
    with tempfile.TemporaryDirectory(prefix='component_builder_compact_') as folder:
        path = Path(folder)
        (path / 'Dockerfile').write_text(dockerfile, encoding='utf-8')
        cmd = ['docker', 'build', '--pull=false', '--network=none', '--progress=plain', '-t', destination, folder]
        process = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, errors='replace', bufsize=1,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for line in process.stdout:
            log(line)
        code = process.wait()
        if code:
            raise RuntimeError('Docker compact build failed with exit code ' + str(code))
    after = inspect_image(destination)
    original_config = normalize_config(before.get('Config') or {})
    new_config = normalize_config(after.get('Config') or {})
    differences = [field for field in original_config if original_config[field] != new_config[field]]
    if differences:
        raise RuntimeError('Compacted image metadata differs in ' + ', '.join(differences) + '. Source image remains unchanged. Inspect the new image before using it.')
    log('Original image size (uncompressed): ' + str(before.get('Size', 0)) + ' bytes\n')
    log('Compacted image size (uncompressed): ' + str(after.get('Size', 0)) + ' bytes\n')
    return {'source': source, 'image': destination, 'before_size': before.get('Size', 0),
            'after_size': after.get('Size', 0), 'config_verified': True}


def show_compaction_dialog(parent, source, callback=None):
    source = str(source or '').strip()
    if not source:
        messagebox.showerror('Compact image', 'Select an existing built image first.', parent=parent)
        return None
    target = simpledialog.askstring('Compact Docker image',
                                    'Create a NEW flattened image tag. This may reduce total size after file removal.\nThe source image stays untouched.\nThe compacted image must be tested after building:',
                                    initialvalue=source + '-compact', parent=parent)
    if target is None:
        return None
    target = target.strip()
    if not target or target == source or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.:/-]*', target):
        messagebox.showerror('Compact image', 'Enter a valid new image tag.', parent=parent)
        return None
    dialog = tk.Toplevel(parent)
    dialog.title('Compacting Docker image')
    dialog.geometry('880x520')
    tk.Label(dialog, text=source + '  →  ' + target, anchor='w').pack(fill='x', padx=12, pady=8)
    output = tk.Text(dialog, wrap='none', font=('Consolas', 9))
    output.pack(fill='both', expand=True, padx=12, pady=8)
    events = queue.Queue()
    state = {'done': False, 'result': None}
    def log(value):
        events.put(('log', str(value)))
    def worker():
        try:
            result = run_compaction(source, target, log)
            events.put(('done', result))
        except Exception as exc:
            events.put(('error', str(exc)))
    def poll():
        try:
            while True:
                event, value = events.get_nowait()
                if event == 'log':
                    output.insert('end', value)
                    output.see('end')
                else:
                    state['done'] = True
                    if event == 'done':
                        state['result'] = value
                        output.insert('end', '\nCOMPACTED IMAGE CREATED. Verify applications in Tab 7 before exporting.\n')
                        if callable(callback):
                            callback(value)
                    else:
                        output.insert('end', '\nCOMPACTION FAILED: ' + value + '\n')
        except queue.Empty:
            pass
        if not state['done'] and dialog.winfo_exists():
            dialog.after(150, poll)
    threading.Thread(target=worker, daemon=True).start()
    dialog.after(150, poll)
    return dialog
