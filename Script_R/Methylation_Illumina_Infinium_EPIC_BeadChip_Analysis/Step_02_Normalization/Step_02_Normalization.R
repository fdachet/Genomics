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
PREV <- file.path(EPIC_ROOT, "Step_01_Raw_IDAT_QC", "Step_01_Output")
DEFAULT_OUT <- file.path(SCRIPT_DIR, "Step_02_Output")
dir.create(DEFAULT_OUT, recursive = TRUE, showWarnings = FALSE)

run_step <- function(v, log) {
    rg <- readRDS(normalizePath(v$rg, mustWork = TRUE))
    detP <- readRDS(normalizePath(v$detp, mustWork = TRUE))
    meta <- read.csv(normalizePath(v$metadata, mustWork = TRUE),
                     stringsAsFactors = FALSE, check.names = FALSE)
    outdir <- v$out_dir
    dir.create(outdir, recursive = TRUE, showWarnings = FALSE)
    method <- v$method
    det_thresh <- as.numeric(v$detection_p)
    pass_fraction <- as.numeric(v$pass_fraction)
    remove_failed <- as_bool(v$remove_failed)

    if (!requireNamespace("minfi", quietly = TRUE)) stop("minfi is not installed.")
    suppressPackageStartupMessages(library(minfi))

    meta <- meta[match(colnames(rg), meta$Sample_Name), , drop = FALSE]
    fail <- colMeans(detP[, colnames(rg), drop = FALSE] > det_thresh, na.rm = TRUE)
    keep <- (1 - fail) >= pass_fraction

    if (remove_failed) {
        if (sum(keep) < 2) stop("Fewer than 2 samples remain after QC.")
        rg <- rg[, keep]
        detP <- detP[, colnames(rg), drop = FALSE]
        meta <- meta[match(colnames(rg), meta$Sample_Name), , drop = FALSE]
    }

    log("Normalization method: ", method)
    if (method == "Noob") obj <- preprocessNoob(rg)
    else if (method == "Funnorm") obj <- preprocessFunnorm(rg)
    else if (method == "Quantile") obj <- preprocessQuantile(rg)
    else if (method == "SWAN") obj <- preprocessSWAN(rg, mSet = preprocessRaw(rg))
    else obj <- preprocessRaw(rg)

    saveRDS(obj, file.path(outdir, "normalized_object.rds"))
    saveRDS(detP, file.path(outdir, "detectionP_normalized_samples.rds"))
    write.csv(meta, file.path(outdir, "metadata_normalized_samples.csv"),
              row.names = FALSE, quote = TRUE)

    b <- getBeta(obj)
    png(file.path(outdir, "01_normalized_beta_density.png"),
        width = 1400, height = 900, res = 150)
    dens <- lapply(seq_len(ncol(b)), function(i) density(b[, i], na.rm = TRUE))
    plot(dens[[1]], main = paste("Normalized beta:", method), xlab = "Beta")
    if (length(dens) > 1) for (i in 2:length(dens)) lines(dens[[i]])
    dev.off()

    paste0("Normalization complete. Samples retained: ", ncol(obj))
}

fields <- list(
    list(name="rg", label="Step 01 rgSet_raw.rds", type="file",
         default=file.path(PREV, "rgSet_raw.rds")),
    list(name="detp", label="Step 01 detectionP.rds", type="file",
         default=file.path(PREV, "detectionP.rds")),
    list(name="metadata", label="Step 01 metadata_raw.csv", type="file",
         default=file.path(PREV, "metadata_raw.csv")),
    list(name="method", label="Normalization method", type="choice", default="Noob",
         choices=c("Noob","Funnorm","Quantile","SWAN","Raw")),
    list(name="detection_p", label="Detection-P threshold", type="text", default="0.01"),
    list(name="pass_fraction", label="Required fraction passing", type="text", default="0.99"),
    list(name="remove_failed", label="Sample QC", type="bool", default="TRUE",
         check_text="Remove samples failing detection-P QC"),
    list(name="out_dir", label="Step 02 output folder", type="dir", default=DEFAULT_OUT)
)

gui <- build_gui(
    "EPIC — Step 02",
    "Normalization",
    "Normalizes the raw minfi object. All metadata/cofactor columns created in the single experimental plan are carried forward automatically.",
    fields, run_step, output_field="out_dir"
)
tkwait.window(gui$window)
