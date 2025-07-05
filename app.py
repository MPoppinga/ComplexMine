import argparse
import json
import logging
import os
import time

import partitioncache
import partitioncache.query_processor  # Still needed for generate_all_query_hash_pairs
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
        "dbname": os.getenv("PG_DB_NAME"),
        "user": os.getenv("PG_DB_USER"),
        "password": os.getenv("PG_DB_PASSWORD"),
        "host": os.getenv("PG_DB_HOST", "localhost"),
        "port": os.getenv("PG_DB_PORT", "5432"),
    }
elif args.dbtype == "mysql":
    db_params = {
        "dbname": os.getenv("MY_DB_NAME"),
        "user": os.getenv("MY_DB_USER"),
        "password": os.getenv("MY_DB_PASSWORD"),
        "host": os.getenv("MY_DB_HOST", "localhost"),
        "port": os.getenv("MY_DB_PORT", "3306"),
    }
else:
    raise ValueError(f"Invalid database type: {args.dbtype}")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/search_results.html")
def search_results():
    """Serve the search results page"""
    return render_template("search_results.html")


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


@app.route("/get_available_molecules")
def get_available_molecules():
    """Get list of available PDB IDs in the database (limited to 50 for performance)"""
    try:
        with get_database_handler(args.dbtype, db_params) as handler:
            _, results = handler.execute_query("SELECT DISTINCT pdb_id FROM complex_data ORDER BY pdb_id LIMIT 50")
            molecules = [row[0] for row in results]
            app.logger.info(f"Retrieved {len(molecules)} available molecules (limited to 50)")
            return jsonify(molecules)
    except Exception as e:
        app.logger.error(f"Error retrieving available molecules: {str(e)}")
        return jsonify({"error": f"Error retrieving molecules: {str(e)}"}), 500


def get_total_partition_count() -> int:
    """Get the total number of partitions (distinct complex_data_id values) in the database"""
    try:
        with get_database_handler(args.dbtype, db_params) as handler:
            _, result = handler.execute_query("SELECT COUNT(DISTINCT complex_data_id) FROM complex_data")
            total_partitions = result[0][0] if result else 0
            app.logger.debug(f"Total partitions in database: {total_partitions}")
            return total_partitions
    except Exception as e:
        app.logger.error(f"Error getting total partition count: {str(e)}")
        return 0


def get_extended_search_query(selected_pairs, auto_queue=False) -> tuple[str, dict]:
    query, cache_stats = generate_search_query(selected_pairs, use_partition_cache=True, auto_queue=auto_queue)
    query_str = query.as_string()

    if args.dbtype == "mysql":
        # Parse and transpile the query from PostgreSQL to MySQL
        query_list = []
        for q in query_str.split(";"):
            qm = sqlglot.transpile(q, read="postgres", write="mysql")[0]
            query_list.append(qm)
        query_str = ";".join(query_list)

    return query_str, cache_stats


def generate_search_query(selected_pairs, use_partition_cache=True, auto_queue=False) -> tuple[sql.Composed, dict]:
    if not use_partition_cache:
        # Build Extended query without partition cache
        query = generate_search_query_sql(selected_pairs, base_query=False)
        cache_stats = {"cache_enabled": False}
        return query, cache_stats

    else:  # Using partition cache
        # Generate Base Query for searching in cache
        base_query = generate_search_query_sql(selected_pairs, base_query=False)

        if auto_queue:
            partitioncache.push_to_original_query_queue(base_query.as_string(), partition_key="complex_data_id", partition_datatype="integer")

        # Get Partition Keys for the base query from cache
        cachetype = args.cachetype
        partiton_key_set, num_total_build_hashes, num_used_hashes = partitioncache.get_partition_keys(
            base_query.as_string(), partitioncache.get_cache_handler(cachetype), partition_key="complex_data_id", min_component_size=1
        )
        app.logger.info(f"DEBUG get_partition_keys: Used cache keys: {partiton_key_set}")
        app.logger.info(f"DEBUG base_query: {base_query.as_string()}")

        app.logger.info(
            f"DEBUG get_partition_keys: used_hashes={num_used_hashes}, total_hashes={num_total_build_hashes}, partitions={len(partiton_key_set) if partiton_key_set else 0}"
        )

        # Build Extended Query for application (e.g. LIMIT clause, PartitionList, PDB_ID id via comple_data table)

        query = generate_search_query_sql(selected_pairs, base_query=False, limit=0)

        ## ADD PARTITION CACHE QUERY TO ORIGINAL QUERY (Simple IN clause for smaller numbe roor TMP TABLE)
        if partiton_key_set is not None:
            query_str = query.as_string()

            if len(partiton_key_set) < USE_TMP_TABLE_FOR_PARTITIONCACHE_OVER_NUM_PARTITIONS:
                query_str = partitioncache.extend_query_with_partition_keys(
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

                query_str = partitioncache.extend_query_with_partition_keys(
                    query_str,
                    partiton_key_set,
                    partition_key="complex_data_id",
                    method="TMP_TABLE_JOIN",
                    p0_alias=alias,
                    analyze_tmp_table=analyze_tmp_table,
                )

            info = f"Created partition cache query with {num_used_hashes} used hashes out of {num_total_build_hashes} total, restricting it to {len(partiton_key_set)} partitions"

            app.logger.info(info)
        else:
            info = f"Created partition cache query with {num_used_hashes} used hashes out of {num_total_build_hashes} total, but no partitions were found"
            app.logger.info(info)
            query_str = query.as_string()

        # Get total partition count from database for accurate reduction calculation
        total_database_partitions = get_total_partition_count()

        # Prepare cache statistics
        partitions_found = len(partiton_key_set) if partiton_key_set else 0

        # Calculate search space reduction based on total database partitions
        if partitions_found > 0 and total_database_partitions > 0:
            search_space_reduction = f"{(partitions_found / total_database_partitions) * 100:.1f}%"
        else:
            search_space_reduction = "0.0%"

        cache_stats = {
            "cache_enabled": True,
            "cache_type": cachetype,
            "used_hashes": num_used_hashes,
            "total_hashes": num_total_build_hashes,
            "total_database_partitions": total_database_partitions,
            "partitions_found": partitions_found,
            "method": "TMP_TABLE_JOIN" if partiton_key_set and len(partiton_key_set) >= USE_TMP_TABLE_FOR_PARTITIONCACHE_OVER_NUM_PARTITIONS else "IN_CLAUSE",
            "search_space_reduction": search_space_reduction,
        }

        app.logger.info(
            f"DEBUG cache_stats: used_hashes={cache_stats['used_hashes']}, total_hashes={cache_stats['total_hashes']}, partitions_found={cache_stats['partitions_found']}"
        )

        return sql.SQL(query_str) + sql.SQL(" LIMIT 500") + sql.SQL(f" -- {info}"), cache_stats  # type: ignore


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
        SELECT cd.complex_data_id,
            {match_columns}
        FROM complex_data cd""").format(
            match_columns=sql.SQL(", ").join(sql.SQL("{}.id AS match_{}").format(sql.Identifier(f"p{i}"), sql.Literal(i)) for i in atoms.keys())
        )
        join_table_alias = "cd"

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

    sql_query += sql.SQL(" WHERE ")
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
    auto_queue = data.get("auto_queue", False)  # Whether to automatically add to queue

    app.logger.info(f"Search request - skip_execution: {skip_execution} ({'PREVIEW' if skip_execution else 'EXECUTION'})")
    app.logger.debug(f"Selected pairs: {selected_pairs}")

    if not selected_pairs:
        return jsonify({"error": "No pairs selected"}), 400

    try:
        sql_query, cache_stats = get_extended_search_query(selected_pairs, auto_queue=auto_queue)
        app.logger.debug(f"Generated SQL query: {sql_query}")
        if skip_execution:
            return jsonify({"sql_query": sqlparse.format(sql_query, reindent=True), "cache_stats": cache_stats})

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
                    "cache_stats": cache_stats,
                    "execution_time_seconds": round(req_time, 3),
                }
            )
    except Exception as e:
        app.logger.error(f"Error executing search: {str(e)}", exc_info=True)
        return jsonify({"error": f"Error executing search: {str(e)}"}), 500


@app.route("/variant_view")
def variant_view():
    """Show query fragments and cache analysis page"""
    selected_pairs = request.args.get("selected_pairs", "[]")
    try:
        selected_pairs = json.loads(selected_pairs)
        return render_template("variant_view.html", selected_pairs=json.dumps(selected_pairs))
    except Exception as e:
        app.logger.error(f"Error processing variant view: {str(e)}")
        return redirect(url_for("error", message="An error occurred while processing the variant view"))


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


# Duplicate route removed - search_results.html route already exists above


@app.route("/cache_query_direct", methods=["POST"])
def cache_query_direct():
    """Add a query directly to the cache using pcache-add CLI"""
    data = request.json
    if data is None:
        return jsonify({"error": "No data received"}), 400

    selected_pairs = data.get("selected_pairs", [])
    if not selected_pairs:
        return jsonify({"error": "No pairs selected"}), 400

    try:
        # Generate the base query for caching
        base_query = generate_search_query_sql(selected_pairs, base_query=True)
        query_str = base_query.as_string()

        # Use pcache-add to add the query to cache
        import subprocess

        # Convert cache type for CLI compatibility
        cli_cache_type = "redis_set" if args.cachetype == "redis" else args.cachetype

        result = subprocess.run(
            [
                "pcache-add",
                "--direct",
                "--query",
                query_str,
                "--partition-key",
                "complex_data_id",
                "--cache-backend",
                cli_cache_type,
                "--env-file",
                "database.env.example",
                "--db-name",
                "proteins",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            app.logger.info(f"Successfully added query to cache: {query_str}")
            return jsonify({"success": True, "message": "Query added to cache successfully", "query": query_str, "output": result.stdout})
        else:
            app.logger.error(f"Failed to add query to cache. Error: {result.stderr}")
            return jsonify({"success": False, "error": f"Failed to add query to cache: {result.stderr}"}), 500

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Cache operation timed out"}), 500
    except Exception as e:
        app.logger.error(f"Error adding query to cache: {str(e)}", exc_info=True)
        return jsonify({"error": f"Error adding query to cache: {str(e)}"}), 500


@app.route("/cache_query_queue", methods=["POST"])
def cache_query_queue():
    """Add a query to the original query queue using pcache-add CLI"""
    data = request.json
    if data is None:
        return jsonify({"error": "No data received"}), 400

    selected_pairs = data.get("selected_pairs", [])
    if not selected_pairs:
        return jsonify({"error": "No pairs selected"}), 400

    try:
        # Generate the base query for caching
        base_query = generate_search_query_sql(selected_pairs, base_query=True)
        query_str = base_query.as_string()

        # Use pcache-add to add the query to queue
        import subprocess

        result = subprocess.run(
            ["pcache-add", "--queue-original", "--query", query_str, "--partition-key", "complex_data_id", "--env-file", "database.env.example"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            app.logger.info(f"Successfully added query to queue: {query_str}")
            return jsonify({"success": True, "message": "Query added to processing queue successfully", "query": query_str, "output": result.stdout})
        else:
            app.logger.error(f"Failed to add query to queue. Error: {result.stderr}")
            return jsonify({"success": False, "error": f"Failed to add query to queue: {result.stderr}"}), 500

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Queue operation timed out"}), 500
    except Exception as e:
        app.logger.error(f"Error adding query to queue: {str(e)}", exc_info=True)
        return jsonify({"error": f"Error adding query to queue: {str(e)}"}), 500


@app.route("/cache_stats")
def cache_stats():
    """Get cache statistics using pcache-manage"""
    try:
        import subprocess

        # Convert cache type for CLI compatibility
        cli_cache_type = "redis_set" if args.cachetype == "redis" else args.cachetype

        # Set environment and run pcache-manage
        env = os.environ.copy()
        # Load additional environment variables from database.env.example
        from dotenv import load_dotenv

        load_dotenv("database.env.example")
        env.update(
            {
                "CACHE_BACKEND": cli_cache_type,
                "PG_DB_NAME": os.getenv("PG_DB_NAME", "proteins"),
                "PG_DB_HOST": os.getenv("PG_DB_HOST", "postgres"),
                "PG_DB_USER": os.getenv("PG_DB_USER", "postgres"),
                "PG_DB_PASSWORD": os.getenv("PG_DB_PASSWORD", "postgres"),
                "REDIS_HOST": os.getenv("REDIS_HOST", "redis"),
                "REDIS_PORT": str(os.getenv("REDIS_PORT", "6379")),
                "REDIS_CACHE_DB": str(os.getenv("REDIS_CACHE_DB", "5")),
            }
        )

        result = subprocess.run(["pcache-manage", "cache", "overview"], capture_output=True, text=True, timeout=10, env=env)

        if result.returncode == 0:
            # Cache overview output goes to stderr in newer versions
            stats_output = result.stdout if result.stdout.strip() else result.stderr
            return jsonify({"success": True, "stats": stats_output, "cache_type": args.cachetype})
        else:
            return jsonify({"success": False, "error": result.stderr}), 500

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Cache stats operation timed out"}), 500
    except Exception as e:
        app.logger.error(f"Error getting cache stats: {str(e)}", exc_info=True)
        return jsonify({"error": f"Error getting cache stats: {str(e)}"}), 500


@app.route("/queue_status")
def queue_status():
    """Get current queue status"""
    try:
        import subprocess

        # Set environment and run pcache-manage for queue
        env = os.environ.copy()
        from dotenv import load_dotenv

        load_dotenv("database.env.example")
        env.update(
            {
                "QUERY_QUEUE_PROVIDER": "redis",
                "REDIS_HOST": os.getenv("REDIS_HOST", "redis"),
                "REDIS_PORT": str(os.getenv("REDIS_PORT", "6379")),
                "QUERY_QUEUE_REDIS_DB": str(os.getenv("QUERY_QUEUE_REDIS_DB", "1")),
            }
        )

        app.logger.debug(f"Queue count environment: QUERY_QUEUE_PROVIDER={env.get('QUERY_QUEUE_PROVIDER')}, REDIS_HOST={env.get('REDIS_HOST')}")

        result = subprocess.run(["pcache-manage", "queue", "count"], capture_output=True, text=True, timeout=5, env=env)

        app.logger.debug(f"Queue count result: returncode={result.returncode}, stdout='{result.stdout}', stderr='{result.stderr}'")

        if result.returncode == 0:
            # Parse queue counts from stdout (newer version) or stderr (fallback)
            total_queue_count = "0"
            original_queue_count = "0"
            fragment_queue_count = "0"
            output = result.stdout if result.stdout.strip() else result.stderr

            for line in output.split("\n"):
                app.logger.debug(f"Processing line: '{line}'")
                if "Original query queue:" in line:
                    # Format: "INFO:   Original query queue: 0 entries"
                    parts = line.split(":")
                    for part in parts:
                        if "entries" in part:
                            original_queue_count = part.strip().split()[0]
                            break
                elif "Query fragment queue:" in line:
                    # Format: "INFO:   Query fragment queue: 0 entries"
                    parts = line.split(":")
                    for part in parts:
                        if "entries" in part:
                            fragment_queue_count = part.strip().split()[0]
                            break
                elif "Total queue entries:" in line or "Total Queue Entries:" in line:
                    # Format: "INFO:   Total queue entries: 0"
                    parts = line.split(":")
                    for part in parts:
                        if part.strip().isdigit() or (part.strip().split() and part.strip().split()[0].isdigit()):
                            total_queue_count = part.strip().split()[0]
                            break

            app.logger.debug(f"Parsed queue counts - total: {total_queue_count}, original: {original_queue_count}, fragment: {fragment_queue_count}")

            return jsonify(
                {
                    "success": True,
                    "queue_count": total_queue_count,
                    "original_queue_count": original_queue_count,
                    "fragment_queue_count": fragment_queue_count,
                    "raw_output": output,
                }
            )
        else:
            return jsonify({"success": False, "error": result.stderr}), 500

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Queue status operation timed out"}), 500
    except Exception as e:
        app.logger.error(f"Error getting queue status: {str(e)}", exc_info=True)
        return jsonify({"error": f"Error getting queue status: {str(e)}"}), 500


@app.route("/cache_count")
def cache_count():
    """Get current cache entry count"""
    try:
        import subprocess

        # Set environment and run pcache-manage for cache count
        env = os.environ.copy()
        from dotenv import load_dotenv

        load_dotenv("database.env.example")

        # Convert cache type for CLI compatibility
        cli_cache_type = "redis_set" if args.cachetype == "redis" else args.cachetype

        env.update(
            {
                "CACHE_BACKEND": cli_cache_type,
                "REDIS_HOST": os.getenv("REDIS_HOST", "redis"),
                "REDIS_PORT": str(os.getenv("REDIS_PORT", "6379")),
                "REDIS_CACHE_DB": str(os.getenv("REDIS_CACHE_DB", "5")),
            }
        )

        app.logger.debug(f"Cache count environment: CACHE_BACKEND={env.get('CACHE_BACKEND')}, REDIS_HOST={env.get('REDIS_HOST')}")

        result = subprocess.run(["pcache-manage", "cache", "count"], capture_output=True, text=True, timeout=5, env=env)

        app.logger.debug(f"Cache count result: returncode={result.returncode}, stdout='{result.stdout}', stderr='{result.stderr}'")

        if result.returncode == 0:
            # Parse cache count from stdout (newer version) or stderr (fallback)
            cache_count = "0"
            output = result.stdout if result.stdout.strip() else result.stderr
            for line in output.split("\n"):
                if "Valid entries:" in line:
                    # Handle both old format "Valid entries: 9" and new format "INFO:   Valid entries: 9"
                    parts = line.split(":")
                    if len(parts) >= 3 and "INFO" in parts[0]:
                        cache_count = parts[2].strip()
                    elif len(parts) >= 2:
                        cache_count = parts[1].strip()
                    break

            return jsonify({"success": True, "cache_count": cache_count, "raw_output": output})
        else:
            return jsonify({"success": False, "error": result.stderr}), 500

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Cache count operation timed out"}), 500
    except Exception as e:
        app.logger.error(f"Error getting cache count: {str(e)}", exc_info=True)
        return jsonify({"error": f"Error getting cache count: {str(e)}"}), 500


@app.route("/get_query_fragments", methods=["POST"])
def get_query_fragments():
    """Get query fragments that would be generated for cache processing"""
    data = request.json
    if data is None:
        return jsonify({"error": "No data received"}), 400

    selected_pairs = data.get("selected_pairs", [])
    if not selected_pairs:
        return jsonify({"error": "No pairs selected"}), 400

    try:
        # Generate the base query that would be used for caching
        base_query = generate_search_query_sql(selected_pairs, base_query=True)
        query_str = base_query.as_string()

        # Use PartitionCache to get the fragments
        # Get all possible query fragments that would be generated
        fragments = partitioncache.query_processor.generate_all_query_hash_pairs(
            query=query_str, partition_key="complex_data_id", min_component_size=1, max_component_size=10, follow_graph=True, keep_all_attributes=True
        )

        # Format fragments for display
        fragment_list = []
        for fragment_sql, fragment_hash in fragments:
            fragment_list.append({"hash": fragment_hash, "sql": fragment_sql, "sql_formatted": sqlparse.format(fragment_sql, reindent=True)})

        return jsonify(
            {
                "success": True,
                "base_query": query_str,
                "base_query_formatted": sqlparse.format(query_str, reindent=True),
                "fragments": fragment_list,
                "fragment_count": len(fragment_list),
            }
        )

    except Exception as e:
        app.logger.error(f"Error getting query fragments: {str(e)}", exc_info=True)
        return jsonify({"error": f"Error getting query fragments: {str(e)}"}), 500


@app.route("/get_cached_fragments", methods=["POST"])
def get_cached_fragments():
    """Get fragments that are currently cached and their partition keys"""
    data = request.json
    if data is None:
        return jsonify({"error": "No data received"}), 400

    selected_pairs = data.get("selected_pairs", [])
    if not selected_pairs:
        return jsonify({"error": "No pairs selected"}), 400

    try:
        # Generate the base query
        base_query = generate_search_query_sql(selected_pairs, base_query=True)
        query_str = base_query.as_string()

        # Get cache handler
        cachetype = args.cachetype
        cache_handler = partitioncache.get_cache_handler(cachetype)

        # Get all possible fragments
        fragments = partitioncache.query_processor.generate_all_query_hash_pairs(
            query=query_str, partition_key="complex_data_id", min_component_size=1, max_component_size=10, follow_graph=True, keep_all_attributes=True
        )

        # Check which fragments are in cache
        cached_fragments = []
        for fragment_sql, fragment_hash in fragments:
            try:
                partition_keys = cache_handler.get_partition_keys_for_hash(fragment_hash)
                if partition_keys is not None and len(partition_keys) > 0:
                    cached_fragments.append(
                        {
                            "hash": fragment_hash,
                            "sql": fragment_sql,
                            "sql_formatted": sqlparse.format(fragment_sql, reindent=True),
                            "partition_count": len(partition_keys),
                            "partition_keys": list(partition_keys)[:10] if len(partition_keys) > 10 else list(partition_keys),  # Limit to first 10 for display
                        }
                    )
            except Exception as e:
                app.logger.debug(f"Fragment {fragment_hash} not in cache or error: {str(e)}")
                continue

        return jsonify({"success": True, "cached_fragments": cached_fragments, "cached_count": len(cached_fragments), "total_fragments": len(fragments)})

    except Exception as e:
        app.logger.error(f"Error getting cached fragments: {str(e)}", exc_info=True)
        return jsonify({"error": f"Error getting cached fragments: {str(e)}"}), 500


@app.route("/clear_cache", methods=["POST"])
def clear_cache():
    """Clear all cache entries using pcache-manage delete"""
    try:
        import subprocess

        # Set environment and run pcache-manage for cache deletion
        env = os.environ.copy()
        from dotenv import load_dotenv

        load_dotenv("database.env.example")
        # Convert cache type for CLI compatibility
        cli_cache_type = "redis_set" if args.cachetype == "redis" else args.cachetype

        env.update(
            {
                "CACHE_BACKEND": cli_cache_type,
                "REDIS_HOST": os.getenv("REDIS_HOST", "redis"),
                "REDIS_PORT": str(os.getenv("REDIS_PORT", "6379")),
                "REDIS_CACHE_DB": str(os.getenv("REDIS_CACHE_DB", "5")),
            }
        )

        result = subprocess.run(["pcache-manage", "cache", "delete", "--all"], capture_output=True, text=True, timeout=30, env=env, input="yes\n")

        if result.returncode == 0:
            app.logger.info("Successfully cleared all cache entries")
            return jsonify({"success": True, "message": "All cache entries cleared successfully", "output": result.stdout})
        else:
            return jsonify({"success": False, "error": result.stderr}), 500

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Clear cache operation timed out"}), 500
    except Exception as e:
        app.logger.error(f"Error clearing cache: {str(e)}", exc_info=True)
        return jsonify({"error": f"Error clearing cache: {str(e)}"}), 500


@app.route("/get_variant_analysis", methods=["POST"])
def get_variant_analysis():
    """Get both queue fragments and extended checking variants for the variant view"""
    data = request.json
    if data is None:
        return jsonify({"error": "No data received"}), 400

    selected_pairs = data.get("selected_pairs", [])
    if not selected_pairs:
        return jsonify({"error": "No pairs selected"}), 400

    try:
        # Use the same method as search results to ensure consistency
        # Generate the base query for cache lookup (same as search results)
        base_query = generate_search_query_sql(selected_pairs, base_query=False)
        query_str = base_query.as_string()

        app.logger.debug(f"Variant view base query: {query_str}")

        # Get cache handler
        cachetype = args.cachetype
        cache_handler = partitioncache.get_cache_handler(cachetype)

        # Get partition keys using the same method as search results
        # This call will also tell us which hashes were actually used
        partiton_key_set, num_total_build_hashes, num_used_hashes = partitioncache.get_partition_keys(
            query_str, cache_handler, partition_key="complex_data_id", min_component_size=1
        )

        app.logger.debug(
            f"Cache stats: used_hashes={num_used_hashes}, total_hashes={num_total_build_hashes}, partitions={len(partiton_key_set) if partiton_key_set else 0}"
        )

        # CRITICAL: We need to get the EXACT fragments that get_partition_keys uses
        # The issue is that generate_all_query_hash_pairs transforms aliases differently
        # than what's actually stored in cache

        # First, let's see what's actually in the cache by getting all possible hashes
        # Using the internal function that get_partition_keys uses
        import partitioncache.query_processor as qp

        # Based on fragment counts, keep_attrs=False (557) matches search results
        # So we need to use that setting to match what's actually cached
        queue_fragments = list(
            qp.generate_all_query_hash_pairs(
                query=query_str,
                partition_key="complex_data_id",
                min_component_size=1,
                follow_graph=True,
                keep_all_attributes=True,  # As pcache-monitor uses
                max_component_size=None,
            )
        )

        extended_fragments = list(
            qp.generate_all_query_hash_pairs(
                query=query_str,
                partition_key="complex_data_id",
                min_component_size=1,
                follow_graph=True,
                keep_all_attributes=False,  # As cache lookup uses
                max_component_size=None,
            )
        )

        app.logger.info(f"Fragment counts: queue={len(queue_fragments)}, extended={len(extended_fragments)}")

        # Use the same approach as get_partition_keys to find cached fragments
        # This avoids the method name issue and uses the proven working approach
        all_fragments = list(queue_fragments) + list(extended_fragments)
        unique_hashes = set()
        cache_lookup = {}

        # Since get_partition_keys works, let's use that approach per fragment
        # Check each fragment individually using the same method as search
        app.logger.info(f"Checking cache for {len(all_fragments)} total fragments using get_partition_keys approach")

        for fragment_sql, fragment_hash in all_fragments:
            app.logger.info(f"Checking fragment: {fragment_hash}")
            if fragment_hash not in unique_hashes:
                unique_hashes.add(fragment_hash)
                try:
                    is_cached = cache_handler.exists(fragment_hash, partition_key="complex_data_id")

                    partition_count = len(cache_handler.get(fragment_hash, partition_key="complex_data_id")) if is_cached else 0

                    cache_lookup[fragment_hash] = {"sql": fragment_sql, "is_cached": is_cached, "partition_count": partition_count}

                    if is_cached:
                        app.logger.info(f"✅ FOUND CACHED: {fragment_hash} with {partition_count} partitions")

                except Exception as e:
                    app.logger.debug(f"Fragment {fragment_hash} check failed: {str(e)}")
                    cache_lookup[fragment_hash] = {"sql": fragment_sql, "is_cached": False, "partition_count": 0}

        cached_count = sum(1 for info in cache_lookup.values() if info["is_cached"])
        app.logger.info(f"🎯 RESULT: Found {cached_count} cached fragments out of {len(cache_lookup)} total")

        # Log available methods on cache handler for debugging
        app.logger.info(f"Cache handler type: {type(cache_handler)}")
        app.logger.info(f"Available methods: {[method for method in dir(cache_handler) if not method.startswith('_')]}")

        # Check which fragments are cached and create sets for intersection
        queue_hashes = {frag_hash for _, frag_hash in queue_fragments}
        extended_hashes = {frag_hash for _, frag_hash in extended_fragments}

        # Format queue fragments using the cache lookup
        queue_list = []
        for fragment_sql, fragment_hash in queue_fragments:
            cache_info = cache_lookup.get(fragment_hash, {"is_cached": False, "partition_count": 0})

            queue_list.append(
                {
                    "hash": fragment_hash,
                    "sql": fragment_sql,
                    "sql_formatted": sqlparse.format(fragment_sql, reindent=True),
                    "is_cached": cache_info["is_cached"],
                    "partition_count": cache_info["partition_count"],
                }
            )

        # Format extended fragments (show ALL variants, not just those missing from queue)
        extended_list = []
        for fragment_sql, fragment_hash in extended_fragments:
            # Show ALL extended variants, including those in queue
            cache_info = cache_lookup.get(fragment_hash, {"is_cached": False, "partition_count": 0})

            extended_list.append(
                {
                    "hash": fragment_hash,
                    "sql": fragment_sql,
                    "sql_formatted": sqlparse.format(fragment_sql, reindent=True),
                    "is_cached": cache_info["is_cached"],
                    "partition_count": cache_info["partition_count"],
                }
            )

        # Sort both lists by SQL length in descending order
        queue_list.sort(key=lambda x: len(x['sql']), reverse=True)
        extended_list.sort(key=lambda x: len(x['sql']), reverse=True)
        
        # Calculate statistics to match search results
        partitions_found = len(partiton_key_set) if partiton_key_set else 0
        total_database_partitions = get_total_partition_count()

        return jsonify(
            {
                "success": True,
                "base_query": query_str,
                "base_query_formatted": sqlparse.format(query_str, reindent=True),
                "queue_fragments": queue_list,
                "extended_variants": extended_list,
                "queue_count": len(queue_list),
                "extended_count": len(extended_list),
                "queue_cached_count": sum(1 for f in queue_list if f["is_cached"]),
                "extended_cached_count": sum(1 for f in extended_list if f["is_cached"]),
                # Add statistics that match search results exactly
                "used_hashes": num_used_hashes,
                "total_hashes": num_total_build_hashes,
                "partitions_found": partitions_found,
                "total_database_partitions": total_database_partitions,
            }
        )

    except Exception as e:
        app.logger.error(f"Error getting variant analysis: {str(e)}", exc_info=True)
        return jsonify({"error": f"Error getting variant analysis: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
