"""Offline candidate provenance and installed-provider verification.

Run with the candidate interpreter and a fresh, empty HOME via env -i.
This does not create an SDK client, read credentials, or contact a provider.
"""
from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
from importlib.metadata import entry_points, version

ROOT = Path(__file__).resolve().parents[2]
START = "3e77460170458c41870bc93b95a0f50efc3d576e"
UPSTREAM = "c32e0acb0ec59d53ac964007c75630e098bcd045"
OUT = Path(__file__).resolve().parent


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def save(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    assert ROOT == Path("/Users/oc/workspace/hermes-upstream-merge-20260908")
    assert Path(sys.prefix).resolve() == ROOT / ".venv-safe"
    assert Path.home().resolve().parent == Path("/private/tmp")
    assert Path.home().name.startswith("hermes-merge.")
    assert git("rev-parse", START) == START
    assert git("rev-parse", "upstream/main") == UPSTREAM
    new_commits = git("rev-list", f"{START}..{UPSTREAM}").splitlines()
    preserved_commits = git("rev-list", f"{UPSTREAM}..{START}").splitlines()
    touched = sorted(set(git(
        "log", "--no-merges", "--format=", "--name-only",
        f"{START}..{UPSTREAM}", "--", "tests/gateway", "tests/agent", "tests/tools",
    ).splitlines()) - {""})
    original = json.loads((ROOT / "merge-evidence/cutover/final-files.json").read_text(encoding="utf-8"))
    assert len(original) == len(set(original)) == 23
    manifest = list(dict.fromkeys(original + ["tests/tools/test_mcp_discovery_retry.py"] + touched))
    assert len(manifest) <= 60
    assert all(f.endswith(".py") and (ROOT / f).is_file() for f in manifest)
    assert not any(f.startswith("tests/hermes_cli/test_update") for f in manifest)
    discovery = ["tools/mcp_tool_discovery.py", "tools/mcp_tool_lifecycle.py",
                 "hermes_cli/config_defaults.py", "tests/tools/test_mcp_discovery_retry.py"]
    assert not git("diff", START, "--", *discovery)
    dependencies = git("diff", "--name-only", START, "--", "pyproject.toml", "uv.lock").splitlines()
    assert not dependencies
    save("provenance.json", {
        "start_head": START, "upstream_sha": UPSTREAM,
        "commits_merged": len(new_commits), "upstream_commits": new_commits,
        "preserved_exclusive_commit_count": len(preserved_commits),
        "preserved_exclusive_commits": preserved_commits,
        "conflicts": [], "python_dependency_changes": dependencies,
        "touched_test_files": touched, "required_test_file_count": len(manifest),
        "discovery_feature_byte_unchanged_from_start": discovery,
    })
    save("required-files.json", manifest)

    # Exercise the production opt-in and discovery paths in an isolated home.
    home = Path.home() / ".hermes"
    home.mkdir(exist_ok=True)
    os.environ["HERMES_HOME"] = str(home)
    (home / "config.yaml").write_text(
        "plugins:\n  enabled: [claude-agent-sdk]\n  disabled: []\n", encoding="utf-8"
    )
    sys.path.insert(0, str(ROOT))
    eps = [ep for ep in entry_points(group="hermes_agent.plugins") if ep.name == "claude-agent-sdk"]
    assert len(eps) == 1 and eps[0].value == "hermes_claude_agent_sdk"
    assert "hermes_claude_agent_sdk" not in sys.modules
    from providers import get_provider_profile
    profile = get_provider_profile("claude-agent-sdk")
    assert profile is not None and profile.name == "claude-agent-sdk"
    assert "hermes_claude_agent_sdk" in sys.modules
    plugin = importlib.import_module("hermes_claude_agent_sdk")
    from hermes_cli.plugins import discover_plugins, get_plugin_manager
    discover_plugins()
    registration = get_plugin_manager().get_agent_runtime(plugin.RUNTIME_ID)
    assert registration is not None
    assert registration.factory is plugin.create_runtime
    from hermes_claude_agent_sdk.configuration import SDKSessionConfiguration
    default_timeout = inspect.signature(SDKSessionConfiguration.create).parameters["turn_timeout_seconds"].default
    actual_timeout = SDKSessionConfiguration.create(cwd=str(ROOT)).turn_timeout_seconds
    assert default_timeout == actual_timeout == 14400.0
    assert plugin.__file__ is not None
    source_dir = Path(plugin.__file__).resolve().parent
    assert source_dir == ROOT / ".venv-safe/lib/python3.12/site-packages/hermes_claude_agent_sdk"
    previous = json.loads((ROOT / "merge-evidence/cutover/sdk-reproduction.json").read_text(encoding="utf-8"))
    hashes = {name: hashlib.sha256((source_dir / name).read_bytes()).hexdigest()
              for name in previous["plugin_source_sha256"]}
    assert hashes == previous["plugin_source_sha256"]
    codex = get_provider_profile("openai-codex")
    assert codex is not None and codex.api_mode == "codex_responses"
    codex_modules = ["plugins.model_providers.openai_codex", "agent.codex_runtime",
                     "agent.codex_responses_adapter", "agent.transports.codex"]
    imported_codex = {}
    for name in codex_modules:
        module = importlib.import_module(name)
        assert module.__file__ is not None
        imported_codex[name] = str(Path(module.__file__).resolve())
    assert all(Path(path).is_relative_to(ROOT) for path in imported_codex.values())
    receipt = {
        "python": sys.executable, "python_version": sys.version.split()[0],
        "hermes_version": version("hermes-agent"),
        "plugin_version": version("hermes-claude-agent-sdk"),
        "sdk_version": version("claude-agent-sdk"), "import_path": str(source_dir),
        "entry_point": {"group": eps[0].group, "name": eps[0].name, "value": eps[0].value},
        "provider_registered_via_production_discovery": profile.name,
        "runtime_registered_via_plugin_manager": registration.descriptor.runtime_id,
        "factory_identity_verified": True,
        "turn_timeout_seconds_default": default_timeout,
        "constructed_turn_timeout_seconds": actual_timeout,
        "all_16_plugin_sources_match_tracked_patch_receipt": True,
        "plugin_source_sha256": hashes, "patch_reapplied": False,
        "openai_codex_profile": {"name": codex.name, "api_mode": codex.api_mode},
        "codex_imports": imported_codex,
        "no_credentials_or_provider_inference": True,
    }
    save("plugin-verification.json", receipt)
    print(json.dumps({"commits_merged": len(new_commits),
                      "preserved_commits": len(preserved_commits),
                      "required_test_files": len(manifest), "plugin": receipt}, indent=2))


if __name__ == "__main__":
    main()
