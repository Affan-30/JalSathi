"""
Step 6 - forecast -> scores + machine-readable reason codes for your NLP layer.

Depth = metres below ground level (BIGGER = deeper = WORSE).  Four components, each 0-100 (higher = better):
  A50  suitability of the forecast median depth           (depth curve in config.py)
  A90  suitability of the pessimistic P90 depth           (uncertainty is penalised, not hidden)
  R    forecast vs THIS well's own same-season history     (needs >= 8 same-season readings, else omitted)
  T    long-term trend of this well, last ~15 yrs (m/yr)   (needs >= 8 years, else omitted)
A missing component is left OUT and the other weights are re-normalised - nothing is filled with a default.
Weights, caps and thresholds are policy choices: agree them with a hydrogeologist before publishing warnings.
"""
import numpy as np
from config import CFG

_X, _Y = zip(*CFG.depth_curve)
USE = {  # weights over (A50, A90, R, T) + caps [(if P90 depth > X metres, cap score at Y)]
    "overall": dict(w=(0.35, 0.20, 0.25, 0.20), caps=[]),
    "irrigation": dict(w=(0.35, 0.25, 0.20, 0.20), caps=[(25, 35)]),
    "industry": dict(w=(0.25, 0.25, 0.30, 0.20), caps=[(20, 40)]),
    "borewell": dict(w=(0.25, 0.45, 0.10, 0.20), caps=[(35, 25)]),
}


def depth_score(d):
    return float(np.interp(d, _X, _Y))


def label(s):
    return "GOOD" if s >= 75 else "MODERATE" if s >= 55 else "STRESSED" if s >= 35 else "CRITICAL"


def advice(s):
    return "RECOMMENDED" if s >= 65 else "CAUTION" if s >= 40 else "NOT_RECOMMENDED"


def _wmean(weights, comp):
    pairs = [(w, c) for w, c in zip(weights, comp) if c is not None]
    return sum(w * c for w, c in pairs) / sum(w for w, _ in pairs)


def score_horizon(h, elapsed_days, last, q, hist_season, lt_slope, stale, has_rain):
    p10, p50, p90 = q["p10"], q["p50"], q["p90"]
    R = None
    if hist_season is not None and len(hist_season) >= 8:
        R = float(100 * (1 - (hist_season < p50).mean()))
    T = None if lt_slope is None else float(50 - 50 * np.tanh(lt_slope / 0.5))
    comp = (depth_score(p50), depth_score(p90), R, T)
    out = {}
    for name, cfg in USE.items():
        s = _wmean(cfg["w"], comp)
        for lim, cap in cfg["caps"]:
            if p90 > lim:
                s = min(s, cap)
        out[name] = round(float(s), 1)
    shallow_safety = 100 * np.clip((p10 - 0.5) / 3.5, 0, 1)              # construction fears a HIGH water table
    out["construction"] = round(float(0.7 * shallow_safety + 0.3 * comp[0]), 1)

    slope = (p50 - last) / (max(elapsed_days, 1) / 30.0)                 # informational; seasonal swings dominate it
    conf = float(1 / (1 + (p90 - p10) / 3.0)) * (CFG.stale_conf_factor if stale else 1.0)
    r = []
    r += ["VERY_DEEP_WATER_TABLE"] if p50 >= 25 else ["DEEP_WATER_TABLE"] if p50 >= 15 else []
    r += (["SHALLOW_WATER_TABLE"] if p10 >= 1.5 else ["VERY_SHALLOW_WATER_TABLE"]) if p10 < 3 else []
    if R is not None:
        r += ["WORSE_THAN_SEASONAL_NORM"] if R < 25 else ["BETTER_THAN_SEASONAL_NORM"] if R > 75 else []
    if lt_slope is not None:
        r += ["LONG_TERM_DECLINE"] if lt_slope > 0.3 else ["LONG_TERM_RECOVERY"] if lt_slope < -0.2 else []
    r += ["HIGH_UNCERTAINTY"] if conf < 0.4 else []
    r += ["STALE_DATA"] if stale else []
    r += [] if has_rain else ["NO_RECENT_RAIN_INPUT"]
    return {"horizon_days": h, "depth_mbgl": {k: round(float(v), 2) for k, v in q.items()},
            "change_since_last_reading_m_per_month": round(float(slope), 2),
            "components": {k: (None if v is None else round(float(v), 1)) for k, v in zip(("A50", "A90", "R", "T"), comp)},
            "gw_score": out["overall"], "gw_status": label(out["overall"]),
            "use_case": {k: {"score": v, "advice": advice(v)} for k, v in out.items() if k != "overall"},
            "confidence": round(conf, 2), "reasons": r}
