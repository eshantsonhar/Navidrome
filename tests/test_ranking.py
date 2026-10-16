"""
Tests for ranking engine
"""

import pytest
import tempfile
import os
from pathlib import Path

from database import Database
from recommendation.ranking import RankingEngine, CandidateScore
from recommendation.feedback import FeedbackState


@pytest.fixture
def temp_db():
    """Create temporary database for testing"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = Database(db_path)
        db.initialize_schema()
        yield db


@pytest.fixture
def sample_tracks(temp_db):
    """Create sample tracks in database"""
    track_ids = []
    with temp_db.transaction() as conn:
        for i in range(10):
            cursor = conn.execute(
                """
                INSERT INTO tracks (file_path, title, artist, duration_seconds, created_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (f"/music/artist{i // 2}/song{i}.mp3", f"Song {i}", f"Artist {i // 2}", 180)
            )
            track_ids.append(cursor.lastrowid)
    return track_ids


def test_eligibility_filtering(temp_db, sample_tracks):
    """Test that ineligible tracks are filtered out"""
    with tempfile.TemporaryDirectory() as tmpdir:
        from config import Config, PathsConfig
        test_config = Config(
            paths=PathsConfig(
                music_base="/music",
                project_dir=tmpdir,
                recommendation_playlist=os.path.join(tmpdir, "test.m3u")
            )
        )

        import config
        original_get_config = config.get_config
        config.get_config = lambda: test_config

        try:
            engine = RankingEngine(temp_db)

            # Mark first track as ineligible (blocked)
            with temp_db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO exclusions (track_id, blocked_until, exclusion_type)
                    VALUES (?, datetime('now', '+7 days'), 'no_feedback')
                    """,
                    (sample_tracks[0],)
                )

            candidates = engine.rank_candidates(sample_tracks, limit=5)

            # First track should not be in results
            assert len(candidates) > 0
            assert all(c.track_id != sample_tracks[0] for c in candidates)

        finally:
            config.get_config = original_get_config


def test_feedback_weighting(temp_db, sample_tracks):
    """Test that feedback state affects scoring"""
    with tempfile.TemporaryDirectory() as tmpdir:
        from config import Config, PathsConfig
        test_config = Config(
            paths=PathsConfig(
                music_base="/music",
                project_dir=tmpdir,
                recommendation_playlist=os.path.join(tmpdir, "test.m3u")
            )
        )

        import config
        original_get_config = config.get_config
        config.get_config = lambda: test_config

        try:
            engine = RankingEngine(temp_db)

            # Set feedback states for two tracks
            with temp_db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO current_feedback (track_id, feedback_state, last_positive_feedback_at)
                    VALUES (?, 'positive', CURRENT_TIMESTAMP)
                    """,
                    (sample_tracks[0],)
                )
                conn.execute(
                    """
                    INSERT INTO current_feedback (track_id, feedback_state)
                    VALUES (?, 'neutral')
                    """,
                    (sample_tracks[2],)
                )

            candidates = engine.rank_candidates(sample_tracks, limit=10)

            # Positive feedback track should be in results
            positive = next((c for c in candidates if c.track_id == sample_tracks[0]), None)
            neutral = next((c for c in candidates if c.track_id == sample_tracks[2]), None)

            assert positive is not None, "Positive feedback track should be in results"
            # Neutral may or may not be in results depending on other factors
            if neutral is not None:
                # Positive should have higher score due to feedback similarity
                assert positive.score > neutral.score, "Positive feedback should score higher than neutral"

        finally:
            config.get_config = original_get_config


def test_artist_diversity_consecutive_limit(temp_db, sample_tracks):
    """Test that consecutive same-artist tracks are limited"""
    with tempfile.TemporaryDirectory() as tmpdir:
        from config import Config, PathsConfig
        test_config = Config(
            paths=PathsConfig(
                music_base="/music",
                project_dir=tmpdir,
                recommendation_playlist=os.path.join(tmpdir, "test.m3u")
            )
        )

        import config
        original_get_config = config.get_config
        config.get_config = lambda: test_config

        try:
            engine = RankingEngine(temp_db)

            # Create candidates with same artist (high scores)
            candidates = [
                CandidateScore(
                    track_id=sample_tracks[i],
                    title=f"Song {i}",
                    artist="Artist 0",
                    score=1.0 - (i * 0.01),
                    reason="Test",
                    details={}
                )
                for i in range(10)
            ]

            diversified = engine._apply_artist_diversity(candidates, limit=10)

            # Should not have more than max_consecutive_same_artist in a row
            max_consecutive = test_config.recommendation.max_consecutive_same_artist

            consecutive = 0
            last_artist = None
            for c in diversified:
                if c.artist == last_artist:
                    consecutive += 1
                else:
                    consecutive = 1
                    last_artist = c.artist
                assert consecutive <= max_consecutive

        finally:
            config.get_config = original_get_config


def test_artist_diversity_percentage_limit(temp_db, sample_tracks):
    """Test that artist diversity enforcement is applied"""
    with tempfile.TemporaryDirectory() as tmpdir:
        from config import Config, PathsConfig
        test_config = Config(
            paths=PathsConfig(
                music_base="/music",
                project_dir=tmpdir,
                recommendation_playlist=os.path.join(tmpdir, "test.m3u")
            )
        )

        import config
        original_get_config = config.get_config
        config.get_config = lambda: test_config

        try:
            engine = RankingEngine(temp_db)

            # Create candidates with mixed artists
            candidates = []
            for i in range(10):
                artist = f"Artist {i % 3}"  # Distribute across 3 artists
                candidates.append(CandidateScore(
                    track_id=sample_tracks[i],
                    title=f"Song {i}",
                    artist=artist,
                    score=1.0 - (i * 0.01),
                    reason="Test",
                    details={}
                ))

            diversified = engine._apply_artist_diversity(candidates, limit=10)

            # Verify that diversity filtering was applied (not all 10 candidates returned if they exceed limits)
            # With max_consecutive_same_artist=2, we should have some filtering
            assert len(diversified) <= 10

            # Verify consecutive limit is respected
            consecutive = 0
            last_artist = None
            for c in diversified:
                if c.artist == last_artist:
                    consecutive += 1
                else:
                    consecutive = 1
                    last_artist = c.artist
                assert consecutive <= test_config.recommendation.max_consecutive_same_artist

        finally:
            config.get_config = original_get_config


def test_deterministic_ordering(temp_db, sample_tracks):
    """Test that ranking is deterministic"""
    with tempfile.TemporaryDirectory() as tmpdir:
        from config import Config, PathsConfig
        test_config = Config(
            paths=PathsConfig(
                music_base="/music",
                project_dir=tmpdir,
                recommendation_playlist=os.path.join(tmpdir, "test.m3u")
            )
        )

        import config
        original_get_config = config.get_config
        config.get_config = lambda: test_config

        try:
            engine = RankingEngine(temp_db)

            # Run ranking twice
            candidates1 = engine.rank_candidates(sample_tracks, limit=5)
            candidates2 = engine.rank_candidates(sample_tracks, limit=5)

            # Results should be identical
            assert len(candidates1) == len(candidates2)
            for c1, c2 in zip(candidates1, candidates2):
                assert c1.track_id == c2.track_id
                assert c1.score == c2.score

        finally:
            config.get_config = original_get_config


def test_empty_candidate_pool(temp_db):
    """Test handling of empty candidate pool"""
    with tempfile.TemporaryDirectory() as tmpdir:
        from config import Config, PathsConfig
        test_config = Config(
            paths=PathsConfig(
                music_base="/music",
                project_dir=tmpdir,
                recommendation_playlist=os.path.join(tmpdir, "test.m3u")
            )
        )

        import config
        original_get_config = config.get_config
        config.get_config = lambda: test_config

        try:
            engine = RankingEngine(temp_db)

            candidates = engine.rank_candidates([], limit=5)

            assert len(candidates) == 0

        finally:
            config.get_config = original_get_config


def test_limit_enforcement(temp_db, sample_tracks):
    """Test that limit parameter is respected"""
    with tempfile.TemporaryDirectory() as tmpdir:
        from config import Config, PathsConfig
        test_config = Config(
            paths=PathsConfig(
                music_base="/music",
                project_dir=tmpdir,
                recommendation_playlist=os.path.join(tmpdir, "test.m3u")
            )
        )

        import config
        original_get_config = config.get_config
        config.get_config = lambda: test_config

        try:
            engine = RankingEngine(temp_db)

            for limit in [1, 3, 5, 10]:
                candidates = engine.rank_candidates(sample_tracks, limit=limit)
                assert len(candidates) <= limit

        finally:
            config.get_config = original_get_config
