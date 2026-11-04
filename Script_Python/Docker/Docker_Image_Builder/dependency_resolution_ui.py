import tkinter as tk
from tkinter import messagebox, ttk

from image_component_inventory import inspect_image_components
from revision_dependencies import dependency_impact, normalize_satisfactions, provider_choices


class DependencyResolutionDialog(tk.Toplevel):
    def __init__(self, parent, app, snapshot=None, checked=None):
        super().__init__(parent)
        self.app = app
        self.snapshot = snapshot
        self.checked = checked or {}
        self.rows = []
        self.title('Planned removals — dependency impact and substitute providers')
        self.geometry('1200x720')
        self.minsize(840, 520)
        self.configure(bg='#E8F8F5')
        self.transient(parent.winfo_toplevel())
        self.summary = tk.StringVar()
        tk.Label(self, text='DEPENDENCIES AFTER SCHEDULED REMOVALS', bg='#117864', fg='white',
                 font=('Segoe UI', 14, 'bold'), anchor='w', padx=12, pady=9).pack(fill='x')
        tk.Label(self, text='An assigned substitute is a USER DECLARATION, not proof of compatibility. Verify the rebuilt image in Tab 5/7.',
                 bg='#FCF3CF', fg='#7D6608', anchor='w', padx=10, pady=8).pack(fill='x', padx=10, pady=(8, 4))
        tk.Label(self, textvariable=self.summary, bg='#D5F5E3', fg='#0E6655', anchor='w', padx=8, pady=7).pack(fill='x', padx=10, pady=4)
        frame = tk.Frame(self)
        frame.pack(fill='both', expand=True, padx=10, pady=5)
        columns = ('owner', 'requirement', 'category', 'status', 'provider', 'detail')
        self.tree = ttk.Treeview(frame, columns=columns, show='headings', selectmode='browse')
        for key, title, width in (('owner', 'Required by', 165), ('requirement', 'Requirement', 180),
                                  ('category', 'Type', 120), ('status', 'Projected status', 135),
                                  ('provider', 'User-selected provider', 190), ('detail', 'Detection / verification', 420)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor='w')
        sy = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        sx = ttk.Scrollbar(frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        sy.grid(row=0, column=1, sticky='ns')
        sx.grid(row=1, column=0, sticky='ew')
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree.tag_configure('missing', background='#FADBD8')
        self.tree.tag_configure('declared', background='#FCF3CF')
        self.tree.tag_configure('found', background='#D5F5E3')
        self.tree.bind('<<TreeviewSelect>>', self._select)
        controls = tk.Frame(self, bg='#E8F8F5')
        controls.pack(fill='x', padx=12, pady=8)
        tk.Label(controls, text='Component that satisfies selected requirement:', bg='#E8F8F5').pack(side='left')
        self.provider = tk.StringVar()
        self.provider_box = ttk.Combobox(controls, textvariable=self.provider, width=40)
        self.provider_box.pack(side='left', padx=7)
        tk.Button(controls, text='Assign provider', bg='#48C9B0', command=self.assign).pack(side='left', padx=3)
        tk.Button(controls, text='Clear assignment', bg='#F5B7B1', command=self.clear).pack(side='left', padx=3)
        tk.Button(controls, text='Recalculate', bg='#A2D9CE', command=self.refresh).pack(side='left', padx=3)
        tk.Button(controls, text='Close', command=self.destroy).pack(side='right', padx=4)
        self.refresh()

    def _load_snapshot(self):
        if self.snapshot is not None:
            return self.snapshot
        archive = str(self.app.state.get('runtime_base_archive') or '')
        if not archive:
            return {}
        try:
            return inspect_image_components(archive)
        except Exception:
            return {}

    def refresh(self):
        self.snapshot = self._load_snapshot()
        previous = self.tree.selection()
        selected_key = None
        if previous:
            old = int(previous[0])
            if old < len(self.rows):
                selected_key = (self.rows[old]['owner'], self.rows[old]['requirement'])
        self.rows = dependency_impact(self.app.state, self.snapshot, self.checked)
        self.provider_box.configure(values=provider_choices(self.app.state, self.snapshot))
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(self.rows):
            tag = 'found' if row['status'] == 'FOUND' else 'declared' if row['status'] in ('PLANNED', 'USER DECLARED') else 'missing'
            self.tree.insert('', 'end', iid=str(index), values=(row['owner'], row['requirement'], row['category'],
                         row['status'], row['provider'], row['detail']), tags=(tag,))
            if selected_key == (row['owner'], row['requirement']):
                self.tree.selection_set(str(index))
        missing = sum(row['status'] in ('MISSING', 'UNVERIFIED', 'UNRESOLVED', 'RECHECK', 'INCOMPATIBLE') for row in self.rows)
        declarations = sum(row['status'] == 'USER DECLARED' for row in self.rows)
        self.summary.set(f'{len(self.app.state.get("image_removals", []))} planned removals  |  '
                         f'{len(self.rows)} identified requirements  |  '
                         f'{missing} missing/unverified/recheck  |  {declarations} user-declared substitutes')
        self._select()

    def _selected_row(self):
        selected = self.tree.selection()
        if not selected:
            return None
        index = int(selected[0])
        return self.rows[index] if index < len(self.rows) else None

    def _select(self, event=None):
        row = self._selected_row()
        self.provider.set(row['provider'] if row else '')

    def _notify_state(self):
        touch = getattr(self.app.state, 'touch', None)
        if callable(touch):
            touch('dependency_satisfactions')
        self.refresh()
        tab = getattr(self.app, 'runtime_tab', None)
        if tab is not None:
            tab.refresh_from_project_state()

    def assign(self):
        row = self._selected_row()
        if not row:
            messagebox.showwarning('Provider', 'Select a dependency first.', parent=self)
            return
        provider = self.provider.get().strip()
        if not provider or len(provider) > 300:
            messagebox.showwarning('Provider', 'Enter or select a component name, OS package, runtime, or executable path.', parent=self)
            return
        if not messagebox.askyesno('Confirm user-declared substitution',
                                   row['owner'] + ' requires ' + row['requirement'] + '.\n\n'
                                   'Record ' + provider + ' as the user-selected provider?\n'
                                   'This does not prove it supplies the required functions or version.', parent=self):
            return
        records = normalize_satisfactions(self.app.state.get('dependency_satisfactions'))
        records = [x for x in records if (x['owner'].lower(), x['requirement'].lower()) != (row['owner'].lower(), row['requirement'].lower())]
        records.append({'owner': row['owner'], 'requirement': row['requirement'],
                        'provider': provider, 'status': 'USER DECLARED', 'notes': ''})
        self.app.state['dependency_satisfactions'] = records
        self._notify_state()

    def clear(self):
        row = self._selected_row()
        if not row:
            return
        self.app.state['dependency_satisfactions'] = [x for x in normalize_satisfactions(self.app.state.get('dependency_satisfactions'))
                                                      if (x['owner'].lower(), x['requirement'].lower()) != (row['owner'].lower(), row['requirement'].lower())]
        self._notify_state()
