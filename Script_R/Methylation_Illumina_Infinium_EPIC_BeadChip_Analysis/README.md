# Illumina Infinium EPIC BeadChip Analysis Pipeline

This project is a guided workflow for processing Illumina Infinium EPIC methylation-array data, beginning with raw IDAT files and ending with a gene-evidence workbook for manual pathway analysis. Each numbered folder is a self-contained GUI step: it opens its own form, carries forward the expected output from the preceding step, writes results to its own `Step_XX_Output` folder, and can save or restore its settings.

The pipeline deliberately separates technical quality control from biological inference. It does not try to “rescue” poor-quality data with downstream statistics: sample and probe decisions are made early, documented, and propagated forward.

## Before you start

Run `00_Installer_Methylation/00_Installer_Methylation.py` to install the required R/Bioconductor packages. Then run the R scripts in order, for example from RStudio or a Windows R session:

```r
source("Step_01_Raw_IDAT_QC/Step_01_Raw_IDAT_QC.R")
```

The scripts use Tcl/Tk, so the R installation must include Tcl/Tk support. The sample data and experimental plan in `Step_01_Raw_IDAT_QC` can be used to check that the workflow launches correctly.

## Required experimental plan

Step 01 needs a tab-delimited experimental plan with these columns:

| Column | Purpose |
| --- | --- |
| `Sample_Name` | Unique name used throughout the workflow. |
| `Group` | Biological group used for DMP/DMR comparisons. |
| `IDAT_Basename` | IDAT basename used to match the red and green IDAT files. |

`Patient`, `Batch`, and any other cofactors are optional at import, but are retained in downstream metadata and can later be used for paired designs, covariate adjustment, or QC visualisation.

## Pipeline at a glance

```text
IDAT files + experimental plan
        │
        ▼
01 Raw IDAT QC ── sample-level detection-P gate
        ▼
02 Normalization ── remove failed samples; inspect beta densities
        ▼
03 Probe filtering ── probe-level detection-P, SNP, and optional sex-chromosome filters
        ▼
04 Matrices ── beta, M-value, and probe-annotation outputs
        ├─────────────────────► 05 PCA / correlation QC
        ├─────────────────────► 06 DMP analysis
        └─────────────────────► 07 DMR analysis
                                  │
                      06 + 07 + 04 annotation
                                  ▼
                         08 Functional annotation
                                  ▼
                         09 RNA-seq integration (optional)
                                  ▼
                         10 Gene evidence export
```

## Why the QC is split across several steps

| Check | Where it happens | Decision it supports |
| --- | --- | --- |
| IDAT pairing and plan matching | Step 01 | Stops incorrect or incomplete raw inputs from entering the analysis. |
| Detection-P sample QC | Steps 01–02 | A sample must pass the probe-level threshold for the required fraction of probes; failing samples can be removed before normalization. |
| Normalized beta densities | Step 02 | Checks whether normalisation produces comparable sample distributions. |
| Detection-P probe QC | Step 03 | Keeps only probes that pass in the required fraction of retained samples. |
| SNP and sex-chromosome policy | Step 03 | Removes measurements likely to be genotype-sensitive; sex-chromosome removal is optional and must match the study question. |
| PCA, correlation, clustering, density, mean beta | Step 05 | Looks for outliers, batch structure, sample swaps, or unexpected grouping before running DMP/DMR statistics. |
| Model checks | Steps 06–07 | Validates group selection, matched samples, paired designs, covariates, and rank-deficient/confounded designs before fitting tests. |

Do not interpret PCA as an automatic exclusion rule. Use it alongside the Step 01/02 QC reports, sample history, laboratory metadata, and study design. If a sample is excluded, record why and rerun the downstream steps from Step 02 or Step 03 as appropriate.

## Step order and outputs

| Step | Role | Main output used next |
| --- | --- | --- |
| 01 | Import raw IDATs and initial QC | `rgSet_raw.rds`, `detectionP.rds`, `metadata_raw.csv` |
| 02 | Normalize and optionally remove failed samples | `normalized_object.rds`, retained detection-P matrix and metadata |
| 03 | Filter poor-performing and unwanted probes | `filtered_object.rds` |
| 04 | Build analysis matrices and annotation | beta/M-value matrices and `probe_annotation.rds` |
| 05 | Explore sample-level QC | QC figures and coordinate/correlation tables |
| 06 | Find differentially methylated positions | `DMP_all.tsv`, `DMP_significant.tsv` |
| 07 | Find differentially methylated regions | `DMR_significant.tsv` |
| 08 | Add gene and genomic context | annotated DMP/DMR tables and gene summaries |
| 09 | Integrate methylation with RNA-seq | ranked integrated candidates |
| 10 | Prepare a reviewable gene-evidence export | Excel and TSV evidence table for IPA/manual analysis |

