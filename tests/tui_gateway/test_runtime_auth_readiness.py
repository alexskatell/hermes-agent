"""Runtime-owned auth must not be mistaken for a missing provider API key."""

import importlib
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def server():
    # No env loading or update-check threads while importing the real RPC host.
    with patch("threading.Thread.start", return_value=None), patch(
        "atexit.register", side_effect=lambda fn, *args, **kwargs: fn
    ), patch.dict("sys.modules", {
        "hermes_cli.env_loader": SimpleNamespace(load_hermes_dotenv=Mock()),
        "hermes_cli.banner": SimpleNamespace(prefetch_update_check=Mock()),
    }):
        return importlib.import_module("tui_gateway.server")


@pytest.mark.parametrize(
    "runtime,configured,ready",
    [
        ({"provider": "runtime-test", "api_mode": "agent_runtime", "api_key": "", "source": "provider-profile"}, False, True),
        ({"provider": "openrouter", "api_mode": "chat_completions", "api_key": "", "source": "env"}, True, False),
        ({"provider": "custom", "api_mode": "chat_completions", "api_key": "no-key-required"}, True, True),
        ({"provider": "bedrock", "api_key": "aws-sdk", "source": "iam-role"}, False, False),
        (RuntimeError("runtime authentication unavailable"), True, False),
    ],
)
def test_runtime_readiness_respects_runtime_owned_auth(server, monkeypatch, runtime, configured, ready):
    import hermes_cli.main
    import hermes_cli.runtime_provider

    resolver = Mock(side_effect=runtime) if isinstance(runtime, Exception) else Mock(return_value=runtime)
    monkeypatch.setattr(hermes_cli.runtime_provider, "resolve_runtime_provider", resolver)
    monkeypatch.setattr(hermes_cli.main, "_has_any_provider_configured", Mock(return_value=configured))

    response = server._methods["setup.runtime_check"]("ready-test", {"provider": "runtime-test"})

    assert response["result"]["ok"] is ready
    resolver.assert_called_once_with(requested="runtime-test")
    if isinstance(runtime, Exception):
        assert response["result"]["error"] == str(runtime)


@pytest.mark.parametrize(
    "mode,key,warns",
    [("agent_runtime", "", False), ("chat_completions", "", True),
     ("chat_completions", "no-key-required", False)],
)
def test_session_credential_warning_respects_runtime_owned_auth(server, mode, key, warns):
    agent = SimpleNamespace(api_mode=mode, api_key=key, provider="provider-test")
    assert bool(server._probe_credentials(agent)) is warns


@pytest.mark.parametrize("enabled", [True, False])
def test_registered_runtime_readiness_uses_real_resolution(server, monkeypatch, tmp_path, enabled):
    import json

    import hermes_cli.main
    import hermes_cli.runtime_provider as rp
    from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest
    from providers.base import ProviderProfile

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    manager = PluginManager()
    manager._discovered = True
    context = PluginContext(PluginManifest(name="runtime-readiness-test"), manager)
    profile = ProviderProfile(
        name="runtime-readiness-provider", api_mode="agent_runtime",
        base_url="runtime://runtime-readiness-provider", auth_type="oauth_external",
    )
    context.register_provider_profile(profile)
    (tmp_path / "config.yaml").write_text(json.dumps({
        "model": {"provider": profile.name, "default": "offline-model"},
        "providers": {profile.name: {"enabled": enabled}},
    }), encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("runtime readiness must not construct a wire client or resolve API credentials")

    monkeypatch.setattr(rp, "resolve_provider", forbidden)
    monkeypatch.setattr("openai.OpenAI", forbidden)
    monkeypatch.setattr("anthropic.Anthropic", forbidden)
    # This unrelated inventory probe must not inspect any real auth stores.
    monkeypatch.setattr(hermes_cli.main, "_has_any_provider_configured", lambda **kw: False)
    try:
        response = server._methods["setup.runtime_check"]("profile-test", {"provider": profile.name})
        result = response["result"]
        assert result["ok"] is enabled
        if enabled:
            assert result["provider"] == profile.name
            assert result["source"] == "provider-profile"
        else:
            assert "disabled" in result["error"]
    finally:
        manager.unload("runtime-readiness-test")
