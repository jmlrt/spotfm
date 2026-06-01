from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from spotfm import lastfm
from spotfm.lastfm import read_lastfm_state, save_lastfm_state
from spotfm.web.auth import require_auth
from spotfm.web.pagination import paginate, pagination_base_url

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()

_FORM_CONTEXT = "form"


def _parse_track_line(line: str) -> dict:
    """Parse 'Artist - Title - period - total - url' into a dict with separate artist/title."""
    parts = line.rsplit(" - ", 3)
    if len(parts) == 4:
        name_part = parts[0]
        artist, _, title = name_part.partition(" - ")
        return {
            "artist": artist.strip(),
            "title": title.strip() if title else name_part.strip(),
            "period_scrobbles": parts[1],
            "total_scrobbles": parts[2],
            "url": parts[3],
        }
    return {"artist": "", "title": line, "period_scrobbles": "?", "total_scrobbles": "?", "url": ""}


@router.get("/scrobbles", response_class=HTMLResponse)
async def scrobbles(
    request: Request,
    fetch: bool = Query(default=False),
    limit: str = Query(default=""),
    scrobbles_minimum: str = Query(default=""),
    period: int = Query(default=90),
    period_minimum: str = Query(default=""),
    page: int = Query(default=1, ge=1),
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

    incremental = limit_int is None
    effective_limit: int = limit_int if limit_int is not None else lastfm_cfg.get("limit", 50)
    current_count = None

    if incremental:
        current_count = user.get_playcount()
        if not isinstance(last_count, int):
            effective_limit = lastfm_cfg.get("limit", 50)
        else:
            effective_limit = current_count - last_count
            if effective_limit <= 0:
                save_lastfm_state(current_count)
                return templates.TemplateResponse(
                    request,
                    "scrobbles.html",
                    context={"state": "no_new", "error": None, "state_info": None, "cfg": lastfm_cfg},
                )

    raw_tracks = list(
        user.get_recent_tracks_scrobbles(
            limit=effective_limit,
            scrobbles_minimum=scrobbles_minimum_int
            if scrobbles_minimum_int is not None
            else lastfm_cfg.get("scrobbles_minimum", 4),
            period=period,
            period_minimum=period_minimum_int if period_minimum_int is not None else lastfm_cfg.get("period_minimum"),
        )
    )
    tracks = [_parse_track_line(line) for line in raw_tracks]

    if incremental:
        save_lastfm_state(current_count)

    # Default order: descending by period scrobbles
    tracks.sort(key=lambda r: int(r["period_scrobbles"]) if r["period_scrobbles"].isdigit() else 0, reverse=True)

    page_tracks, pagination = paginate(tracks, page)

    return templates.TemplateResponse(
        request,
        "scrobbles.html",
        context={
            "state": "results",
            "error": None,
            "tracks": page_tracks,
            "period": period,
            "incremental": incremental,
            "pagination": pagination,
            "base_url": pagination_base_url(request),
        },
    )
