"""
Memory file writer
Generates human-readable memory.txt from database
"""

import logging
from pathlib import Path
from typing import List, Dict
from datetime import datetime

from config import get_config
from database import Database
from .cooldown import ExclusionType

logger = logging.getLogger(__name__)


class MemoryWriter:
    """Generates human-readable memory file from database"""

    def __init__(self, database: Database):
        self.database = database
        self.config = get_config()

    def generate_memory_file(self, output_path: str = None) -> str:
        """
        Generate memory.txt file from database

        Args:
            output_path: Path for output file. If None, uses configured path.

        Returns:
            Path to generated file
        """
        if output_path is None:
            output_path = self.config.paths.memory_file

        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Generate content
        content = self._generate_content()

        # Write to temporary file first
        temp_file = output_file.with_suffix('.tmp')
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(content)

        # Atomic replace
        temp_file.replace(output_file)

        logger.info(f"Generated memory file at {output_path}")
        return str(output_file)

    def _generate_content(self) -> str:
        """Generate memory file content"""
        lines = []

        # Header
        lines.append("# BlackBerry Music Intelligence")
        lines.append("# Automatically generated recommendation memory")
        lines.append("# SQLite is the authoritative event store.")
        lines.append("# This file can be regenerated from the database.")
        lines.append("")
        lines.append(f"# Generated at: {datetime.now().isoformat()}")
        lines.append("")

        # Get active exclusions
        no_feedback = self._get_exclusions_by_type(ExclusionType.NO_FEEDBACK)
        negative = self._get_exclusions_by_type(ExclusionType.NEGATIVE_FEEDBACK)
        manual = self._get_exclusions_by_type(ExclusionType.MANUAL)

        # NO_FEEDBACK section
        if no_feedback:
            lines.append("[NO_FEEDBACK]")
            for exclusion in no_feedback:
                lines.append(self._format_exclusion(exclusion))
            lines.append("")

        # NEGATIVE section
        if negative:
            lines.append("[NEGATIVE]")
            for exclusion in negative:
                lines.append(self._format_exclusion(exclusion))
            lines.append("")

        # MANUAL section
        if manual:
            lines.append("[MANUAL]")
            for exclusion in manual:
                lines.append(self._format_exclusion(exclusion))
            lines.append("")

        # If no exclusions
        if not no_feedback and not negative and not manual:
            lines.append("# No active exclusions")
            lines.append("")

        # Summary
        lines.append("# Summary")
        lines.append(f"# Total active exclusions: {len(no_feedback) + len(negative) + len(manual)}")
        lines.append(f"# No-feedback blocks: {len(no_feedback)}")
        lines.append(f"# Negative feedback blocks: {len(negative)}")
        lines.append(f"# Manual blocks: {len(manual)}")

        return "\n".join(lines)

    def _get_exclusions_by_type(self, exclusion_type: ExclusionType) -> List[Dict]:
        """Get exclusions of a specific type with track info"""
        with self.database.connect() as conn:
            cursor = conn.execute(
                """
                SELECT e.*, t.title, t.artist, t.navidrome_id
                FROM exclusions e
                JOIN tracks t ON e.track_id = t.id
                WHERE e.exclusion_type = ? AND julianday(e.blocked_until) > julianday('now')
                ORDER BY e.blocked_until ASC
                """,
                (exclusion_type.value,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def _format_exclusion(self, exclusion: Dict) -> str:
        """Format exclusion as human-readable line"""
        track_id = exclusion.get('navidrome_id') or f"local:{exclusion['track_id']}"
        title = exclusion['title']
        artist = exclusion['artist']
        blocked_until = exclusion['blocked_until']
        reason = exclusion['reason']
        preference_persistent = exclusion.get('preference_persistent', False)

        lines = [
            f"track_id={track_id}",
            f"title={title}",
            f"artist={artist}",
            f"blocked_until={blocked_until}",
            f"reason={reason}"
        ]

        if preference_persistent:
            lines.append("preference_penalty=persistent")

        if exclusion.get('last_recommended_at'):
            lines.append(f"last_recommended_at={exclusion['last_recommended_at']}")

        if exclusion.get('last_played_at'):
            lines.append(f"last_played_at={exclusion['last_played_at']}")

        return "\n".join(f"  {line}" for line in lines)

    def print_memory(self):
        """Print memory to console"""
        content = self._generate_content()
        print(content)

    def get_memory_summary(self) -> Dict:
        """
        Get summary of memory state

        Returns:
            Dictionary with memory statistics
        """
        from .cooldown import CooldownEngine
        cooldown = CooldownEngine(self.database)
        summary = cooldown.get_exclusion_summary()

        # Add details
        summary['no_feedback_details'] = self._get_exclusions_by_type(ExclusionType.NO_FEEDBACK)
        summary['negative_details'] = self._get_exclusions_by_type(ExclusionType.NEGATIVE_FEEDBACK)
        summary['manual_details'] = self._get_exclusions_by_type(ExclusionType.MANUAL)

        return summary
