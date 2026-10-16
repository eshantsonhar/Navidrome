"""
Music library management
Handles track metadata, file operations, and library scanning
"""

import hashlib
import logging
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime
from dataclasses import dataclass

from mutagen import File
from mutagen.id3 import ID3NoHeaderError

from config import get_config
from database import Database

logger = logging.getLogger(__name__)


@dataclass
class TrackMetadata:
    """Track metadata extracted from audio file"""
    title: str
    artist: str
    album: str
    duration: float
    genre: str
    year: int
    file_hash: str


class MusicLibrary:
    """Manages the music library and track metadata"""

    def __init__(self, database: Database):
        self.database = database
        self.config = get_config()

    def compute_file_hash(self, file_path: str) -> str:
        """
        Compute SHA256 hash of audio file

        Args:
            file_path: Path to audio file

        Returns:
            Hexadecimal hash string
        """
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    def extract_metadata(self, file_path: str) -> Optional[TrackMetadata]:
        """
        Extract metadata from audio file using mutagen

        Args:
            file_path: Path to audio file

        Returns:
            TrackMetadata object or None if extraction fails
        """
        try:
            audio_file = File(file_path)
            if audio_file is None:
                logger.warning(f"Could not read file: {file_path}")
                return None

            # Extract common fields
            title = ""
            artist = ""
            album = ""
            genre = ""
            year = None
            duration = audio_file.info.length if hasattr(audio_file.info, 'length') else 0

            # Try different tag formats
            if hasattr(audio_file, 'tags') and audio_file.tags:
                tags = audio_file.tags

                # Try common tag keys
                title = str(tags.get('TIT2', tags.get('TITLE', ['']))[0])
                artist = str(tags.get('TPE1', tags.get('ARTIST', ['']))[0])
                album = str(tags.get('TALB', tags.get('ALBUM', ['']))[0])
                genre = str(tags.get('TCON', tags.get('GENRE', ['']))[0])

                # Year
                year_tag = tags.get('TDRC', tags.get('DATE', tags.get('YEAR', None)))
                if year_tag:
                    try:
                        year_str = str(year_tag[0])
                        year = int(year_str[:4]) if year_str[:4].isdigit() else None
                    except (ValueError, IndexError):
                        year = None

            # Fallback to easy tags if available
            if not title and hasattr(audio_file, 'get'):
                title = audio_file.get('title', [''])[0]
                artist = audio_file.get('artist', [''])[0]
                album = audio_file.get('album', [''])[0]

            # Compute file hash
            file_hash = self.compute_file_hash(file_path)

            return TrackMetadata(
                title=title or Path(file_path).stem,
                artist=artist or "Unknown Artist",
                album=album or "",
                duration=duration,
                genre=genre or "",
                year=year or 0,
                file_hash=file_hash
            )

        except ID3NoHeaderError:
            logger.warning(f"No ID3 header in file: {file_path}")
            # Return basic metadata from filename
            return TrackMetadata(
                title=Path(file_path).stem,
                artist="Unknown Artist",
                album="",
                duration=0,
                genre="",
                year=0,
                file_hash=self.compute_file_hash(file_path)
            )
        except Exception as e:
            logger.error(f"Error extracting metadata from {file_path}: {e}")
            return None

    def add_track(self, file_path: str, metadata: TrackMetadata = None) -> Optional[int]:
        """
        Add a track to the database

        Args:
            file_path: Path to audio file
            metadata: TrackMetadata object (if None, will extract)

        Returns:
            Track ID or None if addition failed
        """
        if metadata is None:
            metadata = self.extract_metadata(file_path)
            if metadata is None:
                return None

        # Check if track already exists
        with self.database.connect() as conn:
            cursor = conn.execute(
                "SELECT id FROM tracks WHERE file_path = ?",
                (file_path,)
            )
            result = cursor.fetchone()
            if result:
                logger.debug(f"Track already exists: {file_path}")
                return result[0]

            # Insert new track
            cursor = conn.execute(
                """
                INSERT INTO tracks
                (file_path, file_hash, title, artist, album, duration_seconds, genre, year, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    file_path,
                    metadata.file_hash,
                    metadata.title,
                    metadata.artist,
                    metadata.album,
                    metadata.duration,
                    metadata.genre,
                    metadata.year
                )
            )
            track_id = cursor.lastrowid
            logger.info(f"Added track: {metadata.title} by {metadata.artist}")
            return track_id

    def update_track_metadata(self, track_id: int, metadata: TrackMetadata):
        """
        Update track metadata in database

        Args:
            track_id: Track ID
            metadata: New metadata
        """
        with self.database.transaction() as conn:
            conn.execute(
                """
                UPDATE tracks
                SET file_hash = ?, title = ?, artist = ?, album = ?,
                    duration_seconds = ?, genre = ?, year = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    metadata.file_hash,
                    metadata.title,
                    metadata.artist,
                    metadata.album,
                    metadata.duration,
                    metadata.genre,
                    metadata.year,
                    track_id
                )
            )
        logger.info(f"Updated metadata for track {track_id}")

    def get_track_by_path(self, file_path: str) -> Optional[Dict]:
        """
        Get track information by file path

        Args:
            file_path: Path to audio file

        Returns:
            Dictionary with track info or None
        """
        with self.database.connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM tracks WHERE file_path = ?",
                (file_path,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def get_track_by_id(self, track_id: int) -> Optional[Dict]:
        """
        Get track information by ID

        Args:
            track_id: Track ID

        Returns:
            Dictionary with track info or None
        """
        with self.database.connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM tracks WHERE id = ?",
                (track_id,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def scan_directory(self, directory: str, recursive: bool = True) -> Dict[str, int]:
        """
        Scan a directory for audio files and add them to the library

        Args:
            directory: Directory to scan
            recursive: Whether to scan subdirectories

        Returns:
            Dictionary with scan statistics
        """
        logger.info(f"Scanning directory: {directory}")

        stats = {
            'scanned': 0,
            'added': 0,
            'updated': 0,
            'failed': 0
        }

        dir_path = Path(directory)
        if not dir_path.exists():
            logger.error(f"Directory not found: {directory}")
            return stats

        # Audio file extensions
        audio_extensions = {'.mp3', '.m4a', '.flac', '.ogg', '.wav', '.wma', '.aac'}

        # Find audio files
        if recursive:
            audio_files = list(dir_path.rglob('*'))
        else:
            audio_files = list(dir_path.glob('*'))

        audio_files = [f for f in audio_files if f.suffix.lower() in audio_extensions]

        logger.info(f"Found {len(audio_files)} audio files")

        for audio_file in audio_files:
            stats['scanned'] += 1

            try:
                file_path = str(audio_file)
                metadata = self.extract_metadata(file_path)

                if metadata is None:
                    stats['failed'] += 1
                    continue

                # Check if track exists
                existing = self.get_track_by_path(file_path)

                if existing:
                    # Update if hash changed
                    if existing['file_hash'] != metadata.file_hash:
                        self.update_track_metadata(existing['id'], metadata)
                        stats['updated'] += 1
                else:
                    # Add new track
                    self.add_track(file_path, metadata)
                    stats['added'] += 1

            except Exception as e:
                logger.error(f"Error processing {audio_file}: {e}")
                stats['failed'] += 1

        logger.info(f"Scan complete: {stats}")
        return stats

    def verify_track_exists(self, track_id: int) -> bool:
        """
        Verify that a track's file still exists

        Args:
            track_id: Track ID

        Returns:
            True if file exists, False otherwise
        """
        track = self.get_track_by_id(track_id)
        if not track:
            return False

        return Path(track['file_path']).exists()

    def get_all_tracks(self) -> List[Dict]:
        """
        Get all tracks from the library

        Returns:
            List of track dictionaries
        """
        with self.database.connect() as conn:
            cursor = conn.execute("SELECT * FROM tracks")
            return [dict(row) for row in cursor.fetchall()]

    def get_tracks_by_artist(self, artist: str) -> List[Dict]:
        """
        Get all tracks by a specific artist

        Args:
            artist: Artist name

        Returns:
            List of track dictionaries
        """
        with self.database.connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM tracks WHERE artist = ?",
                (artist,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_tracks_by_genre(self, genre: str) -> List[Dict]:
        """
        Get all tracks in a specific genre

        Args:
            genre: Genre name

        Returns:
            List of track dictionaries
        """
        with self.database.connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM tracks WHERE genre = ?",
                (genre,)
            )
            return [dict(row) for row in cursor.fetchall()]
