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
For 10x data, R1 contains barcode/UMI and R2 contains transcript sequence.
STARsolo internally receives R2 first, then R1.

Execution:
- Linux/WSL R: Rscript STARsolo_Rscript.R
- Native Windows R: the script invokes STAR through wsl.exe and Debian WSL.

Edit the USER SETTINGS section before running.
