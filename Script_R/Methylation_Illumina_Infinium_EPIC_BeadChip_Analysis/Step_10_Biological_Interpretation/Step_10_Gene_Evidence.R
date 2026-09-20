
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

build_gui <- function(
    title,
    subtitle,
    description,
    fields,
    run_fun,
    output_field = NULL,
    window = "1120x820"
) {
    need_tk()

    # =====================================================================
    # STEP 10 — ULTRA-STABLE CLASSIC Tcl/Tk LAYOUT
    #
    # IMPORTANT:
    # - No ttk widgets
    # - No grid geometry manager
    # - No nested expandable settings frames
    # - Settings are packed FIRST at the top
    # - Control buttons are packed SECOND
    # - Log is packed LAST and is the only expanding area
    #
    # This is intentionally conservative for Windows R/TclTk compatibility.
    # =====================================================================
    tt <- tktoplevel()
    tkwm.title(tt, title)
    tkwm.geometry(tt, window)
    tkwm.minsize(tt, 900, 650)

    vars <- list()
    widgets <- list()

    # ---------------------------------------------------------------------
    # HEADER
    # ---------------------------------------------------------------------
    header <- tkframe(
        tt,
        background = "#17324D"
    )
    tkpack(
        header,
        side = "top",
        fill = "x"
    )

    tkpack(
        tklabel(
            header,
            text = title,
            foreground = "white",
            background = "#17324D",
            font = "TkDefaultFont 14 bold",
            anchor = "w"
        ),
        side = "top",
        fill = "x",
        padx = 10,
        pady = 4
    )

    tkpack(
        tklabel(
            header,
            text = subtitle,
            foreground = "#D8E7F5",
            background = "#17324D",
            anchor = "w"
        ),
        side = "top",
        fill = "x",
        padx = 10,
        pady = 3
    )

    # ---------------------------------------------------------------------
    # SETTINGS — ALWAYS VISIBLE
    # ---------------------------------------------------------------------
    settings_outer <- tkframe(
        tt,
        background = "#F7FAFC",
        relief = "groove",
        borderwidth = 2
    )
    tkpack(
        settings_outer,
        side = "top",
        fill = "x",
        padx = 10,
        pady = 6
    )

    tkpack(
        tklabel(
            settings_outer,
            text = "STEP 10 SETTINGS",
            background = "#F7FAFC",
            foreground = "#17324D",
            font = "TkDefaultFont 10 bold",
            anchor = "w"
        ),
        side = "top",
        fill = "x",
        padx = 8,
        pady = 4
    )

    browse_file <- function(v) {
        p <- tclvalue(
            tkgetOpenFile(
                filetypes = "{{All files} *}"
            )
        )
        if (nzchar(p)) {
            tclvalue(v) <- p
        }
    }

    browse_dir <- function(v) {
        p <- tclvalue(
            tkchooseDirectory()
        )
        if (nzchar(p)) {
            tclvalue(v) <- p
        }
    }

    # Analysis mode is deliberately rendered as CLASSIC radio buttons
    # rather than a ttk combobox.
    mode_spec <- fields[
        vapply(
            fields,
            function(x) identical(x$name, "analysis_mode"),
            logical(1)
        )
    ][[1]]

    mode_var <- tclVar(
        as.character(mode_spec$default)
    )
    vars[["analysis_mode"]] <- mode_var

    mode_row <- tkframe(
        settings_outer,
        background = "#F7FAFC"
    )
    tkpack(
        mode_row,
        side = "top",
        fill = "x",
        padx = 8,
        pady = 3
    )

    tkpack(
        tklabel(
            mode_row,
            text = "Methylation evidence mode:",
            background = "#F7FAFC",
            anchor = "w",
            width = 30
        ),
        side = "left",
        padx = c(2, 8)
    )

    for (choice in mode_spec$choices) {
        tkpack(
            tkradiobutton(
                mode_row,
                text = choice,
                variable = mode_var,
                value = choice,
                background = "#F7FAFC"
            ),
            side = "left",
            padx = 6
        )
    }

    # All remaining settings use classic entry + browse button rows.
    other_fields <- fields[
        !vapply(
            fields,
            function(x) identical(x$name, "analysis_mode"),
            logical(1)
        )
    ]

    for (s in other_fields) {
        row_frame <- tkframe(
            settings_outer,
            background = "#F7FAFC"
        )
        tkpack(
            row_frame,
            side = "top",
            fill = "x",
            padx = 8,
            pady = 3
        )

        v <- tclVar(
            as.character(s$default)
        )
        vars[[s$name]] <- v

        tkpack(
            tklabel(
                row_frame,
                text = s$label,
                background = "#F7FAFC",
                anchor = "w",
                width = 36
            ),
            side = "left",
            padx = c(2, 6)
        )

        browse_cmd <- if (identical(s$type, "dir")) {
            local({
                vv <- v
                function() browse_dir(vv)
            })
        } else {
            local({
                vv <- v
                function() browse_file(vv)
            })
        }

        # Pack the Browse button on the RIGHT first, then allow the
        # entry to consume all remaining horizontal space.
        tkpack(
            tkbutton(
                row_frame,
                text = "Browse...",
                width = 10,
                command = browse_cmd
            ),
            side = "right",
            padx = c(5, 2)
        )

        entry <- tkentry(
            row_frame,
            textvariable = v
        )
        widgets[[s$name]] <- entry

        tkpack(
            entry,
            side = "left",
            fill = "x",
            expand = TRUE,
            padx = 4
        )
    }

    values <- function() {
        out <- list()
        for (nm in names(vars)) {
            out[[nm]] <- tclvalue(
                vars[[nm]]
            )
        }
        out
    }

    # ---------------------------------------------------------------------
    # CONTROL BUTTONS — ALWAYS VISIBLE, DIRECTLY BELOW SETTINGS
    # ---------------------------------------------------------------------
    button_frame <- tkframe(
        tt,
        background = "#E9EFF5",
        relief = "groove",
        borderwidth = 1
    )
    tkpack(
        button_frame,
        side = "top",
        fill = "x",
        padx = 10,
        pady = c(0, 6)
    )

    # ---------------------------------------------------------------------
    # LOG — ONLY EXPANDING AREA
    # ---------------------------------------------------------------------
    log_frame <- tkframe(
        tt,
        background = "#0F172A",
        relief = "groove",
        borderwidth = 1
    )
    tkpack(
        log_frame,
        side = "top",
        fill = "both",
        expand = TRUE,
        padx = 10,
        pady = c(0, 8)
    )

    logbox <- tktext(
        log_frame,
        background = "#0F172A",
        foreground = "#E2E8F0",
        insertbackground = "white",
        wrap = "word",
        height = 10
    )

    log_scroll <- tkscrollbar(
        log_frame,
        orient = "vertical",
        command = function(...) {
            tkyview(logbox, ...)
        }
    )

    tkconfigure(
        logbox,
        yscrollcommand = function(...) {
            tkset(log_scroll, ...)
        }
    )

    tkpack(
        log_scroll,
        side = "right",
        fill = "y"
    )

    tkpack(
        logbox,
        side = "left",
        fill = "both",
        expand = TRUE
    )

    append_log <- function(...) {
        msg <- paste(..., collapse = "")

        tkinsert(
            logbox,
            "end",
            paste0(msg, "\n")
        )
        tksee(
            logbox,
            "end"
        )

        # Explicitly repaint during long operations.
        tcl("update", "idletasks")
        tcl("update")
    }

    backup <- function() {
        p <- tclvalue(
            tkgetSaveFile(
                defaultextension = ".rds",
                initialfile = "Step10_Settings.rds"
            )
        )
        if (!nzchar(p)) return()

        saveRDS(
            values(),
            p
        )

        tkmessageBox(
            title = "Backup Settings",
            message = paste0(
                "Settings saved:\n",
                p
            ),
            icon = "info"
        )
    }

    restore <- function() {
        p <- tclvalue(
            tkgetOpenFile()
        )
        if (!nzchar(p)) return()

        x <- readRDS(p)

        for (nm in intersect(names(x), names(vars))) {
            tclvalue(vars[[nm]]) <- as.character(
                x[[nm]]
            )
        }

        tkmessageBox(
            title = "Restore Settings",
            message = paste0(
                "Settings restored:\n",
                p
            ),
            icon = "info"
        )
    }

    open_output <- function() {
        if (
            is.null(output_field) ||
            !(output_field %in% names(vars))
        ) {
            return()
        }

        p <- trimws(
            tclvalue(
                vars[[output_field]]
            )
        )

        if (!nzchar(p)) return()

        dir.create(
            p,
            recursive = TRUE,
            showWarnings = FALSE
        )

        if (.Platform$OS.type == "windows") {
            shell.exec(
                normalizePath(
                    p,
                    winslash = "\\",
                    mustWork = FALSE
                )
            )
        } else {
            system2(
                "xdg-open",
                shQuote(p),
                wait = FALSE
            )
        }
    }

    run_callback <- function() {
        tryCatch({
            tkdelete(
                logbox,
                "1.0",
                "end"
            )

            append_log(
                "=== STEP 10 RUN START ==="
            )

            result <- run_fun(
                values(),
                append_log
            )

            append_log(
                "=== STEP 10 RUN COMPLETE ==="
            )

            tkmessageBox(
                title = title,
                message = if (
                    is.null(result)
                ) {
                    "Complete"
                } else {
                    result
                },
                icon = "info"
            )

        }, error = function(e) {
            append_log(
                "ERROR: ",
                conditionMessage(e)
            )

            tkmessageBox(
                title = paste(
                    title,
                    "— Error"
                ),
                message = conditionMessage(e),
                icon = "error"
            )
        })
    }

    # Button row is defined only after all callbacks exist.
    tkpack(
        tkbutton(
            button_frame,
            text = "RUN THIS STEP",
            command = run_callback,
            background = "#2B6CB0",
            foreground = "white",
            font = "TkDefaultFont 9 bold"
        ),
        side = "left",
        padx = 5,
        pady = 5
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
        padx = 5,
        pady = 5
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
        padx = 5,
        pady = 5
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
            padx = 5,
            pady = 5
        )
    }

    tkpack(
        tkbutton(
            button_frame,
            text = "Clear Log",
            command = function() {
                tkdelete(
                    logbox,
                    "1.0",
                    "end"
                )
            }
        ),
        side = "left",
        padx = 5,
        pady = 5
    )

    # Make the window visible and bring it to the front.
    tcl("update", "idletasks")
    tkwm.deiconify(tt)
    tkraise(tt)
    tcl("focus", "-force", tt)

    append_log(
        "GUI ready."
    )
    append_log(
        "All Step 10 settings should be visible above this log."
    )
    append_log(
        "Select DMP + DMR, DMP only, or DMR only, then click RUN THIS STEP."
    )

    invisible(
        list(
            window = tt,
            vars = vars,
            widgets = widgets,
            values = values,
            log = append_log,
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
            check.names = FALSE, quote = "", comment.char = "",
            row.names = NULL
        ))
    }

    if (grepl(",", first, fixed = TRUE)) {
        return(read.csv(
            path, header = TRUE, stringsAsFactors = FALSE,
            check.names = FALSE, quote = "\"", comment.char = "",
            row.names = NULL
        ))
    }

    read.table(
        path, header = TRUE, sep = "", stringsAsFactors = FALSE,
        check.names = FALSE, quote = "", comment.char = "",
        row.names = NULL
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
    unique(
        out[
            nzchar(out) &
            out != "." &
            !toupper(out) %in% c("NA", "N/A", "NONE", "NULL")
        ]
    )
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
PREV9 <- file.path(EPIC_ROOT, "Step_09_RNA_Integration", "Step_09_Output")
DEFAULT_OUT <- file.path(SCRIPT_DIR, "Step_10_Output")
dir.create(DEFAULT_OUT, recursive = TRUE, showWarnings = FALSE)

prepare_bioconductor_cache <- function(cache_root, log) {
    cache_root <- trimws(cache_root)
    if (!nzchar(cache_root)) cache_root <- "C:/Temp/Methylation_BiocCache"
    cache_root <- gsub("\\\\", "/", cache_root)

    exp_cache <- file.path(cache_root, "ExperimentHub")
    ann_cache <- file.path(cache_root, "AnnotationHub")

    for (p in c(cache_root, exp_cache, ann_cache)) {
        if (!dir.exists(p)) {
            ok <- dir.create(p, recursive = TRUE, showWarnings = FALSE)
            if (!ok && !dir.exists(p)) stop("Could not create cache folder: ", p)
        }
    }

    options(
        EXPERIMENT_HUB_CACHE = exp_cache,
        ANNOTATION_HUB_CACHE = ann_cache
    )
    Sys.setenv(
        EXPERIMENT_HUB_CACHE = exp_cache,
        ANNOTATION_HUB_CACHE = ann_cache
    )

    log("Bioconductor cache root: ", cache_root)
}

annotation_for_missmethyl <- function(anno, log) {
    anno <- as.data.frame(
        anno,
        stringsAsFactors = FALSE,
        check.names = FALSE
    )

    if (!("Probe_ID" %in% colnames(anno))) {
        anno$Probe_ID <- rownames(anno)
    }

    nms <- colnames(anno)

    gene_col <- first_existing(
        nms,
        c("UCSC_RefGene_Name", "UCSC_REFGENE_NAME")
    )
    if (is.na(gene_col)) {
        gene_col <- first_regex(
            nms,
            "Gencode.*NAME|gene.*symbol|gene.*name",
            exclude = "group|relation"
        )
    }

    group_col <- first_existing(
        nms,
        c("UCSC_RefGene_Group", "UCSC_REFGENE_GROUP")
    )
    if (is.na(group_col)) {
        group_col <- first_regex(
            nms,
            "Gencode.*GROUP|RefGene.*Group|gene.*relation|gene.*group"
        )
    }

    chr_col <- first_existing(
        nms,
        c("chr", "CHR", "Chromosome", "seqnames")
    )
    pos_col <- first_existing(
        nms,
        c("pos", "MAPINFO", "Position", "start")
    )
    strand_col <- first_existing(
        nms,
        c("strand", "Strand", "Strand_FR")
    )

    if (any(is.na(c(gene_col, group_col, chr_col, pos_col)))) {
        stop(
            "Step 04 annotation does not contain the fields needed for methylation-aware ",
            "gene-set testing. Needed: gene name, gene relation, chromosome, position."
        )
    }

    out <- anno
    out$Name <- trimws(as.character(anno$Probe_ID))
    out$UCSC_RefGene_Name <- as.character(anno[[gene_col]])
    out$UCSC_RefGene_Group <- as.character(anno[[group_col]])
    out$chr <- normalize_chr(anno[[chr_col]])
    out$pos <- safe_numeric(anno[[pos_col]])
    out$strand <- if (!is.na(strand_col)) {
        as.character(anno[[strand_col]])
    } else {
        "*"
    }

    # missMethyl annotation must have one unique row name per probe.
    # Blank probe IDs cannot be matched to DMPs and are discarded.
    valid_name <- !is.na(out$Name) & nzchar(out$Name)
    n_blank <- sum(!valid_name)
    if (n_blank > 0) {
        log(
            "Annotation cleanup: dropping ",
            n_blank,
            " row(s) with blank Probe_ID."
        )
        out <- out[valid_name, , drop = FALSE]
    }

    # A data.frame cannot have duplicated row.names, and missMethyl expects
    # probe names to be unique. Keep the first annotation row for each
    # biological Probe_ID. This is especially important when an EPICv2
    # workflow has already collapsed replicated/design probe IDs upstream.
    dup <- duplicated(out$Name)
    n_dup <- sum(dup)
    if (n_dup > 0) {
        log(
            "Annotation cleanup: found ",
            n_dup,
            " duplicate Probe_ID row(s). Keeping one annotation row per Probe_ID ",
            "to prevent duplicate row.names errors."
        )
        out <- out[!dup, , drop = FALSE]
    }

    if (anyDuplicated(out$Name)) {
        stop("Internal annotation cleanup failed: Probe_ID values are still duplicated.")
    }

    rownames(out) <- out$Name

    log(
        "missMethyl annotation prepared from Step 04: ",
        nrow(out),
        " unique probes. Gene field: ",
        gene_col,
        "; gene-relation field: ",
        group_col
    )

    out
}

dmr_to_granges <- function(dmr) {
    if (!nrow(dmr)) return(NULL)

    chr_col <- first_existing(
        colnames(dmr),
        c("seqnames", "chr", "CHR", "Chromosome", "Chromosome_Standardized")
    )
    start_col <- first_existing(colnames(dmr), c("start", "Start", "START"))
    end_col <- first_existing(colnames(dmr), c("end", "End", "END"))

    if (any(is.na(c(chr_col, start_col, end_col)))) {
        stop("DMR table does not contain chromosome/start/end columns.")
    }

    ch <- normalize_chr(dmr[[chr_col]])
    st <- safe_numeric(dmr[[start_col]])
    en <- safe_numeric(dmr[[end_col]])

    ok <- nzchar(ch) & is.finite(st) & is.finite(en)
    if (!any(ok)) return(NULL)

    GenomicRanges::GRanges(
        seqnames = ch[ok],
        ranges = IRanges::IRanges(start = st[ok], end = en[ok])
    )
}

write_enrichment <- function(x, path, fdr_cut) {
    x <- as.data.frame(x)
    if ("FDR" %in% colnames(x)) {
        if ("P.DE" %in% colnames(x)) {
            x <- x[order(safe_numeric(x$FDR), safe_numeric(x$P.DE)), , drop = FALSE]
        } else {
            x <- x[order(safe_numeric(x$FDR)), , drop = FALSE]
        }

        x$Significant_FDR <- is.finite(safe_numeric(x$FDR)) &
            safe_numeric(x$FDR) <= fdr_cut
    }
    write_tsv(x, path)
    x
}

plot_enrichment <- function(x, path, title) {
    if (!nrow(x) || !("FDR" %in% colnames(x))) return(invisible(NULL))

    q <- x[is.finite(safe_numeric(x$FDR)), , drop = FALSE]
    if (!nrow(q)) return(invisible(NULL))

    q <- q[order(safe_numeric(q$FDR)), , drop = FALSE]
    q <- head(q, 20)

    label_col <- first_existing(
        colnames(q),
        c("TERM", "Term", "Pathway", "PATHWAY", "Description")
    )
    if (is.na(label_col)) {
        label <- rownames(q)
    } else {
        label <- as.character(q[[label_col]])
    }

    score <- -log10(pmax(safe_numeric(q$FDR), .Machine$double.xmin))

    png(path, width = 1500, height = 1000, res = 150)
    par(mar = c(5, 14, 4, 2))
    barplot(
        rev(score),
        names.arg = rev(label),
        horiz = TRUE,
        las = 1,
        xlab = "-log10(FDR)",
        main = title
    )
    dev.off()
}


format_elapsed <- function(seconds) {
    seconds <- suppressWarnings(as.numeric(seconds))
    if (!is.finite(seconds) || seconds < 0) seconds <- 0

    if (seconds < 60) {
        return(sprintf("%.1f sec", seconds))
    }

    minutes <- floor(seconds / 60)
    rem <- seconds - minutes * 60

    if (minutes < 60) {
        return(sprintf("%d min %.0f sec", minutes, rem))
    }

    hours <- floor(minutes / 60)
    minutes2 <- minutes - hours * 60

    sprintf("%d h %d min", hours, minutes2)
}

progress_log <- function(log, percent, message, run_start = NULL) {
    percent <- suppressWarnings(as.numeric(percent))
    if (!is.finite(percent)) percent <- 0
    percent <- min(100, max(0, percent))

    stamp <- format(Sys.time(), "%H:%M:%S")

    elapsed_txt <- ""
    if (!is.null(run_start)) {
        elapsed_txt <- paste0(
            " | elapsed ",
            format_elapsed(
                as.numeric(
                    difftime(
                        Sys.time(),
                        run_start,
                        units = "secs"
                    )
                )
            )
        )
    }

    log(
        sprintf(
            "[%5.1f%%] [%s]%s %s",
            percent,
            stamp,
            elapsed_txt,
            message
        )
    )
}

choose_numeric_column <- function(df, candidates) {
    nms <- colnames(df)
    hit <- candidates[candidates %in% nms]
    if (!length(hit)) return(NA_character_)
    hit[1]
}

split_gene_relation_pairs <- function(gene_text, relation_text) {
    genes <- trimws(
        unlist(
            strsplit(
                clean_gene_tokens(gene_text),
                "[;,]",
                perl = TRUE
            ),
            use.names = FALSE
        )
    )
    genes <- genes[
        nzchar(genes) &
        genes != "." &
        !is.na(genes)
    ]

    if (!length(genes)) {
        return(data.frame(
            Gene = character(),
            Promoter = logical(),
            stringsAsFactors = FALSE
        ))
    }

    relations <- trimws(
        unlist(
            strsplit(
                clean_gene_tokens(relation_text),
                "[;,]",
                perl = TRUE
            ),
            use.names = FALSE
        )
    )
    relations <- relations[
        nzchar(relations) &
        relations != "." &
        !is.na(relations)
    ]

    if (length(relations) == length(genes)) {
        promoter <- is_promoter_relation(relations)
    } else {
        # Annotation resources occasionally contain a different number of
        # gene and relation tokens. In that case retain the gene mapping and
        # conservatively mark promoter association if the probe has any
        # promoter-related annotation.
        promoter <- rep(
            any(is_promoter_relation(relations)),
            length(genes)
        )
    }

    keep <- !duplicated(toupper(genes))

    data.frame(
        Gene = genes[keep],
        Promoter = promoter[keep],
        stringsAsFactors = FALSE
    )
}

build_dmp_gene_evidence <- function(dmp_sig, anno, log, run_start) {
    if (!nrow(dmp_sig)) {
        return(data.frame())
    }

    p_col <- choose_numeric_column(
        dmp_sig,
        c("P.Value", "P_value", "PValue", "pvalue", "p.value", "P")
    )

    fdr_col <- choose_numeric_column(
        dmp_sig,
        c("adj.P.Val", "FDR", "fdr", "padj", "qvalue", "q_value")
    )

    delta_col <- choose_numeric_column(
        dmp_sig,
        c(
            "Delta_Beta",
            "DeltaBeta",
            "delta_beta",
            "Mean_Delta_Beta",
            "meanDifference"
        )
    )

    probes <- as.character(dmp_sig$Probe_ID)
    map_idx <- match(probes, rownames(anno))

    gene_text <- rep("", nrow(dmp_sig))
    relation_text <- rep("", nrow(dmp_sig))

    ok <- !is.na(map_idx)
    gene_text[ok] <- as.character(
        anno$UCSC_RefGene_Name[map_idx[ok]]
    )
    relation_text[ok] <- as.character(
        anno$UCSC_RefGene_Group[map_idx[ok]]
    )

    progress_log(
        log,
        18,
        paste0(
            "Fast DMP IPA mapping: parsing ",
            format(nrow(dmp_sig), big.mark = ","),
            " significant DMP annotations..."
        ),
        run_start
    )

    # FAST VERSION:
    # Do not create/rbind one tiny data.frame per DMP row.
    parsed <- lapply(
        seq_along(gene_text),
        function(i) {
            raw_genes <- trimws(
                unlist(
                    strsplit(
                        clean_gene_tokens(gene_text[i]),
                        "[;,]",
                        perl = TRUE
                    ),
                    use.names = FALSE
                )
            )

            raw_rel <- trimws(
                unlist(
                    strsplit(
                        clean_gene_tokens(relation_text[i]),
                        "[;,]",
                        perl = TRUE
                    ),
                    use.names = FALSE
                )
            )

            valid_gene <- (
                nzchar(raw_genes) &
                raw_genes != "." &
                !is.na(raw_genes) &
                !toupper(raw_genes) %in% c("NA", "N/A", "NONE", "NULL")
            )

            genes <- raw_genes[valid_gene]

            if (!length(genes)) {
                return(
                    list(
                        gene = character(),
                        promoter = logical()
                    )
                )
            }

            if (length(raw_rel) == length(raw_genes)) {
                promoter <- is_promoter_relation(
                    raw_rel[valid_gene]
                )
            } else {
                promoter <- rep(
                    any(
                        is_promoter_relation(raw_rel),
                        na.rm = TRUE
                    ),
                    length(genes)
                )
            }

            # one probe contributes once to a given gene
            keep <- !duplicated(toupper(genes))

            list(
                gene = genes[keep],
                promoter = promoter[keep]
            )
        }
    )

    counts <- vapply(
        parsed,
        function(z) length(z$gene),
        integer(1)
    )

    keep_rows <- counts > 0L

    if (!any(keep_rows)) {
        log(
            "No significant DMPs had usable gene annotations for the IPA table."
        )
        return(data.frame())
    }

    ex <- data.frame(
        Gene = unlist(
            lapply(
                parsed[keep_rows],
                function(z) z$gene
            ),
            use.names = FALSE
        ),
        Promoter = unlist(
            lapply(
                parsed[keep_rows],
                function(z) z$promoter
            ),
            use.names = FALSE
        ),
        DMP_Row = rep.int(
            which(keep_rows),
            counts[keep_rows]
        ),
        stringsAsFactors = FALSE
    )

    ex$Probe_ID <- probes[ex$DMP_Row]

    ex$P_Value <- if (!is.na(p_col)) {
        safe_numeric(
            dmp_sig[[p_col]][ex$DMP_Row]
        )
    } else {
        NA_real_
    }

    ex$FDR <- if (!is.na(fdr_col)) {
        safe_numeric(
            dmp_sig[[fdr_col]][ex$DMP_Row]
        )
    } else {
        NA_real_
    }

    ex$Delta_Beta <- if (!is.na(delta_col)) {
        safe_numeric(
            dmp_sig[[delta_col]][ex$DMP_Row]
        )
    } else {
        NA_real_
    }

    progress_log(
        log,
        22,
        paste0(
            "Fast DMP IPA mapping created ",
            format(nrow(ex), big.mark = ","),
            " probe-to-gene associations; summarizing by gene..."
        ),
        run_start
    )

    groups <- split(
        seq_len(nrow(ex)),
        toupper(ex$Gene)
    )

    out <- lapply(
        groups,
        function(ix) {
            delta <- ex$Delta_Beta[ix]
            delta_finite <- delta[is.finite(delta)]

            direction <- if (!length(delta_finite)) {
                NA_character_
            } else if (all(delta_finite > 0)) {
                "Hyper"
            } else if (all(delta_finite < 0)) {
                "Hypo"
            } else {
                "Mixed"
            }

            data.frame(
                Gene = ex$Gene[ix[1]],
                DMP_Significant = TRUE,
                # gene duplicates within a probe were removed above
                DMP_Count = length(ix),
                DMP_Promoter_Count = sum(
                    ex$Promoter[ix] %in% TRUE
                ),
                DMP_Promoter_Associated = any(
                    ex$Promoter[ix] %in% TRUE
                ),
                DMP_Best_P_Value = safe_min(
                    ex$P_Value[ix]
                ),
                DMP_Best_FDR = safe_min(
                    ex$FDR[ix]
                ),
                DMP_Mean_Delta_Beta = safe_mean(
                    ex$Delta_Beta[ix]
                ),
                DMP_MaxAbs_Delta_Beta = safe_max_abs(
                    ex$Delta_Beta[ix]
                ),
                DMP_Hyper_Count = sum(
                    ex$Delta_Beta[ix] > 0,
                    na.rm = TRUE
                ),
                DMP_Hypo_Count = sum(
                    ex$Delta_Beta[ix] < 0,
                    na.rm = TRUE
                ),
                DMP_Direction = direction,
                stringsAsFactors = FALSE
            )
        }
    )

    out <- do.call(
        rbind,
        out
    )
    rownames(out) <- NULL

    progress_log(
        log,
        25,
        paste0(
            "Fast DMP IPA summary complete: ",
            format(nrow(out), big.mark = ","),
            " genes."
        ),
        run_start
    )

    out
}

build_dmr_gene_evidence <- function(dmr_sig, log, run_start) {
    if (!nrow(dmr_sig)) {
        return(data.frame())
    }

    gene_col <- first_existing(
        colnames(dmr_sig),
        c(
            "overlapping.genes",
            "overlapping_genes",
            "Gene_Symbols",
            "Genes",
            "Gene",
            "UCSC_RefGene_Name"
        )
    )

    if (is.na(gene_col)) {
        gene_col <- first_regex(
            colnames(dmr_sig),
            "overlap.*gene|gene.*symbol|gene.*name"
        )
    }

    if (is.na(gene_col)) {
        log(
            "IPA table note: no DMR gene-name column was detected in ",
            "DMR_significant.tsv; DMR-specific gene evidence will be left NA."
        )
        return(data.frame())
    }

    # Common DMRcate significance/effect fields. Missing fields remain NA.
    min_fdr_col <- choose_numeric_column(
        dmr_sig,
        c(
            "min_smoothed_fdr",
            "min_smoothed_FDR",
            "FDR",
            "fdr"
        )
    )

    stouffer_col <- choose_numeric_column(
        dmr_sig,
        c("Stouffer", "stouffer")
    )

    hmfdr_col <- choose_numeric_column(
        dmr_sig,
        c("HMFDR", "hmfdr")
    )

    fisher_col <- choose_numeric_column(
        dmr_sig,
        c("Fisher", "fisher")
    )

    meandiff_col <- choose_numeric_column(
        dmr_sig,
        c("meandiff", "mean.diff", "MeanDiff", "mean_difference")
    )

    maxdiff_col <- choose_numeric_column(
        dmr_sig,
        c("maxdiff", "max.diff", "MaxDiff", "max_difference")
    )

    ncpg_col <- choose_numeric_column(
        dmr_sig,
        c("no.cpgs", "no_cpgs", "nCpGs", "CpG_Count", "Number_of_CpGs")
    )

    width_col <- choose_numeric_column(
        dmr_sig,
        c("width", "Width")
    )

    n <- nrow(dmr_sig)
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

        genes_list <- lapply(
            dmr_sig[[gene_col]][a:b],
            split_genes
        )

        counts <- lengths(genes_list)
        keep <- counts > 0

        if (any(keep)) {
            original_rows <- seq.int(a, b)

            pieces[[k]] <- data.frame(
                Gene = unlist(
                    genes_list[keep],
                    use.names = FALSE
                ),
                DMR_Row = rep.int(
                    original_rows[keep],
                    counts[keep]
                ),
                stringsAsFactors = FALSE
            )
        }

        pct <- 26 + 5 * k / length(starts)

        progress_log(
            log,
            pct,
            paste0(
                "Building IPA table: DMR gene mapping ",
                format(b, big.mark = ","),
                " / ",
                format(n, big.mark = ","),
                " significant DMR rows"
            ),
            run_start
        )
    }

    pieces <- Filter(
        Negate(is.null),
        pieces
    )

    if (!length(pieces)) {
        return(data.frame())
    }

    ex <- do.call(
        rbind,
        pieces
    )
    rownames(ex) <- NULL

    pull_stat <- function(col) {
        if (is.na(col)) {
            return(
                rep(
                    NA_real_,
                    nrow(ex)
                )
            )
        }
        safe_numeric(
            dmr_sig[[col]][ex$DMR_Row]
        )
    }

    ex$Min_Smoothed_FDR <- pull_stat(min_fdr_col)
    ex$Stouffer <- pull_stat(stouffer_col)
    ex$HMFDR <- pull_stat(hmfdr_col)
    ex$Fisher <- pull_stat(fisher_col)
    ex$MeanDiff <- pull_stat(meandiff_col)
    ex$MaxDiff <- pull_stat(maxdiff_col)
    ex$Number_CpGs <- pull_stat(ncpg_col)
    ex$Width <- pull_stat(width_col)

    groups <- split(
        seq_len(nrow(ex)),
        toupper(ex$Gene)
    )

    out <- lapply(
        groups,
        function(ix) {
            data.frame(
                Gene = ex$Gene[ix[1]],
                DMR_Significant = TRUE,
                DMR_Count = length(
                    unique(ex$DMR_Row[ix])
                ),
                DMR_Total_CpGs = {
                    x <- ex$Number_CpGs[ix]
                    x <- x[is.finite(x)]
                    if (length(x)) sum(x) else NA_real_
                },
                DMR_Best_Min_Smoothed_FDR = safe_min(
                    ex$Min_Smoothed_FDR[ix]
                ),
                DMR_Best_Stouffer = safe_min(
                    ex$Stouffer[ix]
                ),
                DMR_Best_HMFDR = safe_min(
                    ex$HMFDR[ix]
                ),
                DMR_Best_Fisher = safe_min(
                    ex$Fisher[ix]
                ),
                DMR_Mean_MeanDiff = safe_mean(
                    ex$MeanDiff[ix]
                ),
                DMR_MaxAbs_MeanDiff = safe_max_abs(
                    ex$MeanDiff[ix]
                ),
                DMR_MaxAbs_MaxDiff = safe_max_abs(
                    ex$MaxDiff[ix]
                ),
                DMR_Max_Width_bp = {
                    x <- ex$Width[ix]
                    x <- x[is.finite(x)]
                    if (length(x)) max(x) else NA_real_
                },
                stringsAsFactors = FALSE
            )
        }
    )

    out <- do.call(
        rbind,
        out
    )
    rownames(out) <- NULL
    out
}


annotation_for_gene_export <- function(anno, log) {
    anno <- as.data.frame(
        anno,
        stringsAsFactors = FALSE,
        check.names = FALSE
    )

    if (!("Probe_ID" %in% colnames(anno))) {
        anno$Probe_ID <- rownames(anno)
    }

    nms <- colnames(anno)

    gene_col <- first_existing(
        nms,
        c("UCSC_RefGene_Name", "UCSC_REFGENE_NAME")
    )
    if (is.na(gene_col)) {
        gene_col <- first_regex(
            nms,
            "Gencode.*NAME|gene.*symbol|gene.*name",
            exclude = "group|relation"
        )
    }

    group_col <- first_existing(
        nms,
        c("UCSC_RefGene_Group", "UCSC_REFGENE_GROUP")
    )
    if (is.na(group_col)) {
        group_col <- first_regex(
            nms,
            "Gencode.*GROUP|RefGene.*Group|gene.*relation|gene.*group"
        )
    }

    if (any(is.na(c(gene_col, group_col)))) {
        stop(
            "Step 04 annotation must contain a gene-symbol field and a gene-relation field " ,
            "for DMP gene export."
        )
    }

    out <- anno
    out$Name <- trimws(as.character(anno$Probe_ID))
    out$UCSC_RefGene_Name <- as.character(anno[[gene_col]])
    out$UCSC_RefGene_Group <- as.character(anno[[group_col]])

    valid <- !is.na(out$Name) & nzchar(out$Name)
    if (sum(!valid) > 0) {
        log("Annotation cleanup: dropping ", sum(!valid), " blank Probe_ID row(s).")
        out <- out[valid, , drop = FALSE]
    }

    dup <- duplicated(out$Name)
    if (sum(dup) > 0) {
        log(
            "Annotation cleanup: found ",
            sum(dup),
            " duplicate Probe_ID row(s); keeping the first row per Probe_ID."
        )
        out <- out[!dup, , drop = FALSE]
    }

    if (anyDuplicated(out$Name)) {
        stop("Probe_ID values remain duplicated after annotation cleanup.")
    }

    rownames(out) <- out$Name

    log(
        "Gene-export annotation ready: ",
        format(nrow(out), big.mark = ","),
        " unique probes."
    )

    out
}

column_definition_catalog <- function() {
    dmr_source <- "https://bioconductor.org/packages/release/bioc/html/DMRcate.html"

    data.frame(
        Column = c(
            "Gene",
            "Select_for_IPA",
            "Analysis_Mode",
            "Methylation_Evidence",
            "DMP_Significant",
            "DMP_Count",
            "DMP_Promoter_Associated",
            "DMP_Promoter_Count",
            "DMP_Best_P_Value",
            "DMP_Best_FDR",
            "DMP_Mean_Delta_Beta",
            "DMP_MaxAbs_Delta_Beta",
            "DMP_Hyper_Count",
            "DMP_Hypo_Count",
            "DMP_Direction",
            "DMR_Significant",
            "DMR_Count",
            "DMR_Total_CpGs",
            "DMR_Best_Min_Smoothed_FDR",
            "DMR_Best_Stouffer",
            "DMR_Best_HMFDR",
            "DMR_Best_Fisher",
            "DMR_Mean_MeanDiff",
            "DMR_MaxAbs_MeanDiff",
            "DMR_MaxAbs_MaxDiff",
            "DMR_Max_Width_bp",
            "Step09_DMP_Evidence_Count",
            "Step09_DMR_Evidence_Count",
            "Step09_Best_DMP_FDR",
            "Step09_MaxAbs_DMP_Delta_Beta",
            "Step09_RNA_logFC",
            "Step09_RNA_P_value",
            "Step09_RNA_FDR",
            "Step09_RNA_DE_Available",
            "Step09_Inverse_Promoter_RNA_Pattern",
            "Step09_Priority_Score",
            "Step09_Priority_Level"
        ),
        Category = c(
            rep("Selection / identity", 4),
            rep("DMP evidence", 11),
            rep("DMR evidence", 11),
            rep("Step 09 integration", 11)
        ),
        Definition = c(
            "Gene symbol used to summarize methylation evidence. One row in Results corresponds to one gene.",
            "Manual selection flag for your downstream pathway analysis. Step 10 initializes every gene to 0; change selected genes to 1 in Excel.",
            "Methylation evidence mode chosen when Step 10 was run: DMP + DMR, DMP only, or DMR only.",
            "Compact label indicating whether the gene has significant DMP evidence, DMR evidence, or both.",
            "TRUE when at least one significant DMP is associated with this gene.",
            "Number of significant DMP CpG probes associated with this gene. A CpG mapped to the same gene more than once is counted once for that probe-gene association.",
            "TRUE when at least one significant DMP for this gene is annotated to TSS200, TSS1500, 1stExon, 5'UTR, or a promoter annotation.",
            "Number of significant DMP CpG probes for this gene that are promoter-associated by the definition above.",
            "Smallest raw DMP P-value among significant DMPs associated with this gene.",
            "Smallest multiple-testing-adjusted DMP P-value/FDR among significant DMPs associated with this gene.",
            "Mean Delta_Beta across significant DMPs associated with the gene. Delta_Beta is comparison minus reference methylation.",
            "Largest absolute Delta_Beta among significant DMPs associated with the gene. This reports effect magnitude; use DMP_Direction/mean to recover direction.",
            "Number of significant DMPs associated with the gene having Delta_Beta > 0 (higher methylation in comparison than reference).",
            "Number of significant DMPs associated with the gene having Delta_Beta < 0 (lower methylation in comparison than reference).",
            "Hyper when all finite associated DMP Delta_Beta values are positive; Hypo when all are negative; Mixed when both directions occur.",
            "TRUE when at least one significant DMR overlaps/is annotated to this gene.",
            "Number of significant DMRs associated with this gene.",
            "Sum of DMRcate no.cpgs across significant DMRs associated with the gene. This is the summed number of constituent CpGs in those regions; it is not guaranteed to be a unique-CpG count if DMRs overlap.",
            "Smallest min_smoothed_fdr among DMRs associated with the gene. DMRcate defines min_smoothed_fdr as the minimum FDR of the smoothed estimate within a DMR.",
            "Smallest Stouffer DMR summary value among DMRs associated with the gene. DMRcate defines Stouffer as the Stouffer summary transformation of individual constituent-CpG FDRs; smaller values indicate stronger region-level evidence.",
            "Smallest HMFDR among DMRs associated with the gene. HMFDR is DMRcate's harmonic mean of the individual constituent-CpG FDRs; smaller values indicate stronger evidence.",
            "Smallest Fisher value among DMRs associated with the gene. Fisher is DMRcate's Fisher combined-probability summary of constituent-CpG FDRs; smaller values indicate stronger evidence.",
            "Mean of the DMRcate meandiff values across DMRs associated with this gene. Each DMR meandiff is the mean methylation differential/coefficient across that region.",
            "Largest absolute DMR meandiff among DMRs associated with the gene. It highlights the region with the largest average methylation change magnitude.",
            "Largest absolute DMRcate maxdiff among DMRs associated with the gene. Each DMR maxdiff is the constituent CpG differential/coefficient with the largest absolute magnitude in that region.",
            "Largest genomic width, in base pairs, among significant DMRs associated with the gene.",
            "Step 09 count of DMP evidence rows associated with the gene, when Step 09 results are available.",
            "Step 09 count of DMR evidence rows associated with the gene, when Step 09 results are available.",
            "Best/smallest DMP FDR carried forward by Step 09 for this gene.",
            "Largest absolute DMP Delta_Beta carried forward by Step 09 for this gene.",
            "RNA-seq log fold-change from Step 09 when real RNA differential-expression results were supplied. NA means unavailable, not nonsignificant.",
            "RNA-seq raw P-value from Step 09 when available. NA means unavailable.",
            "RNA-seq multiple-testing-adjusted P-value/FDR from Step 09 when available. NA means unavailable.",
            "TRUE when Step 09 had at least one real RNA differential-expression statistic for this gene; FALSE can indicate the NA placeholder workflow.",
            "TRUE when Step 09 identified an inverse promoter-methylation/RNA pattern, such as promoter hypermethylation with RNA downregulation or promoter hypomethylation with RNA upregulation.",
            "Pipeline-specific Step 09 evidence score used to rank integrated methylation/RNA candidates. This is a prioritization heuristic, not a standard biological statistic.",
            "Pipeline-specific Step 09 priority class (for example HIGH, MEDIUM, LOW) derived from Priority_Score."
        ),
        Interpretation = c(
            "Use this as the identifier column when selecting genes for IPA or another pathway tool.",
            "0 = not selected; 1 = selected. Sort/filter this column before exporting your final gene list.",
            "Documents which methylation evidence types were allowed to contribute genes to this workbook.",
            "DMP+DMR usually indicates convergent single-CpG and regional evidence; DMP or DMR alone can still be biologically meaningful.",
            "TRUE indicates single-CpG differential methylation evidence exists for the gene.",
            "Larger values mean more significant individual CpGs map to the gene, but count alone is not an effect-size or significance measure.",
            "Promoter-associated methylation may be particularly relevant to transcriptional regulation, but non-promoter methylation can also be functional.",
            "Larger values indicate more promoter-associated significant CpGs for that gene.",
            "Smaller is stronger statistical evidence. Evaluate together with FDR and effect size.",
            "Smaller is stronger after multiple-testing correction.",
            "Positive = higher methylation in comparison; negative = lower methylation. Averaging can attenuate mixed-direction CpGs.",
            "Larger values mean at least one CpG has a larger methylation-change magnitude.",
            "Useful for seeing how many associated CpGs support increased methylation.",
            "Useful for seeing how many associated CpGs support decreased methylation.",
            "Mixed flags heterogeneous direction within the gene; do not summarize such a gene as simply hyper- or hypomethylated without inspecting sites.",
            "TRUE indicates coordinated regional methylation evidence exists for the gene.",
            "Larger values mean the gene is associated with more significant regions, but regions can differ greatly in size and strength.",
            "A larger total can indicate broader regional CpG support, but compare together with DMR_Count and region significance.",
            "Smaller is stronger. This value is the best (minimum) smoothed-FDR statistic among the gene's associated DMRs.",
            "Smaller is stronger. This is a combined regional significance summary, not a methylation effect size.",
            "Smaller is stronger. This is another combined region-level significance summary.",
            "Smaller is stronger. This is another combined region-level significance summary.",
            "Sign retains direction. Positive/negative meaning follows the contrast used upstream in DMRcate.",
            "Larger magnitude means at least one associated DMR has a stronger average methylation difference.",
            "Larger magnitude means at least one CpG within an associated DMR reaches a stronger methylation difference.",
            "Describes physical extent of the largest associated DMR; width alone does not imply stronger significance.",
            "Supplementary Step 09 evidence; use alongside the direct Step 10 DMP columns.",
            "Supplementary Step 09 evidence; use alongside the direct Step 10 DMR columns.",
            "Smaller is stronger, when available.",
            "Larger magnitude indicates a stronger single-CpG methylation effect carried forward by Step 09.",
            "Positive = RNA higher in comparison; negative = RNA lower, according to the Step 09 contrast.",
            "Smaller is stronger unadjusted RNA evidence.",
            "Smaller is stronger adjusted RNA evidence.",
            "Check this before interpreting RNA columns. FALSE means RNA statistics should not be treated as evidence.",
            "Can support a regulatory interpretation, but remains an association rather than proof of causality.",
            "Higher score means more evidence according to the pipeline's heuristic rules.",
            "Convenient ranking label only; inspect the underlying evidence columns before selecting genes."
        ),
        Source = c(
            "Step 04/06/07 annotations",
            "Step 10 manual selection field",
            "Step 10 setting",
            "Step 10 summary",
            rep("Step 06 DMP analysis", 11),
            rep(dmr_source, 11),
            rep("Step 09 methylation/RNA integration", 11)
        ),
        stringsAsFactors = FALSE
    )
}

build_column_definitions <- function(result_columns) {
    catalog <- column_definition_catalog()

    extra <- setdiff(result_columns, catalog$Column)

    if (length(extra)) {
        extra_defs <- data.frame(
            Column = extra,
            Category = ifelse(
                grepl("^Step09_", extra),
                "Step 09 integration",
                "Additional evidence"
            ),
            Definition = ifelse(
                grepl("^Step09_", extra),
                paste0(
                    "Column copied from Step 09 integrated_candidate_genes.tsv. Original Step 09 column: ",
                    sub("^Step09_", "", extra),
                    "."
                ),
                "Additional column generated by the methylation pipeline."
            ),
            Interpretation = "Use together with its upstream source and the other evidence columns; NA means the value was unavailable.",
            Source = ifelse(
                grepl("^Step09_", extra),
                "Step 09 methylation/RNA integration",
                "Methylation pipeline"
            ),
            stringsAsFactors = FALSE
        )
        catalog <- rbind(catalog, extra_defs)
    }

    idx <- match(result_columns, catalog$Column)
    out <- catalog[idx, , drop = FALSE]
    rownames(out) <- NULL
    out
}

write_gene_evidence_excel <- function(evidence, outdir, log, run_start) {
    if (!nrow(evidence)) {
        stop("Cannot create Excel workbook because the gene-evidence table is empty.")
    }

    if (!requireNamespace("openxlsx", quietly = TRUE)) {
        stop(
            "The CRAN package 'openxlsx' is required to create the Excel workbook. ",
            "Run 02_Install_Windows_R_Packages.R from the pipeline installer, then rerun Step 10."
        )
    }

    progress_log(
        log,
        82,
        "Preparing Excel workbook (Results + Column_Definitions)...",
        run_start
    )

    defs <- build_column_definitions(colnames(evidence))

    wb <- openxlsx::createWorkbook()
    openxlsx::addWorksheet(wb, "Results", gridLines = FALSE)
    openxlsx::addWorksheet(wb, "Column_Definitions", gridLines = FALSE)

    # ------------------------------------------------------------------
    # Core terminology used throughout the workbook.
    # ------------------------------------------------------------------
    dmp_definition <- paste0(
        "DMP = Differentially Methylated Position. ",
        "A DMP is one individual CpG position/probe whose methylation level differs ",
        "significantly between the comparison and reference groups."
    )

    dmr_definition <- paste0(
        "DMR = Differentially Methylated Region. ",
        "A DMR is a genomic region containing multiple nearby CpG positions that show ",
        "coordinated differential methylation between the comparison and reference groups."
    )

    direction_definition <- paste0(
        "Direction: Hyper = higher methylation in the comparison group; ",
        "Hypo = lower methylation in the comparison group. ",
        "Delta_Beta = comparison Beta minus reference Beta."
    )

    interpretation_note <- paste0(
        "DMP and DMR describe methylation evidence, not RNA expression. ",
        "Promoter hypermethylation can be consistent with reduced transcription, but actual ",
        "gene downregulation requires RNA/expression evidence."
    )

    header_style <- openxlsx::createStyle(
        fontColour = "#FFFFFF",
        fgFill = "#1F4E78",
        halign = "center",
        valign = "center",
        textDecoration = "bold",
        border = "Bottom",
        borderColour = "#D9E2F3"
    )

    legend_title_style <- openxlsx::createStyle(
        fontColour = "#FFFFFF",
        fgFill = "#17324D",
        textDecoration = "bold",
        valign = "center"
    )

    dmp_legend_style <- openxlsx::createStyle(
        fgFill = "#D9EAF7",
        fontColour = "#17324D",
        textDecoration = "bold",
        wrapText = TRUE,
        valign = "top"
    )

    dmr_legend_style <- openxlsx::createStyle(
        fgFill = "#E2F0D9",
        fontColour = "#385723",
        textDecoration = "bold",
        wrapText = TRUE,
        valign = "top"
    )

    note_style <- openxlsx::createStyle(
        fgFill = "#FFF2CC",
        fontColour = "#7F6000",
        wrapText = TRUE,
        valign = "top"
    )

    select_style <- openxlsx::createStyle(
        fgFill = "#FFF2CC",
        fontColour = "#7F6000"
    )

    wrap_style <- openxlsx::createStyle(
        valign = "top",
        wrapText = TRUE
    )

    sci_style <- openxlsx::createStyle(numFmt = "0.00E+00")
    effect_style <- openxlsx::createStyle(numFmt = "0.0000")
    integer_style <- openxlsx::createStyle(numFmt = "0")

    # ==================================================================
    # RESULTS SHEET
    # Visible glossary first, then the actual one-gene-per-row table.
    # ==================================================================
    results_last_col <- max(1L, ncol(evidence))
    results_table_start <- 7L
    results_header_row <- results_table_start
    results_data_start <- results_table_start + 1L
    results_data_end <- results_table_start + nrow(evidence)

    openxlsx::mergeCells(
        wb,
        "Results",
        cols = 1:results_last_col,
        rows = 1
    )
    openxlsx::writeData(
        wb,
        "Results",
        "HOW TO READ DMP AND DMR COLUMNS",
        startRow = 1,
        startCol = 1
    )
    openxlsx::addStyle(
        wb,
        "Results",
        legend_title_style,
        rows = 1,
        cols = 1:results_last_col,
        gridExpand = TRUE,
        stack = TRUE
    )

    openxlsx::mergeCells(
        wb,
        "Results",
        cols = 1:results_last_col,
        rows = 2
    )
    openxlsx::writeData(
        wb,
        "Results",
        dmp_definition,
        startRow = 2,
        startCol = 1
    )
    openxlsx::addStyle(
        wb,
        "Results",
        dmp_legend_style,
        rows = 2,
        cols = 1:results_last_col,
        gridExpand = TRUE,
        stack = TRUE
    )

    openxlsx::mergeCells(
        wb,
        "Results",
        cols = 1:results_last_col,
        rows = 3
    )
    openxlsx::writeData(
        wb,
        "Results",
        dmr_definition,
        startRow = 3,
        startCol = 1
    )
    openxlsx::addStyle(
        wb,
        "Results",
        dmr_legend_style,
        rows = 3,
        cols = 1:results_last_col,
        gridExpand = TRUE,
        stack = TRUE
    )

    openxlsx::mergeCells(
        wb,
        "Results",
        cols = 1:results_last_col,
        rows = 4
    )
    openxlsx::writeData(
        wb,
        "Results",
        direction_definition,
        startRow = 4,
        startCol = 1
    )
    openxlsx::addStyle(
        wb,
        "Results",
        note_style,
        rows = 4,
        cols = 1:results_last_col,
        gridExpand = TRUE,
        stack = TRUE
    )

    openxlsx::mergeCells(
        wb,
        "Results",
        cols = 1:results_last_col,
        rows = 5
    )
    openxlsx::writeData(
        wb,
        "Results",
        interpretation_note,
        startRow = 5,
        startCol = 1
    )
    openxlsx::addStyle(
        wb,
        "Results",
        note_style,
        rows = 5,
        cols = 1:results_last_col,
        gridExpand = TRUE,
        stack = TRUE
    )

    openxlsx::setRowHeights(
        wb,
        "Results",
        rows = 1,
        heights = 24
    )
    openxlsx::setRowHeights(
        wb,
        "Results",
        rows = 2:5,
        heights = 34
    )

    openxlsx::writeDataTable(
        wb,
        "Results",
        evidence,
        startRow = results_table_start,
        startCol = 1,
        tableStyle = "TableStyleMedium2",
        withFilter = TRUE
    )

    openxlsx::addStyle(
        wb,
        "Results",
        header_style,
        rows = results_header_row,
        cols = seq_len(ncol(evidence)),
        gridExpand = TRUE,
        stack = TRUE
    )

    openxlsx::freezePane(
        wb,
        "Results",
        firstActiveRow = results_data_start,
        firstActiveCol = 3
    )

    sel_col <- match("Select_for_IPA", colnames(evidence))
    if (!is.na(sel_col)) {
        rows <- results_data_start:results_data_end

        openxlsx::addStyle(
            wb,
            "Results",
            select_style,
            rows = rows,
            cols = sel_col,
            gridExpand = TRUE,
            stack = TRUE
        )

        openxlsx::dataValidation(
            wb,
            "Results",
            cols = sel_col,
            rows = rows,
            type = "list",
            value = '"0,1"'
        )
    }

    p_cols <- grep(
        "P_Value|FDR|Stouffer|HMFDR|Fisher$",
        colnames(evidence)
    )
    if (length(p_cols)) {
        openxlsx::addStyle(
            wb,
            "Results",
            sci_style,
            rows = results_data_start:results_data_end,
            cols = p_cols,
            gridExpand = TRUE,
            stack = TRUE
        )
    }

    effect_cols <- grep(
        "Delta_Beta|MeanDiff|MaxDiff|RNA_logFC",
        colnames(evidence)
    )
    if (length(effect_cols)) {
        openxlsx::addStyle(
            wb,
            "Results",
            effect_style,
            rows = results_data_start:results_data_end,
            cols = effect_cols,
            gridExpand = TRUE,
            stack = TRUE
        )
    }

    count_cols <- grep(
        "_Count$|_CpGs$|_Width_bp$|Priority_Score$",
        colnames(evidence)
    )
    if (length(count_cols)) {
        openxlsx::addStyle(
            wb,
            "Results",
            integer_style,
            rows = results_data_start:results_data_end,
            cols = count_cols,
            gridExpand = TRUE,
            stack = TRUE
        )
    }

    widths <- rep(16, ncol(evidence))
    widths[colnames(evidence) == "Gene"] <- 18
    widths[colnames(evidence) == "Select_for_IPA"] <- 14
    widths[colnames(evidence) == "Analysis_Mode"] <- 14
    widths[colnames(evidence) == "Methylation_Evidence"] <- 20
    widths[grepl("Direction|Priority_Level", colnames(evidence))] <- 16

    openxlsx::setColWidths(
        wb,
        "Results",
        cols = seq_len(ncol(evidence)),
        widths = widths
    )

    # ==================================================================
    # COLUMN DEFINITIONS SHEET
    # A short glossary appears above the detailed per-column dictionary.
    # ==================================================================
    progress_log(
        log,
        90,
        "Writing Column_Definitions sheet with DMP/DMR glossary...",
        run_start
    )

    glossary <- data.frame(
        Term = c(
            "DMP",
            "DMR",
            "CpG",
            "Delta_Beta",
            "Hyper",
            "Hypo"
        ),
        Meaning = c(
            dmp_definition,
            dmr_definition,
            paste0(
                "CpG = cytosine followed by guanine in the DNA sequence. ",
                "Illumina methylation arrays measure methylation at individual CpG positions."
            ),
            paste0(
                "Delta_Beta = mean Beta value in the comparison group minus mean Beta value ",
                "in the reference group. Positive values mean higher methylation in comparison; ",
                "negative values mean lower methylation."
            ),
            "Higher methylation in the comparison group than in the reference group.",
            "Lower methylation in the comparison group than in the reference group."
        ),
        stringsAsFactors = FALSE
    )

    openxlsx::mergeCells(
        wb,
        "Column_Definitions",
        cols = 1:5,
        rows = 1
    )
    openxlsx::writeData(
        wb,
        "Column_Definitions",
        "CORE METHYLATION TERMINOLOGY",
        startRow = 1,
        startCol = 1
    )
    openxlsx::addStyle(
        wb,
        "Column_Definitions",
        legend_title_style,
        rows = 1,
        cols = 1:5,
        gridExpand = TRUE,
        stack = TRUE
    )

    openxlsx::writeDataTable(
        wb,
        "Column_Definitions",
        glossary,
        startRow = 2,
        startCol = 1,
        tableStyle = "TableStyleMedium4",
        withFilter = FALSE
    )

    openxlsx::addStyle(
        wb,
        "Column_Definitions",
        wrap_style,
        rows = 3:(nrow(glossary) + 2L),
        cols = 1:2,
        gridExpand = TRUE,
        stack = TRUE
    )

    defs_table_start <- nrow(glossary) + 4L

    openxlsx::writeData(
        wb,
        "Column_Definitions",
        "DETAILED RESULTS COLUMN DEFINITIONS",
        startRow = defs_table_start,
        startCol = 1
    )
    openxlsx::mergeCells(
        wb,
        "Column_Definitions",
        cols = 1:5,
        rows = defs_table_start
    )
    openxlsx::addStyle(
        wb,
        "Column_Definitions",
        legend_title_style,
        rows = defs_table_start,
        cols = 1:5,
        gridExpand = TRUE,
        stack = TRUE
    )

    defs_table_start <- defs_table_start + 1L

    openxlsx::writeDataTable(
        wb,
        "Column_Definitions",
        defs,
        startRow = defs_table_start,
        startCol = 1,
        tableStyle = "TableStyleMedium2",
        withFilter = TRUE
    )

    openxlsx::addStyle(
        wb,
        "Column_Definitions",
        header_style,
        rows = defs_table_start,
        cols = seq_len(ncol(defs)),
        gridExpand = TRUE,
        stack = TRUE
    )

    openxlsx::addStyle(
        wb,
        "Column_Definitions",
        wrap_style,
        rows = (defs_table_start + 1L):(defs_table_start + nrow(defs)),
        cols = seq_len(ncol(defs)),
        gridExpand = TRUE,
        stack = TRUE
    )

    openxlsx::freezePane(
        wb,
        "Column_Definitions",
        firstActiveRow = defs_table_start + 1L,
        firstActiveCol = 2
    )

    openxlsx::setColWidths(
        wb,
        "Column_Definitions",
        cols = 1,
        widths = 34
    )
    openxlsx::setColWidths(
        wb,
        "Column_Definitions",
        cols = 2,
        widths = 24
    )
    openxlsx::setColWidths(
        wb,
        "Column_Definitions",
        cols = 3,
        widths = 70
    )
    openxlsx::setColWidths(
        wb,
        "Column_Definitions",
        cols = 4,
        widths = 68
    )
    openxlsx::setColWidths(
        wb,
        "Column_Definitions",
        cols = 5,
        widths = 55
    )

    excel_path <- file.path(
        outdir,
        "Step10_Gene_Evidence_for_IPA.xlsx"
    )

    progress_log(
        log,
        95,
        paste0("Saving Excel workbook: ", excel_path),
        run_start
    )

    openxlsx::saveWorkbook(
        wb,
        excel_path,
        overwrite = TRUE
    )

    if (!file.exists(excel_path)) {
        stop("Excel workbook was not created successfully: ", excel_path)
    }

    excel_path
}

build_ipa_gene_selection_table <- function(
    dmp_sig,
    dmr_sig,
    anno,
    candidates,
    outdir,
    log,
    run_start,
    analysis_mode = "DMP + DMR"
) {
    use_dmp <- analysis_mode %in% c(
        "DMP + DMR",
        "DMP only"
    )

    use_dmr <- analysis_mode %in% c(
        "DMP + DMR",
        "DMR only"
    )

    progress_log(
        log,
        17,
        paste0(
            "Creating gene-level evidence table for QIAGEN IPA selection — ",
            analysis_mode,
            "..."
        ),
        run_start
    )

    dmp_gene <- data.frame()
    dmr_gene <- data.frame()

    if (use_dmp) {
        dmp_gene <- build_dmp_gene_evidence(
            dmp_sig,
            anno,
            log,
            run_start
        )
    } else {
        log("IPA table: DMP gene construction skipped.")
    }

    if (use_dmr) {
        dmr_gene <- build_dmr_gene_evidence(
            dmr_sig,
            log,
            run_start
        )
    } else {
        log("IPA table: DMR gene construction skipped.")
    }

    candidate_gene <- data.frame()

    if (
        nrow(candidates) &&
        "Gene" %in% colnames(candidates)
    ) {
        candidate_gene <- candidates
        candidate_gene$Gene <- trimws(
            as.character(candidate_gene$Gene)
        )
        candidate_gene <- candidate_gene[
            nzchar(candidate_gene$Gene) &
            !is.na(candidate_gene$Gene),
            ,
            drop = FALSE
        ]

        candidate_gene <- candidate_gene[
            !duplicated(toupper(candidate_gene$Gene)),
            ,
            drop = FALSE
        ]

        # Prefix Step 09 columns so their origin is unambiguous.
        non_gene <- setdiff(
            colnames(candidate_gene),
            "Gene"
        )
        colnames(candidate_gene)[
            match(
                non_gene,
                colnames(candidate_gene)
            )
        ] <- paste0(
            "Step09_",
            non_gene
        )
    }

    gene_sets <- list()

    if (nrow(dmp_gene)) {
        gene_sets[[length(gene_sets) + 1L]] <- dmp_gene$Gene
    }
    if (nrow(dmr_gene)) {
        gene_sets[[length(gene_sets) + 1L]] <- dmr_gene$Gene
    }
    # Step 09 is supplemental annotation only. It must not introduce genes
    # that are absent from the selected DMP/DMR evidence mode.

    if (!length(gene_sets)) {
        log(
            "WARNING: no gene annotations were available for the IPA gene-selection table."
        )
        return(data.frame())
    }

    genes <- sort(
        unique(
            trimws(
                unlist(
                    gene_sets,
                    use.names = FALSE
                )
            )
        )
    )
    genes <- genes[
        nzchar(genes) &
        !is.na(genes)
    ]

    out <- data.frame(
        Gene = genes,
        Select_for_IPA = 0L,
        Analysis_Mode = analysis_mode,
        stringsAsFactors = FALSE
    )

    merge_by_gene_key <- function(base, add) {
        if (!nrow(add)) return(base)

        base$.__KEY__ <- toupper(base$Gene)
        add$.__KEY__ <- toupper(add$Gene)

        add$Gene <- NULL

        ans <- merge(
            base,
            add,
            by = ".__KEY__",
            all.x = TRUE,
            sort = FALSE
        )

        # Restore the original gene order.
        ord <- match(
            toupper(genes),
            ans$.__KEY__
        )
        ans <- ans[
            ord,
            ,
            drop = FALSE
        ]
        ans$.__KEY__ <- NULL
        ans
    }

    if (use_dmp) {
        out <- merge_by_gene_key(
            out,
            dmp_gene
        )
    }

    if (use_dmr) {
        out <- merge_by_gene_key(
            out,
            dmr_gene
        )
    }

    # Step 09 can annotate the selected genes, but cannot add new genes.
    out <- merge_by_gene_key(
        out,
        candidate_gene
    )

    # Fill logical evidence flags explicitly. Numeric missing statistics remain NA.
    logical_cols <- intersect(
        c(
            "DMP_Significant",
            "DMP_Promoter_Associated",
            "DMR_Significant",
            "Step09_RNA_DE_Available",
            "Step09_Inverse_Promoter_RNA_Pattern"
        ),
        colnames(out)
    )

    for (nm in logical_cols) {
        x <- out[[nm]]
        x[is.na(x)] <- FALSE
        out[[nm]] <- x
    }

    count_cols <- intersect(
        c(
            "DMP_Count",
            "DMP_Promoter_Count",
            "DMP_Hyper_Count",
            "DMP_Hypo_Count",
            "DMR_Count"
        ),
        colnames(out)
    )

    for (nm in count_cols) {
        x <- safe_numeric(out[[nm]])
        x[!is.finite(x)] <- 0
        out[[nm]] <- as.integer(x)
    }

    # A compact evidence label helps manual sorting in Excel.
    dmp_yes <- if ("DMP_Significant" %in% colnames(out)) {
        out$DMP_Significant %in% TRUE
    } else {
        rep(FALSE, nrow(out))
    }

    dmr_yes <- if ("DMR_Significant" %in% colnames(out)) {
        out$DMR_Significant %in% TRUE
    } else {
        rep(FALSE, nrow(out))
    }

    out$Methylation_Evidence <- ifelse(
        dmp_yes & dmr_yes,
        "DMP+DMR",
        ifelse(
            dmp_yes,
            "DMP",
            ifelse(
                dmr_yes,
                "DMR",
                "Step09_only"
            )
        )
    )

    # Put the most useful manual-selection columns first.
    preferred <- c(
        "Gene",
        "Select_for_IPA",
        "Analysis_Mode",
        "Methylation_Evidence",
        "DMP_Significant",
        "DMP_Count",
        "DMP_Promoter_Associated",
        "DMP_Promoter_Count",
        "DMP_Best_P_Value",
        "DMP_Best_FDR",
        "DMP_Mean_Delta_Beta",
        "DMP_MaxAbs_Delta_Beta",
        "DMP_Hyper_Count",
        "DMP_Hypo_Count",
        "DMP_Direction",
        "DMR_Significant",
        "DMR_Count",
        "DMR_Total_CpGs",
        "DMR_Best_Min_Smoothed_FDR",
        "DMR_Best_Stouffer",
        "DMR_Best_HMFDR",
        "DMR_Best_Fisher",
        "DMR_Mean_MeanDiff",
        "DMR_MaxAbs_MeanDiff",
        "DMR_MaxAbs_MaxDiff",
        "DMR_Max_Width_bp",
        "Step09_RNA_logFC",
        "Step09_RNA_P_value",
        "Step09_RNA_FDR",
        "Step09_RNA_DE_Available",
        "Step09_Inverse_Promoter_RNA_Pattern",
        "Step09_Priority_Score",
        "Step09_Priority_Level"
    )

    preferred <- preferred[
        preferred %in% colnames(out)
    ]

    out <- out[
        ,
        c(
            preferred,
            setdiff(
                colnames(out),
                preferred
            )
        ),
        drop = FALSE
    ]

    # Sort strongest evidence first while keeping every gene.
    dmp_fdr_sort <- if ("DMP_Best_FDR" %in% colnames(out)) {
        safe_numeric(out$DMP_Best_FDR)
    } else {
        rep(Inf, nrow(out))
    }
    dmp_fdr_sort[!is.finite(dmp_fdr_sort)] <- Inf

    dmr_fdr_sort <- if ("DMR_Best_Min_Smoothed_FDR" %in% colnames(out)) {
        safe_numeric(out$DMR_Best_Min_Smoothed_FDR)
    } else {
        rep(Inf, nrow(out))
    }
    dmr_fdr_sort[!is.finite(dmr_fdr_sort)] <- Inf

    out <- out[
        order(
            -(dmp_yes & dmr_yes),
            dmp_fdr_sort,
            dmr_fdr_sort,
            out$Gene
        ),
        ,
        drop = FALSE
    ]
    rownames(out) <- NULL

    ipa_path <- file.path(
        outdir,
        "Step10_Gene_Evidence_for_IPA.tsv"
    )

    write_tsv(
        out,
        ipa_path
    )

    instructions <- c(
        "Gene evidence table for manual pathway analysis / QIAGEN IPA",
        "",
        paste("Analysis mode:", analysis_mode),
        "One row = one gene from the selected methylation evidence mode.",
        "Select_for_IPA is initialized to 0 for every gene.",
        "Change Select_for_IPA to 1 for genes you decide to analyze in IPA.",
        "",
        "Important:",
        "- Delta_Beta is DNA methylation change, NOT RNA log2 fold-change.",
        "- DMP/DMR statistics are retained in separate columns.",
        "- Step09_RNA_* columns are included only when Step 09 supplied real RNA statistics.",
        "- Missing statistics are NA/blank, not nonsignificant results.",
        "",
        paste0("Main table: ", ipa_path)
    )

    writeLines(
        instructions,
        file.path(
            outdir,
            "Step10_Gene_Evidence_README.txt"
        )
    )

    progress_log(
        log,
        34,
        paste0(
            "IPA gene-selection table created (",
            analysis_mode,
            "): ",
            format(nrow(out), big.mark = ","),
            " genes -> ",
            ipa_path
        ),
        run_start
    )

    out
}

run_step <- function(v, log) {
    run_start <- Sys.time()

    progress_log(
        log,
        0,
        "Starting Step 10 gene-evidence export for manual pathway analysis...",
        run_start
    )

    outdir <- trimws(v$out_dir)
    if (!nzchar(outdir)) outdir <- DEFAULT_OUT

    dir.create(
        outdir,
        recursive = TRUE,
        showWarnings = FALSE
    )

    if (!requireNamespace("openxlsx", quietly = TRUE)) {
        stop(
            "Missing CRAN package 'openxlsx'. Run 02_Install_Windows_R_Packages.R ",
            "from 00_Installer_Methylation, then rerun Step 10."
        )
    }

    analysis_mode <- trimws(v$analysis_mode)

    if (!(analysis_mode %in% c("DMP + DMR", "DMP only", "DMR only"))) {
        stop("Invalid methylation evidence mode: ", analysis_mode)
    }

    use_dmp <- analysis_mode %in% c("DMP + DMR", "DMP only")
    use_dmr <- analysis_mode %in% c("DMP + DMR", "DMR only")

    log("Analysis mode: ", analysis_mode)
    log("DMP evidence: ", if (use_dmp) "ON" else "SKIPPED")
    log("DMR evidence: ", if (use_dmr) "ON" else "SKIPPED")
    log("GO enrichment: REMOVED")
    log("KEGG enrichment: REMOVED")

    dmp_sig <- data.frame()
    dmr_sig <- data.frame()
    anno <- data.frame()

    if (use_dmp) {
        progress_log(
            log,
            7,
            "Reading Step 06 significant DMP table...",
            run_start
        )

        dmp_path <- trimws(v$dmp_significant)
        if (!nzchar(dmp_path) || !file.exists(dmp_path)) {
            stop("DMP mode is enabled but Step 06 DMP_significant.tsv was not found.")
        }

        dmp_sig <- read_table_auto(dmp_path)

        if (!("Probe_ID" %in% colnames(dmp_sig))) {
            stop("DMP_significant.tsv must contain Probe_ID.")
        }

        log(
            "Significant DMP rows loaded: ",
            format(nrow(dmp_sig), big.mark = ",")
        )

        progress_log(
            log,
            12,
            "Reading Step 04 probe annotation for DMP-to-gene mapping...",
            run_start
        )

        anno_path <- trimws(v$annotation)
        if (!nzchar(anno_path) || !file.exists(anno_path)) {
            stop(
                "DMP mode is enabled but Step 04 probe_annotation.rds was not found."
            )
        }

        anno_raw <- readRDS(
            normalizePath(
                anno_path,
                winslash = "/",
                mustWork = TRUE
            )
        )

        anno <- annotation_for_gene_export(
            anno_raw,
            log
        )
    } else {
        log("DMP table and probe annotation skipped because DMR-only mode was selected.")
    }

    if (use_dmr) {
        progress_log(
            log,
            18,
            "Reading Step 07 significant DMR table...",
            run_start
        )

        dmr_path <- trimws(v$dmr_significant)
        if (!nzchar(dmr_path) || !file.exists(dmr_path)) {
            stop("DMR mode is enabled but Step 07 DMR_significant.tsv was not found.")
        }

        dmr_sig <- read_table_auto(dmr_path)

        log(
            "Significant DMR rows loaded: ",
            format(nrow(dmr_sig), big.mark = ",")
        )
    } else {
        log("DMR table skipped because DMP-only mode was selected.")
    }

    candidates <- data.frame()
    cand_path <- trimws(v$integrated_candidates)

    if (nzchar(cand_path) && file.exists(cand_path)) {
        progress_log(
            log,
            22,
            "Reading optional Step 09 methylation/RNA integration table...",
            run_start
        )

        candidates <- read_table_auto(cand_path)

        log(
            "Step 09 candidate rows loaded: ",
            format(nrow(candidates), big.mark = ",")
        )
    } else {
        log(
            "Step 09 table not supplied/found. The workbook will contain methylation evidence only."
        )
    }

    progress_log(
        log,
        26,
        "Building one-gene-per-row evidence table...",
        run_start
    )

    evidence <- build_ipa_gene_selection_table(
        dmp_sig = dmp_sig,
        dmr_sig = dmr_sig,
        anno = anno,
        candidates = candidates,
        outdir = outdir,
        log = log,
        run_start = run_start,
        analysis_mode = analysis_mode
    )

    if (!nrow(evidence)) {
        stop("No genes were available for the selected evidence mode.")
    }

    progress_log(
        log,
        76,
        paste0(
            "Gene evidence table ready: ",
            format(nrow(evidence), big.mark = ","),
            " genes and ",
            ncol(evidence),
            " information columns."
        ),
        run_start
    )

    excel_path <- write_gene_evidence_excel(
        evidence = evidence,
        outdir = outdir,
        log = log,
        run_start = run_start
    )

    # Keep a plain tab-delimited copy for interoperability with R/Python/IPA.
    tsv_path <- file.path(
        outdir,
        "Step10_Gene_Evidence_for_IPA.tsv"
    )

    write_tsv(
        evidence,
        tsv_path
    )

    summary_lines <- c(
        "Step 10 — Gene evidence export for manual pathway analysis",
        paste("Analysis mode:", analysis_mode),
        paste("Genes exported:", nrow(evidence)),
        paste("Columns exported:", ncol(evidence)),
        paste("Excel workbook:", excel_path),
        paste("Tab-delimited copy:", tsv_path),
        "",
        "GO and KEGG enrichment are not run by this Step 10 version.",
        "Use Select_for_IPA = 1 in the Results worksheet to mark genes selected for your own pathway analysis.",
        "See Column_Definitions in the same workbook for the exact meaning and interpretation of every Results column."
    )

    writeLines(
        summary_lines,
        file.path(outdir, "gene_evidence_export_summary.txt")
    )

    progress_log(
        log,
        100,
        paste0(
            "Step 10 complete. Excel workbook created with ",
            format(nrow(evidence), big.mark = ","),
            " genes. Total elapsed time: ",
            format_elapsed(
                as.numeric(
                    difftime(Sys.time(), run_start, units = "secs")
                )
            )
        ),
        run_start
    )

    paste0(
        "Gene-evidence export complete.\n\n",
        "Excel workbook:\n",
        excel_path,
        "\n\nResults sheet: one gene per row.\n",
        "Column_Definitions sheet: explanation and interpretation of every column.\n\n",
        "GO/KEGG were not run."
    )
}

fields <- list(
    list(
        name = "analysis_mode",
        label = "Methylation evidence mode",
        type = "choice",
        default = "DMP + DMR",
        choices = c(
            "DMP + DMR",
            "DMP only",
            "DMR only"
        )
    ),
    list(
        name = "dmp_significant",
        label = "Step 06 DMP_significant.tsv",
        type = "file",
        default = file.path(PREV6, "DMP_significant.tsv"),
        help = "Required only for DMP + DMR or DMP only."
    ),
    list(
        name = "dmr_significant",
        label = "Step 07 DMR_significant.tsv",
        type = "file",
        default = file.path(PREV7, "DMR_significant.tsv"),
        help = "Required only for DMP + DMR or DMR only."
    ),
    list(
        name = "annotation",
        label = "Step 04 probe_annotation.rds",
        type = "file",
        default = file.path(PREV4, "probe_annotation.rds"),
        help = "Required only when DMP evidence is enabled; used to map significant CpGs to genes/promoter annotations."
    ),
    list(
        name = "integrated_candidates",
        label = "Step 09 integrated candidate genes (optional)",
        type = "file",
        default = file.path(PREV9, "integrated_candidate_genes.tsv"),
        help = "Optional. Adds RNA/integrated evidence columns to genes already selected by the DMP/DMR mode."
    ),
    list(
        name = "out_dir",
        label = "Step 10 output folder",
        type = "dir",
        default = DEFAULT_OUT
    )
)

gui <- build_gui(
    "EPIC — Step 10",
    "Gene evidence table for manual pathway analysis / QIAGEN IPA",
    paste0(
        "This Step 10 does NOT run GO or KEGG. It creates Step10_Gene_Evidence_for_IPA.xlsx. ",
        "The Results worksheet contains one gene per row and all available DMP, DMR and optional ",
        "Step 09 RNA/integration evidence in columns. Select_for_IPA starts at 0; change genes you ",
        "want to analyze to 1. The Results sheet begins with a DMP/DMR glossary, and the Column_Definitions worksheet explains what every Results column ",
        "means, how to interpret it, and its source. Choose DMP + DMR, DMP only, or DMR only. ",
        "Progress, clock time and elapsed time are printed continuously in the existing log."
    ),
    fields,
    run_step,
    output_field = "out_dir",
    window = "1120x820"
)

tkwait.window(gui$window)
