"""
Cooldown and repeat prevention engine
Implements seven-day repeat prevention with proper timezone handling
"""

import logging
from typing import Optional, Dict, List
from datetime import datetime, timedelta, timezone
from enum import Enum

from pytz import timezone as tz
import config
from database import Database

logger = logging.getLogger(__name__)


class ExclusionType(Enum):
    """Types of exclusions"""
    NO_FEEDBACK = "no_feedback"
    NEGATIVE_FEEDBACK = "negative_feedback"
    MANUAL = "manual"


class CooldownEngine:
    """Manages repeat prevention and cooldowns"""

    def __init__(self, database: Database):
        self.database = database
        self.config = config.get_config()
        self.timezone = tz(self.config.recommendation.timezone)

    def get_timezone_aware_now(self) -> datetime:
        """Get current time in configured timezone"""
        return datetime.now(self.timezone)

    def add_exclusion(
        self,
        track_id: int,
        exclusion_type: ExclusionType,
        reason: str,
        preference_persistent: bool = False,
        duration_days: int = None
    ):
        """
        Add an exclusion for a track

        Args:
            track_id: Track ID
            exclusion_type: Type of exclusion
            reason: Human-readable reason
            preference_persistent: Whether negative preference persists after block
            duration_days: Duration in days (uses default if None)
        """
        if duration_days is None:
            duration_days = self.config.recommendation.repeat_cooldown_days

        blocked_until = self.get_timezone_aware_now() + timedelta(days=duration_days)
        # Store as UTC for consistent SQL comparisons
        blocked_until_utc = blocked_until.astimezone(timezone.utc)

        with self.database.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO exclusions
                (track_id, exclusion_type, blocked_until, reason, preference_persistent, created_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (track_id, exclusion_type.value, blocked_until_utc.isoformat(), reason, preference_persistent)
            )

        logger.info(f"Added {exclusion_type.value} exclusion for track {track_id} until {blocked_until}")

    def remove_exclusion(self, track_id: int):
        """
        Remove exclusion for a track

        Args:
            track_id: Track ID
        """
        with self.database.transaction() as conn:
            conn.execute("DELETE FROM exclusions WHERE track_id = ?", (track_id,))
        logger.info(f"Removed exclusion for track {track_id}")

    def get_exclusion(self, track_id: int) -> Optional[Dict]:
        """
        Get current exclusion for a track

        Args:
            track_id: Track ID

        Returns:
            Exclusion dictionary or None
        """
        with self.database.connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM exclusions WHERE track_id = ?",
                (track_id,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def is_excluded(self, track_id: int) -> bool:
        """
        Check if track is currently excluded

        Args:
            track_id: Track ID

        Returns:
            True if excluded, False otherwise
        """
        exclusion = self.get_exclusion(track_id)
        if not exclusion:
            return False

        # Parse blocked_until - handle both legacy timezone-aware and new UTC formats
        blocked_until = datetime.fromisoformat(exclusion['blocked_until'])
        if blocked_until.tzinfo is None:
            # Legacy naive timestamp - assume it's UTC (from before the fix)
            blocked_until = blocked_until.replace(tzinfo=timezone.utc)
        else:
            # Timezone-aware timestamp - convert to UTC
            blocked_until = blocked_until.astimezone(timezone.utc)

        now = self.get_timezone_aware_now().astimezone(timezone.utc)

        if now < blocked_until:
            return True

        # Exclusion has expired, remove it
        logger.info(f"Exclusion expired for track {track_id}, removing")
        self.remove_exclusion(track_id)
        return False

    def is_eligible_for_recommendation(self, track_id: int) -> bool:
        """
        Check if track is eligible for recommendation

        Args:
            track_id: Track ID

        Returns:
            True if eligible, False otherwise
        """
        # Check exclusion
        if self.is_excluded(track_id):
            return False

        # Check feedback state
        from .feedback import FeedbackSystem
        feedback = FeedbackSystem(self.database)
        if feedback.is_negative(track_id):
            # Negative feedback should always exclude
            return False

        return True

    def add_no_feedback_exclusion(self, track_id: int):
        """
        Add exclusion for track recommended without feedback

        Args:
            track_id: Track ID
        """
        self.add_exclusion(
            track_id,
            ExclusionType.NO_FEEDBACK,
            "Recommended without explicit feedback",
            preference_persistent=False
        )

    def add_negative_feedback_exclusion(self, track_id: int, reason: str = "Negative feedback"):
        """
        Add exclusion for track with negative feedback

        Args:
            track_id: Track ID
            reason: Reason for exclusion
        """
        self.add_exclusion(
            track_id,
            ExclusionType.NEGATIVE_FEEDBACK,
            reason,
            preference_persistent=True  # Negative preference persists
        )

    def override_exclusion(self, track_id: int, reason: str = "Positive feedback override"):
        """
        Override exclusion for track with positive feedback

        Args:
            track_id: Track ID
            reason: Reason for override
        """
        exclusion = self.get_exclusion(track_id)
        if exclusion:
            logger.info(f"Overriding exclusion for track {track_id}: {reason}")
            self.remove_exclusion(track_id)

    def record_recommendation(self, track_id: int):
        """
        Record that a track was recommended

        Args:
            track_id: Track ID
        """
        now = self.get_timezone_aware_now()
        now_utc = now.astimezone(timezone.utc)
        blocked_until_utc = now_utc + timedelta(days=self.config.recommendation.repeat_cooldown_days)

        with self.database.transaction() as conn:
            # Update last_recommended_at in exclusions table
            conn.execute(
                """
                INSERT OR REPLACE INTO exclusions
                (track_id, exclusion_type, last_recommended_at, blocked_until, reason, created_at)
                VALUES (?, COALESCE((SELECT exclusion_type FROM exclusions WHERE track_id = ?), 'no_feedback'),
                        ?, COALESCE((SELECT blocked_until FROM exclusions WHERE track_id = ?), ?),
                        COALESCE((SELECT reason FROM exclusions WHERE track_id = ?), 'Recommended'),
                        COALESCE((SELECT created_at FROM exclusions WHERE track_id = ?), CURRENT_TIMESTAMP))
                """,
                (track_id, track_id, now_utc.isoformat(), track_id,
                 blocked_until_utc.isoformat(), track_id, track_id)
            )

        logger.info(f"Recorded recommendation for track {track_id}")

    def record_play(self, track_id: int):
        """
        Record that a track was played

        Args:
            track_id: Track ID
        """
        now = self.get_timezone_aware_now()
        now_utc = now.astimezone(timezone.utc)

        with self.database.transaction() as conn:
            # Update last_played_at in exclusions table
            conn.execute(
                """
                UPDATE exclusions
                SET last_played_at = ?
                WHERE track_id = ?
                """,
                (now_utc.isoformat(), track_id)
            )

        logger.info(f"Recorded play for track {track_id}")

    def get_active_exclusions(self) -> List[Dict]:
        """
        Get all currently active exclusions

        Returns:
            List of exclusion dictionaries
        """
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                SELECT e.*, t.title, t.artist
                FROM exclusions e
                JOIN tracks t ON e.track_id = t.id
                WHERE julianday(e.blocked_until) > julianday('now')
                ORDER BY e.blocked_until ASC
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_exclusions_by_type(self, exclusion_type: ExclusionType) -> List[Dict]:
        """
        Get exclusions of a specific type

        Args:
            exclusion_type: Type of exclusion

        Returns:
            List of exclusion dictionaries
        """
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                SELECT e.*, t.title, t.artist
                FROM exclusions e
                JOIN tracks t ON e.track_id = t.id
                WHERE e.exclusion_type = ? AND julianday(e.blocked_until) > julianday('now')
                ORDER BY e.blocked_until ASC
                """,
                (exclusion_type.value,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def cleanup_expired_exclusions(self):
        """Remove all expired exclusions"""
        with self.database.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM exclusions WHERE julianday(blocked_until) <= julianday('now')"
            )
            deleted = cursor.rowcount
        logger.info(f"Cleaned up {deleted} expired exclusions")
        return deleted

    def get_exclusion_summary(self) -> Dict[str, int]:
        """
        Get summary of current exclusions

        Returns:
            Dictionary with exclusion counts by type
        """
        summary = {
            'total': 0,
            'no_feedback': 0,
            'negative_feedback': 0,
            'manual': 0,
            'expired': 0
        }

        with self.database.connect() as conn:
            # Active exclusions
            cursor = conn.execute(
                "SELECT exclusion_type, COUNT(*) FROM exclusions WHERE julianday(blocked_until) > julianday('now') GROUP BY exclusion_type"
            )
            for row in cursor.fetchall():
                summary[row[0]] = row[1]
                summary['total'] += row[1]

            # Expired exclusions
            cursor = conn.execute(
                "SELECT COUNT(*) FROM exclusions WHERE julianday(blocked_until) <= julianday('now')"
            )
            result = cursor.fetchone()
            if result:
                summary['expired'] = result[0]

        return summary
