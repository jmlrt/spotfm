import pytest


@pytest.mark.unit
def test_scrobbles_page_renders(authed_client, monkeypatch):
    from unittest.mock import MagicMock

    import spotfm.lastfm as lastfm_module

    mock_user = MagicMock()
    mock_user.get_recent_tracks_scrobbles.return_value = iter(
        [
            "Artist A - Track 1 - 5 - 20 - http://last.fm/...",
            "Artist B - Track 2 - 3 - 10 - http://last.fm/...",
        ]
    )
    monkeypatch.setattr(lastfm_module, "Client", MagicMock())
    monkeypatch.setattr(lastfm_module, "User", lambda _: mock_user)

    resp = authed_client.get("/scrobbles")
    assert resp.status_code == 200
    assert "Artist A" in resp.text


@pytest.mark.unit
def test_scrobbles_with_query_params(authed_client, monkeypatch):
    from unittest.mock import MagicMock

    import spotfm.lastfm as lastfm_module

    mock_user = MagicMock()
    mock_user.get_recent_tracks_scrobbles.return_value = iter(["Track 1"])
    monkeypatch.setattr(lastfm_module, "Client", MagicMock())
    monkeypatch.setattr(lastfm_module, "User", lambda _: mock_user)

    resp = authed_client.get("/scrobbles?limit=30&scrobbles_minimum=5&period=60&period_minimum=20")
    assert resp.status_code == 200
    mock_user.get_recent_tracks_scrobbles.assert_called_once_with(
        limit=30, scrobbles_minimum=5, period=60, period_minimum=20
    )


@pytest.mark.unit
def test_scrobbles_invalid_query_params_uses_defaults(authed_client, monkeypatch):
    from unittest.mock import MagicMock

    import spotfm.lastfm as lastfm_module

    mock_user = MagicMock()
    mock_user.get_recent_tracks_scrobbles.return_value = iter(["Track 1"])
    monkeypatch.setattr(lastfm_module, "Client", MagicMock())
    monkeypatch.setattr(lastfm_module, "User", lambda _: mock_user)

    # Pass invalid integers - should use defaults instead of crashing
    resp = authed_client.get("/scrobbles?limit=abc&scrobbles_minimum=xyz&period=invalid")
    assert resp.status_code == 200
    # Should have called with defaults (limit=50, scrobbles_minimum=4, period=90, period_minimum=None)
    mock_user.get_recent_tracks_scrobbles.assert_called_once_with(
        limit=50, scrobbles_minimum=4, period=90, period_minimum=None
    )
