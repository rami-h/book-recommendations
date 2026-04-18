#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
classify_genres.py — מסווג ז'אנרים ותת-ז'אנרים לקטלוג local_library.js
על בסיס מילות מפתח בתקציר, כותרת, מחבר וז'אנר קיים.
"""
import sys, io, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

JS_PATH = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\local_library.js'

# ══════════════════════════════════════════════
# טבלאות סיווג
# ══════════════════════════════════════════════

# תת-ז'אנרים: {שם: [רשימת_מילות_מפתח]}
# מסודר לפי עדיפות — ראשון שמתאים מנצח
SUBGENRE_RULES = [
    # --- ספציפי מאוד קודם ---
    ('שואה', [
        'שואה', 'נאצ', 'היטלר', 'אושוויץ', 'מחנה ריכוז', 'מחנות ריכוז',
        'גטו', 'יהודים באירופה', 'מלחמת העולם השנייה', 'ניצול שואה',
        'כבוש גרמני', 'מחתרת יהודית'
    ]),
    ('מלחמה', [
        'מלחמה', 'חייל', 'חיילים', 'קרב', 'עצמאות', 'מלחמת', 'כוחות',
        'מערכה', 'קרבות', 'גנרל', 'אדמירל', 'שדה הקרב'
    ]),
    ('בלשי ופשע', [
        'בלש', 'בלשי', 'פשע', 'רצח', 'רוצח', 'חקירה', 'גופה',
        'משטרה', 'חוקר', 'עדות', 'עדים', 'עד', 'ראיות', 'חשוד',
        'detective', 'murder', 'crime'
    ]),
    ('מותחן', [
        'מותחן', 'מתח', 'ריגול', 'סוכן', 'ביון', 'מוסד', 'שב"כ',
        'אמן', 'טרור', 'פצצה', 'מרדף', 'איום', 'משימה סודית',
        'thriller', 'spy', 'conspiracy'
    ]),
    ('אימה', [
        'אימה', 'בלהות', 'רוח רפאים', 'רפאים', 'שדים', 'שד ', 'מפחיד',
        'קאלט', 'קאנט', 'vampire', 'horror', 'terror'
    ]),
    ('פנטזיה', [
        'פנטזיה', 'קסם', 'כישוף', 'מכשפה', 'מכשף', 'קוסם', 'דרקון',
        'אלפים', 'גמדים', 'עולם קסום', 'ממלכת', 'חרב קסומה',
        'fantasy', 'magic', 'wizard', 'dragon'
    ]),
    ('מדע בדיוני', [
        'מדע בדיוני', 'חלל', 'כוכב לכת', 'רובוט', 'חייזר', 'עתיד',
        'ספינת חלל', 'טכנולוגיה עתידית', 'science fiction', 'sci-fi',
        'dystopia', 'דיסטופ'
    ]),
    ('רומנטי', [
        'אהבה', 'התאהב', 'התאהבה', 'רומן', 'זוגיות', 'מאהב', 'מאהבת',
        'לב שבור', 'חתונה', 'יחסים רומנטיים', 'romance', 'love story'
    ]),
    ('היסטורי', [
        'היסטורי', 'תקופת', 'המאה ה', 'בעת העתיקה', 'ימי הביניים',
        'רומא', 'יוון', 'מצרים העתיקה', 'אימפריה', 'ממלכה', 'פרעה',
        'קיסר', 'historical', 'ancient'
    ]),
    ('ביוגרפיה ואוטוביוגרפיה', [
        'אוטוביוגרפיה', 'ביוגרפיה', 'חייו של', 'חייה של', 'יומן',
        'זיכרונות', 'מזכרות', 'biography', 'memoir', 'autobiography'
    ]),
    ('ספרות ישראלית', [
        'ישראלי', 'ישראלית', 'תל אביב', 'ירושלים', 'חיפה', 'קיבוץ',
        'עיר ישראלית', 'החברה הישראלית', 'ישראל'
    ]),
    ('פסיכולוגי', [
        'פסיכולוג', 'נפש', 'טראומה', 'נפשי', 'תת-מודע', 'חרדה',
        'דיכאון', 'פסיכיאטר', 'מחלת נפש', 'mental', 'psychological'
    ]),
    ('מסע והרפתקה', [
        'מסע', 'הרפתקה', 'הרפתקאות', 'טיול', 'יומן מסע', 'גיבור עולה',
        'adventure', 'journey', 'quest', 'expedition'
    ]),
    ('שירה', [
        'שירה', 'שיר', 'שירים', 'poetry', 'poem', 'poems', 'פואמה'
    ]),
    ('דרמה', [
        'מחזה', 'תיאטרון', 'דרמה', 'סצינה', 'מערכה', 'acts', 'play', 'drama'
    ]),
    ('הומור וסאטירה', [
        'הומור', 'סאטירה', 'קומדיה', 'מצחיק', 'בדיחה', 'אירוניה',
        'humor', 'comedy', 'satire', 'parody'
    ]),
    ('גרפי / קומיקס', [
        'קומיקס', 'גרפי', 'מאנגה', 'cartoon', 'graphic novel', 'comic'
    ]),
    ('עיון ופילוסופיה', [
        'פילוסופ', 'פילוסופיה', 'מאמר', 'עיון', 'תיאוריה', 'אקדמי',
        'מחקר', 'philosophy', 'academic'
    ]),
    ('דת ורוחניות', [
        'תורה', 'הלכה', 'מצוות', 'ספר קודש', 'תלמוד', 'מדרש',
        'קבלה', 'חסידות', 'אמונה', 'רוחני', 'spiritual', 'religion'
    ]),
    ('בישול ואוכל', [
        'מתכון', 'בישול', 'אפייה', 'מטבח', 'recipe', 'cooking', 'chef'
    ]),
    ('עסקים ופיתוח עצמי', [
        'עסקים', 'מנהיגות', 'הצלחה', 'פיתוח עצמי', 'קריירה',
        'כלכלה', 'ניהול', 'יזמות', 'business', 'leadership', 'success'
    ]),
    ('מדע וטכנולוגיה', [
        'מדע', 'מדעי', 'ביולוגיה', 'פיזיקה', 'כימיה', 'מתמטיקה',
        'טכנולוגיה', 'science', 'technology'
    ]),
]

# ז'אנרים ראשיים — מיפוי מ-sub_genre
GENRE_FROM_SUB = {
    'שואה':                   'ספרות יפה',
    'מלחמה':                  'ספרות יפה',
    'בלשי ופשע':              'בלשי',
    'מותחן':                  'מותחן',
    'אימה':                   'ספרות יפה',
    'פנטזיה':                 'פנטזיה',
    'מדע בדיוני':             'מדע בדיוני',
    'רומנטי':                 'רומנטי',
    'היסטורי':                'רומן היסטורי',
    'ביוגרפיה ואוטוביוגרפיה': 'ביוגרפיה',
    'ספרות ישראלית':          'ספרות יפה',
    'פסיכולוגי':              'ספרות יפה',
    'מסע והרפתקה':            'ספרות יפה',
    'שירה':                   'שירה',
    'דרמה':                   'דרמה',
    'הומור וסאטירה':          'ספרות יפה',
    'גרפי / קומיקס':          'קומיקס',
    'עיון ופילוסופיה':        'עיון',
    'דת ורוחניות':            'עיון',
    'בישול ואוכל':            'עיון',
    'עסקים ופיתוח עצמי':     'עיון',
    'מדע וטכנולוגיה':        'עיון',
}

# ז'אנר ראשי מ-existing genres
GENRE_NORMALIZE = {
    'ספרות יפה': 'ספרות יפה',
    'ילדים ונוער': 'ילדים ונוער',
    'ילדים': 'ילדים ונוער',
    'נוער': 'ילדים ונוער',
    'עיון': 'עיון',
    'רומן היסטורי': 'רומן היסטורי',
    'פנטזיה': 'פנטזיה',
    'מותחן': 'מותחן',
    'רומנטי': 'רומנטי',
    'קומיקס': 'קומיקס',
    'סיפורים קצרים': 'סיפורים קצרים',
    'שירה': 'שירה',
    'דרמה': 'דרמה',
    'ביוגרפיה': 'ביוגרפיה',
    'בלשי': 'בלשי',
    'מדע בדיוני': 'מדע בדיוני',
    'ספר קולי': 'ספר קולי',
}

# תת-ז'אנרים ל-ילדים ונוער לפי גיל/תוכן
CHILDREN_SUB_RULES = [
    ('תמונות ומילים',   ['מילים ראשונות', 'לתינוק', 'ספר תמונות', 'מחברת צביעה']),
    ('גן ילדים',        ['גן', 'גן חובה', 'לגיל גן', 'לפעוטות']),
    ('ראשית קריאה',     ['ראשית קריאה', 'קוראים לבד', 'קריאה עצמאית', 'כיתה א', "כיתה א'"]),
    ('ספרות ילדים',     ['ילדים', 'ילד', 'ילדה', 'ג\\u0027וחה', "ספרי ילדים"]),
    ('נוער',            ['נוער', 'נערה', 'נער', 'תיכון', 'young adult', 'ya ']),
    ('ספרות ילדים',     []),  # fallback
]


def text_for_classification(book):
    """מאגד את כל הטקסט הרלוונטי לסיווג."""
    parts = [
        book.get('title', ''),
        book.get('author', ''),
        book.get('description', ''),
        ' '.join(book.get('genres', [])),
        book.get('sub_genre', ''),
    ]
    return ' '.join(p for p in parts if p).lower()


def detect_subgenre(text, existing_genres):
    """מחזיר תת-ז'אנר על בסיס מילות מפתח."""
    # אם כבר יש תת-ז'אנר — שמור
    # (נקרא רק לספרים ללא תת-ז'אנר)

    # לילדים ונוער — כללים ייחודיים
    if any(g in ['ילדים ונוער', 'ילדים', 'נוער'] for g in existing_genres):
        for sub, kws in CHILDREN_SUB_RULES:
            if not kws or any(kw.lower() in text for kw in kws):
                return sub
        return 'ספרות ילדים'

    # כללים כלליים
    for sub, kws in SUBGENRE_RULES:
        if any(kw.lower() in text for kw in kws):
            return sub

    # fallback לפי ז'אנר קיים
    if 'שירה' in existing_genres: return 'שירה'
    if 'דרמה' in existing_genres: return 'דרמה'
    if 'קומיקס' in existing_genres: return 'קומיקס'
    if 'ביוגרפיה' in existing_genres: return 'ביוגרפיה'
    if 'מדע בדיוני' in existing_genres: return 'מדע בדיוני'
    if 'מותחן' in existing_genres: return 'מותחן'
    if 'בלשי' in existing_genres: return 'בלשי ופשע'
    if 'רומנטי' in existing_genres: return 'רומנטי'
    if 'פנטזיה' in existing_genres: return 'פנטזיה'
    if 'עיון' in existing_genres: return 'עיון'
    if 'רומן היסטורי' in existing_genres: return 'היסטורי'
    if 'סיפורים קצרים' in existing_genres: return 'סיפורים קצרים'

    # אין מספיק מידע
    return None


def classify_book(book):
    """מחזיר (genres_new, sub_genre_new) או None לכל שדה שלא השתנה."""
    genres = list(book.get('genres') or [])
    sub = book.get('sub_genre', '').strip()

    # נרמול genres קיימים
    genres_norm = []
    for g in genres:
        g = g.strip()
        genres_norm.append(GENRE_NORMALIZE.get(g, g))
    genres = genres_norm

    text = text_for_classification(book)

    # זיהוי תת-ז'אנר אם חסר
    new_sub = sub
    if not sub:
        detected = detect_subgenre(text, genres)
        if detected:
            new_sub = detected

    # עדכון ז'אנר ראשי אם חסר
    new_genres = genres
    if not genres and new_sub:
        mapped = GENRE_FROM_SUB.get(new_sub)
        if mapped:
            new_genres = [mapped]
    elif not genres:
        # ניסיון סיווג בסיסי
        if any(kw in text for kw in ['ילד', 'ילדה', 'נוער', 'גן ']):
            new_genres = ['ילדים ונוער']
        elif any(kw in text for kw in ['שיר', 'שירה']):
            new_genres = ['שירה']
        elif any(kw in text for kw in ['מחזה', 'תיאטרון']):
            new_genres = ['דרמה']
        elif any(kw in text for kw in ['קומיקס', 'מנגה']):
            new_genres = ['קומיקס']

    return new_genres, new_sub


# ══════════════════════════════════════════════
# ראשי
# ══════════════════════════════════════════════
def main():
    print('טוען קטלוג...')
    with open(JS_PATH, encoding='utf-8') as f:
        content = f.read()
    start = content.index('[')
    end = content.rindex(']') + 1
    books = json.loads(content[start:end])
    print(f'  {len(books)} ספרים')

    genres_updated = 0
    sub_updated = 0
    both_updated = 0

    for book in books:
        old_genres = list(book.get('genres') or [])
        old_sub    = book.get('sub_genre', '').strip()

        new_genres, new_sub = classify_book(book)

        changed = False
        if new_genres != old_genres:
            book['genres'] = new_genres
            genres_updated += 1
            changed = True
        if new_sub != old_sub:
            book['sub_genre'] = new_sub
            sub_updated += 1
            changed = True
        if changed and new_genres != old_genres and new_sub != old_sub:
            both_updated += 1

    # סיכום
    total = len(books)
    with_genres = sum(1 for b in books if b.get('genres'))
    with_sub    = sum(1 for b in books if b.get('sub_genre', '').strip())
    print(f'\nעדכונים:')
    print(f'  genres עודכן:   {genres_updated}')
    print(f'  sub_genre עודכן: {sub_updated}')
    print(f'\nכיסוי חדש:')
    print(f'  genres:    {with_genres}/{total} ({100*with_genres//total}%)')
    print(f'  sub_genre: {with_sub}/{total} ({100*with_sub//total}%)')

    # שמירה
    print('\nשומר...')
    prefix = content[:start]
    suffix = content[end:]
    new_content = prefix + json.dumps(books, ensure_ascii=False, indent=2) + suffix
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('נשמר בהצלחה ✓')

    # פירוט תת-ז'אנרים
    subs = {}
    for b in books:
        s = b.get('sub_genre', '').strip()
        if s: subs[s] = subs.get(s, 0) + 1
    print(f'\nתת-ז\'אנרים ({len(subs)} ייחודיים):')
    for s, cnt in sorted(subs.items(), key=lambda x: -x[1]):
        print(f'  {s}: {cnt}')


if __name__ == '__main__':
    main()
