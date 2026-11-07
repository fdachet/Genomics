import hashlib
import json
import os
import queue
import re
import shlex
import subprocess
import threading
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


NAME_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9.+_:-]*$')
QUERY_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9.+_:-]*$')
IMAGE_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$')

DISTRIBUTION_REPOSITORIES = {
    'AlmaLinux': 'almalinux',
    'Alpine Linux': 'alpine',
    'Amazon Linux': 'amazonlinux',
    'Debian': 'debian',
    'Fedora': 'fedora',
    'Oracle Linux': 'oraclelinux',
    'Rocky Linux': 'rockylinux/rockylinux',
    'Ubuntu': 'ubuntu',
}


def image_tag_metadata(entry):
    images = entry.get('images') or []
    sizes = {}
    architectures = set()
    for item in images:
        if item.get('os') not in ('linux', None):
            continue
        architecture = str(item.get('architecture') or '').strip()
        if not architecture or architecture == 'unknown':
            continue
        variant = str(item.get('variant') or '').strip()
        key = architecture + ('/' + variant if architecture == 'arm' and variant else '')
        architectures.add(architecture)
        architectures.add(key)
        try:
            size = int(item.get('size') or 0)
        except (ValueError, TypeError):
            size = 0
        if size > 0:
            sizes[key] = size
    try:
        full_size = int(entry.get('full_size') or 0)
    except (ValueError, TypeError):
        full_size = 0
    if len({str(item.get('architecture') or '') for item in images if item.get('os') in ('linux', None)}) == 1 and full_size > 0:
        for architecture in architectures:
            sizes.setdefault(architecture, full_size)
    return {'tag': str(entry.get('name') or ''), 'architectures': sorted(architectures),
            'sizes': sizes, 'full_size': full_size}


def docker_hub_image_parts(image):
    image = str(image or '').strip()
    if '@' in image or not IMAGE_PATTERN.fullmatch(image):
        return None
    if image.startswith('docker.io/'):
        image = image[10:]
    pieces = image.rsplit(':', 1)
    if len(pieces) != 2:
        return None
    name, tag = pieces
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', tag):
        return None
    segments = name.split('/')
    if len(segments) == 1:
        namespace, repository = 'library', segments[0]
    elif len(segments) == 2:
        namespace, repository = segments
    else:
        return None
    if not all(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', value) for value in (namespace, repository)):
        return None
    return namespace, repository, tag


def estimate_docker_hub_image_size(image, platform='', cancel=None, progress=None):
    parts = docker_hub_image_parts(image)
    if not parts:
        return {'image': image, 'size': None, 'reason': 'No Docker Hub size metadata available for this image reference.'}
    if cancel is not None and cancel.is_set():
        raise RuntimeError('Cancelled image-size lookup.')
    namespace, repository, tag = parts
    address = 'https://hub.docker.com/v2/repositories/' + namespace + '/' + repository + '/tags/' + quote(tag)
    if progress:
        progress('Checking Docker Hub reported image size for ' + image + ' (' + (platform or 'default architecture') + ')...')
    try:
        request = Request(address, headers={'Accept': 'application/json', 'User-Agent': 'Component-Docker-Builder/1.0'})
        with urlopen(request, timeout=20) as response:
            entry = json.load(response)
        metadata = image_tag_metadata(entry)
    except Exception as exc:
        if progress:
            progress('Image-size lookup unavailable: ' + str(exc))
        return {'image': image, 'size': None, 'reason': 'Docker Hub did not provide a size estimate.'}
    architecture = platform[len('linux/'):] if platform.startswith('linux/') else ''
    size = metadata['sizes'].get(architecture)
    if not size and not platform and len(metadata['sizes']) == 1:
        size = next(iter(metadata['sizes'].values()))
    if not size:
        return {'image': image, 'size': None, 'reason': 'No architecture-specific size reported by Docker Hub.'}
    return {'image': image, 'size': size, 'reason': 'Docker Hub reported image size'}


def list_distribution_tags(repository, cancel=None, progress=None, max_pages=6, filter_text=''):
    repository = str(repository or '').strip()
    if repository not in DISTRIBUTION_REPOSITORIES.values():
        raise ValueError('The distribution must be selected from the supported Docker Hub catalog.')
    keyword = str(filter_text or '').strip()
    if keyword and not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', keyword):
        raise ValueError('Enter letters, numbers, dots, dashes or underscores for the image-tag search.')
    segments = repository.split('/')
    namespace, image = ('library', segments[0]) if len(segments) == 1 else tuple(segments)
    base_address = 'https://hub.docker.com/v2/repositories/' + namespace + '/' + image + '/tags/'
    address = base_address + '?page_size=100' + ('&name=' + quote(keyword) if keyword else '')
    discovered = {}
    scanned = 0
    fallback = False
    page_limit = max(120, max_pages) if keyword else max_pages
    for page in range(page_limit):
        if cancel is not None and cancel.is_set():
            raise RuntimeError('Cancelled Docker Hub tag lookup.')
        if progress:
            progress(('Searching for older tags containing ' + keyword if keyword else 'Retrieving available release tags') +
                     ', page ' + str(page + 1) + '...')
        parsed = urlparse(address)
        if parsed.scheme != 'https' or parsed.hostname != 'hub.docker.com':
            raise RuntimeError('Unexpected Docker Hub pagination URL; request was stopped.')
        try:
            request = Request(address, headers={'Accept': 'application/json', 'User-Agent': 'Component-Docker-Builder/1.0'})
            with urlopen(request, timeout=20) as response:
                document = json.load(response)
        except Exception as exc:
            raise RuntimeError('Docker Hub release lookup failed: ' + str(exc) + '. You can type an image version manually.') from exc
        entries = document.get('results') or []
        if keyword and not fallback and page == 0 and (not entries or any(
                keyword.casefold() not in str(entry.get('name') or '').casefold() for entry in entries)):
            fallback = True
            address = base_address + '?page_size=100'
            if progress:
                progress('Docker Hub did not restrict the result set to matching tags. Scanning older pages instead.')
            continue
        scanned += 1
        for entry in entries:
            tag = str(entry.get('name') or '').strip()
            if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', tag):
                continue
            if keyword and keyword.casefold() not in tag.casefold():
                continue
            discovered[tag] = image_tag_metadata(entry)
        if progress:
            progress('Discovered ' + str(len(discovered)) + ' release tags so far.')
        next_page = document.get('next')
        if not next_page:
            break
        address = next_page
    if keyword and keyword in discovered:
        pass
    elif keyword and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', keyword):
        exact_address = base_address + quote(keyword)
        try:
            with urlopen(Request(exact_address, headers={'Accept': 'application/json',
                                                         'User-Agent': 'Component-Docker-Builder/1.0'}), timeout=20) as response:
                entry = json.load(response)
            if entry.get('name') == keyword:
                discovered[keyword] = image_tag_metadata(entry)
                if progress:
                    progress('Confirmed exact Docker Hub tag: ' + keyword)
        except HTTPError as exc:
            if exc.code != 404 and progress:
                progress('Exact-tag lookup was unavailable: ' + str(exc))
        except Exception as exc:
            if progress:
                progress('Exact-tag lookup was unavailable: ' + str(exc))
    if keyword and scanned >= page_limit and progress:
        progress('Repository tag enumeration reached its page limit. Use an exact tag to check availability directly.')
    if not discovered:
        if keyword:
            return []
        raise RuntimeError('No release tags were returned by Docker Hub. Enter a version or custom image name manually.')
    return list(discovered.values())


def pull_repository_image(image, platform='', cancel=None, progress=None):
    image = str(image or '').strip()
    if not IMAGE_PATTERN.fullmatch(image):
        raise ValueError('Enter a valid Docker image reference.')
    args = ['docker', 'pull']
    if platform:
        if not re.fullmatch(r'linux/(?:amd64|arm64|386|arm/v[5678]|ppc64le|s390x|riscv64)', platform):
            raise ValueError('Invalid selected Linux platform.')
        args.extend(['--platform', platform])
    args.append(image)
    if progress:
        progress('Downloading ' + image + (' (' + platform + ')' if platform else '') + ' with Docker; this will not change the project builder or runtime.')
    return _run(args, timeout=1800, cancel=cancel, progress=progress, idle_timeout=120)


def list_local_docker_images(cancel=None, progress=None):
    if progress:
        progress('Checking all Linux image tags already available in Docker Desktop...')
    raw = _run(['docker', 'image', 'ls', '--format', '{{.Repository}}|{{.Tag}}|{{.Size}}'],
               timeout=60, cancel=cancel, progress=progress, idle_timeout=0)
    images = {}
    for line in raw.splitlines():
        parts = line.strip().split('|', 2)
        if len(parts) != 3:
            continue
        repo, tag, size = parts
        if repo in ('', '<none>') or tag in ('', '<none>'):
            continue
        if not re.fullmatch(r'[a-zA-Z0-9_.:/-]+', repo) or not re.fullmatch(r'[a-zA-Z0-9_.-]+', tag):
            continue
        ref = repo + ':' + tag
        images[ref] = {'repository': repo, 'tag': tag, 'image': ref, 'size_label': size}
    records = sorted(images.values(), key=lambda row: (row['repository'].casefold(), row['tag'].casefold()))
    if progress:
        progress('Found ' + str(len(records)) + ' already-downloaded Docker image tags.')
    return records


def load_local_distribution_archive(path, archive_type='docker', platform='', cancel=None, progress=None):
    archive = Path(str(path or '').strip()).expanduser().resolve()
    if not archive.is_file():
        raise FileNotFoundError('Choose an existing local Linux archive file.')
    if not archive.name.lower().endswith(('.tar', '.tar.gz', '.tgz', '.tar.xz', '.txz',
                                          '.tar.bz2', '.tbz2', '.tar.zst')):
        raise ValueError('Local distributions must be Docker image archives or Linux rootfs TAR archives. ISO and ZIP are not supported.')
    if archive_type not in ('docker', 'rootfs'):
        raise ValueError('Select either a Docker image archive or a Linux root-filesystem TAR archive.')
    if progress:
        progress('Reading local archive: ' + str(archive))
        progress('Local file size: ' + f'{archive.stat().st_size / 1000000:.1f}' + ' MB. No image registry download is required.')
    if archive_type == 'docker':
        raw = _run(['docker', 'image', 'load', '--input', str(archive)],
                   timeout=3600, cancel=cancel, progress=progress, idle_timeout=0)
        images = re.findall(r'^Loaded image:\s*(\S.+?)\s*$', raw, re.MULTILINE)
        ids = re.findall(r'^Loaded image ID:\s*(sha256:[a-fA-F0-9]+)\s*$', raw, re.MULTILINE)
        candidates = list(dict.fromkeys(images + ids))
        if not candidates:
            raise RuntimeError('Docker loaded the archive but did not report an image name or ID. Use docker image ls to identify the imported image.')
        return {'archive': str(archive), 'type': archive_type, 'images': candidates, 'output': raw}
    stem = archive.name
    for extension in ('.tar.gz', '.tar.xz', '.tar.bz2', '.tar.zst', '.tgz', '.txz', '.tbz2', '.tar'):
        if stem.lower().endswith(extension):
            stem = stem[:-len(extension)]
            break
    stem = re.sub(r'[^a-z0-9_.-]+', '-', stem.lower()).strip('.-')[:45] or 'rootfs'
    tag = 'local-distribution/' + stem + ':' + uuid.uuid4().hex[:10]
    args = ['docker', 'image', 'import']
    if platform:
        if not re.fullmatch(r'linux/(?:amd64|arm64|386|arm/v[5678]|ppc64le|s390x|riscv64)', platform):
            raise ValueError('Invalid selected Linux platform.')
        args.extend(['--platform', platform])
    args.extend([str(archive), tag])
    raw = _run(args, timeout=3600, cancel=cancel, progress=progress, idle_timeout=0)
    return {'archive': str(archive), 'type': archive_type, 'images': [tag], 'output': raw}


def package_name(value):
    name = str(value or '').strip()
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError('Invalid Linux package name: ' + name)
    return name


def _run(args, timeout=120, cancel=None, progress=None, idle_timeout=75, max_output_lines=1400):
    if cancel is not None and cancel.is_set():
        raise RuntimeError('Cancelled.')
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               creationflags=flags)
    started = time.monotonic()
    last_activity = started
    received = queue.Queue()
    output_parts = []
    remainder = ''

    def reader():
        try:
            while True:
                chunk = os.read(process.stdout.fileno(), 4096)
                if not chunk:
                    break
                received.put(chunk)
        except Exception as exc:
            received.put(('reader_error', str(exc)))
        finally:
            received.put(None)

    threading.Thread(target=reader, daemon=True).start()
    ended = False
    try:
        while not ended:
            now = time.monotonic()
            if cancel is not None and cancel.is_set():
                raise RuntimeError('Cancelled the running Docker operation.')
            if now - started > timeout:
                raise RuntimeError('Docker operation timed out after ' + str(timeout) + ' seconds. Check Docker Desktop, DNS, and distribution mirrors.')
            if idle_timeout and now - last_activity > idle_timeout:
                raise RuntimeError('No output from Docker for ' + str(idle_timeout) + ' seconds. The repository or network may be unresponsive.')
            try:
                chunk = received.get(timeout=.25)
            except queue.Empty:
                continue
            if chunk is None:
                ended = True
                break
            if isinstance(chunk, tuple):
                raise RuntimeError('Unable to read Docker output: ' + chunk[1])
            last_activity = time.monotonic()
            remainder += chunk.decode('utf-8', 'replace').replace('\r', '\n')
            lines = remainder.split('\n')
            remainder = lines.pop()
            for line in lines:
                output_parts.append(line)
                if progress is not None and line.strip():
                    progress(line[-1700:])
            if max_output_lines and len(output_parts) > max_output_lines:
                output_parts = output_parts[-min(900, max_output_lines):]
            if len(remainder) > 12000:
                output_parts.append(remainder)
                if progress is not None:
                    progress(remainder[-1700:])
                remainder = ''
        process.wait(timeout=10)
    except Exception:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=10)
        except Exception:
            pass
        raise
    output = '\n'.join(output_parts + ([remainder] if remainder else []))
    if remainder and progress is not None:
        progress(remainder[-1700:])
    if process.returncode:
        raise RuntimeError(('Docker command failed:\n' + output).strip()[-3500:])
    return output


def _docker_shell(image, script, network='none', timeout=180, cancel=None, progress=None, platform='', max_output_lines=1400):
    container_name = 'component-pkgfinder-' + uuid.uuid4().hex[:12]
    try:
        args = ['docker', 'run', '--rm', '--pull=never', '--network=' + network]
        if platform:
            args.extend(['--platform', platform])
        args.extend(['--name', container_name, '--user', '0', '--entrypoint', '/bin/sh', image, '-c', script])
        return _run(args,
                    timeout, cancel, progress, max_output_lines=max_output_lines)
    except Exception:
        try:
            _run(['docker', 'rm', '-f', container_name], 20, idle_timeout=0)
        except Exception:
            pass
        raise


def inspect_repository_image(image, cancel=None, progress=None, platform=''):
    image = str(image or '').strip()
    if not image:
        raise ValueError('Select a builder or runtime image in Tab 1 first.')
    if progress:
        progress('Checking selected image ' + image)
    _run(['docker', 'image', 'inspect', image], 45, cancel)
    script = '''set -e
if [ -r /etc/os-release ]; then . /etc/os-release; fi
printf 'ID=%s\nID_LIKE=%s\nVERSION_ID=%s\nVERSION=%s\nVERSION_CODENAME=%s\nPRETTY_NAME=%s\n' "${ID:-unknown}" "${ID_LIKE:-}" "${VERSION_ID:-}" "${VERSION:-}" "${VERSION_CODENAME:-${UBUNTU_CODENAME:-}}" "${PRETTY_NAME:-unknown}"
if [ -r /etc/lsb-release ]; then . /etc/lsb-release; printf 'LSB_CODENAME=%s\n' "${DISTRIB_CODENAME:-}"; fi
if command -v dpkg >/dev/null 2>&1; then printf 'MANAGER=apt\n'; dpkg --print-architecture | sed 's/^/ARCH=/';
elif command -v apk >/dev/null 2>&1; then printf 'MANAGER=apk\n'; apk --print-arch | sed 's/^/ARCH=/';
elif command -v dnf >/dev/null 2>&1; then printf 'MANAGER=dnf\n'; uname -m | sed 's/^/ARCH=/';
elif command -v yum >/dev/null 2>&1; then printf 'MANAGER=yum\n'; uname -m | sed 's/^/ARCH=/';
elif command -v microdnf >/dev/null 2>&1; then printf 'MANAGER=microdnf\n'; uname -m | sed 's/^/ARCH=/';
else printf 'MANAGER=unsupported\n'; uname -m | sed 's/^/ARCH=/'; fi
if [ -f /etc/debian_version ]; then sed 's/^/DEBIAN_VERSION=/' /etc/debian_version | head -n 1; fi
if [ -f /etc/apt/sources.list ] || [ -d /etc/apt/sources.list.d ]; then
  for file in /etc/apt/sources.list /etc/apt/sources.list.d/*.list; do
    [ -f "$file" ] || continue
    while IFS= read -r line; do
      case "$line" in 'deb '*|'deb-src '*) printf 'REPO|%s\n' "$line";; esac
    done < "$file"
  done
fi
for file in /etc/apt/sources.list.d/*.sources; do
  [ -f "$file" ] || continue
  while IFS= read -r line; do
    case "$line" in 'URIs: '*|'Suites: '*|'Components: '*) printf 'REPO|%s\n' "$line";; esac
  done < "$file"
done
if [ -f /etc/apk/repositories ]; then while IFS= read -r line; do
  case "$line" in ''|'#'*) ;; *) printf 'REPO|%s\n' "$line";; esac
done < /etc/apk/repositories; fi
for file in /etc/yum.repos.d/*.repo; do
  [ -f "$file" ] || continue
  while IFS= read -r line; do
    case "$line" in baseurl=*|metalink=*|mirrorlist=*) printf 'REPO|%s\n' "$line";; esac
  done < "$file"
done'''
    text = _docker_shell(image, script, timeout=45, cancel=cancel, progress=progress, platform=platform)
    result = {'image': image, 'repos': [], 'platform': platform}
    for line in text.splitlines():
        if line.startswith('REPO|'):
            result['repos'].append(line[5:])
        elif '=' in line:
            key, value = line.split('=', 1)
            result[key.strip().lower()] = value.strip()
    if not result.get('version_codename'):
        result['version_codename'] = result.get('lsb_codename', '')
    if not result.get('version_codename'):
        match = re.search(r'\(([-a-zA-Z0-9_]+)\)', result.get('version', ''))
        if match:
            result['version_codename'] = match.group(1).lower()
    if not result.get('version_codename'):
        for source_line in result['repos']:
            parts = source_line.split()
            if len(parts) >= 4 and parts[0] in ('deb', 'deb-src'):
                candidate = parts[2].lower()
                if re.fullmatch('[a-z][a-z0-9_-]*', candidate) and not candidate.endswith(('-updates', '-security', '-backports')):
                    result['version_codename'] = candidate
                    break
    if platform:
        machine = result.get('arch', '').lower()
        if machine in ('x86_64', 'amd64'):
            machine = 'amd64'
        elif machine in ('aarch64', 'arm64'):
            machine = 'arm64'
        elif machine in ('armhf', 'armv7l', 'armv7'):
            machine = 'arm/v7'
        expected = platform[len('linux/'):]
        if machine != expected:
            raise RuntimeError('The image reported architecture ' + result.get('arch', '?') + ' instead of requested ' + expected + '. Select a compatible image platform.')
    return result


def _repository_override(info, archive=False, repository=''):
    repository = str(repository or '').strip()
    manager = info.get('manager')
    if repository:
        if manager == 'apt':
            pieces = repository.split()
            if len(pieces) < 4 or pieces[0] != 'deb':
                raise ValueError('Enter an APT source line: deb https://host/path release main')
            url = pieces[1]
        elif manager == 'apk':
            pieces = [repository]
            url = repository
        else:
            raise ValueError('Custom repository overrides currently require APT or APK; configure DNF/YUM repos in the selected base image.')
        address = urlparse(url)
        if address.scheme not in ('http', 'https') or not address.netloc or address.username or address.password:
            raise ValueError('Repository URL must be a valid HTTP(S) address without credentials.')
        if re.search(r'[\r\n\x00-\x1f]', repository):
            raise ValueError('Invalid repository characters.')
        if manager == 'apt' and not all(re.fullmatch(r'[A-Za-z0-9._/+:-]+', part) for part in pieces[2:]):
            raise ValueError('Invalid repository distribution/components.')
        return repository
    if not archive:
        return ''
    if manager != 'apt':
        raise ValueError('Automatic archive discovery is currently supported for APT distributions. Supply a repository override where supported.')
    release = str(info.get('version_codename') or '').strip().lower()
    if not re.fullmatch('[a-z0-9][a-z0-9_-]*', release):
        raise ValueError('The release codename cannot be identified automatically. Enter a complete APT source line in Repository override.')
    family = str(info.get('id') or '').lower()
    components = []
    for source_line in info.get('repos') or []:
        parts = source_line.split()
        if len(parts) >= 4 and parts[0] == 'deb' and parts[2] == release:
            components = [part for part in parts[3:] if re.fullmatch('[a-zA-Z0-9_-]+', part)]
            if components:
                break
        if len(parts) >= 2 and parts[0] == 'Components:':
            components = [part for part in parts[1:] if re.fullmatch('[a-zA-Z0-9_-]+', part)]
    if not components:
        components = ['main']
    selection = ' '.join(components)
    for candidate in (family, *str(info.get('id_like') or '').lower().split()):
        if candidate == 'debian':
            return 'deb http://archive.debian.org/debian ' + release + ' ' + selection
        if candidate == 'ubuntu':
            return 'deb http://old-releases.ubuntu.com/ubuntu ' + release + ' ' + selection
    raise ValueError('No verified automatic archive template exists for this Linux family. Enter a repository override instead.')


def _repository_setup(info, use_archive=False, source=False, repository=''):
    manager = info.get('manager')
    override = _repository_override(info, use_archive, repository)
    if manager == 'apt':
        apt_options = ' -o Acquire::Retries=0 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20'
        if override:
            lines = [shlex.quote(override)]
            if source:
                if override.startswith('deb '):
                    lines.append(shlex.quote('deb-src ' + override[4:]))
            setup = "printf '%s\\n' " + ' '.join(lines) + ' > /etc/apt/sources.list; '
            setup += "if [ -d /etc/apt/sources.list.d ]; then for f in /etc/apt/sources.list.d/*.list; do [ ! -f \"$f\" ] || mv \"$f\" \"$f.disabled\"; done; fi; "
            option = 'apt-get' + apt_options + (' -o Acquire::Check-Valid-Until=false' if use_archive else '')
            setup += option + ' update'
            return setup, option
        if source:
            return "for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list; do [ -f \"$f\" ] || continue; sed -n 's/^deb /deb-src /p' \"$f\" >> /tmp/component-src.list; done; if [ -s /tmp/component-src.list ]; then cat /tmp/component-src.list >> /etc/apt/sources.list; fi; for f in /etc/apt/sources.list.d/*.sources; do [ ! -f \"$f\" ] || sed -i 's/^Types: deb$/Types: deb deb-src/' \"$f\"; done; apt-get" + apt_options + ' update', 'apt-get' + apt_options
        return 'apt-get' + apt_options + ' update', 'apt-get' + apt_options
    if manager == 'apk':
        if override:
            return "printf '%s\\n' " + shlex.quote(override) + ' > /etc/apk/repositories; apk update', 'apk'
        return 'apk update', 'apk'
    if manager == 'dnf':
        return 'dnf -q makecache', 'dnf'
    if manager == 'yum':
        return 'yum -q makecache', 'yum'
    raise ValueError('This image has no supported repository downloader: ' + str(manager))


def repository_search(info, query, use_archive=False, cancel=None, repository='', progress=None):
    if not QUERY_PATTERN.fullmatch(str(query).strip()):
        raise ValueError('Enter a package name or keyword using letters, numbers, _, +, :, . or -.')
    query = str(query).strip()
    setup, manager = _repository_setup(info, use_archive, repository=repository)
    quoted = shlex.quote(query)
    if info['manager'] == 'apt':
        search = ("apt-cache dumpavail | awk -v keyword=" + quoted +
                  " 'BEGIN { needle=tolower(keyword); n=0 } "
                  "/^Package: / { name=substr($0,10) } "
                  "/^Version: / { version=substr($0,10) } "
                  "/^Description: / { description=substr($0,14) } "
                  "/^$/ { if (name != \"\" && index(tolower(name),needle)>0 && !seen[name]++) "
                  "{ gsub(/[|\\r\\n]/,\" \",description); printf \"PACKAGE|%s|%s|%s\\n\",name,version,description; n++ } "
                  "name=\"\"; version=\"\"; description=\"\" } "
                  "END { if (name != \"\" && index(tolower(name),needle)>0 && !seen[name]++) "
                  "{ gsub(/[|\\r\\n]/,\" \",description); printf \"PACKAGE|%s|%s|%s\\n\",name,version,description } }'")
    elif info['manager'] == 'apk':
        search = "apk search -v " + quoted + " | head -n 100"
    elif info['manager'] == 'dnf':
        search = 'dnf -q search ' + quoted + ' | head -n 100'
    else:
        search = 'yum -q search ' + quoted + ' | head -n 100'
    if progress:
        progress('Refreshing package-name indexes (no binary packages will be downloaded)...')
    def search_progress(line):
        if progress and not line.startswith('PACKAGE|'):
            progress(line)
    text = _docker_shell(info['image'], 'set -e; ' + setup + '; echo PACKAGE_FINDER_SEARCH_BEGIN; ' + search,
                         network='default', timeout=240, cancel=cancel, progress=search_progress,
                         platform=info.get('platform', ''), max_output_lines=0)
    records = []
    seen_names = set()
    for row in text.splitlines():
        row = row.strip()
        if not row:
            continue
        version = ''
        if info['manager'] == 'apt' and row.startswith('PACKAGE|'):
            pieces = row.split('|', 3)
            if len(pieces) != 4:
                continue
            _, name, version, description = pieces
        elif info['manager'] == 'apk' and ' - ' in row:
            label, description = row.split(' - ', 1)
            match = re.match(r'^(.+)-([0-9][^-]*)-r[0-9]+$', label.strip())
            name = match.group(1) if match else label.split(' ', 1)[0]
            version = label[len(name) + 1:] if label.startswith(name + '-') else ''
        elif info['manager'] in ('dnf', 'yum'):
            match = re.match(r'^([A-Za-z0-9_.+:-]+)\s*:\s*(.+)$', row)
            if not match:
                continue
            name, description = match.group(1).split('.', 1)[0], match.group(2)
        else:
            continue
        if NAME_PATTERN.fullmatch(name) and name not in seen_names:
            records.append({'name': name, 'version': version, 'description': description.strip()})
            seen_names.add(name)
    return records, text


def repository_details(info, name, use_archive=False, cancel=None, repository='', progress=None):
    name = package_name(name)
    setup, manager = _repository_setup(info, use_archive, repository=repository)
    quoted = shlex.quote(name)
    if info['manager'] == 'apt':
        command = 'apt-cache show ' + quoted + ' | head -n 90'
    elif info['manager'] == 'apk':
        command = 'apk info -a ' + quoted + ' | head -n 100'
    elif info['manager'] == 'dnf':
        command = 'dnf -q info ' + quoted + ' | head -n 100'
    else:
        command = 'yum -q info ' + quoted + ' | head -n 100'
    if progress:
        progress('Refreshing repository metadata for ' + name)
    return _docker_shell(info['image'], 'set -e; ' + setup + '; echo PACKAGE_FINDER_DETAILS_BEGIN; ' + command,
                         network='default', timeout=240, cancel=cancel, progress=progress, platform=info.get('platform', ''))


def _copy_packages(image, script, folder, cancel=None, progress=None, platform=''):
    container = ''
    try:
        if progress:
            progress('Creating temporary download container')
        args = ['docker', 'create', '--pull=never', '--network=default', '--user', '0']
        if platform:
            args.extend(['--platform', platform])
        args.extend(['--entrypoint', '/bin/sh', image, '-c', script])
        container = _run(args, 40, cancel).strip()
        if not re.fullmatch(r'[a-fA-F0-9]{12,64}', container):
            raise RuntimeError('Docker did not return a valid temporary container ID.')
        if progress:
            progress('Starting the distribution package manager in Docker')
        output = _run(['docker', 'start', '-a', container], 600, cancel, progress)
        status = _run(['docker', 'inspect', '--format', '{{.State.ExitCode}}', container], 35, cancel).strip()
        if status != '0':
            raise RuntimeError('The Linux package manager failed (exit ' + status + '):\n' + output[-2600:])
        if progress:
            progress('Copying downloaded package files to ' + str(folder))
        folder.mkdir(parents=True, exist_ok=True)
        _run(['docker', 'cp', container + ':/package_cache/.', str(folder)], 180, cancel, progress)
        return output
    finally:
        if container:
            try:
                _run(['docker', 'rm', '-f', container], 35)
            except Exception:
                pass


def _cache_distribution_folder(info):
    image = str(info.get('image') or '').strip()
    reference = image.rsplit('/', 1)[-1]
    tag = reference.rsplit(':', 1)[-1] if ':' in reference else reference
    platform = str(info.get('platform') or '').strip()
    architecture = platform.replace('/', '_') if platform.startswith('linux/') else 'linux_' + str(info.get('arch') or 'unknown')
    return (re.sub(r'[^A-Za-z0-9_.-]', '_', tag) + '_' +
            re.sub(r'[^A-Za-z0-9_.-]', '_', architecture))


def cached_repository_package(info, name, cache_root):
    name = package_name(name)
    folder = Path(cache_root).expanduser().resolve() / _cache_distribution_folder(info) / name
    metadata = folder / 'package_manifest.json'
    if not metadata.is_file():
        return None
    try:
        manifest = json.loads(metadata.read_text(encoding='utf-8'))
        if manifest.get('image') != info.get('image') or manifest.get('package') != name:
            return None
        if manifest.get('platform', '') != info.get('platform', ''):
            return None
        files = manifest.get('files') or []
        if not files:
            return None
        for item in files:
            path = Path(item.get('path', '')).resolve()
            if path.parent != folder or not path.is_file():
                return None
            if hashlib.sha256(path.read_bytes()).hexdigest() != item.get('sha256'):
                return None
        return manifest
    except (OSError, ValueError, TypeError, KeyError):
        return None


def repository_download(info, name, cache_root, use_archive=False, cancel=None, repository='', progress=None,
                        allow_unauthenticated=False):
    name = package_name(name)
    existing = cached_repository_package(info, name, cache_root)
    if existing:
        if progress:
            progress('Package already saved and checksum verified: ' + str(Path(existing['files'][0]['path']).parent))
        return existing, 'Reused locally saved package; no repository download was necessary.'
    setup, manager = _repository_setup(info, use_archive, repository=repository)
    quoted = shlex.quote(name)
    family = info['manager']
    if family == 'apt':
        authentication_option = (' -o APT::Get::AllowUnauthenticated=true --allow-unauthenticated'
                                 if allow_unauthenticated else '')
        download = manager + authentication_option + ' download ' + quoted
        collect = ':'
        extension = '.deb'
    elif family == 'apk':
        download = 'apk fetch --output /package_cache ' + quoted
        collect = ':'
        extension = '.apk'
    elif family == 'dnf':
        download = ('if dnf download --help >/dev/null 2>&1; then '
                    'dnf download --destdir=/package_cache ' + quoted + '; '
                    'elif command -v yumdownloader >/dev/null 2>&1; then '
                    'yumdownloader --destdir=/package_cache ' + quoted + '; '
                    'else echo "Package-only download requires the DNF download plugin or yumdownloader" >&2; exit 4; fi')
        collect = ':'
        extension = '.rpm'
    else:
        raise ValueError('This package manager does not provide a supported package-only downloader. Use APT, APK or DNF with a download plugin.')
    safe_name = re.sub(r'[^A-Za-z0-9_.-]', '_', name)
    destination = Path(cache_root).expanduser().resolve() / _cache_distribution_folder(info) / safe_name
    if destination.exists() and any(destination.iterdir()):
        destination = destination.with_name(safe_name + '_' + str(int(time.time())))
    script = 'set -eu; ' + setup + '; mkdir -p /package_cache; cd /package_cache; ' + download + '; ' + collect
    if progress:
        progress('Downloading only the selected package ' + name + ' without installing or resolving its dependencies.')
    log = _copy_packages(info['image'], script, destination, cancel, progress, info.get('platform', ''))
    files = sorted(str(p) for p in destination.iterdir() if p.is_file() and p.suffix == extension)
    if not files:
        raise RuntimeError('No archive was returned for the selected package. Check that the package exists in the configured repository.')
    items = []
    for path in files:
        file = Path(path)
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        items.append({'name': file.name, 'path': str(file), 'sha256': digest, 'bytes': file.stat().st_size})
    not_authenticated = bool(allow_unauthenticated or re.search(
        r'KEYEXPIRED|NO_PUBKEY|GPG error|signatures were invalid|not signed|not authenticated', log, re.I))
    verification = ('UNVERIFIED: repository signature authentication failed or was explicitly bypassed; '
                    'SHA-256 records cache integrity only, not package authenticity'
                    if not_authenticated else 'Downloaded using native distribution package manager without reported signature failures')
    manifest = {'package': name, 'image': info['image'], 'os': info.get('pretty_name', ''),
                'architecture': info.get('arch', ''), 'manager': family, 'archive': bool(use_archive),
                'platform': info.get('platform', ''), 'distribution_id': info.get('id', ''),
                'distribution_version': info.get('version_id', ''),
                'dependencies_included': False, 'download_scope': 'selected_package_only',
                'repository_override': repository,
                'verification': verification, 'allow_unauthenticated': bool(allow_unauthenticated),
                'files': items}
    (destination / 'package_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest, log


def extract_package_executables(manifest, output_root, cancel=None, progress=None):
    manager = str(manifest.get('manager') or '')
    suffix = {'apt': '.deb', 'apk': '.apk', 'dnf': '.rpm'}.get(manager)
    if suffix is None:
        raise ValueError('Executable extraction requires a downloaded DEB, APK or RPM package.')
    package = package_name(manifest.get('package', ''))
    candidates = []
    for item in manifest.get('files') or []:
        archive = Path(item.get('path') or '')
        if not archive.is_file() or archive.suffix.lower() != suffix:
            continue
        if hashlib.sha256(archive.read_bytes()).hexdigest() != item.get('sha256'):
            raise RuntimeError('Cached package checksum does not match: ' + str(archive))
        if archive.name.lower().startswith(package.lower() + ('_' if suffix == '.deb' else '-')):
            candidates.append(archive)
    if not candidates:
        raise RuntimeError('The selected package archive is not in the cache. Download it first.')
    archive = candidates[0]
    image = str(manifest.get('image') or '').strip()
    if not IMAGE_PATTERN.fullmatch(image):
        raise ValueError('Invalid image reference in cached package metadata.')
    output = (Path(output_root).expanduser().resolve() /
              _cache_distribution_folder(manifest) / 'extracted_executables' / package)
    if output.exists() and any(output.iterdir()):
        output = output.with_name(package + '_' + str(int(time.time())))
    container = ''
    unique_name = 'component-pkg-extract-' + uuid.uuid4().hex[:14]
    safe_archive = '/tmp/package-to-extract' + suffix
    extraction_dir = '/tmp/package-extracted'
    if manager == 'apt':
        unpack = 'dpkg-deb -x ' + shlex.quote(safe_archive) + ' ' + extraction_dir
    elif manager == 'apk':
        unpack = 'mkdir -p ' + extraction_dir + '; tar -xzf ' + shlex.quote(safe_archive) + ' -C ' + extraction_dir
    else:
        unpack = 'mkdir -p ' + extraction_dir + '; cd ' + extraction_dir + '; rpm2cpio ' + shlex.quote(safe_archive) + ' | cpio -idm --quiet'
    script = ('set -eu; ' + unpack + '; find ' + extraction_dir +
              ' -type f -perm /111 -print | sed "s#^' + extraction_dir + '/#EXECUTABLE|#"')
    try:
        if progress:
            progress('Extracting compiled executables from ' + archive.name + ' inside the selected Linux distribution.')
        container = _run(['docker', 'create', '--pull=never', '--network=none', '--name', unique_name,
                          '--entrypoint', '/bin/sh', image, '-c', script],
                         timeout=60, cancel=cancel).strip()
        if not re.fullmatch(r'[a-fA-F0-9]{12,64}', container):
            raise RuntimeError('Docker did not return a valid temporary container ID for executable extraction.')
        _run(['docker', 'cp', str(archive), container + ':' + safe_archive],
             timeout=180, cancel=cancel, progress=progress, idle_timeout=0)
        raw = _run(['docker', 'start', '-a', container], timeout=600, cancel=cancel, progress=progress, idle_timeout=0)
        status = _run(['docker', 'inspect', '--format', '{{.State.ExitCode}}', container], timeout=40, cancel=cancel).strip()
        if status != '0':
            raise RuntimeError('The selected Linux distribution could not extract this package: ' + raw[-1600:])
        found = []
        for line in raw.splitlines():
            if line.startswith('EXECUTABLE|'):
                rel = line[len('EXECUTABLE|'):].strip()
                if rel and not rel.startswith(('/', '.')) and '..' not in Path(rel).parts:
                    found.append(rel)
        found = sorted(set(found))
        if not found:
            raise RuntimeError('This package contains no regular executable files. Save its package archive instead.')
        if len(found) > 350:
            raise RuntimeError('This package contains more than 350 executables. Save its package archive to avoid an unexpectedly large extraction.')
        items = []
        for index, rel in enumerate(found, 1):
            if cancel is not None and cancel.is_set():
                raise RuntimeError('Executable extraction cancelled.')
            destination = output / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            _run(['docker', 'cp', container + ':' + extraction_dir + '/' + rel, str(destination)],
                 timeout=120, cancel=cancel, idle_timeout=0)
            items.append({'path': str(destination), 'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
                          'bytes': destination.stat().st_size})
            if progress:
                progress('Extracted ' + str(index) + '/' + str(len(found)) + ': ' + rel)
        return {'package': package, 'image': image, 'folder': str(output), 'files': items,
                'verification': str(manifest.get('verification') or 'unknown')}
    finally:
        if container:
            try:
                _run(['docker', 'rm', '-f', container], timeout=35, idle_timeout=0)
            except Exception:
                pass


def repository_source_download(info, name, cache_root, use_archive=False, cancel=None, repository='', progress=None):
    name = package_name(name)
    if info.get('manager') != 'apt':
        raise ValueError('Source download is currently supported for APT-based distributions only. Select an official ZIP/TAR for other distributions.')
    setup, manager = _repository_setup(info, use_archive, source=True, repository=repository)
    normalized = re.sub('[^a-zA-Z0-9_.-]', '_', info['image'])
    safe_name = re.sub(r'[^A-Za-z0-9_.-]', '_', name)
    destination = Path(cache_root).resolve() / normalized / (safe_name + '_source')
    if destination.exists() and any(destination.iterdir()):
        destination = destination.with_name(safe_name + '_source_' + str(int(time.time())))
    script = 'set -eu; ' + setup + '; mkdir -p /package_cache; cd /package_cache; ' + manager + ' source --download-only ' + shlex.quote(name)
    log = _copy_packages(info['image'], script, destination, cancel, progress, info.get('platform', ''))
    files = sorted(str(p) for p in destination.iterdir() if p.is_file())
    if not files:
        raise RuntimeError('No source package was found. Your distribution may not configure deb-src repositories.')
    items = []
    for file in files:
        path = Path(file)
        items.append({'name': path.name, 'path': file, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size})
    manifest = {'package': name, 'image': info['image'], 'os': info.get('pretty_name', ''),
                'architecture': info.get('arch', ''), 'manager': 'apt-source',
                'verification': 'Downloaded via apt-get source from distribution Sources index', 'files': items}
    (destination / 'package_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest, log
