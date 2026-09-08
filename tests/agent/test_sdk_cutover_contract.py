"""Offline SDK cutover contracts using real SDK messages/session/runtime.

Only authentication and the client transport are fixtures. No provider call,
credential lookup, or live gateway is needed to exercise the installed plugin.
"""
import asyncio
import socket
import subprocess
from types import SimpleNamespace
from typing import Any, cast

import claude_agent_sdk as sdk
import pytest

from agent.runtime_api import RuntimeContentEvent, RuntimeIterationEvent, runtime_api_manifest
from agent.runtime_dispatch import (
    HermesRuntimeHostServices, _collect_runtime_turn, build_runtime_turn_request,
)
from hermes_claude_agent_sdk.compatibility import build_runtime_descriptor, doctor
from hermes_claude_agent_sdk.configuration import SDKSessionConfiguration
from hermes_claude_agent_sdk.content_events import ClaudeSdkEventProjector
from hermes_claude_agent_sdk.runtime import ClaudeAgentSDKRuntime

MODEL = "claude-fable-5-1"


@pytest.fixture(autouse=True)
def forbid_external_transport(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("offline SDK contract attempted external transport")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


def _start(message_id, parent=None, uuid="stream-envelope", **extra):
    return sdk.StreamEvent(
        uuid=uuid, session_id="fixture-session", parent_tool_use_id=parent,
        event={"type": "message_start", "message": {"id": message_id, **extra}},
    )


def _assistant(message_id=None, *, model=MODEL, error=None, parent=None, content=None):
    return sdk.AssistantMessage(
        content=content if content is not None else [sdk.TextBlock(text="commentary")],
        model=model, message_id=message_id, error=error, parent_tool_use_id=parent,
    )


def _result(turns, failed=False):
    return sdk.ResultMessage(
        subtype="error_during_execution" if failed else "success",
        duration_ms=1, duration_api_ms=1, is_error=failed, num_turns=turns,
        session_id="", result=None if failed else "complete", total_cost_usd=0.0,
    )


def _counts(projector, message):
    return [event.iteration for event in projector.project(message).events
            if isinstance(event, RuntimeIterationEvent)]


def test_options_keep_required_timeout_and_enable_early_message_boundaries(tmp_path):
    config = SDKSessionConfiguration.create(cwd=str(tmp_path), parent_env={})
    options = sdk.ClaudeAgentOptions(**cast(dict[str, Any], config.option_fields()))
    assert config.turn_timeout_seconds == 14400.0
    assert (config.connect_timeout_seconds, config.close_timeout_seconds) == (60.0, 15.0)
    assert options.include_partial_messages is True
    assert options.tools == []
    assert options.setting_sources == []


def test_descriptor_rejects_a_host_without_iteration_progress():
    manifest = runtime_api_manifest()
    assert "iteration_progress_v1" in build_runtime_descriptor().required_host_capabilities
    assert doctor(manifest)["compatible"] is True
    missing = dict(manifest, host_capabilities=[
        c for c in manifest["host_capabilities"] if c != "iteration_progress_v1"
    ])
    assert doctor(missing)["compatible"] is False


def test_count_root_responses_not_envelopes_chunks_nested_frames_or_tools():
    projector = ClaudeSdkEventProjector(model=MODEL)
    assert _counts(projector, _start("root-1")) == [1]
    assert _counts(projector, _start("root-1", uuid="other-envelope")) == []
    for kind, body in [("text_delta", {"text": "not emitted twice"}),
                       ("thinking_delta", {"thinking": "not visible"})]:
        chunk = sdk.StreamEvent(uuid="chunk", session_id="fixture-session", event={
            "type": "content_block_delta", "index": 0, "delta": {"type": kind, **body},
        })
        assert list(projector.project(chunk).events) == []
    assert _counts(projector, _assistant("root-1")) == []
    assert _counts(projector, _start("nested-1", parent="tool-parent")) == []
    assert _counts(projector, _assistant("nested-2", parent="tool-parent")) == []
    tools = [sdk.ToolUseBlock(id=f"tool-{i}", name="mcp__hermes-tools__read_file", input={})
             for i in range(3)]
    assert _counts(projector, _assistant("root-2", content=tools[:2])) == [2]
    assert _counts(projector, _assistant("root-2", content=tools[2:])) == []
    assert _counts(projector, sdk.UserMessage(content=[
        sdk.ToolResultBlock(tool_use_id="tool-1", content="fixture result"),
    ])) == []
    for invalid in (None, "", 1, True, "x" * 129):
        assert _counts(projector, _start(invalid)) == []
    assert _counts(projector, _assistant()) == []
    assert projector.api_call_count == 2
    projector.begin_turn()
    assert projector.api_call_count == 0
    assert _counts(projector, _start("root-1")) == [1]


@pytest.mark.parametrize("model,error", [
    ("<synthetic>", None), ("synthetic", None), ("claude-fable-synthetic", None),
    (MODEL, "authentication_failed"),
])
@pytest.mark.parametrize("streamed", [False, True])
def test_synthetic_and_error_frames_emit_neither_progress_nor_commentary(model, error, streamed):
    projector = ClaudeSdkEventProjector(model=MODEL)
    message = (_start("synthetic-id", model=model, error=error) if streamed
               else _assistant("synthetic-id", model=model, error=error))
    events = projector.project(message).events
    assert not [e for e in events if isinstance(e, (RuntimeIterationEvent, RuntimeContentEvent))]
    assert projector.api_call_count == 0


@pytest.mark.parametrize("turns", [0, -1, True, 2.5, "3", None])
def test_invalid_terminal_counts_are_not_invented(turns):
    projector = ClaudeSdkEventProjector(model=MODEL)
    projector.project(_result(turns))
    assert projector.api_call_count == 0


@pytest.mark.parametrize("turns", [1, 99])
def test_observed_response_ids_take_precedence_over_terminal_count(turns):
    projector = ClaudeSdkEventProjector(model=MODEL)
    projector.project(_start("a"))
    projector.project(_start("b"))
    projector.project(_result(turns))
    assert projector.api_call_count == 2


def test_idless_terminal_fallback_is_successful_only_and_does_not_emit_progress():
    projector = ClaudeSdkEventProjector(model=MODEL)
    assert _counts(projector, _result(3)) == []
    assert projector.api_call_count == 3
    projector.begin_turn()
    assert projector.api_call_count == 0
    assert _counts(projector, _result(9, failed=True)) == []
    assert projector.api_call_count == 0


class _Client:
    def __init__(self, *, options, frames):
        self.options = sdk.ClaudeAgentOptions(**options)
        self.frames = frames
        self.queue = asyncio.Queue()

    async def connect(self):
        pass

    async def query(self, prompt):
        for frame in self.frames:
            self.queue.put_nowait(frame)

    async def receive_messages(self):
        while True:
            yield await self.queue.get()

    async def interrupt(self):
        pass

    async def disconnect(self):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("case,turns,expected_count,expected_progress", [
    ("ids", 1, 2, [1, 2]), ("ids", 99, 2, [1, 2]),
    ("no_ids", 3, 3, []), ("no_evidence", 0, 0, []),
])
async def test_actual_runtime_returns_projector_count_and_preserves_display_only_progress(
    tmp_path, case, turns, expected_count, expected_progress,
):
    frames = [sdk.SystemMessage(subtype="init", data={"apiKeySource": "none", "model": MODEL})]
    if case == "ids":
        frames += [_start("one"), _assistant("one"), _start("two"), _assistant("two")]
    elif case == "no_ids":
        frames.append(_assistant())
    frames.append(_result(turns))
    clients = []

    def factory(*, options):
        client = _Client(options=options, frames=frames)
        clients.append(client)
        return client

    agent = SimpleNamespace(
        session_id="fixture-host", _api_call_count=0, _touch_activity=lambda *a, **kw: None,
        tools=(), valid_tool_names=(), _fire_stream_delta=lambda text: None,
    )
    host = HermesRuntimeHostServices(agent, task_id="test", runtime_id="hermes-claude-agent-sdk")
    runtime = ClaudeAgentSDKRuntime(
        auth_probe=lambda: SimpleNamespace(allowed=True, category="subscription_oauth"),
        sdk_module=sdk, client_factory=factory, cwd=str(tmp_path), parent_env={},
    )
    request = build_runtime_turn_request(
        provider="claude-agent-sdk", model=MODEL, api_mode="agent_runtime",
        messages=({"role": "user", "content": "offline fixtures"},),
        prompt_snapshot="constant offline system prompt", tool_schemas=(), correlation_id=case,
    )
    try:
        outcome = await asyncio.wait_for(_collect_runtime_turn(runtime, request, host), timeout=10)
        assert outcome.completed, outcome.failure
        assert outcome.response is not None
        assert outcome.response["api_calls"] == expected_count
        assert [e.iteration for e in outcome.events if isinstance(e, RuntimeIterationEvent)] == expected_progress
        assert agent._api_call_count == max(expected_progress, default=0)
        assert runtime._session_configuration is not None
        assert runtime._session_configuration.turn_timeout_seconds == 14400.0
        assert clients[0].options.include_partial_messages is True
    finally:
        await runtime.close()
