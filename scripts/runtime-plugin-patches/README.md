# Claude SDK host-delta patch

Only the isolated merge worktree's environment is patched. The live checkout,
its environment, and profile settings are not patch targets.

The source wheel `hermes_claude_agent_sdk-0.1.0-py3-none-any.whl` has SHA-256
`f481b2ae859338d4d9dc6ae05bece9c10a97532474337f949a1db353313d3d9b`.
The installed provider SDK is `claude-agent-sdk==0.2.151`.

After installing the original plugin wheel into `.venv-safe`, apply the tracked
patch from the repository root:

```sh
git apply --directory=.venv-safe/lib/python3.12/site-packages scripts/runtime-plugin-patches/claude-sdk-0.1.0-host-delta.patch
```

The patch sets the constructor default `turn_timeout_seconds` to `14400.0`,
matching the inspected live configuration exactly. It also completes the carried
`iteration_progress_v1` contract: root SDK response IDs emit one monotonic
`RuntimeIterationEvent` each, streamed/assembled duplicates are ignored, nested
subagent responses do not increment the parent, and `begin_turn()` resets the
counter. IDs remain internal and are not emitted as visible content.

Verification uses `tests/agent/test_sdk_iteration_progress.py`, including actual
0.2.151 SDK dataclasses, plus `tests/agent/test_runtime_iteration_progress.py`.
The original plugin failed the carried iteration regression before merging;
this is a local-delta repair, not a change to upstream SDK policy or token budget.

`uv sync` without `--inexact` removes packages not in the lockfile, including the
standalone plugin. Reinstall the source wheel and reapply this patch after such
a sync. Use the `.venv-safe/bin/python` interpreter explicitly when testing;
`.venv` is disposable and some CLI/install tests can recreate it.
