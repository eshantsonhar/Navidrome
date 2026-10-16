"""
Configuration loader for BlackBerry Music Intelligence
Loads and validates configuration from config.toml
"""

import os
import toml
from pathlib import Path
from typing import Dict, Any
from pydantic import BaseModel, Field, field_validator


class PathsConfig(BaseModel):
    music_base: str = "/mnt/music"
    project_dir: str = "/mnt/music/script_music_reccomendations"
    seed_playlist_primary: str = "/mnt/music/Bored.m3u"
    seed_playlist_secondary: str = "/mnt/music/the better playlist.m3u"
    recommendation_dir: str = "/mnt/music/daily recommendation"
    recommendation_playlist: str = "/mnt/music/daily_recommendation.m3u"
    top_100_playlist: str = "/mnt/music/top 100_english.m3u"
    database_path: str = "/mnt/music/script_music_reccomendations/data/recommendations.db"
    cache_dir: str = "/mnt/music/script_music_reccomendations/data/cache"
    backup_dir: str = "/mnt/music/script_music_reccomendations/data/backups"
    log_dir: str = "/mnt/music/script_music_reccomendations/logs"
    memory_file: str = "/mnt/music/script_music_reccomendations/memory.txt"


class NavidromeConfig(BaseModel):
    base_url: str = "http://localhost:4533"
    username: str = ""
    password: str = ""
    api_token: str = ""
    api_version: str = "1.16.1"


class OllamaConfig(BaseModel):
    base_url: str = "http://localhost:11434"
    model: str = "llama3.2:1b"
    timeout: int = 60
    max_tokens: int = 2048


class ChartConfig(BaseModel):
    playlist_id: str = "PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI"
    refresh_interval_hours: int = 6
    max_tracks: int = 100


class RecommendationConfig(BaseModel):
    daily_generation_time: str = "08:00"
    timezone: str = "Asia/Kolkata"
    repeat_cooldown_days: int = 7
    seed_playlist_primary_weight: float = 1.0
    seed_playlist_secondary_weight: float = 1.5
    max_consecutive_same_artist: int = 2
    max_artist_percentage: int = 25
    audio_similarity_weight: float = 0.40
    feedback_similarity_weight: float = 0.25
    seed_playlist_similarity_weight: float = 0.15
    discovery_relevance_weight: float = 0.10
    novelty_weight: float = 0.10
    min_playlist_size: int = 20
    max_playlist_size: int = 50

    @field_validator('audio_similarity_weight', 'feedback_similarity_weight',
                     'seed_playlist_similarity_weight', 'discovery_relevance_weight', 'novelty_weight')
    @classmethod
    def weights_must_be_positive(cls, v: float) -> float:
        if v < 0:
            raise ValueError('Weight must be non-negative')
        return v


class SchedulingConfig(BaseModel):
    playlist_check_interval_minutes: int = 3
    feedback_sync_interval_minutes: int = 20
    download_max_retries: int = 3
    download_retry_backoff_seconds: int = 60


class AudioFeaturesConfig(BaseModel):
    enable_audio_analysis: bool = True
    min_duration_seconds: int = 30
    max_concurrent_analyses: int = 2


class DownloadConfig(BaseModel):
    max_concurrent_downloads: int = 2
    download_timeout: int = 300
    max_download_size_mb: int = 50
    auto_download: bool = False
    download_source: str = "spotdl"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    max_log_size_mb: int = 10
    log_backup_count: int = 5


class DatabaseConfig(BaseModel):
    backup_interval_hours: int = 24
    max_backups: int = 7
    enable_integrity_check: bool = True


class FeedbackConfig(BaseModel):
    strong_negative_rating_max: int = 2
    negative_rating: int = 3
    positive_rating_min: int = 4
    min_play_completion_percent: int = 80
    skip_threshold_percent: int = 30
    skip_negative_threshold: int = 3


class SecurityConfig(BaseModel):
    dry_run: bool = False
    verify_mount: bool = True
    expected_mount: str = "/mnt/music"


class Config(BaseModel):
    paths: PathsConfig = Field(default_factory=PathsConfig)
    navidrome: NavidromeConfig = Field(default_factory=NavidromeConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    chart: ChartConfig = Field(default_factory=ChartConfig)
    recommendation: RecommendationConfig = Field(default_factory=RecommendationConfig)
    scheduling: SchedulingConfig = Field(default_factory=SchedulingConfig)
    audio_features: AudioFeaturesConfig = Field(default_factory=AudioFeaturesConfig)
    download: DownloadConfig = Field(default_factory=DownloadConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    feedback: FeedbackConfig = Field(default_factory=FeedbackConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)


def load_config(config_path: str = None) -> Config:
    """
    Load configuration from TOML file

    Args:
        config_path: Path to config.toml. If None, uses default location.

    Returns:
        Config object with all settings
    """
    if config_path is None:
        # Default to config.toml in project directory
        project_dir = Path(__file__).parent
        config_path = project_dir / "config.toml"

    config_file = Path(config_path)

    if not config_file.exists():
        print(f"Config file not found at {config_path}, using defaults")
        return Config()

    with open(config_file, 'r') as f:
        config_data = toml.load(f)

    return Config(**config_data)


def get_config() -> Config:
    """Get the current configuration (singleton pattern)"""
    if not hasattr(get_config, '_instance'):
        get_config._instance = load_config()
    return get_config._instance


def reset_config():
    """Reset configuration (useful for testing)"""
    if hasattr(get_config, '_instance'):
        delattr(get_config, '_instance')
