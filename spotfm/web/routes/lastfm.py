from pathlib import Path

from fastapi import APIRouter, Request
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
    limit: str = "",
    scrobbles_minimum: str = "",
    period: str = "",
    period_minimum: str = "",
):
    redirect = await require_auth(request)
    if redirect:
        return redirect

    config = request.app.state.config
    lastfm_cfg = config.get("lastfm", {})
    lastfm_client = lastfm.Client(
        api_key=lastfm_cfg["api_key"],
        api_secret=lastfm_cfg["api_secret"],
        username=lastfm_cfg["username"],
        password_hash=lastfm_cfg["password_hash"],
    )
    user = lastfm.User(lastfm_client.client)

    try:
        limit_val = int(limit) if limit else 50
        scrobbles_min_val = int(scrobbles_minimum) if scrobbles_minimum else lastfm_cfg.get("scrobbles_minimum", 4)
        period_val = int(period) if period else 90
        period_min_val = int(period_minimum) if period_minimum else lastfm_cfg.get("period_minimum")
    except ValueError:
        limit_val = 50
        scrobbles_min_val = lastfm_cfg.get("scrobbles_minimum", 4)
        period_val = 90
        period_min_val = lastfm_cfg.get("period_minimum")

    # get_recent_tracks_scrobbles yields formatted strings
    tracks = list(
        user.get_recent_tracks_scrobbles(
            limit=limit_val,
            scrobbles_minimum=scrobbles_min_val,
            period=period_val,
            period_minimum=period_min_val,
        )
    )
    return templates.TemplateResponse(request, "scrobbles.html", context={"tracks": tracks})
