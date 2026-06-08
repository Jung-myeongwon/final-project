(() => {
  const PROFILE_KEY = "tastelab_active_profile";
  const PROFILE_LABEL_KEY = "tastelab_profile_labels";
  const PROFILE_IDS = ["profile1", "profile2", "profile3"];

  const $ = (id) => document.getElementById(id);
  const page = document.body.dataset.page || ($("musicResults") ? "music" : "movies");

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function loadJson(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (_) {
      return fallback;
    }
  }

  function activeProfile() {
    const saved = localStorage.getItem(PROFILE_KEY);
    if (PROFILE_IDS.includes(saved)) return saved;
    localStorage.setItem(PROFILE_KEY, "profile1");
    return "profile1";
  }

  function profileNumber(id = activeProfile()) {
    const index = PROFILE_IDS.indexOf(id);
    return index >= 0 ? index + 1 : 1;
  }

  function defaultProfileLabels() {
    return { profile1: "프로필 1", profile2: "프로필 2", profile3: "프로필 3" };
  }

  function profileLabels() {
    return Object.assign(
      defaultProfileLabels(),
      loadJson(PROFILE_LABEL_KEY, {})
    );
  }

  function saveProfileLabel(profileId, label) {
    const labels = profileLabels();
    const cleaned = String(label || "").trim().slice(0, 18) || defaultProfileLabels()[profileId] || "프로필";
    labels[profileId] = cleaned;
    localStorage.setItem(PROFILE_LABEL_KEY, JSON.stringify(labels));
    return labels;
  }

  function sessionId(scope) {
    return `float-${scope}-${activeProfile()}`;
  }

  function formatBotText(text) {
    return escapeHtml(text || "")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\n/g, "<br>");
  }

  function ensureBrandCluster() {
    const nav = document.querySelector(".top-nav");
    const brand = nav?.querySelector(".brand");
    if (!nav || !brand) return null;

    let cluster = nav.querySelector(".brand-cluster");
    if (!cluster) {
      cluster = document.createElement("div");
      cluster.className = "brand-cluster";
      nav.insertBefore(cluster, brand);
      cluster.appendChild(brand);
    }
    return cluster;
  }

  function injectProfileSelector() {
    if ($("profileSwitcher")) return;
    const cluster = ensureBrandCluster();
    const parent = cluster || document.querySelector(".top-nav") || document.body;

    const wrap = document.createElement("div");
    wrap.id = "profileSwitcher";
    wrap.className = "profile-switcher";
    wrap.innerHTML = `
      <button id="profileToggle" class="profile-toggle" type="button" aria-label="추천 프로필 선택" aria-expanded="false">
        <span class="profile-icon">${profileNumber()}</span>
      </button>
      <div id="profileMenu" class="profile-menu hidden" role="menu" aria-label="추천 프로필">
        <div class="profile-menu-title">추천 프로필</div>
        ${PROFILE_IDS.map(id => `
          <div class="profile-menu-row" data-profile-row="${id}">
            <button class="profile-option ${activeProfile() === id ? "active" : ""}" type="button" data-profile="${id}" role="menuitem">
              <span>${profileNumber(id)}</span>
              <b>${escapeHtml(profileLabels()[id])}</b>
            </button>
            <button class="profile-rename-btn" type="button" data-rename-profile="${id}" aria-label="프로필 이름 변경">✎</button>
          </div>
        `).join("")}
        <div id="profileRenameEditor" class="profile-rename-editor hidden">
          <label for="profileRenameInput">프로필 이름</label>
          <input id="profileRenameInput" maxlength="18" autocomplete="off" placeholder="예: 데이트용, 혼자 볼 때" />
          <div class="profile-rename-actions">
            <button id="profileRenameSave" class="tiny-btn" type="button">저장</button>
            <button id="profileRenameCancel" class="profile-cancel-btn" type="button">취소</button>
          </div>
        </div>
      </div>
    `;
    parent.appendChild(wrap);

    const toggle = $("profileToggle");
    const menu = $("profileMenu");
    const editor = $("profileRenameEditor");
    const renameInput = $("profileRenameInput");
    let editingProfile = null;

    function closeEditor() {
      editingProfile = null;
      editor.classList.add("hidden");
      renameInput.value = "";
    }

    function closeMenu() {
      menu.classList.add("hidden");
      toggle.setAttribute("aria-expanded", "false");
      closeEditor();
    }

    function refreshProfileUi() {
      const current = activeProfile();
      const labels = profileLabels();
      const icon = wrap.querySelector(".profile-icon");
      if (icon) icon.textContent = profileNumber(current);
      toggle.title = labels[current] || defaultProfileLabels()[current];
      wrap.querySelectorAll(".profile-option").forEach(btn => {
        const profileId = btn.dataset.profile;
        btn.classList.toggle("active", profileId === current);
        const label = btn.querySelector("b");
        if (label) label.textContent = labels[profileId] || defaultProfileLabels()[profileId];
      });
    }

    toggle.addEventListener("click", (event) => {
      event.stopPropagation();
      const willOpen = menu.classList.contains("hidden");
      menu.classList.toggle("hidden", !willOpen);
      toggle.setAttribute("aria-expanded", String(willOpen));
      if (!willOpen) closeEditor();
    });

    wrap.querySelectorAll(".profile-option").forEach(btn => {
      btn.addEventListener("click", () => {
        const selected = btn.dataset.profile;
        if (!PROFILE_IDS.includes(selected)) return;
        localStorage.setItem(PROFILE_KEY, selected);
        refreshProfileUi();
        closeMenu();
        window.dispatchEvent(new CustomEvent("tastelab:profilechange", { detail: { profile: selected } }));
        appendBotMessage(`${profileLabels()[selected]}로 바꿨어요. 이 프로필은 취향과 피드백을 따로 저장합니다.`);
      });
    });

    wrap.querySelectorAll(".profile-rename-btn").forEach(btn => {
      btn.addEventListener("click", (event) => {
        event.stopPropagation();
        editingProfile = btn.dataset.renameProfile;
        const labels = profileLabels();
        renameInput.value = labels[editingProfile] || defaultProfileLabels()[editingProfile] || "";
        editor.classList.remove("hidden");
        setTimeout(() => renameInput.focus(), 30);
      });
    });

    $("profileRenameSave").addEventListener("click", () => {
      if (!editingProfile) return;
      const labels = saveProfileLabel(editingProfile, renameInput.value);
      refreshProfileUi();
      appendBotMessage(`${labels[editingProfile]} 이름으로 저장했어요.`);
      closeEditor();
    });

    $("profileRenameCancel").addEventListener("click", closeEditor);
    renameInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        $("profileRenameSave").click();
      }
      if (event.key === "Escape") closeEditor();
    });

    document.addEventListener("click", (event) => {
      if (!wrap.contains(event.target)) closeMenu();
    });

    refreshProfileUi();
  }

  function injectChatWidget() {
    if ($("floatingAiWidget")) return;
    const wrap = document.createElement("div");
    wrap.id = "floatingAiWidget";
    wrap.className = "floating-ai-widget";
    wrap.innerHTML = `
      <section id="floatingAiPanel" class="floating-ai-panel glass hidden" aria-label="AI 추천 챗봇">
        <div class="panel-head floating-ai-head">
          <div>
            <span class="mini-label">TasteLab AI</span>
            <h2>${page === "music" ? "음악 추천 대화창" : "영화 추천 대화창"}</h2>
          </div>
          <button id="floatingAiClose" class="tiny-btn" type="button">닫기</button>
        </div>
        <table class="taste-table floating-ai-table">
          <tbody>
            <tr>
              <th>AI 대화</th>
              <td>
                <div id="floatingAiMessages" class="floating-ai-messages" role="log" aria-live="polite">
                  <div class="floating-ai-row bot">
                    <div class="floating-ai-bubble bot">
                      ${page === "music"
                        ? "좋아하는 장르·아티스트·노래를 문장으로 말해 주세요. 추천 결과는 음악 추천 탭에 바로 띄울게요."
                        : "좋아하는 장르·영화·감독·배우를 문장으로 말해 주세요. 추천 결과는 영화 추천 탭에 바로 띄울게요."}
                    </div>
                  </div>
                </div>
              </td>
            </tr>
            <tr>
              <th>질문 입력</th>
              <td>
                <form id="floatingAiForm" class="floating-ai-form" autocomplete="off">
                  <textarea id="floatingAiInput" rows="1" maxlength="2000" placeholder="예: ${page === "music" ? "아이유 느낌의 발라드 추천해줘" : "SF랑 스릴러 섞인 영화 추천해줘"}" required></textarea>
                  <button id="floatingAiSend" class="main-btn" type="submit">전송</button>
                </form>
                <p class="floating-ai-hint">Enter로 전송 · Shift+Enter로 줄바꿈</p>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
      <button id="floatingAiButton" class="floating-ai-button" type="button" aria-label="AI 챗봇 열기" aria-expanded="false">
        <span class="floating-ai-button-mark">AI</span>
      </button>
    `;
    document.body.appendChild(wrap);

    $("floatingAiButton").addEventListener("click", () => togglePanel($("floatingAiPanel").classList.contains("hidden")));
    $("floatingAiClose").addEventListener("click", () => togglePanel(false));
    $("floatingAiForm").addEventListener("submit", (event) => {
      event.preventDefault();
      const input = $("floatingAiInput");
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      autosize(input);
      sendToAssistant(text);
    });
    $("floatingAiInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        $("floatingAiForm").requestSubmit();
      }
    });
    $("floatingAiInput").addEventListener("input", (event) => autosize(event.target));
  }

  function togglePanel(open) {
    const panel = $("floatingAiPanel");
    const button = $("floatingAiButton");
    panel.classList.toggle("hidden", !open);
    button.classList.toggle("is-open", open);
    button.setAttribute("aria-expanded", String(open));
    if (open) setTimeout(() => $("floatingAiInput")?.focus(), 50);
  }

  function autosize(input) {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
  }

  function scrollMessages() {
    const box = $("floatingAiMessages");
    if (!box) return;
    requestAnimationFrame(() => {
      box.scrollTop = box.scrollHeight;
    });
  }

  function appendUserMessage(text) {
    const box = $("floatingAiMessages");
    if (!box) return;
    const row = document.createElement("div");
    row.className = "floating-ai-row user";
    row.innerHTML = `<div class="floating-ai-bubble user">${escapeHtml(text)}</div>`;
    box.appendChild(row);
    scrollMessages();
  }

  function appendBotMessage(text) {
    const box = $("floatingAiMessages");
    if (!box) return;
    const row = document.createElement("div");
    row.className = "floating-ai-row bot";
    row.innerHTML = `<div class="floating-ai-bubble bot">${formatBotText(text)}</div>`;
    box.appendChild(row);
    scrollMessages();
  }

  function setBusy(busy) {
    const input = $("floatingAiInput");
    const send = $("floatingAiSend");
    if (input) input.disabled = busy;
    if (send) {
      send.disabled = busy;
      send.textContent = busy ? "분석 중" : "전송";
    }
  }

  async function sendToAssistant(text) {
    appendUserMessage(text);
    setBusy(true);
    try {
      if (page === "music") {
        await sendMusic(text);
      } else {
        await sendMovie(text);
      }
    } catch (err) {
      appendBotMessage(`요청 중 오류가 발생했어요. 서버 실행 상태를 확인해 주세요. (${err.message || err})`);
    } finally {
      setBusy(false);
    }
  }

  async function sendMovie(text) {
    const movieApi = window.TasteLabMovies || {};
    const res = await fetch("/api/chatbot/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId("movie"),
        message: text,
        auto_recommend: true,
        profile_like_movies: movieApi.getLikedMovieTitles ? movieApi.getLikedMovieTitles() : [],
        exclude_tmdb_ids: movieApi.getExcludedMovieIds ? movieApi.getExcludedMovieIds() : []
      })
    });
    const data = await readResponse(res);
    if (movieApi.applyState && data.state) movieApi.applyState(data.state);
    appendBotMessage(data.response || "응답이 비어 있습니다.");
    if (data.movies && data.movies.length && movieApi.renderAssistantResults) {
      await movieApi.renderAssistantResults(data.movies, `AI가 ${data.movies.length}개의 영화 추천 결과를 띄웠습니다.`);
    }
  }

  async function sendMusic(text) {
    const musicApi = window.TasteLabMusic || {};
    const res = await fetch("/api/music/chatbot/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId("music"),
        message: text,
        auto_recommend: true,
        profile_taste: musicApi.getState ? musicApi.getState() : {},
        exclude_track_keys: musicApi.getExcludedTrackKeys ? musicApi.getExcludedTrackKeys() : []
      })
    });
    const data = await readResponse(res);
    if (musicApi.applyState && data.state) musicApi.applyState(data.state);
    appendBotMessage(data.response || "응답이 비어 있습니다.");
    const tracks = data.tracks || data.results || [];
    if (tracks.length && musicApi.renderAssistantResults) {
      musicApi.renderAssistantResults(tracks, `AI가 ${tracks.length}개의 음악 추천 결과를 띄웠습니다.`);
    }
  }

  async function readResponse(res) {
    let data = {};
    try {
      data = await res.json();
    } catch (_) {
      data = {};
    }
    if (!res.ok) {
      const detail = Array.isArray(data.detail)
        ? data.detail.map(x => x.msg || JSON.stringify(x)).join(", ")
        : (data.detail || data.message || `서버 오류 ${res.status}`);
      throw new Error(detail);
    }
    return data;
  }

  document.addEventListener("DOMContentLoaded", () => {
    injectProfileSelector();
    injectChatWidget();
  });
})();
