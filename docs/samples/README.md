# Manual Upload 샘플 파일

Market Regime Lab 의 **Manual Upload** 를 바로 시험해 보기 위한 예시 파일입니다.
실제 시장 데이터가 아니라 `app/regime/data/sources.py` 의 결정론적 합성
시계열에서 뽑은 300거래일이며, 컬럼 이름·형식이 실제 내려받기 파일과 같은
모양이라 매핑 UI 를 확인하는 용도로 쓸 수 있습니다.

| 파일 | 형태 | 용도 |
|---|---|---|
| `sample_ohlcv.csv` | `Date, Open, High, Low, Close, Volume` | 가격 파일(①) |
| `sample_volume.csv` | `날짜, 거래량` (UTF-8 BOM) | 별도 거래량 파일(②) — 한글 컬럼 자동 매핑 확인용 |
| `sample_us10y.csv` | `observation_date, DGS10` (FRED 형식, percent) | 10년물 파일(③) |

사용법: `./run_regime.sh` → 사이드바 **데이터 입력 방식 → Manual Upload** →
① 가격 파일에 `sample_ohlcv.csv`, (선택) ② 별도 파일에 `sample_volume.csv`,
③ 10년물에 `sample_us10y.csv` 를 올리면 됩니다. 300거래일뿐이라 SMA200 등
장기 지표는 뒤쪽 일부 구간에서만 계산됩니다 — 실제 분석에는 20년치를 올리세요.
