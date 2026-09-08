# Hermes candidate activation handoff

The isolated candidate is fixed and offline-verified. Live activation has not occurred.
The source baseline for this continuation is `941f3213f81fbea4bbf70e9aacca5cc3c4c7517b`.
Use the commit containing this file as the qualified candidate, not that baseline.

## Verified candidate

- The final explicit manifest covers 23 files: 653 passed, zero failed, one known
  strict expected failure. `final-verification.json` reconciles the complete receipt.
- Nonstreaming commentary now survives tool boundaries, repeated commentary cannot
  contaminate a later distinct segment, and final messages remain separate.
- The installed SDK preserves the required 14400-second timeout, enables partial
  messages, requires iteration progress, excludes synthetic/error frames, and
  returns consistent terminal counts. The tracked wheel patch reproduces all 16
  plugin source files exactly; see `sdk-reproduction.json`.
- The reviewer-approved upstream approval/egress safeguards and persisted display
  metadata were retained. No fallback/route or live-profile settings were changed.
- Fresh candidate tests are not proof of a currently running gateway's code or auth.

## Unresolved behavior

The bridge-first SDK commentary ordering race remains a known live defect. Its
strict expected-failure test was preserved, not hidden or counted as a pass.

A newer live zero-usage suppression change was excluded. It changes accounting and
fallback behavior independently and still needs its own regression evidence before
claiming complete live parity. The current candidate must not be activated under an
unqualified claim that every later live change is present.

Native child progress is also distinct from these commentary fixes. The gateway
drops ordinary child progress events, and parent cleanup ends its progress sender.
Use brief parent milestones, grouped native completion events, and `/agents` for
live activity; no cron watcher or promised periodic idle posts were added.

## Activation boundary

The Kanban CLI refused controller creation with:
`delegate_task child contexts cannot mutate Kanban tasks via the CLI`.
No card was created. Do not clear child markers or use another store to evade it.
The permitted parent/operator must own the controller and eventual activation.
This gateway-descended context must not restart the process tree that owns it.

The exact transaction scope is nine plists, four non-plist paths, and two GUI
values. Preserve all remaining fields, credentials, profile confinement, and routes:

- Eight gateway plists: default, CFO, CTO, customer success, legal, marketing,
  outbound, and sales. Change only the two interpreter arguments and the selected
  HERMES_BIN, VIRTUAL_ENV, and first PATH entry.
- Dashboard plist: its working directory and the same three environment fields.
- Dashboard launcher symlink, the qualified Desktop runtime script, the default
  `.env` HERMES_BIN/VIRTUAL_ENV values, and the CLI wrapper's two runtime operands.
- GUI `HERMES_DESKTOP_HERMES_ROOT` and `HERMES_DESKTOP_PYTHON` values.

No Chrome CDP, Telnyx, local-signing, or Codex Sky timer changes/reloads are needed.
Do not start technical_reviewer, cringey, or claude_subscription_test gateways.
Do not edit Cringey's pre-existing child-concurrency mismatch as part of cutover.

## Rollback and ownership prerequisites

`rollback-preservation.json` points to the private bundle. The earlier 32-file
snapshot was moved there byte-for-byte, outside Git. Its 22 manifest entries and
pinned checksum were independently verified. The supplement preserves both wrapper
before-images, symlink metadata, only the two nonsecret `.env` values and hashes,
and both GUI values. The `.env` inverse was checked in memory; its full contents
were never saved. The 13 persistent targets still matched the review before-images
at parent verification.

**Do not execute the old revert script.** It restores/reloads too broad a set and
omits non-plist/GUI restoration, ownership, quiescence, and partial-failure handling.
The supplement is before-image evidence, not a tested live recovery procedure.

The permitted parent/operator must finish these steps before activation:

1. Re-pin the committed candidate and qualify the excluded accounting delta.
2. Refresh before-images and process state; the old snapshot PIDs are stale.
3. Establish an independently owned execution context outside all affected process
   trees. Finish existing work and verify quiescence, including Desktop's separate
   serve process. Detachment alone does not prove ownership independence.
4. Validate a scoped inverse for only the changed targets. Use the existing drain
   contract only within approved scope; preserve and later release only owned
   temporary markers. Never force-kill active sessions.
5. Activate sequentially: seven sibling gateways, dashboard, the same Desktop app
   after its work finishes, and default last. Adopt changed loaded plist arguments,
   then verify source/interpreter, new supervisor/child ownership, and connections.
6. On any failed step, stop advancing and reverse only completed changes. Restore
   GUI selection before an old-runtime Desktop relaunch. Verify old-root health.

Detailed read-only transaction evidence remains at
`/tmp/hermes-cutover-audit-458_krh0/transaction-plan.md` and the private supplement.
Refresh host-specific evidence before use. No live rollback, gateway restart,
credentialed inference, or production transition was exercised by this continuation.
