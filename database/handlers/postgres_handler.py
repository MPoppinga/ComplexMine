import psycopg
from typing import Any, Optional
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

    def get_connection(self):
        return self.connect()

    def execute_query(self, query: str, params: Optional[tuple] = None) -> Any:
        conn = self.get_connection()
        with conn.cursor() as cur:
            count_extra_queries = -1
            for query_part in query.split(";"):
                if query_part.strip(): # Ignore empty queries (e.g. trailing ; in query)
                    count_extra_queries += 1
                
            results = cur.execute(query, params)
            for _ in range(count_extra_queries):                
                cur.nextset()  # Skip potential TMP Table creation empty resultsets       
            
            columns = [desc[0] for desc in results.description] if results and results.description else []
            return columns, cur.fetchall()
  
