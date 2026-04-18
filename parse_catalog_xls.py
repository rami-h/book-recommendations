#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
סקריפט חילוץ קטלוג ספריית שחרות מ-XLS
"""

import xlrd
import re
import json


def guess_era(year_str):
    try:
        year = int(float(year_str))
        if year < 1950: return 'קלאסי'
        elif year < 2000: return 'מודרני'
        else: return 'בן-זמננו'
    except:
        return ''


# מיפוי סוגות לקטגוריות רחבות
GENRE_MAP = {
    'רומן': 'ספרות יפה',
    'רומן היסטורי': 'רומן היסטורי',
    'רומן רומנטי': 'רומנטי',
    'רומן אוטוביוגרפי': 'ביוגרפיה',
    'רומן ביוגרפי': 'ביוגרפיה',
    'רומן גרפי': 'רומן גרפי',
    'מתח': 'מותחן',
    'מותחן פסיכולוגי': 'מותחן',
    'בלש': 'בלשי',
    'פנטזיה': 'פנטזיה',
    'מדע בדיוני': 'מדע בדיוני',
    'אהבה ורומנטיקה': 'רומנטי',
    'ארוטיקה': 'רומנטי',
    'קומיקס': 'קומיקס',
    'שירה': 'שירה',
    'סיפורים': 'סיפורים קצרים',
    'סיפורים קצרים': 'סיפורים קצרים',
    'קובץ סיפורים': 'סיפורים קצרים',
    'נובלות': 'סיפורים קצרים',
    'פרגמנטים': 'סיפורים קצרים',
    'מחזה': 'דרמה',
    'תסריט': 'דרמה',
    'הומור וסאטירה': 'הומור',
    'ממואר': 'ביוגרפיה',
    'מסות': 'מסות',
    'אגדות': 'אגדות',
    'דיסטופיה': 'מדע בדיוני',
    'היסטוריה חלופית': 'רומן היסטורי',
}

# מיפוי סוג (type) לז'אנרים
TYPE_MAP = {
    'סיפורת': 'ספרות יפה',
    'ספרות יפה': 'ספרות יפה',
    'עיון': 'עיון',
    'ספר עיון': 'עיון',
    'שירה': 'שירה',
    'מחזות': 'דרמה',
    'ספרי ילדים ונוער': 'ילדים ונוער',
    'עיון ילדים ונוער': 'עיון',
    'יעץ': 'עיון',
    'ספר קולי': 'ספר קולי',
}


def parse_xls(xls_path, output_path):
    wb = xlrd.open_workbook(xls_path)
    sh = wb.sheet_by_index(0)

    # Read headers
    headers = [str(sh.cell_value(0, c)).strip() for c in range(sh.ncols)]
    print(f"Headers: {headers}")
    print(f"Total rows: {sh.nrows - 1}")

    # Map column indices
    col = {}
    for i, h in enumerate(headers):
        col[h] = i

    books = []
    seen = set()

    for r in range(1, sh.nrows):
        def val(col_name):
            if col_name not in col:
                return ''
            v = sh.cell_value(r, col[col_name])
            if isinstance(v, float):
                if v == int(v):
                    return str(int(v))
                return str(v)
            return str(v).strip()

        title = val('כותר').strip()
        if not title or len(title) < 2:
            continue

        # Clean title
        title = re.sub(r'^\[.*?\]\s*', '', title).strip('"').strip("'").strip()

        # Deduplicate
        key = re.sub(r'\s+', ' ', title.lower().strip())
        if key in seen:
            continue
        seen.add(key)

        author = val('מחבר/ת').strip().strip(':')
        # Fix author order: "שם משפחה שם פרטי" -> as-is (XLS already has good format)

        # Build genres list
        genres = []
        book_type = val('סוג')  # סיפורת, עיון, etc.
        sub_genre = val('סוגה')  # רומן, מתח, פנטזיה, etc.

        # Add sub-genre first (more specific)
        if sub_genre and sub_genre in GENRE_MAP:
            mapped = GENRE_MAP[sub_genre]
            if mapped not in genres:
                genres.append(mapped)
        elif sub_genre:
            genres.append(sub_genre)

        # Add broad type if different
        if book_type and book_type in TYPE_MAP:
            mapped_type = TYPE_MAP[book_type]
            if mapped_type not in genres:
                genres.append(mapped_type)

        # Audience
        audience_raw = val('קהל יעד')
        audience = []
        if audience_raw == 'ילדים':
            audience = ['ילדים']
        elif audience_raw == 'נוער':
            audience = ['נוער']
        elif audience_raw == 'מבוגרים':
            audience = ['מבוגרים']

        # Description
        desc = val('תקציר').strip()
        if desc:
            desc = re.sub(r'\s+', ' ', desc).strip()
            desc = desc[:500]

        # Notes
        notes = val('הערות').strip()

        # Year
        year_raw = val('שנה').strip().lstrip('-')

        # Shelf
        shelf = val('ס. מדף').strip()

        # Series
        series = val('סדרה').strip()

        # Publisher
        publisher = val('מוציא לאור').strip()

        book = {
            'id': f'lib{len(books)+1:04d}',
            'title': title,
            'author': author,
            'genres': genres,
            'sub_genre': sub_genre,  # Keep original sub-genre for explanations
            'themes': [],
            'mood': [],
            'style': [],
            'audience': audience,
            'language': 'עברית',
            'era': guess_era(year_raw),
            'year': year_raw if year_raw else '',
            'description': desc,
            'similar_to': [],
            'in_library': True,
            'library_notes': notes,
            'shelf': shelf,
            'series': series,
            'publisher': publisher,
        }
        books.append(book)

    # Write JS output
    js = f'/**\n * קטלוג ספריית שחרות\n * נוצר אוטומטית מקובץ XLS הקטלוג\n * סה"כ: {len(books)} ספרים\n * עודכן: 14/04/2026\n */\n\nvar LOCAL_LIBRARY = '
    js += json.dumps(books, ensure_ascii=False, indent=2)
    js += ';\n'

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(js)

    with_desc = sum(1 for b in books if b['description'])
    with_genre = sum(1 for b in books if b['sub_genre'])
    print(f'\nOutput: {output_path}')
    print(f'Total unique books: {len(books)}')
    print(f'With description: {with_desc}')
    print(f'With sub-genre: {with_genre}')

    # Stats
    genre_counts = {}
    for b in books:
        sg = b.get('sub_genre', '')
        if sg:
            genre_counts[sg] = genre_counts.get(sg, 0) + 1
    print(f'\nSub-genre distribution:')
    for g, c in sorted(genre_counts.items(), key=lambda x: -x[1]):
        print(f'  {g}: {c}')

    audience_counts = {}
    for b in books:
        a = b.get('audience', [])
        a_str = a[0] if a else 'לא מסווג'
        audience_counts[a_str] = audience_counts.get(a_str, 0) + 1
    print(f'\nAudience distribution:')
    for a, c in sorted(audience_counts.items(), key=lambda x: -x[1]):
        print(f'  {a}: {c}')

    # Sample with descriptions
    descs = [b for b in books if b['description']]
    if descs:
        sample_path = output_path.replace('.js', '_samples.txt')
        with open(sample_path, 'w', encoding='utf-8') as f:
            f.write(f"Books with descriptions: {len(descs)}\n\n")
            for b in descs[:20]:
                f.write(f'"{b["title"]}" / {b["author"]}\n')
                f.write(f'  סוגה: {b["sub_genre"]} | ז\'אנרים: {", ".join(b["genres"])}\n')
                f.write(f'  תקציר: {b["description"][:200]}\n\n')
        print(f'\nSample descriptions written to {sample_path}')

    return books


def main():
    xls_path = r'C:\Users\hacmo\Downloads\קטלוג ספריית שחרות.xls'
    output_path = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\local_library.js'

    print(f'Parsing XLS catalog...\n')
    books = parse_xls(xls_path, output_path)


if __name__ == '__main__':
    main()
