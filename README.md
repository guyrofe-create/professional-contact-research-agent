# Professional Contact Research Agent

כלי לאיסוף שיטתי של כתובות מייל מקצועיות ופומביות בלבד עבור אנשי מקצוע וארגונים בתחום בריאות האישה, הריון, לידה ופוריות.

## קטגוריות
`gynecologist`, `fertility`, `doula`, `midwife`, `lactation`, `childbirth_educator`, `pelvic_floor`, `dietitian`, `mental_health`, `center`.

## קלט
CSV או XLSX עם לפחות שתי עמודות:

```csv
name,category
ישראל ישראלי,gynecologist
שרה כהן,doula
```

ניתן להוסיף עמודות אחרות. הן אינן חובה.

## התקנה והרצה

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python agent.py targets.csv --out output --resume
```

`--resume` גורם לכלי להמשיך מה-checkpoint ולא לבצע שוב אנשים שכבר נבדקו.

## פלט
* `output/audit.xlsx` - כל יעד שנבדק, כולל מי שלא נמצא עבורו מייל.
* `output/contacts.xlsx` - רק כתובות שנמצאו, לאחר הסרת כפילויות לפי מייל.
* `output/checkpoint.jsonl` - checkpoint לאחר כל אדם.
* `output/summary.json` - מספר יעדים, נמצאו, לא נמצאו ומיילים ייחודיים.

## כללי אימות
הכלי אינו מייצר או מנחש כתובות מייל. כתובת נשמרת רק אם היא הופיעה בפועל בדף ציבורי שנפתח במהלך המחקר. נשמר גם `source_url` שממנו הכתובת נשלפה. `confidence` הוא ציון התאמה בין האדם, הדף והמייל ואינו הוכחה לזהות בפני עצמו.

## תהליך החיפוש
לכל יעד מתבצעות מספר שאילתות חיפוש. הכלי פותח תוצאות רלוונטיות ומנסה גם עמודי contact/about/team/profile פנימיים. כך ניתן למצוא מייל גם כאשר לאדם אין אתר אישי, למשל באתר מרפאה, בית חולים, מוסד אקדמי או גוף מקצועי.

## הערה חשובה
יש להשתמש רק במידע מקצועי שפורסם לציבור ובכפוף לתנאי השימוש, robots.txt והדין החל. אין להשתמש בכלי לעקיפת login, CAPTCHA, הגנות אתר או מגבלות גישה.
