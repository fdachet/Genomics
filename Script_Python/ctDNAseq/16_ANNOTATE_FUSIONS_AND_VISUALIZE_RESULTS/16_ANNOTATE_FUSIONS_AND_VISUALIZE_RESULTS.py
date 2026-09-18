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
    parser.add_argument('--annotation-full-integrated-events-tsv', dest='__cfg__annotation_full__integrated_events_tsv', type=str, default='', help='Override annotation_full.integrated_events_tsv for this execution.')
    parser.add_argument('--annotation-full-derivative-chromosomes-tsv', dest='__cfg__annotation_full__derivative_chromosomes_tsv', type=str, default='', help='Override annotation_full.derivative_chromosomes_tsv for this execution.')
    parser.add_argument('--annotation-full-graph-nodes-tsv', dest='__cfg__annotation_full__graph_nodes_tsv', type=str, default='', help='Override annotation_full.graph_nodes_tsv for this execution.')
    parser.add_argument('--annotation-full-graph-edges-tsv', dest='__cfg__annotation_full__graph_edges_tsv', type=str, default='', help='Override annotation_full.graph_edges_tsv for this execution.')
    parser.add_argument('--annotation-full-gene-gtf', dest='__cfg__annotation_full__gene_gtf', type=str, default='', help='Override annotation_full.gene_gtf for this execution.')
    parser.add_argument('--annotation-run-local-gtf-variant-annotation', dest='__cfg__annotation__run_local_gtf_variant_annotation', type=_parse_cli_bool, default=True, help='Override annotation.run_local_gtf_variant_annotation for this execution.')
    parser.add_argument('--annotation-nearest-gene-maximum-distance-bp', dest='__cfg__annotation__nearest_gene_maximum_distance_bp', type=int, default=1000000, help='Override annotation.nearest_gene_maximum_distance_bp for this execution.')
    parser.add_argument('--annotation-maximum-table-rows', dest='__cfg__annotation__maximum_table_rows', type=int, default=300, help='Override annotation.maximum_table_rows for this execution.')
    parser.add_argument('--annotation-run-vep', dest='__cfg__annotation__run_vep', type=_parse_cli_bool, default=False, help='Override annotation.run_vep for this execution.')
    parser.add_argument('--annotation-full-pass-vcf-folder', dest='__cfg__annotation_full__pass_vcf_folder', type=str, default='', help='Override annotation_full.pass_vcf_folder for this execution.')
    parser.add_argument('--references-vep-cache', dest='__cfg__references__vep_cache', type=str, default='', help='Override references.vep_cache for this execution.')
    parser.add_argument('--references-vep-species', dest='__cfg__references__vep_species', type=str, default='homo_sapiens', help='Override references.vep_species for this execution.')
    parser.add_argument('--references-vep-assembly', dest='__cfg__references__vep_assembly', type=str, default='GRCh38', help='Override references.vep_assembly for this execution.')
    return parser



DEFAULT_SETTINGS = {'project': {'name': 'ctDNA_Tumor_Genome_GUI_Pipeline', 'temporary_directory': 'work/tmp'},
 'execution': {'wsl_distribution': '',
               'micromamba_environment': 'ctdna_core',
               'python_executable_in_wsl': 'python3',
               'micromamba_executable': '',
               'micromamba_root_prefix': ''},
 'references': {'fasta': '',
                'targets_bed': '',
                'germline_resource_vcf': '',
                'panel_of_normals_vcf': '',
                'gene_gtf': ''},
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
                'pass_vcf_files': ''},
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
 'annotation_full': {},
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


import bisect
import gzip
import html
import json
import math
import re
import shutil
import textwrap
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

try:
    import pysam
except ModuleNotFoundError:
    pysam = None



SPEC = StepSpecification(
    number=16,
    title="16_ANNOTATE_FUSIONS_AND_VISUALIZE_RESULTS",
    description=(
        "Annotate breakpoint neighborhoods and molecularly validated small variants locally from the GTF, "
        "optionally add VEP annotation, create chromosome-level event views, collect "
        "all QC plots, run MultiQC, and build the final HTML report."
    ),
    default_input_dir="input",
    default_output_dir="output",
)


def optional_table(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, sep="\t", low_memory=False)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def parse_attributes(text: str) -> dict[str, str]:
    output: dict[str, str] = {}
    for item in text.split(";"):
        item = item.strip()
        if not item or " " not in item:
            continue
        key, value = item.split(" ", 1)
        output[key] = value.strip().strip('"')
    return output


def safe_chromosome(value: object) -> str:
    """Return a usable chromosome string, or an empty string for missing values."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "na"} else text


def safe_position(value: object) -> int | None:
    """Convert a coordinate to a positive integer without crashing on NaN/mixed rows."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return int(number)


def _unique_join(values: list[str]) -> str:
    cleaned = sorted({str(value).strip() for value in values if str(value).strip()})
    return ";".join(cleaned)


def load_gtf_resources(
    gtf_path: Path,
    chromosomes: set[str],
    variant_positions: dict[str, list[int]] | None = None,
) -> tuple[
    dict[str, list[tuple[int, int, str]]],
    dict[tuple[str, int], list[dict[str, str]]],
]:
    """
    Scan the GTF once.

    * Always collect compact gene intervals for nearest-gene annotation.
    * When variant_positions is supplied, collect only GTF features that actually
      overlap one of the Step 08 variant positions. This keeps the local annotation
      lightweight and avoids building a large whole-genome transcript database.
    """
    genes: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    overlaps: dict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
    if not gtf_path.exists():
        return genes, overlaps

    targets = set(chromosomes)
    positions_by_chrom = variant_positions or {}
    interesting_features = {
        "gene", "transcript", "exon", "CDS", "UTR",
        "five_prime_utr", "three_prime_utr",
        "start_codon", "stop_codon",
    }

    opener = gzip.open if gtf_path.suffix.lower() == ".gz" else open
    with opener(gtf_path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            pieces = line.rstrip("\n").split("\t")
            if len(pieces) < 9:
                continue

            chromosome = pieces[0]
            if targets and chromosome not in targets:
                continue

            feature = pieces[2]
            if feature not in interesting_features:
                continue

            try:
                start = int(pieces[3])
                end = int(pieces[4])
            except ValueError:
                continue
            strand = pieces[6]

            # Gene intervals are small enough to retain and are needed for
            # nearest-gene annotation of breakpoints and small variants.
            attrs: dict[str, str] | None = None
            if feature == "gene":
                attrs = parse_attributes(pieces[8])
                gene_name = attrs.get("gene_name") or attrs.get("gene_id") or "UNKNOWN_GENE"
                genes[chromosome].append((start, end, gene_name))

            positions = positions_by_chrom.get(chromosome, [])
            if not positions:
                continue

            left = bisect.bisect_left(positions, start)
            right = bisect.bisect_right(positions, end)
            if right <= left:
                continue

            if attrs is None:
                attrs = parse_attributes(pieces[8])
            record = {
                "FEATURE": feature,
                "GENE_ID": attrs.get("gene_id", ""),
                "GENE_NAME": attrs.get("gene_name") or attrs.get("gene_id", ""),
                "TRANSCRIPT_ID": attrs.get("transcript_id", ""),
                "TRANSCRIPT_NAME": attrs.get("transcript_name", ""),
                "EXON_ID": attrs.get("exon_id", ""),
                "EXON_NUMBER": attrs.get("exon_number", ""),
                "STRAND": strand,
            }
            for position in positions[left:right]:
                overlaps[(chromosome, position)].append(record)

    for chromosome in genes:
        genes[chromosome].sort(key=lambda item: item[0])
    return genes, overlaps


def load_genes(
    gtf_path: Path,
    chromosomes: set[str],
) -> dict[str, list[tuple[int, int, str]]]:
    genes, _ = load_gtf_resources(gtf_path, chromosomes, None)
    return genes



def nearest_gene(
    genes: dict[str, list[tuple[int, int, str]]],
    chromosome: str,
    position: int,
    maximum_distance: int,
) -> tuple[str, int | str]:
    records = genes.get(chromosome, [])
    if not records:
        return "", ""
    # records are already sorted by start coordinate; bisect them directly so
    # thousands of variant queries do not rebuild a gene-start list each time.
    index = bisect.bisect_left(records, (position,))
    candidates = records[max(0, index - 20): min(len(records), index + 20)]
    best_name = ""
    best_distance = maximum_distance + 1
    for start, end, name in candidates:
        if start <= position <= end:
            return name, 0
        distance = min(abs(position - start), abs(position - end))
        if distance < best_distance:
            best_name, best_distance = name, distance
    return (best_name, best_distance) if best_distance <= maximum_distance else ("", "")


def annotate_breakpoints(
    breakpoints: pd.DataFrame,
    genes: dict[str, list[tuple[int, int, str]]],
    maximum_distance: int,
) -> pd.DataFrame:
    if breakpoints.empty:
        return breakpoints
    rows: list[dict] = []
    for row in breakpoints.to_dict(orient="records"):
        chrom1 = safe_chromosome(row.get("CHROM1"))
        chrom2 = safe_chromosome(row.get("CHROM2"))
        pos1 = safe_position(row.get("POS1"))
        pos2 = safe_position(row.get("POS2"))
        gene1, distance1 = (
            nearest_gene(genes, chrom1, pos1, maximum_distance)
            if chrom1 and pos1 is not None else ("", "")
        )
        gene2, distance2 = (
            nearest_gene(genes, chrom2, pos2, maximum_distance)
            if chrom2 and pos2 is not None else ("", "")
        )
        rows.append(
            {
                **row,
                "NEAREST_GENE_SIDE1": gene1,
                "DISTANCE_TO_GENE_SIDE1_BP": distance1,
                "NEAREST_GENE_SIDE2": gene2,
                "DISTANCE_TO_GENE_SIDE2_BP": distance2,
            }
        )
    return pd.DataFrame(rows)


def annotate_integrated_events_nearest_gene(
    events: pd.DataFrame,
    genes: dict[str, list[tuple[int, int, str]]],
    maximum_distance: int,
) -> pd.DataFrame:
    """Annotate only rows that actually contain a valid CHROM/POS coordinate."""
    if events.empty:
        return events.copy()

    output = events.copy()
    names: list[str] = []
    distances: list[object] = []
    for row in output.to_dict(orient="records"):
        chromosome = safe_chromosome(row.get("CHROM"))
        position = safe_position(row.get("POS"))
        if not chromosome or position is None:
            names.append("")
            distances.append("")
            continue
        name, distance = nearest_gene(
            genes, chromosome, position, maximum_distance
        )
        names.append(name)
        distances.append(distance)

    output["NEAREST_GENE"] = names
    output["DISTANCE_TO_GENE_BP"] = distances
    return output


def extract_small_variant_events(events: pd.DataFrame) -> pd.DataFrame:
    """Return valid Step 08 small-variant rows embedded by Step 09."""
    if events.empty or "EVENT_TYPE" not in events.columns:
        return pd.DataFrame()
    subset = events.loc[
        events["EVENT_TYPE"].astype(str).str.upper() == "SMALL_VARIANT"
    ].copy()
    if subset.empty:
        return subset

    valid_rows: list[dict] = []
    for row in subset.to_dict(orient="records"):
        chromosome = safe_chromosome(row.get("CHROM"))
        position = safe_position(row.get("POS"))
        if not chromosome or position is None:
            continue
        updated = dict(row)
        updated["CHROM"] = chromosome
        updated["POS"] = position
        valid_rows.append(updated)
    return pd.DataFrame(valid_rows)


def variant_positions_by_chromosome(variants: pd.DataFrame) -> dict[str, list[int]]:
    positions: dict[str, set[int]] = defaultdict(set)
    if variants.empty:
        return {}
    for row in variants.to_dict(orient="records"):
        chromosome = safe_chromosome(row.get("CHROM"))
        position = safe_position(row.get("POS"))
        if chromosome and position is not None:
            positions[chromosome].add(position)
    return {chrom: sorted(values) for chrom, values in positions.items()}


def local_gtf_context(features: list[dict[str, str]]) -> str:
    types = {str(item.get("FEATURE", "")) for item in features}
    if "CDS" in types or "start_codon" in types or "stop_codon" in types:
        return "CODING_REGION"
    if "five_prime_utr" in types or "three_prime_utr" in types or "UTR" in types:
        return "UTR"
    if "exon" in types:
        return "EXON_NON_CDS"
    if "transcript" in types:
        return "TRANSCRIPT_BODY_NON_EXONIC"
    if "gene" in types:
        return "GENE_OVERLAP"
    return "INTERGENIC"


def annotate_small_variants_from_gtf(
    variants: pd.DataFrame,
    genes: dict[str, list[tuple[int, int, str]]],
    feature_overlaps: dict[tuple[str, int], list[dict[str, str]]],
    maximum_distance: int,
) -> pd.DataFrame:
    """
    Lightweight genomic-context annotation using only the selected GTF.

    This intentionally does NOT claim amino-acid consequence, pathogenicity,
    ClinVar status, or population frequency. Those require resources such as VEP.
    """
    if variants.empty:
        return pd.DataFrame()

    rows: list[dict] = []
    for row in variants.to_dict(orient="records"):
        chromosome = safe_chromosome(row.get("CHROM"))
        position = safe_position(row.get("POS"))
        if not chromosome or position is None:
            continue

        features = feature_overlaps.get((chromosome, position), [])
        nearest_name, nearest_distance = nearest_gene(
            genes, chromosome, position, maximum_distance
        )

        rows.append(
            {
                **row,
                "LOCAL_GTF_CONTEXT": local_gtf_context(features),
                "OVERLAPPING_GENE_NAMES": _unique_join(
                    [item.get("GENE_NAME", "") for item in features]
                ),
                "OVERLAPPING_GENE_IDS": _unique_join(
                    [item.get("GENE_ID", "") for item in features]
                ),
                "OVERLAPPING_TRANSCRIPT_IDS": _unique_join(
                    [item.get("TRANSCRIPT_ID", "") for item in features]
                ),
                "OVERLAPPING_TRANSCRIPT_NAMES": _unique_join(
                    [item.get("TRANSCRIPT_NAME", "") for item in features]
                ),
                "OVERLAPPING_EXON_IDS": _unique_join(
                    [item.get("EXON_ID", "") for item in features]
                ),
                "OVERLAPPING_EXON_NUMBERS": _unique_join(
                    [item.get("EXON_NUMBER", "") for item in features]
                ),
                "OVERLAPPING_GTF_FEATURE_TYPES": _unique_join(
                    [item.get("FEATURE", "") for item in features]
                ),
                "OVERLAPPING_STRANDS": _unique_join(
                    [item.get("STRAND", "") for item in features]
                ),
                "NEAREST_GENE_GTF": nearest_name,
                "DISTANCE_TO_NEAREST_GENE_BP_GTF": nearest_distance,
                "LOCAL_GTF_ANNOTATION_NOTE": (
                    "GTF-only genomic context; does not predict amino-acid change, "
                    "pathogenicity, population frequency, or clinical significance."
                ),
            }
        )
    return pd.DataFrame(rows)



def parse_vep_vcf(path: Path, sample_id: str) -> pd.DataFrame:
    if pysam is None or not path.exists():
        return pd.DataFrame()
    rows: list[dict] = []
    with pysam.VariantFile(path) as vcf:
        description = (
            str(vcf.header.info["CSQ"].description)
            if "CSQ" in vcf.header.info else ""
        )
        fields = (
            description.split("Format: ", 1)[1].strip().strip('"').split("|")
            if "Format: " in description else []
        )
        field_index = {name: index for index, name in enumerate(fields)}
        for record in vcf:
            csq_values = record.info.get("CSQ", ())
            if isinstance(csq_values, str):
                csq_values = (csq_values,)
            first = str(csq_values[0]).split("|") if csq_values else []
            def get(name: str) -> str:
                index = field_index.get(name)
                return first[index] if index is not None and index < len(first) else ""
            rows.append(
                {
                    "SAMPLE_ID": sample_id,
                    "CHROM": record.chrom,
                    "POS": int(record.pos),
                    "REF": record.ref,
                    "ALT": record.alts[0] if record.alts else "",
                    "GENE": get("SYMBOL"),
                    "CONSEQUENCE": get("Consequence"),
                    "IMPACT": get("IMPACT"),
                    "FEATURE": get("Feature"),
                    "HGVSC": get("HGVSc"),
                    "HGVSP": get("HGVSp"),
                    "CSQ": ",".join(map(str, csq_values)),
                }
            )
    return pd.DataFrame(rows)


def event_overview_plot(
    events: pd.DataFrame,
    breakpoints: pd.DataFrame,
    output_path: Path,
) -> None:
    points: list[dict] = []
    if not events.empty and "EVENT_TYPE" in events.columns:
        for row in events.to_dict(orient="records"):
            event_type = str(row.get("EVENT_TYPE", ""))
            if event_type == "SMALL_VARIANT":
                chromosome = safe_chromosome(row.get("CHROM"))
                position = safe_position(row.get("POS"))
                if chromosome and position is not None:
                    points.append({
                        "CHROM": chromosome,
                        "POS": position,
                        "EVENT_TYPE": event_type,
                    })
            elif event_type == "COPY_NUMBER_SEGMENT":
                chromosome = safe_chromosome(
                    row.get("CHROM", row.get("chromosome", ""))
                )
                start = safe_position(row.get("START", row.get("start")))
                end = safe_position(row.get("END", row.get("end")))
                if chromosome and start is not None and end is not None:
                    points.append({
                        "CHROM": chromosome,
                        "POS": (start + end) / 2,
                        "EVENT_TYPE": event_type,
                    })
    if not breakpoints.empty:
        for row in breakpoints.to_dict(orient="records"):
            for chrom_key, pos_key in (("CHROM1", "POS1"), ("CHROM2", "POS2")):
                chromosome = safe_chromosome(row.get(chrom_key))
                position = safe_position(row.get(pos_key))
                if chromosome and position is not None:
                    points.append({
                        "CHROM": chromosome,
                        "POS": position,
                        "EVENT_TYPE": "BREAKPOINT_SIDE",
                    })
    table = pd.DataFrame(points)
    if table.empty:
        save_placeholder_plot(
            output_path,
            "Tumor-genome event overview",
            "No integrated events were available.",
        )
        return
    chromosomes = sorted(table["CHROM"].dropna().unique())
    y_map = {chromosome: index for index, chromosome in enumerate(chromosomes)}
    markers = {
        "SMALL_VARIANT": "o",
        "COPY_NUMBER_SEGMENT": "s",
        "BREAKPOINT_SIDE": "^",
    }
    figure, axis = plt.subplots(figsize=(13, max(6, len(chromosomes) * 0.35)))
    for event_type, group in table.groupby("EVENT_TYPE"):
        axis.scatter(
            pd.to_numeric(group["POS"], errors="coerce") / 1_000_000,
            [y_map[value] for value in group["CHROM"]],
            marker=markers.get(event_type, "o"),
            label=event_type,
            alpha=0.75,
        )
    axis.set_yticks(range(len(chromosomes)))
    axis.set_yticklabels(chromosomes)
    axis.set_xlabel("Genomic position (Mb)")
    axis.set_ylabel("Chromosome")
    axis.set_title("Integrated tumor-genome events")
    axis.grid(alpha=0.2)
    axis.legend()
    figure.tight_layout()
    figure.savefig(output_path, dpi=180)
    plt.close(figure)



def table_html(path: Path, maximum_rows: int) -> str:
    table = optional_table(path)
    if table.empty:
        return "<p>No records.</p>"
    note = ""
    if len(table) > maximum_rows:
        note = f"<p>Showing {maximum_rows} of {len(table)} rows.</p>"
        table = table.head(maximum_rows)
    return note + table.to_html(index=False, escape=True, border=0)




def _selected_step10_tsv(
    value: object,
    label: str,
    expected_name: str,
    required_columns: set[str] | None = None,
) -> tuple[Path, pd.DataFrame]:
    text = str(value or "").strip()
    if not text:
        raise ValueError(
            f"{label} is required. Select it explicitly in the Step 10 GUI."
        )

    path = normalized_input_path(text)
    if path.name.lower() != expected_name.lower():
        raise ValueError(
            f"{label} must be the file named '{expected_name}'. "
            f"Selected: {path.name}"
        )
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"{label} was not found: {path}")

    try:
        table = pd.read_csv(path, sep="\t", low_memory=False)
    except pd.errors.EmptyDataError:
        # Step 09 may legitimately produce an empty table when no event of that
        # class exists. Keep the explicit file selection but represent it as empty.
        table = pd.DataFrame()

    if required_columns:
        missing = sorted(required_columns.difference(table.columns))
        if missing:
            raise ValueError(
                f"{label} is missing required column(s): {', '.join(missing)}\n"
                f"File: {path}"
            )
    return path, table


def _parse_explicit_pass_vcf_paths(value: object) -> list[Path]:
    text = str(value or "").strip()
    if not text:
        return []

    output: list[Path] = []
    for item in [piece.strip() for piece in text.split(";") if piece.strip()]:
        path = normalized_input_path(item)
        lower = path.name.lower()

        if not (
            lower.endswith(".pass.vcf.gz")
            or lower.endswith(".pass.vcf")
        ):
            raise ValueError(
                "Step 10 PASS VCF input must end with '.PASS.vcf.gz' or "
                f"'.PASS.vcf'. Selected: {path.name}"
            )
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(
                f"Selected Step 08 PASS VCF was not found: {path}"
            )
        output.append(path)

    return output


def _pass_vcf_sample_id(path: Path) -> str:
    name = path.name
    lower = name.lower()
    for suffix in (".pass.vcf.gz", ".pass.vcf"):
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def load_explicit_step10_inputs(
    settings: dict,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    Path,
    Path,
    pd.DataFrame,
    pd.DataFrame,
]:
    cfg = settings["annotation"]

    events_path, events = _selected_step10_tsv(
        cfg['integrated_events_tsv'],
        "Step 09 integrated-events table",
        "integrated_tumor_genome_events.tsv",
    )
    derivatives_path, derivatives = _selected_step10_tsv(
        cfg['derivative_chromosomes_tsv'],
        "Step 09 derivative-chromosomes table",
        "candidate_derivative_chromosomes.tsv",
    )
    nodes_path, nodes = _selected_step10_tsv(
        cfg['graph_nodes_tsv'],
        "Step 09 graph-nodes table",
        "tumor_genome_graph_nodes.tsv",
    )
    edges_path, edges = _selected_step10_tsv(
        cfg['graph_edges_tsv'],
        "Step 09 graph-edges table",
        "tumor_genome_graph_edges.tsv",
    )

    pass_vcfs = _parse_explicit_pass_vcf_paths(
        cfg['pass_vcf_files']
    )
    if bool(cfg["run_vep"]) and not pass_vcfs:
        raise ValueError(
            "Run VEP is enabled, but no Step 08 PASS VCF was selected. "
            "Select one or more *.PASS.vcf.gz files, or disable VEP."
        )

    small_vcfs = pd.DataFrame(
        [
            {
                "SAMPLE_ID": _pass_vcf_sample_id(path),
                "VCF": str(path),
            }
            for path in pass_vcfs
        ]
    )

    audit_rows = [
        {
            "ROLE": "STEP09_INTEGRATED_EVENTS",
            "FILE": str(events_path),
            "RECORDS": len(events),
            "VALIDATION": "PASS",
        },
        {
            "ROLE": "STEP09_DERIVATIVE_CHROMOSOMES",
            "FILE": str(derivatives_path),
            "RECORDS": len(derivatives),
            "VALIDATION": "PASS",
        },
        {
            "ROLE": "STEP09_GRAPH_NODES",
            "FILE": str(nodes_path),
            "RECORDS": len(nodes),
            "VALIDATION": "PASS",
        },
        {
            "ROLE": "STEP09_GRAPH_EDGES",
            "FILE": str(edges_path),
            "RECORDS": len(edges),
            "VALIDATION": "PASS",
        },
    ]

    for row in small_vcfs.to_dict(orient="records"):
        audit_rows.append(
            {
                "ROLE": "STEP08_PASS_VCF",
                "FILE": str(row["VCF"]),
                "RECORDS": "",
                "VALIDATION": "PASS",
            }
        )

    return (
        events,
        derivatives,
        nodes_path,
        edges_path,
        small_vcfs,
        pd.DataFrame(audit_rows),
    )


def annotation_parameter_rows(settings: dict) -> list[dict[str, object]]:
    cfg = settings["annotation"]
    refs = settings["references"]
    return [
        {
            "PARAMETER": "integrated_events_tsv",
            "VALUE": str(cfg['integrated_events_tsv']),
            "EXPLANATION": (
                "Explicit Step 09 integrated_tumor_genome_events.tsv combining "
                "structural variants, CNVs, and small variants."
            ),
        },
        {
            "PARAMETER": "derivative_chromosomes_tsv",
            "VALUE": str(cfg['derivative_chromosomes_tsv']),
            "EXPLANATION": (
                "Explicit Step 09 candidate_derivative_chromosomes.tsv."
            ),
        },
        {
            "PARAMETER": "graph_nodes_tsv",
            "VALUE": str(cfg['graph_nodes_tsv']),
            "EXPLANATION": (
                "Explicit Step 09 tumor_genome_graph_nodes.tsv included in the report."
            ),
        },
        {
            "PARAMETER": "graph_edges_tsv",
            "VALUE": str(cfg['graph_edges_tsv']),
            "EXPLANATION": (
                "Explicit Step 09 tumor_genome_graph_edges.tsv included in the report."
            ),
        },
        {
            "PARAMETER": "pass_vcf_files",
            "VALUE": str(cfg['pass_vcf_files']),
            "EXPLANATION": (
                "Explicit Step 08 *.PASS.vcf or *.PASS.vcf.gz file(s). "
                "Needed only for optional VEP; lightweight local GTF annotation "
                "uses the Step 08 small-variant rows already integrated by Step 09."
            ),
        },
        {
            "PARAMETER": "gene_gtf",
            "VALUE": str(refs["gene_gtf"]),
            "EXPLANATION": (
                "Gene annotation GTF used for nearest-gene assignment."
            ),
        },
        {
            "PARAMETER": "nearest_gene_maximum_distance_bp",
            "VALUE": int(cfg["nearest_gene_maximum_distance_bp"]),
            "EXPLANATION": (
                "Maximum distance for nearest-gene assignment."
            ),
        },
        {
            "PARAMETER": "run_local_gtf_variant_annotation",
            "VALUE": bool(cfg['run_local_gtf_variant_annotation']),
            "EXPLANATION": (
                "Annotate molecularly validated small variants locally from the selected GTF. "
                "No VEP cache is required. Reports gene/transcript/exon/CDS/UTR "
                "context and nearest gene, but not protein or clinical consequence."
            ),
        },
        {
            "PARAMETER": "run_vep",
            "VALUE": bool(cfg["run_vep"]),
            "EXPLANATION": "Run offline Ensembl VEP on selected Step 08 PASS VCFs.",
        },
        {
            "PARAMETER": "vep_cache",
            "VALUE": str(refs["vep_cache"]),
            "EXPLANATION": "Local offline VEP cache directory.",
        },
        {
            "PARAMETER": "vep_species",
            "VALUE": str(refs["vep_species"]),
            "EXPLANATION": "Species name passed to VEP.",
        },
        {
            "PARAMETER": "vep_assembly",
            "VALUE": str(refs["vep_assembly"]),
            "EXPLANATION": "Genome assembly passed to VEP.",
        },
        {
            "PARAMETER": "maximum_table_rows",
            "VALUE": int(cfg["maximum_table_rows"]),
            "EXPLANATION": (
                "Maximum rows rendered per table inside the HTML report."
            ),
        },
    ]




def chromosome_sort_key(chromosome: str) -> tuple[int, object, str]:
    chrom = safe_chromosome(chromosome)
    if not chrom:
        return (9, "", "")
    stripped = chrom[3:] if chrom.lower().startswith("chr") else chrom
    upper = stripped.upper()
    if upper.isdigit():
        return (0, int(upper), chrom)
    if upper == "X":
        return (1, 23, chrom)
    if upper == "Y":
        return (1, 24, chrom)
    if upper in {"M", "MT"}:
        return (1, 25, chrom)
    return (2, upper, chrom)


def pretty_context_label(value: object, width: int = 16) -> str:
    text = str(value).strip().replace("_", " ")
    text = re.sub(r"\s+", " ", text)
    wrapped = textwrap.wrap(text, width=width) or [text]
    return "\n".join(wrapped)


def _read_loose_tsv(path: Path) -> pd.DataFrame:
    if not path.exists() or not path.is_file() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, sep="\t", low_memory=False)


def infer_chromosome_lengths(
    graph_nodes_path: Path,
    events: pd.DataFrame,
    breakpoints: pd.DataFrame,
    variants: pd.DataFrame,
) -> dict[str, int]:
    lengths: dict[str, int] = defaultdict(int)

    nodes = _read_loose_tsv(graph_nodes_path)
    if not nodes.empty:
        for row in nodes.to_dict(orient="records"):
            chrom = safe_chromosome(row.get("CHROM"))
            end = safe_position(row.get("END"))
            start = safe_position(row.get("START"))
            if not chrom:
                node_id = str(row.get("NODE_ID", "")).strip()
                m = re.match(r"(.+?):(\d+)-(\d+)$", node_id)
                if m:
                    chrom = safe_chromosome(m.group(1))
                    start = safe_position(m.group(2))
                    end = safe_position(m.group(3))
            if chrom:
                for value in (start, end):
                    if value is not None and value > lengths.get(chrom, 0):
                        lengths[chrom] = int(value)

    if not events.empty:
        for row in events.to_dict(orient="records"):
            chrom = safe_chromosome(row.get("CHROM"))
            for key in ("POS", "START", "END"):
                value = safe_position(row.get(key))
                if chrom and value is not None and value > lengths.get(chrom, 0):
                    lengths[chrom] = int(value)

    if not breakpoints.empty:
        for row in breakpoints.to_dict(orient="records"):
            for chrom_key, pos_key in (("CHROM1", "POS1"), ("CHROM2", "POS2")):
                chrom = safe_chromosome(row.get(chrom_key))
                value = safe_position(row.get(pos_key))
                if chrom and value is not None and value > lengths.get(chrom, 0):
                    lengths[chrom] = int(value)

    if not variants.empty:
        for row in variants.to_dict(orient="records"):
            chrom = safe_chromosome(row.get("CHROM"))
            value = safe_position(row.get("POS"))
            if chrom and value is not None and value > lengths.get(chrom, 0):
                lengths[chrom] = int(value)

    # Safety fallback so every chromosome can be rendered.
    for chrom in list(lengths):
        lengths[chrom] = max(int(lengths[chrom]), 1)

    return dict(lengths)


def _chromosome_positions_from_breakpoints(
    breakpoints: pd.DataFrame,
    chromosome: str,
) -> list[int]:
    positions: list[int] = []
    if breakpoints.empty:
        return positions
    for row in breakpoints.to_dict(orient="records"):
        for chrom_key, pos_key in (("CHROM1", "POS1"), ("CHROM2", "POS2")):
            chrom = safe_chromosome(row.get(chrom_key))
            pos = safe_position(row.get(pos_key))
            if chrom == chromosome and pos is not None:
                positions.append(pos)
    return sorted(positions)


def _chromosome_positions_from_variants(
    variants: pd.DataFrame,
    chromosome: str,
) -> list[int]:
    positions: list[int] = []
    if variants.empty:
        return positions
    for row in variants.to_dict(orient="records"):
        chrom = safe_chromosome(row.get("CHROM"))
        pos = safe_position(row.get("POS"))
        if chrom == chromosome and pos is not None:
            positions.append(pos)
    return sorted(positions)


def _chromosome_cnv_segments(
    events: pd.DataFrame,
    chromosome: str,
) -> list[dict[str, object]]:
    segments: list[dict[str, object]] = []
    if events.empty or "EVENT_TYPE" not in events.columns:
        return segments

    for row in events.to_dict(orient="records"):
        if str(row.get("EVENT_TYPE", "")).upper() != "COPY_NUMBER_SEGMENT":
            continue
        chrom = safe_chromosome(row.get("CHROM"))
        start = safe_position(row.get("START"))
        end = safe_position(row.get("END"))
        if chrom != chromosome or start is None or end is None or end < start:
            continue

        call = str(
            row.get("CALL_BY_SIGNED_COPY_RATIO", row.get("CALL", "NEUTRAL"))
        ).strip() or "NEUTRAL"

        segments.append(
            {
                "START": start,
                "END": end,
                "CALL": call.upper(),
            }
        )

    return sorted(segments, key=lambda item: (int(item["START"]), int(item["END"])))


def draw_chromosome_circos_plot(
    chromosome: str,
    chromosome_length: int,
    breakpoint_positions: list[int],
    variant_positions: list[int],
    cnv_segments: list[dict[str, object]],
    output_path: Path,
) -> None:
    """
    Create a simple Circos-style single-chromosome plot.

    Tracks:
      - outer ring: chromosome ideogram
      - red/orange/blue inner arcs: CNV segments
      - green points: molecularly validated small variants
      - purple points: breakpoint sides
    """
    chromosome_length = max(int(chromosome_length), 1)

    def pos_to_theta(position: int) -> float:
        return 2.0 * math.pi * ((max(1, min(int(position), chromosome_length)) - 1) / chromosome_length)

    figure = plt.figure(figsize=(8.4, 8.4))
    axis = figure.add_subplot(111, projection="polar")
    axis.set_theta_offset(math.pi / 2.0)
    axis.set_theta_direction(-1)
    axis.set_ylim(0.0, 1.28)
    axis.set_axis_off()

    # Base chromosome ring.
    ring_angles = [2.0 * math.pi * (i / 720.0) for i in range(721)]
    axis.plot(ring_angles, [1.0] * len(ring_angles), color="#222222", linewidth=5.5, solid_capstyle="round")

    # Ticks every 25% of chromosome length.
    tick_fracs = [0.0, 0.25, 0.50, 0.75]
    for frac in tick_fracs:
        theta = 2.0 * math.pi * frac
        axis.plot([theta, theta], [0.97, 1.08], color="#666666", linewidth=1.0)
        label_pos = int(round(frac * chromosome_length))
        label_text = "0 Mb" if frac == 0.0 else f"{label_pos / 1_000_000:.1f} Mb"
        axis.text(theta, 1.16, label_text, fontsize=8, ha="center", va="center")

    # CNV track.
    cnv_color_map = {
        "GAIN": "#d62728",
        "AMPLIFICATION": "#b2182b",
        "LOSS": "#1f77b4",
        "DELETION": "#2166ac",
        "NEUTRAL": "#9e9e9e",
    }
    for segment in cnv_segments:
        start = int(segment["START"])
        end = int(segment["END"])
        call = str(segment.get("CALL", "NEUTRAL")).upper()
        color = cnv_color_map.get(call, "#ff7f0e")
        if end <= start:
            end = start + 1
        n = max(8, min(220, int((end - start) / max(1, chromosome_length) * 720)))
        segment_angles = [
            pos_to_theta(start + (end - start) * (i / max(1, n - 1)))
            for i in range(n)
        ]
        axis.plot(
            segment_angles,
            [0.84] * len(segment_angles),
            color=color,
            linewidth=8.0,
            solid_capstyle="butt",
            alpha=0.95,
        )

    # Variant track.
    if variant_positions:
        variant_angles = [pos_to_theta(pos) for pos in variant_positions]
        axis.scatter(
            variant_angles,
            [0.66] * len(variant_angles),
            s=11,
            color="#2ca02c",
            alpha=0.50,
            linewidths=0,
            zorder=3,
        )

    # Breakpoint track.
    if breakpoint_positions:
        breakpoint_angles = [pos_to_theta(pos) for pos in breakpoint_positions]
        axis.scatter(
            breakpoint_angles,
            [1.11] * len(breakpoint_angles),
            s=18,
            color="#9467bd",
            alpha=0.75,
            linewidths=0,
            zorder=4,
        )

    # Center text + simple legend.
    axis.text(
        0.0,
        0.0,
        f"{chromosome}\n{chromosome_length / 1_000_000:.1f} Mb",
        ha="center",
        va="center",
        fontsize=14,
        fontweight="bold",
    )
    axis.text(
        math.pi,
        0.28,
        (
            f"CNV segments: {len(cnv_segments)}\n"
            f"Small variants: {len(variant_positions)}\n"
            f"Breakpoint sides: {len(breakpoint_positions)}"
        ),
        ha="center",
        va="center",
        fontsize=9,
    )

    legend_handles = [
        plt.Line2D([0], [0], color="#222222", linewidth=5.5, label="Chromosome ring"),
        plt.Line2D([0], [0], color="#d62728", linewidth=8, label="CNV gain"),
        plt.Line2D([0], [0], color="#1f77b4", linewidth=8, label="CNV loss"),
        plt.Line2D([0], [0], color="#9e9e9e", linewidth=8, label="CNV neutral"),
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor="#2ca02c", markersize=7, label="Small variants"),
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor="#9467bd", markersize=7, label="Breakpoint sides"),
    ]
    axis.legend(
        handles=legend_handles,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.10),
        ncol=2,
        frameon=False,
        fontsize=8,
    )

    figure.tight_layout()
    figure.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def generate_chromosome_circos_plots(
    graph_nodes_path: Path,
    annotated_events: pd.DataFrame,
    annotated_breakpoints: pd.DataFrame,
    variants_for_plotting: pd.DataFrame,
    output_dir: Path,
) -> list[Path]:
    circos_dir = output_dir / "chromosome_circos"
    if circos_dir.exists():
        shutil.rmtree(circos_dir)
    circos_dir.mkdir(parents=True, exist_ok=True)

    lengths = infer_chromosome_lengths(
        graph_nodes_path,
        annotated_events,
        annotated_breakpoints,
        variants_for_plotting,
    )

    chromosomes = sorted(lengths.keys(), key=chromosome_sort_key)
    outputs: list[Path] = []
    for chromosome in chromosomes:
        length = max(int(lengths.get(chromosome, 0)), 1)
        breakpoint_positions = _chromosome_positions_from_breakpoints(
            annotated_breakpoints, chromosome
        )
        variant_positions = _chromosome_positions_from_variants(
            variants_for_plotting, chromosome
        )
        cnv_segments = _chromosome_cnv_segments(annotated_events, chromosome)

        # Skip completely empty chromosomes.
        if not breakpoint_positions and not variant_positions and not cnv_segments:
            continue

        output_path = circos_dir / f"circos_{chromosome}.png"
        draw_chromosome_circos_plot(
            chromosome,
            length,
            breakpoint_positions,
            variant_positions,
            cnv_segments,
            output_path,
        )
        outputs.append(output_path)

    return outputs


def validate_annotation_settings(settings: dict, dry_run: bool) -> None:
    cfg = settings["annotation"]
    refs = settings["references"]

    if int(cfg["nearest_gene_maximum_distance_bp"]) < 0:
        raise ValueError("Maximum nearest-gene distance cannot be negative.")
    if int(cfg["maximum_table_rows"]) < 1:
        raise ValueError("Maximum HTML table rows must be at least 1.")

    gtf_text = str(refs['gene_gtf'] or "").strip()
    if not gtf_text:
        raise ValueError(
            "Select the gene annotation GTF explicitly in Step 16."
        )

    if not dry_run:
        gtf = normalized_input_path(gtf_text)
        if not gtf.exists() or not gtf.is_file():
            raise FileNotFoundError(f"Gene GTF was not found: {gtf}")

    if bool(cfg["run_vep"]):
        cache_text = str(refs['vep_cache'] or "").strip()
        if not cache_text:
            raise ValueError(
                "VEP is enabled. Select the VEP cache folder explicitly."
            )
        if not dry_run:
            cache = normalized_input_path(cache_text)
            if not cache.exists() or not cache.is_dir():
                raise FileNotFoundError(
                    f"VEP cache directory was not found: {cache}"
                )

        if not str(refs["vep_species"]).strip():
            raise ValueError("VEP species cannot be empty when VEP is enabled.")
        if not str(refs["vep_assembly"]).strip():
            raise ValueError("VEP assembly cannot be empty when VEP is enabled.")



def _gene_intervals_from_gtf(gtf_path: Path) -> dict[str,list[tuple[int,int,str,str]]]:
    result=defaultdict(list)
    opener=gzip.open if str(gtf_path).lower().endswith(".gz") else open
    with opener(gtf_path,"rt",encoding="utf-8",errors="replace") as h:
        for line in h:
            if not line or line.startswith("#"): continue
            f=line.rstrip("\n").split("\t")
            if len(f)<9 or f[2]!="gene": continue
            attrs={}
            for item in f[8].split(";"):
                item=item.strip()
                if " " in item:
                    k,v=item.split(" ",1); attrs[k]=v.strip().strip('"')
            result[f[0]].append((int(f[3]),int(f[4]),attrs.get("gene_name",attrs.get("gene_id","")),f[6]))
    return result

def _genes_at(intervals,chrom,pos):
    return [{"GENE":g,"STRAND":s} for st,en,g,s in intervals.get(chrom,[]) if st<=pos<=en]

def candidate_gene_fusions(derivatives: pd.DataFrame, gtf_path: Path) -> pd.DataFrame:
    intervals=_gene_intervals_from_gtf(gtf_path); rows=[]
    for r in derivatives.to_dict(orient="records"):
        try: c1=str(r.get("CHROM1","")); p1=int(float(r.get("POS1",0))); c2=str(r.get("CHROM2","")); p2=int(float(r.get("POS2",0)))
        except Exception: continue
        g1=_genes_at(intervals,c1,p1); g2=_genes_at(intervals,c2,p2)
        if not g1 or not g2: continue
        for a in g1:
            for b in g2:
                if a["GENE"]==b["GENE"] and c1==c2: event="INTRAGENIC_REARRANGEMENT_CANDIDATE"
                else: event="CANDIDATE_GENOMIC_GENE_FUSION"
                rows.append({"SAMPLE_ID":r.get("SAMPLE_ID",""),"GENE1":a["GENE"],"GENE1_STRAND":a["STRAND"],"CHROM1":c1,"POS1":p1,"GENE2":b["GENE"],"GENE2_STRAND":b["STRAND"],"CHROM2":c2,"POS2":p2,"SVTYPE":r.get("SVTYPE",""),"FUSION_INTERPRETATION":event,"IMPORTANT_LIMITATION":"DNA breakpoint compatibility does not prove an expressed or in-frame fusion transcript."})
    return pd.DataFrame(rows)


def backend(settings_path: Path, input_dir: Path, output_dir: Path, dry_run: bool) -> None:
    settings, project_root = load_config(settings_path)

    # Standalone GUI inputs live in annotation_full; alias them into the inherited annotation engine.
    annotation_full = settings['annotation_full']
    annotation_cfg = settings["annotation"]
    references_cfg = settings["references"]
    for key in ("integrated_events_tsv", "derivative_chromosomes_tsv", "graph_nodes_tsv", "graph_edges_tsv"):
        annotation_cfg[key] = str(annotation_full.get(key, "") or "")
    references_cfg["gene_gtf"] = str(annotation_full['gene_gtf'] or "")
    pass_vcf_folder_text = str(annotation_full['pass_vcf_folder'] or "").strip()
    if pass_vcf_folder_text:
        pass_vcf_folder = normalized_input_path(pass_vcf_folder_text)
        pass_files = []
        if pass_vcf_folder.exists() and pass_vcf_folder.is_dir():
            for pattern in ("*.PASS.vcf.gz", "*.PASS.vcf", "*.pass.vcf.gz", "*.pass.vcf"):
                pass_files.extend(sorted(pass_vcf_folder.rglob(pattern)))
        annotation_cfg["pass_vcf_files"] = ";".join(str(path) for path in dict.fromkeys(pass_files))
    else:
        annotation_cfg["pass_vcf_files"] = ""

    output_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(output_dir / "16_ANNOTATE_FUSIONS_AND_VISUALIZE_RESULTS.log")

    validate_annotation_settings(settings, dry_run)
    write_tsv(
        pd.DataFrame(annotation_parameter_rows(settings)),
        output_dir / "annotation_parameters_used.tsv",
    )

    (
        events,
        derivatives,
        graph_nodes_path,
        graph_edges_path,
        small_vcfs,
        input_audit,
    ) = load_explicit_step10_inputs(settings)
    write_tsv(input_audit, output_dir / "step16_input_files_used.tsv")
    cfg = settings["annotation"]

    maximum_gene_distance = int(cfg["nearest_gene_maximum_distance_bp"])
    run_local_gtf = bool(cfg['run_local_gtf_variant_annotation'])
    small_variant_events = extract_small_variant_events(events)
    local_variant_positions = (
        variant_positions_by_chromosome(small_variant_events)
        if run_local_gtf else {}
    )

    chromosomes: set[str] = set()
    if not derivatives.empty:
        for column in ("CHROM1", "CHROM2"):
            if column in derivatives.columns:
                chromosomes.update(
                    chromosome
                    for chromosome in derivatives[column].map(safe_chromosome)
                    if chromosome
                )
    if not events.empty and "CHROM" in events.columns:
        chromosomes.update(
            chromosome
            for chromosome in events["CHROM"].map(safe_chromosome)
            if chromosome
        )
    chromosomes.update(local_variant_positions.keys())

    gtf_path = normalized_input_path(settings["references"]["gene_gtf"])
    genes, local_feature_overlaps = load_gtf_resources(
        gtf_path,
        chromosomes,
        local_variant_positions if run_local_gtf else None,
    )

    annotated_breakpoints = annotate_breakpoints(
        derivatives, genes, maximum_gene_distance
    )
    write_tsv(annotated_breakpoints, output_dir / "annotated_breakpoints.tsv")

    candidate_fusions = candidate_gene_fusions(derivatives, gtf_path)
    write_tsv(
        candidate_fusions,
        output_dir / "candidate_genomic_gene_fusions.tsv",
    )

    annotated_events = annotate_integrated_events_nearest_gene(
        events, genes, maximum_gene_distance
    )
    write_tsv(
        annotated_events,
        output_dir / "annotated_integrated_tumor_genome_events.tsv",
    )

    local_gtf_variants = pd.DataFrame()
    if run_local_gtf and not small_variant_events.empty:
        local_gtf_variants = annotate_small_variants_from_gtf(
            small_variant_events,
            genes,
            local_feature_overlaps,
            maximum_gene_distance,
        )
    write_tsv(
        local_gtf_variants,
        output_dir / "local_gtf_annotated_small_variants.tsv",
    )

    vep_tables: list[pd.DataFrame] = []
    vep_result_rows: list[dict] = []
    if bool(cfg["run_vep"]) and not small_vcfs.empty:
        require_tools(settings, ["vep", "multiqc"], dry_run)
        for row in small_vcfs.to_dict(orient="records"):
            pass_vcf = str(row.get("VCF", "")).strip()
            if not is_nonempty(pass_vcf):
                continue
            sample_id = str(row["SAMPLE_ID"])
            annotated_vcf = output_dir / "vep" / sample_id / f"{sample_id}.vep.vcf.gz"
            annotated_vcf.parent.mkdir(parents=True, exist_ok=True)
            command = (
                f"{quote(settings['tools']['vep'])} --offline --cache "
                f"--dir_cache {quote(normalized_input_path(settings['references']['vep_cache']))} "
                f"--species {quote(settings['references']['vep_species'])} "
                f"--assembly {quote(settings['references']['vep_assembly'])} "
                f"--format vcf --vcf --everything --pick --force_overwrite "
                f"--compress_output bgzip "
                f"--input_file {quote(pass_vcf)} --output_file {quote(annotated_vcf)}"
            )
            run_command(
                command,
                output_dir / "logs" / f"{sample_id}.vep.log",
                dry_run=dry_run,
                shell=True,
            )
            if not dry_run:
                table = parse_vep_vcf(annotated_vcf, sample_id)
                if not table.empty:
                    vep_tables.append(table)
            vep_result_rows.append(
                {"SAMPLE_ID": sample_id, "VEP_ANNOTATED_VCF": str(annotated_vcf)}
            )
    else:
        require_tools(settings, ["multiqc"], dry_run)

    vep_table = (
        pd.concat(vep_tables, ignore_index=True)
        if vep_tables else pd.DataFrame()
    )
    write_tsv(vep_table, output_dir / "vep_annotated_small_variants.tsv")
    write_tsv(pd.DataFrame(vep_result_rows), output_dir / "vep_results.tsv")

    local_context_plot = output_dir / "local_gtf_variant_context_counts.png"
    if run_local_gtf and not local_gtf_variants.empty and "LOCAL_GTF_CONTEXT" in local_gtf_variants.columns:
        counts = local_gtf_variants["LOCAL_GTF_CONTEXT"].value_counts()
        formatted_labels = [pretty_context_label(value) for value in counts.index.astype(str)]
        positions = list(range(len(counts)))
        figure, axis = plt.subplots(figsize=(11, 6.5))
        axis.bar(positions, counts.astype(int))
        axis.set_xticks(positions)
        axis.set_xticklabels(formatted_labels, rotation=28, ha="right")
        axis.set_ylabel("Variant count")
        axis.set_title("molecularly validated small variants — local GTF genomic context")
        axis.grid(axis="y", alpha=0.25)
        figure.subplots_adjust(bottom=0.28)
        figure.tight_layout()
        figure.savefig(local_context_plot, dpi=180)
        plt.close(figure)
    else:
        save_placeholder_plot(
            local_context_plot,
            "Local GTF small-variant annotation",
            (
                "Local GTF annotation was disabled or no molecularly validated small variants "
                "were available."
            ),
        )

    overview_plot = output_dir / "tumor_genome_event_overview.png"
    event_overview_plot(annotated_events, annotated_breakpoints, overview_plot)

    variants_for_circos = (
        local_gtf_variants
        if run_local_gtf and not local_gtf_variants.empty
        else small_variant_events
    )
    circos_plots = generate_chromosome_circos_plots(
        graph_nodes_path,
        annotated_events,
        annotated_breakpoints,
        variants_for_circos,
        output_dir,
    )

    multiqc_dir = output_dir / "multiqc"
    multiqc_dir.mkdir(parents=True, exist_ok=True)
    multiqc_report = multiqc_dir / "multiqc_report.html"
    command = (
        f"{quote(settings['tools']['multiqc'])} --force "
        f"--outdir {quote(multiqc_dir)} "
        f"--filename {quote(multiqc_report.name)} {quote(project_root)}"
    )
    run_command(
        command,
        output_dir / "multiqc.log",
        dry_run=dry_run,
        shell=True,
    )

    assets = output_dir / "assets"
    if assets.exists():
        shutil.rmtree(assets)
    assets.mkdir(parents=True)
    plot_items: list[tuple[str, Path]] = []
    for step_folder in sorted(project_root.glob("[0-9][0-9]_*")):
        step_output = step_folder / "output"
        if not step_output.exists() or step_output.resolve() == output_dir.resolve():
            continue
        for plot in find_plot_files(step_output):
            destination = assets / f"{step_folder.name}__{'__'.join(plot.relative_to(step_output).parts)}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(plot, destination)
            plot_items.append((step_folder.name, destination))
    shutil.copy2(overview_plot, assets / overview_plot.name)
    plot_items.append((SPEC.title, assets / overview_plot.name))
    shutil.copy2(local_context_plot, assets / local_context_plot.name)
    plot_items.append((SPEC.title, assets / local_context_plot.name))
    for circos_plot in circos_plots:
        destination = assets / f"{SPEC.title}__chromosome_circos__{circos_plot.name}"
        shutil.copy2(circos_plot, destination)
        plot_items.append((SPEC.title, destination))

    maximum_rows = int(cfg["maximum_table_rows"])
    table_paths = [
        output_dir / "annotated_breakpoints.tsv",
        output_dir / "annotated_integrated_tumor_genome_events.tsv",
        output_dir / "local_gtf_annotated_small_variants.tsv",
        output_dir / "vep_annotated_small_variants.tsv",
        graph_nodes_path,
        graph_edges_path,
    ]
    table_sections = "\n".join(
        f"<section><h2>{html.escape(path.name)}</h2>{table_html(path, maximum_rows)}</section>"
        for path in table_paths
    )
    plot_sections = "\n".join(
        (
            "<section class='plot-card'>"
            f"<h3>{html.escape(step)} — {html.escape(path.stem)}</h3>"
            f"<img src='{html.escape(str(path.relative_to(output_dir)).replace(chr(92), '/'))}'>"
            "</section>"
        )
        for step, path in plot_items
    )

    report = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>ctDNA tumor-genome reconstruction report</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 28px; line-height: 1.4; }}
.warning {{ background:#fff3cd; border:1px solid #d5a400; padding:12px; }}
table {{ border-collapse:collapse; width:100%; font-size:12px; margin-bottom:24px; }}
th,td {{ border:1px solid #ddd; padding:5px; text-align:left; }}
th {{ background:#f2f2f2; position:sticky; top:0; }}
.plot-card {{ border:1px solid #ddd; padding:12px; margin:14px 0; }}
.plot-card img {{ max-width:1250px; width:100%; height:auto; }}
</style>
</head>
<body>
<h1>ctDNA tumor-genome reconstruction report</h1>
<div class="warning">
<strong>Research use only.</strong> The graph and derivative-chromosome models
are hypotheses supported by short-read ctDNA evidence. They do not constitute
a complete de novo tumor chromosome assembly or a clinically validated result.
</div>
<h2>MultiQC</h2>
<p><a href="multiqc/multiqc_report.html">Open MultiQC report</a></p>
<h1>Annotated tables</h1>
{tables}
<h1>Quality-control and result plots</h1>
{plots}
</body>
</html>
""".format(tables=table_sections, plots=plot_sections)
    report_path = output_dir / "ctDNA_tumor_genome_report.html"
    report_path.write_text(report, encoding="utf-8")

    write_step_status(
        output_dir,
        SPEC.title,
        "PASS",
        f"Created the final annotated report with {len(annotated_events)} "
        f"integrated event record(s), {len(local_gtf_variants)} locally GTF-annotated "
        f"small variant(s), {len(circos_plots)} chromosome circos plot(s), "
        f"and {len(plot_items)} plot(s).",
        0,
        [overview_plot],
    )
    print(report_path)



STEP_GUI = {'environment': 'ctdna_core',
 'fields': [{'setting': 'annotation_full.integrated_events_tsv',
             'label': 'Step 15 integrated_tumor_genome_events.tsv',
             'type': 'file',
             'required': True,
             'expected_name': 'integrated_tumor_genome_events.tsv',
             'filetypes': [('Required Step 15 TSV', 'integrated_tumor_genome_events.tsv'),
                           ('TSV', '*.tsv'),
                           ('All', '*.*')],
             'button_text': 'Browse integrated_tumor_genome_events.tsv',
             'section': 'ANNOTATION INPUTS AND RESOURCES'},
            {'setting': 'annotation_full.derivative_chromosomes_tsv',
             'label': 'Step 15 candidate_derivative_chromosomes.tsv',
             'type': 'file',
             'required': True,
             'expected_name': 'candidate_derivative_chromosomes.tsv',
             'filetypes': [('Required Step 15 TSV', 'candidate_derivative_chromosomes.tsv'),
                           ('TSV', '*.tsv'),
                           ('All', '*.*')],
             'button_text': 'Browse candidate_derivative_chromosomes.tsv',
             'section': 'ANNOTATION INPUTS AND RESOURCES'},
            {'setting': 'annotation_full.graph_nodes_tsv',
             'label': 'Step 15 tumor_genome_graph_nodes.tsv',
             'type': 'file',
             'required': True,
             'expected_name': 'tumor_genome_graph_nodes.tsv',
             'filetypes': [('Required Step 15 TSV', 'tumor_genome_graph_nodes.tsv'),
                           ('TSV', '*.tsv'),
                           ('All', '*.*')],
             'button_text': 'Browse tumor_genome_graph_nodes.tsv',
             'section': 'ANNOTATION INPUTS AND RESOURCES'},
            {'setting': 'annotation_full.graph_edges_tsv',
             'label': 'Step 15 tumor_genome_graph_edges.tsv',
             'type': 'file',
             'required': True,
             'expected_name': 'tumor_genome_graph_edges.tsv',
             'filetypes': [('Required Step 15 TSV', 'tumor_genome_graph_edges.tsv'),
                           ('TSV', '*.tsv'),
                           ('All', '*.*')],
             'button_text': 'Browse tumor_genome_graph_edges.tsv',
             'section': 'ANNOTATION INPUTS AND RESOURCES'},
            {'setting': 'annotation_full.gene_gtf',
             'label': 'Gene annotation GTF',
             'type': 'file',
             'required': True,
             'allowed_suffixes': ['.gtf', '.gtf.gz'],
             'filetypes': [('GTF', '*.gtf *.gtf.gz'), ('All', '*.*')],
             'button_text': 'Browse gene annotation GTF',
             'section': 'ANNOTATION INPUTS AND RESOURCES'},
            {'setting': 'annotation.run_local_gtf_variant_annotation',
             'label': 'Run lightweight local GTF annotation',
             'type': 'bool',
             'help': 'Recommended. Does not require the large VEP cache.',
             'section': 'ANNOTATION / REPORT OPTIONS'},
            {'setting': 'annotation.nearest_gene_maximum_distance_bp',
             'label': 'Nearest-gene maximum distance (bp)',
             'type': 'int',
             'required': True,
             'section': 'ANNOTATION / REPORT OPTIONS'},
            {'setting': 'annotation.maximum_table_rows',
             'label': 'Maximum rows per table in HTML report',
             'type': 'int',
             'required': True,
             'section': 'ANNOTATION / REPORT OPTIONS'},
            {'setting': 'annotation.run_vep',
             'label': 'Optional: run offline VEP annotation',
             'type': 'bool',
             'help': 'Requires PASS VCF group plus a matching local VEP cache. Leave off for lightweight GTF-only '
                     'annotation.',
             'section': 'ANNOTATION / REPORT OPTIONS'},
            {'setting': 'annotation_full.pass_vcf_folder',
             'label': 'Optional Step 11 PASS VCF folder for VEP (group)',
             'type': 'folder',
             'required': False,
             'scan_globs': ['*.PASS.vcf', '*.PASS.vcf.gz'],
             'help': 'A folder is used because there may be multiple per-sample PASS VCF files.',
             'section': 'ANNOTATION INPUTS AND RESOURCES'},
            {'setting': 'references.vep_cache',
             'label': 'Optional VEP cache folder',
             'type': 'folder',
             'required': False,
             'help': 'Required only when VEP is enabled.',
             'section': 'ANNOTATION INPUTS AND RESOURCES'},
            {'setting': 'references.vep_species',
             'label': 'VEP species',
             'type': 'text',
             'required': True,
             'section': 'VEP OPTIONS',
             'help': 'Normally homo_sapiens for this human ctDNA pipeline.'},
            {'setting': 'references.vep_assembly',
             'label': 'VEP assembly',
             'type': 'choice',
             'required': True,
             'section': 'VEP OPTIONS',
             'choices': ['GRCh38', 'GRCh37'],
             'choice_values': {'GRCh38': 'GRCh38', 'GRCh37': 'GRCh37'},
             'help': 'Must match the reference FASTA used for alignment.'}],
 'explanation': 'Annotates integrated events and candidate fusions, adds local GTF context, optionally runs '
                'offline VEP, creates plots/tables and builds the final report. The GTF/VEP resources must use '
                'the same genome assembly as the alignment reference.'}

if __name__ == "__main__":
    launch_step(SPEC, backend)
