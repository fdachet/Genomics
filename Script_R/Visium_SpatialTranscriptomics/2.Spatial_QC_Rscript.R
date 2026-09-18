options(stringsAsFactors=FALSE)
get_script_directory <- function() {
    a<-commandArgs(FALSE); f<-grep("^--file=",a,value=TRUE)
    if(length(f)) {
        command_file <- sub("^--file=", "", f[[1L]])
        if (nzchar(command_file) && !identical(command_file, "-e")) {
            return(dirname(normalizePath(command_file, winslash="/", mustWork=FALSE)))
        }
    }
    source_files <- unlist(lapply(rev(sys.frames()), function(frame) {
        path <- frame$ofile
        if (is.null(path) || !length(path)) character(0) else as.character(path)[1L]
    }), use.names = FALSE)
    source_files <- source_files[!is.na(source_files) & nzchar(source_files)]
    if (length(source_files)) {
        return(dirname(normalizePath(source_files[[1L]], winslash="/", mustWork=FALSE)))
    }
    if(requireNamespace("rstudioapi",quietly=TRUE)&&rstudioapi::isAvailable()) { p<-tryCatch(rstudioapi::getActiveDocumentContext()$path,error=function(e)""); if(nzchar(p)) return(dirname(normalizePath(p,winslash="/",mustWork=FALSE))) }
    normalizePath(getwd(),winslash="/",mustWork=FALSE)
}
SCRIPT_DIRECTORY<-get_script_directory()
PIPELINE_DIRECTORY<-dirname(SCRIPT_DIRECTORY)

ROOT_BROWSE_DIRECTORY<-normalizePath(SCRIPT_DIRECTORY,winslash="/",mustWork=TRUE)

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
        "Script 2 - Spatial QC",
        "Rscript 2.Spatial_QC_Rscript.R [--gui|--cli] [options]",
        c(
            "--gui  Open colored native desktop GUI.", "--cli  Run headlessly.",
            "--results-dir PATH  Required existing parent Results folder selected by the user.",
            "--sample-name NAME  Sample folder to create inside Results (default: Sample_01).",
            "--matrix-h5-file PATH  Required filtered_feature_bc_matrix.h5 selected by the user.",
            "--tissue-positions-file PATH  Required tissue_positions CSV selected by the user.",
            "--scalefactors-file PATH  Required scalefactors_json.json selected by the user.",
            "--tissue-image-file PATH  Required tissue image selected by the user.",
            "--tissue-image-scale hires|lowres", "--min-features N  Minimum detected Feature_Genes/spot.", "--max-features N|Inf  Maximum detected Feature_Genes/spot.",
            "--min-counts N  Minimum total Count_RNAs/spot.", "--max-counts N|Inf  Maximum total Count_RNAs/spot.", "--max-percent-mt N",
            "--qc-low-color COLOR", "--qc-high-color COLOR", "--qc-violin-color COLOR"
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
    tcltk::tkpack(tcltk::tklabel(hero, text = "Calculates spot QC metrics and removes low-quality spatial spots.", background = accent, foreground = "white", anchor = "w", padx = 22L, pady = 4L), fill = "x")

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

                        initial_dir <- ROOT_BROWSE_DIRECTORY
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
                if (
                    identical(f$type, "file") &&
                    !is.null(f$path_pattern) &&
                    nzchar(trimws(as.character(value)[1L])) &&
                    !grepl(f$path_pattern, basename(as.character(value)[1L]), ignore.case = TRUE)
                ) {
                    expected <- if (is.null(f$path_message)) paste0("a filename matching ", f$path_pattern) else f$path_message
                    stop(f$label, " must be ", expected, ".\nSelected: ", basename(as.character(value)[1L]))
                }
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

defaults<-list(
    results_dir="",
    sample_name="Sample_01",
    input_source="Space Ranger H5 + spatial files",
    matrix_h5_file="",
    pre_qc_rds_file="",
    tissue_positions_file="",
    scalefactors_file="",
    tissue_image_file="",
    tissue_image_scale="hires",
    min_features=200,max_features=Inf,min_counts=500,max_counts=Inf,max_percent_mt=8,
    mitochondrial_pattern="^(MT-|mt-)",qc_low_color="#2166AC",qc_high_color="#B2182B",qc_violin_color="#2A9D8F"
)
run_gui<-interactive()||!length(commandArgs(TRUE))||isTRUE(cli$gui);if(isTRUE(cli$cli))run_gui<-FALSE
if(run_gui){gui<-visium_desktop_gui("Script 2 - Spatial Quality Control",list(
    list(name="results_dir",label="Results parent folder",value=defaults$results_dir,type="directory",group="Files",required=TRUE,must_exist=TRUE),
    list(name="sample_name",label="Sample name",value=defaults$sample_name,type="text",group="Files",required=TRUE),
    list(name="sample_results_help",type="info",group="Files",text="Select the existing parent Results folder and enter the sample name. This script creates Results/<sample name>, Results/<sample name>/Seurat_RDS, and Results/<sample name>/2_Spatial_QC."),
    list(name="input_source",label="Input type",value=defaults$input_source,type="radio",choices=c("Space Ranger H5 + spatial files","Pre-QC unfiltered Seurat RDS"),group="Files"),
    list(name="input_source_help",type="info",group="Files",text="Choose one input route. H5 mode requires the H5 matrix plus the three spatial files below. Pre-QC RDS mode requires only a non-filtered spatial Seurat RDS that already contains its tissue image and spot coordinates."),
    list(name="matrix_h5_file",label="H5 mode - filtered gene-feature/barcode Count_RNAs matrix",value="",type="file",group="Files",required=FALSE,must_exist=FALSE,path_pattern="filtered_feature_bc_matrix\\.h5$",path_message="filtered_feature_bc_matrix.h5"),
    list(name="matrix_h5_help",type="info",group="Files",text="H5 mode only: select the Space Ranger filtered_feature_bc_matrix.h5 containing the gene-by-spot Count_RNAs matrix."),
    list(name="pre_qc_rds_file",label="RDS mode - pre-QC unfiltered spatial Seurat RDS",value="",type="file",group="Files",required=FALSE,must_exist=FALSE,path_pattern="\\.rds$",path_message="an .rds file"),
    list(name="pre_qc_rds_help",type="info",group="Files",text="RDS mode only: select a pre-QC, non-filtered Seurat object. The object must contain a Spatial assay with a counts layer and its Visium tissue image/coordinates."),
    list(name="tissue_positions_file",label="H5 mode - tissue positions CSV",value="",type="file",group="Files",required=FALSE,must_exist=FALSE,path_pattern="tissue_positions(_list)?\\.csv$",path_message="tissue_positions.csv or tissue_positions_list.csv"),
    list(name="tissue_positions_help",type="info",group="Files",text="Select tissue_positions.csv or the legacy tissue_positions_list.csv containing spot barcodes, tissue membership, and spatial coordinates."),
    list(name="scalefactors_file",label="H5 mode - scale factors JSON",value="",type="file",group="Files",required=FALSE,must_exist=FALSE,path_pattern="scalefactors_json\\.json$",path_message="scalefactors_json.json"),
    list(name="scalefactors_help",type="info",group="Files",text="Select scalefactors_json.json. This is JSON metadata and must not be the tissue-positions CSV."),
    list(name="tissue_image_file",label="H5 mode - tissue image (PNG)",value="",type="file",group="Files",required=FALSE,must_exist=FALSE,path_pattern="\\.png$",path_message="the Space Ranger PNG tissue image"),
    list(name="tissue_image_help",type="info",group="Files",text="Select tissue_hires_image.png or tissue_lowres_image.png. Seurat Read10X_Image reads the Space Ranger PNG image; convert another image format to PNG before selecting it."),
    list(name="tissue_image_scale",label="Image scale",value="hires",type="radio",choices=c("hires","lowres"),group="Files"),
    list(name="qc_threshold_help",type="info",group="QC",text="These thresholds are starting values, not universal biological cutoffs. Review the QC distributions and tissue maps for this sample, then adjust them for the tissue, chemistry, sequencing depth, and expected biology."),
    list(name="min_features",label="Minimum Feature_Genes/spot (nFeature_Spatial)",value=200,type="number",group="QC"),list(name="max_features",label="Maximum Feature_Genes/spot (nFeature_Spatial)",value=Inf,type="number",infinite=TRUE,group="QC"),list(name="min_counts",label="Minimum Count_RNAs/spot (nCount_Spatial)",value=500,type="number",group="QC"),list(name="max_counts",label="Maximum Count_RNAs/spot (nCount_Spatial)",value=Inf,type="number",infinite=TRUE,group="QC"),list(name="max_percent_mt",label="Maximum mitochondrial percentage (percent.mt)",value=8,type="number",group="QC"),list(name="mitochondrial_pattern",label="Mitochondrial gene-name regex",value="^(MT-|mt-)",type="text",group="QC")
),accent="#0077B6");cli<-modifyList(cli,gui)}
RESULTS_PARENT<-visium_option(cli,"results-dir",defaults$results_dir,"path")
SAMPLE_ID<-visium_safe_sample_name(visium_option(cli,"sample-name",defaults$sample_name))
RESULTS_WORKSPACE<-visium_create_results_workspace(RESULTS_PARENT,SAMPLE_ID)
OUTPUT_DIRECTORY<-visium_stage_directory(RESULTS_WORKSPACE,"2_Spatial_QC",create=TRUE)
INPUT_SOURCE<-visium_option(cli,"input-source",defaults$input_source,"choice",c("Space Ranger H5 + spatial files","Pre-QC unfiltered Seurat RDS"))
MATRIX_H5_FILE<-visium_option(cli,"matrix-h5-file","","path");PRE_QC_INPUT_RDS_FILE<-visium_option(cli,"pre-qc-rds-file","","path");TISSUE_POSITIONS_FILE<-visium_option(cli,"tissue-positions-file","","path");TISSUE_POSITIONS_HAS_HEADER<-nzchar(TISSUE_POSITIONS_FILE)&&identical(tolower(basename(TISSUE_POSITIONS_FILE)),"tissue_positions.csv");SCALEFACTORS_FILE<-visium_option(cli,"scalefactors-file","","path");TISSUE_IMAGE_FILE<-visium_option(cli,"tissue-image-file","","path");TISSUE_IMAGE_SCALE<-visium_option(cli,"tissue-image-scale","hires","choice",c("hires","lowres"))
MIN_FEATURES<-visium_option(cli,"min-features",200,"number");MAX_FEATURES<-visium_option(cli,"max-features",Inf,"number",infinite=TRUE);MIN_COUNTS<-visium_option(cli,"min-counts",500,"number");MAX_COUNTS<-visium_option(cli,"max-counts",Inf,"number",infinite=TRUE);MAX_PERCENT_MT<-visium_option(cli,"max-percent-mt",8,"number");MITOCHONDRIAL_PATTERN<-visium_option(cli,"mitochondrial-pattern",defaults$mitochondrial_pattern)
QC_LOW_COLOR<-visium_option(cli,"qc-low-color","#2166AC");QC_HIGH_COLOR<-visium_option(cli,"qc-high-color","#B2182B");QC_VIOLIN_COLOR<-visium_option(cli,"qc-violin-color","#2A9D8F");visium_colors(c(QC_LOW_COLOR,QC_HIGH_COLOR,QC_VIOLIN_COLOR),"QC colors",3L)
if (MIN_FEATURES < 0 || MIN_COUNTS < 0) stop("Minimum detected-gene and total-RNA thresholds cannot be negative.")
if (MIN_FEATURES > MAX_FEATURES) stop("Minimum detected Feature_Genes cannot exceed maximum detected Feature_Genes.")
if (MIN_COUNTS > MAX_COUNTS) stop("Minimum Count_RNAs/spot cannot exceed maximum Count_RNAs/spot.")
if (MAX_PERCENT_MT < 0 || MAX_PERCENT_MT > 100) stop("Maximum mitochondrial percentage must be between 0 and 100.")
if (inherits(try(grepl(MITOCHONDRIAL_PATTERN, "MT-CO1"), silent = TRUE), "try-error")) stop("Mitochondrial pattern is not a valid regular expression.")

RUNNING_DIRECTORY <- SCRIPT_DIRECTORY
SEURAT_INPUT_DIRECTORY <- file.path(OUTPUT_DIRECTORY, "_Seurat_Formatted_Input")
SEURAT_SPATIAL_DIRECTORY <- file.path(SEURAT_INPUT_DIRECTORY, "spatial")

dir.create(OUTPUT_DIRECTORY, recursive = TRUE, showWarnings = FALSE)

LOG_FILE <- file.path(OUTPUT_DIRECTORY, "run_log.txt")
log_connection <- file(LOG_FILE, open = "wt")
sink(log_connection, type = "output", split = TRUE)
sink(log_connection, type = "message")

on.exit({
    cat("\n\n================ SESSION INFORMATION ================\n")
    print(sessionInfo())
    try(sink(type = "message"), silent = TRUE)
    try(sink(type = "output"), silent = TRUE)
    try(close(log_connection), silent = TRUE)
}, add = TRUE)

cat("Running directory:", RUNNING_DIRECTORY, "\n")
cat("Sample name:", SAMPLE_ID, "\n")
cat("Sample results folder:", RESULTS_WORKSPACE, "\n")
cat("Output directory:", OUTPUT_DIRECTORY, "\n")
cat("Started:", format(Sys.time()), "\n\n")

require_packages <- function(packages) {
    missing_packages <- packages[
        !vapply(packages, requireNamespace, logical(1), quietly = TRUE)
    ]

    if (length(missing_packages) > 0L) {
        stop(
            "Missing required R package(s): ",
            paste(missing_packages, collapse = ", "),
            "\nRun 00_Install_R_Packages.R first."
        )
    }
}

copy_required_file <- function(source_file, destination_file) {
    if (!file.exists(source_file)) {
        stop("Required input file was not found:\n", source_file)
    }

    if (!file.copy(source_file, destination_file, overwrite = TRUE)) {
        stop("Could not copy:\n", source_file, "\nTo:\n", destination_file)
    }
}

save_session_information <- function() {
    capture.output(
        sessionInfo(),
        file = file.path(OUTPUT_DIRECTORY, "sessionInfo.txt")
    )
}

compact_number_labels <- function(values) {
    vapply(values, function(value) {
        if (is.na(value)) return("")
        if (!is.finite(value)) return(as.character(value))
        absolute_value <- abs(value)
        if (absolute_value >= 1e9) {
            scaled_value <- value / 1e9
            suffix <- "B"
        } else if (absolute_value >= 1e6) {
            scaled_value <- value / 1e6
            suffix <- "M"
        } else if (absolute_value >= 1e3) {
            scaled_value <- value / 1e3
            suffix <- "k"
        } else {
            scaled_value <- value
            suffix <- ""
        }
        digits <- if (abs(scaled_value - round(scaled_value)) < 1e-9) 0L else 1L
        paste0(formatC(scaled_value, format = "f", digits = digits), suffix)
    }, character(1))
}

compact_percent_labels <- function(values) {
    vapply(values, function(value) {
        if (is.na(value)) return("")
        if (!is.finite(value)) return(as.character(value))
        digits <- if (abs(value - round(value)) < 1e-9) 0L else 1L
        paste0(formatC(value, format = "f", digits = digits), "%")
    }, character(1))
}

require_packages(c("Seurat", "SeuratObject", "ggplot2", "patchwork", "jsonlite"))

suppressPackageStartupMessages({
    library(Seurat)
    library(SeuratObject)
    library(ggplot2)
    library(patchwork)
})

TISSUE_IMAGE_SCALE <- tolower(trimws(TISSUE_IMAGE_SCALE))

if (!TISSUE_IMAGE_SCALE %in% c("lowres", "hires")) {
    stop('TISSUE_IMAGE_SCALE must be "lowres" or "hires".')
}

if (
    identical(INPUT_SOURCE, "Space Ranger H5 + spatial files") &&
    grepl("hires", basename(TISSUE_IMAGE_FILE), ignore.case = TRUE) &&
    TISSUE_IMAGE_SCALE != "hires"
) {
    stop(
        'The image filename contains "hires", so ',
        'TISSUE_IMAGE_SCALE must be "hires".'
    )
}

if (
    identical(INPUT_SOURCE, "Space Ranger H5 + spatial files") &&
    grepl("lowres", basename(TISSUE_IMAGE_FILE), ignore.case = TRUE) &&
    TISSUE_IMAGE_SCALE != "lowres"
) {
    stop(
        'The image filename contains "lowres", so ',
        'TISSUE_IMAGE_SCALE must be "lowres".'
    )
}

resolve_input <- function(x) {
    x <- trimws(as.character(x)[1L])
    if (!nzchar(x)) return("")
    normalizePath(x, winslash = "/", mustWork = FALSE)
}
MATRIX_H5_PATH <- resolve_input(MATRIX_H5_FILE)
PRE_QC_INPUT_RDS_PATH <- resolve_input(PRE_QC_INPUT_RDS_FILE)
TISSUE_POSITIONS_PATH <- resolve_input(TISSUE_POSITIONS_FILE)
SCALEFACTORS_PATH <- resolve_input(SCALEFACTORS_FILE)
TISSUE_IMAGE_PATH <- resolve_input(TISSUE_IMAGE_FILE)

cat("Input type:", INPUT_SOURCE, "\n")

if (identical(INPUT_SOURCE, "Space Ranger H5 + spatial files")) {
    required_spatial_inputs <- c(
        "Filtered matrix H5" = MATRIX_H5_PATH,
        "Tissue positions CSV" = TISSUE_POSITIONS_PATH,
        "Scale factors JSON" = SCALEFACTORS_PATH,
        "Tissue image" = TISSUE_IMAGE_PATH
    )
    missing_spatial_inputs <- names(required_spatial_inputs)[vapply(required_spatial_inputs, function(path) {
        !nzchar(path) || !file.exists(path) || isTRUE(file.info(path)$isdir)
    }, logical(1))]
    if (length(missing_spatial_inputs)) {
        stop("H5 input mode is missing: ", paste(missing_spatial_inputs, collapse = ", "), ".")
    }
    normalized_input_paths <- normalizePath(required_spatial_inputs, winslash = "/", mustWork = TRUE)
    if (anyDuplicated(tolower(normalized_input_paths))) stop("Each H5/spatial input selector must point to a different file.")
    if (!grepl("filtered_feature_bc_matrix\\.h5$", basename(MATRIX_H5_PATH), ignore.case = TRUE)) stop("Filtered matrix H5 must end with filtered_feature_bc_matrix.h5.")
    if (!grepl("tissue_positions(_list)?\\.csv$", basename(TISSUE_POSITIONS_PATH), ignore.case = TRUE)) stop("Tissue positions must be tissue_positions.csv or tissue_positions_list.csv.")
    if (!grepl("scalefactors_json\\.json$", basename(SCALEFACTORS_PATH), ignore.case = TRUE)) stop("Scale factors JSON must be scalefactors_json.json.")
    if (!grepl("\\.png$", basename(TISSUE_IMAGE_PATH), ignore.case = TRUE)) stop("Tissue image must be the Space Ranger PNG image read by Seurat Read10X_Image.")

    positions_file_has_header <- identical(tolower(basename(TISSUE_POSITIONS_PATH)), "tissue_positions.csv")
    if (!identical(TISSUE_POSITIONS_HAS_HEADER, positions_file_has_header)) stop("Positions CSV header setting does not match ", basename(TISSUE_POSITIONS_PATH), ".")
    scale_factors_data <- tryCatch(jsonlite::fromJSON(SCALEFACTORS_PATH, simplifyVector = TRUE), error = function(error) stop("Scale factors JSON is not valid JSON:\n", conditionMessage(error)))
    required_scale_keys <- c("tissue_hires_scalef", "tissue_lowres_scalef", "spot_diameter_fullres")
    missing_scale_keys <- setdiff(required_scale_keys, names(scale_factors_data))
    if (length(missing_scale_keys)) stop("Scale factors JSON is missing: ", paste(missing_scale_keys, collapse = ", "), ".")

    cat("Matrix H5:", MATRIX_H5_PATH, "\n")
    cat("Tissue positions:", TISSUE_POSITIONS_PATH, "\n")
    cat("Scale factors:", SCALEFACTORS_PATH, "\n")
    cat("Tissue image:", TISSUE_IMAGE_PATH, "\n")
} else {
    if (!nzchar(PRE_QC_INPUT_RDS_PATH) || !file.exists(PRE_QC_INPUT_RDS_PATH) || isTRUE(file.info(PRE_QC_INPUT_RDS_PATH)$isdir)) {
        stop("RDS input mode requires an existing pre-QC unfiltered Seurat RDS.")
    }
    if (!grepl("\\.rds$", basename(PRE_QC_INPUT_RDS_PATH), ignore.case = TRUE)) stop("Pre-QC Seurat input must be an .rds file.")
    cat("Pre-QC unfiltered Seurat RDS:", PRE_QC_INPUT_RDS_PATH, "\n")
}
cat("Image scale:", TISSUE_IMAGE_SCALE, "\n\n")

if (identical(INPUT_SOURCE, "Space Ranger H5 + spatial files")) {
    if (dir.exists(SEURAT_INPUT_DIRECTORY)) unlink(SEURAT_INPUT_DIRECTORY, recursive = TRUE, force = TRUE)
    dir.create(SEURAT_SPATIAL_DIRECTORY, recursive = TRUE, showWarnings = FALSE)
    copy_required_file(MATRIX_H5_PATH, file.path(SEURAT_INPUT_DIRECTORY, "filtered_feature_bc_matrix.h5"))
    STANDARD_POSITIONS_FILE <- if (TISSUE_POSITIONS_HAS_HEADER) "tissue_positions.csv" else "tissue_positions_list.csv"
    copy_required_file(TISSUE_POSITIONS_PATH, file.path(SEURAT_SPATIAL_DIRECTORY, STANDARD_POSITIONS_FILE))
    copy_required_file(SCALEFACTORS_PATH, file.path(SEURAT_SPATIAL_DIRECTORY, "scalefactors_json.json"))
    TISSUE_IMAGE_NAME <- basename(TISSUE_IMAGE_PATH)
    copy_required_file(TISSUE_IMAGE_PATH, file.path(SEURAT_SPATIAL_DIRECTORY, TISSUE_IMAGE_NAME))

    spatial_image <- Read10X_Image(
        image.dir = SEURAT_SPATIAL_DIRECTORY,
        image.name = TISSUE_IMAGE_NAME,
        assay = "Spatial",
        slice = SAMPLE_ID,
        filter.matrix = TRUE
    )
    if (TISSUE_IMAGE_SCALE == "hires" && "scale.factors" %in% slotNames(spatial_image)) {
        spatial_image@scale.factors$lowres <- spatial_image@scale.factors$hires
    }
    spatial_object <- Load10X_Spatial(
        data.dir = SEURAT_INPUT_DIRECTORY,
        filename = "filtered_feature_bc_matrix.h5",
        assay = "Spatial",
        slice = SAMPLE_ID,
        filter.matrix = TRUE,
        image = spatial_image
    )
} else {
    spatial_object <- tryCatch(
        readRDS(PRE_QC_INPUT_RDS_PATH),
        error = function(error) stop("Could not read the selected pre-QC Seurat RDS:\n", conditionMessage(error))
    )
    if (!inherits(spatial_object, "Seurat")) stop("The selected pre-QC RDS does not contain a Seurat object.")
    if (!("Spatial" %in% SeuratObject::Assays(spatial_object))) stop("The selected pre-QC Seurat object has no Spatial assay.")
    spatial_layers <- SeuratObject::Layers(spatial_object, assay = "Spatial")
    if (!("counts" %in% spatial_layers)) stop("The Spatial assay in the selected pre-QC object has no counts layer.")
    if (!length(SeuratObject::Images(spatial_object))) stop("The selected pre-QC object contains no Visium tissue image/spot coordinates required for spatial QC maps.")
    SeuratObject::DefaultAssay(spatial_object) <- "Spatial"
}

spatial_object$sample_id <- SAMPLE_ID

spatial_counts <- SeuratObject::LayerData(spatial_object, assay = "Spatial", layer = "counts")
spatial_object$nCount_Spatial <- Matrix::colSums(spatial_counts)
spatial_object$nFeature_Spatial <- Matrix::colSums(spatial_counts > 0)

spatial_object[["percent.mt"]] <- PercentageFeatureSet(
    spatial_object,
    assay = "Spatial",
    pattern = MITOCHONDRIAL_PATTERN
)

spatial_object$Feature_Genes <- spatial_object$nFeature_Spatial
spatial_object$Count_RNAs <- spatial_object$nCount_Spatial
spatial_object$Mitochondrial_Percent <- spatial_object$percent.mt

PRE_QC_RDS_FILE <- visium_tagged_rds_path(RESULTS_WORKSPACE, "2_Spatial_QC", "S02", "preQC_unfilt")
QC_FILTERED_RDS_FILE <- visium_tagged_rds_path(RESULTS_WORKSPACE, "2_Spatial_QC", "S02", "QCfilt")

same_pre_qc_file <- nzchar(PRE_QC_INPUT_RDS_PATH) && identical(
    tolower(normalizePath(PRE_QC_INPUT_RDS_PATH, winslash = "/", mustWork = TRUE)),
    tolower(normalizePath(PRE_QC_RDS_FILE, winslash = "/", mustWork = FALSE))
)
if (!same_pre_qc_file) {
    saveRDS(spatial_object, PRE_QC_RDS_FILE, compress = FALSE)
} else {
    cat("Pre-QC input is already the standard Step 02 pre-QC RDS; it was not overwritten.\n")
}

metadata_before <- spatial_object[[]]
metadata_before$barcode <- rownames(metadata_before)

write.csv(
    metadata_before,
    file.path(OUTPUT_DIRECTORY, "spot_QC_metrics_before_filtering.csv"),
    row.names = FALSE
)

keep_spots <- rownames(metadata_before)[
    metadata_before$nFeature_Spatial >= MIN_FEATURES &
    metadata_before$nFeature_Spatial <= MAX_FEATURES &
    metadata_before$nCount_Spatial >= MIN_COUNTS &
    metadata_before$nCount_Spatial <= MAX_COUNTS &
    metadata_before$percent.mt <= MAX_PERCENT_MT
]

qc_failure_counts <- c(
    sum(metadata_before$nFeature_Spatial < MIN_FEATURES, na.rm = TRUE),
    sum(metadata_before$nFeature_Spatial > MAX_FEATURES, na.rm = TRUE),
    sum(metadata_before$nCount_Spatial < MIN_COUNTS, na.rm = TRUE),
    sum(metadata_before$nCount_Spatial > MAX_COUNTS, na.rm = TRUE),
    sum(metadata_before$percent.mt > MAX_PERCENT_MT, na.rm = TRUE),
    nrow(metadata_before) - length(keep_spots)
)
qc_filter_summary <- data.frame(
    criterion = c(
        "Feature_Genes (nFeature_Spatial) below minimum",
        "Feature_Genes (nFeature_Spatial) above maximum",
        "Count_RNAs (nCount_Spatial) below minimum",
        "Count_RNAs (nCount_Spatial) above maximum",
        "percent.mt above maximum",
        "failed one or more QC criteria"
    ),
    threshold = c(MIN_FEATURES, MAX_FEATURES, MIN_COUNTS, MAX_COUNTS, MAX_PERCENT_MT, NA_real_),
    spots_evaluated = nrow(metadata_before),
    spots_failing = qc_failure_counts,
    percent_failing = round(100 * qc_failure_counts / max(1L, nrow(metadata_before)), 3),
    note = c(rep("Independent criteria can overlap.", 5L), "Combined unique spots removed."),
    stringsAsFactors = FALSE
)
write.csv(qc_filter_summary, file.path(OUTPUT_DIRECTORY, "QC_filter_failure_summary.csv"), row.names = FALSE)

if (length(keep_spots) == 0L) {
    stop("No spots passed QC. Review spot_QC_metrics_before_filtering.csv.")
}

filtered <- subset(spatial_object, cells = keep_spots)

metadata_after <- filtered[[]]
metadata_after$barcode <- rownames(metadata_after)

write.csv(
    metadata_after,
    file.path(OUTPUT_DIRECTORY, "spot_QC_metrics_after_filtering.csv"),
    row.names = FALSE
)

saveRDS(
    filtered,
    QC_FILTERED_RDS_FILE,
    compress = FALSE
)

plot_metrics <- c("Feature_Genes", "Count_RNAs", "Mitochondrial_Percent")
metric_label_functions <- list(
    Feature_Genes = compact_number_labels,
    Count_RNAs = compact_number_labels,
    Mitochondrial_Percent = compact_percent_labels
)

violin_plots <- VlnPlot(
    filtered,
    features = plot_metrics,
    group.by = "sample_id",
    pt.size = 0,
    cols = QC_VIOLIN_COLOR,
    layer = "counts",
    combine = FALSE
)

for (plot_index in seq_along(violin_plots)) {
    metric_name <- plot_metrics[[plot_index]]
    violin_plots[[plot_index]] <- violin_plots[[plot_index]] +
        ggplot2::scale_y_continuous(labels = metric_label_functions[[metric_name]]) +
        ggplot2::labs(title = metric_name, x = NULL, y = metric_name) +
        ggplot2::theme(
            plot.title = ggplot2::element_text(hjust = 0.5, face = "bold"),
            axis.text.y = ggplot2::element_text(size = 9),
            axis.title.y = ggplot2::element_text(size = 10)
        )
}
violin_plot <- patchwork::wrap_plots(violin_plots, ncol = 3)

ggsave(
    file.path(OUTPUT_DIRECTORY, "spatial_QC_violin_plots.png"),
    violin_plot,
    width = 14,
    height = 6,
    dpi = 300
)

for (image_name in Images(filtered)) {
    spatial_plot_list <- SpatialFeaturePlot(
        filtered,
        features = plot_metrics,
        images = image_name,
        slot = "counts",
        image.scale = TISSUE_IMAGE_SCALE,
        ncol = 3,
        combine = FALSE
    )

    for (plot_index in seq_along(spatial_plot_list)) {
        metric_name <- plot_metrics[[plot_index]]
        spatial_plot_list[[plot_index]] <- suppressMessages(
            spatial_plot_list[[plot_index]] +
                ggplot2::scale_fill_gradient(
                    name = metric_name,
                    low = QC_LOW_COLOR,
                    high = QC_HIGH_COLOR,
                    labels = metric_label_functions[[metric_name]],
                    n.breaks = 4,
                    guide = ggplot2::guide_colorbar(
                        direction = "horizontal",
                        title.position = "top",
                        title.hjust = 0.5,
                        label.position = "bottom",
                        barwidth = grid::unit(4.5, "cm"),
                        barheight = grid::unit(0.35, "cm")
                    )
                ) +
                ggplot2::labs(title = metric_name) +
                ggplot2::theme(
                    plot.title = ggplot2::element_text(hjust = 0.5, face = "bold"),
                    legend.position = "top",
                    legend.direction = "horizontal",
                    legend.justification = "center",
                    legend.title = ggplot2::element_text(size = 9, face = "bold"),
                    legend.text = ggplot2::element_text(size = 8)
                )
        )
    }
    spatial_plot <- patchwork::wrap_plots(spatial_plot_list, ncol = 3)

    safe_image_name <- gsub("[^A-Za-z0-9_.-]", "_", image_name)

    ggsave(
        file.path(
            OUTPUT_DIRECTORY,
            paste0("spatial_QC_maps_", safe_image_name, ".png")
        ),
        spatial_plot,
        width = 15,
        height = 5,
        dpi = 300
    )
}

spot_counts <- data.frame(
    sample_id = SAMPLE_ID,
    spots_before_QC = nrow(metadata_before),
    spots_after_QC = nrow(metadata_after),
    stringsAsFactors = FALSE
)

spot_counts$spots_removed <-
    spot_counts$spots_before_QC -
    spot_counts$spots_after_QC

write.csv(
    spot_counts,
    file.path(OUTPUT_DIRECTORY, "Count_Spots_by_sample.csv"),
    row.names = FALSE
)

settings_used <- data.frame(
    setting = c(
        "SAMPLE_ID",
        "INPUT_SOURCE",
        "MATRIX_H5_FILE",
        "PRE_QC_INPUT_RDS_FILE",
        "TISSUE_POSITIONS_FILE",
        "TISSUE_POSITIONS_HAS_HEADER",
        "SCALEFACTORS_FILE",
        "TISSUE_IMAGE_FILE",
        "TISSUE_IMAGE_SCALE",
        "MIN_FEATURE_GENES_PER_SPOT",
        "MAX_FEATURE_GENES_PER_SPOT",
        "MIN_COUNT_RNAS_PER_SPOT",
        "MAX_COUNT_RNAS_PER_SPOT",
        "MAX_PERCENT_MT",
        "MITOCHONDRIAL_PATTERN"
    ),
    value = c(
        SAMPLE_ID,
        INPUT_SOURCE,
        MATRIX_H5_FILE,
        PRE_QC_INPUT_RDS_FILE,
        TISSUE_POSITIONS_FILE,
        TISSUE_POSITIONS_HAS_HEADER,
        SCALEFACTORS_FILE,
        TISSUE_IMAGE_FILE,
        TISSUE_IMAGE_SCALE,
        MIN_FEATURES,
        MAX_FEATURES,
        MIN_COUNTS,
        MAX_COUNTS,
        MAX_PERCENT_MT,
        MITOCHONDRIAL_PATTERN
    ),
    stringsAsFactors = FALSE
)

write.csv(
    settings_used,
    file.path(OUTPUT_DIRECTORY, "input_settings_used.csv"),
    row.names = FALSE
)

save_session_information()

cat(
    "\nSpatial spot QC completed successfully.\n",
    "Image scale used: ", TISSUE_IMAGE_SCALE, "\n",
    "Spots before QC: ", nrow(metadata_before), "\n",
    "Spots after QC: ", nrow(metadata_after), "\n",
    "Filtered RDS: ", QC_FILTERED_RDS_FILE, "\n",
    sep = ""
)

cat("\n*********** FINISHED ***********\n")

if (identical(.Platform$OS.type, "windows")) {
    speech_command <- paste(
        "Add-Type -AssemblyName System.Speech;",
        "$speaker = [System.Speech.Synthesis.SpeechSynthesizer]::new();",
        "$female = $speaker.GetInstalledVoices() |",
        "Where-Object { $_.VoiceInfo.Gender -eq 'Female' } | Select-Object -First 1;",
        "if ($female) { $speaker.SelectVoice($female.VoiceInfo.Name) };",
        "$speaker.Volume = 100; $speaker.Rate = 3;",
        "$speaker.Speak('Finished'); $speaker.Dispose()"
    )
    try(
        system2(
            "powershell.exe",
            c("-NoProfile", "-NonInteractive", "-Command", shQuote(speech_command)),
            stdout = FALSE,
            stderr = FALSE
        ),
        silent = TRUE
    )
} else {
    cat("\a")
}
