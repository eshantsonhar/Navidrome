"""
Navidrome integration
Handles communication with Navidrome Subsonic API
"""

import logging
import requests
from typing import Dict, List, Optional
from datetime import datetime

import config

logger = logging.getLogger(__name__)


class NavidromeClient:
    """Client for Navidrome Subsonic API"""

    def __init__(self):
        self.config = config.get_config()
        self.base_url = self.config.navidrome.base_url
        self.api_version = self.config.navidrome.api_version
        self.username = self.config.navidrome.username
        self.password = self.config.navidrome.password
        self.api_token = self.config.navidrome.api_token
        self.session = None

    def connect(self) -> bool:
        """
        Establish connection to Navidrome

        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Use token if available, otherwise username/password
            if self.api_token:
                params = {
                    'u': self.username,
                    't': self.api_token,
                    'v': self.api_version,
                    'c': 'BlackBerryMusicIntelligence',
                    'f': 'json'
                }
            else:
                # Generate salt and token for password auth
                import hashlib
                import random
                salt = ''.join(random.choices('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=16))
                token = hashlib.md5((self.password + salt).encode()).hexdigest()
                params = {
                    'u': self.username,
                    's': salt,
                    't': token,
                    'v': self.api_version,
                    'c': 'BlackBerryMusicIntelligence',
                    'f': 'json'
                }

            # Test connection with ping
            response = requests.get(
                f"{self.base_url}/rest/ping.view",
                params=params,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                if data.get('subsonic-response', {}).get('status') == 'ok':
                    self.session = requests.Session()
                    self.session.params = params
                    logger.info("Connected to Navidrome successfully")
                    return True
                else:
                    logger.error(f"Navidrome API error: {data}")
                    return False
            else:
                logger.error(f"Navidrome connection failed: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Navidrome connection error: {e}")
            return False

    def is_connected(self) -> bool:
        """Check if connected to Navidrome"""
        return self.session is not None

    def get_tracks(self) -> List[Dict]:
        """
        Get all tracks from Navidrome library

        Returns:
            List of track dictionaries
        """
        if not self.is_connected():
            logger.error("Not connected to Navidrome")
            return []

        try:
            response = self.session.get(
                f"{self.base_url}/rest/getLibrary.view",
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                tracks = data.get('subsonic-response', {}).get('library', {}).get('artists', [])
                logger.info(f"Retrieved {len(tracks)} tracks from Navidrome")
                return tracks
            else:
                logger.error(f"Error getting tracks: {response.status_code}")
                return []

        except Exception as e:
            logger.error(f"Error getting tracks: {e}")
            return []

    def get_ratings(self) -> Dict[str, int]:
        """
        Get all track ratings from Navidrome

        Returns:
            Dictionary mapping track IDs to ratings (1-5)
        """
        if not self.is_connected():
            logger.error("Not connected to Navidrome")
            return {}

        try:
            response = self.session.get(
                f"{self.base_url}/rest/getStarred2.view",
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                starred = data.get('subsonic-response', {}).get('starred2', {}).get('song', [])
                # This returns starred tracks, not all ratings
                # Navidrome may not expose all ratings via API
                logger.warning("Navidrome API may not expose all ratings")
                return {}
            else:
                logger.error(f"Error getting ratings: {response.status_code}")
                return {}

        except Exception as e:
            logger.error(f"Error getting ratings: {e}")
            return {}

    def get_favorites(self) -> List[str]:
        """
        Get all favorited tracks from Navidrome

        Returns:
            List of track IDs
        """
        if not self.is_connected():
            logger.error("Not connected to Navidrome")
            return []

        try:
            response = self.session.get(
                f"{self.base_url}/rest/getStarred2.view",
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                songs = data.get('subsonic-response', {}).get('starred2', {}).get('song', [])
                track_ids = [song.get('id') for song in songs if song.get('id')]
                logger.info(f"Retrieved {len(track_ids)} favorited tracks")
                return track_ids
            else:
                logger.error(f"Error getting favorites: {response.status_code}")
                return []

        except Exception as e:
            logger.error(f"Error getting favorites: {e}")
            return []

    def get_listening_history(self, limit: int = 100) -> List[Dict]:
        """
        Get listening history from Navidrome

        NOTE: Based on Navidrome Subsonic API documentation (v1.16.1),
        listening history retrieval is NOT listed as a supported endpoint.
        Research confirms that while 'scrobble' exists for submission,
        there is no documented endpoint for retrieving historical listening data.
        This method always returns empty and should not be relied upon.
        The feedback system should use ratings and favorites instead.

        Args:
            limit: Maximum number of entries (ignored, returns empty)

        Returns:
            Empty list (listening history not available via API)
        """
        if not self.is_connected():
            logger.error("Not connected to Navidrome")
            return []

        # Listening history retrieval is not supported by Navidrome Subsonic API v1.16.1
        # Based on official documentation: https://www.navidrome.org/docs/developers/subsonic-api/
        # Confirmed: No endpoint for listening history retrieval, only scrobble submission
        logger.warning("Listening history retrieval not supported by Navidrome Subsonic API")
        logger.warning("Feedback system should rely on ratings and favorites instead")
        return []

    def set_rating(self, track_id: str, rating: int) -> bool:
        """
        Set rating for a track

        Args:
            track_id: Navidrome track ID
            rating: Rating value (1-5)

        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected():
            logger.error("Not connected to Navidrome")
            return False

        if not 1 <= rating <= 5:
            logger.error(f"Invalid rating: {rating}")
            return False

        try:
            response = self.session.get(
                f"{self.base_url}/rest/setRating.view",
                params={'id': track_id, 'rating': rating},
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                if data.get('subsonic-response', {}).get('status') == 'ok':
                    logger.info(f"Set rating {rating} for track {track_id}")
                    return True
                else:
                    logger.error(f"Error setting rating: {data}")
                    return False
            else:
                logger.error(f"Error setting rating: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error setting rating: {e}")
            return False

    def set_favorite(self, track_id: str, favorite: bool) -> bool:
        """
        Set favorite status for a track

        Args:
            track_id: Navidrome track ID
            favorite: Whether to favorite

        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected():
            logger.error("Not connected to Navidrome")
            return False

        try:
            response = self.session.get(
                f"{self.base_url}/rest/star.view",
                params={'id': track_id, 'star': str(favorite).lower()},
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                if data.get('subsonic-response', {}).get('status') == 'ok':
                    logger.info(f"Set favorite={favorite} for track {track_id}")
                    return True
                else:
                    logger.error(f"Error setting favorite: {data}")
                    return False
            else:
                logger.error(f"Error setting favorite: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error setting favorite: {e}")
            return False

    def scan_library(self) -> bool:
        """
        Trigger Navidrome library scan

        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected():
            logger.error("Not connected to Navidrome")
            return False

        try:
            response = self.session.get(
                f"{self.base_url}/rest/startScan.view",
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                if data.get('subsonic-response', {}).get('status') == 'ok':
                    logger.info("Triggered Navidrome library scan")
                    return True
                else:
                    logger.error(f"Error triggering scan: {data}")
                    return False
            else:
                logger.error(f"Error triggering scan: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Error triggering scan: {e}")
            return False
