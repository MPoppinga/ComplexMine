import mysql.connector
from typing import Any, Optional
from .base_handler import DatabaseHandler


class MySQLHandler(DatabaseHandler):

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
                "pool_name": "mypool",
                "pool_size": 5,
                "get_warnings": True,
                "raise_on_warnings": True,
                "connection_timeout": 3600
            }
            self._connection = mysql.connector.connect(**mysql_params)

            # Set session variables for consistent behavior
            with self._connection.cursor() as cursor:
                cursor.execute("SET NAMES utf8mb4")
                cursor.execute("SET CHARACTER SET utf8mb4")
                cursor.execute("SET character_set_connection=utf8mb4")

        return self._connection

    

    def disconnect(self) -> None:
        """Close the database connection"""
        if self._connection and self._connection.is_connected():
            self._connection.close()
            self._connection = None

    def get_connection(self) -> Any:
        """Get a connection, ensuring it's alive"""
        return self.connect()

    def execute_query(self, query: str, params: Optional[tuple] = None) -> tuple[list[str], list[tuple]]:
        """_summary_

        Args:
            query (str): SQL query to execute
            params (Optional[tuple], optional): Parameters to use with the query. Defaults to None.

        Returns:
            tuple[list[str], list[tuple]]: Return list of column names and list of tuples with results
        """
        
        # split query into multiple queries if necessary
        
        if ";" in query:
            query_list = query.split(";")
        else:
            query_list = [query]

        
        conn = self.get_connection()

        with conn.cursor() as cursor:
            
            for query in query_list:
                cursor.execute(query, params)              
                if cursor.description:  
                    try:
                        return [i[0] for i in cursor.description], cursor.fetchall()
                    except mysql.connector.errors.InterfaceError:
                        pass
            return [], []


