from __future__ import annotations
import io,re,time,json
from pathlib import Path
from urllib.parse import urljoin,urlparse
import pandas as pd
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

UA={'User-Agent':'Mozilla/5.0 (compatible; ProfessionalContactResearch/3.0)'}
MOH='https://data.gov.il/he/datasets/ministry-health/database-of-doctors-licenses-moh'
IALP='https://ialp.org.il/counselors/'
IMA='https://www.ima.org.il/doctorsindex/results.aspx?spid=20&page={page}'
DISCOVERY={
'doula':['דולה ישראל','אינדקס דולות ישראל'], 'midwife':['מיילדת עצמאית ישראל','מיילדת פרטית ישראל'],
'childbirth_educator':['מדריכת הכנה ללידה ישראל','קורס הכנה ללידה מדריכה'], 'birth_center':['מרכז לידה ישראל','מרכז הריון ולידה'],
'fertility_doctor':['רופא פוריות IVF ישראל','מומחה פריון ישראל'], 'ivf_unit':['יחידת IVF בית חולים ישראל'],
'fertility_center':['מרכז פוריות פרטי ישראל'], 'embryologist':['אמבריולוגית IVF ישראל','אמבריולוג ישראל'],
'fertility_nurse':['אחות פוריות IVF ישראל'], 'fertility_consultant':['יועצת פוריות ישראל'], 'sperm_bank':['בנק זרע ישראל'],
'fertility_preservation':['מרכז שימור פוריות ישראל'], 'fertility_association':['עמותת פוריות ישראל'],
'pelvic_floor':['פיזיותרפיסטית רצפת אגן הריון ישראל','פיזיותרפיה רצפת אגן נשים ישראל'], 'sleep_consultant':['יועצת שינה תינוקות ישראל'],
'pregnancy_dietitian':['דיאטנית הריון פוריות ישראל','דיאטנית אחרי לידה ישראל'], 'parenting_center':['מרכז הורות תינוקות ישראל'],
'perinatal_mental_health':['פסיכולוגית הריון לידה פוריות ישראל'], 'facebook_group_admin':['קבוצת פייסבוק הריון לידה ישראל','קבוצת פייסבוק IVF פוריות ישראל'],
'community_manager':['קהילת הריון לידה ישראל','קהילת פוריות ישראל'], 'instagram_creator':['אינסטגרם הריון לידה ישראל','אינסטגרם פוריות ישראל'],
'parenting_site':['אתר הורות הריון לידה ישראל'], 'pregnancy_podcast':['פודקאסט הריון לידה פוריות ישראל'],
'doula_school':['בית ספר לדולות ישראל','קורס דולות ישראל'], 'childbirth_school':['קורס מדריכות הכנה ללידה ישראל'],
'women_health_creator':['בלוג בריאות האישה הריון לידה ישראל','יוצרת תוכן בריאות האישה ישראל']}
# Seed organizations guarantee category coverage; web discovery expands each category beyond these seeds.
KNOWN={
'ivf_unit':['יחידת IVF שיבא','יחידת IVF איכילוב','יחידת IVF הדסה','יחידת IVF רמבם','יחידת IVF סורוקה'],
'sperm_bank':['בנק הזרע שיבא','בנק הזרע איכילוב','בנק הזרע הדסה','בנק הזרע רמבם'],
'fertility_association':['איילת השחר פוריות','עמותת חן לפריון'],
'birth_center':['מרכז לידה טבעית שיבא','מרכז לידה טבעית איכילוב'],
'parenting_site':['יולדת','מאקו הורים','דוקטורס נשים'],
'doula_school':['אמאלדת','ללדת בית ספר למקצועות הלידה'],
'childbirth_school':['קורס הכנה ללידה שיבא','קורס הכנה ללידה איכילוב']}
BAD_TITLE=('wikipedia','ויקיפדיה','חדשות','כתבה','מאמר','מדריך','מחיר','דרושים','login','sign in')
def clean_name(s):
 s=re.sub(r'\s+',' ',str(s or '')).strip(' |-–—:');return s[:160]
def add(rows,name,cat,source=''):
 name=clean_name(name)
 if 3<=len(name)<=160:rows.append({'name':name,'category':cat,'seed_source':source})
def entity_title(title):
 t=clean_name(title)
 for sep in [' | ',' - ',' – ',' — ',':']:
  if sep in t:t=t.split(sep)[0].strip()
 if not t or any(x in t.lower() for x in BAD_TITLE) or len(t.split())>12:return ''
 return t

def seed_moh(rows):
 try:
  soup=BeautifulSoup(requests.get(MOH,headers=UA,timeout=30).text,'html.parser');links=[]
  for a in soup.find_all('a',href=True):
   h=urljoin(MOH,a['href']);low=h.lower()
   if '.csv' in low or 'resource' in low or 'download' in low:links.append(h)
  for u in dict.fromkeys(links):
   try:
    r=requests.get(u,headers=UA,timeout=60)
    if r.status_code!=200:continue
    df=None
    for enc in ['utf-8-sig','utf-8','cp1255']:
     try:df=pd.read_csv(io.BytesIO(r.content),encoding=enc);break
     except Exception:pass
    if df is None or df.empty:continue
    spec=next((c for c in df.columns if 'התמחות' in str(c) or 'special' in str(c).lower()),None)
    first=next((c for c in df.columns if 'פרטי' in str(c) or 'first' in str(c).lower()),None);last=next((c for c in df.columns if 'משפחה' in str(c) or 'last' in str(c).lower()),None)
    full=next((c for c in df.columns if 'שם' in str(c) and ('מלא' in str(c) or 'full' in str(c).lower())),None)
    if spec:
     g=df[df[spec].astype(str).str.contains('יילוד|גינקולוג|obstet|gynec',case=False,na=False)]
     for _,x in g.iterrows():add(rows,str(x[full]) if full else f"{x[first]} {x[last]}" if first and last else '','gynecologist',u)
     if len(g)>100:return len(g)
   except Exception:pass
 except Exception:pass
 return 0

def seed_ima(rows):
 seen=set();empty=0
 for page in range(1,30):
  url=IMA.format(page=page)
  try:
   soup=BeautifulSoup(requests.get(url,headers=UA,timeout=30).text,'html.parser');before=len(seen)
   for a in soup.find_all('a',href=True):
    href=a.get('href','');txt=clean_name(a.get_text(' ',strip=True))
    if 'doctorprofile' in href.lower() and 3<=len(txt)<=100:seen.add(txt);add(rows,txt,'gynecologist',url)
   empty=empty+1 if len(seen)==before else 0
   if empty>=2 and page>5:break
  except Exception:empty+=1
 return len(seen)
def seed_ialp(rows):
 try:
  soup=BeautifulSoup(requests.get(IALP,headers=UA,timeout=30).text,'html.parser')
  for a in soup.find_all('a',href=True):
   href=urljoin(IALP,a['href']);txt=clean_name(a.get_text(' ',strip=True))
   if urlparse(href).netloc==urlparse(IALP).netloc and ('counselor' in href.lower() or '/יוע' in href) and txt:add(rows,txt.split(' – ')[0],'lactation',href)
  for h in soup.find_all(['h2','h3','h4']):
   n=clean_name(h.get_text(' ',strip=True))
   if n and not any(x in n for x in ['חיפוש','יועצות','Archive']):add(rows,n.split(' – ')[0],'lactation',IALP)
 except Exception:pass

def web_discovery(rows):
 stats={};d=DDGS()
 for cat,queries in DISCOVERY.items():
  before=len(rows);errors=[]
  for q in queries:
   try:
    results=d.text(q,region='il-he',safesearch='moderate',max_results=30) or []
    for r in results:
     title=entity_title(r.get('title',''));source=r.get('href') or r.get('url') or ''
     if title:add(rows,title,cat,source)
   except Exception as e:errors.append(type(e).__name__+': '+str(e)[:120])
   time.sleep(.25)
  stats[cat]={'added_raw':len(rows)-before,'errors':errors}
 return stats

def main():
 rows=[]
 for cat,names in KNOWN.items():
  for n in names:add(rows,n,cat,'curated_seed')
 moh=seed_moh(rows);ima=seed_ima(rows);seed_ialp(rows);discovery=web_discovery(rows)
 df=pd.DataFrame(rows)
 if df.empty:raise SystemExit('No targets discovered')
 df=df.drop_duplicates(subset=['name','category']).sort_values(['category','name'])
 # Do not merge old targets blindly: each run rebuilds the universe so stale/bad categories cannot mask discovery failures.
 df.to_csv('targets.csv',index=False,encoding='utf-8-sig')
 counts=df.category.value_counts().to_dict();failed=[c for c,v in discovery.items() if v['added_raw']==0 and c not in KNOWN]
 summary={'total':len(df),'moh_gynecology':moh,'ima_gynecology':ima,'categories':counts,'discovery':discovery,'zero_result_categories':failed}
 Path('seed_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 print(f'Targets: {len(df)} | MOH gyn: {moh} | IMA gyn: {ima} | category_count: {len(counts)} | counts: {counts}')
 print('Zero-result non-curated categories:',failed)
 if counts.get('gynecologist',0)<300:raise SystemExit('Safety stop: fewer than 300 gynecologists discovered')
 # Require broad live discovery, not merely category labels from curated seeds.
 live=[c for c,v in counts.items() if c not in {'gynecologist','lactation'} and any(x['category']==c and x['seed_source']!='curated_seed' for x in rows)]
 if len(live)<12:raise SystemExit(f'Safety stop: live discovery covered only {len(live)} additional categories')
if __name__=='__main__':main()
