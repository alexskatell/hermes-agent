# AgentRuntime v1 upstream merge

## Scope and provenance

- Worktree: `/Users/oc/workspace/hermes-upstream-merge-20260908`.
- Branch: `runtime-v1-upstream-merge-20260908`.
- Original live HEAD: `80332e62eb19e48ed4a1c220dc4c06fe343418ac`.
- Carried-delta commit: `902f9fc1409efa1e10a345c8f2d9842b542a9e66`,
  `chore(runtime): commit carried host delta (fallback, iteration progress, discord)`.
- Upstream merge parent: local `origin/main`, `63ec22e797ba73b369d1bcc0bcc69622edd9d7e8`.
- Pre-merge base: `006b1beb00d9d25230571d14277aca3d70e5e11f`.
- A true merge preserves the original 71 local-only commit SHAs. No rebase,
  push, `hermes update`, network fetch, service restart, profile edit, or
  launchd operation is part of this work.
- `/tmp/local-delta.patch` and the four copied untracked tests are retained.
  `merge-evidence/carried-delta.json` verifies the tracked patch and all four
  test hashes against the immutable carried-delta commit.

## Conflict resolutions

There were five unmerged paths. Upstream behavior is the default; local host
contracts are retained at their current upstream integration points.

### `agent/chat_completion_helpers.py`

- Upstream: extracted stream/nonstream helpers and made fallback activation a
  retry loop that checks cooldown/preflight viability and buffers notices after
  a successful activation.
- Local: merge a fallback entry's `request_overrides` into the active request,
  retaining the primary snapshot for restoration on the next turn.
- Resolution: disjoint intent. Keep upstream's fallback control flow. Call
  `_apply_fallback_request_overrides(agent, fb)` inside the successful fallback
  activation block, after reasoning/extra-body rescoping and before prompt
  model-identity rewriting. Deep-copy overrides; do not restore the old loop.
- Verification: fallback unit and integration tests, provider-fallback tests,
  and max-effort transport regression.

### `agent/reasoning_effort.py`

- Upstream: explicit `CODEX_ASTRA_EFFORTS` and Astra normalization; Astra's wire
  choices exclude disabled/minimal reasoning and retain `max`.
- Local: recognize `gpt-6-astra` as supporting `max`, originally by borrowing
  the GPT-5.6 effort set.
- Resolution: superseded local implementation. Keep upstream's dedicated
  Astra effort set/recognizer rather than reintroducing unsupported choices.
  Preserve the local intent that `max` reaches the Codex request. Update the
  carried transport test double with `is_codex_backend=True`, required by
  upstream's transport identity gate.

### `gateway/run_notifications.py`

- Upstream: per-task failure notices have separate deduplication identities
  from the batch's final notification. Completed children can be delivered
  independently and notifications use the current upstream admission flow.
- Local: stable, parent-scoped completion message IDs and durable API-server
  display-row replay detection across the append/ack crash window.
- Resolution: combine both. Keep local stable parent-scoped IDs but append
  `:task_failure:<task_index>` for interim failures. Durable replay lookup
  compares interim-vs-final kind and task index before recognizing an already
  persisted delivery; an interim notice must never suppress its sibling or
  the batch final. Preserve upstream delivery routing/admission semantics.
- Supporting adaptation: `gateway/wake.py` writes `task_failure_notice` and
  `task_index` into display metadata so durable dedup can make that distinction.
- New regression: `tests/gateway/test_runtime_merge_delivery_identity.py`
  exercises distinct interim/batch IDs and persisted-row discrimination.

### `tests/gateway/test_completion_delivery.py`

- Upstream: adds recovery, interim-notice, independent-completion, admission,
  and deferred-delivery regression coverage.
- Local: adds durable message ID propagation and persisted API-server replay
  tests, clarifying at-least-once transport versus durable consumer dedup.
- Resolution: disjoint intent. Retain both test sets and the precise local
  contract docstring. No test deletion or expected-failure conversion.

### `tools/async_delegation.py`

- Upstream: durable `record_unit_child` results survive an abandoned owner;
  recorded children must be replayed even when unfinished siblings are unknown.
- Local: stable parent-scoped delivery IDs and dropping wholly unknown dead-owner
  work rather than waking a parent with an empty completion.
- Resolution: combine behavior conditionally. Recovered recorded child results
  remain pending for delivery; a wholly unknown abandoned unit is dropped.
  Clear stale delivery claims in either case and retain stable IDs for recovery
  and ordinary completion events. Do not erase upstream child-result recovery.

## Auto-merged host boundaries reviewed

- Keep typed turn contracts, runtime registration/dispatch, effective prompt
  snapshots, tool inventory, usage receipts/model provenance, runtime state,
  compaction ownership, and host finalization of external runtimes.
- `agent/conversation_loop.py` restores the primary route before runtime
  selection, dispatches after host turn setup, and resumes the built-in loop
  after a pre-visible-output fallback.
- `agent/turn_runtime.py` retains phase-safe fallback and host-owned finalization;
  built-in Codex preserves its specialized short circuit.
- `gateway/run.py`, `hermes_state_registry.py`, `hermes_state_messages.py`, and
  the split `tools/delegate_tool*.py` files have no remaining delta from
  upstream: upstream already carries/supersedes their overlapping local intent.
  The locally added runtime-state modules remain present.
- Discord adapter opt-ins for auto-threading free channels and reply messages
  remain intact. Title generation still rejects malformed JSON fragments and
  counts answer-shaped output before truncation.

## Pre-existing carried-delta repairs

The pre-merge carried commit was tested in
`/tmp/hermes-host-delta-baseline-20260908`, without stashing or editing live code.

- `test_runtime_iteration_progress.py`: its fake activity callback accepted only
  keyword arguments, but the host calls it positionally. Repair the fake's
  signature; do not weaken the assertion.
- `agent/turn_runtime.py`: failed/cancelled/completed envelopes without terminal
  counts reset observed progress to zero. Preserve the maximum valid host
  progress count in finalization. The original three cases failed on the
  carried commit and pass after this repair.
- `agent/runtime_capabilities.json`: the carried API advertised
  `iteration_progress_v1` but the machine-readable manifest omitted it. Add
  the implemented capability. The unchanged manifest test failed at the
  carried commit and now passes.
- The original installed plugin never emitted iteration events. The copied
  plugin projector now emits bounded, deduplicated root-response iteration
  events and resets them per turn. Nested responses do not consume the parent
  display count or alter SDK budget policy. The tracked site-packages patch
  and real SDK dataclass regression make this reproducible.

## Environment

- `.venv-safe`: Python 3.12.13, editable Hermes 0.21.1 from this worktree.
- Frozen lockfile sync succeeds with `--inexact` so the standalone plugin is
  not removed. Extras: dev, messaging, anthropic, firecrawl, fal, edge-tts,
  mcp, bedrock, vertex, acp, wecom. All live package names are installed;
  core dependency versions follow the new lock rather than the older live env.
- Plugin: `hermes-claude-agent-sdk==0.1.0`, same source wheel as live, SHA-256
  `f481b2ae859338d4d9dc6ae05bece9c10a97532474337f949a1db353313d3d9b`.
  It was copied to `/tmp` before installation; the installed direct URL points
  at that copy. `claude-agent-sdk==0.2.151` was reconstructed from the existing
  cached wheel installation rather than replaced with a different SDK version.
- `configuration.py:73`: `turn_timeout_seconds: float = 14400.0,`.
  Configuration bytes match the inspected live site-packages copy exactly.
- `scripts/runtime-plugin-patches/claude-sdk-0.1.0-host-delta.patch` reproduces
  the timeout and iteration-projector changes from the original wheel.
- `uv pip check --python .venv-safe/bin/python`: all installed packages compatible.

## Isolation caveat

All agent-authored writes target this worktree or `/tmp`. The live tree is not
used as a test or install working directory. Later read-only checks found that
live work continued after the initial capture: `gateway/run_turn_runner.py`
gained a commentary-buffer change and an untracked iteration test changed.
The worktree and live files have different inodes; these later changes are not
silently imported or reverted. Consequently the final live delta cannot be
claimed byte-identical to the initial snapshot. The original captured delta is
verified against its carried commit instead; the final report must disclose
this limitation rather than claim a successful end-to-end byte-identity check.

## Validation results

The post-merge triage below supersedes the earlier full-suite and preliminary
baseline summaries. Only explicit, safety-reviewed file lists were executed.

## Post-merge test triage

### Scope, method, and safety

- The original summary contains **47 failing/error files**: 45 assertion-failure
  files and two no-result files. Classification: **1 merge-induced, 12
  pre-existing-upstream, 34 environment-only**. Four additional failing files
  from the supplied upstream baseline and three original retry-green flakes
  are also classified below: **54 files total; 1 merge-induced, 14
  pre-existing-upstream, 39 environment-only**. The three prohibited update
  files are included in those counts with an explicitly provisional,
  source-identical classification, not a claimed runtime baseline.
- Here, `merge-induced` means unique to the carried host delta versus pristine
  upstream. The background-review fixture mismatch already exists in the
  carried delta; it is not a newly introduced conflict-resolution bug.
- The supplied full-suite log selected **Python 3.11.15**, not `.venv-safe`.
  Anthropic and the standalone SDK plugin were missing there. This triage
  never reran the full suite. The two supplied round2 logs both contain their
  terminal `EXIT=` line. The baseline round2 run exited **4 before collection**
  because the local-only SDK test was absent; it cannot establish a baseline.
  Its merged multi-file companion reported 69 failed / 1997 passed / 36 skipped
  and includes cross-file state contamination.
- The supplied baseline worktree and local `origin/main` had advanced to
  `c8aa5608c24e3636e77c267650c0f1f52e44adb0`. A new detached worktree at
  `/tmp/hermes-triage-base-63ec22e797` pins the actual merge parent
  `63ec22e797ba73b369d1bcc0bcc69622edd9d7e8`. No network fetch was used.
  Baseline tracked source remains unchanged.
- Every new comparison uses an explicit `.py` file in a fresh pytest process,
  the merge's `.venv-safe/bin/python` (3.12.13), a clean environment, fresh
  HOME/HERMES_HOME, canonical short `/private/tmp`, and no pytest cache.
  The exact argv, environment, per-file counts, failure nodes, and raw-log path
  are committed in `merge-evidence/*.jsonl`; `commands.json` records commands
  and aggregate outcomes. A local-only absent file is recorded, never allowed
  to abort collection of unrelated baseline files.
- **Never run** `tests/hermes_cli/test_update_launchd_*.py`,
  `tests/hermes_cli/test_update_head_moved_gate.py`, or
  `tests/hermes_cli/test_update_autostash.py` on this host. Inspection of the
  latter found its discovery mocks do not block
  `_restart_gateway_fleet_after_update` → `_restart_macos_launchd_gateways`.
  The old log shows it reaching launchd supervision failures. None of these
  files was executed during this triage, even with mocks.
- No live checkout/profile edits, service operations, `hermes update`, push,
  fetch, or skill-store edits were performed. `gateway/run_turn_runner.py`
  is byte-unchanged relative to the starting merge; the separate in-flight
  `pending_commentary` change is intentionally left for its owning lane.
- Six generated MagicMock database/lock artifacts (540672 bytes) from the
  earlier test lane were preserved, not committed or deleted, at
  `/private/tmp/hermes-merge-mock-artifacts-fswrlgqq/MagicMock`.

### Repairs and retained work

- `53f9f4daec43e05c0774389721d9d603de59a275` retains the previous lane's
  `gateway/wake.py` metadata repair. Persist both `task_failure_notice` and
  `task_index` so the merged durable replay check cannot collapse an interim
  sibling or the batch final. The three real-DB delivery-identity cases pass.
- `1e1f8a0d4eca7f92b4d21426c42222676da87c5b` initializes
  `_fallback_activated=False` in the bare background-review fixture. The
  four failures were missing fixture state reached by the intentional early
  route restoration. The real cancellation, relay-ordering, and runtime
  selection paths remain exercised. Captured worker errors now appear in
  boundary assertion failures. Red: 4 failed / 11 passed. Green: 15 passed.
- The same test commit moves two carried host-service mocks from the deprecated
  `run_agent.handle_function_call` compatibility pointer to the canonical
  `model_tools.handle_function_call`. No assertion was weakened. All 290 cases
  pass with compatibility warnings promoted to errors.
- Keep the real SDK dataclass iteration regression and patch README from the
  previous lane. Reverse patch-check confirms the installed plugin matches
  the tracked timeout/iteration patch. `uv pip check` finds all 134 packages
  compatible. No venv package or SDK configuration was changed in this triage.
- No test was deleted, xfailed, skipped, or excluded to hide a merge regression.
  The original platform-marked skips and existing performance xfail/xpass
  outcomes are reported as returned. The three update safety exclusions
  above are explicit task constraints, not test modifications.
- Review stayed proportional to a three-line metadata repair and fixture/mock
  changes: exact-parent comparisons, red/green assertions, real-DB delivery
  tests, strict compatibility warnings, targeted Ruff, and diff/security scan.
  No independent reviewer approval is claimed; hooks were disabled for local
  commits so an inherited hook could not launch an unsafe suite.

### Commands and results

All commands below ran from `/Users/oc/workspace/hermes-upstream-merge-20260908`.
The manifest files contain explicit filenames only; no directory discovery or
full-suite selector is permitted. Each batch expands to
`.venv-safe/bin/python -m pytest -q -p no:cacheprovider <one-file>` with the
recorded isolated environment. This uses the task's explicitly permitted
pytest form because the canonical shell runner would select a different venv.

- `.venv-safe/bin/python merge-evidence/run_triage.py --manifest merge-evidence/triage-files.json --label differential --trees both --jobs 4 > /tmp/hermes-triage-differential.log 2>&1`
  - Exact parent: 2666 passed, 63 failed, 44 skipped; one 240s file timeout;
    local-only SDK file absent. Merged: 2680 passed, 61 failed, 44 skipped;
    one 240s file timeout. 48 file records per tree. The merged half ran after
    the background fixture repair; its independent red run is preserved.
- `.venv-safe/bin/python merge-evidence/run_triage.py --manifest merge-evidence/regression-files.json --label regression --trees merged --jobs 3 > /tmp/hermes-triage-regression.log 2>&1`
  - 163 passed, zero failures, ten files.
- `.venv-safe/bin/python merge-evidence/run_triage.py --manifest merge-evidence/extra-files.json --label extra --trees both --jobs 2 > /tmp/hermes-triage-extra.log 2>&1`
  - Each tree: 43 passed, one existing xfailed, one existing xpassed; four files.
    Includes the three original flakes and `test_watchdog_review_76354.py`.
    The latter passes all seven tests on each tree and is not in the supplied
    baseline failing summary; no observed failure is attributed to it.
- `.venv-safe/bin/python merge-evidence/run_triage.py --manifest merge-evidence/retry-files.json --label retry --trees both --jobs 1 > /tmp/hermes-triage-retry.log 2>&1`
  - Exact parent: 215 passed, two failed. Merged: 216 passed, one failed.
    Four files each; lock patience passes on both, heartbeat still fails on
    both, and the upstream FD-ownership failure is again reproduced.
- `.venv-safe/bin/python merge-evidence/run_triage.py --manifest merge-evidence/final-regression-files.json --label final-regression --trees merged --jobs 3 > /tmp/hermes-triage-final-regression.log 2>&1`
  - **453 passed, zero failures, eleven files**. The eight specifically
    requested regression files account for **146 passing tests**;
    the other files cover SDK iteration, background review, and host-tool dispatch.
- The two isolated background-review commands and the strict compatibility
  command, including their `env -i`/temporary-HOME prefixes and log paths, are
  preserved verbatim in `merge-evidence/commands.json`.
  `/tmp/hermes-triage-background-red.log`: 4 failed / 11 passed.
  `/tmp/hermes-triage-background-green.log`: 15 passed.
  `/tmp/hermes-triage-canonical-dispatch.log`: 290 passed, zero warnings.
- `.venv-safe/bin/ruff check gateway/wake.py tests/agent/test_sdk_iteration_progress.py tests/run_agent/test_background_review.py tests/run_agent/test_run_agent.py merge-evidence/run_triage.py`
  - First run caught one missing UTF-8 argument in the new evidence runner;
    corrected. Final result: `All checks passed!`.
- `git diff --check`: passed.
- `git apply --reverse --check --directory=.venv-safe/lib/python3.12/site-packages scripts/runtime-plugin-patches/claude-sdk-0.1.0-host-delta.patch`: passed, read-only verification.
- `uv pip check --python .venv-safe/bin/python`: all 134 installed packages compatible.

The first evidence runner returned zero when orchestration finished even if
individual files failed; its JSONL per-file exits and counts, not that wrapper
exit, are authoritative. The retained runner now propagates a nonzero exit
when any executed file fails. The retry batch verified that failure path;
the final-regression batch verified success. No results were synthesized.

### Per-file classification

Format: file: classification: evidence: action. `classifications.json` holds
machine-readable provenance and exact-node evidence for all 54 entries.
- `tests/agent/test_auxiliary_client.py`: **pre-existing-upstream**: Upstream deadline test has a sub-140ms wall-clock bound; failed on the exact-parent baseline and passes intermittently in fresh processes. Baseline 1 failed, 203 passed in 8.28s (exit 1); merged 204 passed in 7.27s (exit 0). Action: Leave unchanged; not a merge regression.
- `tests/agent/test_auxiliary_named_custom_providers.py`: **environment-only**: Original runner selected Python 3.11 without Anthropic dependencies, changing provider construction/autodetection. Both trees pass with the same installed Python 3.12 venv. Baseline 20 passed in 2.31s (exit 0); merged 20 passed in 2.17s (exit 0). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/agent/test_auxiliary_transport_autodetect.py`: **environment-only**: Original runner selected Python 3.11 without Anthropic dependencies, changing provider construction/autodetection. Both trees pass with the same installed Python 3.12 venv. Baseline 16 passed in 1.19s (exit 0); merged 16 passed in 1.19s (exit 0). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/agent/test_codex_aux_timeout_fd_ownership.py`: **pre-existing-upstream**: Upstream timer/owner-thread test intermittently misses shutdown before client.close; reproduced on the exact-parent baseline. Baseline 1 failed, 1 passed in 2.16s (exit 1); merged 2 passed in 1.77s (exit 0). Action: Leave unchanged; not a merge regression.
- `tests/agent/test_command_token_source.py`: **environment-only**: Original runner selected Python 3.11 without Anthropic dependencies, changing provider construction/autodetection. Both trees pass with the same installed Python 3.12 venv. Baseline 29 passed in 1.34s (exit 0); merged 29 passed in 1.00s (exit 0). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/agent/test_fallback_dynamic_credential.py`: **environment-only**: Original runner selected Python 3.11 without Anthropic dependencies, changing provider construction/autodetection. Both trees pass with the same installed Python 3.12 venv. Baseline 5 passed in 1.21s (exit 0); merged 5 passed in 0.87s (exit 0). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/agent/test_nous_portal_anthropic_wire.py`: **environment-only**: Original runner selected Python 3.11 without Anthropic dependencies, changing provider construction/autodetection. Both trees pass with the same installed Python 3.12 venv. Baseline 25 passed in 1.22s (exit 0); merged 25 passed in 0.82s (exit 0). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/agent/test_sdk_iteration_progress.py`: **environment-only**: Original Python 3.11 runner lacked the standalone plugin. The local-only test is absent upstream and passes twice using the installed, patched SDK in .venv-safe. Absent in pristine upstream; merged 2 passed. Action: Keep the prior real-SDK dataclass regression and reproducible patch README; verify installed patch without modifying the venv.
- `tests/agent/test_set_runtime_main_custom_provider.py`: **environment-only**: Original runner selected Python 3.11 without Anthropic dependencies, changing provider construction/autodetection. Both trees pass with the same installed Python 3.12 venv. Baseline 5 passed in 1.14s (exit 0); merged 5 passed in 0.77s (exit 0). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/agent/test_vision_routing_31179.py`: **environment-only**: Original runner selected Python 3.11 without Anthropic dependencies, changing provider construction/autodetection. Both trees pass with the same installed Python 3.12 venv. Baseline 8 passed in 3.40s (exit 0); merged 8 passed in 1.75s (exit 0). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/computer_use/test_cua_no_overlay.py`: **environment-only**: The macOS CuaDriver.app prerequisite is absent from the isolated test home; both trees raise the same prerequisite error. Baseline 1 failed, 9 passed, 5 skipped in 0.46s (exit 1); merged 1 failed, 9 passed, 5 skipped in 0.22s (exit 1). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/cron/test_file_permissions.py`: **environment-only**: Original run inherited directory permissions; both trees pass with fresh isolated HOME/HERMES_HOME. Baseline 7 passed in 0.51s (exit 0); merged 7 passed in 0.17s (exit 0). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/gateway/test_buzz_adapter.py`: **environment-only**: Fixture creates a path beyond the macOS pathname limit (Errno 63); identical failure on both trees. Baseline 1 failed, 185 passed in 3.22s (exit 1); merged 1 failed, 185 passed in 2.31s (exit 1). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/gateway/test_scale_to_zero.py`: **environment-only**: Original AF_UNIX path is too long on macOS; both trees pass with the shorter /private/tmp sandbox. Baseline 25 passed in 0.78s (exit 0); merged 25 passed in 0.39s (exit 0). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/gateway/test_shutdown_forensics.py`: **environment-only**: The diagnostic spawner requires the GNU timeout executable, absent from this macOS PATH; both trees return None. Baseline 1 failed, 9 passed in 0.58s (exit 1); merged 1 failed, 9 passed in 0.28s (exit 1). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/gateway/test_systemd_notify.py`: **environment-only**: The test assumes Linux abstract UNIX-domain sockets on macOS; identical failure on both trees. Baseline 1 failed, 2 passed in 0.55s (exit 1); merged 1 failed, 2 passed in 0.23s (exit 1). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/gateway/test_voice_command.py`: **pre-existing-upstream**: Both exact-parent and merged per-file runs stall after 43 progress dots and hit the 240s process timeout; the earlier multi-file baseline result is not equivalent isolation. Baseline no summary (exit 124); merged no summary (exit 124). Action: Leave unchanged; not a merge regression.
- `tests/hermes_cli/test_dashboard_auth_gate.py`: **environment-only**: Port 9119 is already occupied on this host; both trees report BACKEND_PORT_IN_USE and exit 75. No service was stopped. Baseline 2 failed, 31 passed in 1.93s (exit 1); merged 2 failed, 31 passed in 1.47s (exit 1). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/hermes_cli/test_plugin_scanner_recursion.py`: **environment-only**: Installed claude-agent-sdk entry point invalidates a fixed plugin-count assertion on both trees. Baseline 1 failed, 11 passed in 1.69s (exit 1); merged 1 failed, 11 passed in 0.98s (exit 1). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/hermes_cli/test_plugins.py`: **environment-only**: Installed claude-agent-sdk entry point adds a second non-bundled plugin to the upstream fixed-count fixture on both trees. Baseline 1 failed, 75 passed in 5.04s (exit 1); merged 1 failed, 75 passed in 3.93s (exit 1). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/hermes_cli/test_plugins_cmd_category_discovery.py`: **environment-only**: Installed claude-agent-sdk entry point adds an unexpected plugin to upstream fixed-count assertions on both trees. Baseline 2 failed, 11 passed in 0.63s (exit 1); merged 2 failed, 11 passed in 0.41s (exit 1). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/hermes_cli/test_session_recovery_lost_and_found.py`: **pre-existing-upstream**: The unsafe-system-sqlite error message no longer contains the expected .recover wording; same failing assertion on the exact-parent baseline. Baseline 1 failed, 9 passed, 2 skipped in 1.43s (exit 1); merged 1 failed, 9 passed, 2 skipped in 1.08s (exit 1). Action: Leave unchanged; not a merge regression.
- `tests/hermes_cli/test_update_autostash.py`: **pre-existing-upstream**: Static classification only: test and update implementation are identical to the exact parent. The original log reaches a launchd supervision failure. Its gateway-discovery fixture does not stub the macOS fleet restart path. Not executed; safety exclusion. Action: DO NOT RUN on this host. Source-identical classification is provisional without a safe isolated-service baseline; recorded as unresolved safety exclusion.
- `tests/hermes_cli/test_update_head_moved_gate.py`: **pre-existing-upstream**: Static classification only: test and update implementation are identical to the exact parent; original success-path test exits 1 in the fleet-restart phase. Not executed; safety exclusion. Action: DO NOT RUN on this host. Source-identical classification is provisional without a safe isolated-service baseline; recorded as unresolved safety exclusion.
- `tests/hermes_cli/test_update_launchd_fleet_restart.py`: **pre-existing-upstream**: Static classification only: upstream-identical test/source; original failures include live PID leakage and stale launchctl/systemctl warning expectations. Not executed; safety exclusion. Action: DO NOT RUN on this host. Source-identical classification is provisional without a safe isolated-service baseline; recorded as unresolved safety exclusion.
- `tests/perf_guards/test_pattern_b_scaling.py`: **environment-only**: Original 20-worker run crossed the wall-clock scaling threshold once; original retry and both lower-concurrency per-file reruns pass. Baseline 2 passed, 1 xfailed, 1 xpassed in 1.30s (exit 0); merged 2 passed, 1 xfailed, 1 xpassed in 0.64s (exit 0). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/plugins/memory/test_hindsight_provider.py`: **environment-only**: Optional hindsight-client/client_api dependencies are absent and lazy installs are disabled; identical dependency-driven failures on both trees. Baseline 8 failed, 77 passed, 1 skipped, 3 warnings in 5.93s (exit 1); merged 8 failed, 77 passed, 1 skipped, 3 warnings in 2.13s (exit 1). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/run_agent/test_background_review.py`: **merge-induced**: Early primary-route restoration from the carried AgentRuntime delta reaches a missing _fallback_activated attribute in the upstream bare-agent fixture. Exact parent passes 15; merged diagnostic run fails 4/15; initialized fixture passes 15. This local-delta incompatibility was inherited, not introduced by a conflict edit. Baseline 15 passed in 1.57s (exit 0); merged 15 passed in 0.84s (exit 0). Action: Set the initialized fallback flag in the fixture and include captured worker errors in boundary assertions; preserve real runtime selection, cancellation, and relay ordering.
- `tests/run_agent/test_run_agent.py`: **environment-only**: Original runner lacked anthropic. Both trees pass in Python 3.12 with the installed dependency; no streaming or provider source change is needed. Baseline 284 passed in 37.99s (exit 0); merged 290 passed, 1 warning in 29.08s (exit 0). Action: Also port two carried runtime-host mock targets to model_tools.handle_function_call; 290 tests pass with compatibility warnings treated as errors.
- `tests/run_agent/test_streaming.py`: **environment-only**: Original runner lacked anthropic. Both trees pass in Python 3.12 with the installed dependency; no streaming or provider source change is needed. Baseline 42 passed in 8.38s (exit 0); merged 42 passed in 6.66s (exit 0). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/run_agent/test_switch_model_reasoning_override.py`: **environment-only**: Original runner lacked anthropic. Both trees pass in Python 3.12 with the installed dependency; no streaming or provider source change is needed. Baseline 2 passed in 1.09s (exit 0); merged 2 passed in 0.61s (exit 0). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/run_agent/test_tool_activity_heartbeat.py`: **pre-existing-upstream**: The test expects two callbacks in 120ms while the implementation floors the interval at 100ms; reproduced unchanged on the exact parent. Baseline 1 failed, 4 passed in 2.93s (exit 1); merged 1 failed, 4 passed in 1.82s (exit 1). Action: Leave unchanged; not a merge regression.
- `tests/scripts/test_contributor_map.py`: **environment-only**: Case-insensitive macOS filesystem makes lower-case and mixed-case fixture paths alias; identical failure on both trees. Baseline 1 failed, 10 passed in 0.57s (exit 1); merged 1 failed, 10 passed in 0.35s (exit 1). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/state/test_write_lock_patience.py`: **pre-existing-upstream**: The exhausted-patience assertion is timing-sensitive: exact parent fails once, merged passes, and isolated retries are recorded separately. Baseline 1 failed, 5 passed in 9.29s (exit 1); merged 6 passed in 8.65s (exit 0). Action: Leave unchanged; not a merge regression.
- `tests/test_guest_durability_barriers.py`: **pre-existing-upstream**: Default durability applies FULL (2), while the upstream unset-config test expects NORMAL (1); same failure on both trees. Baseline 1 failed, 2 passed in 0.42s (exit 1); merged 1 failed, 2 passed in 0.33s (exit 1). Action: Leave unchanged; not a merge regression.
- `tests/test_hermes_state.py`: **environment-only**: Original Python 3.11 FTS trace assertion fails; both exact-parent and merged Python 3.12 per-file runs pass. Multi-file round2 pragma failures disappear with per-file isolation. Baseline 259 passed, 2 skipped in 9.48s (exit 0); merged 259 passed, 2 skipped in 9.33s (exit 0). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/test_managed_runtime_resolution.py`: **environment-only**: Repository-wide AST guard descends into the nonstandard .venv-safe name and flags third-party mcp/cli/claude.py. The baseline has no in-tree venv; no Hermes source lookup is implicated. Baseline 7 passed in 1.38s (exit 0); merged 1 failed, 6 passed in 2.69s (exit 1). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/test_tui_gateway_server.py`: **environment-only**: Original dependency-sensitive provider enumeration and round2 multi-file toolset pollution disappear in clean Python 3.12 per-file runs on both trees. Baseline 637 passed in 39.64s (exit 0); merged 641 passed in 32.83s (exit 0). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/tools/test_approval.py`: **pre-existing-upstream**: The nonrecursive cleanup test expects an allowed result for a path that the current upstream protected-root policy denies; same assertion on both trees. Baseline 1 failed, 117 passed in 5.54s (exit 1); merged 1 failed, 117 passed in 4.54s (exit 1). Action: Leave unchanged; not a merge regression.
- `tests/tools/test_code_kernel.py`: **pre-existing-upstream**: Parallel cell test observes an empty output instead of 1; reproduced on both trees with the same venv and isolated homes. Baseline 1 failed, 21 passed in 7.92s (exit 1); merged 1 failed, 21 passed in 7.10s (exit 1). Action: Leave unchanged; not a merge regression.
- `tests/tools/test_code_kernel_remote.py`: **pre-existing-upstream**: Original run exposed dictionary-changed-size during unsynchronized iteration over _REMOTE_KERNELS. Source is upstream-identical; original retry and both fresh per-file reruns pass. Baseline 13 passed in 3.24s (exit 0); merged 13 passed in 3.02s (exit 0). Action: Leave unchanged; not a merge regression.
- `tests/tools/test_daytona_environment.py`: **environment-only**: Optional daytona==0.155.0 is absent and lazy installs are disabled; all 15 cases fail identically on both trees. Baseline 15 failed in 1.27s (exit 1); merged 15 failed in 0.99s (exit 1). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/tools/test_delegate.py`: **environment-only**: Original assertion compares /tmp or /var to their /private aliases as strings. Both trees pass with canonical /private/tmp temporary paths; child DB still targets the parent profile. Baseline 81 passed in 6.89s (exit 0); merged 81 passed in 4.92s (exit 0). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/tools/test_execution_flag_detection.py`: **environment-only**: Fixture assumes GNU sort/man/script option semantics; macOS binaries do not execute the leading-dash marker. Identical three failures on both trees. Baseline 3 failed, 81 passed, 1 skipped in 74.81s (0:01:14) (exit 1); merged 3 failed, 81 passed, 1 skipped in 73.30s (0:01:13) (exit 1). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/tools/test_file_tools.py`: **environment-only**: Expected /tmp paths differ from macOS canonical /private/tmp paths; two identical mock-argument failures on both trees. Baseline 2 failed, 45 passed, 2 skipped in 1.96s (exit 1); merged 2 failed, 45 passed, 2 skipped in 1.83s (exit 1). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/tools/test_file_tools_live.py`: **environment-only**: Original run hit a process-exit cleanup race (ProcessLookupError); original retry and both fresh per-file reruns pass. Baseline 21 passed in 2.79s (exit 0); merged 21 passed in 2.49s (exit 0). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/tools/test_process_registry.py`: **environment-only**: Eight upstream systemd-scope tests are not Linux-marked and run on macOS, where the production systemd gate correctly stays off. Same failures on both trees; round2 grace-value pollution disappears per-file. Baseline 8 failed, 94 passed, 5 skipped, 1 warning in 10.14s (exit 1); merged 8 failed, 94 passed, 5 skipped, 1 warning in 9.99s (exit 1). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/tools/test_read_file_utf8_binary_regression.py`: **environment-only**: Native rg cleanup encounters macOS killpg PermissionError; identical failure on both trees. Baseline 1 failed, 11 passed in 2.60s (exit 1); merged 1 failed, 11 passed in 1.77s (exit 1). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/tools/test_search_native_rg.py`: **environment-only**: Original rg native subprocess failures disappear with the clean venv/PATH and per-file environment on both trees. Baseline 3 passed in 3.78s (exit 0); merged 3 passed in 3.36s (exit 0). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/tools/test_search_zero_match_and_multipath.py`: **environment-only**: Original rg subprocess failures disappear with the clean venv/PATH and per-file environment on both trees. Baseline 19 passed in 2.01s (exit 0); merged 19 passed in 1.57s (exit 0). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/tools/test_transcription_tools.py`: **pre-existing-upstream**: Both trees fail the compute-type mock expectation (int8 versus float32) and the 100ms command-idle deadline; retained as upstream test/configuration and timing failures. Baseline 2 failed, 52 passed in 3.23s (exit 1); merged 2 failed, 52 passed in 2.52s (exit 1). Action: Leave unchanged; not a merge regression.
- `tests/tools/test_voice_mode.py`: **environment-only**: Remaining WSL2 shell assumptions fail on macOS on both trees; per-file isolation also removes the round2 Pulse socket contamination. Baseline 2 failed, 38 passed, 22 skipped in 1.54s (exit 1); merged 2 failed, 38 passed, 22 skipped in 1.24s (exit 1). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/tools/test_wake_word.py`: **environment-only**: Optional ai-edge-litert/tflite runtime is absent on this Mac; same dependency failure on both trees. Baseline 1 failed, 24 passed, 4 skipped in 1.78s (exit 1); merged 1 failed, 24 passed, 4 skipped in 1.56s (exit 1). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.
- `tests/tools/test_web_tools_config.py`: **environment-only**: Optional parallel-web==0.4.2 is absent and lazy installs are disabled; identical dependency errors on both trees. Baseline 2 failed, 50 passed in 2.08s (exit 1); merged 2 failed, 50 passed in 1.52s (exit 1). Action: Use the verified isolated Python 3.12 runner; leave product/test policy unchanged.

### Remaining limits

- **61 failing tests in 25 files remain**, all explicitly classified as
  pre-existing-upstream or environment-only; see the list and exact failed
  nodes above/in JSONL. They were not changed to make a green headline.
- `tests/gateway/test_voice_command.py` times out at 240 seconds on both
  exact-parent and merged trees. No per-test pass total is inferred from its
  incomplete progress output.
- The three update files are source-identical to the exact parent but not
  runtime-validated during this triage. Their classifications are provisional
  and they remain safety exclusions until a host with isolated service state
  is available. Do not use production gateways to validate them.
- `tests/test_managed_runtime_resolution.py` still sees `.venv-safe` as source;
  its sole offending path is an installed third-party dependency, not Hermes.
  Other retained environment failures include missing optional dependencies,
  macOS/GNU and systemd assumptions, path aliases/limits, and occupied port 9119.
- No merge-induced failure remains in the executed file set. The pending live
  commentary-buffer change has not been ported or validated by this lane.

- During final evidence review, a separate cutover snapshot appeared at
  `merge-evidence/rollback-20260908/` (files timestamped 13:04 EDT). It is
  outside this triage, remains untouched and untracked, and is excluded from
  these commits. The owning lane must decide how to retain it.
