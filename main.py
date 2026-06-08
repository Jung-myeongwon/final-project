import asyncio
import re
from pathlib import Path
import sqlite3
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app_paths import app_base_dir, bundle_dir, ensure_data_files, ensure_env_file, get_lastfm_api_key, load_app_env, resolve_env_path
from movie_recommender_onefile import (
    MUSIC_GENRE_OPTIONS,
    MUSIC_QUERY_ALIASES,
    fetch_trailer_url,
    fetch_movie_external_details,
    lookup_music_cover,
    recommend_movies_and_music,
    recommend_music_by_taste,
    reset_recommendation_history,
    suggest_music_items,
)

BASE_DIR = app_base_dir()
RESOURCE_DIR = bundle_dir()
ensure_data_files()
ensure_env_file()
load_app_env()
DB_PATH = BASE_DIR / "data" / "movies.db"

app = FastAPI(title="TasteLab Movie & Music Recommender")
app.mount("/static", StaticFiles(directory=RESOURCE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=RESOURCE_DIR / "templates")


class RecommendRequest(BaseModel):
    genres: List[str] = Field(default_factory=list)
    directors: List[str] = Field(default_factory=list)
    actors: List[str] = Field(default_factory=list)
    like_movies: List[str] = Field(default_factory=list)
    min_score: float = 6.5
    top_n: int = 6
    music_limit: int = 3
    exclude_last: bool = False
    exclude_tmdb_ids: List[int] = Field(default_factory=list)


class MusicRecommendRequest(BaseModel):
    genres: List[str] = Field(default_factory=list)
    artists: List[str] = Field(default_factory=list)
    tracks: List[str] = Field(default_factory=list)
    albums: List[str] = Field(default_factory=list)
    top_n: int = 12
    offset: int = 0
    exclude_track_keys: List[str] = Field(default_factory=list)


class MovieExternalDetailsRequest(BaseModel):
    tmdb_id: int | None = None
    title: str = Field(default="", max_length=200)
    genres: List[str] = Field(default_factory=list)
    music_limit: int = 5


class MusicCoverRequest(BaseModel):
    name: str = Field(default="", max_length=200)
    artist: str = Field(default="", max_length=200)
    album_name: str = Field(default="", max_length=200)


def fetch_options():
    if not DB_PATH.exists():
        raise FileNotFoundError("data/movies.db 파일이 없습니다.")
    conn = sqlite3.connect(DB_PATH)
    try:
        genres = [r[0] for r in conn.execute("SELECT name FROM genres ORDER BY name").fetchall()]
        title_rows = conn.execute("SELECT title, original_title FROM movies ORDER BY title").fetchall()
        title_seen = set()
        titles = []
        for title, original_title in title_rows:
            for value in [title, original_title]:
                if value and value not in title_seen:
                    titles.append(value)
                    title_seen.add(value)
        directors = [r[0] for r in conn.execute("""
            SELECT DISTINCT p.name
            FROM people p
            JOIN movie_directors md ON p.id = md.person_id
            ORDER BY p.name
        """).fetchall()]
        actors = [r[0] for r in conn.execute("""
            SELECT DISTINCT p.name
            FROM people p
            JOIN movie_actors ma ON p.id = ma.person_id
            ORDER BY p.name
        """).fetchall()]
    finally:
        conn.close()
    return {"genres": genres, "directors": directors, "actors": actors, "titles": titles}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "page": "movies"})


@app.get("/music", response_class=HTMLResponse)
def music_page(request: Request):
    return templates.TemplateResponse("music.html", {"request": request, "page": "music"})


@app.get("/api/options")
def options():
    try:
        return fetch_options()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/music/env-status")
def music_env_status():
    load_app_env()
    env_path = resolve_env_path()
    key = get_lastfm_api_key()
    return {
        "lastfm_configured": bool(key),
        "env_exists": env_path is not None,
        "env_path": str(env_path) if env_path else str(BASE_DIR / ".env"),
        "hint": (
            "LASTFM_API_KEY가 설정되었습니다."
            if key
            else (
                f".env 파일을 확인하세요. 경로: {env_path or BASE_DIR / '.env'} "
                "(파일명이 .env.txt가 아닌지, 키 입력 후 앱을 완전히 종료했다가 다시 실행했는지 확인)"
            )
        ),
    }


@app.get("/api/music/options")
def music_options():
    # LastFM 태그로 바로 검색하기 좋은 값들입니다. 사용자가 직접 입력해도 됩니다.
    return {
        "genres": [
            "케이팝", "팝", "록", "인디", "힙합", "알앤비", "재즈", "일렉트로닉",
            "신스웨이브", "앰비언트", "클래식", "사운드트랙", "로파이", "발라드",
            "어쿠스틱", "포크", "소울", "댄스", "메탈", "시티팝"
        ]
    }


@app.get("/api/movie/{tmdb_id}/trailer")
def movie_trailer(tmdb_id: int):
    from app_paths import get_tmdb_api_key

    if not get_tmdb_api_key():
        return {
            "trailer_url": None,
            "api_key_missing": True,
            "message": "TMDB_API_KEY가 .env에 없습니다. TasteLab.exe와 같은 폴더의 .env를 확인하세요.",
        }
    try:
        return {
            "trailer_url": fetch_trailer_url(tmdb_id),
            "api_key_missing": False,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/movie/external-details")
def movie_external_details(req: MovieExternalDetailsRequest):
    try:
        return fetch_movie_external_details(
            title=req.title,
            genres=req.genres,
            tmdb_id=req.tmdb_id,
            music_limit=req.music_limit,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/recommend")
def recommend(req: RecommendRequest):
    try:
        results = recommend_movies_and_music(
            genres=req.genres,
            directors=req.directors,
            actors=req.actors,
            like_movies=req.like_movies,
            min_score=req.min_score,
            top_n=req.top_n,
            db_path=DB_PATH,
            music_limit=req.music_limit,
            exclude_last=req.exclude_last,
            exclude_tmdb_ids=req.exclude_tmdb_ids,
            include_external=False,
        )
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




@app.get("/api/music/suggest")
def music_suggest(
    kind: str = Query("artist", pattern="^(artist|track|album|genre)$"),
    q: str = Query("", max_length=80),
):
    try:
        return suggest_music_items(kind=kind, query=q, limit=12)
    except Exception as e:
        # 자동완성은 추천 기능의 보조 기능이므로 실패해도 화면 전체가 깨지지 않게 처리합니다.
        return {"results": [], "error": str(e)}

@app.post("/api/music/recommend")
def recommend_music(req: MusicRecommendRequest):
    try:
        return recommend_music_by_taste(
            genres=req.genres,
            artists=req.artists,
            tracks=req.tracks,
            albums=req.albums,
            top_n=req.top_n,
            offset=req.offset,
            exclude_track_keys=req.exclude_track_keys,
            fast=True,
            include_cover_art=False,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/music/cover")
def music_cover(req: MusicCoverRequest):
    try:
        return lookup_music_cover(req.name, req.artist, req.album_name)
    except Exception as e:
        return {"image_url": "", "album_name": req.album_name, "error": str(e)}


@app.post("/api/reset")
def reset():
    try:
        reset_recommendation_history(DB_PATH)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 플로팅 챗봇 / 챗봇 페이지용 비동기 대화 API
# ---------------------------------------------------------------------------

CHAT_SESSIONS: Dict[str, Dict[str, Any]] = {}

RECOMMEND_TRIGGERS = ("추천", "찾아", "보여줘", "권해", "골라", "대박", "알려줘", "뽑아")
RESET_TRIGGERS = ("초기화", "리셋", "reset")

# 한국어·약어 키워드 → DB 장르명 후보 (fetch_options 장르 목록과 교차 매칭)
GENRE_ALIAS_CANDIDATES = {
    "sf": ["Science Fiction", "Sci-Fi", "SF"],
    "sci-fi": ["Science Fiction", "Sci-Fi"],
    "science fiction": ["Science Fiction"],
    "스릴러": ["Thriller"],
    "스릴러물": ["Thriller"],
    "액션": ["Action"],
    "드라마": ["Drama"],
    "코미디": ["Comedy"],
    "로맨스": ["Romance"],
    "호러": ["Horror"],
    "공포": ["Horror"],
    "판타지": ["Fantasy"],
    "애니": ["Animation"],
    "애니메이션": ["Animation"],
    "범죄": ["Crime"],
    "미스터리": ["Mystery"],
    "전쟁": ["War"],
    "다큐": ["Documentary"],
}


class ChatMessageRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., min_length=1, max_length=2000)
    auto_recommend: bool = False
    profile_like_movies: List[str] = Field(default_factory=list)
    exclude_tmdb_ids: List[int] = Field(default_factory=list)


class ChatMessageResponse(BaseModel):
    response: str
    movies: List[Dict[str, Any]] = Field(default_factory=list)
    state: Dict[str, Any] = Field(default_factory=dict)


def _new_chat_session() -> Dict[str, Any]:
    return {
        "genres": [],
        "directors": [],
        "actors": [],
        "like_movies": [],
        "stage": "greeting",
        "turns": 0,
    }


def _taste_snapshot(state: Dict[str, Any]) -> Dict[str, List[str]]:
    return {
        "genres": list(state["genres"]),
        "directors": list(state["directors"]),
        "actors": list(state["actors"]),
        "like_movies": list(state["like_movies"]),
    }


def _diff_newly_noted(before: Dict[str, List[str]], state: Dict[str, Any]) -> List[str]:
    labels = {
        "genres": "장르",
        "like_movies": "영화",
        "directors": "감독",
        "actors": "배우",
    }
    noted: List[str] = []
    for key, label in labels.items():
        for item in state[key]:
            if item not in before[key]:
                noted.append(f"{label} {item}")
    return noted


def _detect_chat_intent(user_msg: str) -> str:
    if _is_reset_request(user_msg):
        return "reset"
    if re.search(r"(안녕|하이|hello|반가|헬로)", user_msg, re.I):
        return "greeting"
    if re.search(r"(고마|감사|thanks|thank\s*you)", user_msg, re.I):
        return "thanks"
    if re.search(r"(도움|help|사용법|어떻게\s*써|뭐라고\s*말)", user_msg, re.I):
        return "help"
    if re.search(r"(또|다른\s*거|다시|재추천|바꿔|다르게)", user_msg):
        return "retry_recommend"
    if _is_recommend_request(user_msg):
        return "recommend"
    return "chat"


def _compose_bot_reply(
    *,
    user_msg: str,
    state: Dict[str, Any],
    intent: str,
    newly_noted: List[str],
    movies: List[Dict[str, Any]] | None = None,
    auto_recommend: bool = False,
) -> str:
    summary = _build_taste_summary(state)
    snippet = user_msg if len(user_msg) <= 48 else f"{user_msg[:48]}…"

    if movies:
        intro = ""
        if newly_noted:
            intro = f"네, **{', '.join(newly_noted)}** 반영했어요. "
        elif intent == "retry_recommend":
            intro = "다른 분위기로 다시 골라봤어요. "
        elif intent == "recommend":
            intro = "요청하신 대로 "
        intro += "취향에 맞는 영화 3편을 추천해 드릴게요."
        if summary:
            intro += f"\n\n지금까지 파악한 취향 — {summary}"
        intro += "\n\n아래 카드에서 포스터와 줄거리를 확인해 보세요!"
        return intro

    if intent == "greeting":
        if state["turns"] <= 1:
            return (
                "안녕하세요! TasteLab 영화 추천 챗봇이에요. "
                "좋아하는 장르, 영화, 감독, 배우를 말씀해 주시면 대화하면서 맞춤 영화를 찾아 드립니다."
            )
        return (
            f"다시 만나서 반가워요! {summary + ' 기준으로 ' if summary else ''}"
            "원하시는 영화 취향을 말씀해 주시거나 **「추천해줘」**라고 해 주세요."
        )

    if intent == "thanks":
        return (
            "천만에요! 도움이 되었다니 기뻐요. "
            "다른 장르나 감독·배우 취향도 알려주시면 더 정교하게 추천해 드릴게요."
        )

    if intent == "help":
        return (
            "이렇게 말씀해 주시면 됩니다.\n"
            "· 장르 — 예: SF, 스릴러, 액션\n"
            "· 좋아하는 영화 — 예: 인터스텔라, 기생충\n"
            "· 감독·배우 — 예: 봉준호, 송강호\n\n"
            "취향을 알려주시면 기억해 두었다가 **「영화 추천해줘」**라고 하실 때 맞춤 3편을 보여 드려요."
        )

    if newly_noted:
        joined = ", ".join(newly_noted)
        if auto_recommend:
            return (
                f"**{joined}** 확인했어요! "
                f"{('지금까지 취향 — ' + summary + '. ') if summary else ''}"
                "조건에 맞는 영화를 찾지 못했어요. 다른 키워드로 다시 말씀해 주실래요?"
            )
        return (
            f"**{joined}** 기억했어요! "
            f"{('현재 취향 — ' + summary + '. ') if summary else ''}"
            "더 알려주시거나 **「추천해줘」**라고 하시면 바로 영화를 골라 드릴게요."
        )

    if intent in ("recommend", "retry_recommend"):
        return (
            "추천해 드리고 싶은데, 아직 취향 정보가 부족해요. "
            "장르(예: SF, 스릴러), 좋아하는 영화, 감독·배우 중 하나 이상을 알려주세요!"
        )

    if summary:
        if auto_recommend:
            return (
                f"말씀해 주신 「{snippet}」 잘 들었어요. "
                f"현재 취향은 {summary}입니다. "
                "이번 입력에서 새 키워드는 찾지 못했어요. 장르·영화·감독·배우를 조금 더 구체적으로 말씀해 주세요."
            )
        return (
            f"네, 「{snippet}」 확인했어요. "
            f"지금까지 취향은 {summary}입니다. "
            "추가로 알려주시거나 **「추천해줘」**라고 해 주시면 맞춤 영화를 보여 드릴게요."
        )

    if auto_recommend:
        return (
            f"「{snippet}」 보내주셨네요! "
            "영화 추천을 위해 장르(예: SF, 스릴러), 좋아하는 영화 제목, 감독·배우 이름을 알려주세요."
        )

    return (
        f"네, 「{snippet}」 잘 받았어요. "
        "영화 추천 챗봇이라 장르·좋아하는 영화·감독·배우를 말씀해 주시면 취향을 모아 추천해 드립니다. "
        "준비되면 **「추천해줘」**라고 해 주세요!"
    )


def _load_chat_options() -> Dict[str, List[str]]:
    try:
        options = fetch_options()
        return {
            "genres": options.get("genres", []),
            "titles": options.get("titles", []),
            "directors": options.get("directors", []),
            "actors": options.get("actors", []),
        }
    except Exception:
        return {"genres": [], "titles": [], "directors": [], "actors": []}


def _match_db_genre(candidates: List[str], db_genres: List[str]) -> str | None:
    lowered = {g.lower(): g for g in db_genres}
    for cand in candidates:
        key = cand.lower()
        if key in lowered:
            return lowered[key]
    for cand in candidates:
        key = cand.lower()
        for genre in db_genres:
            gl = genre.lower()
            if key in gl or gl in key:
                return genre
    return None


def _extract_genres(user_msg: str, db_genres: List[str], state: Dict[str, Any]) -> bool:
    extracted = False
    msg_lower = user_msg.lower()

    for genre in sorted(db_genres, key=len, reverse=True):
        if len(genre) < 2:
            continue
        if genre.lower() in msg_lower and genre not in state["genres"]:
            state["genres"].append(genre)
            extracted = True

    for alias, candidates in GENRE_ALIAS_CANDIDATES.items():
        if alias.lower() not in msg_lower:
            continue
        matched = _match_db_genre(candidates, db_genres)
        if matched and matched not in state["genres"]:
            state["genres"].append(matched)
            extracted = True

    return extracted


def _extract_entities(user_msg: str, options: Dict[str, List[str]], state: Dict[str, Any]) -> bool:
    extracted = _extract_genres(user_msg, options["genres"], state)
    msg_lower = user_msg.lower()

    for director in options["directors"]:
        if len(director) < 2:
            continue
        if director.lower() in msg_lower and director not in state["directors"]:
            state["directors"].append(director)
            extracted = True

    for actor in options["actors"]:
        if len(actor) < 2:
            continue
        if actor.lower() in msg_lower and actor not in state["actors"]:
            state["actors"].append(actor)
            extracted = True

    for title in sorted(options["titles"], key=len, reverse=True):
        if len(title) < 2:
            continue
        if title.lower() in msg_lower and title not in state["like_movies"]:
            state["like_movies"].append(title)
            extracted = True

    return extracted


def _taste_signal_count(state: Dict[str, Any]) -> int:
    return (
        len(state["genres"])
        + len(state["directors"])
        + len(state["actors"])
        + len(state["like_movies"])
    )


def _is_recommend_request(user_msg: str) -> bool:
    return any(word in user_msg for word in RECOMMEND_TRIGGERS)


def _is_reset_request(user_msg: str) -> bool:
    return any(word in user_msg.lower() for word in RESET_TRIGGERS)


def _build_taste_summary(state: Dict[str, Any]) -> str:
    parts = []
    if state["genres"]:
        parts.append(f"장르: {', '.join(state['genres'])}")
    if state["like_movies"]:
        parts.append(f"선호작: {', '.join(state['like_movies'])}")
    if state["directors"]:
        parts.append(f"감독: {', '.join(state['directors'])}")
    if state["actors"]:
        parts.append(f"배우: {', '.join(state['actors'])}")
    return " · ".join(parts) if parts else ""


async def _run_movie_recommendation(state: Dict[str, Any], exclude_tmdb_ids: List[int] | None = None) -> List[Dict[str, Any]]:
    return await asyncio.to_thread(
        recommend_movies_and_music,
        genres=state["genres"],
        directors=state["directors"],
        actors=state["actors"],
        like_movies=state["like_movies"],
        min_score=6.0,
        top_n=6,
        db_path=DB_PATH,
        music_limit=2,
        exclude_last=False,
        exclude_tmdb_ids=exclude_tmdb_ids or [],
        include_external=False,
    )




@app.get("/chatbot", response_class=HTMLResponse)
def chatbot_page(request: Request):
    return templates.TemplateResponse("chatbot.html", {"request": request})


@app.post("/api/chatbot/chat", response_model=ChatMessageResponse)
async def chatbot_chat(req: ChatMessageRequest) -> ChatMessageResponse:
    session_id = req.session_id.strip()
    user_msg = req.message.strip()

    if session_id not in CHAT_SESSIONS:
        CHAT_SESSIONS[session_id] = _new_chat_session()

    state = CHAT_SESSIONS[session_id]
    for title in req.profile_like_movies:
        title = str(title).strip()
        if title and title not in state["like_movies"]:
            state["like_movies"].append(title)
    state["turns"] = state.get("turns", 0) + 1
    intent = _detect_chat_intent(user_msg)

    if intent == "reset":
        CHAT_SESSIONS[session_id] = _new_chat_session()
        return ChatMessageResponse(
            response=(
                "네, 기억하던 취향을 모두 지웠어요. "
                "처음부터 다시 편하게 말씀해 주세요. 장르·영화·감독·배우 무엇이든 좋아요!"
            ),
            movies=[],
            state=CHAT_SESSIONS[session_id],
        )

    taste_before = _taste_snapshot(state)
    options = _load_chat_options()
    _extract_entities(user_msg, options, state)
    newly_noted = _diff_newly_noted(taste_before, state)
    extracted = bool(newly_noted)

    taste_ready = _taste_signal_count(state) >= 2
    should_recommend = intent not in ("greeting", "thanks", "help") and (
        intent in ("recommend", "retry_recommend")
        or (extracted and taste_ready)
        or (req.auto_recommend and extracted and _taste_signal_count(state) >= 1)
    )

    movies: List[Dict[str, Any]] = []
    if should_recommend and _taste_signal_count(state) >= 1:
        try:
            movies = await _run_movie_recommendation(state, req.exclude_tmdb_ids)
            if movies:
                state["stage"] = "recommended"
        except Exception as e:
            return ChatMessageResponse(
                response=(
                    f"죄송해요, 추천 중 문제가 생겼어요. ({e})\n"
                    "잠시 후 다시 말씀해 주시거나 다른 키워드로 시도해 주세요."
                ),
                movies=[],
                state=state,
            )

    response = _compose_bot_reply(
        user_msg=user_msg,
        state=state,
        intent=intent,
        newly_noted=newly_noted,
        movies=movies if movies else None,
        auto_recommend=req.auto_recommend,
    )
    return ChatMessageResponse(response=response, movies=movies, state=state)




def _merge_unique(target: List[str], values: List[str] | None) -> None:
    for value in values or []:
        value = str(value).strip()
        if value and not any(x.lower() == value.lower() for x in target):
            target.append(value)

# ---------------------------------------------------------------------------
# 음악 추천 플로팅 챗봇 API
# ---------------------------------------------------------------------------

MUSIC_CHAT_SESSIONS: Dict[str, Dict[str, Any]] = {}

MUSIC_RECOMMEND_TRIGGERS = (
    "추천", "찾아", "보여줘", "권해", "골라", "알려줘", "뽑아", "플리", "노래", "음악", "틀어",
)
MUSIC_RESET_TRIGGERS = ("초기화", "리셋", "reset")


class MusicChatMessageRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., min_length=1, max_length=2000)
    auto_recommend: bool = False
    profile_taste: Dict[str, List[str]] = Field(default_factory=dict)
    exclude_track_keys: List[str] = Field(default_factory=list)


class MusicChatMessageResponse(BaseModel):
    response: str
    tracks: List[Dict[str, Any]] = Field(default_factory=list)
    state: Dict[str, Any] = Field(default_factory=dict)


def _new_music_chat_session() -> Dict[str, Any]:
    return {
        "genres": [],
        "artists": [],
        "tracks": [],
        "albums": [],
        "stage": "greeting",
        "turns": 0,
        "offset": 0,
    }


def _music_taste_snapshot(state: Dict[str, Any]) -> Dict[str, List[str]]:
    return {
        "genres": list(state["genres"]),
        "artists": list(state["artists"]),
        "tracks": list(state["tracks"]),
        "albums": list(state["albums"]),
    }


def _diff_newly_noted_music(before: Dict[str, List[str]], state: Dict[str, Any]) -> List[str]:
    labels = {
        "genres": "장르",
        "artists": "아티스트",
        "tracks": "노래",
        "albums": "앨범",
    }
    noted: List[str] = []
    for key, label in labels.items():
        for item in state[key]:
            if item not in before[key]:
                noted.append(f"{label} {item}")
    return noted


def _music_taste_signal_count(state: Dict[str, Any]) -> int:
    return (
        len(state["genres"])
        + len(state["artists"])
        + len(state["tracks"])
        + len(state["albums"])
    )


def _is_music_reset_request(user_msg: str) -> bool:
    return any(word in user_msg.lower() for word in MUSIC_RESET_TRIGGERS)


def _is_music_recommend_request(user_msg: str) -> bool:
    return any(word in user_msg for word in MUSIC_RECOMMEND_TRIGGERS)


def _detect_music_chat_intent(user_msg: str) -> str:
    if _is_music_reset_request(user_msg):
        return "reset"
    if re.search(r"(안녕|하이|hello|반가|헬로)", user_msg, re.I):
        return "greeting"
    if re.search(r"(고마|감사|thanks|thank\s*you)", user_msg, re.I):
        return "thanks"
    if re.search(r"(도움|help|사용법|어떻게\s*써|뭐라고\s*말)", user_msg, re.I):
        return "help"
    if re.search(r"(또|다른\s*거|다시|재추천|바꿔|다르게)", user_msg):
        return "retry_recommend"
    if _is_music_recommend_request(user_msg):
        return "recommend"
    return "chat"


def _extract_music_genres(user_msg: str, state: Dict[str, Any]) -> bool:
    extracted = False
    compact = user_msg.lower().replace(" ", "")
    for genre in sorted(MUSIC_GENRE_OPTIONS, key=len, reverse=True):
        key = genre.lower().replace(" ", "")
        if key in compact or genre in user_msg:
            if genre not in state["genres"]:
                state["genres"].append(genre)
                extracted = True
    return extracted


def _extract_music_entities(user_msg: str, state: Dict[str, Any]) -> bool:
    extracted = _extract_music_genres(user_msg, state)
    compact = user_msg.lower().replace(" ", "")

    for alias_key, alias_value in MUSIC_QUERY_ALIASES.items():
        if alias_key.lower().replace(" ", "") in compact or alias_key in user_msg:
            if alias_value not in state["artists"]:
                state["artists"].append(alias_value)
                extracted = True
        if alias_value.lower() in user_msg.lower() and alias_value not in state["artists"]:
            state["artists"].append(alias_value)
            extracted = True

    album_patterns = [
        r"앨범\s*[「\"']?([^」\"'\n,]+)[」\"']?",
        r"[「\"']([^」\"']+)[」\"']\s*앨범",
    ]
    for pattern in album_patterns:
        for match in re.findall(pattern, user_msg):
            name = match.strip() if isinstance(match, str) else ""
            if len(name) >= 2 and name not in state["albums"]:
                state["albums"].append(name)
                extracted = True

    track_patterns = [
        r"노래\s*[「\"']?([^」\"'\n,]+)[」\"']?",
        r"곡\s*[「\"']?([^」\"'\n,]+)[」\"']?",
        r"[「\"']([^」\"']+)[」\"']\s*(?:노래|곡)",
    ]
    for pattern in track_patterns:
        for match in re.findall(pattern, user_msg):
            name = match.strip() if isinstance(match, str) else ""
            if len(name) >= 2 and name not in state["tracks"]:
                state["tracks"].append(name)
                extracted = True

    return extracted


async def _resolve_music_query(query: str) -> tuple[str, str] | None:
    q = query.strip()
    if len(q) < 2:
        return None
    for kind, field in (("artist", "artists"), ("track", "tracks"), ("album", "albums")):
        data = await asyncio.to_thread(suggest_music_items, kind, q, 3)
        results = data.get("results") or []
        if results:
            value = results[0].get("value") or results[0].get("label")
            if value:
                return field, str(value)
    return None


def _build_music_taste_summary(state: Dict[str, Any]) -> str:
    parts = []
    if state["genres"]:
        parts.append(f"장르: {', '.join(state['genres'])}")
    if state["artists"]:
        parts.append(f"아티스트: {', '.join(state['artists'])}")
    if state["tracks"]:
        parts.append(f"노래: {', '.join(state['tracks'])}")
    if state["albums"]:
        parts.append(f"앨범: {', '.join(state['albums'])}")
    return " · ".join(parts) if parts else ""


def _compose_music_bot_reply(
    *,
    user_msg: str,
    state: Dict[str, Any],
    intent: str,
    newly_noted: List[str],
    tracks: List[Dict[str, Any]] | None = None,
    auto_recommend: bool = False,
    api_key_missing: bool = False,
    empty_result: bool = False,
) -> str:
    summary = _build_music_taste_summary(state)
    snippet = user_msg if len(user_msg) <= 48 else f"{user_msg[:48]}…"

    if api_key_missing:
        return (
            "음악 추천 API 키(LASTFM_API_KEY)가 설정되지 않아 추천을 불러오지 못했어요. "
            ".env 파일에 키를 추가한 뒤 서버를 다시 시작해 주세요."
        )

    if tracks:
        intro = ""
        if newly_noted:
            intro = f"네, **{', '.join(newly_noted)}** 반영했어요. "
        elif intent == "retry_recommend":
            intro = "다른 곡으로 다시 골라봤어요. "
        intro += f"취향에 맞는 음악 {len(tracks)}곡을 추천해 드릴게요."
        if summary:
            intro += f"\n\n지금까지 파악한 취향 — {summary}"
        intro += "\n\n아래 카드에서 들어보시고 LastFM 링크도 확인해 보세요!"
        return intro

    if empty_result:
        if newly_noted:
            return (
                f"**{', '.join(newly_noted)}** 확인했어요. "
                "조건에 맞는 곡을 찾지 못했어요. 다른 아티스트·장르·노래로 다시 말씀해 주실래요?"
            )
        return "조건에 맞는 음악을 찾지 못했어요. 다른 키워드로 다시 입력해 주세요."

    if intent == "greeting":
        if state.get("turns", 0) <= 1:
            return (
                "안녕하세요! TasteLab 음악 추천 챗봇이에요. "
                "좋아하는 장르, 아티스트, 노래, 앨범을 말씀해 주시면 대화하면서 맞춤 음악을 찾아 드립니다."
            )
        return (
            f"다시 만나서 반가워요! {summary + ' 기준으로 ' if summary else ''}"
            "원하시는 음악 취향을 말씀해 주시거나 **「음악 추천해줘」**라고 해 주세요."
        )

    if intent == "thanks":
        return "천만에요! 다른 장르나 아티스트 취향도 알려주시면 더 정교하게 추천해 드릴게요."

    if intent == "help":
        return (
            "이렇게 말씀해 주시면 됩니다.\n"
            "· 장르 — 예: 케이팝, 재즈, 로파이\n"
            "· 아티스트 — 예: NewJeans, 아이유, The Weeknd\n"
            "· 노래 — 예: Ditto, 밤편지\n"
            "· 앨범 — 예: Palette\n\n"
            "취향을 알려주시면 기억해 두었다가 맞춤 음악을 추천해 드려요."
        )

    if newly_noted:
        joined = ", ".join(newly_noted)
        if auto_recommend:
            return (
                f"**{joined}** 확인했어요. "
                f"{('현재 취향 — ' + summary + '. ') if summary else ''}"
                "추천 곡을 찾는 중 문제가 있었어요. 다른 키워드로 다시 말씀해 주세요."
            )
        return (
            f"**{joined}** 기억했어요! "
            f"{('현재 취향 — ' + summary + '. ') if summary else ''}"
            "더 알려주시거나 **「음악 추천해줘」**라고 하시면 바로 곡을 골라 드릴게요."
        )

    if intent in ("recommend", "retry_recommend"):
        return (
            "추천해 드리고 싶은데, 아직 음악 취향 정보가 부족해요. "
            "장르·아티스트·노래·앨범 중 하나 이상을 알려주세요!"
        )

    if summary:
        if auto_recommend:
            return (
                f"「{snippet}」 잘 들었어요. 현재 취향은 {summary}입니다. "
                "이번 입력에서 새 키워드는 찾지 못했어요. 장르·아티스트·노래를 조금 더 구체적으로 말씀해 주세요."
            )
        return (
            f"네, 「{snippet}」 확인했어요. 현재 취향은 {summary}입니다. "
            "**「음악 추천해줘」**라고 하시면 맞춤 곡을 보여 드릴게요."
        )

    if auto_recommend:
        return (
            f"「{snippet}」 보내주셨네요! "
            "음악 추천을 위해 장르(예: 케이팝, 재즈), 아티스트, 노래, 앨범 이름을 알려주세요."
        )

    return (
        f"네, 「{snippet}」 잘 받았어요. "
        "장르·아티스트·노래·앨범을 말씀해 주시면 취향을 모아 음악을 추천해 드립니다."
    )


async def _run_music_recommendation(state: Dict[str, Any], exclude_track_keys: List[str] | None = None) -> Dict[str, Any]:
    return await asyncio.to_thread(
        recommend_music_by_taste,
        genres=state["genres"],
        artists=state["artists"],
        tracks=state["tracks"],
        albums=state["albums"],
        top_n=6,
        offset=state.get("offset", 0),
        exclude_track_keys=exclude_track_keys or [],
        fast=True,
        include_cover_art=False,
    )


@app.post("/api/music/chatbot/chat", response_model=MusicChatMessageResponse)
async def music_chatbot_chat(req: MusicChatMessageRequest) -> MusicChatMessageResponse:
    session_id = req.session_id.strip()
    user_msg = req.message.strip()

    if session_id not in MUSIC_CHAT_SESSIONS:
        MUSIC_CHAT_SESSIONS[session_id] = _new_music_chat_session()

    state = MUSIC_CHAT_SESSIONS[session_id]
    for key in ["genres", "artists", "tracks", "albums"]:
        _merge_unique(state[key], req.profile_taste.get(key, []))
    state["turns"] = state.get("turns", 0) + 1
    intent = _detect_music_chat_intent(user_msg)

    if intent == "reset":
        MUSIC_CHAT_SESSIONS[session_id] = _new_music_chat_session()
        return MusicChatMessageResponse(
            response=(
                "네, 음악 취향 기록을 모두 지웠어요. "
                "처음부터 다시 편하게 말씀해 주세요!"
            ),
            tracks=[],
            state=MUSIC_CHAT_SESSIONS[session_id],
        )

    taste_before = _music_taste_snapshot(state)
    extracted = _extract_music_entities(user_msg, state)

    if not extracted and intent not in ("greeting", "thanks", "help", "reset"):
        resolved = await _resolve_music_query(user_msg)
        if resolved:
            field, value = resolved
            if value not in state[field]:
                state[field].append(value)
                extracted = True

    newly_noted = _diff_newly_noted_music(taste_before, state)
    extracted = extracted or bool(newly_noted)

    if intent == "retry_recommend":
        state["offset"] = state.get("offset", 0) + 6

    taste_ready = _music_taste_signal_count(state) >= 2
    should_recommend = intent not in ("greeting", "thanks", "help") and (
        intent in ("recommend", "retry_recommend")
        or (extracted and taste_ready)
        or (req.auto_recommend and extracted and _music_taste_signal_count(state) >= 1)
    )

    tracks: List[Dict[str, Any]] = []
    api_key_missing = False
    empty_result = False

    if should_recommend and _music_taste_signal_count(state) >= 1:
        try:
            payload = await _run_music_recommendation(state, req.exclude_track_keys)
            api_key_missing = bool(payload.get("api_key_missing"))
            tracks = payload.get("results") or []
            empty_result = not tracks and not api_key_missing
            if tracks:
                state["stage"] = "recommended"
        except Exception as e:
            return MusicChatMessageResponse(
                response=(
                    f"죄송해요, 음악 추천 중 문제가 생겼어요. ({e})\n"
                    "잠시 후 다시 시도해 주세요."
                ),
                tracks=[],
                state=state,
            )

    response = _compose_music_bot_reply(
        user_msg=user_msg,
        state=state,
        intent=intent,
        newly_noted=newly_noted,
        tracks=tracks if tracks else None,
        auto_recommend=req.auto_recommend,
        api_key_missing=api_key_missing,
        empty_result=empty_result,
    )
    return MusicChatMessageResponse(response=response, tracks=tracks, state=state)