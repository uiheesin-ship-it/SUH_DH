"""OpenDART document client + 수주잔고(order-backlog) table extractor.

Order backlog is *not* a structured DART API field — it lives in the narrative
"사업의 내용 → 수주상황/수주현황" section of a company's periodic report
(분기/반기/사업보고서), as an HTML table. So we:

  1. list.json  — find periodic-report filings (rcept_no) for a company or,
     market-wide, for a date window (the daily-update entry point).
  2. document.xml?rcept_no=… — download the report (a zip of DART XML/XHTML)
     and parse its tables for a 수주잔고 / 수주잔액 column.

The parser is deliberately conservative and every extracted number keeps its
raw string, unit, and a DART viewer link so a human can verify it — company
table layouts vary too much to trust blindly.

Network calls reach opendart.fss.or.kr, which the web sandbox blocks; this runs
in GitHub Actions with a free DART_API_KEY (register at opendart.fss.or.kr).
The pure parsing helpers (``extract_backlog``, ``parse_amount``,
``period_to_quarter``) take strings and are unit-tested offline.
"""

from __future__ import annotations

import io
import json
import os
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from pathlib import Path

BASE = "https://opendart.fss.or.kr/api"
DATA = Path(__file__).resolve().parent.parent / "data"
CORP_CACHE = DATA / "dart_corp.json"     # 6-digit stock_code -> 8-digit corp_code

# 정기공시 report names we treat as backlog-bearing periodic reports.
PERIODIC = ("분기보고서", "반기보고서", "사업보고서")

# The backlog column header nearly always reads 수주잔고 / 수주잔액 (occasionally
# 계약잔액 or "수주 잔고" with a space). We require a 수주/계약 stem + 잔고/잔액.
_BACKLOG_HEADER = re.compile(r"(수주|계약)\s*(잔고|잔액|미인식|미청구잔여)")
# Rows summarising the whole table.
_TOTAL_ROW = re.compile(r"^\s*(합\s*계|총\s*계|계|합\s*산|total)\s*$", re.I)
_SUBTOTAL_ROW = re.compile(r"소\s*계")
# "(단위 : 백만원)" style unit captions, in a caption cell or nearby text.
_UNIT = re.compile(r"단위\s*[:：]?\s*([가-힣A-Za-z]*원|[가-힣]*달러|[A-Za-z]{3}|USD)")

# unit token -> multiplier to normalise a shown amount into KRW.
_UNIT_MULT = {
    "원": 1, "천원": 1_000, "만원": 10_000, "십만원": 100_000,
    "백만원": 1_000_000, "천만원": 10_000_000, "억원": 100_000_000,
    "십억원": 1_000_000_000, "백억원": 10_000_000_000, "조원": 1_000_000_000_000,
}
# Currency-denominated tables (kept as-is, not converted to KRW).
_FX = {"USD", "달러", "천달러", "백만달러", "천USD", "USD천"}


def key() -> str:
    return os.environ.get("DART_API_KEY", "").strip()


def _get(url: str, timeout: int = 30, retries: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "suh-dh/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:            # transient timeout / connection reset
            last = e
            time.sleep(2 * (attempt + 1))
    raise last  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# corp map
# --------------------------------------------------------------------------- #
def load_corp_map() -> dict[str, str]:
    """6-digit stock_code -> 8-digit DART corp_code (cached in data/dart_corp.json)."""
    if CORP_CACHE.exists():
        try:
            cached = json.loads(CORP_CACHE.read_text(encoding="utf-8"))
            if cached:
                return cached
        except Exception:
            pass
    raw = _get(f"{BASE}/corpCode.xml?crtfc_key={key()}", timeout=180, retries=6)
    zf = zipfile.ZipFile(io.BytesIO(raw))
    root = ET.fromstring(zf.read(zf.namelist()[0]))
    out: dict[str, str] = {}
    for el in root.iter("list"):
        sc = (el.findtext("stock_code") or "").strip()
        cc = (el.findtext("corp_code") or "").strip()
        if len(sc) == 6 and sc.isdigit() and cc:
            out[sc] = cc
    CORP_CACHE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
# list.json — periodic-report filings
# --------------------------------------------------------------------------- #
def _list(params: str, max_pages: int = 20) -> list[dict]:
    """Paginate list.json; returns the raw filing records (or [])."""
    rows: list[dict] = []
    for page in range(1, max_pages + 1):
        url = f"{BASE}/list.json?crtfc_key={key()}&{params}&page_no={page}&page_count=100"
        js = None
        for attempt in range(4):               # retry transient rate limits
            try:
                js = json.loads(_get(url))
            except Exception:
                js = None
                break
            if js.get("status") in ("020", "101", "800"):   # rate/temporary limits
                time.sleep(2 * (attempt + 1))
                continue
            break
        if not js:
            break
        status = js.get("status")
        if status == "013":                    # no matching data
            break
        if status != "000":                    # 011 usage, 020 after retries, …
            raise RuntimeError(f"DART status {status}: {js.get('message')}")
        rows.extend(js.get("list", []))
        if js.get("page_no", 1) >= js.get("total_page", 1):
            break
        time.sleep(0.12)
    return rows


def _is_periodic(report_nm: str) -> bool:
    nm = report_nm or ""
    # Skip amendments/attachments like "[첨부정정]" only when they are not the
    # report itself; keep 정정 reports (they carry the corrected backlog).
    return any(k in nm for k in PERIODIC)


def periodic_filings(corp_code: str, bgn: str, end: str) -> list[dict]:
    """A single company's 정기보고서 filings in [bgn, end], newest first.

    Each item: {rcept_no, rcept_dt (YYYY-MM-DD), report_nm}.
    """
    rows = _list(f"corp_code={corp_code}&bgn_de={bgn}&end_de={end}&pblntf_ty=A")
    return _shape(rows)


def market_periodic_filings(bgn: str, end: str) -> list[dict]:
    """*Every* company's 정기보고서 filings in [bgn, end] — the daily entry point.

    One market-wide list.json sweep (a handful of API calls) instead of polling
    thousands of tickers: order backlog only changes when a periodic report is
    filed, so we look at exactly the day's filers.
    """
    rows = _list(f"bgn_de={bgn}&end_de={end}&pblntf_ty=A")
    return _shape(rows)


def _shape(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for it in rows:
        nm = it.get("report_nm") or ""
        if not _is_periodic(nm):
            continue
        rd = (it.get("rcept_dt") or "").strip()
        rcp = (it.get("rcept_no") or "").strip()
        if not (len(rd) == 8 and rd.isdigit() and rcp):
            continue
        out.append({
            "rcept_no": rcp,
            "rcept_dt": f"{rd[:4]}-{rd[4:6]}-{rd[6:]}",
            "report_nm": nm.strip(),
            "stock_code": (it.get("stock_code") or "").strip(),
            "corp_code": (it.get("corp_code") or "").strip(),
            "corp_name": (it.get("corp_name") or "").strip(),
            "corp_cls": (it.get("corp_cls") or "").strip(),   # Y=KOSPI K=KOSDAQ N=KONEX
        })
    out.sort(key=lambda x: x["rcept_dt"], reverse=True)
    return out


def viewer_url(rcept_no: str) -> str:
    return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


# --------------------------------------------------------------------------- #
# document.xml — download the report body
# --------------------------------------------------------------------------- #
def fetch_document(rcept_no: str, retries: int = 4) -> str:
    """Download a filing's document.xml zip and return its concatenated body.

    Retries on DART's rate-limit error payload (status 020) so concurrent
    backfills don't misread a throttled response as "no backlog".
    """
    url = f"{BASE}/document.xml?crtfc_key={key()}&rcept_no={rcept_no}"
    for attempt in range(retries):
        raw = _get(url, timeout=90)
        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            # DART returns a small XML error payload (not a zip) on limit/bad key.
            body = raw.decode("utf-8", "replace")
            if any(s in body for s in ("020", "101", "800")) and attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return body
        parts: list[str] = []
        for name in zf.namelist():
            try:
                parts.append(zf.read(name).decode("utf-8", "replace"))
            except Exception:
                continue
        return "\n".join(parts)
    return ""


# --------------------------------------------------------------------------- #
# HTML table parsing (stdlib only)
# --------------------------------------------------------------------------- #
class _TableParser(HTMLParser):
    """Collect tables as grids of cell text, expanding colspan for alignment."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._tbl: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._buf: list[str] = []
        self._colspan = 1
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "table":
            self._tbl = []
        elif tag == "tr" and self._tbl is not None:
            self._row = []
        elif tag in ("td", "th", "te") and self._row is not None:
            self._in_cell = True
            self._buf = []
            self._colspan = 1
            for k, v in attrs:
                if k == "colspan":
                    try:
                        self._colspan = max(1, min(20, int(v)))
                    except (TypeError, ValueError):
                        self._colspan = 1
        elif tag == "br" and self._in_cell:
            self._buf.append(" ")

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th", "te") and self._in_cell:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            assert self._row is not None
            self._row.extend([text] * self._colspan)
            self._in_cell = False
        elif tag == "tr" and self._row is not None and self._tbl is not None:
            if any(c for c in self._row):
                self._tbl.append(self._row)
            self._row = None
        elif tag == "table" and self._tbl is not None:
            if self._tbl:
                self.tables.append(self._tbl)
            self._tbl = None


def parse_tables(html: str) -> list[list[list[str]]]:
    p = _TableParser()
    try:
        p.feed(html)
    except Exception:
        pass
    return p.tables


def parse_amount(text: str) -> float | None:
    """Parse a shown amount ('89,123,400', '1,234.5', '(1,200)') to a float.

    Parentheses / a leading minus mean negative; returns None if no digits.
    """
    if not text:
        return None
    neg = "(" in text and ")" in text
    cleaned = re.sub(r"[^\d.\-]", "", text.replace(",", ""))
    cleaned = re.sub(r"(?<!^)-", "", cleaned)     # keep only a leading minus
    if cleaned in ("", "-", ".", "-."):
        return None
    try:
        val = float(cleaned)
    except ValueError:
        return None
    return -val if (neg and val > 0) else val


def unit_multiplier(unit: str | None) -> tuple[float, str | None]:
    """(multiplier, currency) for a unit caption; currency is None for KRW."""
    if not unit:
        return 1.0, None
    u = unit.replace(" ", "")
    if u in _FX or "달러" in u or "USD" in u.upper():
        return 1.0, "USD"
    return float(_UNIT_MULT.get(u, 1)), None


def find_unit(cells_and_text: str) -> str | None:
    m = _UNIT.search(cells_and_text or "")
    return m.group(1).replace(" ", "") if m else None


def period_to_quarter(period: str) -> str:
    """'2025-03' -> '2025 1Q'; month 06→반기, 09→3Q, 12→사업연도."""
    m = re.match(r"(\d{4})[.\-/](\d{1,2})", period or "")
    if not m:
        return period or ""
    year, mon = m.group(1), int(m.group(2))
    label = {3: "1Q", 6: "반기", 9: "3Q", 12: "연간"}.get(mon, f"{mon:02d}월")
    return f"{year} {label}"


def report_period(report_nm: str) -> str:
    """Extract '(2025.03)' business period from a report name -> '2025-03'."""
    m = re.search(r"\((\d{4})[.\-/](\d{1,2})", report_nm or "")
    if not m:
        return ""
    return f"{m.group(1)}-{int(m.group(2)):02d}"


def _header_col(table: list[list[str]]) -> tuple[int, int] | None:
    """Find (header_row_index, backlog_col_index) or None."""
    for r, row in enumerate(table[:6]):        # header is near the top
        for c, cell in enumerate(row):
            if _BACKLOG_HEADER.search(cell):
                return r, c
    return None


def _pick_total(table: list[list[str]], hdr_r: int, col: int) -> tuple[float | None, str, str]:
    """Return (value, raw_text, method) for the backlog column's total.

    Prefers an explicit 합계/총계/계 row; else a single data row; else the sum of
    non-subtotal rows. ``method`` records which, for transparency.
    """
    body = table[hdr_r + 1:]

    def _leading_label(row: list[str]) -> str:
        for cell in row[: max(1, col)]:
            if cell.strip():
                return cell.strip()
        return ""

    # 1) explicit total row (a leading label cell reading 합계/총계/계)
    for row in body:
        if col < len(row) and _TOTAL_ROW.match(_leading_label(row)):
            v = parse_amount(row[col])
            if v is not None:
                return v, row[col], "total-row"
    # 2) collect numeric data rows (excluding subtotals)
    vals: list[tuple[float, str]] = []
    for row in body:
        if col >= len(row):
            continue
        label = " ".join(row[: max(1, col)])
        if _SUBTOTAL_ROW.search(label):
            continue
        v = parse_amount(row[col])
        if v is not None:
            vals.append((v, row[col]))
    if len(vals) == 1:
        return vals[0][0], vals[0][1], "single-row"
    if vals:
        total = sum(v for v, _ in vals)
        return total, f"{total:,.0f}", "row-sum"
    return None, "", "none"


def extract_backlog(html: str) -> dict | None:
    """Extract order backlog from a report body, or None if not disclosed.

    Returns {backlog_krw, backlog_raw, unit, currency, method, columns} where
    backlog_krw is normalised to KRW (None for FX-denominated tables). Scans
    every table; picks the first that yields a total from a 수주잔고 column,
    preferring tables near a 수주 heading.
    """
    tables = parse_tables(html)
    if not tables:
        return None
    doc_unit = find_unit(html[:200000])       # a doc-level "(단위: 백만원)" hint

    best: dict | None = None
    for table in tables:
        found = _header_col(table)
        if not found:
            continue
        hdr_r, col = found
        val, raw, method = _pick_total(table, hdr_r, col)
        if val is None:
            continue
        # Unit: prefer one written inside this table, else the doc-level hint.
        flat = " ".join(c for row in table for c in row)
        unit = find_unit(flat) or doc_unit
        mult, currency = unit_multiplier(unit)
        result = {
            "backlog_krw": None if currency else round(val * mult),
            "backlog_raw": raw,
            "unit": unit,
            "currency": currency,
            "method": method,
            "header": table[hdr_r][col] if col < len(table[hdr_r]) else "수주잔고",
        }
        # Prefer an explicit total row over a summed/single guess.
        if method == "total-row":
            return result
        if best is None:
            best = result
    return best
