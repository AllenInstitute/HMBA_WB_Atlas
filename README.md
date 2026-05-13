# HMBA WB Atlas — v0.1
<img width="1153" height="610" alt="image" src="https://github.com/user-attachments/assets/6dfda292-97b7-4b30-b75c-6d11b12c5dea" />

The HMBA WB Atlas v0.1 is a cross-species whole-brain (WB) single-cell RNA-seq taxonomy from the Human Mammalian Brain Atlas (HMBA) project, covering **human, macaque, and marmoset**, with **mouse** as the reference taxonomy. This is the first internal data share.

- **Species:** human, macaque, marmoset (mouse used as reference).
- **Neighborhoods:** `HY-EA-Glut-GABA`, `TH-EPI-Glut`, `Pallium-Glut`, `NN-IMN`, `Subpallium-GABA`, `P-MY-CB-GABA`, `P-MY-CB-Glut`, `MB-Glut-Dopa-Sero`, and `MB-GABA`.
  - Note: the four midbrain–hindbrain neighborhoods (`P-MY-CB-GABA`, `P-MY-CB-Glut`, `MB-Glut-Dopa-Sero`, and `MB-GABA`) were integrated and shipped together as `MB-HB`.
- **Hierarchy:** `neighborhood` → `class` → `subclass` → `cl` (cluster).

---

## Pipeline

![HMBA WB Atlas workflow](docs/workflow.png)

---

## Delivered files

Everything for v0.1 lives under a single S3 prefix:

```
s3://hmba-cross-species-wg-802451596237-us-west-2/HMBA/Aim1_Atlases/HMBA_WB_Atlas/2026-03-25-data-share/
```

### 1. Per-species × per-neighborhood, ortholog gene space (Zarr)

```
{species}_{neighborhood}.zarr
```

- `species` ∈ `{human, macaque, marmoset}`
- `neighborhood` ∈ `{HY-EA-Glut-GABA, TH-EPI-Glut, Pallium-Glut, NN-IMN, Subpallium-GABA, MB-HB}`
- `var`: 15,138 mouse/human/marmoset/macaque orthologs.
- `obs`: full metadata (see [Metadata fields](#metadata-fields)). All cells passing basic QC are kept. Cells flagged as junk during the subsequent global or per-neighborhood integrations are not removed; they are marked with a `1` in the `junk_global` or `junk_neigh` column, respectively.

### 2. Per-species, full gene space (Zarr or h5ad)

Contains the same cells as (1) but in the **species-native full gene space**.

```
marmoset_allGenes.h5ad
macaque_allGenes.h5ad
human_allGenes/human_allGenes_{neighborhood}.zarr
```

- `obs` columns are identical to the ortholog Zarrs above.
- `var` is the full per-species gene set.

### 3. Annotation spreadsheet

A single Google Sheets workbook with sheets for each level of the hierarchy:

```
https://docs.google.com/spreadsheets/d/1ibqQZTImpm39rzf_o0o9un2_yZmJaKUcc_bvRDSMzL8/edit?usp=sharing
```
It might be updated to append more columns but the link stays the same.

- **`cl` sheet** — one row per cluster (`cluster`). Columns: `cluster id`, `cluster`, `species`, `neighborhood`, `subclass`, `class`, `number of cells`, top 3 brain regions / ROIs, QC summaries (median gene counts, UMI counts, mitochondrial %, doublet scores, distance to closest mouse-cluster centroid), study/donor composition + entropy, sex, sample (10X loads), transferred-label majority and probability for `BG:*`, `Siletti:*`, `marmosetSubcortical:*` taxonomies, and a `note` column flagging junk or low-quality clusters.
- **`subclass` sheet** — one row per subclass per species.
- **`class` sheet** — one row per class per species.

### 4. Latent spaces

scVI latent coordinates for **almost every cell** (per species and per neighborhood):

```
scVI_embeddings/{species}_{neighborhood}.csv
```
Indexed by cell barcode. Note: a few cells from undersampled donors do not have scVI embeddings, because those donors were excluded from scVI training due to having too few cells after subsampling.

---

## Metadata fields

The `obs` schema is identical across the ortholog Zarrs and the full-gene-space Zarr/h5ads. Macaque and marmoset stores share the same 41 columns; human stores include 7 additional Siletti-derived columns (listed at the end).

### Sample / donor identity
| Column | Description |
|---|---|
| `species` | `human` / `macaque` / `marmoset` |
| `donor` | Donor ID |
| `sample` | Library / 10X load ID |
| `sex` | Donor sex |
| `age` | Donor age |
| `study` | Source study / dataset the cell came from. One of `HMBA`, `Siletti`, `AIT21`, `Macosko`. |
| `chemistry` | 10X chemistry version: `multiome` for HMBA, `snRNAseq` for Siletti, `10Xv2` and `10Xv3` for AIT21, and `Macosko_snRNAseq` for Macosko. |

### Anatomical
| Column | Description |
|---|---|
| `brain region` | Coarse brain region |
| `roi` | Region-of-interest (finer than `brain region`). Note: currently inaccurate for marmoset — values should all be `brain` (see To-do). |


### Cell-type labels (HMBA WB taxonomy v0.1, final)
| Column | Description |
|---|---|
| `cl` | Cluster ID, formatted `{species}:{neighborhood}:{int}` |
| `subclass` | Subclass label |
| `class` | Class label |
| `neighborhood` | Assigned neighborhood (one of those listed above) — final assignment used for clustering |


### Initial cell-type-mapper (CTM) reference mapping
Per-cell labels and probabilities from the initial reference mapping against the human WB v1.5 reference:
| Column | Description |
|---|---|
| `ctm_class`, `ctm_class_prob` | Predicted class and probability |
| `ctm_subclass`, `ctm_subclass_prob` | Predicted subclass and probability |
| `ctm_cl`, `ctm_cl_prob` | Predicted cluster and probability |

### Random-forest label transfer
Per-cell predictions from the random-forest classifier trained on the integrated space. The `RF_*` columns come from the first neighborhood-level integration, in which cells were partitioned into four groups of neighborhoods: HY-Subpallium, MB-HB-TH, Pallium-Glut, and NN-IMN. Subclass labels were then transferred from mouse to further split the HY-Subpallium group into HY and Subpallium, and the MB-HB-TH group into MB-HB and TH. Integration was rerun within each of the six resulting neighborhoods, yielding the `rf_*_reint` columns.

| Column | Description |
|---|---|
| `RF_neighborhood`, `RF_neighborhood_prob` | Predicted neighborhood and probability |
| `RF_class`, `RF_class_prob` | Predicted class and probability |
| `RF_subclass`, `RF_subclass_prob` | Predicted subclass and probability |
| `rf_class_reint`, `rf_class_reint_prob` | Re-integrated class prediction and probability |
| `rf_subclass_reint`, `rf_subclass_reint_prob` | Re-integrated subclass prediction and probability |

### Other intermediate cell-type labels
| Column | Description |
|---|---|
| `concensus_subclass`, `concensus_class` | Joint labels from the cell-type-mapper (lifted to AIT33 labels) and original AIT33 labels |
| `neighborhood_byMapping` | Neighborhood labels based on the mapped subclass labels from the initial mapping to the human WB v1.5 reference |

### Junk flags
| Column | Description |
|---|---|
| `junk_global` | Cell flagged as junk in the global integrated space before clustering |
| `junk_neigh` | Cell flagged as junk in the per-neighborhood integrated space before clustering |

### QC metrics (continuous)
| Column | Description |
|---|---|
| `n_genes_by_counts` | Genes detected per cell |
| `total_counts` | Total UMI count per cell |
| `pct_counts_mt` | Mitochondrial read percentage |
| `doublet_score` | dblFinder doublet score |
| `solo_doublet_score` | solo doublet score |
| `tso_reads_fraction` | Fraction of reads containing the 10X TSO sequence, derived from the Optimus pipeline |
| `reads_exonic_intronic_fraction` | Fraction of reads mapping to exons + introns, derived from the Optimus pipeline |


### Human-only columns
These exist only in the human ortholog/full-gene Zarrs (carried over from the Siletti human atlas):

| Column | Description |
|---|---|
| `Siletti_supercluster_term` | Siletti supercluster label |
| `Siletti_cluster_name` | Siletti cluster name |
| `Siletti_cluster_id` | Siletti cluster integer ID |
| `Siletti_subcluster_id` | Siletti subcluster integer ID |
| `cl_v15`, `subclass_v15`, `class_v15` | human WB v1.5 labels |

---

## To-do / improvements for the next iteration

- Perform clustering using the full gene space.
- Correct Siletti NaNs in the `sample` column.
- Use updated metadata from NIMP to correct marmoset `roi` to all `brain`.
- Fix mouse donor info — need exact donor names; see the new metadata for both AIT21 and Macosko from CK.
- Rename `cl` → `cluster` across all files.

---
