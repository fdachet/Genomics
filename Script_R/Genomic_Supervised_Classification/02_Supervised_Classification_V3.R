get_script_file <- function() {
    args <- commandArgs(trailingOnly = FALSE)
    file_arg <- grep("^--file=", args, value = TRUE)
    if (length(file_arg) > 0L) {
        return(normalizePath(sub("^--file=", "", file_arg[1]), winslash = "/", mustWork = FALSE))
    }
    frames <- sys.frames()
    if (length(frames) > 0L) {
        for (i in rev(seq_along(frames))) {
            ofile <- frames[[i]]$ofile
            if (!is.null(ofile) && length(ofile) > 0L && nzchar(as.character(ofile[1]))) {
                return(normalizePath(as.character(ofile[1]), winslash = "/", mustWork = FALSE))
            }
        }
    }
    ""
}

SCRIPT_FILE <- get_script_file()
SCRIPT_DIRECTORY <- if (nzchar(SCRIPT_FILE)) dirname(SCRIPT_FILE) else getwd()
TRAIN_FILE <- file.path(SCRIPT_DIRECTORY, "Input", "Input_Trainer.tabtxt")
CLASSIFY_FILE <- file.path(SCRIPT_DIRECTORY, "Input", "Input_ToClassify.tabtxt")
OUTPUT_ROOT <- file.path(SCRIPT_DIRECTORY, "Output_Supervised_Classification")
.classification_gui_log <- NULL
.LAST_RUN_DIRECTORY <- ""

SAMPLE_ID_COLUMN <- "SampleID"
CLASS_COLUMN <- "Class"
OPTIONAL_KNOWN_CLASS_COLUMN <- "KnownClass"

ADDITIONAL_NON_FEATURE_COLUMNS <- character(0)

RANDOM_SEED <- 12345
CV_FOLDS <- 5
CV_REPEATS <- 3
MODEL_SELECTION_METRIC <- "MeanBalancedAccuracy"

NUMBER_OF_CORES <- 8

MAX_MISSING_FRACTION_PER_FEATURE <- 0.50

LDA_PCA_VARIANCE_TO_RETAIN <- 0.95

RANDOM_FOREST_NUMBER_OF_TREES <- 500

XGBOOST_NUMBER_OF_THREADS <- NUMBER_OF_CORES
XGBOOST_TREE_METHOD <- "hist"

TOP_VARIABLES_TO_PLOT <- 30

RUN_ELASTIC_NET <- TRUE
RUN_RANDOM_FOREST <- TRUE
RUN_SVM <- TRUE
RUN_GRADIENT_BOOSTING <- TRUE
RUN_PLSDA <- TRUE
RUN_LDA <- TRUE
RUN_KNN <- TRUE
RUN_NEAREST_SHRUNKEN_CENTROID <- TRUE


options(stringsAsFactors = FALSE, warn = 1)
set.seed(RANDOM_SEED)

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

load_required_packages <- function(packages) {
    installed <- rownames(installed.packages())
    missing <- setdiff(packages, installed)

    if (length(missing) > 0L) {
        stop(
            "Missing R packages: ", paste(missing, collapse = ", "),
            "\nRun 00_Install_R_Packages.R first, then restart this classification script."
        )
    }

    failed <- character(0)
    for (pkg in packages) {
        ok <- suppressPackageStartupMessages(
            require(pkg, character.only = TRUE, quietly = TRUE)
        )
        if (!ok) {
            failed <- c(failed, pkg)
        }
    }

    if (length(failed) > 0L) {
        stop(
            "Installed packages could not be loaded: ", paste(failed, collapse = ", "),
            "\nRun 00_Install_R_Packages.R and review its installation report."
        )
    }
}



write_tab <- function(x, path) {
    dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
    write.table(
        x,
        file = path,
        sep = "\t",
        quote = FALSE,
        row.names = FALSE,
        col.names = TRUE,
        na = "NA"
    )
}

write_text <- function(x, path) {
    dir.create(dirname(path), recursive = TRUE, showWarnings = FALSE)
    writeLines(as.character(x), con = path, useBytes = TRUE)
}

safe_divide <- function(numerator, denominator) {
    ifelse(is.na(denominator) | denominator == 0, NA_real_, numerator / denominator)
}

safe_mean <- function(values) {
    values <- values[is.finite(values)]
    if (length(values) == 0L) {
        return(NA_real_)
    }
    mean(values)
}

caret_classification_summary <- function(data, lev = NULL, model = NULL) {
    safe_divide_local <- function(numerator, denominator) {
        ifelse(
            is.na(denominator) | denominator == 0,
            NA_real_,
            numerator / denominator
        )
    }

    if (is.null(lev)) {
        lev <- levels(data$obs)
    }

    truth <- factor(data$obs, levels = lev)
    predicted <- factor(data$pred, levels = lev)
    confusion <- table(Truth = truth, Prediction = predicted)

    total <- sum(confusion)
    accuracy <- safe_divide_local(sum(diag(confusion)), total)
    row_totals <- rowSums(confusion)
    column_totals <- colSums(confusion)
    expected_agreement <- safe_divide_local(
        sum(row_totals * column_totals),
        total^2
    )
    kappa <- safe_divide_local(
        accuracy - expected_agreement,
        1 - expected_agreement
    )

    balanced_accuracy <- rep(NA_real_, length(lev))
    f1_values <- rep(NA_real_, length(lev))

    for (i in seq_along(lev)) {
        tp <- confusion[i, i]
        fn <- sum(confusion[i, ]) - tp
        fp <- sum(confusion[, i]) - tp
        tn <- total - tp - fn - fp

        sensitivity <- safe_divide_local(tp, tp + fn)
        specificity <- safe_divide_local(tn, tn + fp)
        precision <- safe_divide_local(tp, tp + fp)
        recall <- sensitivity

        available_balanced_components <- c(sensitivity, specificity)
        if (all(is.na(available_balanced_components))) {
            balanced_accuracy[i] <- NA_real_
        } else {
            balanced_accuracy[i] <- mean(
                available_balanced_components,
                na.rm = TRUE
            )
        }

        if (is.na(precision) && !is.na(recall) && recall == 0) {
            f1_values[i] <- 0
        } else if (!is.na(precision) && !is.na(recall) && precision + recall == 0) {
            f1_values[i] <- 0
        } else {
            f1_values[i] <- safe_divide_local(
                2 * precision * recall,
                precision + recall
            )
        }
    }

    mean_balanced_accuracy <- if (all(is.na(balanced_accuracy))) {
        NA_real_
    } else {
        mean(balanced_accuracy, na.rm = TRUE)
    }

    macro_f1 <- if (all(is.na(f1_values))) {
        NA_real_
    } else {
        mean(f1_values, na.rm = TRUE)
    }

    c(
        Accuracy = accuracy,
        Kappa = kappa,
        MeanBalancedAccuracy = mean_balanced_accuracy,
        MacroF1 = macro_f1
    )
}

collapse_named_row <- function(x) {
    if (is.null(x) || nrow(x) == 0L) {
        return("")
    }
    paste(paste(names(x), as.character(x[1, , drop = TRUE]), sep = "="), collapse = "; ")
}

map_internal_to_original_class <- function(internal_values, class_map) {
    original <- class_map$OriginalClass[
        match(as.character(internal_values), class_map$InternalClass)
    ]
    as.character(original)
}

map_original_to_internal_class <- function(original_values, class_map) {
    internal <- class_map$InternalClass[
        match(as.character(original_values), class_map$OriginalClass)
    ]
    as.character(internal)
}

read_tab_file <- function(path) {
    if (!file.exists(path)) {
        stop("Input file does not exist: ", normalizePath(path, mustWork = FALSE))
    }

    dat <- read.delim(
        file = path,
        header = TRUE,
        sep = "\t",
        quote = "",
        comment.char = "",
        check.names = FALSE,
        stringsAsFactors = FALSE,
        na.strings = c("", "NA", "NaN", "NULL", "null")
    )

    if (ncol(dat) == 0L) {
        stop("No columns were read from: ", path)
    }

    names(dat)[1] <- sub("^\\ufeff", "", names(dat)[1])
    dat
}

convert_numeric_feature_frame <- function(dat, feature_names, file_label) {
    out <- vector("list", length(feature_names))
    names(out) <- feature_names
    invalid_messages <- character(0)

    for (feature in feature_names) {
        raw <- trimws(as.character(dat[[feature]]))
        raw[raw == ""] <- NA_character_
        numeric_values <- suppressWarnings(as.numeric(raw))

        invalid <- !is.na(raw) & is.na(numeric_values)
        if (any(invalid)) {
            examples <- unique(raw[invalid])
            examples <- head(examples, 5L)
            invalid_messages <- c(
                invalid_messages,
                paste0(feature, " = ", paste(examples, collapse = ", "))
            )
        }

        numeric_values[!is.finite(numeric_values)] <- NA_real_
        out[[feature]] <- numeric_values
    }

    if (length(invalid_messages) > 0L) {
        stop(
            "Non-numeric values were found in predictor columns of ", file_label,
            ".\nExamples:\n  ", paste(invalid_messages, collapse = "\n  "),
            "\nAll predictor columns must contain numeric values or NA."
        )
    }

    as.data.frame(out, check.names = FALSE)
}

make_probability_table <- function(probabilities, sample_ids, class_map) {
    if (is.null(probabilities)) {
        return(NULL)
    }

    probabilities <- as.data.frame(probabilities, check.names = FALSE)
    internal_levels <- class_map$InternalClass

    for (level in internal_levels) {
        if (!level %in% names(probabilities)) {
            probabilities[[level]] <- NA_real_
        }
    }

    probabilities <- probabilities[, internal_levels, drop = FALSE]
    original_names <- class_map$OriginalClass[
        match(names(probabilities), class_map$InternalClass)
    ]
    names(probabilities) <- paste0("Probability_", original_names)

    data.frame(
        SampleID = sample_ids,
        probabilities,
        check.names = FALSE
    )
}

summarize_probabilities <- function(probabilities, class_map) {
    if (is.null(probabilities)) {
        return(data.frame(
            PredictedClassFromProbability = NA_character_,
            MaximumProbability = NA_real_,
            SecondBestClass = NA_character_,
            SecondBestProbability = NA_real_,
            ProbabilityMargin = NA_real_,
            stringsAsFactors = FALSE
        ))
    }

    probabilities <- as.matrix(probabilities[, class_map$InternalClass, drop = FALSE])
    predicted_internal <- character(nrow(probabilities))
    second_internal <- character(nrow(probabilities))
    maximum_probability <- numeric(nrow(probabilities))
    second_probability <- numeric(nrow(probabilities))

    for (i in seq_len(nrow(probabilities))) {
        values <- probabilities[i, ]
        if (all(is.na(values))) {
            predicted_internal[i] <- NA_character_
            second_internal[i] <- NA_character_
            maximum_probability[i] <- NA_real_
            second_probability[i] <- NA_real_
            next
        }

        order_index <- order(values, decreasing = TRUE, na.last = TRUE)
        predicted_internal[i] <- colnames(probabilities)[order_index[1]]
        maximum_probability[i] <- values[order_index[1]]

        if (length(order_index) >= 2L) {
            second_internal[i] <- colnames(probabilities)[order_index[2]]
            second_probability[i] <- values[order_index[2]]
        } else {
            second_internal[i] <- NA_character_
            second_probability[i] <- NA_real_
        }
    }

    data.frame(
        PredictedClassFromProbability = map_internal_to_original_class(
            predicted_internal,
            class_map
        ),
        MaximumProbability = maximum_probability,
        SecondBestClass = map_internal_to_original_class(
            second_internal,
            class_map
        ),
        SecondBestProbability = second_probability,
        ProbabilityMargin = maximum_probability - second_probability,
        stringsAsFactors = FALSE
    )
}

compute_classification_metrics <- function(truth_internal, predicted_internal, class_map) {
    internal_levels <- class_map$InternalClass

    truth_factor <- factor(truth_internal, levels = internal_levels)
    predicted_factor <- factor(predicted_internal, levels = internal_levels)

    confusion <- table(
        Truth = truth_factor,
        Prediction = predicted_factor,
        dnn = c("Truth", "Prediction")
    )

    total <- sum(confusion)
    correct <- sum(diag(confusion))
    accuracy <- safe_divide(correct, total)

    row_totals <- rowSums(confusion)
    column_totals <- colSums(confusion)
    expected_agreement <- safe_divide(
        sum(row_totals * column_totals),
        total^2
    )
    kappa <- safe_divide(accuracy - expected_agreement, 1 - expected_agreement)

    per_class <- vector("list", length(internal_levels))

    for (i in seq_along(internal_levels)) {
        class_name <- internal_levels[i]
        tp <- confusion[i, i]
        fn <- sum(confusion[i, ]) - tp
        fp <- sum(confusion[, i]) - tp
        tn <- total - tp - fn - fp

        sensitivity <- safe_divide(tp, tp + fn)
        specificity <- safe_divide(tn, tn + fp)
        precision <- safe_divide(tp, tp + fp)
        recall <- sensitivity
        if (is.na(precision) && !is.na(recall) && recall == 0) {
            f1 <- 0
        } else if (!is.na(precision) && !is.na(recall) && precision + recall == 0) {
            f1 <- 0
        } else {
            f1 <- safe_divide(2 * precision * recall, precision + recall)
        }
        balanced_accuracy <- safe_mean(c(sensitivity, specificity))

        per_class[[i]] <- data.frame(
            InternalClass = class_name,
            Class = map_internal_to_original_class(class_name, class_map),
            TP = as.numeric(tp),
            TN = as.numeric(tn),
            FP = as.numeric(fp),
            FN = as.numeric(fn),
            Sensitivity_Recall = sensitivity,
            Specificity = specificity,
            Precision = precision,
            F1 = f1,
            BalancedAccuracy = balanced_accuracy,
            stringsAsFactors = FALSE
        )
    }

    per_class <- do.call(rbind, per_class)

    overall <- data.frame(
        Accuracy = accuracy,
        CohenKappa = kappa,
        MacroPrecision = safe_mean(per_class$Precision),
        MacroRecall = safe_mean(per_class$Sensitivity_Recall),
        MacroF1 = safe_mean(per_class$F1),
        MeanOneVsAllBalancedAccuracy = safe_mean(per_class$BalancedAccuracy),
        NumberOfEvaluatedPredictions = total,
        stringsAsFactors = FALSE
    )

    confusion_output <- as.data.frame.matrix(confusion, stringsAsFactors = FALSE)
    confusion_output <- data.frame(
        TruthClass = class_map$OriginalClass[
            match(rownames(confusion_output), class_map$InternalClass)
        ],
        confusion_output,
        check.names = FALSE
    )
    names(confusion_output)[-1] <- paste0(
        "Predicted_",
        class_map$OriginalClass[
            match(names(confusion_output)[-1], class_map$InternalClass)
        ]
    )

    list(
        overall = overall,
        per_class = per_class,
        confusion = confusion_output
    )
}

majority_vote_internal <- function(values, internal_levels) {
    values <- as.character(values)
    values <- values[!is.na(values) & values != ""]

    if (length(values) == 0L) {
        return(list(class = NA_character_, count = 0L, tie = FALSE))
    }

    counts <- table(factor(values, levels = internal_levels))
    maximum <- max(counts)
    winners <- internal_levels[counts == maximum]

    list(
        class = winners[1],
        count = as.integer(maximum),
        tie = length(winners) > 1L,
        tied_classes = winners
    )
}

make_caret_seeds <- function(number_of_resamples, number_of_seed_values, seed) {
    set.seed(seed)
    seeds <- vector("list", number_of_resamples + 1L)

    for (i in seq_len(number_of_resamples)) {
        seeds[[i]] <- sample.int(
            .Machine$integer.max,
            number_of_seed_values,
            replace = FALSE
        )
    }

    seeds[[number_of_resamples + 1L]] <- sample.int(
        .Machine$integer.max,
        1L
    )

    seeds
}

extract_oof_predictions <- function(fit, y_internal, sample_ids, class_map) {
    pred_data <- fit$pred

    if (is.null(pred_data) || nrow(pred_data) == 0L ||
        !"rowIndex" %in% names(pred_data)) {
        return(NULL)
    }

    internal_levels <- class_map$InternalClass
    row_indices <- sort(unique(pred_data$rowIndex))
    probability_columns <- intersect(internal_levels, names(pred_data))
    has_all_probability_columns <- length(probability_columns) == length(internal_levels)

    predicted_internal <- character(length(row_indices))
    mean_probability_matrix <- matrix(
        NA_real_,
        nrow = length(row_indices),
        ncol = length(internal_levels),
        dimnames = list(NULL, internal_levels)
    )

    for (i in seq_along(row_indices)) {
        index_value <- row_indices[i]
        subset_rows <- pred_data[pred_data$rowIndex == index_value, , drop = FALSE]

        if (has_all_probability_columns) {
            class_means <- vapply(
                internal_levels,
                function(level) mean(subset_rows[[level]], na.rm = TRUE),
                numeric(1)
            )
            class_means[!is.finite(class_means)] <- NA_real_
            mean_probability_matrix[i, ] <- class_means

            if (!all(is.na(class_means))) {
                predicted_internal[i] <- internal_levels[which.max(class_means)]
            } else {
                vote <- majority_vote_internal(subset_rows$pred, internal_levels)
                predicted_internal[i] <- vote$class
            }
        } else {
            vote <- majority_vote_internal(subset_rows$pred, internal_levels)
            predicted_internal[i] <- vote$class
        }
    }

    truth_internal <- as.character(y_internal[row_indices])

    output <- data.frame(
        SampleID = sample_ids[row_indices],
        TruthClass = map_internal_to_original_class(truth_internal, class_map),
        PredictedClass = map_internal_to_original_class(
            predicted_internal,
            class_map
        ),
        stringsAsFactors = FALSE
    )

    if (has_all_probability_columns) {
        probability_output <- as.data.frame(
            mean_probability_matrix,
            check.names = FALSE
        )
        names(probability_output) <- paste0(
            "MeanOOFProbability_",
            class_map$OriginalClass
        )
        output <- cbind(output, probability_output)
    }

    list(
        table = output,
        truth_internal = truth_internal,
        predicted_internal = predicted_internal,
        probabilities_internal = if (has_all_probability_columns) {
            as.data.frame(mean_probability_matrix, check.names = FALSE)
        } else {
            NULL
        }
    )
}

save_variable_importance <- function(fit, folder, feature_map) {
    importance <- tryCatch(
        caret::varImp(fit, scale = FALSE),
        error = function(e) NULL
    )

    if (is.null(importance) || is.null(importance$importance)) {
        return(invisible(NULL))
    }

    importance_table <- as.data.frame(
        importance$importance,
        check.names = FALSE
    )
    internal_features <- rownames(importance_table)
    original_features <- feature_map$OriginalFeature[
        match(internal_features, feature_map$InternalFeature)
    ]
    original_features[is.na(original_features)] <- internal_features[
        is.na(original_features)
    ]

    importance_table <- data.frame(
        OriginalFeature = original_features,
        InternalFeature = internal_features,
        importance_table,
        check.names = FALSE
    )

    write_tab(
        importance_table,
        file.path(folder, "Variable_Importance.tabtxt")
    )

    save_top_importance_plot_from_table(
        importance_table,
        folder,
        filename = "Top_Variable_Importance.png",
        plot_title = "Top variable importance values"
    )

    invisible(NULL)
}

save_tuning_plot <- function(fit, folder) {
    if (is.null(fit$results) || nrow(fit$results) <= 1L) {
        return(invisible(NULL))
    }

    tryCatch({
        png(
            filename = file.path(folder, "Tuning_Performance.png"),
            width = 1400,
            height = 1000,
            res = 150
        )
        print(plot(fit))
        dev.off()
    }, error = function(e) {
        if (dev.cur() > 1L) {
            dev.off()
        }
        write_text(
            paste("The tuning plot could not be created:", conditionMessage(e)),
            file.path(folder, "Tuning_Plot_Error.txt")
        )
    })

    invisible(NULL)
}


safe_plot_cex <- function(labels, base_cex = 1, min_cex = 0.45) {
    labels <- as.character(labels)
    labels <- labels[!is.na(labels)]
    if (length(labels) == 0L) {
        return(base_cex)
    }
    character_lengths <- nchar(labels)
    character_lengths <- character_lengths[is.finite(character_lengths)]
    if (length(character_lengths) == 0L) {
        return(base_cex)
    }
    max_characters <- max(character_lengths)
    label_count <- length(labels)
    count_factor <- if (label_count <= 10L) 1 else sqrt(10 / label_count)
    width_factor <- if (max_characters <= 15L) 1 else 15 / max_characters
    max(min_cex, min(base_cex, base_cex * count_factor * width_factor))
}
save_top_importance_plot_from_table <- function(
    importance_table,
    folder,
    filename = "Top_Variable_Importance.png",
    plot_title = "Top variable importance values"
) {
    if (is.null(importance_table) || nrow(importance_table) == 0L) {
        return(invisible(NULL))
    }
    importance_table <- as.data.frame(importance_table, check.names = FALSE)
    feature_column <- if ("OriginalFeature" %in% names(importance_table)) {
        "OriginalFeature"
    } else if ("Feature" %in% names(importance_table)) {
        "Feature"
    } else if ("Features" %in% names(importance_table)) {
        "Features"
    } else {
        names(importance_table)[1]
    }
    numeric_column_names <- names(importance_table)[vapply(importance_table, is.numeric, logical(1))]
    if (length(numeric_column_names) == 0L) {
        return(invisible(NULL))
    }
    if ("Overall" %in% numeric_column_names) {
        score_column <- "Overall"
    } else if ("Gain" %in% numeric_column_names) {
        score_column <- "Gain"
    } else if ("importance" %in% numeric_column_names) {
        score_column <- "importance"
    } else {
        candidate_columns <- setdiff(numeric_column_names, c("Frequency", "Cover"))
        if (length(candidate_columns) == 0L) {
            candidate_columns <- numeric_column_names
        }
        aggregate_matrix <- as.matrix(importance_table[, candidate_columns, drop = FALSE])
        storage.mode(aggregate_matrix) <- "numeric"
        importance_table$Overall <- apply(abs(aggregate_matrix), 1L, safe_mean)
        score_column <- "Overall"
    }
    scores <- as.numeric(importance_table[[score_column]])
    scores[!is.finite(scores)] <- NA_real_
    keep <- which(!is.na(scores))
    if (length(keep) == 0L) {
        return(invisible(NULL))
    }
    keep <- keep[order(scores[keep], decreasing = TRUE)]
    keep <- head(keep, TOP_VARIABLES_TO_PLOT)
    labels <- as.character(importance_table[[feature_column]][keep])
    tryCatch({
        png(
            filename = file.path(folder, filename),
            width = 1400,
            height = max(900, 35 * length(keep) + 300),
            res = 150
        )
        old_par <- par(no.readonly = TRUE)
        plot_device <- dev.cur()
        on.exit({
            if (dev.cur() == plot_device) {
                par(old_par)
                dev.off()
            }
        }, add = TRUE)
        max_label_width <- if (length(labels) > 0L) max(nchar(labels), na.rm = TRUE) else 10
        par(mar = c(5, max(10, min(20, max_label_width / 1.5)), 4, 2) + 0.1)
        barplot(
            rev(scores[keep]),
            names.arg = rev(labels),
            horiz = TRUE,
            las = 1,
            xlab = score_column,
            main = plot_title,
            cex.names = safe_plot_cex(labels, base_cex = 0.9)
        )
    }, error = function(e) {
        if (dev.cur() > 1L) {
            try(dev.off(), silent = TRUE)
        }
        write_text(
            paste("The variable-importance plot could not be created:", conditionMessage(e)),
            file.path(folder, paste0(filename, ".error.txt"))
        )
    })
    invisible(NULL)
}
save_confusion_heatmap <- function(confusion_table, file_path, main_title) {
    if (is.null(confusion_table) || nrow(confusion_table) == 0L) {
        return(invisible(NULL))
    }

    confusion_table <- as.data.frame(confusion_table, check.names = FALSE)
    truth_labels <- as.character(confusion_table$TruthClass)
    prediction_columns <- setdiff(names(confusion_table), "TruthClass")
    if (length(prediction_columns) == 0L) {
        return(invisible(NULL))
    }

    predicted_labels <- sub("^Predicted_", "", prediction_columns)
    matrix_values <- as.matrix(confusion_table[, prediction_columns, drop = FALSE])
    storage.mode(matrix_values) <- "numeric"

    tryCatch({
        png(file_path, width = 1400, height = max(900, 90 * nrow(matrix_values) + 300), res = 150)
        old_par <- par(no.readonly = TRUE)
        plot_device <- dev.cur()
        on.exit({
            if (dev.cur() == plot_device) {
                par(old_par)
                dev.off()
            }
        }, add = TRUE)

        par(mar = c(8, 10, 5, 3) + 0.1)
        display_matrix <- matrix_values[nrow(matrix_values):1, , drop = FALSE]
        image(
            x = seq_len(ncol(display_matrix)),
            y = seq_len(nrow(display_matrix)),
            z = t(display_matrix),
            axes = FALSE,
            col = colorRampPalette(c("white", "khaki1", "orange", "red3"))(100),
            xlab = "Predicted class",
            ylab = "True class",
            main = main_title
        )
        axis(1, at = seq_len(ncol(display_matrix)), labels = predicted_labels, las = 2,
             cex.axis = safe_plot_cex(predicted_labels, base_cex = 1))
        axis(2, at = seq_len(nrow(display_matrix)), labels = rev(truth_labels), las = 2,
             cex.axis = safe_plot_cex(truth_labels, base_cex = 1))
        box()

        max_value <- suppressWarnings(max(matrix_values, na.rm = TRUE))
        text_cex <- if (is.finite(max_value) && max_value >= 100) 0.8 else 1
        for (i in seq_len(nrow(matrix_values))) {
            for (j in seq_len(ncol(matrix_values))) {
                text(j, nrow(matrix_values) - i + 1, labels = matrix_values[i, j], cex = text_cex)
            }
        }
    }, error = function(e) {
        if (dev.cur() > 1L) {
            dev.off()
        }
        write_text(
            paste("The confusion-matrix heatmap could not be created:", conditionMessage(e)),
            paste0(file_path, ".error.txt")
        )
    })

    invisible(NULL)
}

save_probability_heatmap <- function(
    probability_table,
    file_path,
    main_title,
    probability_prefix = "^Probability_"
) {
    if (is.null(probability_table) || nrow(probability_table) == 0L) {
        return(invisible(NULL))
    }

    probability_table <- as.data.frame(probability_table, check.names = FALSE)
    probability_columns <- grep(probability_prefix, names(probability_table), value = TRUE)
    if (length(probability_columns) == 0L || !"SampleID" %in% names(probability_table)) {
        return(invisible(NULL))
    }

    sample_labels <- as.character(probability_table$SampleID)
    class_labels <- sub(probability_prefix, "", probability_columns)
    probability_matrix <- as.matrix(probability_table[, probability_columns, drop = FALSE])
    storage.mode(probability_matrix) <- "numeric"

    tryCatch({
        png(file_path, width = 1500, height = max(900, 80 * nrow(probability_matrix) + 300), res = 150)
        old_par <- par(no.readonly = TRUE)
        plot_device <- dev.cur()
        on.exit({
            if (dev.cur() == plot_device) {
                par(old_par)
                dev.off()
            }
        }, add = TRUE)

        par(mar = c(8, max(10, min(18, max(nchar(sample_labels)) / 1.5)), 5, 3) + 0.1)
        display_matrix <- probability_matrix[nrow(probability_matrix):1, , drop = FALSE]
        image(
            x = seq_len(ncol(display_matrix)),
            y = seq_len(nrow(display_matrix)),
            z = t(display_matrix),
            zlim = c(0, 1),
            axes = FALSE,
            col = colorRampPalette(c("white", "lightblue", "dodgerblue3", "navy"))(100),
            xlab = "Class",
            ylab = "Sample",
            main = main_title
        )
        axis(1, at = seq_len(ncol(display_matrix)), labels = class_labels, las = 2,
             cex.axis = safe_plot_cex(class_labels, base_cex = 1))
        axis(2, at = seq_len(nrow(display_matrix)), labels = rev(sample_labels), las = 2,
             cex.axis = safe_plot_cex(sample_labels, base_cex = 0.95))
        box()

        for (i in seq_len(nrow(probability_matrix))) {
            for (j in seq_len(ncol(probability_matrix))) {
                label <- if (is.na(probability_matrix[i, j])) "NA" else format(round(probability_matrix[i, j], 2), nsmall = 2)
                text(j, nrow(probability_matrix) - i + 1, labels = label, cex = 0.8)
            }
        }
    }, error = function(e) {
        if (dev.cur() > 1L) {
            dev.off()
        }
        write_text(
            paste("The probability heatmap could not be created:", conditionMessage(e)),
            paste0(file_path, ".error.txt")
        )
    })

    invisible(NULL)
}

save_prediction_confidence_barplot <- function(prediction_table, file_path, main_title) {
    if (is.null(prediction_table) || nrow(prediction_table) == 0L) {
        return(invisible(NULL))
    }
    if (!all(c("SampleID", "PredictedClass", "MaximumProbability") %in% names(prediction_table))) {
        return(invisible(NULL))
    }

    prediction_table <- as.data.frame(prediction_table, check.names = FALSE)
    classes <- unique(as.character(prediction_table$PredictedClass))
    classes <- classes[!is.na(classes) & classes != ""]
    class_colors <- setNames(rainbow(max(1, length(classes))), classes)
    bar_colors <- class_colors[as.character(prediction_table$PredictedClass)]
    bar_colors[is.na(bar_colors)] <- "grey70"

    tryCatch({
        png(file_path, width = max(1400, 140 * nrow(prediction_table) + 300), height = 900, res = 150)
        old_par <- par(no.readonly = TRUE)
        plot_device <- dev.cur()
        on.exit({
            if (dev.cur() == plot_device) {
                par(old_par)
                dev.off()
            }
        }, add = TRUE)

        par(mar = c(12, 5, 5, 2) + 0.1)
        heights <- prediction_table$MaximumProbability
        heights[!is.finite(heights)] <- NA_real_
        positions <- barplot(
            heights,
            ylim = c(0, 1),
            names.arg = prediction_table$SampleID,
            las = 2,
            col = bar_colors,
            ylab = "Maximum predicted probability",
            main = main_title,
            cex.names = safe_plot_cex(prediction_table$SampleID, base_cex = 0.9)
        )
        abline(h = seq(0, 1, by = 0.1), lty = 3, col = "grey85")
        text(positions, pmin(1, heights + 0.04), labels = prediction_table$PredictedClass,
             srt = 90, adj = c(0, 0.5), xpd = TRUE, cex = 0.8)
        legend("topright", legend = names(class_colors), fill = class_colors, cex = 0.9,
               title = "Predicted class", bg = "white")
    }, error = function(e) {
        if (dev.cur() > 1L) {
            dev.off()
        }
        write_text(
            paste("The confidence barplot could not be created:", conditionMessage(e)),
            paste0(file_path, ".error.txt")
        )
    })

    invisible(NULL)
}

save_predicted_class_counts_plot <- function(prediction_table, file_path, main_title) {
    if (is.null(prediction_table) || nrow(prediction_table) == 0L || !"PredictedClass" %in% names(prediction_table)) {
        return(invisible(NULL))
    }

    counts <- table(prediction_table$PredictedClass, useNA = "ifany")
    labels <- names(counts)

    tryCatch({
        png(file_path, width = max(1100, 140 * length(counts) + 300), height = 850, res = 150)
        old_par <- par(no.readonly = TRUE)
        plot_device <- dev.cur()
        on.exit({
            if (dev.cur() == plot_device) {
                par(old_par)
                dev.off()
            }
        }, add = TRUE)

        par(mar = c(10, 5, 5, 2) + 0.1)
        bp <- barplot(
            counts,
            names.arg = labels,
            col = rainbow(length(counts)),
            las = 2,
            ylab = "Number of samples",
            main = main_title,
            cex.names = safe_plot_cex(labels, base_cex = 1)
        )
        text(bp, counts, labels = counts, pos = 3, cex = 0.95)
    }, error = function(e) {
        if (dev.cur() > 1L) {
            dev.off()
        }
        write_text(
            paste("The predicted-class-count plot could not be created:", conditionMessage(e)),
            paste0(file_path, ".error.txt")
        )
    })

    invisible(NULL)
}

save_algorithm_visualizations <- function(
    folder,
    algorithm_title,
    prediction_output,
    probability_output = NULL,
    oof_table = NULL,
    oof_confusion = NULL,
    external_confusion = NULL
) {
    save_probability_heatmap(
        probability_output,
        file.path(folder, "Classification_Probability_Heatmap.png"),
        paste0(algorithm_title, "\nPredicted class probabilities for classified samples"),
        probability_prefix = "^Probability_"
    )

    save_prediction_confidence_barplot(
        prediction_output,
        file.path(folder, "Classification_Confidence_Barplot.png"),
        paste0(algorithm_title, "\nMaximum probability of the predicted class")
    )

    save_predicted_class_counts_plot(
        prediction_output,
        file.path(folder, "Predicted_Class_Counts.png"),
        paste0(algorithm_title, "\nNumber of classified samples per predicted class")
    )

    if (!is.null(oof_table)) {
        save_probability_heatmap(
            oof_table,
            file.path(folder, "CrossValidated_OOF_Probability_Heatmap.png"),
            paste0(algorithm_title, "\nOut-of-fold class probabilities for training samples"),
            probability_prefix = "^MeanOOFProbability_"
        )
    }

    save_confusion_heatmap(
        oof_confusion,
        file.path(folder, "CrossValidated_Confusion_Matrix_Heatmap.png"),
        paste0(algorithm_title, "\nCross-validated confusion matrix")
    )

    save_confusion_heatmap(
        external_confusion,
        file.path(folder, "ExternalValidation_Confusion_Matrix_Heatmap.png"),
        paste0(algorithm_title, "\nExternal validation confusion matrix")
    )

    invisible(NULL)
}

save_metric_barplot <- function(
    performance_table,
    value_column,
    file_path,
    main_title,
    y_label
) {
    if (is.null(performance_table) || nrow(performance_table) == 0L || !value_column %in% names(performance_table)) {
        return(invisible(NULL))
    }

    performance_table <- as.data.frame(performance_table, check.names = FALSE)
    keep <- which(performance_table$Status == "SUCCESS" & is.finite(performance_table[[value_column]]))
    if (length(keep) == 0L) {
        return(invisible(NULL))
    }

    values <- performance_table[[value_column]][keep]
    labels <- performance_table$AlgorithmKey[keep]
    order_index <- order(values, decreasing = TRUE)
    values <- values[order_index]
    labels <- labels[order_index]

    tryCatch({
        png(file_path, width = max(1200, 140 * length(values) + 300), height = 900, res = 150)
        old_par <- par(no.readonly = TRUE)
        plot_device <- dev.cur()
        on.exit({
            if (dev.cur() == plot_device) {
                par(old_par)
                dev.off()
            }
        }, add = TRUE)

        par(mar = c(10, 5, 5, 2) + 0.1)
        bp <- barplot(
            values,
            names.arg = labels,
            las = 2,
            col = "steelblue",
            ylab = y_label,
            main = main_title,
            cex.names = safe_plot_cex(labels, base_cex = 1)
        )
        text(bp, values, labels = format(round(values, 3), nsmall = 3), pos = 3, cex = 0.9)
    }, error = function(e) {
        if (dev.cur() > 1L) {
            dev.off()
        }
        write_text(
            paste("The metric barplot could not be created:", conditionMessage(e)),
            paste0(file_path, ".error.txt")
        )
    })

    invisible(NULL)
}

save_algorithm_prediction_heatmap <- function(
    classification_summary,
    class_map,
    file_path,
    main_title
) {
    if (is.null(classification_summary) || nrow(classification_summary) == 0L) {
        return(invisible(NULL))
    }

    prediction_columns <- grep("^Prediction_", names(classification_summary), value = TRUE)
    prediction_columns <- c(prediction_columns, "ConsensusClass")
    prediction_columns <- prediction_columns[prediction_columns %in% names(classification_summary)]
    if (length(prediction_columns) == 0L) {
        return(invisible(NULL))
    }

    class_levels <- class_map$OriginalClass
    prediction_matrix <- as.matrix(classification_summary[, prediction_columns, drop = FALSE])
    prediction_numeric <- matrix(
        match(prediction_matrix, class_levels),
        nrow = nrow(prediction_matrix),
        ncol = ncol(prediction_matrix),
        dimnames = dimnames(prediction_matrix)
    )

    column_labels <- sub("^Prediction_", "", prediction_columns)
    column_labels[column_labels == "ConsensusClass"] <- "Consensus"
    sample_labels <- classification_summary$SampleID
    colors <- rainbow(length(class_levels))

    tryCatch({
        png(file_path, width = max(1400, 180 * length(column_labels) + 300),
            height = max(900, 80 * nrow(prediction_numeric) + 300), res = 150)
        old_par <- par(no.readonly = TRUE)
        plot_device <- dev.cur()
        on.exit({
            if (dev.cur() == plot_device) {
                par(old_par)
                dev.off()
            }
        }, add = TRUE)

        layout(matrix(c(1, 2), nrow = 1), widths = c(4, 1))
        par(mar = c(8, max(10, min(18, max(nchar(sample_labels)) / 1.5)), 5, 1) + 0.1)
        display_matrix <- prediction_numeric[nrow(prediction_numeric):1, , drop = FALSE]
        image(
            x = seq_len(ncol(display_matrix)),
            y = seq_len(nrow(display_matrix)),
            z = t(display_matrix),
            zlim = c(1, length(class_levels)),
            axes = FALSE,
            col = colors,
            xlab = "Algorithm",
            ylab = "Sample",
            main = main_title
        )
        axis(1, at = seq_len(ncol(display_matrix)), labels = column_labels, las = 2,
             cex.axis = safe_plot_cex(column_labels, base_cex = 1))
        axis(2, at = seq_len(nrow(display_matrix)), labels = rev(sample_labels), las = 2,
             cex.axis = safe_plot_cex(sample_labels, base_cex = 0.95))
        box()
        for (i in seq_len(nrow(prediction_matrix))) {
            for (j in seq_len(ncol(prediction_matrix))) {
                text(j, nrow(prediction_matrix) - i + 1,
                     labels = as.character(prediction_matrix[i, j]), cex = 0.75)
            }
        }

        par(mar = c(5, 0, 5, 2) + 0.1)
        plot.new()
        legend("center", legend = class_levels, fill = colors, title = "Class", cex = 0.95, bg = "white")
    }, error = function(e) {
        if (dev.cur() > 1L) {
            dev.off()
        }
        write_text(
            paste("The algorithm-prediction heatmap could not be created:", conditionMessage(e)),
            paste0(file_path, ".error.txt")
        )
    })

    invisible(NULL)
}

save_summary_probability_heatmap <- function(classification_summary, file_path, main_title) {
    if (is.null(classification_summary) || nrow(classification_summary) == 0L) {
        return(invisible(NULL))
    }

    probability_columns <- grep("^MeanProbability_", names(classification_summary), value = TRUE)
    if (length(probability_columns) == 0L) {
        return(invisible(NULL))
    }

    probability_table <- data.frame(
        SampleID = classification_summary$SampleID,
        classification_summary[, probability_columns, drop = FALSE],
        check.names = FALSE
    )

    names(probability_table)[-1] <- sub("^MeanProbability_", "Probability_", probability_columns)

    save_probability_heatmap(
        probability_table,
        file_path,
        main_title,
        probability_prefix = "^Probability_"
    )

    invisible(NULL)
}

save_sample_agreement_plot <- function(classification_summary, file_path, main_title) {
    required_columns <- c("SampleID", "AgreementPercent", "ConsensusMeanProbability")
    if (is.null(classification_summary) || nrow(classification_summary) == 0L ||
        !all(required_columns %in% names(classification_summary))) {
        return(invisible(NULL))
    }

    sample_labels <- classification_summary$SampleID
    agreement <- classification_summary$AgreementPercent
    confidence <- 100 * classification_summary$ConsensusMeanProbability

    tryCatch({
        png(file_path, width = max(1400, 140 * nrow(classification_summary) + 300), height = 900, res = 150)
        old_par <- par(no.readonly = TRUE)
        plot_device <- dev.cur()
        on.exit({
            if (dev.cur() == plot_device) {
                par(old_par)
                dev.off()
            }
        }, add = TRUE)

        par(mar = c(12, 5, 5, 5) + 0.1)
        bp <- barplot(
            agreement,
            ylim = c(0, 100),
            names.arg = sample_labels,
            las = 2,
            col = "darkseagreen3",
            ylab = "Agreement percent",
            main = main_title,
            cex.names = safe_plot_cex(sample_labels, base_cex = 0.9)
        )
        abline(h = seq(0, 100, by = 10), lty = 3, col = "grey85")
        lines(bp, confidence, type = "b", pch = 19)
        legend(
            "topright",
            legend = c("Agreement percent", "Consensus mean probability (%)"),
            fill = c("darkseagreen3", NA),
            border = c("black", NA),
            lty = c(NA, 1),
            pch = c(NA, 19),
            bg = "white",
            cex = 0.9
        )
    }, error = function(e) {
        if (dev.cur() > 1L) {
            dev.off()
        }
        write_text(
            paste("The sample-agreement plot could not be created:", conditionMessage(e)),
            paste0(file_path, ".error.txt")
        )
    })

    invisible(NULL)
}

save_training_pca_plot <- function(
    trainer_features,
    training_classes_original,
    training_sample_ids,
    file_path,
    main_title
) {
    if (ncol(trainer_features) < 2L || nrow(trainer_features) < 2L) {
        return(invisible(NULL))
    }

    trainer_matrix <- as.matrix(trainer_features)
    storage.mode(trainer_matrix) <- "numeric"
    medians <- apply(trainer_matrix, 2, function(x) {
        value <- stats::median(x, na.rm = TRUE)
        if (is.finite(value)) value else 0
    })
    for (j in seq_len(ncol(trainer_matrix))) {
        missing <- is.na(trainer_matrix[, j])
        if (any(missing)) {
            trainer_matrix[missing, j] <- medians[j]
        }
    }

    pca <- tryCatch(prcomp(trainer_matrix, center = TRUE, scale. = TRUE), error = function(e) NULL)
    if (is.null(pca) || ncol(pca$x) < 2L) {
        return(invisible(NULL))
    }

    variance_explained <- 100 * (pca$sdev^2 / sum(pca$sdev^2))
    classes <- unique(as.character(training_classes_original))
    class_colors <- setNames(rainbow(length(classes)), classes)
    point_colors <- class_colors[as.character(training_classes_original)]

    tryCatch({
        png(file_path, width = 1300, height = 1000, res = 150)
        old_par <- par(no.readonly = TRUE)
        plot_device <- dev.cur()
        on.exit({
            if (dev.cur() == plot_device) {
                par(old_par)
                dev.off()
            }
        }, add = TRUE)

        par(mar = c(5, 5, 5, 2) + 0.1)
        plot(
            pca$x[, 1], pca$x[, 2],
            col = point_colors,
            pch = 19,
            xlab = paste0("PC1 (", format(round(variance_explained[1], 1), nsmall = 1), "%)"),
            ylab = paste0("PC2 (", format(round(variance_explained[2], 1), nsmall = 1), "%)"),
            main = main_title
        )
        text(pca$x[, 1], pca$x[, 2], labels = training_sample_ids, pos = 3, cex = 0.75)
        legend("topright", legend = names(class_colors), fill = class_colors, title = "Training class", bg = "white")
    }, error = function(e) {
        if (dev.cur() > 1L) {
            dev.off()
        }
        write_text(
            paste("The training PCA plot could not be created:", conditionMessage(e)),
            paste0(file_path, ".error.txt")
        )
    })

    invisible(NULL)
}

save_training_and_prediction_pca_plot <- function(
    trainer_features,
    classify_features,
    training_classes_original,
    consensus_classes,
    training_sample_ids,
    classification_sample_ids,
    file_path,
    main_title
) {
    if (ncol(trainer_features) < 2L || nrow(trainer_features) < 2L || nrow(classify_features) < 1L) {
        return(invisible(NULL))
    }

    trainer_matrix <- as.matrix(trainer_features)
    classify_matrix <- as.matrix(classify_features)
    storage.mode(trainer_matrix) <- "numeric"
    storage.mode(classify_matrix) <- "numeric"

    medians <- apply(trainer_matrix, 2, function(x) {
        value <- stats::median(x, na.rm = TRUE)
        if (is.finite(value)) value else 0
    })
    for (j in seq_len(ncol(trainer_matrix))) {
        train_missing <- is.na(trainer_matrix[, j])
        test_missing <- is.na(classify_matrix[, j])
        if (any(train_missing)) {
            trainer_matrix[train_missing, j] <- medians[j]
        }
        if (any(test_missing)) {
            classify_matrix[test_missing, j] <- medians[j]
        }
    }

    pca <- tryCatch(prcomp(trainer_matrix, center = TRUE, scale. = TRUE), error = function(e) NULL)
    if (is.null(pca) || ncol(pca$x) < 2L) {
        return(invisible(NULL))
    }

    classify_scores <- tryCatch(predict(pca, newdata = classify_matrix), error = function(e) NULL)
    if (is.null(classify_scores) || ncol(classify_scores) < 2L) {
        return(invisible(NULL))
    }

    variance_explained <- 100 * (pca$sdev^2 / sum(pca$sdev^2))
    classes <- unique(c(as.character(training_classes_original), as.character(consensus_classes)))
    classes <- classes[!is.na(classes) & classes != ""]
    class_colors <- setNames(rainbow(length(classes)), classes)

    tryCatch({
        png(file_path, width = 1300, height = 1000, res = 150)
        old_par <- par(no.readonly = TRUE)
        plot_device <- dev.cur()
        on.exit({
            if (dev.cur() == plot_device) {
                par(old_par)
                dev.off()
            }
        }, add = TRUE)

        par(mar = c(5, 5, 5, 2) + 0.1)
        plot(
            pca$x[, 1], pca$x[, 2],
            col = class_colors[as.character(training_classes_original)],
            pch = 19,
            xlab = paste0("PC1 (", format(round(variance_explained[1], 1), nsmall = 1), "%)"),
            ylab = paste0("PC2 (", format(round(variance_explained[2], 1), nsmall = 1), "%)"),
            main = main_title
        )
        text(pca$x[, 1], pca$x[, 2], labels = training_sample_ids, pos = 3, cex = 0.7)
        points(
            classify_scores[, 1], classify_scores[, 2],
            col = class_colors[as.character(consensus_classes)],
            pch = 17,
            cex = 1.2
        )
        text(classify_scores[, 1], classify_scores[, 2], labels = classification_sample_ids, pos = 3, cex = 0.8)
        legend(
            "topright",
            legend = c(paste0("Training: ", names(class_colors)), paste0("To classify: ", names(class_colors))),
            col = c(class_colors, class_colors),
            pch = c(rep(19, length(class_colors)), rep(17, length(class_colors))),
            bg = "white",
            cex = 0.85
        )
    }, error = function(e) {
        if (dev.cur() > 1L) {
            dev.off()
        }
        write_text(
            paste("The combined PCA plot could not be created:", conditionMessage(e)),
            paste0(file_path, ".error.txt")
        )
    })

    invisible(NULL)
}

save_summary_visualizations <- function(
    summary_folder,
    algorithm_performance_summary,
    classification_summary,
    class_map,
    trainer_features,
    classify_features,
    training_classes_original,
    training_sample_ids,
    classification_sample_ids
) {
    save_metric_barplot(
        algorithm_performance_summary,
        "CrossValidatedBalancedAccuracy",
        file.path(summary_folder, "Algorithm_Performance_BalancedAccuracy.png"),
        "Cross-validated balanced accuracy by algorithm",
        "Balanced accuracy"
    )

    save_metric_barplot(
        algorithm_performance_summary,
        "CrossValidatedMacroF1",
        file.path(summary_folder, "Algorithm_Performance_MacroF1.png"),
        "Cross-validated macro-F1 by algorithm",
        "Macro-F1"
    )

    save_metric_barplot(
        algorithm_performance_summary,
        "CrossValidatedAccuracy",
        file.path(summary_folder, "Algorithm_Performance_Accuracy.png"),
        "Cross-validated accuracy by algorithm",
        "Accuracy"
    )

    save_metric_barplot(
        algorithm_performance_summary,
        "RuntimeMinutes",
        file.path(summary_folder, "Algorithm_Runtime_Minutes.png"),
        "Runtime by algorithm",
        "Runtime (minutes)"
    )

    save_algorithm_prediction_heatmap(
        classification_summary,
        class_map,
        file.path(summary_folder, "Algorithm_Predictions_Heatmap.png"),
        "Predicted class from each algorithm and the consensus"
    )

    save_summary_probability_heatmap(
        classification_summary,
        file.path(summary_folder, "Consensus_Mean_Probability_Heatmap.png"),
        "Mean class probability across successful algorithms"
    )

    save_sample_agreement_plot(
        classification_summary,
        file.path(summary_folder, "Consensus_Agreement_Percent.png"),
        "Agreement across algorithms for each classified sample"
    )

    save_training_pca_plot(
        trainer_features,
        training_classes_original,
        training_sample_ids,
        file.path(summary_folder, "Training_PCA.png"),
        "PCA of the training samples"
    )

    save_training_and_prediction_pca_plot(
        trainer_features,
        classify_features,
        training_classes_original,
        classification_summary$ConsensusClass,
        training_sample_ids,
        classification_sample_ids,
        file.path(summary_folder, "Training_and_Classified_Samples_PCA.png"),
        "PCA of training samples and classified samples"
    )

    invisible(NULL)
}


run_pipeline <- function() {


run_timestamp <- format(Sys.time(), "%Y%m%d_%H%M%S")
run_directory <- file.path(OUTPUT_ROOT, paste0("Run_", run_timestamp))
dir.create(run_directory, recursive = TRUE, showWarnings = FALSE)

input_check_folder <- file.path(run_directory, "00_Input_Checks")
summary_folder <- file.path(run_directory, "09_Summary")
dir.create(input_check_folder, recursive = TRUE, showWarnings = FALSE)
dir.create(summary_folder, recursive = TRUE, showWarnings = FALSE)

log_file <- file.path(run_directory, "Run_Log.txt")
log_message <- function(...) {
    text <- paste0(...)
    timestamped <- paste0("[", format(Sys.time(), "%Y-%m-%d %H:%M:%S"), "] ", text)
    cat(timestamped, "\n")
    cat(timestamped, "\n", file = log_file, append = TRUE)
    if (is.function(.classification_gui_log)) {
        try(.classification_gui_log(timestamped), silent = TRUE)
    }
}

log_message("Checking required R packages.")
load_required_packages(required_packages)
log_message("Required R packages are available.")

write_text(
    normalizePath(run_directory, mustWork = FALSE),
    file.path(OUTPUT_ROOT, "Latest_Run_Path.txt")
)

log_message("Pipeline started.")
log_message("Training file: ", normalizePath(TRAIN_FILE, mustWork = FALSE))
log_message("Classification file: ", normalizePath(CLASSIFY_FILE, mustWork = FALSE))
log_message("Output directory: ", normalizePath(run_directory, mustWork = FALSE))


trainer_raw <- read_tab_file(TRAIN_FILE)
classify_raw <- read_tab_file(CLASSIFY_FILE)

if (nrow(trainer_raw) < 4L) {
    stop("The training file must contain at least four samples.")
}
if (nrow(classify_raw) < 1L) {
    stop("The classification file does not contain any samples.")
}

required_trainer_columns <- c(SAMPLE_ID_COLUMN, CLASS_COLUMN)
missing_trainer_columns <- setdiff(required_trainer_columns, names(trainer_raw))
if (length(missing_trainer_columns) > 0L) {
    stop(
        "The training file is missing required columns: ",
        paste(missing_trainer_columns, collapse = ", ")
    )
}

if (!SAMPLE_ID_COLUMN %in% names(classify_raw)) {
    stop("The classification file is missing the required SampleID column: ", SAMPLE_ID_COLUMN)
}

trainer_raw[[SAMPLE_ID_COLUMN]] <- trimws(as.character(trainer_raw[[SAMPLE_ID_COLUMN]]))
trainer_raw[[CLASS_COLUMN]] <- trimws(as.character(trainer_raw[[CLASS_COLUMN]]))
classify_raw[[SAMPLE_ID_COLUMN]] <- trimws(as.character(classify_raw[[SAMPLE_ID_COLUMN]]))

if (any(is.na(trainer_raw[[SAMPLE_ID_COLUMN]]) | trainer_raw[[SAMPLE_ID_COLUMN]] == "")) {
    stop("The training file contains an empty SampleID.")
}
if (any(is.na(classify_raw[[SAMPLE_ID_COLUMN]]) | classify_raw[[SAMPLE_ID_COLUMN]] == "")) {
    stop("The classification file contains an empty SampleID.")
}
if (anyDuplicated(trainer_raw[[SAMPLE_ID_COLUMN]]) > 0L) {
    duplicate_ids <- unique(trainer_raw[[SAMPLE_ID_COLUMN]][
        duplicated(trainer_raw[[SAMPLE_ID_COLUMN]])
    ])
    stop("Duplicate training SampleID values: ", paste(head(duplicate_ids, 20L), collapse = ", "))
}
if (anyDuplicated(classify_raw[[SAMPLE_ID_COLUMN]]) > 0L) {
    duplicate_ids <- unique(classify_raw[[SAMPLE_ID_COLUMN]][
        duplicated(classify_raw[[SAMPLE_ID_COLUMN]])
    ])
    stop("Duplicate classification SampleID values: ", paste(head(duplicate_ids, 20L), collapse = ", "))
}
if (any(is.na(trainer_raw[[CLASS_COLUMN]]) | trainer_raw[[CLASS_COLUMN]] == "")) {
    stop("The training file contains an empty Class value.")
}

original_class_levels <- sort(unique(trainer_raw[[CLASS_COLUMN]]))
if (length(original_class_levels) < 2L) {
    stop("At least two distinct classes are required in the training file.")
}

internal_class_levels <- make.names(original_class_levels, unique = TRUE)
class_map <- data.frame(
    OriginalClass = original_class_levels,
    InternalClass = internal_class_levels,
    stringsAsFactors = FALSE
)
write_tab(class_map, file.path(input_check_folder, "Class_Name_Mapping.tabtxt"))

trainer_non_features <- unique(c(
    SAMPLE_ID_COLUMN,
    CLASS_COLUMN,
    OPTIONAL_KNOWN_CLASS_COLUMN,
    ADDITIONAL_NON_FEATURE_COLUMNS
))
classify_non_features <- unique(c(
    SAMPLE_ID_COLUMN,
    CLASS_COLUMN,
    OPTIONAL_KNOWN_CLASS_COLUMN,
    ADDITIONAL_NON_FEATURE_COLUMNS
))

training_feature_names <- setdiff(names(trainer_raw), trainer_non_features)
if (length(training_feature_names) < 1L) {
    stop("No predictor columns were found in the training file.")
}

missing_classification_features <- setdiff(training_feature_names, names(classify_raw))
if (length(missing_classification_features) > 0L) {
    stop(
        "The classification file is missing predictor columns used by the training file:\n  ",
        paste(head(missing_classification_features, 50L), collapse = "\n  "),
        if (length(missing_classification_features) > 50L) "\n  ..." else ""
    )
}

extra_classification_features <- setdiff(
    setdiff(names(classify_raw), classify_non_features),
    training_feature_names
)

trainer_features <- convert_numeric_feature_frame(
    trainer_raw,
    training_feature_names,
    "Input_Trainer.tabtxt"
)
classify_features <- convert_numeric_feature_frame(
    classify_raw,
    training_feature_names,
    "Input_ToClassify.tabtxt"
)

all_missing <- vapply(trainer_features, function(x) all(is.na(x)), logical(1))
zero_variance <- vapply(
    trainer_features,
    function(x) length(unique(x[!is.na(x)])) <= 1L,
    logical(1)
)
missing_fraction <- vapply(trainer_features, function(x) mean(is.na(x)), numeric(1))
too_many_missing <- missing_fraction > MAX_MISSING_FRACTION_PER_FEATURE

remove_feature <- all_missing | zero_variance | too_many_missing
removed_feature_table <- data.frame(
    Feature = names(trainer_features),
    AllMissingInTraining = all_missing,
    ZeroVarianceInTraining = zero_variance,
    MissingFractionInTraining = missing_fraction,
    Removed = remove_feature,
    RemovalReason = ifelse(
        all_missing,
        "All values missing",
        ifelse(
            zero_variance,
            "Zero variance",
            ifelse(too_many_missing, "Too many missing values", "Retained")
        )
    ),
    stringsAsFactors = FALSE
)
write_tab(
    removed_feature_table,
    file.path(input_check_folder, "Feature_Filtering_Report.tabtxt")
)

retained_features <- names(trainer_features)[!remove_feature]
if (length(retained_features) < 2L) {
    stop(
        "Fewer than two usable predictor columns remain after input filtering. ",
        "Review 00_Input_Checks/Feature_Filtering_Report.tabtxt."
    )
}

trainer_features <- trainer_features[, retained_features, drop = FALSE]
classify_features <- classify_features[, retained_features, drop = FALSE]

internal_feature_names <- make.names(retained_features, unique = TRUE)
feature_map <- data.frame(
    OriginalFeature = retained_features,
    InternalFeature = internal_feature_names,
    stringsAsFactors = FALSE
)
write_tab(feature_map, file.path(input_check_folder, "Feature_Name_Mapping.tabtxt"))

names(trainer_features) <- internal_feature_names
names(classify_features) <- internal_feature_names

training_sample_ids <- trainer_raw[[SAMPLE_ID_COLUMN]]
classification_sample_ids <- classify_raw[[SAMPLE_ID_COLUMN]]

y_internal_character <- map_original_to_internal_class(
    trainer_raw[[CLASS_COLUMN]],
    class_map
)
y_internal <- factor(y_internal_character, levels = internal_class_levels)

class_counts <- as.data.frame(table(trainer_raw[[CLASS_COLUMN]]), stringsAsFactors = FALSE)
names(class_counts) <- c("Class", "TrainingSampleCount")
write_tab(class_counts, file.path(input_check_folder, "Training_Class_Counts.tabtxt"))

if (min(class_counts$TrainingSampleCount) < 2L) {
    stop("Every class must contain at least two training samples.")
}

effective_cv_folds <- min(CV_FOLDS, min(class_counts$TrainingSampleCount))
if (effective_cv_folds < 2L) {
    stop("At least two cross-validation folds are required.")
}

if (effective_cv_folds != CV_FOLDS) {
    log_message(
        "CV_FOLDS was reduced from ", CV_FOLDS, " to ", effective_cv_folds,
        " because the smallest class contains only ",
        min(class_counts$TrainingSampleCount), " samples."
    )
}

known_class_original <- NULL
if (OPTIONAL_KNOWN_CLASS_COLUMN %in% names(classify_raw)) {
    known_class_original <- trimws(as.character(
        classify_raw[[OPTIONAL_KNOWN_CLASS_COLUMN]]
    ))
    nonempty_known <- !is.na(known_class_original) & known_class_original != ""
    unknown_labels <- setdiff(
        unique(known_class_original[nonempty_known]),
        class_map$OriginalClass
    )
    if (length(unknown_labels) > 0L) {
        stop(
            "KnownClass contains labels absent from the training Class column: ",
            paste(unknown_labels, collapse = ", ")
        )
    }
}

input_summary <- data.frame(
    Item = c(
        "Training samples",
        "Samples to classify",
        "Original predictor columns",
        "Retained predictor columns",
        "Removed predictor columns",
        "Number of classes",
        "Cross-validation folds",
        "Cross-validation repeats",
        "Extra classification columns ignored"
    ),
    Value = c(
        nrow(trainer_features),
        nrow(classify_features),
        length(training_feature_names),
        length(retained_features),
        sum(remove_feature),
        length(internal_class_levels),
        effective_cv_folds,
        CV_REPEATS,
        if (length(extra_classification_features) == 0L) {
            "None"
        } else {
            paste(extra_classification_features, collapse = ", ")
        }
    ),
    stringsAsFactors = FALSE
)
write_tab(input_summary, file.path(input_check_folder, "Input_Summary.tabtxt"))

log_message(
    "Input validation completed: ", nrow(trainer_features), " training samples, ",
    nrow(classify_features), " samples to classify, ",
    ncol(trainer_features), " retained features, and ",
    length(internal_class_levels), " classes."
)


set.seed(RANDOM_SEED)
cv_training_indices <- caret::createMultiFolds(
    y_internal,
    k = effective_cv_folds,
    times = CV_REPEATS
)
cv_holdout_indices <- lapply(
    cv_training_indices,
    function(training_indices) setdiff(seq_along(y_internal), training_indices)
)

fold_membership <- do.call(rbind, lapply(names(cv_holdout_indices), function(fold_name) {
    indices <- cv_holdout_indices[[fold_name]]
    data.frame(
        Resample = fold_name,
        RowIndex = indices,
        SampleID = training_sample_ids[indices],
        Class = trainer_raw[[CLASS_COLUMN]][indices],
        stringsAsFactors = FALSE
    )
}))
write_tab(
    fold_membership,
    file.path(input_check_folder, "CrossValidation_Holdout_Assignments.tabtxt")
)


number_of_cores_to_use <- max(1L, as.integer(NUMBER_OF_CORES))
parallel_cluster <- NULL

if (number_of_cores_to_use > 1L) {
    parallel_cluster <- parallel::makePSOCKcluster(number_of_cores_to_use)
    doParallel::registerDoParallel(parallel_cluster)
    log_message("Parallel backend registered with ", number_of_cores_to_use, " workers.")
} else {
    foreach::registerDoSEQ()
    log_message("Parallel processing disabled; one worker will be used.")
}

on.exit({
    if (!is.null(parallel_cluster)) {
        try(parallel::stopCluster(parallel_cluster), silent = TRUE)
    }
}, add = TRUE)


number_of_features <- ncol(trainer_features)
minimum_resample_training_size <- min(vapply(
    cv_training_indices,
    length,
    integer(1)
))

elastic_net_grid <- expand.grid(
    alpha = c(0, 0.25, 0.50, 0.75, 1.00),
    lambda = 10^seq(-4, 1, length.out = 10)
)

ranger_mtry_values <- unique(pmax(
    1L,
    pmin(
        number_of_features,
        round(c(
            sqrt(number_of_features),
            number_of_features / 10,
            number_of_features / 3
        ))
    )
))
ranger_grid <- expand.grid(
    mtry = ranger_mtry_values,
    splitrule = "gini",
    min.node.size = c(1L, 5L, 10L)
)

xgboost_grid <- expand.grid(
    nrounds = c(100L, 300L),
    max_depth = c(2L, 4L),
    eta = c(0.05, 0.10),
    gamma = 0,
    colsample_bytree = c(0.75, 1.00),
    min_child_weight = 1,
    subsample = 0.80
)

maximum_pls_components <- max(
    1L,
    min(
        10L,
        number_of_features,
        minimum_resample_training_size - 1L
    )
)
pls_grid <- expand.grid(ncomp = seq_len(maximum_pls_components))

maximum_knn_k <- max(1L, min(21L, minimum_resample_training_size - 1L))
knn_values <- seq.int(1L, maximum_knn_k, by = 2L)
if (length(knn_values) == 0L) {
    knn_values <- 1L
}
knn_grid <- expand.grid(k = knn_values)

algorithm_specs <- list(
    list(
        enabled = RUN_ELASTIC_NET,
        key = "ElasticNet",
        display_name = "Elastic-net logistic/multinomial regression",
        folder = "01_ElasticNet_Logistic",
        method = "glmnet",
        preprocess = c("zv", "medianImpute", "center", "scale"),
        tune_grid = elastic_net_grid,
        tune_length = NULL,
        extra_arguments = list()
    ),
    list(
        enabled = RUN_RANDOM_FOREST,
        key = "RandomForest",
        display_name = "Random forest",
        folder = "02_RandomForest",
        method = "ranger",
        preprocess = c("zv", "medianImpute"),
        tune_grid = ranger_grid,
        tune_length = NULL,
        extra_arguments = list(
            num.trees = RANDOM_FOREST_NUMBER_OF_TREES,
            importance = "permutation",
            num.threads = 1L
        )
    ),
    list(
        enabled = RUN_SVM,
        key = "SVM",
        display_name = "Support vector machine with radial kernel",
        folder = "03_SVM",
        method = "svmRadial",
        preprocess = c("zv", "medianImpute", "center", "scale"),
        tune_grid = NULL,
        tune_length = 7L,
        extra_arguments = list()
    ),
    list(
        enabled = RUN_GRADIENT_BOOSTING,
        key = "GradientBoosting",
        display_name = "Gradient boosting with native XGBoost",
        folder = "04_GradientBoosting",
        method = "native_xgb_train",
        preprocess = c("medianImpute"),
        tune_grid = xgboost_grid,
        tune_length = NULL,
        extra_arguments = list()
    ),
    list(
        enabled = RUN_PLSDA,
        key = "PLSDA",
        display_name = "Partial least-squares discriminant analysis",
        folder = "05_PLSDA",
        method = "pls",
        preprocess = c("zv", "medianImpute", "center", "scale"),
        tune_grid = pls_grid,
        tune_length = NULL,
        extra_arguments = list()
    ),
    list(
        enabled = RUN_LDA,
        key = "LDA",
        display_name = "Linear discriminant analysis with PCA preprocessing",
        folder = "06_LDA",
        method = "lda",
        preprocess = c("zv", "medianImpute", "center", "scale", "pca"),
        tune_grid = NULL,
        tune_length = 1L,
        extra_arguments = list()
    ),
    list(
        enabled = RUN_KNN,
        key = "kNN",
        display_name = "k-nearest neighbors",
        folder = "07_kNN",
        method = "knn",
        preprocess = c("zv", "medianImpute", "center", "scale"),
        tune_grid = knn_grid,
        tune_length = NULL,
        extra_arguments = list()
    ),
    list(
        enabled = RUN_NEAREST_SHRUNKEN_CENTROID,
        key = "NearestShrunkenCentroid",
        display_name = "Nearest shrunken centroid",
        folder = "08_NearestShrunkenCentroid",
        method = "pam",
        preprocess = c("zv", "medianImpute"),
        tune_grid = NULL,
        tune_length = 15L,
        extra_arguments = list()
    )
)


xgb_fit_medians <- function(x) {
    vapply(
        x,
        function(values) {
            value <- suppressWarnings(stats::median(values, na.rm = TRUE))
            if (is.finite(value)) as.numeric(value) else 0
        },
        numeric(1)
    )
}

xgb_apply_medians <- function(x, medians) {
    x <- as.data.frame(x, check.names = FALSE)
    x <- x[, names(medians), drop = FALSE]

    for (feature in names(medians)) {
        replace_index <- is.na(x[[feature]]) | !is.finite(x[[feature]])
        if (any(replace_index)) {
            x[[feature]][replace_index] <- medians[[feature]]
        }
    }

    x <- as.matrix(x)
    storage.mode(x) <- "double"
    x
}

xgb_make_probability_matrix <- function(raw_prediction, n_samples, class_levels) {
    n_classes <- length(class_levels)

    if (n_classes == 2L) {
        positive_probability <- as.numeric(raw_prediction)
        if (length(positive_probability) != n_samples) {
            stop(
                "Binary XGBoost returned ", length(positive_probability),
                " values for ", n_samples, " samples."
            )
        }
        probability_matrix <- cbind(
            1 - positive_probability,
            positive_probability
        )
    } else {
        if (is.matrix(raw_prediction)) {
            probability_matrix <- raw_prediction
        } else {
            raw_prediction <- as.numeric(raw_prediction)
            if (length(raw_prediction) != n_samples * n_classes) {
                stop(
                    "Multiclass XGBoost returned ", length(raw_prediction),
                    " values; expected ", n_samples * n_classes, "."
                )
            }
            probability_matrix <- matrix(
                raw_prediction,
                nrow = n_samples,
                ncol = n_classes,
                byrow = TRUE
            )
        }
    }

    if (nrow(probability_matrix) != n_samples &&
        ncol(probability_matrix) == n_samples) {
        probability_matrix <- t(probability_matrix)
    }

    if (nrow(probability_matrix) != n_samples ||
        ncol(probability_matrix) != n_classes) {
        stop(
            "Unexpected XGBoost probability dimensions: ",
            paste(dim(probability_matrix), collapse = " x "),
            "; expected ", n_samples, " x ", n_classes, "."
        )
    }

    probability_matrix[!is.finite(probability_matrix)] <- NA_real_

    probability_matrix[
        !is.na(probability_matrix) & probability_matrix < 0
    ] <- 0
    probability_matrix[
        !is.na(probability_matrix) & probability_matrix > 1
    ] <- 1

    probability_sums <- rowSums(probability_matrix, na.rm = TRUE)
    valid <- is.finite(probability_sums) & probability_sums > 0

    if (any(valid)) {
        probability_matrix[valid, ] <- sweep(
            probability_matrix[valid, , drop = FALSE],
            MARGIN = 1L,
            STATS = probability_sums[valid],
            FUN = "/"
        )
    }

    colnames(probability_matrix) <- class_levels
    probability_matrix
}

xgb_predict_probability_matrix <- function(model, x_matrix, class_levels) {
    prediction <- predict(
        model,
        xgboost::xgb.DMatrix(x_matrix, missing = NA_real_)
    )
    xgb_make_probability_matrix(
        prediction,
        nrow(x_matrix),
        class_levels
    )
}

xgb_probability_to_class <- function(probability_matrix, class_levels) {
    apply(probability_matrix, 1L, function(values) {
        if (all(is.na(values))) {
            NA_character_
        } else {
            class_levels[which.max(values)]
        }
    })
}

xgb_fit_model <- function(
    x_matrix,
    y_factor,
    tuning_row,
    class_levels,
    seed
) {
    n_classes <- length(class_levels)
    labels <- as.integer(factor(y_factor, levels = class_levels)) - 1L

    parameters <- list(
        booster = "gbtree",
        objective = if (n_classes == 2L) {
            "binary:logistic"
        } else {
            "multi:softprob"
        },
        eval_metric = if (n_classes == 2L) "logloss" else "mlogloss",
        max_depth = as.integer(tuning_row$max_depth),
        eta = as.numeric(tuning_row$eta),
        gamma = as.numeric(tuning_row$gamma),
        colsample_bytree = as.numeric(tuning_row$colsample_bytree),
        min_child_weight = as.numeric(tuning_row$min_child_weight),
        subsample = as.numeric(tuning_row$subsample),
        tree_method = XGBOOST_TREE_METHOD,
        nthread = max(1L, as.integer(XGBOOST_NUMBER_OF_THREADS)),
        seed = as.integer(seed)
    )

    if (n_classes > 2L) {
        parameters$num_class <- n_classes
    }

    xgboost::xgb.train(
        params = parameters,
        data = xgboost::xgb.DMatrix(
            data = x_matrix,
            label = labels,
            missing = NA_real_
        ),
        nrounds = as.integer(tuning_row$nrounds),
        verbose = 0
    )
}

run_native_xgboost <- function(specification, algorithm_number) {
    algorithm_folder <- file.path(run_directory, specification$folder)
    dir.create(algorithm_folder, recursive = TRUE, showWarnings = FALSE)

    log_message("Starting: ", specification$display_name)
    start_time <- Sys.time()

    class_levels <- internal_class_levels
    grid <- specification$tune_grid
    n_resamples <- length(cv_training_indices)
    metric_names <- c(
        "Accuracy",
        "Kappa",
        "MeanBalancedAccuracy",
        "MacroF1"
    )

    tuning_results <- grid
    for (metric_name in metric_names) {
        tuning_results[[metric_name]] <- NA_real_
        tuning_results[[paste0(metric_name, "SD")]] <- NA_real_
    }
    tuning_results$SuccessfulResamples <- 0L
    tuning_results$FailedResamples <- 0L

    error_rows <- list()

    for (grid_row in seq_len(nrow(grid))) {
        fold_metrics <- matrix(
            NA_real_,
            nrow = n_resamples,
            ncol = length(metric_names),
            dimnames = list(names(cv_training_indices), metric_names)
        )

        for (fold_number in seq_len(n_resamples)) {
            train_index <- cv_training_indices[[fold_number]]
            test_index <- cv_holdout_indices[[fold_number]]

            fold_result <- tryCatch({
                medians <- xgb_fit_medians(
                    trainer_features[train_index, , drop = FALSE]
                )
                x_train <- xgb_apply_medians(
                    trainer_features[train_index, , drop = FALSE],
                    medians
                )
                x_test <- xgb_apply_medians(
                    trainer_features[test_index, , drop = FALSE],
                    medians
                )

                model <- xgb_fit_model(
                    x_matrix = x_train,
                    y_factor = y_internal[train_index],
                    tuning_row = grid[grid_row, , drop = FALSE],
                    class_levels = class_levels,
                    seed = RANDOM_SEED +
                        algorithm_number * 100000L +
                        grid_row * 1000L +
                        fold_number
                )

                probabilities <- xgb_predict_probability_matrix(
                    model,
                    x_test,
                    class_levels
                )
                predicted <- xgb_probability_to_class(
                    probabilities,
                    class_levels
                )

                caret_classification_summary(
                    data.frame(
                        obs = factor(
                            y_internal[test_index],
                            levels = class_levels
                        ),
                        pred = factor(predicted, levels = class_levels)
                    ),
                    lev = class_levels
                )
            }, error = function(e) {
                error_rows[[length(error_rows) + 1L]] <<- data.frame(
                    GridRow = grid_row,
                    Resample = names(cv_training_indices)[fold_number],
                    ErrorMessage = conditionMessage(e),
                    stringsAsFactors = FALSE
                )
                NULL
            })

            if (!is.null(fold_result)) {
                fold_metrics[fold_number, ] <- fold_result[metric_names]
            }
        }

        for (metric_name in metric_names) {
            values <- fold_metrics[, metric_name]
            finite_values <- values[is.finite(values)]
            if (length(finite_values) > 0L) {
                tuning_results[grid_row, metric_name] <- mean(finite_values)
            }
            if (length(finite_values) > 1L) {
                tuning_results[
                    grid_row,
                    paste0(metric_name, "SD")
                ] <- stats::sd(finite_values)
            }
        }

        tuning_results$SuccessfulResamples[grid_row] <- sum(
            is.finite(fold_metrics[, MODEL_SELECTION_METRIC])
        )
        tuning_results$FailedResamples[grid_row] <-
            n_resamples - tuning_results$SuccessfulResamples[grid_row]
    }

    write_tab(
        tuning_results,
        file.path(algorithm_folder, "Tuning_Results.tabtxt")
    )

    if (length(error_rows) > 0L) {
        write_tab(
            do.call(rbind, error_rows),
            file.path(
                algorithm_folder,
                "Native_XGBoost_Fit_Errors.tabtxt"
            )
        )
    }

    if (!MODEL_SELECTION_METRIC %in% names(tuning_results)) {
        stop(
            "MODEL_SELECTION_METRIC is unavailable for XGBoost: ",
            MODEL_SELECTION_METRIC
        )
    }

    valid_grid_rows <- which(
        is.finite(tuning_results[[MODEL_SELECTION_METRIC]])
    )
    if (length(valid_grid_rows) == 0L) {
        first_error <- if (length(error_rows) > 0L) {
            error_rows[[1L]]$ErrorMessage
        } else {
            "No detailed native XGBoost error was captured."
        }
        stop(
            "Every native XGBoost tuning combination failed. First error: ",
            first_error,
            ". See Native_XGBoost_Fit_Errors.tabtxt."
        )
    }

    best_grid_row <- valid_grid_rows[
        which.max(
            tuning_results[[MODEL_SELECTION_METRIC]][valid_grid_rows]
        )
    ]
    best_tune <- grid[best_grid_row, , drop = FALSE]

    write_tab(
        best_tune,
        file.path(algorithm_folder, "Best_Tuning_Parameters.tabtxt")
    )

    oof_probability_sum <- matrix(
        0,
        nrow = nrow(trainer_features),
        ncol = length(class_levels),
        dimnames = list(NULL, class_levels)
    )
    oof_count <- integer(nrow(trainer_features))
    resampling_rows <- list()

    for (fold_number in seq_len(n_resamples)) {
        train_index <- cv_training_indices[[fold_number]]
        test_index <- cv_holdout_indices[[fold_number]]

        medians <- xgb_fit_medians(
            trainer_features[train_index, , drop = FALSE]
        )
        x_train <- xgb_apply_medians(
            trainer_features[train_index, , drop = FALSE],
            medians
        )
        x_test <- xgb_apply_medians(
            trainer_features[test_index, , drop = FALSE],
            medians
        )

        model <- xgb_fit_model(
            x_matrix = x_train,
            y_factor = y_internal[train_index],
            tuning_row = best_tune,
            class_levels = class_levels,
            seed = RANDOM_SEED +
                algorithm_number * 100000L +
                best_grid_row * 1000L +
                fold_number
        )
        probabilities <- xgb_predict_probability_matrix(
            model,
            x_test,
            class_levels
        )
        predicted <- xgb_probability_to_class(
            probabilities,
            class_levels
        )
        fold_metrics <- caret_classification_summary(
            data.frame(
                obs = factor(y_internal[test_index], levels = class_levels),
                pred = factor(predicted, levels = class_levels)
            ),
            lev = class_levels
        )

        resampling_rows[[fold_number]] <- data.frame(
            Resample = names(cv_training_indices)[fold_number],
            Accuracy = unname(fold_metrics["Accuracy"]),
            Kappa = unname(fold_metrics["Kappa"]),
            MeanBalancedAccuracy =
                unname(fold_metrics["MeanBalancedAccuracy"]),
            MacroF1 = unname(fold_metrics["MacroF1"]),
            stringsAsFactors = FALSE
        )

        oof_probability_sum[test_index, ] <-
            oof_probability_sum[test_index, , drop = FALSE] +
            probabilities
        oof_count[test_index] <- oof_count[test_index] + 1L
    }

    write_tab(
        do.call(rbind, resampling_rows),
        file.path(algorithm_folder, "Resampling_Results.tabtxt")
    )

    if (any(oof_count == 0L)) {
        stop(
            "At least one training sample has no out-of-fold ",
            "XGBoost prediction."
        )
    }

    oof_probabilities <- oof_probability_sum / oof_count
    oof_prediction_internal <- xgb_probability_to_class(
        oof_probabilities,
        class_levels
    )
    oof_truth_internal <- as.character(y_internal)

    oof_table <- data.frame(
        SampleID = training_sample_ids,
        TruthClass = map_internal_to_original_class(
            oof_truth_internal,
            class_map
        ),
        PredictedClass = map_internal_to_original_class(
            oof_prediction_internal,
            class_map
        ),
        stringsAsFactors = FALSE
    )
    oof_probability_table <- as.data.frame(
        oof_probabilities,
        check.names = FALSE
    )
    names(oof_probability_table) <- paste0(
        "MeanOOFProbability_",
        class_map$OriginalClass
    )
    write_tab(
        cbind(oof_table, oof_probability_table),
        file.path(
            algorithm_folder,
            "CrossValidated_Training_Predictions.tabtxt"
        )
    )

    oof_metrics <- compute_classification_metrics(
        oof_truth_internal,
        oof_prediction_internal,
        class_map
    )
    write_tab(
        oof_metrics$overall,
        file.path(
            algorithm_folder,
            "CrossValidated_Overall_Metrics.tabtxt"
        )
    )
    write_tab(
        oof_metrics$per_class,
        file.path(
            algorithm_folder,
            "CrossValidated_PerClass_Metrics.tabtxt"
        )
    )
    write_tab(
        oof_metrics$confusion,
        file.path(
            algorithm_folder,
            "CrossValidated_Confusion_Matrix.tabtxt"
        )
    )

    final_medians <- xgb_fit_medians(trainer_features)
    final_x_train <- xgb_apply_medians(
        trainer_features,
        final_medians
    )
    final_x_classify <- xgb_apply_medians(
        classify_features,
        final_medians
    )

    final_model <- xgb_fit_model(
        x_matrix = final_x_train,
        y_factor = y_internal,
        tuning_row = best_tune,
        class_levels = class_levels,
        seed = RANDOM_SEED + algorithm_number
    )

    xgboost::xgb.save(
        final_model,
        file.path(algorithm_folder, "Trained_Model.json")
    )
    saveRDS(
        list(
            TrainingMedians = final_medians,
            InternalFeatureNames = colnames(final_x_train),
            InternalClassLevels = class_levels,
            ClassMap = class_map,
            FeatureMap = feature_map,
            BestTune = best_tune,
            XGBoostVersion = as.character(
                utils::packageVersion("xgboost")
            )
        ),
        file.path(
            algorithm_folder,
            "Preprocessing_and_Model_Metadata.rds"
        )
    )

    capture.output({
        cat("Native XGBoost model\n")
        cat(
            "XGBoost version:",
            as.character(utils::packageVersion("xgboost")),
            "\n"
        )
        cat("caret xgbTree wrapper used: FALSE\n")
        cat(
            "Objective:",
            if (length(class_levels) == 2L) {
                "binary:logistic"
            } else {
                "multi:softprob"
            },
            "\n"
        )
        cat("Best tuning parameters:\n")
        print(best_tune)
        cat("\nFinal booster:\n")
        print(final_model)
    }, file = file.path(algorithm_folder, "Model_Summary.txt"))

    probability_internal <- as.data.frame(
        xgb_predict_probability_matrix(
            final_model,
            final_x_classify,
            class_levels
        ),
        check.names = FALSE
    )
    prediction_internal <- xgb_probability_to_class(
        as.matrix(probability_internal),
        class_levels
    )
    probability_summary <- summarize_probabilities(
        probability_internal,
        class_map
    )

    prediction_output <- data.frame(
        SampleID = classification_sample_ids,
        PredictedClass = map_internal_to_original_class(
            prediction_internal,
            class_map
        ),
        MaximumProbability = probability_summary$MaximumProbability,
        SecondBestClass = probability_summary$SecondBestClass,
        SecondBestProbability =
            probability_summary$SecondBestProbability,
        ProbabilityMargin = probability_summary$ProbabilityMargin,
        stringsAsFactors = FALSE
    )

    if (!is.null(known_class_original)) {
        prediction_output$KnownClass <- known_class_original
        prediction_output$Correct <- ifelse(
            is.na(known_class_original) |
                known_class_original == "",
            NA,
            prediction_output$PredictedClass == known_class_original
        )
    }

    write_tab(
        prediction_output,
        file.path(algorithm_folder, "Classifications.tabtxt")
    )
    write_tab(
        make_probability_table(
            probability_internal,
            classification_sample_ids,
            class_map
        ),
        file.path(algorithm_folder, "Class_Probabilities.tabtxt")
    )

    external_metrics <- NULL
    if (!is.null(known_class_original)) {
        evaluable <- !is.na(known_class_original) &
            known_class_original != ""

        if (any(evaluable)) {
            external_metrics <- compute_classification_metrics(
                map_original_to_internal_class(
                    known_class_original[evaluable],
                    class_map
                ),
                prediction_internal[evaluable],
                class_map
            )
            write_tab(
                external_metrics$overall,
                file.path(
                    algorithm_folder,
                    "ExternalValidation_Overall_Metrics.tabtxt"
                )
            )
            write_tab(
                external_metrics$per_class,
                file.path(
                    algorithm_folder,
                    "ExternalValidation_PerClass_Metrics.tabtxt"
                )
            )
            write_tab(
                external_metrics$confusion,
                file.path(
                    algorithm_folder,
                    "ExternalValidation_Confusion_Matrix.tabtxt"
                )
            )
        }
    }

    importance <- tryCatch(
        xgboost::xgb.importance(
            feature_names = feature_map$InternalFeature,
            model = final_model
        ),
        error = function(e) NULL
    )

    if (!is.null(importance) && nrow(importance) > 0L) {
        importance <- as.data.frame(importance, check.names = FALSE)
        xgb_feature_column <- if ("Features" %in% names(importance)) {
            "Features"
        } else if ("Feature" %in% names(importance)) {
            "Feature"
        } else {
            NA_character_
        }

        if (!is.na(xgb_feature_column)) {
            importance$InternalFeature <- as.character(
                importance[[xgb_feature_column]]
            )
        } else {
            importance$InternalFeature <- rownames(importance)
        }
        importance$OriginalFeature <- feature_map$OriginalFeature[
            match(
                importance$InternalFeature,
                feature_map$InternalFeature
            )
        ]
        importance$OriginalFeature[
            is.na(importance$OriginalFeature)
        ] <- importance$InternalFeature[
            is.na(importance$OriginalFeature)
        ]
        write_tab(
            importance,
            file.path(
                algorithm_folder,
                "Variable_Importance.tabtxt"
            )
        )
        save_top_importance_plot_from_table(
            importance,
            algorithm_folder,
            filename = "Top_Variable_Importance.png",
            plot_title = "Top variable importance values"
        )
    }

    png(
        file.path(algorithm_folder, "Tuning_Plot.png"),
        width = 1400,
        height = 900,
        res = 150
    )
    plot(
        seq_len(nrow(tuning_results)),
        tuning_results[[MODEL_SELECTION_METRIC]],
        type = "b",
        xlab = "Tuning-grid row",
        ylab = MODEL_SELECTION_METRIC,
        main = "Native XGBoost tuning results"
    )
    points(
        best_grid_row,
        tuning_results[[MODEL_SELECTION_METRIC]][best_grid_row],
        pch = 19,
        cex = 1.5
    )
    dev.off()

    save_algorithm_visualizations(
        folder = algorithm_folder,
        algorithm_title = specification$display_name,
        prediction_output = prediction_output,
        probability_output = make_probability_table(
            probability_internal,
            classification_sample_ids,
            class_map
        ),
        oof_table = cbind(oof_table, oof_probability_table),
        oof_confusion = oof_metrics$confusion,
        external_confusion = if (!is.null(external_metrics)) {
            external_metrics$confusion
        } else {
            NULL
        }
    )

    elapsed_minutes <- as.numeric(
        difftime(Sys.time(), start_time, units = "mins")
    )

    performance_row <- data.frame(
        AlgorithmKey = specification$key,
        Algorithm = specification$display_name,
        Status = "SUCCESS",
        CrossValidatedAccuracy =
            oof_metrics$overall$Accuracy,
        CrossValidatedKappa =
            oof_metrics$overall$CohenKappa,
        CrossValidatedMacroF1 =
            oof_metrics$overall$MacroF1,
        CrossValidatedBalancedAccuracy =
            oof_metrics$overall$MeanOneVsAllBalancedAccuracy,
        BestTuningParameters = collapse_named_row(best_tune),
        RuntimeMinutes = elapsed_minutes,
        ErrorMessage = "",
        stringsAsFactors = FALSE
    )

    log_message(
        "Completed: ", specification$display_name,
        " in ",
        format(round(elapsed_minutes, 3), nsmall = 3),
        " minutes."
    )

    list(
        key = specification$key,
        display_name = specification$display_name,
        folder = specification$folder,
        fit = final_model,
        predictions_internal = prediction_internal,
        predictions_original = prediction_output$PredictedClass,
        probabilities_internal = probability_internal,
        probability_summary = probability_summary,
        performance = performance_row,
        status = "SUCCESS",
        error = ""
    )
}


run_one_algorithm <- function(specification, algorithm_number) {
    if (identical(specification$method, "native_xgb_train")) {
        return(run_native_xgboost(specification, algorithm_number))
    }

    algorithm_folder <- file.path(run_directory, specification$folder)
    dir.create(algorithm_folder, recursive = TRUE, showWarnings = FALSE)

    log_message("Starting: ", specification$display_name)
    start_time <- Sys.time()

    number_of_seed_values <- if (!is.null(specification$tune_grid)) {
        max(100L, nrow(specification$tune_grid) + 10L)
    } else {
        500L
    }

    control <- caret::trainControl(
        method = "repeatedcv",
        number = effective_cv_folds,
        repeats = CV_REPEATS,
        verboseIter = FALSE,
        returnData = TRUE,
        returnResamp = "all",
        savePredictions = "final",
        classProbs = TRUE,
        summaryFunction = caret_classification_summary,
        selectionFunction = "best",
        preProcOptions = list(
            thresh = LDA_PCA_VARIANCE_TO_RETAIN,
            ICAcomp = 3,
            k = 5,
            freqCut = 95 / 5,
            uniqueCut = 10,
            cutoff = 0.90
        ),
        index = cv_training_indices,
        indexOut = cv_holdout_indices,
        seeds = make_caret_seeds(
            length(cv_training_indices),
            number_of_seed_values,
            RANDOM_SEED + algorithm_number * 1000L
        ),
        allowParallel = number_of_cores_to_use > 1L
    )

    training_arguments <- list(
        x = trainer_features,
        y = y_internal,
        method = specification$method,
        metric = MODEL_SELECTION_METRIC,
        maximize = TRUE,
        trControl = control,
        preProcess = specification$preprocess
    )

    if (!is.null(specification$tune_grid)) {
        training_arguments$tuneGrid <- specification$tune_grid
    } else {
        training_arguments$tuneLength <- specification$tune_length
    }

    training_arguments <- c(training_arguments, specification$extra_arguments)

    warning_messages <- character(0)
    set.seed(RANDOM_SEED + algorithm_number)

    fit <- withCallingHandlers(
        do.call(caret::train, training_arguments),
        warning = function(w) {
            warning_messages <<- unique(c(warning_messages, conditionMessage(w)))
            invokeRestart("muffleWarning")
        }
    )

    if (length(warning_messages) > 0L) {
        write_text(
            warning_messages,
            file.path(algorithm_folder, "Training_Warnings.txt")
        )
    }

    saveRDS(fit, file.path(algorithm_folder, "Trained_Model.rds"))
    capture.output(
        print(fit),
        file = file.path(algorithm_folder, "Model_Summary.txt")
    )
    write_tab(
        fit$results,
        file.path(algorithm_folder, "Tuning_Results.tabtxt")
    )
    write_tab(
        fit$bestTune,
        file.path(algorithm_folder, "Best_Tuning_Parameters.tabtxt")
    )

    if (!is.null(fit$preProcess) && !is.null(fit$preProcess$rotation)) {
        pca_rotation <- as.data.frame(
            fit$preProcess$rotation,
            check.names = FALSE
        )
        internal_features_in_pca <- rownames(pca_rotation)
        original_features_in_pca <- feature_map$OriginalFeature[
            match(internal_features_in_pca, feature_map$InternalFeature)
        ]
        original_features_in_pca[is.na(original_features_in_pca)] <-
            internal_features_in_pca[is.na(original_features_in_pca)]

        pca_rotation <- data.frame(
            OriginalFeature = original_features_in_pca,
            InternalFeature = internal_features_in_pca,
            pca_rotation,
            check.names = FALSE
        )
        write_tab(
            pca_rotation,
            file.path(algorithm_folder, "PCA_Feature_Loadings.tabtxt")
        )
    }

    if (!is.null(fit$resample)) {
        write_tab(
            fit$resample,
            file.path(algorithm_folder, "Resampling_Results.tabtxt")
        )
    }

    prediction_internal <- as.character(predict(
        fit,
        newdata = classify_features,
        type = "raw"
    ))

    probability_internal <- tryCatch(
        as.data.frame(
            predict(fit, newdata = classify_features, type = "prob"),
            check.names = FALSE
        ),
        error = function(e) {
            write_text(
                paste("Probability prediction failed:", conditionMessage(e)),
                file.path(algorithm_folder, "Probability_Prediction_Error.txt")
            )
            NULL
        }
    )

    if (!is.null(probability_internal)) {
        for (level in internal_class_levels) {
            if (!level %in% names(probability_internal)) {
                probability_internal[[level]] <- NA_real_
            }
        }
        probability_internal <- probability_internal[
            , internal_class_levels, drop = FALSE
        ]
    }

    probability_summary <- summarize_probabilities(
        probability_internal,
        class_map
    )

    prediction_output <- data.frame(
        SampleID = classification_sample_ids,
        PredictedClass = map_internal_to_original_class(
            prediction_internal,
            class_map
        ),
        MaximumProbability = probability_summary$MaximumProbability,
        SecondBestClass = probability_summary$SecondBestClass,
        SecondBestProbability = probability_summary$SecondBestProbability,
        ProbabilityMargin = probability_summary$ProbabilityMargin,
        stringsAsFactors = FALSE
    )

    if (!is.null(known_class_original)) {
        prediction_output$KnownClass <- known_class_original
        prediction_output$Correct <- ifelse(
            is.na(known_class_original) | known_class_original == "",
            NA,
            prediction_output$PredictedClass == known_class_original
        )
    }

    write_tab(
        prediction_output,
        file.path(algorithm_folder, "Classifications.tabtxt")
    )

    probability_output <- make_probability_table(
        probability_internal,
        classification_sample_ids,
        class_map
    )
    if (!is.null(probability_output)) {
        write_tab(
            probability_output,
            file.path(algorithm_folder, "Class_Probabilities.tabtxt")
        )
    }

    oof <- extract_oof_predictions(
        fit,
        y_internal,
        training_sample_ids,
        class_map
    )

    oof_metrics <- NULL
    if (!is.null(oof)) {
        write_tab(
            oof$table,
            file.path(algorithm_folder, "CrossValidated_Training_Predictions.tabtxt")
        )

        oof_metrics <- compute_classification_metrics(
            oof$truth_internal,
            oof$predicted_internal,
            class_map
        )

        write_tab(
            oof_metrics$overall,
            file.path(algorithm_folder, "CrossValidated_Overall_Metrics.tabtxt")
        )
        write_tab(
            oof_metrics$per_class,
            file.path(algorithm_folder, "CrossValidated_PerClass_Metrics.tabtxt")
        )
        write_tab(
            oof_metrics$confusion,
            file.path(algorithm_folder, "CrossValidated_Confusion_Matrix.tabtxt")
        )
    }

    external_metrics <- NULL
    if (!is.null(known_class_original)) {
        evaluable <- !is.na(known_class_original) & known_class_original != ""
        if (any(evaluable)) {
            known_internal <- map_original_to_internal_class(
                known_class_original[evaluable],
                class_map
            )
            external_metrics <- compute_classification_metrics(
                known_internal,
                prediction_internal[evaluable],
                class_map
            )
            write_tab(
                external_metrics$overall,
                file.path(algorithm_folder, "ExternalValidation_Overall_Metrics.tabtxt")
            )
            write_tab(
                external_metrics$per_class,
                file.path(algorithm_folder, "ExternalValidation_PerClass_Metrics.tabtxt")
            )
            write_tab(
                external_metrics$confusion,
                file.path(algorithm_folder, "ExternalValidation_Confusion_Matrix.tabtxt")
            )
        }
    }

    save_variable_importance(fit, algorithm_folder, feature_map)
    save_tuning_plot(fit, algorithm_folder)
    save_algorithm_visualizations(
        folder = algorithm_folder,
        algorithm_title = specification$display_name,
        prediction_output = prediction_output,
        probability_output = probability_output,
        oof_table = if (!is.null(oof)) oof$table else NULL,
        oof_confusion = if (!is.null(oof_metrics)) oof_metrics$confusion else NULL,
        external_confusion = if (!is.null(external_metrics)) external_metrics$confusion else NULL
    )

    elapsed_minutes <- as.numeric(
        difftime(Sys.time(), start_time, units = "mins")
    )

    performance_row <- data.frame(
        AlgorithmKey = specification$key,
        Algorithm = specification$display_name,
        Status = "SUCCESS",
        CrossValidatedAccuracy = if (!is.null(oof_metrics)) {
            oof_metrics$overall$Accuracy
        } else {
            NA_real_
        },
        CrossValidatedKappa = if (!is.null(oof_metrics)) {
            oof_metrics$overall$CohenKappa
        } else {
            NA_real_
        },
        CrossValidatedMacroF1 = if (!is.null(oof_metrics)) {
            oof_metrics$overall$MacroF1
        } else {
            NA_real_
        },
        CrossValidatedBalancedAccuracy = if (!is.null(oof_metrics)) {
            oof_metrics$overall$MeanOneVsAllBalancedAccuracy
        } else {
            NA_real_
        },
        BestTuningParameters = collapse_named_row(fit$bestTune),
        RuntimeMinutes = elapsed_minutes,
        ErrorMessage = "",
        stringsAsFactors = FALSE
    )

    log_message(
        "Completed: ", specification$display_name,
        " in ", format(round(elapsed_minutes, 3), nsmall = 3), " minutes."
    )

    list(
        key = specification$key,
        display_name = specification$display_name,
        folder = specification$folder,
        fit = fit,
        predictions_internal = prediction_internal,
        predictions_original = prediction_output$PredictedClass,
        probabilities_internal = probability_internal,
        probability_summary = probability_summary,
        performance = performance_row,
        status = "SUCCESS",
        error = ""
    )
}


algorithm_results <- list()
algorithm_status_rows <- list()

for (i in seq_along(algorithm_specs)) {
    specification <- algorithm_specs[[i]]

    if (!isTRUE(specification$enabled)) {
        algorithm_status_rows[[length(algorithm_status_rows) + 1L]] <- data.frame(
            AlgorithmKey = specification$key,
            Algorithm = specification$display_name,
            Status = "DISABLED",
            CrossValidatedAccuracy = NA_real_,
            CrossValidatedKappa = NA_real_,
            CrossValidatedMacroF1 = NA_real_,
            CrossValidatedBalancedAccuracy = NA_real_,
            BestTuningParameters = "",
            RuntimeMinutes = NA_real_,
            ErrorMessage = "Disabled in USER SETTINGS",
            stringsAsFactors = FALSE
        )
        next
    }

    result <- tryCatch(
        run_one_algorithm(specification, i),
        error = function(e) {
            algorithm_folder <- file.path(run_directory, specification$folder)
            dir.create(algorithm_folder, recursive = TRUE, showWarnings = FALSE)
            error_message <- conditionMessage(e)
            write_text(
                c(
                    paste("Algorithm:", specification$display_name),
                    paste("Error:", error_message),
                    "",
                    "The other enabled algorithms continued to run."
                ),
                file.path(algorithm_folder, "ERROR.txt")
            )
            log_message("FAILED: ", specification$display_name, " -- ", error_message)

            list(
                key = specification$key,
                display_name = specification$display_name,
                folder = specification$folder,
                fit = NULL,
                predictions_internal = NULL,
                predictions_original = NULL,
                probabilities_internal = NULL,
                probability_summary = NULL,
                performance = data.frame(
                    AlgorithmKey = specification$key,
                    Algorithm = specification$display_name,
                    Status = "FAILED",
                    CrossValidatedAccuracy = NA_real_,
                    CrossValidatedKappa = NA_real_,
                    CrossValidatedMacroF1 = NA_real_,
                    CrossValidatedBalancedAccuracy = NA_real_,
                    BestTuningParameters = "",
                    RuntimeMinutes = NA_real_,
                    ErrorMessage = error_message,
                    stringsAsFactors = FALSE
                ),
                status = "FAILED",
                error = error_message
            )
        }
    )

    algorithm_results[[specification$key]] <- result
    algorithm_status_rows[[length(algorithm_status_rows) + 1L]] <- result$performance
}

algorithm_performance_summary <- do.call(rbind, algorithm_status_rows)
write_tab(
    algorithm_performance_summary,
    file.path(summary_folder, "Algorithm_Performance_Summary.tabtxt")
)


successful_results <- algorithm_results[
    vapply(algorithm_results, function(x) identical(x$status, "SUCCESS"), logical(1))
]

if (length(successful_results) == 0L) {
    stop(
        "All enabled algorithms failed. Review each algorithm folder and Run_Log.txt."
    )
}

classification_summary <- data.frame(
    SampleID = classification_sample_ids,
    stringsAsFactors = FALSE
)

for (result in successful_results) {
    classification_summary[[paste0("Prediction_", result$key)]] <-
        result$predictions_original
    classification_summary[[paste0("Confidence_", result$key)]] <-
        result$probability_summary$MaximumProbability
}

if (!is.null(known_class_original)) {
    classification_summary$KnownClass <- known_class_original
}

mean_probability_matrix <- matrix(
    NA_real_,
    nrow = nrow(classify_features),
    ncol = length(internal_class_levels),
    dimnames = list(NULL, internal_class_levels)
)

for (class_index in seq_along(internal_class_levels)) {
    level <- internal_class_levels[class_index]
    probability_columns <- lapply(successful_results, function(result) {
        if (is.null(result$probabilities_internal) ||
            !level %in% names(result$probabilities_internal)) {
            return(rep(NA_real_, nrow(classify_features)))
        }
        result$probabilities_internal[[level]]
    })

    probability_matrix_for_class <- do.call(cbind, probability_columns)
    mean_values <- rowMeans(probability_matrix_for_class, na.rm = TRUE)
    mean_values[!is.finite(mean_values)] <- NA_real_
    mean_probability_matrix[, class_index] <- mean_values

    classification_summary[[paste0(
        "MeanProbability_",
        class_map$OriginalClass[class_index]
    )]] <- mean_values
}

prediction_columns <- paste0(
    "Prediction_",
    vapply(successful_results, function(x) x$key, character(1))
)

consensus_internal <- character(nrow(classification_summary))
agreement_count <- integer(nrow(classification_summary))
agreement_fraction <- numeric(nrow(classification_summary))
vote_tie <- logical(nrow(classification_summary))
tie_resolution_method <- character(nrow(classification_summary))
consensus_mean_probability <- numeric(nrow(classification_summary))
conclusion <- character(nrow(classification_summary))
number_of_successful_algorithms <- length(successful_results)

for (row_index in seq_len(nrow(classification_summary))) {
    original_votes <- unlist(
        classification_summary[row_index, prediction_columns, drop = FALSE],
        use.names = FALSE
    )
    internal_votes <- map_original_to_internal_class(original_votes, class_map)
    vote <- majority_vote_internal(internal_votes, internal_class_levels)

    chosen_class <- vote$class
    tied <- isTRUE(vote$tie)
    tie_resolution_method[row_index] <- if (tied) {
        "Internal class order"
    } else {
        "No tie"
    }

    if (tied && !all(is.na(mean_probability_matrix[row_index, ]))) {
        tied_indices <- match(vote$tied_classes, internal_class_levels)
        tied_probabilities <- mean_probability_matrix[row_index, tied_indices]
        if (!all(is.na(tied_probabilities))) {
            chosen_class <- vote$tied_classes[which.max(tied_probabilities)]
            tie_resolution_method[row_index] <- "Mean probability"
        }
    }

    consensus_internal[row_index] <- chosen_class
    agreement_count[row_index] <- sum(internal_votes == chosen_class, na.rm = TRUE)
    agreement_fraction[row_index] <- safe_divide(
        agreement_count[row_index],
        number_of_successful_algorithms
    )
    vote_tie[row_index] <- tied

    class_position <- match(chosen_class, internal_class_levels)
    consensus_mean_probability[row_index] <- if (!is.na(class_position)) {
        mean_probability_matrix[row_index, class_position]
    } else {
        NA_real_
    }

    if (agreement_count[row_index] == number_of_successful_algorithms) {
        conclusion[row_index] <- paste0(
            "Unanimous classification: ",
            map_internal_to_original_class(chosen_class, class_map),
            " (", agreement_count[row_index], "/",
            number_of_successful_algorithms, " algorithms)"
        )
    } else if (agreement_fraction[row_index] >= 0.75) {
        conclusion[row_index] <- paste0(
            "Strong agreement: ",
            map_internal_to_original_class(chosen_class, class_map),
            " (", agreement_count[row_index], "/",
            number_of_successful_algorithms, " algorithms)"
        )
    } else if (agreement_fraction[row_index] >= 0.50) {
        conclusion[row_index] <- paste0(
            if (tied) {
                paste0("Tie resolved by ", tolower(tie_resolution_method[row_index]), ": ")
            } else {
                "Moderate agreement: "
            },
            map_internal_to_original_class(chosen_class, class_map),
            " (", agreement_count[row_index], "/",
            number_of_successful_algorithms, " algorithms)"
        )
    } else {
        conclusion[row_index] <- paste0(
            "Weak agreement; interpret cautiously: ",
            map_internal_to_original_class(chosen_class, class_map),
            " (", agreement_count[row_index], "/",
            number_of_successful_algorithms, " algorithms)"
        )
    }
}

classification_summary$ConsensusClass <- map_internal_to_original_class(
    consensus_internal,
    class_map
)
classification_summary$AlgorithmsAgreeingWithConsensus <- agreement_count
classification_summary$AlgorithmsSuccessfullyRun <- number_of_successful_algorithms
classification_summary$AgreementPercent <- 100 * agreement_fraction
classification_summary$Unanimous <- agreement_count == number_of_successful_algorithms
classification_summary$VoteTieOccurred <- vote_tie
classification_summary$TieResolutionMethod <- tie_resolution_method
classification_summary$ConsensusMeanProbability <- consensus_mean_probability
classification_summary$Conclusion <- conclusion

if (!is.null(known_class_original)) {
    classification_summary$ConsensusCorrect <- ifelse(
        is.na(known_class_original) | known_class_original == "",
        NA,
        classification_summary$ConsensusClass == known_class_original
    )
}

priority_columns <- c(
    "SampleID",
    if (!is.null(known_class_original)) "KnownClass" else NULL,
    "ConsensusClass",
    "AlgorithmsAgreeingWithConsensus",
    "AlgorithmsSuccessfullyRun",
    "AgreementPercent",
    "Unanimous",
    "VoteTieOccurred",
    "TieResolutionMethod",
    "ConsensusMeanProbability",
    "Conclusion",
    if (!is.null(known_class_original)) "ConsensusCorrect" else NULL
)
classification_summary <- classification_summary[
    , c(priority_columns, setdiff(names(classification_summary), priority_columns)),
    drop = FALSE
]

write_tab(
    classification_summary,
    file.path(summary_folder, "All_Algorithms_Classification_Summary.tabtxt")
)

simple_prediction_table <- data.frame(
    SampleID = classification_sample_ids,
    stringsAsFactors = FALSE
)
for (result in successful_results) {
    simple_prediction_table[[result$key]] <- result$predictions_original
}
simple_prediction_table$ConsensusClass <- classification_summary$ConsensusClass
simple_prediction_table$AgreementPercent <- classification_summary$AgreementPercent
simple_prediction_table$Conclusion <- classification_summary$Conclusion

write_tab(
    simple_prediction_table,
    file.path(summary_folder, "Predictions_One_Column_Per_Algorithm.tabtxt")
)


consensus_metrics <- NULL
if (!is.null(known_class_original)) {
    evaluable <- !is.na(known_class_original) & known_class_original != ""
    if (any(evaluable)) {
        truth_internal <- map_original_to_internal_class(
            known_class_original[evaluable],
            class_map
        )
        consensus_metrics <- compute_classification_metrics(
            truth_internal,
            consensus_internal[evaluable],
            class_map
        )
        write_tab(
            consensus_metrics$overall,
            file.path(summary_folder, "Consensus_ExternalValidation_Overall_Metrics.tabtxt")
        )
        write_tab(
            consensus_metrics$per_class,
            file.path(summary_folder, "Consensus_ExternalValidation_PerClass_Metrics.tabtxt")
        )
        write_tab(
            consensus_metrics$confusion,
            file.path(summary_folder, "Consensus_ExternalValidation_Confusion_Matrix.tabtxt")
        )
    }
}

save_summary_visualizations(
    summary_folder = summary_folder,
    algorithm_performance_summary = algorithm_performance_summary,
    classification_summary = classification_summary,
    class_map = class_map,
    trainer_features = trainer_features,
    classify_features = classify_features,
    training_classes_original = trainer_raw[[CLASS_COLUMN]],
    training_sample_ids = training_sample_ids,
    classification_sample_ids = classification_sample_ids
)

if (!is.null(consensus_metrics)) {
    save_confusion_heatmap(
        consensus_metrics$confusion,
        file.path(summary_folder, "Consensus_ExternalValidation_Confusion_Matrix_Heatmap.png"),
        "Consensus external validation confusion matrix"
    )
}


capture.output(
    sessionInfo(),
    file = file.path(run_directory, "SessionInfo.txt")
)

run_configuration <- data.frame(
    Setting = c(
        "TRAIN_FILE",
        "CLASSIFY_FILE",
        "RANDOM_SEED",
        "REQUESTED_CV_FOLDS",
        "EFFECTIVE_CV_FOLDS",
        "CV_REPEATS",
        "MODEL_SELECTION_METRIC",
        "NUMBER_OF_CORES",
        "MAX_MISSING_FRACTION_PER_FEATURE",
        "LDA_PCA_VARIANCE_TO_RETAIN",
        "RANDOM_FOREST_NUMBER_OF_TREES",
        "XGBOOST_NUMBER_OF_THREADS",
        "XGBOOST_TREE_METHOD",
        "XGBOOST_PACKAGE_VERSION",
        "CARET_PACKAGE_VERSION"
    ),
    Value = c(
        TRAIN_FILE,
        CLASSIFY_FILE,
        RANDOM_SEED,
        CV_FOLDS,
        effective_cv_folds,
        CV_REPEATS,
        MODEL_SELECTION_METRIC,
        number_of_cores_to_use,
        MAX_MISSING_FRACTION_PER_FEATURE,
        LDA_PCA_VARIANCE_TO_RETAIN,
        RANDOM_FOREST_NUMBER_OF_TREES,
        XGBOOST_NUMBER_OF_THREADS,
        XGBOOST_TREE_METHOD,
        as.character(utils::packageVersion("xgboost")),
        as.character(utils::packageVersion("caret"))
    ),
    stringsAsFactors = FALSE
)
write_tab(
    run_configuration,
    file.path(run_directory, "Run_Configuration.tabtxt")
)

if (!is.null(parallel_cluster)) {
    parallel::stopCluster(parallel_cluster)
    parallel_cluster <- NULL
}

assign(".LAST_RUN_DIRECTORY", run_directory, envir = .GlobalEnv)
log_message("Pipeline completed successfully.")
log_message(
    "Main combined result: ",
    normalizePath(
        file.path(summary_folder, "All_Algorithms_Classification_Summary.tabtxt"),
        mustWork = FALSE
    )
)

cat("\n============================================================\n")
cat("SUPERVISED CLASSIFICATION PIPELINE COMPLETED\n")
cat("Output directory:\n")
cat(normalizePath(run_directory, mustWork = FALSE), "\n")
cat("\nMain summary files:\n")
cat("  09_Summary/All_Algorithms_Classification_Summary.tabtxt\n")
cat("  09_Summary/Predictions_One_Column_Per_Algorithm.tabtxt\n")
cat("  09_Summary/Algorithm_Performance_Summary.tabtxt\n")
cat("============================================================\n")

}


run_supervised_classification_worker <- function(settings_path, status_path) {
    status <- list(
        success = FALSE,
        message = "",
        last_run_directory = ""
    )

    tryCatch({
        settings <- readRDS(settings_path)
        list2env(settings, envir = .GlobalEnv)
        .classification_gui_log <<- NULL
        result <- run_pipeline()
        status$success <- TRUE
        status$message <- "Classification completed successfully."
        status$last_run_directory <- if (exists(".LAST_RUN_DIRECTORY", envir = .GlobalEnv, inherits = FALSE)) {
            get(".LAST_RUN_DIRECTORY", envir = .GlobalEnv, inherits = FALSE)
        } else {
            ""
        }
    }, error = function(e) {
        status$success <- FALSE
        status$message <- conditionMessage(e)
        status$last_run_directory <- if (exists(".LAST_RUN_DIRECTORY", envir = .GlobalEnv, inherits = FALSE)) {
            get(".LAST_RUN_DIRECTORY", envir = .GlobalEnv, inherits = FALSE)
        } else {
            ""
        }
    })

    try(saveRDS(status, status_path), silent = TRUE)

    if (isTRUE(status$success)) {
        quit(save = "no", status = 0L)
    }

    cat("ERROR: ", status$message, "\n", sep = "")
    quit(save = "no", status = 1L)
}

launch_supervised_classification_gui <- function() {
    if (!capabilities("tcltk") || !requireNamespace("tcltk", quietly = TRUE)) {
        stop("Tcl/Tk is not available in this R installation.")
    }

    tt <- tcltk::tktoplevel()
    tcltk::tkwm.title(tt, "Genomic Supervised Classification")
    tcltk::tkwm.geometry(tt, "1180x900")
    tcltk::tkwm.minsize(tt, 1050, 760)

    bg_main <- "#eef5fb"
    bg_header <- "#cfe8ff"
    bg_section <- "#f8fbfe"
    bg_run <- "#bfe6c4"
    bg_stop <- "#f3b5b5"
    bg_button <- "#dcecff"
    bg_warn <- "#fff1bf"
    fg_dark <- "#17324d"

    tcltk::tkconfigure(tt, background = bg_main)

    train_var <- tcltk::tclVar(TRAIN_FILE)
    classify_var <- tcltk::tclVar(CLASSIFY_FILE)
    output_var <- tcltk::tclVar(OUTPUT_ROOT)
    seed_var <- tcltk::tclVar(as.character(RANDOM_SEED))
    folds_var <- tcltk::tclVar(as.character(CV_FOLDS))
    repeats_var <- tcltk::tclVar(as.character(CV_REPEATS))
    cores_var <- tcltk::tclVar(as.character(NUMBER_OF_CORES))
    missing_var <- tcltk::tclVar(as.character(MAX_MISSING_FRACTION_PER_FEATURE))
    pca_var <- tcltk::tclVar(as.character(LDA_PCA_VARIANCE_TO_RETAIN))
    trees_var <- tcltk::tclVar(as.character(RANDOM_FOREST_NUMBER_OF_TREES))
    xgb_threads_var <- tcltk::tclVar(as.character(XGBOOST_NUMBER_OF_THREADS))
    top_vars_var <- tcltk::tclVar(as.character(TOP_VARIABLES_TO_PLOT))
    elastic_var <- tcltk::tclVar(if (RUN_ELASTIC_NET) "1" else "0")
    rf_var <- tcltk::tclVar(if (RUN_RANDOM_FOREST) "1" else "0")
    svm_var <- tcltk::tclVar(if (RUN_SVM) "1" else "0")
    xgb_var <- tcltk::tclVar(if (RUN_GRADIENT_BOOSTING) "1" else "0")
    pls_var <- tcltk::tclVar(if (RUN_PLSDA) "1" else "0")
    lda_var <- tcltk::tclVar(if (RUN_LDA) "1" else "0")
    knn_var <- tcltk::tclVar(if (RUN_KNN) "1" else "0")
    pam_var <- tcltk::tclVar(if (RUN_NEAREST_SHRUNKEN_CENTROID) "1" else "0")
    status_var <- tcltk::tclVar("Ready")

    root_frame <- tcltk::tkframe(tt, background = bg_main, padx = 12, pady = 12)
    tcltk::tkpack(root_frame, fill = "both", expand = TRUE)

    header <- tcltk::tklabel(
        root_frame,
        text = "Multi-Algorithm Supervised Classification for Genomic and Omics Data",
        background = bg_header,
        foreground = fg_dark,
        font = "TkDefaultFont 14 bold",
        padx = 12,
        pady = 10
    )
    tcltk::tkpack(header, fill = "x", pady = "0 8")

    files_frame <- tcltk::tkframe(root_frame, background = bg_section, relief = "groove", borderwidth = 2, padx = 8, pady = 8)
    tcltk::tkpack(files_frame, fill = "x", pady = 4)
    tcltk::tkgrid(tcltk::tklabel(files_frame, text = "Training file", background = bg_section, width = 18, anchor = "w"), row = 0, column = 0, sticky = "w", padx = 4, pady = 4)
    train_entry <- tcltk::tkentry(files_frame, textvariable = train_var, width = 100)
    tcltk::tkgrid(train_entry, row = 0, column = 1, sticky = "we", padx = 4, pady = 4)
    tcltk::tkgrid(tcltk::tkbutton(files_frame, text = "Browse", background = bg_button, command = function() {
        initial <- dirname(tcltk::tclvalue(train_var))
        if (!dir.exists(initial)) initial <- getwd()
        selected <- as.character(tcltk::tkgetOpenFile(initialdir = initial, filetypes = "{{Tab-delimited files} {.tabtxt .txt}} {{All files} {*}}"))
        if (nzchar(selected)) tcltk::tclvalue(train_var) <- selected
    }), row = 0, column = 2, padx = 4, pady = 4)

    tcltk::tkgrid(tcltk::tklabel(files_frame, text = "Samples to classify", background = bg_section, width = 18, anchor = "w"), row = 1, column = 0, sticky = "w", padx = 4, pady = 4)
    classify_entry <- tcltk::tkentry(files_frame, textvariable = classify_var, width = 100)
    tcltk::tkgrid(classify_entry, row = 1, column = 1, sticky = "we", padx = 4, pady = 4)
    tcltk::tkgrid(tcltk::tkbutton(files_frame, text = "Browse", background = bg_button, command = function() {
        initial <- dirname(tcltk::tclvalue(classify_var))
        if (!dir.exists(initial)) initial <- getwd()
        selected <- as.character(tcltk::tkgetOpenFile(initialdir = initial, filetypes = "{{Tab-delimited files} {.tabtxt .txt}} {{All files} {*}}"))
        if (nzchar(selected)) tcltk::tclvalue(classify_var) <- selected
    }), row = 1, column = 2, padx = 4, pady = 4)

    tcltk::tkgrid(tcltk::tklabel(files_frame, text = "Output root", background = bg_section, width = 18, anchor = "w"), row = 2, column = 0, sticky = "w", padx = 4, pady = 4)
    output_entry <- tcltk::tkentry(files_frame, textvariable = output_var, width = 100)
    tcltk::tkgrid(output_entry, row = 2, column = 1, sticky = "we", padx = 4, pady = 4)
    tcltk::tkgrid(tcltk::tkbutton(files_frame, text = "Browse", background = bg_button, command = function() {
        initial <- tcltk::tclvalue(output_var)
        if (!dir.exists(initial)) initial <- getwd()
        selected <- as.character(tcltk::tkchooseDirectory(initialdir = initial, title = "Select output root folder"))
        if (nzchar(selected)) tcltk::tclvalue(output_var) <- selected
    }), row = 2, column = 2, padx = 4, pady = 4)
    tcltk::tkgrid.columnconfigure(files_frame, 1, weight = 1)

    settings_frame <- tcltk::tkframe(root_frame, background = bg_section, relief = "groove", borderwidth = 2, padx = 8, pady = 8)
    tcltk::tkpack(settings_frame, fill = "x", pady = 4)

    add_setting <- function(row, col, label_text, variable, width = 10) {
        tcltk::tkgrid(tcltk::tklabel(settings_frame, text = label_text, background = bg_section, anchor = "w"), row = row, column = col, sticky = "w", padx = 4, pady = 3)
        tcltk::tkgrid(tcltk::tkentry(settings_frame, textvariable = variable, width = width), row = row, column = col + 1, sticky = "w", padx = 4, pady = 3)
    }

    add_setting(0, 0, "Random seed", seed_var)
    add_setting(0, 2, "CV folds", folds_var)
    add_setting(0, 4, "CV repeats", repeats_var)
    add_setting(0, 6, "CPU cores", cores_var)
    add_setting(1, 0, "Max missing fraction", missing_var)
    add_setting(1, 2, "LDA PCA variance", pca_var)
    add_setting(1, 4, "Random forest trees", trees_var)
    add_setting(1, 6, "XGBoost threads", xgb_threads_var)
    add_setting(2, 0, "Top variables to plot", top_vars_var)

    algorithms_frame <- tcltk::tkframe(root_frame, background = bg_section, relief = "groove", borderwidth = 2, padx = 8, pady = 8)
    tcltk::tkpack(algorithms_frame, fill = "x", pady = 4)
    algorithm_items <- list(
        c("Elastic-net logistic / multinomial", "elastic_var"),
        c("Random forest", "rf_var"),
        c("SVM radial", "svm_var"),
        c("XGBoost", "xgb_var"),
        c("PLS-DA", "pls_var"),
        c("LDA with PCA", "lda_var"),
        c("k-nearest neighbors", "knn_var"),
        c("Nearest shrunken centroid", "pam_var")
    )
    algorithm_vars <- list(
        elastic_var = elastic_var,
        rf_var = rf_var,
        svm_var = svm_var,
        xgb_var = xgb_var,
        pls_var = pls_var,
        lda_var = lda_var,
        knn_var = knn_var,
        pam_var = pam_var
    )
    for (i in seq_along(algorithm_items)) {
        item <- algorithm_items[[i]]
        row <- (i - 1L) %/% 4L
        col <- ((i - 1L) %% 4L) * 2L
        tcltk::tkgrid(tcltk::tkcheckbutton(algorithms_frame, text = item[1], variable = algorithm_vars[[item[2]]], background = bg_section), row = row, column = col, columnspan = 2, sticky = "w", padx = 6, pady = 3)
    }
    tcltk::tkgrid(tcltk::tkbutton(algorithms_frame, text = "Select all", background = bg_button, command = function() {
        for (v in algorithm_vars) tcltk::tclvalue(v) <- "1"
    }), row = 2, column = 0, padx = 4, pady = 5, sticky = "w")
    tcltk::tkgrid(tcltk::tkbutton(algorithms_frame, text = "Clear all", background = bg_button, command = function() {
        for (v in algorithm_vars) tcltk::tclvalue(v) <- "0"
    }), row = 2, column = 1, padx = 4, pady = 5, sticky = "w")

    log_frame <- tcltk::tkframe(root_frame, background = bg_section, relief = "groove", borderwidth = 2, padx = 6, pady = 6)
    tcltk::tkpack(log_frame, fill = "both", expand = TRUE, pady = 4)
    log_widget <- tcltk::tktext(log_frame, width = 130, height = 18, wrap = "word", background = "#15202b", foreground = "#eef4f8", insertbackground = "white")
    log_scroll <- tcltk::tkscrollbar(log_frame, orient = "vertical", command = function(...) tcltk::tkyview(log_widget, ...))
    tcltk::tkconfigure(log_widget, yscrollcommand = function(...) tcltk::tkset(log_scroll, ...))
    tcltk::tkpack(log_scroll, side = "right", fill = "y")
    tcltk::tkpack(log_widget, side = "left", fill = "both", expand = TRUE)

    append_log <- function(text) {
        try({
            tcltk::tkinsert(log_widget, "end", paste0(text, "\n"))
            tcltk::tksee(log_widget, "end")
            tcltk::tcl("update")
        }, silent = TRUE)
    }
    .classification_gui_log <<- append_log

    action_frame <- tcltk::tkframe(root_frame, background = bg_main, padx = 2, pady = 4)
    tcltk::tkpack(action_frame, fill = "x")
    status_label <- tcltk::tklabel(action_frame, textvariable = status_var, background = bg_warn, foreground = "#4b3b00", anchor = "w", padx = 8, pady = 5)
    tcltk::tkpack(status_label, side = "bottom", fill = "x", pady = "5 0")

    parse_integer <- function(variable, label, minimum = NULL) {
        value <- suppressWarnings(as.integer(tcltk::tclvalue(variable)))
        if (is.na(value) || (!is.null(minimum) && value < minimum)) {
            stop(paste0(label, " is invalid."))
        }
        value
    }

    parse_numeric <- function(variable, label, minimum = NULL, maximum = NULL, maximum_inclusive = TRUE) {
        value <- suppressWarnings(as.numeric(tcltk::tclvalue(variable)))
        if (is.na(value) || !is.finite(value)) stop(paste0(label, " is invalid."))
        if (!is.null(minimum) && value < minimum) stop(paste0(label, " is below the allowed range."))
        if (!is.null(maximum)) {
            if (maximum_inclusive && value > maximum) stop(paste0(label, " is above the allowed range."))
            if (!maximum_inclusive && value >= maximum) stop(paste0(label, " is above the allowed range."))
        }
        value
    }

    open_folder <- function(path) {
        if (!dir.exists(path)) {
            tcltk::tkmessageBox(icon = "warning", type = "ok", title = "Folder not found", message = "The selected folder does not exist yet.")
            return(invisible(NULL))
        }
        if (.Platform$OS.type == "windows") {
            shell.exec(normalizePath(path, winslash = "\\", mustWork = TRUE))
        } else if (Sys.info()[["sysname"]] == "Darwin") {
            system2("open", path, wait = FALSE)
        } else {
            system2("xdg-open", path, wait = FALSE)
        }
        invisible(NULL)
    }

    run_state <- new.env(parent = emptyenv())
    run_state$process <- NULL
    run_state$stop_requested <- FALSE
    run_state$control_directory <- ""
    run_state$settings_path <- ""
    run_state$status_path <- ""
    run_state$console_path <- ""
    run_state$last_console_line <- 0L

    run_button <- NULL
    stop_button <- NULL

    set_running_state <- function(running) {
        if (!is.null(run_button)) {
            tcltk::tkconfigure(run_button, state = if (running) "disabled" else "normal")
        }
        if (!is.null(stop_button)) {
            tcltk::tkconfigure(stop_button, state = if (running) "normal" else "disabled")
        }
        if (running) {
            tcltk::tkconfigure(tt, cursor = "watch")
        } else {
            tcltk::tkconfigure(tt, cursor = "")
        }
    }

    append_worker_console <- function() {
        path <- run_state$console_path
        if (!nzchar(path) || !file.exists(path)) {
            return(invisible(NULL))
        }

        lines <- tryCatch(
            readLines(path, warn = FALSE, encoding = "UTF-8"),
            error = function(e) character(0)
        )

        if (length(lines) > run_state$last_console_line) {
            new_lines <- lines[seq.int(run_state$last_console_line + 1L, length(lines))]
            for (line in new_lines) {
                if (nzchar(line)) {
                    append_log(line)
                }
            }
            run_state$last_console_line <- length(lines)
        }

        invisible(NULL)
    }

    finish_worker <- function() {
        append_worker_console()
        process_object <- run_state$process
        exit_status <- if (!is.null(process_object)) {
            tryCatch(process_object$get_exit_status(), error = function(e) NA_integer_)
        } else {
            NA_integer_
        }

        status <- NULL
        if (nzchar(run_state$status_path) && file.exists(run_state$status_path)) {
            status <- tryCatch(readRDS(run_state$status_path), error = function(e) NULL)
        }

        was_stopped <- isTRUE(run_state$stop_requested)
        run_state$process <- NULL
        set_running_state(FALSE)

        if (was_stopped) {
            append_log("Classification stopped by user.")
            tcltk::tclvalue(status_var) <- "Stopped by user."
            return(invisible(NULL))
        }

        if (!is.null(status) && isTRUE(status$success)) {
            if (!is.null(status$last_run_directory) && nzchar(status$last_run_directory)) {
                .LAST_RUN_DIRECTORY <<- status$last_run_directory
            }
            append_log("Classification completed successfully.")
            tcltk::tclvalue(status_var) <- paste0("Completed: ", .LAST_RUN_DIRECTORY)
            tcltk::tkmessageBox(
                icon = "info",
                type = "ok",
                title = "Classification complete",
                message = paste0("Output directory:\n", .LAST_RUN_DIRECTORY)
            )
            return(invisible(NULL))
        }

        error_message <- if (!is.null(status) && !is.null(status$message) && nzchar(status$message)) {
            status$message
        } else if (!is.na(exit_status)) {
            paste0("The classification worker exited with status ", exit_status, ".")
        } else {
            "The classification worker stopped unexpectedly."
        }

        append_log(paste0("ERROR: ", error_message))
        tcltk::tclvalue(status_var) <- paste0("Failed: ", error_message)
        tcltk::tkmessageBox(
            icon = "error",
            type = "ok",
            title = "Classification failed",
            message = error_message
        )

        invisible(NULL)
    }

    poll_worker <- function() {
        process_object <- run_state$process
        if (is.null(process_object)) {
            return(invisible(NULL))
        }

        append_worker_console()

        alive <- tryCatch(
            process_object$is_alive(),
            error = function(e) FALSE
        )

        if (isTRUE(alive)) {
            tcltk::tcl("after", 250, poll_worker)
        } else {
            finish_worker()
        }

        invisible(NULL)
    }

    stop_action <- function() {
        process_object <- run_state$process

        if (is.null(process_object)) {
            return(invisible(NULL))
        }

        alive <- tryCatch(
            process_object$is_alive(),
            error = function(e) FALSE
        )

        if (!isTRUE(alive)) {
            return(invisible(NULL))
        }

        run_state$stop_requested <- TRUE
        append_log("Stop requested. Terminating the classification process and its child processes.")
        tcltk::tclvalue(status_var) <- "Stopping classification..."
        tcltk::tkconfigure(stop_button, state = "disabled")

        try(
            process_object$kill_tree(),
            silent = TRUE
        )

        still_alive <- tryCatch(
            process_object$is_alive(),
            error = function(e) FALSE
        )

        if (isTRUE(still_alive)) {
            try(
                process_object$kill(),
                silent = TRUE
            )
        }

        tcltk::tcl("after", 100, poll_worker)
        invisible(NULL)
    }

    run_action <- function() {
        tryCatch({
            if (!is.null(run_state$process)) {
                alive <- tryCatch(run_state$process$is_alive(), error = function(e) FALSE)
                if (isTRUE(alive)) {
                    stop("A classification run is already active.")
                }
            }

            if (!requireNamespace("processx", quietly = TRUE)) {
                stop("The processx package is required for the Run/Stop controls. Run 00_Install_R_Packages.R first.")
            }

            if (!nzchar(SCRIPT_FILE) || !file.exists(SCRIPT_FILE)) {
                stop("The script file path could not be determined. Save this R script to a file and run or source that file before starting the classification.")
            }

            selected_train <- tcltk::tclvalue(train_var)
            selected_classify <- tcltk::tclvalue(classify_var)
            selected_output <- tcltk::tclvalue(output_var)

            if (!file.exists(selected_train)) {
                stop("Training file does not exist.")
            }
            if (!file.exists(selected_classify)) {
                stop("Classification file does not exist.")
            }
            if (!nzchar(selected_output)) {
                stop("Output root is empty.")
            }

            dir.create(selected_output, recursive = TRUE, showWarnings = FALSE)

            TRAIN_FILE <<- normalizePath(selected_train, winslash = "/", mustWork = TRUE)
            CLASSIFY_FILE <<- normalizePath(selected_classify, winslash = "/", mustWork = TRUE)
            OUTPUT_ROOT <<- normalizePath(selected_output, winslash = "/", mustWork = TRUE)
            RANDOM_SEED <<- parse_integer(seed_var, "Random seed", 0L)
            CV_FOLDS <<- parse_integer(folds_var, "CV folds", 2L)
            CV_REPEATS <<- parse_integer(repeats_var, "CV repeats", 1L)
            NUMBER_OF_CORES <<- parse_integer(cores_var, "CPU cores", 1L)
            MAX_MISSING_FRACTION_PER_FEATURE <<- parse_numeric(missing_var, "Max missing fraction", 0, 1)
            LDA_PCA_VARIANCE_TO_RETAIN <<- parse_numeric(pca_var, "LDA PCA variance", 0, 1)

            if (LDA_PCA_VARIANCE_TO_RETAIN <= 0) {
                stop("LDA PCA variance must be greater than 0.")
            }

            RANDOM_FOREST_NUMBER_OF_TREES <<- parse_integer(trees_var, "Random forest trees", 1L)
            XGBOOST_NUMBER_OF_THREADS <<- parse_integer(xgb_threads_var, "XGBoost threads", 1L)
            TOP_VARIABLES_TO_PLOT <<- parse_integer(top_vars_var, "Top variables to plot", 1L)

            RUN_ELASTIC_NET <<- tcltk::tclvalue(elastic_var) == "1"
            RUN_RANDOM_FOREST <<- tcltk::tclvalue(rf_var) == "1"
            RUN_SVM <<- tcltk::tclvalue(svm_var) == "1"
            RUN_GRADIENT_BOOSTING <<- tcltk::tclvalue(xgb_var) == "1"
            RUN_PLSDA <<- tcltk::tclvalue(pls_var) == "1"
            RUN_LDA <<- tcltk::tclvalue(lda_var) == "1"
            RUN_KNN <<- tcltk::tclvalue(knn_var) == "1"
            RUN_NEAREST_SHRUNKEN_CENTROID <<- tcltk::tclvalue(pam_var) == "1"

            enabled <- c(
                RUN_ELASTIC_NET,
                RUN_RANDOM_FOREST,
                RUN_SVM,
                RUN_GRADIENT_BOOSTING,
                RUN_PLSDA,
                RUN_LDA,
                RUN_KNN,
                RUN_NEAREST_SHRUNKEN_CENTROID
            )

            if (!any(enabled)) {
                stop("Select at least one algorithm.")
            }

            settings <- list(
                TRAIN_FILE = TRAIN_FILE,
                CLASSIFY_FILE = CLASSIFY_FILE,
                OUTPUT_ROOT = OUTPUT_ROOT,
                SAMPLE_ID_COLUMN = SAMPLE_ID_COLUMN,
                CLASS_COLUMN = CLASS_COLUMN,
                OPTIONAL_KNOWN_CLASS_COLUMN = OPTIONAL_KNOWN_CLASS_COLUMN,
                ADDITIONAL_NON_FEATURE_COLUMNS = ADDITIONAL_NON_FEATURE_COLUMNS,
                RANDOM_SEED = RANDOM_SEED,
                CV_FOLDS = CV_FOLDS,
                CV_REPEATS = CV_REPEATS,
                MODEL_SELECTION_METRIC = MODEL_SELECTION_METRIC,
                NUMBER_OF_CORES = NUMBER_OF_CORES,
                MAX_MISSING_FRACTION_PER_FEATURE = MAX_MISSING_FRACTION_PER_FEATURE,
                LDA_PCA_VARIANCE_TO_RETAIN = LDA_PCA_VARIANCE_TO_RETAIN,
                RANDOM_FOREST_NUMBER_OF_TREES = RANDOM_FOREST_NUMBER_OF_TREES,
                XGBOOST_NUMBER_OF_THREADS = XGBOOST_NUMBER_OF_THREADS,
                XGBOOST_TREE_METHOD = XGBOOST_TREE_METHOD,
                TOP_VARIABLES_TO_PLOT = TOP_VARIABLES_TO_PLOT,
                RUN_ELASTIC_NET = RUN_ELASTIC_NET,
                RUN_RANDOM_FOREST = RUN_RANDOM_FOREST,
                RUN_SVM = RUN_SVM,
                RUN_GRADIENT_BOOSTING = RUN_GRADIENT_BOOSTING,
                RUN_PLSDA = RUN_PLSDA,
                RUN_LDA = RUN_LDA,
                RUN_KNN = RUN_KNN,
                RUN_NEAREST_SHRUNKEN_CENTROID = RUN_NEAREST_SHRUNKEN_CENTROID
            )

            control_directory <- tempfile("supervised_classification_control_")
            dir.create(control_directory, recursive = TRUE, showWarnings = FALSE)

            run_state$control_directory <- control_directory
            run_state$settings_path <- file.path(control_directory, "settings.rds")
            run_state$status_path <- file.path(control_directory, "status.rds")
            run_state$console_path <- file.path(control_directory, "worker_console.txt")
            run_state$last_console_line <- 0L
            run_state$stop_requested <- FALSE

            saveRDS(settings, run_state$settings_path)

            rscript_executable <- file.path(
                R.home("bin"),
                if (.Platform$OS.type == "windows") "Rscript.exe" else "Rscript"
            )

            if (!file.exists(rscript_executable)) {
                rscript_executable <- Sys.which("Rscript")
            }

            if (!nzchar(rscript_executable) || !file.exists(rscript_executable)) {
                stop("Rscript executable could not be found.")
            }

            tcltk::tkdelete(log_widget, "1.0", "end")

            tcltk::tclvalue(status_var) <- "Running classification..."
            set_running_state(TRUE)

            run_state$process <- processx::process$new(
                command = rscript_executable,
                args = c(
                    SCRIPT_FILE,
                    "--worker",
                    run_state$settings_path,
                    run_state$status_path
                ),
                stdout = run_state$console_path,
                stderr = "2>&1",
                wd = SCRIPT_DIRECTORY,
                cleanup = TRUE,
                cleanup_tree = TRUE,
                windows_hide_window = TRUE
            )

            tcltk::tcl("after", 100, poll_worker)

        }, error = function(e) {
            set_running_state(FALSE)
            append_log(paste0("ERROR: ", conditionMessage(e)))
            tcltk::tclvalue(status_var) <- paste0("Error: ", conditionMessage(e))
            tcltk::tkmessageBox(
                icon = "error",
                type = "ok",
                title = "Invalid settings",
                message = conditionMessage(e)
            )
        })
    }

    close_action <- function() {
        process_object <- run_state$process
        alive <- if (!is.null(process_object)) {
            tryCatch(process_object$is_alive(), error = function(e) FALSE)
        } else {
            FALSE
        }

        if (isTRUE(alive)) {
            response <- as.character(
                tcltk::tkmessageBox(
                    icon = "warning",
                    type = "yesno",
                    title = "Classification is running",
                    message = "A classification run is still active. Stop it and close the window?"
                )
            )

            if (!identical(tolower(response), "yes")) {
                return(invisible(NULL))
            }

            run_state$stop_requested <- TRUE
            try(process_object$kill_tree(), silent = TRUE)
            if (tryCatch(process_object$is_alive(), error = function(e) FALSE)) {
                try(process_object$kill(), silent = TRUE)
            }
        }

        .classification_gui_log <<- NULL
        tcltk::tkdestroy(tt)
        invisible(NULL)
    }

    run_button <- tcltk::tkbutton(
        action_frame,
        text = "Run Classification",
        background = bg_run,
        foreground = "#123b18",
        font = "TkDefaultFont 11 bold",
        padx = 14,
        pady = 6,
        command = run_action
    )
    tcltk::tkpack(run_button, side = "left", padx = 4)

    stop_button <- tcltk::tkbutton(
        action_frame,
        text = "STOP",
        background = bg_stop,
        foreground = "#7a0000",
        activebackground = "#e58f8f",
        activeforeground = "#5a0000",
        font = "TkDefaultFont 11 bold",
        padx = 18,
        pady = 6,
        state = "disabled",
        command = stop_action
    )
    tcltk::tkpack(stop_button, side = "left", padx = 8)

    tcltk::tkpack(
        tcltk::tkbutton(
            action_frame,
            text = "Open Last Run",
            background = bg_button,
            padx = 10,
            pady = 6,
            command = function() {
                target <- if (nzchar(.LAST_RUN_DIRECTORY)) {
                    .LAST_RUN_DIRECTORY
                } else {
                    tcltk::tclvalue(output_var)
                }
                open_folder(target)
            }
        ),
        side = "left",
        padx = 4
    )

    tcltk::tkpack(
        tcltk::tkbutton(
            action_frame,
            text = "Clear Log",
            background = bg_button,
            padx = 10,
            pady = 6,
            command = function() {
                tcltk::tkdelete(log_widget, "1.0", "end")
            }
        ),
        side = "left",
        padx = 4
    )

    tcltk::tkpack(
        tcltk::tkbutton(
            action_frame,
            text = "Close",
            background = "#eeeeee",
            padx = 10,
            pady = 6,
            command = close_action
        ),
        side = "right",
        padx = 4
    )

    tcltk::tclvalue(status_var) <- "Ready. Select the training and classification files, choose algorithms, then run."
    tcltk::tkwait.window(tt)
    invisible(NULL)
}

trailing_arguments <- commandArgs(trailingOnly = TRUE)

if (
    length(trailing_arguments) >= 3L &&
    identical(trailing_arguments[1], "--worker")
) {
    run_supervised_classification_worker(
        trailing_arguments[2],
        trailing_arguments[3]
    )
} else {
    launch_supervised_classification_gui()
}
