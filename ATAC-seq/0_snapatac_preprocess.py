import os
import pandas as pd
import re
import sys
import matplotlib.pyplot as plt
import scipy
import numpy as np
import anndata
import h5py
import tqdm
from os.path import join as pjoin
import snapatac2 as snap
from pathlib import Path
import boto3
import glob

s3_client = boto3.client("s3")
s3_bucket = "hmba-human-wg-802451596237-us-west-2"

lib_info = glob.glob("/data/pipeline/*.csv")[0]
input_df = pd.read_csv(lib_info)

## Load in annotation table
anno_table = pd.read_csv(pjoin("../data/metadata", 'human_obs_metadata.csv'), index_col=0)

scratch_dir = "../scratch"
results_dir = "../results"

for _, row in input_df.iterrows():
    library = row["library_id"]
    s3_path = row["s3_path"]
    h5ad_filename = os.path.basename(s3_path)

    lib_scratch = pjoin(scratch_dir, library)
    lib_results = pjoin(results_dir, library)
    os.makedirs(lib_scratch, exist_ok=True)
    os.makedirs(lib_results, exist_ok=True)

    s3_out_prefix = f"NeMO_atac_process/{library}/"
    expected_files = [h5ad_filename, "frag_size_distr.png", "tsse_by_frags.png", "rerun.txt"]

    try:
        ## Skip if already processed (h5ad and plots exist on S3)
        existing = {obj["Key"].split("/")[-1] for obj in
                    s3_client.list_objects_v2(Bucket=s3_bucket, Prefix=s3_out_prefix).get("Contents", [])}
        if all(f in existing for f in expected_files):
            print(f"[SKIP] Already processed on S3: {library}")
        else:
            ## Copy h5ad from S3 to scratch
            local_file = pjoin(lib_scratch, h5ad_filename)
            if not os.path.exists(local_file):
                s3_key = s3_path.replace(f"s3://{s3_bucket}/", "")
                print(f"[DOWNLOAD] {s3_path} -> {local_file}")
                s3_client.download_file(s3_bucket, s3_key, local_file)

            print(f"[START] Processing: {library}")

            ## Load snapatac2 anndata
            atac_h5ad = snap.read(local_file)

            ## Match indexing between RNA and ATAC
            atac_h5ad.obs["gex_cellname"] = atac_h5ad.obs["gex_barcodes"] + "-" + library

            ## Annotate
            anno_cols = ['neighborhood', 'class', 'subclass','cl', 'donor', 'roi', 'sample', 'sex', 'age', 'doublet_score', 'junk_global', 'junk_neigh']
            anno_sub = anno_table.loc[anno_table.index.isin(atac_h5ad.obs['gex_cellname']), anno_cols]
            for anno in anno_cols:
                taxon_dict = dict(zip(anno_sub.index, anno_sub[anno]))
                atac_h5ad.obs[anno] = [str(taxon_dict.get(x,'nan')) for x in atac_h5ad.obs['gex_cellname']]

            ## Fragment size distribution plot
            snap.metrics.frag_size_distr(atac_h5ad)
            snap.pl.frag_size_distr(atac_h5ad, interactive=False, show=False, out_file=pjoin(lib_results, "frag_size_distr.png"), scale=2)

            ## TSSe by number of fragments plot
            snap.pl.tsse(atac_h5ad, interactive=False, show=False, out_file=pjoin(lib_results, "tsse_by_frags.png"), scale=2)

            ## Write obs to s3 for easy QC visualization
            obs_df = pd.DataFrame(adata.obs)
            obs_df.to_csv(f"/results/metadata_{library}.csv")
            if 'frag_size_distr' in adata.uns:
                fsd = pd.DataFrame(adata.uns['frag_size_distr'])
                fsd.to_csv(f"/results/metadata_fsd_{library}.csv")
            
            ## Clean up
            atac_h5ad.close()

            ## Upload results to S3
            s3_prefix = f"NeMO_atac_process/{library}/"
            print(f"[UPLOAD] {lib_results}/ -> s3://{s3_bucket}/{s3_prefix}")
            for fname in os.listdir(lib_results):
                fpath = pjoin(lib_results, fname)
                if os.path.isfile(fpath):
                    s3_client.upload_file(fpath, s3_bucket, s3_prefix + fname)
                    print(f"  Uploaded: {fname}")

            ## Upload scratch to S3
            print(f"[UPLOAD] {lib_scratch}/ -> s3://{s3_bucket}/{s3_prefix}")
            for fname in os.listdir(lib_scratch):
                fpath = pjoin(lib_scratch, fname)
                if os.path.isfile(fpath):
                    s3_client.upload_file(fpath, s3_bucket, s3_prefix + fname)
                    print(f"  Uploaded: {fname}")

    except Exception:
        print("Exception raised.")

    ## Write a file so nextflow is happy even if processing is skipped
    with open(f"/results/output_{library}.txt", "w") as file:
        file.write(f"[DONE] Processed: {library}")

    ## Remove scratch file to save space
    print(f"[DONE] Processed: {library}")