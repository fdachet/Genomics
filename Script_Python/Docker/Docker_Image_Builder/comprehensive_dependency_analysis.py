from __future__ import annotations

import ast
import csv
import io
import json
import os
import posixpath
import re
import tarfile
import threading
import tkinter as tk
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


def clean_path(path):
    value = str(path or '').replace('\\', '/')
    while value.startswith('./'):
        value = value[2:]
    value = posixpath.normpath(value.lstrip('/'))
    return '' if value in ('', '.', '..') or value.startswith('../') else value


def _json_member(tar, name):
    member = tar.getmember(name)
    stream = tar.extractfile(member)
    if stream is None:
        raise ValueError('Cannot read ' + name)
    return json.load(stream)


def _date(ts):
    if not ts:
        return 'UNKNOWN'
    return str(ts)


def read_docker_save(archive, progress=None):
    archive = Path(archive)
    if not archive.is_file():
        raise FileNotFoundError(str(archive))
    changes = []
    files = {}
    layers_summary = []
    with tarfile.open(archive, 'r:*') as outer:
        manifest = _json_member(outer, 'manifest.json')
        if not isinstance(manifest, list) or not manifest:
            raise ValueError('Docker-save manifest has no images')
        entry = manifest[0]
        layer_names = entry.get('Layers', [])
        if not layer_names:
            raise ValueError('Docker-save manifest has no filesystem layers')
        config = _json_member(outer, entry['Config'])
        history = config.get('history', []) or []
        nonempty = [h for h in history if not h.get('empty_layer')]
        aligned = nonempty if len(nonempty) == len(layer_names) else [{} for _ in layer_names]
        for i, (name, detail) in enumerate(zip(layer_names, aligned), 1):
            created = _date(detail.get('created'))
            command = str(detail.get('created_by') or '').replace('\n', ' ').strip()
            if progress:
                progress(i, len(layer_names), command)
            counts = Counter()
            member = outer.getmember(name)
            with outer.extractfile(member) as stream:
                if stream is None:
                    raise ValueError('Unreadable layer: ' + name)
                with tarfile.open(fileobj=stream, mode='r|*') as layer:
                    for item in layer:
                        path = clean_path(item.name)
                        if not path:
                            continue
                        base = posixpath.basename(path)
                        parent = posixpath.dirname(path)
                        if base == '.wh..wh..opq':
                            prefix = parent + '/' if parent else ''
                            deleted = [p for p in files if p.startswith(prefix)]
                            for old in deleted:
                                previous = files.pop(old)
                                counts['REMOVED'] += 1
                                changes.append({'layer': i, 'created': created, 'command': command,
                                                'action': 'REMOVED', 'path': '/' + old, 'size': 0,
                                                'file_mtime': '', 'previous_layer': previous['layer']})
                            continue
                        if base.startswith('.wh.'):
                            target = posixpath.join(parent, base[4:])
                            deleted = [p for p in files if p == target or p.startswith(target + '/')]
                            for old in deleted:
                                previous = files.pop(old)
                                counts['REMOVED'] += 1
                                changes.append({'layer': i, 'created': created, 'command': command,
                                                'action': 'REMOVED', 'path': '/' + old, 'size': 0,
                                                'file_mtime': '', 'previous_layer': previous['layer']})
                            continue
                        if not (item.isfile() or item.issym() or item.islnk()):
                            continue
                        action = 'MODIFIED' if path in files else 'ADDED'
                        previous = files.get(path, {})
                        mtime = datetime.fromtimestamp(item.mtime, timezone.utc).isoformat() if item.mtime is not None else ''
                        files[path] = {'layer': i, 'size': item.size, 'mtime': mtime,
                                       'kind': 'link' if item.issym() or item.islnk() else 'file',
                                       'link': item.linkname if item.issym() or item.islnk() else '',
                                       'mode': item.mode}
                        counts[action] += 1
                        changes.append({'layer': i, 'created': created, 'command': command,
                                        'action': action, 'path': '/' + path,
                                        'size': item.size, 'file_mtime': mtime,
                                        'previous_layer': previous.get('layer', '')})
            layers_summary.append({'layer': i, 'created': created, 'command': command,
                                   'added': counts['ADDED'], 'modified': counts['MODIFIED'],
                                   'removed': counts['REMOVED'], 'id': name})
    return {'archive': str(archive), 'image_created': _date(config.get('created')),
            'architecture': str(config.get('architecture') or ''), 'os': str(config.get('os') or ''),
            'layers': layers_summary, 'changes': changes, 'files': files,
            'history': history, 'tags': entry.get('RepoTags') or [],
            'history_alignment': len(nonempty) == len(layer_names)}


def _which(image, executable):
    paths = image['files']
    executable = executable.strip()
    if '/' in executable:
        key = clean_path(executable)
        return '/' + key if key in paths else ''
    for folder in ('usr/local/sbin', 'usr/local/bin', 'usr/sbin', 'usr/bin', 'sbin', 'bin',
                   'opt/bin'):
        key = folder + '/' + executable
        if key in paths:
            return '/' + key
    matches = [x for x in paths if posixpath.basename(x) == executable]
    return '/' + matches[0] if len(matches) == 1 else ''


def _present(image, reference):
    key = clean_path(reference)
    if not key:
        return ''
    if key in image['files']:
        return '/' + key
    return ''


def _requirements_for_source(path):
    found = []
    raw = Path(path).read_bytes()[:2_000_000]
    content = raw.decode('utf-8', 'replace')
    if b'\x00' in raw[:4096]:
        return []
    suffix = Path(path).suffix.lower()
    first = content.splitlines()[0] if content.splitlines() else ''
    if first.startswith('#!'):
        first = first[2:].strip()
        bits = first.split()
        interpreter = bits[0] if bits else ''
        if interpreter.endswith('/env') and len(bits) > 1:
            interpreter = next((b for b in bits[1:] if not b.startswith('-')), '')
        if interpreter:
            found.append(('Interpreter', interpreter, 'shebang', True))
    if suffix == '.py':
        try:
            tree = ast.parse(content)
            builtin = set(getattr(__import__('sys'), 'stdlib_module_names', ()))
            modules = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules.update(item.name.split('.')[0] for item in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    modules.add(node.module.split('.')[0])
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ('run', 'Popen', 'call', 'check_call', 'check_output'):
                    if node.args and isinstance(node.args[0], (ast.List, ast.Tuple)) and node.args[0].elts:
                        arg = node.args[0].elts[0]
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            found.append(('Executable', arg.value, 'subprocess call', True))
            for module in sorted(modules - builtin - {'__future__'}):
                found.append(('Python module', module, 'static import; may be optional/local', False))
            found.append(('Interpreter', 'python3', 'Python source', True))
        except SyntaxError:
            found.append(('Analysis', path.name, 'Python parse error', False))
    elif suffix in ('.sh', '.bash'):
        for cmd in sorted(set(re.findall(r'^\s*(?:exec\s+)?(python\d*(?:\.\d+)?|perl|Rscript|java|samtools|bedtools|ffmpeg|blastn|bwa|STAR)\b', content, re.M))):
            found.append(('Executable', cmd, 'shell command', False))
    elif suffix == '.pl':
        for mod in sorted(set(re.findall(r'^\s*use\s+([\w:]+)\s*;', content, re.M))):
            if mod not in ('strict', 'warnings', 'utf8', 'feature', 'lib'):
                found.append(('Perl module', mod, 'Perl use declaration', False))
        found.append(('Interpreter', 'perl', 'Perl source', True))
    elif suffix.lower() in ('.r', '.rscript'):
        for mod in sorted(set(re.findall(r'\b(?:library|require)\s*\(\s*["\']?([\w.]+)', content))):
            found.append(('R package', mod, 'R package import', False))
        found.append(('Interpreter', 'Rscript', 'R source', True))
    for match in re.finditer(r'(?<![\w])([/][\w.\-+]+(?:[/][\w.\-+]+)+\.(?:fa|fasta|fai|gtf|gff|csv|tsv|txt|json|yaml|yml|png|jpg|jpeg|tif|tiff|db|bam|bai|bed|vcf|gz))\b', content, re.I):
        found.append(('Data / config', match.group(1), 'literal absolute path', False))
    return list(dict.fromkeys(found))


def analyze_components(components, image, resolve_source):
    records = []
    files = image['files']
    for comp in components:
        name = str(comp.get('name', '')).strip()
        if not name:
            continue
        source = resolve_source(comp)
        requirements = []
        if source and Path(source).is_file():
            source = Path(source)
            if source.suffix.lower() in ('.py', '.sh', '.bash', '.pl', '.r', '.rscript'):
                try:
                    requirements.extend(_requirements_for_source(source))
                except Exception as exc:
                    requirements.append(('Analysis', source.name, 'read failed: ' + str(exc), False))
            elif source.suffix.lower() in ('.exe', '.dll'):
                requirements.append(('Platform', 'Windows PE executable', 'requires compatible Windows/PE runtime', True))
            elif source.suffix.lower() == '.jar':
                requirements.append(('Interpreter', 'java', 'JAR requires JVM; version checked by existing Java scanner', True))
            else:
                try:
                    from runtime_dependency_scanner import elf_dependencies, is_elf
                    if is_elf(source):
                        report = elf_dependencies(source)
                        for lib in report.get('needed', []):
                            requirements.append(('Shared library', lib, 'ELF DT_NEEDED', True))
                        if report.get('interpreter'):
                            requirements.append(('Dynamic loader', report['interpreter'], 'ELF PT_INTERP', True))
                except Exception as exc:
                    requirements.append(('Analysis', source.name, 'ELF inspection: ' + str(exc), False))
        for kind, requirement, evidence, mandatory in dict.fromkeys(requirements):
            location = ''
            if kind in ('Interpreter', 'Executable'):
                location = _which(image, requirement)
                status = 'PRESENT' if location else 'MISSING' if mandatory else 'UNRESOLVED'
            elif kind in ('Data / config', 'Dynamic loader'):
                location = _present(image, requirement)
                status = 'PRESENT' if location else 'MISSING' if mandatory else 'UNRESOLVED'
            elif kind == 'Shared library':
                matches = [p for p in files if posixpath.basename(p) == requirement]
                location = '/' + matches[0] if matches else ''
                status = 'PRESENT' if matches else 'MISSING'
            elif kind == 'Platform':
                status = 'INCOMPATIBLE' if image.get('os', '').lower() == 'linux' else 'UNRESOLVED'
            else:
                status = 'UNRESOLVED'
            records.append({'component': name, 'kind': kind, 'requirement': requirement,
                            'status': status, 'location': location, 'evidence': evidence})
    return records


class InspectionWindow(tk.Toplevel):
    def __init__(self, parent, app, components, source_resolver, mode):
        super().__init__(parent)
        self.app = app
        self.components = components
        self.source_resolver = source_resolver
        self.mode = mode
        self.title('Docker image layer history' if mode == 'history' else 'Comprehensive dependency analyzer')
        self.geometry('1250x760')
        self.minsize(850, 500)
        self.archive = tk.StringVar(value=str(app.state.get('runtime_base_archive') or ''))
        self.status = tk.StringVar(value='Select a docker-save TAR archive, then click Analyze.')
        self.filter = tk.StringVar()
        self.image = None
        self.rows = []
        self._run_id = 0
        self.sort_column = 'layer' if mode == 'history' else 'component'
        self.sort_descending = False
        self.action_filter = tk.StringVar(value='All actions')
        self.period_filter = tk.StringVar(value='All dates')
        self.date_from = tk.StringVar()
        self.date_to = tk.StringVar()
        self.row_limit = tk.StringVar(value='1000')
        self._filter_job = None
        self.summary = ''
        self.view_rows = []
        header = ttk.Frame(self, padding=8)
        header.pack(fill='x')
        ttk.Label(header, text='Docker image TAR:').pack(side='left')
        ttk.Entry(header, textvariable=self.archive).pack(side='left', fill='x', expand=True, padx=8)
        ttk.Button(header, text='Browse', command=self.browse).pack(side='left')
        self.run_button = ttk.Button(header, text='Analyze', command=self.start)
        self.run_button.pack(side='left', padx=5)
        ttk.Button(header, text='Export CSV', command=self.export).pack(side='left', padx=5)
        filterbar = ttk.Frame(self, padding=(8, 0, 8, 5))
        filterbar.pack(fill='x')
        ttk.Label(filterbar, text='Search:').pack(side='left')
        ttk.Entry(filterbar, textvariable=self.filter).pack(side='left', fill='x', expand=True, padx=(7, 7))
        ttk.Button(filterbar, text='Clear filters', command=self.clear_filters).pack(side='left')
        self.filter.trace_add('write', lambda *_: self.schedule_populate())
        if mode == 'history':
            controls = ttk.Frame(self, padding=(8, 0, 8, 6))
            controls.pack(fill='x')
            ttk.Label(controls, text='Action:').pack(side='left')
            actions = ttk.Combobox(controls, textvariable=self.action_filter, values=('All actions', 'ADDED', 'MODIFIED', 'REMOVED'), state='readonly', width=13)
            actions.pack(side='left', padx=(5, 12))
            ttk.Label(controls, text='Period:').pack(side='left')
            periods = ttk.Combobox(controls, textvariable=self.period_filter, values=('All dates', 'Last 1 day', 'Last 1 week', 'Last 1 month', 'Last 1 year', 'Custom range'), state='readonly', width=16)
            periods.pack(side='left', padx=(5, 12))
            ttk.Label(controls, text='From:').pack(side='left')
            ttk.Entry(controls, textvariable=self.date_from, width=12).pack(side='left', padx=(5, 5))
            ttk.Label(controls, text='To:').pack(side='left')
            ttk.Entry(controls, textvariable=self.date_to, width=12).pack(side='left', padx=(5, 12))
            ttk.Label(controls, text='Max rows:').pack(side='left')
            ttk.Combobox(controls, textvariable=self.row_limit, values=('100', '500', '1000', '2000', '5000', '10000', '25000', 'All'), width=8).pack(side='left', padx=(5, 0))
            for variable in (self.action_filter, self.period_filter, self.date_from, self.date_to, self.row_limit):
                variable.trace_add('write', lambda *_: self.schedule_populate())
            ttk.Label(self, text='Dates: YYYY-MM-DD (inclusive). Relative periods use the current date, not the image creation date. Missing layer dates are excluded by date filters.', padding=(10, 0, 8, 2)).pack(fill='x')
        columns = ('layer', 'created', 'action', 'path', 'size', 'previous_layer', 'command', 'file_mtime') if mode == 'history' else ('component', 'kind', 'requirement', 'status', 'location', 'evidence')
        tableframe = ttk.Frame(self, padding=8)
        tableframe.pack(fill='both', expand=True)
        self.table = ttk.Treeview(tableframe, columns=columns, show='headings', height=18)
        widths = {'layer': 65, 'created': 185, 'action': 100, 'path': 430, 'size': 90,
                  'previous_layer': 100, 'command': 470, 'file_mtime': 195,
                  'component': 180, 'kind': 150, 'requirement': 290, 'status': 110,
                  'location': 340, 'evidence': 330}
        for key in columns:
            self.table.heading(key, text=key.replace('_', ' ').title(), command=lambda column=key: self.change_sort(column))
            self.table.column(key, width=widths.get(key, 150), anchor='w')
        self.table.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(tableframe, orient='vertical', command=self.table.yview)
        sb.pack(side='right', fill='y')
        self.table.configure(yscrollcommand=sb.set)
        self.table.tag_configure('ADDED', background='#e4f4e8', foreground='#18572b')
        self.table.tag_configure('REMOVED', background='#ffe5e5', foreground='#8f2424')
        self.table.tag_configure('MODIFIED', background='#fff1ce', foreground='#785400')
        self.table.tag_configure('PRESENT', background='#e4f4e8', foreground='#18572b')
        self.table.tag_configure('MISSING', background='#ffe5e5', foreground='#8f2424')
        self.table.tag_configure('INCOMPATIBLE', background='#ffe5e5', foreground='#8f2424')
        self.table.tag_configure('UNRESOLVED', background='#fff1ce', foreground='#785400')
        self.columns = columns
        self.refresh_headings()
        ttk.Label(self, textvariable=self.status, padding=8, wraplength=1160).pack(fill='x')
        if mode == 'history':
            ttk.Label(self, text='History dates come from image configuration; file mtime is NOT an installation date. Layers have no guaranteed timestamps. Deleted/replaced files are inferred from whiteouts and layer order. Docker-save history may not map to individual build commands after image squashing.', padding=(8, 0, 8, 8), wraplength=1150).pack(fill='x')
        else:
            ttk.Label(self, text='PRESENT verifies path/name presence only. Static imports may be optional, local, or dynamically resolved. Python/R/Perl package availability and ABI compatibility are UNRESOLVED until runtime testing. This scanner does not execute imported scripts.', padding=(8, 0, 8, 8), wraplength=1150).pack(fill='x')

    def browse(self):
        name = filedialog.askopenfilename(parent=self, title='Open docker-save TAR', filetypes=[('Docker archives', '*.tar *.tar.gz *.tgz'), ('All files', '*.*')])
        if name:
            self.archive.set(name)

    def start(self):
        archive = self.archive.get().strip().strip('"')
        if not Path(archive).is_file():
            messagebox.showerror('Archive', 'Select an existing docker-save TAR archive.', parent=self)
            return
        self._run_id += 1
        run_id = self._run_id
        self.run_button.configure(state='disabled')
        self.status.set('Reading image layers ...')
        def worker():
            try:
                image = read_docker_save(archive, lambda n, total, cmd: self.after(0, lambda n=n, total=total: self.status.set(f'Reading layer {n}/{total} ...')))
                rows = image['changes'] if self.mode == 'history' else analyze_components(self.components, image, self.source_resolver)
                self.after(0, lambda: self.finish(run_id, image, rows, ''))
            except Exception as exc:
                self.after(0, lambda error=str(exc): self.finish(run_id, None, [], error))
        threading.Thread(target=worker, daemon=True).start()

    def finish(self, run_id, image, rows, error):
        if not self.winfo_exists() or run_id != self._run_id:
            return
        self.run_button.configure(state='normal')
        if error:
            self.status.set('Analysis failed: ' + error)
            return
        self.image = image
        self.rows = rows
        if self.mode == 'history':
            self.status.set(f'{len(image["layers"])} filesystem layers | {len(rows)} file changes | {len(image["files"])} final files | image created {image["image_created"]} | history timestamps {"aligned" if image["history_alignment"] else "not aligned"}')
        else:
            counts = Counter(row['status'] for row in rows)
            self.status.set(f'{len(rows)} discovered dependencies | ' + ' | '.join(f'{k}: {v}' for k, v in sorted(counts.items())) + ' | Note: missing paths and dynamic code require functional validation')
        self.populate()

    def clear_filters(self):
        self.filter.set('')
        self.action_filter.set('All actions')
        self.period_filter.set('All dates')
        self.date_from.set('')
        self.date_to.set('')
        self.row_limit.set('1000')
        self.schedule_populate()

    def schedule_populate(self):
        if not hasattr(self, 'table'):
            return
        if self._filter_job is not None:
            self.after_cancel(self._filter_job)
        self._filter_job = self.after(180, self.populate)

    def refresh_headings(self):
        if not hasattr(self, 'table'):
            return
        for key in self.columns:
            arrow = (' ▼' if self.sort_descending else ' ▲') if key == self.sort_column else ''
            self.table.heading(key, text=key.replace('_', ' ').title() + arrow)

    def change_sort(self, column):
        if self.sort_column == column:
            self.sort_descending = not self.sort_descending
        else:
            self.sort_column = column
            self.sort_descending = False
        self.refresh_headings()
        self.schedule_populate()

    @staticmethod
    def parse_date(value):
        value = str(value or '').strip()
        if not value or value.upper() == 'UNKNOWN':
            return None
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (ValueError, OverflowError):
            return None

    @staticmethod
    def parse_day(value):
        return datetime.strptime(value.strip(), '%Y-%m-%d').date()

    def date_bounds(self):
        if self.mode != 'history':
            return None, None
        period = self.period_filter.get()
        current = datetime.now(timezone.utc)
        if period.startswith('Last '):
            days = {'Last 1 day': 1, 'Last 1 week': 7, 'Last 1 month': 30, 'Last 1 year': 365}[period]
            return current - timedelta(days=days), current
        if period == 'Custom range':
            first = self.parse_day(self.date_from.get()) if self.date_from.get().strip() else None
            last = self.parse_day(self.date_to.get()) if self.date_to.get().strip() else None
            if first and last and first > last:
                raise ValueError('From date must be on or before To date.')
            start = datetime.combine(first, datetime.min.time(), timezone.utc) if first else None
            finish = datetime.combine(last + timedelta(days=1), datetime.min.time(), timezone.utc) if last else None
            return start, finish
        return None, None

    def sort_key(self, row):
        key = self.sort_column
        value = row.get(key, '')
        if key in ('layer', 'previous_layer', 'size'):
            try:
                return (0, int(value))
            except (ValueError, TypeError):
                return (1, 0)
        if key in ('created', 'file_mtime'):
            dt = self.parse_date(value)
            return (0, dt.timestamp()) if dt else (1, 0)
        return (0, str(value).casefold())

    def populate(self):
        self._filter_job = None
        if not hasattr(self, 'table'):
            return
        term = self.filter.get().casefold().strip()
        try:
            from_date, to_date = self.date_bounds()
            limit_string = self.row_limit.get().strip()
            limit = None if self.mode != 'history' or limit_string.lower() == 'all' else int(limit_string)
            if limit is not None and not 1 <= limit <= 100000:
                raise ValueError('Max rows must be between 1 and 100,000, or All.')
        except ValueError as exc:
            self.status.set('Invalid filter: ' + str(exc) + ' Use YYYY-MM-DD for dates.')
            return
        action = self.action_filter.get()
        matched = []
        for row in self.rows:
            if term and term not in ' '.join(map(str, row.values())).casefold():
                continue
            if self.mode == 'history':
                if action != 'All actions' and row.get('action') != action:
                    continue
                if from_date is not None or to_date is not None:
                    created = self.parse_date(row.get('created'))
                    if created is None:
                        continue
                    if from_date is not None and created < from_date:
                        continue
                    if to_date is not None and (created > to_date if self.period_filter.get() != 'Custom range' else created >= to_date):
                        continue
            matched.append(row)
        matched.sort(key=self.sort_key, reverse=self.sort_descending)
        self.view_rows = matched
        shown = matched if limit is None else matched[:limit]
        children = self.table.get_children()
        if children:
            self.table.delete(*children)
        for row in shown:
            tag = row.get('action', '') if self.mode == 'history' else row.get('status', '')
            self.table.insert('', 'end', values=[row.get(key, '') for key in self.columns], tags=(tag,))
        self.status.set(f'{len(shown):,} displayed | {len(matched):,} matching | {len(self.rows):,} total events. CSV export includes all {len(self.rows):,} events, regardless of filters or row limit.')

    def export(self):
        if not self.rows:
            messagebox.showinfo('Export', 'Run analysis first.', parent=self)
            return
        path = filedialog.asksaveasfilename(parent=self, title='Export results', defaultextension='.csv', filetypes=[('CSV', '*.csv')])
        if not path:
            return
        with open(path, 'w', newline='', encoding='utf-8-sig') as handle:
            writer = csv.DictWriter(handle, fieldnames=self.columns, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(self.rows)
        self.status.set('Exported ' + str(len(self.rows)) + ' records: ' + path)
