import logging
from collections import Counter
from datetime import date

from spotfm import sqlite, utils
from spotfm.spotify.constants import BATCH_SIZE, MARKET
from spotfm.spotify.track import Track
from spotfm.utils import cache_object, retrieve_object_from_cache


class Playlist:
    kind = "playlist"

    def __init__(self, playlist_id, client=None, refresh=True):
        self.id = utils.parse_url(playlist_id)
        logging.info("Initializing Playlist %s", self.id)
        self.name = None
        self.owner = None
        self.raw_tracks = None  # [tuple(id, added_at)]
        self.updated = None
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
        try:
            self.name, self.owner, self.updated = sqlite.select_db(
                sqlite.DATABASE, f"SELECT name, owner, updated_at FROM playlists WHERE id == '{self.id}'"
            ).fetchone()
        except TypeError:
            logging.info("Playlist ID %s not found in database", self.id)
            return False
        results = sqlite.select_db(
            sqlite.DATABASE, f"SELECT track_id, added_at FROM playlists_tracks WHERE playlist_id == '{self.id}'"
        ).fetchall()
        self.tracks = [(col[0], col[1]) for col in results]
        logging.info("Playlist ID %s retrieved from database", self.id)
        return True

    def update_from_api(self, client):
        playlist = client.playlist(self.id, fields="name,owner.id", market=MARKET)
        self.name = utils.sanitize_string(playlist["name"])
        logging.info("Fetching playlist %s - %s from api", self.id, self.name)
        self.owner = utils.sanitize_string(playlist["owner"]["id"])
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
        # Update or insert playlist metadata
        queries.append(
            f"INSERT OR REPLACE INTO playlists VALUES ('{self.id}', '{self.name}', '{self.owner}', '{self.updated}')"
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
