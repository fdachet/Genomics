

options(stringsAsFactors = FALSE)

script8_parse_cli <- function(args = commandArgs(trailingOnly = TRUE)) {
    values <- list()
    index <- 1L
    while (index <= length(args)) {
        token <- args[[index]]
        if (!startsWith(token, "--")) stop("Unexpected argument: ", token, call. = FALSE)
        token <- substring(token, 3L)
        if (grepl("=", token, fixed = TRUE)) {
            parts <- strsplit(token, "=", fixed = TRUE)[[1L]]
            name <- parts[[1L]]
            value <- paste(parts[-1L], collapse = "=")
        } else {
            name <- token
            if (index < length(args) && !startsWith(args[[index + 1L]], "--")) {
                index <- index + 1L
                value <- args[[index]]
            } else {
                value <- TRUE
            }
        }
        name <- gsub("-", "_", name, fixed = TRUE)
        if (!is.null(values[[name]])) stop("Repeated option: --", gsub("_", "-", name), call. = FALSE)
        values[[name]] <- value
        index <- index + 1L
    }
    values
}

SCRIPT8_CLI <- script8_parse_cli()

if (isTRUE(SCRIPT8_CLI$help)) {
    cat(
        "Script 08 - Edit a Seurat gene-expression matrix\n\n",
        "GUI:\n",
        "  source('8.Edit_Gene_Expression_Matrix.R')\n\n",
        "CLI export:\n",
        "  Rscript 8.Edit_Gene_Expression_Matrix.R --cli --action export --input-rds FILE --positions-file tissue_positions.csv --assay Spatial --layer data --genes GENE1,GENE2 --matrix-file GRID_FOLDER\n\n",
        "CLI import:\n",
        "  Rscript 8.Edit_Gene_Expression_Matrix.R --cli --action import --input-rds FILE --positions-file tissue_positions.csv --assay Spatial --layer data --matrix-file EDITED_GRID_FOLDER --results-dir Results/Sample_01\n\n",
        "Options:\n",
        "  --gui\n  --cli\n  --action export|import\n  --input-rds FILE\n",
        "  --assay NAME\n  --layer NAME\n  --genes comma-separated Feature_Genes\n",
        "  --positions-file tissue_positions.csv\n  --matrix-file GRID_FOLDER_OR_FILE\n  --results-dir SAMPLE_RESULTS_FOLDER\n  --output-rds FILE.rds\n  --image-scale auto|hires|lowres\n",
        sep = ""
    )
    quit(save = "no", status = 0L, runLast = FALSE)
}

script8_require_packages <- function() {
    required <- c("Seurat", "SeuratObject", "Matrix", "ggplot2", "patchwork")
    missing <- required[!vapply(required, requireNamespace, logical(1), quietly = TRUE)]
    if (length(missing)) stop("Missing required R package(s): ", paste(missing, collapse = ", "), call. = FALSE)
}

script8_read_seurat <- function(path) {
    path <- trimws(as.character(path)[1L])
    if (!nzchar(path) || !file.exists(path)) stop("Select an existing Seurat RDS file.", call. = FALSE)
    object <- readRDS(path)
    if (!inherits(object, "Seurat")) stop("The selected RDS does not contain a Seurat object.", call. = FALSE)
    object
}

script8_assays <- function(object) {
    assays <- SeuratObject::Assays(object)
    if (!length(assays)) stop("The Seurat object contains no assays.", call. = FALSE)
    assays
}

script8_layers <- function(object, assay) {
    if (!(assay %in% script8_assays(object))) stop("Assay not found in Seurat object: ", assay, call. = FALSE)
    layers <- SeuratObject::Layers(object, assay = assay)
    if (!length(layers)) stop("Assay '", assay, "' contains no expression layers.", call. = FALSE)
    layers
}

script8_get_layer <- function(object, assay, layer) {
    if (!(layer %in% script8_layers(object, assay))) stop("Layer '", layer, "' is not present in assay '", assay, "'.", call. = FALSE)
    matrix <- SeuratObject::LayerData(object, assay = assay, layer = layer)
    if (is.null(rownames(matrix)) || is.null(colnames(matrix))) stop("The selected layer has no Feature_Gene/spot names.", call. = FALSE)
    matrix
}

script8_safe_name <- function(value) {
    value <- gsub("[^A-Za-z0-9._-]+", "_", as.character(value)[1L])
    gsub("^_+|_+$", "", value)
}

script8_max_value_tag <- function(values) {
    values <- as.numeric(values)
    values <- values[is.finite(values)]
    if (!length(values)) return("NA")
    maximum <- max(values)
    if (abs(maximum - round(maximum)) < 1e-12) {
        formatted <- formatC(round(maximum), format = "f", digits = 0)
    } else {
        formatted <- formatC(round(maximum, 2), format = "f", digits = 2)
    }
    script8_safe_name(formatted)
}

script8_read_tissue_positions <- function(path, object_spots) {
    path <- trimws(as.character(path)[1L])
    if (!nzchar(path) || !file.exists(path)) stop("Select the tissue_positions CSV used to create this Seurat object.", call. = FALSE)
    first_line <- readLines(path, n = 1L, warn = FALSE)
    has_header <- length(first_line) && grepl("barcode|array_row|array_col", first_line, ignore.case = TRUE)
    positions <- read.csv(path, header = has_header, check.names = FALSE, stringsAsFactors = FALSE)
    if (!has_header) {
        if (ncol(positions) < 6L) stop("Headerless tissue_positions file must contain six columns.", call. = FALSE)
        colnames(positions)[1:6] <- c("barcode", "in_tissue", "array_row", "array_col", "pxl_row_in_fullres", "pxl_col_in_fullres")
    } else {
        normalized <- gsub("[^a-z0-9]+", "", tolower(colnames(positions)))
        required <- c(barcode = "barcode", in_tissue = "intissue", array_row = "arrayrow", array_col = "arraycol")
        matched <- match(required, normalized)
        if (anyNA(matched)) stop("Tissue positions file requires barcode, in_tissue, array_row and array_col columns.", call. = FALSE)
        colnames(positions)[matched] <- names(required)
    }

    positions$barcode <- trimws(as.character(positions$barcode))
    positions$array_row <- suppressWarnings(as.integer(positions$array_row))
    positions$array_col <- suppressWarnings(as.integer(positions$array_col))
    if (anyNA(positions$array_row) || anyNA(positions$array_col)) stop("array_row and array_col must contain integers.", call. = FALSE)
    if (anyDuplicated(positions$barcode)) stop("Tissue positions file contains duplicated spot barcodes.", call. = FALSE)

    object_rows <- match(object_spots, positions$barcode)
    if (anyNA(object_rows)) {
        missing <- object_spots[is.na(object_rows)]
        stop("The tissue positions file is not from this Seurat object. Missing object spots: ", length(missing), ". Example: ", paste(head(missing, 5L), collapse = ", "), call. = FALSE)
    }
    object_positions <- positions[object_rows, c("barcode", "array_row", "array_col"), drop = FALSE]
    if (anyDuplicated(paste(object_positions$array_row, object_positions$array_col, sep = ":"))) stop("Multiple object spots share the same array_row/array_col position.", call. = FALSE)
    list(
        map = object_positions,
        rows = seq.int(min(positions$array_row), max(positions$array_row)),
        columns = seq.int(min(positions$array_col), max(positions$array_col)),
        path = normalizePath(path, winslash = "/", mustWork = TRUE)
    )
}

script8_grid_header <- function(gene, assay, layer) {
    paste0(
        "Array_Row|Feature_Gene=", utils::URLencode(gene, reserved = TRUE),
        "|Assay=", utils::URLencode(assay, reserved = TRUE),
        "|Layer=", utils::URLencode(layer, reserved = TRUE)
    )
}

script8_parse_grid_header <- function(header) {
    fields <- strsplit(as.character(header)[1L], "|", fixed = TRUE)[[1L]]
    if (!length(fields) || !identical(fields[[1L]], "Array_Row")) stop("This is not a Step 08 Seurat-grid TSV: invalid first-column header.", call. = FALSE)
    values <- setNames(sub("^[^=]*=", "", fields[-1L]), sub("=.*$", "", fields[-1L]))
    required <- c("Feature_Gene", "Assay", "Layer")
    if (!all(required %in% names(values))) stop("Seurat-grid header is missing Feature_Gene, Assay or Layer information.", call. = FALSE)
    lapply(values[required], utils::URLdecode)
}

script8_export_matrix <- function(object, assay, layer, genes, output_file, positions_file) {
    expression <- script8_get_layer(object, assay, layer)
    genes <- unique(trimws(as.character(genes)))
    genes <- genes[nzchar(genes)]
    if (!length(genes)) stop("Select at least one Feature_Gene to export.", call. = FALSE)
    missing_genes <- setdiff(genes, rownames(expression))
    if (length(missing_genes)) stop("Feature_Gene(s) absent from the selected layer: ", paste(head(missing_genes, 20L), collapse = ", "), call. = FALSE)

    spots <- colnames(expression)
    positions <- script8_read_tissue_positions(positions_file, spots)
    output_directory <- normalizePath(output_file, winslash = "/", mustWork = FALSE)
    dir.create(output_directory, recursive = TRUE, showWarnings = FALSE)
    output_files <- character(length(genes))

    row_indices <- match(positions$map$array_row, positions$rows)
    column_indices <- match(positions$map$array_col, positions$columns)
    for (gene_index in seq_along(genes)) {
        gene <- genes[[gene_index]]
        grid <- matrix(
            NA_real_, nrow = length(positions$rows), ncol = length(positions$columns),
            dimnames = list(as.character(positions$rows), paste0("Array_Column_", positions$columns))
        )
        grid[cbind(row_indices, column_indices)] <- as.numeric(expression[gene, spots])
        export_table <- data.frame(Array_Row = positions$rows, grid, check.names = FALSE)
        colnames(export_table)[1L] <- script8_grid_header(gene, assay, layer)
        maximum_tag <- script8_max_value_tag(expression[gene, spots])
        output_path <- file.path(
            output_directory,
            paste0(
                sprintf("%03d", gene_index), "_", script8_safe_name(gene),
                "_Max", maximum_tag, "_", script8_safe_name(assay), "_",
                script8_safe_name(layer), "_SeuratGrid.tsv"
            )
        )
        write.table(export_table, output_path, sep = "\t", quote = FALSE, row.names = FALSE, col.names = TRUE, na = "")
        output_files[[gene_index]] <- normalizePath(output_path, winslash = "/", mustWork = TRUE)
    }
    output_files
}

script8_read_modified_matrix <- function(matrix_file, expression, object, assay, layer, positions_file) {
    if (!file.exists(matrix_file)) stop("Modified tabulated matrix does not exist: ", matrix_file, call. = FALSE)
    edited <- read.delim(matrix_file, sep = "\t", header = TRUE, check.names = FALSE, stringsAsFactors = FALSE, quote = "", comment.char = "")
    if (nrow(edited) < 1L || ncol(edited) < 2L) stop("Seurat-grid TSV must contain array rows and array-column expression cells.", call. = FALSE)
    metadata <- script8_parse_grid_header(colnames(edited)[1L])
    gene <- metadata$Feature_Gene
    if (!identical(metadata$Assay, assay) || !identical(metadata$Layer, layer)) {
        stop("Grid was exported from ", metadata$Assay, "/", metadata$Layer, " but the GUI currently selects ", assay, "/", layer, ".", call. = FALSE)
    }
    if (!(gene %in% rownames(expression))) stop("Feature_Gene from grid is absent from selected layer: ", gene, call. = FALSE)

    positions <- script8_read_tissue_positions(positions_file, colnames(expression))
    array_rows <- suppressWarnings(as.integer(edited[[1L]]))
    if (anyNA(array_rows) || anyDuplicated(array_rows)) stop("The first TSV column must preserve unique integer array rows.", call. = FALSE)
    array_columns <- suppressWarnings(as.integer(sub("^Array_Column_", "", colnames(edited)[-1L])))
    if (anyNA(array_columns) || anyDuplicated(array_columns)) stop("Expression headers must remain named Array_Column_<number>.", call. = FALSE)
    if (!identical(array_rows, positions$rows) || !identical(array_columns, positions$columns)) stop("Array row/column headers were changed. Preserve the exported Seurat grid dimensions.", call. = FALSE)

    character_grid <- as.matrix(edited[, -1L, drop = FALSE])
    row_indices <- match(positions$map$array_row, array_rows)
    column_indices <- match(positions$map$array_col, array_columns)
    spot_characters <- character_grid[cbind(row_indices, column_indices)]
    spot_values <- suppressWarnings(as.numeric(spot_characters))
    if (anyNA(spot_values) || any(!is.finite(spot_values))) stop("Every grid cell corresponding to a Seurat spot must contain a finite numeric expression value.", call. = FALSE)

    valid_cells <- matrix(FALSE, nrow = nrow(character_grid), ncol = ncol(character_grid))
    valid_cells[cbind(row_indices, column_indices)] <- TRUE
    outside_values <- trimws(character_grid[!valid_cells])
    if (any(!is.na(outside_values) & nzchar(outside_values))) stop("Expression was entered outside the spots present in the Seurat object. Leave non-spot grid cells blank.", call. = FALSE)
    list(gene = gene, spots = positions$map$barcode, values = spot_values, file = matrix_file)
}

script8_import_matrix <- function(object, assay, layer, matrix_file, positions_file) {
    expression <- script8_get_layer(object, assay, layer)
    matrix_files <- if (dir.exists(matrix_file)) {

        list.files(matrix_file, pattern = "_(SeuratGrid|SpatialGrid)\\.tsv$", full.names = TRUE, ignore.case = TRUE)
    } else {
        matrix_file
    }
    matrix_files <- matrix_files[file.exists(matrix_files)]
    if (!length(matrix_files)) stop("No edited *_SeuratGrid.tsv files were found.", call. = FALSE)
    imported <- lapply(matrix_files, script8_read_modified_matrix, expression = expression, object = object, assay = assay, layer = layer, positions_file = positions_file)
    genes <- vapply(imported, `[[`, character(1), "gene")
    if (anyDuplicated(genes)) stop("More than one Seurat-grid file was found for the same Feature_Gene: ", paste(unique(genes[duplicated(genes)]), collapse = ", "), call. = FALSE)
    for (item in imported) {
        if (grepl("^counts($|[.])", layer, ignore.case = TRUE)) {
            if (any(item$values < 0)) stop("A raw counts layer cannot contain negative values.", call. = FALSE)
            if (any(abs(item$values - round(item$values)) > 1e-8)) stop("A raw counts layer must contain whole Count_RNAs values.", call. = FALSE)
        }
        expression[item$gene, item$spots] <- item$values
    }
    object <- SeuratObject::SetAssayData(object, assay = assay, layer = layer, new.data = expression)
    if (grepl("^counts($|[.])", layer, ignore.case = TRUE)) {
        counts <- script8_get_layer(object, assay, layer)
        count_values <- Matrix::colSums(counts)
        feature_values <- Matrix::colSums(counts > 0)
        names(count_values) <- colnames(counts)
        names(feature_values) <- colnames(counts)
        object[[paste0("nCount_", assay)]] <- count_values[colnames(object)]
        object[[paste0("nFeature_", assay)]] <- feature_values[colnames(object)]
        if (identical(assay, "Spatial")) {
            object[["Count_RNAs"]] <- count_values[colnames(object)]
            object[["Feature_Genes"]] <- feature_values[colnames(object)]
            mitochondrial_features <- grep("^(MT-|mt-)", rownames(counts), value = TRUE)
            mitochondrial_percent <- setNames(rep(NA_real_, ncol(counts)), colnames(counts))
            nonzero_total <- count_values > 0
            if (length(mitochondrial_features)) mitochondrial_percent[nonzero_total] <- 100 * Matrix::colSums(counts[mitochondrial_features, , drop = FALSE])[nonzero_total] / count_values[nonzero_total]
            object[["percent.mt"]] <- mitochondrial_percent[colnames(object)]
            object[["Mitochondrial_Percent"]] <- mitochondrial_percent[colnames(object)]
        }
    }
    list(object = object, genes = genes, files = matrix_files)
}

script8_resolve_image_scale <- function(object, requested = "auto") {
    requested <- tolower(trimws(as.character(requested)[1L]))
    if (requested %in% c("hires", "lowres")) return(requested)
    if (!identical(requested, "auto")) stop("Image scale must be auto, hires, or lowres.", call. = FALSE)
    image_name <- SeuratObject::Images(object)[1L]
    image_object <- object[[image_name]]
    scale_factors <- tryCatch(methods::slot(image_object, "scale.factors"), error = function(e) NULL)
    image_array <- tryCatch(methods::slot(image_object, "image"), error = function(e) NULL)
    scale_value <- function(name) {
        value <- tryCatch({
            if (isS4(scale_factors) && name %in% methods::slotNames(scale_factors)) methods::slot(scale_factors, name) else scale_factors[[name]]
        }, error = function(e) NA_real_)
        suppressWarnings(as.numeric(value)[1L])
    }
    factors <- c(hires = scale_value("hires"), lowres = scale_value("lowres"))
    available <- names(factors)[is.finite(factors) & factors > 0]
    if (length(available) == 1L) return(available)
    if (length(available) == 2L && !is.null(image_array) && length(dim(image_array)) >= 2L) {
        coordinates <- tryCatch(SeuratObject::GetTissueCoordinates(image_object), error = function(e) NULL)
        if (!is.null(coordinates)) {
            numeric_columns <- which(vapply(coordinates, is.numeric, logical(1)))
            if (length(numeric_columns) >= 2L) {
                coordinate_extent <- sort(vapply(coordinates[numeric_columns[1:2]], function(x) diff(range(x, na.rm = TRUE)), numeric(1)))
                image_extent <- sort(as.numeric(dim(image_array)[1:2]))
                errors <- vapply(factors, function(factor_value) sum(abs(log(pmax(coordinate_extent * factor_value, 1) / pmax(image_extent, 1)))), numeric(1))
                return(names(which.min(errors)))
            }
        }
    }
    stop("Auto could not determine whether the stored tissue image is hires or lowres. Select hires or lowres explicitly in the Tissue image scale box.", call. = FALSE)
}

script8_plot_spatial_genes <- function(object, assay, layer, genes, results_dir, plot_stage = c("Before_Modification", "After_Modification"), display = TRUE, image_scale = "auto") {
    plot_stage <- match.arg(plot_stage)
    genes <- unique(as.character(genes))
    genes <- genes[nzchar(genes)]
    if (!length(genes)) stop("Select or import at least one Feature_Gene before creating spatial maps.", call. = FALSE)
    missing <- setdiff(genes, rownames(script8_get_layer(object, assay, layer)))
    if (length(missing)) stop("Feature_Gene(s) unavailable for plotting: ", paste(missing, collapse = ", "), call. = FALSE)
    if (!length(SeuratObject::Images(object))) stop("The Seurat object contains no tissue image.", call. = FALSE)
    resolved_image_scale <- script8_resolve_image_scale(object, image_scale)

    plot_object <- object
    SeuratObject::DefaultAssay(plot_object) <- assay
    output_directory <- file.path(results_dir, "8_Edit_Gene_Expression_Matrix", "Gene_Spatial_Maps", plot_stage)
    dir.create(output_directory, recursive = TRUE, showWarnings = FALSE)
    plot_files <- character(length(genes))
    individual_plots <- vector("list", length(genes))
    for (index in seq_along(genes)) {
        gene <- genes[[index]]
        gene_plot <- suppressMessages(suppressWarnings(
            Seurat::SpatialFeaturePlot(
                plot_object, features = gene, images = SeuratObject::Images(plot_object),
                slot = layer, image.scale = resolved_image_scale, alpha = c(0.15, 1),
                min.cutoff = NA, max.cutoff = NA
            ) & ggplot2::scale_fill_gradient(low = "#F7F7F7", high = "#D7191C")
        ))
        gene_plot <- gene_plot + patchwork::plot_annotation(title = gsub("_", " ", plot_stage, fixed = TRUE))
        output_path <- file.path(
            output_directory,
            paste0(script8_safe_name(gene), "_", plot_stage, "_", script8_safe_name(assay), "_", script8_safe_name(layer), ".png")
        )
        ggplot2::ggsave(output_path, gene_plot, width = 10, height = 9, dpi = 300)
        plot_files[[index]] <- normalizePath(output_path, winslash = "/", mustWork = TRUE)
        individual_plots[[index]] <- gene_plot
    }
    if (isTRUE(display)) {
        preview <- if (length(individual_plots) == 1L) individual_plots[[1L]] else patchwork::wrap_plots(individual_plots, ncol = min(3L, length(individual_plots)))
        try({ grDevices::dev.new(width = min(16, 6 * min(3L, length(individual_plots))), height = min(12, 6 * ceiling(length(individual_plots) / 3))); print(preview) }, silent = TRUE)
    }
    plot_files
}

script8_default_output_rds <- function(input_rds, results_dir, assay, layer) {
    results_dir <- normalizePath(results_dir, winslash = "/", mustWork = TRUE)
    rds_dir <- file.path(results_dir, "Seurat_RDS")
    dir.create(rds_dir, recursive = TRUE, showWarnings = FALSE)
    sample_name <- script8_safe_name(basename(results_dir))
    input_base <- tools::file_path_sans_ext(basename(input_rds))
    inherited <- if (grepl("_S[0-9]{2}_", input_base)) sub("^.*_S[0-9]{2}_", "", input_base) else script8_safe_name(input_base)
    base <- file.path(rds_dir, paste0(sample_name, "_S08_", inherited, "_ExprEdited_", script8_safe_name(assay), "_", script8_safe_name(layer), ".rds"))
    if (!file.exists(base)) return(base)
    version <- 2L
    repeat {
        candidate <- sub("\\.rds$", paste0("_v", version, ".rds"), base, ignore.case = TRUE)
        if (!file.exists(candidate)) return(candidate)
        version <- version + 1L
    }
}

script8_save_modified_object <- function(object, input_rds, results_dir, assay, layer, output_rds = "") {
    if (!nzchar(trimws(output_rds))) output_rds <- script8_default_output_rds(input_rds, results_dir, assay, layer)
    output_rds <- normalizePath(output_rds, winslash = "/", mustWork = FALSE)
    if (identical(tolower(normalizePath(input_rds, winslash = "/", mustWork = TRUE)), tolower(output_rds))) {
        stop("The modified object must be saved as a new RDS; overwriting the input RDS is not allowed.", call. = FALSE)
    }
    dir.create(dirname(output_rds), recursive = TRUE, showWarnings = FALSE)
    saveRDS(object, output_rds, compress = FALSE)
    output_rds
}

script8_require_packages()

if (isTRUE(SCRIPT8_CLI$cli)) {
    action <- tolower(trimws(as.character(SCRIPT8_CLI$action)[1L]))
    input_rds <- as.character(SCRIPT8_CLI$input_rds)[1L]
    assay <- as.character(SCRIPT8_CLI$assay)[1L]
    layer <- as.character(SCRIPT8_CLI$layer)[1L]
    matrix_file <- as.character(SCRIPT8_CLI$matrix_file)[1L]
    positions_file <- as.character(SCRIPT8_CLI$positions_file)[1L]
    image_scale <- if (is.null(SCRIPT8_CLI$image_scale)) "auto" else tolower(trimws(as.character(SCRIPT8_CLI$image_scale)[1L]))
    if (!image_scale %in% c("auto", "hires", "lowres")) stop("--image-scale must be auto, hires, or lowres.", call. = FALSE)
    object <- script8_read_seurat(input_rds)

    if (identical(action, "export")) {
        genes <- trimws(strsplit(as.character(SCRIPT8_CLI$genes)[1L], ",", fixed = TRUE)[[1L]])
        saved <- script8_export_matrix(object, assay, layer, genes, matrix_file, positions_file)
        results_dir <- if (is.null(SCRIPT8_CLI$results_dir)) "" else as.character(SCRIPT8_CLI$results_dir)[1L]
        before_plots <- if (nzchar(results_dir) && dir.exists(results_dir)) {
            script8_plot_spatial_genes(object, assay, layer, genes, results_dir, plot_stage = "Before_Modification", display = FALSE, image_scale = image_scale)
        } else character(0)
        cat("Seurat expression grid(s) exported:\n", paste(saved, collapse = "\n"), "\n*********** FINISHED ***********\n", sep = "")
    } else if (identical(action, "import")) {
        results_dir <- as.character(SCRIPT8_CLI$results_dir)[1L]
        output_rds <- if (is.null(SCRIPT8_CLI$output_rds)) "" else as.character(SCRIPT8_CLI$output_rds)[1L]
        imported <- script8_import_matrix(object, assay, layer, matrix_file, positions_file)
        object <- imported$object
        saved <- script8_save_modified_object(object, input_rds, results_dir, assay, layer, output_rds)
        plot_files <- script8_plot_spatial_genes(object, assay, layer, imported$genes, results_dir, plot_stage = "After_Modification", display = FALSE, image_scale = image_scale)
        cat("Modified Seurat RDS saved: ", saved, "\n*********** FINISHED ***********\n", sep = "")
    } else {
        stop("--action must be export or import.", call. = FALSE)
    }
    quit(save = "no", status = 0L, runLast = FALSE)
}

if (!requireNamespace("tcltk", quietly = TRUE)) stop("The R tcltk package is required for the graphical interface.", call. = FALSE)
if (!isTRUE(tryCatch({ tcltk::tclRequire("Tk"); TRUE }, error = function(e) FALSE))) stop("Tcl/Tk could not initialize.", call. = FALSE)

state <- new.env(parent = emptyenv())
state$object <- NULL
state$original_object <- NULL
state$input_rds <- ""
state$all_features <- character(0)
state$visible_features <- character(0)
state$selected_genes <- character(0)
state$updating_list <- FALSE
state$last_imported_genes <- character(0)
state$available_assays <- character(0)
state$available_layers <- character(0)
state$updating_matrix_selectors <- FALSE

results_var <- tcltk::tclVar("")
input_rds_var <- tcltk::tclVar("")
positions_file_var <- tcltk::tclVar("")
assay_var <- tcltk::tclVar("")
layer_var <- tcltk::tclVar("")
image_scale_var <- tcltk::tclVar("auto")
search_var <- tcltk::tclVar("")
selected_status_var <- tcltk::tclVar("No Seurat object loaded.")
matrix_summary_var <- tcltk::tclVar("No expression matrix loaded. Select an input Seurat RDS in FILES.")
export_file_var <- tcltk::tclVar("")
modified_file_var <- tcltk::tclVar("")
status_var <- tcltk::tclVar("Select a sample results folder and a Seurat RDS, then click LOAD SEURAT OBJECT.")

window <- tcltk::tktoplevel(background = "#F4F7FB")
tcltk::tkwm.title(window, "Script 08 - Edit Seurat Gene Expression")
tcltk::tkwm.geometry(window, "1120x900")
tcltk::tkwm.minsize(window, 900L, 720L)
tcltk::tkgrid.columnconfigure(window, 0L, weight = 1L)
tcltk::tkgrid.rowconfigure(window, 1L, weight = 1L)

header <- tcltk::tkframe(window, background = "#AD1457", padx = 18L, pady = 10L)
tcltk::tkgrid(header, row = 0L, column = 0L, sticky = "ew")
tcltk::tkpack(tcltk::tklabel(header, text = "SCRIPT 08 - EDIT SEURAT GENE EXPRESSION", background = "#AD1457", foreground = "white", font = "TkHeadingFont", anchor = "w"), fill = "x")
tcltk::tkpack(tcltk::tklabel(header, text = "Export each selected Feature_Gene as a two-dimensional Visium array-row x array-column grid, create artificial expression in Excel, write it back to Seurat, and display the modified gene on the tissue.", background = "#AD1457", foreground = "white", anchor = "w"), fill = "x", pady = c(3L, 0L))

show_assay_layer_guide <- function() {
    guide_text <- paste(
        "WHAT THE EXPRESSION ASSAYS MEAN",
        "",
        "Spatial",
        "The assay containing the original Visium spatial-transcriptomics expression measurements.",
        "  counts = raw integer Count_RNAs for each Feature_Gene in each spot.",
        "  data   = normalized spatial expression derived from those raw counts.",
        "Spatial/data is generally the main layer for spatial expression maps and is the default used by Step 7.",
        "",
        "SCT",
        "The assay created by SCTransform. It adjusts expression for sequencing-depth and technical differences.",
        "It is used for PCA, clustering, dimensionality reduction, spatial-gene selection, and other downstream analyses.",
        "It is not the original raw Visium measurement.",
        "",
        "WHAT THE EXPRESSION MATRICES / LAYERS MEAN",
        "",
        "counts",
        "Raw integer RNA counts inside Seurat. Use this for original unnormalized measurements.",
        "",
        "data",
        "Normalized expression values. Use this for most expression visualizations and pathway-expression analyses.",
        "",
        "scale.data",
        "Centered and scaled expression, approximately centered around zero. It is used for PCA, clustering and the Step 5 spatial-selection algorithms. It is not a raw expression quantity and may contain only variable Feature_Genes.",
        "",
        "WHAT WILL BE MODIFIED BY THE EXCEL METHOD",
        "  Spatial/data: modifies normalized spatial expression used by many gene-expression maps.",
        "  Spatial/counts: modifies raw integer RNA counts only.",
        "  SCT/data: modifies SCT-normalized expression.",
        "  SCT/scale.data: modifies scaled values used by PCA, clustering and Step 5 spatial ranking.",
        "",
        "WHAT TO SELECT FOR YOUR V7 PIPELINE",
        "",
        "Step 4 clustering / UMAP / spatial cluster groups:",
        "  Select SCT + scale.data if the intention is to change the values used to calculate PCA and clustering.",
        "  The cluster maps do not directly display gene-expression values. Step 4 must be rerun for spots, UMAP positions or clusters to change.",
        "  Step 4 marker-gene testing uses normalized SCT expression; select SCT + data when the intention is specifically to alter normalized expression used by marker comparisons.",
        "",
        "Step 5 spatially variable Feature_Gene selection:",
        "  Select SCT + scale.data to change the values used by Moran's I and mark variogram ranking.",
        "  Select SCT + data to change the expression intensities shown in the top-gene spatial maps.",
        "  Step 5 must be rerun to recalculate rankings, plots and pathway scores.",
        "",
        "Step 7 pathway-footprint analysis and maps:",
        "  Select Spatial + data. This is the Step 7 default and provides normalized expression with broad gene coverage.",
        "  Step 7 must be rerun to recalculate pathway scores, significance, rankings and spatial pathway maps.",
        "",
        "MOST BIOLOGICALLY CONSISTENT WORKFLOW",
        "If correcting the underlying measured expression, edit Spatial + counts, then rerun Step 3 normalization and the required later steps. Directly editing data or scale.data changes only that derived layer and can make counts, normalized expression, scaled expression, PCA and clusters inconsistent with one another.",
        "",
        "A Step 08 output does not retroactively change PNG files or tables already produced by Steps 4, 5 or 7. The modified RDS must be supplied to the relevant step and that analysis must be run again.",
        "",
        "STEP 08 EXCEL FORMAT",
        "Each selected Feature_Gene is exported to its own TSV. The spreadsheet rows are Visium array_row values and the columns are Visium array_col values. A numeric cell is the selected gene's expression in the spot at that physical array position. Blank cells are positions absent from the current Seurat object and must remain blank. The first-column header stores the exact Feature_Gene, assay and layer so the edited grid can be written back safely. The filename records the maximum expression, assay and layer, for example 001_CD68_Max21_SCT_scale.data_SeuratGrid.tsv. These numeric values are used to calculate the plot colors; the Step 08 preview uses the full range with white = low and red = high.",
        sep = "\n"
    )

    help_window <- tcltk::tktoplevel(window, background = "#F4F7FB")
    tcltk::tkwm.title(help_window, "Step 08 - Assay and expression-layer guide")
    tcltk::tkwm.geometry(help_window, "900x720")
    tcltk::tkwm.minsize(help_window, 700L, 520L)
    tcltk::tkgrid.columnconfigure(help_window, 0L, weight = 1L)
    tcltk::tkgrid.rowconfigure(help_window, 0L, weight = 1L)

    help_frame <- tcltk::tkframe(help_window, background = "white", padx = 10L, pady = 10L)
    tcltk::tkgrid(help_frame, row = 0L, column = 0L, sticky = "nsew", padx = 10L, pady = 10L)
    tcltk::tkgrid.columnconfigure(help_frame, 0L, weight = 1L)
    tcltk::tkgrid.rowconfigure(help_frame, 0L, weight = 1L)
    help_box <- tcltk::tktext(help_frame, wrap = "word", background = "white", foreground = "#263238", padx = 10L, pady = 10L, font = "TkDefaultFont")
    help_scroll <- tcltk::tkscrollbar(help_frame, orient = "vertical", command = function(...) tcltk::tkyview(help_box, ...))
    tcltk::tkconfigure(help_box, yscrollcommand = function(...) tcltk::tkset(help_scroll, ...))
    tcltk::tkinsert(help_box, "end", guide_text)
    tcltk::tkconfigure(help_box, state = "disabled")
    tcltk::tkgrid(help_box, row = 0L, column = 0L, sticky = "nsew")
    tcltk::tkgrid(help_scroll, row = 0L, column = 1L, sticky = "ns")
    tcltk::tkgrid(tcltk::tkbutton(help_frame, text = "CLOSE GUIDE", command = function() tcltk::tkdestroy(help_window), background = "#AD1457", foreground = "white", padx = 18L), row = 1L, column = 0L, columnspan = 2L, pady = c(8L, 0L))
    tcltk::tkfocus(help_window)
}

body <- tcltk::tkframe(window, background = "#F4F7FB", padx = 10L, pady = 8L)
tcltk::tkgrid(body, row = 1L, column = 0L, sticky = "nsew")
tcltk::tkgrid.columnconfigure(body, 0L, weight = 1L)
tcltk::tkgrid.rowconfigure(body, 1L, weight = 1L)

files_panel <- tcltk::tkframe(body, background = "white", relief = "groove", borderwidth = 2L, padx = 8L, pady = 6L)
tcltk::tkgrid(files_panel, row = 0L, column = 0L, sticky = "ew", padx = 3L, pady = 3L)
tcltk::tkgrid.columnconfigure(files_panel, 1L, weight = 1L)
tcltk::tkgrid(tcltk::tklabel(files_panel, text = "FILES", background = "#FCE4EC", foreground = "#AD1457", font = "TkHeadingFont", anchor = "w", padx = 8L), row = 0L, column = 0L, columnspan = 3L, sticky = "ew")

browse_results <- function() {
    initial <- tcltk::tclvalue(results_var)
    if (!dir.exists(initial)) initial <- getwd()
    selected <- tcltk::tclvalue(tcltk::tkchooseDirectory(initialdir = initial, title = "Choose sample results folder", mustexist = TRUE))
    if (nzchar(selected)) {
        selected <- normalizePath(selected, winslash = "/", mustWork = TRUE)
        tcltk::tclvalue(results_var) <- selected
        candidates <- list.files(file.path(selected, "2_Spatial_QC"), pattern = "^tissue_positions.*\\.csv$", recursive = TRUE, full.names = TRUE, ignore.case = TRUE)
        if (length(candidates) == 1L) tcltk::tclvalue(positions_file_var) <- normalizePath(candidates[[1L]], winslash = "/", mustWork = TRUE)
    }
}

browse_input_rds <- function() {
    initial <- tcltk::tclvalue(results_var)
    if (dir.exists(file.path(initial, "Seurat_RDS"))) initial <- file.path(initial, "Seurat_RDS")
    if (!dir.exists(initial)) initial <- getwd()
    selected <- tcltk::tclvalue(tcltk::tkgetOpenFile(initialdir = initial, title = "Choose Seurat RDS", filetypes = "{{Seurat RDS} {.rds}} {{All files} {*}}"))
    if (nzchar(selected)) {
        tcltk::tclvalue(input_rds_var) <- normalizePath(selected, winslash = "/", mustWork = TRUE)
        tcltk::tclvalue(status_var) <- "Loading the selected Seurat object..."
        tcltk::tcl("update", "idletasks")
        load_object_gui()
    }
}

browse_positions_file <- function() {
    initial <- tcltk::tclvalue(results_var)
    if (dir.exists(file.path(initial, "2_Spatial_QC"))) initial <- file.path(initial, "2_Spatial_QC")
    if (!dir.exists(initial)) initial <- getwd()
    selected <- tcltk::tclvalue(tcltk::tkgetOpenFile(initialdir = initial, title = "Choose tissue_positions CSV used for this Seurat object", filetypes = "{{Tissue positions CSV} {.csv}} {{All files} {*}}"))
    if (nzchar(selected)) tcltk::tclvalue(positions_file_var) <- normalizePath(selected, winslash = "/", mustWork = TRUE)
}

tcltk::tkgrid(tcltk::tklabel(files_panel, text = "Sample results folder", background = "white", anchor = "w"), row = 1L, column = 0L, sticky = "w", padx = 3L, pady = 3L)
tcltk::tkgrid(tcltk::tkentry(files_panel, textvariable = results_var, width = 85L), row = 1L, column = 1L, sticky = "ew", padx = 3L)
tcltk::tkgrid(tcltk::tkbutton(files_panel, text = "BROWSE...", command = browse_results, background = "#1565C0", foreground = "white"), row = 1L, column = 2L, padx = 3L)
tcltk::tkgrid(tcltk::tklabel(files_panel, text = "Input Seurat RDS", background = "white", anchor = "w"), row = 2L, column = 0L, sticky = "w", padx = 3L, pady = 3L)
tcltk::tkgrid(tcltk::tkentry(files_panel, textvariable = input_rds_var, width = 85L), row = 2L, column = 1L, sticky = "ew", padx = 3L)
tcltk::tkgrid(tcltk::tkbutton(files_panel, text = "BROWSE...", command = browse_input_rds, background = "#1565C0", foreground = "white"), row = 2L, column = 2L, padx = 3L)
tcltk::tkgrid(tcltk::tklabel(files_panel, text = "Tissue positions CSV", background = "white", anchor = "w"), row = 3L, column = 0L, sticky = "w", padx = 3L, pady = 3L)
tcltk::tkgrid(tcltk::tkentry(files_panel, textvariable = positions_file_var, width = 85L), row = 3L, column = 1L, sticky = "ew", padx = 3L)
tcltk::tkgrid(tcltk::tkbutton(files_panel, text = "BROWSE...", command = browse_positions_file, background = "#1565C0", foreground = "white"), row = 3L, column = 2L, padx = 3L)

matrix_panel <- tcltk::tkframe(body, background = "white", relief = "groove", borderwidth = 2L, padx = 8L, pady = 6L)
tcltk::tkgrid(matrix_panel, row = 1L, column = 0L, sticky = "nsew", padx = 3L, pady = 3L)
tcltk::tkgrid.columnconfigure(matrix_panel, 1L, weight = 1L)
tcltk::tkgrid.rowconfigure(matrix_panel, 5L, weight = 1L)
tcltk::tkgrid(tcltk::tklabel(matrix_panel, text = "ASSAY, EXPRESSION MATRIX, AND FEATURE_GENES", background = "#FCE4EC", foreground = "#AD1457", font = "TkHeadingFont", anchor = "w", padx = 8L), row = 0L, column = 0L, columnspan = 4L, sticky = "ew")

matrix_controls <- tcltk::tkframe(matrix_panel, background = "white", padx = 2L, pady = 3L)
tcltk::tkgrid(matrix_controls, row = 1L, column = 0L, columnspan = 4L, sticky = "ew", padx = 3L, pady = 2L)

assay_combo <- tcltk::tklistbox(matrix_controls, selectmode = "browse", exportselection = FALSE, height = 3L, width = 38L, relief = "sunken", borderwidth = 2L)
layer_combo <- tcltk::tklistbox(matrix_controls, selectmode = "browse", exportselection = FALSE, height = 3L, width = 38L, relief = "sunken", borderwidth = 2L)
tcltk::tkgrid(tcltk::tklabel(matrix_controls, text = "Expression assay", background = "white", anchor = "w"), row = 0L, column = 0L, sticky = "w", padx = c(0L, 8L), pady = 3L)
tcltk::tkgrid(assay_combo, row = 0L, column = 1L, sticky = "w", padx = c(0L, 12L), pady = 3L)
tcltk::tkgrid(tcltk::tklabel(matrix_controls, text = "Expression matrix/layer", background = "white", anchor = "w"), row = 1L, column = 0L, sticky = "w", padx = c(0L, 8L), pady = 3L)
tcltk::tkgrid(layer_combo, row = 1L, column = 1L, sticky = "w", padx = c(0L, 12L), pady = 3L)
tcltk::tkgrid(tcltk::tkbutton(matrix_controls, text = "ASSAY/LAYER GUIDE", command = show_assay_layer_guide, background = "#455A64", foreground = "white", padx = 8L), row = 0L, column = 2L, rowspan = 2L, sticky = "ns", padx = c(4L, 0L), pady = 3L)
tcltk::tkgrid(tcltk::tklabel(matrix_controls, text = "Tissue image scale", background = "white", anchor = "w"), row = 2L, column = 0L, sticky = "w", padx = c(0L, 8L), pady = 3L)
tcltk::tkgrid(tcltk::ttkcombobox(matrix_controls, textvariable = image_scale_var, state = "readonly", values = c("auto", "hires", "lowres"), width = 16L), row = 2L, column = 1L, sticky = "w", padx = c(0L, 12L), pady = 3L)
tcltk::tkgrid(tcltk::tklabel(matrix_controls, text = "auto compares the stored image dimensions with its Seurat scale factors; select hires or lowres only to override detection.", background = "white", foreground = "#455A64", anchor = "w", justify = "left", wraplength = 560L), row = 2L, column = 2L, sticky = "w", padx = c(4L, 0L), pady = 3L)

set_matrix_selector <- function(widget, choices, selected = "", empty_text = "Load a Seurat RDS to display choices") {
    state$updating_matrix_selectors <- TRUE
    on.exit({ state$updating_matrix_selectors <- FALSE }, add = TRUE)
    tcltk::tkconfigure(widget, state = "normal")
    tcltk::tkdelete(widget, 0L, "end")
    if (!length(choices)) {
        tcltk::tkinsert(widget, "end", empty_text)
        tcltk::tkconfigure(widget, state = "disabled")
        return(invisible(NULL))
    }
    for (choice in choices) tcltk::tkinsert(widget, "end", choice)
    selected_index <- match(selected, choices, nomatch = 1L)
    tcltk::tcl(widget, "selection", "clear", 0L, "end")
    tcltk::tcl(widget, "selection", "set", selected_index - 1L)
    tcltk::tcl(widget, "activate", selected_index - 1L)
    tcltk::tcl(widget, "see", selected_index - 1L)
    invisible(NULL)
}

set_matrix_selector(assay_combo, character(0), empty_text = "Load a Seurat RDS to display assays")
set_matrix_selector(layer_combo, character(0), empty_text = "Load a Seurat RDS to display layers")

tcltk::tkgrid(
    tcltk::tklabel(matrix_panel, textvariable = matrix_summary_var, background = "#E8F5E9", foreground = "#1B5E20", anchor = "w", padx = 8L, pady = 4L),
    row = 2L, column = 0L, columnspan = 4L, sticky = "ew", padx = 3L, pady = 2L
)
tcltk::tkgrid(
    tcltk::tklabel(
        matrix_panel,
        text = "WHAT THE EXCEL METHOD MODIFIES: Spatial/data = normalized spatial expression used by many gene-expression maps; Spatial/counts = raw integer RNA counts only; SCT/data = SCT-normalized expression; SCT/scale.data = scaled values used by PCA, clustering and Step 5 spatial ranking. The affected step must be rerun with the modified RDS.",
        background = "#FFF8E1", foreground = "#5D4037", anchor = "w", justify = "left", wraplength = 1040L, padx = 8L, pady = 4L
    ),
    row = 3L, column = 0L, columnspan = 4L, sticky = "ew", padx = 3L, pady = 2L
)

gene_list <- tcltk::tklistbox(matrix_panel, selectmode = "multiple", exportselection = FALSE, height = 18L, width = 90L, relief = "solid", borderwidth = 1L)
gene_scroll <- tcltk::tkscrollbar(matrix_panel, orient = "vertical", command = function(...) tcltk::tkyview(gene_list, ...))
tcltk::tkconfigure(gene_list, yscrollcommand = function(...) tcltk::tkset(gene_scroll, ...))

selected_indices <- function() {
    text <- trimws(tcltk::tclvalue(tcltk::tcl(gene_list, "curselection")))
    if (!nzchar(text)) return(integer(0))
    suppressWarnings(as.integer(strsplit(text, "\\s+")[[1L]]) + 1L)
}

sync_selected_genes <- function() {
    if (isTRUE(state$updating_list)) return(invisible(NULL))
    indices <- selected_indices()
    visible_selected <- state$visible_features[indices[indices >= 1L & indices <= length(state$visible_features)]]
    state$selected_genes <- unique(c(setdiff(state$selected_genes, state$visible_features), visible_selected))
    tcltk::tclvalue(selected_status_var) <- paste0(length(state$selected_genes), " Feature_Gene(s) selected. Click a gene to select/deselect it; Ctrl is not needed.")
    invisible(NULL)
}

refresh_gene_list <- function() {
    sync_selected_genes()
    query <- tolower(trimws(tcltk::tclvalue(search_var)))
    visible <- if (!nzchar(query)) state$all_features else state$all_features[grepl(query, tolower(state$all_features), fixed = TRUE)]
    state$visible_features <- visible
    state$updating_list <- TRUE
    on.exit({ state$updating_list <- FALSE }, add = TRUE)
    tcltk::tkdelete(gene_list, 0L, "end")
    for (gene in visible) tcltk::tkinsert(gene_list, "end", gene)
    selected <- match(intersect(state$selected_genes, visible), visible, nomatch = 0L)
    for (index in selected[selected > 0L]) tcltk::tcl(gene_list, "selection", "set", index - 1L)
    tcltk::tclvalue(selected_status_var) <- paste0(length(state$selected_genes), " Feature_Gene(s) selected; ", length(visible), " displayed.")
    invisible(NULL)
}

refresh_features <- function() {
    if (is.null(state$object)) return(invisible(NULL))
    assay <- tcltk::tclvalue(assay_var)
    layer <- tcltk::tclvalue(layer_var)
    expression <- script8_get_layer(state$object, assay, layer)

    state$all_features <- sort(rownames(expression), method = "radix", na.last = TRUE)
    state$selected_genes <- character(0)
    tcltk::tclvalue(search_var) <- ""
    refresh_gene_list()
    tcltk::tclvalue(matrix_summary_var) <- paste0(
        "Loaded matrix: assay = ", assay, " | layer = ", layer, " | ",
        format(nrow(expression), big.mark = ","), " Feature_Genes x ",
        format(ncol(expression), big.mark = ","), " spots. Export: one array-row x array-column Seurat grid per selected Feature_Gene."
    )
    tcltk::tclvalue(status_var) <- paste0("Selected ", assay, "/", layer, ": ", nrow(expression), " Feature_Genes x ", ncol(expression), " spots.")
    invisible(NULL)
}

refresh_layers <- function() {
    if (is.null(state$object)) return(invisible(NULL))
    layers <- script8_layers(state$object, tcltk::tclvalue(assay_var))
    state$available_layers <- layers
    preferred <- if ("data" %in% layers) "data" else if ("counts" %in% layers) "counts" else layers[[1L]]
    tcltk::tclvalue(layer_var) <- preferred
    set_matrix_selector(layer_combo, layers, preferred, "Selected assay contains no layers")
    refresh_features()
}

select_assay_gui <- function() {
    if (isTRUE(state$updating_matrix_selectors) || !length(state$available_assays)) return(invisible(NULL))
    selected <- trimws(tcltk::tclvalue(tcltk::tcl(assay_combo, "curselection")))
    if (!nzchar(selected)) return(invisible(NULL))
    index <- suppressWarnings(as.integer(strsplit(selected, "\\s+")[[1L]][1L])) + 1L
    if (!is.finite(index) || index < 1L || index > length(state$available_assays)) return(invisible(NULL))
    tcltk::tclvalue(assay_var) <- state$available_assays[[index]]
    refresh_layers()
}

select_layer_gui <- function() {
    if (isTRUE(state$updating_matrix_selectors) || !length(state$available_layers)) return(invisible(NULL))
    selected <- trimws(tcltk::tclvalue(tcltk::tcl(layer_combo, "curselection")))
    if (!nzchar(selected)) return(invisible(NULL))
    index <- suppressWarnings(as.integer(strsplit(selected, "\\s+")[[1L]][1L])) + 1L
    if (!is.finite(index) || index < 1L || index > length(state$available_layers)) return(invisible(NULL))
    tcltk::tclvalue(layer_var) <- state$available_layers[[index]]
    refresh_features()
}

load_object_gui <- function() {
    tryCatch({
        tcltk::tclvalue(status_var) <- "Loading the selected Seurat object..."
        tcltk::tcl("update", "idletasks")
        state$input_rds <- normalizePath(tcltk::tclvalue(input_rds_var), winslash = "/", mustWork = TRUE)
        state$object <- script8_read_seurat(state$input_rds)
        state$original_object <- state$object
        assays <- script8_assays(state$object)
        state$available_assays <- assays
        default_assay <- tryCatch(SeuratObject::DefaultAssay(state$object), error = function(e) assays[[1L]])
        tcltk::tclvalue(assay_var) <- if (default_assay %in% assays) default_assay else assays[[1L]]
        set_matrix_selector(assay_combo, assays, tcltk::tclvalue(assay_var), "Seurat object contains no assays")
        refresh_layers()
        tcltk::tclvalue(status_var) <- paste0(
            "Loaded: ", basename(state$input_rds), " | ",
            length(assays), " assay(s) | ", length(state$all_features), " Feature_Genes displayed."
        )
        tcltk::tcl("update", "idletasks")
    }, error = function(e) {
        state$object <- NULL
        state$original_object <- NULL
        state$all_features <- character(0)
        state$visible_features <- character(0)
        state$selected_genes <- character(0)
        state$available_assays <- character(0)
        state$available_layers <- character(0)
        set_matrix_selector(assay_combo, character(0), empty_text = "Load a Seurat RDS to display assays")
        set_matrix_selector(layer_combo, character(0), empty_text = "Load a Seurat RDS to display layers")
        tcltk::tclvalue(assay_var) <- ""
        tcltk::tclvalue(layer_var) <- ""
        tcltk::tkdelete(gene_list, 0L, "end")
        tcltk::tclvalue(matrix_summary_var) <- "No expression matrix loaded. Correct the RDS selection shown in the error message."
        tcltk::tclvalue(selected_status_var) <- "No Seurat object loaded."
        tcltk::tclvalue(status_var) <- paste0("LOAD ERROR: ", conditionMessage(e))
        tcltk::tkmessageBox(title = "Could not load Seurat object", message = conditionMessage(e), icon = "error", type = "ok", parent = window)
    })
}

tcltk::tkgrid(tcltk::tkbutton(files_panel, text = "LOAD SELECTED SEURAT OBJECT", command = load_object_gui, background = "#AD1457", foreground = "white", padx = 14L), row = 4L, column = 0L, columnspan = 3L, sticky = "ew", padx = 3L, pady = 5L)
tcltk::tkgrid(tcltk::tklabel(matrix_panel, text = "Search Feature_Gene", background = "white", anchor = "w"), row = 4L, column = 0L, sticky = "w", padx = 3L)
tcltk::tkgrid(tcltk::tkentry(matrix_panel, textvariable = search_var, width = 40L), row = 4L, column = 1L, sticky = "ew", padx = 3L)
tcltk::tkgrid(tcltk::tkbutton(matrix_panel, text = "FILTER LIST", command = refresh_gene_list, background = "#455A64", foreground = "white"), row = 4L, column = 2L, padx = 3L)
tcltk::tkgrid(tcltk::tkbutton(matrix_panel, text = "SHOW ALL", command = function() { tcltk::tclvalue(search_var) <- ""; refresh_gene_list() }, background = "white", foreground = "#46546A"), row = 4L, column = 3L, padx = 3L)
tcltk::tkgrid(gene_list, row = 5L, column = 0L, columnspan = 3L, sticky = "nsew", padx = 3L, pady = 4L)
tcltk::tkgrid(gene_scroll, row = 5L, column = 3L, sticky = "ns", pady = 4L)

gene_buttons <- tcltk::tkframe(matrix_panel, background = "white")
tcltk::tkgrid(gene_buttons, row = 6L, column = 0L, columnspan = 4L, sticky = "ew", pady = 3L)
tcltk::tkpack(tcltk::tkbutton(gene_buttons, text = "SELECT ALL DISPLAYED", command = function() { state$selected_genes <- unique(c(state$selected_genes, state$visible_features)); refresh_gene_list() }, background = "#455A64", foreground = "white"), side = "left", padx = 3L)
tcltk::tkpack(tcltk::tkbutton(gene_buttons, text = "CLEAR DISPLAYED", command = function() { state$selected_genes <- setdiff(state$selected_genes, state$visible_features); refresh_gene_list() }, background = "white", foreground = "#46546A"), side = "left", padx = 3L)
tcltk::tkpack(tcltk::tkbutton(gene_buttons, text = "CLEAR ALL SELECTIONS", command = function() { state$selected_genes <- character(0); refresh_gene_list() }, background = "white", foreground = "#46546A"), side = "left", padx = 3L)
tcltk::tkpack(tcltk::tklabel(gene_buttons, textvariable = selected_status_var, background = "white", foreground = "#5D4037"), side = "right", padx = 5L)

tcltk::tkbind(gene_list, "<<ListboxSelect>>", sync_selected_genes)
tcltk::tkbind(assay_combo, "<<ListboxSelect>>", select_assay_gui)
tcltk::tkbind(layer_combo, "<<ListboxSelect>>", select_layer_gui)
tcltk::tkbind(window, "<Return>", function() refresh_gene_list())

actions_panel <- tcltk::tkframe(body, background = "white", relief = "groove", borderwidth = 2L, padx = 8L, pady = 6L)
tcltk::tkgrid(actions_panel, row = 2L, column = 0L, sticky = "ew", padx = 3L, pady = 3L)
tcltk::tkgrid.columnconfigure(actions_panel, 1L, weight = 1L)
tcltk::tkgrid(tcltk::tklabel(actions_panel, text = "EXPORT TO EXCEL / IMPORT EDITED MATRIX", background = "#FCE4EC", foreground = "#AD1457", font = "TkHeadingFont", anchor = "w", padx = 8L), row = 0L, column = 0L, columnspan = 3L, sticky = "ew")
tcltk::tkgrid(tcltk::tklabel(actions_panel, text = "Seurat-grid export folder", background = "white", anchor = "w"), row = 1L, column = 0L, sticky = "w", padx = 3L, pady = 3L)
tcltk::tkgrid(tcltk::tkentry(actions_panel, textvariable = export_file_var, width = 85L), row = 1L, column = 1L, sticky = "ew", padx = 3L)

browse_export <- function() {
    initial <- tcltk::tclvalue(results_var)
    if (!dir.exists(initial)) initial <- if (nzchar(state$input_rds)) dirname(state$input_rds) else getwd()
    suggested <- file.path(initial, "8_Edit_Gene_Expression_Matrix", "Seurat_Gene_Grids")
    dir.create(suggested, recursive = TRUE, showWarnings = FALSE)
    selected <- tcltk::tclvalue(tcltk::tkchooseDirectory(initialdir = suggested, title = "Choose folder for one Seurat-grid TSV per selected gene", mustexist = TRUE))
    if (nzchar(selected)) tcltk::tclvalue(export_file_var) <- normalizePath(selected, winslash = "/", mustWork = TRUE)
}
tcltk::tkgrid(tcltk::tkbutton(actions_panel, text = "BROWSE...", command = browse_export, background = "#1565C0", foreground = "white"), row = 1L, column = 2L, padx = 3L)

export_gui <- function() {
    tryCatch({
        if (is.null(state$object)) stop("Load a Seurat object first.")
        results_dir <- tcltk::tclvalue(results_var)
        if (!dir.exists(results_dir)) stop("Select an existing sample results folder before exporting.")
        sync_selected_genes()
        output_file <- tcltk::tclvalue(export_file_var)
        if (!nzchar(trimws(output_file))) {
            base_dir <- tcltk::tclvalue(results_var)
            if (!dir.exists(base_dir)) base_dir <- dirname(state$input_rds)
            output_file <- file.path(base_dir, "8_Edit_Gene_Expression_Matrix", "Seurat_Gene_Grids")
            tcltk::tclvalue(export_file_var) <- normalizePath(output_file, winslash = "/", mustWork = FALSE)
        }
        saved <- script8_export_matrix(state$object, tcltk::tclvalue(assay_var), tcltk::tclvalue(layer_var), state$selected_genes, output_file, tcltk::tclvalue(positions_file_var))
        before_plot_files <- script8_plot_spatial_genes(
            state$original_object,
            tcltk::tclvalue(assay_var),
            tcltk::tclvalue(layer_var),
            state$selected_genes,
            results_dir,
            plot_stage = "Before_Modification",
            display = FALSE,
            image_scale = tcltk::tclvalue(image_scale_var)
        )
        tcltk::tclvalue(modified_file_var) <- normalizePath(output_file, winslash = "/", mustWork = TRUE)
        tcltk::tclvalue(status_var) <- paste0("Exported ", length(saved), " Seurat gene grid(s) and ", length(before_plot_files), " before-modification image(s).")
        tcltk::tkmessageBox(
            title = "Seurat gene grid(s) exported",
            message = paste0(
                length(saved), " file(s) saved in:\n", output_file,
                "\n\nEach file = one Feature_Gene",
                "\nRows = Visium array rows",
                "\nColumns = Visium array columns",
                "\nNumeric cells = expression at that spot",
                "\nBlank cells = no spot; leave them blank",
                "\n\nThe filename includes the maximum expression, assay and layer, for example 001_CD68_Max21_SCT_scale.data_SeuratGrid.tsv.",
                "\n\nBefore-modification tissue image(s):\n", paste(before_plot_files, collapse = "\n"),
                "\n\nDo not rename row/column headers."
            ),
            icon = "info", type = "ok", parent = window
        )
    }, error = function(e) tcltk::tkmessageBox(title = "Export failed", message = conditionMessage(e), icon = "error", type = "ok", parent = window))
}
tcltk::tkgrid(tcltk::tkbutton(actions_panel, text = "EXPORT SELECTED GENE MATRIX", command = export_gui, background = "#00897B", foreground = "white", padx = 14L), row = 2L, column = 0L, columnspan = 3L, sticky = "ew", pady = 4L)

tcltk::tkgrid(tcltk::tklabel(actions_panel, text = "Edited Seurat-grid folder", background = "white", anchor = "w"), row = 3L, column = 0L, sticky = "w", padx = 3L, pady = 3L)
tcltk::tkgrid(tcltk::tkentry(actions_panel, textvariable = modified_file_var, width = 85L), row = 3L, column = 1L, sticky = "ew", padx = 3L)
browse_modified <- function() {
    initial <- tcltk::tclvalue(modified_file_var)
    if (!dir.exists(initial)) initial <- if (dir.exists(tcltk::tclvalue(results_var))) tcltk::tclvalue(results_var) else getwd()
    selected <- tcltk::tclvalue(tcltk::tkchooseDirectory(initialdir = initial, title = "Choose folder containing edited *_SeuratGrid.tsv files", mustexist = TRUE))
    if (nzchar(selected)) tcltk::tclvalue(modified_file_var) <- normalizePath(selected, winslash = "/", mustWork = TRUE)
}
tcltk::tkgrid(tcltk::tkbutton(actions_panel, text = "BROWSE...", command = browse_modified, background = "#1565C0", foreground = "white"), row = 3L, column = 2L, padx = 3L)

import_gui <- function() {
    tryCatch({
        if (is.null(state$object)) stop("Load a Seurat object first.")
        results_dir <- tcltk::tclvalue(results_var)
        if (!dir.exists(results_dir)) stop("Select an existing sample results folder.")
        assay <- tcltk::tclvalue(assay_var)
        layer <- tcltk::tclvalue(layer_var)
        edited_file <- tcltk::tclvalue(modified_file_var)
        imported <- script8_import_matrix(state$object, assay, layer, edited_file, tcltk::tclvalue(positions_file_var))
        modified_object <- imported$object
        saved <- script8_save_modified_object(modified_object, state$input_rds, results_dir, assay, layer)
        state$object <- modified_object
        state$last_imported_genes <- imported$genes
        plot_files <- script8_plot_spatial_genes(modified_object, assay, layer, imported$genes, results_dir, plot_stage = "After_Modification", display = TRUE, image_scale = tcltk::tclvalue(image_scale_var))
        tcltk::tclvalue(status_var) <- paste0("Modified Seurat object and ", length(plot_files), " tissue map(s) saved: ", saved)
        warning_text <- if (grepl("^counts($|[.])", layer, ignore.case = TRUE)) "\n\nRaw counts were changed. nCount/nFeature metadata were recalculated; Spatial percent.mt was recalculated when mitochondrial gene names were identifiable. Normalized layers, PCA, clusters, and downstream results were not recomputed." else ""
        tcltk::tkmessageBox(
            title = "Modified Seurat RDS and tissue map(s) saved",
            message = paste0(
                "Saved as a new object:\n", saved,
                "\n\nModified Feature_Genes: ", paste(imported$genes, collapse = ", "),
                "\n\nSpatial tissue map(s):\n", paste(plot_files, collapse = "\n"),
                warning_text
            ),
            icon = "info", type = "ok", parent = window
        )
    }, error = function(e) tcltk::tkmessageBox(title = "Import failed", message = conditionMessage(e), icon = "error", type = "ok", parent = window))
}
tcltk::tkgrid(tcltk::tkbutton(actions_panel, text = "IMPORT MODIFIED MATRIX + SAVE NEW SEURAT RDS", command = import_gui, background = "#AD1457", foreground = "white", padx = 14L), row = 4L, column = 0L, columnspan = 3L, sticky = "ew", pady = 4L)

preview_gui <- function() {
    tryCatch({
        if (is.null(state$object)) stop("Load a Seurat object first.")
        sync_selected_genes()
        genes <- unique(c(state$last_imported_genes, state$selected_genes))
        if (!length(genes)) stop("Select Feature_Genes in the list or import modified grids first.")
        results_dir <- tcltk::tclvalue(results_var)
        if (!dir.exists(results_dir)) stop("Select an existing sample results folder.")
        plot_stage <- if (length(state$last_imported_genes)) "After_Modification" else "Before_Modification"
        plot_files <- script8_plot_spatial_genes(state$object, tcltk::tclvalue(assay_var), tcltk::tclvalue(layer_var), genes, results_dir, plot_stage = plot_stage, display = TRUE, image_scale = tcltk::tclvalue(image_scale_var))
        tcltk::tclvalue(status_var) <- paste0("Displayed and saved ", length(plot_files), " spatial gene tissue map(s).")
    }, error = function(e) tcltk::tkmessageBox(title = "Spatial visualization failed", message = conditionMessage(e), icon = "error", type = "ok", parent = window))
}
tcltk::tkgrid(tcltk::tkbutton(actions_panel, text = "VISUALIZE SELECTED / MODIFIED GENES ON TISSUE", command = preview_gui, background = "#00897B", foreground = "white", padx = 14L), row = 5L, column = 0L, columnspan = 3L, sticky = "ew", pady = 4L)
tcltk::tkgrid(tcltk::tklabel(actions_panel, text = "Export saves the original tissue image in Gene_Spatial_Maps/Before_Modification. Import writes the edited spot values into a new RDS and saves the modified tissue image in Gene_Spatial_Maps/After_Modification. The input RDS is never overwritten.", background = "#FFF8E1", foreground = "#5D4037", anchor = "w", justify = "left", wraplength = 1000L, padx = 8L, pady = 5L), row = 6L, column = 0L, columnspan = 3L, sticky = "ew", pady = 3L)

footer <- tcltk::tkframe(window, background = "#E8EEF7", padx = 12L, pady = 7L)
tcltk::tkgrid(footer, row = 2L, column = 0L, sticky = "ew")
tcltk::tkpack(tcltk::tklabel(footer, textvariable = status_var, background = "#E8EEF7", foreground = "#263238", anchor = "w"), side = "left", fill = "x", expand = TRUE)
tcltk::tkpack(tcltk::tkbutton(footer, text = "CLOSE", command = function() tcltk::tkdestroy(window), background = "white", foreground = "#46546A", padx = 16L), side = "right")

tcltk::tkfocus(window)
tcltk::tkwait.window(window)
