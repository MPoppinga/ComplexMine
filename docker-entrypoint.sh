#!/bin/bash
set -e

# Create necessary directories
mkdir -p /app/data/af_db

# Check if the ready flag exists
if [ -f /app/data/af_db/ready ]; then
    echo "Ready flag found in data/af_db folder. Skipping download and import."
    DOWNLOAD_DATA="false"
    IMPORT_DATA="false"
fi

echo "DOWNLOAD_DATA: $DOWNLOAD_DATA"
echo "IMPORT_DATA: $IMPORT_DATA"

# Check if we need to download and import data
if [ "$DOWNLOAD_DATA" = "true" ]; then
    echo "Checking for AlphaFold human dataset..."
    
    # Download the dataset if it doesn't exist
    if [ ! -f /app/data/af_db/UP000005640_9606_HUMAN_v4.tar ]; then
        echo "Downloading AlphaFold human dataset..."
        cd /app/data/af_db
        curl -L -C - -O https://ftp.ebi.ac.uk/pub/databases/alphafold/latest/UP000005640_9606_HUMAN_v4.tar \
            --retry 3 \
            --retry-delay 5 \
            --connect-timeout 30 \
            --progress-bar
        cd /app
    else
        echo "AlphaFold dataset archive already exists, skipping download."
    fi
    
    # Extract PDB files if needed
    if [ ! -d /app/data/af_db/AF-* ]; then
        echo "Extracting PDB files from archive..."
        cd /app/data/af_db
        tar -xvf UP000005640_9606_HUMAN_v4.tar --wildcards '*.pdb.gz'
        cd /app
        echo "AlphaFold database extracted"
    else
        echo "PDB files already extracted, skipping extraction."
    fi
fi

if [ "$IMPORT_DATA" = "true" ]; then
    echo "Importing AlphaFold human dataset..."
    python importer.py --import_pdb --pdb_folder="/app/data/af_db" --dbtype="postgresql"
    echo "Import completed"
fi

# Create a ready flag to indicate data has been processed
if [ "$DOWNLOAD_DATA" = "true" ] || [ "$IMPORT_DATA" = "true" ]; then
    echo "Creating ready flag to skip future downloads and imports"
    touch /app/data/af_db/ready
fi


# Start the application
echo "Starting ComplexMine application..."
exec "$@"