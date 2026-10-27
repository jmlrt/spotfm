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
from datetime import datetime
from pathlib import Path
from time import sleep

from spotfm import sqlite, utils
from spotfm.spotify.constants import MARKET
from spotfm.spotify.playlist import Playlist
from spotfm.spotify.track import Track

# Liked Songs (saved tracks) sync tuning.
# Spotify exposes no snapshot for the saved-tracks library, so change detection
# relies on response ordering (newest first) and total-count reconciliation.
LIKED_PAGE_SIZE = 50  # Max page size for GET /me/tracks
LIKED_CONTAINS_CHUNK = 50  # Max ids per GET /me/tracks/contains call (API limit)
LIKED_FETCH_DELAY = 0.1  # Seconds between API calls (prevents 429 errors)
LIKED_DB_CHUNK = 900  # SQLite bound-parameter batch size (limit is 999)


def _chunked(seq, size):
    """Yield successive chunks of seq, each with at most size elements."""
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _extract_saved_track_id(item):
    """Extract the original track ID from a saved-tracks item.

    Spotify relinks tracks based on market availability; linked_from points back
    to the original track. Storing the original ID (same as playlist sync does)
    keeps a recording's ID consistent across playlists and Liked Songs.

    Returns None for unavailable tracks (track is null) or non-track items.
    """
    track = item.get("track")
    if not track or not track.get("id"):
        return None
    linked_from = track.get("linked_from")
    if linked_from and linked_from.get("id"):
        return linked_from["id"]
    return track["id"]


def _scan_page_ordering(items, ordered, prev_added_at):
    """Validate that added_at is non-increasing across a fetched page.

    The whole page is scanned before any threshold cutoff is applied: a
    violation after the cutoff item must still be observed, or an addition
    hiding behind an out-of-order item would be missed without triggering the
    full-walk fallback. Violations in pages that are never fetched remain
    unobservable; any observed violation makes the cutoff unsafe.

    Returns (ordered, last_added_at) for the caller to carry across pages.
    """
    for item in items:
        added_at = item.get("added_at")
        if added_at:
            if ordered and prev_added_at and added_at > prev_added_at:
                logging.warning("Saved tracks not ordered by added_at; change detection may miss additions")
                ordered = False
            prev_added_at = added_at
    return ordered, prev_added_at


def _collect_saved_tracks(client, first_page=None, threshold=None):
    """Page through /me/tracks collecting raw saved-tracks items by track ID.

    Items are returned most-recent-first by added_at. When threshold (the newest
    liked_at stored in the database) is given, paging stops at the first item
    older than or equal to it: everything deeper is older and already known.
    When threshold is None, all pages are walked (first sync or fallback).
    Each fetched page is fully validated for added_at ordering before the
    cutoff is applied; once a violation is observed, the cutoff is disabled and
    the walk continues to the end (the result is already a full walk).

    Returns a tuple (saved, ordered):
    - saved: dict of track_id -> raw saved-tracks item (unavailable/non-track
      items skipped)
    - ordered: False when added_at ordering was observed to be violated, which
      makes the threshold-based early stop unsafe (the additions dict is then
      already the result of a full walk).
    """
    saved = {}
    ordered = True
    prev_added_at = None
    if first_page is None:
        first_page = client.current_user_saved_tracks(limit=LIKED_PAGE_SIZE, market=MARKET)
    results = first_page
    while True:
        items = results.get("items") or []
        ordered, prev_added_at = _scan_page_ordering(items, ordered, prev_added_at)
        for item in items:
            added_at = item.get("added_at")
            if ordered and threshold is not None and added_at and added_at <= threshold:
                return saved, ordered
            track_id = _extract_saved_track_id(item)
            if track_id is None:
                logging.debug("Skipping unavailable or non-track saved item")
                continue
            if track_id not in saved:
                saved[track_id] = item
        if not results.get("next"):
            return saved, ordered
        sleep(LIKED_FETCH_DELAY)
        results = client.next(results)


def _tracks_in_db(track_ids):
    """Return the subset of track_ids that already have a row in the tracks table."""
    in_db = set()
    for chunk in _chunked(track_ids, LIKED_DB_CHUNK):
        placeholders = ",".join(["?"] * len(chunk))
        rows = sqlite.select_db(
            sqlite.DATABASE, f"SELECT id FROM tracks WHERE id IN ({placeholders})", chunk
        ).fetchall()
        in_db.update(row[0] for row in rows)
    return in_db


def _apply_liked_additions(client, additions):
    """Mark tracks as liked and sync metadata for those not yet in the database.

    Metadata is only fetched for tracks missing a tracks row: the vast majority
    of liked tracks are already synced via playlists and need no API calls.

    Two fetch quirks are handled for missing tracks:
    - Track.get_tracks() returns pickle-cache hits without writing them to the
      database, even with sync_to_db=True; any fetched track that still has no
      row is persisted explicitly.
    - A relinked track (linked_from) fetched under its original ID is persisted
      by get_tracks under the market replacement ID (the API response id),
      leaving the original ID without a row and the liked UPDATE a silent
      no-op. Relinked additions are hydrated directly from the raw saved item
      under the original ID instead, consistent with playlist sync.

    Args:
        client: Spotify client instance
        additions: dict of track_id -> raw saved-tracks item

    Returns:
        Number of tracks marked liked (tracks whose metadata could not be
        fetched are skipped; a later sync retries them).
    """
    track_ids = list(additions)

    missing = [tid for tid in track_ids if tid not in _tracks_in_db(track_ids)]
    if missing:
        relinked = {}
        plain = []
        for tid in missing:
            track_data = additions[tid].get("track") or {}
            if track_data.get("linked_from", {}).get("id"):
                relinked[tid] = additions[tid]
            else:
                plain.append(tid)

        if relinked:
            logging.info("Hydrating %d relinked liked tracks under their original IDs", len(relinked))
            for tid, item in relinked.items():
                try:
                    track = Track(tid, client)
                    track.update_from_track(item["track"], client)
                    track.sync_to_db(client)
                except (KeyError, TypeError) as e:
                    logging.warning("Skipping relinked liked track %s: %s", tid, e)

        if plain:
            logging.info("Fetching metadata for %d liked tracks not yet in database", len(plain))
            fetched = Track.get_tracks(plain, client, sync_to_db=True)
            still_missing = {tid for tid in plain if tid not in _tracks_in_db(plain)}
            for track in fetched:
                if track is not None and track.id in still_missing:
                    # Pickle-cache hit returned without a database write
                    track.sync_to_db(client)

    sqlite.execute_many(
        sqlite.DATABASE,
        "UPDATE tracks SET liked = 1, liked_at = ? WHERE id = ?",
        [(additions[track_id].get("added_at"), track_id) for track_id in track_ids],
    )
    logging.info("Marked %d tracks as liked in database", len(track_ids))
    return len(track_ids)


def _detect_and_remove_unliked(client):
    """Verify stored liked tracks are still liked; unset the flag for unlikes.

    Uses GET /me/tracks/contains (50 ids per call, the API limit) over all
    stored liked IDs. Unliked tracks keep their tracks row (negative cache)
    and their liked_at value (historical); only the liked flag is cleared.
    """
    liked_ids = [
        row[0] for row in sqlite.select_db(sqlite.DATABASE, "SELECT id FROM tracks WHERE liked = 1").fetchall()
    ]
    removed = []
    for idx, chunk in enumerate(_chunked(liked_ids, LIKED_CONTAINS_CHUNK)):
        if idx:
            sleep(LIKED_FETCH_DELAY)
        flags = client.current_user_saved_tracks_contains(chunk)
        removed.extend(track_id for track_id, liked in zip(chunk, flags, strict=False) if not liked)

    if removed:
        sqlite.execute_many(
            sqlite.DATABASE, "UPDATE tracks SET liked = 0 WHERE id = ?", [(track_id,) for track_id in removed]
        )
        logging.info("Cleared liked flag for %d tracks unliked on Spotify", len(removed))
    else:
        logging.info("All %d stored liked tracks are still liked", len(liked_ids))
    return len(removed)


def _load_liked_sync_state():
    """Return (spotify_total, newest_added_at) observed at the last sync, or (None, None).

    The state is kept in liked_sync_state. Unavailable items (track null) count
    in the API total and can be the newest item, but they never get a tracks
    row; comparing against the state observed at the last sync keeps the fast
    path working for such libraries, where the stored liked count alone can
    stay permanently below the API total.
    """
    row = sqlite.select_db(
        sqlite.DATABASE, "SELECT spotify_total, newest_added_at FROM liked_sync_state WHERE id = 1"
    ).fetchone()
    return (row[0], row[1]) if row else (None, None)


def _store_liked_sync_state(total, newest_added_at):
    """Persist the observed saved-tracks state for the next sync's fast path."""
    sqlite.execute_many(
        sqlite.DATABASE,
        "INSERT OR REPLACE INTO liked_sync_state (id, spotify_total, newest_added_at) VALUES (1, ?, ?)",
        [(total, newest_added_at)],
    )


def update_liked_tracks(client):
    """Sync Liked Songs (saved tracks) from the Spotify API to the local database.

    API call budget for ~11,000 liked tracks:
    - No changes since last sync: 1 request (first page: total + top added_at)
    - Changes: 1-2 pages to collect additions + ~220 contains checks for
      removals (50 ids per request, the API limit)
    - First sync: ~220 pages; per-track metadata fetches only for tracks not
      already in the database (usually a small fraction)

    Change detection (the saved-tracks library has no snapshot equivalent):
    1. /me/tracks returns items most-recent-first. New likes are collected by
       paging until an item's added_at is older than the newest liked_at stored
       in the database. Each fetched page's ordering is validated before the
       threshold cutoff is applied; an observed violation disables the cutoff
       and the walk completes as a full walk.
    2. Removals have no signal: whenever the fast path fails, all stored liked
       IDs are verified with GET /me/tracks/contains. Unlikes clear the liked
       flag; the tracks row is kept as negative cache.

    The fast path skips the sync when the first page matches the state
    observed at the last sync (stored in liked_sync_state: same total and same
    top added_at), or when the total matches the stored liked count and no item
    is newer than the newest stored liked_at. Either signal is only trusted
    when the first page's added_at ordering is valid. The stored state matters
    for libraries containing unavailable items: they count in the API total and
    can be the newest item, but never get a tracks row, so the liked count
    alone can stay permanently below the API total.

    Tracks relinked by market-based replacement are stored under their original
    ID (linked_from), consistent with playlist sync.

    Args:
        client: Spotify client (spotipy) instance

    Returns:
        Dict with keys: added (int), removed (int), total (int), unchanged (bool)
    """
    db_count, db_max_liked_at = sqlite.select_db(
        sqlite.DATABASE, "SELECT COUNT(*), MAX(liked_at) FROM tracks WHERE liked = 1"
    ).fetchone()
    state_total, state_newest = _load_liked_sync_state()

    results = client.current_user_saved_tracks(limit=LIKED_PAGE_SIZE, market=MARKET)
    total = results.get("total") or 0
    items = results.get("items") or []
    newest_added_at = items[0].get("added_at") if items else None

    # The first page is already fetched: validate its ordering before trusting
    # either fast-path signal — a disordered page can hide additions anywhere
    page_ordered, _ = _scan_page_ordering(items, True, None)

    count_match = (
        db_count
        and total == db_count
        and (newest_added_at is None or db_max_liked_at is None or newest_added_at <= db_max_liked_at)
    )
    state_match = state_total is not None and total == state_total and newest_added_at == state_newest
    if page_ordered and (count_match or state_match):
        logging.info("Liked Songs unchanged (%d tracks, total matches), skipping sync", db_count)
        logging.info("Command: update_liked_tracks | No changes detected (%d liked tracks)", db_count)
        return {"added": 0, "removed": 0, "total": total, "unchanged": True}

    threshold = db_max_liked_at if db_count else None
    # An observed ordering violation disables the threshold cutoff inside the
    # walk, so its result is already a complete full walk — no re-walk needed
    additions, _ = _collect_saved_tracks(client, first_page=results, threshold=threshold)

    added = _apply_liked_additions(client, additions) if additions else 0

    # Fast path failed: something changed (or first sync) — verify all stored
    # liked IDs against the library to detect unlikes
    removed = _detect_and_remove_unliked(client)

    _store_liked_sync_state(total, newest_added_at)

    logging.info(
        "Command: update_liked_tracks | %d added, %d removed, %d liked tracks in database (Spotify total: %d)",
        added,
        removed,
        sqlite.select_db(sqlite.DATABASE, "SELECT COUNT(*) FROM tracks WHERE liked = 1").fetchone()[0],
        total,
    )
    return {"added": added, "removed": removed, "total": total, "unchanged": False}


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
    """Add tracks from file to local database (for later playlist operations).

    Note: This command adds tracks to the LOCAL database only, not to any Spotify playlist.
    Use after with add-tracks-from-file to add to a specific playlist, or rely on
    discover-from-playlists to surface them.

    Args:
        client: Spotify client wrapper instance
        file_path: Path to file containing track IDs (one per line)
    """
    tracks_ids = utils.manage_tracks_ids_file(file_path)

    successfully_added = 0
    for track_id in tracks_ids:
        logging.debug(f"Initializing track {track_id}")
        track = Track.get_track(track_id, client.client)

        if track.name is not None and track.artists is not None and track.album is not None:
            track.sync_to_db(client)
            logging.debug(f"Track {track.id} added to db")
            successfully_added += 1
        else:
            logging.warning(f"Track {track_id} not found on Spotify")

        # Prevent rate limiting (429 errors)
        sleep(0.1)


def add_tracks_from_file_batch(client, file_path):
    """Add tracks from file using optimized batch processing.

    Note: This command adds tracks to the LOCAL database only, not to any Spotify playlist.
    Use after with add-tracks-from-file to add to a specific playlist, or rely on
    discover-from-playlists to surface them.

    Args:
        client: Spotify client wrapper instance
        file_path: Path to file containing track IDs (one per line)
    """
    tracks_ids = utils.manage_tracks_ids_file(file_path)

    # Track.get_tracks() handles all fetching and syncing
    tracks = Track.get_tracks(tracks_ids, client.client, refresh=False)

    # Sync tracks to DB
    for track in tracks:
        try:
            track.sync_to_db(client.client)
            logging.debug(f"Track {track.id} added to db")
        except Exception as e:
            logging.warning(f"Error adding track to db: {e}")


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
        logging.info(f"Fetching playlist {playlist_id} ({idx}/{total_playlists})")
        playlist = Playlist.get_playlist(playlist_id, client.client, refresh=True, sync_to_db=False)
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

        logging.info(f"Discovered {new_this_playlist} new tracks from playlist {playlist.name}")

    if len(new_tracks) > 0:
        logging.info(
            "Command: discover_from_playlists | Found %d new tracks from %d source playlists | Adding to discover playlist %s - %s",
            len(new_tracks),
            total_playlists,
            discover_playlist.id,
            discover_playlist.name,
        )
        discover_playlist.add_tracks(new_tracks, client.client)
        # Only sync to DB after successful playlist add to prevent orphaning tracks
        # if the Spotify API call fails
        logging.info(f"Adding {len(new_tracks)} new tracks to db")
        for track in new_tracks:
            track.sync_to_db(client.client)
    else:
        logging.info(
            "Command: discover_from_playlists | No new tracks discovered from %d source playlists", total_playlists
        )


def count_tracks_by_playlists():
    return sqlite.select_db(
        sqlite.DATABASE,
        "SELECT name, count(*) FROM playlists, playlists_tracks WHERE id = playlists_tracks.playlist_id GROUP BY name;",
    ).fetchall()


def count_liked_tracks():
    """Count tracks currently marked liked in the database."""
    return sqlite.select_db(sqlite.DATABASE, "SELECT count(*) FROM tracks WHERE liked = 1;").fetchone()[0]


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
    # Total = distinct tracks in at least one playlist OR liked.
    # Tracks neither in a playlist nor liked (negative-cache orphans) are not counted.
    return sqlite.select_db(
        sqlite.DATABASE,
        """
        WITH t AS (
            SELECT DISTINCT track_id FROM playlists_tracks
            UNION
            SELECT id FROM tracks WHERE liked = 1
        )
        SELECT count(*) AS tracks FROM t;
        """,
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


NO_PLAYLIST_PATTERN = "none"
"""Sentinel playlist_patterns value selecting tracks that are in zero playlists."""


def find_tracks_by_criteria(
    playlist_patterns, start_date=None, end_date=None, genre_pattern=None, output_file=None, liked=None
):
    """
    Finds tracks matching playlist, date, genre or liked criteria.

    Args:
        playlist_patterns: Playlist ID(s) or name pattern(s) to search within.
                          Can be a single string or list of strings.
                          Supports exact playlist IDs (22 alphanumeric chars) or
                          SQL LIKE patterns (e.g., 'Discover%' matches 'Discover Dest').
                          None: no playlist filter — tracks in at least one playlist
                          OR liked (negative-cache orphans excluded).
                          NO_PLAYLIST_PATTERN ('none'): only tracks in zero playlists.
        start_date: Start date for album release date filtering (YYYY-MM-DD).
        end_date: End date for album release date filtering (YYYY-MM-DD).
        genre_pattern: Regex pattern for genre filtering.
        output_file: Path to output CSV file if specified.
        liked: None for no filter, True for liked tracks only, False for not-liked only.

    Returns:
        List of dictionaries containing track information.
    """
    # No-playlist sentinel: tracks in zero playlists
    if playlist_patterns == NO_PLAYLIST_PATTERN:
        playlist_ids = None
        playlist_names = [NO_PLAYLIST_PATTERN]
        no_playlist_mode = True
    elif playlist_patterns is None:
        # No playlist filter: all tracks in the database
        playlist_ids = None
        playlist_names = None
        no_playlist_mode = False
    else:
        # Resolve patterns to playlist IDs (supports both exact IDs and LIKE patterns)
        playlist_ids, playlist_names = resolve_playlist_patterns_to_ids(playlist_patterns, include_names=True)
        no_playlist_mode = False

        if not playlist_ids:
            logging.info(f"No playlists found matching patterns: {playlist_patterns}")
            return []

    if playlist_names is not None:
        logging.info(f"Searching in playlists: {', '.join(playlist_names)}")

    # Base query for track information.
    # LEFT JOINs keep tracks that are in no playlist (or no album/artist rows).
    base_query = """
        SELECT
            t.id AS track_id,
            t.name AS track_name,
            SUBSTR(al.release_date, 1, 4) AS release_year,
            al.name AS album_name,
            t.liked AS liked,
            GROUP_CONCAT(DISTINCT ar.name) AS artist_names,
            GROUP_CONCAT(DISTINCT ag.genre) AS artist_genres
        FROM
            tracks AS t
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

    # Build FROM additions and WHERE clauses
    from_additions = []
    where_clauses = []
    params = []

    # Filter by playlist IDs
    if playlist_ids is not None:
        from_additions.append("INNER JOIN playlists_tracks AS pt ON t.id = pt.track_id")
        playlist_placeholders = ",".join(["?"] * len(playlist_ids))
        where_clauses.append(f"pt.playlist_id IN ({playlist_placeholders})")
        params.extend(playlist_ids)

    if no_playlist_mode:
        where_clauses.append("NOT EXISTS (SELECT 1 FROM playlists_tracks AS pt WHERE pt.track_id = t.id)")
    elif playlist_ids is None:
        # Default (no playlist filter): playlist members or liked tracks, mirroring
        # count-tracks union semantics. Tracks neither in a playlist nor liked
        # (negative-cache orphans) are excluded; they remain visible via the
        # explicit NO_PLAYLIST_PATTERN filter.
        where_clauses.append("(EXISTS (SELECT 1 FROM playlists_tracks AS pt WHERE pt.track_id = t.id) OR t.liked = 1)")

    # Filter by liked state
    if liked is True:
        where_clauses.append("t.liked = 1")
    elif liked is False:
        where_clauses.append("t.liked = 0")

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

    full_query = base_query + "".join(from_additions)

    if where_clauses:
        full_query += " WHERE " + " AND ".join(where_clauses)

    full_query += group_by_clause + order_by_clause

    logging.debug(f"Executing query: {full_query} with params: {params}")

    raw_results = sqlite.select_db(sqlite.DATABASE, full_query, tuple(params)).fetchall()

    # Process results into a list of dicts for easier handling
    results = []
    for row in raw_results:
        track_id, track_name, release_year, album_name, liked, artist_names, artist_genres = row
        results.append(
            {
                "track_id": track_id,
                "track_name": track_name,
                "release_year": release_year,
                "album_name": album_name,
                "liked": bool(liked),
                "artist_names": artist_names,
                "artist_genres": artist_genres,
            }
        )

    if output_file:
        write_tracks_to_csv(results, output_file)

    return results


def find_liked_only_tracks(output_file=None):
    """Finds tracks that are in Liked Songs but in no playlist.

    These are the tracks worth considering for playlist organization: you saved
    them, but they don't belong to any of your playlists yet.

    Args:
        output_file: Path to output CSV file if specified.

    Returns:
        List of dictionaries containing track information.
    """
    logging.info("Searching for liked tracks in no playlist")
    return find_tracks_by_criteria(playlist_patterns=NO_PLAYLIST_PATTERN, liked=True, output_file=output_file)


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
    Uses a stable schema (always 4 columns) to avoid issues when pattern configuration changes.

    Creates the log file with headers if it doesn't exist. CSV always has 4 columns:
    - timestamp: YYYY-MM-DD HH:MM format
    - total_tracks: Total unique tracks across all playlists or liked
    - pattern_tracks: Count for configured pattern (empty string if no pattern configured)
    - liked_tracks: Count of liked (saved) tracks

    Files written with the previous 3-column schema are migrated in place
    (header rewritten, old rows padded with an empty liked_tracks cell).

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
    liked_tracks = count_liked_tracks()
    # Always count the pattern if configured, otherwise None
    pattern_tracks = count_tracks(new_tracks_pattern) if new_tracks_pattern else None

    # Prepare row with timestamp format: YYYY-MM-DD HH:MM
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    # Always include all columns for schema stability (avoids mismatch issues when pattern is enabled/disabled)
    row = {
        "timestamp": timestamp,
        "total_tracks": total_tracks,
        "pattern_tracks": pattern_tracks if pattern_tracks is not None else "",
        "liked_tracks": liked_tracks,
    }

    # Stable 4-column schema regardless of whether pattern is configured
    fieldnames = ["timestamp", "total_tracks", "pattern_tracks", "liked_tracks"]

    # One-time migration of pre-liked-schema files: rewrite the old 3-column
    # rows with an empty liked_tracks cell so appends never interleave schemas
    if log_path.exists() and log_path.stat().st_size > 0:
        with open(log_path, newline="") as f:
            existing_rows = list(csv.reader(f, delimiter=";"))
        if existing_rows and existing_rows[0] == fieldnames[:3]:
            with open(log_path, "w", newline="") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(fieldnames)
                for old_row in existing_rows[1:]:
                    writer.writerow([*old_row, ""])

    # Check if file needs headers: doesn't exist OR is empty
    needs_header = not log_path.exists() or log_path.stat().st_size == 0

    with open(log_path, "a", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=";")

        if needs_header:
            writer.writeheader()

        writer.writerow(row)

    # Log with appropriate message based on configuration
    if new_tracks_pattern:
        logging.info(
            f"Logged track counts: total={total_tracks}, liked={liked_tracks}, "
            f"{new_tracks_pattern}={pattern_tracks} to {log_path}"
        )
    else:
        logging.info(f"Logged track counts: total={total_tracks}, liked={liked_tracks} to {log_path}")
