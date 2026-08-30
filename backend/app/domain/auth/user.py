"""用户角色与状态的纯业务规则。禁止 IO —— 可脱离数据库单测。"""

STUDENT = "student"
ADMIN = "admin"
ROLES = (STUDENT, ADMIN)

ACTIVE = "active"
DISABLED = "disabled"
STATUSES = (ACTIVE, DISABLED)


def is_admin(role: str) -> bool:
    return role == ADMIN


def can_login(status: str) -> bool:
    return status == ACTIVE
