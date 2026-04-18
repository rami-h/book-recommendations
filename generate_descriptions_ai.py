#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_descriptions_ai.py
============================
מייצר תקצירים בעברית לספרים ללא תקציר באמצעות Claude Haiku.

שימוש:
    set ANTHROPIC_API_KEY=sk-ant-...
    py -3 generate_descriptions_ai.py            # הכל
    py -3 generate_descriptions_ai.py --test     # 40 ספרים ראשונים
    py -3 generate_descriptions_ai.py --resume   # המשך מ-checkpoint

פלט:
  - data/local_library.js מעודכן עם description_source="ai_generated"
  - data/ai_desc_checkpoint.jsonl — checkpoint (עמיד לקריסות)
"""

import json, re, sys, io, time, os, argparse, anthropic

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

JS_PATH   = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\local_library.js'
CKPT_PATH = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\ai_desc_checkpoint.jsonl'
LOG_PATH  = r'C:\Users\hacmo\Desktop\MyWebsite\library\data\ai_desc_log.txt'

MODEL      = 'claude-haiku-4-5'
BATCH_SIZE = 20     # ספרים לכל קריאת API
MAX_TOKENS = 3000
SAVE_EVERY = 100    # שמור local_library.js כל N ספרים
RETRY_WAIT = 8      # שניות המתנה על rate-limit


# ── I/O ──────────────────────────────────────────────────────────────────────

def load_library():
    with open(JS_PATH, 'r', encoding='utf-8-sig') as f:
        content = f.read()
    m = re.search(r'var LOCAL_LIBRARY\s*=\s*(\[.*\])\s*;', content, re.DOTALL)
    if not m:
        raise ValueError('לא נמצא LOCAL_LIBRARY')
    books  = json.loads(m.group(1))
    prefix = content[:m.start(1)]
    suffix = content[m.end(1):]
    return books, prefix, suffix

def save_library(books, prefix, suffix):
    with open(JS_PATH, 'w', encoding='utf-8') as f:
        f.write(prefix)
        f.write(json.dumps(books, ensure_ascii=False, indent=2))
        f.write(suffix)

def load_checkpoint():
    done = {}
    if not os.path.exists(CKPT_PATH):
        return done
    with open(CKPT_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    e = json.loads(line)
                    done[e['id']] = e['description']
                except Exception:
                    pass
    return done

def append_checkpoint(bid, desc):
    with open(CKPT_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'id': bid, 'description': desc}, ensure_ascii=False) + '\n')

def log(msg):
    print(msg, flush=True)
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(msg + '\n')


# ── בניית prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """אתה עוזר קטלוג ספרים בעברית.
תפקידך לכתוב תקצירים קצרים ומדויקים בעברית לספרים.

כללים:
1. אם אתה מכיר את הספר — כתוב תקציר של 2-3 משפטים על העלילה/תוכן האמיתי שלו.
2. אם אינך מכיר את הספר — כתוב תקציר של 2 משפטים המבוסס על הנתונים (ז'אנר, נושאים, מצב-רוח) שסופקו.
   בסגנון: "ספר [סוגה] של [מחבר], העוסק ב[נושאים]. [משפט נוסף על האווירה/הסגנון]."
3. כתוב תמיד בעברית. לא לכתוב "לא ידוע" — תמיד ספק משהו.
4. אל תכתוב שהתקציר מבוסס על מטאדטה — כתוב כאילו אתה יודע על הספר.
5. אורך: 50-200 מילים.

השב בפורמט JSON בלבד:
[{"id": "lib0001", "description": "..."}, ...]"""

def book_to_prompt_entry(book):
    entry = {
        'id':     book['id'],
        'title':  book['title'],
        'author': book.get('author', ''),
    }
    if book.get('sub_genre'):
        entry['sub_genre'] = book['sub_genre']
    if book.get('genres'):
        entry['genres'] = book['genres'][:3]
    if book.get('mood'):
        entry['mood'] = book['mood']
    if book.get('themes'):
        entry['themes'] = book['themes'][:4]
    if book.get('style'):
        entry['style'] = book['style']
    if book.get('series'):
        entry['series'] = book['series']
    return entry


# ── קריאת API ────────────────────────────────────────────────────────────────

def call_api(client, batch):
    entries = [book_to_prompt_entry(b) for b in batch]
    user_msg = (
        f'כתוב תקצירים בעברית ל-{len(batch)} הספרים הבאים:\n\n'
        + json.dumps(entries, ensure_ascii=False, indent=2)
    )

    for attempt in range(4):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{'role': 'user', 'content': user_msg}]
            )
            text = response.content[0].text.strip()

            # חילוץ JSON
            json_match = re.search(r'\[.*\]', text, re.DOTALL)
            if not json_match:
                raise ValueError(f'לא נמצא JSON בתשובה: {text[:200]}')
            results = json.loads(json_match.group(0))

            # וידוא שיש id ו-description
            parsed = {}
            for item in results:
                if item.get('id') and item.get('description'):
                    desc = item['description'].strip()
                    if len(desc) > 20:
                        parsed[item['id']] = desc
            return parsed

        except anthropic.RateLimitError:
            wait = RETRY_WAIT * (attempt + 1)
            log(f'  Rate limit — ממתין {wait}ש...')
            time.sleep(wait)
        except anthropic.APIError as e:
            log(f'  API שגיאה (ניסיון {attempt+1}): {str(e)[:80]}')
            if attempt < 3:
                time.sleep(RETRY_WAIT)
        except Exception as e:
            log(f'  שגיאה לא צפויה (ניסיון {attempt+1}): {str(e)[:120]}')
            if attempt < 3:
                time.sleep(3)

    return {}  # כשל — ממשיך לbatch הבא


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test',   action='store_true', help='רק 40 ספרים')
    parser.add_argument('--resume', action='store_true', help='המשך מ-checkpoint')
    args = parser.parse_args()

    # מפתח API
    api_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
    if not api_key:
        api_key = input('Anthropic API key (sk-ant-...): ').strip()
    if not api_key:
        print('נדרש API key')
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    t0 = time.time()
    log(f'\n=== generate_descriptions_ai.py ===')
    log(f'מודל: {MODEL}  |  batch: {BATCH_SIZE}  |  {time.strftime("%H:%M:%S")}')

    log('טוען ספרייה...')
    books, prefix, suffix = load_library()
    by_id = {b['id']: b for b in books}
    log(f'  {len(books)} ספרים')

    log('טוען checkpoint...')
    done = load_checkpoint()
    log(f'  {len(done)} כבר עובדו')

    # הזרק checkpoint לתוך books
    for bid, desc in done.items():
        if bid in by_id and not by_id[bid].get('description'):
            by_id[bid]['description'] = desc
            by_id[bid]['description_source'] = 'ai_generated'

    # ספרים שנותרו
    no_desc = [b for b in books if not by_id[b['id']].get('description')]
    log(f'ללא תקציר: {len(no_desc)}')

    to_process = [b for b in no_desc if b['id'] not in done]
    if args.test:
        to_process = to_process[:40]
    log(f'לעיבוד: {len(to_process)} ספרים\n')

    if not to_process:
        log('✓ הכל מעובד.')
        return

    total_success = 0
    total_batches = (len(to_process) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_num, batch_start in enumerate(range(0, len(to_process), BATCH_SIZE)):
        batch = to_process[batch_start : batch_start + BATCH_SIZE]
        idx   = batch_start + len(batch)

        elapsed = time.time() - t0
        eta = (elapsed / idx) * (len(to_process) - idx) if idx > 0 else 0
        log(f'[{batch_num+1}/{total_batches}] ספרים {batch_start+1}–{idx}  |  '
            f'{elapsed:.0f}ש  ETA: {eta:.0f}ש')

        results = call_api(client, batch)

        for book in batch:
            desc = results.get(book['id'], '')
            if desc:
                by_id[book['id']]['description'] = desc
                by_id[book['id']]['description_source'] = 'ai_generated'
                append_checkpoint(book['id'], desc)
                total_success += 1
            else:
                # לא קיבלנו תקציר — רשום ריק כ-fallback כדי לא לנסות שוב
                append_checkpoint(book['id'], '')
                log(f'  ! לא התקבל תקציר עבור: {book["title"][:40]}')

        log(f'  הצלחות batch: {len(results)}/{len(batch)}  |  סה"כ: {total_success}/{idx}')

        # שמור כל SAVE_EVERY ספרים
        if idx % SAVE_EVERY == 0 or idx == len(to_process):
            save_library(list(by_id.values()), prefix, suffix)
            log(f'  [שמירה]')

        # השהייה קצרה בין batches (Haiku מהיר — rate limit ידידותי)
        time.sleep(0.5)

    # שמירה סופית
    save_library(list(by_id.values()), prefix, suffix)

    # סיכום
    final_with_desc = sum(1 for b in by_id.values() if b.get('description'))
    log(f'\n=== סיכום ===')
    log(f'תקצירים חדשים:  {total_success}')
    log(f'סה"כ עם תקציר: {final_with_desc}/{len(books)} ({100*final_with_desc//len(books)}%)')
    log(f'זמן כולל: {time.time()-t0:.0f}ש')
    log('✓ בוצע')


if __name__ == '__main__':
    main()
