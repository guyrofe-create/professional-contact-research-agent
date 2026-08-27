from __future__ import annotations
import argparse, json, re, time
from pathlib import Path
from urllib.parse import urljoin, urlparse
import pandas as pd
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

EMAIL_RE=re.compile(r'(?i)(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.-])')
BAD_LOCAL={'example','test','noreply','no-reply','webmaster','privacy','abuse'}
CONTACT_WORDS=('contact','about','team','staff','doctor','clinic','faculty','profile','צור-קשר','אודות','צוות','רופאים','מרפאה','הנהלה','admin','management')

CATEGORY_CONFIG={
 'gynecologist': {'priority':'A','terms':['יילוד וגינקולוגיה','רופא נשים','גינקולוג'], 'kind':'person'},
 'fertility_doctor': {'priority':'A','terms':['פוריות IVF','פריון','שימור פוריות'], 'kind':'person'},
 'ivf_unit': {'priority':'A','terms':['יחידת IVF','הפריה חוץ גופית','יחידת פוריות'], 'kind':'org'},
 'fertility_center': {'priority':'A','terms':['מרכז פוריות','מרפאת פוריות','שימור פוריות'], 'kind':'org'},
 'embryologist': {'priority':'A','terms':['אמבריולוג','אמבריולוגית','embryologist IVF'], 'kind':'person'},
 'fertility_nurse': {'priority':'A','terms':['אחות פוריות','אחות IVF','אחות פריון'], 'kind':'person'},
 'fertility_consultant': {'priority':'A','terms':['יועצת פוריות','יועץ פוריות','fertility consultant'], 'kind':'person'},
 'sperm_bank': {'priority':'A','terms':['בנק זרע','sperm bank'], 'kind':'org'},
 'fertility_preservation': {'priority':'A','terms':['שימור פוריות','fertility preservation'], 'kind':'org'},
 'fertility_association': {'priority':'A','terms':['עמותת פוריות','עמותה IVF','ארגון פוריות'], 'kind':'org'},
 'doula': {'priority':'A','terms':['דולה','doula'], 'kind':'person'},
 'midwife': {'priority':'A','terms':['מיילדת עצמאית','מיילדת פרטית','midwife'], 'kind':'person'},
 'childbirth_educator': {'priority':'A','terms':['מדריכת הכנה ללידה','הכנה ללידה'], 'kind':'person'},
 'birth_center': {'priority':'A','terms':['מרכז לידה','מרכז הריון ולידה'], 'kind':'org'},
 'lactation': {'priority':'B','terms':['יועצת הנקה IBCLC','יועץ הנקה IBCLC'], 'kind':'person'},
 'pelvic_floor': {'priority':'B','terms':['פיזיותרפיסטית רצפת אגן','פיזיותרפיה רצפת אגן'], 'kind':'person'},
 'sleep_consultant': {'priority':'B','terms':['יועצת שינה תינוקות','יועץ שינה תינוקות'], 'kind':'person'},
 'pregnancy_dietitian': {'priority':'B','terms':['דיאטנית הריון','דיאטנית פוריות','דיאטנית אחרי לידה'], 'kind':'person'},
 'parenting_center': {'priority':'B','terms':['מרכז הורות','מרכז אמהות ותינוקות','מרכז הורים ותינוקות'], 'kind':'org'},
 'perinatal_mental_health': {'priority':'B','terms':['פסיכולוגית הריון','טיפול רגשי הריון','טיפול רגשי פוריות','בריאות הנפש סביב לידה'], 'kind':'person'},
 'facebook_group_admin': {'priority':'C','terms':['קבוצת פייסבוק הריון לידה','קבוצת פייסבוק IVF','קבוצת פייסבוק פוריות','קבוצת פייסבוק אמהות'], 'kind':'community'},
 'community_manager': {'priority':'C','terms':['קהילת הריון','קהילת לידה','קהילת פוריות','קהילת אמהות'], 'kind':'community'},
 'instagram_creator': {'priority':'C','terms':['אינסטגרם הריון לידה','אינסטגרם פוריות','יוצרת תוכן הריון'], 'kind':'creator'},
 'parenting_site': {'priority':'C','terms':['אתר הורות','פורטל הריון ולידה','אתר נשים הריון'], 'kind':'org'},
 'pregnancy_podcast': {'priority':'C','terms':['פודקאסט הריון','פודקאסט לידה','פודקאסט פוריות','פודקאסט הורות'], 'kind':'creator'},
 'doula_school': {'priority':'C','terms':['בית ספר לדולות','קורס דולות','לימודי דולה'], 'kind':'org'},
 'childbirth_school': {'priority':'C','terms':['בית ספר הכנה ללידה','קורס מדריכות הכנה ללידה'], 'kind':'org'},
 'women_health_creator': {'priority':'C','terms':['יוצרת תוכן בריאות האישה','משפיענית הריון לידה','בלוג הריון לידה'], 'kind':'creator'},
}

HEADERS={'User-Agent':'Mozilla/5.0 (compatible; ProfessionalContactResearch/1.1; public-contact-research)'}

def norm_email(e): return e.strip(' <>[](){}.,;:\"\'').lower()
def valid_email(e):
    if '@' not in e:return False
    local,domain=e.rsplit('@',1)
    return local not in BAD_LOCAL and '.' in domain and not domain.endswith(('.png','.jpg','.jpeg','.webp'))

def search_queries(name,category):
    cfg=CATEGORY_CONFIG.get(category,{'terms':[category],'kind':'person'})
    terms=cfg['terms']; queries=[]
    for term in terms[:3]:
      if name:
        queries += [f'"{name}" {term} email',f'"{name}" {term} מייל',f'"{name}" {term} contact']
      else:
        queries += [f'"{term}" ישראל email',f'"{term}" ישראל contact']
    return list(dict.fromkeys(queries))

def search_web(name,category,max_results=10):
    out=[];seen=set()
    with DDGS() as d:
      for q in search_queries(name,category):
        try:
          for r in d.text(q,region='il-he',safesearch='moderate',max_results=max_results):
            u=r.get('href') or r.get('url')
            if u and u not in seen:
              seen.add(u);out.append({'url':u,'title':r.get('title',''),'snippet':r.get('body',''),'query':q})
        except Exception: pass
        time.sleep(.6)
    return out[:35]

def fetch(url):
    try:
      r=requests.get(url,headers=HEADERS,timeout=15,allow_redirects=True)
      if r.status_code==200 and 'text/html' in r.headers.get('content-type','text/html'):
        return r.url,r.text
    except requests.RequestException: pass
    return url,''

def extract(url,html):
    soup=BeautifulSoup(html,'html.parser');text=soup.get_text(' ',strip=True)
    emails={norm_email(x) for x in EMAIL_RE.findall(text)}
    for a in soup.select('a[href^="mailto:"]'): emails.add(norm_email(a.get('href','')[7:].split('?')[0]))
    emails={e for e in emails if valid_email(e)}
    links=[]
    for a in soup.find_all('a',href=True):
      href=urljoin(url,a['href']);label=(a.get_text(' ',strip=True)+' '+a['href']).lower()
      if urlparse(href).netloc==urlparse(url).netloc and any(w in label for w in CONTACT_WORDS):links.append(href)
    return emails,list(dict.fromkeys(links))[:8],text[:30000]

def score(email,url,text,name,category):
    s=30;domain=urlparse(url).netloc.lower();local=email.split('@')[0]
    if name:
      tokens=[t.lower() for t in re.findall(r'[A-Za-z\u0590-\u05ff]+',name) if len(t)>2]
      if any(t in text.lower() for t in tokens):s+=25
    if local not in {'info','office','clinic','contact','mail','reception','admin'}:s+=15
    if any(x in domain for x in ['gov.il','ac.il','org.il']):s+=10
    if any(x in url.lower() for x in ['doctor','profile','staff','team','faculty','contact','about','רופא','צוות','אודות']):s+=10
    return min(s,100)

def classify(email,category):
    local=email.split('@')[0]
    if category in {'facebook_group_admin','community_manager','instagram_creator','pregnancy_podcast','women_health_creator'}: return 'BUSINESS_OR_COMMUNITY'
    if local in {'info','office','clinic','contact','reception','secretary','nashim','admin'}:return 'CLINIC_OR_ORGANIZATION'
    return 'PERSONAL_PROFESSIONAL'

def research(row):
    name=str(row.get('name','')).strip();category=str(row.get('category','')).strip()
    cfg=CATEGORY_CONFIG.get(category,{'priority':'','kind':'person'})
    attempts=[];candidates=[]
    for hit in search_web(name,category):
      u,html=fetch(hit['url']);attempts.append(u)
      if not html:continue
      emails,links,text=extract(u,html)
      for e in emails:candidates.append((score(e,u,text,name,category),e,u))
      for link in links[:4]:
        u2,h2=fetch(link);attempts.append(u2)
        if h2:
          es,_,t2=extract(u2,h2)
          for e in es:candidates.append((score(e,u2,t2,name,category),e,u2))
        time.sleep(.2)
      time.sleep(.3)
    candidates=sorted(set(candidates),reverse=True)
    base={'name':name,'category':category,'priority':cfg.get('priority',''),'target_kind':cfg.get('kind','')}
    if candidates:
      sc,e,u=candidates[0]
      return base|{'email':e,'email_type':classify(e,category),'confidence':sc,'source_url':u,'status':'FOUND','attempted_urls':json.dumps(list(dict.fromkeys(attempts)),ensure_ascii=False)}
    return base|{'email':'','email_type':'','confidence':0,'source_url':'','status':'NO_PUBLIC_EMAIL_FOUND','attempted_urls':json.dumps(list(dict.fromkeys(attempts)),ensure_ascii=False)}

def load_input(path):
    p=Path(path)
    if p.suffix.lower()=='.xlsx':return pd.read_excel(p).fillna('').to_dict('records')
    return pd.read_csv(p).fillna('').to_dict('records')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('input');ap.add_argument('--out',default='output');ap.add_argument('--resume',action='store_true');args=ap.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True);checkpoint=out/'checkpoint.jsonl';done={}
    if args.resume and checkpoint.exists():
      for line in checkpoint.read_text(encoding='utf-8').splitlines():
        r=json.loads(line);done[(r['name'],r['category'])]=r
    rows=load_input(args.input);total=len(rows)
    with checkpoint.open('a',encoding='utf-8') as f:
      for i,row in enumerate(rows,1):
        key=(str(row.get('name','')).strip(),str(row.get('category','')).strip())
        if key in done:continue
        print(f'[{i}/{total}] {key[0] or "DISCOVERY"} | {key[1]}',flush=True)
        r=research(row);done[key]=r;f.write(json.dumps(r,ensure_ascii=False)+'\n');f.flush()
    df=pd.DataFrame(list(done.values()))
    if df.empty:return
    df=df.sort_values(['priority','status','confidence'],ascending=[True,True,False]).drop_duplicates(subset=['name','category'],keep='first')
    df.to_csv(out/'audit.csv',index=False,encoding='utf-8-sig');df.to_excel(out/'audit.xlsx',index=False)
    found=df[df.status=='FOUND'].copy().sort_values(['priority','confidence'],ascending=[True,False]).drop_duplicates(subset=['email'],keep='first')
    found.to_csv(out/'contacts.csv',index=False,encoding='utf-8-sig');found.to_excel(out/'contacts.xlsx',index=False)
    summary={'total_targets':len(df),'found':int((df.status=='FOUND').sum()),'not_found':int((df.status=='NO_PUBLIC_EMAIL_FOUND').sum()),'unique_emails':int(found.email.nunique()),'by_category':df.groupby('category').status.value_counts().unstack(fill_value=0).to_dict('index')}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
