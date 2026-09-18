from __future__ import annotations

import threading


import argparse
import bisect
import copy
import csv
import gzip
import html
import json
import logging
import math
import os
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, TextIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
try:
    import pysam
except ModuleNotFoundError:
    pysam = None



def _parse_cli_bool(value: str) -> bool:
    text = str(value).strip().lower()
    if text in {'true', '1', 'yes', 'y', 'on'}:
        return True
    if text in {'false', '0', 'no', 'n', 'off'}:
        return False
    raise argparse.ArgumentTypeError(f"Expected true/false, got: {value}")


def build_cli_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--backend', action='store_true', default=False, help='Run the non-GUI backend used internally by the Windows GUI.')
    parser.add_argument('--cli', action='store_true', default=False, help='Run in command-line/Nextflow mode instead of opening the GUI.')
    parser.add_argument('--settings-file', type=str, default='')
    parser.add_argument('--input-dir', type=str, default='')
    parser.add_argument('--output-dir', type=str, default='')
    parser.add_argument('--threads', type=int, default=10, help='Number of CPU threads used by this step.')
    parser.add_argument('--dry-run', action='store_true', default=False, help='Prepare/check commands without running external tools where supported.')
    parser.add_argument('--breakpoints-analysis-ready-bam-folder', dest='__cfg__breakpoints__analysis_ready_bam_folder', type=str, default='', help='Override breakpoints.analysis_ready_bam_folder for this execution.')
    parser.add_argument('--references-fasta', dest='__cfg__references__fasta', type=str, default='', help='Override references.fasta for this execution.')
    parser.add_argument('--references-fasta-fai', dest='__cfg__references__fasta_fai', type=str, default='', help='Optional explicit reference FASTA .fai file. If blank, Step 06 uses/creates <reference>.fai.')
    parser.add_argument('--breakpoints-canonical-chromosomes', dest='__cfg__breakpoints__canonical_chromosomes', type=str, default='', help='Semicolon/comma-separated reference sequence names that should be reported as canonical. All other FASTA reference sequences are classified as non-canonical.')
    parser.add_argument('--breakpoints-classic-bwa-index-file', dest='__cfg__breakpoints__classic_bwa_index_file', type=str, default='', help='Path to any one classic BWA index component (.amb/.ann/.bwt/.pac/.sa) for the exact selected reference FASTA. Required when GRIDSS2 or SvABA is enabled.')
    parser.add_argument('--breakpoints-run-spades-assembly', dest='__cfg__breakpoints__run_spades_assembly', type=_parse_cli_bool, default=True, help='Override breakpoints.run_spades_assembly for this execution.')
    parser.add_argument('--breakpoints-run-manta', dest='__cfg__breakpoints__run_manta', type=_parse_cli_bool, default=True, help='Override breakpoints.run_manta for this execution.')
    parser.add_argument('--breakpoints-run-gridss2', dest='__cfg__breakpoints__run_gridss2', type=_parse_cli_bool, default=True, help='Run GRIDSS2 on the complete analysis-ready BAM.')
    parser.add_argument('--breakpoints-run-delly', dest='__cfg__breakpoints__run_delly', type=_parse_cli_bool, default=True, help='Run DELLY short-read SV calling on the complete analysis-ready BAM.')
    parser.add_argument('--breakpoints-run-svaba', dest='__cfg__breakpoints__run_svaba', type=_parse_cli_bool, default=True, help='Run SvABA local-assembly SV calling on the complete analysis-ready BAM.')
    parser.add_argument('--breakpoints-spades-kmer-mode', dest='__cfg__breakpoints__spades_kmer_mode', type=str, choices=['automatic', 'manual'], default='automatic', help='SPAdes k-mer selection mode. automatic omits -k and lets SPAdes choose; manual uses breakpoints.spades_kmers.')
    parser.add_argument('--breakpoints-spades-kmers', dest='__cfg__breakpoints__spades_kmers', type=str, default='21,33,55,77', help='Manual SPAdes k-mers. Used only when breakpoints.spades_kmer_mode=manual.')
    parser.add_argument('--breakpoints-minimum-contig-length', dest='__cfg__breakpoints__minimum_contig_length', type=int, default=100, help='Override breakpoints.minimum_contig_length for this execution.')
    parser.add_argument('--breakpoints-minimum-contig-alignment-length', dest='__cfg__breakpoints__minimum_contig_alignment_length', type=int, default=50, help='Override breakpoints.minimum_contig_alignment_length for this execution.')
    parser.add_argument('--breakpoints-local-depth-window-bp', dest='__cfg__breakpoints__local_depth_window_bp', type=int, default=100, help='Override breakpoints.local_depth_window_bp for this execution.')
    parser.add_argument('--tools-manta-config', dest='__cfg__tools__manta_config', type=str, default='configManta.py', help='Override tools.manta_config for this execution.')
    parser.add_argument('--tools-manta-run', dest='__cfg__tools__manta_run', type=str, default='ctdna-manta-run', help='Override tools.manta_run for this execution.')
    parser.add_argument('--tools-gridss', dest='__cfg__tools__gridss', type=str, default='gridss', help='GRIDSS2 wrapper command/path.')
    parser.add_argument('--tools-delly', dest='__cfg__tools__delly', type=str, default='delly', help='DELLY command/path.')
    parser.add_argument('--tools-svaba', dest='__cfg__tools__svaba', type=str, default='svaba', help='SvABA command/path.')
    return parser



DEFAULT_SETTINGS = {'project': {'name': 'ctDNA_Tumor_Genome_GUI_Pipeline', 'temporary_directory': 'work/tmp'},
 'execution': {'wsl_distribution': '',
               'micromamba_environment': 'ctdna_core',
               'python_executable_in_wsl': 'python3',
               'micromamba_executable': '',
               'micromamba_root_prefix': ''},
 'references': {'targets_bed': '',
                'germline_resource_vcf': '',
                'panel_of_normals_vcf': '',
                'gene_gtf': '',
                'vep_cache': '',
                'vep_species': 'homo_sapiens',
                'vep_assembly': 'GRCh38'},
 'tools': {'fastqc': 'fastqc',
           'multiqc': 'multiqc',
           'cutadapt': 'cutadapt',
           'agent': 'agent.sh',
           'bwa_mem2': 'bwa-mem2',
           'samtools': 'samtools',
           'fgbio': 'fgbio',
           'spades': 'spades.py',
           'minimap2': 'minimap2',
           'cnvkit': 'cnvkit.py',
           'gatk': 'gatk',
           'bcftools': 'bcftools',
           'vep': 'vep'},
 'fastq_qc': {'recursive_scan': True, 'minimum_file_size_bytes': 100},
 'trimming': {'adapter_preset': 'Illumina TruSeq / standard ligation',
              'chemistry_processing_mode': 'generic',
              'trim_adapters': True,
              'adapter_r1': 'AGATCGGAAGAGCACACGTCTGAACTCCAGTCA',
              'adapter_r2': 'AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGT',
              'quality_cutoff': 20,
              'minimum_length': 30,
              'maximum_n_fraction': 0.1,
              'umi_mode': 'none',
              'r1_umi_length': 0,
              'r2_umi_length': 0,
              'keep_umi_intermediate_fastq': False},
 'alignment': {'platform': 'ILLUMINA',
               'sort_memory_per_thread': '1G',
               'recursive_fastq_scan': True,
               'auto_create_reference_indexes': True,
               'build_umi_consensus': True,
               'umi_group_strategy': 'adjacency',
               'umi_edit_distance': 1,
               'minimum_reads_per_family': 2,
               'consensus_minimum_base_quality': 20,
               'consensus_maximum_read_error_rate': 0.025,
               'consensus_maximum_base_error_rate': 0.1,
               'consensus_maximum_no_call_fraction': 0.2},
 'bam_qc': {'minimum_mapping_quality': 20,
            'minimum_base_quality': 20,
            'fragment_minimum_length': 30,
            'fragment_maximum_length': 800,
            'short_fragment_maximum': 150,
            'mononucleosome_minimum': 151,
            'mononucleosome_maximum': 220,
            'maximum_fragments_to_analyze': 2000000,
            'genome_bin_depth_enabled': False,
            'genome_bin_size_bp': 100000,
            'infer_high_depth_regions_enabled': True,
            'high_depth_threshold': 10,
            'high_depth_minimum_region_length_bp': 20,
            'high_depth_maximum_merge_gap_bp': 5,
            'high_depth_consensus_enabled': True,
            'high_depth_consensus_minimum_sample_percent': 50.0,
            'fragment_log_count_plot_enabled': False,
            'fragment_log_plot_xmin_bp': 20,
            'fragment_log_plot_xmax_bp': 500,
            'fragment_log_plot_minor_tick_bp': 5,
            'fragment_log_plot_reference_bp': 166},
 'abnormal_alignments': {'minimum_mapping_quality': 20,
                         'minimum_soft_clip_bases': 20,
                         'maximum_expected_insert_size': 1000,
                         'include_supplementary': True,
                         'include_secondary': False},
 'breakpoints': {'minimum_reference_separation_bp': 10000,
                 'manta_targeted_mode': False,
                 'manta_call_regions_bed': '',
                 'local_depth_minimum_mapping_quality': 20,
                 'spades_linux_work_root': '$HOME/ctdna_step06_spades_work'},
 'copy_number': {'enabled': True,
                 'reference_mode': 'existing',
                 'reference_cnn': '',
                 'normal_bam_folder': '',
                 'reference_fasta': '',
                 'targets_bed': '',
                 'output_reference_cnn': '',
                 'method': 'hybrid',
                 'male_reference': False,
                 'segment_method': 'haar',
                 'drop_low_coverage': False,
                 'gain_ratio_threshold': 1.2,
                 'loss_ratio_threshold': -1.25},
 'small_variants': {'enabled': True,
                    'initial_tumor_lod': 1.0,
                    'maximum_reads_per_alignment_start': 0,
                    'minimum_base_quality_score': 10,
                    'maximum_population_allele_frequency': 0.01,
                    'native_pair_hmm_threads': 4,
                    'matched_normal_bam': '',
                    'matched_normal_sample_name': ''},
 'integration': {'candidate_breakpoints_tsv': '',
                 'copy_number_segments_tsv': '',
                 'small_variants_tsv': '',
                 'nearby_variant_window_bp': 1000000,
                 'graph_include_normal_adjacencies': True,
                 'include_neutral_cnv_segments': True},
 'annotation': {'integrated_events_tsv': '',
                'derivative_chromosomes_tsv': '',
                'graph_nodes_tsv': '',
                'graph_edges_tsv': '',
                'pass_vcf_files': '',
                'run_local_gtf_variant_annotation': True,
                'run_vep': False,
                'maximum_table_rows': 300,
                'nearest_gene_maximum_distance_bp': 1000000},
 'sv_consolidation': {'candidate_breakpoints_tsv': '',
                      'breakpoint_tolerance_bp': 100,
                      'minimum_support_records': 1},
 'allele_specific_cnv': {'cnv_segments_tsv': '',
                         'germline_heterozygous_snp_vcf': '',
                         'germline_vcf_sample_name': '',
                         'minimum_snp_depth': 20,
                         'minimum_snps_per_segment': 3,
                         'loh_minor_allele_fraction_threshold': 0.15,
                         'neutral_signed_ratio_abs_limit': 1.2},
 'contamination': {'unfiltered_vcf_folder': '',
                   'bam_folder': '',
                   'common_sites_vcf': '',
                   'reference_fasta': '',
                   'minimum_population_allele_frequency': 0.01},
 'wbc_filter': {'final_vcf_folder': '',
                'wbc_bam_folder': '',
                'pairing_tsv': '',
                'minimum_wbc_depth': 20,
                'germline_vaf_threshold': 0.3,
                'hematopoietic_vaf_threshold': 0.01,
                'tumor_enriched_wbc_vaf_maximum': 0.005},
 'molecular_qc': {'classified_variants_tsv': '',
                  'cfdna_bam_folder': '',
                  'minimum_total_depth': 100,
                  'minimum_alt_molecules': 3,
                  'minimum_molecular_vaf': 0.001,
                  'preferred_molecule_tags': 'MI,RX,UR'},
 'tumor_fraction': {'molecular_variants_tsv': '',
                    'cnv_segments_tsv': '',
                    'allele_specific_loh_tsv': '',
                    'minimum_variants': 3,
                    'maximum_candidate_clonal_vaf': 0.45,
                    'top_fraction_of_variants': 0.25},
 'integration_full': {'consensus_sv_tsv': '',
                      'copy_number_segments_tsv': '',
                      'allele_specific_loh_tsv': '',
                      'molecular_variants_tsv': '',
                      'ctdna_fraction_tsv': '',
                      'reference_fasta': ''},
 'patient_reference': {'reference_fasta': '',
                       'consensus_sv_tsv': '',
                       'somatic_vcf': '',
                       'sample_id': 'PATIENT',
                       'junction_flank_bp': 750},
 'annotation_full': {'integrated_events_tsv': '',
                     'derivative_chromosomes_tsv': '',
                     'graph_nodes_tsv': '',
                     'graph_edges_tsv': '',
                     'gene_gtf': '',
                     'pass_vcf_folder': ''},
 'longitudinal': {'variant_results_folder': '',
                  'sample_metadata_tsv': '',
                  'minimum_alt_molecules': 2,
                  'maximum_variants_to_plot': 20}}

def _inject_cli_defaults_into_default_settings(settings: dict) -> dict:
    parser = build_cli_parser("Internal default initialization")
    if "project" not in settings or not isinstance(settings["project"], dict):
        raise KeyError("Missing required configuration section: project")
    if "threads" in settings["project"]:
        raise RuntimeError("project.threads is duplicated; define it only in build_cli_parser().")
    settings["project"]["threads"] = int(parser.get_default("threads"))
    for action in parser._actions:
        dest = action.dest
        if not isinstance(dest, str) or not dest.startswith("__cfg__"):
            continue
        path = tuple(dest[len("__cfg__"):].split("__"))
        dotted = ".".join(path)
        node = settings
        for key in path[:-1]:
            if key not in node or not isinstance(node[key], dict):
                raise KeyError(f"Missing configuration section while initializing {dotted}: {key}")
            node = node[key]
        leaf = path[-1]
        if leaf in node:
            raise RuntimeError(f"CLI-exposed default {dotted} is duplicated in DEFAULT_SETTINGS; define it only in build_cli_parser().")
        node[leaf] = copy.deepcopy(action.default)
    return settings

DEFAULT_SETTINGS = _inject_cli_defaults_into_default_settings(DEFAULT_SETTINGS)

import json
import logging
import math
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


LOGGER = logging.getLogger("ctdna_pipeline")


def setup_logging(log_file: Path | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, mode="a", encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=handlers,
        force=True,
    )


def _deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path | None = None) -> tuple[dict[str, Any], Path]:
    settings_path = Path(path) if path else (Path(__file__).resolve().parent / "step_user_settings.json")
    user = {}
    if settings_path.exists():
        with settings_path.open("r", encoding="utf-8") as handle:
            user = json.load(handle)
    return _deep_merge(DEFAULT_SETTINGS, user), settings_path


def project_path(project_root: Path, value: str | Path) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (project_root / path).resolve()


def to_wsl_style_path(value: str | Path) -> str:
    text = str(value)
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", text)
    if not match:
        return text
    drive = match.group(1).lower()
    remainder = match.group(2).replace("\\", "/")
    return f"/mnt/{drive}/{remainder}"


def normalized_input_path(value: str | Path) -> Path:
    text = str(value)
    if os.name != "nt":
        text = to_wsl_style_path(text)
    return Path(text)


def quote(value: str | Path) -> str:
    return shlex.quote(str(value))


def read_tsv(path: str | Path, dtype: Any = str) -> pd.DataFrame:
    return pd.read_csv(path, sep="\t", dtype=dtype, keep_default_na=False)


def write_tsv(frame: pd.DataFrame, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination, sep="\t", index=False)


def require_columns(frame: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{label} is missing required columns: {', '.join(missing)}")


def is_nonempty(value: Any) -> bool:
    return str(value).strip() not in {"", "NA", "N/A", "None", "none", "null"}


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def threads(config: dict[str, Any]) -> int:
    return max(1, int(config['project']['threads']))


def executable_exists(executable: str) -> bool:
    if "/" in executable:
        return Path(executable).exists()
    return shutil.which(executable) is not None


def require_tools(config: dict[str, Any], tool_names: Iterable[str], dry_run: bool) -> None:
    if dry_run:
        return
    missing: list[str] = []
    tools = config['tools']
    for name in tool_names:
        executable = str(tools.get(name, "")).strip()
        if not executable or not executable_exists(executable):
            missing.append(f"{name}={executable or '<not configured>'}")
    if missing:
        raise FileNotFoundError("Required tool(s) not found: " + ", ".join(missing))


def run_command(
    command: list[str] | str,
    log_file: Path,
    *,
    dry_run: bool = False,
    shell: bool = False,
    cwd: Path | None = None,
) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    display = (
        " ".join(shlex.quote(str(item)) for item in command)
        if isinstance(command, list)
        else command
    )
    LOGGER.info("COMMAND: %s", display)

    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"\nCOMMAND:\n{display}\n")
        if dry_run:
            handle.write("DRY RUN: command not executed.\n")
            return
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            shell=shell,
            executable="/bin/bash" if shell else None,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {completed.returncode}. See {log_file}."
        )


def save_json(data: Any, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_step_status(
    output_dir: Path,
    step_name: str,
    status: str,
    message: str,
    sample_count: int = 0,
    plot_files: list[Path] | None = None,
) -> None:
    plot_files = plot_files or []
    save_json(
        {
            "step_name": step_name,
            "status": status,
            "message": message,
            "sample_count": int(sample_count),
            "plot_files": [str(path) for path in plot_files],
        },
        output_dir / "step_status.json",
    )


def save_placeholder_plot(
    output_path: Path,
    title: str,
    message: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(9, 5))
    axis.axis("off")
    axis.text(
        0.5,
        0.56,
        title,
        ha="center",
        va="center",
        fontsize=16,
        transform=axis.transAxes,
    )
    axis.text(
        0.5,
        0.40,
        message,
        ha="center",
        va="center",
        fontsize=11,
        wrap=True,
        transform=axis.transAxes,
    )
    figure.tight_layout()
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def save_bar_plot(
    labels: list[str],
    values: list[float],
    output_path: Path,
    title: str,
    y_label: str,
    rotate: int = 0,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(max(8, len(labels) * 0.75), 5.5))
    positions = np.arange(len(labels))
    axis.bar(positions, values)
    axis.set_xticks(positions)
    axis.set_xticklabels(labels, rotation=rotate, ha="right" if rotate else "center")
    axis.set_ylabel(y_label)
    axis.set_title(title)
    axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def save_stacked_status_plot(
    summary: pd.DataFrame,
    category_column: str,
    status_column: str,
    output_path: Path,
    title: str,
) -> None:
    if summary.empty:
        save_placeholder_plot(output_path, title, "No records were available.")
        return

    table = pd.crosstab(summary[category_column], summary[status_column])

    figure, axis = plt.subplots(figsize=(10, 6))
    bottom = np.zeros(len(table), dtype=float)
    x = np.arange(len(table))

    # Fixed biological/QC status colors.
    status_colors = {
        "PASS": "green",
        "WARN": "orange",
        "FAIL": "red",
    }

    # Draw in a stable order instead of relying on crosstab column order.
    preferred_order = ["PASS", "WARN", "FAIL"]

    for status_name in preferred_order:
        matching_columns = [
            column
            for column in table.columns
            if str(column).strip().upper() == status_name
        ]
        if not matching_columns:
            continue

        column = matching_columns[0]
        values = table[column].to_numpy(dtype=float)

        axis.bar(
            x,
            values,
            bottom=bottom,
            label=status_name,
            color=status_colors[status_name],
        )
        bottom += values

    # Preserve any unexpected status values in gray rather than dropping them.
    for column in table.columns:
        status_name = str(column).strip().upper()
        if status_name in status_colors:
            continue

        values = table[column].to_numpy(dtype=float)
        axis.bar(
            x,
            values,
            bottom=bottom,
            label=str(column),
            color="gray",
        )
        bottom += values

    axis.set_xticks(x)
    axis.set_xticklabels(
        table.index.astype(str),
        rotation=45,
        ha="right",
    )
    axis.set_ylabel("Count")
    axis.set_title(title)
    axis.legend()
    axis.grid(axis="y", alpha=0.25)

    figure.tight_layout()
    figure.savefig(output_path, dpi=180)
    plt.close(figure)

def bh_adjust(p_values: list[float]) -> list[float]:
    if not p_values:
        return []
    ordered = sorted(enumerate(p_values), key=lambda pair: pair[1])
    adjusted = [1.0] * len(p_values)
    running = 1.0
    n = len(p_values)
    for reverse_index, (original_index, p_value) in enumerate(
        reversed(ordered), start=1
    ):
        rank = n - reverse_index + 1
        candidate = min(1.0, float(p_value) * n / rank)
        running = min(running, candidate)
        adjusted[original_index] = running
    return adjusted


def safe_float(value: Any, default: float = math.nan) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_reference_name_list(value: object) -> list[str]:
    """Parse an editable canonical-reference list while preserving order."""
    text = str(value or "").strip()
    if not text:
        return []
    tokens = re.split(r"[;,\r\n]+", text)
    output: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        name = token.strip()
        if name and name not in seen:
            output.append(name)
            seen.add(name)
    return output


def reference_names_from_fasta(reference: str | Path) -> list[str]:
    """
    Return FASTA reference sequence names in reference order.

    Prefer an existing samtools .fai index because it is instant even for a
    multi-gigabyte genome FASTA. If no .fai is present, stream only FASTA header
    lines without loading sequence data into memory.
    """
    fasta = Path(reference)
    fai = Path(str(fasta) + ".fai")
    names: list[str] = []
    seen: set[str] = set()

    if fai.exists() and fai.is_file() and fai.stat().st_size > 0:
        with fai.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                name = line.split("\t", 1)[0].strip()
                if name and name not in seen:
                    names.append(name)
                    seen.add(name)
        if names:
            return names

    if not fasta.exists() or not fasta.is_file():
        raise FileNotFoundError(f"Reference FASTA was not found: {fasta}")

    with fasta.open("rb") as handle:
        for raw in handle:
            if not raw.startswith(b">"):
                continue
            header = raw[1:].strip().decode("utf-8", errors="replace")
            name = header.split(None, 1)[0].strip() if header else ""
            if name and name not in seen:
                names.append(name)
                seen.add(name)

    if not names:
        raise ValueError(f"No FASTA reference sequence names were found in: {fasta}")
    return names


_STANDARD_CANONICAL_RE = re.compile(
    r"^(?:chr)?(?:[1-9]|1[0-9]|2[0-2]|X|Y)$",
    re.IGNORECASE,
)


def suggested_standard_canonical_references(reference_names: Iterable[str]) -> list[str]:
    """Suggest autosomes 1-22 plus X/Y, retaining the FASTA's exact names/order."""
    return [
        str(name)
        for name in reference_names
        if _STANDARD_CANONICAL_RE.fullmatch(str(name).strip())
    ]


def classify_breakpoints_by_reference(
    table: pd.DataFrame,
    canonical_chromosomes: Iterable[str],
) -> pd.DataFrame:
    """
    Label each breakend and each event according to the user-selected canonical set.

    A breakpoint is CANONICAL only when BOTH CHROM1 and CHROM2 are in the
    canonical set. Every other event is NON_CANONICAL and is retained for review.
    """
    canonical = {str(name).strip() for name in canonical_chromosomes if str(name).strip()}
    output = table.copy()

    for column in [
        "CHROM1_REFERENCE_CLASS",
        "CHROM2_REFERENCE_CLASS",
        "BREAKPOINT_REFERENCE_CLASS",
    ]:
        if column not in output.columns:
            output[column] = pd.Series(dtype="object")

    if output.empty:
        return output

    chrom1 = output.get("CHROM1", pd.Series("", index=output.index)).astype(str)
    chrom2 = output.get("CHROM2", pd.Series("", index=output.index)).astype(str)
    side1 = chrom1.map(lambda name: "CANONICAL" if name in canonical else "NON_CANONICAL")
    side2 = chrom2.map(lambda name: "CANONICAL" if name in canonical else "NON_CANONICAL")

    output["CHROM1_REFERENCE_CLASS"] = side1
    output["CHROM2_REFERENCE_CLASS"] = side2
    output["BREAKPOINT_REFERENCE_CLASS"] = [
        "CANONICAL"
        if left == "CANONICAL" and right == "CANONICAL"
        else "NON_CANONICAL"
        for left, right in zip(side1, side2)
    ]
    return output


def find_plot_files(output_dir: Path) -> list[Path]:
    return sorted(
        [
            path
            for pattern in ("*.png", "*.jpg", "*.jpeg")
            for path in output_dir.rglob(pattern)
        ]
    )

import gzip
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd


FASTQ_SUFFIXES = (".fastq.gz", ".fq.gz", ".fastq", ".fq")

READ_PATTERNS = (
    re.compile(
        r"^(?P<sample>.+?)(?:[_\\.-])R(?P<read>[12])(?:[_\\.-].*)?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?P<sample>.+?)(?:[_\\.-])READ(?P<read>[12])(?:[_\\.-].*)?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?P<sample>.+?)(?:[_\\.-])(?P<read>[12])(?:[_\\.-].*)?$",
        re.IGNORECASE,
    ),
)

HEADER_READ_TOKEN = re.compile(r"^[12]:")


def strip_fastq_suffix(name: str) -> str:
    lower = name.lower()
    for suffix in FASTQ_SUFFIXES:
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return name


def classify_fastq_name(path: Path) -> tuple[str, str]:
    """Infer sample prefix and R1/R2 role from a FASTQ filename."""
    stem = strip_fastq_suffix(path.name)
    for pattern in READ_PATTERNS:
        match = pattern.match(stem)
        if match:
            return match.group("sample"), match.group("read")
    return stem, "SE"


def _open_fastq_text(path: Path):
    if path.name.lower().endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def _core_read_name_from_header(header: str) -> str:
    token = header.strip().split(maxsplit=1)[0].lstrip("@")
    return re.sub(r"/[12]$", "", token)


def infer_read_number_from_header(path: Path) -> str | None:
    """Infer read 1/read 2 from /1,/2 or CASAVA 1:/2: header information."""
    try:
        with _open_fastq_text(path) as handle:
            header = handle.readline().strip()
    except (OSError, EOFError, UnicodeError):
        return None

    if not header.startswith("@"):
        return None

    fields = header.split()
    first = fields[0]
    if first.endswith("/1"):
        return "1"
    if first.endswith("/2"):
        return "2"
    if len(fields) >= 2 and HEADER_READ_TOKEN.match(fields[1]):
        return fields[1][0]
    return None


def read_header_fingerprint(path: Path, maximum_records: int = 250) -> list[str]:
    """
    Read only a small prefix of FASTQ identifiers.
    The complete FASTQ is never loaded into memory.
    """
    names: list[str] = []
    try:
        with _open_fastq_text(path) as handle:
            for _ in range(maximum_records):
                header = handle.readline()
                if not header:
                    break
                sequence = handle.readline()
                plus = handle.readline()
                quality = handle.readline()
                if not quality:
                    break
                if not header.startswith("@"):
                    break
                names.append(_core_read_name_from_header(header))
    except (OSError, EOFError, UnicodeError):
        return []
    return names


def header_pair_score(
    r1: Path,
    r2: Path,
    maximum_records: int = 250,
) -> tuple[float, int, int]:
    """
    Compare physical FASTQ read/cluster identifiers position-by-position.
    True paired R1/R2 files normally have matching identifiers in the same order.
    """
    names1 = read_header_fingerprint(r1, maximum_records)
    names2 = read_header_fingerprint(r2, maximum_records)
    compared = min(len(names1), len(names2))
    if compared == 0:
        return 0.0, 0, 0

    matching = sum(
        name1 == name2
        for name1, name2 in zip(names1[:compared], names2[:compared])
    )
    return matching / compared, matching, compared


def find_fastq_files(input_dir: Path, recursive: bool = True) -> list[Path]:
    iterator = input_dir.rglob("*") if recursive else input_dir.glob("*")
    return sorted(
        path.resolve()
        for path in iterator
        if path.is_file()
        and any(path.name.lower().endswith(suffix) for suffix in FASTQ_SUFFIXES)
    )


def _unique_sample_id(base: str, used: set[str]) -> str:
    candidate = base
    number = 2
    while candidate in used:
        candidate = f"{base}_part{number}"
        number += 1
    used.add(candidate)
    return candidate


def _choose_header_pairs(
    r1_files: list[tuple[Path, str]],
    r2_files: list[tuple[Path, str]],
    minimum_header_match_fraction: float,
    maximum_header_records: int,
) -> tuple[
    list[tuple[Path, str, Path, str, float, int]],
    list[tuple[Path, str]],
    list[tuple[Path, str]],
]:
    """Rescue unresolved mate pairs using actual FASTQ read identifiers."""
    candidates: list[tuple[float, int, Path, str, Path, str]] = []

    for r1_path, r1_guess in r1_files:
        for r2_path, r2_guess in r2_files:
            score, matching, compared = header_pair_score(
                r1_path,
                r2_path,
                maximum_records=maximum_header_records,
            )
            sufficient = compared >= 10 or (
                compared > 0 and matching == compared
            )
            if sufficient and score >= minimum_header_match_fraction:
                candidates.append(
                    (score, compared, r1_path, r1_guess, r2_path, r2_guess)
                )

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)

    used_r1: set[Path] = set()
    used_r2: set[Path] = set()
    selected: list[tuple[Path, str, Path, str, float, int]] = []

    for score, compared, r1_path, r1_guess, r2_path, r2_guess in candidates:
        if r1_path in used_r1 or r2_path in used_r2:
            continue
        used_r1.add(r1_path)
        used_r2.add(r2_path)
        selected.append(
            (r1_path, r1_guess, r2_path, r2_guess, score, compared)
        )

    remaining_r1 = [x for x in r1_files if x[0] not in used_r1]
    remaining_r2 = [x for x in r2_files if x[0] not in used_r2]
    return selected, remaining_r1, remaining_r2


def detect_fastq_samples(
    input_dir: Path,
    recursive: bool = True,
    minimum_file_size_bytes: int = 100,
    minimum_header_match_fraction: float = 0.95,
    maximum_header_records: int = 250,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Detect FASTQ libraries with filename pairing plus FASTQ-header rescue.

    A pair such as:
        Sample1_R1.fq.gz
        Sample2_R2.fq.gz
    is accepted when the actual FASTQ read identifiers prove that the two
    files are mates, even though the filename prefixes differ.
    """
    files = find_fastq_files(input_dir, recursive)

    file_rows: list[dict[str, object]] = []
    r1_candidates: list[tuple[Path, str]] = []
    r2_candidates: list[tuple[Path, str]] = []
    se_candidates: list[tuple[Path, str]] = []

    for path in files:
        sample_guess, filename_read = classify_fastq_name(path)
        header_read = infer_read_number_from_header(path)

        if filename_read in {"1", "2"}:
            read = filename_read
            role_source = "FILENAME"
        elif header_read in {"1", "2"}:
            read = header_read
            role_source = "FASTQ_HEADER"
        else:
            read = "SE"
            role_source = "UNKNOWN_SINGLE_END"

        if read == "1":
            r1_candidates.append((path, sample_guess))
        elif read == "2":
            r2_candidates.append((path, sample_guess))
        else:
            se_candidates.append((path, sample_guess))

        size = path.stat().st_size
        file_rows.append(
            {
                "FILE": str(path),
                "SAMPLE_ID_GUESS": sample_guess,
                "FILENAME_READ_GUESS": filename_read,
                "HEADER_READ_GUESS": header_read or "",
                "READ_GUESS": read,
                "READ_ROLE_SOURCE": role_source,
                "FILE_SIZE_BYTES": size,
                "SIZE_STATUS": (
                    "PASS" if size >= minimum_file_size_bytes else "WARN_SMALL"
                ),
            }
        )

    sample_rows: list[dict[str, object]] = []
    used_sample_ids: set[str] = set()

    r1_by_sample: dict[str, list[Path]] = defaultdict(list)
    r2_by_sample: dict[str, list[Path]] = defaultdict(list)
    for path, sample in r1_candidates:
        r1_by_sample[sample].append(path)
    for path, sample in r2_candidates:
        r2_by_sample[sample].append(path)

    unresolved_r1: list[tuple[Path, str]] = []
    unresolved_r2: list[tuple[Path, str]] = []

    # Stage 1: conventional identical-prefix filename pairing.
    for sample in sorted(set(r1_by_sample) | set(r2_by_sample)):
        r1s = sorted(r1_by_sample.get(sample, []))
        r2s = sorted(r2_by_sample.get(sample, []))
        pair_count = min(len(r1s), len(r2s))

        for index in range(pair_count):
            r1 = r1s[index]
            r2 = r2s[index]
            score, _matching, compared = header_pair_score(
                r1, r2, maximum_records=maximum_header_records
            )
            sample_id = _unique_sample_id(sample, used_sample_ids)
            sample_rows.append(
                {
                    "SAMPLE_ID": sample_id,
                    "SEQUENCING_LAYOUT": "PAIRED_END",
                    "R1": str(r1),
                    "R2": str(r2),
                    "SINGLE_END_FASTQ": "",
                    "PAIRING_STATUS": "PAIRED",
                    "PAIRING_METHOD": "FILENAME",
                    "HEADER_MATCH_PERCENT": (
                        round(score * 100.0, 2) if compared else ""
                    ),
                    "HEADER_RECORDS_COMPARED": compared if compared else "",
                    "R1_SAMPLE_GUESS": sample,
                    "R2_SAMPLE_GUESS": sample,
                }
            )

        unresolved_r1.extend((p, sample) for p in r1s[pair_count:])
        unresolved_r2.extend((p, sample) for p in r2s[pair_count:])

    # Stage 2: filename mismatch rescue using actual FASTQ identifiers.
    rescued, unresolved_r1, unresolved_r2 = _choose_header_pairs(
        unresolved_r1,
        unresolved_r2,
        minimum_header_match_fraction=minimum_header_match_fraction,
        maximum_header_records=maximum_header_records,
    )

    for r1, r1_guess, r2, r2_guess, score, compared in rescued:
        sample_id = _unique_sample_id(r1_guess, used_sample_ids)
        sample_rows.append(
            {
                "SAMPLE_ID": sample_id,
                "SEQUENCING_LAYOUT": "PAIRED_END",
                "R1": str(r1),
                "R2": str(r2),
                "SINGLE_END_FASTQ": "",
                "PAIRING_STATUS": "PAIRED",
                "PAIRING_METHOD": "FASTQ_HEADER",
                "HEADER_MATCH_PERCENT": round(score * 100.0, 2),
                "HEADER_RECORDS_COMPARED": compared,
                "R1_SAMPLE_GUESS": r1_guess,
                "R2_SAMPLE_GUESS": r2_guess,
            }
        )

    # Only after both pairing methods fail do we report a missing mate.
    for path, sample in unresolved_r1:
        sample_id = _unique_sample_id(sample, used_sample_ids)
        sample_rows.append(
            {
                "SAMPLE_ID": sample_id,
                "SEQUENCING_LAYOUT": "PAIRED_END",
                "R1": str(path),
                "R2": "",
                "SINGLE_END_FASTQ": "",
                "PAIRING_STATUS": "UNPAIRED_MATE",
                "PAIRING_METHOD": "NO_MATCH",
                "HEADER_MATCH_PERCENT": "",
                "HEADER_RECORDS_COMPARED": "",
                "R1_SAMPLE_GUESS": sample,
                "R2_SAMPLE_GUESS": "",
            }
        )

    for path, sample in unresolved_r2:
        sample_id = _unique_sample_id(sample, used_sample_ids)
        sample_rows.append(
            {
                "SAMPLE_ID": sample_id,
                "SEQUENCING_LAYOUT": "PAIRED_END",
                "R1": "",
                "R2": str(path),
                "SINGLE_END_FASTQ": "",
                "PAIRING_STATUS": "UNPAIRED_MATE",
                "PAIRING_METHOD": "NO_MATCH",
                "HEADER_MATCH_PERCENT": "",
                "HEADER_RECORDS_COMPARED": "",
                "R1_SAMPLE_GUESS": "",
                "R2_SAMPLE_GUESS": sample,
            }
        )

    for path, sample in se_candidates:
        sample_id = _unique_sample_id(sample, used_sample_ids)
        sample_rows.append(
            {
                "SAMPLE_ID": sample_id,
                "SEQUENCING_LAYOUT": "SINGLE_END",
                "R1": "",
                "R2": "",
                "SINGLE_END_FASTQ": str(path),
                "PAIRING_STATUS": "SINGLE_END",
                "PAIRING_METHOD": "SINGLE_END_OR_UNKNOWN",
                "HEADER_MATCH_PERCENT": "",
                "HEADER_RECORDS_COMPARED": "",
                "R1_SAMPLE_GUESS": "",
                "R2_SAMPLE_GUESS": "",
            }
        )

    samples = pd.DataFrame(
        sample_rows,
        columns=[
            "SAMPLE_ID",
            "SEQUENCING_LAYOUT",
            "R1",
            "R2",
            "SINGLE_END_FASTQ",
            "PAIRING_STATUS",
            "PAIRING_METHOD",
            "HEADER_MATCH_PERCENT",
            "HEADER_RECORDS_COMPARED",
            "R1_SAMPLE_GUESS",
            "R2_SAMPLE_GUESS",
        ],
    )

    if not samples.empty:
        status_order = {"PAIRED": 0, "UNPAIRED_MATE": 1, "SINGLE_END": 2}
        samples["_ORDER"] = samples["PAIRING_STATUS"].map(status_order).fillna(9)
        samples = (
            samples.sort_values(["_ORDER", "SAMPLE_ID"])
            .drop(columns="_ORDER")
            .reset_index(drop=True)
        )

    return samples, pd.DataFrame(file_rows)

import gzip
import re
from pathlib import Path
from typing import Iterator, TextIO


def open_text(path: Path, mode: str) -> TextIO:
    if path.suffix.lower() == ".gz":
        return gzip.open(path, mode + "t", encoding="utf-8")
    return path.open(mode, encoding="utf-8")


def read_records(handle: TextIO) -> Iterator[tuple[str, str, str, str]]:
    while True:
        header = handle.readline()
        if not header:
            return
        sequence = handle.readline()
        plus = handle.readline()
        quality = handle.readline()
        if not quality:
            raise ValueError("A FASTQ file ended inside a record.")
        yield (
            header.rstrip("\n"),
            sequence.rstrip("\n"),
            plus.rstrip("\n"),
            quality.rstrip("\n"),
        )


def core_read_name(header: str) -> str:
    token = header.split()[0].lstrip("@")
    return re.sub(r"/[12]$", "", token)


def header_with_umi(
    header: str,
    umi: str,
    umi_mode: str = "single",
) -> str:
    """
    Preserve the extracted UMI as metadata after removing its bases from the
    biological read sequence.

    New read-name markers:
      __UMI_SINGLE__<barcode>
      __UMI_DUPLEX__<barcode>

    Step 03 can therefore recover the UMI type automatically without a
    manifest and without asking the user to select single/duplex again.
    """
    mode = str(umi_mode).strip().lower()
    if mode not in {"single", "duplex"}:
        raise ValueError(
            "header_with_umi requires umi_mode='single' or 'duplex'."
        )

    pieces = header.split(maxsplit=1)
    name = re.sub(r"/[12]$", "", pieces[0].lstrip("@"))
    suffix = " " + pieces[1] if len(pieces) == 2 else ""
    marker = "__UMI_SINGLE__" if mode == "single" else "__UMI_DUPLEX__"
    return f"@{name}{marker}{umi}{suffix}"

from pathlib import Path

import pandas as pd


def _is_real_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size >= 0


def sample_id_from_bam(path: Path) -> str:
    name = path.name
    suffixes = (
        ".analysis_ready.bam",
        ".aligned.sorted.bam",
        ".abnormal_pairs.bam",
        ".bam",
    )
    lower = name.lower()
    for suffix in suffixes:
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def discover_bams(input_dir: Path, recursive: bool = True) -> pd.DataFrame:
    """Discover BAM files directly, preferring analysis-ready BAMs per sample."""
    iterator = input_dir.rglob("*.bam") if recursive else input_dir.glob("*.bam")
    files = sorted(path.resolve() for path in iterator if _is_real_file(path))

    # Ignore obvious intermediate BAMs when a final BAM is available.
    ignored_tokens = (
        "markdup.01.",
        "markdup.02.",
        "markdup.03.",
        "01.rx_tagged",
        "02.umi_grouped",
        "05.consensus.mapped",
        "05.consensus.unmapped",
        "06.consensus.zipped",
        "07.consensus.filtered",
    )
    candidates = [
        p for p in files if not any(token in p.name.lower() for token in ignored_tokens)
    ]

    by_sample: dict[str, list[Path]] = {}
    for path in candidates:
        by_sample.setdefault(sample_id_from_bam(path), []).append(path)

    rows: list[dict[str, str]] = []
    for sample_id, sample_files in sorted(by_sample.items()):
        def score(path: Path) -> tuple[int, int]:
            name = path.name.lower()
            if name.endswith(".analysis_ready.bam"):
                priority = 0
            elif name.endswith(".aligned.sorted.bam"):
                priority = 1
            elif name.endswith(".bam"):
                priority = 2
            else:
                priority = 3
            return priority, len(str(path))

        selected = sorted(sample_files, key=score)[0]
        rows.append(
            {
                "SAMPLE_ID": sample_id,
                "BAM": str(selected),
                "BAM_DISCOVERY": "DIRECT_SCAN",
            }
        )
    return pd.DataFrame(rows, columns=["SAMPLE_ID", "BAM", "BAM_DISCOVERY"])


def concat_named_tables(input_dir: Path, filename: str) -> pd.DataFrame:
    """Find every exact-named TSV recursively and concatenate them."""
    frames: list[pd.DataFrame] = []
    for path in sorted(input_dir.rglob(filename)):
        if not path.is_file() or path.stat().st_size == 0:
            continue
        try:
            frame = pd.read_csv(path, sep="\t")
        except pd.errors.EmptyDataError:
            continue
        if not frame.empty:
            frame = frame.copy()
            frame["SOURCE_FILE"] = str(path.resolve())
            frames.append(frame)
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def discover_pass_vcfs(input_dir: Path) -> pd.DataFrame:
    """Find PASS small-variant VCF/VCF.GZ outputs directly."""
    patterns = (
        "*.pass.vcf.gz",
        "*.pass.vcf",
        "*.PASS.vcf.gz",
        "*.PASS.vcf",
        "*.filtered.vcf.gz",
        "*.filtered.vcf",
    )
    seen: set[Path] = set()
    rows: list[dict[str, str]] = []
    for pattern in patterns:
        for path in sorted(input_dir.rglob(pattern)):
            resolved = path.resolve()
            if resolved in seen or not path.is_file():
                continue
            seen.add(resolved)
            name = path.name
            sample = name
            for suffix in (
                ".pass.vcf.gz", ".pass.vcf", ".PASS.vcf.gz", ".PASS.vcf",
                ".filtered.vcf.gz", ".filtered.vcf", ".vcf.gz", ".vcf",
            ):
                if sample.endswith(suffix):
                    sample = sample[: -len(suffix)]
                    break
            rows.append({"SAMPLE_ID": sample, "VCF": str(resolved)})
    return pd.DataFrame(rows, columns=["SAMPLE_ID", "VCF"])



def discover_abnormal_inputs(input_dir: Path) -> pd.DataFrame:
    """Discover only Step-05 abnormal FASTQ/FQ files for SPAdes, grouped by sample."""
    rows: dict[str, dict[str, str]] = {}

    suffix_map = {
        ".abnormal.r1.fastq.gz": "ABNORMAL_R1_FASTQ",
        ".abnormal.r2.fastq.gz": "ABNORMAL_R2_FASTQ",
        ".abnormal.singletons.fastq.gz": "ABNORMAL_SINGLETON_FASTQ",
        ".abnormal.r1.fastq": "ABNORMAL_R1_FASTQ",
        ".abnormal.r2.fastq": "ABNORMAL_R2_FASTQ",
        ".abnormal.singletons.fastq": "ABNORMAL_SINGLETON_FASTQ",
        ".abnormal.r1.fq.gz": "ABNORMAL_R1_FASTQ",
        ".abnormal.r2.fq.gz": "ABNORMAL_R2_FASTQ",
        ".abnormal.singletons.fq.gz": "ABNORMAL_SINGLETON_FASTQ",
        ".abnormal.r1.fq": "ABNORMAL_R1_FASTQ",
        ".abnormal.r2.fq": "ABNORMAL_R2_FASTQ",
        ".abnormal.singletons.fq": "ABNORMAL_SINGLETON_FASTQ",
    }

    for path in sorted(input_dir.rglob("*")):
        if not path.is_file() or path.stat().st_size == 0:
            continue
        lower_name = path.name.lower()
        for suffix, column in suffix_map.items():
            if lower_name.endswith(suffix):
                sample = path.name[: -len(suffix)]
                rows.setdefault(sample, {"SAMPLE_ID": sample})[column] = str(path.resolve())
                break

    columns = [
        "SAMPLE_ID",
        "ABNORMAL_R1_FASTQ",
        "ABNORMAL_R2_FASTQ",
        "ABNORMAL_SINGLETON_FASTQ",
    ]
    result = pd.DataFrame(list(rows.values()))
    if result.empty:
        return pd.DataFrame(columns=columns)
    for col in columns:
        if col not in result.columns:
            result[col] = ""
    return result[columns].fillna("")

def sample_af(sample: Any) -> float:
    try:
        af = sample.get("AF")
        if af is not None:
            if isinstance(af, tuple):
                return float(af[0]) if af else float("nan")
            return float(af)
        ad = sample.get("AD")
        if ad and len(ad) >= 2 and sum(ad) > 0:
            return float(ad[1]) / float(sum(ad))
    except Exception:
        pass
    return float("nan")


def vcf_filter_text(record: Any) -> str:
    values = list(record.filter.keys())
    return ";".join(values) if values else "UNFILTERED"


def svtype_from_record(record: Any) -> str:
    try:
        if "SVTYPE" in record.info:
            return str(record.info["SVTYPE"])
    except Exception:
        pass
    alternate = record.alts[0] if record.alts else ""
    if "[" in alternate or "]" in alternate:
        return "BND"
    if len(record.ref) == 1 and len(alternate) == 1:
        return "SNV"
    return "INDEL"


def dataframe_or_empty(rows: list[dict[str, object]], columns: list[str]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    for column in columns:
        if column not in frame.columns:
            frame[column] = pd.Series(dtype="object")
    return frame[columns]


STEP_ACCENTS = (
    "#176B87", "#1D7A8C", "#2A9D8F", "#4C956C", "#7A9E35",
    "#C49A00", "#D97706", "#C65D2E", "#B23A48", "#9C3D74",
    "#7B4DB4", "#5B5FC7", "#3F6DB5", "#246A73", "#50723C",
    "#8A5A44", "#6B5CA5",
)

@dataclass(frozen=True)
class StepSpecification:
    number: int
    title: str
    description: str
    default_input_dir: str
    default_output_dir: str
    accent_color: str = ""
    @property
    def resolved_accent_color(self) -> str:
        return self.accent_color or STEP_ACCENTS[(max(1, int(self.number))-1) % len(STEP_ACCENTS)]

def _setting_get(settings: dict, dotted: str) -> Any:
    current: Any = settings
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"Missing required configuration setting: {dotted}")
        current = current[part]
    return current

def _setting_set(settings: dict, dotted: str, value: Any) -> None:
    current = settings
    parts = dotted.split(".")
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"Missing required configuration setting path: {dotted}")
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        raise KeyError(f"Unknown configuration setting: {dotted}")
    current[parts[-1]] = value

def _windows_to_wsl(value: str | Path) -> str:
    text = str(value)
    match = re.match(r"^([A-Za-z]):[\\\\/](.*)$", text)
    if match:
        return f"/mnt/{match.group(1).lower()}/{match.group(2).replace(chr(92), '/')}"
    return text.replace(chr(92), "/")

def _wsl_base_args(distro: str) -> list[str]:
    args = ["wsl.exe"]
    if distro.strip():
        args += ["-d", distro.strip()]
    return args

def _detect_micromamba(distro: str) -> tuple[str, str]:
    base = _wsl_base_args(distro)
    probe = subprocess.run(base + ["bash", "-lc", "command -v micromamba"], capture_output=True, text=True)
    executable = probe.stdout.strip() if probe.returncode == 0 else ""
    root = ""
    if executable:
        cmd = f"{shlex.quote(executable)} info --json"
        info = subprocess.run(base + ["bash", "-lc", cmd], capture_output=True, text=True)
        if info.returncode == 0:
            try:
                data = json.loads(info.stdout)
                root = str(data.get("root_prefix", "") or "")
            except Exception:
                pass
    return executable, root

def _scan_folder(path: Path, field: dict) -> tuple[int, int, list[str]]:
    if not path.exists() or not path.is_dir():
        return 0, 0, []
    globs = field.get("scan_globs") or ["*"]
    candidates=[]
    seen=set()
    for pattern in globs:
        for p in path.rglob(pattern):
            if p.is_file() and p not in seen:
                seen.add(p); candidates.append(p)
    accepts=[]; rejects=[]
    need_any=[x.lower() for x in field.get("accept_name_contains_any", [])]
    reject=[x.lower() for x in field.get("reject_name_contains", [])]
    for p in candidates:
        name=p.name.lower()
        ok=(not need_any or any(tok in name for tok in need_any)) and not any(tok in name for tok in reject)
        (accepts if ok else rejects).append(p)
    return len(accepts), len(rejects), [str(p) for p in accepts[:10]]

def _validate_expected_file(path: Path, field: dict) -> None:
    expected = field.get("expected_name", "")
    lower_name = path.name.lower()
    if expected and lower_name != str(expected).lower():
        raise ValueError(f"Expected file named '{expected}', selected '{path.name}'.")
    suffixes = [s.lower() for s in field.get("allowed_suffixes", [])]
    if suffixes and not any(lower_name.endswith(s) for s in suffixes):
        raise ValueError(f"Selected file does not match allowed type(s): {', '.join(suffixes)}")
    accept_any = [str(x).lower() for x in field.get("accept_name_contains_any", [])]
    reject = [str(x).lower() for x in field.get("reject_name_contains", [])]
    if accept_any and not any(token in lower_name for token in accept_any):
        raise ValueError(
            "Selected file name must contain at least one of: "
            + ", ".join(accept_any)
        )
    if reject and any(token in lower_name for token in reject):
        raise ValueError(
            "Selected file is rejected because its name contains a forbidden token: "
            + ", ".join(token for token in reject if token in lower_name)
        )


def recommend_spades_kmers_from_max_read_length(maximum_read_length: int) -> tuple[list[int], str]:
    """Recommend manual SPAdes k-mers from the requested maximum-read-length table."""
    length = int(maximum_read_length)
    if length <= 0:
        return [], "No reads"
    # The user's table uses approximate read-length bands (~50/~75/~100/~150/~250),
    # so choose the nearest band rather than treating 151 bp as a 250-bp library.
    if length <= 62:
        proposed, band = [21, 33], "~50 bp"
    elif length <= 87:
        proposed, band = [21, 33, 55], "~75 bp"
    elif length <= 125:
        proposed, band = [21, 33, 55], "~100 bp"
    elif length <= 200:
        proposed, band = [21, 33, 55, 77], "~150 bp"
    else:
        proposed, band = [21, 33, 55, 77, 99, 127], "~250 bp"
    usable = [k for k in proposed if k <= length and k < 128 and k % 2 == 1]
    if usable:
        return usable, band
    fallback = min(21, length)
    if fallback % 2 == 0:
        fallback -= 1
    return ([fallback] if fallback >= 3 else []), band


def _counter_quantile(length_counts: Counter, total_reads: int, fraction: float) -> int:
    if total_reads <= 0 or not length_counts:
        return 0
    target = max(1, math.ceil(float(total_reads) * float(fraction)))
    cumulative = 0
    for length in sorted(length_counts):
        cumulative += int(length_counts[length])
        if cumulative >= target:
            return int(length)
    return int(max(length_counts))


def _summarize_spades_length_counts(
    *,
    length_counts: Counter,
    total_reads: int,
    files: list[Path],
    file_rows: list[dict[str, object]],
    source_type: str,
    ignored_files: list[Path] | None = None,
) -> dict[str, object]:
    if total_reads <= 0 or not length_counts:
        raise ValueError(f"The abnormal {source_type} source contains zero usable primary reads.")
    minimum = int(min(length_counts))
    maximum = int(max(length_counts))
    median = _counter_quantile(length_counts, total_reads, 0.50)
    p90 = _counter_quantile(length_counts, total_reads, 0.90)
    p95 = _counter_quantile(length_counts, total_reads, 0.95)
    recommended, table_band = recommend_spades_kmers_from_max_read_length(maximum)
    return {
        "SOURCE_TYPE": source_type,
        "FILES": files,
        "IGNORED_FILES": ignored_files or [],
        "FILE_ROWS": file_rows,
        "LENGTH_COUNTS": length_counts,
        "TOTAL_READS": int(total_reads),
        "MIN_READ_LENGTH": minimum,
        "MEDIAN_READ_LENGTH": median,
        "P90_READ_LENGTH": p90,
        "P95_READ_LENGTH": p95,
        "MAX_READ_LENGTH": maximum,
        "RECOMMENDED_KMERS": recommended,
        "TABLE_BAND": table_band,
    }


def _detect_fastq_storage(path: Path) -> tuple[str, str]:
    """Detect FASTQ storage from file CONTENT, never from the filename alone.

    Returns (storage, detail), where storage is GZIP, PLAIN_TEXT, EMPTY, or
    UNKNOWN_BINARY.  This prevents a mislabeled/corrupted *.fastq.gz from
    surfacing only as Python's opaque "Not a gzipped file" exception.
    """
    with path.open("rb") as handle:
        prefix = handle.read(64)
    if not prefix:
        return "EMPTY", "zero-byte file"
    if prefix.startswith(b"\x1f\x8b"):
        return "GZIP", "gzip magic 1f8b"

    probe = prefix
    if probe.startswith(b"\xef\xbb\xbf"):
        probe = probe[3:]
    if probe.startswith(b"@"):
        return "PLAIN_TEXT", "plain FASTQ header detected"

    hex_prefix = prefix[:8].hex(" ")
    return "UNKNOWN_BINARY", f"first bytes: {hex_prefix}"


def _open_fastq_text_by_content(path: Path):
    storage, detail = _detect_fastq_storage(path)
    if storage == "GZIP":
        return gzip.open(path, "rt", encoding="utf-8", errors="strict"), storage, detail
    if storage == "PLAIN_TEXT":
        return path.open("r", encoding="utf-8-sig", errors="strict"), storage, detail
    if storage == "EMPTY":
        raise ValueError(f"FASTQ file is empty: {path}")
    raise ValueError(
        f"File is named like FASTQ but is neither gzip FASTQ nor plain-text FASTQ: {path}. "
        f"Detected {detail}. Re-create this Step 05 FASTQ file."
    )


def _analyze_abnormal_fastq_lengths(fastqs: list[Path]) -> dict[str, object]:
    length_counts: Counter = Counter()
    file_rows: list[dict[str, object]] = []
    ignored_files: list[Path] = []
    total_reads = 0

    for path in fastqs:
        file_reads = 0
        file_min = None
        file_max = 0
        storage = "UNKNOWN"
        detail = ""
        try:
            handle, storage, detail = _open_fastq_text_by_content(path)
            with handle:
                record_number = 0
                while True:
                    header = handle.readline()
                    if not header:
                        break
                    sequence = handle.readline()
                    plus = handle.readline()
                    quality = handle.readline()
                    record_number += 1
                    if not sequence or not plus or not quality:
                        raise ValueError(
                            f"Truncated FASTQ record in {path} near record {record_number:,}."
                        )
                    if not header.startswith("@") or not plus.startswith("+"):
                        raise ValueError(
                            f"Malformed FASTQ structure in {path} near record {record_number:,}."
                        )
                    seq = sequence.rstrip("\r\n")
                    qual = quality.rstrip("\r\n")
                    if len(seq) != len(qual):
                        raise ValueError(
                            f"Sequence/quality length mismatch in {path} near record {record_number:,}: "
                            f"sequence={len(seq)}, quality={len(qual)}."
                        )
                    read_length = len(seq)
                    if read_length <= 0:
                        continue
                    length_counts[read_length] += 1
                    total_reads += 1
                    file_reads += 1
                    file_min = read_length if file_min is None else min(file_min, read_length)
                    file_max = max(file_max, read_length)

            file_rows.append({
                "SOURCE_TYPE": "FASTQ",
                "FILE": str(path),
                "STORAGE_FORMAT": storage,
                "STORAGE_DETAIL": detail,
                "STATUS": "OK",
                "READ_COUNT": file_reads,
                "MIN_READ_LENGTH": file_min or 0,
                "MAX_READ_LENGTH": file_max,
            })
        except (OSError, EOFError, UnicodeError, ValueError) as exc:
            ignored_files.append(path)
            file_rows.append({
                "SOURCE_TYPE": "FASTQ",
                "FILE": str(path),
                "STORAGE_FORMAT": storage,
                "STORAGE_DETAIL": detail,
                "STATUS": f"REJECTED: {exc}",
                "READ_COUNT": 0,
                "MIN_READ_LENGTH": 0,
                "MAX_READ_LENGTH": 0,
            })

    return {
        "LENGTH_COUNTS": length_counts,
        "FILE_ROWS": file_rows,
        "IGNORED_FILES": ignored_files,
        "TOTAL_READS": total_reads,
    }



def analyze_abnormal_read_length_distribution(
    input_dir: Path,
    settings: dict | None = None,
) -> dict[str, object]:
    """Analyze only Step 05 abnormal FASTQ/FQ files for manual SPAdes k-mer guidance."""
    folder = Path(input_dir)
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"Step 05 abnormal FASTQ folder not found: {folder}")

    fastq_suffixes = (
        ".fastq", ".fq", ".fastq.gz", ".fq.gz",
        ".fastq.bgz", ".fq.bgz", ".fastq.bgzf", ".fq.bgzf",
    )
    fastqs = sorted(
        path for path in folder.rglob("*")
        if path.is_file()
        and path.stat().st_size > 0
        and "abnormal" in path.name.lower()
        and path.name.lower().endswith(fastq_suffixes)
    )

    if not fastqs:
        bam_files = sorted(
            path for path in folder.rglob("*.bam")
            if path.is_file() and "abnormal" in path.name.lower()
        )
        extra = (
            "\n\nAbnormal BAM file(s) were found, but BAM is intentionally NOT accepted "
            "as SPAdes input in this Step 06. Use the Step 05 abnormal FASTQ/FQ files."
            if bam_files else ""
        )
        raise FileNotFoundError(
            "No non-empty Step 05 abnormal FASTQ/FQ files were found. Expected filenames "
            "containing 'abnormal' and ending in .fastq/.fq, optionally gzip-compressed."
            + extra
        )

    fastq_result = _analyze_abnormal_fastq_lengths(fastqs)
    if int(fastq_result["TOTAL_READS"]) <= 0:
        raise ValueError("The abnormal FASTQ/FQ files were found but contain zero reads.")

    valid_files = [
        Path(row["FILE"])
        for row in fastq_result["FILE_ROWS"]
        if str(row.get("STATUS", "")).startswith("OK")
    ]
    return _summarize_spades_length_counts(
        length_counts=fastq_result["LENGTH_COUNTS"],
        total_reads=int(fastq_result["TOTAL_READS"]),
        files=valid_files,
        file_rows=fastq_result["FILE_ROWS"],
        source_type="FASTQ",
        ignored_files=fastq_result.get("IGNORED_FILES", []),
    )

def analyze_abnormal_fastq_length_distribution(input_dir: Path) -> dict[str, object]:
    return analyze_abnormal_read_length_distribution(input_dir)

class StandaloneStepGUI:
    def __init__(self, spec: StepSpecification, backend_function, gui_spec: dict):
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
        self.tk=tk; self.ttk=ttk; self.filedialog=filedialog; self.messagebox=messagebox
        self.spec=spec; self.backend_function=backend_function; self.gui_spec=gui_spec
        self.step_dir=Path(__file__).resolve().parent
        self.settings_path=self.step_dir/'step_user_settings.json'
        self.settings,_=load_config(self.settings_path)
        self.root=tk.Tk(); self.root.title(f"{spec.title} - standalone ctDNA step")
        self.root.geometry("1120x850")
        self.root.minsize(920,680)
        self.vars={}
        self.field_widgets={}
        self.field_action_buttons={}
        self._build()

    def _build(self):
        tk,ttk=self.tk,self.ttk
        accent=self.spec.resolved_accent_color

        outer=tk.Frame(self.root,bg="#F4F7FA")
        outer.pack(fill="both",expand=True)

        header=tk.Frame(outer,bg=accent,padx=16,pady=12)
        header.pack(fill="x")
        tk.Label(
            header,
            text=self.spec.title,
            bg=accent,
            fg="white",
            font=("Segoe UI",15,"bold"),
        ).pack(anchor="w")
        tk.Label(
            header,
            text=self.spec.description,
            bg=accent,
            fg="white",
            font=("Segoe UI",9),
            wraplength=1040,
            justify="left",
        ).pack(anchor="w",pady=(4,0))

        canvas=tk.Canvas(outer,bg="#F4F7FA",highlightthickness=0)
        canvas.pack(side="left",fill="both",expand=True)
        scroll=ttk.Scrollbar(outer,orient="vertical",command=canvas.yview)
        scroll.pack(side="right",fill="y")
        canvas.configure(yscrollcommand=scroll.set)

        body=tk.Frame(canvas,bg="#F4F7FA",padx=14,pady=12)
        win=canvas.create_window((0,0),window=body,anchor="nw")
        body.bind("<Configure>",lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",lambda e: canvas.itemconfigure(win,width=e.width))

        explanation=str(self.gui_spec.get("explanation","")).strip()
        if explanation:
            info=tk.LabelFrame(
                body,
                text="ABOUT THIS STEP",
                bg="white",
                fg=accent,
                font=("Segoe UI",10,"bold"),
                padx=12,
                pady=10,
            )
            info.pack(fill="x",pady=(0,10))
            tk.Label(
                info,
                text=explanation,
                bg="white",
                fg="#334155",
                font=("Segoe UI",9),
                wraplength=1010,
                justify="left",
            ).pack(fill="x",anchor="w")

        current_section=None
        current_card=None
        for field in self.gui_spec.get("fields",[]):
            section=str(field.get("section","INPUTS AND PARAMETERS")).strip() or "INPUTS AND PARAMETERS"
            if section != current_section:
                current_section=section
                current_card=tk.LabelFrame(
                    body,
                    text=section,
                    bg="white",
                    fg=accent,
                    font=("Segoe UI",10,"bold"),
                    padx=10,
                    pady=8,
                )
                current_card.pack(fill="x",pady=(0,10))
            self._add_field(current_card,field)

        self.root.after(0, self._update_spades_kmer_controls)

        out_card=tk.LabelFrame(
            body,
            text="OUTPUT AND EXECUTION",
            bg="white",
            fg=accent,
            font=("Segoe UI",10,"bold"),
            padx=10,
            pady=8,
        )
        out_card.pack(fill="x",pady=(0,10))

        output_default=str((self.step_dir/'output').resolve())
        self.vars['__output_dir__']=tk.StringVar(value=output_default)
        self._path_row(
            out_card,
            "Output folder",
            self.vars['__output_dir__'],
            kind="folder",
            title="Select output folder",
        )

        self.vars['project.threads']=tk.StringVar(
            value=str(_setting_get(self.settings,'project.threads'))
        )
        self.vars['execution.wsl_distribution']=tk.StringVar(
            value=str(_setting_get(self.settings,'execution.wsl_distribution'))
        )
        self.vars['execution.micromamba_environment']=tk.StringVar(
            value=str(_setting_get(self.settings,'execution.micromamba_environment'))
        )
        self.vars['execution.micromamba_executable']=tk.StringVar(
            value=str(_setting_get(self.settings,'execution.micromamba_executable'))
        )
        self.vars['execution.micromamba_root_prefix']=tk.StringVar(
            value=str(_setting_get(self.settings,'execution.micromamba_root_prefix'))
        )
        self.vars['execution.python_executable_in_wsl']=tk.StringVar(
            value=str(_setting_get(self.settings,'execution.python_executable_in_wsl'))
        )

        grid=tk.Frame(out_card,bg="white")
        grid.pack(fill="x",pady=(8,0))
        exec_fields=[
            ('Threads','project.threads'),
            ('WSL distribution (blank=default)','execution.wsl_distribution'),
            ('Micromamba env','execution.micromamba_environment'),
            ('Micromamba executable (blank=detect)','execution.micromamba_executable'),
            ('Micromamba root prefix (blank=detect)','execution.micromamba_root_prefix'),
            ('WSL Python','execution.python_executable_in_wsl'),
        ]
        for i,(label,key) in enumerate(exec_fields):
            r=i//2
            c=(i%2)*2
            tk.Label(
                grid,
                text=label,
                bg="white",
                font=("Segoe UI",8,"bold"),
            ).grid(row=r,column=c,sticky="w",padx=(0,5),pady=3)
            ttk.Entry(
                grid,
                textvariable=self.vars[key],
                width=34,
            ).grid(row=r,column=c+1,sticky="ew",padx=(0,14),pady=3)
            grid.columnconfigure(c+1,weight=1)

        progress_box=tk.Frame(out_card,bg="white")
        progress_box.pack(fill="x",pady=(12,4))

        self.progress_text=tk.StringVar(value="Progress: Ready")
        tk.Label(
            progress_box,
            textvariable=self.progress_text,
            bg="white",
            fg="#334155",
            font=("Segoe UI",8,"bold"),
            anchor="w",
        ).pack(fill="x",pady=(0,4))

        self.progress_value=tk.DoubleVar(value=0.0)
        self.progress_bar=ttk.Progressbar(
            progress_box,
            orient="horizontal",
            mode="determinate",
            maximum=100.0,
            variable=self.progress_value,
        )
        self.progress_bar.pack(fill="x")

        tk.Label(
            progress_box,
            text=(
                "During external tools the bar is activity-based because many genomics "
                "programs do not report a reliable percent complete. It changes to 100% "
                "only after the step finishes successfully."
            ),
            bg="white",
            fg="#64748B",
            font=("Segoe UI",8),
            wraplength=980,
            justify="left",
            anchor="w",
        ).pack(fill="x",pady=(4,0))

        buttons=tk.Frame(body,bg="#F4F7FA")
        buttons.pack(fill="x",pady=8)

        self.save_button=ttk.Button(
            buttons,
            text="Save settings",
            command=self._save_clicked,
        )
        self.save_button.pack(side="left",padx=4)

        self.dry_run_button=ttk.Button(
            buttons,
            text="Dry run",
            command=lambda:self._run(True),
        )
        self.dry_run_button.pack(side="left",padx=4)

        self.run_button=ttk.Button(
            buttons,
            text="RUN STEP",
            command=lambda:self._run(False),
        )
        self.run_button.pack(side="left",padx=4)

        self.open_output_button=ttk.Button(
            buttons,
            text="Open output",
            command=self._open_output,
        )
        self.open_output_button.pack(side="left",padx=4)

        self.status=tk.StringVar(value="Ready.")
        tk.Label(
            body,
            textvariable=self.status,
            bg="#F4F7FA",
            fg="#334155",
            font=("Consolas",9),
            wraplength=1030,
            justify="left",
        ).pack(fill="x",pady=(5,10))

    def _initial_for_field(self, field):
        tk=self.tk
        key=field['setting']
        typ=field.get('type','text')

        if key=='__input_dir__':
            value=str((self.step_dir/'input').resolve())
        else:
            value=_setting_get(self.settings,key)

        if typ=='bool':
            return tk.BooleanVar(value=bool(value))

        if typ=='choice':
            reverse={
                str(internal):str(display)
                for display,internal in field.get('choice_values',{}).items()
            }
            display_value=reverse.get(str(value),str(value if value is not None else ''))
            return tk.StringVar(value=display_value)

        return tk.StringVar(value=str(value if value is not None else ''))

    def _add_field(self,parent,field):
        tk,ttk=self.tk,self.ttk
        key=field['setting']
        typ=field.get('type','text')
        var=self._initial_for_field(field)
        self.vars[key]=var

        row=tk.Frame(parent,bg="white")
        row.pack(fill="x",pady=5)

        if typ=='bool':
            ttk.Checkbutton(
                row,
                text=field['label'],
                variable=var,
            ).pack(anchor="w")
        else:
            tk.Label(
                row,
                text=field['label'],
                bg="white",
                font=("Segoe UI",8,"bold"),
                width=34,
                anchor="w",
            ).pack(side="left")

            if typ=='choice':
                choices=list(field.get('choices',[]))
                widget=ttk.Combobox(
                    row,
                    textvariable=var,
                    values=choices,
                    state="readonly",
                )
                widget.pack(side="left",fill="x",expand=True,padx=(4,6))
                widget.bind(
                    "<<ComboboxSelected>>",
                    lambda event,f=field:self._choice_selected(f),
                )
                self.field_widgets[key]=widget
            else:
                entry=ttk.Entry(row,textvariable=var)
                entry.pack(side="left",fill="x",expand=True,padx=(4,6))
                self.field_widgets[key]=entry

                if typ in {'file','folder'}:
                    ttk.Button(
                        row,
                        text=field.get('button_text','Browse'),
                        command=lambda f=field,v=var:self._browse(f,v),
                    ).pack(side="left",padx=3)

                    if typ=='folder' and field.get('scan_globs'):
                        ttk.Button(
                            row,
                            text="Scan",
                            command=lambda f=field,v=var:self._scan(f,v),
                        ).pack(side="left",padx=3)

                if field.get('action_button_text'):
                    action_name=str(field.get('action','')).strip()
                    if action_name == 'analyze_spades_read_lengths':
                        action_command = self._analyze_spades_read_lengths_clicked
                    elif action_name == 'scan_select_canonical_chromosomes':
                        action_command = self._scan_select_canonical_chromosomes_clicked
                    elif action_name == 'create_classic_bwa_index':
                        action_command = self._create_classic_bwa_index_clicked
                    else:
                        action_command = lambda: self.messagebox.showerror(
                            'Unsupported action',
                            f'Unknown GUI field action: {action_name}',
                        )
                    action_button=ttk.Button(
                        row,
                        text=field['action_button_text'],
                        command=action_command,
                    )
                    action_button.pack(side="left",padx=3)
                    self.field_action_buttons[key]=action_button

        if field.get('help'):
            tk.Label(
                parent,
                text=field['help'],
                bg="white",
                fg="#64748B",
                font=("Segoe UI",8),
                wraplength=980,
                justify="left",
            ).pack(fill="x",padx=(34,0),pady=(0,2))


    def _choice_selected(self,field):
        key=field['setting']
        display=str(self.vars[key].get()).strip()
        updates=field.get('choice_updates',{}).get(display,{})

        for target,value in updates.items():
            if target in self.vars:
                self.vars[target].set(value)
            else:
                _setting_set(self.settings,target,value)

        if key == 'breakpoints.spades_kmer_mode':
            self._update_spades_kmer_controls()

    def _update_spades_kmer_controls(self):
        mode_var=self.vars.get('breakpoints.spades_kmer_mode')
        if mode_var is None:
            return
        manual=str(mode_var.get()).strip().lower().startswith('manual')
        state='normal' if manual else 'disabled'
        widget=self.field_widgets.get('breakpoints.spades_kmers')
        if widget is not None:
            widget.configure(state=state)
        button=self.field_action_buttons.get('breakpoints.spades_kmers')
        if button is not None:
            button.configure(state=state)

    def _analyze_spades_read_lengths_clicked(self):
        mode_var=self.vars.get('breakpoints.spades_kmer_mode')
        if mode_var is None or not str(mode_var.get()).strip().lower().startswith('manual'):
            self.messagebox.showinfo('SPAdes k-mers','Select Manual k-mer mode first.')
            return
        input_var=self.vars.get('__input_dir__')
        if input_var is None or not str(input_var.get()).strip():
            self.messagebox.showerror('Read-length analysis','Select the Step 05 abnormal FASTQ folder first.')
            return
        folder=Path(str(input_var.get()).strip())
        self.status.set('Analyzing abnormal FASTQ read-length distribution...')
        button=self.field_action_buttons.get('breakpoints.spades_kmers')
        if button is not None:
            button.configure(state='disabled')
        threading.Thread(
            target=self._analyze_spades_read_lengths_worker,
            args=(folder,),
            daemon=True,
        ).start()

    def _analyze_spades_read_lengths_worker(self,folder: Path):
        try:
            result=analyze_abnormal_read_length_distribution(folder)
        except Exception as exc:
            self.root.after(0,lambda e=exc:self._finish_spades_read_length_analysis(None,e))
            return
        self.root.after(0,lambda r=result:self._finish_spades_read_length_analysis(r,None))

    def _finish_spades_read_length_analysis(self,result,exc):
        self._update_spades_kmer_controls()
        if exc is not None:
            self.status.set('Read-length analysis failed.')
            self.messagebox.showerror('Read-length analysis failed',str(exc))
            return
        recommended=','.join(str(k) for k in result['RECOMMENDED_KMERS'])
        self.vars['breakpoints.spades_kmers'].set(recommended)
        counts=result['LENGTH_COUNTS']
        most_common=sorted(counts.items(),key=lambda item:(-item[1],item[0]))[:12]
        distribution_text='\n'.join(
            f'  {length:>4} bp : {count:,} reads'
            for length,count in most_common
        )
        ignored=result.get('IGNORED_FILES',[])
        ignored_text=(
            "\n\nRejected malformed/non-FASTQ file(s):\n"
            + "\n".join(f"  {path}" for path in ignored)
            if ignored else ""
        )
        message=(
            f"Source analyzed: {result['SOURCE_TYPE']}\n"
            f"Valid abnormal FASTQ files analyzed: {len(result['FILES'])}\n"
            f"Reads analyzed: {result['TOTAL_READS']:,}\n\n"
            f"Minimum length: {result['MIN_READ_LENGTH']} bp\n"
            f"Median length:  {result['MEDIAN_READ_LENGTH']} bp\n"
            f"P90 length:     {result['P90_READ_LENGTH']} bp\n"
            f"P95 length:     {result['P95_READ_LENGTH']} bp\n"
            f"Maximum length: {result['MAX_READ_LENGTH']} bp\n\n"
            f"Table category: {result['TABLE_BAND']}\n"
            f"Recommended manual k-mers: {recommended}\n\n"
            "Most common read lengths:\n"
            f"{distribution_text}"
            f"{ignored_text}\n\n"
            "The recommendation has been inserted into the editable k-mer field. "
            "You can modify it before running Step 06."
        )
        self.status.set(
            f"Read-length analysis complete. Suggested manual k-mers: {recommended}"
        )
        self.messagebox.showinfo('SPAdes read-length distribution',message)

    def _build_wsl_tool_command(self, tool: str, tool_args: list[str]) -> list[str]:
        """Build a WSL command that runs one tool inside the configured Micromamba env."""
        distro = str(self.vars.get('execution.wsl_distribution').get()).strip()
        exe = str(self.vars.get('execution.micromamba_executable').get()).strip()
        root = str(self.vars.get('execution.micromamba_root_prefix').get()).strip()
        env = str(self.vars.get('execution.micromamba_environment').get()).strip()

        if env and not exe:
            detected_exe, detected_root = _detect_micromamba(distro)
            exe = detected_exe
            if not root:
                root = detected_root
            if exe:
                self.vars['execution.micromamba_executable'].set(exe)
                self.vars['execution.micromamba_root_prefix'].set(root)

        command = [tool, *tool_args]
        if env:
            if not exe:
                raise RuntimeError(
                    'Micromamba environment is selected but micromamba was not detected. '
                    'Enter the WSL micromamba executable in the Environment section.'
                )
            prefix = [exe]
            if root:
                prefix += ['-r', root]
            prefix += ['run', '-n', env]
            command = prefix + command

        shell = ' '.join(shlex.quote(str(item)) for item in command)
        return _wsl_base_args(distro) + ['bash', '-lc', shell]

    def _create_classic_bwa_index_clicked(self):
        """Create the classic BWA/BWA-MEM index required by GRIDSS2/SvABA."""
        reference_var = self.vars.get('references.fasta')
        index_var = self.vars.get('breakpoints.classic_bwa_index_file')
        if reference_var is None or index_var is None:
            self.messagebox.showerror(
                'Create BWA-MEM index',
                'Reference FASTA/BWA index controls are unavailable.',
            )
            return

        reference_text = str(reference_var.get()).strip()
        if not reference_text:
            self.messagebox.showerror(
                'Create BWA-MEM index',
                'Select the reference FASTA first.',
            )
            return

        reference = Path(reference_text)
        if not reference.exists() or not reference.is_file():
            self.messagebox.showerror(
                'Create BWA-MEM index',
                f'Reference FASTA was not found:\n{reference}',
            )
            return

        index_dir = reference.parent / "BWA-MEM1_Index"
        indexed_reference = index_dir / reference.name

        try:
            bwa_command = self._build_wsl_tool_command(
                'bwa',
                [
                    'index',
                    '-p', _windows_to_wsl(indexed_reference),
                    _windows_to_wsl(indexed_reference),
                ],
            )
            faidx_command = self._build_wsl_tool_command(
                'samtools',
                ['faidx', _windows_to_wsl(indexed_reference)],
            )
        except Exception as exc:
            self.messagebox.showerror('Create BWA-MEM index', str(exc))
            return

        button = self.field_action_buttons.get('breakpoints.classic_bwa_index_file')
        if button is not None:
            button.configure(state='disabled')
        self.status.set(
            'Creating classic BWA/BWA-MEM index (.amb/.ann/.bwt/.pac/.sa)...'
        )

        threading.Thread(
            target=self._create_classic_bwa_index_worker,
            args=(reference, indexed_reference, bwa_command, faidx_command),
            daemon=True,
        ).start()

    def _create_classic_bwa_index_worker(
        self,
        reference: Path,
        indexed_reference: Path,
        bwa_command: list[str],
        faidx_command: list[str],
    ):
        try:
            index_dir = indexed_reference.parent
            index_dir.mkdir(parents=True, exist_ok=True)

            # GRIDSS2 expects the BWA index prefix to match the FASTA path it is
            # given. Keep an exact mirror of the selected FASTA inside the dedicated
            # BWA-MEM1_Index folder. Prefer a hard link (no duplicate disk usage) and
            # fall back to a normal copy when the filesystem does not support links.
            recreate_mirror = True
            if indexed_reference.exists():
                try:
                    if indexed_reference.samefile(reference):
                        recreate_mirror = False
                    else:
                        source_stat = reference.stat()
                        mirror_stat = indexed_reference.stat()
                        recreate_mirror = not (
                            source_stat.st_size == mirror_stat.st_size
                            and source_stat.st_mtime_ns == mirror_stat.st_mtime_ns
                        )
                except OSError:
                    recreate_mirror = True

            if recreate_mirror:
                if indexed_reference.exists():
                    indexed_reference.unlink()
                try:
                    os.link(reference, indexed_reference)
                    mirror_method = 'HARD_LINK'
                except OSError:
                    shutil.copy2(reference, indexed_reference)
                    mirror_method = 'COPY'
            else:
                mirror_method = 'EXISTING_EXACT_MIRROR'

            completed = subprocess.run(
                bwa_command,
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or '').strip()
                raise RuntimeError(
                    'bwa index failed with exit code '
                    f'{completed.returncode}.\n\n{detail[-5000:]}'
                )

            faidx = subprocess.run(
                faidx_command,
                capture_output=True,
                text=True,
            )
            if faidx.returncode != 0:
                detail = (faidx.stderr or faidx.stdout or '').strip()
                raise RuntimeError(
                    'samtools faidx failed for the BWA-MEM1_Index FASTA with exit code '
                    f'{faidx.returncode}.\n\n{detail[-5000:]}'
                )

            generated = [
                Path(str(indexed_reference) + suffix)
                for suffix in CLASSIC_BWA_INDEX_SUFFIXES
            ]
            generated.append(Path(str(indexed_reference) + '.fai'))
            missing = [
                path for path in generated
                if not path.exists() or not path.is_file() or path.stat().st_size == 0
            ]
            if missing:
                raise FileNotFoundError(
                    'Index creation returned successfully, but the expected BWA-MEM1 '
                    'index set is incomplete. Missing:\n  - '
                    + '\n  - '.join(str(path) for path in missing)
                )

            selected = Path(str(indexed_reference) + '.bwt')
            result = {
                'selected': selected,
                'generated': generated,
                'indexed_reference': indexed_reference,
                'index_dir': index_dir,
                'mirror_method': mirror_method,
                'stdout': (completed.stdout or '').strip(),
                'stderr': (completed.stderr or '').strip(),
            }
        except Exception as exc:
            self.root.after(
                0,
                lambda e=exc: self._finish_create_classic_bwa_index(None, e),
            )
            return

        self.root.after(
            0,
            lambda r=result: self._finish_create_classic_bwa_index(r, None),
        )

    def _finish_create_classic_bwa_index(self, result, exc):
        button = self.field_action_buttons.get('breakpoints.classic_bwa_index_file')
        if button is not None:
            button.configure(state='normal')

        if exc is not None:
            self.status.set('Classic BWA/BWA-MEM index creation failed.')
            self.messagebox.showerror('Create BWA-MEM index failed', str(exc))
            return

        selected = result['selected']
        self.vars['breakpoints.classic_bwa_index_file'].set(str(selected))
        self.status.set(f'Classic BWA/BWA-MEM index created: {selected}')
        files_text = '\n'.join(f'  {path.name}' for path in result['generated'])
        self.messagebox.showinfo(
            'BWA-MEM index created',
            'Classic BWA/BWA-MEM index creation completed successfully.\n\n'
            f'Index folder:\n{result["index_dir"]}\n\n'
            f'Indexed FASTA used by GRIDSS2/SvABA:\n{result["indexed_reference"]}\n'
            f'Mirror method: {result["mirror_method"]}\n\n'
            'Created index files:\n'
            f'{files_text}\n\n'
            f'The BWA index field was automatically set to:\n{selected}\n\n'
            'The main mapping step still uses BWA-MEM2. This separate classic BWA '
            'index is for GRIDSS2/SvABA.'
        )

    def _scan_select_canonical_chromosomes_clicked(self):
        reference_var = self.vars.get('references.fasta')
        canonical_var = self.vars.get('breakpoints.canonical_chromosomes')
        if reference_var is None or canonical_var is None:
            self.messagebox.showerror(
                'Canonical chromosome selection',
                'Reference FASTA/canonical chromosome controls are unavailable.',
            )
            return

        reference_text = str(reference_var.get()).strip()
        if not reference_text:
            self.messagebox.showerror(
                'Canonical chromosome selection',
                'Select the reference FASTA first.',
            )
            return

        reference = Path(reference_text)
        if not reference.exists() or not reference.is_file():
            self.messagebox.showerror(
                'Canonical chromosome selection',
                f'Reference FASTA was not found:\n{reference}',
            )
            return

        self.status.set('Scanning reference FASTA sequence names...')
        self.root.update_idletasks()
        try:
            names = reference_names_from_fasta(reference)
        except Exception as exc:
            self.status.set('Reference FASTA scan failed.')
            self.messagebox.showerror('Reference FASTA scan failed', str(exc))
            return

        self.status.set(
            f'Found {len(names)} reference sequences. Select which are canonical.'
        )
        self._show_canonical_chromosome_selector(names)

    def _show_canonical_chromosome_selector(self, reference_names: list[str]):
        tk, ttk = self.tk, self.ttk
        canonical_var = self.vars['breakpoints.canonical_chromosomes']

        dialog = tk.Toplevel(self.root)
        dialog.title('Select canonical chromosomes / reference sequences')
        dialog.geometry('720x700')
        dialog.minsize(620, 520)
        dialog.transient(self.root)
        dialog.grab_set()

        outer = tk.Frame(dialog, bg='white', padx=12, pady=12)
        outer.pack(fill='both', expand=True)

        tk.Label(
            outer,
            text='Canonical versus non-canonical reference sequences',
            bg='white',
            fg=self.spec.resolved_accent_color,
            font=('Segoe UI', 11, 'bold'),
            anchor='w',
        ).pack(fill='x')

        tk.Label(
            outer,
            text=(
                'Select every FASTA reference sequence that you want to treat as CANONICAL. '
                'Every unselected sequence will automatically be classified as NON_CANONICAL. '
                'The complete reference FASTA is still used for minimap2/Manta alignment.'
            ),
            bg='white',
            fg='#334155',
            font=('Segoe UI', 9),
            wraplength=680,
            justify='left',
        ).pack(fill='x', pady=(5, 10))

        list_frame = tk.Frame(outer, bg='white')
        list_frame.pack(fill='both', expand=True)

        scrollbar = ttk.Scrollbar(list_frame, orient='vertical')
        listbox = tk.Listbox(
            list_frame,
            selectmode=tk.EXTENDED,
            exportselection=False,
            yscrollcommand=scrollbar.set,
            font=('Consolas', 10),
        )
        scrollbar.config(command=listbox.yview)
        listbox.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        for name in reference_names:
            listbox.insert(tk.END, name)

        current = parse_reference_name_list(canonical_var.get())
        current_set = set(current)
        if not current_set:
            current_set = set(suggested_standard_canonical_references(reference_names))

        for index, name in enumerate(reference_names):
            if name in current_set:
                listbox.selection_set(index)

        summary_var = tk.StringVar()

        def update_summary(event=None):
            selected_count = len(listbox.curselection())
            summary_var.set(
                f'Canonical selected: {selected_count}   |   '
                f'Non-canonical: {len(reference_names) - selected_count}   |   '
                f'Total FASTA sequences: {len(reference_names)}'
            )

        listbox.bind('<<ListboxSelect>>', update_summary)

        tk.Label(
            outer,
            textvariable=summary_var,
            bg='white',
            fg='#334155',
            font=('Segoe UI', 9, 'bold'),
            anchor='w',
        ).pack(fill='x', pady=(8, 4))
        update_summary()

        button_bar = tk.Frame(outer, bg='white')
        button_bar.pack(fill='x', pady=(6, 0))

        def select_standard():
            standard = set(suggested_standard_canonical_references(reference_names))
            listbox.selection_clear(0, tk.END)
            for index, name in enumerate(reference_names):
                if name in standard:
                    listbox.selection_set(index)
            update_summary()

        def select_all():
            listbox.selection_set(0, tk.END)
            update_summary()

        def clear_all():
            listbox.selection_clear(0, tk.END)
            update_summary()

        def apply_selection():
            indices = listbox.curselection()
            if not indices:
                self.messagebox.showerror(
                    'Canonical chromosome selection',
                    'Select at least one canonical reference sequence.',
                    parent=dialog,
                )
                return
            selected = [reference_names[index] for index in indices]
            canonical_var.set(';'.join(selected))
            self.status.set(
                f'Canonical references selected: {len(selected)}; '
                f'non-canonical references: {len(reference_names) - len(selected)}.'
            )
            dialog.destroy()

        ttk.Button(
            button_bar,
            text='Select standard 1-22, X, Y',
            command=select_standard,
        ).pack(side='left', padx=(0, 5))
        ttk.Button(
            button_bar,
            text='Select all',
            command=select_all,
        ).pack(side='left', padx=5)
        ttk.Button(
            button_bar,
            text='Clear',
            command=clear_all,
        ).pack(side='left', padx=5)
        ttk.Button(
            button_bar,
            text='Apply selection',
            command=apply_selection,
        ).pack(side='right', padx=(5, 0))
        ttk.Button(
            button_bar,
            text='Cancel',
            command=dialog.destroy,
        ).pack(side='right', padx=5)


    def _path_row(self,parent,label,var,kind='folder',title='Select'):
        tk,ttk=self.tk,self.ttk; row=tk.Frame(parent,bg="white"); row.pack(fill="x",pady=4)
        tk.Label(row,text=label,bg="white",font=("Segoe UI",8,"bold"),width=34,anchor="w").pack(side="left")
        ttk.Entry(row,textvariable=var).pack(side="left",fill="x",expand=True,padx=(4,6))
        ttk.Button(row,text="Browse",command=lambda:self._browse({'type':kind,'title':title},var)).pack(side="left")

    def _browse(self,field,var):
        current=var.get().strip(); initial=Path(current).parent if current and Path(current).parent.exists() else self.step_dir
        if field.get('type')=='folder':
            selected=self.filedialog.askdirectory(initialdir=initial,title=field.get('title',field.get('label','Select folder')))
        else:
            patterns=field.get('filetypes') or [('All files','*.*')]
            selected=self.filedialog.askopenfilename(initialdir=initial,title=field.get('title') or f"Find required file: {field.get('expected_name') or field.get('label','file')}",filetypes=patterns)
        if selected: var.set(selected)

    def _scan(self,field,var):
        try:
            a,r,examples=_scan_folder(Path(var.get().strip()),field)
            self.messagebox.showinfo('Folder scan',f"Accepted: {a}\nRejected: {r}\n\nExamples:\n"+'\n'.join(examples))
        except Exception as exc: self.messagebox.showerror('Scan failed',str(exc))

    def _collect(self):
        settings=copy.deepcopy(self.settings)
        input_dir=self.step_dir/'input'

        for field in self.gui_spec.get('fields',[]):
            key=field['setting']
            typ=field.get('type','text')
            raw=self.vars[key].get()

            if typ=='bool':
                value=bool(raw)
            elif typ=='int':
                value=int(str(raw).strip())
            elif typ=='float':
                value=float(str(raw).strip())
            elif typ=='choice':
                display=str(raw).strip()
                value=field.get('choice_values',{}).get(display,display)
            else:
                value=str(raw).strip()

            if field.get('required') and (value=='' or value is None):
                raise ValueError(f"Required input missing: {field['label']}")

            if typ=='file' and value:
                p=Path(value)
                if not p.exists() or not p.is_file():
                    raise FileNotFoundError(f"File not found: {p}")
                _validate_expected_file(p,field)

            if typ=='folder' and value:
                p=Path(value)
                if not p.exists() or not p.is_dir():
                    raise FileNotFoundError(f"Folder not found: {p}")

            if key=='__input_dir__':
                input_dir=Path(value)
            else:
                _setting_set(settings,key,value)

        _setting_set(
            settings,
            'project.threads',
            int(self.vars['project.threads'].get()),
        )

        for key in [
            'execution.wsl_distribution',
            'execution.micromamba_environment',
            'execution.micromamba_executable',
            'execution.micromamba_root_prefix',
            'execution.python_executable_in_wsl',
        ]:
            _setting_set(settings,key,self.vars[key].get().strip())

        output_dir=Path(self.vars['__output_dir__'].get().strip())
        if not output_dir:
            raise ValueError('Output folder is required.')

        return settings,input_dir,output_dir

    def _save(self):
        settings,input_dir,output_dir=self._collect(); output_dir.mkdir(parents=True,exist_ok=True)
        with self.settings_path.open('w',encoding='utf-8') as h: json.dump(settings,h,indent=2); h.write('\n')
        self.settings=settings; self.status.set(f"Settings saved: {self.settings_path}")
        return settings,input_dir,output_dir

    def _save_clicked(self):
        try: self._save(); self.messagebox.showinfo('Settings','Settings saved successfully.')
        except Exception as exc: self.messagebox.showerror('Settings error',str(exc))

    def _build_wsl_command(self,settings,input_dir,output_dir,dry_run):
        distro=str(_setting_get(settings, 'execution.wsl_distribution'))
        exe=str(_setting_get(settings, 'execution.micromamba_executable')).strip()
        root=str(_setting_get(settings, 'execution.micromamba_root_prefix')).strip()
        env=str(_setting_get(settings, 'execution.micromamba_environment')).strip()
        python_exe=str(_setting_get(settings, 'execution.python_executable_in_wsl')).strip() or 'python3'
        if env and not exe:
            detected_exe,detected_root=_detect_micromamba(distro); exe=detected_exe; root=root or detected_root
            if exe:
                _setting_set(settings,'execution.micromamba_executable',exe); _setting_set(settings,'execution.micromamba_root_prefix',root)
                with self.settings_path.open('w',encoding='utf-8') as h: json.dump(settings,h,indent=2); h.write('\n')
        backend=[python_exe,_windows_to_wsl(Path(__file__).resolve()),'--backend','--settings-file',_windows_to_wsl(self.settings_path),'--input-dir',_windows_to_wsl(input_dir),'--output-dir',_windows_to_wsl(output_dir)]
        if dry_run: backend.append('--dry-run')
        if env:
            if not exe: raise RuntimeError('Micromamba environment is selected but micromamba was not detected. Enter the WSL micromamba executable in the GUI.')
            prefix=[exe]
            if root: prefix += ['-r',root]
            prefix += ['run','-n',env]
            backend=prefix+backend
        shell=' '.join(shlex.quote(str(x)) for x in backend)
        return _wsl_base_args(distro)+['bash','-lc',shell]

    def _run(self,dry_run):
        try:
            settings,input_dir,output_dir=self._save()
            cmd=self._build_wsl_command(
                settings,
                input_dir,
                output_dir,
                dry_run,
            )
        except Exception as exc:
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate")
            self.progress_value.set(0.0)
            self.progress_text.set("Progress: Configuration error")
            self.messagebox.showerror("Execution error",str(exc))
            return

        self.status.set(
            "COMMAND:\n" + " ".join(shlex.quote(x) for x in cmd)
        )
        self._set_running_state(True,dry_run=dry_run)

        worker=threading.Thread(
            target=self._run_worker,
            args=(cmd,dry_run),
            daemon=True,
        )
        worker.start()

    def _set_running_state(self,running,dry_run=False):
        if running:
            self.save_button.configure(state="disabled")
            self.dry_run_button.configure(state="disabled")
            self.run_button.configure(state="disabled")
            self.open_output_button.configure(state="disabled")

            self.progress_bar.stop()
            self.progress_bar.configure(mode="indeterminate")
            self.progress_value.set(0.0)
            self.progress_bar.start(12)
            self.progress_text.set(
                "Progress: Dry run in progress..."
                if dry_run
                else "Progress: Step running..."
            )
        else:
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate")

            self.save_button.configure(state="normal")
            self.dry_run_button.configure(state="normal")
            self.run_button.configure(state="normal")
            self.open_output_button.configure(state="normal")

    def _run_worker(self,cmd,dry_run):
        try:
            completed=subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )
            stdout=completed.stdout or ""
            stderr=completed.stderr or ""
            combined=stdout + (("\n" + stderr) if stderr else "")

            self.root.after(
                0,
                lambda rc=completed.returncode,text=combined,dr=dry_run:
                    self._finish_run(rc,text,dr),
            )
        except Exception as exc:
            message=str(exc)
            self.root.after(
                0,
                lambda msg=message:self._finish_run_exception(msg),
            )

    def _finish_run(self,returncode,text,dry_run):
        self._set_running_state(False,dry_run=dry_run)

        display=text[-6000:] if text else f"Finished with code {returncode}"
        self.status.set(display)

        if returncode==0:
            self.progress_value.set(100.0)
            self.progress_text.set(
                "Progress: 100% — Dry run completed"
                if dry_run
                else "Progress: 100% — Step completed successfully"
            )
            self.messagebox.showinfo(
                "Finished",
                "Dry run completed."
                if dry_run
                else "Step completed successfully.",
            )
        else:
            self.progress_value.set(0.0)
            self.progress_text.set(
                f"Progress: FAILED — exit code {returncode}"
            )
            self.messagebox.showerror(
                "Step failed",
                text[-7000:] if text else f"Process exited with code {returncode}.",
            )

    def _finish_run_exception(self,message):
        self._set_running_state(False)
        self.progress_value.set(0.0)
        self.progress_text.set("Progress: FAILED — execution exception")
        self.status.set(message)
        self.messagebox.showerror("Execution error",message)

    def _open_output(self):
        path=self.vars['__output_dir__'].get().strip()
        if path and Path(path).exists(): os.startfile(path) if os.name=='nt' else subprocess.Popen(['xdg-open',path])

    def run(self): self.root.mainloop()

def launch_step(spec: StepSpecification, backend_function) -> None:
    def set_nested(mapping, path, value):
        node = mapping
        dotted = ".".join(path)
        for key in path[:-1]:
            if not isinstance(node, dict) or key not in node:
                raise KeyError(f"Missing required configuration setting path: {dotted}")
            node = node[key]
        if not isinstance(node, dict) or path[-1] not in node:
            raise KeyError(f"Unknown configuration setting: {dotted}")
        node[path[-1]] = value

    parser = build_cli_parser(spec.description)
    args = parser.parse_args()

    if args.backend or args.cli:
        try:
            input_dir = normalized_input_path(args.input_dir or (Path(__file__).resolve().parent / "input"))
            output_dir = normalized_input_path(args.output_dir or (Path(__file__).resolve().parent / "output"))
            output_dir.mkdir(parents=True, exist_ok=True)
            settings, _ = load_config(Path(args.settings_file) if args.settings_file else None)

            explicit_flags = {token.split("=", 1)[0] for token in sys.argv[1:] if token.startswith("--")}

            if args.cli or "--threads" in explicit_flags:
                if args.threads < 1:
                    raise ValueError("--threads must be at least 1.")
                settings["project"]["threads"] = int(args.threads)

            for action in parser._actions:
                dest = action.dest
                if not isinstance(dest, str) or not dest.startswith("__cfg__"):
                    continue
                flag_name = action.option_strings[0]
                if not args.cli and flag_name not in explicit_flags:
                    continue
                path = tuple(dest[len("__cfg__"):].split("__"))
                set_nested(settings, path, getattr(args, dest))

            effective_settings = output_dir / "cli_effective_settings.json"
            with effective_settings.open("w", encoding="utf-8") as handle:
                json.dump(settings, handle, indent=2)
                handle.write("\n")

            backend_function(effective_settings, input_dir, output_dir, args.dry_run)
        except Exception:
            traceback.print_exc()
            raise SystemExit(1)
    else:
        StandaloneStepGUI(spec, backend_function, globals().get("STEP_GUI", {})).run()




import sys
from pathlib import Path


import re
import gzip
import math
import statistics
import shutil
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

try:
    import pysam
except ModuleNotFoundError:
    pysam = None



SPEC = StepSpecification(
    number=6,
    title="06_ASSEMBLE_AND_CALL_CHROMOSOME_BREAKPOINTS",
    description=(
        "Call structural variants with five complementary strategies: SPAdes→minimap2 "
        "from Step 05 abnormal FASTQ evidence, plus Manta, GRIDSS2, DELLY and SvABA "
        "from complete Step 03 analysis-ready/validated BAMs. Normalize caller outputs "
        "into one breakpoint schema and optionally split results into user-selected "
        "canonical versus non-canonical reference events."
    ),
    default_input_dir="input",
    default_output_dir="output",
)


def fasta_lengths(path: Path) -> pd.DataFrame:
    rows: list[dict] = []
    if not path.exists():
        return pd.DataFrame(rows)
    name = None
    length = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith(">"):
                if name is not None:
                    rows.append({"CONTIG": name, "LENGTH": length})
                name = line[1:].strip().split()[0]
                length = 0
            else:
                length += len(line.strip())
    if name is not None:
        rows.append({"CONTIG": name, "LENGTH": length})
    return pd.DataFrame(rows)


def filter_fasta(source: Path, destination: Path, minimum_length: int) -> int:
    if not source.exists():
        return 0
    count = 0
    name = ""
    sequence_parts: list[str] = []
    with source.open("r", encoding="utf-8", errors="replace") as handle, destination.open(
        "w", encoding="utf-8"
    ) as target:
        def flush() -> None:
            nonlocal count, name, sequence_parts
            sequence = "".join(sequence_parts)
            if name and len(sequence) >= minimum_length:
                target.write(f">{name}\n")
                for start in range(0, len(sequence), 80):
                    target.write(sequence[start:start + 80] + "\n")
                count += 1

        for line in handle:
            if line.startswith(">"):
                flush()
                name = line[1:].strip().split()[0]
                sequence_parts = []
            else:
                sequence_parts.append(line.strip())
        flush()
    return count




def _is_valid_full_bam_filename(path: Path) -> bool:
    """
    Full/validated BAM rule for Step 06 Manta/local depth.

    ACCEPT:
      - *.bam
      - filename contains 'analysis_ready' OR 'validated'
      - filename does NOT contain 'abnormal'
    """
    name = path.name.lower()
    return (
        name.endswith(".bam")
        and "abnormal" not in name
        and ("analysis_ready" in name or "validated" in name)
    )


def _full_bam_sample_id_from_filename(path: Path) -> str:
    """
    Derive sample id from a validated/full BAM filename.

    Examples:
        Sample1.analysis_ready.bam -> Sample1
        Sample1_analysis_ready.bam -> Sample1
        Sample1.validated.bam      -> Sample1
        Sample1_validated.bam      -> Sample1

    The first occurrence of analysis_ready/validated is treated as the
    validation marker.
    """
    stem = path.name[:-4] if path.name.lower().endswith(".bam") else path.stem
    lower = stem.lower()

    positions = [
        position
        for marker in ("analysis_ready", "validated")
        for position in [lower.find(marker)]
        if position >= 0
    ]

    if not positions:
        return stem

    marker_position = min(positions)
    prefix = stem[:marker_position].rstrip("._- ")
    if prefix:
        return prefix

    # Fallback for unusual names beginning with the validation marker.
    remainder = stem
    remainder = re.sub(
        r"(?i)analysis_ready|validated",
        "",
        remainder,
        count=1,
    ).strip("._- ")
    return remainder or stem


def classify_full_bam_folder(folder_value: str) -> tuple[list[Path], list[Path]]:
    """
    Return (accepted, rejected) BAMs for the first Step 06 input folder.
    """
    folder_text = str(folder_value or "").strip()
    if not folder_text:
        return [], []

    folder = normalized_input_path(folder_text)
    if not folder.exists() or not folder.is_dir():
        return [], []

    all_bams = sorted(
        path
        for path in folder.rglob("*.bam")
        if path.is_file() and path.stat().st_size > 0
    )

    accepted = [path for path in all_bams if _is_valid_full_bam_filename(path)]
    rejected = [path for path in all_bams if path not in accepted]
    return accepted, rejected


def validate_full_bam_folder_for_manta(folder_value: str) -> list[Path]:
    """
    Validate the selected full-BAM folder.

    Wrong BAM filenames are excluded from the analysis. The folder is rejected
    only when it contains no acceptable full/validated BAM.
    """
    folder_text = str(folder_value or "").strip()
    if not folder_text:
        raise ValueError(
            "Select the Step 03 validated/full BAM folder for Manta."
        )

    folder = normalized_input_path(folder_text)
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(
            f"Validated/full BAM folder was not found: {folder}"
        )

    accepted, rejected = classify_full_bam_folder(folder_text)

    if not accepted:
        rejected_preview = "\n".join(
            f"  - {path.name}"
            for path in rejected[:15]
        )
        if rejected_preview:
            rejected_preview = "\n\nBAMs found but rejected:\n" + rejected_preview

        raise ValueError(
            "FULL BAM FOLDER REJECTED.\n\n"
            "A BAM is accepted for Manta/local depth only when:\n"
            "  1. its filename contains 'analysis_ready' OR 'validated', and\n"
            "  2. its filename does NOT contain 'abnormal'."
            + rejected_preview
        )

    return accepted


def validate_manta_analysis_ready_bam(
    bam_path: Path,
    sample_id: str,
) -> None:
    """
    Validate one complete/validated BAM before Manta/local-depth use.
    """
    if not _is_valid_full_bam_filename(bam_path):
        raise ValueError(
            f"Manta/full-BAM input for {sample_id} was rejected:\n"
            f"{bam_path}\n\n"
            "Accepted full BAM filenames must contain 'analysis_ready' or "
            "'validated', and must not contain 'abnormal'."
        )



def classify_step05_abnormal_folder(
    folder_value: str,
) -> dict[str, list[Path]]:
    """Classify the Step 05 folder for a FASTQ-only SPAdes branch."""
    folder_text = str(folder_value or "").strip()
    empty = {"ABNORMAL_FASTQS": [], "REJECTED_BAMS": []}
    if not folder_text:
        return empty

    folder = normalized_input_path(folder_text)
    if not folder.exists() or not folder.is_dir():
        return empty

    abnormal_fastqs: list[Path] = []
    rejected_bams: list[Path] = []
    fastq_suffixes = (
        ".fastq", ".fq", ".fastq.gz", ".fq.gz",
        ".fastq.bgz", ".fq.bgz", ".fastq.bgzf", ".fq.bgzf",
    )

    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.stat().st_size == 0:
            continue
        lower = path.name.lower()
        if lower.endswith(".bam"):
            rejected_bams.append(path)
            continue
        if "abnormal" in lower and lower.endswith(fastq_suffixes):
            abnormal_fastqs.append(path)

    return {
        "ABNORMAL_FASTQS": abnormal_fastqs,
        "REJECTED_BAMS": rejected_bams,
    }


def validate_step05_abnormal_folder(
    folder_value: str,
    require_spades_source: bool,
) -> dict[str, list[Path]]:
    """Validate that the SPAdes branch uses only Step 05 abnormal FASTQ/FQ files."""
    folder_text = str(folder_value or "").strip()
    if not folder_text:
        raise ValueError("Select the Step 05 abnormal FASTQ folder.")

    folder = normalized_input_path(folder_text)
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"Step 05 abnormal FASTQ folder was not found: {folder}")

    classified = classify_step05_abnormal_folder(folder_text)
    abnormal_fastqs = classified["ABNORMAL_FASTQS"]
    rejected_bams = classified["REJECTED_BAMS"]

    if require_spades_source and not abnormal_fastqs:
        bam_note = (
            f"\n\nFound {len(rejected_bams)} BAM file(s), but BAM is not accepted by the "
            "SPAdes branch. Select/provide the Step 05 abnormal FASTQ/FQ files."
            if rejected_bams else ""
        )
        raise ValueError(
            "SPAdes is enabled, but no non-empty abnormal FASTQ/FQ file was found. "
            "Accepted extensions are .fastq, .fq, .fastq.gz, and .fq.gz, and the "
            "filename must contain 'abnormal'." + bam_note
        )

    return classified

def validate_spades_abnormal_fastq_path(
    path_value: object,
    sample_id: str,
    role: str,
) -> str:
    """
    Verify that a SPAdes FASTQ input is explicitly an abnormal-read FASTQ.

    SPAdes in Step 06 is the local-assembly branch and must receive the abnormal
    FASTQs created by Step 05. Complete/raw FASTQs are not valid inputs here.
    """
    value = str(path_value or "").strip()
    if not value or value.lower() == "nan":
        return ""

    path = normalized_input_path(value)
    name_lower = path.name.lower()

    if "abnormal" not in name_lower:
        raise ValueError(
            f"SPAdes {role} input for {sample_id} was rejected because its filename "
            f"does not contain 'abnormal'.\n"
            f"Selected FASTQ: {path}\n\n"
            "Step 06 SPAdes must use Step 05 abnormal FASTQs."
        )

    if not name_lower.endswith(
        (
            ".fastq",
            ".fq",
            ".fastq.gz",
            ".fq.gz",
            ".fastq.bgz",
            ".fq.bgz",
        )
    ):
        raise ValueError(
            f"SPAdes {role} input for {sample_id} does not look like a FASTQ file:\n"
            f"{path}"
        )

    return str(path)




def algorithm_input_validation_rows(
    *,
    sample_id: str,
    row: dict,
    step03_full_bam: Path | None,
    run_spades_for_sample: bool,
    run_manta_for_sample: bool,
    run_gridss2_for_sample: bool,
    run_delly_for_sample: bool,
    run_svaba_for_sample: bool,
) -> list[dict[str, object]]:
    """Create an auditable per-algorithm input-selection report."""
    rows: list[dict[str, object]] = []

    if run_spades_for_sample:
        for role, key in [
            ("R1", "ABNORMAL_R1_FASTQ"),
            ("R2", "ABNORMAL_R2_FASTQ"),
            ("SINGLETON", "ABNORMAL_SINGLETON_FASTQ"),
        ]:
            value = str(row.get(key, "") or "").strip()
            if not value or value.lower() == "nan":
                continue
            lower = Path(value).name.lower()
            is_fastq = lower.endswith(
                (
                    ".fastq", ".fq", ".fastq.gz", ".fq.gz",
                    ".fastq.bgz", ".fq.bgz", ".fastq.bgzf", ".fq.bgzf",
                )
            )
            rows.append(
                {
                    "SAMPLE_ID": sample_id,
                    "ALGORITHM": "SPADES_MINIMAP2",
                    "EXPECTED_INPUT_CLASS": "STEP05_ABNORMAL_FASTQ_ONLY",
                    "INPUT_ROLE": role,
                    "SELECTED_INPUT": value,
                    "VALIDATION": (
                        "PASS_ABNORMAL_FASTQ"
                        if "abnormal" in lower and is_fastq
                        else "FAIL_NOT_ABNORMAL_FASTQ"
                    ),
                }
            )

    bam_callers = [
        ("MANTA", run_manta_for_sample),
        ("GRIDSS2", run_gridss2_for_sample),
        ("DELLY", run_delly_for_sample),
        ("SVABA", run_svaba_for_sample),
    ]
    for caller, enabled in bam_callers:
        if enabled and step03_full_bam is not None:
            rows.append(
                {
                    "SAMPLE_ID": sample_id,
                    "ALGORITHM": caller,
                    "EXPECTED_INPUT_CLASS": "COMPLETE_ANALYSIS_READY_BAM",
                    "INPUT_ROLE": "TUMOR_BAM",
                    "SELECTED_INPUT": str(step03_full_bam),
                    "VALIDATION": (
                        "PASS_VALIDATED_FULL_BAM"
                        if _is_valid_full_bam_filename(step03_full_bam)
                        else "FAIL_WRONG_BAM_CLASS"
                    ),
                }
            )

    return rows

def discover_step03_analysis_ready_bams(folder_value: str) -> pd.DataFrame:
    """
    Discover COMPLETE Step 03 BAMs accepted for Manta/local-depth calculations.

    Accepted filename rule:
        *.bam
        AND contains 'analysis_ready' OR 'validated'
        AND does NOT contain 'abnormal'
    """
    folder_text = str(folder_value or "").strip()
    if not folder_text:
        return pd.DataFrame(
            columns=["SAMPLE_ID", "ANALYSIS_READY_BAM", "FULL_BAM_NAME_RULE"]
        )

    accepted = validate_full_bam_folder_for_manta(folder_text)

    rows: list[dict] = []
    for bam_path in accepted:
        sample_id = _full_bam_sample_id_from_filename(bam_path)
        rows.append(
            {
                "SAMPLE_ID": sample_id,
                "ANALYSIS_READY_BAM": str(bam_path),
                "FULL_BAM_NAME_RULE": (
                    "PASS: contains analysis_ready/validated; excludes abnormal"
                ),
            }
        )

    table = pd.DataFrame(rows)
    if table.empty:
        return table

    duplicate_ids = (
        table["SAMPLE_ID"]
        .astype(str)
        .str.lower()
        .duplicated(keep=False)
    )
    if duplicate_ids.any():
        duplicate_rows = table.loc[duplicate_ids].sort_values("SAMPLE_ID")
        raise ValueError(
            "More than one accepted full BAM resolves to the same sample "
            "identifier. Keep one validated/full BAM per sample.\n\n"
            + duplicate_rows.to_string(index=False)
        )

    return table



def map_step03_bams_by_sample(table: pd.DataFrame) -> dict[str, Path]:
    """Return a case-insensitive sample-id lookup for Step 03 BAMs."""
    mapping: dict[str, Path] = {}
    if table.empty:
        return mapping

    for row in table.to_dict(orient="records"):
        sample_id = str(row["SAMPLE_ID"]).strip()
        bam = Path(str(row["ANALYSIS_READY_BAM"]))
        mapping[sample_id] = bam
        mapping[sample_id.lower()] = bam
    return mapping


def find_bai_for_bam(bam_path: Path) -> Path | None:
    """Find either common BAM index naming convention."""
    candidates = [
        Path(str(bam_path) + ".bai"),
        bam_path.with_suffix(".bai"),
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def ensure_step03_bam_ready(
    bam_path: Path,
    settings: dict,
    log_file: Path,
    dry_run: bool,
) -> dict[str, str]:
    """
    Validate the COMPLETE Step 03 BAM used by Manta/local-depth calculations.

    The BAM is never rewritten. A missing/stale BAI is recreated.
    """
    if dry_run:
        return {
            "BAM": str(bam_path),
            "SORT_ORDER": "DRY_RUN",
            "BAI": "",
            "BAI_STATUS": "DRY_RUN",
        }

    if pysam is None:
        raise ModuleNotFoundError(
            "pysam is required in the WSL backend for Step 06 local-depth metrics."
        )

    if not bam_path.exists() or not bam_path.is_file():
        raise FileNotFoundError(
            f"Step 03 analysis-ready BAM was not found: {bam_path}"
        )

    samtools = str(settings["tools"]["samtools"])

    run_command(
        [samtools, "quickcheck", "-v", str(bam_path)],
        log_file,
        dry_run=False,
    )

    with pysam.AlignmentFile(str(bam_path), "rb") as bam:
        header = bam.header.to_dict()
        sort_order = str(
            header.get("HD", {}).get("SO", "unknown")
        ).strip().lower()

    if sort_order != "coordinate":
        raise ValueError(
            "Manta requires the complete Step 03 BAM to be coordinate sorted.\n"
            f"BAM: {bam_path}\n"
            f"@HD SO={sort_order!r}"
        )

    bai = find_bai_for_bam(bam_path)
    if bai is None:
        bai_status = "CREATED_MISSING"
        run_command(
            [
                samtools,
                "index",
                "-@",
                str(threads(settings)),
                str(bam_path),
            ],
            log_file,
            dry_run=False,
        )
    elif bai.stat().st_mtime < bam_path.stat().st_mtime:
        bai_status = "REBUILT_STALE"
        run_command(
            [
                samtools,
                "index",
                "-@",
                str(threads(settings)),
                str(bam_path),
            ],
            log_file,
            dry_run=False,
        )
    else:
        bai_status = "EXISTING_CURRENT"

    bai = find_bai_for_bam(bam_path)
    if bai is None:
        raise FileNotFoundError(
            f"No usable BAM index was found after indexing: {bam_path}"
        )

    return {
        "BAM": str(bam_path),
        "SORT_ORDER": sort_order,
        "BAI": str(bai),
        "BAI_STATUS": bai_status,
    }


def _parse_ref_alt_support(value: object) -> tuple[int | None, int | None]:
    text = str(value or "").strip()
    if not text or text == ".":
        return None, None

    pieces = text.split(",")
    if len(pieces) < 2:
        return None, None

    try:
        return int(pieces[0]), int(pieces[1])
    except ValueError:
        return None, None


def _optional_float(value: object) -> float | None:
    text = str(value or "").strip()
    if not text or text == ".":
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _manta_scoring_status(vcf_path: Path) -> str:
    name = vcf_path.name.lower()
    if "somaticsv" in name:
        return "SOMATIC_SCORED_MATCHED_TUMOR_NORMAL"
    if "diploidsv" in name:
        return "DIPLOID_SCORED"
    if "tumorsv" in name:
        return "TUMOR_ONLY_UNSCORED"
    if "candidatesv" in name:
        return "UNSCORED_CANDIDATE"
    return "UNKNOWN"


def _local_depth_metrics(
    bam: "pysam.AlignmentFile",
    chrom: str,
    position_1based: int,
    radius_bp: int,
    minimum_mapping_quality: int,
) -> dict[str, float | int | str]:
    if chrom not in set(bam.references):
        return {
            "MEAN": float("nan"),
            "MEDIAN": float("nan"),
            "MAX": float("nan"),
            "COVERED_FRACTION": float("nan"),
            "WINDOW_START": "",
            "WINDOW_END": "",
        }

    radius = max(0, int(radius_bp))
    center0 = max(0, int(position_1based) - 1)
    start = max(0, center0 - radius)
    end = center0 + radius + 1

    reference_length = bam.get_reference_length(chrom)
    end = min(end, reference_length)

    if end <= start:
        return {
            "MEAN": 0.0,
            "MEDIAN": 0.0,
            "MAX": 0.0,
            "COVERED_FRACTION": 0.0,
            "WINDOW_START": start + 1,
            "WINDOW_END": end,
        }

    def read_callback(read) -> bool:
        return bool(
            not read.is_unmapped
            and not read.is_secondary
            and not read.is_qcfail
            and not read.is_duplicate
            and int(read.mapping_quality) >= int(minimum_mapping_quality)
        )

    a, c, g, t = bam.count_coverage(
        chrom,
        start,
        end,
        quality_threshold=0,
        read_callback=read_callback,
    )

    depths = [
        int(a[i]) + int(c[i]) + int(g[i]) + int(t[i])
        for i in range(end - start)
    ]

    if not depths:
        mean_depth = 0.0
        median_depth = 0.0
        max_depth = 0.0
        covered_fraction = 0.0
    else:
        mean_depth = float(sum(depths) / len(depths))
        median_depth = float(statistics.median(depths))
        max_depth = float(max(depths))
        covered_fraction = float(
            sum(1 for value in depths if value > 0) / len(depths)
        )

    return {
        "MEAN": mean_depth,
        "MEDIAN": median_depth,
        "MAX": max_depth,
        "COVERED_FRACTION": covered_fraction,
        "WINDOW_START": start + 1,
        "WINDOW_END": end,
    }



def _support_numeric_value(value: object) -> float | None:
    """Best-effort numeric magnitude from caller support fields."""
    raw = str(value or "").strip()
    if not raw or raw == ".":
        return None
    values: list[float] = []
    for token in re.split(r"[,|]", raw):
        token = token.strip()
        if not token:
            continue
        try:
            values.append(float(token))
        except ValueError:
            continue
    if not values:
        return None
    # For ref,alt pairs the alternate count is conventionally last; for a
    # single value this is simply that value.
    return values[-1]


def _heuristic_breakpoint_evidence_score(row: dict) -> tuple[float, str]:
    """
    Transparent 0-100 ranking score.

    IMPORTANT:
    This is NOT a p-value and NOT a calibrated probability.
    """
    source = str(row.get("SOURCE", "")).upper()

    local_min = _optional_float(row.get("LOCAL_DEPTH_MIN_MEAN"))
    local_component = 0.0
    if local_min is not None:
        local_component = 20.0 * min(max(local_min, 0.0) / 10.0, 1.0)

    score = local_component

    if source == "MANTA":
        if str(row.get("FILTER", "")).upper() == "PASS":
            score += 25.0

        alt_support = _optional_float(row.get("MANTA_ALT_SUPPORT_TOTAL"))
        if alt_support is not None:
            score += 25.0 * min(max(alt_support, 0.0) / 5.0, 1.0)

        split_alt = _optional_float(row.get("MANTA_SR_ALT"))
        if split_alt is not None:
            score += 15.0 * min(max(split_alt, 0.0) / 3.0, 1.0)

        imprecise = str(row.get("MANTA_IMPRECISE", "")).upper()
        if imprecise not in {"TRUE", "1", "YES"}:
            score += 10.0

        quality = _optional_float(row.get("MANTA_QUAL"))
        if quality is None:
            quality = _optional_float(row.get("MANTA_JUNCTION_QUAL"))
        if quality is not None:
            score += 5.0 * min(max(quality, 0.0) / 30.0, 1.0)

    elif source == "SPADES_CONTIG_MINIMAP2":
        min_mapq = _optional_float(row.get("CONTIG_MIN_MAPQ"))
        if min_mapq is not None:
            score += 25.0 * min(max(min_mapq, 0.0) / 60.0, 1.0)

        min_identity = _optional_float(row.get("CONTIG_MIN_ALIGNMENT_IDENTITY"))
        if min_identity is not None:
            identity_scaled = (min_identity - 0.85) / 0.15
            score += 25.0 * min(max(identity_scaled, 0.0), 1.0)

        min_alignment = _optional_float(row.get("CONTIG_MIN_ALIGNMENT_LENGTH"))
        if min_alignment is not None:
            score += 20.0 * min(max(min_alignment, 0.0) / 100.0, 1.0)

        if _optional_float(row.get("CONTIG_SUPPORT")):
            score += 10.0

    elif source in {"GRIDSS2", "DELLY", "SVABA"}:
        # Caller QUAL scales are not directly comparable, so use only a
        # conservative caller-specific contribution and retain raw QUAL in the
        # table for manual interpretation.
        if str(row.get("FILTER", "")).upper() == "PASS":
            score += 25.0

        quality = _optional_float(row.get("CALLER_QUAL"))
        if quality is not None:
            qual_scale = 1000.0 if source == "GRIDSS2" else 100.0
            score += 20.0 * min(max(quality, 0.0) / qual_scale, 1.0)

        split_support = _support_numeric_value(row.get("SPLIT_READ_SUPPORT"))
        paired_support = _support_numeric_value(row.get("PAIRED_READ_SUPPORT"))
        assembly_support = _support_numeric_value(row.get("CONTIG_SUPPORT"))
        support_values = [
            value for value in (split_support, paired_support, assembly_support)
            if value is not None
        ]
        if support_values:
            score += 25.0 * min(sum(max(v, 0.0) for v in support_values) / 5.0, 1.0)

    score = round(min(max(score, 0.0), 100.0), 2)

    if score >= 75:
        grade = "STRONG_EVIDENCE"
    elif score >= 50:
        grade = "MODERATE_EVIDENCE"
    elif score >= 25:
        grade = "WEAK_EVIDENCE"
    else:
        grade = "VERY_WEAK_EVIDENCE"

    return score, grade


def annotate_breakpoint_evidence(
    table: pd.DataFrame,
    bam_by_sample: dict[str, Path],
    cfg: dict,
) -> pd.DataFrame:
    if table.empty:
        return table

    radius = int(cfg["local_depth_window_bp"])
    minimum_mapq = int(cfg["local_depth_minimum_mapping_quality"])

    handles: dict[str, "pysam.AlignmentFile"] = {}
    output_rows: list[dict] = []

    try:
        for original in table.to_dict(orient="records"):
            row = dict(original)
            sample_id = str(row.get("SAMPLE_ID", "")).strip()

            bam_path = (
                bam_by_sample.get(sample_id)
                or bam_by_sample.get(sample_id.lower())
            )

            row["LOCAL_DEPTH_BAM"] = str(bam_path) if bam_path else ""
            row["LOCAL_DEPTH_RADIUS_BP"] = radius
            row["LOCAL_DEPTH_MINIMUM_MAPQ"] = minimum_mapq

            if bam_path is not None and pysam is not None:
                handle_key = str(bam_path)
                if handle_key not in handles:
                    handles[handle_key] = pysam.AlignmentFile(
                        str(bam_path),
                        "rb",
                    )
                bam = handles[handle_key]

                side1 = _local_depth_metrics(
                    bam,
                    str(row.get("CHROM1", "")),
                    int(row.get("POS1", 0)),
                    radius,
                    minimum_mapq,
                )
                side2 = _local_depth_metrics(
                    bam,
                    str(row.get("CHROM2", "")),
                    int(row.get("POS2", 0)),
                    radius,
                    minimum_mapq,
                )

                row["LOCAL_DEPTH_SIDE1_MEAN"] = side1["MEAN"]
                row["LOCAL_DEPTH_SIDE1_MEDIAN"] = side1["MEDIAN"]
                row["LOCAL_DEPTH_SIDE1_MAX"] = side1["MAX"]
                row["LOCAL_DEPTH_SIDE1_COVERED_FRACTION"] = side1["COVERED_FRACTION"]
                row["LOCAL_DEPTH_SIDE1_WINDOW_START"] = side1["WINDOW_START"]
                row["LOCAL_DEPTH_SIDE1_WINDOW_END"] = side1["WINDOW_END"]

                row["LOCAL_DEPTH_SIDE2_MEAN"] = side2["MEAN"]
                row["LOCAL_DEPTH_SIDE2_MEDIAN"] = side2["MEDIAN"]
                row["LOCAL_DEPTH_SIDE2_MAX"] = side2["MAX"]
                row["LOCAL_DEPTH_SIDE2_COVERED_FRACTION"] = side2["COVERED_FRACTION"]
                row["LOCAL_DEPTH_SIDE2_WINDOW_START"] = side2["WINDOW_START"]
                row["LOCAL_DEPTH_SIDE2_WINDOW_END"] = side2["WINDOW_END"]

                finite_means = []
                for value in [side1["MEAN"], side2["MEAN"]]:
                    parsed = _optional_float(value)
                    if parsed is not None and not math.isnan(parsed):
                        finite_means.append(parsed)

                row["LOCAL_DEPTH_MIN_MEAN"] = (
                    min(finite_means) if finite_means else ""
                )
                row["LOCAL_DEPTH_MEAN_OF_SIDES"] = (
                    sum(finite_means) / len(finite_means)
                    if finite_means
                    else ""
                )
                row["LOCAL_DEPTH_BOTH_SIDES_COVERED"] = (
                    "YES"
                    if len(finite_means) == 2
                    and all(value > 0 for value in finite_means)
                    else "NO"
                )
            else:
                for key in [
                    "LOCAL_DEPTH_SIDE1_MEAN",
                    "LOCAL_DEPTH_SIDE1_MEDIAN",
                    "LOCAL_DEPTH_SIDE1_MAX",
                    "LOCAL_DEPTH_SIDE1_COVERED_FRACTION",
                    "LOCAL_DEPTH_SIDE1_WINDOW_START",
                    "LOCAL_DEPTH_SIDE1_WINDOW_END",
                    "LOCAL_DEPTH_SIDE2_MEAN",
                    "LOCAL_DEPTH_SIDE2_MEDIAN",
                    "LOCAL_DEPTH_SIDE2_MAX",
                    "LOCAL_DEPTH_SIDE2_COVERED_FRACTION",
                    "LOCAL_DEPTH_SIDE2_WINDOW_START",
                    "LOCAL_DEPTH_SIDE2_WINDOW_END",
                    "LOCAL_DEPTH_MIN_MEAN",
                    "LOCAL_DEPTH_MEAN_OF_SIDES",
                ]:
                    row[key] = ""
                row["LOCAL_DEPTH_BOTH_SIDES_COVERED"] = "NO"

            score, grade = _heuristic_breakpoint_evidence_score(row)
            row["EVIDENCE_SCORE_0_100"] = score
            row["EVIDENCE_GRADE"] = grade
            row["EVIDENCE_SCORE_TYPE"] = "HEURISTIC_RANKING_NOT_P_VALUE"

            scoring_status = str(row.get("MANTA_SCORING_STATUS", ""))
            row["FORMAL_MANTA_SCORING_AVAILABLE"] = (
                "YES"
                if scoring_status
                in {
                    "SOMATIC_SCORED_MATCHED_TUMOR_NORMAL",
                    "DIPLOID_SCORED",
                }
                else "NO"
            )
            row["FORMAL_P_VALUE_AVAILABLE"] = "NO"
            source_name = str(row.get("SOURCE", "")).upper()
            if source_name == "MANTA":
                row["SIGNIFICANCE_NOTE"] = (
                    "No calibrated Step-06 breakpoint p-value is generated. Interpret "
                    "Manta with its FILTER/support/scoring fields plus local depth."
                )
            elif source_name in {"GRIDSS2", "DELLY", "SVABA"}:
                row["SIGNIFICANCE_NOTE"] = (
                    f"{source_name} caller-specific QUAL/FILTER/support fields are "
                    "retained. The Step-06 heuristic score is only a cross-record "
                    "review aid and is not a calibrated probability or p-value."
                )
            else:
                row["SIGNIFICANCE_NOTE"] = (
                    "Assembly/minimap2 evidence is heuristic and is not a calibrated "
                    "probability or p-value."
                )

            output_rows.append(row)
    finally:
        for handle in handles.values():
            handle.close()

    output = pd.DataFrame(output_rows)
    if "EVIDENCE_SCORE_0_100" in output.columns:
        output = output.sort_values(
            ["EVIDENCE_SCORE_0_100", "SAMPLE_ID"],
            ascending=[False, True],
            kind="stable",
        ).reset_index(drop=True)
    return output


def write_breakpoint_evidence_definition(path: Path) -> None:
    rows = [
        {
            "FIELD": "MANTA_QUAL",
            "MEANING": (
                "Raw VCF QUAL from Manta. It can be absent for tumor-only/unscored output."
            ),
        },
        {
            "FIELD": "MANTA_SOMATICSCORE / MANTA_JUNCTION_SOMATICSCORE",
            "MEANING": (
                "Manta somatic quality fields when a scored somatic model is available."
            ),
        },
        {
            "FIELD": "MANTA_QUAL_PHRED_ERROR_PROBABILITY",
            "MEANING": (
                "10^(-QUAL/10), reported only for Manta VCF types treated as scored."
            ),
        },
        {
            "FIELD": "MANTA_PR_REF / MANTA_PR_ALT",
            "MEANING": "Strong Q30 spanning-pair support for reference/alternate allele.",
        },
        {
            "FIELD": "MANTA_SR_REF / MANTA_SR_ALT",
            "MEANING": "Strong Q30 split-read support for reference/alternate allele.",
        },
        {
            "FIELD": "MANTA_ALT_SUPPORT_TOTAL",
            "MEANING": "PR_ALT + SR_ALT. Evidence count for ranking, not a p-value.",
        },
        {
            "FIELD": "LOCAL_DEPTH_SIDE1/2_*",
            "MEANING": (
                "Coverage around each breakend from the COMPLETE Step 03 analysis-ready BAM."
            ),
        },
        {
            "FIELD": "EVIDENCE_SCORE_0_100",
            "MEANING": (
                "Transparent heuristic ranking score combining support, FILTER, local "
                "depth and assembly/alignment evidence. NOT a probability or p-value."
            ),
        },
        {
            "FIELD": "FORMAL_P_VALUE_AVAILABLE",
            "MEANING": "Always NO; this pipeline does not invent a breakpoint p-value.",
        },
        {
            "FIELD": "CHROM1_REFERENCE_CLASS / CHROM2_REFERENCE_CLASS",
            "MEANING": (
                "CANONICAL when the breakend reference sequence was explicitly selected "
                "by the user in the FASTA chromosome selector; otherwise NON_CANONICAL."
            ),
        },
        {
            "FIELD": "BREAKPOINT_REFERENCE_CLASS",
            "MEANING": (
                "CANONICAL only when both breakends are on user-selected canonical "
                "reference sequences. All other events are NON_CANONICAL and retained "
                "in candidate_breakpoints_NonCanonical.tsv when canonical references are selected."
            ),
        },
    ]
    write_tsv(pd.DataFrame(rows), path)


def parse_paf_breakpoints(
    paf_path: Path,
    sample_id: str,
    minimum_alignment_length: int,
    minimum_reference_separation_bp: int,
) -> pd.DataFrame:
    if not paf_path.exists():
        return pd.DataFrame()
    columns = [
        "QUERY", "QUERY_LENGTH", "QUERY_START", "QUERY_END", "STRAND",
        "TARGET", "TARGET_LENGTH", "TARGET_START", "TARGET_END",
        "MATCHES", "ALIGNMENT_LENGTH", "MAPQ",
    ]
    rows: list[dict] = []
    with paf_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            pieces = line.rstrip("\n").split("\t")
            if len(pieces) < 12:
                continue
            record = dict(zip(columns, pieces[:12]))
            for key in [
                "QUERY_LENGTH", "QUERY_START", "QUERY_END", "TARGET_LENGTH",
                "TARGET_START", "TARGET_END", "MATCHES",
                "ALIGNMENT_LENGTH", "MAPQ",
            ]:
                record[key] = int(record[key])
            if record["ALIGNMENT_LENGTH"] >= minimum_alignment_length:
                rows.append(record)
    alignments = pd.DataFrame(rows)
    if alignments.empty:
        return pd.DataFrame()

    breakpoints: list[dict] = []
    for query, group in alignments.groupby("QUERY"):
        group = group.sort_values("QUERY_START")
        records = group.to_dict(orient="records")
        for left, right in zip(records, records[1:]):
            separated = (
                left["TARGET"] != right["TARGET"]
                or left["STRAND"] != right["STRAND"]
                or abs(int(left["TARGET_END"]) - int(right["TARGET_START"]))
                > int(minimum_reference_separation_bp)
            )
            if not separated:
                continue
            pos1 = int(left["TARGET_END"] if left["STRAND"] == "+" else left["TARGET_START"]) + 1
            pos2 = int(right["TARGET_START"] if right["STRAND"] == "+" else right["TARGET_END"]) + 1
            breakpoints.append(
                {
                    "SAMPLE_ID": sample_id,
                    "SOURCE": "SPADES_CONTIG_MINIMAP2",
                    "SVTYPE": "BND",
                    "CHROM1": left["TARGET"],
                    "POS1": pos1,
                    "STRAND1": left["STRAND"],
                    "CHROM2": right["TARGET"],
                    "POS2": pos2,
                    "STRAND2": right["STRAND"],
                    "CONTIG": query,
                    "SPLIT_READ_SUPPORT": "",
                    "PAIRED_READ_SUPPORT": "",
                    "CONTIG_SUPPORT": 1,
                    "CONTIG_LEFT_MAPQ": int(left["MAPQ"]),
                    "CONTIG_RIGHT_MAPQ": int(right["MAPQ"]),
                    "CONTIG_MIN_MAPQ": min(int(left["MAPQ"]), int(right["MAPQ"])),
                    "CONTIG_LEFT_ALIGNMENT_LENGTH": int(left["ALIGNMENT_LENGTH"]),
                    "CONTIG_RIGHT_ALIGNMENT_LENGTH": int(right["ALIGNMENT_LENGTH"]),
                    "CONTIG_MIN_ALIGNMENT_LENGTH": min(
                        int(left["ALIGNMENT_LENGTH"]),
                        int(right["ALIGNMENT_LENGTH"]),
                    ),
                    "CONTIG_LEFT_ALIGNMENT_IDENTITY": (
                        float(left["MATCHES"]) / float(left["ALIGNMENT_LENGTH"])
                        if int(left["ALIGNMENT_LENGTH"]) > 0 else 0.0
                    ),
                    "CONTIG_RIGHT_ALIGNMENT_IDENTITY": (
                        float(right["MATCHES"]) / float(right["ALIGNMENT_LENGTH"])
                        if int(right["ALIGNMENT_LENGTH"]) > 0 else 0.0
                    ),
                    "CONTIG_MIN_ALIGNMENT_IDENTITY": min(
                        (
                            float(left["MATCHES"]) / float(left["ALIGNMENT_LENGTH"])
                            if int(left["ALIGNMENT_LENGTH"]) > 0 else 0.0
                        ),
                        (
                            float(right["MATCHES"]) / float(right["ALIGNMENT_LENGTH"])
                            if int(right["ALIGNMENT_LENGTH"]) > 0 else 0.0
                        ),
                    ),
                    "MANTA_SCORING_STATUS": "",
                    "FILTER": "ASSEMBLY_CANDIDATE",
                }
            )
    return pd.DataFrame(breakpoints)


BND_PATTERN = re.compile(r"[\[\]]([^:\[\]]+):(\d+)[\[\]]")


def _parse_vcf_info_text(text: str) -> dict[str, str]:
    """Parse a VCF INFO column without requiring header declarations."""
    output: dict[str, str] = {}
    text = str(text or "").strip()
    if not text or text == ".":
        return output

    for item in text.split(";"):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            key, value = item.split("=", 1)
            output[key] = value
        else:
            output[item] = "TRUE"
    return output


def _first_integer(value: object, default: int) -> int:
    """Return the first integer-like token from a VCF value."""
    text = str(value or "").strip()
    if not text or text == ".":
        return int(default)

    token = text.split(",", 1)[0].strip()
    try:
        return int(float(token))
    except (TypeError, ValueError):
        return int(default)


def _svtype_from_alt(alt: str) -> str:
    """Infer an SV type if INFO/SVTYPE is absent."""
    alt = str(alt or "")
    if "[" in alt or "]" in alt:
        return "BND"
    if alt.startswith("<") and alt.endswith(">"):
        symbolic = alt[1:-1].strip()
        if symbolic:
            return symbolic
    return "BND"


def _manta_format_support(
    format_text: str,
    sample_texts: list[str],
    key: str,
) -> str:
    """
    Retrieve a Manta FORMAT value such as PR or SR.

    The raw value is retained (for example `20,7`) so both reference and
    alternate support counts remain available.
    """
    format_text = str(format_text or "").strip()
    if not format_text or format_text == ".":
        return ""

    keys = format_text.split(":")
    try:
        index = keys.index(key)
    except ValueError:
        return ""

    for sample_text in sample_texts:
        values = str(sample_text or "").split(":")
        if index >= len(values):
            continue
        value = values[index].strip()
        if value and value != ".":
            return value

    return ""


def parse_manta_vcf(
    vcf_path: Path,
    sample_id: str,
    diagnostics_path: Path | None = None,
) -> pd.DataFrame:
    """
    Parse Manta VCF/VCF.GZ without strict pysam INFO-header lookup.

    Some Manta VCFs do not declare every optional INFO key, especially CHR2.
    Strict VariantRecord INFO access can then raise `ValueError: Invalid header`.

    Direct streaming text parsing is sufficient for Step 06 and avoids that
    failure. Individual malformed records are logged and skipped instead of
    aborting the complete run.
    """
    if not vcf_path.exists() or vcf_path.stat().st_size == 0:
        if diagnostics_path is not None:
            write_tsv(
                pd.DataFrame(
                    [{
                        "SAMPLE_ID": sample_id,
                        "VCF_PATH": str(vcf_path),
                        "STATUS": "VCF_MISSING_OR_EMPTY",
                        "TOTAL_RECORDS": 0,
                        "PARSED_RECORDS": 0,
                        "SKIPPED_RECORDS": 0,
                        "MESSAGE": "Manta VCF was missing or empty.",
                    }]
                ),
                diagnostics_path,
            )
        return pd.DataFrame()

    opener = (
        gzip.open
        if str(vcf_path).lower().endswith((".gz", ".bgz", ".bgzf"))
        else open
    )

    rows: list[dict] = []
    error_rows: list[dict] = []
    total_records = 0
    parsed_records = 0
    skipped_records = 0
    declared_info_ids: list[str] = []
    declared_format_ids: list[str] = []
    vcf_samples: list[str] = []

    with opener(
        vcf_path,
        "rt",
        encoding="utf-8",
        errors="replace",
    ) as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.rstrip("\r\n")

            if line.startswith("##INFO=<ID="):
                declared_info_ids.append(
                    line.split("##INFO=<ID=", 1)[1].split(",", 1)[0]
                )
                continue

            if line.startswith("##FORMAT=<ID="):
                declared_format_ids.append(
                    line.split("##FORMAT=<ID=", 1)[1].split(",", 1)[0]
                )
                continue

            if line.startswith("#CHROM"):
                header_fields = line.split("\t")
                if len(header_fields) > 9:
                    vcf_samples = header_fields[9:]
                continue

            if not line or line.startswith("#"):
                continue

            total_records += 1
            fields: list[str] = []

            try:
                fields = line.split("\t")
                if len(fields) < 8:
                    raise ValueError(
                        f"VCF record has {len(fields)} columns; expected at least 8."
                    )

                chrom1 = fields[0]
                pos1 = int(fields[1])
                manta_id = "" if fields[2] == "." else fields[2]
                alt = "" if fields[4] == "." else fields[4]
                qual_text = "" if fields[5] in {"", "."} else fields[5]
                qual_value = _optional_float(qual_text)
                scoring_status = _manta_scoring_status(vcf_path)
                filter_text = (
                    "UNFILTERED"
                    if fields[6] in {"", "."}
                    else fields[6]
                )

                info = _parse_vcf_info_text(fields[7])

                svtype = str(
                    info.get("SVTYPE")
                    or _svtype_from_alt(alt)
                )

                # Non-breakend events default to the same chromosome.
                chrom2 = str(info.get("CHR2") or chrom1)
                pos2 = _first_integer(
                    info.get("END", ""),
                    pos1,
                )

                # BND/translocation partner is encoded directly in ALT.
                match = BND_PATTERN.search(alt)
                if match:
                    chrom2 = match.group(1)
                    pos2 = int(match.group(2))
                    if not info.get("SVTYPE"):
                        svtype = "BND"

                format_text = fields[8] if len(fields) >= 9 else ""
                sample_texts = fields[9:] if len(fields) >= 10 else []

                # Manta commonly stores PR/SR in FORMAT rather than INFO.
                pr = str(info.get("PR", "")).strip()
                sr = str(info.get("SR", "")).strip()

                if not pr:
                    pr = _manta_format_support(
                        format_text,
                        sample_texts,
                        "PR",
                    )
                if not sr:
                    sr = _manta_format_support(
                        format_text,
                        sample_texts,
                        "SR",
                    )

                ft = _manta_format_support(format_text, sample_texts, "FT")
                gq = _manta_format_support(format_text, sample_texts, "GQ")

                pr_ref, pr_alt = _parse_ref_alt_support(pr)
                sr_ref, sr_alt = _parse_ref_alt_support(sr)

                alt_components = [
                    value for value in [pr_alt, sr_alt] if value is not None
                ]
                ref_components = [
                    value for value in [pr_ref, sr_ref] if value is not None
                ]
                alt_support_total = sum(alt_components) if alt_components else ""
                ref_support_total = sum(ref_components) if ref_components else ""

                support_fraction = ""
                denominator = (
                    (sum(alt_components) if alt_components else 0)
                    + (sum(ref_components) if ref_components else 0)
                )
                if denominator > 0:
                    support_fraction = (
                        (sum(alt_components) if alt_components else 0)
                        / denominator
                    )

                qual_error_probability = ""
                if (
                    qual_value is not None
                    and scoring_status
                    in {
                        "SOMATIC_SCORED_MATCHED_TUMOR_NORMAL",
                        "DIPLOID_SCORED",
                    }
                ):
                    qual_error_probability = 10.0 ** (
                        -float(qual_value) / 10.0
                    )

                rows.append(
                    {
                        "SAMPLE_ID": sample_id,
                        "SOURCE": "MANTA",
                        "SVTYPE": svtype,
                        "CHROM1": chrom1,
                        "POS1": pos1,
                        "STRAND1": "",
                        "CHROM2": chrom2,
                        "POS2": pos2,
                        "STRAND2": "",
                        "CONTIG": "",
                        "SPLIT_READ_SUPPORT": sr,
                        "PAIRED_READ_SUPPORT": pr,
                        "CONTIG_SUPPORT": "",
                        "FILTER": filter_text,
                        "MANTA_ID": manta_id,
                        "MANTA_VCF_FILE": str(vcf_path),
                        "MANTA_SCORING_STATUS": scoring_status,
                        "MANTA_QUAL": qual_value if qual_value is not None else "",
                        "MANTA_QUAL_PHRED_ERROR_PROBABILITY": qual_error_probability,
                        "MANTA_SOMATICSCORE": info.get("SOMATICSCORE", ""),
                        "MANTA_JUNCTION_QUAL": info.get("JUNCTION_QUAL", ""),
                        "MANTA_JUNCTION_SOMATICSCORE": info.get(
                            "JUNCTION_SOMATICSCORE", ""
                        ),
                        "MANTA_BND_DEPTH": info.get("BND_DEPTH", ""),
                        "MANTA_MATE_BND_DEPTH": info.get("MATE_BND_DEPTH", ""),
                        "MANTA_IMPRECISE": (
                            "TRUE" if "IMPRECISE" in info else "FALSE"
                        ),
                        "MANTA_CIPOS": info.get("CIPOS", ""),
                        "MANTA_CIEND": info.get("CIEND", ""),
                        "MANTA_EVENT": info.get("EVENT", ""),
                        "MANTA_MATEID": info.get("MATEID", ""),
                        "MANTA_SAMPLE_FILTER_FT": ft,
                        "MANTA_GQ": gq,
                        "MANTA_PR_REF": pr_ref if pr_ref is not None else "",
                        "MANTA_PR_ALT": pr_alt if pr_alt is not None else "",
                        "MANTA_SR_REF": sr_ref if sr_ref is not None else "",
                        "MANTA_SR_ALT": sr_alt if sr_alt is not None else "",
                        "MANTA_ALT_SUPPORT_TOTAL": alt_support_total,
                        "MANTA_REF_SUPPORT_TOTAL": ref_support_total,
                        "MANTA_SUPPORT_FRACTION": support_fraction,
                    }
                )
                parsed_records += 1

            except Exception as exc:
                skipped_records += 1
                error_rows.append(
                    {
                        "SAMPLE_ID": sample_id,
                        "VCF_PATH": str(vcf_path),
                        "STATUS": "RECORD_SKIPPED",
                        "LINE_NUMBER": line_number,
                        "RECORD_ID": fields[2] if len(fields) > 2 else "",
                        "CHROM": fields[0] if len(fields) > 0 else "",
                        "POS": fields[1] if len(fields) > 1 else "",
                        "ALT": fields[4] if len(fields) > 4 else "",
                        "MESSAGE": str(exc),
                    }
                )

    if diagnostics_path is not None:
        summary_row = {
            "SAMPLE_ID": sample_id,
            "VCF_PATH": str(vcf_path),
            "STATUS": (
                "PARSE_COMPLETED_WITH_SKIPPED_RECORDS"
                if skipped_records
                else "PARSE_COMPLETED"
            ),
            "TOTAL_RECORDS": total_records,
            "PARSED_RECORDS": parsed_records,
            "SKIPPED_RECORDS": skipped_records,
            "VCF_SAMPLE_COLUMNS": ";".join(vcf_samples),
            "DECLARED_INFO_IDS": ";".join(declared_info_ids),
            "DECLARED_FORMAT_IDS": ";".join(declared_format_ids),
            "CHR2_DECLARED_IN_INFO_HEADER": "CHR2" in declared_info_ids,
            "PR_DECLARED_IN_INFO_HEADER": "PR" in declared_info_ids,
            "PR_DECLARED_IN_FORMAT_HEADER": "PR" in declared_format_ids,
            "SR_DECLARED_IN_INFO_HEADER": "SR" in declared_info_ids,
            "SR_DECLARED_IN_FORMAT_HEADER": "SR" in declared_format_ids,
            "MESSAGE": (
                "Header-independent Manta parser used; undeclared INFO fields "
                "cannot trigger strict-header lookup errors."
            ),
        }

        write_tsv(
            pd.DataFrame([summary_row, *error_rows]),
            diagnostics_path,
        )

    return pd.DataFrame(rows)



def _is_vcf_single_breakend_alt(alt: str) -> bool:
    """Return True for VCF single-breakend notation such as A. or .A."""
    alt = str(alt or "").strip()
    return bool(alt) and ("[" not in alt and "]" not in alt) and (
        alt.startswith(".") or alt.endswith(".")
    )


def parse_generic_sv_vcf(
    vcf_path: Path,
    sample_id: str,
    caller: str,
    diagnostics_path: Path | None = None,
    collapse_reciprocal_mates: bool = True,
) -> pd.DataFrame:
    """
    Parse a caller VCF into the common Step-06 breakpoint schema.

    Used for GRIDSS2, DELLY and SvABA. Breakend ALT partner coordinates are
    parsed directly from VCF BND notation. For paired BND records carrying
    MATEID, only one reciprocal representation is retained so the same junction
    is not counted twice merely because VCF encodes both breakends.
    """
    caller = str(caller).strip().upper()
    if not vcf_path.exists() or vcf_path.stat().st_size == 0:
        if diagnostics_path is not None:
            write_tsv(
                pd.DataFrame(
                    [{
                        "SAMPLE_ID": sample_id,
                        "CALLER": caller,
                        "VCF_PATH": str(vcf_path),
                        "STATUS": "VCF_MISSING_OR_EMPTY",
                        "TOTAL_RECORDS": 0,
                        "PARSED_RECORDS": 0,
                        "SKIPPED_RECORDS": 0,
                        "RECIPROCAL_MATES_COLLAPSED": 0,
                    }]
                ),
                diagnostics_path,
            )
        return pd.DataFrame()

    opener = (
        gzip.open
        if str(vcf_path).lower().endswith((".gz", ".bgz", ".bgzf"))
        else open
    )
    rows: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    skip_record_ids: set[str] = set()
    total_records = 0
    parsed_records = 0
    skipped_records = 0
    reciprocal_collapsed = 0

    with opener(vcf_path, "rt", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            total_records += 1
            fields = line.split("\t")
            try:
                if len(fields) < 8:
                    raise ValueError(
                        f"VCF record has {len(fields)} columns; expected at least 8."
                    )

                chrom1 = str(fields[0])
                pos1 = int(fields[1])
                record_id = "" if fields[2] == "." else str(fields[2])
                alt = "" if fields[4] == "." else str(fields[4])
                qual = _optional_float(fields[5])
                filter_text = (
                    "UNFILTERED" if fields[6] in {"", "."} else str(fields[6])
                )
                info = _parse_vcf_info_text(fields[7])

                if (
                    collapse_reciprocal_mates
                    and record_id
                    and record_id in skip_record_ids
                ):
                    reciprocal_collapsed += 1
                    continue

                svtype = str(info.get("SVTYPE") or _svtype_from_alt(alt)).upper()
                chrom2 = str(info.get("CHR2") or chrom1)
                pos2 = _first_integer(info.get("END", ""), pos1)

                bnd_match = BND_PATTERN.search(alt)
                if bnd_match:
                    chrom2 = str(bnd_match.group(1))
                    pos2 = int(bnd_match.group(2))
                    svtype = "BND"
                elif _is_vcf_single_breakend_alt(alt):
                    # Keep the one resolved coordinate and explicitly leave the
                    # partner reference blank. POS2 remains numeric so downstream
                    # evidence annotation cannot fail on integer conversion.
                    chrom2 = ""
                    pos2 = pos1
                    svtype = "SINGLE_BND"

                mateid = str(info.get("MATEID", "") or "").split(",", 1)[0].strip()
                if collapse_reciprocal_mates and mateid:
                    skip_record_ids.add(mateid)

                split_support = (
                    info.get("SR", "")
                    or info.get("SRQ", "")
                    or info.get("BSC", "")
                )
                paired_support = (
                    info.get("PE", "")
                    or info.get("RP", "")
                    or info.get("PR", "")
                )
                assembly_support = (
                    info.get("AS", "")
                    or info.get("RAS", "")
                    or info.get("ASM", "")
                )

                rows.append(
                    {
                        "SAMPLE_ID": sample_id,
                        "SOURCE": caller,
                        "SVTYPE": svtype,
                        "CHROM1": chrom1,
                        "POS1": pos1,
                        "STRAND1": "",
                        "CHROM2": chrom2,
                        "POS2": pos2,
                        "STRAND2": "",
                        "CONTIG": "",
                        "SPLIT_READ_SUPPORT": split_support,
                        "PAIRED_READ_SUPPORT": paired_support,
                        "CONTIG_SUPPORT": assembly_support,
                        "FILTER": filter_text,
                        "CALLER_RECORD_ID": record_id,
                        "CALLER_VCF_FILE": str(vcf_path),
                        "CALLER_QUAL": qual if qual is not None else "",
                        "CALLER_ALT": alt,
                        "CALLER_EVENT": info.get("EVENT", ""),
                        "CALLER_MATEID": info.get("MATEID", ""),
                        "CALLER_INFO": fields[7],
                    }
                )
                parsed_records += 1
            except Exception as exc:
                skipped_records += 1
                errors.append(
                    {
                        "SAMPLE_ID": sample_id,
                        "CALLER": caller,
                        "VCF_PATH": str(vcf_path),
                        "STATUS": "RECORD_SKIPPED",
                        "LINE_NUMBER": line_number,
                        "RECORD_ID": fields[2] if len(fields) > 2 else "",
                        "CHROM": fields[0] if len(fields) > 0 else "",
                        "POS": fields[1] if len(fields) > 1 else "",
                        "MESSAGE": str(exc),
                    }
                )

    if diagnostics_path is not None:
        summary = {
            "SAMPLE_ID": sample_id,
            "CALLER": caller,
            "VCF_PATH": str(vcf_path),
            "STATUS": (
                "PARSE_COMPLETED_WITH_SKIPPED_RECORDS"
                if skipped_records else "PARSE_COMPLETED"
            ),
            "TOTAL_RECORDS": total_records,
            "PARSED_RECORDS": parsed_records,
            "SKIPPED_RECORDS": skipped_records,
            "RECIPROCAL_MATES_COLLAPSED": reciprocal_collapsed,
            "MESSAGE": (
                "Generic VCF parser normalized the caller output to CHROM1/POS1/"
                "CHROM2/POS2. Reciprocal MATEID BND records are collapsed."
            ),
        }
        write_tsv(pd.DataFrame([summary, *errors]), diagnostics_path)

    return pd.DataFrame(rows)


CLASSIC_BWA_INDEX_SUFFIXES = (".amb", ".ann", ".bwt", ".pac", ".sa")


def _classic_bwa_index_prefix_from_selected_file(index_file: Path) -> Path:
    """Return the classic-BWA index prefix after validating one selected component."""
    text = str(index_file)
    for suffix in CLASSIC_BWA_INDEX_SUFFIXES:
        if text.lower().endswith(suffix):
            return Path(text[:-len(suffix)])
    raise ValueError(
        "Classic BWA index selection must be one of: "
        + ", ".join(CLASSIC_BWA_INDEX_SUFFIXES)
        + f". Selected: {index_file}"
    )


def validate_classic_bwa_reference_indexes(
    reference: Path,
    selected_index_file: Path,
) -> dict[str, object]:
    """
    Validate the explicit classic-BWA index selection shared by GRIDSS2/SvABA.

    GRIDSS2 requires classic BWA index files whose prefix exactly matches the
    reference FASTA filename. SvABA also uses BWA-MEM-based reference alignment.
    The GUI can create these classic BWA indexes with the 'Create BWA-MEM index'
    button, or the user can browse to one existing component. This function
    verifies the complete set.
    """
    if not selected_index_file.exists() or not selected_index_file.is_file():
        raise FileNotFoundError(
            f"Selected classic BWA index file was not found: {selected_index_file}"
        )

    prefix = _classic_bwa_index_prefix_from_selected_file(selected_index_file)

    # The index prefix itself is the FASTA path GRIDSS2/SvABA must use. It may be
    # either the original FASTA or an exact mirror in BWA-MEM1_Index.
    indexed_reference = prefix
    if not indexed_reference.exists() or not indexed_reference.is_file():
        raise FileNotFoundError(
            "The FASTA corresponding to the selected classic BWA index prefix was not found.\n"
            f"Expected indexed FASTA: {indexed_reference}"
        )

    if indexed_reference.name != reference.name:
        raise ValueError(
            "The selected classic BWA index uses a FASTA basename that does not match "
            "the selected reference FASTA.\n"
            f"Reference FASTA: {reference.name}\n"
            f"Indexed FASTA: {indexed_reference.name}"
        )

    try:
        source_size = reference.stat().st_size
        indexed_size = indexed_reference.stat().st_size
    except OSError as exc:
        raise OSError(f"Could not compare reference FASTA files: {exc}") from exc
    if source_size != indexed_size:
        raise ValueError(
            "The FASTA stored with the selected classic BWA index does not match the "
            "selected reference FASTA size. Recreate the index with the GUI button.\n"
            f"Reference FASTA: {reference} ({source_size} bytes)\n"
            f"Indexed FASTA: {indexed_reference} ({indexed_size} bytes)"
        )

    required = [Path(str(prefix) + suffix) for suffix in CLASSIC_BWA_INDEX_SUFFIXES]
    missing = [
        path for path in required
        if not path.exists() or not path.is_file() or path.stat().st_size == 0
    ]
    if missing:
        raise FileNotFoundError(
            "The selected classic BWA index set is incomplete. Use the GUI's "
            "Create BWA-MEM index button or select a complete existing index set.\nMissing:\n  - "
            + "\n  - ".join(str(path) for path in missing)
        )

    indexed_fai = Path(str(indexed_reference) + ".fai")
    if not indexed_fai.exists() or indexed_fai.stat().st_size == 0:
        raise FileNotFoundError(
            "The indexed FASTA used by GRIDSS2/SvABA is missing its .fai index: "
            f"{indexed_fai}. Recreate the BWA-MEM1 index with the GUI button."
        )

    return {
        "SELECTED_INDEX_FILE": str(selected_index_file),
        "INDEX_PREFIX": str(prefix),
        "INDEX_FILES": [str(path) for path in required],
        "REFERENCE_FOR_BWA_CALLERS": str(indexed_reference),
        "REFERENCE_FAI_FOR_BWA_CALLERS": str(indexed_fai),
    }


def validate_or_create_reference_fai(
    reference: Path,
    selected_fai_value: object,
    settings: dict,
    log_file: Path,
    dry_run: bool,
) -> Path:
    """Use an explicitly browsed .fai when supplied, otherwise use/create <FASTA>.fai."""
    expected = Path(str(reference) + ".fai")
    selected_text = str(selected_fai_value or "").strip()

    if selected_text:
        selected = normalized_input_path(selected_text)
        try:
            selected_cmp = selected.resolve()
            expected_cmp = expected.resolve()
        except OSError:
            selected_cmp = selected
            expected_cmp = expected
        if selected_cmp != expected_cmp:
            raise ValueError(
                "The selected FASTA index (.fai) must belong to the selected reference FASTA.\n"
                f"Reference FASTA: {reference}\n"
                f"Expected .fai: {expected}\n"
                f"Selected .fai: {selected}"
            )
        if not dry_run and (
            not selected.exists() or not selected.is_file() or selected.stat().st_size == 0
        ):
            raise FileNotFoundError(f"Selected FASTA .fai was not found or is empty: {selected}")

    if dry_run:
        return expected

    if not expected.exists() or expected.stat().st_size == 0:
        run_command(
            [str(settings["tools"]["samtools"]), "faidx", str(reference)],
            log_file,
            dry_run=False,
        )
    if not expected.exists() or expected.stat().st_size == 0:
        raise FileNotFoundError(
            "samtools faidx completed but the reference FASTA index was not created: "
            f"{expected}"
        )
    return expected


def locate_svaba_sv_vcf(run_dir: Path, output_prefix: str) -> Path | None:
    """Locate the structural-variant VCF produced by SvABA."""
    preferred = run_dir / f"{output_prefix}.svaba.sv.vcf"
    if preferred.exists() and preferred.stat().st_size > 0:
        return preferred
    candidates = sorted(run_dir.glob("*.svaba.sv.vcf*"))
    return next(
        (path for path in candidates if path.is_file() and path.stat().st_size > 0),
        None,
    )

def locate_manta_vcf(run_dir: Path) -> Path | None:
    """Locate a structural-variant VCF produced by Manta."""
    candidates = [
        run_dir / "results/variants/somaticSV.vcf.gz",
        run_dir / "results/variants/tumorSV.vcf.gz",
        run_dir / "results/variants/diploidSV.vcf.gz",
        run_dir / "results/variants/candidateSV.vcf.gz",
    ]
    return next(
        (
            path
            for path in candidates
            if path.exists() and path.stat().st_size > 0
        ),
        None,
    )


def breakpoint_parameter_rows(settings: dict) -> list[dict[str, object]]:
    cfg = settings["breakpoints"]
    refs = settings["references"]
    return [
        {
            "PARAMETER": "reference_fasta",
            "VALUE": str(refs["fasta"]),
            "EXPLANATION": (
                "Reference FASTA used by minimap2 and Manta. It should be the exact "
                "same genome build/reference sequence used to create the Step 03 "
                "analysis-ready BAM files."
            ),
        },
        {
            "PARAMETER": "reference_fasta_fai",
            "VALUE": str(refs.get("fasta_fai", "")),
            "EXPLANATION": (
                "Optional explicitly browsed FASTA .fai. If blank, Step 06 uses or "
                "creates <reference FASTA>.fai with samtools faidx."
            ),
        },
        {
            "PARAMETER": "classic_bwa_index_file",
            "VALUE": str(cfg.get("classic_bwa_index_file", "")),
            "EXPLANATION": (
                "One selected or GUI-created classic BWA/BWA-MEM index component for GRIDSS2/SvABA. The GUI creator stores it under BWA-MEM1_Index beside the original reference folder. "
                "Step 06 verifies the full .amb/.ann/.bwt/.pac/.sa set and requires "
                "the index prefix to match the selected reference FASTA exactly."
            ),
        },
        {
            "PARAMETER": "canonical_chromosomes",
            "VALUE": str(cfg.get("canonical_chromosomes", "")),
            "EXPLANATION": (
                "User-selected FASTA reference sequences treated as canonical. A "
                "breakpoint is canonical only when both breakends use names in this "
                "set. Every other event is preserved as non-canonical for review."
            ),
        },
        {
            "PARAMETER": "spades_linux_work_root",
            "VALUE": str(resolve_spades_linux_work_root(settings)),
            "EXPLANATION": (
                "Fixed native-Linux SPAdes work directory: "
                "$HOME/ctdna_step06_spades_work. It is intentionally not "
                "user-configurable. No random temporary folder names are created."
            ),
        },
        {
            "PARAMETER": "algorithm_input_class_validation",
            "VALUE": "ENABLED",
            "EXPLANATION": (
                "SPAdes accepts only Step 05 FASTQ filenames containing 'abnormal'. "
                "Manta accepts only complete *.analysis_ready.bam files and rejects "
                "any selected BAM folder containing filenames with 'abnormal'."
            ),
        },
        {
            "PARAMETER": "run_spades_assembly",
            "VALUE": bool(cfg["run_spades_assembly"]),
            "EXPLANATION": (
                "When enabled, abnormal FASTQ reads from Step 05 are assembled "
                "with SPAdes and the resulting contigs are aligned to the reference."
            ),
        },
        {
            "PARAMETER": "manta_config_command_or_path",
            "VALUE": str(settings['tools']['manta_config']),
            "EXPLANATION": (
                "Explicit user-selected Manta configManta.py command/path. "
                "No Manta absolute path is hardcoded by Step 06."
            ),
        },
        {
            "PARAMETER": "manta_workflow_runner_command_or_path",
            "VALUE": str(settings['tools']['manta_run']),
            "EXPLANATION": (
                "Explicit user-selected Manta workflow runner command/path. "
                "No Manta absolute path is hardcoded by Step 06."
            ),
        },
        {
            "PARAMETER": "analysis_ready_bam_folder",
            "VALUE": str(cfg["analysis_ready_bam_folder"]),
            "EXPLANATION": (
                "Folder containing COMPLETE Step 03 BAMs whose filenames contain ""analysis_ready or validated and do not contain abnormal. "
                "Manta and local breakpoint-depth calculations use these full BAMs."
            ),
        },
        {
            "PARAMETER": "local_depth_window_bp",
            "VALUE": int(cfg["local_depth_window_bp"]),
            "EXPLANATION": (
                "Local depth is summarized within +/- this many bases around each "
                "breakend using the complete Step 03 BAM."
            ),
        },
        {
            "PARAMETER": "local_depth_minimum_mapping_quality",
            "VALUE": int(cfg["local_depth_minimum_mapping_quality"]),
            "EXPLANATION": (
                "Reads below this MAPQ are excluded from local breakpoint-depth evidence."
            ),
        },
        {
            "PARAMETER": "run_manta",
            "VALUE": bool(cfg["run_manta"]),
            "EXPLANATION": (
                "When enabled, Manta independently calls structural variants from "
                "the complete analysis-ready BAM."
            ),
        },
        {
            "PARAMETER": "run_gridss2",
            "VALUE": bool(cfg.get("run_gridss2", True)),
            "EXPLANATION": (
                "GRIDSS2 performs genome-wide breakend assembly plus "
                "split-read/read-pair breakpoint calling from the complete BAM."
            ),
        },
        {
            "PARAMETER": "run_delly",
            "VALUE": bool(cfg.get("run_delly", True)),
            "EXPLANATION": (
                "DELLY short-read SV discovery is run with the current "
                "'delly sr' command and normalized from BCF to the common breakpoint table."
            ),
        },
        {
            "PARAMETER": "run_svaba",
            "VALUE": bool(cfg.get("run_svaba", True)),
            "EXPLANATION": (
                "SvABA performs genome-wide local assembly from the "
                "complete BAM and its SV VCF is normalized to the common breakpoint table."
            ),
        },
        {
            "PARAMETER": "spades_kmer_mode",
            "VALUE": str(cfg.get("spades_kmer_mode", "automatic")),
            "EXPLANATION": (
                "automatic omits SPAdes -k so SPAdes selects k-mers; manual passes "
                "the editable spades_kmers list."
            ),
        },
        {
            "PARAMETER": "spades_kmers",
            "VALUE": str(cfg["spades_kmers"]),
            "EXPLANATION": (
                "Manual-only comma-separated odd k-mer sizes. The GUI can analyze "
                "the Step 05 abnormal FASTQ read-length distribution, propose values "
                "from the maximum-read-length table, and leave the field editable."
            ),
        },
        {
            "PARAMETER": "minimum_contig_length",
            "VALUE": int(cfg["minimum_contig_length"]),
            "EXPLANATION": (
                "SPAdes contigs shorter than this many bases are discarded before "
                "reference alignment and breakpoint interpretation."
            ),
        },
        {
            "PARAMETER": "minimum_contig_alignment_length",
            "VALUE": int(cfg["minimum_contig_alignment_length"]),
            "EXPLANATION": (
                "Each minimap2 PAF alignment used to interpret an assembled contig "
                "must contain at least this many aligned bases."
            ),
        },
        {
            "PARAMETER": "minimum_reference_separation_bp",
            "VALUE": int(cfg["minimum_reference_separation_bp"]),
            "EXPLANATION": (
                "For two successive contig alignments on the same chromosome and "
                "strand, their reference locations must be separated by more than "
                "this distance to be treated as a candidate breakpoint. Different "
                "chromosomes or strands are considered separated regardless of distance."
            ),
        },
        {
            "PARAMETER": "manta_targeted_mode",
            "VALUE": bool(cfg["manta_targeted_mode"]),
            "EXPLANATION": (
                "Adds Manta --exome. Enable for exome/targeted sequencing so Manta "
                "uses non-WGS depth-filtering behavior. This does not itself restrict "
                "calling to target coordinates."
            ),
        },
        {
            "PARAMETER": "manta_call_regions_bed",
            "VALUE": str(cfg["manta_call_regions_bed"]),
            "EXPLANATION": (
                "Optional Manta --callRegions file. Manta requires this BED to be "
                "bgzip-compressed and tabix-indexed. Leave empty for genome-wide calling."
            ),
        },
    ]



def validate_breakpoint_settings(settings: dict, dry_run: bool) -> None:
    cfg = settings["breakpoints"]

    # Validate the fixed, visible Linux work directory early.
    resolve_spades_linux_work_root(settings)

    reference_text = str(settings["references"]["fasta"]).strip()
    if not reference_text:
        raise ValueError(
            "Step 06 requires a reference FASTA. Select the same reference FASTA "
            "used for Step 03 mapping."
        )

    if not dry_run:
        reference = normalized_input_path(reference_text)
        if not reference.exists() or not reference.is_file():
            raise FileNotFoundError(
                f"Step 06 reference FASTA was not found: {reference}"
            )
        if reference.stat().st_size == 0:
            raise ValueError(
                f"Step 06 reference FASTA is empty: {reference}"
            )

    # Canonical selection is optional. If empty, Step 06 writes one unsplit
    # candidate_breakpoints.tsv file. If non-empty, outputs are split into
    # candidate_breakpoints_Canonical.tsv and candidate_breakpoints_NonCanonical.tsv.
    canonical_chromosomes = parse_reference_name_list(
        cfg.get("canonical_chromosomes", "")
    )

    kmer_mode = str(cfg.get("spades_kmer_mode", "automatic")).strip().lower()
    if kmer_mode not in {"automatic", "manual"}:
        raise ValueError("SPAdes k-mer mode must be 'automatic' or 'manual'.")

    kmers = []
    if kmer_mode == "manual":
        for token in str(cfg["spades_kmers"]).split(","):
            token = token.strip()
            if not token:
                continue
            try:
                value = int(token)
            except ValueError as exc:
                raise ValueError(
                    "SPAdes k-mers must be comma-separated integers, e.g. 21,33,55."
                ) from exc
            if value < 3 or value >= 128 or value % 2 == 0:
                raise ValueError(
                    f"SPAdes k-mer {value} is invalid here; use odd k-mers from 3 through 127."
                )
            kmers.append(value)
        if not kmers and bool(cfg["run_spades_assembly"]):
            raise ValueError(
                "Manual SPAdes k-mer mode requires at least one k-mer. Use the "
                "read-length analysis button or enter values such as 21,33,55."
            )

    if int(cfg["minimum_contig_length"]) < 1:
        raise ValueError("Minimum contig length must be at least 1 bp.")
    if int(cfg["minimum_contig_alignment_length"]) < 1:
        raise ValueError("Minimum contig alignment length must be at least 1 bp.")
    if int(cfg["minimum_reference_separation_bp"]) < 0:
        raise ValueError("Minimum reference separation cannot be negative.")
    if int(cfg["local_depth_window_bp"]) < 0:
        raise ValueError("Local breakpoint depth radius cannot be negative.")
    if int(cfg["local_depth_minimum_mapping_quality"]) < 0:
        raise ValueError("Local depth minimum MAPQ cannot be negative.")

    bam_caller_flags = {
        "Manta": bool(cfg.get("run_manta", False)),
        "GRIDSS2": bool(cfg.get("run_gridss2", True)),
        "DELLY": bool(cfg.get("run_delly", True)),
        "SvABA": bool(cfg.get("run_svaba", True)),
    }
    any_bam_caller = any(bam_caller_flags.values())
    classic_bwa_index_text = str(cfg.get("classic_bwa_index_file", "")).strip()
    if (bool(cfg.get("run_gridss2", True)) or bool(cfg.get("run_svaba", True))) and not classic_bwa_index_text:
        raise ValueError(
            "GRIDSS2 and/or SvABA is enabled. Select a classic BWA index component "
            "(.amb/.ann/.bwt/.pac/.sa) using the GUI browse box or CLI option "
            "--breakpoints-classic-bwa-index-file."
        )
    if classic_bwa_index_text and not any(
        classic_bwa_index_text.lower().endswith(suffix)
        for suffix in CLASSIC_BWA_INDEX_SUFFIXES
    ):
        raise ValueError(
            "Classic BWA index file must end in one of: "
            + ", ".join(CLASSIC_BWA_INDEX_SUFFIXES)
        )

    full_bam_folder = str(cfg["analysis_ready_bam_folder"]).strip()
    if any_bam_caller and not full_bam_folder:
        enabled = ", ".join(name for name, flag in bam_caller_flags.items() if flag)
        raise ValueError(
            f"{enabled} is/are enabled, so Step 06 requires an explicitly selected "
            "folder containing the COMPLETE Step 03 analysis-ready/validated BAM files."
        )

    tool_requirements = [
        ("Manta config", "manta_config", bam_caller_flags["Manta"]),
        ("Manta runner", "manta_run", bam_caller_flags["Manta"]),
        ("GRIDSS2", "gridss", bam_caller_flags["GRIDSS2"]),
        ("DELLY", "delly", bam_caller_flags["DELLY"]),
        ("SvABA", "svaba", bam_caller_flags["SvABA"]),
    ]
    for label, key, enabled in tool_requirements:
        if enabled and not str(settings["tools"].get(key, "")).strip():
            raise ValueError(
                f"{label} is enabled but tools.{key} is blank."
            )

    if full_bam_folder and not dry_run:
        validate_full_bam_folder_for_manta(full_bam_folder)

    call_regions = str(cfg["manta_call_regions_bed"]).strip()
    if call_regions and not dry_run:
        path = normalized_input_path(call_regions)
        if not path.exists():
            raise FileNotFoundError(f"Manta call-regions BED was not found: {path}")
        if not str(path).lower().endswith(".gz"):
            raise ValueError(
                "Manta --callRegions requires a bgzip-compressed BED (.bed.gz), "
                "not a plain BED file."
            )
        tbi = Path(str(path) + ".tbi")
        csi = Path(str(path) + ".csi")
        if not tbi.exists() and not csi.exists():
            raise FileNotFoundError(
                f"Manta call-regions BED requires a tabix index (.tbi or .csi): {path}"
            )

def inspect_fastq_file(path_value: object) -> dict[str, object]:
    """
    Stream one FASTQ/FASTQ.GZ file and validate its structure.

    Returns read count plus min/max read length. The function uses constant
    memory and is intentionally strict because malformed/empty FASTQ inputs
    otherwise make SPAdes fail with a generic non-zero exit code.
    """
    text = str(path_value or "").strip()
    if not text or text.lower() == "nan":
        return {
            "PATH": "",
            "EXISTS": False,
            "READ_COUNT": 0,
            "MIN_READ_LENGTH": 0,
            "MAX_READ_LENGTH": 0,
            "VALID_FASTQ": False,
            "STATUS": "NOT_PROVIDED",
        }

    path = normalized_input_path(text)
    if not path.exists() or not path.is_file():
        return {
            "PATH": str(path),
            "EXISTS": False,
            "READ_COUNT": 0,
            "MIN_READ_LENGTH": 0,
            "MAX_READ_LENGTH": 0,
            "VALID_FASTQ": False,
            "STATUS": "MISSING",
        }

    read_count = 0
    minimum_length = None
    maximum_length = 0
    storage = "UNKNOWN"
    storage_detail = ""

    try:
        handle, storage, storage_detail = _open_fastq_text_by_content(path)
        with handle:
            while True:
                header = handle.readline()
                if not header:
                    break
                sequence = handle.readline()
                plus = handle.readline()
                quality = handle.readline()

                if not sequence or not plus or not quality:
                    return {
                        "PATH": str(path),
                        "EXISTS": True,
                        "READ_COUNT": read_count,
                        "MIN_READ_LENGTH": minimum_length or 0,
                        "MAX_READ_LENGTH": maximum_length,
                        "VALID_FASTQ": False,
                        "STATUS": "TRUNCATED_FASTQ_RECORD",
                    }

                header = header.rstrip("\r\n")
                sequence = sequence.rstrip("\r\n")
                plus = plus.rstrip("\r\n")
                quality = quality.rstrip("\r\n")

                if not header.startswith("@"):
                    return {
                        "PATH": str(path),
                        "EXISTS": True,
                        "READ_COUNT": read_count,
                        "MIN_READ_LENGTH": minimum_length or 0,
                        "MAX_READ_LENGTH": maximum_length,
                        "VALID_FASTQ": False,
                        "STATUS": "INVALID_HEADER",
                    }
                if not plus.startswith("+"):
                    return {
                        "PATH": str(path),
                        "EXISTS": True,
                        "READ_COUNT": read_count,
                        "MIN_READ_LENGTH": minimum_length or 0,
                        "MAX_READ_LENGTH": maximum_length,
                        "VALID_FASTQ": False,
                        "STATUS": "INVALID_PLUS_LINE",
                    }
                if len(sequence) != len(quality):
                    return {
                        "PATH": str(path),
                        "EXISTS": True,
                        "READ_COUNT": read_count,
                        "MIN_READ_LENGTH": minimum_length or 0,
                        "MAX_READ_LENGTH": maximum_length,
                        "VALID_FASTQ": False,
                        "STATUS": "SEQUENCE_QUALITY_LENGTH_MISMATCH",
                    }

                length = len(sequence)
                read_count += 1
                maximum_length = max(maximum_length, length)
                minimum_length = (
                    length if minimum_length is None else min(minimum_length, length)
                )
    except (OSError, EOFError, UnicodeError, ValueError) as exc:
        return {
            "PATH": str(path),
            "EXISTS": True,
            "READ_COUNT": read_count,
            "MIN_READ_LENGTH": minimum_length or 0,
            "MAX_READ_LENGTH": maximum_length,
            "VALID_FASTQ": False,
            "STORAGE_FORMAT": storage,
            "STORAGE_DETAIL": storage_detail,
            "STATUS": f"READ_ERROR: {exc}",
        }

    return {
        "PATH": str(path),
        "EXISTS": True,
        "READ_COUNT": read_count,
        "MIN_READ_LENGTH": minimum_length or 0,
        "MAX_READ_LENGTH": maximum_length,
        "VALID_FASTQ": True,
        "STORAGE_FORMAT": storage,
        "STORAGE_DETAIL": storage_detail,
        "STATUS": "OK" if read_count else "EMPTY",
    }


def effective_spades_kmers(configured: str, maximum_read_length: int) -> list[int]:
    """
    Keep configured SPAdes k-mers that are usable for the observed read length.

    SPAdes requires odd k values <128 and in ascending order. In addition, a
    de Bruijn k-mer cannot be longer than the reads supplying it. This function
    prevents a configured large k from causing a run-time failure after trimming.
    """
    requested = sorted(
        {
            int(token.strip())
            for token in str(configured).split(",")
            if token.strip()
        }
    )

    valid = [
        value
        for value in requested
        if value >= 3
        and value < 128
        and value % 2 == 1
        and value <= int(maximum_read_length)
    ]

    if valid:
        return valid

    # Very short reads are not useful for this assembly stage.
    if maximum_read_length < 3:
        return []

    fallback = min(21, int(maximum_read_length))
    if fallback % 2 == 0:
        fallback -= 1
    while fallback >= 3 and fallback > maximum_read_length:
        fallback -= 2

    return [fallback] if fallback >= 3 else []


def tail_text_file(path: Path, maximum_lines: int = 40) -> str:
    """Return the last few lines of a text log without loading huge files."""
    if not path.exists():
        return ""
    from collections import deque
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return "".join(deque(handle, maxlen=maximum_lines)).strip()



def _spades_preflight_from_fastq_results(
    *,
    r1: dict[str, object],
    r2: dict[str, object],
    singles: dict[str, object],
    sample_id: str,
    cfg: dict,
    source_type: str = "FASTQ_DIRECT",
) -> dict[str, object]:
    r1_count = int(r1["READ_COUNT"])
    r2_count = int(r2["READ_COUNT"])
    singleton_count = int(singles["READ_COUNT"])
    maximum_read_length = max(
        int(r1["MAX_READ_LENGTH"]),
        int(r2["MAX_READ_LENGTH"]),
        int(singles["MAX_READ_LENGTH"]),
    )
    kmer_mode = str(cfg.get("spades_kmer_mode", "automatic")).strip().lower()
    kmers = (
        effective_spades_kmers(str(cfg["spades_kmers"]), maximum_read_length)
        if kmer_mode == "manual"
        else []
    )

    common = {
        "R1": r1,
        "R2": r2,
        "SINGLETON": singles,
        "KMERS": kmers,
        "MAX_READ_LENGTH": maximum_read_length,
        "SOURCE_TYPE": source_type,
    }

    if r1_count == 0 and r2_count == 0 and singleton_count == 0:
        return {"MODE": "NO_READS", **common}

    if r1_count > 0 or r2_count > 0:
        if r1_count == 0 or r2_count == 0:
            raise ValueError(
                f"Step 05 paired abnormal FASTQ input is incomplete for {sample_id}: "
                f"R1={r1_count:,}, R2={r2_count:,}."
            )
        if r1_count != r2_count:
            raise ValueError(
                f"Step 05 abnormal FASTQ pairing count mismatch for {sample_id}: "
                f"R1={r1_count:,}, R2={r2_count:,}."
            )
        if kmer_mode == "manual" and not kmers:
            raise ValueError(
                f"No usable manual SPAdes k-mer remains for {sample_id}; maximum read "
                f"length is {maximum_read_length} bp."
            )
        return {"MODE": "PAIRED_WITH_OPTIONAL_SINGLETONS", **common}

    if singleton_count > 0:
        if kmer_mode == "manual" and not kmers:
            raise ValueError(
                f"No usable manual SPAdes k-mer remains for singleton reads in {sample_id}; "
                f"maximum read length is {maximum_read_length} bp."
            )
        return {"MODE": "SINGLE_READ_LIBRARY", **common}

    return {"MODE": "NO_READS", **common}


def prepare_spades_inputs(
    row: dict,
    sample_id: str,
    cfg: dict,
    output_dir: Path,
    settings: dict,
    log_file: Path,
    dry_run: bool,
) -> dict[str, object]:
    """Validate and prepare only Step 05 abnormal FASTQ/FQ files for SPAdes."""
    # This function can write warnings directly to the per-sample log, so
    # ensure the parent exists even when called independently.
    log_file.parent.mkdir(parents=True, exist_ok=True)

    r1 = inspect_fastq_file(row.get("ABNORMAL_R1_FASTQ", ""))
    r2 = inspect_fastq_file(row.get("ABNORMAL_R2_FASTQ", ""))
    singles = inspect_fastq_file(row.get("ABNORMAL_SINGLETON_FASTQ", ""))

    report_rows = []
    for label, result in [("R1", r1), ("R2", r2), ("SINGLETON", singles)]:
        report_rows.append({"SAMPLE_ID": sample_id, "FASTQ_ROLE": label, **result})
    write_tsv(pd.DataFrame(report_rows), output_dir / f"{sample_id}.spades_fastq_preflight.tsv")

    invalid_pairs = [
        (label, result)
        for label, result in [("R1", r1), ("R2", r2)]
        if result["STATUS"] not in {"NOT_PROVIDED", "EMPTY"}
        and (not bool(result["EXISTS"]) or not bool(result["VALID_FASTQ"]))
    ]
    if invalid_pairs:
        details = "; ".join(f"{label}:{result['STATUS']}" for label, result in invalid_pairs)
        raise ValueError(
            f"Abnormal paired FASTQ input for {sample_id} is unusable: {details}. "
            "BAM fallback is disabled; Step 06 SPAdes accepts only valid abnormal FASTQ/FQ files."
        )

    r1_count = int(r1["READ_COUNT"])
    r2_count = int(r2["READ_COUNT"])

    singleton_invalid = (
        singles["STATUS"] not in {"NOT_PROVIDED", "EMPTY"}
        and (not bool(singles["EXISTS"]) or not bool(singles["VALID_FASTQ"]))
    )
    if singleton_invalid:
        if r1_count > 0 and r2_count > 0:
            # A malformed optional singleton file must not block a valid paired-end
            # SPAdes assembly.  Ignore it explicitly and record why.  This is
            # particularly important for legacy Step 05 outputs where -0 and -s
            # were accidentally directed to the same gzip filename.
            bad_path = str(singles.get("PATH", ""))
            bad_status = str(singles.get("STATUS", ""))
            with log_file.open("a", encoding="utf-8") as handle:
                handle.write(
                    "\nSPADES WARNING: ignoring invalid optional singleton FASTQ: "
                    f"{bad_path} ; {bad_status}\n"
                )
            singles = {
                "PATH": "",
                "EXISTS": False,
                "READ_COUNT": 0,
                "MIN_READ_LENGTH": 0,
                "MAX_READ_LENGTH": 0,
                "VALID_FASTQ": False,
                "STORAGE_FORMAT": "IGNORED",
                "STORAGE_DETAIL": bad_status,
                "STATUS": "IGNORED_INVALID_OPTIONAL_SINGLETON",
            }
        else:
            raise ValueError(
                f"The only abnormal single-read FASTQ for {sample_id} is unusable: "
                f"{singles.get('PATH','')} ; {singles.get('STATUS','')}. "
                "No valid paired R1/R2 files are available, so SPAdes cannot continue."
            )

    singleton_count = int(singles["READ_COUNT"])
    if r1_count == 0 and r2_count == 0 and singleton_count == 0:
        raise ValueError(
            f"No reads were found in the abnormal FASTQ/FQ inputs for {sample_id}. "
            "BAM fallback is disabled."
        )

    return _spades_preflight_from_fastq_results(
        r1=r1,
        r2=r2,
        singles=singles,
        sample_id=sample_id,
        cfg=cfg,
        source_type="FASTQ_DIRECT",
    )

def resolve_spades_linux_work_root(settings: dict) -> Path:
    """
    Return the one fixed native-Linux Step 06 SPAdes working directory.

    The path is intentionally NOT configurable:
        $HOME/ctdna_step06_spades_work

    This avoids all Windows/WSL path-conversion and tilde-expansion ambiguity,
    while keeping every temporary SPAdes file in one known location.
    """
    home = Path.home().resolve()
    path = (home / "ctdna_step06_spades_work").resolve()

    # Defensive invariant; this should never fail because path is constructed
    # directly from Path.home().
    if path.parent != home:
        raise RuntimeError(
            "Internal Step 06 safety error: fixed SPAdes work directory is not "
            "directly below Linux HOME."
        )

    return path
def initialize_spades_known_work_root(settings: dict) -> Path:
    """
    Delete stale SPAdes work AS EARLY AS POSSIBLE and return the known root path.

    The root is intentionally NOT recreated here. It is created only when a
    sample actually needs SPAdes, so an empty temporary folder is not left
    behind unnecessarily.
    """
    root = resolve_spades_linux_work_root(settings)

    if root.exists():
        shutil.rmtree(root)

    return root

def prepare_spades_known_workspace(
    work_root: Path,
    sample_id: str,
) -> tuple[Path, Path]:
    """
    Prepare one deterministic per-sample workspace.

    Example:
        /home/dash/ctdna_step06_spades_work/Sample1/spades_assembly
    """
    work_root.mkdir(parents=True, exist_ok=True)

    readme = work_root / "README_STEP06_WORK_DIRECTORY.txt"
    if not readme.exists():
        readme.write_text(
            "Temporary working directory used by ctDNA pipeline Step 06 SPAdes.\n"
            "If this directory is present while Step 06 is not running, it is "
            "stale and can be deleted. Step 06 auto-cleans it at startup.\n",
            encoding="utf-8",
        )

    safe_sample = re.sub(
        r"[^A-Za-z0-9_.-]+",
        "_",
        str(sample_id),
    ).strip("._") or "sample"

    sample_workspace = work_root / safe_sample

    if sample_workspace.exists():
        shutil.rmtree(sample_workspace)

    sample_workspace.mkdir(parents=True, exist_ok=True)
    return sample_workspace, sample_workspace / "spades_assembly"

def cleanup_spades_sample_workspace(sample_workspace: Path | None) -> None:
    """Remove a sample's native-Linux SPAdes working directory."""
    if sample_workspace is not None and sample_workspace.exists():
        shutil.rmtree(sample_workspace, ignore_errors=True)


def cleanup_spades_known_work_root(work_root: Path | None) -> None:
    """
    Remove the known Step 06 work root after normal pipeline completion.

    If the program is forcibly killed, this code cannot run at that exact moment.
    The next Step 06 startup calls initialize_spades_known_work_root(), which
    removes the entire stale root before new work starts.
    """
    if work_root is not None and work_root.exists():
        shutil.rmtree(work_root, ignore_errors=True)


def copy_spades_results_back(
    linux_spades_output: Path,
    durable_output: Path,
) -> list[Path]:
    """
    Copy only durable SPAdes results back to the Windows-visible Step 06 folder.

    The entire internal K*/configs working tree is deliberately NOT copied.
    """
    durable_output.mkdir(parents=True, exist_ok=True)

    names = [
        "contigs.fasta",
        "scaffolds.fasta",
        "assembly_graph.fastg",
        "assembly_graph_with_scaffolds.gfa",
        "contigs.paths",
        "scaffolds.paths",
        "spades.log",
        "params.txt",
        "input_dataset.yaml",
        "dataset.info",
    ]

    copied: list[Path] = []
    for name in names:
        source = linux_spades_output / name
        if not source.exists() or not source.is_file():
            continue
        destination = durable_output / name
        shutil.copy2(source, destination)
        copied.append(destination)

    return copied


def save_spades_workspace_report(
    sample_dir: Path,
    sample_id: str,
    linux_workspace: Path,
    durable_output: Path,
    copied: list[Path],
    status: str,
) -> Path:
    report = sample_dir / f"{sample_id}.spades_workspace.tsv"
    write_tsv(
        pd.DataFrame(
            [{
                "SAMPLE_ID": sample_id,
                "STATUS": status,
                "SPADES_NATIVE_LINUX_WORKSPACE": str(linux_workspace),
                "SPADES_WORK_ROOT": str(linux_workspace.parent),
                "SPADES_DURABLE_OUTPUT": str(durable_output),
                "COPIED_FILES": ";".join(str(path) for path in copied),
                "WORKSPACE_REMOVED_AFTER_RUN": True,
                "RATIONALE": (
                    "SPAdes internal K*/configs trees are run in one fixed, "
                    "visible native-Linux Step 06 work root to avoid WSL1 /mnt/c "
                    "permission failures. No random temporary names are used."
                ),
            }]
        ),
        report,
    )
    return report


def backend(settings_path: Path, input_dir: Path, output_dir: Path, dry_run: bool) -> None:
    settings, _ = load_config(settings_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Remove mutually exclusive/legacy breakpoint tables from an earlier run in
    # the same output folder so the user never sees stale duplicate files.
    for stale_name in [
        "candidate_breakpoints.tsv",
        "candidate_breakpoints_Canonical.tsv",
        "candidate_breakpoints_NonCanonical.tsv",
        "candidate_breakpoints_CANONICAL.tsv",
        "candidate_breakpoints_NONCANONICAL.tsv",
        "candidate_breakpoints_ALL.tsv",
        "candidate_breakpoints_ranked.tsv",
        "candidate_breakpoints_ALL_ranked.tsv",
        "reference_sequence_classification.tsv",
    ]:
        stale_path = output_dir / stale_name
        if stale_path.exists() and stale_path.is_file():
            stale_path.unlink()

    # Create the per-tool/per-sample log directory before any code path can
    # open output/logs/*.log directly. Some SPAdes preflight warning paths
    # write to the sample log before run_command() gets a chance to create
    # its parent directory.
    logs_dir = output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(output_dir / "06_ASSEMBLE_AND_CALL_CHROMOSOME_BREAKPOINTS.log")

    cfg = settings["breakpoints"]
    validate_breakpoint_settings(settings, dry_run)

    # Delete abandoned SPAdes files immediately after settings validation,
    # before tool checks, FASTA indexing, or input discovery.
    write_tsv(
        pd.DataFrame(breakpoint_parameter_rows(settings)),
        output_dir / "breakpoint_parameters_used.tsv",
    )

    required_tools = ["samtools"]
    if bool(cfg["run_spades_assembly"]):
        required_tools.extend(["spades", "minimap2"])
    if bool(cfg["run_manta"]):
        required_tools.extend(["manta_config", "manta_run"])
    if bool(cfg.get("run_gridss2", True)):
        required_tools.append("gridss")
    if bool(cfg.get("run_delly", True)):
        required_tools.extend(["delly", "bcftools"])
    if bool(cfg.get("run_svaba", True)):
        required_tools.append("svaba")
    require_tools(settings, required_tools, dry_run)

    spades_work_root: Path | None = None
    if bool(cfg["run_spades_assembly"]) and not dry_run:
        spades_work_root = initialize_spades_known_work_root(settings)

    reference = normalized_input_path(settings["references"]["fasta"])
    reference_fai = validate_or_create_reference_fai(
        reference,
        settings["references"].get("fasta_fai", ""),
        settings,
        output_dir / "logs" / "reference_fasta_index.log",
        dry_run,
    )

    canonical_chromosomes = parse_reference_name_list(
        cfg.get("canonical_chromosomes", "")
    )
    reference_names = reference_names_from_fasta(reference) if not dry_run else []
    if reference_names and canonical_chromosomes:
        reference_name_set = set(reference_names)
        unknown_canonical = [
            name for name in canonical_chromosomes if name not in reference_name_set
        ]
        if unknown_canonical:
            raise ValueError(
                "The canonical chromosome selection contains name(s) that are not "
                "present in the selected reference FASTA: "
                + ", ".join(unknown_canonical)
                + ". Re-scan the reference FASTA and apply the canonical selection again."
            )

        canonical_set = set(canonical_chromosomes)
        reference_classification = pd.DataFrame(
            [
                {
                    "REFERENCE_SEQUENCE": name,
                    "REFERENCE_CLASS": (
                        "CANONICAL" if name in canonical_set else "NON_CANONICAL"
                    ),
                    "SELECTED_AS_CANONICAL": (
                        "YES" if name in canonical_set else "NO"
                    ),
                }
                for name in reference_names
            ]
        )
        write_tsv(
            reference_classification,
            output_dir / "reference_sequence_classification.tsv",
        )

    classic_bwa_index_info: dict[str, object] = {}
    classic_bwa_needed = bool(cfg.get("run_gridss2", True)) or bool(cfg.get("run_svaba", True))
    if classic_bwa_needed:
        selected_bwa_index_text = str(cfg.get("classic_bwa_index_file", "")).strip()
        if not selected_bwa_index_text:
            raise ValueError(
                "GRIDSS2 and/or SvABA is enabled, so select one classic BWA index file "
                "(.amb/.ann/.bwt/.pac/.sa) in the GUI. Step 06 will verify the complete "
                "index set and will not build it automatically."
            )
        if not dry_run:
            classic_bwa_index_info = validate_classic_bwa_reference_indexes(
                reference,
                normalized_input_path(selected_bwa_index_text),
            )

    if bool(cfg.get("run_gridss2", True)) and not dry_run:
        if not executable_exists("bwa"):
            raise FileNotFoundError(
                "GRIDSS2 is enabled but classic 'bwa' was not found on PATH. "
                "BWA-MEM2 is not a drop-in replacement for GRIDSS2's documented "
                "classic BWA soft-clip realignment requirement."
            )

    abnormal_folder_validation = validate_step05_abnormal_folder(
        str(input_dir),
        require_spades_source=bool(cfg["run_spades_assembly"]),
    )

    # discover_abnormal_inputs is intentionally run ONLY on the second Step 06
    # box (Step 05 abnormal evidence folder).
    inputs = discover_abnormal_inputs(input_dir)
    if inputs.empty:
        raise FileNotFoundError(
            "No accepted Step 05 abnormal FASTQ/FQ inputs were found in the selected "
            "abnormal-evidence folder. BAM is not accepted by the SPAdes branch."
        )

    # Hard-filter discovered paths so only filenames containing 'abnormal' can
    # enter the Step 05/SPAdes branch.
    for column in [
        "ABNORMAL_R1_FASTQ",
        "ABNORMAL_R2_FASTQ",
        "ABNORMAL_SINGLETON_FASTQ",
    ]:
        if column not in inputs.columns:
            continue
        inputs[column] = inputs[column].apply(
            lambda value: (
                value
                if (
                    str(value or "").strip()
                    and str(value or "").lower() != "nan"
                    and "abnormal" in Path(str(value)).name.lower()
                )
                else ""
            )
        )

    # Drop any row that no longer contains accepted abnormal evidence.
    evidence_columns = [
        column
        for column in [
            "ABNORMAL_R1_FASTQ",
            "ABNORMAL_R2_FASTQ",
            "ABNORMAL_SINGLETON_FASTQ",
        ]
        if column in inputs.columns
    ]
    if evidence_columns:
        keep_mask = inputs[evidence_columns].apply(
            lambda row: any(str(value or "").strip() for value in row),
            axis=1,
        )
        inputs = inputs.loc[keep_mask].copy()

    if inputs.empty:
        raise FileNotFoundError(
            "Step 05 folder was scanned, but no filename containing 'abnormal' "
            "was accepted for Step 06."
        )

    step03_bam_table = discover_step03_analysis_ready_bams(
        str(cfg["analysis_ready_bam_folder"])
    )
    step03_bam_by_sample = map_step03_bams_by_sample(step03_bam_table)

    write_tsv(
        step03_bam_table,
        output_dir / "step03_validated_full_bams_scanned.tsv",
    )

    write_tsv(
        pd.DataFrame(
            [
                {
                    "INPUT_CLASS": "STEP05_ABNORMAL_FASTQ_ONLY",
                    "ACCEPTED_COUNT": len(abnormal_folder_validation["ABNORMAL_FASTQS"]),
                    "FILES": ";".join(
                        str(path) for path in abnormal_folder_validation["ABNORMAL_FASTQS"]
                    ),
                },
                {
                    "INPUT_CLASS": "BAM_REJECTED_FOR_SPADES",
                    "ACCEPTED_COUNT": 0,
                    "REJECTED_COUNT": len(abnormal_folder_validation["REJECTED_BAMS"]),
                    "FILES": ";".join(
                        str(path) for path in abnormal_folder_validation["REJECTED_BAMS"]
                    ),
                },
            ]
        ),
        output_dir / "step05_abnormal_evidence_scanned.tsv",
    )

    any_full_bam_caller = any(
        bool(cfg.get(key, False))
        for key in ("run_manta", "run_gridss2", "run_delly", "run_svaba")
    )
    enabled_full_bam_callers = [
        label
        for key, label in [
            ("run_manta", "Manta"),
            ("run_gridss2", "GRIDSS2"),
            ("run_delly", "DELLY"),
            ("run_svaba", "SvABA"),
        ]
        if bool(cfg.get(key, False))
    ]
    if any_full_bam_caller and step03_bam_table.empty:
        raise FileNotFoundError(
            "BAM-based structural-variant caller(s) are enabled ("
            + ", ".join(enabled_full_bam_callers)
            + "), but no analysis-ready/validated BAM files were found in the "
            "selected Step 03 BAM folder."
        )

    input_sample_ids = [
        str(value).strip()
        for value in inputs["SAMPLE_ID"].tolist()
    ]
    missing_step03 = [
        sample_id
        for sample_id in input_sample_ids
        if (
            sample_id not in step03_bam_by_sample
            and sample_id.lower() not in step03_bam_by_sample
        )
    ]
    if any_full_bam_caller and missing_step03:
        raise FileNotFoundError(
            "No matching Step 03 analysis-ready BAM was found for these Step 05 "
            "sample(s): "
            + ", ".join(missing_step03)
            + "\nRequired by enabled BAM caller(s): "
            + ", ".join(enabled_full_bam_callers)
            + "\nExpected examples: Sample1.analysis_ready.bam or Sample1.validated.bam"
        )

    output_rows: list[dict] = []
    breakpoint_tables: list[pd.DataFrame] = []
    contig_metrics: list[pd.DataFrame] = []
    algorithm_validation_rows: list[dict[str, object]] = []

    for row in inputs.to_dict(orient="records"):
        sample_id = row["SAMPLE_ID"]
        has_abnormal_fastq = bool(
            row.get("ABNORMAL_R1_FASTQ")
            or row.get("ABNORMAL_R2_FASTQ")
            or row.get("ABNORMAL_SINGLETON_FASTQ")
        )
        has_abnormal_spades_source = has_abnormal_fastq
        step03_full_bam = (
            step03_bam_by_sample.get(sample_id)
            or step03_bam_by_sample.get(sample_id.lower())
        )

        if step03_full_bam is not None:
            validate_manta_analysis_ready_bam(
                step03_full_bam,
                sample_id,
            )

        run_spades_for_sample = bool(cfg["run_spades_assembly"]) and has_abnormal_spades_source
        run_manta_for_sample = bool(cfg["run_manta"]) and step03_full_bam is not None
        run_gridss2_for_sample = bool(cfg.get("run_gridss2", True)) and step03_full_bam is not None
        run_delly_for_sample = bool(cfg.get("run_delly", True)) and step03_full_bam is not None
        run_svaba_for_sample = bool(cfg.get("run_svaba", True)) and step03_full_bam is not None
        if not any(
            [
                run_spades_for_sample,
                run_manta_for_sample,
                run_gridss2_for_sample,
                run_delly_for_sample,
                run_svaba_for_sample,
            ]
        ):
            continue

        algorithm_validation_rows.extend(
            algorithm_input_validation_rows(
                sample_id=sample_id,
                row=row,
                step03_full_bam=step03_full_bam,
                run_spades_for_sample=run_spades_for_sample,
                run_manta_for_sample=run_manta_for_sample,
                run_gridss2_for_sample=run_gridss2_for_sample,
                run_delly_for_sample=run_delly_for_sample,
                run_svaba_for_sample=run_svaba_for_sample,
            )
        )

        sample_dir = output_dir / sample_id
        sample_dir.mkdir(parents=True, exist_ok=True)
        # Defensive per-sample creation in case this block is reused outside
        # the normal backend initialization path.
        logs_dir = output_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / f"{sample_id}.log"

        filtered_contigs = sample_dir / f"{sample_id}.breakpoint_contigs.fasta"
        paf_path = sample_dir / f"{sample_id}.contig_alignments.paf"
        manta_run = sample_dir / "manta_run"
        manta_vcf = ""
        gridss_run = sample_dir / "gridss2_run"
        gridss_vcf = ""
        delly_run = sample_dir / "delly_run"
        delly_vcf = ""
        svaba_run = sample_dir / "svaba_run"
        svaba_vcf = ""

        spades_input_mode = "NOT_REQUESTED"
        spades_r1_count = 0
        spades_r2_count = 0
        spades_singleton_count = 0
        spades_effective_kmers = ""
        spades_source_type = ""

        if run_spades_for_sample:
            assembly_dir = sample_dir / "spades_assembly"

            # Algorithm-class guard: SPAdes accepts only Step 05 abnormal FASTQ/FQ files.
            # Validate names before expensive FASTQ inspection/assembly.
            for role, key in [
                ("R1", "ABNORMAL_R1_FASTQ"),
                ("R2", "ABNORMAL_R2_FASTQ"),
                ("SINGLETON", "ABNORMAL_SINGLETON_FASTQ"),
            ]:
                value = str(row.get(key, "") or "").strip()
                if value and value.lower() != "nan":
                    validate_spades_abnormal_fastq_path(
                        value,
                        sample_id,
                        role,
                    )


            kmer_mode = str(cfg.get("spades_kmer_mode", "automatic")).strip().lower()
            if dry_run:
                preflight = {
                    "MODE": "DRY_RUN",
                    "SOURCE_TYPE": "FASTQ_DIRECT",
                    "KMERS": (
                        [
                            int(token.strip())
                            for token in str(cfg["spades_kmers"]).split(",")
                            if token.strip()
                        ]
                        if kmer_mode == "manual"
                        else []
                    ),
                    "R1": {"READ_COUNT": 0, "PATH": str(row.get("ABNORMAL_R1_FASTQ", ""))},
                    "R2": {"READ_COUNT": 0, "PATH": str(row.get("ABNORMAL_R2_FASTQ", ""))},
                    "SINGLETON": {
                        "READ_COUNT": 0,
                        "PATH": str(row.get("ABNORMAL_SINGLETON_FASTQ", "")),
                    },
                }
            else:
                preflight = prepare_spades_inputs(
                    row,
                    sample_id,
                    cfg,
                    sample_dir,
                    settings,
                    log_file,
                    dry_run=False,
                )

            spades_input_mode = str(preflight["MODE"])
            spades_r1_count = int(preflight["R1"]["READ_COUNT"])
            spades_r2_count = int(preflight["R2"]["READ_COUNT"])
            spades_singleton_count = int(preflight["SINGLETON"]["READ_COUNT"])
            spades_effective_kmers = (
                ",".join(str(value) for value in preflight["KMERS"])
                if kmer_mode == "manual"
                else "AUTO (SPAdes-selected)"
            )
            spades_source_type = str(preflight.get("SOURCE_TYPE", "FASTQ_DIRECT"))

            if spades_input_mode == "NO_READS":
                # Step 05 can validly produce empty abnormal FASTQs. That means
                # there is nothing for local assembly; it is not a pipeline error.
                run_spades_for_sample = False
                with log_file.open("a", encoding="utf-8") as handle:
                    handle.write(
                        "\nSPADES SKIPPED: Step 05 abnormal FASTQ files contain "
                        "zero reads. Manta may still run independently from the BAM.\n"
                    )
            else:
                # The durable output remains in the ordinary Step 06 folder,
                # but SPAdes MUST NOT use /mnt/c as its own working/output tree
                # under WSL1. SPAdes creates K*/configs directories that can fail
                # on DrvFs/NTFS with Errno 13 Permission denied.
                if not dry_run and assembly_dir.exists():
                    shutil.rmtree(assembly_dir)

                linux_workspace: Path | None = None
                spades_run_output = assembly_dir

                if not dry_run:
                    if spades_work_root is None:
                        raise RuntimeError(
                            "Internal Step 06 error: SPAdes work root was not initialized."
                        )
                    (
                        linux_workspace,
                        spades_run_output,
                    ) = prepare_spades_known_workspace(
                        spades_work_root,
                        sample_id,
                    )

                command_parts = [
                    quote(settings["tools"]["spades"]),
                    "--only-assembler",
                    "-t", str(threads(settings)),
                ]
                if kmer_mode == "manual":
                    command_parts.extend(["-k", quote(spades_effective_kmers)])
                command_parts.extend(["-o", quote(spades_run_output)])

                if spades_input_mode in {
                    "PAIRED_WITH_OPTIONAL_SINGLETONS",
                    "DRY_RUN",
                }:
                    r1_path = str(preflight["R1"]["PATH"]).strip()
                    r2_path = str(preflight["R2"]["PATH"]).strip()
                    singleton_path = str(preflight["SINGLETON"]["PATH"]).strip()

                    if r1_path and r2_path:
                        command_parts.extend([
                            "--pe1-1", quote(r1_path),
                            "--pe1-2", quote(r2_path),
                        ])
                    if singleton_path and (
                        dry_run or spades_singleton_count > 0
                    ):
                        command_parts.extend([
                            "--pe1-s",
                            quote(singleton_path),
                        ])

                elif spades_input_mode == "SINGLE_READ_LIBRARY":
                    command_parts.extend([
                        "--s1",
                        quote(preflight["SINGLETON"]["PATH"]),
                    ])

                copied_spades_files: list[Path] = []

                try:
                    run_command(
                        " ".join(command_parts),
                        log_file,
                        dry_run=dry_run,
                        shell=True,
                    )

                    if not dry_run:
                        copied_spades_files = copy_spades_results_back(
                            spades_run_output,
                            assembly_dir,
                        )
                        save_spades_workspace_report(
                            sample_dir,
                            sample_id,
                            linux_workspace,
                            assembly_dir,
                            copied_spades_files,
                            "SUCCESS",
                        )

                except RuntimeError as exc:
                    # SPAdes' own log lives inside its native-Linux output.
                    internal_log = spades_run_output / "spades.log"
                    internal_tail = (
                        tail_text_file(internal_log, maximum_lines=60)
                        if not dry_run
                        else ""
                    )
                    wrapper_tail = tail_text_file(log_file, maximum_lines=50)

                    if not dry_run:
                        # Preserve useful diagnostic files before deleting scratch.
                        copied_spades_files = copy_spades_results_back(
                            spades_run_output,
                            assembly_dir,
                        )
                        save_spades_workspace_report(
                            sample_dir,
                            sample_id,
                            linux_workspace,
                            assembly_dir,
                            copied_spades_files,
                            "FAILED",
                        )

                    details = internal_tail or wrapper_tail
                    raise RuntimeError(
                        "SPAdes failed during Step 06.\n\n"
                        f"Input mode: {spades_input_mode}\n"
                        f"R1 reads: {spades_r1_count:,}\n"
                        f"R2 reads: {spades_r2_count:,}\n"
                        f"Singleton reads: {spades_singleton_count:,}\n"
                        f"Effective k-mers: {spades_effective_kmers}\n"
                        f"SPAdes native Linux workspace: "
                        f"{linux_workspace if linux_workspace else 'DRY_RUN'}\n"
                        f"Configured SPAdes work root: "
                        f"{resolve_spades_linux_work_root(settings)}\n\n"
                        "Last SPAdes log lines:\n"
                        f"{details}\n\n"
                        f"Original error: {exc}"
                    ) from exc

                finally:
                    if not dry_run:
                        cleanup_spades_sample_workspace(linux_workspace)

                source_contigs = assembly_dir / "contigs.fasta"
                if not dry_run:
                    if not source_contigs.exists() or source_contigs.stat().st_size == 0:
                        # SPAdes can finish without a useful contig for extremely
                        # sparse breakpoint evidence. Treat this as no assembly
                        # evidence rather than trying minimap2 on a missing file.
                        with log_file.open("a", encoding="utf-8") as handle:
                            handle.write(
                                "\nSPADES produced no non-empty contigs.fasta; "
                                "contig-based breakpoint analysis is skipped.\n"
                            )
                    else:
                        filter_fasta(
                            source_contigs,
                            filtered_contigs,
                            int(cfg["minimum_contig_length"]),
                        )

                if dry_run or (
                    filtered_contigs.exists()
                    and filtered_contigs.stat().st_size > 0
                ):
                    minimap_command = (
                        f"{quote(settings['tools']['minimap2'])} -x asm5 -c "
                        f"-t {threads(settings)} {quote(reference)} "
                        f"{quote(filtered_contigs)} > {quote(paf_path)}"
                    )
                    run_command(
                        minimap_command,
                        log_file,
                        dry_run=dry_run,
                        shell=True,
                    )

                    if not dry_run:
                        table = fasta_lengths(filtered_contigs)
                        if not table.empty:
                            table.insert(0, "SAMPLE_ID", sample_id)
                            contig_metrics.append(table)
                        contig_breakpoints = parse_paf_breakpoints(
                            paf_path,
                            sample_id,
                            int(cfg["minimum_contig_alignment_length"]),
                            int(cfg["minimum_reference_separation_bp"]),
                        )
                        if not contig_breakpoints.empty:
                            breakpoint_tables.append(contig_breakpoints)

        step03_bam_readiness: dict[str, str] = {}
        if step03_full_bam is not None and not dry_run:
            step03_bam_readiness = ensure_step03_bam_ready(
                step03_full_bam,
                settings,
                output_dir / "logs" / f"{sample_id}.step03_bam_validation.log",
                dry_run=False,
            )

        if run_manta_for_sample:
            call_regions = str(cfg["manta_call_regions_bed"]).strip()
            region_option = (
                f"--callRegions {quote(normalized_input_path(call_regions))}"
                if is_nonempty(call_regions) else ""
            )
            targeted_option = "--exome" if bool(cfg["manta_targeted_mode"]) else ""
            command = (
                f"{quote(settings['tools']['manta_config'])} "
                f"--tumorBam {quote(step03_full_bam)} "
                f"--referenceFasta {quote(reference)} "
                f"--runDir {quote(manta_run)} {targeted_option} {region_option} && "
                f"{quote(settings['tools']['manta_run'])} {quote(manta_run / 'runWorkflow.py')} -m local "
                f"-j {threads(settings)}"
            )
            run_command(
                command,
                log_file,
                dry_run=dry_run,
                shell=True,
            )
            if not dry_run:
                found = locate_manta_vcf(manta_run)
                if found:
                    manta_vcf = str(found)
                    manta_parse_diagnostics = (
                        sample_dir
                        / f"{sample_id}.manta_vcf_parse_diagnostics.tsv"
                    )
                    table = parse_manta_vcf(
                        found,
                        sample_id,
                        diagnostics_path=manta_parse_diagnostics,
                    )
                    if not table.empty:
                        breakpoint_tables.append(table)


        if run_gridss2_for_sample:
            if not dry_run:
                gridss_run.mkdir(parents=True, exist_ok=True)
            gridss_output_vcf = gridss_run / f"{sample_id}.gridss2.vcf.gz"
            gridss_assembly_bam = gridss_run / f"{sample_id}.gridss2.assembly.bam"
            gridss_working_dir = gridss_run / "working"
            gridss_reference = Path(
                str(classic_bwa_index_info.get("REFERENCE_FOR_BWA_CALLERS", reference))
            )
            gridss_command = [
                str(settings["tools"]["gridss"]),
                "--reference", str(gridss_reference),
                "--output", str(gridss_output_vcf),
                "--assembly", str(gridss_assembly_bam),
                "--threads", str(threads(settings)),
                "--workingdir", str(gridss_working_dir),
                "--labels", str(sample_id),
                str(step03_full_bam),
            ]
            run_command(
                gridss_command,
                log_file,
                dry_run=dry_run,
            )
            if not dry_run and gridss_output_vcf.exists() and gridss_output_vcf.stat().st_size > 0:
                gridss_vcf = str(gridss_output_vcf)
                diagnostics = sample_dir / f"{sample_id}.gridss2_vcf_parse_diagnostics.tsv"
                table = parse_generic_sv_vcf(
                    gridss_output_vcf,
                    sample_id,
                    "GRIDSS2",
                    diagnostics_path=diagnostics,
                    collapse_reciprocal_mates=True,
                )
                if not table.empty:
                    breakpoint_tables.append(table)

        if run_delly_for_sample:
            if not dry_run:
                delly_run.mkdir(parents=True, exist_ok=True)
            delly_bcf = delly_run / f"{sample_id}.delly.bcf"
            delly_output_vcf = delly_run / f"{sample_id}.delly.vcf"
            run_command(
                [
                    str(settings["tools"]["delly"]),
                    "sr",
                    "-g", str(reference),
                    "-o", str(delly_bcf),
                    str(step03_full_bam),
                ],
                log_file,
                dry_run=dry_run,
            )
            run_command(
                [
                    str(settings["tools"]["bcftools"]),
                    "view",
                    "-Ov",
                    "-o", str(delly_output_vcf),
                    str(delly_bcf),
                ],
                log_file,
                dry_run=dry_run,
            )
            if not dry_run and delly_output_vcf.exists() and delly_output_vcf.stat().st_size > 0:
                delly_vcf = str(delly_output_vcf)
                diagnostics = sample_dir / f"{sample_id}.delly_vcf_parse_diagnostics.tsv"
                table = parse_generic_sv_vcf(
                    delly_output_vcf,
                    sample_id,
                    "DELLY",
                    diagnostics_path=diagnostics,
                    collapse_reciprocal_mates=True,
                )
                if not table.empty:
                    breakpoint_tables.append(table)

        if run_svaba_for_sample:
            if not dry_run:
                svaba_run.mkdir(parents=True, exist_ok=True)
            svaba_prefix = re.sub(r"[^A-Za-z0-9._-]+", "_", str(sample_id)).strip("_") or "sample"
            run_command(
                [
                    str(settings["tools"]["svaba"]),
                    "run",
                    "-t", str(step03_full_bam),
                    "-G", str(
                        classic_bwa_index_info.get("REFERENCE_FOR_BWA_CALLERS", reference)
                    ),
                    "-a", svaba_prefix,
                    "-p", str(threads(settings)),
                ],
                log_file,
                dry_run=dry_run,
                cwd=svaba_run,
            )
            if not dry_run:
                found_svaba = locate_svaba_sv_vcf(svaba_run, svaba_prefix)
                if found_svaba is not None:
                    svaba_vcf = str(found_svaba)
                    diagnostics = sample_dir / f"{sample_id}.svaba_vcf_parse_diagnostics.tsv"
                    table = parse_generic_sv_vcf(
                        found_svaba,
                        sample_id,
                        "SVABA",
                        diagnostics_path=diagnostics,
                        collapse_reciprocal_mates=True,
                    )
                    if not table.empty:
                        breakpoint_tables.append(table)

        output_rows.append(
            {
                **row,
                "BREAKPOINT_CONTIGS_FASTA": str(filtered_contigs),
                "CONTIG_ALIGNMENTS_PAF": str(paf_path),
                "FULL_BAM_FOLDER_ROLE": (
                    "MANTA_GRIDSS2_DELLY_SVABA_AND_LOCAL_BREAKPOINT_DEPTH"
                ),
                "ABNORMAL_FOLDER_ROLE": (
                    "SPADES_ABNORMAL_FASTQ_LOCAL_ASSEMBLY"
                ),
                "SPADES_EXPECTED_INPUT_CLASS": (
                    "STEP05_ABNORMAL_FASTQ_ONLY"
                ),
                "MANTA_EXPECTED_INPUT_CLASS": (
                    "BAM_CONTAINS_ANALYSIS_READY_OR_VALIDATED_AND_EXCLUDES_ABNORMAL"
                ),
                "GRIDSS2_EXPECTED_INPUT_CLASS": (
                    "BAM_CONTAINS_ANALYSIS_READY_OR_VALIDATED_AND_EXCLUDES_ABNORMAL"
                ),
                "DELLY_EXPECTED_INPUT_CLASS": (
                    "BAM_CONTAINS_ANALYSIS_READY_OR_VALIDATED_AND_EXCLUDES_ABNORMAL"
                ),
                "SVABA_EXPECTED_INPUT_CLASS": (
                    "BAM_CONTAINS_ANALYSIS_READY_OR_VALIDATED_AND_EXCLUDES_ABNORMAL"
                ),
                "STEP03_ANALYSIS_READY_BAM": (
                    str(step03_full_bam) if step03_full_bam is not None else ""
                ),
                "MANTA_INPUT_BAM": (
                    str(step03_full_bam)
                    if run_manta_for_sample and step03_full_bam is not None
                    else ""
                ),
                "STEP03_BAM_BAI": step03_bam_readiness.get("BAI", ""),
                "STEP03_BAM_BAI_STATUS": step03_bam_readiness.get(
                    "BAI_STATUS", ""
                ),
                "MANTA_RUN_DIRECTORY": str(manta_run),
                "MANTA_SV_VCF": manta_vcf,
                "MANTA_VCF_PARSE_DIAGNOSTICS": (
                    str(
                        sample_dir
                        / f"{sample_id}.manta_vcf_parse_diagnostics.tsv"
                    )
                    if manta_vcf
                    else ""
                ),
                "SPADES_RUN_FOR_SAMPLE": run_spades_for_sample,
                "SPADES_INPUT_MODE": spades_input_mode,
                "SPADES_SOURCE_TYPE": spades_source_type,
                "SPADES_R1_READ_COUNT": spades_r1_count,
                "SPADES_R2_READ_COUNT": spades_r2_count,
                "SPADES_SINGLETON_READ_COUNT": spades_singleton_count,
                "SPADES_KMER_MODE": str(cfg.get("spades_kmer_mode", "automatic")),
                "SPADES_EFFECTIVE_KMERS": spades_effective_kmers,
                "SPADES_WORKSPACE_MODE": (
                    "KNOWN_NATIVE_LINUX_WORKDIR_AUTOCLEAN"
                    if run_spades_for_sample and not dry_run
                    else ("DRY_RUN" if dry_run else "NOT_RUN")
                ),
                "MANTA_RUN_FOR_SAMPLE": run_manta_for_sample,
                "GRIDSS2_RUN_FOR_SAMPLE": run_gridss2_for_sample,
                "GRIDSS2_RUN_DIRECTORY": str(gridss_run),
                "GRIDSS2_SV_VCF": gridss_vcf,
                "DELLY_RUN_FOR_SAMPLE": run_delly_for_sample,
                "DELLY_RUN_DIRECTORY": str(delly_run),
                "DELLY_SV_VCF": delly_vcf,
                "SVABA_RUN_FOR_SAMPLE": run_svaba_for_sample,
                "REFERENCE_FASTA_FAI": str(reference_fai),
                "CLASSIC_BWA_INDEX_SELECTED_FILE": str(cfg.get("classic_bwa_index_file", "")),
                "CLASSIC_BWA_INDEX_PREFIX": str(classic_bwa_index_info.get("INDEX_PREFIX", "")),
                "GRIDSS_SVABA_REFERENCE_FASTA": str(
                    classic_bwa_index_info.get("REFERENCE_FOR_BWA_CALLERS", "")
                ),
                "SVABA_RUN_DIRECTORY": str(svaba_run),
                "SVABA_SV_VCF": svaba_vcf,
                "CANONICAL_CHROMOSOMES": ";".join(canonical_chromosomes),
                "CANONICAL_CLASSIFICATION_RULE": (
                    "BOTH_BREAKENDS_MUST_BE_USER_SELECTED_CANONICAL"
                    if canonical_chromosomes
                    else "NO_CANONICAL_SELECTION_OUTPUT_NOT_SPLIT"
                ),
            }
        )

    combined = (
        pd.concat(breakpoint_tables, ignore_index=True)
        if breakpoint_tables else pd.DataFrame()
    )

    if not dry_run and not combined.empty:
        combined = annotate_breakpoint_evidence(
            combined,
            step03_bam_by_sample,
            cfg,
        )

    if canonical_chromosomes:
        combined = classify_breakpoints_by_reference(
            combined,
            canonical_chromosomes,
        )
        canonical_breakpoints = (
            combined.loc[
                combined["BREAKPOINT_REFERENCE_CLASS"] == "CANONICAL"
            ].copy()
            if "BREAKPOINT_REFERENCE_CLASS" in combined.columns
            else pd.DataFrame()
        )
        noncanonical_breakpoints = (
            combined.loc[
                combined["BREAKPOINT_REFERENCE_CLASS"] == "NON_CANONICAL"
            ].copy()
            if "BREAKPOINT_REFERENCE_CLASS" in combined.columns
            else pd.DataFrame()
        )
    else:
        canonical_breakpoints = combined.copy()
        noncanonical_breakpoints = pd.DataFrame(columns=combined.columns)

    contigs = (
        pd.concat(contig_metrics, ignore_index=True)
        if contig_metrics else pd.DataFrame()
    )
    output_manifest = pd.DataFrame(output_rows)
    write_tsv(output_manifest, output_dir / "breakpoint_calling_results.tsv")
    write_tsv(
        pd.DataFrame(algorithm_validation_rows),
        output_dir / "algorithm_input_validation.tsv",
    )
    if canonical_chromosomes:
        canonical_output_path = output_dir / "candidate_breakpoints_Canonical.tsv"
        noncanonical_output_path = output_dir / "candidate_breakpoints_NonCanonical.tsv"
        write_tsv(canonical_breakpoints, canonical_output_path)
        write_tsv(noncanonical_breakpoints, noncanonical_output_path)
        main_output_path = canonical_output_path
    else:
        main_output_path = output_dir / "candidate_breakpoints.tsv"
        noncanonical_output_path = None
        write_tsv(combined, main_output_path)

    write_tsv(contigs, output_dir / "assembled_contig_metrics.tsv")
    write_breakpoint_evidence_definition(
        output_dir / "breakpoint_evidence_metrics_explained.tsv"
    )

    plots: list[Path] = []
    # When canonical references were selected, biological plots focus on the
    # canonical subset. Otherwise they summarize the unsplit complete table.
    plot_breakpoints = canonical_breakpoints if canonical_chromosomes else combined

    if canonical_chromosomes:
        classification_plot = output_dir / "breakpoint_reference_class_counts.png"
        if combined.empty or "BREAKPOINT_REFERENCE_CLASS" not in combined.columns:
            save_placeholder_plot(
                classification_plot,
                "Canonical versus non-canonical breakpoints",
                "No breakpoint candidates were available.",
            )
        else:
            class_counts = combined["BREAKPOINT_REFERENCE_CLASS"].value_counts()
            save_bar_plot(
                class_counts.index.astype(str).tolist(),
                class_counts.astype(float).tolist(),
                classification_plot,
                "Canonical versus non-canonical breakpoint candidates",
                "Candidate count",
                rotate=0,
            )
        plots.append(classification_plot)


    caller_plot = output_dir / "breakpoint_caller_counts.png"
    if plot_breakpoints.empty or "SOURCE" not in plot_breakpoints.columns:
        save_placeholder_plot(
            caller_plot,
            "Breakpoint candidates by caller",
            "No breakpoint candidates were available.",
        )
    else:
        caller_counts = plot_breakpoints["SOURCE"].astype(str).value_counts()
        save_bar_plot(
            caller_counts.index.tolist(),
            caller_counts.astype(float).tolist(),
            caller_plot,
            "Breakpoint candidates contributed by each algorithm",
            "Candidate record count (before cross-caller consolidation)",
            rotate=30,
        )
    plots.append(caller_plot)

    svtype_plot = output_dir / "breakpoint_svtype_counts.png"
    if plot_breakpoints.empty or "SVTYPE" not in plot_breakpoints.columns:
        save_placeholder_plot(
            svtype_plot,
            "Structural-variant type counts",
            "No breakpoint candidates were available.",
        )
    else:
        counts = plot_breakpoints["SVTYPE"].value_counts()
        save_bar_plot(
            counts.index.astype(str).tolist(),
            counts.astype(float).tolist(),
            svtype_plot,
            "Candidate structural-variant types",
            "Candidate count",
            rotate=45,
        )
    plots.append(svtype_plot)

    chromosome_pair_plot = output_dir / "breakpoint_chromosome_pair_counts.png"
    if plot_breakpoints.empty:
        save_placeholder_plot(
            chromosome_pair_plot,
            "Breakpoint chromosome pairs",
            "No breakpoint candidates were available.",
        )
    else:
        pairs = (
            plot_breakpoints["CHROM1"].astype(str)
            + " ↔ "
            + plot_breakpoints["CHROM2"].astype(str)
        ).value_counts().head(30)
        save_bar_plot(
            pairs.index.astype(str).tolist(),
            pairs.astype(float).tolist(),
            chromosome_pair_plot,
            "Most frequent breakpoint chromosome pairs",
            "Candidate count",
            rotate=65,
        )
    plots.append(chromosome_pair_plot)

    evidence_plot = output_dir / "breakpoint_evidence_score_distribution.png"
    if plot_breakpoints.empty or "EVIDENCE_SCORE_0_100" not in plot_breakpoints.columns:
        save_placeholder_plot(
            evidence_plot,
            "Breakpoint evidence scores",
            "No scored breakpoint candidates were available.",
        )
    else:
        figure, axis = plt.subplots(figsize=(9, 6))
        values = pd.to_numeric(
            plot_breakpoints["EVIDENCE_SCORE_0_100"],
            errors="coerce",
        ).dropna()
        axis.hist(values, bins=20)
        axis.set_xlabel("Heuristic evidence score (0–100; not a p-value)")
        axis.set_ylabel("Breakpoint candidate count")
        axis.set_title("Breakpoint evidence-score distribution")
        axis.grid(axis="y", alpha=0.25)
        figure.tight_layout()
        figure.savefig(evidence_plot, dpi=180)
        plt.close(figure)
    plots.append(evidence_plot)

    support_depth_plot = output_dir / "breakpoint_local_depth_vs_alt_support.png"
    if (
        plot_breakpoints.empty
        or "LOCAL_DEPTH_MIN_MEAN" not in plot_breakpoints.columns
        or "MANTA_ALT_SUPPORT_TOTAL" not in plot_breakpoints.columns
    ):
        save_placeholder_plot(
            support_depth_plot,
            "Local depth versus Manta alternate support",
            "Manta support/local-depth values were not available.",
        )
    else:
        x = pd.to_numeric(
            plot_breakpoints["LOCAL_DEPTH_MIN_MEAN"],
            errors="coerce",
        )
        y = pd.to_numeric(
            plot_breakpoints["MANTA_ALT_SUPPORT_TOTAL"],
            errors="coerce",
        )
        mask = x.notna() & y.notna()
        if not mask.any():
            save_placeholder_plot(
                support_depth_plot,
                "Local depth versus Manta alternate support",
                "No Manta candidate had both local-depth and support values.",
            )
        else:
            figure, axis = plt.subplots(figsize=(9, 6))
            axis.scatter(x[mask], y[mask], alpha=0.7)
            axis.set_xlabel("Minimum mean local depth across both breakends")
            axis.set_ylabel("Manta alternate support (PR_ALT + SR_ALT)")
            axis.set_title("Breakpoint local coverage versus alternate evidence")
            axis.grid(alpha=0.25)
            figure.tight_layout()
            figure.savefig(support_depth_plot, dpi=180)
            plt.close(figure)
    plots.append(support_depth_plot)

    contig_plot = output_dir / "assembled_contig_length_distribution.png"
    if contigs.empty:
        save_placeholder_plot(
            contig_plot,
            "Assembled contig lengths",
            "No filtered SPAdes contigs were available.",
        )
    else:
        figure, axis = plt.subplots(figsize=(9, 6))
        axis.hist(pd.to_numeric(contigs["LENGTH"], errors="coerce").dropna(), bins=60)
        axis.set_xlabel("Contig length (bp)")
        axis.set_ylabel("Contig count")
        axis.set_title("Breakpoint-candidate contig lengths")
        axis.grid(axis="y", alpha=0.25)
        figure.tight_layout()
        figure.savefig(contig_plot, dpi=180)
        plt.close(figure)
    plots.append(contig_plot)

    # A normally completed Step 06 run should leave no native-Linux SPAdes
    # working files behind. Forced termination is handled at the next startup.
    if not dry_run:
        cleanup_spades_known_work_root(spades_work_root)

    status_message = (
        (
            f"Generated {len(combined)} total breakpoint candidate record(s): "
            f"{len(canonical_breakpoints)} canonical and "
            f"{len(noncanonical_breakpoints)} non-canonical. "
            f"Main downstream file: {main_output_path.name}"
        )
        if canonical_chromosomes
        else (
            f"Generated {len(combined)} breakpoint candidate record(s). "
            "No canonical chromosome selection was supplied, so output was not split. "
            f"Main file: {main_output_path.name}"
        )
    )
    write_step_status(
        output_dir,
        SPEC.title,
        "PASS",
        status_message,
        len(output_manifest),
        plots,
    )
    print(main_output_path)



STEP_GUI = {'environment': 'ctdna_core',
 'fields': [{'setting': 'breakpoints.analysis_ready_bam_folder',
             'label': 'Step 03 validated/full BAM folder - Manta/GRIDSS2/DELLY/SvABA/local depth',
             'type': 'folder',
             'required': True,
             'scan_globs': ['*.bam'],
             'accept_name_contains_any': ['analysis_ready', 'validated'],
             'reject_name_contains': ['abnormal', 'aberrant'],
             'section': 'INPUTS AND REFERENCE',
             'help': 'Complete validated BAMs only. Used by enabled BAM-based SV callers (Manta, GRIDSS2, DELLY, SvABA) and local-depth calculations.'},
            {'setting': '__input_dir__',
             'label': 'Step 05 abnormal FASTQ folder - SPAdes input',
             'type': 'folder',
             'required': True,
             'scan_globs': ['*.fastq', '*.fastq.gz', '*.fq', '*.fq.gz'],
             'accept_name_contains_any': ['abnormal'],
             'section': 'INPUTS AND REFERENCE',
             'help': 'Step 05 abnormal FASTQ/FQ files only. BAM files are not accepted by the SPAdes branch.'},
            {'setting': 'references.fasta',
             'label': 'Reference FASTA',
             'type': 'file',
             'required': True,
             'allowed_suffixes': ['.fa', '.fasta', '.fna'],
             'filetypes': [('FASTA', '*.fa *.fasta *.fna'), ('All files', '*.*')],
             'button_text': 'Browse reference FASTA',
             'section': 'INPUTS AND REFERENCE'},
            {'setting': 'references.fasta_fai',
             'label': 'Reference FASTA index (.fai)',
             'type': 'file',
             'required': False,
             'allowed_suffixes': ['.fai'],
             'filetypes': [('FASTA index', '*.fai'), ('All files', '*.*')],
             'button_text': 'Browse FASTA .fai',
             'section': 'INPUTS AND REFERENCE',
             'help': 'Used by the BAM-based SV callers. Select the .fai belonging to the chosen FASTA, or leave blank and Step 06 will create <FASTA>.fai with samtools faidx if needed.'},
            {'setting': 'breakpoints.classic_bwa_index_file',
             'label': 'Classic BWA/BWA-MEM index for GRIDSS2/SvABA',
             'type': 'file',
             'required': False,
             'allowed_suffixes': ['.amb', '.ann', '.bwt', '.pac', '.sa'],
             'filetypes': [('Classic BWA index', '*.amb *.ann *.bwt *.pac *.sa'), ('All files', '*.*')],
             'button_text': 'Browse BWA index',
             'action': 'create_classic_bwa_index',
             'action_button_text': 'Create BWA-MEM1 index',
             'section': 'INPUTS AND REFERENCE',
             'help': 'Required when GRIDSS2 or SvABA is enabled. Either browse to any ONE classic BWA index component for the exact reference FASTA, or click Create BWA-MEM index to run classic `bwa index` in WSL and create a BWA-MEM1_Index subfolder containing an exact FASTA mirror plus .fai/.amb/.ann/.bwt/.pac/.sa. GRIDSS2/SvABA use that indexed FASTA. This index is separate from the BWA-MEM2 index used by the main mapping step.'},
            {'setting': 'breakpoints.canonical_chromosomes',
             'label': 'Canonical chromosomes/reference sequences (optional)',
             'type': 'text',
             'required': False,
             'action': 'scan_select_canonical_chromosomes',
             'action_button_text': 'Scan/select canonical chromosomes',
             'section': 'INPUTS AND REFERENCE',
             'help': 'Optional. Click Scan/select after choosing the FASTA. If one or more references are selected, Step 06 writes candidate_breakpoints_Canonical.tsv and candidate_breakpoints_NonCanonical.tsv. If this field is left empty, no canonical split is applied and the output remains candidate_breakpoints.tsv.'},
            {'setting': 'breakpoints.run_spades_assembly',
             'label': 'Run SPAdes local assembly on abnormal FASTQ evidence',
             'type': 'bool',
             'section': 'CALLERS'},
            {'setting': 'breakpoints.run_manta',
             'label': 'Run Manta structural-variant caller on full BAM',
             'type': 'bool',
             'section': 'CALLERS'},
            {'setting': 'breakpoints.run_gridss2',
             'label': 'Run GRIDSS2 breakpoint/assembly caller on full BAM',
             'type': 'bool',
             'section': 'CALLERS',
             'help': 'Requires BWA on PATH and the classic BWA index selected above with the reference FASTA.'},
            {'setting': 'breakpoints.run_delly',
             'label': 'Run DELLY short-read structural-variant caller on full BAM',
             'type': 'bool',
             'section': 'CALLERS',
             'help': 'Uses DELLY sr on the complete coordinate-sorted/indexed BAM and bcftools to normalize its output to VCF.'},
            {'setting': 'breakpoints.run_svaba',
             'label': 'Run SvABA local-assembly structural-variant caller on full BAM',
             'type': 'bool',
             'section': 'CALLERS',
             'help': 'Performs genome-wide local assembly from the complete analysis-ready BAM using the same reference FASTA and classic BWA index selected above.'},
            {'setting': 'breakpoints.spades_kmer_mode',
             'label': 'SPAdes k-mer selection',
             'type': 'choice',
             'required': True,
             'choices': ['Automatic — recommended', 'Manual'],
             'choice_values': {'Automatic — recommended': 'automatic', 'Manual': 'manual'},
             'section': 'BREAKPOINT PARAMETERS',
             'help': 'Automatic omits -k and lets SPAdes select k-mers. Manual enables the read-length analysis helper and an editable k-mer list.'},
            {'setting': 'breakpoints.spades_kmers',
             'label': 'Manual SPAdes k-mers',
             'type': 'text',
             'required': False,
             'action': 'analyze_spades_read_lengths',
             'action_button_text': 'Analyze read-length distribution',
             'section': 'BREAKPOINT PARAMETERS',
             'help': 'Manual mode only. The analysis button calculates the read-length distribution from abnormal FASTQ/FQ files, proposes k-mers from the maximum-read-length table, and leaves this field editable.'},
            {'setting': 'breakpoints.minimum_contig_length',
             'label': 'Minimum assembled contig length (bp)',
             'type': 'int',
             'required': True,
             'section': 'BREAKPOINT PARAMETERS'},
            {'setting': 'breakpoints.minimum_contig_alignment_length',
             'label': 'Minimum contig alignment length (bp)',
             'type': 'int',
             'required': True,
             'section': 'BREAKPOINT PARAMETERS'},
            {'setting': 'breakpoints.local_depth_window_bp',
             'label': 'Local depth window around breakpoint (bp)',
             'type': 'int',
             'required': True,
             'section': 'BREAKPOINT PARAMETERS'},
            ],
 'explanation': 'Combines five complementary structural-variant strategies: SPAdes→minimap2 assembly of Step 05 abnormal FASTQ evidence, '
                'plus Manta, GRIDSS2, DELLY and SvABA from complete validated BAMs. All five callers are enabled by default, but each can still be disabled individually. '
                'The reference FASTA can be scanned so the user can explicitly select canonical chromosomes/reference sequences. '
                'When a canonical selection exists, results are split into candidate_breakpoints_Canonical.tsv and '
                'candidate_breakpoints_NonCanonical.tsv; when no canonical references are selected, the single output is '
                'candidate_breakpoints.tsv. The full reference remains available to every caller. The abnormal FASTQ subset is used '
                'only by the SPAdes branch and is never substituted for the complete BAM used by the BAM-based callers.'}

if __name__ == "__main__":
    launch_step(SPEC, backend)
