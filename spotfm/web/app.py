import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from spotfm import utils
from spotfm.spotify import client as spotify_client
from spotfm.web.auth import check_api_key, require_auth
from spotfm.web.routes import lastfm as lastfm_routes
from spotfm.web.routes import spotify as spotify_routes

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def create_app(config_file=None):
    config = utils.parse_config(config_file) if config_file else utils.parse_config()

    web_config = config.get("web", {})
    api_key = web_config.get("api_key", "")
    if not api_key:
        print("ERROR: [web] api_key is missing or empty in spotfm.toml", file=sys.stderr)
        sys.exit(1)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.config = config
        app.state.api_key = api_key
        spotify_cfg = config.get("spotify", {})
        app.state.spotify_client = spotify_client.Client(
            client_id=spotify_cfg["client_id"],
            client_secret=spotify_cfg["client_secret"],
        )
        yield

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=api_key, max_age=86400 * 7, https_only=False)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(spotify_routes.router)
    app.include_router(lastfm_routes.router)

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        return templates.TemplateResponse(request, "login.html", context={"error": None})

    @app.post("/login")
    async def login(request: Request, api_key_input: str = Form(alias="api_key")):
        if check_api_key(api_key_input, request.app.state.api_key):
            request.session["authenticated"] = True
            from urllib.parse import unquote

            next_url = unquote(request.query_params.get("next", "/"))
            # Validate next_url is a safe relative path (prevent open redirect)
            if not next_url.startswith("/") or "://" in next_url:
                next_url = "/"
            return RedirectResponse(url=next_url, status_code=302)
        return templates.TemplateResponse(request, "login.html", context={"error": "Invalid API key"}, status_code=401)

    @app.post("/logout")
    async def logout(request: Request):
        request.session.clear()
        return RedirectResponse(url="/login", status_code=302)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        redirect = await require_auth(request)
        if redirect:
            return redirect
        from spotfm import sqlite
        from spotfm.utils import DATABASE

        counts = {}
        for table in ("tracks", "playlists", "artists", "albums"):
            row = sqlite.select_db(DATABASE, f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[table] = row[0] if row else 0
        return templates.TemplateResponse(request, "index.html", context={"counts": counts})

    return app


def run():
    # Single worker is required for SQLite singleton connection safety
    # see: spotfm/sqlite.py check_same_thread=False
    uvicorn.run("spotfm.web.app:create_app", factory=True, host="0.0.0.0", port=8000, workers=1)
