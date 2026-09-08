"""SDK model-response boundaries must reach the Discord iteration display.

Uses the real installed plugin and host dispatcher; no SDK client or network.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.iteration_budget import IterationBudget
from agent.runtime_api import RuntimeCompletedEvent, RuntimeIterationEvent
from agent.runtime_dispatch import (
    HermesRuntimeHostServices, _collect_runtime_turn, build_runtime_turn_request,
)
from gateway.config import Platform
from gateway.platforms.base import MessageEvent
from gateway.run import GatewayRunner
from gateway.session import SessionSource
from run_agent import AIAgent
from hermes_claude_agent_sdk.content_events import ClaudeSdkEventProjector


def _message(kind, **fields):
    return type(kind, (SimpleNamespace,), {})(**fields)


def _start(message_id, parent=None):
    return _message("StreamEvent", parent_tool_use_id=parent, event={
        "type": "message_start", "message": {"id": message_id},
    })


def _agent():
    agent = SimpleNamespace(
        session_id="counter-test", _api_call_count=0, max_iterations=750,
        iteration_budget=IterationBudget(750), _current_tool=None,
        tools=[], valid_tool_names=[], _fire_stream_delta=lambda text: None,
    )
    agent._touch_activity = lambda text: setattr(agent, "_last_activity_desc", text)
    agent.get_activity_summary = AIAgent.get_activity_summary.__get__(agent)
    return agent


def _discord_status(agent):
    event = MessageEvent(text="status", source=SessionSource(
        platform=Platform.DISCORD, chat_id="counter-test", chat_type="thread",
    ))
    runner = object.__new__(GatewayRunner)
    with patch("gateway.run._load_gateway_config", return_value={}), patch(
        "agent.onboarding.is_seen", return_value=True,
    ):
        return runner._compose_busy_ack_message(
            event, 0, None, agent, is_steer_mode=True, is_queue_mode=False,
            is_redirect_mode=False, demoted_for_subagents=False,
            demoted_for_compression=False,
        )


@pytest.mark.asyncio
async def test_sdk_response_boundaries_reach_discord_once_and_reset_per_turn():
    agent = _agent()
    host = HermesRuntimeHostServices(agent, task_id="counter", runtime_id="sdk-test")
    projector = ClaudeSdkEventProjector(model="diagnostic-model")
    request = build_runtime_turn_request(
        provider="example", model="diagnostic-model", api_mode="agent_runtime",
        messages=(), prompt_snapshot="", tool_schemas=(), correlation_id="turn-1",
    )
    snapshots = []
    sdk_messages = [
        _start("msg-1"),
        _start("msg-1"),  # repeated stream start is not another model call
        _message("AssistantMessage", message_id="msg-1", parent_tool_use_id=None,
                 content=[_message("TextBlock", text="one response block")]),
        _start("child-1", parent="nested-tool"),
        _start("msg-2"),
        _message("AssistantMessage", message_id="msg-2", parent_tool_use_id=None,
                 content=[_message("TextBlock", text="second response")]),
    ]

    class Runtime:
        async def close(self):
            pass

        def preflight(self, request):
            return None

        async def run_turn(self, request, host):
            for message in sdk_messages:
                for event in projector.project(message).events:
                    yield event
                snapshots.append(agent.get_activity_summary()["api_call_count"])
            yield RuntimeCompletedEvent(result={"completed": True})

    result = await _collect_runtime_turn(Runtime(), request, host)
    assert result.completed
    assert snapshots == [1, 1, 1, 1, 2, 2], "SDK progress stayed at zero or double-counted response blocks"
    assert "iteration 2/750" in _discord_status(agent)
    assert agent.iteration_budget.used == 0, "Display telemetry must not change SDK budget policy"

    host.refresh_turn("counter", correlation_id="turn-2")
    projector.begin_turn(correlation_id="turn-2")
    assert agent.get_activity_summary()["api_call_count"] == 0
    sdk_messages[:] = [_start("msg-1")]
    snapshots.clear()
    result = await _collect_runtime_turn(Runtime(), request, host)
    assert result.completed
    assert snapshots == [1]
    assert "iteration 1/750" in _discord_status(agent)


def test_real_sdk_types_deduplicate_root_response_boundaries():
    from claude_agent_sdk import AssistantMessage, StreamEvent, TextBlock

    projector = ClaudeSdkEventProjector(model="diagnostic-model")

    def counts(message):
        return [event.iteration for event in projector.project(message).events
                if isinstance(event, RuntimeIterationEvent)]

    def stream(message_id, parent=None):
        return StreamEvent(uuid="event", session_id="session", parent_tool_use_id=parent,
                           event={"type": "message_start", "message": {"id": message_id}})

    assert counts(stream("root-1")) == [1]
    assert counts(AssistantMessage(content=[TextBlock(text="assembled")],
                                   model="diagnostic-model", message_id="root-1")) == []
    assert counts(stream("nested-1", parent="tool-1")) == []
    for invalid in (None, "", 1, "x" * 1024):
        assert counts(stream(invalid)) == []
    assert counts(AssistantMessage(content=[TextBlock(text="next")],
                                   model="diagnostic-model", message_id="root-2")) == [2]
    projector.begin_turn()
    assert counts(stream("root-1")) == [1]
