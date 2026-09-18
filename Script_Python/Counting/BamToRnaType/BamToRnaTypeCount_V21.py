#!/usr/bin/env python3
import os
import subprocess
from tkinter import Tk, filedialog, Label, Button, Entry, StringVar, IntVar, Radiobutton

def get_final_base_name(path):
    """
    Returns a base name (without extension) from the given path.
    If the path is a folder, its last component is used.
    """
    if not path:
        return "comparison"
    norm = os.path.normpath(path)
    base = os.path.basename(norm)
    if not base:
        return "comparison"
    if "." in base:
        base = os.path.splitext(base)[0]
    return base

# --- Helper Functions ---
def windows_to_linux_path(path):
    """Convert a Windows path to a Linux path for WSL."""
    if not path:
        return ""
    try:
        result = subprocess.run(["wsl", "wslpath", "-a", path],
                                capture_output=True, text=True, check=True)
        linux_path = result.stdout.strip()
        if linux_path:
            return linux_path
    except Exception:
        pass
    if ":" in path:
        drive, rest = path.split(":", 1)
        drive = drive.lower()
        rest = rest.lstrip("\\/")  # Remove any leading slashes/backslashes
        return f"/mnt/{drive}/" + rest.replace("\\", "/")
    return path

def get_total_from_summary(summary_file):
    """
    Read a featureCounts summary file and return a list of total reads per BAM sample.
    Totals are computed by summing all numeric columns.
    """
    try:
        with open(summary_file, "r") as f:
            lines = f.readlines()
        totals = None
        for line in lines:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.strip().split()
            nums = []
            for x in parts[1:]:
                try:
                    nums.append(int(x))
                except:
                    nums.append(0)
            if totals is None:
                totals = nums
            else:
                totals = [a + b for a, b in zip(totals, nums)]
        return totals
    except Exception:
        return None

def sum_counts_from_file(count_file):
    """
    Read a featureCounts count file and return (column sums, sample names).
    If header[1] is 'Chr' (or similar), counts start at index 6; otherwise at index 1.
    Sample names are reduced to their basename.
    """
    with open(count_file, "r") as f:
        lines = [line for line in f if not line.startswith("#")]
    header = lines[0].strip().split("\t")
    start_index = 6 if header[1].lower() in ["chr", "chrom", "chromosome"] else 1
    sums = [0] * (len(header) - start_index)
    samples = [os.path.basename(s) for s in header[start_index:]]
    for row in lines[1:]:
        parts = row.strip().split("\t")
        for i, val in enumerate(parts[start_index:]):
            try:
                sums[i] += int(val)
            except:
                continue
    return sums, samples

# --- GUI Selection Functions (Multi-GTF mode only) ---
def select_bin_directory():
    folder = filedialog.askdirectory(title="'bin' Directory Containing featureCounts")
    if folder:
        bin_var.set(folder)
        status_label.config(text=f"'bin' directory set to: {folder}")

def select_bam_folder():
    folder = filedialog.askdirectory(title="Select Folder Containing BAM Files")
    if folder:
        bam_files_var.set(folder)
        status_label.config(text=f"Selected BAM folder: {folder}")

def select_output_file():
    out = filedialog.asksaveasfilename(
        title="Select Output File for Comparison",
        defaultextension=".tabtxt",
        filetypes=[("tabtxt Files", "*.tabtxt"), ("All Files", "*.*")]
    )
    if out:
        output_var.set(out)
        status_label.config(text=f"Output file set to: {out}")

def select_gtf_folder():
    folder = filedialog.askdirectory(title="Select Folder Containing GTF Files")
    if folder:
        gtf_folder_var.set(folder)
        status_label.config(text=f"Selected GTF folder: {folder}")

# --- Comparison Function for Multi-GTF Mode ---
def compare_gtf_results(output_files, gtf_names, output_dir, base_output_file, paired):
    """
    After building the final comparison file, it returns the path to that file.
    """
    results = {}   # annotation -> {sample: assigned_count}
    bam_samples = None
    for i, file in enumerate(output_files):
        try:
            with open(file, "r") as f:
                lines = f.readlines()
            data_lines = [line for line in lines if not line.startswith("#")]
            if not data_lines:
                status_label.config(text=f"No data in output file {file}")
                continue
            header = data_lines[0].strip().split("\t")
            if header[1].lower() in ["chr", "chrom", "chromosome"]:
                current_samples = header[6:]
            else:
                current_samples = header[1:]
            current_samples = [os.path.basename(s) for s in current_samples]
            if bam_samples is None:
                bam_samples = current_samples
            elif bam_samples != current_samples:
                status_label.config(text="Mismatch in BAM sample names across output files.")
                return None
            sums = {sample: 0 for sample in current_samples}
            for row in data_lines[1:]:
                parts = row.strip().split("\t")
                if header[1].lower() in ["chr", "chrom", "chromosome"]:
                    counts = parts[6:]
                else:
                    counts = parts[1:]
                for j, sample in enumerate(current_samples):
                    try:
                        sums[sample] += int(counts[j])
                    except:
                        continue
            results[gtf_names[i]] = sums
        except Exception as e:
            status_label.config(text=f"Error processing file {file}: {e}")
            return None

    # Use the summary file from the first output file for totals.
    summary_file = output_files[0] + ".summary"
    totals = get_total_from_summary(summary_file)
    if totals is None:
        status_label.config(text="Error reading summary file for totals.")
        return None

    # Compute percentages per annotation per sample
    raw_percentages = {}
    for ann in gtf_names:
        raw = []
        for i, sample in enumerate(bam_samples):
            if totals[i] > 0:
                p = (results[ann][sample] / totals[i]) * 100
            else:
                p = 0.0
            raw.append(p)
        raw_percentages[ann] = raw
    percentages = {ann: [round(p, 1) for p in raw_percentages[ann]] for ann in gtf_names}

    # Build header and rows; group rows by strand mode.
    multimap_str = "NoMultimapped"
    overlap_str = "NoOverlapp"
    pair_str = "Paired" if paired == 1 else "NotPaired"
    settings_str = f"{multimap_str}_{overlap_str}_{pair_str}"
    comp_lines = []
    header_line_str = f"{settings_str}\t" + "\t".join(bam_samples)
    comp_lines.append(header_line_str)

    # Group the annotations by their strand mode using explicit prefix matching.
    groups = {"unstranded": [], "stranded-same": [], "stranded-reverse": []}
    for ann in gtf_names:
        if ann.startswith("unstranded-"):
            groups["unstranded"].append(ann)
        elif ann.startswith("stranded-same-"):
            groups["stranded-same"].append(ann)
        elif ann.startswith("stranded-reverse-"):
            groups["stranded-reverse"].append(ann)
        else:
            groups.setdefault("others", []).append(ann)

    # For each mode, output its annotations, then an Unassigned row, then a blank line.
    for mode in ["unstranded", "stranded-same", "stranded-reverse"]:
        if mode in groups and groups[mode]:
            for ann in groups[mode]:
                row = ann + "\t" + "\t".join(f"{percentages[ann][i]:.1f}%" for i in range(len(bam_samples)))
                comp_lines.append(row)
            # Compute the unassigned percentage for this mode group per sample.
            unassigned_values = []
            for i in range(len(bam_samples)):
                sum_ann = sum(percentages[ann][i] for ann in groups[mode])
                ua = round(100.0 - sum_ann, 1)
                unassigned_values.append(ua)
            unassigned_line = f"{mode}-Unassigned\t" + "\t".join(f"{u:.1f}%" for u in unassigned_values)
            comp_lines.append(unassigned_line)
            comp_lines.append("")  # Blank line to separate each strand block

    totals_line = "Total Reads\t" + "\t".join(str(total) for total in totals)
    comp_lines.append(totals_line)
    base_out = os.path.splitext(os.path.basename(base_output_file))[0]
    comp_file = os.path.join(output_dir, base_out + "_comparison.tabtxt")
    comp_file = os.path.normpath(comp_file)
    try:
        with open(comp_file, "w") as out_f:
            out_f.write("\n".join(comp_lines))
        status_label.config(text="Comparison file created: " + comp_file)
        return comp_file  # Return the path to the final comparison file
    except Exception as e:
        status_label.config(text=f"Error writing comparison file: {e}")
        return None

# --- Run featureCounts in Multi-GTF Mode (with 3 strand options) ---
def run_featurecounts_multi_gtf():
    bin_path = bin_var.get()
    bam_folder = bam_files_var.get()
    gtf_folder = gtf_folder_var.get()
    output_file = output_var.get()
    threads = threads_var.get()
    feature_type = "gene"
    gene_id_attr = "gene_id"
    paired_option = paired_var.get()

    if not os.path.exists(bin_path):
        status_label.config(text="Error: 'bin' directory not found. Please set the correct path.")
        return
    if not gtf_folder:
        status_label.config(text="Error: GTF folder not selected.")
        return
    if not output_file:
        status_label.config(text="Error: Output file not set.")
        return

    output_dir = os.path.dirname(os.path.abspath(output_file))
    os.makedirs(output_dir, exist_ok=True)

    linux_bin_path = windows_to_linux_path(bin_path) + "/featureCounts"
    linux_bam_files = windows_to_linux_path(bam_folder) + "/*.bam"
    gtf_folder = os.path.abspath(gtf_folder)
    gtf_files = [os.path.join(gtf_folder, f) for f in os.listdir(gtf_folder) if f.lower().endswith(".gtf")]
    if not gtf_files:
        status_label.config(text="Error: No GTF files found in the selected folder.")
        return

    # Define the three strand modes: (label, value)
    modes = [("unstranded", "0"), ("stranded-same", "1"), ("stranded-reverse", "2")]

    output_files = []
    script_files = []  # We'll store the .lx script files here
    gtf_names = []

    # Outer loop over strand modes, inner loop over GTF files.
    for mode_name, mode_value in modes:
        for gtf_file in gtf_files:
            base_name = os.path.splitext(os.path.basename(gtf_file))[0]
            # Strand mode comes first in the label.
            label = f"{mode_name}-{base_name}"
            gtf_names.append(label)

            output_file_gtf = os.path.join(output_dir, f"{base_name}_{mode_name}.tabtxt")
            linux_gtf_file = windows_to_linux_path(gtf_file)
            linux_output_file = windows_to_linux_path(output_file_gtf)
            paired_flag = "-p" if paired_option == 1 else ""

            # Build the command with the strand option (-s) before the BAM files.
            command = [
                linux_bin_path,
                "-s", mode_value,
                "-a", linux_gtf_file,
                "-o", linux_output_file,
                "-T", str(threads),
                "-t", feature_type,
                "-g", gene_id_attr,
                paired_flag,
                linux_bam_files
            ]
            # Remove empty elements in case paired_flag is not used
            command = [c for c in command if c]
            command_string = " ".join(command)
            if not command_string.strip():
                status_label.config(text=f"Error: Built command for {label} is empty.")
                continue

            script_file_path = os.path.join(output_dir, f"featurecounts_command_{base_name}_{mode_name}.lx")
            try:
                with open(script_file_path, "w", newline="\n") as script_file:
                    script_file.write("#!/bin/bash\n")
                    script_file.write(command_string + "\n")
                os.chmod(script_file_path, 0o755)
            except OSError as e:
                status_label.config(text=f"Error writing script file for {label}: {e}")
                continue

            script_files.append(script_file_path)
            # Execute the script in WSL
            linux_script_file_path = windows_to_linux_path(script_file_path)
            proc = subprocess.run(["wsl", "bash", linux_script_file_path], check=False)
            if proc.returncode != 0:
                status_label.config(text=f"Warning: featureCounts for {label} returned nonzero exit code {proc.returncode}")
            else:
                status_label.config(
                    text=(f"featureCounts completed for {label}! "
                          f"Script exported and executed from {script_file_path}")
                )

            output_files.append(output_file_gtf)

    # Now create the final comparison file
    if output_files:
        comparison_file = compare_gtf_results(output_files, gtf_names, output_dir, output_file, paired_option)

        # After we've created the comparison file, remove all temporary files
        if comparison_file:
            # Remove each count file and its summary
            for fpath in output_files:
                if os.path.exists(fpath):
                    os.remove(fpath)
                summary_path = fpath + ".summary"
                if os.path.exists(summary_path):
                    os.remove(summary_path)

            # Remove the .lx scripts
            for sfile in script_files:
                if os.path.exists(sfile):
                    os.remove(sfile)

            status_label.config(text=(
                f"Cleanup complete. Only final comparison file retained:\n{comparison_file}"
            ))
        else:
            status_label.config(text="Comparison file was not created. No cleanup performed.")

# --- Main GUI (Multi-GTF Mode Only) ---
if __name__ == "__main__":
    print("Starting featureCounts GUI...")
    root = Tk()
    root.title("featureCounts GUI - Multi-GTF Mode Only")
    
    Label(root, text="featureCounts LX 'bin' Directory:").grid(row=0, column=0, sticky="w")
    bin_var = StringVar()
    Button(root, text="Set 'bin' Directory", command=select_bin_directory).grid(row=0, column=1, sticky="w")
    
    Label(root, text="Select BAM Folder:").grid(row=1, column=0, sticky="w")
    bam_files_var = StringVar()
    Button(root, text="Set BAM Folder", command=select_bam_folder).grid(row=1, column=1, sticky="w")
    
    Label(root, text="Select GTF Folder:").grid(row=2, column=0, sticky="w")
    gtf_folder_var = StringVar()
    Button(root, text="Set GTF Folder", command=select_gtf_folder).grid(row=2, column=1, sticky="w")
    
    Label(root, text="Output File (full path):").grid(row=3, column=0, sticky="w")
    output_var = StringVar()
    Entry(root, textvariable=output_var).grid(row=3, column=1, sticky="w")
    Button(root, text="Set Output File", command=select_output_file).grid(row=3, column=2, sticky="w")
    
    Label(root, text="Number of Threads:").grid(row=4, column=0, sticky="w")
    threads_var = IntVar(value=1)
    Entry(root, textvariable=threads_var).grid(row=4, column=1, sticky="w")
    
    Label(root, text="(Feature Type = gene; Grouping = gene_id)").grid(row=5, column=0, columnspan=3, sticky="w")
    
    Label(root, text="Read Pairing:").grid(row=6, column=0, sticky="w")
    paired_var = IntVar(value=1)
    Radiobutton(root, text="Unpaired", variable=paired_var, value=0).grid(row=6, column=1, sticky="w")
    Radiobutton(root, text="Paired", variable=paired_var, value=1).grid(row=6, column=2, sticky="w")
    
    Button(root, text="Run featureCounts", command=run_featurecounts_multi_gtf).grid(row=10, column=0, columnspan=3, pady=10)
    
    status_label = Label(root, text="", fg="blue")
    status_label.grid(row=11, column=0, columnspan=3)
    
    root.mainloop()
