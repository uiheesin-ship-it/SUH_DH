# SUH_DH — 미국 52주 신고가 대시보드

매일 미국 증시 마감 후(한국시간 아침) **52주 신고가**를 기록한 미국 주식을
섹터·소섹터별로 한눈에 훑어보기 위한 실시간 대시보드입니다.

- **데이터 소스**: 신고가 스크리닝은 [Finviz](https://finviz.com) `New High` 시그널,
  차트·뉴스·실적은 [Yahoo Finance](https://finance.yahoo.com) (모두 무료 소스).
- **정리 기준**: 섹터 → 소섹터(산업)별 그룹, 각 그룹 내 **시가총액 순** 정렬.
- **종목별 정보**: 티커, 전일대비 상승률, 상승 이유(최신 뉴스 + 최근 실적발표 배지).
- **차트**: 티커 클릭 시 캔들 차트 모달 — 전체기간/6개월 토글, **거래량**,
  **5/20/50/120일 이동평균선**(각각 다른 색).

## 빠른 시작

```bash
pip install -r requirements.txt

# 실시간(라이브) 데이터로 실행
./run.sh
# 또는: python3 -m uvicorn app.main:app --port 8000

# 네트워크 없이 샘플 데이터로 UI 미리보기
./run.sh --demo
```

브라우저에서 <http://127.0.0.1:8000> 접속.

## 실시간 업데이트

- 상단의 **자동 새로고침**(기본 1분) 체크박스와 간격 선택으로 주기적 갱신.
- **새로고침** 버튼으로 즉시 갱신.
- 서버는 무료 소스의 레이트리밋을 피하려고 짧게 캐시합니다
  (신고가 목록 3분, 차트 10분, 뉴스 30분 — `SUH_DH_*_TTL` 환경변수로 조정).
- ⚠️ 무료 데이터(Yahoo/Finviz)는 실시간 대비 **약 15분 지연**될 수 있습니다.
  진짜 틱 단위 실시간이 필요하면 유료 API(Polygon, IEX 등) 연동이 필요합니다.

## 동작 방식 / 구조

```
app/
  main.py        FastAPI 앱 + JSON API (/api/highs, /api/reason/{t}, /api/chart/{t})
  screener.py    Finviz "New High" 스크리닝 → 섹터/소섹터 그룹, 시총 정렬
  charts.py      Yahoo 과거 시세(차트) + 뉴스/실적(상승 이유)
  indicators.py  이동평균(MA5/20/50/120) 계산
  cache.py       짧은 TTL 인메모리 캐시
  demo_data.py   오프라인 샘플 데이터(SUH_DH_DEMO=1)
  static/
    index.html   대시보드 허브(런처) — 프로그램 카드 목록
    hub.css
    highs/       52주 신고가 프로그램(HTML/CSS/JS, 차트는 Plotly)
```

### 화면 구조 (허브 + 프로그램)

- `/` — **대시보드 허브**. 프로그램들을 카드로 보여주고 눌러서 들어갑니다.
- `/highs/` — 52주 신고가 프로그램.

새 프로그램을 추가하려면: `static/<프로그램>/` 폴더를 만들고,
`static/index.html` 의 `APPS` 배열에 카드 한 줄(`name/emoji/desc/href`)만 추가하면
허브에 자동으로 나타납니다.

API 예시:

| 엔드포인트 | 설명 |
|---|---|
| `GET /api/highs` | 섹터→소섹터로 그룹된 신고가 종목(시총순) |
| `GET /api/reason/{ticker}` | 최신 뉴스 + 최근 실적발표 여부 |
| `GET /api/chart/{ticker}?range=max\|6mo` | OHLCV + 거래량 + MA5/20/50/120 |

## 네트워크 접근 안내 (중요)

이 대시보드는 `finviz.com` 과 `query1/query2.finance.yahoo.com` 으로
아웃바운드 요청을 보냅니다. 로컬 PC에서는 보통 문제없이 동작하지만,
**Claude Code on the web 같은 egress allowlist가 적용된 샌드박스에서는 차단**됩니다.
그런 환경에서 라이브로 쓰려면 해당 호스트를 네트워크 허용 목록에 추가하거나,
미리보기는 `--demo` 모드를 사용하세요.

## 테스트

```bash
python3 -m pytest tests/ -q
```

## 향후 개선 아이디어

- 상승 이유의 정확도 향상(실적 서프라이즈 % 표시, 뉴스 요약).
- 관심 섹터/시총 필터, 신고가 외 추가 시그널.
- 유료 실시간 데이터 소스 연동 옵션.
