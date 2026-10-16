"""
Feedback system
Handles ratings, favorites, and listening history
Implements feedback hierarchy and conflict resolution
"""

import logging
from typing import Optional, Dict, List
from datetime import datetime, timezone
from enum import Enum

import config
from database import Database

logger = logging.getLogger(__name__)


class FeedbackType(Enum):
    """Types of feedback events"""
    RATING = "rating"
    FAVORITE = "favorite"
    DISLIKE = "dislike"
    PLAYLIST_ADD = "playlist_add"
    PLAYLIST_REMOVE = "playlist_remove"
    SKIP = "skip"
    COMPLETE = "complete"


class FeedbackState(Enum):
    """Current feedback state of a track"""
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class FeedbackSystem:
    """Manages feedback events and current feedback state"""

    def __init__(self, database: Database):
        self.database = database
        self.config = config.get_config()

    def record_feedback_event(
        self,
        track_id: int,
        event_type: FeedbackType,
        event_value: str = None,
        source: str = "system"
    ):
        """
        Record a feedback event

        Args:
            track_id: Track ID
            event_type: Type of feedback event
            event_value: Event value (rating number, boolean string, etc.)
            source: Source of feedback (navidrome, substreamer, etc.)
        """
        with self.database.transaction() as conn:
            conn.execute(
                """
                INSERT INTO feedback_events
                (track_id, event_type, event_value, source, event_time)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (track_id, event_type.value, event_value, source)
            )

        logger.info(f"Recorded feedback: {event_type.value} for track {track_id} from {source}")

        # Update current feedback state
        self.update_current_feedback(track_id)

    def update_current_feedback(self, track_id: int):
        """
        Update the current feedback state for a track based on all events

        Args:
            track_id: Track ID
        """
        with self.database.connect() as conn:
            # Get all feedback events for this track
            cursor = conn.execute(
                """
                SELECT event_type, event_value, event_time
                FROM feedback_events
                WHERE track_id = ?
                ORDER BY event_time DESC
                """,
                (track_id,)
            )
            events = cursor.fetchall()

            if not events:
                # No feedback events
                conn.execute(
                    """
                    INSERT OR REPLACE INTO current_feedback
                    (track_id, feedback_state)
                    VALUES (?, 'unknown')
                    """,
                    (track_id,)
                )
                return

            # Determine current state
            current_rating = None
            is_favorite = False
            is_disliked = False
            in_primary = False
            in_secondary = False
            last_positive = None
            last_negative = None

            for event_type, event_value, event_time in events:
                if event_type == FeedbackType.RATING.value:
                    try:
                        rating = int(event_value)
                        current_rating = rating
                        if rating >= self.config.feedback.positive_rating_min:
                            last_positive = event_time
                        elif rating <= self.config.feedback.negative_rating:
                            last_negative = event_time
                    except ValueError:
                        pass

                elif event_type == FeedbackType.FAVORITE.value:
                    if event_value and event_value.lower() in ('true', '1', 'yes'):
                        is_favorite = True
                        last_positive = event_time
                    else:
                        is_favorite = False

                elif event_type == FeedbackType.DISLIKE.value:
                    if event_value and event_value.lower() in ('true', '1', 'yes'):
                        is_disliked = True
                        last_negative = event_time
                    else:
                        is_disliked = False

                elif event_type == FeedbackType.PLAYLIST_ADD.value:
                    if event_value == "Bored.m3u":
                        in_primary = True
                        last_positive = event_time
                    elif event_value == "the better playlist.m3u":
                        in_secondary = True
                        last_positive = event_time

                elif event_type == FeedbackType.PLAYLIST_REMOVE.value:
                    if event_value == "Bored.m3u":
                        in_primary = False
                    elif event_value == "the better playlist.m3u":
                        in_secondary = False

            # Determine feedback state with conflict resolution
            # Current explicit negative rating overrides playlist membership
            if current_rating and current_rating <= self.config.feedback.negative_rating:
                feedback_state = FeedbackState.NEGATIVE
            elif is_disliked:
                feedback_state = FeedbackState.NEGATIVE
            elif is_favorite or (current_rating and current_rating >= self.config.feedback.positive_rating_min):
                feedback_state = FeedbackState.POSITIVE
            elif in_primary or in_secondary:
                feedback_state = FeedbackState.POSITIVE
            else:
                feedback_state = FeedbackState.NEUTRAL

            # Update current feedback
            conn.execute(
                """
                INSERT OR REPLACE INTO current_feedback
                (track_id, current_rating, is_favorite, is_disliked,
                 in_seed_playlist_primary, in_seed_playlist_secondary,
                 last_positive_feedback_at, last_negative_feedback_at, feedback_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    track_id,
                    current_rating,
                    is_favorite,
                    is_disliked,
                    in_primary,
                    in_secondary,
                    last_positive,
                    last_negative,
                    feedback_state.value
                )
            )

    def get_current_feedback(self, track_id: int) -> Optional[Dict]:
        """
        Get current feedback state for a track

        Args:
            track_id: Track ID

        Returns:
            Dictionary with feedback state or None
        """
        with self.database.connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM current_feedback WHERE track_id = ?",
                (track_id,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def is_positive(self, track_id: int) -> bool:
        """
        Check if track has positive feedback

        Args:
            track_id: Track ID

        Returns:
            True if positive, False otherwise
        """
        feedback = self.get_current_feedback(track_id)
        if not feedback:
            return False
        return feedback['feedback_state'] == FeedbackState.POSITIVE.value

    def is_negative(self, track_id: int) -> bool:
        """
        Check if track has negative feedback

        Args:
            track_id: Track ID

        Returns:
            True if negative, False otherwise
        """
        feedback = self.get_current_feedback(track_id)
        if not feedback:
            return False
        return feedback['feedback_state'] == FeedbackState.NEGATIVE.value

    def record_rating(self, track_id: int, rating: int, source: str = "navidrome"):
        """
        Record a rating for a track

        Args:
            track_id: Track ID
            rating: Rating value (1-5)
            source: Source of rating
        """
        if not 1 <= rating <= 5:
            logger.warning(f"Invalid rating {rating} for track {track_id}")
            return

        self.record_feedback_event(
            track_id,
            FeedbackType.RATING,
            str(rating),
            source
        )

    def record_favorite(self, track_id: int, is_favorite: bool, source: str = "navidrome"):
        """
        Record a favorite/unfavorite event

        Args:
            track_id: Track ID
            is_favorite: Whether track is favorited
            source: Source of event
        """
        self.record_feedback_event(
            track_id,
            FeedbackType.FAVORITE,
            str(is_favorite),
            source
        )

    def record_dislike(self, track_id: int, is_disliked: bool, source: str = "navidrome"):
        """
        Record a dislike/undislike event

        Args:
            track_id: Track ID
            is_disliked: Whether track is disliked
            source: Source of event
        """
        self.record_feedback_event(
            track_id,
            FeedbackType.DISLIKE,
            str(is_disliked),
            source
        )

    def record_playlist_add(self, track_id: int, playlist_name: str):
        """
        Record addition to seed playlist

        Args:
            track_id: Track ID
            playlist_name: Name of playlist
        """
        self.record_feedback_event(
            track_id,
            FeedbackType.PLAYLIST_ADD,
            playlist_name,
            "seed_playlist"
        )

    def record_playlist_remove(self, track_id: int, playlist_name: str):
        """
        Record removal from seed playlist

        Args:
            track_id: Track ID
            playlist_name: Name of playlist
        """
        self.record_feedback_event(
            track_id,
            FeedbackType.PLAYLIST_REMOVE,
            playlist_name,
            "seed_playlist"
        )

    def record_listening_event(
        self,
        track_id: int,
        event_type: FeedbackType,
        play_duration: float = 0,
        track_duration: float = 0,
        source: str = "navidrome"
    ):
        """
        Record a listening event (play, skip, complete)

        Args:
            track_id: Track ID
            event_type: Type of event
            play_duration: Duration of play in seconds
            track_duration: Total track duration in seconds
            source: Source of event
        """
        completion_percent = 0
        if track_duration > 0:
            completion_percent = (play_duration / track_duration) * 100

        with self.database.transaction() as conn:
            conn.execute(
                """
                INSERT INTO listening_events
                (track_id, event_type, play_duration_seconds, track_duration_seconds,
                 completion_percent, source, event_time)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (track_id, event_type.value, play_duration, track_duration, completion_percent, source)
            )

        logger.info(f"Recorded listening event: {event_type.value} for track {track_id}")

    def get_recent_listening_events(self, track_id: int, limit: int = 10) -> List[Dict]:
        """
        Get recent listening events for a track

        Args:
            track_id: Track ID
            limit: Maximum number of events

        Returns:
            List of event dictionaries
        """
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM listening_events
                WHERE track_id = ?
                ORDER BY event_time DESC
                LIMIT ?
                """,
                (track_id, limit)
            )
            return [dict(row) for row in cursor.fetchall()]

    def count_recent_skips(self, track_id: int, hours: int = 24) -> int:
        """
        Count recent skip events for a track

        Args:
            track_id: Track ID
            hours: Time window in hours

        Returns:
            Number of skip events
        """
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                SELECT COUNT(*) FROM listening_events
                WHERE track_id = ? AND event_type = 'skip'
                AND event_time >= datetime('now', '-' || ? || ' hours')
                """,
                (track_id, hours)
            )
            result = cursor.fetchone()
            return result[0] if result else 0
