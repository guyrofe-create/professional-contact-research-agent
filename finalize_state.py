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
    verified = sum(str(row.get("status", "")) == "VERIFIED" for row in latest.values())
    retired_verified = 0
    retired = Path("output/retired_targets.jsonl")
    if retired.exists():
        for line in retired.read_text(encoding="utf-8", errors="ignore").splitlines():
            try: retired_verified += json.loads(line).get("status") == "VERIFIED"
            except Exception: pass
    state = f"completed={completed}\nverified={verified}\nretired_verified_preserved={retired_verified}\npreserved_verified_total={verified+retired_verified}\ntouched={len(latest)}\npending={len(pending)}\ntargets={targets}\nalgo_version={agent.ALGO_VERSION}\n"
    Path("output/progress.txt").write_text(state, encoding="utf-8")
    Path("output/COMPLETE.txt").write_text(("COMPLETE" if targets and completed >= targets else "IN_PROGRESS") + "\n" + state, encoding="utf-8")
    export_outputs.main()


if __name__ == "__main__":
    main()
