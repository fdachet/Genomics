import struct
import zipfile
from pathlib import Path

BLOCKED_BINARY_SUFFIXES = {'.jar', '.war', '.ear', '.exe', '.dll', '.com', '.msi', '.bat', '.cmd', '.ps1', '.txt', '.md', '.csv', '.tsv', '.json', '.xml', '.yaml', '.yml', '.py', '.sh', '.bash', '.pl', '.rb', '.js', '.java', '.class', '.c', '.cc', '.cpp', '.h', '.hpp', '.zip', '.tar', '.gz', '.xz', '.7z', '.rar', '.so', '.dylib', '.a', '.o', '.obj', '.pdb', '.deb', '.rpm'}


def inspect_component_file(source):
    path = Path(str(source or '').strip().strip('"')).expanduser()
    if not path.is_file():
        return {'format': 'MISSING', 'detail': 'File not found or not a regular file.', 'suggested_kind': ''}
    suffix = path.suffix.lower()
    try:
        with path.open('rb') as handle:
            header = handle.read(64)
            if header.startswith(b'\x7fELF'):
                if len(header) < 52 or header[4] not in (1, 2) or header[5] not in (1, 2):
                    return {'format': 'INVALID_ELF', 'detail': 'Incomplete or invalid ELF executable.', 'suggested_kind': 'Other'}
                endian = '<' if header[5] == 1 else '>'
                elf_type = struct.unpack_from(endian + 'H', header, 16)[0]
                entry_offset = 24 if header[4] == 1 else 24
                entry_format = 'I' if header[4] == 1 else 'Q'
                entry = struct.unpack_from(endian + entry_format, header, entry_offset)[0]
                if suffix in BLOCKED_BINARY_SUFFIXES:
                    return {'format': 'ELF_NONEXECUTABLE_NAME', 'detail': f'The {suffix} filename is not a supported Linux application-executable name.', 'suggested_kind': 'Other'}
                if elf_type not in (2, 3) or entry == 0:
                    return {'format': 'ELF_NOT_EXECUTABLE', 'detail': 'This ELF is not identified as a runnable program (it may be a shared library or object).', 'suggested_kind': 'Other'}
                return {'format': 'ELF_EXECUTABLE', 'detail': 'Linux ELF executable detected.', 'suggested_kind': 'Binary'}
            if header.startswith(b'MZ'):
                return {'format': 'WINDOWS_PE', 'detail': 'Windows PE executable; it cannot run natively in a Linux Docker image.', 'suggested_kind': 'Other'}
            if header.startswith(b'#!'):
                return {'format': 'SCRIPT', 'detail': 'Script detected; use Other, or Source if it requires a build process.', 'suggested_kind': 'Other'}
            if header.startswith(b'\xca\xfe\xba\xbe'):
                return {'format': 'JAVA_CLASS', 'detail': 'Java bytecode class file; not a Linux ELF executable.', 'suggested_kind': 'Other'}
    except OSError as exc:
        return {'format': 'UNREADABLE', 'detail': str(exc), 'suggested_kind': ''}
    if suffix in {'.jar', '.war', '.ear'}:
        if zipfile.is_zipfile(path):
            try:
                with zipfile.ZipFile(path) as archive:
                    names = archive.namelist()
                    if 'META-INF/MANIFEST.MF' in names or any(n.endswith('.class') for n in names):
                        return {'format': 'JAVA_ARCHIVE', 'detail': 'Java application/library archive; choose JAR/Application.', 'suggested_kind': 'JAR/Application'}
            except (OSError, zipfile.BadZipFile):
                pass
        return {'format': 'INVALID_JAR', 'detail': 'The file does not contain a valid Java archive.', 'suggested_kind': 'JAR/Application'}
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                if 'META-INF/MANIFEST.MF' in names or any(n.endswith('.class') for n in names):
                    return {'format': 'JAVA_ARCHIVE', 'detail': 'Java archive detected by its contents; use JAR/Application.', 'suggested_kind': 'JAR/Application'}
        except (OSError, zipfile.BadZipFile):
            pass
        return {'format': 'ZIP_ARCHIVE', 'detail': 'ZIP archive; not a Linux ELF executable.', 'suggested_kind': 'Other'}
    if suffix in {'.exe', '.dll', '.com', '.msi'}:
        return {'format': 'WINDOWS_OR_UNRECOGNIZED', 'detail': f'{suffix} is not a Linux native executable.', 'suggested_kind': 'Other'}
    if suffix in BLOCKED_BINARY_SUFFIXES:
        return {'format': 'NON_NATIVE_FILE', 'detail': f'{suffix} is not a Linux native executable.', 'suggested_kind': 'Other'}
    return {'format': 'UNKNOWN', 'detail': 'Not a recognized Linux ELF executable. Select Other for data or scripts.', 'suggested_kind': 'Other'}


def validate_component_type(kind, source):
    kind = str(kind or '').strip().lower()
    if kind not in ('binary', 'jar/application'):
        return True, ''
    result = inspect_component_file(source)
    if kind == 'binary':
        if result['format'] == 'ELF_EXECUTABLE':
            return True, ''
        return False, f"'{Path(str(source)).name}' cannot be registered as Binary. {result['detail']} Suggested type: {result['suggested_kind'] or 'Other'}."
    if result['format'] == 'JAVA_ARCHIVE':
        return True, ''
    return False, f"'{Path(str(source)).name}' is not a valid Java application/library archive. {result['detail']}"
