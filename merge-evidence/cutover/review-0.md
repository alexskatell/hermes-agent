**The parent’s current narrow port is correct for LIVE parity. Add one proven missing regression; no further production hunk is needed.**

- Reviewed the current four-file diff. The functional change stays inside `gateway/run_turn_runner.py::TurnRunner._setup_stream_consumer`; the two other runtime changes are diagnostics. Upstream approval/egress safeguards and `persist_user_display_metadata` remain intact.
- Keep the restored `_touch_activity` assertion. A mutation removing activity updates passed the original no-op test and failed the restored assertion.

**Missing regression**

Add `test_repeated_commentary_then_distinct_segment_does_not_concatenate` from the scratch probe file to `tests/gateway/test_runtime_interim_multi_commentary.py`.

It exercises **A → tool → repeated A → tool → B → tool**, requiring exactly `[A, B]`. Removing only the boundary-time `pending_commentary.clear()` left all three existing commentary files green with their usual xfail. The new test caught the resulting `"Inspecting config.Inspecting logs."` concatenation. Restoring the clear passed.

**Offline regression matrix**

Against a scratch copy of the parent’s current source:

- Runtime commentary: **4 passed**; multiple commentary: **1 passed**.
- SDK integration: **2 passed, 1 xfailed**.
- Strengthened iteration test: **9 passed**; SDK iteration: **2 passed**.
- Upstream stream-final contracts: **8 passed**.
- Supplemental probes: **6 passed**, including dedup carry-over, streaming-on final ownership, TTS with interims on/off, activity-test sensitivity, and parent-cleanup relay behavior.
- Final eleven-file batch: **81 passed, 0 failed, 1 expected failure**. This intentionally includes both iteration-test versions.
- Native admission, `/agents`, and selected grouped-completion cases: **8 passed** separately.

The **bridge-first SDK race remains real**: forcing `--runxfail -k bridge-first` failed. Commentary can arrive after its tool boundary. Treat that as a known LIVE defect, not a verified ordering guarantee.

**Native progress lifecycle**

- `_ChildProgressRelay` captures the parent callback and emits grouped progress every five tool starts, plus a final flush.
- Gateway `progress_callback` drops ordinary `subagent.*` progress events; only terminal failure notices get special handling.
- Parent-turn cleanup cancels the progress sender and heartbeat. Normal cleanup preserves the generation, so a late failure notice can still post until a newer turn invalidates it. Rebinding the parent callback does not update the child’s captured callback.
- The independent `_async_delegation_watcher` still delivers idle completions, grouping same-tick results by origin route and parent session. `/agents` provides live activity on demand.

Use native `/agents` and grouped completion events for this handoff. `tool_progress_grouping=accumulate` cannot repair the discarded events or cancelled sender. No cron watcher is warranted.

Suggested status: **“Cutover review: commentary checks passed; handoff pending.”**

Only `/private/tmp/hermes-commentary-review-j_hlefte` was written. Full evidence: `REVIEW.md`, `results.json`, raw logs, `functional-only-port.patch`, and `candidate/tests/gateway/test_review_probes.py`. No checkout, settings, skills, service, or external-system writes by this lane.