#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
evrit_scraper.py — שואב תקצירים מ-e-vrit.co.il ישירות ל-local_library.js
שימוש:
    py -3 evrit_scraper.py --validate         # מדגם 10 דוגמאות ויצא
    py -3 evrit_scraper.py --all --approve    # ריצה מלאה (ללא prompt)
    py -3 evrit_scraper.py --all --approve --resume   # המשך מ-checkpoint
    py -3 evrit_scraper.py --retry --approve  # ניסוי חוזר לנכשלים עם כותרות מנוקות
"""
import sys, io, re, time, random, json, argparse, os, urllib.parse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import openpyxl
from playwright.sync_api import sync_playwright
from difflib import SequenceMatcher

LIBRARY_JS = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\local_library.js'
CKPT_FILE  = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\evrit_checkpoint.jsonl'

# xlsx כמקור רשימת הספרים (עמודות)
XLSX_IN    = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\catalog_no_match_scraped.xlsx'
COL_ID     = 1   # A
COL_TITLE  = 2   # B
COL_AUTHOR = 3   # C
COL_DESC   = 13  # M

CHECKPOINT_EVERY = 25
# checkpoint נפרד לריטריי — כדי לא לדרוס את הישן
RETRY_CKPT_FILE = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\evrit_retry_checkpoint.jsonl'


def log(msg):
    print(msg, flush=True)


# ── similarity ──────────────────────────────────────────────
def _norm(s):
    s = re.sub(r'[\u0591-\u05C7]', '', s)
    s = re.sub(r'[^\u05D0-\u05EAa-zA-Z0-9\s]', ' ', s)
    return ' '.join(s.split()).strip()

def title_similarity(a, b):
    a, b = _norm(a).lower(), _norm(b).lower()
    if not a or not b: return 0.0
    base = SequenceMatcher(None, a, b).ratio()
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if short and short in long_:
        base = max(base, 0.72)
    return base


# ── fetch_evrit ──────────────────────────────────────────────
def fetch_evrit(page, title, author):
    """מחזיר (desc, matched_title) או (None, None) עם הודעה."""
    search_url = 'https://www.e-vrit.co.il/Search/' + urllib.parse.quote(title)
    try:
        page.goto(search_url, wait_until='domcontentloaded', timeout=25000)
        time.sleep(6.0)
    except Exception as e:
        return None, None

    links = page.evaluate('''() => {
        const container = document.querySelector('[class*="product-list"]');
        if (!container) return [];
        const seen = new Set(); const out = [];
        container.querySelectorAll('a[href*="/Product/"]').forEach(a => {
            const m = a.href.match(/Product\/(\d+)\//);
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
        return None, None

    def _score(link):
        sim = title_similarity(title, link['title'])
        q_words = set(title.split())
        c_words = set(link['title'].split())
        extra = c_words - q_words
        penalty = min(0.18, len(extra) * 0.05)
        brevity = 0.02 if len(link['title']) <= len(title) + 5 else 0
        return sim - penalty + brevity

    best = max(links, key=_score)
    if _score(best) < 0.45:
        return None, None

    try:
        page.goto(best['href'], wait_until='domcontentloaded', timeout=20000)
        time.sleep(2.5)
    except Exception:
        return None, None

    data = page.evaluate("""() => {
        const skipWords = ['\u05e7\u05e0\u05d9\u05d9\u05d4', '\u05dc\u05e1\u05dc', '\u05de\u05d7\u05d9\u05e8',
                           '\u05e9\u05e7\u05dc', '\u05e0\u05e8\u05e9\u05de', '\u05d4\u05ea\u05d7\u05d1\u05e8',
                           '\u05e2\u05d5\u05d2\u05d9', '\u05d1\u05ea\u05de\u05d5\u05e0\u05d4:',
                           '\u05d4\u05d5\u05e6\u05d0\u05d4:', '\u05ea\u05d0\u05e8\u05d9\u05da \u05d4\u05d5\u05e6\u05d0\u05d4:',
                           '\u05de\u05e1\u05e4\u05e8 \u05e2\u05de\u05d5\u05d3\u05d9\u05dd:', '\u05e7\u05d8\u05d2\u05d5\u05e8\u05d9\u05d4:'];
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
        return None, None

    desc = re.sub(r'\s+', ' ', desc).strip()
    desc = re.sub(r'מקור:\s*ויקיפדיה\s*https?://\S+\s*', '', desc).strip()
    desc = re.sub(r'\s*(קרא עוד|קראו עוד)\s*$', '', desc).strip()

    if len(desc) > 2500:
        cut = desc[:2500]
        m = re.search(r'[.!?](?=[^.!?]*$)', cut)
        desc = cut[:m.start()+1].strip() if (m and m.start() > 1500) else cut + '...'

    if len(desc) < 80:
        return None, None

    matched = best['title']
    if topics:
        matched += f' | נושאים: {topics[:80]}'
    return desc, matched


# ── Sample validation ────────────────────────────────────────
def validate_sample(page, candidates, n=10):
    """
    בוחר n ספרים אקראיים, מריץ fetch_evrit ומדפיס טבלת השוואה.
    מחזיר מספר ההצלחות. לא מבקש אישור — הרצה נפרדת עם --approve.
    """
    random.seed(42)
    sample = random.sample(candidates, min(n, len(candidates)))

    W_TITLE = 30
    W_MATCH = 32
    W_DESC  = 52

    log(f'\n{"="*72}')
    log(f'  בדיקת מדגם e-vrit — {len(sample)} ספרים אקראיים')
    log(f'{"="*72}')
    log(f'  {"כותרת קיימת":<{W_TITLE}} | {"כותרת שנמצאה":<{W_MATCH}} | תקציר (100 תווים)')
    log('  ' + '-' * (W_TITLE + W_MATCH + W_DESC + 6))

    successes = 0
    for book in sample:
        try:
            desc, matched = fetch_evrit(page, book['title'], book['author'])
        except Exception as e:
            desc, matched = None, f'ERR: {str(e)[:28]}'

        if desc:
            successes += 1
            match_title = (matched or '').split(' | נושאים')[0]
            snippet     = desc[:W_DESC].replace('\n', ' ')
            status = 'V'
        else:
            match_title = '—'
            snippet     = '—'
            status = 'X'

        log(f'  {status} {book["title"][:W_TITLE]:<{W_TITLE}} | {match_title[:W_MATCH]:<{W_MATCH}} | {snippet}')

    log(f'\n  הצלחות: {successes}/{len(sample)} ({100*successes//len(sample)}%)')
    log(f'{"="*72}')
    log('  לריצה מלאה לאחר אישור: py -3 evrit_scraper.py --all --approve')
    log(f'{"="*72}\n')
    return successes


# ── JSONL checkpoint ──────────────────────────────────────────
def load_checkpoint():
    """טוען checkpoint JSONL — מחזיר {book_id: entry}."""
    done = {}
    if not os.path.exists(CKPT_FILE):
        return done
    with open(CKPT_FILE, 'r', encoding='utf-8') as f:
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


def append_checkpoint(entry):
    """מוסיף רשומה אחת ל-JSONL מיד (עמיד לקריסות)."""
    with open(CKPT_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


# ── local_library.js helpers ──────────────────────────────────
def load_library():
    with open(LIBRARY_JS, 'r', encoding='utf-8') as f:
        content = f.read()
    start = content.index('[')
    end   = content.rindex(']') + 1
    books = json.loads(content[start:end])
    return books, content[:start], content[end:]

def save_library(books, prefix, suffix):
    with open(LIBRARY_JS, 'w', encoding='utf-8') as f:
        f.write(prefix + json.dumps(books, ensure_ascii=False, indent=2) + suffix)


# ── xlsx — מקור רשימת ספרים ──────────────────────────────────
def load_xlsx_candidates(path):
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active
    rows = []
    for row in ws.iter_rows(min_row=1, values_only=True):
        book_id = str(row[COL_ID    - 1] or '').strip()
        title   = (row[COL_TITLE - 1] or '').strip()
        author  = (row[COL_AUTHOR- 1] or '').strip()
        if book_id and title:
            rows.append({'id': book_id, 'title': title, 'author': author})
    wb.close()
    return rows


# ── ניקוי כותרות לניסיון חוזר ────────────────────────────────
def clean_title_for_retry(title):
    """
    מנקה כותרת עבור ניסיון חוזר ב-e-vrit:
    - מסיר תת-כותרת אחרי / : — ()
    - מסיר מספר חלק (חלק א, כרך ב, ספר 1...)
    - מסיר שם מחבר שנספח לכותרת
    מחזיר רשימה של גרסאות לנסות (מהמנוקה ביותר לפחות).
    """
    variants = [title]

    # הסר הכל אחרי / (שם מחבר שנספח)
    t = re.split(r'\s*/\s*', title)[0].strip()
    if t != title and len(t) > 2:
        variants.append(t)

    # הסר הכל אחרי : —
    for sep in [' : ', ' — ', ' - ']:
        t2 = t.split(sep)[0].strip()
        if t2 and t2 != t and len(t2) > 2:
            variants.append(t2)
            t = t2
            break

    # הסר סוגריים בסוף
    t3 = re.sub(r'\s*[\(\[].*?[\)\]]\s*$', '', t).strip()
    if t3 and t3 != t and len(t3) > 2:
        variants.append(t3)

    # הסר מספר חלק/כרך/ספר בסוף
    t4 = re.sub(r'\s*(חלק|כרך|ספר|חלק|פרק|book|part|vol)\s*[\d א-ת]+\s*$', '', t3 or t, flags=re.IGNORECASE).strip()
    if t4 and t4 != (t3 or t) and len(t4) > 2:
        variants.append(t4)

    # הסר מספר בסוף (1, 2, ...)
    t5 = re.sub(r'\s+[\d]+\s*$', '', t4 or t3 or t).strip()
    if t5 and t5 != (t4 or t3 or t) and len(t5) > 2:
        variants.append(t5)

    # ייחודי ובסדר
    seen = set()
    result = []
    for v in variants:
        if v not in seen and len(v) > 1:
            seen.add(v)
            result.append(v)
    return result


def run_phase(page, to_process, books_by_id, js_prefix, js_suffix,
              ckpt_file, done_ids, success_count, failed_count,
              use_retry_cleaning=False):
    """לולאת עיבוד ראשית — משותפת ל-all ול-retry."""
    for i, book in enumerate(to_process, 1):
        title  = book['title']
        author = book['author']

        if use_retry_cleaning:
            variants = clean_title_for_retry(title)
        else:
            variants = [title]

        log(f'[{i:04d}/{len(to_process)}] {title[:40]} / {author[:20]}')
        if use_retry_cleaning and len(variants) > 1:
            log(f'  variants: {variants[1:]}')

        t0 = time.time()
        desc = matched = None
        for variant in variants:
            try:
                desc, matched = fetch_evrit(page, variant, author)
            except Exception as e:
                log(f'  !! שגיאה: {str(e)[:60]}')
                desc, matched = None, None
            if desc:
                break

        elapsed = time.time() - t0

        # כתוב לחדשות JSONL מיד
        entry = {'id': book['id'], 'title': title, 'desc': desc or '', 'matched': matched or ''}
        with open(ckpt_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        done_ids.add(book['id'])

        if desc:
            success_count += 1
            if book['id'] in books_by_id:
                books_by_id[book['id']]['description'] = desc
                books_by_id[book['id']]['description_source'] = 'evrit'
            log(f'  V ({elapsed:.1f}s) {matched[:60]}')
            log(f'    {desc[:120]}...' if len(desc) > 120 else f'    {desc}')
        else:
            failed_count += 1
            log(f'  X ({elapsed:.1f}s)')

        if i % CHECKPOINT_EVERY == 0:
            save_library(list(books_by_id.values()), js_prefix, js_suffix)
            log(f'  [שמור] הצלחות={success_count}, כישלונות={failed_count}')

    return success_count, failed_count


# ── main ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--all',      action='store_true', help='ריצה על ספרים שלא נוסו')
    parser.add_argument('--retry',    action='store_true', help='ניסוי חוזר לנכשלים עם כותרות מנוקות')
    parser.add_argument('--approve',  action='store_true', help='אישור מראש — מריץ מיד ללא prompt')
    parser.add_argument('--validate', action='store_true', help='מדגם 10 דוגמאות ויצא')
    parser.add_argument('--sample',   type=int, default=0, help='מדגם N ספרים')
    parser.add_argument('--resume',   action='store_true', help='המשך מ-JSONL checkpoint')
    args = parser.parse_args()

    if not (args.all or args.retry or args.sample or args.validate):
        parser.print_help()
        return

    # טען קטלוג ראשי
    log(f'טוען {LIBRARY_JS}...')
    books, js_prefix, js_suffix = load_library()
    books_by_id = {b['id']: b for b in books}
    log(f'  {len(books)} ספרים')

    # טען checkpoint — אלה שכבר עובדו
    ckpt = load_checkpoint()
    done_ids = set(ckpt.keys())
    success_count = sum(1 for e in ckpt.values() if e.get('desc'))
    log(f'  checkpoint: {len(done_ids)} ספרים כבר עובדו ({success_count} הצלחות)')

    # הזרק תוצאות מ-checkpoint שעדיין חסרות ב-library
    injected = 0
    for book_id, entry in ckpt.items():
        if book_id in books_by_id and entry.get('desc') and not books_by_id[book_id].get('description'):
            books_by_id[book_id]['description'] = entry['desc']
            books_by_id[book_id]['description_source'] = 'evrit'
            injected += 1
    if injected:
        log(f'  הוזרקו מ-checkpoint: {injected}')

    # בנה רשימת מועמדים — כל ספרי ה-library ללא תקציר, לא כולל checkpoint
    needs = [
        {'id': b['id'], 'title': b.get('title', ''), 'author': b.get('author', '')}
        for b in books
        if not b.get('description', '').strip() and b['id'] not in done_ids
    ]
    log(f'  {len(needs)} ספרים ללא תקציר (לא כולל checkpoint)')

    desc_before = sum(1 for b in books if b.get('description', '').strip())

    # ── בנה רשימות לפי מצב ────────────────────────────────────
    # --retry: ספרים שנכשלו בניסיון הראשון (ב-checkpoint ללא desc)
    # --all:   ספרים שלא נוסו כלל
    retry_ckpt = {}
    if args.retry:
        # טען checkpoint ריטריי קיים
        if os.path.exists(RETRY_CKPT_FILE):
            with open(RETRY_CKPT_FILE, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    try:
                        e = json.loads(line)
                        retry_ckpt[e['id']] = e
                    except Exception:
                        pass

        # ספרים שנכשלו בניסיון הראשון, לא הצליחו בריטריי, ועדיין בלי תקציר
        failed_ids = {bid for bid, e in ckpt.items() if not e.get('desc')}
        to_process = [
            {'id': b['id'], 'title': b.get('title', ''), 'author': b.get('author', '')}
            for b in books
            if b['id'] in failed_ids
            and not b.get('description', '').strip()
            and b['id'] not in retry_ckpt
        ]
        active_ckpt_file = RETRY_CKPT_FILE
        active_done_ids  = set(retry_ckpt.keys())
        use_cleaning = True
        log(f'  {len(to_process)} ספרים לניסוי חוזר (כותרות מנוקות)')
    else:
        if args.sample:
            random.seed(77)
            to_process = random.sample(needs, min(args.sample, len(needs)))
        else:
            to_process = needs
        active_ckpt_file = CKPT_FILE
        active_done_ids  = done_ids
        use_cleaning = False

    log(f'לעיבוד: {len(to_process)} ספרים')

    failed_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = ctx.new_page()

        # ── validate / approve ───────────────────────────────────
        if args.validate:
            pool = to_process if to_process else needs
            validate_sample(page, pool, n=10)
            browser.close()
            return

        if not args.approve and not args.resume:
            validate_sample(page, to_process if to_process else needs, n=10)
            log('הוסף --approve כדי להריץ.')
            browser.close()
            return

        # ── ריצה ────────────────────────────────────────────────
        success_count, failed_count = run_phase(
            page, to_process, books_by_id, js_prefix, js_suffix,
            active_ckpt_file, active_done_ids,
            success_count, failed_count,
            use_retry_cleaning=use_cleaning,
        )

        browser.close()

    # שמירה סופית
    save_library(list(books_by_id.values()), js_prefix, js_suffix)

    desc_after = sum(1 for b in books_by_id.values() if b.get('description', '').strip())
    total_books = len(books)

    log(f'\n{"="*60}')
    log(f'סיכום:')
    log(f'  הצלחות בריצה זו: {success_count}')
    log(f'  כישלונות בריצה זו: {failed_count}')
    log(f'\n  כיסוי לפני: {desc_before}/{total_books} ({100*desc_before//total_books}%)')
    log(f'  כיסוי אחרי: {desc_after}/{total_books} ({100*desc_after//total_books}%)')
    log(f'  דלתא:       +{desc_after - desc_before} תקצירים')
    log(f'\n  checkpoint: {active_ckpt_file}')
    log(f'  שמור ב: {LIBRARY_JS}')


if __name__ == '__main__':
    main()
