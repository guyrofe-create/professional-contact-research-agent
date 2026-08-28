from __future__ import annotations

import base64
import csv
import json
import os
import sys
import threading
import time
from pathlib import Path

import requests

ALGO_VERSION = 3
INTERVAL_SECONDS = 120


def _is_agent_run() -> bool:
    return Path(sys.argv[0]).name == "agent.py" and os.getenv("GITHUB_ACTIONS") == "true"


def _count_targets() -> int:
    path = Path("targets.csv")
    if not path.exists():
        return 0
    try:
        with path.open(encoding="utf-8-sig") as f:
            return sum(1 for _ in csv.DictReader(f))
    except Exception:
        return 0


def _count_completed() -> int:
    cp = Path("output/checkpoint.jsonl")
    if not cp.exists():
        return 0
    keys = set()
    try:
        for line in cp.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("algo_version") == ALGO_VERSION:
                keys.add((row.get("name", ""), row.get("category", "")))
    except Exception:
        return 0
    return len(keys)


def _github_put(path: str, text: str, message: str) -> None:
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    if not token or not repo:
        return
    api = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        current = requests.get(api, headers=headers, timeout=15)
        sha = current.json().get("sha") if current.status_code == 200 else None
        payload = {
            "message": message,
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
            "branch": "main",
        }
        if sha:
            payload["sha"] = sha
        response = requests.put(api, headers=headers, json=payload, timeout=20)
        if response.status_code not in (200, 201):
            print("LIVE_PROGRESS_WARNING", response.status_code, response.text[:160], flush=True)
    except Exception as exc:
        print("LIVE_PROGRESS_WARNING", type(exc).__name__, str(exc)[:160], flush=True)


def _publish_loop() -> None:
    last_progress = None
    while True:
        time.sleep(INTERVAL_SECONDS)
        completed = _count_completed()
        targets = _count_targets()
        state = (completed, targets)
        heartbeat = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\n"
        progress = f"completed={completed}\ntargets={targets}\nalgo_version={ALGO_VERSION}\n"
        try:
            Path("output").mkdir(exist_ok=True)
            Path("output/progress.txt").write_text(progress, encoding="utf-8")
            Path("output/last_heartbeat.txt").write_text(heartbeat, encoding="utf-8")
        except Exception:
            pass
        _github_put("output/last_heartbeat.txt", heartbeat, "Live research heartbeat")
        if state != last_progress:
            _github_put("output/progress.txt", progress, f"Live research progress {completed}/{targets}")
            last_progress = state


if _is_agent_run():
    threading.Thread(target=_publish_loop, name="live-progress", daemon=True).start()
