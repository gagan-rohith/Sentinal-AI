from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader

from app.container import Container
from auth.permissions import Principal
from auth.rbac import Permission
from core.exceptions import AuthenticationError

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


async def get_principal(
    api_key: str | None = Security(api_key_header),
    container: Container = Depends(get_container),
) -> Principal:
    if not api_key:
        raise AuthenticationError("missing X-API-Key header")
    principal = container.api_keys.authenticate(api_key)
    if principal is None:
        raise AuthenticationError("invalid API key")
    return principal


def require(permission: Permission) -> Callable[..., Coroutine[Any, Any, Principal]]:
    async def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        principal.require(permission)
        return principal

    return dependency
