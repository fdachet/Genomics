###############################################################################
# INSTALL ALL R PACKAGES USED BY THE NUMBERED scRNA-seq PIPELINE
#
# Includes:
#   Seurat object creation/QC
#   scDblFinder doublet detection
#   SCTransform with glmGamPoi
#   PCA, clustering, UMAP, and Harmony
#   Presto-accelerated Wilcoxon marker tests
#   Manual or SingleR/celldex annotation
#   edgeR pseudobulk differential expression
#
# Run once from a fresh R session.
###############################################################################

options(stringsAsFactors = FALSE)

###############################################################################
# USER SETTINGS
###############################################################################

INSTALL_OPTIONAL_BPCELLS <- FALSE
INSTALL_OPTIONAL_SPATIAL_RCTD <- FALSE
UPDATE_ALREADY_INSTALLED_PACKAGES <- FALSE

###############################################################################
# REPOSITORIES
###############################################################################

options(
    repos = c(
        CRAN = "https://cloud.r-project.org",
        satijalab = "https://satijalab.r-universe.dev",
        bnprks = "https://bnprks.r-universe.dev"
    )
)

###############################################################################
# HELPER FUNCTIONS
###############################################################################

installed_package_names <- function() {
    rownames(utils::installed.packages())
}

install_cran_packages <- function(packages) {
    packages <- unique(packages)
    installed <- installed_package_names()

    packages_to_install <- if (UPDATE_ALREADY_INSTALLED_PACKAGES) {
        packages
    } else {
        setdiff(packages, installed)
    }

    if (!length(packages_to_install)) {
        cat("All requested CRAN/R-universe packages are already installed.\n")
        return(invisible(TRUE))
    }

    cat(
        "\nInstalling CRAN/R-universe packages:\n  ",
        paste(packages_to_install, collapse = "\n  "),
        "\n",
        sep = ""
    )

    utils::install.packages(
        packages_to_install,
        dependencies = c("Depends", "Imports", "LinkingTo")
    )

    invisible(TRUE)
}

install_bioconductor_packages <- function(packages) {
    packages <- unique(packages)
    installed <- installed_package_names()

    packages_to_install <- if (UPDATE_ALREADY_INSTALLED_PACKAGES) {
        packages
    } else {
        setdiff(packages, installed)
    }

    if (!length(packages_to_install)) {
        cat("All requested Bioconductor packages are already installed.\n")
        return(invisible(TRUE))
    }

    cat(
        "\nInstalling Bioconductor packages:\n  ",
        paste(packages_to_install, collapse = "\n  "),
        "\n",
        sep = ""
    )

    BiocManager::install(
        packages_to_install,
        ask = FALSE,
        update = UPDATE_ALREADY_INSTALLED_PACKAGES,
        dependencies = c("Depends", "Imports", "LinkingTo")
    )

    invisible(TRUE)
}

verify_packages <- function(packages, category) {
    packages <- unique(packages)
    available <- vapply(
        packages,
        requireNamespace,
        logical(1),
        quietly = TRUE
    )

    data.frame(
        category = category,
        package = packages,
        installed = unname(available),
        version = vapply(
            packages,
            function(package_name) {
                if (requireNamespace(package_name, quietly = TRUE)) {
                    as.character(utils::packageVersion(package_name))
                } else {
                    NA_character_
                }
            },
            character(1)
        ),
        stringsAsFactors = FALSE
    )
}

###############################################################################
# CRAN AND R-UNIVERSE PACKAGES
###############################################################################

cran_packages <- c(
    "Seurat",
    "SeuratObject",
    "Matrix",
    "sctransform",
    "ggplot2",
    "patchwork",
    "data.table",
    "dplyr",
    "future",
    "future.apply",
    "harmony",
    "uwot",
    "RcppAnnoy",
    "irlba",
    "igraph",
    "presto",
    "remotes",
    "jsonlite",
    "R.utils",
    "rstudioapi"
)

if (INSTALL_OPTIONAL_BPCELLS) {
    cran_packages <- c(cran_packages, "BPCells")
}

install_cran_packages(cran_packages)

###############################################################################
# BIOCONDUCTOR MANAGER
###############################################################################

if (!requireNamespace("BiocManager", quietly = TRUE)) {
    utils::install.packages(
        "BiocManager",
        dependencies = c("Depends", "Imports", "LinkingTo")
    )
}

if (!requireNamespace("BiocManager", quietly = TRUE)) {
    stop("BiocManager could not be installed.")
}

cat("\nR version: ", R.version.string, "\n", sep = "")
cat("Bioconductor version: ", as.character(BiocManager::version()), "\n", sep = "")

###############################################################################
# BIOCONDUCTOR PACKAGES
###############################################################################

bioconductor_packages <- c(
    "SingleCellExperiment",
    "SummarizedExperiment",
    "S4Vectors",
    "MatrixGenerics",
    "DelayedArray",
    "scDblFinder",
    "scuttle",
    "scran",
    "glmGamPoi",
    "edgeR",
    "DESeq2",
    "limma",
    "SingleR",
    "celldex",
    "BiocParallel",
    "ExperimentHub",
    "AnnotationHub"
)

install_bioconductor_packages(bioconductor_packages)

###############################################################################
# OPTIONAL SPATIAL RCTD PACKAGE
###############################################################################

if (INSTALL_OPTIONAL_SPATIAL_RCTD) {
    if (!requireNamespace("remotes", quietly = TRUE)) {
        stop("The remotes package is required to install spacexr.")
    }

    if (!requireNamespace("spacexr", quietly = TRUE) ||
        UPDATE_ALREADY_INSTALLED_PACKAGES) {
        remotes::install_github(
            "dmcable/spacexr",
            build_vignettes = FALSE,
            upgrade = "never"
        )
    }
}

###############################################################################
# FINAL VERIFICATION
###############################################################################

verification <- rbind(
    verify_packages(cran_packages, "CRAN_or_R-universe"),
    verify_packages(bioconductor_packages, "Bioconductor")
)

if (INSTALL_OPTIONAL_SPATIAL_RCTD) {
    verification <- rbind(
        verification,
        verify_packages("spacexr", "GitHub_optional_spatial")
    )
}

verification_file <- file.path(
    getwd(),
    "R_package_installation_verification.csv"
)

utils::write.csv(
    verification,
    verification_file,
    row.names = FALSE
)

cat("\n================ PACKAGE VERIFICATION ================\n")
print(verification, row.names = FALSE)

failed_packages <- verification$package[!verification$installed]

if (length(failed_packages)) {
    stop(
        "\nPackage installation was incomplete. Missing package(s): ",
        paste(failed_packages, collapse = ", "),
        "\nSee: ", verification_file
    )
}

cat("\nAll required scRNA-seq pipeline packages are installed.\n")
cat("Verification file: ", verification_file, "\n", sep = "")
cat("\nImportant performance packages:\n")
cat("  presto installed: ", requireNamespace("presto", quietly = TRUE), "\n", sep = "")
cat("  glmGamPoi installed: ", requireNamespace("glmGamPoi", quietly = TRUE), "\n", sep = "")
cat("  sctransform installed: ", requireNamespace("sctransform", quietly = TRUE), "\n", sep = "")
cat("\nRestart R/RStudio before running the pipeline.\n\n")
print(sessionInfo())
