import numpy as np
import pandas as pd
import snapatac2 as snap
from os.path import join as pjoin
import os
import glob
import boto3

s3_client = boto3.client("s3")
s3_bucket = "hmba-human-wg-802451596237-us-west-2"

scratch_dir = "/root/capsule/scratch"
results_dir = "/root/capsule/results"

## Read library manifest produced by 11_atac_tracker
lib_info = glob.glob("/data/pipeline/*.csv")[0]
input_df = pd.read_csv(lib_info)

## Explicit obs columns for global QC
tss_col = "tsse"
n_frag_col = "n_fragment"
n_frag_peak_col = "n_frag_overlap_peak"

## Global QC thresholds
tss_min = 2.0
frip_min = 0.2

## Download h5ad from S3 and apply per-library QC filtering
for _, row in input_df.iterrows():
    library = row["library_id"]
    s3_path = row["s3_path"]
    h5ad_filename = os.path.basename(s3_path)

    lib_scratch = pjoin(scratch_dir, library)
    os.makedirs(lib_scratch, exist_ok=True)

    local_file = pjoin(lib_scratch, h5ad_filename)
    if not os.path.exists(local_file):
        s3_key = s3_path.replace(f"s3://{s3_bucket}/", "")
        print(f"[DOWNLOAD] {s3_path} -> {local_file}")
        s3_client.download_file(s3_bucket, s3_key, local_file)

    print(f"[START] QC filtering: {library}")
    adata = snap.read(local_file, backed='r')
    n = adata.n_obs
    tss_lib = pd.to_numeric(adata.obs[tss_col], errors="coerce")
    n_frag_lib = pd.to_numeric(adata.obs[n_frag_col], errors="coerce")
    n_frag_peak_lib = pd.to_numeric(adata.obs[n_frag_peak_col], errors="coerce")
    frip_lib = n_frag_peak_lib / n_frag_lib
    lib_pass = (tss_lib >= tss_min) & (frip_lib >= frip_min)

    n_pass = int(np.sum(lib_pass))
    if n_pass == 0:
        print(f"[SKIP] {library}: 0 cells pass QC")
    else:
        ## Subset using snapatac2 and write to a _qc_pass file
        out_path = local_file.replace(".h5ad", "_qc_pass.h5ad")
        subset = adata.subset(np.asarray(lib_pass), out=out_path)
        subset.close()

    ## Close file
    adata.close()

    ## Write a file so nextflow is happy even if processing is skipped
    with open(f"/results/output_qc_{library}.txt", "w") as file:
        file.write(f"[DONE] Processed: {library}\n")
        file.write(f"QC thresholds: TSS >= {tss_min}, FRIP >= {frip_min}\n")
        file.write(f"Passing cells: {n_pass}/{n}\n")

    ##
    print(f"[DONE] {library}: {n_pass}/{n} cells pass → {out_path}")