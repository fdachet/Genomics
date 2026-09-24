

options(stringsAsFactors = FALSE)
setwd("C:\\scRNAseq\\3_Doublet_Detection")
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

SAMPLE_COLUMN <- "sample_id"
# NULL lets scDblFinder estimate an appropriate doublet rate.
EXPECTED_DOUBLET_RATE <- NULL
RANDOM_SEED <- 12345L

###############################################################################
# PACKAGES
###############################################################################

require_packages(c("Seurat", "SeuratObject", "SingleCellExperiment", "scDblFinder", "ggplot2"))

library(Seurat)
library(ggplot2)

###############################################################################
# LOAD OBJECT
###############################################################################

rds_files <- list.files(INPUT_DIRECTORY, pattern = "\\.rds$", recursive = TRUE, full.names = TRUE, ignore.case = TRUE)
if (length(rds_files) != 1L) {
    stop("Place exactly one Seurat RDS file in Input. Found ", length(rds_files), ".")
}

object <- readRDS(rds_files[1L])
if (!inherits(object, "Seurat")) stop("The RDS file does not contain a Seurat object.")
if (!"RNA" %in% SeuratObject::Assays(object)) stop("The Seurat object does not contain an RNA assay.")
if (!SAMPLE_COLUMN %in% colnames(object[[]])) stop("Missing metadata column: ", SAMPLE_COLUMN)

SeuratObject::DefaultAssay(object) <- "RNA"
set.seed(RANDOM_SEED)

###############################################################################
# JOIN SEURAT V5 LAYERS, THEN RUN SCDOUBLETFINDER
###############################################################################

if (inherits(object[["RNA"]], "Assay5")) {
    count_layers <- grep("^counts($|\\.)", SeuratObject::Layers(object[["RNA"]]), value = TRUE)

    if (!length(count_layers)) {
        stop("The RNA assay does not contain raw counts.")
    }

    if (length(count_layers) > 1L || count_layers[1L] != "counts") {
        cat("Joining Seurat v5 RNA layers:", paste(count_layers, collapse = ", "), "\n")
        object <- SeuratObject::JoinLayers(object, assay = "RNA")
    }

    count_layers <- grep("^counts($|\\.)", SeuratObject::Layers(object[["RNA"]]), value = TRUE)

    if (length(count_layers) != 1L || count_layers[1L] != "counts") {
        stop("The RNA assay does not contain exactly one joined counts layer.")
    }
}

single_cell_experiment <- Seurat::as.SingleCellExperiment(object, assay = "RNA")

if (!"counts" %in% SummarizedExperiment::assayNames(single_cell_experiment)) {
    stop("The converted SingleCellExperiment does not contain a counts assay.")
}

if (is.null(EXPECTED_DOUBLET_RATE)) {
    single_cell_experiment <- scDblFinder::scDblFinder(
        single_cell_experiment,
        samples = single_cell_experiment[[SAMPLE_COLUMN]],
        verbose = TRUE
    )
} else {
    single_cell_experiment <- scDblFinder::scDblFinder(
        single_cell_experiment,
        samples = single_cell_experiment[[SAMPLE_COLUMN]],
        dbr = EXPECTED_DOUBLET_RATE,
        verbose = TRUE
    )
}

object$scDblFinder.score <- SummarizedExperiment::colData(single_cell_experiment)$scDblFinder.score
object$scDblFinder.class <- as.character(SummarizedExperiment::colData(single_cell_experiment)$scDblFinder.class)

saveRDS(object, file.path(OUTPUT_DIRECTORY, "seurat_with_doublet_calls.rds"), compress = FALSE)

singlet_cells <- colnames(object)[object$scDblFinder.class == "singlet"]
singlet_object <- subset(object, cells = singlet_cells)
saveRDS(singlet_object, file.path(OUTPUT_DIRECTORY, "seurat_singlets.rds"), compress = FALSE)

###############################################################################
# REPORTS
###############################################################################

metadata <- object[[]]
metadata$cell_barcode <- rownames(metadata)
write.csv(metadata, file.path(OUTPUT_DIRECTORY, "doublet_scores_and_calls.csv"), row.names = FALSE)

summary_table <- as.data.frame(table(
    sample_id = metadata[[SAMPLE_COLUMN]],
    scDblFinder_class = metadata$scDblFinder.class
))
write.csv(summary_table, file.path(OUTPUT_DIRECTORY, "doublet_summary_by_sample.csv"), row.names = FALSE)

score_plot <- ggplot(metadata, aes(x = scDblFinder.score, fill = scDblFinder.class)) +
    geom_histogram(bins = 80, position = "identity", alpha = 0.55) +
    facet_wrap(stats::as.formula(paste("~", SAMPLE_COLUMN)), scales = "free_y") +
    theme_bw(base_size = 11) +
    labs(title = "scDblFinder scores", x = "Doublet score", y = "Number of cells", fill = "Call")

ggsave(file.path(OUTPUT_DIRECTORY, "scDblFinder_score_distribution.png"), score_plot, width = 12, height = 8, dpi = 300)
ggsave(file.path(OUTPUT_DIRECTORY, "scDblFinder_score_distribution.pdf"), score_plot, width = 12, height = 8)

save_session_information()
cat("\nDoublet detection completed successfully.\n")
