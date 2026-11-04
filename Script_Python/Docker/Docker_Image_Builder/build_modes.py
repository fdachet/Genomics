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
        shell += 'if [ "$COMPONENT_BUILDER_ALLOW_DOWNLOADS" != 1 ]; then printf "%s\\n" ' + shlex.quote(str(label or 'dependency step') + ' — skipped (downloads not authorized)') + '; '
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


def derive_next_tag(image):
    image = str(image or '').strip()
    if ':' in image and image.rfind(':') > image.rfind('/'):
        repo, tag = image.rsplit(':', 1)
        match = re.fullmatch(r'(.*?)-rev(\d+)', tag)
        if match:
            return repo + ':' + match.group(1) + '-rev' + str(int(match.group(2)) + 1)
        return repo + ':' + tag + '-rev2'
    return image + ':rev2'
