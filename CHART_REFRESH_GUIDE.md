# Chart Refresh and Song Suggestor Guide

## Manual Commands

### Refresh Chart Manually
```bash
cd /mnt/music/script_music_reccomendations
/tmp/blackberry-music-test-venv/bin/python3 run.py refresh-chart
```

### Display Last Refresh Status
```bash
cd /mnt/music/script_music_reccomendations
/tmp/blackberry-music-test-venv/bin/python3 -c "
from database import Database
from config import get_config
import config

db = Database(get_config().paths.database_path)

with db.connect() as conn:
    cursor = conn.execute('''
        SELECT name, source_type, last_refreshed_at, last_refresh_successful
        FROM chart_sources
    ''')
    result = cursor.fetchone()
    if result:
        print(f'Source: {result[0]}')
        print(f'Type: {result[1]}')
        print(f'Last refreshed: {result[2]}')
        print(f'Successful: {result[3]}')
    else:
        print('No chart refresh history found')
"
```

### View Current Chart Data
```bash
cd /mnt/music/script_music_reccomendations
/tmp/blackberry-music-test-venv/bin/python3 -c "
from database import Database
from config import get_config
import config

db = Database(get_config().paths.database_path)

with db.connect() as conn:
    cursor = conn.execute('SELECT COUNT(*) FROM discovery_candidates WHERE source_type = \"spotify\"')
    count = cursor.fetchone()[0]
    print(f'Total Spotify discovery candidates: {count}')
    
    cursor = conn.execute('''
        SELECT title, artist, source_rank
        FROM discovery_candidates
        WHERE source_type = \"spotify\"
        ORDER BY source_rank
        LIMIT 10
    ''')
    print('\nTop 10 tracks:')
    for row in cursor.fetchall():
        print(f'  {row[2]}. {row[0]} - {row[1]}')
"
```

### Inspect Refresh Failures and Logs
```bash
# View journal logs for chart refresh service
journalctl -u blackberry-music-chart.service -n 50

# View logs for timer
journalctl -u blackberry-music.timer -n 50

# Check application logs
tail -f /mnt/music/script_music_reccomendations/logs/*.log
```

### Run Song Suggestor (Test Mode)
```bash
cd /mnt/music/script_music_reccomendations
/tmp/blackberry-music-test-venv/bin/python3 run.py recommend
```

### Run Focused Chart Updater Tests
```bash
cd /mnt/music/script_music_reccomendations
/tmp/blackberry-music-test-venv/bin/pytest tests/test_chart_updater.py -v
```

### Run Full Test Suite
```bash
cd /mnt/music/script_music_reccomendations
/tmp/blackberry-music-test-venv/bin/pytest tests/ -v
```

### Check Systemd Service and Timer Status
```bash
# Check chart refresh service status
systemctl status blackberry-music-chart.service

# Check timer status
systemctl status blackberry-music.timer

# List all timers
systemctl list-timers

# Check next scheduled run
systemctl list-timers --all
```

## Install and Enable Systemd Timer

After testing is complete, install and enable the timer:

```bash
# Copy service files to systemd directory
sudo cp systemd/blackberry-music-chart.service /etc/systemd/system/
sudo cp systemd/blackberry-music.timer /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable and start the timer
sudo systemctl enable blackberry-music.timer
sudo systemctl start blackberry-music.timer

# Verify status
systemctl status blackberry-music.timer
```

## Disable Systemd Timer

```bash
sudo systemctl stop blackberry-music.timer
sudo systemctl disable blackberry-music.timer
```

## Snapshot Location

Chart snapshots are saved to:
```
/mnt/music/script_music_reccomendations/data/snapshots/
```

Snapshots are named: `{source_type}_chart_{timestamp}.json`

Example: `spotify_chart_20261017_153049.json`

## Database Backup Location

Backups are saved to:
```
/mnt/music/script_music_reccomendations/data/backups/
```

Create a manual backup:
```bash
cd /mnt/music/script_music_reccomendations
cp data/recommendations.db data/backups/recommendations_backup_$(date +%Y%m%d_%H%M%S).db
```

## Current Configuration

- **Target Playlist:** Spotify Billboard Hot 100 (6UeSakyzhiEt4NB3UAd6NQ)
- **Refresh Interval:** 6 hours
- **Max Tracks:** 100
- **Database:** /mnt/music/script_music_reccomendations/data/recommendations.db
- **Virtual Environment:** /tmp/blackberry-music-test-venv

## Limitations

1. **No Library Matching:** Chart entries are discovery candidates only. They are not automatically matched to local library tracks.
2. **No Download Integration:** Tracks from the chart are not automatically downloaded.
3. **Empty Library:** The current library has 0 tracks, so recommendations will be limited.
4. **No Navidrome Credentials:** Navidrome integration requires credentials in config.toml.
5. **Test Environment:** Using temporary virtual environment (/tmp/). Consider creating a permanent venv.
