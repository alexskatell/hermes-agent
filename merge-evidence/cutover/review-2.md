**Rollback is incomplete. Do not run the existing `revert.sh` as-is.**

- **Verified:** all 22 manifest entries and the pinned manifest checksum; all 15 live plist snapshots; all 11 current config hashes. Nine proposed plists pass lint and inverse checks. Both wrapper edits and the two-key `.env` edit reverse byte-for-byte in memory.
- **Minimal persistent delta:** nine plists, four non-plist paths, and two GUI environment values. Gateways change only `ProgramArguments[0],[6]`, `HERMES_BIN`, `VIRTUAL_ENV`, and PATH’s first entry. Dashboard changes its three runtime environment fields and cwd. Non-plist targets are the dashboard symlink, qualified-runtime script, default `.env` runtime values, and CLI wrapper.
- **Rollback gaps:** missing restoration for all four non-plist surfaces and both GUI values; overbroad restoration of 15 plists and reload of 11 jobs; no drain/ownership checks, confirmed old-child exit, loaded-runtime verification, or stop-and-reverse handling of partial failures. Restore only changed targets. Neither the Codex Sky timer nor qualified-runtime plist needs reloading.
- **Safe activation order:** finish active work, establish independently owned parent execution, drain using the existing contract if approved, validate replacements, then sequentially reload the seven siblings, dashboard, separately relaunch Desktop after its sessions finish, and reload **default last**. On failure, halt advancement, reverse committed file/link/env changes, and recover only affected processes. Never force-kill active sessions.
- **Current boundaries:** default reported two active agents; this audit descends from its gateway process. Desktop app `25840` owns separate `serve` PID `25856`; dashboard `56601` is another process. Their quiescence is not established. All gateway PIDs differ from the snapshot. Candidate contents changed during review, so final source qualification belongs to the parent.
- **Exclusions:** no Chrome CDP, Telnyx, local-signing, or Codex Sky restart; no headless gateways; no route/channel changes. No Kanban guard bypass or controller machinery.

**Handoff files**
- `/tmp/hermes-cutover-audit-458_krh0/transaction-plan.md`
- `/tmp/hermes-cutover-audit-458_krh0/rollback-metadata.json`
- Supporting checks: `evidence.json`, `surface-verification.json`, and `proposed-plists/` in that directory.

No production, worktree, profile, skill, or board edits were made by this reviewer. A fresh dry-run invocation was approval-blocked and not retried. Intentional artifacts stayed in the unique scratch directory; the documentation tool additionally created its normal web cache, disclosed in the plan.