import os
import snapatac2 as snap
from tqdm import tqdm
from os.path import join as pjoin

scratch_dir = "/root/capsule/scratch"
out_file = pjoin(scratch_dir, "concatenated.h5ads")

## Walk through all library directories and collect h5ad files
h5ad_files = {}
library_dirs = sorted([d for d in os.listdir(scratch_dir) if os.path.isdir(pjoin(scratch_dir, d))])

for lib_dir in tqdm(library_dirs, desc="Processing libraries"):
    lib_path = pjoin(scratch_dir, lib_dir)
    files = [f for f in os.listdir(lib_path) if f.endswith("_atac.metrics.h5ad")]
    if len(files) == 0:
        continue
    file_path = pjoin(lib_path, files[0])
    adata = snap.read(file_path, backed='r')
    h5ad_files[file_path] = adata

## Concatenate all h5ad files into AnnDataSet
if h5ad_files:
    concatenated = snap.AnnDataSet(
        adatas=[(k, h5ad_files[k]) for k in h5ad_files],
        filename=out_file
    )
    print(f"[DONE] Concatenated {len(h5ad_files)} libraries → {out_file}")
    concatenated.close()

for k in h5ad_files:
    h5ad_files[k].close()