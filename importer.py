import os
import gzip
import argparse
from dotenv import load_dotenv
from database.handlers import get_database_handler
from pdb_import.db_importer import import_pdb_to_db
from database.init_db import init_db
from typing import Dict, Any

from concurrent.futures import ProcessPoolExecutor, as_completed


def read_pdb_file(filename: str, file_path: str) -> str:
    if filename.endswith(".pdb"):
        with open(file_path, "r") as f:
            pdb_content = f.read()
    elif filename.endswith(".gz"):
        with gzip.open(file_path, "rt") as f:
            pdb_content = f.read()
    else:
        raise ValueError(f"Invalid file extension: {filename}")
    return pdb_content


def process_file(file_path: str, db_params: Dict[str, Any], db_type: str, enable_rdkit: bool) -> None:
    # Create a new database handler for this process
    db_handler = get_database_handler(db_type, db_params)
    
    filename = os.path.basename(file_path)
    pdb_content = read_pdb_file(filename, file_path)
    pdb_identifier = os.path.splitext(filename)[0]  # Use filename without extension as pdb_identifier
    try:
        import_pdb_to_db(pdb_content, pdb_identifier, db_handler, enable_rdkit)
    finally:
        db_handler.disconnect()


def import_pdb_files(folder_path: str, db_params: Dict[str, Any], db_type: str, enable_rdkit: bool) -> None:
    fp_list = []
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        if filename.endswith(".pdb") or filename.endswith(".gz"):
            fp_list.append(file_path)

    with ProcessPoolExecutor(max_workers=30) as executor:
        futures = [
            executor.submit(process_file, file_path, db_params, db_type, enable_rdkit)
            for file_path in fp_list
        ]
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
    
    # Enable rdkit ( smarts search ) # TODO SMARTS search is not implemented yet
    parser.add_argument(
        "--enable_rdkit",
        action="store_true",
        help="Enable rdkit ( smarts search )",
    )

    # Add database type argument
    parser.add_argument(
        "--dbtype",
        type=str,
        default="postgresql",
        choices=["postgresql", "mysql"],
        help="Type of database to use (postgresql or mysql)",
    )

    args = parser.parse_args()

    # Load environment variables from database.env
    load_dotenv("database.env")

    # Set up the database connection parameters
    if args.dbtype == "postgresql":
        db_params = {
            "dbname":   os.getenv("PG_DB_NAME"),
            "user":     os.getenv("PG_DB_USER"),
            "password": os.getenv("PG_DB_PASSWORD"),
            "host":     os.getenv("PG_DB_HOST", "localhost"),
            "port":     os.getenv("PG_DB_PORT", "5432"),
        }
    elif args.dbtype == "mysql":
        db_params = {
            "dbname":    os.getenv("MY_DB_NAME"),
            "user":      os.getenv("MY_DB_USER"),
            "password":  os.getenv("MY_DB_PASSWORD"),
            "host":      os.getenv("MY_DB_HOST", "localhost"),
            "port":      os.getenv("MY_DB_PORT", "3306"),
        }
    else:
        raise ValueError(f"Invalid database type: {args.dbtype}")



    # Create database handler for main process
    db_handler = get_database_handler(args.dbtype, db_params)

    try:
        # Initialize the database
        init_db(db_handler, args.enable_rdkit)

        # IMPORT mode
        if args.import_pdb:
            if not args.pdb_folder:
                parser.error("--pdb_folder is required when using --import_pdb")
            # Import PDB files from the specified folder
            import_pdb_files(args.pdb_folder, db_params, args.dbtype, args.enable_rdkit)


    finally:
        db_handler.disconnect()


if __name__ == "__main__":
    main()
