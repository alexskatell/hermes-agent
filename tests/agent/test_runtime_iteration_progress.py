"""Provider-neutral runtime progress and final count regressions."""
import asyncio
from types import SimpleNamespace

import pytest

from agent.runtime_api import RuntimeIterationEvent, RuntimeFailure, RuntimeFailurePhase
from agent.runtime_dispatch import HermesRuntimeHostServices
from agent import turn_runtime


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "2"])
def test_iteration_event_rejects_invalid_counts(value):
    with pytest.raises(ValueError):
        RuntimeIterationEvent(iteration=value)


def test_host_progress_is_monotonic_and_resets_for_next_turn():
    agent = SimpleNamespace(_api_call_count=99, _touch_activity=lambda **kwargs: None)
    host = HermesRuntimeHostServices(agent, task_id="test", runtime_id="test-runtime")
    assert agent._api_call_count == 0

    async def scenario():
        for value in (1, 3, 3, 2):
            await host.emit_iteration(value)
        assert agent._api_call_count == 3
        host.refresh_turn(task_id="test-next")
        assert agent._api_call_count == 0
        await host.emit_iteration(1)
        assert agent._api_call_count == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
def test_finalizer_preserves_observed_count_without_a_terminal_count(monkeypatch, outcome):
    agent = SimpleNamespace(
        provider="test", model="test", api_mode="agent_runtime", tools=(),
        _api_call_count=3, _strip_think_blocks=lambda text: text,
    )
    context = SimpleNamespace(
        messages=[{"role": "user", "content": "test"}], user_message="test",
        original_user_message="test", conversation_history=[], effective_task_id=None,
        turn_id="test-turn", _should_review_memory=False, active_system_prompt="test",
        current_turn_user_idx=0, _ext_prefetch_cache=None, _plugin_user_context=None,
    )
    registration = SimpleNamespace(
        plugin_id="test-plugin", descriptor=SimpleNamespace(runtime_id="test-runtime")
    )
    failure = RuntimeFailure(
        code="test", message="test failure", replay_safe=False,
        phase=RuntimeFailurePhase.AFTER_VISIBLE_OUTPUT,
    ) if outcome == "failed" else None
    dispatched = SimpleNamespace(
        response={"final_response": "done"} if outcome == "completed" else None,
        failure=failure, cancelled=outcome == "cancelled", terminal=None,
    )
    monkeypatch.setattr(turn_runtime, "get_runtime_session", lambda *a, **k:
                        SimpleNamespace(run_turn=lambda request: dispatched))
    monkeypatch.setattr(turn_runtime, "_try_runtime_fallback", lambda *a: False)
    monkeypatch.setattr(turn_runtime, "_runtime_persistence_succeeded", lambda *a: False)
    monkeypatch.setattr(turn_runtime, "finalize_turn", lambda agent, **kwargs:
                        {"api_calls": kwargs["api_call_count"]})
    result = turn_runtime.run_registered_runtime(agent, registration, context)
    assert result is not None
    assert result["api_calls"] == 3
