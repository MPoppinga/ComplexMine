import os
import gzip
import argparse
from dotenv import load_dotenv
from database.handlers import get_database_handler
from pdb_import.db_importer import import_pdb_to_db, check_pdb_exists
from database.init_db import init_db
from typing import Dict, Any, List, Tuple

from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm


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


def process_file(file_path: str, db_params: Dict[str, Any], db_type: str, enable_rdkit: bool, skip_existing: bool = True) -> Tuple[str, bool]:
    """
    Process a single PDB file.
    Returns: (pdb_identifier, was_imported)
    """
    # Create a new database handler for this process
    db_handler = get_database_handler(db_type, db_params)
    
    filename = os.path.basename(file_path)
    pdb_identifier = os.path.splitext(filename)[0]  # Use filename without extension as pdb_identifier
    
    try:
        # Check if PDB already exists if skip_existing is enabled
        if skip_existing and check_pdb_exists(pdb_identifier, db_handler):
            return (pdb_identifier, False)  # Not imported, already exists
        
        # Read and import the PDB file
        pdb_content = read_pdb_file(filename, file_path)
        import_pdb_to_db(pdb_content, pdb_identifier, db_handler, enable_rdkit)
        return (pdb_identifier, True)  # Successfully imported
    finally:
        db_handler.disconnect()


def import_pdb_files(folder_path: str, db_params: Dict[str, Any], db_type: str, enable_rdkit: bool, skip_existing: bool = True, max_workers: int = 30) -> None:
    # Collect all PDB files
    fp_list = []
    print(f"Scanning folder: {folder_path}")
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        if filename.endswith(".pdb") or filename.endswith(".gz"):
            fp_list.append(file_path)
    
    print(f"Found {len(fp_list)} PDB files to process")
    
    if not fp_list:
        print("No PDB files found!")
        return
    
    # Statistics
    imported_count = 0
    skipped_count = 0
    error_count = 0
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Submit all jobs
        futures = [
            executor.submit(process_file, file_path, db_params, db_type, enable_rdkit, skip_existing)
            for file_path in fp_list
        ]
        
        # Progress bar for completed futures
        with tqdm(total=len(futures), desc="Processing PDB files", unit="file") as pbar:
            for future in as_completed(futures):
                try:
                    pdb_identifier, was_imported = future.result()
                    if was_imported:
                        imported_count += 1
                        pbar.set_postfix(imported=imported_count, skipped=skipped_count, errors=error_count)
                    else:
                        skipped_count += 1
                        if skip_existing:
                            pbar.set_postfix(imported=imported_count, skipped=skipped_count, errors=error_count)
                except Exception as e:
                    error_count += 1
                    pbar.set_postfix(imported=imported_count, skipped=skipped_count, errors=error_count)
                    print(f"\nError processing file: {e}")
                finally:
                    pbar.update(1)
    
    # Final statistics
    print(f"\nImport completed!")
    print(f"  Files imported: {imported_count}")
    if skip_existing:
        print(f"  Files skipped (already exist): {skipped_count}")
    print(f"  Errors: {error_count}")
    print(f"  Total files processed: {len(fp_list)}")


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

    # Skip existing data
    parser.add_argument(
        "--no_skip",
        action="store_true",
        help="Don't skip existing PDB entries (re-import them)",
    )

    # Max workers for parallel processing
    parser.add_argument(
        "--max_workers",
        type=int,
        default=30,
        help="Maximum number of worker processes (default: 30)",
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
            skip_existing = not args.no_skip  # If --no_skip is provided, don't skip existing
            import_pdb_files(args.pdb_folder, db_params, args.dbtype, args.enable_rdkit, skip_existing, args.max_workers)


    finally:
        db_handler.disconnect()


if __name__ == "__main__":
    main()
