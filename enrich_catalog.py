#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enrich_catalog.py — מוסיף mood, style, themes, sub_genre לכל ספר
שיטה: Zero-shot classification עם paraphrase-multilingual-MiniLM-L12-v2

שימוש:
    py -3 enrich_catalog.py                          # העשרת ספרים חסרים בלבד
    py -3 enrich_catalog.py --force                  # מחדש הכל (טקסונומיה חדשה)
    py -3 enrich_catalog.py --input data/local_library_described.js
"""

import json, re, sys, io, time, argparse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np

DEFAULT_JS_PATH  = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\local_library_described.js'
CKPT_PATH        = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\enrich_checkpoint.jsonl'
MODEL_NAME       = 'paraphrase-multilingual-MiniLM-L12-v2'
THEME_THRESHOLD  = 0.32   # מוגבה מ-0.28 כדי להפחית רעש
SUB_THRESHOLD    = 0.30
SAVE_EVERY       = 100
BATCH_SIZE       = 64


# ── טקסונומיה מורחבת ─────────────────────────────────────────────────────────

MOOD_LABELS = {
    'כבד ומעמיק':            'ספרות רצינית ומאתגרת. שאלות קיומיות, פסיכולוגיות ומוסריות עמוקות. לא קל לקריאה אך מעמיק ומעשיר.',
    'קליל ומהנה':            'קריאה נגישה ומהנה. זורמת ללא מאמץ, בידורית, מרוממת רוח ומשמחת.',
    'מתח וסאספנס':           'מותחן שלא מרפה. מתח מתמיד, תחושת סכנה מתמשכת, חשיפה הדרגתית של אמת.',
    'רומנטי':                'האהבה היא לב הסיפור. כימיה בין דמויות, רגשות עזים ויחסים רומנטיים.',
    'עצוב ומרגש':            'ספר שנוגע ללב. עוסק באובדן, כאב, אבל ופרידה — עצוב אך יפה ומרגש.',
    'הומוריסטי':             'מצחיק בפירוש. הומור, אבסורד, אירוניה וקומדיה גורמים לצחוק אמיתי.',
    'דיסטופי':               'עולם עתידני שקרס. חברה טוטליטרית ומדכאת, ממשל רודני, אנושות ללא חירות.',
    'נוסטלגי ומרגיע':        'אווירה נוסטלגית חמה ומרגיעה. מזכיר ילדות, זמנים פשוטים ואנושיים.',
    'מפחיד ומאיים':          'פחד, אימה ואי-נוחות. הוררור, מתח פסיכולוגי, אפלה ואיום.',
    'מרגש ומעורר השראה':     'מעורר השראה ונותן כוח. סיפור עמידה במכשולים, ניצחון האדם.',
    'פילוסופי-רעיוני':       'עמוק רעיונית. מציב שאלות על קיום, מוסר, אמת, מוות ומשמעות החיים.',
    'אינטנסיבי ומציף':       'רגשי ועצים. כבד רגשית, ויסצרלי, לא עוזב רגע, מציף וסוחף.',
    'אפי ועשיר':             'יריעה רחבה ועולם עשיר. מסע גדול, דמויות רבות, עלילה בסקלה היסטורית.',
    'מסתורי ואטמוספרי':      'אווירה מסתורית וסוחפת. חידות בלתי פתורות, אפלה, מקום עוטף.',
    'אבסורדי וייחודי':       'הומור אבסורדי, מציאות מעוותת, לוגיקה שבורה, מוזר ובלתי צפוי.',
    'מחמם לב':               'חם ומיטיב. יחסים אנושיים, אמפתיה, קהילה ותחושת שייכות.',
    'אקשן ועוצמה':           'קצב מהיר ועוצמתי. הרפתקאות, לחימה, סכנות פיזיות, פעולה ורצון.',
    'פנימי ואינטרוספקטיבי':  'זרם תודעה, מחשבות פנימיות, עולם פנימי עשיר, רפלקציה ופסיכולוגיה.',
}

STYLE_LABELS = {
    'עלילתי-מהיר':          'כתיבה עלילתית עם פעולה מהירה, הרבה אירועים וקצב גבוה',
    'פנימי-אינטרוספקטיבי':  'כתיבה פנימית עם זרם תודעה, מחשבות ועולם פנימי עשיר',
    'פואטי-ספרותי':          'כתיבה ספרותית ופואטית עם שפה מטופחת ופרוזה איכותית',
    'הומוריסטי-סאטירי':      'כתיבה קומית וסאטירית עם טון הומוריסטי וביקורת חברתית',
    'מתוח-קצבי':             'כתיבה מתוחה עם בניית מתח הדרגתי ותחושת סכנה מתקרבת',
    'מורכב-רב-שכבתי':       'כתיבה מורכבת עם עלילות מקבילות ונרטיב שאינו לינארי',
    'תיאורי-אפי':            'כתיבה תיאורית ואפית עם בניית עולם נרחבת ותיאורים מפורטים',
}

THEME_LABELS = {
    'אהבה ורומנטיקה':       'אהבה רומנטית, זוגיות, חיזור, קשר סנטימנטלי בין שני אנשים',
    'משפחה ויחסים':         'דינמיקה משפחתית, הורים וילדים, אחים, יחסים בין-דוריים',
    'חברות ונאמנות':        'חברות עמוקה, נאמנות, קבוצת חברים קרובים, ידידות',
    'זהות ושורשים':         'חיפוש זהות אישית ותרבותית, שורשים משפחתיים, מי אני באמת',
    'מלחמה וקרב':          'קרבות, חיילים, מלחמה בשדה הקרב, טראומת לוחמים ופצועים',
    'שואה וזיכרון':         'שואת יהודי אירופה, מחנות ריכוז, ניצולים, זיכרון קולקטיבי',
    'התבגרות וגדילה':       'גיל ההתבגרות, מעבר לבגרות, ניסיון ראשוני, גדילה אישית',
    'אובדן ואבל':           'אבל על מת, שכול, אובדן אהובים, תהליך ריפוי מאובדן',
    'השרדות ומצבי קיצון':  'מאבק על החיים, מצוקה קיצונית, הישרדות בטבע, מסע הישרדות',
    'בגידה ואמון':          'בגידה אישית, שבירת אמון, שקר מכוון, ניסיון לשיקום יחסים',
    'כוח ושחיתות':         'שחיתות פוליטית, שימוש לרעה בכוח, עריצות, מניפולציה',
    'גאולה ותיקון עצמי':   'שינוי אישי, גאולה, תיקון טעויות עבר, צמיחה רוחנית',
    'הרפתקה וגילוי':        'מסע לעולמות חדשים, גילויים, הרפתקה פיזית, חקר מקומות',
    'חקירה ופשע':          'פשע שצריך לפתור, בלש פרטי, חקירת משטרה, גופה, חשד ואשמה',
    'אמונה ורוחניות':       'אמונה דתית, ספק, יחס לאלוהים, מיסטיקה ורוחניות',
    'טבע וסביבה':          'קשר עמוק לטבע, בעלי חיים, נוף, אקולוגיה, חיים בשטח',
    'פוליטיקה וחברה':       'פוליטיקה, מחאה, מהפכה, מדיניות, ביקורת חברתית',
    'עוני ומעמד':          'פערים חברתיים, עוני, מאבק מעמדי, ניידות חברתית',
    'יצירה ואמנות':         'אמנות, מוזיקה, כתיבה, יצירה, אמן ומאבקו ליצור',
    'גלות והגירה':          'עזיבת מולדת, הגירה לארץ חדשה, גלות, שייכות ושורשים',
    'נשיות ופמיניזם':       'חוויה נשית, שוויון מגדרי, פמיניזם, דיכוי ושחרור האישה',
    'ילדות ותמימות':        'ילדות, תמימות, מבט ילדותי על העולם, זכרונות ילדות',
    'פשע ועולם תחתון':     'עולם הפשע, מאפיה, גנבים, כנופיות, חיי עבריינות',
    'עתיד וטכנולוגיה':     'מדע בדיוני, טכנולוגיה, בינה מלאכותית, עתיד האנושות',
    'פסיכולוגיה וטראומה':  'בריאות נפשית, פסיכולוגיה, טראומה, הפרעות נפשיות',
    'ספורט ותחרות':        'ספורט, תחרות, ניצחון וכישלון, אימון, גבולות הגוף',
    'מוות ותמותה':         'מוות, מחלה סופנית, ימים אחרונים, מה אחרי המוות',
    'סודות ושקרים':        'סוד שמוסתר, חשיפת אמת מוסתרת, שקרים שמתפרקים',
    'יהדות וישראל':        'הוויה יהודית, ישראל, קהילה יהודית, זהות יהודית',
    'מיתולוגיה ואגדות':    'מיתוסים, אגדות עמים, גיבורים אגדתיים, קסם ואגדה',
    'ריגול ומסתורין':      'ריגול, סוכן מסתורי, שירות ביון, מסר סודי, מרדף',
    'זוגיות ומשבר':        'משבר זוגי, גירושין, בגידה רומנטית, מאבק להציל יחסים',
    'חינוך ובית ספר':      'בית ספר, אוניברסיטה, מורה ותלמיד, גדילה דרך חינוך',
    'ביקורת חברתית':       'ביקורת אירונית על החברה, סאטירה חברתית, חשיפת צביעות',
    'נוסעים ותרבויות':     'טיולים, נסיעות, פגישה עם תרבויות שונות, חוויית עולם',
}

# תת-ז'אנרים לספרות יפה ללא תת-ז'אנר
SUB_GENRE_LABELS = {
    'ספרות ישראלית עכשווית': 'רומן ישראלי עכשווי, חיי יומיום בישראל, דמויות ישראליות, קונפליקטים ישראלים',
    'ספרות קלאסית':           'רומן קלאסי מהמאה ה-19, ויקטוריאני, ספרות אירופית ישנה',
    'ריאליזם קסום':           'ריאליזם קסום: אלמנטים מאגיים בתוך מציאות יומיומית. גרסיה מרקס, בורחס',
    'מותחן':                  'מותחן, פשע, חקירת רצח, מסתורין, בלש. קצב מהיר וסאספנס',
    'מותחן פסיכולוגי':        'מותחן פסיכולוגי: גיבור לא יציב, עולם פנימי מסוכן, גבולות תודעה',
    'רומן היסטורי':           'רומן המתרחש בעבר ההיסטורי. ממלכות, מלחמות ותקופות היסטוריות',
    'פנטזיה':                 'פנטזיה אפית: קסם, עולמות דמיוניים, קרבות, ממלכות ומסעות',
    'מדע בדיוני':             'מדע בדיוני: חלל, רובוטים, טכנולוגיה עתידנית, עתיד האנושות',
    'דיסטופיה':               'דיסטופיה: עולם עתידני מדכא, שלטון טוטליטרי, חברה קפואה',
    'הוררור':                 'הוררור: פחד, אימה, ישויות מפחידות, אפלה ואיום על החיים',
    'סאגה משפחתית':           'סאגה משפחתית: סיפור של משפחה לאורך דורות ועשורים',
    'ספרות עברית קלאסית':    'ספרות עברית קלאסית: עגנון, ביאליק, ברנר, הסופרים הגדולים',
    'ספרות לטינו-אמריקאית':   'ספרות דרום אמריקה וספרד: מקסיקו, ארגנטינה, קולומביה',
    'ספרות יפנית':            'ספרות יפנית: יפן, תרבות יפנית, מוראקמי, אוגאווה',
    'ספרות סקנדינבית':        'ספרות סקנדינבית: שבדית, נורבגית, דנית, נורדי',
    'ביוגרפיה וממואר':        'ביוגרפיה, אוטוביוגרפיה, ממואר: סיפור חיים אמיתי',
    'רומנס':                  'רומנטיקה: סיפור אהבה בעיקרו, זוגיות, Happy end',
    'ספרות נוסעים':           'ספרות נסיעות: טיולים, גילויים, חוויית מקומות שונים',
    'ספרות נוער (YA)':        'Young Adult: ספרות לנוער, גיל ההתבגרות, ראשית בגרות',
    'ספרות ספרדית':           'ספרות ספרדית ופורטוגזית: ספרד, איברי, פורטוגל, ברזיל',
}


# ── I/O ───────────────────────────────────────────────────────────────────────

def load_library(js_path):
    with open(js_path, encoding='utf-8-sig') as f:
        content = f.read()
    m = re.search(r'var LOCAL_LIBRARY\s*=\s*(\[.*\])\s*;', content, re.DOTALL)
    if not m:
        raise ValueError('לא נמצא LOCAL_LIBRARY')
    books  = json.loads(m.group(1))
    prefix = content[:m.start(1)]
    suffix = content[m.end(1):]
    return books, prefix, suffix

def save_library(books, prefix, suffix, js_path):
    with open(js_path, 'w', encoding='utf-8') as f:
        f.write(prefix)
        f.write(json.dumps(books, ensure_ascii=False, indent=2))
        f.write(suffix)

def load_checkpoint():
    done = {}
    try:
        with open(CKPT_PATH, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    e = json.loads(line)
                    done[e['id']] = e
    except FileNotFoundError:
        pass
    return done

def append_checkpoint(entry):
    with open(CKPT_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


# ── בניית טקסט ───────────────────────────────────────────────────────────────

def build_text(book):
    parts = []
    if book.get('title'):
        parts.append(book['title'])
    if book.get('author'):
        parts.append(book['author'])
    if book.get('description'):
        parts.append(book['description'][:600])
    else:
        for g in (book.get('genres') or [])[:3]:
            parts.append(g)
    return ' '.join(p for p in parts if p).strip()

def needs_sub_genre(book):
    """האם הספר מועמד לתת-ז'אנר חדש."""
    if book.get('sub_genre'):
        return False
    genres = book.get('genres') or []
    return 'ספרות יפה' in genres or not genres


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--force',  action='store_true', help='חשב מחדש גם ספרים שכבר עובדו')
    parser.add_argument('--input',  default=DEFAULT_JS_PATH, help='נתיב לקובץ JS')
    parser.add_argument('--test',   action='store_true', help='רק 50 ספרים ראשונים')
    args = parser.parse_args()

    t0 = time.time()
    print(f'=== enrich_catalog.py  {"--force" if args.force else ""}  {time.strftime("%H:%M:%S")} ===')
    print(f'קובץ: {args.input}')

    books, prefix, suffix = load_library(args.input)
    n_total = len(books)
    print(f'{n_total} ספרים נטענו')

    if args.force:
        done = {}
        print('--force: מתעלם מ-checkpoint קיים')
    else:
        done = load_checkpoint()
        print(f'checkpoint: {len(done)} כבר עובדו')

    by_id = {b['id']: b for b in books}

    # הזרקת checkpoint קיים (רק במצב רגיל)
    if not args.force:
        for bid, entry in done.items():
            if bid in by_id:
                b = by_id[bid]
                if entry.get('mood')      and not b.get('mood'):      b['mood']      = entry['mood']
                if entry.get('style')     and not b.get('style'):     b['style']     = entry['style']
                if entry.get('themes')    and not b.get('themes'):    b['themes']    = entry['themes']
                if entry.get('sub_genre') and not b.get('sub_genre'): b['sub_genre'] = entry['sub_genre']

    # ספרים לעיבוד
    if args.force:
        to_process = [b for b in books if b.get('description')]
    else:
        to_process = [
            b for b in books
            if b['id'] not in done and (
                not b.get('mood') or not b.get('style') or
                not b.get('themes') or needs_sub_genre(b)
            )
        ]

    if args.test:
        to_process = to_process[:50]

    print(f'לעיבוד: {len(to_process)} ספרים\n')

    if not to_process:
        print('✓ הכל מעובד.')
        _print_stats(books, n_total)
        return

    print(f'טוען מודל {MODEL_NAME}...')
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL_NAME)
    print('  ✓\n')

    print('מקודד תוויות...')
    mood_keys  = list(MOOD_LABELS.keys())
    mood_embs  = model.encode(list(MOOD_LABELS.values()), normalize_embeddings=True, show_progress_bar=False)

    style_keys = list(STYLE_LABELS.keys())
    style_embs = model.encode(list(STYLE_LABELS.values()), normalize_embeddings=True, show_progress_bar=False)

    theme_keys = list(THEME_LABELS.keys())
    theme_embs = model.encode(list(THEME_LABELS.values()), normalize_embeddings=True, show_progress_bar=False)

    sub_keys   = list(SUB_GENRE_LABELS.keys())
    sub_embs   = model.encode(list(SUB_GENRE_LABELS.values()), normalize_embeddings=True, show_progress_bar=False)
    print('  ✓\n')

    n = len(to_process)
    print(f'מעשיר {n} ספרים (batch={BATCH_SIZE})...')

    for batch_start in range(0, n, BATCH_SIZE):
        batch = to_process[batch_start : batch_start + BATCH_SIZE]
        texts = [build_text(b) for b in batch]

        book_embs = model.encode(
            texts, normalize_embeddings=True,
            batch_size=BATCH_SIZE, show_progress_bar=False
        )

        for book, emb in zip(batch, book_embs):
            mood   = mood_keys[int(np.argmax(mood_embs  @ emb))]
            style  = style_keys[int(np.argmax(style_embs @ emb))]
            scores = theme_embs @ emb
            themes = [theme_keys[j] for j, s in enumerate(scores) if s > THEME_THRESHOLD]
            if not themes:
                themes = [theme_keys[int(np.argmax(scores))]]  # לפחות תמה אחת

            # תת-ז'אנר — רק לספרים מתאימים
            sub = None
            if needs_sub_genre(book):
                sub_scores = sub_embs @ emb
                best_sub_score = float(np.max(sub_scores))
                if best_sub_score >= SUB_THRESHOLD:
                    sub = sub_keys[int(np.argmax(sub_scores))]

            # עדכון (--force דורס הכל, רגיל — רק ריקים)
            if args.force or not book.get('mood'):      book['mood']   = mood
            if args.force or not book.get('style'):     book['style']  = style
            if args.force or not book.get('themes'):    book['themes'] = themes
            if sub and (args.force or not book.get('sub_genre')):
                book['sub_genre'] = sub

            ckpt = {'id': book['id'], 'mood': mood, 'style': style, 'themes': themes}
            if sub:
                ckpt['sub_genre'] = sub
            append_checkpoint(ckpt)

        idx = batch_start + len(batch)
        elapsed = time.time() - t0
        eta = (elapsed / idx) * (n - idx) if idx > 0 else 0
        print(f'  [{idx:04d}/{n}]  {elapsed:.0f}ש  ETA: {eta:.0f}ש', end='\r', flush=True)

        if idx % SAVE_EVERY == 0 or idx == n:
            save_library(books, prefix, suffix, args.input)

    print(f'\n  ✓ הושלם ({time.time()-t0:.0f}ש)\n')
    save_library(books, prefix, suffix, args.input)
    _print_stats(books, n_total)
    _print_validation(books)


def _print_stats(books, total):
    has_mood     = sum(1 for b in books if b.get('mood'))
    has_style    = sum(1 for b in books if b.get('style'))
    has_themes   = sum(1 for b in books if b.get('themes'))
    has_sub      = sum(1 for b in books if b.get('sub_genre'))
    print('כיסוי סופי:')
    print(f'  mood:      {has_mood}/{total}  ({100*has_mood//total}%)')
    print(f'  style:     {has_style}/{total}  ({100*has_style//total}%)')
    print(f'  themes:    {has_themes}/{total}  ({100*has_themes//total}%)')
    print(f'  sub_genre: {has_sub}/{total}  ({100*has_sub//total}%)')

    from collections import Counter
    mood_dist = Counter(b.get('mood','') for b in books if b.get('mood'))
    print('\nפילוג mood:')
    for k, v in mood_dist.most_common():
        print(f'  {v:4d}  {k}')

    sub_dist = Counter(b.get('sub_genre','') for b in books if b.get('sub_genre'))
    print('\nפילוג sub_genre:')
    for k, v in sub_dist.most_common():
        print(f'  {v:4d}  {k}')


def _print_validation(books):
    import random; random.seed(42)
    pool = [b for b in books if b.get('mood') and b.get('description')]
    sample = random.sample(pool, min(15, len(pool)))
    print('\nולידציה — 15 ספרים אקראיים:')
    print(f'  {"כותרת":<30} {"mood":<22} {"sub_genre":<22} themes')
    print('  ' + '-' * 100)
    for b in sample:
        t = ', '.join((b.get('themes') or [])[:2])
        sub = b.get('sub_genre', '')[:20]
        print(f'  {b["title"][:30]:<30} {b.get("mood",""):<22} {sub:<22} {t}')


if __name__ == '__main__':
    main()
