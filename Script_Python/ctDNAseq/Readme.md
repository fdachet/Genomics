# ctDNAseq scripts: GUI + CLI/Nextflow dual mode
Each analysis script keeps its existing GUI as the default behavior and now also supports `--cli` (alias `--no-gui`).
## General usage
GUI (unchanged):
```bash
python STEP.py
```
CLI / Nextflow mode:
```bash
python STEP.py --cli --input-dir INPUT_FOLDER --output-dir OUTPUT_FOLDER [step-specific options]
```
Show all options for one step:
```bash
python STEP.py --help
```
Boolean options take explicit values such as `true` or `false`. Example:
```bash
--alignment-build-umi-consensus true
```
CLI mode starts from the script's `DEFAULT_SETTINGS` unless `--settings-file some.json` is explicitly supplied. The complete effective settings are written into the output folder as `STEP_NAME.cli_settings.json`.
The existing hidden `--backend` interface used by the Tkinter/WSL GUI is preserved.
## Step-specific CLI inputs
### 01_FASTQ_QUALITY_CONTROL(2).py
- `--input-dir PATH` **required**

### 02_UMI_EXTRACTION_AND_TRIMMING(2).py
- `--input-dir PATH` **required**
- `--trimming-umi-mode` — UMI mode: none / single / duplex (text) **required unless provided by defaults/settings file**
- `--trimming-r1-umi-length` — R1 UMI length (bp) (int) **required unless provided by defaults/settings file**
- `--trimming-r2-umi-length` — R2 UMI length (bp) (int) **required unless provided by defaults/settings file**
- `--trimming-trim-adapters` — Trim adapters (bool)
- `--trimming-quality-cutoff` — Quality cutoff (int) **required unless provided by defaults/settings file**
- `--trimming-minimum-length` — Minimum retained read length (bp) (int) **required unless provided by defaults/settings file**
- `--trimming-maximum-n-fraction` — Maximum N fraction (float) **required unless provided by defaults/settings file**
- `--trimming-adapter-r1` — R1 adapter sequence (text)
- `--trimming-adapter-r2` — R2 adapter sequence (text)

### 03_MAP_READS_TO_REFERENCE_AND_CREATE_BAM(3).py
- `--input-dir PATH` **required**
- `--references-fasta` — Reference FASTA (file) **required unless provided by defaults/settings file**
- `--alignment-build-umi-consensus` — Build UMI consensus when UMI metadata is present (bool)
- `--alignment-umi-group-strategy` — UMI group strategy (text) **required unless provided by defaults/settings file**
- `--alignment-umi-edit-distance` — UMI edit distance (int) **required unless provided by defaults/settings file**
- `--alignment-minimum-reads-per-family` — Minimum reads per UMI family (int) **required unless provided by defaults/settings file**
- `--alignment-consensus-minimum-base-quality` — Consensus minimum base quality (int) **required unless provided by defaults/settings file**
- `--alignment-auto-create-reference-indexes` — Auto-create missing FASTA/BWA indexes (bool)

### 04_BAM_MAPPING_AND_FRAGMENT_QC(3).py
- `--input-dir PATH` **required**
- `--references-targets-bed` — Optional known target/capture BED (file)
- `--bam-qc-minimum-mapping-quality` — Minimum mapping quality (int) **required unless provided by defaults/settings file**
- `--bam-qc-minimum-base-quality` — Minimum base quality (int) **required unless provided by defaults/settings file**
- `--bam-qc-fragment-minimum-length` — Minimum fragment length (bp) (int) **required unless provided by defaults/settings file**
- `--bam-qc-fragment-maximum-length` — Maximum fragment length (bp) (int) **required unless provided by defaults/settings file**
- `--bam-qc-short-fragment-maximum` — Short-fragment maximum (bp) (int) **required unless provided by defaults/settings file**
- `--bam-qc-mononucleosome-minimum` — Mononucleosome minimum (bp) (int) **required unless provided by defaults/settings file**
- `--bam-qc-mononucleosome-maximum` — Mononucleosome maximum (bp) (int) **required unless provided by defaults/settings file**
- `--bam-qc-maximum-fragments-to-analyze` — Maximum fragments analyzed (int) **required unless provided by defaults/settings file**
- `--bam-qc-genome-bin-depth-enabled` — Compute genome-wide fixed-bin depth QC (bool)
- `--bam-qc-genome-bin-size-bp` — Genome bin size (bp) (int) **required unless provided by defaults/settings file**
- `--bam-qc-infer-high-depth-regions-enabled` — Infer probable targeted/high-coverage regions and create BED (bool)
- `--bam-qc-high-depth-threshold` — High-depth threshold X (base qualifies at depth >= X) (int) **required unless provided by defaults/settings file**
- `--bam-qc-high-depth-minimum-region-length-bp` — Minimum inferred region length (bp) (int) **required unless provided by defaults/settings file**
- `--bam-qc-high-depth-maximum-merge-gap-bp` — Maximum low-depth gap to bridge (bp) (int) **required unless provided by defaults/settings file**
- `--bam-qc-high-depth-consensus-enabled` — Create consensus inferred-target BED across BAM samples (bool)
- `--bam-qc-high-depth-consensus-minimum-sample-percent` — Consensus minimum sample support (%) (float) **required unless provided by defaults/settings file**
- `--bam-qc-fragment-log-count-plot-enabled` — log(count): create second cfDNA fragment-length plot (bool)
- `--bam-qc-fragment-log-plot-xmin-bp` — Log fragment plot X start (bp) (int) **required unless provided by defaults/settings file**
- `--bam-qc-fragment-log-plot-xmax-bp` — Log fragment plot X end (bp) (int) **required unless provided by defaults/settings file**
- `--bam-qc-fragment-log-plot-minor-tick-bp` — Log plot minor X tick every (bp) (int) **required unless provided by defaults/settings file**
- `--bam-qc-fragment-log-plot-reference-bp` — Dotted fragment reference line (bp) (int) **required unless provided by defaults/settings file**

### 05_EXTRACT_ABNORMAL_ALIGNMENTS(1).py
- `--input-dir PATH` **required**
- `--abnormal-alignments-minimum-mapping-quality` — Minimum mapping quality (int) **required unless provided by defaults/settings file**
- `--abnormal-alignments-minimum-soft-clip-bases` — Minimum soft-clipped bases (int) **required unless provided by defaults/settings file**
- `--abnormal-alignments-maximum-expected-insert-size` — Maximum expected insert size (bp) (int) **required unless provided by defaults/settings file**
- `--abnormal-alignments-include-supplementary` — Include supplementary alignments (bool)
- `--abnormal-alignments-include-secondary` — Include secondary alignments (bool)

### 06_ASSEMBLE_AND_CALL_CHROMOSOME_BREAKPOINTS(1).py
- `--input-dir PATH` **required**
- `--breakpoints-analysis-ready-bam-folder` — Step 03 validated/full BAM folder - Manta/local depth (folder) **required unless provided by defaults/settings file**
- `--references-fasta` — Reference FASTA (file) **required unless provided by defaults/settings file**
- `--breakpoints-run-spades-assembly` — Run SPAdes local assembly on abnormal FASTQs (bool)
- `--breakpoints-run-manta` — Run Manta structural-variant caller on full BAM (bool)
- `--breakpoints-spades-kmers` — SPAdes k-mers (text) **required unless provided by defaults/settings file**
- `--breakpoints-minimum-contig-length` — Minimum assembled contig length (bp) (int) **required unless provided by defaults/settings file**
- `--breakpoints-minimum-contig-alignment-length` — Minimum contig alignment length (bp) (int) **required unless provided by defaults/settings file**
- `--breakpoints-local-depth-window-bp` — Local depth window around breakpoint (bp) (int) **required unless provided by defaults/settings file**
- `--tools-manta-config` — Manta config command/path (blank only if backend can resolve it) (text)
- `--tools-manta-run` — Manta run command/path (blank only if backend can resolve it) (text)

### 07_CONSOLIDATE_STRUCTURAL_VARIANTS.py
- `--sv-consolidation-candidate-breakpoints-tsv` — Step 06 candidate_breakpoints.tsv (file) **required unless provided by defaults/settings file**
- `--sv-consolidation-breakpoint-tolerance-bp` — Breakpoint clustering tolerance (bp) (int) **required unless provided by defaults/settings file**
- `--sv-consolidation-minimum-support-records` — Minimum technical records per consensus event (int) **required unless provided by defaults/settings file**

### 08_CALL_COPY_NUMBER_GAINS_AND_LOSSES.py
- `--input-dir PATH` **required**
- `--references-fasta` — Reference FASTA (file) **required unless provided by defaults/settings file**
- `--copy-number-reference-mode` — CNVkit reference mode: existing / build_from_normals / build_flat (text) **required unless provided by defaults/settings file**
- `--copy-number-method` — Assay method: hybrid / amplicon / wgs (text) **required unless provided by defaults/settings file**
- `--copy-number-normal-bam-folder` — Optional normal BAM folder for building CNVkit reference (folder)
- `--copy-number-reference-cnn` — Optional existing CNVkit reference CNN (file)
- `--copy-number-targets-bed` — Optional target BED (required for hybrid/amplicon) (file)
- `--copy-number-output-reference-cnn` — Optional output CNN path when building reference (text)
- `--copy-number-segment-method` — Segmentation method (text) **required unless provided by defaults/settings file**
- `--copy-number-male-reference` — Use haploid-X/male reference convention (bool)
- `--copy-number-drop-low-coverage` — Drop low-coverage bins (bool)
- `--copy-number-gain-ratio-threshold` — SIGNED_COPY_RATIO gain threshold (float) **required unless provided by defaults/settings file**
- `--copy-number-loss-ratio-threshold` — SIGNED_COPY_RATIO loss threshold (float) **required unless provided by defaults/settings file**

### 09_CALL_ALLELE_SPECIFIC_CNV_AND_LOH.py
- `--input-dir PATH` **required**
- `--allele-specific-cnv-cnv-segments-tsv` — Step 08 copy_number_segments.tsv (file) **required unless provided by defaults/settings file**
- `--allele-specific-cnv-germline-heterozygous-snp-vcf` — Matched-normal/germline heterozygous SNP VCF (file) **required unless provided by defaults/settings file**
- `--allele-specific-cnv-germline-vcf-sample-name` — VCF sample name (blank = first sample) (text)
- `--allele-specific-cnv-minimum-snp-depth` — Minimum depth per heterozygous SNP (int) **required unless provided by defaults/settings file**
- `--allele-specific-cnv-minimum-snps-per-segment` — Minimum SNPs per CNV segment (int) **required unless provided by defaults/settings file**
- `--allele-specific-cnv-loh-minor-allele-fraction-threshold` — LOH minor-allele fraction threshold (float) **required unless provided by defaults/settings file**

### 09B_OPTION_BUILD_MUTECT2_PANEL_OF_NORMALS.py
- `--pon-build-normal-bam-folder` — Validated normal BAM folder (group) (folder) **required unless provided by defaults/settings file**
- `--pon-build-reference-fasta` — Reference FASTA (file) **required unless provided by defaults/settings file**
- `--pon-build-optional-intervals-bed` — Optional assay target/interval BED (file)
- `--pon-build-minimum-normal-samples` — Minimum number of normal samples (int) **required unless provided by defaults/settings file**

### 10_CALL_SNVS_AND_SMALL_INDELS.py
- `--input-dir PATH` **required**
- `--references-fasta` — Reference FASTA (file) **required unless provided by defaults/settings file**
- `--small-variants-matched-normal-bam` — Optional matched-normal BAM (single complete BAM) (file)
- `--small-variants-matched-normal-sample-name` — Matched-normal sample name (text)
- `--references-germline-resource-vcf` — Optional germline population resource VCF (file)
- `--references-panel-of-normals-vcf` — Optional Mutect2 Panel-of-Normals VCF (file)
- `--small-variants-initial-tumor-lod` — Mutect2 initial tumor LOD (float) **required unless provided by defaults/settings file**
- `--small-variants-minimum-base-quality-score` — Minimum base quality score (int) **required unless provided by defaults/settings file**
- `--small-variants-maximum-reads-per-alignment-start` — Maximum reads per alignment start (0 = GATK behavior/default) (int) **required unless provided by defaults/settings file**
- `--small-variants-native-pair-hmm-threads` — Native PairHMM threads (int) **required unless provided by defaults/settings file**

### 11_ESTIMATE_CONTAMINATION_AND_FINALIZE_SOMATIC_CALLS.py
- `--contamination-bam-folder` — Validated/full cfDNA BAM folder (folder) **required unless provided by defaults/settings file**
- `--contamination-unfiltered-vcf-folder` — Step 10 Mutect2 output folder (group of unfiltered VCFs) (folder) **required unless provided by defaults/settings file**
- `--contamination-common-sites-vcf` — Common biallelic SNP resource VCF for contamination (file) **required unless provided by defaults/settings file**
- `--contamination-reference-fasta` — Reference FASTA (file) **required unless provided by defaults/settings file**

### 12_FILTER_WBC_CHIP_AND_GERMLINE_VARIANTS.py
- `--wbc-filter-final-vcf-folder` — Step 11 final PASS VCF folder (folder) **required unless provided by defaults/settings file**
- `--wbc-filter-wbc-bam-folder` — Matched WBC / buffy-coat BAM folder (folder) **required unless provided by defaults/settings file**
- `--wbc-filter-pairing-tsv` — Optional sample pairing TSV (file)
- `--wbc-filter-minimum-wbc-depth` — Minimum WBC depth (int) **required unless provided by defaults/settings file**
- `--wbc-filter-germline-vaf-threshold` — Germline-candidate WBC VAF threshold (float) **required unless provided by defaults/settings file**
- `--wbc-filter-hematopoietic-vaf-threshold` — Hematopoietic/CHIP-candidate WBC VAF threshold (float) **required unless provided by defaults/settings file**
- `--wbc-filter-tumor-enriched-wbc-vaf-maximum` — Maximum WBC VAF for plasma-enriched tumor candidate (float) **required unless provided by defaults/settings file**

### 13_VALIDATE_LOW_VAF_WITH_MOLECULAR_EVIDENCE.py
- `--molecular-qc-classified-variants-tsv` — Step 12 wbc_chip_germline_classified_variants.tsv (file) **required unless provided by defaults/settings file**
- `--molecular-qc-cfdna-bam-folder` — Validated/full cfDNA BAM folder (folder) **required unless provided by defaults/settings file**
- `--molecular-qc-minimum-total-depth` — Minimum allele depth (int) **required unless provided by defaults/settings file**
- `--molecular-qc-minimum-alt-molecules` — Minimum independent ALT molecules (int) **required unless provided by defaults/settings file**
- `--molecular-qc-minimum-molecular-vaf` — Minimum molecular/read VAF (float) **required unless provided by defaults/settings file**
- `--molecular-qc-preferred-molecule-tags` — Preferred BAM molecule tags (text) **required unless provided by defaults/settings file**

### 14_ESTIMATE_CTDNA_TUMOR_FRACTION.py
- `--tumor-fraction-molecular-variants-tsv` — Step 13 molecularly_validated_somatic_variants.tsv (file) **required unless provided by defaults/settings file**
- `--tumor-fraction-cnv-segments-tsv` — Step 08 copy_number_segments.tsv (file) **required unless provided by defaults/settings file**
- `--tumor-fraction-allele-specific-loh-tsv` — Optional Step 09 allele_specific_cnv_loh.tsv (file)
- `--tumor-fraction-minimum-variants` — Minimum variants for estimate (int) **required unless provided by defaults/settings file**
- `--tumor-fraction-maximum-candidate-clonal-vaf` — Maximum candidate clonal VAF (float) **required unless provided by defaults/settings file**
- `--tumor-fraction-top-fraction-of-variants` — Top fraction of high-confidence VAFs used (float) **required unless provided by defaults/settings file**

### 15_INTEGRATE_TUMOR_GENOME_EVENTS.py
- `--integration-full-consensus-sv-tsv` — Step 07 consensus_structural_variants.tsv (file) **required unless provided by defaults/settings file**
- `--integration-full-copy-number-segments-tsv` — Step 08 copy_number_segments.tsv (file) **required unless provided by defaults/settings file**
- `--integration-full-allele-specific-loh-tsv` — Step 09 allele_specific_cnv_loh.tsv (file) **required unless provided by defaults/settings file**
- `--integration-full-molecular-variants-tsv` — Step 13 molecularly_validated_somatic_variants.tsv (file) **required unless provided by defaults/settings file**
- `--integration-full-ctdna-fraction-tsv` — Step 14 ctdna_fraction_estimate.tsv (file) **required unless provided by defaults/settings file**
- `--integration-full-reference-fasta` — Reference FASTA (file) **required unless provided by defaults/settings file**
- `--integration-full-nearby-variant-window-bp` — Nearby small-variant window around breakpoint (bp) (int) **required unless provided by defaults/settings file**
- `--integration-full-graph-include-normal-adjacencies` — Include normal/reference adjacency edges in graph (bool)
- `--integration-full-include-neutral-cnv-segments` — Include NEUTRAL CNV segments in integrated event table (bool)

### 15B_OPTION_BUILD_PATIENT_SPECIFIC_TUMOR_REFERENCE.py
- `--patient-reference-reference-fasta` — Reference FASTA (file) **required unless provided by defaults/settings file**
- `--patient-reference-consensus-sv-tsv` — Step 07 consensus_structural_variants.tsv (file) **required unless provided by defaults/settings file**
- `--patient-reference-somatic-vcf` — Optional high-confidence somatic VCF for sequence consensus (file)
- `--patient-reference-sample-id` — Patient/sample ID (text) **required unless provided by defaults/settings file**
- `--patient-reference-junction-flank-bp` — Breakpoint junction flank on each side (bp) (int) **required unless provided by defaults/settings file**

### 16_ANNOTATE_FUSIONS_AND_VISUALIZE_RESULTS.py
- `--annotation-full-integrated-events-tsv` — Step 15 integrated_tumor_genome_events.tsv (file) **required unless provided by defaults/settings file**
- `--annotation-full-derivative-chromosomes-tsv` — Step 15 candidate_derivative_chromosomes.tsv (file) **required unless provided by defaults/settings file**
- `--annotation-full-graph-nodes-tsv` — Step 15 tumor_genome_graph_nodes.tsv (file) **required unless provided by defaults/settings file**
- `--annotation-full-graph-edges-tsv` — Step 15 tumor_genome_graph_edges.tsv (file) **required unless provided by defaults/settings file**
- `--annotation-full-gene-gtf` — Gene annotation GTF (file) **required unless provided by defaults/settings file**
- `--annotation-run-local-gtf-variant-annotation` — Run lightweight local GTF annotation (bool)
- `--annotation-nearest-gene-maximum-distance-bp` — Nearest-gene maximum distance (bp) (int) **required unless provided by defaults/settings file**
- `--annotation-maximum-table-rows` — Maximum rows per table in HTML report (int) **required unless provided by defaults/settings file**
- `--annotation-run-vep` — Optional: run offline VEP annotation (bool)
- `--annotation-full-pass-vcf-folder` — Optional Step 11 PASS VCF folder for VEP (group) (folder)
- `--references-vep-cache` — Optional VEP cache folder (folder)
- `--references-vep-species` — VEP species (text) **required unless provided by defaults/settings file**
- `--references-vep-assembly` — VEP assembly (text) **required unless provided by defaults/settings file**

### 16B_OPTION_LONGITUDINAL_MRD_TRACKING.py
- `--longitudinal-variant-results-folder` — Folder containing per-timepoint Step 13 result folders/files (folder) **required unless provided by defaults/settings file**
- `--longitudinal-sample-metadata-tsv` — Longitudinal sample metadata TSV (file) **required unless provided by defaults/settings file**
- `--longitudinal-maximum-variants-to-plot` — Maximum variants per patient plot (int) **required unless provided by defaults/settings file**

