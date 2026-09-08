"""Turn-scoped provider fallback for external whole-turn runtimes (agent/turn_runtime.py)."""

from types import SimpleNamespace

import pytest

from agent import turn_runtime
from agent.chat_completion_helpers import _apply_fallback_request_overrides
from agent.error_classifier import FailoverReason
from agent.runtime_api import RuntimeFailure, RuntimeFailurePhase


def _registration(plugin_id="external-plugin"):
    return SimpleNamespace(plugin_id=plugin_id, descriptor=SimpleNamespace(runtime_id="rt-test"))


def _failure(phase, code="sdk_api_rate_limit_429"):
    return RuntimeFailure(code=code, message="boom", phase=phase, replay_safe=False, retryable=True)


class _Agent:
    def __init__(self, *, pending=True, activate=True):
        self.model, self.provider = "primary-model", "primary-provider"
        self._fallback_activated = False
        self._pending = pending
        self._activate = activate
        self.activation_reasons = []
        self._runtime_descriptor = object()
        self._runtime_compaction_ownership = "runtime_native"

    def _has_pending_fallback(self):
        return self._pending

    def _try_activate_fallback(self, reason=None):
        self.activation_reasons.append(reason)
        if self._activate:
            self._fallback_activated = True
            self.model, self.provider = "fb-model", "fb-provider"
        return self._activate


@pytest.mark.parametrize(
    "phase", [RuntimeFailurePhase.PREFLIGHT, RuntimeFailurePhase.BEFORE_VISIBLE_OUTPUT]
)
def test_fallback_activates_when_nothing_was_shown(phase):
    agent = _Agent()
    assert turn_runtime._try_runtime_fallback(agent, _registration(), _failure(phase)) is True
    assert agent.activation_reasons == [FailoverReason.rate_limit]
    assert (agent.model, agent.provider) == ("fb-model", "fb-provider")
    # The built-in loop owns compaction for the rest of the turn.
    assert agent._runtime_descriptor is None
    assert agent._runtime_compaction_ownership is None


@pytest.mark.parametrize(
    "phase", [RuntimeFailurePhase.AFTER_VISIBLE_OUTPUT, RuntimeFailurePhase.AFTER_SIDE_EFFECTS]
)
def test_no_fallback_after_visible_output_or_side_effects(phase):
    agent = _Agent()
    assert turn_runtime._try_runtime_fallback(agent, _registration(), _failure(phase)) is False
    assert agent.activation_reasons == []
    assert agent._runtime_descriptor is not None


def test_builtin_codex_runtime_keeps_its_own_failure_path():
    agent = _Agent()
    failure = _failure(RuntimeFailurePhase.PREFLIGHT)
    assert turn_runtime._try_runtime_fallback(agent, _registration("hermes-core"), failure) is False
    assert agent.activation_reasons == []


def test_no_chain_or_failed_activation_leaves_the_failure_alone():
    failure = _failure(RuntimeFailurePhase.PREFLIGHT)
    assert turn_runtime._try_runtime_fallback(_Agent(pending=False), _registration(), failure) is False
    agent = _Agent(activate=False)
    assert turn_runtime._try_runtime_fallback(agent, _registration(), failure) is False
    assert agent._runtime_descriptor is not None


def test_already_active_fallback_is_not_reactivated():
    agent = _Agent()
    agent._fallback_activated = True
    failure = _failure(RuntimeFailurePhase.PREFLIGHT)
    assert turn_runtime._try_runtime_fallback(agent, _registration(), failure) is False
    assert agent.activation_reasons == []


def test_missing_failure_is_not_a_fallback():
    agent = _Agent()
    assert turn_runtime._try_runtime_fallback(agent, _registration(), None) is False


@pytest.mark.parametrize(
    "code, reason",
    [
        ("sdk_api_rate_limit_429", FailoverReason.rate_limit),
        ("sdk_api_auth_401", FailoverReason.auth),
        ("claude_subscription_auth_rejected", FailoverReason.auth),
        ("claude_subscription_billing_blocked", FailoverReason.billing),
        ("sdk_api_overloaded_529", FailoverReason.overloaded),
        ("sdk_api_server_error_500", FailoverReason.server_error),
        ("sdk_api_timeout_408", FailoverReason.timeout),
        ("claude_runtime_selection_unsupported", None),
    ],
)
def test_failure_codes_map_to_failover_reasons(code, reason):
    assert turn_runtime._failover_reason_for(_failure(RuntimeFailurePhase.PREFLIGHT, code)) is reason


def test_entry_request_overrides_merge_over_agent_overrides():
    agent = SimpleNamespace(request_overrides={"extra_body": {"k": 1}, "reasoning": {"effort": "high"}})
    entry = {"provider": "openai-codex", "model": "m", "request_overrides": {"reasoning": {"effort": "max"}}}
    _apply_fallback_request_overrides(agent, entry)
    assert agent.request_overrides == {"extra_body": {"k": 1}, "reasoning": {"effort": "max"}}
    # The agent owns a copy: mutating it must not leak back into the chain entry.
    agent.request_overrides["reasoning"]["effort"] = "low"
    assert entry["request_overrides"]["reasoning"]["effort"] == "max"


def test_entry_without_overrides_is_a_no_op():
    agent = SimpleNamespace(request_overrides={"reasoning": {"effort": "high"}})
    _apply_fallback_request_overrides(agent, {"provider": "p", "model": "m"})
    assert agent.request_overrides == {"reasoning": {"effort": "high"}}
