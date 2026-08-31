from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

UA = {"User-Agent": "Mozilla/5.0 (compatible; ProfessionalContactResearch/5.0)"}
DISCOVERY_VERSION = 5
MOH = "https://data.gov.il/he/datasets/ministry-health/database-of-doctors-licenses-moh"
MOH_RESOURCE = "9c64c522-bbc2-48fe-96fb-3b2a8626f59e"
MOH_DATASTORE = "https://data.gov.il/api/3/action/datastore_search"
IALP = "https://ialp.org.il/counselors/"
IMA = "https://www.ima.org.il/doctorsindex/results.aspx?spid=20&page={page}"
DISCOVERY = {
    "family_doctor": ["רופא משפחה ישראל", "רופאת משפחה ישראל", "מומחה רפואת משפחה ישראל"],
    "clinic_manager": ["מנהל מרפאה קופת חולים", "מנהלת מרפאה קופת חולים", "מנהל רפואי מרפאה"],
    "womens_health_center": ["מרכז בריאות האישה", "מרפאת נשים קופת חולים", "מרכז בריאות האישה קופת חולים"],
    "community_clinic": ["מרפאת משפחה קופת חולים", "מרפאה קהילתית", "מרכז רפואי קהילתי"],
    "doula": ["דולה ישראל", "אינדקס דולות ישראל"],
    "midwife": ["מיילדת עצמאית ישראל", "מיילדת פרטית ישראל"],
    "childbirth_educator": ["מדריכת הכנה ללידה ישראל"],
    "birth_center": ["מרכז לידה ישראל"],
    "fertility_doctor": ["רופא פוריות IVF ישראל", "מומחה פריון ישראל"],
    "ivf_unit": ["יחידת IVF בית חולים ישראל"],
    "fertility_center": ["מרכז פוריות פרטי ישראל"],
    "embryologist": ["אמבריולוגית IVF ישראל", "אמבריולוג ישראל"],
    "fertility_nurse": ["אחות פוריות IVF ישראל"],
    "fertility_consultant": ["יועצת פוריות ישראל"],
    "sperm_bank": ["בנק זרע ישראל"],
    "fertility_preservation": ["מרכז שימור פוריות ישראל"],
    "fertility_association": ["עמותת פוריות ישראל"],
    "pelvic_floor": ["פיזיותרפיסטית רצפת אגן נשים ישראל"],
    "sleep_consultant": ["יועצת שינה תינוקות ישראל"],
    "pregnancy_dietitian": ["דיאטנית הריון פוריות ישראל"],
    "parenting_center": ["מרכז הורות תינוקות ישראל"],
    "perinatal_mental_health": ["פסיכולוגית הריון לידה פוריות ישראל"],
    "facebook_group_admin": ["קבוצת פייסבוק הריון לידה ישראל", "קבוצת פייסבוק פוריות ישראל"],
    "community_manager": ["קהילת הריון לידה ישראל", "קהילת פוריות ישראל"],
    "instagram_creator": ["אינסטגרם הריון לידה ישראל", "אינסטגרם פוריות ישראל"],
    "parenting_site": ["אתר הורות הריון לידה ישראל"],
    "pregnancy_podcast": ["פודקאסט הריון לידה פוריות ישראל"],
    "doula_school": ["בית ספר לדולות ישראל"],
    "childbirth_school": ["קורס מדריכות הכנה ללידה ישראל"],
    "women_health_creator": ["בלוג בריאות האישה הריון לידה ישראל"],
}
REGIONS = ("תל אביב", "ירושלים", "חיפה", "באר שבע", "אשדוד", "ראשון לציון", "פתח תקווה", "נתניה", "השרון", "הצפון", "הדרום", "השפלה")
PRIORITY_A = {"gynecologist", "fertility_doctor", "ivf_unit", "fertility_center", "embryologist", "fertility_nurse", "fertility_consultant", "sperm_bank", "fertility_preservation", "fertility_association", "doula", "midwife", "childbirth_educator", "birth_center", "womens_health_center"}
PRIORITY_C = {"facebook_group_admin", "community_manager", "instagram_creator", "parenting_site", "pregnancy_podcast", "doula_school", "childbirth_school", "women_health_creator"}
KNOWN = {
    "ivf_unit": ["יחידת IVF שיבא", "יחידת IVF איכילוב", "יחידת IVF הדסה", "יחידת IVF רמבם", "יחידת IVF סורוקה"],
    "sperm_bank": ["בנק הזרע שיבא", "בנק הזרע איכילוב", "בנק הזרע הדסה", "בנק הזרע רמבם"],
    "fertility_association": ["איילת השחר פוריות", "עמותת חן לפריון"],
    "birth_center": ["מרכז לידה טבעית שיבא", "מרכז לידה טבעית איכילוב"],
    "parenting_site": ["יולדת", "מאקו הורים", "דוקטורס נשים"],
    "doula_school": ["אמאלדת", "ללדת בית ספר למקצועות הלידה"],
    "childbirth_school": ["קורס הכנה ללידה שיבא", "קורס הכנה ללידה איכילוב"],
}
BAD_TITLE = ("wikipedia", "ויקיפדיה", "חדשות", "כתבה", "מאמר", "מדריך", "מחיר", "דרושים", "login", "sign in", "כל מה", "למה ", "איך ", "האם ", "מה זה", "אודות", "צור קשר", "עמוד הבית")
BLOCKED = ("wikipedia.org", "google.com", "youtube.com", "investing.com", "globes.co.il", "mako.co.il", "ynet.co.il", "maariv.co.il", "haaretz.co.il", "ice.co.il")


def clean_name(value):
    return re.sub(r"\s+", " ", str(value or "")).strip(" |-–—:")[:160]


def add(rows, name, category, source="", source_type="discovery"):
    name = clean_name(name)
    if 3 <= len(name) <= 160:
        rows.append({"name": name, "category": category, "seed_source": source, "seed_type": source_type})


def entity_title(title, query):
    value = clean_name(title)
    for separator in (" | ", " - ", " – ", " — ", ":"):
        if separator in value:
            value = value.split(separator)[0].strip()
    low = value.lower()
    if not value or any(word in low for word in BAD_TITLE) or len(value.split()) > 10:
        return ""
    profession_words = [x for x in re.split(r"\s+", query) if len(x) > 3 and x not in {"ישראל"}]
    if not any(word.lower() in low for word in profession_words):
        return ""
    return value


def seed_previous(rows):
    path = Path("targets.csv")
    if not path.exists():
        return 0
    frame = pd.read_csv(path).fillna("")
    for record in frame.to_dict("records"):
        add(rows, record.get("name"), record.get("category"), record.get("seed_source", ""), record.get("seed_type", "previous"))
    return len(frame)


def previous_seed_counts():
    path = Path("targets.csv")
    if not path.exists():
        return {}
    frame = pd.read_csv(path).fillna("")
    return frame.seed_type.value_counts().to_dict() if "seed_type" in frame else {}


def discovery_is_current():
    path = Path("seed_summary.json")
    if not path.exists():
        return False
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("discovery_version") == DISCOVERY_VERSION
    except (OSError, ValueError):
        return False


def seed_moh(rows):
    count = 0
    specialties = {
        "gynecologist": "יילוד וגינקולוגיה",
        "family_doctor": "רפואת המשפחה",
    }
    for category, query in specialties.items():
        offset = 0
        while True:
            try:
                response = requests.get(
                    MOH_DATASTORE,
                    params={"resource_id": MOH_RESOURCE, "q": query, "limit": 1000, "offset": offset},
                    headers=UA,
                    timeout=60,
                )
                response.raise_for_status()
                result = response.json().get("result", {})
                records = result.get("records", [])
            except (requests.RequestException, ValueError):
                break
            for item in records:
                if clean_name(item.get("שם התמחות")) != query:
                    continue
                name = clean_name(f'{item.get("שם פרטי", "")} {item.get("שם משפחה", "")}')
                add(rows, name, category, f"{MOH}/{MOH_RESOURCE}", "moh")
                count += 1
            offset += len(records)
            if not records or offset >= int(result.get("total", 0)):
                break
    return count


def seed_ima(rows):
    seen, empty = set(), 0
    for page in range(1, 40):
        url = IMA.format(page=page)
        try:
            soup = BeautifulSoup(requests.get(url, headers=UA, timeout=30).text, "html.parser")
            before = len(seen)
            for anchor in soup.find_all("a", href=True):
                href, text = anchor.get("href", ""), clean_name(anchor.get_text(" ", strip=True))
                if "doctorprofile" in href.lower() and 3 <= len(text) <= 100:
                    seen.add(text)
                    add(rows, text, "gynecologist", urljoin(url, href), "ima")
            empty = empty + 1 if len(seen) == before else 0
            if empty >= 2 and page > 5:
                break
        except Exception:
            empty += 1
    return len(seen)


def seed_ialp(rows):
    try:
        soup = BeautifulSoup(requests.get(IALP, headers=UA, timeout=30).text, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = urljoin(IALP, anchor["href"])
            text = clean_name(anchor.get_text(" ", strip=True)).split(" – ")[0]
            if urlparse(href).netloc == urlparse(IALP).netloc and "counselor" in href.lower() and text:
                add(rows, text, "lactation", href, "ialp")
    except Exception:
        pass


def web_discovery(rows):
    stats, engine = {}, DDGS()
    for category, queries in DISCOVERY.items():
        before, errors = len(rows), []
        expanded_queries=list(queries)
        if category in {"family_doctor","clinic_manager","womens_health_center","community_clinic","doula","midwife","lactation","pelvic_floor"}:
            expanded_queries += [f"{query} {region}" for query in queries for region in REGIONS]
        for query in expanded_queries:
            try:
                for result in engine.text(query, region="il-he", safesearch="moderate", max_results=30) or []:
                    source = result.get("href") or result.get("url") or ""
                    if any(bad in urlparse(source).netloc.lower() for bad in BLOCKED):
                        continue
                    title = entity_title(result.get("title", ""), query)
                    if title:
                        add(rows, title, category, source, "web")
            except Exception as exc:
                errors.append(type(exc).__name__ + ": " + str(exc)[:120])
            time.sleep(0.25)
        stats[category] = {"added_raw": len(rows) - before, "errors": errors}
    return stats


def main():
    rows = []
    previous = seed_previous(rows)
    prior_seed_counts = previous_seed_counts()
    for category, names in KNOWN.items():
        for name in names:
            add(rows, name, category, "curated_seed", "curated")
    moh = seed_moh(rows)
    ima = 0 if prior_seed_counts.get("ima", 0) >= 300 else seed_ima(rows)
    if prior_seed_counts.get("ialp", 0) < 300:
        seed_ialp(rows)
    discovery = {"skipped": "version-5 discovery already persisted"} if discovery_is_current() else web_discovery(rows)
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise SystemExit("No targets discovered")
    frame["source_rank"] = frame.seed_type.map({"moh": 0, "ima": 0, "ialp": 0, "curated": 1, "previous": 2, "web": 3}).fillna(4)
    frame["priority_rank"] = frame.category.map(lambda category: 0 if category in PRIORITY_A else 2 if category in PRIORITY_C else 1)
    frame = frame.sort_values(["priority_rank", "source_rank", "category", "name"]).drop_duplicates(subset=["name", "category"], keep="first").drop(columns=["source_rank", "priority_rank"])
    if len(frame) < previous:
        raise SystemExit(f"Safety stop: target universe shrank from {previous} to {len(frame)}")
    frame.to_csv("targets.csv", index=False, encoding="utf-8-sig")
    counts = frame.category.value_counts().to_dict()
    summary = {"discovery_version": DISCOVERY_VERSION, "total": len(frame), "previous": previous, "moh_official_records": moh, "ima_gynecology": ima, "categories": counts, "discovery": discovery}
    Path("seed_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    if counts.get("gynecologist", 0) < 300:
        raise SystemExit("Safety stop: fewer than 300 gynecologists retained")


if __name__ == "__main__":
    main()
