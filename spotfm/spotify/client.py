import spotipy
from spotipy.oauth2 import CacheFileHandler, SpotifyOAuth

from spotfm import sqlite
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

    def get_playlists_id(self, excluded_playlists=None):
        if excluded_playlists is None:
            excluded_playlists = []
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

    def update_playlists(self, excluded_playlists=None, playlists_pattern=None):
        """
        Update playlists from Spotify API.

        Refetches playlist metadata and track lists. Track/album/artist
        metadata is preserved in cache/DB since it rarely changes.

        Args:
            excluded_playlists: List of playlist IDs to exclude
            playlists_pattern: Playlist ID or SQL LIKE pattern to filter playlists by name
                              Examples: "3iunZ1EyEIWUv3irhm1Au1" (exact ID)
                                       "%Discover%" (name pattern)
                              If provided, only updates playlists matching this filter
        """
        if excluded_playlists is None:
            excluded_playlists = []

        if playlists_pattern:
            # Check if it looks like a playlist ID (22 alphanumeric characters)
            if len(playlists_pattern) == 22 and playlists_pattern.isalnum():
                # Treat as exact playlist ID - fetch from Spotify API directly
                playlists_id = [playlists_pattern]
            else:
                # Try exact ID match in DB first
                results = sqlite.select_db(
                    sqlite.DATABASE, "SELECT id FROM playlists WHERE id = ?;", (playlists_pattern,)
                )
                playlists_id = [id[0] for id in results]

                # If no exact match, try name pattern match
                if not playlists_id:
                    results = sqlite.select_db(
                        sqlite.DATABASE, "SELECT id FROM playlists WHERE name LIKE ?;", (playlists_pattern,)
                    )
                    playlists_id = [id[0] for id in results]

            # Only delete data for matching playlists (if they exist in DB)
            if playlists_id:
                placeholders = ",".join(["?"] * len(playlists_id))
                con = sqlite.get_db_connection(sqlite.DATABASE)
                cur = con.cursor()
                cur.execute(f"DELETE FROM playlists WHERE id IN ({placeholders})", playlists_id)
                cur.execute(f"DELETE FROM playlists_tracks WHERE playlist_id IN ({placeholders})", playlists_id)
                con.commit()
        else:
            # Update all playlists
            playlists_id = self.get_playlists_id(excluded_playlists)

            # Delete playlist metadata and playlist-track relationships
            # Keeps tracks/albums/artists tables intact (metadata rarely changes)
            sqlite.query_db(sqlite.DATABASE, ["DELETE FROM playlists", "DELETE FROM playlists_tracks"])

        for playlist_id in playlists_id:
            # refresh=True fetches latest playlist metadata and track IDs
            # Track.get_tracks() is called with refresh=False (default) to respect cache
            playlist = Playlist.get_playlist(playlist_id, self.client, refresh=True)

            # Remove redundant call - already done by get_playlist(refresh=True)
            # playlist.update_from_api(self.client)

            playlist.sync_to_db(self.client)
