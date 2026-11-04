

import json
import os
import platform
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path


class DockerWindowsDiagnostics:


    def __init__(self, runtime_image="", builder_image="", emit=None):
        self.runtime_image = str(runtime_image or "").strip()
        self.builder_image = str(builder_image or "").strip()
        self.emit = emit or (lambda message: None)
        self.failures = []
        self.warnings = []
        self.passes = []
        self.docker = None

    def report(self, status, title, message=""):
        label = str(status).upper()
        self.emit(f"[{label}] {title}" + (f"\n        {message}" if message else "") + "\n")
        if label == "FAIL":
            self.failures.append(title)
        elif label == "WARN":
            self.warnings.append(title)
        elif label == "PASS":
            self.passes.append(title)

    @staticmethod
    def _run(args, timeout=30):
        try:
            result = subprocess.run(
                [str(a) for a in args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        except subprocess.TimeoutExpired:
            return 124, "", f"Timed out after {timeout} seconds"
        except (FileNotFoundError, PermissionError, OSError) as error:
            return 127, "", str(error)

    @staticmethod
    def _path_to_docker():
        cli = shutil.which("docker.exe") or shutil.which("docker")
        if cli:
            return cli
        if os.name == "nt":
            for key in ("PROGRAMFILES", "PROGRAMW6432", "PROGRAMFILES(X86)"):
                root = os.environ.get(key, "")
                if root:
                    test = Path(root) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe"
                    if test.is_file():
                        return str(test)
        return None

    @staticmethod
    def _desktop_executable():
        if os.name != "nt":
            return None
        for key in ("PROGRAMFILES", "PROGRAMW6432", "LOCALAPPDATA"):
            root = os.environ.get(key, "")
            if root:
                test = Path(root) / "Docker" / "Docker" / "Docker Desktop.exe"
                if test.is_file():
                    return str(test)
        return None

    def _exec(self, *args, timeout=30):
        return self._run([self.docker, *args], timeout=timeout)

    def _image_present(self, image):
        if not image:
            return False
        code, _out, _err = self._exec("image", "inspect", image, "--format", "{{.Id}}", timeout=15)
        return code == 0

    def _choose_image(self):
        for tag in (self.runtime_image, self.builder_image):
            if tag and self._image_present(tag):
                return tag
        code, out, _err = self._exec("image", "ls", "--format", "{{.Repository}}:{{.Tag}}", timeout=20)
        if code == 0:
            tags = [s.strip() for s in out.splitlines() if s.strip() and not s.startswith("<none>")]
            for image in tags:
                if image.startswith(("debian:", "ubuntu:", "alpine:", "busybox:")):
                    return image
        return ""

    def run(self):
        self.emit("WINDOWS DOCKER DIAGNOSTICS\n")
        self.emit("No software installation, image downloads, or permanent test containers.\n\n")
        if platform.system().lower() != "windows":
            self.report("WARN", "Host platform", "This checker is intended for the Windows-hosted GUI. Current host: " + platform.system())
        else:
            self.report("PASS", "Windows host", platform.platform())

        desktop = self._desktop_executable()
        if desktop:
            self.report("PASS", "Docker Desktop installation found", desktop)
        else:
            self.report("WARN", "Docker Desktop application not found in common locations", "Docker CLI may be provided separately or Docker Desktop installed elsewhere.")

        self.docker = self._path_to_docker()
        if not self.docker:
            self.report("FAIL", "Docker CLI not found", "Install Docker Desktop for Windows, or add docker.exe to PATH. Restart the GUI after installation.")
            return self._finish()
        self.report("PASS", "Docker CLI detected", self.docker)
        code, out, err = self._exec("--version")
        if code:
            self.report("FAIL", "Docker CLI cannot start", err or out)
            return self._finish()
        self.report("PASS", "Docker CLI responds", out)

        code, out, err = self._exec("context", "show")
        context = out if code == 0 else "unknown"
        if code == 0:
            self.report("PASS", "Active Docker context", context)
        else:
            self.report("WARN", "Could not inspect active Docker context", err)
        code, endpoint, endpoint_error = self._exec(
            "context", "inspect", "--format", "{{.Endpoints.docker.Host}}", timeout=15,
        )
        if code == 0 and endpoint:
            if endpoint.startswith(("ssh://", "tcp://")):
                self.report("WARN", "Docker context uses a potentially remote daemon", endpoint)
            elif endpoint.startswith("npipe:"):
                self.report("PASS", "Local Windows named-pipe Docker endpoint", endpoint)
            else:
                self.report("WARN", "Docker daemon endpoint is not a Windows named pipe", endpoint)
        elif code:
            self.report("WARN", "Could not inspect Docker daemon endpoint", endpoint_error)
        if os.environ.get("DOCKER_HOST"):
            self.report("WARN", "DOCKER_HOST override configured", "The current daemon may be remote: " + os.environ["DOCKER_HOST"])
        if os.environ.get("DOCKER_CONTEXT"):
            self.report("WARN", "DOCKER_CONTEXT override configured", os.environ["DOCKER_CONTEXT"])

        code, out, err = self._exec("version", "--format", "{{json .Server}}", timeout=35)
        if code:
            self.report("FAIL", "Docker engine not reachable", "Start Docker Desktop, select Linux containers, wait until Engine running, then retry. " + (err or out))
            return self._finish()
        try:
            server = json.loads(out)
            server_version = server.get("Version", "unknown")
        except (ValueError, TypeError):
            server_version = out[:200]
        self.report("PASS", "Docker engine is responding", f"Server version: {server_version}")

        code, out, err = self._exec("info", "--format", "{{json .}}", timeout=40)
        if code:
            self.report("FAIL", "Docker daemon info failed", err or out)
            return self._finish()
        try:
            info = json.loads(out)
        except (TypeError, ValueError):
            self.report("FAIL", "Docker info could not be decoded", out[:300])
            return self._finish()
        ostype = str(info.get("OSType", "")).lower()
        operating_system = info.get("OperatingSystem", "unknown")
        architecture = info.get("Architecture", "unknown")
        if ostype == "linux":
            self.report("PASS", "Linux container engine selected", f"OS: {operating_system} | Architecture: {architecture}")
        else:
            self.report("FAIL", "Linux container engine not selected", f"Docker reports OSType={ostype or 'unknown'}. In Docker Desktop switch to Linux containers.")
            return self._finish()
        self.report("PASS", "Docker storage driver", str(info.get("Driver", "unknown")))

        code, out, err = self._exec("buildx", "version", timeout=15)
        if code == 0:
            self.report("PASS", "Docker Buildx available", out.splitlines()[0] if out else "Available")
        else:
            self.report("WARN", "Docker Buildx unavailable", (err or out) + ". The image builder may require a working Buildx/BuildKit installation.")

        for label, tag in (("Selected runtime image", self.runtime_image), ("Selected builder image", self.builder_image)):
            if not tag:
                self.report("WARN", label + " not configured", "Choose the .tar archive in Tab 2, then click Load selected bases into Docker.")
            elif self._image_present(tag):
                self.report("PASS", label + " available locally", tag)
            else:
                self.report("WARN", label + " not loaded", f"{tag} is not found locally. In Tab 2 load its .tar archive into Docker.")

        image = self._choose_image()
        if not image:
            self.report("WARN", "Container and build smoke tests skipped", "No suitable local Linux test image was found; load the Debian runtime base in Tab 2 and rerun this check.")
            return self._finish()

        self.emit("\nUsing already-present local image: " + image + "\n")
        code, out, err = self._exec(
            "run", "--rm", "--pull=never", "--network=none", "--entrypoint", "/bin/sh",
            image, "-c", "printf DOCKER_RUN_OK", timeout=50,
        )
        if code or out != "DOCKER_RUN_OK":
            self.report("FAIL", "Linux container execution", err or out or f"Exit code {code}")
            return self._finish()
        self.report("PASS", "Linux container execution", "An isolated /bin/sh process ran and exited successfully.")

        with tempfile.TemporaryDirectory(prefix="docker_windows_check_") as temp:
            shared = Path(temp) / "mount"
            shared.mkdir()
            (shared / "probe.txt").write_text("WINDOWS_BIND_MOUNT_OK", encoding="ascii")
            code, out, err = self._exec(
                "run", "--rm", "--pull=never", "--network=none",
                "--mount", f"type=bind,source={shared},target=/docker_windows_check,readonly",
                "--entrypoint", "/bin/sh", image, "-c", "cat /docker_windows_check/probe.txt", timeout=50,
            )
            if code or out != "WINDOWS_BIND_MOUNT_OK":
                self.report("FAIL", "Windows-to-Linux bind mount", (err or out or f"Exit code {code}") + ". Verify Docker Desktop file sharing and engine context.")
            else:
                self.report("PASS", "Windows-to-Linux bind mount", "A file from a Windows temporary folder was read inside Linux.")

            context_dir = Path(temp) / "build"
            context_dir.mkdir()
            (context_dir / "Dockerfile").write_text(
                f"FROM {image}\nRUN /bin/sh -c 'printf DOCKER_BUILD_OK'\n", encoding="utf-8"
            )
            temporary_tag = "local/docker-windows-diagnostic:" + uuid.uuid4().hex[:12]
            try:
                code, out, err = self._exec(
                    "build", "--pull=false", "--network=none", "-t", temporary_tag,
                    str(context_dir), timeout=120,
                )
                if code:
                    self.report("FAIL", "Local Docker image build", (err or out)[-1200:] or f"Exit code {code}")
                else:
                    self.report("PASS", "Local Docker image build", "An offline Dockerfile built successfully using the existing base.")
            finally:
                self._exec("image", "rm", temporary_tag, timeout=30)

        return self._finish()

    def _finish(self):
        if self.failures:
            overall = "FAILED"
        elif self.warnings:
            overall = "READY WITH WARNINGS"
        else:
            overall = "ALL CHECKS PASSED"
        self.emit("\n" + "=" * 62 + "\n")
        self.emit(f"RESULT: {overall} | Passed: {len(self.passes)} | Warnings: {len(self.warnings)} | Failures: {len(self.failures)}\n")
        if self.failures:
            self.emit("Failed checks: " + "; ".join(self.failures) + "\n")
        return overall
