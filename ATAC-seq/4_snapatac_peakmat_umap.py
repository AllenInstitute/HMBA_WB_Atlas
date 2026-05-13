import os
import pandas as pd
import re
from os.path import join as pjoin
import snapatac2 as snap
import anndata as ad

scratch_dir = "/root/capsule/scratch"
groupby = 'subclass'

## Load concatenated dataset
file_path = pjoin(scratch_dir, "concatenated.h5ads")
data = snap.read_dataset(file_path, mode='r+')
data.obs[groupby] = data.adatas.obs[groupby]

## Make peak matrix from merged peaks
peak_path = pjoin(scratch_dir, "merged_peaks.bed")
peak_adata = snap.pp.make_peak_matrix(data, peak_file=peak_path)

## Write out peak matrix
peak_adata.write_h5ad(pjoin(scratch_dir, "concatenated_peakmat.h5ad"))
data.close()

## Dimensionality reduction and UMAP
snap.pp.select_features(peak_adata, n_features=250000)
snap.tl.spectral(peak_adata)
snap.tl.umap(peak_adata)

## Add subclass and donor annotations
peak_adata.obs[groupby] = data.obs[groupby] if hasattr(data, 'obs') else peak_adata.obs.get(groupby, 'nan')

## Reload to add donor info
anno_table = pd.read_csv(pjoin("/data/WB_HMBA_CrossSpecies_03252025_metadata", 'human_obs_metadata.csv'), index_col=0)
donor_dict = dict(zip(anno_table.index, anno_table['donor']))
peak_adata.obs["donor"] = [str(donor_dict.get(x, 'nan')) for x in peak_adata.obs_names]

## Save with UMAP
peak_adata.write_h5ad(pjoin(scratch_dir, "concatenated_peakmat_UMAP.h5ad"))

## Harmony batch correction by donor
peak_adata = ad.read_h5ad(pjoin(scratch_dir, "concatenated_peakmat_UMAP.h5ad"))
snap.pp.harmony(peak_adata, batch="donor", max_iter_harmony=20)
snap.tl.umap(peak_adata, use_rep="X_spectral_harmony")

## Export UMAP coordinates
umap_df = pd.DataFrame(peak_adata.obsm['X_umap'], index=peak_adata.obs_names, columns=['UMAP1', 'UMAP2'])
umap_df[groupby] = peak_adata.obs[groupby].values
umap_df.to_csv(pjoin(scratch_dir, "concatenated_peakmat_UMAP_harmony.csv"))

## Write final output
peak_adata.write_h5ad(pjoin(scratch_dir, "concatenated_peakmat_UMAP.h5ad"))
print(f"[DONE] Peak matrix, UMAP, and harmony correction complete")