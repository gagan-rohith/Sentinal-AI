"""API-key authentication for the critic service.

The service is configured with SHA-256 hashes of the keys it accepts (CRITIC_API_KEY_SHA256,
comma separated), never with the keys themselves. Generate a key with:

    python -m critic_service.keys
"""

import hmac
import re

import structlog
from a2a.types import APIKeySecurityScheme, SecurityRequirement, SecurityScheme, StringList
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from auth.api_keys import hash_key

log = structlog.get_logger(__name__)

HEADER = "X-API-Key"
SCHEME = "apiKey"
# Discovery, liveness and metrics stay open, as on the API; JSON-RPC needs a key.
PUBLIC_PATHS = frozenset({AGENT_CARD_WELL_KNOWN_PATH, "/health", "/metrics"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def parse_key_hashes(config: str) -> frozenset[str]:
    hashes = [part.strip().lower() for part in config.split(",") if part.strip()]
    for position, digest in enumerate(hashes, start=1):
        # The message names the position only: the entry may be a pasted secret.
        if not _SHA256.fullmatch(digest):
            raise ValueError(
                f"CRITIC_API_KEY_SHA256 entry {position} is not a SHA-256 hex digest; use the "
                "hash printed by python -m critic_service.keys, not the key"
            )
    if not hashes:
        raise ValueError(
            "CRITIC_API_KEY_SHA256 is not set; the critic service refuses to run without "
            "authentication. Generate a key with python -m critic_service.keys"
        )
    return frozenset(hashes)


def security_fields() -> dict[str, object]:
    """Agent Card fields that tell A2A clients to send the key in the X-API-Key header."""
    scheme = SecurityScheme(
        api_key_security_scheme=APIKeySecurityScheme(
            location="header", name=HEADER, description="SentinelAI critic API key"
        )
    )
    return {
        "security_schemes": {SCHEME: scheme},
        "security_requirements": [SecurityRequirement(schemes={SCHEME: StringList()})],
    }


class ApiKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, key_hashes: frozenset[str]) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.key_hashes = key_hashes

    def _accepts(self, key: str | None) -> bool:
        if not key:
            return False
        digest = hash_key(key)
        # Compare against every hash so timing does not reveal which one matched.
        matches = [hmac.compare_digest(digest, known) for known in self.key_hashes]
        return any(matches)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in PUBLIC_PATHS or self._accepts(request.headers.get(HEADER)):
            return await call_next(request)
        log.warning(
            "critic_request_unauthorized",
            path=request.url.path,
            key_present=HEADER.lower() in request.headers,
        )
        return JSONResponse(
            {"error": {"code": "unauthorized", "message": "missing or invalid API key"}},
            status_code=401,
            headers={"WWW-Authenticate": HEADER},
        )
