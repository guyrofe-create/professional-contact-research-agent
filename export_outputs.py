from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
import agent

ALGO_VERSION = agent.ALGO_VERSION
OUT = Path('output')
FINAL = Path('final')


def xml_safe(value):
    if not isinstance(value, str):
        return value
    # Keep XML 1.0 legal characters only. This explicitly removes NUL and
    # other control characters regardless of pandas string/object dtype.
    return ''.join(
        ch for ch in value
        if ch in ('\t', '\n', '\r')
        or 0x20 <= ord(ch) <= 0xD7FF
        or 0xE000 <= ord(ch) <= 0xFFFD
        or 0x10000 <= ord(ch) <= 0x10FFFF
    )


def sanitize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    safe = frame.copy()
    for col in safe.columns:
        safe[col] = safe[col].map(xml_safe)
    return safe


def read_checkpoint() -> pd.DataFrame:
    cp = OUT / 'checkpoint.jsonl'
    if not cp.exists():
        raise SystemExit('Missing output/checkpoint.jsonl')
    done = {}
    for line in cp.read_text(encoding='utf-8', errors='ignore').splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        if row.get('algo_version') == ALGO_VERSION:
            done[(row.get('name', ''), row.get('category', ''))] = row
    if not done:
        raise SystemExit(f'No version-{ALGO_VERSION} checkpoint rows found')
    return pd.DataFrame(list(done.values()))


def validate_xlsx(path: Path, expected_min_rows: int = 0):
    if not path.exists() or path.stat().st_size == 0:
        raise SystemExit(f'Missing/empty workbook: {path}')
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = max(0, ws.max_row - 1)
    wb.close()
    if rows < expected_min_rows:
        raise SystemExit(f'Workbook row regression: {path} has {rows}, expected at least {expected_min_rows}')
    print(f'VALIDATED {path} rows={rows} bytes={path.stat().st_size}')


def main():
    OUT.mkdir(exist_ok=True)
    FINAL.mkdir(exist_ok=True)

    frame = read_checkpoint()
    frame = frame.sort_values(['priority', 'status', 'confidence'], ascending=[True, True, False])
    frame = frame.drop_duplicates(subset=['name', 'category'], keep='first')

    expanded = agent.expand_verified_contacts(frame)
    repeated = set()
    if not expanded.empty:
        person = expanded[expanded.target_kind == 'person']
        repeated = {email for email, count in Counter(person.email).items() if count > 2}
    if repeated:
        mask = (frame.target_kind == 'person') & frame.email.isin(repeated)
        frame.loc[mask, 'status'] = 'REVIEW_SHARED_EMAIL'
        frame.loc[mask, 'confidence'] = 0

    safe_frame = sanitize_frame(frame)
    safe_frame.to_csv(OUT / 'audit.csv', index=False, encoding='utf-8-sig')
    safe_frame.to_excel(OUT / 'audit.xlsx', index=False)

    found = expanded[~expanded.email.isin(repeated)].copy() if not expanded.empty else pd.DataFrame(columns=list(frame.columns) + ['candidate_rank'])
    found = found.sort_values(['priority', 'confidence'], ascending=[True, False]).drop_duplicates(subset=['email'], keep='first')
    safe_found = sanitize_frame(found)
    safe_found.to_csv(OUT / 'contacts.csv', index=False, encoding='utf-8-sig')
    safe_found.to_excel(OUT / 'contacts.xlsx', index=False)

    review = sanitize_frame(frame[frame.status.str.startswith('REVIEW')].copy())
    review.to_excel(OUT / 'review.xlsx', index=False)

    summary = {
        'algo_version': ALGO_VERSION,
        'total_targets': int(len(frame)),
        'verified': int((frame.status == 'VERIFIED').sum()),
        'not_verified': int((frame.status == 'NO_VERIFIED_PUBLIC_EMAIL').sum()),
        'review': int(frame.status.str.startswith('REVIEW').sum()),
        'unique_emails': int(found.email.nunique()),
        'by_category': frame.groupby('category').status.value_counts().unstack(fill_value=0).to_dict('index'),
    }
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

    # Validate the generated workbooks before promoting them to FINAL.
    validate_xlsx(OUT / 'audit.xlsx', expected_min_rows=len(frame))
    validate_xlsx(OUT / 'contacts.xlsx', expected_min_rows=len(found))
    validate_xlsx(OUT / 'review.xlsx', expected_min_rows=len(review))

    shutil.copy2(OUT / 'contacts.xlsx', FINAL / 'contacts_FINAL.xlsx')
    shutil.copy2(OUT / 'audit.xlsx', FINAL / 'audit_FINAL.xlsx')
    shutil.copy2(OUT / 'review.xlsx', FINAL / 'review_FINAL.xlsx')
    shutil.copy2(OUT / 'summary.json', FINAL / 'summary_FINAL.json')
    if (OUT / 'COMPLETE.txt').exists():
        shutil.copy2(OUT / 'COMPLETE.txt', FINAL / 'COMPLETE.txt')
    if Path('seed_summary.json').exists():
        shutil.copy2('seed_summary.json', FINAL / 'seed_summary_FINAL.json')

    validate_xlsx(FINAL / 'contacts_FINAL.xlsx', expected_min_rows=len(found))
    validate_xlsx(FINAL / 'audit_FINAL.xlsx', expected_min_rows=len(frame))
    validate_xlsx(FINAL / 'review_FINAL.xlsx', expected_min_rows=len(review))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
