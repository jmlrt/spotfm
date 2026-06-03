from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from spotfm import lastfm
from spotfm.lastfm import fetch_recent_scrobbles, read_lastfm_state
from spotfm.web.auth import require_auth

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()

_FORM_CONTEXT = "form"


@router.get("/scrobbles", response_class=HTMLResponse)
async def scrobbles(
    request: Request,
    fetch: bool = Query(default=False),
    limit: str = Query(default=""),
    scrobbles_minimum: str = Query(default=""),
    period: int = Query(default=90),
    period_minimum: str = Query(default=""),
):
    redirect = await require_auth(request)
    if redirect:
        return redirect

    limit_int: int | None = int(limit) if limit.strip().isdigit() else None
    scrobbles_minimum_int: int | None = int(scrobbles_minimum) if scrobbles_minimum.strip().isdigit() else None
    period_minimum_int: int | None = int(period_minimum) if period_minimum.strip().isdigit() else None

    config = request.app.state.config
    lastfm_cfg = config.get("lastfm", {})

    required_keys = ["api_key", "api_secret", "username", "password_hash"]
    if any(not lastfm_cfg.get(k) for k in required_keys):
        return templates.TemplateResponse(
            request,
            "scrobbles.html",
            context={"state": _FORM_CONTEXT, "error": "Last.FM not configured", "state_info": None, "cfg": lastfm_cfg},
        )

    # Read current state for display in the form
    state_file = read_lastfm_state()
    last_count = (state_file or {}).get("last_scrobble_count") if isinstance(state_file, dict) else None

    if not fetch:
        return templates.TemplateResponse(
            request,
            "scrobbles.html",
            context={
                "state": _FORM_CONTEXT,
                "error": None,
                "state_info": {"last_scrobble_count": last_count} if isinstance(last_count, int) else None,
                "cfg": lastfm_cfg,
                "defaults": {
                    "period": lastfm_cfg.get("period", 90),
                    "scrobbles_minimum": lastfm_cfg.get("scrobbles_minimum", 4),
                    "period_minimum": lastfm_cfg.get("period_minimum", ""),
                    "limit": "",
                },
            },
        )

    # --- Fetch path ---
    lastfm_client = lastfm.Client(
        api_key=lastfm_cfg["api_key"],
        api_secret=lastfm_cfg["api_secret"],
        username=lastfm_cfg["username"],
        password_hash=lastfm_cfg["password_hash"],
    )
    user = lastfm.User(lastfm_client.client)

    # Fetch scrobbles with incremental state management (orchestration in lastfm module)
    tracks, mode = fetch_recent_scrobbles(
        user,
        lastfm_cfg,
        limit=limit_int,
        scrobbles_minimum=scrobbles_minimum_int,
        period=period,
        period_minimum=period_minimum_int,
    )

    if mode == "no_new":
        return templates.TemplateResponse(
            request,
            "scrobbles.html",
            context={"state": "no_new", "error": None, "state_info": None, "cfg": lastfm_cfg},
        )

    # Default order: descending by period scrobbles
    tracks.sort(key=lambda r: r["period_scrobbles"], reverse=True)

    return templates.TemplateResponse(
        request,
        "scrobbles.html",
        context={
            "state": "results",
            "error": None,
            "tracks": tracks,
            "period": period,
            "incremental": mode == "incremental",
        },
    )
