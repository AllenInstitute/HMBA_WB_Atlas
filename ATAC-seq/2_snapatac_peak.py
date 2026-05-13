import os
import pandas as pd
import numpy as np
from os.path import join as pjoin
import snapatac2 as snap

scratch_dir = "/root/capsule/scratch"
groupby = 'subclass'

## Load concatenated dataset
file_path = pjoin(scratch_dir, "concatenated.h5ads")
data = snap.read_dataset(file_path, mode='r+')

## Genome handling
genome_path = "/data/DNA-modeling/aibs-octo-dnaseq-modeling/genomes/human"
chr_sizes = pd.read_csv(pjoin(genome_path, 'star/chrNameLength.txt'), sep='\t', header=None)
chr_sizes_dict = dict(zip(chr_sizes[0], chr_sizes[1]))
fasta_path = pjoin(genome_path, 'fasta/genome.fa') if os.path.exists(pjoin(genome_path, 'fasta/genome.fa')) else pjoin(genome_path, 'fasta/genome.fa.gz')
gtf_path = pjoin(genome_path, 'genes/genes.gtf') if os.path.exists(pjoin(genome_path, 'genes/genes.gtf')) else pjoin(genome_path, 'genes/genes.gtf.gz')

genome = snap.genome.Genome(fasta=fasta_path,
                            annotation=gtf_path,
                            chrom_sizes=chr_sizes_dict)

## Grouping
data.obs[groupby] = data.adatas.obs[groupby]

## Call peaks by subclass
snap.tl.macs3(data, groupby=groupby, n_jobs=24)

## Export and merge peaks
peak_tables = {}
for k in data.uns['macs3'].keys():
    if 'dict' in str(type(data.uns['macs3'][k])):
        peak_tables[k] = list(data.uns['macs3'][k].values())[0]
    else:
        peak_tables[k] = data.uns['macs3'][k]

df = snap.tl.merge_peaks(peak_tables,
                         dict(zip(data.uns['reference_sequences']['reference_seq_name'],
                                  data.uns['reference_sequences']['reference_seq_length'])))

## Save merged peaks as bed file
merged_df = pd.DataFrame(list(df['Peaks'].to_pandas().str.split(r'\:|\-')), columns=['chrom', 'start', 'end'])
merged_df.to_csv(pjoin(scratch_dir, "merged_peaks.bed"), sep='\t', header=None, index=False)

print(f"[DONE] Called and merged peaks by {groupby}")
data.close()