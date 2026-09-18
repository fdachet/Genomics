

options(stringsAsFactors = FALSE)
get_script_directory<-function(){a<-commandArgs(FALSE);f<-grep("^--file=",a,value=TRUE);if(length(f))return(dirname(normalizePath(sub("^--file=","",f[[1L]]),winslash="/",mustWork=FALSE)));if(requireNamespace("rstudioapi",quietly=TRUE)&&rstudioapi::isAvailable()){p<-tryCatch(rstudioapi::getActiveDocumentContext()$path,error=function(e)"");if(nzchar(p))return(dirname(normalizePath(p,winslash="/",mustWork=FALSE)))};normalizePath(getwd(),winslash="/",mustWork=FALSE)}
PIPELINE_SCRIPT_DIRECTORY<-get_script_directory()
PIPELINE_DIRECTORY<-dirname(PIPELINE_SCRIPT_DIRECTORY)

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
        "Script 5 - Spatially Variable Genes and Pathways",
        "Rscript \"5.Spatially_VariableGenes&Pathways.R\" [--gui|--cli] [options]",
        c(
            "--gui  Open colored native desktop GUI.", "--cli  Run headlessly.",
            "--results-dir PATH  Required sample results folder, for example Results/Sample_01.",
            "--input-rds PATH  Required Step 4 clustered Seurat RDS selected by the user.",
            "--selection-method CSV  One or both: moransi,markvariogram.", "--future-workers INT",
            "--plot-top-spatially-variable-features BOOL  Plot top spatial Feature_Genes.", "--plot-user-defined-features BOOL  Plot user-selected Feature_Genes.",
            "--user-defined-plot-file PATH  Required when custom gene/pathway plotting is enabled.",
            "--user-defined-plot-assay ASSAY  Assay name from the input Seurat object.", "--user-defined-plot-layer LAYER  data|scale.data|counts.",
            "--user-defined-combination-method CSV  One or more: sum,mean,mean_by_sign.", "--user-defined-gene-normalization CSV  One or more: robust_minmax,minmax,none.",
            "--user-defined-pathway-palette CSV", "--spatial-gene-low-color COLOR",
            "--spatial-gene-high-color COLOR"
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
    tcltk::tkpack(tcltk::tklabel(hero, text = "Finds genes and linear model pathways with expression patterns that vary across tissue.", background = accent, foreground = "white", anchor = "w", padx = 22L, pady = 4L), fill = "x")

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
                info_label <- tcltk::tklabel(panel, text = info_text, background = "#FFF8E1", foreground = "#5D4037", anchor = "w", wraplength = if (is_files_panel) 900L else if (panel_columns >= 3L) 330L else 500L, justify = "left", padx = 8L, pady = 5L)
                tcltk::tkgrid(info_label, row = field_row, column = 0L, columnspan = panel_field_columns, sticky = "ew", padx = 3L, pady = 3L)
                if (is.function(f$compute)) {
                    refresh_dynamic_info <- function(show_error = FALSE) {
                        gui_values <- setNames(lapply(variables, function(item) tcltk::tclvalue(item)), names(variables))
                        computed <- tryCatch(as.character(f$compute(gui_values)[1L]), error = function(e) paste(info_text, "\nUnable to calculate estimate:", conditionMessage(e)))
                        tcltk::tkconfigure(info_label, text = computed)
                        invisible(TRUE)
                    }
                    dependent_sources <- if (!is.null(f$sources)) as.character(f$sources) else character(0)
                    if (length(dependent_sources)) {
                        dependent_refreshers[[paste0("info_", f$name)]] <<- list(sources = dependent_sources, refresh = refresh_dynamic_info)
                    }
                    refresh_dynamic_info(FALSE)
                }
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
                                    do.call(f$choice_loader, unname(source_values))
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
                                    do.call(f$choice_loader, unname(source_values))
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
                if (f$type %in% c("integer", "number", "text")) {
                    tcltk::tkbind(control, "<KeyRelease>", function() refresh_dependents(f$name, FALSE))
                }

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

visium_gui_assay_choices <- function(input_rds) {
    if (!nzchar(trimws(input_rds)) || !file.exists(input_rds)) return(c("AUTO"))
    obj <- readRDS(input_rds)
    c("AUTO", as.character(SeuratObject::Assays(obj)))
}

visium_gui_layer_choices <- function(input_rds, assay_choice) {
    if (!nzchar(trimws(input_rds)) || !file.exists(input_rds)) return(c("data", "scale.data", "counts"))
    obj <- readRDS(input_rds)
    assay <- if (toupper(assay_choice) == "AUTO") {
        if ("SCT" %in% SeuratObject::Assays(obj)) "SCT" else if ("Spatial" %in% SeuratObject::Assays(obj)) "Spatial" else SeuratObject::Assays(obj)[[1L]]
    } else assay_choice
    if (!(assay %in% SeuratObject::Assays(obj))) return(character(0))
    available <- tryCatch(SeuratObject::Layers(obj[[assay]]), error = function(e) character(0))
    intersect(c("data", "scale.data", "counts"), available)
}

visium_estimate_peak_memory <- function(object_gb, workers, features, score_combinations) {
    object_gb <- max(0, as.numeric(object_gb))
    workers <- max(1L, as.integer(workers))
    features <- max(1L, as.integer(features))
    score_combinations <- max(1L, as.integer(score_combinations))

    master_object_gb <- object_gb
    worker_object_copies_gb <- object_gb * workers * 2.25
    worker_runtime_gb <- workers * 0.25
    analysis_buffers_gb <- max(0.50, object_gb * (0.40 + features / 5000))
    score_combination_overhead_gb <- score_combinations * 0.15
    before_safety_gb <- master_object_gb + worker_object_copies_gb + worker_runtime_gb + analysis_buffers_gb + score_combination_overhead_gb
    list(
        master_object_gb = master_object_gb,
        worker_object_copies_gb = worker_object_copies_gb,
        worker_runtime_gb = worker_runtime_gb,
        analysis_buffers_gb = analysis_buffers_gb,
        score_combination_overhead_gb = score_combination_overhead_gb,
        estimate_gb = before_safety_gb * 1.15
    )
}

visium_memory_estimate_text <- function(values) {
    value_or <- function(name, fallback) if (!is.null(values[[name]])) values[[name]] else fallback
    input_rds <- as.character(value_or("input_rds", ""))
    file_gb <- if (nzchar(input_rds) && file.exists(input_rds)) as.numeric(file.info(input_rds)$size) / 1024^3 else NA_real_
    workers <- suppressWarnings(as.numeric(value_or("future_workers", FUTURE_WORKERS)))
    features <- suppressWarnings(as.numeric(value_or("number_features_to_test", NUMBER_FEATURES_TO_TEST)))
    combinations <- length(visium_csv(value_or("user_defined_combination_method", "sum")))
    normalizations <- length(visium_csv(value_or("user_defined_gene_normalization", "robust_minmax")))
    if (!is.finite(workers) || workers < 1) workers <- FUTURE_WORKERS
    if (!is.finite(features) || features < 1) features <- NUMBER_FEATURES_TO_TEST
    score_combinations <- max(1L, combinations * normalizations)
    estimate_details <- if (is.finite(file_gb) && file_gb > 0) visium_estimate_peak_memory(file_gb, workers, features, score_combinations) else NULL
    ceiling <- suppressWarnings(as.numeric(value_or("future_globals_max_size_gb", FUTURE_GLOBALS_MAX_SIZE_GB)))
    ceiling_text <- if (is.finite(ceiling)) sprintf("; configured future ceiling %.1f GB", ceiling) else ""
    if (!is.null(estimate_details)) {
        sprintf("High-water RAM planning estimate: %.1f GB (master %.1f + per-worker copies/native allocations %.1f + worker runtime %.1f + temporary buffers %.1f + score combinations %.1f GB, including safety margin)%s. This is a planning estimate, not a guarantee: multisession workers do not share RAM and native allocations are not fully visible to object.size(). Reduce Parallel workers to lower this estimate. future.globals.maxSize is not a total-RAM ceiling.", estimate_details$estimate_gb, estimate_details$master_object_gb, estimate_details$worker_object_copies_gb, estimate_details$worker_runtime_gb, estimate_details$analysis_buffers_gb, estimate_details$score_combination_overhead_gb, ceiling_text)
    } else {
        "A high-water RAM planning estimate will be calculated after you select the input RDS. It accounts for independent multisession worker copies, native matrix allocations, worker runtime overhead, Feature_Genes tested, and score combinations."
    }
}

SELECTION_METHOD <- "moransi"
NUMBER_FEATURES_TO_TEST <- 1000L
NUMBER_TOP_FEATURES_TO_PLOT <- 20L
MULTIPLE_IMAGE_FILE <- TRUE
NUMBER_SPATIALLY_VARIABLE_FEATURES <- 1000L
X_CUTS <- 100L
Y_CUTS <- 100L

FUTURE_WORKERS <- 10L
FUTURE_GLOBALS_MAX_SIZE_GB <- 8
RANDOM_SEED <- 12345L

DOMAIN_MARKER_MIN_PCT <- 0.10
DOMAIN_MARKER_LOGFC_THRESHOLD <- 0.25
DOMAIN_MARKER_ADJUSTED_PVALUE_THRESHOLD <- 0.01
MORAN_FDR_THRESHOLD <- 0.05

PLOT_TOP_SPATIALLY_VARIABLE_FEATURES <- FALSE

PLOT_USER_DEFINED_FEATURES <- TRUE
USER_DEFINED_PLOT_FILE <- "Spatial_Plot_Definitions.tabtxt"
USER_DEFINED_PLOT_ASSAY <- "AUTO"
USER_DEFINED_PLOT_LAYER <- "data"
USER_DEFINED_COMBINATION_METHODS <- "sum"

USER_DEFINED_GENE_NORMALIZATIONS <- "robust_minmax"
USER_DEFINED_NORMALIZATION_LOWER_QUANTILE <- 0.01
USER_DEFINED_NORMALIZATION_UPPER_QUANTILE <- 0.99

USER_DEFINED_FINAL_SCORE_MIN <- 0
USER_DEFINED_FINAL_SCORE_MAX <- 1

USER_DEFINED_NONFINITE_AS_MINIMUM <- TRUE

USER_DEFINED_SPOT_ALPHA <- c(1, 1)

USER_DEFINED_NCOL_MULTIPANEL <- 3L

USER_DEFINED_PATHWAY_PALETTE <- c(
    "#08306B",
    "#2171B5",
    "#41B6C4",
    "#7FCDBB",
    "#C7E9B4",
    "#FFFFCC",
    "#FED976",
    "#FD8D3C",
    "#E31A1C"
)

RESULTS_WORKSPACE_DEFAULT<-"";INPUT_RDS_OPTION<-"";SPATIAL_GENE_LOW_COLOR<-"#F1F5F9";SPATIAL_GENE_HIGH_COLOR<-"#B91C1C"
run_gui<-interactive()||!length(commandArgs(TRUE))||isTRUE(cli$gui);if(isTRUE(cli$cli))run_gui<-FALSE
if(run_gui){gui<-visium_desktop_gui("Script 5 - Spatially Variable Genes and Pathways",list(
list(name="results_dir",label="Sample results folder (for example Results/Sample_01)",value=RESULTS_WORKSPACE_DEFAULT,type="directory",group="Files",required=TRUE,must_exist=TRUE),
list(name="input_rds",label="Step 4 resolution-specific clustered Seurat RDS",value="",type="file",group="Files",required=TRUE,must_exist=TRUE,browse_initial_dir=function(values) file.path(values$results_dir,"Seurat_RDS"),path_pattern="_S04_QCfilt_Norm(SCT|Log|RC)_Clstr[0-9]+(\\.[0-9]+)?\\.rds$",path_message="a resolution-specific Step 4 RDS such as *_S04_QCfilt_NormSCT_Clstr0.40.rds or *_Clstr0.80.rds"),
list(name="workspace_help",type="info",group="Files",text="After selecting the sample results folder, Browse opens its Seurat_RDS folder. Select the exact Step 4 clustered RDS to analyze. Its cumulative tags are preserved and _SvgMoran or _SvgMark is appended according to the selected algorithm."),
list(name="user_defined_plot_file",label="Linear-model pathway definition file (not a cluster-name file)",value="",type="file",group="Files"),
list(name="selection_method",label="Spatial selection algorithm(s) (click one or both)",value=SELECTION_METHOD,type="multichoice",choices=c("moransi","markvariogram"),group="Spatial genes"),list(name="number_features_to_test",label="Variable Feature_Genes to test",value=NUMBER_FEATURES_TO_TEST,type="integer",group="Spatial genes"),list(name="number_top_features_to_plot",label="Highest-ranked Feature_Genes to plot",value=NUMBER_TOP_FEATURES_TO_PLOT,type="integer",group="Spatial genes"),list(name="plot_top_spatially_variable_features",label="Create spatial plots for top Feature_Genes",value=PLOT_TOP_SPATIALLY_VARIABLE_FEATURES,type="boolean",group="Spatial genes"),list(name="future_workers",label="Parallel workers",value=FUTURE_WORKERS,type="integer",group="Performance"),list(name="future_globals_max_size_gb",label="Maximum exported globals (GB)",value=FUTURE_GLOBALS_MAX_SIZE_GB,type="number",group="Performance",help="This is future.globals.maxSize: it limits the size of data exported to each worker. It is not a total-RAM ceiling and cannot prevent multisession workers from using more RAM."),list(name="performance_memory_estimate",type="info",group="Performance",text="High-water RAM planning estimate is based on the selected input RDS and independent multisession workers.",sources=c("input_rds","future_workers","future_globals_max_size_gb","number_features_to_test","user_defined_combination_method","user_defined_gene_normalization"),compute=visium_memory_estimate_text),
list(name="plot_user_defined_features",label="Calculate and plot linear model custom pathways",value=PLOT_USER_DEFINED_FEATURES,type="boolean",group="Linear Model custom pathways"),list(name="user_defined_plot_assay",label="Expression assay",value=USER_DEFINED_PLOT_ASSAY,type="choice",choices=c("AUTO"),choice_source="input_rds",choice_loader=visium_gui_assay_choices,group="Linear Model custom pathways"),list(name="user_defined_plot_layer",label="Expression layer (recommended: data)",value=USER_DEFINED_PLOT_LAYER,type="choice",choices=c("data","scale.data","counts"),choice_sources=c("input_rds","user_defined_plot_assay"),choice_loader=visium_gui_layer_choices,group="Linear Model custom pathways"),list(name="user_defined_combination_method",label="Gene-score combination method (select one or more)",value=USER_DEFINED_COMBINATION_METHODS,type="multichoice",choices=c("sum","mean","mean_by_sign"),group="Linear Model custom pathways"),list(name="user_defined_gene_normalization",label="Per-gene normalization (select one or more)",value=USER_DEFINED_GENE_NORMALIZATIONS,type="multichoice",choices=c("robust_minmax","minmax","none"),group="Linear Model custom pathways"),
list(name="spatial_help_moran",type="info",group="Spatial-gene guidance",text="Select Moran's I, mark variogram, or both. Each algorithm runs separately in SvgMoran or SvgMark and adds its tag to the output RDS. Moran results report both an FDR-significance flag and a separate top-ranked flag; a top-N rank alone does not mean statistical significance."),
list(name="spatial_help_variogram",type="info",group="Spatial-gene guidance",text="Moran's I tests local spatial autocorrelation. Mark variogram uses Seurat's distance-dependent spatial-expression method on the assay scale.data layer."),
list(name="spatial_help_features",type="info",group="Spatial-gene guidance",text="Variable Feature_Genes to test takes the first N genes from VariableFeatures(object). Testing more Feature_Genes broadens discovery but increases runtime. Highest-ranked Feature_Genes to plot controls output figures only and does not change the statistical ranking."),
list(name="spatial_help_images",type="info",group="Spatial-gene guidance",text="The selected method is run separately for every spatial image. Rankings are saved per image and combined into a single all-images CSV."),
list(name="custom_help_file",type="info",group="Linear Model pathway definition file",text="Example pathway definition file (tab-delimited, no header): Breast_epithelial<TAB> KRT8<TAB> KRT18<TAB> -VIM. The first column is the pathway/plot name; each remaining column is a Feature_Gene. Prefix a gene with - or NEG: for a negative term, + or POS: for a positive term, and use 2*GENE for a weight."),
list(name="custom_help_assay",type="info",group="Linear Model pathway settings",text="Assay AUTO chooses SCT when available, otherwise Spatial. Use data for normalized expression and for the default pathway scoring. scale.data is a per-gene z-score layer: select it only when every gene should contribute relative expression rather than expression magnitude. counts are raw Count_RNAs and are not recommended for pathway scoring."),
list(name="custom_help_sum",type="info",group="Linear Model pathway scoring",text="sum adds all signed and weighted gene values. Pathways containing more genes can therefore have larger score magnitudes."),
list(name="custom_help_mean",type="info",group="Linear Model pathway scoring",text="mean divides the signed weighted sum by the total absolute weight, making scores more comparable across pathways with different numbers or weights of genes."),
list(name="custom_help_sign",type="info",group="Linear Model pathway scoring",text="mean_by_sign calculates the mean positive-gene signal minus the mean absolute negative-gene signal, balancing unequal positive and negative gene-set sizes."),
list(name="custom_help_norm",type="info",group="Linear Model pathway scoring",text="robust_minmax clips each gene to the 1st and 99th percentiles before rescaling; minmax uses the full observed range; none uses assay values unchanged. The final 0-to-1 pathway value is a within-pathway, within-tissue relative score: compare locations for the same pathway, not absolute magnitude between different pathways.")
),accent="#9C6644");cli<-modifyList(cli,gui)}
RESULTS_WORKSPACE<-visium_validate_results_workspace(visium_option(cli,"results-dir",RESULTS_WORKSPACE_DEFAULT,"path"));INPUT_DIRECTORY_OPTION<-visium_stage_directory(RESULTS_WORKSPACE,"4_Clustering",create=FALSE);OUTPUT_DIRECTORY_OPTION<-visium_stage_directory(RESULTS_WORKSPACE,"5_Spatially_Variable_Genes",create=TRUE);INPUT_RDS_OPTION<-visium_option(cli,"input-rds",INPUT_RDS_OPTION,"path");SELECTION_METHODS<-visium_option(cli,"selection-method",SELECTION_METHOD,"csv");NUMBER_FEATURES_TO_TEST<-visium_option(cli,"number-features-to-test",NUMBER_FEATURES_TO_TEST,"integer");NUMBER_TOP_FEATURES_TO_PLOT<-visium_option(cli,"number-top-features-to-plot",NUMBER_TOP_FEATURES_TO_PLOT,"integer");FUTURE_WORKERS<-visium_option(cli,"future-workers",FUTURE_WORKERS,"integer");FUTURE_GLOBALS_MAX_SIZE_GB<-visium_option(cli,"future-globals-max-size-gb",FUTURE_GLOBALS_MAX_SIZE_GB,"number");PLOT_TOP_SPATIALLY_VARIABLE_FEATURES<-visium_option(cli,"plot-top-spatially-variable-features",PLOT_TOP_SPATIALLY_VARIABLE_FEATURES,"boolean");PLOT_USER_DEFINED_FEATURES<-visium_option(cli,"plot-user-defined-features",PLOT_USER_DEFINED_FEATURES,"boolean");USER_DEFINED_PLOT_FILE<-visium_option(cli,"user-defined-plot-file","","path");USER_DEFINED_PLOT_ASSAY<-visium_option(cli,"user-defined-plot-assay",USER_DEFINED_PLOT_ASSAY);USER_DEFINED_PLOT_LAYER<-visium_option(cli,"user-defined-plot-layer",USER_DEFINED_PLOT_LAYER);USER_DEFINED_COMBINATION_METHODS<-visium_option(cli,"user-defined-combination-method",USER_DEFINED_COMBINATION_METHODS,"csv");USER_DEFINED_GENE_NORMALIZATIONS<-visium_option(cli,"user-defined-gene-normalization",USER_DEFINED_GENE_NORMALIZATIONS,"csv");USER_DEFINED_PATHWAY_PALETTE<-visium_option(cli,"pathway-palette",paste(USER_DEFINED_PATHWAY_PALETTE,collapse=","),"csv");SPATIAL_GENE_LOW_COLOR<-visium_option(cli,"spatial-gene-low-color",SPATIAL_GENE_LOW_COLOR);SPATIAL_GENE_HIGH_COLOR<-visium_option(cli,"spatial-gene-high-color",SPATIAL_GENE_HIGH_COLOR);visium_colors(USER_DEFINED_PATHWAY_PALETTE,"Pathway palette",2L);visium_colors(c(SPATIAL_GENE_LOW_COLOR,SPATIAL_GENE_HIGH_COLOR),"Spatial gene colors",2L)
if(!nzchar(INPUT_RDS_OPTION)||!file.exists(INPUT_RDS_OPTION))stop("Select the Step 4 clustered Seurat RDS explicitly with --input-rds.")
if(PLOT_USER_DEFINED_FEATURES&&(!nzchar(USER_DEFINED_PLOT_FILE)||!file.exists(USER_DEFINED_PLOT_FILE)))stop("Custom gene/pathway plotting is enabled; select its definition file explicitly with --user-defined-plot-file.")
if (NUMBER_FEATURES_TO_TEST < 1L) stop("Variable Feature_Genes to test must be at least 1.")
if (NUMBER_TOP_FEATURES_TO_PLOT < 1L) stop("Highest-ranked Feature_Genes to plot must be at least 1.")
if (FUTURE_WORKERS < 1L) stop("Parallel workers must be at least 1.")
if (FUTURE_GLOBALS_MAX_SIZE_GB <= 0) stop("Maximum exported globals must be greater than 0 GB.")
SELECTION_METHODS <- unique(tolower(trimws(SELECTION_METHODS)))
if (!length(SELECTION_METHODS) || any(!SELECTION_METHODS %in% c("moransi", "markvariogram"))) stop("Spatial selection algorithm(s) must contain only moransi and/or markvariogram.")
USER_DEFINED_COMBINATION_METHODS <- unique(tolower(trimws(USER_DEFINED_COMBINATION_METHODS)))
USER_DEFINED_GENE_NORMALIZATIONS <- unique(tolower(trimws(USER_DEFINED_GENE_NORMALIZATIONS)))
if (!length(USER_DEFINED_COMBINATION_METHODS) || any(!USER_DEFINED_COMBINATION_METHODS %in% c("sum", "mean", "mean_by_sign"))) stop("Gene-score combination method must contain only sum, mean, or mean_by_sign.")
if (!length(USER_DEFINED_GENE_NORMALIZATIONS) || any(!USER_DEFINED_GENE_NORMALIZATIONS %in% c("robust_minmax", "minmax", "none"))) stop("Per-gene normalization must contain only robust_minmax, minmax, or none.")

SCRIPT_DIRECTORY <- PIPELINE_SCRIPT_DIRECTORY
INPUT_DIRECTORY <- INPUT_DIRECTORY_OPTION
OUTPUT_DIRECTORY <- OUTPUT_DIRECTORY_OPTION

dir.create(OUTPUT_DIRECTORY, recursive = TRUE, showWarnings = FALSE)

LOG_FILE <- file.path(OUTPUT_DIRECTORY, "run_log.txt")
log_connection <- file(LOG_FILE, open = "wt")
sink(log_connection, type = "output", split = TRUE)
sink(log_connection, type = "message")

on.exit({
    try(future::plan(future::sequential), silent = TRUE)
    cat("\n\n================ SESSION INFORMATION ================\n")
    print(sessionInfo())
    try(sink(type = "message"), silent = TRUE)
    try(sink(type = "output"), silent = TRUE)
    try(close(log_connection), silent = TRUE)
}, add = TRUE)

cat("Input directory:", INPUT_DIRECTORY, "\n")
cat("Output directory:", OUTPUT_DIRECTORY, "\n")
cat("Started:", format(Sys.time()), "\n\n")

required_packages <- c(
    "Seurat", "SeuratObject", "ggplot2", "future",
    "future.apply", "parallelly", "matrixStats", "scales", "patchwork"
)

missing_packages <- required_packages[
    !vapply(required_packages, requireNamespace, logical(1), quietly = TRUE)
]

if (length(missing_packages)) {
    stop(
        "Missing required package(s): ",
        paste(missing_packages, collapse = ", "),
        "\nInstall them before running this script."
    )
}

if (
    "moransi" %in% SELECTION_METHODS &&
    !requireNamespace("Rfast2", quietly = TRUE) &&
    !requireNamespace("ape", quietly = TRUE)
) {
    stop("Moran's I requires either Rfast2 or ape.")
}

suppressPackageStartupMessages({
    library(Seurat)
    library(SeuratObject)
    library(ggplot2)
    library(future)
    library(future.apply)
    library(parallelly)
    library(scales)
    library(patchwork)
})

available_cores <- parallelly::availableCores()
FUTURE_WORKERS <- min(as.integer(FUTURE_WORKERS), as.integer(available_cores))

if (FUTURE_WORKERS < 2L) {
    stop("At least two available cores are required.")
}

options(future.globals.maxSize = FUTURE_GLOBALS_MAX_SIZE_GB * 1024^3)
future::plan(future::multisession, workers = FUTURE_WORKERS)

cat("Future plan: multisession\n")
cat("Future workers:", future::nbrOfWorkers(), "\n")
cat("Available cores:", available_cores, "\n")
cat("future.globals.maxSize:", FUTURE_GLOBALS_MAX_SIZE_GB, "GiB\n\n")

sanitize_name <- function(x) {
    gsub("[^A-Za-z0-9_.-]", "_", x)
}

bin_spatial_data <- function(data, position, x.cuts, y.cuts) {
    position <- as.data.frame(position[, 1:2, drop = FALSE])
    colnames(position) <- c("x", "y")
    position$x_bin <- cut(position$x, breaks = x.cuts)
    position$y_bin <- cut(position$y, breaks = y.cuts)
    position$bin <- paste0(position$x_bin, "_", position$y_bin)
    bins <- unique(position$bin)

    new_data <- matrix(
        0, nrow(data), length(bins),
        dimnames = list(rownames(data), bins)
    )
    new_position <- matrix(
        0, length(bins), 2,
        dimnames = list(bins, c("x", "y"))
    )

    for (i in seq_along(bins)) {
        cells <- rownames(position)[position$bin == bins[i]]
        new_data[, i] <- if (length(cells) == 1L) {
            data[, cells]
        } else {
            rowMeans(data[, cells, drop = FALSE])
        }
        new_position[i, ] <- colMeans(position[cells, c("x", "y"), drop = FALSE])
    }

    list(data = new_data, position = new_position)
}

run_moransi_parallel <- function(data, position, workers) {
    workers <- min(workers, nrow(data))

    groups <- split(
        rownames(data),
        cut(seq_len(nrow(data)), breaks = workers, labels = FALSE)
    )

    data_groups <- lapply(
        groups,
        function(features) data[features, , drop = FALSE]
    )

    expected_features <- unlist(
        lapply(data_groups, rownames),
        use.names = FALSE
    )

    cat(
        "Moran's I:",
        nrow(data),
        "genes divided among",
        length(data_groups),
        "workers\n"
    )

    result_list <- future.apply::future_lapply(
        data_groups,
        function(data_group, position_matrix) {
            result <- Seurat::RunMoransI(
                data = data_group,
                pos = position_matrix,
                verbose = FALSE
            )

            if (nrow(result) != nrow(data_group)) {
                stop(
                    "A Moran worker returned ",
                    nrow(result),
                    " rows for ",
                    nrow(data_group),
                    " input genes."
                )
            }

            result
        },
        position_matrix = position,
        future.seed = TRUE,
        future.packages = "Seurat",
        future.scheduling = Inf
    )

    results <- do.call(rbind, unname(result_list))

    if (nrow(results) != length(expected_features)) {
        stop(
            "Combined Moran results contain ",
            nrow(results),
            " rows, but ",
            length(expected_features),
            " genes were expected."
        )
    }

    rownames(results) <- expected_features

    if (anyDuplicated(rownames(results))) {
        stop("Duplicated gene names were found in the Moran results.")
    }

    results
}

find_domain_markers_parallel <- function(object) {
    cluster_ids <- sort(unique(as.character(Idents(object))))
    cat("Domain markers:", length(cluster_ids), "clusters in parallel\n")

    results <- future.apply::future_lapply(
        cluster_ids,
        function(cluster_id, x) {
            markers <- Seurat::FindMarkers(
                x,
                ident.1 = cluster_id,
                only.pos = TRUE,
                min.pct = DOMAIN_MARKER_MIN_PCT,
                logfc.threshold = DOMAIN_MARKER_LOGFC_THRESHOLD,
                random.seed = RANDOM_SEED,
                verbose = FALSE
            )

            if (!nrow(markers)) return(NULL)

            markers <- markers[
                order(markers$p_val_adj, -abs(markers$pct.1 - markers$pct.2)),
                ,
                drop = FALSE
            ]
            markers <- markers[
                is.finite(markers$p_val_adj) & markers$p_val_adj < DOMAIN_MARKER_ADJUSTED_PVALUE_THRESHOLD,
                ,
                drop = FALSE
            ]

            if (!nrow(markers)) return(NULL)

            markers$cluster <- cluster_id
            markers$gene <- rownames(markers)
            markers
        },
        x = object,
        future.seed = TRUE,
        future.packages = "Seurat",
        future.scheduling = Inf
    )

    results <- Filter(Negate(is.null), results)
    if (!length(results)) return(data.frame())

    markers <- do.call(rbind, results)
    rownames(markers) <- make.unique(as.character(markers$gene))
    markers
}

read_user_defined_plot_file <- function(file_path) {
    if (!file.exists(file_path)) {
        stop(
            "User-defined plot file not found: ", file_path,
            "\nPlace it in the Input directory."
        )
    }

    first_line <- readLines(file_path, n = 1L, warn = FALSE)
    first_fields <- if (length(first_line)) trimws(strsplit(first_line, "\t", fixed = TRUE)[[1L]]) else character(0)
    normalized_first_fields <- gsub("[^a-z0-9]+", "", tolower(first_fields))
    if (length(normalized_first_fields) >= 2L && identical(normalized_first_fields[1:2], c("clusternumber", "clustername"))) {
        stop(
            "The selected file is a cluster-number-to-name table, not a pathway-definition file: ", file_path,
            "\nSelect a pathway file whose first column contains pathway names and whose remaining columns contain Feature_Gene symbols.",
            "\nExample: My_Pathway<TAB>IGHG1<TAB>IGHG4<TAB>IGKC"
        )
    }

    x <- read.delim(
        file_path,
        header = FALSE,
        sep = "\t",
        quote = "",
        fill = TRUE,
        check.names = FALSE,
        stringsAsFactors = FALSE
    )

    if (ncol(x) < 2L) {
        stop("The user-defined plot file must contain at least 2 columns.")
    }

    if (!nrow(x)) {
        stop("The user-defined plot file is empty.")
    }

    names(x)[1] <- "plot_name"
    x
}

parse_signed_term <- function(term) {
    term <- trimws(as.character(term))
    if (!nzchar(term)) return(NULL)

    if (grepl("^POS:", term, ignore.case = TRUE)) {
        return(list(raw = term, sign = 1, weight = 1, gene = sub("^POS:", "", term, ignore.case = TRUE)))
    }
    if (grepl("^NEG:", term, ignore.case = TRUE)) {
        return(list(raw = term, sign = -1, weight = 1, gene = sub("^NEG:", "", term, ignore.case = TRUE)))
    }

    sign <- 1
    if (substr(term, 1, 1) == "+") {
        term <- substr(term, 2, nchar(term))
        sign <- 1
    } else if (substr(term, 1, 1) == "-") {
        term <- substr(term, 2, nchar(term))
        sign <- -1
    }

    term <- trimws(term)

    weight <- 1
    gene <- term
    if (grepl("^[0-9.]+\\*", term)) {
        weight <- as.numeric(sub("\\*.*$", "", term))
        gene <- sub("^[0-9.]+\\*", "", term)
    }

    gene <- trimws(gene)

    if (!nzchar(gene)) return(NULL)

    list(raw = term, sign = sign, weight = weight, gene = gene)
}

match_gene_names <- function(requested_genes, available_genes) {
    available_upper <- toupper(available_genes)
    out <- vector("list", length(requested_genes))

    for (i in seq_along(requested_genes)) {
        g <- requested_genes[i]
        exact_hit <- g %in% available_genes
        if (exact_hit) {
            out[[i]] <- list(
                requested_gene = g,
                matched_gene = g,
                status = "exact"
            )
        } else {
            hit_index <- which(available_upper == toupper(g))
            if (length(hit_index) == 1L) {
                out[[i]] <- list(
                    requested_gene = g,
                    matched_gene = available_genes[hit_index],
                    status = "case_insensitive"
                )
            } else if (length(hit_index) > 1L) {
                out[[i]] <- list(
                    requested_gene = g,
                    matched_gene = available_genes[hit_index[1L]],
                    status = "multiple_case_insensitive_matches_first_used"
                )
            } else {
                out[[i]] <- list(
                    requested_gene = g,
                    matched_gene = NA_character_,
                    status = "missing"
                )
            }
        }
    }

    out
}

extract_expression_matrix <- function(object, assay, layer, features = NULL, cells = NULL) {
    assay_obj <- object[[assay]]

    available_layers <- tryCatch(Layers(assay_obj), error = function(e) character(0))
    chosen_layer <- layer

    if (!(chosen_layer %in% available_layers)) {
        fallback_layers <- c("data", "scale.data", "counts")
        fallback_layers <- fallback_layers[fallback_layers %in% available_layers]
        if (!length(fallback_layers)) {
            stop(
                "Layer '", layer, "' not found in assay '", assay,
                "' and no fallback layer is available."
            )
        }
        chosen_layer <- fallback_layers[1L]
        cat("Requested layer not found. Falling back to layer:", chosen_layer, "\n")
    }

    mat <- LayerData(
        assay_obj,
        layer = chosen_layer,
        features = features,
        cells = cells
    )

    as.matrix(mat)
}

scale_gene_values <- function(v,
                              method = USER_DEFINED_GENE_NORMALIZATIONS[[1L]],
                              lower_q = USER_DEFINED_NORMALIZATION_LOWER_QUANTILE,
                              upper_q = USER_DEFINED_NORMALIZATION_UPPER_QUANTILE) {
    v <- as.numeric(v)

    if (all(is.na(v))) return(v)

    if (identical(method, "none")) {
        return(v)
    }

    if (identical(method, "minmax")) {
        vmin <- min(v, na.rm = TRUE)
        vmax <- max(v, na.rm = TRUE)
        if (!is.finite(vmin) || !is.finite(vmax) || vmax <= vmin) {
            return(rep(0, length(v)))
        }
        return((v - vmin) / (vmax - vmin))
    }

    if (identical(method, "robust_minmax")) {
        lo <- as.numeric(stats::quantile(v, probs = lower_q, na.rm = TRUE, names = FALSE))
        hi <- as.numeric(stats::quantile(v, probs = upper_q, na.rm = TRUE, names = FALSE))
        if (!is.finite(lo) || !is.finite(hi) || hi <= lo) {
            return(rep(0, length(v)))
        }
        v2 <- pmin(pmax(v, lo), hi)
        return((v2 - lo) / (hi - lo))
    }

    stop("Unknown USER_DEFINED_GENE_NORMALIZATION: ", method)
}

normalize_final_pathway_score <- function(v,
                                          target_min = USER_DEFINED_FINAL_SCORE_MIN,
                                          target_max = USER_DEFINED_FINAL_SCORE_MAX) {
    v <- as.numeric(v)

    if (!is.finite(target_min) || !is.finite(target_max) || target_max <= target_min) {
        stop("USER_DEFINED_FINAL_SCORE_MAX must be greater than USER_DEFINED_FINAL_SCORE_MIN.")
    }

    finite_mask <- is.finite(v)
    finite_values <- v[finite_mask]
    if (!length(finite_values)) {
        if (USER_DEFINED_NONFINITE_AS_MINIMUM) {
            return(rep(target_min, length(v)))
        }
        return(rep(NA_real_, length(v)))
    }

    source_min <- min(finite_values)
    source_max <- max(finite_values)

    if (source_max <= source_min) {
        result <- rep(target_min, length(v))
        if (!USER_DEFINED_NONFINITE_AS_MINIMUM) {
            result[!finite_mask] <- NA_real_
        }
        return(result)
    }

    result <- target_min +
        ((v - source_min) / (source_max - source_min)) *
        (target_max - target_min)

    result <- pmin(pmax(result, target_min), target_max)

    if (USER_DEFINED_NONFINITE_AS_MINIMUM) {
        result[!finite_mask] <- target_min
    } else {
        result[!finite_mask] <- NA_real_
    }

    result
}

build_user_defined_scores <- function(object,
                                      assay,
                                      layer,
                                      definition_table,
                                      output_directory,
                                      normalization_method,
                                      combination_method) {
    all_features <- rownames(object[[assay]])
    all_cells <- colnames(object)

    term_columns <- setdiff(colnames(definition_table), "plot_name")

    parsed_rows <- vector("list", nrow(definition_table))
    all_requested_genes <- character(0)

    for (i in seq_len(nrow(definition_table))) {
        plot_name <- trimws(as.character(definition_table$plot_name[i]))
        terms <- unlist(definition_table[i, term_columns, drop = TRUE], use.names = FALSE)
        terms <- trimws(as.character(terms))
        terms <- terms[nzchar(terms) & !is.na(terms)]

        parsed_terms <- lapply(terms, parse_signed_term)
        parsed_terms <- Filter(Negate(is.null), parsed_terms)

        if (!length(parsed_terms)) {
            stop("No valid terms were found for plot row ", i, " (", plot_name, ").")
        }

        all_requested_genes <- c(all_requested_genes, vapply(parsed_terms, `[[`, character(1), "gene"))
        parsed_rows[[i]] <- list(plot_name = plot_name, terms = parsed_terms)
    }

    unique_requested_genes <- unique(all_requested_genes)
    gene_matches <- match_gene_names(unique_requested_genes, all_features)

    validation_table <- do.call(
        rbind,
        lapply(gene_matches, function(x) as.data.frame(x, stringsAsFactors = FALSE))
    )
    write.csv(
        validation_table,
        file.path(output_directory, "user_defined_spatial_plot_term_validation.csv"),
        row.names = FALSE
    )

    matched_genes <- unique(validation_table$matched_gene[!is.na(validation_table$matched_gene)])
    if (!length(matched_genes)) {
        stop(
            "None of the requested genes match the Feature_Genes in assay '", assay, "' layer '", layer, "'.",
            "\nPathway file: ", USER_DEFINED_PLOT_FILE,
            "\nRequested terms included: ", paste(utils::head(unique(validation_table$requested_gene), 12L), collapse = ", "),
            "\nCheck that the file contains gene symbols or identifiers matching rownames of the selected Seurat assay."
        )
    }

    expr_before <- extract_expression_matrix(
        object = object,
        assay = assay,
        layer = layer,
        features = matched_genes,
        cells = all_cells
    )

    expr_after <- expr_before
    normalization_parameters <- list()

    for (g in rownames(expr_before)) {
        original_values <- expr_before[g, ]
        expr_after[g, ] <- scale_gene_values(original_values, method = normalization_method)

        normalization_parameters[[g]] <- data.frame(
            gene = g,
            method = normalization_method,
            min_before = min(original_values, na.rm = TRUE),
            max_before = max(original_values, na.rm = TRUE),
            q0_before = as.numeric(stats::quantile(original_values, probs = 0, na.rm = TRUE, names = FALSE)),
            q1_before = as.numeric(stats::quantile(original_values, probs = 0.01, na.rm = TRUE, names = FALSE)),
            q5_before = as.numeric(stats::quantile(original_values, probs = 0.05, na.rm = TRUE, names = FALSE)),
            q50_before = as.numeric(stats::quantile(original_values, probs = 0.50, na.rm = TRUE, names = FALSE)),
            q95_before = as.numeric(stats::quantile(original_values, probs = 0.95, na.rm = TRUE, names = FALSE)),
            q99_before = as.numeric(stats::quantile(original_values, probs = 0.99, na.rm = TRUE, names = FALSE)),
            stringsAsFactors = FALSE
        )
    }

    normalization_parameters <- do.call(rbind, normalization_parameters)
    write.csv(
        normalization_parameters,
        file.path(output_directory, "user_defined_gene_normalization_parameters.csv"),
        row.names = FALSE
    )

    write.csv(
        cbind(gene = rownames(expr_before), as.data.frame(expr_before, check.names = FALSE)),
        file.path(output_directory, "user_defined_gene_expression_before_gene_scaling.csv"),
        row.names = FALSE
    )

    write.csv(
        cbind(gene = rownames(expr_after), as.data.frame(expr_after, check.names = FALSE)),
        file.path(output_directory, "user_defined_gene_expression_after_gene_scaling.csv"),
        row.names = FALSE
    )

    match_map <- setNames(validation_table$matched_gene, validation_table$requested_gene)

    raw_score_table <- data.frame(cell = all_cells, check.names = FALSE, stringsAsFactors = FALSE)
    normalized_score_table <- data.frame(cell = all_cells, check.names = FALSE, stringsAsFactors = FALSE)
    metadata_added <- character(0)
    plot_metadata <- vector("list", length(parsed_rows))
    plot_definition_export <- list()

    for (i in seq_along(parsed_rows)) {
        plot_name <- parsed_rows[[i]]$plot_name
        terms <- parsed_rows[[i]]$terms

        resolved <- lapply(terms, function(term) {
            matched_gene <- unname(match_map[term$gene])
            if (is.na(matched_gene) || !nzchar(matched_gene)) {
                stop(
                    "The gene '", term$gene, "' from plot '", plot_name,
                    "' was not found in assay '", assay, "'."
                )
            }
            term$matched_gene <- matched_gene
            term
        })

        score_matrix <- sapply(
            resolved,
            function(term) {
                term$sign * term$weight * expr_after[term$matched_gene, ]
            }
        )

        if (is.null(dim(score_matrix))) {
            score_matrix <- matrix(score_matrix, nrow = length(all_cells), ncol = 1L)
            colnames(score_matrix) <- resolved[[1]]$matched_gene
        }

        abs_weights <- sum(vapply(resolved, function(term) abs(term$weight), numeric(1)))
        n_pos <- sum(vapply(resolved, function(term) term$sign > 0, logical(1)))
        n_neg <- sum(vapply(resolved, function(term) term$sign < 0, logical(1)))

        if (combination_method == "sum") {
            raw_scores <- rowSums(score_matrix)
        } else if (combination_method == "mean") {
            if (abs_weights == 0) {
                raw_scores <- rowSums(score_matrix)
            } else {
                raw_scores <- rowSums(score_matrix) / abs_weights
            }
        } else if (combination_method == "mean_by_sign") {
            pos_terms <- which(vapply(resolved, function(term) term$sign > 0, logical(1)))
            neg_terms <- which(vapply(resolved, function(term) term$sign < 0, logical(1)))
            pos_score <- if (length(pos_terms)) rowMeans(score_matrix[, pos_terms, drop = FALSE]) else rep(0, length(all_cells))
            neg_score <- if (length(neg_terms)) rowMeans(abs(score_matrix[, neg_terms, drop = FALSE])) else rep(0, length(all_cells))
            raw_scores <- pos_score - neg_score
        } else {
            stop("Unknown USER_DEFINED_COMBINATION_METHOD: ", combination_method)
        }

        normalized_scores <- normalize_final_pathway_score(
            v = raw_scores,
            target_min = USER_DEFINED_FINAL_SCORE_MIN,
            target_max = USER_DEFINED_FINAL_SCORE_MAX
        )

        metadata_column <- paste0("UserDefined_", sprintf("%03d", i))
        names(raw_scores) <- all_cells
        names(normalized_scores) <- all_cells

        object[[metadata_column]] <- normalized_scores
        metadata_added <- c(metadata_added, metadata_column)

        raw_score_table[[metadata_column]] <- raw_scores
        normalized_score_table[[metadata_column]] <- normalized_scores

        expression_string <- paste(vapply(
            resolved,
            function(term) {
                paste0(
                    ifelse(term$sign > 0, "+", "-"),
                    ifelse(term$weight == 1, "", paste0(term$weight, "*")),
                    term$matched_gene
                )
            },
            character(1)
        ), collapse = " ")

        plot_definition_export[[i]] <- data.frame(
            plot_index = i,
            plot_name = plot_name,
            metadata_column = metadata_column,
            expression = expression_string,
            contains_negative_term = any(vapply(resolved, function(term) term$sign < 0, logical(1))),
            n_positive_terms = n_pos,
            n_negative_terms = n_neg,
            raw_min = min(raw_scores, na.rm = TRUE),
            raw_max = max(raw_scores, na.rm = TRUE),
            normalized_min = min(normalized_scores, na.rm = TRUE),
            normalized_max = max(normalized_scores, na.rm = TRUE),
            nonfinite_raw_scores = sum(!is.finite(raw_scores)),
            nonfinite_final_scores = sum(!is.finite(normalized_scores)),
            final_target_min = USER_DEFINED_FINAL_SCORE_MIN,
            final_target_max = USER_DEFINED_FINAL_SCORE_MAX,
            stringsAsFactors = FALSE
        )

        plot_metadata[[i]] <- list(
            plot_index = i,
            plot_name = plot_name,
            metadata_column = metadata_column,
            contains_negative_term = any(vapply(resolved, function(term) term$sign < 0, logical(1))),
            expression = expression_string,
            resolved_terms = resolved
        )
    }

    write.csv(
        raw_score_table,
        file.path(output_directory, "user_defined_spatial_plot_scores_raw_all_cells.csv"),
        row.names = FALSE
    )

    write.csv(
        normalized_score_table,
        file.path(output_directory, "user_defined_spatial_plot_scores_normalized_all_cells.csv"),
        row.names = FALSE
    )

    write.csv(
        normalized_score_table,
        file.path(output_directory, "user_defined_spatial_plot_scores_all_cells.csv"),
        row.names = FALSE
    )

    write.csv(
        do.call(rbind, plot_definition_export),
        file.path(output_directory, "user_defined_spatial_plot_definitions.csv"),
        row.names = FALSE
    )

    list(
        object = object,
        plot_metadata = plot_metadata,
        raw_score_table = raw_score_table,
        normalized_score_table = normalized_score_table,
        expr_before = expr_before,
        expr_after = expr_after
    )
}

add_custom_color_scale <- function(plot_object,
                                   values,
                                   contains_negative_term = FALSE,
                                   pathway_palette = USER_DEFINED_PATHWAY_PALETTE,
                                   final_min = USER_DEFINED_FINAL_SCORE_MIN,
                                   final_max = USER_DEFINED_FINAL_SCORE_MAX) {
    values <- as.numeric(values)
    values <- values[is.finite(values)]
    if (!length(values)) return(plot_object)

    color_positions <- seq(final_min, final_max, length.out = length(pathway_palette))

    plot_object +
        scale_fill_gradientn(
            colours = pathway_palette,
            values = scales::rescale(
                color_positions,
                from = c(final_min, final_max)
            ),
            limits = c(final_min, final_max),
            oob = scales::squish,
            na.value = pathway_palette[1L]
        )
}

plot_user_defined_feature <- function(object,
                                      image_name,
                                      plot_name,
                                      metadata_column,
                                      contains_negative_term,
                                      output_file = NULL) {
    values <- object[[metadata_column]][, 1]

    p <- SpatialFeaturePlot(
        object = object,
        features = metadata_column,
        images = image_name,
        ncol = 1,
        alpha = USER_DEFINED_SPOT_ALPHA,
        min.cutoff = USER_DEFINED_FINAL_SCORE_MIN,
        max.cutoff = USER_DEFINED_FINAL_SCORE_MAX
    )

    p <- add_custom_color_scale(
        plot_object = p,
        values = values,
        contains_negative_term = contains_negative_term,
        pathway_palette = USER_DEFINED_PATHWAY_PALETTE,
        final_min = USER_DEFINED_FINAL_SCORE_MIN,
        final_max = USER_DEFINED_FINAL_SCORE_MAX
    )

    p <- p + ggtitle(paste0(plot_name, " — within-tissue relative pathway score"))

    if (!is.null(output_file)) {
        ggsave(
            filename = output_file,
            plot = p,
            width = 7,
            height = 6,
            dpi = 300
        )
    }

    p
}

plot_user_defined_features_for_image <- function(object,
                                                 image_name,
                                                 plot_metadata,
                                                 output_directory,
                                                 multiple_image_file = MULTIPLE_IMAGE_FILE) {
    safe_image_name <- sanitize_name(image_name)

    if (multiple_image_file) {
        plot_dir <- file.path(
            output_directory,
            paste0("selected_genes_and_pathways_", safe_image_name)
        )
        dir.create(plot_dir, recursive = TRUE, showWarnings = FALSE)

        for (i in seq_along(plot_metadata)) {
            md <- plot_metadata[[i]]
            safe_plot_name <- sanitize_name(md$plot_name)
            output_file <- file.path(
                plot_dir,
                paste0(sprintf("%03d", i), "_", safe_plot_name, ".png")
            )

            plot_user_defined_feature(
                object = object,
                image_name = image_name,
                plot_name = md$plot_name,
                metadata_column = md$metadata_column,
                contains_negative_term = md$contains_negative_term,
                output_file = output_file
            )
        }

    } else {
        plots <- vector("list", length(plot_metadata))
        for (i in seq_along(plot_metadata)) {
            md <- plot_metadata[[i]]
            plots[[i]] <- plot_user_defined_feature(
                object = object,
                image_name = image_name,
                plot_name = md$plot_name,
                metadata_column = md$metadata_column,
                contains_negative_term = md$contains_negative_term,
                output_file = NULL
            )
        }

        combined_plot <- patchwork::wrap_plots(plots, ncol = USER_DEFINED_NCOL_MULTIPANEL)

        ggsave(
            filename = file.path(
                output_directory,
                paste0("selected_genes_and_pathways_", safe_image_name, ".png")
            ),
            plot = combined_plot,
            width = 5 * USER_DEFINED_NCOL_MULTIPANEL,
            height = 4 * ceiling(length(plots) / USER_DEFINED_NCOL_MULTIPANEL),
            dpi = 300
        )
    }
}

worker_pids <- unlist(
    future.apply::future_lapply(
        seq_len(FUTURE_WORKERS),
        function(i) Sys.getpid(),
        future.scheduling = Inf
    )
)

write.csv(
    data.frame(worker = seq_along(worker_pids), process_id = worker_pids),
    file.path(OUTPUT_DIRECTORY, "future_worker_processes.csv"),
    row.names = FALSE
)

cat("Worker process IDs:", paste(worker_pids, collapse = ", "), "\n\n")

rds_files <- INPUT_RDS_OPTION

if (length(rds_files) != 1L) {
    stop("Place exactly one clustered spatial RDS file in Input.")
}

INPUT_RDS_FILE <- normalizePath(rds_files[1L], winslash = "/", mustWork = TRUE)
INHERITED_RDS_TAGS <- visium_rds_operation_tags(INPUT_RDS_FILE, "S04")
object <- readRDS(INPUT_RDS_FILE)
analysis_assay <- if ("SCT" %in% Assays(object)) "SCT" else "Spatial"
DefaultAssay(object) <- analysis_assay

object_memory_gb <- as.numeric(object.size(object)) / 1024^3
score_combination_count <- max(1L, length(USER_DEFINED_COMBINATION_METHODS) * length(USER_DEFINED_GENE_NORMALIZATIONS))
memory_estimate <- visium_estimate_peak_memory(object_memory_gb, FUTURE_WORKERS, NUMBER_FEATURES_TO_TEST, score_combination_count)
estimated_peak_memory_gb <- memory_estimate$estimate_gb
cat(sprintf("High-water RAM planning estimate: %.2f GB (master object %.2f + per-worker copies/native allocations %.2f + worker runtime %.2f + temporary buffers %.2f + score combinations %.2f GB, including safety margin).\n", estimated_peak_memory_gb, memory_estimate$master_object_gb, memory_estimate$worker_object_copies_gb, memory_estimate$worker_runtime_gb, memory_estimate$analysis_buffers_gb, memory_estimate$score_combination_overhead_gb))
cat("Note: future.globals.maxSize limits exported globals only; it is not a total-RAM ceiling.\n")
writeLines(sprintf("High-water RAM planning estimate: %.2f GB\nLoaded object size: %.2f GB\nWorkers: %d\nFeature_Genes tested: %d\nCustom score combinations: %d\nMaster object: %.2f GB\nPer-worker copies and native allocations: %.2f GB\nWorker runtime overhead: %.2f GB\nTemporary buffers: %.2f GB\nScore-combination overhead: %.2f GB\nConfigured maximum exported globals: %.2f GB\n\nThis is a planning estimate, not a guarantee. future.globals.maxSize limits exported globals only; it is not a total-RAM ceiling.", estimated_peak_memory_gb, object_memory_gb, FUTURE_WORKERS, NUMBER_FEATURES_TO_TEST, score_combination_count, memory_estimate$master_object_gb, memory_estimate$worker_object_copies_gb, memory_estimate$worker_runtime_gb, memory_estimate$analysis_buffers_gb, memory_estimate$score_combination_overhead_gb, FUTURE_GLOBALS_MAX_SIZE_GB), file.path(OUTPUT_DIRECTORY, "approximate_peak_memory.txt"))

base_object <- object
method_output_rds_files <- character(length(SELECTION_METHODS))
method_output_folder_tags <- c(moransi = "SvgMoran", markvariogram = "SvgMark")

for (method_index in seq_along(SELECTION_METHODS)) {
SELECTION_METHOD <- SELECTION_METHODS[[method_index]]
METHOD_OUTPUT_TAG <- method_output_folder_tags[[SELECTION_METHOD]]
OUTPUT_DIRECTORY <- file.path(OUTPUT_DIRECTORY_OPTION, METHOD_OUTPUT_TAG)
dir.create(OUTPUT_DIRECTORY, recursive = TRUE, showWarnings = FALSE)
object <- base_object
DefaultAssay(object) <- analysis_assay
cat("\n================================================\n")
cat("Spatial selection algorithm:", SELECTION_METHOD, "\n")
cat("Algorithm results folder:", OUTPUT_DIRECTORY, "\n")

features_to_test <- head(VariableFeatures(object), NUMBER_FEATURES_TO_TEST)
if (!length(features_to_test)) stop("The object has no variable gene features (Feature_Genes).")

image_names <- Images(object)
if (!length(image_names)) stop("No spatial image is stored in the object.")

all_rankings <- list()

for (image_name in image_names) {
    cat("Testing image:", image_name, "\n")
    ranking_statistics <- NULL

    if (SELECTION_METHOD == "moransi") {
        position <- GetTissueCoordinates(object[[image_name]])

        if (
            "cell" %in% colnames(position) &&
            (is.null(rownames(position)) ||
             identical(rownames(position), as.character(seq_len(nrow(position)))))
        ) {
            rownames(position) <- position$cell
        }

        cells <- intersect(rownames(position), colnames(object))
        position <- position[cells, , drop = FALSE]

        expression_data <- as.matrix(
            LayerData(
                object[[analysis_assay]],
                layer = "scale.data",
                cells = cells,
                features = features_to_test
            )
        )

        expression_data <- expression_data[
            matrixStats::rowVars(expression_data) > 0,
            ,
            drop = FALSE
        ]

        if (!nrow(expression_data)) stop("No tested genes have non-zero variance.")

        if (!is.null(X_CUTS) && !is.null(Y_CUTS)) {
            binned <- bin_spatial_data(expression_data, position, X_CUTS, Y_CUTS)
            expression_data <- binned$data
            position <- binned$position
        } else {
            position <- as.matrix(position[, 1:2, drop = FALSE])
        }

        results <- run_moransi_parallel(
            expression_data,
            position,
            FUTURE_WORKERS
        )

        cat(
            "Moran-result gene-name matches:",
            sum(rownames(results) %in% rownames(object[[analysis_assay]])),
            "of",
            nrow(results),
            "\n"
        )

        colnames(results) <- c("MoransI_observed", "MoransI_p.value")
        results$Moran_FDR_BH <- stats::p.adjust(results$MoransI_p.value, method = "BH")
        results <- results[
            order(results$Moran_FDR_BH, -abs(results$MoransI_observed)),
            ,
            drop = FALSE
        ]

        results$Moran_significant_FDR_0.05 <- is.finite(results$Moran_FDR_BH) & results$Moran_FDR_BH <= MORAN_FDR_THRESHOLD
        results$Moran_top_ranked <- FALSE
        results$Moran_top_ranked[
            seq_len(min(nrow(results), NUMBER_SPATIALLY_VARIABLE_FEATURES))
        ] <- TRUE
        results$Moran_rank <- seq_len(nrow(results))

        assay_object <- object[[analysis_assay]]
        assay_features <- rownames(assay_object)
        result_features <- intersect(rownames(results), assay_features)

        if (!length(result_features)) {
            stop("None of the Moran-result genes match the assay's gene-feature names (Feature_Genes).")
        }

        full_feature_metadata <- data.frame(
            MoransI_observed = rep(NA_real_, length(assay_features)),
            MoransI_p.value = rep(NA_real_, length(assay_features)),
            Moran_FDR_BH = rep(NA_real_, length(assay_features)),
            Moran_significant_FDR_0.05 = rep(FALSE, length(assay_features)),
            Moran_top_ranked = rep(FALSE, length(assay_features)),
            Moran_rank = rep(NA_integer_, length(assay_features)),
            row.names = assay_features,
            check.names = FALSE
        )

        full_feature_metadata[result_features, "MoransI_observed"] <-
            as.numeric(results[result_features, "MoransI_observed"])

        full_feature_metadata[result_features, "MoransI_p.value"] <-
            as.numeric(results[result_features, "MoransI_p.value"])

        full_feature_metadata[result_features, "Moran_FDR_BH"] <-
            as.numeric(results[result_features, "Moran_FDR_BH"])

        full_feature_metadata[result_features, "Moran_significant_FDR_0.05"] <-
            as.logical(results[result_features, "Moran_significant_FDR_0.05"])

        full_feature_metadata[result_features, "Moran_top_ranked"] <-
            as.logical(results[result_features, "Moran_top_ranked"])

        full_feature_metadata[result_features, "Moran_rank"] <-
            as.integer(results[result_features, "Moran_rank"])

        for (metadata_column in colnames(full_feature_metadata)) {
            metadata_values <- full_feature_metadata[[metadata_column]]
            names(metadata_values) <- rownames(full_feature_metadata)
            assay_object[[metadata_column]] <- metadata_values
        }

        object[[analysis_assay]] <- assay_object
        ranked_features <- rownames(results)
        ranking_statistics <- results[ranked_features, c("MoransI_observed", "MoransI_p.value", "Moran_FDR_BH", "Moran_significant_FDR_0.05", "Moran_top_ranked"), drop = FALSE]

    } else if (SELECTION_METHOD == "markvariogram") {
        object <- FindSpatiallyVariableFeatures(
            object,
            assay = analysis_assay,
            layer = "scale.data",
            features = features_to_test,
            image = image_name,
            selection.method = "markvariogram",
            x.cuts = X_CUTS,
            y.cuts = Y_CUTS,
            nfeatures = NUMBER_SPATIALLY_VARIABLE_FEATURES,
            verbose = TRUE
        )
        ranked_features <- SpatiallyVariableFeatures(
            object,
            method = "markvariogram"
        )
        mark_metadata <- tryCatch(object[[analysis_assay]][[]], error = function(e) NULL)
        mark_columns <- if (is.null(mark_metadata)) character(0) else grep("^markvariogram", colnames(mark_metadata), value = TRUE)
        if (length(mark_columns)) ranking_statistics <- mark_metadata[ranked_features, mark_columns, drop = FALSE]

    } else {
        stop('SELECTION_METHOD must be "moransi" or "markvariogram".')
    }

    safe_name <- sanitize_name(image_name)
    ranking_table <- data.frame(
        rank = seq_along(ranked_features),
        gene = ranked_features,
        image = image_name,
        method = SELECTION_METHOD,
        stringsAsFactors = FALSE
    )
    if (!is.null(ranking_statistics)) {
        ranking_table <- cbind(ranking_table, ranking_statistics[ranked_features, , drop = FALSE])
        rownames(ranking_table) <- NULL
    }
    all_rankings[[image_name]] <- ranking_table

    write.csv(
        ranking_table,
        file.path(
            OUTPUT_DIRECTORY,
            paste0("spatially_variable_genes_", safe_name, ".csv")
        ),
        row.names = FALSE
    )

    if (PLOT_TOP_SPATIALLY_VARIABLE_FEATURES) {
        top_features <- head(ranked_features, NUMBER_TOP_FEATURES_TO_PLOT)

        if (length(top_features) > 0 && !MULTIPLE_IMAGE_FILE) {
            feature_plot <- SpatialFeaturePlot(
                object,
                features = top_features,
                images = image_name,
                ncol = 3,
                alpha = c(0.1, 1),
                max.cutoff = "q95"
            )
            feature_plot <- feature_plot & ggplot2::scale_fill_gradient(
                low = SPATIAL_GENE_LOW_COLOR,
                high = SPATIAL_GENE_HIGH_COLOR
            )

            ggsave(
                file.path(
                    OUTPUT_DIRECTORY,
                    paste0("top_spatially_variable_genes_", safe_name, ".png")
                ),
                feature_plot,
                width = 15,
                height = 4 * ceiling(length(top_features) / 3),
                dpi = 300
            )
        }

        if (length(top_features) > 0 && MULTIPLE_IMAGE_FILE) {
            gene_plot_directory <- file.path(
                OUTPUT_DIRECTORY,
                paste0("top_spatially_variable_genes_", safe_name)
            )

            dir.create(
                gene_plot_directory,
                recursive = TRUE,
                showWarnings = FALSE
            )

            for (gene_name in top_features) {
                safe_gene_name <- sanitize_name(gene_name)

                feature_plot <- SpatialFeaturePlot(
                    object,
                    features = gene_name,
                    images = image_name,
                    ncol = 1,
                    alpha = c(0.1, 1),
                    max.cutoff = "q95"
                )
                feature_plot <- feature_plot + ggplot2::scale_fill_gradient(
                    low = SPATIAL_GENE_LOW_COLOR,
                    high = SPATIAL_GENE_HIGH_COLOR
                )

                ggsave(
                    filename = file.path(
                        gene_plot_directory,
                        paste0(
                            sprintf("%03d", match(gene_name, top_features)),
                            "_",
                            safe_gene_name,
                            ".png"
                        )
                    ),
                    plot = feature_plot,
                    width = 7,
                    height = 6,
                    dpi = 300
                )
            }
        }
    }
}

write.csv(
    do.call(rbind, all_rankings),
    file.path(OUTPUT_DIRECTORY, "spatially_variable_genes_all_images.csv"),
    row.names = FALSE
)

if (PLOT_USER_DEFINED_FEATURES) {
    cat("\nProcessing user-defined genes/pathways...\n")

    user_defined_file_path <- normalizePath(USER_DEFINED_PLOT_FILE, winslash = "/", mustWork = TRUE)
    definition_table <- read_user_defined_plot_file(user_defined_file_path)

    user_plot_assay <- if (toupper(USER_DEFINED_PLOT_ASSAY) == "AUTO") {
        analysis_assay
    } else {
        USER_DEFINED_PLOT_ASSAY
    }

    if (!(user_plot_assay %in% Assays(object))) {
        stop(
            "USER_DEFINED_PLOT_ASSAY '", user_plot_assay,
            "' is not present in the object. Available assays: ",
            paste(Assays(object), collapse = ", ")
        )
    }
    available_layers <- tryCatch(SeuratObject::Layers(object[[user_plot_assay]]), error = function(e) character(0))
    if (!(USER_DEFINED_PLOT_LAYER %in% available_layers)) {
        stop("USER_DEFINED_PLOT_LAYER '", USER_DEFINED_PLOT_LAYER, "' is not present in assay '", user_plot_assay, "'. Available layers: ", paste(available_layers, collapse = ", "))
    }

    object_without_custom_scores <- object
    custom_output_root <- file.path(OUTPUT_DIRECTORY, "Custom_Pathways")
    dir.create(custom_output_root, recursive = TRUE, showWarnings = FALSE)
    custom_output_summary <- list()
    output_index <- 0L

    for (combination_method in USER_DEFINED_COMBINATION_METHODS) {
        for (normalization_method in USER_DEFINED_GENE_NORMALIZATIONS) {
            output_index <- output_index + 1L
            combination_directory <- file.path(
                custom_output_root,
                paste0("Score_", sanitize_name(combination_method), "__GeneNorm_", sanitize_name(normalization_method))
            )
            dir.create(combination_directory, recursive = TRUE, showWarnings = FALSE)
            cat("Custom pathway combination ", output_index, ": ", combination_method, " + ", normalization_method, "\n", sep = "")

            build_result <- build_user_defined_scores(
                object = object_without_custom_scores,
                assay = user_plot_assay,
                layer = USER_DEFINED_PLOT_LAYER,
                definition_table = definition_table,
                output_directory = combination_directory,
                normalization_method = normalization_method,
                combination_method = combination_method
            )

            combination_object <- build_result$object
            plot_metadata <- build_result$plot_metadata
            for (image_name in image_names) {
                cat("Plotting user-defined genes/pathways for image:", image_name, "\n")
                plot_user_defined_features_for_image(
                    object = combination_object,
                    image_name = image_name,
                    plot_metadata = plot_metadata,
                    output_directory = combination_directory,
                    multiple_image_file = MULTIPLE_IMAGE_FILE
                )
            }

            custom_rds_file <- file.path(
                combination_directory,
                paste0(
                    visium_workspace_sample_name(RESULTS_WORKSPACE), "_S05_",
                    INHERITED_RDS_TAGS, "_", METHOD_OUTPUT_TAG, "_Score_", sanitize_name(combination_method),
                    "_GeneNorm_", sanitize_name(normalization_method), ".rds"
                )
            )
            saveRDS(combination_object, custom_rds_file, compress = FALSE)
            custom_output_summary[[output_index]] <- data.frame(
                combination_method = combination_method,
                gene_normalization = normalization_method,
                output_directory = combination_directory,
                output_rds = custom_rds_file,
                stringsAsFactors = FALSE
            )
        }
    }
    custom_output_summary <- do.call(rbind, custom_output_summary)
    write.csv(custom_output_summary, file.path(custom_output_root, "custom_pathway_combinations.csv"), row.names = FALSE)
    object <- object_without_custom_scores
}

DefaultAssay(object) <- if ("Spatial" %in% Assays(object)) "Spatial" else analysis_assay
object <- tryCatch(
    JoinLayers(object, assay = DefaultAssay(object)),
    error = function(e) object
)

if (DefaultAssay(object) == "Spatial") {
    object <- NormalizeData(object, assay = "Spatial", verbose = FALSE)
}

if (!"seurat_clusters" %in% colnames(object[[]])) {
    stop("The object metadata does not contain seurat_clusters.")
}

Idents(object) <- "seurat_clusters"
domain_markers <- find_domain_markers_parallel(object)

write.csv(
    domain_markers,
    file.path(OUTPUT_DIRECTORY, "spatial_domain_markers.csv"),
    row.names = FALSE
)

OUTPUT_RDS_FILE <- visium_tagged_rds_path(RESULTS_WORKSPACE, "5_Spatially_Variable_Genes", "S05", paste0(INHERITED_RDS_TAGS, "_", METHOD_OUTPUT_TAG))
saveRDS(
    object,
    OUTPUT_RDS_FILE,
    compress = FALSE
)

write.csv(
    data.frame(
        setting = c(
            "SELECTION_METHOD", "NUMBER_FEATURE_GENES_TO_TEST",
            "NUMBER_TOP_FEATURE_GENES_TO_PLOT", "NUMBER_SPATIALLY_VARIABLE_FEATURE_GENES",
            "X_CUTS", "Y_CUTS", "FUTURE_WORKERS",
            "FUTURE_GLOBALS_MAX_SIZE_GB", "HIGH_WATER_RAM_PLANNING_GB", "LOADED_OBJECT_SIZE_GB", "RANDOM_SEED",
            "DOMAIN_MARKER_MIN_PCT", "DOMAIN_MARKER_LOGFC_THRESHOLD",
            "DOMAIN_MARKER_ADJUSTED_PVALUE_THRESHOLD", "MORAN_FDR_THRESHOLD",
            "PLOT_TOP_SPATIALLY_VARIABLE_FEATURE_GENES",
            "PLOT_USER_DEFINED_FEATURE_GENES", "USER_DEFINED_PLOT_FILE",
            "USER_DEFINED_PLOT_ASSAY", "USER_DEFINED_PLOT_LAYER",
            "USER_DEFINED_COMBINATION_METHODS",
            "USER_DEFINED_GENE_NORMALIZATIONS",
            "USER_DEFINED_NORMALIZATION_LOWER_QUANTILE",
            "USER_DEFINED_NORMALIZATION_UPPER_QUANTILE",
            "USER_DEFINED_FINAL_SCORE_MIN",
            "USER_DEFINED_FINAL_SCORE_MAX",
            "USER_DEFINED_NONFINITE_AS_MINIMUM",
            "USER_DEFINED_SPOT_ALPHA"
        ),
        value = c(
            SELECTION_METHOD, NUMBER_FEATURES_TO_TEST,
            NUMBER_TOP_FEATURES_TO_PLOT, NUMBER_SPATIALLY_VARIABLE_FEATURES,
            X_CUTS, Y_CUTS, FUTURE_WORKERS,
            FUTURE_GLOBALS_MAX_SIZE_GB, estimated_peak_memory_gb, object_memory_gb, RANDOM_SEED,
            DOMAIN_MARKER_MIN_PCT, DOMAIN_MARKER_LOGFC_THRESHOLD,
            DOMAIN_MARKER_ADJUSTED_PVALUE_THRESHOLD, MORAN_FDR_THRESHOLD,
            PLOT_TOP_SPATIALLY_VARIABLE_FEATURES,
            PLOT_USER_DEFINED_FEATURES, USER_DEFINED_PLOT_FILE,
            USER_DEFINED_PLOT_ASSAY, USER_DEFINED_PLOT_LAYER,
            paste(USER_DEFINED_COMBINATION_METHODS, collapse = ","),
            paste(USER_DEFINED_GENE_NORMALIZATIONS, collapse = ","),
            USER_DEFINED_NORMALIZATION_LOWER_QUANTILE,
            USER_DEFINED_NORMALIZATION_UPPER_QUANTILE,
            USER_DEFINED_FINAL_SCORE_MIN,
            USER_DEFINED_FINAL_SCORE_MAX,
            USER_DEFINED_NONFINITE_AS_MINIMUM,
            paste(USER_DEFINED_SPOT_ALPHA, collapse = ",")
        )
    ),
    file.path(OUTPUT_DIRECTORY, "settings_used.csv"),
    row.names = FALSE
)

capture.output(
    sessionInfo(),
    file = file.path(OUTPUT_DIRECTORY, "sessionInfo.txt")
)

cat("\nSpatially variable-gene analysis completed successfully.\nOutput object: ",OUTPUT_RDS_FILE,"\n",sep="")
method_output_rds_files[[method_index]] <- OUTPUT_RDS_FILE
}

cat("\nAll selected spatial algorithms completed successfully.\nOutput objects:\n", paste(method_output_rds_files, collapse = "\n"), "\n", sep = "")
