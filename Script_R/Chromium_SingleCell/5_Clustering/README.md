# Step 5 — PCA, graph clustering, and UMAP

`Clustering_Rscript.R` reads a normalized Seurat object, calculates principal components, builds the nearest-neighbor graph, assigns graph-based clusters, calculates a UMAP embedding, and saves the clustered object for Step 6.

## Position in the pipeline

```text
Step 4 normalization
        ↓
Normalized Seurat object
        ↓
Step 5 PCA, neighbors, clustering, and UMAP
        ↓
seurat_clustered.rds
        ↓
Step 6 integration, reclustering, markers, and annotation
```

Step 5 creates the `pca` reduction required by `6_Integration_Annotation/Integration_Annotation.R`.

## Directory structure

```text
5_Clustering/
├── Clustering_Rscript.R
├── Input/
│   └── README_INPUTS.txt
└── Output/
```

The script resolves `Input` and `Output` relative to its own location. It creates both directories when they do not already exist.

## Input

The script searches recursively under `Input/` for `.rds` files and requires exactly one file. The object must inherit from the Seurat class.

The input is the normalized object produced by Step 4, normally one of:

```text
seurat_normalized_SCT.rds
seurat_normalized_LogNormalize.rds
```

## Assay selection

The analysis assay is selected from the assays stored in the object:

```text
SCT assay present  → use SCT
SCT assay absent   → use RNA
```

The selected assay becomes the Seurat default assay.

When the RNA assay is selected and has no `scale.data` layer, the script runs `ScaleData` before PCA. An SCT object uses the processed SCT assay directly.

## Settings

| Setting | Default | Function |
| --- | ---: | --- |
| `NUMBER_PCS` | `50` | Number of principal components requested from `RunPCA`. |
| `DIMS_TO_USE` | `1:30` | PCA dimensions requested for neighbors, clusters, and UMAP. |
| `CLUSTER_RESOLUTION` | `0.5` | Resolution passed to `FindClusters`. |
| `RANDOM_SEED` | `12345` | Seed used by clustering and UMAP. |

After PCA, `DIMS_TO_USE` is restricted to dimensions that actually exist in the `pca` embedding. The resulting dimension vector is recorded in `clustering_parameters.csv`.

## Analysis sequence

### 1. Principal-component analysis

```r
RunPCA(
    object,
    assay = analysis_assay,
    npcs = NUMBER_PCS
)
```

This adds a Seurat reduction named `pca` containing cell embeddings and feature loadings.

### 2. Nearest-neighbor graph

```r
FindNeighbors(
    object,
    reduction = "pca",
    dims = valid_dims
)
```

The neighbor graph represents similarity between cells in the selected PCA dimensions.

### 3. Graph clustering

```r
FindClusters(
    object,
    resolution = CLUSTER_RESOLUTION,
    random.seed = RANDOM_SEED
)
```

Cluster assignments are stored in the `seurat_clusters` metadata column and become the active Seurat identities.

### 4. UMAP

```r
RunUMAP(
    object,
    reduction = "pca",
    dims = valid_dims,
    seed.use = RANDOM_SEED
)
```

This adds the two-dimensional `umap` reduction used by the cluster and sample plots.

## Saved Seurat object

```text
Output/seurat_clustered.rds
```

This object contains the normalized assays inherited from Step 4 together with the Step 5 PCA, graph, cluster assignments, and UMAP. It is the input object described by `6_Integration_Annotation/Input/README_INPUTS.txt`.

## PCA elbow plot

```text
Output/PCA_elbow_plot.pdf
```

The horizontal axis represents principal-component number. The vertical axis represents the standard deviation associated with each component. The curve displays how the amount of variation represented by successive components changes across the first 50 or fewer available components.

## UMAP by cluster

```text
Output/UMAP_by_cluster.png
Output/UMAP_by_cluster.pdf
```

Each point is a cell positioned by its two UMAP coordinates. Color represents the `seurat_clusters` assignment. Cluster numbers are printed at the corresponding point groups with label repulsion enabled.

## UMAP by sample

```text
Output/UMAP_by_sample.png
Output/UMAP_by_sample.pdf
```

These files are created when the object metadata contains `sample_id`. They use the same Step 5 UMAP coordinates as the cluster plot, while color represents the originating sample instead of the cluster assignment.

## Cluster counts

```text
Output/cluster_counts_by_sample.csv
```

This table is constructed from the cross-tabulation of cluster and sample metadata.

| Column | Content |
| --- | --- |
| `cluster` | Value from `seurat_clusters`. |
| `sample_id` | Sample metadata value, or `Sample` when `sample_id` is absent. |
| `Freq` | Number of cells in the cluster/sample combination. |

## Parameter record

```text
Output/clustering_parameters.csv
```

The table records:

- selected analysis assay;
- requested number of principal components;
- PCA dimensions actually used;
- clustering resolution.

## Logging and session information

```text
Output/run_log.txt
Output/sessionInfo.txt
```

`run_log.txt` contains the resolved directories, start time, Seurat messages, and session information written during script exit. `sessionInfo.txt` contains a separate copy of the R session information after successful completion.

## Relationship between Step 5 and Step 6

Step 5 establishes the initial PCA-based graph, clusters, and UMAP. Step 6 reads `seurat_clustered.rds` and uses its PCA coordinates as the starting representation.

When Step 6 uses `INTEGRATION_METHOD = "None"`, it recalculates neighbors, clusters, and UMAP from PCA. When it uses `INTEGRATION_METHOD = "Harmony"`, it calculates Harmony coordinates from PCA and recalculates neighbors, clusters, and UMAP from the Harmony reduction. Step 6 then performs marker detection and cell-type annotation.
