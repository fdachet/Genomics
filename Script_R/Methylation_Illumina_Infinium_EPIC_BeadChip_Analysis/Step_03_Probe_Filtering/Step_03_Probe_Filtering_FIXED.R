

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
PREV <- file.path(EPIC_ROOT, "Step_02_Normalization", "Step_02_Output")
DEFAULT_OUT <- file.path(SCRIPT_DIR, "Step_03_Output")
dir.create(DEFAULT_OUT, recursive = TRUE, showWarnings = FALSE)

run_step <- function(v, log) {
    obj <- readRDS(normalizePath(v$obj, mustWork = TRUE))
    detP <- readRDS(normalizePath(v$detp, mustWork = TRUE))
    meta <- read.csv(normalizePath(v$metadata, mustWork = TRUE),
                     stringsAsFactors = FALSE, check.names = FALSE)
    outdir <- v$out_dir
    dir.create(outdir, recursive = TRUE, showWarnings = FALSE)
    dp <- as.numeric(v$detection_p)
    frac <- as.numeric(v$probe_pass_fraction)
    drop_snps <- as_bool(v$drop_snps)
    remove_sex <- as_bool(v$remove_sex)

    if (!requireNamespace("minfi", quietly = TRUE)) stop("minfi missing")
    suppressPackageStartupMessages(library(minfi))

    initial <- rownames(getBeta(obj))
    common <- intersect(initial, rownames(detP))

    log("Initial probes in normalized object: ", length(initial))
    log("Probes also present in detection-P matrix: ", length(common))

    if (length(initial) == 0) {
        stop("The normalized object contains zero probes.")
    }
    if (length(common) == 0) {
        stop(
            "No probe IDs are shared between normalized_object.rds and ",
            "detectionP_normalized_samples.rds. Check that both files came ",
            "from the same Step 02 run."
        )
    }

    missing_samples <- setdiff(colnames(obj), colnames(detP))
    if (length(missing_samples)) {
        stop(
            "Detection-P matrix is missing sample(s): ",
            paste(missing_samples, collapse = ", ")
        )
    }

    obj <- obj[common, ]
    d <- detP[common, colnames(obj), drop = FALSE]
    kp <- rowMeans(d <= dp, na.rm = TRUE) >= frac
    removed_det <- rownames(d)[!kp]
    obj <- obj[kp, ]

    log("Removed by detection-P filtering: ", length(removed_det))
    log("Remaining after detection-P filtering: ", nrow(getBeta(obj)))

    before <- rownames(getBeta(obj))
    removed_snp <- character()
    if (drop_snps) {
        obj2 <- tryCatch(
            dropLociWithSnps(obj, snps = c("CpG", "SBE")),
            error = function(e) {
                warning(conditionMessage(e))
                obj
            }
        )
        removed_snp <- setdiff(before, rownames(getBeta(obj2)))
        obj <- obj2
    }
    log("Removed by SNP filtering: ", length(removed_snp))

    removed_sex <- character()
    if (remove_sex) {
        a <- as.data.frame(getAnnotation(obj))
        cc <- intersect(c("chr","CHR","Chromosome"), colnames(a))
        if (length(cc)) {
            chr <- as.character(a[[cc[1]]])
            keep <- !(chr %in% c("chrX","chrY","X","Y"))
            keep[is.na(keep)] <- TRUE
            removed_sex <- rownames(a)[!keep]
            obj <- obj[keep, ]
        }
    }
    log("Removed from sex chromosomes: ", length(removed_sex))

    final <- rownames(getBeta(obj))
    log("Final probes retained: ", length(final))
    saveRDS(obj, file.path(outdir, "filtered_object.rds"))
    write.csv(meta, file.path(outdir, "metadata_filtered.csv"),
              row.names = FALSE, quote = TRUE)

    # Build the removed-probe report safely even when one or more filters
    # remove ZERO probes. Using Reason="SNP" with Probe_ID=character(0)
    # creates a 0-vs-1 row mismatch in data.frame(), so repeat the reason
    # exactly once per removed probe.
    removed_block <- function(ids, reason) {
        ids <- as.character(ids)
        data.frame(
            Probe_ID = ids,
            Reason = rep(reason, length(ids)),
            stringsAsFactors = FALSE
        )
    }

    removed <- rbind(
        removed_block(removed_det, "DetectionP"),
        removed_block(removed_snp, "SNP"),
        removed_block(removed_sex, "SexChromosome")
    )
    write.table(removed, file.path(outdir, "removed_probes.tsv"),
                sep = "\t", quote = FALSE, row.names = FALSE)

    summary <- data.frame(
        Stage = c("Initial","AfterDetectionP","Final"),
        N = c(length(initial), length(common) - length(removed_det), length(final))
    )
    write.table(summary, file.path(outdir, "filtering_summary.tsv"),
                sep = "\t", quote = FALSE, row.names = FALSE)
    png(file.path(outdir, "01_probe_filtering.png"),
        width = 1000, height = 750, res = 150)
    barplot(summary$N, names.arg = summary$Stage, las = 2,
            ylab = "Probes", main = "EPIC probe filtering")
    dev.off()
    paste0("Probe filtering complete. Final probes: ", length(final))
}

fields <- list(
    list(name="obj", label="Step 02 normalized_object.rds", type="file",
         default=file.path(PREV, "normalized_object.rds")),
    list(name="detp", label="Step 02 detectionP_normalized_samples.rds", type="file",
         default=file.path(PREV, "detectionP_normalized_samples.rds")),
    list(name="metadata", label="Step 02 metadata_normalized_samples.csv", type="file",
         default=file.path(PREV, "metadata_normalized_samples.csv")),
    list(name="detection_p", label="Detection-P threshold", type="text", default="0.01"),
    list(name="probe_pass_fraction", label="Fraction of samples probe must pass", type="text", default="0.95"),
    list(name="drop_snps", label="SNP-associated probes", type="bool", default="TRUE",
         check_text="Remove CpG/SBE SNP-associated probes"),
    list(name="remove_sex", label="Sex chromosomes", type="bool", default="FALSE",
         check_text="Remove chrX/chrY probes"),
    list(name="out_dir", label="Step 03 output folder", type="dir", default=DEFAULT_OUT)
)
gui <- build_gui(
    "EPIC — Step 03",
    "Probe filtering",
    "Filters probes using detection P, optional SNP filtering, and optional sex-chromosome removal. Metadata are carried forward unchanged.",
    fields, run_step, output_field="out_dir"
)
tkwait.window(gui$window)
