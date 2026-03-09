"""Track entity model with three-tier caching and lifecycle tracking.

ARCHITECTURE:
=============

Track implements the three-tier caching pattern:
1. Pickle cache (~/.cache/spotfm/track/{id}.pickle) - Fastest
2. SQLite database (~/.spotfm/spotify.db) - Persistent
3. Spotify API - Source of truth

LIFECYCLE TRACKING:
===================

Tracks maintain timestamps to prevent re-adding intentionally removed tracks:

- created_at: When track was first discovered (immutable, set once)
- last_seen_at: Last time track appeared in any playlist (updated on every sync)

Orphaned tracks (in database but not in any playlist) accumulate and serve as a
"negative cache" for the discovery feature. This prevents discover_from_playlists
from re-adding tracks that were intentionally removed.

WHY THIS MATTERS:
- Deleting orphaned tracks would cause discover_from_playlists to re-add removed tracks
- Tracks are never purged from the database (intentional design)
- Only cleanup should be: tracks not seen in 90+ days AND with explicit user opt-in

PERFORMANCE OPTIMIZATION:
==========================

- Module-level cache (_lifecycle_columns_cache) checks if lifecycle columns exist
  on the first query, then caches the result to avoid checking on every sync_to_db()
- This prevents 12,000+ redundant "SELECT created_at FROM tracks LIMIT 1" queries
  on typical discover operations with 12,000 tracks
"""

import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from time import sleep

from spotfm import sqlite, utils
from spotfm.spotify.album import Album
from spotfm.spotify.artist import Artist
from spotfm.spotify.constants import MARKET
from spotfm.utils import cache_object, retrieve_object_from_cache

# Per-database cache for lifecycle columns existence check to handle database switching at runtime.
# Tests that monkeypatch utils.DATABASE should call reset_lifecycle_columns_cache() to avoid stale entries.
_lifecycle_columns_cache = {}


def reset_lifecycle_columns_cache():
    """Clear the lifecycle-columns cache for all databases.

    Tests that monkeypatch utils.DATABASE should call this to avoid stale cache entries.
    """
    _lifecycle_columns_cache.clear()


def _get_lifecycle_columns_flag():
    """Return the cached lifecycle-columns flag for the current database, or None if unknown."""
    db_key = str(sqlite.DATABASE)
    return _lifecycle_columns_cache.get(db_key)


def _set_lifecycle_columns_flag(value):
    """Set the cached lifecycle-columns flag for the current database."""
    db_key = str(sqlite.DATABASE)
    _lifecycle_columns_cache[db_key] = value


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
    def get_tracks(cls, tracks_id, client=None, refresh=False, rate_limit=True):
        """
        Fetch multiple tracks efficiently, leveraging cache/DB with ThreadPoolExecutor parallelization.

        Strategy:
        1. Check cache/DB for all tracks first (respects 3-tier cache)
        2. Parallelize fetching missing tracks from API (ThreadPoolExecutor with 5 workers)
        3. Collect album/artist IDs from missing tracks
        4. Batch fetch only missing albums and artists (respecting rate_limit parameter)
        5. Return all tracks (cached + newly fetched)

        Args:
            tracks_id: List of track IDs to fetch (URLs, URIs, or plain IDs)
            client: Spotify client (optional)
            refresh: Force refresh from API instead of using cache/DB
            rate_limit: Enable rate limiting for API calls (default: True)
        """
        if not tracks_id:
            return []

        # Normalize all track IDs upfront (handles URLs/URIs)
        normalized_ids = [utils.parse_url(tid) for tid in tracks_id]

        cached_tracks = {}  # Map of normalized_track_id → Track
        normalized_to_fetch = []  # Normalized IDs that need API fetch

        # Phase 1: Check cache/DB for all tracks (CRITICAL for performance)
        # Track unique IDs to avoid fetching duplicates (though input may have repeats)
        seen_missing = set()
        for normalized_id in normalized_ids:
            # Try pickle cache first
            track = retrieve_object_from_cache(cls.kind, normalized_id)
            if track is not None and not refresh:
                cached_tracks[normalized_id] = track
                continue

            # Try DB
            track = Track(normalized_id, client)
            if not refresh and track.update_from_db(client):
                cache_object(track)
                cached_tracks[normalized_id] = track
                continue

            # Track not in cache/DB, need to fetch from API
            # Only add to fetch list once, even if ID appears multiple times in input
            if normalized_id not in seen_missing:
                normalized_to_fetch.append(normalized_id)
                seen_missing.add(normalized_id)

        # If all tracks cached, return early (typical case for update_playlists)
        if not normalized_to_fetch:
            logging.info(f"All {len(cached_tracks)} tracks retrieved from cache/DB")
            return [cached_tracks[nid] for nid in normalized_ids]

        # If client is missing and we have unfetched tracks, we can't proceed
        if client is None:
            logging.warning(
                f"Retrieved {len(cached_tracks)} tracks from cache/DB but {len(normalized_to_fetch)} "
                f"are missing and no client was provided. Returning partial results."
            )
            return [cached_tracks[nid] for nid in normalized_ids if nid in cached_tracks]

        logging.info(
            f"Retrieved {len(cached_tracks)} tracks from cache/DB, fetching {len(normalized_to_fetch)} from API"
        )

        # Phase 2: Fetch missing tracks in parallel with rate limiting
        # Uses ThreadPoolExecutor to parallelize individual API calls while enforcing rate limits.
        # Rate limiting is enforced by throttling task submission rate to maintain same ~10 req/s
        # as sequential baseline. Parallel execution hides network latency while respecting API limits.
        #
        # NOTE: Thread safety - spotipy's requests.Session is assumed thread-safe for concurrent
        # read-only operations. If threading issues occur, fall back to sequential fetch by setting
        # MAX_WORKERS = 1 below.
        MAX_WORKERS = 5  # Up to 5 concurrent in-flight requests (parallelism degree)
        SUBMIT_DELAY = 0.1  # 0.1s between submissions → ~10 req/s max request-start rate (same as sequential baseline)

        def fetch_track(normalized_id):
            """Fetch single track's raw data from API (normalized_id already parsed)."""
            try:
                return client.track(normalized_id, market=MARKET)
            except (KeyError, ValueError) as e:
                # Track not found, deleted, or unavailable on Spotify
                logging.debug(f"Track {normalized_id} not found or unavailable: {e}")
                return None
            # Let unexpected exceptions propagate so result collection can handle them properly

        # Parallel fetch phase: submit tasks with rate limiting
        # Maintain order using a future→(index, track_id) map.
        # Results are collected via as_completed() to avoid head-of-line blocking,
        # then written back into a pre-allocated list by index to preserve input order.
        future_map = {}  # future → (i, normalized_id)
        results = [None] * len(normalized_to_fetch)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            for i, normalized_id in enumerate(normalized_to_fetch):
                future = executor.submit(fetch_track, normalized_id)
                future_map[future] = (i, normalized_id)
                # Rate limiting: sleep between submissions (only if rate_limit=True)
                if rate_limit and i < len(normalized_to_fetch) - 1:
                    sleep(SUBMIT_DELAY)

            # Collect results as futures complete (avoids blocking on slow early requests)
            # as_completed() must be called inside the executor context for incremental processing
            for future in as_completed(future_map):
                i, track_id = future_map[future]
                try:
                    raw_track = future.result()
                    if raw_track is not None:
                        results[i] = raw_track
                except KeyError, ValueError:
                    # Track not found - already logged by fetch_track at debug level
                    pass
                except Exception as e:
                    # Unexpected API/HTTP error - log and skip this track
                    logging.warning(f"Unexpected error fetching track {track_id}: {e}")

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

        # Batch fetch albums and artists (respecting caller's rate limiting preference)
        # When rate_limit=True (default): Apply 0.05s sleep between API calls (~20 req/s)
        # When rate_limit=False: Skip sleeps (useful for testing or when caller manages rate limiting)
        # Note: Parallel track phase ends and would spike request rate without rate limiting.
        # Skip hydrating artists in album fetch - we fetch them separately below with rate limiting
        albums_dict = {}
        if album_ids:
            logging.info("Batch fetching albums (checking cache first)")
            unique_album_ids = list(dict.fromkeys(album_ids))
            albums = Album.get_albums(
                unique_album_ids,
                client,
                refresh=refresh,
                rate_limit=rate_limit,
                hydrate_artists=False,
            )
            albums_dict = {album.id: album for album in albums if album is not None}

        artists_dict = {}
        if artist_ids:
            logging.info("Batch fetching artists (checking cache first)")
            unique_artist_ids = list(dict.fromkeys(artist_ids))
            artists = Artist.get_artists(unique_artist_ids, client, refresh=refresh, rate_limit=rate_limit)
            artists_dict = {artist.id: artist for artist in artists if artist is not None}

        # Populate album.artists
        for album in albums_dict.values():
            if album.artists_id:
                album.artists = [artists_dict[aid] for aid in album.artists_id if aid in artists_dict]

        # Create track objects from fetched data
        fetched_tracks = {}  # Map of track_id → Track
        for raw_track in raw_tracks:
            try:
                track = Track(raw_track["id"], client)
                track.name = utils.sanitize_string(raw_track["name"])
                track.album_id = raw_track["album"]["id"]
                track.updated = str(date.today())

                # Use pre-fetched album (mirrors artist completeness check below)
                album = albums_dict.get(track.album_id)
                if album is None:
                    logging.warning(
                        "Skipping sync for track %s due to missing album %s",
                        track.id,
                        track.album_id,
                    )
                    continue
                track.album = album.name
                track.release_date = album.release_date

                # Use pre-fetched artists
                track.artists_id = [artist["id"] for artist in raw_track["artists"]]
                track.artists = [artists_dict[aid] for aid in track.artists_id if aid in artists_dict]

                # Ensure all artists were hydrated (incomplete artists → incomplete genres)
                if len(track.artists) != len(track.artists_id):
                    missing = [aid for aid in track.artists_id if aid not in artists_dict]
                    logging.warning(
                        "Skipping sync for track %s due to missing artists: %s",
                        track.id,
                        ", ".join(missing),
                    )
                    continue

                track.sync_to_db(client)
                cache_object(track)
                fetched_tracks[track.id] = track

            except (TypeError, KeyError) as e:
                track_id = raw_track.get("id", "unknown") if raw_track else "unknown"
                logging.warning(f"Error processing track {track_id}: {e}", exc_info=True)

        # Rebuild tracks list in original input order (combining cached + fetched)
        # Use normalized IDs for lookups, iterate in normalized_ids order to preserve input order
        tracks = []
        for normalized_id in normalized_ids:
            if normalized_id in cached_tracks:
                tracks.append(cached_tracks[normalized_id])
            elif normalized_id in fetched_tracks:
                tracks.append(fetched_tracks[normalized_id])
            # Skip if track not found (deleted/unavailable)

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

        # Check if lifecycle columns exist (cached per-database after first check)
        has_lifecycle = _get_lifecycle_columns_flag()
        if has_lifecycle is None:
            try:
                sqlite.select_db(sqlite.DATABASE, "SELECT created_at FROM tracks LIMIT 1")
                has_lifecycle = True
            except sqlite3.OperationalError as e:
                if "no such column" in str(e).lower() or "no such table" in str(e).lower():
                    has_lifecycle = False
                else:
                    raise
            _set_lifecycle_columns_flag(has_lifecycle)

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
