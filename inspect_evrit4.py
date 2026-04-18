#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, io, json, time, urllib.parse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright

PRODUCT_URL = 'https://www.e-vrit.co.il/Product/12108/%D7%99%D7%95%D7%9E%D7%A0%D7%95_%D7%A9%D7%9C_%D7%97%D7%A0%D7%95%D7%9F_1'

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
    responses = {}

    def on_response(resp):
        url = resp.url
        if 'api' in url.lower() and resp.status == 200:
            try:
                body = resp.text()
                if len(body) > 50 and len(body) < 50000:
                    responses[url] = body[:2000]
            except Exception:
                pass

    ctx.on('response', on_response)
    page = ctx.new_page()
    page.goto(PRODUCT_URL, wait_until='domcontentloaded', timeout=25000)
    time.sleep(5)

    print('=== API Responses ===')
    for url, body in responses.items():
        if any(x in body for x in ['תקציר', 'תיאור', 'description', 'about', 'text']):
            print(f'\nURL: {url}')
            print(f'Body: {body[:500]}')
            print()

    print('\n=== DOM dump: כל הטקסטים ארוכים ===')
    texts = page.evaluate('''() => {
        const results = [];
        const all = Array.from(document.querySelectorAll('p, div, span, section'));
        const seen = new Set();
        for (const el of all) {
            if (el.querySelectorAll('div,p,section').length > 2) continue;
            const t = (el.textContent || '').trim();
            if (t.length > 100 && t.length < 2000 && !seen.has(t.substring(0,60))) {
                seen.add(t.substring(0,60));
                results.push({
                    tag: el.tagName,
                    cls: el.className.substring(0,50),
                    text: t.substring(0, 300)
                });
            }
            if (results.length >= 15) break;
        }
        return results;
    }''')
    print(json.dumps(texts, ensure_ascii=False, indent=2))

    print('\n=== ספציפי: אחרי heading "עוד על הספר" ===')
    desc_info = page.evaluate('''() => {
        const all = Array.from(document.querySelectorAll('*'));
        for (const el of all) {
            if ((el.textContent || '').trim() === 'עוד על הספר' && el.children.length === 0) {
                let parent = el.parentElement;
                for (let i=0; i<5; i++) {
                    const sibling = parent.nextElementSibling;
                    if (sibling) {
                        const t = sibling.textContent.trim();
                        if (t.length > 80) return {found: true, text: t.substring(0,500), tag: sibling.tagName, cls: sibling.className};
                    }
                    parent = parent.parentElement;
                    if (!parent) break;
                }
            }
        }
        return {found: false};
    }''')
    print(json.dumps(desc_info, ensure_ascii=False, indent=2))

    browser.close()
