"""A whole-turn runtime that fails before visible output hands the turn to ``fallback_providers``.

Runs through the real ``AIAgent`` seam: plugin runtime registration, ``run_conversation``,
the shared ``try_activate_fallback`` swap, the built-in loop on the fallback wire, and the
turn-start primary restore that must happen BEFORE runtime resolution on the next turn.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch

import run_agent

from agent.runtime_api import (
    RUNTIME_API_VERSION,
    RuntimeCompletedEvent,
    RuntimeDescriptor,
    RuntimeFailure,
    RuntimeFailurePhase,
)
from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest


def _mock_response(content, finish_reason="stop"):
    msg = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(message=msg, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], model="fb-model", usage=None)


class _FlakyRuntime:
    """Fails preflight with ``counters['fail_code']`` while set; completes otherwise."""

    def __init__(self, counters):
        self._counters = counters

    def preflight(self, request):
        self._counters["preflight"] += 1
        code = self._counters["fail_code"]
        if code:
            return RuntimeFailure(
                code=code,
                message="runtime unavailable",
                phase=RuntimeFailurePhase.PREFLIGHT,
                replay_safe=True,
                retryable=True,
            )
        return None

    async def run_turn(self, request, host):
        self._counters["turn"] += 1
        yield RuntimeCompletedEvent(
            result={
                "final_response": "external runtime reply",
                "messages": list(request.messages),
                "completed": True,
                "partial": False,
                "error": None,
            }
        )

    async def close(self):
        self._counters["close"] += 1


def _register_runtime(monkeypatch, counters):
    from tools import tool_search

    monkeypatch.setattr(
        tool_search,
        "load_config",
        lambda: tool_search.ToolSearchConfig.from_raw({"enabled": "off"}),
    )
    manager = PluginManager()
    manager._discovered = True
    context = PluginContext(PluginManifest(name="external-runtime"), manager)
    context.register_agent_runtime(
        descriptor=RuntimeDescriptor(
            runtime_id="external-flaky-runtime",
            plugin_version="0.1.0",
            runtime_api_min=RUNTIME_API_VERSION,
            runtime_api_max=RUNTIME_API_VERSION,
            required_host_capabilities=frozenset({"cancellation_v1"}),
            provider_ids=frozenset({"openai"}),
            api_modes=frozenset({"chat_completions"}),
            session_state_schema_version=1,
        ),
        factory=lambda: _FlakyRuntime(counters),
    )
    import hermes_cli.plugins as plugins_module

    monkeypatch.setattr(plugins_module, "_plugin_manager", manager)


def _make_agent(fallback_chain):
    agent = run_agent.AIAgent(
        api_key="primary-key",
        base_url="https://test.invalid",
        provider="openai",
        model="synthetic-model",
        api_mode="chat_completions",
        fallback_model=fallback_chain,
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    agent._cached_system_prompt = "composed synthetic prompt"
    agent.compression_enabled = False
    agent.save_trajectories = False
    # Keep the built-in loop on the non-streaming call so the stub below is the wire.
    agent._disable_streaming = True
    return agent


# The documented custom-endpoint fallback shape (provider: custom + base_url + inline key).
_FALLBACK_ENTRY = {
    "provider": "custom",
    "model": "fb-model",
    "base_url": "https://fallback.invalid/v1",
    "api_key": "fb-key",
    "api_mode": "chat_completions",
    "request_overrides": {"reasoning": {"effort": "max"}},
}


def _run_on_fallback(agent, prompt):
    seen = []

    def _fake_api_call(api_kwargs):
        seen.append(dict(api_kwargs))
        return _mock_response("fallback reply")

    with patch.object(agent, "_interruptible_api_call", side_effect=_fake_api_call):
        result = agent.run_conversation(prompt)
    return result, seen


def test_runtime_failure_before_output_finishes_the_turn_on_the_fallback_provider(monkeypatch):
    counters = {"preflight": 0, "turn": 0, "close": 0, "fail_code": "sdk_api_server_error_500"}
    _register_runtime(monkeypatch, counters)
    agent = _make_agent([dict(_FALLBACK_ENTRY)])

    result, seen = _run_on_fallback(agent, "hello")

    # The runtime never produced output; the same turn completed on the fallback wire.
    assert counters["preflight"] == 1
    assert counters["turn"] == 0
    assert result["final_response"] == "fallback reply"
    assert result.get("failed") is not True
    assert agent._fallback_activated is True
    assert (agent.model, agent.provider) == ("fb-model", "custom")
    assert seen and seen[0]["model"] == "fb-model"
    # The entry's request_overrides travel with the fallback (literal effort for Codex-style wires).
    assert agent.request_overrides["reasoning"] == {"effort": "max"}
    # A server error is not a rate limit: no primary cooldown.
    assert getattr(agent, "_rate_limited_until", 0) <= time.monotonic()

    # Next turn: the primary is restored BEFORE runtime resolution, so the runtime serves again
    # and the fallback-only overrides are gone.
    counters["fail_code"] = None
    second = agent.run_conversation("again")
    assert second["final_response"] == "external runtime reply"
    assert counters["turn"] == 1
    assert agent._fallback_activated is False
    assert (agent.model, agent.provider) == ("synthetic-model", "openai")
    assert agent.request_overrides.get("reasoning") is None
    agent.release_clients()


def test_runtime_rate_limit_arms_the_primary_cooldown(monkeypatch):
    counters = {"preflight": 0, "turn": 0, "close": 0, "fail_code": "sdk_api_rate_limit_429"}
    _register_runtime(monkeypatch, counters)
    agent = _make_agent([dict(_FALLBACK_ENTRY)])

    result, _ = _run_on_fallback(agent, "hello")
    assert result["final_response"] == "fallback reply"
    assert agent._rate_limited_until > time.monotonic()

    # While the cooldown holds, the next turn stays on the fallback without re-probing the runtime.
    counters["fail_code"] = None
    second, _ = _run_on_fallback(agent, "again")
    assert second["final_response"] == "fallback reply"
    assert counters["preflight"] == 1
    assert counters["turn"] == 0
    assert agent._fallback_activated is True
    agent.release_clients()


def test_runtime_failure_without_a_chain_still_fails_the_turn(monkeypatch):
    counters = {"preflight": 0, "turn": 0, "close": 0, "fail_code": "sdk_api_rate_limit_429"}
    _register_runtime(monkeypatch, counters)
    agent = _make_agent([])

    result = agent.run_conversation("hello")

    assert counters["preflight"] == 1
    assert result.get("failed") is True
    assert result["failure"].code == "sdk_api_rate_limit_429"
    assert agent._fallback_activated is False
    agent.release_clients()
