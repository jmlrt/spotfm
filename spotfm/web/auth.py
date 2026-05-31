import hashlib
import hmac

from fastapi import Request
from fastapi.responses import RedirectResponse


def check_api_key(submitted: str, expected: str) -> bool:
    submitted_hash = hashlib.sha256(submitted.encode()).digest()
    expected_hash = hashlib.sha256(expected.encode()).digest()
    return hmac.compare_digest(submitted_hash, expected_hash)


async def require_auth(request: Request):
    if not request.session.get("authenticated"):
        next_url = str(request.url)
        return RedirectResponse(url=f"/login?next={next_url}", status_code=302)
    return None
