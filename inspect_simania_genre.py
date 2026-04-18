#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""בדיקת מבנה דף ספר בסימניה לחילוץ קטגוריה/ז'אנר."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright

# ספרים ידועים שיש להם דף בסימניה (מהריצה הקודמת)
URL = 'https://simania.co.il/bookdetails.php?item_id=50964'  # מישהו לרוץ איתו

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_context(user_agent='Mozilla/5.0').new_page()
    page.goto(URL, wait_until='domcontentloaded', timeout=20000)
    page.wait_for_timeout(2000)

    # חפש קישורי קטגוריה
    cats = page.evaluate('''() => {
        const out = { breadcrumbs: [], category_links: [], tags: [], meta: {} };
        // breadcrumbs
        document.querySelectorAll('nav a, .breadcrumb a, [class*="breadcrumb"] a').forEach(a => {
            out.breadcrumbs.push({text: a.textContent.trim(), href: a.href});
        });
        // כל קישור שמכיל categories או category ב-href
        document.querySelectorAll('a[href*="categories"], a[href*="category"], a[href*="genre"], a[href*="cat="]').forEach(a => {
            out.category_links.push({text: a.textContent.trim(), href: a.href});
        });
        // מילות מפתח או תגיות
        document.querySelectorAll('[class*="tag"], [class*="genre"], [class*="category"]').forEach(el => {
            if (el.children.length < 3) {
                const txt = el.textContent.trim();
                if (txt && txt.length < 100) out.tags.push({tag: el.className, text: txt});
            }
        });
        // כל טקסט שמופיע ליד "קטגוריה" או "ז'אנר"
        const allText = document.body.innerText;
        const lines = allText.split('\\n').map(l => l.trim()).filter(l => l);
        for (let i = 0; i < lines.length; i++) {
            if (lines[i].includes('קטגור') || lines[i].includes('ז\\'אנר') || lines[i].includes('סוג')) {
                out.meta['line_' + i] = lines[i] + ' | next: ' + (lines[i+1] || '');
            }
        }
        return out;
    }''')

    import json
    print(json.dumps(cats, ensure_ascii=False, indent=2))
    browser.close()
