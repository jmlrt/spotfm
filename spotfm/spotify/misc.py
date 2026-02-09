import csv
import logging
from pathlib import Path
from time import sleep

from spotfm import sqlite, utils
from spotfm.spotify.constants import BATCH_SIZE, MARKET
from spotfm.spotify.playlist import Playlist
from spotfm.spotify.track import Track


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


def add_tracks_from_file_batch(client, file_path, batch_size=BATCH_SIZE):
    """Add tracks from file using optimized batch processing."""
    tracks_ids = utils.manage_tracks_ids_file(file_path)

    # Track.get_tracks() handles all batching and syncing
    tracks = Track.get_tracks(tracks_ids, client.client, refresh=False, batch_size=batch_size)

    # Sync tracks to DB
    for track in tracks:
        try:
            track.sync_to_db(client.client)
            logging.info(f"Track {track.id} added to db")
        except Exception as e:
            logging.info(f"Error adding track to db: {e}")


def discover_from_playlists(client, discover_playlist_id, sources_playlists_ids, batch_size=BATCH_SIZE):
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
    - Don't exist in the database (never seen before), OR
    - Exist but are currently in other playlists

    Skips tracks that:
    - Are orphaned (in DB but removed from all playlists)

    Args:
        client: Spotify client instance
        discover_playlist_id: Playlist to add discovered tracks to
        sources_playlists_ids: List of playlist IDs to discover from
        batch_size: Batch size for API operations

    See Also:
        - Track.is_orphaned(): Check if track is in zero playlists
        - Track lifecycle timestamps in hacks/create-tables.sql
    """
    discover_playlist = Playlist.get_playlist(discover_playlist_id, client.client, refresh=True, sync_to_db=False)
    new_tracks = []

    for playlist_id in sources_playlists_ids:
        playlist = Playlist.get_playlist(playlist_id, client.client, refresh=True, sync_to_db=False)
        logging.info(f"Looking for new tracks into {playlist.id} - {playlist.name}")
        tracks = playlist.get_tracks(client.client)

        for track in tracks:
            if not track.update_from_db():
                # Track doesn't exist in DB - truly new
                logging.info(f"New track found: {track.id}")
                new_tracks.append(track)
            elif track.is_orphaned():
                # Track exists in DB but not in any playlist (was removed)
                last_seen = getattr(track, "last_seen_at", "unknown")
                logging.info(f"Skipping orphaned track: {track.id} (last seen: {last_seen})")
                # Do NOT add to new_tracks
            else:
                # Track exists and is in other playlists
                logging.debug(f"Skipping track {track.id} (already in playlists)")

        logging.info(f"Adding {len(new_tracks)} new tracks to db")

        for track in new_tracks:
            track.sync_to_db(client.client)

    logging.info(f"Adding new tracks to {discover_playlist.id} - {discover_playlist.name}")
    if len(new_tracks) > 0:
        discover_playlist.add_tracks(new_tracks, client.client)


def count_tracks_by_playlists():
    return sqlite.select_db(
        sqlite.DATABASE,
        "SELECT name, count(*) FROM playlists, playlists_tracks WHERE id = playlists_tracks.playlist_id GROUP BY name;",
    ).fetchall()


def count_tracks(playlists_patterns=None):
    if playlists_patterns:
        # Handle both single pattern (string) and multiple patterns (list)
        if isinstance(playlists_patterns, str):
            playlists_patterns = [playlists_patterns]

        # Resolve patterns to playlist IDs (supports both exact IDs and LIKE patterns)
        ids = []
        for pattern in playlists_patterns:
            # Check if it looks like a playlist ID (22 alphanumeric characters)
            if len(pattern) == 22 and pattern.isalnum():
                ids.append(pattern)
            else:
                # Try exact ID match first, then name pattern match
                results = sqlite.select_db(sqlite.DATABASE, "SELECT id FROM playlists WHERE id = ?;", (pattern,))
                ids_from_db = [row[0] for row in results]
                if not ids_from_db:
                    results = sqlite.select_db(
                        sqlite.DATABASE, "SELECT id FROM playlists WHERE name LIKE ?;", (pattern,)
                    )
                    ids_from_db = [row[0] for row in results]
                ids.extend(ids_from_db)

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
    if not playlist_patterns:
        return []

    # Handle both single pattern (string) and multiple patterns (list)
    if isinstance(playlist_patterns, str):
        playlist_patterns = [playlist_patterns]

    # Resolve patterns to playlist IDs (supports both exact IDs and LIKE patterns)
    playlist_ids = []
    playlist_names = []
    for pattern in playlist_patterns:
        # Check if it looks like a playlist ID (22 alphanumeric characters)
        if len(pattern) == 22 and pattern.isalnum():
            # Fetch playlist name from DB for logging
            results = sqlite.select_db(sqlite.DATABASE, "SELECT name FROM playlists WHERE id = ?;", (pattern,))
            name_row = results.fetchone()
            playlist_ids.append(pattern)
            playlist_names.append(name_row[0] if name_row else pattern)
        else:
            # Try exact ID match first, then name pattern match
            results = sqlite.select_db(sqlite.DATABASE, "SELECT id, name FROM playlists WHERE id = ?;", (pattern,))
            rows = results.fetchall()
            if not rows:
                results = sqlite.select_db(
                    sqlite.DATABASE, "SELECT id, name FROM playlists WHERE name LIKE ?;", (pattern,)
                )
                rows = results.fetchall()
            for row in rows:
                playlist_ids.append(row[0])
                playlist_names.append(row[1])

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
        # SQLite REGEXP is case-sensitive, so use LOWER for expr and item
        genre_subquery = """
            SELECT DISTINCT t2.id
            FROM tracks AS t2
            LEFT JOIN tracks_artists AS tar2 ON t2.id = tar2.track_id
            LEFT JOIN artists AS ar2 ON tar2.artist_id = ar2.id
            LEFT JOIN artists_genres AS ag2 ON ar2.id = ag2.artist_id
            WHERE LOWER(ag2.genre) REGEXP LOWER(?)
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
