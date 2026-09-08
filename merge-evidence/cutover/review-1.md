**Recommend the four-file scratch delta, not a wholesale live copy.** Candidate passed **71/71 offline checks**; merged passed 40/71 and live 62/71.

- **Configuration:** retain `14400.0`; add `include_partial_messages=True`. Reject live’s `600.0` timeout regression.
- **Compatibility:** require `iteration_progress_v1`; verified that removing it from the host manifest makes compatibility fail.
- **Projector:** preserve merged root-response-ID deduplication and safe stream parsing. Add/reset `api_call_count`; exclude synthetic/error assistant messages **and streamed starts**. Use positive integer `num_turns` only for successful ID-less results, without inventing live progress. Observed IDs always take precedence.
- **Runtime:** replace final `api_calls=1` with `projector.api_call_count`. No host source change needed; verified existing finalization preserves the maximum observed/terminal count, including failure and cancellation.

**Live behavior not to copy unchanged**
- Stream counting bypasses its assistant-only synthetic/error guards.
- Failed ID-less `num_turns=9` currently sets internal count to nine.
- A newer zero-usage suppression block changes accounting/fallback behavior independently. Excluded from this delta; not established as either a regression or a validated fix.

**Artifacts:** `/tmp/claude-sdk-reconcile.epwVbipH/`
- `merged-to-candidate.patch` — incremental recommendation.
- `original-to-candidate.patch` — proposed replacement tracked wheel patch.
- `RECOMMENDATION.md` — exact rationale, commands, required test updates.
- `probe.py`, `launch.py`, result JSON/logs, and `reproduction.json`.

Both patch replays matched all 16 expected plugin files byte-for-byte. Original wheel SHA matched `f481b2ae859338d4d9dc6ae05bece9c10a97532474337f949a1db353313d3d9b`.

Reproduce green:
```sh
/Users/oc/workspace/hermes-upstream-merge-20260908/.venv-safe/bin/python -I -B -S /tmp/claude-sdk-reconcile.epwVbipH/launch.py candidate
```
Use `merged` or `live` for red.

**Required maintained updates:** extend SDK tests with negative message shapes, actual runtime final counts, options and manifest checks; extend host finalizer tests with lower/higher terminal counts; update tracked patch and README together.

Only scratch files changed. Installed plugins remained unchanged; merged HEAD and tracked status remained unchanged. No credentials, network, services, installs, or suite/update tests used. Partial messages do **not** resolve the existing gateway `bridge-first` commentary-ordering xfail.