const $ = (id) => document.getElementById(id);

const musicState = {
  genres: [],
  artists: [],
  tracks: [],
  albums: []
};

const musicChipMap = {
  genres: "musicGenresChips",
  artists: "artistsChips",
  tracks: "tracksChips",
  albums: "albumsChips"
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

function musicTrackKey(name, artist = "") {
  const clean = (value) => normalize(value).toLowerCase().replace(/\s+/g, " ");
  return `${clean(name)}::${clean(artist)}`;
}

function getMusicFeedback() {
  return loadJson(profileKey("musicFeedback"), {});
}

function likedMusicTracksFromFeedback(limit = 2) {
  return Object.values(getMusicFeedback())
    .filter(item => item && item.status === "liked" && item.name)
    .map(item => item.name)
    .slice(-Math.max(1, limit));
}

function excludedMusicTrackKeysFromFeedback() {
  return Object.entries(getMusicFeedback())
    .filter(([, item]) => item && ["liked", "disliked", "not_interested"].includes(item.status))
    .map(([key]) => key)
    .filter(Boolean);
}

function persistMusicTaste() {
  saveJson(profileKey("musicTaste"), musicState);
}

function loadPersistedMusicState() {
  const saved = loadJson(profileKey("musicTaste"), {});
  musicState.genres = Array.isArray(saved.genres) ? saved.genres : [];
  musicState.artists = Array.isArray(saved.artists) ? saved.artists : [];
  musicState.tracks = Array.isArray(saved.tracks) ? saved.tracks : [];
  musicState.albums = Array.isArray(saved.albums) ? saved.albums : [];
  musicOffset = 0;
}

function startWithEmptyMusicTaste() {
  musicState.genres = [];
  musicState.artists = [];
  musicState.tracks = [];
  musicState.albums = [];
  musicOffset = 0;
  ["musicGenreInput", "artistInput", "trackInput", "albumInput"].forEach(id => {
    const el = $(id);
    if (el) el.value = "";
  });
}

function mergeUnique(values) {
  const result = [];
  (values || []).forEach(v => {
    const text = normalize(v);
    if (text && !result.some(x => x.toLowerCase() === text.toLowerCase())) result.push(text);
  });
  return result;
}

let genreOptions = [];
let musicOffset = 0;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function normalize(value) {
  return String(value || "").trim();
}

function debounce(fn, delay = 220) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
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

function renderSuggestions(box, items, label, onPick, emptyText) {
  if (!items.length) {
    box.innerHTML = `<div class="suggestion-empty">${escapeHtml(emptyText || "후보가 없어도 직접 입력 후 추가할 수 있습니다.")}</div>`;
    box.classList.add("show");
    return;
  }
  box.innerHTML = items.map(item => {
    const value = typeof item === "string" ? item : item.value;
    const main = typeof item === "string" ? item : (item.label || item.value);
    const sub = typeof item === "string" ? label : (item.sub || label);
    return `<button class="suggestion-item" type="button" data-value="${escapeHtml(value)}">
      <b>${escapeHtml(main)}</b>
      <span>${escapeHtml(sub)}</span>
    </button>`;
  }).join("");
  box.classList.add("show");
  box.querySelectorAll(".suggestion-item").forEach(btn => {
    btn.addEventListener("mousedown", (e) => {
      e.preventDefault();
      onPick(btn.dataset.value);
    });
  });
}

function bindLocalMusicAutocomplete(inputId, suggestId, getItems, key, label) {
  const input = $(inputId);
  const box = $(suggestId);
  const hide = () => box.classList.remove("show");
  const show = () => {
    const q = normalize(input.value);
    if (!q) return hide();
    const items = searchLocalOptions(getItems(), q, 12);
    renderSuggestions(box, items, label, (value) => {
      addMusicItem(key, value);
      input.value = "";
      hide();
      input.focus();
    }, `일치하는 ${label}가 없으면 직접 입력 후 추가해도 됩니다.`);
  };
  input.addEventListener("input", show);
  input.addEventListener("focus", show);
  input.addEventListener("blur", () => setTimeout(hide, 120));
}

function bindRemoteMusicAutocomplete(inputId, suggestId, kind, key, label) {
  const input = $(inputId);
  const box = $(suggestId);
  const hide = () => box.classList.remove("show");
  const load = debounce(async () => {
    const q = normalize(input.value);
    if (!q) return hide();
    try {
      const res = await fetch(`/api/music/suggest?kind=${encodeURIComponent(kind)}&q=${encodeURIComponent(q)}`);
      const data = await res.json();
      const items = (data.results || []).map(x => ({
        value: x.value || x.name || x.title || "",
        label: x.label || x.name || x.value || "",
        sub: x.sub || x.artist || label
      })).filter(x => x.value);
      renderSuggestions(box, items, label, (value) => {
        addMusicItem(key, value);
        input.value = "";
        hide();
        input.focus();
      }, `후보가 없어도 ${label} 이름을 직접 입력 후 추가할 수 있습니다.`);
    } catch (_) {
      renderSuggestions(box, [], label, () => {}, `${label} 자동완성 연결에 실패했습니다. 직접 입력 후 추가할 수 있습니다.`);
    }
  }, 260);
  input.addEventListener("input", load);
  input.addEventListener("focus", load);
  input.addEventListener("blur", () => setTimeout(hide, 120));
}

function setupMusicAutocomplete() {
  bindLocalMusicAutocomplete("musicGenreInput", "musicGenreSuggest", () => genreOptions, "genres", "장르");
  bindRemoteMusicAutocomplete("artistInput", "artistSuggest", "artist", "artists", "아티스트");
  bindRemoteMusicAutocomplete("trackInput", "trackSuggest", "track", "tracks", "노래");
  bindRemoteMusicAutocomplete("albumInput", "albumSuggest", "album", "albums", "앨범");
}

function addMusicItem(key, value) {
  musicOffset = 0;
  const v = normalize(value);
  if (!v) return;
  if (!musicState[key].some(x => x.toLowerCase() === v.toLowerCase())) {
    musicState[key].push(v);
  }
  persistMusicTaste();
  renderMusicChips();
  renderMusicGenreButtons();
}

function removeMusicItem(key, value) {
  musicOffset = 0;
  musicState[key] = musicState[key].filter(x => x !== value);
  persistMusicTaste();
  renderMusicChips();
  renderMusicGenreButtons();
}

function renderMusicChips() {
  Object.entries(musicChipMap).forEach(([key, id]) => {
    const box = $(id);
    const items = musicState[key] || [];
    box.innerHTML = items.length
      ? items.map(v => `
          <button class="chip" type="button" data-key="${key}" data-value="${escapeHtml(v)}">
            ${escapeHtml(v)} <span>×</span>
          </button>
        `).join("")
      : `<span class="empty-chip">아직 선택 없음</span>`;
  });

  document.querySelectorAll(".chip").forEach(btn => {
    btn.addEventListener("click", () => removeMusicItem(btn.dataset.key, btn.dataset.value));
  });
}

function renderMusicGenreButtons() {
  const box = $("musicGenreButtons");
  box.innerHTML = genreOptions.map(g => {
    const active = musicState.genres.includes(g) ? "active" : "";
    return `<button class="genre-btn ${active}" type="button" data-genre="${escapeHtml(g)}">${escapeHtml(g)}</button>`;
  }).join("");

  document.querySelectorAll(".genre-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const value = btn.dataset.genre;
      if (musicState.genres.includes(value)) removeMusicItem("genres", value);
      else addMusicItem("genres", value);
    });
  });
}

function bindMusicAdd(inputId, buttonId, key) {
  const input = $(inputId);
  const add = () => {
    addMusicItem(key, input.value);
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

function renderMusicSummary() {
  const filled = [
    ["장르", musicState.genres],
    ["아티스트", musicState.artists],
    ["노래", musicState.tracks],
    ["앨범", musicState.albums]
  ].filter(([, values]) => values.length);

  const summary = $("musicSummary");
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

function reasonBlock(item) {
  const reasons = item.reason_items || [];
  if (!reasons.length) return "";
  return `
    <div class="reason-box">
      <div class="section-title">추천 이유</div>
      ${reasons.map(r => `
        <div class="reason-item">
          <span class="reason-icon">♪</span>
          <div>
            <b>${escapeHtml(r.title || "추천 근거")}</b>
            <p>${escapeHtml(r.detail || "음악 취향을 바탕으로 추천했습니다.")}</p>
          </div>
        </div>
      `).join("")}
    </div>`;
}

function fallbackCoverSvg(title, artist) {
  const safeTitle = escapeHtml(title || "Music");
  const safeArtist = escapeHtml(artist || "TasteLab");
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 600">
      <defs>
        <radialGradient id="g1" cx="25%" cy="18%" r="70%">
          <stop offset="0%" stop-color="#5eead4" stop-opacity="0.88"/>
          <stop offset="48%" stop-color="#7c3aed" stop-opacity="0.64"/>
          <stop offset="100%" stop-color="#020617" stop-opacity="1"/>
        </radialGradient>
        <linearGradient id="g2" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0%" stop-color="#0f172a"/>
          <stop offset="55%" stop-color="#312e81"/>
          <stop offset="100%" stop-color="#be185d"/>
        </linearGradient>
      </defs>
      <rect width="600" height="600" fill="url(#g2)"/>
      <circle cx="165" cy="135" r="210" fill="url(#g1)" opacity="0.9"/>
      <circle cx="420" cy="390" r="150" fill="#f0abfc" opacity="0.18"/>
      <path d="M196 357c0-42 36-76 80-76s80 34 80 76-36 76-80 76-80-34-80-76Z" fill="none" stroke="rgba(255,255,255,0.72)" stroke-width="24"/>
      <path d="M276 166v192" stroke="rgba(255,255,255,0.72)" stroke-width="24" stroke-linecap="round"/>
      <text x="42" y="505" fill="white" font-size="34" font-family="Arial, sans-serif" font-weight="800">${safeTitle.slice(0, 26)}</text>
      <text x="42" y="548" fill="rgba(255,255,255,0.78)" font-size="22" font-family="Arial, sans-serif">${safeArtist.slice(0, 32)}</text>
    </svg>`;
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
}

function musicResultCard(item, index) {
  const confidence = Math.max(1, Math.min(100, Math.round((item.match_score || 0) * 100)));
  const realCoverUrl = item.image_url || item.album_image_url || "";
  const coverUrl = realCoverUrl || fallbackCoverSvg(item.name, item.artist);
  const hasCover = Boolean(realCoverUrl);
  const image = `<img src="${escapeHtml(coverUrl)}" alt="${escapeHtml(item.album_name || item.name || "앨범 커버")}" loading="lazy" onerror="this.src='${fallbackCoverSvg("Music", "TasteLab")}';this.parentElement.classList.remove('has-cover');this.parentElement.classList.add('fallback-cover')" />`;
  const album = item.album_name
    ? `<p class="album-name">앨범 · ${escapeHtml(item.album_name)}</p>`
    : "";
  const sources = (item.sources || []).map(s => `<span class="source-pill">${escapeHtml(s)}</span>`).join("");
  const link = item.lastfm_url
    ? `<a class="music-open-link" href="${escapeHtml(item.lastfm_url)}" target="_blank" rel="noreferrer">LastFM에서 보기 →</a>`
    : "";
  const feedbackKey = musicTrackKey(item.name || "", item.artist || "");

  return `
    <article class="music-result-card" data-track-key="${escapeHtml(feedbackKey)}" data-name="${escapeHtml(item.name || "")}" data-artist="${escapeHtml(item.artist || "")}" data-album="${escapeHtml(item.album_name || "")}">
      <div class="music-art ${hasCover ? "has-cover" : "fallback-cover"}" data-cover-loaded="${hasCover ? "1" : "0"}">${image}</div>
      <span class="rank">#${index + 1}</span>
      <h3>${escapeHtml(item.name || "제목 없음")}</h3>
      <p class="artist">${escapeHtml(item.artist || "아티스트 정보 없음")}</p>
      ${album}
      ${sources ? `<div class="source-list">${sources}</div>` : ""}
      <div class="match-meter">
        <span>취향 적합도</span>
        <div><i style="width:${confidence}%"></i></div>
        <b>${confidence}%</b>
      </div>
      ${reasonBlock(item)}
      <div class="feedback-actions music-feedback-actions" data-track-key="${escapeHtml(feedbackKey)}" data-name="${escapeHtml(item.name || "")}" data-artist="${escapeHtml(item.artist || "")}">
        <button class="feedback-btn liked" type="button" data-feedback="liked">들었어요 · 좋았음</button>
        <button class="feedback-btn disliked" type="button" data-feedback="disliked">들었어요 · 별로</button>
        <button class="feedback-btn muted" type="button" data-feedback="not_interested">관심 없음</button>
      </div>
      ${link}
    </article>`;
}

async function enrichMusicCovers() {
  const cards = [...document.querySelectorAll(".music-result-card")].filter(card => {
    const art = card.querySelector(".music-art");
    return art && art.dataset.coverLoaded !== "1";
  });
  for (const card of cards.slice(0, 12)) {
    const art = card.querySelector(".music-art");
    const img = art?.querySelector("img");
    if (!art || !img) continue;
    try {
      const res = await fetch("/api/music/cover", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: card.dataset.name || "",
          artist: card.dataset.artist || "",
          album_name: card.dataset.album || ""
        })
      });
      if (!res.ok) continue;
      const data = await res.json();
      if (data.image_url) {
        img.src = data.image_url;
        art.dataset.coverLoaded = "1";
        art.classList.remove("fallback-cover", "no-cover");
        art.classList.add("has-cover");
      }
      if (data.album_name && !card.querySelector(".album-name")) {
        const artistLine = card.querySelector(".artist");
        artistLine?.insertAdjacentHTML("afterend", `<p class="album-name">앨범 · ${escapeHtml(data.album_name)}</p>`);
      }
    } catch (_) {
      /* 커버는 보조 정보라 실패해도 추천 결과는 유지합니다. */
    }
  }
}

function markMusicFeedback(trackKey, name, artist, status) {
  if (!trackKey || trackKey === "::") return;
  const feedback = getMusicFeedback();
  feedback[trackKey] = {
    status,
    name,
    artist,
    updated_at: new Date().toISOString()
  };
  saveJson(profileKey("musicFeedback"), feedback);

  if (status === "liked" && name) {
    addMusicItem("tracks", name);
  }
}

function syncMusicFeedbackButtonStates() {
  const feedback = getMusicFeedback();
  document.querySelectorAll(".music-feedback-actions").forEach(group => {
    const item = feedback[group.dataset.trackKey || ""];
    group.querySelectorAll(".feedback-btn").forEach(btn => {
      const active = item && item.status === btn.dataset.feedback;
      btn.classList.toggle("active", Boolean(active));
    });
  });
}

function bindMusicFeedbackButtons() {
  document.querySelectorAll(".music-feedback-actions .feedback-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const group = btn.closest(".music-feedback-actions");
      const trackKey = group?.dataset.trackKey || "";
      const name = group?.dataset.name || "";
      const artist = group?.dataset.artist || "";
      const status = btn.dataset.feedback;
      markMusicFeedback(trackKey, name, artist, status);
      syncMusicFeedbackButtonStates();
      const label = status === "liked"
        ? "좋아했던 노래로 저장했어요. 다음 추천에서 유사한 노래를 살짝 참고합니다."
        : "다음 추천에서 이 노래는 제외하도록 저장했어요.";
      if ($("musicStatus")) $("musicStatus").textContent = label;
    });
  });
  syncMusicFeedbackButtonStates();
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

async function loadMusicOptions() {
  const res = await fetch("/api/music/options");
  if (!res.ok) throw new Error("음악 장르 목록을 불러오지 못했습니다.");
  const data = await res.json();
  genreOptions = data.genres || [];
  $("musicGenreList").innerHTML = genreOptions.map(g => `<option value="${escapeHtml(g)}"></option>`).join("");
  startWithEmptyMusicTaste();
  renderMusicGenreButtons();
  renderMusicChips();
  renderMusicSummary();
  setupMusicAutocomplete();
}

async function recommendMusic(nextPage = false) {
  const status = $("musicStatus");
  const results = $("musicResults");
  renderMusicSummary();
  status.textContent = "음악 추천 결과를 불러오는 중입니다.";
  results.innerHTML = "";

  const topN = Number($("musicTopN").value || 12);
  if (nextPage) musicOffset += topN;
  else musicOffset = 0;

  const body = {
    genres: musicState.genres,
    artists: musicState.artists,
    tracks: mergeUnique([...musicState.tracks, ...likedMusicTracksFromFeedback(2)]),
    albums: musicState.albums,
    top_n: topN,
    offset: musicOffset,
    exclude_track_keys: excludedMusicTrackKeysFromFeedback()
  };

  const hasAnyInput = body.genres.length || body.artists.length || body.tracks.length || body.albums.length;
  if (!hasAnyInput) {
    status.textContent = "장르, 아티스트, 노래, 앨범 중 딱 하나만 입력해도 추천받을 수 있습니다.";
    return;
  }

  const res = await fetch("/api/music/recommend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "음악 추천 중 오류가 발생했습니다.");

  if (data.api_key_missing) {
    status.textContent =
      "LASTFM_API_KEY가 인식되지 않습니다. TasteLab.exe와 같은 폴더의 .env 파일을 확인하고, 저장 후 앱을 완전히 종료했다가 다시 실행해 주세요.";
    return;
  }

  const tracks = data.results || [];
  status.textContent = nextPage
    ? `다른 음악 추천 ${tracks.length}개를 불러왔습니다.`
    : (data.message || `${tracks.length}개의 음악 추천 결과를 찾았습니다.`);
  if (!tracks.length) return;
  results.innerHTML = tracks.map(musicResultCard).join("");
  bindMusicFeedbackButtons();
  enrichMusicCovers();
}

function clearMusicTaste() {
  musicState.genres = [];
  musicState.artists = [];
  musicState.tracks = [];
  musicState.albums = [];
  musicOffset = 0;
  ["musicGenreInput", "artistInput", "trackInput", "albumInput"].forEach(id => $(id).value = "");
  persistMusicTaste();
  renderMusicChips();
  renderMusicGenreButtons();
  renderMusicSummary();
  $("musicResults").innerHTML = "";
  $("musicStatus").textContent = "음악 취향을 입력하고 추천받기를 눌러주세요.";
}


function applyMusicStateFromAssistant(nextState = {}) {
  ["genres", "artists", "tracks", "albums"].forEach(key => {
    if (Array.isArray(nextState[key])) {
      musicState[key] = mergeUnique([...musicState[key], ...nextState[key]]);
    }
  });
  persistMusicTaste();
  renderMusicChips();
  renderMusicGenreButtons();
  renderMusicSummary();
}

function renderAssistantMusicResults(tracks, message = "AI 추천 결과를 불러왔습니다.") {
  const status = $("musicStatus");
  const results = $("musicResults");
  if (!tracks || !tracks.length) {
    if (status) status.textContent = message || "추천 결과가 없습니다.";
    return;
  }
  if (status) status.textContent = message;
  if (results) results.innerHTML = tracks.map(musicResultCard).join("");
  bindMusicFeedbackButtons();
  enrichMusicCovers();
}

window.TasteLabMusic = {
  getState: () => ({
    genres: [...musicState.genres],
    artists: [...musicState.artists],
    tracks: mergeUnique([...musicState.tracks, ...likedMusicTracksFromFeedback(2)]),
    albums: [...musicState.albums]
  }),
  getExcludedTrackKeys: excludedMusicTrackKeysFromFeedback,
  applyState: applyMusicStateFromAssistant,
  renderAssistantResults: renderAssistantMusicResults,
};

window.addEventListener("tastelab:profilechange", () => {
  startWithEmptyMusicTaste();
  renderMusicChips();
  renderMusicGenreButtons();
  renderMusicSummary();
  $("musicResults").innerHTML = "";
  $("musicStatus").textContent = "프로필이 변경되었습니다. 이 프로필의 취향으로 새롭게 추천받을 수 있습니다.";
});

bindMusicAdd("musicGenreInput", "addMusicGenreBtn", "genres");
bindMusicAdd("artistInput", "addArtistBtn", "artists");
bindMusicAdd("trackInput", "addTrackBtn", "tracks");
bindMusicAdd("albumInput", "addAlbumBtn", "albums");

$("musicRecommendBtn").addEventListener("click", () => recommendMusic(false).catch(e => $("musicStatus").textContent = e.message));
$("musicRetryBtn").addEventListener("click", () => recommendMusic(true).catch(e => $("musicStatus").textContent = e.message));
$("musicClearBtn").addEventListener("click", clearMusicTaste);

async function checkMusicEnv() {
  try {
    const res = await fetch("/api/music/env-status");
    const data = await res.json();
    const status = $("musicStatus");
    if (!data.lastfm_configured && status) {
      status.textContent = data.hint || "LASTFM_API_KEY를 .env에 설정한 뒤 앱을 다시 실행해 주세요.";
    }
  } catch (_) {
    /* ignore */
  }
}

bindContainedTableScroll();
loadMusicOptions()
  .catch(e => { $("musicStatus").textContent = e.message; })
  .finally(() => checkMusicEnv());
