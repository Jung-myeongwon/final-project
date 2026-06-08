const $ = (id) => document.getElementById(id);

const state = {
  genres: [],
  directors: [],
  actors: [],
  like_movies: []
};

const optionStore = {
  genres: [],
  directors: [],
  actors: [],
  titles: []
};

const chipMap = {
  genres: "genresChips",
  directors: "directorsChips",
  actors: "actorsChips",
  like_movies: "likeMoviesChips"
};


function currentProfileId() {
  return localStorage.getItem("tastelab_active_profile") || "profile1";
}

function profileKey(name) {
  return `tastelab:${currentProfileId()}:${name}`;
}

function loadJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch (_) {
    return fallback;
  }
}

function saveJson(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

function getMovieFeedback() {
  return loadJson(profileKey("movieFeedback"), {});
}

function persistMovieTaste() {
  saveJson(profileKey("movieTaste"), state);
}

function loadPersistedMovieState() {
  const saved = loadJson(profileKey("movieTaste"), {});
  state.genres = Array.isArray(saved.genres) ? saved.genres : [];
  state.directors = Array.isArray(saved.directors) ? saved.directors : [];
  state.actors = Array.isArray(saved.actors) ? saved.actors : [];
  state.like_movies = Array.isArray(saved.like_movies) ? saved.like_movies : [];
}

function startWithEmptyMovieTaste() {
  state.genres = [];
  state.directors = [];
  state.actors = [];
  state.like_movies = [];
  ["movieInput", "directorInput", "actorInput"].forEach(id => {
    const el = $(id);
    if (el) el.value = "";
  });
}

function likedMovieTitlesFromFeedback(limit = 3) {
  return Object.values(getMovieFeedback())
    .filter(item => item && item.status === "liked" && item.title)
    .map(item => item.title)
    .slice(-Math.max(1, limit));
}

function excludedMovieIdsFromFeedback() {
  return Object.entries(getMovieFeedback())
    .filter(([, item]) => item && ["liked", "disliked", "not_interested"].includes(item.status))
    .map(([id]) => Number(id))
    .filter(Number.isFinite);
}

function mergeUnique(values) {
  const result = [];
  (values || []).forEach(v => {
    const text = normalize(v);
    if (text && !result.some(x => x.toLowerCase() === text.toLowerCase())) result.push(text);
  });
  return result;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeText(value, fallback = "") {
  return value === null || value === undefined || value === "" ? fallback : value;
}

function normalize(value) {
  return String(value || "").trim();
}

function fillDatalist(id, values) {
  const el = $(id);
  el.innerHTML = values
    .filter(Boolean)
    .slice(0, 4000)
    .map(v => `<option value="${escapeHtml(v)}"></option>`)
    .join("");
}

function searchLocalOptions(values, query, limit = 12) {
  const q = normalize(query).toLowerCase();
  if (!q) return [];
  const compactQ = q.replaceAll(" ", "");
  const seen = new Set();
  return (values || [])
    .filter(Boolean)
    .filter(v => {
      const text = String(v).toLowerCase();
      const compact = text.replaceAll(" ", "");
      return text.includes(q) || compact.includes(compactQ);
    })
    .filter(v => {
      const key = String(v).toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, limit);
}

function bindLocalAutocomplete(inputId, suggestId, getItems, onPick, label = "후보") {
  const input = $(inputId);
  const box = $(suggestId);
  if (!input || !box) return;

  const hide = () => box.classList.remove("show");
  const show = () => {
    const items = searchLocalOptions(getItems(), input.value, 12);
    if (!normalize(input.value)) {
      hide();
      return;
    }
    if (!items.length) {
      box.innerHTML = `<div class="suggestion-empty">일치하는 ${label}가 없으면 직접 입력 후 추가해도 됩니다.</div>`;
      box.classList.add("show");
      return;
    }
    box.innerHTML = items.map(v => `
      <button class="suggestion-item" type="button" data-value="${escapeHtml(v)}">
        <b>${escapeHtml(v)}</b>
        <span>${escapeHtml(label)}</span>
      </button>`).join("");
    box.classList.add("show");
    box.querySelectorAll(".suggestion-item").forEach(btn => {
      btn.addEventListener("mousedown", (e) => {
        e.preventDefault();
        onPick(btn.dataset.value);
        input.value = "";
        hide();
        input.focus();
      });
    });
  };

  input.addEventListener("input", show);
  input.addEventListener("focus", show);
  input.addEventListener("blur", () => setTimeout(hide, 120));
}

function setupMovieAutocomplete() {
  bindLocalAutocomplete("movieInput", "movieSuggest", () => optionStore.titles, v => addItem("like_movies", v), "영화");
  bindLocalAutocomplete("directorInput", "directorSuggest", () => optionStore.directors, v => addItem("directors", v), "감독");
  bindLocalAutocomplete("actorInput", "actorSuggest", () => optionStore.actors, v => addItem("actors", v), "배우");
}

function addItem(key, value) {
  const v = normalize(value);
  if (!v) return;
  if (!state[key].some(x => x.toLowerCase() === v.toLowerCase())) {
    state[key].push(v);
  }
  persistMovieTaste();
  renderChips();
  renderGenreButtons();
}

function removeItem(key, value) {
  state[key] = state[key].filter(x => x !== value);
  persistMovieTaste();
  renderChips();
  renderGenreButtons();
}

function renderChips() {
  Object.entries(chipMap).forEach(([key, id]) => {
    const box = $(id);
    const items = state[key] || [];
    box.innerHTML = items.length
      ? items.map(v => `
          <button class="chip" type="button" data-key="${key}" data-value="${escapeHtml(v)}">
            ${escapeHtml(v)} <span>×</span>
          </button>
        `).join("")
      : `<span class="empty-chip">아직 선택 없음</span>`;
  });

  document.querySelectorAll(".chip").forEach(btn => {
    btn.addEventListener("click", () => removeItem(btn.dataset.key, btn.dataset.value));
  });
}

function renderGenreButtons() {
  const box = $("genreButtons");
  const preferred = ["Action", "Adventure", "Animation", "Comedy", "Crime", "Drama", "Fantasy", "Horror", "Mystery", "Romance", "Science Fiction", "Thriller", "War", "액션", "드라마", "SF", "스릴러", "코미디", "로맨스"];
  const ordered = [...optionStore.genres].sort((a, b) => {
    const ai = preferred.findIndex(p => a.toLowerCase().includes(p.toLowerCase()) || p.toLowerCase().includes(a.toLowerCase()));
    const bi = preferred.findIndex(p => b.toLowerCase().includes(p.toLowerCase()) || p.toLowerCase().includes(b.toLowerCase()));
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi) || a.localeCompare(b);
  });

  box.innerHTML = ordered.map(g => {
    const active = state.genres.includes(g) ? "active" : "";
    return `<button class="genre-btn ${active}" type="button" data-genre="${escapeHtml(g)}">${escapeHtml(g)}</button>`;
  }).join("");

  document.querySelectorAll(".genre-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const value = btn.dataset.genre;
      if (state.genres.includes(value)) removeItem("genres", value);
      else addItem("genres", value);
    });
  });
}

function bindAdd(inputId, buttonId, key) {
  const input = $(inputId);
  const add = () => {
    addItem(key, input.value);
    input.value = "";
    input.focus();
  };
  $(buttonId).addEventListener("click", add);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      add();
    }
  });
}

function reasonList(movie) {
  const items = movie.reason_items || [];
  if (items.length) {
    return `
      <div class="reason-box">
        <div class="section-title">추천 이유</div>
        ${items.map(item => `
          <div class="reason-item">
            <span class="reason-icon">${escapeHtml(item.icon || "✓")}</span>
            <div>
              <b>${escapeHtml(item.title || "추천 근거")}</b>
              <p>${escapeHtml(item.detail || "취향 분석 기반 추천")}</p>
            </div>
          </div>
        `).join("")}
      </div>`;
  }
  return `<p class="reason">${escapeHtml(safeText(movie.reason, "취향 분석 기반 추천"))}</p>`;
}

function musicCards(tracks, type = "track") {
  if (!tracks || !tracks.length) return "";
  return tracks.slice(0, 5).map(t => {
    const cover = t.image_url || t.album_image_url || "";
    const image = cover
      ? `<img src="${escapeHtml(cover)}" alt="${escapeHtml(t.name || '음악')}" loading="lazy" onerror="this.outerHTML='<div class=&quot;music-placeholder&quot;>♪</div>'" />`
      : `<div class="music-placeholder">♪</div>`;
    const label = `${safeText(t.name, "제목 없음")}${t.artist ? ` - ${t.artist}` : ""}`;
    const tag = t.tag ? `<span class="music-tag">${escapeHtml(t.tag)}</span>` : "";
    const content = `
      ${image}
      <div>
        <strong>${escapeHtml(label)}</strong>
        ${tag}
      </div>`;
    return t.lastfm_url
      ? `<a class="music-card" href="${escapeHtml(t.lastfm_url)}" target="_blank" rel="noreferrer">${content}</a>`
      : `<div class="music-card">${content}</div>`;
  }).join("");
}

function trailerButtonHtml(url) {
  return `<a class="trailer-btn trailer-btn--block" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">▶ YouTube 예고편 / 트레일러 보기</a>`;
}

function trailerLoadingHtml() {
  return `<span class="trailer-loading">YouTube 예고편 링크 불러오는 중…</span>`;
}

function trailerEmptyHtml() {
  return `<span class="trailer-empty">등록된 YouTube 예고편이 없습니다</span>`;
}

function trailerMissingKeyHtml() {
  return `<span class="trailer-missing-key">TMDB_API_KEY를 .env에 설정하면 예고편 버튼이 표시됩니다</span>`;
}

function renderTrailerSlot(card, url) {
  const slot = card.querySelector(".trailer-slot");
  if (!slot || !url) return;
  slot.classList.remove("trailer-slot--pending");
  slot.removeAttribute("aria-hidden");
  slot.innerHTML = trailerButtonHtml(url);
}

function setTrailerSlotMessage(card, html) {
  const slot = card.querySelector(".trailer-slot");
  if (!slot) return;
  slot.classList.remove("trailer-slot--pending");
  slot.removeAttribute("aria-hidden");
  slot.innerHTML = html;
}

async function enrichTrailers(scope = document) {
  const cards = [...scope.querySelectorAll(".card[data-tmdb-id]")];
  await Promise.all(cards.map(async (card) => {
    const tid = (card.dataset.tmdbId || "").trim();
    if (!tid) {
      setTrailerSlotMessage(card, trailerEmptyHtml());
      return;
    }
    if (card.querySelector(".trailer-btn")) return;

    setTrailerSlotMessage(card, trailerLoadingHtml());
    try {
      const res = await fetch(`/api/movie/${encodeURIComponent(tid)}/trailer`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "예고편 조회 실패");
      if (data.api_key_missing) {
        setTrailerSlotMessage(card, trailerMissingKeyHtml());
        return;
      }
      if (data.trailer_url) {
        renderTrailerSlot(card, data.trailer_url);
      } else {
        setTrailerSlotMessage(card, trailerEmptyHtml());
      }
    } catch (_) {
      setTrailerSlotMessage(card, trailerEmptyHtml());
    }
  }));
}

function movieExternalMusicHtml(data, options = {}) {
  const ost = musicCards(data.soundtracks || [], "album");
  const genreMusic = musicCards(data.music_by_genre || [], "track");
  const openAttr = options.open ? " open" : "";
  const body = (ost || genreMusic)
    ? `${ost ? `<div class="section-title small">OST / 사운드트랙</div><div class="music-grid">${ost}</div>` : ""}
       ${genreMusic ? `<div class="section-title small">장르 기반 추천 음악</div><div class="music-grid">${genreMusic}</div>` : ""}`
    : `<p class="lazy-detail-message">OST/추천 음악 정보를 찾지 못했습니다.</p>`;
  return `
    <details class="music-details movie-external-details"${openAttr} data-loaded="1">
      <summary>OST / 추천 음악 보기</summary>
      ${body}
    </details>`;
}

function pendingMovieExternalMusicHtml() {
  return `
    <details class="music-details movie-external-details" data-loaded="0">
      <summary>OST / 추천 음악 보기</summary>
      <p class="lazy-detail-message">추천 결과는 먼저 보여주고, OST와 추천 음악은 뒤에서 준비하고 있어요.</p>
    </details>`;
}

function failedMovieExternalMusicHtml(message, wasOpen = false) {
  return `
    <details class="music-details movie-external-details"${wasOpen ? " open" : ""} data-loaded="0">
      <summary>OST / 추천 음악 보기</summary>
      <p class="lazy-detail-message">OST/추천 음악 정보를 불러오지 못했습니다.${message ? ` (${escapeHtml(message)})` : ""}</p>
    </details>`;
}

async function loadMovieExternalDetailsForCard(card) {
  const box = card?.querySelector(".movie-external-details");
  if (!card || !box || box.dataset.loading === "1" || box.dataset.loaded === "1") return;
  box.dataset.loading = "1";
  const genres = (() => {
    try { return JSON.parse(card.dataset.genres || "[]"); } catch (_) { return []; }
  })();
  try {
    const res = await fetch("/api/movie/external-details", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tmdb_id: card.dataset.tmdbId ? Number(card.dataset.tmdbId) : null,
        title: card.dataset.title || "",
        genres,
        music_limit: 5
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "세부정보를 불러오지 못했습니다.");
    const wasOpen = box.open;
    box.outerHTML = movieExternalMusicHtml(data, { open: wasOpen });
  } catch (err) {
    const wasOpen = box.open;
    box.outerHTML = failedMovieExternalMusicHtml(err.message || String(err), wasOpen);
  } finally {
    /* trailer is loaded by enrichTrailers */
  }
}

function loadMovieExternalDetailsInBackground(scope = document) {
  const cards = [...scope.querySelectorAll(".card[data-tmdb-id]")];
  cards.forEach(card => {
    window.setTimeout(() => loadMovieExternalDetailsForCard(card), 0);
  });
}

function movieCard(movie, index) {
  const poster = movie.poster_url
    ? `<img class="poster" src="${escapeHtml(movie.poster_url)}" alt="${escapeHtml(safeText(movie.title, '영화'))} 포스터" loading="lazy" onerror="this.outerHTML='<div class=&quot;no-poster&quot;>포스터 없음</div>'" />`
    : `<div class="no-poster">포스터 없음</div>`;

  const year = movie.release_date ? String(movie.release_date).slice(0, 4) : "";
  const score = movie.tmdb_score ? `TMDB ${Number(movie.tmdb_score).toFixed(1)}` : "";
  const imdb = movie.imdb_score ? `IMDb ${movie.imdb_score}` : "";
  const meta = [year, score, imdb].filter(Boolean).join(" · ");
  const genres = (movie.genres || []).slice(0, 5).map(g => `<span class="tag">${escapeHtml(g)}</span>`).join("");
  const directors = (movie.directors || []).slice(0, 2).join(", ");
  const actors = (movie.actors || []).slice(0, 4).join(", ");
  const confidence = Math.max(1, Math.min(100, Math.round((movie.match_score || 0) * 100)));
  const trailerInner = movie.trailer_url ? trailerButtonHtml(movie.trailer_url) : trailerLoadingHtml();

  const ost = musicCards(movie.soundtracks || [], "album");
  const genreMusic = musicCards(movie.music_by_genre || [], "track");
  const musicSection = (ost || genreMusic)
    ? movieExternalMusicHtml(movie)
    : pendingMovieExternalMusicHtml();

  return `
    <article class="card" data-tmdb-id="${escapeHtml(movie.tmdb_id ?? "")}" data-title="${escapeHtml(safeText(movie.title, ""))}" data-genres="${escapeHtml(JSON.stringify(movie.genres || []))}">
      <div class="poster-wrap">
        ${poster}
        <span class="rank">#${index + 1}</span>
      </div>
      <div class="card-body">
        <div class="card-topline">
          <span class="score-badge">${escapeHtml(meta || "평점 정보 없음")}</span>
        </div>
        <h3 class="title">${escapeHtml(safeText(movie.title, "제목 없음"))}</h3>
        <div class="trailer-slot">${trailerInner}</div>
        <p class="overview">${escapeHtml(safeText(movie.overview_short, "줄거리 정보 없음"))}</p>
        <div class="tags">${genres}</div>
        ${directors ? `<p class="people"><b>감독</b> ${escapeHtml(directors)}</p>` : ""}
        ${actors ? `<p class="people"><b>배우</b> ${escapeHtml(actors)}</p>` : ""}
        <div class="match-meter">
          <span>취향 적합도</span>
          <div><i style="width:${confidence}%"></i></div>
          <b>${confidence}%</b>
        </div>
        ${reasonList(movie)}
        <div class="feedback-actions" data-tmdb-id="${escapeHtml(movie.tmdb_id ?? "")}" data-title="${escapeHtml(safeText(movie.title, ""))}">
          <button class="feedback-btn liked" type="button" data-feedback="liked">봤어요 · 좋았음</button>
          <button class="feedback-btn disliked" type="button" data-feedback="disliked">봤어요 · 별로</button>
          <button class="feedback-btn muted" type="button" data-feedback="not_interested">관심 없음</button>
        </div>
        ${musicSection}
      </div>
    </article>`;
}


function markMovieFeedback(tmdbId, title, status) {
  if (!tmdbId) return;
  const feedback = getMovieFeedback();
  feedback[String(tmdbId)] = {
    status,
    title,
    updated_at: new Date().toISOString()
  };
  saveJson(profileKey("movieFeedback"), feedback);

  if (status === "liked" && title) {
    addItem("like_movies", title);
  }
}

function syncFeedbackButtonStates() {
  const feedback = getMovieFeedback();
  document.querySelectorAll(".feedback-actions").forEach(group => {
    const item = feedback[String(group.dataset.tmdbId || "")];
    group.querySelectorAll(".feedback-btn").forEach(btn => {
      const active = item && item.status === btn.dataset.feedback;
      btn.classList.toggle("active", Boolean(active));
    });
  });
}

function bindMovieFeedbackButtons() {
  document.querySelectorAll(".feedback-actions .feedback-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const group = btn.closest(".feedback-actions");
      const tmdbId = group?.dataset.tmdbId;
      const title = group?.dataset.title || "";
      const status = btn.dataset.feedback;
      markMovieFeedback(tmdbId, title, status);
      syncFeedbackButtonStates();
      const label = status === "liked" ? "좋았던 영화로 저장했어요. 다음 추천에서 유사 영화에 가산점을 줍니다." : "다음 추천에서 제외하도록 저장했어요.";
      if ($("status")) $("status").textContent = label;
    });
  });
  syncFeedbackButtonStates();
}

function renderSummary() {
  const filled = [
    ["장르", state.genres],
    ["영화", state.like_movies],
    ["감독", state.directors],
    ["배우", state.actors]
  ].filter(([, values]) => values.length);

  const summary = $("summary");
  if (!filled.length) {
    summary.classList.add("hidden");
    summary.innerHTML = "";
    return;
  }

  summary.classList.remove("hidden");
  summary.innerHTML = filled.map(([label, values]) => `
    <div class="summary-item">
      <span>${label}</span>
      <b>${escapeHtml(values.slice(0, 3).join(", "))}${values.length > 3 ? ` 외 ${values.length - 3}` : ""}</b>
    </div>
  `).join("");
}


function bindContainedTableScroll() {
  document.querySelectorAll(".taste-scroll").forEach(area => {
    area.addEventListener("wheel", (e) => {
      const canScroll = area.scrollHeight > area.clientHeight;
      if (!canScroll) return;
      area.scrollTop += e.deltaY;
      e.preventDefault();
      e.stopPropagation();
    }, { passive: false });
  });
}

async function loadOptions() {
  const status = $("status");
  status.textContent = "선택 목록을 불러오는 중입니다.";
  const res = await fetch("/api/options");
  if (!res.ok) throw new Error("선택 목록을 불러오지 못했습니다.");
  const data = await res.json();
  optionStore.genres = data.genres || [];
  optionStore.directors = data.directors || [];
  optionStore.actors = data.actors || [];
  optionStore.titles = data.titles || [];

  fillDatalist("movieList", optionStore.titles);
  fillDatalist("directorList", optionStore.directors);
  fillDatalist("actorList", optionStore.actors);
  setupMovieAutocomplete();
  startWithEmptyMovieTaste();
  renderGenreButtons();
  renderChips();
  renderSummary();
  status.textContent = "취향을 표에 입력하고 추천받기를 눌러주세요.";
}

async function recommend(excludeLast = false) {
  const status = $("status");
  const results = $("results");
  renderSummary();
  status.textContent = "추천 결과를 계산하는 중입니다.";
  results.innerHTML = "";

  const body = {
    genres: state.genres,
    directors: state.directors,
    actors: state.actors,
    like_movies: mergeUnique([...state.like_movies, ...likedMovieTitlesFromFeedback(3)]),
    min_score: Number($("min_score").value || 6.5),
    top_n: Number($("top_n").value || 8),
    music_limit: 5,
    exclude_last: excludeLast,
    exclude_tmdb_ids: excludedMovieIdsFromFeedback()
  };

  const res = await fetch("/api/recommend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "추천 중 오류가 발생했습니다.");

  const movies = data.results || [];
  if (!movies.length) {
    status.textContent = "조건에 맞는 영화가 없습니다. 최소 평점을 낮추거나 선택 조건을 줄여보세요.";
    return;
  }
  status.textContent = `${movies.length}개의 추천 결과를 찾았습니다.`;
  results.innerHTML = movies.map(movieCard).join("");
  bindMovieFeedbackButtons();
  enrichTrailers(results);
  loadMovieExternalDetailsInBackground(results);
}

function clearTaste() {
  state.genres = [];
  state.directors = [];
  state.actors = [];
  state.like_movies = [];
  ["movieInput", "directorInput", "actorInput"].forEach(id => $(id).value = "");
  persistMovieTaste();
  renderChips();
  renderGenreButtons();
  renderSummary();
}


function applyMovieStateFromAssistant(nextState = {}) {
  ["genres", "directors", "actors", "like_movies"].forEach(key => {
    if (Array.isArray(nextState[key])) {
      state[key] = mergeUnique([...state[key], ...nextState[key]]);
    }
  });
  persistMovieTaste();
  renderChips();
  renderGenreButtons();
  renderSummary();
}

async function renderAssistantMovieResults(movies, message = "AI 추천 결과를 불러왔습니다.") {
  const status = $("status");
  const results = $("results");
  if (!movies || !movies.length) {
    if (status) status.textContent = message || "추천 결과가 없습니다.";
    return;
  }
  if (status) status.textContent = message;
  if (results) results.innerHTML = movies.map(movieCard).join("");
  bindMovieFeedbackButtons();
  enrichTrailers(results);
  loadMovieExternalDetailsInBackground(results);
}

window.TasteLabMovies = {
  getState: () => ({
    genres: [...state.genres],
    directors: [...state.directors],
    actors: [...state.actors],
    like_movies: [...state.like_movies]
  }),
  getLikedMovieTitles: () => mergeUnique([...state.like_movies, ...likedMovieTitlesFromFeedback(3)]),
  getExcludedMovieIds: excludedMovieIdsFromFeedback,
  applyState: applyMovieStateFromAssistant,
  renderAssistantResults: renderAssistantMovieResults,
};

window.addEventListener("tastelab:profilechange", () => {
  startWithEmptyMovieTaste();
  renderChips();
  renderGenreButtons();
  renderSummary();
  $("results").innerHTML = "";
  $("status").textContent = "프로필이 변경되었습니다. 이 프로필의 취향으로 새롭게 추천받을 수 있습니다.";
});

bindAdd("movieInput", "addMovieBtn", "like_movies");
bindAdd("directorInput", "addDirectorBtn", "directors");
bindAdd("actorInput", "addActorBtn", "actors");

$("recommendBtn").addEventListener("click", () => recommend(false).catch(e => $("status").textContent = e.message));
$("retryBtn").addEventListener("click", () => recommend(true).catch(e => $("status").textContent = e.message));
$("resetBtn").addEventListener("click", async () => {
  await fetch("/api/reset", { method: "POST" });
  $("status").textContent = "추천 기록을 초기화했습니다.";
});
$("clearBtn").addEventListener("click", clearTaste);

bindContainedTableScroll();
loadOptions().catch(e => $("status").textContent = e.message);
