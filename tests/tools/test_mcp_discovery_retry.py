"""Discovery failures without a parked owner must recover on the MCP loop."""

import asyncio
import json
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest
import yaml

from tools import mcp_tool as mcp
from tools import mcp_tool_config as config
from tools import mcp_tool_discovery as discovery
from tools import mcp_tool_lifecycle as lifecycle
from tools import mcp_tool_loop as loop


@pytest.fixture
def retry_env(monkeypatch, tmp_path):
    lifecycle.shutdown_mcp_servers()
    for name in (
        "_servers", "_server_scope_keys", "_server_connecting", "_server_connect_errors",
        "_server_connect_retry_after", "_server_connect_failures", "_lazy_server_configs",
        "_lazy_server_fingerprints", "_lazy_server_tool_names", "_mcp_tool_server_names",
    ):
        monkeypatch.setattr(mcp, name, set() if name == "_server_connecting" else {})
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(config, "_portable_mcp_servers", lambda servers: None)
    monkeypatch.setattr(mcp, "_MCP_AVAILABLE", True)

    class Clock:
        now = 1000.0

        def __init__(self):
            self.waits = asyncio.Queue()

        async def sleep(self, delay):
            wake = asyncio.get_running_loop().create_future()
            self.waits.put_nowait((delay, wake))
            await wake

        async def advance(self, delay, wake):
            self.now += delay
            wake.set_result(None)

    clock = Clock()
    monkeypatch.setattr(discovery, "time", SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(discovery, "asyncio", SimpleNamespace(**{
        **vars(asyncio), "sleep": clock.sleep,
    }))
    path = tmp_path / "config.yaml"

    def write_config(servers, **globals):
        path.write_text(yaml.safe_dump({"mcp_servers": servers, **globals}))

    env = SimpleNamespace(
        clock=clock, write_config=write_config,
        run=lambda fn: loop._run_on_mcp_loop(fn, timeout=5),
    )
    loop._ensure_mcp_loop()
    try:
        yield env
    finally:
        lifecycle.shutdown_mcp_servers()


@pytest.fixture
def hung_server(monkeypatch):
    created = []

    class HungServer(mcp.MCPServerTask):
        def __init__(self, name):
            super().__init__(name)
            created.append(self)

        async def _run_stdio(self, config):
            await asyncio.Event().wait()
            return "shutdown"

    monkeypatch.setattr(mcp, "MCPServerTask", HungServer)
    return created


def test_discovery_timeout_schedules_one_retry_after_cooldown(retry_env, hung_server):
    """Exercise the outer wait_for cancellation, not the server's parked path."""
    created = hung_server
    servers = {"slow": {"command": "unused", "connect_timeout": 0.01}}
    retry_env.write_config(servers)
    assert discovery.register_mcp_servers(servers) == []
    assert "slow" not in mcp._servers
    assert created[0]._task.cancelled()
    assert "slow" in discovery._discovery_retries
    delay, wake = retry_env.run(retry_env.clock.waits.get)
    assert delay == mcp._CONNECT_RETRY_BASE_BACKOFF_SEC
    assert discovery._connect_cooldown_active("slow")

    first_retry = discovery._discovery_retries["slow"]
    discovery._schedule_discovery_retry("slow")
    discovery.register_mcp_servers(servers)
    assert discovery._discovery_retries == {"slow": first_retry}
    assert len(created) == 1
    assert not wake.done()


def test_repeated_timeouts_keep_retrying_with_capped_backoff(retry_env, hung_server, caplog):
    caplog.set_level("INFO", logger="tools.mcp_tool")
    servers = {"slow": {"command": "unused", "connect_timeout": 0.01}}
    retry_env.write_config(servers)
    discovery.register_mcp_servers(servers)
    for attempt, expected in enumerate((30, 60, 120, 240, 480, 600, 600), start=1):
        delay, wake = retry_env.run(retry_env.clock.waits.get)
        assert delay == expected
        assert len(hung_server) == attempt
        assert all(server._task.cancelled() for server in hung_server)
        assert "slow" not in mcp._servers
        retry_env.run(lambda: retry_env.clock.advance(delay, wake))
    retry_env.run(retry_env.clock.waits.get)
    assert len([r for r in caplog.records if "scheduled discovery retry" in r.message]) == 8
    assert len([r for r in caplog.records if "discovery retry failed" in r.message]) == 7


def test_queued_retry_keeps_deadline_when_manual_discovery_clears_cooldown(retry_env, hung_server):
    servers = {"slow": {"command": "unused", "connect_timeout": 0.01}}
    retry_env.write_config(servers)

    async def discover_then_expire():
        await discovery._discover_all(servers)
        # A manual pass can expire the cooldown before the queued retry even starts.
        mcp._server_connect_retry_after.pop("slow")

    retry_env.run(discover_then_expire)
    delay, _ = retry_env.run(retry_env.clock.waits.get)
    assert delay == mcp._CONNECT_RETRY_BASE_BACKOFF_SEC
    assert len(hung_server) == 1


def test_shutdown_cancels_only_selected_retries(retry_env, hung_server):
    servers = {name: {"command": "unused", "connect_timeout": 0.01}
               for name in ("one", "two")}
    retry_env.write_config(servers)
    discovery.register_mcp_servers(servers)
    retry_env.run(retry_env.clock.waits.get)
    retry_env.run(retry_env.clock.waits.get)
    with mcp._lock:
        mcp._server_scope_keys.update({"one": "profile:one", "two": "profile:two"})
        one, two = discovery._discovery_retries["one"], discovery._discovery_retries["two"]
    assert isinstance(one, asyncio.Task) and isinstance(two, asyncio.Task)
    lifecycle.shutdown_mcp_servers(scope="profile:one")
    assert one.cancelled()
    assert not two.done()
    assert discovery._discovery_retries == {"two": two}
    assert mcp._mcp_loop is not None and mcp._mcp_loop.is_running()
    assert lifecycle._stop_mcp_loop_if_idle() is False
    lifecycle.shutdown_mcp_servers()
    assert two.cancelled()
    assert discovery._discovery_retries == {}
    assert mcp._mcp_loop is None


def test_backoff_stays_bounded_after_many_failures(retry_env):
    mcp._server_connect_failures["slow"] = 10000
    discovery._record_connect_failure("slow")
    assert mcp._server_connect_retry_after["slow"] - retry_env.clock.now == 600


async def _await_retry(task):
    await task


@pytest.mark.parametrize("lazy", [False, True])
def test_successful_retry_reads_fresh_profile_config_and_registers_callable_tools(
    retry_env, monkeypatch, tmp_path, caplog, lazy,
):
    from hermes_constants import (
        get_hermes_home, reset_hermes_home_override, set_hermes_home_override,
    )
    from tools.registry import ToolRegistry
    import tools.registry as registry_module

    caplog.set_level("INFO", logger="tools.mcp_tool")
    registry = ToolRegistry()
    monkeypatch.setattr(registry_module, "registry", registry)
    monkeypatch.setattr(mcp, "_mcp_registry_scope", registry.current_scope_key)
    attempts = []

    class Session:
        async def call_tool(self, name, arguments):
            return SimpleNamespace(
                isError=False, structuredContent=None,
                content=[SimpleNamespace(text="retried:" + arguments["value"])],
            )

    class RecoveringServer(mcp.MCPServerTask):
        async def _run_stdio(self, config):
            attempts.append((get_hermes_home(), config))
            if len(attempts) == 1:
                await asyncio.Event().wait()
            self.session = Session()
            self._tools = [SimpleNamespace(
                name=name, description="Retry integration tool",
                inputSchema={"type": "object", "properties": {"value": {"type": "string"}}},
            ) for name in ("ping", "excluded")]
            self._ready.set()
            return await self._wait_for_lifecycle_event()

    monkeypatch.setattr(mcp, "MCPServerTask", RecoveringServer)
    servers = {"slow": {"command": "unused", "connect_timeout": 0.01, "args": ["old"]}}
    retry_env.write_config(servers)
    token = set_hermes_home_override(str(tmp_path))
    try:
        scope = registry.current_scope_key()
        if lazy:
            from tools.mcp_tool_registration import _register_from_cache_sync
            _register_from_cache_sync("slow", servers["slow"], {
                "tools": [{"name": "stale", "description": "Old cached tool",
                           "inputSchema": {"type": "object", "properties": {}}}],
                "utility_tools": [],
            })
            assert discovery._ensure_lazy_server_connected("slow") is False
        else:
            discovery.register_mcp_servers(servers)
    finally:
        reset_hermes_home_override(token)
    delay, wake = retry_env.run(retry_env.clock.waits.get)
    pending = discovery._discovery_retries["slow"]
    # Only the background task retains the initiating profile. The process now sees another home.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "other"))
    fresh = {"command": "unused", "args": ["new"], "connect_timeout": 5,
             "tools": {"include": ["ping"], "resources": False, "prompts": False}}
    retry_env.write_config({"slow": fresh})
    retry_env.run(lambda: retry_env.clock.advance(delay, wake))
    retry_env.run(lambda: _await_retry(pending))
    assert attempts == [(tmp_path, servers["slow"]), (tmp_path, fresh)]
    assert mcp._server_scope_keys["slow"] == scope
    assert not mcp._server_connect_errors
    assert not mcp._server_connect_retry_after
    assert not mcp._lazy_server_configs
    assert not mcp._lazy_server_tool_names
    assert not discovery._discovery_retries
    assert registry.get_entry("mcp__slow__ping") is None  # invisible to the other profile
    token = set_hermes_home_override(str(tmp_path))
    try:
        entry = registry.get_entry("mcp__slow__ping")
        assert entry is not None and entry.check_fn is not None and entry.check_fn()
        assert json.loads(entry.handler({"value": "ok"})) == {"result": "retried:ok"}
        assert registry.get_entry("mcp__slow__excluded") is None
        assert registry.get_entry("mcp__slow__stale") is None
    finally:
        reset_hermes_home_override(token)
    assert len([r for r in caplog.records if "discovery retry succeeded" in r.message]) == 1


@pytest.mark.parametrize("disabled", [False, "false"])
def test_opt_out_schedules_nothing(retry_env, hung_server, disabled):
    servers = {"slow": {"command": "unused", "connect_timeout": 0.01}}
    retry_env.write_config(servers, mcp_discovery_retry=disabled)
    discovery.register_mcp_servers(servers)
    assert len(hung_server) == 1
    assert discovery._connect_cooldown_active("slow")
    assert discovery._discovery_retries == {}
    assert retry_env.clock.waits.empty()


@pytest.mark.parametrize("change", ["removed", "disabled", "opted_out"])
def test_pending_retry_stops_when_config_no_longer_allows_it(retry_env, hung_server, change):
    servers = {"slow": {"command": "unused", "connect_timeout": 0.01}}
    retry_env.write_config(servers)
    discovery.register_mcp_servers(servers)
    delay, wake = retry_env.run(retry_env.clock.waits.get)
    pending = discovery._discovery_retries["slow"]
    if change == "removed":
        retry_env.write_config({})
    elif change == "disabled":
        retry_env.write_config({"slow": {**servers["slow"], "enabled": False}})
    else:
        retry_env.write_config(servers, mcp_discovery_retry=False)
    retry_env.run(lambda: retry_env.clock.advance(delay, wake))
    retry_env.run(lambda: _await_retry(pending))
    assert len(hung_server) == 1
    assert discovery._discovery_retries == {}


def test_shutdown_cancels_inflight_retry_without_adopting_it(retry_env, monkeypatch):
    started = threading.Event()
    created = []

    class Server(mcp.MCPServerTask):
        def __init__(self, name):
            super().__init__(name)
            created.append(self)

        async def _run_stdio(self, config):
            if len(created) == 2:
                started.set()
            await asyncio.Event().wait()
            return "shutdown"

    monkeypatch.setattr(mcp, "MCPServerTask", Server)
    servers = {"slow": {"command": "unused", "connect_timeout": 0.01}}
    retry_env.write_config(servers)
    discovery.register_mcp_servers(servers)
    delay, wake = retry_env.run(retry_env.clock.waits.get)
    pending = discovery._discovery_retries["slow"]
    retry_env.write_config({"slow": {"command": "unused", "connect_timeout": 60}})
    retry_env.run(lambda: retry_env.clock.advance(delay, wake))
    assert started.wait(timeout=5)
    lifecycle.shutdown_mcp_servers()
    assert pending.cancelled()
    assert all(server._task.cancelled() for server in created)
    assert not mcp._servers
    assert not mcp._server_connecting
    assert not discovery._discovery_retries


@pytest.mark.parametrize("cancel_done", [False, True])
def test_discovery_never_adopts_a_cancelled_task(retry_env, monkeypatch, cancel_done):
    async def cancelled_connect(name, config):
        server = mcp.MCPServerTask(name)
        server._task = asyncio.create_task(asyncio.Event().wait())
        server._task.cancel()
        if cancel_done:
            await asyncio.gather(server._task, return_exceptions=True)
        return server

    monkeypatch.setattr(discovery, "_connect_server", cancelled_connect)
    with pytest.raises(RuntimeError, match="cancelled"):
        retry_env.run(lambda: discovery._discover_and_register_server("cancelled", {"command": "unused"}))
    assert "cancelled" not in mcp._servers


def test_interpreter_exit_drains_pending_retries(retry_env):
    retry_env.write_config({"slow": {"command": "unused"}})
    result = subprocess.run([sys.executable, "-c", """
import asyncio
import atexit
import json

def receipt():
    print(json.dumps({"cancelled": pending.cancelled(),
                      "retries": len(discovery._discovery_retries),
                      "loop_stopped": mcp._mcp_loop is None}))

# LIFO: the lifecycle hook imported below must run before this verification.
atexit.register(receipt)
from tools import mcp_tool as mcp
from tools import mcp_tool_config as config
from tools import mcp_tool_discovery as discovery
from tools import mcp_tool_loop as loop
config._portable_mcp_servers = lambda servers: None
loop._ensure_mcp_loop()

async def prepare():
    discovery._note_connect_failure("slow", TimeoutError())
    discovery._schedule_discovery_retry("slow")
    await asyncio.sleep(0)
    return discovery._discovery_retries["slow"]

pending = loop._run_on_mcp_loop(prepare, timeout=5)
"""], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"cancelled": True, "retries": 0, "loop_stopped": True}
    assert "Exception ignored in atexit" not in result.stderr
