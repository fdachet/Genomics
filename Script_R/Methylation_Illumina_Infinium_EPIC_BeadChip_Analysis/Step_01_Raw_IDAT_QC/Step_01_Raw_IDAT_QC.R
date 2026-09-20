
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


DEFAULT_OUT <- file.path(SCRIPT_DIR, "Step_01_Output")
dir.create(DEFAULT_OUT, recursive = TRUE, showWarnings = FALSE)

read_plan <- function(path) {
    if (!grepl("\\.tabtxt$", path, ignore.case = TRUE)) {
        stop("Experimental plan must have extension .tabtxt")
    }
    x <- read.delim(path, sep = "\t", header = TRUE, check.names = FALSE,
                    stringsAsFactors = FALSE, quote = "", comment.char = "")
    required <- c("Sample_Name", "Group", "IDAT_Basename")
    miss <- setdiff(required, colnames(x))
    if (length(miss)) stop("Missing mandatory column(s): ", paste(miss, collapse = ", "))
    if (any(!nzchar(trimws(x$Sample_Name)))) stop("Sample_Name cannot be empty.")
    if (anyDuplicated(x$Sample_Name)) stop("Sample_Name values must be unique.")
    if (any(!nzchar(trimws(x$IDAT_Basename)))) stop("IDAT_Basename cannot be empty.")
    if (anyDuplicated(x$IDAT_Basename)) stop("IDAT_Basename values must be unique.")
    x
}

is_abs_path <- function(x) {
    grepl("^[A-Za-z]:[/\\\\]", x) || grepl("^/", x)
}

resolve_basename <- function(idat_dir, b) {
    b <- trimws(as.character(b))
    if (grepl("_(Red|Grn|Green)\\.idat(\\.gz)?$", b, ignore.case = TRUE)) {
        stop("IDAT_Basename must NOT contain _Red.idat, _Grn.idat, or .gz. ",
             "Use only the shared basename, e.g. MySample")
    }
    if (is_abs_path(b)) {
        normalizePath(b, winslash = "/", mustWork = FALSE)
    } else {
        normalizePath(file.path(idat_dir, b), winslash = "/", mustWork = FALSE)
    }
}

find_channel <- function(base, channel) {
    candidates <- c(
        paste0(base, "_", channel, ".idat"),
        paste0(base, "_", channel, ".idat.gz")
    )
    found <- candidates[file.exists(candidates)]
    if (length(found) == 1) return(found[1])
    if (length(found) > 1) {
        stop("Both compressed and uncompressed files exist for basename: ", base,
             " channel: ", channel, ". Keep only one form.")
    }
    return("")
}

scan_plan <- function(v) {
    idat_dir <- normalizePath(v$idat_dir, winslash = "/", mustWork = TRUE)
    plan <- read_plan(normalizePath(v$experimental_plan, winslash = "/", mustWork = TRUE))
    rows <- vector("list", nrow(plan))
    for (i in seq_len(nrow(plan))) {
        base <- resolve_basename(idat_dir, plan$IDAT_Basename[i])
        red <- find_channel(base, "Red")
        grn <- find_channel(base, "Grn")
        rows[[i]] <- data.frame(
            Sample_Name = plan$Sample_Name[i],
            Group = plan$Group[i],
            Patient = if ("Patient" %in% colnames(plan)) plan$Patient[i] else "",
            Batch = if ("Batch" %in% colnames(plan)) plan$Batch[i] else "",
            IDAT_Basename = plan$IDAT_Basename[i],
            Red_IDAT = ifelse(nzchar(red), basename(red), "MISSING"),
            Green_IDAT = ifelse(nzchar(grn), basename(grn), "MISSING"),
            Status = ifelse(nzchar(red) && nzchar(grn), "PASS", "MISSING"),
            stringsAsFactors = FALSE
        )
    }
    do.call(rbind, rows)
}

show_scan <- function(gui) {
    tryCatch({
        sc <- scan_plan(gui$values())
        win <- tktoplevel()
        tkwm.title(win, "EPIC Step 01 — IDAT Scan")
        tkwm.geometry(win, "1250x650")
        tx <- tktext(win, wrap = "none", font = "TkFixedFont")
        tkpack(tx, fill = "both", expand = TRUE)
        ok <- sum(sc$Status == "PASS")
        tkinsert(tx, "end", paste0(
            "Samples in experimental plan: ", nrow(sc), "\n",
            "Complete Red/Green pairs: ", ok, "\n",
            "Missing/incomplete pairs: ", nrow(sc) - ok, "\n\n",
            "Required filename rule (basename may be anything):\n",
            "  <IDAT_Basename>_Red.idat   or .idat.gz\n",
            "  <IDAT_Basename>_Grn.idat   or .idat.gz\n\n",
            "Example:\n",
            "  IDAT_Basename = Patient01_Tumor\n",
            "  Patient01_Tumor_Red.idat.gz\n",
            "  Patient01_Tumor_Grn.idat.gz\n\n"
        ))
        dump <- capture.output(print(sc, row.names = FALSE))
        tkinsert(tx, "end", paste(dump, collapse = "\n"))
        tksee(tx, "end")
    }, error = function(e) {
        tkmessageBox(title = "Scan IDAT folder", message = conditionMessage(e), icon = "error")
    })
}

run_step <- function(v, log) {
    idat_dir <- normalizePath(v$idat_dir, winslash = "/", mustWork = TRUE)
    plan_path <- normalizePath(v$experimental_plan, winslash = "/", mustWork = TRUE)
    outdir <- v$out_dir
    dir.create(outdir, recursive = TRUE, showWarnings = FALSE)

    meta <- read_plan(plan_path)
    scan <- scan_plan(v)
    write.table(scan, file.path(outdir, "IDAT_scan.tsv"), sep = "\t",
                quote = FALSE, row.names = FALSE)
    if (any(scan$Status != "PASS")) {
        stop("One or more Red/Green pairs are missing. See IDAT_scan.tsv")
    }

    meta$Basename <- vapply(meta$IDAT_Basename, function(b) resolve_basename(idat_dir, b),
                            character(1))
    write.csv(meta, file.path(outdir, "metadata_raw.csv"), row.names = FALSE, quote = TRUE)

    if (!requireNamespace("minfi", quietly = TRUE)) stop("minfi is not installed.")
    suppressPackageStartupMessages(library(minfi))

    ver <- v$array_version
    if (ver == "EPICv2") {
        req <- c("IlluminaHumanMethylationEPICv2manifest",
                 "IlluminaHumanMethylationEPICv2anno.20a1.hg38")
        array_name <- "IlluminaHumanMethylationEPICv2"
        anno_name <- "20a1.hg38"
    } else {
        req <- c("IlluminaHumanMethylationEPICmanifest",
                 "IlluminaHumanMethylationEPICanno.ilm10b4.hg19")
        array_name <- "IlluminaHumanMethylationEPIC"
        anno_name <- "ilm10b4.hg19"
    }
    miss <- req[!vapply(req, requireNamespace, logical(1), quietly = TRUE)]
    if (length(miss)) stop("Missing R package(s): ", paste(miss, collapse = ", "))

    log("Reading raw IDAT files directly with minfi; no aliases/copies are created.")
    rg <- read.metharray.exp(targets = meta, extended = TRUE, force = TRUE, verbose = TRUE)
    if (ncol(rg) != nrow(meta)) stop("Unexpected number of samples returned by minfi.")
    colnames(rg) <- meta$Sample_Name
    annotation(rg) <- c(array = array_name, annotation = anno_name)
    saveRDS(rg, file.path(outdir, "rgSet_raw.rds"))

    detP <- detectionP(rg)
    saveRDS(detP, file.path(outdir, "detectionP.rds"))

    det_thresh <- as.numeric(v$detection_p)
    pass_fraction <- as.numeric(v$pass_fraction)
    fail_fraction <- colMeans(detP > det_thresh, na.rm = TRUE)
    pass_fraction_sample <- 1 - fail_fraction
    qc <- data.frame(
        Sample_Name = colnames(rg),
        Group = meta$Group[match(colnames(rg), meta$Sample_Name)],
        Mean_detection_P = colMeans(detP, na.rm = TRUE),
        Failed_probe_fraction = fail_fraction,
        Passed_probe_fraction = pass_fraction_sample,
        QC_Pass = pass_fraction_sample >= pass_fraction,
        stringsAsFactors = FALSE
    )
    write.table(qc, file.path(outdir, "sample_qc.tsv"), sep = "\t",
                quote = FALSE, row.names = FALSE)

    png(file.path(outdir, "01_detection_failure_fraction.png"),
        width = 1500, height = 900, res = 150)
    par(mar = c(10, 5, 4, 2))
    barplot(fail_fraction, names.arg = colnames(rg), las = 2,
            ylab = "Failed probe fraction",
            main = paste0("Detection P QC; P=", det_thresh))
    abline(h = 1 - pass_fraction, lty = 2, lwd = 2)
    dev.off()

    raw <- preprocessRaw(rg)
    q <- getQC(raw)
    write.table(as.data.frame(q), file.path(outdir, "raw_intensity_qc.tsv"),
                sep = "\t", quote = FALSE, col.names = NA)
    png(file.path(outdir, "02_raw_intensity_QC.png"),
        width = 1200, height = 900, res = 150)
    plotQC(q)
    dev.off()

    paste0("Raw import/QC complete for ", nrow(meta),
           " samples.\nNext: EPIC Step 02 Normalization")
}

fields <- list(
    list(name="idat_dir", label="IDAT folder", type="dir", default="",
         help="Folder containing the raw _Red/_Grn IDAT pairs."),
    list(name="experimental_plan", label="Experimental plan (.tabtxt)", type="file", default="",
         help="Mandatory columns: Sample_Name, Group, IDAT_Basename. Optional: Patient, Batch, and any other cofactors."),
    list(name="array_version", label="Array version", type="choice", default="EPICv1",
         choices=c("EPICv1","EPICv2"),
         help="GSE86831 is EPICv1."),
    list(name="detection_p", label="Detection-P threshold", type="text", default="0.01",
         help="Probe-level detection-P threshold for sample QC."),
    list(name="pass_fraction", label="Required fraction of passing probes", type="text",
         default="0.99", help="Sample QC threshold."),
    list(name="out_dir", label="Step 01 output folder", type="dir", default=DEFAULT_OUT,
         help="Created automatically beside this R script.")
)

# ----------------------------------------------------------------------
# LAUNCH GUI
# ----------------------------------------------------------------------
# build_gui() requires:
#   title, subtitle, description, fields, run_fun
#
# The previous version passed the arguments in the wrong positions:
#   - `fields` was being used as the description
#   - `run_step` was being used as the fields argument
#   - the required `run_fun` argument was omitted
#
# That prevented the GUI from launching.

gui <- tryCatch(
    build_gui(
        title = "EPIC — Step 01",
        subtitle = "Raw IDAT import and initial quality control",
        description = paste0(
            "This step validates Red/Green IDAT pairs against the experimental plan, ",
            "imports the raw methylation array data with minfi, calculates detection-P ",
            "quality-control metrics, evaluates the fraction of passing probes for each ",
            "sample, generates raw intensity QC plots, and saves the raw RGChannelSet for ",
            "the downstream normalization step."
        ),
        fields = fields,
        run_fun = run_step,
        output_field = "out_dir",
        window = "1240x900"
    ),
    error = function(e) {
        msg <- paste0(
            "The Step 01 GUI could not be launched.\n\n",
            "Error: ", conditionMessage(e), "\n\n",
            "On Windows, verify that R was installed with Tcl/Tk support."
        )
        message(msg)

        try(
            tkmessageBox(
                title = "EPIC Step 01 — Startup Error",
                message = msg,
                icon = "error"
            ),
            silent = TRUE
        )

        stop(e)
    }
)

tkpack(
    tkbutton(
        gui$button_frame,
        text = "SCAN IDAT FOLDER",
        command = function() show_scan(gui),
        background = "#C05621",
        foreground = "white"
    ),
    side = "left",
    padx = 3
)

tkwait.window(gui$window)
