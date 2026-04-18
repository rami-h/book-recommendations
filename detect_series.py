#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
detect_series.py
================
מזהה סדרות עלילה בקטלוג באמצעות Claude Haiku.
אסטרטגיה: מקבץ לפי מחבר → שולח כל מחבר עם 2+ ספרים לבדיקה.

שימוש:
    set ANTHROPIC_API_KEY=sk-ant-...
    py -3 detect_series.py            # ריצה מלאה
    py -3 detect_series.py --test     # 30 מחברים ראשונים
    py -3 detect_series.py --resume   # המשך מ-checkpoint
    py -3 detect_series.py --apply    # החל תוצאות על הקובץ (אחרי בדיקה)
"""

import json, re, sys, io, time, os, argparse, anthropic
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

LIB_PATH  = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\local_library_adults.js'
CKPT_PATH = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\series_checkpoint.jsonl'
OUT_PATH  = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\series_detected.json'
LOG_PATH  = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\series_log.txt'

MODEL      = 'claude-haiku-4-5'
BATCH_SIZE = 30   # מחברים לכל קריאה
MAX_TOKENS = 2000
RETRY_WAIT = 8


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


def normalize_author(text):
    if not text:
        return ''
    return re.sub(r'\s+', ' ', text.strip().lower())


def load_checkpoint():
    done = set()
    if not os.path.exists(CKPT_PATH):
        return done
    with open(CKPT_PATH, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    done.add(json.loads(line)['author_key'])
                except Exception:
                    pass
    return done


def append_checkpoint(author_key, results):
    with open(CKPT_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'author_key': author_key, 'results': results},
                           ensure_ascii=False) + '\n')


SYSTEM_PROMPT = """אתה מומחה לספרות ומזהה סדרות ספרים (שרשרות עלילה).
תפקידך: מרשימת ספרים של מחבר אחד (או קבוצת מחברים), זהה אילו ספרים שייכים לאותה סדרת עלילה.

חוקים:
1. החזר רק סדרות עלילה אמיתיות — ספרים שממשיכים זה את זה או חולקים אותם דמויות/עולם.
2. אל תכלול סדרות הוצאה (Penguin, פרוזה, ספריה לעם) — רק סדרות שהמחבר כתב כסדרה.
3. שם הסדרה: שם המוכר בעברית. אם אין שם עברי מוכר — השתמש בשם הספר הראשון.
4. אם ספר עומד בפני עצמו — אל תכלול אותו.
5. אם אינך בטוח — אל תנחש. השמט.

פורמט תשובה — JSON בלבד:
[
  {"series_name": "שם הסדרה בעברית", "book_ids": ["id1", "id2", ...]},
  ...
]

אם אין סדרות → החזר: []"""


def call_api(client, author_books):
    """שולח קבוצת ספרים (של מחברים שונים) ומקבל זיהוי סדרות."""
    entries = [{'id': b['id'], 'title': b['title'], 'author': b.get('author', '')}
               for b in author_books]

    user_msg = (
        'זהה סדרות עלילה מהרשימה הבאה. '
        'כל ספר מזוהה ב-id.\n\n'
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
                return []
            results = json.loads(json_match.group(0))
            # וידוא מבנה
            validated = []
            for item in results:
                if item.get('series_name') and item.get('book_ids') and len(item['book_ids']) >= 2:
                    validated.append(item)
            return validated

        except anthropic.RateLimitError:
            wait = RETRY_WAIT * (attempt + 1)
            log(f'  Rate limit — ממתין {wait}ש...')
            time.sleep(wait)
        except Exception as e:
            log(f'  שגיאה (ניסיון {attempt+1}): {str(e)[:80]}')
            if attempt < 3:
                time.sleep(3)
    return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test',   action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--apply',  action='store_true',
                        help='החל את series_detected.json על הקובץ')
    args = parser.parse_args()

    books, prefix, suffix = load_library()
    by_id = {b['id']: b for b in books}

    # ── מצב Apply: החל תוצאות שמורות ──────────────────────────────────────────
    if args.apply:
        if not os.path.exists(OUT_PATH):
            print('לא נמצא series_detected.json — הרץ קודם בלי --apply')
            return
        with open(OUT_PATH, encoding='utf-8') as f:
            all_series = json.load(f)

        updated = 0
        for entry in all_series:
            sname = entry['series_name']
            for bid in entry['book_ids']:
                if bid in by_id:
                    by_id[bid]['narrative_series'] = sname
                    updated += 1

        save_library(list(by_id.values()), prefix, suffix)
        print(f'עודכנו: {updated} ספרים ב-{len(all_series)} סדרות')
        print('✓ בוצע')
        return

    # ── קריאת API ─────────────────────────────────────────────────────────────
    api_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if not api_key:
        api_key = input('Anthropic API key: ').strip()
    client = anthropic.Anthropic(api_key=api_key)

    # קיבוץ לפי מחבר — רק מחברים עם 2+ ספרים
    by_author = {}
    for b in books:
        ak = normalize_author(b.get('author', ''))
        if ak:
            by_author.setdefault(ak, []).append(b)

    multi_authors = {ak: bks for ak, bks in by_author.items() if len(bks) >= 2}
    log(f'מחברים עם 2+ ספרים: {len(multi_authors)}')
    log(f'ספרים רלוונטיים: {sum(len(v) for v in multi_authors.values())}')

    # checkpoint
    done = load_checkpoint() if args.resume else set()
    author_keys = [ak for ak in multi_authors if ak not in done]
    if args.test:
        author_keys = author_keys[:30]
    log(f'לעיבוד: {len(author_keys)} מחברים\n')

    all_results = []
    total_series_found = 0

    # עיבוד בbatches של BATCH_SIZE מחברים
    book_batch = []
    batch_authors = []

    def flush_batch():
        nonlocal total_series_found
        if not book_batch:
            return
        results = call_api(client, book_batch)
        if results:
            all_results.extend(results)
            total_series_found += len(results)
            for r in results:
                log(f'  ✓ {r["series_name"]} ({len(r["book_ids"])} ספרים): '
                    + ', '.join(by_id[bid]["title"][:25] for bid in r["book_ids"] if bid in by_id))
        for ak in batch_authors:
            append_checkpoint(ak, results)
        book_batch.clear()
        batch_authors.clear()
        time.sleep(0.3)

    for i, ak in enumerate(author_keys):
        bks = multi_authors[ak]
        book_batch.extend(bks)
        batch_authors.append(ak)

        if len(book_batch) >= BATCH_SIZE or i == len(author_keys) - 1:
            log(f'[{i+1}/{len(author_keys)}] batch {len(batch_authors)} מחברים, '
                f'{len(book_batch)} ספרים | סדרות עד כה: {total_series_found}')
            flush_batch()

    # שמור תוצאות
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    log(f'\n=== סיכום ===')
    log(f'סדרות שזוהו: {total_series_found}')
    log(f'נשמר: {OUT_PATH}')
    log(f'\nבדוק את הקובץ, ואז הרץ:')
    log(f'  py -3 detect_series.py --apply')


if __name__ == '__main__':
    main()
