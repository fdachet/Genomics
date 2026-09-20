###############################################################################
# FAST NORMALIZATION PIPELINE
#
# Reads exactly one Seurat RDS from Input and writes results to Output.
# Main speed improvements:
#   - glmGamPoi for SCTransform
#   - future multisession workers on Windows
#   - SCT residuals stored only for variable genes by default
###############################################################################

options(stringsAsFactors = FALSE)
setwd("C:\\scRNAseq\\4_Normalization")
NUMBER_WORKERS <- 4                       # Windows multisession workers VERIFY WHICH VERSION OF SEURAT I AM USING AS ACTUAL VERSION DOES NOT IMPROVES AND THE OPPOSITE ARE SLOWER SO KEEP 1
FUTURE_MAX_SIZE_GB <- 40
get_script_directory <- function() {
    command_arguments <- commandArgs(trailingOnly = FALSE)
    file_argument <- grep("^--file=", command_arguments, value = TRUE)

    if (length(file_argument) > 0L) {
        script_path <- sub("^--file=", "", file_argument[1L])
        return(dirname(normalizePath(script_path, winslash = "/", mustWork = FALSE)))
    }

    if (requireNamespace("rstudioapi", quietly = TRUE) && rstudioapi::isAvailable()) {
        active_path <- tryCatch(rstudioapi::getActiveDocumentContext()$path, error = function(e) "")
        if (nzchar(active_path)) return(dirname(normalizePath(active_path, winslash = "/", mustWork = FALSE)))
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
    if (requireNamespace("future", quietly = TRUE)) future::plan(future::sequential)
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
        stop("Missing required R package(s): ", paste(missing_packages, collapse = ", "))
    }
}

save_session_information <- function() {
    capture.output(sessionInfo(), file = file.path(OUTPUT_DIRECTORY, "sessionInfo.txt"))
}

###############################################################################
# USER SETTINGS
###############################################################################

NORMALIZATION_METHOD <- "SCTransform"       # "SCTransform" or "LogNormalize"
NUMBER_VARIABLE_FEATURES <- 3000L
VARIABLES_TO_REGRESS <- c("percent.mt")
RANDOM_SEED <- 12345L


SCT_MODEL_CELLS <- 5000L
SCT_RETURN_ONLY_VARIABLE_GENES <- TRUE      # FALSE is slower and uses more RAM

###############################################################################
# PACKAGES AND PARALLELIZATION
###############################################################################

require_packages(c("Seurat", "SeuratObject", "ggplot2", "future", "parallelly"))

if (identical(NORMALIZATION_METHOD, "SCTransform") &&
    !requireNamespace("glmGamPoi", quietly = TRUE)) {
    stop(
        "glmGamPoi is required for fast SCTransform.\n",
        "Install it once with:\n",
        "if (!requireNamespace(\"BiocManager\", quietly = TRUE)) install.packages(\"BiocManager\")\n",
        "BiocManager::install(\"glmGamPoi\")"
    )
}

library(Seurat)
library(ggplot2)

options(future.globals.maxSize = FUTURE_MAX_SIZE_GB * 1024^3)

if (NUMBER_WORKERS > 1L) {
    future::plan(future::multisession, workers = NUMBER_WORKERS)
} else {
    future::plan(future::sequential)
}

cat("Workers used:", NUMBER_WORKERS, "\n")
cat("Future maximum global size:", FUTURE_MAX_SIZE_GB, "GB\n\n")

###############################################################################
# LOAD OBJECT
###############################################################################

rds_files <- list.files(INPUT_DIRECTORY, pattern = "\\.rds$", recursive = TRUE, full.names = TRUE, ignore.case = TRUE)
if (length(rds_files) != 1L) stop("Place exactly one Seurat RDS file in Input. Found ", length(rds_files), ".")

object <- readRDS(rds_files[1L])
if (!inherits(object, "Seurat")) stop("Input RDS is not a Seurat object.")
if (!"RNA" %in% SeuratObject::Assays(object)) stop("The Seurat object does not contain an RNA assay.")

set.seed(RANDOM_SEED)
SeuratObject::DefaultAssay(object) <- "RNA"

valid_regressors <- VARIABLES_TO_REGRESS[VARIABLES_TO_REGRESS %in% colnames(object[[]])]
missing_regressors <- setdiff(VARIABLES_TO_REGRESS, valid_regressors)

if (length(missing_regressors)) {
    warning("Missing regression variables ignored: ", paste(missing_regressors, collapse = ", "))
}

cat("Input RDS:", rds_files[1L], "\n")
cat("Cells:", ncol(object), "\n")
cat("RNA features:", nrow(object[["RNA"]]), "\n")
cat("Regressors:", if (length(valid_regressors)) paste(valid_regressors, collapse = ", ") else "none", "\n\n")

###############################################################################
# NORMALIZATION
###############################################################################

start_time <- Sys.time()

if (identical(NORMALIZATION_METHOD, "SCTransform")) {
    cat("Running SCTransform with glmGamPoi available.\n")

    object <- SCTransform(
        object,
        assay = "RNA",
        new.assay.name = "SCT",
        ncells = min(SCT_MODEL_CELLS, ncol(object)),
        variable.features.n = NUMBER_VARIABLE_FEATURES,
        vars.to.regress = if (length(valid_regressors)) valid_regressors else NULL,
        vst.flavor = "v2",
        return.only.var.genes = SCT_RETURN_ONLY_VARIABLE_GENES,
        conserve.memory = FALSE,
        seed.use = RANDOM_SEED,
        verbose = TRUE
    )

    SeuratObject::DefaultAssay(object) <- "SCT"
    output_name <- "seurat_normalized_SCT.rds"

} else if (identical(NORMALIZATION_METHOD, "LogNormalize")) {
    object <- NormalizeData(object, assay = "RNA", normalization.method = "LogNormalize", scale.factor = 10000, verbose = TRUE)
    object <- FindVariableFeatures(object, assay = "RNA", selection.method = "vst", nfeatures = NUMBER_VARIABLE_FEATURES, verbose = TRUE)
    object <- ScaleData(
        object,
        assay = "RNA",
        features = VariableFeatures(object[["RNA"]]),
        vars.to.regress = if (length(valid_regressors)) valid_regressors else NULL,
        verbose = TRUE
    )

    SeuratObject::DefaultAssay(object) <- "RNA"
    output_name <- "seurat_normalized_LogNormalize.rds"

} else {
    stop("NORMALIZATION_METHOD must be SCTransform or LogNormalize.")
}

elapsed_minutes <- as.numeric(difftime(Sys.time(), start_time, units = "mins"))
cat("\nNormalization time:", round(elapsed_minutes, 3), "minutes\n")

###############################################################################
# OUTPUTS
###############################################################################

variable_features <- VariableFeatures(object)

write.csv(
    data.frame(gene = variable_features),
    file.path(OUTPUT_DIRECTORY, "highly_variable_genes.csv"),
    row.names = FALSE
)

if (length(variable_features) >= 20L) {
    variable_plot <- VariableFeaturePlot(object)
    labeled_plot <- LabelPoints(variable_plot, points = head(variable_features, 20L), repel = TRUE)
    ggsave(file.path(OUTPUT_DIRECTORY, "variable_features.png"), labeled_plot, width = 10, height = 7, dpi = 300)
    ggsave(file.path(OUTPUT_DIRECTORY, "variable_features.pdf"), labeled_plot, width = 10, height = 7)
}

saveRDS(object, file.path(OUTPUT_DIRECTORY, output_name), compress = FALSE)

write.csv(
    data.frame(
        normalization_method = NORMALIZATION_METHOD,
        default_assay = SeuratObject::DefaultAssay(object),
        number_variable_features = length(variable_features),
        variables_regressed = paste(valid_regressors, collapse = ";"),
        glmGamPoi_installed = requireNamespace("glmGamPoi", quietly = TRUE),
        workers_used = NUMBER_WORKERS,
        SCT_model_cells = if (identical(NORMALIZATION_METHOD, "SCTransform")) min(SCT_MODEL_CELLS, ncol(object)) else NA,
        SCT_variable_genes_only = if (identical(NORMALIZATION_METHOD, "SCTransform")) SCT_RETURN_ONLY_VARIABLE_GENES else NA,
        elapsed_minutes = elapsed_minutes
    ),
    file.path(OUTPUT_DIRECTORY, "normalization_summary.csv"),
    row.names = FALSE
)

save_session_information()
future::plan(future::sequential)

cat("\nNormalization and variable-feature selection completed successfully.\n")
cat("Finished:", format(Sys.time()), "\n")
