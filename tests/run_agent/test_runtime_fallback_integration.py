"""A whole-turn runtime that fails before visible output hands the turn to ``fallback_providers``.

Runs through the real ``AIAgent`` seam: plugin runtime registration, ``run_conversation``,
the shared ``try_activate_fallback`` swap, the built-in loop on the fallback wire, and the
turn-start primary restore that must happen BEFORE runtime resolution on the next turn.
"""

from __future__ import annotations

import asyncio
import socket
import subprocess
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import run_agent

from agent.runtime_api import (
    RUNTIME_API_VERSION,
    RuntimeCompletedEvent,
    RuntimeDescriptor,
    RuntimeFailure,
    RuntimeFailurePhase,
)
from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest


@pytest.fixture(autouse=True)
def no_environment_probe(monkeypatch):
    # No unrelated background subprocess may outlive a test's transport guard.
    monkeypatch.setattr("tools.env_probe.warm_environment_probe_async", lambda: None)
    monkeypatch.setattr("tools.env_probe.get_environment_probe_line", lambda **kw: "")


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
        if agent.api_mode == "codex_responses":
            return SimpleNamespace(
                id="offline-response", model=agent.model, status="completed", usage=None,
                output=[SimpleNamespace(
                    type="message", role="assistant", phase="final_answer",
                    content=[SimpleNamespace(type="output_text", text="fallback reply")],
                )],
            )
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


@pytest.mark.parametrize("status", [401, 402, 429])
@pytest.mark.parametrize("usage,cost,visible,fallback", [
    ({"input_tokens": 0, "output_tokens": 0}, 0, False, True),
    ({"input_tokens": 0.0, "output_tokens": 0.0}, 0.0, False, True),
    ({"input_tokens": 0, "output_tokens": 0}, None, False, True),
    ({"input_tokens": 1, "output_tokens": 0}, 0, False, False),
    ({"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 1}, 0, False, False),
    ({"input_tokens": "0", "output_tokens": 0}, 0, False, False),
    ({"input_tokens": 0}, 0, False, False),
    ({"input_tokens": 0, "output_tokens": 0}, 0.01, False, False),
    ({"input_tokens": 0, "output_tokens": 0}, 0, True, False),
])
def test_real_sdk_receipt_controls_astra_fallback_and_primary_restoration(
    monkeypatch, tmp_path, usage, cost, visible, fallback, status,
):
    import claude_agent_sdk as sdk
    import hermes_cli.plugins as plugins_module
    from agent import auxiliary_client
    from hermes_claude_agent_sdk.compatibility import build_runtime_descriptor
    from hermes_claude_agent_sdk.runtime import ClaudeAgentSDKRuntime
    from hermes_state import SessionDB
    from tools import tool_search

    def forbidden(*args, **kwargs):
        pytest.fail("offline fallback regression attempted external transport")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    # Metadata and title generation are unrelated I/O leaves, not fallback decisions.
    monkeypatch.setattr("tools.env_probe._build_probe_line", lambda: "")
    monkeypatch.setattr("agent.title_generator.generate_title", lambda *a, **kw: ("offline", "test"))
    monkeypatch.setattr("agent.model_metadata._fetch_codex_oauth_context_lengths_with_source", lambda *a: ({}, False))
    monkeypatch.setattr(tool_search, "load_config", lambda: tool_search.ToolSearchConfig.from_raw({"enabled": "off"}))
    counts = {"sdk_queries": 0, "fallback_clients": 0}

    class Client:
        def __init__(self, *, options):
            self.options = sdk.ClaudeAgentOptions(**options)
            self.queue = asyncio.Queue()

        async def connect(self):
            pass

        async def query(self, prompt):
            counts["sdk_queries"] += 1
            failed = counts["sdk_queries"] == 1
            self.queue.put_nowait(sdk.SystemMessage(subtype="init", data={"apiKeySource": "none"}))
            if visible and failed:
                self.queue.put_nowait(sdk.AssistantMessage(
                    content=[sdk.TextBlock(text="already visible")], model="claude-fable-5-1",
                ))
            self.queue.put_nowait(sdk.ResultMessage(
                subtype="success", duration_ms=0, duration_api_ms=0, is_error=failed,
                num_turns=0 if failed else 1, session_id="", api_error_status=status if failed else None,
                usage=usage if failed else None, total_cost_usd=cost if failed else None,
                result=None if failed else "restored SDK reply",
            ))

        async def receive_messages(self):
            while True:
                yield await self.queue.get()

        async def interrupt(self):
            pass

        async def disconnect(self):
            pass

    manager = PluginManager()
    manager._discovered = True
    context = PluginContext(PluginManifest(name="offline-sdk-fallback"), manager)
    context.register_agent_runtime(
        descriptor=build_runtime_descriptor(),
        factory=lambda: ClaudeAgentSDKRuntime(
            auth_probe=lambda: SimpleNamespace(allowed=True, category="subscription_oauth"),
            sdk_module=sdk, client_factory=Client, cwd=str(tmp_path), parent_env={},
        ),
    )
    monkeypatch.setattr(plugins_module, "_plugin_manager", manager)

    def fallback_client(provider, **kwargs):
        assert provider == "openai-codex"
        assert kwargs["model"] == "gpt-6-astra"
        assert kwargs["api_mode"] == "codex_responses"
        counts["fallback_clients"] += 1
        return SimpleNamespace(
            base_url="https://chatgpt.com/backend-api/codex", api_key="offline-token",
            close=lambda: None,
        ), kwargs["model"]

    monkeypatch.setattr(auxiliary_client, "resolve_provider_client", fallback_client)
    db = SessionDB(db_path=tmp_path / "fallback.db")
    agent = run_agent.AIAgent(
        api_key="", provider="claude-agent-sdk", model="claude-fable-5-1",
        api_mode="agent_runtime", base_url="runtime://claude-agent-sdk",
        fallback_model=[{
            "provider": "openai-codex", "model": "gpt-6-astra", "api_mode": "codex_responses",
            "request_overrides": {"reasoning": {"effort": "max"}},
        }],
        quiet_mode=True, skip_context_files=True, skip_memory=True, enabled_toolsets=[],
        session_id="sdk-fallback", session_db=db,
    )
    agent._cached_system_prompt = "constant offline prompt"
    agent.compression_enabled = False
    agent.save_trajectories = False
    agent._disable_streaming = True
    try:
        result, seen = _run_on_fallback(agent, "hello")
        receipts = db.list_runtime_usage_receipts(agent.session_id)
        assert counts["sdk_queries"] == 1
        assert counts["fallback_clients"] == int(fallback)
        assert len(seen) == int(fallback)
        assert agent._fallback_activated is fallback
        if fallback:
            assert result["final_response"] == "fallback reply"
            assert receipts == []
            assert (agent.model, agent.provider, agent.api_mode) == ("gpt-6-astra", "openai-codex", "codex_responses")
            assert agent.request_overrides["reasoning"] == {"effort": "max"}
            # Expire the genuine rate-limit cooldown without sleeping or changing routing.
            agent._rate_limited_until = 0
            second, next_seen = _run_on_fallback(agent, "again")
            assert second["final_response"] == "restored SDK reply"
            assert next_seen == []
            assert counts == {"sdk_queries": 2, "fallback_clients": 1}
            assert (agent.model, agent.provider, agent.api_mode) == ("claude-fable-5-1", "claude-agent-sdk", "agent_runtime")
            assert agent._fallback_activated is False
            assert agent.client is None and agent._anthropic_client is None
            assert agent.request_overrides.get("reasoning") is None
        else:
            assert result["failed"] is True
            expected = RuntimeFailurePhase.AFTER_VISIBLE_OUTPUT if visible else RuntimeFailurePhase.AFTER_SIDE_EFFECTS
            assert result["failure"].phase is expected
            assert len(receipts) == (0 if visible else 1)
    finally:
        agent.release_clients()
        manager.unload("offline-sdk-fallback")
        db.close()
