/**
 * recommender.js — Semantic Embedding Recommender
 * ================================================
 * מנוע המלצות סמנטי המשתמש ב-embeddings שחושבו מראש.
 *
 * אלגוריתם:
 *   1. מפענח BOOK_EMBEDDINGS (base64 Float32Array) → מטריצה (n × 128) בזיכרון
 *   2. קורא את וקטורי ספרי הקלט ומחשב centroid מנורמל (L2)
 *   3. מדרג את כל הספרים לפי dot-product עם ה-centroid (= cosine similarity)
 *   4. לכל ספר בתוצאות — מוצא את ספר הקלט הקרוב ביותר (לצורך הסבר)
 *   5. מחזיר [{book, semanticScore, closestInputBook, closestSim}] ממויין
 *
 * שימוש:
 *   var results = SemanticRecommender.recommend(matchedBooks, bookById, opts);
 *   // opts: { excludeIds: Set, libraryOnly: bool, topN: number }
 *   // returns null אם embeddings לא זמינים (fallback ל-metadata)
 */

(function () {
  "use strict";

  // ── מצב פנימי ──────────────────────────────────────────────────────────────
  var _ready      = false;
  var _embeddings = null;   // Float32Array, גודל n*dim
  var _n          = 0;
  var _dim        = 0;
  var _ids        = [];
  var _idToIdx    = {};

  var CHILDREN_SUBGENRES = {
    "ספרות ילדים": true, "גן ילדים": true,
    "ראשית קריאה": true, "ספרות נוער (YA)": true
  };

  // ── אתחול ─────────────────────────────────────────────────────────────────
  function _init() {
    if (_ready) return true;
    if (typeof BOOK_EMBEDDINGS === "undefined") {
      console.warn("SemanticRecommender: BOOK_EMBEDDINGS not loaded");
      return false;
    }

    try {
      var be  = BOOK_EMBEDDINGS;
      _n      = be.n;
      _dim    = be.dim;
      _ids    = be.ids;

      // base64 → Float32Array
      var bin = atob(be.data);
      var buf = new ArrayBuffer(bin.length);
      var u8  = new Uint8Array(buf);
      for (var i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
      _embeddings = new Float32Array(buf);

      // אינדקס id → מיקום
      for (var j = 0; j < _ids.length; j++) _idToIdx[_ids[j]] = j;

      _ready = true;
      console.log(
        "SemanticRecommender ready: " + _n + " books \xD7 " + _dim + " dims"
      );
      return true;
    } catch (e) {
      console.error("SemanticRecommender init error:", e);
      return false;
    }
  }

  // ── עזרים ─────────────────────────────────────────────────────────────────
  function _getVec(id) {
    var idx = _idToIdx[id];
    if (idx === undefined) return null;
    return _embeddings.subarray(idx * _dim, (idx + 1) * _dim);
  }

  /** dot product של שני Float32Array/TypedArray */
  function _dot(a, b) {
    var s = 0;
    for (var i = 0; i < _dim; i++) s += a[i] * b[i];
    return s;
  }

  /** centroid מנורמל L2 מרשימת וקטורים */
  function _centroid(vecs) {
    var c = new Float32Array(_dim);
    for (var i = 0; i < vecs.length; i++) {
      var v = vecs[i];
      for (var j = 0; j < _dim; j++) c[j] += v[j];
    }
    var norm = 0;
    for (var j = 0; j < _dim; j++) norm += c[j] * c[j];
    norm = Math.sqrt(norm);
    if (norm > 0) for (var j = 0; j < _dim; j++) c[j] /= norm;
    return c;
  }

  function _isChildren(book) {
    var aud = book.audience;
    if (aud) {
      var audArr = Array.isArray(aud) ? aud : [aud];
      if (audArr.indexOf("ילדים") !== -1 || audArr.indexOf("נוער") !== -1) return true;
    }
    if (book.sub_genre && CHILDREN_SUBGENRES[book.sub_genre]) return true;
    var g = book.genres;
    if (Array.isArray(g) && g.indexOf("ילדים ונוער") !== -1) return true;
    return false;
  }

  // ── ממשק ציבורי ────────────────────────────────────────────────────────────

  /**
   * recommend(matchedBooks, bookById, options)
   *
   * @param {object[]} matchedBooks  - ספרי קלט (אובייקטים מהקטלוג)
   * @param {object}   bookById      - מפה id → book
   * @param {object}   [options]
   *   @param {Set}    [options.excludeIds]   - מזהים לדילוג (ספרי קלט)
   *   @param {boolean}[options.libraryOnly]  - רק ספרי ספריית שחרות
   *   @param {number} [options.topN=200]     - כמה תוצאות להחזיר
   *
   * @returns {object[]|null}
   *   null אם embeddings לא זמינים (fallback ל-metadata)
   *   אחרת: [{book, semanticScore, closestInputBook, closestSim}]
   *   ממויין לפי semanticScore יורד
   */
  function recommend(matchedBooks, bookById, options) {
    if (!_ready && !_init()) return null;

    options = options || {};
    var topN        = options.topN        || 200;
    var excludeIds  = options.excludeIds  || new Set();
    var libraryOnly = !!options.libraryOnly;

    // ── וקטורי קלט ──────────────────────────────────────────────────────────
    var inputItems = [];
    matchedBooks.forEach(function (b) {
      var v = _getVec(b.id);
      if (v) inputItems.push({ vec: v, book: b });
    });

    // אם אין embedding לאף ספר קלט — fallback
    if (inputItems.length === 0) return null;

    var centroid = _centroid(inputItems.map(function (x) { return x.vec; }));

    // ── דירוג כל הספרים ───────────────────────────────────────────────────
    var results = [];

    for (var i = 0; i < _n; i++) {
      var id = _ids[i];
      if (excludeIds.has(id)) continue;

      var book = bookById[id];
      if (!book)            continue;
      if (_isChildren(book)) continue;
      if (libraryOnly && !book.in_library) continue;

      var vec   = _embeddings.subarray(i * _dim, (i + 1) * _dim);
      var score = _dot(centroid, vec);

      results.push({ id: id, book: book, semanticScore: score, _i: i });
    }

    // מיון יורד
    results.sort(function (a, b) { return b.semanticScore - a.semanticScore; });
    var top = results.slice(0, topN);

    // ── ספר קלט קרוב ביותר לכל תוצאה (לצורך הסבר) ─────────────────────────
    top.forEach(function (r) {
      var bestSim = -Infinity;
      var bestBook = inputItems[0].book;
      var cVec = _embeddings.subarray(r._i * _dim, (r._i + 1) * _dim);

      inputItems.forEach(function (iv) {
        var sim = _dot(cVec, iv.vec);
        if (sim > bestSim) {
          bestSim  = sim;
          bestBook = iv.book;
        }
      });

      r.closestInputBook = bestBook;
      r.closestSim       = bestSim;
      delete r._i;
    });

    return top;
  }

  // ── חשיפה גלובלית ──────────────────────────────────────────────────────────
  window.SemanticRecommender = {
    recommend : recommend,
    init      : _init,
    isReady   : function () { return _ready; }
  };

})();
