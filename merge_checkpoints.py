from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import agent


def key(row):
    return str(row.get("name", "")).strip(), str(row.get("category", "")).strip()


def timestamp(row):
    value = str(row.get("last_attempt_at", ""))
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


def quality(row):
    status = str(row.get("status", ""))
    status_rank = 4 if status == "VERIFIED" else 3 if status == "NO_VERIFIED_PUBLIC_EMAIL" else 2 if status.startswith("REVIEW") else 1
    return status_rank, int(row.get("confidence", 0) or 0), timestamp(row)


def json_list(value):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def combine(left, right):
    winner, other = (left, right) if quality(left) >= quality(right) else (right, left)
    result = dict(winner)
    for field in ("attempted_urls", "alternate_emails"):
        combined = []
        seen = set()
        for item in json_list(winner.get(field, "[]")) + json_list(other.get(field, "[]")):
            marker = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, dict) else str(item)
            if marker not in seen:
                seen.add(marker)
                combined.append(item)
        result[field] = json.dumps(combined, ensure_ascii=False)
    for field in ("search_queries", "search_errors", "search_results", "pages_fetched", "fetch_failures", "retry_count"):
        result[field] = max(int(left.get(field, 0) or 0), int(right.get(field, 0) or 0))
    result["merged_checkpoint_rows"] = int(left.get("merged_checkpoint_rows", 1) or 1) + int(right.get("merged_checkpoint_rows", 1) or 1)
    return result


def read_rows(path):
    rows = []
    source = Path(path)
    if not source.exists():
        return rows
    for line in source.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            migrated = agent.migrate_checkpoint_row(json.loads(line))
        except Exception:
            continue
        if migrated and migrated.get("algo_version") == agent.ALGO_VERSION and all(key(migrated)):
            rows.append(migrated)
    return rows


def merge(paths):
    merged = {}
    for path in paths:
        for row in read_rows(path):
            row_key = key(row)
            merged[row_key] = combine(merged[row_key], row) if row_key in merged else row
    return merged


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    merged = merge(args.inputs)
    Path(args.output).write_text(
        "".join(json.dumps(merged[row_key], ensure_ascii=False) + "\n" for row_key in sorted(merged)),
        encoding="utf-8",
    )
    print(f"Merged checkpoint targets={len(merged)} version={agent.ALGO_VERSION}")


if __name__ == "__main__":
    main()
