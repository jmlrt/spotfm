import hmac

from fastapi import Request
from fastapi.responses import RedirectResponse


def check_api_key(submitted: str, expected: str) -> bool:
    return hmac.compare_digest(submitted, expected)


async def require_auth(request: Request):
    if not request.session.get("authenticated"):
        # Use only path + query, not the full URL (no scheme/host)
        next_path = request.url.path
        if request.url.query:
            next_path += f"?{request.url.query}"
        from urllib.parse import quote

        next_encoded = quote(next_path, safe="/?&=")
        return RedirectResponse(url=f"/login?next={next_encoded}", status_code=302)
    return None
