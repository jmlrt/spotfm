from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spotfm import sqlite, utils

TEST_API_KEY = "test-api-key-12345"


def _write_test_config(path: Path) -> Path:
    config_dir = path / ".spotfm"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "spotfm.toml"
    config_file.write_text(f"""
[web]
api_key = "{TEST_API_KEY}"

[spotify]
client_id = "test_client_id"
client_secret = "test_client_secret"
excluded_playlists = []
sources_playlists = ["source1"]
discover_playlist = "discover_id"

[lastfm]
api_key = "test_lfm_key"
api_secret = "test_lfm_secret"
username = "testuser"
password_hash = "testhash"
""")
    return config_file


@pytest.fixture(autouse=True)
def reset_jobs():
    from spotfm.web.jobs import reset_jobs as _reset

    _reset()
    yield
    _reset()


@pytest.fixture
def test_config_file(tmp_path):
    return _write_test_config(tmp_path)


@pytest.fixture
def app(temp_database, test_config_file, monkeypatch):
    monkeypatch.setattr(utils, "DATABASE", temp_database)
    monkeypatch.setattr(sqlite, "DATABASE", temp_database)

    sqlite.close_db_connection()
    sqlite._reset_migration_state_for_tests()

    # Patch Spotify client creation to avoid real OAuth
    import unittest.mock as mock

    from spotfm.web.app import create_app

    with mock.patch("spotfm.web.app.spotify_client.Client") as mock_client_cls:
        mock_client_cls.return_value = mock.MagicMock()
        return create_app(config_file=test_config_file)


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture
def authed_client(client):
    resp = client.post("/login", data={"api_key": TEST_API_KEY})
    assert resp.status_code in (200, 302)
    return client
