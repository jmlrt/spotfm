"""Tests for Liked Songs (saved tracks) support.

Covers:
- Schema migration (liked/liked_at columns)
- update_liked_tracks sync engine (fast path, additions, removals, fallback)
- Track.sync_to_db preserving liked state across re-syncs
- find_tracks_by_criteria liked filter and no-playlist mode
- find_liked_only_tracks
- count_tracks union semantics and count_liked_tracks
"""

import sqlite3
from unittest.mock import MagicMock

import pytest

from spotfm import sqlite, utils
from spotfm.spotify import misc
from spotfm.spotify.track import Track


def _setup_db(monkeypatch, temp_database):
    """Point the app at the temp database and run the schema migration."""
    monkeypatch.setattr(utils, "DATABASE", temp_database)
    monkeypatch.setattr(sqlite, "DATABASE", temp_database)
    sqlite.migrate_database_schema(temp_database)


def _insert_track(db, tid, name="Track", liked=0, liked_at=None):
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT OR REPLACE INTO tracks (id, name, updated_at, liked, liked_at) VALUES (?, ?, ?, ?, ?)",
        (tid, name, "2026-01-01", liked, liked_at),
    )
    conn.commit()
    conn.close()


def _get_track_row(db, tid):
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT id, liked, liked_at FROM tracks WHERE id = ?", (tid,)).fetchone()
    conn.close()
    return row


def _liked_ids(db):
    conn = sqlite3.connect(str(db))
    rows = conn.execute("SELECT id FROM tracks WHERE liked = 1 ORDER BY id").fetchall()
    conn.close()
    return [r[0] for r in rows]


def _saved_item(track_id, added_at, linked_from=None):
    """Build a /me/tracks item; track_id None simulates an unavailable item."""
    if track_id is None:
        return {"added_at": added_at, "track": None}
    track = {"id": track_id}
    if linked_from:
        track["linked_from"] = {"id": linked_from}
    return {"added_at": added_at, "track": track}


def make_saved_client(pages, total=None, contains_flags=None):
    """Build a fake spotipy client serving /me/tracks pages and contains checks.

    Args:
        pages: list of pages, each a list of items (see _saved_item)
        total: reported total (defaults to the number of items across pages)
        contains_flags: dict of track_id -> bool for contains checks (default True)
    """
    if contains_flags is None:
        contains_flags = {}
    all_items = [item for page in pages for item in page]
    total = len(all_items) if total is None else total
    calls = {"saved_tracks": 0, "next": 0, "contains": []}
    client = MagicMock()

    def saved_tracks(limit=50, offset=0, market=None):
        calls["saved_tracks"] += 1
        return {"items": pages[0], "total": total, "next": True if len(pages) > 1 else None}

    def nxt(results):
        calls["next"] += 1
        idx = calls["next"]
        if idx >= len(pages):
            raise AssertionError("paged past the last page")
        return {"items": pages[idx], "total": total, "next": True if idx + 1 < len(pages) else None}

    def contains(ids):
        calls["contains"].append(list(ids))
        return [contains_flags.get(track_id, True) for track_id in ids]

    client.current_user_saved_tracks.side_effect = saved_tracks
    client.next.side_effect = nxt
    client.current_user_saved_tracks_contains.side_effect = contains
    client.calls = calls
    return client


@pytest.mark.unit
class TestLikedMigration:
    def test_liked_columns_added_by_migration(self, temp_database):
        """Migration adds liked/liked_at to a pre-liked schema database."""
        conn = sqlite3.connect(str(temp_database))
        columns = [row[1] for row in conn.execute("PRAGMA table_info(tracks)").fetchall()]
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()]
        conn.close()
        assert "liked" not in columns  # conftest schema predates liked support
        assert "liked_sync_state" not in tables

        sqlite.migrate_database_schema(temp_database)

        conn = sqlite3.connect(str(temp_database))
        columns = [row[1] for row in conn.execute("PRAGMA table_info(tracks)").fetchall()]
        existing_defaults = conn.execute("SELECT COUNT(*) FROM tracks WHERE liked = 0").fetchone()[0]
        conn.close()

        assert "liked" in columns
        assert "liked_at" in columns
        assert existing_defaults >= 0  # query runs: existing rows default to liked = 0

        conn = sqlite3.connect(str(temp_database))
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()]
        conn.close()
        assert "liked_sync_state" in tables

    def test_migration_is_idempotent(self, temp_database):
        sqlite.migrate_database_schema(temp_database)
        sqlite.migrate_database_schema(temp_database)  # must not raise
        assert "liked" in [row[1] for row in sqlite3.connect(str(temp_database)).execute("PRAGMA table_info(tracks)")]


@pytest.mark.unit
class TestUpdateLikedTracks:
    def test_first_sync_marks_all_liked(self, temp_database, monkeypatch):
        """Empty database: full walk marks every saved track as liked."""
        _setup_db(monkeypatch, temp_database)
        _insert_track(temp_database, "t1")
        _insert_track(temp_database, "t2")
        _insert_track(temp_database, "t3")

        client = make_saved_client(
            pages=[
                [_saved_item("t3", "2026-01-03T00:00:00Z")],
                [_saved_item("t2", "2026-01-02T00:00:00Z"), _saved_item("t1", "2026-01-01T00:00:00Z")],
            ]
        )

        result = misc.update_liked_tracks(client)

        assert result["added"] == 3
        assert result["removed"] == 0
        assert result["unchanged"] is False
        assert _liked_ids(temp_database) == ["t1", "t2", "t3"]
        assert _get_track_row(temp_database, "t3")[1:] == (1, "2026-01-03T00:00:00Z")
        # First sync walked 2 pages
        assert client.calls["saved_tracks"] == 1
        assert client.calls["next"] == 1
        # All newly marked ids were verified (contains check after full sync)
        assert client.calls["contains"] == [["t1", "t2", "t3"]]

    def test_fast_path_unchanged_library(self, temp_database, monkeypatch):
        """No changes: single API call, no contains check, no DB changes."""
        _setup_db(monkeypatch, temp_database)
        _insert_track(temp_database, "t1", liked=1, liked_at="2026-01-01T00:00:00Z")
        _insert_track(temp_database, "t2", liked=1, liked_at="2025-12-01T00:00:00Z")

        # /me/tracks returns items most-recent-first
        client = make_saved_client(
            pages=[[_saved_item("t1", "2026-01-01T00:00:00Z"), _saved_item("t2", "2025-12-01T00:00:00Z")]],
            total=2,
        )

        result = misc.update_liked_tracks(client)

        assert result == {"added": 0, "removed": 0, "total": 2, "unchanged": True}
        assert client.calls["saved_tracks"] == 1  # exactly one request
        assert client.calls["next"] == 0
        assert client.calls["contains"] == []

    def test_fast_path_with_unavailable_items(self, temp_database, monkeypatch):
        """Libraries with unavailable items sync in 1 request once the state is stored.

        Unavailable items (track null) count in the API total and can be the
        newest item, but never get a tracks row: the liked count stays below
        the total forever. The fast path must compare against the state
        (total + top added_at) observed at the previous sync instead.
        """
        _setup_db(monkeypatch, temp_database)
        _insert_track(temp_database, "t1")

        pages = [
            [
                _saved_item(None, "2026-02-01T00:00:00Z"),  # unavailable, newest
                _saved_item("t1", "2026-01-01T00:00:00Z"),
            ]
        ]

        first = misc.update_liked_tracks(make_saved_client(pages, total=2))
        assert first["unchanged"] is False
        assert first["added"] == 1
        assert _liked_ids(temp_database) == ["t1"]

        # Second identical sync: stored state matches — 1 request, no contains sweep
        client = make_saved_client(pages, total=2)
        result = misc.update_liked_tracks(client)
        assert result == {"added": 0, "removed": 0, "total": 2, "unchanged": True}
        assert client.calls["saved_tracks"] == 1
        assert client.calls["next"] == 0
        assert client.calls["contains"] == []

    def test_additions_collected_and_marked(self, temp_database, monkeypatch):
        """New likes are collected by added_at threshold and marked liked."""
        _setup_db(monkeypatch, temp_database)
        _insert_track(temp_database, "t1", liked=1, liked_at="2026-01-01T00:00:00Z")
        _insert_track(temp_database, "t2")
        _insert_track(temp_database, "t3")

        # Newest first; t3 is newer than the stored liked_at threshold
        client = make_saved_client(
            pages=[
                [
                    _saved_item("t3", "2026-03-01T00:00:00Z"),
                    _saved_item("t1", "2026-01-01T00:00:00Z"),  # threshold reached: stop walk
                ]
            ],
            total=3,
        )

        result = misc.update_liked_tracks(client)

        assert result["added"] == 1
        assert result["unchanged"] is False
        assert _get_track_row(temp_database, "t3")[1] == 1
        assert _get_track_row(temp_database, "t3")[2] == "2026-03-01T00:00:00Z"
        # Walk stopped at the threshold item: no extra page fetched
        assert client.calls["next"] == 0

    def test_missing_track_metadata_fetched(self, temp_database, monkeypatch):
        """Liked tracks without a tracks row have their metadata fetched via Track.get_tracks."""
        _setup_db(monkeypatch, temp_database)

        fetched = {}

        def fake_get_tracks(ids, client=None, **kwargs):
            fetched["ids"] = list(ids)
            for tid in ids:
                _insert_track(temp_database, tid)
            return []

        monkeypatch.setattr(misc.Track, "get_tracks", staticmethod(fake_get_tracks))

        client = make_saved_client(pages=[[_saved_item("t_new", "2026-02-01T00:00:00Z")]])
        misc.update_liked_tracks(client)

        assert fetched["ids"] == ["t_new"]
        assert _get_track_row(temp_database, "t_new")[1] == 1

    def test_removal_detected_via_contains(self, temp_database, monkeypatch):
        """Unliked tracks are detected by the contains check; the tracks row is kept."""
        _setup_db(monkeypatch, temp_database)
        _insert_track(temp_database, "t1", liked=1, liked_at="2026-01-01T00:00:00Z")
        _insert_track(temp_database, "t2", liked=1, liked_at="2026-01-02T00:00:00Z")

        # t2 was unliked: total drops to 1, top item is older than the threshold
        client = make_saved_client(
            pages=[[_saved_item("t1", "2026-01-01T00:00:00Z")]],
            total=1,
            contains_flags={"t2": False},
        )

        result = misc.update_liked_tracks(client)

        assert result["removed"] == 1
        assert result["added"] == 0
        # t2 row kept as negative cache with liked cleared; liked_at preserved for history
        assert _get_track_row(temp_database, "t2") == ("t2", 0, "2026-01-02T00:00:00Z")
        assert _liked_ids(temp_database) == ["t1"]

    def test_relinked_track_uses_original_id(self, temp_database, monkeypatch):
        """linked_from (market relinking) resolves to the original track ID."""
        _setup_db(monkeypatch, temp_database)
        _insert_track(temp_database, "original_id")

        client = make_saved_client(
            pages=[[_saved_item("relinked_id", "2026-02-01T00:00:00Z", linked_from="original_id")]]
        )

        misc.update_liked_tracks(client)

        assert _get_track_row(temp_database, "original_id")[1] == 1
        assert _get_track_row(temp_database, "relinked_id") is None  # replacement ID never stored

    def test_relinked_addition_hydrates_original_id(self, temp_database, monkeypatch):
        """A relinked like whose original ID has no row is hydrated under that original ID.

        Track.get_tracks() fetches under the original ID but persists the row
        under the market replacement ID (the API response id), leaving the
        original ID without a row and the liked UPDATE a silent no-op. The
        relinked addition is hydrated from the raw saved item instead.
        """
        _setup_db(monkeypatch, temp_database)

        def fake_update_from_track(self, raw_track, client):
            self.name = "Relinked Track"
            self.album_id = "album1"
            self.updated = "2026-01-01"
            self.artists = []

        monkeypatch.setattr(Track, "update_from_track", fake_update_from_track)

        client = make_saved_client(
            pages=[[_saved_item("relinked_id", "2026-02-01T00:00:00Z", linked_from="original_id")]]
        )

        misc.update_liked_tracks(client)

        assert _get_track_row(temp_database, "original_id")[1] == 1
        assert _get_track_row(temp_database, "relinked_id") is None  # replacement ID never stored

    def test_cached_track_without_row_is_persisted(self, temp_database, monkeypatch):
        """Pickle-cache hits from get_tracks are persisted before the liked UPDATE.

        get_tracks returns cached tracks without writing them to the database
        even with sync_to_db=True (e.g. cached by an earlier sync_to_db=False
        discover fetch); the liked UPDATE would silently mark nothing.
        """
        _setup_db(monkeypatch, temp_database)

        cached_track = Track("t_cached")
        cached_track.name = "Cached Track"
        cached_track.album_id = "album1"
        cached_track.updated = "2026-01-01"
        cached_track.artists = []
        monkeypatch.setattr(misc.Track, "get_tracks", staticmethod(lambda ids, client=None, **kwargs: [cached_track]))

        client = make_saved_client(pages=[[_saved_item("t_cached", "2026-02-01T00:00:00Z")]])

        misc.update_liked_tracks(client)

        assert _get_track_row(temp_database, "t_cached")[1] == 1
        assert _get_track_row(temp_database, "t_cached")[2] == "2026-02-01T00:00:00Z"

    def test_relinked_hydration_failure_is_skipped(self, temp_database, monkeypatch):
        """A relinked addition whose hydration fails is skipped without failing the sync."""
        _setup_db(monkeypatch, temp_database)

        def fake_update_from_track(self, raw_track, client):
            raise KeyError("album")

        monkeypatch.setattr(Track, "update_from_track", fake_update_from_track)

        client = make_saved_client(
            pages=[[_saved_item("relinked_id", "2026-02-01T00:00:00Z", linked_from="original_id")]]
        )

        result = misc.update_liked_tracks(client)

        # The liked UPDATE still ran (a no-op without a row); the sync survived
        assert result["added"] == 1
        assert _get_track_row(temp_database, "original_id") is None

    def test_relinked_hydration_api_error_is_skipped(self, temp_database, monkeypatch):
        """A 429/HTTP error during relinked hydration skips that track, not the sync."""
        from spotipy.exceptions import SpotifyException

        _setup_db(monkeypatch, temp_database)

        def fake_update_from_track(self, raw_track, client):
            raise SpotifyException(429, -1, "rate limited")

        monkeypatch.setattr(Track, "update_from_track", fake_update_from_track)

        client = make_saved_client(
            pages=[[_saved_item("relinked_id", "2026-02-01T00:00:00Z", linked_from="original_id")]]
        )

        result = misc.update_liked_tracks(client)

        assert result["added"] == 1  # the liked UPDATE still ran
        assert _get_track_row(temp_database, "original_id") is None

    def test_collect_saved_tracks_fetches_first_page_and_deduplicates(self):
        """Without a first page the walk fetches it; duplicate ids are collected once."""
        item = _saved_item("t1", "2026-01-01T00:00:00Z")
        client = make_saved_client(pages=[[item, _saved_item("t1", "2026-01-01T00:00:00Z")]])

        saved, ordered = misc._collect_saved_tracks(client)  # first_page=None: fetch from the client

        assert saved == {"t1": item}
        assert ordered is True

    def test_unavailable_items_skipped(self, temp_database, monkeypatch):
        """Items with a null track (unavailable) are ignored."""
        _setup_db(monkeypatch, temp_database)

        _insert_track(temp_database, "t1")

        client = make_saved_client(
            pages=[
                [
                    _saved_item(None, "2026-02-01T00:00:00Z"),  # unavailable
                    _saved_item("t1", "2026-01-01T00:00:00Z"),
                ]
            ],
            total=2,
        )

        result = misc.update_liked_tracks(client)

        assert result["added"] == 1
        assert _liked_ids(temp_database) == ["t1"]

    def test_ordering_violation_triggers_full_walk(self, temp_database, monkeypatch):
        """Non-monotonic added_at ordering falls back to a full walk."""
        _setup_db(monkeypatch, temp_database)
        _insert_track(temp_database, "t_old", liked=1, liked_at="2026-01-01T00:00:00Z")
        _insert_track(temp_database, "t_new1")
        _insert_track(temp_database, "t_new2")

        # added_at increases mid-page (violation), then an old item that would
        # normally end the threshold walk
        client = make_saved_client(
            pages=[
                [
                    _saved_item("t_new1", "2026-03-01T00:00:00Z"),
                    _saved_item("t_new2", "2026-04-01T00:00:00Z"),  # newer than the item above
                    _saved_item("t_old", "2025-06-01T00:00:00Z"),  # threshold cutoff item
                ]
            ],
            total=3,
        )

        misc.update_liked_tracks(client)

        # The violation was detected before the cutoff could stop the walk:
        # the cutoff is disabled and the same walk completes as a full walk
        assert client.calls["saved_tracks"] == 1
        assert _liked_ids(temp_database) == ["t_new1", "t_new2", "t_old"]

    def test_ordering_violation_after_cutoff_item_detected(self, temp_database, monkeypatch):
        """A violation hiding after the cutoff item is still detected (full walk).

        The whole page is validated for added_at ordering before the threshold
        cutoff is applied; stopping at the first older item would miss the
        out-of-order addition behind it.
        """
        _setup_db(monkeypatch, temp_database)
        _insert_track(temp_database, "t_old", liked=1, liked_at="2026-01-01T00:00:00Z")
        _insert_track(temp_database, "t_hidden")

        # The cutoff item comes first; the violation (a newer addition) follows it
        client = make_saved_client(
            pages=[
                [
                    _saved_item("t_old", "2025-06-01T00:00:00Z"),  # threshold cutoff item
                    _saved_item("t_hidden", "2026-04-01T00:00:00Z"),  # newer than the item above
                ]
            ],
            total=2,
        )

        misc.update_liked_tracks(client)

        # The cutoff never fired (the page's ordering was invalid), so the
        # hidden addition was collected despite sitting behind the cutoff item
        assert client.calls["saved_tracks"] == 1
        assert _liked_ids(temp_database) == ["t_hidden", "t_old"]

    def test_disordered_first_page_disables_fast_path(self, temp_database, monkeypatch):
        """A disordered first page makes both fast-path signals untrustworthy."""
        _setup_db(monkeypatch, temp_database)
        _insert_track(temp_database, "t1", liked=1, liked_at="2026-01-01T00:00:00Z")
        _insert_track(temp_database, "t2")
        _insert_track(temp_database, "t_new")

        # total matches the stored count and the top item is not newer — but the
        # page ordering is violated, so the sync must not take the fast path
        client = make_saved_client(
            pages=[
                [
                    _saved_item("t2", "2025-12-01T00:00:00Z"),
                    _saved_item("t_new", "2026-03-01T00:00:00Z"),  # newer than the item above
                ]
            ],
            total=2,
        )

        result = misc.update_liked_tracks(client)

        assert result["unchanged"] is False
        # The cutoff never fired (invalid ordering): both items were collected
        assert result["added"] == 2
        assert _get_track_row(temp_database, "t_new")[1] == 1


@pytest.mark.unit
class TestTrackLikedPreservation:
    def _insert_full_track(self, db, tid, liked, liked_at=None):
        """Insert a track with the album/artist rows update_from_db() needs."""
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO tracks (id, name, updated_at, liked, liked_at) VALUES (?, ?, ?, ?, ?)",
            (tid, f"Track {tid}", "2026-01-01", liked, liked_at),
        )
        conn.execute(
            "INSERT INTO albums (id, name, release_date, updated_at) VALUES (?, ?, ?, ?)",
            ("a1", "Album", "2026-01-01", "2026-01-01"),
        )
        conn.execute("INSERT INTO albums_tracks VALUES ('a1', ?)", (tid,))
        conn.execute("INSERT INTO artists (id, name, updated_at) VALUES ('ar1', 'Artist', '2026-01-01')")
        conn.execute("INSERT INTO tracks_artists VALUES (?, 'ar1')", (tid,))
        conn.commit()
        conn.close()

    def test_sync_to_db_preserves_liked_state(self, temp_database, temp_cache_dir, monkeypatch):
        """A playlist re-sync must not reset the liked flag of an existing track."""
        _setup_db(monkeypatch, temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)
        self._insert_full_track(temp_database, "t1", liked=1, liked_at="2026-01-01T00:00:00Z")

        track = Track("t1")
        assert track.update_from_db() is True
        assert track.liked == 1
        assert track.liked_at == "2026-01-01T00:00:00Z"

        # Re-sync (as update_playlists does): liked state must survive
        track.sync_to_db(None)

        assert _get_track_row(temp_database, "t1")[1] == 1
        assert _get_track_row(temp_database, "t1")[2] == "2026-01-01T00:00:00Z"

    def test_new_track_defaults_to_not_liked(self, temp_database, temp_cache_dir, monkeypatch):
        _setup_db(monkeypatch, temp_database)
        monkeypatch.setattr(utils, "CACHE_DIR", temp_cache_dir)
        self._insert_full_track(temp_database, "t1", liked=0)

        track = Track("t1")
        assert track.update_from_db() is True
        assert track.liked == 0


@pytest.mark.unit
class TestFindTracksLikedFilters:
    @pytest.fixture(autouse=True)
    def setup_library(self, temp_database, monkeypatch):
        """Library layout:
        - t1: in playlist, not liked
        - t2: in playlist, liked
        - t3: no playlist, liked
        - t4: no playlist, not liked (negative-cache orphan)
        """
        _setup_db(monkeypatch, temp_database)
        self.db = temp_database
        conn = sqlite3.connect(str(temp_database))
        conn.execute("INSERT INTO playlists (id, name, owner, updated_at) VALUES ('p1', 'PL1', 'user1', '2026-01-01')")
        for tid, liked in [("t1", 0), ("t2", 1), ("t3", 1), ("t4", 0)]:
            conn.execute(
                "INSERT INTO tracks (id, name, updated_at, liked, liked_at) VALUES (?, ?, ?, ?, ?)",
                (tid, f"Track {tid}", "2026-01-01", liked, "2026-01-01T00:00:00Z" if liked else None),
            )
        conn.execute("INSERT INTO playlists_tracks VALUES ('p1', 't1', '2026-01-01')")
        conn.execute("INSERT INTO playlists_tracks VALUES ('p1', 't2', '2026-01-01')")
        conn.commit()
        conn.close()

    def test_no_playlist_filter_returns_playlist_or_liked(self):
        """Default view mirrors count-tracks union: pure orphans (t4) excluded."""
        results = misc.find_tracks_by_criteria(playlist_patterns=None)
        assert sorted(r["track_id"] for r in results) == ["t1", "t2", "t3"]

    def test_none_pattern_returns_zero_playlist_tracks(self):
        results = misc.find_tracks_by_criteria(playlist_patterns=misc.NO_PLAYLIST_PATTERN)
        assert sorted(r["track_id"] for r in results) == ["t3", "t4"]

    def test_liked_only_filter(self):
        results = misc.find_tracks_by_criteria(playlist_patterns=None, liked=True)
        assert sorted(r["track_id"] for r in results) == ["t2", "t3"]

    def test_not_liked_filter(self):
        """Not-liked view is intersected with the union: pure orphans stay hidden."""
        results = misc.find_tracks_by_criteria(playlist_patterns=None, liked=False)
        assert sorted(r["track_id"] for r in results) == ["t1"]

    def test_no_playlist_and_not_liked_shows_negative_cache(self):
        """The explicit No-playlist filter remains the window into negative cache."""
        results = misc.find_tracks_by_criteria(playlist_patterns=misc.NO_PLAYLIST_PATTERN, liked=False)
        assert [r["track_id"] for r in results] == ["t4"]

    def test_playlist_filter_still_scopes_to_playlist(self):
        results = misc.find_tracks_by_criteria(playlist_patterns=["p1"])
        assert sorted(r["track_id"] for r in results) == ["t1", "t2"]

    def test_playlist_and_liked_filter_combined(self):
        results = misc.find_tracks_by_criteria(playlist_patterns=["p1"], liked=True)
        assert [r["track_id"] for r in results] == ["t2"]

    def test_find_liked_only_tracks(self):
        """The original use case: liked but in no playlist."""
        results = misc.find_liked_only_tracks()
        assert [r["track_id"] for r in results] == ["t3"]
        assert results[0]["liked"] is True

    def test_unmatched_patterns_return_empty(self):
        assert misc.find_tracks_by_criteria(playlist_patterns=["NoSuch%"]) == []


@pytest.mark.unit
class TestCounts:
    @pytest.fixture(autouse=True)
    def setup_library(self, temp_database, monkeypatch):
        """t1 in playlist, t2 liked-only, t3 pure orphan (neither)."""
        _setup_db(monkeypatch, temp_database)
        conn = sqlite3.connect(str(temp_database))
        conn.execute("INSERT INTO playlists (id, name, owner, updated_at) VALUES ('p1', 'PL1', 'user1', '2026-01-01')")
        for tid, liked in [("t1", 0), ("t2", 1), ("t3", 0)]:
            conn.execute(
                "INSERT INTO tracks (id, name, updated_at, liked, liked_at) VALUES (?, ?, ?, ?, ?)",
                (tid, f"Track {tid}", "2026-01-01", liked, "2026-01-01T00:00:00Z" if liked else None),
            )
        conn.execute("INSERT INTO playlists_tracks VALUES ('p1', 't1', '2026-01-01')")
        conn.commit()
        conn.close()

    def test_count_tracks_is_union_of_playlist_and_liked(self):
        # t3 (no playlist, not liked) must not be counted
        assert misc.count_tracks() == 2

    def test_count_liked_tracks(self):
        assert misc.count_liked_tracks() == 1

    def test_count_tracks_with_patterns_unchanged(self):
        assert misc.count_tracks(["p1"]) == 1


@pytest.mark.unit
class TestClientWiring:
    def test_update_playlists_is_playlists_only(self, monkeypatch):
        """cli.update_playlists forwards only playlist arguments — no liked coupling."""
        from spotfm.cli import update_playlists

        client = MagicMock()
        update_playlists(client, ["ex1"], None)
        client.update_playlists.assert_called_once_with(["ex1"], None)


@pytest.mark.unit
class TestLikedSyncEdgeCases:
    def test_contains_check_batches_large_libraries(self, temp_database, monkeypatch):
        """More than LIKED_CONTAINS_CHUNK ids: contains is called per 40-uri chunk (API limit)."""
        _setup_db(monkeypatch, temp_database)

        # 501 liked tracks already in the database, all still liked
        conn = sqlite3.connect(str(temp_database))
        for i in range(501):
            conn.execute(
                "INSERT INTO tracks (id, name, updated_at, liked, liked_at) VALUES (?, ?, ?, ?, ?)",
                (f"t{i:04}", f"Track {i}", "2026-01-01", 1, "2026-01-01T00:00:00Z"),
            )
        conn.commit()
        conn.close()

        # Library unchanged: fast path hits, no contains check at all
        first_item = _saved_item("t0500", "2026-01-01T00:00:00Z")
        client = make_saved_client(pages=[[first_item]], total=501)
        result = misc.update_liked_tracks(client)
        assert result["unchanged"] is True
        assert client.calls["contains"] == []

        # Library changed (total dropped by 1): contains runs over all liked ids in chunks
        client = make_saved_client(pages=[[first_item]], total=500)
        result = misc.update_liked_tracks(client)
        assert result["unchanged"] is False
        assert [len(chunk) for chunk in client.calls["contains"]] == [40] * 12 + [21]

    def test_update_playlists_does_not_touch_saved_tracks(self, temp_database, monkeypatch):
        """update-playlists is playlists-only: the saved-tracks API is never called."""
        from spotfm.spotify.client import Client

        _setup_db(monkeypatch, temp_database)

        client = object.__new__(Client)  # bypass spotipy OAuth in __init__
        client.client = MagicMock()
        monkeypatch.setattr(Client, "get_playlists_id", lambda self, excluded_playlists=None: [])

        client.update_playlists(excluded_playlists=[], playlists_patterns=None)

        client.client.current_user_saved_tracks.assert_not_called()
