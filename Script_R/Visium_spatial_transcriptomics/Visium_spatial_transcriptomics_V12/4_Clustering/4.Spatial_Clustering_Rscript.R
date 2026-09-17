

options(stringsAsFactors = FALSE)

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
PIPELINE_DIRECTORY <- dirname(SCRIPT_DIRECTORY)

VISIUM_RESULTS_DIRECTORY_NAME <- "Results"

visium_safe_sample_name <- function(sample_name) {
    sample_name <- trimws(as.character(sample_name)[1L])
    sample_name <- gsub("[^A-Za-z0-9._-]+", "_", sample_name)
    sample_name <- gsub("^[_ .-]+|[_ .-]+$", "", sample_name)
    if (!nzchar(sample_name)) stop("Sample name must contain at least one letter or number.")
    sample_name
}

visium_find_results_workspaces <- function(pipeline_directory) {
    results_directory <- file.path(normalizePath(pipeline_directory, winslash = "/", mustWork = FALSE), VISIUM_RESULTS_DIRECTORY_NAME)
    if (!dir.exists(results_directory)) return(character(0))
    candidates <- list.dirs(results_directory, recursive = FALSE, full.names = TRUE)
    candidates[dir.exists(file.path(candidates, "Seurat_RDS"))]
}

visium_default_results_workspace <- function(pipeline_directory) {
    workspaces <- visium_find_results_workspaces(pipeline_directory)
    if (length(workspaces) == 1L) workspaces[[1L]] else ""
}

visium_create_results_workspace <- function(pipeline_directory, sample_name) {
    sample_name <- visium_safe_sample_name(sample_name)
    workspace <- file.path(pipeline_directory, VISIUM_RESULTS_DIRECTORY_NAME, sample_name)
    dir.create(file.path(workspace, "Seurat_RDS"), recursive = TRUE, showWarnings = FALSE)
    normalizePath(workspace, winslash = "/", mustWork = TRUE)
}

visium_validate_results_workspace <- function(workspace, must_exist = TRUE) {
    workspace <- trimws(as.character(workspace)[1L])
    if (!nzchar(workspace)) stop("Select the sample results folder, for example Results/Sample_01.")
    if (must_exist && !dir.exists(workspace)) stop("Results workspace does not exist: ", workspace)
    if (!nzchar(basename(normalizePath(workspace, winslash = "/", mustWork = must_exist)))) stop("The selected sample results folder has no valid sample name: ", workspace)
    normalizePath(workspace, winslash = "/", mustWork = must_exist)
}

visium_workspace_sample_name <- function(workspace) {
    workspace <- visium_validate_results_workspace(workspace)
    visium_safe_sample_name(basename(workspace))
}

visium_stage_directory <- function(workspace, stage_name, create = TRUE) {
    stage_directory <- file.path(visium_validate_results_workspace(workspace), stage_name)
    if (create) dir.create(stage_directory, recursive = TRUE, showWarnings = FALSE)
    normalizePath(stage_directory, winslash = "/", mustWork = create)
}

visium_rds_directory <- function(workspace, create = TRUE) {
    rds_directory <- file.path(visium_validate_results_workspace(workspace), "Seurat_RDS")
    if (create) dir.create(rds_directory, recursive = TRUE, showWarnings = FALSE)
    normalizePath(rds_directory, winslash = "/", mustWork = create)
}

visium_find_stage_file <- function(workspace, stage_name, pattern, description) {
    stage_directory <- visium_stage_directory(workspace, stage_name, create = FALSE)
    if (!dir.exists(stage_directory)) stop("Run ", stage_name, " successfully before continuing.")
    rds_directory <- visium_rds_directory(workspace, create = FALSE)
    matches <- list.files(rds_directory, pattern = pattern, full.names = TRUE, ignore.case = TRUE)
    if (length(matches) != 1L) {
        stop(
            "Expected exactly one tagged ", description, " in:\n", rds_directory, "\n",
            "Matching files found: ", length(matches), "\nExpected filename pattern: ", pattern,
            if (length(matches)) paste0("\nCandidates:\n", paste0("  - ", basename(matches), collapse = "\n")) else "",
            "\nSelect the intended input RDS explicitly when multiple matching branches exist."
        )
    }
    normalizePath(matches[[1L]], winslash = "/", mustWork = TRUE)
}

visium_tagged_rds_path <- function(workspace, stage_name, step_tag, operation_tag) {
    operation_tag <- gsub("[^A-Za-z0-9._-]+", "_", operation_tag)
    file.path(visium_rds_directory(workspace), paste0(visium_workspace_sample_name(workspace), "_", step_tag, "_", operation_tag, ".rds"))
}

visium_rds_operation_tags <- function(input_path, step_tag) {
    filename_without_extension <- tools::file_path_sans_ext(basename(input_path))
    inherited_tags <- sub(paste0("^.*_", step_tag, "_"), "", filename_without_extension)
    if (identical(inherited_tags, filename_without_extension) || !nzchar(inherited_tags)) {
        stop("Input RDS does not contain the expected _", step_tag, "_ filename tag: ", basename(input_path))
    }
    inherited_tags
}

visium_parse_cli <- function(args = commandArgs(trailingOnly = TRUE)) {
    out <- list(); i <- 1L
    while (i <= length(args)) {
        token <- args[[i]]
        if (!startsWith(token, "--")) stop("Unexpected argument: ", token, call. = FALSE)
        token <- substring(token, 3L)
        if (startsWith(token, "no-") && !grepl("=", token, fixed = TRUE)) {
            key <- substring(token, 4L); value <- FALSE
        } else if (grepl("=", token, fixed = TRUE)) {
            bits <- strsplit(token, "=", fixed = TRUE)[[1L]]
            key <- bits[[1L]]; value <- paste(bits[-1L], collapse = "=")
        } else {
            key <- token
            if (i < length(args) && !startsWith(args[[i + 1L]], "--")) {
                i <- i + 1L; value <- args[[i]]
            } else value <- TRUE
        }
        key <- gsub("-", "_", key, fixed = TRUE)
        if (!is.null(out[[key]])) stop("Repeated option: --", gsub("_", "-", key), call. = FALSE)
        out[[key]] <- value; i <- i + 1L
    }
    out
}

visium_bool <- function(x, label = "value") {
    if (is.logical(x) && length(x) == 1L && !is.na(x)) return(x)
    x <- tolower(trimws(as.character(x)[1L]))
    if (x %in% c("true", "t", "1", "yes", "y", "on")) return(TRUE)
    if (x %in% c("false", "f", "0", "no", "n", "off")) return(FALSE)
    stop(label, " must be true or false.", call. = FALSE)
}

visium_number <- function(x, label = "value", infinite = FALSE) {
    z <- suppressWarnings(as.numeric(as.character(x)[1L]))
    if (is.na(z) || (!infinite && !is.finite(z))) stop(label, " must be numeric.", call. = FALSE)
    z
}

visium_integer <- function(x, label = "value") {
    z <- visium_number(x, label)
    if (z != trunc(z)) stop(label, " must be a whole number.", call. = FALSE)
    as.integer(z)
}

visium_csv <- function(x, label = "value", empty = TRUE) {
    x <- trimws(as.character(x))
    if (!length(x) || all(!nzchar(x))) {
        if (empty) return(character(0))
        stop(label, " cannot be empty.", call. = FALSE)
    }
    if (length(x) > 1L) return(x[nzchar(x)])
    z <- trimws(strsplit(x[[1L]], ",", fixed = TRUE)[[1L]])
    z[nzchar(z)]
}

visium_dims <- function(x, label = "dimensions") {
    x <- gsub("\\s+", "", as.character(x)[1L])
    if (grepl("^[0-9]+:[0-9]+$", x)) {
        p <- as.integer(strsplit(x, ":", fixed = TRUE)[[1L]])
        return(seq.int(p[[1L]], p[[2L]]))
    }
    z <- suppressWarnings(as.integer(visium_csv(x, label, FALSE)))
    if (anyNA(z)) stop(label, " must be like 1:30 or 1,2,3.", call. = FALSE)
    z
}

visium_resolutions <- function(x, label = "Clustering resolutions") {
    z <- suppressWarnings(as.numeric(visium_csv(x, label, FALSE)))
    if (anyNA(z) || any(!is.finite(z)) || any(z <= 0)) stop(label, " must contain positive numeric values.", call. = FALSE)
    unique(z)
}

visium_resolution_label <- function(resolution) {
    sub("\\.?0+$", "", sprintf("%.2f", as.numeric(resolution)))
}

visium_resolution_rds_label <- function(resolution) sprintf("%.2f", as.numeric(resolution))

visium_colors <- function(x, label = "colors", minimum = 1L) {
    x <- as.character(x)
    if (length(x) < minimum) stop(label, " requires at least ", minimum, " color(s).", call. = FALSE)
    bad <- vapply(x, function(z) inherits(try(grDevices::col2rgb(z), silent = TRUE), "try-error"), logical(1))
    if (any(bad)) stop(label, " contains invalid color(s): ", paste(x[bad], collapse = ", "), call. = FALSE)
    x
}

visium_option <- function(cli, name, default, type = "text", choices = NULL, infinite = FALSE) {
    key <- gsub("-", "_", name, fixed = TRUE)
    value <- if (is.null(cli[[key]])) default else cli[[key]]
    switch(
        type,
        text = as.character(value)[1L],
        path = if (nzchar(trimws(as.character(value)[1L]))) normalizePath(as.character(value)[1L], winslash = "/", mustWork = FALSE) else "",
        boolean = visium_bool(value, paste0("--", name)),
        number = visium_number(value, paste0("--", name), infinite),
        integer = visium_integer(value, paste0("--", name)),
        csv = visium_csv(value, paste0("--", name)),
        dims = visium_dims(value, paste0("--", name)),
        choice = {
            index <- match(tolower(as.character(value)[1L]), tolower(choices))
            if (is.na(index)) stop("--", name, " must be one of: ", paste(choices, collapse = ", "), call. = FALSE)
            choices[[index]]
        },
        stop("Unsupported option type: ", type, call. = FALSE)
    )
}

visium_print_help <- function(title, usage, lines) {
    cat(title, "\n\n", usage, "\n\nOptions:\n  ", paste(lines, collapse = "\n  "), "\n", sep = "")
}

visium_desktop_gui <- function(title, fields, accent = "#1F6FEB", max_width = 1240L, compact_files = FALSE, top_right_group = NULL, second_row_right_group = NULL) {
    tk_ready <- requireNamespace("tcltk", quietly = TRUE) && isTRUE(tryCatch({
        tcltk::tclRequire("Tk"); TRUE
    }, error = function(e) FALSE))
    if (!tk_ready) stop("The native GUI requires an R installation with Tcl/Tk support.", call. = FALSE)
    visium_colors(accent, "GUI accent")

    window <- tcltk::tktoplevel(background = "#F4F7FB")
    tcltk::tkwm.title(window, title)
    screen_width <- as.integer(tcltk::tclvalue(tcltk::tkwinfo("screenwidth", window)))
    screen_height <- as.integer(tcltk::tclvalue(tcltk::tkwinfo("screenheight", window)))
    window_width <- min(as.integer(max_width), max(620L, screen_width - 80L), screen_width)
    window_height <- min(930L, max(600L, screen_height - 80L), screen_height)
    position_x <- max(0L, as.integer((screen_width - window_width) / 2L))
    position_y <- max(0L, as.integer((screen_height - window_height) / 3L))
    tcltk::tkwm.geometry(window, sprintf("%dx%d+%d+%d", window_width, window_height, position_x, position_y))
    tcltk::tkwm.minsize(window, min(620L, window_width), min(600L, window_height))
    tcltk::tkgrid.columnconfigure(window, 0L, weight = 1L)
    tcltk::tkgrid.rowconfigure(window, 2L, weight = 1L)

    hero <- tcltk::tkframe(window, background = accent, relief = "flat", borderwidth = 0L)
    tcltk::tkgrid(hero, row = 0L, column = 0L, sticky = "ew")
    tcltk::tkpack(tcltk::tklabel(hero, text = title, background = accent, foreground = "white", font = "TkHeadingFont", anchor = "w", padx = 22L, pady = 9L), fill = "x")
    tcltk::tkpack(tcltk::tklabel(hero, text = "Group spots by normalized gene-expression similarity, then display those expression-derived clusters on the tissue.", background = accent, foreground = "white", anchor = "w", padx = 22L, pady = 4L), fill = "x")

    viewport <- tcltk::tkframe(window, background = "#F4F7FB")
    tcltk::tkgrid(viewport, row = 2L, column = 0L, sticky = "nsew")
    tcltk::tkgrid.columnconfigure(viewport, 0L, weight = 1L)
    tcltk::tkgrid.rowconfigure(viewport, 0L, weight = 1L)

    canvas <- tcltk::tkcanvas(viewport, background = "#F4F7FB", highlightthickness = 0L, borderwidth = 0L)
    vertical_scrollbar <- tcltk::tkscrollbar(viewport, orient = "vertical", width = 20L, command = function(...) tcltk::tkyview(canvas, ...))
    tcltk::tkconfigure(canvas, yscrollcommand = function(...) tcltk::tkset(vertical_scrollbar, ...))
    tcltk::tkgrid(canvas, row = 0L, column = 0L, sticky = "nsew")
    tcltk::tkgrid(vertical_scrollbar, row = 0L, column = 1L, sticky = "ns")

    body <- tcltk::tkframe(canvas, background = "#F4F7FB", padx = 12L, pady = 10L)
    body_window <- tcltk::tkcreate(canvas, "window", 0L, 0L, window = body, anchor = "nw")
    update_scroll_region <- function() {
        bounds <- tcltk::tclvalue(tcltk::tcl(canvas, "bbox", "all"))
        if (nzchar(bounds)) tcltk::tkconfigure(canvas, scrollregion = bounds)
        invisible(NULL)
    }
    fit_body_to_canvas <- function() {
        canvas_width <- suppressWarnings(as.integer(tcltk::tclvalue(tcltk::tkwinfo("width", canvas))))
        if (is.finite(canvas_width) && canvas_width > 1L) tcltk::tcl(canvas, "itemconfigure", body_window, "-width", canvas_width)
        update_scroll_region()
        invisible(NULL)
    }
    scroll_mouse_wheel <- function(D) {
        delta <- suppressWarnings(as.numeric(D))
        if (is.finite(delta) && delta != 0) tcltk::tkyview(canvas, "scroll", if (delta > 0) -3L else 3L, "units")
        invisible(NULL)
    }
    tcltk::tkbind(body, "<Configure>", update_scroll_region)
    tcltk::tkbind(canvas, "<Configure>", fit_body_to_canvas)
    tcltk::tkbind(window, "<MouseWheel>", scroll_mouse_wheel)
    tcltk::tkbind(window, "<Prior>", function() tcltk::tkyview(canvas, "scroll", -1L, "pages"))
    tcltk::tkbind(window, "<Next>", function() tcltk::tkyview(canvas, "scroll", 1L, "pages"))

    panel_columns <- if (window_width >= 900L) 2L else 1L
    for (column_index in seq_len(panel_columns) - 1L) tcltk::tkgrid.columnconfigure(body, column_index, weight = 1L, uniform = "panels")

    editable_fields <- fields[!vapply(fields, function(f) f$type %in% c("info", "action"), logical(1))]
    compound_number_fields <- lapply(fields[vapply(fields, function(f) identical(f$type, "boolean_number"), logical(1))], function(f) {
        list(name = f$number_name, value = f$number_value, type = if (identical(f$number_type, "integer")) "integer" else "number")
    })
    editable_fields <- c(editable_fields, compound_number_fields)
    variables <- setNames(lapply(editable_fields, function(f) {
        initial <- if (is.logical(f$value)) if (isTRUE(f$value)) "TRUE" else "FALSE" else paste(f$value, collapse = ",")
        tcltk::tclVar(initial)
    }), vapply(editable_fields, `[[`, character(1), "name"))

    if ("results_dir" %in% names(variables)) {
        results_folder_bar <- tcltk::tkframe(window, background = "#E8EEF7", padx = 14L, pady = 7L, relief = "raised", borderwidth = 1L)
        tcltk::tkgrid(results_folder_bar, row = 1L, column = 0L, sticky = "ew")

        tcltk::tkgrid.columnconfigure(results_folder_bar, 1L, weight = 0L)
        tcltk::tkgrid(tcltk::tklabel(results_folder_bar, text = "FILES — SELECT YOUR RESULTS FOLDER", background = "#E8EEF7", foreground = accent, font = "TkHeadingFont", anchor = "w"), row = 0L, column = 0L, columnspan = 3L, sticky = "ew", pady = c(0L, 3L))
        tcltk::tkgrid(tcltk::tklabel(results_folder_bar, text = "Sample results folder (for example Results/Sample_01)", background = "#E8EEF7", foreground = "#1D2A3A", anchor = "w"), row = 1L, column = 0L, sticky = "w", padx = c(0L, 8L))
        tcltk::tkgrid(tcltk::tkentry(results_folder_bar, textvariable = variables[["results_dir"]], width = 24L, relief = "solid", borderwidth = 1L), row = 1L, column = 1L, sticky = "w")
        choose_results_folder <- function() {
            current <- tcltk::tclvalue(variables[["results_dir"]])
            initial_dir <- if (dir.exists(current)) current else getwd()
            selected <- tcltk::tclvalue(tcltk::tkchooseDirectory(initialdir = initial_dir, title = "Choose the Results/SampleName folder", mustexist = TRUE))
            if (nzchar(selected)) tcltk::tclvalue(variables[["results_dir"]]) <- normalizePath(selected, winslash = "/", mustWork = TRUE)
        }
        tcltk::tkgrid(tcltk::tkbutton(results_folder_bar, text = "BROWSE...", command = choose_results_folder, background = "#1565C0", foreground = "white", activebackground = "#0D47A1", activeforeground = "white", relief = "raised", borderwidth = 2L, padx = 10L), row = 1L, column = 2L, sticky = "ew", padx = c(8L, 0L))
        if ("input_rds" %in% names(variables)) {
            tcltk::tkgrid(tcltk::tklabel(results_folder_bar, text = "Step 03 QC-filtered normalized Seurat RDS", background = "#E8EEF7", foreground = "#1D2A3A", anchor = "w"), row = 2L, column = 0L, sticky = "w", padx = c(0L, 8L), pady = c(6L, 0L))
            tcltk::tkgrid(tcltk::tkentry(results_folder_bar, textvariable = variables[["input_rds"]], width = 24L, relief = "solid", borderwidth = 1L), row = 2L, column = 1L, sticky = "w", pady = c(6L, 0L))
            choose_input_rds <- function() {
                current <- tcltk::tclvalue(variables[["input_rds"]])
                results_folder <- tcltk::tclvalue(variables[["results_dir"]])
                rds_folder <- file.path(results_folder, "Seurat_RDS")
                initial_dir <- if (file.exists(current)) dirname(current) else if (dir.exists(rds_folder)) rds_folder else if (dir.exists(results_folder)) results_folder else getwd()
                selected <- tcltk::tclvalue(tcltk::tkgetOpenFile(initialdir = initial_dir, title = "Choose Step 03 QC-filtered normalized Seurat RDS", filetypes = "{{Seurat RDS} {.rds}} {{All files} {*}}"))
                if (nzchar(selected)) tcltk::tclvalue(variables[["input_rds"]]) <- normalizePath(selected, winslash = "/", mustWork = TRUE)
            }
            tcltk::tkgrid(tcltk::tkbutton(results_folder_bar, text = "BROWSE...", command = choose_input_rds, background = "#1565C0", foreground = "white", activebackground = "#0D47A1", activeforeground = "white", relief = "raised", borderwidth = 2L, padx = 10L), row = 2L, column = 2L, sticky = "ew", padx = c(8L, 0L), pady = c(6L, 0L))
        }
    }
    multi_widgets <- list()
    multi_choices <- list()
    dependent_refreshers <- list()
    update_cluster_names_requested <- FALSE
    refresh_dependents <- function(source_name, show_error = TRUE) {
        for (dependent in dependent_refreshers) {
            if (source_name %in% dependent$sources) try(dependent$refresh(show_error), silent = TRUE)
        }
        invisible(NULL)
    }

    panel_fields <- fields[!vapply(fields, function(f) isTRUE(f$hide_in_panels), logical(1))]
    groups <- unique(vapply(panel_fields, function(f) if (is.null(f$group)) "Settings" else f$group, character(1)))
    regular_panel_index <- 0L
    for (group in groups) {
        subset <- panel_fields[vapply(panel_fields, function(f) identical(if (is.null(f$group)) "Settings" else f$group, group), logical(1))]
        is_files_panel <- startsWith(tolower(group), "files")
        is_top_right_panel <- panel_columns >= 2L && isTRUE(compact_files) && !is.null(top_right_group) && identical(tolower(group), tolower(top_right_group))
        is_second_row_right_panel <- panel_columns >= 2L && isTRUE(compact_files) && !is.null(second_row_right_group) && identical(tolower(group), tolower(second_row_right_group))
        if (is_files_panel) {
            panel_row <- 0L; panel_column <- 0L; panel_span <- if (panel_columns >= 2L && isTRUE(compact_files)) 1L else panel_columns
        } else if (is_top_right_panel) {
            panel_row <- 0L; panel_column <- 1L; panel_span <- 1L
        } else if (is_second_row_right_panel) {
            panel_row <- 1L; panel_column <- 1L; panel_span <- 1L
        } else if (panel_columns >= 2L && isTRUE(compact_files)) {

            if (regular_panel_index == 0L) {
                panel_row <- 1L; panel_column <- 0L; panel_span <- 1L
            } else {
                adjusted_index <- regular_panel_index - 1L
                panel_row <- 2L + adjusted_index %/% panel_columns
                panel_column <- adjusted_index %% panel_columns
                panel_span <- 1L
            }
            regular_panel_index <- regular_panel_index + 1L
        } else {
            panel_row <- 1L + regular_panel_index %/% panel_columns
            panel_column <- regular_panel_index %% panel_columns
            panel_span <- 1L
            regular_panel_index <- regular_panel_index + 1L
        }
        panel <- tcltk::tkframe(body, background = "white", relief = "groove", borderwidth = 2L, padx = 8L, pady = 6L)
        tcltk::tkgrid(panel, row = panel_row, column = panel_column, columnspan = panel_span, sticky = "nsew", padx = 5L, pady = 5L)
        has_inline_layout <- any(vapply(subset, function(f) isTRUE(f$inline_with_previous), logical(1)))
        panel_field_columns <- if (has_inline_layout) 6L else 3L
        tcltk::tkgrid.columnconfigure(panel, 1L, weight = 1L)
        if (has_inline_layout) tcltk::tkgrid.columnconfigure(panel, 4L, weight = 1L)
        tcltk::tkgrid(
            tcltk::tklabel(panel, text = toupper(group), background = "#E8EEF7", foreground = accent, font = "TkHeadingFont", anchor = "w", padx = 8L, pady = 4L),
            row = 0L, column = 0L, columnspan = panel_field_columns, sticky = "ew", pady = c(0L, 4L)
        )
        field_rows <- integer(length(subset))
        next_field_row <- 1L
        for (layout_index in seq_along(subset)) {
            if (layout_index > 1L && isTRUE(subset[[layout_index]]$inline_with_previous)) {
                field_rows[[layout_index]] <- field_rows[[layout_index - 1L]]
            } else {
                field_rows[[layout_index]] <- next_field_row
                next_field_row <- next_field_row + 1L
            }
        }
        for (field_index in seq_along(subset)) local({
            f <- subset[[field_index]]
            field_row <- field_rows[[field_index]]
            is_inline_second <- isTRUE(f$inline_with_previous)
            is_inline_first <- field_index < length(subset) && isTRUE(subset[[field_index + 1L]]$inline_with_previous)
            is_inline_field <- is_inline_first || is_inline_second
            field_base_column <- if (is_inline_second) 3L else 0L
            label_column <- field_base_column
            control_column <- field_base_column + 1L
            button_column <- if (has_inline_layout && !is_inline_field) 5L else field_base_column + 2L
            control_span <- if (has_inline_layout && !is_inline_field) 4L else 1L
            if (identical(f$type, "info")) {
                info_text <- if (!is.null(f$text)) f$text else f$label
                tcltk::tkgrid(
                    tcltk::tklabel(panel, text = info_text, background = "#FFF8E1", foreground = "#5D4037", anchor = "w", wraplength = if (is_files_panel) 900L else if (panel_columns >= 3L) 330L else 500L, justify = "left", padx = 8L, pady = 5L),
                    row = field_row, column = 0L, columnspan = panel_field_columns, sticky = "ew", padx = 3L, pady = 3L
                )
            } else if (identical(f$type, "action")) {
                action_command <- function() {
                    if (identical(f$action, "run")) {
                        update_cluster_names_requested <<- FALSE
                        run()
                    } else if (identical(f$action, "browse_results_folder")) {
                        current <- tcltk::tclvalue(variables[["results_dir"]])
                        initial_dir <- if (dir.exists(current)) current else getwd()
                        selected <- tcltk::tclvalue(tcltk::tkchooseDirectory(initialdir = initial_dir, title = "Choose the Results/SampleName folder", mustexist = TRUE))
                        if (nzchar(selected)) tcltk::tclvalue(variables[["results_dir"]]) <- normalizePath(selected, winslash = "/", mustWork = TRUE)
                    } else if (identical(f$action, "update_cluster_names")) {
                        annotation_path <- trimws(tcltk::tclvalue(variables[["cluster_annotation_file"]]))
                        target_rds_path <- trimws(tcltk::tclvalue(variables[["cluster_rds_to_update"]]))
                        if (!nzchar(annotation_path) || !file.exists(annotation_path)) {
                            tcltk::tkmessageBox(title = "Select cluster-name file", message = "First select an existing tabulated Cluster_Number / Cluster_Name file.", icon = "error", type = "ok", parent = window)
                        } else if (!nzchar(target_rds_path) || !file.exists(target_rds_path)) {
                            tcltk::tkmessageBox(title = "Select Step 4 Seurat RDS", message = "Select the existing Step 4 _Clstr0.xx.rds object that must receive the cluster names. If no Step 4 RDS exists, run the clustering analysis first.", icon = "error", type = "ok", parent = window)
                        } else {
                            update_cluster_names_requested <<- TRUE
                            run()
                        }
                    } else if (is.function(f$command)) {
                        f$command()
                    }
                }
                action_button <- tcltk::tkbutton(
                    panel,
                    text = f$label,
                    command = action_command,
                    background = if (is.null(f$background)) accent else f$background,
                    foreground = "white",
                    activebackground = accent,
                    activeforeground = "white",
                    relief = "raised",
                    borderwidth = 2L,
                    padx = 16L,
                    pady = 8L
                )
                tcltk::tkgrid(action_button, row = field_row, column = 0L, columnspan = panel_field_columns, sticky = "ew", padx = 3L, pady = 6L)
            } else {
                variable <- variables[[f$name]]
                label_text <- paste0(f$label, if (isTRUE(f$required)) "  *" else "")
                tcltk::tkgrid(
                    tcltk::tklabel(panel, text = label_text, background = "white", foreground = "#1D2A3A", anchor = "w", wraplength = if (is_inline_field) 125L else if (panel_columns >= 3L && !is_files_panel) 125L else 190L, justify = "left"),
                    row = field_row, column = label_column, sticky = "w", padx = c(3L, 8L), pady = 3L
                )
                if (identical(f$type, "boolean_number")) {
                    control <- tcltk::tkframe(panel, background = "white")
                    tcltk::tkpack(
                        tcltk::tkcheckbutton(control, text = if (is.null(f$boolean_text)) "Enabled" else f$boolean_text, variable = variable, onvalue = "TRUE", offvalue = "FALSE", background = "white", activebackground = "white", selectcolor = "white", anchor = "w"),
                        side = "left", padx = c(0L, 8L)
                    )
                    tcltk::tkpack(
                        tcltk::tklabel(control, text = if (is.null(f$number_label)) "Cutoff:" else paste0(f$number_label, ":"), background = "white", foreground = "#46546A"),
                        side = "left", padx = c(0L, 5L)
                    )
                    tcltk::tkpack(
                        tcltk::tkentry(control, textvariable = variables[[f$number_name]], width = 9L, relief = "solid", borderwidth = 1L, highlightthickness = 1L, highlightcolor = accent),
                        side = "left"
                    )
                } else if (identical(f$type, "boolean")) {
                    control <- tcltk::tkcheckbutton(panel, text = if (is.null(f$boolean_text)) "Enabled" else f$boolean_text, variable = variable, onvalue = "TRUE", offvalue = "FALSE", background = "white", activebackground = "white", selectcolor = "white", anchor = "w")
                } else if (identical(f$type, "radio")) {
                    control <- tcltk::tkframe(panel, background = "white")
                    for (radio_choice in f$choices) {
                        tcltk::tkpack(
                            tcltk::tkradiobutton(control, text = radio_choice, variable = variable, value = radio_choice, background = "white", activebackground = "white", selectcolor = "white", padx = 5L),
                            side = if (identical(f$orientation, "vertical")) "top" else "left",
                            anchor = "w"
                        )
                    }
                } else if (f$type %in% c("choice", "editable_choice")) {
                    control <- tcltk::ttkcombobox(panel, textvariable = variable, values = f$choices, state = if (identical(f$type, "editable_choice")) "normal" else "readonly", width = if (is_inline_field) 15L else if (panel_columns >= 3L && !is_files_panel) 20L else 34L)
                    choice_sources <- if (!is.null(f$choice_sources)) f$choice_sources else f$choice_source
                    if (is.function(f$choice_loader) && length(choice_sources)) {
                        refresh_choice <- function(show_error = TRUE) {
                            source_values <- setNames(lapply(choice_sources, function(source_name) tcltk::tclvalue(variables[[source_name]])), choice_sources)
                            refreshed <- tryCatch({
                                if (length(choice_sources) == 1L && is.null(f$choice_sources)) {
                                    f$choice_loader(source_values[[1L]])
                                } else {
                                    do.call(f$choice_loader, source_values)
                                }
                            }, error = function(e) e)
                            if (inherits(refreshed, "error")) {
                                if (show_error) tcltk::tkmessageBox(title = "Could not refresh choices", message = conditionMessage(refreshed), icon = "error", type = "ok", parent = window)
                                return(invisible(FALSE))
                            }
                            refreshed <- unique(trimws(as.character(refreshed)))
                            refreshed <- refreshed[nzchar(refreshed)]
                            if (!length(refreshed)) {
                                if (show_error) tcltk::tkmessageBox(title = "Could not refresh choices", message = paste(f$label, "has no available choices."), icon = "error", type = "ok", parent = window)
                                return(invisible(FALSE))
                            }
                            tcltk::tkconfigure(control, values = refreshed)
                            current <- tcltk::tclvalue(variable)
                            if (!(current %in% refreshed)) {
                                preferred <- if (as.character(f$value)[1L] %in% refreshed) as.character(f$value)[1L] else refreshed[[1L]]
                                tcltk::tclvalue(variable) <- preferred
                            }
                            invisible(TRUE)
                        }
                        dependent_refreshers[[f$name]] <<- list(sources = choice_sources, refresh = refresh_choice)
                    }
                    tcltk::tkbind(control, "<<ComboboxSelected>>", function() refresh_dependents(f$name, TRUE))
                    if (identical(f$type, "editable_choice")) {
                        tcltk::tkbind(control, "<Return>", function() refresh_dependents(f$name, TRUE))
                        tcltk::tkbind(control, "<FocusOut>", function() refresh_dependents(f$name, TRUE))
                    }
                } else if (identical(f$type, "multichoice")) {
                    control <- tcltk::tkframe(panel, background = "white")
                    tcltk::tkgrid.columnconfigure(control, 0L, weight = 1L)
                    listbox <- tcltk::tklistbox(
                        control,
                        selectmode = "multiple",
                        exportselection = FALSE,
                        height = min(7L, max(3L, length(f$choices))),
                        width = if (panel_columns >= 3L && !is_files_panel) 28L else 42L,
                        relief = "solid",
                        borderwidth = 1L,
                        highlightthickness = 1L,
                        highlightcolor = accent
                    )
                    scrollbar <- tcltk::tkscrollbar(control, orient = "vertical", command = function(...) tcltk::tkyview(listbox, ...))
                    tcltk::tkconfigure(listbox, yscrollcommand = function(...) tcltk::tkset(scrollbar, ...))
                    tcltk::tkgrid(listbox, row = 0L, column = 0L, sticky = "nsew")
                    tcltk::tkgrid(scrollbar, row = 0L, column = 1L, sticky = "ns")

                    populate_multichoice <- function(choices, preserve = character(0)) {
                        choices <- unique(trimws(as.character(choices)))
                        choices <- choices[nzchar(choices)]
                        if (!length(choices)) stop(f$label, " has no available choices.")
                        tcltk::tkdelete(listbox, 0L, "end")
                        for (choice in choices) tcltk::tkinsert(listbox, "end", choice)
                        multi_choices[[f$name]] <<- choices

                        selected <- intersect(preserve, choices)
                        if (!length(selected)) {
                            initial <- trimws(strsplit(tcltk::tclvalue(variable), ",", fixed = TRUE)[[1L]])
                            selected <- intersect(initial[nzchar(initial)], choices)
                        }
                        if (!length(selected) && "all" %in% choices) selected <- "all"
                        for (index in match(selected, choices, nomatch = 0L)) {
                            if (index > 0L) tcltk::tcl(listbox, "selection", "set", index - 1L)
                        }
                        invisible(choices)
                    }

                    populate_multichoice(f$choices)
                    multi_widgets[[f$name]] <<- listbox

                    choice_sources <- if (!is.null(f$choice_sources)) f$choice_sources else f$choice_source
                    if (is.function(f$choice_loader) && length(choice_sources)) {
                        refresh_choices <- function(show_error = TRUE) {
                            current_indices <- suppressWarnings(as.integer(strsplit(trimws(tcltk::tclvalue(tcltk::tcl(listbox, "curselection"))), "\\s+")[[1L]]))
                            current_indices <- current_indices[is.finite(current_indices)] + 1L
                            current_choices <- multi_choices[[f$name]]
                            preserve <- current_choices[current_indices[current_indices >= 1L & current_indices <= length(current_choices)]]
                            source_values <- setNames(lapply(choice_sources, function(source_name) tcltk::tclvalue(variables[[source_name]])), choice_sources)
                            refreshed <- tryCatch({
                                if (length(choice_sources) == 1L && is.null(f$choice_sources)) {
                                    f$choice_loader(source_values[[1L]])
                                } else {
                                    do.call(f$choice_loader, source_values)
                                }
                            }, error = function(e) e)
                            if (inherits(refreshed, "error")) {
                                if (show_error) tcltk::tkmessageBox(title = "Could not refresh choices", message = conditionMessage(refreshed), icon = "error", type = "ok", parent = window)
                                return(invisible(FALSE))
                            }
                            populate_multichoice(refreshed, preserve)
                            invisible(TRUE)
                        }
                        dependent_refreshers[[f$name]] <<- list(sources = choice_sources, refresh = refresh_choices)
                        refresh_button <- tcltk::tkbutton(control, text = "REFRESH PATHWAYS", command = refresh_choices, background = "#455A64", foreground = "white", activebackground = "#263238", activeforeground = "white", relief = "raised", borderwidth = 1L, padx = 8L)
                        tcltk::tkgrid(refresh_button, row = 1L, column = 0L, columnspan = 2L, sticky = "ew", pady = c(4L, 0L))
                    }
                } else {
                    control <- tcltk::tkentry(panel, textvariable = variable, width = if (is_inline_field) 10L else if (is_files_panel && panel_span > 1L) 62L else if (is_files_panel) 28L else if (panel_columns >= 3L) 22L else 34L, relief = "solid", borderwidth = 1L, highlightthickness = 1L, highlightcolor = accent)
                }
                tcltk::tkgrid(control, row = field_row, column = control_column, columnspan = control_span, sticky = "ew", padx = 2L, pady = 3L)

                if (f$type %in% c("file", "directory")) {
                    browse <- function() {
                        current <- tcltk::tclvalue(variable)
                        initial_dir <- if (dir.exists(current)) current else if (file.exists(current)) dirname(current) else getwd()
                        if (!is.null(f$initial_directory_source) && f$initial_directory_source %in% names(variables)) {
                            source_directory <- tcltk::tclvalue(variables[[f$initial_directory_source]])
                            if (!is.null(f$initial_subdirectory) && nzchar(f$initial_subdirectory)) source_directory <- file.path(source_directory, f$initial_subdirectory)
                            if (!nzchar(current) && dir.exists(source_directory)) initial_dir <- source_directory
                        }
                        selected <- if (identical(f$type, "file")) {
                            tcltk::tclvalue(tcltk::tkgetOpenFile(initialdir = initial_dir, title = paste("Choose", f$label)))
                        } else {
                            tcltk::tclvalue(tcltk::tkchooseDirectory(initialdir = initial_dir, title = paste("Choose", f$label), mustexist = FALSE))
                        }
                        if (nzchar(selected)) {
                            tcltk::tclvalue(variable) <- normalizePath(selected, winslash = "/", mustWork = FALSE)
                            refresh_dependents(f$name, TRUE)
                        }
                    }
                    button <- tcltk::tkbutton(panel, text = "BROWSE...", command = browse, background = "#1565C0", foreground = "white", activebackground = "#0D47A1", activeforeground = "white", relief = "raised", borderwidth = 2L, padx = 10L)
                    tcltk::tkgrid(button, row = field_row, column = button_column, sticky = "ew", padx = c(7L, 3L), pady = 3L)
                } else if (identical(f$type, "color")) {
                    choose_color <- function() {
                        selected <- tcltk::tclvalue(tcltk::tcl("tk_chooseColor", initialcolor = tcltk::tclvalue(variable), title = paste("Choose", f$label)))
                        if (nzchar(selected)) tcltk::tclvalue(variable) <- selected
                    }
                    button <- tcltk::tkbutton(panel, text = "COLOR...", command = choose_color, background = "#7B1FA2", foreground = "white", activebackground = "#4A148C", activeforeground = "white", relief = "raised", borderwidth = 1L, padx = 10L)
                    tcltk::tkgrid(button, row = field_row, column = button_column, sticky = "ew", padx = c(7L, 3L), pady = 3L)
                } else if (!is.null(f$help) && nzchar(trimws(as.character(f$help)[1L]))) {
                    show_field_help <- function() {
                        tcltk::tkmessageBox(title = f$label, message = f$help, icon = "info", type = "ok", parent = window)
                    }
                    button <- tcltk::tkbutton(panel, text = "?", command = show_field_help, background = "#E8EEF7", foreground = accent, activebackground = "#D5DFEE", activeforeground = accent, relief = "solid", borderwidth = 1L, padx = 8L)
                    tcltk::tkgrid(button, row = field_row, column = button_column, sticky = "ew", padx = c(7L, 3L), pady = 3L)
                }
            }
        })
    }

    result <- NULL
    action_bar <- tcltk::tkframe(window, background = "#E8EEF7", padx = 16L, pady = 10L, relief = "raised", borderwidth = 1L)
    tcltk::tkgrid(action_bar, row = 3L, column = 0L, sticky = "ew")
    tcltk::tkpack(tcltk::tklabel(action_bar, text = "* Required    Review the colored settings panels before running", background = "#E8EEF7", foreground = "#46546A"), side = "left", padx = 4L)

    cancel <- function() tcltk::tkdestroy(window)
    run_analysis <- function(...) {
        update_cluster_names_requested <<- FALSE
        run()
    }
    run <- function(...) {
        values <- setNames(lapply(variables, tcltk::tclvalue), names(variables))
        for (field_name in names(multi_widgets)) {
            selection_text <- trimws(tcltk::tclvalue(tcltk::tcl(multi_widgets[[field_name]], "curselection")))
            indices <- if (nzchar(selection_text)) suppressWarnings(as.integer(strsplit(selection_text, "\\s+")[[1L]]) + 1L) else integer(0)
            choices <- multi_choices[[field_name]]
            selected <- choices[indices[is.finite(indices) & indices >= 1L & indices <= length(choices)]]
            values[[field_name]] <- if ("all" %in% selected) "all" else paste(selected, collapse = ",")
        }
        values$update_cluster_names_only <- if (isTRUE(update_cluster_names_requested)) "TRUE" else "FALSE"
        error <- tryCatch({
            for (f in fields) {
                value <- values[[f$name]]
                if (isTRUE(f$required) && !nzchar(trimws(as.character(value)[1L]))) stop(f$label, " is required.")
                if (identical(f$type, "integer")) visium_integer(value, f$label)
                if (identical(f$type, "number")) visium_number(value, f$label, isTRUE(f$infinite))
                if (identical(f$type, "boolean")) visium_bool(value, f$label)
                if (identical(f$type, "boolean_number")) {
                    visium_bool(value, f$label)
                    number_label <- if (is.null(f$number_label)) paste(f$label, "cutoff") else f$number_label
                    if (identical(f$number_type, "integer")) {
                        visium_integer(values[[f$number_name]], number_label)
                    } else {
                        visium_number(values[[f$number_name]], number_label)
                    }
                }
                if (identical(f$type, "color")) visium_colors(value, f$label)
                if (identical(f$type, "file") && isTRUE(f$must_exist) && !file.exists(value)) stop(f$label, " does not exist.")
                if (identical(f$type, "directory") && isTRUE(f$must_exist) && !dir.exists(value)) stop(f$label, " does not exist.")
            }
            NULL
        }, error = function(e) conditionMessage(e))
        if (!is.null(error)) {
            tcltk::tkmessageBox(title = "Check settings", message = error, icon = "error", type = "ok", parent = window)
            return(invisible(NULL))
        }
        result <<- values
        tcltk::tkdestroy(window)
    }

    tcltk::tkpack(tcltk::tkbutton(action_bar, text = "RUN ANALYSIS", command = run_analysis, background = accent, foreground = "white", activebackground = accent, activeforeground = "white", relief = "raised", borderwidth = 2L, padx = 28L, pady = 9L), side = "right", padx = 6L)
    tcltk::tkpack(tcltk::tkbutton(action_bar, text = "Cancel", command = cancel, background = "white", foreground = "#46546A", relief = "solid", borderwidth = 1L, padx = 20L, pady = 8L), side = "right", padx = 6L)
    tcltk::tkwm.protocol(window, "WM_DELETE_WINDOW", cancel)
    tcltk::tkfocus(window)
    tcltk::tkwait.window(window)
    if (is.null(result)) stop("Desktop GUI cancelled.", call. = FALSE)
    result
}

cli<-visium_parse_cli()
if (requireNamespace("future", quietly = TRUE)) future::plan(future::sequential)
if(isTRUE(cli$help)){visium_print_help("Script 4 - Expression-Based Clustering and Spatial Visualization","Rscript 4.Spatial_Clustering_Rscript.R [--gui|--cli] [options]",c("--gui  Open colored native desktop GUI.","--cli  Run headlessly.","--results-dir PATH  Results/SampleName folder.","--input-rds PATH  Required Step 3 QC-filtered normalized Seurat RDS.","--number-pcs INT","--dims-to-use 1:30","--cluster-resolutions CSV  Example: 0.4,0.8.","--worker-processes INT  Parallel R processes; 1 disables parallel processing.","--random-seed INT","--cluster-colors auto|CSV","--export-cluster-markers BOOL","--top-marker-genes-per-cluster INT","--cluster-annotation-file PATH  Tab-delimited Cluster_Number / Cluster_Name file.","--cluster-rds-to-update PATH  Exact Step 4 _Clstr0.xx.rds target.","--update-cluster-names-only BOOL  Update the selected Step 4 RDS without rerunning analysis."));quit(save="no",status=0L,runLast=FALSE)}
CLUSTER_RESOLUTION_CHOICES<-sprintf("%.2f",seq(0.05,1.00,by=0.05))
AVAILABLE_CORES<-max(1L,parallel::detectCores(logical=TRUE));DEFAULT_WORKER_PROCESSES<-max(1L,min(4L,AVAILABLE_CORES-1L))
defaults<-list(results_dir=visium_default_results_workspace(PIPELINE_DIRECTORY),input_rds="",number_pcs=50L,dims_to_use="1:30",cluster_resolutions="0.40",worker_processes=DEFAULT_WORKER_PROCESSES,random_seed=12345L,cluster_colors="auto",export_cluster_markers=TRUE,top_marker_genes_per_cluster=20L,cluster_annotation_file="",cluster_rds_to_update="")
run_gui<-interactive()||!length(commandArgs(TRUE))||isTRUE(cli$gui);if(isTRUE(cli$cli))run_gui<-FALSE
if(run_gui){gui<-visium_desktop_gui("Script 4 - Expression-Based Clustering and Spatial Visualization",list(
list(name="results_dir",label="Sample results folder (Results/SampleName)",value=defaults$results_dir,type="directory",group="FILES — SELECT YOUR RESULTS FOLDER",required=TRUE,must_exist=TRUE,hide_in_panels=TRUE),
list(name="input_rds",label="Step 03 QC-filtered normalized Seurat RDS",value=defaults$input_rds,type="file",group="FILES — SELECT INPUT SEURAT RDS",hide_in_panels=TRUE),
list(name="number_pcs",label="Principal components to calculate",value=50,type="integer",group="Clustering"),list(name="dims_to_use",label="PC dimensions used (for example 1:30)",value="1:30",type="text",group="Clustering"),list(name="cluster_resolutions",label="Clustering resolutions (select one or several)",value=defaults$cluster_resolutions,type="multichoice",choices=CLUSTER_RESOLUTION_CHOICES,group="Clustering",required=TRUE),list(name="random_seed",label="Random seed for reproducibility",value=12345,type="integer",group="Clustering"),
list(name="cluster_help_assay",type="info",group="Clustering guidance",text="Assay selection is automatic: the SCT assay is used when present; otherwise the Spatial assay is scaled and used."),
list(name="cluster_help_pcs",type="info",group="Clustering guidance",text="Principal components to calculate (RunPCA npcs) sets the size of the PCA representation. It must cover the highest PC requested in the dimensions setting."),
list(name="cluster_help_dims",type="info",group="Clustering guidance",text="PC dimensions used controls FindNeighbors and RunUMAP. Fewer PCs emphasize broad structure; more PCs can retain subtle biological variation but may also introduce noise. Values above the calculated PCA count are omitted."),
list(name="cluster_help_resolution",type="info",group="Clustering guidance",text="Click each desired resolution to toggle it on or off; every highlighted value will run. Ctrl/Shift is not required. The list runs from 0.05 to 1.00 in 0.05 steps. Each selected resolution creates its own folder such as 4_Clustering/Cluster0.4, diagnostics, and Seurat RDS tagged _Clstr0.40."),
list(name="cluster_help_seed",type="info",group="Clustering guidance",text="Random seed makes graph clustering and UMAP initialization reproducible when the same input and settings are used."),
list(name="worker_processes",label=paste0("Worker processes (available logical cores: ",AVAILABLE_CORES,")"),value=defaults$worker_processes,type="integer",group="Performance",required=TRUE),
list(name="worker_help",type="info",group="Performance",text="Uses separate R worker processes for Seurat operations that support parallel execution, including UMAP and marker-gene calculations. More workers can be faster but each worker may require additional memory. The default is limited to 4 workers to avoid excessive RAM use."),
list(name="export_cluster_markers",label="Export top marker Feature_Genes for each cluster",value=defaults$export_cluster_markers,type="boolean",group="Cluster names and marker genes"),list(name="top_marker_genes_per_cluster",label="Top marker Feature_Genes per cluster",value=defaults$top_marker_genes_per_cluster,type="integer",group="Cluster names and marker genes"),
list(name="cluster_annotation_file",label="Cluster number-to-name table",value=defaults$cluster_annotation_file,type="file",group="Cluster names and marker genes"),
list(name="cluster_rds_to_update",label="Seurat object to update (Step 4 _Clstr0.xx.rds)",value=defaults$cluster_rds_to_update,type="file",group="Cluster names and marker genes",initial_directory_source="results_dir",initial_subdirectory="Seurat_RDS"),
list(name="update_cluster_names_button",label="UPDATE CLUSTER NAMES IN SEURAT RDS",type="action",action="update_cluster_names",group="Cluster names and marker genes",background="#1565C0"),
list(name="cluster_annotation_help",type="info",group="Cluster names and marker genes",text="Tabulated file with headers Cluster_Number and Cluster_Name. Example: Cluster_Number<TAB>Cluster_Name; 0<TAB>Epithelial; 1<TAB>Fibroblasts. Select the exact Step 4 _Clstr0.xx.rds target and the name file, then click UPDATE CLUSTER NAMES IN SEURAT RDS. This updates that RDS without rerunning the analysis."),
list(name="cluster_marker_help",type="info",group="Cluster names and marker genes",text="Marker-gene export is enabled by default. RUN ANALYSIS writes all positive marker Feature_Genes plus the best N marker Feature_Genes for each cluster, inside each Cluster0.xx result folder. Because the same expression data define the clusters and test their markers, marker P values are exploratory evidence for annotation, not independent biological confirmation.")
),accent="#E76F51");cli<-modifyList(cli,gui)}
if (is.null(cli$cluster_resolutions) && !is.null(cli$cluster_resolution)) cli$cluster_resolutions <- cli$cluster_resolution
RESULTS_WORKSPACE<-visium_validate_results_workspace(visium_option(cli,"results-dir",defaults$results_dir,"path"));INPUT_DIRECTORY<-normalizePath(file.path(RESULTS_WORKSPACE,"3_Normalization"),winslash="/",mustWork=FALSE);OUTPUT_DIRECTORY<-visium_stage_directory(RESULTS_WORKSPACE,"4_Clustering",create=TRUE);INPUT_RDS_OPTION<-visium_option(cli,"input-rds",defaults$input_rds,"path");NUMBER_PCS<-visium_option(cli,"number-pcs",50,"integer");DIMS_TO_USE<-visium_option(cli,"dims-to-use","1:30","dims");CLUSTER_RESOLUTIONS<-visium_resolutions(visium_option(cli,"cluster-resolutions",defaults$cluster_resolutions,"csv"),"Clustering resolutions");WORKER_PROCESSES<-visium_option(cli,"worker-processes",defaults$worker_processes,"integer");RANDOM_SEED<-visium_option(cli,"random-seed",12345,"integer");CLUSTER_COLOR_SPEC<-visium_option(cli,"cluster-colors","auto","csv");EXPORT_CLUSTER_MARKERS<-visium_option(cli,"export-cluster-markers",defaults$export_cluster_markers,"boolean");TOP_MARKER_GENES_PER_CLUSTER<-visium_option(cli,"top-marker-genes-per-cluster",defaults$top_marker_genes_per_cluster,"integer");CLUSTER_ANNOTATION_FILE<-visium_option(cli,"cluster-annotation-file",defaults$cluster_annotation_file,"path");CLUSTER_RDS_TO_UPDATE<-visium_option(cli,"cluster-rds-to-update",defaults$cluster_rds_to_update,"path");UPDATE_CLUSTER_NAMES_ONLY<-visium_option(cli,"update-cluster-names-only",FALSE,"boolean")
if(!(length(CLUSTER_COLOR_SPEC)==1L&&tolower(CLUSTER_COLOR_SPEC)=="auto"))visium_colors(CLUSTER_COLOR_SPEC,"Cluster colors")
if (NUMBER_PCS < 2L) stop("Principal components to calculate must be at least 2.")
if (!length(DIMS_TO_USE) || any(DIMS_TO_USE < 1L)) stop("PC dimensions must contain positive integers.")
if (!length(CLUSTER_RESOLUTIONS) || any(CLUSTER_RESOLUTIONS <= 0)) stop("At least one clustering resolution must be greater than 0.")
if (WORKER_PROCESSES < 1L || WORKER_PROCESSES > AVAILABLE_CORES) stop("Worker processes must be between 1 and ", AVAILABLE_CORES, ".")
if (TOP_MARKER_GENES_PER_CLUSTER < 1L) stop("Top marker Feature_Genes per cluster must be at least 1.")
if (nzchar(CLUSTER_ANNOTATION_FILE) && !file.exists(CLUSTER_ANNOTATION_FILE)) stop("Cluster-name tabulated text file does not exist: ", CLUSTER_ANNOTATION_FILE)
if (nzchar(CLUSTER_RDS_TO_UPDATE) && !file.exists(CLUSTER_RDS_TO_UPDATE)) stop("Step 4 clustered Seurat RDS does not exist: ", CLUSTER_RDS_TO_UPDATE)

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
cat("Clustering resolutions:", paste(vapply(CLUSTER_RESOLUTIONS, visium_resolution_label, character(1)), collapse = ", "), "\n")
cat("Worker processes:", WORKER_PROCESSES, "of", AVAILABLE_CORES, "available logical cores\n")
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

require_packages(c("Seurat", "SeuratObject", "ggplot2", "patchwork", "future", "future.apply"))
library(Seurat)
library(ggplot2)
library(patchwork)

read_cluster_name_table <- function(path) {
    if (!nzchar(path)) return(setNames(character(0), character(0)))
    first_line <- readLines(path, n = 1L, warn = FALSE)
    separator <- if (length(first_line) && grepl("\t", first_line, fixed = TRUE)) "\t" else if (length(first_line) && grepl(";", first_line, fixed = TRUE)) ";" else ","
    annotation_table <- tryCatch(read.delim(path, header = TRUE, sep = separator, check.names = FALSE, stringsAsFactors = FALSE, comment.char = "", quote = ""), error = function(e) stop("Could not read cluster-name file: ", conditionMessage(e)))
    if (nrow(annotation_table) < 1L || ncol(annotation_table) < 2L) stop("Cluster-name file must contain at least two columns and one data row.")
    normalized_headers <- gsub("[^a-z0-9]+", "", tolower(colnames(annotation_table)))
    cluster_index <- match(c("clusternumber", "clusterid", "seuratclusters", "cluster"), normalized_headers, nomatch = 0L)
    name_index <- match(c("clustername", "clusterlabel", "annotation", "name"), normalized_headers, nomatch = 0L)
    cluster_index <- cluster_index[cluster_index > 0L]
    name_index <- name_index[name_index > 0L]
    if (!length(cluster_index) || !length(name_index)) stop("Cluster-name file requires the headers Cluster_Number and Cluster_Name. Headers found: ", paste(colnames(annotation_table), collapse = ", "))
    cluster_values <- trimws(as.character(annotation_table[[cluster_index[[1L]]]]))
    name_values <- trimws(as.character(annotation_table[[name_index[[1L]]]]))
    keep <- nzchar(cluster_values) & nzchar(name_values) & !is.na(cluster_values) & !is.na(name_values)
    if (!any(keep)) stop("Cluster-name file contains no usable Cluster_Number / Cluster_Name values.")
    mapping <- stats::setNames(name_values[keep], cluster_values[keep])
    if (anyDuplicated(names(mapping))) stop("Cluster-name file contains duplicated Cluster_Number values.")
    mapping
}

CLUSTER_NAME_MAPPING <- read_cluster_name_table(CLUSTER_ANNOTATION_FILE)

if (isTRUE(UPDATE_CLUSTER_NAMES_ONLY)) {
    if (!length(CLUSTER_NAME_MAPPING)) stop("Select a tabulated cluster-name file before updating the Seurat RDS.")
    if (nzchar(CLUSTER_RDS_TO_UPDATE)) {
        target_rds_files <- normalizePath(CLUSTER_RDS_TO_UPDATE, winslash = "/", mustWork = TRUE)
        if (!grepl("_S04_.*_Clstr[0-9.]+\\.rds$", basename(target_rds_files), ignore.case = TRUE)) stop("Select a Step 4 clustered RDS whose filename ends with _Clstr0.xx.rds: ", target_rds_files)
    } else {
        selected_rds_labels <- vapply(CLUSTER_RESOLUTIONS, visium_resolution_rds_label, character(1))
        all_step4_rds <- list.files(
            visium_rds_directory(RESULTS_WORKSPACE, create = FALSE),
            pattern = "_S04_.*_Clstr[0-9.]+\\.rds$",
            full.names = TRUE,
            ignore.case = TRUE
        )
        target_rds_files <- all_step4_rds[vapply(all_step4_rds, function(path) {
            any(endsWith(tolower(basename(path)), tolower(paste0("_Clstr", selected_rds_labels, ".rds"))))
        }, logical(1))]
        if (!length(target_rds_files)) stop("No Step 4 clustered Seurat RDS is available to rename. Run the clustering analysis first, then select the created _Clstr0.xx.rds file.")
    }

    updated_rds_files <- character(length(target_rds_files))
    for (target_index in seq_along(target_rds_files)) {
        target_rds <- target_rds_files[[target_index]]
        cat("\nUpdating cluster names in:", target_rds, "\n")
        update_object <- readRDS(target_rds)
        if (!"seurat_clusters" %in% colnames(update_object[[]])) stop("The Step 4 RDS has no seurat_clusters metadata column: ", target_rds)
        update_cluster_ids <- as.character(update_object$seurat_clusters)
        updated_names <- unname(CLUSTER_NAME_MAPPING[update_cluster_ids])
        unmatched <- is.na(updated_names) | !nzchar(updated_names)
        if (all(unmatched)) stop("None of the Cluster_Number values in the name file match the Seurat clusters in: ", target_rds)
        if ("Cluster_Name" %in% colnames(update_object[[]])) {
            previous_names <- as.character(update_object$Cluster_Name)
        } else {
            previous_names <- paste0("Cluster_", update_cluster_ids)
        }
        updated_names[unmatched] <- previous_names[unmatched]

        rds_resolution_label <- sub("^.*_Clstr([0-9.]+)\\.rds$", "\\1", basename(target_rds), ignore.case = TRUE)
        cluster_name_column <- paste0("Cluster_Name_Resolution_", gsub("\\.", "_", rds_resolution_label))
        update_object[[cluster_name_column]] <- factor(updated_names)
        update_object[["Cluster_Name"]] <- factor(updated_names)
        saveRDS(update_object, target_rds, compress = FALSE)
        updated_rds_files[[target_index]] <- target_rds

        applied_names <- unique(data.frame(
            Cluster_Number = update_cluster_ids,
            Cluster_Name = updated_names,
            stringsAsFactors = FALSE
        ))
        applied_names <- applied_names[order(suppressWarnings(as.numeric(applied_names$Cluster_Number)), applied_names$Cluster_Number), , drop = FALSE]
        resolution_directory <- file.path(OUTPUT_DIRECTORY, paste0("Cluster", visium_resolution_label(as.numeric(rds_resolution_label))))
        dir.create(resolution_directory, recursive = TRUE, showWarnings = FALSE)
        write.csv(applied_names, file.path(resolution_directory, "Cluster_Names_Applied.csv"), row.names = FALSE)
        if (any(unmatched)) warning(sum(unmatched), " spots retained their previous Cluster_Name because their cluster number was absent from the name file.")
    }

    save_session_information()
    cat("\nCluster names updated successfully in Seurat RDS file(s):\n", paste(updated_rds_files, collapse = "\n"), "\n", sep = "")
} else {
if (!nzchar(INPUT_RDS_OPTION)) stop("Select the Step 03 QC-filtered normalized Seurat RDS with the Browse button before running clustering.")
if (!file.exists(INPUT_RDS_OPTION) || isTRUE(file.info(INPUT_RDS_OPTION)$isdir)) stop("Selected Step 03 Seurat RDS does not exist: ", INPUT_RDS_OPTION)
INPUT_RDS_FILE <- normalizePath(INPUT_RDS_OPTION, winslash = "/", mustWork = TRUE)
if (!grepl("_S03_QCfilt_Norm(SCT|Log)\\.rds$", basename(INPUT_RDS_FILE), ignore.case = TRUE)) {
    stop(
        "Select a Step 03 QC-filtered normalized RDS whose filename ends with ",
        "_S03_QCfilt_NormSCT.rds or _S03_QCfilt_NormLog.rds.\nSelected: ",
        basename(INPUT_RDS_FILE)
    )
}
INHERITED_RDS_TAGS <- visium_rds_operation_tags(INPUT_RDS_FILE, "S03")

previous_future_max_size <- getOption("future.globals.maxSize")
on.exit({
    future::plan(future::sequential)
    options(future.globals.maxSize = previous_future_max_size)
}, add = TRUE)
future_max_size <- max(8 * 1024^3, as.numeric(file.info(INPUT_RDS_FILE)$size) * max(4, WORKER_PROCESSES))
options(future.globals.maxSize = future_max_size)
cat("future.globals.maxSize:", round(future_max_size / 1024^3, 2), "GiB\n")

object <- readRDS(INPUT_RDS_FILE)

set.seed(RANDOM_SEED)
analysis_assay <- if ("SCT" %in% Assays(object)) "SCT" else "Spatial"
DefaultAssay(object) <- analysis_assay

if (analysis_assay == "Spatial" && !"scale.data" %in% Layers(object[["Spatial"]])) {
    object <- ScaleData(object, assay = "Spatial", verbose = TRUE)
}

object <- RunPCA(object, assay = analysis_assay, npcs = NUMBER_PCS, verbose = TRUE)
valid_dims <- DIMS_TO_USE[DIMS_TO_USE <= ncol(Embeddings(object, "pca"))]
if (!length(valid_dims)) stop("None of the requested PC dimensions are available after PCA.")
object <- FindNeighbors(object, reduction = "pca", dims = valid_dims)
if (WORKER_PROCESSES > 1L) {
    future::plan(future::multisession, workers = WORKER_PROCESSES)
} else {
    future::plan(future::sequential)
}
cat("Future plan started immediately before UMAP:", if (WORKER_PROCESSES > 1L) "multisession" else "sequential", "with", future::nbrOfWorkers(), "worker process(es)\n")
object <- RunUMAP(object, reduction = "pca", dims = valid_dims, seed.use = RANDOM_SEED)

clustering_base_object <- object
resolution_summary <- vector("list", length(CLUSTER_RESOLUTIONS))
output_rds_files <- character(length(CLUSTER_RESOLUTIONS))

for (resolution_index in seq_along(CLUSTER_RESOLUTIONS)) {
    clustering_resolution <- CLUSTER_RESOLUTIONS[[resolution_index]]
    resolution_label <- visium_resolution_label(clustering_resolution)
    resolution_rds_label <- visium_resolution_rds_label(clustering_resolution)
    resolution_directory <- file.path(OUTPUT_DIRECTORY, paste0("Cluster", resolution_label))
    dir.create(resolution_directory, recursive = TRUE, showWarnings = FALSE)

    cat("\nClustering resolution ", resolution_label, "\n", sep = "")
    resolution_object <- FindClusters(clustering_base_object, resolution = clustering_resolution, random.seed = RANDOM_SEED)
    resolution_column <- paste0("Cluster_Resolution_", gsub("\\.", "_", resolution_rds_label))
    resolution_object[[resolution_column]] <- factor(resolution_object$seurat_clusters)

    cluster_ids <- as.character(resolution_object$seurat_clusters)
    mapped_names <- unname(CLUSTER_NAME_MAPPING[cluster_ids])
    mapped_names[is.na(mapped_names) | !nzchar(mapped_names)] <- paste0("Cluster_", cluster_ids[is.na(mapped_names) | !nzchar(mapped_names)])
    cluster_name_column <- paste0("Cluster_Name_Resolution_", gsub("\\.", "_", resolution_rds_label))
    resolution_object[[cluster_name_column]] <- factor(mapped_names)

    resolution_object[["Cluster_Name"]] <- factor(mapped_names)
    display_column <- cluster_name_column
    display_values <- as.character(resolution_object[[display_column]][, 1L])
    display_levels <- levels(factor(display_values))
    cluster_colors <- if (length(CLUSTER_COLOR_SPEC) == 1L && tolower(CLUSTER_COLOR_SPEC) == "auto") {
        grDevices::hcl.colors(length(display_levels), "Dark 3")
    } else {
        if (length(CLUSTER_COLOR_SPEC) < length(display_levels)) stop("Not enough cluster colors for resolution ", resolution_label, ".")
        CLUSTER_COLOR_SPEC[seq_along(display_levels)]
    }
    names(cluster_colors) <- display_levels

    annotation_report <- unique(data.frame(
        Cluster_Number = cluster_ids,
        Cluster_Name = mapped_names,
        stringsAsFactors = FALSE
    ))
    annotation_report <- annotation_report[order(suppressWarnings(as.numeric(annotation_report$Cluster_Number)), annotation_report$Cluster_Number), , drop = FALSE]
    write.csv(annotation_report, file.path(resolution_directory, "Cluster_Names_Applied.csv"), row.names = FALSE)

    umap_plot <- DimPlot(resolution_object, reduction = "umap", group.by = display_column, label = TRUE, repel = TRUE, cols = cluster_colors) +
        ggtitle(paste0("Spatial spots in UMAP space (resolution ", resolution_label, ")"))
    ggsave(file.path(resolution_directory, "UMAP_Cluster_Groups.png"), umap_plot, width = 10, height = 8, dpi = 300)

    for (image_name in Images(resolution_object)) {
        spatial_plot <- SpatialDimPlot(resolution_object, images = image_name, group.by = display_column, label = TRUE, repel = TRUE, cols = cluster_colors)
        safe_name <- gsub("[^A-Za-z0-9_.-]", "_", image_name)
        ggsave(file.path(resolution_directory, paste0("Spatial_Cluster_Groups_", safe_name, ".png")), spatial_plot, width = 10, height = 9, dpi = 300)
    }

    cluster_counts <- as.data.frame(table(
        Cluster_Number = cluster_ids,
        Cluster_Name = mapped_names
    ), stringsAsFactors = FALSE)
    names(cluster_counts)[3L] <- "Count_Spots"
    write.csv(cluster_counts, file.path(resolution_directory, "Cluster_Count_Spots.csv"), row.names = FALSE)
    spot_assignments <- data.frame(
        Spot_Barcode = colnames(resolution_object),
        Cluster_Number = cluster_ids,
        Cluster_Name = mapped_names,
        stringsAsFactors = FALSE
    )
    write.csv(spot_assignments, file.path(resolution_directory, "Spot_Cluster_Assignments.csv"), row.names = FALSE)

    if (isTRUE(EXPORT_CLUSTER_MARKERS)) {
        cat("Exporting marker Feature_Genes for resolution ", resolution_label, "\n", sep = "")
        DefaultAssay(resolution_object) <- analysis_assay
        resolution_object <- tryCatch(JoinLayers(resolution_object), error = function(e) resolution_object)
        Idents(resolution_object) <- resolution_column
        marker_clusters <- levels(Idents(resolution_object))
        marker_worker_count <- min(WORKER_PROCESSES, length(marker_clusters))
        if (marker_worker_count != future::nbrOfWorkers()) {
            if (marker_worker_count > 1L) future::plan(future::multisession, workers = marker_worker_count) else future::plan(future::sequential)
        }
        cat("Parallel marker calculation:", length(marker_clusters), "clusters across up to", marker_worker_count, "worker process(es)\n")
        marker_results <- future.apply::future_lapply(
            marker_clusters,
            function(cluster_id) {
                cluster_markers <- Seurat::FindMarkers(
                    resolution_object,
                    assay = analysis_assay,
                    ident.1 = cluster_id,
                    only.pos = TRUE,
                    min.pct = 0.10,
                    logfc.threshold = 0.25,
                    random.seed = RANDOM_SEED,
                    verbose = FALSE
                )
                if (nrow(cluster_markers)) {
                    cluster_markers$Feature_Gene <- rownames(cluster_markers)
                    cluster_markers$cluster <- cluster_id
                    rownames(cluster_markers) <- NULL
                }
                list(markers = cluster_markers, process_id = Sys.getpid())
            },
            future.seed = RANDOM_SEED,
            future.packages = c("Seurat", "SeuratObject"),
            future.scheduling = Inf
        )
        marker_process_ids <- unique(vapply(marker_results, function(x) as.integer(x$process_id), integer(1)))
        cat("Marker worker process IDs:", paste(marker_process_ids, collapse = ", "), "\n")
        marker_tables <- lapply(marker_results, `[[`, "markers")
        marker_tables <- marker_tables[vapply(marker_tables, nrow, integer(1)) > 0L]
        marker_table <- if (length(marker_tables)) do.call(rbind, marker_tables) else data.frame()
        if (nrow(marker_table)) {
            logfc_column <- intersect(c("avg_log2FC", "avg_logFC"), names(marker_table))
            if (!length(logfc_column)) stop("The installed Seurat version did not return a log-fold-change column for marker Feature_Genes.")
            marker_table <- marker_table[order(marker_table$cluster, marker_table$p_val_adj, -marker_table[[logfc_column[[1L]]]]), , drop = FALSE]
            write.csv(marker_table, file.path(resolution_directory, "Cluster_Marker_Feature_Genes_All.csv"), row.names = FALSE)
            top_markers <- do.call(rbind, lapply(split(marker_table, marker_table$cluster), function(x) head(x, TOP_MARKER_GENES_PER_CLUSTER)))
            write.csv(top_markers, file.path(resolution_directory, "Cluster_Top_Marker_Feature_Genes.csv"), row.names = FALSE)
        } else {
            write.csv(marker_table, file.path(resolution_directory, "Cluster_Marker_Feature_Genes_All.csv"), row.names = FALSE)
            write.csv(marker_table, file.path(resolution_directory, "Cluster_Top_Marker_Feature_Genes.csv"), row.names = FALSE)
        }
    }

    output_rds_file <- visium_tagged_rds_path(
        RESULTS_WORKSPACE, "4_Clustering", "S04",
        paste0(INHERITED_RDS_TAGS, "_Clstr", resolution_rds_label)
    )
    saveRDS(resolution_object, output_rds_file, compress = FALSE)
    output_rds_files[[resolution_index]] <- output_rds_file

    resolution_summary[[resolution_index]] <- data.frame(
        Clustering_Resolution = resolution_label,
        Count_Clusters = length(unique(cluster_ids)),
        Count_Spots = length(cluster_ids),
        Output_RDS = output_rds_file,
        Result_Folder = resolution_directory,
        stringsAsFactors = FALSE
    )

    if (length(CLUSTER_RESOLUTIONS) == 1L) {
        ggsave(file.path(OUTPUT_DIRECTORY, "spatial_UMAP_clusters.png"), umap_plot, width = 10, height = 8, dpi = 300)
        write.csv(cluster_counts, file.path(OUTPUT_DIRECTORY, "spatial_cluster_counts.csv"), row.names = FALSE)
    }
}

write.csv(do.call(rbind, resolution_summary), file.path(OUTPUT_DIRECTORY, "Clustering_Resolutions_Summary.csv"), row.names = FALSE)

future::plan(future::sequential)
cat("Parallel worker processes stopped.\n")
save_session_information()
cat("\nSpatial dimensionality reduction and clustering completed.\nOutput object(s):\n", paste(output_rds_files, collapse = "\n"), "\n", sep = "")
}
