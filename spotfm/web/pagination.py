from urllib.parse import urlencode

PAGE_SIZE = 100


def page_window(page: int, total_pages: int) -> list[int | None]:
    """Page numbers to show, with None for ellipsis. Shows all if ≤10, else ±4 around current + first/last."""
    if total_pages <= 10:
        return list(range(1, total_pages + 1))
    pages = sorted({1, total_pages, *range(max(1, page - 4), min(total_pages + 1, page + 5))})
    result: list[int | None] = []
    prev = None
    for p in pages:
        if prev is not None and p - prev > 1:
            result.append(None)  # ellipsis marker
        result.append(p)
        prev = p
    return result


def paginate(items: list, page: int) -> tuple[list, dict]:
    total = len(items)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    return items[start : start + PAGE_SIZE], {
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "pages": page_window(page, total_pages),
    }


def pagination_base_url(request) -> str:
    params = {k: v for k, v in request.query_params.items() if k != "page"}
    qs = urlencode(params)
    return f"{request.url.path}?{qs}&" if qs else f"{request.url.path}?"


def make_sort_url(request, current_sort: str, current_dir: str):
    """Return a callable `f(col)` that builds a sort URL for the given column."""

    def _url(col: str) -> str:
        new_dir = "desc" if current_sort == col and current_dir == "asc" else "asc"
        params = {k: v for k, v in request.query_params.items() if k not in ("page", "sort", "dir")}
        params["sort"] = col
        params["dir"] = new_dir
        return f"{request.url.path}?{urlencode(params)}"

    return _url


def sort_indicator(current_sort: str, current_dir: str, col: str) -> str:
    if current_sort != col:
        return ""
    return " ↓" if current_dir == "desc" else " ↑"
