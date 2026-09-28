"""Caller identity for MCP requests.

Over streamable HTTP the key comes from each request's `X-API-Key` header (or an
`Authorization: Bearer` header). Over stdio there are no headers, so the key is read
from the SENTINEL_API_KEY environment variable that the MCP client sets when it
launches the server.
"""

from collections.abc import Mapping

from auth.api_keys import ApiKeyAuthenticator
from auth.permissions import Principal
from core.exceptions import AuthenticationError

ENV_API_KEY = "SENTINEL_API_KEY"


def extract_key(headers: Mapping[str, str] | None, env: Mapping[str, str]) -> str | None:
    if headers is None:
        return env.get(ENV_API_KEY) or None
    lowered = {k.lower(): v for k, v in headers.items()}
    if lowered.get("x-api-key"):
        return lowered["x-api-key"]
    scheme, _, token = lowered.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token:
        return token.strip()
    return None


def resolve_principal(
    authenticator: ApiKeyAuthenticator,
    headers: Mapping[str, str] | None,
    env: Mapping[str, str],
) -> Principal:
    key = extract_key(headers, env)
    if not key:
        where = f"the {ENV_API_KEY} environment variable" if headers is None else "X-API-Key"
        raise AuthenticationError(f"no API key provided; set {where}")
    principal = authenticator.authenticate(key)
    if principal is None:
        raise AuthenticationError("invalid API key")
    return principal.model_copy(update={"auth_method": f"mcp:{principal.auth_method}"})
