###############################################################################
# STEP 7: SAMPLE-AWARE PSEUDOBULK DIFFERENTIAL EXPRESSION WITH edgeR
#
# Input:  exactly one annotated Seurat .rds file in Input/
# Output: all results in Output/
###############################################################################

options(stringsAsFactors = FALSE)
setwd("C:\\scRNAseq\\7_Pseudobulk_DE")
PIPELINE_START_TIME <- Sys.time()

###############################################################################
# USER SETTINGS
###############################################################################

SAMPLE_COLUMN <- "sample_id"
CELL_TYPE_COLUMN <- "cell_type"
TEST_VARIABLE <- "condition"

# Contrast levels:
# - Use exact metadata values, for example "Control" and "Treatment".
# - Use "AUTO" only when TEST_VARIABLE contains exactly two observed levels.
# - When both are AUTO, the first observed level becomes the reference and the
#   second observed level becomes the test. The chosen contrast is logged and
#   exported to pseudobulk_contrast_used.csv.
REFERENCE_LEVEL <- "AUTO"
TEST_LEVEL <- "AUTO"

# The formula must include TEST_VARIABLE and an intercept.
# Additional sample-level covariates may be added, for example:
# DESIGN_FORMULA <- "~ patient + condition"
DESIGN_FORMULA <- "~ condition"

MINIMUM_CELLS_PER_SAMPLE_CELLTYPE <- 20L
MINIMUM_SAMPLES_PER_GROUP <- 2L
FDR_THRESHOLD <- 0.05
MINIMUM_REAL_FC <- 1.2
LOG2FC_THRESHOLD <- log2(MINIMUM_REAL_FC)

###############################################################################
# SCRIPT-RELATIVE INPUT AND OUTPUT DIRECTORIES
###############################################################################

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
cat("Started:", format(PIPELINE_START_TIME), "\n\n")

###############################################################################
# HELPER FUNCTIONS
###############################################################################

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

sanitize_filename <- function(value) {
    gsub("[^A-Za-z0-9_.-]", "_", value)
}

is_auto_level <- function(value) {
    is.null(value) ||
        length(value) != 1L ||
        is.na(value) ||
        !nzchar(trimws(as.character(value))) ||
        identical(toupper(trimws(as.character(value))), "AUTO")
}

resolve_contrast_levels <- function(observed_levels, reference_setting, test_setting, variable_name) {
    observed_levels <- unique(trimws(as.character(observed_levels)))
    observed_levels <- observed_levels[!is.na(observed_levels) & nzchar(observed_levels)]

    if (length(observed_levels) < 2L) {
        stop(
            "Pseudobulk differential expression requires at least two levels in ",
            variable_name, ". Observed level(s): ",
            if (length(observed_levels)) paste(observed_levels, collapse = ", ") else "<none>",
            "."
        )
    }

    reference_is_auto <- is_auto_level(reference_setting)
    test_is_auto <- is_auto_level(test_setting)

    if (!reference_is_auto) {
        reference_setting <- trimws(as.character(reference_setting))
        if (!reference_setting %in% observed_levels) {
            stop(
                "REFERENCE_LEVEL '", reference_setting, "' is not present in ",
                variable_name, ". Observed levels: ",
                paste(observed_levels, collapse = ", "), "."
            )
        }
    }

    if (!test_is_auto) {
        test_setting <- trimws(as.character(test_setting))
        if (!test_setting %in% observed_levels) {
            stop(
                "TEST_LEVEL '", test_setting, "' is not present in ",
                variable_name, ". Observed levels: ",
                paste(observed_levels, collapse = ", "), "."
            )
        }
    }

    if (reference_is_auto && test_is_auto) {
        if (length(observed_levels) != 2L) {
            stop(
                "REFERENCE_LEVEL and TEST_LEVEL are both AUTO, but ",
                variable_name, " contains ", length(observed_levels),
                " levels: ", paste(observed_levels, collapse = ", "),
                ". Specify the two exact levels to compare."
            )
        }
        reference_level <- observed_levels[1L]
        test_level <- observed_levels[2L]
    } else if (reference_is_auto) {
        remaining_levels <- setdiff(observed_levels, test_setting)
        if (length(remaining_levels) != 1L) {
            stop(
                "REFERENCE_LEVEL is AUTO, but more than one alternative reference level exists: ",
                paste(remaining_levels, collapse = ", "),
                ". Specify REFERENCE_LEVEL explicitly."
            )
        }
        reference_level <- remaining_levels[1L]
        test_level <- test_setting
    } else if (test_is_auto) {
        remaining_levels <- setdiff(observed_levels, reference_setting)
        if (length(remaining_levels) != 1L) {
            stop(
                "TEST_LEVEL is AUTO, but more than one alternative test level exists: ",
                paste(remaining_levels, collapse = ", "),
                ". Specify TEST_LEVEL explicitly."
            )
        }
        reference_level <- reference_setting
        test_level <- remaining_levels[1L]
    } else {
        reference_level <- reference_setting
        test_level <- test_setting
    }

    if (identical(reference_level, test_level)) {
        stop("REFERENCE_LEVEL and TEST_LEVEL must be different.")
    }

    list(
        reference = reference_level,
        test = test_level,
        observed = observed_levels
    )
}

validate_sample_level_constant <- function(metadata, sample_column, variables) {
    sample_ids <- unique(as.character(metadata[[sample_column]]))

    for (variable in variables) {
        inconsistent_samples <- character(0)

        for (sample_id in sample_ids) {
            sample_values <- metadata[as.character(metadata[[sample_column]]) == sample_id, variable]
            sample_values <- unique(trimws(as.character(sample_values)))
            sample_values <- sample_values[!is.na(sample_values) & nzchar(sample_values)]

            if (length(sample_values) != 1L) {
                inconsistent_samples <- c(inconsistent_samples, sample_id)
            }
        }

        if (length(inconsistent_samples)) {
            stop(
                "Metadata column '", variable,
                "' must have exactly one non-missing value within each sample. ",
                "Problematic sample(s): ",
                paste(inconsistent_samples, collapse = ", "), "."
            )
        }
    }
}

###############################################################################
# VALIDATE USER SETTINGS
###############################################################################

if (!is.character(SAMPLE_COLUMN) || length(SAMPLE_COLUMN) != 1L || !nzchar(SAMPLE_COLUMN)) {
    stop("SAMPLE_COLUMN must be one non-empty column name.")
}
if (!is.character(CELL_TYPE_COLUMN) || length(CELL_TYPE_COLUMN) != 1L || !nzchar(CELL_TYPE_COLUMN)) {
    stop("CELL_TYPE_COLUMN must be one non-empty column name.")
}
if (!is.character(TEST_VARIABLE) || length(TEST_VARIABLE) != 1L || !nzchar(TEST_VARIABLE)) {
    stop("TEST_VARIABLE must be one non-empty column name.")
}
if (!is.numeric(MINIMUM_CELLS_PER_SAMPLE_CELLTYPE) ||
    length(MINIMUM_CELLS_PER_SAMPLE_CELLTYPE) != 1L ||
    is.na(MINIMUM_CELLS_PER_SAMPLE_CELLTYPE) ||
    MINIMUM_CELLS_PER_SAMPLE_CELLTYPE < 1 ||
    MINIMUM_CELLS_PER_SAMPLE_CELLTYPE != as.integer(MINIMUM_CELLS_PER_SAMPLE_CELLTYPE)) {
    stop("MINIMUM_CELLS_PER_SAMPLE_CELLTYPE must be one positive integer.")
}
if (!is.numeric(MINIMUM_SAMPLES_PER_GROUP) ||
    length(MINIMUM_SAMPLES_PER_GROUP) != 1L ||
    is.na(MINIMUM_SAMPLES_PER_GROUP) ||
    MINIMUM_SAMPLES_PER_GROUP < 2 ||
    MINIMUM_SAMPLES_PER_GROUP != as.integer(MINIMUM_SAMPLES_PER_GROUP)) {
    stop("MINIMUM_SAMPLES_PER_GROUP must be one integer greater than or equal to 2.")
}
if (!is.numeric(FDR_THRESHOLD) || length(FDR_THRESHOLD) != 1L ||
    is.na(FDR_THRESHOLD) || FDR_THRESHOLD < 0 || FDR_THRESHOLD > 1) {
    stop("FDR_THRESHOLD must be one number between 0 and 1.")
}
if (!is.numeric(MINIMUM_REAL_FC) || length(MINIMUM_REAL_FC) != 1L ||
    is.na(MINIMUM_REAL_FC) || MINIMUM_REAL_FC < 1) {
    stop("MINIMUM_REAL_FC must be one number greater than or equal to 1.")
}

design_formula <- stats::as.formula(DESIGN_FORMULA)
design_variables <- all.vars(design_formula)

if (!TEST_VARIABLE %in% design_variables) {
    stop(
        "DESIGN_FORMULA must include TEST_VARIABLE '", TEST_VARIABLE,
        "'. Current formula: ", DESIGN_FORMULA
    )
}
if (attr(stats::terms(design_formula), "intercept") != 1L) {
    stop(
        "DESIGN_FORMULA must include an intercept so TEST_LEVEL can be tested ",
        "against REFERENCE_LEVEL. Do not use a '~ 0 +' design in this script."
    )
}

###############################################################################
# PACKAGES AND INPUT
###############################################################################

require_packages(c("Seurat", "SeuratObject", "Matrix", "edgeR", "ggplot2"))

rds_files <- list.files(
    INPUT_DIRECTORY,
    pattern = "\\.rds$",
    recursive = TRUE,
    full.names = TRUE,
    ignore.case = TRUE
)

if (length(rds_files) != 1L) {
    stop(
        "Place exactly one annotated Seurat RDS file in Input. Found ",
        length(rds_files), "."
    )
}

object <- readRDS(rds_files[1L])
if (!inherits(object, "Seurat")) stop("The input RDS file is not a Seurat object.")
if (!"RNA" %in% SeuratObject::Assays(object)) stop("The Seurat object does not contain an RNA assay.")

metadata <- object[[]]
required_metadata <- unique(c(SAMPLE_COLUMN, CELL_TYPE_COLUMN, TEST_VARIABLE, design_variables))
missing_metadata <- setdiff(required_metadata, colnames(metadata))

if (length(missing_metadata)) {
    stop("Missing metadata columns: ", paste(missing_metadata, collapse = ", "))
}

metadata[[SAMPLE_COLUMN]] <- trimws(as.character(metadata[[SAMPLE_COLUMN]]))
metadata[[CELL_TYPE_COLUMN]] <- trimws(as.character(metadata[[CELL_TYPE_COLUMN]]))

if (anyNA(metadata[[SAMPLE_COLUMN]]) || any(!nzchar(metadata[[SAMPLE_COLUMN]]))) {
    stop("SAMPLE_COLUMN contains missing or blank values: ", SAMPLE_COLUMN)
}
if (anyNA(metadata[[CELL_TYPE_COLUMN]]) || any(!nzchar(metadata[[CELL_TYPE_COLUMN]]))) {
    stop("CELL_TYPE_COLUMN contains missing or blank values: ", CELL_TYPE_COLUMN)
}

metadata$cell_barcode <- rownames(metadata)

###############################################################################
# JOIN RNA COUNT LAYERS AND EXTRACT RAW COUNTS
###############################################################################

if (inherits(object[["RNA"]], "Assay5")) {
    rna_layers <- SeuratObject::Layers(object[["RNA"]])
    count_layers <- grep("^counts($|\\.)", rna_layers, value = TRUE)

    if (length(count_layers) == 0L) {
        stop("The RNA assay does not contain a raw-count layer.")
    }

    if (length(count_layers) > 1L) {
        cat("Joining ", length(count_layers), " RNA count layers before pseudobulk aggregation.\n", sep = "")
        object <- SeuratObject::JoinLayers(object, assay = "RNA")
        rna_layers <- SeuratObject::Layers(object[["RNA"]])
        count_layers <- grep("^counts($|\\.)", rna_layers, value = TRUE)
    }

    if (length(count_layers) != 1L) {
        stop(
            "Expected exactly one RNA count layer after JoinLayers; found ",
            length(count_layers), ": ", paste(count_layers, collapse = ", ")
        )
    }

    counts_layer <- count_layers[1L]
    counts <- SeuratObject::LayerData(object, assay = "RNA", layer = counts_layer)
} else {
    counts_layer <- "counts"
    counts <- SeuratObject::GetAssayData(object, assay = "RNA", layer = "counts")
}

if (nrow(counts) == 0L || ncol(counts) == 0L) {
    stop("The RNA raw-count matrix is empty.")
}
if (is.null(colnames(counts)) || any(!nzchar(colnames(counts)))) {
    stop("The RNA count matrix does not contain valid cell-barcode column names.")
}
if (!all(colnames(counts) %in% rownames(metadata))) {
    missing_cells <- setdiff(colnames(counts), rownames(metadata))
    stop(
        "Some RNA count-matrix cells are absent from Seurat metadata. Examples: ",
        paste(head(missing_cells, 10L), collapse = ", ")
    )
}

metadata <- metadata[colnames(counts), , drop = FALSE]

###############################################################################
# BUILD AND VALIDATE SAMPLE-LEVEL METADATA
###############################################################################

sample_level_variables <- unique(c(TEST_VARIABLE, design_variables))
validate_sample_level_constant(metadata, SAMPLE_COLUMN, sample_level_variables)

sample_ids_in_order <- unique(as.character(metadata[[SAMPLE_COLUMN]]))
sample_first_indices <- match(sample_ids_in_order, as.character(metadata[[SAMPLE_COLUMN]]))
sample_metadata <- metadata[sample_first_indices, , drop = FALSE]
rownames(sample_metadata) <- sample_ids_in_order

observed_test_values <- trimws(as.character(sample_metadata[[TEST_VARIABLE]]))
if (anyNA(observed_test_values) || any(!nzchar(observed_test_values))) {
    stop("TEST_VARIABLE contains missing or blank sample-level values: ", TEST_VARIABLE)
}

contrast_levels <- resolve_contrast_levels(
    observed_levels = observed_test_values,
    reference_setting = REFERENCE_LEVEL,
    test_setting = TEST_LEVEL,
    variable_name = TEST_VARIABLE
)

REFERENCE_LEVEL <- contrast_levels$reference
TEST_LEVEL <- contrast_levels$test
OBSERVED_TEST_LEVELS <- contrast_levels$observed

sample_metadata[[TEST_VARIABLE]] <- factor(
    trimws(as.character(sample_metadata[[TEST_VARIABLE]])),
    levels = unique(c(REFERENCE_LEVEL, TEST_LEVEL, OBSERVED_TEST_LEVELS))
)
sample_metadata[[TEST_VARIABLE]] <- stats::relevel(
    sample_metadata[[TEST_VARIABLE]],
    ref = REFERENCE_LEVEL
)

cat("Observed ", TEST_VARIABLE, " levels: ", paste(OBSERVED_TEST_LEVELS, collapse = ", "), "\n", sep = "")
cat("Reference level: ", REFERENCE_LEVEL, "\n", sep = "")
cat("Test level: ", TEST_LEVEL, "\n", sep = "")
cat("Contrast: ", TEST_LEVEL, " / ", REFERENCE_LEVEL, "\n\n", sep = "")

write.csv(
    data.frame(
        test_variable = TEST_VARIABLE,
        observed_levels = paste(OBSERVED_TEST_LEVELS, collapse = ";"),
        reference_level = REFERENCE_LEVEL,
        test_level = TEST_LEVEL,
        contrast = paste0(TEST_LEVEL, "/", REFERENCE_LEVEL),
        design_formula = DESIGN_FORMULA,
        stringsAsFactors = FALSE
    ),
    file.path(OUTPUT_DIRECTORY, "pseudobulk_contrast_used.csv"),
    row.names = FALSE
)

###############################################################################
# CELL-TYPE COMPOSITION
###############################################################################

composition_counts <- as.data.frame(
    table(
        sample = metadata[[SAMPLE_COLUMN]],
        cell_type = metadata[[CELL_TYPE_COLUMN]]
    ),
    stringsAsFactors = FALSE
)
colnames(composition_counts) <- c(SAMPLE_COLUMN, CELL_TYPE_COLUMN, "cell_count")
composition_counts <- composition_counts[composition_counts$cell_count > 0L, , drop = FALSE]

composition_totals <- stats::aggregate(
    composition_counts$cell_count,
    by = list(sample = composition_counts[[SAMPLE_COLUMN]]),
    FUN = sum
)
colnames(composition_totals) <- c(SAMPLE_COLUMN, "total_cells")

composition_counts <- merge(
    composition_counts,
    composition_totals,
    by = SAMPLE_COLUMN,
    all.x = TRUE,
    sort = FALSE
)
composition_counts$proportion <- composition_counts$cell_count / composition_counts$total_cells

write.csv(
    composition_counts,
    file.path(OUTPUT_DIRECTORY, "cell_type_composition_by_sample.csv"),
    row.names = FALSE
)

###############################################################################
# PSEUDOBULK edgeR ANALYSIS
###############################################################################

cell_types <- sort(unique(as.character(metadata[[CELL_TYPE_COLUMN]])))
cell_types <- cell_types[!is.na(cell_types) & nzchar(cell_types)]

if (!length(cell_types)) stop("No valid cell types were found in: ", CELL_TYPE_COLUMN)

all_results <- list()
analysis_summary <- list()

for (cell_type in cell_types) {
    cat("\n============================================================\n")
    cat("Analyzing cell type:", cell_type, "\n")

    cell_indices <- which(as.character(metadata[[CELL_TYPE_COLUMN]]) == cell_type)
    cell_metadata <- metadata[cell_indices, , drop = FALSE]
    per_sample_cells <- table(as.character(cell_metadata[[SAMPLE_COLUMN]]))

    eligible_samples <- names(per_sample_cells)[
        per_sample_cells >= MINIMUM_CELLS_PER_SAMPLE_CELLTYPE
    ]

    current_sample_metadata <- sample_metadata[
        rownames(sample_metadata) %in% eligible_samples,
        ,
        drop = FALSE
    ]
    current_sample_metadata <- current_sample_metadata[
        as.character(current_sample_metadata[[TEST_VARIABLE]]) %in%
            c(REFERENCE_LEVEL, TEST_LEVEL),
        ,
        drop = FALSE
    ]

    current_sample_metadata[[TEST_VARIABLE]] <- factor(
        as.character(current_sample_metadata[[TEST_VARIABLE]]),
        levels = c(REFERENCE_LEVEL, TEST_LEVEL)
    )

    group_sizes <- table(current_sample_metadata[[TEST_VARIABLE]])
    reference_samples <- unname(group_sizes[REFERENCE_LEVEL])
    test_samples <- unname(group_sizes[TEST_LEVEL])

    if (is.na(reference_samples)) reference_samples <- 0L
    if (is.na(test_samples)) test_samples <- 0L

    cat("Eligible reference samples:", reference_samples, "\n")
    cat("Eligible test samples:", test_samples, "\n")

    if (reference_samples < MINIMUM_SAMPLES_PER_GROUP ||
        test_samples < MINIMUM_SAMPLES_PER_GROUP) {
        analysis_summary[[cell_type]] <- data.frame(
            cell_type = cell_type,
            status = "SKIPPED_INSUFFICIENT_REPLICATES",
            reference_level = REFERENCE_LEVEL,
            test_level = TEST_LEVEL,
            reference_samples = reference_samples,
            test_samples = test_samples,
            eligible_samples = nrow(current_sample_metadata),
            tested_genes = 0L,
            significant_genes = 0L,
            coefficient = NA_character_,
            stringsAsFactors = FALSE
        )
        next
    }

    selected_cells <- rownames(cell_metadata)[
        as.character(cell_metadata[[SAMPLE_COLUMN]]) %in%
            rownames(current_sample_metadata)
    ]

    if (!length(selected_cells)) {
        analysis_summary[[cell_type]] <- data.frame(
            cell_type = cell_type,
            status = "SKIPPED_NO_SELECTED_CELLS",
            reference_level = REFERENCE_LEVEL,
            test_level = TEST_LEVEL,
            reference_samples = reference_samples,
            test_samples = test_samples,
            eligible_samples = nrow(current_sample_metadata),
            tested_genes = 0L,
            significant_genes = 0L,
            coefficient = NA_character_,
            stringsAsFactors = FALSE
        )
        next
    }

    selected_counts <- counts[, selected_cells, drop = FALSE]
    selected_sample_ids <- factor(
        as.character(metadata[selected_cells, SAMPLE_COLUMN]),
        levels = rownames(current_sample_metadata)
    )

    if (anyNA(selected_sample_ids)) {
        stop("Internal error: selected cells could not be assigned to eligible samples.")
    }

    aggregation_matrix <- Matrix::sparse.model.matrix(
        ~ 0 + selected_sample_ids
    )
    colnames(aggregation_matrix) <- levels(selected_sample_ids)

    pseudobulk_counts <- selected_counts %*% aggregation_matrix
    pseudobulk_counts <- as.matrix(pseudobulk_counts)

    current_sample_metadata <- current_sample_metadata[
        colnames(pseudobulk_counts),
        ,
        drop = FALSE
    ]

    design <- stats::model.matrix(
        design_formula,
        data = current_sample_metadata
    )

    if (qr(design)$rank < ncol(design)) {
        stop(
            "The design matrix is not full rank for cell type '", cell_type,
            "'. Design columns: ", paste(colnames(design), collapse = ", "),
            ". Check whether covariates are confounded or contain only one level."
        )
    }

    expected_coefficient_key <- make.names(
        paste0(TEST_VARIABLE, TEST_LEVEL)
    )
    design_column_keys <- make.names(colnames(design))
    coefficient_indices <- which(design_column_keys == expected_coefficient_key)

    if (length(coefficient_indices) != 1L) {
        stop(
            "Could not identify the main-effect coefficient for ",
            TEST_LEVEL, " versus ", REFERENCE_LEVEL,
            " in cell type '", cell_type, "'. Expected coefficient key: ",
            expected_coefficient_key, ". Design columns: ",
            paste(colnames(design), collapse = ", "),
            ". Use an intercept-based additive design containing ",
            TEST_VARIABLE, " as a main effect."
        )
    }

    coefficient_index <- coefficient_indices[1L]
    coefficient_name <- colnames(design)[coefficient_index]

    dge <- edgeR::DGEList(
        counts = pseudobulk_counts,
        samples = current_sample_metadata
    )

    keep_genes <- edgeR::filterByExpr(dge, design = design)

    if (!any(keep_genes)) {
        analysis_summary[[cell_type]] <- data.frame(
            cell_type = cell_type,
            status = "SKIPPED_NO_GENES_AFTER_FILTERING",
            reference_level = REFERENCE_LEVEL,
            test_level = TEST_LEVEL,
            reference_samples = reference_samples,
            test_samples = test_samples,
            eligible_samples = nrow(current_sample_metadata),
            tested_genes = 0L,
            significant_genes = 0L,
            coefficient = coefficient_name,
            stringsAsFactors = FALSE
        )
        next
    }

    dge <- dge[keep_genes, , keep.lib.sizes = FALSE]
    dge <- edgeR::calcNormFactors(dge)
    dge <- edgeR::estimateDisp(dge, design = design, robust = TRUE)
    fit <- edgeR::glmQLFit(dge, design = design, robust = TRUE)
    qlf_test <- edgeR::glmQLFTest(fit, coef = coefficient_index)

    results <- edgeR::topTags(
        qlf_test,
        n = Inf,
        sort.by = "PValue"
    )$table

    results$gene <- rownames(results)
    results$FDR_percent <- 100 * results$FDR
    results$FC_test_over_reference <- 2^results$logFC
    results$significant <- (
        results$FDR <= FDR_THRESHOLD &
        abs(results$logFC) >= LOG2FC_THRESHOLD
    )
    results$direction <- ifelse(
        results$significant & results$logFC > 0,
        "UP_IN_TEST",
        ifelse(
            results$significant & results$logFC < 0,
            "DOWN_IN_TEST",
            "NOT_SIGNIFICANT"
        )
    )
    results$cell_type <- cell_type
    results$reference_level <- REFERENCE_LEVEL
    results$test_level <- TEST_LEVEL
    results$contrast <- paste0(TEST_LEVEL, "/", REFERENCE_LEVEL)
    results$coefficient <- coefficient_name

    preferred_columns <- c(
        "gene",
        "cell_type",
        "contrast",
        "reference_level",
        "test_level",
        "logFC",
        "FC_test_over_reference",
        "logCPM",
        "F",
        "PValue",
        "FDR",
        "FDR_percent",
        "significant",
        "direction",
        "coefficient"
    )
    preferred_columns <- preferred_columns[
        preferred_columns %in% colnames(results)
    ]
    remaining_columns <- setdiff(colnames(results), preferred_columns)
    results <- results[, c(preferred_columns, remaining_columns), drop = FALSE]

    safe_name <- sanitize_filename(cell_type)

    write.csv(
        results,
        file.path(OUTPUT_DIRECTORY, paste0("DE_", safe_name, ".csv")),
        row.names = FALSE
    )
    write.csv(
        pseudobulk_counts,
        file.path(OUTPUT_DIRECTORY, paste0("Pseudobulk_counts_", safe_name, ".csv")),
        row.names = TRUE
    )

    volcano <- ggplot2::ggplot(
        results,
        ggplot2::aes(
            x = logFC,
            y = -log10(pmax(FDR, .Machine$double.xmin)),
            color = direction
        )
    ) +
        ggplot2::geom_point(size = 1.2, alpha = 0.7) +
        ggplot2::geom_vline(
            xintercept = c(-LOG2FC_THRESHOLD, LOG2FC_THRESHOLD),
            linetype = 2
        ) +
        ggplot2::geom_hline(
            yintercept = -log10(FDR_THRESHOLD),
            linetype = 2
        ) +
        ggplot2::theme_bw(base_size = 11) +
        ggplot2::labs(
            title = paste("Pseudobulk DE:", cell_type),
            subtitle = paste(TEST_LEVEL, "versus", REFERENCE_LEVEL),
            x = paste0(
                "log2 fold change (",
                TEST_LEVEL, " / ", REFERENCE_LEVEL, ")"
            ),
            y = "-log10(FDR)",
            color = "Result"
        )

    ggplot2::ggsave(
        file.path(OUTPUT_DIRECTORY, paste0("Volcano_", safe_name, ".png")),
        volcano,
        width = 8,
        height = 7,
        dpi = 300
    )
    ggplot2::ggsave(
        file.path(OUTPUT_DIRECTORY, paste0("Volcano_", safe_name, ".pdf")),
        volcano,
        width = 8,
        height = 7
    )

    all_results[[cell_type]] <- results
    analysis_summary[[cell_type]] <- data.frame(
        cell_type = cell_type,
        status = "ANALYZED",
        reference_level = REFERENCE_LEVEL,
        test_level = TEST_LEVEL,
        reference_samples = reference_samples,
        test_samples = test_samples,
        eligible_samples = nrow(current_sample_metadata),
        tested_genes = nrow(results),
        significant_genes = sum(results$significant, na.rm = TRUE),
        coefficient = coefficient_name,
        stringsAsFactors = FALSE
    )
}

###############################################################################
# COMBINED OUTPUTS AND SUMMARY
###############################################################################

if (length(all_results)) {
    combined_results <- do.call(rbind, all_results)
    rownames(combined_results) <- NULL

    write.csv(
        combined_results,
        file.path(OUTPUT_DIRECTORY, "DE_all_cell_types_combined.csv"),
        row.names = FALSE
    )
}

if (length(analysis_summary)) {
    summary_table <- do.call(rbind, analysis_summary)
    rownames(summary_table) <- NULL
} else {
    summary_table <- data.frame(
        cell_type = character(0),
        status = character(0),
        reference_level = character(0),
        test_level = character(0),
        reference_samples = integer(0),
        test_samples = integer(0),
        eligible_samples = integer(0),
        tested_genes = integer(0),
        significant_genes = integer(0),
        coefficient = character(0),
        stringsAsFactors = FALSE
    )
}

write.csv(
    summary_table,
    file.path(OUTPUT_DIRECTORY, "pseudobulk_analysis_summary.csv"),
    row.names = FALSE
)

pipeline_minutes <- as.numeric(
    difftime(Sys.time(), PIPELINE_START_TIME, units = "mins")
)

write.csv(
    data.frame(
        input_RDS = basename(rds_files[1L]),
        RNA_counts_layer = counts_layer,
        sample_column = SAMPLE_COLUMN,
        cell_type_column = CELL_TYPE_COLUMN,
        test_variable = TEST_VARIABLE,
        observed_test_levels = paste(OBSERVED_TEST_LEVELS, collapse = ";"),
        reference_level = REFERENCE_LEVEL,
        test_level = TEST_LEVEL,
        contrast = paste0(TEST_LEVEL, "/", REFERENCE_LEVEL),
        design_formula = DESIGN_FORMULA,
        minimum_cells_per_sample_celltype = MINIMUM_CELLS_PER_SAMPLE_CELLTYPE,
        minimum_samples_per_group = MINIMUM_SAMPLES_PER_GROUP,
        FDR_threshold = FDR_THRESHOLD,
        minimum_real_FC = MINIMUM_REAL_FC,
        log2FC_threshold = LOG2FC_THRESHOLD,
        analyzed_cell_types = sum(summary_table$status == "ANALYZED"),
        skipped_cell_types = sum(summary_table$status != "ANALYZED"),
        total_pipeline_minutes = pipeline_minutes,
        stringsAsFactors = FALSE
    ),
    file.path(OUTPUT_DIRECTORY, "pseudobulk_run_summary.csv"),
    row.names = FALSE
)

save_session_information()

cat("\nSample-aware pseudobulk differential-expression analysis completed.\n")
cat("Observed ", TEST_VARIABLE, " levels: ", paste(OBSERVED_TEST_LEVELS, collapse = ", "), "\n", sep = "")
cat("Contrast used: ", TEST_LEVEL, " / ", REFERENCE_LEVEL, "\n", sep = "")
cat("Analyzed cell types:", sum(summary_table$status == "ANALYZED"), "\n")
cat("Skipped cell types:", sum(summary_table$status != "ANALYZED"), "\n")
cat("Total pipeline minutes:", pipeline_minutes, "\n")
cat("Finished:", format(Sys.time()), "\n")
