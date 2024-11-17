#!/bin/sh

mkdir -p /scratch/poppinga/af_db_swissprot
cd /scratch/poppinga/af_db_swissprot
curl -L -O https://ftp.ebi.ac.uk/pub/databases/alphafold/latest/swissprot_pdb_v4.tar \
    --retry 3 \
    --retry-delay 5 \
    --connect-timeout 30 \
    --progress-bar \
    --continue

tar -xvf swissprot_pdb_v4.tar --wildcards '*.pdb.gz'
rm -rf swissprot_pdb_v4.tar

echo "AlphaFold database downloaded and unzipped"