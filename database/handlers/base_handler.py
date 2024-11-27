from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

class DatabaseHandler(ABC):
    def __init__(self, db_params: Dict[str, Any]):
        self.db_params = db_params
        self._connection = None

    def __enter__(self) -> 'DatabaseHandler':
        """Context manager entry point"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit point"""
        self.disconnect()

    @abstractmethod
    def connect(self) -> Any:
        """Establish a connection to the database"""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Close the database connection"""
        pass

    @abstractmethod
    def get_connection(self) -> Any:
        """Get the current database connection or create a new one"""
        pass

    @abstractmethod
    def execute_query(self, query: str, params: Optional[tuple] = None) -> tuple[list[str], list[tuple]]:
        """Execute a query and return the results"""
        pass
