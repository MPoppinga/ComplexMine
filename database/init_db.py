from typing import Any
import psycopg


def init_db(conn: psycopg.Connection[Any], enable_rdkit: bool = False) -> None:
    with conn.cursor() as cur:
        if enable_rdkit:
            # Enable RDKit extension
            cur.execute("CREATE EXTENSION IF NOT EXISTS rdkit;")

            # Create complex_data table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS complex_data (
                    complex_data_id SERIAL PRIMARY KEY,
                    pdb_id TEXT UNIQUE NOT NULL,
                    m MOL NULL
                );
            """)

            cur.execute("""CREATE INDEX IF NOT EXISTS idx_complex_data_mol ON complex_data USING GIST (m);""")
        else:
            cur.execute("""CREATE TABLE IF NOT EXISTS complex_data (
                complex_data_id SERIAL PRIMARY KEY,
                pdb_id TEXT UNIQUE NOT NULL,
                m STRING NULL
            );""")

        # Create data_points table with reference to complex_data
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
                FOREIGN KEY (complex_data_id) REFERENCES complex_data(id)
            );
        """)

        # Create index on complex_data_id for faster queries
        cur.execute("CREATE INDEX IF NOT EXISTS idx_data_points_complex_data_id ON data_points (complex_data_id);")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS data_points_complex_data_id_idx ON data_points (complex_data_id, element, origin);"
        )

        # Create index on pdb_id in complex_data for faster lookups
        cur.execute("CREATE INDEX IF NOT EXISTS idx_complex_data_pdb_id ON complex_data (pdb_id);")

    conn.commit()


def create_postgis_table(conn: psycopg.Connection[Any]) -> None:
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
                FOREIGN KEY (complex_data_id) REFERENCES complex_data(id)
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
