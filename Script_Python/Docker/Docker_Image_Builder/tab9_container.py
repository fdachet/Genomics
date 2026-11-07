import json
import ntpath
import posixpath
import queue
import re
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


EXAMPLES = (
    'ls -lah /data',
    'bedtools --version',
    'bedtools --help',
    'samtools',
    'STAR --help',
    'java -version',
    'java -jar /opt/picard/picard.jar',
    'blat',
    'bedtools sort -i /data/regions.bed > /data/regions.sorted.bed',
)


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
    if not source or not (ntpath.isabs(source) or Path(source).is_absolute()):
        raise ValueError('Choose an existing absolute Windows folder to mount.')
    if ',' in source or '\n' in source or '\r' in source:
        raise ValueError('Choose a mount folder without a comma or newline in its path.')
    for value, label in ((target, 'Container mount path'), (workdir, 'Working directory')):
        if not value.startswith('/') or '\\' in value or ',' in value or any(part == '..' for part in value.split('/')):
            raise ValueError(label + ' must be an absolute Linux path without commas or .. segments.')
        if '\n' in value or '\r' in value:
            raise ValueError(label + ' cannot contain line breaks.')
    if target == '/':
        raise ValueError('Do not mount over the container root filesystem. Use /data or another folder.')
    return {'image': image, 'name': name, 'host_folder': source, 'mount_point': posixpath.normpath(target),
            'workdir': posixpath.normpath(workdir), 'network': bool(config.get('network')),
            'read_only': bool(config.get('read_only')),
            'command': str(config.get('command', '') or '')}


def create_container_args(config):
    data = validate_config(config)
    mount = 'type=bind,source=' + data['host_folder'] + ',target=' + data['mount_point']
    if data['read_only']:
        mount += ',readonly'
    return ['docker', 'run', '--pull', 'never', '--detach', '--name', data['name'], '--mount', mount,
            '--workdir', data['workdir'], '--network', 'bridge' if data['network'] else 'none',
            '--entrypoint', '/bin/sh', data['image'], '-c', 'while :; do sleep 3600; done']


def inspect_container(name):
    process = subprocess.run(['docker', 'container', 'inspect', name], capture_output=True,
                             text=True, errors='replace', timeout=20,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if process.returncode:
        return None
    data = json.loads(process.stdout)
    return data[0] if data else None


def list_docker_images():
    process = subprocess.run(['docker', 'image', 'ls', '--format', '{{json .}}'], capture_output=True,
                             text=True, errors='replace', timeout=35,
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
    result.sort(key=lambda image: (image['name'] != 'component-toolbox:latest', image['name'].lower()))
    return result


class ContainerTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg='#EAF3FA')
        self.app = app
        self.events = queue.Queue()
        self.busy = False
        self._active_process = None
        self.name = tk.StringVar(value='bioinformatics')
        self.image = tk.StringVar()
        self.host_folder = tk.StringVar()
        self.mount_point = tk.StringVar(value='/data')
        self.workdir = tk.StringVar(value='/data')
        self.network = tk.BooleanVar(value=False)
        self.read_only = tk.BooleanVar(value=False)
        self.preset = tk.StringVar(value=EXAMPLES[0])
        self.status = tk.StringVar(value='Select the built image and a Windows folder to begin.')
        self._render()
        self.refresh_from_project_state()
        self.after(100, self._drain)

    def _render(self):
        banner = tk.Frame(self, bg='#196A8D', padx=18, pady=13)
        banner.pack(fill='x', padx=3, pady=(3, 0))
        tk.Label(banner, text='9 — RUN SOFTWARE INSIDE A DOCKER CONTAINER', bg='#196A8D',
                 fg='white', font=('Segoe UI', 16, 'bold')).pack(anchor='w')
        tk.Label(self, text='Run Linux programs from this GUI. Your Windows data folder is accessible inside the container without copying files.',
                 bg='#D9EDF8', fg='#22536D', font=('Segoe UI', 10), anchor='w', padx=14, pady=9).pack(fill='x', padx=3)

        settings = tk.LabelFrame(self, text='Docker image, container and Windows folder mount',
                                 bg='#EAF3FA', fg='#22536D', padx=12, pady=10,
                                 font=('Segoe UI', 10, 'bold'))
        settings.pack(fill='x', padx=17, pady=(10, 5))
        settings.grid_columnconfigure(1, weight=1)

        self._field(settings, 0, 'Final Docker image:', self.image)
        image_actions = tk.Frame(settings, bg='#EAF3FA')
        image_actions.grid(row=0, column=2, padx=5, pady=4, sticky='w')
        tk.Button(image_actions, text='Browse Docker Images', command=self.browse_images,
                  bg='#ABDDE6').pack(side='left', padx=(0, 5))
        tk.Button(image_actions, text='Browse TAR...', command=self.browse_tar,
                  bg='#ABDDE6').pack(side='left', padx=(0, 5))
        tk.Button(image_actions, text='From Tab 6', command=self.use_final_image,
                  bg='#ABDDE6').pack(side='left')
        self._field(settings, 1, 'Container name:', self.name)
        self._field(settings, 2, 'Windows DATA folder to mount:', self.host_folder)
        tk.Button(settings, text='Browse...', command=self.browse, bg='#ABDDE6').grid(row=2, column=2, padx=5, pady=4)
        self._field(settings, 3, 'Folder inside Linux:', self.mount_point)
        self._field(settings, 4, 'Linux working directory:', self.workdir)

        options = tk.Frame(settings, bg='#EAF3FA')
        options.grid(row=5, column=1, columnspan=2, sticky='w', pady=(6, 1))
        tk.Checkbutton(options, text='Enable container network (default: offline)', variable=self.network,
                       bg='#EAF3FA').pack(side='left', padx=(0, 18))
        tk.Checkbutton(options, text='Mount Windows folder read-only', variable=self.read_only,
                       bg='#EAF3FA').pack(side='left')

        controls = tk.Frame(self, bg='#EAF3FA')
        controls.pack(fill='x', padx=17, pady=7)
        self.start_button = self._button(controls, 'Create / Start Container', self.start_container, '#1D9D78')
        self._button(controls, 'Check Container', self.check_container, '#4B9EC9')
        self._button(controls, 'Stop Container', self.stop_container, '#D88755')
        self._button(controls, 'Remove Stopped Container', self.remove_container, '#BE6666')
        self._button(controls, 'Save Settings', self.save_settings, '#AED6F1')

        status_box = tk.Frame(self, bg='#D8EFF0', padx=12, pady=8)
        status_box.pack(fill='x', padx=17)
        tk.Label(status_box, textvariable=self.status, bg='#D8EFF0', fg='#155B62',
                 font=('Segoe UI', 10, 'bold'), anchor='w', wraplength=1350).pack(fill='x')

        command_box = tk.LabelFrame(self, text='Run any Linux command inside the container',
                                    bg='#EAF3FA', fg='#22536D', padx=12, pady=10,
                                    font=('Segoe UI', 10, 'bold'))
        command_box.pack(fill='x', padx=17, pady=(10, 7))
        tk.Label(command_box, text='Examples:', bg='#EAF3FA').pack(anchor='w')
        choices = ttk.Combobox(command_box, textvariable=self.preset, values=EXAMPLES, state='readonly')
        choices.pack(fill='x', pady=(2, 7))
        choices.bind('<<ComboboxSelected>>', self.choose_example)
        tk.Label(command_box, text='Command (editable; /data refers to the mounted Windows folder):',
                 bg='#EAF3FA').pack(anchor='w')
        self.command_editor = tk.Text(command_box, height=3, wrap='word', font=('Consolas', 11))
        self.command_editor.pack(fill='x', pady=(2, 6))
        self.command_editor.insert('1.0', EXAMPLES[0])
        row = tk.Frame(command_box, bg='#EAF3FA')
        row.pack(fill='x')
        self.run_button = self._button(row, 'Run Command', self.run_command, '#20A878')
        self._button(row, 'List Mounted Files', lambda: self.run_command('ls -lah ' + self.mount_point.get().strip()), '#79C6DC')
        self._button(row, 'Clear Output', self.clear_log, '#C1CAD2')
        tk.Label(row, text='Outputs saved under the mounted folder remain on Windows.',
                 bg='#EAF3FA', fg='#486E80').pack(side='right', padx=8)

        logframe = tk.LabelFrame(self, text='Live Docker command output', bg='#EAF3FA',
                                 fg='#22536D', padx=9, pady=8, font=('Segoe UI', 10, 'bold'))
        logframe.pack(fill='both', expand=True, padx=17, pady=(2, 13))
        scroll = ttk.Scrollbar(logframe)
        scroll.pack(side='right', fill='y')
        self.log = tk.Text(logframe, font=('Consolas', 10), wrap='word', yscrollcommand=scroll.set,
                           bg='#FBFEFF', fg='#17324D')
        self.log.pack(side='left', fill='both', expand=True)
        scroll.config(command=self.log.yview)
        self.log.insert('end', 'Create a container, then select or enter a command and click Run Command.\n')

    def _field(self, parent, row, label, variable):
        tk.Label(parent, text=label, bg='#EAF3FA', anchor='w', width=26,
                 font=('Segoe UI', 10, 'bold')).grid(row=row, column=0, sticky='w', padx=(0, 8), pady=4)
        tk.Entry(parent, textvariable=variable, font=('Consolas', 10)).grid(row=row, column=1, sticky='ew', pady=4)

    def _button(self, parent, label, action, color):
        button = tk.Button(parent, text=label, command=action, bg=color, fg='#17202A',
                           font=('Segoe UI', 10), padx=8, pady=5)
        button.pack(side='left', padx=(0, 8))
        return button

    def choose_example(self, event=None):
        self.command_editor.delete('1.0', 'end')
        self.command_editor.insert('1.0', self.preset.get())

    def use_final_image(self):
        image = str(self.app.state.get('built_image') or self.app.state.get('image_name') or '').strip()
        if image:
            self.image.set(image)
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
            self.status.set('SELECTED DOCKER IMAGE: ' + tag + ' | Click Create / Start Container.')
            window.destroy()

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
        if not messagebox.askyesno('Load image into Docker Desktop',
                'Import the selected Docker image archive into Docker Desktop?\n\n' + str(archive) +
                '\n\nThis does not start a container or modify the archive.', parent=self):
            return

        def action():
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
            tags = list(dict.fromkeys(match.strip() for match in re.findall(r'^Loaded image:\s*(.+)$',
                                                                                ''.join(output), flags=re.MULTILINE)))
            if len(tags) == 1:
                self.events.put(('image_selected', tags[0]))
                return 'LOADED AND SELECTED: ' + tags[0] + ' | Click Create / Start Container.'
            self.events.put(('images', list_docker_images()))
            return 'IMAGE LOADED: Choose its tag from the Docker Desktop image list.'

        self._work('Load image archive: ' + archive.name, action)

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
                'read_only': self.read_only.get(),
                'command': self.command_editor.get('1.0', 'end').strip()}

    def save_settings(self):
        try:
            data = validate_config(self._config())
        except ValueError as exc:
            messagebox.showerror('Container settings', str(exc), parent=self)
            return False
        self.app.state['container_config'] = data
        self.status.set('Container settings stored in project state; use Save project JSON in Tab 1 to write them to disk.')
        return True

    def refresh_from_project_state(self):
        data = self.app.state.get('container_config') or {}
        if not isinstance(data, dict):
            data = {}
        default_image = str(self.app.state.get('built_image') or self.app.state.get('image_name') or '').strip()
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
        self.read_only.set(bool(data.get('read_only', False)))
        if data.get('command'):
            self.command_editor.delete('1.0', 'end')
            self.command_editor.insert('1.0', str(data['command']))

    def _append(self, value):
        self.log.insert('end', str(value))
        if float(self.log.index('end-1c').split('.')[0]) > 6000:
            self.log.delete('1.0', '2001.0')
        self.log.see('end')

    def clear_log(self):
        self.log.delete('1.0', 'end')

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
                elif item[0] == 'done':
                    self.busy = False
                    self.start_button.config(state='normal')
                    self.run_button.config(state='normal')
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._drain)

    def _work(self, label, action):
        if self.busy:
            messagebox.showinfo('Container', 'A Docker operation is already running. Wait for it to finish, or use Stop Container.', parent=self)
            return
        self.busy = True
        self.start_button.config(state='disabled')
        self.run_button.config(state='disabled')
        self.events.put(('log', '\n=== ' + label + ' ===\n'))
        self.events.put(('status', label + ' ...'))

        def worker():
            try:
                result = action()
                if result:
                    self.events.put(('status', str(result)))
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                self.events.put(('log', 'ERROR: ' + str(exc) + '\n'))
                self.events.put(('status', 'ERROR: ' + str(exc)))
            finally:
                self.events.put(('done',))

        threading.Thread(target=worker, daemon=True).start()

    def _run(self, args, timeout=None, check=True):
        self.events.put(('log', '$ ' + subprocess.list2cmdline(args) + '\n'))
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, errors='replace',
                                   bufsize=1, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self._active_process = process
        try:
            for line in process.stdout:
                self.events.put(('log', line))
            code = process.wait(timeout=timeout)
        finally:
            self._active_process = None
            if process.stdout:
                process.stdout.close()
        self.events.put(('log', 'Exit code: ' + str(code) + '\n'))
        if code and check:
            raise RuntimeError('Docker command returned exit code ' + str(code))
        return code

    def start_container(self):
        try:
            config = validate_config(self._config())
            if not Path(config['host_folder']).is_dir():
                raise ValueError('Windows mount folder does not exist: ' + config['host_folder'])
            args = create_container_args(config)
        except ValueError as exc:
            messagebox.showerror('Start Container', str(exc), parent=self)
            return
        self.app.state['container_config'] = config

        def action():
            existing = inspect_container(config['name'])
            if existing:
                status = (existing.get('State') or {}).get('Status', '')
                original_image = (existing.get('Config') or {}).get('Image', '')
                if original_image != config['image']:
                    raise RuntimeError('An existing container with this name uses image ' + original_image + '. Stop and remove it, or choose another container name.')
                image_check = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', config['image']],
                                             capture_output=True, text=True, errors='replace', timeout=20,
                                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if image_check.returncode:
                    raise RuntimeError('The selected image is not available in Docker Desktop: ' + config['image'])
                if str(existing.get('Image', '')).strip() != image_check.stdout.strip():
                    raise RuntimeError('This container uses an older build of ' + config['image'] + '. Stop and remove the container, then create it again to use the updated image.')
                if status == 'running':
                    self.events.put(('log', 'Using the existing running container. Existing mount settings are unchanged.\n'))
                    return 'RUNNING: ' + config['name']
                self._run(['docker', 'start', config['name']])
                self.events.put(('log', 'Existing mounts are reused. Remove the stopped container to change its mounts.\n'))
                return 'RUNNING: ' + config['name']
            self._run(args)
            return 'RUNNING: ' + config['name'] + ' | ' + config['host_folder'] + ' → ' + config['mount_point']

        self._work('Start container', action)

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

    def run_command(self, command_override=None):
        name = self.name.get().strip()
        command = command_override if isinstance(command_override, str) else self.command_editor.get('1.0', 'end').strip()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
            messagebox.showerror('Run Command', 'Enter a valid container name.', parent=self)
            return
        if not command or '\x00' in command:
            messagebox.showerror('Run Command', 'Enter a Linux command to run.', parent=self)
            return
        workdir = self.workdir.get().strip() or '/data'
        if not workdir.startswith('/') or '\\' in workdir:
            messagebox.showerror('Run Command', 'Enter a valid absolute Linux working directory.', parent=self)
            return
        if command_override is None:
            data = self._config()
            self.app.state['container_config'] = data

        def action():
            existing = inspect_container(name)
            if not existing or (existing.get('State') or {}).get('Status') != 'running':
                raise RuntimeError('Container is not running. Click Create / Start Container first.')
            code = self._run(['docker', 'exec', '--workdir', workdir, name, '/bin/sh', '-c', command], check=False)
            return ('COMMAND COMPLETED' if code == 0 else 'COMMAND FINISHED WITH NONZERO EXIT CODE ' + str(code)) + ': ' + name

        self._work('Run in ' + name + ': ' + command, action)

    def stop_container(self):
        name = self.name.get().strip()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
            messagebox.showerror('Stop Container', 'Enter a valid container name.', parent=self)
            return

        def worker():
            try:
                existing = inspect_container(name)
                if not existing:
                    self.events.put(('status', 'NOT FOUND: ' + name))
                    return
                if (existing.get('State') or {}).get('Status') != 'running':
                    self.events.put(('status', 'ALREADY STOPPED: ' + name))
                    return
                self.events.put(('log', '\nStopping container ' + name + ' ...\n'))
                process = subprocess.run(['docker', 'stop', '--time', '5', name], capture_output=True,
                                         text=True, errors='replace', timeout=35,
                                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                self.events.put(('log', (process.stdout or '') + (process.stderr or '') + '\n'))
                self.events.put(('status', ('STOPPED: ' if process.returncode == 0 else 'STOP FAILED: ') + name))
            except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
                self.events.put(('status', 'ERROR: ' + str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def remove_container(self):
        name = self.name.get().strip()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
            messagebox.showerror('Remove Container', 'Enter a valid container name.', parent=self)
            return
        if not messagebox.askyesno('Remove stopped container',
                'Remove the stopped container "' + name + '"?\n\nChanges saved only inside that container will be lost. Windows files in the mounted folder and the Docker image will be preserved.', parent=self):
            return

        def action():
            self._run(['docker', 'rm', name])
            return 'REMOVED CONTAINER: ' + name + ' | Docker image and mounted Windows files preserved.'

        self._work('Remove stopped container', action)
