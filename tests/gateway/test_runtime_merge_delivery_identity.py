"""Runtime host delivery IDs must not collapse upstream interim child notices."""
import asyncio
from types import SimpleNamespace

import pytest

from gateway.config import Platform
from gateway.run import GatewayRunner
from hermes_state import SessionDB


def _event(task_index=None):
    evt = {"type": "async_delegation", "delegation_id": "batch",
           "parent_session_id": "parent", "session_key": "api-session",
           "origin_session_id": "api-session"}
    if task_index is not None:
        evt.update(task_failure_notice=True, results=[{"task_index": task_index, "status": "error"}])
    return evt


def test_interim_notices_have_distinct_host_message_and_queue_identities():
    events = [_event(0), _event(1), _event()]
    assert len({GatewayRunner._async_delegation_delivery_id(evt) for evt in events}) == len(events)
    assert len({GatewayRunner._completion_delivery_identity(evt) for evt in events}) == len(events)
    assert GatewayRunner._async_delegation_delivery_id(_event(0)) == GatewayRunner._async_delegation_delivery_id(_event(0))


@pytest.mark.parametrize("indexes", [(0, 1, None), (None, 0, 1)])
def test_api_delivery_keeps_interim_siblings_and_final_but_deduplicates_replays(tmp_path, indexes):
    db = SessionDB(tmp_path / "state.db")
    db.create_session("api-session", "api_server")
    adapter = SimpleNamespace(supports_async_delivery=False, _ensure_session_db=lambda: db)
    runner = object.__new__(GatewayRunner)
    runner.adapters = {Platform.API_SERVER: adapter}
    runner._build_process_event_source = lambda evt: None

    async def deliver():
        for index in indexes:
            event = _event(index)
            assert await runner._inject_watch_notification(str(index), event) is True
            assert await runner._inject_watch_notification(str(index), event) is True

    try:
        asyncio.run(deliver())
        rows = db.get_messages("api-session")
        assert [row["content"] for row in rows] == [str(index) for index in indexes]
    finally:
        db.close()
