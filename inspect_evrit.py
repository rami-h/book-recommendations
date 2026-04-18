#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""בדיקת מבנה e-vrit.co.il — חיפוש + דף ספר."""
import sys, io, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright

QUERY = 'יומנו של חנון'

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36').new_page()

    # --- בדיקת דף חיפוש ---
    print('=== 1. חיפוש ===')
    page.goto('https://www.e-vrit.co.il', wait_until='domcontentloaded', timeout=20000)
    time.sleep(2)

    # נסה לאתר תיבת חיפוש
    search_info = page.evaluate('''() => {
        const inputs = Array.from(document.querySelectorAll('input[type=search], input[type=text], input[placeholder*="חיפ"], input[placeholder*="search"]'));
        return inputs.map(i => ({
            type: i.type, placeholder: i.placeholder,
            name: i.name, id: i.id, cls: i.className.substring(0, 60)
        }));
    }''')
    print('תיבות חיפוש:', json.dumps(search_info, ensure_ascii=False))

    # נסה לבצע חיפוש דרך URL ישיר
    print('\n=== 2. נסיון URL חיפוש ===')
    import urllib.parse
    urls_to_try = [
        f'https://www.e-vrit.co.il/Search/{urllib.parse.quote(QUERY)}',
        f'https://www.e-vrit.co.il/search?q={urllib.parse.quote(QUERY)}',
        f'https://www.e-vrit.co.il/?s={urllib.parse.quote(QUERY)}',
    ]
    for url in urls_to_try:
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=15000)
            time.sleep(2)
            result = page.evaluate('''() => ({
                url: location.href,
                title: document.title,
                product_links: Array.from(document.querySelectorAll('a[href*="/Product/"], a[href*="/product/"], a[href*="/book/"], a[href*="/Books/"]')).slice(0,5).map(a=>({href:a.href, text:(a.textContent||'').trim().substring(0,40)})),
                total_links: document.querySelectorAll('a').length
            })''')
            print(f'URL: {url}')
            print(f'  title: {result["title"][:60]}')
            print(f'  product_links: {json.dumps(result["product_links"], ensure_ascii=False)}')
            print()
        except Exception as e:
            print(f'  ERR: {e}')

    # --- בדיקה דרך תיבת חיפוש ---
    print('=== 3. חיפוש דרך תיבה ===')
    page.goto('https://www.e-vrit.co.il', wait_until='domcontentloaded', timeout=20000)
    time.sleep(2)
    try:
        # מלא תיבת חיפוש
        page.fill('input[type=search], input[placeholder*="חיפ"]', QUERY)
        time.sleep(0.5)
        page.keyboard.press('Enter')
        time.sleep(3)
        result = page.evaluate('''() => ({
            url: location.href,
            products: Array.from(document.querySelectorAll('a[href*="Product"], a[href*="product"], [class*="product"] a')).slice(0,8).map(a=>({href:a.href.substring(0,80), text:(a.textContent||'').trim().substring(0,50)}))
        })''')
        print('URL אחרי חיפוש:', result['url'])
        print('תוצאות:', json.dumps(result['products'], ensure_ascii=False, indent=2))
    except Exception as e:
        print(f'ERR: {e}')

    browser.close()
