/**
 * ============================================
 * ממליץ הספרים של ספריית שחרות
 * מנוע המלצות וממשק משתמש
 * ============================================
 */

(function () {
  "use strict";

  // ===== קונפיגורציה =====
  var MAX_BOOKS = 5;
  var MAX_RESULTS = 10;
  var AUTOCOMPLETE_MIN_CHARS = 2;
  var AUTOCOMPLETE_MAX_RESULTS = 8;
  var FUZZY_THRESHOLD = 0.55;

  // ===== משקולות ניקוד =====
  var WEIGHTS = {
    genres: 3.0,
    // themes: הוסר — מיון אפס-ירייה ב-MiniLM מייצר רעש (40-55% false positives)
    mood: 1.5,
    style: 1.5,
    origin: 1.5,       // ארץ מוצא ספרותית — שדה אמין (זוהה לפי שם מחבר)
    audience: 1.0,
    language: 0.5,
    era: 0.5,
    similar_to: 4.0,
    same_author: 5.0
  };

  // ===== סינון ספרי ילדים =====
  var KIDS_SUB_GENRES_MAP = {
    "ספרות ילדים": true, "גן ילדים": true,
    "ראשית קריאה": true, "ספרות נוער (YA)": true
  };
  function isKidsBook(book) {
    var aud = book.audience;
    if (aud) {
      var arr = Array.isArray(aud) ? aud : [aud];
      if (arr.indexOf("ילדים") !== -1 || arr.indexOf("נוער") !== -1) return true;
    }
    if (book.sub_genre && KIDS_SUB_GENRES_MAP[book.sub_genre]) return true;
    var g = book.genres;
    if (Array.isArray(g) && g.indexOf("ילדים ונוער") !== -1) return true;
    return false;
  }

  // ===== מצב האפליקציה =====
  var state = {
    inputCount: 1,
    activeFilters: [],
    allBooks: [],
    adultBooks: [],
    libraryBooks: [],
    libraryTitles: new Set(),
    // אינדקסים לחיפוש מהיר
    titleIndex: {},     // normalized title -> book
    authorIndex: {},    // normalized author -> [books]
    bookById: {},       // id -> book
  };

  // ===== אתחול נתונים =====
  function initData() {
    state.libraryBooks = (typeof LOCAL_LIBRARY !== "undefined" && LOCAL_LIBRARY) || [];
    var generalCatalog = (typeof GENERAL_CATALOG !== "undefined" && GENERAL_CATALOG) || [];

    // סימון ספרי ספרייה
    state.libraryBooks.forEach(function (book) {
      book.in_library = true;
      state.libraryTitles.add(normalizeTitle(book.title));
    });

    // איחוד: ספריית שחרות + קטלוג כללי (ללא כפילויות)
    var seen = {};
    state.libraryBooks.forEach(function (book) {
      seen[normalizeTitle(book.title)] = true;
      state.allBooks.push(book);
    });
    generalCatalog.forEach(function (book) {
      var key = normalizeTitle(book.title);
      if (!seen[key]) {
        seen[key] = true;
        // בדוק אם מסומן כ-in_library
        if (book.in_library) {
          state.libraryTitles.add(key);
        }
        state.allBooks.push(book);
      }
    });

    // בניית אינדקסים לביצועים
    state.allBooks.forEach(function (book) {
      var titleKey = normalizeTitle(book.title);
      state.titleIndex[titleKey] = book;

      var authorKey = normalizeAuthor(book.author);
      if (authorKey) {
        if (!state.authorIndex[authorKey]) {
          state.authorIndex[authorKey] = [];
        }
        state.authorIndex[authorKey].push(book);
      }
    });

    // אינדקס לפי ID לתמיכה בהמלצות
    state.allBooks.forEach(function (book) {
      if (book.id) state.bookById[book.id] = book;
    });

    state.adultBooks = state.allBooks.filter(function(b) { return !isKidsBook(b); });

    console.log("Catalog loaded: " + state.allBooks.length + " books (" + state.adultBooks.length + " adults), " + state.libraryBooks.length + " in library");
  }

  // ===== נרמול טקסט =====
  function normalizeTitle(text) {
    if (!text) return "";
    return text
      .replace(/["""''`׳״\u05F3\u05F4]/g, "")
      .replace(/[-–—:,.!?()[\]]/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .toLowerCase();
  }

  function normalizeAuthor(text) {
    if (!text) return "";
    return text
      .replace(/["""''`׳״]/g, "")
      .replace(/[-–—,.!?()[\]]/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .toLowerCase();
  }

  // ===== התאמה מעורפלת =====

  function levenshtein(a, b) {
    if (a.length === 0) return b.length;
    if (b.length === 0) return a.length;
    // אופטימיזציה: אם ההפרש באורך גדול מדי, לא שווה לחשב
    if (Math.abs(a.length - b.length) > Math.max(a.length, b.length) * 0.5) {
      return Math.max(a.length, b.length);
    }

    var matrix = [];
    for (var i = 0; i <= b.length; i++) matrix[i] = [i];
    for (var j = 0; j <= a.length; j++) matrix[0][j] = j;

    for (i = 1; i <= b.length; i++) {
      for (j = 1; j <= a.length; j++) {
        var cost = b.charAt(i - 1) === a.charAt(j - 1) ? 0 : 1;
        matrix[i][j] = Math.min(
          matrix[i - 1][j] + 1,
          matrix[i][j - 1] + 1,
          matrix[i - 1][j - 1] + cost
        );
      }
    }
    return matrix[b.length][a.length];
  }

  function similarity(a, b) {
    if (!a || !b) return 0;
    a = normalizeTitle(a);
    b = normalizeTitle(b);

    if (a === b) return 1;

    // הכלה
    if (a.includes(b) || b.includes(a)) {
      var shorter = a.length < b.length ? a : b;
      var longer = a.length < b.length ? b : a;
      return 0.7 + (0.3 * shorter.length / longer.length);
    }

    // מילים משותפות
    var wordsA = a.split(" ").filter(function(w) { return w.length > 1; });
    var wordsB = b.split(" ").filter(function(w) { return w.length > 1; });
    var commonWords = 0;
    wordsA.forEach(function (wA) {
      wordsB.forEach(function (wB) {
        if (wA === wB || (wA.length > 2 && wB.length > 2 && (wA.includes(wB) || wB.includes(wA)))) {
          commonWords++;
        }
      });
    });
    var wordScore = commonWords / Math.max(wordsA.length, wordsB.length, 1);

    // Levenshtein (רק אם האורכים סבירים)
    if (a.length > 50 || b.length > 50) {
      return wordScore;
    }
    var maxLen = Math.max(a.length, b.length);
    var dist = levenshtein(a, b);
    var levScore = 1 - dist / maxLen;

    return Math.max(wordScore * 0.7 + levScore * 0.3, levScore);
  }

  function findBook(userInput) {
    if (!userInput || userInput.trim().length < 2) return null;

    var normalizedInput = normalizeTitle(userInput);

    // ניסיון 1: התאמה מדויקת
    if (state.titleIndex[normalizedInput]) {
      return { book: state.titleIndex[normalizedInput], score: 1 };
    }

    // ניסיון 2: התאמה חלקית מהירה (כולל הכלה)
    var bestMatch = null;
    var bestScore = 0;

    var keys = Object.keys(state.titleIndex);
    for (var k = 0; k < keys.length; k++) {
      var titleKey = keys[k];
      var score = 0;

      if (titleKey.includes(normalizedInput) || normalizedInput.includes(titleKey)) {
        var sh = normalizedInput.length < titleKey.length ? normalizedInput : titleKey;
        var lo = normalizedInput.length < titleKey.length ? titleKey : normalizedInput;
        score = 0.7 + (0.3 * sh.length / lo.length);
      }

      if (score > bestScore) {
        bestScore = score;
        bestMatch = state.titleIndex[titleKey];
      }
    }

    if (bestScore >= 0.8) {
      return { book: bestMatch, score: bestScore };
    }

    // ניסיון 3: fuzzy (רק על חלק מהספרים לביצועים)
    state.allBooks.forEach(function (book) {
      var titleScore = similarity(normalizedInput, book.title);
      var combined = book.title + " " + book.author;
      var combinedScore = similarity(normalizedInput, combined);
      var score = Math.max(titleScore, combinedScore);

      if (score > bestScore) {
        bestScore = score;
        bestMatch = book;
      }
    });

    if (bestScore >= FUZZY_THRESHOLD) {
      return { book: bestMatch, score: bestScore };
    }
    return null;
  }

  // ===== אוטוקומפליט =====
  function getAutocompleteSuggestions(input) {
    if (!input || input.trim().length < AUTOCOMPLETE_MIN_CHARS) return [];

    var normalizedInput = normalizeTitle(input);
    var results = [];

    // חיפוש מהיר: startsWith ו-includes
    state.allBooks.forEach(function (book) {
      var titleNorm = normalizeTitle(book.title);
      var authorNorm = normalizeAuthor(book.author);
      var score = 0;

      if (titleNorm.startsWith(normalizedInput)) {
        score = 1;
      } else if (titleNorm.includes(normalizedInput)) {
        score = 0.8;
      } else if (authorNorm.includes(normalizedInput)) {
        score = 0.6;
      } else {
        // fuzzy רק עם מילים
        var inputWords = normalizedInput.split(" ").filter(function(w) { return w.length > 1; });
        var titleWords = titleNorm.split(" ").filter(function(w) { return w.length > 1; });
        var matched = 0;
        inputWords.forEach(function (iw) {
          titleWords.forEach(function (tw) {
            if (tw.startsWith(iw) || iw.startsWith(tw)) matched++;
          });
        });
        if (matched > 0 && inputWords.length > 0) {
          score = 0.3 + (0.3 * matched / inputWords.length);
        }
      }

      if (score > 0) {
        results.push({ book: book, score: score });
      }
    });

    results.sort(function (a, b) { return b.score - a.score; });
    return results.slice(0, AUTOCOMPLETE_MAX_RESULTS);
  }

  // ===== מנוע המלצות =====

  function buildProfile(matchedBooks) {
    var profile = {
      genres: {},
      themes: {},
      mood: {},
      style: {},
      audience: {},
      language: {},
      era: {},
      origin: {},        // ארץ מוצא ספרותית
      authors: {},       // מחברים שהמשתמש אוהב
      sub_genres: {},     // סוגות ספציפיות
      series: {},         // סדרות
      narrative_series: {},  // סדרות עלילה בלבד (לא סדרות הוצאה)
      similar_ids: new Set(),
      input_ids: new Set(),
      input_titles: new Set()
    };

    matchedBooks.forEach(function (book) {
      countArray(profile.genres, book.genres);
      // themes: לא נכלל בפרופיל — ראה הערה ב-WEIGHTS
      countArray(profile.mood, book.mood);
      countArray(profile.style, book.style);
      countArray(profile.audience, book.audience);
      if (book.language) profile.language[book.language] = (profile.language[book.language] || 0) + 1;
      if (book.era)      profile.era[book.era]           = (profile.era[book.era]           || 0) + 1;
      if (book.origin)   profile.origin[book.origin]     = (profile.origin[book.origin]     || 0) + 1;

      // סוגה ספציפית
      if (book.sub_genre) {
        profile.sub_genres[book.sub_genre] = (profile.sub_genres[book.sub_genre] || 0) + 1;
      }

      // סדרת עלילה
      if (book.narrative_series) {
        profile.narrative_series[book.narrative_series] = (profile.narrative_series[book.narrative_series] || 0) + 1;
      }

      // מחבר
      var authorKey = normalizeAuthor(book.author);
      if (authorKey) {
        profile.authors[authorKey] = (profile.authors[authorKey] || 0) + 1;
      }

      // ספרים דומים
      if (book.similar_to) {
        book.similar_to.forEach(function (id) {
          profile.similar_ids.add(id);
        });
      }

      profile.input_ids.add(book.id);
      profile.input_titles.add(normalizeTitle(book.title));
    });

    return profile;
  }

  // mood ו-style הם strings בודדים אחרי enrichment — תמיכה בשניהם
  function toArr(val) {
    if (!val) return [];
    return Array.isArray(val) ? val : [val];
  }

  function countArray(obj, arr) {
    toArr(arr).forEach(function (item) {
      obj[item] = (obj[item] || 0) + 1;
    });
  }

  function scoreCandidate(candidate, profile, matchedCount) {
    var score = 0;
    var reasons = [];

    // ז'אנרים
    var genreOverlap = overlapScore(candidate.genres, profile.genres);
    if (genreOverlap > 0) {
      score += genreOverlap * WEIGHTS.genres;
      reasons.push({ type: "genres", items: overlapItems(candidate.genres, profile.genres) });
    }

    // נושאים — הוסר מהניקוד (false positives גבוהים בזיהוי אפס-ירייה)

    // אווירה
    var moodOverlap = overlapScore(candidate.mood, profile.mood);
    if (moodOverlap > 0) {
      score += moodOverlap * WEIGHTS.mood;
      reasons.push({ type: "mood", items: overlapItems(candidate.mood, profile.mood) });
    }

    // סגנון
    var styleOverlap = overlapScore(candidate.style, profile.style);
    if (styleOverlap > 0) {
      score += styleOverlap * WEIGHTS.style;
      reasons.push({ type: "style", items: overlapItems(candidate.style, profile.style) });
    }

    // קהל
    var audienceOverlap = overlapScore(candidate.audience, profile.audience);
    if (audienceOverlap > 0) {
      score += audienceOverlap * WEIGHTS.audience;
    }

    // שפה
    if (candidate.language && profile.language[candidate.language]) {
      score += profile.language[candidate.language] * WEIGHTS.language;
    }

    // תקופה
    if (candidate.era && profile.era[candidate.era]) {
      score += profile.era[candidate.era] * WEIGHTS.era;
    }

    // ארץ מוצא ספרותית
    if (candidate.origin && profile.origin[candidate.origin]) {
      score += profile.origin[candidate.origin] * WEIGHTS.origin;
      reasons.push({ type: 'origin', items: [candidate.origin] });
    }

    // אותו מחבר
    var candidateAuthor = normalizeAuthor(candidate.author);
    if (candidateAuthor && profile.authors[candidateAuthor]) {
      score += WEIGHTS.same_author;
      reasons.push({ type: "author", items: [candidate.author] });
    }

    // בונוס סוגה ספציפית
    if (candidate.sub_genre && profile.sub_genres[candidate.sub_genre]) {
      score += profile.sub_genres[candidate.sub_genre] * 2.0;
    }

    // בונוס סדרת עלילה (narrative_series) — לא series שהוא סדרת הוצאה
    if (candidate.narrative_series && profile.narrative_series[candidate.narrative_series]) {
      score += profile.narrative_series[candidate.narrative_series] * 3.0;
      reasons.push({ type: "series", items: [candidate.narrative_series] });
    }

    // בונוס "דומה ל-"
    if (candidate.id && profile.similar_ids.has(candidate.id)) {
      score += WEIGHTS.similar_to;
      reasons.push({ type: "similar", items: [] });
    }

    // נרמול לפי כמות ספרי קלט
    score = score / Math.max(matchedCount, 1);

    return { score: score, reasons: reasons };
  }

  function overlapScore(candidateArr, profileObj) {
    if (!candidateArr || !profileObj) return 0;
    var total = 0;
    toArr(candidateArr).forEach(function (item) {
      if (profileObj[item]) total += profileObj[item];
    });
    return total;
  }

  function overlapItems(candidateArr, profileObj) {
    if (!candidateArr || !profileObj) return [];
    return toArr(candidateArr).filter(function (item) { return profileObj[item]; });
  }

  function passesFilters(book) {
    if (state.activeFilters.length === 0) return true;
    // קיבוץ לפי טיפוס: AND בין טיפוסים, OR בתוך אותו טיפוס
    var byType = {};
    state.activeFilters.forEach(function (f) {
      if (!byType[f.type]) byType[f.type] = [];
      byType[f.type].push(f.value);
    });
    return Object.keys(byType).every(function (type) {
      var vals = byType[type];
      if (type === "genre")    return vals.some(function (v) { return book.genres && book.genres.indexOf(v) !== -1; });
      if (type === "mood")     return vals.some(function (v) { return book.mood === v; });
      if (type === "origin")   return vals.some(function (v) { return book.origin === v; });
      if (type === "language") return vals.some(function (v) {
        if (v === "translated") return book.language && book.language !== "עברית";
        return true;
      });
      return true;
    });
  }

  function adultPool() {
    return state.adultBooks;
  }

  function getRecommendations(userInputs) {
    var matchedBooks = [];
    var unmatchedInputs = [];

    userInputs.forEach(function (input) {
      if (!input.trim()) return;
      var match = findBook(input);
      if (match) {
        matchedBooks.push(match.book);
      } else {
        unmatchedInputs.push(input);
      }
    });

    if (matchedBooks.length === 0) {
      return {
        success: false,
        message: "לא הצלחנו לזהות את הספרים שהזנתם. נסו לכתוב את שם הספר המדויק, או בחרו מהרשימה שמופיעה תוך כדי הקלדה.",
        results: [],
        matchedCount: 0,
        unmatchedInputs: unmatchedInputs
      };
    }

    var profile = buildProfile(matchedBooks);
    var warnMsg = unmatchedInputs.length > 0
      ? "לא הצלחנו לזהות את: " + unmatchedInputs.join(", ") + ". ההמלצות מבוססות על הספרים שזיהינו."
      : "";

    // ── מסלול סמנטי (כשembeddings.js נטען) ─────────────────────────────────────
    // isReady() מחזיר false לפני הקריאה הראשונה ל-recommend() — לא לבדוק אותו כאן
    if (typeof SemanticRecommender !== "undefined") {
      var semTop = SemanticRecommender.recommend(matchedBooks, state.bookById, {
        excludeIds : profile.input_ids,
        topN       : 200
      });

      if (semTop && semTop.length >= 5) {
        // הזרקת ספרים של אותו מחבר שהסמנטיקה פספסה
        var inputAuthorKeys = {};
        matchedBooks.forEach(function(b) {
          var ak = normalizeAuthor(b.author);
          if (ak) inputAuthorKeys[ak] = true;
        });
        var inSemTop = {};
        semTop.forEach(function(r) { inSemTop[r.book.id] = true; });
        var booksPool = adultPool();

        // חשב טווח סמנטי לפני ההזרקה — ספרים מוזרקים מקבלים ציון אמצע (semNorm≈0.5)
        // כך בונוס אותו-מחבר (5.0) מספיק כדי להכריע על פני ספרים גנריים
        var maxSem  = semTop[0].semanticScore;
        var minSem  = semTop[semTop.length - 1].semanticScore;
        var semSpan = (maxSem - minSem) || 0.001;
        var midScore = minSem + semSpan * 0.5;

        booksPool.forEach(function(b) {
          if (profile.input_ids.has(b.id)) return;
          if (inSemTop[b.id]) return;
          var ak = normalizeAuthor(b.author);
          if (ak && inputAuthorKeys[ak]) {
            semTop.push({ book: b, semanticScore: midScore, closestInputBook: matchedBooks[0], closestSim: 0 });
          }
        });

        var maxMeta = 0;
        var enriched = semTop.map(function (r) {
          if (!passesFilters(r.book)) return null;
          var meta = scoreCandidate(r.book, profile, matchedBooks.length);
          if (meta.score > maxMeta) maxMeta = meta.score;
          return {
            book            : r.book,
            semanticScore   : r.semanticScore,
            metaScore       : meta.score,
            reasons         : meta.reasons,
            closestInputBook: r.closestInputBook,
            closestSim      : r.closestSim
          };
        }).filter(Boolean);

        var metaSpan = maxMeta || 0.001;

        // שילוב: 55% סמנטי + 45% מטאדטה
        enriched.forEach(function (r) {
          var semNorm  = (r.semanticScore - minSem) / semSpan;
          var metaNorm = r.metaScore / metaSpan;
          r.score = 0.55 * semNorm + 0.45 * metaNorm;
        });

        enriched.sort(function (a, b) { return b.score - a.score; });
        var topResults = diversifyResults(enriched, MAX_RESULTS);
        topResults.forEach(function (item) {
          item.explanation = generateExplanation(item, matchedBooks, item.closestInputBook);
        });

        if (topResults.length > 0) {
          return {
            success       : true,
            message       : warnMsg,
            results       : topResults,
            matchedCount  : matchedBooks.length,
            unmatchedInputs: unmatchedInputs
          };
        }
      }
    }

    // ── מסלול מטאדטה בלבד (fallback) ─────────────────────────────────────────
    var candidates = adultPool();
    var scored = [];

    candidates.forEach(function (book) {
      if (profile.input_ids.has(book.id) || profile.input_titles.has(normalizeTitle(book.title))) {
        return;
      }
      if (!passesFilters(book)) return;

      var result = scoreCandidate(book, profile, matchedBooks.length);
      if (result.score > 0) {
        scored.push({ book: book, score: result.score, reasons: result.reasons });
      }
    });

    scored.sort(function (a, b) { return b.score - a.score; });
    var topResults = diversifyResults(scored, MAX_RESULTS);

    topResults.forEach(function (item) {
      item.explanation = generateExplanation(item, matchedBooks, null);
    });

    if (topResults.length === 0) {
      return { success: false, message: "לא מצאנו המלצות מתאימות. נסו להזין ספרים אחרים או לשנות את הסינון.", results: [], matchedCount: matchedBooks.length, unmatchedInputs: unmatchedInputs };
    }

    return { success: true, message: warnMsg, results: topResults, matchedCount: matchedBooks.length, unmatchedInputs: unmatchedInputs };
  }

  /**
   * גיוון תוצאות: מגביל לספר אחד בלבד מכל מחבר (קשיח)
   */
  function diversifyResults(scored, maxCount) {
    var results = [];
    var authorSeen = {};

    for (var i = 0; i < scored.length && results.length < maxCount; i++) {
      var authorKey = normalizeAuthor(scored[i].book.author);
      if (!authorSeen[authorKey]) {
        results.push(scored[i]);
        authorSeen[authorKey] = true;
      }
    }
    return results;
  }

  // ===== הסברים בעברית =====

  // תבניות מגוונות לכל סוג סיבה
  var REASON_VARIANTS = {
    genres: [
      "אם אהבתם {items}, כנראה שתאהבו גם את זה",
      "בז'אנר ה{items} שאתם אוהבים",
      "מתאים לטעם שלכם ב{items}"
    ],
    themes: [
      "עוסק ב{items} - נושא שמעניין אתכם",
      "גם כאן תמצאו {items}",
      "נוגע ב{items} כמו הספרים שאהבתם"
    ],
    mood: [
      "אווירה של {items} - כמו שאתם אוהבים",
      "ספר {items} שידבר אליכם"
    ],
    style: [
      "כתוב בסגנון {items} שמתאים לכם",
      "סגנון {items} - קרוב למה שאהבתם"
    ],
    author: [
      "ספר נוסף של {items}",
      "עוד יצירה של {items} שכבר אהבתם",
      "אם אהבתם את {items}, הנה עוד ספר שלהם"
    ],
    similar: [
      "מומלץ למי שאהב את הספרים שבחרתם",
      "קשור ישירות לספרים שאהבתם"
    ],
    sub_genre: [
      "{sub_genre} סוחף שידבר אליכם",
      "אם אהבתם {sub_genre}, זה בדיוק בשבילכם",
      "{sub_genre} שמזכיר את מה שאהבתם"
    ],
    same_audience: [
      "מתאים לאותו קהל קוראים"
    ],
    same_era: [
      "מאותה תקופה ספרותית שמוצאת חן בעיניכם"
    ]
  };

  // סוגות שכדאי להדגיש בהסבר
  var SUB_GENRE_LABELS = {
    'רומן היסטורי': 'רומן היסטורי',
    'מתח': 'מותחן',
    'מותחן פסיכולוגי': 'מותחן פסיכולוגי',
    'בלש': 'ספר בלשי',
    'פנטזיה': 'ספר פנטזיה',
    'מדע בדיוני': 'מדע בדיוני',
    'אהבה ורומנטיקה': 'רומן רומנטי',
    'הומור וסאטירה': 'ספר הומוריסטי',
    'ממואר': 'ממואר',
    'קומיקס': 'קומיקס',
    'רומן גרפי': 'רומן גרפי',
    'דיסטופיה': 'דיסטופיה',
    'אגדות': 'אגדות',
    'שירה': 'שירה',
    'מחזה': 'מחזה',
    'סיפורים': 'אוסף סיפורים',
    'סיפורים קצרים': 'סיפורים קצרים',
    'קובץ סיפורים': 'אוסף סיפורים',
    'נובלות': 'נובלה',
    'מסות': 'מסות',
    'רומן רומנטי': 'רומן רומנטי',
    'רומן אוטוביוגרפי': 'רומן אוטוביוגרפי',
    'רומן ביוגרפי': 'רומן ביוגרפי',
  };

  function pickVariant(templates) {
    return templates[Math.floor(Math.random() * templates.length)];
  }

  // ז'אנרים/סוגות גנריים שלא כדאי לצטט בהסבר — רחבים מדי, לא אומרים כלום
  var GENERIC_GENRES = {
    "ספרות יפה": true,
    "ילדים ונוער": true,
    "עיון": true,
    "ספרות קלאסית": true,
    "ספרות עברית קלאסית": true,
    "ספרות ישראלית עכשווית": true,
    "ספרות עכשווית": true,
    "רומן": true,
    "פרוזה": true
  };

  /**
   * מוצא את המאפיין המשותף הכי ספציפי בין ספר מומלץ לבין ספר קלט.
   * מחזיר string קצר לשימוש בהסבר, או null.
   */
  function findSharedFeature(book, inputBook) {
    // תת-ז'אנר זהה (הכי ספציפי)
    if (book.sub_genre && book.sub_genre === inputBook.sub_genre &&
        !GENERIC_GENRES[book.sub_genre]) {
      return SUB_GENRE_LABELS[book.sub_genre] || book.sub_genre;
    }
    // נושאים הוסרו — נתון רועש, לא אמין להסברים
    // מצב-רוח זהה
    if (book.mood && book.mood === inputBook.mood) {
      return "אווירה " + book.mood;
    }
    return null;
  }

  function generateExplanation(scoredItem, matchedBooks, closestInputBook) {
    var parts = [];
    var book  = scoredItem.book;
    var usedTypes = {};

    // ── 1. קשר סמנטי לספר קלט קרוב ────────────────────────────────────────
    var closestSim = scoredItem.closestSim || 0;
    if (closestInputBook && closestSim > 0.25) {
      var sharedFeat = findSharedFeature(book, closestInputBook);
      if (sharedFeat) {
        parts.push("\u05D1\u05E8\u05D5\u05D7 \u201C" + closestInputBook.title +
                   "\u201D \u2014 " + sharedFeat);
      } else if (matchedBooks.length === 1 || closestSim > 0.4) {
        parts.push("\u05D1\u05E8\u05D5\u05D7 \u201C" + closestInputBook.title + "\u201D");
      }
    }

    // ── 2. מחבר זהה ─────────────────────────────────────────────────────────
    if (parts.length < 2) {
      var reasons = scoredItem.reasons || [];
      var authorR = null;
      for (var ri = 0; ri < reasons.length; ri++) {
        if (reasons[ri].type === "author") { authorR = reasons[ri]; break; }
      }
      if (authorR && authorR.items && authorR.items.length > 0 && !usedTypes.author) {
        parts.push("ספר נוסף של " + authorR.items[0]);
        usedTypes.author = true;
      }
    }

    // ── 3. נושאים — הוסר (נתון רועש)

    // ── 4. תת-ז'אנר ספציפי ──────────────────────────────────────────────────
    if (parts.length < 2 && book.sub_genre && !GENERIC_GENRES[book.sub_genre]) {
      var sgLabel = SUB_GENRE_LABELS[book.sub_genre] || book.sub_genre;
      var inputHasSG = matchedBooks.some(function (mb) {
        return mb.sub_genre === book.sub_genre ||
               (mb.genres && mb.genres.indexOf(book.sub_genre) !== -1);
      });
      if (inputHasSG) {
        parts.push(sgLabel + " שמתאים לכם");
      }
    }

    // ── 5. ז'אנר ספציפי (לא ספרות יפה) ─────────────────────────────────────
    if (parts.length < 2) {
      var reasons3 = scoredItem.reasons || [];
      for (var ri3 = 0; ri3 < reasons3.length && parts.length < 2; ri3++) {
        var r3 = reasons3[ri3];
        if (r3.type !== "genres" || usedTypes.genres) continue;
        if (r3.items && r3.items.length > 0) {
          var specGenre = null;
          for (var gi = 0; gi < r3.items.length; gi++) {
            if (!GENERIC_GENRES[r3.items[gi]]) { specGenre = r3.items[gi]; break; }
          }
          if (specGenre) {
            parts.push("בז\u05F3\u05D0\u05E0\u05E8 " + specGenre + " \u05E9\u05D0\u05D4\u05D1\u05EA\u05DD");
            usedTypes.genres = true;
          }
        }
      }
    }

    // ── 6. ארץ מוצא ─────────────────────────────────────────────────────────
    if (parts.length < 2 && !usedTypes.origin) {
      var reasons5 = scoredItem.reasons || [];
      for (var ri5 = 0; ri5 < reasons5.length && parts.length < 2; ri5++) {
        var r5 = reasons5[ri5];
        if (r5.type === 'origin' && r5.items && r5.items.length > 0) {
          parts.push('ספרות ' + r5.items[0] + ' — כמו שאהבתם');
          usedTypes.origin = true;
        }
      }
    }

    // ── 7. מצב-רוח ──────────────────────────────────────────────────────────
    if (parts.length < 2 && book.mood) {
      var reasons4 = scoredItem.reasons || [];
      for (var ri4 = 0; ri4 < reasons4.length && parts.length < 2; ri4++) {
        var r4 = reasons4[ri4];
        if (r4.type === "mood" && !usedTypes.mood && r4.items && r4.items.length > 0) {
          parts.push("אווירה " + r4.items[0] + " \u2014 כמו שאהבתם");
          usedTypes.mood = true;
        }
      }
    }

    // ── 8. סדרה ─────────────────────────────────────────────────────────────
    if (parts.length === 0 && book.series) {
      var inputInSeries = matchedBooks.some(function (mb) {
        return mb.series && mb.series === book.series;
      });
      if (inputInSeries) parts.push("ספר נוסף מסדרת " + book.series);
    }

    // ── Fallback ─────────────────────────────────────────────────────────────
    if (parts.length === 0) {
      if (book.sub_genre && !GENERIC_GENRES[book.sub_genre]) {
        parts.push("ספר " + (SUB_GENRE_LABELS[book.sub_genre] || book.sub_genre) +
                   " שמתאים לטעם שלכם");
      } else {
        parts.push("ספר שמתאים לטעם הקריאה שלכם");
      }
    }

    return parts.slice(0, 2).join(". ") + ".";
  }

  // ===== המלצה אקראית =====
  function getRandomRecommendation() {
    var pool = adultPool();
    var filtered = pool.filter(passesFilters);
    if (filtered.length === 0) return null;
    return filtered[Math.floor(Math.random() * filtered.length)];
  }

  // ===== ממשק משתמש =====

  var els = {};

  function initUI() {
    els.bookInputs = document.getElementById("bookInputs");
    els.addBookBtn = document.getElementById("addBookBtn");
    els.getRecsBtn = document.getElementById("getRecsBtn");
    els.randomBtn = document.getElementById("randomBtn");
    els.clearBtn = document.getElementById("clearBtn");
    els.filtersRow = document.getElementById("filtersRow");
    els.moodRow = document.getElementById("moodRow");
    els.moodToggle = document.getElementById("moodToggle");
    els.loadingSection = document.getElementById("loadingSection");
    els.resultsSection = document.getElementById("resultsSection");
    els.resultsTitle = document.getElementById("resultsTitle");
    els.resultsSubtitle = document.getElementById("resultsSubtitle");
    els.resultsGrid = document.getElementById("resultsGrid");
    els.emptySection = document.getElementById("emptySection");
    els.emptyText = document.getElementById("emptyText");
    els.printBtn = document.getElementById("printBtn");
    els.tryAgainBtn = document.getElementById("tryAgainBtn");
    els.emptyRetryBtn = document.getElementById("emptyRetryBtn");

    els.addBookBtn.addEventListener("click", addBookInput);
    els.getRecsBtn.addEventListener("click", handleGetRecs);
    els.randomBtn.addEventListener("click", handleRandom);
    els.clearBtn.addEventListener("click", handleClear);
    els.printBtn.addEventListener("click", function () { window.print(); });
    els.tryAgainBtn.addEventListener("click", handleClear);
    els.emptyRetryBtn.addEventListener("click", handleClear);

    document.querySelectorAll(".filter-chip[data-filter]").forEach(function (chip) {
      chip.addEventListener("click", function () {
        chip.classList.toggle("active");
        updateActiveFilters();
      });
    });

    els.moodToggle.addEventListener("change", function () {
      els.moodRow.classList.toggle("hidden", !els.moodToggle.checked);
      if (!els.moodToggle.checked) {
        document.querySelectorAll("#moodRow .filter-chip.active").forEach(function (c) { c.classList.remove("active"); });
        updateActiveFilters();
      }
    });

    setupAutocomplete(0);

    document.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && e.target.classList.contains("book-input")) {
        closeAllAutocomplete();
        handleGetRecs();
      }
    });

    document.addEventListener("click", function (e) {
      if (!e.target.classList.contains("book-input") && !e.target.classList.contains("autocomplete-item")) {
        closeAllAutocomplete();
      }
    });

    // מודאל ספר
    var bookModal = document.getElementById("bookModal");
    document.getElementById("bookModalClose").addEventListener("click", function () {
      bookModal.classList.add("hidden");
    });
    bookModal.addEventListener("click", function (e) {
      if (e.target === bookModal) bookModal.classList.add("hidden");
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") {
        bookModal.classList.add("hidden");
      }
    });
  }

  function addBookInput() {
    if (state.inputCount >= MAX_BOOKS) return;
    var row = document.createElement("div");
    row.className = "book-input-row";
    row.innerHTML =
      '<div class="input-wrapper">' +
        '<input type="text" class="book-input" placeholder="שם הספר..." autocomplete="off" data-index="' + state.inputCount + '" />' +
        '<div class="autocomplete-list" data-index="' + state.inputCount + '"></div>' +
      '</div>' +
      '<span class="match-status" data-index="' + state.inputCount + '"></span>';
    els.bookInputs.appendChild(row);
    setupAutocomplete(state.inputCount);
    state.inputCount++;
    if (state.inputCount >= MAX_BOOKS) els.addBookBtn.classList.add("hidden");
    row.querySelector(".book-input").focus();
  }

  function setupAutocomplete(index) {
    var input = document.querySelector('.book-input[data-index="' + index + '"]');
    var list = document.querySelector('.autocomplete-list[data-index="' + index + '"]');
    var statusEl = document.querySelector('.match-status[data-index="' + index + '"]');
    if (!input || !list) return;

    var activeIndex = -1;
    var debounceTimer = null;

    input.addEventListener("input", function () {
      var value = input.value.trim();
      activeIndex = -1;

      // Debounce לביצועים עם קטלוג גדול
      clearTimeout(debounceTimer);

      if (value.length < AUTOCOMPLETE_MIN_CHARS) {
        list.classList.remove("visible");
        list.innerHTML = "";
        input.classList.remove("matched", "not-matched");
        statusEl.textContent = "";
        return;
      }

      debounceTimer = setTimeout(function () {
        var suggestions = getAutocompleteSuggestions(value);

        if (suggestions.length === 0) {
          list.classList.remove("visible");
          list.innerHTML = "";
          input.classList.remove("matched");
          input.classList.add("not-matched");
          statusEl.textContent = "?";
          statusEl.title = "לא נמצא בקטלוג";
          return;
        }

        var exactMatch = findBook(value);
        if (exactMatch && exactMatch.score > 0.85) {
          input.classList.remove("not-matched");
          input.classList.add("matched");
          statusEl.textContent = "\u2713";
          statusEl.title = "נמצא: " + exactMatch.book.title;
        } else {
          input.classList.remove("matched", "not-matched");
          statusEl.textContent = "";
        }

        list.innerHTML = "";
        suggestions.forEach(function (item, i) {
          var div = document.createElement("div");
          div.className = "autocomplete-item";
          div.dataset.itemIndex = i;

          var libraryBadge = item.book.in_library
            ? '<span class="ac-library">📗</span>'
            : "";

          div.innerHTML =
            '<span class="ac-title">' + escapeHtml(item.book.title) + '</span>' +
            '<span class="ac-author">/ ' + escapeHtml(item.book.author) + '</span>' +
            libraryBadge;

          div.addEventListener("click", function () {
            input.value = item.book.title;
            list.classList.remove("visible");
            list.innerHTML = "";
            input.classList.remove("not-matched");
            input.classList.add("matched");
            statusEl.textContent = "\u2713";
            statusEl.title = "נמצא: " + item.book.title;
          });
          list.appendChild(div);
        });
        list.classList.add("visible");
      }, 150); // debounce 150ms
    });

    input.addEventListener("keydown", function (e) {
      var items = list.querySelectorAll(".autocomplete-item");
      if (!list.classList.contains("visible") || items.length === 0) return;

      if (e.key === "ArrowDown") {
        e.preventDefault();
        activeIndex = Math.min(activeIndex + 1, items.length - 1);
        updateActiveItem(items, activeIndex);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        activeIndex = Math.max(activeIndex - 1, 0);
        updateActiveItem(items, activeIndex);
      } else if (e.key === "Enter" && activeIndex >= 0) {
        e.preventDefault();
        e.stopPropagation();
        items[activeIndex].click();
      } else if (e.key === "Escape") {
        list.classList.remove("visible");
      }
    });
  }

  function updateActiveItem(items, activeIdx) {
    items.forEach(function (item, i) {
      item.classList.toggle("active", i === activeIdx);
    });
    if (items[activeIdx]) items[activeIdx].scrollIntoView({ block: "nearest" });
  }

  function closeAllAutocomplete() {
    document.querySelectorAll(".autocomplete-list").forEach(function (list) {
      list.classList.remove("visible");
    });
  }

  function updateActiveFilters() {
    state.activeFilters = [];
    document.querySelectorAll(".filter-chip.active").forEach(function (chip) {
      state.activeFilters.push({ type: chip.dataset.filter, value: chip.dataset.value });
    });
  }


  function getUserInputs() {
    var inputs = [];
    document.querySelectorAll(".book-input").forEach(function (input) {
      var val = input.value.trim();
      if (val) inputs.push(val);
    });
    return inputs;
  }

  // ===== פעולות ראשיות =====

  function handleGetRecs() {
    var inputs = getUserInputs();
    if (inputs.length === 0) {
      showEmpty("כדי שנוכל להמליץ, הזינו לפחות שם של ספר אחד שאהבתם.");
      return;
    }

    hideAll();
    els.loadingSection.classList.remove("hidden");

    setTimeout(function () {
      try {
        var result = getRecommendations(inputs);
        els.loadingSection.classList.add("hidden");
        if (result.success) {
          showResults(result);
        } else {
          showEmpty(result.message);
        }
      } catch (err) {
        els.loadingSection.classList.add("hidden");
        showEmpty("שגיאה פנימית: " + err.message);
        console.error("getRecommendations error:", err);
      }
    }, 500);
  }

  function handleRandom() {
    var book = getRandomRecommendation();
    if (!book) {
      showEmpty("לא מצאנו ספרים מתאימים. נסו לשנות את הסינון.");
      return;
    }
    hideAll();
    els.resultsSection.classList.remove("hidden");
    els.resultsTitle.textContent = "הפתעה!";
    els.resultsSubtitle.textContent = "הנה ספר אקראי שאולי תאהבו:";
    els.resultsGrid.innerHTML = "";
    els.resultsGrid.appendChild(createRecCard(book, 1, "ספר אקראי מהקטלוג שלנו - מי יודע, אולי זה בדיוק מה שחיפשתם!", true));
  }

  function handleClear() {
    document.querySelectorAll(".book-input").forEach(function (input) {
      input.value = "";
      input.classList.remove("matched", "not-matched");
    });
    document.querySelectorAll(".match-status").forEach(function (el) { el.textContent = ""; });
    var rows = els.bookInputs.querySelectorAll(".book-input-row");
    for (var i = rows.length - 1; i > 0; i--) rows[i].remove();
    state.inputCount = 1;
    els.addBookBtn.classList.remove("hidden");
    document.querySelectorAll(".filter-chip.active").forEach(function (chip) { chip.classList.remove("active"); });
    els.moodRow.classList.add("hidden");
    els.moodToggle.checked = false;
    state.activeFilters = [];
    hideAll();
    document.querySelector(".book-input").focus();
  }

  function hideAll() {
    els.loadingSection.classList.add("hidden");
    els.resultsSection.classList.add("hidden");
    els.emptySection.classList.add("hidden");
  }

  function showEmpty(message) {
    hideAll();
    els.emptyText.textContent = message;
    els.emptySection.classList.remove("hidden");
  }

  function showResults(result) {
    hideAll();
    els.resultsSection.classList.remove("hidden");

    els.resultsTitle.textContent = "ההמלצות שלנו";

    var subtitle = "מצאנו " + result.results.length + " ספרים שכנראה תאהבו";
    if (result.message) subtitle += " | " + result.message;
    els.resultsSubtitle.textContent = subtitle;

    els.resultsGrid.innerHTML = "";
    result.results.forEach(function (item, idx) {
      var isInLibrary = item.book.in_library || state.libraryTitles.has(normalizeTitle(item.book.title));
      var card = createRecCard(item.book, idx + 1, item.explanation, isInLibrary);
      if (item.aiRecommended) card.classList.add("ai-rec-card");
      els.resultsGrid.appendChild(card);
    });
  }

  function createRecCard(book, rank, explanation, isInLibrary) {
    var card = document.createElement("div");
    card.className = "rec-card";

    var tagsHtml = "";
    // Show sub_genre as primary tag if available (more specific)
    if (book.sub_genre && SUB_GENRE_LABELS[book.sub_genre]) {
      tagsHtml += '<span class="rec-tag sub-genre-tag">' + escapeHtml(SUB_GENRE_LABELS[book.sub_genre]) + '</span>';
    }
    if (book.genres) {
      book.genres.forEach(function (g) {
        // Skip if already shown as sub-genre tag
        if (book.sub_genre && SUB_GENRE_LABELS[book.sub_genre] === g) return;
        tagsHtml += '<span class="rec-tag">' + escapeHtml(g) + '</span>';
      });
    }
    if (isInLibrary) {
      tagsHtml += '<span class="rec-tag library-tag">📗 קיים בספריית שחרות</span>';
    }

    var shelfHtml = "";
    if (isInLibrary && book.shelf) {
      shelfHtml = '<div class="rec-card-shelf">📍 מדף: ' + escapeHtml(book.shelf) + '</div>';
    }

    var descHtml = "";
    if (book.description) {
      var desc = book.description;
      var truncated = desc.length > 150;
      var shortDesc = truncated ? desc.substring(0, 150) + '...' : desc;
      descHtml = '<div class="rec-card-description">' +
        '<p class="desc-text">' + escapeHtml(shortDesc) + '</p>' +
        (truncated ? '<button class="desc-toggle" onclick="this.previousElementSibling.textContent=this.dataset.full;this.remove();" data-full="' + escapeHtml(desc).replace(/"/g, '&quot;') + '">קראו עוד</button>' : '') +
        '</div>';
    }

    card.innerHTML =
      '<div class="rec-card-header">' +
        '<div>' +
          '<div class="rec-card-title">' + escapeHtml(book.title) + '</div>' +
          '<div class="rec-card-author">' + escapeHtml(book.author) + '</div>' +
        '</div>' +
        '<div class="rec-card-rank">' + rank + '</div>' +
      '</div>' +
      '<div class="rec-card-tags">' + tagsHtml + '</div>' +
      '<div class="rec-card-reason">' + escapeHtml(explanation) + '</div>' +
      descHtml +
      shelfHtml +
      createSimilarStrip(book);

    // אירועי chips
    card.querySelectorAll(".similar-chip").forEach(function (chip) {
      chip.addEventListener("click", function (e) {
        e.stopPropagation();
        var b = state.bookById[chip.dataset.bookId];
        if (b) showBookModal(b);
      });
    });

    return card;
  }

  // ===== מודאל ספר + ספרים דומים =====

  function createSimilarStrip(book, limit) {
    limit = limit || 5;
    if (!book.similar || !book.similar.length) return "";
    var chips = "";
    var count = 0;
    for (var i = 0; i < book.similar.length && count < limit; i++) {
      var sb = state.bookById[book.similar[i]];
      if (!sb) continue;
      chips += '<button class="similar-chip" data-book-id="' + escapeAttr(sb.id) + '" title="' + escapeAttr(sb.author) + '">' +
        escapeHtml(sb.title) + "</button>";
      count++;
    }
    if (!chips) return "";
    return '<div class="rec-card-similar">' +
      '<span class="similar-label">ספרים דומים:</span>' +
      chips +
      "</div>";
  }

  function showBookModal(book) {
    var isInLib = book.in_library || state.libraryTitles.has(normalizeTitle(book.title));

    // תגיות
    var tagsHtml = "";
    if (book.sub_genre) {
      tagsHtml += '<span class="rec-tag sub-genre-tag">' + escapeHtml(book.sub_genre) + "</span>";
    }
    (book.genres || []).forEach(function (g) {
      if (g !== book.sub_genre) tagsHtml += '<span class="rec-tag">' + escapeHtml(g) + "</span>";
    });
    if (isInLib) tagsHtml += '<span class="rec-tag library-tag">📗 קיים בספריית שחרות</span>';

    // מדף
    var shelfHtml = isInLib && book.shelf
      ? '<div class="book-modal-shelf">📍 מדף: ' + escapeHtml(book.shelf) + "</div>"
      : "";

    // תקציר
    var descHtml = book.description
      ? '<div class="book-modal-desc"><p>' + escapeHtml(book.description) + "</p></div>"
      : "";

    // ספרים דומים במודאל (6)
    var modalSimilar = "";
    if (book.similar && book.similar.length) {
      var chips = "";
      book.similar.slice(0, 6).forEach(function (id) {
        var sb = state.bookById[id];
        if (sb) {
          chips += '<button class="similar-chip" data-book-id="' + escapeAttr(sb.id) + '" title="' + escapeAttr(sb.author) + '">' +
            escapeHtml(sb.title) + "</button>";
        }
      });
      if (chips) {
        modalSimilar = '<div class="book-modal-similar">' +
          '<div class="similar-section-label">ספרים דומים</div>' +
          '<div class="similar-chips-row">' + chips + "</div>" +
          "</div>";
      }
    }

    // עדכן מודאל
    document.getElementById("bookModalTitle").textContent = book.title;
    document.getElementById("bookModalAuthor").textContent = book.author || "";
    var body = document.getElementById("bookModalBody");
    body.innerHTML =
      '<div class="book-modal-tags">' + tagsHtml + "</div>" +
      shelfHtml +
      descHtml +
      modalSimilar;

    // הוסף אירועים לchips
    body.querySelectorAll(".similar-chip").forEach(function (chip) {
      chip.addEventListener("click", function () {
        var b = state.bookById[chip.dataset.bookId];
        if (b) showBookModal(b);
      });
    });

    document.getElementById("bookModal").classList.remove("hidden");
  }

  function escapeAttr(text) {
    if (!text) return "";
    return text.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function escapeHtml(text) {
    if (!text) return "";
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
  }

  // ===== הפעלה =====
  function init() {
    initData();
    initUI();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();
