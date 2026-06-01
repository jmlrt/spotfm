import asyncio
import csv
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from spotfm.spotify import dupes as spotify_dupes
from spotfm.spotify import misc as spotify_misc
from spotfm.web.auth import require_auth
from spotfm.web.jobs import JobStatus, create_job, get_job, get_running_job, run_job

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


@router.get("/playlists", response_class=HTMLResponse)
async def playlists(request: Request):
    redirect = await require_auth(request)
    if redirect:
        return redirect
    rows = spotify_misc.list_playlists_with_track_counts()
    return templates.TemplateResponse(request, "playlists.html", context={"playlists": rows})


@router.get("/tracks", response_class=HTMLResponse)
async def tracks(
    request: Request,
    playlist: str = "",
    artist: str = "",
    album: str = "",
    year_start: str = "",
    year_end: str = "",
):
    redirect = await require_auth(request)
    if redirect:
        return redirect

    from spotfm import sqlite
    from spotfm.utils import DATABASE

    all_playlists = sqlite.select_db(DATABASE, "SELECT id, name FROM playlists ORDER BY name COLLATE NOCASE").fetchall()

    track_rows = []
    if playlist or artist or album or year_start or year_end:
        start_date = f"{year_start}-01-01" if year_start else None
        end_date = f"{year_end}-12-31" if year_end else None
        playlist_patterns = playlist if playlist else "%"
        raw = spotify_misc.find_tracks_by_criteria(
            playlist_patterns=playlist_patterns,
            start_date=start_date,
            end_date=end_date,
        )
        for row in raw:
            track_id, track_name, release_year, album_name, artist_names, *_ = row
            if artist and artist.lower() not in (artist_names or "").lower():
                continue
            if album and album.lower() not in (album_name or "").lower():
                continue
            track_rows.append(
                {
                    "id": track_id,
                    "name": track_name,
                    "year": release_year,
                    "album": album_name,
                    "artists": artist_names,
                }
            )

    return templates.TemplateResponse(
        request,
        "tracks.html",
        context={
            "tracks": track_rows,
            "all_playlists": all_playlists,
            "filters": {
                "playlist": playlist,
                "artist": artist,
                "album": album,
                "year_start": year_start,
                "year_end": year_end,
            },
        },
    )


@router.get("/duplicates", response_class=HTMLResponse)
async def duplicates_page(request: Request):
    redirect = await require_auth(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "duplicates.html", context={"dupes_ids": None, "job": None})


@router.get("/duplicates/ids", response_class=HTMLResponse)
async def duplicates_ids(request: Request):
    redirect = await require_auth(request)
    if redirect:
        return redirect
    config = request.app.state.config
    excluded = config.get("spotify", {}).get("excluded_playlists", [])
    dupes = spotify_dupes.find_duplicate_ids(excluded_playlist_ids=excluded)
    return templates.TemplateResponse(request, "duplicates.html", context={"dupes_ids": dupes, "job": None})


@router.post("/duplicates/names")
async def duplicates_names(request: Request):
    redirect = await require_auth(request)
    if redirect:
        return redirect

    existing = get_running_job("dupe-names")
    if existing:
        return RedirectResponse(url=f"/jobs/{existing.id}", status_code=302)

    config = request.app.state.config
    excluded = config.get("spotify", {}).get("excluded_playlists", [])
    job = create_job("dupe-names")

    asyncio.create_task(run_job(job, spotify_dupes.find_duplicate_names, excluded_playlist_ids=excluded))  # noqa: RUF006
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=302)


@router.post("/jobs/update-playlists")
async def start_update_playlists(request: Request):
    redirect = await require_auth(request)
    if redirect:
        return redirect

    existing = get_running_job("update-playlists")
    if existing:
        return RedirectResponse(url=f"/jobs/{existing.id}", status_code=302)

    form = await request.form()
    sp_client = request.app.state.spotify_client
    config = request.app.state.config
    excluded = config.get("spotify", {}).get("excluded_playlists", [])
    pattern = form.get("pattern") or None

    job = create_job("update-playlists")
    asyncio.create_task(  # noqa: RUF006
        run_job(job, sp_client.update_playlists, excluded_playlists=excluded, playlists_patterns=pattern)
    )
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=302)


@router.post("/jobs/discover")
async def start_discover(request: Request):
    redirect = await require_auth(request)
    if redirect:
        return redirect

    existing = get_running_job("discover")
    if existing:
        return RedirectResponse(url=f"/jobs/{existing.id}", status_code=302)

    sp_client = request.app.state.spotify_client
    config = request.app.state.config
    spotify_cfg = config.get("spotify", {})
    discover_playlist_id = spotify_cfg.get("discover_playlist", "")
    sources = spotify_cfg.get("sources_playlists", [])

    if not discover_playlist_id or not sources:
        return templates.TemplateResponse(
            request,
            "playlists.html",
            context={"playlists": [], "error": "discover_playlist or sources_playlists not configured"},
            status_code=400,
        )

    job = create_job("discover")
    asyncio.create_task(run_job(job, spotify_misc.discover_from_playlists, sp_client, discover_playlist_id, sources))  # noqa: RUF006
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=302)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_status(request: Request, job_id: str):
    redirect = await require_auth(request)
    if redirect:
        return redirect
    job = get_job(job_id)
    if job is None:
        return HTMLResponse("<p>Job not found</p>", status_code=404)
    return templates.TemplateResponse(request, "job_status.html", context={"job": job, "JobStatus": JobStatus})


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
