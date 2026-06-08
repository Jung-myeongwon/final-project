# TasteLab Movie & Music Recommender

우아한 다크/네온 그라데이션 스타일의 영화·음악 추천 웹앱입니다.

## 주요 기능

### 영화 추천
- 표 기반 취향 입력
- 좋아하는 장르, 영화, 감독, 배우 반영
- 포스터 카드 UI
- 추천 이유 표시
- 영화 기반 OST/사운드트랙 추천 유지
- 영화 장르 기반 음악 추천 유지

### 음악 추천
- 상단 메뉴에서 음악 추천 페이지 이동
- 좋아하는 장르, 아티스트, 노래, 앨범 입력
- LastFM 기반 음악 추천
- 추천 이유와 취향 적합도 표시

## 실행

### 개발자용 (Python 설치 필요)

```bash
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

브라우저: `http://127.0.0.1:8000`

Windows에서는 `앱실행.bat` 더블클릭으로도 실행할 수 있습니다.

### 데스크톱 앱 (Python 없이 실행)

1. **한 번만** 프로젝트 폴더에서 `빌드_데스크톱앱.bat`을 실행합니다. (Python + 인터넷 필요)
2. 빌드가 끝나면 `dist\TasteLab` 폴더가 생성됩니다.
3. **`dist\TasteLab` 폴더 전체**를 다른 PC로 복사합니다.
4. `TasteLab.exe`를 더블클릭합니다. 작은 창이 뜨고 브라우저가 자동으로 열립니다.
5. 음악 API를 쓰려면 exe 옆에 `.env` 파일을 두고 `LASTFM_API_KEY`를 설정하세요. (없으면 첫 실행 시 `.env.example`에서 복사됩니다.)

> 종료: TasteLab 창을 닫으면 서버도 함께 종료됩니다.

## 음악 추천 키 설정

`.env.example` 파일명을 `.env`로 바꾸고 아래처럼 입력하세요.

```env
LASTFM_API_KEY=your_lastfm_api_key_here
TMDB_API_KEY=your_tmdb_api_key_here
```

`TMDB_API_KEY`는 추천 영화 카드의 **YouTube 예고편/트레일러** 버튼에 사용됩니다.
