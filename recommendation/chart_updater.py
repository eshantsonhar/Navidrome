"""
Chart updater
Scrapes and maintains chart playlists from various sources (YouTube Music, Spotify)
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
import json
import os

import config
from database import Database

logger = logging.getLogger(__name__)


@dataclass
class ChartEntry:
    """Represents a single chart entry"""
    title: str
    artist: str
    rank: int
    video_id: str = ""
    spotify_uri: str = ""


class ChartUpdater:
    """Updates chart playlists from various sources (YouTube Music, Spotify)"""

    def __init__(self, database: Database):
        self.database = database
        self.config = config.get_config()

    def refresh_chart(self) -> Dict[str, int]:
        """
        Refresh the chart from configured source

        Returns:
            Dictionary with refresh statistics
        """
        logger.info("Refreshing chart")

        stats = {
            'retrieved': 0,
            'added': 0,
            'updated': 0,
            'failed': 0
        }

        try:
            # Detect source type from playlist_id
            playlist_id = self.config.chart.playlist_id

            if playlist_id.startswith('spotify:'):
                # Spotify playlist
                entries = self._fetch_chart_from_spotify(playlist_id)
                source_name = "Spotify Chart"
                source_type = "spotify"
            else:
                # YouTube Music playlist (default)
                entries = self._fetch_chart_from_youtube_music()
                source_name = "YouTube Music Top 100 English"
                source_type = "youtube_music"

            if not entries:
                logger.error("No chart entries retrieved")
                return stats

            stats['retrieved'] = len(entries)

            # Register chart source
            self._register_chart_source(source_name, source_type, playlist_id)

            # Process entries
            for entry in entries:
                try:
                    self._process_chart_entry(entry, source_name)
                    stats['added'] += 1
                except Exception as e:
                    logger.error(f"Error processing chart entry {entry.title}: {e}")
                    stats['failed'] += 1

            # Update last refresh time
            self._update_last_refresh_time(source_name)

            # Save snapshot to persistent storage
            self._save_snapshot(entries, source_name, source_type)

            logger.info(f"Chart refresh complete: {stats}")
            return stats

        except Exception as e:
            logger.error(f"Chart refresh failed: {e}")
            stats['failed'] = stats['retrieved']
            return stats

    def _fetch_chart_from_youtube_music(self) -> List[ChartEntry]:
        """
        Fetch chart entries from YouTube Music

        Returns:
            List of ChartEntry objects
        """
        try:
            # Try to use ytmusicapi from spotdl-env
            import sys
            spotdl_env = Path(self.config.paths.project_dir) / "spotdl-env"
            if spotdl_env.exists():
                # Add spotdl-env to path
                sys.path.insert(0, str(spotdl_env / "lib" / "python3.12" / "site-packages"))

            import ytmusicapi

            # Initialize YTMusic (no auth needed for public playlists)
            ytmusic = ytmusicapi.YTMusic()

            # Get playlist
            playlist_id = self.config.chart.playlist_id
            playlist = ytmusic.get_playlist(playlist_id)

            if not playlist or 'tracks' not in playlist:
                logger.error(f"Could not retrieve playlist {playlist_id}")
                return []

            entries = []
            for idx, track in enumerate(playlist['tracks'][:self.config.chart.max_tracks], 1):
                title = track.get('title', '')
                artists = track.get('artists', [])
                artist = artists[0]['name'] if artists else 'Unknown'
                video_id = track.get('videoId', '')

                entries.append(ChartEntry(
                    title=title,
                    artist=artist,
                    rank=idx,
                    video_id=video_id
                ))

            logger.info(f"Retrieved {len(entries)} entries from YouTube Music")
            return entries

        except ImportError:
            logger.error("ytmusicapi not available, cannot fetch chart")
            return []
        except Exception as e:
            logger.error(f"Error fetching chart from YouTube Music: {e}")
            return []

    def _fetch_chart_from_spotify(self, playlist_id: str) -> List[ChartEntry]:
        """
        Fetch chart entries from Spotify using SpotifyScraper

        Args:
            playlist_id: Spotify playlist ID (with or without spotify: prefix)

        Returns:
            List of ChartEntry objects
        """
        try:
            from spotify_scraper import SpotifyClient

            # Remove spotify: prefix if present
            clean_id = playlist_id.replace('spotify:', '')

            with SpotifyClient() as client:
                playlist = client.get_playlist(clean_id, max_tracks=self.config.chart.max_tracks)

                if not playlist:
                    logger.error(f"Could not retrieve playlist {clean_id}")
                    return []

                entries = []
                for idx, entry in enumerate(playlist.tracks[:self.config.chart.max_tracks], 1):
                    title = entry.track.name
                    artists = entry.track.artists
                    artist = artists[0].name if artists else 'Unknown'
                    spotify_uri = entry.track.uri

                    entries.append(ChartEntry(
                        title=title,
                        artist=artist,
                        rank=idx,
                        spotify_uri=spotify_uri
                    ))

                logger.info(f"Retrieved {len(entries)} entries from Spotify: {playlist.name}")
                return entries

        except ImportError:
            logger.error("spotifyscraper not available, cannot fetch chart")
            return []
        except Exception as e:
            logger.error(f"Error fetching chart from Spotify: {e}")
            return []

    def _register_chart_source(self, name: str, source_type: str, source_id: str):
        """Register chart source in database"""
        with self.database.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO chart_sources
                (name, source_type, source_id, refresh_interval_hours, created_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (name, source_type, source_id, self.config.chart.refresh_interval_hours)
            )

    def _process_chart_entry(self, entry: ChartEntry, source_name: str):
        """
        Process a single chart entry

        Args:
            entry: ChartEntry to process
            source_name: Name of the chart source
        """
        with self.database.connect() as conn:
            # Get chart source ID
            cursor = conn.execute(
                "SELECT id FROM chart_sources WHERE name = ?",
                (source_name,)
            )
            result = cursor.fetchone()
            if not result:
                raise ValueError(f"Chart source {source_name} not registered")
            chart_source_id = result[0]

            # Check if track already exists in library
            cursor = conn.execute(
                "SELECT id FROM tracks WHERE title = ? AND artist = ?",
                (entry.title, entry.artist)
            )
            track_result = cursor.fetchone()
            track_id = track_result[0] if track_result else None

            # Determine source type from playlist_id
            if self.config.chart.playlist_id.startswith('spotify:'):
                source_type = 'spotify'
                source_id_field = entry.spotify_uri if entry.spotify_uri else self.config.chart.playlist_id
            else:
                source_type = 'youtube_music'
                source_id_field = self.config.chart.playlist_id

            # If track doesn't exist, create a discovery candidate
            if not track_id:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO discovery_candidates
                    (title, artist, source_type, source_id, source_rank, first_seen_at, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (entry.title, entry.artist, source_type, source_id_field, entry.rank)
                )
            else:
                # Track exists, update discovery candidate
                conn.execute(
                    """
                    INSERT OR REPLACE INTO discovery_candidates
                    (title, artist, source_type, source_id, source_rank, track_id, is_available,
                     first_seen_at, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1,
                     COALESCE((SELECT first_seen_at FROM discovery_candidates
                               WHERE title = ? AND artist = ?), CURRENT_TIMESTAMP),
                     CURRENT_TIMESTAMP)
                    """,
                    (entry.title, entry.artist, source_type, source_id_field, entry.rank,
                     track_id, entry.title, entry.artist)
                )

            # Add to chart snapshot
            if track_id:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO chart_snapshots
                    (chart_source_id, snapshot_time, track_id, rank)
                    VALUES (?, CURRENT_TIMESTAMP, ?, ?)
                    """,
                    (chart_source_id, track_id, entry.rank)
                )

    def _update_last_refresh_time(self, source_name: str):
        """Update last refresh time in database"""
        with self.database.transaction() as conn:
            conn.execute(
                """
                UPDATE chart_sources
                SET last_refreshed_at = CURRENT_TIMESTAMP, last_refresh_successful = 1
                WHERE name = ?
                """,
                (source_name,)
            )

    def get_current_chart(self) -> List[Dict]:
        """
        Get current chart snapshot

        Returns:
            List of chart entries with track info
        """
        # Determine source name based on playlist_id
        if self.config.chart.playlist_id.startswith('spotify:'):
            source_name = "Spotify Chart"
        else:
            source_name = "YouTube Music Top 100 English"

        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                SELECT cs.rank, t.title, t.artist, t.file_path
                FROM chart_snapshots cs
                JOIN tracks t ON cs.track_id = t.id
                JOIN chart_sources s ON cs.chart_source_id = s.id
                WHERE s.name = ?
                AND cs.snapshot_time = (
                    SELECT MAX(snapshot_time) FROM chart_snapshots
                    WHERE chart_source_id = s.id
                )
                ORDER BY cs.rank ASC
                """,
                (source_name,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def should_refresh(self) -> bool:
        """
        Check if chart should be refreshed based on interval

        Returns:
            True if refresh is needed, False otherwise
        """
        # Determine source name based on playlist_id
        if self.config.chart.playlist_id.startswith('spotify:'):
            source_name = "Spotify Chart"
        else:
            source_name = "YouTube Music Top 100 English"

        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                SELECT last_refreshed_at, refresh_interval_hours
                FROM chart_sources
                WHERE name = ?
                """,
                (source_name,)
            )
            result = cursor.fetchone()

            if not result or not result[0]:
                return True  # Never refreshed

            last_refreshed = datetime.fromisoformat(result[0])
            interval_hours = result[1] or self.config.chart.refresh_interval_hours

            time_since = (datetime.now() - last_refreshed).total_seconds() / 3600
            return time_since >= interval_hours

    def _save_snapshot(self, entries: List[ChartEntry], source_name: str, source_type: str):
        """Save chart snapshot to persistent storage for inspection"""
        try:
            # Determine snapshot directory
            snapshots_dir = Path(self.config.paths.project_dir) / "data" / "snapshots"
            snapshots_dir.mkdir(parents=True, exist_ok=True)

            # Create filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{source_type}_chart_{timestamp}.json"
            snapshot_path = snapshots_dir / filename

            # Prepare snapshot data
            snapshot_data = {
                "source_name": source_name,
                "source_type": source_type,
                "playlist_id": self.config.chart.playlist_id,
                "track_count": len(entries),
                "extracted_at": datetime.now().isoformat(),
                "entries": [
                    {
                        "rank": entry.rank,
                        "title": entry.title,
                        "artist": entry.artist,
                        "spotify_uri": entry.spotify_uri if entry.spotify_uri else None,
                        "video_id": entry.video_id if entry.video_id else None
                    }
                    for entry in entries
                ]
            }

            # Write snapshot
            with open(snapshot_path, 'w', encoding='utf-8') as f:
                json.dump(snapshot_data, f, indent=2, ensure_ascii=False)

            logger.info(f"Chart snapshot saved to {snapshot_path}")

            # Keep only last 10 snapshots to avoid disk space issues
            self._cleanup_old_snapshots(snapshots_dir, source_type, keep=10)

        except Exception as e:
            logger.error(f"Error saving chart snapshot: {e}")

    def _cleanup_old_snapshots(self, snapshots_dir: Path, source_type: str, keep: int = 10):
        """Remove old snapshots, keeping only the most recent N"""
        try:
            # Get all snapshots for this source type
            pattern = f"{source_type}_chart_*.json"
            snapshots = sorted(snapshots_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

            # Remove old ones
            for old_snapshot in snapshots[keep:]:
                old_snapshot.unlink()
                logger.debug(f"Removed old snapshot: {old_snapshot}")

        except Exception as e:
            logger.error(f"Error cleaning up old snapshots: {e}")
