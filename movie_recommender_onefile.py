"""
movie_recommender_onefile.py

영화 추천 + 영화 기반 음악 추천을 한 파일에서 실행하는 통합 버전입니다.

필요 패키지:
    pip install requests python-dotenv sqlalchemy scikit-learn pandas numpy pillow matplotlib

.env 예시:
    TMDB_API_KEY=...
    OMDB_API_KEY=...          # 단일 키
    OMDB_API_KEYS=key1,key2   # 여러 키(쉼표로 구분) - 제한 회피용 로테이션
    LASTFM_API_KEY=...

주피터 노트북에서 사용 예시:
    from movie_recommender_onefile import collect_and_build_db, recommend_movies_and_music

    collect_and_build_db(
        popular_pages=3,
        top_rated_pages=3,
        genres=['액션', '드라마', 'SF', '스릴러'],
        data_dir='../data',
        db_path='../data/movies.db'
    )

    results = recommend_movies_and_music(
        genres=['SF', '스릴러'],
        directors=['Christopher Nolan'],
        actors=['Leonardo DiCaprio'],
        like_movies=['Inception', 'Interstellar'],
        min_score=6.5,
        top_n=4,
        db_path='../data/movies.db'
    )
    results
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from sqlalchemy import Column, Float, ForeignKey, Integer, String, Table, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, joinedload, relationship
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# -----------------------------------------------------------------------------
# 환경 설정
# -----------------------------------------------------------------------------

def safe_print(text: str) -> None:
    """이모티콘이 포함된 텍스트를 안전하게 출력하는 함수"""
    try:
        print(text)
    except UnicodeEncodeError:
        # 인코딩 오류 시 이모티콘을 텍스트로 대체
        safe_text = text
        safe_text = safe_text.replace("═", "=")  # ═ 문자를 =로 대체
        safe_text = safe_text.replace("✅", "[완료]")
        safe_text = safe_text.replace("❌", "[실패]")
        safe_text = safe_text.replace("🎬", "[영화]")
        safe_text = safe_text.replace("📝", "[줄거리]")
        safe_text = safe_text.replace("🎭", "[장르]")
        safe_text = safe_text.replace("🎬", "[감독]")
        safe_text = safe_text.replace("⭐", "[배우]")
        safe_text = safe_text.replace("📊", "[평점]")
        safe_text = safe_text.replace("💡", "[추천 이유]")
        safe_text = safe_text.replace("🖼️", "[포스터]")
        safe_text = safe_text.replace("🎬", "[사운드트랙]")
        safe_text = safe_text.replace("🎶", "[장르 기반 음악]")
        safe_text = safe_text.replace("🎞️", "[좋아한 영화 기반]")
        safe_text = safe_text.replace("👥", "[비슷한 취향]")
        safe_text = safe_text.replace("📈", "[취향 분석 기반]")
        print(safe_text)

def emoji_print(text: str) -> None:
    """주피터 노트북 환경에서 이모티콘을 직접 출력하는 함수"""
    try:
        # 주피터 노트북 환경 감지 - 여러 방법으로 확인
        import sys
        is_notebook = (
            'ipykernel' in sys.modules or 
            'IPython' in sys.modules or
            hasattr(sys.modules.get('builtins', {}), '__IPYTHON__')
        )
        
        if is_notebook:
            # 주피터 노트북에서는 이모티콘 직접 출력
            print(text)
        else:
            # Windows 터미널에서는 safe_print 사용
            safe_print(text)
    except:
        # 예외 발생 시 safe_print 사용
        safe_print(text)

try:
    from app_paths import app_base_dir, get_lastfm_api_key, load_app_env

    BASE_DIR = app_base_dir()
except ImportError:
    BASE_DIR = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()

    def load_app_env():
        load_dotenv(BASE_DIR / ".env", override=True)
        load_dotenv(override=True)
        return BASE_DIR / ".env"

    def get_lastfm_api_key():
        return (os.getenv("LASTFM_API_KEY") or "").strip()

load_app_env()

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
LASTFM_BASE = "https://ws.audioscrobbler.com/2.0/"

# 추천 히스토리(노트북 커널/프로세스 내에서만 유지)
_LAST_RECOMMENDED_BY_DB: dict[str, list[int]] = {}

# TMDB videos API 결과 캐시 (tmdb_id -> trailer_url or None)
_TRAILER_URL_CACHE: dict[int, str | None] = {}


def reset_recommendation_history(db_path: str | Path = "data/movies.db"):
    """같은 세션에서 '직전 추천 제외' 히스토리를 초기화."""
    _LAST_RECOMMENDED_BY_DB.pop(str(Path(db_path)), None)

# -----------------------------------------------------------------------------
# DB 모델
# -----------------------------------------------------------------------------

Base = declarative_base()

movie_directors = Table(
    "movie_directors",
    Base.metadata,
    Column("movie_id", Integer, ForeignKey("movies.id"), primary_key=True),
    Column("person_id", Integer, ForeignKey("people.id"), primary_key=True),
)

movie_actors = Table(
    "movie_actors",
    Base.metadata,
    Column("movie_id", Integer, ForeignKey("movies.id"), primary_key=True),
    Column("person_id", Integer, ForeignKey("people.id"), primary_key=True),
    Column("character", String(200), nullable=True),
)

movie_genres = Table(
    "movie_genres",
    Base.metadata,
    Column("movie_id", Integer, ForeignKey("movies.id"), primary_key=True),
    Column("genre_id", Integer, ForeignKey("genres.id"), primary_key=True),
)


class Movie(Base):
    __tablename__ = "movies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tmdb_id = Column(Integer, unique=True, nullable=False)
    imdb_id = Column(String(20), unique=True, nullable=True)
    title = Column(String(300), nullable=False)
    original_title = Column(String(300), nullable=True)
    overview = Column(Text, nullable=True)
    release_date = Column(String(20), nullable=True)
    runtime = Column(Integer, nullable=True)
    poster_path = Column(String(200), nullable=True)
    poster_url = Column(String(300), nullable=True)
    tmdb_score = Column(Float, nullable=True)
    tmdb_votes = Column(Integer, nullable=True)
    imdb_score = Column(String(20), nullable=True)
    rotten_tomatoes = Column(String(20), nullable=True)
    metacritic = Column(String(20), nullable=True)

    genres = relationship("Genre", secondary=movie_genres, back_populates="movies")
    directors = relationship("Person", secondary=movie_directors, back_populates="directed")
    actors = relationship("Person", secondary=movie_actors, back_populates="acted_in")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tmdb_id": self.tmdb_id,
            "imdb_id": self.imdb_id,
            "title": self.title,
            "original_title": self.original_title,
            "overview": self.overview,
            "release_date": self.release_date,
            "runtime": self.runtime,
            "poster_url": self.poster_url,
            "tmdb_score": self.tmdb_score,
            "tmdb_votes": self.tmdb_votes,
            "imdb_score": self.imdb_score,
            "rotten_tomatoes": self.rotten_tomatoes,
            "metacritic": self.metacritic,
            "genres": [g.name for g in self.genres],
            "directors": [d.name for d in self.directors],
            "actors": [a.name for a in self.actors],
        }


class Person(Base):
    __tablename__ = "people"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tmdb_id = Column(Integer, unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    directed = relationship("Movie", secondary=movie_directors, back_populates="directors")
    acted_in = relationship("Movie", secondary=movie_actors, back_populates="actors")


class Genre(Base):
    __tablename__ = "genres"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    movies = relationship("Movie", secondary=movie_genres, back_populates="genres")


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    favorite_genres = Column(Text, nullable=True)
    favorite_directors = Column(Text, nullable=True)
    favorite_actors = Column(Text, nullable=True)
    favorite_movies = Column(Text, nullable=True)
    min_score = Column(Float, default=6.5)


def get_engine(db_path: str | Path = "data/movies.db"):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", echo=False)


def init_db(db_path: str | Path = "data/movies.db"):
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    return engine

# -----------------------------------------------------------------------------
# API 클라이언트
# -----------------------------------------------------------------------------


class TMDBClient:
    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self):
        try:
            from app_paths import get_tmdb_api_key

            self.api_key = get_tmdb_api_key()
        except ImportError:
            self.api_key = (os.getenv("TMDB_API_KEY") or "").strip()
        if not self.api_key:
            raise ValueError("TMDB_API_KEY가 .env에 없습니다. 예고편 링크에 필요합니다.")
        self.session = requests.Session()
        self.session.params = {"api_key": self.api_key, "language": "ko-KR"}

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.BASE_URL}{endpoint}"
        for attempt in range(3):
            try:
                r = self.session.get(url, params=params, timeout=10)
                r.raise_for_status()
                return r.json()
            except requests.exceptions.HTTPError:
                if r.status_code == 429:
                    time.sleep(2**attempt)
                else:
                    raise
            except requests.exceptions.RequestException as e:
                print(f"  TMDB 요청 실패 ({attempt + 1}/3): {e}")
                time.sleep(1)
        raise RuntimeError(f"TMDB API 요청 실패: {endpoint}")

    def get_popular_movies(self, page: int = 1):
        return self._get("/movie/popular", {"page": page})

    def get_top_rated_movies(self, page: int = 1):
        return self._get("/movie/top_rated", {"page": page})

    def get_movies_by_genre(self, genre_id: int, page: int = 1):
        return self._get(
            "/discover/movie",
            {
                "with_genres": genre_id,
                "sort_by": "vote_average.desc",
                "vote_count.gte": 100,
                "page": page,
            },
        )

    def get_movie_full(self, movie_id: int):
        return self._get(f"/movie/{movie_id}", {"append_to_response": "credits,keywords"})

    def get_movie_videos(self, movie_id: int, language: str | None = None):
        params = {"language": language} if language else None
        return self._get(f"/movie/{movie_id}/videos", params)

    def get_genre_list(self):
        return self._get("/genre/movie/list")


def pick_youtube_trailer_url(videos: list[dict[str, Any]]) -> str | None:
    """TMDB videos 결과에서 YouTube 예고편 URL을 고릅니다."""
    yt = [v for v in videos if (v.get("site") or "").lower() == "youtube" and v.get("key")]
    if not yt:
        return None

    type_priority = {"trailer": 0, "teaser": 1, "clip": 2, "featurette": 3}

    def sort_key(v: dict[str, Any]) -> tuple:
        t = (v.get("type") or "").lower()
        return (
            type_priority.get(t, 99),
            0 if v.get("official") else 1,
            0 if v.get("iso_639_1") == "ko" else 1,
            -(v.get("size") or 0),
        )

    best = min(yt, key=sort_key)
    return f"https://www.youtube.com/watch?v={best['key']}"


def fetch_trailer_url(tmdb_id: int, client: TMDBClient | None = None) -> str | None:
    """영화 TMDB ID로 YouTube 예고편 URL을 조회합니다 (ko → en 순)."""
    tid = int(tmdb_id)
    if tid in _TRAILER_URL_CACHE:
        return _TRAILER_URL_CACHE[tid]

    try:
        tmdb = client or TMDBClient()
    except ValueError:
        return None
    url: str | None = None
    for lang in ("ko-KR", "en-US"):
        try:
            data = tmdb.get_movie_videos(tid, language=lang)
            url = pick_youtube_trailer_url(data.get("results") or [])
            if url:
                break
        except Exception as e:
            print(f"  [TMDB videos] id={tid} lang={lang}: {e}")

    _TRAILER_URL_CACHE[tid] = url
    return url


class OMDbClient:
    BASE_URL = "https://www.omdbapi.com"

    def __init__(self, strict: bool = False):
        keys_raw = (os.getenv("OMDB_API_KEYS") or "").strip()
        if keys_raw:
            keys = [k.strip() for k in keys_raw.split(",") if k.strip()]
        else:
            keys = [os.getenv("OMDB_API_KEY", "").strip()]
            keys = [k for k in keys if k]

        self.session = requests.Session()
        
        # 유효한 키만 필터링
        self.api_keys = self._filter_valid_keys(keys)
        self._key_idx = 0

        if not self.api_keys and strict:
            raise ValueError("OMDB_API_KEY 또는 OMDB_API_KEYS가 .env에 없습니다.")
    
    def _filter_valid_keys(self, keys: list[str]) -> list[str]:
        """유효한 API 키만 필터링"""
        valid_keys = []
        for key in keys:
            try:
                # 간단한 테스트 요청으로 키 유효성 확인
                params = {"apikey": key, "t": "test", "plot": "short"}
                r = self.session.get(self.BASE_URL, params=params, timeout=5)
                if r.status_code == 200:
                    data = r.json()
                    # 명확한 조건: Response가 "True"인 경우만 유효
                    if data.get("Response") == "True":
                        valid_keys.append(key)
                        print(f"[OK] 유효한 OMDb 키: {key[:4]}****")
                    else:
                        print(f"[FAIL] 무효한 OMDb 키: {key[:4]}**** - {data.get('Error', 'Unknown')}")
                else:
                    print(f"[FAIL] 무효한 OMDb 키: {key[:4]}**** - HTTP {r.status_code}")
            except Exception as e:
                print(f"[FAIL] 무효한 OMDb 키: {key[:4]}**** - {str(e)}")
                continue
        return valid_keys

    def _get(self, params: dict[str, Any]) -> dict[str, Any] | None:
        if not self.api_keys:
            return None
        params = dict(params)

        def next_key():
            k = self.api_keys[self._key_idx % len(self.api_keys)]
            self._key_idx += 1
            return k

        # 키 로테이션 + 네트워크 재시도
        for attempt in range(max(3, len(self.api_keys))):
            try:
                params["apikey"] = next_key()
                r = self.session.get(self.BASE_URL, params=params, timeout=10)
                r.raise_for_status()
                data = r.json()
                if data.get("Response") == "False":
                    err = (data.get("Error") or "").lower()
                    # 키 제한/인증 문제면 다른 키로 시도
                    if "limit" in err or "invalid api key" in err or "apikey" in err:
                        continue
                    return None
                return data
            except requests.exceptions.RequestException as e:
                print(f"  OMDb 실패 ({attempt + 1}/3): {e}")
                time.sleep(1)
        return None

    def get_by_imdb_id(self, imdb_id: str):
        return self._get({"i": imdb_id, "plot": "short"})

    def get_by_title(self, title: str, year: int | None = None):
        params: dict[str, Any] = {"t": title}
        if year:
            params["y"] = year
        return self._get(params)


class LastFMClient:
    def __init__(self, strict: bool = False):
        try:
            self.api_key = get_lastfm_api_key()
        except NameError:
            self.api_key = (os.getenv("LASTFM_API_KEY") or "").strip()
        if not self.api_key and strict:
            raise ValueError("LASTFM_API_KEY가 .env에 없습니다.")
        self.session = requests.Session()

    def _get(self, method: str, params: dict[str, Any] | None = None):
        if not self.api_key:
            return {}
        p = {"method": method, "api_key": self.api_key, "format": "json"}
        if params:
            p.update(params)
        r = self.session.get(LASTFM_BASE, params=p, timeout=float(os.getenv("LASTFM_TIMEOUT", "7")))
        r.raise_for_status()
        return r.json()

    def search_soundtrack(self, movie_title: str, limit: int = 3):
        queries = [
            f"{movie_title} soundtrack",
            f"{movie_title} OST",
            f"{movie_title} original score",
        ]
        seen, albums = set(), []
        for q in queries:
            data = self._get("album.search", {"album": q, "limit": limit})
            for a in data.get("results", {}).get("albummatches", {}).get("album", []):
                key = (a.get("name", ""), a.get("artist", ""))
                if key in seen:
                    continue
                seen.add(key)
                images = a.get("image", [])
                image_url = next((img["#text"] for img in reversed(images) if img.get("#text")), None)
                albums.append(
                    {
                        "name": a.get("name", ""),
                        "artist": a.get("artist", ""),
                        "image_url": image_url,
                        "lastfm_url": a.get("url", ""),
                    }
                )
            if len(albums) >= limit:
                break
        return albums[:limit]

    def recommend_by_genre(self, movie_genres: list[str], limit: int = 8):
        tags = self._genres_to_tags(movie_genres)
        seen, tracks = set(), []
        for tag in tags[:3]:
            data = self._get("tag.getTopTracks", {"tag": tag, "limit": limit})
            for t in data.get("tracks", {}).get("track", []):
                name = t.get("name", "")
                artist_data = t.get("artist", {})
                artist = artist_data.get("name", "") if isinstance(artist_data, dict) else artist_data
                key = (name, artist)
                if key in seen:
                    continue
                seen.add(key)
                images = t.get("image", [])
                image_url = next((img["#text"] for img in reversed(images) if img.get("#text")), None)
                tracks.append(
                    {
                        "name": name,
                        "artist": artist,
                        "image_url": image_url,
                        "lastfm_url": t.get("url", ""),
                        "tag": tag,
                    }
                )
            if len(tracks) >= limit:
                break
        return tracks[:limit]

    def _genres_to_tags(self, movie_genres: list[str]):
        mapping = {
            "액션": ["epic", "hard rock", "power metal"],
            "모험": ["adventure", "epic", "orchestral"],
            "SF": ["electronic", "synthwave", "ambient"],
            "공포": ["dark ambient", "gothic", "doom metal"],
            "스릴러": ["dark", "post-rock", "industrial"],
            "드라마": ["singer-songwriter", "folk", "acoustic"],
            "로맨스": ["love songs", "soul", "jazz"],
            "코미디": ["feel good", "pop", "indie pop"],
            "애니메이션": ["anime", "j-pop", "orchestral"],
            "범죄": ["jazz", "hip-hop", "blues"],
            "역사": ["classical", "orchestral", "world"],
            "판타지": ["orchestral", "epic", "celtic"],
            "전쟁": ["orchestral", "epic", "metal"],
            "음악": ["soundtrack", "pop", "indie"],
        }
        tags: list[str] = []
        for genre in movie_genres or []:
            for key, tag_list in mapping.items():
                if key in genre or genre in key:
                    for tag in tag_list:
                        if tag not in tags:
                            tags.append(tag)
                    break
        return tags or ["soundtrack", "cinematic", "instrumental"]

# -----------------------------------------------------------------------------
# 파싱 함수
# -----------------------------------------------------------------------------


def parse_movie(raw: dict[str, Any]):
    credits = raw.get("credits", {})
    directors = [
        {"id": p["id"], "name": p["name"]}
        for p in credits.get("crew", [])
        if p.get("job") == "Director"
    ]
    actors = [
        {"id": p["id"], "name": p["name"], "character": p.get("character", "")}
        for p in credits.get("cast", [])[:10]
    ]
    genres = [g["name"] for g in raw.get("genres", [])]
    return {
        "tmdb_id": raw["id"],
        "imdb_id": raw.get("imdb_id", ""),
        "title": raw.get("title", ""),
        "original_title": raw.get("original_title", ""),
        "overview": raw.get("overview", ""),
        "release_date": raw.get("release_date", ""),
        "runtime": raw.get("runtime"),
        "vote_average": raw.get("vote_average"),
        "vote_count": raw.get("vote_count"),
        "genres": genres,
        "directors": directors,
        "actors": actors,
        "poster_path": raw.get("poster_path", ""),
        "poster_url": f"{TMDB_IMAGE_BASE}{raw.get('poster_path', '')}" if raw.get("poster_path") else None,
    }


def parse_genre_list(raw: dict[str, Any]):
    return {g["id"]: g["name"] for g in raw.get("genres", [])}


def parse_ratings(raw: dict[str, Any] | None):
    if not raw:
        return {}
    ratings = {"imdb_id": raw.get("imdbID", ""), "imdb_votes": raw.get("imdbVotes", "")}
    for r in raw.get("Ratings", []):
        if r.get("Source") == "Internet Movie Database":
            ratings["imdb_score"] = r.get("Value")
        elif r.get("Source") == "Rotten Tomatoes":
            ratings["rotten_tomatoes"] = r.get("Value")
        elif r.get("Source") == "Metacritic":
            ratings["metacritic"] = r.get("Value")
    return ratings

# -----------------------------------------------------------------------------
# 수집기
# -----------------------------------------------------------------------------


class MovieCollector:
    def __init__(self, output_dir: str | Path = "data"):
        self.tmdb = TMDBClient()
        self.omdb = OMDbClient(strict=False)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def collect_movie(self, tmdb_id: int):
        try:
            raw = self.tmdb.get_movie_full(tmdb_id)
            movie = parse_movie(raw)
        except Exception as e:
            print(f"  [TMDB 오류] id={tmdb_id}: {e}")
            return None

        imdb_id = raw.get("imdb_id", "")
        year = int(movie["release_date"][:4]) if movie.get("release_date") else None
        omdb_raw = self.omdb.get_by_imdb_id(imdb_id) if imdb_id else self.omdb.get_by_title(raw.get("original_title", movie["title"]), year=year)
        movie.update(parse_ratings(omdb_raw))
        return movie

    def collect_all(
        self,
        popular_pages: int = 10,
        top_rated_pages: int = 10,
        genres: list[str] | None = None,
        genre_pages: int = 10,
    ):
        print("=== 영화 데이터 수집 시작 ===\n")
        ids = self._gather_ids(popular_pages, top_rated_pages, genres, genre_pages=genre_pages)
        print(f"\n총 {len(ids)}개 영화 수집 시작...\n")

        movies, failed = [], []
        for i, mid in enumerate(ids, 1):
            print(f"  [{i:>4}/{len(ids)}] id={mid} ...", end=" ")
            movie = self.collect_movie(mid)
            if movie:
                emoji_print(f"✅ {movie['title']} (RT: {movie.get('rotten_tomatoes', 'N/A')})")
                movies.append(movie)
            else:
                emoji_print("❌ 실패")
                failed.append(mid)
            time.sleep(0.25)

        emoji_print(f"\n✅ 완료: {len(movies)}개 성공 / {len(failed)}개 실패")
        return movies

    def _gather_ids(
        self,
        popular_pages: int,
        top_rated_pages: int,
        genres: list[str] | None,
        genre_pages: int = 10,
    ):
        ids: set[int] = set()
        print("▶ 인기 영화 ID 수집...")
        for page in range(1, popular_pages + 1):
            for movie in self.tmdb.get_popular_movies(page).get("results", []):
                ids.add(movie["id"])
            time.sleep(0.25)

        print("▶ 평점 높은 영화 ID 수집...")
        for page in range(1, top_rated_pages + 1):
            for movie in self.tmdb.get_top_rated_movies(page).get("results", []):
                ids.add(movie["id"])
            time.sleep(0.25)

        if genres:
            genre_map = parse_genre_list(self.tmdb.get_genre_list())
            for genre_name in genres:
                gid = next((k for k, v in genre_map.items() if genre_name in v or v in genre_name), None)
                if not gid:
                    print(f"  ⚠️ TMDB 장르를 찾지 못함: {genre_name}")
                    continue
                print(f"▶ {genre_name} 장르 ID 수집...")
                for page in range(1, max(1, int(genre_pages)) + 1):
                    for movie in self.tmdb.get_movies_by_genre(gid, page).get("results", []):
                        ids.add(movie["id"])
                    time.sleep(0.25)
        return ids

    def save(self, movies: list[dict[str, Any]], filename: str = "movies.json"):
        path = self.output_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(movies, f, ensure_ascii=False, indent=2)
        print(f"💾 저장 완료: {path} ({len(movies)}개)")
        return path

    def load(self, filename: str = "movies.json"):
        path = self.output_dir / filename
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

# -----------------------------------------------------------------------------
# DB 헬퍼
# -----------------------------------------------------------------------------


class MovieDB:
    def __init__(self, db_path: str | Path = "data/movies.db"):
        self.db_path = Path(db_path)
        self.engine = init_db(self.db_path)

    def session(self):
        return Session(self.engine)

    def save_movies(self, movies: list[dict[str, Any]], verbose: bool = True):
        saved = 0
        with self.session() as sess:
            for data in movies:
                if sess.query(Movie).filter_by(tmdb_id=data["tmdb_id"]).first():
                    continue

                genres = []
                for gname in data.get("genres", []) or []:
                    genre = sess.query(Genre).filter_by(name=gname).first()
                    if not genre:
                        genre = Genre(name=gname)
                        sess.add(genre)
                    genres.append(genre)

                directors = []
                for director_data in data.get("directors", []) or []:
                    person = sess.query(Person).filter_by(tmdb_id=director_data["id"]).first()
                    if not person:
                        person = Person(tmdb_id=director_data["id"], name=director_data["name"])
                        sess.add(person)
                    directors.append(person)

                actors = []
                for actor_data in data.get("actors", []) or []:
                    person = sess.query(Person).filter_by(tmdb_id=actor_data["id"]).first()
                    if not person:
                        person = Person(tmdb_id=actor_data["id"], name=actor_data["name"])
                        sess.add(person)
                    actors.append(person)

                movie = Movie(
                    tmdb_id=data["tmdb_id"],
                    imdb_id=data.get("imdb_id"),
                    title=data["title"],
                    original_title=data.get("original_title"),
                    overview=data.get("overview"),
                    release_date=data.get("release_date"),
                    runtime=data.get("runtime"),
                    poster_path=data.get("poster_path"),
                    poster_url=data.get("poster_url"),
                    tmdb_score=data.get("vote_average"),
                    tmdb_votes=data.get("vote_count"),
                    imdb_score=data.get("imdb_score"),
                    rotten_tomatoes=data.get("rotten_tomatoes"),
                    metacritic=data.get("metacritic"),
                    genres=genres,
                    directors=directors,
                    actors=actors,
                )
                sess.add(movie)
                saved += 1
                if verbose and saved % 50 == 0:
                    print(f"  {saved}개 저장 중...")
            sess.commit()
        emoji_print(f"✅ DB 저장 완료: {saved}개 신규")
        return saved

    def get_top_rated_dicts(self, limit: int = 20, min_votes: int = 100):
        # joinedload로 관계 데이터를 세션 안에서 같이 불러와 DetachedInstanceError 방지
        with self.session() as sess:
            movies = (
                sess.query(Movie)
                .options(joinedload(Movie.genres), joinedload(Movie.directors), joinedload(Movie.actors))
                .filter(Movie.tmdb_votes >= min_votes)
                .order_by(Movie.tmdb_score.desc())
                .limit(limit)
                .all()
            )
            return [m.to_dict() for m in movies]

    def stats(self):
        with self.session() as sess:
            return {
                "영화 수": sess.query(Movie).count(),
                "인물 수": sess.query(Person).count(),
                "장르 수": sess.query(Genre).count(),
            }

    def save_preferences(
        self,
        genres: list[str] | None = None,
        directors: list[str] | None = None,
        actors: list[str] | None = None,
        movies: list[str] | None = None,
        min_score: float = 6.5,
    ):
        with self.session() as sess:
            sess.query(UserPreference).delete()
            pref = UserPreference(
                favorite_genres=json.dumps(genres or [], ensure_ascii=False),
                favorite_directors=json.dumps(directors or [], ensure_ascii=False),
                favorite_actors=json.dumps(actors or [], ensure_ascii=False),
                favorite_movies=json.dumps(movies or [], ensure_ascii=False),
                min_score=min_score,
            )
            sess.add(pref)
            sess.commit()
        emoji_print("✅ 선호도 저장 완료")

    def load_preferences(self):
        with self.session() as sess:
            pref = sess.query(UserPreference).first()
            if not pref:
                return {}
            return {
                "genres": json.loads(pref.favorite_genres or "[]"),
                "directors": json.loads(pref.favorite_directors or "[]"),
                "actors": json.loads(pref.favorite_actors or "[]"),
                "movies": json.loads(pref.favorite_movies or "[]"),
                "min_score": pref.min_score,
            }

# -----------------------------------------------------------------------------
# 추천 엔진
# -----------------------------------------------------------------------------


class RecommendEngine:
    def __init__(self, db_path: str | Path = "data/movies.db"):
        self.engine = get_engine(db_path)
        self._df: pd.DataFrame | None = None
        self._tfidf = None
        self._vec = None
        self._collab: dict[int, set[int]] = defaultdict(set)
        self._tmdbid_to_loc: dict[int, int] = {}

    def load(self):
        with Session(self.engine) as sess:
            movies = (
                sess.query(Movie)
                .options(joinedload(Movie.genres), joinedload(Movie.directors), joinedload(Movie.actors))
                .all()
            )
            rows = []
            for m in movies:
                rows.append(
                    {
                        "id": m.id,
                        "tmdb_id": m.tmdb_id,
                        "title": m.title,
                        "original_title": m.original_title or m.title,
                        "overview": m.overview or "",
                        "release_date": m.release_date or "",
                        "runtime": m.runtime,
                        "tmdb_score": m.tmdb_score or 0.0,
                        "tmdb_votes": m.tmdb_votes or 0,
                        "imdb_score": m.imdb_score or "",
                        "rotten_tomatoes": m.rotten_tomatoes or "",
                        "metacritic": m.metacritic or "",
                        "poster_url": m.poster_url or "",
                        "genres": [g.name for g in m.genres],
                        "directors": [d.name for d in m.directors],
                        "actors": [a.name for a in m.actors],
                    }
                )
        self._df = pd.DataFrame(rows).reset_index(drop=True)
        if self._df.empty:
            raise ValueError("DB에 영화가 없습니다. 먼저 collect_and_build_db()를 실행하세요.")
        self._build_tfidf()
        self._build_collab()
        self._tmdbid_to_loc = {int(tid): int(i) for i, tid in enumerate(self._df["tmdb_id"].tolist())}
        emoji_print(f"✅ {len(self._df)}개 영화 로드 완료")
        return self

    @staticmethod
    def _name_match(query: str, names: list[str]) -> bool:
        q = (query or "").strip().lower()
        if not q:
            return False
        return any(q in (n or "").lower() or (n or "").lower() in q for n in names or [])

    @classmethod
    def _matched_names(cls, queries: list[str] | None, names: list[str] | None) -> list[str]:
        matched = []
        for q in queries or []:
            for n in names or []:
                if cls._name_match(q, [n]) and n not in matched:
                    matched.append(n)
        return matched

    @staticmethod
    def _genre_match(query: str, genres: list[str]) -> bool:
        q = (query or "").strip().lower()
        if not q:
            return False
        return any(q == (g or "").lower() or q in (g or "").lower() or (g or "").lower() in q for g in genres or [])

    def _build_tfidf(self):
        assert self._df is not None

        def soup(row):
            # 감독/배우/장르가 추천에 잘 반영되도록 텍스트 가중치를 반복으로 부여
            return (
                (" ".join(row["genres"]) + " ") * 2
                + (" ".join(row["directors"]) + " ") * 4
                + (" ".join(row["actors"][:6]) + " ") * 2
                + " "
                + row["overview"]
            )

        self._df["soup"] = self._df.apply(soup, axis=1)
        self._vec = TfidfVectorizer(stop_words="english", min_df=1)
        self._tfidf = self._vec.fit_transform(self._df["soup"])

    def _build_collab(self):
        """실제 사용자 로그가 없기 때문에 평점/투표수를 기반으로 데모용 유사 취향군을 생성."""
        assert self._df is not None
        np.random.seed(42)
        n_users = 1200
        for _, row in self._df.iterrows():
            score = row["tmdb_score"] / 10.0
            votes = min(row["tmdb_votes"] / 10000, 1.0)
            prob = min(0.96, score * 0.68 + votes * 0.32)
            liked = set(np.where(np.random.random(n_users) < prob)[0].tolist())
            self._collab[int(row["tmdb_id"])] = liked

    @staticmethod
    def _recent_unique_texts(values: list[str] | None, limit: int = 5) -> list[str]:
        """누적 피드백이 추천을 과하게 지배하지 않도록 최근 선호만 부드럽게 반영."""
        seen: set[str] = set()
        result: list[str] = []
        for raw in reversed(values or []):
            text = str(raw or "").strip()
            key = text.lower()
            if not text or key in seen:
                continue
            seen.add(key)
            result.append(text)
            if len(result) >= limit:
                break
        return list(reversed(result))

    def _liked_features(self, like_ids: list[int]) -> dict[str, Any]:
        assert self._df is not None
        features = {"genres": set(), "directors": set(), "actors": set(), "titles": []}
        if not like_ids:
            return features
        liked = self._df[self._df["tmdb_id"].isin(like_ids)]
        for _, row in liked.iterrows():
            features["titles"].append(str(row["title"]))
            features["genres"].update(row["genres"] or [])
            features["directors"].update(row["directors"] or [])
            features["actors"].update((row["actors"] or [])[:4])
        return features

    def _pref_score(self, df, genres, directors, actors):
        s = pd.Series(0.0, index=df.index)
        for g in genres or []:
            s += df["genres"].apply(lambda x: 2.2 if self._genre_match(g, x) else 0.0)
        for d in directors or []:
            s += df["directors"].apply(lambda x: 5.0 if self._name_match(d, x) else 0.0)
        for a in actors or []:
            s += df["actors"].apply(lambda x: 3.6 if self._name_match(a, x) else 0.0)
        return s

    def _combo_score(self, df, genres, directors, actors, liked_features: dict[str, Any]):
        """장르/감독/배우가 동시에 겹칠 때 가중치를 주는 결합 점수."""
        scores = []
        liked_directors = liked_features.get("directors", set())
        liked_actors = liked_features.get("actors", set())
        liked_genres = liked_features.get("genres", set())
        for _, row in df.iterrows():
            row_genres = row["genres"] or []
            row_directors = row["directors"] or []
            row_actors = row["actors"] or []
            has_genre = any(self._genre_match(g, row_genres) for g in (genres or []))
            has_director = any(self._name_match(d, row_directors) for d in (directors or []))
            has_actor = any(self._name_match(a, row_actors) for a in (actors or []))
            shares_like_director = bool(set(row_directors) & liked_directors)
            shares_like_actor = bool(set(row_actors[:6]) & liked_actors)
            shares_like_genre = bool(set(row_genres) & liked_genres)

            score = 0.0
            if has_director and has_actor:
                score += 0.80
            if has_genre and (has_director or has_actor):
                score += 0.40
            # 좋아요 피드백은 강한 고정 조건이 아니라 부드러운 참고 신호로만 사용한다.
            if shares_like_director and shares_like_actor:
                score += 0.34
            elif shares_like_director or shares_like_actor:
                score += 0.16
            if shares_like_genre and (shares_like_director or shares_like_actor):
                score += 0.10
            scores.append(score)
        return pd.Series(scores, index=df.index)

    def _collab_score(self, like_ids):
        assert self._df is not None
        if not like_ids:
            return pd.Series(0.0, index=self._df.index)
        base: set[int] = set()
        for tid in like_ids:
            base |= self._collab.get(tid, set())
        if not base:
            return pd.Series(0.0, index=self._df.index)
        scores = []
        for _, row in self._df.iterrows():
            users = self._collab.get(int(row["tmdb_id"]), set())
            ratio = len(base & users) / len(base)
            # 협업 신호는 취향 확장용 보조 점수로만 반영한다.
            scores.append(ratio * 0.55 if ratio >= 0.5 else ratio * 0.12)
        return pd.Series(scores, index=self._df.index)

    def _sim_score(self, like_ids):
        assert self._df is not None
        s = pd.Series(0.0, index=self._df.index)
        used = 0
        for tid in like_ids:
            mask = self._df["tmdb_id"] == tid
            if not mask.any():
                continue
            idx = self._df[mask].index[0]
            loc = self._df.index.get_loc(idx)
            sims = cosine_similarity(self._tfidf[loc], self._tfidf).flatten()
            s += pd.Series(sims, index=self._df.index)
            used += 1
        return s / used if used else s

    @staticmethod
    def _overview_short(overview: str, max_chars: int = 260) -> str:
        text = re.sub(r"\s+", " ", (overview or "").strip())
        if not text:
            return ""
        parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
        candidate = " ".join(parts[:3]) if parts else text
        return (candidate[: max_chars - 1] + "…") if len(candidate) > max_chars else candidate

    def _find_sequels(self, like_titles):
        assert self._df is not None
        sequels = []
        for title in like_titles or []:
            base = self._series_base(title)
            if not base:
                continue
            mask = self._df["title"].str.contains(re.escape(base), case=False, na=False)
            series = self._df[mask].sort_values("release_date")
            if len(series) < 2:
                continue
            cur = series[series["title"].str.contains(re.escape(title), case=False, na=False)]
            if cur.empty:
                continue
            pos = series.index.get_loc(cur.index[0])
            if pos + 1 < len(series):
                nxt = series.iloc[pos + 1]
                sequels.append({"tmdb_id": int(nxt["tmdb_id"]), "reason": f"'{title}'의 다음 편입니다."})
        return sequels

    @staticmethod
    def _series_base(title):
        if ":" in title:
            return title.split(":")[0].strip()
        for pat in [r"\s+(2|3|4|II|III|IV)\b", r"\s+Part\s*\d"]:
            m = re.search(pat, title, re.IGNORECASE)
            if m:
                return title[: m.start()].strip()
        return None

    def _best_like_movie_for_row(self, row_tmdb_id: int, like_ids: list[int], like_titles: list[str]):
        if not like_ids:
            return None
        target_loc = self._tmdbid_to_loc.get(int(row_tmdb_id))
        if target_loc is None:
            return None
        like_locs = [self._tmdbid_to_loc.get(int(tid)) for tid in like_ids]
        pairs = [(loc, title) for loc, title in zip(like_locs, like_titles) if loc is not None]
        if not pairs:
            return None
        locs = [p[0] for p in pairs]
        titles = [p[1] for p in pairs]
        sims = cosine_similarity(self._tfidf[target_loc], self._tfidf[locs]).flatten()
        if sims.size == 0:
            return None
        j = int(np.argmax(sims))
        return {"title": titles[j], "score": float(sims[j])}

    @staticmethod
    def _norm(s):
        mx = s.max()
        return s / mx if mx > 0 else s

    def _diversified_top(self, df, top_n: int):
        """상위권 안에서 비슷한 장르/감독/배우가 과하게 반복되지 않도록 재정렬."""
        if df.empty:
            return df
        pool = df.sort_values("final", ascending=False).head(max(int(top_n) * 5, int(top_n) + 8)).copy()
        selected_indexes = []
        while len(selected_indexes) < int(top_n) and not pool.empty:
            best_idx = None
            best_score = None
            for idx, row in pool.iterrows():
                adjusted = float(row.get("final", 0.0))
                row_genres = set(row.get("genres") or [])
                row_directors = set(row.get("directors") or [])
                row_actors = set((row.get("actors") or [])[:4])
                for selected_idx in selected_indexes:
                    prev = df.loc[selected_idx]
                    prev_genres = set(prev.get("genres") or [])
                    prev_directors = set(prev.get("directors") or [])
                    prev_actors = set((prev.get("actors") or [])[:4])
                    genre_overlap = len(row_genres & prev_genres) / max(1, len(row_genres | prev_genres))
                    adjusted -= genre_overlap * 0.035
                    if row_directors & prev_directors:
                        adjusted -= 0.055
                    if row_actors & prev_actors:
                        adjusted -= 0.035
                if best_score is None or adjusted > best_score:
                    best_score = adjusted
                    best_idx = idx
            selected_indexes.append(best_idx)
            pool = pool.drop(index=best_idx)
        return df.loc[selected_indexes]

    def recommend(
        self,
        genres: list[str] | None = None,
        directors: list[str] | None = None,
        actors: list[str] | None = None,
        like_movies: list[str] | None = None,
        min_score: float = 6.5,
        top_n: int = 4,
        exclude_tmdb_ids: list[int] | None = None,
    ):
        assert self._df is not None
        df = self._df.copy()

        like_movie_inputs = self._recent_unique_texts(like_movies or [], limit=5)
        like_ids = []
        like_titles = []
        for title in like_movie_inputs:
            title = str(title).strip()
            if not title:
                continue
            # 완전 일치 우선, 없으면 부분 일치. TMDB 한글 제목/원제 둘 다 검색한다.
            exact = df[(df["title"].str.lower() == title.lower()) | (df["original_title"].str.lower() == title.lower())]
            if not exact.empty:
                match = exact
            else:
                mask_title = df["title"].str.contains(re.escape(title), case=False, na=False)
                mask_original = df["original_title"].str.contains(re.escape(title), case=False, na=False)
                match = df[mask_title | mask_original]
            if not match.empty:
                like_ids.append(int(match.iloc[0]["tmdb_id"]))
                like_titles.append(str(match.iloc[0]["title"]))

        liked_features = self._liked_features(like_ids)
        df["pref"] = self._pref_score(df, genres, directors, actors)
        df["collab"] = self._collab_score(like_ids)
        df["sim"] = self._sim_score(like_ids)
        df["combo"] = self._combo_score(df, genres, directors, actors, liked_features)

        # 직접 입력한 취향과 작품 품질을 중심으로 두고, 좋아요 피드백은 완만한 보조 신호로 반영한다.
        df["final"] = (
            self._norm(df["pref"]) * 0.42
            + self._norm(df["combo"]) * 0.16
            + self._norm(df["collab"]) * 0.10
            + self._norm(df["sim"]) * 0.10
            + (df["tmdb_score"] / 10) * 0.22
        )

        df = df[df["tmdb_score"] >= min_score]
        if like_ids:
            df = df[~df["tmdb_id"].isin(like_ids)]
        if exclude_tmdb_ids:
            df = df[~df["tmdb_id"].isin([int(x) for x in exclude_tmdb_ids])]

        sequels = self._find_sequels(like_movie_inputs)
        sequel_ids = {s["tmdb_id"] for s in sequels}
        # 시리즈물은 살짝 우대하되 결과를 독점하지 않게 제한한다.
        df.loc[df["tmdb_id"].isin(sequel_ids), "final"] = df.loc[df["tmdb_id"].isin(sequel_ids), "final"] + 0.12

        top = self._diversified_top(df, top_n)
        max_final = float(df["final"].max()) if not df.empty and df["final"].max() > 0 else 1.0
        results = []
        for _, row in top.iterrows():
            seq = next((s for s in sequels if s["tmdb_id"] == row["tmdb_id"]), None)
            best_like = self._best_like_movie_for_row(int(row["tmdb_id"]), like_ids, like_titles)
            reason_items = self._reason_items(row, genres, directors, actors, liked_features, best_like, row["collab"], seq)
            results.append(
                {
                    "tmdb_id": int(row["tmdb_id"]),
                    "title": row["title"],
                    "overview_short": self._overview_short(str(row.get("overview", ""))),
                    "genres": row["genres"],
                    "directors": row["directors"],
                    "actors": row["actors"][:4],
                    "release_date": row["release_date"],
                    "tmdb_score": row["tmdb_score"],
                    "rotten_tomatoes": row["rotten_tomatoes"],
                    "imdb_score": row["imdb_score"],
                    "poster_url": row["poster_url"] or None,
                    "collab_pct": round(row["collab"] * 100, 1),
                    "match_score": round(float(row["final"]) / max_final, 3),
                    "reason": self._reason(row, genres, directors, actors, like_movie_inputs, best_like, row["collab"], seq),
                    "reason_items": reason_items,
                }
            )
        return results

    def _reason_items(self, row, genres, directors, actors, liked_features, best_like, collab, seq):
        items: list[dict[str, str]] = []
        row_genres = row.get("genres") or []
        row_directors = row.get("directors") or []
        row_actors = row.get("actors") or []

        if seq:
            items.append({"icon": "▶", "title": "시리즈 연결", "detail": seq["reason"]})

        matched_genres = [g for g in (genres or []) if self._genre_match(g, row_genres)]
        matched_directors = self._matched_names(directors, row_directors)
        matched_actors = self._matched_names(actors, row_actors)

        if matched_directors and matched_actors:
            items.append(
                {
                    "icon": "＋",
                    "title": "감독 + 배우 결합 매칭",
                    "detail": f"선택한 감독({', '.join(matched_directors[:2])})과 배우({', '.join(matched_actors[:2])})가 함께 반영되어 높은 가중치를 받았습니다.",
                }
            )
        elif matched_directors:
            items.append({"icon": "🎬", "title": "감독 취향 반영", "detail": f"좋아하는 감독 {', '.join(matched_directors[:2])} 조건과 맞습니다."})
        elif matched_actors:
            items.append({"icon": "⭐", "title": "배우 취향 반영", "detail": f"좋아하는 배우 {', '.join(matched_actors[:2])} 조건과 맞습니다."})

        liked_directors = set(liked_features.get("directors", set()))
        liked_actors = set(liked_features.get("actors", set()))
        liked_genres = set(liked_features.get("genres", set()))
        shared_directors = list(set(row_directors) & liked_directors)
        shared_actors = list(set(row_actors[:6]) & liked_actors)
        shared_genres = list(set(row_genres) & liked_genres)
        liked_titles = liked_features.get("titles", [])

        if shared_directors and shared_actors:
            base = f"'{liked_titles[0]}'" if liked_titles else "좋아한 영화"
            items.append(
                {
                    "icon": "👥",
                    "title": "좋아한 영화의 인물 조합과 유사",
                    "detail": f"{base}에서 나타난 감독/배우 조합과 겹치는 요소가 있어, 비슷한 취향군이 함께 선택할 가능성이 높은 영화로 계산했습니다.",
                }
            )
        elif best_like and best_like.get("score", 0) >= 0.15:
            items.append(
                {
                    "icon": "🎞️",
                    "title": "좋아한 영화와 유사",
                    "detail": f"'{best_like['title']}'와 장르·인물·줄거리 벡터가 유사합니다.",
                }
            )

        if matched_genres:
            items.append({"icon": "🎭", "title": "장르 취향 반영", "detail": f"선택한 장르 {', '.join(matched_genres[:3])}와 일치합니다."})
        elif shared_genres and liked_titles:
            items.append({"icon": "🎭", "title": "좋아한 영화의 장르 흐름", "detail": f"좋아한 영화들과 {', '.join(shared_genres[:3])} 장르 흐름이 겹칩니다."})

        if collab >= 0.32:
            items.append(
                {
                    "icon": "📈",
                    "title": "비슷한 취향 패턴",
                    "detail": f"좋아한 영화와 유사한 취향군에서 함께 선호될 확률이 높게 계산됐습니다. 유사도 신호: {round(collab * 100)}%",
                }
            )

        if not items:
            items.append({"icon": "✓", "title": "종합 점수 기반", "detail": "평점, 장르, 인물, 줄거리 유사도를 종합해서 추천했습니다."})
        return items[:5]

    def _reason(self, row, genres, directors, actors, like_movies, best_like, collab, seq):
        return " · ".join(item["title"] for item in self._reason_items(row, genres, directors, actors, self._liked_features([]), best_like, collab, seq)) or "취향 분석 기반"

# -----------------------------------------------------------------------------
# 한 번에 쓰는 함수
# -----------------------------------------------------------------------------


def collect_and_build_db(
    popular_pages: int = 10,
    top_rated_pages: int = 10,
    genres: list[str] | None = None,
    genre_pages: int = 10,
    data_dir: str | Path = "data",
    db_path: str | Path = "data/movies.db",
):
    """영화 수집 → movies.json 저장 → movies.db 저장까지 한 번에 실행."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    collector = MovieCollector(output_dir=data_dir)
    movies = collector.collect_all(
        popular_pages=popular_pages,
        top_rated_pages=top_rated_pages,
        genres=genres,
        genre_pages=genre_pages,
    )
    collector.save(movies, "movies.json")

    db = MovieDB(db_path=db_path)
    db.save_movies(movies)
    print("DB 통계:", db.stats())
    return movies


def recommend_movies(
    genres: list[str] | None = None,
    directors: list[str] | None = None,
    actors: list[str] | None = None,
    like_movies: list[str] | None = None,
    min_score: float = 6.5,
    top_n: int = 4,
    db_path: str | Path = "data/movies.db",
    exclude_tmdb_ids: list[int] | None = None,
):
    engine = RecommendEngine(db_path=db_path).load()
    return engine.recommend(
        genres=genres,
        directors=directors,
        actors=actors,
        like_movies=like_movies,
        min_score=min_score,
        top_n=top_n,
        exclude_tmdb_ids=exclude_tmdb_ids,
    )


def recommend_movies_and_music(
    genres: list[str] | None = None,
    directors: list[str] | None = None,
    actors: list[str] | None = None,
    like_movies: list[str] | None = None,
    min_score: float = 6.5,
    top_n: int = 4,
    db_path: str | Path = "data/movies.db",
    music_limit: int = 5,
    exclude_last: bool = False,
    exclude_tmdb_ids: list[int] | None = None,
    include_external: bool = True,
):
    """영화 추천 결과를 반환한다.

    include_external=False이면 TMDB 예고편/LastFM OST/장르 음악 요청을 건너뛰어
    추천 결과를 먼저 빠르게 보여준다.
    """
    db_key = str(Path(db_path))
    exclude_ids = list(_LAST_RECOMMENDED_BY_DB.get(db_key, []) if exclude_last else [])
    if exclude_tmdb_ids:
        exclude_ids.extend(int(x) for x in exclude_tmdb_ids if str(x).strip())
    exclude_ids = list(dict.fromkeys(exclude_ids))
    movies = recommend_movies(
        genres=genres,
        directors=directors,
        actors=actors,
        like_movies=like_movies,
        min_score=min_score,
        top_n=top_n,
        db_path=db_path,
        exclude_tmdb_ids=exclude_ids,
    )
    # 다음 '다시 추천'을 위해 직전 추천 목록 저장(세션 내) - 누적 방식
    current_excluded = _LAST_RECOMMENDED_BY_DB.get(db_key, [])
    new_movie_ids = [int(m["tmdb_id"]) for m in movies if m.get("tmdb_id") is not None]
    _LAST_RECOMMENDED_BY_DB[db_key] = list(set(current_excluded + new_movie_ids))  # 중복 제거하며 누적

    if not include_external:
        for movie in movies:
            movie["trailer_url"] = None
            movie["soundtracks"] = []
            movie["music_by_genre"] = []
            movie["lazy_external"] = True
        return movies

    lastfm = LastFMClient(strict=False)
    tmdb: TMDBClient | None = None
    try:
        tmdb = TMDBClient()
    except ValueError:
        print("  [trailer] TMDB_API_KEY 없음 — 예고편 링크를 건너뜁니다.")

    for movie in movies:
        movie["trailer_url"] = None
        tid = movie.get("tmdb_id")
        if tmdb and tid is not None:
            try:
                movie["trailer_url"] = fetch_trailer_url(int(tid), tmdb)
            except Exception as e:
                print(f"  [trailer] {movie.get('title')}: {e}")

        try:
            movie["soundtracks"] = lastfm.search_soundtrack(movie["title"], limit=3)
        except Exception as e:
            print(f"⚠️ 음악 검색 중 오류 발생 ({movie['title']}): {e}")
            movie["soundtracks"] = []
        
        try:
            movie["music_by_genre"] = lastfm.recommend_by_genre(movie["genres"], limit=music_limit)
        except Exception as e:
            print(f"⚠️ 장르 기반 음악 추천 중 오류 발생 ({movie['genres']}): {e}")
            movie["music_by_genre"] = []
    return movies


def fetch_movie_external_details(
    title: str,
    genres: list[str] | None = None,
    tmdb_id: int | None = None,
    music_limit: int = 5,
) -> dict[str, Any]:
    """선택한 영화 카드에서 사용자가 원할 때만 외부 세부정보를 불러온다."""
    lastfm = LastFMClient(strict=False)
    trailer_url = None
    if tmdb_id is not None:
        try:
            trailer_url = fetch_trailer_url(int(tmdb_id))
        except Exception as e:
            print(f"  [trailer lazy] {title}: {e}")
    try:
        soundtracks = lastfm.search_soundtrack(title, limit=3) if title else []
    except Exception as e:
        print(f"⚠️ Lazy OST 검색 오류({title}): {e}")
        soundtracks = []
    try:
        music_by_genre = lastfm.recommend_by_genre(genres or [], limit=music_limit) if genres else []
    except Exception as e:
        print(f"⚠️ Lazy 장르 음악 검색 오류({genres}): {e}")
        music_by_genre = []
    return {
        "trailer_url": trailer_url,
        "soundtracks": soundtracks,
        "music_by_genre": music_by_genre,
    }


def lookup_music_cover(track_name: str, artist_name: str = "", album_name: str = "") -> dict[str, str]:
    """추천 카드를 먼저 보여준 뒤 앨범 커버만 지연 로딩할 때 사용한다."""
    info: dict[str, str] = {}
    try:
        lastfm = LastFMClient(strict=False)
        if lastfm.api_key and track_name and artist_name:
            info = _lfm_track_album_art(lastfm, track_name, artist_name)
    except Exception as e:
        print(f"⚠️ LastFM 커버 지연 로딩 오류({track_name}, {artist_name}): {e}")
        info = {}
    if info.get("image_url"):
        info["cover_source"] = "LastFM"
        return info
    try:
        return _best_album_art(track_name, artist_name, album_name)
    except Exception as e:
        print(f"⚠️ 외부 커버 지연 로딩 오류({track_name}, {artist_name}): {e}")
        return {}


def chat_recommend(
    message: str,
    genres: list[str] | None = None,
    directors: list[str] | None = None,
    actors: list[str] | None = None,
    like_movies: list[str] | None = None,
    min_score: float = 6.5,
    top_n: int = 4,
    db_path: str | Path = "data/movies.db",
    music_limit: int = 5,
):
    """
    간단 챗봇용 라우터.
    - message에 '다시 추천'이 포함되면: 직전 추천을 제외하고 새로 추천
    - 그 외에는: 직전 추천 제외 없이(=처음 추천) 추천
    """
    msg = (message or "").strip()
    is_retry = bool(re.search(r"다시\\s*추천", msg))
    return recommend_movies_and_music(
        genres=genres,
        directors=directors,
        actors=actors,
        like_movies=like_movies,
        min_score=min_score,
        top_n=top_n,
        db_path=db_path,
        music_limit=music_limit,
        exclude_last=is_retry,
    )


def print_recommendations_with_emoji(results: list[dict[str, Any]]):
    """주피터 노트북 전용 이모티콘 출력 함수"""
    for i, movie in enumerate(results, 1):
        title = movie.get("title", "")
        release = movie.get("release_date", "")
        genres = ", ".join(movie.get("genres", []) or []) or "N/A"
        directors = ", ".join((movie.get("directors", []) or [])[:2]) or "N/A"
        actors = ", ".join((movie.get("actors", []) or [])[:3]) or "N/A"
        overview = (movie.get("overview_short") or "").strip()
        reason = movie.get("reason", "")

        # 주피터에서는 이모티콘 직접 출력
        print("\n" + "═" * 88)
        print(f"🎬 [{i}] {title}  ({release})")
        if overview:
            print(f"📝 줄거리: {overview}")
        print(f"🎭 장르: {genres}")
        print(f"🎬 감독: {directors}")
        print(f"⭐ 배우: {actors}")

        tmdb = movie.get("tmdb_score")
        imdb = movie.get("imdb_score")
        rt = movie.get("rotten_tomatoes")
        print(f"📊 평점: TMDB {tmdb} | IMDb {imdb} | RT {rt}")

        if reason:
            print(f"💡 추천 이유: {reason}")

        poster = movie.get("poster_url")
        if poster:
            print(f"🖼️ 포스터: {poster}")

        soundtracks = movie.get("soundtracks") or []
        if soundtracks:
            print("\n🎬 사운드트랙")
            for s in soundtracks[:3]:
                name = s.get("name", "")
                artist = s.get("artist", "")
                try:
                    print(f"  - {name} / {artist}")
                except UnicodeEncodeError:
                    safe_name = name.encode('cp949', errors='ignore').decode('cp949')
                    safe_artist = artist.encode('cp949', errors='ignore').decode('cp949')
                    print(f"  - {safe_name} / {safe_artist}")

        tracks = movie.get("music_by_genre") or []
        if tracks:
            print("\n🎶 장르 기반 음악")
            for t in tracks[:5]:
                name = t.get("name", "")
                artist = t.get("artist", "")
                tag = t.get("tag", "")
                try:
                    print(f"  - {name} / {artist}  [{tag}]")
                except UnicodeEncodeError:
                    safe_name = name.encode('cp949', errors='ignore').decode('cp949')
                    safe_artist = artist.encode('cp949', errors='ignore').decode('cp949')
                    safe_tag = tag.encode('cp949', errors='ignore').decode('cp949')
                    print(f"  - {safe_name} / {safe_artist}  [{safe_tag}]")
    print("\n" + "═" * 88)


def print_recommendations(results: list[dict[str, Any]]):
    for i, movie in enumerate(results, 1):
        title = movie.get("title", "")
        release = movie.get("release_date", "")
        genres = ", ".join(movie.get("genres", []) or []) or "N/A"
        directors = ", ".join((movie.get("directors", []) or [])[:2]) or "N/A"
        actors = ", ".join((movie.get("actors", []) or [])[:3]) or "N/A"
        overview = (movie.get("overview_short") or "").strip()
        reason = movie.get("reason", "")

        emoji_print("\n" + "═" * 88)
        emoji_print(f"🎬 [{i}] {title}  ({release})")
        if overview:
            emoji_print(f"📝 줄거리: {overview}")
        emoji_print(f"🎭 장르: {genres}")
        emoji_print(f"🎬 감독: {directors}")
        emoji_print(f"⭐ 배우: {actors}")

        tmdb = movie.get("tmdb_score")
        imdb = movie.get("imdb_score")
        rt = movie.get("rotten_tomatoes")
        emoji_print(f"📊 평점: TMDB {tmdb} | IMDb {imdb} | RT {rt}")

        if reason:
            emoji_print(f"💡 추천 이유: {reason}")

        poster = movie.get("poster_url")
        if poster:
            emoji_print(f"🖼️ 포스터: {poster}")

        soundtracks = movie.get("soundtracks") or []
        if soundtracks:
            emoji_print("\n🎬 사운드트랙")
            for s in soundtracks[:3]:
                name = s.get("name", "")
                artist = s.get("artist", "")
                try:
                    print(f"  - {name} / {artist}")
                except UnicodeEncodeError:
                    safe_name = name.encode('cp949', errors='ignore').decode('cp949')
                    safe_artist = artist.encode('cp949', errors='ignore').decode('cp949')
                    print(f"  - {safe_name} / {safe_artist}")

        tracks = movie.get("music_by_genre") or []
        if tracks:
            emoji_print("\n🎶 장르 기반 음악")
            for t in tracks[:5]:
                name = t.get("name", "")
                artist = t.get("artist", "")
                tag = t.get("tag", "")
                try:
                    print(f"  - {name} / {artist}  [{tag}]")
                except UnicodeEncodeError:
                    safe_name = name.encode('cp949', errors='ignore').decode('cp949')
                    safe_artist = artist.encode('cp949', errors='ignore').decode('cp949')
                    safe_tag = tag.encode('cp949', errors='ignore').decode('cp949')
                    print(f"  - {safe_name} / {safe_artist}  [{safe_tag}]")
    emoji_print("\n" + "═" * 88)

# -----------------------------------------------------------------------------
# CLI 실행
# -----------------------------------------------------------------------------


def _split_arg(value: str | None):
    if not value:
        return []
    return [x.strip() for x in value.split(",") if x.strip()]


def test_notebook_emoji():
    """주피터 노트북에서 이모티콘 테스트"""
    print("=== 주피터 노트북 이모티콘 테스트 ===")
    
    # 환경 확인
    import sys
    is_notebook = (
        'ipykernel' in sys.modules or 
        'IPython' in sys.modules or
        hasattr(sys.modules.get('builtins', {}), '__IPYTHON__')
    )
    print(f"주피터 노트북 환경: {is_notebook}")
    
    # 이모티콘 직접 출력 테스트
    print("\n🎬 영화 테스트")
    print("📝 줄거리 테스트")
    print("🎭 장르 테스트")
    print("⭐ 배우 테스트")
    print("📊 평점 테스트")
    print("💡 추천 이유 테스트")
    print("🖼️ 포스터 테스트")
    print("🎬 사운드트랙 테스트")
    print("🎶 장르 기반 음악 테스트")
    
    # 추천 테스트
    print("\n=== 추천 테스트 ===")
    try:
        results = recommend_movies_and_music(
            genres=["SF"],
            directors=[],
            actors=[],
            like_movies=["Inception"],
            min_score=7.0,
            top_n=1,
            db_path="data/movies.db",
            exclude_last=False
        )
        print_recommendations_with_emoji(results)
        
        print("\n=== 재추천 테스트 ===")
        results2 = recommend_movies_and_music(
            genres=["SF"],
            directors=[],
            actors=[],
            like_movies=["Inception"],
            min_score=7.0,
            top_n=1,
            db_path="data/movies.db",
            exclude_last=True  # 이전 추천 제외
        )
        print_recommendations_with_emoji(results2)
        
    except Exception as e:
        print(f"오류 발생: {e}")



# -----------------------------------------------------------------------------
# 웹앱 전용: 일반 음악 추천
# -----------------------------------------------------------------------------

def _lfm_image(obj: dict[str, Any] | None) -> str | None:
    if not obj:
        return None
    images = obj.get("image", []) or []
    return _usable_image_url(next((img.get("#text") for img in reversed(images) if img.get("#text")), "")) or None


def _usable_image_url(url: str | None) -> str:
    url = str(url or "").strip()
    if not url:
        return ""
    # LastFM occasionally returns an empty/default placeholder. Treat that as missing.
    lowered = url.lower()
    if "2a96cbd8b46e442fc41c2b86b821562f" in lowered or "default_album" in lowered:
        return ""
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        return ""
    return url


def _lfm_artist_name(artist_obj: Any) -> str:
    if isinstance(artist_obj, dict):
        return artist_obj.get("name", "") or artist_obj.get("#text", "") or ""
    return str(artist_obj or "")


def _lfm_track_album_art(lastfm: LastFMClient, track_name: str, artist_name: str) -> dict[str, str]:
    """곡 정보에서 앨범 커버를 보강한다.

    LastFM의 top tracks/search 응답은 image 필드가 비어 오는 경우가 많아서,
    결과 카드 표시 직전에 track.getInfo를 한 번 더 조회해 앨범 이미지를 채운다.
    """
    track_name = str(track_name or "").strip()
    artist_name = str(artist_name or "").strip()
    if not track_name or not artist_name:
        return {}
    try:
        info = lastfm._get("track.getInfo", {"track": track_name, "artist": artist_name, "autocorrect": 1})
        track = info.get("track", {}) if isinstance(info, dict) else {}
        album = track.get("album", {}) if isinstance(track, dict) else {}
        image_url = _lfm_image(album) or _lfm_image(track)
        album_name = album.get("title", "") if isinstance(album, dict) else ""
        return {
            "image_url": image_url or "",
            "album_name": album_name or "",
        }
    except Exception:
        return {}




def _itunes_album_art(track_name: str, artist_name: str = "", album_name: str = "") -> dict[str, str]:
    """LastFM이 앨범 커버를 주지 않을 때 iTunes Search API로 커버를 보강한다."""
    terms = []
    for term in [f"{artist_name} {track_name}", f"{artist_name} {album_name}", f"{track_name} {album_name}", track_name, album_name]:
        term = str(term or "").strip()
        if term and term not in terms:
            terms.append(term)

    # KR을 먼저 두어 K-pop/한국어 입력 커버 매칭률을 높이고, US/JP도 순차 보완한다.
    for country in ["KR", "US", "JP"]:
        for entity in ["song", "album"]:
            for term in terms[:5]:
                try:
                    resp = requests.get(
                        "https://itunes.apple.com/search",
                        params={"term": term, "media": "music", "entity": entity, "limit": 8, "country": country},
                        timeout=6,
                    )
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    for result in data.get("results", []):
                        artwork = _usable_image_url(result.get("artworkUrl100") or result.get("artworkUrl60") or "")
                        if not artwork:
                            continue
                        artwork = artwork.replace("100x100bb", "600x600bb").replace("100x100", "600x600").replace("60x60bb", "600x600bb")
                        return {
                            "image_url": artwork,
                            "album_name": result.get("collectionName", "") or album_name or "",
                            "cover_source": f"iTunes {country}",
                        }
                except Exception:
                    continue
    return {}


def _deezer_album_art(track_name: str, artist_name: str = "", album_name: str = "") -> dict[str, str]:
    """API 키 없이 사용할 수 있는 Deezer 검색으로 앨범 커버를 추가 보강한다."""
    queries = []
    if artist_name and track_name:
        queries.append(f'artist:"{artist_name}" track:"{track_name}"')
    if artist_name and album_name:
        queries.append(f'artist:"{artist_name}" album:"{album_name}"')
    for term in [f"{artist_name} {track_name}", f"{artist_name} {album_name}", track_name, album_name]:
        term = str(term or "").strip()
        if term:
            queries.append(term)

    seen = set()
    for query in queries[:6]:
        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            resp = requests.get("https://api.deezer.com/search", params={"q": query, "limit": 6}, timeout=6)
            if resp.status_code != 200:
                continue
            data = resp.json()
            for result in data.get("data", []) or []:
                album = result.get("album", {}) if isinstance(result, dict) else {}
                artwork = _usable_image_url(album.get("cover_xl") or album.get("cover_big") or album.get("cover_medium") or "")
                if not artwork:
                    continue
                return {
                    "image_url": artwork,
                    "album_name": album.get("title", "") or album_name or "",
                    "cover_source": "Deezer",
                }
        except Exception:
            continue
    return {}


def _best_album_art(track_name: str, artist_name: str = "", album_name: str = "") -> dict[str, str]:
    """여러 공개 음악 검색 API를 순차 사용해 커버 URL을 최대한 확보한다."""
    for finder in (_itunes_album_art, _deezer_album_art):
        info = finder(track_name, artist_name, album_name)
        if info.get("image_url"):
            return info
    return {}

def _music_genre_to_tags(genres: list[str] | None) -> list[str]:
    mapping = {
        "케이팝": "k-pop", "kpop": "k-pop", "k-pop": "k-pop",
        "팝": "pop", "pop": "pop",
        "락": "rock", "록": "rock", "rock": "rock",
        "인디": "indie", "indie": "indie",
        "힙합": "hip-hop", "hiphop": "hip-hop", "hip-hop": "hip-hop", "rap": "rap",
        "알앤비": "rnb", "r&b": "rnb", "rnb": "rnb",
        "재즈": "jazz", "jazz": "jazz",
        "일렉": "electronic", "일렉트로닉": "electronic", "전자음악": "electronic", "electronic": "electronic",
        "클래식": "classical", "classical": "classical",
        "OST": "soundtrack", "ost": "soundtrack", "사운드트랙": "soundtrack", "오리지널사운드트랙": "soundtrack", "soundtrack": "soundtrack",
        "시티팝": "city pop", "city pop": "city pop",
        "발라드": "ballad", "ballad": "ballad",
        "어쿠스틱": "acoustic", "acoustic": "acoustic",
        "로파이": "lo-fi", "lo-fi": "lo-fi", "lofi": "lo-fi",
        "앰비언트": "ambient", "ambient": "ambient",
        "신스웨이브": "synthwave", "synthwave": "synthwave",
        "댄스": "dance", "dance": "dance",
        "소울": "soul", "soul": "soul",
        "포크": "folk", "folk": "folk",
        "메탈": "metal", "metal": "metal",
    }
    tags: list[str] = []
    for g in genres or []:
        raw = str(g).strip()
        key = raw.lower()
        tag = mapping.get(key) or mapping.get(raw) or raw
        if tag and tag not in tags:
            tags.append(tag)
    return tags


MUSIC_GENRE_OPTIONS = [
    "케이팝", "팝", "록", "인디", "힙합", "알앤비", "재즈", "일렉트로닉",
    "신스웨이브", "앰비언트", "클래식", "사운드트랙", "로파이", "발라드",
    "어쿠스틱", "포크", "소울", "댄스", "메탈", "시티팝"
]

MUSIC_QUERY_ALIASES = {
    "아이유": "IU", "이지은": "IU", "뉴진스": "NewJeans", "방탄": "BTS", "방탄소년단": "BTS", "비티에스": "BTS",
    "블랙핑크": "BLACKPINK", "르세라핌": "LE SSERAFIM", "아이브": "IVE", "에스파": "aespa",
    "소녀시대": "Girls' Generation", "태연": "Taeyeon", "트와이스": "TWICE", "세븐틴": "SEVENTEEN",
    "찰리푸스": "Charlie Puth", "테일러": "Taylor Swift", "테일러스위프트": "Taylor Swift",
    "위켄드": "The Weeknd", "브루노마스": "Bruno Mars", "아리아나": "Ariana Grande",
    "아델": "Adele", "콜드플레이": "Coldplay", "라디오헤드": "Radiohead",
}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _expand_music_queries(values: list[str] | None) -> list[str]:
    expanded: list[str] = []
    for v in values or []:
        raw = str(v).strip()
        if not raw:
            continue
        aliases = [raw]
        alias = MUSIC_QUERY_ALIASES.get(raw) or MUSIC_QUERY_ALIASES.get(raw.replace(" ", "")) or MUSIC_QUERY_ALIASES.get(raw.lower())
        if alias:
            aliases.append(alias)
        for item in aliases:
            if item and item not in expanded:
                expanded.append(item)
    return expanded


def _lastfm_track_items(data: dict[str, Any], path: str) -> list[dict[str, Any]]:
    cur: Any = data
    for key in path.split("."):
        if not isinstance(cur, dict):
            return []
        cur = cur.get(key, {})
    return _as_list(cur)


def suggest_music_items(kind: str = "artist", query: str = "", limit: int = 12):
    """음악 입력 자동완성. LastFM 검색이 실패해도 빈 결과로 안전하게 반환한다."""
    query = str(query or "").strip()
    kind = (kind or "artist").lower()
    if not query:
        return {"results": []}

    if kind == "genre":
        q = query.lower().replace(" ", "")
        results = [g for g in MUSIC_GENRE_OPTIONS if q in g.lower().replace(" ", "")][:limit]
        return {"results": [{"value": g, "label": g, "sub": "장르"} for g in results]}

    lastfm = LastFMClient(strict=False)
    if not lastfm.api_key:
        return {"results": [], "api_key_missing": True}

    try:
        if kind == "artist":
            queries = _expand_music_queries([query])
            results = []
            seen = set()
            for q in queries:
                data = lastfm._get("artist.search", {"artist": q, "limit": limit})
                artists = _as_list(data.get("results", {}).get("artistmatches", {}).get("artist", []))
                for a in artists[:limit]:
                    name = a.get("name", "")
                    if not name or name.lower() in seen:
                        continue
                    seen.add(name.lower())
                    listeners = a.get("listeners")
                    sub = f"아티스트 · listeners {listeners}" if listeners else "아티스트"
                    results.append({"value": name, "label": name, "sub": sub})
            return {"results": results[:limit]}

        if kind == "track":
            queries = _expand_music_queries([query])
            results = []
            seen = set()
            for q in queries:
                data = lastfm._get("track.search", {"track": q, "limit": limit})
                tracks = _as_list(data.get("results", {}).get("trackmatches", {}).get("track", []))
                for t in tracks[:limit]:
                    name = t.get("name", "")
                    artist = _lfm_artist_name(t.get("artist"))
                    key = (name.lower(), artist.lower())
                    if not name or key in seen:
                        continue
                    seen.add(key)
                    results.append({"value": name, "label": name, "sub": artist or "노래"})
            return {"results": results[:limit]}

        if kind == "album":
            queries = _expand_music_queries([query])
            results = []
            seen = set()
            for q in queries:
                data = lastfm._get("album.search", {"album": q, "limit": limit})
                albums = _as_list(data.get("results", {}).get("albummatches", {}).get("album", []))
                for a in albums[:limit]:
                    name = a.get("name", "")
                    artist = a.get("artist", "")
                    key = (name.lower(), artist.lower())
                    if not name or key in seen:
                        continue
                    seen.add(key)
                    results.append({"value": name, "label": name, "sub": artist or "앨범"})
            return {"results": results[:limit]}
    except Exception as e:
        return {"results": [], "error": str(e)}

    return {"results": []}


def _recent_unique_music_queries(values: list[str] | None, limit: int = 3) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in reversed(values or []):
        text = str(raw or "").strip()
        key = re.sub(r"\s+", " ", text.lower())
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return list(reversed(result))


def recommend_music_by_taste(
    genres: list[str] | None = None,
    artists: list[str] | None = None,
    tracks: list[str] | None = None,
    albums: list[str] | None = None,
    top_n: int = 12,
    offset: int = 0,
    exclude_track_keys: list[str] | None = None,
    fast: bool = True,
    include_cover_art: bool = False,
):
    """LastFM 기반 일반 음악 추천.

    입력된 장르, 아티스트, 좋아하는 노래, 좋아하는 앨범을 각각 신호로 보고
    중복 후보를 합산 점수화한 뒤 추천 이유와 함께 반환한다.
    """
    lastfm = LastFMClient(strict=False)
    if not lastfm.api_key:
        return {
            "api_key_missing": True,
            "message": "LASTFM_API_KEY가 .env에 없어서 음악 추천을 불러오지 못했습니다.",
            "results": [],
        }

    candidates: dict[tuple[str, str], dict[str, Any]] = {}
    # 빠른 모드에서는 추천 후보 계산에 필요한 핵심 API만 호출하고,
    # 앨범 커버/확장 유사 아티스트 탐색은 결과 표시 뒤 지연 로딩한다.
    tag_limit = 2 if fast else 5
    expanded_limit = 2 if fast else 999

    # 누적된 좋아요 노래가 전체 추천을 지배하지 않도록 최근 선호만 반영한다.
    tracks = _recent_unique_music_queries(tracks, limit=3)

    def make_track_key(name: str, artist: str = "") -> str:
        def clean(value: str) -> str:
            return re.sub(r"\s+", " ", str(value or "").strip().lower())
        return f"{clean(name)}::{clean(artist)}"

    exclude_key_set = {str(x or "").strip().lower() for x in (exclude_track_keys or []) if str(x or "").strip()}
    exclude_name_set = {key.split("::", 1)[0] for key in exclude_key_set if "::" in key}

    def is_excluded_track(item: dict[str, Any]) -> bool:
        key = make_track_key(item.get("name", ""), item.get("artist", ""))
        name_key = key.split("::", 1)[0]
        return key in exclude_key_set or name_key in exclude_name_set

    def add_track(name: str, artist: str = "", image_url: str | None = None, url: str = "", score: float = 1.0, reason: str = "취향 기반 추천", source: str = "", album_name: str = ""):
        name = (name or "").strip()
        artist = (artist or "").strip()
        if not name:
            return
        key = (name.lower(), artist.lower())
        item = candidates.setdefault(
            key,
            {
                "name": name,
                "artist": artist,
                "image_url": image_url,
                "lastfm_url": url,
                "album_name": album_name,
                "score": 0.0,
                "reason_items": [],
                "sources": [],
            },
        )
        item["score"] += float(score)
        if image_url and not item.get("image_url"):
            item["image_url"] = image_url
        if url and not item.get("lastfm_url"):
            item["lastfm_url"] = url
        if artist and not item.get("artist"):
            item["artist"] = artist
        if album_name and not item.get("album_name"):
            item["album_name"] = album_name
        if reason and reason not in [r.get("detail") for r in item["reason_items"]]:
            item["reason_items"].append({"title": source or "추천 근거", "detail": reason})
        if source and source not in item["sources"]:
            item["sources"].append(source)

    # 1) 장르 기반: LastFM 태그 인기곡
    tags = _music_genre_to_tags(genres)
    for tag in tags[:tag_limit]:
        try:
            data = lastfm._get("tag.getTopTracks", {"tag": tag, "limit": max(6, min(top_n * 2, 18))})
            for t in data.get("tracks", {}).get("track", []):
                artist = _lfm_artist_name(t.get("artist"))
                add_track(
                    t.get("name", ""), artist, _lfm_image(t), t.get("url", ""),
                    score=1.2,
                    source="장르 취향",
                    reason=f"선택한 장르/무드 '{tag}'에서 많이 추천되는 곡입니다.",
                )
        except Exception as e:
            print(f"⚠️ 장르 음악 추천 오류({tag}): {e}")

    # 2) 아티스트 기반: 선호 아티스트 인기곡 + 유사 아티스트 인기곡
    for artist_name in _expand_music_queries(artists)[:expanded_limit]:
        artist_name = str(artist_name).strip()
        if not artist_name:
            continue
        try:
            data = lastfm._get("artist.getTopTracks", {"artist": artist_name, "limit": max(6, min(top_n, 10))})
            for t in data.get("toptracks", {}).get("track", []):
                artist = _lfm_artist_name(t.get("artist")) or artist_name
                add_track(
                    t.get("name", ""), artist, _lfm_image(t), t.get("url", ""),
                    score=1.45,
                    source="아티스트 취향",
                    reason=f"좋아하는 아티스트 '{artist_name}'의 대표곡 흐름과 맞습니다.",
                )
        except Exception as e:
            print(f"⚠️ 아티스트 인기곡 오류({artist_name}): {e}")

        if fast:
            continue

        try:
            data = lastfm._get("artist.getSimilar", {"artist": artist_name, "limit": 5})
            for sim in data.get("similarartists", {}).get("artist", []):
                sim_name = sim.get("name", "")
                if not sim_name:
                    continue
                top = lastfm._get("artist.getTopTracks", {"artist": sim_name, "limit": 3})
                for t in top.get("toptracks", {}).get("track", []):
                    artist = _lfm_artist_name(t.get("artist")) or sim_name
                    add_track(
                        t.get("name", ""), artist, _lfm_image(t), t.get("url", ""),
                        score=1.5,
                        source="유사 아티스트",
                        reason=f"'{artist_name}'와 비슷하게 들은 아티스트 '{sim_name}'의 곡입니다.",
                    )
        except Exception as e:
            print(f"⚠️ 유사 아티스트 추천 오류({artist_name}): {e}")

    # 3) 좋아하는 노래 기반: 검색 후 유사곡
    for track_query in _expand_music_queries(tracks)[:expanded_limit]:
        track_query = str(track_query).strip()
        if not track_query:
            continue
        try:
            found = lastfm._get("track.search", {"track": track_query, "limit": 3})
            matches = found.get("results", {}).get("trackmatches", {}).get("track", [])
            if isinstance(matches, dict):
                matches = [matches]
            for m in matches[:2]:
                base_track = m.get("name", track_query)
                base_artist = _lfm_artist_name(m.get("artist"))
                add_track(
                    base_track, base_artist, _lfm_image(m), m.get("url", ""),
                    score=0.55,
                    source="좋아하는 노래",
                    reason=f"입력한 좋아하는 노래 '{track_query}'와 직접 연결된 곡입니다.",
                )
                if base_artist:
                    similar = lastfm._get("track.getSimilar", {"track": base_track, "artist": base_artist, "limit": max(5, top_n)})
                    for t in similar.get("similartracks", {}).get("track", []):
                        artist = _lfm_artist_name(t.get("artist"))
                        add_track(
                            t.get("name", ""), artist, _lfm_image(t), t.get("url", ""),
                            score=1.10,
                            source="노래 유사도",
                            reason=f"좋아하는 노래 '{base_track}'와 청취 패턴이 유사한 곡입니다.",
                        )
        except Exception as e:
            print(f"⚠️ 노래 기반 추천 오류({track_query}): {e}")

    # 4) 앨범 기반: 앨범 검색 → 해당 아티스트 인기곡/앨범 수록곡 일부
    for album_query in _expand_music_queries(albums)[:expanded_limit]:
        album_query = str(album_query).strip()
        if not album_query:
            continue
        try:
            found = lastfm._get("album.search", {"album": album_query, "limit": 3})
            matches = found.get("results", {}).get("albummatches", {}).get("album", [])
            if isinstance(matches, dict):
                matches = [matches]
            for album in matches[:2]:
                album_name = album.get("name", album_query)
                album_artist = album.get("artist", "")
                image_url = _lfm_image(album)
                if album_artist:
                    top = lastfm._get("artist.getTopTracks", {"artist": album_artist, "limit": 5})
                    for t in top.get("toptracks", {}).get("track", []):
                        artist = _lfm_artist_name(t.get("artist")) or album_artist
                        add_track(
                            t.get("name", ""), artist, _lfm_image(t) or image_url, t.get("url", ""),
                            score=1.05,
                            source="앨범 취향",
                            reason=f"좋아하는 앨범 '{album_name}'의 아티스트 '{album_artist}' 흐름과 맞습니다.",
                            album_name=album_name,
                        )
                if fast:
                    continue
                try:
                    info = lastfm._get("album.getInfo", {"album": album_name, "artist": album_artist}) if album_artist else {}
                    album_tracks = info.get("album", {}).get("tracks", {}).get("track", [])
                    if isinstance(album_tracks, dict):
                        album_tracks = [album_tracks]
                    for t in album_tracks[:4]:
                        artist = _lfm_artist_name(t.get("artist")) or album_artist
                        add_track(
                            t.get("name", ""), artist, image_url, t.get("url", ""),
                            score=1.0,
                            source="앨범 수록곡",
                            reason=f"좋아하는 앨범 '{album_name}'의 수록곡입니다.",
                            album_name=album_name,
                        )
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️ 앨범 기반 추천 오류({album_query}): {e}")

    # 5) 하나만 입력해도 결과가 나오도록 보완 검색
    #    - 아티스트/곡/앨범명이 정확하지 않아도 search API로 먼저 후보를 찾음
    #    - 그래도 없으면 인기곡으로 최소 결과를 보장함
    if not candidates:
        # 아티스트명을 정확히 모를 때: artist.search → 상위 후보의 대표곡
        for raw_artist in _expand_music_queries(artists):
            try:
                found = lastfm._get("artist.search", {"artist": raw_artist, "limit": 4})
                artist_matches = _as_list(found.get("results", {}).get("artistmatches", {}).get("artist", []))
                for a in artist_matches[:3]:
                    resolved = a.get("name", "")
                    if not resolved:
                        continue
                    top = lastfm._get("artist.getTopTracks", {"artist": resolved, "limit": max(6, top_n)})
                    for t in top.get("toptracks", {}).get("track", []):
                        artist = _lfm_artist_name(t.get("artist")) or resolved
                        add_track(
                            t.get("name", ""), artist, _lfm_image(t), t.get("url", ""),
                            score=1.25,
                            source="아티스트 검색 보완",
                            reason=f"입력한 아티스트 '{raw_artist}'와 가장 가까운 후보 '{resolved}'의 대표곡입니다.",
                        )
            except Exception as e:
                print(f"⚠️ 아티스트 보완 검색 오류({raw_artist}): {e}")

    if not candidates:
        # 곡/앨범/아티스트/장르 어느 하나만 애매하게 입력해도 track.search로 후보 확보
        loose_terms = []
        loose_terms.extend(_expand_music_queries(tracks))
        loose_terms.extend(_expand_music_queries(albums))
        loose_terms.extend(_expand_music_queries(artists))
        loose_terms.extend(tags)
        for term in loose_terms[:3 if fast else 8]:
            try:
                found = lastfm._get("track.search", {"track": term, "limit": max(6, top_n)})
                matches = _as_list(found.get("results", {}).get("trackmatches", {}).get("track", []))
                for t in matches:
                    artist = _lfm_artist_name(t.get("artist"))
                    add_track(
                        t.get("name", ""), artist, _lfm_image(t), t.get("url", ""),
                        score=1.1,
                        source="완화 검색",
                        reason=f"입력한 단어 '{term}'와 연결되는 LastFM 검색 결과입니다.",
                    )
            except Exception as e:
                print(f"⚠️ 완화 검색 오류({term}): {e}")

    if not candidates:
        # 마지막 안전장치: 완전히 빈 화면 대신 LastFM 인기곡으로 보완
        try:
            chart = lastfm._get("chart.getTopTracks", {"limit": max(8, top_n)})
            for t in chart.get("tracks", {}).get("track", []):
                artist = _lfm_artist_name(t.get("artist"))
                add_track(
                    t.get("name", ""), artist, _lfm_image(t), t.get("url", ""),
                    score=0.7,
                    source="인기곡 보완",
                    reason="입력 조건과 직접 일치하는 후보가 부족해 전체 인기곡으로 추천을 보완했습니다.",
                )
        except Exception as e:
            print(f"⚠️ 인기곡 보완 오류: {e}")

    ranked = sorted(candidates.values(), key=lambda x: x.get("score", 0), reverse=True)
    if exclude_key_set:
        ranked = [item for item in ranked if not is_excluded_track(item)]

    def diversify_ranked(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        remaining = list(items)
        diversified: list[dict[str, Any]] = []
        while remaining:
            best_idx = 0
            best_adjusted = None
            used_artists = {str(x.get("artist", "")).lower() for x in diversified if x.get("artist")}
            used_sources = {src for x in diversified for src in (x.get("sources") or [])}
            for i, item in enumerate(remaining):
                adjusted = float(item.get("score", 0.0))
                artist_key = str(item.get("artist", "")).lower()
                if artist_key and artist_key in used_artists:
                    adjusted -= 0.65
                source_overlap = len(set(item.get("sources") or []) & used_sources)
                adjusted -= source_overlap * 0.15
                if best_adjusted is None or adjusted > best_adjusted:
                    best_adjusted = adjusted
                    best_idx = i
            diversified.append(remaining.pop(best_idx))
        return diversified

    ranked = diversify_ranked(ranked)
    max_score = max((item.get("score", 0) for item in ranked), default=1.0)

    # 다른 추천받기: 같은 조건에서 다음 묶음을 보여준다. 후보가 부족하면 앞쪽으로 순환한다.
    limit = max(1, int(top_n))
    if ranked:
        start = max(0, int(offset or 0)) % len(ranked)
        selected = ranked[start:start + limit]
        if len(selected) < limit and len(ranked) > len(selected):
            selected += ranked[:limit - len(selected)]
    else:
        selected = []

    results = []
    cover_cache: dict[tuple[str, str], dict[str, str]] = {}
    cover_api_cache: dict[tuple[str, str, str], dict[str, str]] = {}
    for item in selected:
        image_url = item.get("image_url") or ""
        album_name = item.get("album_name") or ""
        cover_source = "LastFM" if image_url else ""

        if include_cover_art:
            cover_info: dict[str, str] = {}
            if item.get("artist"):
                cache_key = (str(item.get("name", "")).lower(), str(item.get("artist", "")).lower())
                cover_info = cover_cache.setdefault(
                    cache_key,
                    _lfm_track_album_art(lastfm, item.get("name", ""), item.get("artist", "")),
                )
            image_url = image_url or cover_info.get("image_url")
            album_name = album_name or cover_info.get("album_name", "")
            cover_source = "LastFM" if image_url else ""
            if not image_url:
                api_key = (str(item.get("name", "")).lower(), str(item.get("artist", "")).lower(), str(album_name).lower())
                api_info = cover_api_cache.setdefault(
                    api_key,
                    _best_album_art(item.get("name", ""), item.get("artist", ""), album_name),
                )
                image_url = api_info.get("image_url") or image_url
                album_name = album_name or api_info.get("album_name", "")
                cover_source = api_info.get("cover_source", "") if image_url else ""

        results.append(
            {
                "name": item["name"],
                "artist": item.get("artist", ""),
                "album_name": album_name,
                "image_url": image_url,
                "lastfm_url": item.get("lastfm_url", ""),
                "cover_source": cover_source,
                "match_score": round(item.get("score", 0) / max_score, 3),
                "reason_items": item.get("reason_items", [])[:4],
                "sources": item.get("sources", [])[:4],
            }
        )

    if not results:
        return {
            "api_key_missing": False,
            "message": "음악 추천 결과를 찾지 못했습니다. API 키 상태를 확인하거나 다른 단어로 한 번 더 입력해보세요.",
            "results": [],
        }

    return {"api_key_missing": False, "message": f"{len(results)}개의 음악 추천 결과를 찾았습니다.", "results": results}


def main():
    parser = argparse.ArgumentParser(description="영화 추천 + 음악 추천 통합 실행 파일")
    sub = parser.add_subparsers(dest="command")

    p_collect = sub.add_parser("collect", help="영화 수집 후 DB 저장")
    p_collect.add_argument("--popular-pages", type=int, default=10)
    p_collect.add_argument("--top-rated-pages", type=int, default=10)
    p_collect.add_argument("--genres", type=str, default="액션,드라마,SF,스릴러,코미디")
    p_collect.add_argument("--genre-pages", type=int, default=10, help="장르별 discover 수집 페이지 수(기본 10)")
    p_collect.add_argument("--data-dir", type=str, default="data")
    p_collect.add_argument("--db-path", type=str, default="data/movies.db")

    p_rec = sub.add_parser("recommend", help="영화 + 음악 추천")
    p_rec.add_argument("--genres", type=str, default="SF,스릴러")
    p_rec.add_argument("--directors", type=str, default="Christopher Nolan")
    p_rec.add_argument("--actors", type=str, default="Leonardo DiCaprio")
    p_rec.add_argument("--like-movies", type=str, default="Inception,Interstellar")
    p_rec.add_argument("--min-score", type=float, default=6.5)
    p_rec.add_argument("--top-n", type=int, default=4)
    p_rec.add_argument("--db-path", type=str, default="data/movies.db")

    args = parser.parse_args()

    if args.command == "collect":
        collect_and_build_db(
            popular_pages=args.popular_pages,
            top_rated_pages=args.top_rated_pages,
            genres=_split_arg(args.genres),
            genre_pages=args.genre_pages,
            data_dir=args.data_dir,
            db_path=args.db_path,
        )
    elif args.command == "recommend":
        while True:
            results = recommend_movies_and_music(
                genres=_split_arg(args.genres),
                directors=_split_arg(args.directors),
                actors=_split_arg(args.actors),
                like_movies=_split_arg(args.like_movies),
                min_score=args.min_score,
                top_n=args.top_n,
                db_path=args.db_path,
                exclude_last=False,
            )
            print_recommendations(results)
            ans = input("새로운 영화를 추천받으시려면 'y'를 입력하세요: ").strip().lower()
            if ans != "y":
                break
            results = recommend_movies_and_music(
                genres=_split_arg(args.genres),
                directors=_split_arg(args.directors),
                actors=_split_arg(args.actors),
                like_movies=_split_arg(args.like_movies),
                min_score=args.min_score,
                top_n=args.top_n,
                db_path=args.db_path,
                exclude_last=True,
            )
            print_recommendations(results)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
