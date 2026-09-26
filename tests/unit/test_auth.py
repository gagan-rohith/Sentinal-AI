import pytest

from auth.api_keys import KEY_PREFIX, ApiKeyAuthenticator, generate_key, hash_key, parse_key_config
from auth.permissions import Principal
from auth.rbac import ROLE_PERMISSIONS, Permission
from core.enums import Role
from core.exceptions import UnauthorizedActionError


def test_generated_keys_are_unique_and_prefixed() -> None:
    a, b = generate_key(), generate_key()
    assert a != b
    assert a.startswith(KEY_PREFIX)


def test_parse_key_config_maps_hash_to_role() -> None:
    digest = hash_key("secret")
    assert parse_key_config(f"admin:{digest}, viewer:{hash_key('other')}") == {
        digest: Role.ADMIN,
        hash_key("other"): Role.VIEWER,
    }
    assert parse_key_config("") == {}


@pytest.mark.parametrize("config", ["admin", "admin:tooshort", f"superuser:{'a' * 64}"])
def test_parse_key_config_rejects_bad_entries(config: str) -> None:
    with pytest.raises(ValueError):  # noqa: PT011
        parse_key_config(config)


def test_authenticator_resolves_role_without_exposing_key() -> None:
    authenticator = ApiKeyAuthenticator({hash_key("secret"): Role.OPERATOR})
    principal = authenticator.authenticate("secret")
    assert principal is not None
    assert principal.role is Role.OPERATOR
    assert "secret" not in principal.subject
    assert authenticator.authenticate("wrong") is None


def test_roles_are_cumulative() -> None:
    assert ROLE_PERMISSIONS[Role.VIEWER] < ROLE_PERMISSIONS[Role.OPERATOR]
    assert ROLE_PERMISSIONS[Role.OPERATOR] < ROLE_PERMISSIONS[Role.ADMIN]


@pytest.mark.parametrize(
    ("role", "permission", "allowed"),
    [
        (Role.VIEWER, Permission.READ_INCIDENTS, True),
        (Role.VIEWER, Permission.READ_REPORTS, True),
        (Role.VIEWER, Permission.READ_TOOLS, False),
        (Role.OPERATOR, Permission.RUN_ANALYSIS, True),
        (Role.OPERATOR, Permission.CREATE_TICKETS, True),
        (Role.OPERATOR, Permission.EXECUTE_REMEDIATION, False),
        (Role.ADMIN, Permission.EXECUTE_REMEDIATION, True),
    ],
)
def test_permission_matrix(role: Role, permission: Permission, allowed: bool) -> None:
    principal = Principal(subject="t", role=role, auth_method="test")
    assert principal.can(permission) is allowed
    if not allowed:
        with pytest.raises(UnauthorizedActionError):
            principal.require(permission)
