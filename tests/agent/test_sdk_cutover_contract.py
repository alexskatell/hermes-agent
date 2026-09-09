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

from agent.runtime_api import (
    RuntimeContentEvent, RuntimeFailurePhase, RuntimeIterationEvent,
    RuntimeUsageEvent, runtime_api_manifest,
)
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


_ABSENT = object()
_ZERO_USAGE = {"input_tokens": 0, "output_tokens": 0}
_OPTIONAL_COUNTERS = (
    "cache_read_input_tokens", "cache_read_tokens", "cache_creation_input_tokens",
    "cache_write_tokens", "reasoning_tokens",
)


def _usage_result(usage, cost=0, *, failed=True, model_usage=None):
    result = sdk.ResultMessage(
        subtype="success", duration_ms=0, duration_api_ms=0, is_error=failed,
        num_turns=0, session_id="", usage=usage, model_usage=model_usage,
        api_error_status=429 if failed else None, result=None if failed else "complete",
    )
    if cost is not _ABSENT:
        result.total_cost_usd = cost
    return result


@pytest.fixture
def accounting_host(tmp_path):
    from hermes_state import SessionDB

    db = SessionDB(db_path=tmp_path / "accounting.db")
    db.create_session("sdk-accounting", source="test", model=MODEL)
    agent = SimpleNamespace(
        session_id="sdk-accounting", _session_db=db, _api_call_count=0,
        _touch_activity=lambda *a, **kw: None, tools=(), valid_tool_names=(),
        _fire_stream_delta=lambda text: None,
    )
    host = HermesRuntimeHostServices(agent, task_id="accounting", runtime_id="hermes-claude-agent-sdk")
    try:
        yield agent, host, db
    finally:
        db.close()


async def _accounting_turn(tmp_path, host, message, *, prior_frames=(), prior_events=(), host_tool=False):
    frames = [sdk.SystemMessage(subtype="init", data={"apiKeySource": "none", "model": MODEL}),
              *prior_frames, message]
    runtime = ClaudeAgentSDKRuntime(
        auth_probe=lambda: SimpleNamespace(allowed=True, category="subscription_oauth"),
        sdk_module=sdk, client_factory=lambda **kw: _Client(frames=frames, **kw),
        cwd=str(tmp_path), parent_env={},
    )
    request = build_runtime_turn_request(
        provider="claude-agent-sdk", model=MODEL, api_mode="agent_runtime",
        messages=({"role": "user", "content": "offline accounting"},),
        prompt_snapshot="constant offline system prompt", tool_schemas=(), correlation_id="accounting",
    )
    async def with_prior_effects(request, host):
        # Exercise host evidence from earlier in THIS turn, then the real SDK path.
        for event in prior_events:
            yield event
        if host_tool:
            await host.execute_tool("offline_tool", {}, request_id="earlier-tool")
        async for event in runtime.run_turn(request, host):
            yield event

    dispatch_runtime = SimpleNamespace(preflight=runtime.preflight, run_turn=with_prior_effects)
    try:
        return await asyncio.wait_for(_collect_runtime_turn(dispatch_runtime, request, host), timeout=10)
    finally:
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cost", [0, 0.0, None, _ABSENT], ids=["int-zero", "float-zero", "none", "absent"])
@pytest.mark.parametrize("optional", [{}, dict.fromkeys(_OPTIONAL_COUNTERS, 0)])
async def test_confirmed_zero_failure_keeps_receipts_empty_and_failure_previsible(
    tmp_path, accounting_host, cost, optional,
):
    agent, host, db = accounting_host
    outcome = await _accounting_turn(tmp_path, host, _usage_result({**_ZERO_USAGE, **optional}, cost))
    assert outcome.failure is not None
    assert outcome.failure.code == "sdk_api_rate_limit_429"
    assert outcome.failure.phase is RuntimeFailurePhase.BEFORE_VISIBLE_OUTPUT
    assert not [e for e in outcome.events if isinstance(e, RuntimeUsageEvent)]
    assert db.list_runtime_usage_receipts(agent.session_id) == []


class _UnreadableCounter(dict):
    def __contains__(self, key):
        if key == "cache_read_tokens":
            raise RuntimeError("counter lookup failed")
        return super().__contains__(key)


class _UnreadableValue(dict):
    def __getitem__(self, key):
        if key == "cache_read_tokens":
            raise RuntimeError("counter value failed")
        return super().__getitem__(key)


@pytest.mark.asyncio
@pytest.mark.parametrize("usage,cost", [
    *(pytest.param({**_ZERO_USAGE, key: value}, 0, id=f"{key}-{label}")
      for key in (*_ZERO_USAGE, *_OPTIONAL_COUNTERS)
      for value, label in [(1, "positive"), (None, "none"), (False, "bool"), ("0", "string"),
                           (-1, "negative"), (float("nan"), "nan"), (float("inf"), "inf")]),
    pytest.param({"input_tokens": 0}, 0, id="missing-output"),
    pytest.param({"output_tokens": 0}, 0, id="missing-input"),
    pytest.param([], 0, id="not-a-mapping"),
    pytest.param(_UnreadableCounter(_ZERO_USAGE), 0, id="unreadable-optional-membership"),
    pytest.param(_UnreadableValue(**_ZERO_USAGE, cache_read_tokens=0), 0, id="unreadable-optional-value"),
    *(pytest.param(_ZERO_USAGE, value, id=f"cost-{label}")
      for value, label in [(0.01, "positive"), (False, "bool"), ("0", "string"), (-1, "negative"),
                           (float("nan"), "nan"), (float("inf"), "inf"), ({}, "mapping")]),
])
async def test_positive_or_unknown_accounting_retains_receipt_and_blocks_replay(
    tmp_path, accounting_host, usage, cost,
):
    agent, host, db = accounting_host
    outcome = await _accounting_turn(tmp_path, host, _usage_result(usage, cost))
    receipts = [e.receipt for e in outcome.events if isinstance(e, RuntimeUsageEvent)]
    assert len(receipts) == 1
    assert db.list_runtime_usage_receipts(agent.session_id) == receipts
    assert outcome.failure is not None
    assert outcome.failure.phase is RuntimeFailurePhase.AFTER_SIDE_EFFECTS
    assert outcome.replay_safe is False


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["usage", "total_cost_usd", "model_usage"])
@pytest.mark.parametrize("error", [RuntimeError, AttributeError])
async def test_unreadable_accounting_property_is_not_absence(tmp_path, accounting_host, monkeypatch, field, error):
    original = sdk.ResultMessage.__getattribute__

    def read(message, name):
        if name == field:
            raise error("accounting property failed")
        return original(message, name)

    monkeypatch.setattr(sdk.ResultMessage, "__getattribute__", read)
    agent, host, db = accounting_host
    outcome = await _accounting_turn(tmp_path, host, _usage_result(_ZERO_USAGE))
    assert len(db.list_runtime_usage_receipts(agent.session_id)) == 1
    assert outcome.failure.phase is RuntimeFailurePhase.AFTER_SIDE_EFFECTS


@pytest.mark.asyncio
@pytest.mark.parametrize("model_usage", [
    {MODEL: {"inputTokens": 1, "outputTokens": 0}},
    {MODEL: {"inputTokens": 0, "outputTokens": 0, "cacheReadInputTokens": 1}},
    {MODEL: {"inputTokens": 0, "outputTokens": 0, "costUSD": 0.01}},
    {MODEL: {}}, {MODEL: None}, [],
])
async def test_per_model_usage_cannot_be_overruled_by_aggregate_zero(tmp_path, accounting_host, model_usage):
    agent, host, db = accounting_host
    message = _usage_result(_ZERO_USAGE, model_usage=model_usage)
    outcome = await _accounting_turn(tmp_path, host, message)
    assert len(db.list_runtime_usage_receipts(agent.session_id)) == 1
    assert outcome.failure.phase is RuntimeFailurePhase.AFTER_SIDE_EFFECTS


@pytest.mark.asyncio
@pytest.mark.parametrize("usage,failed,receipt_count", [(_ZERO_USAGE, False, 1), (None, False, 0), (None, True, 0)])
async def test_successful_zero_and_absent_usage_preserve_existing_accounting(
    tmp_path, accounting_host, usage, failed, receipt_count,
):
    agent, host, db = accounting_host
    outcome = await _accounting_turn(tmp_path, host, _usage_result(usage, failed=failed))
    assert len(db.list_runtime_usage_receipts(agent.session_id)) == receipt_count
    assert outcome.completed is not failed
    if failed:
        assert outcome.failure.phase is RuntimeFailurePhase.BEFORE_VISIBLE_OUTPUT


@pytest.mark.asyncio
@pytest.mark.parametrize("prior_frames,phase,count", [
    ([_assistant("visible")], RuntimeFailurePhase.AFTER_VISIBLE_OUTPUT, 1),
    ([_start("progress-only")], RuntimeFailurePhase.BEFORE_VISIBLE_OUTPUT, 1),
])
async def test_zero_suppression_preserves_visible_output_and_display_only_iteration_contract(
    tmp_path, accounting_host, prior_frames, phase, count,
):
    agent, host, db = accounting_host
    outcome = await _accounting_turn(tmp_path, host, _usage_result(_ZERO_USAGE), prior_frames=prior_frames)
    assert db.list_runtime_usage_receipts(agent.session_id) == []
    assert outcome.failure.phase is phase
    assert agent._api_call_count == count


@pytest.mark.asyncio
@pytest.mark.parametrize("effect", ["usage", "state", "compaction", "status", "approval", "tool"])
async def test_zero_receipt_suppression_never_erases_prior_host_effects(
    tmp_path, accounting_host, monkeypatch, effect,
):
    from agent.runtime_api import (
        RuntimeApprovalRequestEvent, RuntimeCompactionEvent, RuntimeCompactionPhase,
        RuntimeStateEnvelope, RuntimeStateEvent, RuntimeStatusEvent,
    )
    from agent.turn_runtime import _try_runtime_fallback

    agent, host, db = accounting_host
    earlier_receipt = next(e for e in ClaudeSdkEventProjector(model=MODEL).project(
        _usage_result({"input_tokens": 7, "output_tokens": 0}),
    ).events if isinstance(e, RuntimeUsageEvent))
    state = RuntimeStateEnvelope(runtime_id="hermes-claude-agent-sdk", schema_version=1, state={"cursor": "earlier"})
    events = {
        "usage": earlier_receipt,
        "state": RuntimeStateEvent(state=state),
        "compaction": RuntimeCompactionEvent(phase=RuntimeCompactionPhase.STARTED),
        "status": RuntimeStatusEvent(message="already visible"),
        "approval": RuntimeApprovalRequestEvent(request_id="approval", action="offline", details={}),
    }
    executed = []

    def execute(assistant, messages, task_id):
        executed.append(task_id)
        messages.append({"role": "tool", "tool_call_id": assistant.tool_calls[0].id, "content": "offline result"})

    agent._execute_tool_calls = execute
    agent.valid_tool_names = ("offline_tool",)
    host.refresh_turn("accounting")
    monkeypatch.setattr("tools.approval.request_tool_approval", lambda *a, **kw: {"approved": True})
    outcome = await _accounting_turn(
        tmp_path, host, _usage_result(_ZERO_USAGE),
        prior_events=() if effect == "tool" else (events[effect],), host_tool=effect == "tool",
    )
    assert outcome.failure is not None
    assert outcome.failure.code == "sdk_api_rate_limit_429"
    expected = (RuntimeFailurePhase.AFTER_VISIBLE_OUTPUT if effect in {"status", "approval"}
                else RuntimeFailurePhase.AFTER_SIDE_EFFECTS)
    assert outcome.failure.phase is expected
    assert outcome.replay_safe is False
    receipts = db.list_runtime_usage_receipts(agent.session_id)
    assert receipts == ([earlier_receipt.receipt] if effect == "usage" else [])
    if effect == "state":
        assert db.get_runtime_state(agent.session_id, state.runtime_id) == state
    if effect == "tool":
        assert executed == ["accounting"]
    if effect == "compaction":
        assert agent._runtime_compaction_events[0]["phase"] == "started"

    def forbidden(*args, **kwargs):
        pytest.fail("prior host effects must prevent fallback activation")

    agent._fallback_activated = False
    agent._has_pending_fallback = lambda: True
    agent._try_activate_fallback = forbidden
    registration = SimpleNamespace(plugin_id="offline-sdk", descriptor=build_runtime_descriptor())
    assert _try_runtime_fallback(agent, registration, outcome.failure) is False
