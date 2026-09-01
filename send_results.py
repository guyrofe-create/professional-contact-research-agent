from __future__ import annotations
import json,os,smtplib
from email.message import EmailMessage
from pathlib import Path
import pandas as pd
import agent

def main():
 targets=Path('targets.csv'); checkpoint=Path('output/checkpoint.jsonl')
 if not targets.exists() or not checkpoint.exists(): return
 total=len(pd.read_csv(targets))
 latest={}
 for line in checkpoint.read_text(encoding='utf-8').splitlines():
  try:
   r=json.loads(line)
   if r.get('algo_version')==agent.ALGO_VERSION:
    latest[(r.get('name',''),r.get('category',''))]=r
  except Exception: pass
 done={key for key,row in latest.items() if not str(row.get('status','')).startswith('PENDING')}
 complete_file=Path('output/COMPLETE.txt')
 if len(done)<total or not complete_file.exists() or not complete_file.read_text(encoding='utf-8',errors='ignore').startswith('COMPLETE'):
  print(f'Not complete: {len(done)}/{total}. No final email yet.'); return
 marker=Path('output/final_email_sent.txt')
 if marker.exists(): print('Final email already sent.'); return
 host=os.getenv('SMTP_HOST');port=int(os.getenv('SMTP_PORT') or '587');user=os.getenv('SMTP_USER');password=os.getenv('SMTP_PASSWORD');to=os.getenv('RESULT_EMAIL')
 if not all([host,user,password,to]): print('Complete, but email secrets are not configured.'); return
 summary=Path('output/summary.json').read_text(encoding='utf-8') if Path('output/summary.json').exists() else ''
 msg=EmailMessage();msg['Subject']='מאגר אנשי קשר מקצועיים - המחקר הושלם';msg['From']=user;msg['To']=to
 msg.set_content(f'הסוכן השלים {len(done)}/{total} יעדים. מצורפים קובצי התוצאות.\n\n'+summary)
 for fn in ['output/contacts.xlsx','output/audit.xlsx']:
  p=Path(fn)
  if p.exists():msg.add_attachment(p.read_bytes(),maintype='application',subtype='vnd.openxmlformats-officedocument.spreadsheetml.sheet',filename=p.name)
 with smtplib.SMTP(host,port,timeout=30) as s:
  s.starttls();s.login(user,password);s.send_message(msg)
 marker.write_text('sent',encoding='utf-8');print('Final results emailed.')
if __name__=='__main__':main()
