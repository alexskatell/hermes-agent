# Runtime cutover continuation

Starting candidate: 941f3213f81fbea4bbf70e9aacca5cc3c4c7517b.
Live source: /Users/oc/workspace/hermes-claude-subscription-0.1.0.
Candidate: /Users/oc/workspace/hermes-upstream-merge-20260908.

Francis is the only candidate writer. Three read-only children inspect commentary/progress,
SDK compatibility, and rollback coverage (deleg_55c7d4c1).

1. Preserve the newer live commentary and iteration tests; run them against the
   unchanged candidate to establish the missing behavior. No production tests/services.
2. Port the minimum live gateway delta, retain upstream replay/delivery semantics,
   reconcile the installed SDK plugin, keep the required 14400-second timeout.
3. Run explicit affected and prior regression files, lint, and record exact outputs.
4. Complete the rollback manifest for every affected non-plist field and link.
   Restrict the lifecycle set to eight gateways, dashboard, and Desktop runtime selection.
   Preserve all independent services and headless profile restrictions.
5. Verify readiness before a serialized cutover. Default gateway is last, after
   child work is finished and a durable handoff exists. Confirm new process source,
   route, plugin, and connection evidence; rollback changed targets on failure.

## Controller boundary

The Kanban CLI denied creation of the controller card with `delegate_task child
contexts cannot mutate Kanban tasks via the CLI`. Do not bypass the guard.
Finish local parity and rollback preparation, then hand production transition to
the parent/orchestrator with board-write rights. No services may be restarted from
this context.

Do not use the existing broad rollback script as-is: non-plist coverage and
restart scope are under review. Do not copy the live plugin wholesale: its timeout
has drifted back to 600 seconds. Never run full-suite or launchd/update tests here.
