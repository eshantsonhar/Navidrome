"""
Deterministic recommendation ranking algorithm
Implements hybrid scoring with multiple signals
"""

import logging
from typing import List, Dict, Optional, Set
from dataclasses import dataclass
from datetime import datetime, timedelta

import config
from database import Database
from .feedback import FeedbackSystem, FeedbackState
from .cooldown import CooldownEngine

logger = logging.getLogger(__name__)


@dataclass
class CandidateScore:
    """Represents a scored candidate track"""
    track_id: int
    title: str
    artist: str
    score: float
    reason: str
    details: Dict


class RankingEngine:
    """Deterministic recommendation ranking engine"""

    def __init__(self, database: Database):
        self.database = database
        self.config = config.get_config()
        self.feedback = FeedbackSystem(database)
        self.cooldown = CooldownEngine(database)

    def rank_candidates(self, candidate_ids: List[int], limit: int = None) -> List[CandidateScore]:
        """
        Rank candidate tracks for recommendation

        Args:
            candidate_ids: List of track IDs to rank
            limit: Maximum number of results

        Returns:
            List of scored candidates, sorted by score (highest first)
        """
        if limit is None:
            limit = self.config.recommendation.max_playlist_size

        scored_candidates = []

        for track_id in candidate_ids:
            # Check eligibility
            if not self.cooldown.is_eligible_for_recommendation(track_id):
                continue

            # Get track info
            track = self._get_track_info(track_id)
            if not track:
                continue

            # Calculate score
            score, reason, details = self._calculate_score(track_id, track)

            scored_candidates.append(CandidateScore(
                track_id=track_id,
                title=track['title'],
                artist=track['artist'],
                score=score,
                reason=reason,
                details=details
            ))

        # Sort by score (descending)
        scored_candidates.sort(key=lambda x: x.score, reverse=True)

        # Apply artist diversity
        diversified = self._apply_artist_diversity(scored_candidates, limit)

        logger.info(f"Ranked {len(diversified)} candidates out of {len(candidate_ids)}")
        return diversified[:limit]

    def _get_track_info(self, track_id: int) -> Optional[Dict]:
        """Get track information from database"""
        with self.database.connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM tracks WHERE id = ?",
                (track_id,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def _calculate_score(self, track_id: int, track: Dict) -> tuple[float, str, Dict]:
        """
        Calculate recommendation score for a track

        Args:
            track_id: Track ID
            track: Track information dictionary

        Returns:
            Tuple of (score, reason, details)
        """
        details = {}
        score = 0.0
        reasons = []

        # Get feedback state
        feedback = self.feedback.get_current_feedback(track_id)
        feedback_state = feedback['feedback_state'] if feedback else FeedbackState.UNKNOWN.value

        # 1. Audio similarity (placeholder - would need audio features)
        audio_sim = self._calculate_audio_similarity(track_id)
        score += audio_sim * self.config.recommendation.audio_similarity_weight
        details['audio_similarity'] = audio_sim
        if audio_sim > 0.5:
            reasons.append(f"Similar to preferred audio characteristics ({audio_sim:.2f})")

        # 2. Feedback similarity
        feedback_sim = self._calculate_feedback_similarity(track_id, feedback_state)
        score += feedback_sim * self.config.recommendation.feedback_similarity_weight
        details['feedback_similarity'] = feedback_sim
        if feedback_sim > 0.5:
            reasons.append(f"Matches feedback patterns ({feedback_sim:.2f})")

        # 3. Seed playlist similarity
        playlist_sim = self._calculate_playlist_similarity(track_id, feedback)
        score += playlist_sim * self.config.recommendation.seed_playlist_similarity_weight
        details['playlist_similarity'] = playlist_sim
        if playlist_sim > 0.5:
            reasons.append(f"Similar to seed playlists ({playlist_sim:.2f})")

        # 4. Discovery relevance
        discovery_rel = self._calculate_discovery_relevance(track_id)
        score += discovery_rel * self.config.recommendation.discovery_relevance_weight
        details['discovery_relevance'] = discovery_rel
        if discovery_rel > 0.5:
            reasons.append(f"High discovery relevance ({discovery_rel:.2f})")

        # 5. Novelty
        novelty = self._calculate_novelty(track_id)
        score += novelty * self.config.recommendation.novelty_weight
        details['novelty'] = novelty
        if novelty > 0.5:
            reasons.append(f"Novel exploration ({novelty:.2f})")

        # Combine reasons
        reason = "; ".join(reasons) if reasons else "General recommendation"

        return score, reason, details

    def _calculate_audio_similarity(self, track_id: int) -> float:
        """
        Calculate audio similarity to positively preferred tracks
        Placeholder - would need audio features and similarity computation
        """
        # TODO: Implement actual audio similarity calculation
        # For now, return a neutral value
        return 0.5

    def _calculate_feedback_similarity(self, track_id: int, feedback_state: str) -> float:
        """
        Calculate similarity based on feedback patterns
        """
        if feedback_state == FeedbackState.POSITIVE.value:
            return 1.0
        elif feedback_state == FeedbackState.NEGATIVE.value:
            return 0.0
        elif feedback_state == FeedbackState.NEUTRAL.value:
            return 0.5
        else:
            return 0.3  # Unknown

    def _calculate_playlist_similarity(self, track_id: int, feedback: Optional[Dict]) -> float:
        """
        Calculate similarity to seed playlists
        """
        if not feedback:
            return 0.0

        score = 0.0

        # Check if in primary playlist
        if feedback.get('in_seed_playlist_primary'):
            score += self.config.recommendation.seed_playlist_primary_weight

        # Check if in secondary playlist (stronger signal)
        if feedback.get('in_seed_playlist_secondary'):
            score += self.config.recommendation.seed_playlist_secondary_weight

        # Normalize to 0-1 range
        max_score = (self.config.recommendation.seed_playlist_primary_weight +
                    self.config.recommendation.seed_playlist_secondary_weight)
        if max_score > 0:
            score = score / max_score

        return score

    def _calculate_discovery_relevance(self, track_id: int) -> float:
        """
        Calculate discovery source relevance
        """
        # Check if track is from Top 100 or other discovery sources
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                SELECT COUNT(*) FROM discovery_candidates
                WHERE track_id = ?
                """,
                (track_id,)
            )
            result = cursor.fetchone()
            if result and result[0] > 0:
                # Track is from discovery source
                return 0.7
            else:
                # Track from library
                return 0.5

    def _calculate_novelty(self, track_id: int) -> float:
        """
        Calculate novelty score (underexplored tracks get higher scores)
        """
        # Check how recently track was recommended
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                SELECT MAX(r.generated_at) FROM recommendations r
                JOIN recommendation_entries re ON r.id = re.recommendation_id
                WHERE re.track_id = ?
                """,
                (track_id,)
            )
            result = cursor.fetchone()
            if result and result[0]:
                last_recommended = datetime.fromisoformat(result[0])
                days_since = (datetime.now() - last_recommended).days
                # More recent = lower novelty
                if days_since < 7:
                    return 0.2
                elif days_since < 30:
                    return 0.5
                else:
                    return 0.8
            else:
                # Never recommended = high novelty
                return 1.0

    def _apply_artist_diversity(self, candidates: List[CandidateScore], limit: int) -> List[CandidateScore]:
        """
        Apply artist diversity constraints to ranked list

        Args:
            candidates: List of scored candidates
            limit: Maximum number of tracks

        Returns:
            Filtered list with artist diversity applied
        """
        if not candidates:
            return candidates

        result = []
        artist_counts = {}
        consecutive_count = 0
        last_artist = None

        for candidate in candidates:
            artist = candidate.artist

            # Check consecutive limit
            if artist == last_artist:
                consecutive_count += 1
            else:
                consecutive_count = 1
                last_artist = artist

            if consecutive_count > self.config.recommendation.max_consecutive_same_artist:
                continue

            # Check percentage limit
            current_count = artist_counts.get(artist, 0)
            if len(result) > 0:
                percentage = (current_count + 1) / len(result) * 100
                if percentage > self.config.recommendation.max_artist_percentage:
                    continue

            # Add candidate
            result.append(candidate)
            artist_counts[artist] = current_count + 1

            # Stop if we've reached limit
            if len(result) >= limit:
                break

        return result

    def get_candidate_pool(self) -> List[int]:
        """
        Get pool of candidate tracks for recommendation

        Returns:
            List of track IDs
        """
        candidate_ids = []

        # Get tracks from library
        with self.database.connect() as conn:
            cursor = conn.execute(
                "SELECT id FROM tracks WHERE is_local = 1"
            )
            candidate_ids.extend([row[0] for row in cursor.fetchall()])

        # Get tracks from discovery candidates
        with self.database.connect() as conn:
            cursor = conn.execute(
                "SELECT track_id FROM discovery_candidates WHERE track_id IS NOT NULL AND is_available = 1"
            )
            for row in cursor.fetchall():
                if row[0] not in candidate_ids:
                    candidate_ids.append(row[0])

        logger.info(f"Candidate pool size: {len(candidate_ids)}")
        return candidate_ids
