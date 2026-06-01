import asyncio
import contextlib
import csv
import io
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from spotfm.spotify import dupes as spotify_dupes
from spotfm.spotify import misc as spotify_misc
from spotfm.web.auth import require_auth
from spotfm.web.jobs import JobStatus, create_job, get_job, get_latest_job, get_running_job, run_job
from spotfm.web.pagination import make_sort_url, paginate, pagination_base_url, sort_indicator

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


@router.get("/playlists", response_class=HTMLResponse)
async def playlists(
    request: Request,
    page: int = Query(default=1, ge=1),
    sort: str = Query(default="name"),
    dir: str = Query(default="asc"),
):
    redirect = await require_auth(request)
    if redirect:
        return redirect
    rows = spotify_misc.list_playlists_with_track_counts()
    # rows are (name, pid, count) tuples
    sort_dir = dir if dir in ("asc", "desc") else "asc"
    key = {"name": 0, "count": 2}.get(sort, 0)
    rows = sorted(rows, key=lambda r: r[key] or "", reverse=(sort_dir == "desc"))
    page_rows, pagination = paginate(rows, page)
    sort_fn = make_sort_url(request, sort, sort_dir)
    ind = lambda col: sort_indicator(sort, sort_dir, col)  # noqa: E731
    return templates.TemplateResponse(
        request,
        "playlists.html",
        context={
            "playlists": page_rows,
            "pagination": pagination,
            "base_url": pagination_base_url(request),
            "sort_url": sort_fn,
            "ind": ind,
        },
    )


@router.get("/tracks", response_class=HTMLResponse)
async def tracks(
    request: Request,
    playlist: str = "",
    artist: str = "",
    album: str = "",
    year_start: str = "",
    year_end: str = "",
    page: int = Query(default=1, ge=1),
    sort: str = Query(default="name"),
    dir: str = Query(default="asc"),
):
    redirect = await require_auth(request)
    if redirect:
        return redirect

    from spotfm import sqlite
    from spotfm.utils import DATABASE

    all_playlists = sqlite.select_db(DATABASE, "SELECT id, name FROM playlists ORDER BY name COLLATE NOCASE").fetchall()

    start_date = f"{year_start}-01-01" if year_start else None
    end_date = f"{year_end}-12-31" if year_end else None
    playlist_patterns = playlist if playlist else "%"
    raw = spotify_misc.find_tracks_by_criteria(
        playlist_patterns=playlist_patterns,
        start_date=start_date,
        end_date=end_date,
    )
    track_rows = []
    for row in raw:
        artist_names = row["artist_names"]
        album_name = row["album_name"]
        if artist and artist.lower() not in (artist_names or "").lower():
            continue
        if album and album.lower() not in (album_name or "").lower():
            continue
        track_rows.append(
            {
                "id": row["track_id"],
                "name": row["track_name"],
                "year": row["release_year"],
                "album": album_name,
                "artists": artist_names,
            }
        )

    has_filters = bool(playlist or artist or album or year_start or year_end)

    # Sort before paginating
    sort_dir = dir if dir in ("asc", "desc") else "asc"
    valid_sorts = {"name", "artists", "album", "year"}
    sort_key = sort if sort in valid_sorts else "name"
    track_rows.sort(key=lambda r: r.get(sort_key) or "", reverse=(sort_dir == "desc"))

    page_rows, pagination = paginate(track_rows, page)

    # Batch-fetch playlists for just the current page (efficient: 1 query for ≤100 tracks)
    if page_rows:
        ids = [r["id"] for r in page_rows]
        placeholders = ",".join(["?"] * len(ids))
        pl_rows = sqlite.select_db(
            DATABASE,
            f"SELECT pt.track_id, p.id, p.name FROM playlists_tracks pt JOIN playlists p ON pt.playlist_id = p.id WHERE pt.track_id IN ({placeholders}) ORDER BY p.name",
            ids,
        ).fetchall()
        track_playlists: dict[str, list[tuple[str, str]]] = {}
        for tid, pid, pname in pl_rows:
            track_playlists.setdefault(tid, []).append((pid, pname))
        for r in page_rows:
            r["track_playlists"] = track_playlists.get(r["id"], [])

    sort_fn = make_sort_url(request, sort_key, sort_dir)
    ind = lambda col: sort_indicator(sort_key, sort_dir, col)  # noqa: E731

    return templates.TemplateResponse(
        request,
        "tracks.html",
        context={
            "tracks": page_rows,
            "all_playlists": all_playlists,
            "has_filters": has_filters,
            "pagination": pagination,
            "base_url": pagination_base_url(request),
            "sort_url": sort_fn,
            "ind": ind,
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
    job = get_latest_job("dupe-names")
    return templates.TemplateResponse(
        request, "duplicates.html", context={"dupes_ids": None, "job": job, "JobStatus": JobStatus}
    )


@router.get("/duplicates/ids", response_class=HTMLResponse)
async def duplicates_ids(request: Request, page: int = Query(default=1, ge=1)):
    redirect = await require_auth(request)
    if redirect:
        return redirect
    config = request.app.state.config
    excluded = config.get("spotify", {}).get("excluded_playlists", [])
    with contextlib.redirect_stdout(io.StringIO()):
        dupes = spotify_dupes.find_duplicate_ids(excluded_playlist_ids=excluded)
    page_dupes, pagination = paginate(dupes, page)
    return templates.TemplateResponse(
        request,
        "duplicates.html",
        context={
            "dupes_ids": page_dupes,
            "job": None,
            "pagination": pagination,
            "base_url": pagination_base_url(request),
        },
    )


@router.post("/duplicates/names")
async def duplicates_names(request: Request):
    redirect = await require_auth(request)
    if redirect:
        return redirect

    # Block only if already running; allow re-run when done/failed
    existing = get_running_job("dupe-names")
    if existing:
        return RedirectResponse(url="/duplicates", status_code=302)

    config = request.app.state.config
    excluded = config.get("spotify", {}).get("excluded_playlists", [])
    job = create_job("dupe-names")

    def _find_dupe_names(**kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return spotify_dupes.find_duplicate_names(**kwargs)

    asyncio.create_task(run_job(job, _find_dupe_names, excluded_playlist_ids=excluded))  # noqa: RUF006
    return RedirectResponse(url="/duplicates", status_code=302)


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
async def track_counts(request: Request, page: int = Query(default=1, ge=1)):
    redirect = await require_auth(request)
    if redirect:
        return redirect

    config = request.app.state.config
    log_path_raw = config.get("spotify", {}).get("track_counts_log", "")
    if not log_path_raw:
        return templates.TemplateResponse(
            request,
            "track_counts.html",
            context={"headers": [], "rows": [], "error": "track_counts_log not configured"},
        )

    log_path = Path(log_path_raw).expanduser()
    if not log_path.exists():
        return templates.TemplateResponse(
            request,
            "track_counts.html",
            context={"headers": [], "rows": [], "error": f"Log file not found: {log_path}"},
        )

    try:
        with open(log_path, newline="") as f:
            reader = csv.reader(f, delimiter=";")
            all_rows = [row for row in reader if row]
    except OSError as e:
        return templates.TemplateResponse(
            request, "track_counts.html", context={"headers": [], "rows": [], "error": f"Could not read log file: {e}"}
        )

    headers = all_rows[0] if all_rows else []
    sorted_rows = sorted(all_rows[1:], key=lambda r: r[0] if r else "", reverse=True)
    page_rows, pagination = paginate(sorted_rows, page)

    return templates.TemplateResponse(
        request,
        "track_counts.html",
        context={
            "headers": headers,
            "rows": page_rows,
            "error": None,
            "pagination": pagination,
            "base_url": pagination_base_url(request),
        },
    )
