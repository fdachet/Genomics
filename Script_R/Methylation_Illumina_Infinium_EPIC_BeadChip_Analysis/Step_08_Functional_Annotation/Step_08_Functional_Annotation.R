
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
    # Optional per-field help. Unlike the older Step 06 layout, help is
    # generated only when this particular step defines help text.
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

    if (length(help_lines)) {
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
                text = paste(help_lines, collapse = "\n"),
                justify = "left",
                anchor = "w",
                wraplength = 1020,
                background = "#EEF4FA"
            ),
            fill = "x",
            padx = 10,
            pady = 7
        )
    }

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
PREV6 <- file.path(EPIC_ROOT, "Step_06_DMP", "Step_06_Output")
PREV7 <- file.path(EPIC_ROOT, "Step_07_DMR", "Step_07_Output")
DEFAULT_OUT <- file.path(SCRIPT_DIR, "Step_08_Output")
dir.create(DEFAULT_OUT, recursive = TRUE, showWarnings = FALSE)

standardize_probe_annotation <- function(anno, log) {
    anno <- as.data.frame(anno, stringsAsFactors = FALSE, check.names = FALSE)

    if (!("Probe_ID" %in% colnames(anno))) {
        anno$Probe_ID <- rownames(anno)
    }

    nms <- colnames(anno)

    gene_col <- first_existing(
        nms,
        c(
            "UCSC_RefGene_Name", "UCSC_REFGENE_NAME",
            "Gene_Symbol", "GeneSymbol", "SYMBOL", "gene", "Gene"
        )
    )
    if (is.na(gene_col)) {
        gene_col <- first_regex(
            nms,
            "Gencode.*NAME|gene.*symbol|gene.*name",
            exclude = "group|relation"
        )
    }

    relation_col <- first_existing(
        nms,
        c(
            "UCSC_RefGene_Group", "UCSC_REFGENE_GROUP",
            "Gene_Relation", "feature", "Feature"
        )
    )
    if (is.na(relation_col)) {
        relation_col <- first_regex(
            nms,
            "Gencode.*GROUP|RefGene.*Group|gene.*relation|gene.*group"
        )
    }

    island_col <- first_existing(
        nms,
        c(
            "Relation_to_Island", "Relation_to_UCSC_CpG_Island",
            "Relation_to_UCSC_CpG_Island", "cgi", "CGI"
        )
    )
    if (is.na(island_col)) {
        island_col <- first_regex(
            nms,
            "Relation.*Island|CpG.*Island.*Relation|cgi"
        )
    }

    chr_col <- first_existing(
        nms,
        c("chr", "CHR", "Chromosome", "chromosome", "seqnames")
    )
    pos_col <- first_existing(
        nms,
        c("pos", "MAPINFO", "Position", "position", "start")
    )
    strand_col <- first_existing(
        nms,
        c("strand", "Strand", "Strand_FR")
    )

    out <- data.frame(
        Probe_ID = as.character(anno$Probe_ID),
        Gene_Symbols = if (!is.na(gene_col)) as.character(anno[[gene_col]]) else "",
        Gene_Relation = if (!is.na(relation_col)) as.character(anno[[relation_col]]) else "",
        CpG_Island_Relation = if (!is.na(island_col)) as.character(anno[[island_col]]) else "",
        Chromosome = if (!is.na(chr_col)) normalize_chr(anno[[chr_col]]) else "",
        Position = if (!is.na(pos_col)) safe_numeric(anno[[pos_col]]) else NA_real_,
        Strand = if (!is.na(strand_col)) as.character(anno[[strand_col]]) else "",
        stringsAsFactors = FALSE
    )

    out$Gene_Symbols <- gsub(";+",
        ";",
        gsub("^;|;$", "", gsub(",", ";", out$Gene_Symbols, fixed = TRUE))
    )
    out$Promoter_Associated <- is_promoter_relation(out$Gene_Relation)

    log(
        "Annotation columns detected — Gene: ",
        ifelse(is.na(gene_col), "NONE", gene_col),
        "; relation: ",
        ifelse(is.na(relation_col), "NONE", relation_col),
        "; CpG island: ",
        ifelse(is.na(island_col), "NONE", island_col),
        "; chromosome: ",
        ifelse(is.na(chr_col), "NONE", chr_col),
        "; position: ",
        ifelse(is.na(pos_col), "NONE", pos_col)
    )

    out
}

annotate_dmp <- function(dmp, std_anno) {
    if (!("Probe_ID" %in% colnames(dmp))) {
        stop("DMP table is missing Probe_ID.")
    }

    m <- match(as.character(dmp$Probe_ID), std_anno$Probe_ID)
    add <- std_anno[m, setdiff(colnames(std_anno), "Probe_ID"), drop = FALSE]

    # Avoid duplicate columns already carried from Step 06.
    for (nm in colnames(add)) {
        dmp[[nm]] <- add[[nm]]
    }

    if ("Delta_Beta" %in% colnames(dmp)) {
        db <- safe_numeric(dmp$Delta_Beta)
        dmp$Methylation_Direction <- ifelse(
            !is.finite(db), "",
            ifelse(db > 0, "Hypermethylated_in_comparison",
                   ifelse(db < 0, "Hypomethylated_in_comparison", "No_change"))
        )
    }

    dmp
}

explode_gene_rows <- function(df, gene_col = "Gene_Symbols", log = NULL) {
    if (!(gene_col %in% colnames(df)) || !nrow(df)) {
        return(data.frame())
    }

    raw <- clean_gene_tokens(df[[gene_col]])
    raw[is.na(raw)] <- ""

    if (!is.null(log)) {
        log(
            "Expanding gene annotations for ",
            nrow(df),
            " methylation rows..."
        )
    }

    # Split all rows once. The previous implementation constructed a
    # separate data.frame for every DMP/DMR row and then rbind'ed them.
    gene_lists <- strsplit(
        raw,
        "[;,]",
        perl = TRUE
    )

    gene_lists <- lapply(
        gene_lists,
        function(z) {
            z <- trimws(z)
            z <- z[nzchar(z) & z != "." & !is.na(z)]
            unique(z)
        }
    )

    n_gene <- lengths(gene_lists)
    keep <- n_gene > 0

    if (!any(keep)) {
        return(data.frame())
    }

    row_ids <- which(keep)

    out <- data.frame(
        Row_Index = rep.int(row_ids, n_gene[keep]),
        Gene = unlist(gene_lists[keep], use.names = FALSE),
        stringsAsFactors = FALSE
    )

    if (!is.null(log)) {
        log(
            "Gene expansion complete: ",
            nrow(out),
            " DMP/DMR-to-gene associations."
        )
    }

    out
}

make_dmp_gene_summary <- function(dmp_sig, log = NULL) {
    ex <- explode_gene_rows(
        dmp_sig,
        gene_col = "Gene_Symbols",
        log = log
    )

    if (is.null(ex) || !nrow(ex)) {
        if (!is.null(log)) log("No DMP-associated genes to summarize.")
        return(data.frame())
    }

    ex$FDR <- if ("adj.P.Val" %in% colnames(dmp_sig)) {
        safe_numeric(dmp_sig$adj.P.Val[ex$Row_Index])
    } else {
        NA_real_
    }

    ex$Delta_Beta <- if ("Delta_Beta" %in% colnames(dmp_sig)) {
        safe_numeric(dmp_sig$Delta_Beta[ex$Row_Index])
    } else {
        NA_real_
    }

    ex$Promoter <- if ("Promoter_Associated" %in% colnames(dmp_sig)) {
        as.logical(dmp_sig$Promoter_Associated[ex$Row_Index])
    } else {
        rep(FALSE, nrow(ex))
    }

    if (!is.null(log)) {
        log(
            "Grouping ",
            nrow(ex),
            " DMP-to-gene associations..."
        )
    }

    # Factorize once. All subsequent summaries are linear-time grouped
    # calculations. The previous code repeatedly rescanned the ENTIRE
    # association table once for every gene.
    gene_factor <- factor(ex$Gene)
    gene_levels <- levels(gene_factor)
    group_id <- as.integer(gene_factor)
    n_groups <- length(gene_levels)

    significant_dmps <- tabulate(
        group_id,
        nbins = n_groups
    )

    promoter_dmps <- rowsum(
        as.integer(ex$Promoter %in% TRUE),
        group = group_id,
        reorder = FALSE
    )[, 1]

    # Mean Delta Beta, ignoring non-finite values.
    db <- ex$Delta_Beta
    db_ok <- is.finite(db)

    db_sum <- rowsum(
        ifelse(db_ok, db, 0),
        group = group_id,
        reorder = FALSE
    )[, 1]

    db_n <- rowsum(
        as.integer(db_ok),
        group = group_id,
        reorder = FALSE
    )[, 1]

    mean_db <- ifelse(
        db_n > 0,
        db_sum / db_n,
        NA_real_
    )

    # Best FDR and maximum |Delta Beta| need min/max group operations.
    # split() creates group indices ONCE, avoiding repeated full-table scans.
    group_rows <- split(
        seq_len(nrow(ex)),
        group_id
    )

    best_fdr <- vapply(
        group_rows,
        function(ix) {
            x <- ex$FDR[ix]
            x <- x[is.finite(x)]
            if (length(x)) min(x) else NA_real_
        },
        numeric(1)
    )

    max_abs_db <- vapply(
        group_rows,
        function(ix) {
            x <- abs(ex$Delta_Beta[ix])
            x <- x[is.finite(x)]
            if (length(x)) max(x) else NA_real_
        },
        numeric(1)
    )

    out <- data.frame(
        Gene = gene_levels,
        Significant_DMPs = significant_dmps,
        Promoter_DMPs = promoter_dmps,
        Best_DMP_FDR = unname(best_fdr),
        Mean_Delta_Beta = mean_db,
        MaxAbs_Delta_Beta = unname(max_abs_db),
        stringsAsFactors = FALSE
    )

    out <- out[
        order(
            out$Best_DMP_FDR,
            -out$Significant_DMPs,
            na.last = TRUE
        ),
        ,
        drop = FALSE
    ]

    rownames(out) <- NULL

    if (!is.null(log)) {
        log(
            "Gene-level DMP summary complete: ",
            nrow(out),
            " genes."
        )
    }

    out
}

annotate_dmrs <- function(dmr, std_anno, dmp_all, log) {
    if (!nrow(dmr)) {
        log("No significant DMRs to annotate.")
        return(dmr)
    }

    log("Standardizing DMRcate region annotations...")

    chr_col <- first_existing(
        colnames(dmr),
        c("seqnames", "chr", "CHR", "Chromosome")
    )
    start_col <- first_existing(
        colnames(dmr),
        c("start", "Start", "START")
    )
    end_col <- first_existing(
        colnames(dmr),
        c("end", "End", "END")
    )

    if (is.na(chr_col) || is.na(start_col) || is.na(end_col)) {
        stop(
            "DMR table must contain chromosome/start/end columns. Found columns: ",
            paste(colnames(dmr), collapse = ", ")
        )
    }

    dmr$Chromosome_Standardized <- normalize_chr(dmr[[chr_col]])

    # ------------------------------------------------------------------
    # IMPORTANT PERFORMANCE FIX
    #
    # DMRcate::extractRanges() already supplies DMR-level information
    # including the number of CpGs, regional methylation effect, and
    # overlapping genes in current DMRcate output.
    #
    # Therefore Step 08 MUST NOT loop over every DMR and rediscover the
    # same annotations probe-by-probe. With >100,000 DMRs that approach
    # can take an extremely long time.
    # ------------------------------------------------------------------

    gene_col <- first_existing(
        colnames(dmr),
        c(
            "overlapping.genes",
            "overlapping_genes",
            "overlappingGenes",
            "overlapping.promoters",
            "overlapping_promoters"
        )
    )

    promoter_col <- first_existing(
        colnames(dmr),
        c(
            "overlapping.promoters",
            "overlapping_promoters",
            "overlappingPromoters"
        )
    )

    count_col <- first_existing(
        colnames(dmr),
        c(
            "no.cpgs",
            "no_cpgs",
            "n.cpgs",
            "n_cpgs",
            "No.CpGs"
        )
    )

    effect_col <- first_existing(
        colnames(dmr),
        c(
            "meandiff",
            "mean.diff",
            "meanbetafc",
            "mean_beta_fc",
            "Mean_Delta_Beta",
            "maxdiff",
            "maxbetafc"
        )
    )

    # Gene assignment ---------------------------------------------------
    if (!is.na(gene_col)) {
        genes <- as.character(dmr[[gene_col]])
        genes[is.na(genes)] <- ""

        # DMRcate commonly separates multiple genes with commas.
        genes <- gsub(",", ";", genes, fixed = TRUE)
        genes <- gsub(";[[:space:]]*", ";", genes)
        genes <- gsub("^[;[:space:]]+|[;[:space:]]+$", "", genes)

        dmr$Genes_From_DMRcate <- genes
        dmr$Gene_Symbols <- genes

        log(
            "Using DMRcate gene annotation column: ",
            gene_col
        )
    } else {
        # Do not fall back to a 100,000+ region R loop.
        #
        # The DMR table remains valid for region-level analysis, but gene
        # integration cannot be performed reliably without a DMR-level
        # gene field. The user can still use DMP gene annotation.
        dmr$Genes_From_DMRcate <- ""
        dmr$Gene_Symbols <- ""

        log(
            "WARNING: No DMRcate overlapping-gene/promoter column was found. ",
            "Step 08 will NOT launch a slow per-DMR probe loop. ",
            "DMP annotation remains available, but DMR gene symbols will be blank."
        )
    }

    # Number of constituent CpGs ---------------------------------------
    if (!is.na(count_col)) {
        dmr$Overlapping_Probe_Count <- safe_numeric(dmr[[count_col]])
        log("Using DMRcate CpG-count column: ", count_col)
    } else {
        dmr$Overlapping_Probe_Count <- NA_real_
        log(
            "WARNING: DMRcate CpG-count column was not found; ",
            "Overlapping_Probe_Count will be NA."
        )
    }

    # Regional methylation effect --------------------------------------
    if (!is.na(effect_col)) {
        regional_effect <- safe_numeric(dmr[[effect_col]])
        dmr$Mean_Delta_Beta_From_All_DMPs <- regional_effect
        log("Using DMRcate regional-effect column: ", effect_col)
    } else {
        regional_effect <- rep(NA_real_, nrow(dmr))
        dmr$Mean_Delta_Beta_From_All_DMPs <- regional_effect
        log(
            "WARNING: No DMRcate regional methylation-effect column was found."
        )
    }

    # DMRs are regions, so there is not necessarily one unique
    # probe-level UCSC gene relation / CpG-island relation for the whole
    # region. Keep these fields conservative instead of concatenating
    # hundreds of thousands of probe annotations.
    dmr$Gene_Relation <- ""

    if (!is.na(promoter_col)) {
        promoters <- as.character(dmr[[promoter_col]])
        promoters[is.na(promoters)] <- ""

        dmr$Promoter_Associated <- nzchar(trimws(promoters))
        dmr$Gene_Relation[dmr$Promoter_Associated] <-
            "DMRcate_overlapping_promoter"

        log(
            "Using DMRcate promoter annotation column: ",
            promoter_col
        )
    } else {
        dmr$Promoter_Associated <- FALSE
        log(
            "No promoter-specific DMRcate column detected. ",
            "DMR promoter status is left FALSE conservatively; ",
            "promoter-specific integration can still use the DMP annotations."
        )
    }

    dmr$CpG_Island_Relation <- ""

    # Do not write enormous semicolon-delimited lists of every constituent
    # probe for >100,000 DMRs. Step 07 already reports no.cpgs, and the
    # precise CpG membership can be reconstructed later for selected DMRs
    # only if needed.
    dmr$Overlapping_Array_Probes <- ""

    dmr$Methylation_Direction <- ifelse(
        !is.finite(regional_effect),
        "",
        ifelse(
            regional_effect > 0,
            "Hypermethylated_in_comparison",
            ifelse(
                regional_effect < 0,
                "Hypomethylated_in_comparison",
                "No_change"
            )
        )
    )

    n_gene <- sum(
        vapply(
            dmr$Gene_Symbols,
            function(x) length(split_genes(x)) > 0,
            logical(1)
        )
    )

    log(
        "DMR standardization complete — regions: ",
        nrow(dmr),
        "; regions with gene annotation: ",
        n_gene
    )

    log(
        "No per-DMR probe loop was required."
    )

    dmr
}

make_dmr_gene_summary <- function(dmr_ann, log = NULL) {
    ex <- explode_gene_rows(
        dmr_ann,
        gene_col = "Gene_Symbols",
        log = log
    )

    if (is.null(ex) || !nrow(ex)) {
        if (!is.null(log)) log("No DMR-associated genes to summarize.")
        return(data.frame())
    }

    ex$Promoter <- if ("Promoter_Associated" %in% colnames(dmr_ann)) {
        as.logical(dmr_ann$Promoter_Associated[ex$Row_Index])
    } else {
        rep(FALSE, nrow(ex))
    }

    effect_col <- first_existing(
        colnames(dmr_ann),
        c(
            "meandiff",
            "Mean_Delta_Beta_From_All_DMPs",
            "meanbetafc",
            "maxdiff"
        )
    )

    ex$Effect <- if (!is.na(effect_col)) {
        safe_numeric(dmr_ann[[effect_col]][ex$Row_Index])
    } else {
        NA_real_
    }

    if (!is.null(log)) {
        log(
            "Grouping ",
            nrow(ex),
            " DMR-to-gene associations..."
        )
    }

    gene_factor <- factor(ex$Gene)
    gene_levels <- levels(gene_factor)
    group_id <- as.integer(gene_factor)
    n_groups <- length(gene_levels)

    significant_dmrs <- tabulate(
        group_id,
        nbins = n_groups
    )

    promoter_dmrs <- rowsum(
        as.integer(ex$Promoter %in% TRUE),
        group = group_id,
        reorder = FALSE
    )[, 1]

    eff <- ex$Effect
    eff_ok <- is.finite(eff)

    eff_sum <- rowsum(
        ifelse(eff_ok, eff, 0),
        group = group_id,
        reorder = FALSE
    )[, 1]

    eff_n <- rowsum(
        as.integer(eff_ok),
        group = group_id,
        reorder = FALSE
    )[, 1]

    mean_eff <- ifelse(
        eff_n > 0,
        eff_sum / eff_n,
        NA_real_
    )

    group_rows <- split(
        seq_len(nrow(ex)),
        group_id
    )

    max_abs_eff <- vapply(
        group_rows,
        function(ix) {
            x <- abs(ex$Effect[ix])
            x <- x[is.finite(x)]
            if (length(x)) max(x) else NA_real_
        },
        numeric(1)
    )

    out <- data.frame(
        Gene = gene_levels,
        Significant_DMRs = significant_dmrs,
        Promoter_DMRs = promoter_dmrs,
        Mean_DMR_Effect = mean_eff,
        MaxAbs_DMR_Effect = unname(max_abs_eff),
        stringsAsFactors = FALSE
    )

    out <- out[
        order(
            -out$Significant_DMRs,
            -out$MaxAbs_DMR_Effect,
            na.last = TRUE
        ),
        ,
        drop = FALSE
    ]

    rownames(out) <- NULL

    if (!is.null(log)) {
        log(
            "Gene-level DMR summary complete: ",
            nrow(out),
            " genes."
        )
    }

    out
}

run_step <- function(v, log) {
    outdir <- v$out_dir
    dir.create(outdir, recursive = TRUE, showWarnings = FALSE)

    log("Reading Step 04 probe annotation...")
    anno <- readRDS(normalizePath(v$annotation, winslash = "/", mustWork = TRUE))
    std_anno <- standardize_probe_annotation(anno, log)

    dmp_all <- read_table_auto(v$dmp_all)
    dmp_sig <- read_table_auto(v$dmp_significant)
    dmr_sig <- read_table_auto(v$dmr_significant)

    log("DMP all rows: ", nrow(dmp_all))
    log("Significant DMP rows: ", nrow(dmp_sig))
    log("Significant DMR rows: ", nrow(dmr_sig))

    log("Annotating all DMP rows...")
    dmp_all_ann <- annotate_dmp(dmp_all, std_anno)
    log("All DMP annotation complete.")

    log("Annotating significant DMP rows...")
    dmp_sig_ann <- annotate_dmp(dmp_sig, std_anno)
    log("Significant DMP annotation complete.")

    log("Starting DMR annotation...")
    dmr_ann <- annotate_dmrs(dmr_sig, std_anno, dmp_all_ann, log)

    log("Writing DMP_annotated_all.tsv...")
    write_tsv(
        dmp_all_ann,
        file.path(outdir, "DMP_annotated_all.tsv")
    )
    log("Writing DMP_annotated_significant.tsv...")
    write_tsv(
        dmp_sig_ann,
        file.path(outdir, "DMP_annotated_significant.tsv")
    )

    log("Writing DMR_annotated_significant.tsv...")
    write_tsv(
        dmr_ann,
        file.path(outdir, "DMR_annotated_significant.tsv")
    )

    log("Building gene-level DMP summary...")
    dmp_gene <- make_dmp_gene_summary(dmp_sig_ann, log)

    log("Building gene-level DMR summary...")
    dmr_gene <- make_dmr_gene_summary(dmr_ann, log)

    write_tsv(
        dmp_gene,
        file.path(outdir, "DMP_gene_summary.tsv")
    )
    write_tsv(
        dmr_gene,
        file.path(outdir, "DMR_gene_summary.tsv")
    )

    # Plot 1: DMP gene-relation contexts.
    if (nrow(dmp_sig_ann) && "Gene_Relation" %in% colnames(dmp_sig_ann)) {
        rel <- trimws(unlist(strsplit(
            paste(dmp_sig_ann$Gene_Relation, collapse = ";"),
            "[;,]"
        )))
        rel <- rel[nzchar(rel)]

        if (length(rel)) {
            tb <- sort(table(rel), decreasing = TRUE)
            tb <- head(tb, 15)

            png(
                file.path(outdir, "01_DMP_gene_contexts.png"),
                width = 1300,
                height = 850,
                res = 150
            )
            par(mar = c(10, 5, 4, 2))
            barplot(
                tb,
                las = 2,
                ylab = "Number of significant DMP annotations",
                main = "Top gene-relative contexts among significant DMPs"
            )
            dev.off()
        }
    }

    # Plot 2: genes per DMR.
    if (nrow(dmr_ann)) {
        ng <- vapply(dmr_ann$Gene_Symbols, function(x) length(split_genes(x)), integer(1))
        png(
            file.path(outdir, "02_genes_per_DMR.png"),
            width = 1100,
            height = 800,
            res = 150
        )
        hist(
            ng,
            breaks = 40,
            xlab = "Annotated genes per DMR",
            main = "Gene annotation density of DMRs"
        )
        dev.off()
    }

    summary_lines <- c(
        paste("Array version:", v$array_version),
        paste("All DMPs:", nrow(dmp_all_ann)),
        paste("Significant DMPs:", nrow(dmp_sig_ann)),
        paste(
            "Significant DMPs mapped to >=1 gene:",
            sum(vapply(dmp_sig_ann$Gene_Symbols, function(x) length(split_genes(x)) > 0, logical(1)))
        ),
        paste("Significant DMRs:", nrow(dmr_ann)),
        paste(
            "Significant DMRs mapped to >=1 gene:",
            if (nrow(dmr_ann)) sum(vapply(dmr_ann$Gene_Symbols, function(x) length(split_genes(x)) > 0, logical(1))) else 0
        ),
        paste("Unique DMP-associated genes:", nrow(dmp_gene)),
        paste("Unique DMR-associated genes:", nrow(dmr_gene))
    )

    writeLines(
        summary_lines,
        file.path(outdir, "annotation_summary.txt")
    )

    paste0(
        "Functional annotation complete.\n",
        "DMP-associated genes: ", nrow(dmp_gene), "\n",
        "DMR-associated genes: ", nrow(dmr_gene), "\n",
        "Results:\n", outdir
    )
}

fields <- list(
    list(
        name = "dmp_all",
        label = "Step 06 DMP_all.tsv",
        type = "file",
        default = file.path(PREV6, "DMP_all.tsv")
    ),
    list(
        name = "dmp_significant",
        label = "Step 06 DMP_significant.tsv",
        type = "file",
        default = file.path(PREV6, "DMP_significant.tsv")
    ),
    list(
        name = "dmr_significant",
        label = "Step 07 DMR_significant.tsv",
        type = "file",
        default = file.path(PREV7, "DMR_significant.tsv")
    ),
    list(
        name = "annotation",
        label = "Step 04 probe_annotation.rds",
        type = "file",
        default = file.path(PREV4, "probe_annotation.rds")
    ),
    list(
        name = "array_version",
        label = "Array version",
        type = "choice",
        default = "EPICv1",
        choices = c("EPICv1", "EPICv2")
    ),
    list(
        name = "out_dir",
        label = "Step 08 output folder",
        type = "dir",
        default = DEFAULT_OUT
    )
)

gui <- build_gui(
    "EPIC — Step 08",
    "Functional annotation of DMPs and DMRs",
    paste0(
        "Adds standardized gene, gene-relative, CpG-island, chromosome and position ",
        "annotations to significant methylation results. DMRs are annotated by the ",
        "array probes that physically overlap each region. This step also creates ",
        "gene-level DMP and DMR summaries for downstream RNA-seq integration."
    ),
    fields,
    run_step,
    output_field = "out_dir"
)

tkwait.window(gui$window)
