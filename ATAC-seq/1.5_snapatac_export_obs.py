import os
import pandas as pd
import numpy as np
from os.path import join as pjoin
import anndata
from tqdm import tqdm

scratch_dir = "/root/capsule/scratch"
results_dir = "/root/capsule/results"

## Find all preprocessed h5ad files
h5ad_files = []
for lib_dir in sorted(os.listdir(scratch_dir)):
    lib_path = pjoin(scratch_dir, lib_dir)
    if not os.path.isdir(lib_path):
        continue
    for f in os.listdir(lib_path):
        if f.endswith(".h5ad"):
            h5ad_files.append(pjoin(lib_path, f))

## Read obs and frag_size_distr from each h5ad and combine
obs_dfs = []
frag_size_dfs = []
for f in tqdm(h5ad_files, desc="Reading obs"):
    adata = anndata.read_h5ad(f, backed='r')
    obs_df = pd.DataFrame(adata.obs)
    obs_dfs.append(obs_df)
    if 'frag_size_distr' in adata.uns:
        fsd = pd.DataFrame(adata.uns['frag_size_distr'])
        lib_name = os.path.basename(os.path.dirname(f))
        fsd['library'] = lib_name
        frag_size_dfs.append(fsd)
    adata.file.close()

pd.concat(obs_dfs, ignore_index=True).to_csv(pjoin(results_dir, "adatas_obs.csv"))
pd.concat(frag_size_dfs, ignore_index=True).to_csv(pjoin(results_dir, "frag_size_distr.csv"), index=False)