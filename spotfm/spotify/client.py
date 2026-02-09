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

    def update_playlists(self, excluded_playlists=None, playlists_patterns=None):
        """
        Update playlists from Spotify API.

        Refetches playlist metadata and track lists. Track/album/artist
        metadata is preserved in cache/DB since it rarely changes.

        Args:
            excluded_playlists: List of playlist IDs to exclude
            playlists_patterns: Playlist ID(s) or SQL LIKE pattern(s) to filter playlists by name
                               Can be a single string or list of strings.
                               Examples: "3iunZ1EyEIWUv3irhm1Au1" (exact ID)
                                        "%Discover%" (name pattern)
                                        ["playlist1", "playlist2"] (multiple patterns)
                               If provided, only updates playlists matching these filters
        """
        if excluded_playlists is None:
            excluded_playlists = []

        if playlists_patterns:
            # Handle both single pattern (string) and multiple patterns (list)
            if isinstance(playlists_patterns, str):
                playlists_patterns = [playlists_patterns]

            playlist_ids = []
            for pattern in playlists_patterns:
                # Check if it looks like a playlist ID (22 alphanumeric characters)
                if len(pattern) == 22 and pattern.isalnum():
                    # Treat as exact playlist ID - fetch from Spotify API directly
                    playlist_ids.append(pattern)
                else:
                    # Try exact ID match in DB first
                    results = sqlite.select_db(sqlite.DATABASE, "SELECT id FROM playlists WHERE id = ?;", (pattern,))
                    ids_from_db = [id[0] for id in results]

                    # If no exact match, try name pattern match
                    if not ids_from_db:
                        results = sqlite.select_db(
                            sqlite.DATABASE, "SELECT id FROM playlists WHERE name LIKE ?;", (pattern,)
                        )
                        ids_from_db = [id[0] for id in results]

                    playlist_ids.extend(ids_from_db)

            # Only delete data for matching playlists (if they exist in DB)
            if playlist_ids:
                placeholders = ",".join(["?"] * len(playlist_ids))
                con = sqlite.get_db_connection(sqlite.DATABASE)
                cur = con.cursor()
                cur.execute(f"DELETE FROM playlists WHERE id IN ({placeholders})", playlist_ids)
                cur.execute(f"DELETE FROM playlists_tracks WHERE playlist_id IN ({placeholders})", playlist_ids)
                con.commit()
        else:
            # Update all playlists
            playlist_ids = self.get_playlists_id(excluded_playlists)

            # Delete playlist metadata and playlist-track relationships
            # Keeps tracks/albums/artists tables intact (metadata rarely changes)
            sqlite.query_db(sqlite.DATABASE, ["DELETE FROM playlists", "DELETE FROM playlists_tracks"])

        for playlist_id in playlist_ids:
            # refresh=True fetches latest playlist metadata and track IDs
            # Track.get_tracks() is called with refresh=False (default) to respect cache
            playlist = Playlist.get_playlist(playlist_id, self.client, refresh=True)

            # Remove redundant call - already done by get_playlist(refresh=True)
            # playlist.update_from_api(self.client)

            playlist.sync_to_db(self.client)
