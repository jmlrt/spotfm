import csv
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
async def scrobbles(request: Request):
    redirect = await require_auth(request)
    if redirect:
        return redirect

    config = request.app.state.config
    lastfm_cfg = config.get("lastfm", {})
    lfm_client = lastfm.Client(
        api_key=lastfm_cfg["api_key"],
        api_secret=lastfm_cfg["api_secret"],
        username=lastfm_cfg["username"],
        password_hash=lastfm_cfg["password_hash"],
    )
    user = lastfm.User(lfm_client.client)
    scrobbles_minimum = lastfm_cfg.get("scrobbles_minimum", 4)
    period_minimum = lastfm_cfg.get("period_minimum")
    # get_recent_tracks_scrobbles yields formatted strings
    tracks = list(
        user.get_recent_tracks_scrobbles(
            limit=50,
            scrobbles_minimum=scrobbles_minimum,
            period=90,
            period_minimum=period_minimum,
        )
    )
    return templates.TemplateResponse(request, "scrobbles.html", context={"tracks": tracks})


@router.get("/track-counts", response_class=HTMLResponse)
async def track_counts(request: Request):
    redirect = await require_auth(request)
    if redirect:
        return redirect

    config = request.app.state.config
    log_path_raw = config.get("spotify", {}).get("track_counts_log", "")
    if not log_path_raw:
        return templates.TemplateResponse(
            request, "track_counts.html", context={"rows": [], "error": "track_counts_log not configured"}
        )

    log_path = Path(log_path_raw).expanduser()
    if not log_path.exists():
        return templates.TemplateResponse(
            request, "track_counts.html", context={"rows": [], "error": f"Log file not found: {log_path}"}
        )

    rows = []
    with open(log_path, newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            rows.append(row)

    rows.sort(key=lambda r: r[0] if r else "", reverse=True)

    return templates.TemplateResponse(request, "track_counts.html", context={"rows": rows, "error": None})
