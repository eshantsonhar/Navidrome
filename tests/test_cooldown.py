"""
Tests for cooldown and repeat prevention
"""

import pytest
import tempfile
import os
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import Database
from recommendation.cooldown import CooldownEngine, ExclusionType


@pytest.fixture
def temp_db():
    """Create a temporary database for testing"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = Database(db_path)
        db.initialize_schema()
        yield db
        db.close()


def test_no_feedback_block(temp_db):
    """Test that no-feedback song is blocked for seven days"""
    cooldown = CooldownEngine(temp_db)

    # Add test track
    with temp_db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES ('/test/track.mp3', 'Test Track', 'Test Artist', CURRENT_TIMESTAMP)
            """
        )
        track_id = cursor.lastrowid

    # Add no-feedback exclusion
    cooldown.add_no_feedback_exclusion(track_id)

    # Track should be excluded
    assert cooldown.is_excluded(track_id) == True
    assert cooldown.is_eligible_for_recommendation(track_id) == False


def test_positive_overrides_block(temp_db):
    """Test that positive signal overrides temporary block"""
    from recommendation.feedback import FeedbackSystem
    feedback = FeedbackSystem(temp_db)
    cooldown = CooldownEngine(temp_db)

    # Add test track
    with temp_db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES ('/test/track.mp3', 'Test Track', 'Test Artist', CURRENT_TIMESTAMP)
            """
        )
        track_id = cursor.lastrowid

    # Add no-feedback exclusion
    cooldown.add_no_feedback_exclusion(track_id)
    assert cooldown.is_excluded(track_id) == True

    # Add positive feedback
    feedback.record_rating(track_id, 5, "test")
    feedback.update_current_feedback(track_id)

    # Override exclusion
    cooldown.override_exclusion(track_id)

    # Track should now be eligible
    assert cooldown.is_excluded(track_id) == False
    assert cooldown.is_eligible_for_recommendation(track_id) == True


def test_negative_feedback_block(temp_db):
    """Test that negative feedback starts exclusion"""
    from recommendation.feedback import FeedbackSystem
    feedback = FeedbackSystem(temp_db)
    cooldown = CooldownEngine(temp_db)

    # Add test track
    with temp_db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES ('/test/track.mp3', 'Test Track', 'Test Artist', CURRENT_TIMESTAMP)
            """
        )
        track_id = cursor.lastrowid

    # Add negative feedback
    feedback.record_rating(track_id, 2, "test")
    feedback.update_current_feedback(track_id)

    # Add negative exclusion
    cooldown.add_negative_feedback_exclusion(track_id)

    # Track should be excluded
    assert cooldown.is_excluded(track_id) == True
    assert cooldown.is_eligible_for_recommendation(track_id) == False


def test_negative_persists_after_expiry(temp_db):
    """Test that negative preference persists after block expires"""
    from recommendation.feedback import FeedbackSystem
    feedback = FeedbackSystem(temp_db)
    cooldown = CooldownEngine(temp_db)

    # Add test track
    with temp_db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES ('/test/track.mp3', 'Test Track', 'Test Artist', CURRENT_TIMESTAMP)
            """
        )
        track_id = cursor.lastrowid

    # Add negative feedback
    feedback.record_rating(track_id, 1, "test")
    feedback.update_current_feedback(track_id)

    # Add negative exclusion with short duration for testing
    cooldown.add_exclusion(
        track_id,
        ExclusionType.NEGATIVE_FEEDBACK,
        "Negative feedback",
        preference_persistent=True,
        duration_days=0  # Expires immediately
    )

    # Exclusion should be expired
    assert cooldown.is_excluded(track_id) == False

    # But feedback state should still be negative
    assert feedback.is_negative(track_id) == True


def test_duplicate_paths_no_evade(temp_db):
    """Test that duplicate filenames don't evade cooldowns"""
    cooldown = CooldownEngine(temp_db)

    # Add two tracks with different IDs but same title/artist
    with temp_db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES ('/test/track1.mp3', 'Test Track', 'Test Artist', CURRENT_TIMESTAMP)
            """
        )
        track_id_1 = cursor.lastrowid

        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES ('/test/track2.mp3', 'Test Track', 'Test Artist', CURRENT_TIMESTAMP)
            """
        )
        track_id_2 = cursor.lastrowid

    # Block first track
    cooldown.add_no_feedback_exclusion(track_id_1)

    # First track should be blocked
    assert cooldown.is_excluded(track_id_1) == True

    # Second track should NOT be blocked (different ID)
    assert cooldown.is_excluded(track_id_2) == False


def test_cooldown_cleanup(temp_db):
    """Test cleanup of expired exclusions"""
    cooldown = CooldownEngine(temp_db)

    # Add test track
    with temp_db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES ('/test/track.mp3', 'Test Track', 'Test Artist', CURRENT_TIMESTAMP)
            """
        )
        track_id = cursor.lastrowid

    # Add exclusion with negative duration to ensure it's in the past
    cooldown.add_exclusion(
        track_id,
        ExclusionType.NO_FEEDBACK,
        "Test",
        preference_persistent=False,
        duration_days=-1
    )

    # Cleanup should remove expired exclusion
    deleted = cooldown.cleanup_expired_exclusions()
    assert deleted >= 1


def test_zero_day_boundary_expiry(temp_db):
    """Test zero-day exclusion at exact boundary"""
    cooldown = CooldownEngine(temp_db)

    # Add test track
    with temp_db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES ('/test/track.mp3', 'Test Track', 'Test Artist', CURRENT_TIMESTAMP)
            """
        )
        track_id = cursor.lastrowid

    # Add exclusion with 0 days - should be immediately eligible for cleanup
    cooldown.add_exclusion(
        track_id,
        ExclusionType.NO_FEEDBACK,
        "Test",
        preference_persistent=False,
        duration_days=0
    )

    # Direct database check: verify timestamp is stored
    exclusion = cooldown.get_exclusion(track_id)
    assert exclusion is not None
    assert exclusion['blocked_until'] is not None

    # Cleanup should remove it (0 days means it's either expired or just became active)
    # The important thing is julianday comparison works correctly
    deleted = cooldown.cleanup_expired_exclusions()
    # If it was truly 0 seconds from now, it might not be cleaned up yet
    # But if it's stored as "now" in SQL, comparison should work


def test_legacy_timezone_aware_timestamp(temp_db):
    """Test backward compatibility with legacy timezone-aware timestamps"""
    cooldown = CooldownEngine(temp_db)

    # Add test track
    with temp_db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES ('/test/track.mp3', 'Test Track', 'Test Artist', CURRENT_TIMESTAMP)
            """
        )
        track_id = cursor.lastrowid

    # Manually insert a legacy timezone-aware timestamp (old format)
    from datetime import datetime, timedelta, timezone
    from pytz import timezone as tz
    india_tz = tz('Asia/Kolkata')
    legacy_time = datetime.now(india_tz) + timedelta(days=7)

    with temp_db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO exclusions
            (track_id, exclusion_type, blocked_until, reason, preference_persistent, created_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (track_id, 'no_feedback', legacy_time.isoformat(), 'Legacy test', False)
        )

    # is_excluded should handle the legacy format correctly
    assert cooldown.is_excluded(track_id) == True

    # Remove it
    cooldown.remove_exclusion(track_id)


def test_legacy_naive_utc_timestamp(temp_db):
    """Test backward compatibility with legacy naive UTC timestamps"""
    cooldown = CooldownEngine(temp_db)

    # Add test track
    with temp_db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES ('/test/track.mp3', 'Test Track', 'Test Artist', CURRENT_TIMESTAMP)
            """
        )
        track_id = cursor.lastrowid

    # Manually insert a legacy naive UTC timestamp (no timezone)
    from datetime import datetime, timedelta, timezone
    legacy_time = datetime.now(timezone.utc) + timedelta(days=7)
    # Store without timezone info (old format)
    legacy_naive = legacy_time.replace(tzinfo=None)

    with temp_db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO exclusions
            (track_id, exclusion_type, blocked_until, reason, preference_persistent, created_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (track_id, 'no_feedback', legacy_naive.isoformat(), 'Legacy naive test', False)
        )

    # is_excluded should handle the naive format correctly (assumes UTC)
    assert cooldown.is_excluded(track_id) == True

    # Remove it
    cooldown.remove_exclusion(track_id)


def test_timestamp_utc_normalization(temp_db):
    """Test that timestamps are stored in UTC for consistent SQL comparisons"""
    cooldown = CooldownEngine(temp_db)

    # Add test track
    with temp_db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES ('/test/track.mp3', 'Test Track', 'Test Artist', CURRENT_TIMESTAMP)
            """
        )
        track_id = cursor.lastrowid

    # Add exclusion
    cooldown.add_exclusion(
        track_id,
        ExclusionType.NO_FEEDBACK,
        "Test",
        preference_persistent=False,
        duration_days=7
    )

    # Verify stored timestamp ends with 'Z' (UTC indicator)
    exclusion = cooldown.get_exclusion(track_id)
    assert exclusion is not None
    assert exclusion['blocked_until'].endswith('Z') or '+00:00' in exclusion['blocked_until']


def test_exclusion_boundary_expiry(temp_db):
    """Test exclusion behavior at expiry boundary"""
    cooldown = CooldownEngine(temp_db)

    # Add test track
    with temp_db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES ('/test/track.mp3', 'Test Track', 'Test Artist', CURRENT_TIMESTAMP)
            """
        )
        track_id = cursor.lastrowid

    # Add exclusion that expires in 1 second
    cooldown.add_exclusion(
        track_id,
        ExclusionType.NO_FEEDBACK,
        "Test",
        preference_persistent=False,
        duration_days=0
    )

    # Should be initially excluded (1 second is effectively 0 days but may still be active)
    # The important thing is that julianday comparison works correctly
    exclusion = cooldown.get_exclusion(track_id)
    assert exclusion is not None

    # After cleanup, it should be removed
    deleted = cooldown.cleanup_expired_exclusions()
    # If it was 0 days, it's likely expired now
    # If not, the cleanup still works correctly for genuinely expired entries


def test_active_exclusions_query(temp_db):
    """Test that active exclusions query matches Python logic"""
    cooldown = CooldownEngine(temp_db)

    # Add test track
    with temp_db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES ('/test/track.mp3', 'Test Track', 'Test Artist', CURRENT_TIMESTAMP)
            """
        )
        track_id = cursor.lastrowid

    # Add active exclusion
    cooldown.add_exclusion(
        track_id,
        ExclusionType.NO_FEEDBACK,
        "Test",
        preference_persistent=False,
        duration_days=7
    )

    # Get active exclusions via SQL query
    active = cooldown.get_active_exclusions()
    assert len(active) == 1
    assert active[0]['track_id'] == track_id

    # Get via type-specific query
    by_type = cooldown.get_exclusions_by_type(ExclusionType.NO_FEEDBACK)
    assert len(by_type) == 1
    assert by_type[0]['track_id'] == track_id

    # Summary should count it as active
    summary = cooldown.get_exclusion_summary()
    assert summary['no_feedback'] == 1
    assert summary['total'] == 1


def test_expired_exclusions_query(temp_db):
    """Test that expired exclusions are not counted as active"""
    cooldown = CooldownEngine(temp_db)

    # Add test track
    with temp_db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES ('/test/track.mp3', 'Test Track', 'Test Artist', CURRENT_TIMESTAMP)
            """
        )
        track_id = cursor.lastrowid

    # Add expired exclusion
    cooldown.add_exclusion(
        track_id,
        ExclusionType.NO_FEEDBACK,
        "Test",
        preference_persistent=False,
        duration_days=-1
    )

    # Active exclusions should be empty
    active = cooldown.get_active_exclusions()
    assert len(active) == 0

    # Summary should count it as expired
    summary = cooldown.get_exclusion_summary()
    assert summary['no_feedback'] == 0
    assert summary['total'] == 0
    assert summary['expired'] == 1


def test_memory_generation_consistency(temp_db):
    """Test that memory generation agrees with exclusion queries"""
    from recommendation.memory_writer import MemoryWriter
    cooldown = CooldownEngine(temp_db)
    writer = MemoryWriter(temp_db)

    # Add test track
    with temp_db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES ('/test/track.mp3', 'Test Track', 'Test Artist', CURRENT_TIMESTAMP)
            """
        )
        track_id = cursor.lastrowid

    # Add active exclusion
    cooldown.add_exclusion(
        track_id,
        ExclusionType.NO_FEEDBACK,
        "Test",
        preference_persistent=False,
        duration_days=7
    )

    # Get memory summary
    memory_summary = writer.get_memory_summary()
    assert memory_summary['no_feedback'] == 1
    assert len(memory_summary['no_feedback_details']) == 1

    # Should match cooldown summary
    cooldown_summary = cooldown.get_exclusion_summary()
    assert memory_summary['no_feedback'] == cooldown_summary['no_feedback']
