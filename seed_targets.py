from __future__ import annotations
import io,re,time
from pathlib import Path
from urllib.parse import urljoin
import pandas as pd
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

UA={'User-Agent':'Mozilla/5.0 (compatible; ProfessionalContactResearch/1.2)'}
MOH='https://data.gov.il/he/datasets/ministry-health/database-of-doctors-licenses-moh/9c64c522-bbc2-48fe-96fb-3b2a8626f59e'
IALP='https://ialp.org.il/counselors/'
DISCOVERY={
'doula':['דולה ישראל','אינדקס דולות ישראל'],
'midwife':['מיילדת עצמאית ישראל','מיילדת פרטית ישראל'],
'childbirth_educator':['מדריכת הכנה ללידה ישראל'],
'birth_center':['מרכז לידה ישראל','מרכז הריון ולידה'],
'fertility_doctor':['רופא פוריות IVF ישראל'],
'ivf_unit':['יחידת IVF בית חולים ישראל'],
'fertility_center':['מרכז פוריות פרטי ישראל'],
'embryologist':['אמבריולוגית IVF ישראל','אמבריולוג ישראל'],
'fertility_nurse':['אחות פוריות IVF ישראל'],
'fertility_consultant':['יועצת פוריות ישראל'],
'sperm_bank':['בנק זרע ישראל'],
'fertility_preservation':['מרכז שימור פוריות ישראל'],
'fertility_association':['עמותת פוריות ישראל'],
'pelvic_floor':['פיזיותרפיסטית רצפת אגן הריון ישראל'],
'sleep_consultant':['יועצת שינה תינוקות ישראל'],
'pregnancy_dietitian':['דיאטנית הריון פוריות ישראל'],
'parenting_center':['מרכז הורות תינוקות ישראל'],
'perinatal_mental_health':['פסיכולוגית הריון לידה פוריות ישראל'],
'facebook_group_admin':['קבוצת פייסבוק הריון לידה ישראל','קבוצת פייסבוק IVF פוריות ישראל','קבוצת פייסבוק אמהות ישראל'],
'community_manager':['קהילת הריון לידה ישראל','קהילת פוריות ישראל'],
'instagram_creator':['אינסטגרם הריון לידה ישראל','אינסטגרם פוריות ישראל'],
'parenting_site':['אתר הורות הריון לידה ישראל'],
'pregnancy_podcast':['פודקאסט הריון לידה פוריות ישראל'],
'doula_school':['בית ספר לדולות ישראל'],
'childbirth_school':['קורס מדריכות הכנה ללידה ישראל'],
'women_health_creator':['בלוג בריאות האישה הריון לידה ישראל']}

def clean_name(s):
 s=re.sub(r'\s+',' ',s or '').strip(' |-–—:')
 s=re.sub(r'^(דף הבית|אודות|צור קשר)\s*[-|:]?\s*','',s)
 return s[:160]

def add(rows,name,cat,source=''):
 name=clean_name(name)
 if len(name)>=3: rows.append({'name':name,'category':cat,'seed_source':source})

def seed_moh(rows):
 try:
  html=requests.get(MOH,headers=UA,timeout=30).text; soup=BeautifulSoup(html,'html.parser')
  links=[urljoin(MOH,a.get('href')) for a in soup.find_all('a',href=True) if any(x in a.get('href','').lower() for x in ['csv','download','resource'])]
  for u in dict.fromkeys(links):
   try:
    r=requests.get(u,headers=UA,timeout=60)
    if r.status_code!=200: continue
    ct=r.headers.get('content-type','').lower()
    if 'csv' not in ct and not u.lower().endswith('.csv'): continue
    for enc in ['utf-8-sig','utf-8','cp1255']:
     try: df=pd.read_csv(io.BytesIO(r.content),encoding=enc); break
     except Exception: df=None
    if df is None: continue
    spec=next((c for c in df.columns if 'התמחות' in str(c) and 'שם' in str(c)),None)
    first=next((c for c in df.columns if 'פרטי' in str(c)),None); last=next((c for c in df.columns if 'משפחה' in str(c)),None)
    if spec and first and last:
     g=df[df[spec].astype(str).str.contains('יילוד|גינקולוג',case=False,na=False)]
     for _,x in g.iterrows(): add(rows,f"{x[first]} {x[last]}",'gynecologist',MOH)
     return
   except Exception: pass
 except Exception: pass

def seed_ialp(rows):
 try:
  html=requests.get(IALP,headers=UA,timeout=30).text; soup=BeautifulSoup(html,'html.parser')
  for h in soup.find_all(['h2','h3','h4']):
   name=clean_name(h.get_text(' ',strip=True))
   if name and not any(x in name for x in ['חיפוש','יועצות','Archive']): add(rows,name.split(' – ')[0],'lactation',IALP)
 except Exception: pass

def web_discovery(rows):
 with DDGS() as d:
  for cat,queries in DISCOVERY.items():
   for q in queries:
    try:
     for r in d.text(q,region='il-he',safesearch='moderate',max_results=30):
      title=clean_name(r.get('title',''))
      if title: add(rows,title,cat,r.get('href') or r.get('url') or '')
    except Exception: pass
    time.sleep(.8)

def main():
 rows=[]; seed_moh(rows); seed_ialp(rows); web_discovery(rows)
 df=pd.DataFrame(rows)
 if df.empty: raise SystemExit('No targets discovered')
 df=df.drop_duplicates(subset=['name','category']).sort_values(['category','name'])
 old=Path('targets.csv')
 if old.exists():
  try:
   prev=pd.read_csv(old).fillna(''); df=pd.concat([prev,df],ignore_index=True).drop_duplicates(subset=['name','category'])
  except Exception: pass
 df.to_csv('targets.csv',index=False,encoding='utf-8-sig')
 print(f'Targets: {len(df)}')
if __name__=='__main__': main()
