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
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

ALGO_VERSION = 5
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
GENERIC_LOCAL = {"info", "office", "clinic", "contact", "mail", "reception", "admin", "secretary", "nashim", "service", "hello", "igudyhanaka", "customerservice", "visitors"}
FREE_MAIL = {"gmail.com", "walla.co.il", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "bezeqint.net", "012.net.il", "netvision.net.il"}
BLOCKED_DOMAINS = {"google.com", "youtube.com", "wikipedia.org", "wiktionary.org", "linkedin.com", "rocketreach.co", "zoominfo.com", "prospeo.io", "hunter.io", "apollo.io", "stockanalysis.com", "yahoo.com", "investing.com", "pinterest.com", "mako.co.il", "ynet.co.il", "maariv.co.il", "haaretz.co.il", "israelhayom.co.il", "ice.co.il", "globes.co.il", "themarker.com", "jusbrasil.com.br", "ubereats.com", "ilovepdf.com", "smallpdf.com", "drugs.com", "amazon.com", "reddit.com"}
TRUSTED_REGISTRIES = {"ima.org.il", "practitioners.health.gov.il", "gov.il", "doctors.co.il", "infomed.co.il", "medreviews.co.il", "doctorita.co.il", "docadvisor.co.il", "maccabi4u.co.il", "clalit.co.il", "meuhedet.co.il", "leumit.co.il", "sheba.co.il", "tasmc.org.il", "hadassah.org.il", "rambam.org.il", "assuta.co.il", "hospitals.clalit.co.il", "ialp.org.il", "midwives.org.il"}
GENERAL_CONTENT_PATHS = ("/article", "/articles", "/blog", "/news", "/magazine", "/forum", "/forums", "/podcast", "/כתבות", "/מאמר", "/חדשות", "/פורום")
DIRECTORY_DOMAINS = ("doctors.co.il", "infomed.co.il", "medreviews.co.il", "doctorita.co.il", "docadvisor.co.il", "ima.org.il")
CONTACT_WORDS = ("contact", "about", "team", "staff", "doctor", "clinic", "profile", "email", "directory", "צור-קשר", "צור קשר", "אודות", "צוות", "רופאים", "מרפאה", "דוא״ל", "דואר אלקטרוני")
OFFICIAL_LINK_WORDS = ("website", "official site", "personal site", "clinic site", "אתר", "אתר אישי", "אתר המרפאה")
LARGE_INSTITUTION_DOMAINS = {
    "tasmc.org.il", "sheba.co.il", "hadassah.org.il", "rambam.org.il", "szmc.org.il",
    "clalit.co.il", "maccabi4u.co.il", "meuhedet.co.il", "leumit.co.il", "gov.il",
}
ORGANIZATION_DOMAIN_GROUPS = (
    {"tasmc.org.il", "tlvmc.gov.il"},
    {"maccabi4u.co.il", "mac.org.il"},
    {"clalit.co.il", "hospitals.clalit.co.il"},
)
INVALID_TARGET_NAMES = {"ראשי", "אודות", "הצוות שלנו", "מי אני", "צור קשר", "נשים", "דף הבית"}
CATEGORY_CONFIG = {
    "gynecologist": {"priority": "A", "terms": ["יילוד", "גינקולוג", "רופא נשים", "מיילדות", "obstetric", "gynecolog"], "kind": "person"},
    "family_doctor": {"priority": "B", "terms": ["רפואת משפחה", "רופא משפחה", "רופאת משפחה", "family medicine", "family physician"], "kind": "person"},
    "clinic_manager": {"priority": "B", "terms": ["מנהל מרפאה", "מנהלת מרפאה", "ניהול מרפאה", "medical director"], "kind": "person"},
    "womens_health_center": {"priority": "A", "terms": ["מרכז בריאות האישה", "מרפאת נשים", "בריאות האישה", "women health"], "kind": "org"},
    "community_clinic": {"priority": "B", "terms": ["מרפאה קהילתית", "מרפאת משפחה", "מרכז רפואי", "רפואה ראשונית"], "kind": "org"},
    "fertility_doctor": {"priority": "A", "terms": ["פוריות", "פריון", "ivf", "שימור פוריות"], "kind": "person"}, "ivf_unit": {"priority": "A", "terms": ["ivf", "הפריה חוץ גופית", "יחידת פוריות"], "kind": "org"}, "fertility_center": {"priority": "A", "terms": ["מרכז פוריות", "מרפאת פוריות", "פריון"], "kind": "org"}, "embryologist": {"priority": "A", "terms": ["אמבריולוג", "embryologist", "ivf"], "kind": "person"}, "fertility_nurse": {"priority": "A", "terms": ["אחות פוריות", "אחות פריון", "ivf"], "kind": "person"}, "fertility_consultant": {"priority": "A", "terms": ["יועצת פוריות", "יועץ פוריות", "פריון"], "kind": "person"}, "sperm_bank": {"priority": "A", "terms": ["בנק זרע", "תרומת זרע"], "kind": "org"}, "fertility_preservation": {"priority": "A", "terms": ["שימור פוריות"], "kind": "org"}, "fertility_association": {"priority": "A", "terms": ["עמותת פוריות", "ארגון פוריות", "פריון"], "kind": "org"}, "doula": {"priority": "A", "terms": ["דולה", "doula", "תומכת לידה"], "kind": "person"}, "midwife": {"priority": "A", "terms": ["מיילדת", "midwife"], "kind": "person"}, "childbirth_educator": {"priority": "A", "terms": ["הכנה ללידה", "מדריכת לידה"], "kind": "person"}, "birth_center": {"priority": "A", "terms": ["מרכז לידה", "חדר לידה", "יולדות"], "kind": "org"}, "lactation": {"priority": "B", "terms": ["יועצת הנקה", "ibclc", "הנקה"], "kind": "person"}, "pelvic_floor": {"priority": "B", "terms": ["רצפת אגן", "פיזיותרפיה"], "kind": "person"}, "sleep_consultant": {"priority": "B", "terms": ["יועצת שינה", "ייעוץ שינה"], "kind": "person"}, "pregnancy_dietitian": {"priority": "B", "terms": ["דיאטנית", "תזונה", "הריון", "פוריות"], "kind": "person"}, "parenting_center": {"priority": "B", "terms": ["מרכז הורות", "הורים ותינוקות"], "kind": "org"}, "perinatal_mental_health": {"priority": "B", "terms": ["פסיכולוג", "טיפול רגשי", "הריון", "פוריות"], "kind": "person"}, "facebook_group_admin": {"priority": "C", "terms": ["קבוצת פייסבוק", "הריון", "פוריות"], "kind": "community"}, "community_manager": {"priority": "C", "terms": ["קהילה", "הריון", "פוריות"], "kind": "community"}, "instagram_creator": {"priority": "C", "terms": ["אינסטגרם", "הריון", "פוריות"], "kind": "creator"}, "parenting_site": {"priority": "C", "terms": ["הורות", "הריון", "לידה"], "kind": "org"}, "pregnancy_podcast": {"priority": "C", "terms": ["פודקאסט", "הריון", "פוריות"], "kind": "creator"}, "doula_school": {"priority": "C", "terms": ["בית ספר לדולות", "קורס דולות"], "kind": "org"}, "childbirth_school": {"priority": "C", "terms": ["הכנה ללידה", "קורס מדריכות"], "kind": "org"}, "women_health_creator": {"priority": "C", "terms": ["בריאות האישה", "הריון", "לידה"], "kind": "creator"}}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ProfessionalContactResearch/5.0; public-contact-research)"}
SESSION = requests.Session(); SESSION.headers.update(HEADERS)

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
    domain=host(url); return any(domain==x or domain.endswith("."+x) for x in LARGE_INSTITUTION_DOMAINS)
def name_match(name,text):
    wanted=tokens(name); hay=set(tokens(text)); needed=len(wanted) if len(wanted)<=2 else len(wanted)-1; return bool(wanted) and sum(x in hay for x in wanted)>=needed
def category_match(category,text): return any(norm(term) in norm(text) for term in CATEGORY_CONFIG.get(category,{}).get("terms",[]) if norm(term))
def allowed_identity_page(url,title,page_text,name,category):
    path=urlparse(url).path.lower()
    if any(x in path for x in GENERAL_CONTENT_PATHS): return False
    if not name_match(name,title+" "+page_text[:15000]) or not category_match(category,title+" "+page_text[:15000]): return False
    return True if trusted_registry(url) else name_match(name,title) and category_match(category,title+" "+page_text[:4000])
def norm_email(email): return email.strip(" <>[](){}.,;:\"'").lower().replace("\u00a0","")
def valid_email(email):
    if "@" not in email:return False
    local,domain=email.rsplit("@",1)
    if not local or not domain or "." not in domain:return False
    if local in BAD_LOCAL or domain in PLACEHOLDER_DOMAINS or domain in PLATFORM_DOMAINS:return False
    if local in NON_OUTREACH_LOCAL_EXACT or any(part in local for part in NON_OUTREACH_LOCAL_PARTS):return False
    if domain.endswith((".png",".jpg",".jpeg",".webp")):return False
    if "example" in local or local.startswith(("yourname","your.name","name.surname")):return False
    return True
def local_name_match(email,name):
    local=norm(email.split("@",1)[0]).replace(" ",""); latin=[x for x in tokens(name) if re.search("[a-z]",x) and len(x)>=3]; return bool(latin) and any(x in local for x in latin)
def search_queries(name,category):
    terms=CATEGORY_CONFIG.get(category,{}).get("terms",[category]); profession=" ".join(terms[:2]); queries=[f'"{name}" {profession}',f'"{name}" {profession} מייל',f'"{name}" {profession} אימייל',f'"{name}" {profession} דוא״ל',f'"{name}" {profession} צור קשר',f'"{name}" {profession} אתר רשמי',f'"{name}" מרפאה פרטית',f'"{name}" email',f'"{name}" contact']
    if category in {"gynecologist","fertility_doctor","family_doctor","clinic_manager"}:
        queries += [f'"{name}" site:{d}' for d in DIRECTORY_DOMAINS]
        queries += [f'"{name}" site:{d}' for d in ("clalit.co.il","maccabi4u.co.il","meuhedet.co.il","leumit.co.il")]
    elif CATEGORY_CONFIG.get(category,{}).get("kind")=="person": queries += [f'"{name}" site:doctorita.co.il',f'"{name}" site:doctors.co.il',f'"{name}" site:infomed.co.il']
    return list(dict.fromkeys(queries))
def search_web(name,category,seed_source="",max_results=8):
    seen=set()
    if seed_source.startswith("http") and not blocked_url(seed_source): seen.add(seed_source); yield {"url":seed_source,"title":name,"snippet":"","query":"seed_source","seed":True}
    engine=DDGS()
    for query in search_queries(name,category):
        try:
            for result in engine.text(query,region="il-he",safesearch="moderate",max_results=max_results) or []:
                url=result.get("href") or result.get("url") or ""; title=result.get("title",""); snippet=result.get("body","")
                if url in seen or blocked_url(url) or not name_match(name,title+" "+snippet) or not category_match(category,title+" "+snippet): continue
                seen.add(url); yield {"url":url,"title":title,"snippet":snippet,"query":query,"seed":False}
        except Exception as exc: print("SEARCH_WARNING",type(exc).__name__,str(exc)[:160],flush=True)
        time.sleep(.15)
@lru_cache(maxsize=1024)
def fetch(url):
    if blocked_url(url): return url,""
    try:
        r=SESSION.get(url,timeout=(5,12),allow_redirects=True)
        if r.status_code==200 and "text/html" in r.headers.get("content-type","text/html") and not blocked_url(r.url): return r.url,r.text
    except requests.RequestException: pass
    return url,""
def extract(url,html):
    soup=BeautifulSoup(html,"html.parser")
    found=[]
    for node in soup.select("[data-cfemail]"):
        encoded=node.get("data-cfemail","")
        try:
            key=int(encoded[:2],16); email="".join(chr(int(encoded[i:i+2],16)^key) for i in range(2,len(encoded),2)); email=norm_email(email)
            if valid_email(email):found.append((email,node.parent.get_text(" ",strip=True)[:1600],"cloudflare"))
        except (ValueError,TypeError):pass
    for node in soup.select("[data-email], [data-mail], [data-user]"):
        for attribute in ("data-email","data-mail"):
            email=norm_email(node.get(attribute,""))
            if valid_email(email):found.append((email,node.parent.get_text(" ",strip=True)[:1600],"data_attribute"))
        user=node.get("data-user",""); domain=node.get("data-domain","")
        email=norm_email(f"{user}@{domain}") if user and domain else ""
        if valid_email(email):found.append((email,node.parent.get_text(" ",strip=True)[:1600],"split_data_attribute"))
    raw_text=soup.get_text(" ",strip=True)
    for local,domain,tld in OBFUSCATED_EMAIL_RE.findall(raw_text):
        email=norm_email(f"{local}@{domain}.{tld}")
        if valid_email(email):
            pos=raw_text.lower().find(local.lower()); found.append((email,raw_text[max(0,pos-700):pos+700],"obfuscated_text"))
    for node in soup(["script","style","noscript","svg"]): node.decompose()
    text=soup.get_text(" ",strip=True)
    for anchor in soup.select('a[href^="mailto:"]'):
        email=norm_email(anchor.get("href","")[7:].split("?")[0]); block=anchor.find_parent(["li","p","div","section","article","td"]); context=(block.get_text(" ",strip=True) if block else anchor.parent.get_text(" ",strip=True))[:1600]
        if valid_email(email): found.append((email,context,"mailto"))
    for email in {norm_email(x) for x in EMAIL_RE.findall(text)}:
        if valid_email(email):
            pos=text.lower().find(email.lower()); found.append((email,text[max(0,pos-700):pos+700] if pos>=0 else "","text"))
    links=[]; official_links=[]
    for anchor in soup.find_all("a",href=True):
        href=urljoin(url,anchor["href"]); label=(anchor.get_text(" ",strip=True)+" "+anchor["href"]).lower()
        if registeredish(host(href))==registeredish(host(url)) and any(w in label for w in CONTACT_WORDS): links.append(href)
        elif href.startswith("http") and not blocked_url(href) and any(w in label for w in OFFICIAL_LINK_WORDS):official_links.append(href)
    title=soup.title.get_text(" ",strip=True) if soup.title else ""; return list(dict.fromkeys(found)),list(dict.fromkeys(links))[:12],text[:60000],title,list(dict.fromkeys(official_links))[:3]
def candidate_score(email,url,page_text,title,context,name,category,verified_site,identity_text="",identity_url=""):
    if not valid_email(email) or host(url) in THIRD_PARTY_LEAD_DOMAINS:return None
    kind=CATEGORY_CONFIG.get(category,{"kind":"person"}).get("kind","person"); local,email_domain=email.rsplit("@",1); page_identity=name_match(name,title+" "+page_text[:15000]); inherited_identity=name_match(name,identity_text[:15000]); near_identity=name_match(name,context); profession=category_match(category,title+" "+page_text[:20000]) or category_match(category,identity_text[:20000]); same_domain=related_domains(email_domain,host(url)); related_site=bool(identity_url) and related_domains(host(url),host(identity_url)); free_mail=email_domain in FREE_MAIL
    if not (page_identity or (inherited_identity and related_site)) or not profession:return None
    if large_institution(url) and not (near_identity or local_name_match(email,name) or category_match(category,context)):return None
    if kind=="person":
        if local in GENERIC_LOCAL and not near_identity and not (verified_site and related_site and not large_institution(url)):return None
        if local not in GENERIC_LOCAL and free_mail and not near_identity and not local_name_match(email,name):return None
        if local not in GENERIC_LOCAL and not free_mail and not same_domain and not near_identity and not local_name_match(email,name):return None
        score=55+(20 if near_identity else 0)+(10 if local_name_match(email,name) else 0)+(10 if same_domain else 0)+(10 if inherited_identity else 0)+(5 if verified_site else 0)+(5 if related_site else 0)-(10 if local in GENERIC_LOCAL else 0)
    else:
        if not (same_domain or near_identity or (related_site and not large_institution(url))):return None
        score=70+(15 if same_domain else 0)+(5 if near_identity else 0)+(5 if related_site else 0)
    if host(url).endswith(("gov.il","ac.il","org.il")):score+=5
    return min(score,100) if score>=75 else None
def classify(email,category): return "BUSINESS_OR_COMMUNITY" if CATEGORY_CONFIG.get(category,{}).get("kind") in {"community","creator"} else ("CLINIC_OR_ORGANIZATION" if email.split("@",1)[0] in GENERIC_LOCAL else "PERSONAL_PROFESSIONAL")
def ranked_candidates(candidates):
    best={}
    for candidate in candidates:
        email=candidate[1]
        if email not in best or candidate[0]>best[email][0]:best[email]=candidate
    return sorted(best.values(),key=lambda item:(-item[0],item[1]))
def serialized_candidate(candidate):
    score,email,source,evidence,query,method=candidate
    return {"email":email,"confidence":score,"source_url":source,"evidence":evidence,"matched_query":query,"extraction_method":method}
def row_candidates(record):
    result=[]
    email=norm_email(str(record.get("email", "")))
    if email and valid_email(email):
        result.append({"email":email,"confidence":int(record.get("confidence",0) or 0),"source_url":record.get("source_url",""),"evidence":record.get("evidence",""),"matched_query":record.get("matched_query",""),"extraction_method":record.get("extraction_method","")})
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
def research(row):
    name=str(row.get("name","")).strip(); category=str(row.get("category","")).strip(); seed_source=str(row.get("seed_source","")).strip(); config=CATEGORY_CONFIG.get(category,{"priority":"","kind":"person"}); attempts=[]; candidates=[]; base={"algo_version":ALGO_VERSION,"name":name,"category":category,"priority":config.get("priority",""),"target_kind":config.get("kind",""),"seed_source":seed_source}
    if norm(name) in {norm(x) for x in INVALID_TARGET_NAMES}:
        return base|{"email":"","email_type":"","confidence":0,"source_url":"","status":"REVIEW_INVALID_TARGET_NAME","evidence":"","matched_query":"","extraction_method":"","alternate_emails":"[]","candidate_count":0,"attempted_urls":"[]"}
    for hit in search_web(name,category,seed_source):
        url,html=fetch(hit["url"]); attempts.append(url)
        if not html:continue
        items,links,page_text,title,official_links=extract(url,html); verified_site=allowed_identity_page(url,title,page_text,name,category)
        if not verified_site:continue
        for email,context,method in items:
            score=candidate_score(email,url,page_text,title,context,name,category,verified_site,page_text,url)
            if score is not None:candidates.append((score,email,url,context[:500],hit["query"],method))
        queue=[(link,1) for link in links]
        for external in official_links:
            u3,h3=fetch(external); attempts.append(u3)
            if not h3:continue
            _,_,t3,title3,_=extract(u3,h3)
            if allowed_identity_page(u3,title3,t3,name,category):queue.append((u3,1))
        crawled=set()
        while queue and len(crawled)<18:
            link,depth=queue.pop(0)
            if link in crawled:continue
            crawled.add(link); url2,html2=fetch(link); attempts.append(url2)
            if not html2:continue
            items2,links2,text2,title2,_=extract(url2,html2)
            for email,context,method in items2:
                score=candidate_score(email,url2,text2,title2,context,name,category,True,page_text,url)
                if score is not None:candidates.append((score,email,url2,context[:500],hit["query"],method))
            if depth<2:
                queue.extend((next_link,depth+1) for next_link in links2 if next_link not in crawled)
        ranked=ranked_candidates(candidates)
        if len([x for x in ranked if x[0]>=85])>=3 or (ranked and ranked[0][0]>=90 and len(attempts)>=12) or len(attempts)>=30:break
    candidates=ranked_candidates(candidates)
    if candidates:
        score,email,source,evidence,query,method=candidates[0]; alternates=[serialized_candidate(x) for x in candidates[1:5]]; return base|{"email":email,"email_type":classify(email,category),"confidence":score,"source_url":source,"status":"VERIFIED","evidence":evidence,"matched_query":query,"extraction_method":method,"alternate_emails":json.dumps(alternates,ensure_ascii=False),"candidate_count":len(candidates),"attempted_urls":json.dumps(list(dict.fromkeys(attempts)),ensure_ascii=False)}
    return base|{"email":"","email_type":"","confidence":0,"source_url":"","status":"NO_VERIFIED_PUBLIC_EMAIL","evidence":"","matched_query":"","extraction_method":"","alternate_emails":"[]","candidate_count":0,"attempted_urls":json.dumps(list(dict.fromkeys(attempts)),ensure_ascii=False)}
def load_input(path):
    source=Path(path); frame=pd.read_excel(source) if source.suffix.lower()==".xlsx" else pd.read_csv(source); return frame.fillna("").to_dict("records")
def excel_safe_frame(frame):
    safe=frame.copy()
    for col in safe.columns:
        safe[col]=safe[col].map(lambda v: ILLEGAL_CHARACTERS_RE.sub("",v)[:32767] if isinstance(v,str) else v)
    return safe
def main():
    parser=argparse.ArgumentParser(); parser.add_argument("input"); parser.add_argument("--out",default="output"); parser.add_argument("--resume",action="store_true"); parser.add_argument("--export-only",action="store_true"); args=parser.parse_args(); out=Path(args.out); out.mkdir(parents=True,exist_ok=True); checkpoint=out/"checkpoint.jsonl"; done={}
    if args.resume and checkpoint.exists():
        for line in checkpoint.read_text(encoding="utf-8",errors="ignore").splitlines():
            try: result=json.loads(line)
            except Exception: continue
            if result.get("algo_version")==ALGO_VERSION: done[(result.get("name",""),result.get("category",""))]=result
    rows=load_input(args.input); checkpoint.write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in done.values()),encoding="utf-8")
    if not args.export_only:
        with checkpoint.open("a",encoding="utf-8") as stream:
            for index,row in enumerate(rows,1):
                key=(str(row.get("name","")).strip(),str(row.get("category","")).strip())
                if key in done:continue
                print(f"[{index}/{len(rows)}] {key[0]} | {key[1]}",flush=True); result=research(row); done[key]=result; stream.write(json.dumps(result,ensure_ascii=False)+"\n"); stream.flush()
    frame=pd.DataFrame(list(done.values()))
    if frame.empty:return
    frame=frame.sort_values(["priority","status","confidence"],ascending=[True,True,False]).drop_duplicates(subset=["name","category"],keep="first"); expanded=expand_verified_contacts(frame); repeated=set()
    if not expanded.empty:
        person=expanded[expanded.target_kind=="person"]; repeated={email for email,count in Counter(person.email).items() if count>2}
    if repeated:
        mask=(frame.target_kind=="person")&frame.email.isin(repeated); frame.loc[mask,"status"]="REVIEW_SHARED_EMAIL"; frame.loc[mask,"confidence"]=0
    frame.to_csv(out/"audit.csv",index=False,encoding="utf-8-sig"); excel_safe_frame(frame).to_excel(out/"audit.xlsx",index=False)
    found=expanded[~expanded.email.isin(repeated)].copy().sort_values(["priority","confidence"],ascending=[True,False]).drop_duplicates(subset=["email"],keep="first") if not expanded.empty else pd.DataFrame(columns=list(frame.columns)+["candidate_rank"]); found.to_csv(out/"contacts.csv",index=False,encoding="utf-8-sig"); excel_safe_frame(found).to_excel(out/"contacts.xlsx",index=False); excel_safe_frame(frame[frame.status.str.startswith("REVIEW")]).to_excel(out/"review.xlsx",index=False)
    summary={"algo_version":ALGO_VERSION,"total_targets":len(frame),"verified":int((frame.status=="VERIFIED").sum()),"not_verified":int((frame.status=="NO_VERIFIED_PUBLIC_EMAIL").sum()),"review":int(frame.status.str.startswith("REVIEW").sum()),"unique_emails":int(found.email.nunique()),"by_category":frame.groupby("category").status.value_counts().unstack(fill_value=0).to_dict("index")}; (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
