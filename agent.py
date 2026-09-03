from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import threading
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

ALGO_VERSION = 8
EMAIL_RE = re.compile(r"(?i)(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.-])")
OBFUSCATED_EMAIL_RE = re.compile(
    r"(?ix)(?<![\w.+-])([a-z0-9._%+-]+)\s*(?:\[|\()?\s*(?:at|שטרודל)\s*(?:\]|\))?\s*"
    r"([a-z0-9.-]+)\s*(?:\[|\()?\s*(?:dot|נקודה)\s*(?:\]|\))?\s*([a-z]{2,}(?:\.[a-z]{2,})?)(?![\w.-])"
)
BAD_LOCAL = {
    "example", "test", "noreply", "no-reply", "do-not-reply", "donotreply",
    "webmaster", "privacy", "abuse", "support", "johndoe", "john.doe",
}
PLACEHOLDER_DOMAINS = {"example.com", "example.org", "example.net", "company.com", "mailservice.com"}
PLATFORM_DOMAINS = {"fb.com", "facebook.com", "instagram.com"}
THIRD_PARTY_LEAD_DOMAINS = {"prospeo.io", "hunter.io", "rocketreach.co", "zoominfo.com", "apollo.io"}
NON_OUTREACH_LOCAL_PARTS = ("refund", "billing", "accounts-payable", "career", "jobs", "privacy", "abuse")
NON_OUTREACH_LOCAL_EXACT = {"zimun", "appointments", "torim", "webmaster"}
GENERIC_LOCAL = {"info", "office", "clinic", "contact", "mail", "reception", "admin", "secretary", "nashim", "service", "hello", "igudyhanaka", "customerservice", "visitors", "1800", "general", "center", "centre"}
INSTITUTION_ROLE_PARTS = ("clinic", "unit", "ivf", "nashim", "dept", "department", "office", "secretary", "reception", "center", "centre", "admin")
FREE_MAIL = {"gmail.com", "walla.co.il", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "bezeqint.net", "012.net.il", "netvision.net.il"}
BLOCKED_DOMAINS = {"google.com", "youtube.com", "wikipedia.org", "wiktionary.org", "linkedin.com", "twitter.com", "rocketreach.co", "zoominfo.com", "prospeo.io", "hunter.io", "apollo.io", "stockanalysis.com", "yahoo.com", "investing.com", "pinterest.com", "mako.co.il", "ynet.co.il", "maariv.co.il", "haaretz.co.il", "israelhayom.co.il", "ice.co.il", "globes.co.il", "themarker.com", "jusbrasil.com.br", "ubereats.com", "ilovepdf.com", "smallpdf.com", "drugs.com", "amazon.com", "reddit.com", "asli.org.il", "choosingwisely.org.il", "doctorsonly.co.il"}
TRUSTED_REGISTRIES = {"ima.org.il", "practitioners.health.gov.il", "gov.il", "doctors.co.il", "infomed.co.il", "medreviews.co.il", "doctorita.co.il", "docadvisor.co.il", "maccabi4u.co.il", "clalit.co.il", "meuhedet.co.il", "leumit.co.il", "sheba.co.il", "tasmc.org.il", "hadassah.org.il", "rambam.org.il", "assuta.co.il", "hospitals.clalit.co.il", "ialp.org.il", "midwives.org.il"}
GENERAL_CONTENT_PATHS = ("/article", "/articles", "/blog", "/news", "/magazine", "/forum", "/forums", "/podcast", "/כתבות", "/מאמר", "/חדשות", "/פורום")
DIRECTORY_DOMAINS = ("doctors.co.il", "doctorim.co.il", "infomed.co.il", "medreviews.co.il", "doctorita.co.il", "docadvisor.co.il", "medico.co.il", "beok.co.il", "medpage.co.il", "ima.org.il", "miok.co.il", "bikurofe.co.il", "d.co.il", "easy.co.il", "freeindex.co.il", "doctorindex.co.il", "zap.co.il", "forty.co.il", "prog.co.il", "b144.co.il", "israelbusinessguide.com")
CONTACT_WORDS = ("contact", "about", "email", "team", "staff", "צור-קשר", "צור קשר", "אודות", "דוא״ל", "דואר אלקטרוני", "צוות")
OFFICIAL_LINK_WORDS = ("website", "official site", "personal site", "clinic site", "אתר", "אתר אישי", "אתר המרפאה")
PROFILE_PATH_HINTS = ("doctorprofile", "/doctor/", "/doctors/", "/experts/", "/profile/", "/people/", "doctorssearch/dr/")
GENERIC_LIST_PATHS = ("/doctors/", "/experts/", "/results", "/search", "/index", "/contact", "/contact-us")
INSTITUTION_LINK_WORDS = ("department", "unit", "clinic", "מחלקה", "יחידה", "מרפאה", "אגף")
LARGE_INSTITUTION_DOMAINS = {
    "tasmc.org.il", "sheba.co.il", "hadassah.org.il", "rambam.org.il", "szmc.org.il",
    "clalit.co.il", "maccabi4u.co.il", "meuhedet.co.il", "leumit.co.il", "gov.il",
    "assuta.co.il", "hospitals.clalit.co.il", "shamir.org", "laniado.org.il",
    "mayanei-hayeshua.co.il", "wolfson.org.il", "bmc.gov.il", "poria.health.gov.il",
    "ziv.health.gov.il", "hymc.org.il", "emekmedicalcenter.org.il",
}
ORGANIZATION_DOMAIN_GROUPS = (
    {"tasmc.org.il", "tlvmc.gov.il"},
    {"maccabi4u.co.il", "mac.org.il"},
    {"clalit.co.il", "hospitals.clalit.co.il"},
)
INVALID_TARGET_NAMES = {"ראשי", "אודות", "הצוות שלנו", "מי אני", "צור קשר", "נשים", "דף הבית"}
CATEGORY_CONFIG = {
    "gynecologist": {"priority": "A", "terms": ["יילוד", "גינקולוג", "גניקולוג", "רופא נשים", "רפואת נשים", "גינקולוגיה", "גניקולוגיה", "מיילדות", "obstetric", "gynecolog", "ob/gyn", "obgyn"], "kind": "person"},
    "family_doctor": {"priority": "B", "terms": ["רפואת משפחה", "רופא משפחה", "רופאת משפחה", "מומחה ברפואת המשפחה", "רפואה ראשונית", "family medicine", "family physician"], "kind": "person"},
    "clinic_manager": {"priority": "B", "terms": ["מנהל מרפאה", "מנהלת מרפאה", "ניהול מרפאה", "medical director"], "kind": "person"},
    "womens_health_center": {"priority": "A", "terms": ["מרכז בריאות האישה", "מרפאת נשים", "בריאות האישה", "women health"], "kind": "org"},
    "community_clinic": {"priority": "B", "terms": ["מרפאה קהילתית", "מרפאת משפחה", "מרכז רפואי", "רפואה ראשונית"], "kind": "org"},
    "fertility_doctor": {"priority": "A", "terms": ["פוריות", "פריון", "ivf", "שימור פוריות"], "kind": "person"}, "ivf_unit": {"priority": "A", "terms": ["ivf", "הפריה חוץ גופית", "יחידת פוריות"], "kind": "org"}, "fertility_center": {"priority": "A", "terms": ["מרכז פוריות", "מרפאת פוריות", "פריון"], "kind": "org"}, "embryologist": {"priority": "A", "terms": ["אמבריולוג", "embryologist", "ivf"], "kind": "person"}, "fertility_nurse": {"priority": "A", "terms": ["אחות פוריות", "אחות פריון", "ivf"], "kind": "person"}, "fertility_consultant": {"priority": "A", "terms": ["יועצת פוריות", "יועץ פוריות", "פריון"], "kind": "person"}, "sperm_bank": {"priority": "A", "terms": ["בנק זרע", "תרומת זרע"], "kind": "org"}, "fertility_preservation": {"priority": "A", "terms": ["שימור פוריות"], "kind": "org"}, "fertility_association": {"priority": "A", "terms": ["עמותת פוריות", "ארגון פוריות", "פריון"], "kind": "org"}, "doula": {"priority": "A", "terms": ["דולה", "doula", "תומכת לידה"], "kind": "person"}, "midwife": {"priority": "A", "terms": ["מיילדת", "midwife"], "kind": "person"}, "childbirth_educator": {"priority": "A", "terms": ["הכנה ללידה", "מדריכת לידה"], "kind": "person"}, "birth_center": {"priority": "A", "terms": ["מרכז לידה", "חדר לידה", "יולדות"], "kind": "org"}, "lactation": {"priority": "B", "terms": ["יועצת הנקה", "ibclc", "הנקה"], "kind": "person"}, "pelvic_floor": {"priority": "B", "terms": ["רצפת אגן", "פיזיותרפיה"], "kind": "person"}, "sleep_consultant": {"priority": "B", "terms": ["יועצת שינה", "ייעוץ שינה"], "kind": "person"}, "pregnancy_dietitian": {"priority": "B", "terms": ["דיאטנית", "תזונה", "הריון", "פוריות"], "kind": "person"}, "parenting_center": {"priority": "B", "terms": ["מרכז הורות", "הורים ותינוקות"], "kind": "org"}, "perinatal_mental_health": {"priority": "B", "terms": ["פסיכולוג", "טיפול רגשי", "הריון", "פוריות"], "kind": "person"}, "facebook_group_admin": {"priority": "C", "terms": ["קבוצת פייסבוק", "הריון", "פוריות"], "kind": "community"}, "community_manager": {"priority": "C", "terms": ["קהילה", "הריון", "פוריות"], "kind": "community"}, "parenting_site": {"priority": "C", "terms": ["הורות", "הריון", "לידה"], "kind": "org"}, "pregnancy_podcast": {"priority": "C", "terms": ["פודקאסט", "הריון", "פוריות"], "kind": "creator"}, "doula_school": {"priority": "C", "terms": ["בית ספר לדולות", "קורס דולות"], "kind": "org"}, "childbirth_school": {"priority": "C", "terms": ["הכנה ללידה", "קורס מדריכות"], "kind": "org"}, "women_health_creator": {"priority": "C", "terms": ["בריאות האישה", "הריון", "לידה"], "kind": "creator"}}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ProfessionalContactResearch/8.0; public-contact-research)"}
SEARCH_CALL_LIMIT = int(os.getenv("SEARCH_CALL_LIMIT", "12000"))
SEARCH_CIRCUIT_FAILURES = int(os.getenv("SEARCH_CIRCUIT_FAILURES", "20"))
SEARCH_BACKENDS = os.getenv("SEARCH_BACKENDS", "bing,brave,duckduckgo").strip()
RESEARCH_WORKERS = max(1, int(os.getenv("RESEARCH_WORKERS", "4")))
SEARCH_CALLS = 0
SEARCH_CONSECUTIVE_FAILURES = 0
SEARCH_CIRCUIT_OPEN = False
SEARCH_LOCK = threading.Lock()
THREAD_LOCAL = threading.local()

PERSON_ROLE_REJECT = {
    "sales", "marketing", "international", "logistics", "support", "customerservice",
    "service", "visitors", "billing", "finance", "media", "press",
}
GENERIC_PERSON_TARGET_PHRASES = {
    "ועידה", "ועידת", "כנס", "רופאים פרטיים", "רופא משפחה פרטי", "יומן", "מאמר", "כתבה",
    "טיפול", "טיפולים", "פיזיותרפיה", "דיכאון", "פלטפורמת", "רשימה של", "יחידות",
    "הרשמה וקבלה", "קניה ומכירה", "אודות אתר", "בלוג", "מדריך", "מרכז רפואי",
    "מנהל מרפאה", "מנהלת מרפאה", "מנהל רפואי",
}


def http_session():
    session = getattr(THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update(HEADERS)
        THREAD_LOCAL.session = session
    return session

def norm(value): return re.sub(r"[^a-z0-9\u0590-\u05ff]+", " ", unicodedata.normalize("NFKD", str(value or "")).lower()).strip()
def tokens(value): return [x for x in norm(value).split() if len(x)>=2 and x not in {"דר","דוקטור","פרופ","פרופסור","doctor","prof"}]
def host(url):
    value=urlparse(url).netloc.lower().split(":")[0]; return value[4:] if value.startswith("www.") else value
def registeredish(domain):
    parts=domain.lower().split("."); return ".".join(parts[-3:]) if len(parts)>=3 and parts[-2] in {"co","org","ac","gov","net","com"} else ".".join(parts[-2:])
def related_domains(first,second):
    a,b=registeredish(first),registeredish(second)
    if a==b:return True
    return any(a in group and b in group for group in ORGANIZATION_DOMAIN_GROUPS)
def blocked_url(url):
    domain=host(url); return not domain or any(domain==bad or domain.endswith("."+bad) for bad in BLOCKED_DOMAINS)
def trusted_registry(url):
    domain=host(url); return any(domain==x or domain.endswith("."+x) for x in TRUSTED_REGISTRIES)
def large_institution(url):
    domain=host(url); return domain.endswith(".ac.il") or any(domain==x or domain.endswith("."+x) for x in LARGE_INSTITUTION_DOMAINS)
def directory_site(url):
    domain=host(url); return any(domain==x or domain.endswith("."+x) for x in DIRECTORY_DOMAINS)
def name_match(name,text):
    wanted=tokens(name); hay=set(tokens(text)); needed=len(wanted) if len(wanted)<=2 else len(wanted)-1; return bool(wanted) and sum(x in hay for x in wanted)>=needed
def category_match(category,text): return any(norm(term) in norm(text) for term in CATEGORY_CONFIG.get(category,{}).get("terms",[]) if norm(term))
def allowed_identity_page(url,title,page_text,name,category):
    path=urlparse(url).path.lower()
    if any(x in path for x in GENERAL_CONTENT_PATHS): return False
    title_identity=name_match(name,title)
    intro_identity=name_match(name,page_text[:2500])
    profession=category_match(category,title+" "+page_text[:5000])
    if not profession or not (title_identity or intro_identity):return False
    specific_path=any(hint in path for hint in PROFILE_PATH_HINTS) and path not in GENERIC_LIST_PATHS
    if directory_site(url) or large_institution(url):
        return title_identity or (specific_path and intro_identity)
    return title_identity or intro_identity
def allowed_search_identity_page(url,title,page_text,name,category):
    if not allowed_identity_page(url,title,page_text,name,category):return False
    path=urlparse(url).path.lower(); specific_path=any(hint in path for hint in PROFILE_PATH_HINTS)
    return name_match(name,title) or (specific_path and name_match(name,page_text[:2500]))
def norm_email(email): return email.strip(" <>[](){}.,;:\"'").lower().replace("\u00a0","")
def valid_email(email):
    if "@" not in email:return False
    local,domain=email.rsplit("@",1)
    if not local or not domain or "." not in domain or ".." in email or not EMAIL_RE.fullmatch(email):return False
    if local in BAD_LOCAL or domain in PLACEHOLDER_DOMAINS or domain in PLATFORM_DOMAINS:return False
    if local in NON_OUTREACH_LOCAL_EXACT or any(part in local for part in NON_OUTREACH_LOCAL_PARTS):return False
    if domain.endswith((".png",".jpg",".jpeg",".webp")):return False
    if "example" in local or local.startswith(("yourname","your.name","name.surname")):return False
    return True
def local_name_match(email,name):
    local=norm(email.split("@",1)[0]).replace(" ",""); latin=[x for x in tokens(name) if re.search("[a-z]",x) and len(x)>=3]; return bool(latin) and any(x in local for x in latin)
def normalized_local(email):
    return re.sub(r"[^a-z]+","",email.split("@",1)[0].lower())
def role_address(email):
    local=normalized_local(email)
    return local in GENERIC_LOCAL or any(part in local for part in INSTITUTION_ROLE_PARTS) or local in PERSON_ROLE_REJECT
def forbidden_person_role(email): return normalized_local(email) in PERSON_ROLE_REJECT
def valid_person_target_name(name):
    value=norm(name)
    if not value or any(norm(phrase) in value for phrase in GENERIC_PERSON_TARGET_PHRASES):return False
    words=tokens(name)
    return 2<=len(words)<=6 and not any(word.isdigit() for word in words) and not any(char in str(name) for char in ("?", "!", "@"))
def search_queries(name,category,license_number=""):
    terms=CATEGORY_CONFIG.get(category,{}).get("terms",[category]); profession=terms[0] if terms else category
    search_name=" ".join(tokens(name)); quoted=f'"{search_name}"'
    queries=[f'{quoted} {profession} מייל',f'{quoted} email']
    return queries[:2]
def usable_identity_seed(seed_source):
    if not seed_source.startswith("http") or blocked_url(seed_source):return False
    path=urlparse(seed_source).path.lower()
    return not (host(seed_source).endswith("data.gov.il") and ("dataset" in path or "datastore" in path))
def _search_once(query,max_results):
    global SEARCH_CALLS,SEARCH_CIRCUIT_OPEN
    with SEARCH_LOCK:
        if SEARCH_CIRCUIT_OPEN or SEARCH_CALLS>=SEARCH_CALL_LIMIT:return [],"limit"
        SEARCH_CALLS+=1
    serpapi_key=os.getenv("SERPAPI_KEY","").strip()
    if serpapi_key:
        response=http_session().get("https://serpapi.com/search.json",params={"engine":"google","q":query,"gl":"il","hl":"he","num":max_results,"api_key":serpapi_key},timeout=(5,20))
        response.raise_for_status()
        return [{"href":x.get("link",""),"title":x.get("title",""),"body":x.get("snippet","")} for x in response.json().get("organic_results",[])],"serpapi"
    return DDGS(timeout=8).text(query,region="il-he",safesearch="moderate",max_results=max_results,backend=SEARCH_BACKENDS) or [],"ddgs"
def search_web(name,category,license_number="",max_results=10,state=None):
    global SEARCH_CONSECUTIVE_FAILURES,SEARCH_CIRCUIT_OPEN
    state=state if state is not None else {}; state.update({"queries":0,"errors":0,"results":0,"provider":"","circuit_open":False})
    if SEARCH_CIRCUIT_OPEN or SEARCH_CALLS>=SEARCH_CALL_LIMIT:
        state["circuit_open"]=True; return
    seen=set()
    for query in search_queries(name,category,license_number):
        if SEARCH_CIRCUIT_OPEN or SEARCH_CALLS>=SEARCH_CALL_LIMIT:
            state["circuit_open"]=True; break
        state["queries"]+=1
        try:
            results,provider=_search_once(query,max_results); state["provider"]=provider
            if provider=="limit":state["circuit_open"]=True; break
            with SEARCH_LOCK:SEARCH_CONSECUTIVE_FAILURES=0
        except Exception as exc:
            message=str(exc)
            if "No results found" in message:
                state["provider"]="ddgs"
                with SEARCH_LOCK:SEARCH_CONSECUTIVE_FAILURES=0
                continue
            state["errors"]+=1
            with SEARCH_LOCK:
                SEARCH_CONSECUTIVE_FAILURES+=1
                if SEARCH_CONSECUTIVE_FAILURES>=SEARCH_CIRCUIT_FAILURES:SEARCH_CIRCUIT_OPEN=True
            print("SEARCH_WARNING",type(exc).__name__,str(exc)[:160],flush=True)
            if SEARCH_CIRCUIT_OPEN:state["circuit_open"]=True; break
            continue
        for result in results:
            url=result.get("href") or result.get("url") or ""; title=result.get("title",""); snippet=result.get("body","")
            if url in seen or blocked_url(url) or not name_match(name,title+" "+snippet):continue
            seen.add(url); state["results"]+=1; yield {"url":url,"title":title,"snippet":snippet,"query":query,"seed":False}
        if state["results"]:break
@lru_cache(maxsize=1024)
def fetch(url):
    if blocked_url(url): return url,""
    try:
        r=http_session().get(url,timeout=(4,10),allow_redirects=True)
        if r.status_code==200 and "text/html" in r.headers.get("content-type","text/html") and not blocked_url(r.url): return r.url,r.text
    except requests.RequestException: pass
    return url,""
def nearest_context(node,needle="",limit=700):
    candidates=[]
    current=node
    for _ in range(7):
        current=getattr(current,"parent",None)
        if current is None:break
        value=re.sub(r"\s+"," ",current.get_text(" ",strip=True)).strip()
        if needle and needle.lower() not in value.lower():continue
        if 8<=len(value)<=limit:candidates.append(value)
    if candidates:return min(candidates,key=len)
    value=re.sub(r"\s+"," ",node.parent.get_text(" ",strip=True) if getattr(node,"parent",None) else "")
    return value[:limit]
def identity_profile_links(url,html,name):
    soup=BeautifulSoup(html,"html.parser"); result=[]
    for anchor in soup.find_all("a",href=True):
        href=urljoin(url,anchor["href"]); path=urlparse(href).path.lower()
        if not related_domains(host(href),host(url)) or not any(hint in path for hint in PROFILE_PATH_HINTS):continue
        evidence=anchor.get_text(" ",strip=True)+" "+nearest_context(anchor,limit=500)
        if name_match(name,evidence) and href not in result:result.append(href)
    return result[:2]
def extract(url,html):
    soup=BeautifulSoup(html,"html.parser")
    found=[]
    for node in soup.select("[data-cfemail]"):
        encoded=node.get("data-cfemail","")
        try:
            key=int(encoded[:2],16); email="".join(chr(int(encoded[i:i+2],16)^key) for i in range(2,len(encoded),2)); email=norm_email(email)
            if valid_email(email):found.append((email,nearest_context(node,email),"cloudflare"))
        except (ValueError,TypeError):pass
    for node in soup.select("[data-email], [data-mail], [data-user]"):
        for attribute in ("data-email","data-mail"):
            email=norm_email(node.get(attribute,""))
            if valid_email(email):found.append((email,nearest_context(node,email),"data_attribute"))
        user=node.get("data-user",""); domain=node.get("data-domain","")
        email=norm_email(f"{user}@{domain}") if user and domain else ""
        if valid_email(email):found.append((email,nearest_context(node,email),"split_data_attribute"))
    raw_text=soup.get_text(" ",strip=True)
    for local,domain,tld in OBFUSCATED_EMAIL_RE.findall(raw_text):
        email=norm_email(f"{local}@{domain}.{tld}")
        if valid_email(email):
            pos=raw_text.lower().find(local.lower()); found.append((email,raw_text[max(0,pos-220):pos+220],"obfuscated_text"))
    for node in soup(["script","style","noscript","svg"]): node.decompose()
    text=soup.get_text(" ",strip=True)
    for anchor in soup.select('a[href^="mailto:"]'):
        email=norm_email(anchor.get("href","")[7:].split("?")[0]); context=nearest_context(anchor,email)
        if valid_email(email): found.append((email,context,"mailto"))
    for email in {norm_email(x) for x in EMAIL_RE.findall(text)}:
        if valid_email(email):
            pos=text.lower().find(email.lower()); found.append((email,text[max(0,pos-220):pos+220] if pos>=0 else "","text"))
    links=[]; official_links=[]
    for anchor in soup.find_all("a",href=True):
        href=urljoin(url,anchor["href"]); label=(anchor.get_text(" ",strip=True)+" "+anchor["href"]).lower()
        if registeredish(host(href))==registeredish(host(url)) and any(w in label for w in CONTACT_WORDS):links.append(href)
        elif href.startswith("http") and registeredish(host(href))!=registeredish(host(url)) and not blocked_url(href):
            anchor_text=norm(anchor.get_text(" ",strip=True))
            if any(norm(w) in anchor_text for w in OFFICIAL_LINK_WORDS) and len(anchor_text)<=80:official_links.append(href)
    title=soup.title.get_text(" ",strip=True) if soup.title else ""; return list(dict.fromkeys(found)),list(dict.fromkeys(links))[:6],text[:60000],title,list(dict.fromkeys(official_links))[:2]
def candidate_score(email,url,page_text,title,context,name,category,verified_site,identity_text="",identity_url=""):
    if not valid_email(email) or host(url) in THIRD_PARTY_LEAD_DOMAINS or directory_site(url):return None
    if any(x in urlparse(url).path.lower() for x in GENERAL_CONTENT_PATHS):return None
    kind=CATEGORY_CONFIG.get(category,{"kind":"person"}).get("kind","person")
    local,email_domain=email.rsplit("@",1)
    title_identity=name_match(name,title)
    intro_identity=name_match(name,page_text[:2500])
    inherited_identity=name_match(name,identity_text[:2500])
    direct_context=name_match(name,context)
    profession=category_match(category,title+" "+page_text[:5000]) or category_match(category,identity_text[:5000])
    context_profession=category_match(category,context)
    same_domain=related_domains(email_domain,host(url))
    identity_domain_match=bool(identity_url) and related_domains(email_domain,host(identity_url))
    related_site=bool(identity_url) and related_domains(host(url),host(identity_url))
    linked_identity=bool(identity_url and url!=identity_url and inherited_identity and related_site)
    free_mail=email_domain in FREE_MAIL
    page_email_count=len({norm_email(x) for x in EMAIL_RE.findall(page_text) if valid_email(norm_email(x))})
    if not profession or not (verified_site or linked_identity):return None
    if kind=="person":
        if forbidden_person_role(email):return None
        if free_mail:
            if not (direct_context or (title_identity and page_email_count<=2)):return None
            return 100 if direct_context else 92
        # A footer/support address from another company is not the person's address,
        # even when the doctor's name appears elsewhere on the same long page.
        if not (same_domain or identity_domain_match):
            if not (local_name_match(email,name) and direct_context):return None
        if large_institution(url):
            if role_address(email):
                if not ((direct_context and context_profession) or (url==identity_url and title_identity and context_profession and same_domain)):return None
                return 82
            if not (direct_context or title_identity or (linked_identity and context_profession)):return None
            return 98 if direct_context else 90
        if role_address(email):
            if not ((direct_context and (context_profession or title_identity)) or (linked_identity and page_email_count<=3)):return None
            return 88 if direct_context else 80
        if not (direct_context or title_identity or local_name_match(email,name) or (linked_identity and page_email_count<=3)):return None
        return 98 if direct_context else 90
    if not (same_domain or direct_context):return None
    if local in GENERIC_LOCAL and not (context_profession or direct_context or title_identity):return None
    return 95 if direct_context else 88
def classify(email,category):
    if CATEGORY_CONFIG.get(category,{}).get("kind") in {"community","creator"}:return "BUSINESS_OR_COMMUNITY"
    return "CLINIC_OR_ORGANIZATION" if role_address(email) else "PERSONAL_PROFESSIONAL"
def ranked_candidates(candidates):
    best={}
    for candidate in candidates:
        email=candidate[1]
        if email not in best or candidate[0]>best[email][0]:best[email]=candidate
    return sorted(best.values(),key=lambda item:(-item[0],item[1]))
def serialized_candidate(candidate):
    score,email,source,evidence,query,method,identity_url=candidate
    return {"email":email,"confidence":score,"source_url":source,"identity_url":identity_url,"evidence":evidence,"matched_query":query,"extraction_method":method}
def row_candidates(record):
    result=[]
    email=norm_email(str(record.get("email", "")))
    if email and valid_email(email):
        result.append({"email":email,"confidence":int(record.get("confidence",0) or 0),"source_url":record.get("source_url",""),"identity_url":record.get("identity_url",record.get("source_url","")),"evidence":record.get("evidence",""),"matched_query":record.get("matched_query",""),"extraction_method":record.get("extraction_method","")})
    try:alternates=json.loads(record.get("alternate_emails", "[]") or "[]")
    except (TypeError,json.JSONDecodeError):alternates=[]
    for candidate in alternates:
        email=norm_email(str(candidate.get("email", "")))
        if valid_email(email) and all(email!=x["email"] for x in result):result.append(dict(candidate)|{"email":email})
    return result
def expand_verified_contacts(frame):
    rows=[]
    for record in frame[frame.status=="VERIFIED"].to_dict("records"):
        for position,candidate in enumerate(row_candidates(record)):
            item=dict(record); item.update(candidate); item["email_type"]=classify(candidate["email"],record.get("category","")); item["candidate_rank"]=position+1; rows.append(item)
    return pd.DataFrame(rows)
def annotate_shared_contacts(expanded):
    result=expanded.copy()
    if not result.empty:
        result["shared_target_count"]=result.groupby("email").email.transform("size")
        result["shared_contact"]=result.shared_target_count>1
        result["send_eligible"]=[stored_candidate_still_safe(row) for row in result.to_dict("records")]
        result["personalization_safe"]=[
            bool(row.get("send_eligible")) and row.get("email_type")=="PERSONAL_PROFESSIONAL"
            and int(row.get("shared_target_count",1) or 1)==1
            and (local_name_match(str(row.get("email","")),str(row.get("name",""))) or name_match(str(row.get("name","")),str(row.get("evidence",""))))
            for row in result.to_dict("records")
        ]
        result["outreach_scope"]=[
            "PERSON" if row.get("personalization_safe") else "ORGANIZATION_OR_SHARED_ROUTE"
            for row in result.to_dict("records")
        ]
    return result
def research(row):
    name=str(row.get("name","")).strip(); category=str(row.get("category","")).strip(); seed_source=str(row.get("seed_source","")).strip(); license_number=str(row.get("license_number","")).strip(); config=CATEGORY_CONFIG.get(category,{"priority":"","kind":"person"}); attempts=[]; candidates=[]; search_state={"queries":0,"errors":0,"results":0,"provider":"","circuit_open":False,"pages_fetched":0,"fetch_failures":0}; base={"algo_version":ALGO_VERSION,"name":name,"category":category,"priority":config.get("priority",""),"target_kind":config.get("kind",""),"seed_source":seed_source,"license_number":license_number,"seed_type":row.get("seed_type","")}
    if norm(name) in {norm(x) for x in INVALID_TARGET_NAMES} or (config.get("kind")=="person" and not valid_person_target_name(name)):
        return base|{"email":"","email_type":"","confidence":0,"source_url":"","status":"REVIEW_INVALID_TARGET_NAME","evidence":"","matched_query":"","extraction_method":"","alternate_emails":"[]","candidate_count":0,"attempted_urls":"[]","last_attempt_at":datetime.now(timezone.utc).isoformat()}
    def inspect_hit(hit):
        if hit["url"] in attempts:return
        url,html=fetch(hit["url"]); attempts.append(url)
        if not html:search_state["fetch_failures"]+=1; return
        search_state["pages_fetched"]+=1
        items,links,page_text,title,official_links=extract(url,html); verified_site=allowed_identity_page(url,title,page_text,name,category)
        if not hit.get("seed") and verified_site:verified_site=allowed_search_identity_page(url,title,page_text,name,category)
        if not verified_site:
            for profile in identity_profile_links(url,html,name):inspect_hit({"url":profile,"query":hit["query"],"seed":False})
            return
        if not directory_site(url):
            for email,context,method in items:
                score=candidate_score(email,url,page_text,title,context,name,category,verified_site,page_text,url)
                if score is not None:candidates.append((score,email,url,context[:500],hit["query"],"direct_"+method,url))
        queue=[]
        if not directory_site(url) and not large_institution(url):
            safe_links=links
            if config.get("kind")=="person":safe_links=[link for link in links if not any(word in urlparse(link).path.lower() for word in ("team","staff","doctors","צוות"))]
            queue=safe_links[:4]
        for external in official_links:
            u3,h3=fetch(external); attempts.append(u3)
            if not h3:continue
            items3,links3,t3,title3,_=extract(u3,h3)
            if not allowed_identity_page(u3,title3,t3,name,category):continue
            for email,context,method in items3:
                score=candidate_score(email,u3,t3,title3,context,name,category,True,page_text,url)
                if score is not None:candidates.append((score,email,u3,context[:500],hit["query"],"official_"+method,u3))
            if not large_institution(u3):queue.extend(links3[:3])
        crawled=set()
        while queue and len(crawled)<5:
            link=queue.pop(0)
            if link in crawled:continue
            crawled.add(link); url2,html2=fetch(link); attempts.append(url2)
            if not html2:continue
            items2,links2,text2,title2,_=extract(url2,html2)
            for email,context,method in items2:
                score=candidate_score(email,url2,text2,title2,context,name,category,True,page_text,url)
                if score is not None:candidates.append((score,email,url2,context[:500],hit["query"],"linked_"+method,url))
    if usable_identity_seed(seed_source):inspect_hit({"url":seed_source,"query":"seed_source","seed":True})
    if not candidates:
        for hit in search_web(name,category,license_number,state=search_state):
            inspect_hit(hit)
            if ranked_candidates(candidates) and ranked_candidates(candidates)[0][0]>=90:break
    candidates=ranked_candidates(candidates)
    if candidates:
        score,email,source,evidence,query,method,identity_url=candidates[0]; alternates=[serialized_candidate(x) for x in candidates[1:3]]; return base|{"email":email,"email_type":classify(email,category),"confidence":score,"source_url":source,"identity_url":identity_url,"status":"VERIFIED","evidence":evidence,"matched_query":query,"extraction_method":method,"alternate_emails":json.dumps(alternates,ensure_ascii=False),"candidate_count":len(candidates),"search_queries":search_state.get("queries",0),"search_errors":search_state.get("errors",0),"search_results":search_state.get("results",0),"pages_fetched":search_state.get("pages_fetched",0),"fetch_failures":search_state.get("fetch_failures",0),"search_provider":search_state.get("provider",""),"attempted_urls":json.dumps(list(dict.fromkeys(attempts)),ensure_ascii=False),"last_attempt_at":datetime.now(timezone.utc).isoformat()}
    pending=search_state.get("circuit_open") or (search_state.get("results",0)==0 and search_state.get("errors",0)>0) or (search_state.get("results",0)>0 and search_state.get("pages_fetched",0)==0)
    retry_count=int(row.get("retry_count",0) or 0)+(1 if pending else 0)
    next_retry=(datetime.now(timezone.utc)+timedelta(hours=min(72,6*(2**min(retry_count,3))))).isoformat() if pending else ""
    status="PENDING_SEARCH_PROVIDER" if pending else "NO_VERIFIED_PUBLIC_EMAIL"
    return base|{"email":"","email_type":"","confidence":0,"source_url":"","status":status,"evidence":"","matched_query":"","extraction_method":"","alternate_emails":"[]","candidate_count":0,"retry_count":retry_count,"next_retry_at":next_retry,"last_attempt_at":datetime.now(timezone.utc).isoformat(),"search_queries":search_state.get("queries",0),"search_errors":search_state.get("errors",0),"search_results":search_state.get("results",0),"pages_fetched":search_state.get("pages_fetched",0),"fetch_failures":search_state.get("fetch_failures",0),"search_provider":search_state.get("provider",""),"attempted_urls":json.dumps(list(dict.fromkeys(attempts)),ensure_ascii=False)}

def stored_candidate_still_safe(record):
    if str(record.get("status",""))!="VERIFIED":return False
    name=str(record.get("name","")); category=str(record.get("category","")); email=norm_email(str(record.get("email","")))
    source=str(record.get("source_url","")); identity=str(record.get("identity_url",source)); evidence=str(record.get("evidence",""))
    kind=CATEGORY_CONFIG.get(category,{}).get("kind","person")
    if not valid_email(email) or directory_site(source):return False
    if kind=="person":
        if not valid_person_target_name(name) or forbidden_person_role(email):return False
        domain=email.rsplit("@",1)[1]
        if domain not in FREE_MAIL and not (related_domains(domain,host(source)) or related_domains(domain,host(identity)) or local_name_match(email,name)):return False
        if large_institution(source) and role_address(email) and not (name_match(name,evidence) and category_match(category,evidence)):return False
    return True

def migrate_checkpoint_row(record):
    result=dict(record)
    if int(result.get("algo_version",0) or 0)==ALGO_VERSION:return result
    if int(result.get("algo_version",0) or 0)!=7:return None
    old_status=str(result.get("status",""))
    result["algo_version"]=ALGO_VERSION
    if old_status=="VERIFIED" and stored_candidate_still_safe(record):return result
    if old_status.startswith("REVIEW_INVALID_TARGET_NAME"):return result
    result["previous_status"]=old_status
    if old_status=="VERIFIED":
        result["previous_candidate"]=json.dumps({key:record.get(key,"") for key in ("email","confidence","source_url","identity_url","evidence","matched_query","extraction_method")},ensure_ascii=False)
    result.update({"status":"PENDING_ALGO_UPGRADE","next_retry_at":"","retry_count":0})
    return result

def round_robin_rows(rows):
    buckets={}
    for row in rows:buckets.setdefault(str(row.get("category","")),[]).append(row)
    categories=sorted(buckets,key=lambda c:(CATEGORY_CONFIG.get(c,{}).get("priority","Z"),c))
    result=[]
    while categories:
        remaining=[]
        for category in categories:
            if buckets[category]:result.append(buckets[category].pop(0))
            if buckets[category]:remaining.append(category)
        categories=remaining
    return result

def build_research_queue(rows,stored,now,max_targets):
    direct,fresh,due,deferred=[],[],[],[]
    for row in rows:
        key=(str(row.get("name","")).strip(),str(row.get("category","")).strip()); previous=stored.get(key)
        if previous and not str(previous.get("status","")).startswith("PENDING_"):continue
        if not previous:
            (direct if usable_identity_seed(str(row.get("seed_source","")).strip()) else fresh).append(row); continue
        candidate=dict(row)|{"retry_count":previous.get("retry_count",0),"previous_search_queries":previous.get("search_queries",0),"last_attempt_at":previous.get("last_attempt_at","")}
        # Rows never searched because the old circuit was open are genuinely untouched.
        if int(previous.get("search_queries",0) or 0)==0:
            due.append(candidate); continue
        try:retry_at=datetime.fromisoformat(str(previous.get("next_retry_at","")).replace("Z","+00:00"))
        except (ValueError,TypeError):retry_at=now
        (due if retry_at<=now else deferred).append(candidate if retry_at<=now else (retry_at,candidate))
    due.sort(key=lambda row:(int(row.get("retry_count",0) or 0),str(row.get("last_attempt_at",""))))
    fresh_queue=round_robin_rows(direct)+round_robin_rows(fresh)
    due_queue=round_robin_rows(due)
    queue=(fresh_queue+due_queue)[:max_targets]
    if not queue and deferred:
        deferred.sort(key=lambda item:item[0]); queue=[row for _,row in deferred[:min(250,max_targets)]]
    return queue
def load_input(path):
    source=Path(path); frame=pd.read_excel(source) if source.suffix.lower()==".xlsx" else pd.read_csv(source); return frame.fillna("").to_dict("records")
def retain_active_checkpoint(stored,rows,out):
    active={(str(row.get("name","")).strip(),str(row.get("category","")).strip()) for row in rows}
    retired={key:value for key,value in stored.items() if key not in active}
    if retired:
        archive=out/"retired_targets.jsonl"; archived={}
        if archive.exists():
            for line in archive.read_text(encoding="utf-8",errors="ignore").splitlines():
                try:item=json.loads(line); archived[(item.get("name",""),item.get("category",""))]=item
                except Exception:pass
        for key,value in retired.items():archived[key]=dict(value)|{"retired_at":datetime.now(timezone.utc).isoformat()}
        archive.write_text("".join(json.dumps(row,ensure_ascii=False)+"\n" for row in archived.values()),encoding="utf-8")
    return {key:value for key,value in stored.items() if key in active}
def excel_safe_frame(frame):
    safe=frame.copy()
    for col in safe.columns:
        safe[col]=safe[col].map(lambda v: ILLEGAL_CHARACTERS_RE.sub("",v)[:32767] if isinstance(v,str) else v)
    return safe
def main():
    parser=argparse.ArgumentParser(); parser.add_argument("input"); parser.add_argument("--out",default="output"); parser.add_argument("--resume",action="store_true"); parser.add_argument("--export-only",action="store_true"); parser.add_argument("--max-targets",type=int,default=int(os.getenv("MAX_TARGETS_PER_RUN","10000"))); args=parser.parse_args(); out=Path(args.out); out.mkdir(parents=True,exist_ok=True); checkpoint=out/"checkpoint.jsonl"; stored={}
    if args.resume and checkpoint.exists():
        for line in checkpoint.read_text(encoding="utf-8",errors="ignore").splitlines():
            try: result=migrate_checkpoint_row(json.loads(line))
            except Exception: continue
            if result and result.get("algo_version")==ALGO_VERSION: stored[(result.get("name",""),result.get("category",""))]=result
    rows=load_input(args.input); stored=retain_active_checkpoint(stored,rows,out); checkpoint.write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in stored.values()),encoding="utf-8")
    if not args.export_only:
        with checkpoint.open("a",encoding="utf-8") as stream:
            queue=build_research_queue(rows,stored,datetime.now(timezone.utc),args.max_targets)
            print(f"Research queue={len(queue)} workers={RESEARCH_WORKERS} search_limit={SEARCH_CALL_LIMIT} backends={SEARCH_BACKENDS}",flush=True)
            row_iter=iter(enumerate(queue,1)); in_flight={}
            with concurrent.futures.ThreadPoolExecutor(max_workers=RESEARCH_WORKERS) as pool:
                def submit_next():
                    if SEARCH_CIRCUIT_OPEN or SEARCH_CALLS>=SEARCH_CALL_LIMIT:return False
                    try:index,row=next(row_iter)
                    except StopIteration:return False
                    key=(str(row.get("name","")).strip(),str(row.get("category","")).strip())
                    print(f"[{index}/{len(queue)}] {key[0]} | {key[1]}",flush=True)
                    in_flight[pool.submit(research,row)]=(key,index); return True
                for _ in range(RESEARCH_WORKERS):
                    if not submit_next():break
                while in_flight:
                    done,_=concurrent.futures.wait(in_flight,return_when=concurrent.futures.FIRST_COMPLETED)
                    for future in done:
                        key,index=in_flight.pop(future)
                        try:result=future.result()
                        except Exception as exc:
                            print(f"TARGET_WARNING {key[0]} {type(exc).__name__}: {str(exc)[:160]}",flush=True)
                            continue
                        stored[key]=result; stream.write(json.dumps(result,ensure_ascii=False)+"\n"); stream.flush()
                        submit_next()
            if SEARCH_CIRCUIT_OPEN or SEARCH_CALLS>=SEARCH_CALL_LIMIT:
                print(f"Stopping shift safely after {len(queue)-len(list(row_iter))} scheduled targets and {SEARCH_CALLS} search calls",flush=True)
    frame=pd.DataFrame(list(stored.values()))
    if frame.empty:return
    frame=frame.sort_values(["priority","status","confidence"],ascending=[True,True,False]).drop_duplicates(subset=["name","category"],keep="first"); expanded=annotate_shared_contacts(expand_verified_contacts(frame))
    frame.to_csv(out/"audit.csv",index=False,encoding="utf-8-sig"); excel_safe_frame(frame).to_excel(out/"audit.xlsx",index=False)
    found=expanded[expanded.send_eligible].sort_values(["priority","confidence"],ascending=[True,False]).drop_duplicates(subset=["email"],keep="first") if not expanded.empty else pd.DataFrame(columns=list(frame.columns)+["candidate_rank"]); found.to_csv(out/"contacts.csv",index=False,encoding="utf-8-sig"); excel_safe_frame(found).to_excel(out/"contacts.xlsx",index=False); excel_safe_frame(frame[frame.status.str.startswith("REVIEW")]).to_excel(out/"review.xlsx",index=False)
    summary={"algo_version":ALGO_VERSION,"touched_targets":len(frame),"resolved_targets":int((~frame.status.str.startswith("PENDING")).sum()),"verified":int((frame.status=="VERIFIED").sum()),"not_verified":int((frame.status=="NO_VERIFIED_PUBLIC_EMAIL").sum()),"pending":int(frame.status.str.startswith("PENDING").sum()),"review":int(frame.status.str.startswith("REVIEW").sum()),"unique_emails":int(found.email.nunique()),"personalization_safe_emails":int(found.personalization_safe.sum()) if not found.empty else 0,"search_calls":SEARCH_CALLS,"search_circuit_open":SEARCH_CIRCUIT_OPEN,"by_category":frame.groupby("category").status.value_counts().unstack(fill_value=0).to_dict("index")}; (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
