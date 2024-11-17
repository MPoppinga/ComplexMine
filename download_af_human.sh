#!/bin/sh

mkdir -p data/af_db
cd data/af_db
curl -L -O https://ftp.ebi.ac.uk/pub/databases/alphafold/latest/UP000005640_9606_HUMAN_v4.tar \
    --retry 3 \
    --retry-delay 5 \
    --connect-timeout 30 \
    --progress-bar
tar -xvf UP000005640_9606_HUMAN_v4.tar --wildcards '*.pdb.gz'
rm -rf UP000005640_9606_HUMAN_v4.tar

echo "AlphaFold database downloaded and unzipped"