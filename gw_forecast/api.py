"""
Step 8 - HTTP service. Node.js fetches IMD, then POSTs rain + any newer well readings here.

  uvicorn api:app --port 8000

  GET  /health
  GET  /v1/model-info                          training/validation metrics
  GET  /v1/wells/nearby?lat&lon&k&radius_km    which wells serve a location (+ their district/block/village)
  POST /v1/forecast                            *** lat/lon -> point report + trend + recognised area + area roll-up
  GET  /v1/forecast/quick?lat&lon              same, without IMD rain / new readings (testing; flagged NO_RECENT_RAIN_INPUT)
  POST /v1/forecast/area                       a named district (and optional block) roll-up
  POST /v1/forecast/well/{well_id}             single well
"""
import json
from contextlib import asynccontextmanager
from datetime import date
from typing import Optional
import numpy as np
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from config import CFG
from features import from_day
from predict import Forecaster
from scoring import advice, label

S = {}
AREA_MAX_WELLS = 40


@asynccontextmanager
async def lifespan(app):
    S["fc"] = Forecaster()
    yield


app = FastAPI(title="Groundwater Forecast Service", version="2.1", lifespan=lifespan)


class RainDay(BaseModel):
    date: str
    mm: float = Field(ge=0, le=CFG.rain_max_mm)


class Reading(BaseModel):
    date: str
    depth_mbgl: float


class Req(BaseModel):
    lat: Optional[float] = None
    lon: Optional[float] = None
    district: Optional[str] = None                     # for /v1/forecast/area
    block: Optional[str] = None
    as_of: Optional[str] = None                        # default: today
    radius_km: float = 40
    k: int = Field(3, ge=1, le=8)
    horizons: list[int] = Field([30, 60, 90], max_length=8)    # days ahead, each 7..200; use e.g. [15,30,45,60,75,90] for a smoother trend
    include_area: bool = True
    rain: Optional[list[RainDay]] = None               # OBSERVED daily rain (IMD), ideally last >=180 days; omit missing days
    rain_forecast_5d_mm: Optional[float] = None
    recent_levels: Optional[dict[str, list[Reading]]] = None   # newer readings per well_id than the training data


def _hz(r):
    if any(h < 7 or h > CFG.max_h for h in r.horizons):
        raise HTTPException(422, f"each horizon must be 7..{CFG.max_h} days")
    return tuple(sorted(set(r.horizons)))


def _one(wi, r: Req):
    fc = S["fc"]
    wid = fc.wells.well_id[wi]
    extra = [(x.date, x.depth_mbgl) for x in (r.recent_levels or {}).get(wid, [])]
    rain = [(x.date, x.mm) for x in r.rain] if r.rain else None
    return fc.report(wi, r.as_of or str(date.today()), rain, extra, r.rain_forecast_5d_mm, _hz(r))


def _count(o):
    cnt = {}
    for x in o:
        for q in set(x["reasons"]):
            cnt[q] = cnt.get(q, 0) + 1
    return cnt


def _reliability(reps):
    """HIGH: newest reading <=120 d old AND rain supplied.  MEDIUM: <= max_h (200 d).  LOW: older (model is extrapolating)."""
    best = min(x["staleness_days"] for x in reps)
    first = next(iter(reps[0]["outlook"].values()))
    rain_ok = "NO_RECENT_RAIN_INPUT" not in first["reasons"]
    notes = []
    if best > CFG.max_h:
        notes.append(f"newest reading is {best} days old; the model was trained for gaps up to {CFG.max_h} days")
    if not rain_ok:
        notes.append("no usable recent rainfall input")
    level = "HIGH" if (best <= 120 and rain_ok) else "MEDIUM" if best <= CFG.max_h else "LOW"
    return {"level": level, "newest_reading_age_days": best, "rain_input_used": rain_ok, "notes": notes}


def _blend(reps, w):
    w = np.array(w, float) / np.sum(w)
    out, series = {}, []
    for h in reps[0]["outlook"]:
        o = [x["outlook"][h] for x in reps]
        avg = lambda f: float(sum(wi * f(oi) for wi, oi in zip(w, o)))
        score = avg(lambda x: x["gw_score"])
        uc = {k: avg(lambda x: x["use_case"][k]["score"]) for k in o[0]["use_case"]}
        out[h] = {"horizon_days": int(h), "target_date": o[0]["target_date"], "gw_score": round(score, 1), "gw_status": label(score),
                  "depth_mbgl": {k: round(avg(lambda x: x["depth_mbgl"][k]), 2) for k in ("p10", "p50", "p90")},
                  "use_case": {k: {"score": round(v, 1), "advice": advice(v)} for k, v in uc.items()},
                  "confidence": round(avg(lambda x: x["confidence"]), 2),
                  "reasons": sorted(q for q, c in _count(o).items() if c >= (len(o) + 1) // 2),
                  "reason_share": {q: round(c / len(o), 2) for q, c in sorted(_count(o).items())}}
    for k in range(len(reps[0]["trend"]["series"])):
        pts = [x["trend"]["series"][k] for x in reps]
        sm = [(wi, p["seasonal_median"]) for wi, p in zip(w, pts) if p["seasonal_median"] is not None]
        series.append({"days": pts[0]["days"], "target_date": pts[0]["target_date"],
                       **{q: round(float(sum(wi * p[q] for wi, p in zip(w, pts))), 2) for q in ("p10", "p50", "p90")},
                       "seasonal_median": round(sum(a * b for a, b in sm) / sum(a for a, _ in sm), 2) if sm else None})
    return out, Forecaster.trend_summary(series)


def _rollup(wis, r, label_):
    """Equal-weight roll-up over wells of one administrative area (nearest AREA_MAX_WELLS to the query point if lat/lon given)."""
    fc = S["fc"]
    if r.lat is not None:
        from features import haversine
        d = haversine(r.lat, r.lon, fc.wells.lat.values[wis], fc.wells.lon.values[wis])
        wis = wis[np.argsort(d)]
    reps, skipped = [], 0
    for wi in wis[:AREA_MAX_WELLS]:
        try:
            rep = _one(wi, r)
        except ValueError:
            continue
        if rep["staleness_days"] > CFG.max_usable_stale_days:
            skipped += 1
            continue
        reps.append(rep)
    if not reps:
        return None
    outlook, trend = _blend(reps, [1] * len(reps))
    h_last = str(max(int(h) for h in outlook))
    sc = sorted(reps, key=lambda x: x["outlook"][h_last]["gw_score"])
    return {"area": label_, "n_wells_used": len(reps), "n_wells_in_area": int(len(wis)), "n_wells_skipped_too_stale": skipped,
            "reliability": _reliability(reps), "outlook": outlook, "trend": trend,
            "worst_well": {"well_id": sc[0]["well_id"], "score": sc[0]["outlook"][h_last]["gw_score"], "village": sc[0]["location"].get("village")},
            "best_well": {"well_id": sc[-1]["well_id"], "score": sc[-1]["outlook"][h_last]["gw_score"], "village": sc[-1]["location"].get("village")},
            "spread_of_scores": round(sc[-1]["outlook"][h_last]["gw_score"] - sc[0]["outlook"][h_last]["gw_score"], 1),
            "data_stale": all(x["data_stale"] for x in reps)}


@app.get("/health")
def health():
    return {"ok": True, "wells": len(S["fc"].wells)}


@app.get("/v1/model-info")
def info():
    d = {}
    for f in ("metrics_eval.json", "metrics_telemetry.json"):
        p = CFG.art_dir / f
        if p.exists():
            d[f.split(".")[0]] = json.load(open(p))
    d["trained"] = {k: S["fc"].sc[k] for k in ("mode", "train_cutoff_day")}
    d["trained"]["train_cutoff_date"] = str(from_day(S["fc"].sc["train_cutoff_day"]))
    return d


@app.get("/v1/wells/nearby")
def nearby(lat: float, lon: float, k: int = Query(3, ge=1, le=10), radius_km: float = 40):
    fc = S["fc"]
    res = []
    for wi, d in fc.nearby(lat, lon, k, radius_km):
        w = fc.wells.iloc[wi]
        res.append({"well_id": w.well_id, "distance_km": round(d, 1), "last_stored_reading": str(from_day(max(fc.obs[w.well_id]))),
                    "district": w.district, "block": w.block, "village": w.village})
    return res


def _point(r: Req):
    if r.lat is None or r.lon is None:
        raise HTTPException(422, "lat and lon are required")
    fc = S["fc"]
    cands = fc.nearby(r.lat, r.lon, r.k * 5, r.radius_km)           # look past wells whose data is too old
    if not cands:
        raise HTTPException(404, f"no monitoring well within {r.radius_km} km")
    n0 = fc.wells.iloc[cands[0][0]]                                  # administrative names come from the NEAREST well (no boundary polygons)
    area_names = {"state": n0.state, "district": n0.district, "block": n0.block, "village": n0.village,
                  "from_well": n0.well_id, "distance_km": round(cands[0][1], 1),
                  "note": "names are those of the nearest monitoring well; near borders the true administrative area may differ"}
    reps, ws, used, skipped = [], [], [], []
    for wi, d in cands:
        if len(reps) >= r.k:
            break
        try:
            rep = _one(wi, r)
        except ValueError:
            continue
        if rep["staleness_days"] > CFG.max_usable_stale_days:
            skipped.append({"well_id": rep["well_id"], "distance_km": round(d, 1), "village": rep["location"].get("village"),
                            "last_reading_date": rep["last_reading"]["date"], "staleness_days": rep["staleness_days"]})
            continue
        reps.append(rep); ws.append(1 / max(d, 1.0) ** 2)
        used.append({"well_id": rep["well_id"], "distance_km": round(d, 1), "location": rep["location"],
                     "last_reading": rep["last_reading"], "staleness_days": rep["staleness_days"],
                     "long_term_trend_m_per_year": rep["long_term_trend_m_per_year"]})
    base = {"query": {"lat": r.lat, "lon": r.lon, "as_of": r.as_of or str(date.today())}, "recognized_area": area_names,
            "skipped_wells_too_stale": skipped[:10]}
    if not reps:
        return {"status": "INSUFFICIENT_RECENT_DATA", **base,
                "message": f"No nearby well has a reading newer than {CFG.max_usable_stale_days} days. Send newer readings in "
                           f"recent_levels for these wells (or widen radius_km).", "outlook": None, "trend": None, "area_report": None}
    outlook, trend = _blend(reps, ws)
    res = {"status": "OK", **base, "reliability": _reliability(reps), "wells_used": used,
           "data_stale": all(x["data_stale"] for x in reps), "outlook": outlook, "trend": trend}
    if r.include_area:
        nb = fc.area_wells(n0.district, n0.block)
        use_block = bool(n0.block) and len(nb) >= 3
        aw = nb if use_block else fc.area_wells(n0.district)
        if len(aw):
            res["area_report"] = _rollup(aw, r, {"level": "block" if use_block else "district", "district": n0.district,
                                                 **({"block": n0.block} if use_block else {})})
    return res


@app.post("/v1/forecast")
def forecast(r: Req):
    return _point(r)


@app.get("/v1/forecast/quick")
def quick(lat: float, lon: float, radius_km: float = 40):
    return _point(Req(lat=lat, lon=lon, radius_km=radius_km, horizons=[15, 30, 45, 60, 75, 90]))


@app.post("/v1/forecast/area")
def forecast_area(r: Req):
    if not r.district:
        raise HTTPException(422, "district is required")
    wis = S["fc"].area_wells(r.district, r.block)
    if len(wis) == 0:
        raise HTTPException(404, "no wells for that district/block")
    res = _rollup(wis, r, {"level": "block" if r.block else "district", "district": r.district, "block": r.block})
    if res is None:
        raise HTTPException(422, "wells in that area have too little history")
    return res


@app.post("/v1/forecast/well/{well_id}")
def forecast_well(well_id: str, r: Req):
    wi = S["fc"].idx.get(well_id)
    if wi is None:
        raise HTTPException(404, "unknown well_id")
    try:
        return _one(wi, r)
    except ValueError as e:
        raise HTTPException(422, str(e))