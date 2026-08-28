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

ALGO_VERSION = 4
INTERVAL_SECONDS = 300


def _is_agent_run():
    return Path(sys.argv[0]).name == "agent.py" and os.getenv("GITHUB_ACTIONS") == "true"


def _count(path, version=False):
    if not path.exists():
        return 0
    if path.suffix == ".csv":
        try:
            with path.open(encoding="utf-8-sig") as stream:
                return sum(1 for _ in csv.DictReader(stream))
        except Exception:
            return 0
    keys = set()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
            if not version or row.get("algo_version") == ALGO_VERSION:
                keys.add((row.get("name", ""), row.get("category", "")))
        except Exception:
            pass
    return len(keys)


def _publish(text):
    token, repo = os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPOSITORY")
    if not token or not repo:
        return
    api = f"https://api.github.com/repos/{repo}/contents/live/status.json"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    try:
        current = requests.get(api, headers=headers, timeout=15)
        payload = {"message": "Update live research status", "content": base64.b64encode(text.encode()).decode(), "branch": "main"}
        if current.status_code == 200:
            payload["sha"] = current.json()["sha"]
        response = requests.put(api, headers=headers, json=payload, timeout=20)
        if response.status_code not in (200, 201):
            print("LIVE_PROGRESS_WARNING", response.status_code, response.text[:160], flush=True)
    except Exception as exc:
        print("LIVE_PROGRESS_WARNING", type(exc).__name__, str(exc)[:160], flush=True)


def _loop():
    while True:
        time.sleep(INTERVAL_SECONDS)
        payload = {
            "algo_version": ALGO_VERSION,
            "completed": _count(Path("output/checkpoint.jsonl"), True),
            "targets": _count(Path("targets.csv")),
            "heartbeat_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _publish(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


if _is_agent_run():
    threading.Thread(target=_loop, name="live-progress", daemon=True).start()
