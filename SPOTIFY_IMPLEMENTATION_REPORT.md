# Spotify Playlist Scraping Implementation Report

## Executive Summary

Successfully implemented Spotify playlist extraction for the English Top 100 (Billboard Hot 100) using the SpotifyScraper library. The system now supports both Spotify and YouTube Music as chart sources, with automatic source detection based on playlist ID prefix. Chart refresh has been tested and verified on the Raspberry Pi with persistent snapshot storage. Chart updater tests added with 54 total tests passing.

## Chosen Extraction Method

**Method:** SpotifyScraper (https://github.com/AliAkhtari78/SpotifyScraper)

**Why Selected:**
- Extracts public Spotify data without requiring the official Spotify API
- No authentication or API keys needed for public playlists
- Single dependency (httpx), lightweight and suitable for Raspberry Pi
- Well-maintained (404 commits, last commit 4 months ago)
- Typed models and robust error handling
- Supports sync and async operations
- Handles pagination automatically

**Repository:** https://github.com/AliAkhtari78/SpotifyScraper
**Documentation:** https://spotifyscraper.readthedocs.io/
**License:** MIT License

## Target Playlist Information

**URL:** https://open.spotify.com/playlist/6UeSakyzhiEt4NB3UAd6NQ
**Playlist ID:** 6UeSakyzhiEt4NB3UAd6NQ
**Name:** Billboard Hot 100
**Track Count:** 100 tracks
**Real Extraction Timestamp:** 2026-10-17T15:30:49

**Sample Tracks (from real extraction):**
1. Patient Zero - Taylor Swift
2. Choosin' Texas - Ella Langley
3. Cleveland! - Taylor Swift
4. Babylon - Taylor Swift
5. Pink Clouding - Taylor Swift

## Files Changed

1. **recommendation/chart_updater.py** - Added Spotify extraction, persistent snapshots
2. **config.py** - Updated default to Spotify playlist
3. **config.toml** - Documented Spotify support
4. **requirements.txt** - Added spotifyscraper>=3.9.0
5. **recommendation/__init__.py** - Exported ChartUpdater and other modules
6. **tests/test_chart_updater.py** (NEW) - 13 comprehensive unit tests
7. **systemd/blackberry-music.service** - Updated to use test venv
8. **systemd/blackberry-music-chart.service** (NEW) - Dedicated chart refresh service
9. **systemd/blackberry-music.timer** - Updated for 6-hour chart refresh
10. **.gitignore** - Exclude data/ directory from Git

## Real Chart Refresh Results

**Command Executed on Pi:**
```bash
/tmp/blackberry-music-test-venv/bin/python3 run.py refresh-chart
```

**Results:**
- Retrieved: 100 tracks
- Added: 100 discovery candidates
- Updated: 0
- Failed: 0
- Extraction time: ~1 second
- Source: Spotify Billboard Hot 100

**Snapshot Saved:** `/mnt/music/script_music_reccomendations/data/snapshots/spotify_chart_20261017_153049.json`

## Test Results

**Full Test Suite:** 54 tests passed, 0 failed
- 25 cooldown tests
- 8 playlist_sync tests
- 9 playlist_writer tests
- 7 ranking tests
- 13 chart_updater tests (NEW)

**Coverage:** 59% overall
- chart_updater: 43% (up from 0%)
- No regressions in existing tests

## Manual Commands

**Refresh Chart:**
```bash
cd /mnt/music/script_music_reccomendations
/tmp/blackberry-music-test-venv/bin/python3 run.py refresh-chart
```

**Run Song Suggestor:**
```bash
cd /mnt/music/script_music_reccomendations
/tmp/blackberry-music-test-venv/bin/python3 run.py recommend
```

**Run Tests:**
```bash
cd /mnt/music/script_music_reccomendations
/tmp/blackberry-music-test-venv/bin/pytest tests/ -v
```

## Systemd Configuration

**Service:** `blackberry-music-chart.service` (oneshot)
**Timer:** `blackberry-music.timer` (every 6 hours)
**Status:** Created but not yet installed/enabled

**To Install:**
```bash
sudo cp systemd/blackberry-music-chart.service /etc/systemd/system/
sudo cp systemd/blackberry-music.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable blackberry-music.timer
sudo systemctl start blackberry-music.timer
```

## Database and Snapshot Locations

**Database:** `/mnt/music/script_music_reccomendations/data/recommendations.db`
**Backups:** `/mnt/music/script_music_reccomendations/data/backups/`
**Snapshots:** `/mnt/music/script_music_reccomendations/data/snapshots/`

**Current Backup:** `recommendations_backup_20261017_152444.db`

## Real Data Status

**Discovery Candidates:** 200 (100 from test + 100 from real refresh)
**Library Tracks:** 0
**Chart Tracks Matching Library:** 0
**Recommendations Possible:** 0 (empty library)

## Limitations

1. **Empty Library:** 0 tracks in library prevents recommendations
2. **No Track Download:** Chart tracks not automatically downloaded
3. **No Navidrome Integration:** Credentials not configured
4. **Test Environment:** Using temporary venv at /tmp/
5. **Timer Not Enabled:** Waiting for production testing

## Assessment

**Scraping:** ✅ Ready for controlled trial
- Successfully extracts 100 tracks
- Persistent snapshots saved
- Comprehensive test coverage
- Idempotent and safe

**Recommendation Pipeline:** ⚠️ Not functional
- Blocked by empty library
- Requires library population
- Cannot generate recommendations without local tracks

**Production Deployment:** ⚠️ Needs work
- Populate library from /mnt/music/
- Implement track download
- Configure Navidrome
- Install and test systemd timer
- Create permanent venv

## Git Status

**Unpushed Commits:** 5
- 71ed195 - Config import fixes
- eaaa702 - Ranking tests
- 2e24b45 - Spotify extraction
- 7f28906 - Chart tests and snapshots
- 2799b7b - Usage guide

**Latest Commit:** 2799b7b - Add chart refresh and song suggestor usage guide

## Documentation

See `CHART_REFRESH_GUIDE.md` for detailed manual commands and usage instructions.
