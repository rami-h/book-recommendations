#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Query simania for the 5 test-run books and dump results."""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from scrape_descriptions import fetch_simania
from playwright.sync_api import sync_playwright

OUT = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\simania_test_dump.json'

# The 5 books that succeeded in the earlier test run (from log)
targets = [
    ('אוצר המלך', "ווטסון ג'ודי"),
    ('לונדון בולווארד', 'ברואן קן'),
    ('תשמעו סיפור', 'בשביס זינגר יצחק'),
    ('זה הדברים', 'ברדוגו סמי'),
    ('יומנו של חנון', "קיני ג'ף"),
]

results = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(user_agent='Mozilla/5.0')
    page = ctx.new_page()
    for i, (title, author) in enumerate(targets, 1):
        print(f'[{i}/{len(targets)}] {title} / {author}')
        try:
            result = fetch_simania(page, title, author)
            if isinstance(result, tuple):
                desc, matched = result
            else:
                desc, matched = result, None
        except Exception as e:
            desc, matched = None, None
            print(f'  ERR: {e}')
        entry = {
            'title': title,
            'author': author,
            'matched_title': matched,
            'description': desc,
            'length': len(desc) if desc else 0,
        }
        results.append(entry)
        if desc:
            print(f'  OK [{len(desc)}]  matched="{matched}"')
            print(f'  {desc[:150]}...')
        else:
            print('  -- not found')
        print()
    browser.close()

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

ok = sum(1 for r in results if r['description'])
print(f'Saved {ok}/{len(targets)} to {OUT}')
