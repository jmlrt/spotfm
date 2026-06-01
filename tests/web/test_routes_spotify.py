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
    import spotfm.web.jobs as jobs_module

    calls = []

    async def fake_run_job(job, fn, **kwargs):
        calls.append(job.name)

    monkeypatch.setattr(jobs_module, "run_job", fake_run_job)
    import asyncio

    def mock_create_task(coro):
        coro.close()
        return None

    monkeypatch.setattr(asyncio, "create_task", mock_create_task)

    resp = authed_client.post("/jobs/update-playlists", follow_redirects=False)
    assert resp.status_code == 302
    assert "/jobs/" in resp.headers["location"]


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
def test_track_counts_missing_config(authed_client):
    resp = authed_client.get("/track-counts")
    assert resp.status_code == 200
    assert "not configured" in resp.text or "not found" in resp.text


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
