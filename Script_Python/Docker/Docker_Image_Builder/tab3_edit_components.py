import re
import tkinter as tk
from pathlib import PurePosixPath
from tkinter import messagebox, ttk

from image_removals import normalize_removals, protected_package, removal_id, safe_file_path, safe_package_name


class EditComponentsTab(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg='#EAF2F8')
        self.app = app
        self.records = {}
        self.sort_col = 'name'
        self.sort_desc = False
        self.column_labels = {
            'origin': 'Origin', 'name': 'Component', 'kind': 'Type', 'version': 'Version',
            'path': 'Source / Location', 'enabled': 'Enabled', 'status': 'Status',
        }
        self.search = tk.StringVar()
        self.scope = tk.StringVar(value='Project + installed')
        self.summary = tk.StringVar()
        tk.Label(self, text='3 — EDIT COMPONENT', bg='#1F618D', fg='white',
                 font=('Segoe UI', 16, 'bold'), anchor='w', padx=14, pady=10).pack(fill='x')
        actions = tk.Frame(self, bg='#EAF2F8')
        actions.pack(fill='x', padx=12, pady=(11, 7))
        tk.Button(actions, text='Edit Selected', bg='#85C1E9', command=self.edit_selected).pack(side='left', padx=4)
        tk.Button(actions, text='Remove Selected', bg='#F1948A', command=self.remove_selected).pack(side='left', padx=4)
        tk.Button(actions, text='Enable / Disable', bg='#AED6F1', command=self.toggle_selected).pack(side='left', padx=4)
        tk.Button(actions, text='Cancel Removal', bg='#F7DC6F', command=self.cancel_removal).pack(side='left', padx=4)
        tk.Button(actions, text='Refresh', command=self.refresh_from_project_state).pack(side='left', padx=4)
        filters = tk.Frame(self, bg='#EAF2F8')
        filters.pack(fill='x', padx=16, pady=(3, 7))
        tk.Label(filters, text='Show:', bg='#EAF2F8').pack(side='left')
        selector = ttk.Combobox(filters, textvariable=self.scope, state='readonly', width=24,
                                values=('Project + installed', 'Project components', 'Installed in image', 'Scheduled removals'))
        selector.pack(side='left', padx=(6, 18))
        selector.bind('<<ComboboxSelected>>', lambda event: self.refresh_from_project_state())
        tk.Label(filters, text='Search:', bg='#EAF2F8').pack(side='left')
        tk.Entry(filters, textvariable=self.search).pack(side='left', fill='x', expand=True, padx=(7, 0))
        self.search.trace_add('write', lambda *_: self.refresh_from_project_state())
        frame = tk.Frame(self, bg='#EAF2F8')
        frame.pack(fill='both', expand=True, padx=12, pady=(0, 8))
        columns = tuple(self.column_labels)
        self.tree = ttk.Treeview(frame, columns=columns, show='headings', selectmode='extended', height=20)
        for key, title in self.column_labels.items():
            width = {'origin': 140, 'name': 200, 'kind': 135, 'version': 120,
                     'path': 460, 'enabled': 85, 'status': 170}[key]
            self.tree.heading(key, text=title, command=lambda column=key: self.sort(column))
            self.tree.column(key, width=width, minwidth=65, anchor='w')
        sy = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        sx = ttk.Scrollbar(frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        sy.grid(row=0, column=1, sticky='ns')
        sx.grid(row=1, column=0, sticky='ew')
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree.tag_configure('project', background='#E8F8F5')
        self.tree.tag_configure('installed', background='#EBF5FB')
        self.tree.tag_configure('remove', background='#FADBD8', foreground='#922B21')
        self.tree.tag_configure('disabled', foreground='#777777')
        self.tree.bind('<Double-1>', lambda event: self.edit_selected())
        tk.Label(self, textvariable=self.summary, bg='#D6EAF8', fg='#154360', anchor='w',
                 padx=12, pady=7).pack(fill='x', padx=12, pady=(0, 12))
        self.refresh_from_project_state()

    def _installed(self):
        data = self.app.state.get('base_inventory') or {}
        packages = data.get('packages') or {}
        rows = []
        for item in data.get('executables') or []:
            if not isinstance(item, dict):
                continue
            rows.append({'origin': 'Installed', 'name': str(item.get('name') or ''), 'kind': 'Executable',
                         'version': str(item.get('version') or ''), 'path': str(item.get('path') or ''),
                         'package': str(item.get('package') or '')})
        for group, kind in (('os', 'OS package'), ('python', 'Python package'), ('r', 'R package'), ('perl', 'Perl package')):
            for item in packages.get(group) or []:
                if not isinstance(item, dict):
                    continue
                rows.append({'origin': 'Installed', 'name': str(item.get('name') or ''),
                             'kind': kind, 'version': str(item.get('version') or ''), 'path': ''})
        for jar in packages.get('jars') or []:
            path = str(jar.get('path') or '') if isinstance(jar, dict) else str(jar)
            if path:
                rows.append({'origin': 'Installed', 'name': PurePosixPath(path).name,
                             'kind': 'JAR', 'version': '', 'path': path})
        return rows

    @staticmethod
    def _removal_for(record, package_mode=None):
        kind = record.get('kind', '')
        name = str(record.get('name') or '').strip()
        path = str(record.get('path') or '').strip()
        if kind == 'OS package' or package_mode == 'package':
            target = str(record.get('package') if package_mode == 'package' else name)
            if not safe_package_name(target):
                return None
            return {'kind': 'os_package', 'name': target, 'path': ''}
        if kind in ('Python package', 'R package', 'Perl package'):
            code = {'Python package': 'python_package', 'R package': 'r_package', 'Perl package': 'perl_package'}[kind]
            return {'kind': code, 'name': name, 'path': ''} if safe_package_name(name.replace('::', '')) else None
        if kind in ('Executable', 'JAR') and safe_file_path(path):
            return {'kind': 'file', 'name': name, 'path': path}
        return None

    def refresh_from_project_state(self):
        previous = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        self.records.clear()
        components = self.app.state.get('components') or []
        removals = normalize_removals(self.app.state.get('image_removals') or [])
        removed = {removal_id(r['kind'], r['name'], r['path']): r for r in removals}
        rows = []
        choice = self.scope.get()
        if choice in ('Project + installed', 'Project components'):
            for index, item in enumerate(components):
                if not isinstance(item, dict):
                    continue
                rows.append((f'project:{index}', {
                    'origin': 'Project', 'name': str(item.get('name') or ''),
                    'kind': str(item.get('kind') or ''), 'version': str(item.get('version') or ''),
                    'path': str(item.get('source') or item.get('destination') or ''),
                    'enabled': 'YES' if item.get('enabled', True) else 'NO', 'status': 'Pending addition',
                }, 'project' if item.get('enabled', True) else 'disabled'))
        if choice in ('Project + installed', 'Installed in image'):
            for index, item in enumerate(self._installed()):
                target = self._removal_for(item)
                scheduled = bool(target and removal_id(target['kind'], target['name'], target['path']) in removed)
                row = dict(item, enabled='—', status='REMOVE IN NEXT BUILD' if scheduled else 'Installed in runtime')
                rows.append((f'installed:{index}', row, 'remove' if scheduled else 'installed'))
        if choice in ('Project + installed', 'Scheduled removals'):
            for index, item in enumerate(removals):
                row = {'origin': 'Removal', 'name': str(item.get('name') or ''),
                       'kind': str(item.get('kind') or ''), 'version': '',
                       'path': str(item.get('path') or ''), 'enabled': '—', 'status': 'REMOVE IN NEXT BUILD',
                       'removal': item}
                rows.append((f'removal:{index}', row, 'remove'))
        query = self.search.get().strip().casefold()
        for iid, row, tag in rows:
            values = (row.get('origin', ''), row.get('name', ''), row.get('kind', ''), row.get('version', ''),
                      row.get('path', ''), row.get('enabled', ''), row.get('status', ''))
            if query and query not in ' '.join(map(str, values)).casefold():
                continue
            self.records[iid] = row
            self.tree.insert('', 'end', iid=iid, values=values, tags=(tag,))
        self.apply_sort()
        for iid in previous:
            if self.tree.exists(iid):
                self.tree.selection_add(iid)
        self.summary.set(f'{len(components)} project components   |   {len(removals)} scheduled removals   |   {len(self.tree.get_children())} displayed')

    def select_project_index(self, index):
        iid = f'project:{index}'
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.see(iid)
            self.tree.focus(iid)

    def sort(self, column):
        if self.sort_col == column:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_col = column
            self.sort_desc = False
        self.apply_sort()

    def apply_sort(self):
        for key, label in self.column_labels.items():
            indicator = (' ▼' if self.sort_desc else ' ▲') if key == self.sort_col else ''
            self.tree.heading(key, text=label + indicator)
        if not self.sort_col:
            return
        nodes = list(self.tree.get_children())
        nodes.sort(key=lambda iid: tuple((1, int(part)) if part.isdigit() else (0, part)
                                             for part in re.split(r'(\d+)', str(self.tree.set(iid, self.sort_col)).casefold())),
                   reverse=self.sort_desc)
        for position, iid in enumerate(nodes):
            self.tree.move(iid, '', position)

    def _selected(self):
        return [(iid, self.records[iid]) for iid in self.tree.selection() if iid in self.records]

    def edit_selected(self):
        selected = self._selected()
        if len(selected) != 1:
            messagebox.showinfo('Edit Component', 'Select one project component.', parent=self)
            return
        iid, row = selected[0]
        if not iid.startswith('project:'):
            messagebox.showinfo('Edit Component', 'Installed image files cannot be edited in place. Add a replacement in Tab 4 or schedule the existing component for removal.', parent=self)
            return
        index = int(iid.split(':', 1)[1])
        win = self.app.components_tab.component_dialog(index)
        if win is not None:
            win.bind('<Destroy>', lambda event: self.after_idle(self.refresh_from_project_state) if event.widget is win else None, add='+')

    def toggle_selected(self):
        indices = sorted({int(iid.split(':', 1)[1]) for iid, _ in self._selected() if iid.startswith('project:')})
        if not indices:
            messagebox.showinfo('Enable / Disable', 'Select project components.', parent=self)
            return
        for index in indices:
            item = self.app.state['components'][index]
            item['enabled'] = not bool(item.get('enabled', True))
        self.app.state.touch('components')
        self.refresh_from_project_state()

    def remove_selected(self):
        selected = self._selected()
        project_indices = sorted({int(iid.split(':', 1)[1]) for iid, _ in selected if iid.startswith('project:')})
        installed = [row for iid, row in selected if iid.startswith('installed:')]
        if not project_indices and not installed:
            messagebox.showinfo('Remove Component', 'Select project or installed components.', parent=self)
            return
        proposed = []
        invalid = []
        for item in installed:
            if item.get('kind') == 'Executable' and item.get('package') and safe_package_name(item['package']):
                choice = messagebox.askyesnocancel('Remove executable',
                    item['name'] + ' belongs to package ' + item['package'] + '.\n\nYes: uninstall package.\nNo: remove only executable.\nCancel: skip.', parent=self)
                if choice is None:
                    continue
                record = self._removal_for(item, 'package' if choice else None)
            else:
                record = self._removal_for(item)
            if record is None:
                invalid.append(item.get('name') or item.get('path') or '(unknown)')
            else:
                proposed.append(record)
        proposed = normalize_removals(proposed)
        existing = normalize_removals(self.app.state.get('image_removals') or [])
        known = {removal_id(x['kind'], x['name'], x['path']) for x in existing}
        new = [x for x in proposed if removal_id(x['kind'], x['name'], x['path']) not in known]
        if not project_indices and not new:
            if invalid:
                messagebox.showwarning('Remove Component', 'Unsafe or unverifiable paths: ' + ', '.join(invalid[:12]), parent=self)
            else:
                messagebox.showinfo('Remove Component', 'No new removals selected.', parent=self)
            return
        names = [self.app.state['components'][i].get('name', '') for i in project_indices]
        critical = [x['name'] for x in new if x['kind'] == 'os_package' and protected_package(x['name'])]
        details = f'Remove {len(project_indices)} project component(s) and schedule {len(new)} installed component removal(s)?'
        if names:
            details += '\n\nProject: ' + ', '.join(names[:15])
        if new:
            details += '\n\nInstalled: ' + ', '.join(x['name'] for x in new[:15])
        if critical:
            details += '\n\nWARNING: Foundational packages: ' + ', '.join(critical)
        details += '\n\nChanges to installed files apply only to the next Docker image build.'
        if not messagebox.askyesno('Confirm Component Removal', details, parent=self):
            return
        if critical and not messagebox.askyesno('Confirm Foundational Package Removal',
                                                'Uninstalling foundational OS packages can make the image unusable. Continue?', parent=self):
            return
        for index in reversed(project_indices):
            self.app.state['components'].pop(index)
        if project_indices:
            self.app.state.touch('components')
        if new:
            self.app.state['image_removals'] = normalize_removals(existing + new)
        self.app.components_tab.refresh()
        self.refresh_from_project_state()
        if invalid:
            messagebox.showwarning('Skipped unsafe targets', ', '.join(invalid[:15]), parent=self)

    def cancel_removal(self):
        selected = self._selected()
        requests = []
        for iid, row in selected:
            if iid.startswith('removal:'):
                requests.append(row['removal'])
            elif iid.startswith('installed:'):
                item = self._removal_for(row)
                if item:
                    requests.append(item)
        ids = {removal_id(x['kind'], x['name'], x['path']) for x in requests}
        before = normalize_removals(self.app.state.get('image_removals') or [])
        new = [x for x in before if removal_id(x['kind'], x['name'], x['path']) not in ids]
        if len(new) == len(before):
            messagebox.showinfo('Cancel Removal', 'No selected removal request was found.', parent=self)
            return
        self.app.state['image_removals'] = new
        self.refresh_from_project_state()
