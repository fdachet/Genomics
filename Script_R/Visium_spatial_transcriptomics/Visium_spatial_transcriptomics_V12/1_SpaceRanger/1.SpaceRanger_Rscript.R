

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
    visium_print_help("Script 1 - Space Ranger", "Rscript 1.SpaceRanger_Rscript.R [--gui|--cli] [options]", c(
        "--gui  Open the colored native desktop GUI.", "--cli  Run headlessly with defaults.",
        "--input-dir PATH  Required base folder for relative paths in the sample sheet.",
        "--results-parent PATH  Existing Results parent folder; each sample folder is created inside it.",
        "--sample-sheet PATH  Required CSV selected by the user.",
        "--reference-directory PATH  Existing 10x-compatible reference selected by the user.",
        "--reference-fasta PATH  Required when building a reference.",
        "--reference-gtf PATH  Required when building a reference.",
        "--spaceranger-executable PATH", "--wsl-distribution NAME", "--local-cores INT",
        "--local-memory-gb INT", "--create-bam BOOL", "--build-reference-if-needed BOOL", "--reference-name NAME"
    ))
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
    tcltk::tkpack(tcltk::tklabel(hero, text = "Runs Space Ranger to create Visium gene-by-spot Count_RNAs matrices and spatial outputs.", background = accent, foreground = "white", anchor = "w", padx = 22L, pady = 4L), fill = "x")

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

defaults <- list(
    input_dir = "", output_dir = PIPELINE_DIRECTORY,
    sample_sheet = "", spaceranger_executable = "/usr/local/bin/spaceranger", wsl_distribution = "Debian",
    local_cores = 12L, local_memory_gb = 45L, create_bam = TRUE,
    build_reference_if_needed = TRUE, reference_name = "custom_reference",
    reference_directory = "", reference_fasta = "", reference_gtf = ""
)
run_gui <- interactive() || !length(commandArgs(trailingOnly = TRUE)) || isTRUE(cli$gui)
if (isTRUE(cli$cli)) run_gui <- FALSE
if (run_gui) {
    gui <- visium_desktop_gui("Script 1 - Space Ranger", list(
        list(name="input_dir", label="Base folder for sample-sheet relative paths", value=defaults$input_dir, type="directory", group="Files", required=TRUE, must_exist=TRUE),
        list(name="input_dir_help", type="info", group="Files", text="Select the folder used as the base for relative fastq_directory and image_file paths in the sample sheet. No input file is selected automatically from this folder."),
        list(name="sample_sheet", label="Spatial sample-sheet CSV", value=defaults$sample_sheet, type="file", group="Files", required=TRUE, must_exist=TRUE),
        list(name="sample_sheet_help", type="info", group="Files", text="Required columns: sample_id, fastq_sample, fastq_directory, image_file, slide, and area. The CSV explicitly records the FASTQ folder and tissue image used for every sample."),
        list(name="results_parent", label="Results parent folder", value=defaults$output_dir, type="directory", group="Files", required=TRUE, must_exist=TRUE),
        list(name="results_parent_help", type="info", group="Files", text="For every sample_id row, Step 1 creates <Results parent>/<sample_id>, writes Space Ranger results into its 1_SpaceRanger folder, and creates Seurat_RDS for the tagged RDS objects produced by Steps 2-7."),
        list(name="spaceranger_executable", label="Space Ranger executable", value=defaults$spaceranger_executable, type="text", group="Space Ranger", required=TRUE),
        list(name="wsl_distribution", label="WSL distribution", value=defaults$wsl_distribution, type="text", group="Space Ranger", required=TRUE),
        list(name="local_cores", label="CPU cores", value=defaults$local_cores, type="integer", group="Space Ranger"),
        list(name="local_memory_gb", label="Memory (GB)", value=defaults$local_memory_gb, type="integer", group="Space Ranger"),
        list(name="create_bam", label="Create BAM files", value=defaults$create_bam, type="boolean", group="Space Ranger"),
        list(name="build_reference_if_needed", label="Build reference if needed", value=defaults$build_reference_if_needed, type="boolean", group="Reference"),
        list(name="reference_directory", label="Existing 10x transcriptome reference folder", value=defaults$reference_directory, type="directory", group="Reference"),
        list(name="reference_directory_help", type="info", group="Reference", text="Select an existing Space Ranger-compatible reference folder containing reference.json and the star directory. Leave blank only when building a new reference from the explicitly selected FASTA and GTF files."),
        list(name="reference_fasta", label="Reference genome FASTA (when building)", value=defaults$reference_fasta, type="file", group="Reference"),
        list(name="reference_gtf", label="Reference gene annotation GTF (when building)", value=defaults$reference_gtf, type="file", group="Reference"),
        list(name="reference_name", label="Reference name", value=defaults$reference_name, type="text", group="Reference", required=TRUE)
    ), accent="#0B6E4F")
    cli <- modifyList(cli, gui)
}
INPUT_DIRECTORY <- visium_option(cli, "input-dir", defaults$input_dir, "path")
OUTPUT_DIRECTORY <- visium_option(cli, "results-parent", visium_option(cli, "output-dir", defaults$output_dir, "path"), "path")
SAMPLE_SHEET_OPTION <- visium_option(cli, "sample-sheet", defaults$sample_sheet, "path")
SPACERANGER_EXECUTABLE <- visium_option(cli, "spaceranger-executable", defaults$spaceranger_executable)
WSL_DISTRIBUTION <- visium_option(cli, "wsl-distribution", defaults$wsl_distribution)
LOCAL_CORES <- visium_option(cli, "local-cores", defaults$local_cores, "integer")
LOCAL_MEMORY_GB <- visium_option(cli, "local-memory-gb", defaults$local_memory_gb, "integer")
CREATE_BAM <- visium_option(cli, "create-bam", defaults$create_bam, "boolean")
BUILD_REFERENCE_IF_NEEDED <- visium_option(cli, "build-reference-if-needed", defaults$build_reference_if_needed, "boolean")
REFERENCE_NAME <- visium_option(cli, "reference-name", defaults$reference_name)
REFERENCE_DIRECTORY_OPTION <- visium_option(cli, "reference-directory", defaults$reference_directory, "path")
REFERENCE_FASTA_OPTION <- visium_option(cli, "reference-fasta", defaults$reference_fasta, "path")
REFERENCE_GTF_OPTION <- visium_option(cli, "reference-gtf", defaults$reference_gtf, "path")
if (LOCAL_CORES < 1L || LOCAL_MEMORY_GB < 1L) stop("CPU cores and memory must be positive.")
if (!nzchar(INPUT_DIRECTORY) || !dir.exists(INPUT_DIRECTORY)) stop("Select an existing base input folder with --input-dir.")
if (!nzchar(SAMPLE_SHEET_OPTION) || !file.exists(SAMPLE_SHEET_OPTION) || isTRUE(file.info(SAMPLE_SHEET_OPTION)$isdir)) {
    stop("Select the spatial sample-sheet CSV explicitly with --sample-sheet.")
}

dir.create(OUTPUT_DIRECTORY, recursive = TRUE, showWarnings = FALSE)
BATCH_LOG_DIRECTORY <- file.path(OUTPUT_DIRECTORY, "00_Pipeline_Batch_Logs")
dir.create(BATCH_LOG_DIRECTORY, recursive = TRUE, showWarnings = FALSE)

LOG_FILE <- file.path(BATCH_LOG_DIRECTORY, "1_SpaceRanger_run_log.txt")
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
    capture.output(sessionInfo(), file = file.path(BATCH_LOG_DIRECTORY, "1_SpaceRanger_sessionInfo.txt"))
}

bash_quote <- function(value) {
    if (any(grepl("'", value, fixed = TRUE))) {
        stop("Single-quote characters are not supported in file paths for this wrapper.")
    }
    paste0("'", value, "'")
}
is_windows <- identical(.Platform$OS.type, "windows")

windows_to_wsl_path <- function(path) {
    normalized_path <- normalizePath(path, winslash = "\\", mustWork = FALSE)
    result <- system2(
        "wsl.exe",
        args = c("-d", WSL_DISTRIBUTION, "--", "wslpath", "-a", "-u", normalized_path),
        stdout = TRUE,
        stderr = TRUE
    )
    if (!length(result) || !nzchar(result[1L])) stop("Could not convert path to WSL: ", path)
    trimws(result[1L])
}

linux_path <- function(path) {
    if (is_windows) windows_to_wsl_path(path) else normalizePath(path, winslash = "/", mustWork = FALSE)
}

run_linux_command <- function(command, working_directory = NULL) {
    if (!is.null(working_directory)) {
        command <- paste("cd", bash_quote(linux_path(working_directory)), "&&", command)
    }
    cat("\nCOMMAND\n", command, "\n\n", sep = "")
    status <- if (is_windows) {
        command_file <- tempfile(pattern = "SpaceRanger_command_", tmpdir = OUTPUT_DIRECTORY, fileext = ".sh")
        writeLines(c("#!/usr/bin/env bash", command), command_file, useBytes = TRUE)
        command_file_linux <- windows_to_wsl_path(command_file)
        command_status <- system2(
            "wsl.exe",
            args = c("-d", WSL_DISTRIBUTION, "--", "bash", command_file_linux)
        )
        unlink(command_file)
        command_status
    } else {
        system2("bash", args = c("-lc", command))
    }
    if (!identical(status, 0L)) stop("External Linux command failed with exit status ", status)
}

sample_sheet_files <- normalizePath(SAMPLE_SHEET_OPTION, winslash = "/", mustWork = TRUE)
sample_sheet <- read.csv(sample_sheet_files, check.names = FALSE, na.strings = c("", "NA"))
required_columns <- c("sample_id", "fastq_sample", "fastq_directory", "image_file", "slide", "area")
missing_columns <- setdiff(required_columns, colnames(sample_sheet))
if (length(missing_columns)) stop("Sample sheet is missing: ", paste(missing_columns, collapse = ", "))

reference_directory <- NULL

if (nzchar(REFERENCE_DIRECTORY_OPTION)) {
    if (!dir.exists(REFERENCE_DIRECTORY_OPTION)) stop("Selected reference directory does not exist: ", REFERENCE_DIRECTORY_OPTION)
    if (!file.exists(file.path(REFERENCE_DIRECTORY_OPTION, "reference.json")) || !dir.exists(file.path(REFERENCE_DIRECTORY_OPTION, "star"))) {
        stop("Selected reference directory is not Space Ranger compatible; reference.json or star is missing: ", REFERENCE_DIRECTORY_OPTION)
    }
    reference_directory <- normalizePath(REFERENCE_DIRECTORY_OPTION, winslash = "/", mustWork = TRUE)
} else if (BUILD_REFERENCE_IF_NEEDED) {
    if (!nzchar(REFERENCE_FASTA_OPTION) || !file.exists(REFERENCE_FASTA_OPTION)) {
        stop("Building a reference requires an explicitly selected FASTA file (--reference-fasta).")
    }
    if (!nzchar(REFERENCE_GTF_OPTION) || !file.exists(REFERENCE_GTF_OPTION)) {
        stop("Building a reference requires an explicitly selected GTF file (--reference-gtf).")
    }
    fasta_file <- normalizePath(REFERENCE_FASTA_OPTION, winslash = "/", mustWork = TRUE)
    gtf_file <- normalizePath(REFERENCE_GTF_OPTION, winslash = "/", mustWork = TRUE)

    reference_build_parent <- file.path(OUTPUT_DIRECTORY, "00_Shared_SpaceRanger_Reference")
    dir.create(reference_build_parent, recursive = TRUE, showWarnings = FALSE)

    mkref_command <- paste(
        bash_quote(SPACERANGER_EXECUTABLE), "mkref",
        paste0("--genome=", bash_quote(REFERENCE_NAME)),
        paste0("--fasta=", bash_quote(linux_path(fasta_file))),
        paste0("--genes=", bash_quote(linux_path(gtf_file))),
        paste0("--nthreads=", LOCAL_CORES),
        paste0("--memgb=", LOCAL_MEMORY_GB)
    )
    run_linux_command(mkref_command, working_directory = reference_build_parent)
    reference_directory <- file.path(reference_build_parent, REFERENCE_NAME)
} else {
    stop("Select an existing 10x reference directory or enable reference building and select both FASTA and GTF files.")
}

run_manifest <- list()
sample_stage_directories <- character(0)

for (row_index in seq_len(nrow(sample_sheet))) {
    sample_id <- as.character(sample_sheet$sample_id[row_index])
    fastq_sample <- as.character(sample_sheet$fastq_sample[row_index])
    image_value <- as.character(sample_sheet$image_file[row_index])
    slide <- as.character(sample_sheet$slide[row_index])
    area <- as.character(sample_sheet$area[row_index])
    required_values <- c(sample_id = sample_id, fastq_sample = fastq_sample, image_file = image_value, slide = slide, area = area)
    blank_values <- names(required_values)[is.na(required_values) | !nzchar(trimws(required_values))]
    if (length(blank_values)) {
        stop("Sample sheet row ", row_index, " has blank required value(s): ", paste(blank_values, collapse = ", "), ".")
    }
    if (!grepl("^[A-Za-z0-9_-]+$", sample_id)) stop("sample_id must contain only letters, numbers, underscores, or hyphens in sample sheet row ", row_index, ": ", sample_id)
    image_path <- if (file.exists(image_value)) image_value else file.path(INPUT_DIRECTORY, image_value)
    if (!file.exists(image_path)) stop("Tissue image not found for ", sample_id, ": ", image_path)
    if (isTRUE(file.info(image_path)$isdir)) stop("Tissue image is a directory rather than an image file for ", sample_id, ": ", image_path)
    if (!grepl("\\.(tif|tiff|jpg|jpeg)$", basename(image_path), ignore.case = TRUE)) {
        stop("Space Ranger --image requires a brightfield TIFF, JPG, or JPEG file for ", sample_id, ": ", image_path)
    }

    fastq_directory_value <- as.character(sample_sheet$fastq_directory[row_index])
    if (is.na(fastq_directory_value) || !nzchar(trimws(fastq_directory_value))) {
        stop("fastq_directory is blank for sample ", sample_id, ".")
    }
    fastq_directory <- if (dir.exists(fastq_directory_value)) fastq_directory_value else file.path(INPUT_DIRECTORY, fastq_directory_value)
    if (!dir.exists(fastq_directory)) stop("FASTQ directory not found for ", sample_id, ": ", fastq_directory)
    sample_fastqs <- list.files(fastq_directory, pattern = "\\.fastq\\.gz$", recursive = TRUE, full.names = TRUE, ignore.case = TRUE)
    if (!length(sample_fastqs)) stop("No FASTQ files were found in the selected directory for ", sample_id, ": ", fastq_directory)

    sample_results_workspace <- visium_create_results_workspace(OUTPUT_DIRECTORY, sample_id)
    sample_output_parent <- visium_stage_directory(sample_results_workspace, "1_SpaceRanger", create = TRUE)
    sample_stage_directories <- c(sample_stage_directories, sample_output_parent)
    dir.create(sample_output_parent, recursive = TRUE, showWarnings = FALSE)

    arguments <- c(
        paste0("--id=", bash_quote(sample_id)),
        paste0("--transcriptome=", bash_quote(linux_path(reference_directory))),
        paste0("--fastqs=", bash_quote(linux_path(fastq_directory))),
        paste0("--sample=", bash_quote(fastq_sample)),
        paste0("--image=", bash_quote(linux_path(image_path))),
        paste0("--slide=", bash_quote(slide)),
        paste0("--area=", bash_quote(area)),
        paste0("--create-bam=", tolower(as.character(CREATE_BAM))),
        paste0("--localcores=", LOCAL_CORES),
        paste0("--localmem=", LOCAL_MEMORY_GB)
    )

    command <- paste(bash_quote(SPACERANGER_EXECUTABLE), "count", paste(arguments, collapse = " "))
    run_linux_command(command, working_directory = sample_output_parent)

    outs_directory <- file.path(sample_output_parent, sample_id, "outs")
    required_outputs <- c(
        file.path(outs_directory, "filtered_feature_bc_matrix.h5"),
        file.path(outs_directory, "spatial")
    )
    if (!all(file.exists(required_outputs))) {
        stop("Space Ranger finished but expected outputs were not found for sample: ", sample_id)
    }

    run_manifest[[sample_id]] <- data.frame(
        sample_id = sample_id,
        results_workspace = sample_results_workspace,
        outs_directory = normalizePath(outs_directory, winslash = "/", mustWork = TRUE),
        stringsAsFactors = FALSE
    )
    write.csv(run_manifest[[sample_id]], file.path(sample_output_parent, "SpaceRanger_output_manifest.csv"), row.names = FALSE)
}

write.csv(do.call(rbind, run_manifest), file.path(BATCH_LOG_DIRECTORY, "SpaceRanger_output_manifest_all_samples.csv"), row.names = FALSE)
save_session_information()
flush(log_connection)
for (sample_stage_directory in unique(sample_stage_directories)) {
    file.copy(LOG_FILE, file.path(sample_stage_directory, "run_log.txt"), overwrite = TRUE)
    file.copy(file.path(BATCH_LOG_DIRECTORY, "1_SpaceRanger_sessionInfo.txt"), file.path(sample_stage_directory, "sessionInfo.txt"), overwrite = TRUE)
}
cat("\nSpace Ranger processing completed successfully.\n")
