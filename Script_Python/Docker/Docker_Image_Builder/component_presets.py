
from pathlib import Path
import ntpath
import posixpath
import re
import shlex

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

DETECTORS = (
    ("CMakeLists.txt", "CMake"), ("meson.build", "Meson"),
    ("pom.xml", "Maven"), ("build.gradle", "Gradle"),
    ("build.gradle.kts", "Gradle"), ("Cargo.toml", "Cargo"),
    ("go.mod", "Go"), ("configure", "Configure/Make"),
    ("configure.ac", "Autotools"), ("Makefile", "Make"),
    ("makefile", "Make"), ("GNUmakefile", "Make"),
    ("pyproject.toml", "Python"), ("setup.py", "Python"),
    ("DESCRIPTION", "R package"), ("build.ninja", "Ninja"),
)


def detect_build_system(path):
    directory = Path(str(path).strip())
    if not directory.is_dir():
        return "", ""
    for marker, system in DETECTORS:
        if (directory / marker).exists():
            return system, BUILD_COMMANDS[system]
    return "", ""


def suggested_destination(kind, name):
    kind = str(kind or "").lower().strip()
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name or "component")).strip("_") or "component"
    if kind in ("source", "binary"):
        return "/usr/local/bin/"
    if kind in ("jar/application", "folder", "other", "script"):
        return f"/opt/{safe}/"
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
