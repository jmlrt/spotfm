import pytest

from tests.web.conftest import TEST_API_KEY


@pytest.mark.unit
def test_login_correct_key(client):
    resp = client.post("/login", data={"api_key": TEST_API_KEY}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"


@pytest.mark.unit
def test_login_wrong_key(client):
    resp = client.post("/login", data={"api_key": "wrong"})
    assert resp.status_code == 401
    assert "Invalid API key" in resp.text


@pytest.mark.unit
def test_protected_route_redirects_unauthenticated(client):
    resp = client.get("/playlists", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["location"]


@pytest.mark.unit
def test_protected_route_accessible_after_login(authed_client):
    resp = authed_client.get("/playlists")
    assert resp.status_code == 200


@pytest.mark.unit
def test_logout_clears_session(authed_client):
    resp = authed_client.post("/logout", follow_redirects=False)
    assert resp.status_code == 302
    # After logout, protected routes redirect again
    resp = authed_client.get("/playlists", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["location"]


@pytest.mark.unit
def test_dashboard_requires_auth(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302


@pytest.mark.unit
def test_login_open_redirect_protection(client):
    # Attempt external redirect via next param
    resp = client.post(
        "/login?next=https://evil.com",
        data={"api_key": TEST_API_KEY},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    # Should redirect to "/" instead of the malicious URL
    assert resp.headers["location"] == "/"


@pytest.mark.unit
def test_login_safe_relative_redirect(client):
    # Valid relative redirect should work
    resp = client.post(
        "/login?next=/playlists",
        data={"api_key": TEST_API_KEY},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/playlists"
