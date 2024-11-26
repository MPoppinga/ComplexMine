from typing import Any
from database.handlers import DatabaseHandler, PostgresHandler, MySQLHandler


def init_db(db_handler: DatabaseHandler, enable_rdkit: bool = False) -> None:
    conn = db_handler.get_connection()
    with conn.cursor() as cur:
        if enable_rdkit and isinstance(db_handler, PostgresHandler):
            # Enable RDKit extension (PostgreSQL only)
            cur.execute("CREATE EXTENSION IF NOT EXISTS rdkit;")

            # Create complex_data table with RDKit column
            cur.execute("""
                CREATE TABLE IF NOT EXISTS complex_data (
                    complex_data_id SERIAL PRIMARY KEY,
                    pdb_id TEXT UNIQUE NOT NULL,
                    m MOL NULL
                );
            """)

            cur.execute("""CREATE INDEX IF NOT EXISTS idx_complex_data_mol ON complex_data USING GIST (m);""")
        else:
            # Create complex_data table without RDKit
            if isinstance(db_handler, MySQLHandler):
                # MySQL syntax
                cur.execute("""CREATE TABLE IF NOT EXISTS complex_data (
                    complex_data_id INT AUTO_INCREMENT PRIMARY KEY,
                    pdb_id VARCHAR(255) UNIQUE NOT NULL,
                    m LONGBLOB NULL
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;""")
            else:
                # PostgreSQL syntax
                cur.execute("""CREATE TABLE IF NOT EXISTS complex_data (
                    complex_data_id SERIAL PRIMARY KEY,
                    pdb_id TEXT UNIQUE NOT NULL,
                    m BYTEA NULL
                );""")

        # Create data_points table with reference to complex_data
        if isinstance(db_handler, MySQLHandler):
            # MySQL syntax
            cur.execute("""
                CREATE TABLE IF NOT EXISTS data_points (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    complex_data_id INT NOT NULL,
                    element SMALLINT NOT NULL,
                    type VARCHAR(255) NOT NULL,
                    origin VARCHAR(255) NOT NULL,
                    group_name VARCHAR(255) NOT NULL,
                    x FLOAT NOT NULL,
                    y FLOAT NOT NULL,
                    z FLOAT NOT NULL,
                    FOREIGN KEY (complex_data_id) REFERENCES complex_data(complex_data_id)
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
            """)
        else:
            # PostgreSQL syntax
            cur.execute("""
                CREATE TABLE IF NOT EXISTS data_points (
                    id SERIAL PRIMARY KEY,
                    complex_data_id INTEGER NOT NULL,
                    element SMALLINT NOT NULL,
                    type TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    x REAL NOT NULL,
                    y REAL NOT NULL,
                    z REAL NOT NULL,
                    FOREIGN KEY (complex_data_id) REFERENCES complex_data(complex_data_id)
                );
            """)

        # Create indexes (syntax is the same for both)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_data_points_complex_data_id ON data_points (complex_data_id);")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS data_points_complex_data_id_idx ON data_points (complex_data_id, element, origin);"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_complex_data_pdb_id ON complex_data (pdb_id);")

    conn.commit()


def create_postgis_table(db_handler: DatabaseHandler) -> None:
    if not isinstance(db_handler, PostgresHandler):
        raise ValueError("PostGIS tables can only be created with PostgreSQL")
        
    conn = db_handler.get_connection()
    with conn.cursor() as cur:
        # Enable PostGIS extension
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
        cur.execute("CREATE EXTENSION IF NOT EXISTS btree_gist;")

        print("Creating data_points_postgis")

        # Create data_points_postgis table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS data_points_postgis (
                id SERIAL PRIMARY KEY,
                complex_data_id INTEGER NOT NULL,
                element SMALLINT NOT NULL,
                type TEXT NOT NULL,
                origin TEXT NOT NULL,
                group_name TEXT NOT NULL,
                geom GEOMETRY(POINTZ, 0) NOT NULL,
                FOREIGN KEY (complex_data_id) REFERENCES complex_data(complex_data_id)
            );
        """)

        print("Populating data_points_postgis")

        # Populate data_points_postgis from data_points
        cur.execute("""
            INSERT INTO data_points_postgis (complex_data_id, element, type, origin, group_name, geom)
            SELECT complex_data_id, element, type, origin, group_name, ST_MakePoint(x, y, z)
            FROM data_points
            ON CONFLICT DO NOTHING;
        """)

        print("Creating index on complex_data_id for data_points_postgis")
        # Create index on complex_data_id for data_points_postgis
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_data_points_postgis_complex_data_id ON data_points_postgis (complex_data_id);"
        )

        print("Creating spatial index on geom column")
        # Create spatial index on geom column
        cur.execute("CREATE INDEX IF NOT EXISTS idx_data_points_postgis_geom ON data_points_postgis USING GIST (geom);")

        print("Creating index on idx_data_points_postgiss_full for data_points_postgis")
        # Create index on complex_data_id for data_points_postgis
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_data_points_postgiss_full ON data_points_postgis (complex_data_id, geom, element, origin, id);"
        )

    conn.commit()
