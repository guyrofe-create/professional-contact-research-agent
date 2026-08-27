from __future__ import annotations
import argparse, csv, hashlib, json, re, time
from pathlib import Path
from urllib.parse import urljoin, urlparse
import pandas as pd
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

EMAIL_RE=re.compile(r'(?i)(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.-])')
BAD_LOCAL={'example','test','noreply','no-reply','webmaster','privacy','abuse'}
CONTACT_WORDS=('contact','about','team','staff','doctor','clinic','faculty','profile','צור-קשר','אודות','צוות','רופאים','מרפאה')
CATEGORY_QUERIES={
 'gynecologist':['גינקולוג','גינקולוגית','רופא נשים','רופאת נשים','יילוד וגינקולוגיה'],
 'fertility':['פוריות','פריון','IVF'], 'doula':['דולה','doula'], 'midwife':['מיילדת','midwife'],
 'lactation':['יועצת הנקה','יועץ הנקה','IBCLC'], 'childbirth_educator':['הכנה ללידה','מדריכת הכנה ללידה'],
 'pelvic_floor':['פיזיותרפיה רצפת אגן','פיזיותרפיסטית רצפת אגן'], 'dietitian':['דיאטנית הריון','דיאטנית פוריות'],
 'mental_health':['טיפול רגשי הריון','פסיכולוגית הריון','פסיכולוג פוריות'], 'center':['מרכז הריון ולידה','מרכז פוריות']}
HEADERS={'User-Agent':'Mozilla/5.0 (compatible; ProfessionalContactResearch/1.0; +research)'}

def norm_email(e): return e.strip(' <>[](){}.,;:\"\'').lower()
def valid_email(e):
    if '@' not in e:return False
    local,domain=e.rsplit('@',1)
    return local not in BAD_LOCAL and '.' in domain and not domain.endswith(('.png','.jpg','.jpeg','.webp'))

def search_web(name, category, max_results=10):
    terms=CATEGORY_QUERIES.get(category,[category])
    queries=[f'"{name}" {terms[0]} email',f'"{name}" {terms[0]} מייל',f'"{name}" {terms[0]} contact']
    out=[]; seen=set()
    with DDGS() as d:
      for q in queries:
        try:
          for r in d.text(q, region='il-he', safesearch='moderate', max_results=max_results):
            u=r.get('href') or r.get('url')
            if u and u not in seen: seen.add(u); out.append({'url':u,'title':r.get('title',''),'snippet':r.get('body',''),'query':q})
        except Exception: pass
        time.sleep(.7)
    return out[:25]

def fetch(url):
    try:
      r=requests.get(url,headers=HEADERS,timeout=15,allow_redirects=True)
      if r.status_code==200 and 'text/html' in r.headers.get('content-type','text/html'):
        return r.url,r.text
    except requests.RequestException: pass
    return url,''

def extract(url,html):
    soup=BeautifulSoup(html,'html.parser'); text=soup.get_text(' ',strip=True)
    emails={norm_email(x) for x in EMAIL_RE.findall(text)}
    for a in soup.select('a[href^="mailto:"]'):
      emails.add(norm_email(a.get('href','')[7:].split('?')[0]))
    emails={e for e in emails if valid_email(e)}
    links=[]
    for a in soup.find_all('a',href=True):
      href=urljoin(url,a['href']); label=(a.get_text(' ',strip=True)+' '+a['href']).lower()
      if urlparse(href).netloc==urlparse(url).netloc and any(w in label for w in CONTACT_WORDS): links.append(href)
    return emails,list(dict.fromkeys(links))[:6],text[:20000]

def score(email,url,text,name):
    s=35; domain=urlparse(url).netloc.lower(); local=email.split('@')[0]
    name_tokens=[t.lower() for t in re.findall(r'[A-Za-z\u0590-\u05ff]+',name) if len(t)>2]
    if any(t in text.lower() for t in name_tokens): s+=20
    if local not in {'info','office','clinic','contact','mail','reception'}: s+=15
    if any(x in domain for x in ['gov.il','ac.il','org.il']): s+=10
    if any(x in url.lower() for x in ['doctor','profile','staff','team','faculty','רופא','צוות']): s+=10
    return min(s,100)

def classify(email):
    local=email.split('@')[0]
    if local in {'info','office','clinic','contact','reception','secretary','nashim'}: return 'CLINIC_OR_DEPARTMENT'
    return 'PERSONAL_PROFESSIONAL'

def research(row):
    name=str(row.get('name','')).strip(); category=str(row.get('category','')).strip()
    attempts=[]; candidates=[]
    for hit in search_web(name,category):
      u,html=fetch(hit['url']); attempts.append(u)
      if not html: continue
      emails,links,text=extract(u,html)
      for e in emails:candidates.append((score(e,u,text,name),e,u))
      for link in links[:3]:
        u2,h2=fetch(link); attempts.append(u2)
        if h2:
          es,_,t2=extract(u2,h2)
          for e in es:candidates.append((score(e,u2,t2,name),e,u2))
        time.sleep(.25)
      time.sleep(.35)
    candidates=sorted(set(candidates),reverse=True)
    if candidates:
      sc,e,u=candidates[0]
      return {'name':name,'category':category,'email':e,'email_type':classify(e),'confidence':sc,'source_url':u,'status':'FOUND','attempted_urls':json.dumps(list(dict.fromkeys(attempts)),ensure_ascii=False)}
    return {'name':name,'category':category,'email':'','email_type':'','confidence':0,'source_url':'','status':'NO_PUBLIC_EMAIL_FOUND','attempted_urls':json.dumps(list(dict.fromkeys(attempts)),ensure_ascii=False)}

def load_input(path):
    p=Path(path)
    if p.suffix.lower()=='.xlsx': return pd.read_excel(p).fillna('').to_dict('records')
    return pd.read_csv(p).fillna('').to_dict('records')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('input'); ap.add_argument('--out',default='output'); ap.add_argument('--resume',action='store_true'); args=ap.parse_args()
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True); checkpoint=out/'checkpoint.jsonl'
    done={}
    if args.resume and checkpoint.exists():
      for line in checkpoint.read_text(encoding='utf-8').splitlines():
        r=json.loads(line); done[(r['name'],r['category'])]=r
    rows=load_input(args.input); total=len(rows)
    with checkpoint.open('a',encoding='utf-8') as f:
      for i,row in enumerate(rows,1):
        key=(str(row.get('name','')).strip(),str(row.get('category','')).strip())
        if key in done: continue
        print(f'[{i}/{total}] {key[0]} | {key[1]}',flush=True)
        r=research(row); done[key]=r; f.write(json.dumps(r,ensure_ascii=False)+'\n'); f.flush()
    results=list(done.values()); df=pd.DataFrame(results)
    if not df.empty:
      df=df.sort_values(['status','confidence'],ascending=[True,False]).drop_duplicates(subset=['name','category'],keep='first')
      df.to_csv(out/'audit.csv',index=False,encoding='utf-8-sig'); df.to_excel(out/'audit.xlsx',index=False)
      found=df[df.status=='FOUND'].copy(); found=found.sort_values('confidence',ascending=False).drop_duplicates(subset=['email'],keep='first')
      found.to_csv(out/'contacts.csv',index=False,encoding='utf-8-sig'); found.to_excel(out/'contacts.xlsx',index=False)
      summary={'total_targets':len(df),'found':int((df.status=='FOUND').sum()),'not_found':int((df.status=='NO_PUBLIC_EMAIL_FOUND').sum()),'unique_emails':int(found.email.nunique())}
      (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
      print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
