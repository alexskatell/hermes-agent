"""Explicit-file differential tests; never discovers a suite or runs services.

All commands and outcomes are appended to a JSONL receipt. Tests use the
merge's Python 3.12 environment, fresh HOME/HERMES_HOME, and fresh processes.
No live profile, credential environment, service command, or network fetch.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv-safe/bin/python"
BASE = Path("/tmp/hermes-triage-base-63ec22e797")
BLOCKED = {
    "tests/hermes_cli/test_update_head_moved_gate.py",
    "tests/hermes_cli/test_update_autostash.py",  # until the restart seam is audited
}


def run_file(tree, filename, label):
    assert filename.startswith("tests/") and filename.endswith(".py"), filename
    assert filename not in BLOCKED and "test_update_launchd_" not in filename, filename
    command = [str(PYTHON), "-m", "pytest", "-q", "-p", "no:cacheprovider", filename]
    record = {"label": label, "tree": str(tree), "file": filename, "command": command}
    if not (tree / filename).is_file():
        return {**record, "absent": True}
    home = Path(tempfile.mkdtemp(prefix="hermes-triage-home-", dir="/private/tmp"))
    env = {
        "PATH": f"{PYTHON.parent}:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(home), "HERMES_HOME": str(home / ".hermes"),
        "TMPDIR": "/private/tmp", "TZ": "UTC", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "PYTHONHASHSEED": "0", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
    }
    record["environment"] = env
    log = Path("/tmp") / ("hermes-triage-" + label + "-" + filename.replace("/", "__") + ".log")
    started = time.monotonic()
    with log.open("w") as out:
        proc = subprocess.Popen(command, cwd=tree, env=env, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            rc = proc.wait(timeout=240)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            rc = 124
    text = log.read_text(errors="replace")
    summaries = [s.strip() for s in text.splitlines() if re.search(r"\b\d+ (?:failed|passed|skipped|error|deselected)", s) and " in " in s]
    summary = summaries[-1] if summaries else "no summary"
    counts = {key: int(n) for n, key in re.findall(r"(\d+) (failed|passed|skipped|errors?|deselected|xfailed|xpassed)", summary)}
    return {**record, "exit": rc, "seconds": round(time.monotonic() - started, 2), "log": str(log),
            "summary": summary, "counts": counts,
            "failures": re.findall(r"^(?:FAILED|ERROR) (tests/[^\n]+)", text, re.M)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--trees", choices=["both", "merged", "base"], default="both")
    p.add_argument("--jobs", type=int, default=4)
    args = p.parse_args()
    files = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    assert files and len(files) == len(set(files))
    trees = {"base": BASE, "merged": ROOT}
    receipt = ROOT / "merge-evidence" / (args.label + ".jsonl")
    jobs = [(tree, f, args.label + "-" + kind) for kind, tree in trees.items()
            if args.trees in ("both", kind) for f in files]
    any_failed = False
    with receipt.open("a") as out, ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for fut in as_completed([pool.submit(run_file, *job) for job in jobs]):
            row = fut.result()
            any_failed = any_failed or bool(row.get("exit", 0))
            out.write(json.dumps(row, sort_keys=True) + "\n")
            out.flush()
            print(row["label"], row["file"], row.get("exit", "absent"), row.get("summary", ""), flush=True)
    code = 1 if any_failed else 0
    print(f"EXIT={code}", flush=True)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
