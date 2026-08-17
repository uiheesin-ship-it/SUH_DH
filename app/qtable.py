"""분기 실적표 — 과거 가이던스 / 컨센서스 / 실적 / 향후 가이던스를 한 표로.

티커 하나를 넣으면 **최근 발표 분기**를 기준으로 이전 6개 분기 + 향후 4개 분기를
열로 세우고, 다섯 개의 행 블록을 채웁니다.

    과거 가이던스        그 분기를 앞두고 회사가 제시했던 가이던스
    컨센서스             발표 직전 애널리스트 컨센서스
    실적                 실제 발표치
    향후 가이던스(연간)   그 분기 발표 때 함께 제시한 연간(FY) 가이던스
    향후 가이던스(QoQ)    그 분기 발표 때 함께 제시한 차분기 가이던스

각 블록의 행은 매출 / 영업이익 / EBITDA / EPS 입니다.

자동으로 채워지는 것 vs 큐레이션이 필요한 것
--------------------------------------------
Yahoo(yfinance)로 자동으로 채워지는 부분:

* **실적** — 분기 손익계산서(매출/영업이익/EBITDA/EPS). EBITDA 행이 없으면
  영업이익 + 감가상각비로 역산합니다(출처 ``derived``).
* **컨센서스(EPS)** — ``get_earnings_dates()`` 의 ``EPS Estimate`` 는 과거 분기와
  예정 분기를 함께 주므로 그대로 씁니다.
* **컨센서스(매출·EPS, 향후 2개 분기)** — ``revenue_estimate`` / ``earnings_estimate``
  의 ``0q``(진행 중인 분기) / ``+1q``.

무료 API에 **없는** 부분 — 회사 가이던스(과거·향후, 연간·QoQ) 전체와 과거 분기의
매출 컨센서스 — 은 ``data/guidance_table.json`` 큐레이션 파일에서 가져옵니다
(기존 ``data/guidance.json`` 과 같은 방식: 보도자료·실적발표 자료를 보고 손으로 입력,
출처 링크 포함). 큐레이션 값은 항상 자동 수집값을 **덮어씁니다** — 회사가 발표하는
non-GAAP 영업이익/EBITDA/EPS 는 Yahoo 의 GAAP 수치와 다르기 때문입니다.

단위는 내부적으로 모두 **백만(달러 등 재무제표 통화)** 으로 정규화하고, 출력할 때만
백만/십억으로 환산합니다. EPS 는 주당 금액 그대로입니다.
"""

from __future__ import annotations

import calendar
import json
import math
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

from . import cache

QTABLE_TTL = float(os.environ.get("SUH_DH_QTABLE_TTL", "1800"))

# 열 개수: 최근 발표 분기를 포함한 과거 6개 + 미발표 4개 = 10개.
PAST_QUARTERS = int(os.environ.get("SUH_DH_QTABLE_PAST", "6"))
AHEAD_QUARTERS = int(os.environ.get("SUH_DH_QTABLE_AHEAD", "4"))

# 큐레이션 파일(가이던스·과거 컨센서스). 경로는 SUH_DH_QTABLE_FILE 로 교체 가능.
QTABLE_FILE = os.environ.get("SUH_DH_QTABLE_FILE") or str(
    Path(__file__).resolve().parent.parent / "data" / "guidance_table.json"
)

# 행(지표)과 행 블록(섹션) — 표에 나오는 순서 그대로.
METRICS: list[tuple[str, str]] = [
    ("revenue", "매출"),
    ("operating_income", "영업이익"),
    ("ebitda", "EBITDA"),
    ("eps", "EPS"),
]
SECTIONS: list[tuple[str, str]] = [
    ("past_guidance", "과거 가이던스"),
    ("consensus", "컨센서스"),
    ("actual", "실적"),
    ("fwd_annual", "향후 가이던스(연간)"),
    ("fwd_qoq", "향후 가이던스(QoQ)"),
]

METRIC_KEYS = [m for m, _ in METRICS]
SECTION_KEYS = [s for s, _ in SECTIONS]

# 손익계산서 행 이름(야후는 표기가 조금씩 달라 별칭을 함께 본다). 소문자·공백제거
# 후 비교하므로 여기 표기는 사람이 읽기 좋은 형태로 둔다.
ROW_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("Total Revenue", "Operating Revenue", "Revenue"),
    "operating_income": ("Operating Income", "Total Operating Income As Reported", "EBIT"),
    "ebitda": ("EBITDA", "Normalized EBITDA"),
    "eps": ("Diluted EPS", "Basic EPS"),
}
# EBITDA 행이 없을 때 영업이익에 더해 역산할 감가상각비 후보.
DA_ALIASES = (
    "Reconciled Depreciation",
    "Depreciation And Amortization In Income Statement",
    "Depreciation Amortization Depletion Income Statement",
    "Depreciation Amortization Depletion",
    "Depreciation And Amortization",
)

# 지표별 성격: 금액(백만 단위 환산 대상)인지 주당 금액인지.
PER_SHARE = {"eps"}


# --------------------------------------------------------------------------- #
# 작은 유틸
# --------------------------------------------------------------------------- #
def _demo() -> bool:
    return os.environ.get("SUH_DH_DEMO", "") not in ("", "0", "false", "False")


def _num(x) -> float | None:
    """pandas NaN / None / 문자열을 float 또는 None 으로."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _norm_key(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


# --------------------------------------------------------------------------- #
# 회계 분기 계산
# --------------------------------------------------------------------------- #
# 표의 열 이름은 회사의 **회계연도** 기준입니다. 예) 디지털터빈은 3월 결산이라
# 2026년 3월 마감 분기가 "2026 4Q", 2026년 6월 마감 분기가 "2027 1Q" 입니다.
# 회계연도 번호는 "그 회계연도가 끝나는 달력연도" 규칙을 씁니다(대다수 미국 기업).

_PERIOD_RE = re.compile(r"^(?:FY)?(\d{2,4})[\s_\-./]*(?:Q([1-4])|([1-4])Q)$", re.I)
_FY_RE = re.compile(r"^(?:FY)?(\d{2,4})$", re.I)


def _full_year(y: int) -> int:
    """두 자리 연도(26)를 네 자리(2026)로."""
    return y + 2000 if y < 100 else y


def parse_period(s) -> tuple[int, int] | None:
    """``FY2026Q4`` / ``2026Q4`` / ``2026 4Q`` / ``FY26 4Q`` → ``(2026, 4)``."""
    if isinstance(s, (list, tuple)) and len(s) == 2:
        try:
            return _full_year(int(s[0])), int(s[1])
        except (TypeError, ValueError):
            return None
    if isinstance(s, dict):
        fy, fq = s.get("fy"), s.get("fq")
        if fy is None or fq is None:
            return None
        try:
            return _full_year(int(fy)), int(fq)
        except (TypeError, ValueError):
            return None
    if not isinstance(s, str):
        return None
    m = _PERIOD_RE.match(s.strip())
    if not m:
        return None
    return _full_year(int(m.group(1))), int(m.group(2) or m.group(3))


def parse_fy(s) -> int | None:
    """``FY2027`` / ``2027`` / ``FY27`` → ``2027``."""
    if isinstance(s, int):
        return _full_year(s)
    if not isinstance(s, str):
        return None
    m = _FY_RE.match(s.strip())
    return _full_year(int(m.group(1))) if m else None


def q_index(fy: int, fq: int) -> int:
    """분기를 하나의 정수 축으로 (열 이동·정렬용)."""
    return fy * 4 + (fq - 1)


def from_index(i: int) -> tuple[int, int]:
    fy, r = divmod(i, 4)
    return fy, r + 1


def period_label(fy: int, fq: int) -> str:
    return f"{fy} {fq}Q"


def fy_label(fy: int) -> str:
    """``2027`` → ``FY27`` (표에 쓰는 짧은 표기)."""
    return f"FY{fy % 100:02d}"


def _month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def quarter_end(fy: int, fq: int, fy_end_month: int) -> date:
    """회계분기의 마감일(월말 기준)."""
    y, m = fy, fy_end_month - (4 - fq) * 3
    while m <= 0:
        m += 12
        y -= 1
    return _month_end(y, m)


def _effective_month(d: date) -> tuple[int, int]:
    """52/53주 회계달력 보정: 3일 마감처럼 초순이면 전월 마감으로 본다."""
    if d.day <= 6:
        y, m = (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)
        return y, m
    return d.year, d.month


def period_from_end(d: date, fy_end_month: int) -> tuple[int, int]:
    """분기 **마감일** → ``(회계연도, 분기)``."""
    y, m = _effective_month(d)
    diff = (fy_end_month - m) % 12       # 회계연말까지 남은 개월 수
    fq = 4 - diff // 3
    fy = y if m <= fy_end_month else y + 1
    return fy, fq


def period_from_report(d: date, fy_end_month: int) -> tuple[int, int]:
    """실적 **발표일** → 그 발표가 다루는 ``(회계연도, 분기)``.

    발표는 분기 마감 뒤 2~10주쯤에 나오므로, 발표일에서 열흘을 뺀 시점 이전에
    끝난 가장 최근 회계분기를 그 발표의 분기로 본다.
    """
    ordinal = d.toordinal() - 10
    fy, fq = period_from_end(date.fromordinal(ordinal), fy_end_month)
    # 위 계산은 "그 날짜가 속한 분기"라서, 아직 안 끝난 분기가 나올 수 있다.
    if quarter_end(fy, fq, fy_end_month).toordinal() > ordinal:
        fy, fq = from_index(q_index(fy, fq) - 1)
    return fy, fq


# --------------------------------------------------------------------------- #
# 큐레이션 파일
# --------------------------------------------------------------------------- #
def _load_curated() -> dict:
    path = Path(QTABLE_FILE)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def curated_tickers() -> list[str]:
    """큐레이션 데이터가 입력된 티커 목록(정렬)."""
    return sorted(t for t in _load_curated() if not t.startswith("_"))


def _ticker_block(ticker: str) -> tuple[dict, list[dict]]:
    """티커별 ``(meta, entries)``. 값이 리스트면 entries 로만 본다."""
    block = _load_curated().get(ticker.upper())
    if isinstance(block, list):
        return {}, block
    if isinstance(block, dict):
        meta = block.get("meta") if isinstance(block.get("meta"), dict) else {}
        entries = block.get("entries")
        return meta or {}, entries if isinstance(entries, list) else []
    return {}, []


# 단위 문자열 → 백만 단위로 바꾸는 배수.
_UNIT_SCALE = {
    "": 1.0, "m": 1.0, "m_usd": 1.0, "musd": 1.0, "mn": 1.0, "million": 1.0,
    "b": 1000.0, "b_usd": 1000.0, "busd": 1000.0, "bn": 1000.0, "billion": 1000.0,
    "k": 0.001, "thousand": 0.001,
    "usd": 1.0, "raw": 1e-6,
}


def _unit_scale(unit, metric: str) -> float:
    """금액 항목만 환산한다(EPS 는 주당 금액이라 그대로)."""
    if metric in PER_SHARE or unit is None:
        return 1.0
    key = _norm_key(unit)
    return _UNIT_SCALE.get(key.replace("usd", "") or key, 1.0)


# 큐레이션 kind → (기본 배치 섹션, 그 섹션이 쓰는 기간 필드)
#   quarter_guidance : 분기 가이던스. 대상 분기(for)의 '과거 가이던스',
#                      제시한 분기(given_at)의 '향후 가이던스(QoQ)' 두 칸에 들어간다.
#   annual_guidance  : 연간 가이던스. 제시한 분기(given_at)의 '향후 가이던스(연간)'.
#   consensus/actual : 대상 분기(for)의 컨센서스/실적.
_KIND_PLACEMENT = {
    "quarter_guidance": (("past_guidance", "for"), ("fwd_qoq", "given_at")),
    "guidance": (("past_guidance", "for"), ("fwd_qoq", "given_at")),
    "annual_guidance": (("fwd_annual", "given_at"),),
    "consensus": (("consensus", "for"),),
    "actual": (("actual", "for"),),
}


def _normalize_entry(e: dict) -> dict | None:
    """큐레이션 한 줄을 내부 표현으로(단위 환산 + 기간 파싱)."""
    if not isinstance(e, dict):
        return None
    metric = _norm_key(e.get("metric"))
    metric = {"op_income": "operating_income", "operatingincome": "operating_income",
              "opincome": "operating_income", "revenue": "revenue", "sales": "revenue",
              "ebitda": "ebitda", "eps": "eps"}.get(metric, metric)
    if metric not in METRIC_KEYS:
        return None
    kind = _norm_key(e.get("kind")) or "quarterguidance"
    kind = {"quarterguidance": "quarter_guidance", "qoq": "quarter_guidance",
            "guidance": "quarter_guidance", "annualguidance": "annual_guidance",
            "annual": "annual_guidance", "fy": "annual_guidance",
            "consensus": "consensus", "actual": "actual", "result": "actual"}.get(kind, kind)
    if kind not in _KIND_PLACEMENT:
        return None

    scale = _unit_scale(e.get("unit"), metric)
    low = _num(e.get("low"))
    high = _num(e.get("high"))
    value = _num(e.get("value"))
    if value is None:
        value = _num(e.get("mid"))
    if value is None and low is not None and high is not None:
        value = (low + high) / 2
    return {
        "kind": kind,
        "metric": metric,
        "for": parse_period(e.get("for") or e.get("for_period") or e.get("period")),
        "for_fy": parse_fy(e.get("for_fy") or e.get("fy") or e.get("for") or e.get("period")),
        "given_at": parse_period(e.get("given_at") or e.get("report_period")),
        "low": low * scale if low is not None else None,
        "high": high * scale if high is not None else None,
        "value": value * scale if value is not None else None,
        "text": (e.get("text") or "").strip() or None,
        "sections": [s for s in (e.get("sections") or []) if s in SECTION_KEYS] or None,
        "note": e.get("note"),
        "sources": e.get("sources") or ([e["source"]] if e.get("source") else []),
    }


def _index_curated(entries: list[dict]) -> dict[tuple[str, str, int], dict]:
    """``(섹션, 지표, 분기인덱스) → 엔트리`` 로 펼친다."""
    out: dict[tuple[str, str, int], dict] = {}
    for raw in entries or []:
        e = _normalize_entry(raw)
        if not e:
            continue
        for section, field in _KIND_PLACEMENT[e["kind"]]:
            if e["sections"] and section not in e["sections"]:
                continue
            period = e[field]
            if not period:
                continue
            out[(section, e["metric"], q_index(*period))] = e
    return out


# --------------------------------------------------------------------------- #
# yfinance 수집
# --------------------------------------------------------------------------- #
def _to_date(x) -> date | None:
    if isinstance(x, date) and not isinstance(x, datetime):
        return x
    if isinstance(x, datetime):
        return x.date()
    try:  # pandas Timestamp
        return x.to_pydatetime().date()
    except Exception:
        pass
    try:
        return datetime.strptime(str(x)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _first_frame(tk, attrs: tuple[str, ...]):
    """여러 후보 속성 중 비어 있지 않은 첫 DataFrame."""
    for attr in attrs:
        try:
            obj = getattr(tk, attr, None)
            df = obj() if callable(obj) else obj
        except Exception:
            continue
        if df is not None and getattr(df, "empty", True) is False:
            return df
    return None


def _rows_by_key(df) -> dict[str, dict]:
    """손익계산서를 ``정규화행이름 → {열: 값}`` 으로."""
    out: dict[str, dict] = {}
    for idx in list(getattr(df, "index", [])):
        try:
            out[_norm_key(idx)] = df.loc[idx]
        except Exception:
            continue
    return out


def _pick_row(rows: dict[str, dict], aliases: tuple[str, ...]):
    for name in aliases:
        row = rows.get(_norm_key(name))
        if row is not None:
            return row
    return None


def _fy_end_month(tk, statements: list) -> int:
    """결산월. info 의 lastFiscalYearEnd → 연간 재무제표 열 → 12월 순으로."""
    try:
        info = tk.info or {}
    except Exception:
        info = {}
    ts = info.get("lastFiscalYearEnd") or info.get("nextFiscalYearEnd")
    if ts:
        try:
            d = datetime.fromtimestamp(float(ts), tz=timezone.utc).date()
            return _effective_month(d)[1]
        except Exception:
            pass
    for df in statements:
        months = [_effective_month(d)[1] for d in
                  (_to_date(c) for c in getattr(df, "columns", [])) if d]
        if months:
            return max(set(months), key=months.count)
    return 12


def _fetch_statements(tk) -> dict:
    """분기 손익계산서 → ``{분기마감일: {지표: 값(백만)}}`` + 결산월."""
    qdf = _first_frame(tk, ("quarterly_income_stmt", "quarterly_incomestmt",
                            "quarterly_financials"))
    adf = _first_frame(tk, ("income_stmt", "incomestmt", "financials"))
    fy_end = _fy_end_month(tk, [adf, qdf] if adf is not None else [qdf])
    quarters: dict[tuple[int, int], dict] = {}
    if qdf is None:
        return {"fy_end_month": fy_end, "quarters": quarters}

    rows = _rows_by_key(qdf)
    picked = {m: _pick_row(rows, aliases) for m, aliases in ROW_ALIASES.items()}
    da_row = _pick_row(rows, DA_ALIASES)
    for col in list(qdf.columns):
        d = _to_date(col)
        if not d:
            continue
        period = period_from_end(d, fy_end)
        vals: dict[str, dict] = {}
        for metric, row in picked.items():
            if row is None:
                continue
            v = _num(row.get(col))
            if v is None:
                continue
            if metric not in PER_SHARE:
                v = v / 1e6
            vals[metric] = {"value": v, "source": "yfinance"}
        if "ebitda" not in vals and da_row is not None and "operating_income" in vals:
            da = _num(da_row.get(col))
            if da is not None:
                vals["ebitda"] = {"value": vals["operating_income"]["value"] + da / 1e6,
                                  "source": "derived",
                                  "note": "영업이익 + 감가상각비로 역산(GAAP)"}
        if vals:
            quarters[period] = {"period_end": d.isoformat(), **{k: v for k, v in vals.items()}}
    return {"fy_end_month": fy_end, "quarters": quarters}


def _fetch_earnings_dates(tk, fy_end_month: int, limit: int = 24) -> dict:
    """``get_earnings_dates()`` → ``{분기: {발표일, EPS 컨센서스/실제}}``."""
    out: dict[tuple[int, int], dict] = {}
    try:
        df = tk.get_earnings_dates(limit=limit)
    except Exception:
        df = None
    if df is None or getattr(df, "empty", True):
        return out
    cols = {_norm_key(c): c for c in df.columns}
    est_col = cols.get("epsestimate")
    rep_col = cols.get("reportedeps")
    today = date.today()
    for idx in list(df.index):
        d = _to_date(idx)
        if not d:
            continue
        period = period_from_report(d, fy_end_month)
        row = df.loc[idx]
        est = _num(row.get(est_col)) if est_col else None
        rep = _num(row.get(rep_col)) if rep_col else None
        prev = out.get(period)
        if prev and prev.get("eps_actual") is not None and rep is None:
            continue  # 같은 분기에 대한 중복 행: 값이 있는 쪽을 남긴다
        out[period] = {
            "report_date": d.isoformat(),
            "reported": rep is not None or d <= today,
            "eps_consensus": est,
            "eps_actual": rep,
        }
    return out


def _estimate_rows(df) -> dict[str, float | None]:
    """yfinance 추정치 프레임(0q/+1q/0y/+1y)의 ``avg`` 만 뽑는다."""
    out: dict[str, float | None] = {}
    if df is None:
        return out
    for key in ("0q", "+1q", "0y", "+1y"):
        try:
            if key not in list(getattr(df, "index", [])):
                continue
            row = df.loc[key]
            out[key] = _num(row.get("avg") if hasattr(row, "get") else row["avg"])
        except Exception:
            continue
    return out


def _fetch_forward_consensus(tk) -> dict:
    """향후 2개 분기 매출·EPS 컨센서스. 매출은 원화폐 단위 → 백만으로."""
    rev = _estimate_rows(_first_frame(tk, ("revenue_estimate", "get_revenue_estimate")))
    eps = _estimate_rows(_first_frame(tk, ("earnings_estimate", "get_earnings_estimate")))
    return {
        "revenue": {k: (v / 1e6 if v is not None else None) for k, v in rev.items()},
        "eps": eps,
    }


def _fetch_all(ticker: str) -> dict:
    import yfinance as yf

    tk = yf.Ticker(ticker)
    stmt = _fetch_statements(tk)
    fy_end = stmt["fy_end_month"]
    try:
        info = tk.info or {}
    except Exception:
        info = {}
    return {
        "fy_end_month": fy_end,
        "quarters": stmt["quarters"],
        "earnings": _fetch_earnings_dates(tk, fy_end),
        "forward": _fetch_forward_consensus(tk),
        "name": info.get("shortName") or info.get("longName"),
        "currency": info.get("financialCurrency") or info.get("currency") or "USD",
    }


# --------------------------------------------------------------------------- #
# 셀 만들기 / 숫자 포맷
# --------------------------------------------------------------------------- #
def _trim(v: float, digits: int) -> str:
    s = f"{v:,.{digits}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def fmt_value(v: float | None, metric: str, unit_scale: float = 1.0) -> str:
    """숫자 한 개를 표에 넣을 문자열로. ``unit_scale`` 은 백만→표시단위 배수."""
    if v is None:
        return ""
    if metric in PER_SHARE:
        return _trim(v, 2)
    scaled = v * unit_scale
    return _trim(scaled, 2 if abs(scaled) < 100 else 1)


def _cell(text: str = "", **kw) -> dict:
    cell = {"text": text}
    for k, v in kw.items():
        if v not in (None, [], ""):
            cell[k] = v
    return cell


def _range_text(low, high, value, metric, unit_scale) -> str:
    if low is not None and high is not None:
        return f"{fmt_value(low, metric, unit_scale)}~{fmt_value(high, metric, unit_scale)}"
    return fmt_value(value, metric, unit_scale)


def _curated_cell(e: dict, section: str, metric: str, unit_scale: float) -> dict:
    """큐레이션 엔트리 한 개 → 셀."""
    if e.get("text"):
        text = e["text"]
    else:
        text = _range_text(e.get("low"), e.get("high"), e.get("value"), metric, unit_scale)
        if section == "fwd_annual" and text and e.get("for_fy"):
            text = f"{fy_label(e['for_fy'])} {text}"
    return _cell(
        text,
        value=e.get("value"),
        low=e.get("low"),
        high=e.get("high"),
        source="curated",
        note=e.get("note"),
        sources=e.get("sources"),
    )


# --------------------------------------------------------------------------- #
# 표 조립
# --------------------------------------------------------------------------- #
def _pick_unit(quarters: dict, meta: dict) -> tuple[str, float, str]:
    """표시 단위 결정 → ``(키, 백만→표시 배수, 한국어 라벨)``."""
    want = _norm_key(meta.get("display_unit") or os.environ.get("SUH_DH_QTABLE_UNIT") or "auto")
    if want in ("b", "billion", "busd"):
        return "B", 0.001, "십억"
    if want in ("m", "million", "musd"):
        return "M", 1.0, "백만"
    revenues = [q["revenue"]["value"] for q in quarters.values()
                if isinstance(q.get("revenue"), dict) and q["revenue"].get("value") is not None]
    if revenues and max(abs(v) for v in revenues) >= 10_000:
        return "B", 0.001, "십억"
    return "M", 1.0, "백만"


def _anchor_index(fetched: dict, curated_idx: dict) -> int | None:
    """최근 **발표** 분기의 분기인덱스."""
    candidates: list[int] = []
    for period, vals in (fetched.get("quarters") or {}).items():
        if any(isinstance(v, dict) and v.get("value") is not None
               for k, v in vals.items() if k in METRIC_KEYS):
            candidates.append(q_index(*period))
    for period, e in (fetched.get("earnings") or {}).items():
        if e.get("eps_actual") is not None:
            candidates.append(q_index(*period))
    for (section, _metric, idx) in curated_idx:
        if section == "actual":
            candidates.append(idx)
    return max(candidates) if candidates else None


def _auto_cell(section: str, metric: str, idx: int, fetched: dict,
               anchor: int, unit_scale: float) -> dict | None:
    """자동 수집(yfinance) 값으로 채울 수 있으면 셀을 만든다."""
    period = from_index(idx)
    if section == "actual":
        if metric == "eps":
            e = (fetched.get("earnings") or {}).get(period) or {}
            if e.get("eps_actual") is not None:
                return _cell(fmt_value(e["eps_actual"], metric), value=e["eps_actual"],
                             source="yfinance", note="발표 EPS(야후 기준)")
        vals = (fetched.get("quarters") or {}).get(period) or {}
        got = vals.get(metric)
        if isinstance(got, dict) and got.get("value") is not None:
            return _cell(fmt_value(got["value"], metric, unit_scale), value=got["value"],
                         source=got.get("source", "yfinance"), note=got.get("note"))
        return None

    if section == "consensus":
        if metric == "eps":
            e = (fetched.get("earnings") or {}).get(period) or {}
            if e.get("eps_consensus") is not None:
                return _cell(fmt_value(e["eps_consensus"], metric), value=e["eps_consensus"],
                             source="yfinance", note="야후 EPS 컨센서스")
        # 매출·EPS 의 향후 2개 분기는 야후 추정치(0q/+1q)로.
        key = {anchor + 1: "0q", anchor + 2: "+1q"}.get(idx)
        if key and metric in ("revenue", "eps"):
            v = ((fetched.get("forward") or {}).get(metric) or {}).get(key)
            if v is not None:
                return _cell(fmt_value(v, metric, unit_scale), value=v, source="yfinance",
                             note=f"야후 예상치({key})")
        return None
    return None


def build_table(ticker: str, past: int = PAST_QUARTERS, ahead: int = AHEAD_QUARTERS) -> dict:
    """티커 하나의 분기 실적표(JSON 친화 dict)를 만든다."""
    ticker = ticker.upper().strip()
    meta, entries = _ticker_block(ticker)
    curated_idx = _index_curated(entries)

    fetched: dict = {"quarters": {}, "earnings": {}, "forward": {}, "currency": "USD"}
    fetch_error = None
    if not _demo():
        try:
            fetched = _fetch_all(ticker)
        except Exception as e:  # 네트워크/차단 — 큐레이션만으로라도 표를 그린다
            fetch_error = str(e)

    fy_end_month = int(meta.get("fy_end_month") or fetched.get("fy_end_month") or 12)
    anchor = _anchor_index(fetched, curated_idx)
    if anchor is None:
        # 발표 실적을 하나도 못 찾으면 오늘 기준 직전 분기를 기준점으로 삼는다.
        anchor = q_index(*period_from_report(date.today(), fy_end_month))

    start = anchor - past + 1
    indexes = list(range(start, anchor + ahead + 1))
    unit_key, unit_scale, unit_ko = _pick_unit(fetched.get("quarters") or {}, meta)

    columns = []
    for idx in indexes:
        fy, fq = from_index(idx)
        e = (fetched.get("earnings") or {}).get((fy, fq)) or {}
        columns.append({
            "fy": fy,
            "fq": fq,
            "label": period_label(fy, fq),
            "year": str(fy),
            "quarter": f"{fq}Q",
            "period_end": quarter_end(fy, fq, fy_end_month).isoformat(),
            "report_date": e.get("report_date"),
            "status": "reported" if idx <= anchor else "upcoming",
            "anchor": idx == anchor,
        })

    sections = []
    for skey, slabel in SECTIONS:
        rows = []
        for mkey, mlabel in METRICS:
            cells = []
            for idx in indexes:
                entry = curated_idx.get((skey, mkey, idx))
                if entry is not None:
                    cells.append(_curated_cell(entry, skey, mkey, unit_scale))
                    continue
                cells.append(_auto_cell(skey, mkey, idx, fetched, anchor, unit_scale)
                             or _cell())
            rows.append({"key": mkey, "label": mlabel, "cells": cells})
        sections.append({"key": skey, "label": slabel, "rows": rows})

    filled = sum(1 for s in sections for r in s["rows"] for c in r["cells"] if c["text"])
    anchor_fy, anchor_fq = from_index(anchor)
    return {
        "ticker": ticker,
        "name": meta.get("name") or fetched.get("name"),
        "currency": meta.get("currency") or fetched.get("currency") or "USD",
        "unit": unit_key,
        "unit_ko": unit_ko,
        "unit_label": f"{unit_ko} {meta.get('currency') or fetched.get('currency') or 'USD'} (EPS 는 주당)",
        "fy_end_month": fy_end_month,
        "basis": meta.get("basis"),
        "anchor": {
            "label": period_label(anchor_fy, anchor_fq),
            "fy": anchor_fy,
            "fq": anchor_fq,
            "report_date": ((fetched.get("earnings") or {})
                            .get((anchor_fy, anchor_fq)) or {}).get("report_date"),
        },
        "past": past,
        "ahead": ahead,
        "columns": columns,
        "sections": sections,
        "filled_cells": filled,
        "demo": _demo(),
        "curated": bool(entries),
        "curated_count": len(curated_idx),
        "fetch_error": fetch_error,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "notes": meta.get("notes") or [],
    }


def get_table(ticker: str, past: int = PAST_QUARTERS, ahead: int = AHEAD_QUARTERS) -> dict:
    """캐시를 씌운 :func:`build_table`."""
    ticker = ticker.upper().strip()
    return cache.get_or_set(
        f"qtable:{ticker}:{past}:{ahead}",
        QTABLE_TTL,
        lambda: build_table(ticker, past, ahead),
        # 실적이 하나도 안 채워진 결과(대개 일시적 차단)는 캐시에 고정하지 않는다.
        cache_when=lambda v: _demo() or v.get("filled_cells", 0) > 0,
    )


# --------------------------------------------------------------------------- #
# 표 → 격자(엑셀 붙여넣기용)
# --------------------------------------------------------------------------- #
def to_grid(table: dict) -> list[list[str]]:
    """표를 2차원 문자열 격자로. 사용자 스프레드시트와 같은 레이아웃."""
    cols = table["columns"]
    grid = [[""] + [c["year"] for c in cols], [""] + [c["quarter"] for c in cols]]
    for section in table["sections"]:
        grid.append([section["label"]] + [""] * len(cols))
        for row in section["rows"]:
            grid.append(["    " + row["label"]] + [c.get("text", "") for c in row["cells"]])
    return grid


def to_delimited(table: dict, sep: str = "\t") -> str:
    """격자를 TSV/CSV 문자열로(CSV 는 콤마·따옴표 처리 포함)."""
    lines = []
    for row in to_grid(table):
        if sep == ",":
            cells = [f'"{c}"' if ("," in c or '"' in c) else c
                     for c in (x.replace('"', '""') for x in row)]
        else:
            cells = row
        lines.append(sep.join(cells))
    return "\n".join(lines) + "\n"
