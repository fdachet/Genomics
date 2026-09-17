from __future__ import annotations

from pathlib import Path

from command_utils import (
    IS_WINDOWS,
    find_sdk_tool,
    make_windows_env,
    is_executable_file,
    is_folder,
    project_has_gradle,
    run_capture,
    short_output,
)


def verify_component(component: dict, config: dict) -> tuple[str, str]:
    key = component["key"]
    verify_type = component.get("verify_type", "")
    value = str(config.get(key, "")).strip()

    if verify_type == "project":
        return verify_project(value)
    if verify_type == "output_dir":
        return verify_output_dir(value)
    if verify_type == "java_home":
        return verify_java_home(value)
    if verify_type == "sdk_root":
        return verify_sdk_root(value)
    if verify_type == "file_exists":
        return ("OK", value) if is_executable_file(value) else ("ERROR", f"File not found: {value or '(empty)'}")
    if verify_type == "command_version":
        args = component.get("command_args", [])
        if key == "gradle_exe":
            return verify_gradle_exe(value, config)
        return verify_command(value, args, config)
    if verify_type == "gradle_wrapper":
        return verify_gradle_wrapper(value)
    if component.get("kind") == "folder":
        return ("OK", value) if is_folder(value) else ("ERROR", f"Folder not found: {value or '(empty)'}")
    if component.get("kind") == "file":
        return ("OK", value) if is_executable_file(value) else ("ERROR", f"File not found: {value or '(empty)'}")
    return ("INFO", "No verification rule.")


def verify_project(value: str) -> tuple[str, str]:
    if not value:
        return "ERROR", "No Android source project selected."
    p = Path(value)
    if not p.exists():
        return "ERROR", f"Folder not found: {value}"
    if not project_has_gradle(value):
        return "WARN", "Folder exists, but no settings.gradle/build.gradle was found at root."
    manifest = p / "app" / "src" / "main" / "AndroidManifest.xml"
    wrapper = p / "gradlew.bat"
    notes = ["Gradle project detected"]
    notes.append("AndroidManifest.xml found" if manifest.exists() else "AndroidManifest.xml not found at app/src/main")
    notes.append("gradlew.bat found" if wrapper.exists() else "gradlew.bat not found")
    return "OK", "; ".join(notes)


def verify_output_dir(value: str) -> tuple[str, str]:
    if not value:
        return "ERROR", "No output folder selected."
    p = Path(value)
    try:
        p.mkdir(parents=True, exist_ok=True)
        test = p / ".write_test.tmp"
        test.write_text("ok", encoding="utf-8")
        test.unlink(missing_ok=True)
        return "OK", f"Writable folder: {p}"
    except Exception as exc:
        return "ERROR", f"Cannot write to output folder: {exc}"


def verify_java_home(value: str) -> tuple[str, str]:
    if not value:
        return "ERROR", "JAVA_HOME folder is empty."
    p = Path(value)
    java = p / "bin" / ("java.exe if windows" if False else "java")
    if IS_WINDOWS:
        java = p / "bin" / "java.exe"
    if java.exists():
        result = run_capture([str(java), "-version"], timeout=20)
        return ("OK" if result.returncode == 0 else "ERROR"), short_output(result.output) or str(java)
    return "ERROR", f"bin/java.exe not found under: {value}" if IS_WINDOWS else f"bin/java not found under: {value}"


def verify_sdk_root(value: str) -> tuple[str, str]:
    if not value:
        return "ERROR", "Android SDK root is empty."
    p = Path(value)
    if not p.exists():
        return "ERROR", f"Folder not found: {value}"
    checks = {
        "sdkmanager": find_sdk_tool(value, "sdkmanager"),
        "adb": find_sdk_tool(value, "adb"),
        "aapt2": find_sdk_tool(value, "aapt2"),
        "apksigner": find_sdk_tool(value, "apksigner"),
        "zipalign": find_sdk_tool(value, "zipalign"),
    }
    missing = [name for name, path in checks.items() if not path]
    if missing:
        return "WARN", f"SDK folder exists, but missing: {', '.join(missing)}"
    return "OK", "SDK root contains cmdline-tools, platform-tools, and build-tools tools."


def verify_command(value: str, args: list[str], config: dict | None = None) -> tuple[str, str]:
    if not value:
        return "ERROR", "No command/file path entered."
    command = [value] + list(args)
    env = make_windows_env(config or {}) if IS_WINDOWS else None
    result = run_capture(command, env=env, timeout=45)
    status = "OK" if result.returncode == 0 else "ERROR"
    return status, short_output(result.output) or f"Exit code {result.returncode}"


def verify_gradle_wrapper(value: str) -> tuple[str, str]:
    if not value:
        return "WARN", "No Gradle wrapper selected. A global Gradle executable may still work."
    p = Path(value)
    if not p.exists():
        return "ERROR", f"File not found: {value}"
    result = run_capture([str(p), "-v"], cwd=str(p.parent), timeout=45)
    status = "OK" if result.returncode == 0 else "WARN"
    return status, short_output(result.output) or f"Wrapper exists: {value}"


def verify_gradle_exe(value: str, config: dict | None = None) -> tuple[str, str]:
    """Verify global Gradle and warn clearly if it is older than 8.9."""
    if not value:
        return "ERROR", "No command/file path entered. Use Install -> Gradle to extract Gradle 8.9, or browse to gradle.bat."
    p = Path(value)
    if not p.exists():
        return "ERROR", f"File not found: {value}"
    env = make_windows_env(config or {}) if IS_WINDOWS else None
    result = run_capture([str(p), "-v"], env=env, timeout=45)
    if result.returncode != 0:
        return "ERROR", short_output(result.output) or f"Exit code {result.returncode}"
    import re
    m = re.search(r"Gradle\s+([0-9]+)\.([0-9]+)", result.output)
    if m:
        version = (int(m.group(1)), int(m.group(2)))
        if version < (8, 9):
            return "ERROR", f"Gradle {version[0]}.{version[1]} found, but this project needs Gradle 8.9 or newer. Select C:\\Gradle\\gradle-8.9\\bin\\gradle.bat."
    return "OK", short_output(result.output) or str(p)
