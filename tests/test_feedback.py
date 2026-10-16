"""
Tests for feedback system
"""

import pytest
import tempfile
import os
from pathlib import Path

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import Database
from recommendation.feedback import FeedbackSystem, FeedbackType, FeedbackState


@pytest.fixture
def temp_db():
    """Create a temporary database for testing"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = Database(db_path)
        db.initialize_schema()
        yield db
        db.close()


def test_feedback_classification(temp_db):
    """Test feedback classification rules"""
    feedback = FeedbackSystem(temp_db)

    # Add a test track
    with temp_db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES ('/test/track.mp3', 'Test Track', 'Test Artist', CURRENT_TIMESTAMP)
            """
        )
        track_id = cursor.lastrowid

    # Test positive feedback - 5 star rating
    feedback.record_rating(track_id, 5, "test")
    feedback.update_current_feedback(track_id)
    assert feedback.is_positive(track_id) == True
    assert feedback.is_negative(track_id) == False

    # Test negative feedback - 1 star rating
    feedback.record_rating(track_id, 1, "test")
    feedback.update_current_feedback(track_id)
    assert feedback.is_positive(track_id) == False
    assert feedback.is_negative(track_id) == True

    # Test negative feedback - 3 star rating (should be negative)
    feedback.record_rating(track_id, 3, "test")
    feedback.update_current_feedback(track_id)
    assert feedback.is_positive(track_id) == False
    assert feedback.is_negative(track_id) == True

    # Test positive feedback - 4 star rating
    feedback.record_rating(track_id, 4, "test")
    feedback.update_current_feedback(track_id)
    assert feedback.is_positive(track_id) == True
    assert feedback.is_negative(track_id) == False


def test_playlist_addition_feedback(temp_db):
    """Test that playlist addition produces positive evidence"""
    feedback = FeedbackSystem(temp_db)

    # Add test tracks
    with temp_db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES ('/test/track1.mp3', 'Track 1', 'Artist 1', CURRENT_TIMESTAMP)
            """
        )
        track_id = cursor.lastrowid

    # Add to primary playlist
    feedback.record_playlist_add(track_id, "Bored.m3u")
    feedback.update_current_feedback(track_id)
    assert feedback.is_positive(track_id) == True

    # Add to secondary playlist (stronger signal)
    feedback.record_playlist_add(track_id, "the better playlist.m3u")
    feedback.update_current_feedback(track_id)
    assert feedback.is_positive(track_id) == True


def test_negative_overrides_playlist(temp_db):
    """Test that explicit negative rating overrides playlist membership"""
    feedback = FeedbackSystem(temp_db)

    # Add test track
    with temp_db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES ('/test/track.mp3', 'Test Track', 'Test Artist', CURRENT_TIMESTAMP)
            """
        )
        track_id = cursor.lastrowid

    # Add to playlist
    feedback.record_playlist_add(track_id, "Bored.m3u")
    feedback.update_current_feedback(track_id)
    assert feedback.is_positive(track_id) == True

    # Add negative rating
    feedback.record_rating(track_id, 2, "test")
    feedback.update_current_feedback(track_id)
    # Negative should override playlist membership
    assert feedback.is_negative(track_id) == True
    assert feedback.is_positive(track_id) == False


def test_favorite_is_positive(temp_db):
    """Test that favorite is positive feedback"""
    feedback = FeedbackSystem(temp_db)

    # Add test track
    with temp_db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES ('/test/track.mp3', 'Test Track', 'Test Artist', CURRENT_TIMESTAMP)
            """
        )
        track_id = cursor.lastrowid

    # Mark as favorite
    feedback.record_favorite(track_id, True, "test")
    feedback.update_current_feedback(track_id)
    assert feedback.is_positive(track_id) == True


def test_idempotent_sync(temp_db):
    """Test that repeated sync doesn't duplicate events"""
    feedback = FeedbackSystem(temp_db)

    # Add test track
    with temp_db.transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tracks (file_path, title, artist, created_at)
            VALUES ('/test/track.mp3', 'Test Track', 'Test Artist', CURRENT_TIMESTAMP)
            """
        )
        track_id = cursor.lastrowid

    # Record same favorite multiple times
    feedback.record_favorite(track_id, True, "test")
    feedback.record_favorite(track_id, True, "test")
    feedback.record_favorite(track_id, True, "test")

    # Check that we have 3 events (as recorded)
    with temp_db.connect() as conn:
        cursor = conn.execute(
            "SELECT COUNT(*) FROM feedback_events WHERE track_id = ?",
            (track_id,)
        )
        count = cursor.fetchone()[0]
        assert count == 3  # Events are recorded as they happen

    # But current state should still be positive
    feedback.update_current_feedback(track_id)
    assert feedback.is_positive(track_id) == True
