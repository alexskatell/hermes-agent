#!/usr/bin/env python3
"""Replay the pinned Claude SDK wheel patch without importing either runtime."""

import argparse
import hashlib
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "scripts/runtime-plugin-patches/claude-sdk-0.1.0-host-delta.patch"
RECEIPT = ROOT / "merge-evidence/cutover/sdk-reproduction.json"
SITE_PACKAGES = Path(".venv-safe/lib/python3.12/site-packages")
PACKAGE = "hermes_claude_agent_sdk"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def verify(wheel, *, record=False, backup=None):
    previous = json.loads(RECEIPT.read_text(encoding="utf-8"))
    wheel_bytes = wheel.read_bytes()
    assert sha256(wheel_bytes) == previous["wheel_sha256"], "original wheel hash mismatch"
    replay = Path(tempfile.mkdtemp(prefix="hermes-port-sdk-replay-", dir="/private/tmp"))
    original = {}
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.startswith(f"{PACKAGE}/") and name.endswith(".py"):
                relative = Path(name).relative_to(PACKAGE)
                assert ".." not in relative.parts
                original[str(relative)] = archive.read(name)
                target = replay / PACKAGE / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(original[str(relative)])
    assert original, "wheel contains no plugin sources"
    for args in (["git", "apply", "--check", str(PATCH)], ["git", "apply", str(PATCH)]):
        subprocess.run(args, cwd=replay, check=True)
    installed = ROOT / SITE_PACKAGES / PACKAGE
    paths = {str(path.relative_to(installed)): path for path in installed.rglob("*.py")}
    assert paths.keys() == original.keys(), "installed and wheel source sets differ"
    hashes = {name: sha256(path.read_bytes()) for name, path in sorted(paths.items())}
    replay_hashes = {name: sha256((replay / PACKAGE / name).read_bytes()) for name in paths}
    assert hashes == replay_hashes, "patched-wheel and installed source hashes differ"
    subprocess.run([
        "git", "apply", "--reverse", "--check", f"--directory={SITE_PACKAGES}", str(PATCH),
    ], cwd=ROOT, check=True)
    patch_hash = sha256(PATCH.read_bytes())
    if record:
        previous.update(
            changed_files=sorted(name for name in original if sha256(original[name]) != hashes[name]),
            tracked_patch_sha256=patch_hash, replay=str(replay),
            verified_file_count=len(hashes), plugin_source_sha256=hashes,
            live_environment_written=False, fresh_original_wheel_replay_exit=0,
            installed_reverse_check_exit=0,
            verification_command=(
                ".venv-safe/bin/python scripts/runtime-plugin-patches/verify_claude_sdk_reproduction.py "
                f"--wheel {wheel}"
            ),
            format_note="Blank context lines are unprefixed; forward replay verifies exact source bytes.",
        )
        if backup:
            previous["backup"] = str(backup)
        RECEIPT.write_text(json.dumps(previous, indent=2) + "\n", encoding="utf-8")
    else:
        assert hashes == previous["plugin_source_sha256"], "receipt source hash mismatch"
        assert len(hashes) == previous["verified_file_count"], "receipt count mismatch"
        assert patch_hash == previous["tracked_patch_sha256"], "receipt patch hash mismatch"
    return {
        "verified_file_count": len(hashes), "changed_files": previous["changed_files"],
        "tracked_patch_sha256": patch_hash, "content_events_sha256": hashes["content_events.py"],
        "forward_replay": "pass", "installed_reverse_check": "pass", "replay": str(replay),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--record", action="store_true", help="update the tracked receipt after exact replay")
    parser.add_argument("--backup", type=Path, help="candidate-only before-image location for the receipt")
    args = parser.parse_args()
    print(json.dumps(verify(args.wheel, record=args.record, backup=args.backup), indent=2))
