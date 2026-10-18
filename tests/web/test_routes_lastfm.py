import pytest


@pytest.mark.unit
def test_scrobbles_form_shown_by_default(authed_client, monkeypatch):
    """GET /scrobbles shows the form, not results."""
    import spotfm.lastfm as lastfm_module

    monkeypatch.setattr(lastfm_module, "read_lastfm_state", lambda: {"last_scrobble_count": 1000})

    resp = authed_client.get("/scrobbles")
    assert resp.status_code == 200
    assert "Fetch scrobbles" in resp.text
    # Form is shown with state info
    assert "scrobbles" in resp.text.lower()


@pytest.mark.unit
def test_scrobbles_form_no_state(authed_client, monkeypatch):
    """Form shows first-run message when no state file exists."""
    import spotfm.lastfm as lastfm_module

    monkeypatch.setattr(lastfm_module, "read_lastfm_state", lambda: None)

    resp = authed_client.get("/scrobbles")
    assert resp.status_code == 200
    # Form is shown (either with state or first-run message)
    assert "Fetch scrobbles" in resp.text


@pytest.mark.unit
def test_scrobbles_form_posts(authed_client):
    """The form must submit via POST — GET must never trigger a fetch."""
    resp = authed_client.get("/scrobbles")
    assert resp.status_code == 200
    assert 'method="post"' in resp.text
    assert 'name="fetch"' not in resp.text


@pytest.mark.unit
def test_scrobbles_form_offers_only_supported_periods(authed_client):
    """The period field must offer only Last.FM's supported windows (7/30/90/180/365),
    never a free-form number input."""
    resp = authed_client.get("/scrobbles")
    assert resp.status_code == 200
    assert '<select name="period">' in resp.text
    for p in (7, 30, 90, 180, 365):
        assert f'<option value="{p}"' in resp.text
    assert 'name="period" min=' not in resp.text


@pytest.mark.unit
def test_scrobbles_fetch_rejects_unsupported_period(authed_client, monkeypatch):
    """A period outside the supported windows must fail validation on the form,
    not inside the fetch job (UnknownPeriodError -> failed job)."""
    import spotfm.lastfm as lastfm_module

    calls = []
    monkeypatch.setattr(lastfm_module, "fetch_recent_scrobbles", lambda *a, **k: calls.append(1) or ([], "full"))

    resp = authed_client.post("/scrobbles", data={"period": "14"})
    assert resp.status_code == 200
    assert "Period must be one of" in resp.text
    assert calls == []


@pytest.mark.unit
def test_scrobbles_get_with_query_does_not_fetch(authed_client, monkeypatch):
    """GET /scrobbles with leftover query params (e.g. ?fetch=1) must not fetch."""
    import spotfm.lastfm as lastfm_module

    calls = []
    monkeypatch.setattr(lastfm_module, "fetch_recent_scrobbles", lambda *a, **k: calls.append(1) or ([], "full"))

    resp = authed_client.get("/scrobbles?fetch=1&limit=30")
    assert resp.status_code == 200
    assert "Fetch scrobbles" in resp.text
    assert calls == []


@pytest.mark.unit
def test_scrobbles_fetch_incremental_new(authed_client, monkeypatch):
    """POST /scrobbles with no explicit limit uses incremental state."""
    from unittest.mock import MagicMock

    import spotfm.lastfm as lastfm_module

    mock_user = MagicMock()
    mock_user.get_playcount.return_value = 1032
    mock_user.get_recent_tracks_scrobbles.return_value = iter(
        [
            {
                "artist": "Shurik'n",
                "title": "Manifeste",
                "period_scrobbles": 5,
                "total_scrobbles": 20,
                "url": "https://www.last.fm/user/x/library/music/Shurikn/_/Manifeste",
            }
        ]
    )
    monkeypatch.setattr(lastfm_module, "Client", MagicMock())
    monkeypatch.setattr(lastfm_module, "User", lambda _: mock_user)
    # Patch in lastfm module so fetch_recent_scrobbles() sees the saved state
    monkeypatch.setattr(lastfm_module, "read_lastfm_state", lambda: {"last_scrobble_count": 1000})
    monkeypatch.setattr(lastfm_module, "save_lastfm_state", lambda _: None)

    resp = authed_client.post("/scrobbles")
    assert resp.status_code == 200
    # With saved state (1000), incremental mode fetches diff (1032-1000=32 new scrobbles)
    # Template shows results including the track
    assert "Shurik" in resp.text
    assert "Manifeste" in resp.text


@pytest.mark.unit
def test_scrobbles_fetch_runs_through_job(authed_client, monkeypatch):
    """The POST fetch must go through the jobs infra (executor), not block the event loop."""
    from unittest.mock import MagicMock

    import spotfm.lastfm as lastfm_module
    from spotfm.web.jobs import JobStatus, get_latest_job

    mock_user = MagicMock()
    mock_user.get_playcount.return_value = 1032
    mock_user.get_recent_tracks_scrobbles.return_value = iter(
        [
            {
                "artist": "Shurik'n",
                "title": "Manifeste",
                "period_scrobbles": 5,
                "total_scrobbles": 20,
                "url": "https://www.last.fm/user/x/library/music/Shurikn/_/Manifeste",
            }
        ]
    )
    monkeypatch.setattr(lastfm_module, "Client", MagicMock())
    monkeypatch.setattr(lastfm_module, "User", lambda _: mock_user)
    monkeypatch.setattr(lastfm_module, "read_lastfm_state", lambda: {"last_scrobble_count": 1000})
    monkeypatch.setattr(lastfm_module, "save_lastfm_state", lambda _: None)

    resp = authed_client.post("/scrobbles")

    job = get_latest_job("scrobbles")
    assert job is not None, "POST /scrobbles must create a 'scrobbles' job"
    assert job.status == JobStatus.DONE
    assert resp.status_code == 200
    assert "Shurik" in resp.text


@pytest.mark.unit
def test_scrobbles_fetch_blocked_while_running(authed_client, monkeypatch):
    """A second fetch while one is running must be rejected without starting a new one."""
    import spotfm.lastfm as lastfm_module
    from spotfm.web.jobs import JobStatus, create_job

    calls = []
    monkeypatch.setattr(lastfm_module, "fetch_recent_scrobbles", lambda *a, **k: calls.append(1) or ([], "full"))

    running = create_job("scrobbles")
    running.status = JobStatus.RUNNING

    resp = authed_client.post("/scrobbles", data={"limit": "30"})
    assert resp.status_code == 200
    assert "already in progress" in resp.text
    assert calls == []


@pytest.mark.unit
def test_scrobbles_fetch_failure_shows_error(authed_client, monkeypatch):
    """A failing fetch surfaces the job error on the form instead of raising."""
    from unittest.mock import MagicMock

    import spotfm.lastfm as lastfm_module
    from spotfm.web.jobs import JobStatus, get_latest_job

    monkeypatch.setattr(lastfm_module, "Client", MagicMock())
    monkeypatch.setattr(lastfm_module, "User", lambda _: MagicMock())

    def _boom(*args, **kwargs):
        raise RuntimeError("lastfm exploded")

    monkeypatch.setattr(lastfm_module, "fetch_recent_scrobbles", _boom)

    resp = authed_client.post("/scrobbles")
    assert resp.status_code == 200
    assert "Fetch failed: lastfm exploded" in resp.text
    assert get_latest_job("scrobbles").status == JobStatus.FAILED


@pytest.mark.unit
def test_scrobbles_fetch_no_new(authed_client, monkeypatch):
    """POST /scrobbles incremental with no new scrobbles shows no_new message."""
    from unittest.mock import MagicMock

    import spotfm.lastfm as lastfm_module

    mock_user = MagicMock()
    mock_user.get_playcount.return_value = 1000
    monkeypatch.setattr(lastfm_module, "Client", MagicMock())
    monkeypatch.setattr(lastfm_module, "User", lambda _: mock_user)
    # Patch in lastfm module so fetch_recent_scrobbles() sees the saved state
    monkeypatch.setattr(lastfm_module, "read_lastfm_state", lambda: {"last_scrobble_count": 1000})
    monkeypatch.setattr(lastfm_module, "save_lastfm_state", lambda _: None)

    resp = authed_client.post("/scrobbles")
    assert resp.status_code == 200
    assert "No new scrobbles" in resp.text


@pytest.mark.unit
def test_scrobbles_fetch_explicit_limit_with_state(authed_client, monkeypatch):
    """With saved state, incremental mode is used even when limit is passed."""
    from unittest.mock import MagicMock

    import spotfm.lastfm as lastfm_module

    mock_user = MagicMock()
    mock_user.get_playcount.return_value = 1500
    mock_user.get_recent_tracks_scrobbles.return_value = iter(
        [
            {
                "artist": "Artist A",
                "title": "Track 1",
                "period_scrobbles": 5,
                "total_scrobbles": 20,
                "url": "https://www.last.fm/user/x/library/music/Artist+A/_/Track+1",
            }
        ]
    )
    monkeypatch.setattr(lastfm_module, "Client", MagicMock())
    monkeypatch.setattr(lastfm_module, "User", lambda _: mock_user)
    monkeypatch.setattr(lastfm_module, "read_lastfm_state", lambda: {"last_scrobble_count": 1000})
    monkeypatch.setattr(lastfm_module, "save_lastfm_state", lambda _: None)

    # Even with explicit limit=30, incremental mode uses diff (1500-1000=500)
    resp = authed_client.post(
        "/scrobbles", data={"limit": "30", "scrobbles_minimum": "5", "period": "90", "period_minimum": "20"}
    )

    assert resp.status_code == 200
    assert "last.fm" in resp.text


@pytest.mark.unit
def test_scrobbles_artist_title_split(authed_client, monkeypatch):
    """Artist and title appear in separate columns."""
    from unittest.mock import MagicMock

    import spotfm.lastfm as lastfm_module

    mock_user = MagicMock()
    mock_user.get_playcount.return_value = 1010
    mock_user.get_recent_tracks_scrobbles.return_value = iter(
        [
            {
                "artist": "Akhenaton",
                "title": "La Boîte de Pattes",
                "period_scrobbles": 3,
                "total_scrobbles": 12,
                "url": "https://www.last.fm/user/x/library/music/Akhenaton/_/La+Boite",
            }
        ]
    )
    monkeypatch.setattr(lastfm_module, "Client", MagicMock())
    monkeypatch.setattr(lastfm_module, "User", lambda _: mock_user)
    # Patch in lastfm module so fetch_recent_scrobbles() sees the saved state
    monkeypatch.setattr(lastfm_module, "read_lastfm_state", lambda: {"last_scrobble_count": 1000})
    monkeypatch.setattr(lastfm_module, "save_lastfm_state", lambda _: None)

    resp = authed_client.post("/scrobbles")
    assert resp.status_code == 200
    assert "Akhenaton" in resp.text
    assert "La Boîte de Pattes" in resp.text
