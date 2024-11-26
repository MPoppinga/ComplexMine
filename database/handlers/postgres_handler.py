import psycopg
from typing import Any, Dict, Optional
from .base_handler import DatabaseHandler

class PostgresHandler(DatabaseHandler):
    def connect(self) -> Any:
        if not self._connection or self._connection.closed:
            self._connection = psycopg.connect(**self.db_params)
        return self._connection

    def disconnect(self) -> None:
        if self._connection and not self._connection.closed:
            self._connection.close()
            self._connection = None

    def get_connection(self) -> Any:
        return self.connect()

    def execute_query(self, query: str, params: Optional[tuple] = None) -> Any:
        conn = self.get_connection()
        with conn.cursor() as cur:
            if params:
                cur.execute(query, params)
            else:
                cur.execute(query)
            try:
                return cur.fetchall()
            except psycopg.ProgrammingError:
                return None

    def create_point_geometry(self, x: float, y: float, z: float) -> str:
        return f"ST_MakePoint({x}, {y}, {z})"

    def get_distance_query(self, point1: str, point2: str, distance: float) -> str:
        return f"""
        ST_3DDWithin({point1}, {point2}, {distance} + 0.1)
        AND NOT ST_3DDWithin({point1}, {point2}, {distance} - 0.1)
        """ 