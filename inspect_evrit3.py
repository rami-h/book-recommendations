#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, io, json, time, urllib.parse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
    api_calls = []

    # ציד ה-API
    def on_request(req):
        url = req.url
        if any(x in url for x in ['api', 'search', 'product', 'book', 'json', 'graphql']):
            api_calls.append({'method': req.method, 'url': url[:120]})

    ctx.on('request', on_request)
    page = ctx.new_page()

    # --- חיפוש + לכידת API ---
    print('=== ציד API calls ===')
    query = 'יומנו של חנון'
    page.goto(f'https://www.e-vrit.co.il/Search/{urllib.parse.quote(query)}',
              wait_until='domcontentloaded', timeout=25000)
    time.sleep(6)  # המתן לכל הקריאות

    print(f'API calls ({len(api_calls)}):')
    for c in api_calls[:20]:
        print(f'  [{c["method"]}] {c["url"]}')

    # --- ניסיון לאתר container תוצאות ---
    print('\n=== Containers בדף החיפוש ===')
    containers = page.evaluate('''() => {
        const selectors = [
            '[class*="search"]', '[class*="result"]', '[class*="product-list"]',
            '[class*="grid"]', '[class*="item"]', 'main', '[role="main"]'
        ];
        const found = [];
        for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (el) {
                const links = el.querySelectorAll('a[href*="/Product/"]').length;
                if (links > 0) {
                    found.push({sel, links, cls: el.className.substring(0,60)});
                }
            }
        }
        return found;
    }''')
    print(json.dumps(containers, ensure_ascii=False, indent=2))

    # --- כל הכותרות מ-img.alt בתוצאות ---
    print('\n=== תוצאות חיפוש (מ-img alt) ===')
    results = page.evaluate('''() => {
        return Array.from(document.querySelectorAll('a[href*="/Product/"]')).map(a => {
            const img = a.querySelector('img') || a.closest('[class*="item"], [class*="product"]')?.querySelector('img');
            const slug = decodeURIComponent(a.href.split('/Product/')[1]?.split('/').slice(1).join(' ') || '').replace(/_/g,' ');
            return {
                id: a.href.match(/Product\/(\d+)/)?.[1],
                title_slug: slug.substring(0, 50),
                img_alt: img?.alt?.substring(0, 50) || ''
            };
        }).filter((v,i,a)=>a.findIndex(x=>x.id===v.id)===i).slice(0,15);
    }''')
    print(json.dumps(results, ensure_ascii=False, indent=2))

    # --- דף ספר: תקציר ---
    print('\n=== דף ספר: יומנו של חנון (חיפוש ישיר) ===')
    # ניסה ספר ידוע בe-vrit
    page.goto('https://www.e-vrit.co.il/Product/4977/%D7%99%D7%95%D7%9E%D7%A0%D7%95_%D7%A9%D7%9C_%D7%97%D7%A0%D7%95%D7%9F_-_%D7%92%D7%A8%D7%A1%D7%94_%D7%97%D7%93%D7%A9%D7%94',
              wait_until='domcontentloaded', timeout=20000)
    time.sleep(3)
    book = page.evaluate('''() => {
        const out = { url: location.href };
        // כותרת
        out.h1 = document.querySelector('h1')?.textContent?.trim()?.substring(0,60);
        // תוכן מתחת ל"עוד על הספר"
        const headings = Array.from(document.querySelectorAll('h2,h3,h4'));
        for (const h of headings) {
            if (h.textContent.includes('עוד על הספר') || h.textContent.includes('תיאור') || h.textContent.includes('על הספר')) {
                // אסוף טקסט מהאח הבא
                let next = h.nextElementSibling;
                const texts = [];
                while (next && texts.join(' ').length < 600) {
                    const t = next.textContent.trim();
                    if (t) texts.push(t);
                    next = next.nextElementSibling;
                }
                out.desc_heading = h.textContent.trim();
                out.desc = texts.join(' ').substring(0, 600);
                break;
            }
        }
        // קטגוריה ספציפית לספר
        out.book_cats = Array.from(document.querySelectorAll('a[href*="/Category/"]'))
            .map(a => a.textContent.trim()).filter(t=>t.length>1 && t.length<40);
        // נושאים
        out.topics = Array.from(document.querySelectorAll('[class*="topic"], [class*="tag"], [class*="subject"]'))
            .map(e => e.textContent.trim()).filter(t=>t.length>1 && t.length<40).slice(0,10);
        return out;
    }''')
    print(json.dumps(book, ensure_ascii=False, indent=2))

    browser.close()
