"""In-Base health score + base-type tag — surface "still quietly basing" names.

The main total_score rewards trend + RS, so already-extended momentum names float
to the top. This adds an ORTHOGONAL 0–100 "In-Base" score that instead rewards a
setup that is *tight, quiet, on rising support and NOT yet extended* — i.e. still
inside a constructive base before the breakout. Extended names are not hidden;
they just score low here (strict extension penalty).

Also tags a rough base archetype: flat / tight / abc (corrective bottom) / base.

All pure functions over a screener record (+ a bar-level helper), so unit-testable.
"""

from __future__ import annotations

import numpy as np


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _ret(close, n):
    if len(close) > n and close[-1 - n]:
        return round(close[-1] / close[-1 - n] - 1.0, 4)
    return None


def _range_pct(high, low, n, price):
    if len(high) < n or len(low) < n or not price:
        return None
    seg_h = np.asarray(high[-n:], dtype=float)
    seg_l = np.asarray(low[-n:], dtype=float)
    hi = float(seg_h[np.isfinite(seg_h)].max()) if seg_h.size else None
    lo = float(seg_l[np.isfinite(seg_l)].min()) if seg_l.size else None
    if hi is None or lo is None or price <= 0:
        return None
    return round((hi - lo) / price, 4)


def short_term_metrics(close, high, low, base: dict) -> dict:
    """Bar-level extras the In-Base score needs (merged onto the record)."""
    price = close[-1] if close else None
    bh, bl = base.get("base_high"), base.get("base_low")
    base_pos = None
    if price and bh and bl and bh > bl:
        base_pos = round((price - bl) / (bh - bl), 4)
    return {
        "ret_5d": _ret(close, 5),
        "ret_10d": _ret(close, 10),
        "ret_21d": _ret(close, 21),
        "recent_range_10": _range_pct(high, low, 10, price),
        "recent_range_15": _range_pct(high, low, 15, price),
        "base_position": base_pos,   # 0 = at base low, 1 = at base high
    }


# --------------------------------------------------------------------------- #
# Extension (strict) — how far the name has already "popped"
# --------------------------------------------------------------------------- #
def _not_extended(rec: dict, ic: dict) -> tuple[float, list[str]]:
    """Return (not_extended factor 0..1, human-readable extension flags)."""
    flags: list[str] = []
    ne = 1.0
    price = rec.get("current_price")
    sma50 = rec.get("sma50")
    r5, r10 = rec.get("ret_5d"), rec.get("ret_10d")
    status = (rec.get("pivot") or {}).get("pivot_status")
    bpos = rec.get("base_position")

    if sma50 and price and price / sma50 > float(ic["sma50_stretch"]):
        ne -= 0.5
        flags.append(f"50일선 +{round((price / sma50 - 1) * 100)}%")
    if r10 is not None and r10 > float(ic["max_ret_10d"]):
        ne -= 0.4
        flags.append(f"10일 +{round(r10 * 100)}%")
    if r5 is not None and r5 > float(ic["max_ret_5d"]):
        ne -= 0.3
        flags.append(f"5일 +{round(r5 * 100)}%")
    if status in ("broken_out", "extended"):
        ne -= 0.6
        flags.append("피봇 돌파/과열")
    if bpos is not None and bpos > 0.92 and (r10 or 0) > 0.08:
        ne -= 0.3
        flags.append("베이스 상단 급등")
    return _clamp(ne), flags


def _tightness(rec: dict, ic: dict) -> float:
    t = 0.0
    rr = rec.get("recent_range_10")
    if rr is not None:
        if rr <= float(ic["tight_range"]):
            t += 0.4
        elif rr <= float(ic["tight_range"]) * 1.6:
            t += 0.2
    t += 0.3 * float((rec.get("vcp") or {}).get("vcp_score") or 0.0)
    vol = rec.get("volatility") or {}
    if vol.get("volatility_contraction_grade") == "excellent":
        t += 0.2
    elif vol.get("volatility_contraction_pass"):
        t += 0.1
    if vol.get("recent_atr_compression_pass"):
        t += 0.1
    return _clamp(t)


def _volume(rec: dict) -> float:
    vd = rec.get("volume") or {}
    f = 0.0
    if vd.get("volume_dry_up_excellent"):
        f += 0.6
    elif vd.get("volume_dry_up_pass"):
        f += 0.4
    if (vd.get("high_volume_down_days_20d") or 0) < 2:
        f += 0.2
    ad = vd.get("accumulation_distribution_score")
    if ad is not None:
        f += 0.2 * _clamp((ad + 1) / 2)
    return _clamp(f)


def _support(rec: dict) -> float:
    s = 0.0
    if rec.get("sma50_position_pass"):
        s += 0.4
    s50, s150, s200 = rec.get("sma50"), rec.get("sma150"), rec.get("sma200")
    if s50 and s150 and s200 and s50 > s150 > s200:
        s += 0.35
    if s200 and rec.get("sma200_20d_ago") and s200 > rec["sma200_20d_ago"]:
        s += 0.25
    return _clamp(s)


def _structure(rec: dict, ic: dict) -> float:
    b = rec.get("base") or {}
    st = 0.0
    L = b.get("base_length_days")
    if L and L >= int(ic["min_len"]):
        st += 0.3
    st += {"excellent": 0.3, "good": 0.25, "caution": 0.1}.get(b.get("base_depth_grade"), 0.0)
    if b.get("higher_low"):
        st += 0.2
    bpos = rec.get("base_position")
    if bpos is not None and bpos <= 0.85:
        st += 0.2
    return _clamp(st)


def _base_type(rec: dict, bt: dict) -> str:
    b = rec.get("base") or {}
    if not b.get("base_detected"):
        return "none"
    depth = b.get("base_depth")
    L = b.get("base_length_days")
    rr = rec.get("recent_range_10")
    hl = b.get("higher_low")
    # order matters: corrective (deep + rising lows) first, then tight, then flat.
    if depth is not None and depth >= float(bt["abc_min_depth"]) and hl:
        return "abc"
    if (L and L <= int(bt["tight_max_len"]) and depth is not None
            and depth < float(bt["tight_max_depth"])
            and rr is not None and rr <= float(bt["tight_max_range"])):
        return "tight"
    if L and L >= int(bt["flat_min_len"]) and depth is not None and depth < float(bt["flat_max_depth"]):
        return "flat"
    return "base"


def compute(rec: dict, cfg: dict) -> None:
    """Attach inbase_score, inbase_grade, base_type, extended, extension_flags."""
    ic = cfg["inbase"]
    w = ic["weights"]
    ne, flags = _not_extended(rec, ic)
    parts = {
        "not_extended": ne,
        "tightness": _tightness(rec, ic),
        "volume": _volume(rec),
        "support": _support(rec),
        "structure": _structure(rec, ic),
    }
    score = sum(parts[k] * float(w[k]) for k in parts)
    rec["inbase_score"] = round(score, 1)
    rec["inbase_parts"] = {k: round(v, 3) for k, v in parts.items()}
    rec["extended"] = bool(ne < float(ic.get("extended_cutoff", 0.5)))
    rec["extension_flags"] = flags
    rec["base_type"] = _base_type(rec, cfg["base_type"])
    cut = ic.get("grades", {"prime": 80, "high": 65, "watch": 50})
    rec["inbase_grade"] = (
        "prime" if score >= cut["prime"] else
        "high" if score >= cut["high"] else
        "watch" if score >= cut["watch"] else "low"
    )
