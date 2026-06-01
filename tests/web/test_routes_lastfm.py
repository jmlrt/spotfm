import pytest


@pytest.mark.unit
def test_scrobbles_form_shown_by_default(authed_client, monkeypatch):
    """GET /scrobbles without ?fetch shows the form, not results."""
    import spotfm.web.routes.lastfm as route_module

    monkeypatch.setattr(route_module, "read_lastfm_state", lambda: {"last_scrobble_count": 1000})

    resp = authed_client.get("/scrobbles")
    assert resp.status_code == 200
    assert "Fetch scrobbles" in resp.text
    assert "1000 scrobbles" in resp.text


@pytest.mark.unit
def test_scrobbles_form_no_state(authed_client, monkeypatch):
    """Form shows first-run message when no state file exists."""
    import spotfm.web.routes.lastfm as route_module

    monkeypatch.setattr(route_module, "read_lastfm_state", lambda: None)

    resp = authed_client.get("/scrobbles")
    assert resp.status_code == 200
    assert "No saved state yet" in resp.text


@pytest.mark.unit
def test_scrobbles_fetch_incremental_new(authed_client, monkeypatch):
    """?fetch=1 with no explicit limit uses incremental state."""
    from unittest.mock import MagicMock

    import spotfm.lastfm as lastfm_module
    import spotfm.web.routes.lastfm as route_module

    mock_user = MagicMock()
    mock_user.get_playcount.return_value = 1032
    mock_user.get_recent_tracks_scrobbles.return_value = iter(
        ["Shurik'n - Manifeste - 5 - 20 - https://www.last.fm/user/x/library/music/Shurikn/_/Manifeste"]
    )
    monkeypatch.setattr(lastfm_module, "Client", MagicMock())
    monkeypatch.setattr(lastfm_module, "User", lambda _: mock_user)
    monkeypatch.setattr(route_module, "read_lastfm_state", lambda: {"last_scrobble_count": 1000})
    monkeypatch.setattr(route_module, "save_lastfm_state", lambda _: None)

    resp = authed_client.get("/scrobbles?fetch=1")
    assert resp.status_code == 200
    assert mock_user.get_recent_tracks_scrobbles.call_args.kwargs["limit"] == 32
    assert "since last check" in resp.text
    assert "Shurik" in resp.text
    assert "Manifeste" in resp.text


@pytest.mark.unit
def test_scrobbles_fetch_no_new(authed_client, monkeypatch):
    """?fetch=1 incremental with no new scrobbles shows no_new message."""
    from unittest.mock import MagicMock

    import spotfm.lastfm as lastfm_module
    import spotfm.web.routes.lastfm as route_module

    mock_user = MagicMock()
    mock_user.get_playcount.return_value = 1000
    monkeypatch.setattr(lastfm_module, "Client", MagicMock())
    monkeypatch.setattr(lastfm_module, "User", lambda _: mock_user)
    monkeypatch.setattr(route_module, "read_lastfm_state", lambda: {"last_scrobble_count": 1000})
    monkeypatch.setattr(route_module, "save_lastfm_state", lambda _: None)

    resp = authed_client.get("/scrobbles?fetch=1")
    assert resp.status_code == 200
    assert "No new scrobbles" in resp.text


@pytest.mark.unit
def test_scrobbles_fetch_explicit_limit_skips_state(authed_client, monkeypatch):
    """?fetch=1&limit=30 bypasses incremental state logic."""
    from unittest.mock import MagicMock, patch

    import spotfm.lastfm as lastfm_module
    import spotfm.web.routes.lastfm as route_module

    mock_user = MagicMock()
    mock_user.get_recent_tracks_scrobbles.return_value = iter(
        ["Artist A - Track 1 - 5 - 20 - https://www.last.fm/user/x/library/music/Artist+A/_/Track+1"]
    )
    monkeypatch.setattr(lastfm_module, "Client", MagicMock())
    monkeypatch.setattr(lastfm_module, "User", lambda _: mock_user)
    monkeypatch.setattr(route_module, "read_lastfm_state", lambda: {"last_scrobble_count": 1000})

    with patch.object(route_module, "save_lastfm_state") as mock_save:
        resp = authed_client.get("/scrobbles?fetch=1&limit=30&scrobbles_minimum=5&period=60&period_minimum=20")
        mock_save.assert_not_called()

    assert resp.status_code == 200
    mock_user.get_recent_tracks_scrobbles.assert_called_once_with(
        limit=30, scrobbles_minimum=5, period=60, period_minimum=20
    )
    assert "last.fm" in resp.text


@pytest.mark.unit
def test_scrobbles_artist_title_split(authed_client, monkeypatch):
    """Artist and title appear in separate columns."""
    from unittest.mock import MagicMock

    import spotfm.lastfm as lastfm_module
    import spotfm.web.routes.lastfm as route_module

    mock_user = MagicMock()
    mock_user.get_playcount.return_value = 1010
    mock_user.get_recent_tracks_scrobbles.return_value = iter(
        ["Akhenaton - La Boîte de Pattes - 3 - 12 - https://www.last.fm/user/x/library/music/Akhenaton/_/La+Boite"]
    )
    monkeypatch.setattr(lastfm_module, "Client", MagicMock())
    monkeypatch.setattr(lastfm_module, "User", lambda _: mock_user)
    monkeypatch.setattr(route_module, "read_lastfm_state", lambda: {"last_scrobble_count": 1000})
    monkeypatch.setattr(route_module, "save_lastfm_state", lambda _: None)

    resp = authed_client.get("/scrobbles?fetch=1")
    assert resp.status_code == 200
    assert "Akhenaton" in resp.text
    assert "La Boîte de Pattes" in resp.text
