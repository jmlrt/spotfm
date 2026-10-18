"""Tests for webapp assembly: session config and vendored frontend assets."""

import hashlib
import re
from pathlib import Path

import pytest
from starlette.middleware.sessions import SessionMiddleware


def _write_config(tmp_path, web_extra=""):
    config_dir = tmp_path / ".spotfm"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "spotfm.toml"
    config_file.write_text(f"""
[web]
api_key = "test-api-key-12345"
{web_extra}

[spotify]
client_id = "test_client_id"
client_secret = "test_client_secret"

[lastfm]
api_key = "test_lfm_key"
api_secret = "test_lfm_secret"
username = "testuser"
password_hash = "testhash"
""")
    return config_file


def _session_middleware(app):
    return next(m for m in app.user_middleware if m.cls is SessionMiddleware)


@pytest.mark.unit
def test_session_secret_defaults_to_api_key_hash(tmp_path):
    """Without session_secret config, cookies are signed with a hash of the API key — not the raw key."""
    from spotfm.web.app import create_app

    app = create_app(config_file=_write_config(tmp_path))
    kwargs = _session_middleware(app).kwargs
    assert kwargs["secret_key"] == hashlib.sha256(b"test-api-key-12345").hexdigest()
    assert kwargs["secret_key"] != "test-api-key-12345"


@pytest.mark.unit
def test_session_secret_stable_across_restarts(tmp_path):
    """The derived secret is deterministic so sessions survive a restart."""
    from spotfm.web.app import create_app

    first = _session_middleware(create_app(config_file=_write_config(tmp_path))).kwargs["secret_key"]
    second = _session_middleware(create_app(config_file=_write_config(tmp_path))).kwargs["secret_key"]
    assert first == second


@pytest.mark.unit
def test_dedicated_session_secret_and_https_only(tmp_path):
    """[web] session_secret and https_only override the defaults."""
    from spotfm.web.app import create_app

    config_file = _write_config(tmp_path, web_extra='session_secret = "dedicated-secret"\nhttps_only = true')
    kwargs = _session_middleware(create_app(config_file=config_file)).kwargs
    assert kwargs["secret_key"] == "dedicated-secret"
    assert kwargs["https_only"] is True


@pytest.mark.unit
def test_base_template_uses_vendored_assets():
    """No CDN references; every /static/vendor asset referenced by base.html must exist on disk."""
    web_dir = Path(__file__).parents[2] / "spotfm" / "web"
    content = (web_dir / "templates" / "base.html").read_text()

    assert "cdn.jsdelivr.net" not in content
    assert "unpkg.com" not in content

    refs = re.findall(r"/static/vendor/[\w.-]+", content)
    assert refs, "base.html should reference vendored assets"
    for ref in refs:
        assert (web_dir / "static" / ref.removeprefix("/static/")).is_file(), f"missing vendored asset: {ref}"
