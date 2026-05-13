import numpy as np
import pandas as pd
## Disable Arrow-backed string storage so anndata can write h5ad without errors
pd.options.mode.string_storage = "python"
try:
    pd.options.future.infer_string = False
except Exception:
    pass
import anndata as ad
import snapatac2 as snap
from os.path import join as pjoin
import os
from tqdm import tqdm

scratch_dir = "/root/capsule/scratch"
file_path = pjoin(scratch_dir, "concatenated.h5ads")

## Global QC thresholds
tss_min = 2.0
frip_min = 0.2

## Explicit obs columns for global QC
tss_col = "tsse"
n_frag_col = "n_fragment"
n_frag_peak_col = "n_frag_overlap_peak"

## Open concatenated dataset in read/write mode
data = snap.read_dataset(file_path, mode="r+")
obs = data.adatas.obs

## Compute pass/fail mask
tss = pd.to_numeric(obs[tss_col], errors="coerce")
n_frag = pd.to_numeric(obs[n_frag_col], errors="coerce")
n_frag_peak = pd.to_numeric(obs[n_frag_peak_col], errors="coerce")
frip = n_frag_peak / n_frag
pass_mask = (tss >= tss_min) & (frip >= frip_min)

## Add global QC flags to concatenated dataset
global_pass = np.asarray(pass_mask, dtype=bool)
frip_values = np.asarray(frip, dtype=float)
data.obs["frip"] = frip_values
data.obs["global_qc_pass"] = global_pass
data.obs["global_qc_tss_threshold"] = tss_min
data.obs["global_qc_frip_threshold"] = frip_min

total_cells = data.shape[0]
pass_cells = int(np.sum(global_pass))
fail_cells = int(total_cells - pass_cells)

print(f"[DONE] Added global QC flag to {file_path}")
print(f"[INFO] Using columns: TSS='{tss_col}', FRIP='{n_frag_peak_col}/{n_frag_col}'")
print(f"[INFO] Thresholds: TSS >= {tss_min}, FRIP >= {frip_min}")
print(f"[INFO] Passing cells: {pass_cells}/{total_cells} ({(pass_cells / max(total_cells, 1)):.2%})")
print(f"[INFO] Failing cells: {fail_cells}/{total_cells} ({(fail_cells / max(total_cells, 1)):.2%})")

data.close()

## Build per-library pass masks directly from each AnnData's own obs
## Gather h5ad files the same way as in concatenate
h5ad_files = {}
library_dirs = sorted([d for d in os.listdir(scratch_dir) if os.path.isdir(pjoin(scratch_dir, d))])
for lib_dir in library_dirs:
    lib_path = pjoin(scratch_dir, lib_dir)
    files = [f for f in os.listdir(lib_path) if f.endswith("_atac.metrics.h5ad")]
    if len(files) == 0:
        continue
    file_path_lib = pjoin(lib_path, files[0])
    h5ad_files[lib_dir] = file_path_lib

qc_h5ad_files = {}
for key, h5ad_path in tqdm(h5ad_files.items(), desc="QC filtering libraries"):
    adata = ad.read_h5ad(h5ad_path)
    n = adata.n_obs
    tss_lib = pd.to_numeric(adata.obs[tss_col], errors="coerce")
    n_frag_lib = pd.to_numeric(adata.obs[n_frag_col], errors="coerce")
    n_frag_peak_lib = pd.to_numeric(adata.obs[n_frag_peak_col], errors="coerce")
    frip_lib = n_frag_peak_lib / n_frag_lib
    lib_pass = (tss_lib >= tss_min) & (frip_lib >= frip_min)
    ##
    n_pass = int(np.sum(lib_pass))
    if n_pass == 0:
        print(f"[SKIP] {key}: 0 cells pass QC")
        continue
    ##
    ## Subset and write to a _qc_pass file alongside the original
    out_path = h5ad_path.replace(".h5ad", "_qc_pass.h5ad")
    subset = adata[np.asarray(lib_pass), :].copy()
    ## Safety net: convert any remaining Arrow-backed dtypes for h5ad compatibility
    def _dearrow_df(df):
        df.index = pd.Index(list(df.index.astype(str)))
        for col in df.columns:
            arr = df[col]
            if isinstance(arr.dtype, pd.ArrowDtype) or type(arr.array).__name__ == 'ArrowStringArray':
                df[col] = list(arr.astype(str))
            elif isinstance(arr.dtype, pd.CategoricalDtype):
                vals = list(arr.astype(str))
                df[col] = pd.Categorical(vals)
        return df
    subset.obs = _dearrow_df(subset.obs)
    subset.var = _dearrow_df(subset.var)
    subset.write(out_path)
    del adata, subset
    qc_h5ad_files[out_path] = snap.read(out_path, backed='r')
    print(f"[DONE] {key}: {n_pass}/{n} cells pass → {out_path}")

## Re-concatenate passing libraries into a new AnnDataSet
out_concat = pjoin(scratch_dir, "concatenated_global_qc_pass.h5ads")
if qc_h5ad_files:
    concatenated = snap.AnnDataSet(
        adatas=[(k, qc_h5ad_files[k]) for k in qc_h5ad_files],
        filename=out_concat
    )
    print(f"[DONE] Concatenated {len(qc_h5ad_files)} QC-pass libraries → {out_concat}")
    concatenated.close()

for v in qc_h5ad_files.values():
    v.close()