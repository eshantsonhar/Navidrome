-- BlackBerry Music Intelligence Database Schema
-- Version 1.0
-- Authoritative event store for music recommendations

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);

INSERT INTO schema_version (version, description) VALUES (1, 'Initial schema');

-- Tracks and stable identities
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    navidrome_id TEXT UNIQUE,  -- Navidrome track ID if available
    file_path TEXT NOT NULL,  -- Full path to audio file
    file_hash TEXT,  -- SHA256 hash of file content
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    album TEXT,
    duration_seconds REAL,
    genre TEXT,
    year INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_local BOOLEAN DEFAULT 1,  -- True if file exists locally
    UNIQUE(file_path)
);

CREATE INDEX IF NOT EXISTS idx_tracks_navidrome_id ON tracks(navidrome_id);
CREATE INDEX IF NOT EXISTS idx_tracks_file_hash ON tracks(file_hash);
CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist);
CREATE INDEX IF NOT EXISTS idx_tracks_genre ON tracks(genre);

-- Seed playlist membership and synchronization state
CREATE TABLE IF NOT EXISTS seed_playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,  -- 'Bored.m3u' or 'the better playlist.m3u'
    file_path TEXT NOT NULL,
    weight REAL DEFAULT 1.0,  -- Preference weight
    last_synced_at TIMESTAMP,
    file_hash TEXT,  -- Hash of playlist file for change detection
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS seed_playlist_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL,
    track_id INTEGER NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    removed_at TIMESTAMP,  -- NULL if currently in playlist
    is_current BOOLEAN DEFAULT 1,
    FOREIGN KEY (playlist_id) REFERENCES seed_playlists(id) ON DELETE CASCADE,
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE,
    UNIQUE(playlist_id, track_id, added_at)
);

CREATE INDEX IF NOT EXISTS idx_seed_entries_playlist ON seed_playlist_entries(playlist_id);
CREATE INDEX IF NOT EXISTS idx_seed_entries_track ON seed_playlist_entries(track_id);
CREATE INDEX IF NOT EXISTS idx_seed_entries_current ON seed_playlist_entries(playlist_id, is_current);

-- Chart sources and chart snapshots
CREATE TABLE IF NOT EXISTS chart_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,  -- e.g., 'YouTube Music Top 100 English'
    source_type TEXT NOT NULL,  -- 'youtube_music', 'spotify', etc.
    source_id TEXT,  -- Playlist ID or URL
    refresh_interval_hours INTEGER DEFAULT 6,
    last_refreshed_at TIMESTAMP,
    last_refresh_successful BOOLEAN,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chart_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chart_source_id INTEGER NOT NULL,
    snapshot_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    track_id INTEGER NOT NULL,
    rank INTEGER,
    FOREIGN KEY (chart_source_id) REFERENCES chart_sources(id) ON DELETE CASCADE,
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE,
    UNIQUE(chart_source_id, snapshot_time, track_id)
);

CREATE INDEX IF NOT EXISTS idx_chart_snapshots_source ON chart_snapshots(chart_source_id);
CREATE INDEX IF NOT EXISTS idx_chart_snapshots_time ON chart_snapshots(snapshot_time);
CREATE INDEX IF NOT EXISTS idx_chart_snapshots_track ON chart_snapshots(track_id);

-- Discovery candidates and source memberships
CREATE TABLE IF NOT EXISTS discovery_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    album TEXT,
    source_type TEXT NOT NULL,  -- 'chart', 'youtube_music', 'spotify', etc.
    source_id TEXT,  -- Playlist ID, search query, etc.
    source_rank INTEGER,  -- Position in source
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    track_id INTEGER,  -- NULL if not matched to local track yet
    is_available BOOLEAN DEFAULT 0,  -- True if track_id is set and file exists
    download_status TEXT,  -- 'pending', 'downloading', 'completed', 'failed'
    download_url TEXT,
    download_error TEXT,
    UNIQUE(title, artist, album, source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_discovery_source ON discovery_candidates(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_discovery_track ON discovery_candidates(track_id);
CREATE INDEX IF NOT EXISTS idx_discovery_available ON discovery_candidates(is_available);

-- Audio features
CREATE TABLE IF NOT EXISTS audio_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id INTEGER NOT NULL UNIQUE,
    tempo REAL,  -- BPM
    energy REAL,  -- 0-1
    danceability REAL,  -- 0-1
    acousticness REAL,  -- 0-1
    instrumentalness REAL,  -- 0-1
    valence REAL,  -- 0-1 (musical positiveness)
    loudness REAL,  -- dB
    key INTEGER,  -- 0-11
    mode INTEGER,  -- 0=minor, 1=major
    extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_audio_features_track ON audio_features(track_id);

-- Recommendation history
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_path TEXT NOT NULL,  -- Path to generated M3U
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    track_count INTEGER,
    generation_duration_seconds REAL,
    success BOOLEAN,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS recommendation_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recommendation_id INTEGER NOT NULL,
    track_id INTEGER NOT NULL,
    rank INTEGER,  -- Position in playlist
    score REAL,  -- Recommendation score
    reason TEXT,  -- Human-readable explanation
    FOREIGN KEY (recommendation_id) REFERENCES recommendations(id) ON DELETE CASCADE,
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE,
    UNIQUE(recommendation_id, track_id)
);

CREATE INDEX IF NOT EXISTS idx_rec_entries_recommendation ON recommendation_entries(recommendation_id);
CREATE INDEX IF NOT EXISTS idx_rec_entries_track ON recommendation_entries(track_id);

-- Listening events (scrobbles, plays)
CREATE TABLE IF NOT EXISTS listening_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,  -- 'play', 'skip', 'complete'
    event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    play_duration_seconds REAL,
    track_duration_seconds REAL,
    completion_percent REAL,
    source TEXT,  -- 'navidrome', 'substreamer', 'amperify', etc.
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_listening_track ON listening_events(track_id);
CREATE INDEX IF NOT EXISTS idx_listening_time ON listening_events(event_time);
CREATE INDEX IF NOT EXISTS idx_listening_type ON listening_events(event_type);

-- Feedback events and current feedback state
CREATE TABLE IF NOT EXISTS feedback_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,  -- 'rating', 'favorite', 'dislike', 'playlist_add', 'playlist_remove'
    event_value TEXT,  -- Rating value (1-5), 'true'/'false' for boolean events
    source TEXT,  -- 'navidrome', 'substreamer', 'amperify', 'seed_playlist', etc.
    event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_feedback_track ON feedback_events(track_id);
CREATE INDEX IF NOT EXISTS idx_feedback_time ON feedback_events(event_time);
CREATE INDEX IF NOT EXISTS idx_feedback_type ON feedback_events(event_type);

-- Current feedback state (computed from events)
CREATE TABLE IF NOT EXISTS current_feedback (
    track_id INTEGER PRIMARY KEY,
    current_rating INTEGER,  -- 1-5, NULL if no rating
    is_favorite BOOLEAN DEFAULT 0,
    is_disliked BOOLEAN DEFAULT 0,
    in_seed_playlist_primary BOOLEAN DEFAULT 0,
    in_seed_playlist_secondary BOOLEAN DEFAULT 0,
    last_positive_feedback_at TIMESTAMP,
    last_negative_feedback_at TIMESTAMP,
    feedback_state TEXT,  -- 'positive', 'negative', 'neutral', 'unknown'
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_current_feedback_state ON current_feedback(feedback_state);

-- Artist preferences
CREATE TABLE IF NOT EXISTS artist_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artist TEXT NOT NULL UNIQUE,
    preference_score REAL DEFAULT 0,  -- Computed from user interactions
    play_count INTEGER DEFAULT 0,
    positive_feedback_count INTEGER DEFAULT 0,
    negative_feedback_count INTEGER DEFAULT 0,
    last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_artist_score ON artist_preferences(preference_score);

-- Active repeat exclusions
CREATE TABLE IF NOT EXISTS exclusions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id INTEGER NOT NULL UNIQUE,
    exclusion_type TEXT NOT NULL,  -- 'no_feedback', 'negative_feedback', 'manual'
    last_recommended_at TIMESTAMP,
    last_played_at TIMESTAMP,
    blocked_until TIMESTAMP NOT NULL,
    reason TEXT,
    preference_persistent BOOLEAN DEFAULT 0,  -- True if negative preference persists after block
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_exclusions_track ON exclusions(track_id);
CREATE INDEX IF NOT EXISTS idx_exclusions_blocked_until ON exclusions(blocked_until);
CREATE INDEX IF NOT EXISTS idx_exclusions_type ON exclusions(exclusion_type);

-- Download jobs
CREATE TABLE IF NOT EXISTS download_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL,
    status TEXT NOT NULL,  -- 'pending', 'downloading', 'completed', 'failed'
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    file_path TEXT,  -- Path where file was saved
    file_size_bytes INTEGER,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    FOREIGN KEY (candidate_id) REFERENCES discovery_candidates(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_download_candidate ON download_jobs(candidate_id);
CREATE INDEX IF NOT EXISTS idx_download_status ON download_jobs(status);

-- Daily run history
CREATE TABLE IF NOT EXISTS daily_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date DATE NOT NULL UNIQUE,
    run_type TEXT NOT NULL,  -- 'recommendation', 'chart_refresh', 'full_sync'
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    success BOOLEAN,
    tracks_processed INTEGER,
    errors TEXT
);

CREATE INDEX IF NOT EXISTS idx_daily_runs_date ON daily_runs(run_date);
CREATE INDEX IF NOT EXISTS idx_daily_runs_type ON daily_runs(run_type);

-- System state
CREATE TABLE IF NOT EXISTS system_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Initialize system state
INSERT OR IGNORE INTO system_state (key, value) VALUES
    ('last_playlist_sync', ''),
    ('last_feedback_sync', ''),
    ('last_chart_refresh', ''),
    ('last_recommendation', ''),
    ('database_initialized', 'true');
