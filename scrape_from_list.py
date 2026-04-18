#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scrape_from_list.py
====================
מריץ סקרייפר simania על רשימת ספרים ספציפית מקובץ xlsx.
משתמש בשמות המחברים המתוקנים מה-xlsx (לא מהקטלוג).
מתעלם מ-checkpoint קיים — מנסה מחדש גם ספרים שנכשלו בעבר.

שימוש:
    py -3 scrape_from_list.py                     # ריצה מלאה
    py -3 scrape_from_list.py --test              # 10 ספרים ראשונים
    py -3 scrape_from_list.py --resume            # המשך מ-checkpoint
"""

import json, re, sys, io, time, os, argparse, urllib.parse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from scrape_descriptions import (
    load_library, save_library, http_get,
    fetch_simania, title_similarity, clean_author_family_name,
    normalize_for_match, log, SIMANIA_DELAY, LOG_FILE
)

XLSX_PATH = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\no_description_popular.xlsx'
CKPT_PATH = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\list_scrape_checkpoint.jsonl'
SAVE_EVERY = 20


def load_xlsx():
    import openpyxl
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    # headers: ID, כותרת, מחבר, סוגה, שנה, הוצאה, שפה, קטגוריה
    books = []
    for row in rows[1:]:
        bid, title, author = row[0], row[1], row[2]
        if bid and title:
            books.append({
                'id':     str(bid).strip(),
                'title':  str(title).strip(),
                'author': str(author).strip() if author else '',
            })
    return books


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
                    done[e['id']] = e
                except Exception:
                    pass
    return done


def append_checkpoint(entry):
    with open(CKPT_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test',   action='store_true', help='רק 10 ספרים')
    parser.add_argument('--resume', action='store_true', help='המשך מ-checkpoint')
    args = parser.parse_args()

    log(f'\n=== scrape_from_list.py  {time.strftime("%H:%M:%S")} ===')

    # טען רשימת יעד מ-xlsx
    target_books = load_xlsx()
    log(f'רשימת יעד: {len(target_books)} ספרים')

    # טען ספרייה
    books = load_library()
    by_id = {b['id']: b for b in books}

    # checkpoint של הריצה הזו
    ckpt = load_checkpoint() if args.resume else {}
    log(f'checkpoint: {len(ckpt)} כבר עובדו')

    # סנן: רק ספרים שעדיין ללא תקציר ולא ב-checkpoint הנוכחי
    to_process = [
        b for b in target_books
        if b['id'] not in ckpt and not by_id.get(b['id'], {}).get('description')
    ]

    if args.test:
        to_process = to_process[:10]

    log(f'לעיבוד: {len(to_process)} ספרים\n')

    if not to_process:
        log('הכל מעובד.')
        return

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log('Playwright לא מותקן. הרץ: pip install playwright && playwright install chromium')
        return

    success = 0
    USER_AGENT = 'Mozilla/5.0 (ShaharutLibBot/2.0)'

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=USER_AGENT, locale='he-IL',
            viewport={'width': 1280, 'height': 800}
        )
        page = ctx.new_page()
        page.route('**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,css}',
                   lambda route: route.abort())

        try:
            for i, book in enumerate(to_process):
                catalog_book = by_id.get(book['id'])
                if not catalog_book:
                    log(f'[{i+1}] ID לא נמצא בקטלוג: {book["id"]}')
                    continue

                log(f'\n[{i+1}/{len(to_process)}] {book["title"]} / {book["author"]}')

                # ניסיון 1: כותרת + מחבר
                desc, matched = fetch_simania(page, book['title'], book['author'])

                # ניסיון 2: כותרת בלבד (אם המחבר לא מוכר לסימניה)
                if not desc:
                    time.sleep(1.0)
                    desc, matched = fetch_simania(page, book['title'], '')

                entry = {
                    'id':      book['id'],
                    'title':   book['title'],
                    'desc':    desc or '',
                    'matched': matched or ''
                }
                append_checkpoint(entry)

                if desc:
                    catalog_book['description'] = desc
                    catalog_book['description_source'] = 'simania'
                    success += 1
                    log(f'  ✓ {matched}')
                    log(f'  {desc[:100]}...')
                else:
                    log(f'  ✗ לא נמצא')

                if (i + 1) % SAVE_EVERY == 0:
                    save_library(list(by_id.values()))
                    log(f'  [שמירה] הצלחות: {success}/{i+1}')

                time.sleep(SIMANIA_DELAY)

        finally:
            browser.close()

    save_library(list(by_id.values()))

    log(f'\n=== סיכום ===')
    log(f'הצלחות: {success}/{len(to_process)}  ({100*success//max(len(to_process),1)}%)')
    log(f'✓ בוצע')


if __name__ == '__main__':
    main()
