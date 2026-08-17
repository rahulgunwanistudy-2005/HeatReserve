"""Tests for the authorization boundary."""
from __future__ import annotations

import pytest

from heatreserve.auth import (
    AuthError,
    AuthorizationContext,
    authenticate_api_key,
    judge_auth,
)


class TestAuthorizationContext:
    def test_judge_context_is_judge_sandbox(self):
        ctx = judge_auth()
        assert ctx.is_judge_sandbox()
        assert ctx.has_role("judge")
        assert ctx.has_role("program_operator")

    def test_worker_can_read_own_profile(self):
        ctx = AuthorizationContext(
            subject_id="w-001", tenant_id="t-1",
            roles=frozenset({"worker"}), auth_mode="apikey"
        )
        assert ctx.can_read_worker("w-001")
        assert not ctx.can_read_worker("w-002")

    def test_operator_can_read_any_worker(self):
        ctx = AuthorizationContext(
            subject_id="op-1", tenant_id="t-1",
            roles=frozenset({"program_operator"}), auth_mode="apikey"
        )
        assert ctx.can_read_worker("w-001")
        assert ctx.can_read_worker("w-999")

    def test_worker_can_only_commit_for_self(self):
        ctx = AuthorizationContext(
            subject_id="w-001", tenant_id="t-1",
            roles=frozenset({"worker"}), auth_mode="apikey"
        )
        assert ctx.can_commit_for_worker("w-001", "t-1")
        assert not ctx.can_commit_for_worker("w-002", "t-1")

    def test_cross_tenant_commit_denied_for_non_judge(self):
        ctx = AuthorizationContext(
            subject_id="op-1", tenant_id="t-1",
            roles=frozenset({"program_operator"}), auth_mode="apikey"
        )
        assert not ctx.can_commit_for_worker("w-001", "t-2")

    def test_judge_can_commit_cross_tenant(self):
        ctx = judge_auth()
        assert ctx.can_commit_for_worker("any-worker", "any-tenant")

    def test_auditor_cannot_write_policy(self):
        ctx = AuthorizationContext(
            subject_id="auditor-1", tenant_id="t-1",
            roles=frozenset({"auditor"}), auth_mode="apikey"
        )
        assert not ctx.can_write_policy()

    def test_operator_can_write_policy(self):
        ctx = AuthorizationContext(
            subject_id="op-1", tenant_id="t-1",
            roles=frozenset({"program_operator"}), auth_mode="apikey"
        )
        assert ctx.can_write_policy()


class TestApiKeyAuth:
    def test_valid_key_returns_context(self):
        keys = frozenset({"secret-key-123"})
        ctx = authenticate_api_key("secret-key-123", keys)
        assert ctx.auth_mode == "apikey"
        assert ctx.has_role("program_operator")

    def test_missing_key_raises_auth_error(self):
        with pytest.raises(AuthError) as exc:
            authenticate_api_key(None, frozenset({"key"}))
        assert exc.value.code == "AUTH_REQUIRED"

    def test_invalid_key_raises_auth_error(self):
        with pytest.raises(AuthError) as exc:
            authenticate_api_key("wrong-key", frozenset({"right-key"}))
        assert exc.value.code == "AUTH_REQUIRED"

    def test_empty_key_string_raises(self):
        with pytest.raises(AuthError):
            authenticate_api_key("", frozenset({"right-key"}))

    def test_empty_key_set_always_raises(self):
        with pytest.raises(AuthError):
            authenticate_api_key("any-key", frozenset())
