from enum import StrEnum

from core.enums import Role


class Permission(StrEnum):
    READ_INCIDENTS = "incidents:read"
    READ_REPORTS = "reports:read"
    WRITE_INCIDENTS = "incidents:write"
    READ_TOOLS = "tools:read"
    RUN_ANALYSIS = "analysis:run"
    CREATE_TICKETS = "tickets:create"
    REJECT_REMEDIATION = "remediation:reject"
    RUN_EVALS = "evals:run"
    EXECUTE_REMEDIATION = "remediation:execute"


_VIEWER = frozenset({Permission.READ_INCIDENTS, Permission.READ_REPORTS})
_OPERATOR = _VIEWER | {
    Permission.WRITE_INCIDENTS,
    Permission.READ_TOOLS,
    Permission.RUN_ANALYSIS,
    Permission.CREATE_TICKETS,
    Permission.REJECT_REMEDIATION,
    Permission.RUN_EVALS,
}
_ADMIN = _OPERATOR | {Permission.EXECUTE_REMEDIATION}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: _VIEWER,
    Role.OPERATOR: frozenset(_OPERATOR),
    Role.ADMIN: frozenset(_ADMIN),
}


def role_has(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
