# Step 1 — STARsolo alignment and UMI counting

`Starsolo_Rscript.R` converts paired 10x Genomics FASTQ files into sparse gene-by-cell-barcode count matrices with STARsolo. The script uses the `Input` and `Output` directories located beside the script.

## Role in the pipeline

This is the first analytical stage of the Chromium single-cell workflow:

```text
Paired FASTQ files
        ↓
STAR genome alignment
        ↓
Cell-barcode and UMI processing
        ↓
Filtered and raw gene-by-barcode matrices
        ↓
Step 2: Seurat import and cell QC
```

The filtered STARsolo matrices produced here are read by `2_Seurat/Seurat_QC_Rscript.R`.

## Input directory

The script searches recursively under `Input/` for three input types.

### Paired FASTQ files

Read 1 filenames must end with either:

```text
_R1.fastq.gz
_R1_001.fastq.gz
```

The corresponding Read 2 file is identified by replacing `_R1` with `_R2`. Common Illumina names such as the following are recognized:

```text
Sample01_S1_L001_R1_001.fastq.gz
Sample01_S1_L001_R2_001.fastq.gz
```

The sample name is derived from the portion preceding the sample, lane, and read suffixes. FASTQ pairs from multiple lanes with the same derived sample name are grouped into one STARsolo command.

For the supported 10x 3′ layouts, R1 contains the cell barcode and UMI, while R2 contains the cDNA sequence. STAR receives R2 first and R1 second through `--readFilesIn`.

### STAR genome index

Exactly one directory under `Input/` must contain:

```text
Genome
SA
SAindex
```

That directory is passed to STAR through `--genomeDir`.

### Barcode whitelist

Exactly one recursively discovered filename must contain `whitelist` or `barcodes` and end in `.txt` or `.txt.gz`. A gzipped whitelist is decompressed into `Output/barcode_whitelist_decompressed.txt` before STAR is invoked.

## Script settings

| Setting | Default | Function |
| --- | ---: | --- |
| `STAR_EXECUTABLE` | `/usr/local/bin/STAR` | Linux path to the STAR executable. |
| `WSL_DISTRIBUTION` | `Debian` | WSL distribution used when the script runs from native Windows R. |
| `THREADS` | `12` | Value passed to STAR as `--runThreadN`. |
| `CHEMISTRY` | `10x_3p_v3` | Selects the cell-barcode and UMI coordinates. |
| `CREATE_BAM` | `FALSE` | Controls whether STAR writes an unsorted BAM file. |
| `CELL_FILTER_METHOD` | `EmptyDrops_CR` | Value passed to `--soloCellFilter`. |

The chemistry presets are:

| Preset | Cell barcode | UMI |
| --- | --- | --- |
| `10x_3p_v3` | bases 1–16 of R1 | bases 17–28 of R1 |
| `10x_3p_v2` | bases 1–16 of R1 | bases 17–26 of R1 |

## STARsolo command

For each sample, the script constructs a STAR command containing:

```text
--soloType CB_UMI_Simple
--soloCBmatchWLtype 1MM_multi_Nbase_pseudocounts
--soloUMIfiltering MultiGeneUMI_CR
--soloUMIdedup 1MM_CR
--soloCellFilter EmptyDrops_CR
--clipAdapterType CellRanger4
--outFilterScoreMin 30
--soloFeatures Gene GeneFull Velocyto
```

The cell-barcode and UMI start/length arguments are added from `CHEMISTRY`. Gzipped FASTQ files are read with `zcat`.

When BAM creation is enabled, STAR receives:

```text
--outSAMtype BAM Unsorted
--outSAMattributes NH HI nM AS CR UR CB UB GX GN sS sQ sM
```

Otherwise, `--outSAMtype None` is used.

## Windows and Linux execution

On Windows, the script converts Windows paths with `wslpath`, writes the STAR command to a temporary shell script, and executes it through:

```text
wsl.exe -d Debian -- bash <temporary command file>
```

On Linux, the command is passed to `bash -lc`. Each sample uses a process-specific temporary STAR directory under `/tmp`, which is removed when the command finishes.

## Input detection output

`detected_FASTQ_manifest.csv` records one row per detected FASTQ pair:

| Column | Content |
| --- | --- |
| `sample_id` | Sample name derived from the R1 filename. |
| `R1` | Absolute path to the barcode/UMI FASTQ. |
| `R2` | Absolute path to the cDNA FASTQ. |

## STARsolo result structure

Each sample receives its own directory below `Output/`:

```text
Output/
└── <sample_id>/
    └── <sample_id>_Solo.out/
        └── Gene/
            ├── filtered/
            │   ├── matrix.mtx
            │   ├── barcodes.tsv
            │   └── features.tsv
            ├── raw/
            │   └── matrix.mtx
            └── Summary.csv
```

The script verifies the presence of the filtered matrix, filtered barcodes, filtered features, raw matrix, and STARsolo summary after every sample command.

## Output manifest

`STARsolo_output_manifest.csv` contains one row per completed sample:

| Column | Content |
| --- | --- |
| `sample_id` | Derived sample identifier. |
| `filtered_matrix_directory` | Absolute path to the filtered `Gene` matrix directory. |
| `raw_matrix_directory` | Absolute path to the raw `Gene` matrix directory. |
| `summary_file` | Absolute path to `Summary.csv`. |

## Logging and session information

`run_log.txt` receives the resolved directories, start time, complete STAR command for every sample, messages, errors, and the R session information printed during script exit.

`sessionInfo.txt` contains a second standalone copy of the R session information after successful completion.
