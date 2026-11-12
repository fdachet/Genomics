
from pathlib import Path
import fnmatch
import ntpath
import posixpath
import re
import shlex
from component_output_detector import _makefile_target_candidates, build_target_names
from source_archive import SourceArchive, is_source_archive
from recognized_elements import load_database

BUILD_COMMANDS = {
    "Make": "make",
    "CMake": "cmake -S . -B build && cmake --build build -j 4",
    "Meson": "meson setup build && meson compile -C build",
    "Ninja": "ninja",
    "Configure/Make": "./configure && make",
    "Autotools": "autoreconf -i && ./configure && make",
    "Cargo": "cargo build --release",
    "Go": "go build -o app .",
    "Maven": "mvn package -DskipTests",
    "Gradle": "gradle build",
    "Python": "python -m pip wheel . -w dist",
    "R package": "R CMD build .",
    "Custom": "",
}

COMMON_BUILD_COMMANDS = (
    "make", "make -j 4", "cmake -S . -B build && cmake --build build -j 4",
    "meson setup build && meson compile -C build", "ninja",
    "./configure && make", "autoreconf -i && ./configure && make",
    "cargo build --release", "go build -o app .", "mvn package -DskipTests",
    "gradle build", "python -m pip wheel . -w dist", "R CMD build .",
)

def preferred_make_target(directory, component_name='', source_folder=''):
    targets, _ = _makefile_target_candidates(Path(directory))
    names = build_target_names(component_name, source_folder or directory)
    for target in targets:
        if target.casefold() in names:
            return target
    return ''


def detect_build_system(path, component_name=''):
    directory = Path(str(path).strip())
    archive = SourceArchive(directory) if directory.is_file() and is_source_archive(directory) else None
    if not directory.is_dir() and archive is None:
        return "", ""
    detectors = sorted((item for item in load_database()
                        if item['enabled'] and item['build_system'] and
                        (item['build_command'] or item['build_system'] in BUILD_COMMANDS) and
                        item['kind'] in ('build_file', 'executable')),
                       key=lambda item: (item['priority'], item['name'].lower()))
    for relative in ('', 'source', 'src'):
        work = directory / relative if relative else directory
        if archive is None and not work.is_dir():
            continue
        candidates = ([name.rsplit('/', 1)[-1] for name in archive.file_names
                       if ('/' in name and name.rsplit('/', 1)[0] == relative) or
                       ('/' not in name and not relative)] if archive is not None else
                      [entry.name for entry in work.iterdir() if entry.is_file()])
        for item in detectors:
            pattern = (item['pattern'] or item['name']).lower()
            if not any(fnmatch.fnmatchcase(filename.lower(), pattern) for filename in candidates):
                continue
            system = item['build_system']
            command = item['build_command'] or BUILD_COMMANDS.get(system, '')
            if system == 'Make' and command == 'make':
                target = preferred_make_target(work, component_name, directory) if archive is None else ''
                command = 'make' + (f' -C {shlex.quote(relative)}' if relative else '')
                if target:
                    command += ' ' + shlex.quote(target)
                return system, command
            if system == 'CMake' and relative and command == BUILD_COMMANDS['CMake']:
                return system, f'cmake -S {shlex.quote(relative)} -B build && cmake --build build -j 4'
            if relative:
                command = f'cd {shlex.quote(relative)} && {command}'
            return system, command
    return "", ""


def suggested_destination(kind, name):
    category = str(kind or "").strip().lower()
    if category in ("source", "binary", "script"):
        return "/usr/local/bin/"
    if category in ("jar/application", "folder", "other"):
        label = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(name or "").strip()).strip(".-") or "component"
        return "/opt/" + label + "/"
    return ""


def installed_target(kind, source, destination, name, output_rel=""):
    kind = str(kind or "").lower().strip()
    dest = str(destination or "").strip()
    if not dest.startswith("/"):
        return ""
    filename = ntpath.basename(str(source or "").replace("\\", "/").rstrip("/"))
    if kind == "source":
        filename = posixpath.basename(str(output_rel or "").strip().replace("\\", "/"))
    if kind in ("os package", "base-provided"):
        return ""
    if kind == "folder":
        return dest.rstrip("/") or "/"
    if not filename:
        filename = str(name or "").strip()
    if not filename:
        return ""
    return posixpath.join(dest, filename)


def validation_presets(kind, source, destination, name, output_rel=""):
    kind = str(kind or "").lower().strip()
    target = installed_target(kind, source, destination, name, output_rel)
    values = []
    if kind in ("binary", "source") and target:
        escaped = shlex.quote(target)
        values = [f"test -x {escaped}", f"{escaped} --help",
                  f"{escaped} --version", f"{escaped} -v",
                  f"{escaped} --self-test"]
    elif kind == "jar/application" and target:
        values = [f"test -f {shlex.quote(target)}", f"java -jar {shlex.quote(target)} --version", f"java -jar {shlex.quote(target)} --help", f"java -jar {shlex.quote(target)} --self-test"]
    elif kind == "script" and target:
        ext = Path(str(source or '')).suffix.lower()
        quoted = shlex.quote(target)
        if ext == '.py':
            values = [f"test -f {quoted}", f"python3 -m py_compile {quoted}", f"python3 {quoted} --help"]
        elif ext == '.pl':
            values = [f"test -f {quoted}", f"perl -c {quoted}"]
        elif ext == '.r':
            values = [f"test -f {quoted}", f"Rscript -e {shlex.quote('parse(file=' + repr(target) + ')')}"]
        else:
            values = [f"test -f {quoted}"]
    elif kind == "folder" and target:
        values = [f"test -d {shlex.quote(target)}"]
    elif kind == "other" and target:
        values = [f"test -f {shlex.quote(target)}"]
    elif kind == "os package":
        package = str(name or "").strip()
        if package and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.+-]*", package):
            safe = shlex.quote(package)
            values = ["if command -v rpm >/dev/null 2>&1; then rpm -q " + safe +
                      "; elif command -v dpkg-query >/dev/null 2>&1; then test \"$(dpkg-query -W -f='${Status}' " + safe +
                      " 2>/dev/null)\" = \"install ok installed\"; elif command -v apk >/dev/null 2>&1; then apk info -e " + safe +
                      "; else exit 1; fi"]
            if package.startswith("openjdk-") and ("-jre" in package or "-jdk" in package):
                values.append("java -version")
            elif package == "python3":
                values.append("python3 --version")
    elif kind == "base-provided":
        program = str(name or "").strip()
        if program and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.+-]*", program):
            values = [f"command -v {program}", f"{program} --version"]
    return values
