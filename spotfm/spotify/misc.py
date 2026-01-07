import logging
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
    tracks_ids = utils.manage_tracks_ids_file(file_path)

    # split tracks_ids in batches
    tracks_ids_batches = [tracks_ids[i : i + batch_size] for i in range(0, len(tracks_ids), batch_size)]

    for i, batch in enumerate(tracks_ids_batches):
        logging.info(f"Batch: {i}/{len(tracks_ids_batches)}")
        tracks = client.client.tracks(batch, market=MARKET)

        for raw_track in tracks["tracks"]:
            try:
                logging.info(f"Initializing track {raw_track['id']}")
                track = Track.get_track(raw_track["id"], client.client)
                track.update_from_track(raw_track, client.client)
                track.sync_to_db(client.client)
                logging.info(f"Track {track.id} added to db")
            except TypeError:
                logging.info("Error: Track not found")

        # Prevent rate limiting (429 errors)
        sleep(1)


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
