from Bio import PDB
import warnings
import io
from typing import Dict, Any, List
from database.handlers import DatabaseHandler, PostgresHandler


class InvalidPDBError(Exception):
    pass


def convert_to_native_types(data_points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert numpy types to native Python types"""
    converted_points = []
    for point in data_points:
        converted_point = {
            "element": int(point["element"]),
            "type": str(point["type"]),
            "origin": str(point["origin"]),
            "group_name": str(point["group_name"]),
            "x": float(point["x"]),
            "y": float(point["y"]),
            "z": float(point["z"])
        }
        converted_points.append(converted_point)
    return converted_points


def import_pdb_to_db(pdb_content: str, pdb_identifier: str, db_handler: DatabaseHandler, enable_rdkit: bool) -> None:
    # Parse PDB content and extract interaction points
    data_points: List[Dict[str, Any]] = parse_pdb(pdb_content)
    
    # Convert numpy types to native Python types
    data_points = convert_to_native_types(data_points)

    conn = db_handler.get_connection()
    with conn.cursor() as cur:
        # Check if complex_data with pdb_id exists, if so get id, if not insert and get id
        cur.execute("SELECT complex_data_id FROM complex_data WHERE pdb_id = %s", (pdb_identifier,))

        complex_data_id = cur.fetchone()
        if complex_data_id is None:
            cur.execute("INSERT INTO complex_data (pdb_id) VALUES (%s) RETURNING complex_data_id", (pdb_identifier,))
            c = cur.fetchone()
            if c is not None:
                complex_data_id = c[0]
            else:
                raise Exception("Failed to insert complex data")
            
            # Also calculate and insert smiles
            if enable_rdkit:
                from rdkit import Chem
                mol = Chem.MolFromPDBBlock(pdb_content)
                if mol is not None:
                    if isinstance(db_handler, PostgresHandler):
                        cur.execute(
                            "UPDATE complex_data SET m = mol_from_pkl(%s) WHERE complex_data_id = %s", 
                            (mol.ToBinary(), complex_data_id)
                        )
                    else:
                        # For MySQL, store as binary
                        cur.execute(
                            "UPDATE complex_data SET m = %s WHERE complex_data_id = %s",
                            (mol.ToBinary(), complex_data_id)
                        )

            for point in data_points:
                # Insert data_points
                cur.execute(
                    """
                INSERT INTO data_points 
                (complex_data_id, element, type, origin, group_name, x, y, z)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                    (
                        complex_data_id,
                        point["element"],
                        point["type"],
                        point["origin"],
                        point["group_name"],
                        point["x"],
                        point["y"],
                        point["z"],
                    ),
                )
            conn.commit()
            print(f"Imported {pdb_identifier} to database")


def parse_pdb(pdb_content):
    interaction_points = []
    parser = PDB.PDBParser(QUIET=True)  # type: ignore
    try:
        structure = parser.get_structure("structure", io.StringIO(pdb_content))
        if structure is None:
            raise InvalidPDBError("Failed to parse PDB file")
    except Exception as e:
        raise InvalidPDBError(f"Error parsing PDB file: {str(e)}")

    for model in structure:
        for chain in model:
            for residue in chain:
                for atom in residue:
                    data_point = {
                        "pocket_key": None,  # Assign appropriate value
                        "element": element_to_int(atom.element),
                        "type": atom.name,
                        "origin": residue.resname,
                        "group_name": chain.id,
                        "x": atom.coord[0],
                        "y": atom.coord[1],
                        "z": atom.coord[2],
                    }
                    interaction_points.append(data_point)

    if not interaction_points:
        raise InvalidPDBError("No valid interaction points found in the PDB file")

    return interaction_points


def element_to_int(element_symbol):
    element_mapping = {
                        "H": 1,  
                        "C": 6,  
                        "N": 7,  
                        "O": 8,  
                        "P": 15, 
                        "S": 16, 
                        
                        "Se": 34,
                        "I": 53, 
                        "Fe": 26,
                        "Zn": 30,
                        "Cu": 29,
                        "Mg": 12,
                        "Mn": 25,
                        "Mo": 42,
                        "Co": 27,
                        "Ca": 20,    

                        "F": 9,  
                        "Cl": 17,
                        "Br": 35,    

                        "Na": 11,
                        "K": 19, 
                        "V": 23, 
                        "Ni": 28 
                    }
    return element_mapping.get(element_symbol, 0)


# TODO: Implement a method to calculate surface area without relying on DSSP
warnings.warn("Surface area calculations are not implemented yet.")
