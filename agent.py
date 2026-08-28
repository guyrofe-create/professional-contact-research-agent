from __future__ import annotations
import argparse, json, re, time, unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse
import pandas as pd
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

ALGO_VERSION=3
EMAIL_RE=re.compile(r'(?i)(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.-])')
BAD_LOCAL={'example','test','noreply','no-reply','webmaster','privacy','abuse','support'}
GENERIC_LOCAL={'info','office','clinic','contact','mail','reception','admin','secretary','nashim','service','hello','igudyhanaka'}
CONTACT_WORDS=('contact','about','team','staff','doctor','clinic','faculty','profile','צור-קשר','אודות','צוות','רופאים','מרפאה','הנהלה','admin','management')
CATEGORY_CONFIG={
'gynecologist':{'priority':'A','terms':['יילוד וגינקולוגיה','רופא נשים','גינקולוג'],'kind':'person'},'fertility_doctor':{'priority':'A','terms':['פוריות IVF','פריון','שימור פוריות'],'kind':'person'},'ivf_unit':{'priority':'A','terms':['יחידת IVF','הפריה חוץ גופית','יחידת פוריות'],'kind':'org'},'fertility_center':{'priority':'A','terms':['מרכז פוריות','מרפאת פוריות','שימור פוריות'],'kind':'org'},'embryologist':{'priority':'A','terms':['אמבריולוג','אמבריולוגית','embryologist IVF'],'kind':'person'},'fertility_nurse':{'priority':'A','terms':['אחות פוריות','אחות IVF','אחות פריון'],'kind':'person'},'fertility_consultant':{'priority':'A','terms':['יועצת פוריות','יועץ פוריות'],'kind':'person'},'sperm_bank':{'priority':'A','terms':['בנק זרע'],'kind':'org'},'fertility_preservation':{'priority':'A','terms':['שימור פוריות'],'kind':'org'},'fertility_association':{'priority':'A','terms':['עמותת פוריות','ארגון פוריות'],'kind':'org'},'doula':{'priority':'A','terms':['דולה','doula'],'kind':'person'},'midwife':{'priority':'A','terms':['מיילדת עצמאית','מיילדת פרטית'],'kind':'person'},'childbirth_educator':{'priority':'A','terms':['מדריכת הכנה ללידה','הכנה ללידה'],'kind':'person'},'birth_center':{'priority':'A','terms':['מרכז לידה','מרכז הריון ולידה'],'kind':'org'},'lactation':{'priority':'B','terms':['יועצת הנקה IBCLC'],'kind':'person'},'pelvic_floor':{'priority':'B','terms':['פיזיותרפיסטית רצפת אגן','פיזיותרפיה רצפת אגן'],'kind':'person'},'sleep_consultant':{'priority':'B','terms':['יועצת שינה תינוקות'],'kind':'person'},'pregnancy_dietitian':{'priority':'B','terms':['דיאטנית הריון','דיאטנית פוריות'],'kind':'person'},'parenting_center':{'priority':'B','terms':['מרכז הורות','מרכז הורים ותינוקות'],'kind':'org'},'perinatal_mental_health':{'priority':'B','terms':['פסיכולוגית הריון','טיפול רגשי פוריות'],'kind':'person'},'facebook_group_admin':{'priority':'C','terms':['קבוצת פייסבוק הריון לידה','קבוצת פייסבוק פוריות'],'kind':'community'},'community_manager':{'priority':'C','terms':['קהילת הריון','קהילת פוריות'],'kind':'community'},'instagram_creator':{'priority':'C','terms':['אינסטגרם הריון לידה','אינסטגרם פוריות'],'kind':'creator'},'parenting_site':{'priority':'C','terms':['אתר הורות','פורטל הריון ולידה'],'kind':'org'},'pregnancy_podcast':{'priority':'C','terms':['פודקאסט הריון','פודקאסט פוריות'],'kind':'creator'},'doula_school':{'priority':'C','terms':['בית ספר לדולות','קורס דולות'],'kind':'org'},'childbirth_school':{'priority':'C','terms':['בית ספר הכנה ללידה','קורס מדריכות הכנה ללידה'],'kind':'org'},'women_health_creator':{'priority':'C','terms':['יוצרת תוכן בריאות האישה','בלוג הריון לידה'],'kind':'creator'}}
HEADERS={'User-Agent':'Mozilla/5.0 (compatible; ProfessionalContactResearch/3.0; public-contact-research)'}
def norm(s):return re.sub(r'[^a-z0-9\u0590-\u05ff]+',' ',unicodedata.normalize('NFKD',str(s or '')).lower()).strip()
def tokens(s):return [x for x in norm(s).split() if len(x)>=2 and x not in {'דר','פרופ','doctor','prof'}]
def norm_email(e):return e.strip(' <>[](){}.,;:\"\'').lower()
def valid_email(e):
 if '@' not in e:return False
 local,domain=e.rsplit('@',1);return bool(local and domain and '.' in domain and local not in BAD_LOCAL and not domain.endswith(('.png','.jpg','.jpeg','.webp')))
def person_name_match(name,text):
 ts=tokens(name);hay=norm(text);return bool(ts) and sum(1 for t in ts if t in hay)>=min(2,len(ts))
def local_name_match(email,name):
 local=norm(email.split('@')[0]).replace(' ','');return any(len(t)>=3 and t in local for t in tokens(name) if re.search('[a-z]',t))
def search_queries(name,category):
 cfg=CATEGORY_CONFIG.get(category,{'terms':[category]});terms=cfg.get('terms') or [category]
 # Start with high-signal direct-contact searches, then add at most two category-specific fallbacks.
 qs=[f'"{name}" email',f'"{name}" מייל',f'"{name}" contact',f'"{name}" אתר רשמי']
 for term in terms[:2]:qs.append(f'"{name}" {term}')
 return list(dict.fromkeys(qs))
def search_web(name,category,max_results=6):
 out=[];seen=set();seen_domains=set();d=DDGS()
 for q in search_queries(name,category):
  try:
   for r in (d.text(q,region='il-he',safesearch='moderate',max_results=max_results) or []):
    u=r.get('href') or r.get('url')
    if not u or u in seen:continue
    domain=urlparse(u).netloc.lower()
    # Keep at most two landing pages per domain; contact pages are discovered from those pages.
    if sum(1 for x in out if urlparse(x['url']).netloc.lower()==domain)>=2:continue
    seen.add(u);seen_domains.add(domain);out.append({'url':u,'title':r.get('title',''),'snippet':r.get('body',''),'query':q})
    if len(out)>=18:break
  except Exception as e:print('SEARCH_WARNING',type(e).__name__,str(e)[:160],flush=True)
  if len(out)>=18:break
  time.sleep(.1)
 return out[:18]
def fetch(url):
 try:
  r=requests.get(url,headers=HEADERS,timeout=(5,10),allow_redirects=True)
  if r.status_code==200 and 'text/html' in r.headers.get('content-type','text/html'):return r.url,r.text
 except requests.RequestException:pass
 return url,''
def extract(url,html):
 soup=BeautifulSoup(html,'html.parser');text=soup.get_text(' ',strip=True);found=[]
 for a in soup.select('a[href^="mailto:"]'):
  e=norm_email(a.get('href','')[7:].split('?')[0]);block=a.find_parent(['li','p','div','section','article','td']);ctx=(block.get_text(' ',strip=True) if block else a.parent.get_text(' ',strip=True))[:1200]
  if valid_email(e):found.append((e,ctx,'mailto'))
 for e in {norm_email(x) for x in EMAIL_RE.findall(text)}:
  if valid_email(e):
   pos=text.lower().find(e.lower());found.append((e,text[max(0,pos-450):pos+450] if pos>=0 else '','text'))
 links=[]
 for a in soup.find_all('a',href=True):
  href=urljoin(url,a['href']);label=(a.get_text(' ',strip=True)+' '+a['href']).lower()
  if urlparse(href).netloc==urlparse(url).netloc and any(w in label for w in CONTACT_WORDS):links.append(href)
 return list(dict.fromkeys(found)),list(dict.fromkeys(links))[:8],text[:40000],soup.title.get_text(' ',strip=True) if soup.title else ''
def candidate_score(email,url,page_text,title,context,name,category):
 cfg=CATEGORY_CONFIG.get(category,{'kind':'person'});kind=cfg.get('kind','person');local=email.split('@')[0]
 if kind=='person':
  near=person_name_match(name,context);page=person_name_match(name,title+' '+page_text[:6000]);localmatch=local_name_match(email,name)
  if local in GENERIC_LOCAL and not near:return None
  if not (near or localmatch or (page and ('/profile' in url.lower() or '/doctor' in url.lower()))):return None
  s=40+(35 if near else 0)+(20 if localmatch else 0)+(10 if page else 0)
 else:s=50+(20 if person_name_match(name,title+' '+page_text[:8000]) else 0)
 if any(x in urlparse(url).netloc.lower() for x in ['gov.il','ac.il','org.il']):s+=5
 if local in GENERIC_LOCAL:s-=10
 return max(0,min(s,100))
def classify(email,category):
 local=email.split('@')[0]
 if category in {'facebook_group_admin','community_manager','instagram_creator','pregnancy_podcast','women_health_creator'}:return 'BUSINESS_OR_COMMUNITY'
 return 'CLINIC_OR_ORGANIZATION' if local in GENERIC_LOCAL else 'PERSONAL_PROFESSIONAL'
def research(row):
 name=str(row.get('name','')).strip();category=str(row.get('category','')).strip();cfg=CATEGORY_CONFIG.get(category,{'priority':'','kind':'person'});attempts=[];candidates=[]
 for hit in search_web(name,category):
  u,html=fetch(hit['url']);attempts.append(u)
  if not html:continue
  items,links,text,title=extract(u,html)
  for e,ctx,_ in items:
   sc=candidate_score(e,u,text,title,ctx,name,category)
   if sc is not None:candidates.append((sc,e,u,ctx[:300]))
  for link in links[:2]:
   u2,h2=fetch(link);attempts.append(u2)
   if h2:
    items2,_,t2,title2=extract(u2,h2)
    for e,ctx,_ in items2:
     sc=candidate_score(e,u2,t2,title2,ctx,name,category)
     if sc is not None:candidates.append((sc,e,u2,ctx[:300]))
  # A score of 90 requires strong name/evidence agreement; further broad crawling adds little value.
  if candidates and max(x[0] for x in candidates)>=90:break
  time.sleep(.05)
 candidates=sorted(set(candidates),reverse=True);base={'algo_version':ALGO_VERSION,'name':name,'category':category,'priority':cfg.get('priority',''),'target_kind':cfg.get('kind','')}
 if candidates:
  sc,e,u,ctx=candidates[0];return base|{'email':e,'email_type':classify(e,category),'confidence':sc,'source_url':u,'status':'FOUND','evidence':ctx,'attempted_urls':json.dumps(list(dict.fromkeys(attempts)),ensure_ascii=False)}
 return base|{'email':'','email_type':'','confidence':0,'source_url':'','status':'NO_PUBLIC_EMAIL_FOUND','evidence':'','attempted_urls':json.dumps(list(dict.fromkeys(attempts)),ensure_ascii=False)}
def load_input(path):
 p=Path(path);return (pd.read_excel(p) if p.suffix.lower()=='.xlsx' else pd.read_csv(p)).fillna('').to_dict('records')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('input');ap.add_argument('--out',default='output');ap.add_argument('--resume',action='store_true');args=ap.parse_args();out=Path(args.out);out.mkdir(parents=True,exist_ok=True);checkpoint=out/'checkpoint.jsonl';done={}
 if args.resume and checkpoint.exists():
  for line in checkpoint.read_text(encoding='utf-8').splitlines():
   try:r=json.loads(line)
   except Exception:continue
   if r.get('algo_version')==ALGO_VERSION:done[(r.get('name',''),r.get('category',''))]=r
 rows=load_input(args.input);total=len(rows);checkpoint.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in done.values()),encoding='utf-8')
 with checkpoint.open('a',encoding='utf-8') as f:
  for i,row in enumerate(rows,1):
   key=(str(row.get('name','')).strip(),str(row.get('category','')).strip())
   if key in done:continue
   print(f'[{i}/{total}] {key[0]} | {key[1]}',flush=True);r=research(row);done[key]=r;f.write(json.dumps(r,ensure_ascii=False)+'\n');f.flush()
 df=pd.DataFrame(list(done.values()))
 if df.empty:return
 df=df.sort_values(['priority','status','confidence'],ascending=[True,True,False]).drop_duplicates(subset=['name','category'],keep='first');person=df[df.target_kind=='person'];counts=Counter(person[person.email!=''].email);suspicious={e for e,n in counts.items() if n>2}
 if suspicious:
  mask=(df.target_kind=='person')&df.email.isin(suspicious);df.loc[mask,'status']='REVIEW_SHARED_EMAIL';df.loc[mask,'confidence']=0
 df.to_csv(out/'audit.csv',index=False,encoding='utf-8-sig');df.to_excel(out/'audit.xlsx',index=False);found=df[df.status=='FOUND'].copy().sort_values(['priority','confidence'],ascending=[True,False]).drop_duplicates(subset=['email'],keep='first');found.to_csv(out/'contacts.csv',index=False,encoding='utf-8-sig');found.to_excel(out/'contacts.xlsx',index=False);df[df.status.str.startswith('REVIEW')].to_excel(out/'review.xlsx',index=False)
 summary={'algo_version':ALGO_VERSION,'total_targets':len(df),'found':int((df.status=='FOUND').sum()),'not_found':int((df.status=='NO_PUBLIC_EMAIL_FOUND').sum()),'review':int(df.status.str.startswith('REVIEW').sum()),'unique_emails':int(found.email.nunique()),'by_category':df.groupby('category').status.value_counts().unstack(fill_value=0).to_dict('index')};(out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
