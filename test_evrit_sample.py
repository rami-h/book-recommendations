#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בדיקת מדגם רנדומלי — fetch_evrit על 20 ספרים מהקובץ catalog_no_match_scraped.xlsx
הצג תוצאות לבדיקת איכות לפני הריצה הגדולה.
"""
import sys, io, re, time, random, urllib.parse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import openpyxl
from playwright.sync_api import sync_playwright
from difflib import SequenceMatcher

XLSX_PATH = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\catalog_no_match_scraped.xlsx'
COL_ID     = 1   # A
COL_TITLE  = 2   # B
COL_AUTHOR = 3   # C
COL_DESC   = 13  # M  (1-based)
SAMPLE_SIZE = 20
RANDOM_SEED = 99

# ── similarity ──────────────────────────────────────────────
def _norm(s):
    s = re.sub(r'[\u0591-\u05C7]', '', s)   # ניקוד
    s = re.sub(r'[^\u05D0-\u05EAa-zA-Z0-9\s]', ' ', s)
    return ' '.join(s.split()).strip()

def title_similarity(a, b):
    a, b = _norm(a).lower(), _norm(b).lower()
    if not a or not b: return 0.0
    base = SequenceMatcher(None, a, b).ratio()
    # בונוס אם המחרוזת הקצרה כלולה בארוכה
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if short and short in long_:
        base = max(base, 0.72)
    return base

# ── fetch_evrit (גרסה קבועה) ──────────────────────────────
def fetch_evrit(page, title, author):
    search_url = 'https://www.e-vrit.co.il/Search/' + urllib.parse.quote(title)
    try:
        page.goto(search_url, wait_until='domcontentloaded', timeout=25000)
        time.sleep(6.0)
    except Exception as e:
        return None, None, f'NAV ERR: {str(e)[:60]}'

    links = page.evaluate('''() => {
        const container = document.querySelector('[class*="product-list"]');
        if (!container) return [];
        const seen = new Set(); const out = [];
        container.querySelectorAll('a[href*="/Product/"]').forEach(a => {
            const m = a.href.match(/Product\/(\\d+)\//);
            if (!m) return;
            const id = m[1]; if (seen.has(id)) return; seen.add(id);
            const img = a.querySelector('img') || a.closest('[class]')?.querySelector('img');
            const alt = img?.alt?.trim() || '';
            const slug = decodeURIComponent(a.href.split('/Product/')[1]?.split('/').slice(1).join(' ') || '').replace(/_/g,' ').trim();
            const t = alt || slug;
            if (t.length < 2) return;
            out.push({ id, href: a.href, title: t });
        });
        return out.slice(0, 20);
    }''')

    if not links:
        return None, None, 'אין תוצאות בחיפוש'

    def _score(link):
        sim = title_similarity(title, link['title'])
        q_words = set(title.split())
        c_words = set(link['title'].split())
        extra = c_words - q_words
        penalty = min(0.18, len(extra) * 0.05)
        brevity = 0.02 if len(link['title']) <= len(title) + 5 else 0
        return sim - penalty + brevity

    best = max(links, key=_score)
    best_score = _score(best)
    if best_score < 0.45:
        return None, None, f'ציון נמוך ({best_score:.2f}) — {best["title"][:40]}'

    try:
        page.goto(best['href'], wait_until='domcontentloaded', timeout=20000)
        time.sleep(2.5)
    except Exception as e:
        return None, None, f'BOOK ERR: {str(e)[:60]}'

    data = page.evaluate("""() => {
        // מילות דחייה: תוכן ממשק (לא תקציר)
        const skipWords = ['\u05e7\u05e0\u05d9\u05d9\u05d4', '\u05dc\u05e1\u05dc', '\u05de\u05d7\u05d9\u05e8',
                           '\u05e9\u05e7\u05dc', '\u05e0\u05e8\u05e9\u05de', '\u05d4\u05ea\u05d7\u05d1\u05e8',
                           '\u05e2\u05d5\u05d2\u05d9', '\u05d1\u05ea\u05de\u05d5\u05e0\u05d4:',
                           '\u05d4\u05d5\u05e6\u05d0\u05d4:', '\u05ea\u05d0\u05e8\u05d9\u05da \u05d4\u05d5\u05e6\u05d0\u05d4:',
                           '\u05de\u05e1\u05e4\u05e8 \u05e2\u05de\u05d5\u05d3\u05d9\u05dd:', '\u05e7\u05d8\u05d2\u05d5\u05e8\u05d9\u05d4:'];
        // מסנן ביוגרפיה — מילות מפתח ביוגרפיות
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
        // 3+ שנים = כנראה ביוגרפיה/ביבליוגרפיה
        function hasMultipleYears(t) {
            const m = t.match(/\\b(1[89]\\d{2}|20[012]\\d)\\b/g);
            return m && m.length >= 3;
        }
        // תאריכים ביוגרפיים: (YYYY – YYYY)
        const bioDatesRe = /\\(\\d{4}[\\s\\u2013\\-]+\\d{4}\\)/;

        const paras = Array.from(document.querySelectorAll('p:not([class])'));
        const seen = new Set(); const parts = [];
        for (const p of paras) {
            const t = (p.textContent || '').trim();
            if (t.length < 40 || t.length > 2000) continue;
            if (seen.has(t.substring(0, 40))) continue;
            if (skipWords.some(w => t.includes(w))) continue;
            if (bioContains.some(w => t.includes(w))) continue;
            if (bioStarts.some(w => t.startsWith(w))) continue;
            if (bioDatesRe.test(t)) continue;
            if (hasMultipleYears(t)) continue;
            seen.add(t.substring(0, 40)); parts.push(t);
            if (parts.join(' ').length > 1800) break;
        }

        const tagsEl = document.querySelector('.page-bottom__group-tags') ||
                       document.querySelector('[class*="group-tags"]');
        let topics = '';
        if (tagsEl) {
            const txt = tagsEl.textContent.trim();
            const idx = txt.indexOf('\u05e0\u05d5\u05e9\u05d0\u05d9\u05dd');
            topics = idx >= 0 ? txt.slice(idx + 7).trim().replace(/\s+/g, ' ') : txt.trim();
        }
        return { desc: parts.join('\\n'), topics };
    }""")

    desc = (data.get('desc') or '').strip()
    topics = (data.get('topics') or '').strip()

    if not desc or len(desc) < 80:
        return None, None, f'תקציר קצר מדי ({len(desc)} תווים) — {best["title"][:40]}'

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
    return desc, matched, None


# ── טען xlsx ──────────────────────────────────────────────
def load_candidates(path):
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active
    rows = []
    for i, row in enumerate(ws.iter_rows(min_row=1, values_only=True), start=1):
        title  = (row[COL_TITLE  - 1] or '').strip()
        author = (row[COL_AUTHOR - 1] or '').strip()
        desc   = (row[COL_DESC   - 1] or '').strip()
        if title and not desc:
            rows.append({'row': i, 'title': title, 'author': author})
    wb.close()
    return rows


# ── main ──────────────────────────────────────────────────
def main():
    print(f'טוען קובץ: {XLSX_PATH}')
    candidates = load_candidates(XLSX_PATH)
    print(f'ספרים ללא תקציר: {len(candidates)}')

    random.seed(RANDOM_SEED)
    sample = random.sample(candidates, min(SAMPLE_SIZE, len(candidates)))
    print(f'מדגם: {len(sample)} ספרים\n')
    print('=' * 70)

    successes = 0
    failures  = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = ctx.new_page()

        for i, book in enumerate(sample, 1):
            title  = book['title']
            author = book['author']
            print(f'\n[{i:02d}/{len(sample)}] {title} / {author}')
            t0 = time.time()
            desc, matched, err = fetch_evrit(page, title, author)
            elapsed = time.time() - t0

            if desc:
                successes += 1
                print(f'  ✓ התאמה: {matched[:60]}')
                print(f'  תקציר ({len(desc)} תווים, {elapsed:.1f}ש): {desc[:180]}...' if len(desc) > 180 else f'  תקציר: {desc}')
            else:
                failures += 1
                reason = err or 'לא נמצא'
                print(f'  ✗ נכשל ({elapsed:.1f}ש): {reason}')

        browser.close()

    print('\n' + '=' * 70)
    print(f'סיכום: {successes}/{len(sample)} הצלחות ({100*successes//len(sample)}%)')
    print(f'כישלונות: {failures}')


if __name__ == '__main__':
    main()
