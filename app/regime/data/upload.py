"""Manual upload: turn a user's CSV/XLSX into exactly the frame the auto
downloader produces.

The analysis layers (features / similarity / forward / audit / validation)
never learn where the data came from — everything here ends in the same
normalised schema:

* prices : DatetimeIndex + ``open/high/low/close/volume`` (float)
* yields : DatetimeIndex + one float column, always in **percent**

What the parser has to survive, because real exports do this:

* column names in any language or spelling (``날짜``, ``Close/Last``, ``Vol.``)
  — hence :func:`suggest_mapping` proposes a mapping the user can correct;
* ``$1,234.56``, ``1,234,567``, ``(123)`` for negatives, ``1.2M``;
* Excel serial dates, DD/MM/YYYY, YYYY-MM-DD;
* duplicated and unparseable rows — these are *reported*, never silently
  dropped, because a quietly discarded row changes every rolling window
  downstream.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np
import pandas as pd

PRICE_FIELDS = ("date", "open", "high", "low", "close", "volume")
YIELD_FIELDS = ("date", "yield")

# 별칭은 정규화(소문자·영숫자만) 후 비교한다.
ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "날짜", "일자", "기준일", "datetime", "time", "timestamp", "일시",
             "tradedate", "dt", "index", "observationdate", "period"),
    "open": ("open", "시가", "openprice", "시작가", "o"),
    "high": ("high", "고가", "highprice", "h"),
    "low": ("low", "저가", "lowprice", "l"),
    "close": ("close", "종가", "closelast", "adjclose", "adjustedclose", "last",
              "lastprice", "closeprice", "price", "c", "settle"),
    "volume": ("volume", "거래량", "vol", "totalvolume", "shares", "v", "거래수량"),
    "yield": ("yield", "금리", "수익률", "rate", "dgs10", "value", "close", "종가",
              "10y", "tnx", "yieldpct", "국채금리"),
}

UNIT_FACTORS = {"percent": 1.0, "tenths": 0.1, "basis_points": 0.01, "decimal": 100.0}
UNIT_LABELS = {
    "percent": "percent (4.28 = 4.28%)",
    "tenths": "tenths (42.8 = 4.28%)",
    "basis_points": "basis points (428 = 4.28%)",
    "decimal": "decimal (0.0428 = 4.28%)",
}

_SUFFIXES = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}


@dataclass
class UploadIssue:
    level: str          # info | warn | fail
    message: str


@dataclass
class UploadResult:
    """Parsed upload plus everything the UI needs to explain it."""

    frame: pd.DataFrame | None = None
    series: pd.Series | None = None
    label: str = ""
    issues: list[UploadIssue] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return (self.frame is not None and not self.frame.empty) or \
               (self.series is not None and not self.series.empty)

    @property
    def failed(self) -> list[UploadIssue]:
        return [i for i in self.issues if i.level == "fail"]

    def add(self, level: str, message: str) -> None:
        self.issues.append(UploadIssue(level, message))


# ------------------------------------------------------------------ reading

def _normalise(name: Any) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", str(name).strip().lower())


def read_table(source: Any, filename: str = "", sheet: str | int | None = 0) -> pd.DataFrame:
    """Read a CSV/TSV/XLSX upload into a raw DataFrame (no interpretation yet)."""
    name = (filename or getattr(source, "name", "") or "").lower()
    data = source
    if hasattr(source, "read"):
        data = source.read()
    if isinstance(data, (bytes, bytearray)):
        buf: Any = io.BytesIO(bytes(data))
    else:
        buf = data  # path-like

    if name.endswith((".xlsx", ".xlsm", ".xls")):
        return pd.read_excel(buf, sheet_name=sheet if sheet is not None else 0)

    raw = bytes(data) if isinstance(data, (bytes, bytearray)) else open(data, "rb").read()
    last_error: Exception | None = None
    for enc in ("utf-8-sig", "utf-8", "cp949", "latin-1"):
        try:
            # sep=None + python 엔진 = 구분자 자동 추정(쉼표/탭/세미콜론).
            return pd.read_csv(io.BytesIO(raw), sep=None, engine="python", encoding=enc)
        except Exception as exc:  # noqa: BLE001 - 인코딩/구분자 조합을 순회
            last_error = exc
    raise ValueError(f"CSV 를 읽지 못했습니다: {last_error}")


def sheet_names(source: Any, filename: str = "") -> list[str]:
    name = (filename or getattr(source, "name", "") or "").lower()
    if not name.endswith((".xlsx", ".xlsm", ".xls")):
        return []
    data = source.read() if hasattr(source, "read") else source
    buf = io.BytesIO(bytes(data)) if isinstance(data, (bytes, bytearray)) else data
    return list(pd.ExcelFile(buf).sheet_names)


def suggest_mapping(columns: Iterable[str], fields: Iterable[str] = PRICE_FIELDS) -> dict[str, str | None]:
    """Best-guess {field: column} so the user only fixes what we got wrong."""
    cols = list(columns)
    norm = {c: _normalise(c) for c in cols}
    used: set[str] = set()
    out: dict[str, str | None] = {}
    for field_name in fields:
        aliases = ALIASES.get(field_name, (field_name,))
        pick = None
        for alias in aliases:                                   # 1) 정확히 일치
            for c in cols:
                if c not in used and norm[c] == alias:
                    pick = c
                    break
            if pick:
                break
        if pick is None:                                        # 2) 부분 일치
            # 한두 글자 별칭(o, h, l, v)은 정확히 일치할 때만 쓴다 — 'volume' 안의
            # 'o' 가 Open 컬럼으로 잡히는 식의 오매핑을 막는다.
            for alias in (a for a in aliases if len(a) >= 3):
                for c in cols:
                    if c not in used and alias in norm[c]:
                        pick = c
                        break
                if pick:
                    break
        if pick is not None:
            used.add(pick)
        out[field_name] = pick
    return out


# ------------------------------------------------------------------ parsing

def parse_numeric(series: pd.Series) -> pd.Series:
    """'$1,234.56', '1,234,567', '(123)', '1.2M' → float."""
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float)
    s = series.astype(str).str.strip()
    neg = s.str.match(r"^\(.*\)$", na=False)
    s = s.str.replace(r"^\((.*)\)$", r"\1", regex=True)
    s = s.str.replace(r"[,\s$€£₩%]", "", regex=True)
    mult = pd.Series(1.0, index=s.index)
    for suffix, factor in _SUFFIXES.items():
        hit = s.str.lower().str.endswith(suffix) & s.str.contains(r"\d", regex=True)
        mult = mult.where(~hit, factor)
        s = s.mask(hit, s.str[:-1])
    out = pd.to_numeric(s.replace({"": np.nan, "-": np.nan, "--": np.nan, "N/A": np.nan,
                                   "n/a": np.nan, "nan": np.nan, ".": np.nan}),
                        errors="coerce") * mult
    return out.mask(neg, -out)


def parse_dates(series: pd.Series) -> pd.Series:
    """Text dates, ISO dates and Excel serial numbers → datetime64 (tz-naive)."""
    if pd.api.types.is_numeric_dtype(series):
        v = pd.to_numeric(series, errors="coerce")
        if v.dropna().between(20000, 60000).mean() > 0.9:       # Excel serial
            return pd.to_datetime(v, unit="D", origin="1899-12-30", errors="coerce")
    out = pd.to_datetime(series, errors="coerce", format="mixed", dayfirst=False)
    if out.isna().mean() > 0.2:                                  # DD/MM/YYYY 재시도
        alt = pd.to_datetime(series, errors="coerce", format="mixed", dayfirst=True)
        if alt.isna().mean() < out.isna().mean():
            out = alt
    try:
        out = out.dt.tz_localize(None)
    except (TypeError, AttributeError):
        pass
    return out.dt.normalize()


def _finalise(frame: pd.DataFrame, res: UploadResult, subset: list[str]) -> pd.DataFrame:
    """Shared tail end: drop unusable rows, de-duplicate, sort — and say so."""
    before = len(frame)
    frame = frame[frame.index.notna()]
    dropped_date = before - len(frame)
    if dropped_date:
        res.add("warn", f"날짜를 해석할 수 없는 행 {dropped_date}개를 제외했습니다.")

    bad = frame[subset].isna().any(axis=1).sum() if subset else 0
    if bad:
        frame = frame.dropna(subset=subset)
        res.add("warn", f"필수 값이 비어 있는 행 {int(bad)}개를 제외했습니다.")

    dupes = int(frame.index.duplicated().sum())
    if dupes:
        frame = frame[~frame.index.duplicated(keep="last")]
        res.add("warn", f"중복 날짜 {dupes}건을 발견해 마지막 값만 남겼습니다.")
    return frame.sort_index()


def build_prices(raw: pd.DataFrame, mapping: dict[str, str | None], label: str = "") -> UploadResult:
    """Uploaded OHLCV → the same frame shape the downloader returns."""
    res = UploadResult(label=label)
    if raw is None or raw.empty:
        res.add("fail", "파일에 행이 없습니다.")
        return res
    date_col, close_col = mapping.get("date"), mapping.get("close")
    if not date_col or not close_col:
        res.add("fail", "Date 와 Close 컬럼은 반드시 지정해야 합니다.")
        return res

    frame = pd.DataFrame(index=parse_dates(raw[date_col]))
    frame.index.name = "date"
    frame["close"] = parse_numeric(raw[close_col]).to_numpy()
    for fld in ("open", "high", "low"):
        col = mapping.get(fld)
        if col:
            frame[fld] = parse_numeric(raw[col]).to_numpy()
        else:
            frame[fld] = frame["close"]
            res.add("warn", f"{fld.upper()} 컬럼이 없어 종가로 대체했습니다 — "
                            "CLV(분산일 3번 조건)와 ATR% 는 의미를 잃습니다.")
    vol_col = mapping.get("volume")
    if vol_col:
        frame["volume"] = parse_numeric(raw[vol_col]).to_numpy()
    else:
        frame["volume"] = np.nan
        res.add("warn", "Volume 컬럼이 없습니다 — 거래량을 따로 업로드하지 않으면 "
                        "분산일 분석을 쓸 수 없습니다.")

    frame = frame[["open", "high", "low", "close", "volume"]]
    frame = _finalise(frame, res, subset=["close"])
    if frame.empty:
        res.add("fail", "사용할 수 있는 행이 남지 않았습니다. 컬럼 매핑을 확인하세요.")
        return res

    zero_vol = int(((frame["volume"] <= 0) | frame["volume"].isna()).sum())
    if zero_vol and vol_col:
        res.add("warn", f"거래량이 0 이거나 비어 있는 행 {zero_vol}개 "
                        f"({zero_vol / len(frame) * 100:.1f}%) — 분산일 판정에 영향을 줍니다.")
    broken = int((frame["high"] < frame["low"]).sum())
    if broken:
        res.add("warn", f"고가 < 저가인 행 {broken}개가 있습니다.")

    res.frame = frame
    res.stats = {
        "rows": int(len(frame)),
        "first": str(frame.index.min().date()),
        "last": str(frame.index.max().date()),
        "usable_volume": int(((frame["volume"] > 0) & frame["volume"].notna()).sum()),
        "mapping": {k: v for k, v in mapping.items() if v},
    }
    return res


def build_volume(raw: pd.DataFrame, mapping: dict[str, str | None], label: str = "") -> UploadResult:
    """A standalone volume file (Date + Volume)."""
    res = UploadResult(label=label)
    date_col, vol_col = mapping.get("date"), mapping.get("volume")
    if raw is None or raw.empty or not date_col or not vol_col:
        res.add("fail", "Date 와 Volume 컬럼을 지정해야 합니다.")
        return res
    frame = pd.DataFrame({"volume": parse_numeric(raw[vol_col]).to_numpy()},
                         index=parse_dates(raw[date_col]))
    frame.index.name = "date"
    frame = _finalise(frame, res, subset=["volume"])
    if frame.empty:
        res.add("fail", "사용할 수 있는 거래량 행이 없습니다.")
        return res
    res.series = frame["volume"]
    res.stats = {"rows": int(len(frame)), "first": str(frame.index.min().date()),
                 "last": str(frame.index.max().date()),
                 "usable_volume": int((frame["volume"] > 0).sum())}
    return res


def detect_yield_unit(series: pd.Series) -> str:
    med = float(pd.Series(series).dropna().abs().median()) if len(series.dropna()) else np.nan
    if not np.isfinite(med):
        return "percent"
    if med < 0.2:
        return "decimal"
    if med <= 20:
        return "percent"
    if med <= 200:
        return "tenths"
    return "basis_points"


def build_yield(raw: pd.DataFrame, mapping: dict[str, str | None], label: str = "",
                unit: str = "auto") -> UploadResult:
    """Uploaded 10Y yield → a percent-denominated series.

    ``unit="auto"`` infers from the level and says what it inferred; any other
    value is the user's explicit override and is applied as given.
    """
    res = UploadResult(label=label)
    date_col, y_col = mapping.get("date"), mapping.get("yield")
    if raw is None or raw.empty or not date_col or not y_col:
        res.add("fail", "Date 와 Yield 컬럼을 지정해야 합니다.")
        return res
    frame = pd.DataFrame({"yield": parse_numeric(raw[y_col]).to_numpy()},
                         index=parse_dates(raw[date_col]))
    frame.index.name = "date"
    frame = _finalise(frame, res, subset=["yield"])
    if frame.empty:
        res.add("fail", "사용할 수 있는 금리 행이 없습니다.")
        return res

    detected = detect_yield_unit(frame["yield"])
    applied = detected if unit in ("auto", "", None) else unit
    factor = UNIT_FACTORS.get(applied, 1.0)
    series = frame["yield"] * factor
    if unit in ("auto", "", None):
        res.add("info" if detected == "percent" else "warn",
                f"단위를 {UNIT_LABELS[detected]} 로 추정해 ×{factor:g} 를 적용했습니다. "
                "사이드바에서 직접 지정할 수 있습니다.")
    else:
        res.add("info", f"사용자가 지정한 단위 {UNIT_LABELS.get(applied, applied)} "
                        f"(×{factor:g}) 를 적용했습니다"
                        + (f" — 자동 추정값은 {UNIT_LABELS[detected]} 였습니다."
                           if detected != applied else "."))
    med = float(series.median())
    if not (0.2 <= med <= 10):
        res.add("warn", f"변환 후 중앙값이 {med:.2f}% 입니다 — 10년물 수익률로는 이례적입니다. "
                        "단위 선택을 다시 확인하세요.")
    res.series = series
    res.stats = {"rows": int(len(series)), "first": str(series.index.min().date()),
                 "last": str(series.index.max().date()),
                 "detected_unit": detected, "applied_unit": applied, "factor": factor,
                 "median": med}
    return res


def merge_volume(prices: pd.DataFrame, volume: pd.Series) -> tuple[pd.DataFrame, dict]:
    """Attach a separately sourced volume to the price frame, by date.

    Exact date matching only — a volume bar is a fact about one day, so it is
    never forward-filled onto a day it does not belong to. Coverage statistics
    come back so the UI can show how well the two files line up.
    """
    out = prices.copy()
    aligned = pd.Series(volume, dtype=float).reindex(out.index)
    stats = {
        "price_rows": int(len(out)),
        "volume_rows": int(len(volume)),
        "matched": int(aligned.notna().sum()),
        "price_without_volume": int(aligned.isna().sum()),
        "volume_unused": int(len(volume) - aligned.notna().sum()),
    }
    stats["coverage"] = round(stats["matched"] / max(1, stats["price_rows"]), 4)
    out["volume"] = aligned
    return out, stats
