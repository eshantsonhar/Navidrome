#!/usr/bin/env python3
"""
BlackBerry Music Intelligence - Main Entry Point
Persistent, local-LLM-assisted music recommendation system for Navidrome
"""

import sys
import logging
from pathlib import Path
from config import get_config, load_config
from database import Database

# Setup logging
def setup_logging(level: str = "INFO"):
    """Configure logging"""
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def check_environment():
    """
    Perform read-only environment checks
    Verifies paths, mounts, configuration, and service availability
    """
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel

    console = Console()
    config = get_config()

    console.print(Panel.fit("[bold blue]BlackBerry Music Intelligence - Environment Check[/bold blue]"))

    # Check paths
    table = Table(title="Path Verification")
    table.add_column("Path", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Notes", style="yellow")

    paths_to_check = [
        ("Music Base", config.paths.music_base),
        ("Project Directory", config.paths.project_dir),
        ("Seed Playlist (Primary)", config.paths.seed_playlist_primary),
        ("Seed Playlist (Secondary)", config.paths.seed_playlist_secondary),
        ("Recommendation Directory", config.paths.recommendation_dir),
        ("Top 100 Playlist", config.paths.top_100_playlist),
        ("Database Path", config.paths.database_path),
        ("Memory File", config.paths.memory_file),
    ]

    for name, path in paths_to_check:
        path_obj = Path(path)
        if path_obj.exists():
            if path_obj.is_dir():
                status = "✓ Directory exists"
            else:
                status = "✓ File exists"
            notes = ""
        else:
            status = "✗ Not found"
            notes = "Will be created"
        table.add_row(name, status, notes)

    console.print(table)

    # Check mount
    if config.security.verify_mount:
        mount_check = Path(config.security.expected_mount)
        if mount_check.exists() and mount_check.is_mount():
            console.print(f"[green]✓ Music mount verified at {config.security.expected_mount}[/green]")
        else:
            console.print(f"[red]✗ Music mount not found at {config.security.expected_mount}[/red]")
            console.print("[yellow]Note: This check must be run on BlackBerry, not from Windows access[/yellow]")

    # Check database
    db_path = Path(config.paths.database_path)
    if db_path.exists():
        try:
            db = Database(str(db_path))
            db.connect()
            version = db.get_schema_version()
            integrity = db.check_integrity()
            db.close()

            console.print(f"[green]✓ Database exists (schema version {version})[/green]")
            if integrity:
                console.print("[green]✓ Database integrity check passed[/green]")
            else:
                console.print("[red]✗ Database integrity check failed[/red]")
        except Exception as e:
            console.print(f"[red]✗ Database error: {e}[/red]")
    else:
        console.print("[yellow]Database not found (will be created on first run)[/yellow]")

    # Check seed playlists
    console.print("\n[bold]Seed Playlist Status:[/bold]")
    for name, path in [
        ("Primary", config.paths.seed_playlist_primary),
        ("Secondary", config.paths.seed_playlist_secondary)
    ]:
        playlist_path = Path(path)
        if playlist_path.exists():
            try:
                with open(playlist_path, 'r') as f:
                    lines = f.readlines()
                track_count = sum(1 for line in lines if line and not line.startswith('#'))
                console.print(f"[green]✓ {name}: {track_count} tracks[/green]")
            except Exception as e:
                console.print(f"[red]✗ {name}: Error reading file: {e}[/red]")
        else:
            console.print(f"[red]✗ {name}: File not found[/red]")

    # Note about service checks
    console.print("\n[yellow]Note: Navidrome and Ollama service checks require running on BlackBerry[/yellow]")
    console.print("[yellow]Use SSH to verify: systemctl status navidrome, systemctl status ollama[/yellow]")


def init_database():
    """Initialize database with schema"""
    config = get_config()
    db = Database(config.paths.database_path)

    if Path(config.paths.database_path).exists():
        print("Database already exists. Use migrations to upgrade if needed.")
        return

    print(f"Initializing database at {config.paths.database_path}")
    db.initialize_schema()
    db.close()
    print("Database initialized successfully")


def sync_playlists():
    """Synchronize seed playlists"""
    from config import get_config
    from database import Database
    from recommendation import PlaylistMonitor

    config = get_config()
    db = Database(config.paths.database_path)

    try:
        # Initialize database if needed
        if not Path(config.paths.database_path).exists():
            print("Database not found. Run 'init-db' first.")
            return

        monitor = PlaylistMonitor(db)

        # Register playlists
        monitor.register_all_seed_playlists()

        # Sync playlists
        results = monitor.sync_all_seed_playlists()

        print("Playlist synchronization complete:")
        for playlist_name, stats in results.items():
            print(f"  {playlist_name}:")
            print(f"    Added: {stats['added']}")
            print(f"    Removed: {stats['removed']}")
            print(f"    Unchanged: {stats['unchanged']}")
            print(f"    Total: {stats['total']}")

    except Exception as e:
        print(f"Error syncing playlists: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def sync_feedback():
    """Synchronize feedback from Navidrome"""
    from config import get_config
    from database import Database
    from integrations import NavidromeClient
    from recommendation import MusicLibrary, FeedbackSystem

    config = get_config()
    db = Database(config.paths.database_path)

    try:
        if not Path(config.paths.database_path).exists():
            print("Database not found. Run 'init-db' first.")
            return

        # Connect to Navidrome
        navidrome = NavidromeClient()
        if not navidrome.connect():
            print("Failed to connect to Navidrome")
            return

        library = MusicLibrary(db)
        feedback = FeedbackSystem(db)

        # Get favorites
        favorites = navidrome.get_favorites()
        print(f"Found {len(favorites)} favorited tracks in Navidrome")

        # Sync favorites
        for navidrome_id in favorites:
            # Find track by Navidrome ID
            with db.connect() as conn:
                cursor = conn.execute(
                    "SELECT id FROM tracks WHERE navidrome_id = ?",
                    (navidrome_id,)
                )
                result = cursor.fetchone()
                if result:
                    track_id = result[0]
                    feedback.record_favorite(track_id, True, "navidrome")
                    print(f"  Synced favorite for track {track_id}")

        # Note: Navidrome Subsonic API may not expose all ratings
        print("Note: Full rating sync may not be available via Navidrome API")
        print("Feedback synchronization complete")

    except Exception as e:
        print(f"Error syncing feedback: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def refresh_chart():
    """Refresh Top 100 chart"""
    from config import get_config
    from database import Database
    from recommendation import ChartUpdater, PlaylistWriter

    config = get_config()
    db = Database(config.paths.database_path)

    try:
        if not Path(config.paths.database_path).exists():
            print("Database not found. Run 'init-db' first.")
            return

        updater = ChartUpdater(db)
        writer = PlaylistWriter(db)

        # Refresh chart
        stats = updater.refresh_chart()
        print(f"Chart refresh complete:")
        print(f"  Retrieved: {stats['retrieved']}")
        print(f"  Added: {stats['added']}")
        print(f"  Failed: {stats['failed']}")

        # Generate chart playlist
        chart_tracks = updater.get_current_chart()
        if chart_tracks:
            writer.write_chart_playlist(chart_tracks)
            print(f"Generated chart playlist with {len(chart_tracks)} tracks")
        else:
            print("No chart tracks available for playlist generation")

    except Exception as e:
        print(f"Error refreshing chart: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def recommend():
    """Generate recommendations"""
    from config import get_config
    from database import Database
    from recommendation import RankingEngine, PlaylistWriter, CooldownEngine, FeedbackSystem

    config = get_config()
    db = Database(config.paths.database_path)

    try:
        if not Path(config.paths.database_path).exists():
            print("Database not found. Run 'init-db' first.")
            return

        ranking = RankingEngine(db)
        writer = PlaylistWriter(db)
        cooldown = CooldownEngine(db)
        feedback = FeedbackSystem(db)

        # Get candidate pool
        print("Gathering candidate pool...")
        candidate_ids = ranking.get_candidate_pool()
        print(f"Found {len(candidate_ids)} candidates")

        if not candidate_ids:
            print("No candidates available. Run sync-playlists first.")
            return

        # Rank candidates
        print("Ranking candidates...")
        scored = ranking.rank_candidates(
            candidate_ids,
            limit=config.recommendation.max_playlist_size
        )

        if not scored:
            print("No eligible candidates for recommendation")
            return

        print(f"Ranked {len(scored)} candidates")

        # Write playlist
        print("Generating playlist...")
        playlist_path = writer.write_recommendation_playlist(scored)

        # Record recommendations and add exclusions
        print("Recording recommendations...")
        for candidate in scored:
            cooldown.record_recommendation(candidate.track_id)
            # Add no-feedback exclusion
            cooldown.add_no_feedback_exclusion(candidate.track_id)

        # Regenerate memory file
        from recommendation.memory_writer import MemoryWriter
        memory_writer = MemoryWriter(db)
        memory_writer.generate_memory_file()

        print(f"Recommendation complete: {len(scored)} tracks")
        print(f"Playlist written to: {playlist_path}")
        print(f"Memory file updated")

    except Exception as e:
        print(f"Error generating recommendations: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def show_memory():
    """Show current memory state"""
    from config import get_config
    from database import Database
    from recommendation.memory_writer import MemoryWriter

    config = get_config()
    db = Database(config.paths.database_path)

    try:
        if not Path(config.paths.database_path).exists():
            print("Database not found. Run 'init-db' first.")
            return

        memory_writer = MemoryWriter(db)
        memory_writer.print_memory()

    except Exception as e:
        print(f"Error showing memory: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def rebuild_memory():
    """Rebuild memory file from database"""
    from config import get_config
    from database import Database
    from recommendation.memory_writer import MemoryWriter

    config = get_config()
    db = Database(config.paths.database_path)

    try:
        if not Path(config.paths.database_path).exists():
            print("Database not found. Run 'init-db' first.")
            return

        memory_writer = MemoryWriter(db)
        memory_path = memory_writer.generate_memory_file()
        print(f"Memory file regenerated: {memory_path}")

    except Exception as e:
        print(f"Error rebuilding memory: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def status():
    """Show system status"""
    from config import get_config
    from database import Database
    from recommendation.cooldown import CooldownEngine
    from datetime import datetime

    config = get_config()
    db = Database(config.paths.database_path)

    try:
        if not Path(config.paths.database_path).exists():
            print("Database not found. Run 'init-db' first.")
            return

        print("BlackBerry Music Intelligence - System Status")
        print("=" * 50)

        # Database info
        print(f"\nDatabase: {config.paths.database_path}")
        print(f"Schema version: {db.get_schema_version()}")

        # Exclusion summary
        cooldown = CooldownEngine(db)
        summary = cooldown.get_exclusion_summary()
        print(f"\nExclusions:")
        print(f"  Total active: {summary['total']}")
        print(f"  No-feedback: {summary['no_feedback']}")
        print(f"  Negative feedback: {summary['negative_feedback']}")
        print(f"  Manual: {summary['manual']}")
        print(f"  Expired: {summary['expired']}")

        # Track count
        with db.connect() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM tracks")
            track_count = cursor.fetchone()[0]
            print(f"\nTotal tracks in library: {track_count}")

        # Seed playlist sync status
        with db.connect() as conn:
            cursor = conn.execute("SELECT name, last_synced_at FROM seed_playlists")
            print(f"\nSeed playlist sync status:")
            for row in cursor.fetchall():
                name, last_synced = row
                if last_synced:
                    print(f"  {name}: {last_synced}")
                else:
                    print(f"  {name}: Never synced")

        # Chart status
        with db.connect() as conn:
            cursor = conn.execute(
                "SELECT last_refreshed_at, last_refresh_successful FROM chart_sources"
            )
            result = cursor.fetchone()
            if result:
                last_refresh, success = result
                if last_refresh:
                    status_str = "Success" if success else "Failed"
                    print(f"\nChart last refresh: {last_refresh} ({status_str})")
                else:
                    print(f"\nChart: Never refreshed")

        print(f"\nConfiguration timezone: {config.recommendation.timezone}")
        print(f"Current time: {datetime.now().isoformat()}")

    except Exception as e:
        print(f"Error getting status: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


def backup():
    """Create database backup"""
    config = get_config()
    db = Database(config.paths.database_path)

    if not Path(config.paths.database_path).exists():
        print("Database does not exist, nothing to backup")
        return

    backup_path = db.backup()
    print(f"Backup created at {backup_path}")


def test():
    """Run tests"""
    import subprocess
    print("Running tests...")
    result = subprocess.run(
        ["pytest", "tests/", "-v"],
        cwd=Path(__file__).parent
    )
    sys.exit(result.returncode)


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description="BlackBerry Music Intelligence - Music Recommendation System"
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Add commands
    subparsers.add_parser('check', help='Perform environment checks')
    subparsers.add_parser('init-db', help='Initialize database')
    subparsers.add_parser('sync-playlists', help='Synchronize seed playlists')
    subparsers.add_parser('sync-feedback', help='Synchronize feedback from Navidrome')
    subparsers.add_parser('refresh-chart', help='Refresh Top 100 chart')
    subparsers.add_parser('recommend', help='Generate recommendations')
    subparsers.add_parser('show-memory', help='Show current memory state')
    subparsers.add_parser('rebuild-memory', help='Rebuild memory file from database')
    subparsers.add_parser('status', help='Show system status')
    subparsers.add_parser('backup', help='Create database backup')
    subparsers.add_parser('test', help='Run tests')

    args = parser.parse_args()

    # Load configuration
    try:
        config = load_config()
    except Exception as e:
        print(f"Error loading configuration: {e}")
        sys.exit(1)

    # Setup logging
    setup_logging(config.logging.level)

    # Execute command
    if args.command == 'check':
        check_environment()
    elif args.command == 'init-db':
        init_database()
    elif args.command == 'sync-playlists':
        sync_playlists()
    elif args.command == 'sync-feedback':
        sync_feedback()
    elif args.command == 'refresh-chart':
        refresh_chart()
    elif args.command == 'recommend':
        recommend()
    elif args.command == 'show-memory':
        show_memory()
    elif args.command == 'rebuild-memory':
        rebuild_memory()
    elif args.command == 'status':
        status()
    elif args.command == 'backup':
        backup()
    elif args.command == 'test':
        test()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
