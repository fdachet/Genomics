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
    parser.add_argument('--references-targets-bed', dest='__cfg__references__targets_bed', type=str, default='', help='Override references.targets_bed for this execution.')
    parser.add_argument('--bam-qc-minimum-mapping-quality', dest='__cfg__bam_qc__minimum_mapping_quality', type=int, default=20, help='Override bam_qc.minimum_mapping_quality for this execution.')
    parser.add_argument('--bam-qc-minimum-base-quality', dest='__cfg__bam_qc__minimum_base_quality', type=int, default=20, help='Override bam_qc.minimum_base_quality for this execution.')
    parser.add_argument('--bam-qc-fragment-minimum-length', dest='__cfg__bam_qc__fragment_minimum_length', type=int, default=30, help='Override bam_qc.fragment_minimum_length for this execution.')
    parser.add_argument('--bam-qc-fragment-maximum-length', dest='__cfg__bam_qc__fragment_maximum_length', type=int, default=800, help='Override bam_qc.fragment_maximum_length for this execution.')
    parser.add_argument('--bam-qc-short-fragment-maximum', dest='__cfg__bam_qc__short_fragment_maximum', type=int, default=150, help='Override bam_qc.short_fragment_maximum for this execution.')
    parser.add_argument('--bam-qc-mononucleosome-minimum', dest='__cfg__bam_qc__mononucleosome_minimum', type=int, default=151, help='Override bam_qc.mononucleosome_minimum for this execution.')
    parser.add_argument('--bam-qc-mononucleosome-maximum', dest='__cfg__bam_qc__mononucleosome_maximum', type=int, default=220, help='Override bam_qc.mononucleosome_maximum for this execution.')
    parser.add_argument('--bam-qc-maximum-fragments-to-analyze', dest='__cfg__bam_qc__maximum_fragments_to_analyze', type=int, default=2000000, help='Override bam_qc.maximum_fragments_to_analyze for this execution.')
    parser.add_argument('--bam-qc-genome-bin-depth-enabled', dest='__cfg__bam_qc__genome_bin_depth_enabled', type=_parse_cli_bool, default=False, help='Override bam_qc.genome_bin_depth_enabled for this execution.')
    parser.add_argument('--bam-qc-genome-bin-size-bp', dest='__cfg__bam_qc__genome_bin_size_bp', type=int, default=100000, help='Override bam_qc.genome_bin_size_bp for this execution.')
    parser.add_argument('--bam-qc-infer-high-depth-regions-enabled', dest='__cfg__bam_qc__infer_high_depth_regions_enabled', type=_parse_cli_bool, default=True, help='Override bam_qc.infer_high_depth_regions_enabled for this execution.')
    parser.add_argument('--bam-qc-high-depth-threshold', dest='__cfg__bam_qc__high_depth_threshold', type=int, default=10, help='Override bam_qc.high_depth_threshold for this execution.')
    parser.add_argument('--bam-qc-high-depth-minimum-region-length-bp', dest='__cfg__bam_qc__high_depth_minimum_region_length_bp', type=int, default=20, help='Override bam_qc.high_depth_minimum_region_length_bp for this execution.')
    parser.add_argument('--bam-qc-high-depth-maximum-merge-gap-bp', dest='__cfg__bam_qc__high_depth_maximum_merge_gap_bp', type=int, default=5, help='Override bam_qc.high_depth_maximum_merge_gap_bp for this execution.')
    parser.add_argument('--bam-qc-high-depth-consensus-enabled', dest='__cfg__bam_qc__high_depth_consensus_enabled', type=_parse_cli_bool, default=True, help='Override bam_qc.high_depth_consensus_enabled for this execution.')
    parser.add_argument('--bam-qc-high-depth-consensus-minimum-sample-percent', dest='__cfg__bam_qc__high_depth_consensus_minimum_sample_percent', type=float, default=50.0, help='Override bam_qc.high_depth_consensus_minimum_sample_percent for this execution.')
    parser.add_argument('--bam-qc-fragment-log-count-plot-enabled', dest='__cfg__bam_qc__fragment_log_count_plot_enabled', type=_parse_cli_bool, default=False, help='Override bam_qc.fragment_log_count_plot_enabled for this execution.')
    parser.add_argument('--bam-qc-fragment-log-plot-xmin-bp', dest='__cfg__bam_qc__fragment_log_plot_xmin_bp', type=int, default=20, help='Override bam_qc.fragment_log_plot_xmin_bp for this execution.')
    parser.add_argument('--bam-qc-fragment-log-plot-xmax-bp', dest='__cfg__bam_qc__fragment_log_plot_xmax_bp', type=int, default=500, help='Override bam_qc.fragment_log_plot_xmax_bp for this execution.')
    parser.add_argument('--bam-qc-fragment-log-plot-minor-tick-bp', dest='__cfg__bam_qc__fragment_log_plot_minor_tick_bp', type=int, default=5, help='Override bam_qc.fragment_log_plot_minor_tick_bp for this execution.')
    parser.add_argument('--bam-qc-fragment-log-plot-reference-bp', dest='__cfg__bam_qc__fragment_log_plot_reference_bp', type=int, default=166, help='Override bam_qc.fragment_log_plot_reference_bp for this execution.')
    return parser



DEFAULT_SETTINGS = {'project': {'name': 'ctDNA_Tumor_Genome_GUI_Pipeline', 'temporary_directory': 'work/tmp'},
 'execution': {'wsl_distribution': '',
               'micromamba_environment': 'ctdna_core',
               'python_executable_in_wsl': 'python3',
               'micromamba_executable': '',
               'micromamba_root_prefix': ''},
 'references': {'fasta': '',
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
 'bam_qc': {},
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
            else:
                entry=ttk.Entry(row,textvariable=var)
                entry.pack(side="left",fill="x",expand=True,padx=(4,6))

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


from collections import Counter
import math
import subprocess
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
import pandas as pd

try:
    import pysam
except ModuleNotFoundError:
    pysam = None



SPEC = StepSpecification(
    number=4,
    title="04_BAM_MAPPING_AND_FRAGMENT_QC",
    description=(
        "Browse/scan BAM files directly, validate coordinate sorting, create "
        "missing BAM indexes automatically, and measure depth, mapping evidence, "
        "cfDNA fragment lengths, soft clipping, supplementary alignments, "
        "discordant-pair fractions, optional fixed-width genome-bin depth, "
        "and memory-safe inference of probable high-depth targeted regions as BED."
    ),
    default_input_dir="input",
    default_output_dir="output",
)



def bai_candidates(bam_path: Path) -> list[Path]:
    """
    Return both common BAI naming conventions.

    samtools normally creates:
        sample.bam.bai

    Some software instead uses:
        sample.bai
    """
    candidates = [
        Path(str(bam_path) + ".bai"),
        bam_path.with_suffix(".bai"),
    ]
    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def find_existing_bai(bam_path: Path) -> Path | None:
    for candidate in bai_candidates(bam_path):
        if candidate.exists() and candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


def bam_header_sort_order(bam_path: Path) -> str:
    """
    Read the BAM @HD SO tag.

    Step 04 requires coordinate-sorted BAM files because the analysis-ready
    BAMs are expected to be coordinate sorted and indexed.
    """
    if pysam is None:
        raise ModuleNotFoundError("pysam is required in the WSL1 backend.")

    with pysam.AlignmentFile(bam_path, "rb") as bam:
        header = bam.header.to_dict()
    return str(header.get("HD", {}).get("SO", "unknown")).strip().lower()


def ensure_bam_ready_for_qc(
    bam_path: Path,
    settings: dict,
    log_file: Path,
    dry_run: bool,
) -> dict[str, object]:
    """
    Validate one BAM before QC.

    Checks:
      1. BAM passes `samtools quickcheck`.
      2. BAM header declares SO:coordinate.
      3. A usable .bai exists.
      4. If .bai is missing or older than the BAM, recreate it automatically.

    The BAM itself is never rewritten by Step 04. If it is not coordinate
    sorted, the run stops with a clear error instead of silently sorting a
    different file.
    """
    samtools = str(settings["tools"]["samtools"])
    n_threads = threads(settings)

    if not dry_run and (not bam_path.exists() or not bam_path.is_file()):
        raise FileNotFoundError(f"BAM file not found: {bam_path}")

    # Quick structural/truncation check.
    run_command(
        [samtools, "quickcheck", "-v", str(bam_path)],
        log_file,
        dry_run=dry_run,
    )

    if dry_run:
        sort_order = "DRY_RUN"
        index_before = find_existing_bai(bam_path)
        return {
            "BAM": str(bam_path),
            "QUICKCHECK": "DRY_RUN",
            "SORT_ORDER": sort_order,
            "COORDINATE_SORTED": "DRY_RUN",
            "BAI_STATUS": "DRY_RUN",
            "BAI": str(index_before) if index_before else "",
        }

    sort_order = bam_header_sort_order(bam_path)
    if sort_order != "coordinate":
        raise ValueError(
            f"BAM is not declared coordinate-sorted: {bam_path}\n"
            f"@HD SO value = {sort_order!r}.\n"
            "Step 04 does not silently reorder the BAM. Coordinate-sort it "
            "first (for example with samtools sort), then run Step 04 again."
        )

    existing_bai = find_existing_bai(bam_path)
    if existing_bai is None:
        bai_status = "CREATED_MISSING"
        run_command(
            [samtools, "index", "-@", str(n_threads), str(bam_path)],
            log_file,
            dry_run=False,
        )
    elif existing_bai.stat().st_mtime < bam_path.stat().st_mtime:
        # A BAM newer than its index can make region queries unreliable.
        bai_status = "REBUILT_STALE"
        run_command(
            [samtools, "index", "-@", str(n_threads), str(bam_path)],
            log_file,
            dry_run=False,
        )
    else:
        bai_status = "EXISTING_CURRENT"

    final_bai = find_existing_bai(bam_path)
    if final_bai is None:
        raise FileNotFoundError(
            f"samtools index completed but no .bai could be found for: {bam_path}"
        )

    # Confirm that samtools can actually use the BAM index.
    run_command(
        [samtools, "idxstats", str(bam_path)],
        log_file,
        dry_run=False,
    )

    return {
        "BAM": str(bam_path),
        "QUICKCHECK": "PASS",
        "SORT_ORDER": sort_order,
        "COORDINATE_SORTED": "YES",
        "BAI_STATUS": bai_status,
        "BAI": str(final_bai),
    }


def scan_bam(bam_path: Path, settings: dict) -> tuple[list[int], dict[str, float]]:
    if pysam is None:
        raise ModuleNotFoundError("pysam is required in the WSL1 backend.")
    qc = settings["bam_qc"]
    lengths: list[int] = []
    total = mapped = supplementary = soft_clipped = discordant = 0
    maximum_fragments = int(qc["maximum_fragments_to_analyze"])

    with pysam.AlignmentFile(bam_path, "rb") as bam:
        for read in bam.fetch(until_eof=True):
            total += 1
            if not read.is_unmapped:
                mapped += 1
            if read.is_supplementary:
                supplementary += 1
            cigar = read.cigartuples or []
            if any(operation == 4 and length >= 10 for operation, length in cigar):
                soft_clipped += 1
            if (
                read.is_paired
                and not read.is_unmapped
                and not read.mate_is_unmapped
                and (
                    read.reference_id != read.next_reference_id
                    or not read.is_proper_pair
                )
            ):
                discordant += 1
            if (
                len(lengths) < maximum_fragments
                and read.is_paired
                and read.is_read1
                and not read.is_unmapped
                and not read.mate_is_unmapped
                and not read.is_secondary
                and not read.is_supplementary
                and not read.is_duplicate
                and read.mapping_quality >= int(qc["minimum_mapping_quality"])
            ):
                length = abs(int(read.template_length))
                if (
                    int(qc["fragment_minimum_length"])
                    <= length
                    <= int(qc["fragment_maximum_length"])
                ):
                    lengths.append(length)

    return lengths, {
        "TOTAL_ALIGNMENT_RECORDS": total,
        "MAPPED_RECORDS": mapped,
        "SUPPLEMENTARY_PERCENT": 100.0 * supplementary / total if total else float("nan"),
        "SOFT_CLIPPED_PERCENT": 100.0 * soft_clipped / total if total else float("nan"),
        "DISCORDANT_RECORD_PERCENT": 100.0 * discordant / total if total else float("nan"),
    }


def _bam_reference_lengths(bam_path: Path) -> dict[str, int]:
    """Return reference/contig lengths from the BAM header."""
    if pysam is None:
        raise ModuleNotFoundError("pysam is required in the WSL1 backend.")

    with pysam.AlignmentFile(bam_path, "rb") as bam:
        return {
            str(name): int(length)
            for name, length in zip(bam.references, bam.lengths)
        }


def _merged_bed_length(
    bed_path: Path,
    reference_lengths: dict[str, int],
) -> tuple[int, int, int]:
    """
    Calculate the number of unique reference bases represented by a BED.

    BED intervals are treated as 0-based half-open coordinates. Overlapping
    intervals are merged so target bases are counted exactly once.

    Returns:
        (total_target_bases, valid_interval_count, skipped_interval_count)
    """
    intervals_by_chrom: dict[str, list[tuple[int, int]]] = {}
    valid = 0
    skipped = 0

    with bed_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith(("#", "track", "browser")):
                continue

            fields = line.split("\t")
            if len(fields) < 3:
                fields = line.split()
            if len(fields) < 3:
                skipped += 1
                continue

            chrom = fields[0]
            if chrom not in reference_lengths:
                skipped += 1
                continue

            try:
                start = int(fields[1])
                stop = int(fields[2])
            except ValueError:
                skipped += 1
                continue

            contig_length = reference_lengths[chrom]
            start = max(0, min(start, contig_length))
            stop = max(0, min(stop, contig_length))

            if stop <= start:
                skipped += 1
                continue

            intervals_by_chrom.setdefault(chrom, []).append((start, stop))
            valid += 1

    total = 0
    for intervals in intervals_by_chrom.values():
        intervals.sort()
        current_start, current_stop = intervals[0]

        for start, stop in intervals[1:]:
            if start <= current_stop:
                current_stop = max(current_stop, stop)
            else:
                total += current_stop - current_start
                current_start, current_stop = start, stop

        total += current_stop - current_start

    return total, valid, skipped


def _median_from_histogram(
    histogram: Counter,
    total_positions: int,
) -> float:
    """Exact median from a depth-frequency histogram."""
    if total_positions <= 0:
        return float("nan")

    # 0-based ranks of the middle observation(s).
    left_rank = (total_positions - 1) // 2
    right_rank = total_positions // 2

    cumulative = 0
    left_value = None
    right_value = None

    for depth in sorted(histogram):
        cumulative += int(histogram[depth])

        if left_value is None and cumulative > left_rank:
            left_value = float(depth)

        if cumulative > right_rank:
            right_value = float(depth)
            break

    if left_value is None or right_value is None:
        return float("nan")

    return (left_value + right_value) / 2.0




def _threshold_token(depth_threshold: int) -> str:
    return f"ge{int(depth_threshold)}x"


class HighDepthRegionWriter:
    """
    Stream high-depth genomic positions into merged BED regions without storing
    per-base coverage in memory.

    A position qualifies when depth >= threshold. Neighboring qualifying
    positions can be bridged across up to `maximum_merge_gap_bp` intervening
    bases below threshold. Therefore:
        maximum_merge_gap_bp = 0
    gives strictly contiguous threshold-passing bases.

    The BED itself is BED3 (0-based, half-open) for broad downstream
    compatibility. A companion TSV records the corresponding 1-based
    coordinates and QC statistics.
    """

    def __init__(
        self,
        sample_id: str,
        sample_dir: Path,
        threshold: int,
        minimum_region_length_bp: int,
        maximum_merge_gap_bp: int,
        total_reference_bp: int,
        dry_run: bool = False,
    ) -> None:
        self.sample_id = str(sample_id)
        self.sample_dir = sample_dir
        self.threshold = int(threshold)
        self.minimum_region_length_bp = int(minimum_region_length_bp)
        self.maximum_merge_gap_bp = int(maximum_merge_gap_bp)
        self.total_reference_bp = int(total_reference_bp)
        self.dry_run = bool(dry_run)

        token = _threshold_token(self.threshold)
        self.bed_path = (
            sample_dir
            / f"{self.sample_id}.inferred_high_depth_regions.{token}.bed"
        )
        self.tsv_path = (
            sample_dir
            / f"{self.sample_id}.inferred_high_depth_regions.{token}.tsv"
        )
        self.summary_path = (
            sample_dir
            / f"{self.sample_id}.inferred_high_depth_summary.tsv"
        )
        self.length_plot = (
            sample_dir
            / f"{self.sample_id}.inferred_high_depth_region_lengths.png"
        )
        self.depth_plot = (
            sample_dir
            / f"{self.sample_id}.inferred_high_depth_region_depths.png"
        )

        self.current_chrom: str | None = None
        self.current_start = 0
        self.current_end = 0
        self.current_passing_bases = 0
        self.current_depth_sum = 0
        self.current_min_depth = 0
        self.current_max_depth = 0

        self.region_count = 0
        self.total_inferred_region_bp = 0
        self.total_threshold_passing_bases = 0
        self.region_length_histogram: Counter = Counter()
        self.region_mean_depth_histogram: Counter = Counter()

        sample_dir.mkdir(parents=True, exist_ok=True)
        self._bed_handle = None
        self._tsv_handle = None

        if self.dry_run:
            self.bed_path.write_text("", encoding="utf-8")
            write_tsv(
                pd.DataFrame(
                    columns=[
                        "SAMPLE_ID",
                        "REGION_ID",
                        "CHROM",
                        "BED_START_0BASED",
                        "BED_END_0BASED_EXCLUSIVE",
                        "START_1BASED",
                        "END_1BASED",
                        "REGION_LENGTH_BP",
                        "HIGH_DEPTH_BASE_COUNT",
                        "HIGH_DEPTH_BASE_FRACTION",
                        "MIN_DEPTH_AT_PASSING_BASES",
                        "MEAN_DEPTH_AT_PASSING_BASES",
                        "MAX_DEPTH_AT_PASSING_BASES",
                        "DEPTH_THRESHOLD_X",
                        "MAXIMUM_MERGED_GAP_BP",
                    ]
                ),
                self.tsv_path,
            )
        else:
            self._bed_handle = self.bed_path.open(
                "w",
                encoding="utf-8",
                newline="\n",
            )
            self._tsv_handle = self.tsv_path.open(
                "w",
                encoding="utf-8",
                newline="\n",
            )
            self._tsv_handle.write(
                "\t".join(
                    [
                        "SAMPLE_ID",
                        "REGION_ID",
                        "CHROM",
                        "BED_START_0BASED",
                        "BED_END_0BASED_EXCLUSIVE",
                        "START_1BASED",
                        "END_1BASED",
                        "REGION_LENGTH_BP",
                        "HIGH_DEPTH_BASE_COUNT",
                        "HIGH_DEPTH_BASE_FRACTION",
                        "MIN_DEPTH_AT_PASSING_BASES",
                        "MEAN_DEPTH_AT_PASSING_BASES",
                        "MAX_DEPTH_AT_PASSING_BASES",
                        "DEPTH_THRESHOLD_X",
                        "MAXIMUM_MERGED_GAP_BP",
                    ]
                )
                + "\n"
            )

    def _start_region(self, chrom: str, position: int, depth: int) -> None:
        self.current_chrom = chrom
        self.current_start = int(position)
        self.current_end = int(position)
        self.current_passing_bases = 1
        self.current_depth_sum = int(depth)
        self.current_min_depth = int(depth)
        self.current_max_depth = int(depth)

    def _clear_current(self) -> None:
        self.current_chrom = None
        self.current_start = 0
        self.current_end = 0
        self.current_passing_bases = 0
        self.current_depth_sum = 0
        self.current_min_depth = 0
        self.current_max_depth = 0

    def _finalize_current(self) -> None:
        if self.current_chrom is None:
            return

        region_length = self.current_end - self.current_start + 1
        if region_length >= self.minimum_region_length_bp:
            self.region_count += 1
            region_id = (
                f"{self.sample_id}_HIGH_DEPTH_"
                f"{self.current_chrom}_{self.current_start}_{self.current_end}"
            )
            bed_start = self.current_start - 1
            bed_end = self.current_end
            passing_fraction = (
                self.current_passing_bases / region_length
                if region_length > 0
                else float("nan")
            )
            mean_passing_depth = (
                self.current_depth_sum / self.current_passing_bases
                if self.current_passing_bases > 0
                else float("nan")
            )

            if self._bed_handle is not None:
                self._bed_handle.write(
                    f"{self.current_chrom}\t{bed_start}\t{bed_end}\n"
                )

            if self._tsv_handle is not None:
                values = [
                    self.sample_id,
                    region_id,
                    self.current_chrom,
                    bed_start,
                    bed_end,
                    self.current_start,
                    self.current_end,
                    region_length,
                    self.current_passing_bases,
                    passing_fraction,
                    self.current_min_depth,
                    mean_passing_depth,
                    self.current_max_depth,
                    self.threshold,
                    self.maximum_merge_gap_bp,
                ]
                self._tsv_handle.write(
                    "\t".join(str(value) for value in values) + "\n"
                )

            self.total_inferred_region_bp += region_length
            self.total_threshold_passing_bases += self.current_passing_bases
            self.region_length_histogram[int(region_length)] += 1
            self.region_mean_depth_histogram[
                int(round(mean_passing_depth))
            ] += 1

        self._clear_current()

    def consume(self, chrom: str, position_1based: int, depth: int) -> None:
        if self.dry_run:
            return

        chrom = str(chrom)
        position_1based = int(position_1based)
        depth = int(depth)

        if (
            self.current_chrom is not None
            and chrom != self.current_chrom
        ):
            self._finalize_current()

        if depth < self.threshold:
            return

        if self.current_chrom is None:
            self._start_region(chrom, position_1based, depth)
            return

        intervening_bases = position_1based - self.current_end - 1
        if (
            chrom == self.current_chrom
            and intervening_bases <= self.maximum_merge_gap_bp
        ):
            self.current_end = position_1based
            self.current_passing_bases += 1
            self.current_depth_sum += depth
            self.current_min_depth = min(self.current_min_depth, depth)
            self.current_max_depth = max(self.current_max_depth, depth)
            return

        self._finalize_current()
        self._start_region(chrom, position_1based, depth)

    def _weighted_histogram_plot(
        self,
        histogram: Counter,
        output_path: Path,
        title: str,
        x_label: str,
        log_x: bool = False,
    ) -> None:
        if not histogram:
            save_placeholder_plot(
                output_path,
                title,
                "No inferred high-depth regions passed the selected filters.",
            )
            return

        values = sorted(int(value) for value in histogram)
        weights = [int(histogram[value]) for value in values]
        bins = min(50, max(10, int(math.sqrt(sum(weights))) + 1))

        figure, axis = plt.subplots(figsize=(10, 6))
        axis.hist(values, bins=bins, weights=weights)
        if log_x and max(values) > 100:
            axis.set_xscale("log")
        axis.set_xlabel(x_label)
        axis.set_ylabel("Inferred region count")
        axis.set_title(title)
        axis.grid(axis="y", alpha=0.25)
        figure.tight_layout()
        figure.savefig(output_path, dpi=180)
        plt.close(figure)

    def finish(self) -> tuple[Path, Path, Path, Path, Path, dict[str, object]]:
        if not self.dry_run:
            self._finalize_current()

        if self._bed_handle is not None:
            self._bed_handle.close()
            self._bed_handle = None
        if self._tsv_handle is not None:
            self._tsv_handle.close()
            self._tsv_handle = None

        inferred_percent = (
            100.0 * self.total_inferred_region_bp / self.total_reference_bp
            if self.total_reference_bp > 0
            else float("nan")
        )
        passing_percent = (
            100.0 * self.total_threshold_passing_bases / self.total_reference_bp
            if self.total_reference_bp > 0
            else float("nan")
        )

        summary = {
            "SAMPLE_ID": self.sample_id,
            "DEPTH_THRESHOLD_X": self.threshold,
            "THRESHOLD_RULE": f"DEPTH >= {self.threshold}",
            "MINIMUM_REGION_LENGTH_BP": self.minimum_region_length_bp,
            "MAXIMUM_MERGED_GAP_BP": self.maximum_merge_gap_bp,
            "TOTAL_REFERENCE_BP": self.total_reference_bp,
            "INFERRED_REGION_COUNT": self.region_count,
            "TOTAL_INFERRED_REGION_BP": self.total_inferred_region_bp,
            "INFERRED_REGION_PERCENT_OF_REFERENCE": inferred_percent,
            "THRESHOLD_PASSING_BASES": self.total_threshold_passing_bases,
            "THRESHOLD_PASSING_BASE_PERCENT_OF_REFERENCE": passing_percent,
            "BED_COORDINATE_SYSTEM": "0-based half-open",
            "INTERPRETATION": (
                "Empirically inferred high-coverage regions; not necessarily "
                "identical to the manufacturer's capture/bait design."
            ),
            "BED_FILE": str(self.bed_path),
            "DETAIL_TSV": str(self.tsv_path),
        }
        write_tsv(pd.DataFrame([summary]), self.summary_path)

        if self.dry_run:
            save_placeholder_plot(
                self.length_plot,
                f"{self.sample_id}: inferred high-depth region lengths",
                "Dry run: no depth calculation was executed.",
            )
            save_placeholder_plot(
                self.depth_plot,
                f"{self.sample_id}: inferred high-depth region depth",
                "Dry run: no depth calculation was executed.",
            )
        else:
            self._weighted_histogram_plot(
                self.region_length_histogram,
                self.length_plot,
                f"{self.sample_id}: inferred high-depth region lengths",
                "Region length (bp)",
                log_x=True,
            )
            self._weighted_histogram_plot(
                self.region_mean_depth_histogram,
                self.depth_plot,
                f"{self.sample_id}: mean depth of threshold-passing bases",
                "Mean depth at bases meeting threshold",
                log_x=False,
            )

        return (
            self.bed_path,
            self.tsv_path,
            self.summary_path,
            self.length_plot,
            self.depth_plot,
            summary,
        )


def stream_high_depth_region_inference(
    bam_path: Path,
    settings: dict,
    sample_dir: Path,
    log_file: Path,
    dry_run: bool,
) -> tuple[Path, Path, Path, Path, Path, dict[str, object]]:
    """
    Dedicated whole-genome streaming pass used only when the ordinary Step 04
    depth command is restricted to an existing target BED.

    When Step 04 already runs genome-wide depth, the inference is performed
    inside that existing pass instead, avoiding duplicate BAM traversal.
    """
    qc = settings["bam_qc"]
    threshold = int(qc["high_depth_threshold"])
    minimum_region_length_bp = int(
        qc["high_depth_minimum_region_length_bp"]
    )
    maximum_merge_gap_bp = int(qc["high_depth_maximum_merge_gap_bp"])

    reference_lengths = (
        {}
        if dry_run
        else _bam_reference_lengths(bam_path)
    )
    writer = HighDepthRegionWriter(
        sample_dir.name,
        sample_dir,
        threshold,
        minimum_region_length_bp,
        maximum_merge_gap_bp,
        sum(reference_lengths.values()),
        dry_run=dry_run,
    )

    if dry_run:
        return writer.finish()

    samtools = str(settings["tools"]["samtools"])

    command = [
        samtools,
        "depth",
        "-Q",
        str(qc["minimum_mapping_quality"]),
        "-q",
        str(qc["minimum_base_quality"]),
        str(bam_path),
    ]

    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as log_handle:
        log_handle.write(
            "\nHIGH-DEPTH TARGET-INFERENCE STREAMING COMMAND:\n"
            + " ".join(str(piece) for piece in command)
            + "\n"
        )
        log_handle.flush()

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=log_handle,
            text=True,
            bufsize=1024 * 1024,
        )

        if process.stdout is None:
            process.kill()
            raise RuntimeError(
                "Unable to read samtools depth stdout for target inference."
            )

        for line in process.stdout:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 3:
                continue
            try:
                position_1based = int(fields[1])
                depth = int(fields[2])
            except ValueError:
                continue
            if position_1based < 1 or depth < 0:
                continue
            writer.consume(fields[0], position_1based, depth)

        process.stdout.close()
        return_code = process.wait()

    if return_code != 0:
        raise RuntimeError(
            f"samtools depth failed during high-depth target inference for "
            f"{bam_path} with exit code {return_code}. See log: {log_file}"
        )

    return writer.finish()


def _read_bed3_intervals(path: Path) -> dict[str, list[tuple[int, int]]]:
    output: dict[str, list[tuple[int, int]]] = {}
    if not path.exists() or not path.is_file():
        return output

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 3:
                continue
            try:
                start = int(fields[1])
                end = int(fields[2])
            except ValueError:
                continue
            if end <= start:
                continue
            output.setdefault(fields[0], []).append((start, end))
    return output


def build_consensus_high_depth_bed(
    per_sample_beds: list[tuple[str, Path]],
    output_dir: Path,
    depth_threshold: int,
    minimum_sample_percent: float,
    minimum_region_length_bp: int,
    dry_run: bool,
) -> tuple[Path, Path, Path, Path, dict[str, object]]:
    """
    Build a base-exact consensus BED using a sweep line over the per-sample
    inferred BED intervals.

    A genomic base enters the consensus if it is covered by inferred high-depth
    regions from at least ceil(N * percentage/100) samples.
    """
    token = _threshold_token(depth_threshold)
    bed_path = output_dir / f"consensus_inferred_high_depth_regions.{token}.bed"
    tsv_path = output_dir / f"consensus_inferred_high_depth_regions.{token}.tsv"
    summary_path = output_dir / "consensus_inferred_high_depth_summary.tsv"
    plot_path = output_dir / "consensus_inferred_high_depth_region_lengths.png"

    sample_count = len(per_sample_beds)
    required_support = max(
        1,
        int(math.ceil(sample_count * float(minimum_sample_percent) / 100.0)),
    ) if sample_count else 0

    bed_path.write_text("", encoding="utf-8")
    if dry_run or sample_count == 0:
        write_tsv(
            pd.DataFrame(
                columns=[
                    "REGION_ID",
                    "CHROM",
                    "BED_START_0BASED",
                    "BED_END_0BASED_EXCLUSIVE",
                    "START_1BASED",
                    "END_1BASED",
                    "REGION_LENGTH_BP",
                    "MIN_SUPPORTING_SAMPLE_COUNT",
                    "MAX_SUPPORTING_SAMPLE_COUNT",
                    "REQUIRED_SAMPLE_COUNT",
                    "TOTAL_SAMPLE_COUNT",
                    "REQUIRED_SAMPLE_PERCENT",
                ]
            ),
            tsv_path,
        )
        summary = {
            "TOTAL_SAMPLE_COUNT": sample_count,
            "REQUIRED_SAMPLE_PERCENT": minimum_sample_percent,
            "REQUIRED_SAMPLE_COUNT": required_support,
            "CONSENSUS_REGION_COUNT": 0,
            "TOTAL_CONSENSUS_BP": 0,
            "DEPTH_THRESHOLD_X": depth_threshold,
            "BED_FILE": str(bed_path),
            "DETAIL_TSV": str(tsv_path),
        }
        write_tsv(pd.DataFrame([summary]), summary_path)
        save_placeholder_plot(
            plot_path,
            "Consensus inferred high-depth region lengths",
            (
                "Dry run: no consensus was calculated."
                if dry_run
                else "No BAM samples were available."
            ),
        )
        return bed_path, tsv_path, summary_path, plot_path, summary

    sweep_events: dict[str, Counter] = {}
    for _sample_id, bed in per_sample_beds:
        intervals = _read_bed3_intervals(bed)
        for chrom, chrom_intervals in intervals.items():
            events = sweep_events.setdefault(chrom, Counter())
            for start, end in chrom_intervals:
                events[int(start)] += 1
                events[int(end)] -= 1

    consensus_rows: list[dict[str, object]] = []
    length_histogram: Counter = Counter()

    for chrom in sorted(sweep_events, key=lambda value: (
        _primary_human_chromosome_rank(value)
        if _primary_human_chromosome_rank(value) is not None
        else 10_000,
        str(value),
    )):
        events = sweep_events[chrom]
        current_support = 0
        previous_position: int | None = None

        current_start: int | None = None
        current_end: int | None = None
        current_min_support = 0
        current_max_support = 0

        def finalize_consensus() -> None:
            nonlocal current_start, current_end
            nonlocal current_min_support, current_max_support

            if current_start is None or current_end is None:
                return
            length = current_end - current_start
            if length >= minimum_region_length_bp:
                region_number = len(consensus_rows) + 1
                consensus_rows.append(
                    {
                        "REGION_ID": f"CONSENSUS_HIGH_DEPTH_{region_number}",
                        "CHROM": chrom,
                        "BED_START_0BASED": current_start,
                        "BED_END_0BASED_EXCLUSIVE": current_end,
                        "START_1BASED": current_start + 1,
                        "END_1BASED": current_end,
                        "REGION_LENGTH_BP": length,
                        "MIN_SUPPORTING_SAMPLE_COUNT": current_min_support,
                        "MAX_SUPPORTING_SAMPLE_COUNT": current_max_support,
                        "REQUIRED_SAMPLE_COUNT": required_support,
                        "TOTAL_SAMPLE_COUNT": sample_count,
                        "REQUIRED_SAMPLE_PERCENT": minimum_sample_percent,
                    }
                )
                length_histogram[int(length)] += 1

            current_start = None
            current_end = None
            current_min_support = 0
            current_max_support = 0

        for position in sorted(events):
            if previous_position is not None and position > previous_position:
                qualifies = current_support >= required_support
                if qualifies:
                    if current_start is None:
                        current_start = previous_position
                        current_end = position
                        current_min_support = current_support
                        current_max_support = current_support
                    elif current_end == previous_position:
                        current_end = position
                        current_min_support = min(
                            current_min_support,
                            current_support,
                        )
                        current_max_support = max(
                            current_max_support,
                            current_support,
                        )
                    else:
                        finalize_consensus()
                        current_start = previous_position
                        current_end = position
                        current_min_support = current_support
                        current_max_support = current_support
                elif current_start is not None:
                    finalize_consensus()

            current_support += int(events[position])
            previous_position = position

        finalize_consensus()

    consensus_table = pd.DataFrame(consensus_rows)
    write_tsv(consensus_table, tsv_path)

    with bed_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in consensus_rows:
            handle.write(
                f"{row['CHROM']}\t"
                f"{row['BED_START_0BASED']}\t"
                f"{row['BED_END_0BASED_EXCLUSIVE']}\n"
            )

    total_consensus_bp = int(
        sum(int(row["REGION_LENGTH_BP"]) for row in consensus_rows)
    )
    summary = {
        "TOTAL_SAMPLE_COUNT": sample_count,
        "REQUIRED_SAMPLE_PERCENT": float(minimum_sample_percent),
        "REQUIRED_SAMPLE_COUNT": required_support,
        "CONSENSUS_REGION_COUNT": len(consensus_rows),
        "TOTAL_CONSENSUS_BP": total_consensus_bp,
        "DEPTH_THRESHOLD_X": int(depth_threshold),
        "MINIMUM_REGION_LENGTH_BP": int(minimum_region_length_bp),
        "BED_COORDINATE_SYSTEM": "0-based half-open",
        "BED_FILE": str(bed_path),
        "DETAIL_TSV": str(tsv_path),
        "INTERPRETATION": (
            "Empirical consensus high-coverage regions across Step 04 BAMs; "
            "not necessarily identical to the manufacturer's assay BED."
        ),
    }
    write_tsv(pd.DataFrame([summary]), summary_path)

    if not length_histogram:
        save_placeholder_plot(
            plot_path,
            "Consensus inferred high-depth region lengths",
            "No consensus regions passed the selected support/length filters.",
        )
    else:
        values = sorted(int(value) for value in length_histogram)
        weights = [int(length_histogram[value]) for value in values]
        bins = min(50, max(10, int(math.sqrt(sum(weights))) + 1))
        figure, axis = plt.subplots(figsize=(10, 6))
        axis.hist(values, bins=bins, weights=weights)
        if max(values) > 100:
            axis.set_xscale("log")
        axis.set_xlabel("Consensus region length (bp)")
        axis.set_ylabel("Region count")
        axis.set_title(
            "Consensus inferred high-depth target-region lengths"
        )
        axis.grid(axis="y", alpha=0.25)
        figure.tight_layout()
        figure.savefig(plot_path, dpi=180)
        plt.close(figure)

    return bed_path, tsv_path, summary_path, plot_path, summary



def _primary_human_chromosome_rank(chrom: str) -> int | None:
    """
    Return a conventional plotting rank for human chr1-22, X, Y, M/MT.

    The TSV always contains all contigs from the BAM header. This helper is only
    used to make the overview plot readable when standard human chromosomes are
    available.
    """
    token = str(chrom)
    if token.lower().startswith("chr"):
        token = token[3:]
    token_upper = token.upper()

    if token_upper.isdigit():
        number = int(token_upper)
        if 1 <= number <= 22:
            return number

    if token_upper == "X":
        return 23
    if token_upper == "Y":
        return 24
    if token_upper in {"M", "MT"}:
        return 25
    return None


def _build_genome_bin_table(
    sample_id: str,
    reference_lengths: dict[str, int],
    bin_size_bp: int,
    depth_sums: Counter,
    covered_base_counts: Counter,
) -> pd.DataFrame:
    """
    Build one row for every fixed-width genome bin, including bins with 0 depth.

    Coordinates in BIN_NAME are 1-based inclusive:
        chr14:100001-200000
    """
    rows: list[dict] = []

    for chrom, chrom_length in reference_lengths.items():
        chrom_length = int(chrom_length)
        if chrom_length <= 0:
            continue

        number_of_bins = (chrom_length + bin_size_bp - 1) // bin_size_bp
        rank = _primary_human_chromosome_rank(chrom)

        for bin_index in range(number_of_bins):
            start_1based = bin_index * bin_size_bp + 1
            end_1based = min((bin_index + 1) * bin_size_bp, chrom_length)
            bin_length = end_1based - start_1based + 1
            key = (chrom, bin_index)

            depth_sum = int(depth_sums.get(key, 0))
            covered_bases = int(covered_base_counts.get(key, 0))

            rows.append(
                {
                    "SAMPLE_ID": sample_id,
                    "CHROMOSOME": chrom,
                    "CHROMOSOME_LENGTH": chrom_length,
                    "PRIMARY_CHROMOSOME_RANK": rank if rank is not None else "",
                    "BIN_NUMBER": bin_index + 1,
                    "BIN_START_1BASED": start_1based,
                    "BIN_END_1BASED": end_1based,
                    "BIN_NAME": f"{chrom}:{start_1based}-{end_1based}",
                    "BIN_LENGTH": bin_length,
                    "DEPTH_SUM": depth_sum,
                    "MEAN_DEPTH_ALL_BASES": (
                        depth_sum / bin_length if bin_length > 0 else float("nan")
                    ),
                    "COVERED_BASES": covered_bases,
                    "PERCENT_BASES_COVERED": (
                        100.0 * covered_bases / bin_length
                        if bin_length > 0 else float("nan")
                    ),
                    "MEAN_DEPTH_COVERED_BASES_ONLY": (
                        depth_sum / covered_bases
                        if covered_bases > 0 else 0.0
                    ),
                }
            )

    return pd.DataFrame(rows)


def _canonical_chromosome_display_name(chrom: str) -> str:
    """
    Convert a BAM contig name into the display name used in the stacked plot.

    Examples:
        chr1 -> Chromosome 1
        1    -> Chromosome 1
        chrX -> Chromosome X
    """
    token = str(chrom)
    if token.lower().startswith("chr"):
        token = token[3:]
    return f"Chromosome {token}"


def _save_genome_bin_plots(
    table: pd.DataFrame,
    sample_id: str,
    sample_dir: Path,
    bin_size_bp: int,
) -> tuple[Path, Path, Path, Path]:
    """
    Save four genome-bin plots:

      1. genome-wide linear mean-depth plot,
      2. genome-wide log1p mean-depth plot,
      3. top-30 named bins by mean depth,
      4. chromosome-stacked plot:
            Chromosome 1
            Chromosome 2
            ...
            Chromosome 22
            Chromosome X
            Chromosome Y

         Each chromosome row has:
            x = genomic bin location in Mb
            y = MEAN_DEPTH_ALL_BASES

    The chromosome-stacked plot contains ALL bins for the canonical human
    chromosomes 1-22, X and Y. Mitochondrial and alternate/decoy contigs remain
    in the TSV but are omitted from this particular visualization so that the
    figure remains readable.
    """
    linear_plot = sample_dir / f"{sample_id}.genome_bin_mean_depth.png"
    log_plot = sample_dir / f"{sample_id}.genome_bin_mean_depth_log1p.png"
    top_plot = sample_dir / f"{sample_id}.top_genome_bins_by_depth.png"
    chromosome_plot = (
        sample_dir / f"{sample_id}.genome_bin_depth_by_chromosome.png"
    )

    if table.empty:
        save_placeholder_plot(
            linear_plot,
            f"{sample_id}: genome-bin mean depth",
            "No genome bins were available.",
        )
        save_placeholder_plot(
            log_plot,
            f"{sample_id}: genome-bin mean depth (log1p)",
            "No genome bins were available.",
        )
        save_placeholder_plot(
            top_plot,
            f"{sample_id}: top genome bins by depth",
            "No genome bins were available.",
        )
        save_placeholder_plot(
            chromosome_plot,
            f"{sample_id}: genome bin depth by chromosome",
            "No genome bins were available.",
        )
        return linear_plot, log_plot, top_plot, chromosome_plot

    primary_mask = pd.to_numeric(
        table["PRIMARY_CHROMOSOME_RANK"], errors="coerce"
    ).notna()

    if primary_mask.any():
        plot_table = table.loc[primary_mask].copy()
        plot_table["_RANK"] = pd.to_numeric(
            plot_table["PRIMARY_CHROMOSOME_RANK"], errors="coerce"
        )
        plot_table = plot_table.sort_values(
            ["_RANK", "BIN_START_1BASED"],
            kind="stable",
        )
    else:
        plot_table = table.copy()

    chromosome_order: list[str] = []
    seen: set[str] = set()
    for chrom in plot_table["CHROMOSOME"].astype(str):
        if chrom not in seen:
            chromosome_order.append(chrom)
            seen.add(chrom)

    offsets: dict[str, int] = {}
    chromosome_centers: list[float] = []
    chromosome_labels: list[str] = []
    running = 0

    for chrom in chromosome_order:
        chrom_rows = plot_table.loc[
            plot_table["CHROMOSOME"].astype(str) == chrom
        ]
        if chrom_rows.empty:
            continue
        chrom_length = int(chrom_rows["CHROMOSOME_LENGTH"].iloc[0])
        offsets[chrom] = running
        chromosome_centers.append(running + chrom_length / 2.0)
        chromosome_labels.append(chrom)
        running += chrom_length

    x_values: list[float] = []
    for row in plot_table.to_dict(orient="records"):
        midpoint = (
            int(row["BIN_START_1BASED"]) + int(row["BIN_END_1BASED"])
        ) / 2.0
        x_values.append(offsets[str(row["CHROMOSOME"])] + midpoint)

    y_values = pd.to_numeric(
        plot_table["MEAN_DEPTH_ALL_BASES"],
        errors="coerce",
    ).fillna(0.0).tolist()

    # ------------------------------------------------------------------
    # Existing genome-wide linear plot.
    # ------------------------------------------------------------------
    figure, axis = plt.subplots(figsize=(14, 6))
    axis.plot(x_values, y_values, linewidth=0.8)
    axis.set_xlabel("Genomic position")
    axis.set_ylabel("Mean depth per bin")
    axis.set_title(
        f"{sample_id}: genome-wide depth in {bin_size_bp:,}-bp bins"
    )
    axis.set_xticks(chromosome_centers)
    axis.set_xticklabels(chromosome_labels, rotation=60, ha="right")
    axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    figure.savefig(linear_plot, dpi=180)
    plt.close(figure)

    # ------------------------------------------------------------------
    # Existing genome-wide log1p plot.
    # ------------------------------------------------------------------
    figure, axis = plt.subplots(figsize=(14, 6))
    log_y = [math.log1p(max(0.0, float(value))) for value in y_values]
    axis.plot(x_values, log_y, linewidth=0.8)
    axis.set_xlabel("Genomic position")
    axis.set_ylabel("log1p(mean depth per bin)")
    axis.set_title(
        f"{sample_id}: genome-wide depth in {bin_size_bp:,}-bp bins (log1p)"
    )
    axis.set_xticks(chromosome_centers)
    axis.set_xticklabels(chromosome_labels, rotation=60, ha="right")
    axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    figure.savefig(log_plot, dpi=180)
    plt.close(figure)

    # ------------------------------------------------------------------
    # Existing top-bin plot.
    # ------------------------------------------------------------------
    top = table.nlargest(
        min(30, len(table)),
        "MEAN_DEPTH_ALL_BASES",
    ).copy()
    top = top.sort_values("MEAN_DEPTH_ALL_BASES", ascending=True)

    figure_height = max(6.0, min(14.0, 0.32 * len(top) + 2.5))
    figure, axis = plt.subplots(figsize=(12, figure_height))
    axis.barh(
        top["BIN_NAME"].astype(str),
        pd.to_numeric(
            top["MEAN_DEPTH_ALL_BASES"],
            errors="coerce",
        ).fillna(0.0),
    )
    axis.set_xlabel("Mean depth across all bases in bin")
    axis.set_ylabel("Genomic bin")
    axis.set_title(f"{sample_id}: top genome bins by mean depth")
    axis.grid(axis="x", alpha=0.25)
    figure.tight_layout()
    figure.savefig(top_plot, dpi=180)
    plt.close(figure)

    # ------------------------------------------------------------------
    # NEW: stacked chromosome-by-chromosome plot.
    # ------------------------------------------------------------------
    ranked = table.copy()
    ranked["_RANK"] = pd.to_numeric(
        ranked["PRIMARY_CHROMOSOME_RANK"],
        errors="coerce",
    )

    # Keep chr1-22, X, Y (rank 1-24). Rank 25 is mitochondrial.
    ranked = ranked.loc[
        ranked["_RANK"].between(1, 24, inclusive="both")
    ].copy()
    ranked = ranked.sort_values(
        ["_RANK", "BIN_START_1BASED"],
        kind="stable",
    )

    available_ranks = [
        int(value)
        for value in sorted(ranked["_RANK"].dropna().unique())
    ]

    if not available_ranks:
        save_placeholder_plot(
            chromosome_plot,
            f"{sample_id}: genome bin depth by chromosome",
            "No canonical chromosomes 1-22, X or Y were found.",
        )
    else:
        number_of_panels = len(available_ranks)

        # A tall figure is intentional: each chromosome gets its own readable row.
        figure_height = max(16.0, 1.45 * number_of_panels + 2.5)
        figure, axes = plt.subplots(
            number_of_panels,
            1,
            figsize=(16, figure_height),
            squeeze=False,
        )
        axes = axes[:, 0]

        for axis, rank in zip(axes, available_ranks):
            chrom_rows = ranked.loc[ranked["_RANK"] == rank].copy()
            chrom_rows = chrom_rows.sort_values(
                "BIN_START_1BASED",
                kind="stable",
            )

            chrom = str(chrom_rows["CHROMOSOME"].iloc[0])

            # Use the bin midpoint as its genomic x coordinate.
            # Convert bp to Mb to keep x-axis numbers compact and readable.
            x_mb = (
                (
                    pd.to_numeric(
                        chrom_rows["BIN_START_1BASED"],
                        errors="coerce",
                    )
                    + pd.to_numeric(
                        chrom_rows["BIN_END_1BASED"],
                        errors="coerce",
                    )
                )
                / 2.0
                / 1_000_000.0
            )

            y_depth = pd.to_numeric(
                chrom_rows["MEAN_DEPTH_ALL_BASES"],
                errors="coerce",
            ).fillna(0.0)

            axis.plot(
                x_mb,
                y_depth,
                linewidth=0.85,
            )

            axis.set_title(
                _canonical_chromosome_display_name(chrom),
                loc="left",
                fontsize=9,
                fontweight="bold",
                pad=2,
            )
            axis.set_ylabel("Depth", fontsize=8)
            axis.set_ylim(bottom=0)
            axis.grid(axis="both", alpha=0.22)
            axis.tick_params(axis="both", labelsize=7)

            # The x coordinates show actual genomic position, not merely bin number.
            chrom_length_mb = (
                float(chrom_rows["CHROMOSOME_LENGTH"].iloc[0])
                / 1_000_000.0
            )
            axis.set_xlim(0, chrom_length_mb)

        figure.suptitle(
            (
                f"{sample_id}: genome bin depth by chromosome "
                f"({bin_size_bp:,}-bp bins)"
            ),
            fontsize=15,
            fontweight="bold",
            y=0.998,
        )
        figure.supxlabel("Bin location / genomic position (Mb)", fontsize=11)
        figure.supylabel("Mean sequencing depth per bin", fontsize=11)

        # Leave room for the overall labels/title while keeping all 24 panels.
        figure.tight_layout(rect=(0.035, 0.025, 0.995, 0.985))
        figure.savefig(
            chromosome_plot,
            dpi=180,
            bbox_inches="tight",
        )
        plt.close(figure)

    return linear_plot, log_plot, top_plot, chromosome_plot


def _write_genome_bin_outputs(
    sample_id: str,
    reference_lengths: dict[str, int],
    bin_size_bp: int,
    depth_sums: Counter,
    covered_base_counts: Counter,
    sample_dir: Path,
) -> tuple[Path, Path, Path, Path, Path]:
    table = _build_genome_bin_table(
        sample_id,
        reference_lengths,
        bin_size_bp,
        depth_sums,
        covered_base_counts,
    )

    table_path = sample_dir / f"{sample_id}.genome_bin_depth.tsv"
    write_tsv(table, table_path)

    (
        linear_plot,
        log_plot,
        top_plot,
        chromosome_plot,
    ) = _save_genome_bin_plots(
        table,
        sample_id,
        sample_dir,
        bin_size_bp,
    )
    return (
        table_path,
        linear_plot,
        log_plot,
        top_plot,
        chromosome_plot,
    )


def stream_genome_bin_depth(
    bam_path: Path,
    settings: dict,
    sample_dir: Path,
    log_file: Path,
    bin_size_bp: int,
    dry_run: bool,
) -> tuple[Path, Path, Path, Path, Path]:
    """
    Whole-genome fixed-bin depth using a streaming samtools-depth pass.

    Used when the ordinary Step 04 depth calculation is restricted to a target
    BED. The bin analysis is intentionally genome-wide and independent of BED.

    No per-base depth file and no per-base Python array are created.
    """
    sample_id = sample_dir.name
    reference_lengths = _bam_reference_lengths(bam_path)

    if dry_run:
        empty = pd.DataFrame(
            columns=[
                "SAMPLE_ID",
                "CHROMOSOME",
                "BIN_NUMBER",
                "BIN_START_1BASED",
                "BIN_END_1BASED",
                "BIN_NAME",
                "BIN_LENGTH",
                "DEPTH_SUM",
                "MEAN_DEPTH_ALL_BASES",
                "COVERED_BASES",
                "PERCENT_BASES_COVERED",
                "MEAN_DEPTH_COVERED_BASES_ONLY",
            ]
        )
        table_path = sample_dir / f"{sample_id}.genome_bin_depth.tsv"
        write_tsv(empty, table_path)
        (
            linear_plot,
            log_plot,
            top_plot,
            chromosome_plot,
        ) = _save_genome_bin_plots(
            empty,
            sample_id,
            sample_dir,
            bin_size_bp,
        )
        return (
            table_path,
            linear_plot,
            log_plot,
            top_plot,
            chromosome_plot,
        )

    samtools = str(settings["tools"]["samtools"])
    qc = settings["bam_qc"]

    command = [
        samtools,
        "depth",
        "-Q",
        str(qc["minimum_mapping_quality"]),
        "-q",
        str(qc["minimum_base_quality"]),
        str(bam_path),
    ]

    depth_sums: Counter = Counter()
    covered_base_counts: Counter = Counter()

    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as log_handle:
        log_handle.write(
            "\nGENOME-BIN STREAMING DEPTH COMMAND:\n"
            + " ".join(str(piece) for piece in command)
            + "\n"
        )
        log_handle.flush()

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=log_handle,
            text=True,
            bufsize=1024 * 1024,
        )

        if process.stdout is None:
            process.kill()
            raise RuntimeError(
                "Unable to read samtools depth stdout for genome bins."
            )

        for line in process.stdout:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 3:
                continue

            chrom = fields[0]
            try:
                position_1based = int(fields[1])
                depth = int(fields[2])
            except ValueError:
                continue

            if depth < 0 or chrom not in reference_lengths or position_1based < 1:
                continue

            bin_index = (position_1based - 1) // bin_size_bp
            key = (chrom, bin_index)
            depth_sums[key] += depth
            if depth > 0:
                covered_base_counts[key] += 1

        process.stdout.close()
        return_code = process.wait()

    if return_code != 0:
        raise RuntimeError(
            f"samtools depth failed during genome-bin analysis for {bam_path} "
            f"with exit code {return_code}. See log: {log_file}"
        )

    return _write_genome_bin_outputs(
        sample_id,
        reference_lengths,
        bin_size_bp,
        depth_sums,
        covered_base_counts,
        sample_dir,
    )


def stream_depth_metrics(
    bam_path: Path,
    settings: dict,
    target_bed_path: Path | None,
    sample_dir: Path,
    log_file: Path,
    dry_run: bool,
    genome_bin_size_bp: int | None = None,
) -> tuple[
    dict[str, float],
    Path,
    Path,
    tuple[Path, Path, Path, Path, Path] | None,
    tuple[Path, Path, Path, Path, Path, dict[str, object]] | None,
]:
    """
    Compute depth QC in constant/low memory.

    Important:
    - `samtools depth -a` is NOT used.
    - stdout is consumed one row at a time.
    - depth values are summarized into a small Counter rather than a list.
    - uncovered bases are added mathematically using the BAM reference lengths
      or the merged BED target length.

    This avoids multi-billion-row files and Python objects for a human genome.
    """
    histogram_path = sample_dir / f"{sample_dir.name}.depth_histogram.tsv"
    summary_path = sample_dir / f"{sample_dir.name}.depth_summary.tsv"

    qc = settings["bam_qc"]
    high_depth_enabled = bool(
        qc['infer_high_depth_regions_enabled']
    )
    collect_high_depth_in_this_pass = (
        high_depth_enabled and target_bed_path is None
    )

    if dry_run:
        write_tsv(
            pd.DataFrame(
                columns=["DEPTH", "POSITION_COUNT"]
            ),
            histogram_path,
        )
        write_tsv(
            pd.DataFrame(
                [{
                    "DEPTH_MODE": "DRY_RUN",
                    "TOTAL_POSITIONS": 0,
                    "OBSERVED_POSITIONS": 0,
                    "ZERO_DEPTH_POSITIONS": 0,
                    "MEAN_DEPTH": float("nan"),
                    "MEDIAN_DEPTH": float("nan"),
                    "DEPTH_CV": float("nan"),
                    "PERCENT_BASES_AT_100X": float("nan"),
                    "PERCENT_BASES_AT_500X": float("nan"),
                }]
            ),
            summary_path,
        )
        bin_outputs = None
        if genome_bin_size_bp is not None and target_bed_path is None:
            # Keep the historical dry-run behavior when pysam is available,
            # but do not require BAM access merely to preview high-depth outputs.
            reference_lengths_for_bins = (
                _bam_reference_lengths(bam_path)
                if pysam is not None and bam_path.exists()
                else {}
            )
            bin_outputs = _write_genome_bin_outputs(
                sample_dir.name,
                reference_lengths_for_bins,
                genome_bin_size_bp,
                Counter(),
                Counter(),
                sample_dir,
            )

        high_depth_outputs = None
        if collect_high_depth_in_this_pass:
            writer = HighDepthRegionWriter(
                sample_dir.name,
                sample_dir,
                int(qc["high_depth_threshold"]),
                int(qc["high_depth_minimum_region_length_bp"]),
                int(qc["high_depth_maximum_merge_gap_bp"]),
                0,
                dry_run=True,
            )
            high_depth_outputs = writer.finish()

        return {
            "MEAN_DEPTH": float("nan"),
            "MEDIAN_DEPTH": float("nan"),
            "DEPTH_CV": float("nan"),
            "PERCENT_BASES_AT_100X": float("nan"),
            "PERCENT_BASES_AT_500X": float("nan"),
            "DEPTH_TOTAL_POSITIONS": 0,
            "DEPTH_OBSERVED_POSITIONS": 0,
            "ZERO_DEPTH_POSITIONS": 0,
        }, histogram_path, summary_path, bin_outputs, high_depth_outputs

    samtools = str(settings["tools"]["samtools"])

    reference_lengths = _bam_reference_lengths(bam_path)

    if target_bed_path is not None:
        total_positions, valid_bed_intervals, skipped_bed_intervals = _merged_bed_length(
            target_bed_path,
            reference_lengths,
        )
        if total_positions <= 0:
            raise ValueError(
                "The selected BED contains no valid bases matching BAM reference "
                "contig names. Check chr-prefix/build consistency between BAM and BED."
            )
        depth_mode = "TARGET_BED_ALL_BASES_INCLUDING_IMPLICIT_ZEROS"
    else:
        total_positions = int(sum(reference_lengths.values()))
        valid_bed_intervals = 0
        skipped_bed_intervals = 0
        if total_positions <= 0:
            raise ValueError(
                f"No reference lengths were found in BAM header: {bam_path}"
            )
        depth_mode = "FULL_BAM_REFERENCE_ALL_BASES_INCLUDING_IMPLICIT_ZEROS"

    high_depth_writer = None
    if collect_high_depth_in_this_pass:
        high_depth_writer = HighDepthRegionWriter(
            sample_dir.name,
            sample_dir,
            int(qc["high_depth_threshold"]),
            int(qc["high_depth_minimum_region_length_bp"]),
            int(qc["high_depth_maximum_merge_gap_bp"]),
            int(sum(reference_lengths.values())),
            dry_run=False,
        )

    command = [
        samtools,
        "depth",
        "-Q",
        str(qc["minimum_mapping_quality"]),
        "-q",
        str(qc["minimum_base_quality"]),
    ]
    if target_bed_path is not None:
        command.extend(["-b", str(target_bed_path)])
    command.append(str(bam_path))

    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as log_handle:
        log_handle.write(
            "\nSTREAMING DEPTH COMMAND:\n"
            + " ".join(str(piece) for piece in command)
            + "\n"
        )
        log_handle.flush()

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=log_handle,
            text=True,
            bufsize=1024 * 1024,
        )

        if process.stdout is None:
            process.kill()
            raise RuntimeError("Unable to read samtools depth stdout.")

        histogram: Counter = Counter()
        observed_positions = 0
        depth_sum = 0
        depth_sum_squares = 0
        at_100 = 0
        at_500 = 0

        collect_bins_in_this_pass = (
            genome_bin_size_bp is not None and target_bed_path is None
        )
        bin_depth_sums: Counter = Counter()
        bin_covered_base_counts: Counter = Counter()

        for line in process.stdout:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 3:
                continue

            chrom = fields[0]
            try:
                position_1based = int(fields[1])
                depth = int(fields[2])
            except ValueError:
                continue

            # Without -a, samtools depth normally emits covered positions.
            # Keep this robust if a zero-depth row is emitted by a future build.
            if depth < 0:
                continue

            if high_depth_writer is not None:
                high_depth_writer.consume(
                    chrom,
                    position_1based,
                    depth,
                )

            observed_positions += 1
            histogram[depth] += 1
            depth_sum += depth
            depth_sum_squares += depth * depth
            if depth >= 100:
                at_100 += 1
            if depth >= 500:
                at_500 += 1

            if (
                collect_bins_in_this_pass
                and chrom in reference_lengths
                and position_1based >= 1
            ):
                bin_index = (position_1based - 1) // int(genome_bin_size_bp)
                key = (chrom, bin_index)
                bin_depth_sums[key] += depth
                if depth > 0:
                    bin_covered_base_counts[key] += 1

        process.stdout.close()
        return_code = process.wait()

    if return_code != 0:
        raise RuntimeError(
            f"samtools depth failed for {bam_path} with exit code {return_code}. "
            f"See log: {log_file}"
        )

    if observed_positions > total_positions:
        # This should not happen for a normal BAM/BED combination. Avoid silently
        # creating a negative zero count and report a clear consistency problem.
        raise ValueError(
            f"samtools depth emitted {observed_positions:,} positions, but the "
            f"calculated analysis span is only {total_positions:,} bases for "
            f"{bam_path}. Check BAM/BED coordinate consistency."
        )

    zero_positions = total_positions - observed_positions
    if zero_positions:
        histogram[0] += zero_positions

    mean_depth = depth_sum / total_positions if total_positions else float("nan")

    if total_positions > 1 and mean_depth == mean_depth:
        numerator = (
            depth_sum_squares
            - (depth_sum * depth_sum) / total_positions
        )
        # Floating-point cancellation can produce a tiny negative number.
        numerator = max(0.0, float(numerator))
        variance = numerator / (total_positions - 1)
        depth_cv = (
            (variance ** 0.5) / mean_depth
            if mean_depth > 0
            else float("nan")
        )
    else:
        depth_cv = float("nan")

    median_depth = _median_from_histogram(histogram, total_positions)

    metrics = {
        "MEAN_DEPTH": float(mean_depth),
        "MEDIAN_DEPTH": float(median_depth),
        "DEPTH_CV": float(depth_cv),
        "PERCENT_BASES_AT_100X": float(100.0 * at_100 / total_positions),
        "PERCENT_BASES_AT_500X": float(100.0 * at_500 / total_positions),
        "DEPTH_TOTAL_POSITIONS": int(total_positions),
        "DEPTH_OBSERVED_POSITIONS": int(observed_positions),
        "ZERO_DEPTH_POSITIONS": int(zero_positions),
    }

    histogram_table = pd.DataFrame(
        [
            {
                "DEPTH": int(depth),
                "POSITION_COUNT": int(count),
                "PERCENT_OF_ANALYSIS_BASES": (
                    100.0 * int(count) / total_positions
                ),
            }
            for depth, count in sorted(histogram.items())
        ]
    )
    write_tsv(histogram_table, histogram_path)

    summary_table = pd.DataFrame(
        [{
            "DEPTH_MODE": depth_mode,
            "TARGET_BED": str(target_bed_path) if target_bed_path else "",
            "VALID_BED_INTERVALS": valid_bed_intervals,
            "SKIPPED_BED_INTERVALS": skipped_bed_intervals,
            "TOTAL_POSITIONS": int(total_positions),
            "OBSERVED_POSITIONS": int(observed_positions),
            "ZERO_DEPTH_POSITIONS": int(zero_positions),
            **metrics,
        }]
    )
    write_tsv(summary_table, summary_path)

    bin_outputs = None
    if collect_bins_in_this_pass:
        bin_outputs = _write_genome_bin_outputs(
            sample_dir.name,
            reference_lengths,
            int(genome_bin_size_bp),
            bin_depth_sums,
            bin_covered_base_counts,
            sample_dir,
        )

    high_depth_outputs = (
        high_depth_writer.finish()
        if high_depth_writer is not None
        else None
    )

    return (
        metrics,
        histogram_path,
        summary_path,
        bin_outputs,
        high_depth_outputs,
    )



def save_combined_fragment_length_plot(
    fragment_tables: list[pd.DataFrame],
    output_path: Path,
    *,
    log_count: bool = False,
    x_min_bp: int | None = None,
    x_max_bp: int | None = None,
    minor_tick_bp: int | None = None,
    reference_bp: int | None = None,
) -> None:
    """
    Plot cfDNA fragment-length distributions across all Step 04 BAM samples.

    The linear-count and log-count plots use exactly the same fragment-length
    count tables; the optional second plot changes visualization only.

    Zero-count bins are omitted in log mode because log(0) is undefined.
    """
    title = (
        "cfDNA fragment-length distributions — log(count)"
        if log_count
        else "cfDNA fragment-length distributions"
    )

    if not fragment_tables:
        save_placeholder_plot(
            output_path,
            title,
            "No paired-end fragment lengths were available.",
        )
        return

    figure, axis = plt.subplots(figsize=(12, 6.5))
    plotted_anything = False

    for table in fragment_tables:
        if table is None or table.empty:
            continue
        if "FRAGMENT_LENGTH" not in table.columns or "COUNT" not in table.columns:
            continue

        sample_id = (
            str(table["SAMPLE_ID"].iloc[0])
            if "SAMPLE_ID" in table.columns and len(table) > 0
            else "Sample"
        )

        x = pd.to_numeric(table["FRAGMENT_LENGTH"], errors="coerce")
        y = pd.to_numeric(table["COUNT"], errors="coerce")

        valid = x.notna() & y.notna()
        if x_min_bp is not None:
            valid &= x >= int(x_min_bp)
        if x_max_bp is not None:
            valid &= x <= int(x_max_bp)
        if log_count:
            valid &= y > 0

        x = x[valid]
        y = y[valid]
        if x.empty:
            continue

        ordering = x.argsort()
        axis.plot(
            x.iloc[ordering],
            y.iloc[ordering],
            linewidth=1.8,
            label=sample_id,
        )
        plotted_anything = True

    if not plotted_anything:
        plt.close(figure)
        save_placeholder_plot(
            output_path,
            title,
            "No fragment-length values were available in the selected plotting range.",
        )
        return

    axis.set_xlabel("Fragment length (bp)")
    axis.set_ylabel("Count (log scale)" if log_count else "Count")
    axis.set_title(title)

    if log_count:
        axis.set_yscale("log")

    if x_min_bp is not None and x_max_bp is not None:
        axis.set_xlim(int(x_min_bp), int(x_max_bp))

    if minor_tick_bp is not None and int(minor_tick_bp) > 0:
        axis.xaxis.set_minor_locator(MultipleLocator(int(minor_tick_bp)))
        axis.tick_params(
            axis="x",
            which="minor",
            length=3,
            width=0.7,
        )
        axis.grid(
            axis="x",
            which="minor",
            linestyle=":",
            alpha=0.18,
        )

    if reference_bp is not None:
        reference_bp = int(reference_bp)
        axis.axvline(
            reference_bp,
            linestyle=":",
            linewidth=1.6,
            label=f"Reference: {reference_bp} bp",
        )

    axis.grid(axis="y", which="both", alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(output_path, dpi=180)
    plt.close(figure)



def backend(settings_path: Path, input_dir: Path, output_dir: Path, dry_run: bool) -> None:
    if pysam is None and not dry_run:
        raise ModuleNotFoundError("pysam is required in the WSL1 backend.")
    settings, _ = load_config(settings_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(output_dir / "04_BAM_MAPPING_AND_FRAGMENT_QC.log")
    require_tools(settings, ["samtools"], dry_run)

    inputs = discover_bams(input_dir, recursive=True)
    if inputs.empty:
        raise FileNotFoundError("No BAM files were found in the selected Step 04 input folder.")
    samtools = str(settings["tools"]["samtools"])
    target_bed = str(settings["references"]["targets_bed"]).strip()
    target_bed_path = (
        normalized_input_path(target_bed)
        if is_nonempty(target_bed)
        else None
    )
    if target_bed_path is not None and not dry_run and not target_bed_path.exists():
        raise FileNotFoundError(
            f"Optional target BED was selected but was not found: {target_bed_path}"
        )

    qc = settings["bam_qc"]
    genome_bin_depth_enabled = bool(qc['genome_bin_depth_enabled'])
    genome_bin_size_bp = int(qc['genome_bin_size_bp'])
    if genome_bin_depth_enabled and genome_bin_size_bp < 10000:
        raise ValueError(
            "Genome bin size must be at least 10,000 bp. Smaller bins would "
            "create an unnecessarily large human-genome table."
        )

    high_depth_enabled = bool(
        qc['infer_high_depth_regions_enabled']
    )
    high_depth_threshold = int(qc['high_depth_threshold'])
    high_depth_minimum_region_length_bp = int(
        qc['high_depth_minimum_region_length_bp']
    )
    high_depth_maximum_merge_gap_bp = int(
        qc['high_depth_maximum_merge_gap_bp']
    )
    high_depth_consensus_enabled = bool(
        qc['high_depth_consensus_enabled']
    )
    high_depth_consensus_minimum_sample_percent = float(
        qc['high_depth_consensus_minimum_sample_percent']
    )

    if high_depth_threshold < 1:
        raise ValueError("High-depth threshold X must be at least 1x.")
    if high_depth_minimum_region_length_bp < 1:
        raise ValueError(
            "Minimum inferred high-depth region length must be at least 1 bp."
        )
    if high_depth_maximum_merge_gap_bp < 0:
        raise ValueError(
            "Maximum low-depth gap to bridge cannot be negative."
        )
    if not (
        0.0 < high_depth_consensus_minimum_sample_percent <= 100.0
    ):
        raise ValueError(
            "Consensus minimum sample support must be >0 and <=100 percent."
        )

    fragment_log_count_enabled = bool(
        qc['fragment_log_count_plot_enabled']
    )
    fragment_log_xmin_bp = int(
        qc['fragment_log_plot_xmin_bp']
    )
    fragment_log_xmax_bp = int(
        qc['fragment_log_plot_xmax_bp']
    )
    fragment_log_minor_tick_bp = int(
        qc['fragment_log_plot_minor_tick_bp']
    )
    fragment_log_reference_bp = int(
        qc['fragment_log_plot_reference_bp']
    )

    if fragment_log_xmin_bp < 0:
        raise ValueError(
            "Fragment log(count) plot X minimum must be >= 0 bp."
        )
    if fragment_log_xmax_bp <= fragment_log_xmin_bp:
        raise ValueError(
            "Fragment log(count) plot X maximum must be greater than X minimum."
        )
    if fragment_log_minor_tick_bp < 1:
        raise ValueError(
            "Fragment log(count) plot minor tick spacing must be at least 1 bp."
        )
    if not (
        fragment_log_xmin_bp
        <= fragment_log_reference_bp
        <= fragment_log_xmax_bp
    ):
        raise ValueError(
            "Fragment reference-line position must lie within the selected "
            "log(count) plot X range."
        )

    output_rows: list[dict] = []
    metric_rows: list[dict] = []
    validation_rows: list[dict] = []
    all_fragment_tables: list[pd.DataFrame] = []
    genome_bin_plots: list[Path] = []
    high_depth_plots: list[Path] = []
    high_depth_summary_rows: list[dict[str, object]] = []
    per_sample_high_depth_beds: list[tuple[str, Path]] = []

    for row in inputs.to_dict(orient="records"):
        sample_id = row["SAMPLE_ID"]
        sample_dir = output_dir / sample_id
        sample_dir.mkdir(parents=True, exist_ok=True)
        bam = normalized_input_path(row["BAM"])
        flagstat = sample_dir / f"{sample_id}.flagstat.txt"
        stats = sample_dir / f"{sample_id}.samtools_stats.txt"
        log_file = output_dir / "logs" / f"{sample_id}.log"

        validation = ensure_bam_ready_for_qc(
            bam,
            settings,
            log_file,
            dry_run,
        )
        validation_rows.append(
            {
                "SAMPLE_ID": sample_id,
                **validation,
            }
        )

        command = (
            f"{quote(samtools)} flagstat -@ {threads(settings)} {quote(bam)} "
            f"> {quote(flagstat)} && "
            f"{quote(samtools)} stats -@ {threads(settings)} {quote(bam)} "
            f"> {quote(stats)}"
        )
        run_command(
            command,
            log_file,
            dry_run=dry_run,
            shell=True,
        )

        metrics = {
            "MEAN_DEPTH": float("nan"),
            "MEDIAN_DEPTH": float("nan"),
            "DEPTH_CV": float("nan"),
            "PERCENT_BASES_AT_100X": float("nan"),
            "PERCENT_BASES_AT_500X": float("nan"),
            "DEPTH_TOTAL_POSITIONS": 0,
            "DEPTH_OBSERVED_POSITIONS": 0,
            "ZERO_DEPTH_POSITIONS": 0,
            "FRAGMENT_COUNT": 0,
            "MEAN_FRAGMENT_LENGTH": float("nan"),
            "MEDIAN_FRAGMENT_LENGTH": float("nan"),
            "SHORT_FRAGMENT_FRACTION": float("nan"),
            "MONONUCLEOSOME_FRACTION": float("nan"),
        }
        fragment_table_path = sample_dir / f"{sample_id}.fragment_lengths.tsv"
        fragment_plot = sample_dir / f"{sample_id}.fragment_lengths.png"

        (
            depth_metrics,
            depth_histogram_path,
            depth_summary_path,
            bin_outputs,
            high_depth_outputs,
        ) = stream_depth_metrics(
            bam,
            settings,
            target_bed_path,
            sample_dir,
            log_file,
            dry_run,
            (
                genome_bin_size_bp
                if genome_bin_depth_enabled and target_bed_path is None
                else None
            ),
        )
        metrics.update(depth_metrics)

        if genome_bin_depth_enabled and target_bed_path is not None:
            bin_outputs = stream_genome_bin_depth(
                bam,
                settings,
                sample_dir,
                log_file,
                genome_bin_size_bp,
                dry_run,
            )

        # If ordinary depth was restricted by an existing BED, infer probable
        # high-depth targets in one separate whole-genome streaming pass.
        if (
            high_depth_enabled
            and target_bed_path is not None
            and high_depth_outputs is None
        ):
            high_depth_outputs = stream_high_depth_region_inference(
                bam,
                settings,
                sample_dir,
                log_file,
                dry_run,
            )

        if not dry_run:
            lengths, alignment_metrics = scan_bam(bam, settings)
            metrics.update(alignment_metrics)
            if lengths:
                series = pd.Series(lengths, dtype=float)
                short_count = int((series <= int(qc["short_fragment_maximum"])).sum())
                mono_count = int(
                    (
                        (series >= int(qc["mononucleosome_minimum"]))
                        & (series <= int(qc["mononucleosome_maximum"]))
                    ).sum()
                )
                metrics.update({
                    "FRAGMENT_COUNT": len(lengths),
                    "MEAN_FRAGMENT_LENGTH": float(series.mean()),
                    "MEDIAN_FRAGMENT_LENGTH": float(series.median()),
                    "SHORT_FRAGMENT_FRACTION": short_count / len(lengths),
                    "MONONUCLEOSOME_FRACTION": mono_count / len(lengths),
                })
                counts = Counter(lengths)
                table = pd.DataFrame(
                    sorted(counts.items()),
                    columns=["FRAGMENT_LENGTH", "COUNT"],
                )
                table.insert(0, "SAMPLE_ID", sample_id)
                write_tsv(table, fragment_table_path)
                all_fragment_tables.append(table)

                figure, axis = plt.subplots(figsize=(10, 6))
                axis.hist(lengths, bins=range(30, 401, 2))
                axis.set_xlabel("Fragment length (bp)")
                axis.set_ylabel("Count")
                axis.set_title(f"{sample_id}: cfDNA fragment lengths")
                axis.grid(axis="y", alpha=0.25)
                figure.tight_layout()
                figure.savefig(fragment_plot, dpi=180)
                plt.close(figure)

        metric_rows.append({"SAMPLE_ID": sample_id, **metrics})
        updated = dict(row)
        updated["QC_FLAGSTAT"] = str(flagstat)
        updated["QC_SAMTOOLS_STATS"] = str(stats)
        updated["DEPTH_HISTOGRAM"] = str(depth_histogram_path)
        updated["DEPTH_SUMMARY"] = str(depth_summary_path)

        if bin_outputs is not None:
            (
                genome_bin_table_path,
                genome_bin_linear_plot,
                genome_bin_log_plot,
                genome_bin_top_plot,
                genome_bin_chromosome_plot,
            ) = bin_outputs
            updated["GENOME_BIN_DEPTH_TABLE"] = str(genome_bin_table_path)
            updated["GENOME_BIN_DEPTH_PLOT"] = str(genome_bin_linear_plot)
            updated["GENOME_BIN_DEPTH_LOG1P_PLOT"] = str(genome_bin_log_plot)
            updated["GENOME_BIN_TOP_PLOT"] = str(genome_bin_top_plot)
            updated["GENOME_BIN_CHROMOSOME_STACKED_PLOT"] = str(
                genome_bin_chromosome_plot
            )
            genome_bin_plots.extend(
                [
                    genome_bin_linear_plot,
                    genome_bin_log_plot,
                    genome_bin_top_plot,
                    genome_bin_chromosome_plot,
                ]
            )
        else:
            updated["GENOME_BIN_DEPTH_TABLE"] = ""
            updated["GENOME_BIN_DEPTH_PLOT"] = ""
            updated["GENOME_BIN_DEPTH_LOG1P_PLOT"] = ""
            updated["GENOME_BIN_TOP_PLOT"] = ""
            updated["GENOME_BIN_CHROMOSOME_STACKED_PLOT"] = ""

        if high_depth_outputs is not None:
            (
                high_depth_bed,
                high_depth_tsv,
                high_depth_summary,
                high_depth_length_plot,
                high_depth_depth_plot,
                high_depth_summary_row,
            ) = high_depth_outputs

            updated["INFERRED_HIGH_DEPTH_BED"] = str(high_depth_bed)
            updated["INFERRED_HIGH_DEPTH_TSV"] = str(high_depth_tsv)
            updated["INFERRED_HIGH_DEPTH_SUMMARY"] = str(high_depth_summary)
            updated["INFERRED_HIGH_DEPTH_REGION_LENGTH_PLOT"] = str(
                high_depth_length_plot
            )
            updated["INFERRED_HIGH_DEPTH_REGION_DEPTH_PLOT"] = str(
                high_depth_depth_plot
            )

            per_sample_high_depth_beds.append(
                (sample_id, high_depth_bed)
            )
            high_depth_summary_rows.append(
                dict(high_depth_summary_row)
            )
            high_depth_plots.extend(
                [
                    high_depth_length_plot,
                    high_depth_depth_plot,
                ]
            )
        else:
            updated["INFERRED_HIGH_DEPTH_BED"] = ""
            updated["INFERRED_HIGH_DEPTH_TSV"] = ""
            updated["INFERRED_HIGH_DEPTH_SUMMARY"] = ""
            updated["INFERRED_HIGH_DEPTH_REGION_LENGTH_PLOT"] = ""
            updated["INFERRED_HIGH_DEPTH_REGION_DEPTH_PLOT"] = ""

        updated["FRAGMENT_LENGTH_TABLE"] = str(fragment_table_path)
        updated["FRAGMENT_LENGTH_PLOT"] = str(fragment_plot)
        output_rows.append(updated)

    qc_manifest = pd.DataFrame(output_rows)
    metrics = pd.DataFrame(metric_rows)
    validation_table = pd.DataFrame(validation_rows)
    write_tsv(qc_manifest, output_dir / "bam_qc_results.tsv")
    write_tsv(metrics, output_dir / "bam_mapping_and_fragment_qc_metrics.tsv")
    write_tsv(validation_table, output_dir / "bam_input_validation.tsv")

    high_depth_summary_table = pd.DataFrame(high_depth_summary_rows)
    write_tsv(
        high_depth_summary_table,
        output_dir / "inferred_high_depth_regions_summary.tsv",
    )

    consensus_outputs = None
    if high_depth_enabled and high_depth_consensus_enabled:
        consensus_outputs = build_consensus_high_depth_bed(
            per_sample_high_depth_beds,
            output_dir,
            high_depth_threshold,
            high_depth_consensus_minimum_sample_percent,
            high_depth_minimum_region_length_bp,
            dry_run,
        )

    inferred_target_size_plot = (
        output_dir / "inferred_high_depth_target_size_by_sample.png"
    )
    if high_depth_summary_table.empty:
        save_placeholder_plot(
            inferred_target_size_plot,
            "Inferred high-depth target size by sample",
            "High-depth target inference was disabled or produced no summaries.",
        )
    else:
        save_bar_plot(
            high_depth_summary_table["SAMPLE_ID"].astype(str).tolist(),
            pd.to_numeric(
                high_depth_summary_table["TOTAL_INFERRED_REGION_BP"],
                errors="coerce",
            ).fillna(0).tolist(),
            inferred_target_size_plot,
            (
                f"Inferred genomic span at depth >= "
                f"{high_depth_threshold}x"
            ),
            "Inferred region span (bp)",
            rotate=60,
        )
    if high_depth_enabled:
        high_depth_plots.append(inferred_target_size_plot)

    if consensus_outputs is not None:
        (
            consensus_bed,
            consensus_tsv,
            consensus_summary,
            consensus_plot,
            _consensus_summary_row,
        ) = consensus_outputs
        high_depth_plots.append(consensus_plot)

    plots: list[Path] = []
    for column, title, y_label, filename in [
        ("MEAN_DEPTH", "Mean sequencing depth", "Mean depth", "mean_depth.png"),
        ("SHORT_FRAGMENT_FRACTION", "Short cfDNA fragment fraction", "Fraction", "short_fragment_fraction.png"),
        ("SOFT_CLIPPED_PERCENT", "Soft-clipped alignment records", "Percent", "soft_clipped_percent.png"),
        ("SUPPLEMENTARY_PERCENT", "Supplementary alignment records", "Percent", "supplementary_percent.png"),
        ("DISCORDANT_RECORD_PERCENT", "Discordant paired alignment records", "Percent", "discordant_percent.png"),
    ]:
        plot = output_dir / filename
        if metrics.empty or column not in metrics.columns:
            save_placeholder_plot(plot, title, "No metrics available.")
        else:
            save_bar_plot(
                metrics["SAMPLE_ID"].astype(str).tolist(),
                pd.to_numeric(metrics[column], errors="coerce").fillna(0).tolist(),
                plot, title, y_label, rotate=60,
            )
        plots.append(plot)

    combined_plot = output_dir / "all_fragment_length_distributions.png"
    save_combined_fragment_length_plot(
        all_fragment_tables,
        combined_plot,
        log_count=False,
    )
    plots.append(combined_plot)

    fragment_log_plot = (
        output_dir / "all_fragment_length_distributions_log_count.png"
    )
    if fragment_log_count_enabled:
        save_combined_fragment_length_plot(
            all_fragment_tables,
            fragment_log_plot,
            log_count=True,
            x_min_bp=fragment_log_xmin_bp,
            x_max_bp=fragment_log_xmax_bp,
            minor_tick_bp=fragment_log_minor_tick_bp,
            reference_bp=fragment_log_reference_bp,
        )
        plots.append(fragment_log_plot)

    plots.extend(genome_bin_plots)
    plots.extend(high_depth_plots)

    write_step_status(
        output_dir,
        SPEC.title,
        "PASS",
        f"Validated coordinate sorting/BAM indexes and generated memory-safe "
        f"streaming depth, fragment, abnormal-alignment QC, and "
        f"{'high-depth inferred-target BEDs' if high_depth_enabled else 'standard QC outputs'} "
        f"for {len(qc_manifest)} BAM file(s).",
        len(qc_manifest),
        plots,
    )
    print(output_dir / "bam_qc_results.tsv")



STEP_GUI = {'environment': 'ctdna_core',
 'fields': [{'setting': '__input_dir__',
             'label': 'Validated/full BAM folder',
             'type': 'folder',
             'required': True,
             'scan_globs': ['*.bam'],
             'accept_name_contains_any': ['analysis_ready', 'validated'],
             'reject_name_contains': ['abnormal', 'aberrant'],
             'help': 'Use complete analysis-ready/validated BAMs. Abnormal/aberrant BAM subsets are rejected.',
             'section': 'INPUTS AND REFERENCES'},
            {'setting': 'references.targets_bed',
             'label': 'Optional known target/capture BED',
             'type': 'file',
             'required': False,
             'allowed_suffixes': ['.bed'],
             'filetypes': [('BED', '*.bed'), ('All files', '*.*')],
             'button_text': 'Browse target BED',
             'help': 'Leave blank for genome-wide depth. This is a single file, so it is selected explicitly.',
             'section': 'INPUTS AND REFERENCES'},
            {'setting': 'bam_qc.minimum_mapping_quality',
             'label': 'Minimum mapping quality',
             'type': 'int',
             'required': True,
             'section': 'MAPPING / BASE QUALITY'},
            {'setting': 'bam_qc.minimum_base_quality',
             'label': 'Minimum base quality',
             'type': 'int',
             'required': True,
             'section': 'MAPPING / BASE QUALITY'},
            {'setting': 'bam_qc.fragment_minimum_length',
             'label': 'Minimum fragment length (bp)',
             'type': 'int',
             'required': True,
             'section': 'FRAGMENT QC'},
            {'setting': 'bam_qc.fragment_maximum_length',
             'label': 'Maximum fragment length (bp)',
             'type': 'int',
             'required': True,
             'section': 'FRAGMENT QC'},
            {'setting': 'bam_qc.short_fragment_maximum',
             'label': 'Short-fragment maximum (bp)',
             'type': 'int',
             'required': True,
             'section': 'FRAGMENT QC'},
            {'setting': 'bam_qc.mononucleosome_minimum',
             'label': 'Mononucleosome minimum (bp)',
             'type': 'int',
             'required': True,
             'section': 'FRAGMENT QC'},
            {'setting': 'bam_qc.mononucleosome_maximum',
             'label': 'Mononucleosome maximum (bp)',
             'type': 'int',
             'required': True,
             'section': 'FRAGMENT QC'},
            {'setting': 'bam_qc.maximum_fragments_to_analyze',
             'label': 'Maximum fragments analyzed',
             'type': 'int',
             'required': True,
             'section': 'FRAGMENT QC'},
            {'setting': 'bam_qc.genome_bin_depth_enabled',
             'label': 'Compute genome-wide fixed-bin depth QC',
             'type': 'bool',
             'section': 'GENOME-BIN DEPTH'},
            {'setting': 'bam_qc.genome_bin_size_bp',
             'label': 'Genome bin size (bp)',
             'type': 'int',
             'required': True,
             'section': 'GENOME-BIN DEPTH'},
            {'setting': 'bam_qc.infer_high_depth_regions_enabled',
             'label': 'Infer probable targeted/high-coverage regions and create BED',
             'type': 'bool',
             'help': 'Streams base-level depth and retains bases with depth >= X. This is an empirical '
                     'high-coverage BED, not necessarily the manufacturer bait design.',
             'section': 'HIGH-DEPTH REGION INFERENCE'},
            {'setting': 'bam_qc.high_depth_threshold',
             'label': 'High-depth threshold X (base qualifies at depth >= X)',
             'type': 'int',
             'required': True,
             'section': 'HIGH-DEPTH REGION INFERENCE'},
            {'setting': 'bam_qc.high_depth_minimum_region_length_bp',
             'label': 'Minimum inferred region length (bp)',
             'type': 'int',
             'required': True,
             'section': 'HIGH-DEPTH REGION INFERENCE'},
            {'setting': 'bam_qc.high_depth_maximum_merge_gap_bp',
             'label': 'Maximum low-depth gap to bridge (bp)',
             'type': 'int',
             'required': True,
             'section': 'HIGH-DEPTH REGION INFERENCE'},
            {'setting': 'bam_qc.high_depth_consensus_enabled',
             'label': 'Create consensus inferred-target BED across BAM samples',
             'type': 'bool',
             'section': 'HIGH-DEPTH REGION INFERENCE'},
            {'setting': 'bam_qc.high_depth_consensus_minimum_sample_percent',
             'label': 'Consensus minimum sample support (%)',
             'type': 'float',
             'required': True,
             'section': 'HIGH-DEPTH REGION INFERENCE',
             'help': 'Percentage of BAM samples that must support a region for it to appear in the consensus '
                     'inferred-target BED.'},
            {'setting': 'bam_qc.fragment_log_count_plot_enabled',
             'label': 'log(count): create second cfDNA fragment-length plot',
             'type': 'bool',
             'help': 'Preserves the ordinary linear-count plot and optionally adds a second plot with logarithmic '
                     'Y axis.',
             'section': 'FRAGMENT QC'},
            {'setting': 'bam_qc.fragment_log_plot_xmin_bp',
             'label': 'Log fragment plot X start (bp)',
             'type': 'int',
             'required': True,
             'section': 'FRAGMENT QC'},
            {'setting': 'bam_qc.fragment_log_plot_xmax_bp',
             'label': 'Log fragment plot X end (bp)',
             'type': 'int',
             'required': True,
             'section': 'FRAGMENT QC'},
            {'setting': 'bam_qc.fragment_log_plot_minor_tick_bp',
             'label': 'Log plot minor X tick every (bp)',
             'type': 'int',
             'required': True,
             'section': 'FRAGMENT QC'},
            {'setting': 'bam_qc.fragment_log_plot_reference_bp',
             'label': 'Dotted fragment reference line (bp)',
             'type': 'int',
             'required': True,
             'help': 'Default 166 bp, approximately the dominant mononucleosomal cfDNA fragment length.',
             'section': 'FRAGMENT QC'}],
 'explanation': 'Validates complete BAMs, checks coordinate sorting, creates/rebuilds BAM indexes when needed, '
                'and computes mapping, fragment-length, depth and abnormal-alignment QC. Optional fixed-bin depth '
                'and empirical high-depth BED inference are memory-safe streaming analyses.'}

if __name__ == "__main__":
    launch_step(SPEC, backend)
