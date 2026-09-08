"""Offline SDK -> runtime host -> gateway -> Discord commentary regression."""

import asyncio
from contextlib import suppress
from types import SimpleNamespace
from typing import Any

import pytest

from agent.runtime_dispatch import (
    HermesRuntimeHostServices,
    RuntimeSessionBinding,
    build_runtime_turn_request,
)
from gateway.config import GatewayConfig, Platform, PlatformConfig, StreamingConfig
from gateway.display_config import resolve_display_setting
from gateway.run import GatewayRunner
from gateway.run_turn_runner import TurnRunner
from gateway.session import SessionSource
from gateway.turn_context import TurnContext
from plugins.platforms.discord.adapter import DiscordAdapter
from run_agent import AIAgent

plugin = pytest.importorskip("hermes_claude_agent_sdk.runtime")
from hermes_claude_agent_sdk.compatibility import build_runtime_descriptor


def _message(kind, **fields):
    return type(kind, (SimpleNamespace,), {})(**fields)


class _Channel:
    def __init__(self):
        self.messages = []

    async def send(self, *, content, reference=None):
        message = SimpleNamespace(id=len(self.messages) + 1, content=content)
        self.messages.append(message)
        return message

    def get_partial_message(self, message_id):
        async def edit(*, content):
            self.messages[message_id - 1].content = content
        return SimpleNamespace(edit=edit)


class _Client:
    def __init__(self, *, options, scenario):
        self.options = options
        self.scenario = scenario
        self.messages = asyncio.Queue()
        self.producer = None

    async def connect(self):
        pass

    async def query(self, prompt):
        # Real query only writes the prompt; response/MCP work runs concurrently
        # with the plugin's sole receive_messages reader.
        self.producer = asyncio.create_task(self.scenario(self))

    async def receive_messages(self):
        while True:
            yield await self.messages.get()

    async def interrupt(self):
        await self.disconnect()

    async def disconnect(self):
        if self.producer is not None:
            self.producer.cancel()
            await asyncio.gather(self.producer, return_exceptions=True)


def _sdk(scenario, clients):
    def client(*, options):
        instance = _Client(options=options, scenario=scenario)
        clients.append(instance)
        return instance

    def tool(name, description, input_schema):
        return lambda handler: SimpleNamespace(name=name, handler=handler)

    return SimpleNamespace(
        ClaudeAgentOptions=SimpleNamespace,
        HookMatcher=SimpleNamespace,
        ClaudeSDKClient=client,
        tool=tool,
        create_sdk_mcp_server=lambda **kwargs: kwargs,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("ordering", [
    "content-first",
    "thinking-only",
    pytest.param("bridge-first", marks=pytest.mark.xfail(
        strict=True, raises=AssertionError,
        reason="SDK MCP execution can overtake content projection; plugin needs an ordered display boundary",
    )),
])
async def test_sdk_delivers_each_commentary_before_next_tool_batch(monkeypatch, tmp_path, ordering):
    channel = _Channel()
    adapter = DiscordAdapter(PlatformConfig(enabled=True))
    adapter._client = SimpleNamespace(get_channel=lambda channel_id: channel)
    runner = object.__new__(GatewayRunner)
    runner.adapters = {Platform.DISCORD: adapter}
    runner.config = GatewayConfig(streaming=StreamingConfig(enabled=False))
    ctx = TurnContext(
        source=SessionSource(platform=Platform.DISCORD, chat_id="123", thread_id="123", chat_type="thread"),
        session_id="sdk-commentary",
        user_config={"display": {"platforms": {"discord": {"streaming": False}}}},
        interim_assistant_messages_enabled=True,
        resolve_display_setting=resolve_display_setting,
        _run_still_current=lambda: True,
        _status_adapter=adapter,
        _status_thread_metadata={"thread_id": "123"},
        _loop_for_step=asyncio.get_running_loop(),
    )
    turn = TurnRunner(runner, ctx)
    consumer, delta, commentary, want_interim = turn._setup_stream_consumer("discord")
    assert consumer is not None and want_interim
    agent = AIAgent(
        provider="claude-agent-sdk", model="claude-fable-5-1", api_mode="agent_runtime",
        enabled_toolsets=[], quiet_mode=True, skip_context_files=True, skip_memory=True,
        session_id=ctx.session_id, platform="discord",
        stream_delta_callback=delta, interim_assistant_callback=commentary,
    )
    ctx.agent_holder[0] = agent
    schema = {"type": "function", "function": {
        "name": "read_file", "description": "Read an offline fixture",
        "parameters": {"type": "object", "properties": {}},
    }}
    agent.tools, agent.valid_tool_names = [schema], {"read_file"}
    calls = []
    execute_tools = agent._execute_tool_calls

    def execute(assistant, messages, task_id):
        calls.append(assistant.tool_calls[0].id)
        execute_tools(assistant, messages, task_id)

    monkeypatch.setattr(agent, "_execute_tool_calls", execute)
    # Fake only the leaf tool operation; keep canonical tool execution, stream
    # state, persistence ordering, and the plugin MCP bridge in the path.
    monkeypatch.setattr("model_tools.handle_function_call", lambda *args, **kwargs: "fixture result")
    monkeypatch.setattr(agent, "_flush_messages_to_session_db", lambda messages: True)
    host = HermesRuntimeHostServices(agent, task_id="sdk-test", runtime_id="hermes-claude-agent-sdk", turn_messages=[])
    segments = ["First, inspect the configuration.", "Second, inspect the logs.", "Third, inspect the plugin."]
    final = "The inspection is complete."
    seen = {text: asyncio.Event() for text in segments}
    emit_content = host.emit_content

    projected_texts = []

    async def observe_content(text):
        projected_texts.append(text)
        await emit_content(text)
        if text in seen:
            seen[text].set()

    monkeypatch.setattr(host, "emit_content", observe_content)
    snapshots = []

    async def scenario(client):
        await client.messages.put(_message("SystemMessage", subtype="init", data={"apiKeySource": "none"}))
        handler = client.options.mcp_servers["hermes-tools"]["tools"][0].handler
        for index, text in enumerate(segments):
            private = ordering == "thinking-only" and index > 0
            block = (_message("ThinkingBlock", thinking="private scratchpad", signature="test")
                     if private else _message("TextBlock", text=text))
            await client.messages.put(_message(
                "AssistantMessage", model="claude-fable-5-1", message_id=f"msg-{index}", content=[block],
            ))
            # The real SDK emits separate envelopes for completed text and tool
            # blocks, sharing a model-response ID. Queue order alone is not a
            # projection barrier: MCP executes outside the SDK message reader.
            if not private and (ordering != "bridge-first" or index == 0):
                await asyncio.wait_for(seen[text].wait(), 3)
            await client.messages.put(_message(
                "AssistantMessage", model="claude-fable-5-1", message_id=f"msg-{index}", content=[
                    _message("ToolUseBlock", id=f"tool-{index}", name="mcp__hermes-tools__read_file", input={}),
                ],
            ))
            tool_result = await handler({})
            assert tool_result["is_error"] is False
            if not private:
                await asyncio.wait_for(seen[text].wait(), 3)
            assert consumer.flush_pending_sync(timeout=3)
            snapshots.append([m.content for m in channel.messages])
        await client.messages.put(_message("ResultMessage", result=final, session_id="", usage=None,
                                          is_error=False, subtype="success", terminal_reason="completed"))

    clients = []
    runtime = plugin.ClaudeAgentSDKRuntime(
        auth_probe=lambda: SimpleNamespace(allowed=True, category="subscription_oauth"),
        sdk_module=_sdk(scenario, clients), cwd=str(tmp_path), parent_env={},
    )
    binding = RuntimeSessionBinding(runtime=runtime, host=host, descriptor=build_runtime_descriptor(),
                                    plugin_id="claude-sdk-test", parent_session_id=ctx.session_id)
    request = build_runtime_turn_request(
        provider=agent.provider, model=agent.model, api_mode=agent.api_mode,
        messages=({"role": "user", "content": "inspect fixtures"},),
        prompt_snapshot="Offline commentary test.", tool_schemas=[schema], correlation_id="sdk-test",
    )
    task = asyncio.create_task(runner._run_agent_stream_consumer_task(ctx.stream_consumer_holder))
    try:
        result = await asyncio.wait_for(asyncio.to_thread(binding.run_turn, request), 15)
        assert result.completed, result.failure
        await clients[0].producer
        response = result.response
        turn._finish_stream_consumer(response, [], consumer)
        await asyncio.wait_for(task, 3)
        expected = segments[:1] if ordering == "thinking-only" else segments
        assert projected_texts == [*expected, final]
        assert len(calls) == len(segments)
        assert agent.stream_delta_callback is delta
        assert agent.interim_assistant_callback is commentary
        assert snapshots == [expected[:index + 1] for index in range(len(segments))]
        assert [m.content for m in channel.messages] == expected
        await runner._run_agent_mark_streamed_delivery(response, ctx)
        assert not response.get("already_sent")
        await adapter.send(ctx.source.chat_id, response["final_response"])
        assert [m.content for m in channel.messages] == [*expected, final]
    finally:
        await asyncio.to_thread(binding.close)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        agent.release_clients()
