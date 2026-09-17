

options(stringsAsFactors = FALSE)
get_script_directory<-function(){a<-commandArgs(FALSE);f<-grep("^--file=",a,value=TRUE);if(length(f))return(dirname(normalizePath(sub("^--file=","",f[[1L]]),winslash="/",mustWork=FALSE)));if(requireNamespace("rstudioapi",quietly=TRUE)&&rstudioapi::isAvailable()){p<-tryCatch(rstudioapi::getActiveDocumentContext()$path,error=function(e)"");if(nzchar(p))return(dirname(normalizePath(p,winslash="/",mustWork=FALSE)))};normalizePath(getwd(),winslash="/",mustWork=FALSE)}
SCRIPT_DIRECTORY<-get_script_directory()
PIPELINE_DIRECTORY<-dirname(SCRIPT_DIRECTORY)

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
        "Script 3 - Normalization",
        "Rscript 3.Spatial_Normalization.R [--gui|--cli] [options]",
        c(
            "--gui  Open colored native desktop GUI.", "--cli  Run headlessly.",
            "--results-dir PATH  Required sample results folder, for example Results/Sample_01.",
            "--input-rds PATH  Required Step 2 QC-filtered Seurat RDS selected by the user.",
            "--normalization-method SCTransform|LogNormalize|RelativeCounts",
            "--normalization-scale-factor NUMBER", "--number-variable-features INT  Number of variable Feature_Genes.",
            "--variables-to-regress CSV (use none, or one/several metadata columns)",
            "--random-seed INT  Used only by SCTransform sampling.",
            "--variable-feature-base-color COLOR", "--variable-feature-highlight-color COLOR"
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
    tcltk::tkpack(tcltk::tklabel(hero, text = "Corrects sequencing-depth differences between spots before downstream analysis.", background = accent, foreground = "white", anchor = "w", padx = 22L, pady = 4L), fill = "x")

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

    editable_fields <- fields[!vapply(fields, function(f) f$type %in% c("info", "action", "dynamic_info"), logical(1))]
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
    collect_gui_values <- function() {
        values <- setNames(lapply(variables, tcltk::tclvalue), names(variables))
        for (field_name in names(multi_widgets)) {
            selection_text <- trimws(tcltk::tclvalue(tcltk::tcl(multi_widgets[[field_name]], "curselection")))
            indices <- if (nzchar(selection_text)) suppressWarnings(as.integer(strsplit(selection_text, "\\s+")[[1L]]) + 1L) else integer(0)
            choices <- multi_choices[[field_name]]
            selected <- choices[indices[is.finite(indices) & indices >= 1L & indices <= length(choices)]]
            values[[field_name]] <- if ("all" %in% selected) "all" else paste(selected, collapse = ",")
        }
        values
    }
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
            if (identical(f$type, "dynamic_info")) {
                dynamic_text <- tcltk::tclVar(if (is.null(f$text)) "Waiting for valid settings..." else f$text)
                dynamic_label <- tcltk::tklabel(
                    panel,
                    textvariable = dynamic_text,
                    background = "#E8F5E9",
                    foreground = "#1B5E20",
                    anchor = "w",
                    wraplength = if (panel_columns >= 3L) 330L else 500L,
                    justify = "left",
                    padx = 8L,
                    pady = 7L
                )
                tcltk::tkgrid(dynamic_label, row = field_row, column = 0L, columnspan = panel_field_columns, sticky = "ew", padx = 3L, pady = 3L)
                refresh_dynamic_info <- function(show_error = FALSE) {
                    refreshed <- tryCatch(f$command(collect_gui_values()), error = function(e) e)
                    if (inherits(refreshed, "error")) {
                        message <- paste0("Automatic memory estimate unavailable: ", conditionMessage(refreshed))
                        if (isTRUE(show_error)) {
                            tcltk::tkmessageBox(title = f$label, message = message, icon = "error", type = "ok", parent = window)
                        }
                    } else {
                        message <- as.character(refreshed)[1L]
                    }
                    tcltk::tclvalue(dynamic_text) <- message
                    invisible(!inherits(refreshed, "error"))
                }
                dependent_refreshers[[f$name]] <<- list(sources = f$sources, refresh = refresh_dynamic_info)
                refresh_dynamic_info(FALSE)
            } else if (identical(f$type, "info")) {
                info_text <- if (!is.null(f$text)) f$text else f$label
                tcltk::tkgrid(
                    tcltk::tklabel(panel, text = info_text, background = "#FFF8E1", foreground = "#5D4037", anchor = "w", wraplength = if (is_files_panel) 900L else if (panel_columns >= 3L) 330L else 500L, justify = "left", padx = 8L, pady = 5L),
                    row = field_row, column = 0L, columnspan = panel_field_columns, sticky = "ew", padx = 3L, pady = 3L
                )
            } else if (identical(f$type, "action")) {
                action_command <- function() {
                    if (identical(f$action, "run")) {
                        run()
                    } else if (is.function(f$command)) {
                        action_values <- setNames(lapply(variables, tcltk::tclvalue), names(variables))
                        for (field_name in names(multi_widgets)) {
                            selection_text <- trimws(tcltk::tclvalue(tcltk::tcl(multi_widgets[[field_name]], "curselection")))
                            indices <- if (nzchar(selection_text)) suppressWarnings(as.integer(strsplit(selection_text, "\\s+")[[1L]]) + 1L) else integer(0)
                            choices <- multi_choices[[field_name]]
                            selected <- choices[indices[is.finite(indices) & indices >= 1L & indices <= length(choices)]]
                            action_values[[field_name]] <- if ("all" %in% selected) "all" else paste(selected, collapse = ",")
                        }
                        f$command(action_values)
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
                        tcltk::tkcheckbutton(control, text = if (is.null(f$boolean_text)) "Enabled" else f$boolean_text, variable = variable, onvalue = "TRUE", offvalue = "FALSE", background = "white", activebackground = "white", selectcolor = "white", anchor = "w", command = function() refresh_dependents(f$name, FALSE)),
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
                    control <- tcltk::tkcheckbutton(panel, text = if (is.null(f$boolean_text)) "Enabled" else f$boolean_text, variable = variable, onvalue = "TRUE", offvalue = "FALSE", background = "white", activebackground = "white", selectcolor = "white", anchor = "w", command = function() refresh_dependents(f$name, FALSE))
                } else if (identical(f$type, "radio")) {
                    control <- tcltk::tkframe(panel, background = "white")
                    for (radio_choice in f$choices) {
                        tcltk::tkpack(
                            tcltk::tkradiobutton(control, text = radio_choice, variable = variable, value = radio_choice, background = "white", activebackground = "white", selectcolor = "white", padx = 5L, command = function() refresh_dependents(f$name, FALSE)),
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
                    tcltk::tkbind(listbox, "<<ListboxSelect>>", function() refresh_dependents(f$name, FALSE))

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
                        refresh_button <- tcltk::tkbutton(control, text = if (is.null(f$refresh_label)) "REFRESH CHOICES" else f$refresh_label, command = refresh_choices, background = "#455A64", foreground = "white", activebackground = "#263238", activeforeground = "white", relief = "raised", borderwidth = 1L, padx = 8L)
                        tcltk::tkgrid(refresh_button, row = 1L, column = 0L, columnspan = 2L, sticky = "ew", pady = c(4L, 0L))
                    }
                } else {
                    control <- tcltk::tkentry(panel, textvariable = variable, width = if (is_inline_field) 10L else if (is_files_panel && panel_span > 1L) 62L else if (is_files_panel) 28L else if (panel_columns >= 3L) 22L else 34L, relief = "solid", borderwidth = 1L, highlightthickness = 1L, highlightcolor = accent)
                    tcltk::tkbind(control, "<KeyRelease>", function() refresh_dependents(f$name, FALSE))
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

step3_inspect_input_rds <- local({
    cache <- new.env(parent = emptyenv())

    function(input_rds) {
        input_rds <- trimws(as.character(input_rds)[1L])
        if (!nzchar(input_rds) || !file.exists(input_rds)) {
            stop("Select the Step 2 QC-filtered Seurat RDS first.")
        }
        normalized_path <- normalizePath(input_rds, winslash = "/", mustWork = TRUE)
        file_details <- file.info(normalized_path)
        cache_key <- paste(
            normalized_path,
            file_details$size,
            as.numeric(file_details$mtime),
            sep = "|"
        )
        if (exists(cache_key, envir = cache, inherits = FALSE)) {
            return(get(cache_key, envir = cache, inherits = FALSE))
        }
        if (!requireNamespace("SeuratObject", quietly = TRUE)) {
            stop("The SeuratObject package is required to inspect the selected RDS.")
        }

        object <- readRDS(normalized_path)
        if (!inherits(object, "Seurat")) {
            stop("The selected RDS does not contain a Seurat object.")
        }
        metadata <- methods::slot(object, "meta.data")

        eligible <- names(metadata)[vapply(metadata, function(column) {
            non_missing <- column[!is.na(column)]
            unique_count <- length(unique(non_missing))
            if (unique_count < 2L) return(FALSE)
            if (is.numeric(column) || is.integer(column) || is.logical(column) || is.factor(column)) {
                return(TRUE)
            }
            is.character(column) && unique_count <= min(50L, max(2L, floor(nrow(metadata) / 5L)))
        }, logical(1))]

        preferred <- c(
            "percent.mt", "nCount_Spatial", "nFeature_Spatial",
            "Mitochondrial_Percent", "Count_RNAs", "Feature_Genes"
        )
        eligible <- c(intersect(preferred, eligible), sort(setdiff(eligible, preferred)))

        deduplicated <- character(0)
        for (metadata_name in eligible) {
            is_duplicate <- any(vapply(deduplicated, function(existing_name) {
                identical(metadata[[metadata_name]], metadata[[existing_name]])
            }, logical(1)))
            if (!is_duplicate) deduplicated <- c(deduplicated, metadata_name)
        }

        inspection <- list(
            path = normalized_path,
            features = nrow(object),
            spots = ncol(object),
            object_bytes = as.numeric(utils::object.size(object)),
            metadata_choices = deduplicated
        )
        assign(cache_key, inspection, envir = cache)
        inspection
    }
})

step3_metadata_regression_choices <- function(input_rds) {
    choices <- step3_inspect_input_rds(input_rds)$metadata_choices
    c("None (no regression)", choices)
}

step3_estimate_sct_memory <- function(
    features,
    spots,
    object_bytes,
    variable_features,
    sampled_spots,
    bin_size,
    conserve_memory,
    return_only_variable_genes
) {
    features <- max(1, as.numeric(features))
    spots <- max(1, as.numeric(spots))
    variable_features <- min(features, max(1, as.numeric(variable_features)))
    sampled_spots <- min(spots, max(1, as.numeric(sampled_spots)))
    bin_size <- min(features, max(1, as.numeric(bin_size)))
    conserve_memory <- isTRUE(conserve_memory)
    return_only_variable_genes <- isTRUE(return_only_variable_genes)

    gib <- 1024^3
    object_gib <- as.numeric(object_bytes) / gib
    sampled_model_gib <- features * sampled_spots * 8 / gib
    batch_work_gib <- bin_size * spots * 8 / gib
    output_features <- if (return_only_variable_genes) variable_features else features
    output_matrix_gib <- output_features * spots * 8 / gib

    model_multiplier <- if (conserve_memory) 3 else 5
    output_multiplier <- if (conserve_memory) 1.5 else 2.5
    estimated_peak_gib <- 1.25 * (
        object_gib +
        0.5 +
        model_multiplier * sampled_model_gib +
        3 * batch_work_gib +
        output_multiplier * output_matrix_gib
    )
    recommended_ram_gib <- max(4, ceiling(estimated_peak_gib * 1.25))

    list(
        estimated_peak_gib = estimated_peak_gib,
        recommended_ram_gib = recommended_ram_gib,
        object_gib = object_gib,
        sampled_spots = sampled_spots,
        output_features = output_features,
        features = features,
        spots = spots
    )
}

step3_sct_memory_report <- function(values) {
    if (!identical(values$normalization_method, "SCTransform")) {
        return("Automatic peak-memory estimation applies only to SCTransform.")
    }
    inspection <- step3_inspect_input_rds(values$input_rds)
    estimate <- step3_estimate_sct_memory(
        features = inspection$features,
        spots = inspection$spots,
        object_bytes = inspection$object_bytes,
        variable_features = visium_integer(values$number_variable_features, "Number of variable Feature_Genes"),
        sampled_spots = visium_integer(values$sct_ncells, "Spots sampled to fit SCT model"),
        bin_size = visium_integer(values$sct_bin_size, "Genes processed per SCT batch"),
        conserve_memory = visium_bool(values$sct_conserve_memory, "Conserve memory"),
        return_only_variable_genes = visium_bool(values$sct_return_only_variable_genes, "Store only variable genes")
    )

    paste0(
        "Approximate peak R memory: ", sprintf("%.2f", estimate$estimated_peak_gib), " GiB\n",
        "Recommended available RAM: at least ", estimate$recommended_ram_gib, " GiB\n\n",
        "Selected object: ", format(estimate$features, big.mark = ","), " genes x ",
        format(estimate$spots, big.mark = ","), " spots\n",
        "SCT model-fitting spots: ", format(estimate$sampled_spots, big.mark = ","), "\n",
        "SCT output Feature_Genes estimated: ", format(estimate$output_features, big.mark = ","), "\n",
        "Current Seurat object in memory: ", sprintf("%.2f", estimate$object_gib), " GiB\n\n",
        "This is a conservative planning estimate, not an exact guarantee. R, Seurat, ",
        "plotting, operating-system use, and other programs can increase actual RAM use. ",
        "future.globals.maxSize is a transfer ceiling and is not a physical RAM limit."
    )
}

defaults<-list(results_dir="",normalization_method="SCTransform",normalization_scale_factor=10000,number_variable_features=3000L,variables_to_regress="None (no regression)",random_seed=12345L,future_globals_max_size_gb=4,sct_ncells=2000L,sct_bin_size=500L,sct_conserve_memory=FALSE,sct_return_only_variable_genes=TRUE,variable_feature_base_color="#4D4D4D",variable_feature_highlight_color="#E63946")
run_gui<-interactive()||!length(commandArgs(TRUE))||isTRUE(cli$gui);if(isTRUE(cli$cli))run_gui<-FALSE
if(run_gui){gui<-visium_desktop_gui("Script 3 - Spatial Normalization",list(
list(name="results_dir",label="Sample results folder (for example Results/Sample_01)",value=defaults$results_dir,type="directory",group="Files",required=TRUE,must_exist=TRUE),
list(name="input_rds",label="Step 2 QC-filtered Seurat RDS",value="",type="file",group="Files",required=TRUE,must_exist=TRUE,browse_initial_dir=function(values) file.path(values$results_dir,"Seurat_RDS"),path_pattern="_S02_QCfilt\\.rds$",path_message="the tagged *_S02_QCfilt.rds produced after Step 2 QC filtering"),
list(name="input_rds_guide",type="info",group="Files",text="After selecting the sample results folder, Browse opens its Seurat_RDS folder. Select the exact post-QC *_S02_QCfilt.rds to normalize. The selected filename tags are preserved in the Step 3 output name."),
list(name="normalization_method",label="Normalization method (select one)",value=defaults$normalization_method,type="radio",choices=c("SCTransform","LogNormalize","RelativeCounts"),group="Normalization"),list(name="normalization_scale_factor",label="Per-spot Count_RNAs scale factor (LogNormalize/RelativeCounts)",value=defaults$normalization_scale_factor,type="number",group="Normalization"),list(name="number_variable_features",label="Number of variable Feature_Genes",value=defaults$number_variable_features,type="integer",group="Normalization"),list(name="variables_to_regress",label="Metadata variables to regress (select None, one, or several)",value=defaults$variables_to_regress,type="multichoice",choices=c("None (no regression)"),choice_source="input_rds",choice_loader=step3_metadata_regression_choices,refresh_label="REFRESH METADATA LIST",group="Normalization"),
list(name="method_help_sct",type="info",group="Normalization guidance",text="SCTransform fits a regularized negative-binomial model to stabilize variance across sequencing depth. It creates an SCT assay and is a variance-stabilizing transformation implemented through sctransform::vst, but it is not the same algorithm as the bulk RNA-seq VST in DESeq2."),
list(name="method_help_log",type="info",group="Normalization guidance",text="LogNormalize divides each spot by that spot's total Count_RNAs/UMIs, multiplies by the selected scale factor (default 10,000), and applies log1p."),
list(name="method_help_rc",type="info",group="Normalization guidance",text="RelativeCounts performs the same per-spot Count_RNAs scaling without log transformation (Seurat normalization.method='RC'). A full-image divisor is not offered because one common divisor would not correct sequencing-depth differences between spots."),
list(name="method_help_common",type="info",group="Normalization guidance",text="The script finds variable Feature_Genes and scales the Spatial assay after LogNormalize or RelativeCounts. The 'vst' name used by FindVariableFeatures is a gene-feature selection method, not an additional normalization. Select None for no regression, or select one/several varying metadata columns with Ctrl/Shift; avoid regressing biological variables of interest."),
list(name="future_globals_max_size_gb",label="future.globals.maxSize ceiling (GB; not a RAM limit)",value=defaults$future_globals_max_size_gb,type="number",group="SCTransform"),list(name="sct_ncells",label="Spots sampled to fit SCT model",value=defaults$sct_ncells,type="integer",group="SCTransform"),list(name="sct_bin_size",label="Feature_Genes processed per SCT batch",value=defaults$sct_bin_size,type="integer",group="SCTransform"),list(name="sct_conserve_memory",label="Conserve memory",value=defaults$sct_conserve_memory,type="boolean",group="SCTransform"),list(name="sct_return_only_variable_genes",label="Store only variable Feature_Genes in SCT assay",value=defaults$sct_return_only_variable_genes,type="boolean",group="SCTransform"),list(name="random_seed",label="SCTransform random seed (spot sampling)",value=defaults$random_seed,type="integer",group="SCTransform"),
list(name="sct_memory_report",label="Automatic SCTransform peak-memory estimate",type="dynamic_info",group="SCTransform",text="Select the Step 2 RDS to calculate the estimate automatically.",sources=c("input_rds","normalization_method","number_variable_features","sct_ncells","sct_bin_size","sct_conserve_memory","sct_return_only_variable_genes"),command=step3_sct_memory_report),
list(name="sct_help_memory",type="info",group="SCTransform details",text="The approximate peak-memory report refreshes automatically after the selected RDS or any relevant SCTransform parameter changes. It uses the actual object size, Feature_Genes, spots, sampled spots, bin size, conserve-memory choice, and retained output Feature_Genes. future.globals.maxSize is only a transfer ceiling."),
list(name="sct_help_ncells",type="info",group="SCTransform details",text="Spots sampled: number of spots used to estimate the SCTransform model, capped at the number of spots in the object. Larger values may improve model stability but require more time and memory."),
list(name="sct_help_bin",type="info",group="SCTransform details",text="Genes per SCT batch (bin_size): controls how many genes are processed together. Smaller batches can reduce peak memory use but may run more slowly."),
list(name="sct_help_conserve",type="info",group="SCTransform details",text="Conserve memory: reduces storage of large intermediate matrices. Enable it for limited-memory computers; runtime may increase."),
list(name="sct_help_variable",type="info",group="SCTransform details",text="Store only variable Feature_Genes: TRUE keeps only selected variable genes in the SCT scale.data output and saves memory. FALSE retains broader gene coverage and uses more memory. The random seed is useful only for reproducible SCTransform spot sampling; LogNormalize and RelativeCounts do not use it.")
),accent="#6A4C93");cli<-modifyList(cli,gui)}
RESULTS_WORKSPACE<-visium_validate_results_workspace(visium_option(cli,"results-dir",defaults$results_dir,"path"));INPUT_DIRECTORY<-visium_stage_directory(RESULTS_WORKSPACE,"2_Spatial_QC",create=FALSE);OUTPUT_DIRECTORY<-visium_stage_directory(RESULTS_WORKSPACE,"3_Normalization",create=TRUE);INPUT_RDS_OPTION<-visium_option(cli,"input-rds","","path")
if(!nzchar(INPUT_RDS_OPTION)||!file.exists(INPUT_RDS_OPTION))stop("Select the Step 2 QC-filtered Seurat RDS explicitly with --input-rds.")
NORMALIZATION_METHOD<-visium_option(cli,"normalization-method","SCTransform","choice",c("SCTransform","LogNormalize","RelativeCounts"));NORMALIZATION_SCALE_FACTOR<-visium_option(cli,"normalization-scale-factor",10000,"number");NUMBER_VARIABLE_FEATURES<-visium_option(cli,"number-variable-features",3000,"integer");VARIABLES_TO_REGRESS<-visium_option(cli,"variables-to-regress","none","csv");VARIABLES_TO_REGRESS<-trimws(as.character(VARIABLES_TO_REGRESS));VARIABLES_TO_REGRESS<-VARIABLES_TO_REGRESS[nzchar(VARIABLES_TO_REGRESS)];if(any(tolower(VARIABLES_TO_REGRESS)%in%c("none","none (no regression)")))VARIABLES_TO_REGRESS<-character(0);RANDOM_SEED<-visium_option(cli,"random-seed",12345,"integer");FUTURE_GLOBALS_MAX_SIZE_GB<-visium_option(cli,"future-globals-max-size-gb",4,"number");SCT_NCELLS<-visium_option(cli,"sct-ncells",2000,"integer");SCT_BIN_SIZE<-visium_option(cli,"sct-bin-size",500,"integer");SCT_CONSERVE_MEMORY<-visium_option(cli,"sct-conserve-memory",FALSE,"boolean");SCT_RETURN_ONLY_VARIABLE_GENES<-visium_option(cli,"sct-return-only-variable-genes",TRUE,"boolean")
VARIABLE_FEATURE_BASE_COLOR<-visium_option(cli,"variable-feature-base-color","#4D4D4D");VARIABLE_FEATURE_HIGHLIGHT_COLOR<-visium_option(cli,"variable-feature-highlight-color","#E63946");visium_colors(c(VARIABLE_FEATURE_BASE_COLOR,VARIABLE_FEATURE_HIGHLIGHT_COLOR),"Feature_Genes colors",2L)
if (NUMBER_VARIABLE_FEATURES < 1L) stop("Number of variable Feature_Genes must be at least 1.")
if (NORMALIZATION_SCALE_FACTOR <= 0) stop("The per-spot normalization scale factor must be greater than 0.")
if (FUTURE_GLOBALS_MAX_SIZE_GB <= 0) stop("Memory-transfer ceiling must be greater than 0 GB.")
if (SCT_NCELLS < 1L) stop("SCTransform sampled spots must be at least 1.")
if (SCT_BIN_SIZE < 1L) stop("SCTransform bin size must be at least 1.")

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

cat("Input directory:", INPUT_DIRECTORY, "\n")
cat("Output directory:", OUTPUT_DIRECTORY, "\n")
cat("Started:", format(Sys.time()), "\n\n")

required_packages <- c("Seurat", "SeuratObject", "sctransform", "ggplot2", "future")
missing_packages <- required_packages[
    !vapply(required_packages, requireNamespace, logical(1), quietly = TRUE)
]

if (length(missing_packages)) {
    stop(
        "Missing required package(s): ",
        paste(missing_packages, collapse = ", "),
        "\nRun 00_Install_R_Packages.R first."
    )
}

suppressPackageStartupMessages({
    library(Seurat)
    library(SeuratObject)
    library(sctransform)
    library(ggplot2)
})

options(
    future.globals.maxSize = FUTURE_GLOBALS_MAX_SIZE_GB * 1024^3
)

future::plan(future::sequential)

cat("Execution mode: sequential, one R process\n")
cat("future.globals.maxSize:", FUTURE_GLOBALS_MAX_SIZE_GB, "GiB\n\n")

rds_files <- INPUT_RDS_OPTION

if (length(rds_files) != 1L) {
    stop(
        "Expected exactly one tagged Step 2 QC-filtered RDS.\n",
        "Number of matching post-QC RDS files found: ",
        length(rds_files)
    )
}

INPUT_RDS_FILE <- normalizePath(rds_files[1L], winslash = "/", mustWork = TRUE)
input_rds_basename <- basename(INPUT_RDS_FILE)

if (grepl("(^|[._ -])(before|pre)[._ -]*QC([._ -]|$)", input_rds_basename, ignore.case = TRUE)) {
    stop(
        "The selected file appears to be the pre-QC object: ", input_rds_basename, "\n",
        "Select the tagged *_S02_QCfilt.rds created by Step 2 after QC filtering."
    )
}

if (!grepl("_S02_QCfilt\\.rds$", input_rds_basename, ignore.case = TRUE)) {
    warning(
        "Advanced input override does not have the expected *_S02_QCfilt.rds tag. Confirm that it is the post-QC ",
        "filtered Seurat object from Step 2."
    )
}

object <- readRDS(INPUT_RDS_FILE)

if (!inherits(object, "Seurat")) {
    stop("The input RDS file does not contain a Seurat object.")
}

if (!"Spatial" %in% Assays(object)) {
    stop('The input Seurat object does not contain an assay named "Spatial".')
}

DefaultAssay(object) <- "Spatial"

found_regressors <- VARIABLES_TO_REGRESS[
    VARIABLES_TO_REGRESS %in% colnames(object[[]])
]

missing_regressors <- setdiff(VARIABLES_TO_REGRESS, found_regressors)

if (length(missing_regressors)) {
    warning(
        "Regression variable(s) not found and omitted: ",
        paste(missing_regressors, collapse = ", ")
    )
}

constant_regressors <- found_regressors[vapply(found_regressors, function(metadata_name) {
    metadata_values <- object[[metadata_name, drop = TRUE]]
    length(unique(metadata_values[!is.na(metadata_values)])) < 2L
}, logical(1))]

if (length(constant_regressors)) {
    warning(
        "Regression variable(s) are constant across the selected spots and were omitted: ",
        paste(constant_regressors, collapse = ", ")
    )
}

valid_regressors <- setdiff(found_regressors, constant_regressors)

sct_memory_estimate <- NULL
if (identical(NORMALIZATION_METHOD, "SCTransform")) {
    sct_memory_estimate <- step3_estimate_sct_memory(
        features = nrow(object),
        spots = ncol(object),
        object_bytes = as.numeric(utils::object.size(object)),
        variable_features = NUMBER_VARIABLE_FEATURES,
        sampled_spots = SCT_NCELLS,
        bin_size = SCT_BIN_SIZE,
        conserve_memory = SCT_CONSERVE_MEMORY,
        return_only_variable_genes = SCT_RETURN_ONLY_VARIABLE_GENES
    )
}

cat("Input RDS:", INPUT_RDS_FILE, "\n")
cat("Normalization method:", NORMALIZATION_METHOD, "\n")
if (NORMALIZATION_METHOD %in% c("LogNormalize", "RelativeCounts")) {
    cat("Per-spot scale factor:", NORMALIZATION_SCALE_FACTOR, "\n")
}
cat(
    "Regression variables used:",
    if (length(valid_regressors)) paste(valid_regressors, collapse = ", ") else "<none>",
    "\n\n"
)
if (!is.null(sct_memory_estimate)) {
    cat(
        "Approximate SCTransform peak R memory:",
        sprintf("%.2f GiB", sct_memory_estimate$estimated_peak_gib),
        "\nRecommended available RAM: at least",
        sct_memory_estimate$recommended_ram_gib,
        "GiB\n\n"
    )
}

normalization_start <- Sys.time()

if (identical(NORMALIZATION_METHOD, "SCTransform")) {
    object <- SCTransform(
        object = object,
        assay = "Spatial",
        new.assay.name = "SCT",
        ncells = min(SCT_NCELLS, ncol(object)),
        variable.features.n = NUMBER_VARIABLE_FEATURES,
        vars.to.regress = if (length(valid_regressors)) valid_regressors else NULL,
        vst.flavor = "v2",
        bin_size = SCT_BIN_SIZE,
        conserve.memory = SCT_CONSERVE_MEMORY,
        return.only.var.genes = SCT_RETURN_ONLY_VARIABLE_GENES,
        seed.use = RANDOM_SEED,
        verbose = TRUE
    )

    DefaultAssay(object) <- "SCT"
    output_operation_tag <- "QCfilt_NormSCT"

} else if (NORMALIZATION_METHOD %in% c("LogNormalize", "RelativeCounts")) {
    seurat_normalization_method <- if (identical(NORMALIZATION_METHOD, "LogNormalize")) {
        "LogNormalize"
    } else {
        "RC"
    }

    object <- NormalizeData(
        object,
        assay = "Spatial",
        normalization.method = seurat_normalization_method,
        scale.factor = NORMALIZATION_SCALE_FACTOR,
        verbose = TRUE
    )

    object <- FindVariableFeatures(
        object,
        assay = "Spatial",
        selection.method = "vst",
        nfeatures = NUMBER_VARIABLE_FEATURES,
        verbose = TRUE
    )

    object <- ScaleData(
        object,
        assay = "Spatial",
        vars.to.regress = if (length(valid_regressors)) valid_regressors else NULL,
        verbose = TRUE
    )

    DefaultAssay(object) <- "Spatial"
    output_operation_tag <- if (identical(NORMALIZATION_METHOD, "LogNormalize")) {
        "QCfilt_NormLog"
    } else {
        "QCfilt_NormRC"
    }

} else {
    stop('NORMALIZATION_METHOD must be "SCTransform", "LogNormalize", or "RelativeCounts".')
}

normalization_minutes <- as.numeric(
    difftime(Sys.time(), normalization_start, units = "mins")
)

OUTPUT_RDS_FILE <- visium_tagged_rds_path(RESULTS_WORKSPACE, "3_Normalization", "S03", output_operation_tag)

saveRDS(object, OUTPUT_RDS_FILE, compress = FALSE)

write.csv(
    data.frame(gene = VariableFeatures(object)),
    file.path(OUTPUT_DIRECTORY, "normalization_variable_Feature_Genes.csv"),
    row.names = FALSE
)

ggsave(
    filename = file.path(OUTPUT_DIRECTORY, "normalization_variable_Feature_Genes.png"),
    plot = VariableFeaturePlot(object,cols=c(VARIABLE_FEATURE_BASE_COLOR,VARIABLE_FEATURE_HIGHLIGHT_COLOR)) +
        ggplot2::labs(title = "Variable Feature_Genes after normalization"),
    width = 9,
    height = 7,
    dpi = 300
)

if (!is.null(sct_memory_estimate)) {
    write.csv(
        data.frame(
            metric = c(
                "estimated_peak_R_memory_GiB",
                "recommended_available_RAM_GiB",
                "input_Seurat_object_GiB",
                "input_Feature_Genes",
                "input_spots",
                "SCT_model_fitting_spots",
                "SCT_output_Feature_Genes"
            ),
            value = c(
                sct_memory_estimate$estimated_peak_gib,
                sct_memory_estimate$recommended_ram_gib,
                sct_memory_estimate$object_gib,
                sct_memory_estimate$features,
                sct_memory_estimate$spots,
                sct_memory_estimate$sampled_spots,
                sct_memory_estimate$output_features
            ),
            stringsAsFactors = FALSE
        ),
        file.path(OUTPUT_DIRECTORY, "SCTransform_memory_estimate.csv"),
        row.names = FALSE
    )
}

write.csv(
    data.frame(
        setting = c(
            "NORMALIZATION_METHOD",
            "NORMALIZATION_SCALE_FACTOR",
            "NUMBER_VARIABLE_FEATURE_GENES",
            "VARIABLES_TO_REGRESS_REQUESTED",
            "VARIABLES_TO_REGRESS_USED",
            "RANDOM_SEED_SCT_ONLY",
            "FUTURE_GLOBALS_MAX_SIZE_GB",
            "SCT_NCELLS",
            "SCT_BIN_SIZE",
            "SCT_CONSERVE_MEMORY",
            "SCT_RETURN_ONLY_VARIABLE_GENES",
            "SCT_ESTIMATED_PEAK_MEMORY_GIB",
            "SCT_RECOMMENDED_AVAILABLE_RAM_GIB",
            "EXECUTION_MODE",
            "NORMALIZATION_MINUTES"
        ),
        value = c(
            NORMALIZATION_METHOD,
            if (NORMALIZATION_METHOD %in% c("LogNormalize", "RelativeCounts")) NORMALIZATION_SCALE_FACTOR else NA,
            NUMBER_VARIABLE_FEATURES,
            paste(VARIABLES_TO_REGRESS, collapse = ","),
            paste(valid_regressors, collapse = ","),
            if (identical(NORMALIZATION_METHOD, "SCTransform")) RANDOM_SEED else NA,
            FUTURE_GLOBALS_MAX_SIZE_GB,
            SCT_NCELLS,
            SCT_BIN_SIZE,
            SCT_CONSERVE_MEMORY,
            SCT_RETURN_ONLY_VARIABLE_GENES,
            if (is.null(sct_memory_estimate)) NA else sct_memory_estimate$estimated_peak_gib,
            if (is.null(sct_memory_estimate)) NA else sct_memory_estimate$recommended_ram_gib,
            "sequential",
            normalization_minutes
        ),
        stringsAsFactors = FALSE
    ),
    file.path(OUTPUT_DIRECTORY, "normalization_settings_used.csv"),
    row.names = FALSE
)

capture.output(
    sessionInfo(),
    file = file.path(OUTPUT_DIRECTORY, "sessionInfo.txt")
)

cat(
    "\nSpatial normalization completed successfully.\n",
    "Execution mode: sequential\n",
    "Normalization minutes: ", normalization_minutes, "\n",
    "Output object: ", OUTPUT_RDS_FILE, "\n",
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
