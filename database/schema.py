"""
Database schema initialization and management
"""

import sqlite3
import logging
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class Database:
    """Database connection and schema management"""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection: Optional[sqlite3.Connection] = None

    def connect(self) -> sqlite3.Connection:
        """Establish database connection"""
        if self.connection is None:
            self.connection = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0
            )
            self.connection.row_factory = sqlite3.Row
            # Enable foreign keys
            self.connection.execute("PRAGMA foreign_keys = ON")
            # Enable WAL mode for better concurrency
            self.connection.execute("PRAGMA journal_mode = WAL")
            logger.info(f"Connected to database at {self.db_path}")
        return self.connection

    def close(self):
        """Close database connection"""
        if self.connection is not None:
            self.connection.close()
            self.connection = None
            logger.info("Database connection closed")

    @contextmanager
    def transaction(self):
        """Context manager for database transactions"""
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Transaction failed, rolled back: {e}")
            raise

    def initialize_schema(self, schema_file: str = None):
        """
        Initialize database schema from SQL file

        Args:
            schema_file: Path to schema.sql file. If None, uses default.
        """
        if schema_file is None:
            schema_file = Path(__file__).parent / "schema.sql"

        schema_path = Path(schema_file)

        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        with open(schema_path, 'r') as f:
            schema_sql = f.read()

        with self.transaction() as conn:
            # Execute schema
            conn.executescript(schema_sql)
            logger.info("Database schema initialized successfully")

    def check_integrity(self) -> bool:
        """
        Run SQLite integrity check

        Returns:
            True if database is valid, False otherwise
        """
        try:
            with self.connect() as conn:
                cursor = conn.execute("PRAGMA integrity_check")
                result = cursor.fetchone()
                if result and result[0] == "ok":
                    logger.info("Database integrity check passed")
                    return True
                else:
                    logger.error(f"Database integrity check failed: {result}")
                    return False
        except Exception as e:
            logger.error(f"Integrity check error: {e}")
            return False

    def backup(self, backup_path: str = None):
        """
        Create database backup

        Args:
            backup_path: Path for backup file. If None, generates timestamped name.
        """
        if backup_path is None:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.db_path.parent / f"recommendations_backup_{timestamp}.db"

        backup_path = Path(backup_path)
        backup_path.parent.mkdir(parents=True, exist_ok=True)

        # Use SQLite backup API
        with self.connect() as source:
            backup = sqlite3.connect(str(backup_path))
            source.backup(backup)
            backup.close()

        logger.info(f"Database backup created at {backup_path}")
        return backup_path

    def get_schema_version(self) -> int:
        """Get current schema version"""
        with self.connect() as conn:
            cursor = conn.execute("SELECT MAX(version) FROM schema_version")
            result = cursor.fetchone()
            return result[0] if result and result[0] else 0

    def vacuum(self):
        """Run VACUUM to optimize database"""
        with self.connect() as conn:
            conn.execute("VACUUM")
            logger.info("Database VACUUM completed")

    def analyze(self):
        """Run ANALYZE to update query planner statistics"""
        with self.connect() as conn:
            conn.execute("ANALYZE")
            logger.info("Database ANALYZE completed")
