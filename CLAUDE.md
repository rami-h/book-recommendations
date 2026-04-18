# Claude Instructions — ספריית שחרות Book Recommender

## Project Overview

This project uses Python. The main application is a Hebrew book catalog with a web UI. Always handle Hebrew/RTL text properly in scraping, parsing, and display.

- **Stack**: Python (data pipeline) + vanilla JS/HTML/CSS (browser UI)
- **Catalog**: ~5,083 Hebrew books in `data/local_library.js`
- **Pipeline**: parse → classify genres → enrich (mood/style/themes) → embeddings → recommend
- **Encoding**: always open files with `encoding='utf-8'` or `encoding='utf-8-sig'`; use `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')` at the top of every script

---

## Versioning

- When changing recommender/scoring logic, bump version and update ALL locations (search for the constant/function across the repo, not just the obvious file).

---

## Web Scraping

- Always validate scraped data against source (e.g., title/author match) before bulk-writing to catalog.
- Run scrapers in resumable batches with checkpointing so a mid-run crash doesn't lose progress.
- Prefer Hebrew-native sources (Simania, e-vrit) over Google Books for Hebrew book metadata.

When scraping external sites, always implement:

1. **Checkpoint/resume capability** — save progress every N items (default: every 25–100) to a `.jsonl` file. On restart, load the checkpoint and skip already-processed items.
2. **Error handling that doesn't crash the full run** — wrap each item's fetch in try/except; log failures and continue. Never let a single network error abort the entire batch.
3. **A dry-run mode** — test on 5 items before running on the full dataset. Print results for manual review and require explicit confirmation before proceeding.

### Data Validation

Before scraping or API-matching books by title:

- Validate results against known metadata (author, ISBN, language) to avoid mismatches.
- Use fuzzy title matching with a similarity threshold (≥ 0.5 word overlap recommended).
- Always show a sample of 5 matches for user review before bulk processing — print the original title, the matched title, and a snippet of the description side by side.
- Flag and skip matches where author family name doesn't appear in the result's author field.

---

## Data Pipeline Scripts

| Script | Purpose |
|---|---|
| `enrich_catalog.py` | Zero-shot mood/style/themes via sentence-transformers |
| `compute_embeddings.py` | PCA-reduced semantic embeddings → `data/embeddings.js` |
| `scrape_descriptions.py` | Fetch descriptions: Google Books API → Simania Playwright |
| `generate_descriptions_ai.py` | AI-generated descriptions for remaining books (Claude Haiku) |
| `recommend.py` | Pre-compute IDF-weighted `similar[]` lists for each book |

After any script that modifies `data/local_library.js`, re-run `compute_embeddings.py` to keep embeddings in sync.

---

## Recommendation Algorithm

- **Semantic**: centroid of input book embeddings → cosine similarity (dot product, L2-normalized)
- **Metadata**: IDF-weighted genre + themes + mood + style overlap
- **Blend**: 55% semantic + 45% metadata
- **Dedup**: strict 1 book per author
- **Children's books**: excluded via `audience='ילדים'` OR `sub_genre` in `{ספרות ילדים, גן ילדים, ראשית קריאה}`
