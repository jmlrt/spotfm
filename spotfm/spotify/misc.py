"""High-level Spotify commands and utilities.

DISCOVER WORKFLOW (discover_from_playlists):
===========================================

The discover feature finds new tracks in source playlists that don't exist in the
local database, then adds them to a destination playlist.

ALGORITHM:
1. Fetch all tracks from source playlists via Spotify API
2. Load tracks into database (creates Track objects, syncs to SQLite)
3. Query database for orphaned track IDs (tracks in DB but not in any playlist)
4. Skip orphaned tracks to prevent re-adding intentionally removed tracks
5. Add remaining new tracks to destination playlist
6. Sync destination playlist to database

WHY SKIP ORPHANED TRACKS?
- Orphaned tracks represent tracks the user intentionally removed
- They accumulate in the database as a "negative cache"
- Skipping them prevents re-discovering removed tracks on subsequent runs
- This is the core feature that makes the discovery truly "smart"

PLAYLIST RESOLUTION:
====================

resolve_playlist_patterns_to_ids() normalizes various playlist reference formats:
- Direct Spotify IDs (22 alphanumeric chars)
- Exact database lookups by ID
- Fuzzy name lookups (SQL LIKE pattern matching)
- Supports single string or list of patterns

This allows config to reference playlists by name, ID, or URL pattern.

RATE LIMITING:
==============

Sleep calls are strategically placed across the Spotify integration:
- In this module: 0.1s between individual track API calls (prevent 429 errors)
- In track.py: ~1s between track batches and 0.5s between album/artist batch fetches

Timing should not be removed without understanding Spotify API limits.
"""

import csv
import logging
import sys
from datetime import datetime
from pathlib import Path
from time import sleep

from spotfm import sqlite, utils
from spotfm.spotify.constants import MARKET
from spotfm.spotify.playlist import Playlist
from spotfm.spotify.track import Track


def resolve_playlist_patterns_to_ids(playlists_patterns, include_names=False):
    """Normalize and resolve playlist patterns to a list of playlist IDs.

    Supports:
    - A single string pattern or an iterable of patterns.
    - Direct playlist IDs (22 alphanumeric chars).
    - Exact ID lookup in the database.
    - Name pattern lookup via SQL LIKE.

    Args:
        playlists_patterns: String or list of strings representing playlist IDs or patterns
        include_names: If True, also return playlist names for logging

    Returns:
        If include_names=False: List of playlist IDs
        If include_names=True: Tuple of (list of playlist IDs, list of playlist names)
    """
    if not playlists_patterns:
        return ([], []) if include_names else []

    # Handle both single pattern (string) and multiple patterns (list)
    if isinstance(playlists_patterns, str):
        playlists_patterns = [playlists_patterns]

    ids = []
    names = [] if include_names else None
    seen_ids = set()  # Track seen IDs to avoid duplicates

    for pattern in playlists_patterns:
        # Check if it looks like a playlist ID (22 alphanumeric characters)
        if isinstance(pattern, str) and len(pattern) == 22 and pattern.isalnum():
            if pattern not in seen_ids:
                seen_ids.add(pattern)
                ids.append(pattern)
                if include_names:
                    # Fetch playlist name from DB for logging
                    results = sqlite.select_db(sqlite.DATABASE, "SELECT name FROM playlists WHERE id = ?;", (pattern,))
                    name_row = results.fetchone()
                    names.append(name_row[0] if name_row else pattern)
        else:
            # Try exact ID match first, then name pattern match
            query = (
                "SELECT id, name FROM playlists WHERE id = ?;"
                if include_names
                else "SELECT id FROM playlists WHERE id = ?;"
            )
            results = sqlite.select_db(sqlite.DATABASE, query, (pattern,))
            rows = results.fetchall()

            if not rows:
                query = (
                    "SELECT id, name FROM playlists WHERE name LIKE ?;"
                    if include_names
                    else "SELECT id FROM playlists WHERE name LIKE ?;"
                )
                results = sqlite.select_db(sqlite.DATABASE, query, (pattern,))
                rows = results.fetchall()

            for row in rows:
                playlist_id = row[0]
                if playlist_id not in seen_ids:
                    seen_ids.add(playlist_id)
                    ids.append(playlist_id)
                    if include_names:
                        names.append(row[1])

    return (ids, names) if include_names else ids


def add_tracks_from_file(client, file_path):
    tracks_ids = utils.manage_tracks_ids_file(file_path)

    for track_id in tracks_ids:
        logging.info(f"Initializing track {track_id}")
        track = Track.get_track(track_id, client.client)

        if track.name is not None and track.artists is not None and track.album is not None:
            track.sync_to_db(client)
            logging.info(f"Track {track.id} added to db")
        else:
            logging.info(f"Error: Track {track.id} not found")

        # Prevent rate limiting (429 errors)
        sleep(0.1)


def add_tracks_from_file_batch(client, file_path):
    """Add tracks from file using optimized batch processing."""
    tracks_ids = utils.manage_tracks_ids_file(file_path)

    # Track.get_tracks() handles all fetching and syncing
    tracks = Track.get_tracks(tracks_ids, client.client, refresh=False)

    # Sync tracks to DB
    for track in tracks:
        try:
            track.sync_to_db(client.client)
            logging.info(f"Track {track.id} added to db")
        except Exception as e:
            logging.info(f"Error adding track to db: {e}")


def remove_tracks_from_file(client, playlist_id, file_path):
    """Remove tracks from a Spotify playlist using track IDs from a file.

    Each line in the file should be a Spotify track ID or URL.
    Removes the tracks from the Spotify playlist and updates the local DB.

    WARNING: This does NOT remove tracks from the tracks table (they remain as
    orphaned tracks, preserving the negative cache for discover_from_playlists).

    Args:
        client: Spotify client wrapper instance
        playlist_id: ID of the playlist to remove tracks from
        file_path: Path to file containing track IDs (one per line)
    """
    # Normalize playlist_id once for consistent use with both Spotify API and DB
    normalized_playlist_id = utils.parse_url(playlist_id)

    # Parse and filter out empty/whitespace-only IDs to avoid invalid API/DB operations
    raw_track_ids = utils.manage_tracks_ids_file(file_path)
    track_ids = []
    for raw_id in raw_track_ids:
        parsed_id = utils.parse_url(raw_id)
        if not parsed_id or not parsed_id.strip():
            continue
        parsed_id = parsed_id.strip()
        # Validate that parsed ID is alphanumeric (valid Spotify track IDs are alphanumeric strings)
        # Reject IDs with special characters or spaces that indicate parsing errors
        if not parsed_id.isalnum():
            logging.warning(f"Skipping invalid track ID: {parsed_id}")
            continue
        track_ids.append(parsed_id)

    if not track_ids:
        logging.info(
            f"No valid track IDs found in file {file_path}; nothing to remove from playlist {normalized_playlist_id}"
        )
        return

    # Use Playlist(id) directly to avoid overhead of get_playlist (which loads full playlist metadata)
    playlist = Playlist(normalized_playlist_id)
    # Only delete from DB tracks that were successfully removed from Spotify
    successfully_removed = playlist.remove_tracks(track_ids, client.client)

    if not successfully_removed:
        logging.warning(f"No tracks were successfully removed from playlist {normalized_playlist_id}")
        return

    # Remove from local DB playlists_tracks (not tracks table — preserve negative cache)
    # Use batched DELETEs with IN clause for efficiency and to avoid excessively large SQL statements
    chunk_size = 900
    con = sqlite.get_db_connection(sqlite.DATABASE)
    cur = con.cursor()
    for i in range(0, len(successfully_removed), chunk_size):
        chunk = successfully_removed[i : i + chunk_size]
        # Use parameterized query: ? for playlist_id, ? for each track in the IN clause
        placeholders = ",".join("?" * len(chunk))
        cur.execute(
            f"DELETE FROM playlists_tracks WHERE playlist_id = ? AND track_id IN ({placeholders})",
            [normalized_playlist_id, *chunk],
        )
    con.commit()
    logging.info(f"Removed {len(successfully_removed)} tracks from playlist {normalized_playlist_id}")


def discover_from_playlists(client, discover_playlist_id, sources_playlists_ids):
    """Discover new tracks from source playlists and add them to a discover playlist.

    This function uses lifecycle tracking to distinguish between:
    - Tracks never seen before (added to discover playlist)
    - Tracks removed from all playlists (skipped to prevent re-adding)

    Lifecycle tracking:
    - Tracks have `created_at` and `last_seen_at` timestamps
    - Orphaned tracks (in DB but not in any playlist) are intentionally preserved
    - These orphaned tracks serve as a "negative cache" to prevent re-discovery

    WARNING: Do NOT delete orphaned tracks from the tracks table, as this will
    cause previously removed tracks to be re-added to the discover playlist.

    Only adds tracks that:
    - Don't exist in the database (never seen before)

    Skips tracks that:
    - Are orphaned (in DB but removed from all playlists)
    - Already exist in the database (whether in other playlists or not)

    Args:
        client: Spotify client instance
        discover_playlist_id: Playlist to add discovered tracks to
        sources_playlists_ids: List of playlist IDs to discover from

    See Also:
        - Track.is_orphaned(): Check if track is in zero playlists
        - Track lifecycle timestamps in hacks/create-tables.sql
    """
    discover_playlist = Playlist.get_playlist(discover_playlist_id, client.client, refresh=True, sync_to_db=False)
    new_tracks = []
    seen_new_ids = set()  # Track IDs already added in this run to avoid duplicates across source playlists
    total_playlists = len(sources_playlists_ids)

    for idx, playlist_id in enumerate(sources_playlists_ids, 1):
        playlist = Playlist.get_playlist(playlist_id, client.client, refresh=True, sync_to_db=False)
        print(f"fetching playlist {playlist.name} {idx}/{total_playlists}", file=sys.stderr, flush=True)
        logging.info(f"Looking for new tracks into {playlist.id} - {playlist.name}")

        # Pre-check which track IDs are already in DB for this discover run.
        # Playlist.get_playlist(..., refresh=True, sync_to_db=False) has already called
        # update_from_api(), so playlist.raw_tracks is a stable snapshot from the API; some of
        # these IDs may already exist in the DB from update_playlists or prior discovers.
        raw_track_ids = [utils.parse_url(raw_track[0]) for raw_track in playlist.raw_tracks]
        if raw_track_ids:
            # Batch IDs to avoid exceeding SQLite's bound-parameter limit (commonly 999).
            in_db_before = set()
            chunk_size = 900
            for i in range(0, len(raw_track_ids), chunk_size):
                chunk = raw_track_ids[i : i + chunk_size]
                placeholders = ",".join(["?"] * len(chunk))
                rows = sqlite.select_db(
                    sqlite.DATABASE,
                    f"SELECT id FROM tracks WHERE id IN ({placeholders})",
                    chunk,
                ).fetchall()
                in_db_before.update(row[0] for row in rows)
        else:
            in_db_before = set()

        # playlist.tracks is already populated by update_from_api() (with sync_to_db=False).
        # Using it directly avoids a redundant second get_tracks() call.
        tracks = playlist.tracks
        new_this_playlist = 0

        for track in tracks:
            if track.id not in in_db_before and track.id not in seen_new_ids:
                # Track wasn't in DB before this run AND not already added in a previous source playlist
                logging.debug(f"New track found: {track.id}")
                new_tracks.append(track)
                seen_new_ids.add(track.id)
                new_this_playlist += 1
            elif track.is_orphaned():
                # Track exists in DB but not in any playlist (was intentionally removed)
                last_seen = getattr(track, "last_seen_at", "unknown")
                logging.info(f"Skipping orphaned track: {track.id} (last seen: {last_seen})")
                # Do NOT add to new_tracks
            else:
                # Track exists and is in other playlists
                logging.debug(f"Skipping track {track.id} (already in playlists)")

        print(f"discovered {new_this_playlist} new tracks from playlist {playlist.name}", file=sys.stderr)

    print(f"total discovered from all playlists: {len(new_tracks)} new tracks", file=sys.stderr)
    logging.info(f"Adding new tracks to {discover_playlist.id} - {discover_playlist.name}")
    if len(new_tracks) > 0:
        discover_playlist.add_tracks(new_tracks, client.client)
        # Only sync to DB after successful playlist add to prevent orphaning tracks
        # if the Spotify API call fails
        logging.info(f"Adding {len(new_tracks)} new tracks to db")
        for track in new_tracks:
            track.sync_to_db(client.client)


def count_tracks_by_playlists():
    return sqlite.select_db(
        sqlite.DATABASE,
        "SELECT name, count(*) FROM playlists, playlists_tracks WHERE id = playlists_tracks.playlist_id GROUP BY name;",
    ).fetchall()


def count_tracks(playlists_patterns=None):
    if playlists_patterns:
        # Resolve patterns to playlist IDs (supports both exact IDs and LIKE patterns)
        ids = resolve_playlist_patterns_to_ids(playlists_patterns)

        if not ids:
            return 0
        query = f"""
          WITH t AS (SELECT DISTINCT track_id FROM playlists_tracks WHERE playlist_id IN ({",".join(["?"] * len(ids))}))
          SELECT count(*) AS tracks FROM t;
        """
        return sqlite.select_db(sqlite.DATABASE, query, ids).fetchone()[0]
    return sqlite.select_db(
        sqlite.DATABASE,
        "WITH t AS (SELECT DISTINCT track_id FROM playlists_tracks) SELECT count(*) AS tracks FROM t;",
    ).fetchone()[0]


def find_relinked_tracks(client, excluded_playlist_ids=None, output_file=None):
    """Find tracks that are relinked by Spotify's market-based replacement.

    Spotify performs automatic track replacement (relinking) based on regional
    availability. This function identifies which tracks in your playlists are
    being replaced when fetched with the configured market parameter.

    Only reports relinked tracks where the replacement has different metadata
    (artist name or track name) from the original. Tracks that are relinked
    to different IDs but have identical metadata are filtered out.

    Args:
        client: Spotify client instance
        excluded_playlist_ids: List of playlist IDs to exclude from the search
        output_file: Optional path to CSV output file

    Returns:
        List of dicts containing relinked track information where metadata differs
    """
    if excluded_playlist_ids is None:
        excluded_playlist_ids = []

    # Get all playlists from database
    query = "SELECT id, name FROM playlists"
    params = []

    if excluded_playlist_ids:
        placeholders = ",".join(["?"] * len(excluded_playlist_ids))
        query += f" WHERE id NOT IN ({placeholders})"
        params = excluded_playlist_ids

    playlists = sqlite.query_db_select(sqlite.DATABASE, query, tuple(params))

    relinked_tracks = []
    total_playlists = len(playlists)

    logging.info(f"Checking {total_playlists} playlists for relinked tracks (market: {MARKET})")

    for idx, (playlist_id, playlist_name) in enumerate(playlists, 1):
        logging.info(f"[{idx}/{total_playlists}] Checking playlist: {playlist_name}")

        # Fetch playlist items with linked_from information
        results = client.playlist_items(
            playlist_id,
            fields="items(added_at,track(id,name,artists,linked_from)),next",
            market=MARKET,
            additional_types=["track"],
        )

        tracks = results["items"]
        while results["next"]:
            results = client.next(results)
            tracks.extend(results["items"])

        # Find tracks with linked_from (relinked tracks)
        for track_data in tracks:
            if track_data["track"] is None:
                continue

            track = track_data["track"]
            if track.get("linked_from"):
                # This track is relinked
                original_id = track["linked_from"]["id"]
                replacement_id = track["id"]
                track_name = track["name"]
                artists = ", ".join([a["name"] for a in track["artists"]])

                # Fetch original track details
                try:
                    sleep(0.1)  # Prevent rate limiting
                    original_track = client.track(original_id, market=MARKET)
                    original_name = original_track["name"]
                    original_artists = ", ".join([a["name"] for a in original_track["artists"]])
                except Exception as e:
                    logging.warning(f"Could not fetch original track {original_id}: {e}")
                    original_name = "Unknown"
                    original_artists = "Unknown"

                # Only report if the metadata actually changed (different artists or track name)
                if original_artists != artists or original_name != track_name:
                    relinked_tracks.append(
                        {
                            "playlist_id": playlist_id,
                            "playlist_name": playlist_name,
                            "original_id": original_id,
                            "original_track": f"{original_artists} - {original_name}",
                            "replacement_id": replacement_id,
                            "replacement_track": f"{artists} - {track_name}",
                            "added_at": track_data["added_at"],
                        }
                    )

                    logging.info(
                        f"  Found relinked track: {original_artists} - {original_name} -> {artists} - {track_name}"
                    )

    logging.info(f"Found {len(relinked_tracks)} relinked tracks across {total_playlists} playlists")

    # Output results
    if output_file:
        write_relinked_tracks_csv(relinked_tracks, output_file)
    else:
        for track in relinked_tracks:
            print(
                f"Relinked - {track['playlist_name']} - {track['original_track']} -> {track['replacement_track']} - {track['original_id']} - {track['replacement_id']}"
            )

    return relinked_tracks


def list_playlists_with_track_counts():
    """Lists all playlists with their track counts, sorted by playlist name."""
    query = """
        SELECT
            p.name,
            p.id,
            COUNT(pt.track_id) AS track_count
        FROM
            playlists AS p
        LEFT JOIN
            playlists_tracks AS pt ON p.id = pt.playlist_id
        GROUP BY
            p.id, p.name
        ORDER BY
            p.name COLLATE NOCASE;
    """
    return sqlite.select_db(sqlite.DATABASE, query).fetchall()


def find_tracks_by_criteria(playlist_patterns, start_date=None, end_date=None, genre_pattern=None, output_file=None):
    """
    Finds tracks from specified playlists that match date or genre criteria.

    Args:
        playlist_patterns: Playlist ID(s) or name pattern(s) to search within.
                          Can be a single string or list of strings.
                          Supports exact playlist IDs (22 alphanumeric chars) or
                          SQL LIKE patterns (e.g., 'Discover%' matches 'Discover Dest').
        start_date: Start date for album release date filtering (YYYY-MM-DD).
        end_date: End date for album release date filtering (YYYY-MM-DD).
        genre_pattern: Regex pattern for genre filtering.
        output_file: Path to output CSV file if specified.

    Returns:
        List of dictionaries containing track information.
    """
    # Resolve patterns to playlist IDs (supports both exact IDs and LIKE patterns)
    playlist_ids, playlist_names = resolve_playlist_patterns_to_ids(playlist_patterns, include_names=True)

    if not playlist_ids:
        logging.info(f"No playlists found matching patterns: {playlist_patterns}")
        return []

    logging.info(f"Searching in playlists: {', '.join(playlist_names)}")

    # Base query for track information
    base_query = """
        SELECT
            t.id AS track_id,
            t.name AS track_name,
            SUBSTR(al.release_date, 1, 4) AS release_year,
            al.name AS album_name,
            GROUP_CONCAT(DISTINCT ar.name) AS artist_names,
            GROUP_CONCAT(DISTINCT ag.genre) AS artist_genres
        FROM
            tracks AS t
        INNER JOIN
            playlists_tracks AS pt ON t.id = pt.track_id
        LEFT JOIN
            albums_tracks AS atr ON t.id = atr.track_id
        LEFT JOIN
            albums AS al ON atr.album_id = al.id
        LEFT JOIN
            tracks_artists AS tar ON t.id = tar.track_id
        LEFT JOIN
            artists AS ar ON tar.artist_id = ar.id
        LEFT JOIN
            artists_genres AS ag ON ar.id = ag.artist_id
    """

    # Build WHERE clauses
    where_clauses = []
    params = []

    # Filter by playlist IDs
    playlist_placeholders = ",".join(["?"] * len(playlist_ids))
    where_clauses.append(f"pt.playlist_id IN ({playlist_placeholders})")
    params.extend(playlist_ids)

    # Filter by date range
    if start_date and end_date:
        where_clauses.append("al.release_date BETWEEN ? AND ?")
        params.extend([start_date, end_date])
    elif start_date:
        where_clauses.append("al.release_date >= ?")
        params.append(start_date)
    elif end_date:
        where_clauses.append("al.release_date <= ?")
        params.append(end_date)

    # Filter by genre pattern
    if genre_pattern:
        # Need a subquery to filter by genre after aggregation
        # REGEXP uses case-insensitive matching (re.IGNORECASE in _regexp UDF)
        genre_subquery = """
            SELECT DISTINCT t2.id
            FROM tracks AS t2
            LEFT JOIN tracks_artists AS tar2 ON t2.id = tar2.track_id
            LEFT JOIN artists AS ar2 ON tar2.artist_id = ar2.id
            LEFT JOIN artists_genres AS ag2 ON ar2.id = ag2.artist_id
            WHERE ag2.genre REGEXP ?
        """
        where_clauses.append(f"t.id IN ({genre_subquery})")
        params.append(genre_pattern)

    group_by_clause = """
        GROUP BY
            t.id, t.name, al.name, al.release_date
    """

    order_by_clause = """
        ORDER BY
            artist_names COLLATE NOCASE, track_name COLLATE NOCASE
    """

    full_query = base_query

    if where_clauses:
        full_query += " WHERE " + " AND ".join(where_clauses)

    full_query += group_by_clause + order_by_clause

    logging.debug(f"Executing query: {full_query} with params: {params}")

    raw_results = sqlite.select_db(sqlite.DATABASE, full_query, tuple(params)).fetchall()

    # Process results into a list of dicts for easier handling
    results = []
    for row in raw_results:
        track_id, track_name, release_year, album_name, artist_names, artist_genres = row
        results.append(
            {
                "track_id": track_id,
                "track_name": track_name,
                "release_year": release_year,
                "album_name": album_name,
                "artist_names": artist_names,
                "artist_genres": artist_genres,
            }
        )

    if output_file:
        write_tracks_to_csv(results, output_file)

    return results


def write_tracks_to_csv(tracks_data, output_file):
    """Write track data to CSV file.

    Args:
        tracks_data: List of dictionaries containing track information.
        output_file: Path to output CSV file.
    """
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="") as csvfile:
        fieldnames = [
            "Artist(s)",
            "Track Name",
            "Album Name",
            "Release Year",
            "Genre(s)",
            "Track ID",
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()

        for track in tracks_data:
            writer.writerow(
                {
                    "Artist(s)": track["artist_names"],
                    "Track Name": track["track_name"],
                    "Album Name": track["album_name"],
                    "Release Year": track["release_year"],
                    "Genre(s)": track["artist_genres"],
                    "Track ID": track["track_id"],
                }
            )

    logging.info(f"Wrote {len(tracks_data)} tracks to {output_path}")


def write_relinked_tracks_csv(relinked_tracks, output_file):
    """Write relinked tracks to CSV file.
    Args:
        relinked_tracks: List of relinked track dicts
        output_file: Path to output CSV file
    """
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="") as csvfile:
        fieldnames = [
            "Playlist",
            "Original Track",
            "Original ID",
            "Replacement Track",
            "Replacement ID",
            "Added At",
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()

        for track in relinked_tracks:
            writer.writerow(
                {
                    "Playlist": track["playlist_name"],
                    "Original Track": track["original_track"],
                    "Original ID": track["original_id"],
                    "Replacement Track": track["replacement_track"],
                    "Replacement ID": track["replacement_id"],
                    "Added At": track["added_at"],
                }
            )

    logging.info(f"Wrote {len(relinked_tracks)} relinked tracks to {output_path}")


def log_track_counts(config=None):
    """Log track counts to CSV, with optional pattern-specific tracking.

    Appends a row with timestamp, total track count, and optional pattern-specific count.
    Uses a stable schema (always 3 columns) to avoid issues when pattern configuration changes.

    Creates the log file with headers if it doesn't exist. CSV always has 3 columns:
    - timestamp: YYYY-MM-DD HH:MM format
    - total_tracks: Total unique tracks across all playlists
    - pattern_tracks: Count for configured pattern (empty string if no pattern configured)

    Args:
        config: Configuration dict (optional). If not provided, uses defaults:
                - Log path: ~/.spotfm/track-counts.csv
                - Pattern: None (no secondary pattern tracking)

                Can customize via config["spotify"]:
                - track_counts_log: Path to CSV file
                - new_tracks_pattern: SQL LIKE pattern for pattern-specific tracking (e.g., "IR%", "New%").
                  Omit this key to disable pattern tracking. If specified, must be a string.
    """
    # Determine log file path
    if config and "spotify" in config and "track_counts_log" in config["spotify"]:
        log_path_str = config["spotify"]["track_counts_log"]
        # Validate config path is not empty and is a string
        if not log_path_str or not isinstance(log_path_str, str):
            raise ValueError(f"Invalid track_counts_log in config: {log_path_str}")
        log_path = Path(log_path_str).expanduser()
        # Reject directory paths
        if log_path.exists() and log_path.is_dir():
            raise ValueError(f"track_counts_log must be a file path, not a directory: {log_path}")
    else:
        log_path = utils.WORK_DIR / "track-counts.csv"

    # Determine pattern for secondary tracking (optional, defaults to None)
    new_tracks_pattern = None
    if config and "spotify" in config and "new_tracks_pattern" in config["spotify"]:
        new_tracks_pattern = config["spotify"]["new_tracks_pattern"]
        # Validate pattern is a string (if specified)
        if new_tracks_pattern is not None and not isinstance(new_tracks_pattern, str):
            raise ValueError(f"new_tracks_pattern must be a string, got {type(new_tracks_pattern).__name__}")

    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Get counts
    total_tracks = count_tracks()
    # Always count the pattern if configured, otherwise None
    pattern_tracks = count_tracks(new_tracks_pattern) if new_tracks_pattern else None

    # Prepare row with timestamp format: YYYY-MM-DD HH:MM
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    # Always include all columns for schema stability (avoids mismatch issues when pattern is enabled/disabled)
    row = {
        "timestamp": timestamp,
        "total_tracks": total_tracks,
        "pattern_tracks": pattern_tracks if pattern_tracks is not None else "",
    }

    # Always use stable 3-column schema regardless of whether pattern is configured
    fieldnames = ["timestamp", "total_tracks", "pattern_tracks"]

    # Check if file needs headers: doesn't exist OR is empty
    needs_header = not log_path.exists() or log_path.stat().st_size == 0

    with open(log_path, "a", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=";")

        if needs_header:
            writer.writeheader()

        writer.writerow(row)

    # Log with appropriate message based on configuration
    if new_tracks_pattern:
        logging.info(f"Logged track counts: total={total_tracks}, {new_tracks_pattern}={pattern_tracks} to {log_path}")
    else:
        logging.info(f"Logged track counts: total={total_tracks} to {log_path}")
