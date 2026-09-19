"""과거 시점의 12M forward PER — 실적발표일 기준.

정의부터 분명히 한다. 어떤 과거 시점 T 의 12M forward PER 은

    T 시점 주가 ÷ (T 이후 4개 분기 EPS 합)

이다. T 를 무엇으로 삼느냐가 갈림길인데, 여기서는 **실적발표일**을 쓴다.
재무정보 기준일(분기말)이 아니다. 2024년 1분기가 3월 31일에 끝나도 시장이
그 숫자를 아는 건 4월 하순이다. 기준일로 계단을 밟으면 아직 공개되지 않은
실적으로 그 사이 주가를 나누게 된다 — 미래 정보가 과거 차트에 새어 든다.
그래서 계단은 발표일에 밟고, 기준일은 **같이 표시만** 한다(차트에 둘 다
찍어 달라는 요구가 여기서 나온다).

컨센이 필요한 구간은 생각보다 좁다. T 가 1년보다 예전이면 그 4개 분기는
이미 다 발표됐다. 그러니 추정이 섞이는 건 **마지막 1년 남짓**뿐이고, 거기만
점선으로 그린다. 과거 시점의 그 당시 컨센(point-in-time)은 필요 없다 —
무료로는 구할 수도 없다. 다만 그래서 과거 구간의 선은 "그때 시장이 기대하던
PER" 이 아니라 "지나고 보니 그때 주가가 실제 향후 4분기 이익의 몇 배였나"
라는 뜻이 된다. 다른 이야기라서 화면에도 그렇게 적는다.

확정 실적으로 만든 값이 **실선**, 컨센이 한 분기라도 섞이면 **점선**이다.

실측(tools/consensus_probe.py, 2026-09-17, 8종목): 야후가 공짜로 주는
분기 컨센은 0q·+1q **두 개뿐**이다. 4개가 필요하므로 나머지 둘은 연간
추정(0y·+1y)에서 이미 아는 분기를 빼고 남은 분기에 고르게 나눠 만든다.
"""

from __future__ import annotations

from datetime import date, timedelta

HORIZON = 4              # 앞으로 몇 분기를 12개월로 볼 것인가
# --- 계절성 배분 손잡이 ------------------------------------------------------
# 연간 컨센을 미발표 분기에 나눌 때 쓴다. 바꿔 가며 맞춰 볼 값들이라 한데 모은다.
SEASON_YEARS = 3         # 비중을 구할 때 볼 과거 회계연도 수
SEASON_TOL = 0.15        # 연도별 비중이 이보다 흩어지면 계절성을 못 믿는다
SEASON_MIN_YEARS = 2     # 쓸 수 있는 해가 이보다 적으면 균등 배분
ANNOUNCE_MIN = 3         # 분기말 이후 이만큼 지나야 발표로 본다
ANNOUNCE_MAX = 120       # 이보다 늦으면 그 분기의 발표가 아니다


def _d(x) -> date | None:
    if isinstance(x, date):
        return x
    try:
        return date.fromisoformat(str(x)[:10])
    except (ValueError, TypeError):
        return None


def _month_end(y: int, m: int) -> int:
    return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day


def add_months(d: date, n: int) -> date:
    """n 개월 더한다. **월말은 월말로 간다.**

    분기 기준일은 대부분 월말이다. 9월 30일 + 3개월을 12월 30일로 만들면
    회계연도 마지막 날(12월 31일)과 어긋나서 그 분기가 어느 해에 속하는지
    판정이 틀어진다. 월말이면 가는 달의 월말로, 아니면 그 달 안으로 줄인다.
    """
    y, m = divmod((d.year * 12 + d.month - 1) + n, 12)
    m += 1
    last = _month_end(y, m)
    return date(y, m, last if d.day == _month_end(d.year, d.month) else min(d.day, last))


# --- 실적발표일 -------------------------------------------------------------
def match_announcements(quarters: list[dict], announced: list) -> list[dict]:
    """분기마다 실적발표일을 붙인다.

    야후의 발표일(``get_earnings_dates``)이 있으면 그걸 쓴다 — 보도자료가 나간
    날이다. 없으면 EDGAR 제출일로 물러선다. 제출일은 보도자료보다 며칠 늦는
    일이 많아 차선이지만, 기준일보다는 훨씬 낫다.

    붙이는 방향이 중요하다. **발표일마다 그 직전에 끝난 분기를 찾는다.**
    반대로 분기마다 뒤에 오는 첫 발표일을 집으면, 발표일이 듬성듬성할 때
    엉뚱한 분기가 먼저 집어 가 버린다(4분기가 다음 해 1분기 발표를 가져간다).
    값으로 맞추지는 않는다 — EPS 가 같은 분기는 얼마든지 있다.
    """
    qs = sorted(quarters, key=lambda r: r["end"])
    ends = [_d(q["end"]) for q in qs]
    hit: dict[int, date] = {}
    for cand in sorted(x for x in (_d(a) for a in announced or []) if x):
        best = None
        for i, e in enumerate(ends):
            if e is None:
                continue
            gap = (cand - e).days
            if ANNOUNCE_MIN <= gap <= ANNOUNCE_MAX:
                best = i        # 기준일이 오름차순이라 뒤로 갈수록 가깝다
        if best is not None and best not in hit:
            hit[best] = cand    # 같은 분기에 둘이 붙으면 이른 쪽(보도자료)
    out = []
    for i, q in enumerate(qs):
        row = dict(q)
        if i in hit:
            row["announced"] = hit[i].isoformat()
            row["announced_source"] = "실적발표일(야후)"
        else:
            filed = q.get("first_filed") or q.get("last_filed")
            row["announced"] = filed or None
            row["announced_source"] = "EDGAR 제출일" if filed else "없음"
        out.append(row)
    return out


# --- 앞으로의 분기 ----------------------------------------------------------
def project_ends(last_end, count: int, step_days: int | None = None) -> list[str]:
    """아직 안 끝난 분기의 기준일을 만든다.

    분기 길이는 회사마다 다르다(애플은 52/53주라 6월 27일에 끝난다). 정확한
    날짜가 필요한 게 아니라 **순서와 회계연도 소속**만 필요하므로 3개월씩
    더해 만든다. 화면에는 '추정'이라고 표시된다.
    """
    d = _d(last_end)
    if d is None:
        return []
    out = []
    for i in range(1, count + 1):
        out.append((add_months(d, 3 * i) if step_days is None
                    else d + timedelta(days=step_days * i)).isoformat())
    return out


def _fq_pos(end, fy_end) -> int | None:
    """분기 기준일이 그 회계연도의 **몇 번째 분기**인지(1~4)."""
    e, f = _d(end), _d(fy_end)
    if e is None or f is None:
        return None
    lo = add_months(f, -12)
    if not (lo < e <= f):
        return None
    months = (e.year - lo.year) * 12 + (e.month - lo.month)
    pos = max(1, min(4, round(months / 3)))
    return pos


def _fy_of(end, bounds: list[date]):
    """이 분기가 속한 회계연도의 마지막 기준일."""
    e = _d(end)
    if e is None:
        return None
    for b in bounds:
        if add_months(b, -12) < e <= b:
            return b
    return None


def seasonal_weights(known: dict[str, float], fy_ends: list[str],
                     years: int = SEASON_YEARS, tol: float = SEASON_TOL
                     ) -> tuple[dict[int, float], str, dict]:
    """과거 분기들이 그 해 합계에서 차지한 비중 — 계절성 지수.

    연간 컨센을 남은 분기에 **÷4 로 나누면** 계절성이 큰 회사가 크게 틀어진다
    (애플 4분기, 유통 연말). 그렇다고 성장 추세까지 여기서 다루지는 않는다 —
    추세는 연간 컨센이 이미 담고 있고, 여기서는 **한 해 안의 배분**만 본다.
    그래서 꾸준히 성장하는 회사도 뒤 분기 비중이 자연히 커진다.

    산식
        w[y][q] = v[y][q] / Σ_q v[y][q]      (그 해 분기 합이 양수일 때만)
        w[q]    = median_y w[y][q]           평균이 아니라 **중앙값** — 한 해의
                                             이상치(일회성 손익)에 안 흔들리게
        정규화  w[q] ← w[q] / Σ w

    믿을 수 있나
        spread[q] = max_y w[y][q] − min_y w[y][q]
        max_q spread[q] > tol 이면 계절성이 해마다 달라 못 믿는다 → 균등.
        쓸 수 있는 해가 SEASON_MIN_YEARS 보다 적어도 균등.

    반환: (분기위치→비중, 판정, 근거)
    """
    bounds = sorted(x for x in (_d(e) for e in fy_ends or []) if x)
    per_year: dict[date, dict[int, float]] = {}
    for end, val in (known or {}).items():
        if val is None:
            continue
        f = _fy_of(end, bounds)
        pos = _fq_pos(end, f.isoformat()) if f else None
        if f and pos:
            per_year.setdefault(f, {})[pos] = val

    rows = []
    for f in sorted(per_year, reverse=True):
        qs = per_year[f]
        if len(qs) != 4:
            continue                      # 네 분기가 다 있는 해만
        total = sum(qs.values())
        if total <= 0:
            continue                      # 적자 해는 비중이 음수로 뒤집힌다
        rows.append({q: qs[q] / total for q in (1, 2, 3, 4)})
        if len(rows) >= years:
            break

    even = {q: 0.25 for q in (1, 2, 3, 4)}
    why = {"years_used": len(rows), "tol": tol}
    if len(rows) < SEASON_MIN_YEARS:
        why["reason"] = f"쓸 수 있는 회계연도가 {len(rows)}개뿐입니다(최소 {SEASON_MIN_YEARS}개)"
        return even, "균등", why

    spread = {q: max(r[q] for r in rows) - min(r[q] for r in rows) for q in (1, 2, 3, 4)}
    why["spread"] = {q: round(v, 4) for q, v in spread.items()}
    if max(spread.values()) > tol:
        why["reason"] = (f"연도별 비중이 최대 {max(spread.values()):.1%} 벌어져 "
                         f"계절성을 믿기 어렵습니다(허용 {tol:.0%})")
        return even, "균등", why

    med = {}
    for q in (1, 2, 3, 4):
        vals = sorted(r[q] for r in rows)
        n = len(vals)
        med[q] = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    tot = sum(med.values())
    if tot <= 0:
        why["reason"] = "비중 합이 0 이하입니다"
        return even, "균등", why
    w = {q: med[q] / tot for q in (1, 2, 3, 4)}
    why["weights"] = {q: round(v, 4) for q, v in w.items()}
    return w, "계절성", why


def fill_estimates(future_ends: list[str], est: dict, fy_ends: list[str],
                   known: dict[str, float]) -> dict[str, dict]:
    """미발표 분기의 EPS 를 컨센으로 채운다.

    야후가 주는 건 분기 둘(0q·+1q)과 연간 둘(0y·+1y)이다. 분기 둘은 그대로
    쓰고, 나머지는 연간에서 **이미 아는 분기를 빼고** 남은 분기 수로 나눈다.
    연간 추정에는 이미 발표된 분기가 들어 있으므로 그걸 빼야 남은 분기의
    기대치가 된다. 그냥 연간÷4 로 하면 계절성이 큰 회사가 크게 틀어진다.

    ``known`` 은 기준일 → 확정 EPS. ``fy_ends`` 는 회계연도 마지막 기준일들
    (EDGAR 연간 사실에서 온 실제 날짜 + 앞으로 두 해).
    """
    out: dict[str, dict] = {}
    for key, end in (("0q", future_ends[0] if future_ends else None),
                     ("+1q", future_ends[1] if len(future_ends) > 1 else None)):
        v = (est or {}).get(key)
        if end and v is not None:
            out[end] = {"val": float(v), "source": f"컨센 {key}"}

    bounds = sorted(x for x in (_d(e) for e in fy_ends or []) if x)
    w, mode, why = seasonal_weights(known, fy_ends)
    for key in ("0y", "+1y"):
        total = (est or {}).get(key)
        if total is None:
            continue
        fy_end = _fy_for(key, bounds, _d(future_ends[0]) if future_ends else None)
        if fy_end is None:
            continue
        lo = add_months(fy_end, -12)
        mine = [e for e in future_ends if lo < _d(e) <= fy_end]
        if not mine:
            continue
        booked = sum(v for e, v in known.items() if lo < _d(e) <= fy_end)
        booked += sum(r["val"] for e, r in out.items() if lo < _d(e) <= fy_end)
        rest = [e for e in mine if e not in out]
        if not rest:
            continue
        residual = float(total) - booked
        if residual <= 0:
            # 이미 확정·배정된 분기 합이 연간 추정을 넘었다. 음수를 지어내지
            # 않고 비워 둔다 — 화면에서 그 이유를 보여 준다.
            for e in rest:
                out[e] = {"val": None, "source": f"컨센 {key}",
                          "note": "이미 확정된 분기 합이 연간 추정을 넘었습니다"}
            continue
        # ÷남은분기 대신 **계절성 비중**으로 나눈다.
        share = {e: w.get(_fq_pos(e, fy_end.isoformat()) or 0, 0.25) for e in rest}
        denom = sum(share.values()) or 1.0
        for e in rest:
            out[e] = {"val": residual * share[e] / denom,
                      "source": f"컨센 {key} {mode} 배분",
                      "weight": round(share[e] / denom, 4), "mode": mode}
    return out


def _fy_for(key: str, bounds: list[date], first_future: date | None) -> date | None:
    """'0y' 는 **첫 미발표 분기가 속한** 회계연도, '+1y' 는 그다음.

    야후의 '0y'(Current Year)가 가리키는 게 그것이다. 마지막 발표 분기가
    속한 해가 아니다 — 4분기를 막 발표했다면 0y 는 이미 다음 회계연도다.
    """
    if not bounds or first_future is None:
        return None
    future = [b for b in bounds if b >= first_future]
    if not future:
        return None
    return future[0] if key == "0y" else (future[1] if len(future) > 1 else None)


# --- 창 만들기 --------------------------------------------------------------
def forward_windows(quarters: list[dict], estimated: dict[str, dict],
                    horizon: int = HORIZON) -> list[dict]:
    """발표 시점마다 '앞으로 4개 분기' 창을 만든다.

    i 번째 분기가 발표된 순간 시장이 아는 마지막 실적은 i 다. 그러니 그 시점의
    forward 12개월은 i+1 … i+4 이다. 창은 다음 발표일 직전까지 유효하다.
    """
    qs = sorted(quarters, key=lambda r: r["end"])
    vals = {q["end"]: q for q in qs}
    ends = [q["end"] for q in qs] + sorted(estimated)
    out = []
    for i, q in enumerate(qs):
        opens = q.get("announced")
        if not opens:
            continue
        fwd = ends[i + 1:i + 1 + horizon]
        if len(fwd) < horizon:
            continue
        rows, n_est, ok = [], 0, True
        for e in fwd:
            if e in vals:
                v = vals[e].get("val")
                rows.append({"end": e, "val": v, "estimated": False})
            elif e in estimated:
                v = estimated[e]["val"]
                n_est += 1
                rows.append({"end": e, "val": v,
                             "estimated": True, "source": estimated[e]["source"]})
            else:
                ok = False
                break
            if v is None:
                ok = False
                break
        if not ok:
            continue
        nxt = qs[i + 1].get("announced") if i + 1 < len(qs) else None
        out.append({
            "from": opens, "to": nxt,
            "basis_end": q["end"],
            "announced_source": q.get("announced_source"),
            "eps": round(sum(r["val"] for r in rows), 6),
            "estimated": n_est,
            "confirmed": n_est == 0,
            "quarters": rows,
        })
    return out


def per_series(dates: list[str], closes: list[float], windows: list[dict]) -> list[dict]:
    """주가 계열에 창을 붙여 PER 을 만든다.

    EPS 합이 0 이하면 PER 을 내지 않는다(``None``). 적자 구간의 PER 은 음수로
    나와 그리면 차트를 망가뜨리고, 읽는 사람을 속인다.
    """
    if not windows:
        return []
    wins = sorted(windows, key=lambda w: w["from"])
    out, wi = [], -1
    for d, c in zip(dates, closes):
        while wi + 1 < len(wins) and wins[wi + 1]["from"] <= d:
            wi += 1
        if wi < 0:
            out.append({"date": d, "close": c, "per": None})
            continue
        w = wins[wi]
        if w["to"] and d >= w["to"]:
            out.append({"date": d, "close": c, "per": None})
            continue
        eps = w["eps"]
        out.append({"date": d, "close": c,
                    "per": round(c / eps, 3) if eps and eps > 0 else None,
                    "confirmed": w["confirmed"],
                    "basis_end": w["basis_end"], "announced": w["from"]})
    return out
