#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compute_embeddings.py — וקטורים סמנטיים לכל ספר בקטלוג

שלבים:
  1. בנה טקסט לכל ספר: כותרת + תת-ז'אנר + mood + themes + תקציר
  2. קודד עם paraphrase-multilingual-MiniLM-L12-v2 → 384 מימדים
  3. PCA 384 → 128 (שומר ~95% מהשונות, גודל קובץ קטן יותר)
  4. נרמול L2 (cosine similarity = dot product)
  5. שמור כ-Float32Array מקודד base64 → data/embeddings.js (~3MB)

הפלט נטען בדפדפן ל-recommender.js לחישוב centroid בזמן-אמת.
"""

import json, re, sys, io, base64, time, argparse, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np
from sklearn.decomposition import PCA
from sentence_transformers import SentenceTransformer

BASE_DIR = r'C:\Users\hacmo\Desktop\MyWebsite\library'
DEFAULT_IN  = r'data\local_library.js'
DEFAULT_OUT = r'data\embeddings.js'
MODEL    = 'paraphrase-multilingual-MiniLM-L12-v2'
DIM      = 128
BATCH    = 64


# ── I/O ───────────────────────────────────────────────────────────────────────

def load_library(path):
    with open(path, encoding='utf-8-sig') as f:
        content = f.read()
    m = re.search(r'var LOCAL_LIBRARY\s*=\s*(\[.*\])\s*;', content, re.DOTALL)
    return json.loads(m.group(1))


# ── בניית טקסט ────────────────────────────────────────────────────────────────

def build_text(book):
    """
    בונה טקסט סמנטי לכל ספר משדות אמינים בלבד.
    שדות שהוסרו: themes — נוצרו ב-zero-shot ומייצרים false positives.
    """
    parts = []

    # כותרת ומחבר — עוגן זהות חזק (מקשר ספרים של אותו מחבר)
    if book.get('title'):
        parts.append(book['title'])
    if book.get('author'):
        parts.append(book['author'])

    # ז'אנרים — אמינים, לא נוצרו ב-zero-shot
    genres = book.get('genres') or []
    if isinstance(genres, list) and genres:
        parts.extend(genres[:3])

    # תת-ז'אנר + מצב-רוח + סגנון — ערכים בודדים, אמינים יחסית
    if book.get('sub_genre'):
        parts.append(book['sub_genre'])
    if book.get('mood'):
        parts.append(book['mood'])
    if book.get('style'):
        parts.append(book['style'])

    # סדרה — מקשר ספרים מאותה סדרה
    if book.get('series'):
        parts.append(book['series'])

    # תקציר — הסיגנל העיקרי (500 תווים ראשונים)
    if book.get('description'):
        parts.append(book['description'][:500])

    return ' '.join(p for p in parts if p).strip()


# ── ולידציה ───────────────────────────────────────────────────────────────────

def validate(ids, vectors, books_by_id, pairs):
    """בדוק שזוגות ספרים מוכרים מקבלים similarity גבוה."""
    id_to_idx = {bid: i for i, bid in enumerate(ids)}
    print('\nולידציה — similarity בין ספרים דומים:')
    for title_a, title_b in pairs:
        ba = next((b for b in books_by_id.values() if title_a in b.get('title', '')), None)
        bb = next((b for b in books_by_id.values() if title_b in b.get('title', '')), None)
        if not ba or not bb:
            print(f'  לא נמצא: {title_a} | {title_b}')
            continue
        ia = id_to_idx.get(ba['id'])
        ib = id_to_idx.get(bb['id'])
        if ia is None or ib is None:
            continue
        sim = float(np.dot(vectors[ia], vectors[ib]))
        print(f'  {sim:.3f}  {ba["title"][:30]} ↔ {bb["title"][:30]}')


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',  default=DEFAULT_IN,  help='קובץ JS של הספרייה (יחסי לתיקיית הפרויקט)')
    parser.add_argument('--output', default=DEFAULT_OUT, help='קובץ פלט embeddings (יחסי לתיקיית הפרויקט)')
    args = parser.parse_args()

    js_path  = os.path.join(BASE_DIR, args.input)  if not os.path.isabs(args.input)  else args.input
    out_path = os.path.join(BASE_DIR, args.output) if not os.path.isabs(args.output) else args.output

    t0 = time.time()

    print(f'קובץ קלט:  {js_path}')
    print(f'קובץ פלט:  {out_path}')
    print('טוען ספרייה...')
    books = load_library(js_path)
    n = len(books)
    ids = [b['id'] for b in books]
    books_by_id = {b['id']: b for b in books}
    print(f'  {n} ספרים')

    # בנה טקסטים
    print('בונה טקסטים...')
    texts = [build_text(b) for b in books]
    with_desc = sum(1 for b in books if b.get('description'))
    print(f'  {with_desc}/{n} ספרים עם תקציר ({100*with_desc//n}%)')

    # קודד
    print(f'\nטוען מודל {MODEL}...')
    model = SentenceTransformer(MODEL)
    print('  ✓ מוכן')

    print(f'מקודד {n} ספרים (batch={BATCH})...')
    raw_embs = model.encode(
        texts,
        batch_size=BATCH,
        normalize_embeddings=False,
        show_progress_bar=True
    )
    # raw_embs: (n, 384) float32
    print(f'  ✓ ({time.time()-t0:.0f}ש)')

    # PCA 384 → DIM
    print(f'\nPCA {raw_embs.shape[1]} → {DIM} מימדים...')
    pca = PCA(n_components=DIM, random_state=42)
    reduced = pca.fit_transform(raw_embs).astype(np.float32)
    explained = pca.explained_variance_ratio_.sum()
    print(f'  שונות מוסברת: {explained:.1%}')

    # L2 normalize → cosine similarity = dot product
    norms = np.linalg.norm(reduced, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    vectors = (reduced / norms).astype(np.float32)

    # ולידציה
    validate(ids, vectors, books_by_id, [
        ('מאה שנים של בדידות', 'בית הרוחות'),       # ריאליזם קסום לטינו-אמריקאי
        ('האחים קרמאזוב', 'החטא ועונשו'),            # דוסטוייבסקי
        ('מדריך הטרמפיסט', 'סוכנות הבילוש'),        # דאגלס אדאמס (ז'אנרים שונים — מבחן קשה)
        ('האמן ומרגריטה', 'האחים קרמאזוב'),          # ספרות רוסית קלאסית
    ])

    # שמור כ-base64
    print('\nמקודד ושומר...')
    flat  = vectors.flatten()   # (n * DIM,) float32
    b64   = base64.b64encode(flat.tobytes()).decode('ascii')

    js = (
        '// Auto-generated by compute_embeddings.py — אל תערוך ידנית\n'
        f'// {n} ספרים × {DIM} מימדים, L2-normalized Float32Array\n'
        f'// PCA variance explained: {explained:.1%}\n'
        'var BOOK_EMBEDDINGS = {\n'
        f'  "n":    {n},\n'
        f'  "dim":  {DIM},\n'
        f'  "ids":  {json.dumps(ids, ensure_ascii=False)},\n'
        f'  "data": "{b64}"\n'
        '};\n'
    )

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(js)

    size_mb = len(b64) * 3 / 4 / (1024 * 1024)
    print(f'  נשמר: {out_path}')
    print(f'  גודל: {size_mb:.1f}MB  ({n} ספרים × {DIM} dims)')
    print(f'  זמן כולל: {time.time()-t0:.0f}ש')
    print('  ✓ בוצע')


if __name__ == '__main__':
    main()
