#Clustering

#auto_correlation_topN_positive.R
#
#Reads C:/Haley/CorrelationWithClinical/Test/Input.tabtxt (genes × samples),
#computes Pearson, Spearman & Kendall correlations for selected gene pairs,
#automatically chooses full‑matrix vs per‑pair loop, then
#filters by top‑N, correlation threshold, or p‑value threshold,
#and displays the gene names in the initial analysis group.
#-----------------------------------------------------------------------------

#1) Setup
rm(list=ls())
setwd("P:\\Biostat\\BreastCancer\\BrCa_IR_Assay\\Clustering\\Interractom\\Samples")

#2) Parameters
# - group_size: 0 = full‑matrix; otherwise number of genes in first block
# - top_n: if filter_method="top_n", number of best positive correlations to keep  #IS IT FOR EACH METHOD OR ACROSS ALL METHODS ?
# - filter_method: one of "top_n", "corr_threshold", "pvalue_threshold"
# - cor_threshold: if filter_method="corr_threshold", correlation cutoff (0–1)
# - pvalue_threshold: if filter_method="pvalue_threshold", p-value cutoff (0–1)
# - do_spearman: TRUE to compute Spearman correlations; FALSE to skip
# - do_kendall:  TRUE to compute Kendall correlations;  FALSE to skip

group_size        <- 0
top_n             <- 100000
filter_method     <-"pvalue_threshold"       #options: "top_n", "corr_threshold", "pvalue_threshold"
cor_threshold     <- 0.80
pvalue_threshold  <- 0.05
do_spearman       <- F    # NON Parametric equivalent to Pearson Correlation
do_kendall        <- F  #  NON Parametric (using concordant pairs and discordant pairs

#3) Read input
cat("Reading Input.tabtxt...\n")
raw         <- read.table("Input.tabtxt", sep="\t", header=TRUE,
                          check.names=FALSE, stringsAsFactors=FALSE, fill=TRUE)
genes       <- raw[[1]]
expr_mat    <- as.matrix(suppressWarnings(apply(raw[,-1], 2, as.numeric)))
n_genes     <- nrow(expr_mat)
n_samples   <- ncol(expr_mat)
cat("Loaded", n_genes, "genes ×", n_samples, "samples\n\n")

#4) Clamp group_size and compute percentage
group_size <- max(0, min(group_size, n_genes))
pct        <- if(n_genes > 0) (group_size / n_genes) * 100 else 0

#5) Decide computation strategy
use_full_matrix <- (group_size == 0) || (pct > 5) || (group_size == n_genes)
if (!do_spearman) cat("Spearman correlations DISABLED\n")
if (!do_kendall)  cat("Kendall correlations DISABLED\n")

#6) Display the names of genes in the initial group
if (!use_full_matrix) {
  cat(sprintf("GROUP MODE: analyzing first %d genes (%.2f%% of %d)\n",
              group_size, pct, n_genes))
  cat("Genes in analysis group:\n")
  cat(paste(genes[1:group_size], collapse=", "), "\n\n")
} else {
  cat(sprintf("FULL‑MATRIX MODE: analyzing all %d genes\n", n_genes))
  cat("Analyzing all genes:\n")
  cat(paste(genes, collapse=", "), "\n\n")
}

#7) Compute correlations
if (use_full_matrix) {
  #full-matrix computation
  cor_p <- cor(t(expr_mat), use="pairwise.complete.obs", method="pearson")
  if (do_spearman) cor_s <- cor(t(expr_mat), use="pairwise.complete.obs", method="spearman")
  if (do_kendall)  cor_k <- cor(t(expr_mat), use="pairwise.complete.obs", method="kendall")

  ut      <- upper.tri(cor_p)
  idx_mat <- which(ut, arr.ind=TRUE)
  rp_all  <- cor_p[ut]
  rs_all  <- if(do_spearman) cor_s[ut] else rep(NA_real_, length(rp_all))
  rk_all  <- if(do_kendall)  cor_k[ut] else rep(NA_real_, length(rp_all))

} else {
  #loop-mode computation on subset
  k     <- group_size
  u1    <- which(upper.tri(matrix(0, k, k)), arr.ind=TRUE)
  p1    <- cbind(i=u1[,1], j=u1[,2])
  p2    <- expand.grid(i=1:k, j=(k+1):n_genes)
  pairs <- rbind(p1, as.matrix(p2))
  np    <- nrow(pairs)
  cat("Total pairs to evaluate in group:", np, "\n")

  means <- rowMeans(expr_mat, na.rm=TRUE)
  sds   <- apply(expr_mat, 1, sd, na.rm=TRUE)
  ranks <- t(apply(expr_mat, 1, rank, na.last="keep"))

  rp_all <- numeric(np)
  rs_all <- if(do_spearman) numeric(np) else rep(NA_real_, np)
  rk_all <- if(do_kendall)  numeric(np) else rep(NA_real_, np)

  prog <- max(1, floor(np/10))
  cat("Computing per‑pair correlations...\n")
  for (m in seq_len(np)) {
    i <- pairs[m,1]; j <- pairs[m,2]
    x <- expr_mat[i,]; y <- expr_mat[j,]
    cov_xy    <- sum((x - means[i]) * (y - means[j]), na.rm=TRUE) /
                 (sum(!is.na(x & y)) - 1)
    rp_all[m] <- cov_xy / (sds[i] * sds[j])
    if (do_spearman)
      rs_all[m] <- cor(ranks[i,], ranks[j,], use="pairwise.complete.obs", method="pearson")
    if (do_kendall)
      rk_all[m] <- cor(x, y, use="pairwise.complete.obs", method="kendall")
    if (m %% prog == 0)
      cat(sprintf("  %3d%% complete\n", round(m/np*100)))
  }
  cat("Loop complete\n\n")
  idx_mat <- pairs
}

#8) Keep only positive correlations
pos_p <- which(rp_all > 0)
pos_s <- if(do_spearman) which(rs_all > 0) else integer(0)
pos_k <- if(do_kendall)  which(rk_all > 0) else integer(0)

#9) Compute p-values for positives
df <- n_samples - 2

tp_all  <- rp_all[pos_p] * sqrt(df) / sqrt(1 - rp_all[pos_p]^2)
p_p_all <- 2 * pt(-abs(tp_all), df=df)

if (do_spearman) {
  ts_all  <- rs_all[pos_s] * sqrt(df) / sqrt(1 - rs_all[pos_s]^2)
  p_s_all <- 2 * pt(-abs(ts_all), df=df)
}

if (do_kendall) {
  m        <- n_samples
  var_tau  <- 2 * (2*m + 5) / (9 * m * (m - 1))
  zk_all   <- rk_all[pos_k] / sqrt(var_tau)
  p_k_all  <- 2 * pnorm(-abs(zk_all))
}

#10) Select indices according to filter_method
if (filter_method == "corr_threshold") {
  cat(sprintf("Filtering by correlation >= %.4f\n", cor_threshold))
  sel_p <- which(rp_all[pos_p] >= cor_threshold)
  sel_s <- if(do_spearman) which(rs_all[pos_s] >= cor_threshold) else integer(0)
  sel_k <- if(do_kendall)  which(rk_all[pos_k] >= cor_threshold) else integer(0)

} else if (filter_method == "pvalue_threshold") {
  cat(sprintf("Filtering by p-value <= %.4g\n", pvalue_threshold))
  sel_p <- which(p_p_all <= pvalue_threshold)
  sel_s <- if(do_spearman) which(p_s_all <= pvalue_threshold) else integer(0)
  sel_k <- if(do_kendall)  which(p_k_all <= pvalue_threshold) else integer(0)

} else {
  cat("Selecting top", top_n, "positive per method...\n")
  sel_p <- head(order(rp_all[pos_p], decreasing=TRUE), top_n)
  sel_s <- if(do_spearman) head(order(rs_all[pos_s], decreasing=TRUE), top_n) else integer(0)
  sel_k <- if(do_kendall)  head(order(rk_all[pos_k], decreasing=TRUE), top_n) else integer(0)
}

keep_indices <- unique(c(pos_p[sel_p], pos_s[sel_s], pos_k[sel_k]))
cat("Total unique pairs kept:", length(keep_indices), "\n\n")

idx_keep <- idx_mat[keep_indices, , drop=FALSE]
rp_keep  <- rp_all[keep_indices]
rs_keep  <- rs_all[keep_indices]
rk_keep  <- rk_all[keep_indices]

#11) Re-compute p-values for kept correlations
tp  <- rp_keep * sqrt(df) / sqrt(1 - rp_keep^2);    p_p <- 2 * pt(-abs(tp), df=df)
if (do_spearman) {
  ts  <- rs_keep * sqrt(df) / sqrt(1 - rs_keep^2);  p_s <- 2 * pt(-abs(ts), df=df)
}
if (do_kendall) {
  zk  <- rk_keep / sqrt(var_tau);                    p_k <- 2 * pnorm(-abs(zk))
}

#12) Assemble and write
cat("Assembling output... total unique pairs:", nrow(out <- data.frame(
  GeneSource = genes[idx_keep[,1]],
  Pearson    = round(rp_keep,    4),
  p_Pearson  = signif(p_p,       4),
  stringsAsFactors = FALSE
)), "\n")

#Add optional columns for Spearman/Kendall
if (do_spearman) {
  out$Spearman   <- round(rs_keep,    4)
  out$p_Spearman <- signif(p_s,       4)
}
if (do_kendall) {
  out$Kendall    <- round(rk_keep,    4)
  out$p_Kendall  <- signif(p_k,       4)
}
out$GeneTarget <- genes[idx_keep[,2]]
out <- unique(out)

#Determine threshold label for filename
if (filter_method == "pvalue_threshold") {
  thr_label <- sprintf("p%.4g", pvalue_threshold)
} else if (filter_method == "corr_threshold") {
  thr_label <- sprintf("r%.2f", cor_threshold)
} else {
  thr_label <- sprintf("top%d", top_n)
}

#Determine count label for filename
count <- nrow(out)
if (count >= 1e6) {
  count_str <- sprintf("%.1fM", count/1e6)
} else if (count >= 1e3) {
  count_str <- sprintf("%.1fk", count/1e3)
} else {
  count_str <- as.character(count)
}

#Construct dynamic filename
file_name <- sprintf("R_Correlation_%s_%s.tabtxt", thr_label, count_str)

#Write to file
cat("Writing output to", file_name, "...\n")
write.table(
  out,
  file      = file_name,
  sep       = "\t",
  quote     = FALSE,
  row.names = FALSE,
  col.names = TRUE
)
cat("Done: wrote", count, "unique positive pairs to", file_name, "\n")
