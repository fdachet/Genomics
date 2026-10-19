10x Chromium 3' v2/v3 gene-expression inputs
================================================

This pipeline is specifically configured for 10x Chromium 3' v2/v3
gene-expression libraries. It is not a conventional paired-end RNA-seq
pipeline and does not support 10x 5', Flex, ATAC-seq, or other library types.

Place the following inside this Input folder:

1. Paired gzipped FASTQ files for each sample.
   Common names:
       Sample01_S1_L001_R1_001.fastq.gz
       Sample01_S1_L001_R2_001.fastq.gz

2. One STAR genome-index directory containing at least:
       Genome
       SA
       SAindex

3. One 10x barcode whitelist text file. Its name must contain either
   "whitelist" or "barcodes" and end in .txt or .txt.gz.

The script automatically groups multiple lanes belonging to the same sample.
For supported 10x Chromium 3' v2/v3 gene-expression libraries:
- R1 contains the cell barcode and UMI; it is not a genomic cDNA mate.
- R2 contains the transcript/cDNA sequence that is aligned to the genome.
- Corresponding R1 and R2 records are linked by their Illumina read identifier
  and record order because they originate from the same sequencing cluster.

STARsolo requires the cDNA read before the barcode/UMI read, so the script
passes R2 first and R1 second to --readFilesIn. This does not reverse or break
the FASTQ pairing.

Execution:
- Linux/WSL R: Rscript STARsolo_Rscript.R
- Native Windows R: the script invokes STAR through wsl.exe and Debian WSL.

Edit the USER SETTINGS section before running.
