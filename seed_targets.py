from __future__ import annotations
import io,re,time
from pathlib import Path
from urllib.parse import urljoin,urlparse
import pandas as pd
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

UA={'User-Agent':'Mozilla/5.0 (compatible; ProfessionalContactResearch/2.0)'}
MOH='https://data.gov.il/he/datasets/ministry-health/database-of-doctors-licenses-moh'
IALP='https://ialp.org.il/counselors/'
IMA='https://www.ima.org.il/doctorsindex/results.aspx?spid=20&page={page}'
DISCOVERY={
'doula':['דולה ישראל','אינדקס דולות ישראל'],
'midwife':['מיילדת עצמאית ישראל','מיילדת פרטית ישראל'],
'childbirth_educator':['מדריכת הכנה ללידה ישראל','קורס הכנה ללידה מדריכה'],
'birth_center':['מרכז לידה ישראל','מרכז הריון ולידה'],
'fertility_doctor':['רופא פוריות IVF ישראל','מומחה פריון ישראל'],
'ivf_unit':['יחידת IVF בית חולים ישראל'],
'fertility_center':['מרכז פוריות פרטי ישראל'],
'embryologist':['אמבריולוגית IVF ישראל','אמבריולוג ישראל'],
'fertility_nurse':['אחות פוריות IVF ישראל'],
'fertility_consultant':['יועצת פוריות ישראל'],
'sperm_bank':['בנק זרע ישראל'],
'fertility_preservation':['מרכז שימור פוריות ישראל'],
'fertility_association':['עמותת פוריות ישראל'],
'pelvic_floor':['פיזיותרפיסטית רצפת אגן הריון ישראל','פיזיותרפיה רצפת אגן נשים ישראל'],
'sleep_consultant':['יועצת שינה תינוקות ישראל'],
'pregnancy_dietitian':['דיאטנית הריון פוריות ישראל','דיאטנית אחרי לידה ישראל'],
'parenting_center':['מרכז הורות תינוקות ישראל'],
'perinatal_mental_health':['פסיכולוגית הריון לידה פוריות ישראל'],
'facebook_group_admin':['קבוצת פייסבוק הריון לידה ישראל','קבוצת פייסבוק IVF פוריות ישראל','קבוצת פייסבוק אמהות ישראל'],
'community_manager':['קהילת הריון לידה ישראל','קהילת פוריות ישראל'],
'instagram_creator':['אינסטגרם הריון לידה ישראל','אינסטגרם פוריות ישראל'],
'parenting_site':['אתר הורות הריון לידה ישראל'],
'pregnancy_podcast':['פודקאסט הריון לידה פוריות ישראל'],
'doula_school':['בית ספר לדולות ישראל','קורס דולות ישראל'],
'childbirth_school':['קורס מדריכות הכנה ללידה ישראל'],
'women_health_creator':['בלוג בריאות האישה הריון לידה ישראל','יוצרת תוכן בריאות האישה ישראל']}

BAD_TITLE=('facebook','instagram','linkedin','youtube','ויקיפדיה','wikipedia','חדשות','כתבה','מאמר','מדריך','מחיר','דרושים')
def clean_name(s):
 s=re.sub(r'\s+',' ',str(s or '')).strip(' |-–—:')
 s=re.sub(r'^(דף הבית|אודות|צור קשר)\s*[-|:]?\s*','',s)
 return s[:160]
def add(rows,name,cat,source=''):
 name=clean_name(name)
 if 3<=len(name)<=160: rows.append({'name':name,'category':cat,'seed_source':source})
def likely_title_entity(title):
 t=clean_name(title)
 # Search-result titles often contain suffixes. Keep the leftmost entity-like segment.
 for sep in [' | ',' - ',' – ',' — ',':']:
  if sep in t:t=t.split(sep)[0].strip()
 if not t or any(x.lower() in t.lower() for x in BAD_TITLE):return ''
 if len(t.split())>9:return ''
 return t

def seed_moh(rows):
 # data.gov sometimes changes the resource URL. Discover CSV links from the dataset page and common API/resource anchors.
 try:
  html=requests.get(MOH,headers=UA,timeout=30).text;soup=BeautifulSoup(html,'html.parser')
  links=[]
  for a in soup.find_all('a',href=True):
   h=urljoin(MOH,a['href']); low=h.lower()
   if '.csv' in low or 'resource' in low or 'download' in low:links.append(h)
  for u in dict.fromkeys(links):
   try:
    r=requests.get(u,headers=UA,timeout=60)
    if r.status_code!=200:continue
    if b',' not in r.content[:5000] and b';' not in r.content[:5000]:continue
    df=None
    for enc in ['utf-8-sig','utf-8','cp1255']:
     try:df=pd.read_csv(io.BytesIO(r.content),encoding=enc);break
     except Exception:pass
    if df is None or df.empty:continue
    cols={str(c):c for c in df.columns}
    spec=next((c for c in df.columns if ('התמחות' in str(c) or 'special' in str(c).lower())),None)
    first=next((c for c in df.columns if ('פרטי' in str(c) or 'first' in str(c).lower())),None)
    last=next((c for c in df.columns if ('משפחה' in str(c) or 'last' in str(c).lower())),None)
    full=next((c for c in df.columns if ('שם' in str(c) and ('מלא' in str(c) or 'full' in str(c).lower()))),None)
    if spec:
     g=df[df[spec].astype(str).str.contains('יילוד|גינקולוג|obstet|gynec',case=False,na=False)]
     for _,x in g.iterrows():
      name=(str(x[full]) if full else f"{x[first]} {x[last]}" if first and last else '')
      add(rows,name,'gynecologist',u)
     if len(g)>100:return len(g)
   except Exception:pass
 except Exception:pass
 return 0

def seed_ima(rows):
 # Reliable fallback for the active specialist index. Do not use IMA contact details, only names.
 seen=set();empty=0
 for page in range(1,25):
  url=IMA.format(page=page)
  try:
   soup=BeautifulSoup(requests.get(url,headers=UA,timeout=30).text,'html.parser');before=len(seen)
   for a in soup.find_all('a',href=True):
    href=a.get('href','');txt=clean_name(a.get_text(' ',strip=True))
    if ('DoctorProfile' in href or 'doctorprofile' in href.lower()) and 3<=len(txt)<=100:
     seen.add(txt);add(rows,txt,'gynecologist',url)
   if len(seen)==before:empty+=1
   else:empty=0
   if empty>=2 and page>5:break
  except Exception:empty+=1
  time.sleep(.2)
 return len(seen)

def seed_ialp(rows):
 try:
  soup=BeautifulSoup(requests.get(IALP,headers=UA,timeout=30).text,'html.parser')
  links=set()
  for a in soup.find_all('a',href=True):
   href=urljoin(IALP,a['href']);txt=clean_name(a.get_text(' ',strip=True))
   if urlparse(href).netloc==urlparse(IALP).netloc and ('counselor' in href.lower() or '/יוע' in href) and txt:links.add((href,txt))
  for href,txt in links:add(rows,txt.split(' – ')[0],'lactation',href)
  # fallback headings
  for h in soup.find_all(['h2','h3','h4']):
   name=clean_name(h.get_text(' ',strip=True))
   if name and not any(x in name for x in ['חיפוש','יועצות','Archive']):add(rows,name.split(' – ')[0],'lactation',IALP)
 except Exception:pass

def web_discovery(rows):
 with DDGS() as d:
  for cat,queries in DISCOVERY.items():
   for q in queries:
    try:
     for r in d.text(q,region='il-he',safesearch='moderate',max_results=40):
      source=r.get('href') or r.get('url') or '';title=likely_title_entity(r.get('title',''))
      if title:add(rows,title,cat,source)
    except Exception:pass
    time.sleep(.6)

def main():
 rows=[]
 moh=seed_moh(rows)
 ima=seed_ima(rows)
 seed_ialp(rows)
 web_discovery(rows)
 df=pd.DataFrame(rows)
 if df.empty:raise SystemExit('No targets discovered')
 df=df.drop_duplicates(subset=['name','category']).sort_values(['category','name'])
 old=Path('targets.csv')
 if old.exists():
  try:
   prev=pd.read_csv(old).fillna('');df=pd.concat([prev,df],ignore_index=True).drop_duplicates(subset=['name','category'])
  except Exception:pass
 df.to_csv('targets.csv',index=False,encoding='utf-8-sig')
 counts=df.category.value_counts().to_dict()
 Path('seed_summary.json').write_text(pd.Series({'total':len(df),'moh_gynecology':moh,'ima_gynecology':ima,'categories':counts}).to_json(force_ascii=False,indent=2),encoding='utf-8')
 print(f'Targets: {len(df)} | MOH gyn: {moh} | IMA gyn: {ima} | categories: {counts}')
 if counts.get('gynecologist',0)<300: raise SystemExit('Safety stop: fewer than 300 gynecologists discovered; do not run incomplete universe')
 if len(counts)<10: raise SystemExit('Safety stop: too few target categories discovered')
if __name__=='__main__':main()
