"""한국 상장사 분기별 수주잔고(order-backlog) 대시보드.

정적 빌드는 GitHub Actions가 커밋해 둔 ``data/kr_backlog.json`` 을 읽어 표시하고,
라이브 API는 요청 시 한 종목을 DART에서 다시 수집한다. 데이터 생성/갱신은
``tools/kr_dart_backlog.py`` 가 담당한다(수주잔고는 정기보고서를 낸 회사만, 그리고
그 회사가 보고서를 낼 때만 갱신되므로 매일 전 종목을 스캔하지 않는다).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

DATA_FILE = os.environ.get("SUH_DH_BACKLOG_FILE") or str(
    Path(__file__).resolve().parent.parent / "data" / "kr_backlog.json"
)


def _demo() -> bool:
    return os.environ.get("SUH_DH_DEMO", "").strip() in ("1", "true", "yes")


def _load() -> dict:
    path = Path(DATA_FILE)
    if not path.exists():
        return {"_meta": {}, "companies": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"_meta": {}, "companies": {}}
    if not isinstance(data, dict):
        return {"_meta": {}, "companies": {}}
    data.setdefault("companies", {})
    data.setdefault("_meta", {})
    return data


def _pct(cur, prev) -> float | None:
    if cur is None or prev in (None, 0):
        return None
    return round((cur - prev) / abs(prev) * 100, 1)


def _company_view(rec: dict) -> dict | None:
    """Shape one company's stored record into a dashboard row."""
    quarters = [q for q in rec.get("quarters", []) if isinstance(q, dict)]
    if not quarters:
        return None
    # newest first by business period, then receipt date
    quarters.sort(key=lambda q: (q.get("period", ""), q.get("rcept_dt", "")), reverse=True)

    latest = quarters[0]
    krw = [q.get("backlog_krw") for q in quarters]
    qoq = _pct(krw[0], krw[1]) if len(krw) > 1 else None
    # year-over-year: same quarter one year back is ~4 entries down for a pure
    # quarterly filer (Q1→반기→Q3→연간). Fall back to None if unavailable.
    yoy = _pct(krw[0], krw[4]) if len(krw) > 4 else None

    return {
        "stock_code": rec.get("stock_code"),
        "name": rec.get("name") or rec.get("stock_code"),
        "market": rec.get("market") or "",
        "sector": rec.get("sector") or "기타",
        "industry": rec.get("industry") or "",
        "latest_backlog_krw": latest.get("backlog_krw"),
        "latest_backlog_raw": latest.get("backlog_raw"),
        "latest_unit": latest.get("unit"),
        "currency": latest.get("currency"),
        "latest_quarter": latest.get("quarter") or latest.get("period"),
        "latest_rcept_dt": latest.get("rcept_dt"),
        "qoq_pct": qoq,
        "yoy_pct": yoy,
        "source": latest.get("source"),
        "quarters": [
            {
                "quarter": q.get("quarter") or q.get("period"),
                "period": q.get("period"),
                "rcept_dt": q.get("rcept_dt"),
                "backlog_krw": q.get("backlog_krw"),
                "backlog_raw": q.get("backlog_raw"),
                "unit": q.get("unit"),
                "currency": q.get("currency"),
                "report_nm": q.get("report_nm"),
                "source": q.get("source"),
            }
            for q in quarters
        ],
    }


def get_dashboard() -> dict:
    """Payload for /api/backlog and the pre-built static data/kr_backlog view."""
    if _demo():
        return _demo_payload()

    data = _load()
    rows: list[dict] = []
    for rec in data.get("companies", {}).values():
        view = _company_view(rec)
        if view:
            rows.append(view)

    # KRW-denominated first (largest backlog on top), FX/unknown after.
    rows.sort(
        key=lambda r: (r.get("latest_backlog_krw") is None, -(r.get("latest_backlog_krw") or 0))
    )

    meta = data.get("_meta", {})
    return {
        "updated": meta.get("updated"),
        "count": len(rows),
        "companies": rows,
        "demo": False,
        "note": meta.get("note", ""),
    }


# --------------------------------------------------------------------------- #
# live single-company refresh (optional; needs DART_API_KEY + network)
# --------------------------------------------------------------------------- #
def refresh_company(stock_code: str, years_back: int = 1) -> dict | None:
    """Fetch one company's recent backlog live from DART (returns a stored rec)."""
    from datetime import date, timedelta

    from . import dartdoc

    code = stock_code.split(".")[0]
    corp = dartdoc.load_corp_map().get(code)
    if not corp:
        return None
    end = date.today().strftime("%Y%m%d")
    bgn = (date.today() - timedelta(days=int(years_back * 365) + 120)).strftime("%Y%m%d")
    quarters: list[dict] = []
    name = ""
    for f in dartdoc.periodic_filings(corp, bgn, end):
        name = name or f.get("corp_name") or ""
        try:
            body = dartdoc.fetch_document(f["rcept_no"])
            bl = dartdoc.extract_backlog(body)
        except Exception:
            bl = None
        if not bl:
            continue
        period = dartdoc.report_period(f["report_nm"])
        quarters.append({
            "period": period,
            "quarter": dartdoc.period_to_quarter(period),
            "rcept_dt": f["rcept_dt"],
            "rcept_no": f["rcept_no"],
            "report_nm": f["report_nm"],
            "source": dartdoc.viewer_url(f["rcept_no"]),
            **bl,
        })
    if not quarters:
        return None
    return {"stock_code": code, "corp_code": corp, "name": name,
            "market": "", "sector": "", "quarters": quarters}


# --------------------------------------------------------------------------- #
# demo payload (offline UI preview)
# --------------------------------------------------------------------------- #
def _demo_payload() -> dict:
    def q(period, quarter, rcept, raw, krw):
        return {"quarter": quarter, "period": period, "rcept_dt": rcept,
                "backlog_krw": krw, "backlog_raw": raw, "unit": "백만원",
                "currency": None, "report_nm": f"분기보고서 ({period.replace('-', '.')})",
                "source": "https://dart.fss.or.kr/"}

    companies = [
        {
            "stock_code": "000720", "name": "현대건설(예시)", "market": "KOSPI",
            "sector": "건설", "latest_backlog_krw": 90_100_000_000_000,
            "latest_backlog_raw": "90,100,000", "latest_unit": "백만원",
            "currency": None, "latest_quarter": "2025 3Q", "latest_rcept_dt": "2025-11-14",
            "qoq_pct": 2.1, "yoy_pct": 5.4, "source": "https://dart.fss.or.kr/",
            "quarters": [
                q("2025-09", "2025 3Q", "2025-11-14", "90,100,000", 90_100_000_000_000),
                q("2025-06", "2025 반기", "2025-08-14", "88,300,000", 88_300_000_000_000),
                q("2025-03", "2025 1Q", "2025-05-15", "86,000,000", 86_000_000_000_000),
                q("2024-12", "2024 연간", "2025-03-11", "85_500_000".replace("_", ","), 85_500_000_000_000),
            ],
        },
        {
            "stock_code": "009540", "name": "HD한국조선해양(예시)", "market": "KOSPI",
            "sector": "조선", "latest_backlog_krw": 78_000_000_000_000,
            "latest_backlog_raw": "780,000", "latest_unit": "억원",
            "currency": None, "latest_quarter": "2025 3Q", "latest_rcept_dt": "2025-11-13",
            "qoq_pct": -1.2, "yoy_pct": 12.0, "source": "https://dart.fss.or.kr/",
            "quarters": [
                q("2025-09", "2025 3Q", "2025-11-13", "780,000", 78_000_000_000_000),
                q("2025-06", "2025 반기", "2025-08-13", "789,000", 78_900_000_000_000),
            ],
        },
    ]
    return {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(companies), "companies": companies, "demo": True,
        "note": "DEMO 데이터 (실제 수치 아님)",
    }
