"""Each distinct runtime commentary segment must reach the platform, not only the first."""

import asyncio
from contextlib import suppress

import pytest

from tests.gateway.test_runtime_interim_delivery import _wire_turn


@pytest.mark.asyncio
async def test_nonstreaming_runtime_delivers_every_distinct_commentary_segment():
    runner, turn, ctx, agent, host, consumer, adapter, channel = _wire_turn()
    assert consumer is not None
    task = asyncio.create_task(consumer.run())
    try:
        segments = ["First, I'll read the config.", "Config looks fine; checking logs.", "Logs point at the plugin."]
        for index, text in enumerate(segments):
            await host.emit_content(text)
            await host.execute_tool("read_file", {}, request_id=f"tool-{index}")
            assert await asyncio.wait_for(channel.sent.get(), timeout=2) == text
        final = "Done."
        await host.emit_content(final)
        response = {"final_response": final, "completed": True, "messages": []}
        turn._finish_stream_consumer(response, [], consumer)
        await asyncio.wait_for(task, timeout=2)
        assert [m.content for m in channel.messages.values()] == segments
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_repeated_commentary_then_distinct_segment_does_not_concatenate():
    runner, turn, ctx, agent, host, consumer, adapter, channel = _wire_turn()
    assert consumer is not None
    task = asyncio.create_task(consumer.run())
    try:
        first, second = 'Inspecting config.', 'Inspecting logs.'
        for index, text in enumerate((first, first, second)):
            await host.emit_content(text)
            await host.execute_tool('read_file', {}, request_id=f'dedup-{index}')
            assert await asyncio.to_thread(consumer.flush_pending_sync, timeout=2)
        consumer.finish()
        await asyncio.wait_for(task, 2)
        assert [m.content for m in channel.messages.values()] == [first, second]
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
