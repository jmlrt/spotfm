from collections import Counter

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from spotfm import utils

REDIRECT_URI = "http://127.0.0.1:9090"
SCOPE = "user-library-read playlist-read-private playlist-read-collaborative"

# TODO
# update sqlite db from the spotify api


class Client:
    def __init__(self, client_id, client_secret, redirect_uri=REDIRECT_URI, scope=SCOPE):
        self.client = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=scope,
            )
        )


class Playlist:
    def __init__(self, playlist_id):
        self.id = playlist_id
        self.name, self.owner = utils.select_db(
            utils.DATABASE, f"SELECT name, owner FROM playlists WHERE id == '{self.id}'"
        ).fetchone()
        results = utils.select_db(
            utils.DATABASE, f"SELECT track_id FROM playlists_tracks WHERE playlist_id == '{self.id}'"
        ).fetchall()
        self.tracks_id = [col[0] for col in results]

        self._tracks = None
        self._tracks_names = None
        self._sorted_tracks = None

    @classmethod
    def get_user_playlists(cls, client, excluded_playlists=[]):
        playlists_ids = []
        user = client.current_user()["id"]

        def filter_playlists(playlists):
            for playlist in playlists["items"]:
                if playlist["owner"]["id"] == user and playlist["id"] not in excluded_playlists:
                    yield playlist["id"]

        playlists = client.current_user_playlists()
        for playlist in filter_playlists(playlists):
            playlists_ids.append(playlist)
        while playlists["next"]:
            playlists = client.next(playlists)
            for playlist in filter_playlists(playlists):
                playlists_ids.append(playlist)

        return playlists_ids

    @property
    def tracks(self):
        if self._tracks is not None:
            return self._tracks
        self._tracks = []
        for track_id in self.tracks_id:
            self._tracks.append(Track(track_id))
        return self._tracks

    @property
    def tracks_names(self):
        if self._tracks_names is not None:
            return self._tracks_names
        self._tracks_names = []
        for track in self.tracks:
            self._tracks_names.append(track.__str__())
        return self._tracks_names

    @property
    def sorted_tracks(self):
        if self._sorted_tracks is not None:
            return self._sorted_tracks
        self._sorted_tracks = sorted(self.tracks)
        return self._sorted_tracks

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

    def __repr__(self):
        return f"Playlist({self.owner} - {self.name})"

    def __str__(self):
        return f"{self.owner} - {self.name}"


class Track:
    def __init__(self, track_id):
        self.id = track_id
        self.name = utils.select_db(utils.DATABASE, f"SELECT name FROM tracks WHERE id == '{self.id}'").fetchone()[0]
        self.album_id = utils.select_db(
            utils.DATABASE, f"SELECT album_id FROM albums_tracks WHERE track_id == '{self.id}'"
        ).fetchone()[0]
        self.album, self.release_date = utils.select_db(
            utils.DATABASE, f"SELECT name, release_date FROM albums WHERE id == '{self.album_id}'"
        ).fetchone()
        results = utils.select_db(
            utils.DATABASE, f"SELECT artist_id FROM tracks_artists WHERE track_id == '{self.id}'"
        ).fetchall()
        self.artists_id = [col[0] for col in results]
        self._artists = None
        self._genres = None

    @property
    def artists(self):
        if self._artists is not None:
            return self._artists
        self._artists = []
        for artist_id in self.artists_id:
            self._artists.append(Artist(artist_id))
        return self._artists

    @property
    def genres(self):
        if self._genres is not None:
            return self._genres
        genres = []
        for artist in self.artists:
            for genre in artist.genres:
                genres.append(genre)
        self._genres = list(dict.fromkeys(genres))
        return self._genres

    def get_artists_names(self):
        artists_names = []
        for artist in self.artists:
            artists_names.append(artist.name)
        return ", ".join(artists_names)

    def get_genres_names(self):
        return ", ".join(self.genres)

    def __repr__(self):
        artists_names = [artist.name for artist in self.artists]
        return f"Track({', '.join(artists_names)} - {self.name})"

    def __str__(self):
        artists_names = [artist.name for artist in self.artists]
        return f"{', '.join(artists_names)} - {self.name}"

    def __lt__(self, other):
        return self.__repr__() < other.__repr__()


class Artist:
    def __init__(self, artist_id):
        self.id = artist_id
        self.name = utils.select_db(utils.DATABASE, f"SELECT name FROM artists WHERE id == '{self.id}'").fetchone()[0]
        results = utils.select_db(
            utils.DATABASE, f"SELECT genre FROM artists_genres WHERE artist_id == '{self.id}'"
        ).fetchall()
        self.genres = [col[0] for col in results]

    def __repr__(self):
        return f"Artist({self.name})"

    def __str__(self):
        return self.name


def count_tracks_in_playlists():
    return utils.select_db(
        utils.DATABASE,
        "select name, count(*) from playlists, playlists_tracks where id = playlists_tracks.playlist_id group by name;",
    ).fetchall()
