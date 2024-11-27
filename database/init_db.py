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
        
        # Analyze tables
        if isinstance(db_handler, PostgresHandler):
            cur.execute("ANALYZE complex_data;")
            cur.execute("ANALYZE data_points;")
        elif isinstance(db_handler, MySQLHandler):
            cur.execute("ANALYZE TABLE data_points PERSISTENT FOR ALL;")
            cur.execute("ANALYZE TABLE complex_data PERSISTENT FOR ALL;")

    conn.commit()


