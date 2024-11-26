from typing import Dict, Any
from .base_handler import DatabaseHandler
from .postgres_handler import PostgresHandler
from .mysql_handler import MySQLHandler

def get_database_handler(db_type: str, db_params: Dict[str, Any]) -> DatabaseHandler:
    """Factory function to get the appropriate database handler"""
    handlers = {
        'postgresql': PostgresHandler,
        'mysql': MySQLHandler
    }
    
    handler_class = handlers.get(db_type.lower())
    if not handler_class:
        raise ValueError(f"Unsupported database type: {db_type}")
    
    return handler_class(db_params) 