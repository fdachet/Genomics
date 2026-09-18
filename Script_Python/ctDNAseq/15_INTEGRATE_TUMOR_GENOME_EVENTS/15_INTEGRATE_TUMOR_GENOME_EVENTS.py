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
    parser.add_argument('--integration-full-consensus-sv-tsv', dest='__cfg__integration_full__consensus_sv_tsv', type=str, default='', help='Override integration_full.consensus_sv_tsv for this execution.')
    parser.add_argument('--integration-full-copy-number-segments-tsv', dest='__cfg__integration_full__copy_number_segments_tsv', type=str, default='', help='Override integration_full.copy_number_segments_tsv for this execution.')
    parser.add_argument('--integration-full-allele-specific-loh-tsv', dest='__cfg__integration_full__allele_specific_loh_tsv', type=str, default='', help='Override integration_full.allele_specific_loh_tsv for this execution.')
    parser.add_argument('--integration-full-molecular-variants-tsv', dest='__cfg__integration_full__molecular_variants_tsv', type=str, default='', help='Override integration_full.molecular_variants_tsv for this execution.')
    parser.add_argument('--integration-full-ctdna-fraction-tsv', dest='__cfg__integration_full__ctdna_fraction_tsv', type=str, default='', help='Override integration_full.ctdna_fraction_tsv for this execution.')
    parser.add_argument('--integration-full-reference-fasta', dest='__cfg__integration_full__reference_fasta', type=str, default='', help='Override integration_full.reference_fasta for this execution.')
    parser.add_argument('--integration-full-nearby-variant-window-bp', dest='__cfg__integration_full__nearby_variant_window_bp', type=int, default=1000000, help='Override integration_full.nearby_variant_window_bp for this execution.')
    parser.add_argument('--integration-full-graph-include-normal-adjacencies', dest='__cfg__integration_full__graph_include_normal_adjacencies', type=_parse_cli_bool, default=True, help='Override integration_full.graph_include_normal_adjacencies for this execution.')
    parser.add_argument('--integration-full-include-neutral-cnv-segments', dest='__cfg__integration_full__include_neutral_cnv_segments', type=_parse_cli_bool, default=True, help='Override integration_full.include_neutral_cnv_segments for this execution.')
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
 'integration_full': {},
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


from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
import numpy as np
import pandas as pd

try:
    import networkx as nx
except ModuleNotFoundError:
    nx = None



SPEC = StepSpecification(
    number=15,
    title="15_INTEGRATE_TUMOR_GENOME_EVENTS",
    description=(
        "Combine structural-variant breakpoints, copy-number segments, and "
        "small variants; construct a segment-and-junction tumor-genome graph; "
        "and propose candidate derivative-chromosome connections."
    ),
    default_input_dir="input",
    default_output_dir="output",
)


def optional_table(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, sep="\t")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def reference_lengths(reference_fasta: Path) -> dict[str, int]:
    fai = Path(str(reference_fasta) + ".fai")
    lengths: dict[str, int] = {}
    if not fai.exists():
        return lengths
    with fai.open("r", encoding="utf-8") as handle:
        for line in handle:
            pieces = line.rstrip("\n").split("\t")
            if len(pieces) >= 2:
                lengths[pieces[0]] = int(pieces[1])
    return lengths


def normalize_cnv(cnv: pd.DataFrame) -> pd.DataFrame:
    """Normalize Step 07 CNV columns, preferring current signed-ratio fields."""
    if cnv.empty:
        return cnv

    rename: dict[str, str] = {}
    for column in cnv.columns:
        lower = column.lower()
        if lower == "chromosome":
            rename[column] = "CHROM"
        elif lower == "start":
            rename[column] = "START"
        elif lower == "end":
            rename[column] = "END"
        elif lower == "signed_copy_ratio":
            rename[column] = "SIGNED_COPY_RATIO"
        elif lower == "log2":
            rename[column] = "LOG2"
        elif lower == "call" and "CALL" not in cnv.columns:
            rename[column] = "CALL"

    cnv = cnv.rename(columns=rename)

    for required in ["CHROM", "START", "END"]:
        if required not in cnv.columns:
            cnv[required] = ""

    # Current Step 07 classification takes priority over any legacy CALL field.
    signed_call_columns = [
        column
        for column in cnv.columns
        if column.lower() == "call_by_signed_copy_ratio"
    ]
    if signed_call_columns:
        cnv["CALL"] = cnv[signed_call_columns[0]].astype(str)
    elif "CALL" not in cnv.columns:
        cnv["CALL"] = "UNKNOWN"

    cnv["START"] = pd.to_numeric(cnv["START"], errors="coerce")
    cnv["END"] = pd.to_numeric(cnv["END"], errors="coerce")

    if "SIGNED_COPY_RATIO" in cnv.columns:
        cnv["SIGNED_COPY_RATIO"] = pd.to_numeric(
            cnv["SIGNED_COPY_RATIO"], errors="coerce"
        )
    else:
        cnv["SIGNED_COPY_RATIO"] = np.nan

    # Backward compatibility with older Step 07 outputs.
    if cnv["SIGNED_COPY_RATIO"].isna().all() and "LOG2" in cnv.columns:
        log2 = pd.to_numeric(cnv["LOG2"], errors="coerce")
        ordinary = np.power(2.0, log2)
        cnv["SIGNED_COPY_RATIO"] = np.where(
            ordinary >= 1.0,
            ordinary,
            -1.0 / ordinary,
        )

    return cnv



def _interval_group_from_frame(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    """Create a compact interval group while preserving the original row order."""
    return {
        "START": pd.to_numeric(frame["START"], errors="coerce").to_numpy(dtype=float),
        "END": pd.to_numeric(frame["END"], errors="coerce").to_numpy(dtype=float),
        "CALL": frame["CALL"].astype(str).to_numpy(dtype=object),
        "RATIO": pd.to_numeric(
            frame["SIGNED_COPY_RATIO"], errors="coerce"
        ).to_numpy(dtype=float),
    }


def build_cnv_interval_index(cnv: pd.DataFrame) -> dict[str, object]:
    """
    Build chromosome/sample CNV interval indexes once.

    This preserves the exact selection semantics of the previous cnv_at():
    when a sample-specific overlapping segment exists it is used; otherwise the
    first overlapping segment from the chromosome-wide table is used.
    """
    index: dict[str, object] = {
        "all": {},
        "sample": {},
        "has_sample": "SAMPLE_ID" in cnv.columns,
    }
    if cnv.empty:
        return index

    all_groups: dict[str, dict[str, np.ndarray]] = {}
    for chromosome, group in cnv.groupby(cnv["CHROM"].astype(str), sort=False):
        all_groups[str(chromosome)] = _interval_group_from_frame(group)
    index["all"] = all_groups

    if "SAMPLE_ID" in cnv.columns:
        sample_groups: dict[tuple[str, str], dict[str, np.ndarray]] = {}
        for (sample_id, chromosome), group in cnv.groupby(
            [cnv["SAMPLE_ID"].astype(str), cnv["CHROM"].astype(str)],
            sort=False,
        ):
            sample_groups[(str(sample_id), str(chromosome))] = (
                _interval_group_from_frame(group)
            )
        index["sample"] = sample_groups

    return index


def _query_cnv_interval_group(
    group: dict[str, np.ndarray] | None,
    position: int,
) -> tuple[str, float] | None:
    if not group:
        return None

    starts = group["START"]
    ends = group["END"]
    hits = np.flatnonzero((starts <= position) & (ends >= position))
    if hits.size == 0:
        return None

    i = int(hits[0])
    return str(group["CALL"][i]), float(group["RATIO"][i])


def cnv_at_indexed(
    cnv_index: dict[str, object],
    sample_id: str,
    chromosome: str,
    position: int,
) -> tuple[str, float]:
    chromosome = str(chromosome)
    sample_id = str(sample_id)

    if bool(cnv_index.get("has_sample")) and sample_id:
        sample_groups = cnv_index.get("sample", {})
        result = _query_cnv_interval_group(
            sample_groups.get((sample_id, chromosome)),
            position,
        )
        if result is not None:
            return result

    all_groups = cnv_index.get("all", {})
    result = _query_cnv_interval_group(
        all_groups.get(chromosome),
        position,
    )
    return result if result is not None else ("UNKNOWN", float("nan"))


def cnv_at(
    cnv: pd.DataFrame,
    sample_id: str,
    chromosome: str,
    position: int,
) -> tuple[str, float]:
    """Compatibility wrapper; performance-sensitive code uses a prebuilt index."""
    return cnv_at_indexed(
        build_cnv_interval_index(cnv),
        sample_id,
        chromosome,
        position,
    )


def build_snv_position_index(snv: pd.DataFrame) -> dict[str, object]:
    """
    Build sorted position arrays for exact inclusive nearby-SNV counting.

    The old implementation re-filtered the entire SNV DataFrame twice for every
    breakpoint. Search-sorted arrays return the same counts in O(log N) time.
    """
    index: dict[str, object] = {
        "all": {},
        "sample": {},
        "has_sample": "SAMPLE_ID" in snv.columns,
    }
    if snv.empty:
        return index

    positions = pd.to_numeric(snv["POS"], errors="coerce")
    valid = positions.notna()
    if not bool(valid.any()):
        return index

    compact = pd.DataFrame(
        {
            "CHROM": snv.loc[valid, "CHROM"].astype(str).to_numpy(),
            "POS": positions.loc[valid].to_numpy(dtype=float),
        }
    )
    if "SAMPLE_ID" in snv.columns:
        compact["SAMPLE_ID"] = snv.loc[valid, "SAMPLE_ID"].astype(str).to_numpy()

    all_groups: dict[str, np.ndarray] = {}
    for chromosome, group in compact.groupby("CHROM", sort=False):
        all_groups[str(chromosome)] = np.sort(
            group["POS"].to_numpy(dtype=float)
        )
    index["all"] = all_groups

    if "SAMPLE_ID" in compact.columns:
        sample_groups: dict[tuple[str, str], np.ndarray] = {}
        for (sample_id, chromosome), group in compact.groupby(
            ["SAMPLE_ID", "CHROM"], sort=False
        ):
            sample_groups[(str(sample_id), str(chromosome))] = np.sort(
                group["POS"].to_numpy(dtype=float)
            )
        index["sample"] = sample_groups

    return index


def _count_sorted_positions(
    positions: np.ndarray | None,
    position: int,
    window: int,
) -> int:
    if positions is None or positions.size == 0:
        return 0
    lower = int(position) - int(window)
    upper = int(position) + int(window)
    left = int(np.searchsorted(positions, lower, side="left"))
    right = int(np.searchsorted(positions, upper, side="right"))
    return right - left


def nearby_snv_count_indexed(
    snv_index: dict[str, object],
    sample_id: str,
    chromosome: str,
    position: int,
    window: int,
) -> int:
    chromosome = str(chromosome)
    sample_id = str(sample_id)

    all_groups = snv_index.get("all", {})
    all_count = _count_sorted_positions(
        all_groups.get(chromosome), position, window
    )

    # Preserve the original fallback rule exactly: if there are zero
    # sample-specific variants in this window, use all variants in the window.
    if bool(snv_index.get("has_sample")) and sample_id:
        sample_groups = snv_index.get("sample", {})
        sample_count = _count_sorted_positions(
            sample_groups.get((sample_id, chromosome)),
            position,
            window,
        )
        if sample_count > 0:
            return sample_count

    return all_count


def nearby_snv_count(
    snv: pd.DataFrame,
    sample_id: str,
    chromosome: str,
    position: int,
    window: int,
) -> int:
    """Compatibility wrapper; performance-sensitive code uses a prebuilt index."""
    return nearby_snv_count_indexed(
        build_snv_position_index(snv),
        sample_id,
        chromosome,
        position,
        window,
    )


def segment_node_id(chromosome: str, start: int, end: int) -> str:
    return f"{chromosome}:{start}-{end}"


def build_node_interval_index(nodes: pd.DataFrame) -> dict[str, dict[str, np.ndarray]]:
    """Index non-overlapping graph nodes by chromosome for fast breakpoint lookup."""
    index: dict[str, dict[str, np.ndarray]] = {}
    if nodes.empty:
        return index

    for chromosome, group in nodes.groupby("CHROM", sort=False):
        ordered = group.sort_values("START", kind="stable")
        index[str(chromosome)] = {
            "START": ordered["START"].to_numpy(dtype=np.int64),
            "END": ordered["END"].to_numpy(dtype=np.int64),
            "NODE_ID": ordered["NODE_ID"].astype(str).to_numpy(dtype=object),
        }
    return index


def locate_node_indexed(
    node_index: dict[str, dict[str, np.ndarray]],
    chromosome: str,
    position: int,
) -> str:
    group = node_index.get(str(chromosome))
    if not group:
        return ""

    starts = group["START"]
    i = int(np.searchsorted(starts, int(position), side="right") - 1)
    if i < 0:
        return ""
    if int(group["END"][i]) < int(position):
        return ""
    return str(group["NODE_ID"][i])


def locate_node(nodes: pd.DataFrame, chromosome: str, position: int) -> str:
    """Compatibility wrapper; build_graph_tables uses one prebuilt node index."""
    return locate_node_indexed(
        build_node_interval_index(nodes), chromosome, position
    )


def build_graph_tables(
    breakpoints: pd.DataFrame,
    cnv: pd.DataFrame,
    lengths: dict[str, int],
    include_normal: bool,
    cnv_index: dict[str, object] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    affected: set[str] = set()
    boundaries: dict[str, set[int]] = defaultdict(lambda: {1})
    if cnv_index is None:
        cnv_index = build_cnv_interval_index(cnv)

    if not breakpoints.empty:
        for row in breakpoints.to_dict(orient="records"):
            for chrom_key, pos_key in (("CHROM1", "POS1"), ("CHROM2", "POS2")):
                chromosome = str(row.get(chrom_key, ""))
                if not chromosome:
                    continue
                position = int(float(row.get(pos_key, 0) or 0))
                affected.add(chromosome)
                if position > 1:
                    boundaries[chromosome].add(position)
                    boundaries[chromosome].add(position + 1)

    if not cnv.empty:
        non_neutral = cnv[cnv["CALL"].astype(str) != "NEUTRAL"]
        for row in non_neutral.to_dict(orient="records"):
            chromosome = str(row["CHROM"])
            affected.add(chromosome)
            start = max(1, int(float(row["START"])) + 1)
            end = max(start, int(float(row["END"])))
            boundaries[chromosome].update({start, end + 1})

    for chromosome in affected:
        inferred = 0
        if not cnv.empty:
            values = pd.to_numeric(
                cnv.loc[cnv["CHROM"].astype(str) == chromosome, "END"],
                errors="coerce",
            ).dropna()
            if not values.empty:
                inferred = int(values.max())
        if not breakpoints.empty:
            for key, pos_key in (("CHROM1", "POS1"), ("CHROM2", "POS2")):
                values = pd.to_numeric(
                    breakpoints.loc[
                        breakpoints[key].astype(str) == chromosome,
                        pos_key,
                    ],
                    errors="coerce",
                ).dropna()
                if not values.empty:
                    inferred = max(inferred, int(values.max()) + 1)
        chromosome_length = int(lengths.get(chromosome, inferred or 1))
        boundaries[chromosome].add(chromosome_length + 1)

    node_rows: list[dict] = []
    for chromosome in sorted(affected):
        points = sorted(value for value in boundaries[chromosome] if value >= 1)
        for left, right in zip(points, points[1:]):
            start, end = left, right - 1
            if end < start:
                continue
            midpoint = (start + end) // 2
            call, signed_ratio = cnv_at_indexed(
                cnv_index, "", chromosome, midpoint
            )
            node_rows.append(
                {
                    "NODE_ID": segment_node_id(chromosome, start, end),
                    "CHROM": chromosome,
                    "START": start,
                    "END": end,
                    "LENGTH": end - start + 1,
                    "COPY_NUMBER_CALL": call,
                    "COPY_NUMBER_SIGNED_RATIO": signed_ratio,
                }
            )
    nodes = pd.DataFrame(node_rows)

    edge_rows: list[dict] = []
    if include_normal and not nodes.empty:
        for chromosome, group in nodes.groupby("CHROM"):
            ordered = group.sort_values("START").to_dict(orient="records")
            for left, right in zip(ordered, ordered[1:]):
                edge_rows.append(
                    {
                        "EDGE_ID": f"NORMAL::{left['NODE_ID']}::{right['NODE_ID']}",
                        "SOURCE_NODE": left["NODE_ID"],
                        "TARGET_NODE": right["NODE_ID"],
                        "EDGE_TYPE": "REFERENCE_ADJACENCY",
                        "SAMPLE_ID": "",
                        "SVTYPE": "",
                        "BREAKPOINT_SOURCE": "REFERENCE",
                    }
                )

    if not breakpoints.empty and not nodes.empty:
        node_index = build_node_interval_index(nodes)
        for index, row in enumerate(breakpoints.to_dict(orient="records"), start=1):
            source = locate_node_indexed(
                node_index, str(row["CHROM1"]), int(float(row["POS1"]))
            )
            target = locate_node_indexed(
                node_index, str(row["CHROM2"]), int(float(row["POS2"]))
            )
            if source and target:
                edge_rows.append(
                    {
                        "EDGE_ID": f"TUMOR_JUNCTION_{index}",
                        "SOURCE_NODE": source,
                        "TARGET_NODE": target,
                        "EDGE_TYPE": "TUMOR_JUNCTION",
                        "SAMPLE_ID": row.get("SAMPLE_ID", ""),
                        "SVTYPE": row.get("SVTYPE", "BND"),
                        "BREAKPOINT_SOURCE": row.get("SOURCE", ""),
                    }
                )
    return nodes, pd.DataFrame(edge_rows)


def write_gfa(nodes: pd.DataFrame, edges: pd.DataFrame, path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write("H\\tVN:Z:1.0\\n")
        for row in nodes.to_dict(orient="records"):
            signed_ratio = row.get("COPY_NUMBER_SIGNED_RATIO", "")
            handle.write(
                f"S\\t{row['NODE_ID']}\\t*\\tLN:i:{int(row['LENGTH'])}"
                f"\\tCN:Z:{row.get('COPY_NUMBER_CALL', 'UNKNOWN')}"
                f"\\tSR:Z:{signed_ratio}\\n"
            )
        for row in edges.to_dict(orient="records"):
            handle.write(
                f"L\\t{row['SOURCE_NODE']}\\t+\\t{row['TARGET_NODE']}\\t+\\t0M"
                f"\\tET:Z:{row['EDGE_TYPE']}\\n"
            )



def chromosome_sort_key(chromosome: str) -> tuple[int, object]:
    clean = str(chromosome).lower().replace("chromosome", "").replace("chr", "")
    if clean.isdigit():
        return (0, int(clean))
    special = {"x": 23, "y": 24, "m": 25, "mt": 25}
    if clean in special:
        return (0, special[clean])
    return (1, clean)


def _fast_genomic_graph_plot(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    path: Path,
) -> None:
    """
    Fast deterministic large-graph visualization.

    Nodes are positioned by chromosome and genomic midpoint. This changes only
    the drawing layout; graph nodes, graph edges, CNV calls, breakpoint links,
    and every scientific TSV/GFA result are unchanged.
    """
    node_table = nodes.copy()
    node_table["MIDPOINT_MB"] = (
        pd.to_numeric(node_table["START"], errors="coerce")
        + pd.to_numeric(node_table["END"], errors="coerce")
    ) / 2_000_000.0

    chromosomes = sorted(
        node_table["CHROM"].astype(str).unique(),
        key=chromosome_sort_key,
    )
    y_map = {chrom: float(len(chromosomes) - i - 1) for i, chrom in enumerate(chromosomes)}

    node_table["Y"] = node_table["CHROM"].astype(str).map(y_map).astype(float)
    node_table["X"] = pd.to_numeric(node_table["MIDPOINT_MB"], errors="coerce")

    position = {
        str(row.NODE_ID): (float(row.X), float(row.Y))
        for row in node_table.itertuples(index=False)
        if np.isfinite(float(row.X))
    }

    figure_height = max(7.0, min(18.0, 0.5 * len(chromosomes) + 3.0))
    figure, axis = plt.subplots(figsize=(16, figure_height))

    # Draw chromosome baselines in a single collection.
    baseline_segments: list[list[tuple[float, float]]] = []
    for chromosome, group in node_table.groupby(node_table["CHROM"].astype(str), sort=False):
        x_values = pd.to_numeric(group["X"], errors="coerce").dropna()
        if x_values.empty:
            continue
        y = y_map[str(chromosome)]
        baseline_segments.append([(float(x_values.min()), y), (float(x_values.max()), y)])
    if baseline_segments:
        axis.add_collection(LineCollection(baseline_segments, linewidths=0.6, alpha=0.25))

    # Nodes: one scatter call rather than thousands of NetworkX artists.
    axis.scatter(
        node_table["X"],
        node_table["Y"],
        s=8,
        alpha=0.65,
        zorder=3,
    )

    normal_segments: list[list[tuple[float, float]]] = []
    tumor_segments: list[list[tuple[float, float]]] = []
    tumor_nodes: set[str] = set()

    for row in edges.itertuples(index=False):
        source = str(row.SOURCE_NODE)
        target = str(row.TARGET_NODE)
        if source not in position or target not in position:
            continue
        segment = [position[source], position[target]]
        if str(row.EDGE_TYPE) == "TUMOR_JUNCTION":
            tumor_segments.append(segment)
            tumor_nodes.update((source, target))
        else:
            normal_segments.append(segment)

    if normal_segments:
        axis.add_collection(
            LineCollection(normal_segments, linewidths=0.45, alpha=0.18, zorder=1)
        )
    if tumor_segments:
        axis.add_collection(
            LineCollection(
                tumor_segments,
                linewidths=1.25,
                alpha=0.65,
                linestyles="dashed",
                zorder=2,
            )
        )

    # Labels are expensive and unreadable for thousands of nodes. Preserve useful
    # labels on small/medium large graphs; otherwise label only a bounded set of
    # tumor-junction nodes. This affects visualization only, not graph content.
    if len(nodes) <= 1000:
        label_nodes = list(position)
    else:
        label_nodes = sorted(tumor_nodes)[:200]

    for node_id in label_nodes:
        x, y = position[node_id]
        if len(nodes) <= 500:
            label = node_id.replace("chr", "", 1).replace(":", "\n", 1)
        else:
            label = node_id.split(":", 1)[0].replace("chr", "", 1)
        axis.text(x, y + 0.08, label, fontsize=5, ha="center", va="bottom", alpha=0.7)

    axis.set_yticks([y_map[c] for c in chromosomes])
    axis.set_yticklabels(chromosomes)
    axis.set_xlabel("Genomic position (Mb)")
    axis.set_ylabel("Chromosome")
    axis.set_title(
        "Segment-and-junction tumor-genome graph — genomic-position layout "
        f"({len(nodes):,} nodes, {len(edges):,} edges)"
    )
    axis.grid(axis="x", alpha=0.15)
    axis.autoscale_view()
    figure.tight_layout()
    figure.savefig(path, dpi=180)
    plt.close(figure)


def graph_plot(nodes: pd.DataFrame, edges: pd.DataFrame, path: Path) -> None:
    if nodes.empty:
        save_placeholder_plot(
            path,
            "Tumor-genome graph",
            "No graph nodes were created.",
        )
        return

    # Keep the previous force-directed visualization for small graphs where it is
    # fast. Large graphs use a linear-time genomic-position layout, avoiding the
    # O(N^2)-like practical cost of spring_layout on thousands of nodes.
    if nx is not None and len(nodes) <= 500:
        graph = nx.Graph()
        for row in nodes.to_dict(orient="records"):
            graph.add_node(row["NODE_ID"], call=row["COPY_NUMBER_CALL"])
        for row in edges.to_dict(orient="records"):
            graph.add_edge(
                row["SOURCE_NODE"],
                row["TARGET_NODE"],
                edge_type=row["EDGE_TYPE"],
            )

        figure, axis = plt.subplots(figsize=(14, 9))
        position = nx.spring_layout(graph, seed=17, k=1.2)
        nx.draw_networkx_nodes(graph, position, node_size=260, ax=axis)
        normal = [
            (u, v)
            for u, v, data in graph.edges(data=True)
            if data.get("edge_type") == "REFERENCE_ADJACENCY"
        ]
        tumor = [
            (u, v)
            for u, v, data in graph.edges(data=True)
            if data.get("edge_type") == "TUMOR_JUNCTION"
        ]
        nx.draw_networkx_edges(
            graph, position, edgelist=normal, width=1, alpha=0.4, ax=axis
        )
        nx.draw_networkx_edges(
            graph,
            position,
            edgelist=tumor,
            width=2.8,
            style="dashed",
            ax=axis,
        )
        labels = {
            node: node.replace("chr", "").replace(":", "\n", 1)
            for node in graph.nodes
        }
        nx.draw_networkx_labels(
            graph, position, labels=labels, font_size=6, ax=axis
        )
        axis.set_title("Segment-and-junction tumor-genome graph")
        axis.axis("off")
        figure.tight_layout()
        figure.savefig(path, dpi=180)
        plt.close(figure)
        return

    _fast_genomic_graph_plot(nodes, edges, path)


def _selected_required_file(
    value: object,
    label: str,
    expected_name: str,
) -> Path:
    text = str(value or "").strip()
    if not text:
        raise ValueError(
            f"{label} is required. Select it explicitly in the Step 09 GUI."
        )

    path = normalized_input_path(text)
    if path.name.lower() != expected_name.lower():
        raise ValueError(
            f"{label} must be the file named '{expected_name}'. "
            f"Selected: {path.name}"
        )
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"{label} was not found: {path}")
    return path


def _read_required_tsv(
    path: Path,
    label: str,
    required_columns: set[str],
) -> pd.DataFrame:
    try:
        table = pd.read_csv(path, sep="\t")
    except pd.errors.EmptyDataError:
        # A previous step can legitimately produce zero records. An exact,
        # explicitly selected expected output file is accepted as an empty table.
        return pd.DataFrame(columns=sorted(required_columns))

    missing = sorted(required_columns.difference(table.columns))
    if missing:
        raise ValueError(
            f"{label} is missing required column(s): {', '.join(missing)}\n"
            f"File: {path}"
        )
    return table


def load_explicit_step09_inputs(
    settings: dict,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Path, pd.DataFrame]:
    cfg = settings["integration_full"]

    breakpoint_path = _selected_required_file(
        cfg['consensus_sv_tsv'],
        "Step 07 consensus structural-variant table",
        "consensus_structural_variants.tsv",
    )
    cnv_path = _selected_required_file(
        cfg['copy_number_segments_tsv'],
        "Step 08 copy-number table",
        "copy_number_segments.tsv",
    )
    snv_path = _selected_required_file(
        cfg['molecular_variants_tsv'],
        "Step 13 molecularly validated SNV/indel table",
        "molecularly_validated_somatic_variants.tsv",
    )

    fasta_text = str(settings['integration_full']['reference_fasta'] or "").strip()
    if not fasta_text:
        raise ValueError(
            "Reference FASTA is required for Step 09. Select it explicitly."
        )
    fasta = normalized_input_path(fasta_text)
    if not fasta.exists() or not fasta.is_file():
        raise FileNotFoundError(f"Reference FASTA was not found: {fasta}")

    breakpoints = _read_required_tsv(
        breakpoint_path,
        "Step 06 consensus_structural_variants.tsv",
        {"CHROM1", "POS1", "CHROM2", "POS2"},
    )

    raw_cnv = _read_required_tsv(
        cnv_path,
        "Step 08 copy_number_segments.tsv",
        {"chromosome", "start", "end"},
    )
    if (
        not raw_cnv.empty
        and not {"CALL_BY_SIGNED_COPY_RATIO", "CALL"}.intersection(raw_cnv.columns)
    ):
        raise ValueError(
            "Step 07 copy_number_segments.tsv must contain "
            "CALL_BY_SIGNED_COPY_RATIO (current pipeline) or CALL (legacy)."
        )
    cnv = normalize_cnv(raw_cnv)

    snv = _read_required_tsv(
        snv_path,
        "Step 08 molecularly_validated_somatic_variants.tsv",
        {"CHROM", "POS"},
    )

    audit = pd.DataFrame(
        [
            {
                "ROLE": "STEP06_BREAKPOINTS",
                "FILE": str(breakpoint_path),
                "EXPECTED_BASENAME": "consensus_structural_variants.tsv",
                "RECORDS": len(breakpoints),
                "VALIDATION": "PASS",
            },
            {
                "ROLE": "STEP07_COPY_NUMBER",
                "FILE": str(cnv_path),
                "EXPECTED_BASENAME": "copy_number_segments.tsv",
                "RECORDS": len(cnv),
                "VALIDATION": "PASS",
            },
            {
                "ROLE": "STEP08_SMALL_VARIANTS",
                "FILE": str(snv_path),
                "EXPECTED_BASENAME": "molecularly_validated_somatic_variants.tsv",
                "RECORDS": len(snv),
                "VALIDATION": "PASS",
            },
            {
                "ROLE": "REFERENCE_FASTA",
                "FILE": str(fasta),
                "EXPECTED_BASENAME": fasta.name,
                "RECORDS": "",
                "VALIDATION": "PASS",
            },
        ]
    )

    return breakpoints, cnv, snv, fasta, audit


def integration_parameter_rows(settings: dict) -> list[dict[str, object]]:
    cfg = settings["integration_full"]
    return [
        {
            "PARAMETER": "consensus_sv_tsv",
            "VALUE": str(cfg['consensus_sv_tsv']),
            "EXPLANATION": (
                "Explicit Step 07 consensus_structural_variants.tsv containing "
                "structural-variant breakpoint pairs."
            ),
        },
        {
            "PARAMETER": "copy_number_segments_tsv",
            "VALUE": str(cfg['copy_number_segments_tsv']),
            "EXPLANATION": (
                "Explicit Step 08 copy_number_segments.tsv containing copy-number "
                "segments and signed-ratio gain/loss calls."
            ),
        },
        {
            "PARAMETER": "molecular_variants_tsv",
            "VALUE": str(cfg['molecular_variants_tsv']),
            "EXPLANATION": (
                "Explicit Step 13 molecularly_validated_somatic_variants.tsv containing "
                "PASS Mutect2 SNVs and small indels."
            ),
        },
        {
            "PARAMETER": "reference_fasta",
            "VALUE": str(settings['integration_full']['reference_fasta']),
            "EXPLANATION": "Reference FASTA used for chromosome lengths.",
        },
        {
            "PARAMETER": "nearby_variant_window_bp",
            "VALUE": int(cfg["nearby_variant_window_bp"]),
            "EXPLANATION": (
                "For each breakpoint side, count small variants within +/- this "
                "many bases. This is contextual proximity only."
            ),
        },
        {
            "PARAMETER": "graph_include_normal_adjacencies",
            "VALUE": bool(cfg["graph_include_normal_adjacencies"]),
            "EXPLANATION": (
                "Add reference adjacency edges between neighboring chromosome segments."
            ),
        },
        {
            "PARAMETER": "include_neutral_cnv_segments",
            "VALUE": bool(cfg["include_neutral_cnv_segments"]),
            "EXPLANATION": (
                "Keep NEUTRAL copy-number segments in the integrated event table."
            ),
        },
    ]



def validate_integration_settings(settings: dict) -> None:
    cfg = settings["integration_full"]
    if int(cfg["nearby_variant_window_bp"]) < 0:
        raise ValueError("Nearby-variant window cannot be negative.")


def backend(settings_path: Path, input_dir: Path, output_dir: Path, dry_run: bool) -> None:
    settings, _ = load_config(settings_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(output_dir / "15_INTEGRATE_TUMOR_GENOME_EVENTS.log")

    validate_integration_settings(settings)
    write_tsv(
        pd.DataFrame(integration_parameter_rows(settings)),
        output_dir / "integration_parameters_used.tsv",
    )

    breakpoints, cnv, snv, reference_fasta, input_audit = (
        load_explicit_step09_inputs(settings)
    )
    loh_path = normalized_input_path(settings['integration_full']['allele_specific_loh_tsv'])
    fraction_path = normalized_input_path(settings['integration_full']['ctdna_fraction_tsv'])
    loh = pd.read_csv(loh_path, sep="\t", low_memory=False) if loh_path.exists() and loh_path.is_file() else pd.DataFrame()
    fraction = pd.read_csv(fraction_path, sep="\t", low_memory=False) if fraction_path.exists() and fraction_path.is_file() else pd.DataFrame()
    write_tsv(input_audit, output_dir / "step15_input_files_used.tsv")
    window = int(settings["integration_full"]["nearby_variant_window_bp"])

    # Build lookup structures once. These are exact accelerators: they do not
    # alter event definitions, thresholds, coordinates, or output records.
    cnv_index = build_cnv_interval_index(cnv)
    snv_index = build_snv_position_index(snv)

    derivative_rows: list[dict] = []
    if not breakpoints.empty:
        for row in breakpoints.to_dict(orient="records"):
            sample_id = str(row.get("SAMPLE_ID", ""))
            chrom1, chrom2 = str(row["CHROM1"]), str(row["CHROM2"])
            pos1, pos2 = int(float(row["POS1"])), int(float(row["POS2"]))
            call1, ratio1 = cnv_at_indexed(
                cnv_index, sample_id, chrom1, pos1
            )
            call2, ratio2 = cnv_at_indexed(
                cnv_index, sample_id, chrom2, pos2
            )
            derivative_rows.append(
                {
                    **row,
                    "CNV_CALL_SIDE1": call1,
                    "CNV_SIGNED_COPY_RATIO_SIDE1": ratio1,
                    "CNV_CALL_SIDE2": call2,
                    "CNV_SIGNED_COPY_RATIO_SIDE2": ratio2,
                    "NEARBY_SMALL_VARIANTS_SIDE1": nearby_snv_count_indexed(
                        snv_index, sample_id, chrom1, pos1, window
                    ),
                    "NEARBY_SMALL_VARIANTS_SIDE2": nearby_snv_count_indexed(
                        snv_index, sample_id, chrom2, pos2, window
                    ),
                    "CANDIDATE_DERIVATIVE_DESCRIPTION": (
                        f"{chrom1}:{pos1} [{call1}] ↔ {chrom2}:{pos2} [{call2}]"
                    ),
                }
            )
    derivatives = pd.DataFrame(derivative_rows)

    event_tables: list[pd.DataFrame] = []
    if not breakpoints.empty:
        table = breakpoints.copy()
        table["EVENT_TYPE"] = "STRUCTURAL_VARIANT"
        event_tables.append(table)
    if not cnv.empty:
        table = cnv.copy()
        if not bool(settings["integration_full"]["include_neutral_cnv_segments"]):
            table = table.loc[
                table["CALL"].astype(str).str.upper() != "NEUTRAL"
            ].copy()
        if not table.empty:
            table["EVENT_TYPE"] = "COPY_NUMBER_SEGMENT"
            event_tables.append(table)
    if not snv.empty:
        table = snv.copy()
        table["EVENT_TYPE"] = "SMALL_VARIANT"
        event_tables.append(table)
    integrated = (
        pd.concat(event_tables, ignore_index=True, sort=False)
        if event_tables else pd.DataFrame()
    )

    lengths = reference_lengths(reference_fasta)
    nodes, edges = build_graph_tables(
        breakpoints,
        cnv,
        lengths,
        bool(settings["integration_full"]["graph_include_normal_adjacencies"]),
        cnv_index=cnv_index,
    )
    graph_path = output_dir / "tumor_genome_graph.gfa"
    write_gfa(nodes, edges, graph_path)

    write_tsv(integrated, output_dir / "integrated_tumor_genome_events.tsv")
    write_tsv(derivatives, output_dir / "candidate_derivative_chromosomes.tsv")
    write_tsv(nodes, output_dir / "tumor_genome_graph_nodes.tsv")
    write_tsv(edges, output_dir / "tumor_genome_graph_edges.tsv")

    plots: list[Path] = []
    event_plot = output_dir / "integrated_event_type_counts.png"
    if integrated.empty:
        save_placeholder_plot(event_plot, "Integrated event counts", "No event tables were available.")
    else:
        counts = integrated["EVENT_TYPE"].value_counts()
        save_bar_plot(
            counts.index.astype(str).tolist(),
            counts.astype(float).tolist(),
            event_plot,
            "Integrated tumor-genome event types",
            "Record count",
            rotate=35,
        )
    plots.append(event_plot)

    chromosome_plot = output_dir / "events_by_chromosome.png"
    chromosome_values: list[str] = []
    if not breakpoints.empty:
        chromosome_values.extend(breakpoints["CHROM1"].astype(str).tolist())
        chromosome_values.extend(breakpoints["CHROM2"].astype(str).tolist())
    if not cnv.empty:
        chromosome_values.extend(
            cnv.loc[cnv["CALL"].astype(str) != "NEUTRAL", "CHROM"].astype(str).tolist()
        )
    if not snv.empty:
        chromosome_values.extend(snv["CHROM"].astype(str).tolist())
    if not chromosome_values:
        save_placeholder_plot(chromosome_plot, "Events by chromosome", "No chromosome events available.")
    else:
        counts = pd.Series(chromosome_values).value_counts()
        save_bar_plot(
            counts.index.astype(str).tolist(),
            counts.astype(float).tolist(),
            chromosome_plot,
            "Integrated events by chromosome",
            "Event-side count",
            rotate=60,
        )
    plots.append(chromosome_plot)

    graph_png = output_dir / "tumor_genome_graph.png"
    graph_plot(nodes, edges, graph_png)
    plots.append(graph_png)

    write_step_status(
        output_dir,
        SPEC.title,
        "PASS",
        f"Integrated {len(integrated)} event record(s), created "
        f"{len(nodes)} graph node(s) and {len(edges)} edge(s).",
        0,
        plots,
    )
    print(output_dir / "integrated_tumor_genome_events.tsv")



STEP_GUI = {'environment': 'ctdna_core',
 'fields': [{'setting': 'integration_full.consensus_sv_tsv',
             'label': 'Step 07 consensus_structural_variants.tsv',
             'type': 'file',
             'required': True,
             'expected_name': 'consensus_structural_variants.tsv',
             'filetypes': [('Required Step 07 TSV', 'consensus_structural_variants.tsv'),
                           ('TSV', '*.tsv'),
                           ('All', '*.*')],
             'button_text': 'Browse consensus_structural_variants.tsv',
             'section': 'INTEGRATION INPUTS'},
            {'setting': 'integration_full.copy_number_segments_tsv',
             'label': 'Step 08 copy_number_segments.tsv',
             'type': 'file',
             'required': True,
             'expected_name': 'copy_number_segments.tsv',
             'filetypes': [('Required Step 08 TSV', 'copy_number_segments.tsv'), ('TSV', '*.tsv'), ('All', '*.*')],
             'button_text': 'Browse copy_number_segments.tsv',
             'section': 'INTEGRATION INPUTS'},
            {'setting': 'integration_full.allele_specific_loh_tsv',
             'label': 'Step 09 allele_specific_cnv_loh.tsv',
             'type': 'file',
             'required': True,
             'expected_name': 'allele_specific_cnv_loh.tsv',
             'filetypes': [('Required Step 09 TSV', 'allele_specific_cnv_loh.tsv'),
                           ('TSV', '*.tsv'),
                           ('All', '*.*')],
             'button_text': 'Browse allele_specific_cnv_loh.tsv',
             'section': 'INTEGRATION INPUTS'},
            {'setting': 'integration_full.molecular_variants_tsv',
             'label': 'Step 13 molecularly_validated_somatic_variants.tsv',
             'type': 'file',
             'required': True,
             'expected_name': 'molecularly_validated_somatic_variants.tsv',
             'filetypes': [('Required Step 13 TSV', 'molecularly_validated_somatic_variants.tsv'),
                           ('TSV', '*.tsv'),
                           ('All', '*.*')],
             'button_text': 'Browse molecularly_validated_somatic_variants.tsv',
             'section': 'INTEGRATION INPUTS'},
            {'setting': 'integration_full.ctdna_fraction_tsv',
             'label': 'Step 14 ctdna_fraction_estimate.tsv',
             'type': 'file',
             'required': True,
             'expected_name': 'ctdna_fraction_estimate.tsv',
             'filetypes': [('Required Step 14 TSV', 'ctdna_fraction_estimate.tsv'),
                           ('TSV', '*.tsv'),
                           ('All', '*.*')],
             'button_text': 'Browse ctdna_fraction_estimate.tsv',
             'section': 'INTEGRATION INPUTS'},
            {'setting': 'integration_full.reference_fasta',
             'label': 'Reference FASTA',
             'type': 'file',
             'required': True,
             'allowed_suffixes': ['.fa', '.fasta', '.fna'],
             'filetypes': [('FASTA', '*.fa *.fasta *.fna'), ('All', '*.*')],
             'button_text': 'Browse reference FASTA',
             'section': 'INTEGRATION INPUTS'},
            {'setting': 'integration_full.nearby_variant_window_bp',
             'label': 'Nearby small-variant window around breakpoint (bp)',
             'type': 'int',
             'required': True,
             'section': 'GRAPH / INTEGRATION OPTIONS'},
            {'setting': 'integration_full.graph_include_normal_adjacencies',
             'label': 'Include normal/reference adjacency edges in graph',
             'type': 'bool',
             'section': 'GRAPH / INTEGRATION OPTIONS'},
            {'setting': 'integration_full.include_neutral_cnv_segments',
             'label': 'Include NEUTRAL CNV segments in integrated event table',
             'type': 'bool',
             'section': 'GRAPH / INTEGRATION OPTIONS'}],
 'explanation': 'Integrates consensus structural variants, copy-number segments, allele-specific LOH, validated '
                'small variants and ctDNA fraction into a tumor-genome event model and graph. This is the central '
                'integration step of the expanded pipeline.'}

if __name__ == "__main__":
    launch_step(SPEC, backend)
