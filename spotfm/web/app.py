import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from spotfm import utils
from spotfm.spotify import client as spotify_client
from spotfm.web.auth import BasicAuthMiddleware
from spotfm.web.routes import lastfm as lastfm_routes
from spotfm.web.routes import spotify as spotify_routes

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def create_app(config_file=None):
    # INFO records from the business modules feed the job log handlers (live logs);
    # nothing else listens on the root logger in this process, so no restore is needed
    logging.getLogger().setLevel(logging.INFO)

    config = utils.parse_config(config_file) if config_file else utils.parse_config()

    api_key = config.get("web", {}).get("api_key", "")
    if not api_key:
        raise RuntimeError("[web] api_key is missing or empty in spotfm.toml")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.config = config
        spotify_cfg = config.get("spotify", {})
        app.state.spotify_client = spotify_client.Client(
            client_id=spotify_cfg["client_id"],
            client_secret=spotify_cfg["client_secret"],
        )
        yield

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(BasicAuthMiddleware, api_key=api_key)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(spotify_routes.router)
    app.include_router(lastfm_routes.router)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        from spotfm import sqlite
        from spotfm.utils import DATABASE

        # Track universe mirrors count-tracks: playlist members + liked tracks
        # (pure negative-cache orphans excluded)
        union_tracks = "SELECT track_id FROM playlists_tracks UNION SELECT id FROM tracks WHERE liked = 1"
        queries = {
            "tracks": f"SELECT COUNT(*) FROM ({union_tracks})",
            "liked": "SELECT COUNT(*) FROM tracks WHERE liked = 1",
            "playlists": "SELECT COUNT(*) FROM playlists",
            "artists": f"SELECT COUNT(DISTINCT ta.artist_id) FROM tracks_artists ta WHERE ta.track_id IN ({union_tracks})",
            "albums": f"SELECT COUNT(DISTINCT at.album_id) FROM albums_tracks at WHERE at.track_id IN ({union_tracks})",
        }
        counts = {}
        for key, query in queries.items():
            row = sqlite.select_db(DATABASE, query).fetchone()
            counts[key] = row[0] if row else 0
        return templates.TemplateResponse(request, "index.html", context={"counts": counts})

    return app


def run():
    # Single worker: the job registry and running-job guards are in-process state —
    # multiple worker processes would each track their own jobs
    uvicorn.run("spotfm.web.app:create_app", factory=True, host="0.0.0.0", port=8000, workers=1)
