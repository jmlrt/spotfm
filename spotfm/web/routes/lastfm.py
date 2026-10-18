from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from spotfm import lastfm
from spotfm.lastfm import PREDEFINED_PERIODS
from spotfm.web.jobs import JobStatus, create_job, get_running_job, run_job

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()

_FORM_CONTEXT = "form"


def _form_int(value):
    text = value.strip() if isinstance(value, str) else ""
    return int(text) if text.isdigit() else None


async def _scrobbles_form(request: Request, error=None):
    lastfm_cfg = request.app.state.config.get("lastfm", {})
    state = lastfm.read_lastfm_state()
    last_count = state.get("last_scrobble_count") if isinstance(state, dict) else None
    return templates.TemplateResponse(
        request,
        "scrobbles.html",
        context={
            "state": _FORM_CONTEXT,
            "error": error,
            "state_info": {"last_scrobble_count": last_count} if isinstance(last_count, int) else None,
            "cfg": lastfm_cfg,
            "periods": PREDEFINED_PERIODS,
            "defaults": {
                "period": lastfm_cfg.get("period", 90),
                "scrobbles_minimum": lastfm_cfg.get("scrobbles_minimum", 4),
                "period_minimum": lastfm_cfg.get("period_minimum", ""),
                "limit": "",
            },
        },
    )


@router.get("/scrobbles", response_class=HTMLResponse)
async def scrobbles_page(request: Request):
    return await _scrobbles_form(request)


@router.post("/scrobbles", response_class=HTMLResponse)
async def scrobbles_fetch(request: Request):

    form = await request.form()
    limit_int = _form_int(form.get("limit"))
    scrobbles_minimum_int = _form_int(form.get("scrobbles_minimum"))
    period_minimum_int = _form_int(form.get("period_minimum"))
    period = _form_int(form.get("period")) or 90
    if period not in PREDEFINED_PERIODS:
        return await _scrobbles_form(
            request, error=f"Period must be one of {', '.join(map(str, PREDEFINED_PERIODS))} days"
        )

    lastfm_cfg = request.app.state.config.get("lastfm", {})
    required_keys = ["api_key", "api_secret", "username", "password_hash"]
    if any(not lastfm_cfg.get(k) for k in required_keys):
        return await _scrobbles_form(request, error="Last.FM not configured")

    # The fetch is a long network operation (rate-limited Last.FM API), so it runs
    # in the jobs executor to keep the event loop responsive, and a running-job
    # guard prevents two concurrent fetches from racing on the state file.
    existing = get_running_job("scrobbles")
    if existing:
        return await _scrobbles_form(request, error="A scrobbles fetch is already in progress")

    job = create_job("scrobbles")

    def _fetch():
        lastfm_client = lastfm.Client(
            api_key=lastfm_cfg["api_key"],
            api_secret=lastfm_cfg["api_secret"],
            username=lastfm_cfg["username"],
            password_hash=lastfm_cfg["password_hash"],
        )
        user = lastfm.User(lastfm_client.client)
        return lastfm.fetch_recent_scrobbles(
            user,
            lastfm_cfg,
            limit=limit_int,
            scrobbles_minimum=scrobbles_minimum_int,
            period=period,
            period_minimum=period_minimum_int,
        )

    await run_job(job, _fetch)

    if job.status == JobStatus.FAILED:
        return await _scrobbles_form(request, error=f"Fetch failed: {job.error}")

    tracks, mode = job.result

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
