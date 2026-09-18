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
    parser.add_argument('--small-variants-matched-normal-bam', dest='__cfg__small_variants__matched_normal_bam', type=str, default='', help='Override small_variants.matched_normal_bam for this execution.')
    parser.add_argument('--small-variants-matched-normal-sample-name', dest='__cfg__small_variants__matched_normal_sample_name', type=str, default='', help='Override small_variants.matched_normal_sample_name for this execution.')
    parser.add_argument('--references-germline-resource-vcf', dest='__cfg__references__germline_resource_vcf', type=str, default='', help='Override references.germline_resource_vcf for this execution.')
    parser.add_argument('--references-panel-of-normals-vcf', dest='__cfg__references__panel_of_normals_vcf', type=str, default='', help='Override references.panel_of_normals_vcf for this execution.')
    parser.add_argument('--small-variants-initial-tumor-lod', dest='__cfg__small_variants__initial_tumor_lod', type=float, default=1.0, help='Override small_variants.initial_tumor_lod for this execution.')
    parser.add_argument('--small-variants-minimum-base-quality-score', dest='__cfg__small_variants__minimum_base_quality_score', type=int, default=10, help='Override small_variants.minimum_base_quality_score for this execution.')
    parser.add_argument('--small-variants-maximum-reads-per-alignment-start', dest='__cfg__small_variants__maximum_reads_per_alignment_start', type=int, default=0, help='Override small_variants.maximum_reads_per_alignment_start for this execution.')
    parser.add_argument('--small-variants-native-pair-hmm-threads', dest='__cfg__small_variants__native_pair_hmm_threads', type=int, default=0, help='Native PairHMM threads per Mutect2 job; 0 = allocate automatically from project.threads.')
    parser.add_argument('--small-variants-parallel-samples', dest='__cfg__small_variants__parallel_samples', type=int, default=0, help='Number of tumor BAMs to process simultaneously; 0 = allocate automatically from project.threads.')
    return parser



DEFAULT_SETTINGS = {'project': {'name': 'ctDNA_Tumor_Genome_GUI_Pipeline', 'temporary_directory': 'work/tmp'},
 'execution': {'wsl_distribution': '',
               'micromamba_environment': 'ctdna_core',
               'python_executable_in_wsl': 'python3',
               'micromamba_executable': '',
               'micromamba_root_prefix': ''},
 'references': {'targets_bed': '',
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
 'small_variants': {'enabled': True, 'maximum_population_allele_frequency': 0.01},
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


def _analyze_target_bed(path: Path) -> dict[str, object]:
    """Validate and summarize a BED file without changing its biological intervals."""
    result: dict[str, object] = {
        "path": str(path),
        "valid_intervals": 0,
        "invalid_lines": 0,
        "raw_total_bp": 0,
        "merged_intervals": 0,
        "merged_total_bp": 0,
        "chromosomes": 0,
    }
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Target BED not found: {path}")

    by_chrom: dict[str, list[tuple[int, int]]] = defaultdict(list)
    opener = gzip.open if path.name.lower().endswith('.gz') else open
    with opener(path, 'rt', encoding='utf-8', errors='replace') as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or stripped.startswith('track ') or stripped.startswith('browser '):
                continue
            fields = stripped.split('\t')
            if len(fields) < 3:
                fields = stripped.split()
            if len(fields) < 3:
                result['invalid_lines'] = int(result['invalid_lines']) + 1
                continue
            chrom = fields[0].strip()
            try:
                start = int(fields[1])
                end = int(fields[2])
            except ValueError:
                result['invalid_lines'] = int(result['invalid_lines']) + 1
                continue
            if not chrom or start < 0 or end <= start:
                result['invalid_lines'] = int(result['invalid_lines']) + 1
                continue
            by_chrom[chrom].append((start, end))
            result['valid_intervals'] = int(result['valid_intervals']) + 1
            result['raw_total_bp'] = int(result['raw_total_bp']) + (end - start)

    merged_count = 0
    merged_bp = 0
    for chrom, intervals in by_chrom.items():
        intervals.sort()
        if not intervals:
            continue
        cur_start, cur_end = intervals[0]
        for start, end in intervals[1:]:
            if start <= cur_end:  # merge only overlapping/abutting intervals; exact union is preserved
                cur_end = max(cur_end, end)
            else:
                merged_count += 1
                merged_bp += cur_end - cur_start
                cur_start, cur_end = start, end
        merged_count += 1
        merged_bp += cur_end - cur_start

    result['merged_intervals'] = merged_count
    result['merged_total_bp'] = merged_bp
    result['chromosomes'] = len(by_chrom)
    return result


def _format_bp(value: int) -> str:
    value = int(value)
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.3f} Gb"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.3f} Mb"
    if value >= 1_000:
        return f"{value / 1_000:.1f} kb"
    return f"{value} bp"

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
            ('Threads / total CPU cores','project.threads'),
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

        tk.Label(
            out_card,
            text=("Threads / total CPU cores is the ONLY thread control in this GUI. "
                  "Step 10 automatically divides this CPU budget between simultaneous tumor samples "
                  "and Mutect2 PairHMM workers."),
            bg="white", fg="#64748B", font=("Segoe UI",8),
            wraplength=980, justify="left", anchor="w",
        ).pack(fill="x",pady=(5,0))

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
            buttons, text="Backup settings (.json)", command=self._backup_settings_clicked,
        )
        self.backup_settings_button.pack(side="left",padx=4)

        self.restore_settings_button=ttk.Button(
            buttons, text="Restore settings (.json)", command=self._restore_settings_clicked,
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

                if typ in {'file','folder'}:
                    ttk.Button(
                        row,
                        text=field.get('button_text','Browse'),
                        command=lambda f=field,v=var:self._browse(f,v),
                    ).pack(side="left",padx=3)

                    if key=='references.targets_bed':
                        ttk.Button(
                            row, text="Verify BED / -L", command=lambda:self._verify_target_bed(True),
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

        if key=='references.targets_bed':
            if not hasattr(self,'bed_status_text'):
                self.bed_status_text=self.tk.StringVar(value='BED restriction: not checked yet.')
            tk.Label(
                parent, textvariable=self.bed_status_text, bg='white', fg='#0F766E',
                font=('Segoe UI',8,'bold'), wraplength=980, justify='left', anchor='w',
            ).pack(fill='x',padx=(34,0),pady=(0,4))
            self.root.after(100, lambda:self._verify_target_bed(False))


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
        if selected:
            var.set(selected)
            if field.get('setting')=='references.targets_bed':
                self._verify_target_bed(False)

    def _verify_target_bed(self,show_dialog=False):
        try:
            var=self.vars.get('references.targets_bed')
            value=str(var.get()).strip() if var is not None else ''
            if not value:
                message='BED restriction INACTIVE — Mutect2 will not receive -L and can traverse the full reference.'
                if hasattr(self,'bed_status_text'): self.bed_status_text.set(message)
                if show_dialog: self.messagebox.showwarning('Target BED',message)
                return None
            info=_analyze_target_bed(Path(value))
            if int(info['valid_intervals']) < 1:
                raise ValueError('The selected BED contains no valid genomic intervals.')
            wsl_path=_windows_to_wsl(value)
            message=(
                f"BED restriction ACTIVE — {int(info['valid_intervals']):,} valid intervals; "
                f"exact covered union {_format_bp(int(info['merged_total_bp']))}; "
                f"Mutect2 will receive: -L {wsl_path}"
            )
            if int(info['invalid_lines']) > 0:
                message += f" | WARNING: {int(info['invalid_lines'])} malformed lines ignored by the GUI check."
            if hasattr(self,'bed_status_text'): self.bed_status_text.set(message)
            if show_dialog:
                self.messagebox.showinfo(
                    'Target BED / Mutect2 -L verification',
                    message + '\n\nThe exact command is also written to output/logs/<sample>.log.',
                )
            return info
        except Exception as exc:
            message=f'BED verification FAILED — {exc}'
            if hasattr(self,'bed_status_text'): self.bed_status_text.set(message)
            if show_dialog: self.messagebox.showerror('Target BED verification',str(exc))
            return None

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

        # The GUI exposes a single CPU control: project.threads. PairHMM workers
        # are always allocated automatically from that total budget.
        _setting_set(settings,'small_variants.native_pair_hmm_threads',0)
        settings['_gui_state']={'input_dir':str(input_dir),'output_dir':str(output_dir)}

        return settings,input_dir,output_dir

    def _settings_from_gui_without_path_validation(self):
        settings=copy.deepcopy(self.settings)
        for field in self.gui_spec.get('fields',[]):
            key=field['setting']
            if key=='__input_dir__':
                continue
            typ=field.get('type','text')
            raw=self.vars[key].get()
            if typ=='bool': value=bool(raw)
            elif typ=='int': value=int(str(raw).strip())
            elif typ=='float': value=float(str(raw).strip())
            elif typ=='choice':
                display=str(raw).strip(); value=field.get('choice_values',{}).get(display,display)
            else: value=str(raw).strip()
            _setting_set(settings,key,value)
        _setting_set(settings,'project.threads',int(self.vars['project.threads'].get()))
        _setting_set(settings,'small_variants.native_pair_hmm_threads',0)
        for key in ['execution.wsl_distribution','execution.micromamba_environment','execution.micromamba_executable','execution.micromamba_root_prefix','execution.python_executable_in_wsl']:
            _setting_set(settings,key,self.vars[key].get().strip())
        settings['_gui_state']={
            'input_dir':str(self.vars.get('__input_dir__').get()).strip() if self.vars.get('__input_dir__') is not None else '',
            'output_dir':str(self.vars.get('__output_dir__').get()).strip() if self.vars.get('__output_dir__') is not None else '',
        }
        return settings

    def _automatic_settings_backup(self):
        if not self.settings_path.exists() or not self.settings_path.is_file():
            return None
        backup_dir=self.step_dir/'settings_backups'
        backup_dir.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup_path=backup_dir/f'step_user_settings_{stamp}.json'
        shutil.copy2(self.settings_path,backup_path)
        return backup_path

    def _write_primary_settings(self,settings,make_backup=True):
        backup_path=self._automatic_settings_backup() if make_backup else None
        self.settings_path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.settings_path.with_name(self.settings_path.name+'.tmp')
        with temporary.open('w',encoding='utf-8') as h:
            json.dump(settings,h,indent=2,ensure_ascii=False); h.write('\n')
        os.replace(temporary,self.settings_path)
        return backup_path

    def _save(self):
        settings,input_dir,output_dir=self._collect()
        settings['_gui_state']={'input_dir':str(input_dir),'output_dir':str(output_dir)}
        output_dir.mkdir(parents=True,exist_ok=True)
        backup_path=self._write_primary_settings(settings,make_backup=True)
        self.settings=settings
        self._verify_target_bed(False)
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
        try:
            settings=self._settings_from_gui_without_path_validation()
            stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
            selected=self.filedialog.asksaveasfilename(
                initialdir=self.step_dir,
                initialfile=f'step10_settings_backup_{stamp}.json',
                title='Backup Step 10 settings JSON',
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
                json.dump(settings,h,indent=2,ensure_ascii=False); h.write('\n')
            os.replace(temporary,backup_path)
            self.status.set(f"Settings backup created: {backup_path}")
            self.messagebox.showinfo('Settings backup',f"Backup created successfully:\n\n{backup_path}")
        except Exception as exc:
            self.messagebox.showerror('Settings backup error',str(exc))

    def _restore_settings_clicked(self):
        try:
            selected=self.filedialog.askopenfilename(
                initialdir=self.step_dir,
                title='Restore Step 10 settings JSON',
                filetypes=[('JSON settings','*.json'),('All files','*.*')],
            )
            if not selected:
                return
            restore_path=Path(selected)
            with restore_path.open('r',encoding='utf-8') as h:
                loaded=json.load(h)
            if not isinstance(loaded,dict):
                raise ValueError('The selected JSON does not contain a settings object.')
            restored=_deep_merge(DEFAULT_SETTINGS,loaded)
            # Global Threads is authoritative; old PairHMM GUI values are ignored.
            restored.setdefault('small_variants',{})['native_pair_hmm_threads']=0
            self.settings=restored
            gui_state=restored.get('_gui_state',{}) if isinstance(restored,dict) else {}

            for field in self.gui_spec.get('fields',[]):
                key=field['setting']; typ=field.get('type','text')
                if key=='__input_dir__':
                    value=str(gui_state.get('input_dir',''))
                else:
                    value=_setting_get(restored,key)
                if typ=='choice':
                    reverse={str(internal):str(display) for display,internal in field.get('choice_values',{}).items()}
                    value=reverse.get(str(value),str(value if value is not None else ''))
                elif typ=='bool': value=bool(value)
                else: value=str(value if value is not None else '')
                if key in self.vars: self.vars[key].set(value)

            if '__output_dir__' in self.vars:
                self.vars['__output_dir__'].set(str(gui_state.get('output_dir','')))
            for key in ['project.threads','execution.wsl_distribution','execution.micromamba_environment','execution.micromamba_executable','execution.micromamba_root_prefix','execution.python_executable_in_wsl']:
                if key in self.vars:
                    self.vars[key].set(str(_setting_get(restored,key)))

            self._verify_target_bed(False)
            self.status.set(f'Settings restored from: {restore_path}')
            self.messagebox.showinfo(
                'Settings restored',
                'Settings restored successfully, including BAM folder, output folder, Reference FASTA and target BED.\n\n'+str(restore_path),
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

        bed_summary=self.bed_status_text.get() if hasattr(self,'bed_status_text') else 'BED restriction status unavailable.'
        self.status.set(
            bed_summary + "\n\nCOMMAND:\n" + " ".join(shlex.quote(x) for x in cmd)
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
            self.backup_settings_button.configure(state="disabled")
            self.restore_settings_button.configure(state="disabled")
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
            self.backup_settings_button.configure(state="normal")
            self.restore_settings_button.configure(state="normal")
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
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

try:
    import pysam
except ModuleNotFoundError:
    pysam = None



SPEC = StepSpecification(
    number=10,
    title="10_CALL_SNVS_AND_SMALL_INDELS",
    description=(
        "Call somatic SNVs and small insertions/deletions with Mutect2, learn "
        "orientation artifacts, filter candidates, and export PASS variants."
    ),
    default_input_dir="input",
    default_output_dir="output",
)


def bam_sample_name(path: Path) -> str:
    if pysam is None:
        return ""
    with pysam.AlignmentFile(path, "rb") as bam:
        names = {
            record.get("SM", "")
            for record in bam.header.to_dict().get("RG", [])
            if record.get("SM")
        }
    return sorted(names)[0] if names else ""



def _step08_full_bam_sample_id(path: Path) -> str:
    """
    Derive a sample ID from an accepted validated/full BAM filename.

    Examples:
        Sample1.analysis_ready.bam -> Sample1
        Sample1_analysis_ready.bam -> Sample1
        Sample1.validated.bam      -> Sample1
        Sample1_VALIDATED.bam      -> Sample1
    """
    stem = path.name[:-4] if path.name.lower().endswith(".bam") else path.stem
    lower = stem.lower()

    marker_positions = [
        pos
        for marker in ("analysis_ready", "validated")
        for pos in [lower.find(marker)]
        if pos >= 0
    ]

    if marker_positions:
        prefix = stem[: min(marker_positions)].rstrip("._- ")
        if prefix:
            return prefix

    return stem


def _step08_is_validated_full_bam_name(path: Path) -> bool:
    """
    Step 08 tumor/matched-normal BAM naming rule.

    ACCEPT:
        *.bam containing 'analysis_ready' OR 'validated'

    REJECT:
        any filename containing 'abnormal'
        any BAM lacking both validation markers
    """
    name = path.name.lower()
    return (
        name.endswith(".bam")
        and "abnormal" not in name
        and ("analysis_ready" in name or "validated" in name)
    )


def classify_step08_bam_folder(
    input_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Scan all BAMs recursively and classify every file before Mutect2.

    The returned accepted table contains ONLY complete validated/full BAMs.
    """
    rows: list[dict[str, str]] = []
    accepted_rows: list[dict[str, str]] = []

    for path in sorted(input_dir.rglob("*.bam")):
        if not path.is_file():
            continue

        lower = path.name.lower()

        if "abnormal" in lower:
            bam_class = "REJECT_ABNORMAL"
            reason = (
                "Filename contains 'abnormal'. Step 08 Mutect2 requires the "
                "complete validated/full BAM, not Step 05 abnormal evidence."
            )
        elif "analysis_ready" in lower or "validated" in lower:
            bam_class = "ACCEPT_VALIDATED_FULL"
            reason = (
                "Filename contains analysis_ready or validated and does not "
                "contain abnormal."
            )
            accepted_rows.append(
                {
                    "SAMPLE_ID": _step08_full_bam_sample_id(path),
                    "BAM": str(path.resolve()),
                    "BAM_DISCOVERY": "STEP08_VALIDATED_FILENAME_SCAN",
                }
            )
        else:
            bam_class = "REJECT_NOT_VALIDATED_NAME"
            reason = (
                "Filename does not contain analysis_ready or validated."
            )

        rows.append(
            {
                "BAM": str(path.resolve()),
                "BAM_FILENAME": path.name,
                "STEP08_CLASS": bam_class,
                "REASON": reason,
            }
        )

    audit = pd.DataFrame(
        rows,
        columns=[
            "BAM",
            "BAM_FILENAME",
            "STEP08_CLASS",
            "REASON",
        ],
    )
    accepted = pd.DataFrame(
        accepted_rows,
        columns=[
            "SAMPLE_ID",
            "BAM",
            "BAM_DISCOVERY",
        ],
    )

    return accepted, audit


def validate_step08_tumor_inputs(
    accepted: pd.DataFrame,
    audit: pd.DataFrame,
) -> None:
    """
    Refuse Step 08 if any abnormal BAM is present or no validated/full BAM exists.
    """
    abnormal = (
        audit[audit["STEP08_CLASS"] == "REJECT_ABNORMAL"]
        if not audit.empty
        else pd.DataFrame()
    )

    if not abnormal.empty:
        raise ValueError(
            "STEP 08 INPUT REJECTED: BAM filename containing 'abnormal' detected.\n\n"
            "Mutect2 must use COMPLETE validated/full BAMs. Do not use Step 05 "
            "abnormal-evidence BAMs.\n\n"
            + abnormal[["BAM_FILENAME", "BAM"]].to_string(index=False)
        )

    if accepted.empty:
        rejected = (
            audit[audit["STEP08_CLASS"] == "REJECT_NOT_VALIDATED_NAME"]
            if not audit.empty
            else pd.DataFrame()
        )
        detail = ""
        if not rejected.empty:
            detail = (
                "\n\nBAMs found but rejected because their filenames did not "
                "contain 'analysis_ready' or 'validated':\n"
                + rejected[["BAM_FILENAME", "BAM"]].to_string(index=False)
            )

        raise ValueError(
            "STEP 08 INPUT REJECTED: no validated/full BAM was accepted.\n\n"
            "Accepted BAM filenames must contain 'analysis_ready' OR 'validated' "
            "and must NOT contain 'abnormal'."
            + detail
        )


def validate_step08_explicit_bam(
    bam_path: Path,
    label: str,
    dry_run: bool,
) -> None:
    """
    Apply the same validated/full filename rule to an explicitly selected BAM,
    such as the optional matched normal.
    """
    lower = bam_path.name.lower()

    if "abnormal" in lower:
        raise ValueError(
            f"{label} REJECTED: filename contains 'abnormal': {bam_path}\n"
            "Select the complete validated/full BAM instead."
        )

    if not (
        "analysis_ready" in lower
        or "validated" in lower
    ):
        raise ValueError(
            f"{label} REJECTED: filename must contain 'analysis_ready' or "
            f"'validated': {bam_path}"
        )

    if not dry_run:
        if (
            not bam_path.exists()
            or not bam_path.is_file()
            or bam_path.stat().st_size == 0
        ):
            raise FileNotFoundError(
                f"{label} was not found or is empty: {bam_path}"
            )


def _optional_step08_path_text(value: object) -> str:
    """Return an optional explicitly selected resource path, or blank."""
    return str(value or "").strip()



def parse_pass_vcf(path: Path, sample_id: str) -> pd.DataFrame:
    if pysam is None or not path.exists():
        return pd.DataFrame()
    rows: list[dict] = []
    with pysam.VariantFile(path) as vcf:
        samples = list(vcf.header.samples)
        sample_name = sample_id if sample_id in samples else (samples[0] if samples else None)
        for record in vcf:
            alternate = record.alts[0] if record.alts else ""
            sample = record.samples[sample_name] if sample_name else {}
            ad = sample.get("AD") if sample_name else None
            rows.append(
                {
                    "SAMPLE_ID": sample_id,
                    "CHROM": record.chrom,
                    "POS": int(record.pos),
                    "REF": record.ref,
                    "ALT": alternate,
                    "VARIANT_TYPE": (
                        "SNV" if len(record.ref) == 1 and len(alternate) == 1 else "INDEL"
                    ),
                    "FILTER": ";".join(record.filter.keys()) or "PASS",
                    "QUAL": record.qual,
                    "REF_COUNT": int(ad[0]) if ad and len(ad) >= 2 else "",
                    "ALT_COUNT": int(ad[1]) if ad and len(ad) >= 2 else "",
                    "VAF": sample_af(sample) if sample_name else float("nan"),
                    "TLOD": str(record.info.get("TLOD", "")),
                }
            )
    return pd.DataFrame(rows)


def filter_counts(path: Path, sample_id: str) -> pd.DataFrame:
    if pysam is None or not path.exists():
        return pd.DataFrame()
    counts: Counter = Counter()
    with pysam.VariantFile(path) as vcf:
        for record in vcf:
            filters = list(record.filter.keys())
            for value in filters or ["UNFILTERED"]:
                counts[value] += 1
    return pd.DataFrame(
        [{"SAMPLE_ID": sample_id, "FILTER": key, "COUNT": value} for key, value in counts.items()]
    )



def small_variant_parameter_rows(settings: dict) -> list[dict[str, object]]:
    cfg = settings["small_variants"]
    refs = settings["references"]
    return [
        {
            "PARAMETER": "tumor_bam_rule",
            "VALUE": "ANALYSIS_READY_OR_VALIDATED_AND_NOT_ABNORMAL",
            "EXPLANATION": (
                "Step 08 Mutect2 accepts only complete BAM filenames containing "
                "'analysis_ready' or 'validated'. Any filename containing "
                "'abnormal' is rejected."
            ),
        },
        {
            "PARAMETER": "enabled",
            "VALUE": bool(cfg["enabled"]),
            "EXPLANATION": "Run or skip Mutect2 SNV/small-indel calling.",
        },
        {
            "PARAMETER": "targets_bed",
            "VALUE": _optional_step08_path_text(refs["targets_bed"]),
            "EXPLANATION": (
                "Optional interval BED passed with -L. For targeted ctDNA panels, "
                "selecting the assay target BED keeps calling focused on intended regions."
            ),
        },
        {
            "PARAMETER": "germline_resource_vcf",
            "VALUE": _optional_step08_path_text(refs["germline_resource_vcf"]),
            "EXPLANATION": (
                "Optional population germline allele-frequency resource passed to "
                "Mutect2 --germline-resource; particularly useful in tumor-only calling."
            ),
        },
        {
            "PARAMETER": "panel_of_normals_vcf",
            "VALUE": _optional_step08_path_text(refs["panel_of_normals_vcf"]),
            "EXPLANATION": (
                "Optional Mutect2 Panel of Normals used to identify recurrent "
                "technical/artifactual sites."
            ),
        },
        {
            "PARAMETER": "matched_normal_bam",
            "VALUE": str(cfg["matched_normal_bam"]),
            "EXPLANATION": (
                "Optional matched-normal BAM. Leave empty for tumor-only calling. "
                "This pipeline applies the one selected normal to the current run."
            ),
        },
        {
            "PARAMETER": "matched_normal_sample_name",
            "VALUE": str(cfg["matched_normal_sample_name"]),
            "EXPLANATION": (
                "Read-group SM name for the matched normal. If omitted, Step 08 "
                "attempts to infer it from the normal BAM."
            ),
        },
        {
            "PARAMETER": "initial_tumor_lod",
            "VALUE": float(cfg["initial_tumor_lod"]),
            "EXPLANATION": (
                "Mutect2 initial candidate-emission tumor LOD threshold. Lowering "
                "it allows weaker candidate evidence into the unfiltered VCF; final "
                "FilterMutectCalls filtering still applies afterward."
            ),
        },
        {
            "PARAMETER": "maximum_reads_per_alignment_start",
            "VALUE": int(cfg["maximum_reads_per_alignment_start"]),
            "EXPLANATION": (
                "Mutect2 downsampling ceiling per alignment start. Reads above a "
                "positive threshold are downsampled; 0 disables this downsampling. "
                "The pipeline default is 0 to retain high-depth ctDNA evidence."
            ),
        },
        {
            "PARAMETER": "minimum_base_quality_score",
            "VALUE": int(cfg["minimum_base_quality_score"]),
            "EXPLANATION": (
                "Mutect2 minimum base quality. Bases below this score are not used "
                "for variant calling."
            ),
        },
        {
            "PARAMETER": "maximum_population_allele_frequency",
            "VALUE": float(cfg["maximum_population_allele_frequency"]),
            "EXPLANATION": (
                "Mutect2 --max-population-af used in tumor-only mode to exclude "
                "variants that are too common in the population germline resource."
            ),
        },
        {
            "PARAMETER": "native_pair_hmm_threads",
            "VALUE": int(cfg["native_pair_hmm_threads"]),
            "EXPLANATION": (
                "Native Pair-HMM worker threads used inside each Mutect2 job; automatically allocated from project.threads in the GUI. "
                "0 = automatic allocation from the global Threads budget."
            ),
        },
        {
            "PARAMETER": "parallel_samples",
            "VALUE": int(cfg["parallel_samples"]),
            "EXPLANATION": (
                "Number of tumor BAMs processed at the same time. "
                "0 = automatic allocation from the global Threads budget."
            ),
        },
    ]


def validate_small_variant_settings(settings: dict, dry_run: bool) -> None:
    cfg = settings["small_variants"]
    refs = settings["references"]

    if float(cfg["initial_tumor_lod"]) < 0:
        raise ValueError("Initial tumor LOD cannot be negative.")
    if int(cfg["maximum_reads_per_alignment_start"]) < 0:
        raise ValueError("Maximum reads per alignment start cannot be negative.")
    if not 0 <= int(cfg["minimum_base_quality_score"]) <= 93:
        raise ValueError("Minimum base-quality score must be between 0 and 93.")
    if not 0 <= float(cfg["maximum_population_allele_frequency"]) <= 1:
        raise ValueError("Maximum population allele frequency must be between 0 and 1.")
    if int(cfg["native_pair_hmm_threads"]) < 0:
        raise ValueError("Native Pair-HMM threads must be 0 (auto) or at least 1.")
    if int(cfg["parallel_samples"]) < 0:
        raise ValueError("Parallel samples must be 0 (auto) or at least 1.")

    if bool(cfg["enabled"]) and not dry_run:
        for label, value in [
            ("Target BED", _optional_step08_path_text(refs["targets_bed"])),
            (
                "Germline resource VCF",
                _optional_step08_path_text(refs["germline_resource_vcf"]),
            ),
            (
                "Panel of Normals VCF",
                _optional_step08_path_text(refs["panel_of_normals_vcf"]),
            ),
            ("Matched-normal BAM", cfg["matched_normal_bam"]),
        ]:
            value = str(value).strip()
            if not value:
                continue
            path = normalized_input_path(value)
            if not path.exists():
                raise FileNotFoundError(f"{label} was selected but not found: {path}")



def _resolve_mutect2_parallelism(
    settings: dict,
    sample_count: int,
) -> tuple[int, int]:
    """
    Return (parallel_sample_jobs, pairhmm_threads_per_job).

    The GUI has ONE CPU control: project.threads. Independent samples are run
    concurrently when possible, and the remaining CPU budget is assigned to
    Mutect2 PairHMM workers automatically.
    """
    cfg = settings["small_variants"]
    total_threads = max(1, int(settings["project"]["threads"]))
    sample_count = max(1, int(sample_count))
    requested_jobs = int(cfg.get("parallel_samples", 0))

    if requested_jobs > 0:
        jobs = min(sample_count, max(1, requested_jobs), total_threads)
    elif sample_count == 1:
        jobs = 1
    else:
        # Aim for at least ~4 PairHMM workers per Mutect2 process while making
        # use of independent tumor BAMs.
        jobs = min(sample_count, max(1, total_threads // 4))

    pairhmm = max(1, total_threads // jobs)
    return max(1, jobs), max(1, pairhmm)


def _run_one_mutect2_sample(
    row: dict,
    settings: dict,
    output_dir: Path,
    reference: Path,
    targets: str,
    germline: str,
    pon: str,
    normal_bam: Path | None,
    normal_name: str,
    pairhmm_threads: int,
    dry_run: bool,
) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """Run Mutect2, orientation modeling, filtering and PASS export for one sample."""
    cfg = settings["small_variants"]
    enabled = bool(cfg["enabled"])

    sample_id = str(row["SAMPLE_ID"])
    sample_dir = output_dir / sample_id
    sample_dir.mkdir(parents=True, exist_ok=True)

    updated = dict(row)
    updated["INPUT_BAM_VALIDATION"] = (
        "PASS_ANALYSIS_READY_OR_VALIDATED_AND_NOT_ABNORMAL"
    )

    unfiltered = sample_dir / f"{sample_id}.mutect2.unfiltered.vcf.gz"
    f1r2 = sample_dir / f"{sample_id}.f1r2.tar.gz"
    orientation = sample_dir / f"{sample_id}.orientation_model.tar.gz"
    filtered = sample_dir / f"{sample_id}.filtered.vcf.gz"
    passed = sample_dir / f"{sample_id}.PASS.vcf.gz"
    stats = Path(str(unfiltered) + ".stats")

    variants = pd.DataFrame()
    filters = pd.DataFrame()

    if enabled:
        optional = ""
        if is_nonempty(targets):
            optional += f" -L {quote(normalized_input_path(targets))}"
        if is_nonempty(germline):
            optional += (
                f" --germline-resource {quote(normalized_input_path(germline))}"
            )
        if is_nonempty(pon):
            optional += (
                f" --panel-of-normals {quote(normalized_input_path(pon))}"
            )
        if normal_bam is not None:
            if not normal_name:
                raise ValueError(
                    "A matched-normal BAM was selected but its sample name is unknown."
                )
            optional += f" -I {quote(normal_bam)} -normal {quote(normal_name)}"

        command = (
            f"{quote(settings['tools']['gatk'])} Mutect2 "
            f"-R {quote(reference)} -I {quote(row['BAM'])} "
            f"-tumor {quote(sample_id)} {optional} "
            f"--f1r2-tar-gz {quote(f1r2)} "
            f"--initial-tumor-lod {cfg['initial_tumor_lod']} "
            f"--max-reads-per-alignment-start "
            f"{cfg['maximum_reads_per_alignment_start']} "
            f"--min-base-quality-score {cfg['minimum_base_quality_score']} "
            f"--max-population-af "
            f"{cfg['maximum_population_allele_frequency']} "
            f"--native-pair-hmm-threads {int(pairhmm_threads)} "
            f"-O {quote(unfiltered)} && "
            f"{quote(settings['tools']['gatk'])} LearnReadOrientationModel "
            f"-I {quote(f1r2)} -O {quote(orientation)} && "
            f"{quote(settings['tools']['gatk'])} FilterMutectCalls "
            f"-R {quote(reference)} -V {quote(unfiltered)} "
            f"--stats {quote(stats)} --ob-priors {quote(orientation)} "
            f"-O {quote(filtered)} && "
            f"{quote(settings['tools']['bcftools'])} view -f PASS -Oz "
            f"-o {quote(passed)} {quote(filtered)} && "
            f"{quote(settings['tools']['bcftools'])} index -t {quote(passed)}"
        )
        run_command(
            command,
            output_dir / "logs" / f"{sample_id}.log",
            dry_run=dry_run,
            shell=True,
        )

        if not dry_run:
            variants = parse_pass_vcf(passed, sample_id)
            filters = filter_counts(filtered, sample_id)

    updated["UNFILTERED_SMALL_VARIANT_VCF"] = str(unfiltered)
    updated["FILTERED_SMALL_VARIANT_VCF"] = str(filtered)
    updated["PASS_SMALL_VARIANT_VCF"] = str(passed)
    updated["READ_ORIENTATION_MODEL"] = str(orientation)
    updated["PAIRHMM_THREADS_USED"] = int(pairhmm_threads)
    return updated, variants, filters


def backend(settings_path: Path, input_dir: Path, output_dir: Path, dry_run: bool) -> None:
    if pysam is None and not dry_run:
        raise ModuleNotFoundError("pysam is required in the WSL1 backend.")
    settings, _ = load_config(settings_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(output_dir / "10_CALL_SNVS_AND_SMALL_INDELS.log")

    enabled = bool(settings["small_variants"]["enabled"])
    require_tools(settings, ["gatk", "bcftools"], dry_run or not enabled)

    inputs, input_audit = classify_step08_bam_folder(input_dir)
    write_tsv(
        input_audit,
        output_dir / "step08_bam_input_scan.tsv",
    )
    validate_step08_tumor_inputs(inputs, input_audit)

    reference = normalized_input_path(settings["references"]["fasta"])
    targets = _optional_step08_path_text(
        settings["references"]["targets_bed"]
    )
    bed_info = None
    if is_nonempty(targets):
        bed_path = normalized_input_path(targets)
        bed_info = _analyze_target_bed(bed_path)
        if int(bed_info['valid_intervals']) < 1:
            raise ValueError(f'Target BED contains no valid intervals: {bed_path}')
        LOGGER.info(
            'TARGET BED RESTRICTION ACTIVE: Mutect2 will receive -L %s | intervals=%d | exact covered union=%s',
            str(bed_path), int(bed_info['valid_intervals']), _format_bp(int(bed_info['merged_total_bp']))
        )
    else:
        LOGGER.warning('TARGET BED RESTRICTION INACTIVE: Mutect2 will run without -L.')
    germline = _optional_step08_path_text(
        settings["references"]["germline_resource_vcf"]
    )
    pon = _optional_step08_path_text(
        settings["references"]["panel_of_normals_vcf"]
    )
    cfg = settings["small_variants"]
    validate_small_variant_settings(settings, dry_run)
    bed_audit_row = {
        'TARGET_RESTRICTION_ACTIVE': bool(is_nonempty(targets)),
        'TARGET_BED': targets,
        'MUTECT2_INTERVAL_ARGUMENT': (f'-L {targets}' if is_nonempty(targets) else ''),
        'VALID_BED_INTERVALS': int(bed_info['valid_intervals']) if bed_info else 0,
        'MERGED_UNION_INTERVALS': int(bed_info['merged_intervals']) if bed_info else 0,
        'EXACT_COVERED_UNION_BP': int(bed_info['merged_total_bp']) if bed_info else 0,
        'INVALID_BED_LINES': int(bed_info['invalid_lines']) if bed_info else 0,
    }
    write_tsv(pd.DataFrame([bed_audit_row]), output_dir / 'mutect2_target_bed_used.tsv')
    write_tsv(
        pd.DataFrame(small_variant_parameter_rows(settings)),
        output_dir / "small_variant_parameters_used.tsv",
    )

    normal_bam_text = str(cfg["matched_normal_bam"]).strip()
    normal_bam = (
        normalized_input_path(normal_bam_text)
        if normal_bam_text
        else None
    )
    normal_name = str(cfg["matched_normal_sample_name"]).strip()

    if normal_bam is not None:
        validate_step08_explicit_bam(
            normal_bam,
            "Matched-normal BAM",
            dry_run,
        )

        if not normal_name and not dry_run:
            normal_name = bam_sample_name(normal_bam)

        if not normal_name and dry_run:
            # Dry-run must remain runnable even though BAM-header SM inference is
            # intentionally deferred to the real run.
            normal_name = "INFER_FROM_BAM_HEADER_ON_REAL_RUN"

    output_rows: list[dict] = []
    variant_tables: list[pd.DataFrame] = []
    filter_tables: list[pd.DataFrame] = []

    input_records = inputs.to_dict(orient="records")
    parallel_jobs, pairhmm_threads = _resolve_mutect2_parallelism(
        settings,
        len(input_records),
    )

    LOGGER.info(
        "Mutect2 CPU plan: global Threads=%d; parallel sample jobs=%d; "
        "PairHMM threads/job=%d; target BED=%s",
        int(settings["project"]["threads"]),
        parallel_jobs,
        pairhmm_threads,
        targets if is_nonempty(targets) else "<NONE: full selected reference will be traversed>",
    )

    write_tsv(
        pd.DataFrame(
            [
                {
                    "GLOBAL_THREADS_BUDGET": int(settings["project"]["threads"]),
                    "PARALLEL_SAMPLE_JOBS": int(parallel_jobs),
                    "PAIRHMM_THREADS_PER_JOB": int(pairhmm_threads),
                    "TARGET_BED": targets,
                    "TARGET_RESTRICTION_ACTIVE": bool(is_nonempty(targets)),
                }
            ]
        ),
        output_dir / "mutect2_parallelism_used.tsv",
    )

    from concurrent.futures import ThreadPoolExecutor, as_completed

    results_by_index: dict[int, tuple[dict, pd.DataFrame, pd.DataFrame]] = {}

    if parallel_jobs <= 1 or len(input_records) <= 1:
        for index, row in enumerate(input_records):
            results_by_index[index] = _run_one_mutect2_sample(
                row=row,
                settings=settings,
                output_dir=output_dir,
                reference=reference,
                targets=targets,
                germline=germline,
                pon=pon,
                normal_bam=normal_bam,
                normal_name=normal_name,
                pairhmm_threads=pairhmm_threads,
                dry_run=dry_run,
            )
    else:
        with ThreadPoolExecutor(
            max_workers=parallel_jobs,
            thread_name_prefix="mutect2_sample",
        ) as executor:
            future_to_index = {
                executor.submit(
                    _run_one_mutect2_sample,
                    row,
                    settings,
                    output_dir,
                    reference,
                    targets,
                    germline,
                    pon,
                    normal_bam,
                    normal_name,
                    pairhmm_threads,
                    dry_run,
                ): index
                for index, row in enumerate(input_records)
            }
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                results_by_index[index] = future.result()

    for index in sorted(results_by_index):
        updated, variants, filters = results_by_index[index]
        output_rows.append(updated)
        if not variants.empty:
            variant_tables.append(variants)
        if not filters.empty:
            filter_tables.append(filters)

    output_manifest = pd.DataFrame(output_rows)
    variants = pd.concat(variant_tables, ignore_index=True) if variant_tables else pd.DataFrame()
    filters = pd.concat(filter_tables, ignore_index=True) if filter_tables else pd.DataFrame()
    write_tsv(output_manifest, output_dir / "small_variant_results.tsv")
    write_tsv(variants, output_dir / "somatic_snvs_and_small_indels.tsv")
    write_tsv(filters, output_dir / "mutect2_filter_counts.tsv")

    plots: list[Path] = []
    count_plot = output_dir / "pass_small_variant_counts.png"
    if variants.empty:
        save_placeholder_plot(
            count_plot,
            "PASS SNV and small-indel counts",
            "No PASS small variants were available.",
        )
    else:
        counts = variants.groupby(["SAMPLE_ID", "VARIANT_TYPE"]).size()
        labels = [f"{sample}_{kind}" for sample, kind in counts.index]
        save_bar_plot(
            labels, counts.astype(float).tolist(),
            count_plot, "PASS small variants", "Variant count", rotate=65,
        )
    plots.append(count_plot)

    vaf_plot = output_dir / "pass_small_variant_vaf_distribution.png"
    vaf = (
        pd.to_numeric(variants["VAF"], errors="coerce").dropna()
        if not variants.empty else pd.Series(dtype=float)
    )
    if vaf.empty:
        save_placeholder_plot(vaf_plot, "PASS variant VAF", "No VAF values available.")
    else:
        figure, axis = plt.subplots(figsize=(9, 6))
        axis.hist(vaf, bins=60)
        axis.set_xlabel("Variant allele fraction")
        axis.set_ylabel("PASS variant count")
        axis.set_title("PASS SNV/small-indel VAF distribution")
        axis.grid(axis="y", alpha=0.25)
        figure.tight_layout()
        figure.savefig(vaf_plot, dpi=180)
        plt.close(figure)
    plots.append(vaf_plot)

    filter_plot = output_dir / "mutect2_filter_reason_counts.png"
    if filters.empty:
        save_placeholder_plot(filter_plot, "Mutect2 filter reasons", "No filter table available.")
    else:
        totals = filters.groupby("FILTER")["COUNT"].sum().sort_values(ascending=False).head(30)
        save_bar_plot(
            totals.index.astype(str).tolist(), totals.astype(float).tolist(),
            filter_plot, "Mutect2 filter categories", "Assignments", rotate=65,
        )
    plots.append(filter_plot)

    write_step_status(
        output_dir,
        SPEC.title,
        "PASS" if enabled else "SKIP",
        (
            f"Produced {len(variants)} PASS SNV/small-indel record(s) from validated/full BAM input(s)."
            if enabled else "Small-variant calling was disabled."
        ),
        len(output_manifest),
        plots,
    )
    print(output_dir / "somatic_snvs_and_small_indels.tsv")



STEP_GUI = {'environment': 'ctdna_gatk',
 'fields': [{'setting': '__input_dir__',
             'label': 'Validated/full tumor BAM folder',
             'type': 'folder',
             'required': True,
             'scan_globs': ['*.bam'],
             'accept_name_contains_any': ['analysis_ready', 'validated'],
             'reject_name_contains': ['abnormal', 'aberrant'],
             'help': 'Mutect2 must use complete BAM evidence, not Step 05 abnormal BAMs.',
             'section': 'TUMOR / NORMAL / REFERENCE INPUTS'},
            {'setting': 'references.fasta',
             'label': 'Reference FASTA',
             'type': 'file',
             'required': True,
             'allowed_suffixes': ['.fa', '.fasta', '.fna'],
             'filetypes': [('FASTA', '*.fa *.fasta *.fna'), ('All files', '*.*')],
             'button_text': 'Browse reference FASTA',
             'section': 'TUMOR / NORMAL / REFERENCE INPUTS'},
            {'setting': 'references.targets_bed',
             'label': 'Optional target BED — strongly recommended for targeted sequencing',
             'type': 'file',
             'required': False,
             'allowed_suffixes': ['.bed'],
             'filetypes': [('BED', '*.bed'), ('All files', '*.*')],
             'button_text': 'Browse target BED',
             'help': 'Restricts Mutect2 with -L to the intended target regions. After selecting the BED, use Verify BED / -L: the GUI reports interval count, total covered bases and the exact -L path. The same information is written to mutect2_target_bed_used.tsv and each sample log contains the exact Mutect2 command.',
             'section': 'TUMOR / NORMAL / REFERENCE INPUTS'},
            {'setting': 'small_variants.matched_normal_bam',
             'label': 'Optional matched-normal BAM (single complete BAM)',
             'type': 'file',
             'required': False,
             'allowed_suffixes': ['.bam'],
             'filetypes': [('BAM', '*.bam'), ('All files', '*.*')],
             'button_text': 'Browse matched-normal BAM',
             'accept_name_contains_any': ['analysis_ready', 'validated'],
             'reject_name_contains': ['abnormal', 'aberrant'],
             'help': 'Use a validated/analysis-ready matched normal, never an abnormal BAM subset.',
             'section': 'TUMOR / NORMAL / REFERENCE INPUTS'},
            {'setting': 'small_variants.matched_normal_sample_name',
             'label': 'Matched-normal sample name',
             'type': 'text',
             'required': False,
             'section': 'MUTECT2 PARAMETERS'},
            {'setting': 'references.germline_resource_vcf',
             'label': 'Optional germline population resource VCF',
             'type': 'file',
             'required': False,
             'allowed_suffixes': ['.vcf', '.vcf.gz'],
             'filetypes': [('VCF', '*.vcf *.vcf.gz'), ('All files', '*.*')],
             'button_text': 'Browse germline VCF',
             'section': 'TUMOR / NORMAL / REFERENCE INPUTS'},
            {'setting': 'references.panel_of_normals_vcf',
             'label': 'Optional Mutect2 Panel-of-Normals VCF',
             'type': 'file',
             'required': False,
             'allowed_suffixes': ['.vcf', '.vcf.gz'],
             'filetypes': [('VCF', '*.vcf *.vcf.gz'), ('All files', '*.*')],
             'button_text': 'Browse PoN VCF',
             'section': 'TUMOR / NORMAL / REFERENCE INPUTS'},
            {'setting': 'small_variants.initial_tumor_lod',
             'label': 'Mutect2 initial tumor LOD',
             'type': 'float',
             'required': True,
             'section': 'MUTECT2 PARAMETERS'},
            {'setting': 'small_variants.minimum_base_quality_score',
             'label': 'Minimum base quality score',
             'type': 'int',
             'required': True,
             'section': 'MUTECT2 PARAMETERS'},
            {'setting': 'small_variants.maximum_reads_per_alignment_start',
             'label': 'Maximum reads per alignment start (0 = GATK behavior/default)',
             'type': 'int',
             'required': True,
             'section': 'MUTECT2 PARAMETERS'},
            {'setting': 'small_variants.parallel_samples',
             'label': 'Parallel tumor BAMs / samples (0 = auto)',
             'type': 'int',
             'required': True,
             'help': 'Runs independent tumor samples simultaneously. 0 automatically balances concurrent Mutect2 jobs against PairHMM threads so the total CPU request stays near the global Threads setting.',
             'section': 'PERFORMANCE'}],
 'explanation': 'Calls somatic SNVs and small indels with GATK Mutect2 from complete validated tumor/cfDNA BAMs. The GUI exposes one CPU setting only: Threads / total CPU cores; PairHMM workers are allocated automatically. '
                'For targeted sequencing, select a target BED so Mutect2 does not scan unnecessary genome regions. '
                'Step 10 can process independent BAM samples in parallel and automatically allocate PairHMM threads '
                'from the global Threads budget. Matched-normal, germline population resource and Panel-of-Normals '
                'inputs are optional but should match the reference build and assay.'}

if __name__ == "__main__":
    launch_step(SPEC, backend)
