"""Turn a fully-computed record into weighted sub-scores, a total and alerts.

Each sub-score is computed as a 0..1 fraction of "how good is this dimension",
then multiplied by its configured weight, so changing the weights in config.yaml
re-scales everything consistently (total is always out of the weight sum, 100 by
default). Missing/NaN inputs contribute 0 to that dimension, never a crash.
"""

from __future__ import annotations


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _trend_frac(rec: dict) -> float:
    tt = rec.get("trend") or {}
    total = tt.get("total") or 10
    return _clamp((tt.get("pass_count") or 0) / total)


def _rs_frac(rec: dict) -> float:
    rp = rec.get("rs_percentile")
    if rp is None:
        core = 0.0
    elif rp >= 90:
        core = 1.0
    elif rp >= 80:
        core = 0.6 + 0.4 * (rp - 80) / 10.0
    else:
        core = 0.6 * (rp / 80.0)
    bonus = 0.0
    if rec.get("rs_line_spy_near_high"):
        bonus += 0.34
    if rec.get("rs_line_qqq_near_high"):
        bonus += 0.33
    if (rec.get("rs_vs_spy_3m") or 0) > 0 and (rec.get("rs_vs_qqq_3m") or 0) > 0:
        bonus += 0.33
    return _clamp(0.7 * core + 0.3 * bonus)


def _base_frac(rec: dict, cfg: dict) -> float:
    base = rec.get("base") or {}
    pivot = rec.get("pivot") or {}
    frac = 0.0
    if base.get("base_detected"):
        frac += 0.20
    grade = base.get("base_depth_grade")
    frac += {"excellent": 0.25, "good": 0.18, "caution": 0.10}.get(grade, 0.0)
    dist = pivot.get("distance_to_pivot")
    ready = float(cfg["base"]["pivot_ready_threshold"])
    watch = float(cfg["base"]["pivot_watch_threshold"])
    status = pivot.get("pivot_status")
    if status == "broken_out":
        frac += 0.20
    elif dist is not None and 0 <= dist <= ready:
        frac += 0.25
    elif dist is not None and dist <= watch:
        frac += 0.15
    if rec.get("sma50_position_pass"):
        frac += 0.15
    if base.get("higher_low"):
        frac += 0.10
    L = base.get("base_length_days")
    if L and int(cfg["base"]["min_length_days"]) <= L <= int(cfg["base"]["max_length_days"]):
        frac += 0.05
    return _clamp(frac)


def _vcp_frac(rec: dict) -> float:
    vol = rec.get("volatility") or {}
    vcp = rec.get("vcp") or {}
    grade = vol.get("volatility_contraction_grade")
    if grade == "excellent":
        part = 0.50
    elif vol.get("volatility_contraction_pass"):
        part = 0.35
    else:
        part = 0.0
    part += (vcp.get("vcp_score") or 0.0) * 0.35
    if vol.get("recent_atr_compression_pass"):
        part += 0.15
    return _clamp(part)


def _volume_frac(rec: dict, cfg: dict) -> float:
    vd = rec.get("volume") or {}
    frac = 0.0
    if vd.get("volume_dry_up_excellent"):
        frac += 0.50
    elif vd.get("volume_dry_up_pass"):
        frac += 0.35
    if vd.get("base_volume_fade_pass"):
        frac += 0.20
    hv = vd.get("high_volume_down_days_20d")
    hv_max = int(cfg["volume"]["high_volume_down_days_max"])
    if hv is not None and hv < hv_max:
        frac += 0.20
    ad = vd.get("accumulation_distribution_score")
    if ad is not None:
        frac += 0.10 * _clamp((ad + 1) / 2)
    return _clamp(frac)


def compute_scores(rec: dict, cfg: dict) -> None:
    """Attach *_score, total_score, setup_grade, alert_type and notes to rec."""
    w = cfg["scoring"]
    trend = round(_trend_frac(rec) * w["trend_weight"], 1)
    rs = round(_rs_frac(rec) * w["rs_weight"], 1)
    base = round(_base_frac(rec, cfg) * w["base_weight"], 1)
    vcp = round(_vcp_frac(rec) * w["vcp_weight"], 1)
    volume = round(_volume_frac(rec, cfg) * w["volume_weight"], 1)
    sector = round((rec.get("sector_detail") or {}).get("sector_action_score", 0.5) * w["sector_weight"], 1)

    total = round(trend + rs + base + vcp + volume + sector, 1)
    rec["trend_score"] = trend
    rec["rs_score"] = rs
    rec["base_score"] = base
    rec["vcp_score"] = vcp
    rec["volume_score"] = volume
    rec["sector_score"] = sector
    rec["total_score"] = total
    rec["setup_grade"] = _grade(total, w)
    rec["alert_type"] = _alert(rec, cfg)
    rec["notes"] = _notes(rec)


def _grade(total: float, w: dict) -> str:
    if total >= w["grade_prime"]:
        return "Prime"
    if total >= w["grade_high"]:
        return "High"
    if total >= w["grade_watch"]:
        return "Watch"
    return "Low"


def _alert(rec: dict, cfg: dict) -> str:
    a = cfg["alerts"]
    pivot = rec.get("pivot") or {}
    vol = rec.get("volatility") or {}
    vd = rec.get("volume") or {}
    price = rec.get("current_price")
    pivot_price = pivot.get("pivot_price")
    sma50 = rec.get("sma50")
    total = rec.get("total_score", 0)
    dist = pivot.get("distance_to_pivot")

    if pivot.get("breakout_signal") and total >= a["breakout_min_score"]:
        return "breakout"
    if (
        total >= a["ready_min_score"]
        and dist is not None and 0 <= dist <= a["ready_max_distance_to_pivot"]
        and vd.get("volume_dry_up_pass")
        and vol.get("volatility_contraction_pass")
        and rec.get("rs_line_spy_near_high")
    ):
        return "ready"
    extended = (
        (pivot_price and price and price > pivot_price * a["extended_pivot_ratio"])
        or (sma50 and price and price > sma50 * a["extended_sma50_ratio"])
    )
    if extended:
        return "extended"
    return "none"


def _notes(rec: dict) -> str:
    tags = []
    base = rec.get("base") or {}
    pivot = rec.get("pivot") or {}
    vcp = rec.get("vcp") or {}
    vol = rec.get("volatility") or {}
    vd = rec.get("volume") or {}
    if base.get("base_depth") is not None:
        tags.append(f"베이스 {round(base['base_depth']*100)}%/{base.get('base_length_days')}d")
    if vcp.get("vcp_pattern_pass"):
        tags.append("VCP 3단축소")
    if vol.get("volatility_contraction_grade") == "excellent":
        tags.append("변동성 급축소")
    if vd.get("volume_dry_up_excellent"):
        tags.append("거래량 마름(우수)")
    elif vd.get("volume_dry_up_pass"):
        tags.append("거래량 마름")
    d = pivot.get("distance_to_pivot")
    if d is not None:
        tags.append(f"pivot {round(d*100,1)}%")
    if (vd.get("high_volume_down_days_20d") or 0) >= 2:
        tags.append("대량 하락일 주의")
    if rec.get("rs_line_spy_near_high"):
        tags.append("RS라인 신고가")
    return " · ".join(tags)
