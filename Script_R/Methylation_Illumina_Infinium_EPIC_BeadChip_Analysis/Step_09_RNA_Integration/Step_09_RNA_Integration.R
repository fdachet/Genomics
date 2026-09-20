
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
    # Optional per-field help
    #
    # Keep help available, but do NOT consume permanent vertical space.
    # It is shown on demand from a Help button in the control row.
    # ---------------------------------------------------------------------
    help_lines <- character()

    for (s in fields) {
        if (!is.null(s$help) && nzchar(s$help)) {
            help_lines <- c(
                help_lines,
                paste0("• ", s$label, ": ", s$help)
            )
        }
    }

    show_help <- function() {
        msg <- if (length(help_lines)) {
            paste(help_lines, collapse = "\n\n")
        } else {
            "No additional field-specific help is defined for this step."
        }

        tkmessageBox(
            title = paste(title, "— Help"),
            message = msg,
            icon = "info"
        )
    }

    # ---------------------------------------------------------------------
    # Controls are placed immediately below the input form so they remain
    # visible even on Windows systems using display scaling.
    # ---------------------------------------------------------------------
    # Dedicated row for refreshing metadata selectors so the button cannot
    # be pushed off-screen by the Run/Backup/Restore controls.
    selector_button_frame <- tkframe(tt, background = "#F3F7FB")
    tkpack(selector_button_frame, fill = "x", padx = 10, pady = 3)

    button_frame <- tkframe(tt, background = "#F3F7FB")
    tkpack(button_frame, fill = "x", padx = 10, pady = 3)

    # ---------------------------------------------------------------------
    # Log frame
    #
    # Controls above reserve their space first. The log is the only
    # expandable region and consumes only the remaining vertical space.
    # ---------------------------------------------------------------------
    log_frame <- tkframe(
        tt,
        background = "#0F172A",
        relief = "groove",
        borderwidth = 1
    )

    logbox <- tktext(
        log_frame,
        background = "#0F172A",
        foreground = "#E2E8F0",
        insertbackground = "white",
        wrap = "none",
        height = 8
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

    tkpack(
        logbox,
        side = "left",
        fill = "both",
        expand = TRUE
    )

    tkpack(
        log_scroll,
        side = "right",
        fill = "y"
    )

    tkpack(
        log_frame,
        fill = "both",
        expand = TRUE,
        padx = 10,
        pady = 5
    )

    append_log <- function(...) {
        msg <- paste(..., collapse = "")

        # Internal progress messages:
        #   @@PROGRESS|35.0|Integrating DMP genes...
        #
        # Display progress ONLY in the scrollable log. No progress widget
        # is added to the GUI, so progress cannot cover or displace buttons.
        m <- regexec(
            "^@@PROGRESS\\|([0-9]+(?:\\.[0-9]+)?)\\|(.*)$",
            msg,
            perl = TRUE
        )
        hit <- regmatches(msg, m)[[1]]

        if (length(hit) == 3) {
            pct <- suppressWarnings(as.numeric(hit[2]))
            task <- trimws(hit[3])

            if (!is.finite(pct)) pct <- 0
            pct <- min(100, max(0, pct))

            display_msg <- paste0(
                "[",
                sprintf("%5.1f%%", pct),
                "] ",
                task
            )
        } else {
            display_msg <- msg
        }

        if (nzchar(display_msg)) {
            tkinsert(
                logbox,
                "end",
                paste0(display_msg, "\n")
            )
            tksee(logbox, "end")
        }

        tcl("update", "idletasks")
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
            append_log("@@PROGRESS|0|Starting Step 09...")

            result <- run_fun(
                values(),
                append_log
            )

            append_log("@@PROGRESS|100|Step 09 complete.")
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


    tkpack(
        tkbutton(
            button_frame,
            text = "Help",
            command = show_help,
            background = "#5E6B78",
            foreground = "white"
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




progress_log <- function(log, percent, message) {
    percent <- suppressWarnings(as.numeric(percent))
    if (!is.finite(percent)) percent <- 0
    percent <- min(100, max(0, percent))

    log(
        paste0(
            "@@PROGRESS|",
            sprintf("%.1f", percent),
            "|",
            message
        )
    )
}

read_table_auto <- function(path) {
    path <- normalizePath(path, winslash = "/", mustWork = TRUE)
    first <- readLines(path, n = 1, warn = FALSE)
    if (!length(first)) stop("Input table is empty: ", path)

    if (grepl("\t", first, fixed = TRUE)) {
        return(read.delim(
            path, header = TRUE, sep = "\t", stringsAsFactors = FALSE,
            check.names = FALSE, quote = "", comment.char = ""
        ))
    }

    if (grepl(",", first, fixed = TRUE)) {
        return(read.csv(
            path, header = TRUE, stringsAsFactors = FALSE,
            check.names = FALSE, quote = "\"", comment.char = ""
        ))
    }

    read.table(
        path, header = TRUE, sep = "", stringsAsFactors = FALSE,
        check.names = FALSE, quote = "", comment.char = ""
    )
}

write_tsv <- function(x, path) {
    write.table(
        x, path, sep = "\t", quote = FALSE,
        row.names = FALSE, na = ""
    )
}

clean_gene_tokens <- function(x) {
    x <- as.character(x)
    x[is.na(x)] <- ""
    x <- gsub("\\|", ";", x)
    x <- gsub("/", ";", x, fixed = TRUE)
    x
}

split_genes <- function(x) {
    x <- clean_gene_tokens(x)
    out <- unlist(strsplit(x, "[;,]"), use.names = FALSE)
    out <- trimws(out)
    unique(out[nzchar(out) & out != "."])
}

first_existing <- function(nms, candidates) {
    hit <- candidates[candidates %in% nms]
    if (length(hit)) hit[1] else NA_character_
}

first_regex <- function(nms, pattern, exclude = NULL) {
    hit <- grep(pattern, nms, ignore.case = TRUE, value = TRUE)
    if (!is.null(exclude) && length(hit)) {
        hit <- hit[!grepl(exclude, hit, ignore.case = TRUE)]
    }
    if (length(hit)) hit[1] else NA_character_
}

safe_numeric <- function(x) {
    suppressWarnings(as.numeric(as.character(x)))
}

normalize_chr <- function(x) {
    x <- as.character(x)
    x[is.na(x)] <- ""
    x <- trimws(x)

    idx <- nzchar(x) & !grepl("^chr", x, ignore.case = TRUE)
    if (any(idx)) {
        x[idx] <- paste0("chr", x[idx])
    }

    x
}

is_promoter_relation <- function(x) {
    grepl(
        "TSS200|TSS1500|1stExon|5['’]?UTR|promoter",
        as.character(x),
        ignore.case = TRUE
    )
}

safe_min <- function(x) {
    x <- safe_numeric(x)
    x <- x[is.finite(x)]
    if (!length(x)) NA_real_ else min(x)
}

safe_max_abs <- function(x) {
    x <- safe_numeric(x)
    x <- x[is.finite(x)]
    if (!length(x)) NA_real_ else max(abs(x))
}

safe_mean <- function(x) {
    x <- safe_numeric(x)
    x <- x[is.finite(x)]
    if (!length(x)) NA_real_ else mean(x)
}

EPIC_ROOT <- dirname(SCRIPT_DIR)
PREV4 <- file.path(EPIC_ROOT, "Step_04_Matrices", "Step_04_Output")
PREV8 <- file.path(EPIC_ROOT, "Step_08_Functional_Annotation", "Step_08_Output")
DEFAULT_OUT <- file.path(SCRIPT_DIR, "Step_09_Output")
dir.create(DEFAULT_OUT, recursive = TRUE, showWarnings = FALSE)

make_rna_de_unique <- function(
    rna,
    gene_col,
    logfc_col,
    fdr_col,
    pvalue_col = "NONE"
) {
    if (!(gene_col %in% colnames(rna))) {
        stop("RNA gene column is missing: ", gene_col)
    }
    if (!(logfc_col %in% colnames(rna))) {
        stop("RNA logFC column is missing: ", logfc_col)
    }
    if (!(fdr_col %in% colnames(rna))) {
        stop("RNA FDR column is missing: ", fdr_col)
    }

    pval <- rep(NA_real_, nrow(rna))
    if (
        nzchar(pvalue_col) &&
        toupper(pvalue_col) != "NONE" &&
        pvalue_col %in% colnames(rna)
    ) {
        pval <- safe_numeric(rna[[pvalue_col]])
    }

    out <- data.frame(
        Gene = trimws(as.character(rna[[gene_col]])),
        RNA_logFC = safe_numeric(rna[[logfc_col]]),
        RNA_P_value = pval,
        RNA_FDR = safe_numeric(rna[[fdr_col]]),
        stringsAsFactors = FALSE
    )

    out <- out[nzchar(out$Gene), , drop = FALSE]
    out$Gene_Key <- toupper(out$Gene)

    # A row is considered to contain an actual RNA DE result only when at
    # least one DE statistic is finite. Placeholder rows created by this GUI
    # therefore remain explicitly "not analyzed", rather than being treated
    # as nonsignificant results.
    out$RNA_DE_Available <- (
        is.finite(out$RNA_logFC) |
        is.finite(out$RNA_P_value) |
        is.finite(out$RNA_FDR)
    )

    ord <- order(
        ifelse(is.finite(out$RNA_FDR), out$RNA_FDR, Inf),
        -abs(ifelse(is.finite(out$RNA_logFC), out$RNA_logFC, 0))
    )

    out <- out[ord, , drop = FALSE]
    out <- out[!duplicated(out$Gene_Key), , drop = FALSE]
    out
}

explode_methylation_genes <- function(
    df,
    source,
    log = NULL,
    progress_start = 0,
    progress_end = 100
) {
    if (!nrow(df) || !("Gene_Symbols" %in% colnames(df))) {
        if (!is.null(log)) {
            progress_log(
                log,
                progress_end,
                paste0(
                    source,
                    ": no Gene_Symbols rows to expand."
                )
            )
        }
        return(data.frame())
    }

    n <- nrow(df)

    # About 20 chunks gives the user regular progress updates while avoiding
    # one data.frame allocation per methylation row.
    chunk_size <- max(
        2000L,
        ceiling(n / 20)
    )

    starts <- seq.int(
        1L,
        n,
        by = chunk_size
    )

    pieces <- vector(
        "list",
        length(starts)
    )

    for (k in seq_along(starts)) {
        a <- starts[k]
        b <- min(
            n,
            a + chunk_size - 1L
        )

        raw <- clean_gene_tokens(
            df$Gene_Symbols[a:b]
        )
        raw[is.na(raw)] <- ""

        gene_lists <- strsplit(
            raw,
            "[;,]",
            perl = TRUE
        )

        gene_lists <- lapply(
            gene_lists,
            function(z) {
                z <- trimws(z)
                z <- z[
                    nzchar(z) &
                    z != "." &
                    !is.na(z)
                ]
                unique(z)
            }
        )

        counts <- lengths(gene_lists)
        keep <- counts > 0

        if (any(keep)) {
            original_rows <- seq.int(a, b)

            piece <- data.frame(
                Methylation_Row = rep.int(
                    original_rows[keep],
                    counts[keep]
                ),
                Gene = unlist(
                    gene_lists[keep],
                    use.names = FALSE
                ),
                stringsAsFactors = FALSE
            )

            piece$Gene_Key <- toupper(
                piece$Gene
            )
            piece$Evidence_Source <- source

            pieces[[k]] <- piece
        }

        frac <- k / length(starts)
        pct <- progress_start +
            frac * (progress_end - progress_start)

        if (!is.null(log)) {
            progress_log(
                log,
                pct,
                paste0(
                    source,
                    ": expanding methylation gene annotations — rows ",
                    format(b, big.mark = ","),
                    " / ",
                    format(n, big.mark = ",")
                )
            )
        }
    }

    pieces <- Filter(
        Negate(is.null),
        pieces
    )

    if (!length(pieces)) {
        return(data.frame())
    }

    out <- do.call(
        rbind,
        pieces
    )

    rownames(out) <- NULL

    if (!is.null(log)) {
        log(
            source,
            " gene expansion produced ",
            format(nrow(out), big.mark = ","),
            " methylation-to-gene associations."
        )
    }

    out
}

integrate_one <- function(
    meth,
    rna_unique,
    source,
    log = NULL,
    progress_start = 0,
    progress_end = 100
) {
    expansion_end <- progress_start +
        0.70 * (progress_end - progress_start)

    ex <- explode_methylation_genes(
        meth,
        source,
        log,
        progress_start,
        expansion_end
    )

    if (!nrow(ex)) {
        if (!is.null(log)) {
            progress_log(
                log,
                progress_end,
                paste0(
                    source,
                    ": no gene associations to integrate."
                )
            )
        }
        return(data.frame())
    }

    if (!is.null(log)) {
        progress_log(
            log,
            expansion_end + 0.05 * (progress_end - progress_start),
            paste0(
                source,
                ": matching ",
                format(nrow(ex), big.mark = ","),
                " gene associations to the RNA table..."
            )
        )
    }

    # rna_unique has one row per Gene_Key. match() is faster and preserves
    # order better than a large all.x merge().
    m <- match(
        ex$Gene_Key,
        rna_unique$Gene_Key
    )

    ex$RNA_logFC <- rna_unique$RNA_logFC[m]
    ex$RNA_P_value <- rna_unique$RNA_P_value[m]
    ex$RNA_FDR <- rna_unique$RNA_FDR[m]
    ex$RNA_DE_Available <- rna_unique$RNA_DE_Available[m]

    if (!is.null(log)) {
        progress_log(
            log,
            expansion_end + 0.15 * (progress_end - progress_start),
            paste0(
                source,
                ": attaching original methylation statistics..."
            )
        )
    }

    meth_rows <- meth[
        ex$Methylation_Row,
        ,
        drop = FALSE
    ]

    out <- cbind(
        ex,
        meth_rows
    )

    if (!is.null(log)) {
        progress_log(
            log,
            progress_end,
            paste0(
                source,
                ": methylation/RNA gene matching complete — ",
                format(nrow(out), big.mark = ","),
                " integrated rows."
            )
        )
    }

    out
}

choose_effect_column <- function(df, source) {
    if (source == "DMP") {
        if ("Delta_Beta" %in% colnames(df)) return("Delta_Beta")
    }

    first_existing(
        colnames(df),
        c(
            "meandiff",
            "Mean_Delta_Beta_From_All_DMPs",
            "Mean_Delta_Beta",
            "maxdiff"
        )
    )
}

add_biological_priority <- function(df, source, rna_fdr_cut, rna_fc_cut, meth_cut) {
    if (!nrow(df)) return(df)

    eff_col <- choose_effect_column(df, source)
    eff <- if (!is.na(eff_col)) safe_numeric(df[[eff_col]]) else rep(NA_real_, nrow(df))

    promoter <- if ("Promoter_Associated" %in% colnames(df)) {
        as.logical(df$Promoter_Associated)
    } else if ("Gene_Relation" %in% colnames(df)) {
        is_promoter_relation(df$Gene_Relation)
    } else {
        rep(FALSE, nrow(df))
    }

    rna_available <- if ("RNA_DE_Available" %in% colnames(df)) {
        as.logical(df$RNA_DE_Available)
    } else {
        (
            is.finite(df$RNA_logFC) |
            is.finite(df$RNA_FDR)
        )
    }

    rna_sig <- rna_available &
        is.finite(df$RNA_FDR) &
        df$RNA_FDR <= rna_fdr_cut &
        is.finite(df$RNA_logFC) &
        abs(df$RNA_logFC) >= rna_fc_cut

    meth_strong <- is.finite(eff) & abs(eff) >= meth_cut

    inverse_promoter <- promoter & rna_sig & meth_strong &
        (
            (eff > 0 & df$RNA_logFC < 0) |
            (eff < 0 & df$RNA_logFC > 0)
        )

    df$Methylation_Effect_Used <- eff
    df$RNA_DE_Available <- rna_available
    df$RNA_Significant <- rna_sig
    df$Promoter_Associated_Standard <- promoter
    df$Inverse_Promoter_RNA_Pattern <- inverse_promoter

    df$Integrated_Interpretation <- ifelse(
        !rna_available,
        "RNA differential-expression result unavailable (NA placeholder)",
        ifelse(
            inverse_promoter & eff > 0,
            "HIGH: promoter hypermethylation + RNA down",
            ifelse(
                inverse_promoter & eff < 0,
                "HIGH: promoter hypomethylation + RNA up",
                ifelse(
                    rna_sig & meth_strong,
                    "RNA and methylation both significant; regulatory direction needs context",
                    ifelse(
                        rna_sig,
                        "RNA significant; methylation effect below selected threshold",
                        "RNA DE result available but not significant at selected thresholds"
                    )
                )
            )
        )
    )

    df
}

aggregate_candidates <- function(
    dmp_int,
    dmr_int,
    rna_unique,
    rna_fdr_cut,
    log = NULL,
    progress_start = 0,
    progress_end = 100
) {
    genes <- sort(
        unique(
            c(
                if (nrow(dmp_int)) dmp_int$Gene else character(),
                if (nrow(dmr_int)) dmr_int$Gene else character()
            )
        )
    )

    genes <- genes[
        nzchar(genes) &
        !is.na(genes)
    ]

    if (!length(genes)) {
        if (!is.null(log)) {
            progress_log(
                log,
                progress_end,
                "No integrated genes were available for candidate ranking."
            )
        }
        return(data.frame())
    }

    if (!is.null(log)) {
        progress_log(
            log,
            progress_start,
            paste0(
                "Building candidate ranking for ",
                format(length(genes), big.mark = ","),
                " unique genes..."
            )
        )
    }

    # -------------------------
    # DMP grouped summaries
    # -------------------------
    dmp_count <- setNames(
        integer(length(genes)),
        genes
    )
    dmp_best_fdr <- setNames(
        rep(NA_real_, length(genes)),
        genes
    )
    dmp_max_abs <- setNames(
        rep(NA_real_, length(genes)),
        genes
    )
    dmp_inverse <- setNames(
        rep(FALSE, length(genes)),
        genes
    )

    if (nrow(dmp_int)) {
        groups <- split(
            seq_len(nrow(dmp_int)),
            dmp_int$Gene
        )

        nms <- names(groups)

        dmp_count[nms] <- lengths(groups)

        dmp_best_fdr[nms] <- vapply(
            groups,
            function(ix) {
                if (!("adj.P.Val" %in% colnames(dmp_int))) {
                    return(NA_real_)
                }
                safe_min(
                    dmp_int$adj.P.Val[ix]
                )
            },
            numeric(1)
        )

        dmp_max_abs[nms] <- vapply(
            groups,
            function(ix) {
                if (!("Delta_Beta" %in% colnames(dmp_int))) {
                    return(NA_real_)
                }
                safe_max_abs(
                    dmp_int$Delta_Beta[ix]
                )
            },
            numeric(1)
        )

        if ("Inverse_Promoter_RNA_Pattern" %in% colnames(dmp_int)) {
            dmp_inverse[nms] <- vapply(
                groups,
                function(ix) {
                    any(
                        dmp_int$Inverse_Promoter_RNA_Pattern[ix] %in% TRUE,
                        na.rm = TRUE
                    )
                },
                logical(1)
            )
        }
    }

    if (!is.null(log)) {
        progress_log(
            log,
            progress_start + 0.35 * (progress_end - progress_start),
            "DMP evidence grouped by gene."
        )
    }

    # -------------------------
    # DMR grouped summaries
    # -------------------------
    dmr_count <- setNames(
        integer(length(genes)),
        genes
    )
    dmr_inverse <- setNames(
        rep(FALSE, length(genes)),
        genes
    )

    if (nrow(dmr_int)) {
        groups <- split(
            seq_len(nrow(dmr_int)),
            dmr_int$Gene
        )

        nms <- names(groups)
        dmr_count[nms] <- lengths(groups)

        if ("Inverse_Promoter_RNA_Pattern" %in% colnames(dmr_int)) {
            dmr_inverse[nms] <- vapply(
                groups,
                function(ix) {
                    any(
                        dmr_int$Inverse_Promoter_RNA_Pattern[ix] %in% TRUE,
                        na.rm = TRUE
                    )
                },
                logical(1)
            )
        }
    }

    if (!is.null(log)) {
        progress_log(
            log,
            progress_start + 0.60 * (progress_end - progress_start),
            "DMR evidence grouped by gene."
        )
    }

    # RNA lookup is one match per unique gene.
    rna_m <- match(
        toupper(genes),
        rna_unique$Gene_Key
    )

    rna_fc <- rna_unique$RNA_logFC[rna_m]
    rna_p <- rna_unique$RNA_P_value[rna_m]
    rna_fdr <- rna_unique$RNA_FDR[rna_m]

    rna_available <- rep(
        FALSE,
        length(genes)
    )

    ok <- !is.na(rna_m)
    rna_available[ok] <- rna_unique$RNA_DE_Available[
        rna_m[ok]
    ] %in% TRUE

    rna_sig <- rna_available &
        is.finite(rna_fdr) &
        rna_fdr <= rna_fdr_cut

    promoter_inverse <- unname(
        dmp_inverse[genes] |
        dmr_inverse[genes]
    )

    score <- integer(
        length(genes)
    )

    score <- score +
        ifelse(promoter_inverse, 4L, 0L) +
        ifelse(rna_sig, 2L, 0L) +
        ifelse(unname(dmr_count[genes]) > 0L, 2L, 0L) +
        ifelse(unname(dmp_count[genes]) >= 2L, 1L, 0L) +
        ifelse(
            is.finite(unname(dmp_max_abs[genes])) &
            unname(dmp_max_abs[genes]) >= 0.20,
            1L,
            0L
        )

    level <- ifelse(
        score >= 6,
        "HIGH",
        ifelse(
            score >= 3,
            "MEDIUM",
            "LOW"
        )
    )

    ans <- data.frame(
        Gene = genes,
        DMP_Evidence_Count = unname(dmp_count[genes]),
        DMR_Evidence_Count = unname(dmr_count[genes]),
        Best_DMP_FDR = unname(dmp_best_fdr[genes]),
        MaxAbs_DMP_Delta_Beta = unname(dmp_max_abs[genes]),
        RNA_logFC = rna_fc,
        RNA_P_value = rna_p,
        RNA_FDR = rna_fdr,
        RNA_DE_Available = rna_available,
        Inverse_Promoter_RNA_Pattern = promoter_inverse,
        Priority_Score = score,
        Priority_Level = level,
        stringsAsFactors = FALSE
    )

    ans <- ans[
        order(
            -ans$Priority_Score,
            ans$RNA_FDR,
            ans$Best_DMP_FDR,
            na.last = TRUE
        ),
        ,
        drop = FALSE
    ]

    rownames(ans) <- NULL

    if (!is.null(log)) {
        progress_log(
            log,
            progress_end,
            paste0(
                "Candidate ranking complete — ",
                format(nrow(ans), big.mark = ","),
                " genes."
            )
        )
    }

    ans
}

prepare_expression_matrix <- function(path, gene_col) {
    x <- read_table_auto(path)
    if (!(gene_col %in% colnames(x))) {
        stop("RNA expression gene column not found: ", gene_col)
    }

    genes <- trimws(as.character(x[[gene_col]]))
    sample_cols <- setdiff(colnames(x), gene_col)

    if (!length(sample_cols)) {
        stop("RNA expression matrix contains no sample columns.")
    }

    mat <- as.matrix(x[, sample_cols, drop = FALSE])
    storage.mode(mat) <- "double"

    good <- nzchar(genes)
    genes <- genes[good]
    mat <- mat[good, , drop = FALSE]

    # Average duplicate gene rows.
    keys <- toupper(genes)
    sums <- rowsum(mat, group = keys, reorder = FALSE, na.rm = TRUE)
    counts <- rowsum(!is.na(mat), group = keys, reorder = FALSE)
    avg <- sums / pmax(counts, 1)

    avg
}

run_correlations <- function(dmp_int, beta, expr, meta, ref, cmp, patient_col, max_pairs, log, progress_start = 88, progress_end = 95) {
    if (!nrow(dmp_int)) return(list(sample = data.frame(), paired = data.frame()))

    if (!("Probe_ID" %in% colnames(dmp_int))) {
        log("Matched correlation skipped: integrated DMP table has no Probe_ID.")
        return(list(sample = data.frame(), paired = data.frame()))
    }

    common_samples <- intersect(colnames(beta), colnames(expr))

    if (length(common_samples) < 3) {
        log(
            "Matched correlation skipped: fewer than 3 shared sample names between ",
            "beta matrix and RNA expression matrix."
        )
        return(list(sample = data.frame(), paired = data.frame()))
    }

    log("Shared methylation/RNA sample names: ", length(common_samples))

    ord <- seq_len(nrow(dmp_int))
    if ("adj.P.Val" %in% colnames(dmp_int)) {
        ord <- order(
            ifelse(is.finite(safe_numeric(dmp_int$adj.P.Val)), safe_numeric(dmp_int$adj.P.Val), Inf),
            ifelse(is.finite(dmp_int$RNA_FDR), dmp_int$RNA_FDR, Inf)
        )
    }

    dmp_int <- dmp_int[ord, , drop = FALSE]
    dmp_int <- dmp_int[
        !duplicated(paste(dmp_int$Probe_ID, dmp_int$Gene_Key, sep = "|")),
        ,
        drop = FALSE
    ]

    dmp_int <- head(dmp_int, max_pairs)

    sample_rows <- list()
    paired_rows <- list()

    do_paired <- !is.null(meta) &&
        nzchar(patient_col) &&
        toupper(patient_col) != "NONE" &&
        nzchar(ref) &&
        nzchar(cmp) &&
        all(c("Sample_Name", "Group", patient_col) %in% colnames(meta))

    progress_every <- max(
        1L,
        floor(nrow(dmp_int) / 20L)
    )

    for (i in seq_len(nrow(dmp_int))) {
        if (
            i == 1L ||
            i == nrow(dmp_int) ||
            (i %% progress_every) == 0L
        ) {
            pct <- progress_start +
                (i / nrow(dmp_int)) *
                (progress_end - progress_start)

            progress_log(
                log,
                pct,
                paste0(
                    "Matched methylation/RNA correlations — ",
                    format(i, big.mark = ","),
                    " / ",
                    format(nrow(dmp_int), big.mark = ","),
                    " DMP-gene pairs"
                )
            )
        }

        probe <- as.character(dmp_int$Probe_ID[i])
        gene_key <- toupper(as.character(dmp_int$Gene[i]))

        if (!(probe %in% rownames(beta)) || !(gene_key %in% rownames(expr))) next

        b <- safe_numeric(beta[probe, common_samples])
        e <- safe_numeric(expr[gene_key, common_samples])

        ok <- is.finite(b) & is.finite(e)
        if (sum(ok) >= 3 && stats::sd(b[ok]) > 0 && stats::sd(e[ok]) > 0) {
            pear <- tryCatch(cor.test(b[ok], e[ok], method = "pearson"), error = function(e) NULL)
            spear <- tryCatch(cor.test(b[ok], e[ok], method = "spearman", exact = FALSE), error = function(e) NULL)

            sample_rows[[length(sample_rows) + 1L]] <- data.frame(
                Probe_ID = probe,
                Gene = as.character(dmp_int$Gene[i]),
                N_Samples = sum(ok),
                Pearson_r = if (!is.null(pear)) unname(pear$estimate) else NA_real_,
                Pearson_P = if (!is.null(pear)) pear$p.value else NA_real_,
                Spearman_rho = if (!is.null(spear)) unname(spear$estimate) else NA_real_,
                Spearman_P = if (!is.null(spear)) spear$p.value else NA_real_,
                stringsAsFactors = FALSE
            )
        }

        if (do_paired) {
            md <- meta[
                meta$Sample_Name %in% common_samples &
                meta$Group %in% c(ref, cmp),
                ,
                drop = FALSE
            ]

            patients <- unique(trimws(as.character(md[[patient_col]])))
            patients <- patients[nzchar(patients)]

            db <- numeric()
            de <- numeric()

            for (pat in patients) {
                q <- md[trimws(as.character(md[[patient_col]])) == pat, , drop = FALSE]
                sr <- q$Sample_Name[q$Group == ref]
                sc <- q$Sample_Name[q$Group == cmp]

                if (length(sr) != 1 || length(sc) != 1) next
                if (!all(c(sr, sc) %in% common_samples)) next

                vb <- safe_numeric(beta[probe, c(sr, sc)])
                ve <- safe_numeric(expr[gene_key, c(sr, sc)])

                if (all(is.finite(vb)) && all(is.finite(ve))) {
                    db <- c(db, vb[2] - vb[1])
                    de <- c(de, ve[2] - ve[1])
                }
            }

            if (length(db) >= 3 && sd(db) > 0 && sd(de) > 0) {
                pear_d <- tryCatch(cor.test(db, de, method = "pearson"), error = function(e) NULL)
                spear_d <- tryCatch(cor.test(db, de, method = "spearman", exact = FALSE), error = function(e) NULL)

                paired_rows[[length(paired_rows) + 1L]] <- data.frame(
                    Probe_ID = probe,
                    Gene = as.character(dmp_int$Gene[i]),
                    N_Pairs = length(db),
                    DeltaBeta_vs_DeltaExpression_Pearson_r =
                        if (!is.null(pear_d)) unname(pear_d$estimate) else NA_real_,
                    Pearson_P = if (!is.null(pear_d)) pear_d$p.value else NA_real_,
                    DeltaBeta_vs_DeltaExpression_Spearman_rho =
                        if (!is.null(spear_d)) unname(spear_d$estimate) else NA_real_,
                    Spearman_P = if (!is.null(spear_d)) spear_d$p.value else NA_real_,
                    stringsAsFactors = FALSE
                )
            }
        }
    }

    sample_df <- if (length(sample_rows)) do.call(rbind, sample_rows) else data.frame()
    paired_df <- if (length(paired_rows)) do.call(rbind, paired_rows) else data.frame()

    if (nrow(sample_df)) {
        sample_df$Pearson_FDR <- p.adjust(sample_df$Pearson_P, method = "BH")
        sample_df$Spearman_FDR <- p.adjust(sample_df$Spearman_P, method = "BH")
    }

    if (nrow(paired_df)) {
        paired_df$Pearson_FDR <- p.adjust(paired_df$Pearson_P, method = "BH")
        paired_df$Spearman_FDR <- p.adjust(paired_df$Spearman_P, method = "BH")
    }

    list(sample = sample_df, paired = paired_df)
}

run_step <- function(v, log) {
    outdir <- v$out_dir

    progress_log(
        log,
        1,
        "Preparing Step 09 output folder..."
    )

    dir.create(
        outdir,
        recursive = TRUE,
        showWarnings = FALSE
    )

    progress_log(
        log,
        4,
        "Reading Step 08 annotated DMP table..."
    )
    dmp <- read_table_auto(
        v$dmp_annotated
    )
    log(
        "DMP annotated rows loaded: ",
        format(nrow(dmp), big.mark = ",")
    )

    progress_log(
        log,
        10,
        "Reading Step 08 annotated DMR table..."
    )
    dmr <- read_table_auto(
        v$dmr_annotated
    )
    log(
        "DMR annotated rows loaded: ",
        format(nrow(dmr), big.mark = ",")
    )

    progress_log(
        log,
        16,
        "Reading RNA differential-expression table..."
    )
    rna <- read_table_auto(
        v$rna_de
    )
    log(
        "RNA table rows loaded: ",
        format(nrow(rna), big.mark = ",")
    )

    gene_col <- trimws(v$rna_gene_col)
    logfc_col <- trimws(v$rna_logfc_col)
    fdr_col <- trimws(v$rna_fdr_col)

    if (
        !nzchar(gene_col) ||
        !nzchar(logfc_col) ||
        !nzchar(fdr_col)
    ) {
        stop(
            "Use LOAD / REFRESH RNA + METADATA DROPDOWNS and select RNA gene/logFC/FDR columns."
        )
    }

    pvalue_col <- trimws(
        v$rna_pvalue_col
    )

    progress_log(
        log,
        20,
        "Standardizing RNA gene identifiers and DE columns..."
    )

    rna_unique <- make_rna_de_unique(
        rna,
        gene_col,
        logfc_col,
        fdr_col,
        pvalue_col
    )

    log(
        "Unique RNA gene keys: ",
        format(nrow(rna_unique), big.mark = ",")
    )
    log(
        "RNA genes with any DE statistic available: ",
        format(
            sum(
                rna_unique$RNA_DE_Available %in% TRUE,
                na.rm = TRUE
            ),
            big.mark = ","
        )
    )

    rna_fdr_cut <- as.numeric(
        v$rna_fdr
    )
    rna_fc_cut <- as.numeric(
        v$rna_abs_logfc
    )
    meth_cut <- as.numeric(
        v$methyl_abs_effect
    )
    max_corr <- suppressWarnings(
        as.integer(
            v$max_correlation_pairs
        )
    )

    if (
        !is.finite(rna_fdr_cut) ||
        rna_fdr_cut <= 0 ||
        rna_fdr_cut >= 1
    ) {
        stop(
            "RNA FDR threshold must be between 0 and 1."
        )
    }

    if (
        !is.finite(rna_fc_cut) ||
        rna_fc_cut < 0
    ) {
        stop(
            "Minimum absolute RNA logFC must be >= 0."
        )
    }

    if (
        !is.finite(meth_cut) ||
        meth_cut < 0
    ) {
        stop(
            "Minimum absolute methylation effect must be >= 0."
        )
    }

    if (
        !is.finite(max_corr) ||
        max_corr < 1
    ) {
        stop(
            "Maximum correlation pairs must be a positive integer."
        )
    }

    # ------------------------------------------------------------------
    # DMP -> RNA gene integration
    # ------------------------------------------------------------------
    progress_log(
        log,
        23,
        "Starting DMP-to-RNA gene integration..."
    )

    dmp_int <- integrate_one(
        dmp,
        rna_unique,
        "DMP",
        log,
        23,
        45
    )

    # ------------------------------------------------------------------
    # DMR -> RNA gene integration
    # ------------------------------------------------------------------
    progress_log(
        log,
        46,
        "Starting DMR-to-RNA gene integration..."
    )

    dmr_int <- integrate_one(
        dmr,
        rna_unique,
        "DMR",
        log,
        46,
        62
    )

    # ------------------------------------------------------------------
    # Biological priority flags
    # ------------------------------------------------------------------
    progress_log(
        log,
        64,
        "Calculating methylation/RNA biological-priority flags..."
    )

    dmp_int <- add_biological_priority(
        dmp_int,
        "DMP",
        rna_fdr_cut,
        rna_fc_cut,
        meth_cut
    )

    dmr_int <- add_biological_priority(
        dmr_int,
        "DMR",
        rna_fdr_cut,
        rna_fc_cut,
        meth_cut
    )

    # ------------------------------------------------------------------
    # Write large integrated tables
    # ------------------------------------------------------------------
    progress_log(
        log,
        67,
        "Writing DMP_RNA_integrated.tsv..."
    )
    write_tsv(
        dmp_int,
        file.path(
            outdir,
            "DMP_RNA_integrated.tsv"
        )
    )

    progress_log(
        log,
        70,
        "Writing DMR_RNA_integrated.tsv..."
    )
    write_tsv(
        dmr_int,
        file.path(
            outdir,
            "DMR_RNA_integrated.tsv"
        )
    )

    # ------------------------------------------------------------------
    # Candidate ranking
    # ------------------------------------------------------------------
    candidates <- aggregate_candidates(
        dmp_int,
        dmr_int,
        rna_unique,
        rna_fdr_cut,
        log,
        72,
        82
    )

    progress_log(
        log,
        83,
        "Writing integrated_candidate_genes.tsv..."
    )
    write_tsv(
        candidates,
        file.path(
            outdir,
            "integrated_candidate_genes.tsv"
        )
    )

    # ------------------------------------------------------------------
    # Optional matched sample-level correlation
    # ------------------------------------------------------------------
    corr_result <- list(
        sample = data.frame(),
        paired = data.frame()
    )

    expr_path <- trimws(
        v$rna_expression
    )
    beta_path <- trimws(
        v$beta_matrix
    )

    if (
        nzchar(expr_path) &&
        nzchar(beta_path)
    ) {
        expr_gene_col <- trimws(
            v$expression_gene_col
        )

        if (!nzchar(expr_gene_col)) {
            stop(
                "RNA expression matrix was provided but no expression gene column was selected."
            )
        }

        progress_log(
            log,
            85,
            "Reading normalized RNA expression matrix..."
        )

        expr <- prepare_expression_matrix(
            expr_path,
            expr_gene_col
        )

        progress_log(
            log,
            87,
            "Reading Step 04 beta matrix for matched correlations..."
        )

        beta <- readRDS(
            normalizePath(
                beta_path,
                winslash = "/",
                mustWork = TRUE
            )
        )
        beta <- as.matrix(beta)
        storage.mode(beta) <- "double"

        meta <- NULL
        meta_path <- trimws(
            v$metadata
        )

        if (
            nzchar(meta_path) &&
            file.exists(meta_path)
        ) {
            meta <- read.csv(
                normalizePath(
                    meta_path,
                    winslash = "/",
                    mustWork = TRUE
                ),
                stringsAsFactors = FALSE,
                check.names = FALSE
            )
        }

        corr_result <- run_correlations(
            dmp_int,
            beta,
            expr,
            meta,
            trimws(v$reference),
            trimws(v$comparison),
            trimws(v$patient_column),
            max_corr,
            log,
            88,
            94
        )

        progress_log(
            log,
            95,
            "Writing matched correlation tables..."
        )

        write_tsv(
            corr_result$sample,
            file.path(
                outdir,
                "DMP_gene_sample_correlations.tsv"
            )
        )

        write_tsv(
            corr_result$paired,
            file.path(
                outdir,
                "DMP_gene_paired_delta_correlations.tsv"
            )
        )
    } else {
        progress_log(
            log,
            94,
            paste0(
                "Matched sample-level correlation skipped — ",
                "provide both beta_matrix.rds and a normalized RNA expression matrix to enable it."
            )
        )
    }

    # ------------------------------------------------------------------
    # Plots
    # ------------------------------------------------------------------
    progress_log(
        log,
        96,
        "Creating integrated candidate plots..."
    )

    if (nrow(candidates)) {
        top <- head(
            candidates,
            30
        )

        png(
            file.path(
                outdir,
                "01_top_integrated_candidates.png"
            ),
            width = 1400,
            height = 950,
            res = 150
        )

        par(
            mar = c(
                5,
                12,
                4,
                2
            )
        )

        barplot(
            rev(
                top$Priority_Score
            ),
            names.arg = rev(
                top$Gene
            ),
            horiz = TRUE,
            las = 1,
            xlab = "Integrated priority score",
            main = "Top methylation + RNA candidate genes"
        )

        dev.off()
    }

    hi <- if (nrow(dmp_int)) {
        dmp_int[
            dmp_int$Inverse_Promoter_RNA_Pattern %in% TRUE &
            is.finite(
                dmp_int$Methylation_Effect_Used
            ) &
            is.finite(
                dmp_int$RNA_logFC
            ),
            ,
            drop = FALSE
        ]
    } else {
        data.frame()
    }

    if (nrow(hi)) {
        png(
            file.path(
                outdir,
                "02_promoter_methylation_vs_RNA_logFC.png"
            ),
            width = 1100,
            height = 850,
            res = 150
        )

        plot(
            hi$Methylation_Effect_Used,
            hi$RNA_logFC,
            pch = 16,
            xlab = "Methylation effect (comparison - reference)",
            ylab = "RNA log fold-change",
            main = "High-priority promoter methylation / RNA patterns"
        )

        abline(
            h = 0,
            v = 0,
            lty = 2
        )

        grid()
        dev.off()
    }

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    progress_log(
        log,
        98,
        "Writing Step 09 integration summary..."
    )

    summary_lines <- c(
        paste(
            "RNA table genes:",
            nrow(rna_unique)
        ),
        paste(
            "RNA genes with any DE statistic available:",
            sum(
                rna_unique$RNA_DE_Available %in% TRUE,
                na.rm = TRUE
            )
        ),
        paste(
            "RNA placeholder genes with DE statistics unavailable:",
            sum(
                !(rna_unique$RNA_DE_Available %in% TRUE),
                na.rm = TRUE
            )
        ),
        paste(
            "DMP-gene/RNA integrated rows:",
            nrow(dmp_int)
        ),
        paste(
            "DMR-gene/RNA integrated rows:",
            nrow(dmr_int)
        ),
        paste(
            "Prioritized unique genes:",
            nrow(candidates)
        ),
        paste(
            "HIGH priority genes:",
            if (nrow(candidates)) {
                sum(
                    candidates$Priority_Level == "HIGH"
                )
            } else {
                0
            }
        ),
        paste(
            "Sample-level correlation rows:",
            nrow(corr_result$sample)
        ),
        paste(
            "Paired delta-correlation rows:",
            nrow(corr_result$paired)
        )
    )

    writeLines(
        summary_lines,
        file.path(
            outdir,
            "integration_summary.txt"
        )
    )

    progress_log(
        log,
        99.5,
        "Finalizing Step 09 outputs..."
    )

    paste0(
        "Methylation / RNA integration complete.\\n",
        "Prioritized genes: ",
        nrow(candidates),
        "\\n",
        "HIGH priority genes: ",
        if (nrow(candidates)) {
            sum(
                candidates$Priority_Level == "HIGH"
            )
        } else {
            0
        },
        "\\nResults:\\n",
        outdir
    )
}

fields <- list(
    list(
        name = "dmp_annotated",
        label = "Step 08 DMP annotated",
        type = "file",
        default = file.path(PREV8, "DMP_annotated_significant.tsv")
    ),
    list(
        name = "dmr_annotated",
        label = "Step 08 DMR annotated",
        type = "file",
        default = file.path(PREV8, "DMR_annotated_significant.tsv")
    ),
    list(
        name = "rna_de",
        label = "RNA-seq differential-expression table",
        type = "file",
        default = ""
    ),
    list(
        name = "rna_gene_col",
        label = "RNA gene-symbol column",
        type = "dynamic_choice",
        default = ""
    ),
    list(
        name = "rna_logfc_col",
        label = "RNA log fold-change column",
        type = "dynamic_choice",
        default = ""
    ),
    list(
        name = "rna_fdr_col",
        label = "RNA FDR / adjusted-P column",
        type = "dynamic_choice",
        default = ""
    ),
    list(
        name = "rna_pvalue_col",
        label = "RNA raw P-value column (optional)",
        type = "dynamic_choice",
        default = "NONE"
    ),
    list(
        name = "rna_fdr",
        label = "RNA FDR threshold",
        type = "text",
        default = "0.05"
    ),
    list(
        name = "rna_abs_logfc",
        label = "Minimum absolute RNA logFC",
        type = "text",
        default = "0.5"
    ),
    list(
        name = "methyl_abs_effect",
        label = "Minimum absolute methylation effect",
        type = "text",
        default = "0.10"
    ),
    list(
        name = "rna_expression",
        label = "Normalized RNA expression matrix (optional)",
        type = "file",
        default = ""
    ),
    list(
        name = "expression_gene_col",
        label = "Expression matrix gene column",
        type = "dynamic_choice",
        default = ""
    ),
    list(
        name = "beta_matrix",
        label = "Step 04 beta_matrix.rds (optional)",
        type = "file",
        default = file.path(PREV4, "beta_matrix.rds")
    ),
    list(
        name = "metadata",
        label = "Step 04 metadata_matrices.csv (optional)",
        type = "file",
        default = file.path(PREV4, "metadata_matrices.csv")
    ),
    list(
        name = "reference",
        label = "Reference Group for paired Δ analysis",
        type = "dynamic_choice",
        default = ""
    ),
    list(
        name = "comparison",
        label = "Comparison Group for paired Δ analysis",
        type = "dynamic_choice",
        default = ""
    ),
    list(
        name = "patient_column",
        label = "Patient/pair column for paired Δ analysis",
        type = "dynamic_choice",
        default = "NONE"
    ),
    list(
        name = "max_correlation_pairs",
        label = "Maximum DMP-gene pairs for correlation",
        type = "text",
        default = "500"
    ),
    list(
        name = "out_dir",
        label = "Step 09 output folder",
        type = "dir",
        default = DEFAULT_OUT
    )
)



extract_genes_from_step08_summary <- function(
    annotated_path,
    summary_filename,
    label,
    log = NULL
) {
    annotated_path <- trimws(as.character(annotated_path))

    if (!nzchar(annotated_path)) {
        return(character())
    }

    summary_path <- file.path(
        dirname(annotated_path),
        summary_filename
    )

    # Prefer the small gene-level summary produced by Step 08.
    if (file.exists(summary_path)) {
        if (!is.null(log)) {
            log(
                "Reading fast Step 08 gene summary: ",
                summary_path
            )
        }

        x <- read_table_auto(summary_path)

        gene_col <- first_existing(
            colnames(x),
            c("Gene", "Gene_Symbol", "GeneSymbol", "SYMBOL")
        )

        if (!is.na(gene_col)) {
            genes <- trimws(as.character(x[[gene_col]]))
            genes <- unique(
                genes[
                    nzchar(genes) &
                    !is.na(genes) &
                    genes != "."
                ]
            )

            if (!is.null(log)) {
                log(
                    label,
                    " summary contributed ",
                    length(genes),
                    " unique genes."
                )
            }

            return(genes)
        }

        if (!is.null(log)) {
            log(
                "WARNING: ",
                summary_path,
                " has no recognizable Gene column; falling back to the annotated table."
            )
        }
    } else if (!is.null(log)) {
        log(
            "Step 08 summary not found: ",
            summary_path,
            " — falling back to the annotated table."
        )
    }

    extract_genes_from_step08(
        annotated_path,
        label,
        log
    )
}

extract_genes_from_step08 <- function(path, label, log = NULL) {
    if (!nzchar(path) || !file.exists(path)) {
        if (!is.null(log)) {
            log(label, " file not found; skipping it for RNA template creation.")
        }
        return(character())
    }

    x <- read_table_auto(path)

    if (!("Gene_Symbols" %in% colnames(x))) {
        if (!is.null(log)) {
            log(
                label,
                " does not contain Gene_Symbols; skipping it for RNA template creation."
            )
        }
        return(character())
    }

    genes <- unique(
        unlist(
            lapply(x$Gene_Symbols, split_genes),
            use.names = FALSE
        )
    )

    genes <- trimws(as.character(genes))
    genes <- genes[nzchar(genes) & !is.na(genes)]

    if (!is.null(log)) {
        log(label, " contributed ", length(genes), " unique genes.")
    }

    genes
}

guess_gene_column <- function(x) {
    prefs <- c(
        "Gene", "gene", "SYMBOL", "GeneSymbol",
        "gene_name", "external_gene_name"
    )

    hit <- prefs[prefs %in% colnames(x)]
    if (length(hit)) return(hit[1])

    if (ncol(x) >= 1) return(colnames(x)[1])

    NA_character_
}

copy_or_na <- function(x, candidates) {
    hit <- candidates[candidates %in% colnames(x)]
    if (length(hit)) {
        return(x[[hit[1]]])
    }

    rep(NA_real_, nrow(x))
}

create_or_complete_rna_de_table <- function(gui) {
    tryCatch({
        gui$log("@@PROGRESS|0|Preparing RNA DE placeholder table...")
        gui$log("CREATE / COMPLETE RNA DE TABLE requested.")

        selected_rna <- trimws(tclvalue(gui$vars$rna_de))

        # The output is automatic. No file dialog is used.
        out_dir <- trimws(tclvalue(gui$vars$out_dir))
        if (!nzchar(out_dir)) {
            out_dir <- DEFAULT_OUT
            tclvalue(gui$vars$out_dir) <- out_dir
        }

        dir.create(
            out_dir,
            recursive = TRUE,
            showWarnings = FALSE
        )

        save_path <- file.path(
            out_dir,
            "RNAseq_differential_expression_template.tsv"
        )

        gui$log(
            "RNA DE output will be written automatically to: ",
            save_path
        )

        if (nzchar(selected_rna) && file.exists(selected_rna)) {
            # -------------------------------------------------------------
            # Complete an existing RNA table.
            # -------------------------------------------------------------
            gui$log(
                "Completing selected RNA differential-expression table: ",
                selected_rna
            )

            x <- read_table_auto(selected_rna)

            selected_gene <- trimws(
                tclvalue(gui$vars$rna_gene_col)
            )

            gene_col <- if (
                nzchar(selected_gene) &&
                selected_gene %in% colnames(x)
            ) {
                selected_gene
            } else {
                guess_gene_column(x)
            }

            if (is.na(gene_col)) {
                stop(
                    "Could not identify a gene column in the selected RNA table."
                )
            }

            out <- x

            if (!("Gene" %in% colnames(out))) {
                out$Gene <- as.character(
                    out[[gene_col]]
                )
            }

            if (!("log2FoldChange" %in% colnames(out))) {
                out$log2FoldChange <- copy_or_na(
                    out,
                    c(
                        "logFC",
                        "Log2FC",
                        "FoldChange",
                        "FC"
                    )
                )
            }

            if (!("P_value" %in% colnames(out))) {
                out$P_value <- copy_or_na(
                    out,
                    c(
                        "pvalue",
                        "p.value",
                        "P.Value",
                        "PValue",
                        "P"
                    )
                )
            }

            if (!("FDR" %in% colnames(out))) {
                out$FDR <- copy_or_na(
                    out,
                    c(
                        "padj",
                        "adj.P.Val",
                        "qvalue",
                        "q_value"
                    )
                )
            }

            mode_message <- paste0(
                "A standardized RNA DE table was created from your selected table.\n",
                "Existing values were preserved where possible; missing statistics were filled with NA."
            )
        } else {
            # -------------------------------------------------------------
            # No RNA DE table exists yet.
            #
            # Use Step 08 gene-level summaries first. They contain only one
            # row per gene and are dramatically faster to read than the huge
            # DMP/DMR annotated tables.
            # -------------------------------------------------------------
            gui$log("@@PROGRESS|15|Reading Step 08 gene summaries...")
            gui$log(
                "No RNA DE table selected. Creating an NA placeholder table ",
                "from Step 08 gene-level summaries."
            )

            dmp_path <- trimws(
                tclvalue(gui$vars$dmp_annotated)
            )
            dmr_path <- trimws(
                tclvalue(gui$vars$dmr_annotated)
            )

            dmp_genes <- extract_genes_from_step08_summary(
                dmp_path,
                "DMP_gene_summary.tsv",
                "Step 08 DMP",
                gui$log
            )

            dmr_genes <- extract_genes_from_step08_summary(
                dmr_path,
                "DMR_gene_summary.tsv",
                "Step 08 DMR",
                gui$log
            )

            genes <- sort(
                unique(
                    c(
                        dmp_genes,
                        dmr_genes
                    )
                )
            )

            genes <- genes[
                nzchar(genes) &
                !is.na(genes) &
                genes != "."
            ]

            if (!length(genes)) {
                stop(
                    "No genes could be recovered from the selected Step 08 outputs."
                )
            }

            gui$log(
                "Unique methylation-associated genes collected: ",
                length(genes)
            )
            gui$log("@@PROGRESS|70|Building NA RNA differential-expression rows...")

            out <- data.frame(
                Gene = genes,
                log2FoldChange = rep(
                    NA_real_,
                    length(genes)
                ),
                P_value = rep(
                    NA_real_,
                    length(genes)
                ),
                FDR = rep(
                    NA_real_,
                    length(genes)
                ),
                stringsAsFactors = FALSE
            )

            mode_message <- paste0(
                "A placeholder RNA differential-expression table was created from ",
                length(genes),
                " methylation-associated genes.\n\n",
                "Fold change, raw P-value and FDR are NA because RNA differential ",
                "expression has not yet been performed."
            )
        }

        gui$log("@@PROGRESS|85|Writing RNA differential-expression table...")
        gui$log(
            "Writing RNA differential-expression table..."
        )

        write_tsv(
            out,
            save_path
        )

        if (!file.exists(save_path)) {
            stop(
                "The RNA DE table was not created successfully:\n",
                save_path
            )
        }

        size_bytes <- file.info(save_path)$size

        gui$log("@@PROGRESS|100|RNA differential-expression placeholder table created.")
        gui$log(
            "RNA differential-expression table created successfully."
        )
        gui$log(
            "Rows: ",
            nrow(out),
            "; file size: ",
            format(
                size_bytes,
                big.mark = ","
            ),
            " bytes"
        )
        gui$log(
            "Created file: ",
            normalizePath(
                save_path,
                winslash = "/",
                mustWork = FALSE
            )
        )

        # Automatically select the newly created file.
        tclvalue(gui$vars$rna_de) <- save_path
        tclvalue(gui$vars$rna_gene_col) <- "Gene"
        tclvalue(gui$vars$rna_logfc_col) <- "log2FoldChange"
        tclvalue(gui$vars$rna_pvalue_col) <- "P_value"
        tclvalue(gui$vars$rna_fdr_col) <- "FDR"

        refresh_rna_metadata_dropdowns(
            gui,
            FALSE
        )

        tkmessageBox(
            title = "RNA differential-expression table created",
            message = paste0(
                mode_message,
                "\n\nCreated automatically in:\n",
                normalizePath(
                    save_path,
                    winslash = "/",
                    mustWork = FALSE
                ),
                "\n\nThe RNA-seq differential-expression table field has been filled automatically.",
                "\n\nIMPORTANT: NA means 'RNA differential expression not analyzed yet'; ",
                "it does not mean nonsignificant."
            ),
            icon = "info"
        )

        invisible(TRUE)
    }, error = function(e) {
        msg <- conditionMessage(e)

        gui$log(
            "ERROR creating RNA DE table: ",
            msg
        )

        tkmessageBox(
            title = "RNA DE table creation — Error",
            message = msg,
            icon = "error"
        )

        invisible(FALSE)
    })
}

refresh_rna_metadata_dropdowns <- function(gui, show_message = TRUE) {
    tryCatch({
        # RNA differential-expression table.
        rna_path <- trimws(tclvalue(gui$vars$rna_de))
        if (nzchar(rna_path) && file.exists(rna_path)) {
            rna <- read_table_auto(rna_path)
            cols <- colnames(rna)

            for (nm in c("rna_gene_col", "rna_logfc_col", "rna_fdr_col")) {
                tkconfigure(gui$widgets[[nm]], values = cols)
            }

            tkconfigure(
                gui$widgets$rna_pvalue_col,
                values = c("NONE", cols)
            )

            gene_pref <- c("Gene", "gene", "SYMBOL", "GeneSymbol", "gene_name", "external_gene_name")
            fc_pref <- c("log2FoldChange", "logFC", "Log2FC", "FoldChange", "FC")
            fdr_pref <- c("padj", "adj.P.Val", "FDR", "qvalue", "q_value")
            p_pref <- c("P_value", "pvalue", "p.value", "P.Value", "PValue", "P")

            gp <- gene_pref[gene_pref %in% cols]
            fp <- fc_pref[fc_pref %in% cols]
            ap <- fdr_pref[fdr_pref %in% cols]
            pp <- p_pref[p_pref %in% cols]

            if (length(gp) && !(tclvalue(gui$vars$rna_gene_col) %in% cols)) {
                tclvalue(gui$vars$rna_gene_col) <- gp[1]
            }
            if (length(fp) && !(tclvalue(gui$vars$rna_logfc_col) %in% cols)) {
                tclvalue(gui$vars$rna_logfc_col) <- fp[1]
            }
            if (length(ap) && !(tclvalue(gui$vars$rna_fdr_col) %in% cols)) {
                tclvalue(gui$vars$rna_fdr_col) <- ap[1]
            }

            current_p <- tclvalue(gui$vars$rna_pvalue_col)
            if (length(pp) && !(current_p %in% c("NONE", cols))) {
                tclvalue(gui$vars$rna_pvalue_col) <- pp[1]
            } else if (length(pp) && current_p == "NONE") {
                tclvalue(gui$vars$rna_pvalue_col) <- pp[1]
            } else if (!length(pp) && !(current_p %in% c("NONE", cols))) {
                tclvalue(gui$vars$rna_pvalue_col) <- "NONE"
            }

            gui$log("RNA DE columns loaded: ", paste(cols, collapse = ", "))
        }

        # Optional expression matrix.
        expr_path <- trimws(tclvalue(gui$vars$rna_expression))
        if (nzchar(expr_path) && file.exists(expr_path)) {
            expr <- read_table_auto(expr_path)
            cols <- colnames(expr)
            tkconfigure(gui$widgets$expression_gene_col, values = cols)

            pref <- c("Gene", "gene", "SYMBOL", "GeneSymbol", "gene_name")
            hit <- pref[pref %in% cols]

            if (length(hit) &&
                !(tclvalue(gui$vars$expression_gene_col) %in% cols)) {
                tclvalue(gui$vars$expression_gene_col) <- hit[1]
            } else if (!length(hit) &&
                       !(tclvalue(gui$vars$expression_gene_col) %in% cols)) {
                tclvalue(gui$vars$expression_gene_col) <- cols[1]
            }

            gui$log("RNA expression columns loaded.")
        }

        # Methylation metadata.
        meta_path <- trimws(tclvalue(gui$vars$metadata))
        if (nzchar(meta_path) && file.exists(meta_path)) {
            md <- read.csv(
                normalizePath(meta_path, winslash = "/", mustWork = TRUE),
                stringsAsFactors = FALSE,
                check.names = FALSE
            )

            if ("Group" %in% colnames(md)) {
                groups <- sort(unique(trimws(as.character(md$Group))))
                groups <- groups[nzchar(groups)]
                tkconfigure(gui$widgets$reference, values = groups)
                tkconfigure(gui$widgets$comparison, values = groups)

                if (length(groups) >= 2) {
                    if (!(tclvalue(gui$vars$reference) %in% groups)) {
                        tclvalue(gui$vars$reference) <- groups[1]
                    }

                    others <- setdiff(groups, tclvalue(gui$vars$reference))
                    if (length(others) &&
                        (!(tclvalue(gui$vars$comparison) %in% groups) ||
                         tclvalue(gui$vars$comparison) == tclvalue(gui$vars$reference))) {
                        tclvalue(gui$vars$comparison) <- others[1]
                    }
                }
            }

            pair_cols <- setdiff(
                colnames(md),
                c("Sample_Name", "Group", "IDAT_Basename", "Basename")
            )
            choices <- c("NONE", pair_cols)
            tkconfigure(gui$widgets$patient_column, values = choices)

            if (!(tclvalue(gui$vars$patient_column) %in% choices)) {
                tclvalue(gui$vars$patient_column) <- "NONE"
            }

            gui$log(
                "Metadata groups/pair columns loaded."
            )
        }

        if (show_message) {
            tkmessageBox(
                title = "RNA / metadata dropdowns",
                message = "Available columns were loaded from the selected files.",
                icon = "info"
            )
        }

        invisible(TRUE)
    }, error = function(e) {
        if (show_message) {
            tkmessageBox(
                title = "Dropdown loading — Error",
                message = conditionMessage(e),
                icon = "error"
            )
        }
        invisible(FALSE)
    })
}

gui <- build_gui(
    "EPIC — Step 09",
    "Integrate DNA methylation with RNA-seq",
    paste0(
        "Links Step 08 DMP/DMR gene annotations to RNA-seq by matching gene identifiers ",
        "case-insensitively (for example TP53 in methylation to TP53 in the selected RNA ",
        "gene column). The CREATE RNA DE TABLE button automatically writes a placeholder ",
        "table into the Step 09 output folder using Step 08 gene summaries and fills unavailable fold-change, P-value and FDR values ",
        "with NA. NA means RNA differential expression has not yet been analyzed. If actual ",
        "RNA DE statistics are available, the step prioritizes promoter hypermethylation + ",
        "RNA downregulation and promoter hypomethylation + RNA upregulation. Optional matched ",
        "sample expression enables sample-level and paired Δmethylation–Δexpression correlations."
    ),
    fields,
    run_step,
    output_field = "out_dir",
    window = "1180x1000"
)

tkpack(
    tkbutton(
        gui$selector_button_frame,
        text = "CREATE RNA DE TABLE (NA) IN STEP 09 OUTPUT",
        command = function() create_or_complete_rna_de_table(gui),
        background = "#2F855A",
        foreground = "white"
    ),
    side = "left",
    padx = 3
)

tkpack(
    tkbutton(
        gui$selector_button_frame,
        text = "LOAD / REFRESH RNA + METADATA DROPDOWNS",
        command = function() refresh_rna_metadata_dropdowns(gui, TRUE),
        background = "#C05621",
        foreground = "white"
    ),
    side = "left",
    padx = 3
)

refresh_rna_metadata_dropdowns(gui, FALSE)

tkwait.window(gui$window)
