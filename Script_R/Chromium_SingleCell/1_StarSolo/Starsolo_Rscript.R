###############################################################################
# NUMBERED BIOINFORMATICS PIPELINE
#
# This script always reads from the Input folder located beside the script and
# writes to the Output folder located beside the script.
#
# Run from RStudio or with:
#     Rscript SCRIPT_NAME.R
###############################################################################

options(stringsAsFactors = FALSE)

get_script_directory <- function() {
    command_arguments <- commandArgs(trailingOnly = FALSE)
    file_argument <- grep("^--file=", command_arguments, value = TRUE)

    if (length(file_argument) > 0L) {
        script_path <- sub("^--file=", "", file_argument[1L])
        return(dirname(normalizePath(script_path, winslash = "/", mustWork = FALSE)))
    }

    if (requireNamespace("rstudioapi", quietly = TRUE) && rstudioapi::isAvailable()) {
        active_path <- tryCatch(rstudioapi::getActiveDocumentContext()$path, error = function(e) "")
        if (nzchar(active_path)) {
            return(dirname(normalizePath(active_path, winslash = "/", mustWork = FALSE)))
        }
    }

    normalizePath(getwd(), winslash = "/", mustWork = FALSE)
}

SCRIPT_DIRECTORY <- get_script_directory()
INPUT_DIRECTORY <- file.path(SCRIPT_DIRECTORY, "Input")
OUTPUT_DIRECTORY <- file.path(SCRIPT_DIRECTORY, "Output")

dir.create(INPUT_DIRECTORY, recursive = TRUE, showWarnings = FALSE)
dir.create(OUTPUT_DIRECTORY, recursive = TRUE, showWarnings = FALSE)

LOG_FILE <- file.path(OUTPUT_DIRECTORY, "run_log.txt")
log_connection <- file(LOG_FILE, open = "wt")
sink(log_connection, type = "output", split = TRUE)
sink(log_connection, type = "message")

on.exit({
    cat("\n\n================ SESSION INFORMATION ================\n")
    print(sessionInfo())
    sink(type = "message")
    sink(type = "output")
    close(log_connection)
}, add = TRUE)

cat("Script directory:", SCRIPT_DIRECTORY, "\n")
cat("Input directory:", INPUT_DIRECTORY, "\n")
cat("Output directory:", OUTPUT_DIRECTORY, "\n")
cat("Started:", format(Sys.time()), "\n\n")

require_packages <- function(packages) {
    missing_packages <- packages[!vapply(packages, requireNamespace, logical(1), quietly = TRUE)]
    if (length(missing_packages) > 0L) {
        stop(
            "Missing required R package(s): ",
            paste(missing_packages, collapse = ", "),
            "\nRun 00_Install/00_Install_R_Packages_scRNAseq.R first."
        )
    }
}

save_session_information <- function() {
    capture.output(sessionInfo(), file = file.path(OUTPUT_DIRECTORY, "sessionInfo.txt"))
}

###############################################################################
# USER SETTINGS
###############################################################################

# Linux path to STAR inside Linux / WSL.
STAR_EXECUTABLE <- "/usr/local/bin/STAR"

# Used only when this R script is executed from native Windows R.
WSL_DISTRIBUTION <- "Debian"

THREADS <- 12L

# Supported presets in this script:
#   "10x_3p_v3"  = 16 bp cell barcode + 12 bp UMI
#   "10x_3p_v2"  = 16 bp cell barcode + 10 bp UMI
CHEMISTRY <- "10x_3p_v3"

# Set TRUE only when a BAM file is required. BAM files can be very large.
CREATE_BAM <- FALSE

# Cell calling and Cell Ranger-like barcode / UMI handling.
CELL_FILTER_METHOD <- "EmptyDrops_CR"

###############################################################################
# INTERNAL FUNCTIONS
###############################################################################

bash_quote <- function(value) {
    if (any(grepl("'", value, fixed = TRUE))) {
        stop("Single-quote characters are not supported in file paths for this wrapper.")
    }
    paste0("'", value, "'")
}

is_windows <- identical(.Platform$OS.type, "windows")

windows_to_wsl_path <- function(path) {
    normalized_path <- normalizePath(path, winslash = "\\", mustWork = FALSE)
    result <- system2(
        "wsl.exe",
        args = c("-d", WSL_DISTRIBUTION, "--", "wslpath", "-a", "-u", normalized_path),
        stdout = TRUE,
        stderr = TRUE
    )
    if (!length(result) || !nzchar(result[1L])) {
        stop("Could not convert this Windows path to a WSL path: ", path)
    }
    trimws(result[1L])
}

linux_path <- function(path) {
    if (is_windows) windows_to_wsl_path(path) else normalizePath(path, winslash = "/", mustWork = FALSE)
}

run_linux_command <- function(command) {
    cat("\nCOMMAND\n", command, "\n\n", sep = "")

    if (is_windows) {
        command_file <- tempfile(pattern = "STARsolo_command_", tmpdir = OUTPUT_DIRECTORY, fileext = ".sh")
        writeLines(c("#!/usr/bin/env bash", command), command_file, useBytes = TRUE)
        command_file_linux <- windows_to_wsl_path(command_file)
        status <- system2(
            "wsl.exe",
            args = c("-d", WSL_DISTRIBUTION, "--", "bash", command_file_linux)
        )
        unlink(command_file)
    } else {
        status <- system2("bash", args = c("-lc", command))
    }

    if (!identical(status, 0L)) {
        stop("External Linux command failed with exit status ", status)
    }
}

find_star_index <- function(root_directory) {
    candidate_directories <- unique(c(root_directory, list.dirs(root_directory, recursive = TRUE, full.names = TRUE)))
    required_files <- c("Genome", "SA", "SAindex")

    valid <- candidate_directories[vapply(
        candidate_directories,
        function(directory) all(file.exists(file.path(directory, required_files))),
        logical(1)
    )]

    if (length(valid) != 1L) {
        stop(
            "Expected exactly one STAR genome-index directory under Input. Found ",
            length(valid), ". A valid index contains Genome, SA, and SAindex."
        )
    }
    valid[1L]
}

find_barcode_whitelist <- function(root_directory) {
    candidates <- list.files(
        root_directory,
        pattern = "(whitelist|barcodes).*(txt|txt\\.gz)$",
        recursive = TRUE,
        full.names = TRUE,
        ignore.case = TRUE
    )
    if (length(candidates) != 1L) {
        stop(
            "Expected exactly one barcode-whitelist file under Input. Found ",
            length(candidates), "."
        )
    }
    candidates[1L]
}

sample_name_from_r1 <- function(filename) {
    name <- basename(filename)
    patterns <- c(
        "_S[0-9]+_L[0-9]{3}_R1_001\\.fastq\\.gz$",
        "_L[0-9]{3}_R1_001\\.fastq\\.gz$",
        "_R1_001\\.fastq\\.gz$",
        "_R1\\.fastq\\.gz$"
    )
    for (pattern in patterns) {
        updated <- sub(pattern, "", name, ignore.case = TRUE)
        if (!identical(updated, name)) return(updated)
    }
    stop("Could not infer a sample name from R1 file: ", filename)
}

matching_r2 <- function(r1_file) {
    candidates <- unique(c(
        sub("_R1_", "_R2_", r1_file, ignore.case = TRUE),
        sub("_R1\\.fastq", "_R2.fastq", r1_file, ignore.case = TRUE)
    ))
    candidates <- candidates[file.exists(candidates)]
    if (length(candidates) != 1L) {
        stop("Could not identify exactly one matching R2 file for: ", r1_file)
    }
    candidates[1L]
}

###############################################################################
# DETECT INPUTS
###############################################################################

r1_files <- list.files(
    INPUT_DIRECTORY,
    pattern = "_R1(_001)?\\.fastq\\.gz$",
    recursive = TRUE,
    full.names = TRUE,
    ignore.case = TRUE
)

if (!length(r1_files)) {
    stop("No gzipped R1 FASTQ files were found under Input.")
}

r2_files <- vapply(r1_files, matching_r2, character(1))
sample_names <- vapply(r1_files, sample_name_from_r1, character(1))

fastq_manifest <- data.frame(
    sample_id = sample_names,
    R1 = normalizePath(r1_files, winslash = "/", mustWork = TRUE),
    R2 = normalizePath(r2_files, winslash = "/", mustWork = TRUE),
    stringsAsFactors = FALSE
)

write.csv(fastq_manifest, file.path(OUTPUT_DIRECTORY, "detected_FASTQ_manifest.csv"), row.names = FALSE)

star_index <- find_star_index(INPUT_DIRECTORY)
barcode_whitelist <- find_barcode_whitelist(INPUT_DIRECTORY)

# STAR expects a plain-text barcode whitelist. Transparently decompress .gz files.
if (grepl("\\.gz$", barcode_whitelist, ignore.case = TRUE)) {
    decompressed_whitelist <- file.path(OUTPUT_DIRECTORY, "barcode_whitelist_decompressed.txt")
    input_connection <- gzfile(barcode_whitelist, open = "rb")
    output_connection <- file(decompressed_whitelist, open = "wb")
    on.exit(try(close(input_connection), silent = TRUE), add = TRUE)
    on.exit(try(close(output_connection), silent = TRUE), add = TRUE)
    repeat {
        buffer <- readBin(input_connection, what = "raw", n = 1024L * 1024L)
        if (!length(buffer)) break
        writeBin(buffer, output_connection)
    }
    close(input_connection)
    close(output_connection)
    barcode_whitelist <- decompressed_whitelist
}

chemistry_settings <- switch(
    CHEMISTRY,
    "10x_3p_v3" = list(cb_start = 1L, cb_length = 16L, umi_start = 17L, umi_length = 12L),
    "10x_3p_v2" = list(cb_start = 1L, cb_length = 16L, umi_start = 17L, umi_length = 10L),
    stop("Unsupported CHEMISTRY value: ", CHEMISTRY)
)

###############################################################################
# RUN EACH SAMPLE
###############################################################################

sample_results <- list()

for (sample_id in unique(fastq_manifest$sample_id)) {
    sample_manifest <- fastq_manifest[fastq_manifest$sample_id == sample_id, , drop = FALSE]
    sample_manifest <- sample_manifest[order(sample_manifest$R1), , drop = FALSE]

    sample_output <- file.path(OUTPUT_DIRECTORY, sample_id)
    dir.create(sample_output, recursive = TRUE, showWarnings = FALSE)

    r1_linux <- vapply(sample_manifest$R1, linux_path, character(1))
    r2_linux <- vapply(sample_manifest$R2, linux_path, character(1))
    index_linux <- linux_path(star_index)
    whitelist_linux <- linux_path(barcode_whitelist)
    output_linux <- linux_path(sample_output)

    # STARsolo requires cDNA/transcript R2 first and barcode/UMI R1 second.
    r2_argument <- paste(r2_linux, collapse = ",")
    r1_argument <- paste(r1_linux, collapse = ",")

    temporary_directory <- paste0("/tmp/STARsolo_", gsub("[^A-Za-z0-9_.-]", "_", sample_id), "_", Sys.getpid())
    output_prefix <- paste0(output_linux, "/", sample_id, "_")

    sam_arguments <- if (CREATE_BAM) {
        "--outSAMtype BAM Unsorted --outSAMattributes NH HI nM AS CR UR CB UB GX GN sS sQ sM"
    } else {
        "--outSAMtype None"
    }

    command <- paste(
        "set -euo pipefail;",
        "rm -rf", bash_quote(temporary_directory), ";",
        bash_quote(STAR_EXECUTABLE),
        "--runThreadN", THREADS,
        "--genomeDir", bash_quote(index_linux),
        "--readFilesIn", bash_quote(r2_argument), bash_quote(r1_argument),
        "--readFilesCommand zcat",
        "--soloType CB_UMI_Simple",
        "--soloCBstart", chemistry_settings$cb_start,
        "--soloCBlen", chemistry_settings$cb_length,
        "--soloUMIstart", chemistry_settings$umi_start,
        "--soloUMIlen", chemistry_settings$umi_length,
        "--soloCBwhitelist", bash_quote(whitelist_linux),
        "--soloCBmatchWLtype 1MM_multi_Nbase_pseudocounts",
        "--soloUMIfiltering MultiGeneUMI_CR",
        "--soloUMIdedup 1MM_CR",
        "--soloCellFilter", CELL_FILTER_METHOD,
        "--clipAdapterType CellRanger4",
        "--outFilterScoreMin 30",
        "--soloFeatures Gene GeneFull Velocyto",
        sam_arguments,
        "--outTmpDir", bash_quote(temporary_directory),
        "--outFileNamePrefix", bash_quote(output_prefix),
        "; rm -rf", bash_quote(temporary_directory)
    )

    run_linux_command(command)

    filtered_directory <- file.path(sample_output, paste0(sample_id, "_Solo.out"), "Gene", "filtered")
    raw_directory <- file.path(sample_output, paste0(sample_id, "_Solo.out"), "Gene", "raw")
    summary_file <- file.path(sample_output, paste0(sample_id, "_Solo.out"), "Gene", "Summary.csv")

    expected_files <- c(
        file.path(filtered_directory, "matrix.mtx"),
        file.path(filtered_directory, "barcodes.tsv"),
        file.path(filtered_directory, "features.tsv"),
        file.path(raw_directory, "matrix.mtx"),
        summary_file
    )

    missing_outputs <- expected_files[!file.exists(expected_files)]
    if (length(missing_outputs)) {
        stop("STARsolo finished but expected output files are missing:\n", paste(missing_outputs, collapse = "\n"))
    }

    sample_results[[sample_id]] <- data.frame(
        sample_id = sample_id,
        filtered_matrix_directory = normalizePath(filtered_directory, winslash = "/", mustWork = TRUE),
        raw_matrix_directory = normalizePath(raw_directory, winslash = "/", mustWork = TRUE),
        summary_file = normalizePath(summary_file, winslash = "/", mustWork = TRUE),
        stringsAsFactors = FALSE
    )
}

result_manifest <- do.call(rbind, sample_results)
write.csv(result_manifest, file.path(OUTPUT_DIRECTORY, "STARsolo_output_manifest.csv"), row.names = FALSE)

save_session_information()
cat("\nSTARsolo processing completed successfully.\n")
