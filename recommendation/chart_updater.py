"""
YouTube Music Top 100 chart updater
Scrapes and maintains the English Top 100 chart
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime
from dataclasses import dataclass

from config import get_config
from database import Database

logger = logging.getLogger(__name__)


@dataclass
class ChartEntry:
    """Represents a single chart entry"""
    title: str
    artist: str
    rank: int
    video_id: str = ""


class ChartUpdater:
    """Updates Top 100 chart from YouTube Music"""

    def __init__(self, database: Database):
        self.database = database
        self.config = get_config()

    def refresh_chart(self) -> Dict[str, int]:
        """
        Refresh the Top 100 chart from YouTube Music

        Returns:
            Dictionary with refresh statistics
        """
        logger.info("Refreshing Top 100 chart")

        stats = {
            'retrieved': 0,
            'added': 0,
            'updated': 0,
            'failed': 0
        }

        try:
            # Get chart entries from YouTube Music
            entries = self._fetch_chart_from_youtube_music()

            if not entries:
                logger.error("No chart entries retrieved")
                return stats

            stats['retrieved'] = len(entries)

            # Register chart source
            self._register_chart_source()

            # Process entries
            for entry in entries:
                try:
                    self._process_chart_entry(entry)
                    stats['added'] += 1
                except Exception as e:
                    logger.error(f"Error processing chart entry {entry.title}: {e}")
                    stats['failed'] += 1

            # Update last refresh time
            self._update_last_refresh_time()

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

    def _register_chart_source(self):
        """Register chart source in database"""
        with self.database.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO chart_sources
                (name, source_type, source_id, refresh_interval_hours, created_at)
                VALUES ('YouTube Music Top 100 English', 'youtube_music', ?, ?, CURRENT_TIMESTAMP)
                """,
                (self.config.chart.playlist_id, self.config.chart.refresh_interval_hours)
            )

    def _process_chart_entry(self, entry: ChartEntry):
        """
        Process a single chart entry

        Args:
            entry: ChartEntry to process
        """
        with self.database.connect() as conn:
            # Get chart source ID
            cursor = conn.execute(
                "SELECT id FROM chart_sources WHERE name = 'YouTube Music Top 100 English'"
            )
            result = cursor.fetchone()
            if not result:
                raise ValueError("Chart source not registered")
            chart_source_id = result[0]

            # Check if track already exists in library
            cursor = conn.execute(
                "SELECT id FROM tracks WHERE title = ? AND artist = ?",
                (entry.title, entry.artist)
            )
            track_result = cursor.fetchone()
            track_id = track_result[0] if track_result else None

            # If track doesn't exist, create a discovery candidate
            if not track_id:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO discovery_candidates
                    (title, artist, source_type, source_id, source_rank, first_seen_at, last_seen_at)
                    VALUES (?, ?, 'youtube_music', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    (entry.title, entry.artist, self.config.chart.playlist_id, entry.rank)
                )
            else:
                # Track exists, update discovery candidate
                conn.execute(
                    """
                    INSERT OR REPLACE INTO discovery_candidates
                    (title, artist, source_type, source_id, source_rank, track_id, is_available,
                     first_seen_at, last_seen_at)
                    VALUES (?, ?, 'youtube_music', ?, ?, ?, 1,
                     COALESCE((SELECT first_seen_at FROM discovery_candidates
                               WHERE title = ? AND artist = ?), CURRENT_TIMESTAMP),
                     CURRENT_TIMESTAMP)
                    """,
                    (entry.title, entry.artist, self.config.chart.playlist_id, entry.rank,
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

    def _update_last_refresh_time(self):
        """Update last refresh time in database"""
        with self.database.transaction() as conn:
            conn.execute(
                """
                UPDATE chart_sources
                SET last_refreshed_at = CURRENT_TIMESTAMP, last_refresh_successful = 1
                WHERE name = 'YouTube Music Top 100 English'
                """
            )

    def get_current_chart(self) -> List[Dict]:
        """
        Get current chart snapshot

        Returns:
            List of chart entries with track info
        """
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                SELECT cs.rank, t.title, t.artist, t.file_path
                FROM chart_snapshots cs
                JOIN tracks t ON cs.track_id = t.id
                JOIN chart_sources s ON cs.chart_source_id = s.id
                WHERE s.name = 'YouTube Music Top 100 English'
                AND cs.snapshot_time = (
                    SELECT MAX(snapshot_time) FROM chart_snapshots
                    WHERE chart_source_id = s.id
                )
                ORDER BY cs.rank ASC
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def should_refresh(self) -> bool:
        """
        Check if chart should be refreshed based on interval

        Returns:
            True if refresh is needed, False otherwise
        """
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                SELECT last_refreshed_at, refresh_interval_hours
                FROM chart_sources
                WHERE name = 'YouTube Music Top 100 English'
                """
            )
            result = cursor.fetchone()

            if not result or not result[0]:
                return True  # Never refreshed

            last_refreshed = datetime.fromisoformat(result[0])
            interval_hours = result[1] or self.config.chart.refresh_interval_hours

            time_since = (datetime.now() - last_refreshed).total_seconds() / 3600
            return time_since >= interval_hours
