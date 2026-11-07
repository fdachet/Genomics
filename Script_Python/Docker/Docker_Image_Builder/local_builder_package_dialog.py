import copy
import json
import queue
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from local_builder_package_install import install_local_packages_in_builder, preflight_local_builder_packages
from docker_image_checkpoint import checkpoint_sidecar_path, read_checkpoint_metadata, save_image_checkpoint
from project_state import effective_builder_image


def publish_local_package_install(state, result, role, also_other, origin='local'):
    if role not in ('builder', 'runtime'):
        raise ValueError('Unknown package installation target.')
    original_runtime = str(state.get('base_image') or '').strip()
    original_builder = effective_builder_image(state)
    source = str(result.get('source_image') or result['builder_from']).strip()
    new_image = str(result.get('installed_image') or result['builder_image']).strip()
    if source != (original_builder if role == 'builder' else original_runtime):
        raise RuntimeError('The selected ' + role + ' changed while Docker was installing packages. '
                           'The newly created image was preserved but the project selection was not overwritten.')
    if also_other and original_runtime != original_builder:
        raise RuntimeError('Builder and runtime no longer refer to the same starting image. '
                           'Select and install each independently.')
    original_runtime_archive = str(state.get('runtime_base_archive') or '')
    original_builder_archive = str(state.get('builder_base_archive') or '')
    builder_was_implicit = not (str(state.get('builder_image') or '').strip() or original_builder_archive.strip())
    if role == 'builder':
        prior_inventory = state.get('builder_inventory') or {}
        if not prior_inventory and source == original_runtime:
            prior_inventory = state.get('base_inventory') or {}
        prior_system = state.get('builder_system') or state.get('base_system') or {}
    else:
        prior_inventory = state.get('base_inventory') or {}
        prior_system = state.get('base_system') or {}
    inventory = copy.deepcopy(prior_inventory)
    if not isinstance(inventory, dict):
        inventory = {}
    packages_section = inventory.setdefault('packages', {})
    if not isinstance(packages_section, dict):
        packages_section = {}
        inventory['packages'] = packages_section
    records = list(packages_section.get('os') or [])
    for package in result['packages']:
        records = [entry for entry in records if not (isinstance(entry, dict) and
                   str(entry.get('name') or '').lower() == package['name'].lower())]
        records.append({'name': package['name'], 'version': package['version'],
                        'architecture': package['architecture'], 'status': 'INSTALLED',
                        'origin': origin.upper() + ' ' + role.upper() + ' INSTALL'})
    packages_section['os'] = records
    system = dict(prior_system) if isinstance(prior_system, dict) else {}
    if not system:
        info = result['builder_info']
        system = {'os': info.get('pretty_name', ''), 'architecture': info.get('arch', ''),
                  'distribution': info.get('id', ''), 'version': info.get('version_id', '')}
    if role == 'builder':
        changes = {'builder_image': new_image, 'builder_base_archive': '',
                   'builder_inventory': inventory, 'builder_system': system}
        if also_other:
            changes.update({'base_image': new_image, 'runtime_base_archive': '',
                            'base_inventory': copy.deepcopy(inventory), 'base_system': dict(system)})
    else:
        changes = {'base_image': new_image, 'runtime_base_archive': '',
                   'base_inventory': inventory, 'base_system': system}
        if also_other:
            changes.update({'builder_image': new_image, 'builder_base_archive': '',
                            'builder_inventory': copy.deepcopy(inventory), 'builder_system': dict(system)})
        elif builder_was_implicit and original_builder == original_runtime:
            changes.update({'builder_image': original_builder, 'builder_base_archive': '',
                            'builder_inventory': copy.deepcopy(prior_inventory),
                            'builder_system': dict(prior_system) if isinstance(prior_system, dict) else {}})
    key = (origin + '_builder_installs') if role == 'builder' else (origin + '_runtime_installs')
    history = list(state.get(key) or [])
    history.append({'source_image': source, 'installed_image': new_image,
                    'builder_from': source if role == 'builder' else original_builder,
                    'builder_image': new_image if role == 'builder' or also_other else original_builder,
                    'also_runtime': bool(also_other) if role == 'builder' else True,
                    'previous_runtime_image': original_runtime,
                    'previous_runtime_archive': original_runtime_archive,
                    'previous_builder_image': original_builder,
                    'previous_builder_archive': original_builder_archive,
                    'also_other': bool(also_other), 'role': role, 'network': str(result.get('network') or 'offline'),
                    'saved_tar': str(result.get('saved_tar') or ''),
                    'custom_command': str(result.get('custom_command') or ''),
                    'verification': result['verification'], 'packages': result['packages']})
    changes[key] = history
    state.update(changes)
    return new_image


class LocalBuilderPackageDialog(tk.Toplevel):
    def __init__(self, parent, app, initial_files=None, on_complete=None, target='builder'):
        super().__init__(parent)
        if target not in ('builder', 'runtime'):
            raise ValueError('Choose builder or runtime as the installation target.')
        self.app = app
        self.target_role = target
        self.on_complete = on_complete
        self.files = []
        self.messages = queue.Queue()
        self.cancel_event = threading.Event()
        self.busy = False
        self.builder = effective_builder_image(app.state)
        self.runtime = str(app.state.get('base_image') or '').strip()
        self.source = self.builder if target == 'builder' else self.runtime
        self.share_option_available = bool(self.builder and self.builder == self.runtime)
        self.builder_caption = tk.StringVar(value='Current builder: ' + (self.builder or 'NOT SELECTED'))
        self.runtime_caption = tk.StringVar(value='Current runtime: ' + (self.runtime or 'NOT SELECTED'))
        self.also_other = tk.BooleanVar(value=False)
        self.save_image_tar = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value='Choose the local packages to install in the selected ' + target + '.')
        self.title('Install local package into ' + target)
        self.geometry('940x635')
        self.minsize(730, 490)
        self.configure(bg='#E8F8F5')
        self.transient(parent.winfo_toplevel())
        self.protocol('WM_DELETE_WINDOW', self._close)

        tk.Label(self, text='INSTALL LOCAL PACKAGE INTO ' + target.upper(), bg='#117864', fg='white',
                 font=('Segoe UI', 15, 'bold'), anchor='w', padx=16, pady=12).pack(fill='x')
        details = tk.Frame(self, bg='#E8F8F5')
        details.pack(fill='x', padx=16, pady=(12, 5))
        tk.Label(details, textvariable=self.builder_caption, bg='#E8F8F5',
                 anchor='w', font=('Segoe UI', 10, 'bold')).pack(fill='x')
        tk.Label(details, textvariable=self.runtime_caption,
                 bg='#E8F8F5', anchor='w').pack(fill='x')
        self.relationship_text = tk.StringVar()
        self._refresh_relationship_text()
        tk.Label(details, textvariable=self.relationship_text, bg='#E8F8F5', fg='#21618C', anchor='w',
                 wraplength=880, justify='left').pack(fill='x', pady=(3, 0))

        file_header = tk.Frame(self, bg='#E8F8F5')
        file_header.pack(fill='x', padx=16, pady=(8, 3))
        tk.Label(file_header, text='Selected Linux package archives (.deb, .rpm, .apk):',
                 bg='#E8F8F5', font=('Segoe UI', 10, 'bold')).pack(side='left')
        self.add_button = tk.Button(file_header, text='Browse package file(s)', bg='#48C9B0', command=self._browse)
        self.add_button.pack(side='right', padx=(6, 0))
        self.remove_button = tk.Button(file_header, text='Remove selected', command=self._remove)
        self.remove_button.pack(side='right', padx=4)
        holder = tk.Frame(self)
        holder.pack(fill='both', expand=True, padx=16, pady=(0, 8))
        self.listbox = tk.Listbox(holder, selectmode='extended', height=7, font=('Consolas', 10))
        scroll = ttk.Scrollbar(holder, orient='vertical', command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')

        option_frame = tk.Frame(self, bg='#E8F8F5')
        option_frame.pack(fill='x', padx=16)
        alternate = 'runtime base' if target == 'builder' else 'builder'
        self.both_checkbox = tk.Checkbutton(option_frame, text='Also use the new image as the ' + alternate,
                                             variable=self.also_other, bg='#E8F8F5', fg='#0E6655',
                                             state='normal' if self.share_option_available else 'disabled')
        self.both_checkbox.pack(anchor='w')
        self.tar_checkbox = tk.Checkbutton(
            option_frame, text='Save updated Docker image to a reusable TAR file after installation',
            variable=self.save_image_tar, bg='#E8F8F5', fg='#0E6655',
        )
        self.tar_checkbox.pack(anchor='w')
        tk.Label(option_frame, text='Installation is offline. Include any required dependency archives in the selection. '
                 'Click Check dependencies to see what the selected ' + target + ' is missing before installation. '
                 'Package installation scripts execute inside Docker; choose trusted files.',
                 wraplength=880, justify='left', fg='#9C640C', bg='#E8F8F5').pack(fill='x', pady=(4, 6))
        tk.Label(self, textvariable=self.status, bg='#D5F5E3', fg='#0E6655',
                 anchor='w', padx=9, pady=6).pack(fill='x', padx=16)
        self.log = scrolledtext.ScrolledText(self, height=10, bg='white', font=('Consolas', 9))
        self.log.pack(fill='both', expand=True, padx=16, pady=(7, 8))
        actions = tk.Frame(self, bg='#E8F8F5')
        actions.pack(fill='x', padx=16, pady=(0, 12))
        self.check_button = tk.Button(actions, text='Check dependencies',
                                      bg='#3498DB', fg='white', command=self._check_dependencies)
        self.check_button.pack(side='left', padx=(0, 8))
        self.install_button = tk.Button(actions, text='Install selected package(s) into ' + target,
                                        bg='#27AE60', fg='white', command=self._install)
        self.install_button.pack(side='left')
        self.close_button = tk.Button(actions, text='Close', command=self._close)
        self.close_button.pack(side='right')
        if initial_files:
            self._add_files(initial_files)
        if not self.source:
            self.status.set('Select or load a Docker ' + target + ' image in Tab 1 before installing packages.')
            self.install_button.configure(state='disabled')
            self.check_button.configure(state='disabled')
        self.grab_set()
        self.focus_set()

    def _refresh_relationship_text(self):
        if self.share_option_available:
            text = ('Builder and runtime currently use the same image. '
                    'By default, installation updates only the ' + self.target_role + '; you may choose both.')
        else:
            text = ('Builder and runtime use different images. Installation updates only the ' +
                    self.target_role + '; the other image is preserved.')
        self.relationship_text.set(text)

    def _add_files(self, paths):
        for entry in paths:
            path = Path(entry).expanduser()
            if path.is_file() and path.suffix.lower() in ('.deb', '.rpm', '.apk'):
                source = str(path.resolve())
                if source not in self.files:
                    self.files.append(source)
        self._refresh_files()

    def _refresh_files(self):
        self.listbox.delete(0, 'end')
        total = 0
        for path in self.files:
            source = Path(path)
            size = source.stat().st_size if source.is_file() else 0
            total += size
            self.listbox.insert('end', source.name + '    (' + f'{size / 1000000:.2f}' + ' MB)    ' + str(source.parent))
        if not self.busy:
            self.status.set(str(len(self.files)) + ' package archive(s) selected, ' + f'{total / 1000000:.2f}' + ' MB total.')

    def _browse(self):
        paths = filedialog.askopenfilenames(parent=self, title='Select a package and any required dependencies',
                                            filetypes=[('Linux packages', '*.deb *.rpm *.apk'), ('All files', '*.*')])
        if paths:
            self._add_files(paths)

    def _remove(self):
        selected = set(self.listbox.curselection())
        self.files = [path for index, path in enumerate(self.files) if index not in selected]
        self._refresh_files()

    def _append(self, line):
        if not self.winfo_exists():
            return
        self.log.insert('end', str(line).rstrip() + '\n')
        self.log.see('end')

    def _check_dependencies(self):
        if self.busy:
            return
        self.builder = effective_builder_image(self.app.state)
        self.runtime = str(self.app.state.get('base_image') or '').strip()
        self.source = self.builder if self.target_role == 'builder' else self.runtime
        self.share_option_available = bool(self.builder and self.builder == self.runtime)
        if not self.share_option_available:
            self.also_other.set(False)
        if not self.source:
            messagebox.showerror('Image not selected', 'Choose or load a Docker ' + self.target_role + ' in Tab 1.', parent=self)
            return
        if not self.files:
            messagebox.showwarning('No local packages', 'Browse and select a local package archive first.', parent=self)
            return
        self._set_busy(True)
        self.status.set('Checking required packages against the selected ' + self.target_role + '...')
        self._append('DEPENDENCY CHECK: ' + self.source)
        files = list(self.files)
        image = self.source

        def work():
            try:
                result = preflight_local_builder_packages(image, files, self.cancel_event,
                                                          lambda line: self.messages.put(('log', line)))
                self.messages.put(('preflight', result))
            except Exception as exc:
                self.messages.put(('preflight_error', str(exc)))

        threading.Thread(target=work, daemon=True).start()
        self.after(100, self._poll)

    def _set_busy(self, busy):
        self.busy = busy
        self.check_button.configure(state='disabled' if busy or not self.source else 'normal')
        self.install_button.configure(state='disabled' if busy or not self.source else 'normal')
        self.add_button.configure(state='disabled' if busy else 'normal')
        self.remove_button.configure(state='disabled' if busy else 'normal')
        self.both_checkbox.configure(state='disabled' if busy or not self.share_option_available else 'normal')
        self.tar_checkbox.configure(state='disabled' if busy else 'normal')
        self.close_button.configure(text='Stop' if busy else 'Close', command=self._close)
        if busy:
            self.cancel_event.clear()

    def _install(self):
        if self.busy:
            return
        self.builder = effective_builder_image(self.app.state)
        self.runtime = str(self.app.state.get('base_image') or '').strip()
        self.source = self.builder if self.target_role == 'builder' else self.runtime
        self.share_option_available = bool(self.builder and self.builder == self.runtime)
        if not self.share_option_available:
            self.also_other.set(False)
        if not self.source:
            messagebox.showerror('Image not selected', 'Choose or load a Docker ' + self.target_role + ' in Tab 1.', parent=self)
            return
        if not self.files:
            messagebox.showwarning('No local packages', 'Click Browse package file(s) and choose at least one Linux package archive.', parent=self)
            return
        tar_path = ''
        if self.save_image_tar.get():
            initial_dir = str(self.app.state.get('export_image_dir') or self.app.state.get('project_dir') or '').strip()
            if not initial_dir or not Path(initial_dir).is_dir():
                initial_dir = str(Path.cwd())
            suggested = re.sub(r'[^A-Za-z0-9_.-]', '_', self.source) + '_with_local_packages.tar'
            tar_path = filedialog.asksaveasfilename(
                parent=self, title='Choose where to save the updated Docker image TAR',
                initialdir=initial_dir, initialfile=suggested, defaultextension='.tar',
                filetypes=[('Docker image archive', '*.tar')],
            )
            if not tar_path:
                return
        runtime_changes = self.target_role == 'runtime' or self.also_other.get()
        archive_note = ('\n\nThe updated image will also be saved to:\n' + tar_path if tar_path else
                        '\n\nThe updated image will be available through its Docker tag, without a TAR export.')
        shared_note = ('\nThe previous image will stay selected as the builder.'
                       if self.target_role == 'runtime' and not self.also_other.get() and
                       self.builder == self.runtime else '')
        if not messagebox.askyesno('Confirm offline ' + self.target_role + ' installation',
                                   'Install ' + str(len(self.files)) + ' selected local Linux package archive(s) into a new image based on:\n' +
                                   self.source + '\n\nNetwork: DISABLED. Dependencies will be checked first, and missing ones will stop installation before the Docker build.\n' +
                                   'Package authenticity has not been verified; package installation scripts run as root inside Docker.\n\n' +
                                   ('The new image will become BOTH builder and runtime.' if self.also_other.get() else
                                    'The new image will become the ' + self.target_role.upper() + ' ONLY.') +
                                   shared_note + archive_note + '\n\nContinue?', parent=self):
            return
        self._set_busy(True)
        self.status.set('Checking dependencies before installing local packages...')
        files = list(self.files)
        image = self.source
        both = self.also_other.get()
        role = self.target_role

        def work():
            try:
                result = install_local_packages_in_builder(image, files, self.cancel_event,
                                                           lambda line: self.messages.put(('log', line)), role=role)
                tar_error = ''
                if tar_path:
                    self.messages.put(('log', 'Saving the installed Docker image as a reusable TAR...'))
                    try:
                        checkpoint = save_image_checkpoint(
                            result['builder_image'], tar_path, cancel=self.cancel_event,
                            progress=lambda line: self.messages.put(('log', line)),
                        )
                        result['saved_tar'] = checkpoint['archive']
                    except Exception as exc:
                        tar_error = str(exc)
                        self.messages.put(('log', 'TAR EXPORT FAILED: ' + tar_error))
                self.messages.put(('success', (result, both, tar_error)))
            except Exception as exc:
                self.messages.put(('failure', str(exc)))

        threading.Thread(target=work, daemon=True).start()
        self.after(100, self._poll)

    def _poll(self):
        if not self.winfo_exists():
            return
        done = False
        while True:
            try:
                name, data = self.messages.get_nowait()
            except queue.Empty:
                break
            if name == 'log':
                self._append(data)
            elif name == 'preflight':
                missing = data['missing']
                if missing:
                    self.status.set(str(len(missing)) + ' required package(s) are missing or have incompatible versions.')
                    summary = ('The selected ' + self.target_role + ' cannot install these packages offline yet.\n\n' +
                               '\n'.join(item['package'] + ' needs ' + item['requirement'] + ' [' + item['status'] + ']'
                                         for item in missing[:30]) +
                               ('\n...additional requirements are in the log.' if len(missing) > 30 else '') +
                               '\n\nAdd matching dependency .deb files, then check again.')
                    messagebox.showwarning('Missing package dependencies', summary, parent=self)
                else:
                    self.status.set('Dependencies satisfied: selected packages are ready for offline installation.')
                    messagebox.showinfo('Dependencies satisfied',
                                        'All declared Debian dependencies are present in the ' + self.target_role + ' or among the selected local packages.'
                                        if data['packages'][0]['manager'] == 'apt' else
                                        'Package compatibility was checked. Detailed dependency preflight is currently supported for Debian packages.',
                                        parent=self)
                done = True
            elif name == 'preflight_error':
                self._append('DEPENDENCY CHECK FAILED: ' + data)
                self.status.set('Dependency check failed. Review the log.')
                messagebox.showerror('Dependency check failed', data[-3000:], parent=self)
                done = True
            elif name == 'success':
                result, both, tar_error = data
                try:
                    self._publish(result, both)
                    self._append('SUCCESS: updated ' + self.target_role + ' ' + result['builder_image'])
                    self.status.set('Installed and verified ' + str(len(result['packages'])) + ' package(s) in the new ' + self.target_role + '.')
                    messagebox.showinfo(self.target_role.capitalize() + ' updated', 'Packages installed and verified successfully.\n\n' +
                                        'New ' + self.target_role + ': ' + result['builder_image'] + '\n\n' +
                                        ('This image is now used for both builder and runtime.' if both else
                                         'The other image selection was preserved.') +
                                        ('\n\nDocker TAR saved: ' + result['saved_tar'] if result.get('saved_tar') else
                                         '\n\nTAR could not be saved: ' + tar_error if tar_error else
                                         '\n\nNo TAR export selected.') +
                                        '\n\nThe package list is available in Tab 2.', parent=self)
                except Exception as exc:
                    self._append('DOCKER IMAGE CREATED, BUT PROJECT UPDATE FAILED: ' + str(exc))
                    self.status.set('The Docker image was created, but the project could not be updated.')
                    messagebox.showerror('Project update failed', str(exc), parent=self)
                done = True
            elif name == 'failure':
                self._append('INSTALLATION FAILED: ' + data)
                self.status.set('Installation failed. Review the log for missing dependencies or an incompatible package.')
                messagebox.showerror(self.target_role.capitalize() + ' installation failed', data[-3000:], parent=self)
                done = True
        if done:
            self._set_busy(False)
        elif self.busy:
            self.after(100, self._poll)

    def _publish(self, result, both):
        state = self.app.state
        publish_local_package_install(state, result, self.target_role, both)
        saved_tar = str(result.get('saved_tar') or '').strip()
        if saved_tar:
            image = str(result['builder_image'])
            if self.target_role == 'runtime':
                inventory = state.get('base_inventory') or {}
                system = state.get('base_system') or {}
            else:
                inventory = state.get('builder_inventory') or {}
                system = state.get('builder_system') or {}
            metadata = read_checkpoint_metadata(saved_tar)
            metadata['docker_tag'] = image
            metadata['inspection'] = copy.deepcopy(inventory) if isinstance(inventory, dict) else {}
            if isinstance(system, dict) and system:
                metadata['inspection']['system'] = copy.deepcopy(system)
            try:
                checkpoint_sidecar_path(saved_tar).write_text(json.dumps(metadata, indent=2), encoding='utf-8')
            except OSError as exc:
                self._append('WARNING: TAR was saved, but its metadata could not be updated: ' + str(exc))
            changes = {}
            if self.target_role == 'runtime' or both:
                changes['runtime_base_archive'] = saved_tar
            if self.target_role == 'builder' or both:
                changes['builder_base_archive'] = saved_tar
            state.update(changes)
        self.builder = effective_builder_image(state)
        self.runtime = str(state.get('base_image') or '')
        self.source = self.builder if self.target_role == 'builder' else self.runtime
        self.share_option_available = bool(self.builder and self.builder == self.runtime)
        self.also_other.set(False)
        self._refresh_relationship_text()
        self.builder_caption.set('Current builder: ' + self.builder)
        self.runtime_caption.set('Current runtime: ' + (self.runtime or 'NOT SELECTED'))
        if callable(self.on_complete):
            self.on_complete()

    def _close(self):
        if self.busy:
            self.cancel_event.set()
            self.status.set('Stopping the running Docker operation...')
            return
        self.grab_release()
        self.destroy()
