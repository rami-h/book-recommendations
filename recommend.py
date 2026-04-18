#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
recommend.py — מחשב המלצות לכל ספר ב-local_library.js

אלגוריתם:
  score(a, b) = metadata_score + tfidf_cosine × 2.0

  metadata_score:
    same_series    +5.0
    same_author    +3.0
    same_sub_genre +3.0
    genres Jaccard ×2.5
    themes Jaccard ×2.0
    same_mood      +1.5
    same_style     +1.0
    same_audience  +1.0

  בחירת 8 המלצות: ממוין יורד, ספר אחד למחבר (קשיח), ספרי ילדים מוחרגים.

פלט: שדה "similar": [id×8] מתווסף לכל ספר ב-local_library.js
"""

import json, re, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import numpy as np
from collections import defaultdict
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import MultiLabelBinarizer

JS_PATH    = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\local_library.js'
N_SIMILAR  = 8
TFIDF_W    = 2.0   # weight of TF-IDF cosine in combined score

# ספר נחשב "ילדים" אם אחד מהתנאים מתקיים
CHILDREN_AUDIENCE  = 'ילדים'
CHILDREN_SUBGENRES = {'ספרות ילדים', 'גן ילדים', 'ראשית קריאה'}


# ── I/O ──────────────────────────────────────────────────────────────────────

def load_library():
    with open(JS_PATH, encoding='utf-8-sig') as f:
        content = f.read()
    m = re.search(r'var LOCAL_LIBRARY\s*=\s*(\[.*\])\s*;', content, re.DOTALL)
    if not m:
        raise ValueError('לא נמצא LOCAL_LIBRARY ב-JS')
    books  = json.loads(m.group(1))
    prefix = content[:m.start(1)]
    suffix = content[m.end(1):]
    return books, prefix, suffix

def save_library(books, prefix, suffix):
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(prefix)
        f.write(json.dumps(books, ensure_ascii=False, indent=2))
        f.write(suffix)
    print(f'  נשמר: {JS_PATH}')


# ── Helpers ───────────────────────────────────────────────────────────────────

def to_list(v):
    if isinstance(v, list): return [x.strip() for x in v if x and str(x).strip()]
    if isinstance(v, str) and v.strip(): return [v.strip()]
    return []

def str_val(b, field):
    v = b.get(field) or ''
    if isinstance(v, list): v = v[0] if v else ''
    return str(v).strip()


# ── Score matrices ─────────────────────────────────────────────────────────────

def categorical_matrix(books, field, weight):
    """n×n matrix: +weight where books[i][field] == books[j][field] (non-empty)."""
    n = len(books)
    values = [str_val(b, field) for b in books]
    groups = defaultdict(list)
    for idx, v in enumerate(values):
        if v:
            groups[v].append(idx)
    mat = np.zeros((n, n), dtype=np.float32)
    for indices in groups.values():
        if len(indices) < 2:
            continue
        arr = np.array(indices, dtype=np.int32)
        mat[np.ix_(arr, arr)] += weight
    return mat

def idf_tag_matrix(books, field, weight):
    """
    IDF-weighted cosine similarity on a list field.
    תגית נדירה ("מותחן") → IDF גבוה → משמעות רבה.
    תגית שכיחה ("ספרות יפה", 53%) → IDF נמוך → כמעט אינה תורמת.
    """
    all_lists = [to_list(b.get(field)) for b in books]
    mlb = MultiLabelBinarizer(sparse_output=False)
    bin_mat = mlb.fit_transform(all_lists).astype(np.float32)
    if bin_mat.shape[1] == 0:
        return np.zeros((len(books), len(books)), dtype=np.float32)
    n        = len(books)
    doc_freq = bin_mat.sum(axis=0)                          # (n_tags,)
    idf      = np.log(n / (1.0 + doc_freq)).astype(np.float32)
    weighted = bin_mat * idf[None, :]                       # (n, n_tags)
    norms    = np.linalg.norm(weighted, axis=1, keepdims=True)
    norms    = np.where(norms == 0, 1.0, norms)
    normed   = weighted / norms
    sim      = normed @ normed.T                            # (n, n) cosine
    return (sim * weight).astype(np.float32)

def build_meta_matrix(books):
    t = time.time()
    print('  סדרה / מחבר / תת-ז\'אנר / מצב-רוח / סגנון / קהל...', flush=True)
    mat  = categorical_matrix(books, 'series',    5.0)
    mat += categorical_matrix(books, 'author',    3.0)
    mat += categorical_matrix(books, 'sub_genre', 3.0)
    mat += categorical_matrix(books, 'mood',      1.5)
    mat += categorical_matrix(books, 'style',     1.0)
    mat += categorical_matrix(books, 'audience',  1.0)
    print('  ז\'אנרים (IDF-weighted)...', flush=True)
    mat += idf_tag_matrix(books, 'genres',  2.5)
    print('  נושאים (IDF-weighted)...', flush=True)
    mat += idf_tag_matrix(books, 'themes',  2.0)
    np.fill_diagonal(mat, 0)
    print(f'  בוצע ({time.time()-t:.1f}ש)')
    return mat

def build_tfidf_matrix(books):
    t = time.time()
    descs = [b.get('description') or '' for b in books]
    n_desc = sum(1 for d in descs if len(d) > 50)
    print(f'  {n_desc}/{len(books)} ספרים עם תקציר', flush=True)
    vect = TfidfVectorizer(
        min_df=2, max_df=0.95,
        sublinear_tf=True,
        analyzer='char_wb',
        ngram_range=(2, 4),
    )
    sparse = vect.fit_transform(descs)          # (n, vocab)
    sim    = cosine_similarity(sparse)          # (n, n) dense float64
    sim    = sim.astype(np.float32)
    np.fill_diagonal(sim, 0)
    print(f'  בוצע ({time.time()-t:.1f}ש)')
    return sim


# ── Selection ─────────────────────────────────────────────────────────────────

def select_top(i, scores_row, books, is_children, n=N_SIMILAR):
    """
    Given scores for book[i] vs all others, return list of up to n book IDs:
      - self excluded
      - children's books excluded
      - max 1 per author (strict)
    """
    row = scores_row.copy()
    row[i] = -1.0
    row[is_children] = -1.0

    # argsort descending
    order = np.argsort(row)[::-1]

    result      = []
    seen_authors = set()

    for j in order:
        if row[j] < 0:
            break           # all remaining are self/children (score = -1)
        b      = books[j]
        author = str_val(b, 'author')
        if author and author in seen_authors:
            continue
        result.append(b['id'])
        if author:
            seen_authors.add(author)
        if len(result) >= n:
            break

    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    t0 = time.time()
    print('טוען ספרייה...')
    books, prefix, suffix = load_library()
    n = len(books)
    print(f'  {n} ספרים')

    is_children = np.array([
        str_val(b, 'audience') == CHILDREN_AUDIENCE or
        str_val(b, 'sub_genre') in CHILDREN_SUBGENRES
        for b in books
    ])
    n_kids = int(is_children.sum())
    print(f'  {n_kids} ספרי ילדים (audience=ילדים או sub_genre ילדים) → מוחרגים מהמלצות')
    print(f'  {n - n_kids} ספרים מועמדים להמלצה\n')

    print('שלב 1 — ציוני metadata:')
    meta = build_meta_matrix(books)

    print('\nשלב 2 — TF-IDF על תקצירים:')
    tfidf = build_tfidf_matrix(books)

    print('\nמשלב ציונים...')
    combined = meta + tfidf * TFIDF_W   # float32

    print(f'בוחר {N_SIMILAR} המלצות לכל ספר (ספר אחד למחבר)...')
    t1 = time.time()
    for i, book in enumerate(books):
        if i % 250 == 0:
            print(f'  [{i:04d}/{n}]', end='\r', flush=True)
        book['similar'] = select_top(i, combined[i], books, is_children)

    print(f'  [{n}/{n}] בוצע ({time.time()-t1:.1f}ש)')

    print('\nשומר...')
    save_library(books, prefix, suffix)

    # ── Stats ──
    with_similar = sum(1 for b in books if b.get('similar'))
    avg_n        = sum(len(b.get('similar') or []) for b in books) / n
    under_8      = sum(1 for b in books if 0 < len(b.get('similar') or []) < N_SIMILAR)
    print(f'\nסיכום:')
    print(f'  {with_similar}/{n} ספרים קיבלו המלצות')
    print(f'  ממוצע {avg_n:.1f} המלצות לספר')
    if under_8:
        print(f'  {under_8} ספרים קיבלו פחות מ-{N_SIMILAR} (מחבר ייחודי מדי)')
    print(f'  זמן כולל: {time.time()-t0:.0f} שניות')
    print('  ✓ בוצע')


if __name__ == '__main__':
    main()
