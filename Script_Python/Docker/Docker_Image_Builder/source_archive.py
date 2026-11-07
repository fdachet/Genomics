import io
import os
import posixpath
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


SOURCE_SUFFIXES = ('.zip', '.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tbz2', '.tar.xz', '.txz')


def is_source_archive(path):
    value = str(path or '').lower()
    return any(value.endswith(suffix) for suffix in SOURCE_SUFFIXES)


def archive_stem(path):
    name = Path(str(path)).name
    for suffix in sorted(SOURCE_SUFFIXES, key=len, reverse=True):
        if name.lower().endswith(suffix):
            return name[:-len(suffix)]
    return Path(name).stem


def safe_member_name(value):
    name = str(value or '').replace('\\', '/')
    while name.startswith('./'):
        name = name[2:]
    if not name or name.startswith('/') or ':' in name.split('/')[0] or '\x00' in name:
        raise ValueError('Source archive contains an unsafe member path: ' + name[:200])
    normalized = posixpath.normpath(name)
    if normalized in ('', '.') or normalized.startswith('../') or any(part == '..' for part in name.split('/')):
        raise ValueError('Source archive contains an unsafe member path: ' + name[:200])
    return normalized


class SourceArchive:
    def __init__(self, path):
        self.path = Path(path).resolve()
        if not self.path.is_file() or not is_source_archive(self.path):
            raise ValueError('Select an existing ZIP or TAR source archive.')
        self.zip = self.path.name.lower().endswith('.zip')
        with self._open() as source:
            records = []
            raw_files = []
            entries = source.infolist() if self.zip else source.getmembers()
            if len(entries) > 100000:
                raise ValueError('Source archive contains too many entries.')
            for member in entries:
                raw = member.filename if self.zip else member.name
                try:
                    name = safe_member_name(raw)
                except ValueError:
                    if str(raw or '').strip('./'):
                        raise
                    continue
                mode = member.external_attr >> 16 if self.zip else member.mode
                kind = ('dir' if (member.is_dir() if self.zip else member.isdir()) else
                        'link' if (stat.S_ISLNK(mode) if self.zip else member.issym()) else
                        'file' if (not self.zip and member.isfile()) or self.zip else
                        'hardlink' if member.islnk() else 'other')
                records.append((name, member, kind, mode))
                if kind in ('file', 'link', 'hardlink'):
                    raw_files.append(name)
            first_parts = {name.split('/')[0] for name in raw_files}
            self.prefix = next(iter(first_parts)) + '/' if len(first_parts) == 1 and all('/' in name for name in raw_files) else ''
            self.entries = {}
            for name, member, kind, mode in records:
                if self.prefix and not name.startswith(self.prefix):
                    if name + '/' == self.prefix and kind == 'dir':
                        continue
                    raise ValueError('Source archive has inconsistent root directories.')
                relative = name[len(self.prefix):] if self.prefix else name
                if not relative:
                    continue
                if relative in self.entries:
                    raise ValueError('Source archive contains duplicate paths: ' + relative)
                self.entries[relative] = (member, kind, mode)
        self.file_names = tuple(sorted(name for name, (_, kind, _) in self.entries.items() if kind in ('file', 'link', 'hardlink')))

    def _open(self):
        return zipfile.ZipFile(self.path, 'r') if self.zip else tarfile.open(self.path, 'r:*')

    def has(self, relative):
        entry = self.entries.get(str(relative).replace('\\', '/').lstrip('/'))
        return bool(entry and entry[1] in ('file', 'link', 'hardlink'))

    def read_bytes(self, relative, max_bytes=1024 * 1024):
        name = str(relative).replace('\\', '/').lstrip('/')
        if name not in self.entries:
            raise FileNotFoundError(name)
        member, kind, _ = self.entries[name]
        if kind != 'file':
            raise ValueError('Cannot read non-regular archive member as text: ' + name)
        if (member.file_size if self.zip else member.size) > max_bytes:
            raise ValueError('Source documentation or build file exceeds inspection size limit.')
        with self._open() as source:
            stream = source.open(member) if self.zip else source.extractfile(member)
            if stream is None:
                raise ValueError('Could not open source archive member: ' + name)
            with stream:
                return stream.read(max_bytes + 1)

    def read_head(self, relative, max_bytes=256):
        name = str(relative).replace('\\', '/').lstrip('/')
        member, kind, _ = self.entries[name]
        if kind != 'file':
            return b''
        with self._open() as source:
            stream = source.open(member) if self.zip else source.extractfile(member)
            if stream is None:
                return b''
            with stream:
                return stream.read(max_bytes)

    def read_text(self, relative, max_bytes=1024 * 1024):
        return self.read_bytes(relative, max_bytes).decode('utf-8-sig', errors='replace')

    def _link_target(self, source, name, member, kind):
        if kind == 'link':
            if self.zip:
                with source.open(member) as stream:
                    target = stream.read(4097).decode('utf-8', errors='replace')
            else:
                target = member.linkname
        else:
            target = member.linkname
            if self.prefix and target.startswith(self.prefix):
                target = target[len(self.prefix):]
        if not target or len(target) > 4096 or target.startswith('/') or '\x00' in target or '\\' in target:
            raise ValueError('Source archive contains an unsafe symbolic link: ' + name)
        resolved = (posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
                    if kind == 'link' else posixpath.normpath(target))
        if resolved.startswith('../') or resolved == '..' or resolved.startswith('/'):
            raise ValueError('Source archive symbolic link escapes the source tree: ' + name)
        return target

    def write_normalized_tar(self, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        with self._open() as source, tarfile.open(destination, 'w', format=tarfile.PAX_FORMAT) as archive:
            for name, (member, kind, mode) in sorted(self.entries.items()):
                if kind not in ('file', 'dir', 'link', 'hardlink'):
                    raise ValueError('Source archive has an unsupported special file: ' + name)
                info = tarfile.TarInfo(name)
                info.mode = stat.S_IMODE(mode) or (0o755 if kind == 'dir' else 0o644)
                info.mtime = 0
                if kind == 'dir':
                    info.type = tarfile.DIRTYPE
                    archive.addfile(info)
                elif kind in ('link', 'hardlink'):
                    info.type = tarfile.SYMTYPE if kind == 'link' else tarfile.LNKTYPE
                    info.linkname = self._link_target(source, name, member, kind)
                    archive.addfile(info)
                else:
                    size = member.file_size if self.zip else member.size
                    total += size
                    if size > 2 * 1024 ** 3 or total > 4 * 1024 ** 3:
                        raise ValueError('Source archive uncompressed data exceeds the safety limit.')
                    info.size = size
                    stream = source.open(member) if self.zip else source.extractfile(member)
                    if stream is None:
                        raise ValueError('Cannot extract source archive file: ' + name)
                    with stream:
                        archive.addfile(info, stream)
        return destination


class ArchiveDocument:
    def __init__(self, archive, member):
        self.archive = Path(archive)
        self.member = str(member)
        self.name = PurePosixPath(self.member).name

    def relative_to(self, base):
        if Path(base).resolve() != self.archive.resolve():
            raise ValueError('Document is not inside this archive.')
        return PurePosixPath(self.member)

    def read_text(self, encoding='utf-8-sig', errors='replace'):
        return SourceArchive(self.archive).read_bytes(self.member, 8 * 1024 * 1024).decode(encoding, errors=errors)

    def __str__(self):
        return str(self.archive) + ' :: ' + self.member
