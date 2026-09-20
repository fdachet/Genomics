#!/usr/bin/env Rscript
# ============================================================================
# SELF-CONTAINED WINDOWS R GUI
# ============================================================================
# This file contains R code only.
# It is intended to be run directly with Windows R / RStudio / Rscript.
# No Python launcher is required.
# ============================================================================

options(stringsAsFactors = FALSE)

script_file <- function() {
    a <- commandArgs(trailingOnly = FALSE)
    h <- grep("^--file=", a, value = TRUE)
    if (length(h)) {
        return(normalizePath(sub("^--file=", "", h[1]), winslash = "/", mustWork = FALSE))
    }
    return(NA_character_)
}
.sf <- script_file()
SCRIPT_DIR <- if (!is.na(.sf)) dirname(.sf) else getwd()

as_bool <- function(x) {
    toupper(trimws(as.character(x))) %in% c("TRUE", "T", "YES", "Y", "1")
}

need_tk <- function() {
    if (!requireNamespace("tcltk", quietly = TRUE)) {
        stop("R package 'tcltk' is required for this GUI. Standard Windows R normally includes it.")
    }
    suppressPackageStartupMessages(library(tcltk))
}

build_gui <- function(title, subtitle, description, fields, run_fun,
                      output_field = NULL, window = "1120x900") {
    need_tk()

    tt <- tktoplevel()
    tkwm.title(tt, title)
    tkwm.geometry(tt, window)
    tkwm.minsize(tt, 900, 720)

    vars <- list()
    widgets <- list()
    multi_options <- new.env(parent = emptyenv())

    # ---------------------------------------------------------------------
    # Header
    # ---------------------------------------------------------------------
    header <- tkframe(tt, background = "#17324D")
    tkpack(header, fill = "x")

    tkpack(
        tklabel(
            header,
            text = title,
            foreground = "white",
            background = "#17324D",
            font = "TkDefaultFont 16 bold",
            anchor = "w"
        ),
        fill = "x",
        padx = 12,
        pady = 5
    )

    tkpack(
        tklabel(
            header,
            text = subtitle,
            foreground = "#D8E7F5",
            background = "#17324D",
            anchor = "w"
        ),
        fill = "x",
        padx = 12,
        pady = 5
    )

    # ---------------------------------------------------------------------
    # Description / instructions
    # ---------------------------------------------------------------------
    desc <- tkframe(
        tt,
        background = "white",
        relief = "groove",
        borderwidth = 1
    )
    tkpack(desc, fill = "x", padx = 10, pady = 6)

    tkpack(
        tklabel(
            desc,
            text = description,
            justify = "left",
            anchor = "w",
            wraplength = 1030,
            background = "white"
        ),
        fill = "x",
        padx = 10,
        pady = 8
    )

    # ---------------------------------------------------------------------
    # Compact form: ONLY label | control | Browse
    # Long help text is intentionally NOT placed in a fourth grid column,
    # because that caused clipping on Windows / high-DPI displays.
    # ---------------------------------------------------------------------
    form_outer <- tkframe(
        tt,
        background = "white",
        relief = "groove",
        borderwidth = 1
    )
    tkpack(form_outer, fill = "x", padx = 10, pady = 4)

    form <- tkframe(form_outer, background = "white")
    tkpack(form, fill = "x", padx = 8, pady = 8)

    tkgrid.columnconfigure(form, 0, weight = 0)
    tkgrid.columnconfigure(form, 1, weight = 1)
    tkgrid.columnconfigure(form, 2, weight = 0)

    browse_file <- function(v) {
        p <- tclvalue(tkgetOpenFile())
        if (nzchar(p)) tclvalue(v) <- p
    }

    browse_dir <- function(v) {
        p <- tclvalue(tkchooseDirectory())
        if (nzchar(p)) tclvalue(v) <- p
    }

    # ---------------------------------------------------------------------
    # Multi-select popup for additional covariates
    # ---------------------------------------------------------------------
    open_multiselect <- function(name, var) {
        opts <- multi_options[[name]]
        if (is.null(opts)) opts <- character()

        win <- tktoplevel(tt)
        tkwm.title(win, "Select additional covariates")
        tkwm.geometry(win, "520x560")
        tkwm.minsize(win, 420, 420)

        tkpack(
            tklabel(
                win,
                text = paste0(
                    "Select zero or more metadata columns.\n",
                    "Use Ctrl+click to select individual columns or Shift+click for a range."
                ),
                justify = "left",
                anchor = "w"
            ),
            fill = "x",
            padx = 10,
            pady = 8
        )

        box <- tkframe(win)
        tkpack(box, fill = "both", expand = TRUE, padx = 10, pady = 5)

        lb <- tklistbox(
            box,
            selectmode = "extended",
            exportselection = FALSE,
            width = 45,
            height = 18
        )

        sb <- tkscrollbar(
            box,
            orient = "vertical",
            command = function(...) tkyview(lb, ...)
        )

        tkconfigure(
            lb,
            yscrollcommand = function(...) tkset(sb, ...)
        )

        tkpack(lb, side = "left", fill = "both", expand = TRUE)
        tkpack(sb, side = "right", fill = "y")

        for (opt in opts) tkinsert(lb, "end", opt)

        current <- trimws(tclvalue(var))
        current <- if (nzchar(current)) {
            trimws(unlist(strsplit(current, ",")))
        } else {
            character()
        }

        if (length(current) && length(opts)) {
            idx <- which(opts %in% current) - 1L
            for (i in idx) tkselection.set(lb, i)
        }

        buttons <- tkframe(win)
        tkpack(buttons, fill = "x", padx = 10, pady = 8)

        tkpack(
            tkbutton(
                buttons,
                text = "Use selected",
                command = function() {
                    sel_text <- tclvalue(tkcurselection(lb))

                    if (nzchar(sel_text)) {
                        sel <- as.integer(strsplit(sel_text, " +")[[1]])
                        chosen <- opts[sel + 1L]
                    } else {
                        chosen <- character()
                    }

                    tclvalue(var) <- paste(chosen, collapse = ", ")
                    tkdestroy(win)
                },
                background = "#2B6CB0",
                foreground = "white"
            ),
            side = "left",
            padx = 4
        )

        tkpack(
            tkbutton(
                buttons,
                text = "NONE",
                command = function() {
                    tclvalue(var) <- ""
                    tkdestroy(win)
                }
            ),
            side = "left",
            padx = 4
        )

        tkpack(
            tkbutton(
                buttons,
                text = "Cancel",
                command = function() tkdestroy(win)
            ),
            side = "left",
            padx = 4
        )
    }

    # ---------------------------------------------------------------------
    # Fields
    # ---------------------------------------------------------------------
    for (i in seq_along(fields)) {
        s <- fields[[i]]
        r <- i - 1

        v <- tclVar(as.character(s$default))
        vars[[s$name]] <- v

        tkgrid(
            tklabel(
                form,
                text = s$label,
                background = "white",
                anchor = "w",
                width = 28
            ),
            row = r,
            column = 0,
            sticky = "w",
            padx = c(4, 10),
            pady = 4
        )

        if (s$type %in% c("choice", "dynamic_choice")) {
            vals <- if (is.null(s$choices)) character() else as.character(s$choices)

            w <- ttkcombobox(
                form,
                textvariable = v,
                values = vals,
                state = "readonly",
                width = 52
            )

            widgets[[s$name]] <- w

            tkgrid(
                w,
                row = r,
                column = 1,
                columnspan = 2,
                sticky = "we",
                padx = 4,
                pady = 4
            )

        } else if (s$type == "multichoice") {
            multi_options[[s$name]] <- if (is.null(s$choices)) {
                character()
            } else {
                as.character(s$choices)
            }

            holder <- tkframe(form, background = "white")

            w <- tkentry(
                holder,
                textvariable = v,
                width = 50,
                state = "readonly"
            )

            tkpack(
                w,
                side = "left",
                fill = "x",
                expand = TRUE
            )

            tkpack(
                tkbutton(
                    holder,
                    text = "Select...",
                    command = local({
                        nm <- s$name
                        vv <- v
                        function() open_multiselect(nm, vv)
                    })
                ),
                side = "left",
                padx = 4
            )

            widgets[[s$name]] <- w

            tkgrid(
                holder,
                row = r,
                column = 1,
                columnspan = 2,
                sticky = "we",
                padx = 4,
                pady = 4
            )

        } else if (s$type == "bool") {
            w <- tkcheckbutton(
                form,
                variable = v,
                onvalue = "TRUE",
                offvalue = "FALSE",
                background = "white",
                text = ifelse(is.null(s$check_text), "", s$check_text)
            )

            widgets[[s$name]] <- w

            tkgrid(
                w,
                row = r,
                column = 1,
                columnspan = 2,
                sticky = "w",
                padx = 4,
                pady = 4
            )

        } else {
            w <- tkentry(
                form,
                textvariable = v,
                width = 66
            )

            widgets[[s$name]] <- w

            tkgrid(
                w,
                row = r,
                column = 1,
                sticky = "we",
                padx = 4,
                pady = 4
            )

            if (s$type == "file") {
                tkgrid(
                    tkbutton(
                        form,
                        text = "Browse...",
                        width = 10,
                        command = local({
                            vv <- v
                            function() browse_file(vv)
                        })
                    ),
                    row = r,
                    column = 2,
                    padx = 5,
                    pady = 4
                )
            }

            if (s$type == "dir") {
                tkgrid(
                    tkbutton(
                        form,
                        text = "Browse...",
                        width = 10,
                        command = local({
                            vv <- v
                            function() browse_dir(vv)
                        })
                    ),
                    row = r,
                    column = 2,
                    padx = 5,
                    pady = 4
                )
            }
        }
    }

    # ---------------------------------------------------------------------
    # Metadata-selection help is now BELOW the fields, not beside them.
    # ---------------------------------------------------------------------
    help_frame <- tkframe(
        tt,
        background = "#EEF4FA",
        relief = "groove",
        borderwidth = 1
    )
    tkpack(help_frame, fill = "x", padx = 10, pady = 4)

    tkpack(
        tklabel(
            help_frame,
            text = paste0(
                "Selection fields:\n",
                "• Reference Group and Comparison Group come from metadata column Group.\n",
                "• Paired-design column: select NONE for unpaired data or Patient (or another pair-ID column) for true paired samples.\n",
                "• Additional covariates: click Select... and choose zero or more metadata columns.\n",
                "• If you browse to a different metadata file, click LOAD / REFRESH DROPDOWNS."
            ),
            justify = "left",
            anchor = "w",
            wraplength = 1020,
            background = "#EEF4FA"
        ),
        fill = "x",
        padx = 10,
        pady = 7
    )

    # Dedicated row for refreshing metadata selectors so the button cannot
    # be pushed off-screen by the Run/Backup/Restore controls.
    selector_button_frame <- tkframe(tt, background = "#F3F7FB")
    tkpack(selector_button_frame, fill = "x", padx = 10, pady = 3)

    button_frame <- tkframe(tt, background = "#F3F7FB")
    tkpack(button_frame, fill = "x", padx = 10, pady = 3)

    # ---------------------------------------------------------------------
    # Log
    # ---------------------------------------------------------------------
    log_frame <- tkframe(tt, background = "#0F172A")
    tkpack(log_frame, fill = "both", expand = TRUE, padx = 10, pady = 5)

    logbox <- tktext(
        log_frame,
        background = "#0F172A",
        foreground = "#E2E8F0",
        insertbackground = "white",
        wrap = "none",
        height = 11
    )

    log_scroll <- tkscrollbar(
        log_frame,
        orient = "vertical",
        command = function(...) tkyview(logbox, ...)
    )

    tkconfigure(
        logbox,
        yscrollcommand = function(...) tkset(log_scroll, ...)
    )

    tkpack(logbox, side = "left", fill = "both", expand = TRUE)
    tkpack(log_scroll, side = "right", fill = "y")

    append_log <- function(...) {
        msg <- paste(..., collapse = "")
        tkinsert(logbox, "end", paste0(msg, "\n"))
        tksee(logbox, "end")
        tcl("update")
    }

    values <- function() {
        out <- list()
        for (nm in names(vars)) out[[nm]] <- tclvalue(vars[[nm]])
        out
    }

    backup <- function() {
        p <- tclvalue(tkgetSaveFile(defaultextension = ".rds"))
        if (!nzchar(p)) return()

        saveRDS(values(), p)

        tkmessageBox(
            title = "Backup Settings",
            message = paste("Saved:", p),
            icon = "info"
        )
    }

    restore <- function() {
        p <- tclvalue(tkgetOpenFile())
        if (!nzchar(p)) return()

        x <- readRDS(p)

        for (nm in intersect(names(x), names(vars))) {
            tclvalue(vars[[nm]]) <- as.character(x[[nm]])
        }

        tkmessageBox(
            title = "Restore Settings",
            message = paste("Restored:", p),
            icon = "info"
        )
    }

    open_output <- function() {
        if (is.null(output_field) || !(output_field %in% names(vars))) return()

        p <- tclvalue(vars[[output_field]])
        if (!nzchar(p)) return()

        dir.create(p, recursive = TRUE, showWarnings = FALSE)

        if (.Platform$OS.type == "windows") {
            shell.exec(
                normalizePath(p, winslash = "\\", mustWork = FALSE)
            )
        } else {
            system2("xdg-open", shQuote(p), wait = FALSE)
        }
    }

    run_callback <- function() {
        tryCatch({
            append_log("=== RUN START ===")

            result <- run_fun(
                values(),
                append_log
            )

            append_log("=== RUN COMPLETE ===")

            tkmessageBox(
                title = title,
                message = ifelse(is.null(result), "Complete", result),
                icon = "info"
            )

        }, error = function(e) {
            append_log("ERROR: ", conditionMessage(e))

            tkmessageBox(
                title = paste(title, "— Error"),
                message = conditionMessage(e),
                icon = "error"
            )
        })
    }

    # Analysis buttons remain on a separate line from LOAD / REFRESH.
    tkpack(
        tkbutton(
            button_frame,
            text = "RUN THIS STEP",
            command = run_callback,
            background = "#2B6CB0",
            foreground = "white"
        ),
        side = "left",
        padx = 3
    )

    tkpack(
        tkbutton(
            button_frame,
            text = "Backup Settings",
            command = backup,
            background = "#157A75",
            foreground = "white"
        ),
        side = "left",
        padx = 3
    )

    tkpack(
        tkbutton(
            button_frame,
            text = "Restore Settings",
            command = restore,
            background = "#2F855A",
            foreground = "white"
        ),
        side = "left",
        padx = 3
    )

    if (!is.null(output_field)) {
        tkpack(
            tkbutton(
                button_frame,
                text = "Open Output Folder",
                command = open_output,
                background = "#C05621",
                foreground = "white"
            ),
            side = "left",
            padx = 3
        )
    }

    tkpack(
        tkbutton(
            button_frame,
            text = "Clear Log",
            command = function() tkdelete(logbox, "1.0", "end")
        ),
        side = "left",
        padx = 3
    )

    invisible(
        list(
            window = tt,
            vars = vars,
            widgets = widgets,
            values = values,
            log = append_log,
            button_frame = button_frame,
            selector_button_frame = selector_button_frame,
            multi_options = multi_options,
            run = run_callback
        )
    )
}


EPIC_ROOT <- dirname(SCRIPT_DIR)
PREV <- file.path(EPIC_ROOT, "Step_04_Matrices", "Step_04_Output")
DEFAULT_OUT <- file.path(SCRIPT_DIR, "Step_07_Output")
dir.create(DEFAULT_OUT, recursive = TRUE, showWarnings = FALSE)

parse_covariates <- function(x) {
    x <- trimws(x)
    if (!nzchar(x)) return(character())
    unique(trimws(unlist(strsplit(x, ","))))
}

prepare_design <- function(md, ref, cmp, patient_col, covariates, log) {
    if (!("Group" %in% colnames(md))) {
        stop("Metadata are missing the mandatory Group column.")
    }

    available_groups <- sort(unique(trimws(as.character(md$Group))))
    available_groups <- available_groups[nzchar(available_groups)]

    if (!(ref %in% available_groups)) {
        stop(
            "Reference Group '", ref, "' was not found in the metadata.\n",
            "Available Group values: ", paste(available_groups, collapse = ", ")
        )
    }

    if (!(cmp %in% available_groups)) {
        stop(
            "Comparison Group '", cmp, "' was not found in the metadata.\n",
            "Available Group values: ", paste(available_groups, collapse = ", ")
        )
    }

    md <- md[md$Group %in% c(ref, cmp), , drop = FALSE]
    md$Group <- trimws(as.character(md$Group))

    group_counts <- table(md$Group)
    log(
        "Selected groups: ",
        ref, " n=", unname(group_counts[ref]),
        " ; ",
        cmp, " n=", unname(group_counts[cmp])
    )

    if (sum(md$Group == ref) < 1 || sum(md$Group == cmp) < 1) {
        stop("Both reference and comparison groups must contain at least one sample.")
    }

    md$group <- factor(md$Group, levels = c(ref, cmp))
    if (nlevels(droplevels(md$group)) < 2) {
        stop(
            "The Group factor has fewer than 2 levels after sample filtering.\n",
            "Reference = ", ref, "; Comparison = ", cmp
        )
    }

    terms <- character()
    paired <- nzchar(patient_col) && toupper(patient_col) != "NONE"

    if (paired) {
        if (!(patient_col %in% colnames(md))) {
            stop(
                "Paired-design column '", patient_col, "' is not present in metadata.\n",
                "For unpaired data enter NONE in the Paired-design column field."
            )
        }

        patient_values <- trimws(as.character(md[[patient_col]]))

        if (any(is.na(patient_values) | !nzchar(patient_values))) {
            stop(
                "Paired analysis was requested using column '", patient_col,
                "', but one or more selected samples have a blank Patient value.\n",
                "If these data are unpaired, enter NONE in the Paired-design column field."
            )
        }

        patient_factor <- droplevels(factor(patient_values))

        if (nlevels(patient_factor) < 2) {
            stop(
                "Paired analysis requires at least 2 different patient IDs, but only ",
                nlevels(patient_factor), " was found.\n",
                "For unpaired data enter NONE."
            )
        }

        # For a strict paired tumor/control-style comparison, each patient should
        # contribute both selected Group levels. Stop instead of silently dropping data.
        pairing_table <- table(patient_values, md$Group)
        incomplete <- rownames(pairing_table)[
            rowSums(pairing_table[, c(ref, cmp), drop = FALSE] > 0) < 2
        ]

        if (length(incomplete)) {
            stop(
                "Incomplete pairing detected. These Patient IDs do not contain both '",
                ref, "' and '", cmp, "':\n  ",
                paste(incomplete, collapse = ", "),
                "\nCorrect the experimental plan or use NONE for an unpaired analysis."
            )
        }

        md$patient_model <- patient_factor
        terms <- c(terms, "patient_model")
        log("Paired design: ", nlevels(patient_factor), " patient pairs.")
    } else {
        log("Unpaired design selected.")
    }

    # Remove accidental duplicates and reserved design variables.
    covariates <- unique(covariates[nzchar(covariates)])
    covariates <- setdiff(covariates, c("Group", patient_col))

    used_covariates <- character()
    skipped_covariates <- character()

    for (cv in covariates) {
        if (!(cv %in% colnames(md))) {
            stop("Covariate column missing from metadata: ", cv)
        }

        raw <- md[[cv]]

        if (any(is.na(raw) | trimws(as.character(raw)) == "")) {
            stop(
                "Covariate '", cv,
                "' contains missing/blank values in the selected samples."
            )
        }

        unique_values <- unique(as.character(raw))

        # Constant variables cannot be used in a regression design.
        if (length(unique_values) < 2) {
            log(
                "Skipping covariate '", cv,
                "' because it has only one value: ", unique_values[1]
            )
            skipped_covariates <- c(skipped_covariates, cv)
            next
        }

        # With Patient as a fixed effect, a covariate that never changes within
        # any patient is fully confounded with Patient (e.g. Sex, baseline Age,
        # or a Batch that is identical for both members of every pair).
        if (paired) {
            pv <- as.character(md[[patient_col]])
            values_per_patient <- tapply(
                as.character(raw),
                pv,
                function(x) length(unique(x))
            )

            if (all(values_per_patient <= 1)) {
                log(
                    "Skipping covariate '", cv,
                    "' because it is constant within every patient and is therefore ",
                    "confounded with the Patient fixed effect."
                )
                skipped_covariates <- c(skipped_covariates, cv)
                next
            }
        }

        if (is.character(raw) || is.logical(raw) || is.factor(raw)) {
            md[[cv]] <- droplevels(factor(raw))

            if (nlevels(md[[cv]]) < 2) {
                log(
                    "Skipping covariate '", cv,
                    "' because it has fewer than 2 factor levels."
                )
                skipped_covariates <- c(skipped_covariates, cv)
                next
            }
        } else if (is.numeric(raw) || is.integer(raw)) {
            if (length(unique(as.numeric(raw))) < 2) {
                log(
                    "Skipping covariate '", cv,
                    "' because it has no variation."
                )
                skipped_covariates <- c(skipped_covariates, cv)
                next
            }
        }

        used_covariates <- c(used_covariates, cv)
        terms <- c(terms, paste0("`", cv, "`"))
    }

    if (length(used_covariates)) {
        log("Covariates used: ", paste(used_covariates, collapse = ", "))
    } else {
        log("Additional covariates used: NONE")
    }

    if (length(skipped_covariates)) {
        log(
            "Covariates skipped as constant/confounded: ",
            paste(skipped_covariates, collapse = ", ")
        )
    }

    rhs <- paste(c(terms, "group"), collapse = " + ")
    log("Statistical model: ~ ", rhs)

    design <- tryCatch(
        model.matrix(as.formula(paste("~", rhs)), data = md),
        error = function(e) {
            stop(
                "Could not construct the statistical design matrix.\n",
                "Original R error: ", conditionMessage(e), "\n\n",
                "This usually means a factor has fewer than 2 levels after filtering."
            )
        }
    )

    if (qr(design)$rank < ncol(design)) {
        stop(
            "The design matrix is rank deficient after validation.\n",
            "Model columns: ", paste(colnames(design), collapse = ", "), "\n\n",
            "Remove redundant/confounded covariates. In a paired fixed-effect model, ",
            "patient-level variables such as Sex or a baseline Age are usually already ",
            "represented by Patient and should not be added separately."
        )
    }

    list(
        md = md,
        design = design,
        used_covariates = used_covariates,
        skipped_covariates = skipped_covariates
    )
}


prepare_bioconductor_hub_caches <- function(cache_root, log) {
    cache_root <- trimws(as.character(cache_root))

    if (!nzchar(cache_root)) {
        cache_root <- "C:/Temp/Methylation_BiocCache"
    }

    cache_root <- gsub("\\\\", "/", cache_root)

    if (!dir.exists(cache_root)) {
        ok <- dir.create(
            cache_root,
            recursive = TRUE,
            showWarnings = FALSE
        )

        if (!ok && !dir.exists(cache_root)) {
            stop(
                "Could not create the Bioconductor cache root:\n",
                cache_root,
                "\nCheck Windows folder permissions."
            )
        }
    }

    experiment_cache <- file.path(
        cache_root,
        "ExperimentHub"
    )

    annotation_cache <- file.path(
        cache_root,
        "AnnotationHub"
    )

    caches <- c(
        ExperimentHub = experiment_cache,
        AnnotationHub = annotation_cache
    )

    for (nm in names(caches)) {
        p <- caches[[nm]]

        if (!dir.exists(p)) {
            ok <- dir.create(
                p,
                recursive = TRUE,
                showWarnings = FALSE
            )

            if (!ok && !dir.exists(p)) {
                stop(
                    "Could not create the ",
                    nm,
                    " cache directory:\n",
                    p,
                    "\nCheck Windows folder permissions."
                )
            }
        }

        test_file <- file.path(
            p,
            paste0(".methylation_pipeline_write_test_", Sys.getpid())
        )

        writable <- tryCatch({
            writeLines("test", test_file, useBytes = TRUE)
            unlink(test_file)
            TRUE
        }, error = function(e) {
            FALSE
        })

        if (!writable) {
            stop(
                nm,
                " cache directory is not writable:\n",
                p
            )
        }
    }

    # Set cache locations BEFORE DMRcate / Hub namespaces are loaded.
    options(
        EXPERIMENT_HUB_CACHE = experiment_cache,
        ANNOTATION_HUB_CACHE = annotation_cache
    )

    Sys.setenv(
        EXPERIMENT_HUB_CACHE = experiment_cache,
        ANNOTATION_HUB_CACHE = annotation_cache
    )

    log("Bioconductor cache root: ", cache_root)
    log("ExperimentHub cache: ", experiment_cache)
    log("AnnotationHub cache: ", annotation_cache)
    log(
        "These are ordinary folders under C:/Temp and can be deleted manually ",
        "when Step 07 is not running. Required resources will be downloaded again ",
        "on the next run if the cache is removed."
    )

    invisible(
        list(
            Root = cache_root,
            ExperimentHub = experiment_cache,
            AnnotationHub = annotation_cache
        )
    )
}

run_step <- function(v, log) {
    M <- readRDS(normalizePath(v$m_matrix, mustWork = TRUE))
    meta <- read.csv(
        normalizePath(v$metadata, mustWork = TRUE),
        stringsAsFactors = FALSE,
        check.names = FALSE
    )

    outdir <- v$out_dir
    dir.create(outdir, recursive = TRUE, showWarnings = FALSE)

    ver <- v$array_version
    ref <- trimws(v$reference)
    cmp <- trimws(v$comparison)

    if (!nzchar(ref) || !nzchar(cmp) || ref == cmp) {
        stop("Reference and comparison groups must both be selected and must differ.")
    }

    patient_col <- trimws(v$patient_column)
    covariates <- parse_covariates(v$covariates)

    lambda <- as.numeric(v$lambda)
    C <- as.numeric(v$C)
    fdr <- as.numeric(v$fdr)

    if (!is.finite(lambda) || lambda <= 0) {
        stop("DMRcate lambda must be a positive number.")
    }

    if (!is.finite(C) || C <= 0) {
        stop("DMRcate C must be a positive number.")
    }

    if (!is.finite(fdr) || fdr <= 0 || fdr >= 1) {
        stop("FDR threshold must be between 0 and 1.")
    }

    # DMRcate can access annotation resources through ExperimentHub.
    # Prepare the Hub cache FIRST so Windows R never pauses for an
    # interactive yes/no cache-directory question.
    prepare_bioconductor_hub_caches(v$cache_root, log)

    if (!requireNamespace("DMRcate", quietly = TRUE) ||
        !requireNamespace("limma", quietly = TRUE)) {
        stop("Required R packages DMRcate and/or limma are not installed.")
    }

    suppressPackageStartupMessages(library(DMRcate))
    suppressPackageStartupMessages(library(limma))

    if (!("Sample_Name" %in% colnames(meta))) {
        stop("metadata_matrices.csv is missing mandatory column: Sample_Name")
    }

    if (!("Group" %in% colnames(meta))) {
        stop("metadata_matrices.csv is missing mandatory column: Group")
    }

    if (anyDuplicated(meta$Sample_Name)) {
        stop("metadata_matrices.csv contains duplicated Sample_Name values.")
    }

    common_samples <- intersect(colnames(M), as.character(meta$Sample_Name))

    if (length(common_samples) < 2) {
        stop(
            "Fewer than 2 samples are shared by M_value_matrix.rds and ",
            "metadata_matrices.csv."
        )
    }

    md <- meta[match(common_samples, meta$Sample_Name), , drop = FALSE]
    M2 <- M[, md$Sample_Name, drop = FALSE]

    # Same robust design validation used in Step 06.
    pd <- prepare_design(
        md,
        ref,
        cmp,
        patient_col,
        covariates,
        log
    )

    md <- pd$md
    design <- pd$design

    # Keep only the exact samples retained by the design.
    M2 <- M2[, md$Sample_Name, drop = FALSE]

    if (ncol(M2) != nrow(design)) {
        stop(
            "Internal sample/design mismatch: methylation matrix has ",
            ncol(M2),
            " samples but the design matrix has ",
            nrow(design),
            " rows."
        )
    }

    coef <- grep("^group", colnames(design), value = TRUE)

    if (length(coef) != 1) {
        stop(
            "Could not identify the Group coefficient in the design matrix.\n",
            "Design columns: ",
            paste(colnames(design), collapse = ", ")
        )
    }

    # DMRcate >= current Bioconductor releases expects the explicit
    # arraytype names "EPICv1" or "EPICv2".
    arraytype <- if (ver == "EPICv2") "EPICv2" else "EPICv1"
    genome <- if (ver == "EPICv2") "hg38" else "hg19"

    # Probe-ID sanity check before cpg.annotate().
    # Canonical EPICv1 IDs are typically cg######## (10 characters).
    # EPICv2 contains replicated probe IDs such as cg########_TC21
    # (15 characters).  Do not silently change the user's selection;
    # stop with a clear message if the matrix strongly contradicts it.
    probe_ids <- rownames(M2)
    cg_ids <- probe_ids[grepl("^cg", probe_ids)]

    if (length(cg_ids)) {
        prop_len10 <- mean(nchar(cg_ids) == 10)
        prop_len15 <- mean(nchar(cg_ids) == 15)

        log(
            "Probe-ID check: ",
            round(100 * prop_len10, 1), "% length-10; ",
            round(100 * prop_len15, 1), "% length-15 among cg probes."
        )

        if (arraytype == "EPICv1" && prop_len15 > 0.50) {
            stop(
                "Array version is set to EPICv1, but most cg probe IDs look like ",
                "EPICv2 replicated IDs (for example cg00000029_TC21). ",
                "Select EPICv2 in the Array version dropdown."
            )
        }

        if (arraytype == "EPICv2" && prop_len10 > 0.90 && prop_len15 < 0.05) {
            stop(
                "Array version is set to EPICv2, but the probe IDs look like ",
                "EPICv1 IDs (for example cg00000029). ",
                "Select EPICv1 in the Array version dropdown."
            )
        }
    }

    log("DMRcate arraytype: ", arraytype)
    log("Genome: ", genome)
    log("Reference group: ", ref)
    log("Comparison group: ", cmp)
    log("Model matrix columns: ", paste(colnames(design), collapse = ", "))
    log("DMRcate lambda: ", lambda)
    log("DMRcate C: ", C)
    log("FDR threshold: ", fdr)

    ca <- cpg.annotate(
        datatype = "array",
        object = M2,
        what = "M",
        analysis.type = "differential",
        design = design,
        coef = coef,
        arraytype = arraytype,
        fdr = fdr
    )

    saveRDS(
        ca,
        file.path(outdir, "DMRcate_CpG_annotation.rds")
    )

    dm <- dmrcate(
        ca,
        lambda = lambda,
        C = C,
        pcutoff = fdr
    )

    saveRDS(
        dm,
        file.path(outdir, "DMRcate_results.rds")
    )

    gr <- extractRanges(
        dm,
        genome = genome
    )

    tab <- as.data.frame(gr)

    write.table(
        tab,
        file.path(outdir, "DMR_significant.tsv"),
        sep = "\t",
        quote = FALSE,
        row.names = FALSE
    )

    # Write the selected analysis design for reproducibility.
    design_out <- data.frame(
        Sample_Name = md$Sample_Name,
        Group = md$Group,
        design,
        check.names = FALSE
    )

    write.table(
        design_out,
        file.path(outdir, "DMR_design_matrix.tsv"),
        sep = "\t",
        quote = FALSE,
        row.names = FALSE
    )

    if (nrow(tab)) {
        png(
            file.path(outdir, "01_DMR_width_distribution.png"),
            width = 1100,
            height = 800,
            res = 150
        )

        hist(
            tab$width,
            breaks = 50,
            xlab = "DMR width (bp)",
            main = paste0(
                "DMR widths: ",
                cmp,
                " vs ",
                ref
            )
        )

        dev.off()
    }

    paste0(
        "DMR analysis complete.\n",
        "Reference: ", ref, "\n",
        "Comparison: ", cmp, "\n",
        "DMRs: ", nrow(tab)
    )
}

fields <- list(
    list(
        name = "m_matrix",
        label = "Step 04 M_value_matrix.rds",
        type = "file",
        default = file.path(PREV, "M_value_matrix.rds")
    ),

    list(
        name = "metadata",
        label = "Step 04 metadata_matrices.csv",
        type = "file",
        default = file.path(PREV, "metadata_matrices.csv"),
        help = "After choosing another metadata file, click LOAD / REFRESH DROPDOWNS."
    ),

    list(
        name = "array_version",
        label = "Array version",
        type = "choice",
        default = "EPICv1",
        choices = c("EPICv1", "EPICv2"),
        help = "EPICv1 uses standard 10-character cg probe IDs and hg19 in DMRcate; EPICv2 supports replicated IDs such as cg00000029_TC21 and uses hg38."
    ),

    list(
        name = "reference",
        label = "Reference Group",
        type = "dynamic_choice",
        default = "",
        help = "Dropdown is populated from unique values in metadata column Group."
    ),

    list(
        name = "comparison",
        label = "Comparison Group",
        type = "dynamic_choice",
        default = "",
        help = "Dropdown is populated from unique values in metadata column Group."
    ),

    list(
        name = "patient_column",
        label = "Paired-design column",
        type = "dynamic_choice",
        default = "NONE",
        help = "Select NONE for unpaired data or choose the metadata column containing patient/pair IDs."
    ),

    list(
        name = "covariates",
        label = "Additional covariates",
        type = "multichoice",
        default = "",
        help = "Click Select... and choose zero or more metadata columns."
    ),

    list(
        name = "lambda",
        label = "DMRcate lambda",
        type = "text",
        default = "1000"
    ),

    list(
        name = "C",
        label = "DMRcate C",
        type = "text",
        default = "2"
    ),

    list(
        name = "fdr",
        label = "FDR threshold",
        type = "text",
        default = "0.05"
    ),

    list(
        name = "cache_root",
        label = "Bioconductor cache folder",
        type = "dir",
        default = "C:/Temp/Methylation_BiocCache",
        help = "ExperimentHub and AnnotationHub will cache under this folder. You may delete the cache later to reclaim disk space."
    ),

    list(
        name = "out_dir",
        label = "Step 07 output folder",
        type = "dir",
        default = DEFAULT_OUT
    )
)

refresh_metadata_dropdowns <- function(gui, show_message = TRUE) {
    tryCatch({
        p <- trimws(tclvalue(gui$vars$metadata))

        if (!nzchar(p) || !file.exists(p)) {
            stop("Select a valid metadata_matrices.csv file first.")
        }

        md <- read.csv(
            normalizePath(p, winslash = "/", mustWork = TRUE),
            stringsAsFactors = FALSE,
            check.names = FALSE
        )

        required <- c("Sample_Name", "Group")
        missing <- setdiff(required, colnames(md))
        if (length(missing)) {
            stop("Metadata are missing: ", paste(missing, collapse = ", "))
        }

        groups <- sort(unique(trimws(as.character(md$Group))))
        groups <- groups[nzchar(groups)]

        if (length(groups) < 2) {
            stop(
                "The metadata contain fewer than two non-empty Group values.\n",
                "Found: ", paste(groups, collapse = ", ")
            )
        }

        tkconfigure(gui$widgets$reference, values = groups)
        tkconfigure(gui$widgets$comparison, values = groups)

        current_ref <- trimws(tclvalue(gui$vars$reference))
        current_cmp <- trimws(tclvalue(gui$vars$comparison))

        # Prefer common reference-like biological labels when present.
        preferred_ref <- c(
            "Normal", "Control", "Healthy", "Untreated",
            "Reference", "WT", "PrEC"
        )
        pref <- preferred_ref[preferred_ref %in% groups]

        if (!(current_ref %in% groups)) {
            current_ref <- if (length(pref)) pref[1] else groups[1]
            tclvalue(gui$vars$reference) <- current_ref
        }

        if (!(current_cmp %in% groups) || current_cmp == current_ref) {
            other <- setdiff(groups, current_ref)
            tclvalue(gui$vars$comparison) <- other[1]
        }

        reserved <- c(
            "Sample_Name", "Group", "IDAT_Basename", "Basename",
            "Internal_ID", "Original_Red_IDAT", "Original_Green_IDAT"
        )

        metadata_columns <- setdiff(colnames(md), reserved)

        # Put the common pair column first if it exists.
        if ("Patient" %in% metadata_columns) {
            pair_choices <- c("NONE", "Patient", setdiff(sort(metadata_columns), "Patient"))
        } else {
            pair_choices <- c("NONE", sort(metadata_columns))
        }

        tkconfigure(gui$widgets$patient_column, values = pair_choices)

        current_pair <- trimws(tclvalue(gui$vars$patient_column))
        if (!(current_pair %in% pair_choices)) {
            tclvalue(gui$vars$patient_column) <- "NONE"
        }

        gui$multi_options$covariates <- sort(metadata_columns)

        current_cov <- trimws(tclvalue(gui$vars$covariates))
        if (nzchar(current_cov)) {
            current_cov <- trimws(unlist(strsplit(current_cov, ",")))
            current_cov <- current_cov[current_cov %in% metadata_columns]
            tclvalue(gui$vars$covariates) <- paste(current_cov, collapse = ",")
        }

        gui$log(
            "Metadata dropdowns loaded. Groups: ",
            paste(groups, collapse = ", ")
        )
        gui$log(
            "Pair/covariate columns available: ",
            if (length(metadata_columns)) paste(metadata_columns, collapse = ", ") else "NONE"
        )

        if (show_message) {
            tkmessageBox(
                title = "Metadata dropdowns",
                message = paste0(
                    "Loaded ", length(groups), " groups and ",
                    length(metadata_columns), " metadata columns."
                ),
                icon = "info"
            )
        }

        invisible(TRUE)

    }, error = function(e) {
        if (show_message) {
            tkmessageBox(
                title = "Metadata dropdowns — Error",
                message = conditionMessage(e),
                icon = "error"
            )
        }
        invisible(FALSE)
    })
}

gui <- build_gui(
    "EPIC — Step 07",
    "Differentially methylated regions (DMRcate)",
    paste0(
        "Runs DMRcate directly in Windows R. ",
        "Reference Group, Comparison Group, pairing column, and additional ",
        "covariates are selected from metadata_matrices.csv using the same ",
        "dropdown / multi-select controls as Step 06. Bioconductor ",
        "ExperimentHub/AnnotationHub cache folders are created under the selected ",
        "C:/Temp cache root so the analysis remains non-interactive and the cache ",
        "is easy to locate and delete."
    ),
    fields,
    run_step,
    output_field = "out_dir"
)

tkpack(
    tkbutton(
        gui$selector_button_frame,
        text = "LOAD / REFRESH DROPDOWNS",
        command = function() refresh_metadata_dropdowns(gui, TRUE),
        background = "#C05621",
        foreground = "white"
    ),
    side = "left",
    padx = 3
)

tkpack(
    tklabel(
        gui$selector_button_frame,
        text = "Use this after selecting a different metadata_matrices.csv file.",
        background = "#F3F7FB",
        foreground = "#5E6B78"
    ),
    side = "left",
    padx = 8
)

# Populate selectors automatically when the default metadata file exists.
refresh_metadata_dropdowns(gui, FALSE)

tkwait.window(gui$window)
