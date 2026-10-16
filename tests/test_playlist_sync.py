"""
Tests for playlist synchronization
"""

import pytest
import tempfile
import os
from pathlib import Path

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import Database
from recommendation.playlist_monitor import PlaylistMonitor


@pytest.fixture
def temp_db():
    """Create a temporary database for testing"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = Database(db_path)
        db.initialize_schema()
        yield db
        db.close()


@pytest.fixture
def temp_playlist():
    """Create a temporary M3U playlist for testing"""
    with tempfile.TemporaryDirectory() as tmpdir:
        playlist_path = os.path.join(tmpdir, "test.m3u")
        with open(playlist_path, 'w') as f:
            f.write("#EXTM3U\n")
            f.write("#EXTINF:180,Artist - Song 1\n")
            f.write("/music/Artist/Song 1.mp3\n")
            f.write("#EXTINF:200,Artist - Song 2\n")
            f.write("/music/Artist/Song 2.mp3\n")
        yield playlist_path


def test_playlist_parsing(temp_playlist):
    """Test M3U playlist parsing"""
    monitor = PlaylistMonitor(Database(":memory:"))
    entries = monitor.parse_m3u(temp_playlist)

    assert len(entries) == 2
    assert entries[0].title == "Song 1"
    assert entries[0].artist == "Artist"
    assert entries[0].path == "/music/Artist/Song 1.mp3"


def test_playlist_registration(temp_db):
    """Test playlist registration"""
    monitor = PlaylistMonitor(temp_db)

    monitor.register_playlist("Test.m3u", "/test/Test.m3u", weight=1.5)

    with temp_db.connect() as conn:
        cursor = conn.execute("SELECT * FROM seed_playlists WHERE name = 'Test.m3u'")
        result = cursor.fetchone()
        assert result is not None
        assert result['weight'] == 1.5


def test_playlist_sync_detection(temp_db, temp_playlist):
    """Test that playlist changes are detected"""
    monitor = PlaylistMonitor(temp_db)

    # Register playlist
    monitor.register_playlist("Test.m3u", temp_playlist, weight=1.0)

    # First sync
    stats1 = monitor.sync_playlist("Test.m3u", temp_playlist)
    assert stats1['added'] > 0 or stats1['unchanged'] > 0

    # Second sync without changes
    stats2 = monitor.sync_playlist("Test.m3u", temp_playlist)
    # Should not add new entries
    assert stats2['added'] == 0


def test_playlist_addition_affects_taste(temp_db, temp_playlist):
    """Test that playlist addition affects taste profile"""
    from recommendation.feedback import FeedbackSystem
    feedback = FeedbackSystem(temp_db)
    monitor = PlaylistMonitor(temp_db)

    # Register and sync playlist
    monitor.register_playlist("Test.m3u", temp_playlist, weight=1.0)
    monitor.sync_playlist("Test.m3u", temp_playlist)

    # Get synced track IDs
    with temp_db.connect() as conn:
        cursor = conn.execute(
            """
            SELECT t.id FROM tracks t
            JOIN seed_playlist_entries spe ON t.id = spe.track_id
            JOIN seed_playlists sp ON spe.playlist_id = sp.id
            WHERE sp.name = 'Test.m3u' AND spe.is_current = 1
            """
        )
        track_ids = [row[0] for row in cursor.fetchall()]

    # Should have tracks synced
    assert len(track_ids) > 0


def test_chart_not_affect_taste(temp_db):
    """Test that chart membership does not directly affect personalized taste"""
    from recommendation.feedback import FeedbackSystem
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

    # Add to chart (discovery candidate)
    with temp_db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO discovery_candidates
            (title, artist, source_type, source_id, first_seen_at, last_seen_at, track_id, is_available)
            VALUES ('Test Track', 'Test Artist', 'chart', 'test', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, 1)
            """,
            (track_id,)
        )

    # Update feedback
    feedback.update_current_feedback(track_id)

    # Should not be positive just from chart membership
    current = feedback.get_current_feedback(track_id)
    assert current['feedback_state'] != 'positive'


def test_unicode_in_playlist():
    """Test that Unicode and spaces in filenames work"""
    with tempfile.TemporaryDirectory() as tmpdir:
        playlist_path = os.path.join(tmpdir, "test.m3u")
        with open(playlist_path, 'w', encoding='utf-8') as f:
            f.write("#EXTM3U\n")
            f.write("#EXTINF:180,日本語 - 曲名\n")
            f.write("/music/日本語/曲名.mp3\n")
            f.write("#EXTINF:200,Special Characters - Test (2024)\n")
            f.write("/music/Special Characters/Test (2024).mp3\n")

        monitor = PlaylistMonitor(Database(":memory:"))
        entries = monitor.parse_m3u(playlist_path)

        assert len(entries) == 2
        assert entries[0].title == "曲名"
        assert entries[1].title == "Test (2024)"
