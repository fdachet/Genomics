import json
import ntpath
import posixpath
import queue
import re
import shlex
import subprocess
import os
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from workflow_toolbar import add_more_menu


def command_examples(state, mount_point):
    mount = shlex.quote(str(mount_point or '/'))
    examples = ['pwd', 'ls -lah ' + mount]
    for component in state.get('components') or []:
        if not isinstance(component, dict) or not component.get('enabled', True):
            continue
        kind = str(component.get('kind') or '').lower()
        if kind not in ('binary', 'source', 'os package', 'script'):
            continue
        name = str(component.get('name') or '').strip()
        if kind == 'os package':
            executable = name if re.fullmatch(r'[A-Za-z0-9_+.-]+', name) else ''
            if executable:
                examples.append('command -v ' + shlex.quote(executable))
            continue
        source = str(component.get('source') or '').strip()
        if kind == 'source':
            record = (state.get('compiled_artifacts') or {}).get(name) or {}
            source = str(record.get('artifact') or '')
        destination = str(component.get('destination') or '').strip()
        if not source or not destination.startswith('/'):
            continue
        target = posixpath.join(destination, Path(source).name)
        examples.append('test -x ' + shlex.quote(target) + ' && echo EXECUTABLE_FOUND')
    return list(dict.fromkeys(examples))


def validate_config(config):
    name = str(config.get('name', '')).strip()
    image = str(config.get('image', '')).strip()
    source = str(config.get('host_folder', '')).strip()
    target = str(config.get('mount_point', '')).strip()
    workdir = str(config.get('workdir', '')).strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
        raise ValueError('Container name must contain only letters, numbers, dots, underscores, or hyphens.')
    if not image or any(x in image for x in ('\r', '\n', ' ', '\t')):
        raise ValueError('Select a valid Docker image tag.')
    enabled = bool(config.get('mount_enabled', True))
    if enabled and (not source or not (ntpath.isabs(source) or Path(source).is_absolute())):
        raise ValueError('Choose an existing absolute Windows folder, or disable the Windows folder mount.')
    if enabled and (',' in source or '\n' in source or '\r' in source):
        raise ValueError('Choose a mount folder without a comma or newline in its path.')
    for value, label in ((target, 'Container mount path'), (workdir, 'Working directory')):
        if not value.startswith('/') or '\\' in value or ',' in value or any(part == '..' for part in value.split('/')):
            raise ValueError(label + ' must be an absolute Linux path without commas or .. segments.')
        if '\n' in value or '\r' in value:
            raise ValueError(label + ' cannot contain line breaks.')
    if enabled and target == '/':
        raise ValueError('Do not mount over the container root filesystem. Use /data or another folder.')
    return {'image': image, 'name': name, 'host_folder': source, 'mount_point': posixpath.normpath(target),
            'workdir': posixpath.normpath(workdir), 'mount_enabled': enabled, 'network': bool(config.get('network')),
            'read_only': bool(config.get('read_only')),
            'command': str(config.get('command', '') or ''),
            'source_tar': str(config.get('source_tar', '') or '').strip()}


MANAGED_LABEL = 'org.component-image-builder.tab9.managed'


def is_managed_container(info):
    config = (info or {}).get('Config') or {}
    labels = config.get('Labels') or {}
    if labels.get(MANAGED_LABEL) == 'true':
        return True
    entrypoint = config.get('Entrypoint') or []
    command = config.get('Cmd') or []
    if isinstance(entrypoint, str):
        entrypoint = [entrypoint]
    if isinstance(command, str):
        command = [command]
    return entrypoint == ['/bin/sh'] and command == ['-c', 'while :; do sleep 3600; done']


def docker_image_id(image):
    result = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image],
                            capture_output=True, text=True, errors='replace', timeout=90,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return result.stdout.strip() if result.returncode == 0 else ''


def create_container_args(config):
    data = validate_config(config)
    args = ['docker', 'create', '--pull', 'never', '--name', data['name'], '--label', MANAGED_LABEL + '=true']
    if data['mount_enabled']:
        mount = 'type=bind,source=' + data['host_folder'] + ',target=' + data['mount_point']
        if data['read_only']:
            mount += ',readonly'
        args.extend(['--mount', mount])
    args.extend(['--workdir', data['workdir'], '--network', 'bridge' if data['network'] else 'none',
                 '--entrypoint', '/bin/sh', data['image'], '-c', 'while :; do sleep 3600; done'])
    return args


def mount_error_guidance(error, source):
    message = str(error)
    lowered = message.lower()
    if 'bind source path does not exist' in lowered or 'invalid mount config' in lowered:
        return (message + '\n\nDocker Desktop cannot access the Windows source folder: ' + source +
                '\nThis commonly occurs when the selected drive is a Windows mapped network drive, '
                'a SUBST drive, or a drive not shared with Docker Desktop.'
                '\nChoose a local folder on a Docker-accessible drive, configure Docker Desktop drive/file sharing, '
                'or uncheck "Mount Windows folder" to run the Linux container without Windows files.'
                '\nIf the P: drive is mapped, try a local path or a supported UNC path; '
                'Windows Explorer access alone does not prove Docker can access it.')
    return message


def inspect_container(name):
    process = subprocess.run(['docker', 'container', 'inspect', name], capture_output=True,
                             text=True, errors='replace', timeout=90,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if process.returncode:
        return None
    data = json.loads(process.stdout)
    return data[0] if data else None


def list_docker_images():
    process = subprocess.run(['docker', 'image', 'ls', '--format', '{{json .}}'], capture_output=True,
                             text=True, errors='replace', timeout=90,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if process.returncode:
        raise RuntimeError((process.stderr or process.stdout or 'Unable to list images in Docker Desktop.').strip())
    result = []
    seen = set()
    for line in process.stdout.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        repository = str(row.get('Repository', '') or '').strip()
        tag = str(row.get('Tag', '') or '').strip()
        if not repository or repository == '<none>' or not tag or tag == '<none>':
            continue
        name = repository + ':' + tag
        if name in seen:
            continue
        seen.add(name)
        result.append({'name': name, 'id': str(row.get('ID', '') or ''),
                       'size': str(row.get('Size', '') or ''),
                       'created': str(row.get('CreatedSince', '') or row.get('CreatedAt', '') or '')})
    result.sort(key=lambda image: image['name'].lower())
    return result


class ContainerTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg='#EAF3FA')
        self.app = app
        self.events = queue.Queue()
        self.busy = False
        self._active_process = None
        self.name = tk.StringVar(value='container')
        self.image = tk.StringVar()
        self.runtime_source_info = tk.StringVar(value='Tab 0 runtime: no archive selected')
        self.host_folder = tk.StringVar()
        self.mount_point = tk.StringVar(value='/data')
        self.workdir = tk.StringVar(value='/data')
        self.network = tk.BooleanVar(value=False)
        self._details = []
        self._pending_auto_start = None
        self._pending_terminal_open = False
        self._source_tar_path = ''
        self._session_image_id = ''
        self._session_image_tag = ''
        self.mount_enabled = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value='Select an image or Docker TAR. The container will start automatically.')
        self._render()
        self.refresh_from_project_state()
        self.after(100, self._drain)

    def _render(self):
        banner = tk.Frame(self, bg='#196A8D', padx=18, pady=13)
        banner.pack(fill='x', padx=3, pady=(3, 0))
        tk.Label(banner, text='9 — RUN SOFTWARE INSIDE A DOCKER CONTAINER', bg='#196A8D',
                 fg='white', font=('Segoe UI', 16, 'bold')).pack(anchor='w')
        tk.Label(self, text='Load a Docker image and open its full Linux terminal. Windows folders are accessible only when mounted.',
                 bg='#D9EDF8', fg='#22536D', font=('Segoe UI', 10), anchor='w', padx=14, pady=9).pack(fill='x', padx=3)

        settings = tk.LabelFrame(self, text='Docker image, container and Windows folder mount',
                                 bg='#EAF3FA', fg='#22536D', padx=12, pady=10,
                                 font=('Segoe UI', 10, 'bold'))
        settings.pack(fill='x', padx=17, pady=(10, 5))
        settings.grid_columnconfigure(1, weight=1)

        self._field(settings, 0, 'Docker image to run:', self.image)
        image_actions = tk.Frame(settings, bg='#EAF3FA')
        image_actions.grid(row=1, column=1, columnspan=2, padx=2, pady=(0, 4), sticky='w')
        tk.Button(image_actions, text='From Tab 0 Runtime TAR', command=self.use_tab1_runtime,
                  bg='#68CBB0', font=('Segoe UI', 10, 'bold')).pack(side='left', padx=(0, 8))
        tk.Button(image_actions, text='From Tab 6 Final Image', command=self.use_final_image,
                  bg='#ABDDE6').pack(side='left', padx=(0, 8))
        tk.Button(image_actions, text='Browse Docker Images', command=self.browse_images,
                  bg='#ABDDE6').pack(side='left', padx=(0, 8))
        tk.Button(image_actions, text='Browse TAR...', command=self.browse_tar,
                  bg='#ABDDE6').pack(side='left')
        tk.Label(settings, textvariable=self.runtime_source_info, bg='#EAF3FA', fg='#315D74',
                 anchor='w', justify='left', wraplength=1160,
                 font=('Segoe UI', 9)).grid(row=2, column=1, columnspan=2, sticky='ew', pady=(0, 6))
        self._field(settings, 3, 'Container name:', self.name)
        self._field(settings, 4, 'Windows DATA folder to mount:', self.host_folder)
        tk.Button(settings, text='Browse...', command=self.browse,
                  bg='#ABDDE6').grid(row=4, column=2, padx=5, pady=4)
        self._field(settings, 5, 'Folder inside Linux:', self.mount_point)
        self._field(settings, 6, 'Linux working directory:', self.workdir)

        options = tk.Frame(settings, bg='#EAF3FA')
        options.grid(row=7, column=1, columnspan=2, sticky='w', pady=(6, 1))
        tk.Checkbutton(options, text='Mount Windows folder', variable=self.mount_enabled,
                       bg='#EAF3FA').pack(side='left', padx=(0, 18))
        tk.Checkbutton(options, text='Enable container network (default: offline)', variable=self.network,
                       bg='#EAF3FA').pack(side='left', padx=(0, 18))

        controls = tk.Frame(self, bg='#EAF3FA')
        controls.pack(fill='x', padx=17, pady=7)
        self.start_button = self._button(controls, 'Start New Container', self.start_container, '#1D9D78')
        self._button(controls, 'Open Runtime Container', lambda: self.use_tab1_runtime(open_terminal=True), '#68CBB0')
        self._button(controls, 'Open Container', self.open_terminal, '#78C7F0')
        self._button(controls, 'Stop + Remove Container and Image', self.stop_container, '#D88755')
        self._button(controls, 'Save Settings', self.save_settings, '#AED6F1')
        add_more_menu(controls, [
            ("Check container status", self.check_container),
            ("Diagnose Docker or Windows mount", self.diagnose_docker),
            ("View operation details", self.show_operation_details),
        ], "#EAF3FA")

        status_box = tk.Frame(self, bg='#D8EFF0', padx=12, pady=8)
        status_box.pack(fill='x', padx=17)
        tk.Label(status_box, textvariable=self.status, bg='#D8EFF0', fg='#155B62',
                 font=('Segoe UI', 10, 'bold'), anchor='w', wraplength=1350).pack(fill='x')


    def _field(self, parent, row, label, variable):
        tk.Label(parent, text=label, bg='#EAF3FA', anchor='w', width=26,
                 font=('Segoe UI', 10, 'bold')).grid(row=row, column=0, sticky='w', padx=(0, 8), pady=4)
        tk.Entry(parent, textvariable=variable, font=('Consolas', 10)).grid(row=row, column=1, sticky='ew', pady=4)

    def _button(self, parent, label, action, color):
        button = tk.Button(parent, text=label, command=action, bg=color, fg='#17202A',
                           font=('Segoe UI', 10), padx=8, pady=5)
        button.pack(side='left', padx=(0, 8))
        return button

    def use_tab1_runtime(self, open_terminal=False):
        archive_name = str(self.app.state.get('runtime_base_archive') or '').strip()
        runtime_tag = str(self.app.state.get('base_image') or '').strip()
        if not runtime_tag and not archive_name:
            messagebox.showwarning('Tab 0 runtime image',
                                   'Load a runtime Docker TAR in Tab 0 first.', parent=self)
            return
        if archive_name:
            self._append('Tab 0 runtime archive: ' + archive_name + '\n')

        def action():
            if runtime_tag:
                check = subprocess.run(['docker', 'image', 'inspect', runtime_tag],
                                       capture_output=True, text=True, errors='replace', timeout=90,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if check.returncode == 0:
                    self.events.put(('image_selected', runtime_tag, True, open_terminal, archive_name))
                    return 'RUNTIME IMAGE SELECTED: ' + runtime_tag + ' | Starting container automatically.'
            if not archive_name:
                raise RuntimeError('The Tab 0 runtime tag is not loaded in Docker Desktop and no TAR path is recorded. Reload the TAR in Tab 0.')
            archive = Path(archive_name)
            if not archive.is_file():
                raise RuntimeError('The Tab 0 runtime image is not loaded in Docker Desktop and the TAR cannot be found: ' + str(archive))
            return self._load_tar_action(archive, expected_tag=runtime_tag, source='Tab 0 runtime', open_terminal=open_terminal)

        self._work('Select runtime image from Tab 0', action)

    def use_final_image(self):
        image = str(self.app.state.get('built_image') or self.app.state.get('image_name') or '').strip()
        if image:
            self.image.set(image)
            self._source_tar_path = str(self.app.state.get('last_full_image_tar') or '')
            self.start_container(automatic=True)
        else:
            messagebox.showwarning('Image', 'Build or select your final Docker image in Tab 6.', parent=self)

    def browse_images(self):
        def action():
            images = list_docker_images()
            self.events.put(('images', images))
            return str(len(images)) + ' locally available Docker image tags found.'

        self._work('Browse images in Docker Desktop', action)

    def _show_image_picker(self, images):
        if not images:
            messagebox.showinfo('Docker images', 'Docker Desktop has no tagged local images. Build one in Tab 6 or load a .tar archive.', parent=self)
            return
        window = tk.Toplevel(self)
        window.title('Select an image from Docker Desktop')
        window.geometry('960x550')
        window.minsize(650, 360)
        window.transient(self.winfo_toplevel())
        window.configure(bg='#EAF3FA')
        tk.Label(window, text='Choose the installed Docker IMAGE TAG to run', bg='#196A8D',
                 fg='white', font=('Segoe UI', 13, 'bold'), padx=12, pady=12).pack(fill='x')
        tk.Label(window, text='These images are stored inside Docker Desktop. They do not have normal Windows file paths.',
                 bg='#EAF3FA', fg='#38637B', anchor='w', padx=12, pady=7).pack(fill='x')
        content = tk.Frame(window, bg='#EAF3FA')
        content.pack(fill='both', expand=True, padx=12, pady=8)
        columns = ('tag', 'id', 'size', 'created')
        tree = ttk.Treeview(content, columns=columns, show='headings', selectmode='browse')
        for field, title, width in (('tag', 'Image name / tag', 420), ('id', 'Image ID', 180),
                                    ('size', 'Size', 100), ('created', 'Created', 150)):
            tree.heading(field, text=title)
            tree.column(field, width=width, stretch=(field == 'tag'))
        scrollbar = ttk.Scrollbar(content, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        selected_id = None
        for index, row in enumerate(images):
            entry = str(index)
            tree.insert('', 'end', iid=entry, values=(row['name'], row['id'], row['size'], row['created']))
            if row['name'] == self.image.get().strip():
                selected_id = entry
        entry = selected_id if selected_id is not None else '0'
        tree.selection_set(entry)
        tree.focus(entry)
        tree.see(entry)

        def select_image(event=None):
            selected = tree.selection()
            if not selected:
                return
            tag = images[int(selected[0])]['name']
            self.image.set(tag)
            self._source_tar_path = ''
            self.status.set('SELECTED DOCKER IMAGE: ' + tag + ' | Starting container automatically.')
            window.destroy()
            self.start_container(automatic=True)

        tree.bind('<Double-1>', select_image)
        controls = tk.Frame(window, bg='#EAF3FA')
        controls.pack(fill='x', padx=12, pady=(0, 12))
        tk.Button(controls, text='Use Selected Image', command=select_image,
                  bg='#1D9D78', padx=12, pady=5).pack(side='left', padx=(0, 8))
        tk.Button(controls, text='Cancel', command=window.destroy,
                  padx=12, pady=5).pack(side='left')
        window.grab_set()

    def browse_tar(self):
        directory = str(self.app.state.get('export_image_dir') or '').strip()
        initialdir = directory if Path(directory).is_dir() else str(Path.cwd())
        path = filedialog.askopenfilename(parent=self, title='Select a saved Docker image archive',
                                          initialdir=initialdir,
                                          filetypes=[('Docker image archives', '*.tar *.tar.gz *.tgz'),
                                                     ('All files', '*.*')])
        if not path:
            return
        archive = Path(path)
        if not archive.is_file():
            messagebox.showerror('Load Docker TAR', 'The selected archive does not exist.', parent=self)
            return
        if re.search(r'_with_(?:repository|local)_packages\.tar(?:\.gz)?$', archive.name, re.I):
            messagebox.showerror('Package-stage archive selected',
                    'This is an OLD package-stage TAR, not the complete application image.\n\n'
                    'Build your full Docker image in Tab 6 and use its automatically exported *_FULL.tar instead.',
                    parent=self)
            return
        self._work('Load image archive: ' + archive.name,
                   lambda: self._load_tar_action(archive, source='manually selected'))

    def _load_tar_action(self, archive, expected_tag='', source='', open_terminal=False):
        args = ['docker', 'load', '-i', str(archive)]
        self.events.put(('log', '$ ' + subprocess.list2cmdline(args) + '\n'))
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, errors='replace', bufsize=1,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        output = []
        try:
            for line in process.stdout:
                output.append(line)
                self.events.put(('log', line))
            code = process.wait()
        finally:
            if process.stdout:
                process.stdout.close()
        self.events.put(('log', 'Docker load exit code: ' + str(code) + '\n'))
        if code:
            raise RuntimeError('Docker could not load this image archive (exit code ' + str(code) + ').')
        text_output = ''.join(output)
        tags = list(dict.fromkeys(match.strip() for match in re.findall(r'^Loaded image:\s*(.+)$',
                                                                             text_output, flags=re.MULTILINE)))
        image_ids = list(dict.fromkeys(match.strip() for match in re.findall(r'^Loaded image ID:\s*(.+)$',
                                                                                  text_output, flags=re.MULTILINE)))
        selected = ''
        if expected_tag:
            check = subprocess.run(['docker', 'image', 'inspect', expected_tag],
                                   capture_output=True, text=True, errors='replace', timeout=90,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if check.returncode == 0:
                selected = expected_tag
        if not selected and len(tags) == 1:
            selected = tags[0]
        if not selected and not tags and len(image_ids) == 1:
            selected = image_ids[0]
        if selected:
            self.events.put(('image_selected', selected, True, open_terminal, str(archive)))
            return 'IMAGE LOADED FROM ' + (source or 'TAR').upper() + ': ' + selected + ' | Starting container automatically.'
        self.events.put(('images', list_docker_images()))
        return 'IMAGE LOADED: Multiple image tags found. Select the image to start automatically.'

    def browse(self):
        initial = self.host_folder.get().strip()
        initial = initial if Path(initial).is_dir() else str(Path.cwd())
        folder = filedialog.askdirectory(parent=self, initialdir=initial, title='Select Windows folder visible inside Docker')
        if folder:
            self.host_folder.set(folder)

    def _config(self):
        return {'name': self.name.get(), 'image': self.image.get(),
                'host_folder': self.host_folder.get(), 'mount_point': self.mount_point.get(),
                'workdir': self.workdir.get(), 'network': self.network.get(),
                'read_only': False, 'mount_enabled': self.mount_enabled.get(),
                'source_tar': self._source_tar_path}

    def save_settings(self):
        try:
            data = validate_config(self._config())
        except ValueError as exc:
            messagebox.showerror('Container settings', str(exc), parent=self)
            return False
        self.app.state['container_config'] = data
        self.status.set('Container settings stored in project state; use Save project JSON in Tab 0 to write them to disk.')
        return True

    def refresh_from_project_state(self):
        data = self.app.state.get('container_config') or {}
        if not isinstance(data, dict):
            data = {}
        runtime_archive = str(self.app.state.get('runtime_base_archive') or '').strip()
        runtime_tag = str(self.app.state.get('base_image') or '').strip()
        if runtime_archive:
            self.runtime_source_info.set('Tab 0 runtime TAR: ' + runtime_archive +
                                         ('  |  Image tag: ' + runtime_tag if runtime_tag else '  |  Tag not yet available'))
        elif runtime_tag:
            self.runtime_source_info.set('Tab 0 runtime Docker tag: ' + runtime_tag + '  |  No TAR recorded')
        else:
            self.runtime_source_info.set('Tab 0 runtime: no image selected')
        self._source_tar_path = str(data.get('source_tar') or '')
        default_image = str(self.app.state.get('built_image') or self.app.state.get('base_image')
                            or self.app.state.get('image_name') or '').strip()
        for key, variable in (('name', self.name), ('image', self.image),
                              ('host_folder', self.host_folder), ('mount_point', self.mount_point),
                              ('workdir', self.workdir)):
            value = data.get(key)
            if value:
                variable.set(str(value))
        if not data.get('image') and default_image:
            self.image.set(default_image)
        if not data.get('host_folder'):
            candidate = str(self.app.state.get('project_dir', '') or '')
            if candidate:
                self.host_folder.set(candidate)
        self.network.set(bool(data.get('network', False)))
        self.mount_enabled.set(bool(data.get('mount_enabled', True)))
        if not self._source_tar_path and self.image.get().strip() == runtime_tag and runtime_archive:
            self._source_tar_path = runtime_archive
    def _append(self, value):
        self._details.append(str(value))
        if len(self._details) > 1500:
            self._details = self._details[-1100:]

    def show_operation_details(self):
        window = tk.Toplevel(self)
        window.title('Docker container operation details')
        window.geometry('1020x580')
        window.configure(bg='#EAF3FA')
        box = tk.Frame(window, bg='#EAF3FA')
        box.pack(fill='both', expand=True, padx=12, pady=12)
        scrolly = ttk.Scrollbar(box, orient='vertical')
        scrolly.pack(side='right', fill='y')
        output = tk.Text(box, font=('Consolas', 10), wrap='word', yscrollcommand=scrolly.set)
        output.insert('1.0', ''.join(self._details))
        output.pack(side='left', fill='both', expand=True)
        scrolly.config(command=output.yview)
        window.transient(self.winfo_toplevel())

    def _drain(self):
        try:
            while True:
                item = self.events.get_nowait()
                if item[0] == 'log':
                    self._append(item[1])
                elif item[0] == 'status':
                    self.status.set(item[1])
                elif item[0] == 'images':
                    self._show_image_picker(item[1])
                elif item[0] == 'image_selected':
                    self.image.set(item[1])
                    self._source_tar_path = str(item[4]) if len(item) > 4 else ''
                    if len(item) > 2 and item[2]:
                        self._pending_auto_start = bool(item[3]) if len(item) > 3 else False
                elif item[0] == 'session_started':
                    self._session_image_tag = item[1]
                    self._session_image_id = item[2]
                elif item[0] == 'session_stopped':
                    self._session_image_tag = ''
                    self._session_image_id = ''
                elif item[0] == 'container_config':
                    config = item[1]
                    self.name.set(config['name'])
                    self.app.state['container_config'] = config
                elif item[0] == 'launch_terminal':
                    self._pending_terminal_open = True
                elif item[0] == 'error':
                    messagebox.showerror('Docker container', item[1], parent=self)
                elif item[0] == 'done':
                    self.busy = False
                    self.start_button.config(state='normal')
                    if self._pending_auto_start is not None:
                        open_terminal = self._pending_auto_start
                        self._pending_auto_start = None
                        self.after_idle(lambda do_open=open_terminal: self.start_container(automatic=True, open_after_start=do_open))
                    elif self._pending_terminal_open:
                        self._pending_terminal_open = False
                        self.after_idle(self.open_terminal)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._drain)

    def _work(self, label, action):
        if self.busy:
            messagebox.showinfo('Container', 'A Docker operation is already in progress.', parent=self)
            return
        self.busy = True
        self.start_button.config(state='disabled')
        self.events.put(('log', '\n=== ' + label + ' ===\n'))
        self.events.put(('status', label + ' ...'))

        def worker():
            try:
                result = action()
                if result:
                    self.events.put(('status', str(result)))
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                message = str(exc)
                self.events.put(('log', 'ERROR: ' + message + '\n'))
                self.events.put(('status', 'ERROR: ' + message[:220]))
                self.events.put(('error', message))
            finally:
                self.events.put(('done',))

        threading.Thread(target=worker, daemon=True).start()

    def _run(self, args, timeout=180, check=True):
        command = subprocess.list2cmdline(args)
        self.events.put(('log', '$ ' + command + '\n'))
        self.events.put(('status', 'Docker: ' + ' '.join(args[1:3]) + ' ...'))
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, errors='replace',
                                   bufsize=1, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self._active_process = process
        output = ''
        started = time.monotonic()
        try:
            if timeout is None:
                chunks = []
                for line in process.stdout:
                    chunks.append(line)
                    self.events.put(('log', line))
                output = ''.join(chunks)
                code = process.wait()
            else:
                timeout = max(0.01, float(timeout))
                while True:
                    elapsed = time.monotonic() - started
                    remaining = timeout - elapsed
                    if remaining <= 0:
                        process.kill()
                        partial, _ = process.communicate()
                        output = partial or output
                        if output:
                            self.events.put(('log', output))
                        raise RuntimeError('Docker command timed out after ' + str(round(timeout, 1)) +
                                           ' seconds: ' + command +
                                           ('\nOutput: ' + output.strip()[-1800:] if output.strip() else '\nNo response from Docker.'))
                    try:
                        output, _ = process.communicate(timeout=min(10.0, remaining))
                        code = process.returncode
                        break
                    except subprocess.TimeoutExpired:
                        elapsed = time.monotonic() - started
                        self.events.put(('status', 'Waiting for Docker (' + str(int(elapsed)) +
                                         ' seconds): ' + ' '.join(args[1:3])))
                if output:
                    self.events.put(('log', output))
        finally:
            self._active_process = None
            if process.stdout:
                process.stdout.close()
        self.events.put(('log', 'Exit code: ' + str(code) + '\n'))
        if code and check:
            raise RuntimeError('Docker command returned exit code ' + str(code) + ': ' + command +
                               ('\n' + output.strip()[-1800:] if output.strip() else ''))
        return code

    def _archive_for(self, config):
        archive = str(config.get('source_tar') or '').strip()
        if archive and Path(archive).is_file():
            return archive
        state = self.app.state
        image = config['image']
        if image == str(state.get('base_image') or '').strip():
            candidate = str(state.get('runtime_base_archive') or '').strip()
            if candidate and Path(candidate).is_file():
                return candidate
        if image in (str(state.get('built_image') or '').strip(), str(state.get('image_name') or '').strip()):
            candidate = str(state.get('last_full_image_tar') or '').strip()
            if candidate and Path(candidate).is_file():
                return candidate
        return ''

    def _ensure_image_loaded(self, config):
        image = config['image']
        image_id = docker_image_id(image)
        if image_id:
            return image_id
        archive = self._archive_for(config)
        if not archive:
            raise RuntimeError('Docker image is not loaded and no saved TAR was found for ' + image +
                               '. Select the TAR in Tab 9 to import it.')
        self.events.put(('log', 'Loading image from TAR before creating the container: ' + archive + '\n'))
        self._run(['docker', 'load', '-i', archive], timeout=1200)
        image_id = docker_image_id(image)
        if not image_id:
            raise RuntimeError('The TAR loaded, but did not provide the selected image tag: ' + image +
                               '. Choose the tag reported by Docker.')
        return image_id

    def _remove_image_if_unused(self, image, expected_id=''):
        image = str(image or '').strip()
        if not image:
            return 'NO IMAGE SELECTED'
        current_id = docker_image_id(image)
        if not current_id:
            return 'IMAGE ALREADY UNLOADED: ' + image
        if expected_id and current_id != expected_id:
            return 'IMAGE CHANGED: retained ' + image + ' because its image ID differs from the session image'
        self.events.put(('log', 'Removing the selected Docker image (the saved TAR is unchanged): ' + image + '\n'))
        try:
            self._run(['docker', 'image', 'rm', image], timeout=180)
        except RuntimeError as exc:
            return 'IMAGE RETAINED: ' + image + ' | ' + str(exc)
        return 'IMAGE UNLOADED: ' + image

    def _remove_existing_session(self, name, replacement_image=''):
        existing = inspect_container(name)
        if not existing:
            return ''
        if not is_managed_container(existing):
            raise RuntimeError('A container named ' + name + ' already exists but was not created by Tab 9. '
                               'Choose another name or remove the unrelated container manually.')
        old_image = str((existing.get('Config') or {}).get('Image') or '').strip()
        old_id = str(existing.get('Image') or '').strip()
        if (existing.get('State') or {}).get('Status') == 'running':
            self._run(['docker', 'stop', '--time', '5', name], timeout=120)
        self._run(['docker', 'rm', name], timeout=120)
        self.events.put(('log', 'Removed previous Tab 9 container: ' + name + '\n'))
        if old_image and old_image != replacement_image:
            self.events.put(('log', self._remove_image_if_unused(old_image, old_id) + '\n'))
        return old_image

    def start_container(self, automatic=False, open_after_start=False):
        try:
            config = validate_config(self._config())
            if config['mount_enabled'] and not Path(config['host_folder']).is_dir():
                raise ValueError('Windows mount folder does not exist: ' + config['host_folder'])
        except ValueError as exc:
            messagebox.showerror('Start Container', str(exc), parent=self)
            return
        selected_base = str(self.app.state.get('base_image') or '').strip()
        final_tag = str(self.app.state.get('built_image') or self.app.state.get('image_name') or '').strip()
        if not automatic and selected_base and config['image'] == selected_base and config['image'] != final_tag:
            if not messagebox.askyesno('Runtime base image selected',
                    'You selected a runtime BASE checkpoint:\n\n' + config['image'] +
                    ('\n\nYour assembled image is ' + final_tag + '.' if final_tag else '\n\nNo assembled image has been selected.') +
                    ' The base may not contain your selected components.\n\nStart the selected base anyway?', parent=self):
                return
        self.app.state['container_config'] = config

        def action():
            current = dict(config)
            self._remove_existing_session(current['name'], replacement_image=current['image'])
            image_id = self._ensure_image_loaded(current)
            args = create_container_args(current)
            self.events.put(('log', 'Creating a fresh container with the CURRENT Windows mount settings...\n'))
            try:
                self._run(args, timeout=240)
                self._run(['docker', 'start', current['name']], timeout=180)
            except Exception as exc:
                failed = inspect_container(current['name'])
                if failed and is_managed_container(failed):
                    try:
                        self._run(['docker', 'rm', '-f', current['name']], timeout=120)
                    except Exception:
                        pass
                self.events.put(('log', self._remove_image_if_unused(current['image'], image_id) + '\n'))
                raise RuntimeError(mount_error_guidance(exc, current['host_folder'])) from exc
            self.events.put(('session_started', current['image'], image_id))
            if open_after_start:
                self.events.put(('launch_terminal',))
            return ('RUNNING: ' + current['name'] + ' | Fresh container | ' +
                    (current['host_folder'] + ' → ' + current['mount_point'] if current['mount_enabled'] else 'No Windows folder mounted'))

        self._work('Start new Docker container', action)

    def open_terminal(self):
        name = self.name.get().strip()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
            messagebox.showerror('Interactive terminal', 'Enter a valid container name.', parent=self)
            return
        workdir = self.workdir.get().strip() or '/'
        if not workdir.startswith('/') or '\\' in workdir or any(p == '..' for p in workdir.split('/')):
            messagebox.showerror('Interactive terminal', 'Enter a valid absolute Linux working directory.', parent=self)
            return
        if os.name != 'nt':
            messagebox.showerror('Interactive terminal',
                                 'This GUI terminal launcher requires Windows. Run docker exec -it from a terminal on other systems.',
                                 parent=self)
            return

        def action():
            existing = inspect_container(name)
            if not existing or (existing.get('State') or {}).get('Status') != 'running':
                raise RuntimeError('Container is not running. Select a Docker image to start it first.')
            probe = subprocess.run(['docker', 'exec', name, '/bin/sh', '-c', 'command -v bash'],
                                   capture_output=True, text=True, errors='replace', timeout=15,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            shell = 'bash' if probe.returncode == 0 else '/bin/sh'
            command = ['docker', 'exec', '-it', '--workdir', workdir, name, shell]
            self.events.put(('log', 'Opening a real interactive terminal: $ ' +
                             subprocess.list2cmdline(command) + '\n'))
            flags = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0)
            subprocess.Popen(command, creationflags=flags)
            return 'INTERACTIVE TERMINAL LAUNCHED: ' + name + ' | Shell: ' + shell

        self._work('Open container terminal', action)

    def diagnose_docker(self):
        image = self.image.get().strip()
        host_folder = self.host_folder.get().strip()
        mount_point = self.mount_point.get().strip()
        if not image:
            messagebox.showerror('Docker diagnostics', 'Select a Docker image first.', parent=self)
            return
        if self.mount_enabled.get() and (not host_folder or not Path(host_folder).is_dir()):
            messagebox.showerror('Docker diagnostics', 'Select an existing Windows data folder first, or disable Windows folder mounting.', parent=self)
            return
        if not mount_point.startswith('/') or '\\' in mount_point or ',' in mount_point:
            messagebox.showerror('Docker diagnostics', 'Enter a valid absolute Linux mount path.', parent=self)
            return

        def action():
            self.events.put(('log', 'CHECK 1/4 — Docker Desktop engine response\n'))
            self._run(['docker', 'info', '--format', '{{.ServerVersion}}'], timeout=12)
            self.events.put(('log', 'CHECK 2/4 — Selected local Docker image\n'))
            self._run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], timeout=15)
            self.events.put(('log', 'CHECK 3/4 — Can this image run WITHOUT mounting Windows files?\n'))
            self._run(['docker', 'run', '--rm', '--pull', 'never', '--network', 'none',
                       '--entrypoint', '/bin/sh', image, '-c', 'echo CONTAINER_NO_MOUNT_OK'], timeout=35)
            if self.mount_enabled.get():
                self.events.put(('log', 'CHECK 4/4 — Can Docker mount the selected Windows directory?\n'))
                mount = 'type=bind,source=' + host_folder + ',target=' + mount_point + ',readonly'
                try:
                    self._run(['docker', 'run', '--rm', '--pull', 'never', '--network', 'none',
                               '--mount', mount, '--entrypoint', '/bin/sh', image, '-c',
                               'test -d ' + shlex.quote(posixpath.normpath(mount_point)) + ' && echo WINDOWS_MOUNT_OK'], timeout=35)
                except RuntimeError as exc:
                    raise RuntimeError(mount_error_guidance(exc, host_folder)) from exc
                self.events.put(('log', 'ALL FOUR DIAGNOSTIC CHECKS PASSED.\n'))
                return 'DOCKER ENGINE AND WINDOWS FOLDER MOUNT: WORKING.'
            self.events.put(('log', 'CHECK 4/4 — Skipped: Windows folder mounting disabled.\n'))
            return 'DOCKER ENGINE AND IMAGE: WORKING (NO WINDOWS MOUNT).' 

        self._work('Diagnose Docker Desktop and Windows file sharing', action)

    def check_container(self):
        name = self.name.get().strip()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
            messagebox.showerror('Container', 'Enter a valid container name.', parent=self)
            return

        def action():
            result = inspect_container(name)
            if not result:
                return 'NOT FOUND: ' + name + ' | Click Create / Start Container.'
            status = (result.get('State') or {}).get('Status', 'unknown').upper()
            image = (result.get('Config') or {}).get('Image', '')
            self.events.put(('log', 'Container: ' + name + '\nStatus: ' + status + '\nImage: ' + image + '\n'))
            for mount in result.get('Mounts', []):
                if mount.get('Type') == 'bind':
                    self.events.put(('log', 'Windows mount: ' + str(mount.get('Source', '')) +
                                     ' → ' + str(mount.get('Destination', '')) +
                                     (' (read-only)' if not mount.get('RW', True) else ' (read/write)') + '\n'))
            return status + ': ' + name + ' | Image: ' + image

        self._work('Inspect container', action)

    def stop_container(self):
        name = self.name.get().strip()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
            messagebox.showerror('Stop Container', 'Enter a valid container name.', parent=self)
            return
        image = self.image.get().strip()
        session_id = self._session_image_id if self._session_image_tag == image else ''

        def action():
            existing = inspect_container(name)
            if existing:
                if not is_managed_container(existing):
                    raise RuntimeError('The container ' + name + ' was not created by Tab 9. No Docker resources were deleted.')
                image_name = str((existing.get('Config') or {}).get('Image') or image).strip()
                image_id = str(existing.get('Image') or '').strip()
                if (existing.get('State') or {}).get('Status') == 'running':
                    self._run(['docker', 'stop', '--time', '5', name], timeout=120)
                self._run(['docker', 'rm', name], timeout=120)
                self.events.put(('log', 'Container removed: ' + name + '\n'))
            else:
                image_name = image if session_id else ''
                image_id = session_id
            cleanup = self._remove_image_if_unused(image_name, image_id)
            self.events.put(('session_stopped',))
            return 'CONTAINER STOPPED AND REMOVED: ' + name + ' | ' + cleanup + ' | Original TAR preserved.'

        self._work('Stop container, remove it and unload its Docker image', action)

    def remove_container(self):
        self.stop_container()
