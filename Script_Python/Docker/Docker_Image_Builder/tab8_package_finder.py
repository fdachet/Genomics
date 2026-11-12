import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from local_builder_package_install import describe_local_package, preflight_local_builder_packages
from local_package_catalog import package_identity
from package_repository_finder import (DISTRIBUTION_REPOSITORIES, estimate_docker_hub_image_size,
                                       cached_repository_package, extract_package_executables, inspect_repository_image,
                                       list_distribution_tags, list_local_docker_images,
                                       load_local_distribution_archive, pull_repository_image,
                                       repository_details, repository_download,
                                       repository_search, repository_source_download,
                                       _repository_override, _run)
from project_state import effective_builder_image


class PackageFinderTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg='#EAF2F8')
        self.app = app
        self.messages = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.busy_since = 0.0
        self.image_info = None
        self.inspect_requested_image = ''
        self.inspect_requested_platform = ''
        self.inspected_images = set()
        self.last_manifest = None
        self.last_source_manifest = None
        self.available = {}
        self.release_tags = {}
        self.all_tag_names = []
        self.image_size_result = None
        self.image_size_for = None
        self.repo_signature_warning = ''
        self.repo_signature_key = None
        self.pending_after_download = None
        self.pending_search = False
        self.local_docker_images = {}
        self.sort_column = ''
        self.sort_descending = False
        tk.Label(self, text='8 — FIND PRECOMPILED LINUX PACKAGES', bg='#2471A3', fg='white',
                 font=('Segoe UI', 16, 'bold'), anchor='w', padx=20, pady=15).pack(fill='x', padx=8, pady=(8, 6))
        tk.Label(self, text='Choose a downloaded Linux image or a Docker Hub release, search packages, then save the selected binary package or add it to the runtime/builder.',
                 bg='#EAF2F8', fg='#154360', anchor='w').pack(fill='x', padx=16)

        image_bar = tk.Frame(self, bg='#EAF2F8')
        self.target = tk.StringVar(value='Builder')
        self.target_selector = ttk.Combobox(image_bar, textvariable=self.target, values=['Builder', 'Runtime'], width=13, state='readonly')
        self.image_label = tk.StringVar(value='No Docker image selected')

        source_bar = tk.Frame(self, bg='#EAF2F8')
        source_bar.pack(fill='x', padx=16, pady=(0, 3))
        tk.Label(source_bar, text='Search distribution:', bg='#EAF2F8').pack(side='left')
        saved_mode = str(app.state.get('package_finder_source_mode') or '')
        source_modes = ['Downloaded Docker images', 'Docker Hub', 'Local Docker image archive', 'Local Linux rootfs archive']
        if saved_mode not in source_modes:
            saved_mode = 'Downloaded Docker images'
        self.app.state['package_finder_source_mode'] = saved_mode
        self.source_mode = tk.StringVar(value=saved_mode)
        self.source_selector = ttk.Combobox(source_bar, textvariable=self.source_mode,
                                           values=source_modes, width=26, state='readonly')
        self.source_selector.pack(side='left', padx=8)
        self.source_selector.bind('<<ComboboxSelected>>', self._source_changed)
        tk.Label(source_bar, text='Architecture:', bg='#EAF2F8').pack(side='left', padx=(12, 3))
        self.search_platform = tk.StringVar(value=str(app.state.get('package_finder_platform') or 'linux/amd64'))
        self.platform_selector = ttk.Combobox(source_bar, textvariable=self.search_platform,
                                               values=['linux/amd64', 'linux/arm64', 'linux/386', 'linux/arm/v7',
                                                       'linux/ppc64le', 'linux/s390x', 'linux/riscv64'],
                                               width=14, state='readonly')
        self.platform_selector.pack(side='left', padx=3)
        self.platform_selector.bind('<<ComboboxSelected>>', self._source_changed)

        self.distribution_bar = tk.Frame(self, bg='#EAF2F8')
        tk.Label(self.distribution_bar, text='Distribution:', bg='#EAF2F8').pack(side='left')
        self.distribution_name = tk.StringVar(value=str(app.state.get('package_finder_distribution') or ''))
        self.distribution_selector = ttk.Combobox(self.distribution_bar, textvariable=self.distribution_name,
                                                 values=sorted(DISTRIBUTION_REPOSITORIES), width=19, state='readonly')
        self.distribution_selector.pack(side='left', padx=8)
        self.distribution_selector.bind('<<ComboboxSelected>>', self._distribution_changed)
        tk.Label(self.distribution_bar, text='Image version / tag (keyword):', bg='#EAF2F8').pack(side='left', padx=(10, 3))
        self.distribution_tag = tk.StringVar(value=str(app.state.get('package_finder_distribution_tag') or ''))
        self.tag_selector = ttk.Combobox(self.distribution_bar, textvariable=self.distribution_tag, width=26)
        self.tag_selector.pack(side='left', padx=4)
        self.tag_selector.bind('<<ComboboxSelected>>', self._source_changed)
        self.tag_selector.bind('<FocusOut>', self._source_changed)
        self.tag_selector.bind('<KeyRelease>', self._filter_version_tags)
        tk.Button(self.distribution_bar, text='Find / count versions', bg='#AED6F1',
                  command=self.fetch_versions).pack(side='left', padx=6)
        self.tag_filter_status = tk.StringVar(value='Type a release keyword and click Find / count versions.')
        self.tag_status_caption = tk.Label(self, textvariable=self.tag_filter_status,
                                           bg='#EAF2F8', fg='#566573', anchor='w')
        self.tag_status_caption.pack(fill='x', padx=18, pady=(0, 2))

        self.custom_bar = tk.Frame(self, bg='#EAF2F8')
        tk.Label(self.custom_bar, text='Custom Docker image:', bg='#EAF2F8').pack(side='left')
        self.custom_image = tk.StringVar(value=str(app.state.get('package_finder_custom_image') or ''))
        custom_entry = tk.Entry(self.custom_bar, textvariable=self.custom_image, width=55)
        custom_entry.pack(side='left', padx=8)
        custom_entry.bind('<Return>', self._source_changed)
        custom_entry.bind('<FocusOut>', self._source_changed)
        tk.Label(self.custom_bar, text='Enter a full image name and tag, e.g. registry.example.org/os:version',
                 bg='#EAF2F8', fg='#566573').pack(side='left', padx=4)

        self.local_bar = tk.Frame(self, bg='#EAF2F8')
        tk.Label(self.local_bar, text='Local distribution archive:', bg='#EAF2F8').pack(side='left')
        self.local_archive = tk.StringVar(value=str(app.state.get('package_finder_local_archive') or ''))
        local_entry = tk.Entry(self.local_bar, textvariable=self.local_archive, width=64)
        local_entry.pack(side='left', padx=8, fill='x', expand=True)
        local_entry.bind('<Return>', self._source_changed)
        local_entry.bind('<FocusOut>', self._source_changed)
        tk.Button(self.local_bar, text='Browse...', command=self.browse_local_archive).pack(side='left', padx=5)
        self.local_loaded_image = tk.StringVar(value=str(app.state.get('package_finder_local_image') or ''))
        self.local_loaded_path = str(app.state.get('package_finder_local_loaded_path') or '')
        self.local_description = tk.StringVar(value='Choose an image TAR archive saved by Docker or a Linux rootfs TAR archive.')
        tk.Label(self.local_bar, textvariable=self.local_description,
                 bg='#EAF2F8', fg='#566573').pack(side='left', padx=5)
        self._toggle_source_controls()

        self.system_label = tk.StringVar(value='OS / architecture: inspect the selected image')
        self.system_caption = tk.Label(self, textvariable=self.system_label, bg='#D6EAF8', anchor='w', padx=10, pady=7)
        self.system_caption.pack(fill='x', padx=16, pady=4)
        self.size_label = tk.StringVar(value='Choose an image already downloaded in Docker Desktop.')
        tk.Label(self, textvariable=self.size_label, bg='#EAF2F8', fg='#154360',
                 anchor='w').pack(fill='x', padx=18, pady=(0, 2))
        control = tk.Frame(self, bg='#EAF2F8')
        control.pack(fill='x', padx=16, pady=6)
        tk.Label(control, text='Search package:', bg='#EAF2F8').pack(side='left')
        self.query = tk.StringVar(value='')
        search_entry = tk.Entry(control, textvariable=self.query, width=30)
        search_entry.pack(side='left', padx=7)
        search_entry.bind('<Return>', lambda e: self.search())
        tk.Button(control, text='Search packages', bg='#48C9B0', command=self.search).pack(side='left', padx=4)
        self.use_archive = tk.BooleanVar(value=bool(app.state.get('package_finder_archive_mode', False)))
        repository_bar = tk.Frame(self, bg='#EAF2F8')
        self.repo_override = tk.StringVar(value='')

        self.results_status = tk.StringVar(value='Search to list available packages without downloading package binaries.')
        tk.Label(self, textvariable=self.results_status, bg='#D6EAF8', fg='#154360',
                 font=('Segoe UI', 10, 'bold'), anchor='w', padx=10, pady=6).pack(fill='x', padx=16)
        frame = tk.Frame(self, bg='white', bd=1, relief='solid')
        frame.pack(fill='both', expand=True, padx=16, pady=4)
        tree_style = ttk.Style(self)
        tree_style.configure('Finder.Treeview', background='#FFFFFF', foreground='#17202A',
                             fieldbackground='#FFFFFF', rowheight=25, font=('Segoe UI', 10))
        tree_style.configure('Finder.Treeview.Heading', background='#D6EAF8', foreground='#154360',
                             font=('Segoe UI', 10, 'bold'))
        tree_style.map('Finder.Treeview', background=[('selected', '#2874A6')],
                       foreground=[('selected', '#FFFFFF')])
        self.table = ttk.Treeview(frame, columns=('name', 'version', 'description'),
                                  show='headings', selectmode='browse', height=13, style='Finder.Treeview')
        self.heading_labels = {'name': 'Package', 'version': 'Available version',
                               'description': 'Repository description'}
        self._update_headings()
        self.table.column('name', width=250, minwidth=100)
        self.table.column('version', width=170, minwidth=100)
        self.table.column('description', width=730, minwidth=300)
        self.table.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(frame, command=self.table.yview)
        scrollbar.pack(side='right', fill='y')
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.bind('<<TreeviewSelect>>', self._selected)
        self.table.tag_configure('even', background='#FFFFFF', foreground='#17202A')
        self.table.tag_configure('odd', background='#EAF2F8', foreground='#17202A')
        self.details = tk.Text(self, height=3, wrap='word', font=('Consolas', 9), bg='white')
        self.details.pack(fill='x', padx=16, pady=4)
        actions = tk.Frame(self, bg='#EAF2F8')
        actions.pack(fill='x', padx=16, pady=8)
        tk.Label(actions, text='Selected package action:', bg='#EAF2F8').pack(side='left')
        self.selected_action = tk.StringVar(value='Save selected precompiled package')
        ttk.Combobox(actions, textvariable=self.selected_action, state='readonly', width=38,
                     values=['Save selected precompiled package',
                             'Extract executable files to folder',
                             'Add binary packages to final runtime',
                             'Install binary packages in builder']).pack(side='left', padx=7)
        tk.Button(actions, text='Run selected action', bg='#82E0AA', command=self.run_selected_action).pack(side='left', padx=4)
        tk.Button(actions, text='Stop', bg='#F1948A', command=self._stop).pack(side='right', padx=3)
        cache_bar = tk.Frame(self, bg='#EAF2F8')
        cache_bar.pack(fill='x', padx=16, pady=(0, 5))
        tk.Label(cache_bar, text='Save under folder (tag_linux_arch/package):', bg='#EAF2F8').pack(side='left')
        self.cache = tk.StringVar()
        tk.Entry(cache_bar, textvariable=self.cache).pack(side='left', fill='x', expand=True, padx=8)
        tk.Button(cache_bar, text='Browse', command=self.choose_cache).pack(side='left')
        saved_bar = tk.Frame(self, bg='#EAF2F8')
        saved_bar.pack(fill='x', padx=16, pady=(0, 5))
        tk.Label(saved_bar, text='Saved package file:', bg='#EAF2F8').pack(side='left')
        self.saved_package_path = tk.StringVar(value='No package has been downloaded.')
        ttk.Entry(saved_bar, textvariable=self.saved_package_path, state='readonly').pack(
            side='left', fill='x', expand=True, padx=8)
        tk.Button(saved_bar, text='Open folder', command=self.open_saved_folder).pack(side='left', padx=3)
        tk.Button(saved_bar, text='Copy file path', command=self.copy_saved_path).pack(side='left', padx=3)
        foot = tk.Frame(self, bg='#EAF2F8')
        foot.pack(fill='x', padx=16)
        tk.Label(foot, text='Live package manager log', bg='#EAF2F8', font=('Segoe UI', 9, 'bold')).pack(side='left')
        tk.Button(foot, text='Clear log', command=lambda: self.log.delete('1.0', 'end')).pack(side='right')
        self.activity = tk.StringVar(value='Ready')
        tk.Label(foot, textvariable=self.activity, bg='#EAF2F8', fg='#154360').pack(side='left', padx=15)
        self.log = tk.Text(self, height=7, wrap='word', bg='white', font=('Consolas', 9))
        self.log.pack(fill='x', padx=16, pady=(3, 12))
        self._save_source_settings()
        self.refresh_from_project_state()
        if self.source_mode.get() == 'Downloaded Docker images':
            self.after(200, self.fetch_versions)
        self.after(100, self._drain)
        self.after(1000, self._pulse)

    def _toggle_source_controls(self):
        mode = self.source_mode.get()
        self.distribution_bar.pack_forget()
        self.custom_bar.pack_forget()
        self.local_bar.pack_forget()
        settings = {'fill': 'x', 'padx': 16, 'pady': (0, 3),
                    'before': self.tag_status_caption}
        if mode in ('Downloaded Docker images', 'Docker Hub'):
            self.distribution_bar.pack(**settings)
        elif mode in ('Local Docker image archive', 'Local Linux rootfs archive'):
            self.local_bar.pack(**settings)
        if mode == 'Downloaded Docker images':
            self.distribution_selector.configure(state='readonly')
        else:
            self.distribution_selector.configure(state='readonly', values=sorted(DISTRIBUTION_REPOSITORIES))
        self.platform_selector.configure(state='readonly')

    def _save_source_settings(self):
        for key, value in (
            ('package_finder_source_mode', self.source_mode.get()),
            ('package_finder_distribution', self.distribution_name.get()),
            ('package_finder_distribution_tag', self.distribution_tag.get().strip()),
            ('package_finder_custom_image', self.custom_image.get().strip()),
            ('package_finder_platform', self.search_platform.get()),
            ('package_finder_local_archive', self.local_archive.get().strip()),
        ):
            if self.app.state.get(key) != value:
                self.app.state[key] = value

    def _source_changed(self, event=None):
        self._save_source_settings()
        self._toggle_source_controls()
        self.refresh_from_project_state()
        self._update_size_label()
        if event and getattr(event, 'widget', None) == self.source_selector and self.source_mode.get() == 'Downloaded Docker images':
            self.fetch_versions()

    def _distribution_changed(self, event=None):
        self.distribution_tag.set('')
        self.tag_selector.configure(values=[])
        self.release_tags = {}
        self.all_tag_names = []
        self.tag_filter_status.set('Type a version keyword and click Find / count versions.')
        self._source_changed()
        if self.source_mode.get() == 'Downloaded Docker images':
            self._show_local_versions()

    @staticmethod
    def _size_text(size):
        if size is None or size <= 0:
            return 'not available'
        if size >= 1000000000:
            return f'{size / 1000000000:.2f} GB'
        return f'{size / 1000000:.1f} MB'

    def _known_image_size(self, image, platform):
        tag = self.distribution_tag.get().strip()
        if self.source_mode.get() == 'Docker Hub':
            release = self.release_tags.get(tag) or {}
            sizes = release.get('sizes') or {}
            architecture = platform[6:] if platform.startswith('linux/') else ''
            if architecture in sizes:
                return sizes[architecture]
            if not platform and len(sizes) == 1:
                return next(iter(sizes.values()))
        if self.image_size_for == (image, platform) and self.image_size_result:
            return self.image_size_result.get('size')
        return None

    def _update_size_label(self):
        if not hasattr(self, 'size_label'):
            return
        image = self._image()
        if not image:
            self.size_label.set('Select a distribution and image version, then search packages.')
            return
        if self.source_mode.get() == 'Downloaded Docker images':
            row = self.local_docker_images.get(image, {})
            if not row:
                self.size_label.set('Select an exact locally downloaded image tag from the dropdown.')
            else:
                self.size_label.set('Already downloaded in Docker Desktop: ' + image +
                                    (' | Image size: ' + row['size_label'] if row.get('size_label') else ''))
            return
        if self.source_mode.get() in ('Local Docker image archive', 'Local Linux rootfs archive'):
            self.size_label.set('Local image loaded: ' + image)
            return
        size = self._known_image_size(image, self._selected_platform())
        if size:
            self.size_label.set('Estimated image download: ' + self._size_text(size) +
                                ' (Docker Hub image metadata; cached layers may reduce actual transfer)')
        else:
            self.size_label.set('Estimated image download: size not yet available — checked before pull approval.')

    def _matching_version_tags(self, fragment):
        fragment = str(fragment or '').casefold()
        return [name for name in self.all_tag_names if fragment in name.casefold()]

    def _filter_version_tags(self, event=None):
        if event and event.keysym in ('Up', 'Down', 'Return', 'Escape', 'Tab', 'Left', 'Right', 'Home', 'End'):
            return
        typed = self.distribution_tag.get()
        if self.source_mode.get() == 'Downloaded Docker images':
            self.all_tag_names = sorted([row['tag'] for row in self.local_docker_images.values()
                                         if row['repository'] == self.distribution_name.get()], reverse=True)
        choices = self._matching_version_tags(typed)
        self.tag_selector.configure(values=choices)
        if typed:
            if choices:
                self.tag_filter_status.set(str(len(choices)) + ' matching ' +
                                           ('downloaded' if self.source_mode.get() == 'Downloaded Docker images' else 'available') + ' version tags.')
            else:
                self.tag_filter_status.set('No matching loaded tag. Use Find / count versions to refresh the list.')
        else:
            self.tag_filter_status.set(str(len(choices)) + ' loaded tags. Type any part of a version to filter.')
        self._update_size_label()
        if event is not None and typed and choices and self.tag_selector.focus_get() == self.tag_selector:
            self.after_idle(lambda: self.tag_selector.event_generate('<Down>')
                            if self.tag_selector.focus_get() == self.tag_selector else None)

    def _show_local_versions(self):
        repository = self.distribution_name.get().strip()
        keyword = self.distribution_tag.get().strip()
        tags = sorted({row['tag'] for row in self.local_docker_images.values()
                       if row['repository'] == repository and keyword.casefold() in row['tag'].casefold()},
                      key=lambda label: tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                                              for part in re.split(r'(\d+)', label)), reverse=True)
        self.all_tag_names = sorted({row['tag'] for row in self.local_docker_images.values()
                                     if row['repository'] == repository})
        self.tag_selector.configure(values=tags)
        if not repository:
            self.tag_filter_status.set('Choose a downloaded Linux distribution above.')
        else:
            self.tag_filter_status.set(str(len(tags)) + ' downloaded version tags of ' + repository +
                                       (' contain ' + keyword if keyword else ' are available locally') + '.')
        if len(tags) == 1 and not keyword:
            self.distribution_tag.set(tags[0])
            self._save_source_settings()
        self._update_size_label()

    def _update_headings(self):
        for column, label in self.heading_labels.items():
            direction = (' ▼' if self.sort_descending else ' ▲') if self.sort_column == column else ''
            self.table.heading(column, text=label + direction,
                               command=lambda key=column: self._sort_results(key))

    def _sort_results(self, column=None):
        if column is not None:
            if self.sort_column == column:
                self.sort_descending = not self.sort_descending
            else:
                self.sort_column = column
                self.sort_descending = False
        if not self.sort_column:
            return
        column = self.sort_column
        def key(item):
            value = self.table.set(item, column).casefold()
            if column == 'version':
                return tuple((1, int(part)) if part.isdigit() else (0, part)
                             for part in re.split(r'(\d+)', value))
            return value
        ordered = sorted(self.table.get_children(''), key=key, reverse=self.sort_descending)
        for index, item in enumerate(ordered):
            self.table.move(item, '', index)
            self.table.item(item, tags=('even' if index % 2 == 0 else 'odd',))
        self._update_headings()

    def _selected_platform(self):
        return self.search_platform.get()

    def _image(self):
        mode = self.source_mode.get()
        if mode in ('Local Docker image archive', 'Local Linux rootfs archive'):
            try:
                matching_file = (Path(self.local_loaded_path).resolve() ==
                                 Path(self.local_archive.get().strip()).resolve())
            except (OSError, ValueError):
                matching_file = False
            return self.local_loaded_image.get().strip() if (
                self.local_loaded_path and matching_file and
                self.app.state.get('package_finder_local_loaded_mode') == mode) else ''
        if mode in ('Downloaded Docker images', 'Docker Hub'):
            repository = (self.distribution_name.get().strip() if mode == 'Downloaded Docker images'
                          else DISTRIBUTION_REPOSITORIES.get(self.distribution_name.get(), ''))
            tag = self.distribution_tag.get().strip()
            if repository and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', tag):
                return repository + ':' + tag
            return ''
        if mode == 'Custom Docker image':
            return self.custom_image.get().strip()
        state = self.app.state
        if self.target.get() == 'Builder':
            return effective_builder_image(state)
        return str(state.get('base_image') or '').strip()

    def refresh_from_project_state(self):
        state_fields = (
            ('package_finder_source_mode', self.source_mode),
            ('package_finder_distribution', self.distribution_name),
            ('package_finder_distribution_tag', self.distribution_tag),
            ('package_finder_custom_image', self.custom_image),
            ('package_finder_platform', self.search_platform),
            ('package_finder_local_archive', self.local_archive),
        )
        previous_distribution = self.distribution_name.get()
        for key, variable in state_fields:
            saved = str(self.app.state.get(key) or '')
            if saved != variable.get():
                variable.set(saved)
        if self.distribution_name.get() != previous_distribution:
            self.release_tags = {}
            self.all_tag_names = []
            self.tag_selector.configure(values=[])
        self._toggle_source_controls()
        image = self._image()
        self.image_label.set(image or ('Select a distribution and version, or enter a Docker image name'
                                       if self.source_mode.get() != 'Selected builder/runtime'
                                       else 'Not selected in Tab 1'))
        if self.source_mode.get() in ('Local Docker image archive', 'Local Linux rootfs archive'):
            self.image_label.set(image or 'Select a local TAR archive and click Load local Linux distribution')
            self.local_description.set('Loaded image: ' + image if image else 'Selected file is not loaded in Docker Desktop yet.')
        self.use_archive.set(bool(self.app.state.get('package_finder_archive_mode', False)))
        if self.image_info and (self.image_info.get('image') != image or
                                self.image_info.get('platform', '') != self._selected_platform()):
            self.image_info = None
            self.system_label.set('OS / architecture: inspect the newly selected image')
            self.available.clear()
            self.results_status.set('Image changed. Search the selected distribution repositories.')
            self.repo_signature_warning = ''
            self.repo_signature_key = None
            for item in self.table.get_children():
                self.table.delete(item)
            if image != self.app.state.get('package_finder_archive_image', ''):
                self.app.state['package_finder_archive_mode'] = False
                self.use_archive.set(False)
        if not self.image_info:
            self.system_label.set(('Selected Linux image: ' + image + ' | Ready to search' if image
                                   else 'Choose an image version/tag (already downloaded images appear in the dropdown).'))
        if not self.cache.get().strip():
            project = str(self.app.state.get('project_dir') or '').strip()
            configured = str(self.app.state.get('package_finder_cache') or '').strip()
            self.cache.set(configured or str(Path(project or Path.cwd()) / '_package_cache'))
        if not self.last_manifest:
            downloads = self.app.state.get('package_finder_downloads') or []
            if downloads:
                self.last_manifest = downloads[-1]
        if not self.last_source_manifest:
            downloads = self.app.state.get('package_finder_source_downloads') or []
            if downloads:
                self.last_source_manifest = downloads[-1]
        self._update_size_label()

    def _append(self, message):
        self.log.insert('end', str(message).rstrip() + '\n')
        self.log.see('end')

    def _stop(self):
        if self.busy:
            self.cancel.set()
            self.activity.set('Stopping running Docker operation...')
            self._append('STOP REQUESTED: terminating Docker operation')

    def _pulse(self):
        if self.busy:
            elapsed = int(time.monotonic() - self.busy_since)
            self.activity.set('Working — ' + str(elapsed) + ' seconds elapsed | Stop to cancel')
        self.after(1000, self._pulse)

    def _work(self, name, function):
        if self.busy:
            messagebox.showinfo('Package Finder', 'Wait for the current operation or press Stop.', parent=self)
            return False
        self.cancel.clear()
        self.busy = True
        self.busy_since = time.monotonic()
        self.activity.set('Running ' + name + '...')
        self._append('START: ' + name)
        def worker():
            try:
                result = function(lambda line: self.messages.put(('progress', name, line)))
                self.messages.put(('done', name, result))
            except Exception as exc:
                self.messages.put(('error', name, str(exc)))
        threading.Thread(target=worker, daemon=True).start()
        return True

    def _drain(self):
        try:
            while True:
                kind, name, payload = self.messages.get_nowait()
                if kind == 'progress':
                    self._append(payload)
                    continue
                self.busy = False
                self.activity.set('Failed: ' + name if kind == 'error' else 'Completed: ' + name)
                if kind == 'error':
                    if (name == 'inspect' and self.inspect_requested_image == self._image() and
                            self.inspect_requested_platform == self._selected_platform() and
                            re.search(r'No such image|No such object|image not found', payload, re.IGNORECASE)):
                        self.activity.set('Selected Linux image is not downloaded')
                        self._append('IMAGE NOT DOWNLOADED: ' + self.inspect_requested_image)
                        requested_image = self.inspect_requested_image
                        requested_platform = self.inspect_requested_platform
                        if self.source_mode.get() == 'Docker Hub':
                            self._append('This release is not yet in Docker Desktop. You can approve downloading it.')
                            self.after_idle(lambda: self.pull_image()
                                            if self._image() == requested_image and
                                            self._selected_platform() == requested_platform else None)
                        else:
                            self.pending_search = False
                            self._append('Refresh downloaded Docker images or load the selected local TAR archive.')
                    else:
                        self._append('FAILED: ' + name + '\n' + payload)
                        retrying = False
                        if name in ('search', 'details', 'download', 'source'):
                            retrying = bool(self._offer_archive_after_error(name, payload))
                        if name == 'download' and not retrying:
                            self.pending_after_download = None
                else:
                    try:
                        self._finish(name, payload)
                    except Exception as exc:
                        self._append('ERROR updating package finder: ' + str(exc))
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _offer_archive_after_error(self, operation, error):
        info = self.image_info or {}
        if (info.get('manager') != 'apt' or self.use_archive.get() or
                self.repo_override.get().strip() or not re.search(r'\b404\b', error)):
            return
        try:
            archive = _repository_override(info, archive=True)
        except (ValueError, KeyError):
            return
        self._append('ARCHIVED RELEASE DETECTED: the configured package repositories returned HTTP 404.')
        self._append('Proposed archived repository: ' + archive)
        question = ('The configured repositories for ' + info.get('pretty_name', 'this Linux release') +
                    ' returned HTTP 404. This release may have moved to its official archive.\n\n' +
                    'Proposed repository:\n' + archive + '\n\n' +
                    'Use this archived repository and retry ' + operation + '?\n\n' +
                    'Archived releases are no longer supported and may contain unpatched vulnerabilities. ' +
                    'The archived package source will be used only for this package operation.')
        if not messagebox.askyesno('Use archived Linux repository?', question, parent=self):
            self._append('Archive switch declined. You can select an archive or configure a custom repository manually.')
            return
        self.use_archive.set(True)
        self._repository_settings()
        self._append('Archive selected: ' + archive + '. Retrying ' + operation + '...')
        retry = {'search': self.search, 'details': self.details_selected,
                 'download': self.download, 'source': self.download_source}[operation]
        self.after(50, lambda: retry(retry_approved=True))
        return True

    def _finish(self, name, result):
        if name == 'inspect':
            if result.get('image') != self._image() or result.get('platform', '') != self._selected_platform():
                self._append('Image selection changed while inspection was running; stale results were discarded.')
                return
            self.image_info = result
            self.system_label.set(result.get('pretty_name', '?') + ' | ' + result.get('arch', '?') +
                                  ' | package manager: ' + result.get('manager', '?') + ' | ' + result.get('image', ''))
            self._append('Detected ' + self.system_label.get())
            for repository in result.get('repos') or []:
                self._append('Configured repository: ' + repository)
            self._append('Package search uses repositories configured in this Linux image. If retired URLs return 404, the official archive can be approved.')
            if self.pending_search:
                self.pending_search = False
                self.after(40, self.search)
        elif name == 'local_versions':
            if self.source_mode.get() != 'Downloaded Docker images':
                self._append('The source mode changed; discarded the outdated Docker image list.')
                return
            self.local_docker_images = {row['image']: row for row in result}
            repository_names = sorted({row['repository'] for row in result}, key=str.casefold)
            self.distribution_selector.configure(values=repository_names)
            selected = self.distribution_name.get().strip()
            if selected not in repository_names:
                matches = [name for name in repository_names if name.casefold() == selected.casefold() or
                           name.split('/')[-1].casefold() == selected.casefold()]
                if matches:
                    self.distribution_name.set(matches[0])
                elif len(repository_names) == 1:
                    self.distribution_name.set(repository_names[0])
                else:
                    self.distribution_name.set('')
            self._save_source_settings()
            self._show_local_versions()
            self._append('Docker Desktop has ' + str(len(result)) + ' locally downloaded image tags across ' +
                         str(len(repository_names)) + ' repositories. No image download is needed.')
        elif name == 'versions':
            repository, filter_text, releases = result
            if repository != DISTRIBUTION_REPOSITORIES.get(self.distribution_name.get()):
                self._append('Distribution was changed while querying Docker Hub; outdated versions were discarded.')
                return
            count = len(releases)
            self._append('SEARCH RESULT: ' + str(count) + ' available image tags contain ' +
                         (filter_text if filter_text else 'the requested release filter') + '.')
            if not count:
                self.tag_filter_status.set('0 matching tags. Refine the keyword or enter an exact release tag.')
                return
            self.tag_filter_status.set(str(count) + ' matching tags found. Choose whether to display these choices.')
            self.update_idletasks()
            question = ('Search term: ' + (filter_text or '(all recent tags)') + '\n' +
                        'Matching Docker image versions: ' + str(count) + '\n\n' +
                        'Display these ' + str(count) + ' version choices in the dropdown?\n\n' +
                        'Yes: show matching release tags.\nNo: keep the keyword so you can make it more specific.\n\n' +
                        'This only retrieves tag names. No Linux images are downloaded.')
            if not messagebox.askyesno('Review distribution version matches', question, parent=self):
                self._append('Search choices not loaded. Improve your keyword and click Find available versions again.')
                self.tag_filter_status.set(str(count) + ' choices found but not loaded. Refine the keyword and search again.')
                return
            for row in releases:
                self.release_tags[row['tag']] = row
            self.all_tag_names = sorted(self.release_tags, key=lambda item: tuple(
                (1, int(part)) if part.isdigit() else (0, part.casefold())
                for part in re.split(r'(\d+)', item)), reverse=True)
            self._filter_version_tags()
            self._update_size_label()
            self._append('Loaded ' + str(len(releases)) + (' release tags containing ' + filter_text
                         if filter_text else ' recent release tags') + ' for ' + repository + '.')
            self._append('Select a release tag and search a package. Docker will download the image only if it is missing.')
        elif name == 'size':
            image, platform, size_info = result
            self.image_size_for = (image, platform)
            self.image_size_result = size_info
            if image != self._image() or platform != self._selected_platform():
                self._append('Image selection changed; size estimate discarded for download confirmation.')
                return
            self._update_size_label()
            if size_info.get('size'):
                self._append('Docker Hub reports an image size of ' + self._size_text(size_info['size']) +
                             ' for ' + image + ' (' + (platform or 'Docker default') + ').')
            else:
                self._append('Image-size estimate unavailable: ' + size_info.get('reason', 'unknown reason'))
            self.after(25, lambda: self._confirm_pull(image, platform, size_info.get('size')))
        elif name == 'pull':
            self._append('Selected Linux image downloaded and cached by Docker. Inspecting its distribution and package manager...')
            self.after(25, self.inspect_image)
        elif name == 'local_load':
            images = result.get('images') or []
            if not images:
                raise RuntimeError('No images were reported by Docker when loading the archive.')
            chosen = images[0]
            if len(images) > 1:
                listing = '\n'.join(images[:25])
                if len(images) > 25:
                    listing += '\n... and ' + str(len(images) - 25) + ' more'
                chosen = simpledialog.askstring('Choose a loaded Linux distribution',
                                                'Docker loaded multiple images:\n\n' + listing +
                                                '\n\nEnter the exact image to inspect:',
                                                initialvalue=images[0], parent=self)
                if not chosen:
                    self._append('Local archive loaded. Select an image from it before searching packages.')
                    return
                if chosen not in images:
                    messagebox.showerror('Image not in local archive',
                                         'The image name must match an image reported by Docker load.', parent=self)
                    return
            self.local_loaded_path = result['archive']
            self.local_loaded_image.set(chosen)
            self.app.state['package_finder_local_image'] = chosen
            self.app.state['package_finder_local_loaded_path'] = self.local_loaded_path
            loaded_mode = ('Local Docker image archive' if result.get('type') == 'docker'
                           else 'Local Linux rootfs archive')
            self.app.state['package_finder_local_loaded_mode'] = loaded_mode
            self._append('Local distribution available in Docker Desktop: ' + chosen)
            self._append('Inspecting the local distribution; then enter a package keyword and search.')
            self.refresh_from_project_state()
            self.after(25, self.inspect_image)
        elif name == 'search':
            records, raw = result
            warning = re.search(r'(?:GPG error|KEYEXPIRED|NO_PUBKEY|signatures were invalid|not signed)', raw, re.IGNORECASE)
            self.repo_signature_key = (self._image(), self._selected_platform(),
                                       self.use_archive.get(), self.repo_override.get().strip())
            self.repo_signature_warning = warning.group(0) if warning else ''
            if warning:
                self._append('WARNING: APT could not verify the repository signature (' +
                             warning.group(0) + '). Package authenticity is not established.')
            self.available = {row['name']: row for row in records}
            for item in self.table.get_children():
                self.table.delete(item)
            for index, row in enumerate(records):
                self.table.insert('', 'end', iid=row['name'], tags=('even' if index % 2 == 0 else 'odd',),
                                  values=(row['name'], row.get('version', ''), row['description']))
            self._sort_results()
            self.results_status.set(str(len(records)) + ' package choices listed — no package archives downloaded. Select one, then click Run selected action')
            self.details.delete('1.0', 'end')
            self.details.insert('end', 'Select the exact package you want from the table above.')
            self._append('Found ' + str(len(records)) + ' package choices. Search only read repository indexes; no package binaries were downloaded.')
            if records:
                self._append('PACKAGE LIST: ' + ', '.join(row['name'] for row in records[:25]) + (' ...' if len(records) > 25 else ''))
                self._append('Select the exact package to download and save, extract, or add to runtime/builder.')
            if not records:
                self._append('No matching precompiled package. Try another keyword or Linux distribution version.')
            if not records and raw.strip():
                self._append(raw[-1800:])
        elif name == 'details':
            self.details.delete('1.0', 'end')
            self.details.insert('end', result)
            self._append('Displayed available version, dependency and description information.')
        elif name == 'download':
            manifest, raw = result
            self.last_manifest = manifest
            self._append('Saved and SHA-256 verified ' + str(len(manifest['files'])) + ' selected package archive(s):')
            for file in manifest['files']:
                self._append('  ' + file['path'])
                try:
                    package = describe_local_package(file['path'])
                    if package['dependencies']:
                        self._append('PACKAGE REQUIREMENTS FOR ' + package['name'] + ': ' + package['dependencies'])
                        self._append('These dependencies are NOT included in this package download. '
                                     'Builder installation checks which ones are already installed or must be supplied.')
                except (OSError, ValueError) as exc:
                    self._append('Could not read package dependencies: ' + str(exc))
            self._show_saved_package(manifest)
            if 'UNVERIFIED' in str(manifest.get('verification') or '').upper():
                self._append('SECURITY WARNING: This archive is not signature-authenticated. Do not treat its SHA-256 as proof of provenance.')
            self._append(raw[-1200:])
            records = list(self.app.state.get('package_finder_downloads') or [])
            records.append(manifest)
            self.app.state['package_finder_downloads'] = records
            pending = self.pending_after_download
            self.pending_after_download = None
            if pending == 'runtime':
                self.after(50, self.add_to_runtime)
            elif pending == 'builder':
                self.after(50, self.install_into_builder)
            elif pending == 'extract':
                self.after(50, self.extract_selected_package)
        elif name == 'extract':
            self._append('EXTRACTED ' + str(len(result.get('files') or [])) +
                         ' compiled executable files to: ' + result['folder'])
            self._append('These are Linux executables and may need Linux shared libraries to run.')
            records = list(self.app.state.get('package_finder_extractions') or [])
            records.append(result)
            self.app.state['package_finder_extractions'] = records
        elif name == 'source':
            manifest, raw = result
            self.last_source_manifest = manifest
            self._append('Downloaded ' + str(len(manifest['files'])) + ' distribution source-package files:')
            for file in manifest['files']:
                self._append('  ' + file['path'])
            self._append(raw[-1200:])
            records = list(self.app.state.get('package_finder_source_downloads') or [])
            records.append(manifest)
            self.app.state['package_finder_source_downloads'] = records
        elif name == 'builder':
            tag, manifest = result
            self.app.state['builder_image'] = tag
            self.app.state['builder_base_archive'] = ''
            records = list(self.app.state.get('package_finder_builder_installs') or [])
            records.append({'image': tag, 'from_image': manifest.get('installed_builder_base', ''),
                            'package_source_image': manifest['image'], 'manifest': manifest})
            self.app.state['package_finder_builder_installs'] = records
            self._append('BUILDER-ONLY IMAGE CREATED: ' + tag)
            self._append('Tab 4 will compile with this image; the final runtime image remains unchanged.')
            self.refresh_from_project_state()

    def inspect_image(self):
        image = self._image()
        if not image:
            if self.source_mode.get() in ('Local Docker image archive', 'Local Linux rootfs archive'):
                self.load_local_archive()
                return
            messagebox.showwarning('Choose Linux image',
                                   'Choose a Linux distribution and an exact version tag. Use Find / count versions to list downloaded or available image versions.', parent=self)
            return
        self.inspected_images.add((image, self._selected_platform()))
        platform = self._selected_platform()
        self.inspect_requested_image = image
        self.inspect_requested_platform = platform
        self._work('inspect', lambda progress: inspect_repository_image(image, self.cancel, progress, platform))

    def fetch_versions(self):
        mode = self.source_mode.get()
        if mode == 'Downloaded Docker images':
            self._work('local_versions', lambda progress: list_local_docker_images(self.cancel, progress))
            return
        if mode in ('Local Docker image archive', 'Local Linux rootfs archive'):
            self.load_local_archive()
            return
        repository = DISTRIBUTION_REPOSITORIES.get(self.distribution_name.get(), '')
        if not repository:
            messagebox.showwarning('Choose distribution', 'Select a distribution before retrieving its versions.', parent=self)
            return
        if str(self.app.state.get('package_download_policy') or '').lower() == 'offline':
            messagebox.showwarning('Network policy', 'The project is offline. Change network policy in Tab 1 first.', parent=self)
            return
        filter_text = self.distribution_tag.get().strip()
        explanation = ('Search older tags containing: ' + filter_text + '\n' if filter_text else 'List recently published tags.\n')
        if not messagebox.askyesno('Approve Docker Hub lookup',
                                   'Retrieve Docker image versions for ' + repository + ' from hub.docker.com?\n' +
                                   explanation + '\nThis only lists versions; no image will be downloaded.', parent=self):
            return
        self._work('versions', lambda progress: (repository, filter_text,
                   list_distribution_tags(repository, self.cancel, progress, filter_text=filter_text)))

    def browse_local_archive(self):
        file = filedialog.askopenfilename(parent=self, title='Choose a local Linux image or rootfs TAR archive',
                                          filetypes=[('Linux TAR archives', '*.tar *.tar.gz *.tgz *.tar.xz *.txz *.tar.bz2 *.tbz2 *.tar.zst'),
                                                     ('All files', '*.*')])
        if file:
            self.local_archive.set(file)
            self._source_changed()

    def load_local_archive(self):
        mode = self.source_mode.get()
        if mode not in ('Local Docker image archive', 'Local Linux rootfs archive'):
            return
        path = Path(self.local_archive.get().strip()).expanduser()
        if not path.is_file():
            messagebox.showwarning('Choose an existing local archive',
                                   'Browse to a Docker image TAR archive or a Linux root-filesystem TAR archive first.', parent=self)
            return
        category = 'docker' if mode == 'Local Docker image archive' else 'rootfs'
        size = self._size_text(path.stat().st_size)
        explanation = ('Docker will restore the image and its existing tags.' if category == 'docker'
                       else 'Docker will import the Linux filesystem as a new, separately tagged image.')
        if not messagebox.askyesno('Load local Linux distribution',
                                   'Selected file:\n' + str(path) + '\nArchive size: ' + size +
                                   '\n\n' + explanation +
                                   '\n\nLoading an archive can import or replace Docker image tags. Only use files from sources you trust.' +
                                   '\nNo download from a Docker registry is needed. Proceed?', parent=self):
            return
        self._save_source_settings()
        platform = self._selected_platform()
        self._work('local_load', lambda progress: load_local_distribution_archive(
                   str(path), category, platform, self.cancel, progress))

    def pull_image(self):
        image = self._image()
        if not image:
            messagebox.showwarning('Choose Linux image', 'Choose a distribution and version, or enter a full custom Docker image name.', parent=self)
            return
        if str(self.app.state.get('package_download_policy') or '').lower() == 'offline':
            messagebox.showwarning('Network policy', 'The project is offline. Change network policy in Tab 1 first.', parent=self)
            return
        tag = self.distribution_tag.get().strip()
        platform = self._selected_platform()
        release = self.release_tags.get(tag)
        if release and platform:
            architecture = platform.split('/')[1]
            supported = release.get('architectures') or []
            if supported and architecture not in supported:
                if not messagebox.askyesno('Architecture not listed',
                                           'Docker Hub does not list ' + architecture + ' for ' + image + '.\n\nAttempt download anyway?', parent=self):
                    return
        size = self._known_image_size(image, platform)
        if size:
            self._confirm_pull(image, platform, size)
            return
        self._work('size', lambda progress: (image, platform,
                   estimate_docker_hub_image_size(image, platform, self.cancel, progress)))

    def _confirm_pull(self, image, platform, size):
        if image != self._image() or platform != self._selected_platform():
            return
        estimate = (self._size_text(size) + ' (Docker Hub reported; actual download may be smaller with cached layers)'
                    if size else 'Unavailable from Docker Hub; actual transfer size is unknown')
        if not messagebox.askyesno('Download Linux image',
                                   'Run docker pull for:\n' + image + '\nArchitecture: ' + (platform or 'Docker default') +
                                   '\nEstimated download size: ' + estimate +
                                   '\n\nThis downloads a Linux image to Docker Desktop. It does not replace the builder or runtime in Tab 1. Continue?', parent=self):
            return
        self._work('pull', lambda progress: pull_repository_image(image, platform, self.cancel, progress))

    def _ready(self):
        if self.image_info is None or self.image_info.get('image') != self._image() or self.image_info.get('platform', '') != self._selected_platform():
            messagebox.showwarning('Package Finder', 'Search for a package in the selected Linux distribution first.', parent=self)
            return False
        return True

    def _repository_settings(self):
        archive = self.use_archive.get()
        override = self.repo_override.get().strip()
        self.app.state['package_finder_archive_mode'] = archive
        self.app.state['package_finder_repository_override'] = override
        self.app.state['package_finder_archive_image'] = self._image()
        return archive, override

    def run_selected_action(self):
        if not self.table.selection():
            messagebox.showwarning('Select a binary package',
                                   'Select the package you want in the search results first.', parent=self)
            return
        action = self.selected_action.get()
        if action == 'Save selected precompiled package':
            self.download()
        elif action == 'Extract executable files to folder':
            self.extract_selected_package()
        elif action == 'Add binary packages to final runtime':
            self.add_to_runtime()
        elif action == 'Install binary packages in builder':
            self.install_into_builder()

    def extract_selected_package(self):
        selected = self.table.selection()
        if not selected:
            messagebox.showwarning('Select a package', 'Choose a package in the search results first.', parent=self)
            return
        package = selected[0]
        manifest = self._cached_selection(package)
        if not manifest:
            if not messagebox.askyesno('Download before executable extraction',
                                       'The selected package is not cached yet. Download ' + package +
                                       ' only (without installing or resolving dependencies), then extract its executable files to your selected folder?', parent=self):
                return
            self.pending_after_download = 'extract'
            if not self.download():
                self.pending_after_download = None
            return
        folder = self.cache.get().strip()
        if not folder:
            self.choose_cache()
            folder = self.cache.get().strip()
        if not folder:
            return
        if not messagebox.askyesno('Extract Linux executable files',
                                   'Extract the regular executable files from ' + package +
                                   ' inside a temporary Linux container and save them under:\n' + folder +
                                   '\n\nLinux executables may require additional shared libraries. Continue?', parent=self):
            return
        self._work('extract', lambda progress: extract_package_executables(manifest, folder, self.cancel, progress))

    def _cached_selection(self, package):
        image = self._image()
        platform = self._selected_platform()
        records = [self.last_manifest] + list(reversed(self.app.state.get('package_finder_downloads') or []))
        for manifest in records:
            if not isinstance(manifest, dict) or manifest.get('package') != package or manifest.get('image') != image:
                continue
            if manifest.get('platform', '') != platform:
                continue
            try:
                self._validated_files(manifest)
                self.last_manifest = manifest
                return manifest
            except (OSError, ValueError):
                continue
        if self.image_info and self.image_info.get('image') == image:
            manifest = cached_repository_package(self.image_info, package, self.cache.get().strip())
            if manifest:
                self.last_manifest = manifest
                return manifest
        return None

    def _network_ok(self, action):
        if str(self.app.state.get('package_download_policy') or '').lower() == 'offline':
            messagebox.showwarning('Network policy', 'The project is set to offline. Change network policy in Tab 1 before repository access.', parent=self)
            return False
        info = self.image_info or {}
        override = self.repo_override.get().strip()
        if self.use_archive.get() and not override:
            try:
                repositories = _repository_override(info, archive=True)
            except ValueError:
                repositories = 'An archived repository for ' + info.get('pretty_name', 'selected distribution')
        else:
            repositories = override or '\n'.join((info.get('repos') or [])[:5]) or 'The repository configuration in the selected image'
        return messagebox.askyesno('Approve repository network access', action + '\n\nSelected image: ' + self._image() + '\nRepositories:\n' + repositories + '\n\nThe Linux package manager will use these sources. Verify their authenticity and compatibility. Archived releases can contain unsupported software. Continue?', parent=self)

    def search(self, retry_approved=False):
        query = self.query.get().strip()
        if not query:
            messagebox.showwarning('Package keyword required', 'Enter a package keyword to search the selected distribution.', parent=self)
            return
        image = self._image()
        if self.source_mode.get() == 'Downloaded Docker images' and image not in self.local_docker_images:
            messagebox.showwarning('Select a downloaded image',
                                   'Choose an exact image version from the list of images stored in Docker Desktop. Click Find / count versions to refresh.', parent=self)
            return
        if not image:
            if self.source_mode.get() in ('Local Docker image archive', 'Local Linux rootfs archive'):
                self.pending_search = True
                self.load_local_archive()
                return
            messagebox.showwarning('Choose Linux image', 'Choose a distribution and exact image version first.', parent=self)
            return
        if self.image_info is None or self.image_info.get('image') != image or self.image_info.get('platform', '') != self._selected_platform():
            self.pending_search = True
            self.inspect_image()
            return
        if not retry_approved and not self._network_ok('Search package repository?'):
            return
        info = dict(self.image_info)
        archived, repository = self._repository_settings()
        self._work('search', lambda progress: repository_search(info, query, archived, self.cancel, repository, progress))

    def _selected(self, event=None):
        selected = self.table.selection()
        if selected:
            row = self.available.get(selected[0], {})
            self.details.delete('1.0', 'end')
            self.details.insert('end', 'Version: ' + (row.get('version') or 'not listed') + '\n' + row.get('description', ''))
            manifest = self._cached_selection(selected[0])
            if manifest:
                self._show_saved_package(manifest)
                self.details.insert('end', '\nAlready saved in the selected distribution/architecture folder.')
            else:
                self.saved_package_path.set('No downloaded package for ' + selected[0] + '.')

    def _package(self):
        selected = self.table.selection()
        if not selected:
            messagebox.showwarning('Package Finder', 'Select a package in the search results.', parent=self)
            return ''
        return selected[0]

    def details_selected(self, retry_approved=False):
        name = self._package()
        if not name or not self._ready() or (not retry_approved and not self._network_ok('Retrieve version and dependency metadata?')):
            return
        info = dict(self.image_info)
        archived, repository = self._repository_settings()
        self._work('details', lambda progress: repository_details(info, name, archived, self.cancel, repository, progress))

    def download(self, retry_approved=False):
        name = self._package()
        if not name or not self._ready():
            return False
        if self._cached_selection(name):
            manifest = self.last_manifest
            self._show_saved_package(manifest)
            self._append('Already downloaded and SHA-256 verified: ' + manifest['files'][0]['path'])
            pending = self.pending_after_download
            self.pending_after_download = None
            if pending == 'runtime':
                self.after(30, self.add_to_runtime)
            elif pending == 'builder':
                self.after(30, self.install_into_builder)
            elif pending == 'extract':
                self.after(30, self.extract_selected_package)
            return True
        if not retry_approved and not self._network_ok('Download ONLY the selected precompiled package (not its dependencies)?'):
            return False
        info = dict(self.image_info)
        archived, repository = self._repository_settings()
        cache = self.cache.get().strip()
        warning_key = (self._image(), self._selected_platform(), archived, repository)
        unverified = bool(self.repo_signature_warning and self.repo_signature_key == warning_key)
        if unverified and not retry_approved:
            question = ('The package indexes for this distribution reported ' + self.repo_signature_warning +
                        '. APT cannot authenticate the archived packages using the configured signing key.\n\n' +
                        'Download only ' + name + ' WITHOUT authenticated package signatures?\n\n' +
                        'If approved, every downloaded package will be labeled UNVERIFIED in its provenance. ' +
                        'This is less secure than a verified repository. Use only archives you trust.')
            if not messagebox.askyesno('Unverified Linux package download', question, parent=self):
                self._append('User declined downloading unauthenticated package archives.')
                return False
        return bool(self._work('download', lambda progress: repository_download(info, name, cache, archived,
                   self.cancel, repository, progress, allow_unauthenticated=unverified)))

    def download_source(self, retry_approved=False):
        if not self._ready():
            return
        selected = self.table.selection()
        name = selected[0] if selected else self.query.get().strip()
        if not name:
            return
        if not retry_approved and not self._network_ok('Download distribution source package (without Windows extraction)?'):
            return
        info = dict(self.image_info)
        archived, repository = self._repository_settings()
        cache = self.cache.get().strip()
        self._work('source', lambda progress: repository_source_download(info, name, cache, archived, self.cancel, repository, progress))

    def choose_cache(self):
        folder = filedialog.askdirectory(parent=self, title='Choose local package download cache')
        if folder:
            self.cache.set(folder)
            self.app.state['package_finder_cache'] = folder

    def _show_saved_package(self, manifest):
        files = manifest.get('files') or []
        if files:
            path = Path(files[0].get('path') or '')
            if path.is_file():
                self.saved_package_path.set(str(path))
                return
        self.saved_package_path.set('Package archive missing from disk.')

    def open_saved_folder(self):
        path = Path(self.saved_package_path.get().strip())
        if not path.is_file():
            messagebox.showwarning('No saved package',
                                   'There is no downloaded package to open. Select a package and choose Save selected precompiled package.',
                                   parent=self)
            return
        try:
            folder = str(path.parent)
            if os.name == 'nt':
                os.startfile(folder)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', folder])
            else:
                subprocess.Popen(['xdg-open', folder])
        except (OSError, ValueError) as exc:
            messagebox.showerror('Unable to open folder', str(exc), parent=self)

    def copy_saved_path(self):
        path = Path(self.saved_package_path.get().strip())
        if not path.is_file():
            messagebox.showwarning('No saved package', 'Download a package before copying its path.', parent=self)
            return
        self.clipboard_clear()
        self.clipboard_append(str(path))
        self.update()

    def _validated_files(self, manifest):
        files = []
        for entry in manifest.get('files') or []:
            path = Path(entry['path'])
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
                raise ValueError('Cached package missing or checksum mismatch: ' + str(path))
            files.append(path)
        if not files:
            raise ValueError('No downloaded files are available. Download a package first.')
        return files

    def _manifest(self, action):
        selected = self.table.selection()
        selected_name = selected[0] if selected else ''
        manifest = self._cached_selection(selected_name) if selected_name else None
        if not manifest:
            if not selected_name:
                messagebox.showwarning('Package Finder', 'Select a package in the search results first.', parent=self)
                return None
            if not messagebox.askyesno('Download selected package first?',
                                       'The selected package ' + selected_name + ' has not been downloaded to the cache.\n\n' +
                                       'Download just this package archive (no dependencies), then automatically continue with ' + action + '?',
                                       parent=self):
                return None
            self.pending_after_download = 'runtime' if action == 'final runtime' else 'builder'
            if not self.download():
                self.pending_after_download = None
            return None
        verification = str(manifest.get('verification') or '')
        warning = ('\n\nSECURITY WARNING: Package source is not authenticated.\n' + verification
                   if 'UNVERIFIED' in verification.upper() else '')
        if not messagebox.askyesno('Confirm package use',
                                   'Use downloaded ' + manifest['package'] + ' package for ' + action + '?\n\n' +
                                   'The archive is specific to ' + manifest['os'] + ' (' + manifest['architecture'] + ').\n' +
                                   'Dependencies are not bundled; installation may require separately available dependencies.' +
                                   warning, parent=self):
            return None
        return manifest

    def add_to_runtime(self):
        manifest = self._manifest('final runtime')
        if not manifest:
            return
        runtime = str(self.app.state.get('base_image') or '').strip()
        if not runtime:
            messagebox.showwarning('Missing runtime', 'Select a runtime image in Tab 1 first.', parent=self)
            return
        if manifest['image'] != runtime:
            warning = ('The downloaded packages were built for:\n' + str(manifest.get('os') or manifest['image']) +
                       '\nSource image: ' + manifest['image'] + '\n\nSelected runtime image: ' + runtime +
                       '\n\nDifferent distributions, releases, or CPU architectures can make these packages incompatible. ' +
                       'Tab 6 must independently validate installation. Add the packages anyway?')
            if not messagebox.askyesno('Check distribution compatibility', warning, parent=self):
                return
        try:
            files = self._validated_files(manifest)
            components = list(self.app.state.get('components') or [])
            existing = {(str(c.get('kind', '')).lower(), str(c.get('source', ''))) for c in components if isinstance(c, dict)}
            added = 0
            for path in files:
                if ('os package', str(path)) in existing:
                    continue
                pkg, version = package_identity(path)
                components.append({'enabled': True, 'name': pkg, 'version': version, 'kind': 'OS package',
                                   'source': str(path), 'destination': '', 'depends': '',
                                   'build_system': '', 'build_command': '', 'build_deps': '',
                                   'runtime_packages': '', 'output_rel': '', 'validation': '',
                                   'add_to_path': False, 'base_match': '', 'local_package_files': [str(path)]})
                added += 1
            self.app.state['components'] = components
            self._append('ADDED ' + str(added) + ' binary OS packages to Tab 3 for final-image installation in Tab 6.')
        except Exception as exc:
            messagebox.showerror('Package Finder', str(exc), parent=self)

    def install_into_builder(self):
        manifest = self._manifest('builder-only installation')
        if not manifest:
            return
        builder = effective_builder_image(self.app.state)
        if not builder:
            messagebox.showwarning('No builder', 'Select or load a builder image in Tab 1 before installing packages.', parent=self)
            return
        try:
            paths = self._validated_files(manifest)
        except Exception as exc:
            messagebox.showerror('Package Finder', str(exc), parent=self)
            return
        self._work('builder', lambda progress: self._build_builder_image(manifest, paths, builder, progress))

    def _build_builder_image(self, manifest, paths, builder_image, progress=None):
        family = manifest['manager']
        if family not in ('apt', 'apk', 'dnf'):
            raise RuntimeError('Offline installation is not supported for this package manager.')
        archive_suffix = {'apt': '.deb', 'apk': '.apk', 'dnf': '.rpm'}[family]
        if any(path.suffix != archive_suffix for path in paths):
            raise RuntimeError('Downloaded package format does not match the image manager.')
        if not re.fullmatch(r'[A-Za-z0-9_./:@+-]+', builder_image):
            raise RuntimeError('Invalid builder Docker image reference.')
        if progress:
            progress('Verifying that the actual builder distribution matches the package source...')
        builder_info = inspect_repository_image(builder_image, self.cancel, progress)
        builder_manager = builder_info.get('manager', '')
        manager_compatible = builder_manager == family or (family == 'dnf' and builder_manager in ('dnf', 'yum'))
        source_id = str(manifest.get('distribution_id') or '').lower()
        source_version = str(manifest.get('distribution_version') or '')
        source_arch = str(manifest.get('architecture') or '')
        if manifest['image'] != builder_image and (not source_id or not source_version):
            raise RuntimeError('The cached packages lack distribution version metadata. Re-download them from the desired distribution before installing in a different builder.')
        mismatches = []
        if not manager_compatible:
            mismatches.append('package manager: ' + family + ' vs ' + builder_manager)
        if source_id and source_id != str(builder_info.get('id') or '').lower():
            mismatches.append('distribution: ' + source_id + ' vs ' + str(builder_info.get('id') or '?'))
        if source_version and source_version != str(builder_info.get('version_id') or ''):
            mismatches.append('release: ' + source_version + ' vs ' + str(builder_info.get('version_id') or '?'))
        if source_arch and source_arch != str(builder_info.get('arch') or ''):
            mismatches.append('architecture: ' + source_arch + ' vs ' + str(builder_info.get('arch') or '?'))
        if mismatches:
            raise RuntimeError('Cannot install packages compiled for another Linux distribution into the selected builder.\n' +
                               '\n'.join(mismatches) + '\nChoose a matching package-search distribution or builder image.')
        if family == 'apt':
            if progress:
                progress('Checking every downloaded DEB dependency against the actual builder and selected local archives...')
            preflight = preflight_local_builder_packages(builder_image, paths, self.cancel, progress)
            if preflight['missing']:
                raise RuntimeError('OFFLINE INSTALLATION STOPPED BEFORE DOCKER BUILD: required dependencies are missing:\n' +
                                   '\n'.join(row['package'] + ' needs ' + row['requirement'] +
                                             ' [' + row['status'] + ']' for row in preflight['missing']) +
                                   '\n\nDownload the missing dependency DEB archives, then use Tab 3 > '
                                   'Install local package into builder > Browse package file(s) to select the '
                                   'original package AND its dependencies together. Check dependencies before installing. '
                                   'A single package archive may not include its required dependencies.')
        digest = hashlib.sha256((builder_image + ''.join(e['sha256'] for e in manifest['files'])).encode()).hexdigest()[:16]
        tag = 'component-builder-pkgs:' + digest
        with tempfile.TemporaryDirectory(prefix='docker_pkg_builder_') as work:
            root = Path(work)
            (root / 'packages').mkdir()
            for idx, path in enumerate(paths):
                shutil.copy2(path, root / 'packages' / (str(idx).zfill(4) + '_' + path.name))
            install = {'apt': 'dpkg -i /tmp/package-cache/*.deb',
                       'apk': 'apk add --no-network /tmp/package-cache/*.apk',
                       'dnf': 'rpm -Uvh --replacepkgs /tmp/package-cache/*.rpm'}[family]
            text = 'FROM ' + builder_image + '\nUSER root\nCOPY packages/ /tmp/package-cache/\nRUN set -eu; ' + install + '; rm -rf /tmp/package-cache\n'
            (root / 'Dockerfile').write_text(text, encoding='utf-8')
            _run(['docker', 'build', '--pull=false', '--network=none', '-t', tag, str(root)], 600, self.cancel, progress)
        installed = dict(manifest)
        installed['installed_builder_base'] = builder_image
        return tag, installed

    def import_source(self):
        if self.last_source_manifest:
            candidates = [f['path'] for f in self.last_source_manifest['files'] if re.search(r'\.(?:orig\.)?tar\.(?:gz|xz|bz2)$', f['name'], re.I)]
            if candidates and messagebox.askyesno('Use downloaded source', 'Use the distribution source archive just downloaded from APT?\n\nNote: Debian patches may be stored in a separate archive, so the complete source build may need the corresponding packaging steps.', parent=self):
                self._add_source_archive(candidates[0])
                return
        file = filedialog.askopenfilename(parent=self, title='Choose official source archive (not unpacked on Windows)',
                                          filetypes=[('Source archives', '*.zip *.tar *.tar.gz *.tgz *.tar.xz *.txz *.tar.bz2 *.tbz2'), ('All files', '*.*')])
        if not file:
            return
        self._add_source_archive(file)

    def _add_source_archive(self, file):
        components = list(self.app.state.get('components') or [])
        name = Path(file).name
        for extension in ('.tar.gz', '.tar.xz', '.tar.bz2', '.tgz', '.txz', '.tbz2', '.tar', '.zip'):
            if name.lower().endswith(extension):
                name = name[:-len(extension)]
                break
        components.append({'enabled': True, 'name': name, 'version': '', 'kind': 'Source', 'source': file,
                           'destination': '', 'depends': '', 'build_system': '', 'build_command': '',
                           'build_deps': '', 'runtime_packages': '', 'output_rel': '', 'validation': '',
                           'add_to_path': False, 'base_match': '', 'local_package_files': []})
        self.app.state['components'] = components
        self._append('Source archive added directly to Tab 3: ' + file)
        self._append('Tab 4 extracts it inside Docker without Windows filesystem symlink restrictions.')
