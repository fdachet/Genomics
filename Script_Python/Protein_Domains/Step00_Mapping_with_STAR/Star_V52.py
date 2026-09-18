# Star_V51_FIFO_FIX.py
# Fixes STAR FIFO error when output directory is on /mnt/c (NTFS):
# - Automatically sets --outTmpDir to a Linux path (/tmp/...) per sample when output is under /mnt/*
# - Cleans the temp dir after run
#
# Based on the user's current script content. :contentReference[oaicite:1]{index=1}

import tkinter as tk
from tkinter import filedialog, messagebox, Toplevel
import tkinter.ttk as ttk
import subprocess
import threading
import os
import glob
import re
import gzip
import math
import shlex
import time

detected_samples = {}

# global summary state for multi-mapping runs
total_star_jobs = 0
completed_star_jobs = 0
failed_star_jobs = 0
star_jobs_start_time = None


def browse_file(entry_field):
    filename = filedialog.askopenfilename()
    if filename:
        entry_field.delete(0, tk.END)
        entry_field.insert(0, filename)


def browse_files(entry_field):
    filenames = filedialog.askopenfilenames()
    if filenames:
        entry_field.delete(0, tk.END)
        entry_field.insert(0, ' '.join(filenames))


def browse_directory(entry_field):
    directory = filedialog.askdirectory()
    if directory:
        entry_field.delete(0, tk.END)
        entry_field.insert(0, directory)


def convert_path_to_wsl(win_path):
    # Convert Windows path to WSL path
    paths = win_path.split()
    wsl_paths = []
    for path in paths:
        if ':' in path:
            drive, path_part = path.split(':', 1)
            path = '/mnt/' + drive.lower() + path_part.replace('\\', '/')
        else:
            path = path.replace('\\', '/')
        wsl_paths.append(path)
    return ' '.join(wsl_paths)


def is_compressed_fastq(path):
    lower = path.lower()
    return lower.endswith(('.gz', '.gzip', '.bz2', '.bz'))


def validate_inputs():
    operation_mode = mode_var.get()
    threads_per_mapping = threads_per_mapping_entry.get()
    num_parallel_mappings = num_parallel_mappings_entry.get()
    limit_bam_sort_ram_gb = limit_bam_sort_ram_entry.get().strip()

    if not threads_per_mapping.isdigit() or int(threads_per_mapping) < 1:
        messagebox.showerror("Input Error", "Threads per Mapping must be a positive integer.")
        return False

    if not num_parallel_mappings.isdigit() or int(num_parallel_mappings) < 0:
        messagebox.showerror("Input Error", "Number of Parallel Mappings must be a non-negative integer.")
        return False

    if limit_bam_sort_ram_gb and not limit_bam_sort_ram_gb.isdigit():
        messagebox.showerror("Input Error", "Limit BAM sort RAM (GB) must be a positive integer.")
        return False

    if operation_mode == "alignment":
        if not reads_dir_entry.get():
            messagebox.showerror("Input Error", "Reads Directory is required.")
            return False
        if not samples_listbox.size():
            messagebox.showerror("Input Error", "No samples detected. Please scan the reads directory.")
            return False
        if not samples_listbox.curselection():
            messagebox.showerror("Input Error", "No samples selected.")
            return False
        if not ref_entry.get():
            messagebox.showerror("Input Error", "Reference Genome Directory is required.")
            return False
        if not output_entry.get():
            messagebox.showerror("Input Error", "Output Directory is required.")
            return False

        if only_unmapped_var.get() and not save_unmapped_var.get():
            messagebox.showerror("Input Error", "To discard mapped alignments you must save unmapped reads.")
            return False

    elif operation_mode == "genome_index":
        if not genome_fasta_entry.get():
            messagebox.showerror("Input Error", "Genome FASTA Files are required.")
            return False
        if not output_entry.get():
            messagebox.showerror("Input Error", "Output Directory is required.")
            return False
    else:
        messagebox.showerror("Mode Error", "Unknown operation mode selected.")
        return False
    return True


def toggle_mode():
    if mode_var.get() == "alignment":
        reads_dir_entry.config(state='normal')
        browse_reads_dir_button.config(state='normal')
        scan_reads_button.config(state='normal')
        paired_checkbox.config(state='normal')
        samples_listbox.config(state='normal')
        ref_entry.config(state='normal')
        browse_ref_button.config(state='normal')

        if only_unmapped_var.get():
            samtype_optionmenu.config(state='disabled')
        else:
            samtype_optionmenu.config(state='normal')

        advanced_entry.config(state='normal')
        genome_fasta_entry.config(state='disabled')
        browse_genome_fasta_button.config(state='disabled')
        annotation_gtf_entry.config(state='disabled')
        browse_annotation_gtf_button.config(state='disabled')
        select_all_button.config(state='normal')
        two_pass_checkbox.config(state='normal')
        limit_bam_sort_ram_entry.config(state='normal')
        genome_load_checkbox.config(state='normal')
        mapping_accuracy_optionmenu.config(state='normal')
        genome_mode_optionmenu.config(state='normal')
        save_unmapped_checkbox.config(state='normal')
        unmapped_dir_entry.config(state='normal')
        unmapped_browse_button.config(state='normal')
        only_unmapped_checkbox.config(state='normal')
        create_bai_checkbox.config(state='normal')
    else:
        reads_dir_entry.config(state='disabled')
        browse_reads_dir_button.config(state='disabled')
        scan_reads_button.config(state='disabled')
        paired_checkbox.config(state='disabled')
        samples_listbox.config(state='disabled')
        ref_entry.config(state='disabled')
        browse_ref_button.config(state='disabled')
        samtype_optionmenu.config(state='disabled')
        advanced_entry.config(state='normal')
        genome_fasta_entry.config(state='normal')
        browse_genome_fasta_button.config(state='normal')
        annotation_gtf_entry.config(state='normal')
        browse_annotation_gtf_button.config(state='normal')
        select_all_button.config(state='disabled')
        two_pass_checkbox.config(state='disabled')
        limit_bam_sort_ram_entry.config(state='disabled')
        genome_load_checkbox.config(state='disabled')
        mapping_accuracy_optionmenu.config(state='disabled')
        genome_mode_optionmenu.config(state='disabled')
        save_unmapped_checkbox.config(state='disabled')
        unmapped_dir_entry.config(state='disabled')
        unmapped_browse_button.config(state='disabled')
        only_unmapped_checkbox.config(state='disabled')
        create_bai_checkbox.config(state='disabled')


def toggle_only_unmapped():
    if only_unmapped_var.get():
        save_unmapped_var.set(True)
        save_unmapped_checkbox.config(state='normal')
        samtype_optionmenu.config(state='disabled')
    else:
        if mode_var.get() == "alignment":
            samtype_optionmenu.config(state='normal')


def scan_reads_directory():
    reads_dir = reads_dir_entry.get()
    if not os.path.isdir(reads_dir):
        messagebox.showerror("Input Error", f"Reads Directory does not exist: {reads_dir}")
        return

    fastq_files = (
        glob.glob(os.path.join(reads_dir, '*.fastq*')) +
        glob.glob(os.path.join(reads_dir, '*.fq*')) +
        glob.glob(os.path.join(reads_dir, '*mate1')) +
        glob.glob(os.path.join(reads_dir, '*mate2'))
    )
    samples = {}
    paired = paired_var.get()

    for file in fastq_files:
        basename = os.path.basename(file)
        compressed = is_compressed_fastq(file)
        if paired:
            if re.search(r'R1', basename, re.IGNORECASE):
                sample_name = re.sub(r'R1.*', '', basename, flags=re.IGNORECASE)
                if sample_name not in samples:
                    samples[sample_name] = {'R1': '', 'R2': '', 'compressed': False}
                samples[sample_name]['R1'] = file
                if compressed:
                    samples[sample_name]['compressed'] = True
            elif re.search(r'R2', basename, re.IGNORECASE):
                sample_name = re.sub(r'R2.*', '', basename, flags=re.IGNORECASE)
                if sample_name not in samples:
                    samples[sample_name] = {'R1': '', 'R2': '', 'compressed': False}
                samples[sample_name]['R2'] = file
                if compressed:
                    samples[sample_name]['compressed'] = True
            else:
                sample_name = basename
                samples[sample_name] = {'single': file, 'compressed': compressed}
        else:
            sample_name = basename
            samples[sample_name] = {'single': file, 'compressed': compressed}

    samples_listbox.delete(0, tk.END)
    paired_ok = 0
    issues = 0
    for sample_name in sorted(samples.keys()):
        compressed = samples[sample_name].get('compressed', False)
        comp_txt = "compressed (zcat)" if compressed else "uncompressed"
        if paired:
            r1 = samples[sample_name].get('R1')
            r2 = samples[sample_name].get('R2')
            if r1 and r2:
                status = "paired OK"
                paired_ok += 1
            else:
                miss = []
                if not r1:
                    miss.append('R1')
                if not r2:
                    miss.append('R2')
                if 'single' in samples[sample_name]:
                    status = "single-end (no explicit R1/R2)"
                else:
                    status = f"paired, missing {','.join(miss)}"
                    issues += 1
        else:
            status = "single-end"

        label = f"{sample_name} [{status}; {comp_txt}]"
        samples_listbox.insert(tk.END, label)

    total = len(samples)
    if paired:
        sample_summary_label.config(text=f"Samples: {total} (paired OK: {paired_ok} / issues: {issues})")
    else:
        sample_summary_label.config(text=f"Samples: {total} (single-end mode)")

    result_text.insert(tk.END, f"Scan complete: {total} samples.\n")
    if paired:
        result_text.insert(tk.END, f"Paired OK: {paired_ok}; Issues: {issues}.\n")
    result_text.insert(tk.END, "Note: 'compressed (zcat)' samples will be mapped with --readFilesCommand zcat.\n")
    result_text.see(tk.END)

    global detected_samples
    detected_samples = samples


def select_all_samples():
    samples_listbox.select_set(0, tk.END)


def show_code_window(commands):
    execution_cancelled = [False]

    code_win = Toplevel(root)
    code_win.title("Commands to be Executed")

    frame = ttk.Frame(code_win)
    frame.pack(fill="both", expand=True)

    scrollbar = ttk.Scrollbar(frame, orient="vertical")
    text_widget = tk.Text(frame, wrap="word", yscrollcommand=scrollbar.set)
    scrollbar.config(command=text_widget.yview)
    scrollbar.pack(side="right", fill="y")
    text_widget.pack(side="left", fill="both", expand=True)

    for line in commands:
        text_widget.insert(tk.END, line + "\n")

    text_widget.config(state='disabled')

    button_frame = ttk.Frame(code_win)
    button_frame.pack(pady=5)

    def on_ok():
        execution_cancelled[0] = False
        code_win.destroy()

    def on_cancel():
        execution_cancelled[0] = True
        code_win.destroy()

    ok_button = tk.Button(button_frame, text="OK", command=on_ok)
    ok_button.pack(side="left", padx=5)

    cancel_button = tk.Button(button_frame, text="Cancel", command=on_cancel)
    cancel_button.pack(side="left", padx=5)

    code_win.grab_set()
    code_win.wait_window(code_win)

    return execution_cancelled[0]


def add_accuracy_params(star_cmd, accuracy_mode):
    """
    Add STAR filtering parameters according to the selected mapping accuracy.

    Relaxed is designed to recover more low-expression / weak RNA-seq signal
    without deliberately increasing the accepted number of multimapping loci.
    """
    mode = accuracy_mode.strip().lower()

    if mode == "relaxed":
        star_cmd.extend([
            # More permissive than STAR default absolute mismatch cap.
            # Default is usually 10. This helps long or lower-quality reads survive filtering.
            '--outFilterMismatchNmax', '20',

            # Keep a reasonable mismatch-rate ceiling so the added reads are not mostly bad matches.
            # For 150 bp reads, 0.20 means at most ~30 mismatches by ratio, but the absolute cap above
            # still limits the alignment to 20 mismatches.
            '--outFilterMismatchNoverLmax', '0.20',

            # Do NOT increase accepted multimapping compared with STAR default.
            # STAR default is 10; keeping 10 avoids the old relaxed setting that allowed 200 loci.
            '--outFilterMultimapNmax', '10',

            # More permissive minimum normalized alignment score.
            # Default is usually 0.66; 0.33 can rescue partial/degraded reads but is not as unsafe as 0.
            '--outFilterScoreMinOverLread', '0.33',

            # More permissive minimum fraction of matched bases.
            # Default is usually 0.66; 0.33 keeps a minimum evidence requirement for each read/read-pair.
            '--outFilterMatchNminOverLread', '0.33',
        ])
    elif mode == "strict":
        star_cmd.extend([
            '--outFilterMismatchNmax', '3',
            '--outFilterMismatchNoverLmax', '0.03',
            '--outFilterMultimapNmax', '5',
            '--outFilterScoreMinOverLread', '0.70',
            '--outFilterMatchNminOverLread', '0.70'
        ])
    # Default: add nothing, so STAR internal defaults are used.


def accuracy_help_text(mode):
    mode = mode.strip().lower()
    if mode == "relaxed":
        return (
            "Mapping accuracy: RELAXED (low-expression rescue; no extra multimapping allowance)\n"
            "Settings applied:\n"
            "  --outFilterMismatchNmax       20\n"
            "      Maximum number of mismatches allowed for one read alignment.\n"
            "  --outFilterMismatchNoverLmax  0.20\n"
            "      Maximum mismatch fraction relative to the mapped read length.\n"
            "  --outFilterMultimapNmax       10\n"
            "      Maximum number of genomic loci a read may map to before it is rejected as too multi-mapped.\n"
            "  --outFilterScoreMinOverLread  0.33\n"
            "      Minimum normalized alignment score relative to read length; lower values keep weaker alignments.\n"
            "  --outFilterMatchNminOverLread 0.33\n"
            "      Minimum normalized matched-bases fraction relative to read length; lower values keep shorter partial alignments.\n"
            "Effect:\n"
            "  - More permissive than Default for weak/partial/low-quality RNA-seq alignments.\n"
            "  - Does not raise the multimapping-loci limit above STAR default.\n"
            "  - Best goal: rescue extra uniquely mapped or still-low-multimap reads from low-expression RNAs.\n"
        )
    elif mode == "strict":
        return (
            "Mapping accuracy: STRICT (most stringent)\n"
            "Settings applied:\n"
            "  --outFilterMismatchNmax       3\n"
            "      Maximum number of mismatches allowed for one read alignment.\n"
            "  --outFilterMismatchNoverLmax  0.03\n"
            "      Maximum mismatch fraction relative to the mapped read length.\n"
            "  --outFilterMultimapNmax       5\n"
            "      Maximum number of genomic loci a read may map to before it is rejected as too multi-mapped.\n"
            "  --outFilterScoreMinOverLread  0.70\n"
            "      Minimum normalized alignment score relative to read length; higher values keep only stronger alignments.\n"
            "  --outFilterMatchNminOverLread 0.70\n"
            "      Minimum normalized matched-bases fraction relative to read length; higher values reject shorter partial alignments.\n"
            "Effect: maps fewer read nucleotides, but retained mappings are more conservative.\n"
        )
    else:
        return (
            "Mapping accuracy: DEFAULT (STAR internal defaults)\n"
            "Settings shown below are STAR defaults; the GUI does not explicitly add them to the command.\n"
            "Settings applied by STAR internally:\n"
            "  --outFilterMismatchNmax       10\n"
            "      Maximum number of mismatches allowed for one read alignment.\n"
            "  --outFilterMismatchNoverLmax  0.30\n"
            "      Maximum mismatch fraction relative to the mapped read length.\n"
            "  --outFilterMultimapNmax       10\n"
            "      Maximum number of genomic loci a read may map to before it is rejected as too multi-mapped.\n"
            "  --outFilterScoreMinOverLread  0.66\n"
            "      Minimum normalized alignment score relative to read length; this controls how strong the alignment must be.\n"
            "  --outFilterMatchNminOverLread 0.66\n"
            "      Minimum normalized matched-bases fraction relative to read length; this controls how much of the read must align.\n"
            "Effect:\n"
            "  - Balanced mapping stringency.\n"
            "  - Usually recommended as the main reference setting.\n"
            "  - Use this as the baseline when checking whether Relaxed really rescues useful low-expression RNA signal.\n"
        )


def mapping_accuracy_validation_text():
    return (
        "How to evaluate whether relaxed mappings are still trustworthy:\n"
        "  1) Compare each sample Log.final.out between Default and Relaxed.\n"
        "  2) A useful rescue is mainly an increase in uniquely mapped reads and average mapped length.\n"
        "  3) The percentage of reads mapped to multiple loci should stay close to Default; if it jumps, do not use Relaxed for final counts.\n"
        "  4) The percentage of reads mapped to too many loci should not increase strongly.\n"
        "  5) Check mismatch rate per base; a large jump suggests false or wrong-reference mappings.\n"
        "  6) For RNA-seq, check that rescued reads still pile up on real exons/splice junctions and not random intergenic/repeat regions.\n"
        "  7) For low-expression RNA detection, prioritize genes/transcripts supported by unique reads, splice-compatible reads, and reproducible signal across samples.\n"
    )


def splice_mode_help_text(mode):
    mode = mode.lower()
    if mode == "unspliced":
        return (
            "Genome / gene structure: UNSPLICED (no introns expected)\n"
            "Settings applied:\n"
            "  --alignIntronMax 1\n"
            "  --alignSJoverhangMin 999\n"
            "  --outFilterType Normal\n"
            "  --outSAMstrandField None\n"
            "Use the 'Advanced STAR options' field to override these if needed.\n"
        )
    else:
        return (
            "Genome / gene structure: SPLICED (introns allowed; typical RNA-seq)\n"
            "Settings applied:\n"
            "  --outFilterType BySJout\n"
            "  --outSAMstrandField intronMotif\n"
            "Use the 'Advanced STAR options' field to override or extend intron-related parameters.\n"
        )


def add_splice_mode_params(star_cmd, genome_mode):
    # IMPORTANT: splice-mode is only controlled here (avoid duplicate STAR args)
    mode = genome_mode.lower()
    if mode == "unspliced":
        star_cmd.extend([
            '--alignIntronMax', '1',
            '--alignSJoverhangMin', '999',
            '--outFilterType', 'Normal',
            '--outSAMstrandField', 'None'
        ])
    else:
        star_cmd.extend([
            '--outFilterType', 'BySJout',
            '--outSAMstrandField', 'intronMotif'
        ])


def update_accuracy_help(*args):
    mode = mapping_accuracy_var.get()
    txt = accuracy_help_text(mode)
    mapping_accuracy_help_label.config(text=txt)

    mode_lower = mode.strip().lower()
    if mode_lower == "relaxed":
        color = "spring green"
        fg = "black"
    elif mode_lower == "strict":
        color = "#ffaaaa"
        fg = "black"
    else:
        color = "yellow"
        fg = "black"

    mapping_accuracy_optionmenu.config(bg=color, fg=fg, activebackground=color, activeforeground=fg)
    try:
        mapping_accuracy_optionmenu['menu'].config(bg=color, fg=fg, activebackground=color, activeforeground=fg)
    except Exception:
        pass
    mapping_accuracy_help_label.config(bg=color, fg=fg)

    toggle_only_unmapped()


def compute_genome_length_and_saindex(win_fasta_paths_str):
    paths = shlex.split(win_fasta_paths_str)
    if not paths:
        raise ValueError("No FASTA files provided.")

    total_bases = 0
    for p in paths:
        if not p:
            continue
        if not os.path.isfile(p):
            raise FileNotFoundError(f"FASTA file not found: {p}")
        is_gz = p.lower().endswith(('.gz', '.gzip'))
        opener = gzip.open if is_gz else open
        with opener(p, 'rt') as fh:
            for line in fh:
                if not line:
                    continue
                if line[0] == '>':
                    continue
                total_bases += len(line.strip())

    if total_bases <= 0:
        raise ValueError("Total genome length is zero; FASTA may be empty or malformed.")

    genome_length = total_bases
    sa = int(math.log2(genome_length) / 2.0 - 1.0)
    if sa < 1:
        sa = 1
    if sa > 14:
        sa = 14

    return genome_length, sa


def toggle_two_pass_mode():
    if two_pass_var.get():
        genome_load_var.set(False)
        genome_load_checkbox.config(state='disabled')
    else:
        if mode_var.get() == "alignment":
            genome_load_checkbox.config(state='normal')


def toggle_genome_load_mode():
    if genome_load_var.get():
        two_pass_var.set(False)
        two_pass_checkbox.config(state='disabled')
    else:
        if mode_var.get() == "alignment":
            two_pass_checkbox.config(state='normal')


def format_seconds(sec: float) -> str:
    sec = int(sec)
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    else:
        return f"{m:02d}:{s:02d}"


def update_global_summary():
    if 'global_summary_label' not in globals():
        return
    global total_star_jobs, completed_star_jobs, star_jobs_start_time

    if total_star_jobs <= 0 or star_jobs_start_time is None:
        global_summary_label.config(text="Global mapping progress: idle")
        try:
            progress['value'] = 0
        except Exception:
            pass
        return

    done = completed_star_jobs
    total = total_star_jobs
    percent = (done / total) * 100.0 if total > 0 else 0.0
    elapsed = time.time() - star_jobs_start_time
    elapsed_str = format_seconds(elapsed)

    if done > 0:
        avg_per_job = elapsed / done
        remaining_jobs = max(total - done, 0)
        eta_seconds = avg_per_job * remaining_jobs
    else:
        eta_seconds = 0.0
    eta_str = format_seconds(eta_seconds)

    text = (
        f"Global mapping: {done} / {total} completed "
        f"({percent:5.1f}%)\n"
        f"Elapsed: {elapsed_str}   |   Estimated remaining: {eta_str}"
    )
    global_summary_label.config(text=text)

    try:
        progress['value'] = percent
    except Exception:
        pass


def periodic_summary_refresh():
    update_global_summary()
    if 'root' in globals():
        root.after(10000, periodic_summary_refresh)


def _advanced_has_option(advanced_str: str, opt_name: str) -> bool:
    if not advanced_str:
        return False
    toks = advanced_str.strip().split()
    return opt_name in toks


def add_relaxed_safety_params(star_cmd, accuracy_mode, only_unmapped, out_samtype, advanced_options):
    """
    Protect SAM/BAM output from per-read buffer problems when producing alignments.
    Relaxed mode does not increase accepted multimapping loci, but it can still make
    some reads easier to align, so output is capped to keep BAM size controlled.
    """
    mode = accuracy_mode.strip().lower()
    producing_alignments = (not only_unmapped) and bool(out_samtype)

    if mode == "relaxed":
        if not _advanced_has_option(advanced_options, "--alignTranscriptsPerReadNmax"):
            star_cmd.extend(["--alignTranscriptsPerReadNmax", "10000"])

        if producing_alignments:
            # Only controls how many SAM/BAM lines are written for a multimapping read.
            # It does not make STAR accept more multimapping loci.
            if not _advanced_has_option(advanced_options, "--outSAMmultNmax"):
                star_cmd.extend(["--outSAMmultNmax", "1"])
            if not _advanced_has_option(advanced_options, "--limitOutSAMoneReadBytes"):
                star_cmd.extend(["--limitOutSAMoneReadBytes", "1000000"])


def needs_linux_tmp_dir(output_dir_wsl: str) -> bool:
    # If output is on /mnt/<drive>/..., it is a Windows filesystem mount (NTFS)
    # which does not support FIFO -> must use --outTmpDir on Linux FS.
    out = (output_dir_wsl or "").strip()
    return out.startswith("/mnt/")


def safe_tmp_dir_for_sample(sample_name: str) -> str:
    # Linux temp dir path (FIFO-supported). Use timestamp for uniqueness.
    ts = int(time.time())
    # STAR likes writable, local FS. /tmp is ideal.
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", sample_name)
    return f"/tmp/STARtmp_{safe_name}_{ts}"


def run_star():
    if not validate_inputs():
        return

    run_button.config(state=tk.DISABLED)
    status_label.config(text="Status: Preparing Commands...")

    operation_mode = mode_var.get()
    threads_per_mapping = int(threads_per_mapping_entry.get())
    num_parallel_mappings = int(num_parallel_mappings_entry.get())
    output_dir = convert_path_to_wsl(output_entry.get())
    advanced_options = advanced_entry.get().strip()

    limit_bam_sort_ram_gb_str = limit_bam_sort_ram_entry.get().strip()
    limit_bam_sort_ram_bytes = None
    if limit_bam_sort_ram_gb_str:
        try:
            limit_bam_sort_ram_bytes = str(int(limit_bam_sort_ram_gb_str) * 1024 * 1024 * 1024)
        except ValueError:
            messagebox.showerror("Input Error", "Limit BAM sort RAM (GB) must be an integer.")
            run_button.config(state=tk.NORMAL)
            return

    genome_load_keep = genome_load_var.get()

    if operation_mode == "alignment":
        ref_genome = convert_path_to_wsl(ref_entry.get())
        paired = paired_var.get()
        out_samtype = samtype_var.get()
        two_pass_mode = two_pass_var.get()
        accuracy_mode = mapping_accuracy_var.get()
        genome_mode = genome_mode_var.get()
        save_unmapped = save_unmapped_var.get()
        only_unmapped = only_unmapped_var.get()
        create_bai = create_bai_var.get()
        unmapped_output_dir = unmapped_dir_entry.get().strip()
        unmapped_output_dir_wsl = convert_path_to_wsl(unmapped_output_dir) if unmapped_output_dir else ""

        selected_indices = samples_listbox.curselection()
        if not selected_indices:
            messagebox.showerror("Input Error", "No samples selected.")
            run_button.config(state=tk.NORMAL)
            return

        samples_to_run = [samples_listbox.get(idx) for idx in selected_indices]
        base_samples = [re.sub(r"\s+\[.*$", "", s).strip() for s in samples_to_run]

        global total_star_jobs, completed_star_jobs, failed_star_jobs, star_jobs_start_time
        total_star_jobs = len(base_samples)
        completed_star_jobs = 0
        failed_star_jobs = 0
        star_jobs_start_time = time.time()
        update_global_summary()

        result_text.insert(tk.END, accuracy_help_text(accuracy_mode) + "\n")
        result_text.insert(tk.END, splice_mode_help_text(genome_mode) + "\n")

        if needs_linux_tmp_dir(output_dir):
            result_text.insert(
                tk.END,
                "NOTE: Output directory is on /mnt/* (Windows NTFS). "
                "STAR will use a Linux temp folder via --outTmpDir (/tmp/...) to avoid FIFO errors.\n\n"
            )

        result_text.see(tk.END)

        star_commands = []
        for sample_name in base_samples:
            sample_files = detected_samples[sample_name]
            sample_base_noext = re.sub(r'(\.fastq(\.gz)?|\.fq(\.gz)?)$', '', sample_name, flags=re.IGNORECASE)

            if paired:
                if 'R1' in sample_files and 'R2' in sample_files and sample_files['R1'] and sample_files['R2']:
                    read_files_in_list = [convert_path_to_wsl(sample_files['R1']), convert_path_to_wsl(sample_files['R2'])]
                elif 'single' in sample_files and sample_files['single']:
                    read_files_in_list = [convert_path_to_wsl(sample_files['single'])]
                else:
                    messagebox.showerror("Input Error", f"Paired files not found for sample {sample_name}.")
                    run_button.config(state=tk.NORMAL)
                    return
            else:
                if 'single' in sample_files and sample_files['single']:
                    read_files_in_list = [convert_path_to_wsl(sample_files['single'])]
                else:
                    messagebox.showerror("Input Error", f"Read file not found for sample {sample_name}.")
                    run_button.config(state=tk.NORMAL)
                    return

            # FIFO-safe tmp dir if output is on /mnt/*
            tmpdir = None
            if needs_linux_tmp_dir(output_dir):
                tmpdir = safe_tmp_dir_for_sample(sample_name)

            star_cmd = [
                'echo -n "Limit open files before: " && ulimit -n ; '
                'echo "abcdefgh" | sudo -S prlimit --pid=$$ --nofile=262144:262144 ; '
                'echo -n "Limit open files after: " && ulimit -n ; STAR',
                '--runThreadN', str(threads_per_mapping),
                '--genomeDir', ref_genome,
                '--outSAMattributes', 'NH', 'HI', 'AS', 'nM', 'NM', 'MD', 'jM', 'jI', 'XS',
                '--outSAMmapqUnique', '255',
            ]

            # add outTmpDir early
            if tmpdir:
                star_cmd.extend(['--outTmpDir', tmpdir])

            star_cmd.extend(['--readFilesIn'])
            star_cmd.extend(read_files_in_list)
            star_cmd.extend(['--outFileNamePrefix', f"{output_dir}/{sample_name}_"])

            # splice-mode ONLY here
            add_splice_mode_params(star_cmd, genome_mode)

            if genome_load_keep and two_pass_mode:
                genome_load_keep = False
            if genome_load_keep:
                star_cmd.extend(['--genomeLoad', 'LoadAndKeep'])
            if two_pass_mode:
                star_cmd.extend(['--twopassMode', 'Basic'])

            sample_compressed = any(is_compressed_fastq(p) for p in read_files_in_list)
            if sample_compressed:
                star_cmd.extend(['--readFilesCommand', 'zcat'])

            bam_path = None

            if only_unmapped:
                star_cmd.extend(['--outSAMtype', 'None'])
            else:
                if out_samtype:
                    star_cmd.extend(['--outSAMtype'] + out_samtype.split())
                    if out_samtype.startswith("BAM"):
                        if "SortedByCoordinate" in out_samtype:
                            bam_path = f"{output_dir}/{sample_name}_Aligned.sortedByCoord.out.bam"
                        else:
                            bam_path = f"{output_dir}/{sample_name}_Aligned.out.bam"

            if limit_bam_sort_ram_bytes:
                star_cmd.extend(['--limitBAMsortRAM', limit_bam_sort_ram_bytes])

            add_accuracy_params(star_cmd, accuracy_mode)

            add_relaxed_safety_params(
                star_cmd=star_cmd,
                accuracy_mode=accuracy_mode,
                only_unmapped=only_unmapped,
                out_samtype=out_samtype if not only_unmapped else "",
                advanced_options=advanced_options
            )

            if save_unmapped:
                star_cmd.extend(['--outReadsUnmapped', 'Fastx'])

            if advanced_options:
                star_cmd.extend(advanced_options.split())

            star_cmd_str = ' '.join(star_cmd)

            # Move & rename unmapped reads
            if save_unmapped and unmapped_output_dir_wsl:
                if paired:
                    star_cmd_str += (
                        f" ; mkdir -p {unmapped_output_dir_wsl}"
                        f" ; if [ -f {output_dir}/{sample_name}_Unmapped.out.mate1 ]; then "
                        f"mv {output_dir}/{sample_name}_Unmapped.out.mate1 "
                        f"{unmapped_output_dir_wsl}/{sample_base_noext}_Unmapped_R1.fastq ; fi"
                        f" ; if [ -f {output_dir}/{sample_name}_Unmapped.out.mate2 ]; then "
                        f"mv {output_dir}/{sample_name}_Unmapped.out.mate2 "
                        f"{unmapped_output_dir_wsl}/{sample_base_noext}_Unmapped_R2.fastq ; fi"
                        f" ; true"
                    )
                else:
                    star_cmd_str += (
                        f" ; mkdir -p {unmapped_output_dir_wsl}"
                        f" ; if [ -f {output_dir}/{sample_name}_Unmapped.out.mate1 ]; then "
                        f"mv {output_dir}/{sample_name}_Unmapped.out.mate1 "
                        f"{unmapped_output_dir_wsl}/{sample_base_noext}_Unmapped.fastq ; fi"
                        f" ; true"
                    )

            # If only_unmapped: delete alignments BUT KEEP LOGS
            if only_unmapped:
                star_cmd_str += (
                    f" ; rm -f {output_dir}/{sample_name}_Aligned.out.bam"
                    f" {output_dir}/{sample_name}_Aligned.sortedByCoord.out.bam"
                    f" {output_dir}/{sample_name}_Aligned.out.sam"
                    f" {output_dir}/{sample_name}_SJ.out.tab 2>/dev/null || true"
                )

            # Create BAM index (.bai) if requested and a BAM is expected
            if create_bai and bam_path and not only_unmapped:
                star_cmd_str += f" ; samtools index {bam_path}"

            # Cleanup STAR temp dir if we forced --outTmpDir
            if tmpdir:
                # STAR deletes its tmp folder normally, but keep this as safety if it crashes
                star_cmd_str += f" ; rm -rf {tmpdir} 2>/dev/null || true"

            star_cmd_str = (
                f'echo "__STAR_JOB_BEGIN__ {sample_name}" ; '
                + star_cmd_str +
                f' ; echo "__STAR_JOB_END__ {sample_name}"'
            )

            star_commands.append(star_cmd_str)

        modified_commands = []
        total_cmds = len(star_commands)

        if num_parallel_mappings <= 1:
            for cmd in star_commands:
                modified_commands.append(cmd)
        else:
            for i, cmd in enumerate(star_commands, start=1):
                if i == total_cmds:
                    modified_commands.append(cmd)
                else:
                    if (i % num_parallel_mappings) != 0:
                        modified_commands.append(cmd + " &")
                    else:
                        modified_commands.append(cmd)

        modified_commands.append("wait")

        canceled = show_code_window(modified_commands)
        if canceled:
            status_label.config(text="Status: Canceled by user.")
            run_button.config(state=tk.NORMAL)
            return

        script_path = f"{output_dir}/star_script.lx"
        commands_str = "\n".join(modified_commands) + "\n"

        try:
            p = subprocess.Popen(["wsl", "tee", script_path],
                                 stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 text=True)
            stdout, stderr = p.communicate(input=commands_str)
            if p.returncode != 0:
                raise Exception(f"Failed to write script to WSL: {stderr}")

            subprocess.run(['wsl', 'sh', '-c', f"sed -i 's/\\r$//' {script_path}"], check=True)
            subprocess.run(['wsl', 'chmod', '+x', script_path], check=True)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to write script in WSL: {e}")
            run_button.config(state=tk.NORMAL)
            return

        parallel_command = f"wsl {script_path}"
        status_label.config(text="Status: Running STAR...")

        def run_parallel():
            global completed_star_jobs
            try:
                process = subprocess.Popen(
                    parallel_command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    shell=True,
                    bufsize=1
                )
                for line in process.stdout:
                    output = line.strip()
                    if not output:
                        continue
                    if output.startswith("__STAR_JOB_END__"):
                        completed_star_jobs += 1

                    result_text.insert(tk.END, f"{output}\n")
                    result_text.see(tk.END)
                    root.update_idletasks()

                rc = process.wait()
                if rc == 0:
                    status_label.config(text="Status: All STAR mappings completed.")
                else:
                    status_label.config(text="Status: Error in parallel execution.")
            except Exception as e:
                messagebox.showerror("Error", f"An error occurred: {e}")
            finally:
                run_button.config(state=tk.NORMAL)

        threading.Thread(target=run_parallel, daemon=True).start()

    elif operation_mode == "genome_index":
        raw_genome_fasta_win = genome_fasta_entry.get()
        genome_fasta = convert_path_to_wsl(raw_genome_fasta_win)
        annotation_gtf = convert_path_to_wsl(annotation_gtf_entry.get()) if annotation_gtf_entry.get() else None

        star_command = [
            'STAR',
            '--runThreadN', str(threads_per_mapping),
            '--runMode', 'genomeGenerate',
            '--genomeDir', output_dir,
            '--genomeFastaFiles', genome_fasta
        ]

        auto_sa_nbases = None
        if '--genomeSAindexNbases' in advanced_options:
            result_text.insert(tk.END, "Genome Index: Detected manual --genomeSAindexNbases in Advanced STAR options; automatic estimation disabled.\n")
            result_text.see(tk.END)
        else:
            try:
                genome_len, auto_sa_nbases = compute_genome_length_and_saindex(raw_genome_fasta_win)
                result_text.insert(tk.END, f"Genome Index: Estimated genome length ≈ {genome_len} bp; using --genomeSAindexNbases {auto_sa_nbases}\n")
                result_text.see(tk.END)
            except Exception as e:
                messagebox.showerror("Genome size error", f"Could not estimate genome length for automatic --genomeSAindexNbases:\n{e}")
                run_button.config(state=tk.NORMAL)
                return

        if auto_sa_nbases is not None:
            star_command.extend(['--genomeSAindexNbases', str(auto_sa_nbases)])

        if annotation_gtf:
            star_command.extend(['--sjdbGTFfile', annotation_gtf])

        if advanced_options:
            star_command.extend(advanced_options.split())

        star_cmd_str = ' '.join(star_command)
        modified_commands = [star_cmd_str, "wait"]

        canceled = show_code_window(modified_commands)
        if canceled:
            status_label.config(text="Status: Canceled by user.")
            run_button.config(state=tk.NORMAL)
            return

        script_path = f"{output_dir}/run_star_script.sh"
        commands_str = "\n".join(modified_commands) + "\n"

        try:
            p = subprocess.Popen(["wsl", "tee", script_path],
                                 stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 text=True)
            stdout, stderr = p.communicate(input=commands_str)
            if p.returncode != 0:
                raise Exception(f"Failed to write script to WSL: {stderr}")

            subprocess.run(['wsl', 'sh', '-c', f"sed -i 's/\\r$//' {script_path}"], check=True)
            subprocess.run(['wsl', 'chmod', '+x', script_path], check=True)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to write script in WSL: {e}")
            run_button.config(state=tk.NORMAL)
            return

        parallel_command = f"wsl {script_path}"
        status_label.config(text="Status: Running STAR Genome Indexing...")

        def target_genome():
            try:
                process = subprocess.Popen(
                    parallel_command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    shell=True,
                    bufsize=1
                )
                for line in process.stdout:
                    output = line.strip()
                    if output:
                        result_text.insert(tk.END, f"Genome Index: {output}\n")
                        result_text.see(tk.END)
                        root.update_idletasks()
                rc = process.wait()
                if rc == 0:
                    status_label.config(text="Status: Genome Indexing Completed")
                else:
                    status_label.config(text="Status: Error in Genome Indexing")
            except Exception as e:
                messagebox.showerror("Error", f"An error occurred during genome indexing: {e}")
            finally:
                run_button.config(state=tk.NORMAL)

        threading.Thread(target=target_genome, daemon=True).start()

    else:
        messagebox.showerror("Mode Error", "Unknown operation mode selected.")
        run_button.config(state=tk.NORMAL)


# ---------------- UI ----------------
root = tk.Tk()
root.title("STAR GUI (to close Vmmem use cmd then wsl --shutdown)")

# Keep your existing size, but reduce if you want (works fine on 1080p with scrolling)
root.geometry("1075x1200")

row_idx = 0

mode_var = tk.StringVar(value="alignment")
tk.Label(root, text="Operation Mode:").grid(row=row_idx, column=0, sticky=tk.W, padx=5, pady=5)
tk.Radiobutton(root, text="Align Reads", variable=mode_var, value="alignment", command=toggle_mode)\
    .grid(row=row_idx, column=1, sticky=tk.W, padx=5)
tk.Radiobutton(root, text="Build Genome Index", variable=mode_var, value="genome_index", command=toggle_mode)\
    .grid(row=row_idx, column=2, sticky=tk.W, padx=5)
row_idx += 1

threads_per_mapping_label = tk.Label(root, text="Threads per mapping\n(physical cores)")
threads_per_mapping_label.grid(row=row_idx, column=0, sticky=tk.W, padx=5, pady=2)
threads_per_mapping_entry = tk.Entry(root, width=6)
threads_per_mapping_entry.grid(row=row_idx, column=1, sticky=tk.W, padx=5)
threads_per_mapping_entry.insert(0, "10")

tk.Label(root, text="Parallel mappings:").grid(row=row_idx, column=2, sticky=tk.E, padx=5)
num_parallel_mappings_entry = tk.Entry(root, width=4)
num_parallel_mappings_entry.grid(row=row_idx, column=3, sticky=tk.W, padx=5)
num_parallel_mappings_entry.insert(0, "1")

scan_reads_button = tk.Button(root, text="Scan Reads\n(R1/R2 pairing + compression)", command=scan_reads_directory)
scan_reads_button.grid(row=row_idx, column=4, sticky=tk.W, padx=5, pady=2)

paired_var = tk.BooleanVar()
paired_checkbox = tk.Checkbutton(root, text="Paired-end", variable=paired_var)
paired_checkbox.grid(row=row_idx, column=5, sticky=tk.W, padx=5)
row_idx += 1

tk.Label(root, text="Reads Directory:").grid(row=row_idx, column=0, sticky=tk.W, padx=5)
reads_dir_entry = tk.Entry(root, width=60)
reads_dir_entry.grid(row=row_idx, column=1, columnspan=3, sticky=tk.W + tk.E, padx=5)
browse_reads_dir_button = tk.Button(root, text="Browse", command=lambda: browse_directory(reads_dir_entry))
browse_reads_dir_button.grid(row=row_idx, column=4, sticky=tk.W, padx=5)
row_idx += 1

tk.Label(root, text="STAR Index (genomeDir):").grid(row=row_idx, column=0, sticky=tk.W, padx=5)
ref_entry = tk.Entry(root, width=60)
ref_entry.grid(row=row_idx, column=1, columnspan=3, sticky=tk.W + tk.E, padx=5)
browse_ref_button = tk.Button(root, text="Browse", command=lambda: browse_directory(ref_entry))
browse_ref_button.grid(row=row_idx, column=4, sticky=tk.W, padx=5)
row_idx += 1

tk.Label(root, text="Output Directory:").grid(row=row_idx, column=0, sticky=tk.W, padx=5)
output_entry = tk.Entry(root, width=60)
output_entry.grid(row=row_idx, column=1, columnspan=3, sticky=tk.W + tk.E, padx=5)
browse_output_button = tk.Button(root, text="Browse", command=lambda: browse_directory(output_entry))
browse_output_button.grid(row=row_idx, column=4, sticky=tk.W, padx=5)
row_idx += 1

tk.Label(root, text="Genome FASTA Files:").grid(row=row_idx, column=0, sticky=tk.W, padx=5)
genome_fasta_entry = tk.Entry(root, width=60)
genome_fasta_entry.grid(row=row_idx, column=1, columnspan=3, sticky=tk.W + tk.E, padx=5)
browse_genome_fasta_button = tk.Button(root, text="Browse", command=lambda: browse_files(genome_fasta_entry))
browse_genome_fasta_button.grid(row=row_idx, column=4, sticky=tk.W, padx=5)
row_idx += 1

tk.Label(root, text="Annotation GTF File:").grid(row=row_idx, column=0, sticky=tk.W, padx=5)
annotation_gtf_entry = tk.Entry(root, width=60)
annotation_gtf_entry.grid(row=row_idx, column=1, columnspan=3, sticky=tk.W + tk.E, padx=5)
browse_annotation_gtf_button = tk.Button(root, text="Browse", command=lambda: browse_file(annotation_gtf_entry))
browse_annotation_gtf_button.grid(row=row_idx, column=4, sticky=tk.W, padx=5)
row_idx += 1

tk.Label(root, text="Output SAM / BAM:").grid(row=row_idx, column=0, sticky=tk.W, padx=5)
samtype_var = tk.StringVar(value="BAM SortedByCoordinate")
samtype_options = ["BAM Unsorted", "BAM SortedByCoordinate", "SAM"]
samtype_optionmenu = tk.OptionMenu(root, samtype_var, *samtype_options)
samtype_optionmenu.grid(row=row_idx, column=1, sticky=tk.W, padx=5)

two_pass_var = tk.BooleanVar(value=False)
two_pass_checkbox = tk.Checkbutton(root, text="2-pass mapping", variable=two_pass_var, command=toggle_two_pass_mode)
two_pass_checkbox.grid(row=row_idx, column=2, sticky=tk.W, padx=5)

tk.Label(root, text="limitBAMsortRAM (GB):").grid(row=row_idx, column=3, sticky=tk.E, padx=5)
limit_bam_sort_ram_entry = tk.Entry(root, width=6)
limit_bam_sort_ram_entry.grid(row=row_idx, column=4, sticky=tk.W, padx=5)
limit_bam_sort_ram_entry.insert(0, "12")
row_idx += 1

genome_load_var = tk.BooleanVar(value=True)
genome_load_checkbox = tk.Checkbutton(
    root,
    text="Keep genome in shared memory (--genomeLoad LoadAndKeep)",
    variable=genome_load_var,
    command=toggle_genome_load_mode
)
genome_load_checkbox.grid(row=row_idx, column=0, columnspan=5, sticky=tk.W, padx=5, pady=3)
row_idx += 1

create_bai_var = tk.BooleanVar(value=True)
create_bai_checkbox = tk.Checkbutton(root, text="Create BAM index (.bai) with samtools", variable=create_bai_var)
create_bai_checkbox.grid(row=row_idx, column=0, columnspan=5, sticky=tk.W, padx=5, pady=3)
row_idx += 1

tk.Label(root, text="Mapping Accuracy:").grid(row=row_idx, column=0, sticky=tk.W, padx=5)
mapping_accuracy_var = tk.StringVar(value="Default")
mapping_accuracy_options = ["Relaxed", "Default", "Strict"]
mapping_accuracy_optionmenu = tk.OptionMenu(root, mapping_accuracy_var, *mapping_accuracy_options)
mapping_accuracy_optionmenu.grid(row=row_idx, column=1, sticky=tk.W, padx=5)
row_idx += 1

mapping_accuracy_help_label = tk.Label(root, text="", justify=tk.LEFT, anchor="w")
mapping_accuracy_help_label.grid(row=row_idx, column=0, columnspan=5, sticky=tk.W, padx=5)
row_idx += 1

tk.Label(root, text="Genome / gene structure:").grid(row=row_idx, column=0, sticky=tk.W, padx=5)
genome_mode_var = tk.StringVar(value="Spliced")
genome_mode_options = ["Spliced", "Unspliced"]
genome_mode_optionmenu = tk.OptionMenu(root, genome_mode_var, *genome_mode_options)
genome_mode_optionmenu.grid(row=row_idx, column=1, sticky=tk.W, padx=5)
row_idx += 1

save_unmapped_var = tk.BooleanVar(value=False)
save_unmapped_checkbox = tk.Checkbutton(root, text="Save unmapped reads (FastQ)", variable=save_unmapped_var)
save_unmapped_checkbox.grid(row=row_idx, column=0, sticky=tk.W, padx=5, pady=3)

tk.Label(root, text="Unmapped folder:").grid(row=row_idx, column=1, sticky=tk.E, padx=5)
unmapped_dir_entry = tk.Entry(root, width=40)
unmapped_dir_entry.grid(row=row_idx, column=2, sticky=tk.W, padx=5)
unmapped_browse_button = tk.Button(root, text="Browse", command=lambda: browse_directory(unmapped_dir_entry))
unmapped_browse_button.grid(row=row_idx, column=3, sticky=tk.W, padx=5)
row_idx += 1

only_unmapped_var = tk.BooleanVar(value=False)
only_unmapped_checkbox = tk.Checkbutton(
    root,
    text="Discard mapped alignments (keep only unmapped reads)",
    variable=only_unmapped_var,
    command=toggle_only_unmapped
)
only_unmapped_checkbox.grid(row=row_idx, column=0, columnspan=5, sticky=tk.W, padx=5, pady=3)
row_idx += 1

tk.Label(root, text="Advanced STAR options:").grid(row=row_idx, column=0, sticky=tk.W, padx=5)
advanced_entry = tk.Entry(root, width=60)
advanced_entry.grid(row=row_idx, column=1, columnspan=3, sticky=tk.W + tk.E, padx=5)
row_idx += 1

progress = ttk.Progressbar(root, orient=tk.HORIZONTAL, length=400, mode='determinate')
progress.grid(row=row_idx, column=0, columnspan=5, pady=5, padx=5, sticky=tk.W + tk.E)
row_idx += 1

global_summary_label = tk.Label(root, text="Global mapping progress: idle", justify=tk.LEFT, anchor="w")
global_summary_label.grid(row=row_idx, column=0, columnspan=5, sticky=tk.W, padx=5)
row_idx += 1

status_label = tk.Label(root, text="Status: Idle")
status_label.grid(row=row_idx, column=0, columnspan=3, sticky=tk.W, padx=5)
run_button = tk.Button(root, text="Run STAR", command=run_star)
run_button.grid(row=row_idx, column=3, sticky=tk.E, padx=5, pady=3)
row_idx += 1

bottom_frame = tk.Frame(root)
bottom_frame.grid(row=row_idx, column=0, columnspan=6, sticky=tk.N + tk.S + tk.E + tk.W, padx=5, pady=5)

left_frame = tk.Frame(bottom_frame)
left_frame.grid(row=0, column=0, sticky=tk.N + tk.S + tk.E + tk.W, padx=5)

tk.Label(left_frame, text="Detected Samples:").grid(row=0, column=0, sticky=tk.W)

samples_frame = tk.Frame(left_frame)
samples_frame.grid(row=1, column=0, sticky=tk.N + tk.S + tk.E + tk.W)

samples_listbox = tk.Listbox(samples_frame, selectmode=tk.EXTENDED, width=60, height=12)
samples_listbox.grid(row=0, column=0, sticky=tk.N + tk.S + tk.E + tk.W)

samples_scrollbar = tk.Scrollbar(samples_frame, orient="vertical", command=samples_listbox.yview)
samples_scrollbar.grid(row=0, column=1, sticky=tk.N + tk.S)
samples_listbox.config(yscrollcommand=samples_scrollbar.set)

samples_frame.grid_rowconfigure(0, weight=1)
samples_frame.grid_columnconfigure(0, weight=1)

sample_summary_label = tk.Label(left_frame, text="Samples: 0 (paired OK: 0 / issues: 0)")
sample_summary_label.grid(row=2, column=0, sticky=tk.W, pady=(2, 0))

select_all_button = tk.Button(left_frame, text="Select All", command=select_all_samples)
select_all_button.grid(row=3, column=0, sticky=tk.W, pady=(2, 0))

left_frame.grid_rowconfigure(1, weight=1)
left_frame.grid_columnconfigure(0, weight=1)

right_frame = tk.Frame(bottom_frame)
right_frame.grid(row=0, column=1, sticky=tk.N + tk.S + tk.E + tk.W, padx=5)

tk.Label(right_frame, text="Log:").grid(row=0, column=0, sticky=tk.W)

log_frame = tk.Frame(right_frame)
log_frame.grid(row=1, column=0, sticky=tk.N + tk.S + tk.E + tk.W)

result_text = tk.Text(log_frame, height=14, width=70)
result_text.grid(row=0, column=0, sticky=tk.N + tk.S + tk.E + tk.W)

log_scrollbar = tk.Scrollbar(log_frame, orient="vertical", command=result_text.yview)
log_scrollbar.grid(row=0, column=1, sticky=tk.N + tk.S)
result_text.config(yscrollcommand=log_scrollbar.set)

log_frame.grid_rowconfigure(0, weight=1)
log_frame.grid_columnconfigure(0, weight=1)

bottom_frame.grid_rowconfigure(0, weight=1)
bottom_frame.grid_columnconfigure(0, weight=1)
bottom_frame.grid_columnconfigure(1, weight=1)

mapping_accuracy_var.trace_add("write", update_accuracy_help)
update_accuracy_help()

toggle_mode()
root.after(10000, periodic_summary_refresh)
root.mainloop()
