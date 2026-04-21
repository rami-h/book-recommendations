#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inject_borderline.py
====================
קורא את borderline_review.xlsx, שולף תקצירים מ-URL לכל שורה מאושרת (1),
ומזריק לתוך local_library_adults.js / local_library_kids.js.
"""
import json, re, sys, io, time, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ADULTS_PATH = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\local_library_adults.js'
KIDS_PATH   = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\local_library_kids.js'
BORDER_XLSX = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\borderline_review.xlsx'


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


def fetch_desc_simania(page, url):
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=15000)
        time.sleep(2)
    except Exception as e:
        return None
    desc = page.evaluate('''() => {
        const all = Array.from(document.querySelectorAll('div, p'));
        const seen = new Set();
        for (const el of all) {
            if (el.closest('.review-preview-text') || el.classList.contains('review-preview-text')) continue;
            if (el.querySelectorAll('div, p').length > 2) continue;
            const text = (el.textContent || '').trim();
            if (text.length < 80 || text.length > 4000) continue;
            if (text.startsWith('הספר ') && text.includes('יצא לאור')) continue;
            const sig = text.substring(0, 80);
            if (seen.has(sig)) continue;
            seen.add(sig);
            return text;
        }
        return null;
    }''')
    if not desc or len(desc) < 80:
        return None
    desc = re.sub(r'\s+', ' ', desc).strip()
    desc = re.sub(r'\s*(קרא עוד|קראו עוד|להמשך קריאה|עוד\.\.\.?)\s*$', '', desc).strip()
    if len(desc) > 2500:
        cut = desc[:2500]
        m2 = re.search(r'[.!?](?=[^.!?]*$)', cut)
        desc = cut[:m2.start()+1].strip() if m2 and m2.start() > 1500 else cut + '...'
    return desc


def fetch_desc_evrit(page, url):
    try:
        page.goto(url, wait_until='networkidle', timeout=25000)
        time.sleep(3)
    except Exception as e:
        return None
    data = page.evaluate('''() => {
        // JSON-LD first
        const scripts = Array.from(document.querySelectorAll('script[type="application/ld+json"]'));
        for (const s of scripts) {
            try {
                const obj = JSON.parse(s.textContent);
                const arr = Array.isArray(obj) ? obj : [obj];
                for (const item of arr) {
                    if (item.description && item.description.length > 60) return item.description;
                }
            } catch(e) {}
        }
        // fallback: p:not([class])
        const skipWords = ['קנייה','לסל','מחיר','שקל','נרשם','התחבר','עוגי',
                           'בתמונה:','הוצאה:','תאריך הוצאה:','מספר עמודים:','קטגוריה:'];
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
        return parts.join(' ') || null;
    }''')
    if not data or len(data) < 80:
        return None
    return re.sub(r'\s+', ' ', data).strip()


def main():
    import openpyxl
    from playwright.sync_api import sync_playwright

    wb = openpyxl.load_workbook(BORDER_XLSX)
    ws = wb.active

    approved = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        bid, our_title, matched, score, source, url, snippet, approval = row
        if str(approval).strip() == '1' and url:
            approved.append({'id': bid, 'title': our_title, 'url': url,
                             'source': (source or '').lower()})

    print(f'מאושרים לטיפול: {len(approved)}')

    adults, ac, am = load_js(ADULTS_PATH)
    kids,   kc, km = load_js(KIDS_PATH)
    by_id = {b['id']: b for b in adults + kids}

    injected = 0
    failed   = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for i, entry in enumerate(approved, 1):
            bid   = entry['id']
            title = entry['title']
            url   = entry['url']
            src   = entry['source']
            print(f'[{i}/{len(approved)}] {title[:45]}')

            if 'simania' in src or 'simania' in url:
                desc = fetch_desc_simania(page, url)
            else:
                desc = fetch_desc_evrit(page, url)

            if desc:
                book = by_id.get(bid)
                if book:
                    book['description'] = desc
                    book['description_source'] = src
                injected += 1
                print(f'  ✓ {desc[:100]}...')
            else:
                failed.append(title)
                print(f'  ✗ לא הצלחתי לשלוף תקציר')

            time.sleep(1.5)

        browser.close()

    save_js(ADULTS_PATH, adults, ac, am)
    save_js(KIDS_PATH,   kids,   kc, km)

    print(f'\nהוזרקו: {injected}/{len(approved)}')
    if failed:
        print('נכשלו:')
        for t in failed:
            print(f'  - {t}')


if __name__ == '__main__':
    main()
