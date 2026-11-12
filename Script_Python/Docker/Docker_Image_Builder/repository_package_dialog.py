import queue
import re
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext

from final_image_updates import build_full_image_now, stage_online_request
from local_builder_package_dialog import publish_local_package_install
from network_policy import POLICY_OFFLINE, normalize_policy, validate_packages
from package_repository_finder import _repository_override, inspect_repository_image
from project_state import effective_builder_image
from repository_package_install import archived_repository_recommended, custom_install_problem, infer_packages_from_install_command, install_repository_packages_in_image, repository_install_command
from recognized_elements import recognized_names, valid_name


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
        self.verify_commands = tuple(sorted(set(command for command in verify_commands if valid_name(command))))
        self.packages = tk.StringVar(value=', '.join(validate_packages(packages)))
        self.custom_command = tk.StringVar(value='')
        self.check_commands = tk.StringVar(value=', '.join(self.verify_commands))
        self.also_other = tk.BooleanVar(value=False)
        self.archive = tk.BooleanVar(value=False)
        self.allow_unverified = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='Inspecting the selected Docker image and its Linux package manager...')
        self.repository = tk.StringVar(value='Inspecting repositories...')
        self.title('Install OS packages into ' + ('the complete final image' if target == 'runtime' else 'the build-only image'))
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
        tk.Label(entry, text='Linux package name(s) in the selected distribution:', bg='#E8F8F5',
                 font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        tk.Entry(entry, textvariable=self.packages, font=('Consolas', 11)).pack(fill='x', pady=(5, 4))
        tk.Label(entry, text='Separate package names with commas. Use Tab 8 to search the selected distribution repository and confirm the exact names.', bg='#E8F8F5',
                 fg='#21618C', anchor='w', wraplength=900).pack(fill='x')
        tk.Label(entry, text='Custom installation command (optional; leave blank for automatic installation):', bg='#E8F8F5',
                 font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(9, 0))
        tk.Entry(entry, textvariable=self.custom_command, font=('Consolas', 10)).pack(fill='x', pady=(4, 2))
        tk.Label(entry, text='A custom command overrides automatic dependency installation. '
                 'Use noninteractive commands only (-y for APT/DNF/YUM). Executed as root; do not use sudo or PowerShell. '
                 'For old archives with expired signatures, enter package names above and leave this field BLANK. '
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
        self.archive_control = tk.Checkbutton(options, text='Use the official archived distribution repository (old releases)',
                                             variable=self.archive, bg='#E8F8F5', command=self._repository_caption)
        self.archive_control.pack(anchor='w')
        self.unverified_control = tk.Checkbutton(options, text='Allow packages with expired/unverified archive signatures (security risk)',
                                                variable=self.allow_unverified, bg='#E8F8F5', fg='#922B21')
        self.unverified_control.pack(anchor='w')
        tk.Label(options, text='Runtime packages are installed during assembly of the COMPLETE final image in Tab 6. '
                 'Tab 3 does not create or export an intermediate TAR. Build-only packages remain exclusive to the builder. '
                 'Internet access is requested for each installation, and archived packages may be insecure.',
                 bg='#FCF3CF', fg='#7D6608', justify='left', anchor='w',
                 wraplength=905, padx=8, pady=7).pack(fill='x', pady=8)
        tk.Label(self, textvariable=self.status, bg='#D5F5E3', fg='#0E6655',
                 anchor='w', padx=10, pady=7).pack(fill='x', padx=16)
        self.log = scrolledtext.ScrolledText(self, height=8, bg='white', font=('Consolas', 9))
        self.log.pack(fill='both', expand=True, padx=16, pady=(8, 10))
        actions = tk.Frame(self, bg='#E8F8F5')
        actions.pack(fill='x', padx=16, pady=(0, 12))
        self.install_button = tk.Button(actions, text='Install into complete final image' if target == 'runtime' else 'Install into build-only image',
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
        commands = set(self.verify_commands)
        recognized = recognized_names()
        for name in requested:
            if name in recognized:
                commands.add(name)
        return validate_packages(requested), sorted(commands), []

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
            problem = custom_install_problem(custom)
            if problem:
                if not requests:
                    raise ValueError(problem + ' Select exact OS packages and leave the custom command blank to use the automatic installer.')
                if not messagebox.askyesno('Custom command needs correction',
                        problem + '\n\nClear the custom command and use automatic, noninteractive package installation for the selected packages instead?',
                        parent=self):
                    return
                custom = ''
                self.custom_command.set('')
            if custom and self.allow_unverified.get():
                if not requests:
                    inferred = infer_packages_from_install_command(custom)
                    if not inferred:
                        raise ValueError('Expired-signature approval applies to the automatic installer. Enter exact package names and leave the custom command blank, or manage authentication explicitly in a custom command without this checkbox.')
                    if not messagebox.askyesno('Use automatic archive installation',
                            'The custom command contains these packages:\n\n' + ', '.join(inferred) +
                            '\n\nMove them into the package list, clear the custom command, and use the automatic '
                            'installer with the archive-signature approval you selected?\n\n'
                            'You will be asked again before installing unauthenticated packages.', parent=self):
                        return
                    requests = inferred
                    self.packages.set(', '.join(requests))
                    custom = ''
                    self.custom_command.set('')
                else:
                    if not messagebox.askyesno('Use archive-signature approval',
                            'The expired-signature approval is applied to the automatic package installer, not custom shell commands.\n\n'
                            'Clear the custom command and let the automatic installer use the approved archive setting?',
                            parent=self):
                        return
                    custom = ''
                    self.custom_command.set('')
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
        if self.target_role == 'runtime':
            if getattr(self.app.build_tab, '_busy', False):
                messagebox.showerror('Final image busy', 'Wait until the current full-image build finishes.', parent=self)
                return
            try:
                repository_install_command(self.info, names, use_archive=self.archive.get(),
                                           allow_unverified=self.allow_unverified.get(), custom_command=custom)
            except ValueError as exc:
                messagebox.showerror('Invalid installation command', str(exc), parent=self)
                return
            request_description = ('Install the following packages DIRECTLY into the assembled final image in Tab 6:\n\n' +
                                   ('\n'.join(names) or '(custom installation command)') + '\n\n' +
                                   ('Custom command: ' + custom + '\n\n' if custom else '') +
                                   'Starting runtime: ' + self.source + '\n' +
                                   'Repository: ' + repository + '\n\n' +
                                   'No intermediate Docker image TAR will be created. The completed image will be exported after assembly.\n' +
                                   'The build needs approved network access to install these packages.\n\nContinue?')
            if not messagebox.askyesno('Update the COMPLETE Docker image', request_description, parent=self):
                return
            if self.allow_unverified.get() and not messagebox.askyesno(
                    'Unverified archived packages',
                    'These Linux packages may have expired or unverified signatures. Continue despite this security risk?',
                    parent=self):
                return
            try:
                stage_online_request(self.app.state, self.source, names, self.info,
                                     use_archive=self.archive.get(), allow_unverified=self.allow_unverified.get(),
                                     custom_command=custom, verify_commands=commands)
                self._close()
                build_full_image_now(self.app)
            except (ValueError, RuntimeError) as exc:
                messagebox.showerror('Final image update', str(exc), parent=self.app)
            return
        current = effective_builder_image(self.app.state) if self.target_role == 'builder' else str(self.app.state.get('base_image') or '')
        if current != self.source:
            messagebox.showerror('Image changed', 'The selected ' + self.target_role + ' image changed. Reopen this dialog.', parent=self)
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
                                   warning +
                                   '\n\nApprove network access and installation?', parent=self):
            return
        if self.allow_unverified.get() and not messagebox.askyesno('Unverified package installation',
                                    'These packages might not have valid cryptographic signatures. '
                                    'Archived distribution repositories may be unmaintained and vulnerable. '
                                    'This approval affects ONLY this installation. Continue anyway?', parent=self):
            return
        role = self.target_role
        both = False
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
                self.messages.put(('success', (result, both, '')))
            except Exception as exc:
                self.messages.put(('failure', str(exc)))
        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll)

    def _publish(self, result, both):
        state = self.app.state
        publish_local_package_install(state, result, self.target_role, both, origin='repository')
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
                result, both, _ = data
                try:
                    self._publish(result, both)
                    self._append('VERIFIED: ' + result['installed_image'])
                    self.status.set('Installation completed. Close and reopen to install more packages.')
                    self.info = None
                    messagebox.showinfo('Docker image updated', 'Installed OS packages and their dependencies.\n\n' +
                                        'New image: ' + result['installed_image'] + '\n' +
                                        ('Builder and runtime both use this image.' if both else
                                         'Only the selected ' + self.target_role + ' was updated.') +
                                        '\nNo intermediate TAR created. The final image is exported in Tab 6.' +
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
