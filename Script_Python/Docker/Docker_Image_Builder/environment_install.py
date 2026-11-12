from __future__ import annotations

import json
import re
import shlex


def shell_run(script):
    if not str(script or '').strip():
        return []
    return ['RUN /bin/sh -ec ' + shlex.quote(str(script).replace('\r\n', '\n')), '']


def language_lines(plan):
    lines = []
    pv = plan['python_version']
    rv = plan['r_version']
    lv = plan['perl_version']
    config = plan['config']
    modules = plan['language_packages']
    if plan['python_required']:
        binary = ('python' + str(pv[0])) if pv else 'python'
        lines += shell_run('command -v ' + shlex.quote(binary) + ' >/dev/null || { echo "Required Python executable unavailable: ' + binary + '" >&2; exit 52; }')
        if pv:
            expected = ','.join(str(x) for x in (pv + (0,) * (3 - len(pv))))
            code = 'import sys; required=(' + expected + '); current=sys.version_info[:3]; print("Python", sys.version); assert current >= required, "Python version too old"'
            lines += shell_run(shlex.quote(binary) + ' -c ' + shlex.quote(code))
        if modules['python_packages']:
            lines += shell_run(shlex.quote(binary) + ' -m venv /opt/component-builder/python-venv')
            lines += ['ENV VIRTUAL_ENV=/opt/component-builder/python-venv', 'ENV PATH="/opt/component-builder/python-venv/bin:${PATH}"', '']
            cmd = '/opt/component-builder/python-venv/bin/python -m pip install --no-cache-dir ' + ' '.join(shlex.quote(x) for x in modules['python_packages'])
            lines += shell_run(cmd)
            lines += shell_run('/opt/component-builder/python-venv/bin/python -m pip check')
    if plan['r_required']:
        lines += shell_run('command -v Rscript >/dev/null || { echo "Rscript unavailable" >&2; exit 53; }')
        if rv:
            target = '.'.join(map(str, rv))
            code = 'stopifnot(getRversion() >= package_version(' + json.dumps(target) + '))'
            lines += shell_run('Rscript --vanilla -e ' + shlex.quote(code))
        if modules['cran_packages']:
            package_array = 'c(' + ','.join(json.dumps(x) for x in modules['cran_packages']) + ')'
            code = 'pkgs <- ' + package_array + '; missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly=TRUE)]; if(length(missing)) install.packages(missing, repos="https://cloud.r-project.org"); stopifnot(all(vapply(pkgs, requireNamespace, logical(1), quietly=TRUE)))'
            lines += shell_run('Rscript --vanilla -e ' + shlex.quote(code))
        if modules['bioc_packages']:
            package_array = 'c(' + ','.join(json.dumps(x) for x in modules['bioc_packages']) + ')'
            code = 'pkgs <- ' + package_array + '; missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly=TRUE)]; if(length(missing)) { if(!requireNamespace("BiocManager", quietly=TRUE)) install.packages("BiocManager", repos="https://cloud.r-project.org"); BiocManager::install(missing, ask=FALSE, update=FALSE) }; stopifnot(all(vapply(pkgs, requireNamespace, logical(1), quietly=TRUE)))'
            lines += shell_run('Rscript --vanilla -e ' + shlex.quote(code))
    if plan['perl_required']:
        lines += shell_run('command -v perl >/dev/null || { echo "Perl unavailable" >&2; exit 54; }')
        if lv:
            target = 'v' + '.'.join(map(str, lv)) if len(lv) > 1 else str(lv[0])
            code = 'use version; die "Perl version too old" unless version->parse($^V) >= version->parse(' + json.dumps(target) + ');'
            lines += shell_run('perl -e ' + shlex.quote(code))
        if modules['cpan_modules']:
            lines += shell_run('command -v cpanm >/dev/null || { echo "cpanm unavailable: install cpanminus or supply a custom installer" >&2; exit 55; }')
            for module in modules['cpan_modules']:
                if not re.fullmatch(r'[A-Za-z_][\w]*(?:::[A-Za-z_][\w]*)*', module):
                    raise ValueError('Invalid Perl module: ' + module)
                lines += shell_run('perl -M' + module + ' -e 1 >/dev/null 2>&1 || cpanm --notest ' + shlex.quote(module))
                lines += shell_run('perl -M' + module + ' -e 1')
    return lines


def verification_lines(plan):
    return shell_run(plan['config']['verify_commands'])


def pre_lines(plan):
    return shell_run(plan['config']['pre_commands'])


def post_lines(plan):
    return shell_run(plan['config']['post_commands'])


def custom_script_lines(script, context, name):
    if not str(script or '').strip():
        return []
    filename = 'custom_' + name + '.sh'
    (context / filename).write_text(str(script).replace('\r\n', '\n').rstrip() + '\n', encoding='utf-8')
    destination = '/tmp/component-builder-' + name + '.sh'
    return ['COPY ' + json.dumps([filename, destination]), 'RUN /bin/sh -e ' + shlex.quote(destination) + ' && rm -f ' + shlex.quote(destination), '']
