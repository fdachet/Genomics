#!/usr/bin/env python3

from __future__ import annotations

import csv
import glob
import hashlib
import io
import json
import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

RESERVED_WORDS = {"WAS", "WASG", "WASJ"}
WIRE_TOKENS = {"|", "-"}
RESERVED = RESERVED_WORDS | WIRE_TOKENS
PROGRAM_TYPES = ("Linux executable", "Python 3", "Rscript", "Bash", "Inline Bash")
DATA_INPUT_MODES = ("Per-sample files", "Shared single resource")
MODE_PER_SAMPLE = DATA_INPUT_MODES[0]
MODE_SHARED = DATA_INPUT_MODES[1]
WASJ_FILE_MATCH_MODES = ("Exact path", "Filename only")
SAFE_RUNTIME_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
MEMORY_VALUE_RE = re.compile(r"^(\d+(?:\.\d+)?|\.\d+)\s*(B|KB|MB|GB|TB|PB)$",re.IGNORECASE)
TIME_PART_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(milliseconds?|msecs?|ms|seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|w)",
    re.IGNORECASE,
)
_LITERAL_LBRACE = "\ue000NEXTDASH_LITERAL_LBRACE\ue001"
_LITERAL_RBRACE = "\ue000NEXTDASH_LITERAL_RBRACE\ue001"

KNOWN_DATA_SUFFIXES = (
    ".fastq.gz", ".fq.gz", ".fasta.gz", ".fa.gz", ".fna.gz", ".vcf.gz",
    ".bed.gz", ".gff.gz", ".gtf.gz", ".idat.gz", ".txt.gz", ".csv.gz",
    ".tsv.gz", ".fastq", ".fq", ".fasta", ".fa", ".fna", ".bam",
    ".sam", ".cram", ".vcf", ".bcf", ".bed", ".gff", ".gtf",
    ".idat", ".txt", ".csv", ".tsv", ".bw", ".bigwig", ".h5",
    ".h5ad", ".loom", ".mtx", ".rds",
)


class NetDashError(RuntimeError):
    pass


@dataclass
class ValidationIssue:
    level: str
    message: str
    cells: tuple[tuple[int, int], ...] = ()

    def __str__(self) -> str:
        loc = ""
        if self.cells:
            loc = " [" + ", ".join(f"R{r+1}C{c+1}" for r, c in self.cells) + "]"
        return f"{self.level}: {self.message}{loc}"


@dataclass
class ProgramDef:
    program_id: str
    name: str = ""
    program_path: str = ""
    program_type: str = "Linux executable"
    arguments_template: str = "-i {input} -o {output}"
    cpus: int = 1
    memory: str = "1 GB"
    time: str = "24h"
    max_forks: int = 0
    publish_subdirectory: str = ""
    additional_inputs: str = ""
    additional_outputs: str = ""
    shared_resources: str = ""

    def normalized_name(self) -> str:
        return self.name.strip() or f"Program_{self.program_id}"

    def normalized_publish_dir(self) -> str:
        return self.publish_subdirectory.strip() or f"{sanitize_filename_component(self.normalized_name())}_out"


@dataclass
class DataDef:
    label: str
    description: str = ""
    input_pattern: str = ""
    sample_regex: str = ""
    output_template: str = ""
    input_mode: str = MODE_PER_SAMPLE


    input_extensions: str = ""
    group_files_by_sample: bool = False
    expected_files_per_sample: int = 2


    publish_directory: str = ""
    local_scan_pattern: str = ""

    def normalized_output_template(self) -> str:
        return self.output_template.strip() or f"{{lineage}}.{sanitize_filename_component(self.label)}"

    def normalized_input_mode(self) -> str:
        return self.input_mode if self.input_mode in DATA_INPUT_MODES else MODE_PER_SAMPLE


@dataclass
class WASJConfig:
    barrier_id: str
    sample_table_path: str = ""
    file_column: str = ""
    sample_id_column: str = ""
    file_match_mode: str = WASJ_FILE_MATCH_MODES[0]
    join_key: str = ""
    difference_keys: list[str] = field(default_factory=list)

    difference_values: dict[str, dict[str, str]] = field(default_factory=dict)


    @property
    def role_values(self) -> dict[str, dict[str, str]]:
        return self.difference_values

    @role_values.setter
    def role_values(self,value: dict[str, dict[str, str]]) -> None:
        self.difference_values=value

    def normalized_difference_keys(self) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in self.difference_keys:
            value = str(value).strip()
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result


@dataclass
class ProgramOccurrence:
    occurrence_id: str
    program_id: str
    row: int
    col: int
    input_labels: list[str]
    output_label: str
    barrier: str = "NONE"
    barrier_id: str = ""
    barrier_cells: list[tuple[int, int]] = field(default_factory=list)
    wait_labels: list[str] = field(default_factory=list)
    primary_label: str = ""

    @property
    def arity(self) -> int:
        return len(self.input_labels)

    def dependency_labels(self) -> list[str]:
        values = list(self.input_labels)
        for value in self.wait_labels:
            if value not in values:
                values.append(value)
        return values


@dataclass
class ParsedGrid:
    grid: list[list[str]]
    data_labels: set[str]
    program_ids: set[str]
    occurrences: list[ProgramOccurrence]
    producer_by_data: dict[str, ProgramOccurrence]
    root_data: set[str]
    was_blocks: list[list[tuple[int, int]]]
    wasg_cells: list[tuple[int, int]]
    wasj_blocks: list[list[tuple[int, int]]]
    wire_sources: dict[tuple[int, int], str] = field(default_factory=dict)
    note_cells: list[tuple[int, int]] = field(default_factory=list)

    def wasj_occurrences(self) -> list[ProgramOccurrence]:
        return [x for x in self.occurrences if x.barrier == "WASJ"]


@dataclass
class WASJPreview:
    barrier_id: str
    input_labels: list[str]
    join_key: str
    difference_keys: list[str]
    role_values: dict[str, dict[str, str]]
    join_values: list[str]
    rows: list[dict[str, str]]
    issues: list[ValidationIssue]






def normalize_token(token: str) -> str:
    token = (token or "").strip()
    if token.upper() in RESERVED_WORDS:
        return token.upper()
    return token


def normalize_grid(grid: list[list[str]]) -> list[list[str]]:
    if not grid:
        return [[""]]
    width = max(1, max(len(row) for row in grid))
    result = []
    for row in grid:
        clean = [normalize_token(x) for x in row]
        clean += [""] * (width - len(clean))
        result.append(clean)
    return result


def trim_grid(grid: list[list[str]]) -> list[list[str]]:
    g = normalize_grid(grid)
    while len(g) > 2 and all(not x for x in g[-1]):
        g.pop()
    last = 0
    for row in g:
        for idx, token in enumerate(row):
            if token:
                last = max(last, idx)
    return [row[: max(4, last + 1)] for row in g]


def program_token_id(token: str) -> str:
    token = normalize_token(token)
    match = re.fullmatch(r"([0-9]+)(?:_([A-Za-z][A-Za-z0-9_]*))?", token)
    return match.group(1) if match else token


def program_display_token(program_id: str, definition: ProgramDef | None = None) -> str:
    if definition is None:
        return str(program_id)
    label = sanitize_identifier(definition.normalized_name())
    return f"{program_id}_{label}"


def parse_shared_resources(value: str) -> list[tuple[str, str]]:
    resources = []
    seen = set()
    for line in str(value or "").replace("\r", "").replace("\n", ";").split(";"):
        line = line.strip()
        if not line:
            continue
        if "=" not in line:
            raise NetDashError("Shared resources must use NAME=DATA_WORD.")
        key, word = [part.strip() for part in line.split("=", 1)]
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key):
            raise NetDashError(f"Invalid shared-resource alias {key!r}.")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", word):
            raise NetDashError(f"Invalid shared data word {word!r}.")
        if key.casefold() in seen or re.fullmatch(r"(?i)(input\d*|inputs|output\d*|sample|cpus|group|group_manifest)", key):
            raise NetDashError(f"Duplicate or reserved shared-resource alias {key!r}.")
        seen.add(key.casefold())
        resources.append((key, word))
    return resources


def checked_shared_resources(pdef: ProgramDef, parsed: ParsedGrid, data_defs: dict[str, DataDef]) -> list[tuple[str, str]]:
    declared = parse_shared_resources(pdef.shared_resources)
    for alias, word in declared:
        if word not in parsed.root_data:
            raise NetDashError(f"Program {pdef.program_id}: shared resource {alias}={word} is not a root data word in Tab 1.")
        if data_defs.get(word, DataDef(word)).normalized_input_mode() != MODE_SHARED:
            raise NetDashError(f"Program {pdef.program_id}: {word} must have input mode 'Shared single resource' in Tab 2.")
    return declared


def token_kind(token: str) -> str:
    token = normalize_token(token)
    if not token:
        return "blank"
    if token.startswith("#"):
        return "note"
    if token in RESERVED_WORDS:
        return "reserved"
    if token == "|":
        return "wire_v"
    if token == "-":
        return "wire_h"
    if re.match(r"^[0-9]", token):
        return "program"
    return "data"


def program_sort_key(program_id: str) -> tuple[int, int | str]:
    return (0, int(program_id)) if program_id.isdigit() else (1, program_id.casefold())


def sanitize_identifier(value: str, uppercase: bool = False) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", value or "").strip("_") or "NODE"
    if value[0].isdigit():
        value = "N_" + value
    return value.upper() if uppercase else value


def sanitize_filename_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value or "").strip("._-") or "DATA"


def is_safe_runtime_identifier(value: object) -> bool:
    """Whether an identifier can be interpolated safely into generated Bash."""
    text=str(value or "")
    return text not in (".","..") and bool(SAFE_RUNTIME_IDENTIFIER_RE.fullmatch(text))


def is_valid_memory_value(value: object) -> bool:
    match=MEMORY_VALUE_RE.fullmatch(str(value or "").strip())
    return bool(match and float(match.group(1))>0)


def is_valid_time_value(value: object) -> bool:
    text=str(value or "").strip()
    if not text:return False
    position=0;total=0.0
    units={
        "millisecond":0.001,"milliseconds":0.001,"msec":0.001,"msecs":0.001,"ms":0.001,
        "second":1,"seconds":1,"sec":1,"secs":1,"s":1,
        "minute":60,"minutes":60,"min":60,"mins":60,"m":60,
        "hour":3600,"hours":3600,"hr":3600,"hrs":3600,"h":3600,
        "day":86400,"days":86400,"d":86400,
        "week":604800,"weeks":604800,"w":604800,
    }
    for match in TIME_PART_RE.finditer(text):
        if text[position:match.start()].strip():return False
        total+=float(match.group(1))*units[match.group(2).lower()]
        position=match.end()
    return not text[position:].strip() and total>0


def _protect_literal_braces(value: str) -> str:
    """Protect doubled braces while NextDash placeholders are validated/rendered."""
    return str(value).replace("{{",_LITERAL_LBRACE).replace("}}",_LITERAL_RBRACE)


def _restore_literal_braces(value: str) -> str:
    return str(value).replace(_LITERAL_LBRACE,"{").replace(_LITERAL_RBRACE,"}")



ASSET_TEMPLATE_TOKENS = ("{input}", "{input_stem}", "{sample}", "{lineage}")


def parse_additional_inputs(value: str) -> list[tuple[str, str]]:
    """Semicolon-delimited NAME=PATH rules; NAME placeholders are available to programs."""
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in str(value or "").replace("\r\n", "\n").replace("\n", ";").split(";"):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise NetDashError("Additional inputs must be NAME=PATH entries separated by semicolons.")
        key, path = (piece.strip() for piece in item.split("=", 1))
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key):
            raise NetDashError(f"Additional input name {key!r} is invalid.")
        if key.casefold() in seen or re.fullmatch(r"(?i)(input\d*|inputs|output\d*|sample|cpus|group|group_manifest)", key):
            raise NetDashError(f"Additional input name {key!r} is duplicated or reserved.")
        seen.add(key.casefold())
        if not path or any(char in path for char in ('"', "'", "`", "$", "\r", "\n", "\t", ";")):
            raise NetDashError(f"Additional input {key}: path is missing or contains unsupported characters.")
        remainder = path
        for token in ASSET_TEMPLATE_TOKENS:
            remainder = remainder.replace(token, "")
        if "{" in remainder or "}" in remainder:
            raise NetDashError(f"Additional input {key}: supported placeholders are {{input}}, {{input_stem}}, {{sample}}, {{lineage}}.")
        result.append((key, path))
    if len(result) > 64:
        raise NetDashError("A program may declare at most 64 additional input files.")
    return result


def parse_additional_outputs(value: str) -> list[str]:
    """Secondary output filename templates, separated by semicolons."""
    values = [item.strip() for item in str(value or "").replace("\r\n", "\n").replace("\n", ";").split(";") if item.strip()]
    if len(values) > 64:
        raise NetDashError("A program may declare at most 64 additional output files.")
    for value in values:
        if value in (".", "..") or "/" in value or "\\" in value or any(ch in value for ch in ('"', "'", "`", "$", "\r", "\n", "\t", "*", "?", "[", "]")):
            raise NetDashError(f"Additional output {value!r} must be one concrete filename template.")
        residual=value
        for token in ("{sample}", "{lineage}", "{data}", "{program}"):
            residual=residual.replace(token, "")
        if "{" in residual or "}" in residual:
            raise NetDashError(f"Additional output {value!r} uses unsupported placeholders.")
        if "{sample}" not in value and "{lineage}" not in value:
            raise NetDashError(f"Additional output {value!r} must contain {{sample}} or {{lineage}} to avoid sample collisions.")
    if len(values) != len(set(values)):
        raise NetDashError("Additional output filename templates cannot be duplicated.")
    return values


def _asset_groovy_path_template(value: str, convert_windows: bool) -> str:
    """Build a Groovy GString without permitting arbitrary interpolated code."""
    value = windows_path_to_wsl(value) if convert_windows else value
    value = value.replace("\\", "/")
    for marker, expression in (
        ("{input_stem}", "${input_file.toString().replaceFirst(/\\.[^./]+$/, '')}"),
        ("{input}", "${input_file.toString()}"),
        ("{sample}", "${sample_id.toString()}"),
        ("{lineage}", "${lineage.toString()}"),
    ):
        value=value.replace(marker, f"__ND_{ASSET_TEMPLATE_TOKENS.index(marker)}__")
    value=value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
    for i, expression in enumerate(("${input_file.toString()}", "${input_file.toString().replaceFirst(/\\.[^./]+$/, '')}", "${sample_id.toString()}", "${lineage.toString()}")):
        value=value.replace(f"__ND_{i}__",expression)
    return f'file("{value}", checkIfExists: true)'


def validate_relative_subdirectory(value: str,field_name: str="publish subdirectory") -> str:
    value=str(value or "").strip().replace("\\","/")
    if not value:return value
    if value.startswith("/") or re.match(r"^[A-Za-z]:/",value) or any(part in ("",".","..") for part in value.split("/")):
        raise NetDashError(f"{field_name} must be a safe relative directory without empty, '.' or '..' components")
    if any(ch in value for ch in ('"',"`","$","\r","\n","\t")):
        raise NetDashError(f"{field_name} contains unsafe characters")
    return value


def windows_path_to_wsl(value: str) -> str:
    value = (value or "").strip()
    match = re.match(r"^([A-Za-z]):[\\/]+(.*)$", value)
    if not match:
        return re.sub(r"/+", "/", value.replace("\\", "/"))
    rest = re.sub(r"/+", "/", match.group(2).replace("\\", "/"))
    return f"/mnt/{match.group(1).lower()}/{rest}"


def local_preview_path(value: str) -> str:
    value = (value or "").strip()
    if os.name == "nt":
        match = re.match(r"^/mnt/([A-Za-z])/(.*)$", value)
        if match:
            return f"{match.group(1).upper()}:\\{match.group(2).replace('/', os.sep)}"
    return value


def smart_sample_id(path_value: str, sample_regex: str = "") -> str:
    name = re.split(r"[\\/]", str(path_value))[-1]
    if sample_regex.strip():
        try:
            match = re.search(sample_regex.strip(), name)
        except re.error as exc:
            raise NetDashError(f"Invalid sample regex {sample_regex!r}: {exc}.") from exc
        if not match:
            raise NetDashError(f"Filename {name!r} does not match sample regex {sample_regex!r}.")
        return str(match.group(1) if match.groups() else match.group(0))
    lower = name.lower()
    for suffix in KNOWN_DATA_SUFFIXES:
        if lower.endswith(suffix) and len(name) > len(suffix):
            return name[:-len(suffix)]
    return Path(name).stem


def infer_lineage(path_value: str) -> str:
    return smart_sample_id(path_value, "")


def normalize_extension_filter(value: str) -> list[str]:
    """Normalize a user extension filter such as '.fastq.gz,.fq.gz' or 'bam'."""
    raw = (value or "").strip()
    if not raw or raw.lower() in {"*", "*.*", "all", "all files", "(all files)"}:
        return []
    parts = [x.strip() for x in re.split(r"[,;\s]+", raw) if x.strip()]
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        part = part.lower()
        if part.startswith("*"):
            part = part[1:]
        if part and not part.startswith("."):
            part = "." + part
        if part and part not in seen:
            seen.add(part)
            result.append(part)
    return result


def discover_files(pattern: str, extension_filter: str = "") -> list[Path]:
    raw = local_preview_path(pattern)
    if not raw:
        return []
    p = Path(raw)
    if not any(ch in raw for ch in "*?[]") and p.is_dir():
        raw = str(p / "*")
    files = sorted({Path(x) for x in glob.glob(raw,recursive=True) if Path(x).is_file()})
    extensions = normalize_extension_filter(extension_filter)
    if extensions:
        files = [p for p in files if any(p.name.lower().endswith(ext) for ext in extensions)]
    return files


def read_tabtxt(path: Path) -> tuple[list[list[str]], bool]:
    rows: list[list[str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for line in handle.read().splitlines():
            row = []
            for cell in line.split("\t"):
                original = cell.strip()
                row.append(normalize_token(original))
            rows.append(row)


    return normalize_grid(rows or [[""]]), False


def write_tabtxt(path: Path, grid: list[list[str]]) -> None:
    g = trim_grid(grid)
    with path.open("w", encoding="utf-8", newline="") as handle:
        for row in g:
            handle.write("\t".join(row) + "\n")






def _sniff_delimiter(text: str, path: Path) -> str:
    if path.suffix.lower() == ".csv":
        return ","
    if path.suffix.lower() in (".tsv", ".tabtxt", ".tab"):
        return "\t"
    try:
        return csv.Sniffer().sniff(text[:8192], delimiters="\t,;").delimiter
    except Exception:
        return "\t"


def read_sample_table(path_value: str) -> tuple[list[str], list[dict[str, str]]]:
    path = Path(local_preview_path(path_value)).expanduser()
    if not path.is_file():
        raise NetDashError(f"Sample table does not exist: {path_value}")
    text = path.read_text(encoding="utf-8-sig")
    delimiter = _sniff_delimiter(text, path)
    reader = csv.reader(io.StringIO(text),delimiter=delimiter)
    try:raw_headers=next(reader)
    except StopIteration:raw_headers=[]
    headers=[str(value).strip() for value in raw_headers]
    if not headers:
        raise NetDashError(f"Sample table has no header row: {path_value}")
    blank_columns=[index+1 for index,value in enumerate(headers) if not value]
    if blank_columns:
        raise NetDashError(
            f"Sample metadata table contains blank column name(s) at position(s) {blank_columns!r}: {path_value}"
        )
    exact_seen: set[str]=set()
    for header in headers:
        if header in exact_seen:
            raise NetDashError(
                f"Sample metadata table contains duplicate column name {header!r} after whitespace normalization: {path_value}"
            )
        exact_seen.add(header)
    case_seen: dict[str,str]={}
    for header in headers:
        folded=header.casefold()
        previous=case_seen.get(folded)
        if previous is not None:
            raise NetDashError(
                f"Sample metadata table contains column names {previous!r} and {header!r} that differ only by case: {path_value}"
            )
        case_seen[folded]=header
    rows: list[dict[str, str]] = []
    for line_number,values in enumerate(reader,2):
        if len(values)>len(headers):
            raise NetDashError(
                f"Sample metadata table row {line_number} has {len(values)} fields but the header has {len(headers)}: {path_value}"
            )
        padded=list(values)+[""]*(len(headers)-len(values))
        row={header:str(padded[index]).strip() for index,header in enumerate(headers)}
        if any(row.values()):
            rows.append(row)
    return headers, rows


def _uses_windows_path_semantics(value: str) -> bool:
    value = str(value or "").strip().replace("\\", "/")
    return bool(re.match(r"^[A-Za-z]:/",value) or re.match(r"^/mnt/[A-Za-z]/",value,re.IGNORECASE))


def _normalized_compare_path(value: str) -> str:
    original=str(value or "").strip()
    normalized=re.sub(r"/+", "/", windows_path_to_wsl(original).replace("\\", "/")).rstrip("/")
    return normalized.casefold() if _uses_windows_path_semantics(original) else normalized


def _path_exact_equivalent(a: str, b: str) -> bool:
    aa = _normalized_compare_path(a)
    bb = _normalized_compare_path(b)
    if not aa or not bb:
        return False
    return aa == bb


def _path_equivalent(a: str, b: str) -> bool:
    """Compatibility name retained; path matching is now exact and never falls back silently."""
    return _path_exact_equivalent(a,b)


def _filename_equivalent(filename: str, path_value: str) -> bool:
    filename=Path(str(filename or "").replace("\\","/")).name
    candidate=Path(str(path_value or "").replace("\\","/")).name
    if _uses_windows_path_semantics(path_value):
        return filename.casefold()==candidate.casefold()
    return filename==candidate


def _find_metadata_row(
    manifest_row: dict[str, str],
    cfg: WASJConfig,
    table_rows: list[dict[str, str]],
) -> tuple[dict[str, str] | None, str | None]:
    matches: list[dict[str, str]] = []
    if cfg.file_column.strip():
        col = cfg.file_column.strip()
        if cfg.file_match_mode=="Filename only":
            matches=[row for row in table_rows if _filename_equivalent(row.get(col,""),manifest_row["input_path"])]
        else:
            matches=[row for row in table_rows if _path_exact_equivalent(row.get(col,""),manifest_row["input_path"])]
    elif cfg.sample_id_column.strip():
        col = cfg.sample_id_column.strip()
        sid = manifest_row["sample_id"]
        matches = [row for row in table_rows if row.get(col, "") == sid]
    else:
        return None, "Define either File column or Sample ID column for this WASJ."

    if not matches:
        return None, f"No metadata row matched {manifest_row['input_path']!r}."
    if len(matches) > 1:
        return None, f"More than one metadata row matched {manifest_row['input_path']!r}."
    return matches[0], None






def _vertical_blocks(grid: list[list[str]], token: str) -> list[list[tuple[int, int]]]:
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    blocks: list[list[tuple[int, int]]] = []
    for col in range(cols):
        row = 0
        while row < rows:
            if grid[row][col] != token:
                row += 1
                continue
            block: list[tuple[int, int]] = []
            while row < rows and grid[row][col] == token:
                block.append((row, col))
                row += 1
            blocks.append(block)
    return blocks


class _WireResolver:
    def __init__(self, grid: list[list[str]]):
        self.grid = grid
        self.rows = len(grid)
        self.cols = len(grid[0]) if self.rows else 0
        self.cache: dict[tuple[int, int], str] = {}
        self.stack: set[tuple[int, int]] = set()

    def resolve(self, row: int, col: int) -> str:
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            raise NetDashError("Wire endpoint is outside the grid.")
        cell = (row, col)
        if cell in self.cache:
            return self.cache[cell]
        if cell in self.stack:
            raise NetDashError("Wire loop detected.")
        self.stack.add(cell)
        try:
            token = self.grid[row][col]
            kind = token_kind(token)
            if kind == "data":
                self.cache[cell] = token
                return token
            if kind == "wire_h":
                left = col - 1
                while left >= 0 and self.grid[row][left] == "-":
                    left -= 1
                right = col + 1
                while right < self.cols and self.grid[row][right] == "-":
                    right += 1
                candidates: list[str] = []
                for c in (left, right):
                    if 0 <= c < self.cols and token_kind(self.grid[row][c]) in ("data", "wire_v"):
                        try:
                            candidates.append(self.resolve(row, c))
                        except NetDashError:
                            pass
                unique = sorted(set(candidates))
                if not unique:
                    raise NetDashError("Horizontal wire '-' must connect to a data stream on at least one end.")
                if len(unique) > 1:
                    raise NetDashError(f"Horizontal wire '-' connects different streams {unique}; use WASJ to join streams.")
                label = unique[0]
                start = left + 1
                end = right - 1
                for c in range(start, end + 1):
                    if self.grid[row][c] == "-":
                        self.cache[(row, c)] = label
                return label
            if kind == "wire_v":
                top = row
                while top > 0 and self.grid[top - 1][col] == "|":
                    top -= 1
                bottom = row
                while bottom + 1 < self.rows and self.grid[bottom + 1][col] == "|":
                    bottom += 1
                candidates: list[str] = []
                for rr in (top - 1, bottom + 1):
                    if 0 <= rr < self.rows and token_kind(self.grid[rr][col]) in ("data", "wire_h"):
                        try:
                            candidates.append(self.resolve(rr, col))
                        except NetDashError:
                            pass

                for rr in range(top, bottom + 1):
                    for cc in (col - 1, col + 1):
                        if 0 <= cc < self.cols and token_kind(self.grid[rr][cc]) == "data":
                            candidates.append(self.grid[rr][cc])
                unique = sorted(set(candidates))
                if not unique:
                    raise NetDashError("Vertical wire '|' must touch one data stream.")
                if len(unique) > 1:
                    raise NetDashError(f"Vertical wire '|' touches different data streams {unique}; use WASJ to join streams.")
                label = unique[0]
                for rr in range(top, bottom + 1):
                    self.cache[(rr, col)] = label
                return label
            raise NetDashError(f"Cell R{row+1}C{col+1} does not carry a data stream.")
        finally:
            self.stack.discard(cell)


def _barrier_id(token: str, block: list[tuple[int, int]]) -> str:
    top_row = min(r for r, _ in block)
    col = block[0][1]
    return f"{token}_R{top_row+1}C{col+1}"


def parse_grid(grid: list[list[str]]) -> tuple[ParsedGrid, list[ValidationIssue]]:
    g = normalize_grid(grid)
    rows, cols = len(g), len(g[0]) if g else 0
    issues: list[ValidationIssue] = []
    data_labels: set[str] = set()
    program_ids: set[str] = set()
    note_cells: list[tuple[int, int]] = []

    for r in range(rows):
        for c in range(cols):
            token = g[r][c]
            kind = token_kind(token)
            if kind == "data":
                data_labels.add(token)
            elif kind == "program":
                program_ids.add(program_token_id(token))
            elif kind == "note":
                note_cells.append((r, c))

    was_blocks = _vertical_blocks(g, "WAS")
    wasj_blocks = _vertical_blocks(g, "WASJ")
    wasg_blocks = _vertical_blocks(g, "WASG")
    wasg_cells = [cell for block in wasg_blocks for cell in block]

    resolver = _WireResolver(g)
    wire_sources: dict[tuple[int, int], str] = {}
    for r in range(rows):
        for c in range(cols):
            if token_kind(g[r][c]) in ("wire_h", "wire_v"):
                try:
                    wire_sources[(r, c)] = resolver.resolve(r, c)
                except NetDashError as exc:
                    issues.append(ValidationIssue("ERROR", str(exc), ((r, c),)))

    def resolve_source(r: int, c: int) -> str | None:
        if not (0 <= r < rows and 0 <= c < cols):
            return None
        try:
            return resolver.resolve(r, c)
        except NetDashError as exc:
            issues.append(ValidationIssue("ERROR", str(exc), ((r, c),)))
            return None

    block_for_cell: dict[tuple[int, int], tuple[str, list[tuple[int, int]]]] = {}
    for token, blocks in (("WAS", was_blocks), ("WASJ", wasj_blocks)):
        for block in blocks:
            for cell in block:
                block_for_cell[cell] = (token, block)


    for block in was_blocks:
        right_programs: list[tuple[int, int]] = []
        for r, c in block:
            if c == 0 or token_kind(g[r][c - 1]) not in ("data", "wire_h", "wire_v"):
                issues.append(ValidationIssue("ERROR", "Every WAS row needs a data stream immediately on its left.", ((r, c),)))
            else:
                resolve_source(r, c - 1)
            if c + 1 < cols and token_kind(g[r][c + 1]) == "program":
                right_programs.append((r, c + 1))
        if len(right_programs) != 1:
            issues.append(ValidationIssue("ERROR", "A WAS block must have exactly one program immediately on its right. Other WAS rows are wait-only dependency signals.", tuple(block)))


    for block in wasg_blocks:
        if len(block) != 1:
            issues.append(ValidationIssue("ERROR", "WASG groups one stream into one cohort. Use one WASG cell, not a vertical WASG block.", tuple(block)))
        for r, c in block:
            if c == 0 or token_kind(g[r][c - 1]) not in ("data", "wire_h", "wire_v"):
                issues.append(ValidationIssue("ERROR", "WASG needs one per-sample data stream immediately on its left.", ((r, c),)))
            else:
                resolve_source(r, c - 1)
            if c + 1 >= cols or token_kind(g[r][c + 1]) != "program":
                issues.append(ValidationIssue("ERROR", "WASG must have a program ID immediately on its right.", ((r, c),)))


    for block in wasj_blocks:
        if len(block) < 2:
            issues.append(ValidationIssue("ERROR", "WASJ requires at least two vertically contiguous streams. Use WAS for one-stream synchronization.", tuple(block)))
        right_programs: list[tuple[int, int]] = []
        resolved_inputs: list[str] = []
        for r, c in block:
            if c == 0 or token_kind(g[r][c - 1]) not in ("data", "wire_h", "wire_v"):
                issues.append(ValidationIssue("ERROR", "Every WASJ row needs a data stream immediately on its left.", ((r, c),)))
            else:
                source = resolve_source(r, c - 1)
                if source:
                    resolved_inputs.append(source)
            if c + 1 < cols and token_kind(g[r][c + 1]) == "program":
                right_programs.append((r, c + 1))
        if len(right_programs) != 1:
            issues.append(ValidationIssue("ERROR", "A WASJ block must have exactly one program immediately on its right.", tuple(block)))
        if len(resolved_inputs) != len(set(resolved_inputs)):
            issues.append(ValidationIssue("ERROR", "A WASJ block contains the same logical data stream more than once.", tuple(block)))

    occurrences: list[ProgramOccurrence] = []

    for r in range(rows):
        for c in range(cols):
            token = g[r][c]
            if token_kind(token) != "program":
                continue
            pid = program_token_id(token)
            if c + 1 >= cols or token_kind(g[r][c + 1]) not in ("data", "wire_h", "wire_v"):
                issues.append(ValidationIssue(
                    "ERROR",
                    f"Program {pid} must have an output data word, '-' wire, or '|' wire immediately on its right.",
                    ((r, c),),
                ))
                continue
            output_label = resolve_source(r, c + 1)
            if not output_label:
                issues.append(ValidationIssue(
                    "ERROR",
                    f"Program {pid}'s output wire must lead to exactly one data word.",
                    ((r, c + 1),),
                ))
                continue
            if c == 0:
                issues.append(ValidationIssue("ERROR", f"Program {pid} has no input on its left.", ((r, c),)))
                continue

            left = g[r][c - 1]
            left_kind = token_kind(left)
            barrier = "NONE"
            barrier_cells: list[tuple[int, int]] = []
            barrier_id = ""
            inputs: list[str] = []
            waits: list[str] = []
            primary = ""

            if left_kind in ("data", "wire_h", "wire_v"):
                source = resolve_source(r, c - 1)
                if source:
                    inputs = [source]
                    primary = source

            elif left == "WAS":
                barrier = "WAS"
                _, block = block_for_cell.get((r, c - 1), ("WAS", [(r, c - 1)]))
                barrier_cells = list(block)
                barrier_id = _barrier_id("WAS", block)
                source_by_row: dict[int, str] = {}
                for br, bc in block:
                    source = resolve_source(br, bc - 1) if bc > 0 else None
                    if source:
                        source_by_row[br] = source
                        if source not in waits:
                            waits.append(source)
                primary = source_by_row.get(r, "")
                if primary:
                    inputs = [primary]

            elif left == "WASG":
                barrier = "WASG"
                barrier_cells = [(r, c - 1)]
                barrier_id = f"WASG_R{r+1}C{c}"
                source = resolve_source(r, c - 2) if c >= 2 else None
                if source:
                    inputs = [source]
                    primary = source

            elif left == "WASJ":
                barrier = "WASJ"
                _, block = block_for_cell.get((r, c - 1), ("WASJ", [(r, c - 1)]))
                barrier_cells = list(block)
                barrier_id = _barrier_id("WASJ", block)
                for br, bc in block:
                    source = resolve_source(br, bc - 1) if bc > 0 else None
                    if source and source not in inputs:
                        inputs.append(source)

                primary = inputs[0] if inputs else ""

            else:
                issues.append(ValidationIssue("ERROR", f"Program {pid} needs data, a wire, WAS, WASG, or WASJ immediately on its left.", ((r, c),)))
                continue

            if not inputs:
                continue
            occurrences.append(ProgramOccurrence(
                occurrence_id=f"P{pid}_R{r+1}C{c+1}",
                program_id=pid,
                row=r,
                col=c,
                input_labels=inputs,
                output_label=output_label,
                barrier=barrier,
                barrier_id=barrier_id,
                barrier_cells=barrier_cells,
                wait_labels=waits,
                primary_label=primary or inputs[0],
            ))

    producer_by_data: dict[str, ProgramOccurrence] = {}
    for occ in occurrences:
        if occ.output_label in producer_by_data:
            prev = producer_by_data[occ.output_label]
            issues.append(ValidationIssue(
                "ERROR",
                f"Data {occ.output_label!r} has multiple producers ({prev.occurrence_id}, {occ.occurrence_id}).",
                ((occ.row, occ.col + 1),),
            ))
        else:
            producer_by_data[occ.output_label] = occ

    root_data = data_labels - set(producer_by_data)
    parsed = ParsedGrid(
        grid=g,
        data_labels=data_labels,
        program_ids=program_ids,
        occurrences=occurrences,
        producer_by_data=producer_by_data,
        root_data=root_data,
        was_blocks=was_blocks,
        wasg_cells=wasg_cells,
        wasj_blocks=wasj_blocks,
        wire_sources=wire_sources,
        note_cells=note_cells,
    )


    deps: dict[str, set[str]] = {occ.occurrence_id: set() for occ in occurrences}
    for occ in occurrences:
        for label in occ.dependency_labels():
            producer = producer_by_data.get(label)
            if producer and producer.occurrence_id != occ.occurrence_id:
                deps[occ.occurrence_id].add(producer.occurrence_id)

    temporary: set[str] = set()
    permanent: set[str] = set()

    def visit(node: str, stack: list[str]):
        if node in permanent:
            return
        if node in temporary:
            issues.append(ValidationIssue("ERROR", "Dependency cycle detected: " + " -> ".join(stack + [node])))
            return
        temporary.add(node)
        for dep in deps.get(node, set()):
            visit(dep, stack + [node])
        temporary.remove(node)
        permanent.add(node)

    for node in deps:
        visit(node, [])

    return parsed, issues


def topological_occurrences(parsed: ParsedGrid) -> list[ProgramOccurrence]:
    deps: dict[str, set[str]] = {occ.occurrence_id: set() for occ in parsed.occurrences}
    by_id = {occ.occurrence_id: occ for occ in parsed.occurrences}
    for occ in parsed.occurrences:
        for label in occ.dependency_labels():
            producer = parsed.producer_by_data.get(label)
            if producer and producer.occurrence_id != occ.occurrence_id:
                deps[occ.occurrence_id].add(producer.occurrence_id)
    remaining = set(deps)
    result: list[ProgramOccurrence] = []
    while remaining:
        ready = sorted(
            (node for node in remaining if not (deps[node] & remaining)),
            key=lambda node: (by_id[node].col, by_id[node].row, node),
        )
        if not ready:
            raise NetDashError("Dependency graph contains a cycle.")
        for node in ready:
            result.append(by_id[node])
            remaining.remove(node)
    return result






def is_shared_root(label: str, parsed: ParsedGrid, data_defs: dict[str, DataDef]) -> bool:
    return label in parsed.root_data and data_defs.get(label, DataDef(label)).normalized_input_mode() == MODE_SHARED


def metadata_root_for_label(parsed: ParsedGrid, data_defs: dict[str, DataDef], label: str) -> str | None:
    """Return the root stream whose metadata is carried by this logical stream."""
    seen: set[str] = set()
    current = label
    while current not in seen:
        seen.add(current)
        if current in parsed.root_data:
            return None if is_shared_root(current, parsed, data_defs) else current
        producer = parsed.producer_by_data.get(current)
        if producer is None:
            return None
        if producer.barrier == "WASG":
            return None
        current = producer.primary_label or (producer.input_labels[0] if producer.input_labels else "")
        if not current:
            return None
    return None


def _unknown_argument_placeholders(
    args: str,
    occ: ProgramOccurrence,
    parsed: ParsedGrid,
    data_defs: dict[str,DataDef],
) -> list[str]:
    """Return brace placeholders that NextDash cannot render for this process."""
    args=_protect_literal_braces(args)
    allowed={"{output}","{sample}","{cpus}"}
    grouped_labels: set[str]=set()
    if occ.barrier=="WASG":
        label=occ.input_labels[0]
        allowed.update({"{inputs}","{group}","{group_manifest}",f"{{{label}}}"})
    else:
        for idx,label in enumerate(occ.input_labels,1):
            allowed.add(f"{{input{idx}}}")
            if len(occ.input_labels)==1:
                allowed.add("{input}")
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",label):
                allowed.add(f"{{{label}}}")
            if label in parsed.root_data and data_defs.get(label,DataDef(label)).group_files_by_sample:
                grouped_labels.add(label)
                if len(occ.input_labels)==1:
                    allowed.add("{inputs}")
                try:expected=int(data_defs[label].expected_files_per_sample)
                except (TypeError,ValueError):expected=0
                allowed.update(f"{{{label}_{member}}}" for member in range(1,expected+1))

    unknown: set[str]=set()
    for token in re.findall(r"\{[^{}\r\n]+\}",args):
        if token in allowed:
            continue



        generic=re.fullmatch(r"\{input(\d+)\}",token)
        if generic and token==f"{{input{int(generic.group(1))}}}" and occ.barrier!="WASG":
            continue
        handled_member=False
        for label in grouped_labels:
            member=re.fullmatch(rf"\{{{re.escape(label)}_(\d+)\}}",token)
            if member and token==f"{{{label}_{int(member.group(1))}}}":
                handled_member=True
                break
        if not handled_member:
            unknown.add(token)
    return sorted(unknown)


def validate_definitions(
    parsed: ParsedGrid,
    programs: dict[str, ProgramDef],
    data_defs: dict[str, DataDef],
    wasj_configs: dict[str, WASJConfig] | None = None,
    require_files: bool = False,
) -> list[ValidationIssue]:
    wasj_configs = wasj_configs or {}
    issues: list[ValidationIssue] = []

    for pid in sorted(parsed.program_ids, key=program_sort_key):
        pdef = programs.get(pid)
        if pdef is None:
            issues.append(ValidationIssue("ERROR", f"Program {pid} has no definition."))
            continue
        if pdef.program_type not in PROGRAM_TYPES:
            issues.append(ValidationIssue("ERROR", f"Program {pid}: unsupported type {pdef.program_type!r}."))
        if pdef.cpus < 1:
            issues.append(ValidationIssue("ERROR", f"Program {pid}: CPUs must be >= 1."))
        if pdef.max_forks < 0:
            issues.append(ValidationIssue("ERROR", f"Program {pid}: maxForks must be >= 0."))
        memory_value=str(pdef.memory or "").strip();time_value=str(pdef.time or "").strip()
        if not memory_value or not time_value:
            issues.append(ValidationIssue("ERROR", f"Program {pid}: memory and time are required."))
        if memory_value and not is_valid_memory_value(memory_value):
            issues.append(ValidationIssue(
                "ERROR",
                f"Program {pid}: invalid memory value {memory_value!r}. Use a positive value such as 512 MB, 1 GB, or 8 GB.",
            ))
        if time_value and not is_valid_time_value(time_value):
            issues.append(ValidationIssue(
                "ERROR",
                f"Program {pid}: invalid time value {time_value!r}. Use a positive duration such as 30m, 2h, 24h, 2d, or 1d 6h.",
            ))
        if not pdef.program_path.strip() and pdef.program_type != "Inline Bash":
            issues.append(ValidationIssue("ERROR", f"Program {pid}: program/script path is undefined."))
        elif require_files and pdef.program_type != "Inline Bash" and not Path(local_preview_path(pdef.program_path)).expanduser().is_file():
            if os.name=="nt" and pdef.program_path.strip().startswith("/"):
                issues.append(ValidationIssue("WARNING",f"Program {pid}: Linux program path is validated at runtime inside the container: {pdef.program_path}"))
            else:
                issues.append(ValidationIssue("ERROR",f"Program {pid}: file does not exist: {pdef.program_path}"))
        try:validate_relative_subdirectory(pdef.publish_subdirectory,"Program publish subdirectory")
        except NetDashError as exc:issues.append(ValidationIssue("ERROR",f"Program {pid}: {exc}."))
        try:
            extra_inputs=parse_additional_inputs(pdef.additional_inputs)
            extras=parse_additional_outputs(pdef.additional_outputs)
            shared_assets=checked_shared_resources(pdef,parsed,data_defs)
            duplicated={key.casefold() for key,_ in extra_inputs} & {key.casefold() for key,_ in shared_assets}
            if duplicated:
                raise NetDashError(f"Program {pid}: asset aliases are duplicated across Additional Inputs and Shared Resources: {sorted(duplicated)}")
        except NetDashError as exc:
            issues.append(ValidationIssue("ERROR",f"Program {pid}: {exc}"))
            extra_inputs=[];extras=[];shared_assets=[]
        if any("{input}" in item or "{input_stem}" in item for _, item in extra_inputs):
            for occ in [o for o in parsed.occurrences if o.program_id==pid]:
                if occ.barrier not in ("NONE", "WAS") or len(occ.input_labels)!=1:
                    issues.append(ValidationIssue("ERROR", f"Program {pid}: automatic paired inputs require a single per-sample input stream (normal or WAS).", ((occ.row,occ.col),)))
        for occ in [o for o in parsed.occurrences if o.program_id==pid]:
            if shared_assets and occ.barrier == "WASG":
                issues.append(ValidationIssue("ERROR",f"Program {pid}: shared-resource inputs cannot be attached directly to a WASG cohort step.",((occ.row,occ.col),)))
            if extra_inputs and (occ.barrier not in ("NONE", "WAS") or (occ.input_labels and occ.input_labels[0] in parsed.root_data and data_defs.get(occ.input_labels[0],DataDef(occ.input_labels[0])).group_files_by_sample)):
                issues.append(ValidationIssue("ERROR",f"Program {pid}: additional file inputs currently require one ungrouped per-sample stream (normal or WAS).",((occ.row,occ.col),)))
            if extras:
                main_template=data_defs.get(occ.output_label,DataDef(occ.output_label)).normalized_output_template()
                if main_template in extras:
                    issues.append(ValidationIssue("ERROR",f"Program {pid}: secondary output duplicates the primary output template.",((occ.row,occ.col),)))

        for occ in [o for o in parsed.occurrences if o.program_id == pid]:
            args = _protect_literal_braces(pdef.arguments_template)
            if "{output}" not in args and "{output1}" not in args:
                issues.append(ValidationIssue("ERROR", f"Program {pid} arguments must contain {{output}} or {{output1}}.", ((occ.row, occ.col),)))
            known_asset_tokens={f"{{{key}}}" for key,_ in extra_inputs+shared_assets}
            known_extra_outputs={f"{{output{i}}}" for i in range(1,len(extras)+2)}
            for placeholder in sorted(set(_unknown_argument_placeholders(args,occ,parsed,data_defs))-known_asset_tokens-known_extra_outputs):
                issues.append(ValidationIssue(
                    "ERROR",
                    f"Program {pid} contains unknown argument placeholder {placeholder}.",
                    ((occ.row,occ.col),),
                ))

            if occ.barrier == "WASJ":
                per_sample_labels = [
                    label for label in occ.input_labels
                    if not is_shared_root(label, parsed, data_defs)
                ]
                if not per_sample_labels:
                    issues.append(ValidationIssue(
                        "ERROR",
                        f"{occ.barrier_id}: WASJ requires at least one per-sample stream; all inputs are shared resources.",
                        tuple(occ.barrier_cells),
                    ))

            if occ.barrier == "WASG":
                label = occ.input_labels[0]
                if not any(x in args for x in ("{inputs}", "{group}", "{group_manifest}", f"{{{label}}}")):
                    issues.append(ValidationIssue(
                        "ERROR",
                        f"Program {pid} follows WASG. Arguments must contain {{group_manifest}}, {{group}}, {{inputs}}, or {{{label}}}.",
                        ((occ.row, occ.col),),
                    ))
                continue

            invalid_generic_indexes=sorted({
                int(value) for value in re.findall(r"\{input(\d+)\}",args)
                if int(value)<1 or int(value)>len(occ.input_labels)
            })
            if invalid_generic_indexes:
                grouped_labels=[
                    label for label in occ.input_labels
                    if label in parsed.root_data and data_defs.get(label,DataDef(label)).group_files_by_sample
                ]
                guidance=(
                    f" For individual grouped members, use named placeholders such as {{{grouped_labels[0]}_1}}, {{{grouped_labels[0]}_2}}, ... ."
                    if grouped_labels else ""
                )
                issues.append(ValidationIssue(
                    "ERROR",
                    f"Program {pid}: generic placeholder index(es) {invalid_generic_indexes!r} exceed the {len(occ.input_labels)} logical input stream(s)."+guidance,
                    ((occ.row,occ.col),),
                ))

            for idx, label in enumerate(occ.input_labels, 1):
                generic=f"{{input{idx}}}"
                named = f"{{{label}}}" if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", label) else ""
                multifile=label in parsed.root_data and data_defs.get(label,DataDef(label)).group_files_by_sample
                aliases=[generic]
                if len(occ.input_labels)==1:aliases.append("{input}")
                if len(occ.input_labels)==1 and multifile:aliases.append("{inputs}")
                if named:aliases.append(named)
                member_indexes:set[int]=set()
                if multifile and named:
                    member_indexes={int(value) for value in re.findall(rf"\{{{re.escape(label)}_(\d+)\}}",args)}
                    try:
                        expected=int(data_defs[label].expected_files_per_sample)
                    except (TypeError,ValueError):
                        expected=0
                    uses_whole_stream=any(token in args for token in aliases)
                    invalid_members=sorted(value for value in member_indexes if value<1 or value>expected)
                    if invalid_members:
                        issues.append(ValidationIssue(
                            "ERROR",
                            f"Program {pid}: grouped data {label!r} has out-of-range member placeholder(s) "
                            + ", ".join(f"{{{label}_{value}}}" for value in invalid_members)
                            + f"; configured Files/sample is {expected}.",
                            ((occ.row,occ.col),),
                        ))
                    if member_indexes and not uses_whole_stream and member_indexes!=set(range(1,expected+1)):
                        issues.append(ValidationIssue("ERROR",f"Program {pid}: grouped data {label!r} expects {expected} files per sample. Member placeholders must include exactly " + ", ".join(f"{{{label}_{i}}}" for i in range(1,expected+1)) + ".",((occ.row,occ.col),)))
                if not any(token in args for token in aliases) and not member_indexes:
                    issues.append(ValidationIssue(
                        "ERROR",
                        f"Program {pid} input {idx} is data {label!r}; arguments need {generic}"
                        + (f", {named}, or named members such as {{{label}_1}}" if multifile and named else f" or {named}" if named else "") + ".",
                        ((occ.row, occ.col),),
                    ))

    for label in sorted(parsed.data_labels):
        ddef = data_defs.get(label)
        if ddef is None:
            issues.append(ValidationIssue("ERROR", f"Data {label!r} has no definition."))
            continue
        if label in parsed.root_data:
            if ddef.normalized_input_mode() == MODE_PER_SAMPLE and ddef.sample_regex.strip():
                try:
                    re.compile(ddef.sample_regex.strip())
                except re.error as exc:
                    issues.append(ValidationIssue("ERROR", f"Root data {label!r}: invalid sample regex: {exc}."))
            if ddef.group_files_by_sample:
                if ddef.normalized_input_mode()!=MODE_PER_SAMPLE:
                    issues.append(ValidationIssue("ERROR",f"Root data {label!r}: grouped multi-file mode cannot be combined with Shared single resource."))
                if not ddef.sample_regex.strip():
                    issues.append(ValidationIssue("ERROR",f"Root data {label!r}: grouped multi-file mode requires a sample ID regex that maps related files to one sample."))
                try:
                    expected_files=int(ddef.expected_files_per_sample)
                except (TypeError,ValueError):
                    expected_files=0
                if expected_files<2:
                    issues.append(ValidationIssue("ERROR",f"Root data {label!r}: expected files per grouped sample must be at least 2."))
            if not ddef.input_pattern.strip():
                issues.append(ValidationIssue("ERROR", f"Root data {label!r} must define an input folder/file/glob."))
            elif require_files:
                files = discover_files(discovery_pattern(ddef), ddef.input_extensions)
                if ddef.normalized_input_mode() == MODE_SHARED:
                    if len(files) != 1:
                        issues.append(ValidationIssue("ERROR", f"Shared data {label!r} must resolve to exactly one file; found {len(files)}."))
                elif not files:
                    issues.append(ValidationIssue("ERROR", f"Root data {label!r}: no files match {ddef.input_pattern!r}" + (f" with extension filter {ddef.input_extensions!r}." if ddef.input_extensions else ".")))
        else:
            template = ddef.normalized_output_template()
            if "/" in template or "\\" in template:
                issues.append(ValidationIssue("ERROR", f"Generated data {label!r}: output template must be a filename, not a path."))
            if any(ch in template for ch in ('"', "`", "$", "\r", "\n", "\t")):
                issues.append(ValidationIssue(
                    "ERROR",
                    f"Generated data {label!r}: output template contains characters that are unsafe in Nextflow/Bash filenames.",
                ))
            controlled=template
            for field_name in ("sample","lineage","data","program"):controlled=controlled.replace(f"{{{field_name}}}","")
            if any(ch in controlled for ch in "*?[]{}"):
                issues.append(ValidationIssue("ERROR",f"Generated data {label!r}: output template must be one concrete filename; wildcards and uncontrolled braces are not allowed."))
            allowed = {"sample", "lineage", "data", "program"}
            unknown = set(re.findall(r"\{([A-Za-z0-9_]+)\}", template)) - allowed
            if unknown:
                issues.append(ValidationIssue("ERROR", f"Generated data {label!r}: unknown output-template fields: {', '.join(sorted(unknown))}."))
            producer=parsed.producer_by_data.get(label)
            if producer:
                upstream=producer.primary_label or (producer.input_labels[0] if producer.input_labels else "")
                per_sample=producer.barrier=="WASJ" or (producer.barrier!="WASG" and bool(upstream) and metadata_root_for_label(parsed,data_defs,upstream) is not None)
                if per_sample and "{sample}" not in template and "{lineage}" not in template:
                    issues.append(ValidationIssue("ERROR",f"Generated data {label!r}: per-sample output template must contain {{sample}} or {{lineage}} to prevent samples overwriting one another."))

    for occ in parsed.wasj_occurrences():
        cfg = wasj_configs.get(occ.barrier_id)
        if cfg is None:
            issues.append(ValidationIssue("ERROR", f"{occ.barrier_id} has no WASJ metadata configuration.", tuple(occ.barrier_cells)))
            continue
        if not cfg.sample_table_path.strip():
            issues.append(ValidationIssue("ERROR", f"{occ.barrier_id}: sample table is not defined.", tuple(occ.barrier_cells)))
            continue
        try:
            headers, _ = read_sample_table(cfg.sample_table_path)
        except Exception as exc:
            issues.append(ValidationIssue("ERROR", f"{occ.barrier_id}: {exc}", tuple(occ.barrier_cells)))
            continue
        if not cfg.join_key.strip() or cfg.join_key not in headers:
            issues.append(ValidationIssue("ERROR", f"{occ.barrier_id}: choose a valid Join key column.", tuple(occ.barrier_cells)))
        diff = cfg.normalized_difference_keys()
        if not diff:
            issues.append(ValidationIssue("ERROR", f"{occ.barrier_id}: define at least one Difference key.", tuple(occ.barrier_cells)))
        for key in diff:
            if key not in headers:
                issues.append(ValidationIssue("ERROR", f"{occ.barrier_id}: Difference key {key!r} is not in the sample table.", tuple(occ.barrier_cells)))
        if cfg.file_column and cfg.file_column not in headers:
            issues.append(ValidationIssue("ERROR", f"{occ.barrier_id}: file column {cfg.file_column!r} is not in the sample table.", tuple(occ.barrier_cells)))
        if cfg.file_column and cfg.file_match_mode not in WASJ_FILE_MATCH_MODES:
            issues.append(ValidationIssue("ERROR",f"{occ.barrier_id}: choose Exact path or Filename only matching.",tuple(occ.barrier_cells)))
        if cfg.sample_id_column and cfg.sample_id_column not in headers:
            issues.append(ValidationIssue("ERROR", f"{occ.barrier_id}: sample ID column {cfg.sample_id_column!r} is not in the sample table.", tuple(occ.barrier_cells)))
        if not cfg.file_column and not cfg.sample_id_column:
            issues.append(ValidationIssue("ERROR", f"{occ.barrier_id}: choose File column or Sample ID column so NextDash can match files to metadata rows.", tuple(occ.barrier_cells)))

    return issues






def discovery_pattern(ddef: DataDef) -> str:
    return (ddef.local_scan_pattern or "").strip() or ddef.input_pattern


def manifest_input_path(ddef: DataDef, discovered_file: Path) -> str:
    local=(ddef.local_scan_pattern or "").strip()
    if not local:
        return str(discovered_file)
    runtime=ddef.input_pattern.strip().replace("\\", "/")
    if not any(symbol in local for symbol in "*?["):
        return runtime
    local_path=local.replace("\\", "/")
    start=min((local_path.index(symbol) for symbol in "*?[" if symbol in local_path),default=len(local_path))
    local_dir=local_path[:start].rsplit("/",1)[0]
    runtime_start=min((runtime.index(symbol) for symbol in "*?[" if symbol in runtime),default=len(runtime))
    runtime_dir=runtime[:runtime_start].rsplit("/",1)[0]
    found=str(discovered_file).replace("\\", "/")
    prefix=local_dir.rstrip("/")+"/"
    if os.path.normcase(found).casefold().startswith(os.path.normcase(prefix).casefold()):
        suffix=found[len(prefix):]
        return runtime_dir.rstrip("/")+"/"+suffix
    raise NetDashError(f"Local scanned file {found!r} is outside its expected source folder {local_dir!r}.")


def scan_root_inputs(
    parsed: ParsedGrid,
    data_defs: dict[str, DataDef],
    wasj_configs: dict[str, WASJConfig] | None = None,
) -> tuple[list[dict[str, str]], list[ValidationIssue]]:
    wasj_configs = wasj_configs or {}
    rows: list[dict[str, str]] = []
    issues: list[ValidationIssue] = []

    for label in sorted(parsed.root_data):
        ddef = data_defs.get(label, DataDef(label))
        if not ddef.input_pattern.strip():
            continue
        files = discover_files(discovery_pattern(ddef), ddef.input_extensions)
        if ddef.normalized_input_mode() == MODE_SHARED:
            if len(files) == 1:
                rows.append({
                    "data_id": label,
                    "sample_id": "__SHARED__",
                    "input_path": manifest_input_path(ddef,files[0]),
                    "lineage": sanitize_filename_component(label),
                    "metadata_json": "{}",
                })
            elif files:
                issues.append(ValidationIssue("ERROR", f"Shared root {label!r} must match exactly one file; found {len(files)}."))
            continue

        seen: set[str] = set();sample_counts: dict[str,int]={}
        for path in files:
            try:
                sid = smart_sample_id(str(path), ddef.sample_regex)
            except NetDashError as exc:
                issues.append(ValidationIssue("ERROR", f"Data {label!r}: {exc}"))
                continue
            if sid in seen:
                if not ddef.group_files_by_sample:
                    issues.append(ValidationIssue("ERROR",f"Data {label!r}: duplicate sample ID {sid!r}. Enable 'Group files with the same sample ID' for paired-end or multi-file samples."))
                    continue
            seen.add(sid)
            sample_counts[sid]=sample_counts.get(sid,0)+1
            rows.append({
                "data_id": label,
                "sample_id": sid,
                "input_path": manifest_input_path(ddef,path),
                "lineage": sanitize_filename_component(sid) if ddef.group_files_by_sample else infer_lineage(str(path)),
                "metadata_json": "{}",
            })
        try:
            expected=int(ddef.expected_files_per_sample)
        except (TypeError,ValueError):
            expected=0
        if ddef.group_files_by_sample and expected>=2:
            for sid,count in sorted(sample_counts.items()):
                if count!=expected:issues.append(ValidationIssue("ERROR",f"Data {label!r}: grouped sample {sid!r} has {count} file(s); expected exactly {expected}."))



    for occ in parsed.wasj_occurrences():
        cfg = wasj_configs.get(occ.barrier_id)
        if not cfg or not cfg.sample_table_path.strip():
            continue
        try:
            headers, table_rows = read_sample_table(cfg.sample_table_path)
        except Exception as exc:
            issues.append(ValidationIssue("ERROR", f"{occ.barrier_id}: {exc}", tuple(occ.barrier_cells)))
            continue
        metadata_roots = {
            metadata_root_for_label(parsed, data_defs, label)
            for label in occ.input_labels
            if not is_shared_root(label, parsed, data_defs)
        }
        metadata_roots.discard(None)
        for manifest_row in rows:
            if manifest_row["data_id"] not in metadata_roots:
                continue
            meta_row, error = _find_metadata_row(manifest_row, cfg, table_rows)
            if error:
                issues.append(ValidationIssue("ERROR", f"{occ.barrier_id}: {error}"))
                continue
            metadata = json.loads(manifest_row.get("metadata_json") or "{}")
            for header in headers:
                metadata[f"{occ.barrier_id}::{header}"] = meta_row.get(header, "")
            manifest_row["metadata_json"] = json.dumps(metadata, separators=(",", ":"))

    issues.extend(validate_manifest_runtime_identifiers(rows))
    return rows, issues


def validate_manifest_runtime_identifiers(manifest_rows: list[dict[str,str]]) -> list[ValidationIssue]:
    """Reject manifest identities that are unsafe in generated Bash strings."""
    issues: list[ValidationIssue]=[]
    reported: set[tuple[str,str,str]]=set()
    for row in manifest_rows:
        sample_id=str(row.get("sample_id", ""))
        lineage=str(row.get("lineage", ""))
        unsafe_fields=[]
        if not is_safe_runtime_identifier(sample_id):unsafe_fields.append(("sample_id",sample_id))
        if not is_safe_runtime_identifier(lineage):unsafe_fields.append(("lineage",lineage))
        for field_name,value in unsafe_fields:
            key=(str(row.get("data_id", "")),field_name,value)
            if key in reported:continue
            reported.add(key)
            issues.append(ValidationIssue(
                "ERROR",
                f"Data {row.get('data_id','')!r}: {field_name} {value!r} is unsafe for generated shell code. "
                "Use only ASCII letters, digits, underscore, hyphen, and period; adjust the Sample ID regex if necessary.",
            ))
    return issues


def _manifest_rows_for_stream(
    parsed: ParsedGrid,
    data_defs: dict[str, DataDef],
    manifest_rows: list[dict[str, str]],
    label: str,
) -> list[dict[str, str]]:
    root = metadata_root_for_label(parsed, data_defs, label)
    if root is None:
        return []
    return [row for row in manifest_rows if row["data_id"] == root and row["sample_id"] != "__SHARED__"]


def preview_wasj(
    parsed: ParsedGrid,
    data_defs: dict[str, DataDef],
    manifest_rows: list[dict[str, str]],
    occ: ProgramOccurrence,
    cfg: WASJConfig,
) -> WASJPreview:
    issues: list[ValidationIssue] = []
    if occ.barrier != "WASJ":
        raise NetDashError("preview_wasj requires a WASJ occurrence.")
    try:
        headers, table_rows = read_sample_table(cfg.sample_table_path)
    except Exception as exc:
        return WASJPreview(occ.barrier_id, occ.input_labels, cfg.join_key, cfg.normalized_difference_keys(), cfg.role_values, [], [], [ValidationIssue("ERROR", str(exc), tuple(occ.barrier_cells))])

    join_key = cfg.join_key.strip()
    diff_keys = cfg.normalized_difference_keys()
    if join_key not in headers:
        issues.append(ValidationIssue("ERROR", f"Join key {join_key!r} is not a sample-table column.", tuple(occ.barrier_cells)))
    for key in diff_keys:
        if key not in headers:
            issues.append(ValidationIssue("ERROR", f"Difference key {key!r} is not a sample-table column.", tuple(occ.barrier_cells)))

    per_sample_labels = [label for label in occ.input_labels if not is_shared_root(label, parsed, data_defs)]
    maps: dict[str, dict[str, dict[str, str]]] = {}
    inferred: dict[str, dict[str, str]] = {label: {} for label in per_sample_labels}

    for label in per_sample_labels:
        stream_rows = _manifest_rows_for_stream(parsed, data_defs, manifest_rows, label)
        if not stream_rows:
            issues.append(ValidationIssue("ERROR", f"{occ.barrier_id}: no per-sample files are available for stream {label!r}.", tuple(occ.barrier_cells)))
            continue
        by_join: dict[str, dict[str, str]] = {}
        role_values_seen: dict[str, set[str]] = {key: set() for key in diff_keys}
        for mrow in stream_rows:
            meta_row, error = _find_metadata_row(mrow, cfg, table_rows)
            if error:
                issues.append(ValidationIssue("ERROR", f"{occ.barrier_id} / {label}: {error}"))
                continue
            jv = str(meta_row.get(join_key, "")).strip()
            if not jv:
                issues.append(ValidationIssue("ERROR", f"{occ.barrier_id} / {label}: empty Join key for {mrow['input_path']!r}."))
                continue
            if not is_safe_runtime_identifier(jv):
                issues.append(ValidationIssue(
                    "ERROR",
                    f"{occ.barrier_id} / {label}: Join key value {jv!r} is unsafe for generated shell code. "
                    "Use only ASCII letters, digits, underscore, hyphen, and period.",
                    tuple(occ.barrier_cells),
                ))
            if jv in by_join:
                root=metadata_root_for_label(parsed,data_defs,label)
                same_multifile_sample=bool(root and data_defs.get(root,DataDef(root)).group_files_by_sample and by_join[jv].get("sample_id")==mrow.get("sample_id"))
                if same_multifile_sample:
                    existing_meta=json.loads(by_join[jv].get("metadata_json") or "{}")
                    current_meta=json.loads(mrow.get("metadata_json") or "{}")
                    if any(existing_meta.get(f"{occ.barrier_id}::{key}")!=current_meta.get(f"{occ.barrier_id}::{key}") for key in [join_key,*diff_keys]):
                        issues.append(ValidationIssue("ERROR",f"{occ.barrier_id} / {label}: files grouped as sample {mrow.get('sample_id')!r} have inconsistent Join/Difference metadata.",tuple(occ.barrier_cells)))
                    continue
                issues.append(ValidationIssue("ERROR",f"{occ.barrier_id} / {label}: Join key {jv!r} occurs more than once in this stream. The Join key alone must identify one logical sample per stream; choose a unique/composite identifier column or group replicates first.",tuple(occ.barrier_cells)))
                continue
            record = dict(mrow)
            record["__join__"] = jv
            for key in diff_keys:
                difference_value=str(meta_row.get(key, "")).strip()
                record[f"__role__{key}"] = difference_value
                if not difference_value:
                    issues.append(ValidationIssue(
                        "ERROR",
                        f"{occ.barrier_id} / {label}: Difference key {key!r} is empty for {mrow['input_path']!r}.",
                        tuple(occ.barrier_cells),
                    ))
                else:
                    role_values_seen[key].add(difference_value)
            by_join[jv] = record
        maps[label] = by_join

        expected = cfg.role_values.get(label, {})
        for key in diff_keys:
            values = role_values_seen.get(key, set())
            if key in expected and expected[key] != "":
                bad = sorted(v for v in values if v != expected[key])
                if bad:
                    issues.append(ValidationIssue(
                        "ERROR",
                        f"{occ.barrier_id} / {label}: expected {key}={expected[key]!r}, but observed {sorted(values)!r}.",
                        tuple(occ.barrier_cells),
                    ))
                inferred[label][key] = expected[key]
            elif len(values) == 1:
                inferred[label][key] = next(iter(values))
            elif len(values) == 0:
                inferred[label][key] = ""
                issues.append(ValidationIssue(
                    "ERROR",
                    f"{occ.barrier_id} / {label}: no non-empty value is available for Difference key {key!r}.",
                    tuple(occ.barrier_cells),
                ))
            else:
                issues.append(ValidationIssue(
                    "ERROR",
                    f"{occ.barrier_id} / {label}: Difference key {key!r} has multiple values {sorted(values)!r}. "
                    "Each NextDash stream must represent one Difference signature; narrow the input definition or split the stream.",
                    tuple(occ.barrier_cells),
                ))


    signatures: dict[tuple[str, ...], str] = {}
    for label in per_sample_labels:
        signature = tuple(inferred.get(label, {}).get(key, "") for key in diff_keys)
        if not diff_keys or not signature or not all(signature):
            issues.append(ValidationIssue(
                "ERROR",
                f"{occ.barrier_id}: stream {label!r} does not have a complete Difference signature for keys {diff_keys!r}.",
                tuple(occ.barrier_cells),
            ))
            continue
        if signature in signatures:
            issues.append(ValidationIssue(
                "ERROR",
                f"{occ.barrier_id}: streams {signatures[signature]!r} and {label!r} have the same Difference signature {signature!r}.",
                tuple(occ.barrier_cells),
            ))
        else:
            signatures[signature] = label

    join_sets = [set(maps.get(label, {})) for label in per_sample_labels if maps.get(label) is not None]
    join_values: list[str] = []
    if join_sets:
        union = set().union(*join_sets)
        intersection = set.intersection(*join_sets) if join_sets else set()
        join_values = sorted(union)
        for value in sorted(union - intersection):
            missing = [label for label in per_sample_labels if value not in maps.get(label, {})]
            issues.append(ValidationIssue(
                "ERROR",
                f"{occ.barrier_id}: Join key {value!r} is missing from stream(s): {', '.join(missing)}.",
                tuple(occ.barrier_cells),
            ))

    preview_rows: list[dict[str, str]] = []
    for value in join_values:
        row = {"join_key": value}
        for label in occ.input_labels:
            if is_shared_root(label, parsed, data_defs):
                row[label] = "SHARED RESOURCE"
            else:
                item = maps.get(label, {}).get(value)
                row[label] = Path(item["input_path"]).name if item else "MISSING"
        preview_rows.append(row)


    merged_roles: dict[str, dict[str, str]] = {}
    for label in per_sample_labels:
        merged_roles[label] = dict(inferred.get(label, {}))
        merged_roles[label].update({k: v for k, v in cfg.role_values.get(label, {}).items() if v != ""})

    return WASJPreview(
        barrier_id=occ.barrier_id,
        input_labels=occ.input_labels,
        join_key=join_key,
        difference_keys=diff_keys,
        role_values=merged_roles,
        join_values=join_values,
        rows=preview_rows,
        issues=issues,
    )


def validate_wasj_configs(
    parsed: ParsedGrid,
    data_defs: dict[str, DataDef],
    manifest_rows: list[dict[str, str]],
    wasj_configs: dict[str, WASJConfig],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for occ in parsed.wasj_occurrences():
        cfg = wasj_configs.get(occ.barrier_id)
        if not cfg:
            continue
        preview = preview_wasj(parsed, data_defs, manifest_rows, occ, cfg)
        issues.extend(preview.issues)
    return issues



validate_join_sample_sets = validate_wasj_configs


def calculate_expected_published_outputs(
    parsed: ParsedGrid,
    programs: dict[str, ProgramDef],
    data_defs: dict[str, DataDef],
    wasj_configs: dict[str, WASJConfig],
    manifest_rows: list[dict[str, str]],
    results_directory: str = "results",
) -> tuple[list[dict[str,str]],list[ValidationIssue]]:
    """Calculate every publishDir filename and report destination collisions.

    This mirrors the record identity/lineage transformations performed by the
    generated workflow. It deliberately runs before files are generated so two
    biological records can never silently target the same published path.
    """
    issues: list[ValidationIssue] = []
    records_by_label: dict[str,list[dict[str,str]]] = {}

    for label in sorted(parsed.root_data):
        root_rows=[row for row in manifest_rows if row.get("data_id")==label]
        if is_shared_root(label,parsed,data_defs):
            records_by_label[label]=[{
                "sample_id":sanitize_filename_component(label),
                "lineage":sanitize_filename_component(label),
                "metadata_json":"{}",
                "source":f"shared root {label}",
            }] if root_rows else []
            continue

        logical_rows: list[dict[str,str]]=[]
        seen_samples: set[str]=set()
        grouped=data_defs.get(label,DataDef(label)).group_files_by_sample
        for row in root_rows:
            sample_id=str(row.get("sample_id", ""))
            if grouped and sample_id in seen_samples:
                continue
            seen_samples.add(sample_id)
            logical_rows.append({
                "sample_id":sample_id,
                "lineage":str(row.get("lineage", "")),
                "metadata_json":str(row.get("metadata_json", "{}")),
                "source":f"root {label} sample {sample_id}",
            })
        records_by_label[label]=logical_rows

    publications: list[dict[str,str]]=[]
    seen_destinations: dict[str,dict[str,str]]={}
    try:
        ordered=topological_occurrences(parsed)
    except NetDashError:


        return publications,issues
    for occ in ordered:
        pdef=programs.get(occ.program_id,ProgramDef(occ.program_id))
        out_def=data_defs.get(occ.output_label,DataDef(occ.output_label))

        if occ.barrier=="WASG":
            group_id=f"GROUP_{sanitize_filename_component(occ.input_labels[0])}"
            output_records=[{
                "sample_id":group_id,
                "lineage":group_id,
                "metadata_json":"{}",
                "source":f"{occ.occurrence_id} group {group_id}",
            }] if records_by_label.get(occ.input_labels[0]) else []
        elif occ.barrier=="WASJ":
            sample_labels=[label for label in occ.input_labels if not is_shared_root(label,parsed,data_defs)]
            cfg=wasj_configs.get(occ.barrier_id,WASJConfig(occ.barrier_id))
            metadata_key=f"{occ.barrier_id}::{cfg.join_key.strip()}"
            keyed: list[dict[str,dict[str,str]]]=[]
            for label in sample_labels:
                values: dict[str,dict[str,str]]={}
                for record in records_by_label.get(label,[]):
                    try:
                        metadata=json.loads(record.get("metadata_json") or "{}")
                    except (TypeError,ValueError,json.JSONDecodeError):
                        metadata={}
                    join_value=str(metadata.get(metadata_key, "")).strip()
                    if join_value:
                        values[join_value]=record
                keyed.append(values)
            common_join_values=set.intersection(*(set(values) for values in keyed)) if keyed else set()
            output_records=[]
            for join_value in sorted(common_join_values):
                primary=keyed[0][join_value]
                output_records.append({
                    "sample_id":join_value,
                    "lineage":primary.get("lineage", ""),
                    "metadata_json":primary.get("metadata_json", "{}"),
                    "source":f"{occ.occurrence_id} join {join_value}",
                })
        else:
            source_label=occ.primary_label or occ.input_labels[0]
            output_records=[dict(record) for record in records_by_label.get(source_label,[])]

        records_by_label[occ.output_label]=output_records
        template=out_def.normalized_output_template()
        custom=(out_def.publish_directory or "").strip().replace("\\","/").rstrip("/")
        publish_directory=custom or f"{(results_directory or 'results').strip().replace(chr(92),'/').rstrip('/')}/{pdef.normalized_publish_dir()}"
        for record in output_records:
            filename=template
            for token,value in {
                "{sample}":record.get("sample_id", ""),
                "{lineage}":record.get("lineage", ""),
                "{data}":sanitize_filename_component(out_def.label),
                "{program}":sanitize_filename_component(pdef.normalized_name()),
            }.items():
                filename=filename.replace(token,str(value))
            if (
                not filename
                or "/" in filename
                or "\\" in filename
                or filename in (".","..")
                or any(ch in filename for ch in ('"',"$","`","\r","\n","\t"))
            ):
                issues.append(ValidationIssue(
                    "ERROR",
                    f"Expected output filename {filename!r} for {record['source']} is not one safe filename.",
                    ((occ.row,occ.col),),
                ))
                continue
            destination=f"{publish_directory}/{filename}"
            destination_key=re.sub(r"/+","/",destination)
            if os.name=="nt" or _uses_windows_path_semantics(destination):
                destination_key=destination_key.casefold()
            publication={
                "data_id":occ.output_label,
                "program_id":occ.program_id,
                "occurrence_id":occ.occurrence_id,
                "sample_id":record.get("sample_id", ""),
                "lineage":record.get("lineage", ""),
                "filename":filename,
                "publish_directory":publish_directory,
                "destination":destination,
                "source":record["source"],
            }
            previous=seen_destinations.get(destination_key)
            if previous is not None:
                issues.append(ValidationIssue(
                    "ERROR",
                    f"Published output collision: {destination!r} would be written by both {previous['source']} ({previous['occurrence_id']}) and {publication['source']} ({occ.occurrence_id}). Change an output template or published folder.",
                    ((occ.row,occ.col),),
                ))
            else:
                seen_destinations[destination_key]=publication
            publications.append(publication)
            try:
                secondary_templates=parse_additional_outputs(pdef.additional_outputs)
            except NetDashError as exc:
                issues.append(ValidationIssue("ERROR",f"Program {occ.program_id}: {exc}",((occ.row,occ.col),)))
                secondary_templates=[]
            for auxiliary_index, auxiliary_template in enumerate(secondary_templates, 2):
                auxiliary_name=auxiliary_template
                for token,value in {
                    "{sample}":record.get("sample_id", ""),
                    "{lineage}":record.get("lineage", ""),
                    "{data}":sanitize_filename_component(out_def.label),
                    "{program}":sanitize_filename_component(pdef.normalized_name()),
                }.items():
                    auxiliary_name=auxiliary_name.replace(token,str(value))
                auxiliary_destination=f"{publish_directory}/{auxiliary_name}"
                auxiliary_key=re.sub(r"/+","/",auxiliary_destination)
                if os.name=="nt" or _uses_windows_path_semantics(auxiliary_destination):
                    auxiliary_key=auxiliary_key.casefold()
                entry={**publication,
                    "data_id":f"{occ.output_label}:auxiliary_{auxiliary_index}",
                    "filename":auxiliary_name,
                    "destination":auxiliary_destination,
                }
                existing=seen_destinations.get(auxiliary_key)
                if existing is not None:
                    issues.append(ValidationIssue("ERROR",f"Published output collision: {auxiliary_destination!r} is produced by both {existing['source']} and {entry['source']}.",((occ.row,occ.col),)))
                else:
                    seen_destinations[auxiliary_key]=entry
                publications.append(entry)

    return publications,issues






def _groovy_quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _program_command(pdef: ProgramDef, convert_windows: bool) -> str:
    path = windows_path_to_wsl(pdef.program_path) if convert_windows else pdef.program_path
    quoted = shlex.quote(path)
    return {
        "Python 3": f"python3 {quoted}",
        "Rscript": f"Rscript --vanilla {quoted}",
        "Bash": f"bash {quoted}",
    }.get(pdef.program_type, quoted)


def _render_task_command(pdef: ProgramDef, args: str, convert_windows: bool) -> str:
    """For Inline Bash, run the template as the task script, not bash -c with positional arguments."""
    if pdef.program_type == "Inline Bash":
        return args
    return f"{_program_command(pdef, convert_windows)} {args}"


def _process_name(occ: ProgramOccurrence, pdef: ProgramDef) -> str:
    return sanitize_identifier(f"P{occ.program_id}_{pdef.normalized_name()}_{occ.output_label}_R{occ.row+1}C{occ.col+1}", True)


def _channel_name(label: str) -> str:


    base = sanitize_identifier(label)[:48]
    digest = hashlib.sha1(label.encode("utf-8")).hexdigest()[:12]
    return f"ch_{base}_{digest}"


def _bash_double_quote_text(value: str) -> str:
    """Escape display-only text embedded inside a Bash double-quoted string."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")


def _output_expr(ddef: DataDef, pdef: ProgramDef, lineage_var: str, sample_var: str = "sample_id") -> str:
    output = ddef.normalized_output_template()
    replacements = {
        "{sample}": f"${{{sample_var}}}",
        "{lineage}": f"${{{lineage_var}}}",
        "{data}": sanitize_filename_component(ddef.label),
        "{program}": sanitize_filename_component(pdef.normalized_name()),
    }
    for old, new in replacements.items():
        output = output.replace(old, new)
    return output


def _replace_input_placeholders(args: str,occ: ProgramOccurrence,variables: dict[str,str],multi_file_counts: dict[str,int] | None=None) -> str:
    multi_file_counts=multi_file_counts or {};multi_file_labels=set(multi_file_counts)
    if occ.barrier == "WASG":
        label = occ.input_labels[0]
        for token in ("{group}","{group_manifest}",f"{{{label}}}"):
            args=args.replace(token,'"\\$GROUP_MANIFEST"')
        args=args.replace("{inputs}",'"\\${GROUP_INPUTS[@]}"')
        return args

    for idx, label in enumerate(occ.input_labels, 1):
        if label in multi_file_labels:
            variable=variables[label]
            all_files=f'"\\${{{variable}_FILES[@]}}"'
            args=args.replace(f"{{input{idx}}}",all_files)
            if len(occ.input_labels)==1:
                args=args.replace("{inputs}",all_files).replace("{input}",all_files)
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",label):
                for member in range(1,multi_file_counts[label]+1):args=args.replace(f"{{{label}_{member}}}",f'"\\${{{variable}_FILES[{member-1}]}}"')
                args=args.replace(f"{{{label}}}",all_files)
            continue
        replacement = f'"\\${variables[label]}"'
        args = args.replace(f"{{input{idx}}}", replacement)
        if len(occ.input_labels) == 1:
            args = args.replace("{input}", replacement)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", label):
            args = args.replace(f"{{{label}}}", replacement)
    return args


def _publish_dir_literal(
    pdef: ProgramDef,
    out_def: DataDef,
    convert_windows: bool,
) -> str:
    """Return a Groovy expression for publishDir for this output data word."""
    custom = (out_def.publish_directory or "").strip()
    if not custom:
        subdir = validate_relative_subdirectory(pdef.normalized_publish_dir(),"Program publish subdirectory")
        subdir = subdir.replace("$", "\\$").replace('"', '\\"')
        return f'"${{params.outdir}}/{subdir}"'

    runtime = windows_path_to_wsl(custom) if convert_windows else custom
    runtime = runtime.replace("\\", "/")

    if runtime.startswith("/") or re.match(r"^[A-Za-z]:/", runtime) or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", runtime):
        return _groovy_quote(runtime)

    safe = validate_relative_subdirectory(runtime,"Published output folder").replace("$", "\\$").replace('"', '\\"')
    return f'"${{projectDir}}/{safe}"'


def _render_process(
    occ: ProgramOccurrence,
    pdef: ProgramDef,
    out_def: DataDef,
    parsed: ParsedGrid,
    data_defs: dict[str, DataDef],
    convert_windows: bool,
    cache_enabled: bool,
) -> str:
    pname = _process_name(occ, pdef)
    max_forks = f"    maxForks {pdef.max_forks}\n" if pdef.max_forks > 0 else ""
    cache_value="true" if cache_enabled else "false"
    additional_outputs = parse_additional_outputs(pdef.additional_outputs)
    input_assets = parse_additional_inputs(pdef.additional_inputs)
    shared_assets = checked_shared_resources(pdef,parsed,data_defs)
    extra_output_exprs = [
        _output_expr(DataDef(out_def.label,output_template=template),pdef,"group_id" if occ.barrier=="WASG" else "lineage1","group_id" if occ.barrier=="WASG" else "join_id" if occ.barrier=="WASJ" else "sample_id")
        for template in additional_outputs
    ]
    extra_output_lines = "".join(f'    path("{expr}"), emit: auxiliary_{i}\n' for i,expr in enumerate(extra_output_exprs,2))
    extra_file_assignments = "".join(f'    OUTPUT_FILE{i}="{expr}"\n' for i,expr in enumerate(extra_output_exprs,2))
    extra_file_checks = "".join(f'    test -f "\\$OUTPUT_FILE{i}"\n' for i in range(2,len(extra_output_exprs)+2))
    extra_stub_touches = "".join(f'    touch "{expr}"\n' for expr in extra_output_exprs)

    if occ.barrier == "WASG":
        label = occ.input_labels[0]
        lineage_var = "group_id"
        out_expr = _output_expr(out_def, pdef, lineage_var, "group_id")
        args = _replace_input_placeholders(_protect_literal_braces(pdef.arguments_template),occ,{})
        args = args.replace("{output}", '"\\$OUTPUT_FILE"').replace("{output1}", '"\\$OUTPUT_FILE"').replace("{sample}", '"\\$SAMPLE_ID"').replace("{cpus}", '"\\$TASK_CPUS"')
        for i in range(2,len(extra_output_exprs)+2):args=args.replace(f"{{output{i}}}",f'"\\$OUTPUT_FILE{i}"')
        args = _restore_literal_braces(args)
        return f'''process {pname} {{
    cache {cache_value}
    tag "${{group_id}}"
    cpus {pdef.cpus}
    memory {_groovy_quote(pdef.memory)}
    time {_groovy_quote(pdef.time)}
{max_forks}    publishDir {_publish_dir_literal(pdef, out_def, convert_windows)},
        mode: params.publish_mode,
        overwrite: false

    input:
    tuple val(group_id), val(member_ids), path(input_files, stageAs: 'netdash_group_inputs??/*')

    output:
    tuple val(group_id), path("{out_expr}"), val(group_id), val("{{}}"), emit: output_files
{extra_output_lines}
    script:
    group_manifest_text = (0..<member_ids.size()).collect {{ i -> "${{member_ids[i]}}\\t${{input_files[i]}}" }}.join('\\n')
    """
    set -euo pipefail
    SAMPLE_ID="${{group_id}}"
    TASK_CPUS="${{task.cpus}}"
    GROUP_MANIFEST="netdash_group_inputs.tsv"
    OUTPUT_FILE="{out_expr}"
{extra_file_assignments}    cat > "\\$GROUP_MANIFEST" <<'NETDASH_GROUP_EOF'
sample_id\tfile
${{group_manifest_text}}
NETDASH_GROUP_EOF
    mapfile -t GROUP_INPUTS < <(tail -n +2 "\\$GROUP_MANIFEST" | cut -f2-)

    echo "Program      : {_bash_double_quote_text(pdef.normalized_name())} (ID {pdef.program_id})"
    echo "Barrier      : WASG"
    echo "Group size   : ${{member_ids.size()}}"
    echo "Group list   : \\$GROUP_MANIFEST"
    echo "Output       : \\$OUTPUT_FILE"
    {_render_task_command(pdef, args, convert_windows)}
    test -f "\\$OUTPUT_FILE"
{extra_file_checks}    """

    stub:
    """
    touch "{out_expr}"
{extra_stub_touches}    """
}}'''

    shared_labels = [label for label in occ.input_labels if is_shared_root(label, parsed, data_defs)]
    sample_labels = [label for label in occ.input_labels if label not in shared_labels]
    multi_file_counts={
        label:int(data_defs[label].expected_files_per_sample)
        for label in sample_labels
        if label in parsed.root_data and data_defs.get(label,DataDef(label)).group_files_by_sample
    }
    multi_file_labels=set(multi_file_counts)
    variables: dict[str, str] = {}

    input_lines: list[str] = []
    setup_lines: list[str] = []
    echo_lines: list[str] = []

    if occ.barrier == "WASJ":
        tuple_parts = ["val(join_id)"]
        sample_idx = 0
        for label in sample_labels:
            sample_idx += 1
            variables[label] = f"INPUT{occ.input_labels.index(label)+1}"
            tuple_parts += [
                f"val(source_sample_id{sample_idx})",
                f"path(sample_input{sample_idx}, stageAs: 'netdash_input{occ.input_labels.index(label)+1}/*')",
                f"val(lineage{sample_idx})",
                f"val(meta_json{sample_idx})",
            ]
        input_lines.append("    tuple " + ", ".join(tuple_parts))
        for label in shared_labels:
            pos = occ.input_labels.index(label) + 1
            variables[label] = f"INPUT{pos}"
            input_lines.append(f"    path(shared_input{pos}, stageAs: 'netdash_input{pos}/*')")

        setup_lines += ['    SAMPLE_ID="${join_id}"', '    TASK_CPUS="${task.cpus}"']
        sample_idx = 0
        for label in sample_labels:
            sample_idx += 1
            pos = occ.input_labels.index(label) + 1
            if label in multi_file_labels:
                setup_lines.append(f'    INPUT{pos}_FILES=( netdash_input{pos}/* )')
                setup_lines.append(f'    INPUT{pos}="\\${{INPUT{pos}_FILES[0]}}"')
            else:setup_lines.append(f'    INPUT{pos}="${{sample_input{sample_idx}}}"')
            if label in multi_file_labels:echo_lines.append(f'    echo "{_bash_double_quote_text(label):<12}: \\${{INPUT{pos}_FILES[*]}} ({multi_file_counts[label]} grouped files)"')
            else:echo_lines.append(f'    echo "{_bash_double_quote_text(label):<12}: \\$INPUT{pos}"')
        for label in shared_labels:
            pos = occ.input_labels.index(label) + 1
            setup_lines.append(f'    INPUT{pos}="${{shared_input{pos}}}"')
            echo_lines.append(f'    echo "{_bash_double_quote_text(label):<12}: \\$INPUT{pos} (shared)"')

        lineage_var = "lineage1"
        meta_var = "meta_json1"
        sample_output_var = "join_id"

    else:

        label = occ.input_labels[0]
        variables[label] = "INPUT1"
        path_binding="path(sample_input1, stageAs: 'netdash_input1/*')" if label in multi_file_labels else "path(sample_input1)"
        asset_input_fields=", ".join(f"path(asset_file{i})" for i,_ in enumerate(input_assets,1))
        input_lines.append(f"    tuple val(sample_id), {path_binding}, " + (asset_input_fields+", " if asset_input_fields else "")+"val(lineage1), val(meta_json1)")
        for i,(key,_asset_path) in enumerate(input_assets,1):
            setup_lines.append(f'    ASSET_{key}="${{asset_file{i}}}"')
            echo_lines.append(f'    echo "Resource {key:<12}: \\$ASSET_{key}"')
        setup_lines += ['    SAMPLE_ID="${sample_id}"']
        if label in multi_file_labels:setup_lines += ['    INPUT1_FILES=( netdash_input1/* )','    INPUT1="\\${INPUT1_FILES[0]}"']
        else:setup_lines += ['    INPUT1="${sample_input1}"']
        setup_lines += ['    TASK_CPUS="${task.cpus}"']
        echo_lines.append(f'    echo "{_bash_double_quote_text(label):<12}: \\$INPUT1"')
        lineage_var = "lineage1"
        meta_var = "meta_json1"
        sample_output_var = "sample_id"

    for idx,(key,word) in enumerate(shared_assets,1):
        input_lines.append(f"    path(shared_asset{idx})")
        setup_lines.append(f'    ASSET_{key}="${{shared_asset{idx}}}"')
        echo_lines.append(f'    echo "Shared {key:<12}: \\$ASSET_{key} ({word})"')

    out_expr = _output_expr(out_def, pdef, lineage_var, sample_output_var)
    args = _replace_input_placeholders(_protect_literal_braces(pdef.arguments_template),occ,variables,multi_file_counts)
    args = args.replace("{output}", '"\\$OUTPUT_FILE"').replace("{output1}", '"\\$OUTPUT_FILE"').replace("{sample}", '"\\$SAMPLE_ID"').replace("{cpus}", '"\\$TASK_CPUS"')
    for i in range(2,len(extra_output_exprs)+2):args=args.replace(f"{{output{i}}}",f'"\\$OUTPUT_FILE{i}"')
    for key,_path in input_assets+shared_assets:args=args.replace(f"{{{key}}}",f'"\\$ASSET_{key}"')
    args = _restore_literal_braces(args)

    return f'''process {pname} {{
    cache {cache_value}
    tag "${{{sample_output_var}}}"
    cpus {pdef.cpus}
    memory {_groovy_quote(pdef.memory)}
    time {_groovy_quote(pdef.time)}
{max_forks}    publishDir {_publish_dir_literal(pdef, out_def, convert_windows)},
        mode: params.publish_mode,
        overwrite: false

    input:
{chr(10).join(input_lines)}

    output:
    tuple val({sample_output_var}), path("{out_expr}"), val({lineage_var}), val({meta_var}), emit: output_files
{extra_output_lines}
    script:
    """
    set -euo pipefail
{chr(10).join(setup_lines)}
    OUTPUT_FILE="{out_expr}"
{extra_file_assignments}    echo "Program      : {_bash_double_quote_text(pdef.normalized_name())} (ID {pdef.program_id})"
    echo "Barrier      : {occ.barrier}"
    echo "Sample/Join  : \\$SAMPLE_ID"
{chr(10).join(echo_lines)}
    echo "Output       : \\$OUTPUT_FILE"
    {_render_task_command(pdef, args, convert_windows)}
    test -f "\\$OUTPUT_FILE"
{extra_file_checks}    """

    stub:
    """
    touch "{out_expr}"
{extra_stub_touches}    """
}}'''


def _was_release_workflow(occ: ProgramOccurrence, parsed: ParsedGrid, data_defs: dict[str, DataDef]) -> tuple[list[str], str]:
    """Wait for every WAS stream to close, then re-emit the primary stream item-by-item.

    Each collected stream becomes exactly one tuple keyed by a constant barrier ID.
    Keyed joins therefore act as a deterministic global gate without merging the
    biological sample records themselves. After the gate opens, only the primary
    stream's collected rows are flattened back into individual sample tuples.
    """
    lines: list[str] = []
    primary = occ.primary_label
    if is_shared_root(primary, parsed, data_defs):
        raise NetDashError("WAS primary stream must be per-sample, not a shared resource.")

    gate_key = sanitize_identifier(occ.barrier_id)
    primary_gate = f"was_primary_{gate_key}"
    lines += [
        f"    {primary_gate} = {_channel_name(primary)}",
        "        .collect(flat: false)",
        f"        .map {{ rows -> tuple('{gate_key}', rows) }}",
        "",
    ]
    gate = primary_gate
    dep_number = 0
    for label in occ.wait_labels:
        if label == primary or is_shared_root(label, parsed, data_defs):
            continue
        dep_number += 1
        dep_gate = f"was_dep_{gate_key}_{dep_number}"
        lines += [
            f"    {dep_gate} = {_channel_name(label)}",
            "        .collect(flat: false)",
            f"        .map {{ rows -> tuple('{gate_key}', true) }}",
            "",
        ]
        joined = f"was_gate_{gate_key}_{dep_number}"
        lines += [
            f"    {joined} = {gate}.join(",
            f"        {dep_gate},",
            "        by: 0,",
            "        failOnDuplicate: true,",
            "        failOnMismatch: true",
            "    )",
            "",
        ]
        gate = joined

    release = f"was_release_{gate_key}"
    lines += [
        f"    {release} = {gate}",
        "        .map { values -> values[1] }",
        "        .flatMap { rows -> rows }",
        "",
    ]
    return lines, release


def render_main_nf(
    parsed: ParsedGrid,
    programs: dict[str, ProgramDef],
    data_defs: dict[str, DataDef],
    wasj_configs: dict[str, WASJConfig] | None = None,
    results_directory: str = "results",
    publish_mode: str = "link",
    convert_windows_paths: bool = True,
    cache_enabled: bool = False,
) -> str:
    wasj_configs = wasj_configs or {}
    if publish_mode not in ("link", "copy"):
        raise NetDashError("publish_mode must be link or copy")
    results_directory = (results_directory or "results").strip().replace("\\", "/")
    if (
        not results_directory
        or results_directory.startswith("/")
        or re.match(r"^[A-Za-z]:/", results_directory)
        or any(part == ".." for part in results_directory.split("/"))
        or any(ch in results_directory for ch in ('"', "`", "$", "\r", "\n", "\t"))
    ):
        raise NetDashError("results_directory must be a safe relative directory inside the generated project")
    errors = [x for x in validate_definitions(parsed, programs, data_defs, wasj_configs, False) if x.level == "ERROR"]
    if errors:
        raise NetDashError("\n".join(map(str, errors)))

    ordered = topological_occurrences(parsed)
    processes = "\n\n\n".join(
        _render_process(occ,programs[occ.program_id],data_defs[occ.output_label],parsed,data_defs,convert_windows_paths,cache_enabled)
        for occ in ordered
    )

    workflow: list[str] = [
        "    manifest_ch = Channel",
        "        .fromPath(params.input_manifest, checkIfExists: true)",
        "        .splitCsv(header: true, sep: '\\t')",
        "",
    ]

    for label in sorted(parsed.root_data):
        channel = _channel_name(label)
        if is_shared_root(label, parsed, data_defs):
            workflow += [
                f"    {channel} = manifest_ch",
                f"        .filter {{ row -> row.data_id.toString() == {_groovy_quote(label)} }}",
                "        .map { row -> file(row.input_path.toString(), checkIfExists: true) }",
                "        .first()",
                "",
            ]
        else:
            workflow += [
                f"    {channel} = manifest_ch",
                f"        .filter {{ row -> row.data_id.toString() == {_groovy_quote(label)} }}",
                "        .map { row ->",
                "            tuple(",
                "                row.sample_id.toString(),",
                "                file(row.input_path.toString(), checkIfExists: true),",
                "                row.lineage.toString(),",
                "                row.metadata_json.toString()",
                "            )",
                "        }",
            ]
            if data_defs.get(label,DataDef(label)).group_files_by_sample:
                workflow += [
                    "        .groupTuple(by: 0)",
                    "        .map { sample_id, input_files, lineages, metadata_values ->",
                    "            def unique_lineages = lineages.unique()",
                    "            if( unique_lineages.size() != 1 ) throw new IllegalStateException(\"Grouped files have inconsistent lineage for ${sample_id}\")",
                    "            tuple(sample_id, input_files.sort { it.name }, unique_lineages[0], metadata_values[0])",
                    "        }",
                ]
            workflow.append("")

    for occ in ordered:
        pdef = programs[occ.program_id]
        pname = _process_name(occ, pdef)

        if occ.barrier == "NONE":
            source_label = occ.input_labels[0]
            source = _channel_name(source_label)
            if is_shared_root(source_label, parsed, data_defs):



                adapter = f"shared_record_{sanitize_identifier(occ.occurrence_id)}"
                record_id = sanitize_filename_component(source_label)
                workflow += [
                    f"    {adapter} = {source}.map {{ input_file ->",
                    f"        tuple({_groovy_quote(record_id)}, input_file, {_groovy_quote(record_id)}, {_groovy_quote('{}')})",
                    "    }",
                    "",
                ]
                call_args = [adapter]
            else:
                call_args = [source]

        elif occ.barrier == "WAS":
            barrier_lines, release = _was_release_workflow(occ, parsed, data_defs)
            workflow += barrier_lines
            call_args = [release]

        elif occ.barrier == "WASG":
            source = _channel_name(occ.input_labels[0])
            grouped = f"wasg_{sanitize_identifier(occ.barrier_id)}"
            workflow += [
                f"    {grouped} = {source}",
                "        .collect(flat: false)",
                "        .map { rows ->",
                "            def sorted_rows = rows.sort { a, b -> a[0].toString() <=> b[0].toString() }",
                "            def flattened_ids = sorted_rows.collectMany { row -> row[1] instanceof Collection ? row[1].collect { row[0] } : [row[0]] }",
                "            def flattened_files = sorted_rows.collectMany { row -> row[1] instanceof Collection ? row[1] : [row[1]] }",
                "            tuple(",
                f"                'GROUP_{sanitize_filename_component(occ.input_labels[0])}',",
                "                flattened_ids,",
                "                flattened_files",
                "            )",
                "        }",
                "",
            ]
            call_args = [grouped]

        else:
            cfg = wasj_configs[occ.barrier_id]
            sample_labels = [label for label in occ.input_labels if not is_shared_root(label, parsed, data_defs)]
            shared_labels = [label for label in occ.input_labels if is_shared_root(label, parsed, data_defs)]
            keyed_channels: list[str] = []
            meta_key = f"{occ.barrier_id}::{cfg.join_key}"
            for idx, label in enumerate(sample_labels, 1):
                waited = f"wasj_wait_{sanitize_identifier(occ.barrier_id)}_{idx}"
                keyed = f"wasj_key_{sanitize_identifier(occ.barrier_id)}_{idx}"
                workflow += [
                    f"    {waited} = {_channel_name(label)}",
                    "        .collect(flat: false)",
                    "        .flatMap { rows -> rows }",
                    "",
                    f"    {keyed} = {waited}.map {{ sample_id, input_file, lineage, metadata_json ->",
                    "        def meta = new groovy.json.JsonSlurper().parseText(metadata_json)",
                    f"        def join_value = meta[{_groovy_quote(meta_key)}]",
                    "        if( join_value == null || join_value.toString() == '' ) "
                    f"throw new IllegalStateException({_groovy_quote(f'Missing WASJ Join key {cfg.join_key} for {label}')})",
                    "        tuple(join_value.toString(), sample_id, input_file, lineage, metadata_json)",
                    "    }",
                    "",
                ]
                keyed_channels.append(keyed)

            joined = keyed_channels[0]
            for idx, right in enumerate(keyed_channels[1:], 2):
                out = f"wasj_join_{sanitize_identifier(occ.barrier_id)}_{idx}"
                workflow += [
                    f"    {out} = {joined}.join(",
                    f"        {right},",
                    "        by: 0,",
                    "        failOnDuplicate: true,",
                    "        failOnMismatch: true",
                    "    )",
                    "",
                ]
                joined = out
            call_args = [joined] + [_channel_name(label) for label in shared_labels]

        input_assets=parse_additional_inputs(pdef.additional_inputs)
        if input_assets:
            prepared=f"resources_{sanitize_identifier(occ.occurrence_id)}"
            mapped_assets=[_asset_groovy_path_template(path_template,convert_windows_paths) for _name,path_template in input_assets]
            workflow += [
                f"    {prepared} = {call_args[0]}.map {{ sample_id, input_file, lineage, metadata_json ->",
                "        tuple(sample_id, input_file, " + ", ".join(mapped_assets) + ", lineage, metadata_json)",
                "    }",
                "",
            ]
            call_args=[prepared]
        call_args += [_channel_name(word) for _alias,word in checked_shared_resources(pdef,parsed,data_defs)]
        workflow += [
            f"    {pname}({', '.join(call_args)})",
            f"    {_channel_name(occ.output_label)} = {pname}.out.output_files",
            "",
        ]

    consumed = {label for occ in parsed.occurrences for label in occ.dependency_labels()}
    for label in sorted(parsed.data_labels - consumed):
        if label in parsed.root_data and is_shared_root(label, parsed, data_defs):
            continue
        workflow.append(f'    {_channel_name(label)}.view {{ item -> "FINAL {label}: ${{item[0]}} -> ${{item[1]}}" }}')

    return f'''nextflow.enable.dsl=2

params.input_manifest = "${{projectDir}}/input_manifest.tsv"
params.outdir = "${{projectDir}}/{results_directory}"
params.publish_mode = {_groovy_quote(publish_mode)}

{processes}

workflow {{
{chr(10).join(workflow)}
}}
'''


def _plain_tsv_field(value: object, column: str) -> str:
    text = str(value)
    if any(ch in text for ch in ("\t", "\r", "\n")):
        raise NetDashError(f"Manifest column {column!r} contains a tab or newline, which is not supported.")
    return text


def render_manifest_tsv(rows: list[dict[str, str]], convert_windows_paths: bool = True) -> str:



    headers = ["data_id", "sample_id", "input_path", "lineage", "metadata_json"]
    lines = ["\t".join(headers)]
    for row in rows:
        path = windows_path_to_wsl(row["input_path"]) if convert_windows_paths else row["input_path"]
        values = [row["data_id"], row["sample_id"], path, row["lineage"], row.get("metadata_json", "{}")]
        lines.append("\t".join(_plain_tsv_field(value, column) for value, column in zip(values, headers)))
    return "\n".join(lines) + "\n"


def render_definition_summary(
    parsed: ParsedGrid,
    programs: dict[str, ProgramDef],
    data_defs: dict[str, DataDef],
    wasj_configs: dict[str, WASJConfig] | None = None,
) -> str:
    wasj_configs = wasj_configs or {}
    lines = ["PROGRAMS", "--------"]
    for pid in sorted(parsed.program_ids, key=program_sort_key):
        p = programs.get(pid, ProgramDef(pid))
        uses = [o for o in parsed.occurrences if o.program_id == pid]
        lines += [
            f"{pid}: {p.normalized_name()}",
            f"    path: {p.program_path or '(undefined)'}",
            f"    arguments: {p.arguments_template}",
            f"    additional inputs: {p.additional_inputs or '(none)'}",
            f"    additional outputs: {p.additional_outputs or '(none)'}",
            f"    barriers: {', '.join(sorted({o.barrier for o in uses})) or 'none'}",
            "",
        ]
    lines += ["DATA", "----"]
    for label in sorted(parsed.data_labels):
        d = data_defs.get(label, DataDef(label))
        role = "ROOT INPUT" if label in parsed.root_data else "GENERATED"
        lines += [f"{label}: {role}", f"    description: {d.description or '(undefined)'}"]
        if role == "ROOT INPUT":
            lines += [
                f"    mode: {d.normalized_input_mode()}",
                f"    input: {d.input_pattern or '(undefined)'}",
                f"    extension filter: {d.input_extensions or '(all files)'}",
            ]
        else:
            lines.append(f"    output template: {d.normalized_output_template()}")
            lines.append(f"    published folder: {d.publish_directory or '(default results/<program>_out)'}")
        lines.append("")
    lines += ["WASJ CONFIGURATIONS", "-------------------"]
    for occ in parsed.wasj_occurrences():
        cfg = wasj_configs.get(occ.barrier_id, WASJConfig(occ.barrier_id))
        lines += [
            f"{occ.barrier_id}: inputs={', '.join(occ.input_labels)}",
            f"    sample table: {cfg.sample_table_path or '(undefined)'}",
            f"    join key: {cfg.join_key or '(undefined)'}",
            f"    difference keys: {', '.join(cfg.normalized_difference_keys()) or '(undefined)'}",
            f"    difference values: {json.dumps(cfg.role_values, ensure_ascii=False)}",
            "",
        ]
    return "\n".join(lines)


def render_routing_tsv(parsed: ParsedGrid, programs: dict[str, ProgramDef], data_defs: dict[str, DataDef]) -> str:
    stream=io.StringIO()
    writer=csv.writer(stream,delimiter="\t",lineterminator="\n")
    writer.writerow(["program_id","program_name","input_data_words","output_data_word","output_filename_template","published_folder","next_programs","shared_resource_aliases","auxiliary_output_templates"])
    for occ in topological_occurrences(parsed):
        p=programs[occ.program_id]
        output=data_defs[occ.output_label]
        consumers=[x for x in parsed.occurrences if occ.output_label in x.dependency_labels()]
        next_ids=",".join(f"{x.program_id}_{programs[x.program_id].normalized_name()}" for x in consumers)
        shared=";".join(f"{alias}={word}" for alias,word in parse_shared_resources(p.shared_resources))
        writer.writerow([occ.program_id,p.normalized_name(),",".join(occ.input_labels),occ.output_label,output.normalized_output_template(),output.publish_directory or p.normalized_publish_dir(),next_ids,shared,";".join(parse_additional_outputs(p.additional_outputs))])
    return stream.getvalue()


def save_project(
    output_directory: Path,
    grid: list[list[str]],
    parsed: ParsedGrid,
    programs: dict[str, ProgramDef],
    data_defs: dict[str, DataDef],
    wasj_configs: dict[str, WASJConfig],
    manifest_rows: list[dict[str, str]],
    results_directory: str = "results",
    publish_mode: str = "link",
    convert_windows_paths: bool = True,
    overwrite: bool = False,
    cache_enabled: bool = False,
) -> Path:
    preflight_issues=validate_manifest_runtime_identifiers(manifest_rows)
    preflight_issues+=validate_wasj_configs(parsed,data_defs,manifest_rows,wasj_configs)
    _expected_publications,publication_issues=calculate_expected_published_outputs(
        parsed,programs,data_defs,wasj_configs,manifest_rows,results_directory
    )
    preflight_issues+=publication_issues
    preflight_errors=[issue for issue in preflight_issues if issue.level=="ERROR"]
    if preflight_errors:
        raise NetDashError("Project generation preflight failed:\n"+"\n".join(map(str,preflight_errors)))
    output_directory = output_directory.expanduser()
    output_directory.mkdir(parents=True, exist_ok=True)
    targets = [
        output_directory / "main.nf",
        output_directory / "input_manifest.tsv",
        output_directory / "NextDash.tabtxt",
        output_directory / "DEFINITIONS.txt",
        output_directory / "ROUTING.tsv",
    ]
    if not overwrite:
        existing = [p for p in targets if p.exists()]
        if existing:
            raise NetDashError("Generated files already exist: " + ", ".join(p.name for p in existing))
    (output_directory / "main.nf").write_text(
        render_main_nf(parsed,programs,data_defs,wasj_configs,results_directory,publish_mode,convert_windows_paths,cache_enabled),
        encoding="utf-8",
    )
    (output_directory / "input_manifest.tsv").write_text(render_manifest_tsv(manifest_rows, convert_windows_paths), encoding="utf-8")
    write_tabtxt(output_directory / "NextDash.tabtxt", grid)
    (output_directory / "DEFINITIONS.txt").write_text(render_definition_summary(parsed, programs, data_defs, wasj_configs), encoding="utf-8")
    (output_directory / "ROUTING.tsv").write_text(render_routing_tsv(parsed, programs, data_defs),encoding="utf-8")
    return output_directory






import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk



C_BLANK = "#FFFFFF"
C_DATA = "#DCEEFF"
C_PROGRAM = "#EADCF8"
C_WAS = "#FFD166"
C_WASG = "#7BD389"
C_WASJ = "#FF8FA3"
C_SERIAL = "#DDF4E4"
C_SERIAL_EDGE = "#2E8B57"
C_ERROR = "#FADBD8"
C_WIRE = "#E5E7EB"
C_NOTE = "#F3F4F6"
C_SHARED = "#D6F3F0"
C_TEXT = "#1F2937"
C_EDGE = "#64748B"
C_BLUE = "#2563EB"
C_PURPLE = "#7C3AED"
C_RED = "#DC2626"
C_TEAL = "#0F766E"
C_WAS_EDGE = "#B77900"
C_WASG_EDGE = "#1B7F3A"
C_WASJ_EDGE = "#C9184A"
C_TAB_WORKFLOW = "#2F80ED"
C_TAB_DEFINITIONS = "#8E44AD"
C_TAB_WASJ = "#F2994A"
C_TAB_VALIDATION = "#219653"
C_TAB_GENERATE = "#C62828"
C_BUTTON_READ = "#6C5CE7"
C_BUTTON_SAVE = "#5B4BC4"
C_BUTTON_VALIDATE = "#1677C8"
C_BUTTON_GENERATE = "#168A45"


class SpreadsheetGrid(ttk.Frame):
    def __init__(self, parent, rows=8, cols=12, on_change=None, on_select=None):
        super().__init__(parent)
        self.rows = rows
        self.cols = cols
        self.on_change = on_change
        self.on_select = on_select
        self.vars: list[list[tk.StringVar]] = []
        self.entries: list[list[tk.Entry]] = []
        self.active_cell: tuple[int, int] | None = None

        self.canvas = tk.Canvas(self, background="#F7F9FC", highlightthickness=1)
        self.inner = ttk.Frame(self.canvas)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.hbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vbar.set, xscrollcommand=self.hbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._build([])

    def _cell_color(self, token: str) -> str:
        token = token.strip()
        if not token:
            return C_BLANK
        upper = token.upper()
        if upper == "WAS":
            return C_WAS
        if upper == "WASG":
            return C_WASG
        if upper == "WASJ":
            return C_WASJ
        kind = token_kind(token)
        if kind == "program":
            return C_PROGRAM
        if kind in ("wire_v", "wire_h"):
            return C_WIRE
        if kind == "note":
            return C_NOTE
        return C_DATA

    def _build(self, data):
        for child in self.inner.winfo_children():
            child.destroy()
        self.vars = []
        self.entries = []
        ttk.Label(self.inner, text="", width=5).grid(row=0, column=0, sticky="nsew")
        for c in range(self.cols):
            ttk.Label(self.inner, text=f"C{c+1}", anchor="center", width=27).grid(row=0, column=c+1, sticky="nsew", padx=1, pady=1)
        for r in range(self.rows):
            ttk.Label(self.inner, text=f"R{r+1}", anchor="center", width=5).grid(row=r+1, column=0, sticky="nsew", padx=1, pady=1)
            row_vars, row_entries = [], []
            for c in range(self.cols):
                value = data[r][c] if r < len(data) and c < len(data[r]) else ""
                var = tk.StringVar(value=value)
                ent = tk.Entry(self.inner, textvariable=var, width=27, justify="center", relief="solid", bd=1, fg=C_TEXT)
                ent.grid(row=r+1, column=c+1, sticky="nsew", padx=1, pady=1, ipady=6)
                ent.configure(bg=self._cell_color(value))
                ent.bind("<FocusIn>", lambda _e, rr=r, cc=c: self._activate(rr, cc))
                ent.bind("<KeyRelease>", lambda _e, rr=r, cc=c: self._edited(rr, cc))
                row_vars.append(var)
                row_entries.append(ent)
            self.vars.append(row_vars)
            self.entries.append(row_entries)

    def _activate(self, row, col):
        self.active_cell = (row, col)
        if self.on_select:
            self.on_select(row,col)

    def _edited(self, row, col):
        self.entries[row][col].configure(bg=self._cell_color(self.vars[row][col].get()))
        if self.on_change:
            self.on_change()

    def get_grid(self):
        return [[v.get().strip() for v in row] for row in self.vars]

    def set_grid(self, grid):
        grid = grid or [[""]]
        self.rows = max(6, len(grid))
        self.cols = max(8, max(len(row) for row in grid))
        self._build(grid)
        if self.on_change:
            self.on_change()

    def refresh_program_labels(self, programs: dict[str, ProgramDef]):
        for r, row in enumerate(self.vars):
            for c, variable in enumerate(row):
                value=variable.get().strip()
                if token_kind(value)!="program":
                    continue
                pid=program_token_id(value)
                expected=program_display_token(pid, programs.get(pid))
                if value!=expected:
                    variable.set(expected)

    def apply_data_flow_colors(self, serial_labels: set[str], shared_labels: set[str]):
        """Apply semantic flow colors after the application has parsed the grid."""
        for r, row in enumerate(self.vars):
            for c, var in enumerate(row):
                token = var.get().strip()
                if token_kind(token) != "data":
                    continue
                if token in shared_labels:
                    color = C_SHARED
                elif token in serial_labels:
                    color = C_SERIAL
                else:
                    color = C_DATA
                self.entries[r][c].configure(bg=color)

    def set_active_value(self, value):
        if not self.active_cell:
            messagebox.showinfo("Grid", "Click a spreadsheet cell first.", parent=self)
            return
        r, c = self.active_cell
        self.vars[r][c].set(value)
        self._edited(r, c)
        self.entries[r][c].focus_set()

    def add_row(self):
        data = self.get_grid(); self.rows += 1; self._build(data)
        if self.on_change: self.on_change()
    def remove_row(self):
        if self.rows <= 2: return
        data = self.get_grid()[:-1]; self.rows -= 1; self._build(data)
        if self.on_change: self.on_change()
    def add_col(self):
        data = self.get_grid(); self.cols += 1; self._build(data)
        if self.on_change: self.on_change()
    def remove_col(self):
        if self.cols <= 4: return
        data = [r[:-1] for r in self.get_grid()]; self.cols -= 1; self._build(data)
        if self.on_change: self.on_change()
    def clear(self):
        self._build([[""] * self.cols for _ in range(self.rows)])
    def trim_empty(self):
        self.set_grid(trim_grid(self.get_grid()))


class NetDashApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("NextDash v11 → Nextflow Generator")
        self.root.geometry("1720x1020")
        self.root.minsize(1250, 780)

        self.programs: dict[str, ProgramDef] = {}
        self.data_defs: dict[str, DataDef] = {}
        self.wasj_configs: dict[str, WASJConfig] = {}
        self.current_parsed = None
        self.manifest_rows: list[dict[str, str]] = []
        self.last_issues = []
        self.current_grid_path: Path | None = None
        self.current_wasj_id = ""
        self.sample_table_headers: list[str] = []
        self._loading_program_form = False
        self._loading_data_form = False
        self._tab2_sorts = {"program": (None, False), "data": (None, False)}
        self._program_multiline_widgets = {}

        self.output_dir_var = tk.StringVar(value=str(Path.cwd() / "generated_nextdash_pipeline"))
        self.results_var = tk.StringVar(value="results")
        self.publish_mode_var = tk.StringVar(value="copy")
        self.cache_enabled_var = tk.BooleanVar(value=False)
        self.convert_var = tk.BooleanVar(value=True)
        self.overwrite_var = tk.BooleanVar(value=False)
        self.cache_size_var = tk.StringVar(value="Cached task data: not scanned")
        self.status_var = tk.StringVar(value="Build the grid, define all numbers/data words, configure WASJ metadata, then validate.")
        self.tab_images: list[tk.PhotoImage] = []

        self._build_header()
        style = ttk.Style(root)
        style.configure("NetDash.TNotebook.Tab", padding=(10, 6), font=("TkDefaultFont", 9, "bold"))
        self.notebook = ttk.Notebook(root, style="NetDash.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._build_grid_tab()
        self._build_definitions_tab()
        self._build_wasj_tab()
        self._build_validation_tab()
        self._build_generate_tab()
        ttk.Label(root, textvariable=self.status_var, anchor="w", relief="sunken").pack(fill="x", padx=8, pady=(0, 8))

        self.sync_definitions()
        self.root.after(250, self.refresh_cache_size)
        self.root.bind("<Control-o>", lambda _e: self.load_grid())
        self.root.bind("<Control-s>", lambda _e: self.save_grid())




    def _add_colored_tab(self, tab, text: str, color: str):
        marker = tk.PhotoImage(width=14, height=14)
        marker.put(color, to=(0, 0, 14, 14))
        self.tab_images.append(marker)
        self.notebook.add(tab, text=text, image=marker, compound="left")

    def _colored_action_button(self, parent, text: str, command, color: str):
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=color,
            fg="white",
            activebackground=color,
            activeforeground="white",
            relief="flat",
            bd=0,
            padx=12,
            pady=6,
            cursor="hand2",
            font=("TkDefaultFont", 9, "bold"),
        )

    def _build_header(self):
        hdr = ttk.Frame(self.root, padding=8); hdr.pack(fill="x")
        ttk.Label(hdr, text="NextDash v11 — Workflow", font=("TkDefaultFont", 12, "bold")).pack(anchor="w")
        leg = tk.Frame(hdr, bg="#F7F9FC"); leg.pack(fill="x")
        for txt, bg in [
            ("ROOT DATA", C_DATA), ("SHARED RESOURCE", C_SHARED), ("PROGRAM", C_PROGRAM),
            ("WAS", C_WAS), ("WASG", C_WASG), ("WASJ", C_WASJ), ("WIRE | -", C_WIRE),
            ("NOTE #", C_NOTE), ("ERROR", C_ERROR),
        ]:
            tk.Label(leg, text=txt, bg=bg, fg=C_TEXT, padx=8, pady=3, relief="solid", bd=1).pack(side="left", padx=(0, 5))


    def _build_grid_tab(self):
        tab = ttk.Frame(self.notebook, padding=8); self._add_colored_tab(tab, "1 — Workflow spreadsheet", C_TAB_WORKFLOW)
        tab.rowconfigure(2, weight=1); tab.columnconfigure(0, weight=1)

        files = ttk.Frame(tab); files.grid(row=0, column=0, sticky="ew", pady=(0, 3))
        for text, cmd in [
            ("New", self.new_grid), ("Load .tabtxt…", self.load_grid), ("Save .tabtxt", self.save_grid), ("Save .tabtxt As…", self.save_grid_as),
            ("Load full project…", self.load_project), ("Save full project…", self.save_project_file),
        ]:
            ttk.Button(files, text=text, command=cmd).pack(side="left", padx=(0, 5))
        ttk.Label(files, text="Ctrl+O = load grid   Ctrl+S = save grid").pack(side="left", padx=8)

        tools = ttk.Frame(tab); tools.grid(row=1, column=0, sticky="ew", pady=(2, 5))
        for text, cmd in [
            ("+ Row", self.sheet_add_row_placeholder),
        ]:
            pass
        buttons = [
            ("+ Row", lambda: self.sheet.add_row()), ("- Row", lambda: self.sheet.remove_row()),
            ("+ Column", lambda: self.sheet.add_col()), ("- Column", lambda: self.sheet.remove_col()),
            ("Trim empty margins", self.trim_grid_margins),
            ("Insert WAS", lambda: self.sheet.set_active_value("WAS")),
            ("Insert WASG", lambda: self.sheet.set_active_value("WASG")),
            ("Insert WASJ", lambda: self.sheet.set_active_value("WASJ")),
            ("Insert |", lambda: self.sheet.set_active_value("|")),
            ("Insert -", lambda: self.sheet.set_active_value("-")),
            ("Insert # note", lambda: self.sheet.set_active_value("# note")),
            ("Examples…", self.example_menu), ("Sync definitions", self.sync_definitions), ("Show file routing…", self.show_routing_map),
        ]
        for text, cmd in buttons:
            ttk.Button(tools, text=text, command=cmd).pack(side="left", padx=(0, 4))

        self.cell_details=tk.StringVar(value="Select a workflow cell to see its input, output and destination.")
        self.sheet = SpreadsheetGrid(tab, rows=8, cols=12, on_change=self.grid_changed, on_select=self.describe_grid_cell)
        self.sheet.grid(row=2, column=0, sticky="nsew")
        ttk.Label(tab,textvariable=self.cell_details,anchor="w").grid(row=3,column=0,sticky="ew",pady=(5,0))

    def describe_grid_cell(self,row,col):
        try:
            cell=self.sheet.vars[row][col].get().strip()
            parsed,_=parse_grid(self.sheet.get_grid())
            kind=token_kind(cell)
            if kind=="program":
                pid=program_token_id(cell)
                p=self.programs.get(pid)
                occ=next((x for x in parsed.occurrences if x.row==row and x.col==col),None)
                if occ and p:
                    source=", ".join(occ.input_labels)
                    output=self.data_defs.get(occ.output_label,DataDef(occ.output_label)).normalized_output_template()
                    self.cell_details.set(f"{pid}_{p.normalized_name()} | Input: {source} | Output: {occ.output_label} → {output}")
                else:self.cell_details.set(f"Program {pid}")
            elif kind=="data":
                d=self.data_defs.get(cell,DataDef(cell))
                producer=parsed.producer_by_data.get(cell)
                produced=f"{producer.program_id}_{self.programs[producer.program_id].normalized_name()}" if producer and producer.program_id in self.programs else "ROOT"
                destinations=", ".join(f"{occ.program_id}_{self.programs[occ.program_id].normalized_name()}" for occ in parsed.occurrences if cell in occ.dependency_labels()) or "FINAL"
                file=d.input_pattern if cell in parsed.root_data else d.normalized_output_template()
                self.cell_details.set(f"{cell} | {file} | From: {produced} | To: {destinations}")
            else:self.cell_details.set(cell)
        except Exception:
            self.cell_details.set("Select an input or output data word.")

    def sheet_add_row_placeholder(self):
        pass

    def _build_definitions_tab(self):
        tab = ttk.Frame(self.notebook, padding=8); self._add_colored_tab(tab, "2 — Program + Data definitions", C_TAB_DEFINITIONS)
        tab.rowconfigure(1, weight=1); tab.columnconfigure(0, weight=1)

        tools = ttk.LabelFrame(tab, text="Read definitions from the workflow spreadsheet", padding=7)
        tools.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        self._colored_action_button(
            tools,
            "Read Programs + Data from Workflow Spreadsheet",
            self.read_variables_from_workflow,
            C_BUTTON_READ,
        ).pack(side="left")

        pane = ttk.Panedwindow(tab, orient="horizontal"); pane.grid(row=1, column=0, sticky="nsew")
        left = ttk.LabelFrame(pane, text="Program IDs", padding=6)
        right = ttk.LabelFrame(pane, text="Data words", padding=6)
        pane.add(left, weight=3); pane.add(right, weight=2)
        self._build_program_editor(left); self._build_data_editor(right)

    def _build_program_editor(self, parent):
        parent.rowconfigure(1, weight=0)
        parent.rowconfigure(2, weight=1)
        parent.columnconfigure(0, weight=1)
        self.program_tree = ttk.Treeview(parent, columns=("id", "name", "path", "usage"), show="headings", height=7)
        for key, title, width in [("id", "ID", 50), ("name", "Name", 180), ("path", "Program/script", 310), ("usage", "Grid usage", 125)]:
            self.program_tree.heading(key, text=title, command=lambda k=key: self._sort_tab2_tree("program", k))
            self.program_tree.column(key, width=width, minwidth=45, stretch=key in ("name", "path"))
        self.program_tree.grid(row=1, column=0, sticky="ew", pady=(5, 7))
        self.program_tree.bind("<<TreeviewSelect>>", self.load_program)
        self.program_tree.bind("<Double-1>", self.on_program_double_click)
        self.program_tree.tag_configure("missing", background=C_ERROR)
        self.program_tree.tag_configure("ok", background=C_PROGRAM)

        body = ttk.Frame(parent)
        body.grid(row=2, column=0, sticky="nsew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        scroll_canvas = tk.Canvas(body, highlightthickness=0, borderwidth=0)
        scroll_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=scroll_canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        scroll_canvas.configure(yscrollcommand=scrollbar.set)
        interior = ttk.Frame(scroll_canvas, padding=(0, 3, 6, 5))
        window_id = scroll_canvas.create_window((0, 0), window=interior, anchor="nw")
        interior.bind("<Configure>", lambda _e: scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all")))
        scroll_canvas.bind("<Configure>", lambda e: scroll_canvas.itemconfigure(window_id, width=e.width))
        self.program_editor_canvas = scroll_canvas

        form = ttk.Frame(interior)
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)
        form.columnconfigure(2, weight=0)
        self.p_id = tk.StringVar(); self.p_name = tk.StringVar(); self.p_path = tk.StringVar(); self.p_type = tk.StringVar(value="Linux executable")
        self.p_args = tk.StringVar(value="-i {input} -o {output}"); self.p_cpus = tk.StringVar(value="1"); self.p_mem = tk.StringVar(value="1 GB")
        self.p_time = tk.StringVar(value="24h"); self.p_forks = tk.StringVar(value="0"); self.p_outdir = tk.StringVar()
        self.p_extra_inputs = tk.StringVar(); self.p_extra_outputs = tk.StringVar(); self.p_shared_resources=tk.StringVar()
        for var in (self.p_name,self.p_path,self.p_type,self.p_args,self.p_cpus,self.p_mem,self.p_time,self.p_forks,self.p_outdir,self.p_extra_inputs,self.p_extra_outputs,self.p_shared_resources):
            var.trace_add("write", self._auto_save_program)

        fields = [
            ("Program ID", self.p_id), ("Name", self.p_name), ("Program/script", self.p_path),
            ("CPUs", self.p_cpus), ("Memory", self.p_mem), ("Time", self.p_time),
            ("maxForks", self.p_forks), ("Checkpoint folder", self.p_outdir),
        ]
        for row, (label, var) in enumerate(fields):
            ttk.Label(form, text=label + ":").grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(form, textvariable=var, state="readonly" if label == "Program ID" else "normal").grid(row=row, column=1, sticky="ew", padx=(6, 4), pady=2)
            if label == "Program/script":
                actions = ttk.Frame(form)
                actions.grid(row=row, column=2, sticky="w", pady=2)
                ttk.Button(actions, text="Browse…", command=self.browse_program).pack(side="left")
                ttk.Button(actions, text="CLI help…", command=self.read_selected_program_cli_help).pack(side="left", padx=(4,0))
        row = len(fields)
        ttk.Label(form, text="Type:").grid(row=row, column=0, sticky="w", pady=2)
        ttk.Combobox(form, textvariable=self.p_type, values=PROGRAM_TYPES, state="readonly").grid(row=row, column=1, sticky="ew", padx=(6, 4), pady=2)
        row += 1
        self._add_program_multiline_editor(form, row, "Arguments / Inline Bash", "arguments", self.p_args, 6)
        row += 1
        self._add_program_multiline_editor(form, row, "Shared resources (ALIAS=DATA_WORD)", "shared", self.p_shared_resources, 4)
        row += 1
        self._add_program_multiline_editor(form, row, "Additional input files", "inputs", self.p_extra_inputs, 4)
        row += 1
        self._add_program_multiline_editor(form, row, "Additional output files", "outputs", self.p_extra_outputs, 3)
        routing=ttk.LabelFrame(interior,text="Input / output routing",padding=5)
        routing.pack(fill="x",pady=(8,4))
        self.routing_tree=ttk.Treeview(routing,columns=("kind","word","placeholder","file","destination"),show="headings",height=8)
        for key,title,width in [("kind","Role",90),("word","Data / program",150),("placeholder","Placeholder",105),("file","Filename / source",330),("destination","Sent to / location",330)]:
            self.routing_tree.heading(key,text=title)
            self.routing_tree.column(key,width=width,minwidth=70,stretch=key in ("file","destination"))
        self.routing_tree.pack(fill="x")
        self.routing_tree.bind("<Double-1>",self._routing_double_click)

    def _add_program_multiline_editor(self, form, row, title, key, variable, height):
        cell = ttk.Frame(form)
        cell.grid(row=row, column=0, sticky="nw", pady=(7, 3))
        ttk.Label(cell, text=title + ":").pack(anchor="w")
        ttk.Button(cell, text="Expand editor…", command=lambda k=key: self.edit_program_multiline(k)).pack(anchor="w", pady=(3, 0))
        container = ttk.Frame(form)
        container.grid(row=row, column=1, columnspan=2, sticky="nsew", padx=(6, 4), pady=(5, 3))
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        widget = tk.Text(container, height=height, width=54, wrap="word", undo=True, font=("Consolas", 10), relief="solid", borderwidth=1)
        widget.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(container, orient="vertical", command=widget.yview)
        bar.grid(row=0, column=1, sticky="ns")
        widget.configure(yscrollcommand=bar.set)
        self._program_multiline_widgets[key] = (widget, variable)
        widget.bind("<<Modified>>", lambda _e, k=key: self._program_multiline_changed(k))
        widget.edit_modified(False)

    def _program_multiline_changed(self, key):
        widget, variable = self._program_multiline_widgets[key]
        if not widget.edit_modified():
            return
        widget.edit_modified(False)
        if self._loading_program_form:
            return
        value = widget.get("1.0", "end-1c")
        if variable.get() != value:
            variable.set(value)

    def _refresh_program_multiline(self):
        for key, (widget, variable) in self._program_multiline_widgets.items():
            value = variable.get()
            if key in ("inputs", "outputs", "shared"):
                value = value.replace(";", "\n")
            widget.delete("1.0", "end")
            widget.insert("1.0", value)
            widget.edit_modified(False)

    def edit_program_multiline(self, key):
        if not self.p_id.get().strip():
            messagebox.showinfo("Program editor", "Select a program first.", parent=self.root)
            return
        title = {"arguments": "Arguments / Inline Bash", "inputs": "Additional input files", "outputs": "Additional output files", "shared": "Shared resources"}[key]
        widget, variable = self._program_multiline_widgets[key]
        win = tk.Toplevel(self.root)
        win.title(f"Program {self.p_id.get()} — {title}")
        win.geometry("1100x670")
        win.transient(self.root)
        holder = ttk.Frame(win, padding=10)
        holder.pack(fill="both", expand=True)
        frame = ttk.Frame(holder)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        edit = tk.Text(frame, wrap="none", undo=True, font=("Consolas", 11))
        edit.grid(row=0, column=0, sticky="nsew")
        ys = ttk.Scrollbar(frame, orient="vertical", command=edit.yview)
        ys.grid(row=0, column=1, sticky="ns")
        xs = ttk.Scrollbar(frame, orient="horizontal", command=edit.xview)
        xs.grid(row=1, column=0, sticky="ew")
        edit.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        edit.insert("1.0", widget.get("1.0", "end-1c"))
        buttons = ttk.Frame(holder)
        buttons.pack(fill="x", pady=(8, 0))
        def commit():
            value = edit.get("1.0", "end-1c").strip()
            self._loading_program_form = True
            try:
                if key == "arguments" and self.p_type.get() == "Inline Bash":
                    self.p_path.set("/bin/bash")
                variable.set(value)
                widget.delete("1.0", "end")
                widget.insert("1.0", value)
                widget.edit_modified(False)
            finally:
                self._loading_program_form = False
            self.save_program(silent=False)
            win.destroy()
        ttk.Button(buttons, text="Save", command=commit).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=win.destroy).pack(side="right", padx=(0,8))
        edit.focus_set()

    def _sort_tab2_tree(self, table, column):
        previous, descending = self._tab2_sorts[table]
        self._tab2_sorts[table] = (column, not descending if previous == column else False)
        self._apply_tab2_sort(table)

    def _apply_tab2_sort(self, table):
        tree = self.program_tree if table == "program" else self.data_tree
        selected, descending = self._tab2_sorts[table]
        titles = {"program": {"id":"ID","name":"Name","path":"Program/script","usage":"Grid usage"},
                  "data": {"label":"Data word","role":"Data type","mode":"Input mode","definition":"Definition / input","producer":"Produced by","consumer":"Used by"}}[table]
        for column, label in titles.items():
            suffix = (" ▼" if descending else " ▲") if column == selected else ""
            tree.heading(column, text=label + suffix, command=lambda k=column, t=table: self._sort_tab2_tree(t,k))
        if not selected:
            return
        def sort_key(iid):
            value = str(tree.set(iid, selected)).strip()
            if table == "program" and selected == "id":
                return program_sort_key(value)
            return value.casefold()
        items = sorted(tree.get_children(""), key=sort_key, reverse=descending)
        for index, iid in enumerate(items):
            tree.move(iid, "", index)

    def _build_data_editor(self, parent):
        parent.rowconfigure(1, weight=1); parent.columnconfigure(0, weight=1)
        self.data_tree = ttk.Treeview(parent, columns=("label", "role", "mode", "definition", "producer", "consumer"), show="headings", height=10)
        for key, title, width in [("label", "Data word", 100), ("role", "Data type", 90), ("mode", "Input mode", 130), ("definition", "Definition / input", 250), ("producer", "Produced by", 150), ("consumer", "Used by", 150)]:
            self.data_tree.heading(key, text=title, command=lambda k=key: self._sort_tab2_tree("data", k)); self.data_tree.column(key, width=width, stretch=key == "definition")
        self.data_tree.grid(row=1, column=0, sticky="nsew", pady=(5, 7)); self.data_tree.bind("<<TreeviewSelect>>", self.load_data); self.data_tree.bind("<Double-1>", self.on_data_double_click)
        for tag, color in [("missing", C_ERROR), ("root", C_DATA), ("shared", C_SHARED), ("parallel", C_DATA), ("serial", C_SERIAL)]:
            self.data_tree.tag_configure(tag, background=color)

        form = ttk.Frame(parent); form.grid(row=2, column=0, sticky="ew"); form.columnconfigure(1, weight=1)
        self.d_label = tk.StringVar(); self.d_role = tk.StringVar(); self.d_mode = tk.StringVar(value=DATA_INPUT_MODES[0])
        self.d_desc = tk.StringVar(); self.d_input = tk.StringVar(); self.d_regex = tk.StringVar(); self.d_output = tk.StringVar()
        self.d_extensions = tk.StringVar(); self.d_publish = tk.StringVar(); self.d_local_scan = tk.StringVar();self.d_multifile=tk.BooleanVar(value=False);self.d_group_size=tk.StringVar(value="2")
        for var in (self.d_mode,self.d_desc,self.d_input,self.d_regex,self.d_output,self.d_extensions,self.d_publish,self.d_local_scan,self.d_multifile,self.d_group_size):
            var.trace_add("write",self._auto_save_data)
        ttk.Label(form, text="Data word:").grid(row=0, column=0, sticky="w", pady=2); ttk.Entry(form, textvariable=self.d_label, state="readonly").grid(row=0, column=1, sticky="ew", padx=(6,4), pady=2)
        ttk.Label(form, text="Detected data type:").grid(row=1, column=0, sticky="w", pady=2); ttk.Entry(form, textvariable=self.d_role, state="readonly").grid(row=1, column=1, sticky="ew", padx=(6,4), pady=2)
        ttk.Label(form, text="Root input mode:").grid(row=2, column=0, sticky="w", pady=2); ttk.Combobox(form, textvariable=self.d_mode, values=DATA_INPUT_MODES, state="readonly").grid(row=2, column=1, sticky="ew", padx=(6,4), pady=2)
        ttk.Label(form, text="Description:").grid(row=3, column=0, sticky="w", pady=2)
        ttk.Entry(form, textvariable=self.d_desc).grid(row=3, column=1, sticky="ew", padx=(6,4), pady=2)

        ttk.Label(form, text="Input folder/file/glob:").grid(row=4, column=0, sticky="w", pady=2)
        ttk.Entry(form, textvariable=self.d_input).grid(row=4, column=1, sticky="ew", padx=(6,4), pady=2)
        b = ttk.Frame(form); b.grid(row=4, column=2, sticky="w")
        ttk.Button(b, text="Folder…", command=self.browse_data_folder).pack(side="left")
        ttk.Button(b, text="File…", command=self.browse_data_files).pack(side="left", padx=(3,0))

        ttk.Label(form, text="Input extension filter:").grid(row=5, column=0, sticky="w", pady=2)
        extension_values = (
            "", ".fastq", ".fastq.gz", ".fq", ".fq.gz",
            ".fastq,.fastq.gz,.fq,.fq.gz", ".sam", ".bam", ".cram",
            ".vcf", ".vcf.gz", ".bed", ".gtf", ".gff", ".idat", ".idat.gz",
            ".txt", ".tsv", ".csv"
        )
        ttk.Combobox(form, textvariable=self.d_extensions, values=extension_values, state="normal").grid(row=5, column=1, sticky="ew", padx=(6,4), pady=2)
        ttk.Label(form, text="Examples: .fastq.gz   or   .fastq,.fq,.fastq.gz,.fq.gz", wraplength=280).grid(row=5, column=2, sticky="w")

        ttk.Label(form, text="Sample ID regex:").grid(row=6, column=0, sticky="w", pady=2)
        ttk.Entry(form, textvariable=self.d_regex).grid(row=6, column=1, sticky="ew", padx=(6,4), pady=2)
        grouping=ttk.Frame(form);grouping.grid(row=6,column=2,sticky="w")
        ttk.Checkbutton(grouping,text="Group same sample ID",variable=self.d_multifile).pack(side="left")
        ttk.Label(grouping,text="Files/sample:").pack(side="left",padx=(8,3))
        ttk.Spinbox(grouping,textvariable=self.d_group_size,from_=2,to=99,width=4).pack(side="left")

        ttk.Label(form, text="Generated output template:").grid(row=7, column=0, sticky="w", pady=2)
        ttk.Entry(form, textvariable=self.d_output).grid(row=7, column=1, sticky="ew", padx=(6,4), pady=2)

        ttk.Label(form, text="Published output folder:").grid(row=8, column=0, sticky="w", pady=2)
        ttk.Entry(form, textvariable=self.d_publish).grid(row=8, column=1, sticky="ew", padx=(6,4), pady=2)
        outb = ttk.Frame(form); outb.grid(row=8, column=2, sticky="w")
        ttk.Button(outb, text="Folder…", command=self.browse_publish_folder).pack(side="left")
        ttk.Button(outb, text="Clear", command=lambda: self.d_publish.set("")).pack(side="left", padx=(3,0))

        ttk.Label(form,text="Local scan path (optional):").grid(row=9,column=0,sticky="w",pady=2)
        ttk.Entry(form,textvariable=self.d_local_scan).grid(row=9,column=1,sticky="ew",padx=(6,4),pady=2)
        ttk.Button(form,text="Browse…",command=self.browse_local_scan).grid(row=9,column=2,sticky="w",pady=2)

        self.manifest_text = tk.Text(parent, height=8, wrap="none", state="disabled"); self.manifest_text.grid(row=3, column=0, sticky="ew", pady=(8,0))

    def _build_wasj_tab(self):
        tab = ttk.Frame(self.notebook, padding=8); self._add_colored_tab(tab, "3 — WASJ metadata + pairing", C_TAB_WASJ)
        tab.rowconfigure(1, weight=1); tab.columnconfigure(0, weight=1)
        ttk.Label(tab, text=(
            "WASJ does NOT pair files by order. Each stream is already identified by its NextDash data word; the sample table tells NextDash which records belong together.  "
            "Join key = biological unit to match (e.g. patient_id). Difference key(s) = what distinguishes members inside that unit (condition, read, assay, timepoint, ...)."
        ), wraplength=1600, justify="left").grid(row=0, column=0, sticky="ew", pady=(0,6))

        pane = ttk.Panedwindow(tab, orient="horizontal"); pane.grid(row=1, column=0, sticky="nsew")
        left = ttk.LabelFrame(pane, text="WASJ blocks", padding=6); right = ttk.LabelFrame(pane, text="Selected WASJ configuration", padding=6)
        pane.add(left, weight=1); pane.add(right, weight=3)
        left.rowconfigure(1, weight=1); left.columnconfigure(0, weight=1)
        ttk.Label(left, text="Each vertical WASJ block has its own metadata rules.").grid(row=0, column=0, sticky="w")
        self.wasj_tree = ttk.Treeview(left, columns=("id","program","inputs","status"), show="headings", height=13)
        for k,t,w in [("id","Barrier",145),("program","Program",80),("inputs","Input streams",220),("status","Config",100)]:
            self.wasj_tree.heading(k,text=t); self.wasj_tree.column(k,width=w,stretch=k=="inputs")
        self.wasj_tree.grid(row=1,column=0,sticky="nsew",pady=(5,5)); self.wasj_tree.bind("<<TreeviewSelect>>",self.load_wasj)
        self.wasj_tree.tag_configure("missing",background=C_ERROR); self.wasj_tree.tag_configure("ok",background=C_WASJ)
        ttk.Button(left,text="Refresh WASJ blocks",command=self.sync_definitions).grid(row=2,column=0,sticky="w")

        right.rowconfigure(12, weight=1); right.columnconfigure(1, weight=1)
        self.w_id=tk.StringVar(); self.w_inputs=tk.StringVar(); self.w_table=tk.StringVar(); self.w_filecol=tk.StringVar();self.w_filematch=tk.StringVar(value=WASJ_FILE_MATCH_MODES[0]); self.w_sidcol=tk.StringVar(); self.w_join=tk.StringVar(); self.w_diff=tk.StringVar()
        labels=[("Barrier ID",self.w_id),("Input streams",self.w_inputs),("Sample metadata table",self.w_table)]
        for row,(lab,var) in enumerate(labels):
            ttk.Label(right,text=lab+":").grid(row=row,column=0,sticky="w",pady=2)
            ttk.Entry(right,textvariable=var,state="readonly" if row<2 else "normal").grid(row=row,column=1,sticky="ew",padx=(6,4),pady=2)
            if lab=="Sample metadata table": ttk.Button(right,text="Browse…",command=self.browse_sample_table).grid(row=row,column=2,pady=2)
        ttk.Button(right,text="Load/refresh table columns",command=self.refresh_sample_table_columns).grid(row=3,column=1,sticky="w",pady=(2,6))

        ttk.Label(right,text="File column (preferred):").grid(row=4,column=0,sticky="w",pady=2)
        self.w_file_combo=ttk.Combobox(right,textvariable=self.w_filecol,state="readonly"); self.w_file_combo.grid(row=4,column=1,sticky="ew",padx=(6,4),pady=2)
        match_frame=ttk.Frame(right);match_frame.grid(row=4,column=2,sticky="w");ttk.Label(match_frame,text="Match:").pack(side="left");ttk.Combobox(match_frame,textvariable=self.w_filematch,values=WASJ_FILE_MATCH_MODES,state="readonly",width=14).pack(side="left",padx=(3,0))
        ttk.Label(right,text="Sample ID column (alternative matching):").grid(row=5,column=0,sticky="w",pady=2)
        self.w_sid_combo=ttk.Combobox(right,textvariable=self.w_sidcol,state="readonly"); self.w_sid_combo.grid(row=5,column=1,sticky="ew",padx=(6,4),pady=2)
        ttk.Label(right,text="WASJ Join key:").grid(row=6,column=0,sticky="w",pady=2)
        self.w_join_combo=ttk.Combobox(right,textvariable=self.w_join,state="readonly"); self.w_join_combo.grid(row=6,column=1,sticky="ew",padx=(6,4),pady=2)
        ttk.Label(right,text="Difference key(s):").grid(row=7,column=0,sticky="nw",pady=2)
        diff_frame=ttk.Frame(right);diff_frame.grid(row=7,column=1,columnspan=2,sticky="ew",padx=(6,4),pady=2);diff_frame.columnconfigure(0,weight=1)
        ttk.Entry(diff_frame,textvariable=self.w_diff,state="readonly").grid(row=0,column=0,sticky="ew",pady=(0,3))
        self.w_diff_list=tk.Listbox(diff_frame,selectmode=tk.MULTIPLE,exportselection=False,height=4)
        self.w_diff_list.grid(row=1,column=0,sticky="ew");self.w_diff_list.bind("<<ListboxSelect>>",self._on_difference_selection)
        diff_scroll=ttk.Scrollbar(diff_frame,orient="vertical",command=self.w_diff_list.yview);diff_scroll.grid(row=1,column=1,sticky="ns");self.w_diff_list.configure(yscrollcommand=diff_scroll.set)
        ttk.Label(right,text="Select one or more metadata columns. Selected names appear above, separated by commas.",wraplength=800).grid(row=8,column=1,columnspan=2,sticky="w")

        roles=ttk.LabelFrame(right,text="Expected Difference values for each input stream",padding=5); roles.grid(row=9,column=0,columnspan=3,sticky="ew",pady=(8,4)); roles.columnconfigure(0,weight=1)
        self.role_tree=ttk.Treeview(roles,columns=("data","role"),show="headings",height=5)
        self.role_tree.heading("data",text="Data stream");self.role_tree.heading("role",text="Expected Difference values")
        self.role_tree.column("data",width=150);self.role_tree.column("role",width=560,stretch=True)
        self.role_tree.grid(row=0,column=0,columnspan=3,sticky="ew");self.role_tree.bind("<<TreeviewSelect>>",self.load_role)
        self.role_label=tk.StringVar();self.role_values=tk.StringVar()
        ttk.Label(roles,text="Selected:").grid(row=1,column=0,sticky="w",pady=(4,0));ttk.Entry(roles,textvariable=self.role_label,state="readonly",width=18).grid(row=1,column=1,sticky="w",pady=(4,0))
        ttk.Label(roles,text="Values:").grid(row=2,column=0,sticky="w");ttk.Entry(roles,textvariable=self.role_values).grid(row=2,column=1,sticky="ew",padx=(4,4))
        ttk.Label(roles,text="Format: condition=Tumor; assay=DNA").grid(row=3,column=1,sticky="w")
        ttk.Button(roles,text="Save Difference values",command=self.save_role).grid(row=2,column=2)

        action=ttk.Frame(right);action.grid(row=10,column=0,columnspan=3,sticky="ew",pady=(5,5))
        ttk.Button(action,text="Save WASJ configuration",command=self.save_wasj).pack(side="left")
        ttk.Button(action,text="Auto-infer Difference values",command=self.infer_wasj_roles).pack(side="left",padx=(5,0))
        ttk.Button(action,text="Preview / validate pairing",command=self.preview_selected_wasj).pack(side="left",padx=(5,0))

        self.wasj_preview=tk.Text(right,height=15,wrap="none",state="disabled");self.wasj_preview.grid(row=12,column=0,columnspan=3,sticky="nsew",pady=(5,0))

    def _build_validation_tab(self):
        tab=ttk.Frame(self.notebook,padding=8);self._add_colored_tab(tab,"4 — Validation + Diagram",C_TAB_VALIDATION)
        tab.rowconfigure(1,weight=1);tab.columnconfigure(0,weight=1)
        buttons=ttk.Frame(tab);buttons.grid(row=0,column=0,sticky="ew",pady=(0,5))
        self._colored_action_button(buttons,"Validate all",self.validate_and_diagram,C_BUTTON_VALIDATE).pack(side="left")
        pane=ttk.Panedwindow(tab,orient="horizontal");pane.grid(row=1,column=0,sticky="nsew")
        left=ttk.LabelFrame(pane,text="Validation report",padding=5);right=ttk.LabelFrame(pane,text="Interpreted workflow",padding=5);pane.add(left,weight=1);pane.add(right,weight=3)
        left.rowconfigure(0,weight=1);left.columnconfigure(0,weight=1);right.rowconfigure(0,weight=1);right.columnconfigure(0,weight=1)
        self.validation_text=tk.Text(left,wrap="word",state="disabled",width=42);self.validation_text.grid(row=0,column=0,sticky="nsew")
        holder=ttk.Frame(right);holder.grid(row=0,column=0,sticky="nsew");holder.rowconfigure(0,weight=1);holder.columnconfigure(0,weight=1)
        self.diagram=tk.Canvas(holder,background="#F8FAFC",highlightthickness=1,width=950,height=620);self.diagram.grid(row=0,column=0,sticky="nsew")
        y=ttk.Scrollbar(holder,orient="vertical",command=self.diagram.yview);x=ttk.Scrollbar(holder,orient="horizontal",command=self.diagram.xview);y.grid(row=0,column=1,sticky="ns");x.grid(row=1,column=0,sticky="ew");self.diagram.configure(yscrollcommand=y.set,xscrollcommand=x.set)

    def _build_generate_tab(self):
        tab=ttk.Frame(self.notebook,padding=8);self._add_colored_tab(tab,"5 — Generate main.nf",C_TAB_GENERATE)
        tab.rowconfigure(2,weight=1);tab.columnconfigure(0,weight=1)
        settings=ttk.LabelFrame(tab,text="Generation settings",padding=6);settings.grid(row=0,column=0,sticky="ew");settings.columnconfigure(1,weight=1)
        for row,(label,var) in enumerate([("Output project folder",self.output_dir_var),("Results folder inside project",self.results_var)]):
            ttk.Label(settings,text=label+":").grid(row=row,column=0,sticky="w",pady=2);ttk.Entry(settings,textvariable=var).grid(row=row,column=1,sticky="ew",padx=(6,4),pady=2)
            if row==0:ttk.Button(settings,text="Browse…",command=self.browse_output_dir).grid(row=row,column=2,pady=2)
        ttk.Label(
            settings,
            text="This is the subfolder where generated pipeline outputs are collected; the default is 'results'.",
            wraplength=1100,
            justify="left",
        ).grid(row=2,column=1,columnspan=2,sticky="w",padx=(6,4),pady=(0,5))
        ttk.Label(settings,text="How generated outputs are saved:").grid(row=3,column=0,sticky="w",pady=2)
        ttk.Combobox(settings,textvariable=self.publish_mode_var,values=("copy",),state="readonly",width=10).grid(row=3,column=1,sticky="w",padx=(6,4),pady=2)
        ttk.Label(
            settings,
            text="copy keeps generated results safe when the temporary Nextflow work cache is removed.",
            wraplength=1100,
            justify="left",
        ).grid(row=4,column=1,columnspan=2,sticky="w",padx=(6,4),pady=(0,5))
        ttk.Checkbutton(settings,text="Convert Windows paths to /mnt/<drive>/... for WSL",variable=self.convert_var).grid(row=5,column=1,sticky="w")
        ttk.Checkbutton(settings,text="Overwrite generated files",variable=self.overwrite_var).grid(row=6,column=1,sticky="w")
        ttk.Checkbutton(settings,text="Enable Nextflow task caching (-resume can reuse successful tasks)",variable=self.cache_enabled_var).grid(row=7,column=1,sticky="w")
        ttk.Label(
            settings,
            text=(
                "Enable caching only when you plan to use -resume; it is disabled by default to match NextDash low-storage mode. Nextflow still creates "
                "temporary task files in work/ while running. After the run has completely stopped, the button below removes work/ "
                "and .nextflow/cache/. Published result copies are preserved."
            ),
            wraplength=1100,
            justify="left",
        ).grid(row=8,column=1,columnspan=2,sticky="w",padx=(6,4),pady=(5,2))
        cache_actions=ttk.Frame(settings);cache_actions.grid(row=9,column=1,columnspan=2,sticky="w",padx=(6,4),pady=(4,2))
        ttk.Label(cache_actions,textvariable=self.cache_size_var).pack(side="left",padx=(0,8))
        ttk.Button(cache_actions,text="Refresh size",command=self.refresh_cache_size).pack(side="left",padx=(0,6))
        self._colored_action_button(cache_actions,"Remove cached data",self.remove_cached_data,C_RED).pack(side="left")
        actions=ttk.Frame(tab);actions.grid(row=1,column=0,sticky="ew",pady=(6,5))
        self._colored_action_button(actions,"Generate project",self.generate_project,C_BUTTON_GENERATE).pack(side="left")
        self.main_preview=tk.Text(tab,wrap="none",state="disabled");self.main_preview.grid(row=2,column=0,sticky="nsew")




    def grid_changed(self):



        try:
            parsed, _issues = parse_grid(self.sheet.get_grid())
            self.refresh_grid_flow_colors(parsed)
        except Exception:


            pass
        self.status_var.set("Grid changed. Sync definitions / WASJ blocks before generation.")

    def trim_grid_margins(self):
        self.sheet.trim_empty()
        self.status_var.set(
            "Removed excess blank rows at the bottom and blank columns on the right while keeping a small editable grid; cell contents were not changed."
        )

    def new_grid(self):
        if messagebox.askyesno("New grid","Clear the workflow grid and current definitions?",parent=self.root):
            self.sheet.clear();self.programs.clear();self.data_defs.clear();self.wasj_configs.clear();self.current_grid_path=None;self.sync_definitions()

    def load_grid(self):
        path=filedialog.askopenfilename(parent=self.root,title="Load NextDash tabulated grid",filetypes=[("NextDash tabulated text","*.tabtxt *.tsv *.txt"),("All files","*")])
        if not path:return
        try:
            grid,_converted=read_tabtxt(Path(path));self.sheet.set_grid(grid);self.current_grid_path=Path(path);self.sync_definitions()
            self.status_var.set(f"Loaded {path}")
        except Exception as exc:messagebox.showerror("Load grid",str(exc),parent=self.root)

    def save_grid(self):
        if self.current_grid_path is None:return self.save_grid_as()
        try:write_tabtxt(self.current_grid_path,self.sheet.get_grid());self.status_var.set(f"Saved grid: {self.current_grid_path}")
        except Exception as exc:messagebox.showerror("Save grid",str(exc),parent=self.root)

    def save_grid_as(self):
        path=filedialog.asksaveasfilename(parent=self.root,title="Save NextDash grid",defaultextension=".tabtxt",filetypes=[("NextDash tabulated text","*.tabtxt"),("TSV","*.tsv"),("All files","*")])
        if not path:return
        self.current_grid_path=Path(path);self.save_grid()

    def save_project_file(self):
        path=filedialog.asksaveasfilename(parent=self.root,title="Save complete NextDash project",defaultextension=".nextdash.json",filetypes=[("NextDash project","*.nextdash.json *.nextDash.json"),("JSON","*.json")])
        if not path:return
        payload={
            "format":"NextDash project","version":11.0,"grid":trim_grid(self.sheet.get_grid()),
            "programs":{k:vars(v) for k,v in self.programs.items()},
            "data_defs":{k:vars(v) for k,v in self.data_defs.items()},
            "wasj_configs":{k:vars(v) for k,v in self.wasj_configs.items()},
            "settings":{"output_dir":self.output_dir_var.get(),"results":self.results_var.get(),"publish_mode":self.publish_mode_var.get(),"convert_windows_to_wsl":bool(self.convert_var.get()),"cache_enabled":bool(self.cache_enabled_var.get())},
        }
        try:Path(path).write_text(json.dumps(payload,indent=2),encoding="utf-8");self.status_var.set(f"Saved full NextDash project: {path}")
        except Exception as exc:messagebox.showerror("Save project",str(exc),parent=self.root)

    def load_project(self):
        path=filedialog.askopenfilename(parent=self.root,title="Load NextDash project",filetypes=[("NextDash project","*.nextdash.json *.nextDash.json *.netdash.json *.json"),("All files","*")])
        if not path:return
        try:
            payload=json.loads(Path(path).read_text(encoding="utf-8"))
            if payload.get("format") not in ("NextDash project", "NetDash project"):raise ValueError("This JSON file is not a NextDash project.")
            self.programs={k:ProgramDef(**v) for k,v in payload.get("programs",{}).items()};self.data_defs={k:DataDef(**v) for k,v in payload.get("data_defs",{}).items()}
            self.wasj_configs={}
            for key,values in payload.get("wasj_configs",{}).items():
                values=dict(values)
                if "difference_values" not in values and "role_values" in values:values["difference_values"]=values["role_values"]
                values.pop("role_values",None)
                self.wasj_configs[key]=WASJConfig(**values)
            s=payload.get("settings",{});self.output_dir_var.set(s.get("output_dir",self.output_dir_var.get()));self.results_var.set(s.get("results","results"));self.publish_mode_var.set("copy");self.convert_var.set(bool(s.get("convert_windows_to_wsl",True)));self.cache_enabled_var.set(bool(s.get("cache_enabled",False)))
            self.current_grid_path=None;self.sheet.set_grid(payload.get("grid") or [[""]*12 for _ in range(8)]);self.sync_definitions();self.status_var.set(f"Loaded project: {path}")
        except Exception as exc:messagebox.showerror("Load project",str(exc),parent=self.root)




    def example_menu(self):
        win=tk.Toplevel(self.root);win.title("NextDash examples");win.geometry("680x380");frm=ttk.Frame(win,padding=12);frm.pack(fill="both",expand=True)
        ttk.Label(frm,text="Choose an example",font=("TkDefaultFont",11,"bold")).pack(anchor="w",pady=(0,8))
        examples=[
            ("Vertical WAS — wait for B and D, then continue B samples", self.load_was_example),
            ("WASG — group all count files into one cohort analysis", self.load_wasg_example),
            ("WASJ — paired Tumor / Normal by patient_id", self.load_wasj_example),
            ("Mixed — simple → WAS → WASJ → simple", self.load_mixed_example),
        ]
        for label,cmd in examples:
            ttk.Button(frm,text=label,command=lambda c=cmd:(c(),win.destroy())).pack(fill="x",pady=4)

    def load_was_example(self):
        self.sheet.set_grid([["A","4","B","WAS","5","E"],["","","D","WAS","",""]]);self.sync_definitions();self.status_var.set("Loaded the vertical WAS example matching your NextDash(1).tabtxt logic.")
    def load_wasg_example(self):
        self.sheet.set_grid([["COUNTS","1","QC","WASG","2","COHORT_RESULT"]]);self.sync_definitions();self.status_var.set("Loaded a WASG cohort example.")
    def load_wasj_example(self):
        self.sheet.set_grid([["TUMOR","WASJ","7","PAIR_RESULT"],["NORMAL","WASJ","",""]]);self.sync_definitions();self.programs["7"].arguments_template="--tumor {TUMOR} --normal {NORMAL} -o {output}";self.refresh_program_tree();self.status_var.set("Loaded Tumor/Normal WASJ example. Configure patient_id + condition in Tab 3.")
    def load_mixed_example(self):
        self.sheet.set_grid([["A","1","B","WAS","2","C","WASJ","4","E","5","F"],["","","D","WAS","","D2","WASJ","",""]]);self.sync_definitions();self.status_var.set("Loaded a mixed synchronization example.")




    def _parse_and_sync(self):
        parsed,issues=parse_grid(self.sheet.get_grid());self.current_parsed=parsed
        for row in self.sheet.get_grid():
            for token in row:
                if token_kind(token)!="program":
                    continue
                pid=program_token_id(token)
                alias=token[len(pid)+1:] if token.startswith(pid+"_") else ""
                self.programs.setdefault(pid,ProgramDef(pid,name=alias or f"Program_{pid}"))
        self.sheet.refresh_program_labels(self.programs)
        for label in parsed.data_labels:
            self.data_defs.setdefault(label,DataDef(label))
        active_ids={occ.barrier_id for occ in parsed.wasj_occurrences()}
        for barrier_id in active_ids:self.wasj_configs.setdefault(barrier_id,WASJConfig(barrier_id))
        return parsed,issues

    def sync_definitions(self):
        parsed,issues=self._parse_and_sync();self.refresh_program_tree();self.refresh_data_tree();self.refresh_wasj_tree();self.refresh_grid_flow_colors(parsed);self.status_var.set(f"Synchronized: {len(parsed.program_ids)} programs, {len(parsed.data_labels)} data words, {len(parsed.wasj_occurrences())} WASJ block(s).")
        return parsed,issues

    def read_variables_from_workflow(self):
        """Read program IDs and data words directly from the Tab 1 grid."""
        parsed, issues = self.sync_definitions()
        structural_errors = [x for x in issues if getattr(x, "level", "") == "ERROR"]
        msg = (
            f"Read {len(parsed.program_ids)} program ID(s) and {len(parsed.data_labels)} data word(s) "
            "from the workflow spreadsheet."
        )
        if structural_errors:
            msg += f"  The grid also has {len(structural_errors)} structural validation error(s); definitions were still refreshed."
        self.status_var.set(msg)
        return parsed, issues

    def refresh_program_tree(self):
        if not hasattr(self,"program_tree") or not self.current_parsed:return
        self.program_tree.delete(*self.program_tree.get_children())
        for pid in sorted(self.current_parsed.program_ids,key=program_sort_key):
            p=self.programs[pid];uses=[o for o in self.current_parsed.occurrences if o.program_id==pid];usage=", ".join(sorted({f"{o.barrier}:{o.arity}" for o in uses}))
            self.program_tree.insert("","end",iid=pid,values=(pid,p.normalized_name(),("[Inline Bash]" if p.program_type=="Inline Bash" else (p.program_path or "UNDEFINED")),usage),tags=("ok" if p.program_type=="Inline Bash" or p.program_path.strip() else "missing",))
        self._apply_tab2_sort("program")

    def _program_route_records(self, pid: str):
        parsed=self.current_parsed
        if not parsed or pid not in self.programs:
            return []
        p=self.programs[pid]
        records=[]
        for occ in [o for o in parsed.occurrences if o.program_id==pid]:
            for idx,word in enumerate(occ.input_labels,1):
                d=self.data_defs.get(word,DataDef(word))
                source=d.input_pattern if word in parsed.root_data else d.normalized_output_template()
                producer=parsed.producer_by_data.get(word)
                from_program=(f"{producer.program_id}_{self.programs[producer.program_id].normalized_name()}" if producer else "ROOT")
                placeholder="{input}" if len(occ.input_labels)==1 else f"{{input{idx}}}"
                records.append(("INPUT",word,placeholder,source,from_program))
            d=self.data_defs[occ.output_label]
            consumers=[o for o in parsed.occurrences if occ.output_label in o.dependency_labels()]
            downstream=", ".join(f"{o.program_id}_{self.programs[o.program_id].normalized_name()}" for o in consumers) or "FINAL OUTPUT"
            records.append(("OUTPUT",occ.output_label,"{output}",d.normalized_output_template(),downstream))
            for idx,template in enumerate(parse_additional_outputs(p.additional_outputs),2):
                records.append(("AUX OUTPUT",occ.output_label,f"{{output{idx}}}",template,"Published with primary output"))
            for alias,word in parse_shared_resources(p.shared_resources):
                d=self.data_defs.get(word,DataDef(word))
                records.append(("SHARED",word,f"{{{alias}}}",d.input_pattern,"Shared single resource"))
        return records

    def refresh_program_routing(self):
        if not hasattr(self,"routing_tree"):
            return
        tree=self.routing_tree
        tree.delete(*tree.get_children())
        pid=self.p_id.get().strip() if hasattr(self,"p_id") else ""
        if not pid or pid not in self.programs:
            return
        try:
            records=self._program_route_records(pid)
        except NetDashError as exc:
            records=[("ERROR",pid,"","",str(exc))]
        for kind,word,placeholder,file,dest in records:
            tree.insert("","end",values=(kind,word,placeholder,file,dest))

    def _routing_double_click(self,event):
        item=self.routing_tree.identify_row(event.y)
        if not item:
            return
        kind,word,*_ = self.routing_tree.item(item,"values")
        if kind in ("INPUT","OUTPUT","AUX OUTPUT","SHARED") and self.data_tree.exists(word):
            self.data_tree.selection_set(word)
            self.data_tree.see(word)
            self.load_data()

    def show_routing_map(self):
        self.sync_definitions()
        win=tk.Toplevel(self.root)
        win.title("Workflow file routing")
        win.geometry("1350x600")
        frame=ttk.Frame(win,padding=10)
        frame.pack(fill="both",expand=True)
        tree=ttk.Treeview(frame,columns=("program","input","output","template","next","shared"),show="headings")
        for key,title,width in [("program","Program",220),("input","Input data",135),("output","Output data",135),("template","Output filename",235),("next","Next program",285),("shared","Shared resources",285)]:
            tree.heading(key,text=title)
            tree.column(key,width=width,minwidth=90,stretch=True)
        tree.pack(fill="both",expand=True)
        parsed=self.current_parsed
        for occ in topological_occurrences(parsed):
            p=self.programs[occ.program_id]
            d=self.data_defs[occ.output_label]
            consumers=[x for x in parsed.occurrences if occ.output_label in x.dependency_labels()]
            next_names=", ".join(f"{x.program_id}_{self.programs[x.program_id].normalized_name()}" for x in consumers) or "FINAL"
            resources=", ".join(f"{alias}={word}" for alias,word in parse_shared_resources(p.shared_resources))
            tree.insert("","end",iid=occ.occurrence_id,values=(f"{occ.program_id}_{p.normalized_name()}",", ".join(occ.input_labels),occ.output_label,d.normalized_output_template(),next_names,resources))
        def navigate(_event):
            row=tree.focus()
            match=next((o for o in parsed.occurrences if o.occurrence_id==row),None)
            if match and self.program_tree.exists(match.program_id):
                self.program_tree.selection_set(match.program_id)
                self.program_tree.see(match.program_id)
                self.load_program()
                self.notebook.select(1)
                win.destroy()
        tree.bind("<Double-1>",navigate)

    def _terminal_data_labels(self):
        if not self.current_parsed:
            return set()
        consumed = {label for occ in self.current_parsed.occurrences for label in occ.dependency_labels()}
        generated = set(self.current_parsed.producer_by_data)
        return generated - consumed

    def _stream_is_parallel(self, label, parsed=None, seen=None):
        """Whether a logical stream still represents independent sample/group items."""
        parsed = parsed or self.current_parsed
        if not parsed:
            return True
        seen = set() if seen is None else seen
        if label in seen:
            return True
        seen.add(label)
        if label in parsed.root_data:
            return self.data_defs.get(label, DataDef(label)).normalized_input_mode() != MODE_SHARED
        producer = parsed.producer_by_data.get(label)
        if producer is None:
            return True
        if producer.barrier == "WASG":
            return False


        if producer.barrier == "WASJ":
            return True
        upstream = producer.primary_label or (producer.input_labels[0] if producer.input_labels else "")
        return self._stream_is_parallel(upstream, parsed, seen) if upstream else True

    def refresh_grid_flow_colors(self, parsed=None):
        parsed = parsed or self.current_parsed
        if not parsed or not hasattr(self, "sheet"):
            return
        serial_labels = {label for label in parsed.data_labels if not self._stream_is_parallel(label, parsed)}
        shared_labels = {
            label for label in parsed.root_data
            if self.data_defs.get(label, DataDef(label)).normalized_input_mode() == MODE_SHARED
        }
        self.sheet.apply_data_flow_colors(serial_labels, shared_labels)

    def refresh_data_tree(self):
        if not hasattr(self,"data_tree") or not self.current_parsed:return
        self.data_tree.delete(*self.data_tree.get_children())
        terminals = self._terminal_data_labels()
        for label in sorted(self.current_parsed.data_labels):
            d=self.data_defs[label]
            root=label in self.current_parsed.root_data
            terminal=(not root and label in terminals)
            if root:
                role="ROOT INPUT"
                mode=d.normalized_input_mode()
                definition=d.input_pattern or "UNDEFINED"
                if d.local_scan_pattern:
                    definition+=f" | local: {d.local_scan_pattern}"
                if d.input_extensions.strip():
                    definition += f"  [filter: {d.input_extensions}]"
                ok=bool(d.input_pattern.strip())
                tag="missing" if not ok else ("shared" if d.normalized_input_mode()==MODE_SHARED else "root")
            else:
                role="FINAL OUTPUT" if terminal else "GENERATED"
                parallel=self._stream_is_parallel(label)
                flow_mode="parallel per-sample flow" if parallel else "serial cohort flow"
                mode=("terminal output — " if terminal else "intermediate output — ")+flow_mode
                destination=d.publish_directory.strip() or "results/<program>_out"
                definition=f"{d.normalized_output_template()}  →  {destination}"
                tag="parallel" if parallel else "serial"
            producer=self.current_parsed.producer_by_data.get(label)
            produced_by=(f"{producer.program_id}_{self.programs[producer.program_id].normalized_name()}" if producer else "ROOT")
            consumers=[o for o in self.current_parsed.occurrences if label in o.dependency_labels()]
            used_by=", ".join(f"{o.program_id}_{self.programs[o.program_id].normalized_name()}" for o in consumers) or "—"
            resource_users=[]
            for pid in self.current_parsed.program_ids:
                try:
                    resources=parse_shared_resources(self.programs[pid].shared_resources)
                except NetDashError:
                    resources=[]
                if any(res_word==label for _alias,res_word in resources):
                    resource_users.append(f"{pid}_{self.programs[pid].normalized_name()}")
            if resource_users:
                used_by=", ".join(resource_users)
            self.data_tree.insert("","end",iid=label,values=(label,role,mode,definition,produced_by,used_by),tags=(tag,))
        self._apply_tab2_sort("data")

    def refresh_wasj_tree(self):
        if not hasattr(self,"wasj_tree") or not self.current_parsed:return
        self.wasj_tree.delete(*self.wasj_tree.get_children())
        for occ in self.current_parsed.wasj_occurrences():
            cfg=self.wasj_configs.setdefault(occ.barrier_id,WASJConfig(occ.barrier_id));ok=bool(cfg.sample_table_path and cfg.join_key and cfg.normalized_difference_keys() and (cfg.file_column or cfg.sample_id_column))
            self.wasj_tree.insert("","end",iid=occ.barrier_id,values=(occ.barrier_id,occ.program_id,", ".join(occ.input_labels),"configured" if ok else "MISSING"),tags=("ok" if ok else "missing",))




    def load_program(self,_e=None):
        sel=self.program_tree.selection()
        if not sel:return
        p=self.programs[sel[0]]
        self._loading_program_form=True
        try:self.p_id.set(p.program_id);self.p_name.set(p.name);self.p_path.set(p.program_path);self.p_type.set(p.program_type);self.p_args.set(p.arguments_template);self.p_cpus.set(str(p.cpus));self.p_mem.set(p.memory);self.p_time.set(p.time);self.p_forks.set(str(p.max_forks));self.p_outdir.set(p.publish_subdirectory);self.p_extra_inputs.set(p.additional_inputs);self.p_extra_outputs.set(p.additional_outputs);self.p_shared_resources.set(p.shared_resources)
        finally:
            self._refresh_program_multiline()
            self._loading_program_form=False
        self.refresh_program_routing()

    def edit_inline_bash(self):
        if self.p_type.get() != "Inline Bash":
            self._loading_program_form=True
            try:
                self.p_type.set("Inline Bash")
                self.p_path.set("/bin/bash")
            finally:
                self._loading_program_form=False
            self.save_program(silent=True)
        self.edit_program_multiline("arguments")

    def _auto_save_program(self,*_args):
        if not self._loading_program_form:self.save_program(silent=True,refresh=False)

    def save_program(self,silent=False,refresh=True):
        pid=self.p_id.get().strip()
        if not pid:return
        try:
            p=self.programs[pid];p.name=self.p_name.get().strip();p.program_path=self.p_path.get().strip();p.program_type=self.p_type.get();p.arguments_template=self.p_args.get().strip();p.cpus=int(self.p_cpus.get());p.memory=self.p_mem.get().strip();p.time=self.p_time.get().strip();p.max_forks=int(self.p_forks.get());p.publish_subdirectory=self.p_outdir.get().strip();p.additional_inputs=self.p_extra_inputs.get().strip();p.additional_outputs=self.p_extra_outputs.get().strip();p.shared_resources=self.p_shared_resources.get().strip()
            self.sheet.refresh_program_labels(self.programs)
            if refresh:self.refresh_program_tree()
            self.refresh_program_routing()
            if not silent:self.status_var.set(f"Saved Program {pid}.")
        except Exception as exc:
            if not silent:messagebox.showerror("Program definition",str(exc),parent=self.root)
    def browse_program(self):
        p = filedialog.askopenfilename(
            parent=self.root,
            title="Choose program/script",
            filetypes=[
                ("Programs/scripts", "*.py *.R *.r *.sh *.bash *.pl *.rb *.exe *.lx"),
                ("Linux .lx", "*.lx"),
                ("All files", "*"),
            ],
        )
        if not p:
            return ""
        self.p_path.set(p)
        suffix = Path(p).suffix.lower()
        if suffix == ".py":
            self.p_type.set("Python 3")
        elif suffix == ".r":
            self.p_type.set("Rscript")
        elif suffix in (".sh", ".bash"):
            self.p_type.set("Bash")
        elif suffix == ".lx":
            self.p_type.set("Linux executable")
        self.save_program(silent=True)
        return p

    def on_program_double_click(self, event):
        row = self.program_tree.identify_row(event.y)
        if not row:
            return
        self.program_tree.selection_set(row)
        self.program_tree.focus(row)
        self.load_program()
        if self.p_type.get() == "Inline Bash":
            self.edit_inline_bash()
        elif self.browse_program():
            self.save_program()

    def _cli_probe_commands(self, path: str, program_type: str, flag: str):
        """Return safe command candidates for asking a program for CLI help."""
        path = path.strip()
        if not path:
            return []
        suffix = Path(path).suffix.lower()
        candidates = []


        if program_type == "Python 3" or suffix == ".py":
            candidates.append([sys.executable, path, flag])


        if program_type == "Rscript" or suffix == ".r":
            candidates.append(["Rscript", path, flag])

        if os.name == "nt":
            wsl_path = windows_path_to_wsl(path)
            qpath = shlex.quote(wsl_path)
            if program_type == "Bash" or suffix in (".sh", ".bash"):
                candidates.append(["wsl", "bash", "-lc", f"bash {qpath} {shlex.quote(flag)}"])
            else:

                candidates.append(["wsl", "bash", "-lc", f"{qpath} {shlex.quote(flag)}"])
        else:
            if program_type == "Bash" or suffix in (".sh", ".bash"):
                candidates.append(["bash", path, flag])
            elif program_type == "Linux executable" and not candidates:
                candidates.append([path, flag])


        unique = []
        seen = set()
        for cmd in candidates:
            key = tuple(cmd)
            if key not in seen:
                unique.append(cmd)
                seen.add(key)
        return unique

    def _probe_program_cli_help(self, path: str, program_type: str):
        attempts = []
        best = None
        for flag in ("--help", "-h"):
            for cmd in self._cli_probe_commands(path, program_type, flag):
                printable = subprocess.list2cmdline(cmd) if os.name == "nt" else shlex.join(cmd)
                try:
                    completed = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        errors="replace",
                        timeout=8,
                    )
                    output = ((completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")).strip()
                    attempts.append((printable, completed.returncode, output))
                    if output and (best is None or len(output) > len(best[2])):
                        best = (printable, completed.returncode, output)

                    if output and completed.returncode == 0:
                        return (printable, completed.returncode, output), attempts
                except subprocess.TimeoutExpired:
                    attempts.append((printable, None, "Timed out after 8 seconds. The program may not implement this help flag."))
                except FileNotFoundError as exc:
                    attempts.append((printable, None, f"Command/interpreter not found: {exc}"))
                except Exception as exc:
                    attempts.append((printable, None, str(exc)))
        return best, attempts

    def read_selected_program_cli_help(self):
        path = self.p_path.get().strip()
        if not path:
            messagebox.showerror("CLI help", "Choose a program/script first.", parent=self.root)
            return

        self.status_var.set("Reading CLI help from the selected program…")
        best, attempts = self._probe_program_cli_help(path, self.p_type.get())

        win = tk.Toplevel(self.root)
        win.title(f"CLI help — {Path(path).name}")
        win.geometry("1100x720")
        win.minsize(760, 480)
        holder = ttk.Frame(win, padding=8)
        holder.pack(fill="both", expand=True)
        ttk.Label(
            holder,
            text=(
                "NextDash tried the selected program with --help and -h only. "
                "The text below is whatever the program itself reports; NextDash does not execute the normal analysis intentionally."
            ),
            wraplength=1000,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))

        text = tk.Text(holder, wrap="none")
        ybar = ttk.Scrollbar(holder, orient="vertical", command=text.yview)
        xbar = ttk.Scrollbar(holder, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        text.pack(side="left", fill="both", expand=True)
        ybar.pack(side="right", fill="y")
        xbar.pack(side="bottom", fill="x")

        if best:
            command, rc, output = best
            body = f"COMMAND USED:\n{command}\n\nRETURN CODE: {rc}\n\nCLI HELP / ACCEPTED OPTIONS:\n{output}\n"
            self.status_var.set("CLI help read successfully. Review the program's own help text.")
        else:
            lines = [
                "No useful CLI help text was returned.",
                "The program may use a different help mechanism, require an interpreter that is not available, or not implement CLI help.",
                "",
                "ATTEMPTS:",
            ]
            for command, rc, output in attempts:
                lines += [f"\n$ {command}", f"return code: {rc}", output or "(no output)"]
            body = "\n".join(lines)
            self.status_var.set("No standard --help/-h output was found for the selected program.")
        text.insert("1.0", body)
        text.configure(state="disabled")

        buttons = ttk.Frame(win, padding=(8, 0, 8, 8))
        buttons.pack(fill="x")
        def copy_help():
            self.root.clipboard_clear()
            self.root.clipboard_append(body)
            self.status_var.set("CLI help copied to clipboard.")
        ttk.Button(buttons, text="Copy", command=copy_help).pack(side="left")
        ttk.Button(buttons, text="Close", command=win.destroy).pack(side="right")

    def load_data(self,_e=None):
        sel=self.data_tree.selection()
        if not sel:return
        label=sel[0]
        d=self.data_defs[label]
        if label in self.current_parsed.root_data:
            role="ROOT INPUT"
        elif label in self._terminal_data_labels():
            role="FINAL OUTPUT"
        else:
            role="GENERATED"
        self._loading_data_form=True
        try:
            self.d_label.set(label); self.d_role.set(role); self.d_mode.set(d.normalized_input_mode())
            self.d_desc.set(d.description); self.d_input.set(d.input_pattern); self.d_local_scan.set(d.local_scan_pattern); self.d_extensions.set(d.input_extensions)
            self.d_regex.set(d.sample_regex);self.d_multifile.set(bool(d.group_files_by_sample));self.d_group_size.set(str(d.expected_files_per_sample)); self.d_output.set(d.output_template or d.normalized_output_template()); self.d_publish.set(d.publish_directory)
        finally:self._loading_data_form=False

    def _auto_save_data(self,*_args):
        if not self._loading_data_form:self.save_data(silent=True,refresh=False)

    def save_data(self,silent=False,refresh=True):
        label=self.d_label.get().strip()
        if not label:return
        d=self.data_defs[label]
        d.input_mode=self.d_mode.get(); d.description=self.d_desc.get().strip(); d.input_pattern=self.d_input.get().strip();d.local_scan_pattern=self.d_local_scan.get().strip()
        d.input_extensions=self.d_extensions.get().strip(); d.sample_regex=self.d_regex.get().strip(); d.output_template=self.d_output.get().strip()
        d.group_files_by_sample=bool(self.d_multifile.get());d.publish_directory=self.d_publish.get().strip()
        try:d.expected_files_per_sample=int(self.d_group_size.get())
        except (TypeError,ValueError):pass
        if refresh:self.refresh_data_tree();self.refresh_grid_flow_colors()
        if not silent:
            if label in self.current_parsed.root_data:
                filt=f"; filter={d.input_extensions}" if d.input_extensions else ""
                self.status_var.set(f"Saved input data {label}{filt}.")
            else:
                destination=d.publish_directory or "results/<program>_out"
                self.status_var.set(f"Saved generated data {label}; publish destination: {destination}.")

    def browse_local_scan(self):
        if self.d_mode.get()==MODE_SHARED:
            selected=filedialog.askopenfilename(parent=self.root,title="Select local reference file")
        else:
            selected=filedialog.askdirectory(parent=self.root,title="Select local input folder")
        if selected:
            self.d_local_scan.set(selected)
            self.save_data(silent=True)

    def browse_data_folder(self):
        p=filedialog.askdirectory(parent=self.root,title="Choose input folder")
        if p:self.d_input.set(p);self.save_data(silent=True)
        return p

    def browse_data_files(self):
        p=filedialog.askopenfilename(parent=self.root,title="Choose input file")
        if p:self.d_input.set(p);self.save_data(silent=True)
        return p

    def browse_publish_folder(self):
        p=filedialog.askdirectory(parent=self.root,title="Choose published/final output folder")
        if p:self.d_publish.set(p);self.save_data(silent=True)
        return p

    def on_data_double_click(self, event):
        row = self.data_tree.identify_row(event.y)
        if not row:return
        self.data_tree.selection_set(row); self.data_tree.focus(row); self.load_data()
        label=self.d_label.get().strip()
        if not self.current_parsed:return
        if label in self.current_parsed.root_data:
            chosen=self.browse_data_files() if self.d_mode.get()==MODE_SHARED else self.browse_data_folder()
        else:
            chosen=self.browse_publish_folder()
        if chosen:self.save_data()

    def scan_inputs(self):
        parsed,_=self._parse_and_sync();rows,issues=scan_root_inputs(parsed,self.data_defs,self.wasj_configs);self.manifest_rows=rows
        lines=["data\tsample_id\tfile"]+[f"{r['data_id']}\t{r['sample_id']}\t{r['input_path']}" for r in rows]+[str(i) for i in issues]
        self._set_text(self.manifest_text,"\n".join(lines));self.status_var.set(f"Scanned {len(rows)} root input records.")




    def _occurrence_by_wasj_id(self,barrier_id):
        if not self.current_parsed:return None
        return next((o for o in self.current_parsed.wasj_occurrences() if o.barrier_id==barrier_id),None)

    def load_wasj(self,_e=None):
        sel=self.wasj_tree.selection()
        if not sel:return
        bid=sel[0];self.current_wasj_id=bid;occ=self._occurrence_by_wasj_id(bid);cfg=self.wasj_configs.setdefault(bid,WASJConfig(bid))
        self.w_id.set(bid);self.w_inputs.set(", ".join(occ.input_labels) if occ else "");self.w_table.set(cfg.sample_table_path);self.w_filecol.set(cfg.file_column);self.w_filematch.set(cfg.file_match_mode if cfg.file_match_mode in WASJ_FILE_MATCH_MODES else WASJ_FILE_MATCH_MODES[0]);self.w_sidcol.set(cfg.sample_id_column);self.w_join.set(cfg.join_key);self.w_diff.set(", ".join(cfg.normalized_difference_keys()));self.refresh_sample_table_columns(silent=True);self.refresh_role_tree();self._set_text(self.wasj_preview,"Click 'Preview / validate pairing' after configuring Join key and Difference keys.")

    def browse_sample_table(self):
        p=filedialog.askopenfilename(parent=self.root,title="Choose sample metadata table",filetypes=[("Tab/CSV metadata","*.tabtxt *.tsv *.csv *.txt"),("All files","*")])
        if p:self.w_table.set(p);self.refresh_sample_table_columns()

    def _on_difference_selection(self,_event=None):
        if getattr(self,"_updating_difference_list",False):return
        selected=[self.w_diff_list.get(index) for index in self.w_diff_list.curselection()]
        self.w_diff.set(", ".join(selected))
        self._sync_current_wasj_config()
        self._refresh_difference_values_from_metadata()

    def _refresh_difference_choices(self,headers):
        if not hasattr(self,"w_diff_list"):return
        selected={value.strip() for value in self.w_diff.get().split(",") if value.strip()}
        self._updating_difference_list=True
        try:
            self.w_diff_list.delete(0,"end")
            for index,header in enumerate(headers):
                self.w_diff_list.insert("end",header)
                if header in selected:self.w_diff_list.selection_set(index)
            if headers:
                valid=[header for header in headers if header in selected]
                self.w_diff.set(", ".join(valid))
        finally:
            self._updating_difference_list=False

    def refresh_sample_table_columns(self,silent=False):
        path=self.w_table.get().strip()
        headers=[]
        if path:
            try:headers,_=read_sample_table(path)
            except Exception as exc:
                if not silent:messagebox.showerror("Sample table",str(exc),parent=self.root)
        self.sample_table_headers=headers
        values=[""]+headers
        self.w_file_combo.configure(values=values);self.w_sid_combo.configure(values=values);self.w_join_combo.configure(values=values)
        self._refresh_difference_choices(headers)
        if headers and self.w_filecol.get() not in headers:
            self.w_filecol.set("")
            for candidate in ("file","filename","path","input_path","File","Filename"):
                if candidate in headers:self.w_filecol.set(candidate);break
        if headers and self.w_sidcol.get() and self.w_sidcol.get() not in headers:self.w_sidcol.set("")
        if headers and not self.w_sidcol.get():
            for candidate in ("sample_id","sample","Sample_ID","Sample"):
                if candidate in headers:self.w_sidcol.set(candidate);break
        if headers and self.w_join.get() not in headers:
            self.w_join.set("")
            for candidate in ("patient_id","patient","subject_id","subject","sample_id"):
                if candidate in headers:self.w_join.set(candidate);break
        if headers and not self.w_diff.get().strip():
            identity_columns={self.w_filecol.get().strip(),self.w_sidcol.get().strip(),self.w_join.get().strip(),"sample_id"}
            candidates=[header for header in headers if header not in identity_columns]
            if len(candidates)==1:
                candidate=candidates[0];index=headers.index(candidate)
                self._updating_difference_list=True
                try:self.w_diff_list.selection_set(index);self.w_diff.set(candidate)
                finally:self._updating_difference_list=False
        self._sync_current_wasj_config()
        self._refresh_difference_values_from_metadata()
        if headers and not silent:self.status_var.set(f"Loaded {len(headers)} sample-table columns.")

    def _sync_current_wasj_config(self):
        bid=self.current_wasj_id or self.w_id.get().strip()
        if not bid:return None
        cfg=self.wasj_configs.setdefault(bid,WASJConfig(bid))
        cfg.sample_table_path=self.w_table.get().strip();cfg.file_column=self.w_filecol.get().strip();cfg.file_match_mode=self.w_filematch.get() if self.w_filematch.get() in WASJ_FILE_MATCH_MODES else WASJ_FILE_MATCH_MODES[0];cfg.sample_id_column=self.w_sidcol.get().strip();cfg.join_key=self.w_join.get().strip()
        cfg.difference_keys=[value.strip() for value in self.w_diff.get().split(",") if value.strip()]
        return cfg

    def _refresh_difference_values_from_metadata(self):
        cfg=self._sync_current_wasj_config();occ=self._occurrence_by_wasj_id(self.current_wasj_id)
        if not cfg or not occ:return
        difference_keys=cfg.normalized_difference_keys();valid=set(difference_keys)
        cfg.role_values={label:{key:value for key,value in values.items() if key in valid} for label,values in cfg.role_values.items()}
        if difference_keys and cfg.sample_table_path and self.current_parsed:
            rows,_=scan_root_inputs(self.current_parsed,self.data_defs,self.wasj_configs)
            preview=preview_wasj(self.current_parsed,self.data_defs,rows,occ,cfg)
            for label,values in preview.role_values.items():
                inferred={key:value for key,value in values.items() if key in valid and value != ""}
                if inferred:cfg.role_values[label]=inferred
        self.refresh_role_tree()

    def _parse_role_text(self,text):
        result={}
        for part in text.split(";"):
            if "=" in part:
                k,v=part.split("=",1);k=k.strip();v=v.strip()
                if k:result[k]=v
        return result
    def _role_text(self,mapping):return "; ".join(f"{k}={v}" for k,v in mapping.items())

    def refresh_role_tree(self):
        self.role_tree.delete(*self.role_tree.get_children())
        occ=self._occurrence_by_wasj_id(self.current_wasj_id);cfg=self.wasj_configs.get(self.current_wasj_id)
        if not occ or not cfg:return
        keys=cfg.normalized_difference_keys()
        self.role_tree.heading("role",text=f"Expected Difference values ({', '.join(keys)})" if keys else "Expected Difference values")
        for label in occ.input_labels:
            if label in self.current_parsed.root_data and self.data_defs.get(label,DataDef(label)).normalized_input_mode()==MODE_SHARED:difference="SHARED RESOURCE"
            else:difference=self._role_text({key:value for key,value in cfg.role_values.get(label,{}).items() if key in keys}) or "UNDEFINED"
            self.role_tree.insert("","end",iid=label,values=(label,difference))

    def load_role(self,_e=None):
        sel=self.role_tree.selection()
        if not sel:return
        label=sel[0];cfg=self.wasj_configs.get(self.current_wasj_id);self.role_label.set(label);self.role_values.set(self._role_text(cfg.role_values.get(label,{})) if cfg else "")
    def save_role(self):
        label=self.role_label.get().strip();cfg=self.wasj_configs.get(self.current_wasj_id)
        if not label or not cfg:return
        cfg.role_values[label]=self._parse_role_text(self.role_values.get());self.refresh_role_tree();self.status_var.set(f"Saved WASJ Difference values for {label}.")

    def save_wasj(self):
        bid=self.w_id.get().strip()
        if not bid:return
        self._sync_current_wasj_config();self._refresh_difference_values_from_metadata();self.refresh_wasj_tree();self.status_var.set(f"Saved {bid} metadata configuration.")

    def infer_wasj_roles(self):
        self.save_wasj();occ=self._occurrence_by_wasj_id(self.current_wasj_id);cfg=self.wasj_configs.get(self.current_wasj_id)
        if not occ or not cfg:return
        parsed,_=self._parse_and_sync();rows,_=scan_root_inputs(parsed,self.data_defs,self.wasj_configs);preview=preview_wasj(parsed,self.data_defs,rows,occ,cfg)
        for label,mapping in preview.role_values.items():
            cfg.role_values[label]=mapping
        self.refresh_role_tree();self._show_wasj_preview(preview);self.status_var.set("Auto-inferred constant Difference values where possible.")

    def preview_selected_wasj(self):
        self.save_wasj();occ=self._occurrence_by_wasj_id(self.current_wasj_id);cfg=self.wasj_configs.get(self.current_wasj_id)
        if not occ or not cfg:
            messagebox.showinfo("WASJ","Select a WASJ block first.",parent=self.root);return
        parsed,_=self._parse_and_sync();rows,scan_issues=scan_root_inputs(parsed,self.data_defs,self.wasj_configs);preview=preview_wasj(parsed,self.data_defs,rows,occ,cfg);preview.issues[:0]=scan_issues;self._show_wasj_preview(preview)

    def _show_wasj_preview(self,preview):
        lines=[f"WASJ PAIRING PREVIEW — {preview.barrier_id}",f"Join key: {preview.join_key or '(undefined)'}",f"Difference keys: {', '.join(preview.difference_keys) or '(undefined)'}",""]
        lines.append("Expected/inferred Difference values:")
        for label in preview.input_labels:lines.append(f"  {label}: {self._role_text(preview.role_values.get(label,{})) or '(none/shared)'}")
        lines.append("")
        header=["JOIN KEY"]+preview.input_labels;lines.append("\t".join(header))
        for row in preview.rows:lines.append("\t".join([row.get("join_key","")]+[row.get(label,"") for label in preview.input_labels]))
        lines.append("")
        errors=[x for x in preview.issues if x.level=="ERROR"]
        lines += [str(x) for x in preview.issues] if preview.issues else [f"VALID: {len(preview.rows)} complete matched Join-key group(s)."]
        lines.append("");lines.append("STATUS: INVALID" if errors else "STATUS: VALID")
        self._set_text(self.wasj_preview,"\n".join(lines))




    def _all_validation(self,require_files=False):
        parsed,issues=self._parse_and_sync();issues+=validate_definitions(parsed,self.programs,self.data_defs,self.wasj_configs,require_files=require_files);rows,scan_issues=scan_root_inputs(parsed,self.data_defs,self.wasj_configs);issues+=scan_issues
        if rows:issues+=validate_wasj_configs(parsed,self.data_defs,rows,self.wasj_configs)
        expected_outputs,publication_issues=calculate_expected_published_outputs(parsed,self.programs,self.data_defs,self.wasj_configs,rows,self.results_var.get().strip() or "results")
        issues+=publication_issues;self.expected_published_outputs=expected_outputs
        self.manifest_rows=rows;self.last_issues=issues;self.refresh_program_tree();self.refresh_data_tree();self.refresh_wasj_tree();self.refresh_grid_flow_colors(parsed);return parsed,issues

    def validate_and_diagram(self):
        parsed,issues=self._all_validation(require_files=False);errors=[i for i in issues if i.level=="ERROR"]
        shared=[x for x in sorted(parsed.root_data) if self.data_defs.get(x,DataDef(x)).normalized_input_mode()==MODE_SHARED]
        lines=["VALIDATION SUMMARY",f"Programs: {len(parsed.program_ids)}",f"Data words: {len(parsed.data_labels)}",f"Root inputs: {', '.join(sorted(parsed.root_data)) or '(none)'}",f"Shared resources: {', '.join(shared) or '(none)'}",f"Program occurrences: {len(parsed.occurrences)}",f"Expected published files: {len(getattr(self,'expected_published_outputs',[]))}",f"WAS blocks: {len(parsed.was_blocks)}",f"WASG cells: {len(parsed.wasg_cells)}",f"WASJ blocks: {len(parsed.wasj_blocks)}",f"Resolved wire cells: {len(parsed.wire_sources)}",""]
        lines += [str(i) for i in issues] if issues else ["OK: grid grammar, definitions, metadata keys, and WASJ pairings are structurally valid."]
        self._set_text(self.validation_text,"\n".join(lines));self.draw_diagram(parsed,errors);self.notebook.select(3);self.status_var.set("Validation passed." if not errors else f"Validation found {len(errors)} error(s).")
        return not errors

    def _diagram_round_rect(self, canvas, x1, y1, x2, y2, radius=14, **options):
        radius = min(radius, (x2-x1)/2, (y2-y1)/2)
        points = [
            x1+radius,y1, x2-radius,y1, x2,y1, x2,y1+radius,
            x2,y2-radius, x2,y2, x2-radius,y2, x1+radius,y2,
            x1,y2, x1,y2-radius, x1,y1+radius, x1,y1,
        ]
        return canvas.create_polygon(points, smooth=True, splinesteps=18, **options)

    def draw_diagram(self,parsed,errors):
        cv=self.diagram;cv.delete("all");cv.configure(background="#F8FAFC")
        grid=parsed.grid;rows=len(grid);cols=len(grid[0]) if grid else 0
        cw,ch=180,98;origin_x,origin_y=58,48;node_w,node_h=128,54
        diagram_width=max(1060,origin_x+cols*cw+55)
        error_cells={cell for issue in errors for cell in issue.cells}

        def bounds(r,c):
            x=origin_x+c*cw+18;y=origin_y+r*ch+21
            return x,y,x+node_w,y+node_h

        def center(r,c):
            x1,y1,x2,y2=bounds(r,c);return (x1+x2)/2,(y1+y2)/2


        for r in range(rows):
            lane_y=origin_y+r*ch+5
            cv.create_rectangle(10,lane_y,diagram_width-20,lane_y+ch-10,fill="#FFFFFF" if r%2==0 else "#F1F5F9",outline="")
            cv.create_text(28,lane_y+(ch-10)/2,text=f"R{r+1}",fill="#94A3B8",font=("TkDefaultFont",8,"bold"))


        for r in range(rows):
            for c in range(cols-1):
                a,b=grid[r][c],grid[r][c+1]
                if not a or not b or token_kind(a)=="note" or token_kind(b)=="note":continue
                _,cy=center(r,c);x1=bounds(r,c)[2]+3;x2=bounds(r,c+1)[0]-5
                cv.create_line(x1,cy,x2,cy,arrow="last",arrowshape=(9,11,4),width=3,fill="#94A3B8",capstyle="round")


        for (r,c),source in parsed.wire_sources.items():
            if grid[r][c]=="|":
                cx,_=center(r,c);top=origin_y+r*ch+4;bottom=origin_y+(r+1)*ch+4
                cv.create_line(cx,top,cx,bottom,width=5,fill=C_BLUE,capstyle="round")
                cv.create_text(cx+9,top+7,anchor="nw",text=source,fill=C_BLUE,font=("TkDefaultFont",8,"bold"))
        for _token,blocks,color in (("WAS",parsed.was_blocks,C_WAS_EDGE),("WASJ",parsed.wasj_blocks,C_WASJ_EDGE)):
            for block in blocks:
                if len(block)>1:
                    first_r,c=block[0];last_r=block[-1][0];cx,_=center(first_r,c)
                    cv.create_line(cx,center(first_r,c)[1],cx,center(last_r,c)[1],width=7,fill=color,capstyle="round")

        for r,row in enumerate(grid):
            for c,token in enumerate(row):
                if not token:continue
                kind=token_kind(token);x1,y1,x2,y2=bounds(r,c);cx,cy=center(r,c)
                if kind=="wire_v":continue
                if kind=="wire_h":
                    cv.create_line(x1-12,cy,x2+12,cy,width=5,fill=C_BLUE,capstyle="round")
                    continue
                if kind=="note":
                    self._diagram_round_rect(cv,x1,y1+7,x2,y2-7,radius=10,fill=C_NOTE,outline="#CBD5E1",width=1)
                    cv.create_text(cx,cy,text=token,fill=C_EDGE,width=node_w-12,font=("TkDefaultFont",8,"italic"))
                    continue
                if (r,c) in error_cells:bg,edge=C_ERROR,C_RED
                elif token=="WAS":bg,edge=C_WAS,C_WAS_EDGE
                elif token=="WASG":bg,edge=C_WASG,C_WASG_EDGE
                elif token=="WASJ":bg,edge=C_WASJ,C_WASJ_EDGE
                elif kind=="program":bg,edge=C_PROGRAM,C_PURPLE
                else:
                    shared=token in parsed.root_data and self.data_defs.get(token,DataDef(token)).normalized_input_mode()==MODE_SHARED
                    if shared:bg,edge=C_SHARED,C_TEAL
                    elif self._stream_is_parallel(token, parsed):bg,edge=C_DATA,C_BLUE
                    else:bg,edge=C_SERIAL,C_SERIAL_EDGE

                self._diagram_round_rect(cv,x1+4,y1+5,x2+4,y2+5,radius=14,fill="#CBD5E1",outline="")
                self._diagram_round_rect(cv,x1,y1,x2,y2,radius=14,fill=bg,outline=edge,width=3)
                label=token
                if kind=="program" and token in self.programs:label=f"{token}\n{self.programs[token].normalized_name()}"
                cv.create_text(cx,cy,text=label,width=node_w-14,fill=C_TEXT,font=("TkDefaultFont",9,"bold" if kind in ("program","reserved") else "normal"),justify="center")


        legend_y=origin_y+rows*ch+22;legend_x=22
        legend=[("Parallel data",C_DATA,C_BLUE),("Serial/cohort",C_SERIAL,C_SERIAL_EDGE),("Program",C_PROGRAM,C_PURPLE),("WAS",C_WAS,C_WAS_EDGE),("WASG",C_WASG,C_WASG_EDGE),("WASJ",C_WASJ,C_WASJ_EDGE),("Shared",C_SHARED,C_TEAL),("Error",C_ERROR,C_RED)]
        for text,fill,edge in legend:
            self._diagram_round_rect(cv,legend_x,legend_y,legend_x+18,legend_y+18,radius=5,fill=fill,outline=edge,width=2)
            cv.create_text(legend_x+24,legend_y+9,anchor="w",text=text,fill=C_TEXT,font=("TkDefaultFont",8,"bold"))
            legend_x+=118 if text in ("Parallel data","Serial/cohort") else 88 if text!="Program" else 105
        cv.configure(scrollregion=(0,0,diagram_width,max(520,legend_y+55)))




    def preview_main(self):
        parsed,issues=self._all_validation(require_files=False);errors=[i for i in issues if i.level=="ERROR"]
        if errors:messagebox.showerror("Cannot preview","Fix validation errors first:\n\n"+"\n".join(str(x) for x in errors[:15]),parent=self.root);self.validate_and_diagram();return
        try:content=render_main_nf(parsed,self.programs,self.data_defs,self.wasj_configs,self.results_var.get().strip() or "results",self.publish_mode_var.get(),self.convert_var.get(),self.cache_enabled_var.get())
        except Exception as exc:messagebox.showerror("Preview error",str(exc),parent=self.root);return
        self._set_text(self.main_preview,content);self.notebook.select(4);self.status_var.set("main.nf preview generated from validated NextDash graph.")

    def stub_validate(self):
        parsed,issues=self._all_validation(require_files=True);errors=[i for i in issues if i.level=="ERROR"]
        if errors:messagebox.showerror("Stub validation blocked","Fix validation errors first:\n\n"+"\n".join(str(x) for x in errors[:15]),parent=self.root);self.validate_and_diagram();return
        try:main_text=render_main_nf(parsed,self.programs,self.data_defs,self.wasj_configs,self.results_var.get().strip() or "results",self.publish_mode_var.get(),self.convert_var.get(),self.cache_enabled_var.get());manifest_text=render_manifest_tsv(self.manifest_rows,self.convert_var.get())
        except Exception as exc:messagebox.showerror("Stub validation",str(exc),parent=self.root);return
        self.status_var.set("Running Nextflow -stub-run in a temporary folder…")
        def worker():
            temp_dir=Path(tempfile.mkdtemp(prefix="nextdash_v8_stub_"))
            try:
                (temp_dir/"main.nf").write_text(main_text,encoding="utf-8");(temp_dir/"input_manifest.tsv").write_text(manifest_text,encoding="utf-8")
                if os.name=="nt":
                    command=f"cd {shlex.quote(windows_path_to_wsl(str(temp_dir)))} && nextflow run main.nf -stub-run";completed=subprocess.run(["wsl","bash","-lc",command],capture_output=True,text=True,timeout=300)
                else:completed=subprocess.run(["nextflow","run","main.nf","-stub-run"],cwd=temp_dir,capture_output=True,text=True,timeout=300)
                output=(completed.stdout or "")+("\n"+completed.stderr if completed.stderr else "");ok=completed.returncode==0
            except Exception as exc:ok=False;output=str(exc)
            finally:shutil.rmtree(temp_dir,ignore_errors=True)
            self.root.after(0,lambda:self._stub_done(ok,output))
        threading.Thread(target=worker,daemon=True).start()
    def _stub_done(self,ok,output):
        self.status_var.set("Nextflow stub validation PASSED." if ok else "Nextflow stub validation FAILED.");messagebox.showinfo("Nextflow -stub-run" if ok else "Nextflow -stub-run failed",output[-12000:] or ("PASSED" if ok else "FAILED"),parent=self.root)

    def browse_output_dir(self):
        p=filedialog.askdirectory(parent=self.root,title="Choose generated project folder")
        if p:
            self.output_dir_var.set(p)
            self.refresh_cache_size()

    @staticmethod
    def _format_byte_size(size: int) -> str:
        value = float(size)
        units = ("B", "KB", "MB", "GB", "TB", "PB")
        for unit in units:
            if value < 1024.0 or unit == units[-1]:
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.2f} {unit}"
            value /= 1024.0
        return f"{size} B"

    def _cache_targets(self) -> tuple[Path, list[Path]]:
        raw = self.output_dir_var.get().strip()
        if not raw:
            raise NetDashError("Choose an output project folder first.")
        project = Path(raw).expanduser().resolve(strict=False)
        return project, [project / "work", project / ".nextflow" / "cache"]

    @staticmethod
    def _path_size(path: Path) -> int:
        if not path.exists() and not path.is_symlink():
            return 0
        if path.is_symlink():
            return path.lstat().st_size
        total = 0
        for root, dirs, files in os.walk(path, followlinks=False):
            dirs[:] = [name for name in dirs if not (Path(root) / name).is_symlink()]
            for name in files:
                item = Path(root) / name
                try:
                    total += item.lstat().st_size
                except OSError:
                    pass
        return total

    def refresh_cache_size(self):
        try:
            project, targets = self._cache_targets()
        except Exception as exc:
            self.cache_size_var.set(f"Cached task data: unavailable ({exc})")
            return
        self.cache_size_var.set("Cached task data: scanning…")

        def worker():
            size = sum(self._path_size(path) for path in targets)
            text = f"Cached task data in {project}: {self._format_byte_size(size)}"
            self.root.after(0, lambda: self.cache_size_var.set(text))

        threading.Thread(target=worker, daemon=True).start()

    def remove_cached_data(self):
        try:
            project, targets = self._cache_targets()
            existing = [path for path in targets if path.exists() or path.is_symlink()]
            size = sum(self._path_size(path) for path in existing)
        except Exception as exc:
            messagebox.showerror("Remove cached data", str(exc), parent=self.root)
            return
        if not existing:
            self.cache_size_var.set(f"Cached task data in {project}: 0 B")
            messagebox.showinfo("Remove cached data", "No work cache was found in the selected project.", parent=self.root)
            return
        results_path = project / (self.results_var.get().strip() or "results")
        linked_results: list[Path] = []
        if results_path.is_dir():
            for root, dirs, files in os.walk(results_path, followlinks=False):
                for name in [*dirs, *files]:
                    item = Path(root) / name
                    if item.is_symlink():
                        try:
                            destination = item.resolve(strict=False)
                            if any(destination == target.resolve(strict=False) or target.resolve(strict=False) in destination.parents for target in targets):
                                linked_results.append(item)
                        except OSError:
                            linked_results.append(item)
        if linked_results:
            examples = "\n".join(str(path) for path in linked_results[:5])
            messagebox.showerror(
                "Remove cached data",
                f"Removal was stopped because {len(linked_results)} result file(s) are links into the work cache, for example:\n\n"
                f"{examples}\n\nCopy those result files to independent files first, or regenerate the project with the new 'copy' mode. "
                "Deleting the cache now would destroy access to those results.",
                parent=self.root,
            )
            return
        listed = "\n".join(str(path) for path in existing)
        if not messagebox.askyesno(
            "Remove cached data",
            f"Delete {self._format_byte_size(size)} of cached task data?\n\n{listed}\n\n"
            "Only continue after every Nextflow run using this project has stopped. "
            "This cannot be undone and -resume will no longer reuse these tasks. "
            "Independent result copies and project files will not be deleted.",
            parent=self.root,
        ):
            return
        try:
            for target in existing:
                resolved = target.resolve(strict=False)
                if resolved == project or project not in resolved.parents:
                    if target.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(target)):
                        target.unlink()
                        continue
                    raise NetDashError(f"Refusing to delete a cache path outside the selected project: {target}")
                shutil.rmtree(target)
            self.cache_size_var.set(f"Cached task data in {project}: 0 B")
            self.status_var.set(f"Removed {self._format_byte_size(size)} of cached task data from {project}.")
            messagebox.showinfo("Remove cached data", f"Removed {self._format_byte_size(size)}. Published results were preserved.", parent=self.root)
        except Exception as exc:
            messagebox.showerror("Remove cached data", f"Cache removal was not completed:\n{exc}", parent=self.root)
    def generate_project(self):
        parsed,issues=self._all_validation(require_files=True);errors=[i for i in issues if i.level=="ERROR"]
        if errors:messagebox.showerror("Generation blocked","Fix validation errors first:\n\n"+"\n".join(str(x) for x in errors[:18]),parent=self.root);self.validate_and_diagram();return
        try:out=save_project(Path(self.output_dir_var.get()),self.sheet.get_grid(),parsed,self.programs,self.data_defs,self.wasj_configs,self.manifest_rows,self.results_var.get().strip() or "results",self.publish_mode_var.get(),self.convert_var.get(),self.overwrite_var.get(),self.cache_enabled_var.get())
        except Exception as exc:messagebox.showerror("Generation error",str(exc),parent=self.root);return
        self.status_var.set(f"Generated Nextflow project: {out}");self.refresh_cache_size();messagebox.showinfo("Generated",f"Created:\n{out/'main.nf'}\n{out/'input_manifest.tsv'}\n{out/'NextDash.tabtxt'}\n{out/'DEFINITIONS.txt'}\n{out/'ROUTING.tsv'}",parent=self.root)


    def _set_text(self,widget,text):
        widget.configure(state="normal");widget.delete("1.0","end");widget.insert("1.0",text);widget.configure(state="disabled")


def main():
    root=tk.Tk();NetDashApp(root);root.mainloop();return 0


if __name__=="__main__":
    raise SystemExit(main())
