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

The patch keeps the required `turn_timeout_seconds` default at `14400.0`.
This is the cutover policy, not a claim that the current live environment matches:
the later live audit found its default had drifted back to `600.0`.

The four-file patch also:

- Enables partial SDK messages so root response starts can be observed early,
  and requires the host's `iteration_progress_v1` capability.
- Emits one monotonic `RuntimeIterationEvent` per distinct valid root response ID.
  Streamed/assembled duplicates, nested responses, chunks, and synthetic/error
  frames do not increment the parent. IDs and thinking chunks remain internal.
- Resets observed IDs and `api_call_count` in `begin_turn()`. Successful ID-less
  results may provide a positive exact-integer terminal `num_turns`; that fallback
  emits no invented live progress and never replaces observed IDs. Failed results
  cannot invent a terminal count.
- Returns the projector's count instead of a hard-coded one. Host finalization
  retains the maximum of observed and terminal counts without changing SDK budgets.

Verification uses `tests/agent/test_sdk_iteration_progress.py`,
`tests/agent/test_sdk_cutover_contract.py` and
`tests/agent/test_runtime_iteration_progress.py`. The maintained offline tests use
real 0.2.151 SDK dataclasses, SDKSession/runtime and host dispatcher, replacing
only authentication/transport and persistence/final-delivery leaves. Network and
subprocess transport are explicitly forbidden in the cutover contract tests.

The original plugin failed the carried iteration regression before merging.
The later parity extension also covers negative message shapes, real final counts,
options, and capability rejection. This is not a change to SDK token-budget policy.
The known bridge-first commentary ordering xfail remains separate; partial messages
do not resolve that live race.

## Rejected zero-usage results and fallback

The patch suppresses a failed result's receipt only when raw input/output are
numeric zero, optional cache/reasoning counters are absent or numeric zero, and
cost is absent, `None`, or numeric zero. This explicit absent-cost policy applies
only with otherwise confirmed zero work. `bool`, strings, negatives, non-finite
values, lookup/property failures, and other unknown accounting retain a receipt.
Successful zero-usage results still emit a receipt; explicit `usage=None` retains
the existing no-receipt behavior. Nonempty or malformed `model_usage` also retains
a receipt: aggregate zeros cannot disprove per-model work.

Real projector → SDKSession → runtime → host-dispatch tests assert temporary
SessionDB rows and failure phases. Whole-turn tests prove auth/billing/quota
failures can use the configured `gpt-6-astra` / `openai-codex` fallback exactly once
and restore the primary next turn (after the existing rate-limit cooldown, where
applicable). Earlier content, status, approval, tool, usage, state, or compaction
evidence still blocks replay; display-only iteration progress does not.

The receipt is `merge-evidence/cutover/sdk-reproduction.json` (not the evidence
root). There are still 16 source files: `content_events.py` was already patched,
so this port updates its hash rather than adding a seventeenth file. Verify the
entire installed source set by replaying the pinned original wheel in a fresh
temporary directory and reverse-checking the installed candidate patch:

```sh
.venv-safe/bin/python scripts/runtime-plugin-patches/verify_claude_sdk_reproduction.py --wheel /private/tmp/hermes_claude_agent_sdk-0.1.0-py3-none-any.whl
```

This verification does not import either runtime or alter the installed package.
After an authorized patch change, `--record` updates the receipt only after exact
source-set/hash equality; normal verification also checks the recorded hashes.
`MERGE-LOG.md` records the exact isolated regression commands and results.

`uv sync` without `--inexact` removes packages not in the lockfile, including the
standalone plugin. Reinstall the source wheel and reapply this patch after such
a sync. Use the `.venv-safe/bin/python` interpreter explicitly when testing;
`.venv` is disposable and some CLI/install tests can recreate it.
