from pathlib import Path
import csv
import json

import agent
import export_outputs


def main():
    with open("targets.csv", encoding="utf-8-sig") as source:
        targets = sum(1 for _ in csv.DictReader(source))
    latest = {}
    checkpoint = Path("output/checkpoint.jsonl")
    for line in checkpoint.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        if row.get("algo_version") == agent.ALGO_VERSION:
            latest[(row.get("name", ""), row.get("category", ""))] = row
    pending = {row_key for row_key, row in latest.items() if str(row.get("status", "")).startswith("PENDING")}
    completed = len(latest) - len(pending)
    state = f"completed={completed}\ntouched={len(latest)}\npending={len(pending)}\ntargets={targets}\nalgo_version={agent.ALGO_VERSION}\n"
    Path("output/progress.txt").write_text(state, encoding="utf-8")
    Path("output/COMPLETE.txt").write_text(("COMPLETE" if targets and completed >= targets else "IN_PROGRESS") + "\n" + state, encoding="utf-8")
    export_outputs.main()


if __name__ == "__main__":
    main()
