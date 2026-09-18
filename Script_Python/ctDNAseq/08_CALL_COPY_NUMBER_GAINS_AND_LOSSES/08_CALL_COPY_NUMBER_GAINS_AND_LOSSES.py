from __future__ import annotations

import threading

# ============================================================================
# SELF-CONTAINED RUNTIME
# This file intentionally contains its own settings, GUI, discovery, plotting,
# WSL launcher, and helper functions. It does not import a project-level package.
# ============================================================================
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
from datetime import datetime
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


# ============================================================================
# REAL COMMON CLI ARGUMENT PARSER — EDIT CLI ARGUMENTS HERE
# This is the actual argparse code used by launch_step().
# Step-specific DEFAULT_SETTINGS options are added automatically later.
# ============================================================================
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
    parser.add_argument('--references-fasta', dest='__cfg__references__fasta', type=str, default='', help='Override references.fasta for this execution.')
    parser.add_argument('--copy-number-reference-mode', dest='__cfg__copy_number__reference_mode', type=str, default='existing', help='Override copy_number.reference_mode for this execution.')
    parser.add_argument('--copy-number-method', dest='__cfg__copy_number__method', type=str, default='hybrid', help='Override copy_number.method for this execution.')
    parser.add_argument('--copy-number-normal-bam-folder', dest='__cfg__copy_number__normal_bam_folder', type=str, default='', help='Override copy_number.normal_bam_folder for this execution.')
    parser.add_argument('--copy-number-reference-cnn', dest='__cfg__copy_number__reference_cnn', type=str, default='', help='Override copy_number.reference_cnn for this execution.')
    parser.add_argument('--copy-number-targets-bed', dest='__cfg__copy_number__targets_bed', type=str, default='', help='Override copy_number.targets_bed for this execution.')
    parser.add_argument('--copy-number-output-reference-cnn', dest='__cfg__copy_number__output_reference_cnn', type=str, default='', help='Override copy_number.output_reference_cnn for this execution.')
    parser.add_argument('--copy-number-segment-method', dest='__cfg__copy_number__segment_method', type=str, default='haar', help='Override copy_number.segment_method for this execution.')
    parser.add_argument('--copy-number-male-reference', dest='__cfg__copy_number__male_reference', type=_parse_cli_bool, default=False, help='Override copy_number.male_reference for this execution.')
    parser.add_argument('--copy-number-drop-low-coverage', dest='__cfg__copy_number__drop_low_coverage', type=_parse_cli_bool, default=False, help='Override copy_number.drop_low_coverage for this execution.')
    parser.add_argument('--copy-number-gain-ratio-threshold', dest='__cfg__copy_number__gain_ratio_threshold', type=float, default=1.4, help='Override copy_number.gain_ratio_threshold for this execution.')
    parser.add_argument('--copy-number-loss-ratio-threshold', dest='__cfg__copy_number__loss_ratio_threshold', type=float, default=-1.4, help='Override copy_number.loss_ratio_threshold for this execution.')
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
           'manta_config': '',
           'manta_run': '',
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
 'breakpoints': {'run_spades_assembly': True,
                 'run_manta': True,
                 'spades_kmers': '21,33,55',
                 'minimum_contig_length': 100,
                 'minimum_contig_alignment_length': 50,
                 'minimum_reference_separation_bp': 10000,
                 'manta_targeted_mode': False,
                 'manta_call_regions_bed': '',
                 'analysis_ready_bam_folder': '',
                 'local_depth_window_bp': 100,
                 'local_depth_minimum_mapping_quality': 20,
                 'spades_linux_work_root': '$HOME/ctdna_step06_spades_work'},
 'copy_number': {'enabled': True},
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
    """Discover Step-05 abnormal FASTQs and matching analysis-ready BAMs."""
    rows: dict[str, dict[str, str]] = {}

    suffix_map = {
        ".abnormal.R1.fastq.gz": "ABNORMAL_R1_FASTQ",
        ".abnormal.R2.fastq.gz": "ABNORMAL_R2_FASTQ",
        ".abnormal.singletons.fastq.gz": "ABNORMAL_SINGLETON_FASTQ",
        ".abnormal.R1.fastq": "ABNORMAL_R1_FASTQ",
        ".abnormal.R2.fastq": "ABNORMAL_R2_FASTQ",
        ".abnormal.singletons.fastq": "ABNORMAL_SINGLETON_FASTQ",
    }
    for path in sorted(input_dir.rglob("*")):
        if not path.is_file():
            continue
        for suffix, column in suffix_map.items():
            if path.name.endswith(suffix):
                sample = path.name[: -len(suffix)]
                rows.setdefault(sample, {"SAMPLE_ID": sample})[column] = str(path.resolve())
                break

    bams = discover_bams(input_dir, recursive=True)
    for record in bams.to_dict(orient="records"):
        sample = str(record["SAMPLE_ID"])
        rows.setdefault(sample, {"SAMPLE_ID": sample})["FINAL_BAM"] = str(record["BAM"])

    columns = [
        "SAMPLE_ID",
        "FINAL_BAM",
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

from pathlib import Path
from typing import Any

import pandas as pd


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
                section_help = str(
                    self.gui_spec.get("section_help", {}).get(section, "")
                ).strip()
                if section_help:
                    tk.Label(
                        current_card,
                        text=section_help,
                        bg="white",
                        fg="#475569",
                        font=("Segoe UI", 8),
                        wraplength=990,
                        justify="left",
                        anchor="w",
                    ).pack(fill="x", padx=(4, 4), pady=(0, 8))
            self._add_field(current_card,field)

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

        gui_state=self.settings.get('_gui_state',{}) if isinstance(self.settings,dict) else {}
        output_default=str(gui_state.get('output_dir') or (self.step_dir/'output').resolve())
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

        self.backup_settings_button=ttk.Button(
            buttons,
            text="Backup settings (.json)",
            command=self._backup_settings_clicked,
        )
        self.backup_settings_button.pack(side="left",padx=4)

        self.restore_settings_button=ttk.Button(
            buttons,
            text="Restore settings (.json)",
            command=self._restore_settings_clicked,
        )
        self.restore_settings_button.pack(side="left",padx=4)

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
            gui_state=self.settings.get('_gui_state',{}) if isinstance(self.settings,dict) else {}
            value=str(gui_state.get('input_dir') or (self.step_dir/'input').resolve())
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
            else:
                entry=ttk.Entry(row,textvariable=var)
                entry.pack(side="left",fill="x",expand=True,padx=(4,6))

                if typ in {'file','folder','save_file'}:
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

    def _path_row(self,parent,label,var,kind='folder',title='Select'):
        tk,ttk=self.tk,self.ttk; row=tk.Frame(parent,bg="white"); row.pack(fill="x",pady=4)
        tk.Label(row,text=label,bg="white",font=("Segoe UI",8,"bold"),width=34,anchor="w").pack(side="left")
        ttk.Entry(row,textvariable=var).pack(side="left",fill="x",expand=True,padx=(4,6))
        ttk.Button(row,text="Browse",command=lambda:self._browse({'type':kind,'title':title},var)).pack(side="left")

    def _browse(self,field,var):
        current=var.get().strip()
        current_path=Path(current) if current else None
        initial=(
            current_path.parent
            if current_path is not None and current_path.parent.exists()
            else self.step_dir
        )
        field_type=field.get('type')
        if field_type=='folder':
            selected=self.filedialog.askdirectory(
                initialdir=initial,
                title=field.get('title',field.get('label','Select folder')),
            )
        elif field_type=='save_file':
            patterns=field.get('filetypes') or [('All files','*.*')]
            initialfile=(
                current_path.name
                if current_path is not None and current_path.name
                else field.get('default_filename','CNVkit_flat_reference.cnn')
            )
            selected=self.filedialog.asksaveasfilename(
                initialdir=initial,
                initialfile=initialfile,
                title=field.get('title') or field.get('label','Select output file'),
                filetypes=patterns,
                defaultextension=field.get('default_extension','.cnn'),
                confirmoverwrite=True,
            )
        else:
            patterns=field.get('filetypes') or [('All files','*.*')]
            selected=self.filedialog.askopenfilename(
                initialdir=initial,
                title=field.get('title') or f"Find required file: {field.get('expected_name') or field.get('label','file')}",
                filetypes=patterns,
            )
        if selected:
            var.set(selected)

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

            if typ=='save_file' and value:
                p=Path(value)
                suffixes=[s.lower() for s in field.get('allowed_suffixes',[])]
                if suffixes and not any(p.name.lower().endswith(s) for s in suffixes):
                    raise ValueError(
                        f"Output filename must end with one of: {', '.join(suffixes)}"
                    )

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

    def _settings_from_gui_without_path_validation(self):
        """Collect the current GUI values for a manual JSON backup.

        Unlike _collect(), this does not require selected files/folders to exist.
        This lets the user back up partially completed GUI settings safely.
        """
        settings=copy.deepcopy(self.settings)

        for field in self.gui_spec.get('fields',[]):
            key=field['setting']
            if key=='__input_dir__':
                continue
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

            _setting_set(settings,key,value)

        _setting_set(settings,'project.threads',int(self.vars['project.threads'].get()))
        for key in [
            'execution.wsl_distribution',
            'execution.micromamba_environment',
            'execution.micromamba_executable',
            'execution.micromamba_root_prefix',
            'execution.python_executable_in_wsl',
        ]:
            _setting_set(settings,key,self.vars[key].get().strip())

        # GUI-only locations are not part of DEFAULT_SETTINGS, so preserve them
        # explicitly. These include the validated/full BAM folder and output folder.
        settings['_gui_state']={
            'input_dir': str(self.vars.get('__input_dir__').get()).strip()
                if self.vars.get('__input_dir__') is not None else '',
            'output_dir': str(self.vars.get('__output_dir__').get()).strip()
                if self.vars.get('__output_dir__') is not None else '',
        }

        return settings

    def _automatic_settings_backup(self):
        """Back up the previous step_user_settings.json before it is overwritten."""
        if not self.settings_path.exists() or not self.settings_path.is_file():
            return None

        backup_dir=self.step_dir/'settings_backups'
        backup_dir.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup_path=backup_dir/f'step_user_settings_{stamp}.json'
        shutil.copy2(self.settings_path,backup_path)
        return backup_path

    def _write_primary_settings(self,settings,make_backup=True):
        """Atomically write step_user_settings.json, optionally backing up the old file."""
        backup_path=self._automatic_settings_backup() if make_backup else None
        self.settings_path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.settings_path.with_name(self.settings_path.name+'.tmp')
        with temporary.open('w',encoding='utf-8') as h:
            json.dump(settings,h,indent=2,ensure_ascii=False)
            h.write('\n')
        os.replace(temporary,self.settings_path)
        return backup_path

    def _save(self):
        settings,input_dir,output_dir=self._collect()
        # Preserve GUI-only locations that are not represented in DEFAULT_SETTINGS.
        settings['_gui_state']={
            'input_dir': str(input_dir),
            'output_dir': str(output_dir),
        }
        output_dir.mkdir(parents=True,exist_ok=True)
        backup_path=self._write_primary_settings(settings,make_backup=True)
        self.settings=settings
        if backup_path is None:
            self.status.set(f"Settings saved: {self.settings_path} (no previous JSON existed to back up)")
        else:
            self.status.set(f"Settings saved: {self.settings_path} | Previous settings backed up: {backup_path}")
        return settings,input_dir,output_dir

    def _save_clicked(self):
        try:
            self._save()
            self.messagebox.showinfo('Settings',self.status.get())
        except Exception as exc:
            self.messagebox.showerror('Settings error',str(exc))

    def _backup_settings_clicked(self):
        """Save the current GUI values to a user-selected standalone JSON backup file."""
        try:
            settings=self._settings_from_gui_without_path_validation()
            stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
            default_name=f'step08_settings_backup_{stamp}.json'
            selected=self.filedialog.asksaveasfilename(
                initialdir=self.step_dir,
                initialfile=default_name,
                title='Backup Step 08 settings JSON',
                filetypes=[('JSON settings','*.json'),('All files','*.*')],
                defaultextension='.json',
                confirmoverwrite=True,
            )
            if not selected:
                return
            backup_path=Path(selected)
            backup_path.parent.mkdir(parents=True,exist_ok=True)
            temporary=backup_path.with_name(backup_path.name+'.tmp')
            with temporary.open('w',encoding='utf-8') as h:
                json.dump(settings,h,indent=2,ensure_ascii=False)
                h.write('\n')
            os.replace(temporary,backup_path)
            self.status.set(f"Settings backup created: {backup_path}")
            self.messagebox.showinfo('Settings backup',f"Backup created successfully:\n\n{backup_path}")
        except Exception as exc:
            self.messagebox.showerror('Settings backup error',str(exc))

    def _restore_settings_clicked(self):
        """Load a saved/backup JSON and repopulate every GUI field, including GUI-only paths."""
        try:
            selected=self.filedialog.askopenfilename(
                initialdir=self.step_dir,
                title='Restore Step 08 settings JSON',
                filetypes=[('JSON settings','*.json'),('All files','*.*')],
            )
            if not selected:
                return

            restore_path=Path(selected)
            with restore_path.open('r',encoding='utf-8') as h:
                loaded=json.load(h)
            if not isinstance(loaded,dict):
                raise ValueError('The selected JSON does not contain a settings object.')

            # Merge with current defaults so older backups remain usable if new
            # settings have been added since the backup was created.
            restored=_deep_merge(DEFAULT_SETTINGS,loaded)
            self.settings=restored
            gui_state=restored.get('_gui_state',{}) if isinstance(restored,dict) else {}

            for field in self.gui_spec.get('fields',[]):
                key=field['setting']
                typ=field.get('type','text')
                if key=='__input_dir__':
                    value=str(gui_state.get('input_dir',''))
                else:
                    value=_setting_get(restored,key)

                if typ=='choice':
                    reverse={
                        str(internal):str(display)
                        for display,internal in field.get('choice_values',{}).items()
                    }
                    value=reverse.get(str(value),str(value if value is not None else ''))
                elif typ=='bool':
                    value=bool(value)
                else:
                    value=str(value if value is not None else '')
                if key in self.vars:
                    self.vars[key].set(value)

            if '__output_dir__' in self.vars:
                self.vars['__output_dir__'].set(str(gui_state.get('output_dir','')))

            for key in [
                'project.threads',
                'execution.wsl_distribution',
                'execution.micromamba_environment',
                'execution.micromamba_executable',
                'execution.micromamba_root_prefix',
                'execution.python_executable_in_wsl',
            ]:
                if key in self.vars:
                    self.vars[key].set(str(_setting_get(restored,key)))

            self.status.set(f'Settings restored from: {restore_path}')
            self.messagebox.showinfo(
                'Settings restored',
                'Settings restored successfully, including the validated/full BAM '
                f'folder and output folder.\n\n{restore_path}',
            )
        except Exception as exc:
            self.messagebox.showerror('Settings restore error',str(exc))

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
                self._write_primary_settings(settings,make_backup=True)
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


from pathlib import Path
import shutil
import math

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd



SPEC = StepSpecification(
    number=8,
    title="08_CALL_COPY_NUMBER_GAINS_AND_LOSSES",
    description=(
        "Run CNVkit using an existing or newly built assay-specific reference, "
        "segment copy-number signal, classify gains/losses with LINEAR copy "
        "ratios, and plot genome-wide signed copy ratios."
    ),
    default_input_dir="input",
    default_output_dir="output",
)



def _is_validated_full_bam_name(path: Path) -> bool:
    """
    Step 07 tumor/control BAM rule.

    ACCEPT only BAM filenames that:
      - contain 'analysis_ready' OR 'validated'
      - do NOT contain 'abnormal'
    """
    name = path.name.lower()
    return (
        name.endswith(".bam")
        and "abnormal" not in name
        and ("analysis_ready" in name or "validated" in name)
    )


def validate_and_filter_full_bams(
    inputs: pd.DataFrame,
    label: str,
) -> pd.DataFrame:
    """
    Validate BAM discovery for CNV analysis/reference building.

    Any abnormal BAM causes an immediate hard error. Other BAMs that do not
    contain analysis_ready/validated are rejected. At least one valid full BAM
    must remain.
    """
    if inputs.empty:
        raise FileNotFoundError(f"No BAM files were found for {label}.")

    abnormal_rows: list[dict[str, str]] = []
    invalid_rows: list[dict[str, str]] = []
    keep_rows: list[dict[str, str]] = []

    for row in inputs.to_dict(orient="records"):
        bam_value = str(
            row.get("BAM")
            or row.get("FINAL_BAM")
            or ""
        ).strip()
        if not bam_value:
            continue

        bam_path = Path(bam_value)
        record = {
            "SAMPLE_ID": str(row.get("SAMPLE_ID", "")),
            "BAM": str(bam_path),
        }

        if "abnormal" in bam_path.name.lower():
            abnormal_rows.append(record)
        elif not _is_validated_full_bam_name(bam_path):
            invalid_rows.append(record)
        else:
            keep_rows.append(dict(row))

    if abnormal_rows:
        table = pd.DataFrame(abnormal_rows)
        raise ValueError(
            f"{label.upper()} REJECTED: abnormal BAM detected.\n\n"
            "CNV analysis must use COMPLETE validated/full BAMs. BAM filenames "
            "containing 'abnormal' are forbidden.\n\n"
            + table.to_string(index=False)
        )

    if not keep_rows:
        extra = ""
        if invalid_rows:
            extra = (
                "\n\nBAMs found but rejected because the filename did not contain "
                "'analysis_ready' or 'validated':\n"
                + pd.DataFrame(invalid_rows).to_string(index=False)
            )
        raise ValueError(
            f"{label.upper()} REJECTED: no validated/full BAM was accepted.\n\n"
            "Accepted BAM filenames must contain 'analysis_ready' OR 'validated' "
            "and must NOT contain 'abnormal'."
            + extra
        )

    return pd.DataFrame(keep_rows)


def discover_reference_normal_bams(folder_value: str) -> pd.DataFrame:
    """Discover and validate normal/control full BAMs for reference building."""
    folder_text = str(folder_value or "").strip()
    if not folder_text:
        return pd.DataFrame(columns=["SAMPLE_ID", "BAM", "BAM_DISCOVERY"])

    folder = normalized_input_path(folder_text)
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(
            f"Normal/control BAM folder was not found: {folder}"
        )

    table = discover_bams(folder, recursive=True)
    return validate_and_filter_full_bams(
        table,
        "CNVkit normal/control BAM folder",
    )


def _is_placeholder_cnn(value: object) -> bool:
    return not str(value or "").strip()


def _bam_index_exists(bam_path: Path) -> bool:
    candidates = [
        Path(str(bam_path) + ".bai"),
        bam_path.with_suffix(".bai"),
        Path(str(bam_path) + ".csi"),
        bam_path.with_suffix(".csi"),
    ]
    return any(
        path.exists() and path.is_file() and path.stat().st_size > 0
        for path in candidates
    )


def validate_bam_indexes(table: pd.DataFrame, label: str) -> None:
    """CNVkit requires indexed BAMs; report all missing indexes at once."""
    missing: list[str] = []
    for row in table.to_dict(orient="records"):
        bam_path = Path(str(row["BAM"]))
        if not _bam_index_exists(bam_path):
            missing.append(str(bam_path))

    if missing:
        raise FileNotFoundError(
            f"{label}: BAM index (.bai/.csi) missing for:\n  - "
            + "\n  - ".join(missing)
        )


def resolve_existing_reference_cnn(cfg: dict) -> Path:
    """Validate an explicitly selected existing CNVkit reference."""
    value = cfg['reference_cnn']
    if _is_placeholder_cnn(value):
        raise ValueError(
            "CNVkit reference mode is 'existing', but no real .cnn file was "
            "selected. Select an existing .cnn file explicitly, or choose a "
            "reference-building mode."
        )

    reference = normalized_input_path(value)
    if (
        not reference.exists()
        or not reference.is_file()
        or reference.stat().st_size == 0
    ):
        raise FileNotFoundError(
            f"CNVkit reference CNN was not found or is empty: {reference}"
        )
    return reference


def build_cnvkit_reference(
    settings: dict,
    cfg: dict,
    output_dir: Path,
    dry_run: bool,
) -> tuple[Path, pd.DataFrame]:
    """
    Build a CNVkit reference with `cnvkit.py batch -n`.

    build_from_normals:
        pooled reference from selected validated normal/control BAMs

    build_flat:
        flat reference; `-n/--normal` is supplied without BAM filenames
    """
    mode = str(cfg['reference_mode']).strip()
    if mode not in {"build_from_normals", "build_flat"}:
        raise ValueError(f"Unsupported CNVkit reference build mode: {mode}")

    output_value = str(cfg['output_reference_cnn']).strip()
    if not output_value:
        raise ValueError(
            "Select an explicit output filename for the new CNVkit reference CNN."
        )

    output_reference = normalized_input_path(output_value)
    output_reference.parent.mkdir(parents=True, exist_ok=True)

    if (
        not dry_run
        and output_reference.exists()
        and output_reference.stat().st_size > 0
    ):
        raise FileExistsError(
            "The requested new CNVkit reference already exists. To prevent an "
            "accidental overwrite, choose 'existing' reference mode or select a "
            f"different output filename:\n{output_reference}"
        )

    fasta_value = str(settings['references']['fasta']).strip()
    if not fasta_value:
        raise ValueError(
            "Building a CNVkit reference requires the Reference FASTA selected in "
            "INPUTS AND REFERENCE (references.fasta)."
        )
    fasta = normalized_input_path(fasta_value)
    if (
        not dry_run
        and (
            not fasta.exists()
            or not fasta.is_file()
            or fasta.stat().st_size == 0
        )
    ):
        raise FileNotFoundError(
            f"CNVkit reference-build FASTA was not found or is empty: {fasta}"
        )

    method = str(cfg["method"]).strip()
    targets_value = str(cfg['targets_bed']).strip()
    targets: Path | None = None

    if method in {"hybrid", "amplicon"}:
        if not targets_value:
            raise ValueError(
                f"CNVkit method '{method}' requires a target BED when building "
                "a new reference."
            )
        targets = normalized_input_path(targets_value)
        if (
            not dry_run
            and (
                not targets.exists()
                or not targets.is_file()
                or targets.stat().st_size == 0
            )
        ):
            raise FileNotFoundError(
                f"CNVkit target/bait BED was not found or is empty: {targets}"
            )

    normals = pd.DataFrame(
        columns=["SAMPLE_ID", "BAM", "BAM_DISCOVERY"]
    )
    normal_paths: list[Path] = []

    if mode == "build_from_normals":
        normals = discover_reference_normal_bams(
            str(cfg['normal_bam_folder'])
        )
        validate_bam_indexes(
            normals,
            "CNVkit normal/control reference build",
        )
        normal_paths = [
            Path(str(value))
            for value in normals["BAM"].tolist()
        ]

    # Temporary build directory is the only automatically generated location.
    # It is deleted after a successful reference build.
    build_work = output_dir / "_TEMP_CNVKIT_REFERENCE_BUILD"
    if not dry_run:
        if build_work.exists():
            shutil.rmtree(build_work, ignore_errors=True)
        build_work.mkdir(parents=True, exist_ok=True)

    cnvkit = str(settings["tools"]["cnvkit"])
    normal_args = " ".join(quote(path) for path in normal_paths)
    male_option = (
        "--male-reference"
        if bool(cfg["male_reference"])
        else ""
    )

    command_parts = [
        f"{quote(cnvkit)} batch",
        "-n",
    ]
    if normal_args:
        command_parts.append(normal_args)

    command_parts.extend(
        [
            f"--method {quote(method)}",
            f"--fasta {quote(fasta)}",
        ]
    )

    if targets is not None:
        command_parts.append(f"--targets {quote(targets)}")

    command_parts.extend(
        [
            f"--output-reference {quote(output_reference)}",
            f"--output-dir {quote(build_work)}",
            f"--processes {threads(settings)}",
        ]
    )

    if male_option:
        command_parts.append(male_option)

    command = " ".join(command_parts)

    run_command(
        command,
        output_dir / "logs" / "cnvkit_reference_build.log",
        dry_run=dry_run,
        shell=True,
    )

    if not dry_run:
        if (
            not output_reference.exists()
            or not output_reference.is_file()
            or output_reference.stat().st_size == 0
        ):
            raise FileNotFoundError(
                "CNVkit reference-build command completed but the requested "
                f"reference CNN was not created: {output_reference}"
            )

        # Build products other than the selected CNN are temporary.
        shutil.rmtree(build_work, ignore_errors=True)

    return output_reference, normals



def chromosome_key(chromosome: str) -> tuple[int, str]:
    clean = str(chromosome).replace("chr", "")
    if clean.isdigit():
        return int(clean), ""
    return {"X": 23, "Y": 24, "M": 25, "MT": 25}.get(clean.upper(), 1000), clean



def ordinary_ratio_to_signed_copy_ratio(value: object) -> float:
    """
    Convert ordinary positive copy ratio to user-facing SIGNED_COPY_RATIO.

    R >= 1.0 -> +R
    0 < R < 1.0 -> -1/R

    Examples:
        2.00 -> +2.00
        1.20 -> +1.20
        1.00 -> +1.00
        0.80 -> -1.25
        0.50 -> -2.00
        0.25 -> -4.00

    This is not a native CNVkit metric and is not log2.
    """
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return float("nan")

    if not math.isfinite(ratio) or ratio <= 0:
        return float("nan")

    if ratio >= 1.0:
        return ratio

    return -1.0 / ratio


def copy_number_plot(
    cnr: pd.DataFrame,
    cns: pd.DataFrame,
    output: Path,
    sample_id: str,
    gain_ratio_threshold: float,
    loss_ratio_threshold: float,
) -> None:
    """
    Plot SIGNED_COPY_RATIO, not log2.

    CNVkit native log2 is converted to ordinary ratio:
        COPY_RATIO = 2**log2

    Then:
        COPY_RATIO >= 1 -> +COPY_RATIO
        COPY_RATIO < 1  -> -1/COPY_RATIO
    """
    if cnr.empty or cns.empty:
        save_placeholder_plot(
            output,
            f"{sample_id}: copy number",
            "No CNVkit bins or segments.",
        )
        return

    cnr = cnr.copy()
    cns = cns.copy()

    cnr["COPY_RATIO"] = np.power(
        2.0,
        pd.to_numeric(cnr["log2"], errors="coerce"),
    )
    cns["COPY_RATIO"] = np.power(
        2.0,
        pd.to_numeric(cns["log2"], errors="coerce"),
    )

    cnr["SIGNED_COPY_RATIO"] = [
        ordinary_ratio_to_signed_copy_ratio(value)
        for value in cnr["COPY_RATIO"]
    ]
    cns["SIGNED_COPY_RATIO"] = [
        ordinary_ratio_to_signed_copy_ratio(value)
        for value in cns["COPY_RATIO"]
    ]

    chromosomes = sorted(
        cnr["chromosome"].astype(str).unique(),
        key=chromosome_key,
    )
    offsets: dict[str, float] = {}
    centers: list[float] = []
    labels: list[str] = []
    cumulative = 0.0

    for chromosome in chromosomes:
        subset = cnr[
            cnr["chromosome"].astype(str) == chromosome
        ]
        length = float(subset["end"].max())
        offsets[chromosome] = cumulative
        centers.append(cumulative + length / 2)
        labels.append(chromosome)
        cumulative += length

    cnr["X"] = [
        offsets[str(chrom)] + (float(start_pos) + float(end_pos)) / 2
        for chrom, start_pos, end_pos in zip(
            cnr["chromosome"],
            cnr["start"],
            cnr["end"],
        )
    ]

    figure, axis = plt.subplots(figsize=(14, 6))
    axis.scatter(
        cnr["X"],
        cnr["SIGNED_COPY_RATIO"],
        s=5,
        alpha=0.45,
    )

    for segment in cns.itertuples(index=False):
        offset = offsets.get(str(segment.chromosome), 0.0)
        axis.plot(
            [
                offset + float(segment.start),
                offset + float(segment.end),
            ],
            [
                float(segment.SIGNED_COPY_RATIO),
                float(segment.SIGNED_COPY_RATIO),
            ],
            linewidth=2,
        )

    axis.axhline(1.0, linewidth=1)
    axis.axhline(-1.0, linewidth=1)
    axis.axhline(
        float(gain_ratio_threshold),
        linewidth=1,
        linestyle="--",
    )
    axis.axhline(
        float(loss_ratio_threshold),
        linewidth=1,
        linestyle="--",
    )

    axis.set_xticks(centers)
    axis.set_xticklabels(labels, rotation=60, ha="right")
    axis.set_ylabel(
        "SIGNED_COPY_RATIO (+R if R>=1; -1/R if R<1)"
    )
    axis.set_xlabel("Chromosome")
    axis.set_title(
        f"{sample_id}: CNV profile — signed non-log ratio"
    )
    axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    figure.savefig(output, dpi=180)
    plt.close(figure)



def copy_number_parameter_rows(
    settings: dict,
    effective_reference: Path | None = None,
) -> list[dict[str, object]]:
    cfg = settings["copy_number"]
    return [
        {
            "PARAMETER": "input_bam_rule",
            "VALUE": "VALIDATED_COMPLETE_BAM_ONLY",
            "EXPLANATION": (
                "Step 07 accepts only BAM filenames containing analysis_ready "
                "or validated and rejects filenames containing abnormal."
            ),
        },
        {
            "PARAMETER": "enabled",
            "VALUE": bool(cfg["enabled"]),
            "EXPLANATION": "Run or skip CNVkit copy-number analysis.",
        },
        {
            "PARAMETER": "reference_mode",
            "VALUE": str(cfg['reference_mode']),
            "EXPLANATION": (
                "existing = use a previously built CNVkit copy-number reference profile (.cnn); "
                "build_from_normals = construct a pooled assay-matched reference from validated "
                "normal/control BAMs; build_flat = construct a neutral (log2=0) reference when "
                "suitable normal samples are unavailable."
            ),
        },
        {
            "PARAMETER": "effective_reference_cnn",
            "VALUE": str(effective_reference or ""),
            "EXPLANATION": (
                "The actual CNVkit copy-number reference profile (.cnn) used for tumor/test "
                "BAM normalization. A reference .cnn stores the expected signal for genomic "
                "bins and bias/reliability information; CNN here is a CNVkit file extension, "
                "not a convolutional neural network."
            ),
        },
        {
            "PARAMETER": "method",
            "VALUE": str(cfg["method"]),
            "EXPLANATION": (
                "hybrid = hybridization capture using target and off-target "
                "information; amplicon = PCR-targeted sequencing using targets only; "
                "wgs = whole-genome sequencing using genome-wide bins."
            ),
        },
        {
            "PARAMETER": "male_reference",
            "VALUE": bool(cfg["male_reference"]),
            "EXPLANATION": (
                "CNVkit haploid-X reference convention (-y). This describes the "
                "reference baseline, not the biological sex of the current sample."
            ),
        },
        {
            "PARAMETER": "segment_method",
            "VALUE": str(cfg["segment_method"]),
            "EXPLANATION": (
                "haar = pure-Python HaarSeg segmentation; none = no merging of "
                "neighboring bins into broader CNV segments."
            ),
        },
        {
            "PARAMETER": "drop_low_coverage",
            "VALUE": bool(cfg["drop_low_coverage"]),
            "EXPLANATION": (
                "Remove very-low-coverage bins before segmentation."
            ),
        },
        {
            "PARAMETER": "gain_ratio_threshold",
            "VALUE": float(cfg["gain_ratio_threshold"]),
            "EXPLANATION": (
                "SIGNED_COPY_RATIO gain threshold. Default +1.40 corresponds to an ordinary "
                "tumor/reference copy ratio of 1.40. This custom reporting scale is not log2."
            ),
        },
        {
            "PARAMETER": "loss_ratio_threshold",
            "VALUE": float(cfg["loss_ratio_threshold"]),
            "EXPLANATION": (
                "SIGNED_COPY_RATIO loss threshold. Default -1.40 corresponds to an ordinary "
                "tumor/reference ratio of about 0.714 (1/1.40). Example -2 corresponds to "
                "ordinary ratio 0.5. This custom reporting scale is not log2."
            ),
        },
    ]



def validate_copy_number_settings(
    settings: dict,
    dry_run: bool,
) -> None:
    cfg = settings["copy_number"]

    method = str(cfg["method"]).strip()
    if method not in {"hybrid", "amplicon", "wgs"}:
        raise ValueError(
            "CNVkit method must be hybrid, amplicon, or wgs."
        )

    segment_method = str(cfg["segment_method"]).strip()
    if segment_method not in {"haar", "none"}:
        raise ValueError(
            "This pipeline supports CNVkit segment method haar or none."
        )

    reference_mode = str(
        cfg['reference_mode']
    ).strip()
    if reference_mode not in {
        "existing",
        "build_from_normals",
        "build_flat",
    }:
        raise ValueError(
            "CNVkit reference mode must be existing, build_from_normals, "
            "or build_flat."
        )

    gain = float(cfg["gain_ratio_threshold"])
    loss = float(cfg["loss_ratio_threshold"])

    if gain <= 1.0:
        raise ValueError(
            "Gain SIGNED_COPY_RATIO threshold must be > +1.0. "
            "Example: +1.20 corresponds to ordinary ratio 1.20."
        )
    if loss > -1.0:
        raise ValueError(
            "Loss SIGNED_COPY_RATIO threshold must be <= -1.0. "
            "Example: -2 corresponds to ordinary ratio 0.5."
        )

    if not bool(cfg["enabled"]):
        return

    if reference_mode == "existing":
        if not dry_run:
            resolve_existing_reference_cnn(cfg)
        elif _is_placeholder_cnn(cfg['reference_cnn']):
            raise ValueError(
                "Select a real CNVkit reference CNN or choose a reference-build mode."
            )
        return

    # Reference-build modes.
    if not str(cfg['output_reference_cnn']).strip():
        raise ValueError(
            "Select the output filename for the new CNVkit reference CNN."
        )

    if not str(settings['references']['fasta']).strip():
        raise ValueError(
            "Select the Reference FASTA in INPUTS AND REFERENCE. "
            "This value is stored as references.fasta and is required to build a CNVkit reference."
        )

    if (
        method in {"hybrid", "amplicon"}
        and not str(cfg['targets_bed']).strip()
    ):
        raise ValueError(
            f"Method '{method}' requires a target/bait BED when building "
            "a CNVkit reference."
        )

    if (
        reference_mode == "build_from_normals"
        and not str(cfg['normal_bam_folder']).strip()
    ):
        raise ValueError(
            "build_from_normals requires a selected normal/control BAM folder."
        )



def backend(
    settings_path: Path,
    input_dir: Path,
    output_dir: Path,
    dry_run: bool,
) -> None:
    settings, _ = load_config(settings_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(
        output_dir / "08_CALL_COPY_NUMBER_GAINS_AND_LOSSES.log"
    )

    enabled = bool(settings["copy_number"]["enabled"])
    require_tools(
        settings,
        ["cnvkit"],
        dry_run or not enabled,
    )

    inputs = discover_bams(input_dir, recursive=True)
    if inputs.empty:
        raise FileNotFoundError(
            "No BAM files were found in the selected Step 07 validated BAM folder."
        )

    # Strong full-BAM rule:
    # analysis_ready/validated required; abnormal forbidden.
    inputs = validate_and_filter_full_bams(
        inputs,
        "Step 07 tumor/test BAM folder",
    )
    validate_bam_indexes(
        inputs,
        "Step 07 tumor/test BAMs",
    )

    cfg = settings["copy_number"]
    validate_copy_number_settings(settings, dry_run)

    reference_mode = str(
        cfg['reference_mode']
    ).strip()

    normal_reference_bams = pd.DataFrame()
    effective_reference: Path | None = None

    if enabled:
        if reference_mode == "existing":
            effective_reference = (
                normalized_input_path(
                    cfg['reference_cnn']
                )
                if dry_run
                else resolve_existing_reference_cnn(cfg)
            )
        else:
            effective_reference, normal_reference_bams = (
                build_cnvkit_reference(
                    settings,
                    cfg,
                    output_dir,
                    dry_run,
                )
            )

    write_tsv(
        pd.DataFrame(
            copy_number_parameter_rows(
                settings,
                effective_reference,
            )
        ),
        output_dir / "copy_number_parameters_used.tsv",
    )

    if not normal_reference_bams.empty:
        write_tsv(
            normal_reference_bams,
            output_dir
            / "cnvkit_reference_normal_bams_scanned.tsv",
        )

    write_tsv(
        pd.DataFrame(
            [
                {
                    "REFERENCE_MODE": reference_mode,
                    "EFFECTIVE_REFERENCE_CNN": (
                        str(effective_reference)
                        if effective_reference is not None
                        else ""
                    ),
                    "ASSAY_METHOD": str(cfg["method"]),
                    "MALE_HAPLOID_X_REFERENCE": bool(
                        cfg["male_reference"]
                    ),
                    "NORMAL_CONTROL_BAM_COUNT": (
                        len(normal_reference_bams)
                        if not normal_reference_bams.empty
                        else 0
                    ),
                }
            ]
        ),
        output_dir / "cnvkit_reference_used.tsv",
    )

    gain_ratio = float(cfg["gain_ratio_threshold"])
    loss_ratio = float(cfg["loss_ratio_threshold"])

    output_rows: list[dict] = []
    segment_tables: list[pd.DataFrame] = []
    plots: list[Path] = []

    for row in inputs.to_dict(orient="records"):
        sample_id = str(row["SAMPLE_ID"])
        sample_dir = output_dir / sample_id
        sample_dir.mkdir(parents=True, exist_ok=True)

        bam_path = Path(str(row["BAM"]))

        updated = dict(row)
        updated["INPUT_BAM_VALIDATION"] = (
            "PASS_VALIDATED_FULL_BAM_NO_ABNORMAL"
        )
        updated["CNVKIT_REFERENCE_MODE"] = reference_mode
        updated["CNVKIT_REFERENCE_CNN"] = (
            str(effective_reference)
            if effective_reference is not None
            else ""
        )
        updated["CNVKIT_CNR"] = ""
        updated["CNVKIT_CNS"] = ""
        updated["CNVKIT_CALLED_CNS"] = ""
        updated["COPY_NUMBER_PLOT"] = ""

        if not enabled:
            output_rows.append(updated)
            continue

        if effective_reference is None:
            raise RuntimeError(
                "CNVkit is enabled but no effective reference CNN was resolved."
            )

        male_option = (
            "--male-reference"
            if bool(cfg["male_reference"])
            else ""
        )
        low_coverage_option = (
            "--drop-low-coverage"
            if bool(cfg["drop_low_coverage"])
            else ""
        )

        # IMPORTANT: discover_bams returns column BAM, not FINAL_BAM.
        command = (
            f"{quote(settings['tools']['cnvkit'])} batch "
            f"{quote(bam_path)} "
            f"--reference {quote(effective_reference)} "
            f"--output-dir {quote(sample_dir)} "
            f"--method {quote(cfg['method'])} "
            f"--segment-method {quote(cfg['segment_method'])} "
            f"--processes {threads(settings)} "
            f"{male_option} {low_coverage_option}"
        )

        run_command(
            command,
            output_dir / "logs" / f"{sample_id}.log",
            dry_run=dry_run,
            shell=True,
        )

        cnr_path = sample_dir / f"{sample_id}.cnr"
        cns_path = sample_dir / f"{sample_id}.cns"

        if not dry_run:
            cnr_candidates = sorted(sample_dir.glob("*.cnr"))
            cns_candidates = sorted(sample_dir.glob("*.cns"))
            if cnr_candidates:
                cnr_path = cnr_candidates[0]
            if cns_candidates:
                cns_path = cns_candidates[0]

        called_cns = sample_dir / f"{sample_id}.called.cns"
        call_command = (
            f"{quote(settings['tools']['cnvkit'])} call "
            f"{quote(cns_path)} "
            f"{male_option} "
            f"-o {quote(called_cns)}"
        )

        run_command(
            call_command,
            output_dir / "logs" / f"{sample_id}.log",
            dry_run=dry_run,
            shell=True,
        )

        plot_path = (
            sample_dir
            / f"{sample_id}.copy_number_profile_SIGNED_RATIO.png"
        )

        if (
            not dry_run
            and cnr_path.exists()
            and called_cns.exists()
        ):
            cnr = pd.read_csv(cnr_path, sep="\t")
            cns = pd.read_csv(called_cns, sep="\t")

            cns.insert(0, "SAMPLE_ID", sample_id)

            # CNVkit stores log2 natively. Convert once to the user-facing
            # LINEAR ratio and classify exclusively on that ratio.
            cns["COPY_RATIO"] = np.power(
                2.0,
                pd.to_numeric(
                    cns["log2"],
                    errors="coerce",
                ),
            )

            cns["SIGNED_COPY_RATIO"] = [
                ordinary_ratio_to_signed_copy_ratio(value)
                for value in cns["COPY_RATIO"]
            ]

            cns["CALL_BY_SIGNED_COPY_RATIO"] = np.where(
                cns["SIGNED_COPY_RATIO"] >= gain_ratio,
                "GAIN",
                np.where(
                    cns["SIGNED_COPY_RATIO"] <= loss_ratio,
                    "LOSS",
                    "NEUTRAL",
                ),
            )

            cns["GAIN_SIGNED_RATIO_THRESHOLD"] = gain_ratio
            cns["LOSS_SIGNED_RATIO_THRESHOLD"] = loss_ratio
            cns["RATIO_SCALE_NOTE"] = (
                "SIGNED_COPY_RATIO: +R if R>=1; -1/R if R<1; not log2"
            )

            segment_tables.append(cns)

            copy_number_plot(
                cnr,
                cns,
                plot_path,
                sample_id,
                gain_ratio,
                loss_ratio,
            )
        else:
            save_placeholder_plot(
                plot_path,
                f"{sample_id}: copy-number profile",
                "CNVkit output was not available. "
                "This is expected during dry run.",
            )

        plots.append(plot_path)

        updated["CNVKIT_CNR"] = str(cnr_path)
        updated["CNVKIT_CNS"] = str(cns_path)
        updated["CNVKIT_CALLED_CNS"] = str(called_cns)
        updated["COPY_NUMBER_PLOT"] = str(plot_path)
        updated["GAIN_SIGNED_RATIO_THRESHOLD"] = gain_ratio
        updated["LOSS_SIGNED_RATIO_THRESHOLD"] = loss_ratio
        output_rows.append(updated)

    output_manifest = pd.DataFrame(output_rows)
    segments = (
        pd.concat(segment_tables, ignore_index=True)
        if segment_tables
        else pd.DataFrame()
    )

    write_tsv(
        output_manifest,
        output_dir / "copy_number_results.tsv",
    )
    write_tsv(
        segments,
        output_dir / "copy_number_segments.tsv",
    )

    call_plot = (
        output_dir
        / "copy_number_call_counts_SIGNED_RATIO.png"
    )

    call_column = "CALL_BY_SIGNED_COPY_RATIO"
    if segments.empty or call_column not in segments.columns:
        save_placeholder_plot(
            call_plot,
            "Copy-number gain/loss calls",
            "No called CNVkit segments were available.",
        )
    else:
        counts = segments[call_column].value_counts()
        save_bar_plot(
            counts.index.astype(str).tolist(),
            counts.astype(float).tolist(),
            call_plot,
            "Copy-number segment calls — signed copy ratio",
            "Segment count",
        )

    plots.append(call_plot)

    write_step_status(
        output_dir,
        SPEC.title,
        "PASS" if enabled else "SKIP",
        (
            f"CNVkit processed {len(output_manifest)} validated/full BAM file(s) "
            "using signed non-log copy-ratio reporting."
            if enabled
            else "Copy-number analysis was disabled."
        ),
        len(output_manifest),
        plots,
    )

    print(output_dir / "copy_number_segments.tsv")



STEP_GUI = {
    'environment': 'ctdna_core',
    'section_help': {
        'INPUTS AND REFERENCE': (
            "This section defines the data and genomic baseline used for CNV analysis. CNV means "
            "Copy Number Variation: a genomic region present at a higher or lower copy number than "
            "the expected baseline. Select complete validated tumor/test BAMs, not abnormal-read-only "
            "BAMs. The reference FASTA must match the genome build used for alignment. For targeted "
            "sequencing, provide the official assay target/bait BED when available; if it is unavailable, "
            "a targeted/high-depth BED inferred in Step 04 can be used as a practical fallback. A CNVkit "
            ".cnn file is a tabular copy-number coverage/reference-profile file. CNVkit documentation "
            "uses .cnn as the file extension for bin-level coverage and reference profiles; it should not "
            "be interpreted as 'convolutional neural network'. If suitable normal/control BAMs exist, they "
            "can be used to build an assay-matched reference. If NO suitable normal/control BAMs exist, "
            "select 'build_flat' in the CNVkit options and specify where the new flat .cnn reference file "
            "should be created."
        ),
        'CNVKIT OPTIONS': (
            "CNVkit measures read depth in genomic bins, normalizes the signal against a reference, and "
            "then combines neighboring bins into larger regions that have a similar copy-number signal. "
            "REFERENCE MODE: use 'existing' if you already have an appropriate .cnn; use "
            "'build_from_normals' when suitable assay-matched normal/control BAMs are available; use "
            "'build_flat' when no suitable normal/control BAMs are available. When 'build_flat' or "
            "'build_from_normals' is selected, you MUST fill the output .cnn path so the newly created "
            "reference has a filename/location. ASSAY METHOD: hybrid = hybridization capture, amplicon = "
            "PCR-primer amplicon sequencing, wgs = whole-genome sequencing. If you know the experiment "
            "was a targeted panel but do not know whether enrichment used capture probes or PCR primers, "
            "choose 'hybrid' provisionally rather than assuming amplicon. REGION DETECTION: Haar detects "
            "changes in bin-level copy ratio and coalesces adjacent bins into candidate CNV regions; "
            "'none' is mainly a coarse/testing baseline that reports chromosome-arm-level averages. "
            "No SNP-to-phenotype clinical database is required for this step; allele-specific SNP/BAF/LOH "
            "analysis and clinical annotation belong downstream."
        ),
    },
    'fields': [
        {
            'setting': '__input_dir__',
            'label': 'Validated/full BAM folder',
            'type': 'folder',
            'required': True,
            'scan_globs': ['*.bam'],
            'accept_name_contains_any': ['analysis_ready', 'validated'],
            'reject_name_contains': ['abnormal', 'aberrant'],
            'section': 'INPUTS AND REFERENCE',
            'help': (
                "Folder containing the complete analysis-ready tumor/test BAM files. CNVkit needs "
                "genome/target-wide depth information, so do not use BAMs containing only abnormal, "
                "discordant, or breakpoint-supporting reads. BAM index files (.bai) should be present."
            ),
        },
        {
            'setting': 'references.fasta',
            'label': 'Reference FASTA',
            'type': 'file',
            'required': True,
            'allowed_suffixes': ['.fa', '.fasta', '.fna'],
            'filetypes': [('FASTA', '*.fa *.fasta *.fna'), ('All files', '*.*')],
            'button_text': 'Browse reference FASTA',
            'section': 'INPUTS AND REFERENCE',
            'help': (
                "Genome FASTA corresponding to the BAM alignment build (for example GRCh38). CNVkit "
                "uses the FASTA when building references to calculate sequence-related bias information "
                "such as GC content."
            ),
        },
        {
            'setting': 'copy_number.normal_bam_folder',
            'label': 'Optional normal BAM folder for building CNVkit reference',
            'type': 'folder',
            'required': False,
            'scan_globs': ['*.bam'],
            'accept_name_contains_any': ['analysis_ready', 'validated'],
            'reject_name_contains': ['abnormal', 'aberrant'],
            'section': 'INPUTS AND REFERENCE',
            'help': (
                "Used only with reference mode 'build_from_normals'. Prefer normal/control samples "
                "generated with the same capture panel or WGS protocol, library preparation, genome "
                "build, and broadly comparable sequencing conditions as the tumor/test samples."
            ),
        },
        {
            'setting': 'copy_number.reference_cnn',
            'label': 'Optional existing CNVkit reference CNN (.cnn)',
            'type': 'file',
            'required': False,
            'allowed_suffixes': ['.cnn'],
            'filetypes': [('CNVkit reference', '*.cnn'), ('All files', '*.*')],
            'button_text': 'Browse reference CNN',
            'section': 'INPUTS AND REFERENCE',
            'help': (
                "Used only with reference mode 'existing'. CNV = Copy Number Variation. A CNVkit .cnn "
                "reference is a tabular copy-number reference profile containing the expected normalized "
                "signal for genomic bins plus bias/reliability information (for example GC content, "
                "RepeatMasker fraction and spread when available). CNVkit uses .cnn as the extension for "
                "coverage/reference-profile tables; it does NOT mean a convolutional neural network. "
                "Reuse the same appropriate reference across samples from the same assay/project when possible."
            ),
        },
        {
            'setting': 'copy_number.targets_bed',
            'label': 'Optional targeted BED (required for hybrid/amplicon)',
            'type': 'file',
            'required': False,
            'allowed_suffixes': ['.bed'],
            'filetypes': [('BED', '*.bed'), ('All files', '*.*')],
            'button_text': 'Browse target BED',
            'section': 'INPUTS AND REFERENCE',
            'help': (
                "Genomic intervals expected to have reliable assay coverage. For hybrid capture, the "
                "manufacturer's bait/capture BED is preferred; for amplicon sequencing, use the assay "
                "target BED. If an official BED is not available, a targeted/high-depth BED can be "
                "inferred/generated from covered high-depth regions in Step 04 and selected here. "
                "Whole-genome sequencing (WGS) does not require this BED."
            ),
        },
        {
            'setting': 'copy_number.reference_mode',
            'label': 'CNVkit reference mode / copy-number baseline',
            'type': 'choice',
            'required': True,
            'section': 'CNVKIT OPTIONS',
            'choices': ['existing', 'build_from_normals', 'build_flat'],
            'choice_values': {
                'existing': 'existing',
                'build_from_normals': 'build_from_normals',
                'build_flat': 'build_flat',
            },
            'help': (
                "CNV = Copy Number Variation. This option defines the baseline used to decide whether "
                "coverage is increased or decreased. existing = use a previously built assay-appropriate "
                ".cnn reference. build_from_normals = create a pooled .cnn from suitable normal/control "
                "BAMs. build_flat = create a neutral reference (expected log2 copy ratio 0 for each bin). "
                "IMPORTANT: if you have NO suitable normal/control BAMs, 'build_flat' is the appropriate "
                "mode. A flat reference is a practical fallback, although subtle CNVs are less reliable "
                "than with a good assay-matched normal reference."
            ),
        },
        {
            'setting': 'copy_number.method',
            'label': 'Assay method / target-enrichment design',
            'type': 'choice',
            'required': True,
            'section': 'CNVKIT OPTIONS',
            'choices': ['hybrid', 'amplicon', 'wgs'],
            'choice_values': {'hybrid': 'hybrid', 'amplicon': 'amplicon', 'wgs': 'wgs'},
            'help': (
                "Select how genomic DNA was enriched/sequenced, NOT the sequencer brand. hybrid = "
                "hybridization-capture targeted sequencing using capture probes/baits; CNVkit can use "
                "both target and off-target coverage. amplicon = PCR-primer targeted sequencing; analysis "
                "is concentrated on the amplified target intervals. wgs = whole-genome sequencing using "
                "genome-wide bins; a target BED is generally not required. If you only know that the "
                "experiment used a TARGETED PANEL but do not know whether it used hybridization probes "
                "or PCR primers, choose 'hybrid' provisionally rather than guessing 'amplicon'."
            ),
        },
        {
            'setting': 'copy_number.output_reference_cnn',
            'label': 'Output CNVkit reference (.cnn) — REQUIRED when building',
            'type': 'save_file',
            'required': False,
            'allowed_suffixes': ['.cnn'],
            'filetypes': [('CNVkit reference', '*.cnn'), ('All files', '*.*')],
            'button_text': 'Choose save path',
            'title': 'Choose where to save the new CNVkit reference (.cnn)',
            'default_filename': 'GRCh38_flat_reference.cnn',
            'default_extension': '.cnn',
            'section': 'CNVKIT OPTIONS',
            'help': (
                "Leave this empty only when reference mode = 'existing'. If reference mode = "
                "'build_flat' or 'build_from_normals', you MUST choose where the NEW reference "
                "will be created. Click 'Choose save path', select a folder, and enter a filename "
                "such as GRCh38_flat_reference.cnn. The selected file does not need to exist yet; "
                "Step 08 creates it. The program then uses this .cnn copy-number reference profile "
                "as the normalization baseline."
            ),
        },
        {
            'setting': 'copy_number.segment_method',
            'label': 'Bin coalescence optimisation for CNV region detection',
            'type': 'choice',
            'required': True,
            'section': 'CNVKIT OPTIONS',
            'choices': ['haar', 'none'],
            'choice_values': {'haar': 'haar', 'none': 'none'},
            'help': (
                "This step starts with many small genomic bins. Region detection asks where the copy-ratio "
                "signal changes, then coalesces adjacent bins with similar signal into larger candidate CNV "
                "regions. haar = HaarSeg, a fast wavelet-based change-point method; it is a sensible choice "
                "for targeted panels and is the recommended routine option in this pipeline. none = do not "
                "search for local change-points; CNVkit instead reports coarse weighted chromosome-arm-level "
                "averages. Use 'none' mainly for testing/debugging or a very coarse baseline, not for routine "
                "focal CNV-region detection."
            ),
        },
        {
            'setting': 'copy_number.male_reference',
            'label': 'Use haploid-X/male reference convention',
            'type': 'bool',
            'section': 'CNVKIT OPTIONS',
            'help': (
                "Controls CNVkit's sex-chromosome baseline convention for the REFERENCE. Enable it when "
                "the CNVkit reference was constructed using the male/haploid-X convention. This setting "
                "describes the reference baseline; it is not simply a checkbox for the current patient's sex."
            ),
        },
        {
            'setting': 'copy_number.drop_low_coverage',
            'label': 'Drop low-coverage bins',
            'type': 'bool',
            'section': 'CNVKIT OPTIONS',
            'help': (
                "Remove bins with zero or extremely low read depth before segmentation. This can reduce "
                "artifacts from poorly covered regions, but aggressive removal can also reduce usable "
                "information in very low-depth ctDNA data."
            ),
        },
        {
            'setting': 'copy_number.gain_ratio_threshold',
            'label': 'SIGNED_COPY_RATIO gain threshold',
            'type': 'float',
            'required': True,
            'section': 'CNVKIT OPTIONS',
            'help': (
                "Default = +1.40. This pipeline converts CNVkit log2 values to an ordinary copy ratio R. "
                "For R >= 1, SIGNED_COPY_RATIO = +R, so +1.40 means tumor/test coverage is approximately "
                "1.40 times the reference expectation. This threshold is a reporting/calling cutoff in "
                "this pipeline, not a CNVkit log2 threshold."
            ),
        },
        {
            'setting': 'copy_number.loss_ratio_threshold',
            'label': 'SIGNED_COPY_RATIO loss threshold',
            'type': 'float',
            'required': True,
            'section': 'CNVKIT OPTIONS',
            'help': (
                "Default = -1.40. For an ordinary ratio R < 1, this pipeline reports "
                "SIGNED_COPY_RATIO = -1/R. Therefore -1.40 corresponds to R approximately 0.714. "
                "For comparison, -2.0 corresponds to an ordinary ratio of 0.50. This custom signed "
                "scale makes gains positive and losses negative while avoiding values between -1 and +1."
            ),
        },
    ],
    'explanation': (
        "Step 08 calls copy-number gains and losses with CNVkit from complete validated BAMs. CNVkit "
        "measures read depth in genomic bins, normalizes it against a copy-number reference profile, "
        "corrects systematic coverage biases, and segments the resulting signal into copy-number regions. "
        "For targeted sequencing, provide the assay BED (or a high-depth target BED inferred in Step 04); "
        "for WGS, a target BED is not required. CNV means Copy Number Variation. A CNVkit .cnn file is a "
        "tabular copy-number coverage/reference profile, not a convolutional neural network. If no suitable "
        "normal/control BAMs exist, select build_flat and provide an output .cnn path for the new flat "
        "reference. If the data are known to be a targeted panel but hybrid-capture versus PCR-amplicon "
        "enrichment is unknown, select hybrid provisionally. Haar region detection coalesces neighboring "
        "bins into candidate CNV regions; none gives coarse chromosome-arm averages. This step does not "
        "require a clinical SNP/phenotype database; clinical interpretation and allele-specific SNP analysis "
        "are separate downstream tasks."
    ),
}


if __name__ == "__main__":
    launch_step(SPEC, backend)
