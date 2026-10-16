"""
Playlist monitoring and synchronization
Detects changes to seed playlists and updates the database
"""

import hashlib
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime
from dataclasses import dataclass

import config
from database import Database

logger = logging.getLogger(__name__)


@dataclass
class PlaylistEntry:
    """Represents a single entry in a playlist"""
    path: str
    title: str = ""
    artist: str = ""
    duration: float = 0

    def __hash__(self):
        # Hash based on normalized path for deduplication
        return hash(self.path.lower().strip())

    def __eq__(self, other):
        if not isinstance(other, PlaylistEntry):
            return False
        return self.path.lower().strip() == other.path.lower().strip()


class PlaylistMonitor:
    """Monitors seed playlists for changes and synchronizes with database"""

    def __init__(self, database: Database):
        self.database = database
        self.config = config.get_config()

    def compute_file_hash(self, file_path: str) -> str:
        """
        Compute SHA256 hash of a file

        Args:
            file_path: Path to file

        Returns:
            Hexadecimal hash string
        """
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    def parse_m3u(self, file_path: str) -> List[PlaylistEntry]:
        """
        Parse M3U playlist file

        Args:
            file_path: Path to M3U file

        Returns:
            List of PlaylistEntry objects
        """
        entries = []
        path_obj = Path(file_path)

        if not path_obj.exists():
            logger.error(f"Playlist file not found: {file_path}")
            return entries

        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        current_entry = None

        for line in lines:
            line = line.strip()

            if not line:
                continue

            if line.startswith('#EXTINF:'):
                # Parse extended info: #EXTINF:duration,artist - title
                try:
                    parts = line[8:].split(',', 1)
                    if len(parts) == 2:
                        duration_str, metadata = parts
                        duration = float(duration_str) if duration_str else 0

                        # Parse artist and title
                        if ' - ' in metadata:
                            artist, title = metadata.split(' - ', 1)
                        else:
                            artist = ""
                            title = metadata

                        current_entry = PlaylistEntry(
                            path="",
                            title=title.strip(),
                            artist=artist.strip(),
                            duration=duration
                        )
                except Exception as e:
                    logger.warning(f"Error parsing EXTINF line: {e}")
                    current_entry = None

            elif not line.startswith('#'):
                # This is a file path
                file_line = line.strip()

                if current_entry:
                    current_entry.path = file_line
                    entries.append(current_entry)
                    current_entry = None
                else:
                    # No EXTINF, just add the path
                    entries.append(PlaylistEntry(path=file_line))

        logger.info(f"Parsed {len(entries)} entries from {file_path}")
        return entries

    def get_playlist_hash(self, file_path: str) -> Optional[str]:
        """
        Get stored hash of playlist from database

        Args:
            file_path: Path to playlist file

        Returns:
            Stored hash or None if not found
        """
        with self.database.connect() as conn:
            cursor = conn.execute(
                "SELECT file_hash FROM seed_playlists WHERE file_path = ?",
                (file_path,)
            )
            result = cursor.fetchone()
            return result[0] if result else None

    def register_playlist(self, name: str, file_path: str, weight: float = 1.0):
        """
        Register a seed playlist in the database

        Args:
            name: Playlist name (e.g., 'Bored.m3u')
            file_path: Full path to playlist file
            weight: Preference weight
        """
        with self.database.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO seed_playlists
                (name, file_path, weight, created_at)
                VALUES (?, ?, ?, COALESCE((SELECT created_at FROM seed_playlists WHERE name = ?), CURRENT_TIMESTAMP))
                """,
                (name, file_path, weight, name)
            )
        logger.info(f"Registered playlist: {name} at {file_path}")

    def sync_playlist(self, name: str, file_path: str) -> Dict[str, int]:
        """
        Synchronize a seed playlist with the database

        Args:
            name: Playlist name
            file_path: Path to playlist file

        Returns:
            Dictionary with sync statistics
        """
        logger.info(f"Syncing playlist: {name}")

        # Get current file hash
        current_hash = self.compute_file_hash(file_path)
        stored_hash = self.get_playlist_hash(file_path)

        # Check if playlist has changed
        if stored_hash and current_hash == stored_hash:
            logger.info(f"Playlist {name} unchanged, skipping sync")
            return {
                'added': 0,
                'removed': 0,
                'unchanged': 0,
                'total': 0
            }

        # Parse playlist
        entries = self.parse_m3u(file_path)

        if not entries:
            logger.warning(f"No entries found in playlist: {name}")
            return {
                'added': 0,
                'removed': 0,
                'unchanged': 0,
                'total': 0
            }

        # Get playlist ID
        with self.database.connect() as conn:
            cursor = conn.execute(
                "SELECT id FROM seed_playlists WHERE name = ?",
                (name,)
            )
            result = cursor.fetchone()
            if not result:
                logger.error(f"Playlist {name} not registered in database")
                return {
                    'added': 0,
                    'removed': 0,
                    'unchanged': 0,
                    'total': 0
                }
            playlist_id = result[0]

        # Get current entries
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                SELECT t.file_path, spe.id
                FROM seed_playlist_entries spe
                JOIN tracks t ON spe.track_id = t.id
                WHERE spe.playlist_id = ? AND spe.is_current = 1
                """,
                (playlist_id,)
            )
            current_entries = {row[0]: row[1] for row in cursor.fetchall()}

        # Compute set difference
        new_paths = {entry.path for entry in entries}
        old_paths = set(current_entries.keys())

        added_paths = new_paths - old_paths
        removed_paths = old_paths - new_paths
        unchanged_paths = new_paths & old_paths

        stats = {
            'added': len(added_paths),
            'removed': len(removed_paths),
            'unchanged': len(unchanged_paths),
            'total': len(entries)
        }

        with self.database.transaction() as conn:
            # Mark old entries as removed
            for path in removed_paths:
                entry_id = current_entries[path]
                conn.execute(
                    "UPDATE seed_playlist_entries SET is_current = 0, removed_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (entry_id,)
                )

            # Add new entries
            for entry in entries:
                if entry.path in added_paths:
                    # Try to find or create track
                    track_id = self._get_or_create_track(conn, entry)
                    if track_id:
                        conn.execute(
                            """
                            INSERT INTO seed_playlist_entries
                            (playlist_id, track_id, added_at, is_current)
                            VALUES (?, ?, CURRENT_TIMESTAMP, 1)
                            """,
                            (playlist_id, track_id)
                        )

            # Update playlist hash and sync time
            conn.execute(
                """
                UPDATE seed_playlists
                SET file_hash = ?, last_synced_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (current_hash, playlist_id)
            )

        logger.info(f"Synced playlist {name}: {stats}")
        return stats

    def _get_or_create_track(self, conn, entry: PlaylistEntry) -> Optional[int]:
        """
        Get existing track or create new one

        Args:
            conn: Database connection
            entry: Playlist entry

        Returns:
            Track ID or None if creation failed
        """
        # Try to find by file path
        cursor = conn.execute(
            "SELECT id FROM tracks WHERE file_path = ?",
            (entry.path,)
        )
        result = cursor.fetchone()
        if result:
            return result[0]

        # Create new track (metadata may be incomplete)
        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (entry.path, entry.title, entry.artist)
        )
        return cursor.lastrowid

    def sync_all_seed_playlists(self) -> Dict[str, Dict[str, int]]:
        """
        Synchronize all registered seed playlists

        Returns:
            Dictionary mapping playlist names to sync statistics
        """
        results = {}

        # Sync primary playlist
        primary_stats = self.sync_playlist(
            "Bored.m3u",
            self.config.paths.seed_playlist_primary
        )
        results["Bored.m3u"] = primary_stats

        # Sync secondary playlist
        secondary_stats = self.sync_playlist(
            "the better playlist.m3u",
            self.config.paths.seed_playlist_secondary
        )
        results["the better playlist.m3u"] = secondary_stats

        return results

    def register_all_seed_playlists(self):
        """Register both seed playlists in the database"""
        self.register_playlist(
            "Bored.m3u",
            self.config.paths.seed_playlist_primary,
            self.config.recommendation.seed_playlist_primary_weight
        )

        self.register_playlist(
            "the better playlist.m3u",
            self.config.paths.seed_playlist_secondary,
            self.config.recommendation.seed_playlist_secondary_weight
        )
