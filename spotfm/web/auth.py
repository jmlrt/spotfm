import base64
import hmac

from fastapi import Request
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware


def verify_basic_auth(request: Request, api_key: str) -> bool:
    """Check the Authorization header against the configured API key. The username is ignored."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header.removeprefix("Basic ")).decode()
    except ValueError, UnicodeDecodeError:
        return False
    _, _, password = decoded.partition(":")
    # hmac.compare_digest rejects non-ASCII strings, so compare UTF-8 bytes
    return hmac.compare_digest(password.encode(), api_key.encode())


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Protect the whole app with HTTP Basic auth — the browser prompts once and remembers the key."""

    def __init__(self, app, api_key: str):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next):
        if not verify_basic_auth(request, self.api_key):
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="spotfm"'})
        return await call_next(request)
