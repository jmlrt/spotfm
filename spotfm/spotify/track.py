import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from time import sleep

from spotfm import sqlite, utils
from spotfm.spotify.album import Album
from spotfm.spotify.artist import Artist
from spotfm.spotify.constants import BATCH_SIZE, MARKET
from spotfm.utils import cache_object, retrieve_object_from_cache


class Track:
    kind = "track"

    def __init__(self, id, client=None, refresh=False):
        logging.info("Initializing Track %s", id)
        self.id = utils.parse_url(id)
        self.name = None
        self.album_id = None
        self.album = None
        self.release_date = None
        self.artists_id = None
        self.updated = None
        self.artists = None
        self._genres = None

    def __repr__(self):
        artists_names = [artist.name for artist in self.artists]
        return f"Track({', '.join(artists_names)} - {self.name})"

    def __str__(self):
        artists_names = [artist.name for artist in self.artists]
        return f"{', '.join(artists_names)} - {self.name}"

    def __lt__(self, other):
        return self.__repr__() < other.__repr__()

    @classmethod
    def get_track(cls, id, client=None, refresh=False, sync_to_db=True):
        track = retrieve_object_from_cache(cls.kind, id)
        if track is not None and (client is None or not refresh):
            return track

        track = Track(id, client)
        if client is not None and (not track.update_from_db(client) or refresh):
            track.update_from_api(client)
            cache_object(track)
            if sync_to_db:
                track.sync_to_db(client)
        return track

    @classmethod
    def get_tracks(cls, tracks_id, client=None, refresh=False, batch_size=BATCH_SIZE):
        """
        Fetch multiple tracks efficiently, leveraging cache/DB.

        Strategy:
        1. Check cache/DB for all tracks first (respects 3-tier cache)
        2. Only batch fetch missing tracks from API
        3. Collect album/artist IDs from missing tracks
        4. Batch fetch only missing albums and artists
        5. Return all tracks (cached + newly fetched)
        """
        if not tracks_id:
            return []

        tracks = []
        tracks_to_fetch = []

        # Phase 1: Check cache/DB for all tracks (CRITICAL for performance)
        for track_id in tracks_id:
            # Try pickle cache first
            track = retrieve_object_from_cache(cls.kind, track_id)
            if track is not None and not refresh:
                tracks.append(track)
                continue

            # Try DB
            track = Track(track_id, client)
            if not refresh and track.update_from_db(client):
                tracks.append(track)
                continue

            # Track not in cache/DB, need to fetch from API
            tracks_to_fetch.append(track_id)

        # If all tracks cached, return early (typical case for update_playlists)
        if not tracks_to_fetch:
            logging.info(f"All {len(tracks)} tracks retrieved from cache/DB")
            return tracks

        logging.info(f"Retrieved {len(tracks)} tracks from cache/DB, fetching {len(tracks_to_fetch)} from API")

        # Phase 2: Fetch missing tracks in parallel with rate limiting
        # Uses ThreadPoolExecutor to parallelize individual API calls while enforcing rate limits.
        # Rate limiting is enforced by throttling task submission rate to maintain same ~10 req/s
        # as sequential baseline. Parallel execution hides network latency while respecting API limits.
        #
        # NOTE: Thread safety - spotipy's requests.Session is assumed thread-safe for concurrent
        # read-only operations. If threading issues occur, fall back to sequential fetch by setting
        # MAX_WORKERS = 1 below.
        MAX_WORKERS = 5  # Conservative: 5 parallel workers allow ~5 req/s burst
        SUBMIT_DELAY = 0.1  # 0.1s between submissions → ~10 req/s max rate (same as sequential baseline)

        def fetch_track(track_id):
            """Fetch single track's raw data from API."""
            try:
                return client.track(track_id, market=MARKET)
            except Exception as e:
                # Skip tracks that can't be fetched (deleted, unavailable, etc.)
                logging.debug(f"Failed to fetch track {track_id}: {e}")
                return None

        # Parallel fetch phase: submit tasks with rate limiting
        # Maintain order using indexed futures
        futures_with_index = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for i, track_id in enumerate(tracks_to_fetch):
                future = executor.submit(fetch_track, track_id)
                futures_with_index.append((i, future))
                # Rate limiting: sleep between submissions (same as sequential baseline)
                if i < len(tracks_to_fetch) - 1:
                    sleep(SUBMIT_DELAY)

            # Collect results in original order
            results = [None] * len(futures_with_index)
            for i, future in futures_with_index:
                try:
                    raw_track = future.result()
                    if raw_track is not None:
                        results[i] = raw_track
                except Exception as e:
                    # Thread raised an exception - log and skip this track
                    logging.warning(f"Thread failed fetching track at index {i}: {e}")

        # Filter out None results while maintaining order
        raw_tracks = [track for track in results if track is not None]

        # Sequential processing after parallel fetches
        # Create track objects, fetch albums/artists, and sync to DB
        album_ids = []
        artist_ids = []

        # Collect all album/artist IDs from raw tracks
        for raw_track in raw_tracks:
            album_ids.append(raw_track["album"]["id"])
            artist_ids.extend([artist["id"] for artist in raw_track["artists"]])

        # Batch fetch albums and artists
        albums_dict = {}
        if album_ids:
            logging.info("Batch fetching albums (checking cache first)")
            unique_album_ids = list(dict.fromkeys(album_ids))
            albums = Album.get_albums(unique_album_ids, client, refresh=refresh)
            albums_dict = {album.id: album for album in albums if album is not None}

        artists_dict = {}
        if artist_ids:
            logging.info("Batch fetching artists (checking cache first)")
            unique_artist_ids = list(dict.fromkeys(artist_ids))
            artists = Artist.get_artists(unique_artist_ids, client, refresh=refresh)
            artists_dict = {artist.id: artist for artist in artists if artist is not None}

        # Populate album.artists
        for album in albums_dict.values():
            if album.artists_id:
                album.artists = [artists_dict[aid] for aid in album.artists_id if aid in artists_dict]

        # Create track objects from fetched data
        for raw_track in raw_tracks:
            try:
                track = Track(raw_track["id"], client)
                track.name = utils.sanitize_string(raw_track["name"])
                track.album_id = raw_track["album"]["id"]
                track.updated = str(date.today())

                # Use pre-fetched album
                album = albums_dict.get(track.album_id)
                if album:
                    track.album = album.name
                    track.release_date = album.release_date

                # Use pre-fetched artists
                track.artists_id = [artist["id"] for artist in raw_track["artists"]]
                track.artists = [artists_dict[aid] for aid in track.artists_id if aid in artists_dict]

                track.sync_to_db(client)
                cache_object(track)
                tracks.append(track)

            except (TypeError, KeyError) as e:
                logging.info(f"Error processing track: {e}")

        return tracks

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

    def update_from_db(self, client=None):
        try:
            # Try new schema first (with lifecycle columns)
            result = sqlite.select_db(
                sqlite.DATABASE,
                f"SELECT name, updated_at, created_at, last_seen_at FROM tracks WHERE id == '{self.id}'",
            ).fetchone()
            if result:
                self.name, self.updated, self.created_at, self.last_seen_at = result
        except sqlite3.OperationalError as e:
            # Fallback to old schema (columns don't exist yet)
            if "no such column" in str(e).lower():
                logging.debug("Lifecycle columns not found, using old schema")
                result = sqlite.select_db(
                    sqlite.DATABASE, f"SELECT name, updated_at FROM tracks WHERE id == '{self.id}'"
                ).fetchone()
                if result:
                    self.name, self.updated = result
                    # Set default values for missing columns
                    self.created_at = str(date.today())
                    self.last_seen_at = str(date.today())
            else:
                raise
        except TypeError:
            logging.info("Track ID %s not found in database", self.id)
            return False
        try:
            self.album_id = sqlite.select_db(
                sqlite.DATABASE, f"SELECT album_id FROM albums_tracks WHERE track_id == '{self.id}'"
            ).fetchone()[0]
        except TypeError:
            logging.info("Album ID %s not found in database", self.id)
            return False
        album = Album.get_album(self.album_id, client)
        # TODO: add Album object instead
        self.album = album.name
        self.release_date = album.release_date
        results = sqlite.select_db(
            sqlite.DATABASE, f"SELECT artist_id FROM tracks_artists WHERE track_id == '{self.id}'"
        ).fetchall()
        self.artists_id = [col[0] for col in results]
        self.artists = [Artist.get_artist(id, client) for id in self.artists_id]
        logging.info("Track ID %s retrieved from database", self.id)
        return True

    def update_from_api(self, client):
        logging.info("Fetching track %s from api", self.id)
        track = client.track(self.id, market=MARKET)
        self.name = utils.sanitize_string(track["name"])
        self.album_id = track["album"]["id"]
        album = Album.get_album(self.album_id, client)
        self.album = album.name
        self.release_date = album.release_date
        self.artists_id = [artist["id"] for artist in track["artists"]]
        self.artists = [Artist.get_artist(id, client) for id in self.artists_id]
        self.updated = str(date.today())
        # Only set created_at if not already set (preserve original creation date)
        if not hasattr(self, "created_at") or self.created_at is None:
            self.created_at = str(date.today())
        self.last_seen_at = str(date.today())  # Always update when fetched

    def update_from_track(self, track, client):
        self.name = utils.sanitize_string(track["name"])
        self.album_id = track["album"]["id"]
        album = Album.get_album(self.album_id, client)
        self.album = album.name
        self.release_date = album.release_date
        self.artists_id = [artist["id"] for artist in track["artists"]]
        self.artists = [Artist.get_artist(id, client) for id in self.artists_id]
        self.updated = str(date.today())

    def sync_to_db(self, client):
        logging.info("Syncing track %s to database", self.id)
        # Remove redundant Album.get_album() call
        # Album should already be synced by Track.get_tracks()
        queries = []

        # Check if lifecycle columns exist
        try:
            sqlite.select_db(sqlite.DATABASE, "SELECT created_at FROM tracks LIMIT 1")
            has_lifecycle = True
        except sqlite3.OperationalError:
            has_lifecycle = False

        if has_lifecycle:
            # New schema with lifecycle tracking
            created = getattr(self, "created_at", str(date.today()))
            last_seen = str(date.today())
            queries.append(
                f"INSERT OR REPLACE INTO tracks VALUES "
                f"('{self.id}', '{self.name}', '{self.updated}', "
                f"COALESCE((SELECT created_at FROM tracks WHERE id = '{self.id}'), '{created}'), "
                f"'{last_seen}')"
            )
        else:
            # Old schema without lifecycle tracking
            queries.append(f"INSERT OR IGNORE INTO tracks VALUES ('{self.id}', '{self.name}', '{self.updated}')")

        queries.append(f"INSERT OR IGNORE INTO albums_tracks VALUES ('{self.album_id}', '{self.id}')")
        for artist in self.artists:
            queries.append(f"INSERT OR IGNORE INTO tracks_artists VALUES ('{self.id}', '{artist.id}')")
        logging.debug(queries)
        sqlite.query_db(sqlite.DATABASE, queries)
        logging.info(f"Track {self.id} added to db")

    def is_orphaned(self):
        """Check if track is not currently in any playlist.

        Orphaned tracks are intentionally preserved in the database to serve
        as a "negative cache" for the discover_from_playlists feature.

        WARNING: Do not delete orphaned tracks, as this will cause
        discover_from_playlists to re-add previously removed tracks.

        Returns:
            bool: True if track exists in DB but not in any playlists_tracks entry
        """
        result = sqlite.select_db(
            sqlite.DATABASE, f"SELECT COUNT(*) FROM playlists_tracks WHERE track_id = '{self.id}'"
        ).fetchone()
        return result[0] == 0

    def get_artists_names(self):
        artists_names = []
        for artist in self.artists:
            artists_names.append(artist.name)
        return ", ".join(artists_names)

    def get_genres_names(self):
        return ", ".join(self.genres)
