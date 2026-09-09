from __future__ import annotations

import json
import os
import re
import time
import concurrent.futures
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

UA = {"User-Agent": "Mozilla/5.0 (compatible; ProfessionalContactResearch/5.0)"}
DISCOVERY_VERSION = 8
MOH = "https://data.gov.il/he/datasets/ministry-health/database-of-doctors-licenses-moh"
MOH_RESOURCE = "9c64c522-bbc2-48fe-96fb-3b2a8626f59e"
MOH_DATASTORE = "https://data.gov.il/api/3/action/datastore_search"
IALP = "https://ialp.org.il/counselors/"
IMA = "https://www.ima.org.il/doctorsindex/results.aspx?spid={spid}&page={page}"
IMA_SPECIALTIES = {
    "gynecologist": 20,
    "family_doctor": 99,
}
KNOWN_MANAGER_TARGETS = {
    "שי גור":"https://hospitals.clalit.co.il/geha/he/med/clinics/Pages/adults.aspx",
    "יוליה ולדמן-גרינשפון":"https://hospitals.clalit.co.il/soroka/he/med-units/medicine-division/Pages/dermatoclinic.aspx",
    "בועז בלוך":"https://hospitals.clalit.co.il/emek/he/departmentsandclinics/internal_departments/Pages/mental_health_clinic.aspx",
    "איתן מנגובי":"https://hospitals.clalit.co.il/carmel/he/Departments-and-Outpatient-Clinics-main/Clinical-departments-and-clinics/Pages/pre-surgery.aspx",
    "אלכס גורי":"https://hospitals.clalit.co.il/kaplan/he/med_units/travel_clinic/Pages/travel_clinic.aspx",
    "תמר גוטסמן יקותיאלי":"https://hospitals.clalit.co.il/rabin/he/special-medical-services/travelers-clinic-beilinson/Pages/travelers_clinic_beilinson.aspx",
    "מרק הלמן":"https://hospitals.clalit.co.il/rabin/he/departments-and-clinics/neurology/Pages/multiple_sclerosis_neuro_immunology.aspx",
    "שומרית דיין-רוזנבלום":"https://hospitals.clalit.co.il/shalvata/he/children/departments/Pages/childrens_ward.aspx",
}
KNOWN_MANAGER_URLS=tuple(KNOWN_MANAGER_TARGETS.values())
EXCLUDED_CATEGORIES = {"instagram_creator"}
INVALID_ENTITY_NAMES = {
    "ראשי", "אודות", "אודותינו", "הצוות שלנו", "מי אני", "צור קשר", "נשים", "דף הבית",
}
GENERIC_PERSON_TARGET_PHRASES = {
    "ועידה", "ועידת", "כנס", "רופאים פרטיים", "רופא משפחה פרטי", "יומן", "מאמר", "כתבה",
    "טיפול", "טיפולים", "פיזיותרפיה", "דיכאון", "פלטפורמת", "רשימה של", "יחידות",
    "הרשמה וקבלה", "קניה ומכירה", "אודות אתר", "בלוג", "מדריך", "מרכז רפואי",
    "התמחות ברפואת משפחה", "להתמחות ברפואת משפחה", "ייעוץ רפואת ילדים", "קורס הכנה ללידה",
    "מומחה ברפואת משפחה", "מומחית ברפואת משפחה", "מומחה רפואת משפחה", "מומחית רפואת משפחה",
    "מנהל מרפאה", "מנהלת מרפאה", "מנהל רפואי",
}
CLINIC_MANAGER_ROLE_PHRASES = {"מנהל מרפאה", "מנהלת מרפאה", "מנהל המרפאה", "מנהלת המרפאה", "מנהל רפואי", "מנהלת רפואית"}
NON_NAME_TOKENS = {
    "ivf", "vbac", "israel", "ישראל", "אתר", "קורס", "קורסי", "לידה", "לידות",
    "הריון", "הנקה", "פוריות", "פריון", "הפריה", "גופית", "אמבריולוגיה", "אמבריולוג",
    "דולה", "דולות", "מיילדת", "מיילדות", "יועצת", "יועץ", "אחות", "פיזיותרפיה",
    "רצפת", "אגן", "רופא", "רופאת", "רופאים", "רפואה", "רפואי", "משפחה",
    "מרכז", "מרכזי", "יחידה", "יחידות", "מכון", "מרפאה", "מרפאת", "בית", "ספר",
    "מנהל", "מנהלת", "התמחות", "להתמחות", "ייעוץ", "ילדים", "כללית", "מכבי", "מאוחדת", "לאומית",
    "pelvic", "floor", "doula", "midwife", "clinic", "center", "centre",
}
PERSON_CATEGORIES = {
    "gynecologist", "family_doctor", "clinic_manager", "fertility_doctor", "embryologist",
    "fertility_nurse", "fertility_consultant", "doula", "midwife", "childbirth_educator",
    "lactation", "pelvic_floor", "sleep_consultant", "pregnancy_dietitian", "perinatal_mental_health",
}
DISCOVERY = {
    "family_doctor": ["רופא משפחה ישראל", "רופאת משפחה ישראל", "מומחה רפואת משפחה ישראל"],
    "clinic_manager": [
        'site:hospitals.clalit.co.il "מנהל המרפאה" ד"ר',
        'site:hospitals.clalit.co.il "מנהלת המרפאה" ד"ר',
        'site:clalit.co.il "מנהל המרפאה" ד"ר',
        'site:maccabi4u.co.il "מנהל המרפאה" ד"ר',
        'site:meuhedet.co.il "מנהל המרפאה" ד"ר',
        'site:leumit.co.il "מנהל המרפאה" ד"ר',
        '"מנהל מרפאה" ד"ר קופת חולים',
        '"מנהלת מרפאה" ד"ר קופת חולים',
    ],
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
    "parenting_site": ["אתר הורות הריון לידה ישראל"],
    "pregnancy_podcast": ["פודקאסט הריון לידה פוריות ישראל"],
    "doula_school": ["בית ספר לדולות ישראל"],
    "childbirth_school": ["קורס מדריכות הכנה ללידה ישראל"],
    "women_health_creator": ["בלוג בריאות האישה הריון לידה ישראל"],
}
REGIONS = ("תל אביב", "ירושלים", "חיפה", "באר שבע", "אשדוד", "ראשון לציון", "פתח תקווה", "נתניה", "השרון", "הצפון", "הדרום", "השפלה")
PRIORITY_A = {"gynecologist", "family_doctor", "clinic_manager", "fertility_doctor", "ivf_unit", "fertility_center", "embryologist", "fertility_nurse", "fertility_consultant", "sperm_bank", "fertility_preservation", "fertility_association", "doula", "midwife", "childbirth_educator", "birth_center", "womens_health_center"}
PRIORITY_C = {"facebook_group_admin", "community_manager", "parenting_site", "pregnancy_podcast", "doula_school", "childbirth_school", "women_health_creator"}
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


def person_identity_key(name, category):
    value = re.sub(r"^(?:ד[\"״']?ר|דוקטור|פרופ[\"׳']?|פרופסור)\s+", "", clean_name(name), flags=re.I)
    words = [word for word in re.split(r"[^\w\u0590-\u05ff]+", value.lower()) if len(word) >= 2]
    return " ".join(sorted(words)) if category in PERSON_CATEGORIES else " ".join(words)


def valid_person_target(name, category, source_type="", role_evidence=""):
    if category not in PERSON_CATEGORIES:
        return True
    value=clean_name(name).lower()
    rejected_phrases=GENERIC_PERSON_TARGET_PHRASES-(CLINIC_MANAGER_ROLE_PHRASES if category=="clinic_manager" else set())
    if any(phrase in value for phrase in rejected_phrases):
        return False
    words=[word for word in re.split(r"[^\w\u0590-\u05ff]+",value) if len(word)>=2 and word not in {"דר","דוקטור","פרופ","פרופסור"}]
    plausible=[word for word in words if word not in NON_NAME_TOKENS]
    structurally_valid=2<=len(words)<=6 and len(plausible)>=2 and not any(word.isdigit() for word in words) and not any(char in value for char in ("?","!","@"))
    if category=="clinic_manager":
        evidence=clean_name(str(name)+" "+str(role_evidence)).lower()
        return structurally_valid and any(role in evidence for role in CLINIC_MANAGER_ROLE_PHRASES) and any(word in evidence for word in ("מרפאה","מרפאת"))
    return structurally_valid


def add(rows, name, category, source="", source_type="discovery", **metadata):
    name = clean_name(name)
    if category not in EXCLUDED_CATEGORIES and name not in INVALID_ENTITY_NAMES and 3 <= len(name) <= 160 and valid_person_target(name,category,source_type,metadata.get("role_evidence","")):
        rows.append({"name": name, "category": category, "seed_source": source, "seed_type": source_type} | metadata)


def clinic_manager_people(title, snippet):
    """Extract named physicians only when nearby text states a clinic-manager role."""
    # clean_name is intentionally capped for entity labels; never use that cap
    # for full-page evidence or roles below the first navigation block vanish.
    text = re.sub(r"\s+", " ", f"{title} {snippet}").strip()[:500000]
    roles = list(re.finditer(r"(?:מנהל(?:ת)?(?:\s+רפואי(?:ת)?)?\s+(?:ה)?מרפא(?:ה|ת)|מנהל(?:ת)?\s+מרפא(?:ה|ת))", text))
    doctors = list(re.finditer(r"(?:ד[\"״']?ר|דוקטור|פרופ[\"׳']?|פרופסור)\s+([א-ת][א-ת׳'\"-]+(?:\s+[א-ת][א-ת׳'\"-]+){1,3})", text))
    stop={"מונה","מונתה","הוא","היא","מנהל","מנהלת","רפואי","רפואית","מרפאה","מרפאת","המרפאה","של","את","במרפאה","למרפאה","צוות","הצוות","מציע","מציעה","יצירת","קשר","סגן","סגנית","אח","אחות","אחראי","אחראית","מיקום","פרטים","נגישות","תוכן","דף","כתובת","טלפון","דואל","דוא״ל","שעות"}
    found=[]
    for role in roles:
        if re.search(r"(?:סגן|סגנית|ממלא(?:ת)? מקום)\s*$",text[max(0,role.start()-20):role.start()]):continue
        after=[doctor for doctor in doctors if 0<=doctor.start()-role.end()<=35]
        before=[doctor for doctor in doctors if 0<=role.start()-doctor.end()<=160 and any(cue in text[doctor.end():role.start()] for cue in ("מונה","מונתה","משמש","משמשת","הוא","היא",","," - "))]
        nearby=after or before
        doctor=min(nearby,key=lambda match:abs(match.start()-role.start())) if nearby else None
        if not doctor:continue
        kept=[]
        for word in doctor.group(1).split():
            normalized=word.strip(".,:;()[]").lower()
            if normalized in stop:break
            kept.append(word.strip(".,:;()[]"))
        name=clean_name(" ".join(kept))
        evidence=re.sub(r"\s+"," ",text[max(0,role.start()-160):role.end()+160]).strip()
        if 2<=len(name.split())<=4 and name not in {item[0] for item in found}:found.append((name,evidence))
    return found


def clinic_manager_person(title, snippet):
    people=clinic_manager_people(title,snippet)
    return people[0] if people else ("","")


def seed_clalit_manager_sitemap(rows):
    """Discover managers deterministically from official hospital pages, without a search API."""
    session=requests.Session()
    retry=Retry(total=2,connect=2,read=2,status=2,backoff_factor=0.25,status_forcelist=(429,500,502,503,504),allowed_methods=frozenset({"GET"}))
    session.mount("https://",HTTPAdapter(max_retries=retry,pool_connections=16,pool_maxsize=16))
    try:
        index=session.get("https://hospitals.clalit.co.il/sitemap.xml",headers=UA,timeout=30)
        index.raise_for_status()
        child_maps=[node.text.strip() for node in ET.fromstring(index.content).iter() if node.tag.endswith("loc") and node.text and "mobile" not in node.text]
        urls=[]
        for child in child_maps:
            response=session.get(child,headers=UA,timeout=60); response.raise_for_status()
            urls.extend(node.text.strip() for node in ET.fromstring(response.content).iter() if node.tag.endswith("loc") and node.text)
    except (requests.RequestException,ET.ParseError) as exc:
        return {"pages_considered":0,"pages_fetched":0,"added_raw":0,"errors":[type(exc).__name__+": "+str(exc)[:120]]}
    candidates=list(KNOWN_MANAGER_URLS)
    clinic_segments={"clinic","clinics","outpatient","outpatient-clinics","מרפאה","מרפאות"}
    for url in dict.fromkeys(urls):
        parsed=urlparse(url)
        path=parsed.path.lower()
        if parsed.netloc.lower().split(":")[0]!="hospitals.clalit.co.il" or "/he/" not in path:continue
        if path.endswith((".pdf",".doc",".docx",".xls",".xlsx",".ppt",".pptx",".jpg",".jpeg",".png")):continue
        segments=path.split("/")
        if any(segment in clinic_segments for segment in segments) or (segments and "clinic" in segments[-1]):candidates.append(url)
    candidates=list(dict.fromkeys(candidates))
    known=set(KNOWN_MANAGER_URLS)
    candidates.sort(key=lambda url:(0 if url in known else 1 if "clinic" in urlparse(url).path.lower().split("/")[-1] else 2,url))
    def inspect(url):
        try:
            # This is broad discovery, not verification. Fail fast here; the
            # research stage retries the small set of actual candidate pages.
            response=requests.get(url,headers=UA,timeout=(3,8)); response.raise_for_status()
            if "text/html" not in response.headers.get("content-type","").lower():return [],False
            soup=BeautifulSoup(response.text,"html.parser")
            return [(name,evidence,url) for name,evidence in clinic_manager_people(soup.title.get_text(" ",strip=True) if soup.title else "",soup.get_text(" ",strip=True))],True
        except requests.RequestException:return [],False
    found=[]; fetched=0
    # The site starts returning generic WAF pages under high concurrency. Four
    # workers remains fast for the filtered set and preserves actual content.
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(inspect,url) for url in candidates]
        for completed,future in enumerate(concurrent.futures.as_completed(futures),1):
            items,success=future.result(); found.extend(items); fetched+=success
            if completed%500==0:print(f"Clinic-manager sitemap {completed}/{len(candidates)}",flush=True)
    before=len(rows)
    for name,evidence,url in found:add(rows,name,"clinic_manager",url,"official_sitemap",role_evidence=evidence)
    return {"pages_considered":len(candidates),"pages_fetched":fetched,"added_raw":len(rows)-before,"errors":[]}


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
        add(
            rows, record.get("name"), record.get("category"), record.get("seed_source", ""),
            record.get("seed_type", "previous"), license_number=record.get("license_number", ""),
            specialty_certificate=record.get("specialty_certificate", ""), role_evidence=record.get("role_evidence", ""),
        )
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
        summary=json.loads(path.read_text(encoding="utf-8"))
        return summary.get("discovery_version")==DISCOVERY_VERSION and int(summary.get("categories",{}).get("clinic_manager",0) or 0)>=len(KNOWN_MANAGER_TARGETS)
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
                add(
                    rows, name, category, f"{MOH}/{MOH_RESOURCE}", "moh",
                    license_number=item.get("מספר רישיון רופא", ""),
                    specialty_certificate=item.get("מספר תעודת התמחות", ""),
                )
                count += 1
            offset += len(records)
            if not records or offset >= int(result.get("total", 0)):
                break
    return count


def seed_ima(rows, categories=None):
    counts = {}
    for category, spid in IMA_SPECIALTIES.items():
        if categories is not None and category not in categories:
            continue
        seen, empty = set(), 0
        for page in range(1, 80):
            url = IMA.format(spid=spid, page=page)
            try:
                response = requests.get(url, headers=UA, timeout=30)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                before = len(seen)
                for anchor in soup.find_all("a", href=True):
                    href, text = anchor.get("href", ""), clean_name(anchor.get_text(" ", strip=True))
                    if "doctorprofile" not in href.lower() or not text or text in {"מידע נוסף"}:
                        continue
                    profile = urljoin(url, href)
                    key = (text, profile)
                    if key not in seen:
                        seen.add(key)
                        add(rows, text, category, profile, "ima")
                empty = empty + 1 if len(seen) == before else 0
                if empty >= 2 and page > 5:
                    break
            except requests.RequestException:
                empty += 1
                if empty >= 3:
                    break
        counts[category] = len(seen)
    return counts


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
        if category in {"family_doctor","womens_health_center","community_clinic","doula","midwife","lactation","pelvic_floor"}:
            expanded_queries += [f"{query} {region}" for query in queries for region in REGIONS]
        for query in expanded_queries:
            try:
                serpapi_key=os.getenv("SERPAPI_KEY","").strip()
                if serpapi_key:
                    response=requests.get("https://serpapi.com/search.json",params={"engine":"google","q":query,"gl":"il","hl":"he","num":100,"api_key":serpapi_key},headers=UA,timeout=40)
                    response.raise_for_status()
                    results=[{"href":item.get("link",""),"title":item.get("title",""),"body":item.get("snippet","")} for item in response.json().get("organic_results",[])]
                else:
                    results=engine.text(query, region="il-he", safesearch="moderate", max_results=30, backend="bing,brave") or []
                for result in results:
                    source = result.get("href") or result.get("url") or ""
                    if any(bad in urlparse(source).netloc.lower() for bad in BLOCKED):
                        continue
                    if category=="clinic_manager":
                        title,role_evidence=clinic_manager_person(result.get("title", ""),result.get("body", ""))
                        if title:add(rows,title,category,source,"web",role_evidence=role_evidence)
                    else:
                        title = entity_title(result.get("title", ""), query)
                        if title:add(rows, title, category, source, "web")
            except Exception as exc:
                if "No results found" not in str(exc):
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
    for name,url in KNOWN_MANAGER_TARGETS.items():
        add(rows,name,"clinic_manager",url,"official_curated",role_evidence=f"מנהל המרפאה: ד\"ר {name}")
    moh = seed_moh(rows)
    prior_frame = pd.read_csv("targets.csv").fillna("") if Path("targets.csv").exists() else pd.DataFrame()
    missing_ima = {
        category for category in IMA_SPECIALTIES
        if prior_frame.empty or len(prior_frame[(prior_frame.get("seed_type", "") == "ima") & (prior_frame.get("category", "") == category)]) < 300
    }
    ima = seed_ima(rows, missing_ima) if missing_ima else {"skipped": "full IMA specialty coverage already persisted"}
    if prior_seed_counts.get("ialp", 0) < 300:
        seed_ialp(rows)
    if discovery_is_current():
        discovery={"skipped":f"version-{DISCOVERY_VERSION} discovery already persisted"}
    else:
        manager_sitemap=seed_clalit_manager_sitemap(rows)
        discovery=web_discovery(rows)
        discovery["clinic_manager_official_sitemap"]=manager_sitemap
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise SystemExit("No targets discovered")
    frame["source_rank"] = frame.seed_type.map({"ima": 0, "ialp": 0, "curated": 1, "moh": 2, "previous": 3, "web": 4}).fillna(5)
    frame["priority_rank"] = frame.category.map(lambda category: 0 if category in PRIORITY_A else 2 if category in PRIORITY_C else 1)
    frame["identity_key"] = [person_identity_key(name, category) for name, category in zip(frame.name, frame.category)]
    frame = frame.sort_values(["priority_rank", "source_rank", "category", "name"]).drop_duplicates(subset=["identity_key", "category"], keep="first").drop(columns=["source_rank", "priority_rank", "identity_key"])
    expected_previous = previous
    if not prior_frame.empty and "category" in prior_frame:
        comparable = prior_frame[
            ~prior_frame.category.isin(EXCLUDED_CATEGORIES)
            & ~prior_frame.name.map(clean_name).isin(INVALID_ENTITY_NAMES)
        ].copy()
        comparable = comparable[
            [valid_person_target(name,category,seed_type,role_evidence) for name,category,seed_type,role_evidence in zip(comparable.name,comparable.category,comparable.seed_type,comparable.get("role_evidence",pd.Series([""]*len(comparable))))]
        ]
        comparable["identity_key"] = [person_identity_key(name, category) for name, category in zip(comparable.name, comparable.category)]
        expected_previous = len(comparable.drop_duplicates(subset=["identity_key", "category"]))
    if len(frame) < expected_previous:
        raise SystemExit(f"Safety stop: target universe shrank unexpectedly from {previous} to {len(frame)}")
    frame.to_csv("targets.csv", index=False, encoding="utf-8-sig")
    counts = frame.category.value_counts().to_dict()
    summary = {
        "discovery_version": DISCOVERY_VERSION,
        "total": len(frame),
        "previous": previous,
        "moh_records_refreshed": moh,
        "moh_targets_retained": int((frame.seed_type == "moh").sum()),
        "ima_official_profiles": ima,
        "categories": counts,
        "discovery": discovery,
    }
    Path("seed_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    if counts.get("gynecologist", 0) < 300:
        raise SystemExit("Safety stop: fewer than 300 gynecologists retained")


if __name__ == "__main__":
    main()
