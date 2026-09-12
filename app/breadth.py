"""미장 마켓 브레스(시장 폭) 대시보드 — 지표 레지스트리 · 채점 · 뷰 구성.

지수는 시총 가중이라 대형주 몇 개로도 올라간다. 마켓 브레스는 "얼마나 많은
종목이 같이 가고 있는가"를 보는 것이고, 지수 신고가 + 브레스 하락 = 내부 붕괴
라는 전형적인 천장 신호를 잡는 데 쓴다.

값은 직접 계산하지 않고 이미 시장이 계산해 둔 지표를 받아온다. 수집은
``tools/breadth_us.py`` 가 하고(TradingView INDEX 심볼 → Yahoo 파생비율 →
FRED 스프레드, 실패 시 구성종목 직접 계산으로 폴백) 결과를
``data/breadth_us.json`` 에 날짜별 시계열로 쌓는다. 이 모듈은 그 파일을 읽어
구간 판정 · 0~100 종합점수 · 다이버전스 경고까지 붙인 뷰를 만든다.

레지스트리를 tools 가 아니라 여기에 둔 이유: 수집기와 화면이 같은 심볼 목록 ·
같은 임계값을 보게 하려고. 지표 하나 추가는 METRICS 에 한 줄 추가로 끝난다.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DATA_FILE = os.environ.get("SUH_DH_BREADTH_FILE") or str(
    Path(__file__).resolve().parent.parent / "data" / "breadth_us.json"
)

# 시계열로 보관할 최대 일수(약 2년). 파일이 무한히 커지지 않게 수집기가 자른다.
MAX_HISTORY_DAYS = 500

# 종합점수에 넣어 줄 수 있는 최대 지연(거래일).
#
# 지표마다 자기 마지막 값을 쓰게 고쳤더니 반대쪽 문제가 생겼다 — Yahoo 의
# ^VIX3M 이 2026-07-17 이후로 갱신을 멈췄는데, 두 달 묵은 VIX 기간구조가
# "현재 리스크 레짐"인 척 점수에 들어가고 있었다. 며칠 어긋나는 건 정상이고
# 두 달은 죽은 값이다. 이 선을 넘으면 카드에는 날짜와 함께 남기되(원천이 죽은
# 걸 사용자가 알아야 하니까) 점수 계산에서는 뺀다.
STALE_LIMIT_DAYS = 5


@dataclass(frozen=True)
class Metric:
    """지표 하나의 정의.

    zones 는 (상한, 라벨, 색키) 리스트로 낮은 값부터 나열한다. 마지막 항목의
    상한은 None(무한대). value → 구간 판정은 이 표 하나만 보고 한다.

    score_at 은 (0점이 되는 값, 100점이 되는 값). 두 값의 대소가 뒤집혀 있으면
    (예: 하이일드 스프레드) 낮을수록 좋은 지표로 자동 처리된다. weight 가 0 이면
    화면에는 보여주되 종합점수에는 넣지 않는다.
    """

    key: str
    label: str
    source: str              # "tradingview" | "yahoo" | "fred" | "derived"
    symbol: str              # TradingView 심볼 등 원천 식별자("" = 파생)
    group: str               # "core" | "extra" | "context"
    unit: str = "%"
    desc: str = ""
    use: str = ""            # 용도 한 줄
    zones: tuple = ()
    score_at: tuple[float, float] | None = None
    weight: float = 0.0
    decimals: int = 1


# 0~100% 형태(‘N일선 위 종목 비율’)는 구간 해석이 전부 같으므로 한 번만 정의한다.
PCT_ZONES = (
    (20.0, "극단 침체", "deep-low"),
    (40.0, "약세", "low"),
    (60.0, "중립", "mid"),
    (80.0, "양호", "high"),
    (None, "과열", "deep-high"),
)

# 지표 레지스트리. 순서가 곧 화면 배치 순서.
# 지표 레지스트리. 순서가 곧 화면 배치 순서.
#
# 출처 이력(왜 이 구성인가):
#   TradingView 의 INDEX:S5FI 계열은 웹 화면 전용이라 공개 조회 경로가 없다.
#   스캐너의 america/global 엔드포인트는 응답은 하지만 INDEX 심볼에 0행을 주고,
#   단건 조회도 close 를 돌려주지 않는다(실행 1·2차 로그로 확인). 그래서 숫자는
#   구성종목에서 직접 계산하고, TradingView 는 화면 하단 위젯 차트로만 쓴다.
#   FRED 하이일드 스프레드도 러너에서 계속 read timeout 이라(이 저장소의 기존
#   fred-rates 워크플로도 한 번도 성공하지 못했다) HYG/LQD 비율로 대체했다.
METRICS: tuple[Metric, ...] = (
    # ── core: %>이평선 (구성종목 종가로 직접 계산) ────────────────────────
    Metric("S5TW", "S&P500 20일선 위 비율", "computed", "S&P 500 구성종목", "core",
           desc="S&P 500 종목 중 20일 이동평균 위에 있는 비율",
           use="단기 breadth — 과열/침체가 가장 빨리 찍힌다. 되돌림 타이밍용.",
           zones=PCT_ZONES, score_at=(0, 100), weight=10),
    Metric("S5FI", "S&P500 50일선 위 비율", "computed", "S&P 500 구성종목", "core",
           desc="S&P 500 종목 중 50일 이동평균 위에 있는 비율",
           use="중기 breadth — 시장 폭의 기준 지표. 하나만 본다면 이것.",
           zones=PCT_ZONES, score_at=(0, 100), weight=25),
    Metric("S5TH", "S&P500 200일선 위 비율", "computed", "S&P 500 구성종목", "core",
           desc="S&P 500 종목 중 200일 이동평균 위에 있는 비율",
           use="장기 건강도 — 강세장/약세장 구분. 50% 아래 지속은 구조적 약세.",
           zones=PCT_ZONES, score_at=(0, 100), weight=20),
    Metric("NDFI", "나스닥100 50일선 위 비율", "computed", "Nasdaq 100 구성종목", "core",
           desc="Nasdaq 100 종목 중 50일 이동평균 위에 있는 비율",
           use="성장주 중기 breadth — S5FI 와 벌어지면 스타일 쏠림 신호.",
           zones=PCT_ZONES, score_at=(0, 100), weight=5),
    Metric("NDTH", "나스닥100 200일선 위 비율", "computed", "Nasdaq 100 구성종목", "core",
           desc="Nasdaq 100 종목 중 200일 이동평균 위에 있는 비율",
           use="성장주 장기 건강도.",
           zones=PCT_ZONES, score_at=(0, 100), weight=5),

    # ── extra: %>이평선만으로는 안 보이는 것 ──────────────────────────────
    # NYSE 전체(약 3,000 종목) 기준 A/D·신고가는 받아올 곳이 없어서, 같은 성격을
    # S&P 500 안에서 계산한다. 모집단이 다르므로 이름도 다르게 붙였다 — NYSE 판을
    # 보고 싶으면 화면 하단 TradingView 위젯(INDEX:ADDN 등)을 쓰면 된다.
    Metric("SPX_NHNL", "S&P500 신고가−신저가", "computed", "S&P 500 구성종목", "extra",
           unit="종목", decimals=0,
           desc="S&P 500 안에서 52주 신고가를 낸 종목수 − 신저가를 낸 종목수",
           use="%>MA 가 높은데 이 값이 음수면 겉만 멀쩡한 장. 레짐 확인에 %>MA "
               "다음으로 중요하다. (NYSE 전체가 아니라 S&P 500 기준)",
           zones=((-40.0, "신저가 우위 극단", "deep-low"), (-5.0, "신저가 우위", "low"),
                  (5.0, "균형", "mid"), (40.0, "신고가 우위", "high"),
                  (None, "신고가 폭발", "deep-high")),
           score_at=(-40, 40), weight=10),
    Metric("SPX_AD", "S&P500 상승−하락 종목수", "computed", "S&P 500 구성종목", "extra",
           unit="종목", decimals=0,
           desc="당일 S&P 500 안에서 오른 종목수 − 내린 종목수",
           use="그날 시장이 넓게 올랐는지 좁게 올랐는지. 지수는 올랐는데 이 값이 "
               "음수면 대형주 몇 개가 끌어올린 날. (NYSE 전체가 아니라 S&P 500 기준)",
           zones=((-350.0, "매도 우위 극단", "deep-low"), (-100.0, "매도 우위", "low"),
                  (100.0, "혼조", "mid"), (350.0, "매수 우위", "high"),
                  (None, "매수 우위 극단", "deep-high")),
           score_at=(-350, 350), weight=5),
    Metric("RSP_SPY_20D", "동일가중/시총가중 20일 추이", "yahoo", "RSP÷SPY", "extra",
           unit="%", decimals=2,
           desc="RSP(동일가중 S&P) ÷ SPY(시총가중) 비율의 최근 20거래일 변화율",
           use="브레스를 값 하나로 압축한 것. 플러스면 평균 종목이 지수를 이기는 "
               "장(건강), 마이너스면 대형주 쏠림.",
           zones=((-2.0, "극단 쏠림", "deep-low"), (-0.5, "대형주 쏠림", "low"),
                  (0.5, "중립", "mid"), (2.0, "폭 확산", "high"),
                  (None, "강한 확산", "deep-high")),
           score_at=(-2.0, 2.0), weight=10),

    # ── context: 리스크 레짐(브레스는 아니지만 같이 봐야 하는 것) ─────────
    Metric("VIX_TERM", "VIX 기간구조(3M÷1M)", "yahoo", "^VIX3M÷^VIX", "context",
           unit="배", decimals=3,
           desc="3개월 VIX ÷ 1개월 VIX. 1 미만은 백워데이션(단기 공포 우위)",
           use="1 아래로 내려가면 위험 국면. 브레스 악화와 겹치면 방어적으로.",
           zones=((0.95, "백워데이션(위험)", "deep-low"), (1.0, "평탄", "low"),
                  (1.1, "정상", "mid"), (None, "안정", "high")),
           score_at=(0.95, 1.12), weight=7),
    Metric("HYG_LQD_20D", "하이일드/투자등급 20일", "yahoo", "HYG÷LQD", "context",
           unit="%", decimals=2,
           desc="HYG(하이일드 ETF) ÷ LQD(투자등급 ETF) 비율의 20거래일 변화율",
           use="신용시장의 확인. 주식 브레스가 무너질 때 이 값도 같이 빠지면 진짜 "
               "위험, 조용하면 단순 조정일 확률이 높다. (FRED 스프레드가 러너에서 "
               "계속 막혀 그 자리를 대신한다)",
           zones=((-1.5, "위험회피 극단", "deep-low"), (-0.4, "위험회피", "low"),
                  (0.4, "중립", "mid"), (1.5, "위험선호", "high"),
                  (None, "강한 위험선호", "deep-high")),
           score_at=(-1.5, 1.5), weight=10),
    Metric("XLP_SPY_20D", "방어주 상대강도 20일", "yahoo", "XLP÷SPY", "context",
           unit="%", decimals=2,
           desc="XLP(필수소비재) ÷ SPY 비율의 최근 20거래일 변화율",
           use="플러스(방어주 우위)는 지수가 버텨도 내부는 방어 전환 중이라는 뜻. "
               "브레스 악화의 선행 신호로 자주 나온다.",
           zones=((-2.0, "공격적", "deep-high"), (-0.5, "위험선호", "high"),
                  (0.5, "중립", "mid"), (2.0, "방어 전환", "low"),
                  (None, "강한 방어", "deep-low")),
           score_at=(2.0, -2.0), weight=5),
    Metric("SPY_VS_200", "S&P500 200일선 이격", "yahoo", "SPY", "context",
           unit="%", decimals=2,
           desc="SPY 종가의 200일 이동평균 대비 괴리율",
           use="브레스를 해석할 기준선. 지수는 200일선 위인데 브레스가 40% 미만 "
               "이면 그게 바로 다이버전스.",
           zones=((-5.0, "추세 이탈", "deep-low"), (0.0, "200일선 아래", "low"),
                  (5.0, "추세 유지", "mid"), (12.0, "강세", "high"),
                  (None, "과열 이격", "deep-high")),
           weight=0),
    Metric("QQQ_VS_200", "나스닥100 200일선 이격", "yahoo", "QQQ", "context",
           unit="%", decimals=2,
           desc="QQQ 종가의 200일 이동평균 대비 괴리율",
           use="성장주 추세 기준선.",
           zones=((-5.0, "추세 이탈", "deep-low"), (0.0, "200일선 아래", "low"),
                  (5.0, "추세 유지", "mid"), (12.0, "강세", "high"),
                  (None, "과열 이격", "deep-high")),
           weight=0),
    Metric("VIX", "VIX", "yahoo", "^VIX", "context", unit="", decimals=2,
           desc="S&P 500 30일 내재변동성",
           use="절대 수준보다 기간구조(위)와 같이 본다.",
           zones=((13.0, "안일", "deep-high"), (18.0, "안정", "high"),
                  (25.0, "경계", "mid"), (35.0, "불안", "low"),
                  (None, "패닉", "deep-low")),
           weight=0),
)


BY_KEY: dict[str, Metric] = {m.key: m for m in METRICS}

GROUPS = (
    ("core", "핵심 브레스", "얼마나 많은 종목이 추세 위에 있고, 오늘 얼마나 넓게 올랐나"),
    ("extra", "확인 지표", "%>이평선만으로는 안 보이는 것 — 신고가/신저가, 모멘텀, 거래량, 쏠림"),
    ("context", "리스크 레짐", "브레스를 해석할 배경 — 변동성 · 신용 · 방어주 · 추세 기준선"),
)

# 종합점수 → 레짐. (하한, 라벨, 색키, 한 줄 해석)
REGIMES = (
    (0, "위험", "deep-low",
     "시장 폭이 무너진 상태. 신규 진입보다 현금 비중과 손절 관리가 먼저."),
    (30, "주의", "low",
     "폭이 좁아지는 중. 돌파 실패율이 올라가므로 포지션을 줄여 대응."),
    (45, "중립", "mid",
     "방향성 없는 구간. 개별 종목 세팅의 질로만 승부."),
    (60, "양호", "high",
     "폭이 넓은 상승. 베이스 돌파의 성공률이 가장 높은 구간."),
    (80, "과열", "deep-high",
     "대부분의 종목이 이미 올라온 상태. 신규 진입보다 보유분 관리 구간."),
)


# ---------------------------------------------------------------- helpers
def _demo() -> bool:
    return os.environ.get("SUH_DH_DEMO", "").strip() in ("1", "true", "yes")


def zone_of(m: Metric, value: float | None) -> tuple[str | None, str | None]:
    """(라벨, 색키). 값이 없거나 구간표가 없으면 (None, None)."""
    if value is None or not m.zones:
        return None, None
    for upper, label, tone in m.zones:
        if upper is None or value < upper:
            return label, tone
    return m.zones[-1][1], m.zones[-1][2]


def sub_score(m: Metric, value: float | None) -> float | None:
    """지표 값을 0~100 점으로 정규화. score_at 이 없으면 채점 대상이 아니다.

    score_at=(lo, hi) 에서 lo 가 0점, hi 가 100점. lo > hi 면 (하이일드 스프레드
    처럼) 낮을수록 좋은 지표로 자동 반전된다.
    """
    if value is None or not m.score_at:
        return None
    lo, hi = m.score_at
    if lo == hi:
        return None
    pct = (value - lo) / (hi - lo) * 100
    return round(max(0.0, min(100.0, pct)), 1)


def composite(values: dict[str, float | None]) -> dict:
    """가중 평균 종합점수. 값이 없는 지표의 가중치는 나머지에 재분배된다."""
    parts, total_w = [], 0.0
    for m in METRICS:
        if m.weight <= 0:
            continue
        s = sub_score(m, values.get(m.key))
        if s is None:
            continue
        parts.append({"key": m.key, "label": m.label, "score": s, "weight": m.weight})
        total_w += m.weight
    if not parts:
        return {"score": None, "regime": None, "tone": None, "note":
                "지표 값을 아직 수집하지 못했습니다.", "parts": [], "coverage": 0.0}

    score = round(sum(p["score"] * p["weight"] for p in parts) / total_w, 1)
    full_w = sum(m.weight for m in METRICS if m.weight > 0)
    label, tone, note = REGIMES[0][1], REGIMES[0][2], REGIMES[0][3]
    for lower, lab, t, n in REGIMES:
        if score >= lower:
            label, tone, note = lab, t, n
    return {
        "score": score,
        "regime": label,
        "tone": tone,
        "note": note,
        "parts": sorted(parts, key=lambda p: -p["weight"]),
        # 가중치 기준 커버리지. 낮으면 점수를 신뢰하지 말라는 뜻.
        "coverage": round(total_w / full_w * 100, 0) if full_w else 0.0,
    }


def _series_rows(data: dict) -> list[tuple[str, dict]]:
    series = data.get("series") or {}
    return sorted(((d, v) for d, v in series.items() if isinstance(v, dict)))


def _last_points(rows: list[tuple[str, dict]], key: str) -> tuple[str | None, float | None, float | None]:
    """그 지표가 실제로 값을 가진 마지막 (날짜, 값, 그 전 값).

    원천마다 마지막 거래일이 하루이틀 어긋난다 — 실제로 ^VIX3M 이 SPY 보다 며칠
    일찍 끝나는 바람에 VIX 기간구조가 459일치나 쌓여 있는데도 카드가 "—" 로
    비어 있었다. 기준일 한 줄만 보지 말고 지표별로 마지막 값을 찾아 쓰고,
    기준일보다 오래됐으면 화면에 그 날짜를 같이 보여준다.
    """
    pts = [(d, v[key]) for d, v in rows if v.get(key) is not None]
    if not pts:
        return None, None, None
    d, val = pts[-1]
    prev = pts[-2][1] if len(pts) > 1 else None
    return d, val, prev


def _trend(rows: list[tuple[str, dict]], key: str, back: int) -> float | None:
    """back 거래일 전 대비 변화량(절대값 차이). 데이터가 모자라면 None."""
    pts = [(d, v.get(key)) for d, v in rows if v.get(key) is not None]
    if len(pts) < 2:
        return None
    cur = pts[-1][1]
    idx = max(0, len(pts) - 1 - back)
    prev = pts[idx][1]
    if prev is None or idx == len(pts) - 1:
        return None
    return round(cur - prev, 4)


def divergences(rows: list[tuple[str, dict]]) -> list[dict]:
    """지수와 브레스가 어긋나는 전형적인 패턴만 골라 경고로 만든다.

    브레스 대시보드를 보는 진짜 이유가 이것이므로, 숫자를 나열하는 대신 판정을
    문장으로 내놓는다. 근거가 되는 수치를 항상 같이 담아 눈으로 검증할 수 있게 한다.
    """
    if not rows:
        return []
    latest = rows[-1][1]
    out: list[dict] = []

    spy_gap = latest.get("SPY_VS_200")
    s5fi = latest.get("S5FI")
    s5th = latest.get("S5TH")
    nhnl = latest.get("SPX_NHNL")

    # 1) 지수는 추세 위인데 절반도 안 되는 종목만 추세 위 — 전형적 천장 신호.
    if spy_gap is not None and s5fi is not None and spy_gap > 0 and s5fi < 45:
        out.append({
            "level": "warn",
            "title": "지수 강세 · 브레스 약세 (베어리시 다이버전스)",
            "detail": f"S&P500 은 200일선 +{spy_gap:.1f}% 위인데 50일선 위 종목은 "
                      f"{s5fi:.0f}% 뿐입니다. 소수 대형주가 지수를 끌고 가는 구조로, "
                      f"개별 종목 돌파는 실패하기 쉽습니다.",
        })

    # 2) 지수 추세 위 + 신저가가 신고가보다 많음 — 내부 손상.
    # 기준이 S&P 500(500 종목)이라 NYSE 전체를 볼 때보다 임계값이 작다.
    if spy_gap is not None and nhnl is not None and spy_gap > 0 and nhnl < -5:
        out.append({
            "level": "warn",
            "title": "지수 강세 · 신저가 우위",
            "detail": f"S&P 500 안에서 신고가−신저가가 {nhnl:+.0f} 종목입니다. 지수가 "
                      f"추세 위인데 신저가가 더 많다는 것은 하위 종목군이 이미 "
                      f"무너지고 있다는 뜻입니다.",
        })

    # 3) 20일 전 대비 중기 브레스가 크게 빠졌는데 지수는 버팀 — 악화 진행 중.
    d20 = _trend(rows, "S5FI", 20)
    if d20 is not None and d20 <= -15 and (spy_gap is None or spy_gap > -3):
        out.append({
            "level": "warn",
            "title": "브레스 급속 악화",
            "detail": f"50일선 위 종목 비율이 20거래일 만에 {d20:+.0f}%p 줄었습니다. "
                      f"지수가 아직 버티고 있어도 내부는 이미 이탈 중입니다.",
        })

    # 4) 바닥 신호: 극단 침체 + 브레스 반등 시작.
    if s5th is not None and s5th < 25 and (d20 or 0) > 10:
        out.append({
            "level": "good",
            "title": "브레스 바닥 반등",
            "detail": f"200일선 위 종목이 {s5th:.0f}% 로 극단 침체 구간인데 중기 브레스는 "
                      f"20거래일간 {d20:+.0f}%p 개선됐습니다. 바닥권 전환 후보 국면입니다.",
        })

    # 5) 신용시장 확인. 주식 브레스가 나쁜데 신용은 조용하면 단순 조정일 확률.
    credit = latest.get("HYG_LQD_20D")
    if credit is not None and s5fi is not None and s5fi < 40 and credit > -0.4:
        out.append({
            "level": "info",
            "title": "주식 브레스 약세 · 신용시장은 안정",
            "detail": f"하이일드/투자등급 비율이 20거래일간 {credit:+.2f}% 로 버티고 "
                      f"있습니다. 신용 경색을 동반하지 않은 조정일 가능성이 높습니다.",
        })
    return out


def _read_file() -> dict | str:
    """저장된 스냅샷, 또는 못 읽은 이유(문자열)."""
    path = Path(DATA_FILE)
    if not path.exists():
        return "아직 수집된 데이터가 없습니다. breadth 워크플로를 실행하세요."
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return f"breadth 데이터를 읽지 못했습니다: {e}"
    if not isinstance(data, dict) or not isinstance(data.get("series"), dict):
        return "breadth 데이터 형식이 올바르지 않습니다."
    return data


def get_breadth() -> dict:
    """대시보드가 그대로 그릴 수 있는 형태로 스냅샷을 반환한다."""
    data = _read_file()
    if isinstance(data, str):
        # SUH_DH_DEMO=1 이면 합성 시계열로 화면/채점/경고를 확인할 수 있게 한다.
        if _demo():
            from .demo_data import demo_breadth_series

            data = demo_breadth_series()
        else:
            return _empty(data)

    rows = _series_rows(data)
    if not rows:
        return _empty("아직 수집된 데이터가 없습니다. breadth 워크플로를 실행하세요.")

    latest_date = rows[-1][0]
    sources = data.get("sources") or {}

    # 기준일에서 며칠 전인지 세려면 날짜 목록이 필요하다(거래일 기준).
    day_index = {d: i for i, (d, _) in enumerate(rows)}
    last_i = len(rows) - 1

    metrics = []
    for m in METRICS:
        mdate, v, p = _last_points(rows, m.key)
        lag = last_i - day_index[mdate] if mdate in day_index else 0
        usable = v is not None and lag <= STALE_LIMIT_DAYS
        label, tone = zone_of(m, v)
        # 스파크라인: 최근 90 영업일. (날짜, 값) 쌍으로 보내 결측을 건너뛴다.
        spark = [[d, r[m.key]] for d, r in rows[-90:] if r.get(m.key) is not None]
        metrics.append({
            "key": m.key, "label": m.label, "group": m.group, "unit": m.unit,
            "symbol": m.symbol, "source": sources.get(m.key) or m.source,
            "desc": m.desc, "use": m.use, "decimals": m.decimals,
            "value": v, "prev": p,
            # 이 지표의 값이 실제로 찍힌 날. 기준일과 다르면 화면이 날짜를 띄운다.
            "asof": mdate, "stale": bool(mdate and mdate != latest_date),
            # 너무 오래된 값은 보여주되 점수에서는 뺀다(원천이 죽은 경우).
            "lag": lag, "usable": usable,
            "change": round(v - p, 4) if (v is not None and p is not None) else None,
            "d20": _trend(rows, m.key, 20),
            "zone": label, "tone": tone,
            "score": sub_score(m, v), "weight": m.weight,
            "spark": spark,
        })

    # 점수에는 "지금 값"만 넣는다 — 오래 묵은 값은 카드에만 남는다.
    values = {m["key"]: m["value"] for m in metrics if m["usable"]}
    return {
        "updated": data.get("updated"),
        "asof": latest_date,
        "demo": bool(data.get("demo")) or _demo(),
        "count": sum(1 for m in metrics if m["value"] is not None),
        "total": len(metrics),
        "days": len(rows),
        "composite": composite(values),
        "score_history": _score_history(rows),
        "alerts": divergences(rows),
        "groups": [{"key": k, "label": lab, "desc": d} for k, lab, d in GROUPS],
        "metrics": metrics,
        "notes": data.get("notes") or [],
    }


def _score_history(rows: list[tuple[str, dict]], days: int = 120) -> list[list]:
    """종합점수의 과거 추이. 점수 자체가 시장 레짐의 요약이므로 같이 그린다."""
    out = []
    for d, r in rows[-days:]:
        c = composite({k: r.get(k) for k in BY_KEY})
        # 커버리지가 너무 낮은 날(수집 초기/장애일)은 점수를 신뢰할 수 없어 뺀다.
        if c["score"] is not None and c["coverage"] >= 50:
            out.append([d, c["score"]])
    return out


def _empty(note: str) -> dict:
    return {
        "updated": None, "asof": None, "demo": _demo(), "count": 0,
        "total": len(METRICS), "days": 0,
        "composite": {"score": None, "regime": None, "tone": None,
                      "note": note, "parts": [], "coverage": 0.0},
        "score_history": [], "alerts": [],
        "groups": [{"key": k, "label": lab, "desc": d} for k, lab, d in GROUPS],
        "metrics": [
            {"key": m.key, "label": m.label, "group": m.group, "unit": m.unit,
             "symbol": m.symbol, "source": m.source, "desc": m.desc, "use": m.use,
             "decimals": m.decimals, "value": None, "prev": None, "change": None,
             "asof": None, "stale": False, "lag": 0, "usable": False,
             "d20": None, "zone": None, "tone": None, "score": None,
             "weight": m.weight, "spark": []}
            for m in METRICS
        ],
        "notes": [note],
    }


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
