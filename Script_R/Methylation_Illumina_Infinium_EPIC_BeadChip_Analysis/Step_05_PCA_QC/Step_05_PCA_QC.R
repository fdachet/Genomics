

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
PREV <- file.path(EPIC_ROOT, "Step_04_Matrices", "Step_04_Output")
DEFAULT_OUT <- file.path(SCRIPT_DIR, "Step_05_Output")
dir.create(DEFAULT_OUT, recursive = TRUE, showWarnings = FALSE)

median_impute_rows <- function(m) {
    if (!anyNA(m) && all(is.finite(m))) return(m)

    row_med <- apply(m, 1, function(x) {
        y <- x[is.finite(x)]
        if (!length(y)) return(NA_real_)
        median(y)
    })

    keep <- is.finite(row_med)
    m <- m[keep, , drop = FALSE]
    row_med <- row_med[keep]

    for (i in seq_len(nrow(m))) {
        bad <- !is.finite(m[i, ])
        if (any(bad)) m[i, bad] <- row_med[i]
    }

    m
}

run_step <- function(v, log) {
    beta <- readRDS(normalizePath(v$beta, winslash = "/", mustWork = TRUE))
    meta <- read.csv(
        normalizePath(v$metadata, winslash = "/", mustWork = TRUE),
        stringsAsFactors = FALSE,
        check.names = FALSE
    )

    outdir <- v$out_dir
    dir.create(outdir, recursive = TRUE, showWarnings = FALSE)

    if (!is.matrix(beta) && !is.data.frame(beta)) {
        stop("beta_matrix.rds must contain a matrix or data.frame.")
    }

    beta <- as.matrix(beta)
    storage.mode(beta) <- "double"

    if (!("Sample_Name" %in% colnames(meta))) {
        stop("metadata_matrices.csv is missing mandatory column: Sample_Name")
    }

    samples <- intersect(as.character(meta$Sample_Name), colnames(beta))
    if (length(samples) < 2) {
        stop("Need at least 2 samples shared by beta matrix and metadata.")
    }

    meta <- meta[match(samples, meta$Sample_Name), , drop = FALSE]
    beta <- beta[, samples, drop = FALSE]

    color_col <- trimws(v$color_column)
    shape_col <- trimws(v$shape_column)

    if (!nzchar(color_col)) color_col <- "Group"

    if (!(color_col %in% colnames(meta))) {
        stop("PCA color column not found in metadata: ", color_col)
    }

    if (toupper(shape_col) != "NONE" &&
        !(shape_col %in% colnames(meta))) {
        stop("PCA shape column not found in metadata: ", shape_col)
    }

    top_n <- suppressWarnings(as.integer(v$top_variable))
    if (!is.finite(top_n) || top_n < 2) {
        stop("Most-variable CpGs must be >= 2.")
    }

    log("Samples matched: ", length(samples))
    log("CpGs in beta matrix: ", nrow(beta))

    # ------------------------------------------------------------------------
    # PCA: select the most variable CpGs.
    # Center beta values, but do NOT variance-scale each CpG.
    # ------------------------------------------------------------------------
    probe_var <- apply(beta, 1, var, na.rm = TRUE)
    valid_var <- which(is.finite(probe_var))

    if (length(valid_var) < 2) {
        stop("Fewer than 2 CpGs have finite variance.")
    }

    ord <- valid_var[order(probe_var[valid_var], decreasing = TRUE)]
    ord <- ord[seq_len(min(top_n, length(ord)))]

    pca_beta <- beta[ord, , drop = FALSE]
    pca_beta <- median_impute_rows(pca_beta)

    vv <- apply(pca_beta, 1, var)
    pca_beta <- pca_beta[is.finite(vv) & vv > 0, , drop = FALSE]

    if (nrow(pca_beta) < 2) {
        stop("Fewer than 2 variable CpGs remain for PCA.")
    }

    log("CpGs used for PCA: ", nrow(pca_beta))

    pca <- prcomp(
        t(pca_beta),
        center = TRUE,
        scale. = FALSE
    )

    explained <- 100 * pca$sdev^2 / sum(pca$sdev^2)

    pca_table <- data.frame(
        Sample_Name = rownames(pca$x),
        PC1 = pca$x[, 1],
        PC2 = if (ncol(pca$x) >= 2) pca$x[, 2] else 0,
        stringsAsFactors = FALSE
    )

    md <- meta[match(pca_table$Sample_Name, meta$Sample_Name), , drop = FALSE]

    # Preserve all metadata/cofactors in the PCA-coordinate output.
    pca_table <- cbind(
        pca_table,
        md[, setdiff(colnames(md), "Sample_Name"), drop = FALSE]
    )

    write.table(
        pca_table,
        file.path(outdir, "PCA_coordinates.tabtxt"),
        sep = "\t",
        quote = FALSE,
        row.names = FALSE
    )

    write.table(
        data.frame(
            PC = paste0("PC", seq_along(explained)),
            Variance_Percent = explained
        ),
        file.path(outdir, "PCA_variance_explained.tabtxt"),
        sep = "\t",
        quote = FALSE,
        row.names = FALSE
    )

    # ------------------------------------------------------------------------
    # PCA plot
    # ------------------------------------------------------------------------
    cf <- factor(md[[color_col]])
    clev <- levels(cf)
    cvals <- seq_along(clev)
    point_col <- cvals[cf]

    if (toupper(shape_col) != "NONE") {
        sf <- factor(md[[shape_col]])
        slev <- levels(sf)
        pvals <- rep(15:25, length.out = length(slev))
        point_pch <- pvals[sf]
    } else {
        slev <- character()
        point_pch <- rep(19, nrow(md))
    }

    png(
        file.path(outdir, "01_PCA.png"),
        width = 1300,
        height = 950,
        res = 150
    )

    plot(
        pca_table$PC1,
        pca_table$PC2,
        pch = point_pch,
        col = point_col,
        cex = 1.4,
        xlab = paste0("PC1 (", round(explained[1], 1), "%)"),
        ylab = paste0("PC2 (", round(explained[2], 1), "%)"),
        main = "EPIC PCA"
    )

    grid()

    if (as_bool(v$label_points)) {
        text(
            pca_table$PC1,
            pca_table$PC2,
            labels = pca_table$Sample_Name,
            pos = 3,
            cex = 0.75
        )
    }

    legend(
        "topright",
        legend = clev,
        col = cvals,
        pch = 19,
        title = color_col,
        bty = "n"
    )

    if (length(slev)) {
        legend(
            "bottomright",
            legend = slev,
            pch = rep(15:25, length.out = length(slev)),
            title = shape_col,
            bty = "n"
        )
    }

    dev.off()

    # ------------------------------------------------------------------------
    # Sample correlation
    # ------------------------------------------------------------------------
    corr_method <- v$correlation

    if (!(corr_method %in% c("pearson", "spearman"))) {
        stop("Correlation must be pearson or spearman.")
    }

    cor_matrix <- cor(
        beta,
        use = "pairwise.complete.obs",
        method = corr_method
    )

    write.table(
        data.frame(
            Sample_Name = rownames(cor_matrix),
            cor_matrix,
            check.names = FALSE
        ),
        file.path(outdir, "sample_correlation.tabtxt"),
        sep = "\t",
        quote = FALSE,
        row.names = FALSE
    )

    png(
        file.path(outdir, "02_sample_correlation_heatmap.png"),
        width = 1200,
        height = 1050,
        res = 150
    )

    heatmap(
        cor_matrix,
        symm = TRUE,
        scale = "none",
        margins = c(9, 9),
        main = paste("Sample correlation —", corr_method)
    )

    dev.off()

    # ------------------------------------------------------------------------
    # Hierarchical clustering
    # ------------------------------------------------------------------------
    if (v$distance_method == "1-correlation") {
        dist_obj <- as.dist(1 - cor_matrix)
    } else if (v$distance_method == "Euclidean") {
        clust_beta <- median_impute_rows(beta)
        dist_obj <- dist(t(clust_beta), method = "euclidean")
    } else {
        stop("Unknown clustering distance.")
    }

    linkage_map <- c(
        "Average" = "average",
        "Complete" = "complete",
        "Single" = "single",
        "Ward.D2" = "ward.D2"
    )

    if (!(v$linkage %in% names(linkage_map))) {
        stop("Unknown clustering linkage.")
    }

    if (v$linkage == "Ward.D2" &&
        v$distance_method != "Euclidean") {
        stop("Ward.D2 requires Euclidean distance.")
    }

    hc <- hclust(
        dist_obj,
        method = unname(linkage_map[v$linkage])
    )

    saveRDS(
        hc,
        file.path(outdir, "hierarchical_clustering.rds")
    )

    png(
        file.path(outdir, "03_hierarchical_clustering.png"),
        width = 1350,
        height = 850,
        res = 150
    )

    plot(
        hc,
        main = paste(
            "Hierarchical clustering —",
            v$distance_method,
            "/",
            v$linkage
        ),
        xlab = "",
        sub = ""
    )

    dev.off()

    # ------------------------------------------------------------------------
    # Beta-value distributions
    # ------------------------------------------------------------------------
    png(
        file.path(outdir, "04_beta_density.png"),
        width = 1300,
        height = 900,
        res = 150
    )

    dens <- lapply(seq_len(ncol(beta)), function(i) {
        x <- beta[, i]
        x <- x[is.finite(x)]

        if (length(x) < 2) {
            stop("Sample has fewer than two finite beta values: ", colnames(beta)[i])
        }

        density(x, from = 0, to = 1)
    })

    plot(
        dens[[1]],
        xlim = c(0, 1),
        xlab = "Beta value",
        ylab = "Density",
        main = "Beta-value distributions"
    )

    if (length(dens) > 1) {
        for (i in 2:length(dens)) {
            lines(dens[[i]])
        }
    }

    if (length(samples) <= 20) {
        legend(
            "topright",
            legend = samples,
            lty = 1,
            bty = "n",
            cex = 0.7
        )
    }

    dev.off()

    # ------------------------------------------------------------------------
    # Mean beta per sample
    # ------------------------------------------------------------------------
    mean_beta <- colMeans(beta, na.rm = TRUE)

    write.table(
        data.frame(
            Sample_Name = names(mean_beta),
            Mean_Beta = mean_beta
        ),
        file.path(outdir, "sample_mean_beta.tabtxt"),
        sep = "\t",
        quote = FALSE,
        row.names = FALSE
    )

    png(
        file.path(outdir, "05_mean_beta_per_sample.png"),
        width = 1300,
        height = 850,
        res = 150
    )

    par(mar = c(10, 5, 4, 2))

    barplot(
        mean_beta,
        las = 2,
        ylab = "Mean beta",
        main = "Mean methylation per sample"
    )

    dev.off()

    paste0(
        "PCA / clustering QC complete.\n",
        "Samples: ", length(samples), "\n",
        "CpGs used for PCA: ", nrow(pca_beta), "\n",
        "Results:\n", outdir
    )
}

fields <- list(
    list(
        name = "beta",
        label = "Step 04 beta_matrix.rds",
        type = "file",
        default = file.path(PREV, "beta_matrix.rds"),
        help = "Reads the native R beta matrix directly; no TSV.GZ re-import."
    ),
    list(
        name = "metadata",
        label = "Step 04 metadata_matrices.csv",
        type = "file",
        default = file.path(PREV, "metadata_matrices.csv"),
        help = "Contains Group, Patient, Batch and all cofactors propagated from Step 01."
    ),
    list(
        name = "top_variable",
        label = "Most-variable CpGs for PCA",
        type = "text",
        default = "50000",
        help = "PCA is centered but beta values are not variance-scaled."
    ),
    list(
        name = "color_column",
        label = "PCA color metadata column",
        type = "text",
        default = "Group",
        help = "Examples: Group, Batch, Sex, Treatment."
    ),
    list(
        name = "shape_column",
        label = "PCA shape metadata column",
        type = "text",
        default = "NONE",
        help = "Optional second metadata variable; use NONE to disable."
    ),
    list(
        name = "label_points",
        label = "PCA labels",
        type = "bool",
        default = "TRUE",
        check_text = "Label PCA points with Sample_Name"
    ),
    list(
        name = "correlation",
        label = "Sample correlation",
        type = "choice",
        default = "pearson",
        choices = c("pearson", "spearman")
    ),
    list(
        name = "distance_method",
        label = "Clustering distance",
        type = "choice",
        default = "1-correlation",
        choices = c("1-correlation", "Euclidean")
    ),
    list(
        name = "linkage",
        label = "Clustering linkage",
        type = "choice",
        default = "Average",
        choices = c("Average", "Complete", "Single", "Ward.D2"),
        help = "Ward.D2 is allowed only with Euclidean distance."
    ),
    list(
        name = "out_dir",
        label = "Step 05 output folder",
        type = "dir",
        default = DEFAULT_OUT
    )
)

gui <- build_gui(
    "EPIC — Step 05",
    "PCA / correlation / hierarchical clustering / methylation QC",
    paste0(
        "Direct Windows R step. Reads beta_matrix.rds from Step 04 and performs ",
        "PCA with prcomp(), sample correlation, hierarchical clustering, ",
        "beta-value density plots and mean-beta QC. Metadata from the original ",
        "experimental plan can be used to color or shape PCA points. No Python is used."
    ),
    fields,
    run_step,
    output_field = "out_dir"
)

tkwait.window(gui$window)
