#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
סקריפט חילוץ תקצירים בשתי שיטות:
1. Google Books API (מהיר, חינם) - ניסיון ראשון
2. simania.co.il דרך Playwright - רק לספרים שלא נמצאו ב-Google Books

שימוש:
    python scrape_descriptions.py --test           # ניסוי על 20 ספרים
    python scrape_descriptions.py --limit 50       # 50 ספרים ראשונים
    python scrape_descriptions.py --all            # כל הספרים החסרים
    python scrape_descriptions.py --resume         # המשך מאיפה שהפסיק
    python scrape_descriptions.py --phase google   # רק Google Books
    python scrape_descriptions.py --phase simania  # רק simania
"""

import json
import re
import time
import urllib.parse
import urllib.request
import sys
import os
import argparse
from bs4 import BeautifulSoup

LIBRARY_JS = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\local_library.js'
PROGRESS_FILE = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\scrape_progress.json'
SIMANIA_CKPT = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\simania_checkpoint.jsonl'
LOG_FILE = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\scrape_log.txt'

USER_AGENT = 'Mozilla/5.0 (ShaharutLibBot; library-enrichment; contact=library@shaharut)'
GOOGLE_DELAY = 0.5
SIMANIA_DELAY = 2.5
TIMEOUT = 15

SAVE_EVERY = 25  # checkpoint + local_library.js כל 25 ספרים


def log(msg):
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(msg + '\n')
    try:
        ascii_msg = msg.encode('ascii', 'replace').decode('ascii')
        print(ascii_msg, flush=True)
    except Exception:
        pass


def load_library():
    with open(LIBRARY_JS, 'r', encoding='utf-8') as f:
        content = f.read()
    m = re.search(r'var LOCAL_LIBRARY = (\[.*\]);', content, re.DOTALL)
    if not m:
        raise Exception('Could not parse local_library.js')
    return json.loads(m.group(1))


def save_library(books):
    js = (
        '/**\n'
        ' * קטלוג ספריית שחרות\n'
        ' * נוצר אוטומטית מקובץ XLS של הקטלוג, והועשר עם תקצירים ממקורות חיצוניים\n'
        f' * סה"כ: {len(books)} ספרים\n'
        ' */\n\n'
        'var LOCAL_LIBRARY = '
    )
    js += json.dumps(books, ensure_ascii=False, indent=2)
    js += ';\n'
    with open(LIBRARY_JS, 'w', encoding='utf-8') as f:
        f.write(js)


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        'google_tried': [],     # ids tried via Google Books
        'google_success': 0,
        'simania_tried': [],    # ids tried via Simania
        'simania_success': 0,
        'failed_ids': [],       # tried both, still failed
    }


def save_progress(progress):
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


# ── Sample validation ────────────────────────────────────────
def validate_simania_sample(page, candidates, n=10):
    """
    בוחר n ספרים אקראיים, מריץ fetch_simania ומציג טבלת השוואה.
    מחזיר True אם המשתמש אישר להמשיך, False אחרת.
    """
    import random
    random.seed(42)
    sample = random.sample(candidates, min(n, len(candidates)))

    log('\n' + '='*70)
    log(f'בדיקת מדגם לפני ריצה מלאה — {len(sample)} ספרים (Simania)')
    log('='*70 + '\n')

    W_TITLE = 28
    W_MATCH = 28
    W_DESC  = 50

    header = f'{"כותרת קיימת":<{W_TITLE}} | {"כותרת שנמצאה":<{W_MATCH}} | {"תקציר (100 תווים)"}'
    log(header)
    log('-' * (W_TITLE + W_MATCH + W_DESC + 6))

    successes = 0
    for book in sample:
        try:
            desc, matched = fetch_simania(page, book['title'], book['author'])
        except Exception as e:
            desc, matched = None, f'ERR: {str(e)[:25]}'
        time.sleep(SIMANIA_DELAY)

        if desc:
            successes += 1
            snippet = desc[:W_DESC].replace('\n', ' ')
        else:
            matched  = matched or '—'
            snippet  = '—'

        log(f'{book["title"][:W_TITLE]:<{W_TITLE}} | {(matched or "")[:W_MATCH]:<{W_MATCH}} | {snippet}')

    log(f'\nהצלחות: {successes}/{len(sample)}')
    log('='*70)

    answer = input('\nלהמשיך לריצה המלאה? (yes / no): ').strip().lower()
    return answer in ('yes', 'y', 'כן', 'י')


# ── JSONL checkpoint לסימניה ──────────────────────────────────
def load_simania_checkpoint():
    """מחזיר {book_id: entry} מקובץ JSONL קיים."""
    done = {}
    if not os.path.exists(SIMANIA_CKPT):
        return done
    with open(SIMANIA_CKPT, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                done[entry['id']] = entry
            except Exception:
                pass
    return done


def append_simania_checkpoint(entry):
    """מוסיף רשומה אחת לקובץ JSONL (בטוח לקריסות)."""
    with open(SIMANIA_CKPT, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def http_get(url):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode('utf-8', errors='replace')


# ============================================================
# נרמול והתאמת כותרות
# ============================================================

def normalize_for_match(text):
    if not text:
        return ''
    text = re.sub(r'[\"\'״׳:,\.\-\(\)\[\]!?]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip().lower()
    return text


def title_similarity(a, b):
    a_words = set(w for w in normalize_for_match(a).split() if len(w) > 1)
    b_words = set(w for w in normalize_for_match(b).split() if len(w) > 1)
    if not a_words or not b_words:
        return 0.0
    common = a_words & b_words
    return len(common) / min(len(a_words), len(b_words))


def clean_author_family_name(author):
    if not author:
        return ''
    parts = author.strip().split()
    return parts[0] if parts else ''


# ============================================================
# שלב 1: Google Books API
# ============================================================

def fetch_google_books(title, author):
    """מחפש ספר ב-Google Books, מחזיר תיאור אם נמצא ומתאים."""
    author_key = clean_author_family_name(author)
    queries = [
        f'intitle:{title} inauthor:{author_key}',
        f'{title} {author_key}',
    ]

    for q in queries:
        # ניסיון עם retry על 503
        data = None
        for attempt in range(3):
            try:
                url = f'https://www.googleapis.com/books/v1/volumes?q={urllib.parse.quote(q)}&langRestrict=he&maxResults=5'
                data = json.loads(http_get(url))
                break
            except urllib.error.HTTPError as e:
                if e.code == 503 and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                log(f'  [Google ERR] HTTP {e.code}')
                break
            except Exception as e:
                log(f'  [Google ERR] {str(e)[:60]}')
                break
        if data is None:
            continue

        items = data.get('items', [])
        for item in items:
            v = item.get('volumeInfo', {})
            g_title = v.get('title', '')
            g_authors = v.get('authors', [])
            desc = v.get('description', '')

            if not desc or len(desc) < 50:
                continue

            # אימות התאמה
            score = title_similarity(title, g_title)
            if score < 0.5:
                continue

            # אימות מחבר (אם קיים)
            if g_authors and author_key:
                author_match = any(
                    author_key in a or a in author_key or title_similarity(author_key, a) > 0.5
                    for a in g_authors
                )
                if not author_match:
                    continue

            # מצאנו התאמה טובה
            desc = re.sub(r'\s+', ' ', desc).strip()
            return desc[:1500], g_title

    return None, None


def phase_google_books(books_to_process, books_by_id, progress):
    log(f'\n=== שלב 1: Google Books API ({len(books_to_process)} ספרים) ===')

    tried_set = set(progress['google_tried'])

    for i, book in enumerate(books_to_process):
        if book['id'] in tried_set:
            continue

        log(f'\n[G {i+1}/{len(books_to_process)}] {book["title"]} / {book["author"]}')

        desc, matched = fetch_google_books(book['title'], book['author'])
        progress['google_tried'].append(book['id'])

        if desc:
            books_by_id[book['id']]['description'] = desc
            books_by_id[book['id']]['description_source'] = 'google_books'
            progress['google_success'] += 1
            log(f'  V {matched}')
            log(f'  {desc[:120]}...')
        else:
            log(f'  X לא נמצא ב-Google Books')

        if (i + 1) % SAVE_EVERY == 0:
            save_library(list(books_by_id.values()))
            save_progress(progress)
            log(f'  [נשמר] Google הצלחה={progress["google_success"]}/{len(progress["google_tried"])}')

        time.sleep(GOOGLE_DELAY)

    save_library(list(books_by_id.values()))
    save_progress(progress)


# ============================================================
# שלב 2: Simania via Playwright
# ============================================================

def phase_simania_playwright(books_to_process, books_by_id, progress):
    """מריץ Playwright על simania לספרים שלא נמצאו ב-Google Books."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log('Playwright לא מותקן - מדלג על שלב simania')
        return

    # טען checkpoint JSONL — ספרים שכבר עובדו
    ckpt = load_simania_checkpoint()
    log(f'  checkpoint קיים: {len(ckpt)} ספרים')

    # הזרק תוצאות מ-checkpoint לתוך books_by_id
    for book_id, entry in ckpt.items():
        if book_id in books_by_id and entry.get('desc') and not books_by_id[book_id].get('description'):
            books_by_id[book_id]['description'] = entry['desc']
            books_by_id[book_id]['description_source'] = 'simania'

    # מסנן רק ספרים שעדיין ללא תקציר ולא ב-checkpoint
    remaining = [
        b for b in books_to_process
        if not books_by_id[b['id']].get('description') and b['id'] not in ckpt
    ]
    log(f'\n=== שלב 2: Simania Playwright ({len(remaining)} ספרים נותרו) ===')

    if not remaining:
        return

    success_count = sum(1 for e in ckpt.values() if e.get('desc'))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale='he-IL',
            viewport={'width': 1280, 'height': 800},
        )
        page = context.new_page()
        page.route('**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,css}', lambda route: route.abort())

        # ── בדיקת מדגם לפני ריצה מלאה (רק אם אין checkpoint קיים) ──
        if not ckpt:
            approved = validate_simania_sample(page, remaining, n=10)
            if not approved:
                log('\nריצה בוטלה על ידי המשתמש.')
                browser.close()
                return

        try:
            for i, book in enumerate(remaining):
                log(f'\n[S {i+1}/{len(remaining)}] {book["title"]} / {book["author"]}')

                desc, matched = fetch_simania(page, book['title'], book['author'])

                # כתוב לחדשות JSONL מיד — עמיד לקריסות
                entry = {'id': book['id'], 'title': book['title'], 'desc': desc or '', 'matched': matched or ''}
                append_simania_checkpoint(entry)
                progress['simania_tried'].append(book['id'])

                if desc:
                    books_by_id[book['id']]['description'] = desc
                    books_by_id[book['id']]['description_source'] = 'simania'
                    success_count += 1
                    progress['simania_success'] += 1
                    log(f'  V {matched}')
                    log(f'  {desc[:120]}...')
                else:
                    progress['failed_ids'].append(book['id'])
                    log(f'  X לא נמצא ב-Simania')

                # שמור local_library.js כל 25 ספרים
                if (i + 1) % SAVE_EVERY == 0:
                    save_library(list(books_by_id.values()))
                    save_progress(progress)
                    log(f'  [נשמר] הצלחות={success_count}/{i+1}')

                time.sleep(SIMANIA_DELAY)
        finally:
            browser.close()

    save_library(list(books_by_id.values()))
    save_progress(progress)


def fetch_simania(page, title, author):
    """חיפוש והורדה מ-simania דרך Playwright."""
    author_key = clean_author_family_name(author)
    query = f'{title} {author_key}'.strip()
    search_url = 'https://simania.co.il/searchBooks.php?query=' + urllib.parse.quote(query)

    # טעינת דף החיפוש (domcontentloaded במקום networkidle - הרבה יותר מהיר ואמין)
    try:
        page.goto(search_url, wait_until='domcontentloaded', timeout=15000)
        time.sleep(1.5)  # זמן לרינדור ראשוני
    except Exception as e:
        log(f'  [Simania NAV ERR] {str(e)[:60]}')
        return None, None

    # איסוף קישורי bookdetails
    book_links = page.evaluate('''() => {
        const links = Array.from(document.querySelectorAll('a[href*="bookdetails.php"]'));
        const seen = new Set();
        const result = [];
        for (const a of links) {
            const m = a.href.match(/item_id=(\\d+)/);
            if (!m) continue;
            const id = m[1];
            if (seen.has(id)) continue;
            const text = (a.textContent || '').trim();
            if (text.length < 2 || text.includes('מוכרים')) continue;
            seen.add(id);
            result.push({ id, href: 'https://simania.co.il/bookdetails.php?item_id=' + id, text });
            if (result.length >= 10) break;
        }
        return result;
    }''')

    if not book_links:
        return None, None

    # התאמת קישור הכי טוב לכותרת
    best = None
    best_score = 0.0
    for link in book_links:
        score = title_similarity(title, link['text'])
        if score > best_score:
            best_score = score
            best = link

    if not best or best_score < 0.5:
        return None, None

    # טעינת דף הספר
    try:
        page.goto(best['href'], wait_until='domcontentloaded', timeout=15000)
        time.sleep(1.5)
    except Exception as e:
        log(f'  [Simania BOOK ERR] {str(e)[:60]}')
        return None, None

    # חילוץ התקציר - הבלוק הראשון שאינו ביקורת ואינו מטא-נתונים
    desc = page.evaluate('''() => {
        // איסוף כל בלוקי טקסט ארוכים שאינם בתוך .review-preview-text
        const all = Array.from(document.querySelectorAll('div, p'));
        const blocks = [];
        const seen = new Set();
        for (const el of all) {
            // לא לספור ביקורות
            if (el.closest('.review-preview-text') || el.classList.contains('review-preview-text')) continue;
            if (el.closest('.line-clamp-6') && !el.classList.contains('relative')) continue;
            // לא לספור אלמנטים עם הרבה ילדים (רק עלים)
            if (el.querySelectorAll('div, p').length > 2) continue;
            const text = (el.textContent || '').trim();
            if (text.length < 120 || text.length > 4000) continue;
            // בלוק מטא ("הספר יצא לאור בשנת...") מתחיל כך
            if (text.startsWith('הספר ') && text.includes('יצא לאור')) continue;
            // חתימה ראשונית
            const sig = text.substring(0, 80);
            if (seen.has(sig)) continue;
            seen.add(sig);
            blocks.push(text);
            if (blocks.length >= 3) break;
        }
        return blocks[0] || null;
    }''')

    if not desc or len(desc) < 80:
        return None, None

    desc = re.sub(r'\s+', ' ', desc).strip()
    # הסרת שאריות כפתור "קרא עוד" ודומיו מסוף התקציר
    desc = re.sub(r'\s*(קרא עוד|קראו עוד|להמשך קריאה|עוד\.\.\.?)\s*$', '', desc).strip()
    # חיתוך בגבול משפט: אם התקציר ארוך מ-2500, חתוך בנקודה/סימן פיסוק האחרון שלפני 2500
    MAX_LEN = 2500
    if len(desc) > MAX_LEN:
        cut = desc[:MAX_LEN]
        # חפש נקודה/סימן קריאה/שאלה אחרונים
        m = re.search(r'[.!?](?=[^.!?]*$)', cut)
        if m and m.start() > MAX_LEN * 0.6:
            desc = cut[:m.start()+1].strip()
        else:
            desc = cut.strip() + '...'
    return desc, best['text']


def fetch_evrit(page, title, author):
    """חיפוש והורדה מ-e-vrit.co.il דרך Playwright."""
    # e-vrit: חיפוש לפי כותרת בלבד — הוספת מחבר מקלקלת תוצאות
    search_url = 'https://www.e-vrit.co.il/Search/' + urllib.parse.quote(title)

    try:
        page.goto(search_url, wait_until='domcontentloaded', timeout=25000)
        time.sleep(6.0)  # e-vrit צריך זמן לרינדור תוצאות חיפוש
    except Exception as e:
        log(f'  [evrit NAV ERR] {str(e)[:60]}')
        return None, None

    # חילוץ תוצאות חיפוש — שימוש ב-[class*="product-list"] שעובד יותר טוב
    links = page.evaluate('''() => {
        const container = document.querySelector('[class*="product-list"]');
        if (!container) return [];
        const seen = new Set();
        const out = [];
        container.querySelectorAll('a[href*="/Product/"]').forEach(a => {
            const m = a.href.match(/Product\/(\d+)\//);
            if (!m) return;
            const id = m[1];
            if (seen.has(id)) return;
            seen.add(id);
            // כותרת מ-img alt או מה-URL slug
            const img = a.querySelector('img') || a.closest('[class]')?.querySelector('img');
            const alt = img?.alt?.trim() || '';
            const slug = decodeURIComponent(a.href.split('/Product/')[1]?.split('/').slice(1).join(' ') || '').replace(/_/g,' ').trim();
            const title = alt || slug;
            if (title.length < 2) return;
            out.push({ id, href: a.href, title });
            if (out.length >= 20) return;
        });
        return out;
    }''')

    if not links:
        return None, None

    # התאמת הכותרת הטובה ביותר — עם עונש על תוכן עודף (כדי למנוע match לכותרת שונה)
    def _evrit_score(link):
        sim = title_similarity(title, link['title'])
        # עונש אם הכותרת המוצעת ארוכה בהרבה מהחיפוש (מונע "בית הבובות של גבי" -> "בית הבובות")
        q_words = set(title.split())
        c_words = set(link['title'].split())
        extra = c_words - q_words
        length_penalty = min(0.18, len(extra) * 0.05)
        # בונוס קל לכותרות קצרות (מעדיף ספר ראשון בסדרה)
        brevity_bonus = 0.02 if len(link['title']) <= len(title) + 5 else 0
        return sim - length_penalty + brevity_bonus

    best = None
    best_score = 0.0
    for link in links:
        score = _evrit_score(link)
        if score > best_score:
            best_score = score
            best = link

    if not best or best_score < 0.45:
        return None, None

    # טעינת דף הספר
    try:
        page.goto(best['href'], wait_until='domcontentloaded', timeout=20000)
        time.sleep(2.5)
    except Exception as e:
        log(f'  [evrit BOOK ERR] {str(e)[:60]}')
        return None, None

    # חילוץ תקציר + נושאים
    data = page.evaluate("""() => {
        const skipWords = ['\u05e7\u05e0\u05d9\u05d9\u05d4', '\u05dc\u05e1\u05dc', '\u05de\u05d7\u05d9\u05e8',
                           '\u05e9\u05e7\u05dc', '\u05e0\u05e8\u05e9\u05de', '\u05d4\u05ea\u05d7\u05d1\u05e8',
                           '\u05e2\u05d5\u05d2\u05d9', '\u05d1\u05ea\u05de\u05d5\u05e0\u05d4:',
                           '\u05d4\u05d5\u05e6\u05d0\u05d4:', '\u05ea\u05d0\u05e8\u05d9\u05da \u05d4\u05d5\u05e6\u05d0\u05d4:',
                           '\u05de\u05e1\u05e4\u05e8 \u05e2\u05de\u05d5\u05d3\u05d9\u05dd:', '\u05e7\u05d8\u05d2\u05d5\u05e8\u05d9\u05d4:'];
        // מסנן ביוגרפיה
        const bioContains = [
            '\u05e0\u05d5\u05dc\u05d3 \u05d1', '\u05e0\u05d5\u05dc\u05d3\u05d4 \u05d1',
            '\u05e1\u05d5\u05e4\u05e8 \u05d9\u05e9\u05e8\u05d0\u05dc\u05d9', '\u05e1\u05d5\u05e4\u05e8\u05ea \u05d9\u05e9\u05e8\u05d0\u05dc\u05d9\u05ea',
            '\u05ea\u05d5\u05e8\u05d2\u05de\u05d5 \u05dc', '\u05e9\u05dd \u05e2\u05d8',
            '\u05d4\u05e1\u05e4\u05e8\u05d9\u05dd \u05e9\u05dc\u05d5 \u05ea\u05d5\u05e8\u05d2',
            '\u05d4\u05e1\u05e4\u05e8\u05d9\u05dd \u05e9\u05dc\u05d4 \u05ea\u05d5\u05e8\u05d2',
            '\u05e1\u05e4\u05e8\u05d9\u05d5 \u05ea\u05d5\u05e8\u05d2', '\u05e1\u05e4\u05e8\u05d9\u05d4 \u05ea\u05d5\u05e8\u05d2',
            '\u05e4\u05e8\u05e1\u05dd \u05e2\u05d3 \u05db\u05d4', '\u05d0\u05e0\u05d2\u05dc\u05d9\u05ea:',
            '\u05d2\u05d5\u05d9\u05e1 \u05dc', '\u05e2\u05d1\u05d3 \u05db\u05e2\u05d9\u05ea\u05d5\u05e0\u05d0\u05d9',
            '\u05de\u05e1\u05e4\u05e8\u05d9\u05d5:', '\u05de\u05e1\u05e4\u05e8\u05d9\u05d4:',
            '\u05d7\u05ea\u05df \u05e4\u05e8\u05e1', '\u05d7\u05ea\u05e0\u05ea \u05e4\u05e8\u05e1',
            '\u05d9\u05e6\u05d0 \u05dc\u05d0\u05d5\u05e8 \u05dc\u05e8\u05d0\u05e9\u05d5\u05e0\u05d4 \u05d1\u05e9\u05e0\u05ea'
        ];
        const bioStarts = [
            '\u05d6\u05d5\u05db\u05d4 \u05e4\u05e8\u05e1', '\u05d6\u05d5\u05db\u05d9\u05d9\u05ea \u05e4\u05e8\u05e1',
            '\u05e4\u05e8\u05e1\u05d9\u05dd',
            '\u05d1\u05e1\u05e4\u05e8\u05d9\u05d5 \u05e0\u05d5\u05d8\u05d4', '\u05d1\u05e1\u05e4\u05e8\u05d9\u05d4 \u05e0\u05d5\u05d8\u05d4',
            '\u05de\u05e1\u05e4\u05e8\u05d9\u05d5:', '\u05de\u05e1\u05e4\u05e8\u05d9\u05d4:',
            '\u05e1\u05e4\u05e8\u05d9\u05d5:', '\u05e1\u05e4\u05e8\u05d9\u05d4:',
            '\u05d4\u05d5\u05e6\u05d0\u05d4:', '\u05ea\u05e8\u05d2\u05d5\u05dd:'
        ];
        function hasMultipleYears(t) {
            const m = t.match(/\\b(1[89]\\d{2}|20[012]\\d)\\b/g);
            return m && m.length >= 3;
        }
        const bioDatesRe = /\\(\\d{4}[\\s\\u2013\\-]+\\d{4}\\)/;

        const paras = Array.from(document.querySelectorAll('p:not([class])'));
        const seen = new Set();
        const parts = [];
        for (const p of paras) {
            const t = (p.textContent || '').trim();
            if (t.length < 40 || t.length > 2000) continue;
            if (seen.has(t.substring(0, 40))) continue;
            if (skipWords.some(w => t.includes(w))) continue;
            if (bioContains.some(w => t.includes(w))) continue;
            if (bioStarts.some(w => t.startsWith(w))) continue;
            if (bioDatesRe.test(t)) continue;
            if (hasMultipleYears(t)) continue;
            seen.add(t.substring(0, 40));
            parts.push(t);
            if (parts.join(' ').length > 1800) break;
        }
        const tagsEl = document.querySelector('.page-bottom__group-tags') ||
                       document.querySelector('[class*="group-tags"]');
        let topics = '';
        if (tagsEl) {
            const txt = tagsEl.textContent.trim();
            const idx = txt.indexOf('\\u05e0\\u05d5\\u05e9\\u05d0\\u05d9\\u05dd');
            topics = idx >= 0 ? txt.slice(idx + 7).trim().replace(/\\s+/g, ' ') : txt.trim();
        }
        return { desc: parts.join('\\n'), topics };
    }""")

    desc = (data.get('desc') or '').strip()
    topics = (data.get('topics') or '').strip()

    if not desc or len(desc) < 80:
        return None, None

    desc = re.sub(r'\s+', ' ', desc).strip()
    # הסר "מקור: ויקיפדיה https://..." מכל מקום בטקסט
    desc = re.sub(r'מקור:\s*ויקיפדיה\s*https?://\S+\s*', '', desc).strip()
    desc = re.sub(r'\s*(קרא עוד|קראו עוד)\s*$', '', desc).strip()
    if len(desc) > 2500:
        cut = desc[:2500]
        m = re.search(r'[.!?](?=[^.!?]*$)', cut)
        desc = cut[:m.start()+1].strip() if (m and m.start() > 1500) else cut + '...'

    matched = best['title']
    if topics:
        matched += f' | נושאים: {topics[:80]}'
    return desc, matched


# ============================================================
# ראשי
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--phase', choices=['google', 'simania', 'both'], default='both')
    args = parser.parse_args()

    if not (args.test or args.all or args.resume or args.limit):
        parser.print_help()
        sys.exit(0)

    books = load_library()
    log(f'טעון: {len(books)} ספרים')

    needs_desc = [b for b in books if not b.get('description')]
    log(f'ללא תקציר: {len(needs_desc)}')

    # בחירת מדגם מייצג לבדיקה - לא רק ספרים ראשונים
    if args.test:
        # דוגם ספרים מגוונים: מתחילת, אמצע וסוף הרשימה
        import random
        random.seed(42)
        sample = random.sample(needs_desc, min(30, len(needs_desc)))
        to_process = sample[:20]
    elif args.limit:
        to_process = needs_desc[:args.limit]
    elif args.all:
        to_process = needs_desc
    else:
        to_process = needs_desc

    log(f'לעיבוד: {len(to_process)} ספרים')
    log(f'התחלה: {time.strftime("%Y-%m-%d %H:%M:%S")}')

    progress = load_progress() if (args.resume or args.all) else {
        'google_tried': [], 'google_success': 0,
        'simania_tried': [], 'simania_success': 0,
        'failed_ids': [],
    }

    books_by_id = {b['id']: b for b in books}

    try:
        if args.phase in ('google', 'both'):
            phase_google_books(to_process, books_by_id, progress)

        if args.phase in ('simania', 'both'):
            phase_simania_playwright(to_process, books_by_id, progress)
    except KeyboardInterrupt:
        log('\n\nהופסק ע"י המשתמש.')
    finally:
        save_library(list(books_by_id.values()))
        save_progress(progress)

    # סיכום
    total_tried = len(set(progress['google_tried'] + progress['simania_tried']))
    total_success = progress['google_success'] + progress['simania_success']
    log(f'\n=== סיכום ===')
    log(f'ניסיונות: {total_tried}')
    log(f'הצלחות מ-Google Books: {progress["google_success"]}')
    log(f'הצלחות מ-Simania: {progress["simania_success"]}')
    log(f'סה"כ הצלחות: {total_success}')
    if total_tried > 0:
        log(f'אחוז הצלחה: {100*total_success/total_tried:.0f}%')


if __name__ == '__main__':
    main()
