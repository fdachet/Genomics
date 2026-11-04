import re
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path
from component_file_types import validate_component_type

FLAGS = ("--version", "-V", "-v")


def extract_version(output, executable_name=""):
    name = str(executable_name or "").lower()
    for line in str(output or "")[:10000].splitlines()[:30]:
        line = line.strip()
        if not line or len(line) > 250:
            continue
        if re.search(r"\b(error|not found|unknown option|invalid option|usage:|no such file)\b", line, re.I):
            continue
        match = re.search(r"\b(?:version|ver\.)\s*[:=]?\s*v?(\d+(?:\.\d+){1,3}(?:[-+][a-zA-Z0-9.]+)?)\b", line, re.I)
        if match:
            return match.group(1)
        match = re.match(r"^([a-zA-Z][a-zA-Z0-9_.+-]*)\s+\([^)]{1,100}\)\s+v?(\d+(?:\.\d+){1,3}(?:[-+][a-zA-Z0-9.]+)?)\b", line)
        if match and name and match.group(1).lower() == name:
            return match.group(2)
        match = re.match(r"^([a-zA-Z][a-zA-Z0-9_.+-]*)\s+v?(\d+(?:\.\d+){1,3}(?:[-+][a-zA-Z0-9.]+)?)\b", line)
        if match and name and match.group(1).lower() == name:
            return match.group(2)
        match = re.fullmatch(r"v?(\d+(?:\.\d+){1,3}(?:[-+][a-zA-Z0-9.]+)?)", line, re.I)
        if match:
            return match.group(1)
    return ""


def inspect_jar(path):
    result = {"version": "", "main_class": "", "minimum_java": "", "class_major": 0, "error": ""}
    try:
        with zipfile.ZipFile(path) as archive:
            raw = archive.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace")
            unfolded = []
            for line in raw.splitlines():
                if line.startswith(" ") and unfolded:
                    unfolded[-1] += line[1:]
                else:
                    unfolded.append(line)
            fields = {}
            for line in unfolded:
                if ":" in line:
                    key, value = line.split(":", 1)
                    fields[key.lower().strip()] = value.strip()
            result["main_class"] = fields.get("main-class", "")
            for key in ("implementation-version", "bundle-version", "specification-version"):
                value = fields.get(key, "")
                if value and re.search(r"\d", value):
                    result["version"] = value
                    break
            majors = []
            for item in archive.infolist():
                if item.filename.endswith(".class") and not item.filename.startswith("META-INF/versions/"):
                    with archive.open(item) as source:
                        header = source.read(8)
                    if len(header) == 8 and header[:4] == b"\xca\xfe\xba\xbe":
                        majors.append(int.from_bytes(header[6:8], "big"))
            if majors:
                major = max(majors)
                result["class_major"] = major
                if major >= 49:
                    result["minimum_java"] = str(major - 44)
                elif major == 48:
                    result["minimum_java"] = "1.4"
                elif major == 47:
                    result["minimum_java"] = "1.3"
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        result["error"] = "Cannot read JAR metadata: " + str(exc)
    return result


def probe_binary_version(source, runtime_image, selected_flag="Auto", timeout=15, runner=None, component_kind="Binary"):
    path = Path(str(source or "").strip()).expanduser()
    image = str(runtime_image or "").strip()
    if not path.is_file():
        return {"version": "", "attempts": [], "error": f"Component file does not exist: {path}"}
    if path.suffix.lower() == ".jar" or str(component_kind).lower() == "jar/application":
        meta = inspect_jar(path)
        details = ["Java application archive (JAR)"]
        if meta["main_class"]:
            details.append("Main-Class: " + meta["main_class"])
        if meta["minimum_java"]:
            details.append("Minimum Java version for bundled class files: " + meta["minimum_java"])
        details.append("Application version from JAR manifest: " + (meta["version"] or "not declared"))
        details.append("Executing this JAR additionally requires a compatible Java runtime in the final image.")
        return {"version": meta["version"], "attempts": [{"flag": "JAR manifest", "code": "METADATA", "output": "\n".join(details)}], "error": meta["error"], "java_minimum": meta["minimum_java"]}
    valid, error = validate_component_type("Binary", path)
    if not valid:
        return {"version": "", "attempts": [], "error": error}
    if not image:
        return {"version": "", "attempts": [], "error": "No runtime base image selected in Tab 1."}
    docker = shutil.which("docker")
    if not docker:
        return {"version": "", "attempts": [], "error": "docker.exe was not found. Check Docker Desktop in Tab 1."}
    flags = FLAGS if selected_flag == "Auto" else (selected_flag,)
    if any(flag not in FLAGS for flag in flags):
        return {"version": "", "attempts": [], "error": "Unsupported version flag."}
    run = runner or subprocess.run
    kwargs = {"capture_output": True, "text": True, "errors": "replace", "timeout": timeout, "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    attempts = []
    def invoke(argv):
        return run(argv, **kwargs)
    try:
        checked = invoke([docker, "image", "inspect", image])
        if checked.returncode:
            return {"version": "", "attempts": [], "error": "Docker cannot inspect runtime image " + image + ". Load it in Tab 2. " + (checked.stderr or "")[:1500]}
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"version": "", "attempts": [], "error": "Docker image inspection failed: " + str(exc)}
    path = path.resolve()
    for flag in flags:
        container_name = "docker-version-probe-" + uuid.uuid4().hex[:12]
        script = 'chmod +x /tmp/version_probe && exec /tmp/version_probe "$1"'
        created = False
        try:
            create = invoke([docker, "create", "--name", container_name, "--network", "none", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "64", "--memory", "256m", "--entrypoint", "/bin/sh", image, "-c", script, "version-probe", flag])
            if create.returncode:
                detail = ((create.stderr or "") + (create.stdout or "")).strip()[:1800]
                attempts.append({"flag": flag, "code": create.returncode, "output": "Docker container creation failed: " + detail})
                break
            created = True
            copied = invoke([docker, "cp", str(path), container_name + ":/tmp/version_probe"])
            if copied.returncode:
                attempts.append({"flag": flag, "code": copied.returncode, "output": "Could not copy binary into temporary container: " + (copied.stderr or "")[:1800]})
                break
            started = invoke([docker, "start", "-a", container_name])
            output = ((started.stdout or "") + "\n" + (started.stderr or "")).strip()[:3000]
            attempts.append({"flag": flag, "code": started.returncode, "output": output})
            if started.returncode == 0:
                version = extract_version(output, path.name)
                if version:
                    return {"version": version, "attempts": attempts, "error": ""}
        except subprocess.TimeoutExpired:
            attempts.append({"flag": flag, "code": "TIMEOUT", "output": f"Docker did not finish this step within {timeout} seconds"})
            break
        except (OSError, ValueError) as exc:
            attempts.append({"flag": flag, "code": "ERROR", "output": str(exc)})
            break
        finally:
            if created:
                try:
                    run([docker, "rm", "-f", container_name], capture_output=True, text=True, timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                except (subprocess.TimeoutExpired, OSError):
                    pass
    details = "No verified version could be obtained. Inspect the command output; the binary may not support standard version flags, or may not run in the selected runtime."
    return {"version": "", "attempts": attempts, "error": details}
