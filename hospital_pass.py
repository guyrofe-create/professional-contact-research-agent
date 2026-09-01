from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
from ddgs import DDGS

import agent

# Official Israeli hospital, health-fund and medical-center domains. Provider pages
# are treated as first-party institutional sources, not general web directories.
HOSPITAL_DOMAINS = (
    "sheba.co.il", "tasmc.org.il", "hadassah.org.il", "rambam.org.il",
    "assuta.co.il", "hospitals.clalit.co.il", "shamir.org", "szmc.org.il",
    "laniado.org.il", "mayanei-hayeshua.co.il", "poria.health.gov.il",
    "ziv.health.gov.il", "wolfson.org.il", "bmc.gov.il", "gov.il",
    "clalit.co.il", "hospitals.clalit.co.il", "maccabi4u.co.il", "mac.org.il",
    "meuhedet.co.il", "leumit.co.il",
)
ELIGIBLE = {
    "gynecologist", "fertility_doctor", "fertility_nurse", "midwife", "embryologist",
    "family_doctor", "clinic_manager", "womens_health_center", "community_clinic",
}


def queries(name: str, category: str):
    terms = agent.CATEGORY_CONFIG.get(category, {}).get("terms", [category])
    profession = " ".join(terms[:2])
    for domain in HOSPITAL_DOMAINS:
        yield f'"{name}" {profession} site:{domain}'


def hospital_research(row: dict):
    name = str(row.get("name", "")).strip()
    category = str(row.get("category", "")).strip()
    if category not in ELIGIBLE:
        return None
    engine = DDGS()
    candidates = []
    attempted = []
    for query in queries(name, category):
        try:
            results = engine.text(query, region="il-he", safesearch="moderate", max_results=5, backend="brave,duckduckgo,mojeek") or []
        except Exception as exc:
            print("HOSPITAL_SEARCH_WARNING", type(exc).__name__, str(exc)[:120], flush=True)
            time.sleep(.2)
            continue
        for hit in results:
            url = hit.get("href") or hit.get("url") or ""
            if not url or agent.blocked_url(url):
                continue
            if not any(agent.host(url) == d or agent.host(url).endswith("." + d) for d in HOSPITAL_DOMAINS):
                continue
            evidence = (hit.get("title", "") + " " + hit.get("body", ""))
            if not agent.name_match(name, evidence):
                continue
            url, html = agent.fetch(url)
            attempted.append(url)
            if not html:
                continue
            items, links, text, title, _ = agent.extract(url, html)
            if not agent.name_match(name, title + " " + text[:20000]) or not agent.category_match(category, title + " " + text[:20000]):
                continue
            for email, context, method in items:
                score = agent.candidate_score(email, url, text, title, context, name, category, True, text, url)
                if score is not None:
                    candidates.append((score, email, url, context[:500], query, method))
            for link in links:
                u2, h2 = agent.fetch(link)
                attempted.append(u2)
                if not h2:
                    continue
                items2, _, text2, title2, _ = agent.extract(u2, h2)
                for email, context, method in items2:
                    score = agent.candidate_score(email, u2, text2, title2, context, name, category, True, text, url)
                    if score is not None:
                        candidates.append((score, email, u2, context[:500], query, method))
            if candidates:
                break
        if candidates:
            break
        time.sleep(.1)
    if not candidates:
        return None
    score, email, source, evidence, query, method = sorted(set(candidates), reverse=True)[0]
    return dict(row) | {
        "email": email, "email_type": agent.classify(email, category), "confidence": score,
        "source_url": source, "status": "VERIFIED", "evidence": evidence,
        "matched_query": query, "extraction_method": "hospital_" + method,
        "attempted_urls": json.dumps(list(dict.fromkeys(attempted)), ensure_ascii=False),
        "hospital_pass": 1,
    }


def main():
    cp = Path("output/checkpoint.jsonl")
    if not cp.exists():
        return
    rows = []
    for line in cp.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
            if row.get("algo_version") == agent.ALGO_VERSION:
                rows.append(row)
        except Exception:
            pass
    changed = 0
    for i, row in enumerate(rows):
        if row.get("category") not in ELIGIBLE or row.get("status") not in {"NO_VERIFIED_PUBLIC_EMAIL", "RETRY_SEARCH_UNAVAILABLE"} or row.get("hospital_pass"):
            continue
        print(f'HOSPITAL_PASS {row.get("name")} | {row.get("category")}', flush=True)
        result = hospital_research(row)
        rows[i] = result if result else (dict(row) | {"hospital_pass": 1})
        if result:
            changed += 1
        cp.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
    print(f"Hospital pass complete; newly verified={changed}", flush=True)


if __name__ == "__main__":
    main()
