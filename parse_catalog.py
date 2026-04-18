#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
סקריפט לחילוץ קטלוג ספריית שחרות מקובץ PDF
ויצירת קובץ local_library.js לאפליקציית ממליץ הספרים
"""

import pdfplumber
import re
import json
import sys

def is_mostly_latin(text):
    """Check if text is mostly Latin characters"""
    if not text:
        return False
    latin = sum(1 for c in text if 'A' <= c <= 'Z' or 'a' <= c <= 'z')
    hebrew = sum(1 for c in text if '\u0590' <= c <= '\u05FF')
    return latin > hebrew and latin > 3

def reverse_hebrew_line(line):
    """Reverse visual-order Hebrew line to logical order"""
    if not line or not line.strip():
        return line
    # Don't reverse primarily Latin text
    if is_mostly_latin(line):
        return line
    reversed_line = line[::-1]
    # Fix number sequences
    def fix_numbers(match):
        return match.group(0)[::-1]
    reversed_line = re.sub(r'[\d][\d\-\./,]*[\d]', fix_numbers, reversed_line)
    # Fix brackets/parens
    swaps = {'(': ')', ')': '(', '[': ']', ']': '['}
    return ''.join(swaps.get(ch, ch) for ch in reversed_line)

def parse_catalog(pdf_path, max_pages=None):
    """Extract all books from the catalog PDF"""

    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages) if max_pages is None else min(max_pages, len(pdf.pages))
        all_lines = []

        for i in range(total):
            if i % 200 == 0:
                print(f"  reading page {i+1}/{total}...", flush=True)
            text = pdf.pages[i].extract_text()
            if text:
                all_lines.extend(text.split('\n'))

    print(f"  total lines: {len(all_lines)}")

    # Parse entries
    entries = []
    current = {}
    current_field = None
    current_multiline = []

    skip_patterns = [
        re.compile(r'^\d{2}:\d{2}:\d{2}\s+\d{2}/\d{2}/\d{4}'),
        re.compile(r'לבח תוירפס'),
        re.compile(r'םירתוכ תמישר'),
        re.compile(r'םירתוכ תומכ'),
        re.compile(r'ןורגא תכרעמ'),
    ]

    for line in all_lines:
        line = line.strip()
        if not line:
            continue
        if any(p.search(line) for p in skip_patterns):
            continue

        rev = reverse_hebrew_line(line)

        # New entry marker
        if 'סוג חומר:' in rev or line.endswith('רמוח גוס') or line.startswith('םירפס :רמוח גוס'):
            # Save multiline field
            if current_field == 'summary' and current_multiline:
                current['description'] = ' '.join(current_multiline)
            # Save entry
            if current.get('title'):
                entries.append(current)
            current = {}
            current_field = None
            current_multiline = []
            continue

        # Field matching (labels appear at end of visual Hebrew line)
        field_matched = False

        # Title/responsibility
        if 'תוירחא .מ/רתוכ' in line or 'כותר/מ. אחריות:' in rev:
            title_part = rev.split('כותר/מ. אחריות:')[-1].strip() if 'כותר/מ. אחריות:' in rev else reverse_hebrew_line(line.split('תוירחא .מ/רתוכ')[0].strip().lstrip(':').strip())
            # Extract title (before the / author part)
            if ' / ' in title_part:
                title = title_part.split(' / ')[0].strip()
            else:
                title = title_part
            current['title'] = title.strip('"').strip()
            current_field = None
            field_matched = True

        # Author (but not the "authors" compound field)
        elif (line.endswith('ת/רבחמ') or 'ת/רבחמ :' in line) and 'םירבחמ' not in line:
            author_raw = line.split(':')[0].strip() if ':' in line else line.replace('ת/רבחמ', '').strip()
            author = reverse_hebrew_line(author_raw)
            # Fix "last, first" -> "first last"
            if ',' in author:
                parts = author.split(',', 1)
                author = parts[1].strip() + ' ' + parts[0].strip()
            current['author'] = author.strip()
            current_field = None
            field_matched = True

        # Genre/type
        elif line.endswith('גוס') and 'רמוח גוס' not in line and len(line) < 80:
            genre_raw = line.replace('גוס', '').strip().strip(':').strip()
            current['genre'] = reverse_hebrew_line(genre_raw)
            current_field = None
            field_matched = True

        # Language
        elif line.endswith('הפש') or 'שפה:' in rev:
            lang_raw = line.replace('הפש', '').strip().strip(':').strip()
            current['language'] = reverse_hebrew_line(lang_raw)
            current_field = None
            field_matched = True

        # Shelf
        elif 'ףדמ' in line and 'ןוימ' in line:
            shelf_raw = line.split(';')[0].strip() if ';' in line else line
            shelf_raw = shelf_raw.replace('ףדמ', '').replace('ןוימ', '').replace('.סמ', '').replace('.ס/', '').strip().strip(';').strip()
            current['shelf'] = reverse_hebrew_line(shelf_raw)
            current_field = None
            field_matched = True

        # Notes
        elif line.endswith('תורעה') and len(line) < 200:
            notes_raw = line.replace('תורעה', '').strip().strip(':').strip()
            current['notes'] = reverse_hebrew_line(notes_raw)
            current_field = None
            field_matched = True

        # Audience
        elif 'דעי להק' in line:
            aud_raw = line.replace('דעי להק', '').strip().strip(':').strip()
            current['audience'] = reverse_hebrew_line(aud_raw)
            current_field = None
            field_matched = True

        # ISBN
        elif 'ב"תסמ' in line:
            isbn_raw = line.replace('ב"תסמ', '').strip().strip(':').strip()
            current['isbn'] = re.sub(r'[^\d\-X]', '', isbn_raw)
            current_field = None
            field_matched = True

        # Summary (can be multiline)
        elif line.endswith('ריצקת') or 'תקציר:' in rev:
            summary_raw = line.replace('ריצקת', '').strip().strip(':').strip()
            current_multiline = [reverse_hebrew_line(summary_raw)] if summary_raw else []
            current_field = 'summary'
            field_matched = True

        # Publisher (extract year)
        elif 'רואל איצומ' in line or 'מוציא לאור:' in rev:
            pub = rev if 'מוציא לאור:' in rev else reverse_hebrew_line(line)
            year_match = re.search(r'(\d{4})', pub)
            if year_match:
                current['year'] = year_match.group(1)
            current_field = None
            field_matched = True

        # Series
        elif line.endswith('הרדס') and len(line) < 100:
            series_raw = line.replace('הרדס', '').strip().strip(':').strip()
            current['series'] = reverse_hebrew_line(series_raw)
            current_field = None
            field_matched = True

        # Catalog date, copies - just skip
        elif 'גולטיק ךיראת' in line or 'םיקתוע תומכ' in line or (re.match(r'^\d+$', line.split(':')[0].strip() if ':' in line else '')):
            current_field = None
            field_matched = True

        # Multi-line continuation (for summary)
        if not field_matched and current_field == 'summary':
            current_multiline.append(reverse_hebrew_line(line))

    # Save last entry
    if current_field == 'summary' and current_multiline:
        current['description'] = ' '.join(current_multiline)
    if current.get('title'):
        entries.append(current)

    return entries


def guess_era(year_str):
    try:
        year = int(year_str)
        if year < 1950: return 'קלאסי'
        elif year < 2000: return 'מודרני'
        else: return 'בן-זמננו'
    except:
        return ''


def entries_to_library_js(entries, output_path):
    """Convert parsed entries to local_library.js"""
    books = []
    seen_titles = set()

    for i, e in enumerate(entries):
        title = e.get('title', '').strip()
        if not title or len(title) < 2:
            continue

        # Deduplicate by title
        title_key = re.sub(r'\s+', ' ', title.lower().strip())
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)

        author = e.get('author', '').strip()
        genre = e.get('genre', '')
        genres = [genre] if genre else []

        # Guess audience from genre
        audience = []
        aud = e.get('audience', '')
        if aud:
            audience = [aud]
        elif 'ילדים' in genre or 'נוער' in genre:
            audience = ['צעירים']

        book = {
            'id': f'lib{len(books)+1:04d}',
            'title': title,
            'author': author,
            'genres': genres,
            'themes': [],
            'mood': [],
            'style': [],
            'audience': audience,
            'language': e.get('language', ''),
            'era': guess_era(e.get('year', '')),
            'description': e.get('description', '')[:300],
            'similar_to': [],
            'in_library': True,
            'library_notes': e.get('notes', ''),
            'shelf': e.get('shelf', ''),
        }
        books.append(book)

    # Write JS
    js = f'/**\n * קטלוג ספריית שחרות\n * נוצר אוטומטית מקובץ PDF\n * סה"כ: {len(books)} ספרים\n */\n\nvar LOCAL_LIBRARY = '
    js += json.dumps(books, ensure_ascii=False, indent=2)
    js += ';\n'

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(js)

    print(f'\nOutput: {output_path}')
    print(f'Total unique books: {len(books)}')

    # Sample
    print('\n--- Sample (first 10) ---')
    for b in books[:10]:
        g = f' [{", ".join(b["genres"])}]' if b["genres"] else ''
        print(f'  "{b["title"]}" / {b["author"]}{g}')

    return books


def main():
    pdf_path = r'C:\Users\hacmo\Downloads\קטלוג 12.04.26.pdf'
    output_path = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\local_library.js'

    print(f'Parsing: {pdf_path}')
    print('This will take several minutes for ~2000 pages...\n')

    entries = parse_catalog(pdf_path)
    print(f'\nRaw entries found: {len(entries)}')

    books = entries_to_library_js(entries, output_path)


if __name__ == '__main__':
    main()
