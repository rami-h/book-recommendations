# ממליץ הספרים של ספריית שחרות

אפליקציית אינטרנט קלילה שנותנת המלצות ספרים מותאמות אישית, בעברית, לקהילת ספריית שחרות.

## איך זה עובד?

1. המשתמש מזין 1-5 ספרים שאהב
2. המערכת מזהה את הספרים ובונה "פרופיל טעם"
3. המערכת מחפשת ספרים עם מאפיינים דומים
4. המשתמש מקבל 5-10 המלצות עם הסבר לכל אחת

## הפעלה מהירה

### האפשרות הפשוטה ביותר
פשוט פתחו את `index.html` בדפדפן.

> **שימו לב:** הקבצים עובדים ישירות מהדיסק (file://) כי הנתונים נטענים כקבצי JavaScript ולא כ-JSON, כך שאין בעיות אבטחה של הדפדפן.

### הפעלה עם שרת מקומי (אופציונלי)
אם יש לכם Python מותקן:
```bash
cd library
python -m http.server 8000
```
ואז פתחו בדפדפן: http://localhost:8000

## מבנה הקבצים

```
library/
├── index.html                    ← הדף הראשי
├── styles.css                    ← עיצוב
├── app.js                        ← מנוע ההמלצות והממשק
├── print.css                     ← עיצוב להדפסה
├── data/
│   ├── general_catalog.js        ← קטלוג כללי (~100 ספרים)
│   └── local_library.js          ← קטלוג ספריית שחרות (~40 ספרים)
├── assets/
│   └── logo-placeholder.svg      ← לוגו
└── README.md                     ← הקובץ הזה
```

## עריכת קטלוג הספרייה

### עריכה ידנית
1. פתחו את `data/local_library.js` בעורך טקסט (Notepad, VS Code וכו')
2. כל ספר הוא בלוק בתוך סוגריים מסולסלים `{ }`
3. הוסיפו/ערכו/מחקו ספרים
4. שמרו את הקובץ

### שדות חובה לכל ספר
| שדה | תיאור | דוגמה |
|------|--------|--------|
| id | מזהה ייחודי | "lib041" |
| title | שם הספר | "הנסיך הקטן" |
| author | מחבר/ת | "אנטואן דה סנט-אכזופרי" |
| genres | ז'אנרים | ["ספרות יפה", "פנטזיה"] |

### שדות מומלצים
| שדה | תיאור | ערכים לדוגמה |
|------|--------|--------------|
| themes | נושאים | ["אהבה", "מסע", "זהות"] |
| mood | אווירה | ["חם", "מתוח", "פילוסופי"] |
| style | סגנון | ["פואטי", "קולח", "מורכב"] |
| audience | קהל | ["מבוגרים", "צעירים", "כל הגילים"] |
| language | שפת מקור | "עברית" / "אנגלית" / "צרפתית" |
| era | תקופה | "קלאסי" / "מודרני" / "בן-זמננו" |
| description | תיאור קצר | "סיפור על..." |
| similar_to | ספרים דומים | ["lib001", "lib005"] |
| library_notes | הערות ספרנית | "3 עותקים" |
| shelf | מיקום במדף | "ספרות עברית א-ד" |

### ייבוא מגיליון אלקטרוני (Excel / Google Sheets)

1. צרו גיליון עם עמודות לכל שדה
2. מערכים (genres, themes וכו') - כתבו עם פסיקים: `ספרות יפה, פנטזיה`
3. ייצאו ל-CSV
4. השתמשו בסקריפט ההמרה הבא (דורש Python):

```python
import csv
import json

books = []
with open('library.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        book = {
            'id': row['id'],
            'title': row['title'],
            'author': row['author'],
            'genres': [x.strip() for x in row.get('genres', '').split(',') if x.strip()],
            'themes': [x.strip() for x in row.get('themes', '').split(',') if x.strip()],
            'mood': [x.strip() for x in row.get('mood', '').split(',') if x.strip()],
            'style': [x.strip() for x in row.get('style', '').split(',') if x.strip()],
            'audience': [x.strip() for x in row.get('audience', '').split(',') if x.strip()],
            'language': row.get('language', ''),
            'era': row.get('era', ''),
            'description': row.get('description', ''),
            'similar_to': [x.strip() for x in row.get('similar_to', '').split(',') if x.strip()],
            'library_notes': row.get('library_notes', ''),
            'shelf': row.get('shelf', '')
        }
        books.append(book)

# שמירה כקובץ JS
with open('data/local_library.js', 'w', encoding='utf-8') as f:
    f.write('var LOCAL_LIBRARY = ')
    json.dump(books, f, ensure_ascii=False, indent=2)
    f.write(';\\n')

print(f'הומרו {len(books)} ספרים בהצלחה!')
```

## העלאה לאינטרנט

### GitHub Pages (מומלץ - חינם ופשוט)
1. צרו חשבון ב-github.com
2. צרו repository חדש (למשל: `library-recommender`)
3. העלו את כל הקבצים
4. Settings → Pages → Source: main branch
5. האתר יהיה זמין בכתובת: `https://USERNAME.github.io/library-recommender`

### Netlify (חינם, גרירה ושחרור)
1. היכנסו ל-netlify.com
2. גררו את תיקיית הפרויקט לאזור ההעלאה
3. האתר מוכן תוך שניות

### שרת סטטי כלשהו
כל שרת שיכול להגיש קבצי HTML סטטיים יעבוד - אין צורך בשרת צד-שרת.

## איך עובד מנוע ההמלצות?

ראו את הסעיף "STEP 4" בתיעוד המלא בסוף קובץ זה.

---

*נבנה באהבה לקהילת ספריית שחרות*
