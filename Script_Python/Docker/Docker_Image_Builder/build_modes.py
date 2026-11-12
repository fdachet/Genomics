import re
import shlex

STRICT = 'strict'
PERMISSIVE = 'permissive'
ASSEMBLY = 'assembly'
MODES = (STRICT, PERMISSIVE, ASSEMBLY)


def normalize_mode(value):
    return value if value in MODES else PERMISSIVE


def optional_command(command, label, network_sensitive=False):
    text = str(command or '').strip()
    if text.startswith('RUN '):
        text = text[4:].strip()
    text = re.sub(r'\\[ \t]*\n[ \t]*', ' ', text).replace('\n', ' ')
    shell = 'mkdir -p /opt/component-builder; '
    if network_sensitive:
        skipped = shlex.quote(str(label or 'dependency step') + ' — skipped (downloads not authorized)')
        shell += 'if [ "$COMPONENT_BUILDER_ALLOW_DOWNLOADS" != 1 ]; then printf "%s\\n" ' + skipped + ' >> /opt/component-builder/setup-issues.txt; printf "%s\\n" ' + skipped + '; '
        shell += 'else ( ' + text + ' ) || { printf "%s\\n" ' + shlex.quote(str(label or 'dependency step') + ' — failed') + ' >> /opt/component-builder/setup-issues.txt; }; fi'
    else:
        shell += '( ' + text + ' ) || { printf "%s\\n" ' + shlex.quote(str(label or 'dependency step') + ' — failed') + ' >> /opt/component-builder/setup-issues.txt; }'
    return 'RUN /bin/sh -c ' + shlex.quote(shell)


def optional_lines(lines, label, network_sensitive=False, mode=PERMISSIVE):
    if mode == ASSEMBLY:
        return []
    if mode == STRICT:
        return list(lines)
    return [optional_command(line, label, network_sensitive) if line.startswith('RUN ') else line for line in lines]


def environment_lines(lines, mode):
    if mode == ASSEMBLY:
        return []
    if mode == STRICT:
        return list(lines)
    output = []
    for index, line in enumerate(lines):
        if line.startswith('RUN '):
            network = bool(re.search(r'pip install|BiocManager::install|install\.packages|cpanm\s', line, re.I))
            output.append(optional_command(line, 'Language environment step ' + str(index + 1), network))
        else:
            output.append(line)
    return output


def timestamp_image_tag(image, now=None):
    from datetime import datetime
    now = now or datetime.now()
    image = str(image or '').strip()
    if not image:
        image = 'docker-image'
    repository = image.rsplit(':', 1)[0] if ':' in image and image.rfind(':') > image.rfind('/') else image
    hour = now.hour % 12 or 12
    meridiem = 'am' if now.hour < 12 else 'pm'
    stamp = f'{now:%b}{now.day}_{hour}.{now.minute:02d}{meridiem}'
    return repository + ':' + stamp


def derive_next_tag(image):
    image = str(image or '').strip()
    candidate = timestamp_image_tag(image)
    if candidate != image:
        return candidate
    if ':' in image and image.rfind(':') > image.rfind('/'):
        repo, tag = image.rsplit(':', 1)
        match = re.fullmatch(r'(.*?)(?:_(\d+))?', tag)
        if match:
            return repo + ':' + match.group(1) + '_' + str(int(match.group(2) or 1) + 1)
    return image + '_2'
