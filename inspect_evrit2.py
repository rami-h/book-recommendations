#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, io, json, time, urllib.parse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36').new_page()

    # --- 1. חיפוש עם המתנה ארוכה יותר ---
    print('=== 1. חיפוש עם wait_until=networkidle ===')
    query = 'יומנו של חנון'
    url = f'https://www.e-vrit.co.il/Search/{urllib.parse.quote(query)}'
    page.goto(url, wait_until='domcontentloaded', timeout=20000)
    time.sleep(4)  # המתן לרינדור JS

    result = page.evaluate('''() => {
        // נסה לאתר את מכולת תוצאות החיפוש
        const links = Array.from(document.querySelectorAll('a[href*="/Product/"]'));
        return links.slice(0, 10).map(a => {
            // חלץ כותרת מה-URL
            const parts = a.href.split('/Product/')[1] || '';
            const slug = parts.split('/').slice(1).join('/');
            const decoded = decodeURIComponent(slug).replace(/_/g, ' ');
            return {
                href: a.href,
                text: (a.textContent || '').trim().substring(0, 60),
                title_from_url: decoded.substring(0, 60),
                img_alt: (a.querySelector('img') ? a.querySelector('img').alt : '').substring(0, 60)
            };
        });
    }''')
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # --- 2. דף ספר ספציפי ---
    # ננסה ספר שיומנו של חנון ייתכן שיש לו
    print('\n=== 2. דף ספר ===')
    # מאגר הנתונים שלנו יש את הקישורים - ניקח את הראשון שהכותרת שלו דומה
    # בינתיים נסה ספר ידוע
    page.goto('https://www.e-vrit.co.il/Product/16071/%D7%99%D7%95%D7%9E%D7%A0%D7%95_%D7%A9%D7%9C_%D7%97%D7%A0%D7%95%D7%9F', wait_until='domcontentloaded', timeout=20000)
    time.sleep(3)

    book_data = page.evaluate('''() => {
        const out = {};
        // כותרת
        out.title = (document.querySelector('h1, [class*="title"], [class*="name"]') || {}).textContent?.trim()?.substring(0, 80);
        // תיאור/תקציר
        const descSelectors = ['[class*="desc"], [class*="about"], [class*="synopsis"], [class*="summary"], [id*="desc"], [id*="about"]'];
        for (const sel of descSelectors) {
            const el = document.querySelector(sel);
            if (el && el.textContent.trim().length > 100) {
                out.desc = el.textContent.trim().substring(0, 400);
                out.desc_selector = sel;
                break;
            }
        }
        // קטגוריה
        out.categories = Array.from(document.querySelectorAll('a[href*="/Category/"]')).map(a=>({
            text: a.textContent.trim(), href: a.href
        })).slice(0, 5);
        // מחבר
        out.author = Array.from(document.querySelectorAll('a[href*="/Author/"], [class*="author"]')).map(a=>a.textContent.trim()).slice(0,3);
        // כל h2, h3 לאיתור מבנה
        out.headings = Array.from(document.querySelectorAll('h2,h3')).map(h=>h.textContent.trim().substring(0,40)).slice(0,8);
        out.url = location.href;
        return out;
    }''')
    print(json.dumps(book_data, ensure_ascii=False, indent=2))

    browser.close()
