import spotipy
from spotipy.oauth2 import CacheFileHandler, SpotifyOAuth

from spotfm import utils
from spotfm.spotify.constants import REDIRECT_URI, SCOPE, TOKEN_CACHE_FILE
from spotfm.spotify.playlist import Playlist

# TODO:
# - use query params instead of f-strings
#    (https://docs.python.org/3/library/sqlite3.html#sqlite3-placeholders)


class Client:
    def __init__(self, client_id, client_secret, redirect_uri=REDIRECT_URI, scope=SCOPE):
        handler = CacheFileHandler(cache_path=TOKEN_CACHE_FILE)
        self.client = spotipy.Spotify(
            retries=0,
            auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=scope,
                cache_handler=handler,
            ),
        )

    def get_playlists_id(self, excluded_playlists=[]):
        playlists_ids = []
        user = self.client.current_user()["id"]

        def filter_playlists(playlists):
            for playlist in playlists["items"]:
                if playlist["owner"]["id"] == user and playlist["id"] not in excluded_playlists:
                    yield playlist["id"]

        playlists = self.client.current_user_playlists()
        for playlist in filter_playlists(playlists):
            playlists_ids.append(playlist)
        while playlists["next"]:
            playlists = self.client.next(playlists)
            for playlist in filter_playlists(playlists):
                playlists_ids.append(playlist)

        return playlists_ids

    def update_playlists(self, excluded_playlists=[]):
        playlists_id = self.get_playlists_id(excluded_playlists)
        utils.query_db(utils.DATABASE, ["DELETE FROM playlists", "DELETE FROM playlists_tracks"])
        for playlist_id in playlists_id:
            Playlist(playlist_id, self.client)
