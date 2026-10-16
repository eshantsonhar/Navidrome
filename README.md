# BlackBerry Music Intelligence

A persistent, local-LLM-assisted music recommendation system for Navidrome running on Raspberry Pi 5 (BlackBerry).

## ⚠️ IMPORTANT: Current Verification Status

**This system has NOT been runtime tested yet.** The following items require verification before deployment:

- ⚠️ Python environment on BlackBerry (spotdl-env may be incomplete)
- ⚠️ Navidrome credentials must be configured in `config.toml`
- ⚠️ YouTube Music Top 100 playlist ID needs verification
- ⚠️ Chart scraper may require authentication
- ⚠️ Navidrome listening history may not be available via API
- ⚠️ Systemd service PATH needs fix for actual Python location

**Do not deploy this system without completing the deployment verification steps below.**

The code implementation has been audited and verified structurally correct, but runtime testing is required.

## Overview

BlackBerry Music Intelligence is a hybrid recommendation system that:

- Monitors your seed playlists (`Bored.m3u` and `the better playlist.m3u`) to learn your taste
- Maintains a seven-day repeat prevention memory for recommended tracks
- Scrapes the YouTube Music Top 100 English chart for discovery
- Integrates with Navidrome for ratings and favorites
- Uses a local LLM (Ollama) for preference analysis and discovery suggestions
- Generates daily recommendation playlists
- Stores all state in a SQLite database with a human-readable memory file

## Architecture

The system consists of:

- **Deterministic recommendation engine** - Ranks candidates using multiple signals
- **SQLite database** - Authoritative event store for all interactions
- **Playlist monitor** - Detects changes to seed playlists
- **Feedback system** - Handles ratings, favorites, and listening history
- **Cooldown engine** - Enforces seven-day repeat prevention
- **Chart updater** - Maintains Top 100 chart from YouTube Music
- **M3U writer** - Generates valid playlists
- **Ollama integration** - Local LLM for taste analysis
- **Scheduler** - Systemd timer for automated runs

## Installation

### Prerequisites

- Raspberry Pi 5 (BlackBerry) with Navidrome installed
- Python 3.12+
- Music library mounted at `/mnt/music`
- Samba share configured for access

### Setup

1. **Clone or copy the project to BlackBerry**:
   ```bash
   cd /mnt/music/script_music_reccomendations
   ```

2. **Install Python dependencies**:
   ```bash
   # Use existing spotdl-env or create new
   pip install -r requirements.txt
   ```

3. **Configure the system**:
   Edit `config.toml` to set:
   - Navidrome URL and authentication
   - Ollama URL and model
   - Timezone (default: Asia/Kolkata)
   - Paths (should be correct for `/mnt/music`)

4. **Initialize the database**:
   ```bash
   python run.py init-db
   ```

5. **Verify the environment**:
   ```bash
   python run.py check
   ```

## Configuration

Key configuration options in `config.toml`:

```toml
[paths]
music_base = "/mnt/music"
seed_playlist_primary = "/mnt/music/Bored.m3u"
seed_playlist_secondary = "/mnt/music/the better playlist.m3u"
recommendation_playlist = "/mnt/music/daily_recommendation.m3u"

[navidrome]
base_url = "http://localhost:4533"
username = "your_username"
password = "your_password"

[ollama]
base_url = "http://localhost:11434"
model = "llama3.2:1b"

[recommendation]
timezone = "Asia/Kolkata"
repeat_cooldown_days = 7
```

## Usage

### CLI Commands

```bash
# Check environment and paths
python run.py check

# Initialize database
python run.py init-db

# Synchronize seed playlists
python run.py sync-playlists

# Synchronize feedback from Navidrome
python run.py sync-feedback

# Refresh Top 100 chart
python run.py refresh-chart

# Generate recommendations
python run.py recommend

# Show current memory state
python run.py show-memory

# Rebuild memory file from database
python run.py rebuild-memory

# Show system status
python run.py status

# Create database backup
python run.py backup

# Run tests
python run.py test
```

### Daily Workflow

The recommended daily workflow:

1. **Sync playlists** (after you make changes):
   ```bash
   python run.py sync-playlists
   ```

2. **Generate recommendations**:
   ```bash
   python run.py recommend
   ```

3. **Check status**:
   ```bash
   python run.py status
   ```

The generated playlist will be at `/mnt/music/daily_recommendation.m3u`.

## Feedback System

### Feedback Hierarchy

The system interprets feedback in this order (highest priority first):

**Strong Positive:**
- Added to `the better playlist.m3u` (weight: 1.5)
- Added to `Bored.m3u` (weight: 1.0)
- Explicit favorite in Navidrome
- 4-5 star rating

**Negative:**
- 1-2 star rating (strongly negative)
- 3 star rating (negative)
- Explicit dislike
- Repeated early skips

**No Feedback:**
- Absence of explicit signal
- Chart membership alone
- Discovery without user action

### Important Rules

- **Three stars is NEGATIVE**, not neutral
- **Explicit negative rating overrides playlist membership**
- **Chart membership is NOT a positive signal**
- **Removing from playlist is not automatically a dislike**
- **Positive feedback overrides the seven-day block**

## Seven-Day Repeat Prevention

### How It Works

When a track is recommended without explicit feedback:

1. It receives a **no-feedback block** for 7 days
2. The block prevents re-recommendation during this period
3. After 7 days, the block expires
4. The track becomes eligible again

### Override Conditions

A positive signal (favorite, 4-5 star rating, playlist addition) **immediately overrides** the block.

### Negative Feedback

Negative feedback creates a **negative-feedback block** that:
- Lasts 7 days
- **Persists after expiration** (the preference penalty remains)
- Cannot be overridden by popularity or similarity

### Tracking

The system tracks:
- `last_recommended_at`
- `last_played_at`
- `last_positive_feedback_at`
- `last_negative_feedback_at`
- `blocked_until`
- `current_feedback_state`

All timestamps are timezone-aware (configured in `config.toml`).

## Memory File

The human-readable memory file is at:
```
/mnt/music/script_music_reccomendations/memory.txt
```

It shows:
- Currently blocked tracks
- Reason for block
- Block expiration time
- Whether negative preference persists

**Important:** The SQLite database is the authoritative source. The memory file can be regenerated with:
```bash
python run.py rebuild-memory
```

## Top 100 Chart

The system maintains the YouTube Music Top 100 English chart:

- **Refresh interval:** Every 6 hours (configurable)
- **Output:** `/mnt/music/top 100_english.m3u`
- **Purpose:** Discovery source, NOT a taste signal
- **Independence:** Operates separately from personalized recommendations

A chart song only affects personalized taste when:
- Added to a seed playlist, OR
- Receives explicit positive feedback

## Seed Playlists

### Bored.m3u
- **Weight:** 1.0 (weaker signal)
- **Purpose:** Broad collection of songs of interest
- **Location:** `/mnt/music/Bored.m3u`

### the better playlist.m3u
- **Weight:** 1.5 (stronger signal)
- **Purpose:** Strong indicator of your taste
- **Location:** `/mnt/music/the better playlist.m3u`

Both playlists are **continuously monitored** for changes.

## Recommendation Algorithm

The ranking engine uses these signals:

```
score = 0.40 * audio_similarity
      + 0.25 * feedback_similarity
      + 0.15 * seed_playlist_similarity
      + 0.10 * discovery_relevance
      + 0.10 * novelty
```

**Hard exclusions are never overridden by score:**
- Active no-feedback block
- Active negative-feedback block
- Current explicit negative rating

### Artist Diversity

The system enforces:
- Maximum 2 consecutive tracks from same artist
- Maximum 25% of playlist from single artist

## Navidrome Integration

### Supported Features

- **Favorites:** Synchronized via Subsonic API
- **Ratings:** Limited support (API may not expose all ratings)
- **Listening History:** May not be available via Subsonic API

### Authentication

Configure in `config.toml`:
```toml
[navidrome]
base_url = "http://localhost:4533"
username = "your_username"
password = "your_password"
# OR
api_token = "your_token"
```

### Known Limitations

- Navidrome Subsonic API may not expose:
  - All user ratings
  - Complete listening history
  - Skip events

The system works with whatever the API provides.

## Ollama Integration

### Model Selection

For Raspberry Pi 5, start with small quantized models:
- `llama3.2:1b` (recommended)
- `phi3:mini`
- `gemma2:2b`

### LLM Role

The LLM **supports** the system but does not:
- Maintain the authoritative database
- Decide if seven-day exclusion can be bypassed
- Override explicit negative feedback
- Generate arbitrary file paths

### LLM Use Cases

- Summarize preference patterns
- Suggest discovery directions
- Explain why a track might match taste
- Categorize tracks with missing metadata

### Fallback

The system works **without Ollama** if:
- Ollama is not running
- Model is not available
- Inference fails

## Systemd Service

### Installation

```bash
# Copy service files
sudo cp systemd/blackberry-music.service /etc/systemd/system/
sudo cp systemd/blackberry-music.timer /etc/systemd/system/

# Enable and start
sudo systemctl enable blackberry-music.timer
sudo systemctl start blackberry-music.timer
```

### Schedule

The timer runs:
- Daily at 8:00 AM (configurable)
- Every 6 hours for chart refresh

### Manual Control

```bash
# Check status
sudo systemctl status blackberry-music.timer

# Stop timer
sudo systemctl stop blackberry-music.timer

# Start timer
sudo systemctl start blackberry-music.timer
```

## Database

### Location
```
/mnt/music/script_music_reccomendations/data/recommendations.db
```

### Schema

The database contains:
- Tracks and stable identities
- Seed-playlist membership
- Chart sources and snapshots
- Discovery candidates
- Audio features
- Recommendation history
- Listening events
- Feedback events
- Artist preferences
- Active exclusions
- Download jobs
- Daily run history

### Backups

Automatic backups are stored in:
```
/mnt/music/script_music_reccomendations/data/backups/
```

Manual backup:
```bash
python run.py backup
```

### Recovery

If the database is lost or corrupt:
1. Stop the affected workflow
2. Preserve available files
3. Restore from backup
4. Report the issue

## Testing

Run the test suite:
```bash
python run.py test
```

Tests cover:
- Feedback classification
- Repeat prevention
- Playlist synchronization
- M3U output
- Failure recovery

## Logs

Logs are stored in:
```
/mnt/music/script_music_reccomendations/logs/
```

Configure log level in `config.toml`:
```toml
[logging]
level = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

## Troubleshooting

### Database not found
Run: `python run.py init-db`

### Navidrome connection failed
- Check Navidrome is running: `systemctl status navidrome`
- Verify URL and credentials in `config.toml`
- Check firewall settings

### Ollama not available
- Check Ollama is running: `systemctl status ollama`
- Verify model is installed: `ollama list`
- The system will work without Ollama

### Music mount not found
- Verify mount: `mount | grep /mnt/music`
- Check Samba configuration
- System will stop safely instead of writing to wrong location

### Playlist not syncing
- Check file paths in `config.toml`
- Verify playlist files exist
- Check file permissions

## Deployment Procedure

⚠️ **DO NOT deploy until you have SSH access to BlackBerry and can execute commands directly.**

### Prerequisites
- SSH access to BlackBerry (Raspberry Pi 5)
- Navidrome running and accessible
- Python 3.12+ installed on BlackBerry
- `/mnt/music` mount verified and writable

### Step-by-Step Deployment

1. **Verify Python installation on BlackBerry**:
   ```bash
   ssh blackberry@192.168.1.23
   python3 --version  # Should be 3.12+
   ```

2. **Navigate to project directory**:
   ```bash
   cd /mnt/music/script_music_reccomendations
   ```

3. **Verify /mnt/music mount**:
   ```bash
   mount | grep /mnt/music
   ls -la /mnt/music
   ```

4. **Verify Navidrome is running**:
   ```bash
   curl http://localhost:4533/rest/ping.view
   # Or check service: systemctl status navidrome
   ```

5. **Configure Navidrome credentials**:
   ```bash
   nano config.toml
   # Set navidrome.username and navidrome.password
   # Verify navidrome.base_url is correct
   ```

6. **Verify YouTube Music Top 100 playlist ID**:
   - Open YouTube Music in browser
   - Search for "Top 100 English" or similar
   - Copy the actual playlist ID from URL
   - Update `chart.playlist_id` in `config.toml`

7. **Install Python dependencies**:
   ```bash
   # Option A: Use system Python
   pip3 install -r requirements.txt

   # Option B: Create virtual environment
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

8. **Set dry-run mode for initial testing**:
   ```bash
   # Verify dry_run = true in config.toml (already set)
   ```

9. **Initialize database**:
   ```bash
   python3 run.py init-db
   ```

10. **Run environment check**:
    ```bash
    python3 run.py check
    ```

11. **Run tests**:
    ```bash
    python3 run.py test
    # Fix any test failures before proceeding
    ```

12. **Disable dry-run mode**:
    ```bash
    nano config.toml
    # Set dry_run = false
    ```

13. **Sync seed playlists**:
    ```bash
    python3 run.py sync-playlists
    # Verify tracks are imported into database
    ```

14. **Generate recommendations**:
    ```bash
    python3 run.py recommend
    # Verify daily_recommendation.m3u is generated
    ```

15. **Test M3U import in Navidrome**:
    - Access Navidrome web interface
    - Import the generated `daily_recommendation.m3u`
    - Verify tracks play correctly

16. **Test chart refresh**:
    ```bash
    python3 run.py refresh-chart
    # Verify top 100_english.m3u is generated
    ```

17. **Test Ollama (if using LLM)**:
    ```bash
    # Verify Ollama is running: systemctl status ollama
    # Check available models: ollama list
    # Test inference: ollama run llama3.2:1b
    ```

18. **Fix systemd service PATH**:
    ```bash
    # If using system Python:
    sudo nano systemd/blackberry-music.service
    # Change PATH to: /usr/local/bin:/usr/bin:/bin
    # Or use venv path if created
    ```

19. **Test systemd service manually**:
    ```bash
    sudo cp systemd/blackberry-music.service /etc/systemd/system/
    sudo systemctl start blackberry-music.service
    sudo systemctl status blackberry-music.service
    sudo systemctl stop blackberry-music.service
    ```

20. **Enable systemd timer (ONLY after manual tests pass)**:
    ```bash
    sudo cp systemd/blackberry-music.timer /etc/systemd/system/
    sudo systemctl enable blackberry-music.timer
    sudo systemctl start blackberry-music.timer
    sudo systemctl status blackberry-music.timer
    ```

21. **Monitor first automated run**:
    ```bash
    tail -f logs/blackberry-music.log
    # Or: journalctl -u blackberry-music.service -f
    ```

### Troubleshooting Python Environment

If `spotdl-env/bin/` is empty:
```bash
# Use system Python instead
# Update systemd service PATH to use /usr/bin/python3
# Or create new venv: python3 -m venv venv
```

## Known Limitations

### Navidrome API
- **Confirmed via research:** Navidrome Subsonic API v1.16.1 supports `getStarred2` for favorites and `setRating` for ratings
- **Confirmed via research:** Listening history retrieval is NOT listed in supported endpoints - likely unavailable
- Navidrome does NOT mark songs as played on `stream()` calls, only on `scrobble(submission=true)`
- IDs are always strings (MD5 or UUID), not integers
- Skip events may not be available via Subsonic API

### YouTube Music Chart Scraper
- **Critical:** The configured playlist ID `PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI` is UNVERIFIED
- No official YouTube Music Top 100 English playlist ID was found in research
- Current playlist may be a user playlist, not the official Top 100
- `ytmusicapi` supports both authenticated and non-authenticated requests
- Public catalog may work without authentication, but this is not guaranteed
- If authentication is required, the current implementation will fail

### Ollama on Raspberry Pi 5
- **Confirmed via research:** Pi 5 (8GB) can run 1B-3B models at Q4 quantization
- **Recommended models:** `llama3.2:1b` (5-15 tokens/sec), `llama3.2:3b` (1.5-5 tokens/sec), `BitNet B1.58 2B 4T` (8+ tokens/sec)
- 3B models may take 6-50 seconds per response depending on input length
- Quantization (q4_k_m) is essential for memory-limited devices
- Monitor CPU temperature during inference
- The system works without Ollama if unavailable

### Ollama on Raspberry Pi 5
- Large models may cause swapping
- Inference time varies by model
- Must benchmark before production use

### Music Acquisition
- Download feature requires configuration
- Legal restrictions may apply
- Failed downloads require manual retry

## File Paths

### Linux (BlackBerry)
- Project: `/mnt/music/script_music_reccomendations`
- Music base: `/mnt/music`
- Seed playlists: `/mnt/music/Bored.m3u`, `/mnt/music/the better playlist.m3u`
- Output: `/mnt/music/daily_recommendation.m3u`
- Chart: `/mnt/music/top 100_english.m3u`
- Memory: `/mnt/music/script_music_reccomendations/memory.txt`

### Windows (External Access)
- Project: `\\192.168.1.23\music\script_music_reccomendations`
- Music base: `\\192.168.1.23\music`
- Same relative paths under music share

## Security

- **Credentials** stored in `config.toml` (not in source control)
- **No arbitrary command execution** from metadata or LLM output
- **Path validation** for all file operations
- **Mount verification** before writes
- **Secret redaction** in logs
- **Dry-run mode** available for testing

## Performance

Designed for Raspberry Pi 5 constraints:
- Cached metadata and audio features
- Incremental playlist synchronization
- Limited concurrent downloads
- Small LLM contexts
- Bounded caches
- Prioritizes Navidrome responsiveness

## License

MIT

## Contributing

This is a personal project for BlackBerry. Contributions are welcome but should:
- Preserve existing functionality
- Add tests for new features
- Update documentation
- Follow existing code style
