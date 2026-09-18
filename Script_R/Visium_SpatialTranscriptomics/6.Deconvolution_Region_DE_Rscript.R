

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

cli <- visium_parse_cli()
if (isTRUE(cli$help)) {
    visium_print_help(
        "Script 6 - Cell-Type Annotation, Deconvolution, and Region DE",
        "Rscript 6.Deconvolution_Region_DE_Rscript.R [--gui|--cli] [options]",
        c(
            "--gui  Open the colored native desktop GUI.", "--cli  Run headlessly.",
            "--results-dir PATH  Required sample results folder, for example Results/Sample_01.",
            "--spatial-rds PATH  Required Step 5 spatial-variable-gene Seurat RDS.",
            "--reference-rds PATH  Required annotated scRNA-seq Seurat RDS unless method=None.",
            "--deconvolution-method SeuratLabelTransfer|RCTD|None",
            "--reference-cell-type-column NAME", "--reference-assay NAME",
            "--dims 1:30", "--rctd-mode Full|Doublet|Multi", "--rctd-cores INT", "--annotation-colors auto|CSV",
            "--sample-column NAME", "--region-column NAME", "--test-variable NAME",
            "--reference-level VALUE", "--test-level VALUE", "--design-formula FORMULA",
            "--minimum-spots-per-sample-region INT", "--minimum-samples-per-group INT"
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
    tcltk::tkpack(tcltk::tklabel(hero, text = "Groups spots into regions or clusters, identifies marker genes, and reports statistics for each region.", background = accent, foreground = "white", anchor = "w", padx = 22L, pady = 4L), fill = "x")

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

visium_gui_read_seurat_rds <- function(path, file_description) {
    path <- trimws(as.character(path)[1L])
    if (!nzchar(path) || !file.exists(path)) {
        stop("Select the ", file_description, " first.", call. = FALSE)
    }
    object <- readRDS(path)
    if (!inherits(object, "Seurat")) {
        stop("The selected ", file_description, " is not a Seurat RDS object.", call. = FALSE)
    }
    object
}

visium_gui_metadata_columns <- function(path, file_description) {
    object <- visium_gui_read_seurat_rds(path, file_description)
    columns <- colnames(object[[]])
    if (!length(columns)) stop("The selected ", file_description, " has no metadata columns.", call. = FALSE)
    columns
}

visium_gui_assays <- function(path, file_description) {
    object <- visium_gui_read_seurat_rds(path, file_description)
    assays <- SeuratObject::Assays(object)
    if (!length(assays)) stop("The selected ", file_description, " has no expression assays.", call. = FALSE)
    assays
}

visium_normalize_proportion_matrix <- function(proportions) {
    proportions <- as.matrix(proportions)
    storage.mode(proportions) <- "double"
    proportions[!is.finite(proportions)] <- 0
    totals <- rowSums(proportions)
    valid <- is.finite(totals) & totals > 0
    if (any(valid)) proportions[valid, ] <- proportions[valid, , drop = FALSE] / totals[valid]
    if (any(!valid)) proportions[!valid, ] <- 0
    proportions
}

visium_rctd_proportions <- function(rctd, mode) {
    spot_names <- colnames(rctd@spatialRNA@counts)
    if (identical(mode, "Full")) {
        proportions <- spacexr::normalize_weights(rctd@results$weights)
    } else if (identical(mode, "Doublet")) {
        proportions <- spacexr::get_doublet_weights(rctd)
    } else {
        results <- rctd@results
        if (length(results) != length(spot_names)) {
            stop("RCTD Multi returned ", length(results), " spot results for ", length(spot_names), " analyzed spots.")
        }
        cell_types <- as.character(rctd@cell_type_info$renorm[[2]])
        proportions <- matrix(0, nrow = length(spot_names), ncol = length(cell_types), dimnames = list(spot_names, cell_types))
        for (index in seq_along(results)) {
            entry <- results[[index]]
            weights <- as.numeric(entry$sub_weights)
            labels <- names(entry$sub_weights)
            if (is.null(labels) || length(labels) != length(weights) || any(!nzchar(labels))) labels <- as.character(entry$cell_type_list)
            if (length(labels) != length(weights)) stop("RCTD Multi returned incompatible cell-type labels and proportions for spot ", spot_names[[index]], ".")
            known <- labels %in% cell_types
            if (any(known)) proportions[index, labels[known]] <- weights[known]
        }
    }
    proportions <- visium_normalize_proportion_matrix(proportions)
    if (is.null(rownames(proportions)) && nrow(proportions) == length(spot_names)) rownames(proportions) <- spot_names
    missing_spots <- setdiff(spot_names, rownames(proportions))
    if (length(missing_spots)) stop("RCTD proportion output is missing analyzed spot barcodes: ", paste(head(missing_spots, 10L), collapse = ", "))
    proportions[spot_names, , drop = FALSE]
}

defaults <- list(
    results_dir = "",
    spatial_rds = "", reference_rds = "",
    deconvolution_method = "SeuratLabelTransfer",
    reference_cell_type_column = "cell_type", reference_assay = "RNA",
    dims = "1:30", rctd_mode = "Full", rctd_cores = 8L,
    sample_column = "sample_id", region_column = "seurat_clusters",
    test_variable = "condition", reference_level = "Control",
    test_level = "Treatment", design_formula = "~ condition",
    minimum_spots_per_sample_region = 10L, minimum_samples_per_group = 2L,
    annotation_colors = "auto"
)

run_gui <- interactive() || !length(commandArgs(trailingOnly = TRUE)) || isTRUE(cli$gui)
if (isTRUE(cli$cli)) run_gui <- FALSE
if (run_gui) {
    gui <- visium_desktop_gui(
        "Script 6 - Cell-Type Annotation, Deconvolution, and Region DE",
        list(
            list(name = "results_dir", label = "Sample results folder (for example Results/Sample_01)", value = defaults$results_dir, type = "directory", group = "Files - settings and explanations", required = TRUE, must_exist = TRUE),
            list(name = "spatial_rds", label = "Step 5 resolution-specific spatial-variable-gene Seurat RDS", value = "", type = "file", group = "Files - settings and explanations", required = TRUE, must_exist = TRUE, browse_initial_dir = function(values) file.path(values$results_dir, "Seurat_RDS"), path_pattern = "_S05_.*_Clstr[0-9]+(\\.[0-9]+)?_Svg(Moran|Mark)\\.rds$", path_message = "a tagged Step 5 RDS preserving the clustering resolution and algorithm, such as *_S05_QCfilt_NormSCT_Clstr0.40_SvgMoran.rds or *_SvgMark.rds"),
            list(name = "spatial_rds_help", type = "info", group = "Files - settings and explanations", text = "After selecting the sample results folder, Browse opens its Seurat_RDS folder. Select the exact Step 5 spatial Seurat RDS to analyze. Its cumulative tags are preserved; Step 6 appends DeconvLT, DeconvRCTDFull, DeconvRCTDDoublet, DeconvRCTDMulti, or NoDeconv plus RegDE."),
            list(name = "reference_rds", label = "Annotated scRNA-seq reference Seurat RDS (required for SeuratLabelTransfer or RCTD; not required for None)", value = defaults$reference_rds, type = "file", group = "Files - settings and explanations", browse_initial_dir = function(values) file.path(values$results_dir, "Seurat_RDS")),
            list(name = "reference_rds_help", type = "info", group = "Files - settings and explanations", text = "WHAT IT IS: A separate, annotated single-cell RNA-seq Seurat object—not a Visium/spatial object. Its expression matrix has Feature_Genes as rows and individual cells as columns; the RNA assay normally contains a raw Count_RNAs layer; reference[[]] has one metadata row per cell; and a column such as cell_type assigns a biological label to every cell. Gene identifiers should match the spatial data, and the reference should preferably match the same species, tissue, and biological context."),
            list(name = "reference_source_help", type = "info", group = "Files - settings and explanations", text = "WHERE TO GET IT: Use your own annotated scRNA-seq Seurat analysis, or search CELLxGENE (cellxgene.cziscience.com/datasets), Human Cell Atlas (data.humancellatlas.org), Broad Single Cell Portal (singlecell.broadinstitute.org), or NCBI GEO (ncbi.nlm.nih.gov/geo). Downloads may be matrices, H5, or H5AD rather than Seurat RDS files; import the Count_RNAs matrix into Seurat, perform QC/annotation, verify the cell-type metadata, then saveRDS(reference, 'reference.rds'). A raw dataset without trustworthy cell-type annotations is not yet a usable reference."),
            list(name = "output_dir_help", type = "info", group = "Files - settings and explanations", text = "RDS LOCATION: Every RDS belongs in the workspace's Seurat_RDS folder, including the external scRNA reference (use a clear name containing reference or scRNA), the optional RCTD model, and the tagged Step 6 Seurat output. Plots, tables, logs, and settings remain in 6_Deconvolution_Region_DE."),

            list(name = "deconvolution_method", label = "Cell-type annotation or deconvolution method (select one)", value = defaults$deconvolution_method, type = "radio", choices = c("SeuratLabelTransfer", "RCTD", "None"), group = "Deconvolution - settings and explanations"),
            list(name = "deconvolution_method_help", type = "info", group = "Deconvolution - settings and explanations", text = "SeuratLabelTransfer is cell-type annotation: it assigns the most likely reference label to each spatial spot but does not estimate a cell mixture. RCTD is deconvolution: it estimates mixtures of cell types from raw Count_RNAs, requires spacexr, and this script accepts one spatial image per RCTD run. None skips both; region analyses can still run from the spatial object's region metadata."),
            list(name = "rctd_mode", label = "RCTD spot-mixture mode (select one)", value = defaults$rctd_mode, type = "radio", choices = c("Full", "Doublet", "Multi"), group = "Deconvolution - settings and explanations"),
            list(name = "rctd_mode_help", type = "info", group = "Deconvolution - settings and explanations", text = "Full is the recommended default for conventional Visium because a spot can contain many cell types. Doublet restricts each spot to one or two cell types and is intended mainly for higher-resolution platforms. Multi allows a limited mixture, using the spacexr maximum of four cell types per spot unless its package configuration is changed. This selection affects RCTD only."),
            list(name = "deconvolution_source_help", type = "info", group = "Deconvolution - settings and explanations", text = "COLUMN SOURCE: The two selectors below read only from the annotated scRNA-seq reference Seurat RDS selected above—not from the spatial Seurat RDS or from a text file. Select the reference RDS first, then choose from its available metadata columns and assays."),
            list(name = "reference_cell_type_column", label = "Cell-type metadata column (from scRNA-seq reference RDS)", value = defaults$reference_cell_type_column, type = "choice", choices = defaults$reference_cell_type_column, choice_source = "reference_rds", choice_loader = function(reference_rds) unique(c(defaults$reference_cell_type_column, visium_gui_metadata_columns(reference_rds, "annotated scRNA-seq reference Seurat RDS"))), group = "Deconvolution - settings and explanations"),
            list(name = "reference_cell_type_column_help", type = "info", group = "Deconvolution - settings and explanations", text = "Choose the metadata column in the scRNA-seq reference object (reference[[]]) that contains one biological label per cell, for example cell_type, celltype, or annotation. Select biologically annotated labels such as T_cell, epithelial, or fibroblast—not raw cluster numbers unless those clusters have been identified."),
            list(name = "reference_assay", label = "Expression assay (from scRNA-seq reference RDS)", value = defaults$reference_assay, type = "choice", choices = defaults$reference_assay, choice_source = "reference_rds", choice_loader = function(reference_rds) unique(c(defaults$reference_assay, visium_gui_assays(reference_rds, "annotated scRNA-seq reference Seurat RDS"))), group = "Deconvolution - settings and explanations"),
            list(name = "reference_assay_help", type = "info", group = "Deconvolution - settings and explanations", text = "Choose an assay listed in the selected scRNA-seq reference object, normally RNA. RCTD requires raw Count_RNAs in that assay's counts layer. Label transfer uses SCT automatically only when both objects contain SCT; otherwise it normalizes the selected reference assay and the Spatial assay."),
            list(name = "dims", label = "PC dimensions for label transfer (for example 1:30)", value = defaults$dims, type = "text", group = "Deconvolution - settings and explanations"),
            list(name = "dims_help", type = "info", group = "Deconvolution - settings and explanations", text = "Principal components used to build transfer anchors and calculate label predictions. The default 1:30 is a common starting point. This setting affects SeuratLabelTransfer only and must not exceed the number of PCs that can be calculated from the shared genes/cells."),
            list(name = "rctd_cores", label = "CPU cores for RCTD", value = defaults$rctd_cores, type = "integer", group = "Deconvolution - settings and explanations"),
            list(name = "rctd_cores_help", type = "info", group = "Deconvolution - settings and explanations", text = "Maximum CPU cores used by RCTD. More cores can reduce runtime but increase simultaneous memory/CPU use. This setting is ignored by SeuratLabelTransfer and None."),
            list(name = "annotation_colors", label = "Cell-type map colors (auto or comma-separated)", value = defaults$annotation_colors, type = "text", group = "Deconvolution - settings and explanations"),
            list(name = "annotation_colors_help", type = "info", group = "Deconvolution - settings and explanations", text = "Use auto to generate distinct colors, or enter valid R colors separated by commas, for example #1B9E77,#D95F02,#7570B3. Colors are recycled if fewer colors than cell types are supplied."),

            list(name = "region_de_source_help", type = "info", group = "Region DE - settings and explanations", text = "COLUMN SOURCE: All column and group selectors in this section read from the metadata table of the selected Step 5 spatial Seurat RDS (the Visium/spatial object). They do not read from the scRNA-seq reference RDS or from a text file. Select the Step 5 RDS first, then choose from its available metadata columns."),
            list(name = "sample_column", label = "Independent-sample ID column (from spatial RDS)", value = defaults$sample_column, type = "choice", choices = defaults$sample_column, choice_source = "spatial_rds", choice_loader = function(spatial_rds) unique(c(defaults$sample_column, visium_gui_metadata_columns(spatial_rds, "Step 5 spatial Seurat RDS"))), group = "Region DE - settings and explanations"),
            list(name = "sample_column_help", type = "info", group = "Region DE - settings and explanations", text = "Choose the spatial-object metadata column identifying independent biological samples or tissue sections, for example sample_id. Spots from the same section are not independent replicates; their Count_RNAs values are summed within each sample and region for pseudobulk DE."),
            list(name = "region_column", label = "Region or cluster column (from spatial RDS)", value = defaults$region_column, type = "choice", choices = defaults$region_column, choice_source = "spatial_rds", choice_loader = function(spatial_rds) unique(c(defaults$region_column, visium_gui_metadata_columns(spatial_rds, "Step 5 spatial Seurat RDS"))), group = "Region DE - settings and explanations"),
            list(name = "region_column_help", type = "info", group = "Region DE - settings and explanations", text = "Choose the spatial-object metadata column that partitions spots into tissue regions or clusters. The default seurat_clusters is created by Step 4. Exploratory markers and a separate sample-aware edgeR analysis are calculated for each region."),
            list(name = "test_variable", label = "Experimental variable column (from spatial RDS)", value = defaults$test_variable, type = "choice", choices = defaults$test_variable, choice_source = "spatial_rds", choice_loader = function(spatial_rds) unique(c(defaults$test_variable, visium_gui_metadata_columns(spatial_rds, "Step 5 spatial Seurat RDS"))), group = "Region DE - settings and explanations"),
            list(name = "test_variable_help", type = "info", group = "Region DE - settings and explanations", text = "Choose the spatial-object metadata column containing the experimental groups to compare, for example condition, treatment, or disease_status. It must also appear in the design formula and should be constant within each independent sample."),
            list(name = "reference_level", label = "Baseline/reference group value (from selected spatial column)", value = defaults$reference_level, type = "text", group = "Region DE - settings and explanations"),
            list(name = "reference_level_help", type = "info", group = "Region DE - settings and explanations", text = "Enter the exact value from the selected experimental-variable column in the spatial RDS to use as the baseline, for example Control. Results are interpreted relative to this group."),
            list(name = "test_level", label = "Group compared with baseline (from selected spatial column)", value = defaults$test_level, type = "text", group = "Region DE - settings and explanations"),
            list(name = "test_level_help", type = "info", group = "Region DE - settings and explanations", text = "Enter a second exact value from the selected experimental-variable column in the spatial RDS. The reported contrast is this group divided by the baseline group."),
            list(name = "design_formula", label = "Pseudobulk design formula", value = defaults$design_formula, type = "text", group = "Region DE - settings and explanations"),
            list(name = "design_formula_help", type = "info", group = "Region DE - settings and explanations", text = "R model formula passed to model.matrix, for example ~ condition. It must include the experimental variable. Add covariates only when they are sample-level metadata columns and the study has enough independent samples to estimate them."),
            list(name = "minimum_spots_per_sample_region", label = "Minimum spots in each sample-region", value = defaults$minimum_spots_per_sample_region, type = "integer", group = "Region DE - settings and explanations"),
            list(name = "minimum_spots_per_sample_region_help", type = "info", group = "Region DE - settings and explanations", text = "A sample contributes to a region's pseudobulk profile only when at least this many spots fall in that region. Raising the value improves aggregation depth but can exclude more sample-region combinations."),
            list(name = "minimum_samples_per_group", label = "Minimum independent samples per group", value = defaults$minimum_samples_per_group, type = "integer", group = "Region DE - settings and explanations"),
            list(name = "minimum_samples_per_group_help", type = "info", group = "Region DE - settings and explanations", text = "Minimum biological replicates required in both reference and test groups after spot filtering. Regions that fail this requirement are skipped. The script also requires at least four unique samples overall before sample-aware DE is attempted.")
        ),
        accent = "#00897B"
    )
    cli <- modifyList(cli, gui)
}

RESULTS_WORKSPACE <- visium_validate_results_workspace(visium_option(cli, "results-dir", defaults$results_dir, "path"))
INPUT_DIRECTORY <- visium_stage_directory(RESULTS_WORKSPACE, "5_Spatially_Variable_Genes", create = FALSE)
OUTPUT_DIRECTORY <- visium_stage_directory(RESULTS_WORKSPACE, "6_Deconvolution_Region_DE", create = TRUE)
REFERENCE_INPUT_DIRECTORY <- visium_rds_directory(RESULTS_WORKSPACE, create = TRUE)
SPATIAL_RDS_OPTION <- visium_option(cli, "spatial-rds", defaults$spatial_rds, "path")
REFERENCE_RDS_OPTION <- visium_option(cli, "reference-rds", defaults$reference_rds, "path")

DECONVOLUTION_METHOD <- visium_option(cli, "deconvolution-method", defaults$deconvolution_method, "choice", c("SeuratLabelTransfer", "RCTD", "None"))
REFERENCE_CELL_TYPE_COLUMN <- visium_option(cli, "reference-cell-type-column", defaults$reference_cell_type_column)
REFERENCE_ASSAY <- visium_option(cli, "reference-assay", defaults$reference_assay)
DIMS_TO_USE <- visium_option(cli, "dims", defaults$dims, "dims")
RCTD_MODE <- visium_option(cli, "rctd-mode", defaults$rctd_mode, "choice", c("Full", "Doublet", "Multi"))
RCTD_CORES <- visium_option(cli, "rctd-cores", defaults$rctd_cores, "integer")
ANNOTATION_COLORS <- visium_option(cli, "annotation-colors", defaults$annotation_colors)

SAMPLE_COLUMN <- visium_option(cli, "sample-column", defaults$sample_column)
REGION_COLUMN <- visium_option(cli, "region-column", defaults$region_column)
TEST_VARIABLE <- visium_option(cli, "test-variable", defaults$test_variable)
REFERENCE_LEVEL <- visium_option(cli, "reference-level", defaults$reference_level)
TEST_LEVEL <- visium_option(cli, "test-level", defaults$test_level)
DESIGN_FORMULA <- visium_option(cli, "design-formula", defaults$design_formula)
MINIMUM_SPOTS_PER_SAMPLE_REGION <- visium_option(cli, "minimum-spots-per-sample-region", defaults$minimum_spots_per_sample_region, "integer")
MINIMUM_SAMPLES_PER_GROUP <- visium_option(cli, "minimum-samples-per-group", defaults$minimum_samples_per_group, "integer")
if (!length(DIMS_TO_USE) || any(DIMS_TO_USE < 1L)) stop("PC dimensions must contain positive integers.")
if (RCTD_CORES < 1L) stop("RCTD cores must be at least 1.")
if (!nzchar(SPATIAL_RDS_OPTION) || !file.exists(SPATIAL_RDS_OPTION)) stop("Select the Step 5 spatial Seurat RDS explicitly with --spatial-rds.")
if (!identical(DECONVOLUTION_METHOD, "None") && !nzchar(REFERENCE_RDS_OPTION)) stop("The selected deconvolution method requires an scRNA-seq reference RDS.")
if (nzchar(REFERENCE_RDS_OPTION) && !file.exists(REFERENCE_RDS_OPTION)) stop("scRNA-seq reference RDS does not exist: ", REFERENCE_RDS_OPTION)
if (nzchar(REFERENCE_RDS_OPTION)) {
    reference_parent <- normalizePath(dirname(REFERENCE_RDS_OPTION), winslash = "/", mustWork = TRUE)
    if (!identical(tolower(reference_parent), tolower(REFERENCE_INPUT_DIRECTORY))) {
        stop(
            "All RDS objects for this sample must be stored in:\n", REFERENCE_INPUT_DIRECTORY, "\n",
            "Move or copy the scRNA-seq reference RDS into that folder, then select it again.\n",
            "Selected reference: ", normalizePath(REFERENCE_RDS_OPTION, winslash = "/", mustWork = TRUE)
        )
    }
}
if (!nzchar(trimws(REFERENCE_CELL_TYPE_COLUMN))) stop("Reference cell-type metadata column cannot be empty.")
if (!nzchar(trimws(REFERENCE_ASSAY))) stop("Reference assay cannot be empty.")
if (any(!nzchar(trimws(c(SAMPLE_COLUMN, REGION_COLUMN, TEST_VARIABLE, REFERENCE_LEVEL, TEST_LEVEL))))) stop("Region DE column and group names cannot be empty.")
if (identical(REFERENCE_LEVEL, TEST_LEVEL)) stop("Region DE reference and test groups must be different.")
design_formula_object <- tryCatch(stats::as.formula(DESIGN_FORMULA), error = function(e) NULL)
if (is.null(design_formula_object)) stop("Region DE design formula is not valid R formula syntax.")
if (!(TEST_VARIABLE %in% all.vars(design_formula_object))) stop("Region DE design formula must include the experimental variable: ", TEST_VARIABLE)
if (MINIMUM_SPOTS_PER_SAMPLE_REGION < 1L) stop("Minimum spots in each sample-region must be at least 1.")
if (MINIMUM_SAMPLES_PER_GROUP < 2L) stop("Minimum independent samples per group must be at least 2.")

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
cat("Deconvolution method:", DECONVOLUTION_METHOD, "\n")
if (identical(DECONVOLUTION_METHOD, "RCTD")) cat("RCTD mode:", RCTD_MODE, "\n")
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

require_packages(c("Seurat", "SeuratObject", "Matrix", "edgeR", "ggplot2"))
library(Seurat)
library(Matrix)
library(edgeR)
library(ggplot2)

rds_files <- c(SPATIAL_RDS_OPTION, if (nzchar(REFERENCE_RDS_OPTION)) REFERENCE_RDS_OPTION)
if (!length(rds_files)) stop("No RDS files were found in Input.")
missing_rds <- rds_files[!file.exists(rds_files)]
if (length(missing_rds)) stop("RDS file does not exist: ", paste(missing_rds, collapse = ", "))

objects <- lapply(rds_files, readRDS)
spatial_indices <- which(vapply(objects, function(x) inherits(x, "Seurat") && length(Images(x)) > 0L, logical(1)))
if (length(spatial_indices) != 1L) stop("Input must contain exactly one spatial Seurat object.")
spatial_object <- objects[[spatial_indices]]

reference_indices <- setdiff(seq_along(objects), spatial_indices)
reference_object <- if (length(reference_indices) == 1L) objects[[reference_indices]] else NULL
if (length(reference_indices) > 1L) stop("Input contains more than one possible scRNA-seq reference RDS.")

if (identical(DECONVOLUTION_METHOD, "SeuratLabelTransfer")) {
    if (is.null(reference_object)) stop("Seurat label transfer requires one scRNA-seq reference RDS in Input.")
    if (!REFERENCE_CELL_TYPE_COLUMN %in% colnames(reference_object[[]])) {
        stop("Reference object lacks cell-type column: ", REFERENCE_CELL_TYPE_COLUMN)
    }

    use_sct_transfer <- "SCT" %in% Assays(spatial_object) && "SCT" %in% Assays(reference_object)

    if (use_sct_transfer) {
        query_assay <- "SCT"
        reference_assay_for_transfer <- "SCT"
        reference_normalization <- "SCT"

        DefaultAssay(reference_object) <- "SCT"
        reference_object <- RunPCA(reference_object, assay = "SCT", npcs = max(DIMS_TO_USE), verbose = FALSE)
        DefaultAssay(spatial_object) <- "SCT"
        spatial_object <- RunPCA(spatial_object, assay = "SCT", npcs = max(DIMS_TO_USE), verbose = FALSE)
    } else {
        query_assay <- "Spatial"
        reference_assay_for_transfer <- REFERENCE_ASSAY
        reference_normalization <- "LogNormalize"

        DefaultAssay(reference_object) <- reference_assay_for_transfer
        reference_object <- NormalizeData(reference_object, assay = reference_assay_for_transfer, verbose = FALSE)
        reference_object <- FindVariableFeatures(reference_object, assay = reference_assay_for_transfer, verbose = FALSE)
        reference_object <- ScaleData(reference_object, assay = reference_assay_for_transfer, verbose = FALSE)
        reference_object <- RunPCA(reference_object, assay = reference_assay_for_transfer, npcs = max(DIMS_TO_USE), verbose = FALSE)

        DefaultAssay(spatial_object) <- query_assay
        spatial_object <- NormalizeData(spatial_object, assay = query_assay, verbose = FALSE)
        spatial_object <- FindVariableFeatures(spatial_object, assay = query_assay, verbose = FALSE)
        spatial_object <- ScaleData(spatial_object, assay = query_assay, verbose = FALSE)
        spatial_object <- RunPCA(spatial_object, assay = query_assay, npcs = max(DIMS_TO_USE), verbose = FALSE)
    }

    anchors <- FindTransferAnchors(
        reference = reference_object,
        query = spatial_object,
        reference.assay = reference_assay_for_transfer,
        query.assay = query_assay,
        normalization.method = reference_normalization,
        reference.reduction = "pca",
        dims = DIMS_TO_USE
    )

    predictions <- TransferData(
        anchorset = anchors,
        refdata = reference_object[[REFERENCE_CELL_TYPE_COLUMN, drop = TRUE]],
        prediction.assay = TRUE,
        weight.reduction = spatial_object[["pca"]],
        dims = DIMS_TO_USE
    )

    spatial_object[["celltype_predictions"]] <- predictions
    prediction_matrix <- LayerData(spatial_object, assay = "celltype_predictions", layer = "data")
    spatial_object$predicted_cell_type <- GetTransferPredictions(
        spatial_object,
        assay = "celltype_predictions",
        score.filter = 0
    )

    write.csv(
        as.data.frame(t(as.matrix(prediction_matrix))),
        file.path(OUTPUT_DIRECTORY, "cell_type_prediction_scores.csv")
    )

} else if (identical(DECONVOLUTION_METHOD, "RCTD")) {
    require_packages("spacexr")
    if (is.null(reference_object)) stop("RCTD requires one scRNA-seq reference RDS in Input.")
    if (length(Images(spatial_object)) != 1L) {
        stop("This RCTD implementation currently expects one spatial slice per run.")
    }
    if (!REFERENCE_CELL_TYPE_COLUMN %in% colnames(reference_object[[]])) {
        stop("Reference object lacks cell-type column: ", REFERENCE_CELL_TYPE_COLUMN)
    }

    reference_object <- tryCatch(JoinLayers(reference_object, assay = REFERENCE_ASSAY), error = function(e) reference_object)
    spatial_object <- tryCatch(JoinLayers(spatial_object, assay = "Spatial"), error = function(e) spatial_object)

    reference_counts <- LayerData(reference_object, assay = REFERENCE_ASSAY, layer = "counts")
    reference_clusters <- factor(reference_object[[REFERENCE_CELL_TYPE_COLUMN, drop = TRUE]])
    names(reference_clusters) <- colnames(reference_object)
    reference_n_umi <- Matrix::colSums(reference_counts)
    names(reference_n_umi) <- colnames(reference_object)
    rctd_reference <- spacexr::Reference(reference_counts, reference_clusters, reference_n_umi)

    spatial_counts <- LayerData(spatial_object, assay = "Spatial", layer = "counts")
    coordinates <- GetTissueCoordinates(spatial_object)
    coordinates <- coordinates[colnames(spatial_counts), , drop = FALSE]
    coordinates <- coordinates[, seq_len(min(2L, ncol(coordinates))), drop = FALSE]
    colnames(coordinates) <- c("x", "y")
    spatial_rna <- spacexr::SpatialRNA(coordinates, spatial_counts, Matrix::colSums(spatial_counts))

    rctd <- spacexr::create.RCTD(spatial_rna, rctd_reference, max_cores = RCTD_CORES)
    rctd <- spacexr::run.RCTD(rctd, doublet_mode = tolower(RCTD_MODE))
    rctd_proportions <- visium_rctd_proportions(rctd, RCTD_MODE)
    proportion_export <- data.frame(Spot_Barcode = rownames(rctd_proportions), rctd_proportions, check.names = FALSE)
    write.csv(proportion_export, file.path(OUTPUT_DIRECTORY, paste0("RCTD_", RCTD_MODE, "_cell_type_proportions.csv")), row.names = FALSE)

    proportion_metadata <- matrix(
        NA_real_,
        nrow = ncol(spatial_object),
        ncol = ncol(rctd_proportions),
        dimnames = list(colnames(spatial_object), paste0("RCTD_Proportion_", make.unique(gsub("[^A-Za-z0-9_.-]", "_", colnames(rctd_proportions)))))
    )
    shared_spots <- intersect(rownames(proportion_metadata), rownames(rctd_proportions))
    proportion_metadata[shared_spots, ] <- rctd_proportions[shared_spots, , drop = FALSE]
    spatial_object <- AddMetaData(spatial_object, metadata = as.data.frame(proportion_metadata, check.names = FALSE))

    dominant_cell_type <- setNames(rep(NA_character_, ncol(spatial_object)), colnames(spatial_object))
    valid_proportion_rows <- rowSums(rctd_proportions) > 0
    if (any(valid_proportion_rows)) {
        dominant_cell_type[rownames(rctd_proportions)[valid_proportion_rows]] <- colnames(rctd_proportions)[max.col(rctd_proportions[valid_proportion_rows, , drop = FALSE], ties.method = "first")]
    }
    spatial_object <- AddMetaData(spatial_object, metadata = dominant_cell_type, col.name = "RCTD_dominant_cell_type")
    spatial_object <- AddMetaData(spatial_object, metadata = setNames(rep(RCTD_MODE, ncol(spatial_object)), colnames(spatial_object)), col.name = "RCTD_mode")

    if (identical(RCTD_MODE, "Doublet")) {
        spatial_object <- AddMetaData(spatial_object, metadata = rctd@results$results_df)
        write.csv(rctd@results$results_df, file.path(OUTPUT_DIRECTORY, "RCTD_Doublet_assignments.csv"))
    }

    RCTD_RESULT_RDS_FILE <- file.path(visium_rds_directory(RESULTS_WORKSPACE, create = TRUE), paste0(visium_workspace_sample_name(RESULTS_WORKSPACE), "_S06_RCTD_", RCTD_MODE, "_model.rds"))
    saveRDS(rctd, RCTD_RESULT_RDS_FILE, compress = FALSE)

} else if (!identical(DECONVOLUTION_METHOD, "None")) {
    stop("DECONVOLUTION_METHOD must be SeuratLabelTransfer, RCTD, or None.")
}

annotation_column <- if ("predicted_cell_type" %in% colnames(spatial_object[[]])) {
    "predicted_cell_type"
} else if ("RCTD_dominant_cell_type" %in% colnames(spatial_object[[]])) {
    "RCTD_dominant_cell_type"
} else if ("first_type" %in% colnames(spatial_object[[]])) {
    "first_type"
} else {
    NULL
}

if (!is.null(annotation_column)) {
    annotation_levels <- sort(unique(stats::na.omit(as.character(spatial_object[[annotation_column, drop = TRUE]]))))
    annotation_palette <- if (tolower(trimws(ANNOTATION_COLORS)) == "auto") {
        grDevices::hcl.colors(max(1L, length(annotation_levels)), palette = "Dark 3")
    } else {
        visium_colors(visium_csv(ANNOTATION_COLORS, "Annotation colors", empty = FALSE), "Annotation colors")
    }
    annotation_palette <- stats::setNames(rep(annotation_palette, length.out = length(annotation_levels)), annotation_levels)
    for (image_name in Images(spatial_object)) {
        plot_object <- SpatialDimPlot(
            spatial_object,
            images = image_name,
            group.by = annotation_column,
            label = TRUE,
            repel = TRUE,
            cols = annotation_palette
        )
        safe_name <- gsub("[^A-Za-z0-9_.-]", "_", image_name)
        ggsave(
            file.path(OUTPUT_DIRECTORY, paste0("annotated_spatial_map_", safe_name, ".png")),
            plot_object,
            width = 12,
            height = 10,
            dpi = 300
        )
    }
}

DefaultAssay(spatial_object) <- "Spatial"
spatial_object <- tryCatch(JoinLayers(spatial_object, assay = "Spatial"), error = function(e) spatial_object)
spatial_object <- NormalizeData(spatial_object, assay = "Spatial", verbose = FALSE)
Idents(spatial_object) <- REGION_COLUMN
fold_change_from_log2 <- function(log2_fc) 2^log2_fc
fold_change_direction <- function(log2_fc) ifelse(is.na(log2_fc), NA_character_, ifelse(log2_fc > 0, "Higher_in_region_or_test_group", ifelse(log2_fc < 0, "Lower_in_region_or_test_group", "No_change")))

region_markers <- FindAllMarkers(
    spatial_object,
    only.pos = TRUE,
    min.pct = 0.10,
    logfc.threshold = 0.25,
    fc.name = "avg_log2FC",
    base = 2
)
if ("avg_log2FC" %in% colnames(region_markers)) {
    region_markers$avg_FC <- fold_change_from_log2(region_markers$avg_log2FC)
    region_markers$Direction <- fold_change_direction(region_markers$avg_log2FC)
} else if ("avg_logFC" %in% colnames(region_markers)) {
    colnames(region_markers)[match("avg_logFC", colnames(region_markers))] <- "avg_log2FC"
    region_markers$avg_FC <- fold_change_from_log2(region_markers$avg_log2FC)
    region_markers$Direction <- fold_change_direction(region_markers$avg_log2FC)
}
marker_header_labels <- c(
    p_val = "p_val (Region vs all the other regions)",
    avg_log2FC = "avg_log2FC (Log2 expression difference: region vs all other regions)",
    avg_FC = "avg_FC (Conventional fold change: region / all other regions; 0.5 means half and 2 means twice)",
    Direction = "Direction (Whether expression is higher or lower inside the region)",
    pct.1 = "Percentage%Inside (% of spots in the cluster expressing the gene)",
    pct.2 = "Percentage%Outside (% of spots outside the cluster expressing the gene)",
    p_val_adj = "Bonferroni_Adjusted_P (Gene in region vs the same gene in all the other regions)",
    cluster = "Cluster (Cluster containing this gene)",
    gene = "gene (Candidate marker gene)"
)
marker_export <- region_markers
for (column_name in intersect(names(marker_header_labels), colnames(marker_export))) {
    colnames(marker_export)[match(column_name, colnames(marker_export))] <- marker_header_labels[[column_name]]
}
write.csv(marker_export, file.path(OUTPUT_DIRECTORY, "exploratory_region_markers.csv"), row.names = FALSE)

metadata <- spatial_object[[]]
can_run_sample_aware_de <- all(c(SAMPLE_COLUMN, REGION_COLUMN, TEST_VARIABLE) %in% colnames(metadata)) &&
    length(unique(metadata[[SAMPLE_COLUMN]])) >= 4L

if (can_run_sample_aware_de) {
    design_variables <- unique(all.vars(design_formula_object))
    missing_design_columns <- setdiff(design_variables, colnames(metadata))
    if (length(missing_design_columns)) stop("Design-formula column(s) are absent from the spatial Seurat metadata: ", paste(missing_design_columns, collapse = ", "))
    sample_ids <- as.character(metadata[[SAMPLE_COLUMN]])
    if (anyNA(sample_ids) || any(!nzchar(trimws(sample_ids)))) stop("Every spot must have a non-empty independent-sample ID before sample-aware DE can run.")
    inconsistent_entries <- character(0)
    for (sample_id in unique(sample_ids)) {
        sample_rows <- sample_ids == sample_id
        for (variable_name in design_variables) {
            observed_values <- metadata[[variable_name]][sample_rows]
            unique_values <- unique(as.character(observed_values[!is.na(observed_values)]))
            if (anyNA(observed_values) || length(unique_values) != 1L) inconsistent_entries <- c(inconsistent_entries, paste0(sample_id, ":", variable_name))
        }
    }
    if (length(inconsistent_entries)) stop("Sample-level design metadata must have exactly one non-missing value per independent sample. Conflicting sample:column entries: ", paste(unique(inconsistent_entries), collapse = ", "))
    sample_metadata <- metadata[!duplicated(metadata[[SAMPLE_COLUMN]]), , drop = FALSE]
    rownames(sample_metadata) <- as.character(sample_metadata[[SAMPLE_COLUMN]])
    sample_metadata[[TEST_VARIABLE]] <- factor(sample_metadata[[TEST_VARIABLE]])
    sample_metadata[[TEST_VARIABLE]] <- relevel(sample_metadata[[TEST_VARIABLE]], ref = REFERENCE_LEVEL)

    counts <- LayerData(spatial_object, assay = "Spatial", layer = "counts")
    regions <- sort(unique(as.character(metadata[[REGION_COLUMN]])))
    combined_region_results <- list()

    for (region in regions) {
        region_cells <- rownames(metadata)[as.character(metadata[[REGION_COLUMN]]) == region]
        region_meta <- metadata[region_cells, , drop = FALSE]
        spot_counts <- table(region_meta[[SAMPLE_COLUMN]])
        eligible_samples <- names(spot_counts)[spot_counts >= MINIMUM_SPOTS_PER_SAMPLE_REGION]
        current_sample_metadata <- sample_metadata[eligible_samples, , drop = FALSE]
        current_sample_metadata <- current_sample_metadata[current_sample_metadata[[TEST_VARIABLE]] %in% c(REFERENCE_LEVEL, TEST_LEVEL), , drop = FALSE]
        current_sample_metadata[[TEST_VARIABLE]] <- droplevels(current_sample_metadata[[TEST_VARIABLE]])

        group_sizes <- table(current_sample_metadata[[TEST_VARIABLE]])
        if (length(group_sizes) < 2L || any(group_sizes < MINIMUM_SAMPLES_PER_GROUP)) next

        selected_cells <- rownames(region_meta)[region_meta[[SAMPLE_COLUMN]] %in% rownames(current_sample_metadata)]
        selected_counts <- counts[, selected_cells, drop = FALSE]
        sample_factor <- factor(metadata[selected_cells, SAMPLE_COLUMN], levels = rownames(current_sample_metadata))
        aggregation_matrix <- sparse.model.matrix(~ 0 + sample_factor)
        colnames(aggregation_matrix) <- sub("^sample_factor", "", colnames(aggregation_matrix))
        pseudobulk_counts <- as.matrix(selected_counts %*% aggregation_matrix)
        current_sample_metadata <- current_sample_metadata[colnames(pseudobulk_counts), , drop = FALSE]

        design <- model.matrix(design_formula_object, current_sample_metadata)
        if (qr(design)$rank < ncol(design)) {
            warning("Skipping region ", region, ": the design matrix is rank deficient for the eligible independent samples.")
            next
        }
        reference_metadata <- current_sample_metadata
        test_metadata <- current_sample_metadata
        reference_metadata[[TEST_VARIABLE]] <- factor(REFERENCE_LEVEL, levels = levels(current_sample_metadata[[TEST_VARIABLE]]))
        test_metadata[[TEST_VARIABLE]] <- factor(TEST_LEVEL, levels = levels(current_sample_metadata[[TEST_VARIABLE]]))
        reference_design <- model.matrix(design_formula_object, reference_metadata)
        test_design <- model.matrix(design_formula_object, test_metadata)
        if (!identical(colnames(reference_design), colnames(design)) || !identical(colnames(test_design), colnames(design))) stop("Could not construct a consistent ", TEST_LEVEL, " versus ", REFERENCE_LEVEL, " contrast for region ", region, ".")
        contrast_vector <- colMeans(test_design - reference_design)
        if (!any(abs(contrast_vector) > sqrt(.Machine$double.eps))) stop("The design formula produces a zero ", TEST_LEVEL, " versus ", REFERENCE_LEVEL, " contrast. Include ", TEST_VARIABLE, " in an estimable term.")

        dge <- DGEList(pseudobulk_counts)
        keep <- filterByExpr(dge, design)
        dge <- dge[keep, , keep.lib.sizes = FALSE]
        dge <- calcNormFactors(dge)
        dge <- estimateDisp(dge, design, robust = TRUE)
        fit <- glmQLFit(dge, design, robust = TRUE)
        test <- glmQLFTest(fit, contrast = contrast_vector)
        result <- topTags(test, n = Inf)$table
        if ("logFC" %in% colnames(result)) {
            colnames(result)[match("logFC", colnames(result))] <- "log2FC"
            result$FC <- fold_change_from_log2(result$log2FC)
            result$Direction <- fold_change_direction(result$log2FC)
        }
        result$gene <- rownames(result)
        result$region <- region
        result$contrast <- paste0(TEST_LEVEL, "/", REFERENCE_LEVEL)
        combined_region_results[[region]] <- result

        safe_region <- gsub("[^A-Za-z0-9_.-]", "_", region)
        write.csv(result, file.path(OUTPUT_DIRECTORY, paste0("sample_aware_DE_region_", safe_region, ".csv")), row.names = FALSE)
    }

    if (length(combined_region_results)) {
        write.csv(
            do.call(rbind, combined_region_results),
            file.path(OUTPUT_DIRECTORY, "sample_aware_DE_all_regions.csv"),
            row.names = FALSE
        )
    }
} else {
    writeLines(
        "Sample-aware region DE was not run. It requires sample_id, region, condition, and replicated independent tissue sections.",
        file.path(OUTPUT_DIRECTORY, "sample_aware_DE_NOT_RUN.txt")
    )
}

SPATIAL_INPUT_RDS_FILE <- normalizePath(rds_files[spatial_indices], winslash = "/", mustWork = TRUE)
INHERITED_RDS_TAGS <- visium_rds_operation_tags(SPATIAL_INPUT_RDS_FILE, "S05")
step6_method_tag <- switch(DECONVOLUTION_METHOD, SeuratLabelTransfer = "DeconvLT", RCTD = paste0("DeconvRCTD", RCTD_MODE), None = "NoDeconv")
step6_operation_tag <- paste0(INHERITED_RDS_TAGS, "_", step6_method_tag, "_RegDE")
OUTPUT_RDS_FILE <- visium_tagged_rds_path(RESULTS_WORKSPACE, "6_Deconvolution_Region_DE", "S06", step6_operation_tag)
saveRDS(spatial_object, OUTPUT_RDS_FILE, compress = FALSE)
save_session_information()
cat("\nSpatial cell-type mapping and region analysis completed successfully.\nOutput object: ",OUTPUT_RDS_FILE,"\n",sep="")
