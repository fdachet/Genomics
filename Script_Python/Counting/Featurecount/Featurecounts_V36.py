#!/usr/bin/env python3
import os
import re
import shlex
import subprocess
import threading
import queue
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, StringVar, IntVar
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

# If using WSL without a DISPLAY, set DISPLAY to :0
if os.name != "nt" and "DISPLAY" not in os.environ:
    os.environ["DISPLAY"] = ":0"


MODE_CHOICES = {
    0: "s0 only (unstranded)",
    1: "s1 only (same strand / StringTie --fr)",
    2: "s2 only (reverse strand / StringTie --rf)",
    3: "s1 + s2 then compare",
    4: "s0 + s1 + s2 then compare",
}

MODE_LABELS = {
    0: "s0_Unstranded",
    1: "s1_StrandedSame_Stringtie_fr",
    2: "s2_StrandedReverse_String_rf",
}

PASTEL = {
    "app_bg": "#f8f4ff",
    "panel_bg": "#fffafc",
    "panel2_bg": "#f6fffb",
    "panel3_bg": "#fffdf3",
    "header_bg": "#f3f7ff",
    "title_fg": "#6c5b7b",
    "text_fg": "#4b5563",
    "button_bg": "#d9ecff",
    "button_active": "#c4e1ff",
    "run_bg": "#d9f7e8",
    "run_active": "#c1efd8",
    "scan_bg": "#ffeccf",
    "scan_active": "#ffe0ae",
    "verify_bg": "#efe3ff",
    "verify_active": "#e2d1ff",
    "entry_bg": "#ffffff",
    "status_ok": "#5b7db1",
    "status_err": "#c0617a",
}

status_var = None
root = None
fc_cmd_var = None
bam_var = None
gtf_var = None
output_var = None
strand_var = None
threads_var = None
feature_type_var = None
gene_id_var = None
paired_var = None
multimap_var = None
overlap_var = None
minov_var = None
status_label = None
run_button = None
scan_button = None
verify_button = None
debug_button = None
report_box = None
strand_combo = None


def set_status(text: str, is_error: bool = False):
    status_var.set(text)
    try:
        status_label.configure(foreground=PASTEL["status_err"] if is_error else PASTEL["status_ok"])
        root.update_idletasks()
    except Exception:
        pass


def format_elapsed(seconds: float) -> str:
    seconds = int(max(0, seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def set_progress_ui(value=None, text=None, elapsed=None, indeterminate=None):
    try:
        if progress_text_var is not None and text is not None:
            progress_text_var.set(text)
        if elapsed_var is not None and elapsed is not None:
            elapsed_var.set(elapsed)
        if progress_bar is not None and indeterminate is not None:
            desired_mode = "indeterminate" if indeterminate else "determinate"
            current_mode = str(progress_bar.cget("mode"))
            if current_mode != desired_mode:
                try:
                    progress_bar.stop()
                except Exception:
                    pass
                progress_bar.configure(mode=desired_mode)
                if desired_mode == "indeterminate":
                    progress_bar.start(12)
            elif desired_mode == "indeterminate":
                progress_bar.start(12)
            else:
                try:
                    progress_bar.stop()
                except Exception:
                    pass
        if progress_var is not None and value is not None:
            progress_var.set(max(0.0, min(100.0, float(value))))
        if root is not None:
            root.update_idletasks()
    except Exception:
        pass


def reset_progress_ui(text: str = "Ready."):
    set_progress_ui(value=0, text=text, elapsed="Elapsed: 00:00", indeterminate=False)


def windows_to_linux_path(win_path: str) -> str:
    normalized = win_path.replace("\\", "/")
    res = subprocess.run(
        ["wsl", "wslpath", "-u", normalized],
        capture_output=True,
        text=True,
        check=True,
    )
    converted = re.sub(r"/+", "/", res.stdout.strip())
    if not converted:
        raise RuntimeError(f"Could not convert path to WSL path: {win_path}")
    return converted


def run_wsl_bash(script_text: str, check: bool = False, interactive: bool = False):
    return subprocess.run(
        ["wsl", "bash", "--noprofile", "--norc", "-lc", script_text],
        capture_output=True,
        text=True,
        check=check,
    )


def run_wsl_command_capture(command_text: str, interactive: bool = False):
    return subprocess.run(
        ["wsl", "bash", "--noprofile", "--norc", "-lc", command_text],
        capture_output=True,
        text=True,
        check=False,
    )


def _shorten_one_line(text: str, max_len: int = 160) -> str:
    text = (text or "").replace("\r", "").strip()
    if not text:
        return "<no output>"
    text = " | ".join(text.splitlines())
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def _indent_block(text: str, prefix: str = "    ") -> str:
    text = (text or "").replace("\r", "")
    if not text.strip():
        return prefix + "<empty>"
    return "\n".join(prefix + line for line in text.splitlines())


def probe_featurecounts_candidate(candidate: str, interactive: bool = True):
    candidate = (candidate or "").strip()
    q = shlex.quote(candidate)

    if "/" in candidate:
        resolve_cmd = f"test -x {q} && printf '%s\\n' {q} || true"
    else:
        resolve_cmd = f"command -v {q} 2>/dev/null || true"
    resolve_res = run_wsl_command_capture(resolve_cmd, interactive=interactive)
    resolved = ((resolve_res.stdout or "") + (("\n" + resolve_res.stderr) if resolve_res.stderr else "")).replace("\r", "").strip()

    version_cmd = f"{q} -v"
    version_res = run_wsl_command_capture(version_cmd, interactive=interactive)
    stdout = (version_res.stdout or "").replace("\r", "").strip()
    stderr = (version_res.stderr or "").replace("\r", "").strip()
    rc = version_res.returncode

    combined_parts = []
    if stdout:
        combined_parts.append(stdout)
    if stderr:
        combined_parts.append(stderr)
    combined_output = "\n".join(combined_parts).strip()

    lower = combined_output.lower()
    looks_valid = ("featurecounts v" in lower) or (bool(resolved) and rc == 0 and "command not found" not in lower)

    return {
        "candidate": candidate,
        "resolved": resolved,
        "rc": rc,
        "stdout": stdout,
        "stderr": stderr,
        "combined": combined_output,
        "looks_valid": looks_valid,
    }

def gather_wsl_featurecounts_debug(preferred: str = ""):
    preferred = (preferred or "").strip()
    env_script = r"""set +e
printf 'WHOAMI\t%s\n' "$(whoami 2>/dev/null)"
printf 'HOME\t%s\n' "$HOME"
printf 'PWD\t%s\n' "$(pwd 2>/dev/null)"
printf 'SHELL\t%s\n' "$SHELL"
printf 'PATH\t%s\n' "$PATH"
printf 'TYPE_FEATURECOUNTS_BEGIN\n'
type -a featureCounts 2>&1
printf 'TYPE_FEATURECOUNTS_END\n'
printf 'WHICH_FEATURECOUNTS_BEGIN\n'
which featureCounts 2>&1
printf 'WHICH_FEATURECOUNTS_END\n'
printf 'WHEREIS_FEATURECOUNTS_BEGIN\n'
whereis featureCounts 2>&1
printf 'WHEREIS_FEATURECOUNTS_END\n'
printf 'LS_USRBIN_BEGIN\n'
ls -l /usr/bin/featureCounts 2>&1
printf 'LS_USRBIN_END\n'
"""
    env_res = run_wsl_bash(env_script, check=False, interactive=True)
    env_text = ((env_res.stdout or "") + (("\n" + env_res.stderr) if env_res.stderr else "")).replace("\r", "")

    env_map = {}
    for key in ["WHOAMI", "HOME", "PWD", "SHELL", "PATH"]:
        m = re.search(rf"^{key}\t(.*)$", env_text, flags=re.MULTILINE)
        env_map[key] = m.group(1) if m else ""

    def extract_block(name: str):
        m = re.search(rf"{name}_BEGIN\n(.*?){name}_END", env_text, flags=re.DOTALL)
        return m.group(1).strip() if m else ""

    home_dir = env_map.get("HOME", "")
    candidates = []
    if preferred:
        candidates.append(preferred)
    for cmd in [
        "featureCounts",
        "/usr/bin/featureCounts",
        "/usr/local/bin/featureCounts",
        f"{home_dir}/bin/featureCounts" if home_dir else "",
        "/home/dash/bin/featureCounts",
    ]:
        cmd = (cmd or "").strip()
        if cmd and cmd not in candidates:
            candidates.append(cmd)

    probes = [probe_featurecounts_candidate(c, interactive=True) for c in candidates]

    debug_lines = [
        "featureCounts resolution",
        "=" * 72,
        f"Requested command/path: {preferred if preferred else '<empty>'}",
        f"WSL interactive user: {env_map.get('WHOAMI') or '?'}",
        f"WSL HOME: {env_map.get('HOME') or '<unknown>'}",
        f"WSL PWD: {env_map.get('PWD') or '<unknown>'}",
        f"WSL SHELL: {env_map.get('SHELL') or '<unknown>'}",
        f"WSL PATH: {env_map.get('PATH') or '<empty>'}",
        "Candidates checked:",
    ]
    for c in candidates:
        debug_lines.append(f"  - {c}")
    debug_lines.append("")
    debug_lines.append("WSL command discovery")
    debug_lines.append("-" * 72)
    debug_lines.append("type -a featureCounts:")
    debug_lines.append(_indent_block(extract_block("TYPE_FEATURECOUNTS")))
    debug_lines.append("which featureCounts:")
    debug_lines.append(_indent_block(extract_block("WHICH_FEATURECOUNTS")))
    debug_lines.append("whereis featureCounts:")
    debug_lines.append(_indent_block(extract_block("WHEREIS_FEATURECOUNTS")))
    debug_lines.append("ls -l /usr/bin/featureCounts:")
    debug_lines.append(_indent_block(extract_block("LS_USRBIN")))
    debug_lines.append("")
    debug_lines.append("Probe results:")
    for p in probes:
        debug_lines.append(f"  - {p['candidate']} -> rc={p['rc']}; resolved={p['resolved'] if p['resolved'] else '<none>'}; output={_shorten_one_line(p['combined'])}")
    debug_lines.append("")
    debug_lines.append("Raw per-candidate output")
    debug_lines.append("-" * 72)
    for p in probes:
        debug_lines.append(f"Candidate: {p['candidate']}")
        debug_lines.append(f"Resolved: {p['resolved'] if p['resolved'] else '<none>'}")
        debug_lines.append(f"Return code: {p['rc']}")
        debug_lines.append("STDOUT:")
        debug_lines.append(_indent_block(p['stdout']))
        debug_lines.append("STDERR:")
        debug_lines.append(_indent_block(p['stderr']))
        debug_lines.append("")

    return env_map, probes, "\n".join(debug_lines).rstrip() + "\n"


def select_dir(var, title):
    d = filedialog.askdirectory(title=title)
    if d:
        var.set(d)
        set_status(f"{title} set to: {d}")


def select_file(var, title, patterns):
    f = filedialog.askopenfilename(title=title, filetypes=patterns)
    if f:
        var.set(f)
        set_status(f"{title} set to: {f}")


def select_output_file():
    f = filedialog.asksaveasfilename(
        title="Select Output File",
        defaultextension=".tabtxt",
        filetypes=[("Text Files", "*.tabtxt"), ("TSV Files", "*.tsv"), ("All Files", "*.*")],
    )
    if f:
        output_var.set(f)
        set_status(f"Output file set to: {f}")


def ensure_output_extension(path: str) -> str:
    return path if path.lower().endswith(".tabtxt") else path + ".tabtxt"


def find_bam_files(bam_dir: str):
    return sorted(Path(bam_dir).glob("*.bam"))


def human_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(n)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{n} B"


def validate_scan_inputs():
    bam_dir = bam_var.get().strip()
    if not bam_dir:
        raise ValueError("Missing: BAM folder")
    if not os.path.isdir(bam_dir):
        raise ValueError(f"BAM folder not found: {bam_dir}")

    bam_files = find_bam_files(bam_dir)
    if not bam_files:
        raise ValueError(f"No .bam files found in: {bam_dir}")

    return bam_dir, bam_files


def get_modes_from_choice(choice: int):
    if choice == 3:
        return [(1, MODE_LABELS[1]), (2, MODE_LABELS[2])]
    if choice == 4:
        return [(0, MODE_LABELS[0]), (1, MODE_LABELS[1]), (2, MODE_LABELS[2])]
    return [(choice, MODE_LABELS[choice])]


def resolve_samtools_command():
    home_res = run_wsl_command_capture('printf \'%s\' "$HOME"', interactive=True)
    home_dir = ((home_res.stdout or "") + (("\n" + home_res.stderr) if home_res.stderr else "")).strip()

    candidates = ["samtools", "/usr/bin/samtools", "/usr/local/bin/samtools"]
    if home_dir:
        candidates.append(f"{home_dir}/bin/samtools")
    if "/home/dash/bin/samtools" not in candidates:
        candidates.append("/home/dash/bin/samtools")

    for candidate in candidates:
        q = shlex.quote(candidate)
        if "/" in candidate:
            cmd = f"test -x {q}"
        else:
            cmd = f"command -v {q} >/dev/null 2>&1"
        res = run_wsl_command_capture(cmd, interactive=True)
        if res.returncode == 0:
            return candidate
    return None


def analyze_bam_pairing(bam_file: Path, sample_reads: int = 2000):
    samtools_cmd = resolve_samtools_command()
    if not samtools_cmd:
        raise RuntimeError("samtools was not found in WSL. Install samtools or add it to the WSL PATH before using Scan BAM folder.")

    bam_linux = windows_to_linux_path(str(bam_file))
    cmd = (
        f"{shlex.quote(samtools_cmd)} view {shlex.quote(bam_linux)} 2>/dev/null | "
        f"head -n {int(sample_reads)}"
    )
    res = run_wsl_command_capture(cmd, interactive=True)
    if res.returncode != 0:
        err = ((res.stderr or "") + ("\n" + res.stdout if res.stdout else "")).strip()
        raise RuntimeError(f"Could not inspect BAM file in WSL: {bam_file.name}" + (f"\n{err}" if err else ""))

    total = 0
    paired = 0
    first_mate = 0
    second_mate = 0

    for line in (res.stdout or "").splitlines():
        if not line.strip() or line.startswith("@"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        try:
            flag = int(parts[1])
        except Exception:
            continue
        total += 1
        if flag & 0x1:
            paired += 1
        if flag & 0x40:
            first_mate += 1
        if flag & 0x80:
            second_mate += 1

    unpaired = total - paired

    if total == 0:
        status = "NO_READS_SAMPLED"
    elif paired == total:
        status = "PAIRED"
    elif paired == 0:
        status = "UNPAIRED"
    else:
        status = "MIXED"

    return {
        "bam": bam_file.name,
        "status": status,
        "sampled_reads": total,
        "paired_reads": paired,
        "unpaired_reads": unpaired,
        "first_mate_reads": first_mate,
        "second_mate_reads": second_mate,
        "samtools_cmd": samtools_cmd,
    }


def resolve_featurecounts_command(preferred: str = "", update_field: bool = True):
    env_map, probes, debug_text = gather_wsl_featurecounts_debug(preferred)

    for p in probes:
        if p["looks_valid"]:
            chosen = p["candidate"]
            resolved = p["resolved"] if p["resolved"] else chosen
            if update_field and fc_cmd_var is not None:
                fc_cmd_var.set(chosen)
            debug_text += "\nChosen command/path: " + chosen + "\n"
            debug_text += "Resolved executable: " + resolved + "\n"
            if p["combined"]:
                debug_text += "Version/command output:\n" + _indent_block(p["combined"]) + "\n"
            return chosen, resolved, debug_text

    home_dir = env_map.get("HOME", "") if env_map else ""
    debug_text += "\nNo working featureCounts command was found in WSL interactive shell.\n"
    debug_text += "Examples to try manually:\n"
    debug_text += "  featureCounts\n"
    debug_text += "  /usr/bin/featureCounts\n"
    if home_dir:
        debug_text += f"  {home_dir}/bin/featureCounts\n"
    debug_text += "\nWhy this can happen:\n"
    debug_text += "  - the GUI WSL launch context differs from your terminal\n"
    debug_text += "  - the command runs but returns output in an unexpected way\n"
    debug_text += "  - the executable exists but cannot be executed from this WSL launch context\n"
    return None, None, debug_text




def validate_count_inputs():
    bam_dir, bam_files = validate_scan_inputs()
    requested_fc_cmd = fc_cmd_var.get().strip() if fc_cmd_var is not None else ""
    fc_cmd, resolved_cmd, resolution_text = resolve_featurecounts_command(requested_fc_cmd, update_field=True)
    gtf_file = gtf_var.get().strip()
    out_base = output_var.get().strip()

    missing = []
    if not fc_cmd:
        missing.append("working WSL featureCounts command/path")
    if not gtf_file:
        missing.append("GTF file")
    if not out_base:
        missing.append("output file")
    if missing:
        raise ValueError("Missing: " + ", ".join(missing) + "\n\n" + resolution_text)

    if not os.path.isfile(gtf_file):
        raise ValueError(f"GTF file not found: {gtf_file}")

    try:
        threads = int(threads_var.get())
    except Exception:
        raise ValueError("Threads must be an integer.")
    if threads < 1 or threads > 64:
        raise ValueError("Threads must be between 1 and 64 for featureCounts.")

    minov = minov_var.get().strip()
    if minov:
        try:
            int(minov)
        except Exception:
            raise ValueError("MinOverlap must be empty or an integer.")

    return fc_cmd, (resolved_cmd if resolved_cmd else fc_cmd), ensure_output_extension(out_base), bam_dir, bam_files

def verify_featurecounts_command(show_message: bool = True):
    preferred = fc_cmd_var.get().strip() if fc_cmd_var is not None else ""
    fc_cmd, resolved_cmd, resolution_text = resolve_featurecounts_command(preferred, update_field=True)
    update_report(resolution_text)
    if not fc_cmd:
        set_status("featureCounts verification failed.", is_error=True)
        if show_message:
            messagebox.showerror("featureCounts verification", resolution_text)
        return False, resolution_text

    final_probe = probe_featurecounts_candidate(fc_cmd, interactive=True)
    combined = final_probe["combined"].strip() if final_probe["combined"].strip() else "No output returned."
    report_text = resolution_text + "\nfeatureCounts verification\n" + "=" * 72 + "\n" + combined + "\n"
    update_report(report_text)

    looks_valid = final_probe["looks_valid"]
    if looks_valid:
        set_status("featureCounts verification succeeded.")
        if show_message:
            messagebox.showinfo("featureCounts verification", combined)
    else:
        set_status("featureCounts verification failed.", is_error=True)
        if show_message:
            messagebox.showerror("featureCounts verification", combined)
    return looks_valid, combined


def debug_featurecounts_command(show_message: bool = False):
    preferred = fc_cmd_var.get().strip() if fc_cmd_var is not None else ""
    _env_map, _probes, debug_text = gather_wsl_featurecounts_debug(preferred)
    update_report(debug_text)
    set_status("featureCounts WSL debug report generated.")
    if show_message:
        messagebox.showinfo("featureCounts debug", "Detailed WSL debug report written in the report panel.")
    return debug_text



def write_and_run_featurecounts_script(fc_cmd, resolved_fc_cmd, gtf, out_file, threads, feat, gid_attr, strand_value, flags, bam_dir, bam_files, label, step_index, total_steps, start_time):
    parent = Path(out_file).parent
    parent.mkdir(parents=True, exist_ok=True)

    bam_linux_files = [windows_to_linux_path(str(p)) for p in bam_files]
    if not bam_linux_files:
        raise RuntimeError(f"No BAM files found in {bam_dir}")

    exec_cmd = resolved_fc_cmd if resolved_fc_cmd else fc_cmd
    gtf_linux = gtf if str(gtf).startswith("/") else windows_to_linux_path(gtf)
    out_linux = windows_to_linux_path(out_file)

    cmd = [
        "wsl",
        "--exec",
        exec_cmd,
        "-a", gtf_linux,
        "-o", out_linux,
        "-T", str(threads),
        "-t", feat,
        "-g", gid_attr,
        "-s", str(strand_value),
    ]
    cmd.extend(str(x) for x in flags)
    cmd.extend(bam_linux_files)

    start_percent = ((step_index - 1) / max(1, total_steps)) * 100.0
    end_percent = (step_index / max(1, total_steps)) * 100.0
    progress_text = f"Step {step_index}/{total_steps}: running {label}"
    header_text = (
        f"\n[{label}] featureCounts run\n"
        + "-" * 72
        + f"\nOutput file: {out_file}\n"
        + f"BAM files: {len(bam_linux_files)}\n\n"
    )

    set_status(progress_text)
    run_command_with_live_output(
        cmd=cmd,
        header_text=header_text,
        progress_text=progress_text,
        start_percent=start_percent,
        end_percent=end_percent,
        start_time=start_time,
    )

def parse_featurecounts_file(filename: str, label: str):
    lines = Path(filename).read_text(encoding="utf-8", errors="replace").splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if line and line.split("\t")[0].lower().startswith("geneid"):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError(f"Could not find featureCounts header in: {filename}")

    header = lines[header_idx].split("\t")
    sample_cols = header[6:]
    sample_headers = [f"{label}_{Path(col).name}" for col in sample_cols]

    gene_order = []
    gene_counts = {}
    column_sums = [0] * len(sample_headers)

    for line in lines[header_idx + 1:]:
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        gene_id = parts[0]
        counts = []
        for x in parts[6:6 + len(sample_headers)]:
            try:
                val = int(float(x))
            except Exception:
                val = 0
            counts.append(val)
        gene_order.append(gene_id)
        gene_counts[gene_id] = counts
        for i, val in enumerate(counts):
            column_sums[i] += val

    return {
        "label": label,
        "sample_headers": sample_headers,
        "gene_order": gene_order,
        "gene_counts": gene_counts,
        "column_sums": column_sums,
    }


def format_sum_in_millions(value):
    value_m = float(value) / 1e6
    if value_m > 1:
        return str(int(round(value_m)))
    if value_m == 0:
        return "0"
    return (f"{value_m:.3f}").rstrip("0").rstrip(".")


def compare_results(out_files, base_output):
    cmp_fn = os.path.splitext(base_output)[0] + "_comparison.tabtxt"
    tables = [parse_featurecounts_file(fn, label) for fn, label in out_files]

    ordered_gene_ids = []
    seen = set()
    for table in tables:
        for gene_id in table["gene_order"]:
            if gene_id not in seen:
                seen.add(gene_id)
                ordered_gene_ids.append(gene_id)

    with open(cmp_fn, "w", encoding="utf-8", newline="\n") as out:
        header = ["GeneID"]
        for table in tables:
            header.extend(table["sample_headers"])
        out.write("\t".join(header) + "\n")

        sum_row = ["SUM"]
        for table in tables:
            sum_row.extend(format_sum_in_millions(x) for x in table["column_sums"])
        out.write("\t".join(sum_row) + "\n")

        for gene_id in ordered_gene_ids:
            row = [gene_id]
            for table in tables:
                counts = table["gene_counts"].get(gene_id, [0] * len(table["sample_headers"]))
                row.extend(str(x) for x in counts)
            out.write("\t".join(row) + "\n")

    return cmp_fn

def update_report(text: str):
    if report_box is None:
        return
    report_box.configure(state="normal")
    report_box.delete("1.0", tk.END)
    report_box.insert(tk.END, text)
    report_box.see(tk.END)
    report_box.configure(state="disabled")


def clear_report():
    update_report("")


def append_report(text: str):
    if report_box is None:
        return
    report_box.configure(state="normal")
    report_box.insert(tk.END, text)
    report_box.see(tk.END)
    report_box.configure(state="disabled")
    try:
        root.update_idletasks()
    except Exception:
        pass


def _stream_reader(pipe, output_queue):
    try:
        for line in iter(pipe.readline, ""):
            output_queue.put(line)
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def run_command_with_live_output(cmd, header_text: str, progress_text: str, start_percent: float, end_percent: float, start_time: float):
    append_report(header_text)
    append_report("Command argv (single line):\n")
    append_report("    " + " ".join(shlex.quote(str(x)) for x in cmd) + "\n\n")

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    q = queue.Queue()
    reader = threading.Thread(target=_stream_reader, args=(process.stdout, q), daemon=True)
    reader.start()

    captured = []
    set_progress_ui(value=start_percent, text=progress_text, elapsed=f"Elapsed: {format_elapsed(time.time() - start_time)}", indeterminate=True)

    while True:
        while True:
            try:
                line = q.get_nowait()
            except queue.Empty:
                break
            captured.append(line)
            append_report(line if line.endswith("\n") else line + "\n")

        if process.poll() is not None and q.empty():
            break

        set_progress_ui(
            text=progress_text,
            elapsed=f"Elapsed: {format_elapsed(time.time() - start_time)}",
            indeterminate=True,
        )
        try:
            root.update()
        except Exception:
            pass
        time.sleep(0.05)

    reader.join(timeout=0.2)

    while True:
        try:
            line = q.get_nowait()
        except queue.Empty:
            break
        captured.append(line)
        append_report(line if line.endswith("\n") else line + "\n")

    return_code = process.wait()
    set_progress_ui(value=end_percent, text=progress_text, elapsed=f"Elapsed: {format_elapsed(time.time() - start_time)}", indeterminate=False)

    if return_code != 0:
        output_text = "".join(captured).strip()
        debug_lines = [
            "featureCounts execution failed",
            "=" * 72,
            f"Return code: {return_code}",
            "Command argv (single line):",
            "    " + " ".join(shlex.quote(str(x)) for x in cmd),
            "Command argv (numbered):",
            _indent_block("\n".join(f"[{i}] {str(x)}" for i, x in enumerate(cmd))),
            "Captured output:",
            _indent_block(output_text),
        ]
        raise RuntimeError("\n".join(debug_lines))

    append_report("\n")


def scan_bam_folder():
    try:
        bam_dir, bam_files = validate_scan_inputs()
        scan_button.configure(state="disabled")
        run_button.configure(state="disabled")
        verify_button.configure(state="disabled")
        debug_button.configure(state="disabled")
        clear_report()
        start_time = time.time()
        total_bams = len(bam_files)
        set_status("Scanning BAM files for paired/unpaired reads ...")
        set_progress_ui(value=0, text=f"Scanning BAM 0/{total_bams}", elapsed="Elapsed: 00:00", indeterminate=False)

        pairing_results = []
        samtools_cmd = None
        append_report("BAM folder scan (live)\n")
        append_report("=" * 72 + "\n")
        append_report(f"BAM folder: {bam_dir}\n")
        append_report(f"Total BAM files: {total_bams}\n\n")

        for idx, bam in enumerate(bam_files, start=1):
            step_text = f"Scanning BAM {idx}/{total_bams}: {bam.name}"
            set_status(step_text)
            set_progress_ui(
                value=((idx - 1) / max(1, total_bams)) * 100.0,
                text=step_text,
                elapsed=f"Elapsed: {format_elapsed(time.time() - start_time)}",
                indeterminate=False,
            )
            result = analyze_bam_pairing(bam)
            pairing_results.append(result)
            if samtools_cmd is None:
                samtools_cmd = result["samtools_cmd"]
            append_report(
                f"{result['bam']}\t{result['status']}\tsampled={result['sampled_reads']}\tpaired={result['paired_reads']}\tunpaired={result['unpaired_reads']}\tR1={result['first_mate_reads']}\tR2={result['second_mate_reads']}\n"
            )
            set_progress_ui(
                value=(idx / max(1, total_bams)) * 100.0,
                text=step_text,
                elapsed=f"Elapsed: {format_elapsed(time.time() - start_time)}",
                indeterminate=False,
            )

        paired_bams = sum(1 for x in pairing_results if x["status"] == "PAIRED")
        unpaired_bams = sum(1 for x in pairing_results if x["status"] == "UNPAIRED")
        mixed_bams = sum(1 for x in pairing_results if x["status"] == "MIXED")
        empty_bams = sum(1 for x in pairing_results if x["status"] == "NO_READS_SAMPLED")

        summary_lines = [
            "\nSummary",
            "-" * 72,
            f"samtools used in WSL: {samtools_cmd if samtools_cmd else '<not found>'}",
            f"PAIRED BAMs: {paired_bams}",
            f"UNPAIRED BAMs: {unpaired_bams}",
            f"MIXED BAMs: {mixed_bams}",
            f"BAMs with no sampled reads: {empty_bams}",
            "",
            "Each BAM is classified from the read flags inside the BAM file.",
            "Status is based on sampled alignments read with samtools view.",
            "",
        ]
        append_report("\n".join(summary_lines))
        set_progress_ui(value=100, text="Scan finished.", elapsed=f"Elapsed: {format_elapsed(time.time() - start_time)}", indeterminate=False)
        set_status(f"Scan finished. {total_bams} BAM files analyzed for paired/unpaired reads.")
    except subprocess.CalledProcessError as e:
        msg = f"Scan failed with return code {e.returncode}."
        append_report(msg + "\n")
        set_progress_ui(text="Scan failed.", elapsed="Elapsed: 00:00", indeterminate=False)
        set_status(msg, is_error=True)
        messagebox.showerror("Error", msg)
    except Exception as e:
        append_report(str(e) + "\n")
        set_progress_ui(text="Scan failed.", elapsed="Elapsed: 00:00", indeterminate=False)
        set_status(str(e), is_error=True)
        messagebox.showerror("Error", str(e))
    finally:
        scan_button.configure(state="normal")
        run_button.configure(state="normal")
        verify_button.configure(state="normal")
        debug_button.configure(state="normal")


def run_featurecounts():

    try:
        fc_cmd, resolved_fc_cmd, out_base, bam_dir, bam_files = validate_count_inputs()
        gtf_file = gtf_var.get().strip()
        strand_choice = int(strand_var.get())
        threads = int(threads_var.get())
        feat = feature_type_var.get().strip()
        gid_attr = gene_id_var.get().strip()
        paired = int(paired_var.get())
        multi_map = int(multimap_var.get())
        overlap = int(overlap_var.get())
        minov = minov_var.get().strip()

        run_button.configure(state="disabled")
        scan_button.configure(state="disabled")
        verify_button.configure(state="disabled")
        debug_button.configure(state="disabled")

        clear_report()
        start_time = time.time()
        modes = get_modes_from_choice(strand_choice)
        total_steps = 1 + len(modes) + (1 if len(modes) > 1 else 0)
        set_progress_ui(value=0, text=f"Step 1/{total_steps}: verifying featureCounts", elapsed="Elapsed: 00:00", indeterminate=False)
        append_report("Preparing featureCounts run...\n")
        append_report("=" * 72 + "\n")

        ok, verify_text = verify_featurecounts_command(show_message=False)
        if not ok:
            raise RuntimeError("featureCounts verification failed before counting.\n\n" + verify_text)

        set_progress_ui(
            value=(1 / max(1, total_steps)) * 100.0,
            text=f"Step 1/{total_steps}: verification done",
            elapsed=f"Elapsed: {format_elapsed(time.time() - start_time)}",
            indeterminate=False,
        )

        gtf = windows_to_linux_path(gtf_file)

        flags = []
        if paired:
            flags.append("-p")
        if multi_map:
            flags.append("-M")
        if overlap:
            flags.append("-O")
        if minov:
            flags += ["--minOverlap", str(int(minov))]

        out_files = []

        for idx, (sval, label) in enumerate(modes, start=1):
            this_out = out_base.replace(".tabtxt", f"_{label}.tabtxt")
            write_and_run_featurecounts_script(
                fc_cmd=fc_cmd,
                resolved_fc_cmd=resolved_fc_cmd,
                gtf=gtf,
                out_file=this_out,
                threads=threads,
                feat=feat,
                gid_attr=gid_attr,
                strand_value=sval,
                flags=flags,
                bam_dir=bam_dir,
                bam_files=bam_files,
                label=label,
                step_index=1 + idx,
                total_steps=total_steps,
                start_time=start_time,
            )
            out_files.append((this_out, label))

        if len(out_files) > 1:
            compare_step = total_steps
            set_status("Creating comparison file ...")
            set_progress_ui(
                value=((compare_step - 1) / max(1, total_steps)) * 100.0,
                text=f"Step {compare_step}/{total_steps}: creating comparison file",
                elapsed=f"Elapsed: {format_elapsed(time.time() - start_time)}",
                indeterminate=False,
            )
            append_report("Creating comparison file...\n")
            cmp_fn = compare_results(out_files, out_base)
            append_report(f"Comparison file created: {cmp_fn}\n")
            set_progress_ui(value=100, text="Finished.", elapsed=f"Elapsed: {format_elapsed(time.time() - start_time)}", indeterminate=False)
            set_status("Done. Comparison file created: " + cmp_fn)
            append_report("\nfeatureCounts run completed successfully.\n")
            append_report("Outputs:\n" + "\n".join(x[0] for x in out_files) + f"\n\nComparison:\n{cmp_fn}\n")
            messagebox.showinfo(
                "Done",
                "featureCounts finished successfully.\n\n"
                + "Outputs:\n"
                + "\n".join(x[0] for x in out_files)
                + f"\n\nComparison:\n{cmp_fn}",
            )
        else:
            set_progress_ui(value=100, text="Finished.", elapsed=f"Elapsed: {format_elapsed(time.time() - start_time)}", indeterminate=False)
            append_report(f"featureCounts run completed successfully.\nOutput:\n{out_files[0][0]}\n")
            set_status("Done. featureCounts output created: " + out_files[0][0])
            messagebox.showinfo("Done", f"featureCounts finished successfully.\n\nOutput:\n{out_files[0][0]}")

    except subprocess.CalledProcessError as e:
        msg = f"featureCounts failed with return code {e.returncode}."
        append_report(msg + "\n")
        set_progress_ui(text="Run failed.", indeterminate=False)
        set_status(msg, is_error=True)
        messagebox.showerror("Error", msg)
    except Exception as e:
        append_report(str(e) + "\n")
        set_progress_ui(text="Run failed.", indeterminate=False)
        set_status(str(e), is_error=True)
        messagebox.showerror("Error", str(e))
    finally:
        run_button.configure(state="normal")
        scan_button.configure(state="normal")
        verify_button.configure(state="normal")
        debug_button.configure(state="normal")

def make_path_row(parent, row, label_text, text_var, browse_cmd, button_text="Browse", label_style="Field.TLabel"):
    ttk.Label(parent, text=label_text, style=label_style).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=6)
    entry = ttk.Entry(parent, textvariable=text_var)
    entry.grid(row=row, column=1, sticky="ew", pady=6)
    ttk.Button(parent, text=button_text, command=browse_cmd, style="Soft.TButton").grid(row=row, column=2, sticky="ew", padx=(10, 0), pady=6)
    return entry




def copy_report_to_clipboard():
    if report_box is None:
        return
    text = report_box.get("1.0", tk.END)
    root.clipboard_clear()
    root.clipboard_append(text)
    set_status("Report copied to clipboard.")

def build_gui():
    global root
    global status_var, status_label
    global fc_cmd_var, bam_var, gtf_var, output_var
    global strand_var, threads_var, feature_type_var, gene_id_var
    global paired_var, multimap_var, overlap_var, minov_var
    global run_button, scan_button, verify_button, debug_button, report_box, progress_bar, progress_var, progress_text_var, elapsed_var, strand_combo

    root = tk.Tk()
    root.title("featureCounts GUI")
    root.geometry("1160x780")
    root.minsize(1000, 700)
    root.configure(bg=PASTEL["app_bg"])

    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure("TFrame", background=PASTEL["app_bg"])
    style.configure("Header.TFrame", background=PASTEL["header_bg"])
    style.configure("CardBlue.TLabelframe", background=PASTEL["panel_bg"], borderwidth=1, relief="solid")
    style.configure("CardBlue.TLabelframe.Label", background=PASTEL["panel_bg"], foreground=PASTEL["title_fg"], font=("Segoe UI", 10, "bold"))
    style.configure("CardGreen.TLabelframe", background=PASTEL["panel2_bg"], borderwidth=1, relief="solid")
    style.configure("CardGreen.TLabelframe.Label", background=PASTEL["panel2_bg"], foreground=PASTEL["title_fg"], font=("Segoe UI", 10, "bold"))
    style.configure("CardPeach.TLabelframe", background=PASTEL["panel3_bg"], borderwidth=1, relief="solid")
    style.configure("CardPeach.TLabelframe.Label", background=PASTEL["panel3_bg"], foreground=PASTEL["title_fg"], font=("Segoe UI", 10, "bold"))

    style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), background=PASTEL["header_bg"], foreground=PASTEL["title_fg"])
    style.configure("SubTitle.TLabel", font=("Segoe UI", 10), background=PASTEL["app_bg"], foreground=PASTEL["text_fg"])
    style.configure("HeaderSub.TLabel", font=("Segoe UI", 10), background=PASTEL["header_bg"], foreground=PASTEL["text_fg"])
    style.configure("Field.TLabel", font=("Segoe UI", 10), background=PASTEL["panel_bg"], foreground=PASTEL["text_fg"])
    style.configure("FieldGreen.TLabel", font=("Segoe UI", 10), background=PASTEL["panel2_bg"], foreground=PASTEL["text_fg"])
    style.configure("FieldPeach.TLabel", font=("Segoe UI", 10), background=PASTEL["panel3_bg"], foreground=PASTEL["text_fg"])

    style.configure("TEntry", fieldbackground=PASTEL["entry_bg"], padding=6)
    style.configure("TCombobox", fieldbackground=PASTEL["entry_bg"], padding=5)
    style.configure("TSpinbox", fieldbackground=PASTEL["entry_bg"], padding=4)
    style.configure("TRadiobutton", background=PASTEL["panel2_bg"], foreground=PASTEL["text_fg"])
    style.configure("TCheckbutton", background=PASTEL["panel3_bg"], foreground=PASTEL["text_fg"])

    style.configure("Soft.TButton", font=("Segoe UI", 10), padding=7, background=PASTEL["button_bg"], foreground="#355070", borderwidth=1)
    style.map("Soft.TButton", background=[("active", PASTEL["button_active"]), ("pressed", PASTEL["button_active"])])

    style.configure("Run.TButton", font=("Segoe UI", 11, "bold"), padding=9, background=PASTEL["run_bg"], foreground="#3b5f4a", borderwidth=1)
    style.map("Run.TButton", background=[("active", PASTEL["run_active"]), ("pressed", PASTEL["run_active"])])

    style.configure("Scan.TButton", font=("Segoe UI", 11, "bold"), padding=9, background=PASTEL["scan_bg"], foreground="#7a5c30", borderwidth=1)
    style.map("Scan.TButton", background=[("active", PASTEL["scan_active"]), ("pressed", PASTEL["scan_active"])])

    style.configure("Verify.TButton", font=("Segoe UI", 11, "bold"), padding=9, background=PASTEL["verify_bg"], foreground="#5c4a7a", borderwidth=1)
    style.map("Verify.TButton", background=[("active", PASTEL["verify_active"]), ("pressed", PASTEL["verify_active"])])
    style.configure("Debug.TButton", font=("Segoe UI", 11, "bold"), padding=9, background="#ffe3ea", foreground="#7a4058", borderwidth=1)
    style.map("Debug.TButton", background=[("active", "#ffd0dc"), ("pressed", "#ffd0dc")])

    main = ttk.Frame(root, padding=16)
    main.grid(row=0, column=0, sticky="nsew")
    root.grid_rowconfigure(0, weight=1)
    root.grid_columnconfigure(0, weight=1)
    main.grid_rowconfigure(2, weight=1)
    main.grid_columnconfigure(0, weight=1)

    header = ttk.Frame(main, style="Header.TFrame", padding=14)
    header.grid(row=0, column=0, sticky="ew")
    header.grid_columnconfigure(0, weight=1)
    ttk.Label(header, text="featureCounts GUI", style="Title.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Label(
        header,
        text="Uses the WSL featureCounts command directly, verifies the installed version, scans BAM folders, and can compare strand modes.",
        style="HeaderSub.TLabel",
        wraplength=1000,
        justify="left",
    ).grid(row=1, column=0, sticky="w", pady=(4, 0))

    ttk.Label(main, text="Enter the WSL command for featureCounts (for example: featureCounts or /home/dash/bin/featureCounts), then verify it before running.", style="SubTitle.TLabel", wraplength=1040, justify="left").grid(row=1, column=0, sticky="w", pady=(10, 12))

    content = ttk.Frame(main)
    content.grid(row=2, column=0, sticky="nsew")
    content.grid_rowconfigure(0, weight=1)
    content.grid_columnconfigure(0, weight=11)
    content.grid_columnconfigure(1, weight=10)

    left = ttk.Frame(content)
    right = ttk.Frame(content)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    right.grid(row=0, column=1, sticky="nsew")
    left.grid_columnconfigure(0, weight=1)
    left.grid_rowconfigure(2, weight=1)
    right.grid_columnconfigure(0, weight=1)
    right.grid_rowconfigure(2, weight=1)

    paths_frame = ttk.LabelFrame(left, text="Input / Output", style="CardBlue.TLabelframe", padding=14)
    paths_frame.grid(row=0, column=0, sticky="ew")
    paths_frame.grid_columnconfigure(1, weight=1)

    fc_cmd_var = StringVar(value="featureCounts")
    bam_var = StringVar()
    gtf_var = StringVar()
    output_var = StringVar()

    ttk.Label(paths_frame, text="WSL featureCounts command/path", style="Field.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=6)
    ttk.Entry(paths_frame, textvariable=fc_cmd_var).grid(row=0, column=1, columnspan=2, sticky="ew", pady=6)

    make_path_row(paths_frame, 1, "BAM folder", bam_var, lambda: select_dir(bam_var, "Select BAM Folder"), "Select")
    make_path_row(paths_frame, 2, "Genome GTF", gtf_var, lambda: select_file(gtf_var, "Select GTF", [("GTF files", "*.gtf"), ("All files", "*.*")]), "Select")
    make_path_row(paths_frame, 3, "Output base file", output_var, select_output_file, "Browse")

    opts_frame = ttk.LabelFrame(left, text="Counting Options", style="CardGreen.TLabelframe", padding=14)
    opts_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
    opts_frame.grid_columnconfigure(1, weight=1)
    opts_frame.grid_columnconfigure(3, weight=1)

    strand_var = IntVar(value=3)
    threads_var = IntVar(value=1)
    feature_type_var = StringVar(value="exon")
    gene_id_var = StringVar(value="gene_id")
    paired_var = IntVar(value=1)
    multimap_var = IntVar(value=0)
    overlap_var = IntVar(value=0)
    minov_var = StringVar(value="")

    ttk.Label(opts_frame, text="Strand mode", style="FieldGreen.TLabel").grid(row=0, column=0, sticky="w", pady=6, padx=(0, 10))
    strand_combo = ttk.Combobox(opts_frame, state="readonly", values=[MODE_CHOICES[i] for i in range(len(MODE_CHOICES))])
    strand_combo.current(3)
    strand_combo.grid(row=0, column=1, columnspan=3, sticky="ew", pady=6)

    def sync_strand_choice(event=None):
        selected_text = strand_combo.get()
        for k, v in MODE_CHOICES.items():
            if v == selected_text:
                strand_var.set(k)
                break

    strand_combo.bind("<<ComboboxSelected>>", sync_strand_choice)
    sync_strand_choice()

    ttk.Label(opts_frame, text="Threads", style="FieldGreen.TLabel").grid(row=1, column=0, sticky="w", pady=6, padx=(0, 10))
    ttk.Spinbox(opts_frame, from_=1, to=64, textvariable=threads_var, width=10).grid(row=1, column=1, sticky="w", pady=6)

    ttk.Label(opts_frame, text="Feature type (-t)", style="FieldGreen.TLabel").grid(row=1, column=2, sticky="w", pady=6, padx=(14, 10))
    ttk.Entry(opts_frame, textvariable=feature_type_var).grid(row=1, column=3, sticky="ew", pady=6)

    ttk.Label(opts_frame, text="Group-by attribute (-g)", style="FieldGreen.TLabel").grid(row=2, column=0, sticky="w", pady=6, padx=(0, 10))
    ttk.Entry(opts_frame, textvariable=gene_id_var).grid(row=2, column=1, sticky="ew", pady=6)

    ttk.Label(opts_frame, text="Paired-end reads", style="FieldGreen.TLabel").grid(row=2, column=2, sticky="w", pady=6, padx=(14, 10))
    paired_box = ttk.Frame(opts_frame)
    paired_box.grid(row=2, column=3, sticky="w", pady=6)
    ttk.Radiobutton(paired_box, text="No", variable=paired_var, value=0).grid(row=0, column=0, padx=(0, 10))
    ttk.Radiobutton(paired_box, text="Yes", variable=paired_var, value=1).grid(row=0, column=1)

    notes_frame = ttk.LabelFrame(left, text="Notes", style="CardPeach.TLabelframe", padding=14)
    notes_frame.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
    notes_frame.grid_columnconfigure(0, weight=1)
    notes_text = (
        "• Use the WSL command exactly as you would type it in WSL.\n"
        "• Verification is run in an interactive WSL shell so it matches your manual terminal use more closely.\n"
        "• Scan BAM folder analyzes the read flags inside each BAM to classify it as paired, unpaired, mixed, or empty.\n"
        "• The comparison file has a single GeneID column and the SUM_M row is written immediately under the column titles in millions of reads."
    )
    ttk.Label(notes_frame, text=notes_text, style="FieldPeach.TLabel", justify="left", wraplength=500).grid(row=0, column=0, sticky="nw")

    adv_frame = ttk.LabelFrame(right, text="Advanced Options", style="CardPeach.TLabelframe", padding=14)
    adv_frame.grid(row=0, column=0, sticky="ew")
    adv_frame.grid_columnconfigure(0, weight=1)

    ttk.Checkbutton(
        adv_frame,
        text="-M  Allow one read to be counted at multiple mapping loci",
        variable=multimap_var,
    ).grid(row=0, column=0, sticky="w", pady=6)

    ttk.Checkbutton(
        adv_frame,
        text="-O  Allow one read to overlap multiple genes/features",
        variable=overlap_var,
    ).grid(row=1, column=0, sticky="w", pady=6)

    minov_row = ttk.Frame(adv_frame)
    minov_row.grid(row=2, column=0, sticky="ew", pady=8)
    minov_row.grid_columnconfigure(1, weight=1)
    ttk.Label(minov_row, text="--minOverlap", style="FieldPeach.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 10))
    ttk.Entry(minov_row, textvariable=minov_var).grid(row=0, column=1, sticky="ew")

    progress_frame = ttk.LabelFrame(right, text="Progress", style="CardGreen.TLabelframe", padding=14)
    progress_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
    progress_frame.grid_columnconfigure(0, weight=1)

    progress_var = tk.DoubleVar(value=0.0)
    progress_text_var = StringVar(value="Ready.")
    elapsed_var = StringVar(value="Elapsed: 00:00")

    ttk.Label(progress_frame, textvariable=progress_text_var, style="FieldGreen.TLabel", wraplength=470, justify="left").grid(row=0, column=0, sticky="w")
    progress_bar = ttk.Progressbar(progress_frame, variable=progress_var, maximum=100, mode="determinate")
    progress_bar.grid(row=1, column=0, sticky="ew", pady=(8, 6))
    ttk.Label(progress_frame, textvariable=elapsed_var, style="FieldGreen.TLabel").grid(row=2, column=0, sticky="w")

    report_frame = ttk.LabelFrame(right, text="Live Output / Report", style="CardBlue.TLabelframe", padding=14)
    report_frame.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
    report_frame.grid_columnconfigure(0, weight=1)
    report_frame.grid_rowconfigure(1, weight=1)

    ttk.Label(report_frame, text="Use Verify featureCounts for a quick test, Debug featureCounts for raw WSL diagnostics, and Scan BAM folder to inspect paired/unpaired read flags inside each BAM.", style="Field.TLabel", wraplength=470, justify="left").grid(row=0, column=0, sticky="w", pady=(0, 10))

    report_box = ScrolledText(
        report_frame,
        wrap="word",
        height=18,
        font=("Consolas", 9),
        bg="#fffdfd",
        fg="#4b5563",
        insertbackground="#4b5563",
        relief="flat",
        borderwidth=1,
        padx=10,
        pady=10,
    )
    report_box.grid(row=1, column=0, sticky="nsew")
    report_box.insert("1.0", "Live output and reports will appear here.\n")
    report_box.configure(state="disabled")

    bottom = ttk.Frame(main)
    bottom.grid(row=3, column=0, sticky="ew", pady=(14, 0))
    bottom.grid_columnconfigure(0, weight=1)
    bottom.grid_columnconfigure(1, weight=1)
    bottom.grid_columnconfigure(2, weight=1)
    bottom.grid_columnconfigure(3, weight=1)
    bottom.grid_columnconfigure(4, weight=1)

    run_button = ttk.Button(bottom, text="Run featureCounts", command=run_featurecounts, style="Run.TButton")
    run_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

    scan_button = ttk.Button(bottom, text="Scan BAM folder", command=scan_bam_folder, style="Scan.TButton")
    scan_button.grid(row=0, column=1, sticky="ew", padx=6)

    verify_button = ttk.Button(bottom, text="Verify featureCounts", command=verify_featurecounts_command, style="Verify.TButton")
    verify_button.grid(row=0, column=2, sticky="ew", padx=6)

    debug_button = ttk.Button(bottom, text="Debug featureCounts", command=debug_featurecounts_command, style="Debug.TButton")
    debug_button.grid(row=0, column=3, sticky="ew", padx=6)

    ttk.Button(bottom, text="Copy report", command=copy_report_to_clipboard, style="Soft.TButton").grid(row=0, column=4, sticky="ew", padx=(6, 0))

    reset_progress_ui("Ready.")

    status_var = StringVar(value="Ready.")
    status_label = ttk.Label(main, textvariable=status_var, style="SubTitle.TLabel", wraplength=1040, justify="left")
    status_label.grid(row=4, column=0, sticky="ew", pady=(10, 0))

    try:
        fc_cmd, resolved_cmd, resolution_text = resolve_featurecounts_command(fc_cmd_var.get(), update_field=True)
        update_report(resolution_text)
        if fc_cmd:
            set_status("featureCounts auto-detected in WSL interactive shell.")
        else:
            set_status("featureCounts was not auto-detected; try Verify featureCounts.", is_error=True)
    except Exception as e:
        update_report(str(e) + "\n")
        set_status("Could not auto-detect featureCounts at startup.", is_error=True)

    return root


if __name__ == "__main__":
    app = build_gui()
    app.mainloop()
