from __future__ import annotations
import os,smtplib
from email.message import EmailMessage
from pathlib import Path

def main():
 host=os.getenv('SMTP_HOST'); port=int(os.getenv('SMTP_PORT','587')); user=os.getenv('SMTP_USER'); password=os.getenv('SMTP_PASSWORD'); to=os.getenv('RESULT_EMAIL')
 if not all([host,user,password,to]):
  print('Email secrets not configured; GitHub artifact remains available.'); return
 summary=Path('output/summary.json').read_text(encoding='utf-8') if Path('output/summary.json').exists() else ''
 msg=EmailMessage(); msg['Subject']='מאגר אנשי קשר מקצועיים - המחקר הושלם'; msg['From']=user; msg['To']=to
 msg.set_content('הסוכן השלים את רשימת היעדים הנוכחית. מצורפים קובצי התוצאות.\n\n'+summary)
 for fn in ['output/contacts.xlsx','output/audit.xlsx']:
  p=Path(fn)
  if p.exists(): msg.add_attachment(p.read_bytes(),maintype='application',subtype='vnd.openxmlformats-officedocument.spreadsheetml.sheet',filename=p.name)
 with smtplib.SMTP(host,port,timeout=30) as s:
  s.starttls(); s.login(user,password); s.send_message(msg)
 print('Final results emailed.')
if __name__=='__main__': main()
