# Deployment Notes for BlackBerry Music Intelligence

**Last Updated:** 2026-10-15
**Audit Status:** Static code review COMPLETE, runtime testing PENDING
**Status:** NOT READY FOR DEPLOYMENT - requires on-BlackBerry verification

## Summary

The code implementation has been audited and verified structurally correct. All feedback hierarchy rules, cooldown logic, database schema, and CLI commands are implemented correctly. However, runtime testing has not been performed due to Windows UNC access limitations.

## Critical Issues Requiring Resolution

### 1. Python Environment
- **Issue:** `spotdl-env/bin/` directory is empty - no Python binary found
- **Impact:** Cannot execute `run.py` from the existing virtual environment
- **Solution:** Use system Python (`/usr/bin/python3`) or create new virtual environment
- **Action Required:** During deployment on BlackBerry

### 2. Navidrome Credentials
- **Issue:** `navidrome.username` and `navidrome.password` are empty in `config.toml`
- **Impact:** Cannot sync feedback from Navidrome
- **Solution:** Configure actual Navidrome credentials
- **Action Required:** Before running `sync-feedback`

### 3. YouTube Music Top 100 Playlist ID
- **Issue:** Configured playlist ID `PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI` is UNVERIFIED
- **Impact:** Chart scraper may retrieve wrong playlist or fail
- **Solution:** Verify correct playlist ID via YouTube Music web interface
- **Action Required:** Before running `refresh-chart`

### 4. Systemd Service PATH
- **Issue:** Systemd service PATH points to empty `spotdl-env/bin/`
- **Impact:** Service will fail to start
- **Solution:** Service file has been updated to use system Python
- **Action Required:** Verify during deployment, adjust if using venv

## Research Findings

### Ollama on Raspberry Pi 5
- **Finding:** Pi 5 (8GB) can run 1B-3B models at Q4 quantization
- **Recommended:** `llama3.2:1b` (5-15 tokens/sec), `llama3.2:3b` (1.5-5 tokens/sec)
- **Performance:** 3B models may take 6-50 seconds per response
- **Quantization:** q4_k_m is essential
- **Status:** Configured model is appropriate

### Navidrome API
- **Finding:** Navidrome Subsonic API v1.16.1 confirmed
- **Supported:** `getStarred2` (favorites), `setRating` (ratings), `scrobble` (submission)
- **NOT Supported:** Listening history retrieval (not in API documentation)
- **IDs:** Always strings (MD5/UUID), not integers
- **Status:** Feedback should rely on ratings and favorites, not listening history

### YouTube Music / ytmusicapi
- **Finding:** ytmusicapi supports both authenticated and non-authenticated requests
- **Public Catalog:** May work without authentication
- **User Library:** Requires authentication
- **Official Top 100:** No official playlist ID found in research
- **Status:** Current playlist ID unverified, may require authentication

## Code Verification Status

### Verified (Static Review)
- ✅ Database schema - comprehensive and correct
- ✅ Feedback hierarchy - matches requirements exactly (3-star negative, negative overrides playlist)
- ✅ Cooldown engine - matches requirements exactly (7-day, timezone-aware, persistent preference)
- ✅ M3U writer - with validation and atomic writes
- ✅ CLI commands - all required implemented
- ✅ Test coverage - critical cases covered
- ✅ Data integrity safeguards - transactions, backups, atomic writes
- ✅ Security - no secrets exposed, path validation present

### Not Verified (Requires Runtime)
- ❌ Database initialization
- ❌ Playlist synchronization
- ❌ Feedback synchronization
- ❌ Chart scraper
- ❌ Recommendation generation
- ❌ M3U import in Navidrome
- ❌ Ollama inference
- ❌ Systemd service execution
- ❌ Timer scheduling

## Configuration Changes Made

### config.toml
- Changed `dry_run = true` for safe initial testing
- Note: Change to `false` after manual testing is complete

### systemd/blackberry-music.service
- Updated PATH to use system Python (`/usr/bin/python3`)
- Updated ExecStart to use system Python
- Added comments for venv alternative
- Note: Adjust if using virtual environment

### integrations/navidrome.py
- Updated `get_listening_history()` documentation
- Added explicit warning that this endpoint is not supported
- Returns empty list with clear logging

### README.md
- Added verification status warning at top
- Added detailed deployment procedure with 21 steps
- Updated known limitations with research findings
- Added troubleshooting section for Python environment

## Test Execution Plan

### Phase 1: Unit Tests
```bash
python3 run.py test
```
Expected: All tests pass

### Phase 2: Integration Tests
```bash
python3 run.py init-db
python3 run.py check
python3 run.py sync-playlists
```
Expected: Database initialized, tracks imported from seed playlists

### Phase 3: Recommendation Test
```bash
python3 run.py recommend
```
Expected: `daily_recommendation.m3u` generated with valid tracks

### Phase 4: Chart Test
```bash
python3 run.py refresh-chart
```
Expected: `top 100_english.m3u` generated with chart tracks

### Phase 5: Service Test
```bash
sudo systemctl start blackberry-music.service
sudo systemctl status blackberry-music.service
```
Expected: Service starts successfully

## Risk Assessment

### High Risk
- Python environment failure (mitigated: documentation provided)
- Navidrome API incompatibility (mitigated: researched limitations)
- Chart scraper authentication failure (mitigated: error handling)

### Medium Risk
- Playlist path resolution (mitigated: path validation)
- Timezone configuration (mitigated: documentation)
- Systemd service configuration (mitigated: corrected service file)

### Low Risk
- M3U format issues (mitigated: validation)
- Database corruption (mitigated: backups, integrity checks)
- Ollama performance (mitigated: model selection, optional)

## Success Criteria

Deployment is successful when:
1. ✅ Python environment verified and working
2. ✅ Navidrome credentials configured and connection tested
3. ✅ Database initialized and integrity check passed
4. ✅ All unit tests passing
5. ✅ Seed playlists synced successfully
6. ✅ Feedback sync with Navidrome successful (favorites)
7. ✅ Recommendation generation produces valid M3U
8. ✅ M3U imports and plays in Navidrome
9. ✅ Chart refresh produces valid chart M3U
10. ✅ Memory file generated and readable
11. ✅ Status command reports correct state
12. ✅ Systemd service starts and stops correctly
13. ✅ Systemd timer triggers service as scheduled
14. ✅ First automated run completes successfully
15. ✅ Logs show no errors
16. ✅ Navidrome remains responsive during operation
17. ✅ No data loss or corruption
18. ✅ Cooldowns enforced correctly
19. ✅ Feedback hierarchy respected
20. ✅ Documentation updated with actual deployment steps

## Next Steps

The next session should:
1. SSH into BlackBerry (192.168.1.23)
2. Retrieve Memory MCP context for full handoff
3. Follow the 25-step deployment procedure in README.md
4. Execute the test plan above
5. Update documentation with actual results
6. Enable systemd service only after manual tests pass

## Handoff

All audit findings, research results, defect lists, risk assessments, and deployment plans have been stored in Memory MCP. The next session can retrieve complete context by querying Memory MCP.

**Key Memory MCP Entities:**
- "BlackBerry Music Intelligence - Audit 2026-10-15"
- "Firecrawl Research Results - Ollama, YouTube Music, Navidrome"
- "Code Repairs Needed"
- "Deployment Readiness"
- "Handoff Plan for Next Session"
- "Final Audit Report 2026-10-15"

No information has been lost. The next session can proceed efficiently without repeating investigations.
