# Reusing the isolated test comparison

1. Pin the exact upstream merge parent, not a moving remote-tracking ref. Use
   an authorized detached `/tmp` worktree; never stash or reset a live checkout.
2. Inspect explicit test files and their service-call seams before execution.
   Never run a full suite or any launchd/update restart test on a production host.
   The recorded manifests are reviewed for this task only, not universal safe lists.
3. Use the same named venv interpreter on both trees. Isolate each file in a new
   process with a clean environment and short, canonical temporary HOME and
   HERMES_HOME. A custom `.venv-safe` can be accidentally scanned by AST guards.
4. Record absent local-only tests rather than passing their paths to a baseline
   multi-file pytest invocation. Otherwise one missing path aborts the baseline.
5. Compare failure nodes and causes, not just aggregate counts. Same-source
   platform/dependency failures are not merge regressions. Check timing flakes
   with bounded isolated retries; do not convert them to xfail.
6. For host-delta-only failures, compare the test and source against both exact
   parents. Repair the active upstream seam or an obsolete fixture, preserving
   runtime dispatch, cancellation, delivery identities, and persistence behavior.
7. Save each completed file's real argv, environment, exit, summary, and raw-log
   path before continuing. Read receipts back and aggregate with code. Never
   treat a scheduler's zero exit as proof that child tests passed.
8. Run the explicit affected/regression manifests, lint the changed files, review
   the diff, and commit only the requested source/test/evidence paths. Preserve
   generated test artifacts separately; do not commit mock databases or venvs.

`commands.json` and `classifications.json` are the audit index. The `*.jsonl`
receipts retain every completed per-file run. Raw logs stay at the recorded
`/tmp` paths. `run_triage.py` blocks the known unsafe update filenames and never
expands directories into a suite. The caller must still review any new manifest.

This procedure was retained in the worktree instead of the profile skill store
because this task expressly prohibits edits under `~/.hermes`.
