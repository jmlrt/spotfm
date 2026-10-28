import sqlite3

import pytest


def _insert_playlist(db_path, pid, name, owner="owner"):
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO playlists (id, name, owner, updated_at) VALUES (?, ?, ?, ?)",
        (pid, name, owner, "2024-01-01"),
    )
    conn.commit()
    conn.close()


def _insert_track(db_path, tid, name):
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO tracks (id, name, updated_at) VALUES (?, ?, ?)",
        (tid, name, "2024-01-01"),
    )
    conn.commit()
    conn.close()


@pytest.mark.unit
def test_playlists_page_renders(authed_client, temp_database):
    _insert_playlist(temp_database, "pl1", "My Playlist")
    resp = authed_client.get("/playlists")
    assert resp.status_code == 200
    assert "My Playlist" in resp.text


@pytest.mark.unit
def test_playlists_empty(authed_client):
    resp = authed_client.get("/playlists")
    assert resp.status_code == 200
    assert "No playlists found" in resp.text


@pytest.mark.unit
def test_tracks_page_no_filters(authed_client):
    resp = authed_client.get("/tracks")
    assert resp.status_code == 200
    assert "Filter" in resp.text


@pytest.mark.unit
def test_tracks_page_with_playlist_filter(authed_client, temp_database, monkeypatch):
    import spotfm.spotify.misc as misc_module

    monkeypatch.setattr(misc_module, "find_tracks_by_criteria", lambda **kwargs: [])
    resp = authed_client.get("/tracks?playlist=pl1")
    assert resp.status_code == 200


@pytest.mark.unit
def test_duplicates_page_renders(authed_client):
    resp = authed_client.get("/duplicates")
    assert resp.status_code == 200
    assert "Exact duplicates" in resp.text


@pytest.mark.unit
def test_duplicates_ids_empty_db(authed_client, monkeypatch):
    import spotfm.spotify.dupes as dupes_module

    monkeypatch.setattr(dupes_module, "find_duplicate_ids", lambda **kwargs: [])
    resp = authed_client.get("/duplicates/ids")
    assert resp.status_code == 200
    assert "No exact duplicates" in resp.text


@pytest.mark.unit
def test_update_playlists_creates_job(authed_client, monkeypatch):
    import spotfm.web.routes.spotify as spotify_routes

    def mock_spawn_job(job, fn, *args, **kwargs):
        return None

    monkeypatch.setattr(spotify_routes, "spawn_job", mock_spawn_job)

    resp = authed_client.post("/jobs/update-playlists", follow_redirects=False)
    assert resp.status_code == 302
    assert "/jobs/" in resp.headers["location"]


@pytest.mark.unit
def test_update_liked_creates_job(authed_client, monkeypatch):
    import spotfm.web.routes.spotify as spotify_routes

    def mock_spawn_job(job, fn, *args, **kwargs):
        return None

    monkeypatch.setattr(spotify_routes, "spawn_job", mock_spawn_job)

    resp = authed_client.post("/jobs/update-liked", follow_redirects=False)
    assert resp.status_code == 302
    assert "/jobs/" in resp.headers["location"]


@pytest.mark.unit
def test_update_playlists_parses_form_before_running_job_guard(authed_client, monkeypatch):
    """The running-job guard must run after the form parse: awaiting the body between
    the check and the job creation would let two concurrent requests (double-click)
    both pass the check and start duplicate jobs."""
    import spotfm.web.routes.spotify as spotify_routes
    from spotfm.web.jobs import JobStatus, create_job

    order = []
    running = create_job("update-playlists")
    running.status = JobStatus.RUNNING

    async def fake_form(self):
        order.append("form")
        return {}

    monkeypatch.setattr("starlette.requests.Request.form", fake_form)
    monkeypatch.setattr(spotify_routes, "get_running_job", lambda name: order.append("guard") or running)

    resp = authed_client.post("/jobs/update-playlists", follow_redirects=False)
    assert resp.status_code == 302
    assert f"/jobs/{running.id}" in resp.headers["location"]
    assert order == ["form", "guard"]


@pytest.mark.unit
def test_discover_unconfigured_renders_400_error(authed_client):
    """The unconfigured-discover response must render the playlists page with the
    error (playlists.html needs the sort/pagination context), not crash with a 500."""
    original = authed_client.app.state.config
    authed_client.app.state.config = {
        **original,
        "spotify": {"client_id": "id", "client_secret": "sec", "excluded_playlists": []},
    }
    try:
        resp = authed_client.post("/jobs/discover", follow_redirects=False)
        assert resp.status_code == 400
        assert "not configured" in resp.text
    finally:
        authed_client.app.state.config = original


@pytest.mark.unit
def test_job_status_not_found(authed_client):
    resp = authed_client.get("/jobs/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.unit
def test_job_status_found(authed_client, monkeypatch):
    from spotfm.web.jobs import JobStatus, create_job

    job = create_job("test-job")
    job.status = JobStatus.DONE

    resp = authed_client.get(f"/jobs/{job.id}")
    assert resp.status_code == 200
    assert "Done" in resp.text


@pytest.mark.unit
def test_track_counts_default_path_used_when_unset(authed_client, tmp_path, monkeypatch):
    """Without track_counts_log, the page must read the same default path the update
    job writes to (utils.WORK_DIR / "track-counts.csv"), not report it unconfigured."""
    csv_file = tmp_path / "track-counts.csv"
    csv_file.write_text("2024-01-01;100\n2024-02-01;105\n")
    monkeypatch.setattr("spotfm.utils.WORK_DIR", tmp_path)

    resp = authed_client.get("/track-counts")
    assert resp.status_code == 200
    assert "2024-02-01" in resp.text


@pytest.mark.unit
def test_track_counts_default_path_missing_file(authed_client, tmp_path, monkeypatch):
    monkeypatch.setattr("spotfm.utils.WORK_DIR", tmp_path)
    resp = authed_client.get("/track-counts")
    assert resp.status_code == 200
    assert "not found" in resp.text


@pytest.mark.unit
def test_track_counts_renders_liked_column(authed_client, tmp_path, monkeypatch):
    """The liked_tracks CSV column renders on the /track-counts page."""
    csv_file = tmp_path / "track-counts.csv"
    csv_file.write_text("timestamp;total_tracks;pattern_tracks;liked_tracks\n2024-01-01;100;;50\n2024-02-01;105;2;52\n")
    monkeypatch.setattr("spotfm.utils.WORK_DIR", tmp_path)

    resp = authed_client.get("/track-counts")
    assert resp.status_code == 200
    assert "liked_tracks" in resp.text
    assert "52" in resp.text


@pytest.mark.unit
def test_dashboard_shows_liked_and_union_tracks(authed_client, temp_database):
    """Dashboard: tracks = playlist members + liked (pure orphans excluded), plus a liked stat."""
    from spotfm import sqlite as sqlite_module

    sqlite_module.migrate_database_schema(temp_database)
    conn = sqlite3.connect(str(temp_database))
    conn.execute("INSERT INTO playlists (id, name, owner, updated_at) VALUES ('p1', 'PL1', 'u', '2026-01-01')")
    conn.execute("INSERT INTO tracks (id, name, updated_at) VALUES ('t1', 'In Playlist', '2026-01-01')")
    conn.execute(
        "INSERT INTO tracks (id, name, updated_at, liked, liked_at) VALUES ('t2', 'Liked Only', '2026-01-01', 1, '2026-01-01')"
    )
    conn.execute("INSERT INTO tracks (id, name, updated_at) VALUES ('t3', 'Orphan', '2026-01-01')")
    conn.execute("INSERT INTO playlists_tracks VALUES ('p1', 't1', '2026-01-01')")
    conn.commit()
    conn.close()

    resp = authed_client.get("/")
    assert resp.status_code == 200
    assert "Liked songs" in resp.text
    # tracks: t1 (playlist) + t2 (liked); pure orphan t3 excluded
    assert "<h3>2</h3>" in resp.text
    # liked: t2 only
    assert "<h3>1</h3>" in resp.text


@pytest.mark.unit
def test_track_counts_renders_csv(authed_client, tmp_path, monkeypatch):
    csv_file = tmp_path / "track-counts.csv"
    csv_file.write_text("2024-01-01,100\n2024-02-01,105\n")

    # Patch config to point at temp CSV
    original_state = authed_client.app.state.config
    patched_config = {
        **original_state,
        "spotify": {**original_state.get("spotify", {}), "track_counts_log": str(csv_file)},
    }
    authed_client.app.state.config = patched_config

    resp = authed_client.get("/track-counts")
    assert resp.status_code == 200
    assert "2024-02-01" in resp.text

    authed_client.app.state.config = original_state


@pytest.mark.unit
def test_tracks_liked_filter_passthrough(authed_client, monkeypatch):
    """liked=liked maps to liked=True in the core query."""
    import spotfm.spotify.misc as misc_module

    captured = {}
    monkeypatch.setattr(misc_module, "find_tracks_by_criteria", lambda **kwargs: captured.update(kwargs) or [])
    resp = authed_client.get("/tracks?liked=liked")
    assert resp.status_code == 200
    assert captured["liked"] is True


@pytest.mark.unit
def test_tracks_not_liked_filter_passthrough(authed_client, monkeypatch):
    import spotfm.spotify.misc as misc_module

    captured = {}
    monkeypatch.setattr(misc_module, "find_tracks_by_criteria", lambda **kwargs: captured.update(kwargs) or [])
    resp = authed_client.get("/tracks?liked=not")
    assert resp.status_code == 200
    assert captured["liked"] is False


@pytest.mark.unit
def test_tracks_playlist_none_maps_to_no_playlist_mode(authed_client, monkeypatch):
    import spotfm.spotify.misc as misc_module

    captured = {}
    monkeypatch.setattr(misc_module, "find_tracks_by_criteria", lambda **kwargs: captured.update(kwargs) or [])
    resp = authed_client.get("/tracks?playlist=none")
    assert resp.status_code == 200
    assert captured["playlist_patterns"] == misc_module.NO_PLAYLIST_PATTERN


@pytest.mark.unit
def test_tracks_no_playlist_filter_passes_none(authed_client, monkeypatch):
    """No playlist selected: all tracks (liked-only and zero-playlist included)."""
    import spotfm.spotify.misc as misc_module

    captured = {}
    monkeypatch.setattr(misc_module, "find_tracks_by_criteria", lambda **kwargs: captured.update(kwargs) or [])
    resp = authed_client.get("/tracks")
    assert resp.status_code == 200
    assert captured["playlist_patterns"] is None
    assert captured["liked"] is None


@pytest.mark.unit
def test_tracks_page_renders_liked_column(authed_client, temp_database, monkeypatch):
    from spotfm import sqlite as sqlite_module

    sqlite_module.migrate_database_schema(temp_database)
    conn = sqlite3.connect(str(temp_database))
    conn.execute(
        "INSERT INTO tracks (id, name, updated_at, liked, liked_at) VALUES ('t1', 'Liked One', '2026-01-01', 1, '2026-01-01')"
    )
    conn.execute("INSERT INTO tracks (id, name, updated_at, liked) VALUES ('t2', 'Plain One', '2026-01-01', 0)")
    conn.commit()
    conn.close()

    resp = authed_client.get("/tracks")
    assert resp.status_code == 200
    assert "Liked" in resp.text
    assert "Liked One" in resp.text
    assert "Yes" in resp.text


@pytest.mark.unit
def test_tracks_sort_by_liked_mixed_rows(authed_client, temp_database, monkeypatch):
    """Sorting by liked must not crash on pages mixing liked and not-liked rows.

    Regression: liked False was coerced to "" by the sort key while True stayed
    a bool, and comparing them raises TypeError (a 500 on the /tracks page).
    """
    from spotfm import sqlite as sqlite_module

    sqlite_module.migrate_database_schema(temp_database)
    conn = sqlite3.connect(str(temp_database))
    conn.execute(
        "INSERT INTO tracks (id, name, updated_at, liked, liked_at) VALUES ('t1', 'Liked One', '2026-01-01', 1, '2026-01-01')"
    )
    conn.execute("INSERT INTO tracks (id, name, updated_at, liked) VALUES ('t2', 'Plain One', '2026-01-01', 0)")
    conn.commit()
    conn.close()

    # The default view excludes pure orphans; playlist=none is the window that
    # shows zero-playlist tracks, so both rows are visible and sortable there
    for direction in ("asc", "desc"):
        resp = authed_client.get(f"/tracks?playlist=none&sort=liked&dir={direction}")
        assert resp.status_code == 200
        assert "Liked One" in resp.text
        assert "Plain One" in resp.text

    # desc puts the liked track first
    resp = authed_client.get("/tracks?playlist=none&sort=liked&dir=desc")
    assert resp.text.index("Liked One") < resp.text.index("Plain One")
