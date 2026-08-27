from __future__ import annotations
import argparse, json, re, time, unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse
import pandas as pd
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

ALGO_VERSION=2
EMAIL_RE=re.compile(r'(?i)(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.-])')
BAD_LOCAL={'example','test','noreply','no-reply','webmaster','privacy','abuse','support'}
GENERIC_LOCAL={'info','office','clinic','contact','mail','reception','admin','secretary','nashim','service','hello','igudyhanaka'}
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
HEADERS={'User-Agent':'Mozilla/5.0 (compatible; ProfessionalContactResearch/2.0; public-contact-research)'}

def norm(s):
    s=unicodedata.normalize('NFKD',str(s or '')).lower()
    return re.sub(r'[^a-z0-9\u0590-\u05ff]+',' ',s).strip()
def tokens(s): return [x for x in norm(s).split() if len(x)>=2 and x not in {'דר','פרופ','doctor','prof'}]
def norm_email(e): return e.strip(' <>[](){}.,;:\"\'').lower()
def valid_email(e):
    if '@' not in e:return False
    local,domain=e.rsplit('@',1)
    return bool(local and domain and '.' in domain and local not in BAD_LOCAL and not domain.endswith(('.png','.jpg','.jpeg','.webp')))
def person_name_match(name,text):
    ts=tokens(name); hay=norm(text)
    if not ts:return False
    hits=sum(1 for t in ts if t in hay)
    return hits>=min(2,len(ts))
def local_name_match(email,name):
    local=norm(email.split('@')[0]).replace(' ','')
    latin=[t for t in tokens(name) if re.search('[a-z]',t)]
    return any(len(t)>=3 and t in local for t in latin)

def search_queries(name,category):
    cfg=CATEGORY_CONFIG.get(category,{'terms':[category]}); qs=[]
    for term in cfg['terms'][:3]:
      if name: qs += [f'"{name}" {term} email',f'"{name}" {term} מייל',f'"{name}" {term} contact',f'"{name}" {term} אתר']
      else: qs += [f'"{term}" ישראל email',f'"{term}" ישראל contact']
    return list(dict.fromkeys(qs))
def search_web(name,category,max_results=10):
    out=[];seen=set()
    with DDGS() as d:
      for q in search_queries(name,category):
        try:
          for r in d.text(q,region='il-he',safesearch='moderate',max_results=max_results):
            u=r.get('href') or r.get('url')
            if u and u not in seen: seen.add(u);out.append({'url':u,'title':r.get('title',''),'snippet':r.get('body',''),'query':q})
        except Exception: pass
        time.sleep(.45)
    return out[:40]
def fetch(url):
    try:
      r=requests.get(url,headers=HEADERS,timeout=15,allow_redirects=True)
      if r.status_code==200 and 'text/html' in r.headers.get('content-type','text/html'): return r.url,r.text
    except requests.RequestException: pass
    return url,''
def extract(url,html):
    soup=BeautifulSoup(html,'html.parser');text=soup.get_text(' ',strip=True)
    found=[]
    for a in soup.select('a[href^="mailto:"]'):
      e=norm_email(a.get('href','')[7:].split('?')[0])
      if valid_email(e):
        block=a.find_parent(['li','p','div','section','article','td'])
        ctx=(block.get_text(' ',strip=True) if block else a.parent.get_text(' ',strip=True))[:1200]
        found.append((e,ctx,'mailto'))
    for e in {norm_email(x) for x in EMAIL_RE.findall(text)}:
      if valid_email(e):
        pos=text.lower().find(e.lower()); ctx=text[max(0,pos-450):pos+450] if pos>=0 else ''
        found.append((e,ctx,'text'))
    links=[]
    for a in soup.find_all('a',href=True):
      href=urljoin(url,a['href']);label=(a.get_text(' ',strip=True)+' '+a['href']).lower()
      if urlparse(href).netloc==urlparse(url).netloc and any(w in label for w in CONTACT_WORDS):links.append(href)
    return list(dict.fromkeys(found)),list(dict.fromkeys(links))[:8],text[:40000],soup.title.get_text(' ',strip=True) if soup.title else ''
def candidate_score(email,url,page_text,title,context,name,category):
    cfg=CATEGORY_CONFIG.get(category,{'kind':'person'});kind=cfg.get('kind','person');local=email.split('@')[0]
    if kind=='person':
      near=person_name_match(name,context); page=person_name_match(name,title+' '+page_text[:6000]); localmatch=local_name_match(email,name)
      # Generic site-wide addresses are not attributable to a person unless the local context explicitly contains the name.
      if local in GENERIC_LOCAL and not near:return None
      if not (near or localmatch or (page and '/profile' in url.lower()) or (page and '/doctor' in url.lower())):return None
      s=40+(35 if near else 0)+(20 if localmatch else 0)+(10 if page else 0)
    else:
      s=50+(20 if person_name_match(name,title+' '+page_text[:8000]) else 0)
    domain=urlparse(url).netloc.lower()
    if any(x in domain for x in ['gov.il','ac.il','org.il']):s+=5
    if local in GENERIC_LOCAL:s-=10
    return max(0,min(s,100))
def classify(email,category):
    local=email.split('@')[0]
    if category in {'facebook_group_admin','community_manager','instagram_creator','pregnancy_podcast','women_health_creator'}:return 'BUSINESS_OR_COMMUNITY'
    if local in GENERIC_LOCAL:return 'CLINIC_OR_ORGANIZATION'
    return 'PERSONAL_PROFESSIONAL'
def research(row):
    name=str(row.get('name','')).strip();category=str(row.get('category','')).strip();cfg=CATEGORY_CONFIG.get(category,{'priority':'','kind':'person'})
    attempts=[];candidates=[]
    for hit in search_web(name,category):
      u,html=fetch(hit['url']);attempts.append(u)
      if not html:continue
      items,links,text,title=extract(u,html)
      for e,ctx,mode in items:
        sc=candidate_score(e,u,text,title,ctx,name,category)
        if sc is not None:candidates.append((sc,e,u,ctx[:300]))
      for link in links[:4]:
        u2,h2=fetch(link);attempts.append(u2)
        if h2:
          items2,_,t2,title2=extract(u2,h2)
          for e,ctx,mode in items2:
            sc=candidate_score(e,u2,t2,title2,ctx,name,category)
            if sc is not None:candidates.append((sc,e,u2,ctx[:300]))
        time.sleep(.15)
      time.sleep(.2)
    candidates=sorted(set(candidates),reverse=True)
    base={'algo_version':ALGO_VERSION,'name':name,'category':category,'priority':cfg.get('priority',''),'target_kind':cfg.get('kind','')}
    if candidates:
      sc,e,u,ctx=candidates[0]
      return base|{'email':e,'email_type':classify(e,category),'confidence':sc,'source_url':u,'status':'FOUND','evidence':ctx,'attempted_urls':json.dumps(list(dict.fromkeys(attempts)),ensure_ascii=False)}
    return base|{'email':'','email_type':'','confidence':0,'source_url':'','status':'NO_PUBLIC_EMAIL_FOUND','evidence':'','attempted_urls':json.dumps(list(dict.fromkeys(attempts)),ensure_ascii=False)}
def load_input(path):
    p=Path(path)
    if p.suffix.lower()=='.xlsx':return pd.read_excel(p).fillna('').to_dict('records')
    return pd.read_csv(p).fillna('').to_dict('records')
def main():
    ap=argparse.ArgumentParser();ap.add_argument('input');ap.add_argument('--out',default='output');ap.add_argument('--resume',action='store_true');args=ap.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True);checkpoint=out/'checkpoint.jsonl';done={}
    if args.resume and checkpoint.exists():
      for line in checkpoint.read_text(encoding='utf-8').splitlines():
        try:r=json.loads(line)
        except Exception:continue
        if r.get('algo_version')==ALGO_VERSION:done[(r.get('name',''),r.get('category',''))]=r
    rows=load_input(args.input);total=len(rows)
    # Rewrite checkpoint with only current-version results, automatically discarding old flawed output.
    checkpoint.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in done.values()),encoding='utf-8')
    with checkpoint.open('a',encoding='utf-8') as f:
      for i,row in enumerate(rows,1):
        key=(str(row.get('name','')).strip(),str(row.get('category','')).strip())
        if key in done:continue
        print(f'[{i}/{total}] {key[0] or "DISCOVERY"} | {key[1]}',flush=True)
        r=research(row);done[key]=r;f.write(json.dumps(r,ensure_ascii=False)+'\n');f.flush()
    df=pd.DataFrame(list(done.values()))
    if df.empty:return
    df=df.sort_values(['priority','status','confidence'],ascending=[True,True,False]).drop_duplicates(subset=['name','category'],keep='first')
    # Quarantine a repeated address assigned to multiple distinct people. This catches site-wide association addresses.
    person=df[df.target_kind=='person']; counts=Counter(person[person.email!=''].email)
    suspicious={e for e,n in counts.items() if n>2}
    if suspicious:
      mask=(df.target_kind=='person') & df.email.isin(suspicious)
      df.loc[mask,'status']='REVIEW_SHARED_EMAIL';df.loc[mask,'confidence']=0
    df.to_csv(out/'audit.csv',index=False,encoding='utf-8-sig');df.to_excel(out/'audit.xlsx',index=False)
    found=df[df.status=='FOUND'].copy().sort_values(['priority','confidence'],ascending=[True,False]).drop_duplicates(subset=['email'],keep='first')
    found.to_csv(out/'contacts.csv',index=False,encoding='utf-8-sig');found.to_excel(out/'contacts.xlsx',index=False)
    review=df[df.status.str.startswith('REVIEW')].copy();review.to_excel(out/'review.xlsx',index=False)
    summary={'algo_version':ALGO_VERSION,'total_targets':len(df),'found':int((df.status=='FOUND').sum()),'not_found':int((df.status=='NO_PUBLIC_EMAIL_FOUND').sum()),'review':int(df.status.str.startswith('REVIEW').sum()),'unique_emails':int(found.email.nunique()),'by_category':df.groupby('category').status.value_counts().unstack(fill_value=0).to_dict('index')}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
