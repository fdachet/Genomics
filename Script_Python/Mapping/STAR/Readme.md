# STAR GUI for RNA-seq mapping

`Star_V52.py` is a small Windows/Tkinter interface for running [STAR](https://github.com/alexdobin/STAR) through WSL. It is made for the practical part of RNA-seq analysis: selecting FASTQ files, checking their pairing, building readable STAR commands, and running several samples without manually rewriting long command lines each time.

It is not a replacement for checking mapping quality. The GUI makes the STAR options more visible, but the final judgement still comes from the STAR log files, the BAM files, and the biology of the experiment.

## The important difference: genome index versus mapping

These two operations are easy to confuse at the beginning, but they do very different jobs.

| Operation | Input | What STAR creates | When it is needed |
| --- | --- | --- | --- |
| **Build Genome Index** | Reference genome FASTA, optionally a GTF annotation | A `genomeDir` folder containing STAR lookup/index files | Usually once per genome + annotation version. Rebuild only when the reference, annotation, or important index setting changes. |
| **Align Reads** | FASTQ reads from each sample and an existing `genomeDir` | SAM/BAM alignments, splice-junction table, logs, and optionally unmapped FASTQ | Once for every sequencing sample (or again if mapping settings change). |

An index is like preparing the very large book index before reading a pile of documents. STAR uses it to rapidly find where each sequencing read belongs in the reference genome. Mapping is the later step where the real reads are compared against this prepared reference. Do **not** point `STAR Index (genomeDir)` at a FASTA file: it must point to the folder produced by **Build Genome Index**.

For ordinary human RNA-seq, use the same genome assembly and compatible annotation everywhere. For example, do not create an index from GRCh38 FASTA and then interpret the results with a GTF intended for another assembly or another annotation release.

## Requirements

- Windows with WSL available (`wsl` must open from PowerShell or Command Prompt).
- STAR installed inside the WSL Linux distribution and available as `STAR` on the Linux `PATH`.
- `samtools` installed in WSL if the **Create BAM index (.bai)** option is used.
- Read access to FASTQ, FASTA and GTF files, plus write access to the output folder.
- Enough RAM and disk space. Genome indexing and coordinate-sorted BAM files can use a lot of both.

The GUI converts normal Windows paths such as `P:\Data\sample.fastq.gz` into WSL paths such as `/mnt/p/Data/sample.fastq.gz`. When the output folder is on a Windows-mounted drive (`/mnt/...`), it automatically sends STAR temporary work to Linux `/tmp`. This avoids a known FIFO/temporary-file problem on NTFS mounted drives. The temporary folder is cleaned after the sample finishes, including after a failure when possible.

## Quick use

1. Start the GUI with Python on Windows:

   ```powershell
   python Star_V52.py
   ```

2. If this is a new reference, choose **Build Genome Index** and create the `genomeDir` first.
3. Choose **Align Reads** for the routine analysis.
4. Select the reads folder, click **Scan Reads**, review the detected samples, and select the ones to run.
5. Select the existing **STAR Index (genomeDir)** and an output directory.
6. Choose the output type and the mapping options appropriate for the experiment.
7. Click **Run STAR**. A window first shows the complete command(s); this is a useful last check before starting.
8. Read `Log.final.out` for every sample before continuing to counting or differential expression.

## Screenshot: relaxed RNA-seq mapping

![STAR GUI with relaxed mapping settings](Screenshot/Mapping_Relaxed.png)

*Figure 1. The alignment screen of the STAR GUI. The left radio button, **Align Reads**, is selected, so the fields needed for FASTQ mapping are active and the FASTA/GTF index-building fields are greyed out. At the top, ten threads are assigned to one mapping job; `Parallel mappings: 1` means samples will run one after another, which is safer when RAM is limited. The output is a coordinate-sorted BAM with 12 GB reserved for BAM sorting and an accompanying `.bai` index. The green panel is the selected **Relaxed** mode. It spells out the actual filter values so the user can see that relaxed mapping is more permissive for partial or weak RNA-seq reads, while keeping the multi-locus acceptance limit at 10. The lower panes are intentionally empty in this example: after scanning a reads directory, the left pane lists detected samples and pairing/compression status; during the run, the right pane receives STAR messages and the progress section shows completed samples and an estimated remaining time.*

## Alignment mode: fields and functions

### Sample discovery and compute settings

| GUI function | What it does | Why it is there |
| --- | --- | --- |
| **Threads per mapping (physical cores)** | Sets STAR `--runThreadN` for one sample. | More threads can make one mapping faster, but each concurrent sample needs its own memory. Start with physical cores rather than assuming all logical cores are free. |
| **Parallel mappings** | Runs several sample commands in parallel; `0` or `1` runs serially. | Useful for many small jobs, but total CPU/RAM is approximately threads × parallel jobs. For a large mammalian genome, avoid high parallelism unless the computer has sufficient RAM. |
| **Paired-end** | Tells the scan to look for `R1` and `R2` mates. | Proper mate pairing gives STAR insert-size and paired-read information. The scan reports missing mates instead of silently treating a broken pair as normal. |
| **Reads Directory** | Folder containing FASTQ/FASTQ.gz (also `.fq`, and some `mate1`/`mate2` names). | This is the source data. The script does not modify the original FASTQ files. |
| **Scan Reads (R1/R2 pairing + compression)** | Detects candidate files, groups `R1`/`R2`, and notes compressed files. | It gives a simple quality control before a long run. Compressed reads are automatically passed with STAR `--readFilesCommand zcat`. Carefully inspect unusual naming, because automatic detection can only follow the file names it sees. |
| **Detected Samples / Select All** | Lets the user choose the samples to map. | Allows a subset or a rerun of failed samples without rerunning everything. |
| **STAR Index (genomeDir)** | Existing STAR reference-index folder. | Required for alignment. It contains the genome search structures created by the index mode, not raw FASTA. |
| **Output Directory** | Writes STAR output with one prefix per sample. | Keeps BAMs, logs and splice junction files together. Use a new folder for a distinct run/settings combination so results are traceable. |

### Alignment outputs and performance options

| GUI function | STAR behaviour | Why it is there |
| --- | --- | --- |
| **Output SAM / BAM** | Chooses `BAM Unsorted`, `BAM SortedByCoordinate`, or `SAM` via `--outSAMtype`. | Coordinate-sorted BAM is normally the convenient choice for viewing in IGV, counting, and downstream QC. Unsorted BAM may be faster if another program will sort it. SAM is plain text and large, so it is usually only useful for debugging. |
| **limitBAMsortRAM (GB)** | Converts GB to bytes for `--limitBAMsortRAM`. | Prevents coordinate sorting from trying to use more RAM than you planned. If too low, sorting can fail or be slow; if too high, Windows/WSL can become unstable. |
| **Create BAM index (.bai) with samtools** | Runs `samtools index` after a BAM is made. | A `.bai` lets IGV and many tools jump directly to a genomic region instead of scanning the full BAM. It makes most sense for coordinate-sorted BAM. |
| **Keep genome in shared memory** | Adds `--genomeLoad LoadAndKeep`. | Keeps the STAR index loaded for later samples, so serial mapping can start faster. It consumes substantial shared memory and should be used only when the computer has room. |
| **2-pass mapping** | Adds `--twopassMode Basic`. | STAR first discovers splice junctions, then remaps reads using those junctions. This can improve splice-aware RNA-seq alignment, especially when sample-specific junctions matter. It is deliberately mutually exclusive with `LoadAndKeep` in this GUI because the combination is not a simple memory-saving setup. |
| **Save unmapped reads (FastQ)** | Adds `--outReadsUnmapped Fastx`; optional folder moves/renames the output. | Useful when investigating viral/bacterial material, contamination, an alternative genome, or poor mapping. These reads can be analysed separately. |
| **Discard mapped alignments (keep only unmapped reads)** | Sets `--outSAMtype None` and removes alignment files while retaining logs. | Makes an explicit unmapped-read workflow without filling disk with BAMs. It requires saving unmapped reads, because otherwise there would be no useful result left apart from logs. |
| **Advanced STAR options** | Appends extra parameters exactly as space-separated STAR arguments. | Gives experienced users access to special STAR options without changing the script. Use with care: an advanced option can override a GUI choice or make the run hard to reproduce if it is not recorded. |

The GUI adds useful alignment tags (`NH`, `HI`, `AS`, `nM`, `NM`, `MD`, `jM`, `jI`, `XS`) to the SAM/BAM record and marks uniquely mapped reads with MAPQ 255. These tags preserve information such as alignment score, mismatches, multiplicity and splice-junction details for later inspection.

### Mapping accuracy: Default, Relaxed, Strict

The accuracy selection controls STAR filters; it does not make a bad library good. **Default** is the sensible reference run for most datasets. Run relaxed mode only when there is a biological reason to rescue weak/partial reads, and compare its `Log.final.out` with Default.

| Mode | Main values used by the GUI | When it can help | Main caution |
| --- | --- | --- | --- |
| **Default** | Uses STAR internal defaults (mismatch max 10; mismatch fraction 0.30; multimap max 10; minimum score/matched fraction 0.66). | Standard RNA-seq baseline. | Still check mapping rate, mismatch rate, and rRNA/repeat behaviour. |
| **Relaxed** | Mismatch max 20; mismatch fraction 0.20; multimap max remains 10; minimum score and matched fraction 0.33. | Degraded tissue, low-input RNA, or an exploratory search for reproducible low-expression RNA signal. | More partial/weak alignments survive. Confirm that any gain is mainly unique or low-multimap reads on credible exons/junctions, not random/repeat signal. The GUI limits BAM lines for multimappers in this mode to help control output size. |
| **Strict** | Mismatch max 3; mismatch fraction 0.03; multimap max 5; minimum score and matched fraction 0.70. | A conservative sensitivity analysis or a dataset where incorrect matches are a major concern. | It will discard more real reads, particularly shorter, lower-quality or biologically variable reads. |

For a relaxed comparison, look for an increase in uniquely mapped reads and reasonable mapped length. Be suspicious if the multiple-loci fraction, reads mapping to too many loci, or mismatch rate rises a lot. For RNA-seq, rescued reads should still support known exons and splice junctions and be reproducible across relevant samples.

### Genome / gene structure

| Option | What STAR receives | Typical use |
| --- | --- | --- |
| **Spliced** | `--outFilterType BySJout` and `--outSAMstrandField intronMotif`. | Normal eukaryotic RNA-seq, where mature RNA reads can span introns. This is the default and the usual choice for transcriptome data. |
| **Unspliced** | `--alignIntronMax 1`, `--alignSJoverhangMin 999`, normal filter type, no strand field. | Genomic DNA, prokaryotic data, or a deliberately intron-free mapping problem. It blocks normal splice junction behaviour. |

## Build Genome Index mode

When **Build Genome Index** is selected, the mapping-specific FASTQ controls are disabled and three fields matter:

| GUI function | What it does | Why it is there |
| --- | --- | --- |
| **Genome FASTA Files** | One or more reference genome FASTA files passed as `--genomeFastaFiles`. Compressed `.gz` FASTA is supported when estimating length. | This is the genome sequence that reads will map against. Multiple chromosome/contig FASTA files may be selected together. |
| **Annotation GTF File** | Optional `--sjdbGTFfile`. | Adds known exon-exon junctions to the STAR index. For standard RNA-seq this is strongly recommended: annotated splice junctions are represented during mapping. |
| **Output Directory** | Used as `--genomeDir`. | This is where STAR writes the index. It becomes the folder selected later in **STAR Index (genomeDir)**. Do not put ordinary alignment output in the same place. |
| **Threads per mapping** | Used as `--runThreadN` during `--runMode genomeGenerate`. | Genome generation can use several CPUs; this label is shared with mapping mode for simplicity. |
| **Advanced STAR options** | Added to the genome-generation command. | Supports special references or manual STAR index settings. |

The script calculates `--genomeSAindexNbases` from the total FASTA length using STAR's standard logarithmic rule, capped between 1 and 14. This avoids a common manual setting mistake. If an advanced option already includes `--genomeSAindexNbases`, the automatic calculation is intentionally skipped and the manual value wins.

Index creation may take time and consumes storage, but it is generally done once per clearly defined reference. Record the genome build, FASTA source/version, GTF version, date and any advanced options with the resulting `genomeDir`. A small change in annotation can change splice-junction handling and therefore mapping/counting results.

## What files to inspect after mapping

For each sample, STAR commonly creates files using the selected sample prefix:

- `*_Log.final.out` — the first QC report to read: uniquely mapped rate, multi-mapping, too-many-loci reads, mismatch rate, splice junctions, and more.
- `*_Aligned.sortedByCoord.out.bam` — coordinate-sorted reads when that output was selected.
- `*.bai` — BAM index, when requested.
- `*_SJ.out.tab` — detected splice junctions (unless running the unmapped-only option, where the script removes alignment-associated files).
- `*_Unmapped.out.mate1` / `mate2` — unmapped reads when saving them; the GUI can move and rename them to the chosen unmapped folder.
- `*_Log.out` and related STAR logs — useful if a job fails or an option needs auditing.

Do not judge a sample only from “mapping completed”. A high mapping rate can still be wrong when the reference is inappropriate, while a lower rate can be expected for degraded material, mixed species, tumour samples, targeted libraries, or an incomplete reference. Compare samples within the same cohort and investigate strong outliers.

## Implementation notes

- Input fields are validated before the run: positive thread count, non-negative parallel jobs, required folders, detected/selected samples, and compatible unmapped-only settings.
- All commands are shown before execution. This makes the workflow more transparent and gives a final chance to stop an incorrect run.
- The generated shell commands run in a background thread so the GUI and log remain responsive.
- Progress is updated every ten seconds from completed sample markers; the remaining-time estimate is approximate and becomes better after the first samples finish.
- The script increases the Linux open-file limit before running STAR. This is intended to prevent file-descriptor errors on large jobs; ensure the WSL environment permits the configured privilege step before relying on it in a shared/production environment.

## Files in this folder

```text
Star_V52.py                         STAR GUI source code
Screenshot/Mapping_Relaxed.png      Example of the Relaxed alignment interface
Readme.md                           This documentation
```

## Interpretation boundary

This program prepares and runs read alignment. It does not perform gene counting, transcript quantification, differential expression, variant calling, or clinical interpretation. Keep the STAR version and all settings with the results, then use the logs and downstream QC before drawing biological conclusions.
