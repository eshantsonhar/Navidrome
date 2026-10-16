"""
Ollama LLM integration
Provides local LLM support for recommendation enhancement
"""

import logging
import json
from typing import Dict, Optional, List
from dataclasses import dataclass

try:
    import requests
except ImportError:
    requests = None

import config

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Response from LLM"""
    content: str
    model: str
    success: bool
    error: str = ""


class OllamaClient:
    """Client for Ollama local LLM"""

    def __init__(self):
        self.config = config.get_config()
        self.base_url = self.config.ollama.base_url
        self.model = self.config.ollama.model
        self.timeout = self.config.ollama.timeout
        self.max_tokens = self.config.ollama.max_tokens
        self.available = False

    def check_availability(self) -> bool:
        """
        Check if Ollama is available

        Returns:
            True if available, False otherwise
        """
        if requests is None:
            logger.warning("requests library not available")
            return False

        try:
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                models = data.get('models', [])
                model_names = [m.get('name', '') for m in models]

                # Check if configured model is available
                if self.model in model_names:
                    self.available = True
                    logger.info(f"Ollama available with model: {self.model}")
                    return True
                else:
                    logger.warning(f"Model {self.model} not found. Available models: {model_names}")
                    return False
            else:
                logger.error(f"Ollama not available: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Ollama check failed: {e}")
            return False

    def generate(
        self,
        prompt: str,
        model: str = None,
        max_tokens: int = None,
        temperature: float = 0.7
    ) -> LLMResponse:
        """
        Generate text using Ollama

        Args:
            prompt: Input prompt
            model: Model to use (uses configured if None)
            max_tokens: Maximum tokens (uses configured if None)
            temperature: Sampling temperature

        Returns:
            LLMResponse object
        """
        if not self.available and not self.check_availability():
            return LLMResponse(
                content="",
                model=self.model,
                success=False,
                error="Ollama not available"
            )

        if model is None:
            model = self.model
        if max_tokens is None:
            max_tokens = self.max_tokens

        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    'model': model,
                    'prompt': prompt,
                    'stream': False,
                    'options': {
                        'num_predict': max_tokens,
                        'temperature': temperature
                    }
                },
                timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()
                content = data.get('response', '')
                return LLMResponse(
                    content=content,
                    model=model,
                    success=True
                )
            else:
                error_msg = f"Ollama API error: {response.status_code}"
                logger.error(error_msg)
                return LLMResponse(
                    content="",
                    model=model,
                    success=False,
                    error=error_msg
                )

        except Exception as e:
            error_msg = f"Ollama generation error: {e}"
            logger.error(error_msg)
            return LLMResponse(
                content="",
                model=model,
                success=False,
                error=error_msg
            )

    def generate_json(
        self,
        prompt: str,
        schema: Dict,
        model: str = None,
        max_tokens: int = None
    ) -> Optional[Dict]:
        """
        Generate structured JSON output using Ollama

        Args:
            prompt: Input prompt
            schema: Expected JSON schema
            model: Model to use
            max_tokens: Maximum tokens

        Returns:
            Parsed JSON dictionary or None if failed
        """
        # Add JSON instruction to prompt
        json_prompt = f"{prompt}\n\nRespond with valid JSON matching this schema:\n{json.dumps(schema, indent=2)}"

        response = self.generate(json_prompt, model, max_tokens)

        if not response.success:
            return None

        try:
            # Try to parse JSON from response
            # Look for JSON in code blocks or raw text
            content = response.content.strip()

            # Remove code block markers if present
            if content.startswith('```json'):
                content = content[7:]
            if content.startswith('```'):
                content = content[3:]
            if content.endswith('```'):
                content = content[:-3]

            content = content.strip()

            parsed = json.loads(content)
            return parsed

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from LLM response: {e}")
            logger.debug(f"Response content: {response.content}")
            return None

    def summarize_preferences(self, feedback_data: Dict) -> Optional[str]:
        """
        Summarize user preferences from feedback data

        Args:
            feedback_data: Dictionary with feedback statistics

        Returns:
            Summary text or None if failed
        """
        prompt = f"""
Analyze this music feedback data and summarize the user's preferences:

{json.dumps(feedback_data, indent=2)}

Provide a concise summary of:
1. Favorite artists
2. Preferred genres
3. Musical characteristics the user enjoys
4. Any patterns in their listening habits

Keep the summary under 200 words.
"""

        response = self.generate(prompt, max_tokens=500)

        if response.success:
            return response.content
        else:
            return None

    def suggest_discovery_directions(self, preference_summary: str) -> Optional[List[str]]:
        """
        Suggest discovery directions based on preferences

        Args:
            preference_summary: Summary of user preferences

        Returns:
            List of suggested directions or None if failed
        """
        prompt = f"""
Based on this preference summary:
{preference_summary}

Suggest 3-5 discovery directions for finding new music the user might enjoy.
Each direction should be a short phrase (e.g., "indie electronic with female vocals").

Respond as a JSON array of strings.
"""

        schema = {
            "type": "array",
            "items": {"type": "string"}
        }

        result = self.generate_json(prompt, schema, max_tokens=300)

        if result:
            return result
        else:
            return None

    def explain_recommendation(self, track: Dict, preferences: Dict) -> Optional[str]:
        """
        Explain why a track might match user preferences

        Args:
            track: Track information
            preferences: User preference data

        Returns:
            Explanation text or None if failed
        """
        prompt = f"""
Explain why this track might match the user's preferences:

Track: {track.get('title')} by {track.get('artist')}
Genre: {track.get('genre')}
Year: {track.get('year')}

User preferences:
{json.dumps(preferences, indent=2)}

Provide a brief explanation (under 100 words) of why this track might appeal to the user.
"""

        response = self.generate(prompt, max_tokens=200)

        if response.success:
            return response.content
        else:
            return None

    def categorize_track(self, track: Dict) -> Optional[Dict]:
        """
        Categorize a track with missing metadata

        Args:
            track: Track information (may have missing fields)

        Returns:
            Dictionary with suggested metadata or None if failed
        """
        prompt = f"""
Categorize this track:

Title: {track.get('title')}
Artist: {track.get('artist')}

Suggest:
1. Genre
2. Mood (e.g., energetic, calm, melancholic)
3. Era (e.g., 2000s, 2010s, 2020s)

Respond as JSON with keys: genre, mood, era.
"""

        schema = {
            "type": "object",
            "properties": {
                "genre": {"type": "string"},
                "mood": {"type": "string"},
                "era": {"type": "string"}
            }
        }

        result = self.generate_json(prompt, schema, max_tokens=200)

        if result:
            return result
        else:
            return None
