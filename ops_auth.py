"""Server-side authorization guards for URA-PROMET revenue operations."""
from fastapi import HTTPException

REVENUE_ROLES = {"revenue_staff", "revenue_admin"}


def require_revenue_user(user: dict) -> dict:
    if user.get("role") not in REVENUE_ROLES:
        raise HTTPException(status_code=403, detail="Revenue role required")
    return user


def require_revenue_admin(user: dict) -> dict:
    if user.get("role") != "revenue_admin":
        raise HTTPException(status_code=403, detail="Revenue Admin role required")
    return user
