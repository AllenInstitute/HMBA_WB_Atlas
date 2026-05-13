import os
import pandas as pd
from os.path import join as pjoin
import snapatac2 as snap
import pybedtools

scratch_dir = "/root/capsule/scratch"
groupby = 'subclass'

## Genome handling
genome_path = "/data/DNA-modeling/aibs-octo-dnaseq-modeling/genomes/human"
chr_sizes = pd.read_csv(pjoin(genome_path, 'star/chrNameLength.txt'), sep='\t', header=None)
chr_sizes_dict = dict(zip(chr_sizes[0], chr_sizes[1]))
fasta_path = pjoin(genome_path, 'fasta/genome.fa') if os.path.exists(pjoin(genome_path, 'fasta/genome.fa')) else pjoin(genome_path, 'fasta/genome.fa.gz')
gtf_path = pjoin(genome_path, 'genes/genes.gtf') if os.path.exists(pjoin(genome_path, 'genes/genes.gtf')) else pjoin(genome_path, 'genes/genes.gtf.gz')

genome = snap.genome.Genome(fasta=fasta_path,
                            annotation=gtf_path,
                            chrom_sizes=chr_sizes_dict)

## Load concatenated dataset
file_path = pjoin(scratch_dir, "concatenated.h5ads")
data = snap.read_dataset(file_path, mode='r+')
data.obs[groupby] = data.adatas.obs[groupby]

## bigwig output directory
out_dir = pjoin(scratch_dir, f'{groupby}_bigwig_TSSnorm')
os.makedirs(out_dir, exist_ok=True)

## Build TSS windows for normalization
gtf = pybedtools.BedTool(genome.annotation)
transcripts = gtf.filter(lambda x: x[2] == "transcript")

def tss_window(feature):
    if feature.strand == "+":
        tss = feature.start
        start = max(tss - 100, 0)
        end = tss + 101
    else:
        tss = feature.end
        start = max(tss - 101, 0)
        end = tss + 100
    gene_id = feature.attrs.get("gene_id", "NA")
    return (feature.chrom, start, end, gene_id, 0, feature.strand)

tss_windows = [tss_window(f) for f in transcripts]
tss_df = pd.DataFrame(tss_windows, columns=["chrom", "start", "end", "gene_id", "score", "strand"])
tss_df = tss_df.drop_duplicates()
tss_list = tss_df.apply(lambda row: f"{row['chrom']}:{row['start']}-{row['end']}", axis=1).tolist()

## Export bigwigs by subclass with TSS normalization
snap.ex.export_coverage(data, groupby=groupby, out_dir=out_dir, normalization='CPM', bin_size=10, counting_strategy='insertion', include_for_norm=tss_list)

print(f"[DONE] Exported bigwigs by {groupby} → {out_dir}")
data.close()