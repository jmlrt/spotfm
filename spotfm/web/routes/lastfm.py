from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from spotfm import lastfm
from spotfm.web.auth import require_auth

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


@router.get("/scrobbles", response_class=HTMLResponse)
async def scrobbles(
    request: Request,
    limit: int = Query(default=50),
    scrobbles_minimum: int | None = Query(default=None),
    period: int = Query(default=90),
    period_minimum: int | None = Query(default=None),
):
    redirect = await require_auth(request)
    if redirect:
        return redirect

    config = request.app.state.config
    lastfm_cfg = config.get("lastfm", {})

    required_keys = ["api_key", "api_secret", "username", "password_hash"]
    if any(not lastfm_cfg.get(k) for k in required_keys):
        return templates.TemplateResponse(
            request, "scrobbles.html", context={"tracks": [], "error": "Last.FM not configured"}
        )

    lastfm_client = lastfm.Client(
        api_key=lastfm_cfg["api_key"],
        api_secret=lastfm_cfg["api_secret"],
        username=lastfm_cfg["username"],
        password_hash=lastfm_cfg["password_hash"],
    )
    user = lastfm.User(lastfm_client.client)

    tracks = list(
        user.get_recent_tracks_scrobbles(
            limit=limit,
            scrobbles_minimum=scrobbles_minimum
            if scrobbles_minimum is not None
            else lastfm_cfg.get("scrobbles_minimum", 4),
            period=period,
            period_minimum=period_minimum if period_minimum is not None else lastfm_cfg.get("period_minimum"),
        )
    )
    return templates.TemplateResponse(request, "scrobbles.html", context={"tracks": tracks, "error": None})
