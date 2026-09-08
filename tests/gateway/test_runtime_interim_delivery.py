"""Runtime deltas must become commentary even when text streaming is disabled."""

import asyncio
from contextlib import suppress
from types import SimpleNamespace
from typing import Any

import pytest

from agent.runtime_dispatch import HermesRuntimeHostServices
from gateway.config import GatewayConfig, Platform, PlatformConfig, StreamingConfig
from gateway.display_config import resolve_display_setting
from gateway.run import GatewayRunner
from gateway.run_turn_runner import TurnRunner
from gateway.session import SessionSource
from gateway.turn_context import TurnContext
from plugins.platforms.discord.adapter import DiscordAdapter
from run_agent import AIAgent


class _DiscordChannel:
    """Replace only Discord's network transport, retaining the real adapter."""

    def __init__(self):
        self.messages = {}
        self.sent = asyncio.Queue()

    async def send(self, *, content, reference=None):
        message = SimpleNamespace(id=len(self.messages) + 1, content=content)
        self.messages[message.id] = message
        self.sent.put_nowait(content)
        return message

    def get_partial_message(self, message_id):
        async def edit(*, content):
            self.messages[message_id].content = content
        return SimpleNamespace(edit=edit)


def _wire_turn(*, interim=True):
    channel = _DiscordChannel()
    adapter = DiscordAdapter(PlatformConfig(enabled=True))
    adapter._client = SimpleNamespace(get_channel=lambda channel_id: channel)
    runner = object.__new__(GatewayRunner)
    runner.adapters = {Platform.DISCORD: adapter}
    runner.config = GatewayConfig(streaming=StreamingConfig(enabled=False))
    source = SessionSource(platform=Platform.DISCORD, chat_id="123", thread_id="123", chat_type="thread")
    ctx = TurnContext(
        source=source,
        session_id="runtime-commentary",
        user_config={"display": {"platforms": {"discord": {"streaming": False}}}},
        interim_assistant_messages_enabled=interim,
        resolve_display_setting=resolve_display_setting,
        _run_still_current=lambda: True,
        _status_adapter=adapter,
        _status_thread_metadata={"thread_id": "123"},
        _loop_for_step=asyncio.get_running_loop(),
    )
    turn = TurnRunner(runner, ctx)
    consumer, delta, commentary, want_interim = turn._setup_stream_consumer("discord")
    agent: Any = object.__new__(AIAgent)
    agent.session_id = ctx.session_id
    agent.model, agent.provider, agent.platform = "test-model", "test-runtime", "discord"
    agent.stream_delta_callback, agent._stream_callback = delta, None
    agent.interim_assistant_callback = commentary if want_interim else None
    agent.valid_tool_names, agent.tools = {"read_file"}, []

    def execute_tool(assistant, messages, task_id):
        messages.append({"role": "tool", "tool_call_id": assistant.tool_calls[0].id, "content": "tool result"})

    agent._execute_tool_calls = execute_tool
    agent._flush_messages_to_session_db = lambda messages: True
    ctx.agent_holder[0] = agent
    host = HermesRuntimeHostServices(agent, task_id="test", runtime_id="test-runtime", turn_messages=[])
    return runner, turn, ctx, agent, host, consumer, adapter, channel


@pytest.mark.asyncio
@pytest.mark.parametrize("producer", ["runtime", "builtin", "codex"])
async def test_nonstreaming_commentary_survives_tool_boundaries_without_repeating_final(producer):
    runner, turn, ctx, agent, host, consumer, adapter, channel = _wire_turn()
    assert consumer is not None
    task = asyncio.create_task(consumer.run())
    try:
        preamble = "I'll inspect the files first."
        await host.emit_content("I'll inspect ")
        await host.emit_content("the files first.")
        # A flush barrier must not turn buffered tokens into a streaming preview.
        assert await asyncio.to_thread(consumer.flush_pending_sync, timeout=2)
        assert not channel.messages
        if producer == "builtin":
            agent._emit_interim_assistant_message({"role": "assistant", "content": preamble})
        elif producer == "codex":
            agent._fire_streamed_codex_commentary(preamble)
        await host.execute_tool("read_file", {}, request_id="tool-1")
        assert await asyncio.wait_for(channel.sent.get(), timeout=2) == preamble
        # Parallel / text-free tools and repeated model narration must not replay commentary.
        await host.execute_tool("read_file", {}, request_id="tool-2")
        await host.emit_content(preamble)
        if producer == "builtin":
            agent._emit_interim_assistant_message({"role": "assistant", "content": preamble})
        elif producer == "codex":
            agent._fire_streamed_codex_commentary(preamble)
        await host.execute_tool("read_file", {}, request_id="tool-3")

        final = "The files are consistent."
        await host.emit_content(final)
        response = {"final_response": final, "completed": True, "messages": []}
        turn._finish_stream_consumer(response, [], consumer)
        await asyncio.wait_for(task, timeout=2)
        await runner._run_agent_mark_streamed_delivery(response, ctx)
        assert not response.get("already_sent")
        assert [m.content for m in channel.messages.values()] == [preamble]
        await adapter.send(ctx.source.chat_id, response["final_response"])
        assert [m.content for m in channel.messages.values()] == [preamble, final]
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_nonstreaming_runtime_commentary_respects_opt_out_and_turn_ownership():
    for interim in (False, True):
        runner, turn, ctx, agent, host, consumer, adapter, channel = _wire_turn(interim=interim)
        await host.emit_content("This must remain hidden.")
        if interim:
            ctx._run_still_current = lambda: False
        await host.execute_tool("read_file", {}, request_id="tool-1")
        if consumer is not None:
            consumer.finish()
            await asyncio.wait_for(consumer.run(), timeout=2)
        assert not channel.messages
