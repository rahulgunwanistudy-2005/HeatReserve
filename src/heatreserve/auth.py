"""
Authorization boundary for HeatReserve.

Live mode: API key authentication via X-API-Key header.
           Requests without a valid key receive 401.
           Wrong-tenant access receives 403.

Judge mode: auth-free; all principals operate within the sandbox.

INVARIANT: live mode fails closed on missing/invalid auth.
           Judge Mode remains accessible without production IDP.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

LOGGER = logging.getLogger("heatreserve.auth")

Role = Literal[
    "worker",
    "sponsor_admin",
    "program_operator",
    "auditor",
    "judge",
    "system",
]


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    subject_id: str
    tenant_id: str
    roles: frozenset[str]
    auth_mode: str  # "apikey" | "none" | "judge"

    def has_role(self, role: Role) -> bool:
        return role in self.roles

    def is_judge_sandbox(self) -> bool:
        return self.auth_mode == "judge"

    def can_read_worker(self, worker_id: str) -> bool:
        if "program_operator" in self.roles or "auditor" in self.roles:
            return True
        return "worker" in self.roles and self.subject_id == worker_id

    def can_commit_for_worker(self, worker_id: str, tenant_id: str) -> bool:
        if tenant_id != self.tenant_id and not self.is_judge_sandbox():
            return False
        if "program_operator" in self.roles:
            return True
        return "worker" in self.roles and self.subject_id == worker_id

    def can_read_reserve(self, tenant_id: str) -> bool:
        if tenant_id != self.tenant_id and not self.is_judge_sandbox():
            return False
        return bool(
            {"program_operator", "sponsor_admin", "auditor"} & self.roles
        )

    def can_write_policy(self) -> bool:
        return "program_operator" in self.roles

    def can_run_allocator(self) -> bool:
        return bool({"program_operator", "sponsor_admin"} & self.roles)


JUDGE_CONTEXT = AuthorizationContext(
    subject_id="judge",
    tenant_id="judge-tenant",
    roles=frozenset({"judge", "program_operator"}),
    auth_mode="judge",
)

SYSTEM_CONTEXT = AuthorizationContext(
    subject_id="system",
    tenant_id="system",
    roles=frozenset({"system"}),
    auth_mode="none",
)


class AuthError(ValueError):
    """Raised when authentication/authorization fails."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def authenticate_api_key(
    api_key: str | None,
    valid_keys: frozenset[str],
    tenant_id: str = "default",
) -> AuthorizationContext:
    """
    Authenticate an API key request.
    Fails closed: returns AuthError on any ambiguity.
    """
    if not api_key:
        LOGGER.warning("auth.missing_key tenant=%s", tenant_id)
        raise AuthError("AUTH_REQUIRED", "Authentication required. Provide X-API-Key header.")
    if api_key not in valid_keys:
        LOGGER.warning("auth.invalid_key tenant=%s key_prefix=%s", tenant_id, api_key[:4])
        raise AuthError("AUTH_REQUIRED", "Invalid API key.")
    return AuthorizationContext(
        subject_id=f"apikey:{api_key[:8]}",
        tenant_id=tenant_id,
        roles=frozenset({"program_operator", "worker"}),
        auth_mode="apikey",
    )


def judge_auth() -> AuthorizationContext:
    """Judge Mode auth context — no credentials required."""
    return JUDGE_CONTEXT
