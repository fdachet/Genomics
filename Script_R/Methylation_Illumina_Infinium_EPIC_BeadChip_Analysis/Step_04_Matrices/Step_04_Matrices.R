#!/usr/bin/env Rscript

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
                      output_field = NULL, window = "1180x850") {
    need_tk()
    tt <- tktoplevel()
    tkwm.title(tt, title)
    tkwm.geometry(tt, window)

    vars <- list()

    header <- tkframe(tt, background = "#17324D")
    tkpack(header, fill = "x")
    tkpack(tklabel(header, text = title, foreground = "white",
                   background = "#17324D", font = "TkDefaultFont 16 bold",
                   anchor = "w"), fill = "x", padx = 12, pady = 6)
    tkpack(tklabel(header, text = subtitle, foreground = "#D8E7F5",
                   background = "#17324D", anchor = "w"),
           fill = "x", padx = 12, pady = 6)

    desc <- tkframe(tt, background = "white", relief = "groove", borderwidth = 1)
    tkpack(desc, fill = "x", padx = 10, pady = 8)
    tkpack(tklabel(desc, text = description, justify = "left", anchor = "w",
                   wraplength = 1120, background = "white"),
           fill = "x", padx = 10, pady = 10)

    form <- tkframe(tt, background = "white", relief = "groove", borderwidth = 1)
    tkpack(form, fill = "x", padx = 10, pady = 4)

    browse_file <- function(v) {
        p <- tclvalue(tkgetOpenFile())
        if (nzchar(p)) tclvalue(v) <- p
    }
    browse_dir <- function(v) {
        p <- tclvalue(tkchooseDirectory())
        if (nzchar(p)) tclvalue(v) <- p
    }

    for (i in seq_along(fields)) {
        s <- fields[[i]]
        r <- i - 1
        v <- tclVar(as.character(s$default))
        vars[[s$name]] <- v

        tkgrid(tklabel(form, text = s$label, background = "white", anchor = "w"),
               row = r, column = 0, sticky = "w", padx = 6, pady = 4)

        if (s$type == "choice") {
            w <- ttkcombobox(form, textvariable = v, values = as.character(s$choices),
                             state = "readonly", width = 30)
            tkgrid(w, row = r, column = 1, sticky = "w", padx = 4, pady = 4)
        } else if (s$type == "bool") {
            w <- tkcheckbutton(form, variable = v, onvalue = "TRUE", offvalue = "FALSE",
                               background = "white", text = ifelse(is.null(s$check_text), "", s$check_text))
            tkgrid(w, row = r, column = 1, sticky = "w", padx = 4, pady = 4)
        } else {
            w <- tkentry(form, textvariable = v, width = 72)
            tkgrid(w, row = r, column = 1, sticky = "we", padx = 4, pady = 4)
            if (s$type == "file") {
                tkgrid(tkbutton(form, text = "Browse...",
                                command = local({vv <- v; function() browse_file(vv)})),
                       row = r, column = 2, padx = 5, pady = 4)
            }
            if (s$type == "dir") {
                tkgrid(tkbutton(form, text = "Browse...",
                                command = local({vv <- v; function() browse_dir(vv)})),
                       row = r, column = 2, padx = 5, pady = 4)
            }
        }

        if (!is.null(s$help) && nzchar(s$help)) {
            tkgrid(tklabel(form, text = s$help, justify = "left", anchor = "w",
                           wraplength = 350, foreground = "#5E6B78",
                           background = "white"),
                   row = r, column = 3, sticky = "w", padx = 8, pady = 4)
        }
    }

    button_frame <- tkframe(tt, background = "#F3F7FB")
    tkpack(button_frame, fill = "x", padx = 10, pady = 6)

    log_frame <- tkframe(tt, background = "#0F172A")
    tkpack(log_frame, fill = "both", expand = TRUE, padx = 10, pady = 5)
    logbox <- tktext(log_frame, background = "#0F172A", foreground = "#E2E8F0",
                     insertbackground = "white", wrap = "none", height = 17)
    tkpack(logbox, fill = "both", expand = TRUE)

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
        tkmessageBox(title = "Backup Settings", message = paste("Saved:", p), icon = "info")
    }

    restore <- function() {
        p <- tclvalue(tkgetOpenFile())
        if (!nzchar(p)) return()
        x <- readRDS(p)
        for (nm in intersect(names(x), names(vars))) {
            tclvalue(vars[[nm]]) <- as.character(x[[nm]])
        }
        tkmessageBox(title = "Restore Settings", message = paste("Restored:", p), icon = "info")
    }

    open_output <- function() {
        if (is.null(output_field) || !(output_field %in% names(vars))) return()
        p <- tclvalue(vars[[output_field]])
        if (!nzchar(p)) return()
        dir.create(p, recursive = TRUE, showWarnings = FALSE)
        if (.Platform$OS.type == "windows") {
            shell.exec(normalizePath(p, winslash = "\\", mustWork = FALSE))
        } else {
            system2("xdg-open", shQuote(p), wait = FALSE)
        }
    }

    run_callback <- function() {
        tryCatch({
            append_log("=== RUN START ===")
            result <- run_fun(values(), append_log)
            append_log("=== RUN COMPLETE ===")
            tkmessageBox(title = title, message = ifelse(is.null(result), "Complete", result),
                         icon = "info")
        }, error = function(e) {
            append_log("ERROR: ", conditionMessage(e))
            tkmessageBox(title = paste(title, "— Error"),
                         message = conditionMessage(e), icon = "error")
        })
    }

    tkpack(tkbutton(button_frame, text = "RUN THIS STEP", command = run_callback,
                    background = "#2B6CB0", foreground = "white"),
           side = "left", padx = 3)
    tkpack(tkbutton(button_frame, text = "Backup Settings", command = backup,
                    background = "#157A75", foreground = "white"),
           side = "left", padx = 3)
    tkpack(tkbutton(button_frame, text = "Restore Settings", command = restore,
                    background = "#2F855A", foreground = "white"),
           side = "left", padx = 3)
    if (!is.null(output_field)) {
        tkpack(tkbutton(button_frame, text = "Open Output Folder", command = open_output,
                        background = "#C05621", foreground = "white"),
               side = "left", padx = 3)
    }
    tkpack(tkbutton(button_frame, text = "Clear Log",
                    command = function() tkdelete(logbox, "1.0", "end")),
           side = "left", padx = 3)

    invisible(list(window = tt, vars = vars, values = values,
                   log = append_log, button_frame = button_frame,
                   run = run_callback))
}


EPIC_ROOT <- dirname(SCRIPT_DIR)
PREV <- file.path(EPIC_ROOT, "Step_03_Probe_Filtering", "Step_03_Output")
DEFAULT_OUT <- file.path(SCRIPT_DIR, "Step_04_Output")
dir.create(DEFAULT_OUT, recursive = TRUE, showWarnings = FALSE)

run_step <- function(v, log) {
    obj <- readRDS(normalizePath(v$obj, mustWork = TRUE))
    meta <- read.csv(normalizePath(v$metadata, mustWork = TRUE),
                     stringsAsFactors = FALSE, check.names = FALSE)
    outdir <- v$out_dir
    ver <- v$array_version
    dir.create(outdir, recursive = TRUE, showWarnings = FALSE)

    if (!requireNamespace("minfi", quietly = TRUE)) stop("minfi missing")
    suppressPackageStartupMessages(library(minfi))

    b <- getBeta(obj)
    m <- getM(obj)
    a <- as.data.frame(getAnnotation(obj))

    collapse_cg <- function(x) {
        ids <- sub("_.*$", "", rownames(x))
        keep <- grepl("^cg", ids)
        x <- x[keep, , drop = FALSE]
        ids <- ids[keep]
        lev <- unique(ids)
        s <- rowsum(x, factor(ids, levels = lev), reorder = FALSE, na.rm = TRUE)
        n <- rowsum(!is.na(x), factor(ids, levels = lev), reorder = FALSE)
        o <- s / pmax(n, 1)
        rownames(o) <- lev
        o
    }

    if (ver == "EPICv2") {
        b <- collapse_cg(b)
        m <- collapse_cg(m)
        a$Probe_ID <- sub("_.*$", "", rownames(a))
        a <- a[grepl("^cg", a$Probe_ID), , drop = FALSE]
        a <- a[!duplicated(a$Probe_ID), , drop = FALSE]
        rownames(a) <- a$Probe_ID
        a <- a[match(rownames(b), rownames(a)), , drop = FALSE]
    } else {
        a$Probe_ID <- rownames(a)
        a <- a[match(rownames(b), rownames(a)), , drop = FALSE]
    }

    saveRDS(b, file.path(outdir, "beta_matrix.rds"))
    saveRDS(m, file.path(outdir, "M_value_matrix.rds"))
    saveRDS(a, file.path(outdir, "probe_annotation.rds"))
    write.csv(meta, file.path(outdir, "metadata_matrices.csv"),
              row.names = FALSE, quote = TRUE)

    writegz <- function(df, p) {
        con <- gzfile(p, "wt")
        on.exit(close(con), add = TRUE)
        write.table(df, con, sep = "\t", quote = FALSE, row.names = FALSE)
        close(con)
        on.exit(NULL, add = FALSE)
    }
    writegz(data.frame(Probe_ID = rownames(b), b, check.names = FALSE),
            file.path(outdir, "beta_matrix.tsv.gz"))
    writegz(data.frame(Probe_ID = rownames(m), m, check.names = FALSE),
            file.path(outdir, "M_value_matrix.tsv.gz"))
    writegz(data.frame(Probe_ID = rownames(a), a, check.names = FALSE),
            file.path(outdir, "probe_annotation.tsv.gz"))

    meanb <- colMeans(b, na.rm = TRUE)
    png(file.path(outdir, "01_sample_mean_beta.png"),
        width = 1300, height = 850, res = 150)
    par(mar = c(10, 5, 4, 2))
    barplot(meanb, las = 2, ylab = "Mean beta", main = "Mean methylation")
    dev.off()
    paste0("Matrices created. CpGs: ", nrow(b))
}

fields <- list(
    list(name="obj", label="Step 03 filtered_object.rds", type="file",
         default=file.path(PREV, "filtered_object.rds")),
    list(name="metadata", label="Step 03 metadata_filtered.csv", type="file",
         default=file.path(PREV, "metadata_filtered.csv")),
    list(name="array_version", label="Array version", type="choice", default="EPICv1",
         choices=c("EPICv1","EPICv2")),
    list(name="out_dir", label="Step 04 output folder", type="dir", default=DEFAULT_OUT)
)
gui <- build_gui(
    "EPIC — Step 04",
    "Beta / M-value matrices and probe annotation",
    "Creates beta and M-value matrices. For EPIC v2, replicate-probe identifiers are collapsed to biological CpG IDs by arithmetic mean.",
    fields, run_step, output_field="out_dir"
)
tkwait.window(gui$window)
