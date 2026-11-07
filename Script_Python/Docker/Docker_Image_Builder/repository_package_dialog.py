import copy
import json
import queue
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext

from docker_image_checkpoint import checkpoint_sidecar_path, read_checkpoint_metadata, save_image_checkpoint
from local_builder_package_dialog import publish_local_package_install
from network_policy import POLICY_OFFLINE, normalize_policy, validate_packages
from package_repository_finder import _repository_override, inspect_repository_image
from project_state import effective_builder_image
from repository_package_install import archived_repository_recommended, infer_packages_from_install_command, install_repository_packages_in_image
from source_build_dependencies import TOOLS, suggested_package


class RepositoryPackageInstallDialog(tk.Toplevel):
    def __init__(self, parent, app, target='builder', packages=(), verify_commands=(), on_complete=None):
        super().__init__(parent)
        if target not in ('builder', 'runtime'):
            raise ValueError('Select a builder or runtime installation target.')
        self.app = app
        self.target_role = target
        self.on_complete = on_complete
        self.source = effective_builder_image(app.state) if target == 'builder' else str(app.state.get('base_image') or '').strip()
        self.messages = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.info = None
        self.original_runtime = str(app.state.get('base_image') or '').strip()
        self.original_builder = effective_builder_image(app.state)
        self.share_option_available = bool(self.original_builder and self.original_builder == self.original_runtime)
        self.verify_commands = tuple(sorted(set(command for command in verify_commands if command in TOOLS)))
        self.packages = tk.StringVar(value=', '.join(validate_packages(packages)))
        self.custom_command = tk.StringVar(value='')
        self.check_commands = tk.StringVar(value=', '.join(self.verify_commands))
        self.also_other = tk.BooleanVar(value=False)
        self.archive = tk.BooleanVar(value=False)
        self.allow_unverified = tk.BooleanVar(value=False)
        self.save_tar = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value='Inspecting the selected Docker image and its Linux package manager...')
        self.repository = tk.StringVar(value='Inspecting repositories...')
        self.title('Install OS packages automatically into ' + target)
        self.geometry('990x780')
        self.minsize(810, 640)
        self.configure(bg='#E8F8F5')
        self.transient(parent.winfo_toplevel())
        self.protocol('WM_DELETE_WINDOW', self._close)

        tk.Label(self, text='AUTOMATIC REPOSITORY PACKAGE INSTALLATION', bg='#117864', fg='white',
                 font=('Segoe UI', 15, 'bold'), anchor='w', padx=16, pady=13).pack(fill='x')
        tk.Label(self, text='Selected ' + target + ': ' + (self.source or 'NOT SELECTED'),
                 bg='#E8F8F5', anchor='w', padx=15, font=('Segoe UI', 10, 'bold')).pack(fill='x', pady=(9, 2))
        tk.Label(self, textvariable=self.repository, bg='#E8F8F5', fg='#21618C',
                 anchor='w', justify='left', wraplength=920, padx=15).pack(fill='x', pady=2)

        entry = tk.Frame(self, bg='#E8F8F5')
        entry.pack(fill='x', padx=16, pady=(14, 8))
        tk.Label(entry, text='Linux package name(s) or known executable(s):', bg='#E8F8F5',
                 font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        tk.Entry(entry, textvariable=self.packages, font=('Consolas', 11)).pack(fill='x', pady=(5, 4))
        tk.Label(entry, text='Separate entries with commas. Known executable names are mapped to the distribution package, '
                 'for example R → r-base-core on Debian. You can also enter exact package names.', bg='#E8F8F5',
                 fg='#21618C', anchor='w', wraplength=900).pack(fill='x')
        tk.Label(entry, text='Custom installation command (optional; overrides automatic command):', bg='#E8F8F5',
                 font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(9, 0))
        tk.Entry(entry, textvariable=self.custom_command, font=('Consolas', 10)).pack(fill='x', pady=(4, 2))
        tk.Label(entry, text='Examples: apt-get install -y r-base-core   |   apk add R   |   dnf install -y R. '
                 'Executed as root in the NEW Docker image only; no sudo or PowerShell. '
                 'Do not include passwords or tokens.', bg='#E8F8F5',
                 fg='#21618C', anchor='w', wraplength=900).pack(fill='x')
        tk.Label(entry, text='Executables to verify after installation (comma-separated; optional if a package is selected):',
                 bg='#E8F8F5', font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(9, 0))
        tk.Entry(entry, textvariable=self.check_commands, font=('Consolas', 10)).pack(fill='x', pady=(4, 0))
        options = tk.Frame(self, bg='#E8F8F5')
        options.pack(fill='x', padx=16, pady=6)
        alternate = 'runtime base' if target == 'builder' else 'builder'
        self.both_control = tk.Checkbutton(options, text='Also use the updated image as the ' + alternate,
                                          variable=self.also_other, bg='#E8F8F5',
                                          state='normal' if self.share_option_available else 'disabled')
        self.both_control.pack(anchor='w')
        self.archive_control = tk.Checkbutton(options, text='Use the official archived distribution repository (old releases)',
                                             variable=self.archive, bg='#E8F8F5', command=self._repository_caption)
        self.archive_control.pack(anchor='w')
        self.unverified_control = tk.Checkbutton(options, text='Allow packages with expired/unverified archive signatures (security risk)',
                                                variable=self.allow_unverified, bg='#E8F8F5', fg='#922B21')
        self.unverified_control.pack(anchor='w')
        tk.Checkbutton(options, text='Save updated Docker image as reusable TAR after installation',
                       variable=self.save_tar, bg='#E8F8F5').pack(anchor='w')
        tk.Label(options, text='APT, APK, DNF, YUM, or MicroDNF installs the selected packages and their dependencies '
                 'inside a new Docker image. The original image remains unchanged. Internet access is requested '
                 'for each installation, and archived packages may be insecure.',
                 bg='#FCF3CF', fg='#7D6608', justify='left', anchor='w',
                 wraplength=905, padx=8, pady=7).pack(fill='x', pady=8)
        tk.Label(self, textvariable=self.status, bg='#D5F5E3', fg='#0E6655',
                 anchor='w', padx=10, pady=7).pack(fill='x', padx=16)
        self.log = scrolledtext.ScrolledText(self, height=8, bg='white', font=('Consolas', 9))
        self.log.pack(fill='both', expand=True, padx=16, pady=(8, 10))
        actions = tk.Frame(self, bg='#E8F8F5')
        actions.pack(fill='x', padx=16, pady=(0, 12))
        self.install_button = tk.Button(actions, text='Install packages and dependencies into ' + target,
                                        bg='#27AE60', fg='white', command=self._install, state='disabled')
        self.install_button.pack(side='left')
        self.close_button = tk.Button(actions, text='Close', command=self._close)
        self.close_button.pack(side='right')
        self.grab_set()
        self._inspect()

    def _append(self, message):
        if self.winfo_exists():
            self.log.insert('end', str(message).rstrip() + '\n')
            self.log.see('end')

    def _repository_caption(self):
        if self.info is None:
            return
        try:
            if self.archive.get():
                source = _repository_override(self.info, archive=True)
                self.repository.set(self.info.get('pretty_name', '') + ' | ' +
                                    self.info.get('manager', '') + ' | ' + source)
            else:
                repositories = self.info.get('repos') or []
                self.repository.set(self.info.get('pretty_name', '') + ' | ' +
                                    self.info.get('manager', '') + ' | ' +
                                    (repositories[0] if repositories else 'image-configured repositories'))
        except ValueError as exc:
            self.repository.set(str(exc))

    def _inspect(self):
        if not self.source:
            self.status.set('Select the Docker ' + self.target_role + ' image in Tab 1 first.')
            return
        image = self.source
        def worker():
            try:
                report = inspect_repository_image(image, cancel=self.cancel)
                self.messages.put(('inspected', report))
            except Exception as exc:
                self.messages.put(('failure', 'Cannot inspect selected image: ' + str(exc)))
        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll)

    def _set_busy(self, value):
        self.busy = value
        self.install_button.configure(state='disabled' if value or not self.info else 'normal')
        self.close_button.configure(text='Stop' if value else 'Close')
        self.archive_control.configure(state='disabled' if value or not self.info or self.info.get('manager') != 'apt' else 'normal')
        self.unverified_control.configure(state='disabled' if value or not self.info or self.info.get('manager') != 'apt' else 'normal')
        self.both_control.configure(state='disabled' if value or not self.share_option_available else 'normal')

    def _resolve_requests(self, requested):
        manager = str(self.info.get('manager') or '')
        report = {'manager': 'rpm' if manager in ('dnf', 'yum', 'microdnf') else manager,
                  'distro': str(self.info.get('id') or ''),
                  'distro_version': str(self.info.get('version_id') or '')}
        resolved = []
        mapped = []
        commands = set(self.verify_commands)
        for name in requested:
            tool = name if name in TOOLS else ''
            package = suggested_package(tool, report) if tool else ''
            if package:
                if package != name:
                    mapped.append((name, package))
                commands.add(tool)
                resolved.append(package)
            else:
                resolved.append(name)
        return validate_packages(resolved), sorted(commands), mapped

    def _install(self):
        if self.busy or self.info is None:
            return
        if normalize_policy(self.app.state.get('package_download_policy')) == POLICY_OFFLINE:
            messagebox.showwarning('Offline-only mode selected',
                                   'Tab 1 is set to Offline only. Switch to Ask before downloading missing OS packages '
                                   'to enable automatic repository installation.', parent=self)
            return
        try:
            requests = validate_packages(re.split(r'[,\n]+', self.packages.get()))
            custom = self.custom_command.get().strip()
            if not requests and not custom:
                raise ValueError('Enter a Linux package name or a custom installation command.')
            names, commands, mapped = self._resolve_requests(requests)
            if custom and not names:
                names = infer_packages_from_install_command(custom)
            commands = sorted(set(commands) | set(validate_packages(re.split(r'[,\n]+', self.check_commands.get()))))
            if custom and not names and not commands:
                raise ValueError('Enter a package name or executable name to verify the custom installation.')
            if self.allow_unverified.get() and not self.archive.get():
                raise ValueError('Unverified packages may only be approved for an explicitly selected archived APT repository.')
            if self.archive.get():
                repository = _repository_override(self.info, archive=True)
            else:
                repository = '\n'.join(self.info.get('repos') or []) or 'Repositories configured in this image'
        except ValueError as exc:
            messagebox.showerror('Package selection', str(exc), parent=self)
            return
        current = effective_builder_image(self.app.state) if self.target_role == 'builder' else str(self.app.state.get('base_image') or '')
        if current != self.source:
            messagebox.showerror('Image changed', 'The selected ' + self.target_role + ' image changed. Reopen this dialog.', parent=self)
            return
        tar_path = ''
        if self.save_tar.get():
            folder = str(self.app.state.get('export_image_dir') or self.app.state.get('project_dir') or '').strip()
            if not folder or not Path(folder).is_dir():
                folder = str(Path.cwd())
            suggested = re.sub(r'[^A-Za-z0-9_.-]', '_', self.source) + '_with_repository_packages.tar'
            tar_path = filedialog.asksaveasfilename(parent=self, title='Save reusable updated Docker image TAR',
                                                    initialdir=folder, initialfile=suggested,
                                                    defaultextension='.tar', filetypes=[('Docker image TAR', '*.tar')])
            if not tar_path:
                return
        warning = ('\n\nWARNING: You selected installation of packages whose signatures may be expired or unverified.'
                   if self.allow_unverified.get() else '')
        detail = ('This changes BOTH builder and runtime.' if self.also_other.get() else
                  'This changes only the ' + self.target_role + '. The other image is preserved.')
        mapped_text = ('Recognized executable-to-package mappings:\n' +
                       '\n'.join('  ' + name + ' → ' + package for name, package in mapped) + '\n\n') if mapped else ''
        command_text = ('\n\nCUSTOM INSTALL COMMAND (runs inside the new Docker image as root):\n' + custom +
                        '\nThe command can make other changes to this image besides installing packages.'
                        if custom else '\n\nThe detected Linux package manager will install the packages automatically.')
        if not messagebox.askyesno('Approve Linux package downloads',
                                   'Create a new Docker image based on:\n' + self.source + '\n\nVerify OS packages:\n  ' +
                                   ('\n  '.join(names) or '(none specified)') + '\n\n' + mapped_text +
                                   'Repositories:\n' + repository + command_text +
                                   '\n\nVerify executables:\n  ' + ('\n  '.join(commands) or '(none specified)') +
                                   '\n\nThe Linux package manager will automatically download and install any required dependencies. '
                                   'Package installation scripts will execute as root inside Docker.\n\n' + detail +
                                   ('\n\nSave a reusable TAR:\n' + tar_path if tar_path else '') + warning +
                                   '\n\nApprove network access and installation?', parent=self):
            return
        if self.allow_unverified.get() and not messagebox.askyesno('Unverified package installation',
                                    'These packages might not have valid cryptographic signatures. '
                                    'Expired Jessie repositories are unmaintained and vulnerable. '
                                    'This approval affects ONLY this installation. Continue anyway?', parent=self):
            return
        role = self.target_role
        both = bool(self.also_other.get())
        use_archive = bool(self.archive.get())
        allow_unverified = bool(self.allow_unverified.get())
        source = self.source
        info = dict(self.info)
        self.cancel.clear()
        self._set_busy(True)
        self.status.set('Running the approved Docker installation and resolving Linux dependencies...')
        self._append('Installing into a new Docker image: ' + self.source)
        def worker():
            try:
                result = install_repository_packages_in_image(
                    source, names, role=role, use_archive=use_archive,
                    allow_unverified=allow_unverified, verify_commands=commands, custom_command=custom,
                    cancel=self.cancel, progress=lambda line: self.messages.put(('log', line)), info=info)
                error = ''
                if tar_path:
                    self.messages.put(('log', 'Saving the verified Docker image to the selected TAR...'))
                    try:
                        archive = save_image_checkpoint(result['installed_image'], tar_path,
                                                        cancel=self.cancel,
                                                        progress=lambda line: self.messages.put(('log', line)))
                        result['saved_tar'] = archive['archive']
                    except Exception as exc:
                        error = str(exc)
                        self.messages.put(('log', 'TAR EXPORT FAILED: ' + error))
                self.messages.put(('success', (result, both, error)))
            except Exception as exc:
                self.messages.put(('failure', str(exc)))
        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll)

    def _publish(self, result, both):
        state = self.app.state
        publish_local_package_install(state, result, self.target_role, both, origin='repository')
        saved = str(result.get('saved_tar') or '')
        if saved:
            image = result['installed_image']
            inventory = state.get('base_inventory' if self.target_role == 'runtime' else 'builder_inventory') or {}
            system = state.get('base_system' if self.target_role == 'runtime' else 'builder_system') or {}
            metadata = read_checkpoint_metadata(saved)
            metadata['docker_tag'] = image
            metadata['inspection'] = copy.deepcopy(inventory) if isinstance(inventory, dict) else {}
            if isinstance(system, dict) and system:
                metadata['inspection']['system'] = copy.deepcopy(system)
            try:
                checkpoint_sidecar_path(saved).write_text(json.dumps(metadata, indent=2), encoding='utf-8')
            except OSError as exc:
                self._append('WARNING: TAR saved but inventory metadata update failed: ' + str(exc))
            changes = {}
            if self.target_role == 'runtime' or both:
                changes['runtime_base_archive'] = saved
            if self.target_role == 'builder' or both:
                changes['builder_base_archive'] = saved
            state.update(changes)
        if callable(self.on_complete):
            self.on_complete()

    def _poll(self):
        if not self.winfo_exists():
            return
        finished = False
        while True:
            try:
                event, data = self.messages.get_nowait()
            except queue.Empty:
                break
            if event == 'log':
                self._append(data)
            elif event == 'inspected':
                self.info = data
                self.archive.set(archived_repository_recommended(data))
                self._repository_caption()
                self.status.set('Ready: ' + data.get('pretty_name', '') + ' — ' +
                                str(data.get('manager', '')).upper() + ' will install dependencies automatically.')
                self._set_busy(False)
            elif event == 'success':
                result, both, error = data
                try:
                    self._publish(result, both)
                    self._append('VERIFIED: ' + result['installed_image'])
                    self.status.set('Installation completed. Close and reopen to install more packages.')
                    self.info = None
                    messagebox.showinfo('Docker image updated', 'Installed OS packages and their dependencies.\n\n' +
                                        'New image: ' + result['installed_image'] + '\n' +
                                        ('Builder and runtime both use this image.' if both else
                                         'Only the selected ' + self.target_role + ' was updated.') +
                                        ('\nSaved TAR: ' + result['saved_tar'] if result.get('saved_tar') else
                                         '\nTAR export failed: ' + error if error else '\nTAR export was not selected.') +
                                        '\n\nReview packages in Tab 2.', parent=self)
                    finished = True
                except Exception as exc:
                    self.status.set('Docker image created, but project update failed.')
                    messagebox.showerror('Could not update project', str(exc), parent=self)
                    finished = True
            elif event == 'failure':
                self._append('INSTALLATION FAILED: ' + data)
                self.status.set('Installation failed; original Docker image was preserved.')
                messagebox.showerror('Repository installation failed', data[-3500:], parent=self)
                finished = True
        if finished:
            self._set_busy(False)
        elif self.busy or (self.info is None and self.status.get().startswith('Inspecting')):
            self.after(100, self._poll)

    def _close(self):
        if self.busy:
            self.cancel.set()
            self.status.set('Stopping the ongoing Docker operation...')
            return
        self.grab_release()
        self.destroy()
        parent = self.master
        if isinstance(parent, tk.Toplevel) and parent.winfo_exists():
            parent.grab_set()
