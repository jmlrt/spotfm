import logging
import sqlite3
from collections import Counter
from datetime import date

from spotfm import sqlite, utils
from spotfm.spotify.constants import BATCH_SIZE, MARKET
from spotfm.spotify.track import Track
from spotfm.utils import cache_object, retrieve_object_from_cache

# Cache for snapshot_id column existence check, keyed by database path (as string for consistency)
_snapshot_id_column_cache = {}


def reset_snapshot_id_column_cache():
    """Clear the snapshot_id column existence cache for all databases."""
    _snapshot_id_column_cache.clear()


def _check_snapshot_id_column():
    """Check if snapshot_id column exists in playlists table (cached per database).

    If the column is missing, automatically add it via ALTER TABLE migration.
    """
    db_key = str(sqlite.DATABASE)
    cached = _snapshot_id_column_cache.get(db_key)
    if cached is not None:
        return cached

    # Initial existence check
    try:
        sqlite.select_db(sqlite.DATABASE, "SELECT snapshot_id FROM playlists LIMIT 1")
        _snapshot_id_column_cache[db_key] = True
        return True
    except sqlite3.OperationalError as e:
        msg = str(e).lower()
        # Only attempt migration if the column is actually missing
        if "no such column" not in msg:
            raise

    # Column is missing - attempt migration by adding it
    logging.info("Adding snapshot_id column to playlists table")
    try:
        sqlite.query_db(sqlite.DATABASE, ["ALTER TABLE playlists ADD COLUMN snapshot_id TEXT"])
    except sqlite3.OperationalError as alter_err:
        alter_msg = str(alter_err).lower()
        # Column might have been added concurrently or already exist
        if "duplicate column" in alter_msg:
            logging.debug("snapshot_id column already exists in playlists table")
        else:
            # Transient failure (e.g. database locked) — don't cache so the next call can retry
            logging.warning("Failed to add snapshot_id column to playlists table: %s", alter_err)
            return False

    # Re-check after migration
    try:
        sqlite.select_db(sqlite.DATABASE, "SELECT snapshot_id FROM playlists LIMIT 1")
        _snapshot_id_column_cache[db_key] = True
        logging.debug("snapshot_id column is now available in playlists table")
    except sqlite3.OperationalError as e:
        logging.warning("snapshot_id column still missing after migration attempt: %s", e)
        _snapshot_id_column_cache[db_key] = False
    return _snapshot_id_column_cache[db_key]


class Playlist:
    kind = "playlist"

    def __init__(self, playlist_id, client=None, refresh=True):
        self.id = utils.parse_url(playlist_id)
        logging.info("Initializing Playlist %s", self.id)
        self.name = None
        self.owner = None
        self.raw_tracks = None  # [(track_id, added_at)] loaded from DB or API
        self.tracks = None  # [Track] after hydration; None until update_from_api() is called
        self.updated = None
        self.snapshot_id = None  # Spotify snapshot ID to detect unchanged playlists
        # TODO: self._tracks_names
        # TODO: self._sorted_tracks

    def __repr__(self):
        return f"Playlist({self.owner} - {self.name})"

    def __str__(self):
        return f"{self.owner} - {self.name}"

    @classmethod
    def get_playlist(cls, id, client=None, refresh=False, sync_to_db=True):
        playlist = retrieve_object_from_cache(cls.kind, id)
        if playlist is not None and (client is None or not refresh):
            return playlist

        playlist = Playlist(id, client)
        if client is not None and (not playlist.update_from_db() or refresh):
            playlist.update_from_api(client)
            cache_object(playlist)
            if sync_to_db:
                playlist.sync_to_db(client)
        return playlist

    # TODO
    # @property
    # def tracks(self):
    #     if self._tracks is not None:
    #         return self._tracks
    #     self._tracks = []
    #     for track_id in self.tracks_id:
    #         self._tracks.append(Track.get_track(track_id), client)
    #     return self._tracks

    # TODO
    # @property
    # def tracks_names(self):
    #     if self._tracks_names is not None:
    #         return self._tracks_names
    #     self._tracks_names = []
    #     for track in self.tracks:
    #         self._tracks_names.append(track.__str__())
    #     return self._tracks_names

    # TODO
    # @property
    # def sorted_tracks(self):
    #     if self._sorted_tracks is not None:
    #         return self._sorted_tracks
    #     self._sorted_tracks = sorted(self.tracks)
    #     return self._sorted_tracks

    def get_tracks(self, client):
        raw_tracks_id = [raw_track[0] for raw_track in self.raw_tracks]
        return Track.get_tracks(raw_tracks_id, client)

    def update_from_db(self):
        has_snapshot_id = _check_snapshot_id_column()

        try:
            if has_snapshot_id:
                # New schema with snapshot_id
                result = sqlite.select_db(
                    sqlite.DATABASE,
                    f"SELECT name, owner, updated_at, snapshot_id FROM playlists WHERE id == '{self.id}'",
                ).fetchone()
                self.name, self.owner, self.updated, self.snapshot_id = result
            else:
                # Old schema without snapshot_id
                result = sqlite.select_db(
                    sqlite.DATABASE, f"SELECT name, owner, updated_at FROM playlists WHERE id == '{self.id}'"
                ).fetchone()
                self.name, self.owner, self.updated = result
                self.snapshot_id = None
        except TypeError:
            logging.info("Playlist ID %s not found in database", self.id)
            return False
        results = sqlite.select_db(
            sqlite.DATABASE, f"SELECT track_id, added_at FROM playlists_tracks WHERE playlist_id == '{self.id}'"
        ).fetchall()
        self.raw_tracks = [(col[0], col[1]) for col in results]
        logging.info("Playlist ID %s retrieved from database", self.id)
        return True

    def update_from_api(self, client):
        playlist = client.playlist(self.id, fields="name,owner.id,snapshot_id", market=MARKET)
        self.name = utils.sanitize_string(playlist["name"])
        logging.info("Fetching playlist %s - %s from api", self.id, self.name)
        self.owner = utils.sanitize_string(playlist["owner"]["id"])
        new_snapshot = playlist.get("snapshot_id")

        # If snapshot_id is not set but DB has it, load it for comparison
        if not self.snapshot_id and _check_snapshot_id_column():
            try:
                result = sqlite.select_db(
                    sqlite.DATABASE, f"SELECT snapshot_id FROM playlists WHERE id == '{self.id}'"
                ).fetchone()
                if result:
                    self.snapshot_id = result[0]
            except (sqlite3.OperationalError, TypeError):
                # Column might not exist yet or playlist not in DB
                pass

        # Skip re-fetching playlist items if snapshot hasn't changed
        if self.snapshot_id and self.snapshot_id == new_snapshot:
            logging.info("Playlist %s unchanged (snapshot_id match), skipping API item fetch", self.id)
            # Ensure raw_tracks and tracks are populated for downstream operations (e.g., sync_to_db)
            if self.raw_tracks is None:
                # update_from_db() was not called — fetch track IDs from DB
                results = sqlite.select_db(
                    sqlite.DATABASE,
                    f"SELECT track_id, added_at FROM playlists_tracks WHERE playlist_id == '{self.id}'",
                ).fetchall()
                self.raw_tracks = [(col[0], col[1]) for col in results]
            if self.tracks is None:
                # Hydrate Track objects from raw_tracks (set by update_from_db or just above)
                self.tracks = self.get_tracks(client)
            # Update the last-updated marker to reflect a successful refresh
            self.updated = str(date.today())
            return

        self.snapshot_id = new_snapshot
        results = client.playlist_items(
            self.id, fields="items(added_at,track(id,linked_from)),next", market=MARKET, additional_types=["track"]
        )
        tracks = results["items"]
        while results["next"]:
            results = client.next(results)
            tracks.extend(results["items"])
        # Use linked_from.id if available (for relinked tracks), otherwise use track.id
        # Spotify relinks tracks based on market availability, but we want the original track ID
        self.raw_tracks = []
        for track in tracks:
            if track["track"] is not None:
                track_data = track["track"]
                # If track is relinked, use the original track ID from linked_from
                track_id = track_data["linked_from"]["id"] if track_data.get("linked_from") else track_data["id"]
                self.raw_tracks.append((track_id, track["added_at"]))
        self.tracks = self.get_tracks(client)
        self.updated = str(date.today())

    def sync_to_db(self, client):
        logging.info("Syncing playlist %s - %s to database", self.id, self.name)
        queries = []

        has_snapshot_id = _check_snapshot_id_column()

        # Update or insert playlist metadata with explicit column names for schema stability
        if has_snapshot_id:
            # New schema with snapshot_id - escape single quotes for SQL safety
            if self.snapshot_id:
                escaped = self.snapshot_id.replace("'", "''")
                snapshot_id_val = f"'{escaped}'"
            else:
                snapshot_id_val = "NULL"
            queries.append(
                f"INSERT OR REPLACE INTO playlists (id, name, owner, updated_at, snapshot_id) VALUES ('{self.id}', '{self.name}', '{self.owner}', '{self.updated}', {snapshot_id_val})"
            )
        else:
            # Old schema without snapshot_id
            queries.append(
                f"INSERT OR REPLACE INTO playlists (id, name, owner, updated_at) VALUES ('{self.id}', '{self.name}', '{self.owner}', '{self.updated}')"
            )

        # Delete all existing tracks for this playlist to handle removed tracks
        queries.append(f"DELETE FROM playlists_tracks WHERE playlist_id = '{self.id}'")
        # Sync all unique tracks first
        for track in self.tracks:
            track.sync_to_db(client)
        # Insert tracks using raw_tracks to preserve duplicates and added_at dates
        # Use INSERT OR IGNORE in case playlist has same track multiple times
        for track_id, added_at in self.raw_tracks:
            queries.append(f"INSERT OR IGNORE INTO playlists_tracks VALUES ('{self.id}', '{track_id}', '{added_at}')")
        logging.debug(queries)
        sqlite.query_db(sqlite.DATABASE, queries)

    def get_playlist_genres(self):
        genres = []
        for track in self.tracks:
            for genre in track.genres:
                genres.append(genre)
        return Counter(genres)

    # TODO
    # def remove_track(self, track_id):
    #     self.client.playlist_remove_all_occurrences_of_items(self.id, [track_id])

    def add_tracks(self, tracks, client, batch_size=BATCH_SIZE):
        tracks_id = [track.id for track in tracks]
        tracks_id_batches = [tracks_id[i : i + batch_size] for i in range(0, len(tracks_id), batch_size)]

        for i, batch in enumerate(tracks_id_batches):
            logging.info(f"Batch: {i}/{len(tracks_id_batches)}")
            try:
                client.playlist_add_items(self.id, batch)
            except TypeError:
                print(f"Error: Failed to add {batch} to playlist {self.id}")
