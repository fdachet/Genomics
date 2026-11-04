import tkinter as tk
from tkinter import ttk, messagebox

from general_environment import FIELDS, detect, defaults, normalize, package_plan, items, version, custom_directives
from dependency_planner import identify_runtime_family


LABELS = (
    ('java_version', 'Java major version (optional)', 1),
    ('python_version', 'Minimum Python version', 1),
    ('python_packages', 'Python packages (pip)', 4),
    ('r_version', 'Minimum R version', 1),
    ('cran_packages', 'R packages (CRAN)', 4),
    ('bioc_packages', 'R packages (Bioconductor)', 4),
    ('perl_version', 'Minimum Perl version', 1),
    ('cpan_modules', 'Perl modules (CPAN)', 4),
    ('os_packages', 'Additional OS packages', 3),
    ('pre_commands', 'Custom setup BEFORE application files', 5),
    ('post_commands', 'Custom setup AFTER application files', 5),
    ('verify_commands', 'Custom final-image verification commands', 4),
    ('dockerfile_directives', 'Additional Dockerfile instructions (RUN, ENV, CMD, ENTRYPOINT, EXPOSE, etc.)', 5),
)


class EnvironmentEditor(tk.Toplevel):
    def __init__(self, owner, state):
        super().__init__(owner)
        self.state = state
        self.title('Language Environments / Custom Docker Setup')
        self.geometry('1020x820')
        self.minsize(720, 580)
        self.configure(bg='#EAF7F2')
        self.transient(owner.winfo_toplevel())
        self.config_data = normalize(state.get('environment_requirements'))
        header = tk.Frame(self, bg='#0D7868', padx=14, pady=10)
        header.pack(fill='x')
        tk.Label(header, text='LANGUAGE RUNTIMES, PACKAGES AND CUSTOM SETUP', bg='#0D7868', fg='white', font=('Segoe UI', 13, 'bold')).pack(anchor='w')
        outer = tk.Frame(self, bg='#EAF7F2')
        outer.pack(fill='both', expand=True)
        canvas = tk.Canvas(outer, bg='#EAF7F2', highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        scroll.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        form = tk.Frame(canvas, bg='#EAF7F2')
        win = canvas.create_window((0, 0), window=form, anchor='nw')
        form.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(win, width=event.width))
        self.fields = {}
        tk.Label(form, text='Enter minimum interpreter versions and one package per line. Blank fields impose no explicit requirement. Application files and folders remain registered in Tab 3.', bg='#EAF7F2', fg='#165D52', justify='left', wraplength=900).pack(fill='x', padx=18, pady=(14, 8))
        for field, title, rows in LABELS:
            tk.Label(form, text=title, bg='#EAF7F2', font=('Segoe UI', 10, 'bold'), anchor='w').pack(fill='x', padx=18, pady=(12, 3))
            if rows == 1:
                item = tk.Entry(form, font=('Consolas', 10))
                item.pack(fill='x', padx=18)
                item.insert(0, self.config_data[field])
            else:
                item = tk.Text(form, height=rows, font=('Consolas', 10), wrap='none', undo=True)
                item.pack(fill='x', padx=18)
                item.insert('1.0', self.config_data[field])
            self.fields[field] = item
        self.auto_var = tk.BooleanVar(value=self.config_data['auto_detect'])
        self.network_var = tk.BooleanVar(value=self.config_data['allow_custom_network'])
        tk.Checkbutton(form, text='Suggest dependencies from registered source/scripts and dependency manifests', variable=self.auto_var, bg='#EAF7F2').pack(anchor='w', padx=16, pady=(15, 3))
        tk.Checkbutton(form, text='Custom setup commands may require network access (request approval before build)', variable=self.network_var, bg='#EAF7F2').pack(anchor='w', padx=16, pady=3)
        tk.Label(form, text='Custom commands run as root inside the Docker BUILD environment. Use Linux shell syntax, not Windows commands. Docker builds without network unless a download is approved. These commands are trusted instructions and can change the image.', bg='#EAF7F2', fg='#B03A2E', wraplength=900, justify='left').pack(fill='x', padx=18, pady=(8, 15))
        footer = tk.Frame(self, bg='#CFECE0', padx=12, pady=9)
        footer.pack(fill='x')
        tk.Button(footer, text='Save environment', bg='#138D75', fg='white', command=self.save).pack(side='right', padx=6)
        tk.Button(footer, text='Cancel', command=self.destroy).pack(side='right', padx=6)
        tk.Button(footer, text='Detect requirements', bg='#AED6F1', command=self.preview).pack(side='left', padx=6)
        tk.Button(footer, text='Insert detected packages', bg='#A2D9CE', command=self.insert_detected).pack(side='left', padx=6)

    def data(self):
        result = defaults()
        for key, widget in self.fields.items():
            result[key] = (widget.get() if isinstance(widget, tk.Entry) else widget.get('1.0', 'end')).strip()
        result['auto_detect'] = self.auto_var.get()
        result['allow_custom_network'] = self.network_var.get()
        return result

    def preview(self):
        result = detect(self.state.get('components', []))
        lines = ['Requirements detected from registered files (review before use):', '']
        for key, values in result['packages'].items():
            lines.append(key + ': ' + (', '.join(values) or 'none'))
        lines += ['', 'Minimum versions declared in manifests: ' + ', '.join(key + ' ' + val for key, val in result['versions'].items() if val), 'Language hints: ' + ', '.join(key for key, present in result['hints'].items() if present)]
        lines += ['', *result['issues']]
        window = tk.Toplevel(self)
        window.title('Detected requirements')
        window.geometry('900x480')
        text = tk.Text(window, font=('Consolas', 10), wrap='word')
        text.pack(fill='both', expand=True)
        text.insert('1.0', '\n'.join(lines))
        text.configure(state='disabled')

    def insert_detected(self):
        result = detect(self.state.get('components', []))
        for key, additions in result['packages'].items():
            widget = self.fields[key]
            existing = widget.get('1.0', 'end').strip()
            combined = existing.splitlines() + additions
            seen = list(dict.fromkeys(value.strip() for value in combined if value.strip()))
            widget.delete('1.0', 'end')
            widget.insert('1.0', '\n'.join(seen))
        messagebox.showinfo('Detected requirements', 'Detected packages were added to the editable fields. Verify package names and versions before building.', parent=self)

    def save(self):
        data = self.data()
        try:
            for field in ('java_version', 'python_version', 'r_version', 'perl_version'):
                version(data[field], field)
            for field in ('python_packages', 'cran_packages', 'bioc_packages', 'cpan_modules', 'os_packages'):
                items(data[field], spec=field == 'python_packages')
            custom_directives(data['dockerfile_directives'])
            family = identify_runtime_family(self.state)
            package_plan({**self.state, 'environment_requirements': data}, family)
        except (ValueError, OSError) as exc:
            messagebox.showerror('Environment requirements', str(exc), parent=self)
            return
        self.state['environment_requirements'] = data
        self.destroy()
