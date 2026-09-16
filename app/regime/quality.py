"""Data quality checks — "이 숫자를 믿고 분석해도 되는가".

Every check returns a :class:`Check` with one of three statuses (ok / warn /
fail), a human-readable detail line and the value it judged, so the same report
renders in Streamlit and on the terminal::

    python3 -m app.regime.quality --ticker '^IXIC'          # 실데이터
    python3 -m app.regime.quality --ticker '^IXIC' --demo   # 합성 데이터

The checks exist because three things silently break this kind of analysis:

* **Volume** — distribution days compare today's volume with yesterday's. An
  index whose feed reports 0 (or nothing) on some days does not just lose those
  days: it quietly changes the distribution-day count that everything else is
  conditioned on.
* **Yield units** — ^TNX is published as a percentage (4.28 = 4.28%), but some
  mirrors carry tenths (42.8) or basis points (428). A 100× unit error does not
  crash anything; it just makes the macro feature meaningless.
* **Calendar** — duplicated dates, missing weeks and a stale last bar all look
  like ordinary data until a forward return is measured across the hole.

The same checks run whether the data was downloaded or uploaded by hand — the
loader normalises both into one schema — and a separate source summary states,
per stream, where the numbers actually came from.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

# info 는 "알고 있어야 하는 성질"(경고가 아님) — 종합 판정을 끌어내리지 않는다.
STATUS_ORDER = {"info": 0, "ok": 0, "warn": 1, "fail": 2}
STATUS_ICON = {"info": "ℹ️", "ok": "✅", "warn": "⚠️", "fail": "❌"}

# 분산일 판정이 성립하려면 거래량이 사실상 매일 있어야 한다. 아래 비율 밑으로
# 떨어지면 개수 자체가 신뢰할 수 없게 된다.
VOLUME_OK_RATIO = 0.98
VOLUME_WARN_RATIO = 0.90
# 10년물 수익률의 상식적인 범위(2006~현재 실제 범위는 약 0.5%~5.3%).
YIELD_SANE_RANGE = (0.2, 10.0)

# proxy 거래량 경고에서 "무엇의 거래량이 아닌지"를 분명히 쓰기 위한 이름표.
INDEX_NAMES = {
    "^IXIC": "Nasdaq Composite", "^GSPC": "S&P 500", "^DJI": "Dow Jones",
    "^RUT": "Russell 2000", "^NDX": "Nasdaq 100",
}
KIND_LABELS = {"auto": "Auto Download", "upload": "Manual Upload", "proxy": "Proxy (사용자 지정)"}


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    status: str
    detail: str
    value: str = ""
    suggestion: str = ""


@dataclass
class QualityReport:
    series: str
    checks: list[Check] = field(default_factory=list)

    def add(self, *checks: Check) -> None:
        self.checks.extend(checks)

    @property
    def status(self) -> str:
        """Worst status in the report. ``info`` notes never set the verdict."""
        worst = max((c.status for c in self.checks), key=lambda s: STATUS_ORDER[s], default="ok")
        return "ok" if worst == "info" else worst

    def problems(self) -> list[Check]:
        return [c for c in self.checks if c.status in ("warn", "fail")]

    def notes(self) -> list[Check]:
        return [c for c in self.checks if c.status == "info"]

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame([{
            "": STATUS_ICON[c.status],
            "시리즈": self.series,
            "항목": c.label,
            "값": c.value,
            "판정": c.detail,
            "제안": c.suggestion,
        } for c in self.checks])


def _bd_gaps(index: pd.DatetimeIndex) -> pd.Series:
    """Business days missing between consecutive bars (휴장일 포함이라 3~4 는 정상)."""
    if len(index) < 2:
        return pd.Series(dtype=float)
    gaps = pd.Series(np.busday_count(index[:-1].values.astype("datetime64[D]"),
                                     index[1:].values.astype("datetime64[D]")),
                     index=index[1:], dtype=float)
    return gaps


def check_calendar(name: str, df: pd.DataFrame, years: int) -> list[Check]:
    idx = pd.DatetimeIndex(df.index)
    out: list[Check] = []
    if len(idx) == 0:
        return [Check("range", "기간", "fail", "데이터가 비어 있습니다.")]

    span_years = (idx.max() - idx.min()).days / 365.25
    per_year = len(idx) / span_years if span_years > 0 else 0
    status = "ok" if span_years >= years * 0.9 else "warn"
    out.append(Check("range", "기간", status,
                     f"{span_years:.1f}년치 · 연 {per_year:.0f}거래일"
                     + ("" if status == "ok" else f" (요청 {years}년보다 짧습니다)"),
                     f"{idx.min().date()} ~ {idx.max().date()} · {len(idx):,}행",
                     "" if status == "ok" else "소스가 보유한 이력이 짧거나 상장 이후 기간이 짧습니다."))

    trading_status = "ok" if 240 <= per_year <= 258 else "warn"
    out.append(Check("trading_days", "연간 거래일 수", trading_status,
                     "미국 거래일(약 252일) 범위 안" if trading_status == "ok"
                     else "거래일 수가 비정상입니다 — 누락 또는 중복 가능성",
                     f"{per_year:.1f}일/년"))

    dups = int(idx.duplicated().sum())
    out.append(Check("duplicates", "중복 날짜", "ok" if dups == 0 else "fail",
                     "중복 없음" if dups == 0 else f"{dups}개 날짜가 중복됩니다",
                     f"{dups}개",
                     "" if dups == 0 else "로더가 마지막 값만 남기지만, 소스 이상을 의심해야 합니다."))

    gaps = _bd_gaps(idx)
    big = gaps[gaps > 5]
    worst = f"{gaps.max():.0f}영업일" if len(gaps) else "–"
    out.append(Check("gaps", "연속성(공백)", "ok" if big.empty else "warn",
                     "5영업일 넘는 공백 없음" if big.empty
                     else f"5영업일 넘는 공백 {len(big)}건 (최대 {worst}, "
                          + ", ".join(str(d.date()) for d in big.sort_values(ascending=False).index[:3]) + " …)",
                     f"최대 {worst}",
                     "" if big.empty else "해당 구간을 지나는 forward return 은 실제보다 긴 기간을 재게 됩니다."))

    missing = {c: int(df[c].isna().sum()) for c in df.columns}
    bad = {k: v for k, v in missing.items() if v}
    out.append(Check("missing", "결측치", "ok" if not bad else "warn",
                     "없음" if not bad else ", ".join(f"{k} {v}개" for k, v in bad.items()),
                     f"{sum(missing.values())}개"))

    last = idx.max()
    stale_bd = int(np.busday_count(last.date(), pd.Timestamp.today().date()))
    status = "ok" if stale_bd <= 3 else ("warn" if stale_bd <= 10 else "fail")
    out.append(Check("stale", "최신성", status,
                     f"마지막 봉이 {stale_bd}영업일 전" + ("" if status == "ok" else " — 캐시가 오래됐거나 소스가 멈췄습니다"),
                     f"{last.date()}",
                     "" if status == "ok" else "사이드바의 '데이터 새로고침(캐시 비우기)' 후 다시 시도하세요."))
    return out


def check_prices(df: pd.DataFrame) -> list[Check]:
    out: list[Check] = []
    o, h, l, c = (df.get(k) for k in ("open", "high", "low", "close"))
    bad_hl = int((h < l).sum())
    bad_c = int(((c > h + 1e-9) | (c < l - 1e-9)).sum())
    nonpos = int((c <= 0).sum())
    broken = bad_hl + bad_c + nonpos
    out.append(Check("ohlc", "OHLC 정합성", "ok" if broken == 0 else "fail",
                     "고가≥저가, 종가가 범위 안" if broken == 0
                     else f"high<low {bad_hl}건 · 종가 범위 밖 {bad_c}건 · 0 이하 {nonpos}건",
                     f"{broken}건"))

    ret = c.pct_change() * 100
    ext = int((ret.abs() > 15).sum())
    out.append(Check("extreme", "극단 일간 변동(±15%)", "ok" if ext <= 5 else "warn",
                     f"{ext}일 — 지수라면 1987/2020 같은 날만 해당해야 합니다",
                     f"{ext}일",
                     "" if ext <= 5 else "분할·통화 변경 등으로 가격이 튀었을 수 있습니다."))
    return out


def check_volume(df: pd.DataFrame, ticker: str) -> list[Check]:
    """Is this volume series usable for distribution-day counting?"""
    out: list[Check] = []
    v = df["volume"] if "volume" in df.columns else pd.Series(dtype=float)
    n = len(v)
    if n == 0:
        return [Check("volume", "거래량", "fail", "거래량 컬럼이 없습니다.", "–",
                      "분산일 분석을 쓸 수 없습니다.")]

    usable = v.notna() & (v > 0)
    ratio = float(usable.mean())
    recent = v.tail(60)
    recent_bad = int((recent.isna() | (recent <= 0)).sum())
    suggestion = (
        f"{ticker} 의 거래량이 분산일 판정에 부적합합니다. 대안: "
        "① QQQ / ONEQ 등 추종 ETF 의 거래량을 대용치로 사용, "
        "② Stooq(^ndq) 등 다른 소스의 같은 지수 거래량, "
        "③ 지수 대신 ETF(QQQ) 자체를 티커로 분석, "
        "④ 거래량 조건(Y)을 끄고 하락률·CLV 두 조건만으로 분산일을 정의."
    )
    if ratio >= VOLUME_OK_RATIO and recent_bad == 0:
        status, detail = "ok", "결측·0 거래량이 사실상 없음 — 분산일 판정에 사용 가능"
        suggestion = ""
    elif ratio >= VOLUME_WARN_RATIO:
        status = "warn"
        detail = (f"{(1 - ratio) * 100:.1f}% 가 결측이거나 0 입니다"
                  + (f" (최근 60봉 중 {recent_bad}봉 포함)" if recent_bad else ""))
    else:
        status = "fail"
        detail = f"사용 가능한 거래량이 {ratio * 100:.1f}% 뿐입니다 — 분산일 개수를 신뢰할 수 없습니다"
    out.append(Check("volume_usable", "거래량 사용 가능성", status, detail,
                     f"유효 {ratio * 100:.1f}%", suggestion))

    # 단위가 도중에 바뀌면(주 → 천주 등) 전일 대비 배수 조건이 통째로 무너진다.
    med = v.where(usable).rolling(60, min_periods=30).median().dropna()
    if len(med) > 120:
        step = (med / med.shift(60)).dropna()
        jump = float(step.max()) if len(step) else 1.0
        drop = float(step.min()) if len(step) else 1.0
        unit_bad = jump > 5 or drop < 0.2
        out.append(Check("volume_unit", "거래량 단위 일관성", "warn" if unit_bad else "ok",
                         "60일 중앙값이 5배 이상 급변한 구간이 있습니다 — 단위 변경 의심"
                         if unit_bad else "전 구간 단위가 일관됩니다",
                         f"중앙값 변화 배수 {drop:.2f}~{jump:.2f}",
                         "단위가 바뀐 구간에서는 '거래량 ≥ 전일×(1+Y%)' 조건이 왜곡됩니다." if unit_bad else ""))

    ratio_series = (v / v.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
    if len(ratio_series):
        med_ratio = float(ratio_series.median())
        sane = 0.8 <= med_ratio <= 1.25
        out.append(Check("volume_ratio", "전일 대비 거래량 배수 분포", "ok" if sane else "warn",
                         f"중앙값 {med_ratio:.2f} — 1.0 근처가 정상" if sane
                         else f"중앙값 {med_ratio:.2f} 로 치우쳐 있습니다",
                         f"중앙값 {med_ratio:.2f}"))

    if ticker.startswith("^"):
        out.append(Check("volume_definition", "거래량 정의", "info",
                         "지수 거래량은 구성종목 합산(composite)이라 개별 종목 거래량과 정의가 다릅니다. "
                         "분산일의 '거래량 증가'는 시장 전체 매도 압력의 대용치로만 해석하세요.",
                         "composite",
                         "^IXIC 의 Yahoo 거래량은 나스닥 상장 종목 합산 거래량이며, 장중/당일 값은 확정 전 수치일 수 있습니다."))
    return out


def check_yield(series: pd.Series, symbol: str, label: str,
                declared_unit: str = "percent") -> list[Check]:
    """Is the macro series really a yield, and in which unit?"""
    out: list[Check] = []
    s = series.dropna()
    if s.empty:
        # 매크로는 선택 입력이다 — 없으면 해당 feature 만 빠지고 분석은 그대로 돈다.
        # 분석을 막는 fail 이 아니라 warn 으로 둔다.
        return [Check("yield_data", label, "warn", "데이터를 받지 못했습니다 — 매크로 feature 없이 분석합니다.",
                      "–", f"{symbol} 을(를) 자동 수신할 수 없다면 10년물 CSV/XLSX 를 직접 업로드하세요.")]

    med = float(s.median())
    if med < 0.2:
        unit, transform = "decimal (0.0428 = 4.28%)", "×100 필요"
        status = "fail"
    elif med <= 20:
        unit, transform, status = "percent (4.28 = 4.28%)", "변환 없음", "ok"
    elif med <= 200:
        unit, transform, status = "tenths (42.8 = 4.28%)", "÷10 적용됨", "warn"
    else:
        unit, transform, status = "basis points (428 = 4.28%)", "÷100 필요", "fail"
    out.append(Check("yield_unit", f"{label} 단위", status,
                     f"추정 단위 {unit} · 로더 처리: {transform} · 선언 단위 '{declared_unit}'",
                     f"중앙값 {med:.2f} · 범위 {s.min():.2f}~{s.max():.2f}",
                     "" if status == "ok" else
                     "loader._normalise_unit 이 퍼센트로 맞춥니다. 그래도 범위가 이상하면 소스를 바꾸세요."))

    lo, hi = YIELD_SANE_RANGE
    inside = float(((s >= lo) & (s <= hi)).mean())
    ok_range = inside > 0.98
    out.append(Check("yield_range", f"{label} 값 범위", "ok" if ok_range else "fail",
                     f"{inside * 100:.1f}% 가 {lo}~{hi}% 안에 있습니다 — 수익률(yield) 시계열로 보입니다"
                     if ok_range else
                     f"{(1 - inside) * 100:.1f}% 가 상식 범위를 벗어납니다 — 가격 지수이거나 단위가 다를 수 있습니다",
                     f"{s.min():.2f}~{s.max():.2f}%",
                     "" if ok_range else "^TNX(수익률) 대신 채권 가격/선물을 받았는지 확인하세요."))

    d = (s.diff().abs() * 100).dropna()          # bp
    wild = int((d > 50).sum())
    out.append(Check("yield_jumps", f"{label} 일간 변동", "ok" if wild <= 3 else "warn",
                     f"하루 50bp 넘게 움직인 날 {wild}일" + (" — 정상 범위" if wild <= 3 else " — 소스 오류 의심"),
                     f"최대 {d.max():.0f}bp" if len(d) else "–"))
    return out


def check_alignment(calendar: pd.DatetimeIndex, aligned: pd.Series, label: str) -> list[Check]:
    """How much of the aligned macro column is real vs forward-filled."""
    if aligned is None or aligned.dropna().empty:
        # 매크로가 통째로 비어 있는 것은 "분석 불가"가 아니라 "이 feature 없이 진행".
        return [Check("align", f"{label} 정렬", "warn",
                      "거래일 달력에 맞춘 값이 없습니다 — 매크로 feature 없이 분석합니다.", "0%",
                      "10년물 CSV/XLSX 를 직접 올리면 매크로 feature 가 함께 계산됩니다.")]
    coverage = float(aligned.notna().mean())
    # forward-fill 로 채워진 날 = 값은 있으나 직전 값과 완전히 같은 날의 상한 추정
    filled = float((aligned.diff() == 0).mean())
    status = "ok" if coverage > 0.98 else ("warn" if coverage > 0.9 else "fail")
    return [Check("align", f"{label} 정렬 커버리지", status,
                  f"거래일의 {coverage * 100:.1f}% 에 값이 있습니다 "
                  f"(그 중 {filled * 100:.1f}% 는 전일과 동일 — forward-fill 포함)",
                  f"{coverage * 100:.1f}%",
                  "" if status == "ok" else "빈 날의 매크로 feature 는 결측이 되어 매칭 후보에서 빠집니다.")]


def check_distribution_day(market, params) -> list[Check]:
    """Do the current thresholds actually find anything?"""
    from .features.distribution import flags

    f = flags(market, params)
    n = int(f["dd_flag"].sum())
    per_year = n / max(1e-9, (market.calendar.max() - market.calendar.min()).days / 365.25)
    dp = params.distribution
    if n == 0:
        status = "fail"
        detail = "현재 임계값으로 분산일이 한 번도 잡히지 않습니다 — 조건이 과도하게 엄격하거나 거래량이 비어 있습니다"
    elif per_year < 3:
        status, detail = "warn", f"연 {per_year:.1f}회로 너무 드뭅니다 — 임계값을 완화해 보세요"
    elif per_year > 60:
        status, detail = "warn", f"연 {per_year:.1f}회로 너무 흔합니다 — 신호로서 변별력이 약합니다"
    else:
        status, detail = "ok", f"연 {per_year:.1f}회 — 신호로 쓸 만한 빈도입니다"
    return [Check("dd_rate", "분산일 검출 빈도", status, detail, f"총 {n}일",
                  f"현재 조건: r ≤ -{dp.drop_pct}% · V ≥ 전일×{1 + dp.volume_bump_pct / 100:.2f} · CLV ≤ {dp.clv_max}")]


def check_sources(market, params) -> list[Check]:
    """Where each stream came from — and, for a proxy volume, a loud warning."""
    srcs = market.meta.get("sources", {}) or {}
    ticker = market.ticker
    name = INDEX_NAMES.get(ticker.upper(), ticker)
    out: list[Check] = []

    price = srcs.get("price", {})
    out.append(Check("price_source", "가격 데이터 소스", "info",
                     f"{KIND_LABELS.get(price.get('kind'), price.get('kind'))} · {price.get('name')}",
                     f"{price.get('first')} ~ {price.get('last')} · {price.get('rows', 0):,}행"))

    vol = srcs.get("volume", {})
    kind = vol.get("kind")
    if kind == "proxy":
        out.append(Check("volume_source", "거래량 데이터 소스", "warn",
                         f"Volume Source: {vol.get('name')} — not {name} volume",
                         f"{vol.get('usable', 0):,}개 사용 가능",
                         "대용 거래량입니다. 분산일 개수는 지수 자체의 거래량이 아니라 "
                         "이 종목의 거래량으로 계산됩니다 — 해석에 반드시 반영하세요."))
    else:
        out.append(Check("volume_source", "거래량 데이터 소스", "info",
                         f"{KIND_LABELS.get(kind, kind)} · {vol.get('name')}",
                         f"{vol.get('usable', 0):,}개 사용 가능"))

    merge = (vol.get("merge") or {})
    if merge:
        cov = float(merge.get("coverage", 0))
        status = "ok" if cov >= 0.98 else ("warn" if cov >= 0.9 else "fail")
        out.append(Check("volume_merge", "가격·거래량 병합 커버리지", status,
                         f"가격 {merge.get('price_rows', 0):,}행 중 {merge.get('matched', 0):,}행에 "
                         f"거래량이 붙었습니다 (거래량 없는 날 {merge.get('price_without_volume', 0):,}행, "
                         f"쓰이지 않은 거래량 행 {merge.get('volume_unused', 0):,}행)",
                         f"{cov * 100:.1f}%",
                         "" if status == "ok" else
                         "날짜 기준 정확 매칭만 합니다(거래량은 forward-fill 하지 않음). "
                         "두 파일의 날짜 형식·기간이 같은지 확인하세요."))
    return out


def data_source_summary(market) -> pd.DataFrame:
    """One table: what fed the price, the volume and each macro series."""
    srcs = market.meta.get("sources", {}) or {}
    rows = []

    def add(label: str, entry: dict) -> None:
        if not entry:
            return
        rows.append({
            "스트림": label,
            "입력 방식": KIND_LABELS.get(entry.get("kind"), entry.get("kind")),
            "파일명 / 제공자": entry.get("name"),
            "기간": f"{entry.get('first')} ~ {entry.get('last')}",
            "행 수": entry.get("rows", 0),
            "사용 가능 관측치": entry.get("usable", 0),
        })

    add("Price (OHLC)", srcs.get("price", {}))
    add("Volume", srcs.get("volume", {}))
    for key, entry in srcs.items():
        if str(key).startswith("exog:"):
            add(f"Macro · {str(key).split(':', 1)[1]}", entry)
    return pd.DataFrame(rows)


def run_checks(market, params) -> list[QualityReport]:
    """Full data-quality sweep for one loaded market snapshot."""
    reports: list[QualityReport] = []

    price = QualityReport(series=market.ticker)
    price.add(*check_sources(market, params))
    price.add(*check_calendar(market.ticker, market.prices, params.years))
    price.add(*check_prices(market.prices))
    price.add(*check_volume(market.prices, market.ticker))
    price.add(*check_distribution_day(market, params))
    meta = market.meta.get("series", {}).get(market.ticker, {})
    if meta.get("source") == "synthetic":
        price.add(Check("source", "데이터 출처", "warn",
                        "synthetic — 합성 데이터이므로 실제 시장이 아닙니다", "synthetic"))
    reports.append(price)

    for spec in params.exogenous or ():
        key, symbol = str(spec.get("key")), str(spec.get("symbol"))
        label = str(spec.get("label", symbol))
        rep = QualityReport(series=symbol)
        aligned = market.exog[key] if (market.exog is not None and key in market.exog.columns) else None
        if aligned is None:
            rep.add(Check("missing_series", label, "warn",
                          "시리즈를 받지 못했습니다 — 매크로 feature 없이 분석합니다.", "–",
                          f"{symbol} 을(를) 자동 수신할 수 없다면 파일로 직접 올릴 수 있습니다."))
        else:
            rep.add(*check_yield(aligned, symbol, label, str(spec.get("unit", ""))))
            rep.add(*check_alignment(market.calendar, aligned, label))
            info = market.meta.get("series", {}).get(symbol, {})
            stale = info.get("stale_days")
            rep.add(Check("exog_source", f"{label} 출처/최신성",
                          "ok" if (stale or 0) <= 5 else "warn",
                          f"{info.get('source')} · 마지막 실관측 {info.get('last_date')}"
                          + (f" ({stale}일 전)" if stale else ""),
                          str(info.get("source"))))
        reports.append(rep)
    return reports


def summary_frame(reports: list[QualityReport]) -> pd.DataFrame:
    frames = [r.frame() for r in reports if len(r.checks)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def overall_status(reports: list[QualityReport]) -> str:
    worst = max((r.status for r in reports), key=lambda s: STATUS_ORDER[s], default="ok")
    return "ok" if worst == "info" else worst


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Market Regime Lab — data quality check")
    ap.add_argument("--ticker", default=None, help="기본값은 regime_config.yaml 의 티커")
    ap.add_argument("--years", type=int, default=None)
    ap.add_argument("--demo", action="store_true", help="네트워크 없이 합성 데이터로 실행")
    ap.add_argument("--no-cache", action="store_true", help="디스크 캐시를 무시하고 새로 받기")
    args = ap.parse_args(argv)

    from .config import Params, load_config
    from .data import load_market

    params = Params.from_config(load_config())
    ticker = args.ticker or params.ticker
    years = args.years or params.years
    params = replace(params, ticker=ticker, years=years)
    market = load_market(ticker, years, params.exogenous,
                         source="synthetic" if args.demo else "auto",
                         use_cache=not args.no_cache)
    if market.empty:
        print(f"[FAIL] {ticker} 데이터를 받지 못했습니다 "
              f"(네트워크 차단 환경이면 --demo 로 파이프라인만 확인할 수 있습니다).")
        return 2

    reports = run_checks(market, params)
    frame = summary_frame(reports)
    with pd.option_context("display.max_colwidth", 90, "display.width", 200):
        print(frame.to_string(index=False))
    status = overall_status(reports)
    print(f"\n종합 판정: {STATUS_ICON[status]} {status.upper()}")
    for rep in reports:
        for c in rep.problems():
            if c.suggestion:
                print(f"  - [{rep.series}] {c.label}: {c.suggestion}")
    return {"ok": 0, "warn": 0, "fail": 1}[status]


if __name__ == "__main__":
    raise SystemExit(main())
