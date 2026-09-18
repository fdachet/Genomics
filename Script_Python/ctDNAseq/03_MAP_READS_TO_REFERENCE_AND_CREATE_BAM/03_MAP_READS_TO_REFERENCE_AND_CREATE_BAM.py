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
    parser.add_argument('--references-fasta', dest='__cfg__references__fasta', type=str, default='', help='Override references.fasta for this execution.')
    parser.add_argument('--references-bwa-mem2-index-prefix', dest='__cfg__references__bwa_mem2_index_prefix', type=str, default='', help='Optional BWA-MEM2 index prefix. You may also provide the path to any BWA-MEM2 index component; its suffix is removed automatically.')
    parser.add_argument('--create-bwa-mem2-index-only', action='store_true', default=False, help='Create/rebuild the selected BWA-MEM2 index as a standalone action, then exit without mapping reads.')
    parser.add_argument('--verify-bwa-mem2-index-only', action='store_true', default=False, help='Verify the selected BWA-MEM2 index as a standalone action, report every required component, then exit without mapping reads.')
    parser.add_argument('--alignment-build-umi-consensus', dest='__cfg__alignment__build_umi_consensus', type=_parse_cli_bool, default=True, help='Override alignment.build_umi_consensus for this execution.')
    parser.add_argument('--alignment-umi-group-strategy', dest='__cfg__alignment__umi_group_strategy', type=str, default='adjacency', help='Override alignment.umi_group_strategy for this execution.')
    parser.add_argument('--alignment-umi-edit-distance', dest='__cfg__alignment__umi_edit_distance', type=int, default=1, help='Override alignment.umi_edit_distance for this execution.')
    parser.add_argument('--alignment-minimum-reads-per-family', dest='__cfg__alignment__minimum_reads_per_family', type=int, default=2, help='Override alignment.minimum_reads_per_family for this execution.')
    parser.add_argument('--alignment-consensus-minimum-base-quality', dest='__cfg__alignment__consensus_minimum_base_quality', type=int, default=20, help='Override alignment.consensus_minimum_base_quality for this execution.')
    parser.add_argument('--alignment-auto-create-fasta-indexes', '--alignment-auto-create-reference-indexes', dest='__cfg__alignment__auto_create_fasta_indexes', type=_parse_cli_bool, default=True, help='Auto-create only FASTA support files (.fai and .dict). BWA-MEM2 indexes are NEVER created automatically; use the separate index-creation action.')
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

                if typ in {'file','folder','bwa_index_prefix'}:
                    ttk.Button(
                        row,
                        text=field.get('button_text','Browse'),
                        command=lambda f=field,v=var:self._browse(f,v),
                    ).pack(side="left",padx=3)

                    if typ=='bwa_index_prefix':
                        self.bwa_verify_button=ttk.Button(
                            row,
                            text=field.get('verify_button_text','Verify BWA-MEM2 index'),
                            command=self._verify_bwa_index_clicked,
                        )
                        self.bwa_verify_button.pack(side="left",padx=3)

                        self.bwa_index_button=ttk.Button(
                            row,
                            text=field.get('create_button_text','Create BWA-MEM2 index'),
                            command=self._create_bwa_index_clicked,
                        )
                        self.bwa_index_button.pack(side="left",padx=3)

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
        if selected:
            if field.get('type')=='bwa_index_prefix':
                var.set(str(strip_bwa_mem2_index_component_suffix(Path(selected))))
            else:
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

    def _build_wsl_command(self,settings,input_dir,output_dir,dry_run,extra_backend_args=None):
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
        backend=[python_exe,_windows_to_wsl(Path(__file__).resolve()),'--backend']
        if extra_backend_args:
            backend += list(extra_backend_args)
        backend += ['--settings-file',_windows_to_wsl(self.settings_path),'--input-dir',_windows_to_wsl(input_dir),'--output-dir',_windows_to_wsl(output_dir)]
        if dry_run: backend.append('--dry-run')
        if env:
            if not exe: raise RuntimeError('Micromamba environment is selected but micromamba was not detected. Enter the WSL micromamba executable in the GUI.')
            prefix=[exe]
            if root: prefix += ['-r',root]
            prefix += ['run','-n',env]
            backend=prefix+backend
        shell=' '.join(shlex.quote(str(x)) for x in backend)
        return _wsl_base_args(distro)+['bash','-lc',shell]

    def _save_index_action_settings(self):
        """
        Save the current reference/index/environment controls for standalone
        BWA-MEM2 create/verify actions without requiring a valid FASTQ input folder.
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

            if key=='references.fasta':
                if not value:
                    raise ValueError('Reference FASTA is required for BWA-MEM2 index actions.')
                p=Path(value)
                if not p.exists() or not p.is_file():
                    raise FileNotFoundError(f'Reference FASTA not found: {p}')
                _validate_expected_file(p,field)

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

        output_text=self.vars['__output_dir__'].get().strip()
        output_dir=Path(output_text) if output_text else (self.step_dir/'output')
        output_dir.mkdir(parents=True,exist_ok=True)

        with self.settings_path.open('w',encoding='utf-8') as h:
            json.dump(settings,h,indent=2)
            h.write('\n')
        self.settings=settings
        return settings,output_dir

    def _verify_bwa_index_clicked(self):
        """Verify BWA-MEM2 index files only. This never creates an index or maps reads."""
        try:
            settings,output_dir=self._save_index_action_settings()
            dummy_input=self.step_dir/'input'
            cmd=self._build_wsl_command(
                settings,
                dummy_input,
                output_dir,
                False,
                extra_backend_args=['--verify-bwa-mem2-index-only'],
            )
        except Exception as exc:
            self.messagebox.showerror('BWA-MEM2 verification error',str(exc))
            return

        reference=str(_setting_get(settings,'references.fasta')).strip()
        prefix=str(_setting_get(settings,'references.bwa_mem2_index_prefix')).strip() or reference
        self.status.set(
            'Verifying BWA-MEM2 index only (nothing will be created and mapping will NOT run).\n'
            f'Reference: {reference}\nIndex prefix: {prefix}'
        )
        self._set_running_state(True)
        self.progress_text.set('Progress: Verifying BWA-MEM2 index...')

        worker=threading.Thread(
            target=self._run_verify_index_worker,
            args=(cmd,),
            daemon=True,
        )
        worker.start()

    def _run_verify_index_worker(self,cmd):
        try:
            completed=subprocess.run(cmd,capture_output=True,text=True)
            stdout=completed.stdout or ''
            stderr=completed.stderr or ''
            combined=stdout + (('\n'+stderr) if stderr else '')
            self.root.after(
                0,
                lambda rc=completed.returncode,text=combined:self._finish_verify_index_run(rc,text),
            )
        except Exception as exc:
            message=str(exc)
            self.root.after(0,lambda msg=message:self._finish_verify_index_exception(msg))

    def _finish_verify_index_run(self,returncode,text):
        self._set_running_state(False)
        display=text[-9000:] if text else f'Finished with code {returncode}'
        self.status.set(display)
        if returncode==0:
            self.progress_value.set(100.0)
            self.progress_text.set('Progress: 100% — BWA-MEM2 index verification PASSED')
            self.messagebox.showinfo(
                'BWA-MEM2 index verification — PASS',
                (text[-7000:] if text else 'BWA-MEM2 index verification passed.')
                + '\n\nNo index was created and no read mapping was started.'
            )
        else:
            self.progress_value.set(0.0)
            self.progress_text.set('Progress: BWA-MEM2 index verification FAILED')
            self.messagebox.showerror(
                'BWA-MEM2 index verification — FAIL',
                text[-9000:] if text else f'Verification exited with code {returncode}.',
            )

    def _finish_verify_index_exception(self,message):
        self._set_running_state(False)
        self.progress_value.set(0.0)
        self.progress_text.set('Progress: BWA-MEM2 index verification FAILED — execution exception')
        self.status.set(message)
        self.messagebox.showerror('BWA-MEM2 verification error',message)

    def _create_bwa_index_clicked(self):
        """Run BWA-MEM2 indexing only. This never launches read mapping."""
        try:
            settings,output_dir=self._save_index_action_settings()
            dummy_input=self.step_dir/'input'
            cmd=self._build_wsl_command(
                settings,
                dummy_input,
                output_dir,
                False,
                extra_backend_args=['--create-bwa-mem2-index-only'],
            )
        except Exception as exc:
            self.messagebox.showerror('BWA-MEM2 indexing error',str(exc))
            return

        reference=str(_setting_get(settings,'references.fasta')).strip()
        prefix=str(_setting_get(settings,'references.bwa_mem2_index_prefix')).strip() or reference
        self.status.set(
            'Creating BWA-MEM2 index only (mapping will NOT run).\n'
            f'Reference: {reference}\nIndex prefix: {prefix}'
        )
        self._set_running_state(True)
        self.progress_text.set('Progress: Creating BWA-MEM2 index...')

        worker=threading.Thread(
            target=self._run_index_worker,
            args=(cmd,),
            daemon=True,
        )
        worker.start()

    def _run_index_worker(self,cmd):
        try:
            completed=subprocess.run(cmd,capture_output=True,text=True)
            stdout=completed.stdout or ''
            stderr=completed.stderr or ''
            combined=stdout + (('\n'+stderr) if stderr else '')
            self.root.after(
                0,
                lambda rc=completed.returncode,text=combined:self._finish_index_run(rc,text),
            )
        except Exception as exc:
            message=str(exc)
            self.root.after(0,lambda msg=message:self._finish_index_exception(msg))

    def _finish_index_run(self,returncode,text):
        self._set_running_state(False)
        display=text[-6000:] if text else f'Finished with code {returncode}'
        self.status.set(display)
        if returncode==0:
            self.progress_value.set(100.0)
            self.progress_text.set('Progress: 100% — BWA-MEM2 index created successfully')
            self.messagebox.showinfo(
                'BWA-MEM2 index',
                'BWA-MEM2 index creation completed successfully.\n\n'
                'No read mapping was started. You can now click RUN STEP separately.'
            )
        else:
            self.progress_value.set(0.0)
            self.progress_text.set(f'Progress: BWA-MEM2 indexing FAILED — exit code {returncode}')
            self.messagebox.showerror(
                'BWA-MEM2 indexing failed',
                text[-7000:] if text else f'Process exited with code {returncode}.',
            )

    def _finish_index_exception(self,message):
        self._set_running_state(False)
        self.progress_value.set(0.0)
        self.progress_text.set('Progress: BWA-MEM2 indexing FAILED — execution exception')
        self.status.set(message)
        self.messagebox.showerror('BWA-MEM2 indexing error',message)

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
            if hasattr(self,'bwa_verify_button'):
                self.bwa_verify_button.configure(state="disabled")
            if hasattr(self,'bwa_index_button'):
                self.bwa_index_button.configure(state="disabled")

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
            if hasattr(self,'bwa_verify_button'):
                self.bwa_verify_button.configure(state="normal")
            if hasattr(self,'bwa_index_button'):
                self.bwa_index_button.configure(state="normal")

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

            if args.create_bwa_mem2_index_only:
                create_bwa_mem2_index_action(settings, output_dir, args.dry_run)
                return

            if args.verify_bwa_mem2_index_only:
                verify_bwa_mem2_index_action(settings, output_dir)
                return

            backend_function(effective_settings, input_dir, output_dir, args.dry_run)
        except Exception:
            traceback.print_exc()
            raise SystemExit(1)
    else:
        StandaloneStepGUI(spec, backend_function, globals().get("STEP_GUI", {})).run()




import sys
from pathlib import Path


import gzip
import re
from pathlib import Path

import pandas as pd

try:
    import pysam
except ModuleNotFoundError:
    pysam = None



SPEC = StepSpecification(
    number=3,
    title="03_MAP_READS_TO_REFERENCE_AND_CREATE_BAM",
    description=(
        "Browse and scan mapping-ready FASTQ files, select the exact reference "
        "FASTA, use an existing BWA-MEM2 reference index, map ctDNA reads, and "
        "automatically use UMI metadata preserved by Step 02 for consensus."
    ),
    default_input_dir="input",
    default_output_dir="output",
)

UMI_PATTERN = re.compile(
    r"^(?P<name>.+?)"
    r"(?:(?:__UMI_(?P<mode>SINGLE|DUPLEX)__)|(?:__UMI__))"
    r"(?P<umi>[ACGTNacgtn-]+)$",
    re.IGNORECASE,
)


def add_rx_tag(input_bam: Path, output_bam: Path) -> int:
    if pysam is None:
        raise ModuleNotFoundError("pysam is required in the WSL1 backend.")
    tagged = 0
    with pysam.AlignmentFile(input_bam, "rb") as source:
        with pysam.AlignmentFile(output_bam, "wb", header=source.header) as target:
            for read in source:
                match = UMI_PATTERN.match(read.query_name)
                if match:
                    read.query_name = match.group("name")
                    read.set_tag("RX", match.group("umi").upper(), value_type="Z")
                    tagged += 1
                target.write(read)
    return tagged


def parse_flagstat(path: Path) -> dict[str, float]:
    result: dict[str, float] = {}
    if not path.exists():
        return result
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    patterns = {
        "TOTAL_READS": r"^(\d+) \+ \d+ in total",
        "MAPPED_READS": r"^(\d+) \+ \d+ mapped",
        "PROPERLY_PAIRED_READS": r"^(\d+) \+ \d+ properly paired",
        "DUPLICATE_READS": r"^(\d+) \+ \d+ duplicates",
    }
    for key, pattern in patterns.items():
        for line in lines:
            match = re.search(pattern, line)
            if match:
                result[key] = float(match.group(1))
                break
    total = result.get("TOTAL_READS", 0)
    result["MAPPING_PERCENT"] = (
        100.0 * result.get("MAPPED_READS", 0) / total if total else float("nan")
    )
    result["PROPERLY_PAIRED_PERCENT"] = (
        100.0 * result.get("PROPERLY_PAIRED_READS", 0) / total
        if total else float("nan")
    )
    return result



def sequence_dictionary_path(reference: Path) -> Path:
    """Return the conventional sequence-dictionary path for a FASTA."""
    lower = reference.name.lower()
    for suffix in (".fasta.gz", ".fa.gz", ".fna.gz", ".fasta", ".fa", ".fna"):
        if lower.endswith(suffix):
            return reference.with_name(reference.name[: -len(suffix)] + ".dict")
    return Path(str(reference) + ".dict")


BWA_MEM2_INDEX_COMPONENT_SUFFIXES = (
    ".bwt.2bit.64",
    ".bwt.8bit.32",
    ".0123",
    ".amb",
    ".ann",
    ".pac",
)


def strip_bwa_mem2_index_component_suffix(path: Path) -> Path:
    """
    Convert a selected BWA-MEM2 index component into the common index prefix.

    Examples:
      GRCh38.fa.bwt.2bit.64 -> GRCh38.fa
      my_index.0123         -> my_index
      my_index              -> my_index
    """
    text = str(path)
    lower = text.lower()
    for suffix in BWA_MEM2_INDEX_COMPONENT_SUFFIXES:
        if lower.endswith(suffix.lower()):
            return Path(text[: -len(suffix)])
    return path


def resolve_bwa_mem2_index_prefix(settings: dict, reference: Path) -> Path:
    """
    Resolve the prefix used by `bwa-mem2 mem`.

    A custom setting may point either to the prefix itself or to any one of the
    BWA-MEM2 sidecar files selected with the GUI Browse button. When blank, the
    FASTA path is the prefix, preserving the conventional/default behavior.
    """
    configured = str(settings["references"].get("bwa_mem2_index_prefix", "")).strip()
    if not configured:
        return reference
    selected = normalized_input_path(configured)
    return strip_bwa_mem2_index_component_suffix(selected)


def bwa_mem2_index_paths(prefix_path: Path) -> dict[str, Path]:
    """Known BWA-MEM2 sidecar files created for a common index prefix."""
    prefix = str(prefix_path)
    return {
        "0123": Path(prefix + ".0123"),
        "amb": Path(prefix + ".amb"),
        "ann": Path(prefix + ".ann"),
        "pac": Path(prefix + ".pac"),
        "bwt_2bit_64": Path(prefix + ".bwt.2bit.64"),
        "bwt_8bit_32": Path(prefix + ".bwt.8bit.32"),
    }


def reference_index_status(reference: Path, bwa_index_prefix: Path | None = None) -> dict[str, object]:
    """Report FASTA, selected BWA-MEM2 index, samtools faidx, and sequence-dict status."""
    prefix = bwa_index_prefix if bwa_index_prefix is not None else reference
    bwa = bwa_mem2_index_paths(prefix)

    file_status: dict[str, dict[str, object]] = {}
    for key, path in bwa.items():
        exists = path.exists() and path.is_file()
        size = path.stat().st_size if exists else 0
        file_status[key] = {
            "PATH": path,
            "EXISTS": bool(exists),
            "SIZE_BYTES": int(size),
            "NONEMPTY": bool(exists and size > 0),
        }

    core_keys = ("0123", "amb", "ann", "pac")
    core_ok = all(bool(file_status[key]["NONEMPTY"]) for key in core_keys)

    # BWA-MEM2 versions/builds have used 2-bit and 8-bit BWT representations.
    # A usable index needs at least one non-empty supported BWT representation,
    # in addition to all four core sidecar files above.
    bwt_keys = ("bwt_2bit_64", "bwt_8bit_32")
    bwt_ok = any(bool(file_status[key]["NONEMPTY"]) for key in bwt_keys)

    fai = Path(str(reference) + ".fai")
    dictionary = sequence_dictionary_path(reference)
    return {
        "FASTA_EXISTS": reference.exists(),
        "BWA_MEM2_INDEX_PREFIX": prefix,
        "BWA_MEM2_INDEX_OK": bool(core_ok and bwt_ok),
        "BWA_CORE_FILES_OK": bool(core_ok),
        "BWA_BWT_FILE_OK": bool(bwt_ok),
        "BWA_FILE_STATUS": file_status,
        "FAI_OK": fai.exists() and fai.stat().st_size > 0,
        "DICT_OK": dictionary.exists() and dictionary.stat().st_size > 0,
        "FAI": fai,
        "DICT": dictionary,
        "BWA_FILES": bwa,
    }


def infer_reference_build_from_fai(reference: Path) -> str:
    """Infer GRCh38 vs GRCh37 from chr1/1 length when a .fai is available."""
    fai = Path(str(reference) + ".fai")
    if not fai.exists():
        return "UNKNOWN"
    try:
        with fai.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                fields = line.rstrip("\n").split("\t")
                if len(fields) < 2:
                    continue
                if fields[0] in {"chr1", "1"}:
                    length = int(fields[1])
                    if length == 248_956_422:
                        return "GRCh38"
                    if length == 249_250_621:
                        return "GRCh37"
                    return f"UNKNOWN_chr1_length_{length}"
    except (OSError, ValueError):
        return "UNKNOWN"
    return "UNKNOWN"


def ensure_reference_indexes(
    settings: dict,
    reference: Path,
    output_dir: Path,
    dry_run: bool,
) -> dict[str, object]:
    """
    Validate the reference resources needed for mapping.

    IMPORTANT: this function NEVER creates a BWA-MEM2 index. BWA-MEM2 index
    creation is a separate GUI/CLI action. During mapping, the selected/default
    BWA-MEM2 index must already exist and be complete.

    Automatic creation applies only to FASTA support files: the random-access
    index (.fai) and sequence dictionary (.dict). BWA-MEM2 indexes are never
    created from the normal mapping path.
    """
    bwa_index_prefix = resolve_bwa_mem2_index_prefix(settings, reference)
    status = reference_index_status(reference, bwa_index_prefix)
    auto_create_fasta = bool(settings['alignment']['auto_create_fasta_indexes'])

    log_file = output_dir / 'reference_indexing.log'
    samtools = str(settings['tools']['samtools'])

    if not bool(status['FASTA_EXISTS']) and not dry_run:
        raise FileNotFoundError(f'Reference FASTA not found: {reference}')

    # BWA-MEM2 indexing is deliberately NOT performed here.
    if not bool(status['BWA_MEM2_INDEX_OK']) and not dry_run:
        raise FileNotFoundError(
            'BWA-MEM2 index is missing or incomplete for the selected prefix.\n'
            f'Reference FASTA: {reference}\n'
            f'BWA-MEM2 prefix: {bwa_index_prefix}\n\n'
            "Use the separate 'Create BWA-MEM2 index' button first, or browse "
            'to an existing BWA-MEM2 index. Mapping has not been started.'
        )

    # .fai and .dict remain tied to the FASTA and may still be auto-created.
    status = reference_index_status(reference, bwa_index_prefix)
    if not bool(status['FAI_OK']):
        if auto_create_fasta or dry_run:
            run_command([samtools, 'faidx', str(reference)], log_file, dry_run=dry_run)

    status = reference_index_status(reference, bwa_index_prefix)
    if not bool(status['DICT_OK']):
        if auto_create_fasta or dry_run:
            run_command(
                [samtools, 'dict', '-o', str(status['DICT']), str(reference)],
                log_file,
                dry_run=dry_run,
            )

    final_status = reference_index_status(reference, bwa_index_prefix)
    if not dry_run:
        missing=[]
        if not bool(final_status['BWA_MEM2_INDEX_OK']):
            missing.append(f'BWA-MEM2 index for prefix {bwa_index_prefix}')
        if not bool(final_status['FAI_OK']):
            missing.append('samtools FASTA index (.fai)')
        if not bool(final_status['DICT_OK']):
            missing.append('sequence dictionary (.dict)')
        if missing:
            raise FileNotFoundError(
                'Required reference files are missing: ' + ', '.join(missing)
            )

    final_status['BWA_MEM2_INDEX_PREFIX']=bwa_index_prefix
    return final_status


def _human_file_size(size_bytes: int) -> str:
    """Compact human-readable byte count for index verification reports."""
    size = float(max(0, int(size_bytes)))
    units = ("B", "KB", "MB", "GB", "TB")
    unit = units[0]
    for candidate in units:
        unit = candidate
        if size < 1024.0 or candidate == units[-1]:
            break
        size /= 1024.0
    return f"{size:.2f} {unit}" if unit != "B" else f"{int(size)} B"


def verify_bwa_mem2_index_action(
    settings: dict,
    output_dir: Path,
) -> dict[str, object]:
    """
    Standalone, read-only BWA-MEM2 index verification action.

    Nothing is created, repaired, overwritten, or mapped. The action verifies
    that the four core BWA-MEM2 sidecars (.0123, .amb, .ann, .pac) are present
    and non-empty and that at least one supported BWT representation
    (.bwt.2bit.64 or .bwt.8bit.32) is present and non-empty.
    """
    reference = normalized_input_path(settings['references']['fasta'])
    prefix = resolve_bwa_mem2_index_prefix(settings, reference)
    status = reference_index_status(reference, prefix)

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / 'bwa_mem2_index_verification.tsv'

    labels = {
        '0123': '.0123',
        'amb': '.amb',
        'ann': '.ann',
        'pac': '.pac',
        'bwt_2bit_64': '.bwt.2bit.64',
        'bwt_8bit_32': '.bwt.8bit.32',
    }
    required_kind = {
        '0123': 'REQUIRED',
        'amb': 'REQUIRED',
        'ann': 'REQUIRED',
        'pac': 'REQUIRED',
        'bwt_2bit_64': 'BWT_ALTERNATIVE',
        'bwt_8bit_32': 'BWT_ALTERNATIVE',
    }

    rows=[]
    for key in ('0123','amb','ann','pac','bwt_2bit_64','bwt_8bit_32'):
        info=status['BWA_FILE_STATUS'][key]
        rows.append({
            'COMPONENT': labels[key],
            'REQUIREMENT': required_kind[key],
            'PATH': str(info['PATH']),
            'EXISTS': bool(info['EXISTS']),
            'NONEMPTY': bool(info['NONEMPTY']),
            'SIZE_BYTES': int(info['SIZE_BYTES']),
            'STATUS': 'PASS' if bool(info['NONEMPTY']) else 'MISSING_OR_EMPTY',
        })
    write_tsv(pd.DataFrame(rows), report_path)

    lines=[
        'BWA-MEM2 INDEX VERIFICATION',
        f'Prefix: {prefix}',
        '',
        'Required core components:',
    ]
    for key in ('0123','amb','ann','pac'):
        info=status['BWA_FILE_STATUS'][key]
        mark='PASS' if bool(info['NONEMPTY']) else 'FAIL'
        lines.append(
            f'  [{mark}] {info["PATH"]}  ({_human_file_size(int(info["SIZE_BYTES"]))})'
        )

    lines += ['', 'BWT representation (at least one is required):']
    for key in ('bwt_2bit_64','bwt_8bit_32'):
        info=status['BWA_FILE_STATUS'][key]
        mark='PASS' if bool(info['NONEMPTY']) else 'NOT PRESENT'
        lines.append(
            f'  [{mark}] {info["PATH"]}  ({_human_file_size(int(info["SIZE_BYTES"]))})'
        )

    lines += [
        '',
        f'Core files: {"PASS" if status["BWA_CORE_FILES_OK"] else "FAIL"}',
        f'BWT file:   {"PASS" if status["BWA_BWT_FILE_OK"] else "FAIL"}',
        f'OVERALL:    {"PASS" if status["BWA_MEM2_INDEX_OK"] else "FAIL"}',
        f'Report: {report_path}',
    ]
    message='\n'.join(lines)
    print(message)

    if not bool(status['BWA_MEM2_INDEX_OK']):
        missing_core=[]
        for key in ('0123','amb','ann','pac'):
            if not bool(status['BWA_FILE_STATUS'][key]['NONEMPTY']):
                missing_core.append(str(status['BWA_FILE_STATUS'][key]['PATH']))
        problems=[]
        if missing_core:
            problems.append('Missing/empty required core files: ' + ', '.join(missing_core))
        if not bool(status['BWA_BWT_FILE_OK']):
            problems.append(
                'No non-empty BWT representation found. Expected at least one of: '
                + str(status['BWA_FILE_STATUS']['bwt_2bit_64']['PATH']) + ', '
                + str(status['BWA_FILE_STATUS']['bwt_8bit_32']['PATH'])
            )
        raise FileNotFoundError(
            'BWA-MEM2 index verification FAILED for prefix: '
            + str(prefix) + '\n' + '\n'.join(problems)
            + f'\nDetailed report: {report_path}'
        )

    LOGGER.info('BWA-MEM2 index verification passed. Prefix: %s',prefix)
    return status


def create_bwa_mem2_index_action(
    settings: dict,
    output_dir: Path,
    dry_run: bool = False,
) -> dict[str, object]:
    """
    Standalone BWA-MEM2 indexing action.

    This function only creates/rebuilds the BWA-MEM2 index and validates its
    component files. It does not discover FASTQs, map reads, create BAMs, or run
    any other Step 03 analysis.
    """
    require_tools(settings,['bwa_mem2'],dry_run)

    reference=normalized_input_path(settings['references']['fasta'])
    if not dry_run and (not reference.exists() or not reference.is_file()):
        raise FileNotFoundError(f'Reference FASTA not found: {reference}')

    prefix=resolve_bwa_mem2_index_prefix(settings,reference)
    if not dry_run:
        prefix.parent.mkdir(parents=True,exist_ok=True)

    log_file=output_dir/'bwa_mem2_index_creation.log'
    bwa=str(settings['tools']['bwa_mem2'])

    run_command(
        [bwa,'index','-p',str(prefix),str(reference)],
        log_file,
        dry_run=dry_run,
    )

    status=reference_index_status(reference,prefix)
    if not dry_run and not bool(status['BWA_MEM2_INDEX_OK']):
        raise RuntimeError(
            'bwa-mem2 index finished, but the expected index components were not '
            f'found for prefix: {prefix}. See {log_file}.'
        )

    LOGGER.info('Standalone BWA-MEM2 index action completed. Prefix: %s',prefix)
    return status


def _open_fastq_header_text(path: Path):
    if path.name.lower().endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def inspect_fastq_umi_headers(
    path: Path,
    maximum_records: int = 100,
) -> dict[str, int]:
    """
    Inspect molecular-barcode metadata in mapping-ready FASTQ headers.

    Step 02 already removed the artificial UMI bases from the sequence. The
    barcode identity remains in the header because Step 03 needs it to group
    molecular families after alignment.
    """
    result = {
        "RECORDS": 0,
        "READ_NAME_UMI_SINGLE": 0,
        "READ_NAME_UMI_DUPLEX": 0,
        "READ_NAME_UMI_LEGACY": 0,
        "RX_COMMENT": 0,
        "AGILENT_MBC_COMMENT": 0,
    }

    try:
        with _open_fastq_header_text(path) as handle:
            for _ in range(maximum_records):
                header = handle.readline()
                if not header:
                    break
                sequence = handle.readline()
                plus = handle.readline()
                quality = handle.readline()

                if not quality or not header.startswith("@"):
                    break

                result["RECORDS"] += 1
                first_token = header.split(maxsplit=1)[0].upper()

                if "__UMI_SINGLE__" in first_token:
                    result["READ_NAME_UMI_SINGLE"] += 1
                elif "__UMI_DUPLEX__" in first_token:
                    result["READ_NAME_UMI_DUPLEX"] += 1
                elif "__UMI__" in first_token:
                    result["READ_NAME_UMI_LEGACY"] += 1

                if "RX:Z:" in header:
                    result["RX_COMMENT"] += 1

                if (
                    "RX:Z:" in header
                    and ("ZA:Z:" in header or "ZB:Z:" in header)
                ):
                    result["AGILENT_MBC_COMMENT"] += 1

    except (OSError, EOFError, UnicodeError):
        pass

    return result


def classify_umi_evidence(paths: list[Path]) -> dict[str, str]:
    """
    Determine UMI processing automatically.

    There is intentionally no Step 03 UMI mode selection. Step 02 is the step
    where the user defines none/single/duplex, and that decision is preserved
    in the FASTQ metadata.
    """
    totals = {
        "RECORDS": 0,
        "READ_NAME_UMI_SINGLE": 0,
        "READ_NAME_UMI_DUPLEX": 0,
        "READ_NAME_UMI_LEGACY": 0,
        "RX_COMMENT": 0,
        "AGILENT_MBC_COMMENT": 0,
    }

    for path in paths:
        if not path:
            continue
        counts = inspect_fastq_umi_headers(path)
        for key in totals:
            totals[key] += counts[key]

    if totals["AGILENT_MBC_COMMENT"] > 0:
        return {
            "MOLECULAR_CHEMISTRY": "AGILENT_SURESELECT_XT_HS2_DUAL_MBC",
            "UMI_EVIDENCE": "AGILENT_RX_QX_ZA_ZB_FASTQ_COMMENT",
            "RX_SOURCE": "FASTQ_COMMENT",
            "AUTO_UMI_MODE": "none",
            "UMI_MODE_SOURCE": "AGILENT_AGENT_METADATA",
        }

    if totals["READ_NAME_UMI_DUPLEX"] > 0:
        return {
            "MOLECULAR_CHEMISTRY": "GENERIC",
            "UMI_EVIDENCE": "READ_NAME___UMI_DUPLEX___SUFFIX",
            "RX_SOURCE": "READ_NAME_SUFFIX",
            "AUTO_UMI_MODE": "duplex",
            "UMI_MODE_SOURCE": "STEP02_FASTQ_HEADER",
        }

    if totals["READ_NAME_UMI_SINGLE"] > 0:
        return {
            "MOLECULAR_CHEMISTRY": "GENERIC",
            "UMI_EVIDENCE": "READ_NAME___UMI_SINGLE___SUFFIX",
            "RX_SOURCE": "READ_NAME_SUFFIX",
            "AUTO_UMI_MODE": "single",
            "UMI_MODE_SOURCE": "STEP02_FASTQ_HEADER",
        }

    if totals["READ_NAME_UMI_LEGACY"] > 0:
        return {
            "MOLECULAR_CHEMISTRY": "GENERIC",
            "UMI_EVIDENCE": "LEGACY_READ_NAME___UMI___SUFFIX",
            "RX_SOURCE": "READ_NAME_SUFFIX",
            "AUTO_UMI_MODE": "single",
            "UMI_MODE_SOURCE": "LEGACY_HEADER_ASSUMED_NON_DUPLEX",
        }

    if totals["RX_COMMENT"] > 0:
        return {
            "MOLECULAR_CHEMISTRY": "GENERIC_RX_COMMENT",
            "UMI_EVIDENCE": "RX_FASTQ_COMMENT",
            "RX_SOURCE": "FASTQ_COMMENT",
            "AUTO_UMI_MODE": "single",
            "UMI_MODE_SOURCE": "RX_TAG_NON_DUPLEX_DEFAULT",
        }

    return {
        "MOLECULAR_CHEMISTRY": "GENERIC",
        "UMI_EVIDENCE": "NONE_DETECTED",
        "RX_SOURCE": "NONE",
        "AUTO_UMI_MODE": "none",
        "UMI_MODE_SOURCE": "NO_UMI_METADATA",
    }


def discover_mapping_fastqs(input_dir: Path, settings: dict) -> pd.DataFrame:
    """Scan mapping-ready FASTQs directly; no input manifest is used."""
    recursive = bool(settings['alignment']['recursive_fastq_scan'])
    samples, files = detect_fastq_samples(
        input_dir,
        recursive=recursive,
        minimum_file_size_bytes=1,
    )
    if files.empty:
        raise FileNotFoundError(
            "No FASTQ files were found in the selected input folder. Recognized "
            "extensions: .fastq, .fq, .fastq.gz, .fq.gz"
        )

    # Step 02 can optionally retain an internal UMI-extracted FASTQ before
    # final trimming. It is not a mapping-ready final input and must not be
    # treated as a second biological sample when both files are present.
    def is_internal_umi_intermediate(record: dict[str, object]) -> bool:
        values = [
            str(record.get("R1", "")),
            str(record.get("R2", "")),
            str(record.get("SINGLE_END_FASTQ", "")),
        ]
        return any(".umi_extracted." in value.lower() for value in values)

    if not samples.empty:
        keep_mask = [
            not is_internal_umi_intermediate(record)
            for record in samples.to_dict(orient="records")
        ]
        samples = samples.loc[keep_mask].reset_index(drop=True)

    unresolved = samples[samples["PAIRING_STATUS"].astype(str) == "UNPAIRED_MATE"]
    if not unresolved.empty:
        preview = []
        for row in unresolved.head(20).to_dict(orient="records"):
            preview.append(
                f"{row['SAMPLE_ID']}: R1={row.get('R1') or 'NOT FOUND'}; "
                f"R2={row.get('R2') or 'NOT FOUND'}"
            )
        raise ValueError(
            "Unresolved paired-end FASTQ files were detected. Correct the input "
            "selection/names or verify the files are true mates.\n" + "\n".join(preview)
        )

    rows: list[dict[str, object]] = []
    for row in samples.to_dict(orient="records"):
        if row["PAIRING_STATUS"] not in {"PAIRED", "SINGLE_END"}:
            continue
        fastqs: list[Path] = []
        if row["PAIRING_STATUS"] == "PAIRED":
            fastqs = [normalized_input_path(row["R1"]), normalized_input_path(row["R2"])]
        else:
            fastqs = [normalized_input_path(row["SINGLE_END_FASTQ"])]

        evidence = classify_umi_evidence(fastqs)
        effective_mode = evidence["AUTO_UMI_MODE"]

        if effective_mode == "duplex" and row["PAIRING_STATUS"] != "PAIRED":
            raise ValueError(
                f"{row['SAMPLE_ID']}: Step 02 FASTQ metadata identifies a "
                "duplex UMI library, but duplex consensus requires paired-end FASTQs."
            )

        sample_id = str(row["SAMPLE_ID"])
        sample_id = re.sub(
            r"(?:[._-](?:processed|trimmed|cleaned|cut))$",
            "",
            sample_id,
            flags=re.IGNORECASE,
        )

        rows.append(
            {
                "SAMPLE_ID": sample_id,
                "SEQUENCING_LAYOUT": row["SEQUENCING_LAYOUT"],
                "R1": row.get("R1", ""),
                "R2": row.get("R2", ""),
                "SINGLE_END_FASTQ": row.get("SINGLE_END_FASTQ", ""),
                "PAIRING_METHOD": row.get("PAIRING_METHOD", ""),
                "HEADER_MATCH_PERCENT": row.get("HEADER_MATCH_PERCENT", ""),
                "UMI_MODE": effective_mode,
                **evidence,
            }
        )
    return pd.DataFrame(rows)

def build_umi_consensus(
    settings: dict,
    sample_id: str,
    umi_mode: str,
    rx_source: str,
    aligned_bam: Path,
    final_bam: Path,
    sample_dir: Path,
    log_file: Path,
    dry_run: bool,
) -> None:
    if pysam is None and not dry_run:
        raise ModuleNotFoundError("pysam is required in the WSL1 backend.")

    samtools = str(settings["tools"]["samtools"])
    bwa = str(settings["tools"]["bwa_mem2"])
    fgbio = str(settings["tools"]["fgbio"])
    reference = normalized_input_path(settings["references"]["fasta"])
    alignment = settings["alignment"]
    n_threads = threads(settings)

    rx_bam = sample_dir / "01.rx_tagged.bam"
    grouped_bam = sample_dir / "02.umi_grouped.bam"
    family_hist = sample_dir / "02.umi_family_sizes.tsv"
    group_metrics = sample_dir / "02.umi_grouping_metrics.tsv"
    consensus_unmapped = sample_dir / "03.consensus.unmapped.bam"
    consensus_metrics = sample_dir / "03.consensus_metrics.tsv"
    consensus_fastq = sample_dir / "04.consensus.interleaved.fastq.gz"
    mapped_qname = sample_dir / "05.consensus.mapped.queryname.bam"
    unmapped_qname = sample_dir / "05.consensus.unmapped.queryname.bam"
    zipped = sample_dir / "06.consensus.zipped.queryname.bam"
    filtered = sample_dir / "07.consensus.filtered.queryname.bam"

    group_input_bam = rx_bam
    if rx_source == "READ_NAME_SUFFIX":
        if not dry_run:
            if add_rx_tag(aligned_bam, rx_bam) == 0:
                raise ValueError(
                    f"{sample_id}: no __UMI__ suffix was found in aligned read names."
                )
    elif rx_source == "FASTQ_COMMENT":
        # BWA-MEM2 -C has already propagated SAM-style RX tags from FASTQ comments.
        group_input_bam = aligned_bam
    else:
        raise ValueError(
            f"{sample_id}: UMI consensus was requested but no usable RX source is available."
        )

    group_command = [
        fgbio, "GroupReadsByUmi",
        "--input", str(group_input_bam),
        "--output", str(grouped_bam),
        "--strategy", ("paired" if umi_mode == "duplex" else str(alignment["umi_group_strategy"])),
        "--edits", str(alignment["umi_edit_distance"]),
        "--min-map-q", "20",
        "--threads", str(n_threads),
        "--family-size-histogram", str(family_hist),
        "--grouping-metrics", str(group_metrics),
    ]
    run_command(group_command, log_file, dry_run=dry_run)

    if umi_mode == "duplex":
        consensus_command = [
            fgbio, "CallDuplexConsensusReads",
            "--input", str(grouped_bam),
            "--output", str(consensus_unmapped),
            "--stats", str(consensus_metrics),
            "--min-reads", str(alignment["minimum_reads_per_family"]), "1", "1",
            "--threads", str(n_threads),
        ]
    else:
        consensus_command = [
            fgbio, "CallMolecularConsensusReads",
            "--input", str(grouped_bam),
            "--output", str(consensus_unmapped),
            "--stats", str(consensus_metrics),
            "--min-reads", str(alignment["minimum_reads_per_family"]),
            "--threads", str(n_threads),
        ]
    run_command(consensus_command, log_file, dry_run=dry_run)

    command = (
        f"{quote(samtools)} fastq -n {quote(consensus_unmapped)} | "
        f"gzip -c > {quote(consensus_fastq)} && "
        f"{quote(bwa)} mem -p -Y -t {n_threads} "
        f"{quote(reference)} {quote(consensus_fastq)} | "
        f"{quote(samtools)} sort -n -@ {n_threads} -o {quote(mapped_qname)} - && "
        f"{quote(samtools)} sort -n -@ {n_threads} "
        f"-o {quote(unmapped_qname)} {quote(consensus_unmapped)} && "
        f"{quote(fgbio)} ZipperBams "
        f"--input {quote(mapped_qname)} --unmapped {quote(unmapped_qname)} "
        f"--ref {quote(reference)} --output {quote(zipped)} "
        f"--tags-to-reverse Consensus && "
        f"{quote(fgbio)} FilterConsensusReads "
        f"--input {quote(zipped)} --output {quote(filtered)} "
        f"--ref {quote(reference)} "
        f"--min-reads {alignment['minimum_reads_per_family']} "
        f"--max-read-error-rate {alignment['consensus_maximum_read_error_rate']} "
        f"--max-base-error-rate {alignment['consensus_maximum_base_error_rate']} "
        f"--min-base-quality {alignment['consensus_minimum_base_quality']} "
        f"--max-no-calls {alignment['consensus_maximum_no_call_fraction']} && "
        f"{quote(samtools)} sort -@ {n_threads} -o {quote(final_bam)} "
        f"{quote(filtered)} && "
        f"{quote(samtools)} index -@ {n_threads} {quote(final_bam)}"
    )
    run_command(command, log_file, dry_run=dry_run, shell=True)



def _bam_index_candidates(bam_path: Path) -> list[Path]:
    """
    Return common samtools BAM index naming variants.

    `samtools index sample.bam` normally produces sample.bam.bai, but the
    alternative sample.bai form can also occur. CSI variants are included so
    stale temporary indexes cannot remain behind.
    """
    candidates = [
        Path(str(bam_path) + ".bai"),
        bam_path.with_suffix(".bai"),
        Path(str(bam_path) + ".csi"),
        bam_path.with_suffix(".csi"),
    ]

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _find_existing_bam_index(bam_path: Path) -> Path | None:
    """Return the first non-empty BAM index found for `bam_path`."""
    for candidate in _bam_index_candidates(bam_path):
        if (
            candidate.exists()
            and candidate.is_file()
            and candidate.stat().st_size > 0
        ):
            return candidate
    return None


def validate_final_analysis_ready_bam_before_cleanup(
    final_bam: Path,
    flagstat: Path,
    samtools: str,
    log_file: Path,
    dry_run: bool,
) -> dict[str, str]:
    """
    Confirm that the final Step 03 product is safe before deleting intermediates.

    Cleanup is allowed only after:
      1. final analysis-ready BAM exists and is non-empty;
      2. its BAM index exists and is non-empty;
      3. flagstat exists and is non-empty;
      4. `samtools quickcheck -v` succeeds.

    If any check fails, an exception is raised BEFORE cleanup, preserving the
    temporary BAMs for troubleshooting.
    """
    if dry_run:
        return {
            "FINAL_BAM_VALIDATION": "DRY_RUN_NOT_VALIDATED",
            "FINAL_BAM_INDEX": str(final_bam) + ".bai",
        }

    if not final_bam.exists() or not final_bam.is_file():
        raise FileNotFoundError(
            f"Final analysis-ready BAM was not created: {final_bam}"
        )
    if final_bam.stat().st_size <= 0:
        raise ValueError(
            f"Final analysis-ready BAM is empty: {final_bam}"
        )

    final_index = _find_existing_bam_index(final_bam)
    if final_index is None:
        raise FileNotFoundError(
            "Final analysis-ready BAM index is missing or empty. "
            "Intermediate BAMs will NOT be removed.\n"
            f"BAM: {final_bam}"
        )

    if not flagstat.exists() or not flagstat.is_file():
        raise FileNotFoundError(
            "Final flagstat output is missing. Intermediate BAMs will NOT be "
            f"removed: {flagstat}"
        )
    if flagstat.stat().st_size <= 0:
        raise ValueError(
            "Final flagstat output is empty. Intermediate BAMs will NOT be "
            f"removed: {flagstat}"
        )

    run_command(
        [samtools, "quickcheck", "-v", str(final_bam)],
        log_file,
        dry_run=False,
    )

    return {
        "FINAL_BAM_VALIDATION": "PASS_QUICKCHECK_INDEX_FLAGSTAT",
        "FINAL_BAM_INDEX": str(final_index),
    }


def cleanup_step03_intermediate_bams(
    sample_id: str,
    sample_dir: Path,
    aligned_bam: Path,
    dry_run: bool,
) -> list[dict[str, str]]:
    """
    Remove only the four known Step 03 temporary BAMs and their indexes.

    Target BAMs:
      - <sample>.aligned.sorted.bam
      - markdup.01.name_sorted.bam
      - markdup.02.fixmate.bam
      - markdup.03.coordinate.bam

    The final analysis-ready BAM and its index are never targeted.
    """
    temporary_bams = [
        aligned_bam,
        sample_dir / "markdup.01.name_sorted.bam",
        sample_dir / "markdup.02.fixmate.bam",
        sample_dir / "markdup.03.coordinate.bam",
    ]

    rows: list[dict[str, str]] = []

    for bam_path in temporary_bams:
        related_paths = [bam_path, *_bam_index_candidates(bam_path)]

        for path in related_paths:
            existed_before = path.exists()

            if dry_run:
                status = (
                    "DRY_RUN_WOULD_REMOVE"
                    if existed_before
                    else "DRY_RUN_NOT_PRESENT"
                )
            elif existed_before:
                try:
                    path.unlink()
                    status = "REMOVED"
                except OSError as exc:
                    raise OSError(
                        f"Could not remove Step 03 temporary file: {path}"
                    ) from exc
            else:
                status = "NOT_PRESENT"

            rows.append(
                {
                    "SAMPLE_ID": sample_id,
                    "TEMPORARY_FILE": str(path),
                    "FILE_TYPE": (
                        "TEMPORARY_BAM"
                        if path == bam_path
                        else "TEMPORARY_BAM_INDEX"
                    ),
                    "STATUS": status,
                }
            )

    return rows



def backend(settings_path: Path, input_dir: Path, output_dir: Path, dry_run: bool) -> None:
    settings, _ = load_config(settings_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(output_dir / "03_MAP_READS_TO_REFERENCE_AND_CREATE_BAM.log")
    require_tools(settings, ["bwa_mem2", "samtools"], dry_run)

    reference = normalized_input_path(settings["references"]["fasta"])
    if not dry_run and not reference.exists():
        raise FileNotFoundError(f"Reference FASTA not found: {reference}")

    # The exact FASTA selected by the user is the mapping reference.
    # There is deliberately no separate GRCh37/GRCh38 selector.
    index_status = ensure_reference_indexes(
        settings,
        reference,
        output_dir,
        dry_run,
    )
    bwa_index_prefix = Path(index_status["BWA_MEM2_INDEX_PREFIX"])

    mapping_inputs = discover_mapping_fastqs(input_dir, settings)
    if mapping_inputs.empty:
        raise FileNotFoundError("No mapping-ready FASTQ libraries were detected.")

    if (
        bool(settings['alignment']['build_umi_consensus'])
        and any(
            str(value) in {"single", "duplex"}
            for value in mapping_inputs["UMI_MODE"].tolist()
        )
    ):
        require_tools(settings, ["fgbio"], dry_run)

    bwa = str(settings["tools"]["bwa_mem2"])
    samtools = str(settings["tools"]["samtools"])
    n_threads = threads(settings)
    memory = str(settings["alignment"]["sort_memory_per_thread"])
    platform = str(settings["alignment"]["platform"])
    output_rows: list[dict] = []
    metric_rows: list[dict] = []
    cleanup_rows: list[dict[str, str]] = []

    # Record what the scan found for reproducibility. This is an OUTPUT report,
    # not an input manifest and no later step is required to use it.
    write_tsv(mapping_inputs, output_dir / "detected_mapping_fastqs.tsv")

    for row in mapping_inputs.to_dict(orient="records"):
        sample_id = str(row["SAMPLE_ID"])
        sample_dir = output_dir / sample_id
        sample_dir.mkdir(parents=True, exist_ok=True)
        aligned_bam = sample_dir / f"{sample_id}.aligned.sorted.bam"
        final_bam = sample_dir / f"{sample_id}.analysis_ready.bam"
        flagstat = sample_dir / f"{sample_id}.flagstat.txt"
        log_file = output_dir / "logs" / f"{sample_id}.log"
        read_group = (
            f"@RG\\tID:{sample_id}\\tSM:{sample_id}\\tLB:{sample_id}"
            f"\\tPL:{platform}"
        )

        molecular_chemistry = str(row.get("MOLECULAR_CHEMISTRY", "GENERIC"))
        rx_source = str(row.get("RX_SOURCE", "NONE"))
        is_agilent_xths2 = molecular_chemistry == "AGILENT_SURESELECT_XT_HS2_DUAL_MBC"

        # BWA-MEM2 -C propagates SAM-style fields from FASTQ comments, which is
        # needed for AGeNT RX/QX/ZA/ZB and other pre-extracted RX-comment UMIs.
        bwa_comment_option = "-C " if rx_source == "FASTQ_COMMENT" else ""

        if row["SEQUENCING_LAYOUT"] == "PAIRED_END":
            r1 = normalized_input_path(row["R1"])
            r2 = normalized_input_path(row["R2"])
            command = (
                f"{quote(bwa)} mem -Y {bwa_comment_option}-t {n_threads} "
                f"-R {quote(read_group)} {quote(bwa_index_prefix)} {quote(r1)} {quote(r2)} | "
                f"{quote(samtools)} sort -@ {n_threads} -m {quote(memory)} "
                f"-o {quote(aligned_bam)} - && "
                f"{quote(samtools)} index -@ {n_threads} {quote(aligned_bam)}"
            )
        else:
            single = normalized_input_path(row["SINGLE_END_FASTQ"])
            command = (
                f"{quote(bwa)} mem -Y {bwa_comment_option}-t {n_threads} "
                f"-R {quote(read_group)} {quote(bwa_index_prefix)} {quote(single)} | "
                f"{quote(samtools)} sort -@ {n_threads} -m {quote(memory)} "
                f"-o {quote(aligned_bam)} - && "
                f"{quote(samtools)} index -@ {n_threads} {quote(aligned_bam)}"
            )
        run_command(command, log_file, dry_run=dry_run, shell=True)

        if is_agilent_xths2:
            command = (
                f"{quote(samtools)} view -b -o {quote(final_bam)} {quote(aligned_bam)} && "
                f"{quote(samtools)} index -@ {n_threads} {quote(final_bam)}"
            )
            run_command(command, log_file, dry_run=dry_run, shell=True)
            processing = "AGILENT_MBC_TAGGED_REQUIRES_CREAK"
        else:
            use_consensus = (
                str(row["UMI_MODE"]) in {"single", "duplex"}
                and bool(settings["alignment"]["build_umi_consensus"])
                and row["SEQUENCING_LAYOUT"] == "PAIRED_END"
            )
            if use_consensus:
                build_umi_consensus(
                    settings,
                    sample_id,
                    str(row["UMI_MODE"]),
                    rx_source,
                    aligned_bam,
                    final_bam,
                    sample_dir,
                    log_file,
                    dry_run,
                )
                processing = "UMI_CONSENSUS"
            else:
                markdup_stats = sample_dir / f"{sample_id}.markdup_metrics.txt"
                if row["SEQUENCING_LAYOUT"] == "PAIRED_END":
                    name_sorted = sample_dir / "markdup.01.name_sorted.bam"
                    fixmate_bam = sample_dir / "markdup.02.fixmate.bam"
                    coordinate_bam = sample_dir / "markdup.03.coordinate.bam"
                    command = (
                        f"{quote(samtools)} sort -n -@ {n_threads} -o {quote(name_sorted)} {quote(aligned_bam)} && "
                        f"{quote(samtools)} fixmate -m {quote(name_sorted)} {quote(fixmate_bam)} && "
                        f"{quote(samtools)} sort -@ {n_threads} -m {quote(memory)} -o {quote(coordinate_bam)} {quote(fixmate_bam)} && "
                        f"{quote(samtools)} markdup -s -f {quote(markdup_stats)} -@ {n_threads} {quote(coordinate_bam)} {quote(final_bam)} && "
                        f"{quote(samtools)} index -@ {n_threads} {quote(final_bam)}"
                    )
                else:
                    command = (
                        f"{quote(samtools)} markdup -s -f {quote(markdup_stats)} -@ {n_threads} "
                        f"{quote(aligned_bam)} {quote(final_bam)} && "
                        f"{quote(samtools)} index -@ {n_threads} {quote(final_bam)}"
                    )
                run_command(command, log_file, dry_run=dry_run, shell=True)
                processing = (
                    "DUPLICATE_MARKING"
                    if str(row["UMI_MODE"]) == "none"
                    else "UMI_TAGGED_NO_CONSENSUS"
                )

        command = (
            f"{quote(samtools)} flagstat -@ {n_threads} {quote(final_bam)} > {quote(flagstat)}"
        )
        run_command(command, log_file, dry_run=dry_run, shell=True)

        # Cleanup is permitted only after the final BAM, its index, and flagstat
        # have all passed validation. If validation fails, intermediates remain.
        final_validation = validate_final_analysis_ready_bam_before_cleanup(
            final_bam,
            flagstat,
            samtools,
            log_file,
            dry_run,
        )

        sample_cleanup_rows = cleanup_step03_intermediate_bams(
            sample_id,
            sample_dir,
            aligned_bam,
            dry_run,
        )
        cleanup_rows.extend(sample_cleanup_rows)

        metric_rows.append(
            {
                "SAMPLE_ID": sample_id,
                "MOLECULAR_PROCESSING": processing,
                **(parse_flagstat(flagstat) if not dry_run else {}),
            }
        )
        output_rows.append(
            {
                **row,
                "REFERENCE_FASTA": str(reference),
                "BWA_MEM2_INDEX_PREFIX": str(bwa_index_prefix),
                "ALIGNED_BAM": str(aligned_bam),
                "ALIGNED_BAM_STATUS": (
                    "TEMPORARY_REMOVED_AFTER_SUCCESS"
                    if not dry_run
                    else "DRY_RUN_WOULD_REMOVE_AFTER_SUCCESS"
                ),
                "FINAL_BAM": str(final_bam),
                "BAM_INDEX": final_validation["FINAL_BAM_INDEX"],
                "FINAL_BAM_VALIDATION": final_validation[
                    "FINAL_BAM_VALIDATION"
                ],
                "MOLECULAR_PROCESSING": processing,
                "FLAGSTAT": str(flagstat),
            }
        )

    results = pd.DataFrame(output_rows)
    metrics = pd.DataFrame(metric_rows)
    cleanup_report = pd.DataFrame(cleanup_rows)

    write_tsv(results, output_dir / "mapping_results.tsv")
    write_tsv(metrics, output_dir / "mapping_qc_metrics.tsv")
    write_tsv(
        cleanup_report,
        output_dir / "intermediate_bam_cleanup.tsv",
    )

    mapping_plot = output_dir / "mapping_percent.png"
    paired_plot = output_dir / "properly_paired_percent.png"
    if metrics.empty or "MAPPING_PERCENT" not in metrics.columns:
        save_placeholder_plot(mapping_plot, "Mapping percentage", "No flagstat metrics available.")
        save_placeholder_plot(paired_plot, "Properly paired percentage", "No flagstat metrics available.")
    else:
        labels = metrics["SAMPLE_ID"].astype(str).tolist()
        save_bar_plot(
            labels,
            pd.to_numeric(metrics["MAPPING_PERCENT"], errors="coerce").fillna(0).tolist(),
            mapping_plot,
            "Reads mapped to the selected reference assembly",
            "Mapped reads (%)",
            rotate=60,
        )
        save_bar_plot(
            labels,
            pd.to_numeric(metrics["PROPERLY_PAIRED_PERCENT"], errors="coerce").fillna(0).tolist(),
            paired_plot,
            "Properly paired reads",
            "Properly paired (%)",
            rotate=60,
        )

    write_step_status(
        output_dir,
        SPEC.title,
        "PASS",
        (
            f"Mapped {len(results)} directly scanned FASTQ library record(s) to "
            f"{reference.name} using BWA-MEM2 index prefix {bwa_index_prefix}; "
            f"validated final analysis-ready BAMs and removed "
            f"known temporary BAM/intermediate-index files after successful "
            f"sample completion; no input manifest was used."
        ),
        len(results),
        [mapping_plot, paired_plot],
    )
    print(output_dir / "mapping_results.tsv")



STEP_GUI = {'environment': 'ctdna_core',
 'fields': [{'setting': '__input_dir__',
             'label': 'Processed FASTQ folder from Step 02',
             'type': 'folder',
             'required': True,
             'scan_globs': ['*.fastq', '*.fastq.gz', '*.fq', '*.fq.gz'],
             'section': 'INPUTS AND REFERENCES'},
            {'setting': 'references.fasta',
             'label': 'Reference FASTA',
             'type': 'file',
             'required': True,
             'allowed_suffixes': ['.fa', '.fasta', '.fna'],
             'filetypes': [('FASTA', '*.fa *.fasta *.fna'), ('All files', '*.*')],
             'button_text': 'Browse reference FASTA',
             'section': 'INPUTS AND REFERENCES',
             'help': 'Must match the genome build used by all VCF/GTF/CNV resources downstream.'},
            {'setting': 'references.bwa_mem2_index_prefix',
             'label': 'BWA-MEM2 index prefix / existing index file',
             'type': 'bwa_index_prefix',
             'required': False,
             'filetypes': [('BWA-MEM2 index files', '*.0123 *.amb *.ann *.pac *.bwt.2bit.64 *.bwt.8bit.32'),
                           ('All files', '*.*')],
             'button_text': 'Browse BWA index',
             'verify_button_text': 'Verify BWA-MEM2 index',
             'create_button_text': 'Create BWA-MEM2 index',
             'section': 'INPUTS AND REFERENCES',
             'help': 'Browse to any existing BWA-MEM2 index component; the common prefix is recovered automatically. '
                     'Use Verify BWA-MEM2 index to check every required component and reject missing/empty files without creating anything. '
                     'To build/rebuild an index, use the separate Create BWA-MEM2 index button. Neither action starts mapping. '
                     'Leave blank to use the reference FASTA path as the conventional prefix.'},
            {'setting': 'alignment.build_umi_consensus',
             'label': 'Build UMI consensus when UMI metadata is present',
             'type': 'bool',
             'section': 'UMI CONSENSUS'},
            {'setting': 'alignment.umi_group_strategy',
             'label': 'UMI group strategy',
             'type': 'choice',
             'required': True,
             'section': 'UMI CONSENSUS',
             'choices': ['adjacency', 'edit', 'identity'],
             'choice_values': {'adjacency': 'adjacency', 'edit': 'edit', 'identity': 'identity'},
             'help': 'Simplex UMI grouping strategy for fgbio. Duplex UMI libraries automatically use the paired '
                     'strategy regardless of this selection.'},
            {'setting': 'alignment.umi_edit_distance',
             'label': 'UMI edit distance',
             'type': 'int',
             'required': True,
             'section': 'UMI CONSENSUS'},
            {'setting': 'alignment.minimum_reads_per_family',
             'label': 'Minimum reads per UMI family',
             'type': 'int',
             'required': True,
             'section': 'UMI CONSENSUS'},
            {'setting': 'alignment.consensus_minimum_base_quality',
             'label': 'Consensus minimum base quality',
             'type': 'int',
             'required': True,
             'section': 'UMI CONSENSUS'},
            {'setting': 'alignment.auto_create_fasta_indexes',
             'label': 'Auto-create FASTA support files (.fai/.dict)',
             'type': 'bool',
             'section': 'INPUTS AND REFERENCES',
             'help': 'Creates only the FASTA .fai index and sequence .dict when missing. It NEVER creates a BWA-MEM2 index. '
                     'BWA-MEM2 index creation is available only through the separate Create BWA-MEM2 index action.'},
            {'setting': 'alignment.consensus_maximum_read_error_rate',
             'label': 'Consensus maximum read error rate',
             'type': 'float',
             'required': True,
             'section': 'ADVANCED UMI CONSENSUS',
             'help': 'fgbio consensus read-level error-rate filter.'},
            {'setting': 'alignment.consensus_maximum_base_error_rate',
             'label': 'Consensus maximum base error rate',
             'type': 'float',
             'required': True,
             'section': 'ADVANCED UMI CONSENSUS',
             'help': 'fgbio consensus base-level error-rate filter.'},
            {'setting': 'alignment.consensus_maximum_no_call_fraction',
             'label': 'Consensus maximum no-call fraction',
             'type': 'float',
             'required': True,
             'section': 'ADVANCED UMI CONSENSUS',
             'help': 'Maximum fraction of no-call bases allowed in a consensus read.'},
            {'setting': 'alignment.sort_memory_per_thread',
             'label': 'samtools sort memory per thread',
             'type': 'text',
             'required': True,
             'section': 'ADVANCED ALIGNMENT',
             'help': 'Example: 1G. This is passed to samtools sort per thread.'}],
 'explanation': 'Maps Step 02 reads with BWA-MEM2, creates coordinate-sorted/indexed BAMs, and can build UMI '
                'consensus reads when Step 02 preserved UMI metadata. The reference FASTA must match all '
                'downstream resources. Browse to an existing BWA-MEM2 index, verify its complete component set with the separate '
                'verification button, or create/rebuild one with the separate index action button. Mapping never creates a BWA-MEM2 index automatically; missing FASTA .fai/.dict '
                'indexes can still be created automatically.'}

if __name__ == "__main__":
    launch_step(SPEC, backend)
