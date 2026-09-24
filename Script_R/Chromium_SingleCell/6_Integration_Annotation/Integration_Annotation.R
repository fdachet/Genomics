###############################################################################
# STEP 6: HARMONY INTEGRATION, CLUSTERING, MARKERS, AND CELL-TYPE ANNOTATION
#
# Input:  exactly one Seurat .rds file in Input/
# Output: all results in Output/
###############################################################################

options(stringsAsFactors = FALSE)
PIPELINE_START_TIME <- Sys.time()


CPU_CORES <- 4L

# Speed settings.
FAST_UMAP <- TRUE# Faster gradient optimisation but UMAP coordinates may vary   'Uniform Manifold Approximation and Projection'
# This correspond to a reduction of dimension to project a high dimensional data on a 2D plot (x,y)
FUTURE_MAX_SIZE_GB <- 8# How many GB an object can be used by 1 core
# FUTURE_MAX_SIZE_GB * Core_Used should be significantly inferior to total memory
MAX_CELLS_PER_CLUSTER <- 2000L    # use Inf  else number 2000 speeds large clusters of hundred of thousand of cells
#it is the q of cells used during the marker-gene statistical test

# Integration.
INTEGRATION_METHOD <- "None"       # "Harmony" or "None"    Harmonise different samples by removing variation
#of each sample using PCA so cell like 'T cell' will be identified the same cell between Sample1 and Sample2
#Harmony is very important if many samples have batch effects or technical biais  
BATCH_COLUMN <- "batch"            # Metadata column used only by Harmony for correction of unwanted batch effects

DIMS_TO_USE <- 1:30  # 1:30  each cell has expression value from thousand of gene, this use PCA 
# only select the most usefull principal components (NPO: not genes)is enough)
#Can use the plot 'PCA elbow' for the number of components needed)

CLUSTER_RESOLUTION <- 0.5# Modify the number of cluster detected resolution = 0.2 → big cluster and sure
#Resolution=0.8 → lot of small cluster but can be bacground noise
RANDOM_SEED <- 12345L

# UMAP plots. These columns only control plot data export.
UMAP_GROUP_COLUMNS <- c("sample_id", "patient", "condition")

# Annotation.
ANNOTATION_METHOD <- "Manual"     # "Manual", "SingleR", "ClustersOnly"
#SingleR → needs reference profiles and uses correlations between the test expression profile and known reference profiles
#Manual → Reads cluster_annotations.csv, or creates cluster_annotations_template.csv.
# ClusterOnly → No biological names are assigned

SINGLER_REFERENCE <- "HumanPrimaryCellAtlas" # or "BlueprintEncode" #Name of the reference file used when anotation=SingleR and assign the best label found


MIN_MARKER_FRACTION <- 0.10  # Gene must be detected in at least this fraction of either comparison group
# Marker significance filter:
# Fold-change threshold: the cluster is analyzed versus all the other cells 

MARKER_SIGNIFICANCE_TYPE <- "adjusted_pvalue"   #"pvalue" or "adjusted_pvalue"
MARKER_SIGNIFICANCE_THRESHOLD <- 0.01 #α Usually 0.01 or 0.05
MIN_MARKER_FC <- 1.5  



# Multicore settings.
MARKER_WORKERS <- CPU_CORES
SINGLER_WORKERS <- CPU_CORES
UMAP_THREADS <- CPU_CORES
###############################################################################
# SCRIPT-RELATIVE INPUT AND OUTPUT DIRECTORIES
###############################################################################

get_script_directory <- function() {
    arguments <- commandArgs(trailingOnly = FALSE)
    file_argument <- grep("^--file=", arguments, value = TRUE)

    if (length(file_argument)) {
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
cat("Started:", format(PIPELINE_START_TIME), "\n\n")

###############################################################################
# HELPER FUNCTIONS
###############################################################################

require_packages <- function(packages) {
    missing <- packages[!vapply(packages, requireNamespace, logical(1), quietly = TRUE)]
    if (length(missing)) {
        stop(
            "Missing required R package(s): ", paste(missing, collapse = ", "),
            "\nRun 00_Install/00_Install_R_Packages_scRNAseq.R first."
        )
    }
}

save_session_information <- function() {
    capture.output(sessionInfo(), file = file.path(OUTPUT_DIRECTORY, "sessionInfo.txt"))
}

sort_cluster_ids <- function(cluster_ids) {
    cluster_ids <- unique(as.character(cluster_ids))
    numeric_ids <- suppressWarnings(as.numeric(cluster_ids))
    if (all(!is.na(numeric_ids))) cluster_ids[order(numeric_ids)] else sort(cluster_ids)
}

write_current_annotation_template <- function(cluster_ids) {
    cluster_ids <- sort_cluster_ids(cluster_ids)
    template <- data.frame(
        cluster = cluster_ids,
        cell_type = paste0("REPLACE_WITH_CELL_TYPE_", cluster_ids),
        stringsAsFactors = FALSE
    )
    write.csv(template, file.path(OUTPUT_DIRECTORY, "cluster_annotations_template.csv"), row.names = FALSE)
}

validate_scalar_number <- function(value, name, minimum = -Inf, maximum = Inf, allow_infinite = FALSE) {
    valid <- is.numeric(value) && length(value) == 1L && !is.na(value)
    if (!allow_infinite) valid <- valid && is.finite(value)
    valid <- valid && value >= minimum && value <= maximum
    if (!valid) stop(name, " must be one numeric value between ", minimum, " and ", maximum, ".")
}

###############################################################################
# VALIDATE USER SETTINGS
###############################################################################

if (!INTEGRATION_METHOD %in% c("Harmony", "None")) {
    stop("INTEGRATION_METHOD must be \"Harmony\" or \"None\".")
}
if (!ANNOTATION_METHOD %in% c("Manual", "SingleR", "ClustersOnly")) {
    stop("ANNOTATION_METHOD must be \"Manual\", \"SingleR\", or \"ClustersOnly\".")
}
if (!SINGLER_REFERENCE %in% c("HumanPrimaryCellAtlas", "BlueprintEncode")) {
    stop("SINGLER_REFERENCE must be \"HumanPrimaryCellAtlas\" or \"BlueprintEncode\".")
}
if (!MARKER_SIGNIFICANCE_TYPE %in% c("pvalue", "adjusted_pvalue")) {
    stop("MARKER_SIGNIFICANCE_TYPE must be \"pvalue\" or \"adjusted_pvalue\".")
}

validate_scalar_number(CLUSTER_RESOLUTION, "CLUSTER_RESOLUTION", minimum = 0)
validate_scalar_number(MIN_MARKER_FRACTION, "MIN_MARKER_FRACTION", minimum = 0, maximum = 1)
validate_scalar_number(MIN_MARKER_FC, "MIN_MARKER_FC", minimum = 1)
validate_scalar_number(MARKER_SIGNIFICANCE_THRESHOLD, "MARKER_SIGNIFICANCE_THRESHOLD", minimum = 0, maximum = 1)
validate_scalar_number(FUTURE_MAX_SIZE_GB, "FUTURE_MAX_SIZE_GB", minimum = 0)
validate_scalar_number(MAX_CELLS_PER_CLUSTER, "MAX_CELLS_PER_CLUSTER", minimum = 1, allow_infinite = TRUE)

if (!is.numeric(DIMS_TO_USE) || !length(DIMS_TO_USE) || anyNA(DIMS_TO_USE) ||
    any(DIMS_TO_USE < 1) || any(DIMS_TO_USE != as.integer(DIMS_TO_USE))) {
    stop("DIMS_TO_USE must contain positive integer dimensions, for example 1:30.")
}
DIMS_TO_USE <- sort(unique(as.integer(DIMS_TO_USE)))

for (worker_setting in c("MARKER_WORKERS", "SINGLER_WORKERS", "UMAP_THREADS")) {
    value <- get(worker_setting)
    if (!is.numeric(value) || length(value) != 1L || is.na(value) ||
        value < 1 || value != as.integer(value)) {
        stop(worker_setting, " must be one positive integer.")
    }
}

detected_logical_cores <- parallel::detectCores(logical = TRUE)
if (!is.na(detected_logical_cores) &&
    max(MARKER_WORKERS, SINGLER_WORKERS, UMAP_THREADS) > detected_logical_cores) {
    warning(
        "At least one worker/thread setting exceeds the detected logical-core count of ",
        detected_logical_cores, "."
    )
}

###############################################################################
# PACKAGES AND INPUT
###############################################################################

require_packages(c("Seurat", "SeuratObject", "ggplot2", "future"))
library(Seurat)
library(ggplot2)

# This is a maximum allowed size for globals exported to one future operation.
# It does not reserve RAM and it is not a total RAM limit for all workers.
options(future.globals.maxSize = FUTURE_MAX_SIZE_GB * 1024^3)
future::plan(future::sequential)

cat("Marker workers:", MARKER_WORKERS, "\n")
cat("SingleR workers:", SINGLER_WORKERS, "\n")
cat("UMAP threads:", UMAP_THREADS, "\n")
cat("Fast UMAP:", FAST_UMAP, "\n")
cat("Future globals maximum:", FUTURE_MAX_SIZE_GB, "GB\n\n")

rds_files <- list.files(
    INPUT_DIRECTORY, pattern = "\\.rds$", recursive = TRUE,
    full.names = TRUE, ignore.case = TRUE
)
if (length(rds_files) != 1L) {
    stop("Place exactly one Seurat RDS file in Input. Found ", length(rds_files), ".")
}

object <- readRDS(rds_files[1L])
if (!inherits(object, "Seurat")) stop("The input RDS file is not a Seurat object.")

set.seed(RANDOM_SEED)
analysis_assay <- if ("SCT" %in% SeuratObject::Assays(object)) "SCT" else "RNA"
SeuratObject::DefaultAssay(object) <- analysis_assay

if (!"pca" %in% SeuratObject::Reductions(object)) {
    stop(
        "The input Seurat object does not contain a PCA reduction. ",
        "Run PCA in the preceding pipeline step before this script."
    )
}

available_pca_dimensions <- ncol(SeuratObject::Embeddings(object, "pca"))
valid_pca_dims <- DIMS_TO_USE[DIMS_TO_USE <= available_pca_dimensions]
if (length(valid_pca_dims) < 2L) {
    stop(
        "Fewer than two requested PCA dimensions are available. Requested: ",
        paste(DIMS_TO_USE, collapse = ","), "; available PCA dimensions: ",
        available_pca_dimensions, "."
    )
}
if (length(valid_pca_dims) < length(DIMS_TO_USE)) {
    warning(
        "Some requested dimensions do not exist and were excluded. Requested: ",
        paste(DIMS_TO_USE, collapse = ","), "; used: ",
        paste(valid_pca_dims, collapse = ","), "."
    )
}

harmony_minutes <- NA_real_
neighbors_clusters_minutes <- NA_real_
umap_minutes <- NA_real_
markers_minutes <- NA_real_
annotation_minutes <- NA_real_
reduction_to_use <- "pca"
harmony_applied <- FALSE

###############################################################################
# OPTIONAL HARMONY INTEGRATION
###############################################################################

if (identical(INTEGRATION_METHOD, "Harmony")) {
    require_packages("harmony")

    metadata_columns <- colnames(object[[]])
    if (!BATCH_COLUMN %in% metadata_columns) {
        stop("Harmony was requested, but the metadata column was not found: ", BATCH_COLUMN)
    }

    batch_values <- as.character(object[[BATCH_COLUMN, drop = TRUE]])
    if (anyNA(batch_values) || any(!nzchar(trimws(batch_values)))) {
        stop("Harmony batch column contains missing or blank values: ", BATCH_COLUMN)
    }

    unique_batches <- unique(batch_values)

    if (length(unique_batches) > 1L) {
        if ("condition" %in% metadata_columns) {
            condition_values <- as.character(object[["condition", drop = TRUE]])
            valid_pairs <- !is.na(condition_values) & nzchar(trimws(condition_values))
            batch_condition_pairs <- unique(data.frame(
                batch = batch_values[valid_pairs],
                condition = condition_values[valid_pairs],
                stringsAsFactors = FALSE
            ))

            if (length(unique(batch_condition_pairs$condition)) > 1L) {
                conditions_per_batch <- tapply(
                    batch_condition_pairs$condition,
                    batch_condition_pairs$batch,
                    function(x) length(unique(x))
                )
                if (all(conditions_per_batch == 1L)) {
                    stop(
                        "Harmony correction was stopped because every batch contains only one condition. ",
                        "The batch and condition effects are confounded, so correcting batch could remove ",
                        "the biological condition effect."
                    )
                }
            }
        }

        start_time <- Sys.time()
        object <- harmony::RunHarmony(
            object = object,
            group.by.vars = BATCH_COLUMN,
            reduction.use = "pca",
            dims.use = valid_pca_dims,
            reduction.save = "harmony",
            verbose = TRUE
        )
        harmony_minutes <- as.numeric(difftime(Sys.time(), start_time, units = "mins"))
        reduction_to_use <- "harmony"
        harmony_applied <- TRUE
    } else {
        warning(
            "Harmony was requested, but ", BATCH_COLUMN, " contains only one value (",
            unique_batches[1L], "). Harmony was skipped and PCA will be used."
        )
    }
}

###############################################################################
# ALWAYS RECALCULATE NEIGHBORS, CLUSTERS, AND UMAP
#
# This block runs with either:
#   Harmony dimensions, when Harmony was successfully applied; or
#   PCA dimensions, when INTEGRATION_METHOD = "None" or Harmony was skipped.
###############################################################################

if (!reduction_to_use %in% SeuratObject::Reductions(object)) {
    stop("Required reduction was not found after integration: ", reduction_to_use)
}

available_reduction_dimensions <- ncol(SeuratObject::Embeddings(object, reduction_to_use))
valid_dims <- DIMS_TO_USE[DIMS_TO_USE <= available_reduction_dimensions]
if (length(valid_dims) < 2L) {
    stop("Fewer than two valid dimensions are available in reduction: ", reduction_to_use)
}

cat("Reduction used for neighbors, clustering, and UMAP:", reduction_to_use, "\n")
cat("Dimensions used:", paste(valid_dims, collapse = ","), "\n")
cat("Clustering resolution:", CLUSTER_RESOLUTION, "\n\n")

neighbor_graph_name <- paste0(reduction_to_use, "_nn")
snn_graph_name <- paste0(reduction_to_use, "_snn")

start_time <- Sys.time()
object <- Seurat::FindNeighbors(
    object,
    reduction = reduction_to_use,
    dims = valid_dims,
    graph.name = c(neighbor_graph_name, snn_graph_name),
    verbose = TRUE
)
object <- Seurat::FindClusters(
    object,
    graph.name = snn_graph_name,
    resolution = CLUSTER_RESOLUTION,
    random.seed = RANDOM_SEED,
    cluster.name = "seurat_clusters",
    verbose = TRUE
)
neighbors_clusters_minutes <- as.numeric(difftime(Sys.time(), start_time, units = "mins"))

start_time <- Sys.time()
object <- Seurat::RunUMAP(
    object,
    reduction = reduction_to_use,
    dims = valid_dims,
    reduction.name = "umap",
    seed.use = RANDOM_SEED,
    n_threads = UMAP_THREADS,
    uwot.sgd = FAST_UMAP,
    verbose = TRUE
)
umap_minutes <- as.numeric(difftime(Sys.time(), start_time, units = "mins"))

if (!"seurat_clusters" %in% colnames(object[[]])) {
    stop("FindClusters completed without creating the seurat_clusters metadata column.")
}
if (!"umap" %in% SeuratObject::Reductions(object)) {
    stop("RunUMAP completed without creating the umap reduction.")
}

cluster_ids <- as.character(object$seurat_clusters)
ordered_clusters <- sort_cluster_ids(cluster_ids)
cluster_counts <- data.frame(
    cluster = ordered_clusters,
    cell_count = as.integer(table(factor(cluster_ids, levels = ordered_clusters))),
    stringsAsFactors = FALSE
)
write.csv(cluster_counts, file.path(OUTPUT_DIRECTORY, "cluster_cell_counts.csv"), row.names = FALSE)

cat("Number of clusters:", nrow(cluster_counts), "\n")
print(cluster_counts)

###############################################################################
# MARKER IDENTIFICATION
###############################################################################

MIN_MARKER_LOG2FC <- log2(MIN_MARKER_FC)
SIGNIFICANCE_COLUMN <- if (MARKER_SIGNIFICANCE_TYPE == "pvalue") "p_val" else "p_val_adj"

cat("\nMarker minimum real FC:", MIN_MARKER_FC, "\n")
cat("Marker minimum log2FC:", MIN_MARKER_LOG2FC, "\n")
cat("Marker minimum fraction:", MIN_MARKER_FRACTION, "\n")
cat("Marker significance column:", SIGNIFICANCE_COLUMN, "\n")
cat("Marker significance threshold:", MARKER_SIGNIFICANCE_THRESHOLD, "\n")

if ("RNA" %in% SeuratObject::Assays(object)) {
    if (inherits(object[["RNA"]], "Assay5")) {
        rna_layers <- SeuratObject::Layers(object[["RNA"]])
        multiple_count_layers <- sum(grepl("^counts($|\\.)", rna_layers)) > 1L
        multiple_data_layers <- sum(grepl("^data($|\\.)", rna_layers)) > 1L

        if (multiple_count_layers || multiple_data_layers) {
            object <- SeuratObject::JoinLayers(object, assay = "RNA")
        }
    }

    SeuratObject::DefaultAssay(object) <- "RNA"
    rna_layers <- SeuratObject::Layers(object[["RNA"]])
    normalized_data_layers <- grep("^data($|\\.)", rna_layers, value = TRUE)
    RNA_NORMALIZATION_PERFORMED <- FALSE

    if (length(normalized_data_layers) == 0L) {
        cat("RNA normalized data layer is absent; running NormalizeData().\n")
        object <- Seurat::NormalizeData(object, assay = "RNA", verbose = TRUE)
        RNA_NORMALIZATION_PERFORMED <- TRUE
    } else {
        selected_data_layer <- normalized_data_layers[1L]
        data_layer <- suppressWarnings(tryCatch(
            SeuratObject::LayerData(
                object,
                assay = "RNA",
                layer = selected_data_layer,
                fast = TRUE
            ),
            error = function(e) NULL
        ))

        if (is.null(data_layer) || nrow(data_layer) == 0L || ncol(data_layer) == 0L) {
            cat("RNA normalized data layer is empty; running NormalizeData().\n")
            object <- Seurat::NormalizeData(object, assay = "RNA", verbose = TRUE)
            RNA_NORMALIZATION_PERFORMED <- TRUE
        } else {
            cat("Using existing RNA normalized data layer:", selected_data_layer, "\n")
        }
    }
} else {
    RNA_NORMALIZATION_PERFORMED <- FALSE
    SeuratObject::DefaultAssay(object) <- analysis_assay
}

SeuratObject::Idents(object) <- "seurat_clusters"

if (MARKER_WORKERS > 1L) {
    future::plan(future::multisession, workers = MARKER_WORKERS)
} else {
    future::plan(future::sequential)
}

cat("Active future workers for markers:", future::nbrOfWorkers(), "\n")
cat("Presto fast Wilcoxon available:", requireNamespace("presto", quietly = TRUE), "\n")

start_time <- Sys.time()
markers_all <- Seurat::FindAllMarkers(
    object,
    only.pos = TRUE,
    test.use = "wilcox",
    min.pct = MIN_MARKER_FRACTION,
    logfc.threshold = MIN_MARKER_LOG2FC,
    max.cells.per.ident = MAX_CELLS_PER_CLUSTER,
    random.seed = RANDOM_SEED,
    return.thresh = 1,
    densify = FALSE,
    assay = SeuratObject::DefaultAssay(object),
    verbose = TRUE
)
markers_minutes <- as.numeric(difftime(Sys.time(), start_time, units = "mins"))
future::plan(future::sequential)

if (nrow(markers_all) == 0L) {
    warning("FindAllMarkers returned no markers before significance filtering.")
    markers <- markers_all
} else {
    if (!SIGNIFICANCE_COLUMN %in% colnames(markers_all)) {
        stop("FindAllMarkers did not return the expected column: ", SIGNIFICANCE_COLUMN)
    }
    markers <- markers_all[
        !is.na(markers_all[[SIGNIFICANCE_COLUMN]]) &
        markers_all[[SIGNIFICANCE_COLUMN]] <= MARKER_SIGNIFICANCE_THRESHOLD,
        ,
        drop = FALSE
    ]
}

prepare_marker_export <- function(marker_table) {
    marker_table <- as.data.frame(marker_table, stringsAsFactors = FALSE)

    if ("avg_log2FC" %in% colnames(marker_table)) {
        marker_table$FC <- 2^marker_table$avg_log2FC
    } else if ("avg_logFC" %in% colnames(marker_table)) {
        warning("FindAllMarkers returned avg_logFC instead of avg_log2FC. FC was calculated with exp(avg_logFC).")
        marker_table$FC <- exp(marker_table$avg_logFC)
    } else {
        stop("FindAllMarkers did not return avg_log2FC or avg_logFC; the real FC column cannot be calculated.")
    }

    rename_columns <- c(
        "pct.1" = "fraction_cells_expressing_in_cluster",
        "pct.2" = "fraction_cells_expressing_in_all_other_cells"
    )

    for (old_name in names(rename_columns)) {
        if (old_name %in% colnames(marker_table)) {
            colnames(marker_table)[colnames(marker_table) == old_name] <- rename_columns[[old_name]]
        }
    }

    logfc_column <- if ("avg_log2FC" %in% colnames(marker_table)) "avg_log2FC" else "avg_logFC"
    preferred_order <- c(
        "p_val",
        logfc_column,
        "FC",
        "fraction_cells_expressing_in_cluster",
        "fraction_cells_expressing_in_all_other_cells",
        "p_val_adj",
        "cluster",
        "gene"
    )
    preferred_order <- preferred_order[preferred_order %in% colnames(marker_table)]
    remaining_columns <- setdiff(colnames(marker_table), preferred_order)

    marker_table[, c(preferred_order, remaining_columns), drop = FALSE]
}

markers_all_export <- prepare_marker_export(markers_all)
markers_export <- prepare_marker_export(markers)

write.csv(
    markers_all_export,
    file.path(OUTPUT_DIRECTORY, "cluster_markers_before_significance_filter.csv"),
    row.names = FALSE
)
write.csv(
    markers_export,
    file.path(OUTPUT_DIRECTORY, "cluster_markers.csv"),
    row.names = FALSE
)

cat("Markers before significance filtering:", nrow(markers_all), "\n")
cat("Markers after significance filtering:", nrow(markers), "\n")
cat("Added real FC column and explicit expression-fraction column names to marker exports.\n")

###############################################################################
# ANNOTATION
###############################################################################

annotation_file <- list.files(
    INPUT_DIRECTORY,
    pattern = "cluster.*annotation.*\\.csv$",
    recursive = TRUE,
    full.names = TRUE,
    ignore.case = TRUE
)

start_time <- Sys.time()
current_clusters <- sort_cluster_ids(object$seurat_clusters)

if (identical(ANNOTATION_METHOD, "Manual")) {
    use_manual_annotations <- FALSE

    if (length(annotation_file) == 1L) {
        annotation_table <- read.csv(annotation_file, check.names = FALSE, stringsAsFactors = FALSE)

        if (!all(c("cluster", "cell_type") %in% colnames(annotation_table))) {
            stop("Manual annotation CSV must contain cluster and cell_type columns.")
        }

        annotation_table$cluster <- trimws(as.character(annotation_table$cluster))
        annotation_table$cell_type <- trimws(as.character(annotation_table$cell_type))

        if (any(!nzchar(annotation_table$cluster)) || any(!nzchar(annotation_table$cell_type))) {
            stop("Manual annotation CSV contains blank cluster or cell_type values.")
        }
        if (anyDuplicated(annotation_table$cluster)) {
            duplicated_ids <- unique(annotation_table$cluster[duplicated(annotation_table$cluster)])
            stop("Manual annotation CSV contains duplicated cluster IDs: ", paste(duplicated_ids, collapse = ", "))
        }

        annotation_clusters <- sort_cluster_ids(annotation_table$cluster)
        missing_clusters <- setdiff(current_clusters, annotation_clusters)
        extra_clusters <- setdiff(annotation_clusters, current_clusters)

        if (length(missing_clusters) || length(extra_clusters)) {
            write_current_annotation_template(current_clusters)
            warning(
                "The manual annotation file does not match the current clustering and was ignored. ",
                if (length(missing_clusters)) paste0("Missing current clusters: ", paste(missing_clusters, collapse = ", "), ". ") else "",
                if (length(extra_clusters)) paste0("Obsolete/extra clusters: ", paste(extra_clusters, collapse = ", "), ". ") else "",
                "A new cluster_annotations_template.csv was written to Output."
            )
        } else {
            use_manual_annotations <- TRUE
        }

        if (use_manual_annotations) {
            cluster_to_type <- setNames(annotation_table$cell_type, annotation_table$cluster)
            object$cell_type <- unname(cluster_to_type[as.character(object$seurat_clusters)])
        } else {
            object$cell_type <- paste0("Cluster_", object$seurat_clusters)
        }

    } else if (length(annotation_file) == 0L) {
        object$cell_type <- paste0("Cluster_", object$seurat_clusters)
        write_current_annotation_template(current_clusters)
        warning(
            "No manual annotation file was provided. Numerical cluster labels were retained, ",
            "and cluster_annotations_template.csv was written to Output."
        )
    } else {
        stop("More than one cluster annotation CSV was found in Input.")
    }

} else if (identical(ANNOTATION_METHOD, "SingleR")) {
    require_packages(c("SingleR", "celldex", "SingleCellExperiment", "BiocParallel"))

    if (!"RNA" %in% SeuratObject::Assays(object)) {
        stop("SingleR annotation requires an RNA assay.")
    }

    reference <- switch(
        SINGLER_REFERENCE,
        "HumanPrimaryCellAtlas" = celldex::HumanPrimaryCellAtlasData(),
        "BlueprintEncode" = celldex::BlueprintEncodeData()
    )

    sce <- Seurat::as.SingleCellExperiment(object, assay = "RNA")
    singleR_param <- BiocParallel::SnowParam(
        workers = max(1L, SINGLER_WORKERS),
        type = "SOCK",
        progressbar = TRUE,
        RNGseed = RANDOM_SEED
    )

    predictions <- SingleR::SingleR(
        test = sce,
        ref = reference,
        labels = reference$label.main,
        clusters = object$seurat_clusters,
        BPPARAM = singleR_param
    )

    cluster_labels <- setNames(as.character(predictions$pruned.labels), rownames(predictions))
    missing_pruned <- is.na(cluster_labels) | !nzchar(cluster_labels)
    cluster_labels[missing_pruned] <- as.character(predictions$labels[missing_pruned])

    assigned_labels <- unname(cluster_labels[as.character(object$seurat_clusters)])
    unresolved <- is.na(assigned_labels) | !nzchar(assigned_labels)
    assigned_labels[unresolved] <- paste0("Cluster_", object$seurat_clusters[unresolved])
    object$cell_type <- assigned_labels

    write.csv(
        as.data.frame(predictions),
        file.path(OUTPUT_DIRECTORY, "SingleR_cluster_predictions.csv"),
        row.names = TRUE
    )

} else {
    object$cell_type <- paste0("Cluster_", object$seurat_clusters)
}

annotation_minutes <- as.numeric(difftime(Sys.time(), start_time, units = "mins"))
SeuratObject::Idents(object) <- "cell_type"

###############################################################################
# OUTPUTS
###############################################################################

saveRDS(
    object,
    file.path(OUTPUT_DIRECTORY, "seurat_integrated_annotated.rds"),
    compress = FALSE
)

p_clusters <- Seurat::DimPlot(
    object,
    reduction = "umap",
    group.by = "seurat_clusters",
    label = TRUE,
    repel = TRUE
) + ggplot2::ggtitle(
    paste0(
        "Seurat clusters | resolution = ", CLUSTER_RESOLUTION,
        " | reduction = ", reduction_to_use
    )
)

ggplot2::ggsave(
    file.path(OUTPUT_DIRECTORY, "UMAP_by_Seurat_clusters.png"),
    p_clusters, width = 12, height = 9, dpi = 300
)
ggplot2::ggsave(
    file.path(OUTPUT_DIRECTORY, "UMAP_by_Seurat_clusters.pdf"),
    p_clusters, width = 12, height = 9
)

p_celltype <- Seurat::DimPlot(
    object,
    reduction = "umap",
    group.by = "cell_type",
    label = TRUE,
    repel = TRUE
) + ggplot2::ggtitle("Annotated cell types")

ggplot2::ggsave(
    file.path(OUTPUT_DIRECTORY, "UMAP_annotated_cell_types.png"),
    p_celltype, width = 12, height = 9, dpi = 300
)
ggplot2::ggsave(
    file.path(OUTPUT_DIRECTORY, "UMAP_annotated_cell_types.pdf"),
    p_celltype, width = 12, height = 9
)

available_metadata_columns <- colnames(object[[]])

for (group_column in unique(UMAP_GROUP_COLUMNS)) {
    if (!group_column %in% available_metadata_columns) {
        warning("UMAP metadata column was not found and was skipped: ", group_column)
        next
    }

    group_values <- object[[group_column, drop = TRUE]]
    nonmissing_values <- unique(group_values[!is.na(group_values)])
    number_groups <- length(nonmissing_values)
    safe_group_name <- gsub("[^A-Za-z0-9_-]+", "_", group_column)

    p_metadata <- Seurat::DimPlot(
        object,
        reduction = "umap",
        group.by = group_column,
        label = FALSE
    ) + ggplot2::ggtitle(paste("UMAP by", group_column))

    ggplot2::ggsave(
        file.path(OUTPUT_DIRECTORY, paste0("UMAP_by_", safe_group_name, ".png")),
        p_metadata, width = 10, height = 8, dpi = 300
    )
    ggplot2::ggsave(
        file.path(OUTPUT_DIRECTORY, paste0("UMAP_by_", safe_group_name, ".pdf")),
        p_metadata, width = 10, height = 8
    )

    cat(
        "Exported UMAP grouped by ", group_column,
        " with ", number_groups, " unique group(s).\n",
        sep = ""
    )
}

annotation_summary <- as.data.frame(table(
    sample_id = if ("sample_id" %in% available_metadata_columns) object$sample_id else "Sample",
    cell_type = object$cell_type
))
write.csv(
    annotation_summary,
    file.path(OUTPUT_DIRECTORY, "cell_type_counts_by_sample.csv"),
    row.names = FALSE
)

cluster_assignment <- data.frame(
    cell = colnames(object),
    seurat_cluster = as.character(object$seurat_clusters),
    cell_type = as.character(object$cell_type),
    stringsAsFactors = FALSE
)
for (metadata_column in unique(UMAP_GROUP_COLUMNS)) {
    if (metadata_column %in% available_metadata_columns) {
        cluster_assignment[[metadata_column]] <- object[[metadata_column, drop = TRUE]]
    }
}
write.csv(
    cluster_assignment,
    file.path(OUTPUT_DIRECTORY, "cell_cluster_assignments.csv"),
    row.names = FALSE
)

pipeline_elapsed_minutes <- as.numeric(difftime(Sys.time(), PIPELINE_START_TIME, units = "mins"))

summary_table <- data.frame(
    input_RDS = basename(rds_files[1L]),
    analysis_assay = analysis_assay,
    integration_method_requested = INTEGRATION_METHOD,
    Harmony_applied = harmony_applied,
    Harmony_batch_column = BATCH_COLUMN,
    downstream_reduction = reduction_to_use,
    neighbor_graph = neighbor_graph_name,
    SNN_graph = snn_graph_name,
    dimensions_requested = paste(DIMS_TO_USE, collapse = ","),
    dimensions_used = paste(valid_dims, collapse = ","),
    cluster_resolution = CLUSTER_RESOLUTION,
    number_of_clusters = nrow(cluster_counts),
    annotation_method = ANNOTATION_METHOD,
    SingleR_reference = SINGLER_REFERENCE,
    UMAP_group_columns = paste(unique(UMAP_GROUP_COLUMNS), collapse = ";"),
    marker_workers_requested = MARKER_WORKERS,
    SingleR_workers_requested = SINGLER_WORKERS,
    UMAP_threads_requested = UMAP_THREADS,
    fast_UMAP = FAST_UMAP,
    future_globals_max_GB = FUTURE_MAX_SIZE_GB,
    max_cells_per_cluster_for_markers = MAX_CELLS_PER_CLUSTER,
    RNA_NormalizeData_performed = RNA_NORMALIZATION_PERFORMED,
    marker_minimum_FC = MIN_MARKER_FC,
    marker_minimum_log2FC = MIN_MARKER_LOG2FC,
    marker_minimum_fraction = MIN_MARKER_FRACTION,
    marker_significance_type = MARKER_SIGNIFICANCE_TYPE,
    marker_significance_column = SIGNIFICANCE_COLUMN,
    marker_significance_threshold = MARKER_SIGNIFICANCE_THRESHOLD,
    markers_before_significance_filter = nrow(markers_all),
    markers_after_significance_filter = nrow(markers),
    Presto_installed = requireNamespace("presto", quietly = TRUE),
    Harmony_minutes = harmony_minutes,
    neighbors_clusters_minutes = neighbors_clusters_minutes,
    UMAP_minutes = umap_minutes,
    marker_detection_minutes = markers_minutes,
    annotation_minutes = annotation_minutes,
    total_pipeline_minutes = pipeline_elapsed_minutes,
    stringsAsFactors = FALSE
)

write.csv(
    summary_table,
    file.path(OUTPUT_DIRECTORY, "integration_annotation_summary.csv"),
    row.names = FALSE
)

save_session_information()

cat("\nPipeline completed successfully.\n")
cat("Harmony applied:", harmony_applied, "\n")
cat("Reduction used:", reduction_to_use, "\n")
cat("Clustering resolution:", CLUSTER_RESOLUTION, "\n")
cat("Number of clusters:", nrow(cluster_counts), "\n")
cat("Harmony minutes:", harmony_minutes, "\n")
cat("Neighbors/clustering minutes:", neighbors_clusters_minutes, "\n")
cat("UMAP minutes:", umap_minutes, "\n")
cat("Marker detection minutes:", markers_minutes, "\n")
cat("Marker significance filter:", SIGNIFICANCE_COLUMN, "<=", MARKER_SIGNIFICANCE_THRESHOLD, "\n")
cat("Markers retained:", nrow(markers), "of", nrow(markers_all), "\n")
cat("Annotation minutes:", annotation_minutes, "\n")
cat("Total pipeline minutes:", pipeline_elapsed_minutes, "\n")
cat("Finished:", format(Sys.time()), "\n")
