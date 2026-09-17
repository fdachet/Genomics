

options(repos = c(CRAN = "https://cloud.r-project.org"))
options(BioC_mirror = "https://bioconductor.org")

install_missing <- function(packages, source_label) {
    packages <- unique(as.character(packages))
    installed <- rownames(utils::installed.packages())
    missing <- setdiff(packages, installed)
    if (!length(missing)) {
        cat(source_label, ": all packages are already installed.\n", sep = "")
        return(invisible(character(0)))
    }
    cat(source_label, ": installing ", paste(missing, collapse = ", "), "\n", sep = "")
    if (identical(source_label, "CRAN")) {
        utils::install.packages(missing, dependencies = TRUE)
    } else {
        BiocManager::install(missing, ask = FALSE, update = FALSE)
    }
    still_missing <- missing[!vapply(missing, requireNamespace, logical(1), quietly = TRUE)]
    if (length(still_missing)) {
        stop(source_label, " installation did not provide: ", paste(still_missing, collapse = ", "), call. = FALSE)
    }
    invisible(missing)
}

cran_packages <- c(
    "Seurat", "SeuratObject", "sctransform", "Matrix",
    "ggplot2", "patchwork", "scales", "matrixStats",
    "future", "future.apply", "parallelly",
    "data.table", "dplyr", "harmony", "jsonlite", "R.utils",
    "remotes",

    "Rfast2", "ape",

    "rstudioapi"
)

install_missing(cran_packages, "CRAN")

install_missing("BiocManager", "CRAN")

bioconductor_packages <- c(
    "progeny",
    "SingleCellExperiment",
    "scDblFinder",
    "edgeR",
    "DESeq2",
    "limma",
    "SingleR",
    "celldex",
    "BiocParallel"
)
install_missing(bioconductor_packages, "Bioconductor")

INSTALL_RCTD <- FALSE

if (isTRUE(INSTALL_RCTD)) {
    if (!requireNamespace("remotes", quietly = TRUE)) stop("The remotes package is required for spacexr installation.")
    if (!requireNamespace("spacexr", quietly = TRUE)) {
        cat("RCTD: installing spacexr from GitHub...\n")
        remotes::install_github("dmcable/spacexr", build_vignettes = FALSE, upgrade = "never")
    } else {
        cat("RCTD: spacexr is already installed.\n")
    }
} else {
    cat("RCTD: skipped (INSTALL_RCTD <- FALSE). Set it to TRUE only if Step 6 RCTD is required.\n")
}

cat("\nV5 package installation completed.\n")
print(utils::sessionInfo())
