from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from collections import Counter
from functools import lru_cache
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

ALGO_VERSION = 4
EMAIL_RE = re.compile(r"(?i)(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.-])")
BAD_LOCAL = {"example", "test", "noreply", "no-reply", "webmaster", "privacy", "abuse", "support"}
GENERIC_LOCAL = {"info", "office", "clinic", "contact", "mail", "reception", "admin", "secretary", "nashim", "service", "hello", "igudyhanaka", "customerservice", "visitors"}
FREE_MAIL = {"gmail.com", "walla.co.il", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "bezeqint.net", "012.net.il", "netvision.net.il"}
BLOCKED_DOMAINS = {
    "google.com", "youtube.com", "wikipedia.org", "wiktionary.org", "linkedin.com", "rocketreach.co",
    "zoominfo.com", "stockanalysis.com", "yahoo.com", "investing.com", "pinterest.com",
    "mako.co.il", "ynet.co.il", "maariv.co.il",
    "haaretz.co.il", "israelhayom.co.il", "ice.co.il", "globes.co.il", "themarker.com", "jusbrasil.com.br",
    "ubereats.com", "ilovepdf.com", "smallpdf.com", "drugs.com", "amazon.com", "reddit.com",
}
CONTACT_WORDS = ("contact", "about", "team", "staff", "doctor", "clinic", "profile", "צור-קשר", "צור קשר", "אודות", "צוות", "רופאים", "מרפאה")
CATEGORY_CONFIG = {
    "gynecologist": {"priority": "A", "terms": ["יילוד", "גינקולוג", "רופא נשים", "מיילדות", "obstetric", "gynecolog"], "kind": "person"},
    "fertility_doctor": {"priority": "A", "terms": ["פוריות", "פריון", "ivf", "שימור פוריות"], "kind": "person"},
    "ivf_unit": {"priority": "A", "terms": ["ivf", "הפריה חוץ גופית", "יחידת פוריות"], "kind": "org"},
    "fertility_center": {"priority": "A", "terms": ["מרכז פוריות", "מרפאת פוריות", "פריון"], "kind": "org"},
    "embryologist": {"priority": "A", "terms": ["אמבריולוג", "embryologist", "ivf"], "kind": "person"},
    "fertility_nurse": {"priority": "A", "terms": ["אחות פוריות", "אחות פריון", "ivf"], "kind": "person"},
    "fertility_consultant": {"priority": "A", "terms": ["יועצת פוריות", "יועץ פוריות", "פריון"], "kind": "person"},
    "sperm_bank": {"priority": "A", "terms": ["בנק זרע", "תרומת זרע"], "kind": "org"},
    "fertility_preservation": {"priority": "A", "terms": ["שימור פוריות"], "kind": "org"},
    "fertility_association": {"priority": "A", "terms": ["עמותת פוריות", "ארגון פוריות", "פריון"], "kind": "org"},
    "doula": {"priority": "A", "terms": ["דולה", "doula", "תומכת לידה"], "kind": "person"},
    "midwife": {"priority": "A", "terms": ["מיילדת", "midwife"], "kind": "person"},
    "childbirth_educator": {"priority": "A", "terms": ["הכנה ללידה", "מדריכת לידה"], "kind": "person"},
    "birth_center": {"priority": "A", "terms": ["מרכז לידה", "חדר לידה", "יולדות"], "kind": "org"},
    "lactation": {"priority": "B", "terms": ["יועצת הנקה", "ibclc", "הנקה"], "kind": "person"},
    "pelvic_floor": {"priority": "B", "terms": ["רצפת אגן", "פיזיותרפיה"], "kind": "person"},
    "sleep_consultant": {"priority": "B", "terms": ["יועצת שינה", "ייעוץ שינה"], "kind": "person"},
    "pregnancy_dietitian": {"priority": "B", "terms": ["דיאטנית", "תזונה", "הריון", "פוריות"], "kind": "person"},
    "parenting_center": {"priority": "B", "terms": ["מרכז הורות", "הורים ותינוקות"], "kind": "org"},
    "perinatal_mental_health": {"priority": "B", "terms": ["פסיכולוג", "טיפול רגשי", "הריון", "פוריות"], "kind": "person"},
    "facebook_group_admin": {"priority": "C", "terms": ["קבוצת פייסבוק", "הריון", "פוריות"], "kind": "community"},
    "community_manager": {"priority": "C", "terms": ["קהילה", "הריון", "פוריות"], "kind": "community"},
    "instagram_creator": {"priority": "C", "terms": ["אינסטגרם", "הריון", "פוריות"], "kind": "creator"},
    "parenting_site": {"priority": "C", "terms": ["הורות", "הריון", "לידה"], "kind": "org"},
    "pregnancy_podcast": {"priority": "C", "terms": ["פודקאסט", "הריון", "פוריות"], "kind": "creator"},
    "doula_school": {"priority": "C", "terms": ["בית ספר לדולות", "קורס דולות"], "kind": "org"},
    "childbirth_school": {"priority": "C", "terms": ["הכנה ללידה", "קורס מדריכות"], "kind": "org"},
    "women_health_creator": {"priority": "C", "terms": ["בריאות האישה", "הריון", "לידה"], "kind": "creator"},
}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ProfessionalContactResearch/4.0; public-contact-research)"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9\u0590-\u05ff]+", " ", unicodedata.normalize("NFKD", str(value or "")).lower()).strip()


def tokens(value: str) -> list[str]:
    return [x for x in norm(value).split() if len(x) >= 2 and x not in {"דר", "דוקטור", "פרופ", "פרופסור", "doctor", "prof"}]


def host(url: str) -> str:
    value = urlparse(url).netloc.lower().split(":")[0]
    return value[4:] if value.startswith("www.") else value


def registeredish(domain: str) -> str:
    parts = domain.lower().split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "org", "ac", "gov", "net", "com"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def blocked_url(url: str) -> bool:
    domain = host(url)
    return not domain or any(domain == bad or domain.endswith("." + bad) for bad in BLOCKED_DOMAINS)


def norm_email(email: str) -> str:
    return email.strip(" <>[](){}.,;:\"'").lower().replace("\u00a0", "")


def valid_email(email: str) -> bool:
    if "@" not in email:
        return False
    local, domain = email.rsplit("@", 1)
    return bool(local and domain and "." in domain and local not in BAD_LOCAL and not domain.endswith((".png", ".jpg", ".jpeg", ".webp")))


def name_match(name: str, text: str) -> bool:
    wanted = tokens(name)
    hay = set(tokens(text))
    if not wanted:
        return False
    needed = len(wanted) if len(wanted) <= 2 else len(wanted) - 1
    return sum(token in hay for token in wanted) >= needed


def category_match(category: str, text: str) -> bool:
    hay = norm(text)
    return any(norm(term) in hay for term in CATEGORY_CONFIG.get(category, {}).get("terms", []) if norm(term))


def local_name_match(email: str, name: str) -> bool:
    local = norm(email.split("@", 1)[0]).replace(" ", "")
    latin = [x for x in tokens(name) if re.search("[a-z]", x) and len(x) >= 3]
    return bool(latin) and any(x in local for x in latin)


def search_queries(name: str, category: str) -> list[str]:
    terms = CATEGORY_CONFIG.get(category, {}).get("terms", [category])
    profession = " ".join(terms[:2])
    return list(dict.fromkeys([
        f'"{name}" {profession}',
        f'"{name}" {profession} מייל',
        f'"{name}" {profession} צור קשר',
        f'"{name}" {profession} אתר רשמי',
        f'"{name}" email',
        f'"{name}" contact',
    ]))


def search_web(name: str, category: str, seed_source: str = "", max_results: int = 8):
    seen: set[str] = set()
    if seed_source.startswith("http") and not blocked_url(seed_source):
        seen.add(seed_source)
        yield {"url": seed_source, "title": name, "snippet": "", "query": "seed_source", "seed": True}
    engine = DDGS()
    for query in search_queries(name, category):
        try:
            results = engine.text(query, region="il-he", safesearch="moderate", max_results=max_results) or []
            for result in results:
                url = result.get("href") or result.get("url") or ""
                title = result.get("title", "")
                snippet = result.get("body", "")
                if url in seen or blocked_url(url):
                    continue
                evidence = title + " " + snippet
                if not name_match(name, evidence) or not category_match(category, evidence):
                    continue
                seen.add(url)
                yield {"url": url, "title": title, "snippet": snippet, "query": query, "seed": False}
        except Exception as exc:
            print("SEARCH_WARNING", type(exc).__name__, str(exc)[:160], flush=True)
        time.sleep(0.15)


@lru_cache(maxsize=1024)
def fetch(url: str) -> tuple[str, str]:
    if blocked_url(url):
        return url, ""
    try:
        response = SESSION.get(url, timeout=(5, 12), allow_redirects=True)
        if response.status_code == 200 and "text/html" in response.headers.get("content-type", "text/html") and not blocked_url(response.url):
            return response.url, response.text
    except requests.RequestException:
        pass
    return url, ""


def extract(url: str, html: str):
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()
    text = soup.get_text(" ", strip=True)
    found = []
    for anchor in soup.select('a[href^="mailto:"]'):
        email = norm_email(anchor.get("href", "")[7:].split("?")[0])
        block = anchor.find_parent(["li", "p", "div", "section", "article", "td"])
        context = (block.get_text(" ", strip=True) if block else anchor.parent.get_text(" ", strip=True))[:1600]
        if valid_email(email):
            found.append((email, context, "mailto"))
    for email in {norm_email(x) for x in EMAIL_RE.findall(text)}:
        if valid_email(email):
            pos = text.lower().find(email.lower())
            found.append((email, text[max(0, pos - 700):pos + 700] if pos >= 0 else "", "text"))
    links = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(url, anchor["href"])
        label = (anchor.get_text(" ", strip=True) + " " + anchor["href"]).lower()
        if registeredish(host(href)) == registeredish(host(url)) and any(word in label for word in CONTACT_WORDS):
            links.append(href)
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    return list(dict.fromkeys(found)), list(dict.fromkeys(links))[:5], text[:60000], title


def candidate_score(email: str, url: str, page_text: str, title: str, context: str, name: str, category: str, verified_site: bool):
    config = CATEGORY_CONFIG.get(category, {"kind": "person"})
    kind = config.get("kind", "person")
    local, email_domain = email.rsplit("@", 1)
    page_identity = name_match(name, title + " " + page_text[:15000])
    near_identity = name_match(name, context)
    profession = category_match(category, title + " " + page_text[:20000])
    same_domain = registeredish(email_domain) == registeredish(host(url))
    free_mail = email_domain in FREE_MAIL
    if not page_identity or not profession:
        return None
    if kind == "person":
        if local in GENERIC_LOCAL:
            if not near_identity and not verified_site:
                return None
        elif free_mail and not near_identity and not local_name_match(email, name):
            return None
        elif not free_mail and not same_domain and not near_identity and not local_name_match(email, name):
            return None
        score = 55 + (20 if near_identity else 0) + (10 if local_name_match(email, name) else 0) + (10 if same_domain else 0) + (5 if verified_site else 0)
        if local in GENERIC_LOCAL:
            score -= 10
    else:
        if not (same_domain or near_identity):
            return None
        score = 70 + (15 if same_domain else 0) + (5 if near_identity else 0)
    if host(url).endswith(("gov.il", "ac.il", "org.il")):
        score += 5
    return min(score, 100) if score >= 75 else None


def classify(email: str, category: str) -> str:
    local = email.split("@", 1)[0]
    if CATEGORY_CONFIG.get(category, {}).get("kind") in {"community", "creator"}:
        return "BUSINESS_OR_COMMUNITY"
    return "CLINIC_OR_ORGANIZATION" if local in GENERIC_LOCAL else "PERSONAL_PROFESSIONAL"


def research(row: dict) -> dict:
    name = str(row.get("name", "")).strip()
    category = str(row.get("category", "")).strip()
    seed_source = str(row.get("seed_source", "")).strip()
    config = CATEGORY_CONFIG.get(category, {"priority": "", "kind": "person"})
    attempts, candidates = [], []
    for hit in search_web(name, category, seed_source):
        url, html = fetch(hit["url"])
        attempts.append(url)
        if not html:
            continue
        items, links, page_text, title = extract(url, html)
        verified_site = name_match(name, title + " " + page_text[:15000]) and category_match(category, title + " " + page_text[:20000])
        if not verified_site:
            continue
        for email, context, method in items:
            score = candidate_score(email, url, page_text, title, context, name, category, verified_site)
            if score is not None:
                candidates.append((score, email, url, context[:500], hit["query"], method))
        for link in links:
            url2, html2 = fetch(link)
            attempts.append(url2)
            if not html2:
                continue
            items2, _, text2, title2 = extract(url2, html2)
            for email, context, method in items2:
                score = candidate_score(email, url2, text2, title2, context, name, category, True)
                if score is not None:
                    candidates.append((score, email, url2, context[:500], hit["query"], method))
        if any(item[0] >= 90 for item in candidates):
            break
    candidates = sorted(set(candidates), reverse=True)
    base = {"algo_version": ALGO_VERSION, "name": name, "category": category, "priority": config.get("priority", ""), "target_kind": config.get("kind", ""), "seed_source": seed_source}
    if candidates:
        score, email, source, evidence, query, method = candidates[0]
        return base | {"email": email, "email_type": classify(email, category), "confidence": score, "source_url": source, "status": "VERIFIED", "evidence": evidence, "matched_query": query, "extraction_method": method, "attempted_urls": json.dumps(list(dict.fromkeys(attempts)), ensure_ascii=False)}
    return base | {"email": "", "email_type": "", "confidence": 0, "source_url": "", "status": "NO_VERIFIED_PUBLIC_EMAIL", "evidence": "", "matched_query": "", "extraction_method": "", "attempted_urls": json.dumps(list(dict.fromkeys(attempts)), ensure_ascii=False)}


def load_input(path: str):
    source = Path(path)
    frame = pd.read_excel(source) if source.suffix.lower() == ".xlsx" else pd.read_csv(source)
    return frame.fillna("").to_dict("records")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--out", default="output")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    checkpoint = out / "checkpoint.jsonl"
    done = {}
    if args.resume and checkpoint.exists():
        for line in checkpoint.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                result = json.loads(line)
            except Exception:
                continue
            if result.get("algo_version") == ALGO_VERSION:
                done[(result.get("name", ""), result.get("category", ""))] = result
    rows = load_input(args.input)
    checkpoint.write_text("".join(json.dumps(result, ensure_ascii=False) + "\n" for result in done.values()), encoding="utf-8")
    with checkpoint.open("a", encoding="utf-8") as stream:
        for index, row in enumerate(rows, 1):
            key = (str(row.get("name", "")).strip(), str(row.get("category", "")).strip())
            if key in done:
                continue
            print(f"[{index}/{len(rows)}] {key[0]} | {key[1]}", flush=True)
            result = research(row)
            done[key] = result
            stream.write(json.dumps(result, ensure_ascii=False) + "\n")
            stream.flush()
    frame = pd.DataFrame(list(done.values()))
    if frame.empty:
        return
    frame = frame.sort_values(["priority", "status", "confidence"], ascending=[True, True, False]).drop_duplicates(subset=["name", "category"], keep="first")
    person = frame[frame.target_kind == "person"]
    repeated = {email for email, count in Counter(person[person.email != ""].email).items() if count > 2}
    if repeated:
        mask = (frame.target_kind == "person") & frame.email.isin(repeated)
        frame.loc[mask, "status"] = "REVIEW_SHARED_EMAIL"
        frame.loc[mask, "confidence"] = 0
    frame.to_csv(out / "audit.csv", index=False, encoding="utf-8-sig")
    frame.to_excel(out / "audit.xlsx", index=False)
    found = frame[frame.status == "VERIFIED"].copy().sort_values(["priority", "confidence"], ascending=[True, False]).drop_duplicates(subset=["email"], keep="first")
    found.to_csv(out / "contacts.csv", index=False, encoding="utf-8-sig")
    found.to_excel(out / "contacts.xlsx", index=False)
    frame[frame.status.str.startswith("REVIEW")].to_excel(out / "review.xlsx", index=False)
    summary = {"algo_version": ALGO_VERSION, "total_targets": len(frame), "verified": int((frame.status == "VERIFIED").sum()), "not_verified": int((frame.status == "NO_VERIFIED_PUBLIC_EMAIL").sum()), "review": int(frame.status.str.startswith("REVIEW").sum()), "unique_emails": int(found.email.nunique()), "by_category": frame.groupby("category").status.value_counts().unstack(fill_value=0).to_dict("index")}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
