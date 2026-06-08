const $ = (id) => document.getElementById(id);

const SESSION_KEY = "tastelab_chat_session";
const API_CHAT = "/api/chatbot/chat";

let isSending = false;

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

function getSessionId() {
  let id = sessionStorage.getItem(SESSION_KEY);
  if (!id) {
    id = typeof crypto !== "undefined" && crypto.randomUUID
      ? crypto.randomUUID()
      : `sess-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    sessionStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

function shortSessionId(id) {
  if (!id) return "";
  return id.length > 10 ? `${id.slice(0, 8)}…` : id;
}

function formatBotText(text) {
  const escaped = escapeHtml(text || "");
  return escaped
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

function reasonList(movie) {
  const items = movie.reason_items || [];
  if (items.length) {
    return `
      <div class="reason-box">
        <div class="section-title">추천 이유</div>
        ${items.map((item) => `
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

function musicCards(tracks) {
  if (!tracks || !tracks.length) return "";
  return tracks.slice(0, 4).map((t) => {
    const cover = t.image_url || t.album_image_url || "";
    const image = cover
      ? `<img src="${escapeHtml(cover)}" alt="${escapeHtml(t.name || "음악")}" loading="lazy" onerror="this.outerHTML='<div class=&quot;music-placeholder&quot;>♪</div>'" />`
      : `<div class="music-placeholder">♪</div>`;
    const label = `${safeText(t.name, "제목 없음")}${t.artist ? ` - ${t.artist}` : ""}`;
    const content = `${image}<div><strong>${escapeHtml(label)}</strong></div>`;
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

function setTrailerSlotMessage(card, html) {
  const slot = card.querySelector(".trailer-slot");
  if (!slot) return;
  slot.classList.remove("trailer-slot--pending");
  slot.removeAttribute("aria-hidden");
  slot.innerHTML = html;
}

function movieCard(movie, index) {
  const poster = movie.poster_url
    ? `<img class="poster" src="${escapeHtml(movie.poster_url)}" alt="${escapeHtml(safeText(movie.title, "영화"))} 포스터" loading="lazy" onerror="this.outerHTML='<div class=&quot;no-poster&quot;>포스터 없음</div>'" />`
    : `<div class="no-poster">포스터 없음</div>`;

  const year = movie.release_date ? String(movie.release_date).slice(0, 4) : "";
  const score = movie.tmdb_score ? `TMDB ${Number(movie.tmdb_score).toFixed(1)}` : "";
  const imdb = movie.imdb_score ? `IMDb ${movie.imdb_score}` : "";
  const meta = [year, score, imdb].filter(Boolean).join(" · ");
  const genres = (movie.genres || []).slice(0, 5).map((g) => `<span class="tag">${escapeHtml(g)}</span>`).join("");
  const directors = (movie.directors || []).slice(0, 2).join(", ");
  const actors = (movie.actors || []).slice(0, 4).join(", ");
  const confidence = Math.max(1, Math.min(100, Math.round((movie.match_score || 0) * 100)));
  const trailerInner = movie.trailer_url ? trailerButtonHtml(movie.trailer_url) : trailerLoadingHtml();

  const ost = musicCards(movie.soundtracks || []);
  const genreMusic = musicCards(movie.music_by_genre || []);
  const musicSection = ost || genreMusic
    ? `<details class="music-details">
        <summary>음악추천 보기</summary>
        ${ost ? `<div class="section-title small">OST</div><div class="music-grid">${ost}</div>` : ""}
        ${genreMusic ? `<div class="section-title small">장르 음악</div><div class="music-grid">${genreMusic}</div>` : ""}
      </details>`
    : "";

  return `
    <article class="card chat-movie-card" data-tmdb-id="${escapeHtml(movie.tmdb_id ?? "")}">
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
        ${musicSection}
      </div>
    </article>`;
}

function renderMoviesGrid(movies) {
  if (!movies || !movies.length) return "";
  return `
    <div class="chat-movies-block">
      <div class="chat-movies-label">추천 영화 ${movies.length}편</div>
      <div class="movie-grid chat-movie-grid">
        ${movies.map((m, i) => movieCard(m, i)).join("")}
      </div>
    </div>`;
}

function scrollChatToBottom() {
  const box = $("chatMessages");
  if (!box) return;
  requestAnimationFrame(() => {
    box.scrollTop = box.scrollHeight;
  });
}

function appendChatRow(role, innerHtml) {
  const box = $("chatMessages");
  const row = document.createElement("div");
  row.className = `chat-row ${role}`;
  if (role === "bot") {
    row.innerHTML = `
      <div class="chat-avatar" aria-hidden="true">AI</div>
      <div class="chat-bubble bot">${innerHtml}</div>`;
  } else {
    row.innerHTML = `
      <div class="chat-bubble user">${innerHtml}</div>
      <div class="chat-avatar user-avatar" aria-hidden="true">나</div>`;
  }
  box.appendChild(row);
  scrollChatToBottom();
  return row;
}

function appendUserMessage(text) {
  return appendChatRow("user", `<p>${escapeHtml(text)}</p>`);
}

function appendBotMessage(response, movies) {
  const textHtml = `<div class="chat-text">${formatBotText(response)}</div>`;
  const moviesHtml = renderMoviesGrid(movies);
  const row = appendChatRow("bot", `${textHtml}${moviesHtml}`);
  if (movies && movies.length) {
    enrichTrailers(row, movies);
  }
  return row;
}

function appendErrorMessage(message) {
  return appendChatRow("bot", `<p class="chat-error">${escapeHtml(message)}</p>`);
}

function setTyping(visible) {
  const el = $("chatTyping");
  if (!el) return;
  el.classList.toggle("hidden", !visible);
  el.setAttribute("aria-hidden", visible ? "false" : "true");
  if (visible) scrollChatToBottom();
}

function setSending(sending) {
  isSending = sending;
  const input = $("chatInput");
  const btn = $("sendBtn");
  if (input) input.disabled = sending;
  if (btn) {
    btn.disabled = sending;
    btn.classList.toggle("is-loading", sending);
  }
  setTyping(sending);
}

async function enrichTrailers(row, movies) {
  const cards = [...row.querySelectorAll(".card[data-tmdb-id]")];
  await Promise.all(cards.map(async (card, index) => {
    const movie = movies[index];
    if (!movie) return;
    if (movie.trailer_url) {
      renderTrailerSlot(card, movie.trailer_url);
      return;
    }
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
      if (!res.ok) throw new Error(data.detail || "failed");
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

function renderTrailerSlot(card, url) {
  const slot = card.querySelector(".trailer-slot");
  if (!slot || !url) return;
  slot.classList.remove("trailer-slot--pending");
  slot.removeAttribute("aria-hidden");
  slot.innerHTML = trailerButtonHtml(url);
}

async function sendChatMessage(message) {
  const text = String(message || "").trim();
  if (!text || isSending) return;

  appendUserMessage(text);
  setSending(true);

  try {
    const res = await fetch(API_CHAT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: getSessionId(),
        message: text
      })
    });

    if (!res.ok) {
      let detail = `서버 오류 (${res.status})`;
      try {
        const err = await res.json();
        detail = err.detail || err.message || detail;
        if (Array.isArray(detail)) detail = detail.map((d) => d.msg || d).join(", ");
      } catch (_) {
        /* ignore */
      }
      appendErrorMessage(`요청에 실패했습니다. ${detail}`);
      return;
    }

    const data = await res.json();
    appendBotMessage(data.response || "응답이 비어 있습니다.", data.movies || []);
  } catch (err) {
    appendErrorMessage(`네트워크 오류가 발생했습니다. 서버가 실행 중인지 확인해 주세요. (${err.message || err})`);
  } finally {
    setSending(false);
  }
}

function resetChatUi() {
  const box = $("chatMessages");
  box.innerHTML = `
    <div class="chat-row bot">
      <div class="chat-avatar" aria-hidden="true">AI</div>
      <div class="chat-bubble bot">
        <p>대화와 취향 기록을 초기화했습니다. 다시 장르·영화·감독·배우를 말씀해 주세요!</p>
      </div>
    </div>`;
  scrollChatToBottom();
}

function updateSessionBadge() {
  const badge = $("sessionBadge");
  if (!badge) return;
  const id = getSessionId();
  badge.textContent = `세션 ${shortSessionId(id)}`;
  badge.title = id;
}

function autosizeInput() {
  const input = $("chatInput");
  if (!input) return;
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
}

function bindEvents() {
  const form = $("chatForm");
  const input = $("chatInput");

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const value = input.value.trim();
    if (!value) return;
    input.value = "";
    autosizeInput();
    sendChatMessage(value);
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  input.addEventListener("input", autosizeInput);

  $("resetChatBtn").addEventListener("click", async () => {
    if (isSending) return;
    setSending(true);
    try {
      await sendChatMessage("초기화");
    } finally {
      resetChatUi();
      setSending(false);
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  updateSessionBadge();
  bindEvents();
  autosizeInput();
  $("chatInput").focus();
});
