"""
Database migration management
"""

import sqlite3
import logging
from pathlib import Path
from typing import List, Dict
from .schema import Database

logger = logging.getLogger(__name__)


class Migration:
    """Represents a single database migration"""

    def __init__(self, version: int, description: str, up_sql: str, down_sql: str = ""):
        self.version = version
        self.description = description
        self.up_sql = up_sql
        self.down_sql = down_sql


class MigrationManager:
    """Manages database schema migrations"""

    def __init__(self, database: Database):
        self.database = database
        self.migrations_dir = Path(__file__).parent / "migrations"
        self.migrations: List[Migration] = []
        self._load_migrations()

    def _load_migrations(self):
        """Load migration files from migrations directory"""
        if not self.migrations_dir.exists():
            self.migrations_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created migrations directory at {self.migrations_dir}")
            return

        # Load migration files (format: V001__description.sql)
        for migration_file in sorted(self.migrations_dir.glob("V*.sql")):
            parts = migration_file.stem.split("__", 1)
            if len(parts) == 2:
                version_str = parts[0][1:]  # Remove 'V' prefix
                try:
                    version = int(version_str)
                    description = parts[1]
                    with open(migration_file, 'r') as f:
                        content = f.read()
                        # Split up and down migrations if present
                        if "-- DOWN" in content:
                            up_sql, down_sql = content.split("-- DOWN")
                            up_sql = up_sql.strip()
                            down_sql = down_sql.strip()
                        else:
                            up_sql = content.strip()
                            down_sql = ""
                        self.migrations.append(Migration(version, description, up_sql, down_sql))
                        logger.info(f"Loaded migration V{version}: {description}")
                except ValueError as e:
                    logger.warning(f"Could not parse migration file {migration_file}: {e}")

    def get_current_version(self) -> int:
        """Get current database schema version"""
        return self.database.get_schema_version()

    def get_latest_version(self) -> int:
        """Get latest available migration version"""
        if not self.migrations:
            return 0
        return max(m.version for m in self.migrations)

    def migrate(self, target_version: int = None):
        """
        Run migrations to bring database to target version

        Args:
            target_version: Target schema version. If None, migrates to latest.
        """
        current_version = self.get_current_version()
        latest_version = self.get_latest_version()

        if target_version is None:
            target_version = latest_version

        if current_version == target_version:
            logger.info(f"Database already at version {current_version}")
            return

        if target_version > latest_version:
            logger.warning(f"Target version {target_version} exceeds latest version {latest_version}")
            target_version = latest_version

        if target_version < current_version:
            logger.warning(f"Downgrading from {current_version} to {target_version}")
            self._migrate_down(current_version, target_version)
        else:
            logger.info(f"Migrating from {current_version} to {target_version}")
            self._migrate_up(current_version, target_version)

    def _migrate_up(self, from_version: int, to_version: int):
        """Apply migrations to upgrade schema"""
        for migration in self.migrations:
            if from_version < migration.version <= to_version:
                logger.info(f"Applying migration V{migration.version}: {migration.description}")
                try:
                    with self.database.transaction() as conn:
                        conn.executescript(migration.up_sql)
                        # Update schema version
                        conn.execute(
                            "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                            (migration.version, migration.description)
                        )
                    logger.info(f"Migration V{migration.version} completed")
                except Exception as e:
                    logger.error(f"Migration V{migration.version} failed: {e}")
                    raise

    def _migrate_down(self, from_version: int, to_version: int):
        """Apply down migrations to downgrade schema"""
        for migration in reversed(self.migrations):
            if to_version <= migration.version < from_version:
                if not migration.down_sql:
                    logger.warning(f"Migration V{migration.version} has no down migration, skipping")
                    continue
                logger.info(f"Reverting migration V{migration.version}: {migration.description}")
                try:
                    with self.database.transaction() as conn:
                        conn.executescript(migration.down_sql)
                        # Remove schema version entry
                        conn.execute(
                            "DELETE FROM schema_version WHERE version = ?",
                            (migration.version,)
                        )
                    logger.info(f"Migration V{migration.version} reverted")
                except Exception as e:
                    logger.error(f"Migration revert V{migration.version} failed: {e}")
                    raise

    def create_migration(self, description: str) -> Path:
        """
        Create a new migration file

        Args:
            description: Migration description

        Returns:
            Path to created migration file
        """
        if not self.migrations_dir.exists():
            self.migrations_dir.mkdir(parents=True, exist_ok=True)

        next_version = self.get_latest_version() + 1
        filename = f"V{next_version:03d}__{description.replace(' ', '_')}.sql"
        migration_path = self.migrations_dir / filename

        template = f"""-- Migration V{next_version}: {description}
-- UP
-- Add your migration SQL here

-- DOWN
-- Add your rollback SQL here (optional)
"""

        with open(migration_path, 'w') as f:
            f.write(template)

        logger.info(f"Created migration file: {migration_path}")
        return migration_path
