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
