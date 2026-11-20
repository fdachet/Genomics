import csv
import datetime
import os
from pathlib import Path
import json
import queue
import re
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


DEFAULT_THRESHOLDS = {'memory': 80, 'java_heap': 85, 'open_files': 75, 'disk': 90}


LINUX_PROBE = r'''
printf 'SHELL_FD\t%s\t%s\n' "$(ulimit -Sn 2>/dev/null)" "$(ulimit -Hn 2>/dev/null)"
if [ -r /proc/sys/fs/file-nr ]; then
    printf 'KERNEL_FD\t%s\n' "$(cat /proc/sys/fs/file-nr)"
fi
if [ -r /proc/meminfo ]; then
    while read -r key value extra; do
        case "$key" in
            MemTotal:|MemAvailable:|SwapTotal:|SwapFree:)
                printf 'MEM\t%s\t%s\n' "${key%:}" "$value" ;;
        esac
    done < /proc/meminfo
fi
for item in memory.peak:/sys/fs/cgroup/memory.peak memory.max:/sys/fs/cgroup/memory.max memory.current:/sys/fs/cgroup/memory.current memory.swap.max:/sys/fs/cgroup/memory.swap.max memory.swap.current:/sys/fs/cgroup/memory.swap.current pids.max:/sys/fs/cgroup/pids.max pids.current:/sys/fs/cgroup/pids.current memory.legacy.max:/sys/fs/cgroup/memory/memory.limit_in_bytes memory.legacy.current:/sys/fs/cgroup/memory/memory.usage_in_bytes pids.legacy.max:/sys/fs/cgroup/pids/pids.max pids.legacy.current:/sys/fs/cgroup/pids/pids.current cpu.max:/sys/fs/cgroup/cpu.max; do
    key=${item%%:*}
    file=${item#*:}
    if [ -r "$file" ]; then
        value=$(cat "$file" 2>/dev/null)
        printf 'CGROUP\t%s\t%s\n' "$key" "$value"
    fi
done
if [ -r /sys/fs/cgroup/memory.stat ]; then
    while read -r field value; do
        case "$field" in
            anon|file|slab|kernel|sock|shmem|file_mapped|pgmajfault)
                printf 'CGROUP	memory.stat.%s	%s\n' "$field" "$value" ;;
        esac
    done < /sys/fs/cgroup/memory.stat
fi
for item in memory.events:/sys/fs/cgroup/memory.events cpu.stat:/sys/fs/cgroup/cpu.stat; do
    key=${item%%:*}
    file=${item#*:}
    if [ -r "$file" ]; then
        while read -r field value; do
            printf 'EVENT\t%s.%s\t%s\n' "$key" "$field" "$value"
        done < "$file"
    fi
done
for kind in cpu memory io; do
    file="/sys/fs/cgroup/$kind.pressure"
    scope=container
    if [ ! -r "$file" ]; then
        file="/proc/pressure/$kind"
        scope=vm
    fi
    if [ -r "$file" ]; then
        while IFS= read -r line; do
            printf 'PRESSURE\t%s.%s\t%s\n' "$scope" "$kind" "$line"
        done < "$file"
    fi
done
if command -v getconf >/dev/null 2>&1; then
    printf 'CPUS\t%s\n' "$(getconf _NPROCESSORS_ONLN 2>/dev/null)"
    printf 'TICKS\t%s\n' "$(getconf CLK_TCK 2>/dev/null)"
fi
for location in "$@"; do
    [ -e "$location" ] || continue
    if command -v df >/dev/null 2>&1; then
        line=$(df -Pk "$location" 2>/dev/null | tail -n 1)
        [ -n "$line" ] && printf 'DISK\t%s\t%s\n' "$location" "$line"
        line=$(df -Pi "$location" 2>/dev/null | tail -n 1)
        [ -n "$line" ] && printf 'INODE\t%s\t%s\n' "$location" "$line"
    fi
done
process_count=0
for directory in /proc/[0-9]*; do
    [ -r "$directory/status" ] || continue
    process_count=$((process_count+1))
    [ "$process_count" -le 350 ] || continue
    pid=${directory##*/}
    name=''
    rss=0
    vm=0
    swap=0
    threads=0
    state=?
    while IFS= read -r line; do
        label=${line%%:*}
        value=${line#*:}
        case "$label" in
            Name) name=$value ;;
            State) set -- $value; state=${1:-?} ;;
            VmRSS) set -- $value; rss=${1:-0} ;;
            VmSwap) set -- $value; swap=${1:-0} ;;
            VmSize) set -- $value; vm=${1:-0} ;;
            Threads) set -- $value; threads=${1:-0} ;;
        esac
    done < "$directory/status"
    soft='?'
    hard='?'
    if [ -r "$directory/limits" ]; then
        while IFS= read -r line; do
            case "$line" in
                'Max open files'*) set -- $line; soft=${4:-?}; hard=${5:-?} ;;
            esac
        done < "$directory/limits"
    fi
    fds='?'
    if [ -d "$directory/fd" ]; then
        fds=$(ls -1A "$directory/fd" 2>/dev/null | wc -l)
        set -- $fds; fds=${1:-0}
    fi
    command_line=''
    if [ -r "$directory/cmdline" ] && command -v tr >/dev/null 2>&1; then
        command_line=$(tr '\000\011\012\015' '    ' < "$directory/cmdline" 2>/dev/null | cut -c 1-450)
    fi
    [ -n "$command_line" ] || command_line=$name
    ticks='?'
    start_ticks='?'
    if [ -r "$directory/stat" ]; then
        stat_text=$(cat "$directory/stat" 2>/dev/null)
        case "$stat_text" in
            *') '*)
                stat_tail=${stat_text#*') '}
                set -- $stat_tail
                if [ $# -ge 13 ]; then
                    ticks=$((${12}+${13}))
                fi
                if [ $# -ge 20 ]; then
                    start_ticks=${20}
                fi ;;
        esac
    fi
    hwm=0
    while IFS= read -r line; do
        case "$line" in
            VmHWM:*) set -- $line; hwm=${2:-0}; break ;;
        esac
    done < "$directory/status"
    proc_read='?'
    proc_write='?'
    if [ -r "$directory/io" ]; then
        while read -r field value; do
            case "$field" in
                read_bytes:) proc_read=$value ;;
                write_bytes:) proc_write=$value ;;
            esac
        done < "$directory/io"
    fi
    printf 'PROC_EXTRA\t%s\t%s\t%s\t%s\n' "$pid" "$hwm" "$proc_read" "$proc_write"
    name=$(printf '%s' "$name" | tr '\011\012\015' '   ')
    printf 'PROC\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$pid" "$name" "$rss" "$swap" "$vm" "$threads" "$fds" "$soft" "$hard" "$ticks" "$state" "$start_ticks" "$command_line"
done
printf 'PROC_COUNT\t%s\n' "$process_count"
if command -v timeout >/dev/null 2>&1; then
    java_tool=''
    if command -v jstat >/dev/null 2>&1; then
        java_tool=$(command -v jstat)
    fi
    jcmd_tool=''
    if command -v jcmd >/dev/null 2>&1; then
        jcmd_tool=$(command -v jcmd)
    fi
    java_count=0
    for directory in /proc/[0-9]*; do
        [ -r "$directory/comm" ] || continue
        read -r comm < "$directory/comm"
        case "$comm" in
            java|java.exe) ;;
            *) continue ;;
        esac
        java_count=$((java_count+1))
        [ "$java_count" -le 8 ] || continue
        pid=${directory##*/}
        if [ -n "$java_tool" ]; then
            measured=$(timeout 2 "$java_tool" -gc "$pid" 1 2>/dev/null)
            if [ -n "$measured" ]; then
                headline=$(printf '%s\n' "$measured" | sed -n '1p')
                numbers=$(printf '%s\n' "$measured" | sed -n '2p')
                if [ -n "$numbers" ]; then
                    printf 'JSTAT\t%s\t%s\t%s\n' "$pid" "$headline" "$numbers"
                else
                    printf 'JSTAT_ERROR\t%s\tjstat returned incomplete data\n' "$pid"
                fi
            else
                printf 'JSTAT_ERROR\t%s\tjstat unavailable for this process (permissions or unsupported JVM)\n' "$pid"
            fi
        else
            printf 'JSTAT_ERROR\t%s\tjstat is not installed in this container\n' "$pid"
        fi
        if [ -n "$jcmd_tool" ]; then
            flags=$(timeout 2 "$jcmd_tool" "$pid" VM.flags 2>/dev/null)
            if [ -n "$flags" ]; then
                flags=$(printf '%s' "$flags" | tr '\011\012\015' '   ' | cut -c 1-5000)
                printf 'JCMD\t%s\t%s\n' "$pid" "$flags"
            fi
        fi
    done
    if [ "$java_count" -gt 8 ]; then
        printf 'JAVA_PROBE_STATUS\tOnly first 8 Java processes were probed to limit monitoring overhead\n'
    fi
else
    printf 'JAVA_PROBE_STATUS\tJVM monitoring needs the timeout utility; metrics unavailable\n'
fi
printf 'DONE\t1\n'
'''


STOP_PROCESS_PROBE = r'''
set -f
signal=$1
shift
case "$signal" in
    TERM|KILL) ;;
    *) printf 'ERROR\tInvalid signal\n'; exit 2 ;;
esac
for entry in "$@"; do
    pid=${entry%%:*}
    expected_start=${entry#*:}
    case "$pid" in
        ''|*[!0-9]*) printf 'INVALID\t%s\tInvalid PID\n' "$pid"; continue ;;
    esac
    case "$expected_start" in
        ''|*[!0-9]*) printf 'INVALID\t%s\tMissing process identity\n' "$pid"; continue ;;
    esac
    if [ "$pid" -le 1 ]; then
        printf 'PROTECTED\t%s\tPID 1 and nonpositive PIDs cannot be terminated\n' "$pid"
        continue
    fi
    if [ ! -r "/proc/$pid/stat" ]; then
        printf 'GONE\t%s\tProcess is no longer running\n' "$pid"
        continue
    fi
    stat_text=$(cat "/proc/$pid/stat" 2>/dev/null) || {
        printf 'GONE\t%s\tProcess disappeared before identity verification\n' "$pid"
        continue
    }
    case "$stat_text" in
        *') '*) stat_tail=${stat_text#*') '} ;;
        *) printf 'ERROR\t%s\tCannot parse process identity\n' "$pid"; continue ;;
    esac
    set -- $stat_tail
    if [ "$#" -lt 20 ]; then
        printf 'ERROR\t%s\tMissing start time from process metadata\n' "$pid"
        continue
    fi
    if [ "${20}" != "$expected_start" ]; then
        printf 'REUSED\t%s\tPID now refers to a different process; no signal sent\n' "$pid"
        continue
    fi
    proc_name=''
    if [ -r "/proc/$pid/comm" ]; then
        read -r proc_name < "/proc/$pid/comm"
    fi
    proc_command=''
    if [ -r "/proc/$pid/cmdline" ] && command -v tr >/dev/null 2>&1; then
        proc_command=$(tr '\000' ' ' < "/proc/$pid/cmdline" 2>/dev/null)
    fi
    case "$proc_name:$proc_command" in
        sleep:'sleep 3600'*|sh:'/bin/sh -s -- / /tmp /dev/shm'*)
            printf 'PROTECTED\t%s\tContainer keep-alive or monitoring process cannot be terminated\n' "$pid"
            continue ;;
    esac
    if [ "$1" = 'Z' ] || [ "$1" = 'X' ]; then
        printf 'GONE\t%s\tProcess has already exited\n' "$pid"
        continue
    fi
    if kill -s "$signal" "$pid" 2>/dev/null; then
        printf 'SIGNALED\t%s\tSIG%s delivered\n' "$pid" "$signal"
    else
        printf 'FAILED\t%s\tSignal failed (permission denied or process exited)\n' "$pid"
    fi
done
printf 'DONE\t1\n'
'''


def _num(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _bytes(value):
    if value is None:
        return 'unknown'
    amount = float(value)
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if abs(amount) < 1024 or unit == 'TiB':
            return ('%.0f ' if unit == 'B' else '%.2f ') % amount + unit
        amount /= 1024


def _parse_size(value):
    match = re.match(r'^\s*([\d.]+)\s*([KMGT]?i?B|[KMGT]?B|B)\s*$', str(value), re.I)
    if not match:
        return None
    factors = {'B': 1, 'KB': 1000, 'MB': 1000 ** 2, 'GB': 1000 ** 3, 'TB': 1000 ** 4,
               'KIB': 1024, 'MIB': 1024 ** 2, 'GIB': 1024 ** 3, 'TIB': 1024 ** 4}
    return int(float(match.group(1)) * factors[match.group(2).upper()])


def _percent(used, total):
    return 100 * used / total if used is not None and total not in (None, 0) else None


def _java_heap(command):
    matches = re.findall(r'(?<!\S)-Xmx(\d+(?:\.\d+)?)([kKmMgG]?)\b', command)
    if matches:
        n, unit = matches[-1]
        return int(float(n) * {'': 1, 'k': 1024, 'm': 1024 ** 2, 'g': 1024 ** 3}[unit.lower()])
    matches = re.findall(r'(?<!\S)-XX:MaxHeapSize=(\d+)(?:\s|$)', command)
    return int(matches[-1]) if matches else None


def _run(args, timeout=30, script=None):
    payload = None
    if script is not None:
        payload = script.replace('\r\n', '\n').replace('\r', '\n').encode('utf-8')
    result = subprocess.run(args, input=payload, capture_output=True,
                            timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    stdout = result.stdout.decode('utf-8', errors='replace')
    stderr = result.stderr.decode('utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError('Docker command failed:\n' + subprocess.list2cmdline(args) +
                           '\n' + (stderr or stdout)[-1600:])
    return stdout


def _df(text):
    tokens = text.split()
    if len(tokens) < 6:
        return None
    try:
        return {'filesystem': tokens[0], 'total': int(tokens[1]), 'used': int(tokens[2]),
                'available': int(tokens[3]), 'pct': float(tokens[4].rstrip('%')),
                'mount': ' '.join(tokens[5:])}
    except ValueError:
        return None


def process_role(p):
    pid = p.get('pid')
    name = (p.get('name') or '').strip()
    cmd = (p.get('command') or '').strip()
    if pid == 1:
        return 'Container main / protected'
    if name == 'sleep' and cmd.startswith('sleep 3600'):
        return 'Keep-alive / protected'
    if name in ('sh', 'dash', 'bash') and ('/bin/sh -s -- / /tmp /dev/shm' in cmd or
                                        '/bin/sh -s -- TERM' in cmd or
                                        '/bin/sh -s -- KILL' in cmd):
        return 'Monitor / protected'
    if name in ('java', 'java.exe'):
        return 'Java job'
    if name in ('bash', 'sh', 'dash'):
        return 'Interactive shell'
    return 'Other process'


def is_infrastructure(p):
    return p.get('role') in ('Container main / protected', 'Keep-alive / protected',
                             'Monitor / protected', 'Interactive shell')


def parse_probe(output):
    result = {'shell_fd': [], 'kernel_fd': [], 'meminfo': {}, 'cgroup': {}, 'events': {},
              'pressure': {}, 'disks': {}, 'inodes': {}, 'processes': [], 'cpu_count': None,
              'clock_ticks': None, 'process_count': None, 'java_probe_status': None}
    complete = False
    extras = {}
    jstats = {}
    jerrors = {}
    jflags = {}
    for line in output.splitlines():
        a = line.split('\t')
        kind = a[0]
        if kind == 'DONE':
            complete = True
        elif kind == 'SHELL_FD' and len(a) >= 3:
            result['shell_fd'] = a[1:3]
        elif kind == 'KERNEL_FD' and len(a) >= 4:
            result['kernel_fd'] = [_num(x) for x in a[1:4]]
        elif kind == 'MEM' and len(a) >= 3:
            result['meminfo'][a[1]] = _num(a[2])
        elif kind == 'CGROUP' and len(a) >= 3:
            result['cgroup'][a[1]] = a[2]
        elif kind == 'EVENT' and len(a) >= 3:
            result['events'][a[1]] = _num(a[2])
        elif kind == 'PRESSURE' and len(a) >= 3:
            match = re.search(r'avg10=([\d.]+)', a[2])
            result['pressure'][a[1] + '.' + a[2].split()[0]] = float(match.group(1)) if match else None
        elif kind in ('DISK', 'INODE') and len(a) >= 3:
            data = _df(a[2])
            if data is not None:
                result['disks' if kind == 'DISK' else 'inodes'][a[1]] = data
        elif kind == 'CPUS' and len(a) >= 2:
            result['cpu_count'] = _num(a[1])
        elif kind == 'TICKS' and len(a) >= 2:
            result['clock_ticks'] = _num(a[1])
        elif kind == 'PROC_EXTRA' and len(a) >= 5:
            pid = _num(a[1])
            if pid is not None:
                extras[pid] = {'rss_peak_kib': _num(a[2]), 'read_bytes': _num(a[3]),
                               'write_bytes': _num(a[4])}
        elif kind == 'JSTAT' and len(a) >= 4:
            pid = _num(a[1])
            if pid is not None:
                labels, values = a[2].split(), a[3].split()
                if len(labels) == len(values) and labels:
                    try:
                        vals = dict(zip(labels, (float(x) for x in values)))
                        used = sum(vals[x] for x in ('S0U', 'S1U', 'EU', 'OU'))
                        capacity = sum(vals[x] for x in ('S0C', 'S1C', 'EC', 'OC'))
                        jstats[pid] = {'heap_used': int(used * 1024), 'heap_committed': int(capacity * 1024),
                                       'gc_count': vals.get('YGC', 0) + vals.get('FGC', 0) + vals.get('CGC', 0),
                                       'gc_seconds': vals.get('GCT'), 'method': 'jstat -gc'}
                    except (KeyError, ValueError, OverflowError):
                        jerrors[pid] = 'Unrecognized jstat output'
                else:
                    jerrors[pid] = 'Unrecognized jstat output'
        elif kind == 'JSTAT_ERROR' and len(a) >= 3:
            pid = _num(a[1])
            if pid is not None:
                jerrors[pid] = a[2]
        elif kind == 'JCMD' and len(a) >= 3:
            pid = _num(a[1])
            if pid is not None:
                match = re.search(r'(?:^|\s)-XX:MaxHeapSize=(\d+)', a[2])
                if match:
                    jflags[pid] = int(match.group(1))
        elif kind == 'JAVA_PROBE_STATUS' and len(a) >= 2:
            result['java_probe_status'] = a[1]
        elif kind == 'PROC_COUNT' and len(a) >= 2:
            result['process_count'] = _num(a[1])
        elif kind == 'PROC' and len(a) >= 12:
            cmd = '\t'.join(a[13:]) if len(a) >= 14 else '\t'.join(a[11:])
            proc = {'pid': _num(a[1]), 'name': a[2].strip(), 'rss_kib': _num(a[3]),
                    'swap_kib': _num(a[4]), 'virtual_kib': _num(a[5]), 'threads': _num(a[6]),
                    'fds': _num(a[7]), 'fd_soft': _num(a[8]), 'fd_hard': _num(a[9]),
                    'ticks': _num(a[10]), 'state': a[11].strip() if len(a) >= 14 else '?',
                    'start_ticks': _num(a[12]) if len(a) >= 14 else None,
                    'command': cmd, 'cpu_percent': None}
            proc['heap_max'] = _java_heap(cmd) if proc['name'] in ('java', 'java.exe') else None
            result['processes'].append(proc)
    for proc in result['processes']:
        pid = proc['pid']
        proc.update(extras.get(pid) or {})
        proc['role'] = process_role(proc)
        if proc['name'] in ('java', 'java.exe'):
            proc.update(jstats.get(pid) or {})
            if pid in jflags:
                proc['heap_max'] = jflags[pid]
                proc['heap_max_source'] = 'jcmd VM.flags'
            elif proc['heap_max'] is not None:
                proc['heap_max_source'] = 'command-line -Xmx'
            else:
                proc['heap_max_source'] = 'unknown'
            proc['heap_status'] = (jerrors.get(pid) or ('measured' if pid in jstats else
                                    result['java_probe_status'] or 'JVM heap telemetry unavailable'))
    if not complete:
        raise RuntimeError('Linux resource probe did not complete. Confirm /bin/sh is present in the container.')
    return result


def collect_snapshot(name):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name or ''):
        raise ValueError('Invalid container name.')
    info = json.loads(_run(['docker', 'container', 'inspect', name], timeout=20))[0]
    state = info.get('State') or {}
    snapshot = {'name': name, 'container_id': info.get('Id'), 'time': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                'state': state, 'host': info.get('HostConfig') or {},
                'image': (info.get('Config') or {}).get('Image'), 'restart_count': info.get('RestartCount', 0),
                'mounts': info.get('Mounts') or [], 'stats': {}, 'linux': {}}
    if not state.get('Running'):
        return snapshot
    stats = json.loads(_run(['docker', 'stats', '--no-stream', '--format', '{{json .}}', name], timeout=30))
    memory = str(stats.get('MemUsage') or '').split('/', 1)
    stats['memory_used'] = _parse_size(memory[0]) if memory else None
    stats['memory_limit'] = _parse_size(memory[1]) if len(memory) > 1 else None
    try:
        stats['cpu_value'] = float(str(stats.get('CPUPerc', '')).rstrip('%'))
    except ValueError:
        stats['cpu_value'] = None
    snapshot['stats'] = stats
    paths = ['/', '/tmp', '/dev/shm', '/data']
    wd = (info.get('Config') or {}).get('WorkingDir')
    if wd and wd.startswith('/') and wd not in paths:
        paths.append(wd)
    for mount in snapshot['mounts']:
        path = mount.get('Destination')
        if path and path.startswith('/') and path not in paths and len(paths) < 18:
            paths.append(path)
    snapshot['linux'] = parse_probe(_run(['docker', 'exec', '-i', name, '/bin/sh', '-s', '--'] + paths,
                                         timeout=55, script=LINUX_PROBE))
    return snapshot


def stop_selected_processes(name, container_id, selections, signal):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name or ''):
        raise ValueError('Invalid container name.')
    if signal not in ('TERM', 'KILL'):
        raise ValueError('Unsupported signal.')
    if not container_id or not re.fullmatch(r'[a-fA-F0-9]{12,64}', container_id):
        raise ValueError('Container identity is unavailable. Refresh the monitor.')
    if not selections or len(selections) > 100:
        raise ValueError('Select between 1 and 100 processes.')
    entries = []
    seen = set()
    for item in selections:
        pid = item.get('pid')
        started = item.get('start_ticks')
        if type(pid) is not int or type(started) is not int or pid <= 1 or started <= 0 or is_infrastructure(item) and item.get('role') != 'Interactive shell':
            raise ValueError('Invalid or protected process selected. Refresh the process list.')
        if pid in seen:
            raise ValueError('Duplicate process PID in selection.')
        seen.add(pid)
        entries.append('%d:%d' % (pid, started))
    info = json.loads(_run(['docker', 'container', 'inspect', name], timeout=20))[0]
    if info.get('Id') != container_id:
        raise RuntimeError('The container has been replaced since the snapshot; refresh before terminating processes.')
    if not (info.get('State') or {}).get('Running'):
        raise RuntimeError('The container is no longer running.')
    mode = str((info.get('HostConfig') or {}).get('PidMode') or '')
    if mode not in ('', 'private'):
        raise RuntimeError('Termination is disabled for containers with shared PID namespaces (%s).' % mode)
    command = ['docker', 'exec', '-i', '--user', '0', container_id,
               '/bin/sh', '-s', '--', signal] + entries
    output = _run(command, timeout=30, script=STOP_PROCESS_PROBE)
    statuses = []
    done = False
    for row in output.splitlines():
        fields = row.split('\t', 2)
        if fields[0] == 'DONE':
            done = True
        elif len(fields) == 3 and fields[0] in (
                'SIGNALED', 'FAILED', 'GONE', 'REUSED', 'PROTECTED', 'INVALID', 'ERROR'):
            statuses.append({'status': fields[0], 'pid': fields[1], 'message': fields[2]})
    if not done or len(statuses) != len(selections):
        raise RuntimeError('Incomplete termination response; refresh to verify the current process state.\n' + output[-1600:])
    return statuses


def _effective_limit(data):
    cg = (data.get('linux') or {}).get('cgroup') or {}
    for key in ('memory.max', 'memory.legacy.max'):
        value = _num(cg.get(key))
        if value is not None and 0 < value < 1 << 60:
            return value
    return (data.get('stats') or {}).get('memory_limit')


def _capacity(data):
    linux = data.get('linux') or {}
    host = data.get('host') or {}
    available = linux.get('cpu_count')
    constraints = [float(available)] if available else []
    quota = str((linux.get('cgroup') or {}).get('cpu.max') or '').split()
    if len(quota) == 2 and quota[0] != 'max':
        q, period = _num(quota[0]), _num(quota[1])
        if q and period:
            constraints.append(q / period)
    nanocpus = _num(host.get('NanoCpus'))
    if nanocpus and nanocpus > 0:
        constraints.append(nanocpus / 1e9)
    q, period = _num(host.get('CpuQuota')), _num(host.get('CpuPeriod'))
    if q and period and q > 0:
        constraints.append(q / period)
    return min(constraints) if constraints else None


def warnings_for(data, previous=None, thresholds=None):
    limits = dict(DEFAULT_THRESHOLDS)
    if isinstance(thresholds, dict):
        for k in limits:
            v = _num(thresholds.get(k))
            if v is not None and 30 <= v <= 99:
                limits[k] = v
    alerts = []
    state = data.get('state') or {}
    if not state.get('Running'):
        alerts.append(('CRITICAL', 'Container stopped: %s, exit code %s.' %
                       (state.get('Status'), state.get('ExitCode'))))
        if state.get('OOMKilled'):
            alerts.append(('CRITICAL', 'Docker reports the container was killed by out-of-memory.'))
        return alerts
    linux = data.get('linux') or {}
    stats = data.get('stats') or {}
    mem = linux.get('meminfo') or {}
    cg = linux.get('cgroup') or {}
    events = linux.get('events') or {}
    used = stats.get('memory_used')
    limit = _effective_limit(data)
    ratio = _percent(used, limit)
    if ratio is not None and ratio >= limits['memory']:
        alerts.append(('CRITICAL' if ratio >= min(98, max(92, limits['memory'] + 8)) else 'WARNING',
                       'Docker memory is %.1f%% of its reported limit.' % ratio))
    hard = _num(cg.get('memory.max') or cg.get('memory.legacy.max'))
    charged = _num(cg.get('memory.current') or cg.get('memory.legacy.current'))
    ratio = _percent(charged, hard) if hard and hard < 1 << 60 else None
    if ratio is not None and ratio >= limits['memory']:
        alerts.append(('CRITICAL' if ratio >= min(98, max(92, limits['memory'] + 8)) else 'WARNING',
                       'Cgroup memory including filesystem cache reached %.1f%% of its hard limit.' % ratio))
    vm_total, vm_available = mem.get('MemTotal'), mem.get('MemAvailable')
    if vm_total and vm_available is not None:
        ratio = 100 * (vm_total - vm_available) / vm_total
        if ratio >= 90:
            alerts.append(('CRITICAL' if ratio >= 96 else 'WARNING',
                           'Linux VM physical memory is %.1f%% occupied.' % ratio))
    for key in ('memory.events.oom_kill', 'memory.events.oom'):
        current = events.get(key)
        before = ((previous or {}).get('linux') or {}).get('events', {}).get(key)
        if current is not None and before is not None and current > before:
            alerts.append(('CRITICAL', '%s increased from %d to %d while monitoring.' % (key, before, current)))
        elif key.endswith('oom_kill') and current:
            alerts.append(('WARNING', 'Cgroup recorded %d OOM kills since this container started.' % current))
    pid_used = _num(cg.get('pids.current') or cg.get('pids.legacy.current'))
    pid_max = _num(cg.get('pids.max') or cg.get('pids.legacy.max'))
    ratio = _percent(pid_used, pid_max)
    if ratio is not None and ratio >= limits['memory']:
        alerts.append(('CRITICAL' if ratio >= 95 else 'WARNING',
                       'PID/thread count is %.1f%% of its maximum.' % ratio))
    for proc in linux.get('processes') or []:
        heap_percent = _percent(proc.get('heap_used'), proc.get('heap_max'))
        if heap_percent is not None and heap_percent >= limits['java_heap']:
            alerts.append(('CRITICAL' if heap_percent >= 96 else 'WARNING',
                           'Java PID %s heap %s / %s (%.1f%%), risk of Java heap exhaustion.' %
                           (proc['pid'], _bytes(proc['heap_used']), _bytes(proc['heap_max']), heap_percent)))
        if (proc.get('fd_growth_per_min') or 0) > 120 and (proc.get('fds') or 0) >= 100:
            alerts.append(('WARNING', 'PID %s (%s) open file descriptors increased at %.0f/min; monitor for a leak.' %
                           (proc['pid'], proc['name'], proc['fd_growth_per_min'])))
        if (proc.get('gc_rate') or 0) >= 30 and heap_percent is not None and heap_percent >= 65:
            alerts.append(('WARNING', 'Java PID %s has %.1f GCs/min with %.1f%% of maximum heap occupied.' %
                           (proc['pid'], proc['gc_rate'], heap_percent)))
        ratio = _percent(proc.get('fds'), proc.get('fd_soft'))
        if ratio is not None and ratio >= limits['open_files']:
            alerts.append(('CRITICAL' if ratio >= 95 else 'WARNING',
                           'PID %s (%s) has %s/%s open file descriptors (%.1f%%).' %
                           (proc['pid'], proc['name'], proc['fds'], proc['fd_soft'], ratio)))
    kernel = linux.get('kernel_fd') or []
    if len(kernel) == 3 and kernel[0] is not None:
        ratio = _percent(max(0, kernel[0] - (kernel[1] or 0)), kernel[2])
        if ratio is not None and ratio >= 80:
            alerts.append(('CRITICAL' if ratio >= 95 else 'WARNING',
                           'System-wide open files reached %.1f%% of the kernel maximum.' % ratio))
    for group, label in (('disks', 'Disk capacity'), ('inodes', 'Available file/inode capacity')):
        for path, item in (linux.get(group) or {}).items():
            if item['pct'] >= limits['disk']:
                alerts.append(('CRITICAL' if item['pct'] >= 98 else 'WARNING',
                               '%s at %s is %.1f%% used.' % (label, path, item['pct'])))
    swap_used = _num(cg.get('memory.swap.current'))
    if swap_used is not None and swap_used > (1 << 30):
        alerts.append(('WARNING', 'Container is using over 1 GiB of swap, indicating memory pressure.'))
    for key, stall in (linux.get('pressure') or {}).items():
        if stall is not None and (key.endswith('memory.some') and stall >= 10 or
                                  key.endswith('io.some') and stall >= 25):
            alerts.append(('WARNING', '%s stall time reached %.1f%% over 10 seconds.' % (key, stall)))
    throttled = events.get('cpu.stat.nr_throttled')
    earlier = ((previous or {}).get('linux') or {}).get('events', {}).get('cpu.stat.nr_throttled')
    if throttled is not None and earlier is not None and throttled > earlier:
        alerts.append(('WARNING', 'CPU throttling has increased; CPU throttling normally slows jobs rather than killing them.'))
    capacity = _capacity(data)
    cpu = stats.get('cpu_value')
    if capacity and cpu is not None and cpu >= capacity * 90:
        alerts.append(('WARNING', 'CPU usage is near all %.1f available logical CPUs; expect slowdown, not automatic termination.' % capacity))
    jvms = [p for p in linux.get('processes') or [] if p['name'] in ('java', 'java.exe')]
    if jvms and all(p['heap_max'] is not None for p in jvms) and vm_total:
        total = sum(p['heap_max'] for p in jvms)
        if total >= 0.9 * vm_total * 1024:
            alerts.append(('WARNING', 'Combined Java -Xmx values total %s, nearly all available VM RAM before native memory.' % _bytes(total)))
    if linux.get('process_count', 0) > len(linux.get('processes') or []):
        alerts.append(('WARNING', 'More than 350 processes detected; detailed table is limited to 350 processes.'))
    if not alerts:
        alerts.append(('OK', 'No current resource-limit warning. Java heap exhaustion and application errors remain possible.'))
    return alerts


def make_report(data, previous=None, peak=None, thresholds=None):
    linux = data.get('linux') or {}
    state = data.get('state') or {}
    stats = data.get('stats') or {}
    cg = linux.get('cgroup') or {}
    mem = linux.get('meminfo') or {}
    processes = linux.get('processes') or []
    lines = ['CONTAINER RESOURCE DIAGNOSTICS', 'Container: ' + data['name'],
             'Timestamp: ' + data['time'], 'Image: ' + str(data.get('image')),
             'Status: ' + str(state.get('Status')), 'Exit code: ' + str(state.get('ExitCode')),
             'Docker OOMKilled: ' + str(state.get('OOMKilled')),
             'Restart count: ' + str(data.get('restart_count', 0)), '', 'WARNINGS / ASSESSMENT']
    lines += ['[%s] %s' % item for item in warnings_for(data, previous, thresholds)]
    if not state.get('Running'):
        return '\n'.join(lines) + '\n'
    used, limit = stats.get('memory_used'), _effective_limit(data)
    ratio = _percent(used, limit)
    physical = (mem.get('MemTotal') or 0) * 1024
    free = (mem.get('MemAvailable') or 0) * 1024
    total_swap = (mem.get('SwapTotal') or 0) * 1024
    free_swap = (mem.get('SwapFree') or 0) * 1024
    kernel = linux.get('kernel_fd') or []
    jvms = [p for p in processes if p['name'] in ('java', 'java.exe')]
    explicit = [p['heap_max'] for p in jvms if p['heap_max'] is not None]
    lines += ['', 'MEMORY / CPU',
              'Docker RAM used / available: %s / %s%s' %
              (_bytes(used), _bytes(limit), (' (%.1f%%)' % ratio) if ratio is not None else ''),
              'Highest Docker RAM reading in this monitor: ' + _bytes(peak),
              'Cgroup kernel-recorded memory peak (if available): ' +
              _bytes(_num(cg.get('memory.peak'))),
              'Docker explicitly configured memory cap: ' + str(data['host'].get('Memory') or 'none'),
              'Cgroup memory charged including cache: ' + _bytes(_num(cg.get('memory.current') or cg.get('memory.legacy.current'))),
              'Cgroup hard memory limit: ' + str(cg.get('memory.max', cg.get('memory.legacy.max', 'unknown'))),
              'Linux VM physical RAM: ' + _bytes(physical),
              'Linux VM available RAM: ' + _bytes(free),
              'Linux VM swap used / total: %s / %s' % (_bytes(total_swap - free_swap), _bytes(total_swap)),
              'Cgroup swap used / maximum: %s / %s' % (_bytes(_num(cg.get('memory.swap.current'))), cg.get('memory.swap.max', 'unknown')),
              'Docker CPU consumption (100% means one CPU): ' + str(stats.get('CPUPerc', 'unknown')),
              'Linux logical CPUs: ' + str(linux.get('cpu_count')),
              'Estimated CPU capacity: ' + str(_capacity(data)),
              'CPU quota: ' + str(cg.get('cpu.max', 'not reported')),
              'Docker block I/O: ' + str(stats.get('BlockIO', 'unknown')),
              '', 'MEMORY/OOM/CPU EVENTS']
    lines += [name + ': ' + str(value) for name, value in sorted((linux.get('events') or {}).items())]
    lines += [name + ' avg10: ' + str(value) + '%' for name, value in sorted((linux.get('pressure') or {}).items())]
    pid_cur = _num(cg.get('pids.current') or cg.get('pids.legacy.current'))
    pid_max = cg.get('pids.max', cg.get('pids.legacy.max', 'unknown'))
    lines += ['', 'THREADS / PROCESSES',
              'PIDs currently used / limit: %s / %s' % (pid_cur, pid_max),
              'Live processes observed (includes sleeping processes): ' + str(linux.get('process_count')),
              'Detailed processes listed: ' + str(len(processes)),
              'Runnable processes (state R) among listed: ' + str(sum(p.get('state') == 'R' for p in processes)),
              'Explicit Docker pids limit: ' + str(data['host'].get('PidsLimit') or 'none'),
              '', 'OPEN FILES',
              'Diagnostic shell soft/hard open-file limit: ' + ' / '.join(linux.get('shell_fd') or ['unknown']),
              'Sum of process open FDs (not a shared per-process limit): ' +
              str(sum(p['fds'] or 0 for p in processes)),
              'Per-process limits shown below are individually measured from /proc/PID/limits.',
              'Docker configured ulimits: ' + json.dumps(data['host'].get('Ulimits'))]
    if len(kernel) == 3 and kernel[0] is not None:
        lines.append('Kernel-wide files used / maximum: %s / %s' %
                     (max(0, kernel[0] - (kernel[1] or 0)), kernel[2]))
    lines += ['', 'DISK SPACE AND FILE/INODE COUNTS']
    for group, label in (('disks', 'DISK space (KiB)'), ('inodes', 'INODE/file capacity')):
        for path, item in (linux.get(group) or {}).items():
            lines.append('%s %s: %s used / %s total, %s available (%.1f%% used), mount=%s' %
                         (label, path, item['used'], item['total'], item['available'], item['pct'], item['mount']))
    lines += ['', 'JAVA HEAPS',
              'Active JVM processes: ' + str(len(jvms)),
              'Active JVMs with explicit heap maxima: ' + str(len(explicit)),
              'Sum of explicitly configured Java maximum heaps: ' + _bytes(sum(explicit)),
              'JVM telemetry requires jstat (and optionally jcmd) installed in container.',
              'A process with no explicit -Xmx and no jcmd-reported limit has unknown heap maximum.',
              'JVM probe status: ' + str(linux.get('java_probe_status') or 'see individual processes'),
              'Observed Java heap used/committed/max:',
              *['PID %s: %s / %s / %s (%s)' % (p['pid'], _bytes(p.get('heap_used')),
                   _bytes(p.get('heap_committed')), _bytes(p.get('heap_max')),
                   p.get('heap_status', '?')) for p in jvms],
              '', 'PROCESSES (RSS is actual resident RAM, not Java heap capacity)',
              'PID | Role | State | Name | CPU% | RSS MiB | Peak RSS MiB | JVM Heap Used/Committed/Maximum | GC/min | OpenFD/SoftFD | Command']
    for p in sorted(processes, key=lambda x: x.get('rss_kib') or 0, reverse=True):
        lines.append('%s | %s | %s | %s | %s | %.1f | %.1f | %s / %s / %s | %s | %s/%s | %s' %
                     (p['pid'], p.get('role','?'), p.get('state') or '?', p['name'],
                      ('%.1f' % p['cpu_percent']) if p.get('cpu_percent') is not None else '?',
                      (p.get('rss_kib') or 0) / 1024, (p.get('rss_peak_kib') or 0) / 1024,
                      _bytes(p.get('heap_used')), _bytes(p.get('heap_committed')),
                      _bytes(p.get('heap_max')), ('%.1f' % p['gc_rate']) if p.get('gc_rate') is not None else '-',
                      p['fds'], p['fd_soft'], p['command']))
    lines += ['', 'NOTE',
              'CPU saturation usually slows processes but does not directly terminate them.',
              'JVM OutOfMemoryError may occur with free Docker RAM and no Linux OOM kills.',
              'History records only samples collected while this monitor is open; short-lived peaks may be missed.',
              'memory.peak and per-process VmHWM are kernel-recorded peaks when available.']
    return '\n'.join(lines) + '\n'


class ContainerResourceMonitor(tk.Toplevel):
    def __init__(self, parent, name):
        super().__init__(parent)
        self.name = name
        self.title('Docker Container Resource Monitor — ' + name)
        self.geometry('1240x830')
        self.minsize(900, 590)
        self.transient(parent.winfo_toplevel())
        self.configure(bg='#EAF3FA')
        self.auto = tk.BooleanVar(value=True)
        self.thresholds = dict(DEFAULT_THRESHOLDS)
        self.record_history = tk.BooleanVar(value=False)
        self.history_path = tk.StringVar(value='')
        self.history_status = tk.StringVar(value='History not being recorded.')
        self.history_error = ''
        self.history_summary = tk.StringVar(value='No historical measurements yet.')
        self.history_metric = tk.StringVar(value='Docker memory (MiB)')
        self.history_samples = []
        self.history_events = []
        self.last_alerts = set()
        self._load_monitor_settings()
        self.status = tk.StringVar(value='Collecting resource statistics...')
        self.health = tk.StringVar(value='Loading...')
        self.events = queue.Queue()
        self.busy = False
        self.closed = False
        self.timer = None
        self.snapshot = None
        self.peak_memory = None
        self.report = ''
        self.action_history = []
        self.history_max_samples = 7200
        self.history_max_events = 2000
        self.process_lookup = {}
        self.action_busy = False
        self.process_summary = tk.StringVar(value='Processes: collecting...')
        self.last_monotonic = None
        self.sort_column = 'rss_kib'
        self.reverse_sort = True
        self._render()
        self._update_history_status()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(70, self._drain)
        self.after_idle(self.refresh)

    def _render(self):
        top = tk.Frame(self, bg='#196A8D', padx=14, pady=12)
        top.pack(fill='x')
        tk.Label(top, text='CONTAINER RESOURCE MONITOR — ' + self.name, bg='#196A8D',
                 fg='white', font=('Segoe UI', 15, 'bold')).pack(anchor='w')
        tk.Label(top, text='Resource monitoring and confirmed process termination: RAM, CPU, swap, OOM, PIDs, open files, disk and Java',
                 bg='#196A8D', fg='white').pack(anchor='w')
        controls = tk.Frame(self, bg='#EAF3FA', padx=12, pady=9)
        controls.pack(fill='x')
        self.refresh_button = tk.Button(controls, text='Refresh Now', command=self.refresh,
                                        bg='#78C7F0', font=('Segoe UI', 10, 'bold'), padx=12)
        self.refresh_button.pack(side='left', padx=(0, 12))
        tk.Checkbutton(controls, text='Auto-refresh every 5 seconds', variable=self.auto,
                       command=self._toggle, bg='#EAF3FA').pack(side='left', padx=(0, 12))
        tk.Button(controls, text='Save Complete Report...', command=self.save,
                  bg='#B8DCD2').pack(side='left', padx=(0, 12))
        tk.Button(controls, text='Warning Thresholds...', command=self._threshold_dialog).pack(side='left', padx=(0, 12))
        tk.Button(controls, text='Close', command=self.close).pack(side='right')
        history_controls = tk.Frame(self, bg='#EAF3FA', padx=12, pady=5)
        history_controls.pack(fill='x')
        tk.Checkbutton(history_controls, text='Record history to file', bg='#EAF3FA',
                       variable=self.record_history, command=self._toggle_history_recording).pack(side='left', padx=(0, 8))
        tk.Entry(history_controls, textvariable=self.history_path, width=75).pack(side='left', fill='x', expand=True)
        tk.Button(history_controls, text='Browse...', command=self._browse_history_file).pack(side='left', padx=(8, 10))
        tk.Label(self, textvariable=self.history_status, anchor='w', bg='#EAF3FA', fg='#34546B',
                 padx=14, pady=3).pack(fill='x')
        head = tk.Frame(self, bg='#D8EFF0', padx=10, pady=8)
        head.pack(fill='x', padx=12)
        self.health_label = tk.Label(head, textvariable=self.health, bg='#D8EFF0', fg='#20566A',
                                     anchor='w', font=('Segoe UI', 11, 'bold'))
        self.health_label.pack(fill='x')
        tk.Label(head, textvariable=self.status, bg='#D8EFF0', fg='#315D74', anchor='w',
                 font=('Segoe UI', 9)).pack(fill='x')
        tabs = ttk.Notebook(self)
        tabs.pack(fill='both', expand=True, padx=12, pady=(8, 12))
        overview = tk.Frame(tabs)
        process_frame = tk.Frame(tabs)
        history_frame = tk.Frame(tabs)
        detail_frame = tk.Frame(tabs)
        tabs.add(overview, text='Overview + Warnings')
        tabs.add(process_frame, text='Processes + Open Files')
        tabs.add(history_frame, text='History + Failures')
        tabs.add(detail_frame, text='Raw Diagnostics (JSON)')
        self._render_history(history_frame)
        raw_actions = tk.Frame(detail_frame)
        raw_actions.pack(fill='x', padx=7, pady=(5, 0))
        tk.Label(raw_actions, text='Exact most recent snapshot, JVM counters and recent events. For troubleshooting and export.',
                 anchor='w').pack(side='left')
        tk.Button(raw_actions, text='Copy JSON', command=self._copy_raw_json).pack(side='right')
        self.overview = self._text_widget(overview)
        self.details = self._text_widget(detail_frame)
        action_bar = tk.Frame(process_frame, bg='#EAF3FA', pady=6, padx=8)
        action_bar.grid(row=0, column=0, columnspan=2, sticky='ew')
        tk.Label(action_bar, textvariable=self.process_summary, bg='#EAF3FA',
                 font=('Segoe UI', 10, 'bold')).pack(side='left', padx=(0, 18))
        self.term_button = tk.Button(action_bar, text='Terminate Selected (SIGTERM)',
                                     bg='#F4D187', state='disabled',
                                     command=lambda: self.stop_processes('TERM'))
        self.term_button.pack(side='left', padx=(0, 8))
        self.kill_button = tk.Button(action_bar, text='Force Kill Selected (SIGKILL)',
                                     bg='#F2B2AE', state='disabled',
                                     command=lambda: self.stop_processes('KILL'))
        self.kill_button.pack(side='left')
        self.columns = [('pid','PID',75), ('role','Role',150), ('rss_peak_kib','Peak RSS MiB',110),
                        ('heap_used','Heap used MiB',120), ('heap_committed','Heap committed MiB',135),
                        ('heap_pct','Heap % max',95), ('gc_rate','GC/min',80), ('heap_status','Heap telemetry',210),
                        ('read_bytes','Disk read MiB',100), ('write_bytes','Disk write MiB',110),
                        ('fd_growth_per_min','FD growth/min',105),
                        ('read_bytes_per_sec','Read MiB/s',100), ('write_bytes_per_sec','Write MiB/s',100), ('state','State',65), ('name','Process',140), ('cpu_percent','CPU %',85),
                        ('rss_kib','RSS MiB',95), ('swap_kib','Swap MiB',95),
                        ('virtual_kib','Virtual MiB',100), ('threads','Threads',80),
                        ('fds','Open files',95), ('fd_soft','FD soft limit',110),
                        ('fd_pct','FD limit %',95), ('heap_max','Java -Xmx',110),
                        ('command','Full command',550)]
        self.table = ttk.Treeview(process_frame, columns=[c[0] for c in self.columns], show='headings', selectmode='extended')
        for key, title, width in self.columns:
            self.table.heading(key, text=title, command=lambda col=key: self.sort(col))
            self.table.column(key, width=width, stretch=(key == 'command'),
                              anchor='w' if key in ('name', 'command', 'role') else 'e')
        self.table.tag_configure('critical', background='#F9D7D7')
        self.table.tag_configure('warning', background='#FFF0CD')
        self.table.tag_configure('protected', background='#E4E4E4')
        self.table.tag_configure('java', background='#E5F4FF')
        self.table.bind('<<TreeviewSelect>>', self._update_stop_buttons)
        sy = ttk.Scrollbar(process_frame, orient='vertical', command=self.table.yview)
        sx = ttk.Scrollbar(process_frame, orient='horizontal', command=self.table.xview)
        self.table.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.table.grid(row=1, column=0, sticky='nsew')
        sy.grid(row=1, column=1, sticky='ns')
        sx.grid(row=2, column=0, sticky='ew')
        process_frame.grid_rowconfigure(1, weight=1)
        process_frame.grid_columnconfigure(0, weight=1)
        tk.Label(process_frame, text='Select one or more PIDs (Ctrl/Shift-click). Main, keep-alive and monitor processes are protected. SIGTERM requests graceful exit; SIGKILL stops immediately.',
                 anchor='w', pady=5).grid(row=3, column=0, sticky='ew')

    @staticmethod
    def _text_widget(parent):
        frame = tk.Frame(parent)
        frame.pack(fill='both', expand=True)
        field = tk.Text(frame, font=('Consolas', 10), wrap='none', padx=10, pady=10)
        for level, color in (('CRITICAL','#9E1616'), ('WARNING','#985900'), ('OK','#12663F')):
            field.tag_configure(level, foreground=color, font=('Consolas', 10, 'bold'))
        sy = ttk.Scrollbar(frame, orient='vertical', command=field.yview)
        sx = ttk.Scrollbar(frame, orient='horizontal', command=field.xview)
        field.config(yscrollcommand=sy.set, xscrollcommand=sx.set)
        field.grid(row=0, column=0, sticky='nsew')
        sy.grid(row=0, column=1, sticky='ns')
        sx.grid(row=1, column=0, sticky='ew')
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        return field

    @staticmethod
    def _write(widget, content):
        widget.config(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', content)
        for level in ('CRITICAL','WARNING','OK'):
            position = '1.0'
            while True:
                match = widget.search('[' + level + ']', position, stopindex='end')
                if not match:
                    break
                widget.tag_add(level, match, match + ' lineend')
                position = match + ' lineend'
        widget.config(state='disabled')

    def _toggle(self):
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
        if self.auto.get() and not self.busy:
            self.timer = self.after(5000, self._auto_tick)

    def _auto_tick(self):
        self.timer = None
        if not self.closed and self.auto.get():
            self.refresh()

    def refresh(self):
        if self.closed or self.busy:
            return
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
        self.busy = True
        self.refresh_button.config(state='disabled')
        self._update_stop_buttons()
        self.status.set('Collecting Docker and Linux resource counters...')

        def worker():
            try:
                self.events.put(('ok', collect_snapshot(self.name)))
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
                self.events.put(('error', str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _drain(self):
        if self.closed:
            return
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == 'ok':
                    self._display(payload)
                elif kind == 'stop_result':
                    signal, statuses, items = payload
                    for item, outcome in zip(items, statuses):
                        self._add_history_event('SIGNAL', 'SIG%s sent to PID %s (%s): %s — %s' % (
                            signal, item['pid'], item.get('name'), outcome['status'], outcome['message']),
                            item.get('pid'))
                        self.action_history.append('%s | SIG%s | PID %s (%s) | %s: %s' % (
                            datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                            signal, item['pid'], item.get('name'), outcome['status'], outcome['message']))
                    self.action_busy = False
                    self.busy = False
                    self.refresh_button.config(state='normal')
                    self._update_stop_buttons()
                    messagebox.showinfo('Process termination results', '\n'.join(
                        'PID %s: %s — %s' % (x['pid'], x['status'], x['message']) for x in statuses), parent=self)
                    self.refresh()
                    continue
                elif kind == 'stop_error':
                    self.action_busy = False
                    self.busy = False
                    self.refresh_button.config(state='normal')
                    self._update_stop_buttons()
                    messagebox.showerror('Unable to terminate selected processes', payload, parent=self)
                    self.refresh()
                    continue
                else:
                    self._add_history_event('MONITOR ERROR', str(payload)[:500])
                    self._refresh_history_view()
                    self.health.set('UNAVAILABLE — unable to read container resources')
                    self.health_label.config(fg='#A11D1D')
                    self.status.set(payload[:300])
                    self._write(self.overview, 'Container monitoring failed:\n\n' + payload)
                self.busy = False
                self.refresh_button.config(state='normal')
                self._update_stop_buttons()
                if self.auto.get() and self.timer is None:
                    self.timer = self.after(5000, self._auto_tick)
        except queue.Empty:
            pass
        self.after(120, self._drain)

    def _display(self, data):
        previous = self.snapshot if self.snapshot and self.snapshot.get('state', {}).get('Running') else None
        now = time.monotonic()
        if previous and self.last_monotonic is not None:
            elapsed = now - self.last_monotonic
            hz = (data.get('linux') or {}).get('clock_ticks') or 100
            earlier = {p['pid']: p for p in previous['linux']['processes']}
            for p in (data.get('linux') or {}).get('processes') or []:
                old = earlier.get(p['pid'])
                if old and old['name'] == p['name'] and old.get('start_ticks') == p.get('start_ticks') and elapsed > 0:
                    if p.get('gc_count') is not None and old.get('gc_count') is not None:
                        p['gc_rate'] = max(0.0, (p['gc_count'] - old['gc_count']) * 60.0 / elapsed)
                    if p.get('fds') is not None and old.get('fds') is not None:
                        p['fd_growth_per_min'] = (p['fds'] - old['fds']) * 60.0 / elapsed
                    for field in ('read_bytes', 'write_bytes'):
                        if p.get(field) is not None and old.get(field) is not None:
                            p[field + '_per_sec'] = max(0.0, (p[field]-old[field])/elapsed)
                if old and old['name'] == p['name'] and old.get('start_ticks') == p.get('start_ticks') and elapsed > 0 and hz and \
                        old['ticks'] is not None and p['ticks'] is not None:
                    p['cpu_percent'] = max(0, (p['ticks'] - old['ticks']) * 100 / (hz * elapsed))
        self.last_monotonic = now
        used = (data.get('stats') or {}).get('memory_used')
        if used is not None:
            self.peak_memory = max(self.peak_memory or 0, used)
        alarms = warnings_for(data, previous, self.thresholds)
        self._record_sample_and_events(data, previous, alarms)
        level = 'CRITICAL' if any(a[0] == 'CRITICAL' for a in alarms) else \
                'WARNING' if any(a[0] == 'WARNING' for a in alarms) else 'OK'
        count = sum(a[0] != 'OK' for a in alarms)
        self.health.set('%s — %s resource warning(s)' % (level, count))
        self.health_label.config(fg={'CRITICAL':'#A11D1D','WARNING':'#945B00','OK':'#147042'}[level])
        self.status.set('Last snapshot: ' + data['time'] +
                        '  |  Record history to a Windows file to preserve evidence after a job exits.')
        self.report = make_report(data, previous, self.peak_memory, self.thresholds)
        if self.action_history:
            self.report += '\nPROCESS TERMINATION HISTORY (this monitor session)\n'
            self.report += '\n'.join(self.action_history) + '\n'
        if self.history_events:
            self.report += '\nRECENT DETECTED EVENTS (PID disappearance alone does not prove a crash)\n'
            self.report += '\n'.join('%s | %s | %s' % (x['time'], x['kind'], x['message'])
                                     for x in self.history_events[-50:]) + '\n'
        self.report += '\nHistory file: %s\n' % (self.history_path.get() if self.record_history.get() else 'off')
        self._write(self.overview, self.report)
        self.raw_json = json.dumps({'snapshot': data, 'recent_events': self.history_events[-100:]},
                                   indent=2, ensure_ascii=False, default=str)
        self._write(self.details, self.raw_json)
        self.snapshot = data
        self._fill_table()
        self._refresh_history_view()

    def sort(self, column):
        if self.sort_column == column:
            self.reverse_sort = not self.reverse_sort
        else:
            self.sort_column = column
            self.reverse_sort = column not in ('name','command','role')
        self._fill_table()

    def _update_stop_buttons(self, event=None):
        valid = bool(self.table.selection()) and not self.busy and not self.action_busy
        if valid:
            for iid in self.table.selection():
                process = self.process_lookup.get(iid)
                if not process or not isinstance(process.get('start_ticks'), int) or \
                        process['start_ticks'] <= 0 or not isinstance(process.get('pid'), int) or process['pid'] <= 1 or \
                        process.get('role') in ('Container main / protected', 'Keep-alive / protected', 'Monitor / protected'):

                    valid = False
                    break
        state = 'normal' if valid else 'disabled'
        self.term_button.config(state=state)
        self.kill_button.config(state=state)

    def stop_processes(self, signal):
        if self.closed or self.busy or self.action_busy or not self.snapshot:
            return
        if not (self.snapshot.get('state') or {}).get('Running'):
            messagebox.showwarning('Container stopped', 'Refresh and start the container before terminating processes.', parent=self)
            return
        ids = self.table.selection()
        items = [self.process_lookup[iid] for iid in ids if iid in self.process_lookup]
        if not items or len(items) != len(ids) or len(items) > 100:
            messagebox.showwarning('Select processes', 'Select 1–100 processes in the table.', parent=self)
            return
        if any(p['pid'] <= 1 or not isinstance(p.get('start_ticks'), int) or p['start_ticks'] <= 0 or
               p.get('role') in ('Container main / protected', 'Keep-alive / protected', 'Monitor / protected') for p in items):
            messagebox.showwarning('Protected process', 'PID 1 and processes with unverifiable identities cannot be terminated.', parent=self)
            return
        mode = str((self.snapshot.get('host') or {}).get('PidMode') or '')
        if mode not in ('', 'private'):
            messagebox.showwarning('Shared PID namespace', 'Terminating processes is disabled for shared PID namespaces.', parent=self)
            return
        lines = ['PID %s — %s — %s' % (p['pid'], p['name'], p['command'][:110]) for p in items]
        shown = '\n'.join(lines[:12])
        if len(items) > 12:
            shown += '\n... and %d additional processes' % (len(items)-12)
        warning = ('SIGKILL immediately stops processes without cleanup. Output files may be incomplete.' if signal == 'KILL'
                   else 'SIGTERM requests graceful termination. Applications may stop without finishing output files.')
        ask = ('Send SIG%s to these %d selected process(es) inside %s?\n\n%s\n\n%s\n\n'
               'This runs kill as root inside the container. PID 1 is protected.\n'
               'The container will not be stopped or restarted.') % (signal, len(items), self.name, shown, warning)
        if not messagebox.askyesno('Confirm SIG%s' % signal, ask, parent=self,
                                   icon='warning' if signal == 'KILL' else 'question'):
            return
        self.action_busy = True
        self.busy = True
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
        self.refresh_button.config(state='disabled')
        self._update_stop_buttons()
        self.status.set('Sending SIG%s to %d selected processes...' % (signal, len(items)))
        cid = self.snapshot.get('container_id')

        def worker():
            try:
                result = stop_selected_processes(self.name, cid, items, signal)
                self.events.put(('stop_result', (signal, result, items)))
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired,
                    json.JSONDecodeError) as exc:
                self.events.put(('stop_error', str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _fill_table(self):
        selected = set(self.table.selection())
        self.table.delete(*self.table.get_children())
        self.process_lookup = {}
        if not self.snapshot:
            self.process_summary.set('Processes: unavailable')
            self._update_stop_buttons()
            return
        linux = self.snapshot.get('linux') or {}
        processes = list(linux.get('processes') or [])
        total = linux.get('process_count')
        java_count = sum(p['name'] in ('java', 'java.exe') for p in processes)
        running = sum(p.get('state') == 'R' for p in processes)
        cg = linux.get('cgroup') or {}
        threads = cg.get('pids.current', cg.get('pids.legacy.current', '?'))
        maximum = cg.get('pids.max', cg.get('pids.legacy.max', '?'))
        active_jobs = sum(not is_infrastructure(p) for p in processes)
        self.process_summary.set('All processes: %s | Workload: %s | Runnable: %s | Java: %s | Threads/tasks: %s / %s' %
                                 (total if total is not None else '?', active_jobs, running, java_count, threads, maximum))

        def sort_value(p):
            if self.sort_column == 'fd_pct':
                return _percent(p['fds'], p['fd_soft']) or 0
            val = p.get(self.sort_column)
            return str(val or '').lower() if self.sort_column in ('name', 'state', 'command', 'role') else val or 0

        processes.sort(key=sort_value, reverse=self.reverse_sort)
        for p in processes:
            pid = p.get('pid')
            start = p.get('start_ticks')
            if pid is None:
                continue
            iid = 'pid%s_start%s' % (pid, start if start is not None else 'unknown')
            self.process_lookup[iid] = p
            ratio = _percent(p['fds'], p['fd_soft'])
            heap_ratio = _percent(p.get('heap_used'), p.get('heap_max'))
            tag = 'protected' if p.get('role') in ('Container main / protected', 'Keep-alive / protected', 'Monitor / protected') else \
                  'critical' if (ratio is not None and ratio >= 95) or (heap_ratio is not None and heap_ratio >= 96) else \
                  'warning' if (ratio is not None and ratio >= 75) or (heap_ratio is not None and heap_ratio >= 85) else \
                  'java' if p.get('role') == 'Java job' else ''
            values = (pid, p.get('role', 'Other'),
                      '%.1f' % ((p.get('rss_peak_kib') or 0) / 1024) if p.get('rss_peak_kib') is not None else '-',
                      '%.1f' % (p.get('heap_used') / 1048576) if p.get('heap_used') is not None else '-',
                      '%.1f' % (p.get('heap_committed') / 1048576) if p.get('heap_committed') is not None else '-',
                      ('%.1f%%' % heap_ratio) if heap_ratio is not None else '-',
                      ('%.1f' % p['gc_rate']) if p.get('gc_rate') is not None else '-',
                      p.get('heap_status', '-') if p.get('role') == 'Java job' else '-',
                      '%.1f' % (p['read_bytes'] / 1048576) if p.get('read_bytes') is not None else '-',
                      '%.1f' % (p['write_bytes'] / 1048576) if p.get('write_bytes') is not None else '-',
                      ('%.1f' % p['fd_growth_per_min']) if p.get('fd_growth_per_min') is not None else '-',
                      ('%.2f' % (p['read_bytes_per_sec']/1048576)) if p.get('read_bytes_per_sec') is not None else '-',
                      ('%.2f' % (p['write_bytes_per_sec']/1048576)) if p.get('write_bytes_per_sec') is not None else '-',
                      pid, p.get('state') or '?', p['name'],
                      ('%.1f' % p['cpu_percent']) if p.get('cpu_percent') is not None else '-',
                      '%.1f' % ((p.get('rss_kib') or 0) / 1024),
                      '%.1f' % ((p.get('swap_kib') or 0) / 1024),
                      '%.1f' % ((p.get('virtual_kib') or 0) / 1024),
                      p['threads'], p['fds'], p['fd_soft'],
                      ('%.1f%%' % ratio) if ratio is not None else '?',
                      _bytes(p['heap_max']) if p['heap_max'] is not None else '-', p['command'])
            self.table.insert('', 'end', iid=iid, values=values, tags=(tag,) if tag else ())
        keep = [iid for iid in selected if iid in self.process_lookup]
        if keep:
            self.table.selection_set(keep)
        self._update_stop_buttons()

    def save(self):
        if not self.report:
            messagebox.showinfo('Resource report', 'No successful snapshot is available yet.', parent=self)
            return
        path = filedialog.asksaveasfilename(parent=self, title='Save Docker container resource report',
                                             initialfile='Docker_Resource_Report_' + self.name + '.txt',
                                             defaultextension='.txt',
                                             filetypes=[('Text reports','*.txt'),('All files','*.*')])
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as output:
                output.write(self.report)
                output.write('\nRAW SNAPSHOT (JSON)\n')
                json.dump(self.snapshot, output, ensure_ascii=False, indent=2, default=str)
                output.write('\n')
        except OSError as exc:
            messagebox.showerror('Save diagnostic report', str(exc), parent=self)
            return
        messagebox.showinfo('Saved diagnostic report', path, parent=self)



    def _threshold_dialog(self):
        dialog = tk.Toplevel(self)
        dialog.title('Resource warning thresholds')
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Show warnings when a resource reaches this percentage of its limit:').grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 12))
        labels = [('memory','Docker / cgroup memory'), ('java_heap','Java maximum heap'),
                  ('open_files','Open file descriptors'), ('disk','Disk / inode capacity')]
        variables = {}
        for i, (key, label) in enumerate(labels, 1):
            ttk.Label(frame, text=label).grid(row=i, column=0, sticky='w', padx=(0, 12), pady=5)
            variables[key] = tk.StringVar(value=str(self.thresholds[key]))
            ttk.Spinbox(frame, from_=30, to=99, textvariable=variables[key], width=8).grid(
                row=i, column=1, sticky='e', pady=5)
        ttk.Label(frame, text='Critical alerts retain higher thresholds. CPU and I/O pressure use fixed safety rules.',
                  wraplength=395, foreground='#526B82').grid(row=5, column=0, columnspan=2,
                                                               sticky='w', pady=(8, 12))
        footer = ttk.Frame(frame)
        footer.grid(row=6, column=0, columnspan=2, sticky='e')
        def accept():
            values = {}
            try:
                for key, variable in variables.items():
                    value = int(variable.get().strip())
                    if not 30 <= value <= 99:
                        raise ValueError('Set each percentage between 30 and 99.')
                    values[key] = value
            except ValueError as exc:
                messagebox.showerror('Invalid threshold', str(exc), parent=dialog)
                return
            self.thresholds.update(values)
            self._save_monitor_settings()
            dialog.destroy()
            if self.snapshot:
                self.refresh()
        ttk.Button(footer, text='Save thresholds', command=accept).pack(side='left', padx=(0, 8))
        ttk.Button(footer, text='Cancel', command=dialog.destroy).pack(side='left')
        dialog.protocol('WM_DELETE_WINDOW', dialog.destroy)
        dialog.wait_window()

    @staticmethod
    def _settings_path():
        local = os.environ.get('LOCALAPPDATA')
        folder = Path(local) / 'Docker_Image_Builder' if local else Path.home() / '.docker_image_builder'
        return folder / 'resource_monitor_settings.json'

    def _load_monitor_settings(self):
        try:
            obj = json.loads(self._settings_path().read_text(encoding='utf-8'))
            self.history_path.set(str(obj.get('history_path') or ''))
            self.record_history.set(bool(obj.get('record_history')))
            saved = obj.get('thresholds') or {}
            if isinstance(saved, dict):
                for key in DEFAULT_THRESHOLDS:
                    value = _num(saved.get(key))
                    if value is not None and 30 <= value <= 99:
                        self.thresholds[key] = value
        except (OSError, ValueError, TypeError):
            pass

    def _save_monitor_settings(self):
        try:
            path = self._settings_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({'history_path': self.history_path.get(),
                                       'record_history': bool(self.record_history.get()),
                                       'thresholds': self.thresholds}, indent=2),
                            encoding='utf-8')
        except OSError:
            pass

    def _browse_history_file(self):
        current = self.history_path.get().strip()
        proposed = ('Docker_Container_History_%s_%s.jsonl' %
                    (self.name, datetime.datetime.now().strftime('%Y%m%d_%H%M%S')))
        filename = filedialog.asksaveasfilename(parent=self, title='Choose persistent Docker monitoring history file',
            initialfile=Path(current).name if current else proposed,
            initialdir=str(Path(current).parent) if current else None,
            defaultextension='.jsonl',
            filetypes=[('JSON Lines history', '*.jsonl'), ('All files', '*.*')])
        if not filename:
            return False
        self.history_path.set(filename)
        self.history_error = ''
        self._save_monitor_settings()
        self._update_history_status()
        return True

    def _toggle_history_recording(self):
        if self.record_history.get():
            self.history_error = ''
            if not self.history_path.get().strip() and not self._browse_history_file():
                self.record_history.set(False)
                self._update_history_status()
                return
            try:
                self._write_history_record({'type': 'session_started', 'time':
                    datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                    'container': self.name, 'message': 'Recording started; existing file is appended to.'})
            except OSError as exc:
                self.record_history.set(False)
                messagebox.showerror('History logging unavailable', str(exc), parent=self)
        self._save_monitor_settings()
        self._update_history_status()

    def _write_history_record(self, record):
        path_text = self.history_path.get().strip()
        if not path_text:
            raise OSError('Select a history file with Browse before enabling recording.')
        path = Path(path_text).expanduser()
        if not path.parent.is_dir():
            raise OSError('History destination folder does not exist: ' + str(path.parent))
        with path.open('a', encoding='utf-8', newline='\n') as file:
            file.write(json.dumps(record, ensure_ascii=False, separators=(',', ':'), default=str) + '\n')

    def _update_history_status(self):
        if not self.record_history.get():
            self.history_status.set(self.history_error or 'History file recording OFF. In-memory history is kept only while the monitor stays open.')
            return
        path = Path(self.history_path.get().strip())
        try:
            suffix = ', file size %s' % _bytes(path.stat().st_size) if path.is_file() else ''
        except OSError:
            suffix = ''
        if path.is_file():
            try:
                if path.stat().st_size >= 1024**3:
                    suffix += ' — WARNING: file exceeds 1 GiB; monitor available disk space'
            except OSError:
                pass
        self.history_status.set('Recording every successful refresh → %s%s' % (str(path), suffix))

    def _add_history_event(self, kind, message, pid=None):
        event = {'time': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
                 'kind': str(kind), 'message': str(message), 'pid': pid}
        self.history_events.append(event)
        if len(self.history_events) > self.history_max_events:
            del self.history_events[:len(self.history_events) - self.history_max_events]
        if self.record_history.get() and self.history_path.get().strip():
            try:
                self._write_history_record({'type': 'event', 'container': self.name, **event})
            except OSError as exc:
                self.record_history.set(False)
                self.history_error = 'HISTORY WRITE FAILED — logging disabled: %s' % exc
                self.history_status.set(self.history_error)
                self._save_monitor_settings()
        return event

    def _record_sample_and_events(self, data, previous, alarms):
        linux = data.get('linux') or {}
        stats = data.get('stats') or {}
        procs = linux.get('processes') or []
        jvms = [p for p in procs if p.get('role') == 'Java job']
        cg = linux.get('cgroup') or {}
        self.history_samples.append({
            'time': data['time'], 'memory_used': stats.get('memory_used'),
            'memory_limit': _effective_limit(data), 'cpu_percent': stats.get('cpu_value'),
            'java_rss': sum((p.get('rss_kib') or 0) * 1024 for p in jvms),
            'java_heap': sum(p.get('heap_used') or 0 for p in jvms),
            'java_count': len(jvms), 'process_count': linux.get('process_count'),
            'oom_kill': (linux.get('events') or {}).get('memory.events.oom_kill'),
            'cgroup_memory_peak': _num(cg.get('memory.peak')),
            'cpu_pressure': (linux.get('pressure') or {}).get('container.cpu.some'),
            'io_pressure': (linux.get('pressure') or {}).get('container.io.some')})
        if len(self.history_samples) > self.history_max_samples:
            del self.history_samples[:len(self.history_samples) - self.history_max_samples]
        current_alerts = set((level, text) for level, text in alarms if level in ('CRITICAL', 'WARNING'))
        if previous and previous.get('container_id') == data.get('container_id'):
            prior = { (p.get('pid'), p.get('start_ticks')): p for p in
                      (previous.get('linux') or {}).get('processes') or [] }
            current = { (p.get('pid'), p.get('start_ticks')): p for p in procs }
            prev_count = (previous.get('linux') or {}).get('process_count') or 0
            max_listed = len((previous.get('linux') or {}).get('processes') or [])
            if prev_count <= max_listed and (linux.get('process_count') or 0) <= len(procs):
                oom_prev = ((previous.get('linux') or {}).get('events') or {}).get('memory.events.oom_kill')
                oom_now = (linux.get('events') or {}).get('memory.events.oom_kill')
                possible_oom = oom_now is not None and oom_prev is not None and oom_now > oom_prev
                for identity, old in prior.items():
                    if identity not in current and not is_infrastructure(old):
                        note = ('PID %s (%s) disappeared; last RSS %s, peak RSS %s, '
                                'open FDs %s, observed Java heap %s. Exit reason/code unknown.' %
                                (old.get('pid'), old.get('name'),
                                 _bytes((old.get('rss_kib') or 0) * 1024),
                                 _bytes((old.get('rss_peak_kib') or 0) * 1024),
                                 old.get('fds'), _bytes(old.get('heap_used'))))
                        if possible_oom:
                            note += ' OOM kill counter also increased; possible relationship, not proven.'
                        self._add_history_event('PROCESS EXIT OBSERVED', note, old.get('pid'))
                for identity, new in current.items():
                    if identity not in prior and new.get('role') == 'Java job':
                        self._add_history_event('JAVA START OBSERVED',
                                                'PID %s started: %s' % (new['pid'], new.get('command', '')[:220]),
                                                new['pid'])
        elif previous and previous.get('container_id') != data.get('container_id'):
            self._add_history_event('CONTAINER REPLACED', 'Container ID changed. Old PID identities are no longer relevant.')
        for level, message in sorted(current_alerts - self.last_alerts):
            self._add_history_event(level, message)
        self.last_alerts = current_alerts
        if self.record_history.get():
            try:
                self._write_history_record({'type': 'snapshot', 'time': data['time'],
                                            'container': self.name, 'snapshot': data,
                                            'warnings': alarms})
            except OSError as exc:
                self.record_history.set(False)
                self.history_error = 'HISTORY WRITE FAILED — logging disabled: %s' % exc
                self.history_status.set(self.history_error)
                self._save_monitor_settings()
        self._update_history_status()

    def _render_history(self, parent):
        bar = tk.Frame(parent, padx=8, pady=5)
        bar.pack(fill='x')
        tk.Label(bar, textvariable=self.history_summary, font=('Segoe UI', 10, 'bold')).pack(side='left')
        tk.Button(bar, text='Export session CSV...', command=self._export_history_csv).pack(side='right')
        combo = ttk.Combobox(bar, textvariable=self.history_metric, state='readonly', width=25,
            values=('Docker memory (MiB)', 'Total Java RSS (MiB)', 'Observed Java heap (MiB)',
                    'CPU usage (%)', 'Java process count', 'Total process count',
                    'I/O pressure (%)'))
        combo.pack(side='right', padx=8)
        combo.bind('<<ComboboxSelected>>', lambda event: self._draw_history_chart())
        self.history_canvas = tk.Canvas(parent, bg='#FFFFFF', height=188, highlightthickness=1,
                                        highlightbackground='#CBD5E1')
        self.history_canvas.pack(fill='x', padx=10, pady=(1, 8))
        self.history_canvas.bind('<Configure>', lambda event: self._draw_history_chart())
        tk.Label(parent, text='Recent sampled measurements (this monitor session)', anchor='w').pack(fill='x', padx=10)
        measure_frame = tk.Frame(parent)
        measure_frame.pack(fill='both', expand=True, padx=10, pady=(2, 7))
        cols = ('time', 'memory', 'cpu', 'java', 'jvm_rss', 'jvm_heap', 'processes', 'oom')
        self.history_table = ttk.Treeview(measure_frame, columns=cols, show='headings', height=6)
        for col, label, width in [('time','Time',200), ('memory','Docker RAM MiB',125),
                                   ('cpu','CPU %',85), ('java','Java JVMs',85),
                                   ('jvm_rss','Java RSS MiB',110), ('jvm_heap','JVM heap MiB',110),
                                   ('processes','Processes',95), ('oom','OOM kills',95)]:
            self.history_table.heading(col, text=label)
            self.history_table.column(col, width=width, anchor='e' if col != 'time' else 'w')
        scr = ttk.Scrollbar(measure_frame, orient='vertical', command=self.history_table.yview)
        self.history_table.configure(yscrollcommand=scr.set)
        self.history_table.pack(side='left', fill='both', expand=True)
        scr.pack(side='right', fill='y')
        tk.Label(parent, text='Events: process starts/disappearances, new warnings, OOM counter changes and manual signals',
                 anchor='w').pack(fill='x', padx=10)
        event_frame = tk.Frame(parent)
        event_frame.pack(fill='both', expand=True, padx=10, pady=(2, 8))
        self.history_event_table = ttk.Treeview(event_frame, columns=('time', 'kind', 'message'),
                                                show='headings', height=7)
        for col, label, width in [('time','Time',190), ('kind','Event',180), ('message','Details',800)]:
            self.history_event_table.heading(col, text=label)
            self.history_event_table.column(col, width=width, stretch=(col=='message'), anchor='w')
        sy = ttk.Scrollbar(event_frame, orient='vertical', command=self.history_event_table.yview)
        sx = ttk.Scrollbar(parent, orient='horizontal', command=self.history_event_table.xview)
        self.history_event_table.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.history_event_table.pack(side='left', fill='both', expand=True)
        sy.pack(side='right', fill='y')
        sx.pack(fill='x', padx=10, pady=(0, 8))

    def _refresh_history_view(self):
        self.history_summary.set('%d samples | %d events | latest %s' %
                                 (len(self.history_samples), len(self.history_events),
                                  self.history_samples[-1]['time'] if self.history_samples else '-'))
        samples = self.history_samples[-250:]
        self.history_table.delete(*self.history_table.get_children())
        for item in reversed(samples):
            self.history_table.insert('', 'end', values=(item['time'],
                '%.1f' % (item['memory_used'] / 1048576) if item['memory_used'] is not None else '-',
                '%.1f' % item['cpu_percent'] if item['cpu_percent'] is not None else '-',
                item['java_count'], '%.1f' % (item['java_rss'] / 1048576),
                '%.1f' % (item['java_heap'] / 1048576), item['process_count'], item['oom_kill']))
        self.history_event_table.delete(*self.history_event_table.get_children())
        for ev in reversed(self.history_events[-300:]):
            self.history_event_table.insert('', 'end', values=(ev['time'], ev['kind'], ev['message']))
        self._draw_history_chart()

    def _draw_history_chart(self):
        canvas = self.history_canvas
        canvas.delete('all')
        width = max(280, canvas.winfo_width())
        height = max(130, canvas.winfo_height())
        left, right, top, bottom = 65, 18, 18, 35
        metric = self.history_metric.get()
        attributes = {'Docker memory (MiB)': ('memory_used', 1048576),
                      'Total Java RSS (MiB)': ('java_rss', 1048576),
                      'Observed Java heap (MiB)': ('java_heap', 1048576),
                      'CPU usage (%)': ('cpu_percent', 1),
                      'Java process count': ('java_count', 1),
                      'Total process count': ('process_count', 1),
                      'I/O pressure (%)': ('io_pressure', 1)}
        key, factor = attributes.get(metric, ('memory_used', 1048576))
        series = [(x['time'], x[key] / factor) for x in self.history_samples[-500:]
                  if x.get(key) is not None]
        canvas.create_text(12, 8, text=metric, anchor='nw', fill='#34495E')
        if not series:
            canvas.create_text(width/2, height/2, text='No measurements available yet',
                               fill='#64748B')
            return
        plot_width = max(1, width - left - right)
        plot_height = max(1, height - top - bottom)
        max_val = max(1.0, max(v for _, v in series) * 1.12)
        for k in range(5):
            y = top + plot_height * k / 4
            canvas.create_line(left, y, left + plot_width, y, fill='#EDF1F5')
            canvas.create_text(left-8, y, text='%.1f' % (max_val * (4-k)/4),
                               anchor='e', fill='#64748B')
        coords=[]
        for i,(when,val) in enumerate(series):
            x = left + plot_width*i/max(1, len(series)-1)
            y = top + plot_height * (1-val/max_val)
            coords.extend((x,y))
        if len(coords)>=4:
            canvas.create_line(*coords, fill='#087EAE', width=2, smooth=False)
        else:
            x,y=coords
            canvas.create_oval(x-3,y-3,x+3,y+3,fill='#087EAE',outline='')
        canvas.create_text(left, height-10, text=series[0][0][11:19],anchor='w',fill='#64748B')
        canvas.create_text(width-right,height-10,text=series[-1][0][11:19],anchor='e',fill='#64748B')
        canvas.create_text(width-right,top-9,text='Latest %.2f' % series[-1][1],
                           anchor='e',fill='#087EAE')

    def _export_history_csv(self):
        if not self.history_samples:
            messagebox.showinfo('History export','No samples have been collected yet.',parent=self)
            return
        path = filedialog.asksaveasfilename(parent=self, title='Export this session history as CSV',
                initialfile='Docker_Monitor_%s_History.csv' % self.name,
                defaultextension='.csv', filetypes=[('CSV files','*.csv'),('All files','*.*')])
        if not path:
            return
        try:
            with open(path,'w',encoding='utf-8-sig',newline='') as file:
                writer=csv.DictWriter(file,fieldnames=list(self.history_samples[0].keys()))
                writer.writeheader()
                writer.writerows(self.history_samples)
        except OSError as exc:
            messagebox.showerror('History export failed',str(exc),parent=self)
            return
        messagebox.showinfo('History exported',path,parent=self)

    def _copy_raw_json(self):
        raw=getattr(self,'raw_json','')
        if not raw:
            return
        self.clipboard_clear()
        self.clipboard_append(raw)

    def close(self):
        self._save_monitor_settings()
        self.closed = True
        if self.timer is not None:
            self.after_cancel(self.timer)
        self.destroy()
