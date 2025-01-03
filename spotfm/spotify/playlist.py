import logging
from collections import Counter
from datetime import date

from spotfm import utils
from spotfm.spotify.constants import MARKET
from spotfm.spotify.track import Track


class Playlist:
    def __init__(self, playlist_id, client=None, refresh=True):
        self.id = utils.parse_url(playlist_id)
        logging.info("Initializing Playlist %s", self.id)
        self.name = None
        self.owner = None
        self.tracks = None  # [(id, added_at)]
        self.updated = None
        # TODO: self._tracks
        # TODO: self._tracks_names
        # TODO: self._sorted_tracks

        if (refresh and client is not None) or (not self.update_from_db() and client is not None):
            self.update_from_api(client)
            self.sync_to_db(client)

    def __repr__(self):
        return f"Playlist({self.owner} - {self.name})"

    def __str__(self):
        return f"{self.owner} - {self.name}"

    # TODO
    # @property
    # def tracks(self):
    #     if self._tracks is not None:
    #         return self._tracks
    #     self._tracks = []
    #     for track_id in self.tracks_id:
    #         self._tracks.append(Track(track_id))
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

    def update_from_db(self):
        try:
            self.name, self.owner, self.updated = utils.select_db(
                utils.DATABASE, f"SELECT name, owner, updated_at FROM playlists WHERE id == '{self.id}'"
            ).fetchone()
        except TypeError:
            logging.info("Playlist ID %s not found in database", self.id)
            return False
        results = utils.select_db(
            utils.DATABASE, f"SELECT track_id, added_at FROM playlists_tracks WHERE playlist_id == '{self.id}'"
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
            self.id, fields="items(added_at,track.id),next", market=MARKET, additional_types=["track"]
        )
        tracks = results["items"]
        while results["next"]:
            results = client.next(results)
            tracks.extend(results["items"])
        self.tracks = [(track["track"]["id"], track["added_at"]) for track in tracks if track["track"] is not None]
        self.updated = str(date.today())

    def sync_to_db(self, client):
        logging.info("Syncing playlist %s to database", self.id)
        queries = []
        queries.append(
            f"INSERT OR IGNORE INTO playlists VALUES ('{self.id}', '{self.name}', '{self.owner}', '{self.updated}')"
        )
        for track in self.tracks:
            Track(track[0], client)
            queries.append(f"INSERT OR IGNORE INTO playlists_tracks VALUES ('{self.id}', '{track[0]}', '{track[1]}')")
        logging.debug(queries)
        utils.query_db(utils.DATABASE, queries)

    def get_playlist_genres(self):
        genres = []
        for track in self.tracks:
            for genre in track.genres:
                genres.append(genre)
        return Counter(genres)

    # TODO
    # def remove_track(self, track_id):
    #     self.client.playlist_remove_all_occurrences_of_items(self.id, [track_id])

    # TODO
    # def add_track(self, track_id):
    #     try:
    #         self.client.playlist_add_items(self.id, [track_id])
    #     except TypeError:
    #         print(f"Error: Failed to add {Track(self.client, track_id)}")
