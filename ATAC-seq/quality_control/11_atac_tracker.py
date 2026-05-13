import boto3
import pandas as pd

s3 = boto3.client("s3")

bucket = "hmba-human-wg-802451596237-us-west-2"
prefix = "NeMO_atac_process/"

paginator = s3.get_paginator("list_objects_v2")
h5ad_files = []
for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
    for obj in page.get("Contents", []):
        key = obj["Key"]
        if key.endswith(".h5ad"):
            h5ad_files.append(key)

records = []
for key in sorted(h5ad_files):
    s3_path = f"s3://{bucket}/{key}"
    # library_id is the first directory after the prefix, e.g. "960_B03"
    library_id = key.replace(prefix, "").split("/")[0]
    records.append({"library_id": library_id, "s3_path": s3_path})

df = pd.DataFrame(records)

## Save each library to a csv for parallel processing on code ocean.
for library_id, group in df.groupby("library_id"):
    group.to_csv(f"../results/{library_id}.csv", index=False)
    print(f"Saved ../results/{library_id}.csv")
