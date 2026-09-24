###############################################################################
#Under the running level, need Folders:  Sample1/Input(Sample2/Input/..) with 4 files inside each Input:
#1)genes.tsv (or features.tsv each gene analysed in row: e.g. ENSG001285	CD68/ENSG002373	GAPDH/ENSG086092 ...)
#2)barcodes.tsv (each droplet nucleic tag: e.g. AACCAC-1/GAGCTAC-1/....)
#3)matrix.mtx (row1: %%MatrixMarket matrix coordinate real general) → indicate the matrix is using the format 'MatrixMarket',
# it is a matrix, coordinate indicate that the matrix is sparse (so the 0 are removed and 
# the format is: Gene#/Droplet#/UMIquantity, the values are real number, it is a general matrix (without symetry)
#4) sample_metadata.tabtxt Under Input that contain information about each sample (control, patient pairing..), e.g. : sample_id/condition/batch/patient
###############################################################################

options(stringsAsFactors = FALSE)
setwd("C:\\scRNAseq\\2_Seurat")
get_script_directory <- function() {
    command_arguments <- commandArgs(trailingOnly = FALSE)
    file_argument <- grep("^--file=", command_arguments, value = TRUE)

    if (length(file_argument) > 0L) {
        script_path <- sub("^--file=", "", file_argument[1L])
        return(dirname(normalizePath(script_path, winslash = "/", mustWork = FALSE)))
    }

    if (requireNamespace("rstudioapi", quietly = TRUE) && rstudioapi::isAvailable()) {
        active_path <- tryCatch(rstudioapi::getActiveDocumentContext()$path, error = function(e) "")
        if (nzchar(active_path)) {
            return(dirname(normalizePath(active_path, winslash = "/", mustWork = FALSE)))
        }
    }

    normalizePath(getwd(), winslash = "/", mustWork = FALSE)
}

SCRIPT_DIRECTORY <- get_script_directory()
INPUT_DIRECTORY <- file.path(SCRIPT_DIRECTORY, "Input")
OUTPUT_DIRECTORY <- file.path(SCRIPT_DIRECTORY, "Output")

dir.create(INPUT_DIRECTORY, recursive = TRUE, showWarnings = FALSE)
dir.create(OUTPUT_DIRECTORY, recursive = TRUE, showWarnings = FALSE)

LOG_FILE <- file.path(OUTPUT_DIRECTORY, "run_log.txt")
log_connection <- file(LOG_FILE, open = "wt")
sink(log_connection, type = "output", split = TRUE)
sink(log_connection, type = "message")

on.exit({
    cat("\n\n================ SESSION INFORMATION ================\n")
    print(sessionInfo())
    sink(type = "message")
    sink(type = "output")
    close(log_connection)
}, add = TRUE)

cat("Script directory:", SCRIPT_DIRECTORY, "\n")
cat("Input directory:", INPUT_DIRECTORY, "\n")
cat("Output directory:", OUTPUT_DIRECTORY, "\n")
cat("Started:", format(Sys.time()), "\n\n")

require_packages <- function(packages) {
    missing_packages <- packages[!vapply(packages, requireNamespace, logical(1), quietly = TRUE)]
    if (length(missing_packages) > 0L) {
        stop(
            "Missing required R package(s): ",
            paste(missing_packages, collapse = ", "),
            "\nRun 00_Install/00_Install_R_Packages_scRNAseq.R first."
        )
    }
}

save_session_information <- function() {
    capture.output(sessionInfo(), file = file.path(OUTPUT_DIRECTORY, "sessionInfo.txt"))
}

###############################################################################
# USER SETTINGS
###############################################################################

MIN_FEATURES <- 200L
MAX_FEATURES <- 7500L
MIN_COUNTS <- 500L
MAX_COUNTS <- Inf
MAX_PERCENT_MT <- 20
MIN_CELLS_PER_GENE <- 3L
MITOCHONDRIAL_PATTERN <- "^MT-"
RIBOSOMAL_PATTERN <- "^RP[SL]"

###############################################################################
# PACKAGES
###############################################################################

require_packages(c("Seurat", "SeuratObject", "Matrix", "ggplot2", "patchwork"))

library(Seurat)
library(ggplot2)
library(patchwork)

###############################################################################
# LOCATE FILTERED 10x / STARSOLO MATRICES
###############################################################################

is_matrix_directory <- function(directory) {
    matrix_exists <- any(file.exists(file.path(directory, c("matrix.mtx", "matrix.mtx.gz"))))
    barcode_exists <- any(file.exists(file.path(directory, c("barcodes.tsv", "barcodes.tsv.gz"))))
    feature_exists <- any(file.exists(file.path(directory, c("features.tsv", "features.tsv.gz", "genes.tsv", "genes.tsv.gz"))))
    matrix_exists && barcode_exists && feature_exists
}

candidate_directories <- unique(c(INPUT_DIRECTORY, list.dirs(INPUT_DIRECTORY, recursive = TRUE, full.names = TRUE)))
matrix_directories <- candidate_directories[vapply(candidate_directories, is_matrix_directory, logical(1))]

preferred <- matrix_directories[basename(matrix_directories) %in% c("filtered", "filtered_feature_bc_matrix")]
if (length(preferred)) matrix_directories <- preferred

if (!length(matrix_directories)) {
    stop("No filtered 10x/STARsolo matrix directory was found under Input.")
}

infer_sample_id <- function(directory) {
    current_base <- basename(directory)

    if (identical(current_base, "filtered")) {
        solo_directory <- dirname(dirname(directory))
        sample_parent <- dirname(solo_directory)
        candidate <- basename(sample_parent)
        if (nzchar(candidate)) return(candidate)
    }

    if (identical(current_base, "filtered_feature_bc_matrix")) {
        parent <- dirname(directory)
        if (identical(basename(parent), "outs")) parent <- dirname(parent)
        return(basename(parent))
    }

    basename(directory)
}

sample_ids <- make.unique(vapply(matrix_directories, infer_sample_id, character(1)))

matrix_manifest <- data.frame(
    sample_id = sample_ids,
    matrix_directory = normalizePath(matrix_directories, winslash = "/", mustWork = TRUE),
    stringsAsFactors = FALSE
)
write.csv(matrix_manifest, file.path(OUTPUT_DIRECTORY, "detected_matrix_manifest.csv"), row.names = FALSE)

###############################################################################
# OPTIONAL SAMPLE METADATA
#
# Priority:
#   1) Input/sample_metadata.csv     (comma-delimited)
#   2) Input/sample_metadata.tabtxt  (tab-delimited, only if CSV is absent)
###############################################################################

metadata_csv_file <- file.path(INPUT_DIRECTORY, "sample_metadata.csv")
metadata_tabtxt_file <- file.path(INPUT_DIRECTORY, "sample_metadata.tabtxt")

sample_metadata <- NULL

if (file.exists(metadata_csv_file)) {
    cat("Reading comma-delimited metadata:", metadata_csv_file, "\n")
    sample_metadata <- read.csv(
        metadata_csv_file,
        header = TRUE,
        check.names = FALSE,
        stringsAsFactors = FALSE
    )
} else if (file.exists(metadata_tabtxt_file)) {
    cat("sample_metadata.csv was not found. Reading tab-delimited metadata:", metadata_tabtxt_file, "\n")
    sample_metadata <- read.delim(
        metadata_tabtxt_file,
        header = TRUE,
        sep = "\t",
        quote = "\"",
        comment.char = "",
        check.names = FALSE,
        stringsAsFactors = FALSE
    )
} else {
    cat("No sample_metadata.csv or sample_metadata.tabtxt file was found. Continuing without sample metadata.\n")
}

if (!is.null(sample_metadata)) {
    if (!"sample_id" %in% colnames(sample_metadata)) {
        stop("Sample metadata must contain a column named sample_id.")
    }

    sample_metadata$sample_id <- trimws(as.character(sample_metadata$sample_id))

    if (any(is.na(sample_metadata$sample_id) | sample_metadata$sample_id == "")) {
        stop("Sample metadata contains one or more empty sample_id values.")
    }

    duplicated_samples <- sample_metadata$sample_id[duplicated(sample_metadata$sample_id)]
    if (length(duplicated_samples)) {
        stop("Duplicated sample_id values in metadata: ", paste(unique(duplicated_samples), collapse = ", "))
    }
}

###############################################################################
# CREATE AND MERGE SEURAT OBJECTS
###############################################################################

object_list <- vector("list", nrow(matrix_manifest))
names(object_list) <- matrix_manifest$sample_id

for (row_index in seq_len(nrow(matrix_manifest))) {
    sample_id <- matrix_manifest$sample_id[row_index]
    matrix_directory <- matrix_manifest$matrix_directory[row_index]

    cat("Reading sample:", sample_id, "\n")
    counts <- Read10X(data.dir = matrix_directory, gene.column = 2, unique.features = TRUE)

    if (is.list(counts)) {
        if ("Gene Expression" %in% names(counts)) {
            counts <- counts[["Gene Expression"]]
        } else {
            counts <- counts[[1L]]
        }
    }

    object <- CreateSeuratObject(
        counts = counts,
        assay = "RNA",
        project = sample_id,
        min.cells = MIN_CELLS_PER_GENE,
        min.features = 0
    )

    object$sample_id <- sample_id
    object[["percent.mt"]] <- PercentageFeatureSet(object, pattern = MITOCHONDRIAL_PATTERN)
    object[["percent.ribo"]] <- PercentageFeatureSet(object, pattern = RIBOSOMAL_PATTERN)

    if (!is.null(sample_metadata)) {
        metadata_row <- sample_metadata[sample_metadata$sample_id == sample_id, , drop = FALSE]
        if (nrow(metadata_row) != 1L) {
            stop("Metadata has no unique row for sample_id: ", sample_id)
        }
        for (column_name in setdiff(colnames(metadata_row), "sample_id")) {
            object[[column_name]] <- metadata_row[[column_name]][1L]
        }
    }

    object_list[[sample_id]] <- object
}

if (length(object_list) == 1L) {
    combined <- object_list[[1L]]
} else {
    combined <- merge(
        x = object_list[[1L]],
        y = object_list[-1L],
        add.cell.ids = names(object_list),
        project = "scRNAseq_project",
        merge.data = FALSE
    )
}

saveRDS(combined, file.path(OUTPUT_DIRECTORY, "seurat_before_QC.rds"), compress = FALSE)

###############################################################################
# QC TABLES AND PLOTS
###############################################################################

qc_metadata_before <- combined[[]]
qc_metadata_before$cell_barcode <- rownames(qc_metadata_before)
write.csv(qc_metadata_before, file.path(OUTPUT_DIRECTORY, "cell_QC_metrics_before_filtering.csv"), row.names = FALSE)

pdf(file.path(OUTPUT_DIRECTORY, "QC_violin_plots_before_filtering.pdf"), width = 14, height = 8)
print(VlnPlot(
    combined,
    features = c("nFeature_RNA", "nCount_RNA", "percent.mt", "percent.ribo"),
    group.by = "sample_id",
    ncol = 2,
    pt.size = 0
))
dev.off()

pdf(file.path(OUTPUT_DIRECTORY, "QC_scatter_plots_before_filtering.pdf"), width = 12, height = 6)
print(
    FeatureScatter(combined, feature1 = "nCount_RNA", feature2 = "percent.mt", group.by = "sample_id") |
    FeatureScatter(combined, feature1 = "nCount_RNA", feature2 = "nFeature_RNA", group.by = "sample_id")
)
dev.off()

###############################################################################
# FILTER CELLS
###############################################################################

keep_cells <- rownames(qc_metadata_before)[
    qc_metadata_before$nFeature_RNA >= MIN_FEATURES &
    qc_metadata_before$nFeature_RNA <= MAX_FEATURES &
    qc_metadata_before$nCount_RNA >= MIN_COUNTS &
    qc_metadata_before$nCount_RNA <= MAX_COUNTS &
    qc_metadata_before$percent.mt <= MAX_PERCENT_MT
]

filtered <- subset(combined, cells = keep_cells)

qc_metadata_after <- filtered[[]]
qc_metadata_after$cell_barcode <- rownames(qc_metadata_after)
write.csv(qc_metadata_after, file.path(OUTPUT_DIRECTORY, "cell_QC_metrics_after_filtering.csv"), row.names = FALSE)

cell_counts <- merge(
    as.data.frame(table(before = qc_metadata_before$sample_id)),
    as.data.frame(table(after = qc_metadata_after$sample_id)),
    by.x = "before", by.y = "after", all = TRUE
)
colnames(cell_counts) <- c("sample_id", "cells_before_QC", "cells_after_QC")
cell_counts[is.na(cell_counts)] <- 0
cell_counts$cells_removed <- cell_counts$cells_before_QC - cell_counts$cells_after_QC
write.csv(cell_counts, file.path(OUTPUT_DIRECTORY, "cell_counts_by_sample.csv"), row.names = FALSE)

pdf(file.path(OUTPUT_DIRECTORY, "QC_violin_plots_after_filtering.pdf"), width = 14, height = 8)
print(VlnPlot(
    filtered,
    features = c("nFeature_RNA", "nCount_RNA", "percent.mt", "percent.ribo"),
    group.by = "sample_id",
    ncol = 2,
    pt.size = 0
))
dev.off()

saveRDS(filtered, file.path(OUTPUT_DIRECTORY, "seurat_QC_filtered.rds"), compress = FALSE)

parameter_table <- data.frame(
    parameter = c("MIN_FEATURES", "MAX_FEATURES", "MIN_COUNTS", "MAX_COUNTS", "MAX_PERCENT_MT"),
    value = c(MIN_FEATURES, MAX_FEATURES, MIN_COUNTS, MAX_COUNTS, MAX_PERCENT_MT)
)
write.csv(parameter_table, file.path(OUTPUT_DIRECTORY, "QC_parameters.csv"), row.names = FALSE)

save_session_information()
cat("\nSeurat cell-level QC completed successfully.\n")
