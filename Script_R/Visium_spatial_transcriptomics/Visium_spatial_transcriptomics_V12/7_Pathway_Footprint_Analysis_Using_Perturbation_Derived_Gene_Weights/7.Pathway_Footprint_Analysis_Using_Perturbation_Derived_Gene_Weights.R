

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

visium_safe_sample_name <- function(sample_name) {
    sample_name <- trimws(as.character(sample_name)[1L])
    sample_name <- gsub("[^A-Za-z0-9._-]+", "_", sample_name)
    sample_name <- gsub("^[_ .-]+|[_ .-]+$", "", sample_name)
    if (!nzchar(sample_name)) stop("Sample name must contain at least one letter or number.")
    sample_name
}

visium_create_results_workspace <- function(results_parent, sample_name) {
    results_parent <- trimws(as.character(results_parent)[1L])
    if (!nzchar(results_parent) || !dir.exists(results_parent)) {
        stop("Selected Results parent folder does not exist: ", results_parent)
    }
    sample_name <- visium_safe_sample_name(sample_name)
    workspace <- file.path(results_parent, sample_name)
    dir.create(file.path(workspace, "Seurat_RDS"), recursive = TRUE, showWarnings = FALSE)
    normalizePath(workspace, winslash = "/", mustWork = TRUE)
}

visium_validate_results_workspace <- function(workspace, must_exist = TRUE) {
    workspace <- trimws(as.character(workspace)[1L])
    if (!nzchar(workspace)) stop("Select the sample results folder, for example Results/Sample_01.")
    if (must_exist && !dir.exists(workspace)) stop("Sample results folder does not exist: ", workspace)
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
    x <- trimws(as.character(x)[1L])
    if (!nzchar(x)) {
        if (empty) return(character(0))
        stop(label, " cannot be empty.", call. = FALSE)
    }
    z <- trimws(strsplit(x, ",", fixed = TRUE)[[1L]])
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

SCRIPT7_CLI <- visium_parse_cli()
if (isTRUE(SCRIPT7_CLI$help)) {
    visium_print_help(
        "Script 7 - Pathway Footprint Analysis",
        "Rscript 7.Pathway_Footprint_Analysis_Using_Perturbation_Derived_Gene_Weights_v3.R [--gui|--cli] [options]",
        c(
            "--gui  Open the colored native desktop GUI.", "--cli  Run headlessly.",
            "--results-dir PATH  Required sample results folder, for example Results/Sample_01.",
            "--input-rds PATH  Required Step 6 deconvolution/region-DE Seurat RDS.",
            "--fingerprint-database PATH  Optional custom pathway database.",
            "--organism NAME (Human/Mouse use PROGENy; others use matching fingerprint rows)",
            "--source NAME (All sources|PROGENy|a fingerprint Source)", "--pathways all|CSV", "--top-genes INT",
            "--assay NAME", "--layer NAME", "--tissue-normalization NAME",
            "--lower-quantile NUMBER", "--upper-quantile NUMBER",
            "--minimum-genes-present INT", "--minimum-coverage NUMBER",
            "--primary-correlation Spearman|Pearson",
            "--significance-source 'Empirical weight permutation'|'Classical correlation P (fast)'",
            "--permutations INT", "--fdr-scope NAME",
            "--use-correlation-threshold BOOL", "--correlation-threshold NUMBER",
            "--use-significance-p-threshold BOOL", "--significance-p-threshold NUMBER",
            "--use-fdr-threshold BOOL", "--fdr-threshold NUMBER",
            "--use-activity-threshold BOOL", "--activity-percentile-threshold NUMBER",
            "--use-spatial-filter BOOL", "--minimum-adjacent-spots INT",
            "--adjacency-mode NAME", "--distance-multiplier NUMBER", "--random-seed INT",
            "--parallelize-pathways BOOL", "--cpu-cores INT",
            "--output-primary-activity-only BOOL  Save only fluorescent-green threshold-passing spatial image per pathway.",
            "--save-debug-matrices BOOL  Save detailed technical audit tables and pathway-by-spot matrices (default FALSE).",
            "--export-most-represented-pathways BOOL  Save pathways with retained high-relative-activity regions (default TRUE; legacy option name)."
        )
    )
    quit(save = "no", status = 0L, runLast = FALSE)
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
    tcltk::tkgrid.rowconfigure(window, 1L, weight = 1L)

    hero <- tcltk::tkframe(window, background = accent, relief = "flat", borderwidth = 0L)
    tcltk::tkgrid(hero, row = 0L, column = 0L, sticky = "ew")
    tcltk::tkpack(tcltk::tklabel(hero, text = title, background = accent, foreground = "white", font = "TkHeadingFont", anchor = "w", padx = 22L, pady = 9L), fill = "x")
    tcltk::tkpack(tcltk::tklabel(hero, text = "Scores pathway footprints and maps supported activity across tissue spots.", background = accent, foreground = "white", anchor = "w", padx = 22L, pady = 4L), fill = "x")

    viewport <- tcltk::tkframe(window, background = "#F4F7FB")
    tcltk::tkgrid(viewport, row = 1L, column = 0L, sticky = "nsew")
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
    multi_widgets <- list()
    multi_choices <- list()
    dependent_refreshers <- list()
    refresh_dependents <- function(source_name, show_error = TRUE) {
        for (dependent in dependent_refreshers) {
            if (source_name %in% dependent$sources) try(dependent$refresh(show_error), silent = TRUE)
        }
        invisible(NULL)
    }

    groups <- unique(vapply(fields, function(f) if (is.null(f$group)) "Settings" else f$group, character(1)))
    regular_panel_index <- 0L
    for (group in groups) {
        subset <- fields[vapply(fields, function(f) identical(if (is.null(f$group)) "Settings" else f$group, group), logical(1))]
        is_files_panel <- identical(tolower(group), "files") || any(vapply(subset, function(f) f$type %in% c("file", "directory"), logical(1)))
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
                    if (identical(f$action, "run")) run() else if (is.function(f$command)) f$command()
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
                        selectmode = "extended",
                        exportselection = FALSE,
                        height = if (isTRUE(f$popup_selector)) min(14L, max(8L, length(f$choices))) else min(7L, max(3L, length(f$choices))),
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

                    selected_multichoice <- function() {
                        indices <- suppressWarnings(as.integer(strsplit(trimws(tcltk::tclvalue(tcltk::tcl(listbox, "curselection"))), "\\s+")[[1L]]))
                        indices <- indices[is.finite(indices)] + 1L
                        choices <- multi_choices[[f$name]]
                        choices[indices[indices >= 1L & indices <= length(choices)]]
                    }

                    set_multichoice_selection <- function(selected) {
                        choices <- multi_choices[[f$name]]
                        selected <- intersect(selected, choices)
                        tcltk::tcl(listbox, "selection", "clear", 0L, "end")
                        for (index in match(selected, choices, nomatch = 0L)) {
                            if (index > 0L) tcltk::tcl(listbox, "selection", "set", index - 1L)
                        }
                        tcltk::tclvalue(variable) <- paste(selected, collapse = ",")
                        invisible(selected)
                    }

                    click_index <- tcltk::tclVar("-1")
                    toggle_pathway_selection <- function() {
                        index <- suppressWarnings(as.integer(tcltk::tclvalue(click_index)))
                        choices <- multi_choices[[f$name]]
                        if (!is.finite(index) || index < 0L || index >= length(choices)) return(invisible(NULL))

                        clicked <- choices[[index + 1L]]
                        current <- selected_multichoice()
                        individual_choices <- setdiff(choices, "all")
                        if ("all" %in% current) current <- individual_choices

                        if (identical(clicked, "all")) {
                            selected <- if (length(current) == length(individual_choices)) character(0) else individual_choices
                        } else if (clicked %in% current) {
                            selected <- setdiff(current, clicked)
                        } else {
                            selected <- unique(c(current, clicked))
                        }

                        selected_for_list <- if (length(individual_choices) && length(selected) == length(individual_choices) && "all" %in% choices) "all" else selected
                        set_multichoice_selection(selected_for_list)
                        invisible(NULL)
                    }
                    listbox$env$pathway_click_index <- click_index
                    listbox$env$pathway_toggle_callback <- toggle_pathway_selection
                    toggle_callback_command <- tcltk::.Tcl.callback(toggle_pathway_selection)
                    toggle_binding_script <- paste0(
                        "if {!(%s & 0x0001)} {set ", as.character(click_index),
                        " [%W nearest %y]; ", toggle_callback_command, "; break}"
                    )
                    tcltk::tkbind(listbox, "<Button-1>", toggle_binding_script)

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
                        if (!length(selected) && "all" %in% choices && !isTRUE(f$allow_empty_selection)) selected <- "all"
                        set_multichoice_selection(selected)
                        invisible(choices)
                    }

                    populate_multichoice(f$choices)
                    multi_widgets[[f$name]] <<- listbox

                    next_control_row <- 1L
                    if (isTRUE(f$popup_selector)) {
                        open_large_selector <- function() {
                            choices <- multi_choices[[f$name]]
                            pathway_choices <- setdiff(choices, "all")
                            if (!length(pathway_choices)) {
                                tcltk::tkmessageBox(title = "No pathways", message = "No individual pathways are available to select.", icon = "info", type = "ok", parent = window)
                                return(invisible(NULL))
                            }

                            current_selection <- selected_multichoice()
                            selected_pathways <- if ("all" %in% current_selection) pathway_choices else intersect(current_selection, pathway_choices)
                            selector_window <- tcltk::tktoplevel(background = "#F4F7FB")
                            tcltk::tkwm.title(selector_window, paste0(f$label, " - Select pathways"))
                            tcltk::tkwm.geometry(selector_window, "1040x720")
                            tcltk::tkgrid.columnconfigure(selector_window, 0L, weight = 1L)
                            tcltk::tkgrid.rowconfigure(selector_window, 1L, weight = 1L)

                            header <- tcltk::tkframe(selector_window, background = accent, padx = 14L, pady = 9L)
                            tcltk::tkgrid(header, row = 0L, column = 0L, sticky = "ew")
                            tcltk::tkpack(tcltk::tklabel(header, text = "SELECT PATHWAYS", background = accent, foreground = "white", font = "TkHeadingFont", anchor = "w"), fill = "x")
                            tcltk::tkpack(tcltk::tklabel(header, text = "Click the checkboxes to select individual pathways. Ctrl is not needed. Shift selection remains available in the main list.", background = accent, foreground = "white", anchor = "w"), fill = "x", pady = c(3L, 0L))

                            viewport <- tcltk::tkframe(selector_window, background = "#F4F7FB", padx = 10L, pady = 8L)
                            tcltk::tkgrid(viewport, row = 1L, column = 0L, sticky = "nsew")
                            tcltk::tkgrid.columnconfigure(viewport, 0L, weight = 1L)
                            tcltk::tkgrid.rowconfigure(viewport, 0L, weight = 1L)
                            selector_canvas <- tcltk::tkcanvas(viewport, background = "white", highlightthickness = 0L, borderwidth = 0L)
                            selector_scrollbar <- tcltk::tkscrollbar(viewport, orient = "vertical", command = function(...) tcltk::tkyview(selector_canvas, ...))
                            tcltk::tkconfigure(selector_canvas, yscrollcommand = function(...) tcltk::tkset(selector_scrollbar, ...))
                            tcltk::tkgrid(selector_canvas, row = 0L, column = 0L, sticky = "nsew")
                            tcltk::tkgrid(selector_scrollbar, row = 0L, column = 1L, sticky = "ns")
                            selector_body <- tcltk::tkframe(selector_canvas, background = "white", padx = 12L, pady = 10L)
                            selector_body_window <- tcltk::tkcreate(selector_canvas, "window", 0L, 0L, window = selector_body, anchor = "nw")
                            update_selector_scroll <- function() {
                                bounds <- tcltk::tclvalue(tcltk::tcl(selector_canvas, "bbox", "all"))
                                if (nzchar(bounds)) tcltk::tkconfigure(selector_canvas, scrollregion = bounds)
                                invisible(NULL)
                            }
                            fit_selector_width <- function() {
                                canvas_width <- suppressWarnings(as.integer(tcltk::tclvalue(tcltk::tkwinfo("width", selector_canvas))))
                                if (is.finite(canvas_width) && canvas_width > 1L) tcltk::tcl(selector_canvas, "itemconfigure", selector_body_window, "-width", canvas_width)
                                update_selector_scroll()
                                invisible(NULL)
                            }
                            tcltk::tkbind(selector_body, "<Configure>", update_selector_scroll)
                            tcltk::tkbind(selector_canvas, "<Configure>", fit_selector_width)

                            choice_variables <- setNames(lapply(pathway_choices, function(choice) tcltk::tclVar(if (choice %in% selected_pathways) "TRUE" else "FALSE")), pathway_choices)
                            selector_columns <- min(4L, max(1L, length(pathway_choices)))
                            selector_rows <- ceiling(length(pathway_choices) / selector_columns)
                            for (index in seq_along(pathway_choices)) {
                                column_index <- (index - 1L) %/% selector_rows
                                row_index <- (index - 1L) %% selector_rows
                                tcltk::tkgrid(
                                    tcltk::tkcheckbutton(selector_body, text = pathway_choices[[index]], variable = choice_variables[[pathway_choices[[index]]]], onvalue = "TRUE", offvalue = "FALSE", background = "white", activebackground = "white", selectcolor = "white", anchor = "w"),
                                    row = row_index, column = column_index, sticky = "w", padx = 8L, pady = 2L
                                )
                            }

                            footer <- tcltk::tkframe(selector_window, background = "#E8EEF7", padx = 10L, pady = 8L)
                            tcltk::tkgrid(footer, row = 2L, column = 0L, sticky = "ew")
                            select_all <- function() {
                                for (choice in pathway_choices) tcltk::tclvalue(choice_variables[[choice]]) <- "TRUE"
                            }
                            clear_all <- function() {
                                for (choice in pathway_choices) tcltk::tclvalue(choice_variables[[choice]]) <- "FALSE"
                            }
                            apply_and_close <- function() {
                                selected <- pathway_choices[vapply(pathway_choices, function(choice) identical(tcltk::tclvalue(choice_variables[[choice]]), "TRUE"), logical(1))]
                                selected_for_list <- if (length(selected) == length(pathway_choices) && "all" %in% choices) "all" else selected
                                set_multichoice_selection(selected_for_list)
                                refresh_dependents(f$name, TRUE)
                                tcltk::tkdestroy(selector_window)
                            }
                            tcltk::tkpack(tcltk::tkbutton(footer, text = "SELECT ALL", command = select_all, background = "#455A64", foreground = "white", padx = 10L), side = "left", padx = 3L)
                            tcltk::tkpack(tcltk::tkbutton(footer, text = "CLEAR ALL", command = clear_all, background = "white", foreground = "#46546A", padx = 10L), side = "left", padx = 3L)
                            tcltk::tkpack(tcltk::tkbutton(footer, text = "CANCEL", command = function() tcltk::tkdestroy(selector_window), background = "white", foreground = "#46546A", padx = 12L), side = "right", padx = 3L)
                            tcltk::tkpack(tcltk::tkbutton(footer, text = "APPLY SELECTION AND CLOSE", command = apply_and_close, background = accent, foreground = "white", activebackground = accent, activeforeground = "white", padx = 14L), side = "right", padx = 3L)
                            tcltk::tkfocus(selector_window)
                            invisible(NULL)
                        }
                        large_selector_button <- tcltk::tkbutton(control, text = "OPEN LARGE PATHWAY SELECTOR...", command = open_large_selector, background = "#1565C0", foreground = "white", activebackground = "#0D47A1", activeforeground = "white", relief = "raised", borderwidth = 1L, padx = 8L)
                        tcltk::tkgrid(large_selector_button, row = next_control_row, column = 0L, columnspan = 2L, sticky = "ew", pady = c(4L, 0L))
                        next_control_row <- next_control_row + 1L
                    }

                    choice_sources <- if (!is.null(f$choice_sources)) f$choice_sources else f$choice_source
                    if (is.function(f$choice_loader) && length(choice_sources)) {
                        refresh_choices <- function(show_error = TRUE) {
                            preserve <- selected_multichoice()
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
                        tcltk::tkgrid(refresh_button, row = next_control_row, column = 0L, columnspan = 2L, sticky = "ew", pady = c(4L, 0L))
                    }
                } else {
                    control <- tcltk::tkentry(panel, textvariable = variable, width = if (is_inline_field) 10L else if (is_files_panel && panel_span > 1L) 62L else if (is_files_panel) 28L else if (panel_columns >= 3L) 22L else 34L, relief = "solid", borderwidth = 1L, highlightthickness = 1L, highlightcolor = accent)
                }
                tcltk::tkgrid(control, row = field_row, column = control_column, columnspan = control_span, sticky = "ew", padx = 2L, pady = 3L)

                if (f$type %in% c("file", "directory")) {
                    browse <- function() {
                        current <- tcltk::tclvalue(variable)
                        initial_dir <- if (dir.exists(current)) current else if (file.exists(current)) dirname(current) else getwd()
                        if (!dir.exists(current) && !file.exists(current) && is.function(f$browse_initial_dir)) {
                            gui_values <- setNames(
                                lapply(variables, function(item) tcltk::tclvalue(item)),
                                names(variables)
                            )
                            preferred_dir <- tryCatch(
                                as.character(f$browse_initial_dir(gui_values))[1L],
                                error = function(e) ""
                            )
                            while (nzchar(preferred_dir) && !dir.exists(preferred_dir)) {
                                parent_dir <- dirname(preferred_dir)
                                if (identical(parent_dir, preferred_dir)) break
                                preferred_dir <- parent_dir
                            }
                            if (nzchar(preferred_dir) && dir.exists(preferred_dir)) {
                                initial_dir <- preferred_dir
                            }
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
    tcltk::tkgrid(action_bar, row = 2L, column = 0L, sticky = "ew")
    tcltk::tkpack(tcltk::tklabel(action_bar, text = "* Required    Review the colored settings panels before running", background = "#E8EEF7", foreground = "#46546A"), side = "left", padx = 4L)

    cancel <- function() tcltk::tkdestroy(window)
    run <- function() {
        values <- setNames(lapply(variables, tcltk::tclvalue), names(variables))
        for (field_name in names(multi_widgets)) {
            selection_text <- trimws(tcltk::tclvalue(tcltk::tcl(multi_widgets[[field_name]], "curselection")))
            indices <- if (nzchar(selection_text)) suppressWarnings(as.integer(strsplit(selection_text, "\\s+")[[1L]]) + 1L) else integer(0)
            choices <- multi_choices[[field_name]]
            selected <- choices[indices[is.finite(indices) & indices >= 1L & indices <= length(choices)]]
            values[[field_name]] <- if ("all" %in% selected) "all" else paste(selected, collapse = ",")
        }
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

    tcltk::tkpack(tcltk::tkbutton(action_bar, text = "RUN ANALYSIS", command = run, background = accent, foreground = "white", activebackground = accent, activeforeground = "white", relief = "raised", borderwidth = 2L, padx = 28L, pady = 9L), side = "right", padx = 6L)
    tcltk::tkpack(tcltk::tkbutton(action_bar, text = "Cancel", command = cancel, background = "white", foreground = "#46546A", relief = "solid", borderwidth = 1L, padx = 20L, pady = 8L), side = "right", padx = 6L)
    tcltk::tkwm.protocol(window, "WM_DELETE_WINDOW", cancel)
    tcltk::tkfocus(window)
    tcltk::tkwait.window(window)
    if (is.null(result)) stop("Desktop GUI cancelled.", call. = FALSE)
    result
}

sanitize_name <- function(x) {
    x <- gsub("[^A-Za-z0-9_.-]", "_", as.character(x))
    x <- gsub("_+", "_", x)
    x
}

`%||%` <- function(x, y) if (is.null(x) || length(x) == 0L || is.na(x[1L]) || !nzchar(as.character(x[1L]))) y else x

as_numeric_safe <- function(x, default = NA_real_) {
    z <- suppressWarnings(as.numeric(x))
    z[!is.finite(z)] <- default
    z
}

.GUI <- new.env(parent = emptyenv())
.GUI$log_widget <- NULL
.GUI$status_var <- NULL
.GUI$progress_var <- NULL
.GUI$output_directory <- NULL

append_log <- function(...) {
    msg <- paste0(...)
    stamp <- format(Sys.time(), "%Y-%m-%d %H:%M:%S")
    line <- paste0("[", stamp, "] ", msg)
    cat(line, "\n")

    if (!is.null(.GUI$log_widget)) {
        try({
            tcltk::tkinsert(.GUI$log_widget, "end", paste0(line, "\n"))
            tcltk::tksee(.GUI$log_widget, "end")
            tcltk::tcl("update", "idletasks")
        }, silent = TRUE)
    }

    if (!is.null(.GUI$output_directory) && nzchar(.GUI$output_directory)) {
        try(cat(line, "\n", file = file.path(.GUI$output_directory, "run_log.txt"), append = TRUE), silent = TRUE)
    }
    invisible(line)
}

set_status <- function(text, progress = NULL) {
    if (!is.null(.GUI$status_var)) try(tcltk::tclvalue(.GUI$status_var) <- text, silent = TRUE)
    if (!is.null(progress) && !is.null(.GUI$progress_var)) {
        try(tcltk::tclvalue(.GUI$progress_var) <- as.numeric(progress), silent = TRUE)
    }
    try(tcltk::tcl("update", "idletasks"), silent = TRUE)
}

show_error <- function(title, message) {
    append_log("ERROR: ", message)
    try(tcltk::tkmessageBox(title = title, message = message, icon = "error", type = "ok"), silent = TRUE)
}

show_info <- function(title, message) {
    try(tcltk::tkmessageBox(title = title, message = message, icon = "info", type = "ok"), silent = TRUE)
}

cran_packages <- c("Seurat", "SeuratObject", "Matrix", "ggplot2", "scales", "matrixStats")
bioc_packages <- c("progeny")

missing_packages <- function(include_progeny = TRUE) {
    pkgs <- cran_packages
    if (include_progeny) pkgs <- c(pkgs, bioc_packages)
    pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]
}

install_missing_packages <- function() {
    missing_cran <- cran_packages[!vapply(cran_packages, requireNamespace, logical(1), quietly = TRUE)]
    if (length(missing_cran)) {
        append_log("Installing missing CRAN package(s): ", paste(missing_cran, collapse = ", "))
        install.packages(missing_cran)
    }

    missing_bioc <- bioc_packages[!vapply(bioc_packages, requireNamespace, logical(1), quietly = TRUE)]
    if (length(missing_bioc)) {
        if (!requireNamespace("BiocManager", quietly = TRUE)) install.packages("BiocManager")
        append_log("Installing missing Bioconductor package(s): ", paste(missing_bioc, collapse = ", "))
        BiocManager::install(missing_bioc, ask = FALSE, update = FALSE)
    }

    still_missing <- missing_packages(TRUE)
    if (length(still_missing)) {
        stop("The following packages are still missing: ", paste(still_missing, collapse = ", "))
    }
    show_info("Packages", "Required packages are installed.")
}

normalize_model_column_names <- function(x) {
    names(x) <- tolower(gsub("[^a-zA-Z0-9]+", "_", names(x)))
    x
}

find_column_alias <- function(nms, aliases) {
    hit <- aliases[aliases %in% nms]
    if (length(hit)) hit[1L] else NA_character_
}

normalize_direction_sign <- function(x) {
    z <- toupper(trimws(as.character(x)))
    out <- rep(NA_real_, length(z))
    out[z %in% c("UP", "+", "+1", "1", "POS", "POSITIVE", "INCREASE", "INCREASED")] <- 1
    out[z %in% c("DOWN", "-", "-1", "NEG", "NEGATIVE", "DECREASE", "DECREASED")] <- -1
    out
}

make_pathway_labels <- function(source, pathway_name, pathway_id) {
    source <- trimws(as.character(source))
    pathway_name <- trimws(as.character(pathway_name))
    pathway_id <- trimws(as.character(pathway_id))
    base <- paste0("[", source, "] ", pathway_name)

    key <- paste(source, pathway_name, sep = "\r")
    ids_per_key <- tapply(pathway_id, key, function(z) length(unique(z[nzchar(z)])))
    ambiguous <- unname(ids_per_key[key]) > 1L
    ambiguous[is.na(ambiguous)] <- FALSE
    base[ambiguous] <- paste0(base[ambiguous], " {", pathway_id[ambiguous], "}")
    base
}

load_builtin_progeny_model <- function(organism = "Human") {
    organism_key <- tolower(trimws(as.character(organism)[1L]))
    organism_label <- switch(organism_key, human = "Human", mouse = "Mouse", NULL)
    dataset_name <- switch(organism_key, human = "model_human_full", mouse = "model_mouse_full", NULL)

    if (is.null(dataset_name)) {
        append_log("No built-in PROGENy model is available for organism '", organism, "'; using organism-matched fingerprint pathways only.")
        return(NULL)
    }

    if (!requireNamespace("progeny", quietly = TRUE)) {
        stop("The Bioconductor package 'progeny' is not installed. Use 'Install/Check Packages'.")
    }

    env <- new.env(parent = emptyenv())
    suppressWarnings(utils::data(list = dataset_name, package = "progeny", envir = env))

    if (exists(dataset_name, envir = env, inherits = FALSE)) {
        model <- get(dataset_name, envir = env, inherits = FALSE)
    } else {
        model <- tryCatch(get(dataset_name, envir = asNamespace("progeny")), error = function(e) NULL)
    }
    if (is.null(model)) stop("Could not load PROGENy dataset: ", dataset_name)

    model <- as.data.frame(model, stringsAsFactors = FALSE)
    model <- normalize_model_column_names(model)

    path_col <- find_column_alias(names(model), c("pathway", "source"))
    gene_col <- find_column_alias(names(model), c("gene", "target"))
    weight_col <- find_column_alias(names(model), c("weight", "coefficient", "coef"))
    p_col <- find_column_alias(names(model), c("p_value", "p_value_", "pvalue", "p_val", "p"))

    if (any(is.na(c(path_col, gene_col, weight_col)))) {
        stop("Unexpected PROGENy model format. Required pathway/gene/weight columns were not found.")
    }

    pathway_name <- as.character(model[[path_col]])
    weight <- suppressWarnings(as.numeric(model[[weight_col]]))
    pval <- if (!is.na(p_col)) suppressWarnings(as.numeric(model[[p_col]])) else rep(NA_real_, nrow(model))

    out <- data.frame(
        organism = organism_label,
        source = "PROGENy",
        pathway_id = pathway_name,
        pathway_name = pathway_name,
        gene = as.character(model[[gene_col]]),
        ensembl_name = NA_character_,
        direction = ifelse(weight > 0, "UP", ifelse(weight < 0, "DOWN", "ZERO")),
        perturbation_weight = weight,
        model_p_value = pval,
        model_fdr = NA_real_,
        model_specificity_weight = NA_real_,
        effective_weight = weight,
        library_type = "PROGENy",
        stringsAsFactors = FALSE
    )

    valid <- nzchar(out$pathway_name) & nzchar(out$gene) & is.finite(out$effective_weight) & out$effective_weight != 0
    out <- out[valid, , drop = FALSE]

    for (p in unique(out$pathway_name)) {
        idx <- which(out$pathway_name == p & is.finite(out$model_p_value))
        if (length(idx)) out$model_fdr[idx] <- stats::p.adjust(out$model_p_value[idx], method = "BH")
    }

    out$pathway <- make_pathway_labels(out$source, out$pathway_name, out$pathway_id)
    out$model_source <- paste0("PROGENy_", organism_label)
    out
}

read_delimited_flexible <- function(path) {
    ext <- tolower(tools::file_ext(path))
    if (ext == "csv") {
        read.csv(path, check.names = FALSE, stringsAsFactors = FALSE)
    } else {
        read.delim(path, check.names = FALSE, stringsAsFactors = FALSE, sep = "\t", quote = "", fill = TRUE,
                   na.strings = c("", "NA", "NaN", "NULL"))
    }
}

load_fingerprint_pathways_database <- function(path, organism = NULL) {
    if (is.null(path) || !nzchar(trimws(path))) return(NULL)
    if (!file.exists(path)) stop("Fingerprint_Pathways.tabtxt was not found: ", path)

    x_original <- read_delimited_flexible(path)
    x <- normalize_model_column_names(x_original)

    required <- c(
        "organism", "source", "pathway_id", "pathway_name", "gene", "ensembl_name",
        "direction", "model_p_value", "model_fdr", "model_specificity_weight"
    )
    missing <- setdiff(required, names(x))
    if (length(missing)) {
        stop(
            "Fingerprint_Pathways.tabtxt is missing required column(s): ",
            paste(missing, collapse = ", "),
            "\nRequired displayed columns are:\n",
            "Organism | Source | Pathway_ID | Pathway_Name | Gene | Ensembl Name | Direction | ",
            "Model_P_Value | Model_FDR | Model_Specificity_Weight"
        )
    }

    organism_value <- trimws(as.character(x$organism))
    source <- trimws(as.character(x$source))
    pathway_id <- trimws(as.character(x$pathway_id))
    pathway_name <- trimws(as.character(x$pathway_name))
    gene <- trimws(as.character(x$gene))
    ensembl <- trimws(as.character(x$ensembl_name))
    direction_text <- trimws(as.character(x$direction))
    direction_sign <- normalize_direction_sign(direction_text)
    model_p <- suppressWarnings(as.numeric(x$model_p_value))
    model_fdr <- suppressWarnings(as.numeric(x$model_fdr))
    spec_weight <- suppressWarnings(as.numeric(x$model_specificity_weight))

    bad_direction <- is.na(direction_sign)
    if (any(bad_direction)) {
        examples <- unique(direction_text[bad_direction])
        stop(
            "Unrecognized Direction value(s) in Fingerprint_Pathways.tabtxt: ",
            paste(head(examples, 10), collapse = ", "),
            "\nUse UP/DOWN, +/-, +1/-1, POS/NEG, or INCREASE/DECREASE."
        )
    }

    bad_weight <- !is.finite(spec_weight) | spec_weight < 0
    if (any(bad_weight)) {
        stop("Model_Specificity_Weight must contain non-negative numeric values for every database row.")
    }
    if (any(is.finite(model_p) & (model_p < 0 | model_p > 1))) stop("Model_P_Value values must be between 0 and 1 or NA.")
    if (any(is.finite(model_fdr) & (model_fdr < 0 | model_fdr > 1))) stop("Model_FDR values must be between 0 and 1 or NA.")

    if (any(!nzchar(organism_value))) stop("Organism cannot be blank in Fingerprint_Pathways.tabtxt.")
    if (any(!nzchar(source))) stop("Source cannot be blank in Fingerprint_Pathways.tabtxt.")
    if (any(!nzchar(pathway_id))) stop("Pathway_ID cannot be blank in Fingerprint_Pathways.tabtxt.")
    if (any(!nzchar(pathway_name))) stop("Pathway_Name cannot be blank in Fingerprint_Pathways.tabtxt.")
    if (any(!nzchar(gene) & !nzchar(ensembl))) stop("Every row must contain Gene and/or Ensembl Name.")

    out <- data.frame(
        organism = organism_value,
        source = source,
        pathway_id = pathway_id,
        pathway_name = pathway_name,
        gene = gene,
        ensembl_name = ensembl,
        direction = ifelse(direction_sign > 0, "UP", "DOWN"),
        perturbation_weight = NA_real_,
        model_p_value = model_p,
        model_fdr = model_fdr,
        model_specificity_weight = spec_weight,
        effective_weight = direction_sign * spec_weight,
        library_type = "FingerprintDB",
        stringsAsFactors = FALSE
    )

    if (!is.null(organism) && nzchar(trimws(as.character(organism)[1L]))) {
        selected_organism <- trimws(as.character(organism)[1L])
        out <- out[tolower(out$organism) == tolower(selected_organism), , drop = FALSE]
        if (!nrow(out)) return(NULL)
    }

    out <- out[is.finite(out$effective_weight) & out$effective_weight != 0, , drop = FALSE]
    if (!nrow(out)) stop("Fingerprint_Pathways.tabtxt contains no non-zero usable pathway-gene rows.")

    out$pathway <- make_pathway_labels(out$source, out$pathway_name, out$pathway_id)
    out$model_source <- paste0("Fingerprint_Pathways:", basename(path))
    out
}

load_combined_pathway_library <- function(organism = "Human", fingerprint_path = "", source = "All sources") {
    selected_source <- trimws(as.character(source)[1L])
    if (!nzchar(selected_source)) stop("Source cannot be blank.")
    source_key <- tolower(selected_source)
    all_sources <- source_key %in% c("all", "all sources")

    progeny_model <- if (all_sources || identical(source_key, "progeny")) load_builtin_progeny_model(organism) else NULL
    custom_model <- load_fingerprint_pathways_database(fingerprint_path, organism)
    if (!is.null(custom_model) && !all_sources) {
        if (identical(source_key, "progeny")) {
            custom_model <- NULL
        } else {
            custom_model <- custom_model[tolower(custom_model$source) == source_key, , drop = FALSE]
            if (!nrow(custom_model)) custom_model <- NULL
        }
    }

    if (is.null(progeny_model) && is.null(custom_model)) {
        stop("No pathways are available for organism '", organism, "' and source '", selected_source, "'. Check the Organism/Source columns and selections.")
    }
    if (is.null(progeny_model)) return(custom_model)
    if (is.null(custom_model)) return(progeny_model)

    common <- union(names(progeny_model), names(custom_model))
    add_missing <- function(x) {
        for (nm in setdiff(common, names(x))) x[[nm]] <- NA
        x[, common, drop = FALSE]
    }
    combined <- rbind(add_missing(progeny_model), add_missing(custom_model))
    rownames(combined) <- NULL
    combined
}

select_top_model_genes <- function(model, progeny_top_n = 100L) {
    progeny_top_n <- max(1L, as.integer(progeny_top_n))
    split_model <- split(model, model$pathway)

    selected <- lapply(split_model, function(x) {

        fdr_sort <- ifelse(is.finite(x$model_fdr), x$model_fdr, Inf)
        p_sort <- ifelse(is.finite(x$model_p_value), x$model_p_value, Inf)
        x <- x[order(fdr_sort, p_sort, -abs(x$effective_weight), na.last = TRUE), , drop = FALSE]

        gene_key <- ifelse(nzchar(x$gene), toupper(x$gene), toupper(x$ensembl_name))
        x <- x[!duplicated(gene_key), , drop = FALSE]

        if (all(x$library_type == "PROGENy")) head(x, progeny_top_n) else x
    })
    do.call(rbind, unname(selected))
}

prepare_weighted_model <- function(full_model, progeny_top_n) {
    model <- select_top_model_genes(full_model, progeny_top_n)
    model$expected_direction <- ifelse(model$effective_weight > 0, "UP", ifelse(model$effective_weight < 0, "DOWN", "ZERO"))
    model
}

load_spatial_object <- function(path) {
    if (!file.exists(path)) stop("Input RDS not found: ", path)
    obj <- readRDS(path)
    if (!inherits(obj, "Seurat")) stop("The selected RDS is not a Seurat object.")
    if (!length(Seurat::Images(obj))) stop("The Seurat object does not contain a spatial image.")
    obj
}

available_assays <- function(object) {
    as.character(SeuratObject::Assays(object))
}

available_layers <- function(object, assay) {
    if (!(assay %in% available_assays(object))) return(character(0))
    tryCatch(as.character(SeuratObject::Layers(object[[assay]])), error = function(e) character(0))
}

ensure_expression_layer <- function(object, assay = "Spatial", layer = "data") {
    if (!(assay %in% available_assays(object))) {
        stop("Assay '", assay, "' is not present. Available assays: ", paste(available_assays(object), collapse = ", "))
    }

    object <- tryCatch(SeuratObject::JoinLayers(object, assay = assay), error = function(e) object)
    layers <- available_layers(object, assay)

    if (!(layer %in% layers) && identical(layer, "data") && "counts" %in% layers) {
        append_log("Requested data layer is absent; running NormalizeData on assay '", assay, "' in memory.")
        object <- Seurat::NormalizeData(object, assay = assay, verbose = FALSE)
        layers <- available_layers(object, assay)
    }

    if (!(layer %in% layers)) {
        fallback <- intersect(c("data", "counts", "scale.data"), layers)
        if (!length(fallback)) stop("No usable expression layer was found in assay '", assay, "'.")
        append_log("Layer '", layer, "' unavailable. Falling back to '", fallback[1L], "'.")
        layer <- fallback[1L]
    }

    list(object = object, layer = layer)
}

get_expression_matrix <- function(object, assay, layer, features = NULL, cells = NULL) {
    mat <- SeuratObject::LayerData(object[[assay]], layer = layer, features = features, cells = cells)
    if (!inherits(mat, "Matrix")) mat <- Matrix::Matrix(mat, sparse = TRUE)
    mat
}

match_model_to_features <- function(model, available_features) {
    available_upper <- toupper(available_features)
    first_index <- !duplicated(available_upper)
    feature_map <- setNames(available_features[first_index], available_upper[first_index])

    gene_key <- toupper(as.character(model$gene))
    matched <- unname(feature_map[gene_key])

    if ("ensembl_name" %in% names(model)) {
        need <- is.na(matched) | !nzchar(matched)
        ensembl_key <- toupper(as.character(model$ensembl_name))
        matched[need] <- unname(feature_map[ensembl_key[need]])
    }

    model$matched_feature <- matched
    model$feature_found <- !is.na(matched) & nzchar(matched)
    model
}

normalize_vector_tissue <- function(v, method = "Tissue percentile centered", lower_q = 0.01, upper_q = 0.99) {
    v <- as.numeric(v)
    finite <- is.finite(v)
    if (!any(finite)) return(rep(0, length(v)))
    if (sum(finite) < 2L || diff(range(v[finite])) == 0) return(rep(0, length(v)))

    if (identical(method, "Tissue percentile centered")) {
        r <- rank(v, ties.method = "average", na.last = "keep")
        rr <- range(r[is.finite(r)])
        if (diff(rr) == 0) return(rep(0, length(v)))
        z <- (r - rr[1L]) / diff(rr)
        z[!is.finite(z)] <- 0.5
        return(z - 0.5)
    }

    if (identical(method, "Robust min-max centered")) {
        lo <- as.numeric(stats::quantile(v[finite], probs = lower_q, na.rm = TRUE, names = FALSE))
        hi <- as.numeric(stats::quantile(v[finite], probs = upper_q, na.rm = TRUE, names = FALSE))
        if (!is.finite(lo) || !is.finite(hi) || hi <= lo) return(rep(0, length(v)))
        z <- pmin(pmax(v, lo), hi)
        z <- (z - lo) / (hi - lo)
        z[!is.finite(z)] <- 0.5
        return(z - 0.5)
    }

    if (identical(method, "Gene z-score across tissue")) {
        mu <- mean(v[finite])
        s <- stats::sd(v[finite])
        if (!is.finite(s) || s <= 0) return(rep(0, length(v)))
        z <- (v - mu) / s
        z[!is.finite(z)] <- 0
        return(pmin(pmax(z, -5), 5))
    }

    if (identical(method, "Median-centered assay values")) {
        med <- stats::median(v[finite], na.rm = TRUE)
        z <- v - med
        z[!is.finite(z)] <- 0
        return(z)
    }

    stop("Unknown tissue normalization method: ", method)
}

normalize_matrix_tissue <- function(mat, method, lower_q = 0.01, upper_q = 0.99) {
    if (nrow(mat) == 0L) return(matrix(numeric(0), 0, ncol(mat)))
    dense <- as.matrix(mat)
    out <- t(vapply(
        seq_len(nrow(dense)),
        function(i) normalize_vector_tissue(dense[i, ], method, lower_q, upper_q),
        numeric(ncol(dense))
    ))
    rownames(out) <- rownames(dense)
    colnames(out) <- colnames(dense)
    out
}

percentile01 <- function(v) {
    v <- as.numeric(v)
    if (length(v) < 2L || diff(range(v, finite = TRUE, na.rm = TRUE)) == 0) return(rep(0.5, length(v)))
    r <- rank(v, ties.method = "average", na.last = "keep")
    rr <- range(r, na.rm = TRUE)
    z <- (r - rr[1L]) / diff(rr)
    z[!is.finite(z)] <- 0.5
    z
}

zscore_safe <- function(v) {
    s <- stats::sd(v, na.rm = TRUE)
    if (!is.finite(s) || s <= 0) return(rep(0, length(v)))
    z <- (v - mean(v, na.rm = TRUE)) / s
    z[!is.finite(z)] <- 0
    z
}

safe_cor_by_column <- function(weight, x, method = "pearson") {
    x <- as.matrix(x)
    weight <- as.numeric(weight)
    if (length(weight) < 3L || nrow(x) < 3L || stats::sd(weight, na.rm = TRUE) == 0) {
        return(rep(NA_real_, ncol(x)))
    }

    x[!is.finite(x)] <- 0
    weight[!is.finite(weight)] <- 0

    if (identical(method, "spearman")) {
        weight <- rank(weight, ties.method = "average")
        x <- matrixStats::colRanks(x, ties.method = "average", preserveShape = TRUE)
    }

    wc <- weight - mean(weight)
    xc <- sweep(x, 2L, colMeans(x), FUN = "-")
    denom <- sqrt(sum(wc^2)) * sqrt(colSums(xc^2))
    numer <- as.numeric(crossprod(wc, xc))
    out <- numer / denom
    out[!is.finite(out)] <- NA_real_
    pmin(pmax(out, -1), 1)
}

correlation_p_from_r <- function(r, n_genes, tail = "Positive fingerprint match (one-sided)") {
    r <- as.numeric(r)
    n_genes <- as.integer(n_genes)
    out <- rep(NA_real_, length(r))
    if (!is.finite(n_genes) || n_genes < 3L) return(out)
    valid <- is.finite(r)
    if (!any(valid)) return(out)
    rr <- pmin(pmax(r[valid], -1), 1)
    df <- n_genes - 2L
    denom <- pmax(1 - rr^2, .Machine$double.eps)
    tstat <- rr * sqrt(df / denom)
    if (identical(tail, "Absolute correlation (two-sided)")) {
        out[valid] <- 2 * stats::pt(-abs(tstat), df = df)
    } else {

        out[valid] <- stats::pt(tstat, df = df, lower.tail = FALSE)
    }
    out[valid & abs(r) >= 1] <- 0
    pmin(pmax(out, 0), 1)
}

default_parallel_cores <- function() {
    detected <- tryCatch(parallel::detectCores(logical = TRUE), error = function(e) 1L)
    if (!length(detected) || !is.finite(detected) || is.na(detected) || detected < 1L) detected <- 1L
    max(1L, min(8L, as.integer(detected) - 1L))
}

resolve_parallel_cores <- function(requested_cores = 1L, task_count = 1L) {
    detected <- tryCatch(parallel::detectCores(logical = TRUE), error = function(e) 1L)
    if (!length(detected) || !is.finite(detected) || is.na(detected) || detected < 1L) detected <- 1L
    requested_cores <- suppressWarnings(as.integer(requested_cores))
    if (!length(requested_cores) || is.na(requested_cores) || requested_cores < 1L) requested_cores <- 1L
    task_count <- suppressWarnings(as.integer(task_count))
    if (!length(task_count) || is.na(task_count) || task_count < 1L) task_count <- 1L
    max(1L, min(requested_cores, as.integer(detected), task_count))
}

compute_observed_scores_one_pathway <- function(pathway, split_model, normalized_expression, all_cells) {
    pathway_model <- split_model[[pathway]]
    pm <- pathway_model[pathway_model$feature_found, , drop = FALSE]
    requested_n <- nrow(pathway_model)
    if (!nrow(pm)) return(list(pathway = pathway, coverage = NULL))

    pm <- pm[order(-abs(pm$effective_weight)), , drop = FALSE]
    pm <- pm[!duplicated(pm$matched_feature), , drop = FALSE]

    genes <- pm$matched_feature
    x <- normalized_expression[genes, , drop = FALSE]
    w <- pm$effective_weight
    denom <- sum(abs(w))
    if (!is.finite(denom) || denom <= 0) return(list(pathway = pathway, coverage = NULL))

    score <- as.numeric(w %*% x) / denom
    pearson <- safe_cor_by_column(w, x, method = "pearson")
    spearman <- safe_cor_by_column(w, x, method = "spearman")
    pearson_p <- correlation_p_from_r(pearson, length(w), "Positive fingerprint match (one-sided)")
    spearman_p <- correlation_p_from_r(spearman, length(w), "Positive fingerprint match (one-sided)")

    list(
        pathway = pathway,
        score = score,
        pearson = pearson,
        spearman = spearman,
        pearson_p_positive = pearson_p,
        spearman_p_positive = spearman_p,
        coverage = data.frame(
            pathway = pathway,
            genes_requested = requested_n,
            genes_found = nrow(pm),
            coverage_fraction = nrow(pm) / requested_n,
            positive_genes_found = sum(w > 0),
            negative_genes_found = sum(w < 0),
            sum_abs_effective_weight = denom,
            stringsAsFactors = FALSE
        )
    )
}

calculate_observed_scores <- function(model, normalized_expression, all_cells, parallelize = FALSE, cores = 1L) {
    pathways <- unique(model$pathway)
    score <- matrix(NA_real_, nrow = length(pathways), ncol = length(all_cells), dimnames = list(pathways, all_cells))
    pearson <- score
    spearman <- score
    pearson_p <- score
    spearman_p <- score
    split_model <- split(model, model$pathway)

    cores_to_use <- if (isTRUE(parallelize)) resolve_parallel_cores(cores, length(pathways)) else 1L

    if (cores_to_use > 1L) {
        results <- tryCatch({
            cl <- parallel::makeCluster(cores_to_use)
            on.exit(try(parallel::stopCluster(cl), silent = TRUE), add = TRUE)

            parallel::clusterExport(
                cl,
                varlist = c("split_model", "normalized_expression", "all_cells"),
                envir = environment()
            )
            parallel::clusterExport(
                cl,
                varlist = c("compute_observed_scores_one_pathway", "safe_cor_by_column", "correlation_p_from_r"),
                envir = .GlobalEnv
            )

            parallel::parLapply(
                cl,
                pathways,
                function(p) compute_observed_scores_one_pathway(p, split_model, normalized_expression, all_cells)
            )
        }, error = function(e) {
            append_log("Parallel pathway score calculation failed; using sequential calculation. Reason: ", conditionMessage(e))
            NULL
        })
    } else {
        results <- NULL
    }

    if (is.null(results)) {
        results <- lapply(
            pathways,
            function(p) compute_observed_scores_one_pathway(p, split_model, normalized_expression, all_cells)
        )
    }

    coverage_rows <- list()
    for (res in results) {
        p <- res$pathway
        if (!is.null(res$score)) score[p, ] <- res$score
        if (!is.null(res$pearson)) pearson[p, ] <- res$pearson
        if (!is.null(res$spearman)) spearman[p, ] <- res$spearman
        if (!is.null(res$pearson_p_positive)) pearson_p[p, ] <- res$pearson_p_positive
        if (!is.null(res$spearman_p_positive)) spearman_p[p, ] <- res$spearman_p_positive
        if (!is.null(res$coverage)) coverage_rows[[length(coverage_rows) + 1L]] <- res$coverage
    }

    list(
        score = score,
        pearson = pearson,
        spearman = spearman,
        pearson_p_positive = pearson_p,
        spearman_p_positive = spearman_p,
        coverage = if (length(coverage_rows)) do.call(rbind, coverage_rows) else data.frame()
    )
}

prepare_correlation_matrix <- function(weight, x, method = "Spearman") {
    x <- as.matrix(x)
    w <- as.numeric(weight)

    if (identical(method, "Spearman")) {
        w <- rank(w, ties.method = "average")
        x <- matrixStats::colRanks(x, ties.method = "average", preserveShape = TRUE)
    }

    x[!is.finite(x)] <- 0
    w[!is.finite(w)] <- 0

    w_center <- w - mean(w)
    x_center <- sweep(x, 2L, colMeans(x), FUN = "-")
    w_norm <- sqrt(sum(w_center^2))
    x_norm <- sqrt(colSums(x_center^2))

    list(
        weight = w,
        weight_center = w_center,
        expression_center = x_center,
        weight_norm = w_norm,
        expression_norm = x_norm
    )
}

empirical_correlation_p_for_pathway <- function(
    pathway,
    pm,
    normalized_expression,
    observed_correlation,
    method = "Spearman",
    permutations = 500L,
    tail = "Positive fingerprint match (one-sided)",
    seed = 12345L
) {
    permutations <- as.integer(permutations)
    if (permutations < 1L) return(rep(NA_real_, length(observed_correlation)))

    pm <- pm[pm$feature_found, , drop = FALSE]
    pm <- pm[order(-abs(pm$effective_weight)), , drop = FALSE]
    pm <- pm[!duplicated(pm$matched_feature), , drop = FALSE]
    if (nrow(pm) < 3L) return(rep(NA_real_, length(observed_correlation)))

    genes <- pm$matched_feature
    x <- normalized_expression[genes, , drop = FALSE]
    prep <- prepare_correlation_matrix(pm$effective_weight, x, method)
    if (!is.finite(prep$weight_norm) || prep$weight_norm <= 0) {
        return(rep(NA_real_, length(observed_correlation)))
    }

    valid_expression <- is.finite(prep$expression_norm) & prep$expression_norm > 0
    result <- rep(NA_real_, length(observed_correlation))
    valid_observed <- is.finite(observed_correlation) & valid_expression
    if (!any(valid_observed)) return(result)

    set.seed(seed + sum(utf8ToInt(pathway)) + ifelse(identical(method, "Spearman"), 100000L, 200000L))

    permuted_weights <- t(replicate(
        permutations,
        sample(prep$weight, length(prep$weight), replace = FALSE)
    ))
    permuted_center <- permuted_weights - rowMeans(permuted_weights)
    permuted_norm <- sqrt(rowSums(permuted_center^2))

    numerator <- permuted_center %*% prep$expression_center
    denominator <- outer(permuted_norm, prep$expression_norm, FUN = "*")
    null_correlation <- numerator / denominator
    null_correlation[!is.finite(null_correlation)] <- NA_real_

    obs <- observed_correlation
    if (identical(tail, "Absolute correlation (two-sided)")) {
        exceed <- colSums(abs(null_correlation) >= matrix(abs(obs), nrow = permutations, ncol = length(obs), byrow = TRUE), na.rm = TRUE)
    } else {
        exceed <- colSums(null_correlation >= matrix(obs, nrow = permutations, ncol = length(obs), byrow = TRUE), na.rm = TRUE)
    }

    result[valid_observed] <- (1 + exceed[valid_observed]) / (permutations + 1)
    result
}

compute_empirical_correlations_parallel <- function(
    pathway_ids,
    weighted_model,
    normalized_expression,
    observed_correlation,
    method,
    permutations,
    tail,
    seed,
    parallelize = FALSE,
    cores = 1L
) {
    split_weighted_model <- split(weighted_model, weighted_model$pathway)
    cores_to_use <- if (isTRUE(parallelize)) resolve_parallel_cores(cores, length(pathway_ids)) else 1L

    worker_fun <- function(p) {
        empirical_correlation_p_for_pathway(
            pathway = p,
            pm = split_weighted_model[[p]],
            normalized_expression = normalized_expression,
            observed_correlation = observed_correlation[p, ],
            method = method,
            permutations = permutations,
            tail = tail,
            seed = seed
        )
    }

    if (cores_to_use > 1L) {
        results <- tryCatch({
            cl <- parallel::makeCluster(cores_to_use)
            on.exit(try(parallel::stopCluster(cl), silent = TRUE), add = TRUE)

            parallel::clusterExport(
                cl,
                varlist = c(
                    "split_weighted_model", "normalized_expression", "observed_correlation",
                    "method", "permutations", "tail", "seed"
                ),
                envir = environment()
            )
            parallel::clusterExport(
                cl,
                varlist = c("empirical_correlation_p_for_pathway", "prepare_correlation_matrix"),
                envir = .GlobalEnv
            )

            parallel::parLapply(cl, pathway_ids, worker_fun)
        }, error = function(e) {
            append_log("Parallel empirical pathway permutations failed; using sequential permutations. Reason: ", conditionMessage(e))
            NULL
        })
    } else {
        results <- NULL
    }

    if (is.null(results)) results <- lapply(pathway_ids, worker_fun)
    names(results) <- pathway_ids
    results
}

adjust_fdr_matrix <- function(pmat, scope = "Per spot across pathways") {
    out <- pmat
    if (identical(scope, "Per spot across pathways")) {
        for (j in seq_len(ncol(pmat))) out[, j] <- stats::p.adjust(pmat[, j], method = "BH")
    } else if (identical(scope, "Per pathway across spots")) {
        for (i in seq_len(nrow(pmat))) out[i, ] <- stats::p.adjust(pmat[i, ], method = "BH")
    } else if (identical(scope, "Global pathway x spot")) {
        out[] <- stats::p.adjust(as.vector(pmat), method = "BH")
    } else {
        stop("Unknown FDR scope: ", scope)
    }
    out
}

get_image_coordinates_full <- function(object, image_name) {
    image_object <- object[[image_name]]

    coords <- NULL
    if ("coordinates" %in% slotNames(image_object)) {
        coords <- tryCatch(image_object@coordinates, error = function(e) NULL)
    }

    if (is.null(coords) || !nrow(coords)) {
        coords <- tryCatch(Seurat::GetTissueCoordinates(image_object, scale = NULL), error = function(e) NULL)
    }
    if (is.null(coords) || !nrow(coords)) {
        coords <- tryCatch(Seurat::GetTissueCoordinates(object, image = image_name), error = function(e) NULL)
    }
    if (is.null(coords) || !nrow(coords)) stop("Could not retrieve spatial coordinates for image: ", image_name)

    coords <- as.data.frame(coords, stringsAsFactors = FALSE)
    if (is.null(rownames(coords)) || all(rownames(coords) %in% as.character(seq_len(nrow(coords))))) {
        cell_col <- intersect(c("cell", "barcode", "Cell", "Barcode"), colnames(coords))
        if (length(cell_col)) rownames(coords) <- as.character(coords[[cell_col[1L]]])
    }

    coords
}

find_array_columns <- function(coords) {
    lower <- tolower(colnames(coords))
    row_candidates <- c("array_row", "row", "arrayrow")
    col_candidates <- c("array_col", "col", "arraycol")
    ri <- match(row_candidates, lower, nomatch = 0L)
    ci <- match(col_candidates, lower, nomatch = 0L)
    ri <- ri[ri > 0L]
    ci <- ci[ci > 0L]
    if (!length(ri) || !length(ci)) return(NULL)
    c(row = colnames(coords)[ri[1L]], col = colnames(coords)[ci[1L]])
}

build_hex_adjacency <- function(coords) {
    rc <- find_array_columns(coords)
    if (is.null(rc)) return(NULL)

    r <- as.integer(coords[[rc["row"]]])
    c <- as.integer(coords[[rc["col"]]])
    cells <- rownames(coords)
    ok <- is.finite(r) & is.finite(c) & !is.na(cells)
    r <- r[ok]; c <- c[ok]; cells <- cells[ok]

    key <- paste(r, c, sep = ":")
    lookup <- setNames(cells, key)
    deltas <- rbind(c(0, -2), c(0, 2), c(-1, -1), c(-1, 1), c(1, -1), c(1, 1))

    adj <- setNames(vector("list", length(cells)), cells)
    for (i in seq_along(cells)) {
        nkeys <- paste(r[i] + deltas[, 1], c[i] + deltas[, 2], sep = ":")
        neigh <- unname(lookup[nkeys])
        neigh <- neigh[!is.na(neigh)]
        adj[[cells[i]]] <- unique(neigh)
    }
    attr(adj, "method") <- "Visium hex array_row/array_col direct neighbors"
    adj
}

find_xy_columns <- function(coords) {
    lower <- tolower(colnames(coords))
    candidate_pairs <- list(
        c("imagecol", "imagerow"),
        c("x", "y"),
        c("pxl_col_in_fullres", "pxl_row_in_fullres"),
        c("pixelx", "pixely")
    )
    for (pair in candidate_pairs) {
        if (all(pair %in% lower)) {
            return(c(x = colnames(coords)[match(pair[1L], lower)], y = colnames(coords)[match(pair[2L], lower)]))
        }
    }
    numeric_cols <- which(vapply(coords, is.numeric, logical(1)))
    if (length(numeric_cols) >= 2L) return(c(x = colnames(coords)[numeric_cols[1L]], y = colnames(coords)[numeric_cols[2L]]))
    NULL
}

build_distance_adjacency <- function(coords, distance_multiplier = 1.25) {
    xy_cols <- find_xy_columns(coords)
    if (is.null(xy_cols)) stop("Could not identify X/Y coordinates for adjacency fallback.")

    xy <- as.matrix(coords[, xy_cols, drop = FALSE])
    storage.mode(xy) <- "double"
    cells <- rownames(coords)
    ok <- complete.cases(xy) & !is.na(cells)
    xy <- xy[ok, , drop = FALSE]
    cells <- cells[ok]

    if (nrow(xy) > 7000L) {
        warning("Distance-based fallback on >7000 spots can require substantial memory.")
    }

    d <- as.matrix(stats::dist(xy))
    diag(d) <- Inf
    nearest <- apply(d, 1L, min, na.rm = TRUE)
    threshold <- stats::median(nearest[is.finite(nearest)], na.rm = TRUE) * distance_multiplier

    adj <- setNames(vector("list", length(cells)), cells)
    for (i in seq_along(cells)) {
        neigh <- which(d[i, ] <= threshold)
        adj[[cells[i]]] <- cells[neigh]
    }
    attr(adj, "method") <- paste0("Distance fallback; threshold=", signif(threshold, 5))
    adj
}

build_adjacency <- function(object, image_name, mode = "Auto: Visium hex then distance", distance_multiplier = 1.25) {
    coords <- get_image_coordinates_full(object, image_name)
    image_cells <- intersect(rownames(coords), colnames(object))
    coords <- coords[image_cells, , drop = FALSE]

    if (grepl("Visium hex", mode, fixed = TRUE) || grepl("Auto", mode, fixed = TRUE)) {
        adj <- build_hex_adjacency(coords)
        if (!is.null(adj)) return(adj)
        if (!grepl("Auto", mode, fixed = TRUE)) stop("Visium row/column coordinates were not available.")
    }
    build_distance_adjacency(coords, distance_multiplier)
}

connected_components_mask <- function(mask_named, adjacency, minimum_size = 4L) {
    minimum_size <- max(1L, as.integer(minimum_size))
    cells <- names(adjacency)
    active <- setNames(rep(FALSE, length(cells)), cells)
    common <- intersect(names(mask_named), cells)
    active[common] <- as.logical(mask_named[common])
    active[is.na(active)] <- FALSE

    component_id <- setNames(rep(0L, length(cells)), cells)
    component_size <- setNames(rep(0L, length(cells)), cells)
    visited <- setNames(rep(FALSE, length(cells)), cells)
    components <- list()
    cid <- 0L

    for (start in cells) {
        if (!active[start] || visited[start]) next
        cid <- cid + 1L
        queue <- start
        visited[start] <- TRUE
        members <- character(0)

        while (length(queue)) {
            node <- queue[1L]
            queue <- queue[-1L]
            members <- c(members, node)
            neigh <- adjacency[[node]]
            neigh <- neigh[neigh %in% cells]
            to_add <- neigh[active[neigh] & !visited[neigh]]
            if (length(to_add)) {
                visited[to_add] <- TRUE
                queue <- c(queue, to_add)
            }
        }

        component_id[members] <- cid
        component_size[members] <- length(members)
        components[[as.character(cid)]] <- members
    }

    retained <- component_size >= minimum_size & active
    list(
        retained = retained,
        component_id = component_id,
        component_size = component_size,
        components = components,
        n_components = length(components),
        n_retained_components = sum(vapply(components, length, integer(1)) >= minimum_size),
        largest_component = if (length(components)) max(vapply(components, length, integer(1))) else 0L
    )
}

add_numeric_metadata <- function(object, column, values) {
    values <- values[colnames(object)]
    object[[column]] <- as.numeric(values)
    object
}

add_factor_metadata <- function(object, column, values, levels = NULL) {
    values <- values[colnames(object)]
    if (is.null(levels)) values <- factor(values) else values <- factor(values, levels = levels)
    object[[column]] <- values
    object
}

plot_continuous_pathway <- function(object, image_name, metadata_column, pathway, output_file) {
    p <- Seurat::SpatialFeaturePlot(
        object,
        features = metadata_column,
        images = image_name,
        alpha = c(1, 1),
        min.cutoff = 0,
        max.cutoff = 1
    ) +
        ggplot2::scale_fill_gradientn(
            colours = c("#08306B", "#2171B5", "#41B6C4", "#7FCDBB", "#FFFFCC", "#FD8D3C", "#E31A1C"),
            limits = c(0, 1),
            oob = scales::squish
        ) +
        ggplot2::ggtitle(paste0(pathway, " weighted activity percentile (relative within this tissue)"))

    ggplot2::ggsave(output_file, p, width = 8, height = 7, dpi = 300)
}

plot_correlation_pathway <- function(object, image_name, metadata_column, pathway, method, output_file) {
    p <- Seurat::SpatialFeaturePlot(
        object,
        features = metadata_column,
        images = image_name,
        alpha = c(1, 1),
        min.cutoff = -1,
        max.cutoff = 1
    ) +
        ggplot2::scale_fill_gradient2(
            low = "#2166AC",
            mid = "grey95",
            high = "#B2182B",
            midpoint = 0,
            limits = c(-1, 1),
            oob = scales::squish
        ) +
        ggplot2::ggtitle(paste0(pathway, " ", method, " fingerprint correlation"))

    ggplot2::ggsave(output_file, p, width = 8, height = 7, dpi = 300)
}

plot_threshold_pathway <- function(object, image_name, metadata_column, pathway, output_file) {
    p <- Seurat::SpatialDimPlot(
        object,
        images = image_name,
        group.by = metadata_column,
        label = FALSE,
        cols = c("Does not pass" = "grey80", "Passes thresholds" = "#FDAE61")
    ) + ggplot2::ggtitle(paste0(pathway, " spots passing enabled thresholds"))
    ggplot2::ggsave(output_file, p, width = 8, height = 7, dpi = 300)
}

plot_retained_activity_pathway <- function(object, image_name, metadata_column, pathway, output_file) {
    p <- Seurat::SpatialDimPlot(
        object,
        images = image_name,
        group.by = metadata_column,
        label = FALSE,
        cols = c("No retained high-activity region" = "grey80", "Retained high-activity region" = "#D7301F")
    ) + ggplot2::ggtitle(paste0(pathway, " retained high-relative-activity footprint"))
    ggplot2::ggsave(output_file, p, width = 8, height = 7, dpi = 300)
}

plot_primary_activity_passed_only <- function(object, image_name, metadata_column, pathway, output_file) {
    p <- Seurat::SpatialDimPlot(
        object,
        images = image_name,
        group.by = metadata_column,
        label = FALSE,
        cols = c(
            "Does not pass" = "#00000000",
            "Passes thresholds" = "#39FF14"
        )
    ) +
        ggplot2::ggtitle(paste0(pathway, " primary activity: spots passing enabled thresholds")) +
        ggplot2::theme(legend.position = "none")

    ggplot2::ggsave(output_file, p, width = 8, height = 7, dpi = 300)
}


summarize_annotation_context <- function(object, long_stats, retained_activity_matrix, output_directory) {
    meta <- object[[]]
    annotation_columns <- intersect(c("predicted_cell_type", "RCTD_dominant_cell_type", "first_type", "seurat_clusters", "sample_id"), colnames(meta))
    rows <- list()

    if (length(annotation_columns)) {
        for (p in rownames(retained_activity_matrix)) {
            cells <- colnames(retained_activity_matrix)[retained_activity_matrix[p, ]]
            cells <- intersect(cells, rownames(meta))
            if (!length(cells)) next
            for (col in annotation_columns) {
                tab <- as.data.frame(table(as.character(meta[cells, col, drop = TRUE])), stringsAsFactors = FALSE)
                colnames(tab) <- c("annotation_value", "spots")
                tab$pathway <- p
                tab$annotation_column <- col
                tab$fraction <- tab$spots / sum(tab$spots)
                rows[[length(rows) + 1L]] <- tab[, c("pathway", "annotation_column", "annotation_value", "spots", "fraction")]
            }
        }
    }
    if (length(rows)) write.csv(do.call(rbind, rows), file.path(output_directory, "retained_high_relative_activity_by_annotation.csv"), row.names = FALSE)

    if ("celltype_predictions" %in% SeuratObject::Assays(object)) {
        pred <- tryCatch(SeuratObject::LayerData(object[["celltype_predictions"]], layer = "data"), error = function(e) NULL)
        if (!is.null(pred)) {
            pred_rows <- list()
            for (p in rownames(retained_activity_matrix)) {
                cells <- colnames(retained_activity_matrix)[retained_activity_matrix[p, ]]
                cells <- intersect(cells, colnames(pred))
                if (!length(cells)) next
                means <- Matrix::rowMeans(pred[, cells, drop = FALSE])
                pred_rows[[p]] <- data.frame(pathway = p, cell_type = names(means), mean_prediction_score = as.numeric(means), stringsAsFactors = FALSE)
            }
            if (length(pred_rows)) write.csv(do.call(rbind, pred_rows), file.path(output_directory, "retained_high_relative_activity_mean_celltype_prediction_scores.csv"), row.names = FALSE)
        }
    }
}

run_pathway_footprint_analysis <- function(settings, model_full, selected_pathways, object = NULL) {

    settings$significance_tail <- "Positive fingerprint match (one-sided)"
    outdir <- normalizePath(settings$output_directory, winslash = "/", mustWork = FALSE)
    dir.create(outdir, recursive = TRUE, showWarnings = FALSE)
    .GUI$output_directory <- outdir
    if (file.exists(file.path(outdir, "run_log.txt"))) file.remove(file.path(outdir, "run_log.txt"))

    append_log("=== SCRIPT 7: Pathway-Footprint Analysis Using Perturbation-Derived Gene Weights ===")
    append_log("Input RDS: ", settings$input_rds)
    append_log("Output: ", outdir)
    append_log("Organism: ", settings$organism)
    append_log("Source filter: ", settings$source)
    append_log("Selected pathways: ", paste(selected_pathways, collapse = ", "))
    append_log("Fingerprint database: ", if (nzchar(trimws(settings$fingerprint_database))) settings$fingerprint_database else "<not supplied; PROGENy only>")
    append_log("Primary pathway/spot statistic: signed weighted footprint activity; within-tissue activity percentile is used for the default threshold")
    append_log("Complementary fingerprint compatibility statistic: ", settings$primary_correlation, " correlation")
    append_log("Significance source: ", settings$significance_source)
    append_log("Parallel pathway computation: ", if (isTRUE(settings$parallelize_pathways)) paste0("Enabled; requested cores=", settings$cpu_cores, "; effective cores=", resolve_parallel_cores(settings$cpu_cores, length(selected_pathways))) else "Disabled")
    append_log("Image output mode: ", if (isTRUE(settings$output_primary_activity_only)) "Primary activity passing-spots image only" else "Full pathway image set")

    req <- missing_packages(include_progeny = any(model_full$library_type == "PROGENy"))
    if (length(req)) stop("Missing required packages: ", paste(req, collapse = ", "))

    if (is.null(object)) object <- load_spatial_object(settings$input_rds)
    ensure <- ensure_expression_layer(object, settings$assay, settings$layer)
    object <- ensure$object
    settings$layer <- ensure$layer

    all_cells <- colnames(object)
    append_log("Spots in object: ", length(all_cells))
    append_log("Assay/layer: ", settings$assay, "/", settings$layer)

    weighted_model_all <- prepare_weighted_model(model_full, settings$top_genes)
    weighted_model <- weighted_model_all[weighted_model_all$pathway %in% selected_pathways, , drop = FALSE]
    if (!nrow(weighted_model)) stop("No rows remain after pathway selection.")

    expr_source <- get_expression_matrix(object, settings$assay, settings$layer)
    weighted_model <- match_model_to_features(weighted_model, rownames(expr_source))

    coverage_pre <- aggregate(feature_found ~ pathway, data = weighted_model, FUN = sum)
    requested_pre <- as.data.frame(table(weighted_model$pathway), stringsAsFactors = FALSE)
    colnames(requested_pre) <- c("pathway", "requested")
    coverage_pre <- merge(requested_pre, coverage_pre, by = "pathway", all.x = TRUE)
    coverage_pre$coverage <- coverage_pre$feature_found / coverage_pre$requested

    keep_pathways <- coverage_pre$pathway[
        coverage_pre$feature_found >= settings$minimum_genes_present &
        coverage_pre$coverage >= settings$minimum_coverage
    ]
    skipped <- setdiff(selected_pathways, keep_pathways)
    if (length(skipped)) append_log("Skipped for insufficient footprint-gene coverage: ", paste(skipped, collapse = ", "))
    if (!length(keep_pathways)) stop("No selected pathways meet the minimum gene-coverage criteria.")
    weighted_model <- weighted_model[weighted_model$pathway %in% keep_pathways, , drop = FALSE]

    weighted_model_export <- weighted_model
    names(weighted_model_export)[names(weighted_model_export) == "matched_feature"] <- "matched_Feature_Gene"
    names(weighted_model_export)[names(weighted_model_export) == "feature_found"] <- "Feature_Gene_found"
    coverage_pre_export <- coverage_pre
    names(coverage_pre_export)[names(coverage_pre_export) == "requested"] <- "Count_Feature_Genes_requested"
    names(coverage_pre_export)[names(coverage_pre_export) == "feature_found"] <- "Count_Feature_Genes_found"
    names(coverage_pre_export)[names(coverage_pre_export) == "coverage"] <- "Feature_Genes_coverage_fraction"
    if (isTRUE(settings$save_debug_matrices)) {
        write.csv(weighted_model_export, file.path(outdir, "footprint_model_Feature_Genes_used.csv"), row.names = FALSE)
        write.csv(coverage_pre_export, file.path(outdir, "footprint_model_Feature_Genes_coverage_precheck.csv"), row.names = FALSE)
    }

    set_status("Normalizing footprint genes across tissue...", 10)
    selected_features <- unique(weighted_model$matched_feature[weighted_model$feature_found])
    expr_selected <- expr_source[selected_features, , drop = FALSE]
    normalized_selected <- normalize_matrix_tissue(
        expr_selected,
        settings$tissue_normalization,
        settings$lower_quantile,
        settings$upper_quantile
    )

    set_status("Calculating weighted pathway activity and complementary fingerprint correlations...", 20)
    observed <- calculate_observed_scores(
        weighted_model,
        normalized_selected,
        all_cells,
        parallelize = settings$parallelize_pathways,
        cores = settings$cpu_cores
    )
    score_raw <- observed$score
    pearson <- observed$pearson
    spearman <- observed$spearman
    pearson_p_positive <- observed$pearson_p_positive
    spearman_p_positive <- observed$spearman_p_positive
    if (isTRUE(settings$save_debug_matrices)) {
        write.csv(observed$coverage, file.path(outdir, "pathway_gene_coverage.csv"), row.names = FALSE)
    }

    valid_pathways <- rownames(score_raw)[rowSums(is.finite(score_raw)) > 0]
    score_raw <- score_raw[valid_pathways, , drop = FALSE]
    pearson <- pearson[valid_pathways, , drop = FALSE]
    spearman <- spearman[valid_pathways, , drop = FALSE]
    pearson_p_positive <- pearson_p_positive[valid_pathways, , drop = FALSE]
    spearman_p_positive <- spearman_p_positive[valid_pathways, , drop = FALSE]
    weighted_model <- weighted_model[weighted_model$pathway %in% valid_pathways, , drop = FALSE]
    if (!length(valid_pathways)) stop("No pathways produced valid spot-level scores.")

    primary_correlation <- if (identical(settings$primary_correlation, "Pearson")) pearson else spearman
    classical_corr_p <- if (identical(settings$primary_correlation, "Pearson")) pearson_p_positive else spearman_p_positive

    correlation_valid <- rowSums(is.finite(primary_correlation)) > 0
    if (any(!correlation_valid)) {
        bad <- rownames(primary_correlation)[!correlation_valid]
        append_log("Complementary correlation is undefined, but weighted activity remains available, for: ", paste(bad, collapse = ", "))
    }

    score_percentile <- t(apply(score_raw, 1L, percentile01))
    rownames(score_percentile) <- rownames(score_raw)
    colnames(score_percentile) <- colnames(score_raw)
    score_z <- t(apply(score_raw, 1L, zscore_safe))
    rownames(score_z) <- rownames(score_raw)
    colnames(score_z) <- colnames(score_raw)

    classical_fdr <- adjust_fdr_matrix(classical_corr_p, settings$fdr_scope)
    pmat <- matrix(NA_real_, nrow = nrow(primary_correlation), ncol = ncol(primary_correlation), dimnames = dimnames(primary_correlation))
    empirical_fdr <- pmat

    if (identical(settings$significance_source, "Empirical weight permutation")) {
        set_status("Empirical significance of pathway/spot correlations...", 30)
        append_log("Empirical correlation permutations: pathway-level parallel computation starting...")
        pathway_ids <- rownames(primary_correlation)
        empirical_results <- compute_empirical_correlations_parallel(
            pathway_ids = pathway_ids,
            weighted_model = weighted_model,
            normalized_expression = normalized_selected,
            observed_correlation = primary_correlation,
            method = settings$primary_correlation,
            permutations = settings$permutations,
            tail = settings$significance_tail,
            seed = settings$random_seed,
            parallelize = settings$parallelize_pathways,
            cores = settings$cpu_cores
        )
        for (p in pathway_ids) pmat[p, ] <- empirical_results[[p]]
        empirical_fdr <- adjust_fdr_matrix(pmat, settings$fdr_scope)
        significance_p <- pmat
        significance_fdr <- empirical_fdr
    } else {
        append_log("Using classical correlation P values for significance/FDR; empirical permutations skipped.")
        significance_p <- classical_corr_p
        significance_fdr <- classical_fdr
    }

    set_status("Applying selected spot-level thresholds...", 68)
    initial_significant <- matrix(TRUE, nrow = nrow(primary_correlation), ncol = ncol(primary_correlation), dimnames = dimnames(primary_correlation))

    if (settings$use_correlation_threshold) {
        corr_value <- if (identical(settings$significance_tail, "Absolute correlation (two-sided)")) abs(primary_correlation) else primary_correlation
        initial_significant <- initial_significant & is.finite(corr_value) & corr_value >= settings$correlation_threshold
    }
    if (settings$use_significance_p_threshold) {
        initial_significant <- initial_significant & is.finite(significance_p) & significance_p <= settings$significance_p_threshold
    }
    if (settings$use_fdr_threshold) {
        initial_significant <- initial_significant & is.finite(significance_fdr) & significance_fdr <= settings$fdr_threshold
    }
    if (settings$use_activity_threshold) {
        initial_significant <- initial_significant & is.finite(score_percentile) & score_percentile >= settings$activity_percentile_threshold
    }

    rownames(initial_significant) <- rownames(primary_correlation)
    colnames(initial_significant) <- colnames(primary_correlation)

    set_status("Applying spatial adjacency / connected-component rule...", 70)
    retained <- matrix(FALSE, nrow = nrow(primary_correlation), ncol = ncol(primary_correlation), dimnames = dimnames(primary_correlation))
    component_id <- matrix(0L, nrow = nrow(primary_correlation), ncol = ncol(primary_correlation), dimnames = dimnames(primary_correlation))
    component_size <- matrix(0L, nrow = nrow(primary_correlation), ncol = ncol(primary_correlation), dimnames = dimnames(primary_correlation))
    component_summary_rows <- list()

    image_names <- Seurat::Images(object)
    for (image_name in image_names) {
        append_log("Building adjacency for image: ", image_name)
        adjacency <- build_adjacency(object, image_name, settings$adjacency_mode, settings$distance_multiplier)
        append_log("Adjacency method: ", attr(adjacency, "method"))
        image_cells <- intersect(names(adjacency), all_cells)

        for (p in rownames(primary_correlation)) {
            mask <- setNames(initial_significant[p, image_cells], image_cells)
            effective_minimum <- if (settings$use_spatial_filter) settings$minimum_adjacent_spots else 1L
            cc <- connected_components_mask(mask, adjacency, effective_minimum)

            retained_values <- if (settings$use_spatial_filter) cc$retained else as.logical(mask[names(cc$retained)])
            names(retained_values) <- names(cc$retained)
            retained[p, names(retained_values)] <- retained_values
            component_id[p, names(cc$component_id)] <- cc$component_id
            component_size[p, names(cc$component_size)] <- cc$component_size

            component_summary_rows[[length(component_summary_rows) + 1L]] <- data.frame(
                image = image_name,
                pathway = p,
                adjacency_method = attr(adjacency, "method"),
                threshold_passing_spots_before_spatial_filter = sum(mask, na.rm = TRUE),
                connected_components = cc$n_components,
                retained_components = if (settings$use_spatial_filter) cc$n_retained_components else cc$n_components,
                largest_component = cc$largest_component,
                retained_spots = sum(retained_values, na.rm = TRUE),
                spatial_filter_enabled = settings$use_spatial_filter,
                minimum_component_size = if (settings$use_spatial_filter) settings$minimum_adjacent_spots else 1L,
                stringsAsFactors = FALSE
            )
        }
    }

    component_summary <- do.call(rbind, component_summary_rows)
    if (isTRUE(settings$save_debug_matrices)) {
        write.csv(component_summary, file.path(outdir, "pathway_spatial_component_summary.csv"), row.names = FALSE)
    }

    set_status("Building rankings and output tables...", 78)
    long_rows <- vector("list", nrow(primary_correlation))
    for (i in seq_len(nrow(primary_correlation))) {
        p <- rownames(primary_correlation)[i]
        long_rows[[i]] <- data.frame(
            spot = colnames(primary_correlation),
            pathway = p,
            primary_correlation_method = settings$primary_correlation,
            primary_correlation = as.numeric(primary_correlation[p, ]),
            pearson_correlation = as.numeric(pearson[p, ]),
            spearman_correlation = as.numeric(spearman[p, ]),
            classical_correlation_p = as.numeric(classical_corr_p[p, ]),
            classical_correlation_fdr = as.numeric(classical_fdr[p, ]),
            empirical_correlation_p = as.numeric(pmat[p, ]),
            empirical_correlation_fdr = as.numeric(empirical_fdr[p, ]),
            significance_source = settings$significance_source,
            significance_p = as.numeric(significance_p[p, ]),
            significance_fdr = as.numeric(significance_fdr[p, ]),
            weighted_footprint_score = as.numeric(score_raw[p, ]),
            activity_z_score = as.numeric(score_z[p, ]),
            activity_percentile = as.numeric(score_percentile[p, ]),
            passes_enabled_spot_thresholds = as.logical(initial_significant[p, ]),
            spatially_retained = as.logical(retained[p, ]),
            connected_component_id = as.integer(component_id[p, ]),
            connected_component_size = as.integer(component_size[p, ]),
            stringsAsFactors = FALSE
        )
    }
    long_stats <- do.call(rbind, long_rows)
    long_stats$rank_by_weighted_activity_within_spot <- NA_integer_
    long_stats$rank_by_correlation_within_spot <- NA_integer_
    long_stats$rank_by_significance_within_spot <- NA_integer_
    spot_groups <- split(seq_len(nrow(long_stats)), long_stats$spot)
    for (idx in spot_groups) {
        primary_rank_value <- if (identical(settings$significance_tail, "Absolute correlation (two-sided)")) abs(long_stats$primary_correlation[idx]) else long_stats$primary_correlation[idx]

        ord_activity <- order(
            -long_stats$activity_percentile[idx],
            -long_stats$weighted_footprint_score[idx],
            -primary_rank_value,
            na.last = TRUE
        )
        long_stats$rank_by_weighted_activity_within_spot[idx[ord_activity]] <- seq_along(ord_activity)

        ord_corr <- order(
            -primary_rank_value,
            long_stats$significance_fdr[idx],
            long_stats$significance_p[idx],
            -long_stats$activity_percentile[idx],
            na.last = TRUE
        )
        long_stats$rank_by_correlation_within_spot[idx[ord_corr]] <- seq_along(ord_corr)

        ord_sig <- order(
            long_stats$significance_fdr[idx],
            long_stats$significance_p[idx],
            -primary_rank_value,
            -long_stats$activity_percentile[idx],
            na.last = TRUE
        )
        long_stats$rank_by_significance_within_spot[idx[ord_sig]] <- seq_along(ord_sig)
    }
    if (isTRUE(settings$save_debug_matrices)) {
        write.csv(long_stats, file.path(outdir, "spot_pathway_correlations_significance_and_rankings.csv"), row.names = FALSE)
    }

    make_best_spot_table <- function(rank_column) {
        rows <- lapply(spot_groups, function(idx) {
            ranks <- long_stats[[rank_column]][idx]
            best_idx <- idx[which.min(ranks)]
            data.frame(
                spot = long_stats$spot[best_idx],
                best_pathway = long_stats$pathway[best_idx],
                primary_correlation_method = settings$primary_correlation,
                primary_correlation = long_stats$primary_correlation[best_idx],
                pearson_correlation = long_stats$pearson_correlation[best_idx],
                spearman_correlation = long_stats$spearman_correlation[best_idx],
                significance_source = long_stats$significance_source[best_idx],
                significance_p = long_stats$significance_p[best_idx],
                significance_fdr = long_stats$significance_fdr[best_idx],
                empirical_correlation_p = long_stats$empirical_correlation_p[best_idx],
                empirical_correlation_fdr = long_stats$empirical_correlation_fdr[best_idx],
                weighted_footprint_score = long_stats$weighted_footprint_score[best_idx],
                activity_percentile = long_stats$activity_percentile[best_idx],
                passes_enabled_spot_thresholds = long_stats$passes_enabled_spot_thresholds[best_idx],
                spatially_retained = long_stats$spatially_retained[best_idx],
                stringsAsFactors = FALSE
            )
        })
        do.call(rbind, rows)
    }

    best_weighted_activity_table <- make_best_spot_table("rank_by_weighted_activity_within_spot")
    best_correlated_table <- make_best_spot_table("rank_by_correlation_within_spot")
    best_significant_table <- make_best_spot_table("rank_by_significance_within_spot")
    if (isTRUE(settings$save_debug_matrices)) {
        write.csv(best_weighted_activity_table, file.path(outdir, "highest_weighted_activity_pathway_per_spot.csv"), row.names = FALSE)
        write.csv(best_correlated_table, file.path(outdir, "best_correlated_pathway_per_spot_before_spatial_filter.csv"), row.names = FALSE)
        write.csv(best_significant_table, file.path(outdir, "most_significant_pathway_per_spot_before_spatial_filter.csv"), row.names = FALSE)
    }

    total_spots <- length(all_cells)
    pathway_ranking_rows <- lapply(rownames(primary_correlation), function(p) {
        idx <- long_stats$pathway == p
        retained_idx <- idx & long_stats$spatially_retained
        threshold_passing_before <- sum(long_stats$passes_enabled_spot_thresholds[idx], na.rm = TRUE)
        retained_n <- sum(long_stats$spatially_retained[idx], na.rm = TRUE)
        corr_ret <- long_stats$primary_correlation[retained_idx]
        data.frame(
            pathway = p,
            retained_high_activity_spots = retained_n,
            percent_tissue_in_retained_high_activity_region = 100 * retained_n / total_spots,
            threshold_passing_spots_before_spatial_filter = threshold_passing_before,
            largest_connected_component = max(long_stats$connected_component_size[idx], na.rm = TRUE),
            median_primary_correlation_retained = if (any(retained_idx)) stats::median(corr_ret, na.rm = TRUE) else NA_real_,
            max_primary_correlation = suppressWarnings(max(long_stats$primary_correlation[idx], na.rm = TRUE)),
            median_activity_percentile_retained = if (any(retained_idx)) stats::median(long_stats$activity_percentile[retained_idx], na.rm = TRUE) else NA_real_,
            median_weighted_score_retained = if (any(retained_idx)) stats::median(long_stats$weighted_footprint_score[retained_idx], na.rm = TRUE) else NA_real_,
            significance_source = settings$significance_source,
            best_significance_p = suppressWarnings(min(long_stats$significance_p[idx], na.rm = TRUE)),
            best_significance_fdr = suppressWarnings(min(long_stats$significance_fdr[idx], na.rm = TRUE)),
            best_empirical_correlation_p = suppressWarnings(min(long_stats$empirical_correlation_p[idx], na.rm = TRUE)),
            best_empirical_correlation_fdr = suppressWarnings(min(long_stats$empirical_correlation_fdr[idx], na.rm = TRUE)),
            high_relative_activity_region_detected = retained_n > 0,
            stringsAsFactors = FALSE
        )
    })
    pathway_ranking <- do.call(rbind, pathway_ranking_rows)
    numeric_cols <- c("max_primary_correlation", "best_significance_p", "best_significance_fdr", "best_empirical_correlation_p", "best_empirical_correlation_fdr")
    for (nm in numeric_cols) pathway_ranking[[nm]][!is.finite(pathway_ranking[[nm]])] <- NA_real_
    activity_sort <- ifelse(is.finite(pathway_ranking$median_activity_percentile_retained), pathway_ranking$median_activity_percentile_retained, -Inf)
    weighted_sort <- ifelse(is.finite(pathway_ranking$median_weighted_score_retained), pathway_ranking$median_weighted_score_retained, -Inf)
    corr_sort <- ifelse(is.finite(pathway_ranking$median_primary_correlation_retained), pathway_ranking$median_primary_correlation_retained, -Inf)
    if (identical(settings$significance_tail, "Absolute correlation (two-sided)")) corr_sort <- abs(corr_sort)
    pathway_ranking <- pathway_ranking[order(
        -pathway_ranking$retained_high_activity_spots,
        -pathway_ranking$largest_connected_component,
        -activity_sort,
        -weighted_sort,
        -corr_sort,
        pathway_ranking$best_significance_fdr,
        na.last = TRUE
    ), , drop = FALSE]
    pathway_ranking$global_rank <- seq_len(nrow(pathway_ranking))
    write.csv(pathway_ranking, file.path(outdir, "pathway_global_spatial_ranking.csv"), row.names = FALSE)

    retained_high_activity_pathways <- pathway_ranking[pathway_ranking$high_relative_activity_region_detected, , drop = FALSE]
    retained_high_activity_pathways$retained_region_rank <- seq_len(nrow(retained_high_activity_pathways))
    if (isTRUE(settings$export_most_represented_pathways)) {
        write.csv(retained_high_activity_pathways, file.path(outdir, "pathways_with_retained_high_relative_activity_regions.csv"), row.names = FALSE)
    }

    dominant <- setNames(rep("None", length(all_cells)), all_cells)
    dominant_activity <- setNames(rep(NA_real_, length(all_cells)), all_cells)
    dominant_weighted_score <- setNames(rep(NA_real_, length(all_cells)), all_cells)
    dominant_corr <- setNames(rep(NA_real_, length(all_cells)), all_cells)
    dominant_fdr <- setNames(rep(NA_real_, length(all_cells)), all_cells)
    for (cell in all_cells) {
        candidate <- rownames(retained)[retained[, cell]]
        if (!length(candidate)) next
        corr_vals <- primary_correlation[candidate, cell]
        rank_vals <- if (identical(settings$significance_tail, "Absolute correlation (two-sided)")) abs(corr_vals) else corr_vals
        best <- candidate[order(-score_percentile[candidate, cell], -score_raw[candidate, cell], -rank_vals, significance_fdr[candidate, cell], na.last = TRUE)][1L]
        dominant[cell] <- best
        dominant_activity[cell] <- score_percentile[best, cell]
        dominant_weighted_score[cell] <- score_raw[best, cell]
        dominant_corr[cell] <- primary_correlation[best, cell]
        dominant_fdr[cell] <- significance_fdr[best, cell]
    }
    dominant_table <- data.frame(
        spot = all_cells,
        dominant_pathway = unname(dominant[all_cells]),
        dominant_within_tissue_activity_percentile = unname(dominant_activity[all_cells]),
        dominant_weighted_footprint_score = unname(dominant_weighted_score[all_cells]),
        complementary_primary_correlation = unname(dominant_corr[all_cells]),
        complementary_correlation_significance_fdr = unname(dominant_fdr[all_cells]),
        stringsAsFactors = FALSE
    )
    write.csv(dominant_table, file.path(outdir, "dominant_pathway_per_spot.csv"), row.names = FALSE)

    for (p in rownames(primary_correlation)) {
        safe <- sanitize_name(p)
        corr_col <- paste0("PF_", safe, "_correlation")
        activity_col <- paste0("PF_", safe, "_activity")
        threshold_col <- paste0("PF_", safe, "_threshold")
        retained_col <- paste0("PF_", safe, "_retained_high_activity_region")
        object <- add_numeric_metadata(object, corr_col, setNames(primary_correlation[p, ], all_cells))
        object <- add_numeric_metadata(object, activity_col, setNames(score_percentile[p, ], all_cells))
        threshold_values <- setNames(ifelse(initial_significant[p, ], "Passes thresholds", "Does not pass"), all_cells)
        object <- add_factor_metadata(object, threshold_col, threshold_values, levels = c("Does not pass", "Passes thresholds"))
        retained_values <- setNames(ifelse(retained[p, ], "Retained high-activity region", "No retained high-activity region"), all_cells)
        object <- add_factor_metadata(object, retained_col, retained_values, levels = c("No retained high-activity region", "Retained high-activity region"))
    }
    object <- add_factor_metadata(object, "PF_Dominant_Pathway", dominant)

    set_status("Creating spatial maps...", 85)
    plot_root <- file.path(outdir, "Pathway_Footprint_Maps")
    dir.create(plot_root, recursive = TRUE, showWarnings = FALSE)

    for (image_name in image_names) {
        image_dir <- file.path(plot_root, sanitize_name(image_name))
        dir.create(image_dir, recursive = TRUE, showWarnings = FALSE)

        for (p in rownames(primary_correlation)) {
            safe <- sanitize_name(p)
            corr_col <- paste0("PF_", safe, "_correlation")
            activity_col <- paste0("PF_", safe, "_activity")
            threshold_col <- paste0("PF_", safe, "_threshold")
            retained_col <- paste0("PF_", safe, "_retained_high_activity_region")

            if (isTRUE(settings$output_primary_activity_only)) {
                try(plot_primary_activity_passed_only(
                    object,
                    image_name,
                    threshold_col,
                    p,
                    file.path(image_dir, paste0(safe, "_primary_activity_passing_spots_only.png"))
                ), silent = TRUE)
            } else {
                try(plot_correlation_pathway(
                    object, image_name, corr_col, p, settings$primary_correlation,
                    file.path(image_dir, paste0(safe, "_", tolower(settings$primary_correlation), "_correlation.png"))
                ), silent = TRUE)
                try(plot_continuous_pathway(
                    object, image_name, activity_col, p,
                    file.path(image_dir, paste0(safe, "_weighted_activity_percentile.png"))
                ), silent = TRUE)
                try(plot_threshold_pathway(
                    object, image_name, threshold_col, p,
                    file.path(image_dir, paste0(safe, "_spots_passing_enabled_thresholds.png"))
                ), silent = TRUE)
                try(plot_retained_activity_pathway(
                    object, image_name, retained_col, p,
                    file.path(image_dir, paste0(safe, "_retained_high_relative_activity_region.png"))
                ), silent = TRUE)
            }
        }

        if (!isTRUE(settings$output_primary_activity_only)) {
            try({
                dominant_plot <- Seurat::SpatialDimPlot(
                    object,
                    images = image_name,
                    group.by = "PF_Dominant_Pathway",
                    label = FALSE
                ) + ggplot2::ggtitle("Dominant retained high-relative-activity pathway footprint")
                ggplot2::ggsave(file.path(image_dir, "Dominant_Pathway_Fingerprint.png"), dominant_plot, width = 10, height = 8, dpi = 300)
            }, silent = TRUE)
        }
    }

    summarize_annotation_context(object, long_stats, retained, outdir)

    if (isTRUE(settings$save_debug_matrices)) {
        write.csv(data.frame(pathway = rownames(primary_correlation), primary_correlation, check.names = FALSE), file.path(outdir, paste0(tolower(settings$primary_correlation), "_correlation_matrix.csv")), row.names = FALSE)
        write.csv(data.frame(pathway = rownames(pearson), pearson, check.names = FALSE), file.path(outdir, "pearson_correlation_matrix.csv"), row.names = FALSE)
        write.csv(data.frame(pathway = rownames(spearman), spearman, check.names = FALSE), file.path(outdir, "spearman_correlation_matrix.csv"), row.names = FALSE)
        write.csv(data.frame(pathway = rownames(classical_corr_p), classical_corr_p, check.names = FALSE), file.path(outdir, "classical_primary_correlation_p_matrix.csv"), row.names = FALSE)
        write.csv(data.frame(pathway = rownames(classical_fdr), classical_fdr, check.names = FALSE), file.path(outdir, "classical_primary_correlation_fdr_matrix.csv"), row.names = FALSE)
        write.csv(data.frame(pathway = rownames(pmat), pmat, check.names = FALSE), file.path(outdir, "empirical_correlation_p_matrix.csv"), row.names = FALSE)
        write.csv(data.frame(pathway = rownames(empirical_fdr), empirical_fdr, check.names = FALSE), file.path(outdir, "empirical_correlation_fdr_matrix.csv"), row.names = FALSE)
        write.csv(data.frame(pathway = rownames(significance_p), significance_p, check.names = FALSE), file.path(outdir, "significance_p_used_for_filtering_matrix.csv"), row.names = FALSE)
        write.csv(data.frame(pathway = rownames(significance_fdr), significance_fdr, check.names = FALSE), file.path(outdir, "significance_fdr_used_for_filtering_matrix.csv"), row.names = FALSE)
        write.csv(data.frame(pathway = rownames(score_raw), score_raw, check.names = FALSE), file.path(outdir, "weighted_footprint_scores_raw_matrix.csv"), row.names = FALSE)
        write.csv(data.frame(pathway = rownames(score_percentile), score_percentile, check.names = FALSE), file.path(outdir, "weighted_footprint_activity_percentile_matrix.csv"), row.names = FALSE)
        write.csv(data.frame(pathway = rownames(initial_significant), initial_significant, check.names = FALSE), file.path(outdir, "spots_passing_enabled_thresholds_matrix.csv"), row.names = FALSE)
        write.csv(data.frame(pathway = rownames(retained), retained, check.names = FALSE), file.path(outdir, "retained_high_relative_activity_region_matrix.csv"), row.names = FALSE)
        append_log("Detailed debug tables and pathway-by-spot matrices were saved.")
    } else {
        append_log("Detailed debug tables and pathway-by-spot matrices were not saved (Save detailed debug tables and matrices = off).")
    }

    settings_table <- data.frame(
        setting = names(settings),
        value = vapply(settings, function(x) paste(x, collapse = ","), character(1)),
        stringsAsFactors = FALSE
    )
    write.csv(settings_table, file.path(outdir, "settings_used.csv"), row.names = FALSE)
    capture.output(sessionInfo(), file = file.path(outdir, "sessionInfo.txt"))
    if (is.null(settings$results_workspace) || !nzchar(settings$results_workspace)) {
        stop("A sample results folder such as Results/Sample_01 is required so the final RDS can be stored in Seurat_RDS.")
    }
    inherited_rds_tags <- visium_rds_operation_tags(settings$input_rds, "S06")
    output_rds_file <- visium_tagged_rds_path(settings$results_workspace, "7_Pathway_Footprint_Analysis", "S07", paste0(inherited_rds_tags, "_PathwayFP"))
    saveRDS(object, output_rds_file, compress = FALSE)
    if (!is.null(settings$results_workspace) && nzchar(settings$results_workspace)) {
    }

    set_status("Completed successfully.", 100)
    append_log("Analysis completed successfully.")
    append_log("Final Seurat object: ", output_rds_file)

    list(
        object = object,
        model = weighted_model,
        score = score_raw,
        pearson = pearson,
        spearman = spearman,
        primary_correlation = primary_correlation,
        classical_correlation_p = classical_corr_p,
        classical_fdr = classical_fdr,
        empirical_p = pmat,
        empirical_fdr = empirical_fdr,
        significance_p = significance_p,
        significance_fdr = significance_fdr,
        passes_thresholds = initial_significant,
        retained = retained,
        long_stats = long_stats,
        pathway_ranking = pathway_ranking,
        retained_high_activity_pathways = retained_high_activity_pathways,
        dominant = dominant_table,
        component_summary = component_summary,
        settings = settings
    )
}

show_retained_high_activity_pathways_gui <- function(ranking, output_directory) {
    if (!requireNamespace("tcltk", quietly = TRUE)) return(invisible(NULL))

    ranking <- as.data.frame(ranking, stringsAsFactors = FALSE)
    result_window <- tcltk::tktoplevel(background = "#F4F7FB")
    tcltk::tkwm.title(result_window, "Retained High-Activity Pathway Regions - Ranked Results")
    screen_width <- as.integer(tcltk::tclvalue(tcltk::tkwinfo("screenwidth", result_window)))
    screen_height <- as.integer(tcltk::tclvalue(tcltk::tkwinfo("screenheight", result_window)))
    result_width <- min(1180L, max(760L, screen_width - 100L), screen_width)
    result_height <- min(720L, max(540L, screen_height - 120L), screen_height)
    tcltk::tkwm.geometry(result_window, sprintf("%dx%d", result_width, result_height))
    tcltk::tkgrid.columnconfigure(result_window, 0L, weight = 1L)
    tcltk::tkgrid.rowconfigure(result_window, 1L, weight = 1L)

    header <- tcltk::tkframe(result_window, background = "#6A1B9A", padx = 18L, pady = 10L)
    tcltk::tkgrid(header, row = 0L, column = 0L, sticky = "ew")
    tcltk::tkpack(tcltk::tklabel(header, text = "PATHWAYS WITH RETAINED HIGH-RELATIVE-ACTIVITY REGIONS", background = "#6A1B9A", foreground = "white", font = "TkHeadingFont", anchor = "w"), fill = "x")
    tcltk::tkpack(tcltk::tklabel(header, text = "Only pathways with spots retained after all enabled thresholds and the connected-region rule are listed.", background = "#6A1B9A", foreground = "white", anchor = "w"), fill = "x", pady = c(3L, 0L))

    table_frame <- tcltk::tkframe(result_window, background = "white", padx = 10L, pady = 10L)
    tcltk::tkgrid(table_frame, row = 1L, column = 0L, sticky = "nsew", padx = 12L, pady = 10L)
    tcltk::tkgrid.columnconfigure(table_frame, 0L, weight = 1L)
    tcltk::tkgrid.rowconfigure(table_frame, 1L, weight = 1L)
    tcltk::tkgrid(
        tcltk::tklabel(table_frame, text = "Ranking order: retained high-activity spots, largest connected region, median activity percentile, weighted score, correlation, then optional FDR.", background = "#FFF8E1", foreground = "#5D4037", anchor = "w", justify = "left", padx = 8L, pady = 6L),
        row = 0L, column = 0L, columnspan = 2L, sticky = "ew", pady = c(0L, 8L)
    )

    columns <- c("rank", "pathway", "spots", "percent", "largest", "fdr", "correlation")
    tree <- tcltk::ttktreeview(table_frame, columns = columns, show = "headings", height = 18L)
    headings <- c("Rank", "Pathway", "Retained high-activity spots", "% tissue retained", "Largest region", "Best optional FDR", "Median correlation")
    widths <- c(60L, 310L, 105L, 90L, 125L, 110L, 130L)
    for (index in seq_along(columns)) {
        tcltk::tcl(tree, "heading", columns[[index]], text = headings[[index]])
        tcltk::tcl(tree, "column", columns[[index]], width = widths[[index]], anchor = if (index == 2L) "w" else "center")
    }
    vertical <- tcltk::ttkscrollbar(table_frame, orient = "vertical", command = function(...) tcltk::tkyview(tree, ...))
    tcltk::tcl(tree, "configure", yscrollcommand = function(...) tcltk::tkset(vertical, ...))
    tcltk::tkgrid(tree, row = 1L, column = 0L, sticky = "nsew")
    tcltk::tkgrid(vertical, row = 1L, column = 1L, sticky = "ns")

    if (nrow(ranking)) {
        for (row_index in seq_len(nrow(ranking))) {
            row <- ranking[row_index, , drop = FALSE]
            values <- c(
                as.character(row$retained_region_rank),
                as.character(row$pathway),
                as.character(row$retained_high_activity_spots),
                sprintf("%.2f", row$percent_tissue_in_retained_high_activity_region),
                as.character(row$largest_connected_component),
                if (is.finite(row$best_significance_fdr)) format(row$best_significance_fdr, digits = 3L, scientific = TRUE) else "",
                if (is.finite(row$median_primary_correlation_retained)) sprintf("%.3f", row$median_primary_correlation_retained) else ""
            )
            tcltk::tcl(tree, "insert", "", "end", values = values)
        }
    } else {
        tcltk::tcl(tree, "insert", "", "end", values = c("", "No retained high-relative-activity region detected", "0", "0.00", "", "", ""))
    }

    footer <- tcltk::tkframe(result_window, background = "#E8EEF7", padx = 14L, pady = 9L)
    tcltk::tkgrid(footer, row = 2L, column = 0L, sticky = "ew")
    tcltk::tkpack(tcltk::tklabel(footer, text = paste("Saved list:", file.path(output_directory, "pathways_with_retained_high_relative_activity_regions.csv")), background = "#E8EEF7", foreground = "#46546A", anchor = "w"), side = "left", fill = "x", expand = TRUE)
    open_output <- function() {
        if (.Platform$OS.type == "windows") shell.exec(normalizePath(output_directory, winslash = "\\", mustWork = TRUE))
    }
    tcltk::tkpack(tcltk::tkbutton(footer, text = "Close", command = function() tcltk::tkdestroy(result_window), background = "white", foreground = "#46546A", padx = 18L), side = "right", padx = 4L)
    tcltk::tkpack(tcltk::tkbutton(footer, text = "OPEN OUTPUT FOLDER", command = open_output, background = "#1565C0", foreground = "white", activebackground = "#0D47A1", activeforeground = "white", padx = 14L), side = "right", padx = 4L)

    tcltk::tkfocus(result_window)
    tcltk::tkwait.window(result_window)
    invisible(NULL)
}

SCRIPT7_RUN_GUI <- interactive() || !length(commandArgs(trailingOnly = TRUE)) || isTRUE(SCRIPT7_CLI$gui)
if (isTRUE(SCRIPT7_CLI$cli)) SCRIPT7_RUN_GUI <- FALSE
SCRIPT7_FROM_DESKTOP_GUI <- FALSE
SCRIPT7_ANALYSIS_COMPLETE <- FALSE

if (SCRIPT7_RUN_GUI) {
    default_database_gui <- ""
    default_results_workspace_gui <- ""

    script7_builtin_pathway_choices <- paste0(
        "[PROGENy] ",
        c("Androgen", "EGFR", "Estrogen", "Hypoxia", "JAK-STAT", "MAPK", "NFkB", "PI3K", "p53", "TGFb", "TNFa", "Trail", "VEGF", "WNT")
    )
    script7_fingerprint_organisms <- function(database_path = "") {
        if (!nzchar(trimws(database_path))) return(character(0))
        database_preview <- normalize_model_column_names(read_delimited_flexible(database_path))
        if (!("organism" %in% names(database_preview))) {
            stop("The fingerprint database must contain an Organism column.")
        }
        organisms <- unique(trimws(as.character(database_preview$organism)))
        organisms[nzchar(organisms)]
    }
    initial_organism_choices <- tryCatch(
        unique(c("Human", "Mouse", script7_fingerprint_organisms(default_database_gui))),
        error = function(e) {
            warning("The default fingerprint database could not populate the organism list: ", conditionMessage(e))
            c("Human", "Mouse")
        }
    )
    script7_gui_source_choices <- function(fingerprint_database = "", organism = "Human") {
        organism_key <- tolower(trimws(organism))
        progeny_source <- if (organism_key %in% c("human", "mouse")) "PROGENy" else character(0)
        custom_sources <- character(0)
        if (nzchar(trimws(fingerprint_database))) {
            custom_model <- load_fingerprint_pathways_database(fingerprint_database, organism)
            if (!is.null(custom_model)) custom_sources <- sort(unique(custom_model$source))
        }
        unique(c("All sources", progeny_source, custom_sources))
    }
    initial_source_choices <- tryCatch(
        script7_gui_source_choices(default_database_gui, "Human"),
        error = function(e) {
            warning("The default fingerprint database could not populate the source list: ", conditionMessage(e))
            c("All sources", "PROGENy")
        }
    )
    script7_gui_pathway_choices <- function(fingerprint_database = "", organism = "Human", source = "All sources") {
        organism_key <- tolower(trimws(organism))
        source_key <- tolower(trimws(source))
        all_sources <- source_key %in% c("all", "all sources")
        progeny_choices <- if (organism_key %in% c("human", "mouse") && (all_sources || identical(source_key, "progeny"))) script7_builtin_pathway_choices else character(0)
        custom_choices <- character(0)
        if (nzchar(trimws(fingerprint_database))) {
            custom_model <- load_fingerprint_pathways_database(fingerprint_database, organism)
            if (!is.null(custom_model) && !all_sources) {
                if (identical(source_key, "progeny")) {
                    custom_model <- NULL
                } else {
                    custom_model <- custom_model[tolower(custom_model$source) == source_key, , drop = FALSE]
                    if (!nrow(custom_model)) custom_model <- NULL
                }
            }
            if (!is.null(custom_model)) custom_choices <- sort(unique(custom_model$pathway))
        }
        unique(c("all", progeny_choices, custom_choices))
    }
    initial_pathway_choices <- tryCatch(
        script7_gui_pathway_choices(default_database_gui, "Human", "All sources"),
        error = function(e) {
            warning("The default fingerprint database could not populate the GUI pathway list: ", conditionMessage(e))
            c("all", script7_builtin_pathway_choices)
        }
    )

    gui_values <- visium_desktop_gui(
        "Script 7 - Pathway-Footprint Analysis",
        list(
            list(name = "results_dir", label = "Sample results folder (for example Results/Sample_01)", value = default_results_workspace_gui, type = "directory", group = "Files", required = TRUE, must_exist = TRUE),
            list(name = "input_rds", label = "Step 6 resolution-specific deconvolution/region-DE Seurat RDS", value = "", type = "file", group = "Files", required = TRUE, must_exist = TRUE, browse_initial_dir = function(values) file.path(values$results_dir, "Seurat_RDS"), path_pattern = "_S06_.*_Clstr[0-9]+(\\.[0-9]+)?_Svg(Moran|Mark)_(DeconvLT|DeconvRCTD(Full|Doublet|Multi)?|NoDeconv)_RegDE\\.rds$", path_message = "a tagged Step 6 RDS preserving clustering resolution, SVG method, and deconvolution mode, such as *_Clstr0.40_SvgMoran_DeconvRCTDFull_RegDE.rds"),
            list(name = "workspace_help", type = "info", group = "Files", text = "After selecting the sample results folder, Browse opens its Seurat_RDS folder. Select the exact Step 6 RDS to analyze. Its cumulative tags are preserved and PathwayFP is appended to the Step 7 output filename."),
            list(name = "fingerprint_database", label = "Optional custom fingerprint pathway database", value = default_database_gui, type = "file", group = "Files"),
            list(name = "organism", label = "Organism", value = "Human", type = "editable_choice", choices = initial_organism_choices, group = "Pathways", help = "Select Human or Mouse for the corresponding built-in PROGENy model. Organisms read from the fingerprint database are also offered. You may type a database organism exactly as written and press Enter. PROGENy pathways are excluded for organisms other than Human or Mouse."),
            list(name = "source", label = "Source", value = "All sources", type = "choice", choices = initial_source_choices, choice_sources = c("fingerprint_database", "organism"), choice_loader = script7_gui_source_choices, group = "Pathways", help = "Filters pathways by the Source column after Organism filtering. All sources combines every matching custom source with PROGENy when supported. PROGENy selects only the built-in model. Other entries, such as KEGG or CUSTOM WEIGHTED, select only matching fingerprint rows."),
            list(name = "top_genes", label = "Most significant PROGENy genes per pathway", value = 100L, type = "integer", group = "Pathways", help = "Number of highest-priority PROGENy response genes retained for each pathway. Genes are ordered by available model FDR, then model P value, then absolute perturbation weight. This setting does not shorten custom fingerprint pathways."),
            list(name = "pathways", label = "Pathways to analyze", value = "", type = "multichoice", choices = initial_pathway_choices, choice_sources = c("fingerprint_database", "organism", "source"), choice_loader = script7_gui_pathway_choices, popup_selector = TRUE, allow_empty_selection = TRUE, group = "Pathways", required = TRUE, help = "The list starts with no pathway selected. For simple individual selection without Ctrl, use OPEN LARGE PATHWAY SELECTOR: click pathway checkboxes, then APPLY SELECTION AND CLOSE. Shift remains available for a consecutive range in the main list."),
            list(name = "assay", label = "Expression assay", value = "Spatial", type = "choice", choices = c("Spatial", "SCT"), group = "Expression", help = "Select the Seurat assay supplying footprint-gene expression. Spatial usually preserves broad gene coverage; SCT uses SCTransform-corrected values. The selected assay must exist in the input object."),
            list(name = "layer", label = "Expression layer", value = "data", type = "choice", choices = c("data", "counts", "scale.data"), group = "Expression", inline_with_previous = TRUE, help = "data contains normalized expression and is the usual choice. counts contains raw Count_RNAs. scale.data contains scaled values but may include only variable Feature_Genes. If the requested layer is unavailable, the script reports and uses an available fallback."),
            list(name = "tissue_normalization", label = "Tissue gene normalization", value = "Tissue percentile centered", type = "choice", choices = c("Tissue percentile centered", "Robust min-max centered", "Gene z-score across tissue", "Median-centered assay values"), group = "Expression", help = "Normalizes each footprint gene across tissue spots before comparison with pathway weights. Tissue percentile centered uses ranks from -0.5 to 0.5; robust min-max clips outliers then rescales; gene z-score centers and scales by standard deviation; median-centered subtracts the tissue median without range scaling."),
            list(name = "lower_quantile", label = "Robust lower quantile", value = 0.01, type = "number", group = "Expression", help = "Lower clipping boundary used only by Robust min-max centered normalization. A value of 0.01 clips expression below the first percentile before rescaling."),
            list(name = "upper_quantile", label = "Robust upper quantile", value = 0.99, type = "number", group = "Expression", inline_with_previous = TRUE, help = "Upper clipping boundary used only by Robust min-max centered normalization. A value of 0.99 clips expression above the 99th percentile. It must be greater than the lower quantile."),
            list(name = "minimum_genes_present", label = "Minimum footprint Feature_Genes found", value = 15L, type = "integer", group = "Expression", help = "Minimum number of pathway footprint Feature_Genes that must match gene features in the selected assay. A pathway with fewer matched genes is unavailable because its weighted score would be based on insufficient footprint coverage."),
            list(name = "minimum_coverage", label = "Minimum Feature_Genes coverage", value = 0.20, type = "number", group = "Expression", inline_with_previous = TRUE, help = "Minimum fraction of a pathway's model Feature_Genes that must be found in the assay, from 0 to 1. Both this fraction and the minimum Feature_Genes count must pass."),
            list(name = "use_spatial_filter", label = "Require touching threshold-passing spots", value = TRUE, type = "boolean_number", boolean_text = "Enabled", number_name = "minimum_adjacent_spots", number_label = "Minimum number of spots", number_value = 4L, number_type = "integer", group = "Expression", help = "Tick Enabled to retain only connected groups containing at least the minimum number of spots that pass every enabled threshold. Disable it to keep every threshold-passing spot without a connected-region requirement."),
            list(name = "correlation_meaning_help", type = "info", group = "Correlation", text = "The signed weighted footprint score is the primary pathway activity measure. Correlation is complementary: it asks whether the across-gene expression pattern resembles the signed footprint, but it does not replace the weighted activity score. Spearman uses gene ranks; Pearson measures a linear pattern match."),
            list(name = "primary_correlation", label = "Complementary fingerprint correlation", value = "Spearman", type = "choice", choices = c("Spearman", "Pearson"), group = "Correlation"),
            list(name = "significance_source", label = "Optional correlation P/FDR source", value = "Classical correlation P (fast)", type = "choice", choices = c("Empirical weight permutation", "Classical correlation P (fast)"), group = "Correlation"),
            list(name = "permutations", label = "Number of empirical weight permutations", value = 500L, type = "integer", group = "Correlation"),
            list(name = "random_seed", label = "Random seed for reproducible permutations", value = 12345L, type = "integer", group = "Correlation", help = "Initializes the random number generator used for empirical weight permutations so repeated runs with the same data and settings reproduce the same empirical P values."),
            list(name = "correlation_significance_help", type = "info", group = "Correlation", text = "Correlation testing is permanently a positive fingerprint match (one-sided). Empirical significance permutes pathway weights to form a null distribution; more permutations improve P-value resolution (approximately 1/(permutations + 1)) but take longer. Classical P is faster and uses the correlation plus the number of matched genes."),
            list(name = "threshold_selection_help", type = "info", group = "Thresholds", text = "Weighted activity percentile is the primary default filter. Correlation and its P/FDR filters are optional compatibility checks and start disabled. Every enabled cutoff is combined with AND logic."),
            list(name = "fdr_scope", label = "FDR scope (select one)", value = "Per spot across pathways", type = "radio", orientation = "vertical", choices = c("Per spot across pathways", "Per pathway across spots", "Global pathway x spot"), group = "Thresholds", help = "Select which family of P values receives Benjamini-Hochberg correction. Per spot compares pathways within each spot; per pathway compares spots for each pathway; global corrects every pathway-by-spot result together."),
            list(name = "use_correlation_threshold", label = "Optional correlation cutoff", value = FALSE, type = "boolean_number", boolean_text = "Enabled", number_name = "correlation_threshold", number_label = "Minimum correlation", number_value = 0.50, group = "Thresholds", help = "Optional compatibility filter. Enable it only when the pathway's across-gene expression pattern must also match its footprint weights."),
            list(name = "use_significance_p_threshold", label = "Optional correlation-P cutoff", value = FALSE, type = "boolean_number", boolean_text = "Enabled", number_name = "significance_p_threshold", number_label = "Maximum P", number_value = 0.05, group = "Thresholds", help = "Optional correlation significance filter. It is not a significance test of the weighted activity magnitude itself."),
            list(name = "use_fdr_threshold", label = "Optional correlation-FDR cutoff", value = FALSE, type = "boolean_number", boolean_text = "Enabled", number_name = "fdr_threshold", number_label = "Maximum FDR", number_value = 0.05, group = "Thresholds", help = "Optional BH-adjusted correlation filter. It is not an adjusted P value for the weighted activity magnitude itself."),
            list(name = "use_activity_threshold", label = "Primary weighted-activity percentile cutoff", value = TRUE, type = "boolean_number", boolean_text = "Enabled", number_name = "activity_percentile_threshold", number_label = "Minimum percentile", number_value = 0.75, group = "Thresholds", help = "Enabled by default. For each pathway separately, 0.75 retains spots in that pathway's top tissue quartile. This is a within-tissue relative activity threshold, not an absolute cutoff shared across pathways or samples."),
            list(name = "threshold_logic_help", type = "info", group = "Thresholds", text = "Activity percentile ranks each pathway's signed weighted score across spots in this tissue. It supports spatial localization within the same pathway, but values should not be interpreted as absolute activity or directly compared between pathways or separate samples."),
            list(name = "parallelize_pathways", label = "Parallel computation of pathways", value = TRUE, type = "boolean_number", boolean_text = "Enabled", number_name = "cpu_cores", number_label = "Number of CPU cores", number_value = default_parallel_cores(), number_type = "integer", group = "Output", help = "When enabled, independent pathway score calculations and empirical pathway permutation tests are distributed across the requested CPU cores. Windows uses PSOCK workers. The effective number of workers is capped by the number of pathways and detected logical CPU cores."),
            list(name = "output_primary_activity_only", label = "Output only primary-activity passing-spots image per pathway", value = FALSE, type = "boolean", boolean_text = "Enabled", group = "Output", help = "When enabled, output only one spatial image per pathway. Spots passing every enabled pathway threshold are shown in fluorescent green; spots that fail are transparent/not represented, and no legend is displayed on the right. Correlation, activity-percentile, threshold, retained-region, and dominant-pathway images are suppressed."),
            list(name = "export_most_represented_pathways", label = "Export pathways with retained high-activity regions", value = TRUE, type = "boolean", boolean_text = "Enabled", group = "Output", help = "Enabled by default: save pathways_with_retained_high_relative_activity_regions.csv, a ranked list of pathways retained in at least one spot after every enabled threshold and the connected-region rule. A retained region indicates high relative activity within this tissue; it does not by itself prove absolute pathway presence."),
            list(name = "save_debug_matrices", label = "Save detailed debug tables and matrices", value = FALSE, type = "boolean", boolean_text = "Enabled", group = "Output", help = "Off by default: save only the main biological pathway summaries, spatial maps, final Seurat RDS, and run settings. Enable this only when investigating the calculation: it also saves gene-coverage checks, per-spot technical ranking tables, spatial-filter diagnostics, and the large pathway-by-spot matrix CSV files.")
        ),
        accent = "#6A1B9A",
        compact_files = TRUE,
        top_right_group = "Expression",
        second_row_right_group = "Output"
    )
    SCRIPT7_CLI <- modifyList(SCRIPT7_CLI, gui_values)
    SCRIPT7_FROM_DESKTOP_GUI <- TRUE
    SCRIPT7_RUN_GUI <- FALSE
}

if (!SCRIPT7_RUN_GUI) {
    default_database <- ""
    results_workspace <- visium_validate_results_workspace(visium_option(SCRIPT7_CLI, "results-dir", "", "path"))
    resolved_input_rds <- visium_option(SCRIPT7_CLI, "input-rds", "", "path")
    if (!nzchar(resolved_input_rds) || !file.exists(resolved_input_rds)) {
        stop("Select the Step 6 deconvolution/region-DE Seurat RDS explicitly with --input-rds.")
    }
    settings <- list(
        results_workspace = results_workspace,
        input_rds = resolved_input_rds,
        output_directory = visium_stage_directory(results_workspace, "7_Pathway_Footprint_Analysis", create = TRUE),
        organism = visium_option(SCRIPT7_CLI, "organism", "Human"),
        source = visium_option(SCRIPT7_CLI, "source", "All sources"),
        fingerprint_database = visium_option(SCRIPT7_CLI, "fingerprint-database", default_database, "path"),
        top_genes = visium_option(SCRIPT7_CLI, "top-genes", 100L, "integer"),
        assay = visium_option(SCRIPT7_CLI, "assay", "Spatial"),
        layer = visium_option(SCRIPT7_CLI, "layer", "data"),
        tissue_normalization = visium_option(SCRIPT7_CLI, "tissue-normalization", "Tissue percentile centered"),
        lower_quantile = visium_option(SCRIPT7_CLI, "lower-quantile", 0.01, "number"),
        upper_quantile = visium_option(SCRIPT7_CLI, "upper-quantile", 0.99, "number"),
        minimum_genes_present = visium_option(SCRIPT7_CLI, "minimum-genes-present", 15L, "integer"),
        minimum_coverage = visium_option(SCRIPT7_CLI, "minimum-coverage", 0.20, "number"),
        primary_correlation = visium_option(SCRIPT7_CLI, "primary-correlation", "Spearman", "choice", c("Spearman", "Pearson")),
        significance_source = visium_option(SCRIPT7_CLI, "significance-source", "Classical correlation P (fast)", "choice", c("Empirical weight permutation", "Classical correlation P (fast)")),
        permutations = visium_option(SCRIPT7_CLI, "permutations", 500L, "integer"),
        significance_tail = "Positive fingerprint match (one-sided)",
        fdr_scope = visium_option(SCRIPT7_CLI, "fdr-scope", "Per spot across pathways", "choice", c("Per spot across pathways", "Per pathway across spots", "Global pathway x spot")),
        use_correlation_threshold = visium_option(SCRIPT7_CLI, "use-correlation-threshold", FALSE, "boolean"),
        correlation_threshold = visium_option(SCRIPT7_CLI, "correlation-threshold", 0.50, "number"),
        use_significance_p_threshold = visium_option(SCRIPT7_CLI, "use-significance-p-threshold", FALSE, "boolean"),
        significance_p_threshold = visium_option(SCRIPT7_CLI, "significance-p-threshold", 0.05, "number"),
        use_fdr_threshold = visium_option(SCRIPT7_CLI, "use-fdr-threshold", FALSE, "boolean"),
        fdr_threshold = visium_option(SCRIPT7_CLI, "fdr-threshold", 0.05, "number"),
        use_activity_threshold = visium_option(SCRIPT7_CLI, "use-activity-threshold", TRUE, "boolean"),
        activity_percentile_threshold = visium_option(SCRIPT7_CLI, "activity-percentile-threshold", 0.75, "number"),
        use_spatial_filter = visium_option(SCRIPT7_CLI, "use-spatial-filter", TRUE, "boolean"),
        minimum_adjacent_spots = visium_option(SCRIPT7_CLI, "minimum-adjacent-spots", 4L, "integer"),
        adjacency_mode = visium_option(SCRIPT7_CLI, "adjacency-mode", "Auto: Visium hex then distance", "choice", c("Auto: Visium hex then distance", "Visium hex direct neighbors", "Distance-based nearest spots")),
        distance_multiplier = visium_option(SCRIPT7_CLI, "distance-multiplier", 1.25, "number"),
        random_seed = visium_option(SCRIPT7_CLI, "random-seed", 12345L, "integer"),
        parallelize_pathways = visium_option(SCRIPT7_CLI, "parallelize-pathways", TRUE, "boolean"),
        cpu_cores = visium_option(SCRIPT7_CLI, "cpu-cores", default_parallel_cores(), "integer"),
        output_primary_activity_only = visium_option(SCRIPT7_CLI, "output-primary-activity-only", FALSE, "boolean"),
        export_most_represented_pathways = visium_option(SCRIPT7_CLI, "export-most-represented-pathways", TRUE, "boolean"),
        save_debug_matrices = visium_option(SCRIPT7_CLI, "save-debug-matrices", FALSE, "boolean")
    )

    if (!file.exists(settings$input_rds)) stop("--input-rds must identify a valid Seurat RDS file.")
    if (nzchar(settings$fingerprint_database) && !file.exists(settings$fingerprint_database)) stop("--fingerprint-database does not exist.")
    if (!nzchar(trimws(settings$organism))) stop("--organism cannot be blank.")
    if (!nzchar(trimws(settings$source))) stop("--source cannot be blank.")
    if (settings$top_genes < 1L) stop("--top-genes must be at least 1.")
    if (settings$minimum_genes_present < 3L) stop("--minimum-genes-present must be at least 3.")
    if (settings$minimum_coverage < 0 || settings$minimum_coverage > 1) stop("--minimum-coverage must be between 0 and 1.")
    if (settings$lower_quantile < 0 || settings$upper_quantile > 1 || settings$lower_quantile >= settings$upper_quantile) stop("Quantiles must satisfy 0 <= lower < upper <= 1.")
    if (settings$permutations < 20L) stop("--permutations must be at least 20.")
    if (settings$correlation_threshold < 0 || settings$correlation_threshold > 1) stop("--correlation-threshold must be between 0 and 1.")
    if (settings$significance_p_threshold <= 0 || settings$significance_p_threshold > 1) stop("--significance-p-threshold must be in (0,1].")
    if (settings$fdr_threshold <= 0 || settings$fdr_threshold > 1) stop("--fdr-threshold must be in (0,1].")
    if (settings$activity_percentile_threshold < 0 || settings$activity_percentile_threshold > 1) stop("--activity-percentile-threshold must be between 0 and 1.")
    if (settings$minimum_adjacent_spots < 1L) stop("--minimum-adjacent-spots must be at least 1.")
    if (settings$distance_multiplier <= 1) stop("--distance-multiplier must be greater than 1.")
    if (settings$cpu_cores < 1L) stop("--cpu-cores must be at least 1.")

    model_full <- load_combined_pathway_library(settings$organism, settings$fingerprint_database, settings$source)
    available_pathways <- sort(unique(model_full$pathway))
    requested <- visium_option(SCRIPT7_CLI, "pathways", "all")
    if (tolower(trimws(requested)) == "all") {
        selected_pathways <- available_pathways
    } else {
        requested_pathways <- visium_csv(requested, "--pathways", empty = FALSE)
        indices <- match(tolower(requested_pathways), tolower(available_pathways))
        if (anyNA(indices)) stop("Unknown pathway(s): ", paste(requested_pathways[is.na(indices)], collapse = ", "))
        selected_pathways <- available_pathways[indices]
    }
    analysis_result <- run_pathway_footprint_analysis(settings, model_full, selected_pathways)
    cat("Script 7 completed. Output:", settings$output_directory, "\n")
    if (SCRIPT7_FROM_DESKTOP_GUI) {
        SCRIPT7_ANALYSIS_COMPLETE <- TRUE
    } else {
        quit(save = "no", status = 0L, runLast = FALSE)
    }
}

if (!SCRIPT7_ANALYSIS_COMPLETE) {

if (!requireNamespace("tcltk", quietly = TRUE)) {
    stop("The R tcltk package is required for the graphical interface.")
}

library(tcltk)

APP <- new.env(parent = emptyenv())
APP$model_full <- NULL
APP$prepared_preview_model <- NULL
APP$object_preview <- NULL
APP$object_path <- NULL
APP$last_result <- NULL

GUI_ACCENT <- "#6A1B9A"
root <- tktoplevel(background = "#F4F7FB")
tkwm.title(root, "Script 7 - Pathway-Footprint Analysis Using Perturbation-Derived Gene Weights")
screen_width <- as.integer(tclvalue(tkwinfo("screenwidth", root)))
screen_height <- as.integer(tclvalue(tkwinfo("screenheight", root)))
window_width <- min(1280L, max(760L, screen_width - 60L), screen_width)
window_height <- min(940L, max(600L, screen_height - 100L), screen_height)
window_x <- max(0L, as.integer((screen_width - window_width) / 2L))
window_y <- max(0L, as.integer((screen_height - window_height) / 3L))
tkwm.geometry(root, sprintf("%dx%d+%d+%d", window_width, window_height, window_x, window_y))
tkwm.minsize(root, min(760L, window_width), min(600L, window_height))

header_frame <- tkframe(root, background = GUI_ACCENT, borderwidth = 0)
tkgrid(header_frame, row = 0, column = 0, sticky = "ew")
tklabel(header_frame, text = "Script 7 - Pathway-Footprint Analysis", background = GUI_ACCENT, foreground = "white", font = "TkHeadingFont", anchor = "w", padx = 18, pady = 8) |>
    tkpack(fill = "x")
tklabel(header_frame, text = "Scores pathway footprints and maps supported activity across tissue spots.", background = GUI_ACCENT, foreground = "white", anchor = "w", padx = 18, pady = 4) |>
    tkpack(fill = "x")

input_rds_var <- tclVar("")
output_dir_var <- tclVar("")
organism_var <- tclVar("Human")
fingerprint_db_var <- tclVar("")
top_genes_var <- tclVar("100")
assay_var <- tclVar("Spatial")
layer_var <- tclVar("data")
normalization_var <- tclVar("Tissue percentile centered")
lower_q_var <- tclVar("0.01")
upper_q_var <- tclVar("0.99")
minimum_genes_var <- tclVar("15")
minimum_coverage_var <- tclVar("0.20")
primary_correlation_var <- tclVar("Spearman")
significance_source_var <- tclVar("Classical correlation P (fast)")
permutations_var <- tclVar("500")
significance_tail_var <- tclVar("Positive fingerprint match (one-sided)")
fdr_scope_var <- tclVar("Per spot across pathways")
use_correlation_threshold_var <- tclVar("0")
correlation_threshold_var <- tclVar("0.50")
use_significance_p_threshold_var <- tclVar("0")
significance_p_threshold_var <- tclVar("0.05")
use_fdr_threshold_var <- tclVar("0")
fdr_threshold_var <- tclVar("0.05")
use_activity_threshold_var <- tclVar("1")
activity_threshold_var <- tclVar("0.75")
use_spatial_filter_var <- tclVar("1")
minimum_adjacent_var <- tclVar("4")
adjacency_mode_var <- tclVar("Auto: Visium hex then distance")
distance_multiplier_var <- tclVar("1.25")
random_seed_var <- tclVar("12345")
status_var <- tclVar("Ready")
progress_var <- tclVar(0)
.GUI$status_var <- status_var
.GUI$progress_var <- progress_var

main <- ttkframe(root, padding = 8)
tkgrid(main, row = 1, column = 0, sticky = "nsew")
tkgrid.columnconfigure(main, 0, weight = 1)
tkgrid.rowconfigure(main, 5, weight = 1)
tkgrid.columnconfigure(root, 0, weight = 1)
tkgrid.rowconfigure(root, 1, weight = 1)

make_path_row <- function(parent, row, label, variable, browse_command, width = 60) {
    ttklabel(parent, text = label, width = 28) |> tkgrid(row = row, column = 0, sticky = "w", padx = 3, pady = 2)
    ttkentry(parent, textvariable = variable, width = width) |> tkgrid(row = row, column = 1, sticky = "ew", padx = 3, pady = 2)
    tkbutton(parent, text = "BROWSE...", command = browse_command, background = "#DCEBFF", foreground = "#174EA6", activebackground = "#C5DCF9", relief = "raised", borderwidth = 1, padx = 10) |> tkgrid(row = row, column = 2, padx = 3, pady = 2)
    tkgrid.columnconfigure(parent, 1, weight = 1)
}

input_frame <- ttklabelframe(main, text = "1. Input / output files", padding = 6)
tkgrid(input_frame, row = 0, column = 0, sticky = "ew", padx = 2, pady = 3)

browse_rds <- function() {
    f <- tclvalue(tkgetOpenFile(filetypes = "{{Seurat RDS} {.rds}} {{All files} *}"))
    if (nzchar(f)) tclvalue(input_rds_var) <- f
}
browse_output <- function() {
    f <- tclvalue(tkchooseDirectory(initialdir = tclvalue(output_dir_var), title = "Choose Script 7 output folder"))
    if (nzchar(f)) tclvalue(output_dir_var) <- f
}
browse_fingerprint_database <- function() {
    f <- tclvalue(tkgetOpenFile(
        initialfile = "Fingerprint_Pathways.tabtxt",
        filetypes = "{{Fingerprint pathway database} {.tabtxt .txt .tsv}} {{All files} *}"
    ))
    if (nzchar(f)) tclvalue(fingerprint_db_var) <- f
}

make_path_row(input_frame, 0, "Final spatial Seurat RDS", input_rds_var, browse_rds)
make_path_row(input_frame, 1, "Output folder", output_dir_var, browse_output)
make_path_row(input_frame, 2, "Fingerprint_Pathways.tabtxt", fingerprint_db_var, browse_fingerprint_database)

model_frame <- ttklabelframe(main, text = "2. Pathway footprint library and gene weights", padding = 6)
tkgrid(model_frame, row = 2, column = 0, sticky = "ew", padx = 2, pady = 3)
for (j in 0:7) tkgrid.columnconfigure(model_frame, j, weight = if (j %in% c(1, 3, 5, 7)) 1 else 0)

ttklabel(model_frame, text = "Organism") |> tkgrid(row = 0, column = 0, sticky = "w")
organism_combo <- ttkcombobox(model_frame, textvariable = organism_var, state = "readonly", values = c("Human", "Mouse"), width = 12)
tkgrid(organism_combo, row = 0, column = 1, sticky = "ew", padx = 3)

ttklabel(model_frame, text = "PROGENy top genes/pathway") |> tkgrid(row = 0, column = 2, sticky = "w")
ttkentry(model_frame, textvariable = top_genes_var, width = 8) |> tkgrid(row = 0, column = 3, sticky = "w", padx = 3)

ttklabel(
    model_frame,
    text = "Library = organism-matched PROGENy (Human/Mouse) + organism-matched fingerprint pathways",
    wraplength = 570
) |> tkgrid(row = 1, column = 0, columnspan = 5, sticky = "w", pady = 3)

install_button <- ttkbutton(model_frame, text = "Install/Check Packages", command = function() {
    tryCatch(install_missing_packages(), error = function(e) show_error("Package installation", conditionMessage(e)))
})
tkgrid(install_button, row = 0, column = 5, rowspan = 2, padx = 4)

pathway_frame <- ttklabelframe(main, text = "3. Select pathway footprints", padding = 6)
tkgrid(pathway_frame, row = 3, column = 0, sticky = "nsew", padx = 2, pady = 3)
tkgrid.columnconfigure(pathway_frame, 0, weight = 1)
tkgrid.rowconfigure(pathway_frame, 1, weight = 1)

pathway_list <- tklistbox(pathway_frame, selectmode = "extended", height = 9, exportselection = FALSE)
pathway_scroll <- ttkscrollbar(pathway_frame, orient = "vertical", command = function(...) tkyview(pathway_list, ...))
tcl(pathway_list, "configure", yscrollcommand = function(...) tkset(pathway_scroll, ...))
tkgrid(pathway_list, row = 1, column = 0, sticky = "nsew")
tkgrid(pathway_scroll, row = 1, column = 1, sticky = "ns")

pathway_button_frame <- ttkframe(pathway_frame)
tkgrid(pathway_button_frame, row = 0, column = 0, columnspan = 2, sticky = "ew", pady = 3)

load_library_gui <- function(show_message = TRUE) {
    tryCatch({
        set_status("Loading pathway library...", 0)
        db_path <- trimws(tclvalue(fingerprint_db_var))
        APP$model_full <- load_combined_pathway_library(tclvalue(organism_var), db_path)
        db_key <- if (nzchar(db_path)) normalizePath(db_path, winslash = "/", mustWork = FALSE) else "<none>"
        APP$model_key <- paste("PROGENy+FingerprintDB", tclvalue(organism_var), db_key, sep = "|")
        paths <- sort(unique(APP$model_full$pathway))
        tkdelete(pathway_list, 0, "end")
        for (p in paths) tkinsert(pathway_list, "end", p)
        if (length(paths)) tcl(pathway_list, "selection", "set", 0, "end")
        append_log("Loaded pathway library with ", length(paths), " pathways and ", nrow(APP$model_full), " gene-pathway rows.")
        set_status("Pathway library loaded.", 0)
        if (show_message) show_info("Pathway library", paste0("Loaded ", length(paths), " pathways. All are selected initially."))
    }, error = function(e) show_error("Load pathway library", conditionMessage(e)))
}

selected_pathways_gui <- function() {
    idx <- as.integer(tkcurselection(pathway_list))
    if (!length(idx)) return(character(0))
    vapply(idx, function(i) tclvalue(tkget(pathway_list, i)), character(1))
}

show_model_genes_gui <- function() {
    tryCatch({
        if (is.null(APP$model_full)) load_library_gui(FALSE)
        selected <- selected_pathways_gui()
        if (!length(selected)) stop("Select at least one pathway.")
        pm <- prepare_weighted_model(
            APP$model_full,
            as.integer(tclvalue(top_genes_var))
        )
        pm <- pm[pm$pathway %in% selected, , drop = FALSE]
        pm <- pm[order(pm$pathway, pm$model_p_value, -abs(pm$effective_weight), na.last = TRUE), , drop = FALSE]

        win <- tktoplevel(root)
        tkwm.title(win, "Selected pathway genes / perturbation weights")
        tkwm.geometry(win, "1050x650")
        txt <- tktext(win, wrap = "none", font = "TkFixedFont")
        ys <- ttkscrollbar(win, orient = "vertical", command = function(...) tkyview(txt, ...))
        xs <- ttkscrollbar(win, orient = "horizontal", command = function(...) tkxview(txt, ...))
        tcl(txt, "configure", yscrollcommand = function(...) tkset(ys, ...), xscrollcommand = function(...) tkset(xs, ...))
        tkgrid(txt, row = 0, column = 0, sticky = "nsew")
        tkgrid(ys, row = 0, column = 1, sticky = "ns")
        tkgrid(xs, row = 1, column = 0, sticky = "ew")
        tkgrid.rowconfigure(win, 0, weight = 1); tkgrid.columnconfigure(win, 0, weight = 1)

        display_cols <- c("source", "pathway_id", "pathway_name", "gene", "ensembl_name", "direction", "perturbation_weight", "model_p_value", "model_fdr", "model_specificity_weight", "effective_weight", "library_type")
        header <- paste(display_cols, collapse = "\t")
        lines <- apply(pm[, display_cols, drop = FALSE], 1L, function(z) paste(z, collapse = "\t"))
        tkinsert(txt, "end", paste(c(header, lines), collapse = "\n"))
    }, error = function(e) show_error("View pathway genes", conditionMessage(e)))
}

export_model_gui <- function() {
    tryCatch({
        if (is.null(APP$model_full)) load_library_gui(FALSE)
        selected <- selected_pathways_gui()
        if (!length(selected)) stop("Select at least one pathway.")
        pm <- prepare_weighted_model(APP$model_full, as.integer(tclvalue(top_genes_var)))
        pm <- pm[pm$pathway %in% selected, , drop = FALSE]
        out <- tclvalue(tkgetSaveFile(initialfile = "selected_pathway_footprint_profiles.csv", defaultextension = ".csv", filetypes = "{{CSV} {.csv}}"))
        if (nzchar(out)) {
            write.csv(pm, out, row.names = FALSE)
            show_info("Export", paste0("Saved:\n", out))
        }
    }, error = function(e) show_error("Export pathway profiles", conditionMessage(e)))
}

btn_load <- ttkbutton(pathway_button_frame, text = "Load / Refresh Pathway Library", command = load_library_gui)
btn_all <- ttkbutton(pathway_button_frame, text = "Select All", command = function() tcl(pathway_list, "selection", "set", 0, "end"))
btn_none <- ttkbutton(pathway_button_frame, text = "Clear", command = function() tcl(pathway_list, "selection", "clear", 0, "end"))
btn_view <- ttkbutton(pathway_button_frame, text = "View Genes + Weights", command = show_model_genes_gui)
btn_export <- ttkbutton(pathway_button_frame, text = "Export Selected Profiles", command = export_model_gui)
tkpack(btn_load, btn_all, btn_none, btn_view, btn_export, side = "left", padx = 3)

score_frame <- ttklabelframe(main, text = "4. Pathway/spot activity, optional correlation tests, and connected-region rules", padding = 6)
tkgrid(score_frame, row = 4, column = 0, sticky = "ew", padx = 2, pady = 3)

labels_values <- list(
    list("Assay", assay_var, c("Spatial", "SCT"), 14),
    list("Layer (counts = raw Count_RNAs)", layer_var, c("data", "counts", "scale.data"), 14),
    list("Tissue gene normalization", normalization_var, c("Tissue percentile centered", "Robust min-max centered", "Gene z-score across tissue", "Median-centered assay values"), 28)
)
col <- 0
for (item in labels_values) {
    ttklabel(score_frame, text = item[[1]]) |> tkgrid(row = 0, column = col, sticky = "w", padx = 2)
    ttkcombobox(score_frame, textvariable = item[[2]], state = "readonly", values = item[[3]], width = item[[4]]) |> tkgrid(row = 0, column = col + 1, sticky = "ew", padx = 2)
    col <- col + 2
}

ttklabel(score_frame, text = "Robust lower q") |> tkgrid(row = 1, column = 0, sticky = "w")
ttkentry(score_frame, textvariable = lower_q_var, width = 8) |> tkgrid(row = 1, column = 1, sticky = "w")
ttklabel(score_frame, text = "Robust upper q") |> tkgrid(row = 1, column = 2, sticky = "w")
ttkentry(score_frame, textvariable = upper_q_var, width = 8) |> tkgrid(row = 1, column = 3, sticky = "w")
ttklabel(score_frame, text = "Min footprint genes found") |> tkgrid(row = 1, column = 4, sticky = "w")
ttkentry(score_frame, textvariable = minimum_genes_var, width = 8) |> tkgrid(row = 1, column = 5, sticky = "w")
ttklabel(score_frame, text = "Min gene coverage") |> tkgrid(row = 1, column = 6, sticky = "w")
ttkentry(score_frame, textvariable = minimum_coverage_var, width = 8) |> tkgrid(row = 1, column = 7, sticky = "w")

ttklabel(score_frame, text = "Complementary correlation") |> tkgrid(row = 2, column = 0, sticky = "w")
ttkcombobox(score_frame, textvariable = primary_correlation_var, state = "readonly", values = c("Spearman", "Pearson"), width = 14) |> tkgrid(row = 2, column = 1, sticky = "w")
ttklabel(score_frame, text = "Significance source") |> tkgrid(row = 2, column = 2, sticky = "w")
ttkcombobox(score_frame, textvariable = significance_source_var, state = "readonly", values = c("Empirical weight permutation", "Classical correlation P (fast)"), width = 26) |> tkgrid(row = 2, column = 3, sticky = "ew")
ttklabel(score_frame, text = "Correlation test") |> tkgrid(row = 2, column = 4, sticky = "w")
ttkcombobox(score_frame, textvariable = significance_tail_var, state = "readonly", values = c("Positive fingerprint match (one-sided)", "Absolute correlation (two-sided)"), width = 31) |> tkgrid(row = 2, column = 5, columnspan = 3, sticky = "ew")

ttkcheckbutton(score_frame, text = "Optional correlation threshold", variable = use_correlation_threshold_var, onvalue = "1", offvalue = "0") |> tkgrid(row = 3, column = 0, sticky = "w")
ttkentry(score_frame, textvariable = correlation_threshold_var, width = 8) |> tkgrid(row = 3, column = 1, sticky = "w")
ttkcheckbutton(score_frame, text = "Optional correlation P threshold", variable = use_significance_p_threshold_var, onvalue = "1", offvalue = "0") |> tkgrid(row = 3, column = 2, sticky = "w")
ttkentry(score_frame, textvariable = significance_p_threshold_var, width = 8) |> tkgrid(row = 3, column = 3, sticky = "w")
ttklabel(score_frame, text = "Empirical permutations") |> tkgrid(row = 3, column = 4, sticky = "w")
ttkentry(score_frame, textvariable = permutations_var, width = 8) |> tkgrid(row = 3, column = 5, sticky = "w")
ttklabel(score_frame, text = "(used only for empirical significance)") |> tkgrid(row = 3, column = 6, columnspan = 2, sticky = "w")

ttkcheckbutton(score_frame, text = "Optional correlation FDR threshold", variable = use_fdr_threshold_var, onvalue = "1", offvalue = "0") |> tkgrid(row = 4, column = 0, sticky = "w")
ttkentry(score_frame, textvariable = fdr_threshold_var, width = 8) |> tkgrid(row = 4, column = 1, sticky = "w")
ttklabel(score_frame, text = "FDR scope") |> tkgrid(row = 4, column = 2, sticky = "w")
ttkcombobox(score_frame, textvariable = fdr_scope_var, state = "readonly", values = c("Per spot across pathways", "Per pathway across spots", "Global pathway x spot"), width = 25) |> tkgrid(row = 4, column = 3, sticky = "ew")
ttkcheckbutton(score_frame, text = "Use primary weighted-activity percentile", variable = use_activity_threshold_var, onvalue = "1", offvalue = "0") |> tkgrid(row = 4, column = 4, sticky = "w")
ttkentry(score_frame, textvariable = activity_threshold_var, width = 8) |> tkgrid(row = 4, column = 5, sticky = "w")
ttklabel(score_frame, text = "(relative within tissue)") |> tkgrid(row = 4, column = 6, sticky = "w")

ttkcheckbutton(score_frame, text = "Require touching threshold-passing spots", variable = use_spatial_filter_var, onvalue = "1", offvalue = "0") |> tkgrid(row = 5, column = 0, sticky = "w")
ttklabel(score_frame, text = "Minimum touching spots") |> tkgrid(row = 5, column = 2, sticky = "w")
ttkentry(score_frame, textvariable = minimum_adjacent_var, width = 8) |> tkgrid(row = 5, column = 3, sticky = "w")
ttklabel(score_frame, text = "Adjacency") |> tkgrid(row = 5, column = 4, sticky = "w")
ttkcombobox(score_frame, textvariable = adjacency_mode_var, state = "readonly", values = c("Auto: Visium hex then distance", "Visium hex direct neighbors", "Distance-based nearest spots"), width = 30) |> tkgrid(row = 5, column = 5, columnspan = 3, sticky = "ew")

ttklabel(score_frame, text = "Distance multiplier") |> tkgrid(row = 6, column = 0, sticky = "w")
ttkentry(score_frame, textvariable = distance_multiplier_var, width = 8) |> tkgrid(row = 6, column = 1, sticky = "w")
ttklabel(score_frame, text = "Random seed") |> tkgrid(row = 6, column = 2, sticky = "w")
ttkentry(score_frame, textvariable = random_seed_var, width = 10) |> tkgrid(row = 6, column = 3, sticky = "w")
ttklabel(score_frame, text = "Empirical null: pathway weights permuted among the same footprint genes") |> tkgrid(row = 6, column = 4, columnspan = 4, sticky = "w")

for (j in 0:7) tkgrid.columnconfigure(score_frame, j, weight = if (j %% 2 == 1) 1 else 0)

inspect_object_gui <- function() {
    tryCatch({
        set_status("Inspecting Seurat object...", 0)
        APP$object_preview <- load_spatial_object(tclvalue(input_rds_var))
        APP$object_path <- normalizePath(tclvalue(input_rds_var), winslash = "/", mustWork = FALSE)
        ass <- available_assays(APP$object_preview)
        preferred <- if ("Spatial" %in% ass) "Spatial" else ass[1L]
        tclvalue(assay_var) <- preferred
        lays <- available_layers(APP$object_preview, preferred)
        if ("data" %in% lays) tclvalue(layer_var) <- "data" else if (length(lays)) tclvalue(layer_var) <- lays[1L]
        msg <- paste0(
            "Spots: ", ncol(APP$object_preview),
            "\nImages: ", paste(Seurat::Images(APP$object_preview), collapse = ", "),
            "\nAssays: ", paste(ass, collapse = ", "),
            "\nSelected assay/layer: ", tclvalue(assay_var), "/", tclvalue(layer_var)
        )
        append_log(gsub("\n", " | ", msg))
        show_info("Seurat object", msg)
        set_status("Object inspected.", 0)
    }, error = function(e) show_error("Inspect object", conditionMessage(e)))
}

action_frame <- ttklabelframe(main, text = "5. Run / rank pathways", padding = 6)
tkgrid(action_frame, row = 1, column = 0, sticky = "ew", padx = 2, pady = 3)

collect_settings <- function() {
    qlow <- as.numeric(tclvalue(lower_q_var)); qhigh <- as.numeric(tclvalue(upper_q_var))
    if (!is.finite(qlow) || !is.finite(qhigh) || qlow < 0 || qhigh > 1 || qlow >= qhigh) stop("Robust quantiles must satisfy 0 <= lower < upper <= 1.")

    corr_t <- as.numeric(tclvalue(correlation_threshold_var))
    significance_t <- as.numeric(tclvalue(significance_p_threshold_var))
    fdr_t <- as.numeric(tclvalue(fdr_threshold_var))
    act_t <- as.numeric(tclvalue(activity_threshold_var))

    if (!is.finite(corr_t) || corr_t < 0 || corr_t > 1) stop("Minimum correlation must be between 0 and 1.")
    if (!is.finite(significance_t) || significance_t <= 0 || significance_t > 1) stop("Significance P threshold must be in (0,1].")
    if (!is.finite(fdr_t) || fdr_t <= 0 || fdr_t > 1) stop("FDR threshold must be in (0,1].")
    if (!is.finite(act_t) || act_t < 0 || act_t > 1) stop("Activity percentile threshold must be in [0,1].")

    list(
        results_workspace = legacy_results_workspace,
        input_rds = tclvalue(input_rds_var),
        output_directory = tclvalue(output_dir_var),
        organism = tclvalue(organism_var),
        fingerprint_database = tclvalue(fingerprint_db_var),
        top_genes = as.integer(tclvalue(top_genes_var)),
        assay = tclvalue(assay_var),
        layer = tclvalue(layer_var),
        tissue_normalization = tclvalue(normalization_var),
        lower_quantile = qlow,
        upper_quantile = qhigh,
        minimum_genes_present = as.integer(tclvalue(minimum_genes_var)),
        minimum_coverage = as.numeric(tclvalue(minimum_coverage_var)),
        primary_correlation = tclvalue(primary_correlation_var),
        significance_source = tclvalue(significance_source_var),
        permutations = as.integer(tclvalue(permutations_var)),
        significance_tail = tclvalue(significance_tail_var),
        fdr_scope = tclvalue(fdr_scope_var),
        use_correlation_threshold = identical(tclvalue(use_correlation_threshold_var), "1"),
        correlation_threshold = corr_t,
        use_significance_p_threshold = identical(tclvalue(use_significance_p_threshold_var), "1"),
        significance_p_threshold = significance_t,
        use_fdr_threshold = identical(tclvalue(use_fdr_threshold_var), "1"),
        fdr_threshold = fdr_t,
        use_activity_threshold = identical(tclvalue(use_activity_threshold_var), "1"),
        activity_percentile_threshold = act_t,
        use_spatial_filter = identical(tclvalue(use_spatial_filter_var), "1"),
        minimum_adjacent_spots = as.integer(tclvalue(minimum_adjacent_var)),
        adjacency_mode = tclvalue(adjacency_mode_var),
        distance_multiplier = as.numeric(tclvalue(distance_multiplier_var)),
        random_seed = as.integer(tclvalue(random_seed_var))
    )
}

validate_settings <- function(s) {
    if (!file.exists(s$input_rds)) stop("Select a valid Seurat RDS input.")
    if (!nzchar(s$output_directory)) stop("Select an output directory.")
    if (nzchar(trimws(s$fingerprint_database)) && !file.exists(s$fingerprint_database)) stop("Select a valid Fingerprint_Pathways.tabtxt file, or leave it blank to use PROGENy only.")
    if (!is.finite(s$top_genes) || s$top_genes < 1) stop("Top genes/pathway must be >= 1.")
    if (!is.finite(s$minimum_genes_present) || s$minimum_genes_present < 3) stop("Minimum genes present must be >= 3 for correlation analysis.")
    if (!is.finite(s$minimum_coverage) || s$minimum_coverage < 0 || s$minimum_coverage > 1) stop("Minimum gene coverage must be between 0 and 1.")
    if (!s$primary_correlation %in% c("Spearman", "Pearson")) stop("Primary correlation must be Spearman or Pearson.")
    if (!s$significance_source %in% c("Empirical weight permutation", "Classical correlation P (fast)")) stop("Unknown significance source.")
    if (!is.finite(s$permutations) || s$permutations < 20) stop("Use at least 20 empirical permutations. 500 is the GUI default; 1000+ gives finer p-value resolution.")
    if (!is.finite(s$minimum_adjacent_spots) || s$minimum_adjacent_spots < 1) stop("Minimum touching spots must be >= 1.")
    if (!is.finite(s$distance_multiplier) || s$distance_multiplier <= 1) stop("Distance multiplier must be > 1.")
    invisible(TRUE)
}

update_ranking_tree <- function(ranking) {
    children_text <- as.character(tcl(ranking_tree, "children", ""))
    if (nzchar(children_text)) {
        children <- strsplit(children_text, "\\s+")[[1L]]
        for (item in children[nzchar(children)]) tcl(ranking_tree, "delete", item)
    }
    if (is.null(ranking) || !nrow(ranking)) return()
    for (i in seq_len(nrow(ranking))) {
        r <- ranking[i, ]
        vals <- c(
            r$global_rank,
            r$pathway,
            r$retained_high_activity_spots,
            sprintf("%.2f", r$percent_tissue_in_retained_high_activity_region),
            r$largest_connected_component,
            ifelse(is.na(r$median_primary_correlation_retained), "", sprintf("%.3f", r$median_primary_correlation_retained)),
            ifelse(is.na(r$best_significance_fdr), "", format(r$best_significance_fdr, digits = 3, scientific = TRUE)),
            ifelse(r$high_relative_activity_region_detected, "YES", "NO")
        )
        tcl(ranking_tree, "insert", "", "end", values = vals)
    }
}

run_gui_analysis <- function() {
    tryCatch({
        settings <- collect_settings(); validate_settings(settings)
        db_path <- trimws(settings$fingerprint_database)
        db_key <- if (nzchar(db_path)) normalizePath(db_path, winslash = "/", mustWork = FALSE) else "<none>"
        current_model_key <- paste("PROGENy+FingerprintDB", settings$organism, db_key, sep = "|")
        if (is.null(APP$model_full) || is.null(APP$model_key) || !identical(APP$model_key, current_model_key)) {
            load_library_gui(FALSE)
        }
        selected <- selected_pathways_gui()
        if (!length(selected)) stop("Select at least one pathway.")

        if (identical(settings$significance_source, "Empirical weight permutation")) {
            min_empirical_p <- 1 / (settings$permutations + 1)
            best_case_first_rank_fdr <- min(1, length(selected) * min_empirical_p)
            append_log(
                "Correlation empirical resolution: minimum attainable p=", signif(min_empirical_p, 4),
                "; selected pathways=", length(selected),
                "; approximate best-case rank-1 BH FDR=", signif(best_case_first_rank_fdr, 4),
                ". For very large pathway libraries, increase permutations or choose Classical correlation P (fast)."
            )
            if (settings$use_fdr_threshold && best_case_first_rank_fdr > settings$fdr_threshold) {
                append_log(
                    "WARNING: With the selected number of pathways and permutations, empirical P-value resolution may be too coarse for the requested FDR threshold. ",
                    "Consider more permutations, fewer selected pathways, or Classical correlation P (fast)."
                )
            }
        }

        input_norm <- normalizePath(settings$input_rds, winslash = "/", mustWork = FALSE)
        object_for_run <- if (!is.null(APP$object_preview) && !is.null(APP$object_path) && identical(APP$object_path, input_norm)) APP$object_preview else NULL

        set_status("Running pathway-footprint analysis...", 1)
        APP$last_result <- run_pathway_footprint_analysis(settings, APP$model_full, selected, object_for_run)
        APP$object_preview <- APP$last_result$object
        APP$object_path <- input_norm
        update_ranking_tree(APP$last_result$pathway_ranking)
        show_info("Completed", paste0(
            "Pathway-footprint analysis completed.\n\n",
            "Pathways with retained high-relative-activity regions: ", sum(APP$last_result$pathway_ranking$high_relative_activity_region_detected), " / ", nrow(APP$last_result$pathway_ranking), "\n",
            "Output: ", settings$output_directory
        ))
    }, error = function(e) {
        set_status("Analysis stopped with an error.", 0)
        show_error("Script 7 analysis", conditionMessage(e))
    })
}

open_output_gui <- function() {
    path <- tclvalue(output_dir_var)
    if (!dir.exists(path)) return(show_error("Output", "Output directory does not exist yet."))
    if (.Platform$OS.type == "windows") {
        shell.exec(normalizePath(path, winslash = "\\", mustWork = TRUE))
    } else if (Sys.info()[["sysname"]] == "Darwin") {
        system2("open", path)
    } else {
        system2("xdg-open", path)
    }
}

btn_inspect <- tkbutton(action_frame, text = "Inspect Seurat Object", command = inspect_object_gui, background = "#E8EAF6", foreground = "#283593", relief = "flat", padx = 10)
btn_run <- tkbutton(action_frame, text = "RANK PATHWAYS + BUILD SPATIAL MAPS", command = run_gui_analysis, background = GUI_ACCENT, foreground = "white", activebackground = "#4A148C", activeforeground = "white", relief = "flat", padx = 12)
btn_open <- tkbutton(action_frame, text = "Open Output Folder", command = open_output_gui, background = "#E0F2F1", foreground = "#00695C", relief = "flat", padx = 10)
tkpack(btn_inspect, side = "left", padx = 4)
tkpack(btn_run, side = "left", padx = 4, ipadx = 10, ipady = 5)
tkpack(btn_open, side = "left", padx = 4)

results_frame <- ttklabelframe(main, text = "6. Pathway ranking (after analysis)", padding = 6)
tkgrid(results_frame, row = 5, column = 0, sticky = "nsew", padx = 2, pady = 3)
tkgrid.rowconfigure(results_frame, 0, weight = 1)
tkgrid.columnconfigure(results_frame, 0, weight = 1)

columns <- c("rank", "pathway", "retained", "percent_tissue", "largest_component", "median_correlation", "best_fdr", "retained_region")
ranking_tree <- ttktreeview(results_frame, columns = columns, show = "headings", height = 9)
heading_labels <- c("Rank", "Pathway", "Retained high-activity spots", "% tissue retained", "Largest connected region", "Median correlation", "Best optional FDR", "High-activity region")
for (i in seq_along(columns)) {
    tcl(ranking_tree, "heading", columns[i], text = heading_labels[i])
    tcl(ranking_tree, "column", columns[i], width = c(55, 220, 100, 80, 180, 125, 125, 75)[i], anchor = if (i == 2) "w" else "center")
}
rank_scroll <- ttkscrollbar(results_frame, orient = "vertical", command = function(...) tkyview(ranking_tree, ...))
tcl(ranking_tree, "configure", yscrollcommand = function(...) tkset(rank_scroll, ...))
tkgrid(ranking_tree, row = 0, column = 0, sticky = "nsew")
tkgrid(rank_scroll, row = 0, column = 1, sticky = "ns")

log_frame <- ttklabelframe(main, text = "Status / log", padding = 5)
tkgrid(log_frame, row = 6, column = 0, sticky = "ew", padx = 2, pady = 3)
tkgrid.columnconfigure(log_frame, 0, weight = 1)

progress <- ttkprogressbar(log_frame, orient = "horizontal", mode = "determinate", maximum = 100, variable = progress_var)
tkgrid(progress, row = 0, column = 0, sticky = "ew", padx = 2)
ttklabel(log_frame, textvariable = status_var) |> tkgrid(row = 0, column = 1, sticky = "e", padx = 5)

log_text <- tktext(log_frame, height = 6, wrap = "word", font = "TkFixedFont")
log_scroll <- ttkscrollbar(log_frame, orient = "vertical", command = function(...) tkyview(log_text, ...))
tcl(log_text, "configure", yscrollcommand = function(...) tkset(log_scroll, ...))
tkgrid(log_text, row = 1, column = 0, sticky = "ew")
tkgrid(log_scroll, row = 1, column = 1, sticky = "ns")
.GUI$log_widget <- log_text

append_log("Script 7 GUI started.")
append_log("Recommended input: the uniquely matching tagged S06 RDS in the selected workspace's Seurat_RDS folder")
append_log("Default assay: Spatial/data, to retain broad gene coverage for pathway footprints.")
append_log("Pathway library: built-in PROGENy + optional Fingerprint_Pathways.tabtxt. Script 7 reads but never creates/modifies the database.")
append_log("Core analysis: correlate each selected pathway fingerprint with every Visium spot. Spearman is the default primary statistic.")
append_log("Correlation, significance-P, FDR, activity, and connected-spot filters are independently switchable in the GUI.")
append_log("For large pathway libraries, Classical correlation P (fast) avoids the finite permutation-P resolution limit; empirical weight permutation remains available for stronger pathway-specific testing.")

if (requireNamespace("progeny", quietly = TRUE)) {
    try(load_library_gui(FALSE), silent = TRUE)
} else {
    append_log("PROGENy is not installed. Use 'Install/Check Packages' before loading the built-in pathway library.")
}

tkfocus(root)
tkwait.window(root)
}
