from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


IS_WINDOWS = sys.platform.startswith("win")


class CommandResult:
    def __init__(self, returncode: int, output: str):
        self.returncode = returncode
        self.output = clean_text_output(output)

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def decode_output_bytes(data: bytes | str | None) -> str:
    """Decode command output robustly, including UTF-16/NULL-padded text."""
    if data is None:
        return ""
    if isinstance(data, str):
        return clean_text_output(data)
    if not data:
        return ""

    # UTF-16 output usually has many zero bytes.
    if b"\x00" in data[:400]:
        for enc in ("utf-16", "utf-16le", "utf-16be"):
            try:
                text = data.decode(enc, errors="strict")
                if text.strip():
                    return clean_text_output(text)
            except Exception:
                pass

    for enc in ("utf-8-sig", "utf-8", "mbcs" if IS_WINDOWS else "utf-8", "cp1252"):
        try:
            return clean_text_output(data.decode(enc, errors="replace"))
        except Exception:
            pass
    return clean_text_output(data.decode("utf-8", errors="replace"))


def clean_text_output(text: str | bytes | None) -> str:
    """Remove NUL characters and other display artifacts from command output."""
    if text is None:
        return ""
    if isinstance(text, bytes):
        return decode_output_bytes(text)
    text = str(text)
    if "\x00" in text:
        text = text.replace("\x00", "")
    text = text.replace("\ufeff", "")
    text = text.replace("\ufffd", "")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def run_capture(command, cwd: str | None = None, env: dict | None = None, shell: bool = False, timeout: int = 25) -> CommandResult:
    creationflags = 0
    if IS_WINDOWS:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            command,
            cwd=cwd or None,
            env=env,
            shell=shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=False,
            timeout=timeout,
            creationflags=creationflags,
        )
        return CommandResult(completed.returncode, decode_output_bytes(completed.stdout))
    except subprocess.TimeoutExpired as exc:
        text = decode_output_bytes(exc.stdout)
        return CommandResult(124, text + "\nTIMEOUT")
    except FileNotFoundError as exc:
        return CommandResult(127, str(exc))
    except Exception as exc:
        return CommandResult(1, str(exc))


def run_streaming(command, state, cwd: str | None = None, env: dict | None = None, shell: bool = False, input_text: str | None = None) -> int:
    state.stop_requested = False
    state.log("$ " + command_to_text(command), "CMD")
    creationflags = 0
    if IS_WINDOWS:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(
            command,
            cwd=cwd or None,
            env=env,
            shell=shell,
            stdin=subprocess.PIPE if input_text is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        state.current_process = proc
        if input_text is not None and proc.stdin is not None:
            try:
                proc.stdin.write(input_text)
                proc.stdin.flush()
                proc.stdin.close()
            except Exception:
                pass
        assert proc.stdout is not None
        for line in proc.stdout:
            state.log(clean_text_output(line).rstrip("\n"), "OUT")
        rc = proc.wait()
        state.current_process = None
        state.log(f"Process finished with exit code {rc}", "OK" if rc == 0 else "ERROR")
        return rc
    except FileNotFoundError as exc:
        state.current_process = None
        state.log(str(exc), "ERROR")
        return 127
    except Exception as exc:
        state.current_process = None
        state.log(str(exc), "ERROR")
        return 1


def command_to_text(command) -> str:
    if isinstance(command, str):
        return command
    if IS_WINDOWS:
        def q(value) -> str:
            text = str(value)
            if not text:
                return '""'
            if any(ch.isspace() for ch in text) or any(ch in text for ch in "&()[]{}^=;!'`,~"):
                return '"' + text.replace('\"', '\\"') + '"'
            return text
        return " ".join(q(x) for x in command)
    return " ".join(shlex.quote(str(x)) for x in command)


def quote_sh(value: str) -> str:
    return shlex.quote(value)


def find_on_path(name: str, env: dict | None = None) -> str:
    return shutil.which(name, path=(env or os.environ).get("PATH")) or ""


def is_executable_file(path: str) -> bool:
    return bool(path) and Path(path).exists() and Path(path).is_file()


def is_folder(path: str) -> bool:
    return bool(path) and Path(path).exists() and Path(path).is_dir()


def short_output(text: str, max_len: int = 220) -> str:
    text = clean_text_output(text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    out = " | ".join(lines[:2])
    return out if len(out) <= max_len else out[: max_len - 3] + "..."


def first_existing(paths: list[Path]) -> str:
    for path in paths:
        if path.exists():
            return str(path)
    return ""


def default_android_sdk_root() -> str:
    candidates: list[Path] = []
    if os.environ.get("ANDROID_HOME"):
        candidates.append(Path(os.environ["ANDROID_HOME"]))
    if os.environ.get("ANDROID_SDK_ROOT"):
        candidates.append(Path(os.environ["ANDROID_SDK_ROOT"]))
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Android" / "Sdk")
    candidates.extend([Path("C:/Android/Sdk"), Path.home() / "AppData/Local/Android/Sdk"])
    return first_existing(candidates)


def find_sdk_tool(sdk_root: str, tool_name: str) -> str:
    if not sdk_root:
        return ""
    root = Path(sdk_root)
    names = [tool_name]
    lower = tool_name.lower()
    if IS_WINDOWS and not lower.endswith((".bat", ".exe", ".cmd")):
        names.extend([tool_name + ".bat", tool_name + ".cmd", tool_name + ".exe"])

    candidates: list[Path] = []
    for name in names:
        candidates.extend([
            root / "cmdline-tools" / "latest" / "bin" / name,
            root / "tools" / "bin" / name,
            root / "platform-tools" / name,
        ])

    # Android command-line tools are valid under any folder name inside
    # cmdline-tools, for example:
    #   cmdline-tools\latest\bin\sdkmanager.bat
    #   cmdline-tools\latest_gui_20260513_114013\bin\sdkmanager.bat
    # This matters when Windows locks the old broken "latest" folder and the GUI
    # repairs the installation into a clean versioned folder instead.
    cmdline_parent = root / "cmdline-tools"
    if cmdline_parent.exists():
        version_dirs = sorted([p for p in cmdline_parent.iterdir() if p.is_dir()], reverse=True)
        # Prefer "latest" when it exists, then any repaired folder.
        version_dirs = sorted(version_dirs, key=lambda p: (p.name.lower() != "latest", p.name.lower()))
        for version_dir in version_dirs:
            for name in names:
                candidates.append(version_dir / "bin" / name)

    build_tools = root / "build-tools"
    if build_tools.exists():
        version_dirs = sorted([p for p in build_tools.iterdir() if p.is_dir()], reverse=True)
        for version_dir in version_dirs:
            for name in names:
                candidates.append(version_dir / name)

    return first_existing(candidates)


def find_latest_build_tools_dir(sdk_root: str) -> str:
    build_tools = Path(sdk_root) / "build-tools"
    if not build_tools.exists():
        return ""
    dirs = sorted([p for p in build_tools.iterdir() if p.is_dir()], reverse=True)
    return str(dirs[0]) if dirs else ""


def project_has_gradle(project_dir: str) -> bool:
    p = Path(project_dir)
    return any((p / name).exists() for name in ("settings.gradle", "settings.gradle.kts", "build.gradle", "build.gradle.kts"))


def gradle_wrapper_windows(project_dir: str) -> str:
    wrapper = Path(project_dir) / "gradlew.bat"
    return str(wrapper) if wrapper.exists() else ""


def gradle_wrapper_unix(project_dir: str) -> str:
    wrapper = Path(project_dir) / "gradlew"
    return str(wrapper) if wrapper.exists() else ""


def split_tasks(task_text: str) -> list[str]:
    task_text = (task_text or "assembleDebug").strip()
    try:
        return shlex.split(task_text, posix=not IS_WINDOWS)
    except Exception:
        return task_text.split()


def list_apks(project_dir: str) -> list[Path]:
    p = Path(project_dir)
    if not p.exists():
        return []
    roots = [p / "app" / "build" / "outputs" / "apk", p]
    found: list[Path] = []
    for root in roots:
        if root.exists():
            found.extend(root.rglob("*.apk"))
    unique: list[Path] = []
    seen = set()
    for apk in found:
        key = str(apk.resolve()) if apk.exists() else str(apk)
        if key not in seen:
            unique.append(apk)
            seen.add(key)
    return sorted(unique, key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)


def sanitize_filename(name: str, fallback: str = "app") -> str:
    """Return a Windows-safe filename stem while preserving readable spaces."""
    text = clean_text_output(name or "").strip()
    text = re.sub(r'[\\/:*?"<>|]+', "_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


def _find_main_manifest(project_dir: str) -> Path | None:
    root = Path(project_dir)
    preferred = root / "app" / "src" / "main" / "AndroidManifest.xml"
    if preferred.exists():
        return preferred
    matches = sorted(root.glob("**/src/main/AndroidManifest.xml"))
    if matches:
        return matches[0]
    matches = sorted(root.glob("**/AndroidManifest.xml"))
    return matches[0] if matches else None


def _resolve_android_string_resource(project_dir: str, resource_ref: str) -> str:
    """Resolve @string/app_name from Android res/values XML files."""
    if not resource_ref.startswith("@string/"):
        return resource_ref
    key = resource_ref.split("/", 1)[1].strip()
    root = Path(project_dir)
    value_files = []
    for base in [root / "app" / "src" / "main" / "res" / "values", *root.glob("**/src/main/res/values")]:
        if base.exists() and base.is_dir():
            value_files.extend(sorted(base.glob("*.xml")))
    seen = set()
    for xml_file in value_files:
        if xml_file in seen:
            continue
        seen.add(xml_file)
        try:
            tree = ET.parse(xml_file)
            for elem in tree.getroot().iter("string"):
                if elem.attrib.get("name") == key:
                    return "".join(elem.itertext()).strip()
        except Exception:
            continue
    return resource_ref


def get_android_app_label(project_dir: str) -> str:
    """Read the installed app name from AndroidManifest.xml/string resources.

    This is the label Android shows under the installed launcher icon.  The APK
    Builder uses it to name the copied APK as: <installed app name>.apk.
    """
    manifest = _find_main_manifest(project_dir)
    if manifest:
        try:
            tree = ET.parse(manifest)
            root = tree.getroot()
            android_ns = "{http://schemas.android.com/apk/res/android}"
            app = root.find("application")
            label = ""
            if app is not None:
                label = app.attrib.get(android_ns + "label", "") or app.attrib.get("label", "")
            if not label:
                label = root.attrib.get(android_ns + "label", "") or root.attrib.get("label", "")
            if label:
                resolved = _resolve_android_string_resource(str(manifest.parents[3]) if manifest.name == "AndroidManifest.xml" and len(manifest.parents) >= 4 else project_dir, label)
                if resolved and not resolved.startswith("@"):
                    return clean_text_output(resolved).strip()
        except Exception:
            pass

    # Fallback to Gradle project/app folder name if no label can be resolved.
    return Path(project_dir).resolve().name if project_dir else "app"




def app_name_from_apk_name(output_apk_name: str, fallback: str = "app") -> str:
    """Return the installed app label derived from the final copied APK name."""
    name = sanitize_filename(output_apk_name or "", fallback=fallback)
    if name.lower().endswith(".apk"):
        name = name[:-4]
    name = name.strip(" .")
    return name or fallback


def make_application_id_from_name(app_name: str, prefix: str = "local.dashapp") -> str:
    """Create a valid, stable Android applicationId from the app name.

    Different app names produce different package/application IDs, so Android
    installs them as separate apps instead of updating the previous app.
    """
    label = app_name_from_apk_name(app_name, fallback="app")
    pieces = re.split(r"[^A-Za-z0-9]+", label.lower())
    parts: list[str] = []
    for piece in pieces:
        if not piece:
            continue
        piece = re.sub(r"[^a-z0-9_]", "", piece)
        if not piece:
            continue
        if piece[0].isdigit():
            piece = "a" + piece
        # Avoid Java/Kotlin keywords as package components.
        if piece in {"class", "package", "int", "long", "float", "double", "new", "return", "if", "else", "for", "while", "android"}:
            piece = piece + "app"
        parts.append(piece[:40])
    if not parts:
        parts = ["app"]
    candidate = prefix.rstrip(".") + "." + ".".join(parts[:4])
    candidate = re.sub(r"\.+", ".", candidate).strip(".")
    if len(candidate) > 150:
        candidate = candidate[:150].rstrip(".")
    return candidate


def _find_app_build_file(project_dir: str) -> Path | None:
    root = Path(project_dir)
    for rel in ("app/build.gradle", "app/build.gradle.kts"):
        path = root / rel
        if path.exists():
            return path
    matches = sorted(root.glob("**/build.gradle")) + sorted(root.glob("**/build.gradle.kts"))
    for path in matches:
        if path.name.startswith("build.gradle") and "app" in [part.lower() for part in path.parts]:
            return path
    return matches[0] if matches else None


def _replace_or_insert_application_id(build_text: str, application_id: str, is_kts: bool = False) -> tuple[str, bool]:
    """Replace or insert defaultConfig.applicationId in an Android Gradle file."""
    if is_kts:
        pattern = r'(?m)^(\s*)applicationId\s*=\s*["\'][^"\']+["\']'
        repl = rf'\1applicationId = "{application_id}"'
    else:
        pattern = r'(?m)^(\s*)applicationId\s+["\'][^"\']+["\']'
        repl = rf'\1applicationId "{application_id}"'
    new_text, count = re.subn(pattern, repl, build_text, count=1)
    if count:
        return new_text, True

    # Insert inside defaultConfig { ... } if present.
    m = re.search(r'(?m)^(\s*)defaultConfig\s*\{', build_text)
    if m:
        indent = m.group(1) + "    "
        insertion = f'\n{indent}applicationId = "{application_id}"' if is_kts else f'\n{indent}applicationId "{application_id}"'
        pos = m.end()
        return build_text[:pos] + insertion + build_text[pos:], True

    return build_text, False


def get_current_application_id(project_dir: str) -> str:
    build = _find_app_build_file(project_dir)
    if not build:
        return ""
    try:
        text = build.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    for pattern in (
        r'applicationId\s*=\s*["\']([^"\']+)["\']',
        r'applicationId\s+["\']([^"\']+)["\']',
    ):
        m = re.search(pattern, text)
        if m:
            return m.group(1).strip()
    return ""


def _write_app_name_string(project_dir: str, app_name: str) -> None:
    root = Path(project_dir)
    values_dir = root / "app" / "src" / "main" / "res" / "values"
    values_dir.mkdir(parents=True, exist_ok=True)
    strings = values_dir / "strings.xml"
    ET.register_namespace("tools", "http://schemas.android.com/tools")
    if strings.exists():
        try:
            tree = ET.parse(strings)
            root_elem = tree.getroot()
        except Exception:
            root_elem = ET.Element("resources")
            tree = ET.ElementTree(root_elem)
    else:
        root_elem = ET.Element("resources")
        tree = ET.ElementTree(root_elem)
    if root_elem.tag != "resources":
        root_elem = ET.Element("resources")
        tree = ET.ElementTree(root_elem)
    elem = None
    for child in root_elem.findall("string"):
        if child.attrib.get("name") == "app_name":
            elem = child
            break
    if elem is None:
        elem = ET.SubElement(root_elem, "string", {"name": "app_name"})
    elem.text = app_name
    tree.write(strings, encoding="utf-8", xml_declaration=True)


def apply_app_identity_to_project(project_dir: str, output_apk_name: str, application_id_override: str = "", make_new_application: bool = True) -> tuple[bool, str]:
    """Apply installed app label and, optionally, a unique applicationId.

    Android decides whether an APK is an update or a separate app mainly from
    applicationId/package name. Therefore changing only the visible app label or
    the copied APK filename is not enough. This function changes the visible
    label and, when make_new_application is true, changes defaultConfig
    applicationId to a value derived from the selected app/APK name.
    """
    project = Path(clean_cmd_text(project_dir))
    if not project.exists():
        return False, f"App source-code folder not found: {project}"

    app_label = app_name_from_apk_name(output_apk_name or get_android_app_label(str(project)), fallback="app")
    if not app_label:
        app_label = "app"

    try:
        _write_app_name_string(str(project), app_label)
    except Exception as exc:
        return False, f"Could not update app name resource: {exc}"

    manifest = _find_main_manifest(str(project))
    if not manifest:
        return False, "AndroidManifest.xml was not found in the selected project."
    try:
        ET.register_namespace("android", "http://schemas.android.com/apk/res/android")
        tree = ET.parse(manifest)
        manifest_root = tree.getroot()
        android_attr = "{http://schemas.android.com/apk/res/android}"
        app = manifest_root.find("application")
        if app is None:
            return False, "AndroidManifest.xml has no <application> tag."
        app.set(android_attr + "label", "@string/app_name")
        tree.write(manifest, encoding="utf-8", xml_declaration=True)
    except Exception as exc:
        return False, f"Could not update AndroidManifest.xml app label: {exc}"

    if not make_new_application:
        return True, f"Installed app name set to '{app_label}'. Application ID was not changed."

    application_id = clean_cmd_text(application_id_override or "").strip()
    if not application_id:
        application_id = make_application_id_from_name(app_label)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+", application_id):
        return False, f"Invalid Android application ID: {application_id}"

    build = _find_app_build_file(str(project))
    if not build:
        return False, "Could not find app/build.gradle or app/build.gradle.kts to update applicationId."
    try:
        text = build.read_text(encoding="utf-8", errors="replace")
        new_text, changed = _replace_or_insert_application_id(text, application_id, is_kts=build.suffix == ".kts")
        if not changed:
            return False, "Could not find or insert defaultConfig/applicationId in the app build file."
        build.write_text(new_text, encoding="utf-8")
    except Exception as exc:
        return False, f"Could not update applicationId in {build}: {exc}"

    return True, f"Installed app name set to '{app_label}' and applicationId set to '{application_id}'. Android will treat it as a separate app."

def copy_newest_apk(project_dir: str, output_dir: str, output_apk_name: str = "") -> Path | None:
    apks = list_apks(project_dir)
    if not apks:
        return None
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    newest = apks[0]
    # Empty output_apk_name means: use the Android installed app label.
    # A user-entered name can include or omit .apk.
    app_name = sanitize_filename(output_apk_name or get_android_app_label(project_dir), fallback=newest.stem)
    if app_name.lower().endswith(".apk"):
        app_name = app_name[:-4]
    target = out / f"{app_name}.apk"
    # The default output file name matches the installed app name exactly.
    # Therefore overwrite the previous copy instead of adding a timestamp.
    if newest.resolve() != target.resolve():
        if target.exists():
            target.unlink()
        shutil.copy2(newest, target)
    return target


SUPPORTED_ICON_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def get_selected_icon_resource_name() -> str:
    return "custom_launcher_icon"


def validate_icon_source(icon_file: str) -> tuple[bool, str]:
    icon_path = Path(clean_cmd_text(icon_file))
    if not icon_file:
        return False, "No icon picture file selected."
    if not icon_path.exists() or not icon_path.is_file():
        return False, f"Icon picture file not found: {icon_path}"
    suffix = icon_path.suffix.lower()
    if suffix not in SUPPORTED_ICON_EXTENSIONS:
        return False, (
            f"Unsupported icon file type: {suffix or '(no extension)'}. "
            "Use PNG, JPG/JPEG, or WEBP."
        )
    return True, str(icon_path)


def apply_launcher_icon_to_project(project_dir: str, icon_file: str) -> tuple[bool, str]:
    """Copy a selected picture into the Android project and set it as launcher icon.

    The function intentionally uses only Python stdlib. It does not resize or
    convert the image, so it supports Android-compatible bitmap resources that
    can be copied directly: PNG, JPG/JPEG, and WEBP.
    """
    project = Path(clean_cmd_text(project_dir))
    if not project.exists():
        return False, f"App source-code folder not found: {project}"
    ok, message = validate_icon_source(icon_file)
    if not ok:
        return False, message
    icon_path = Path(message)

    manifest = _find_main_manifest(str(project))
    if not manifest:
        return False, "AndroidManifest.xml was not found in the selected project."

    main_src = manifest.parent
    res_dir = main_src / "res"
    drawable_dir = res_dir / "drawable"
    drawable_dir.mkdir(parents=True, exist_ok=True)

    resource_name = get_selected_icon_resource_name()
    suffix = icon_path.suffix.lower()
    if suffix == ".jpeg":
        suffix = ".jpg"
    target = drawable_dir / f"{resource_name}{suffix}"
    shutil.copy2(icon_path, target)

    # Remove previous icon copies with another extension to avoid duplicate
    # resources named custom_launcher_icon. Android resources cannot have two
    # files with the same base name in the same resource folder.
    for ext in SUPPORTED_ICON_EXTENSIONS:
        old = drawable_dir / f"{resource_name}{ext}"
        if old != target and old.exists():
            try:
                old.unlink()
            except Exception:
                pass

    try:
        ET.register_namespace("android", "http://schemas.android.com/apk/res/android")
        tree = ET.parse(manifest)
        root = tree.getroot()
        android_attr = "{http://schemas.android.com/apk/res/android}"
        app = root.find("application")
        if app is None:
            return False, "AndroidManifest.xml has no <application> tag."
        app.set(android_attr + "icon", "@drawable/custom_launcher_icon")
        app.set(android_attr + "roundIcon", "@drawable/custom_launcher_icon")
        tree.write(manifest, encoding="utf-8", xml_declaration=True)
    except Exception as exc:
        return False, f"Icon copied, but AndroidManifest.xml could not be updated: {exc}"

    return True, f"Launcher icon applied: {target}"


def get_current_manifest_icon(project_dir: str) -> str:
    manifest = _find_main_manifest(project_dir)
    if not manifest:
        return ""
    try:
        tree = ET.parse(manifest)
        root = tree.getroot()
        android_ns = "{http://schemas.android.com/apk/res/android}"
        app = root.find("application")
        if app is None:
            return ""
        return app.attrib.get(android_ns + "icon", "") or app.attrib.get("icon", "")
    except Exception:
        return ""


def unique_existing_order(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for path in paths:
        text = clean_cmd_text(path)
        if not text:
            continue
        key = text.lower() if IS_WINDOWS else text
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out

def make_windows_env(config: dict) -> dict:
    """Return an environment that forces the selected JDK and Android SDK paths.

    sdkmanager.bat decides which Java to use from JAVA_HOME/PATH.  The GUI must
    therefore prepend the selected JDK bin folder before the normal Windows PATH;
    otherwise sdkmanager may accidentally find an old Java first and print
    "Java version 17 or higher is required" even when a newer JDK is installed.
    """
    env = os.environ.copy()
    java_home = clean_cmd_text(config.get("java_home", ""))
    java_exe = clean_cmd_text(config.get("java_exe", ""))
    sdk_root = clean_cmd_text(config.get("android_sdk_root_windows", ""))
    sdkmanager_exe = clean_cmd_text(config.get("sdkmanager_exe", ""))
    gradle_exe = clean_cmd_text(config.get("gradle_exe", ""))

    prepend_paths = []
    if java_home:
        env["JAVA_HOME"] = java_home
        prepend_paths.append(str(Path(java_home) / "bin"))
    elif java_exe:
        java_path = Path(java_exe)
        if java_path.exists():
            prepend_paths.append(str(java_path.parent))
            if java_path.parent.name.lower() == "bin":
                env["JAVA_HOME"] = str(java_path.parent.parent)

    if sdk_root:
        env["ANDROID_HOME"] = sdk_root
        env["ANDROID_SDK_ROOT"] = sdk_root
        if sdkmanager_exe:
            sm = Path(sdkmanager_exe)
            if sm.parent.name.lower() == "bin":
                prepend_paths.append(str(sm.parent))
        prepend_paths.extend([
            str(Path(sdk_root) / "cmdline-tools" / "latest" / "bin"),
            str(Path(sdk_root) / "platform-tools"),
        ])
        build_tools = find_latest_build_tools_dir(sdk_root)
        if build_tools:
            prepend_paths.append(build_tools)

    if gradle_exe:
        gp = Path(gradle_exe)
        if gp.parent:
            prepend_paths.append(str(gp.parent))

    env["PATH"] = os.pathsep.join(unique_existing_order(prepend_paths) + [env.get("PATH", "")])
    return env


def detect_project_environment(config: dict) -> str:
    return "Windows"


def clean_cmd_text(value: str) -> str:
    """Remove accidental quote characters and backslash-escaped quotes from saved paths.

    The GUI stores plain Windows paths such as:
        C:\\Android\\Sdk\\cmdline-tools\\latest\\bin\\sdkmanager.bat

    Older versions could accidentally save values with surrounding quotes or literal
    \" sequences. Those break cmd.exe and produce errors such as:
        '\\"C:\\Android\\Sdk\\...\\sdkmanager.bat\\"' is not recognized
    """
    text = str(value or "").strip()
    while text.startswith("'") and text.endswith("'") and len(text) >= 2:
        text = text[1:-1].strip()
    while text.startswith('"') and text.endswith('"') and len(text) >= 2:
        text = text[1:-1].strip()
    text = text.replace('\\"', '"').replace("\\'", "'")
    while text.startswith('"') and text.endswith('"') and len(text) >= 2:
        text = text[1:-1].strip()
    return text


def quote_cmd_arg(value: str) -> str:
    """Quote one Windows cmd.exe argument safely enough for paths/package names."""
    text = clean_cmd_text(value).replace('"', '')
    return f'"{text}"'


def windows_env_setup_script(config: dict) -> str:
    """Return cmd.exe SET commands that force the selected JDK and SDK tools first.

    This is intentionally stronger than passing env=... to subprocess. On Windows,
    resolving a bare executable such as java.exe can still be surprising when old
    Oracle Java shims exist on the user's PATH. Running through cmd.exe with an
    explicit SET "PATH=...;%PATH%" makes the next `where java` and sdkmanager.bat
    use the selected JDK first.
    """
    java_home = clean_cmd_text(config.get("java_home", ""))
    java_exe = clean_cmd_text(config.get("java_exe", ""))
    sdk_root = clean_cmd_text(config.get("android_sdk_root_windows", ""))
    sdkmanager_exe = clean_cmd_text(config.get("sdkmanager_exe", ""))
    gradle_exe = clean_cmd_text(config.get("gradle_exe", ""))

    java_bin = ""
    if java_exe:
        jp = Path(java_exe)
        if jp.exists() or jp.parent:
            java_bin = str(jp.parent)
            if not java_home and jp.parent.name.lower() == "bin":
                java_home = str(jp.parent.parent)
    if not java_bin and java_home:
        java_bin = str(Path(java_home) / "bin")

    prepend: list[str] = []
    if java_bin:
        prepend.append(java_bin)
    if sdk_root:
        if sdkmanager_exe:
            sm = Path(sdkmanager_exe)
            if sm.parent.name.lower() == "bin":
                prepend.append(str(sm.parent))
        prepend.extend([
            str(Path(sdk_root) / "cmdline-tools" / "latest" / "bin"),
            str(Path(sdk_root) / "platform-tools"),
        ])
        build_tools = find_latest_build_tools_dir(sdk_root)
        if build_tools:
            prepend.append(build_tools)
    if gradle_exe:
        gp = Path(gradle_exe)
        if gp.parent:
            prepend.append(str(gp.parent))

    parts: list[str] = []
    if java_home:
        parts.append(f'set "JAVA_HOME={java_home}"')
    if sdk_root:
        parts.append(f'set "ANDROID_HOME={sdk_root}"')
        parts.append(f'set "ANDROID_SDK_ROOT={sdk_root}"')
    if prepend:
        path_prefix = ";".join(unique_existing_order(prepend))
        parts.append(f'set "PATH={path_prefix};%PATH%"')
    return " && ".join(parts)


def windows_comspec() -> str:
    return os.environ.get("COMSPEC") or str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe")


def make_temp_cmd_file(script: str) -> str:
    """Write a Windows batch file and return its path.

    This is intentionally used instead of passing a long quoted command as:
        [cmd.exe, /c, script]

    On Windows, subprocess.list2cmdline escapes embedded quotes as \". cmd.exe can
    then see literal backslashes and fail with errors like:
        '\"C:\\Android\\Sdk\\...\\sdkmanager.bat\"' is not recognized

    A temporary .cmd file avoids all nested-quote problems. The batch file contains
    normal Windows syntax such as:
        set "JAVA_HOME=C:\\..."
        call "C:\\Android\\Sdk\\cmdline-tools\\latest\\bin\\sdkmanager.bat" ...
    """
    temp_dir = Path(tempfile.gettempdir()) / "APKBuilderGUI"
    temp_dir.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="run_", suffix=".cmd", dir=str(temp_dir), text=True)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("@echo off\n")
        f.write("REM Temporary command generated by APK Builder GUI.\n")
        f.write(script.strip())
        f.write("\nexit /b %ERRORLEVEL%\n")
    return path


def windows_script_command(script: str) -> list[str]:
    return [windows_comspec(), "/d", "/c", make_temp_cmd_file(script)]


def run_windows_script_capture(script: str, timeout: int = 25) -> CommandResult:
    cmd_file = make_temp_cmd_file(script)
    try:
        return run_capture([windows_comspec(), "/d", "/c", cmd_file], timeout=timeout)
    finally:
        try:
            Path(cmd_file).unlink(missing_ok=True)
        except Exception:
            pass


def run_windows_script_streaming(script: str, state, input_text: str | None = None, timeout_note: bool = False, cwd: str | None = None) -> int:
    cmd_file = make_temp_cmd_file(script)
    state.log("Temporary Windows command file created to avoid quote-escaping problems:", "INFO")
    state.log(cmd_file, "CMD")
    state.log("Command content:", "INFO")
    for line in script.split(" && "):
        state.log("  " + line, "CMD")
    try:
        return run_streaming([windows_comspec(), "/d", "/c", cmd_file], state, input_text=input_text, cwd=cwd)
    finally:
        try:
            Path(cmd_file).unlink(missing_ok=True)
        except Exception:
            pass
