#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
סקריפט v2 - חילוץ קטלוג ספריית שחרות מ-PDF כולל תקצירים
"""

import pdfplumber
import re
import json

def is_mostly_latin(text):
    if not text: return False
    latin = sum(1 for c in text if 'A' <= c <= 'Z' or 'a' <= c <= 'z')
    hebrew = sum(1 for c in text if '\u0590' <= c <= '\u05FF')
    return latin > hebrew and latin > 3

def reverse_hebrew_line(line):
    if not line or not line.strip(): return line
    if is_mostly_latin(line): return line
    reversed_line = line[::-1]
    def fix_numbers(match): return match.group(0)[::-1]
    reversed_line = re.sub(r'[\d][\d\-\./,]*[\d]', fix_numbers, reversed_line)
    swaps = {'(': ')', ')': '(', '[': ']', ']': '['}
    return ''.join(swaps.get(ch, ch) for ch in reversed_line)


def parse_catalog(pdf_path):
    """Extract all books from the catalog PDF, including summaries"""
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        all_lines = []
        for i in range(total):
            if i % 200 == 0:
                print(f"  reading page {i+1}/{total}...", flush=True)
            text = pdf.pages[i].extract_text()
            if text:
                all_lines.extend(text.split('\n'))

    print(f"  total lines: {len(all_lines)}")

    # --- Field detection patterns (visual Hebrew, labels at end of line) ---
    # Each returns (field_name, value_extractor)

    skip_line = re.compile(
        r'^\d{2}:\d{2}:\d{2}|לבח תוירפס|םירתוכ תמישר|םירתוכ תומכ|ןורגא תכרעמ'
    )

    entries = []
    current = {}
    in_summary = False
    summary_lines = []

    def flush_summary():
        nonlocal in_summary, summary_lines
        if in_summary and summary_lines:
            text = ' '.join(summary_lines).strip()
            if text:
                current['description'] = reverse_hebrew_line(text)[:500]
        in_summary = False
        summary_lines = []

    def save_entry():
        nonlocal current
        flush_summary()
        if current.get('title'):
            entries.append(current)
        current = {}

    for line in all_lines:
        line = line.strip()
        if not line: continue
        if skip_line.search(line): continue

        # === New entry: סוג חומר: ספרים ===
        if line.startswith('םירפס :רמוח גוס') or line == 'םירפס :רמוח גוס':
            save_entry()
            current = {}
            continue

        # === Summary field (multiline) ===
        if line.endswith('ריצקת') or ':ריצקת' in line:
            flush_summary()
            raw = line.replace('ריצקת', '').strip().strip(':').strip()
            in_summary = True
            summary_lines = [raw] if raw else []
            continue

        # === Check for known field labels (ends summary if active) ===
        field_detected = False

        # Title/responsibility
        if 'תוירחא .מ/רתוכ' in line:
            flush_summary()
            raw = line.split('תוירחא .מ/רתוכ')[0].strip().lstrip(':').strip()
            rev = reverse_hebrew_line(raw)
            if ' / ' in rev:
                title = rev.split(' / ')[0].strip()
            else:
                title = rev
            current['title'] = title.strip('"').strip()
            field_detected = True

        # Author (not compound "authors" line)
        elif (line.endswith('ת/רבחמ') or 'ת/רבחמ :' in line) and 'םירבחמ' not in line:
            flush_summary()
            raw = line.split(':')[0].strip() if ':' in line else line.replace('ת/רבחמ', '').strip()
            author = reverse_hebrew_line(raw)
            if ',' in author:
                parts = author.split(',', 1)
                author = parts[1].strip() + ' ' + parts[0].strip()
            current['author'] = author.strip()
            field_detected = True

        # Genre
        elif line.endswith('גוס') and 'רמוח גוס' not in line and len(line) < 80:
            flush_summary()
            raw = line.replace('גוס', '').strip().strip(':').strip()
            current['genre'] = reverse_hebrew_line(raw)
            field_detected = True

        # Language
        elif line.endswith('הפש') and len(line) < 40:
            flush_summary()
            raw = line.replace('הפש', '').strip().strip(':').strip()
            current['language'] = reverse_hebrew_line(raw)
            field_detected = True

        # Shelf
        elif 'ףדמ' in line and 'ןוימ' in line:
            flush_summary()
            raw = line.split(';')[0].strip() if ';' in line else line
            raw = raw.replace('ףדמ', '').replace('ןוימ', '').replace('.סמ', '').replace('.ס/', '').strip().strip(';').strip()
            current['shelf'] = reverse_hebrew_line(raw)
            field_detected = True

        # Notes
        elif line.endswith('תורעה') and len(line) < 200:
            flush_summary()
            raw = line.replace('תורעה', '').strip().strip(':').strip()
            current['notes'] = reverse_hebrew_line(raw)
            field_detected = True

        # Audience
        elif 'דעי להק' in line:
            flush_summary()
            raw = line.replace('דעי להק', '').strip().strip(':').strip()
            current['audience'] = reverse_hebrew_line(raw)
            field_detected = True

        # ISBN
        elif 'ב"תסמ' in line:
            flush_summary()
            raw = line.replace('ב"תסמ', '').strip().strip(':').strip()
            current['isbn'] = re.sub(r'[^\d\-X]', '', raw)
            field_detected = True

        # Publisher (extract year)
        elif 'רואל איצומ' in line:
            flush_summary()
            year_match = re.search(r'(\d{4})', line)
            if year_match:
                current['year'] = year_match.group(1)
            field_detected = True

        # Series
        elif line.endswith('הרדס') and len(line) < 100:
            flush_summary()
            raw = line.replace('הרדס', '').strip().strip(':').strip()
            current['series'] = reverse_hebrew_line(raw)
            field_detected = True

        # Catalog date / copies - just stop summary
        elif 'גולטיק ךיראת' in line or 'םיקתוע תומכ' in line:
            flush_summary()
            field_detected = True

        elif re.match(r'^\d+\s*:םיקתוע$', line):
            flush_summary()
            field_detected = True

        # Format/print
        elif line.endswith('תסופד') and len(line) < 30:
            flush_summary()
            field_detected = True

        # Illustrations
        elif 'םירויא' in line and len(line) < 60:
            flush_summary()
            field_detected = True

        # === Continuation of summary ===
        if not field_detected and in_summary:
            summary_lines.append(line)

    # Final entry
    save_entry()
    return entries


def guess_era(year_str):
    try:
        year = int(year_str)
        if year < 1950: return 'קלאסי'
        elif year < 2000: return 'מודרני'
        else: return 'בן-זמננו'
    except: return ''


GENRE_FIXES = {
    'ה: רומן היסטורי': 'רומן היסטורי', 'ה: פנטזיה': 'פנטזיה',
    'ה: מתח': 'מותחן', 'ה: אהבה ורומנטיקה': 'רומנטי',
    'ה: קומיקס': 'קומיקס', 'ה: סיפורים': 'סיפורים קצרים',
    'ה: בלש': 'בלשי', 'ה: אימה': 'אימה', 'ה: הרפתקה': 'הרפתקאות',
    'ה: ביוגרפיה': 'ביוגרפיה', 'ה: מדע בדיוני': 'מדע בדיוני',
    'ה: הומור': 'הומור', 'סיפורת': 'ספרות יפה',
}


def entries_to_library_js(entries, output_path):
    books = []
    seen = set()

    for e in entries:
        title = e.get('title', '').strip()
        if not title or len(title) < 2: continue
        title = re.sub(r'^\[.*?\]\s*', '', title).strip('"').strip("'").strip()
        title = title.replace('\\"', '"')

        key = re.sub(r'\s+', ' ', title.lower().strip())
        if key in seen: continue
        seen.add(key)

        author = e.get('author', '').strip().strip(':')
        genre = e.get('genre', '').strip()
        if genre in GENRE_FIXES: genre = GENRE_FIXES[genre]
        elif genre.startswith('ה: '): genre = genre[3:]
        genres = [genre] if genre else []

        # Extract sub-genre from notes
        notes = e.get('notes', '')
        sub_genre = ''
        note_genres = {
            'רומן מתח': 'מותחן', 'רומן היסטורי': 'רומן היסטורי',
            'פנטסיה': 'פנטזיה', 'פנטזיה': 'פנטזיה',
            'קומיקס': 'קומיקס', 'שירה': 'שירה',
            'סיפור-דיאלוג': 'דרמה', 'ספורים': 'סיפורים קצרים',
        }
        for pattern, mapped in note_genres.items():
            if pattern in notes:
                sub_genre = mapped
                if mapped not in genres:
                    genres.append(mapped)
                break

        audience = []
        aud = e.get('audience', '')
        if aud: audience = [aud]
        elif 'ילדים' in genre or 'נוער' in genre: audience = ['צעירים']

        # Description
        desc = e.get('description', '').strip()
        # Clean up reversed artifacts
        if desc:
            desc = re.sub(r'\s+', ' ', desc).strip()

        shelf = e.get('shelf', '').strip(':').strip()

        book = {
            'id': f'lib{len(books)+1:04d}',
            'title': title,
            'author': author,
            'genres': genres,
            'themes': [],
            'mood': [],
            'style': [],
            'audience': audience,
            'language': e.get('language', 'עברית') or 'עברית',
            'era': guess_era(e.get('year', '')),
            'description': desc,
            'similar_to': [],
            'in_library': True,
            'library_notes': notes,
            'shelf': shelf,
        }
        books.append(book)

    js = f'/**\n * קטלוג ספריית שחרות\n * נוצר אוטומטית מקובץ PDF הקטלוג\n * סה"כ: {len(books)} ספרים\n * עודכן: 12/04/2026\n */\n\nvar LOCAL_LIBRARY = '
    js += json.dumps(books, ensure_ascii=False, indent=2)
    js += ';\n'

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(js)

    with_desc = sum(1 for b in books if b['description'])
    print(f'\nOutput: {output_path}')
    print(f'Total unique books: {len(books)}')
    print(f'With description: {with_desc}')

    return books


def main():
    pdf_path = r'C:\Users\hacmo\Downloads\קטלוג 12.04.26.pdf'
    output_path = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\local_library.js'

    print(f'Parsing catalog...\n')
    entries = parse_catalog(pdf_path)
    print(f'\nRaw entries: {len(entries)}')

    books = entries_to_library_js(entries, output_path)

    # Sample descriptions
    descs = [b for b in books if b['description']]
    if descs:
        with open(output_path.replace('.js', '_samples.txt'), 'w', encoding='utf-8') as f:
            f.write(f"Books with descriptions: {len(descs)}\n\n")
            for b in descs[:20]:
                f.write(f'"{b["title"]}" / {b["author"]}\n  {b["description"][:200]}\n\n')
        print(f'\nSample descriptions written to _samples.txt')


if __name__ == '__main__':
    main()
