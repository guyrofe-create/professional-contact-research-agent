from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=False, text=True, capture_output=True)


def main() -> int:
    Path("output/last_heartbeat.txt").write_text(
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n",
        encoding="utf-8",
    )
    finalized = run("python", "finalize_state.py")
    if finalized.returncode:
        print(finalized.stderr[-500:])
        return finalized.returncode
    run(
        "git", "add", "--", "output/checkpoint.jsonl", "output/last_heartbeat.txt",
        "output/progress.txt", "output/COMPLETE.txt", "output/summary.json",
        "targets.csv", "seed_summary.json",
    )
    changed = run("git", "diff", "--cached", "--quiet")
    if changed.returncode == 0:
        return 0
    run("git", "config", "user.name", "contact-research-bot")
    run("git", "config", "user.email", "actions@users.noreply.github.com")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    committed = run("git", "commit", "-m", f"Research live checkpoint {stamp}")
    if committed.returncode:
        print(committed.stderr[-500:])
        return committed.returncode
    pushed = run("git", "push", "origin", "HEAD:main")
    if pushed.returncode:
        print(pushed.stderr[-500:])
    return pushed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
