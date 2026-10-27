import csv
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from spotfm import utils
from spotfm.spotify import dupes as spotify_dupes
from spotfm.spotify import misc as spotify_misc
from spotfm.web.jobs import JobStatus, create_job, get_job, get_latest_job, get_running_job, spawn_job
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
    rows = spotify_misc.list_playlists_with_track_counts()
    # rows are (name, pid, count) tuples
    sort_dir = dir if dir in ("asc", "desc") else "asc"
    key = {"name": 0, "count": 2}.get(sort, 0)
    if sort == "count":
        rows = sorted(rows, key=lambda r: r[key] or 0, reverse=(sort_dir == "desc"))
    else:
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
    liked: str = "",
    page: int = Query(default=1, ge=1),
    sort: str = Query(default="name"),
    dir: str = Query(default="asc"),
):
    from spotfm import sqlite
    from spotfm.utils import DATABASE

    all_playlists = sqlite.select_db(DATABASE, "SELECT id, name FROM playlists ORDER BY name COLLATE NOCASE").fetchall()

    start_date = f"{year_start}-01-01" if year_start else None
    end_date = f"{year_end}-12-31" if year_end else None
    if playlist == "none":
        playlist_patterns = spotify_misc.NO_PLAYLIST_PATTERN
    elif playlist:
        playlist_patterns = playlist
    else:
        playlist_patterns = None
    liked_filter = {"liked": True, "not": False}.get(liked)
    raw = spotify_misc.find_tracks_by_criteria(
        playlist_patterns=playlist_patterns,
        start_date=start_date,
        end_date=end_date,
        liked=liked_filter,
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
                "liked": row["liked"],
            }
        )

    has_filters = bool(playlist or artist or album or year_start or year_end or liked)

    # Sort before paginating
    sort_dir = dir if dir in ("asc", "desc") else "asc"
    valid_sorts = {"name", "artists", "album", "year", "liked"}
    sort_key = sort if sort in valid_sorts else "name"

    def _sort_value(row):
        value = row.get(sort_key)
        # liked is a bool: coerce to int so False sorts as 0 instead of ""
        # (an empty str), which cannot be compared with True and would raise
        if isinstance(value, bool):
            return int(value)
        return value or ""

    track_rows.sort(key=_sort_value, reverse=(sort_dir == "desc"))

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
                "liked": liked,
            },
        },
    )


@router.get("/duplicates", response_class=HTMLResponse)
async def duplicates_page(request: Request):
    job = get_latest_job("dupe-names")
    return templates.TemplateResponse(request, "duplicates.html", context={"job": job, "JobStatus": JobStatus})


@router.get("/duplicates/ids", response_class=HTMLResponse)
async def duplicates_ids(
    request: Request,
    page: int = Query(default=1, ge=1),
    sort: str = Query(default="track_name"),
    dir: str = Query(default="asc"),
):
    config = request.app.state.config
    excluded = config.get("spotify", {}).get("excluded_playlists", [])
    dupes = spotify_dupes.find_duplicate_ids(excluded_playlist_ids=excluded)

    sort_dir = dir if dir in ("asc", "desc") else "asc"
    valid_sorts = {"track_name", "artists", "playlists"}
    sort_key = sort if sort in valid_sorts else "track_name"
    dupes.sort(key=lambda r: (r.get(sort_key) or "").lower(), reverse=(sort_dir == "desc"))

    page_dupes, pagination = paginate(dupes, page)
    sort_fn = make_sort_url(request, sort_key, sort_dir)
    ind = lambda col: sort_indicator(sort_key, sort_dir, col)  # noqa: E731
    return templates.TemplateResponse(
        request,
        "duplicates_ids.html",
        context={
            "dupes": page_dupes,
            "pagination": pagination,
            "base_url": pagination_base_url(request),
            "sort_url": sort_fn,
            "ind": ind,
        },
    )


@router.get("/duplicates/names", response_class=HTMLResponse)
async def duplicates_names_results(
    request: Request,
    page: int = Query(default=1, ge=1),
    sort: str = Query(default="score"),
    dir: str = Query(default="desc"),
):
    job = get_latest_job("dupe-names")
    if not job or not job.result:
        return RedirectResponse(url="/duplicates", status_code=302)

    result = list(job.result)
    sort_dir = dir if dir in ("asc", "desc") else "desc"
    valid_sorts = {"track1", "artists1", "track2", "artists2", "score"}
    sort_key = sort if sort in valid_sorts else "score"
    if sort_key == "score":
        result.sort(key=lambda r: r.get("score") or 0, reverse=(sort_dir == "desc"))
    else:
        result.sort(key=lambda r: (r.get(sort_key) or "").lower(), reverse=(sort_dir == "desc"))

    page_result, pagination = paginate(result, page)
    sort_fn = make_sort_url(request, sort_key, sort_dir)
    ind = lambda col: sort_indicator(sort_key, sort_dir, col)  # noqa: E731
    return templates.TemplateResponse(
        request,
        "duplicates_names.html",
        context={
            "pairs": page_result,
            "pagination": pagination,
            "base_url": pagination_base_url(request),
            "sort_url": sort_fn,
            "ind": ind,
        },
    )


@router.post("/duplicates/names")
async def duplicates_names_start(request: Request):
    # Block only if already running; allow re-run when done/failed
    existing = get_running_job("dupe-names")
    if existing:
        return RedirectResponse(url="/duplicates", status_code=302)

    config = request.app.state.config
    excluded = config.get("spotify", {}).get("excluded_playlists", [])
    job = create_job("dupe-names")

    def _find_dupe_names(**kwargs):
        return spotify_dupes.find_duplicate_names(**kwargs)

    spawn_job(job, _find_dupe_names, excluded_playlist_ids=excluded)
    return RedirectResponse(url="/duplicates", status_code=302)


@router.post("/jobs/update-playlists")
async def start_update_playlists(request: Request):
    # Parse the form before the guard: awaiting the body would otherwise let two
    # concurrent requests both pass the check and start duplicate jobs
    form = await request.form()

    existing = get_running_job("update-playlists")
    if existing:
        return RedirectResponse(url=f"/jobs/{existing.id}", status_code=302)

    sp_client = request.app.state.spotify_client
    config = request.app.state.config
    excluded = config.get("spotify", {}).get("excluded_playlists", [])
    pattern = form.get("pattern") or None

    def _update_and_log():
        sp_client.update_playlists(
            excluded_playlists=excluded,
            playlists_patterns=pattern,
            update_liked=config.get("spotify", {}).get("update_liked", True),
        )
        if not pattern:
            spotify_misc.log_track_counts(config)

    job = create_job("update-playlists")
    spawn_job(job, _update_and_log)
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=302)


@router.post("/jobs/update-liked")
async def start_update_liked(request: Request):
    existing = get_running_job("update-liked")
    if existing:
        return RedirectResponse(url=f"/jobs/{existing.id}", status_code=302)

    sp_client = request.app.state.spotify_client
    config = request.app.state.config

    def _update_liked_and_log():
        spotify_misc.update_liked_tracks(sp_client.client)
        spotify_misc.log_track_counts(config)

    job = create_job("update-liked")
    spawn_job(job, _update_liked_and_log)
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=302)


@router.post("/jobs/discover")
async def start_discover(request: Request):
    existing = get_running_job("discover")
    if existing:
        return RedirectResponse(url=f"/jobs/{existing.id}", status_code=302)

    sp_client = request.app.state.spotify_client
    config = request.app.state.config
    spotify_cfg = config.get("spotify", {})
    discover_playlist_id = spotify_cfg.get("discover_playlist", "")
    sources = spotify_cfg.get("sources_playlists", [])

    if not discover_playlist_id or not sources:
        # playlists.html uses the sort/pagination helpers unconditionally, so the
        # error page needs the same context shape as GET /playlists
        empty_rows, pagination = paginate([], 1)
        return templates.TemplateResponse(
            request,
            "playlists.html",
            context={
                "playlists": empty_rows,
                "error": "discover_playlist or sources_playlists not configured",
                "pagination": pagination,
                "base_url": pagination_base_url(request),
                "sort_url": make_sort_url(request, "name", "asc"),
                "ind": lambda col: sort_indicator("name", "asc", col),
            },
            status_code=400,
        )

    job = create_job("discover")
    spawn_job(job, spotify_misc.discover_from_playlists, sp_client, discover_playlist_id, sources)
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=302)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_status(request: Request, job_id: str):
    job = get_job(job_id)
    if job is None:
        return HTMLResponse("<p>Job not found</p>", status_code=404)
    is_htmx = request.headers.get("HX-Request") == "true"
    template = "job_status.html" if is_htmx else "job_page.html"
    return templates.TemplateResponse(request, template, context={"job": job, "JobStatus": JobStatus})


@router.get("/track-counts", response_class=HTMLResponse)
async def track_counts(request: Request, page: int = Query(default=1, ge=1)):
    config = request.app.state.config
    log_path_raw = config.get("spotify", {}).get("track_counts_log", "")
    # log_track_counts() falls back to WORK_DIR when the setting is absent — mirror
    # that default so the page shows the history the update job actually wrote
    log_path = Path(log_path_raw).expanduser() if log_path_raw else utils.WORK_DIR / "track-counts.csv"
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
