import mysql.connector
from mysql.connector import Error as MySQLError
from typing import Any, Dict, Optional
from .base_handler import DatabaseHandler
import time


class MySQLHandler(DatabaseHandler):
    def __init__(self, db_params: Dict[str, Any]):
        super().__init__(db_params)
        self.max_retries = 3
        self.retry_delay = 1  # seconds

    def connect(self) -> Any:
        """Establish a connection to the database"""
        if not self._connection or not self._connection.is_connected():
            mysql_params = {
                "database": self.db_params.get("dbname"),
                "user": self.db_params.get("user"),
                "password": self.db_params.get("password"),
                "host": self.db_params.get("host"),
                "port": int(self.db_params.get("port", 3306)),
                "charset": "utf8mb4",
                "collation": "utf8mb4_general_ci",
                "use_unicode": True,
                "connect_timeout": 60,  # 60 seconds timeout
            }
            self._connection = mysql.connector.connect(**mysql_params)

            # Set session variables for consistent behavior
            with self._connection.cursor() as cursor:
                cursor.execute("SET NAMES utf8mb4")
                cursor.execute("SET CHARACTER SET utf8mb4")
                cursor.execute("SET character_set_connection=utf8mb4")
                cursor.execute("SET SESSION wait_timeout=28800")  # 8 hours
                cursor.execute("SET SESSION interactive_timeout=28800")  # 8 hours
        return self._connection

    def ensure_connection(self) -> Any:
        """Ensure the connection is alive and reconnect if necessary"""
        for attempt in range(self.max_retries):
            try:
                if not self._connection or not self._connection.is_connected():
                    self.connect()
                else:
                    # Test the connection with a simple query
                    try:
                        with self._connection.cursor() as cursor:
                            cursor.execute("SELECT 1")
                    except MySQLError:
                        self._connection = None
                        self.connect()
                return self._connection
            except MySQLError as e:
                if attempt == self.max_retries - 1:  # Last attempt
                    raise
                time.sleep(self.retry_delay * (attempt + 1))  # Exponential backoff
                self._connection = None  # Force reconnection
        return self._connection

    def disconnect(self) -> None:
        """Close the database connection"""
        if self._connection and self._connection.is_connected():
            self._connection.close()
            self._connection = None

    def get_connection(self) -> Any:
        """Get a connection, ensuring it's alive"""
        return self.ensure_connection()

    def execute_query(self, query: str, params: Optional[tuple] = None) -> Any:
        """Execute a query with automatic reconnection on failure"""
        max_attempts = 2  # Try once, retry once if connection lost
        attempt = 0
        last_error = None
        
        while attempt < max_attempts:
            conn = self.ensure_connection()
            cursor = None
            try:
                cursor = conn.cursor()
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                try:
                    result = cursor.fetchall()
                    return result
                except mysql.connector.errors.InterfaceError:
                    return None
            except MySQLError as e:
                last_error = e
                if "Lost connection" in str(e) or "Connection not available" in str(e):
                    attempt += 1
                    if attempt < max_attempts:
                        self._connection = None
                        time.sleep(self.retry_delay)
                        continue
                raise
            finally:
                if cursor:
                    cursor.close()
        
        if last_error:
            raise last_error
        raise MySQLError("Failed to execute query after maximum retries")

    def create_point_geometry(self, x: float, y: float, z: float) -> str:
        return f"POINT({x} {y} {z})"

    def get_distance_query(self, point1: str, point2: str, distance: float) -> str:
        return f"""
        ABS(ST_Distance({point1}, {point2}) - {distance}) <= 0.1
        """
