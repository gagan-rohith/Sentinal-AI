from pydantic import BaseModel

from auth.rbac import Permission, role_has
from core.enums import Role
from core.exceptions import UnauthorizedActionError


class Principal(BaseModel):
    subject: str
    role: Role
    auth_method: str

    def can(self, permission: Permission) -> bool:
        return role_has(self.role, permission)

    def require(self, permission: Permission) -> None:
        if not self.can(permission):
            raise UnauthorizedActionError(
                f"role '{self.role}' is missing permission '{permission}'",
                details={"subject": self.subject, "required": permission.value},
            )
