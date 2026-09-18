# Step 09 — Call allele-specific CNV and LOH

This step measures B-allele imbalance at heterozygous germline SNPs inside the Step 08 copy-number segments. It summarizes allele balance by segment and identifies loss of heterozygosity, including copy-neutral LOH patterns.

![Allele-specific CNV and LOH interface](screenshot-1598x1491.png)

## Settings

| Setting | Default | What it controls |
|---|---:|---|
| **Validated/full BAM folder** | — | Complete cfDNA BAMs used to count reference and alternate alleles at germline SNPs. **Scan** discovers the samples. |
| **Step 08 `copy_number_segments.tsv`** | — | Copy-number regions in which SNP allele balance is summarized. |
| **Allele-specific / LOH SNP source** | No matched-normal/germline source | Chooses between carrying segments forward without LOH evaluation and calculating LOH from a heterozygous germline SNP VCF. |
| **Matched-normal/germline heterozygous SNP VCF** | Blank | VCF containing heterozygous `0/1` SNP genotypes used as informative allele-balance sites. |
| **VCF sample name** | First sample | Sample column read from the germline VCF. A blank field selects the first sample. |
| **Minimum depth per heterozygous SNP** | `20` | Total cfDNA read depth required for an individual SNP to contribute to segment statistics. |
| **Minimum SNPs per CNV segment** | `3` | Number of qualifying heterozygous sites required to assign a segment-level allele-specific result. |
| **LOH minor-allele fraction threshold** | `0.15` | Segment minor-allele fraction at or below which the segment is classified as LOH. |

## Output and execution settings

**Output folder** stores the allele-specific results. **Threads** defaults to `10`, **Micromamba env** to `ctdna_core`, and **WSL Python** to `python3`. The WSL distribution, Micromamba root prefix and executable can be selected directly or discovered automatically.

## Main outputs

`allele_specific_cnv_loh.tsv` contains segment-level copy-number and LOH classifications. `allele_specific_snp_baf.tsv` contains the individual SNP measurements, and `loh_classification_counts.png` summarizes the segment classes.
