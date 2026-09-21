CRAN_REPOSITORY <- "https://cloud.r-project.org"

required_packages <- c(
    "caret",
    "glmnet",
    "ranger",
    "kernlab",
    "xgboost",
    "pls",
    "MASS",
    "class",
    "pamr",
    "doParallel",
    "foreach",
    "processx"
)

options(repos = c(CRAN = CRAN_REPOSITORY))

cat("R package installer for Genomic Supervised Classification\n")
cat("R version:", R.version.string, "\n")
cat("Library paths:\n")
cat(paste0("  ", .libPaths(), collapse = "\n"), "\n\n")

installed_before <- rownames(installed.packages())
missing_before <- setdiff(required_packages, installed_before)

if (length(missing_before) == 0L) {
    cat("All required CRAN packages are already installed.\n")
} else {
    cat("Packages to install:\n")
    cat(paste0("  ", missing_before, collapse = "\n"), "\n\n")

    install.packages(
        missing_before,
        repos = CRAN_REPOSITORY,
        dependencies = c("Depends", "Imports", "LinkingTo")
    )
}

installed_after <- rownames(installed.packages())
still_missing <- setdiff(required_packages, installed_after)

load_results <- setNames(
    logical(length(required_packages)),
    required_packages
)

for (pkg in required_packages) {
    load_results[[pkg]] <- suppressPackageStartupMessages(
        require(pkg, character.only = TRUE, quietly = TRUE)
    )
}

report <- data.frame(
    Package = required_packages,
    Installed = required_packages %in% installed_after,
    Loadable = as.logical(load_results[required_packages]),
    Version = vapply(
        required_packages,
        function(pkg) {
            if (pkg %in% installed_after) {
                as.character(utils::packageVersion(pkg))
            } else {
                ""
            }
        },
        character(1)
    ),
    stringsAsFactors = FALSE
)

report_path <- file.path(getwd(), "R_Package_Installation_Report.tabtxt")

write.table(
    report,
    file = report_path,
    sep = "\t",
    quote = FALSE,
    row.names = FALSE,
    col.names = TRUE
)

cat("\nPackage status:\n")
print(report, row.names = FALSE)

if (!capabilities("tcltk") || !requireNamespace("tcltk", quietly = TRUE)) {
    cat("\nTcl/Tk is not available in this R installation.\n")
    cat("The classification GUI requires an R installation with Tcl/Tk support.\n")
} else {
    cat("\nTcl/Tk GUI support is available.\n")
}

if (length(still_missing) > 0L || any(!load_results)) {
    failed <- unique(c(
        still_missing,
        names(load_results)[!load_results]
    ))

    cat("\nInstallation is incomplete.\n")
    cat("Packages still unavailable:\n")
    cat(paste0("  ", failed, collapse = "\n"), "\n")
    cat("Report:", normalizePath(report_path, winslash = "/", mustWork = FALSE), "\n")
    stop("One or more required R packages are unavailable.")
}

cat("\nAll required packages are installed and load successfully.\n")
cat("Report:", normalizePath(report_path, winslash = "/", mustWork = FALSE), "\n")
cat("You can now run Supervised_Classification_V3_GUI_Stop.R.\n")
