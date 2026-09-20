###############################################################################
# NUMBERED BIOINFORMATICS PIPELINE
#
# This script always reads from the Input folder located beside the script and
# writes to the Output folder located beside the script.
#
# Run from RStudio or with:
#     Rscript SCRIPT_NAME.R
###############################################################################

options(stringsAsFactors = FALSE)
setwd("C:\\scRNAseq\\5_Clustering")

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
            "\nRun the top-level 00_Install_R_Packages.R script first."
        )
    }
}

save_session_information <- function() {
    capture.output(sessionInfo(), file = file.path(OUTPUT_DIRECTORY, "sessionInfo.txt"))
}

###############################################################################
# USER SETTINGS
###############################################################################

NUMBER_PCS <- 50L
DIMS_TO_USE <- 1:30
CLUSTER_RESOLUTION <- 0.5
RANDOM_SEED <- 12345L

###############################################################################
# PACKAGES
###############################################################################

require_packages(c("Seurat", "SeuratObject", "ggplot2", "patchwork"))
library(Seurat)
library(ggplot2)
library(patchwork)

rds_files <- list.files(INPUT_DIRECTORY, pattern = "\\.rds$", recursive = TRUE, full.names = TRUE, ignore.case = TRUE)
if (length(rds_files) != 1L) stop("Place exactly one normalized Seurat RDS file in Input.")

object <- readRDS(rds_files[1L])
if (!inherits(object, "Seurat")) stop("Input RDS is not a Seurat object.")

set.seed(RANDOM_SEED)

analysis_assay <- if ("SCT" %in% Assays(object)) "SCT" else "RNA"
DefaultAssay(object) <- analysis_assay

if (analysis_assay == "RNA" && !"scale.data" %in% Layers(object[["RNA"]])) {
    object <- ScaleData(object, assay = "RNA", verbose = TRUE)
}

object <- RunPCA(object, assay = analysis_assay, npcs = NUMBER_PCS, verbose = TRUE)
valid_dims <- DIMS_TO_USE[DIMS_TO_USE <= ncol(Embeddings(object, "pca"))]
if (!length(valid_dims)) stop("No requested PCA dimensions are available.")

object <- FindNeighbors(object, reduction = "pca", dims = valid_dims, verbose = TRUE)
object <- FindClusters(object, resolution = CLUSTER_RESOLUTION, random.seed = RANDOM_SEED, verbose = TRUE)
object <- RunUMAP(object, reduction = "pca", dims = valid_dims, seed.use = RANDOM_SEED, verbose = TRUE)

saveRDS(object, file.path(OUTPUT_DIRECTORY, "seurat_clustered.rds"), compress = FALSE)

p_cluster <- DimPlot(object, reduction = "umap", group.by = "seurat_clusters", label = TRUE, repel = TRUE) +
    ggtitle("UMAP by cluster")

ggsave(file.path(OUTPUT_DIRECTORY, "UMAP_by_cluster.png"), p_cluster, width = 10, height = 8, dpi = 300)
ggsave(file.path(OUTPUT_DIRECTORY, "UMAP_by_cluster.pdf"), p_cluster, width = 10, height = 8)

if ("sample_id" %in% colnames(object[[]])) {
    p_sample <- DimPlot(object, reduction = "umap", group.by = "sample_id") + ggtitle("UMAP by sample")
    ggsave(file.path(OUTPUT_DIRECTORY, "UMAP_by_sample.png"), p_sample, width = 10, height = 8, dpi = 300)
    ggsave(file.path(OUTPUT_DIRECTORY, "UMAP_by_sample.pdf"), p_sample, width = 10, height = 8)
}

pdf(file.path(OUTPUT_DIRECTORY, "PCA_elbow_plot.pdf"), width = 8, height = 6)
print(ElbowPlot(object, ndims = min(NUMBER_PCS, 50L)))
dev.off()

cluster_counts <- as.data.frame(table(
    cluster = object$seurat_clusters,
    sample_id = if ("sample_id" %in% colnames(object[[]])) object$sample_id else "Sample"
))
write.csv(cluster_counts, file.path(OUTPUT_DIRECTORY, "cluster_counts_by_sample.csv"), row.names = FALSE)

write.csv(
    data.frame(
        parameter = c("analysis_assay", "NUMBER_PCS", "DIMS_TO_USE", "CLUSTER_RESOLUTION"),
        value = c(analysis_assay, NUMBER_PCS, paste(valid_dims, collapse = ","), CLUSTER_RESOLUTION)
    ),
    file.path(OUTPUT_DIRECTORY, "clustering_parameters.csv"),
    row.names = FALSE
)

save_session_information()
cat("\nDimensionality reduction and clustering completed successfully.\n")
