import time
from collections import Counter

import spotipy
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyOAuth

from spotfm import utils

REDIRECT_URI = "http://127.0.0.1:9090"
SCOPE = "user-library-read playlist-read-private playlist-read-collaborative"


class Client:
    def __init__(
        self, client_id, client_secret, redirect_uri=REDIRECT_URI, scope=SCOPE
    ):
        self.client = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=scope,
            )
        )


class Playlist:
    def __init__(self, client, playlist_id):
        self.client = client
        self.id = playlist_id
        self.raw_playlist = client.playlist(playlist_id)
        self.name = self.raw_playlist["name"]
        self.owner = self.raw_playlist["owner"]["display_name"]
        self._tracks = None
        self._tracks_ids = None
        self._tracks_names = None
        self._sorted_tracks = None
        utils.cache_object(self, f"playlists/{playlist_id}.pickle")

    @classmethod
    def get_playlist(cls, client, playlist_id, refresh=False):
        cache_file = f"spotify/playlists/{playlist_id}.pickle"
        playlist = utils.retrieve_object_from_cache(cache_file)
        if playlist is not None and refresh is False:
            return playlist
        return Playlist(client, playlist_id)

    @classmethod
    def get_user_playlists(cls, client, excluded_playlists=[]):
        playlists_ids = []
        user = client.current_user()["id"]

        def filter_playlists(playlists):
            for playlist in playlists["items"]:
                if (
                    playlist["owner"]["id"] == user
                    and playlist["id"] not in excluded_playlists
                ):
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
        tracks = self.raw_playlist["tracks"]
        for track in tracks["items"]:
            time.sleep(0.1)
            try:
                if track["track"]["type"] == "track":
                    self._tracks.append(
                        Track.get_track(self.client, track["track"]["id"])
                    )
            except TypeError:
                print(f"Error: Failed to add {track}")

            while tracks["next"]:
                try:
                    tracks = self.client.next(tracks)
                    for track in tracks["items"]:
                        if track["track"]["type"] == "track":
                            self._tracks.append(
                                Track.get_track(self.client, track["track"]["id"])
                            )
                except (TypeError, SpotifyException):
                    print(f"Error: Failed to add {track}")

        return self._tracks

    @property
    def tracks_ids(self):
        if self._tracks_ids is not None:
            return self._tracks_ids
        self._tracks_ids = []

        for track in self.tracks:
            self._tracks_ids.append(track.id)
        return self._tracks_ids

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

    def remove_track(self, track_id):
        self.client.playlist_remove_all_occurrences_of_items(self.id, [track_id])

    def add_track(self, track_id):
        try:
            self.client.playlist_add_items(self.id, [track_id])
        except TypeError:
            print(f"Error: Failed to add {Track(self.client, track_id)}")

    def __repr__(self):
        return f"Playlist({self.owner} - {self.name})"

    def __str__(self):
        return f"{self.owner} - {self.name}"


class Track:
    def __init__(self, client, track_id):
        self.client = client
        self.id = track_id
        self.raw_track = client.track(track_id)
        self._artists = None
        self._genres = None
        self.name = self.raw_track["name"]
        self.album = self.raw_track["album"]["name"]
        self.release_date = self.raw_track["album"]["release_date"]
        utils.cache_object(self, f"tracks/{track_id}.pickle")

    @classmethod
    def get_track(cls, client, track_id, refresh=False):
        cache_file = f"spotify/tracks/{track_id}.pickle"
        track = utils.retrieve_object_from_cache(cache_file)
        if track is not None and refresh is False:
            return track
        return Track(client, track_id)

    @property
    def artists(self):
        if self._artists is not None:
            return self._artists
        self._artists = []
        for raw_artist in self.raw_track["artists"]:
            self._artists.append(Artist.get_artist(self.client, raw_artist["id"]))
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
    def __init__(self, client, artist_id):
        self.client = client
        self.id = artist_id
        self.raw_artist = client.artist(artist_id)
        self.name = self.raw_artist["name"]
        self.genres = self.raw_artist["genres"]
        utils.cache_object(self, f"artists/{artist_id}.pickle")

    def __repr__(self):
        return f"Artist({self.name})"

    def __str__(self):
        return self.name

    @classmethod
    def get_artist(cls, client, artist_id, refresh=False):
        cache_file = f"spotify/artists/{artist_id}.pickle"
        artist = utils.retrieve_object_from_cache(cache_file)
        if artist is not None and refresh is False:
            return artist
        return Artist(client, artist_id)


def count_tracks_in_playlists(client):
    # TODO add EXCLUDED_PLAYLISTS
    playlists_ids = Playlist.get_user_playlists(client)
    total_tracks = []

    csvfile = utils.WORK_DIR / f"{utils.get_date()}_count.csv"
    with open(csvfile, "w") as f:
        f.write("playlist;tracks\n")
        for playlist_id in playlists_ids:
            playlist = Playlist.get_playlist(client, playlist_id, refresh=True)
            f.write(f"{playlist_id}_{playlist.name};{len(playlist.tracks)}\n")
            for track in playlist.tracks:
                total_tracks.append(track)
        f.write(f"TOTAL;{len(set(total_tracks))}\n")
    print(f"{len(set(total_tracks))}")
