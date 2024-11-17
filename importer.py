import os
import gzip
import argparse
from dotenv import load_dotenv
import psycopg
from pdb_import.db_importer import import_pdb_to_db
from database.init_db import init_db, create_postgis_table

from concurrent.futures import ProcessPoolExecutor, as_completed


def read_pdb_file(filename, file_path):
    if filename.endswith(".pdb"):
        with open(file_path, "r") as f:
            pdb_content = f.read()
    elif filename.endswith(".gz"):
        with gzip.open(file_path, "rt") as f:
            pdb_content = f.read()
    else:
        raise ValueError(f"Invalid file extension: {filename}")
    return pdb_content


def process_file(file_path, db_params, enable_rdkit):
    filename = os.path.basename(file_path)
    pdb_content = read_pdb_file(filename, file_path)
    pdb_identifier = os.path.splitext(filename)[0]  # Use filename without extension as pdb_identifier
    import_pdb_to_db(pdb_content, pdb_identifier, db_params, enable_rdkit)


def import_pdb_files(folder_path, db_params, enable_rdkit):
    fp_list = []
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        if filename.endswith(".pdb") or filename.endswith(".gz"):
            fp_list.append(file_path)

    with ProcessPoolExecutor(max_workers=30) as executor:
        futures = [executor.submit(process_file, file_path, db_params, enable_rdkit) for file_path in fp_list]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"An error occurred: {e}")


def main():
    parser = argparse.ArgumentParser(description="Geometric search on PDB files")

    # IMPORT mode
    parser.add_argument("--import_pdb", action="store_true", help="Import PDB files into the database")
    parser.add_argument("--pdb_folder", type=str, help="Path to the folder containing PDB files")

    # CREATE POSTGIS
    parser.add_argument(
        "--create_postgis",
        action="store_true",
        help="Create PostGIS table from existing data",
    )
    
    # Enable rdkit ( smarts search ) # TODO SMARTS search is not implemented yet
    parser.add_argument(
        "--enable_rdkit",
        action="store_true",
        help="Enable rdkit ( smarts search )",
    )

    args = parser.parse_args()

    # Load environment variables from database.env
    load_dotenv("database.env")

    # Set up the database connection parameters
    db_params = {
        "dbname": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "host": os.getenv("DB_HOST", "localhost"),
        "port": os.getenv("DB_PORT", "5432"),
    }

    with psycopg.connect(**db_params) as conn:
        # Initialize the database
        init_db(conn, args.enable_rdkit)

    # IMPORT mode
    if args.import_pdb:
        if not args.pdb_folder:
            parser.error("--pdb_folder is required when using --import_pdb")
        # Import PDB files from the specified folder
        import_pdb_files(args.pdb_folder, db_params, args.enable_rdkit)

    # CREATE POSTGIS mode
    if args.create_postgis:
        with psycopg.connect(**db_params) as conn:
            create_postgis_table(conn)
        print("PostGIS table created successfully")



if __name__ == "__main__":
    main()
