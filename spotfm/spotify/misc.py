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
    discover_playlist = Playlist.get_playlist(discover_playlist_id, client.client, refresh=True, sync_to_db=False)
    new_tracks = []

    for playlist_id in sources_playlists_ids:
        playlist = Playlist.get_playlist(playlist_id, client.client, refresh=True, sync_to_db=False)
        logging.info(f"Looking for new tracks into {playlist.id} - {playlist.name}")
        tracks = playlist.get_tracks(client.client)

        for track in tracks:
            if not track.update_from_db():
                logging.info(f"New track found: {track.id}")
                new_tracks.append(track)

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


def count_tracks(playlists_pattern=None):
    if playlists_pattern:
        results = sqlite.select_db(sqlite.DATABASE, "SELECT id FROM playlists WHERE name LIKE ?;", (playlists_pattern,))
        ids = [id[0] for id in results]
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
                        f"  Found relinked track: {original_artists} - {original_name} → {artists} - {track_name}"
                    )

    logging.info(f"Found {len(relinked_tracks)} relinked tracks across {total_playlists} playlists")

    # Output results
    if output_file:
        write_relinked_tracks_csv(relinked_tracks, output_file)
    else:
        for track in relinked_tracks:
            print(
                f"Relinked;{track['playlist_name']};{track['original_track']};→;{track['replacement_track']};{track['original_id']};{track['replacement_id']}"
            )

    return relinked_tracks


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
