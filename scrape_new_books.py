#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scrape_new_books.py
===================
מגרד תקצירים מסימניה ו-e-vrit עבור ספרים חדשים שחסר להם תקציר.
מעדכן את local_library_adults.js ו-local_library_kids.js.

שימוש:
    py -3 scrape_new_books.py --test         # 5 ספרים ראשונים, הצג תוצאות
    py -3 scrape_new_books.py                # ספרים מ-NEW_IDS
    py -3 scrape_new_books.py --auto-ids     # זיהוי אוטומטי של ספרים חדשים (IDs גבוהים ללא תקציר)
"""

import json, re, sys, io, time, os, argparse, urllib.parse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ADULTS_PATH = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\local_library_adults.js'
KIDS_PATH   = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\local_library_kids.js'

# IDs של הספרים החדשים מה-PDF — מעדכנים ידנית אחרי כל קליטה
NEW_IDS = {f'lib{i}' for i in list(range(5781, 5826)) + [3133]}

SIMANIA_DELAY = 2.5

# נרמול שמות מחברים — וריאציות ידועות → צורת חיפוש מיטבית
AUTHOR_NORMALIZE = {
    'זיס דוקטור':    'דוקטור סוס',
    'ד"ר סאוס':      'דוקטור סוס',
    'ד"ר סוס':       'דוקטור סוס',
    'דוקטור זוס':    'דוקטור סוס',
    'סאוס ד"ר':      'דוקטור סוס',
    'סוס ד"ר':       'דוקטור סוס',
}


def load_js(path):
    with open(path, encoding='utf-8-sig') as f:
        content = f.read()
    m = re.search(r'var LOCAL_LIBRARY\w*\s*=\s*(\[.*\])\s*;', content, re.DOTALL)
    return json.loads(m.group(1)), content, m


def save_js(path, books, content, m):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content[:m.start(1)])
        f.write(json.dumps(books, ensure_ascii=False, indent=2))
        f.write(content[m.end(1):])


def normalize_word(w):
    """מסיר ה' הידיעה מתחילת מילה לצורך השוואה."""
    return w[1:] if len(w) > 2 and w[0] == 'ה' else w


def title_similarity(a, b):
    def words(s):
        return {normalize_word(w) for w in re.sub(r'[^\w\s]', '', s).split()}
    a_words = words(a)
    b_words = words(b)
    if not a_words or not b_words:
        return 0.0
    return len(a_words & b_words) / max(len(a_words), len(b_words))


def search_title(title):
    """כותרת לחיפוש — מסיר תת-כותרת אחרי נקודותיים."""
    return re.split(r'\s*[:\u2014\u2013]\s*', title)[0].strip()


def normalize_author(author):
    """מחזיר את צורת החיפוש המיטבית של שם המחבר."""
    return AUTHOR_NORMALIZE.get(author.strip(), author) if author else author


def author_search_key(author):
    """מילת החיפוש מהמחבר — שם משפחה (מילה אחרונה) עדיף על ראשונה."""
    norm = normalize_author(author)
    parts = norm.split() if norm else []
    return parts[-1] if parts else ''


def fetch_simania(page, title, author):
    """חיפוש תקציר מסימניה."""
    author_key = author_search_key(author)
    query = f'{search_title(title)} {author_key}'.strip()
    search_url = 'https://simania.co.il/searchBooks.php?query=' + urllib.parse.quote(query)

    try:
        page.goto(search_url, wait_until='domcontentloaded', timeout=15000)
        time.sleep(1.5)
    except Exception as e:
        print(f'  [NAV ERR] {str(e)[:60]}')
        return None, None

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

    best = max(book_links, key=lambda l: title_similarity(title, l['text']))
    if title_similarity(title, best['text']) < 0.5:
        return None, None

    try:
        page.goto(best['href'], wait_until='domcontentloaded', timeout=15000)
        time.sleep(1.5)
    except Exception as e:
        print(f'  [BOOK ERR] {str(e)[:60]}')
        return None, None

    desc = page.evaluate('''() => {
        const all = Array.from(document.querySelectorAll('div, p'));
        const blocks = [];
        const seen = new Set();
        for (const el of all) {
            if (el.closest('.review-preview-text') || el.classList.contains('review-preview-text')) continue;
            if (el.querySelectorAll('div, p').length > 2) continue;
            const text = (el.textContent || '').trim();
            if (text.length < 120 || text.length > 4000) continue;
            if (text.startsWith('הספר ') && text.includes('יצא לאור')) continue;
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
    desc = re.sub(r'\s*(קרא עוד|קראו עוד|להמשך קריאה|עוד\.\.\.?)\s*$', '', desc).strip()
    if len(desc) > 2500:
        cut = desc[:2500]
        m2 = re.search(r'[.!?](?=[^.!?]*$)', cut)
        desc = cut[:m2.start()+1].strip() if m2 and m2.start() > 1500 else cut + '...'

    return desc, best['text']


def fetch_evrit(page, title, author):
    """חיפוש תקציר מ-e-vrit."""
    # e-vrit — חיפוש לפי כותרת ראשית בלבד (ללא תת-כותרת, המחבר לא עוזר שם)
    search_url = 'https://www.e-vrit.co.il/Search/' + urllib.parse.quote(search_title(title))
    try:
        page.goto(search_url, wait_until='domcontentloaded', timeout=25000)
        time.sleep(7.0)
    except Exception as e:
        print(f'  [evrit NAV ERR] {str(e)[:60]}')
        return None, None

    links = page.evaluate('''() => {
        const container = document.querySelector('[class*="product-list"]');
        if (!container) return [];
        const seen = new Set();
        const out = [];
        container.querySelectorAll('a[href*="/Product/"]').forEach(a => {
            const m = a.href.match(/Product\/(\\d+)\//);
            if (!m) return;
            const id = m[1];
            if (seen.has(id)) return;
            seen.add(id);
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

    def evrit_score(link):
        # recall: כמה מהמילים שלנו מופיעות בתוצאה (לא עונשים על מילים נוספות שלהם)
        our = {normalize_word(w) for w in re.sub(r'[^\w\s]', '', search_title(title)).split()}
        their = {normalize_word(w) for w in re.sub(r'[^\w\s]', '', link['title']).split()}
        if not our:
            return 0.0
        recall = len(our & their) / len(our)
        # עונש קטן על מילים זרות לחלוטין (מניעת false-positive)
        extra = their - our
        penalty = min(0.15, len(extra) * 0.02)
        return recall - penalty

    best = max(links, key=evrit_score)
    if evrit_score(best) < 0.6:
        return None, None

    try:
        page.goto(best['href'], wait_until='domcontentloaded', timeout=20000)
        time.sleep(3.0)
    except Exception as e:
        print(f'  [evrit BOOK ERR] {str(e)[:60]}')
        return None, None

    data = page.evaluate('''() => {
        const skipWords = ['קנייה','לסל','מחיר','שקל','נרשם','התחבר','עוגי','בתמונה:','הוצאה:','תאריך הוצאה:','מספר עמודים:','קטגוריה:'];
        const paras = Array.from(document.querySelectorAll('p:not([class])'));
        const seen = new Set();
        const parts = [];
        for (const p of paras) {
            const t = (p.textContent || '').trim();
            if (t.length < 40 || t.length > 2000) continue;
            if (seen.has(t.substring(0, 40))) continue;
            if (skipWords.some(w => t.includes(w))) continue;
            seen.add(t.substring(0, 40));
            parts.push(t);
            if (parts.join(' ').length > 1800) break;
        }
        return { desc: parts.join('\\n') };
    }''')

    desc = (data.get('desc') or '').strip()
    if not desc or len(desc) < 80:
        return None, None

    desc = re.sub(r'\s+', ' ', desc).strip()
    return desc, best['title']


def auto_detect_new_ids(adults, kids, top_n=60):
    """מזהה אוטומטית ספרים חדשים: ה-top_n ספרים עם IDs המספריים הגבוהים ביותר, ללא תקציר."""
    all_books = adults + kids
    # חלץ את המספר מה-ID (lib1234 → 1234)
    def id_num(b):
        m = re.search(r'\d+', b['id'])
        return int(m.group()) if m else 0
    sorted_books = sorted(all_books, key=id_num, reverse=True)
    # קח רק את ה-top_n ללא תקציר
    no_desc = [b for b in sorted_books if not b.get('description', '').strip()]
    detected = {b['id'] for b in no_desc[:top_n]}
    return detected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test',     action='store_true', help='5 ספרים ראשונים בלבד')
    parser.add_argument('--auto-ids', action='store_true', help='זיהוי אוטומטי של ספרים חדשים לפי IDs גבוהים')
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('Playwright לא מותקן. הרץ: py -3 -m playwright install chromium')
        sys.exit(1)

    adults, ac, am = load_js(ADULTS_PATH)
    kids,   kc, km = load_js(KIDS_PATH)

    # קבע אילו ספרים לסרוק
    if args.auto_ids:
        target_ids = auto_detect_new_ids(adults, kids)
        print(f'מצב --auto-ids: זוהו {len(target_ids)} ספרים (IDs גבוהים ללא תקציר)')
    else:
        target_ids = NEW_IDS

    # מצא ספרים ללא תקציר מתוך הרשימה
    all_books = [(b, 'adults') for b in adults] + [(b, 'kids') for b in kids]
    targets = [(b, src) for b, src in all_books
               if b['id'] in target_ids and not b.get('description','').strip()]

    if args.test:
        targets = targets[:5]

    print(f'ספרים לגריפה: {len(targets)}')
    print()

    adults_by_id = {b['id']: b for b in adults}
    kids_by_id   = {b['id']: b for b in kids}

    found = 0
    not_found = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page_sim = browser.new_page()
        page_evr = browser.new_page()

        for i, (book, src) in enumerate(targets, 1):
            title  = book['title']
            author = book.get('author', '')
            print(f'[{i}/{len(targets)}] {title[:40]}')

            # שלב 1: סימניה
            desc, matched = fetch_simania(page_sim, title, author)
            source = 'simania'

            # שלב 2: evrit אם לא נמצא
            if not desc:
                time.sleep(0.5)
                desc, matched = fetch_evrit(page_evr, title, author)
                source = 'evrit'

            if desc:
                target = adults_by_id.get(book['id']) or kids_by_id.get(book['id'])
                if target:
                    target['description'] = desc
                    target['description_source'] = source
                found += 1
                if args.test:
                    print(f'  ✓ [{source}] ({matched})')
                    print(f'  {desc[:200]}...' if len(desc) > 200 else f'  {desc}')
                else:
                    print(f'  ✓ [{source}] {matched[:35]}')
            else:
                not_found.append(title)
                print(f'  ✗ לא נמצא')

            time.sleep(SIMANIA_DELAY)

        page_sim.close()
        page_evr.close()
        browser.close()

    # שמירה
    if not args.test:
        save_js(ADULTS_PATH, adults, ac, am)
        save_js(KIDS_PATH,   kids,   kc, km)
        print(f'\nנשמר.')
    else:
        print(f'\n--- טסט בלבד, לא נשמר ---')

    print(f'\nנמצאו: {found}/{len(targets)}')
    if not_found:
        print('לא נמצאו:')
        for t in not_found:
            print(f'  - {t}')


if __name__ == '__main__':
    main()
