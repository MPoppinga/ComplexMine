import argparse
import json
import logging
import os
import time

import partitioncache.apply_cache
import partitioncache.cache_handler
import partitioncache.query_processor
import partitioncache.queue
import sqlglot
import sqlparse
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_cors import CORS
from psycopg import sql

from database.handlers import get_database_handler

USE_TMP_TABLE_FOR_PARTITIONCACHE_OVER_NUM_PARTITIONS = 100_000
PUSH_TO_QUEUE = True
TMP_JOIN_ALL = False  # TODO: Needs heuristic which is faster in which cases

# Add argument parser
parser = argparse.ArgumentParser(description="Run the Flask application with partition cache settings")
parser.add_argument("--cachetype", type=str, default="shelve", choices=["shelve", "redis", "rocksdb"], help="Type of partition cache to use (shelve or redis)")
parser.add_argument("--database_env", type=str, default="database.env", help="Path to the database.env file")
parser.add_argument("--dbtype", type=str, default="postgresql", choices=["postgresql", "mysql"], help="Type of database to use (postgresql or mysql)")
args = parser.parse_args()


# Load environment variables from database.env
load_dotenv(args.database_env)

app = Flask(__name__)
CORS(app)  # Enable Cross-Origin Resource Sharing

# Set up logging
logging.basicConfig(level=logging.DEBUG)

# Database connection parameters
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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/get_pdb_identifiers")
def get_pdb_identifiers():
    search_term = request.args.get("search", "").strip().lower()
    if len(search_term) > 50:
        return jsonify({"error": "Search term too long"}), 400
    try:
        with get_database_handler(args.dbtype, db_params) as handler:
            if search_term:
                _, pdb_data = handler.execute_query(
                    sql.SQL("""
                    SELECT pdb_id
                    FROM complex_data
                    WHERE pdb_id ILIKE {}
                    ORDER BY pdb_id
                    LIMIT 25
                        """)
                    .format(sql.Literal("%" + search_term + "%"))
                    .as_string()
                )
            else:
                _, pdb_data = handler.execute_query(
                    sql.SQL("""
                    SELECT pdb_id
                    FROM complex_data
                    ORDER BY pdb_id
                    LIMIT 25
                        """).as_string()
                )
            pdb_data = [{"id": row[0]} for row in pdb_data]
            print(pdb_data)
        
        if not pdb_data:
            app.logger.warning("No PDB identifiers found matching the search criteria.")
        else:
            app.logger.info(f"Retrieved {len(pdb_data)} PDB identifiers")

        return jsonify(pdb_data)
    except Exception as e:
        app.logger.error(f"Error retrieving PDB identifiers: {str(e)}")
        return jsonify({"error": "Failed to retrieve PDB identifiers"}), 500


@app.route("/get_molecule/<pdb_id>")
def get_molecule(pdb_id):
    try:
        with get_database_handler(args.dbtype, db_params) as handler:
            _, atoms = handler.execute_query(
                sql.SQL("""
                SELECT id, element, type, origin, x, y, z
                FROM data_points
                WHERE data_points.complex_data_id = (
                    SELECT complex_data_id FROM complex_data WHERE pdb_id = {}
                )
                """)
                .format(sql.Literal(pdb_id))
                .as_string()
            )
            if not atoms:
                app.logger.warning(f"No atoms found for PDB ID: {pdb_id}")
                return jsonify({"error": "No atoms found"}), 404

            atom_list = [
                {
                    "id": atom[0],
                    "element": atom[1],
                    "type": atom[2],
                    "origin": atom[3],
                    "x": atom[4],
                    "y": atom[5],
                    "z": atom[6],
                }
                for atom in atoms
            ]

            app.logger.info(f"Retrieved {len(atom_list)} atoms for PDB ID: {pdb_id}")
            return jsonify(atom_list)
    except Exception as e:
        app.logger.error(f"Error retrieving molecule for PDB ID {pdb_id}: {str(e)}")
        return jsonify({"error": f"Error retrieving molecule: {str(e)}"}), 500


def get_extended_search_query(selected_pairs) -> str:
    query = generate_search_query(selected_pairs, use_partition_cache=True).as_string()

    if args.dbtype == "mysql":
        # Parse and transpile the query from PostgreSQL to MySQL
        query_list = []
        for q in query.split(";"):
            qm = sqlglot.transpile(q, read="postgres", write="mysql")[0]
            query_list.append(qm)
        query = ";".join(query_list)

    return query


def generate_search_query(selected_pairs,  use_partition_cache=True) -> sql.Composed:
    if not use_partition_cache:
        # Build Extended query without partition cache
        query = generate_search_query_sql(selected_pairs, base_query=False)
        return query

    else:  # Using partition cache
        
        # Generate Base Query for searching in cache
        base_query = generate_search_query_sql(selected_pairs, base_query=True)

        if PUSH_TO_QUEUE:
            partitioncache.queue.push_to_queue(base_query.as_string())

        # Get Partition Keys for the base query from cache
        cachetype = args.cachetype
        partiton_key_set, num_total_build_hashes, num_used_hashes = partitioncache.apply_cache.get_partition_keys(
            base_query.as_string(), partitioncache.cache_handler.get_cache_handler(cachetype), partition_key="complex_data_id"
        )

        # Build Extended Query for application (e.g. LIMIT clause, PartitionList, PDB_ID id via comple_data table)

        query = generate_search_query_sql(selected_pairs, base_query=False, limit=0)

        ## ADD PARTITION CACHE QUERY TO ORIGINAL QUERY (Simple IN clause for smaller numbe roor TMP TABLE)
        if partiton_key_set is not None:
            query_str = query.as_string()

            if len(partiton_key_set) < USE_TMP_TABLE_FOR_PARTITIONCACHE_OVER_NUM_PARTITIONS:
                query_str = partitioncache.apply_cache.extend_query_with_partition_keys(
                    query_str, partiton_key_set, partition_key="complex_data_id", method="IN", p0_alias="cd"
                )

            else:
               
                if args.dbtype == "postgresql":
                    analyze_tmp_table = True
                else:
                    analyze_tmp_table = False
                    
                if TMP_JOIN_ALL:
                    alias = None
                else:
                    alias = "cd"

                query_str = partitioncache.apply_cache.extend_query_with_partition_keys(
                    query_str,
                        partiton_key_set,
                        partition_key="complex_data_id",
                        method="TMP_TABLE_JOIN",
                        p0_alias=alias,
                        analyze_tmp_table=analyze_tmp_table,
                    )


            app.logger.info(
                f"Created partition cache query with {num_used_hashes} used hashes out of {num_total_build_hashes} total, restricting it to {len(partiton_key_set)} partitions"
            )
        else:
            app.logger.info(
                f"Created partition cache query with {num_used_hashes} used hashes out of {num_total_build_hashes} total, but no partitions were found"
            )
            query_str = query.as_string()

        return sql.SQL(query_str) + sql.SQL(" LIMIT 500")  # type: ignore


def generate_search_query_sql(selected_pairs, base_query=False, limit=500) -> sql.Composed:
    atoms = {}
    distances = {}
    for pair in selected_pairs:
        for atom in [pair["atom1"], pair["atom2"]]:
            atoms[atom["matchid"]] = atom
        distances[(pair["atom1"]["matchid"], pair["atom2"]["matchid"])] = pair["distance"]

    num_points = len(atoms)

    if base_query:
        sql_query = sql.SQL("""
        SELECT p0.complex_data_id,
            {match_columns}
        FROM data_points p0""").format(
            match_columns=sql.SQL(", ").join(sql.SQL("{}.id AS match_{}").format(sql.Identifier(f"p{i}"), sql.Literal(i)) for i in atoms.keys())
        )
        join_table_alias = "p0"

    else:
        sql_query = sql.SQL("""
        SELECT cd.pdb_id,
            {match_columns}
        FROM complex_data cd""").format(
            match_columns=sql.SQL(", ").join(sql.SQL("{}.id AS match_{}").format(sql.Identifier(f"p{i}"), sql.Literal(i)) for i in atoms.keys())
        )
        join_table_alias = "cd"

    for i in range(1, num_points + 1):
        sql_query += sql.SQL(", data_points {0}").format(sql.Identifier(f"p{i}"))

    sql_query += sql.SQL(" WHERE ")

    conditions = []

    for i in range(1, num_points + 1):
        conditions.append(sql.SQL("{0}.complex_data_id = {1}.complex_data_id").format(sql.Identifier(f"p{i}"), sql.Identifier(join_table_alias)))

    for id, atom in atoms.items():
        ident = sql.Identifier(f"p{id}")
        if atom["element"] is not None:
            conditions.append(sql.SQL("{0}.element = {1}").format(ident, sql.Literal(atom["element"])))
        if atom["origin"] is not None:
            conditions.append(sql.SQL("{0}.origin = {1}").format(ident, sql.Literal(atom["origin"])))

    for (p1, p2), dist in distances.items():
        conditions.append(
            sql.SQL("""
        ABS(SQRT(
            POWER({0}.x - {1}.x, 2) +
            POWER({0}.y - {1}.y, 2) +
            POWER({0}.z - {1}.z, 2)
        ) - {2}) <= 0.1
        """).format(sql.Identifier(f"p{p1}"), sql.Identifier(f"p{p2}"), sql.Literal(dist))
        )

    sql_query += sql.SQL(" AND ").join(conditions)

    if not base_query and limit:
        # Add LIMIT clause to the query
        sql_query += sql.SQL(" LIMIT {0}").format(sql.Literal(limit))

    return sql_query



@app.route("/search", methods=["POST"])
def search():
    data = request.json
    if data is None:
        return jsonify({"error": "No data received"}), 400
    selected_pairs = data.get("selected_pairs", [])  # The pairs to search for
    skip_execution = data.get("skip_execution", False)  # Skip execution and return SQL query only to display while query will be executed in the background

    app.logger.info(f"Search request - skip_execution: {skip_execution}")
    app.logger.debug(f"Selected pairs: {selected_pairs}")

    if not selected_pairs:
        return jsonify({"error": "No pairs selected"}), 400

    try:
        sql_query = get_extended_search_query(selected_pairs)
        app.logger.debug(f"Generated SQL query: {sql_query}")
        if skip_execution:
            return jsonify({"sql_query": sqlparse.format(sql_query, reindent=True)})

        with get_database_handler(args.dbtype, db_params) as handler:
            
            app.logger.debug("Executing SQL query")            
            
            start_time = time.perf_counter()

            columns, query_result = handler.execute_query(sql_query)
            app.logger.debug("SQL query executed successfully")

            results = []
            for row in query_result:                
                matches = {col.split("_")[1]: int(row[i]) for i, col in enumerate(columns[1:], 1)}
                result = {"pdb_id": row[0], "matches": matches}
                results.append(result)

            limit_reached = len(results) == 500
            req_time = time.perf_counter() - start_time
            app.logger.info(f"Search completed. Found {len(results)} results in {req_time:.2f} seconds.")
            handler.disconnect()
            return jsonify(
                {
                    "sql_query": str(sql_query),
                    "results": results,
                    "limit_reached": limit_reached,
                }
            )
    except Exception as e:
        app.logger.error(f"Error executing search: {str(e)}", exc_info=True)
        return jsonify({"error": f"Error executing search: {str(e)}"}), 500


@app.route("/view_molecule/<pdb_id>")
def view_molecule(pdb_id):
    matches = request.args.get("matches", "{}")
    pairs = request.args.get("pairs", "[]")
    try:
        matches = json.loads(matches)
        pairs = json.loads(pairs)

        # Ensure matches is a dictionary of integers (matchNr: DB_ID)
        if not isinstance(matches, dict) or not all(isinstance(k, str) and isinstance(v, int) for k, v in matches.items()):
            raise ValueError("Invalid matches format")

        # Ensure pairs is a list of pairs of integers (MatchNrs)
        if not isinstance(pairs, list) or not all(isinstance(p, list) and len(p) == 2 and all(isinstance(m, int) for m in p) for p in pairs):
            raise ValueError("Invalid pairs format")

        # Create match_data as a list of [matchNr, dbId] pairs
        match_data = list(matches.items())

        app.logger.debug(f"Viewing molecule: {pdb_id}, Match Data: {match_data}, Pairs: {pairs}")
        return render_template("view_molecule.html", pdb_id=pdb_id, match_data=match_data, pairs=pairs)
    except Exception as e:
        app.logger.error(f"Error processing view_molecule for pdb_id {pdb_id}: {str(e)}")
        return redirect(url_for("error", message="An error occurred while processing the molecule view"))


@app.route("/error")
def error():
    message = request.args.get("message", "An unknown error occurred.")
    return render_template("error.html", message=message)


@app.route("/search_results")
def search_results():
    return render_template("search_results.html")


if __name__ == "__main__":
    app.run(debug=True)
