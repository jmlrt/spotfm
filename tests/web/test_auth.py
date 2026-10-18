import base64

import pytest

from tests.web.conftest import TEST_API_KEY, basic_auth_header


def _header(api_key: str) -> str:
    return basic_auth_header(api_key)["Authorization"]


@pytest.mark.unit
def test_unauthenticated_request_gets_401_with_challenge(client):
    resp = client.get("/playlists")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == 'Basic realm="spotfm"'


@pytest.mark.unit
def test_wrong_api_key_gets_401(client):
    client.headers.update(basic_auth_header("wrong-key"))
    resp = client.get("/playlists")
    assert resp.status_code == 401


@pytest.mark.unit
def test_authenticated_request_passes(authed_client):
    resp = authed_client.get("/playlists")
    assert resp.status_code == 200


@pytest.mark.unit
def test_username_is_ignored(authed_client):
    # Only the password position matters — any username works
    token = base64.b64encode(f"anyuser:{TEST_API_KEY}".encode()).decode()
    authed_client.headers.update({"Authorization": f"Basic {token}"})
    resp = authed_client.get("/playlists")
    assert resp.status_code == 200


@pytest.mark.unit
def test_malformed_authorization_header_gets_401(client):
    for header in ("Bearer something", "Basic !!!not-base64!!!", "Basic"):
        client.headers.update({"Authorization": header})
        assert client.get("/playlists").status_code == 401


@pytest.mark.unit
def test_dashboard_requires_auth(client):
    assert client.get("/", follow_redirects=False).status_code == 401


@pytest.mark.unit
def test_non_ascii_password_gets_401_not_500(client):
    # hmac.compare_digest rejects non-ASCII strings — a typo'd accented password
    # must still be rejected cleanly instead of raising TypeError (500)
    token = base64.b64encode("spotfm:pässwörd".encode()).decode()
    client.headers.update({"Authorization": f"Basic {token}"})
    resp = client.get("/playlists")
    assert resp.status_code == 401


@pytest.mark.unit
def test_verify_basic_auth_supports_non_ascii_key():
    # A non-ASCII configured key must be usable, not crash compare_digest
    from spotfm.web.auth import verify_basic_auth

    class StubRequest:
        def __init__(self, header):
            self.headers = {"Authorization": header}

    token = base64.b64encode("user:clé-secrète".encode()).decode()
    request = StubRequest(f"Basic {token}")
    assert verify_basic_auth(request, "clé-secrète") is True
    assert verify_basic_auth(request, "autre-clé") is False
