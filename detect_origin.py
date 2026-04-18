#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
detect_origin.py
================
מזהה ארץ מוצא ספרותית לכל ספר לפי שם המחבר, באמצעות Claude Haiku.
מוסיף שדה `origin` לכל ספר ב-local_library_adults.js.

שימוש:
    set ANTHROPIC_API_KEY=sk-ant-...
    py -3 detect_origin.py            # ריצה מלאה
    py -3 detect_origin.py --test     # 50 מחברים ראשונים
    py -3 detect_origin.py --resume   # המשך מ-checkpoint
    py -3 detect_origin.py --apply    # החל תוצאות שמורות על הקובץ
"""

import json, re, sys, io, time, os, argparse, anthropic
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

LIB_PATH  = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\local_library_adults.js'
CKPT_PATH = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\origin_checkpoint.jsonl'
OUT_PATH  = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\origin_detected.json'
LOG_PATH  = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\origin_log.txt'

MODEL      = 'claude-haiku-4-5'
BATCH_SIZE = 60    # מחברים לכל קריאה — שאלת עובדה, לא ניתוח
MAX_TOKENS = 2000
RETRY_WAIT = 8

# ערכים חוקיים בלבד — מונע המצאות
VALID_ORIGINS = {
    'ישראלית', 'רוסית', 'יפנית', 'צרפתית', 'בריטית', 'אמריקאית',
    'סקנדינבית', 'גרמנית', 'איטלקית', 'ספרדית', 'לטינו-אמריקאית',
    'פורטוגזית', 'ערבית', 'אחר'
}

SYSTEM_PROMPT = """אתה מומחה לספרות עולמית. תפקידך לזהות את ארץ המוצא הספרותית של מחברים לפי שמם.

ערכים מותרים בלבד (החזר בדיוק אחד מהם לכל מחבר):
ישראלית | רוסית | יפנית | צרפתית | בריטית | אמריקאית | סקנדינבית | גרמנית | איטלקית | ספרדית | לטינו-אמריקאית | פורטוגזית | ערבית | אחר

כללים:
- "ישראלית" = ישראלים וסופרים יהודים שכתבו עברית כשפה ראשונה
- "סקנדינבית" = שוודים, נורווגים, דנים, פינים, איסלנדים
- "לטינו-אמריקאית" = ארגנטינה, קולומביה, מקסיקו, ברזיל (לא ספרד/פורטוגל)
- "בריטית" = אנגלים, סקוטים, אירים
- "אחר" = כל מה שלא ברשימה (הונגרי, פולני, טורקי, סיני וכו')
- אם ספר עברי כתב על נושא זר — הוא עדיין "ישראלית"
- לא לנחש: אם שם המחבר לא ידוע לך — "אחר"

פורמט תשובה — JSON בלבד, מערך עם אובייקט לכל מחבר:
[{"author": "שם המחבר", "origin": "ערך מהרשימה"}]"""


def log(msg):
    print(msg, flush=True)
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(msg + '\n')


def load_library():
    with open(LIB_PATH, encoding='utf-8-sig') as f:
        content = f.read()
    m = re.search(r'var LOCAL_LIBRARY\s*=\s*(\[.*\])\s*;', content, re.DOTALL)
    books = json.loads(m.group(1))
    prefix = content[:m.start(1)]
    suffix = content[m.end(1):]
    return books, prefix, suffix


def save_library(books, prefix, suffix):
    with open(LIB_PATH, 'w', encoding='utf-8') as f:
        f.write(prefix)
        f.write(json.dumps(books, ensure_ascii=False, indent=2))
        f.write(suffix)


def load_checkpoint():
    done = {}
    if not os.path.exists(CKPT_PATH):
        return done
    with open(CKPT_PATH, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    e = json.loads(line)
                    done[e['author']] = e['origin']
                except Exception:
                    pass
    return done


def append_checkpoint(author, origin):
    with open(CKPT_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'author': author, 'origin': origin},
                           ensure_ascii=False) + '\n')


def call_api(client, authors, author_titles=None):
    """שולח רשימת מחברים (+ כותרת לדוגמה), מקבל origin לכל אחד."""
    entries = []
    for a in authors:
        entry = {'author': a}
        if author_titles and a in author_titles:
            entry['sample_title'] = author_titles[a]
        entries.append(entry)
    user_msg = (
        f'זהה ארץ מוצא לכל אחד מ-{len(authors)} המחברים הבאים.\n'
        f'השמות הם תעתיק עברי בסדר משפחה-פרטי. כותרת הספר עוזרת לזיהוי.\n\n'
        + json.dumps(entries, ensure_ascii=False, indent=2)
    )

    for attempt in range(4):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{'role': 'user', 'content': user_msg}]
            )
            text = response.content[0].text.strip()
            json_match = re.search(r'\[.*\]', text, re.DOTALL)
            if not json_match:
                raise ValueError(f'לא נמצא JSON: {text[:100]}')
            results = json.loads(json_match.group(0))

            # בנה מילון author→origin, ווידוא ערכים חוקיים
            parsed = {}
            for item in results:
                author = item.get('author', '').strip()
                origin = item.get('origin', '').strip()
                if author and origin in VALID_ORIGINS:
                    parsed[author] = origin
                elif author and origin:
                    log(f'  ! ערך לא חוקי "{origin}" עבור {author} — מוחלף ב"אחר"')
                    parsed[author] = 'אחר'
            return parsed

        except anthropic.RateLimitError:
            wait = RETRY_WAIT * (attempt + 1)
            log(f'  Rate limit — ממתין {wait}ש...')
            time.sleep(wait)
        except Exception as e:
            log(f'  שגיאה (ניסיון {attempt+1}): {str(e)[:100]}')
            if attempt < 3:
                time.sleep(3)
    return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test',        action='store_true', help='50 מחברים ראשונים')
    parser.add_argument('--test-offset', type=int, default=0, help='דלג על N מחברים לפני test')
    parser.add_argument('--resume',      action='store_true', help='המשך מ-checkpoint')
    parser.add_argument('--apply',       action='store_true', help='החל origin_detected.json על הקובץ')
    args = parser.parse_args()

    books, prefix, suffix = load_library()
    by_id = {b['id']: b for b in books}

    # ── מצב Apply ──────────────────────────────────────────────────────────────
    if args.apply:
        if not os.path.exists(OUT_PATH):
            print('לא נמצא origin_detected.json')
            return

        with open(OUT_PATH, encoding='utf-8') as f:
            author_origins = json.load(f)

        updated = skipped = unknown = already_tagged = 0
        origin_counts = {}
        for book in books:
            author = (book.get('author') or '').strip()
            if not author:
                skipped += 1
                continue
            if 'origin' in book:
                # לא מדרסים נתונים שכבר קיימים (מסקריפט הסטטי)
                already_tagged += 1
                continue
            origin = author_origins.get(author)
            if origin:
                book['origin'] = origin
                origin_counts[origin] = origin_counts.get(origin, 0) + 1
                updated += 1
            else:
                unknown += 1

        save_library(books, prefix, suffix)

        print(f'\n✓ עודכנו: {updated} ספרים')
        print(f'  כבר מתויגים (לא שונו): {already_tagged}')
        print(f'  לא נמצא מחבר ב-API: {unknown}')
        print(f'  ללא שם מחבר: {skipped}')
        print('\nהתפלגות ארצות מוצא (חדשים בלבד):')
        for orig, cnt in sorted(origin_counts.items(), key=lambda x: -x[1]):
            print(f'  {cnt:4d}  {orig}')
        return

    # ── קריאת API ─────────────────────────────────────────────────────────────
    api_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if not api_key:
        api_key = input('Anthropic API key: ').strip()
    if not api_key:
        print('נדרש API key')
        sys.exit(1)
    client = anthropic.Anthropic(api_key=api_key)

    # אסוף רק מחברים של ספרים שעדיין חסר להם origin
    author_book_count = {}
    author_sample_title = {}   # מחבר → כותרת ספר לדוגמה לסיוע בזיהוי
    for b in books:
        if 'origin' not in b:
            a = (b.get('author') or '').strip()
            if a:
                author_book_count[a] = author_book_count.get(a, 0) + 1
                if a not in author_sample_title and b.get('title'):
                    author_sample_title[a] = b['title']

    # מיין לפי מספר ספרים (הכי הרבה קודם — כדי שכשל חלקי יפגע פחות)
    all_authors = sorted(author_book_count.keys(), key=lambda a: -author_book_count[a])
    log(f'מחברים ייחודיים ללא origin: {len(all_authors)}')
    log(f'  (הושמטו מחברים עם origin קיים מהסקריפט הסטטי)')

    log(f'10 מחברים בעלי הכי הרבה ספרים:')
    for a in all_authors[:10]:
        log(f'    {author_book_count[a]:2d} ספרים  {a}  ("{author_sample_title.get(a,"")}")')

    done = load_checkpoint() if args.resume else {}
    log(f'checkpoint: {len(done)} כבר עובדו')

    to_process = [a for a in all_authors if a not in done]
    if args.test:
        offset = args.test_offset
        to_process = to_process[offset: offset + 50]
    log(f'לעיבוד: {len(to_process)} מחברים\n')

    all_results = dict(done)  # מתחיל מה-checkpoint

    total_batches = (len(to_process) + BATCH_SIZE - 1) // BATCH_SIZE
    for batch_num, start in enumerate(range(0, len(to_process), BATCH_SIZE)):
        batch = to_process[start: start + BATCH_SIZE]
        log(f'[{batch_num+1}/{total_batches}] {len(batch)} מחברים...')

        results = call_api(client, batch, author_sample_title)

        # שמור תוצאות ו-checkpoint
        found = missed = 0
        for author in batch:
            origin = results.get(author, 'אחר')
            all_results[author] = origin
            append_checkpoint(author, origin)
            if origin != 'אחר':
                found += 1
            else:
                missed += 1

        log(f'  זוהו: {found}/{len(batch)}  |  "אחר": {missed}')

        # הדפסת דגימה
        for author in batch[:5]:
            log(f'    {author:35}  →  {all_results[author]}')

        time.sleep(0.5)

    # שמור JSON סופי
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    # סטטיסטיקה
    from collections import Counter
    counts = Counter(all_results.values())
    log(f'\n=== סיכום ===')
    log(f'סה"כ מחברים: {len(all_results)}')
    for orig, cnt in counts.most_common():
        log(f'  {cnt:4d}  {orig}')
    log(f'\nנשמר: {OUT_PATH}')
    log(f'שלב הבא: py -3 detect_origin.py --apply')


if __name__ == '__main__':
    main()
