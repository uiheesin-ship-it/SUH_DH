"""국장 분기 실적의 원본 — DART Open API(opendart.fss.or.kr).

미장은 EDGAR companyfacts 한 번이면 전부 나왔다. 국장은 그 자리에 **DART 정기
보고서**가 들어간다. 다른 점이 셋이라 얇은 층을 따로 둔다.

  1. 한 번에 안 온다. companyfacts 는 회사당 파일 하나지만 DART 는
     (회계연도 × 보고서) 마다 한 번씩 부른다 — 5년이면 20번이다. 그래서
     보고서 하나하나를 길게 캐시한다(이미 제출된 보고서는 안 바뀐다).
  2. 기간 표현이 다르다. EDGAR 는 사실마다 start/end 가 붙지만 DART 는
     보고서가 기간을 들고 있다. thstrm_dt("2025.07.01 ~ 2025.09.30")를 쓰고,
     없으면 (회계연도, 보고서코드)에서 만든다.
  3. **실적발표일이 정기보고서 접수일이 아니다.** 거래소에 먼저 내는
     〈연결재무제표기준영업(잠정)실적〉이 보통 2~5주 빠르다(실측 2026-09-19:
     에코프로비엠 잠정 2025-04-29 vs 분기보고서 2025-05-14, 삼성전자 잠정
     2026-04-07 vs 분기보고서 2026-05-15). 미장에서 "야후 발표일 → EDGAR
     제출일" 로 물러섰던 것과 같은 구조라, 잠정 → 정기 순으로 쓴다.

실측(tools/kr_fundamentals_probe.py, 2026-09-19, 삼성전자·KB금융·에코프로비엠):

  fnlttSinglAcnt(주요계정)   5년 20개 중 **18개**가 온다(아직 안 나온 2개 제외).
                             thstrm_amount 가 **당기 3개월**이고 thstrm_add_amount
                             가 누적이다 — 반기 누적 = 1분기 + 당기로 검산했다.
                             사업보고서는 당기가 **연간**이고 누적이 없다.
  fnlttSinglAcntAll(전체)    158~346행. 기본·희석주당이익(ifrs-full_…PerShare),
                             차입금·사채·리스부채·현금·비지배지분·우선주자본금이
                             표준 계정코드로 온다. 미장보다 오히려 깔끔하다 —
                             회사마다 태그를 갈아타지 않는다.
                             다만 **감가상각은 회사마다 있고 없다**(에코프로비엠
                             은 없다). 미장과 같은 한계다.

네트워크는 여기까지다. 숫자를 분기 계열로 펴는 규칙은 app/krfundamentals.py 에
있고 네트워크를 모른다 — 샌드박스에서 DART 가 막혀 있어도 규칙은 검증된다.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from datetime import date

from . import cache, dartdoc

BASE = "https://opendart.fss.or.kr/api"
# 이미 제출된 보고서는 바뀌지 않는다(정정공시는 새 접수번호로 온다). 길게 둔다.
REPORT_TTL = 86400.0 * 7
FILING_TTL = 3600.0 * 6
# 정기보고서 코드 → (분기 번호, 기본 마감 월일)
REPRT = {"11013": (1, "03-31"), "11012": (2, "06-30"),
         "11014": (3, "09-30"), "11011": (4, "12-31")}
YEARS = 6                 # 5년 20분기를 채우려면 한 해 더 봐야 한다
PERIODIC = ("분기보고서", "반기보고서", "사업보고서")
FLASH = "잠정"            # 〈연결재무제표기준영업(잠정)실적〉
KEY_TTL = 600.0           # 키 판정은 잠깐만 기억한다(키를 고치면 곧 반영되게)

# DART 가 돌려주는 상태 코드. 그대로 두면 화면에 "000" 같은 숫자만 뜬다.
#
# 키가 틀렸을 때가 제일 헷갈린다 — 보고서 조회는 "자료 없음" 처럼 답해서
# "이 종목은 보고서가 없나 보다" 로 읽힌다. 5년치 48번을 다 두드린 뒤에야
# 빈손으로 끝난다. 그래서 **첫 한 번**으로 키부터 판정한다.
STATUS = {
    "010": "등록되지 않은 키입니다 — opendart.fss.or.kr 에서 발급받은 40자리 키인지 확인하세요.",
    "011": "사용할 수 없는 키입니다 — 메일로 온 인증 링크를 눌러 활성화했는지 확인하세요.",
    "012": "이 IP 에서는 접근할 수 없는 키입니다.",
    "013": "조회된 자료가 없습니다.",
    "020": "오늘 요청 한도를 넘었습니다(하루 20,000건) — 내일 다시 되거나 다른 키가 필요합니다.",
    "100": "요청 값이 잘못됐습니다.",
    "101": "부적절한 접근입니다.",
    "800": "DART 가 시스템 점검 중입니다.",
    "900": "DART 쪽에서 알 수 없는 오류가 났습니다.",
}


def _api(path: str, **params) -> dict:
    q = urllib.parse.urlencode({"crtfc_key": dartdoc.key(), **params})
    raw = dartdoc._get(f"{BASE}/{path}?{q}", timeout=40, retries=3)
    return json.loads(raw)


def check_key() -> None:
    """키가 쓸 수 있는 것인지 **한 번** 확인한다. 못 쓰면 이유를 그대로 말한다.

    안 하면 어떻게 되냐면: 보고서 조회가 키 문제를 "자료 없음"(013)으로 답해서
    5년치 48번을 다 두드린 뒤 빈손으로 끝난다. 화면에는 "정기보고서를 받지
    못했습니다" 라고만 떠서, 키가 문제인지 종목이 문제인지 알 수가 없다.

    값싼 호출 하나(공시목록 1건)로 갈라 놓고, 결과는 잠깐 기억한다 — 키를
    고치면 곧 다시 확인되도록 길게 잡지 않는다.
    """
    def produce():
        try:
            d = _api("list.json", bgn_de="20240101", end_de="20240102",
                     page_count="1")
        except Exception as e:  # noqa: BLE001
            return {"ok": False,
                    "why": f"DART 에 연결하지 못했습니다({type(e).__name__})."}
        status = d.get("status")
        if status in ("000", "013"):        # 013 = 그날 공시가 없었을 뿐
            return {"ok": True}
        return {"ok": False,
                "why": STATUS.get(status) or f"DART status {status}: {d.get('message')}"}

    got = cache.get_or_set(f"krdart:key:{dartdoc.key()[-6:]}", KEY_TTL, produce,
                           cache_when=lambda v: bool(v.get("ok")))
    if not got.get("ok"):
        raise LookupError(f"DART API 키를 쓸 수 없습니다 — {got['why']}")


def corp_code(code: str) -> str:
    """6자리 종목코드 → 8자리 DART 고유번호."""
    code = (code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise LookupError(f"국장 종목코드는 여섯 자리 숫자입니다: {code!r}")
    cc = dartdoc.load_corp_map().get(code)
    if not cc:
        raise LookupError(f"{code} 를 DART 고유번호 목록에서 찾지 못했습니다.")
    return cc


def report(corp: str, year: int, reprt: str) -> list[dict]:
    """보고서 하나의 **전체 재무제표** 행들. 없으면 빈 목록.

    연결(CFS)을 먼저 쓰고, 연결재무제표를 안 내는 회사(별도만 내는 소형주)는
    별도(OFS)로 물러선다. 섞지는 않는다 — 한 보고서 안에서 하나만 쓴다.
    """
    def produce():
        for fs in ("CFS", "OFS"):
            try:
                d = _api("fnlttSinglAcntAll.json", corp_code=corp,
                         bsns_year=str(year), reprt_code=reprt, fs_div=fs)
            except Exception:  # noqa: BLE001
                return []
            if d.get("status") == "000" and d.get("list"):
                rows = d["list"]
                for r in rows:
                    r["_fs"] = fs
                    r["_year"] = year
                    r["_reprt"] = reprt
                return rows
            if d.get("status") not in ("000", "013"):
                # 013 = 자료 없음(아직 안 나온 분기). 그 밖은 키·한도 문제다.
                return []
            time.sleep(0.2)
        return []

    return cache.get_or_set(f"krdart:rep:{corp}:{year}:{reprt}", REPORT_TTL,
                            produce, cache_when=lambda v: bool(v))


def reports(corp: str, years: int = YEARS) -> dict[tuple[int, str], list[dict]]:
    """최근 몇 해의 (회계연도, 보고서) → 행들.

    아직 안 나온 분기는 013(자료 없음)으로 비어 온다 — 그건 실패가 아니다.
    """
    this = date.today().year
    out = {}
    for year in range(this - years + 1, this + 1):
        for reprt in REPRT:
            rows = report(corp, year, reprt)
            if rows:
                out[(year, reprt)] = rows
            time.sleep(0.15)
    return out


def announcements(corp: str, years: int = YEARS) -> list[dict]:
    """실적발표일 후보 — 〈잠정실적〉 공시일과 정기보고서 접수일.

    잠정이 먼저다. 거래소 공시로 매출·영업이익이 먼저 나가고 정기보고서는
    2~5주 뒤에 접수된다. 시장이 숫자를 아는 날은 잠정 쪽이다.
    """
    def produce():
        end = date.today()
        beg = end.replace(year=end.year - years)
        rows = []
        for ty, kind in (("I", "잠정실적"), ("A", "정기보고서")):
            try:
                got = dartdoc._list(
                    f"corp_code={corp}&bgn_de={beg:%Y%m%d}&end_de={end:%Y%m%d}"
                    f"&pblntf_ty={ty}")
            except Exception:  # noqa: BLE001
                got = []
            for r in got:
                nm = r.get("report_nm") or ""
                keep = (FLASH in nm and "실적" in nm) if ty == "I" \
                    else any(p in nm for p in PERIODIC)
                if keep and r.get("rcept_dt"):
                    rows.append({"date": f"{r['rcept_dt'][:4]}-{r['rcept_dt'][4:6]}"
                                         f"-{r['rcept_dt'][6:]}",
                                 "kind": kind, "name": nm.strip()})
        rows.sort(key=lambda r: (r["date"], r["kind"] != "잠정실적"))
        return rows

    return cache.get_or_set(f"krdart:ann:{corp}", FILING_TTL, produce,
                            cache_when=lambda v: bool(v))


def fetch(code: str) -> dict:
    """종목코드 하나의 DART 재료 전부.

    키가 없으면 **먼저 그렇게 말한다.** 없는 채로 부르면 DART 가 "자료 없음"
    처럼 답해서 "이 종목은 보고서가 없습니다" 라는 엉뚱한 메시지가 뜬다.
    """
    if not dartdoc.key():
        raise LookupError(
            "DART_API_KEY 가 없습니다 — 국장은 DART 무료 API 키가 필요합니다. "
            "opendart.fss.or.kr 에서 받아(1분, 무료) 환경변수로 넣으세요. "
            "로컬이라면 저장소 폴더의 .env 파일에 "
            "DART_API_KEY=발급받은키 를 한 줄 적고 ./run.sh 를 다시 띄우세요"
            "(.env.example 을 복사해서 쓰면 됩니다).")
    check_key()
    corp = corp_code(code)
    return {"code": code, "corp_code": corp,
            "reports": reports(corp), "announcements": announcements(corp)}
